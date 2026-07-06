"""Read-only source_ref to compact evidence backtrace.

This module resolves local source_refs into bounded compact evidence for model
consumption. It does not expose raw excerpts to frontends by default, does not
write memory/platform state, and does not synthesize an answer.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from src.raw_evidence_excerpt import _append_jsonl_obj_excerpt, _resolve_source_path
    from src.raw_text_decode import decode_text_bytes as _decode_text_bytes
except Exception:  # pragma: no cover - direct script import fallback
    from raw_evidence_excerpt import _append_jsonl_obj_excerpt, _resolve_source_path
    from raw_text_decode import decode_text_bytes as _decode_text_bytes


SOURCE_REF_COMPACT_EVIDENCE_CONTRACT = "source_ref_compact_evidence.v2026.6.21"
DEFAULT_COMPACT_EVIDENCE_CHARS = 720
MAX_COMPACT_EVIDENCE_CHARS = 1800
DEFAULT_FAST_SCAN_BYTES = 192 * 1024
MAX_FAST_SCAN_BYTES = 512 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def _bounded_text(value: Any, limit: int) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for term in re.findall(r"[\w\-.:\u4e00-\u9fff]+", str(query or "").lower()):
        cleaned = term.strip("._:-")
        if len(cleaned) >= 2 and cleaned not in terms:
            terms.append(cleaned)
    return terms


def _query_visible_text(value: Any, query: str, limit: int) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    terms = _query_terms(query)
    if not terms:
        return _bounded_text(text, limit)
    lower = text.lower()
    starts = {0}
    for term in terms:
        start = 0
        while True:
            index = lower.find(term, start)
            if index < 0:
                break
            starts.add(max(0, min(index - limit // 3, len(text) - limit)))
            starts.add(max(0, min(index - limit // 2, len(text) - limit)))
            start = index + max(len(term), 1)

    def score(offset: int) -> tuple[int, int, int]:
        window = lower[offset:offset + limit]
        matched = sum(1 for term in terms if term in window)
        density = sum(window.count(term) for term in terms)
        result_terms = 0
        if re.search(r"\b(verified|succeeds?|returns?|returned|exit=0)\b|返回|跑通|修复|对齐", window, flags=re.I):
            result_terms = 1
        return matched, density + result_terms, offset

    best = max(starts, key=score)
    excerpt = text[best:best + limit]
    if best > 0 and limit > 5:
        excerpt = "[...]" + excerpt[5:]
    if best + limit < len(text) and limit > 5:
        excerpt = excerpt[:-5] + "[...]"
    return excerpt


def _stable_ref(surface: dict[str, Any], source_refs: dict[str, Any], *, index: int) -> str:
    for key in ("evidence_ref", "source_id", "library_id", "ref_id"):
        value = _text(surface.get(key) or source_refs.get(key))
        if value:
            return value
    seed = "|".join(
        [
            _text(source_refs.get("source_system")),
            _text(source_refs.get("source_path")),
            ",".join(str(item) for item in _items(source_refs.get("msg_ids"))),
            str(index),
        ]
    )
    return "source-ref-" + hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except Exception:
        return False


def _resolve_source_path_for_fast_read(source_path: str, *, memcore_root: str = "") -> Path | None:
    if not _text(source_path):
        return None
    direct = Path(source_path).expanduser()
    root = _text(memcore_root)
    if direct.is_absolute() and root:
        root_path = Path(root).expanduser()
        memory_root = root_path / "memory"
        try:
            resolved = direct.resolve()
        except Exception:
            return None
        if resolved.exists() and (_is_path_inside(resolved, memory_root) or _is_path_inside(resolved, root_path / "output")):
            return resolved
        return None
    resolved = _resolve_source_path(source_path)
    return resolved if resolved and resolved.exists() else None


def _byte_offset_map(source_refs: dict[str, Any], msg_ids: list[str]) -> dict[str, dict[str, int]]:
    raw = source_refs.get("byte_offsets") or source_refs.get("line_offsets") or {}
    if not isinstance(raw, dict):
        return {}
    if "start" in raw and "end" in raw:
        try:
            start = int(raw.get("start"))
            end = int(raw.get("end"))
        except Exception:
            return {}
        if start >= 0 and end > start:
            return {(msg_ids[0] if msg_ids else "__offset__"): {"start": start, "end": end}}
        return {}
    wanted = set(msg_ids)
    offsets: dict[str, dict[str, int]] = {}
    for key, value in raw.items():
        msg_id = str(key or "")
        if wanted and msg_id not in wanted:
            continue
        if not isinstance(value, dict):
            continue
        try:
            start = int(value.get("start"))
            end = int(value.get("end"))
        except Exception:
            continue
        if start >= 0 and end > start:
            offsets[msg_id] = {"start": start, "end": end}
    return offsets


def _msg_ids_for_offset_read(msg_ids: list[str], offsets: dict[str, dict[str, int]]) -> list[str]:
    if list(offsets.keys()) == ["__offset__"]:
        return []
    return msg_ids


def _decode_jsonl_excerpt_from_bytes(
    data: bytes,
    msg_ids: list[str],
    excerpt_chars: int,
    *,
    query: str = "",
) -> tuple[str, str | None]:
    text = _decode_text_bytes(data)
    excerpt_parts: list[str] = []
    pending = set(str(mid) for mid in msg_ids if str(mid))
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        _append_jsonl_obj_excerpt(obj, msg_ids, excerpt_parts, pending)
        if not msg_ids and not excerpt_parts:
            _append_jsonl_obj_excerpt(obj, [], excerpt_parts)
        if excerpt_parts and ((msg_ids and not pending) or len(" | ".join(excerpt_parts)) >= excerpt_chars):
            break
    bounded = _query_visible_text(" | ".join(excerpt_parts), query, excerpt_chars)
    evidence_hash = hashlib.sha256(bounded.encode("utf-8")).hexdigest() if bounded else None
    return bounded, evidence_hash


def _read_by_byte_offsets(
    path: Path,
    offsets: dict[str, dict[str, int]],
    msg_ids: list[str],
    excerpt_chars: int,
    *,
    query: str = "",
) -> tuple[str, str, str | None]:
    if not offsets:
        return "", "offset_missing", None
    try:
        file_size = path.stat().st_size
    except Exception:
        return "", "offset_stat_error", None
    parts: list[bytes] = []
    ordered_ids = [msg_id for msg_id in msg_ids if msg_id in offsets] or list(offsets.keys())
    try:
        with path.open("rb") as handle:
            for msg_id in ordered_ids[:3]:
                pos = offsets.get(msg_id) or {}
                start = max(0, min(int(pos.get("start", 0)), file_size))
                end = max(start, min(int(pos.get("end", start)), file_size))
                if end <= start:
                    continue
                handle.seek(start)
                parts.append(handle.read(min(end - start, MAX_FAST_SCAN_BYTES)))
    except Exception:
        return "", "offset_read_error", None
    text, evidence_hash = _decode_jsonl_excerpt_from_bytes(
        b"\n".join(parts),
        msg_ids,
        excerpt_chars,
        query=query,
    )
    return text, ("raw_offset" if text else "offset_cache_miss"), evidence_hash


def _read_fast_jsonl_window(
    path: Path,
    msg_ids: list[str],
    excerpt_chars: int,
    *,
    query: str = "",
) -> tuple[str, str, str | None]:
    try:
        file_size = path.stat().st_size
    except Exception:
        return "", "source_stat_error", None
    if file_size <= 0:
        return "", "source_empty", None
    window = min(DEFAULT_FAST_SCAN_BYTES, MAX_FAST_SCAN_BYTES, file_size)
    try:
        with path.open("rb") as handle:
            if msg_ids:
                head = handle.read(window)
                handle.seek(max(0, file_size - window))
                tail = handle.read(window)
                text, evidence_hash = _decode_jsonl_excerpt_from_bytes(
                    head + b"\n" + tail,
                    msg_ids,
                    excerpt_chars,
                    query=query,
                )
                return text, ("raw_fast_window" if text else "fast_window_miss"), evidence_hash
            handle.seek(max(0, file_size - window))
            data = handle.read(window)
    except Exception:
        return "", "fast_window_read_error", None
    text, evidence_hash = _decode_jsonl_excerpt_from_bytes(data, msg_ids, excerpt_chars, query=query)
    return text, ("raw_fast_window" if text else "fast_window_miss"), evidence_hash


def _extract_fast_compact_evidence(
    source_path: str,
    msg_ids: list[str],
    excerpt_chars: int,
    source_refs: dict[str, Any],
    *,
    memcore_root: str = "",
    query: str = "",
) -> tuple[str, str, str | None]:
    resolved = _resolve_source_path_for_fast_read(source_path, memcore_root=memcore_root)
    if resolved is None:
        return "", "missing_source_path", None
    offsets = _byte_offset_map(source_refs, msg_ids)
    offset_msg_ids = _msg_ids_for_offset_read(msg_ids, offsets)
    offset_text, offset_status, offset_hash = _read_by_byte_offsets(
        resolved,
        offsets,
        offset_msg_ids,
        excerpt_chars,
        query=query,
    )
    if offset_text:
        return offset_text, offset_status, offset_hash
    return _read_fast_jsonl_window(resolved, msg_ids, excerpt_chars, query=query)


def source_refs_from_surface(surface: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return source refs without copying raw excerpts."""

    value = _dict(surface)
    nested = _dict(value.get("source_refs"))
    refs: dict[str, Any] = {}
    for key in (
        "source_system",
        "source_path",
        "session_id",
        "canonical_window_id",
        "source_refs_canonical_window_id",
        "project_id",
        "project_root",
        "workstream_id",
        "task_id",
        "raw_evidence_status",
        "artifact_type",
        "msg_ids",
        "byte_offsets",
        "line_offsets",
        "line_start",
        "line_end",
        "evidence_hash",
    ):
        value_for_key = nested.get(key) if key in nested else value.get(key)
        if value_for_key not in (None, "", [], {}):
            refs[key] = value_for_key
    return refs


