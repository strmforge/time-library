#!/usr/bin/env python3
"""Read-only raw session shallow indexes for reading-area lanes.

This module builds catalog records from already captured raw/source session
metadata. It does not distill, rewrite, or mutate raw records. Scope comes only
from borrowing-card self reports, never from technical project_id inference.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from src.source_system_taxonomy import canonical_reading_area_lane, source_system_aliases
    from src.source_system_runtime_declarations import (
        source_system_for_reading_area_raw_index,
        source_system_index_status_matches_reading_area_raw_index,
        source_system_reading_area_raw_index_source_ref_kind,
        source_system_uses_reading_area_raw_index,
    )
except Exception:  # pragma: no cover
    from source_system_taxonomy import canonical_reading_area_lane, source_system_aliases
    from source_system_runtime_declarations import (
        source_system_for_reading_area_raw_index,
        source_system_index_status_matches_reading_area_raw_index,
        source_system_reading_area_raw_index_source_ref_kind,
        source_system_uses_reading_area_raw_index,
    )


RAW_SESSION_INDEX_CONTRACT = "time_library_raw_session_shallow_index.v1"
RAW_SESSION_INDEX_RECORD_TYPE = "raw_session_shallow_index"
MIMOCODE_SOURCE_SYSTEM = source_system_for_reading_area_raw_index("declared_checkpoint_markdown") or "mimocode"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value: Any, *, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in ("", None):
        return []
    return [value]


def _string_list(value: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in _as_list(value):
        text = _clean(item, limit=200)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _records_db_default_path(root: str | Path | None = None) -> Path:
    if root:
        return Path(root).expanduser() / "output" / "records" / "records.db"
    env_root = os.environ.get("MEMCORE_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser() / "output" / "records" / "records.db"
    return Path("~/Library/Application Support/memcore-cloud/output/records/records.db").expanduser()


def _load_registry(path: str | Path | None = None) -> dict[str, Any]:
    try:
        from src.reading_area_registry import load_registry
    except Exception:  # pragma: no cover
        from reading_area_registry import load_registry

    return load_registry(path)


def _resolve_scope_values(scope_type: str, values: Any, registry: dict[str, Any]) -> set[str]:
    try:
        from src.reading_area_registry import resolve_scope_id
    except Exception:  # pragma: no cover
        from reading_area_registry import resolve_scope_id

    resolved: set[str] = set()
    for value in _string_list(values):
        scope_id = resolve_scope_id(scope_type, value, registry=registry)
        resolved.add(scope_id or value)
    return {item for item in resolved if item}


def _declared_cards(registry: dict[str, Any]) -> list[dict[str, Any]]:
    cards = []
    for card in (registry.get("borrowing_cards") or {}).values():
        if not isinstance(card, dict):
            continue
        if card.get("declared_project_ids") or card.get("declared_series_ids") or card.get("declared_reading_area_ids"):
            cards.append(card)
    return cards


def _card_identity_values(card: dict[str, Any]) -> list[str]:
    anchors = card.get("technical_anchors") if isinstance(card.get("technical_anchors"), dict) else {}
    return _string_list(
        [
            card.get("session_id"),
            card.get("canonical_window_id"),
            anchors.get("session_id"),
            anchors.get("canonical_window_id"),
            anchors.get("raw_artifact_id"),
            anchors.get("mimocode_session_id"),
        ]
    )


def _mimocode_root_default_path(root: str | Path | None = None) -> Path:
    if root:
        return Path(root).expanduser()
    env_root = os.environ.get("MEMCORE_MIMOCODE_ROOT", "").strip() or os.environ.get("MIMOCODE_HOME", "").strip()
    if env_root:
        return Path(env_root).expanduser()
    return Path("~/.local/share/mimocode").expanduser()


def _source_root_candidates(extra_allowed_roots: Any = None) -> list[Path]:
    roots: list[Path] = []
    for item in os.environ.get("MEMCORE_ALLOWED_SOURCE_ROOTS", "").split(os.pathsep):
        if item.strip():
            roots.append(Path(item.strip()).expanduser())
    env_root = os.environ.get("MEMCORE_ROOT", "").strip()
    if env_root:
        roots.append(Path(env_root).expanduser())
    roots.extend(
        [
            Path("~/Library/Application Support/memcore-cloud").expanduser(),
            Path("~/.codex/sessions").expanduser(),
            Path("~/.claude/projects").expanduser(),
            _mimocode_root_default_path(),
        ]
    )
    for item in _as_list(extra_allowed_roots):
        if item:
            roots.append(Path(item).expanduser())
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve(strict=False)
        except Exception:
            continue
        key = str(resolved)
        if key and key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def is_allowed_raw_source_path(source_path: str | Path, *, extra_allowed_roots: Any = None) -> bool:
    """Return True only for source files under known local memory roots.

    Reading-area lanes are read-only, but library_id pull still opens a local
    file for byte-offset evidence. Keep that read bounded to declared memory
    roots and test-provided fixture roots instead of trusting arbitrary
    source_refs.
    """

    if not source_path:
        return False
    try:
        source = Path(source_path).expanduser()
        if not source.is_absolute():
            return False
        resolved_source = source.resolve(strict=False)
    except Exception:
        return False
    for root in _source_root_candidates(extra_allowed_roots):
        try:
            if resolved_source == root or root in resolved_source.parents:
                return True
        except Exception:
            continue
    return False


def _scope_allowed(card: dict[str, Any], *, project_ids: set[str], series_ids: set[str]) -> bool:
    if project_ids and not (set(_string_list(card.get("declared_project_ids"))) & project_ids):
        return False
    if series_ids and not (set(_string_list(card.get("declared_series_ids"))) & series_ids):
        return False
    return True


def _session_rows_for_card(conn: sqlite3.Connection, card: dict[str, Any]) -> list[dict[str, Any]]:
    identities = _card_identity_values(card)
    if not identities:
        return []
    placeholders = ",".join("?" for _ in identities)
    rows = conn.execute(
        f"""
        select record_id, source_system, session_id, canonical_window_id,
               project_id, project_root, thread_name, source_path, raw_path,
               source_size_bytes, raw_size_bytes, source_line_count, raw_line_count,
               indexed_message_count, raw_offset_coverage_count, index_status,
               updated_at
        from canonical_sessions
        where session_id in ({placeholders})
           or canonical_window_id in ({placeholders})
           or raw_artifact_id in ({placeholders})
        order by updated_at desc
        """,
        (*identities, *identities, *identities),
    ).fetchall()
    columns = [
        "record_id",
        "source_system",
        "session_id",
        "canonical_window_id",
        "project_id",
        "project_root",
        "thread_name",
        "source_path",
        "raw_path",
        "source_size_bytes",
        "raw_size_bytes",
        "source_line_count",
        "raw_line_count",
        "indexed_message_count",
        "raw_offset_coverage_count",
        "index_status",
        "updated_at",
    ]
    return [dict(zip(columns, row)) for row in rows]


def _checkpoint_title(path: Path, fallback: str) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                if line.lower().startswith("topic:"):
                    return _clean(line.split(":", 1)[1], limit=80)
                if line.startswith("#"):
                    title = line.lstrip("#").strip()
                    if title and not title.lower().startswith("session checkpoint"):
                        return _clean(title, limit=80)
    except Exception:
        pass
    return _clean(fallback, limit=80)


def _mimocode_source_path_for_identity(mimocode_root: Path, identity: str) -> Path:
    root = mimocode_root.expanduser()
    checkpoint = root / "memory" / "sessions" / identity / "checkpoint.md"
    if checkpoint.exists():
        return checkpoint
    notes = root / "memory" / "sessions" / identity / "notes.md"
    if notes.exists():
        return notes
    diff = root / "storage" / "session_diff" / f"{identity}.json"
    if diff.exists():
        return diff
    return checkpoint


def _mimocode_session_rows_for_card(card: dict[str, Any], *, mimocode_root: str | Path | None = None) -> list[dict[str, Any]]:
    source = _clean(card.get("source_system") or card.get("consumer"), limit=80).lower().replace("-", "_")
    consumer = _clean(card.get("consumer"), limit=80).lower().replace("-", "_")
    if not source_system_uses_reading_area_raw_index(
        source,
        consumer=consumer,
        kind="declared_checkpoint_markdown",
    ):
        return []
    root = _mimocode_root_default_path(mimocode_root)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for identity in _card_identity_values(card):
        if not identity.startswith("ses_") or identity in seen:
            continue
        seen.add(identity)
        source_path = _mimocode_source_path_for_identity(root, identity)
        if not source_path.exists() or not source_path.is_file():
            continue
        size = source_path.stat().st_size
        rows.append(
            {
                "record_id": identity,
                "source_system": MIMOCODE_SOURCE_SYSTEM,
                "session_id": identity,
                "canonical_window_id": identity,
                "project_id": "",
                "project_root": "",
                "thread_name": _checkpoint_title(source_path, identity),
                "source_path": str(source_path),
                "raw_path": "",
                "source_size_bytes": size,
                "raw_size_bytes": 0,
                "source_line_count": 0,
                "raw_line_count": 0,
                "indexed_message_count": 0,
                "raw_offset_coverage_count": 0,
                "index_status": source_system_reading_area_raw_index_source_ref_kind(
                    MIMOCODE_SOURCE_SYSTEM,
                    "mimocode_checkpoint_source_path_fallback",
                ),
                "updated_at": datetime.fromtimestamp(source_path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    return rows


def _usable_thread_name(value: Any) -> str:
    thread_name = _clean(value, limit=80)
    if not thread_name:
        return ""
    if re.fullmatch(r"[0-9a-f-]{12,}", thread_name.lower()):
        return ""
    if thread_name.lower() in {"new chat", "untitled"}:
        return ""
    return thread_name


_CONTINUATION_SUMMARY_RE = re.compile(
    r"^(This session is being continued from a previous conversation|Summary:|"
    r"本会话从上一段|以下是上一段对话摘要)",
    re.IGNORECASE,
)
_BORING_USER_MESSAGE_RE = re.compile(
    r"^\s*(<environment_context>|# Instructions|# Selected text:|Files mentioned by the user:)",
    re.IGNORECASE,
)
_SOURCE_SLICE_MAX_BYTES = 4096


def _message_text_from_payload(payload_json: str, fallback: str = "") -> str:
    try:
        payload = json.loads(payload_json or "{}")
    except Exception:
        return _clean(fallback, limit=1200)
    source_line = payload.get("source_line") if isinstance(payload.get("source_line"), dict) else {}
    value = source_line.get("content")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return _clean(fallback, limit=1200)


def _exact_message_text_offsets(message: dict[str, Any], text: str) -> dict[str, Any]:
    source_path = _clean(message.get("source_path"), limit=1000)
    if not source_path or not text:
        return {}
    path = Path(source_path).expanduser()
    if not path.exists() or not path.is_file():
        return {}
    try:
        size = path.stat().st_size
    except OSError:
        return {}
    start_hint = int(message.get("source_offset_start") or 0)
    end_hint = int(message.get("source_offset_end") or 0)
    start_hint = max(0, min(start_hint, size))
    if end_hint <= start_hint:
        end_hint = min(size, start_hint + 65536)
    else:
        end_hint = min(end_hint, size)
    max_needle_len = max(
        len(text.encode("utf-8")),
        len(json.dumps(text, ensure_ascii=False)[1:-1].encode("utf-8")),
    )
    max_window = max(65536, min(2 * 1024 * 1024, max_needle_len * 4 + 4096))
    end_hint = min(size, start_hint + max_window, max(end_hint, start_hint))
    try:
        with path.open("rb") as f:
            f.seek(start_hint)
            data = f.read(max(0, end_hint - start_hint))
    except OSError:
        return {}
    candidates = [
        ("first_user_message_text", text.encode("utf-8")),
        ("first_user_message_json_escaped_text", json.dumps(text, ensure_ascii=False)[1:-1].encode("utf-8")),
    ]
    for basis, needle in candidates:
        if not needle:
            continue
        local = data.find(needle)
        if local >= 0:
            start = start_hint + local
            return {"start": start, "end": start + len(needle), "basis": basis}
    return {}


def _first_user_message_for_session(conn: sqlite3.Connection, session: dict[str, Any]) -> dict[str, Any]:
    select_sql = """
        select message_id, source_system, session_id, canonical_window_id,
               source_path, raw_path, role, timestamp,
               source_offset_start, source_offset_end,
               raw_offset_start, raw_offset_end,
               raw_available, content_preview, payload_json
        from canonical_messages
        where {where_clause}
          and role='user'
        order by rowid asc
        limit 40
        """
    rows = []
    # Prefer the indexed, precise record_id path. Some installed stores have no
    # standalone message index for session_id/canonical_window_id, so an OR query
    # or unscoped fallback can turn one raw-card borrow into a large table scan.
    source_system = _clean(session.get("source_system"), limit=120)
    for field in ("record_id", "session_id", "canonical_window_id"):
        value = _clean(session.get(field), limit=240)
        if not value:
            continue
        if field != "record_id" and source_system:
            rows = conn.execute(
                select_sql.format(where_clause=f"source_system=? and {field}=?"),
                (source_system, value),
            ).fetchall()
        else:
            rows = conn.execute(
                select_sql.format(where_clause=f"{field}=?"),
                (value,),
            ).fetchall()
        if rows:
            break
    columns = [
        "message_id",
        "source_system",
        "session_id",
        "canonical_window_id",
        "source_path",
        "raw_path",
        "role",
        "timestamp",
        "source_offset_start",
        "source_offset_end",
        "raw_offset_start",
        "raw_offset_end",
        "raw_available",
        "content_preview",
        "payload_json",
    ]
    fallback: dict[str, Any] = {}
    for row in rows:
        item = dict(zip(columns, row))
        text = _message_text_from_payload(str(item.get("payload_json") or ""), str(item.get("content_preview") or ""))
        item["content"] = text
        if not fallback:
            fallback = item
        if _CONTINUATION_SUMMARY_RE.search(text.strip()):
            continue
        if _BORING_USER_MESSAGE_RE.search(text.strip()):
            continue
        if len(_clean(text, limit=240)) < 6:
            continue
        exact = _exact_message_text_offsets(item, text)
        if exact:
            item["source_offset_start"] = exact["start"]
            item["source_offset_end"] = exact["end"]
            item["source_span_selection_basis"] = exact["basis"]
        return item
    return fallback


def _session_level_source_message(session: dict[str, Any]) -> dict[str, Any]:
    """Cheap source-ref fallback for catalog display when thread_name is enough.

    Startup catalog delivery must stay light. For sessions that already have a
    usable thread name, avoid scanning the large canonical_messages table just to
    find a title. The record remains source-backed through a bounded source slice.
    """

    source_path = _clean(session.get("source_path"), limit=1000)
    raw_path = _clean(session.get("raw_path"), limit=1000)
    source_size = int(session.get("source_size_bytes") or 0)
    raw_size = int(session.get("raw_size_bytes") or 0)
    use_raw = raw_path and raw_size > 0 and Path(raw_path).exists()
    size = raw_size if use_raw else source_size
    path = raw_path if use_raw else source_path
    start = 0
    end = min(max(size, 0), _SOURCE_SLICE_MAX_BYTES)
    selection_basis = "session_file_head_fallback"
    meaningful = _meaningful_source_slice(path)
    if meaningful:
        start = meaningful["start"]
        end = meaningful["end"]
        selection_basis = meaningful["basis"]
    return {
        "message_id": _clean(session.get("record_id") or session.get("session_id"), limit=160),
        "source_system": session.get("source_system"),
        "session_id": session.get("session_id"),
        "canonical_window_id": session.get("canonical_window_id"),
        "source_path": source_path,
        "raw_path": raw_path,
        "role": "session",
        "source_offset_start": start if source_path and end else None,
        "source_offset_end": end if source_path and end else None,
        "raw_offset_start": start if use_raw and end else None,
        "raw_offset_end": end if use_raw and end else None,
        "content_preview": _usable_thread_name(session.get("thread_name")),
        "content": "",
        "source_span_selection_basis": selection_basis,
    }


def _meaningful_source_slice(source_path: str) -> dict[str, Any]:
    if not source_path:
        return {}
    path = Path(source_path).expanduser()
    if not path.exists() or not path.is_file():
        return {}
    try:
        data = path.read_bytes()[:65536]
    except OSError:
        return {}
    text = data.decode("utf-8", errors="ignore")
    if not text.strip():
        return {}
    markers = [
        ("## §1 Active intent", "checkpoint_active_intent"),
        ("## Active intent", "checkpoint_active_intent"),
        ("## 当前目标", "checkpoint_active_intent"),
        ("Topic:", "checkpoint_topic"),
    ]
    for marker, basis in markers:
        idx = text.find(marker)
        if idx < 0:
            continue
        start = len(text[:idx].encode("utf-8"))
        next_section = text.find("\n## ", idx + len(marker))
        end_char = next_section if next_section > idx else min(len(text), idx + _SOURCE_SLICE_MAX_BYTES)
        end = min(len(text[:end_char].encode("utf-8")), start + _SOURCE_SLICE_MAX_BYTES)
        if end > start:
            return {"start": start, "end": end, "basis": basis}
    offset = 0
    for raw_line in data.splitlines(keepends=True):
        line_text = raw_line.decode("utf-8", errors="ignore").strip()
        line_start = offset
        offset += len(raw_line)
        if not line_text:
            continue
        lowered = line_text.lower()
        if lowered.startswith("# session checkpoint") or lowered.startswith("_generated by checkpoint"):
            continue
        end = min(len(data), line_start + _SOURCE_SLICE_MAX_BYTES)
        return {"start": line_start, "end": end, "basis": "first_non_boilerplate_line"}
    return {}


def _cheap_title(session: dict[str, Any], message: dict[str, Any]) -> tuple[str, str]:
    thread_name = _usable_thread_name(session.get("thread_name"))
    if thread_name:
        return thread_name, "thread_name"
    text = _clean(message.get("content") or message.get("content_preview"), limit=140)
    for sep in ("。", "！", "？", "\n", ".", "!", "?"):
        if sep in text[:100]:
            text = text.split(sep, 1)[0]
            break
    return _clean(text, limit=80) or _clean(session.get("session_id"), limit=80), "first_user_message"


def _source_ref_for_message(message: dict[str, Any], session: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    raw_start = message.get("raw_offset_start")
    raw_end = message.get("raw_offset_end")
    source_start = message.get("source_offset_start")
    source_end = message.get("source_offset_end")
    raw_path = _clean(message.get("raw_path") or session.get("raw_path"), limit=1000)
    source_path = _clean(message.get("source_path") or session.get("source_path"), limit=1000)
    use_raw = raw_path and raw_start is not None and raw_end is not None and Path(raw_path).exists()
    path = raw_path if use_raw else source_path
    start = raw_start if use_raw else source_start
    end = raw_end if use_raw else source_end
    raw_source_system = _clean(session.get("source_system") or message.get("source_system"), limit=80)
    raw_consumer = _clean(card.get("consumer") or card.get("source_system"), limit=80)
    canonical_lane = canonical_reading_area_lane(raw_source_system, consumer=raw_consumer)
    ref = {
        "source_system": raw_source_system,
        "source_system_canonical_lane": canonical_lane,
        "source_system_aliases": source_system_aliases(raw_source_system, consumer=raw_consumer),
        "consumer": raw_consumer,
        "source_path": path,
        "session_id": _clean(session.get("session_id"), limit=160),
        "canonical_window_id": _clean(session.get("canonical_window_id"), limit=160),
        "message_id": _clean(message.get("message_id"), limit=160),
        "role": _clean(message.get("role") or "user", limit=80),
        "artifact_type": RAW_SESSION_INDEX_RECORD_TYPE,
        "raw_path": raw_path,
        "original_source_path": source_path,
        "source_ref_kind": session.get("index_status")
        if source_system_index_status_matches_reading_area_raw_index(raw_source_system, str(session.get("index_status") or ""))
        else ("raw_path" if use_raw else "source_path_fallback_raw_missing"),
        "source_span_selection_basis": _clean(message.get("source_span_selection_basis") or "first_user_message", limit=120),
    }
    if start is not None and end is not None:
        try:
            ref["byte_offsets"] = {"start": int(start), "end": int(end)}
        except Exception:
            pass
    return ref


def _record_id_for(card: dict[str, Any], session: dict[str, Any]) -> str:
    seed = "|".join(
        [
            str(card.get("card_id") or ""),
            str(session.get("source_system") or ""),
            str(session.get("session_id") or ""),
            str(session.get("canonical_window_id") or ""),
            str(session.get("source_path") or session.get("raw_path") or ""),
        ]
    )
    return "ZX-RAW-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10].upper()


def _record_for_session(card: dict[str, Any], session: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    title, title_source = _cheap_title(session, message)
    source_refs = _source_ref_for_message(message, session, card)
    library_id = _record_id_for(card, session)
    raw_source_system = _clean(session.get("source_system"), limit=80)
    raw_consumer = _clean(card.get("consumer") or card.get("source_system"), limit=80)
    canonical_lane = canonical_reading_area_lane(raw_source_system, consumer=raw_consumer)
    return {
        "_type": RAW_SESSION_INDEX_RECORD_TYPE,
        "type": "raw_jsonl",
        "library_shelf": "raw",
        "library_id": library_id,
        "title": title,
        "summary": title,
        "detail": "",
        "source_system": canonical_lane,
        "origin_source_system": raw_source_system,
        "source_system_aliases": source_system_aliases(raw_source_system, consumer=raw_consumer),
        "consumer": raw_consumer,
        "session_id": _clean(session.get("session_id"), limit=160),
        "canonical_window_id": _clean(session.get("canonical_window_id"), limit=160),
        "declared_project_ids": _string_list(card.get("declared_project_ids")),
        "declared_series_ids": _string_list(card.get("declared_series_ids")),
        "declared_reading_area_ids": _string_list(card.get("declared_reading_area_ids")),
        "reading_area_matched_card_ids": _string_list(card.get("card_id")),
        "source_refs": source_refs,
        "lifecycle_status": "active",
        "created_at": _now(),
        "updated_at": _clean(session.get("updated_at"), limit=80) or _now(),
        "raw_index_meta": {
            "contract": RAW_SESSION_INDEX_CONTRACT,
            "projection_only": True,
            "read_only": True,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "title_model_used": False,
            "title_source": title_source,
            "scope_source": "borrowing_card_declared_membership",
            "technical_project_id_used_as_declared_identity": False,
            "session_index_status": _clean(session.get("index_status"), limit=80),
            "raw_offset_coverage_count": int(session.get("raw_offset_coverage_count") or 0),
            "source_span_selection_basis": source_refs.get("source_span_selection_basis"),
            "source_system_taxonomy_applied": True,
        },
    }


def build_raw_session_index_records(
    *,
    records_db_path: str | Path | None = None,
    memcore_root: str | Path | None = None,
    reading_area_registry_path: str | Path | None = None,
    project_ids: list[str] | tuple[str, ...] | str | None = None,
    series_ids: list[str] | tuple[str, ...] | str | None = None,
    source_systems: list[str] | tuple[str, ...] | str | None = None,
    mimocode_root: str | Path | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Build read-only raw shelf records for sessions with declared cards."""

    db_path = Path(records_db_path).expanduser() if records_db_path else _records_db_default_path(memcore_root)
    registry = _load_registry(reading_area_registry_path)
    declared_project_filter = _resolve_scope_values("project", project_ids, registry)
    declared_series_filter = _resolve_scope_values("series", series_ids, registry)
    source_filter = set(_string_list(source_systems))
    cards = [
        card
        for card in _declared_cards(registry)
        if _scope_allowed(card, project_ids=declared_project_filter, series_ids=declared_series_filter)
    ]
    if not db_path.exists():
        return {
            "ok": False,
            "contract": RAW_SESSION_INDEX_CONTRACT,
            "read_only": True,
            "write_performed": False,
            "error": "records_db_missing",
            "records_db_path": str(db_path),
            "card_count": len(cards),
            "records": [],
        }
    records: list[dict[str, Any]] = []
    matched_sessions = 0
    seen_sessions: set[tuple[str, str, str]] = set()
    with sqlite3.connect(db_path) as conn:
        for card in cards:
            sessions = _session_rows_for_card(conn, card)
            sessions.extend(_mimocode_session_rows_for_card(card, mimocode_root=mimocode_root))
            for session in sessions:
                if source_filter and str(session.get("source_system") or "") not in source_filter:
                    continue
                key = (
                    str(session.get("source_system") or ""),
                    str(session.get("session_id") or ""),
                    str(session.get("canonical_window_id") or ""),
                )
                if key in seen_sessions:
                    continue
                seen_sessions.add(key)
                message = _first_user_message_for_session(conn, session)
                if not message:
                    message = _session_level_source_message(session)
                if not message:
                    continue
                matched_sessions += 1
                records.append(_record_for_session(card, session, message))
                if limit and len(records) >= int(limit):
                    break
            if limit and len(records) >= int(limit):
                break
    return {
        "ok": True,
        "contract": RAW_SESSION_INDEX_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "projection_only": True,
        "records_db_path": str(db_path),
        "registry_path": str(reading_area_registry_path or ""),
        "declared_card_count": len(cards),
        "matched_session_count": matched_sessions,
        "record_count": len(records),
        "scope_policy": "borrowing_card_declared_membership_only_no_project_id_inference",
        "title_model_used": False,
        "records": records,
    }


def read_raw_index_source_excerpt(record: dict[str, Any], *, extra_allowed_roots: Any = None) -> dict[str, Any]:
    refs = record.get("source_refs") if isinstance(record.get("source_refs"), dict) else {}
    source_path = refs.get("source_path") or ""
    offsets = refs.get("byte_offsets") if isinstance(refs.get("byte_offsets"), dict) else {}
    if not source_path:
        return {"ok": False, "status": "missing_source_path", "text": ""}
    if not is_allowed_raw_source_path(source_path, extra_allowed_roots=extra_allowed_roots):
        return {"ok": False, "status": "source_path_not_allowed", "source_path": source_path, "text": ""}
    if "start" not in offsets or "end" not in offsets:
        return {"ok": False, "status": "missing_byte_offsets", "source_path": source_path, "text": ""}
    try:
        start = int(offsets.get("start"))
        end = int(offsets.get("end"))
        with open(source_path, "rb") as f:
            f.seek(start)
            data = f.read(max(0, end - start))
        return {
            "ok": True,
            "status": "ok",
            "source_path": source_path,
            "byte_offsets": {"start": start, "end": end},
            "text": data.decode("utf-8", errors="ignore"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": f"read_error:{type(exc).__name__}",
            "source_path": source_path,
            "byte_offsets": offsets,
            "text": "",
        }


def fetch_raw_session_index_record_by_library_id(library_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    target = _clean(library_id, limit=160)
    for record in records or []:
        if isinstance(record, dict) and _clean(record.get("library_id"), limit=160) == target:
            return record
    return {}


__all__ = [
    "RAW_SESSION_INDEX_CONTRACT",
    "RAW_SESSION_INDEX_RECORD_TYPE",
    "build_raw_session_index_records",
    "fetch_raw_session_index_record_by_library_id",
    "is_allowed_raw_source_path",
    "read_raw_index_source_excerpt",
]