def _surface_summary(surface: dict[str, Any]) -> str:
    return " | ".join(
        part
        for part in (
            _text(surface.get("title")),
            _text(surface.get("summary")),
            _text(surface.get("rank_reason")),
        )
        if part
    )


def build_compact_evidence_from_source_surface(
    surface: dict[str, Any],
    *,
    index: int = 1,
    excerpt_chars: int = DEFAULT_COMPACT_EVIDENCE_CHARS,
    memcore_root: str = "",
    query: str = "",
) -> dict[str, Any]:
    """Build one compact evidence item from a work_preflight source surface.

    The returned ``text`` is for the evidence-bound model packet. UI callers
    should use source refs/receipt fields and explicit raw expansion, not this
    as a default raw display.
    """

    surface = _dict(surface)
    source_refs = source_refs_from_surface(surface)
    excerpt_chars = _safe_int(excerpt_chars, DEFAULT_COMPACT_EVIDENCE_CHARS, 80, MAX_COMPACT_EVIDENCE_CHARS)
    source_path = _text(source_refs.get("source_path"))
    msg_ids = [str(item) for item in _items(source_refs.get("msg_ids")) if str(item)]
    precise_offsets = _byte_offset_map(source_refs, msg_ids)
    compact_surface = _surface_summary(surface)
    raw_excerpt = ""
    raw_status = "not_attempted"
    evidence_hash = _text(source_refs.get("evidence_hash"))
    source_exists = False
    if source_path:
        source_exists = _resolve_source_path_for_fast_read(source_path, memcore_root=memcore_root) is not None
    if source_path and source_exists and (msg_ids or precise_offsets):
        raw_excerpt, raw_status, raw_hash = _extract_fast_compact_evidence(
            source_path,
            msg_ids,
            excerpt_chars,
            source_refs,
            memcore_root=memcore_root,
            query=query,
        )
        if raw_hash:
            evidence_hash = raw_hash
    elif source_path and source_exists and not compact_surface:
        raw_excerpt, raw_status, raw_hash = _extract_fast_compact_evidence(
            source_path,
            [],
            excerpt_chars,
            source_refs,
            memcore_root=memcore_root,
            query=query,
        )
        if not raw_excerpt:
            raw_status = "source_anchor_without_precise_msg_or_offset"
        if raw_hash:
            evidence_hash = raw_hash
    elif source_path and source_exists:
        raw_status = "source_anchor_without_precise_msg_or_offset"
    else:
        raw_status = "missing_source_path"

    compact_text = _query_visible_text(raw_excerpt or compact_surface, query, excerpt_chars)
    evidence_ref = _stable_ref(surface, source_refs, index=index)
    library_id = _text(surface.get("library_id") or source_refs.get("library_id")) or evidence_ref
    has_raw_compact = bool(compact_text and raw_excerpt)
    has_surface_text = bool(compact_surface)
    return {
        "contract": SOURCE_REF_COMPACT_EVIDENCE_CONTRACT,
        "ok": bool(compact_text),
        "created_at": _now(),
        "read_only": True,
        "findings_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "raw_excerpt_exposed": False,
        "compact_evidence_for_model_only": True,
        "raw_authority_policy": "raw_source_text_is_highest_authority",
        "summary_policy": "summaries_are_navigation_not_source_replacement",
        "summary_may_replace_raw": False,
        "source_id": evidence_ref,
        "evidence_ref": evidence_ref,
        "library_id": library_id,
        "shelf": _text(surface.get("library_shelf") or surface.get("shelf")),
        "semantic_type": "source_ref_compact_evidence",
        "answer_bearing": "supporting_context" if has_raw_compact or has_surface_text else "candidate_only",
        "text": compact_text or f"work_preflight source anchor {index}",
        "matched_by": ",".join(str(item) for item in _items(surface.get("matched_by"))) or "work_preflight",
        "rank_reason": _text(surface.get("rank_reason")),
        "source_refs": source_refs,
        "raw_expand_available": bool(source_path),
        "raw_evidence_status": raw_status,
        "raw_excerpt_available_for_internal_model_context": has_raw_compact,
        "raw_excerpt_exposed_by_default": False,
        "compact_evidence_hash": evidence_hash
        or (hashlib.sha256(compact_text.encode("utf-8", errors="ignore")).hexdigest() if compact_text else ""),
        "limitations": [
            "compact_evidence_is_not_frontend_raw_excerpt",
            "source_refs_are_local_entry_evidence_not_platform_model_receipt",
            "summaries_are_navigation_not_source_replacement",
        ],
    }


def build_source_ref_compact_evidence_probe(
    surfaces: list[dict[str, Any]] | None = None,
    *,
    limit: int = 3,
    excerpt_chars: int = DEFAULT_COMPACT_EVIDENCE_CHARS,
    memcore_root: str = "",
    query: str = "",
) -> dict[str, Any]:
    items = [
        build_compact_evidence_from_source_surface(
            surface,
            index=index,
            excerpt_chars=excerpt_chars,
            memcore_root=memcore_root,
            query=query,
        )
        for index, surface in enumerate((surfaces or [])[: max(0, int(limit or 0))], start=1)
        if isinstance(surface, dict)
    ]
    return {
        "ok": any(bool(item.get("ok")) for item in items),
        "contract": SOURCE_REF_COMPACT_EVIDENCE_CONTRACT,
        "created_at": _now(),
        "read_only": True,
        "findings_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "raw_excerpt_exposed": False,
        "compact_evidence_for_model_only": True,
        "items_count": len(items),
        "answer_bearing_items_count": sum(1 for item in items if item.get("answer_bearing") == "supporting_context"),
        "raw_backtrace_hits_count": sum(1 for item in items if item.get("raw_excerpt_available_for_internal_model_context")),
        "items": items,
        "final_evidence_authority": "raw_source_refs",
    }


__all__ = [
    "SOURCE_REF_COMPACT_EVIDENCE_CONTRACT",
    "DEFAULT_COMPACT_EVIDENCE_CHARS",
    "MAX_COMPACT_EVIDENCE_CHARS",
    "source_refs_from_surface",
    "build_compact_evidence_from_source_surface",
    "build_source_ref_compact_evidence_probe",
]
