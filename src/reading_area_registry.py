#!/usr/bin/env python3
"""Read-only reading-area borrowing-card registry.

This module is the self-report layer above window binding. It records which
reading areas, projects, and series a window declared it entered. It does not
infer project identity from technical anchors such as cwd/window project_id, and
it does not own or mutate reading-area content.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc
REGISTRY_VERSION = "2026.7.1"
READING_AREA_REGISTRY_CONTRACT = "time_library_reading_area_registry.v1"
BORROWING_CARD_CONTRACT = "time_library_borrowing_card.v1"
BORROWING_RECORD_CONTRACT = "time_library_borrowing_record.v1"
WHITEBOARD_RECORD_CONTRACT = "time_library_whiteboard_record.v1"
WHITEBOARD_LIST_CONTRACT = "time_library_whiteboard_list.v1"
PROJECT_HISTORY_RECORD_CONTRACT = "time_library_project_history_record.v1"
PROJECT_HISTORY_LIST_CONTRACT = "time_library_project_history_list.v1"
PROJECT_NOMINATION_CONTRACT = "time_library_project_nomination.v1"
PROJECT_NOMINATION_LIST_CONTRACT = "time_library_project_nomination_list.v1"
DEFAULT_REGISTRY_RELATIVE_PATH = "config/reading_area_registry.json"
BORROWING_HISTORY_LIMIT = 200
WHITEBOARD_VISIBLE_STATUSES = {"active", "handoff", "blocked"}
WHITEBOARD_ALLOWED_STATUSES = {"active", "superseded", "completed", "blocked", "handoff", "cancelled"}
WHITEBOARD_ALLOWED_RECORD_TYPES = {"claim_task", "checkpoint", "handoff"}
PROJECT_HISTORY_VISIBLE_STATUSES = {"active"}
PROJECT_HISTORY_ALLOWED_TYPES = {"milestone", "decision", "handoff", "checkpoint"}
PROJECT_NOMINATION_ALLOWED_STATUSES = {"pending", "claimed", "rejected"}
PROJECT_HISTORY_EVIDENCE_ARCHIVE_RELATIVE = "output/project_history_evidence/slices"
TEMP_SOURCE_PATH_MARKERS = (
    "/var/folders/",
    "/private/var/folders/",
    "/tmp/",
    "/private/tmp/",
)
TIME_LIBRARY_CANONICAL_PROJECT_ID = "project:time-library:03657f57bf"
TIME_LIBRARY_CANONICAL_PROJECT_NAME = "time-library"
TIME_LIBRARY_PROJECT_ALIASES = (
    "time-library",
    "Time Library",
    "时间图书馆",
    "\u5fc6\u51e1\u5c18",
)


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _memcore_root() -> Path:
    try:
        from config_loader import get_memcore_root

        return Path(get_memcore_root()).expanduser()
    except Exception:
        env_root = os.environ.get("MEMCORE_ROOT", "").strip()
        if env_root:
            return Path(env_root).expanduser()
        return Path(__file__).resolve().parents[1]


def registry_path(path: str | Path | None = None) -> Path:
    explicit = str(path or os.environ.get("MEMCORE_READING_AREA_REGISTRY") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return _memcore_root() / DEFAULT_REGISTRY_RELATIVE_PATH


def _clean(value: Any, *, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _string_list(value: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in _as_list(value):
        text = _clean(item, limit=160)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _slug(value: Any, *, fallback: str = "item", limit: int = 64) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return (text or fallback)[:limit].strip("-") or fallback


def _stable_id(kind: str, name: Any) -> str:
    label = _clean(name, limit=160)
    digest = hashlib.sha256(f"{kind}|{label}".encode("utf-8")).hexdigest()[:10]
    return f"{kind}:{_slug(label, fallback=kind)}:{digest}"


def _card_id(source_system: str, canonical_window_id: str, session_id: str = "", consumer: str = "") -> str:
    seed = "|".join(
        [
            _clean(source_system).lower(),
            _clean(consumer).lower(),
            _clean(canonical_window_id),
            _clean(session_id),
        ]
    )
    return "card:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _empty_registry() -> dict[str, Any]:
    return {
        "_meta": {
            "version": REGISTRY_VERSION,
            "contract": READING_AREA_REGISTRY_CONTRACT,
            "updated_at": ts(),
            "projection_revision": 0,
            "policy": "agent_self_report_only_no_project_inference",
            "read_only_reading_area": True,
            "not_a_sixth_shelf": True,
            "project_id_technical_anchor_not_overwritten": True,
            "content_ownership": "registry_records_membership_only_not_reading_area_content",
        },
        "borrowing_cards": {},
        "reading_areas": {},
        "projects": {},
        "series": {},
        "aliases": {"reading_area": {}, "project": {}, "series": {}},
        "merges": {"reading_area": [], "project": [], "series": []},
        "archives": {"reading_area": [], "project": [], "series": []},
        "borrowing_records": [],
        "whiteboard_records": [],
        "project_history_records": [],
        "project_nominations": [],
    }


def _normalize_registry(value: Any) -> dict[str, Any]:
    registry = value if isinstance(value, dict) else {}
    base = _empty_registry()
    merged = {**base, **registry}
    meta = merged.get("_meta") if isinstance(merged.get("_meta"), dict) else {}
    merged["_meta"] = {
        **base["_meta"],
        **meta,
        "version": str(meta.get("version") or REGISTRY_VERSION),
        "contract": READING_AREA_REGISTRY_CONTRACT,
        "projection_revision": int(meta.get("projection_revision") or 0),
        "read_only_reading_area": True,
        "not_a_sixth_shelf": True,
        "project_id_technical_anchor_not_overwritten": True,
    }
    for key, default in (
        ("borrowing_cards", {}),
        ("reading_areas", {}),
        ("projects", {}),
        ("series", {}),
    ):
        if not isinstance(merged.get(key), dict):
            merged[key] = default
    aliases = merged.get("aliases") if isinstance(merged.get("aliases"), dict) else {}
    merged["aliases"] = {
        "reading_area": aliases.get("reading_area") if isinstance(aliases.get("reading_area"), dict) else {},
        "project": aliases.get("project") if isinstance(aliases.get("project"), dict) else {},
        "series": aliases.get("series") if isinstance(aliases.get("series"), dict) else {},
    }
    merges = merged.get("merges") if isinstance(merged.get("merges"), dict) else {}
    merged["merges"] = {
        "reading_area": merges.get("reading_area") if isinstance(merges.get("reading_area"), list) else [],
        "project": merges.get("project") if isinstance(merges.get("project"), list) else [],
        "series": merges.get("series") if isinstance(merges.get("series"), list) else [],
    }
    archives = merged.get("archives") if isinstance(merged.get("archives"), dict) else {}
    merged["archives"] = {
        "reading_area": archives.get("reading_area") if isinstance(archives.get("reading_area"), list) else [],
        "project": archives.get("project") if isinstance(archives.get("project"), list) else [],
        "series": archives.get("series") if isinstance(archives.get("series"), list) else [],
    }
    if not isinstance(merged.get("borrowing_records"), list):
        merged["borrowing_records"] = []
    if not isinstance(merged.get("whiteboard_records"), list):
        merged["whiteboard_records"] = []
    if not isinstance(merged.get("project_history_records"), list):
        merged["project_history_records"] = []
    if not isinstance(merged.get("project_nominations"), list):
        merged["project_nominations"] = []
    return merged


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    resolved = registry_path(path)
    if not resolved.exists():
        return _empty_registry()
    try:
        data = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except Exception:
        return _empty_registry()
    return _normalize_registry(data)


def save_registry(registry: dict[str, Any], path: str | Path | None = None) -> Path:
    resolved = registry_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_registry(registry)
    normalized["_meta"]["updated_at"] = ts()
    normalized["_meta"]["projection_revision"] = int(normalized["_meta"].get("projection_revision") or 0) + 1
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, resolved)
    return resolved


def _normalize_source_system(value: Any) -> str:
    return _clean(value, limit=120).lower().replace("-", "_")


def _stable_whiteboard_id(seed: str) -> str:
    return "WB-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10].upper()


def _stable_project_history_id(seed: str) -> str:
    return "PH-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10].upper()


def _stable_project_nomination_id(seed: str) -> str:
    return "PN-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10].upper()


def _whiteboard_record_type(value: Any) -> str:
    selected = _clean(value, limit=40).lower().replace("-", "_")
    return selected if selected in WHITEBOARD_ALLOWED_RECORD_TYPES else "checkpoint"


def _whiteboard_status(value: Any, *, record_type: str = "checkpoint") -> str:
    selected = _clean(value, limit=40).lower().replace("-", "_")
    if selected in WHITEBOARD_ALLOWED_STATUSES:
        return selected
    if record_type == "claim_task":
        return "active"
    if record_type == "handoff":
        return "handoff"
    return "active"


def _whiteboard_status_label(status: str) -> str:
    return {
        "active": "进行中",
        "handoff": "待接棒",
        "blocked": "阻塞",
        "completed": "完成",
        "cancelled": "取消",
        "superseded": "已替代",
    }.get(status, status or "进行中")


def _project_history_type(value: Any) -> str:
    selected = _clean(value, limit=40).lower().replace("-", "_")
    return selected if selected in PROJECT_HISTORY_ALLOWED_TYPES else "milestone"


def _canonical_lane(source_system: Any, *, consumer: Any = "") -> str:
    try:
        from src.source_system_taxonomy import canonical_reading_area_lane
    except Exception:  # pragma: no cover
        from source_system_taxonomy import canonical_reading_area_lane
    return canonical_reading_area_lane(source_system, consumer=consumer)


def _first_role(explicit_role: Any, declared_roles: list[str]) -> str:
    explicit = _clean(explicit_role, limit=80)
    if explicit:
        return explicit
    return declared_roles[0] if declared_roles else ""


def _scope_matches_record(record: dict[str, Any], *, reading_area_ids: set[str], project_ids: set[str], series_ids: set[str]) -> bool:
    if not reading_area_ids and not project_ids and not series_ids:
        return False
    declared_areas = set(_string_list(record.get("declared_reading_area_ids")))
    declared_projects = set(_string_list(record.get("declared_project_ids")))
    declared_series = set(_string_list(record.get("declared_series_ids")))
    return bool(
        (reading_area_ids and declared_areas & reading_area_ids)
        or (project_ids and declared_projects & project_ids)
        or (series_ids and declared_series & series_ids)
    )


def _whiteboard_evidence_refs(
    *,
    library_ids: list[str] | tuple[str, ...] | str | None = None,
    source_refs: list[Any] | tuple[Any, ...] | Any | None = None,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for library_id in _string_list(library_ids):
        refs.append({"type": "library_id", "library_id": library_id})
    for item in _as_list(source_refs):
        if isinstance(item, dict):
            refs.append(dict(item))
            continue
        text = _clean(item, limit=400)
        if text:
            refs.append({"type": "source_ref", "source_ref": text})
    return refs


def _source_ref_offsets(ref: dict[str, Any]) -> dict[str, Any]:
    offsets = ref.get("byte_offsets") if isinstance(ref.get("byte_offsets"), dict) else {}
    if "start" in offsets or "end" in offsets:
        return dict(offsets)
    return {}


def _primary_evidence_ref(evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
    for item in evidence_refs:
        if isinstance(item, dict) and item.get("source_path") and _source_ref_offsets(item):
            return dict(item)
    for item in evidence_refs:
        if isinstance(item, dict) and item.get("source_path"):
            return dict(item)
    return {}


def _is_temporary_source_path(source_path: str) -> bool:
    path = _clean(source_path, limit=1200)
    if not path:
        return False
    expanded = str(Path(path).expanduser())
    lowered = expanded.lower()
    return any(marker in lowered for marker in TEMP_SOURCE_PATH_MARKERS)


def _project_history_evidence_archive_dir(path: str | Path | None = None) -> Path:
    return registry_path(path).parent.parent / PROJECT_HISTORY_EVIDENCE_ARCHIVE_RELATIVE


def _materialize_project_history_source_ref_if_needed(
    source_ref: dict[str, Any],
    *,
    raw: bytes,
    sha: str,
    path: str | Path | None = None,
) -> dict[str, Any]:
    source_path = _clean(source_ref.get("source_path"), limit=1200)
    if not _is_temporary_source_path(source_path):
        return source_ref
    archive_dir = _project_history_evidence_archive_dir(path)
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{sha}.txt"
    if not archive_path.exists():
        tmp = archive_path.with_suffix(archive_path.suffix + ".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, archive_path)
    materialized = dict(source_ref)
    materialized["original_source_ref"] = dict(source_ref)
    materialized["source_path"] = str(archive_path)
    materialized["resolved_source_path"] = str(archive_path)
    materialized["byte_offsets"] = {"start": 0, "end": len(raw)}
    materialized["source_persistence"] = "durable_project_history_evidence_archive"
    materialized["source_materialized_from_temporary_path"] = True
    materialized["verbatim_sha256"] = sha
    return materialized


def _read_source_slice(source_ref: dict[str, Any]) -> tuple[bytes, str, str]:
    source_path = _clean(source_ref.get("resolved_source_path") or source_ref.get("source_path"), limit=1200)
    offsets = _source_ref_offsets(source_ref)
    if not source_path:
        return b"", "", "source_path_missing"
    try:
        start = int(offsets.get("start"))
        end = int(offsets.get("end"))
    except (TypeError, ValueError):
        return b"", "", "byte_offsets_missing"
    if start < 0 or end <= start:
        return b"", "", "byte_offsets_invalid"
    path = Path(source_path).expanduser()
    if not path.is_file():
        return b"", "", "source_path_unreadable"
    try:
        if path.stat().st_size < end:
            return b"", "", "byte_offsets_out_of_range"
        with path.open("rb") as f:
            f.seek(start)
            raw = f.read(end - start)
    except OSError:
        return b"", "", "source_path_unreadable"
    return raw, raw.decode("utf-8", errors="ignore"), ""


def _whiteboard_primary_source_ref(evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
    for item in evidence_refs:
        if not isinstance(item, dict):
            continue
        if item.get("source_path"):
            return dict(item)
        if item.get("byte_offsets") and item.get("source_path"):
            return dict(item)
    for item in evidence_refs:
        if not isinstance(item, dict):
            continue
        if item.get("library_id"):
            return {"library_id": _clean(item.get("library_id"), limit=120)}
    return {}


def _whiteboard_task_label(record: dict[str, Any]) -> str:
    return _clean(record.get("task_name") or record.get("summary") or record.get("task_id"), limit=28)


def _whiteboard_display_line(record: dict[str, Any]) -> str:
    role = _clean(record.get("role"), limit=16) or "未设角色"
    agent = _clean(record.get("agent") or record.get("source_system"), limit=16) or "agent"
    task = _whiteboard_task_label(record)
    status_label = _whiteboard_status_label(_clean(record.get("status"), limit=24))
    next_owner = _clean(record.get("next_owner"), limit=20)
    line = f"在飞：{role}/{agent} {task} -> {status_label}"
    if next_owner:
        line += f"；交接给 {next_owner}"
    line += f"；[{_clean(record.get('record_id'), limit=40)}]"
    return line


def _project_history_display_line(record: dict[str, Any]) -> str:
    title = _clean(record.get("title") or record.get("summary") or record.get("record_id"), limit=34)
    kind = _clean(record.get("history_type"), limit=16) or "milestone"
    return f"历史：{kind} {title}；[{_clean(record.get('record_id'), limit=40)}]"


def _nomination_display_line(record: dict[str, Any]) -> str:
    project = _clean(record.get("nominated_project") or record.get("target_project_id"), limit=40)
    source = _clean(record.get("source_system"), limit=24) or "source"
    session = _clean(record.get("session_id") or record.get("canonical_window_id"), limit=28)
    return f"提名：{source}/{session} -> {project or '未定项目'}；[{_clean(record.get('nomination_id'), limit=40)}]"


def resolve_borrowing_card(
    *,
    card_id: str = "",
    source_system: str = "",
    canonical_window_id: str = "",
    session_id: str = "",
    consumer: str = "",
    registry: dict[str, Any] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    reg = _normalize_registry(registry) if registry is not None else load_registry(path)
    selected_id = _clean(card_id, limit=220)
    if selected_id:
        card = reg["borrowing_cards"].get(selected_id)
        if isinstance(card, dict):
            return {"ok": True, "card": card, "card_id": selected_id}
        return {"ok": False, "error": "borrowing_card_not_found", "card_id": selected_id}
    source = _normalize_source_system(source_system)
    canonical = _clean(canonical_window_id, limit=200)
    session = _clean(session_id, limit=200)
    selected_consumer = _normalize_source_system(consumer)
    if not source or not (canonical or session):
        return {"ok": False, "error": "borrowing_card_identity_required"}
    for existing_id, card in reg["borrowing_cards"].items():
        if not isinstance(card, dict):
            continue
        if source and _normalize_source_system(card.get("source_system")) != source:
            continue
        if selected_consumer and _normalize_source_system(card.get("consumer")) != selected_consumer:
            continue
        if canonical and _clean(card.get("canonical_window_id"), limit=200) != canonical:
            continue
        if session and _clean(card.get("session_id"), limit=200) != session:
            continue
        return {"ok": True, "card": card, "card_id": existing_id}
    return {
        "ok": False,
        "error": "borrowing_card_not_found",
        "source_system": source,
        "canonical_window_id": canonical,
        "session_id": session,
        "consumer": selected_consumer,
    }


def _scope_bucket(scope_type: str) -> str:
    selected = _clean(scope_type).lower()
    if selected not in {"reading_area", "project", "series"}:
        raise ValueError("scope_type_must_be_reading_area_project_or_series")
    return selected


def _scope_store_key(scope_type: str) -> str:
    return {"reading_area": "reading_areas", "project": "projects", "series": "series"}[_scope_bucket(scope_type)]


def _known_scope_identity(scope_type: str, value: Any) -> tuple[str, str, list[str]]:
    bucket = _scope_bucket(scope_type)
    text = _clean(value, limit=200)
    if bucket == "project" and text.casefold() in {alias.casefold() for alias in TIME_LIBRARY_PROJECT_ALIASES}:
        return (
            TIME_LIBRARY_CANONICAL_PROJECT_ID,
            TIME_LIBRARY_CANONICAL_PROJECT_NAME,
            list(TIME_LIBRARY_PROJECT_ALIASES),
        )
    return "", "", []


def _archived_scope_redirect(registry: dict[str, Any], scope_type: str, value: Any) -> str:
    bucket = _scope_bucket(scope_type)
    text = _clean(value, limit=200)
    lowered = text.lower()
    for archive in reversed(registry.get("archives", {}).get(bucket, [])):
        if not isinstance(archive, dict):
            continue
        historical_names = _string_list([
            archive.get("from_id"),
            archive.get("from_name"),
            *archive.get("from_aliases", []),
        ])
        if text in historical_names or lowered in {name.lower() for name in historical_names}:
            return _clean(archive.get("to_id"), limit=160)
    return ""


def resolve_scope_id(scope_type: str, value: str, *, registry: dict[str, Any] | None = None, path: str | Path | None = None) -> str:
    bucket = _scope_bucket(scope_type)
    text = _clean(value, limit=200)
    if not text:
        return ""
    reg = _normalize_registry(registry) if registry is not None else load_registry(path)
    store = reg[_scope_store_key(bucket)]
    aliases = reg["aliases"][bucket]
    if text in store:
        return text
    known_id, _, _ = _known_scope_identity(bucket, text)
    if known_id and known_id in store:
        return known_id
    if text in aliases:
        return str(aliases[text])
    lowered = text.lower()
    for scope_id, scope in store.items():
        if lowered == str(scope_id).lower() or lowered == str(scope.get("name") or "").lower():
            return scope_id
        if lowered in [str(alias).lower() for alias in scope.get("aliases", []) or []]:
            return scope_id
    resolved = aliases.get(lowered, "")
    if resolved:
        return resolved
    return _archived_scope_redirect(reg, bucket, text)


def _ensure_scope(
    registry: dict[str, Any],
    scope_type: str,
    *,
    name: str,
    scope_id: str = "",
    declared_by_card_id: str = "",
    aliases: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    bucket = _scope_bucket(scope_type)
    store = registry[_scope_store_key(bucket)]
    known_id, known_name, known_aliases = _known_scope_identity(bucket, name)
    explicit_id = _clean(scope_id, limit=160)
    archived_id = "" if explicit_id or known_id else _archived_scope_redirect(registry, bucket, name)
    if archived_id and archived_id in store:
        return archived_id
    existing_id = resolve_scope_id(bucket, name, registry=registry)
    chosen_id = explicit_id or existing_id or known_id
    if not chosen_id:
        chosen_id = _stable_id(bucket, name)
    now = ts()
    existing = store.get(chosen_id) if isinstance(store.get(chosen_id), dict) else {}
    scope_name = known_name or _clean(name, limit=200) or existing.get("name") or chosen_id
    alias_values = _string_list([*(aliases or []), *known_aliases, existing.get("name"), name, scope_name])
    store[chosen_id] = {
        **existing,
        "id": chosen_id,
        "name": scope_name,
        "scope_type": bucket,
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
        "declared_by_card_ids": sorted(set(_string_list(existing.get("declared_by_card_ids")) + _string_list(declared_by_card_id))),
        "aliases": sorted(set(_string_list(existing.get("aliases")) + alias_values)),
        "self_reported": True,
        "inferred": False,
        "read_only": True,
        "reading_area_content_write_performed": False,
        "metadata": {**(existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}), **(metadata or {})},
    }
    for alias in store[chosen_id]["aliases"]:
        registry["aliases"][bucket][alias] = chosen_id
        registry["aliases"][bucket][alias.lower()] = chosen_id
    registry["aliases"][bucket][chosen_id] = chosen_id
    return chosen_id


def ensure_borrowing_card(
    *,
    source_system: str,
    canonical_window_id: str,
    session_id: str = "",
    consumer: str = "",
    native_window_id: str = "",
    title: str = "",
    binding: dict[str, Any] | None = None,
    declared_by: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Create or update the borrowing card for a window.

    The technical project_id from a window binding is preserved only as an
    anchor in technical_anchors. It is never copied into declared project ids.
    """

    source = _clean(source_system).lower().replace("-", "_")
    canonical = _clean(canonical_window_id)
    session = _clean(session_id)
    if not source or not (canonical or session):
        return {
            "ok": False,
            "error": "source_system_and_window_identity_required",
            "registry_path": str(registry_path(path)),
        }
    registry = load_registry(path)
    binding = binding if isinstance(binding, dict) else {}
    card_id = _card_id(source, canonical or session, session, consumer or source)
    now = ts()
    existing = registry["borrowing_cards"].get(card_id)
    existing = existing if isinstance(existing, dict) else {}
    technical_anchors = existing.get("technical_anchors") if isinstance(existing.get("technical_anchors"), dict) else {}
    binding_meta = binding.get("metadata") if isinstance(binding.get("metadata"), dict) else {}
    for key in (
        "project_id",
        "project_root",
        "workstream_id",
        "task_id",
        "canonical_window_id",
        "session_id",
        "source_path",
    ):
        value = binding.get(key, "") or binding_meta.get(key, "")
        if value not in ("", None, [], {}):
            technical_anchors[key] = value
    card = {
        **existing,
        "card_id": card_id,
        "contract": BORROWING_CARD_CONTRACT,
        "source_system": source,
        "consumer": _clean(consumer) or source,
        "canonical_window_id": canonical or session,
        "session_id": session,
        "native_window_id": _clean(native_window_id),
        "title": _clean(title, limit=200),
        "issued_at": existing.get("issued_at") or now,
        "updated_at": now,
        "declared_by": _clean(declared_by, limit=120) or existing.get("declared_by", ""),
        "declared_reading_area_ids": _string_list(existing.get("declared_reading_area_ids")),
        "declared_project_ids": _string_list(existing.get("declared_project_ids")),
        "declared_series_ids": _string_list(existing.get("declared_series_ids")),
        "declared_roles": _string_list(existing.get("declared_roles")),
        "aliases": existing.get("aliases") if isinstance(existing.get("aliases"), dict) else {},
        "technical_anchors": technical_anchors,
        "policy": "self_reported_membership_only",
        "project_identity_source": "agent_self_report_not_technical_project_id",
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "reading_area_content_write_performed": False,
        "owns_reading_area_content": False,
        "append_only_borrowing_records": True,
    }
    registry["borrowing_cards"][card_id] = card
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "card": card,
        "card_id": card_id,
        "project_id_preserved_as_technical_anchor_only": bool(technical_anchors.get("project_id")),
        "declared_project_ids": card["declared_project_ids"],
    }


def ensure_borrowing_card_for_current_window(
    *,
    source_system: str,
    consumer: str = "",
    window_registry_path: str | Path | None = None,
    reading_area_registry_path: str | Path | None = None,
) -> dict[str, Any]:
    """Issue a borrowing card from the current-window binding registry.

    This is the bridge from the existing technical window binding to the
    self-reported reading-area layer. The binding's project_id remains only a
    technical anchor; declared project/series ids must still come from
    declare_membership().
    """

    try:
        from src.window_binding_registry import get_current_window_binding
    except Exception:  # pragma: no cover
        from window_binding_registry import get_current_window_binding

    binding = get_current_window_binding(
        source_system,
        consumer=consumer,
        path=window_registry_path,
    )
    if not binding:
        return {
            "ok": False,
            "error": "current_window_binding_not_found",
            "source_system": _clean(source_system).lower().replace("-", "_"),
            "consumer": _clean(consumer),
            "window_registry_path": str(window_registry_path or ""),
            "registry_path": str(registry_path(reading_area_registry_path)),
        }
    result = ensure_borrowing_card(
        source_system=str(binding.get("source_system") or source_system),
        consumer=str(binding.get("consumer") or consumer or source_system),
        canonical_window_id=str(binding.get("canonical_window_id") or ""),
        session_id=str(binding.get("session_id") or ""),
        native_window_id=str(binding.get("native_window_id") or ""),
        title=str(binding.get("title") or ""),
        binding=binding,
        path=reading_area_registry_path,
    )
    result["window_binding_applied"] = bool(result.get("ok"))
    result["window_binding_key"] = str(binding.get("binding_key") or "")
    result["window_registry_path"] = str(window_registry_path or "")
    return result


def declare_membership(
    *,
    card_id: str,
    reading_area: str = "",
    projects: list[str] | tuple[str, ...] | str | None = None,
    series: list[str] | tuple[str, ...] | str | None = None,
    roles: list[str] | tuple[str, ...] | str | None = None,
    aliases: list[str] | tuple[str, ...] | str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    card = registry["borrowing_cards"].get(_clean(card_id))
    if not isinstance(card, dict):
        return {"ok": False, "error": "borrowing_card_not_found", "registry_path": str(registry_path(path))}
    area_id = ""
    if _clean(reading_area):
        area_id = _ensure_scope(
            registry,
            "reading_area",
            name=reading_area,
            declared_by_card_id=card_id,
            aliases=_string_list(aliases),
        )
        card["declared_reading_area_ids"] = sorted(set(_string_list(card.get("declared_reading_area_ids")) + [area_id]))
    project_ids: list[str] = []
    for project in _string_list(projects):
        project_id = _ensure_scope(registry, "project", name=project, declared_by_card_id=card_id)
        project_ids.append(project_id)
    if project_ids:
        card["declared_project_ids"] = sorted(set(_string_list(card.get("declared_project_ids")) + project_ids))
    series_ids: list[str] = []
    for item in _string_list(series):
        series_id = _ensure_scope(registry, "series", name=item, declared_by_card_id=card_id)
        series_ids.append(series_id)
    if series_ids:
        card["declared_series_ids"] = sorted(set(_string_list(card.get("declared_series_ids")) + series_ids))
    role_ids = _string_list(roles)
    if role_ids:
        card["declared_roles"] = sorted(set(_string_list(card.get("declared_roles")) + role_ids))
    card["updated_at"] = ts()
    registry["borrowing_cards"][card_id] = card
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "card_id": card_id,
        "reading_area_id": area_id,
        "project_ids": project_ids,
        "series_ids": series_ids,
        "declared_roles": _string_list(card.get("declared_roles")),
        "self_reported": True,
        "inferred": False,
        "read_only": True,
        "reading_area_content_write_performed": False,
    }


def write_whiteboard_record(
    *,
    borrowing_card_id: str = "",
    source_system: str = "",
    canonical_window_id: str = "",
    session_id: str = "",
    consumer: str = "",
    record_type: str,
    task_id: str,
    task_name: str = "",
    summary: str,
    status: str = "",
    role: str = "",
    next_owner: str = "",
    supersedes: list[str] | tuple[str, ...] | str | None = None,
    library_ids: list[str] | tuple[str, ...] | str | None = None,
    source_refs: list[Any] | tuple[Any, ...] | Any | None = None,
    request_id: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    resolved = resolve_borrowing_card(
        card_id=borrowing_card_id,
        source_system=source_system,
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        consumer=consumer,
        registry=registry,
    )
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": str(resolved.get("error") or "borrowing_card_not_found"),
            "registry_path": str(registry_path(path)),
            "write_performed": False,
            "whiteboard_registry_write_performed": False,
        }
    card = resolved["card"]
    selected_record_type = _whiteboard_record_type(record_type)
    clean_task_id = _clean(task_id, limit=120)
    if not clean_task_id:
        return {
            "ok": False,
            "error": "task_id_required",
            "registry_path": str(registry_path(path)),
            "write_performed": False,
            "whiteboard_registry_write_performed": False,
        }
    summary_text = _clean(summary, limit=240)
    if not summary_text:
        return {
            "ok": False,
            "error": "summary_required",
            "registry_path": str(registry_path(path)),
            "write_performed": False,
            "whiteboard_registry_write_performed": False,
        }
    declared_reading_area_ids = _string_list(card.get("declared_reading_area_ids"))
    declared_project_ids = _string_list(card.get("declared_project_ids"))
    declared_series_ids = _string_list(card.get("declared_series_ids"))
    if not (declared_reading_area_ids or declared_project_ids or declared_series_ids):
        return {
            "ok": False,
            "error": "declared_scope_required_before_whiteboard_write",
            "registry_path": str(registry_path(path)),
            "card_id": resolved.get("card_id", ""),
            "write_performed": False,
            "whiteboard_registry_write_performed": False,
        }
    declared_roles = _string_list(card.get("declared_roles"))
    role_snapshot = _first_role(role, declared_roles)
    normalized_status = _whiteboard_status(status, record_type=selected_record_type)
    next_owner_text = _clean(next_owner, limit=120)
    evidence_refs = _whiteboard_evidence_refs(library_ids=library_ids, source_refs=source_refs)
    supersedes_ids = _string_list(supersedes)
    request_key = _clean(request_id, limit=160)
    existing_records = registry.get("whiteboard_records") if isinstance(registry.get("whiteboard_records"), list) else []
    if request_key:
        for existing in existing_records:
            if isinstance(existing, dict) and _clean(existing.get("request_id"), limit=160) == request_key:
                return {
                    "ok": True,
                    "already_recorded": True,
                    "registry_path": str(registry_path(path)),
                    "record": existing,
                    "record_id": existing.get("record_id", ""),
                    "card_id": resolved.get("card_id", ""),
                    "whiteboard_registry_write_performed": False,
                    "write_performed": False,
                    "reading_area_content_write_performed": False,
                }
    now = ts()
    record_id = _stable_whiteboard_id(
        "|".join(
            [
                resolved.get("card_id", ""),
                clean_task_id,
                selected_record_type,
                request_key or now,
                summary_text,
            ]
        )
    )
    record = {
        "contract": WHITEBOARD_RECORD_CONTRACT,
        "record_id": record_id,
        "card_id": resolved.get("card_id", ""),
        "record_type": selected_record_type,
        "task_id": clean_task_id,
        "task_name": _clean(task_name, limit=120) or clean_task_id,
        "status": normalized_status,
        "summary": summary_text,
        "role": role_snapshot,
        "declared_roles_snapshot": declared_roles,
        "agent": _canonical_lane(card.get("source_system"), consumer=card.get("consumer")),
        "source_system": _normalize_source_system(card.get("source_system")),
        "consumer": _clean(card.get("consumer"), limit=120),
        "canonical_window_id": _clean(card.get("canonical_window_id"), limit=200),
        "session_id": _clean(card.get("session_id"), limit=200),
        "next_owner": next_owner_text,
        "supersedes": supersedes_ids,
        "declared_reading_area_ids": declared_reading_area_ids,
        "declared_project_ids": declared_project_ids,
        "declared_series_ids": declared_series_ids,
        "evidence_refs": evidence_refs,
        "source_ref": _whiteboard_primary_source_ref(evidence_refs),
        "request_id": request_key,
        "created_at": now,
        "updated_at": now,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
    }
    registry["whiteboard_records"] = existing_records + [record]
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "record": record,
        "record_id": record_id,
        "card_id": resolved.get("card_id", ""),
        "whiteboard_registry_write_performed": True,
        "write_performed": True,
        "reading_area_content_write_performed": False,
    }


def list_whiteboard_records(
    *,
    borrowing_card_id: str = "",
    source_system: str = "",
    canonical_window_id: str = "",
    session_id: str = "",
    consumer: str = "",
    reading_area_ids: list[str] | tuple[str, ...] | str | None = None,
    project_ids: list[str] | tuple[str, ...] | str | None = None,
    series_ids: list[str] | tuple[str, ...] | str | None = None,
    statuses: list[str] | tuple[str, ...] | str | None = None,
    limit: int = 20,
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    scoped_area_ids = set(_string_list(reading_area_ids))
    scoped_project_ids = set(_string_list(project_ids))
    scoped_series_ids = set(_string_list(series_ids))
    if borrowing_card_id or source_system or canonical_window_id or session_id:
        resolved = resolve_borrowing_card(
            card_id=borrowing_card_id,
            source_system=source_system,
            canonical_window_id=canonical_window_id,
            session_id=session_id,
            consumer=consumer,
            registry=registry,
        )
        if resolved.get("ok"):
            card = resolved["card"]
            scoped_area_ids.update(_string_list(card.get("declared_reading_area_ids")))
            scoped_project_ids.update(_string_list(card.get("declared_project_ids")))
            scoped_series_ids.update(_string_list(card.get("declared_series_ids")))
    allowed_statuses = set(_string_list(statuses)) or set(WHITEBOARD_VISIBLE_STATUSES)
    matches: list[dict[str, Any]] = []
    for record in registry.get("whiteboard_records") or []:
        if not isinstance(record, dict):
            continue
        if not _scope_matches_record(
            record,
            reading_area_ids=scoped_area_ids,
            project_ids=scoped_project_ids,
            series_ids=scoped_series_ids,
        ):
            continue
        if allowed_statuses and _clean(record.get("status"), limit=40) not in allowed_statuses:
            continue
        copy = dict(record)
        copy["display_line"] = _whiteboard_display_line(copy)
        matches.append(copy)
    matches.sort(key=lambda item: (_clean(item.get("created_at"), limit=40), _clean(item.get("record_id"), limit=40)), reverse=True)
    visible = matches[: max(1, min(int(limit or 20), 100))]
    return {
        "ok": True,
        "contract": WHITEBOARD_LIST_CONTRACT,
        "registry_path": str(registry_path(path)),
        "read_only": True,
        "write_performed": False,
        "whiteboard_registry_write_performed": False,
        "reading_area_content_write_performed": False,
        "projection_revision": int(((registry.get("_meta") or {}).get("projection_revision") or 0)),
        "updated_at": str(((registry.get("_meta") or {}).get("updated_at") or "")),
        "record_count": len(matches),
        "visible_record_count": len(visible),
        "records": visible,
        "scope": {
            "reading_area_ids": sorted(scoped_area_ids),
            "project_ids": sorted(scoped_project_ids),
            "series_ids": sorted(scoped_series_ids),
        },
        "statuses": sorted(allowed_statuses),
    }


def write_project_history_record(
    *,
    borrowing_card_id: str = "",
    source_system: str = "",
    canonical_window_id: str = "",
    session_id: str = "",
    consumer: str = "",
    history_type: str = "milestone",
    project_id: str = "",
    title: str = "",
    summary: str = "",
    source_refs: list[Any] | tuple[Any, ...] | Any | None = None,
    request_id: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    resolved = resolve_borrowing_card(
        card_id=borrowing_card_id,
        source_system=source_system,
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        consumer=consumer,
        registry=registry,
    )
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": str(resolved.get("error") or "borrowing_card_not_found"),
            "registry_path": str(registry_path(path)),
            "write_performed": False,
            "project_history_registry_write_performed": False,
        }
    card = resolved["card"]
    declared_projects = _string_list(card.get("declared_project_ids"))
    declared_series = _string_list(card.get("declared_series_ids"))
    declared_areas = _string_list(card.get("declared_reading_area_ids"))
    selected_project = _clean(project_id, limit=160) or (declared_projects[0] if declared_projects else "")
    if not selected_project:
        return {
            "ok": False,
            "error": "declared_project_required_before_project_history_write",
            "registry_path": str(registry_path(path)),
            "write_performed": False,
            "project_history_registry_write_performed": False,
        }
    summary_text = _clean(summary, limit=500)
    title_text = _clean(title, limit=160) or summary_text[:80]
    if not summary_text or not title_text:
        return {
            "ok": False,
            "error": "title_and_summary_required",
            "registry_path": str(registry_path(path)),
            "write_performed": False,
            "project_history_registry_write_performed": False,
        }
    evidence_refs = _whiteboard_evidence_refs(source_refs=source_refs)
    primary = _primary_evidence_ref(evidence_refs)
    if not primary:
        return {
            "ok": False,
            "error": "source_ref_required",
            "registry_path": str(registry_path(path)),
            "write_performed": False,
            "project_history_registry_write_performed": False,
        }
    raw, source_text, read_error = _read_source_slice(primary)
    if read_error:
        return {
            "ok": False,
            "error": read_error,
            "registry_path": str(registry_path(path)),
            "write_performed": False,
            "project_history_registry_write_performed": False,
        }
    verbatim_value = primary.get("verbatim_excerpt")
    verbatim = str(verbatim_value) if verbatim_value not in (None, "") else source_text
    if verbatim != source_text:
        return {
            "ok": False,
            "error": "verbatim_source_mismatch",
            "registry_path": str(registry_path(path)),
            "write_performed": False,
            "project_history_registry_write_performed": False,
        }
    sha = hashlib.sha256(raw).hexdigest()
    supplied_sha = _clean(primary.get("verbatim_sha256"), limit=128)
    if supplied_sha and supplied_sha != sha:
        return {
            "ok": False,
            "error": "verbatim_sha256_mismatch",
            "registry_path": str(registry_path(path)),
            "write_performed": False,
            "project_history_registry_write_performed": False,
        }
    primary = dict(primary)
    primary["verbatim_excerpt"] = verbatim
    primary["verbatim_sha256"] = sha
    primary.setdefault("source_mode", "evidence_bound_project_history_digest")
    primary = _materialize_project_history_source_ref_if_needed(primary, raw=raw, sha=sha, path=path)
    request_key = _clean(request_id, limit=160)
    existing_records = registry.get("project_history_records") if isinstance(registry.get("project_history_records"), list) else []
    if request_key:
        for existing in existing_records:
            if isinstance(existing, dict) and _clean(existing.get("request_id"), limit=160) == request_key:
                return {
                    "ok": True,
                    "already_recorded": True,
                    "registry_path": str(registry_path(path)),
                    "record": existing,
                    "record_id": existing.get("record_id", ""),
                    "project_history_registry_write_performed": False,
                    "write_performed": False,
                }
    now = ts()
    record_id = _stable_project_history_id(
        "|".join([
            resolved.get("card_id", ""),
            selected_project,
            _project_history_type(history_type),
            request_key or now,
            title_text,
            sha,
        ])
    )
    record = {
        "contract": PROJECT_HISTORY_RECORD_CONTRACT,
        "record_id": record_id,
        "record_type": "project_history",
        "history_type": _project_history_type(history_type),
        "status": "active",
        "title": title_text,
        "summary": summary_text,
        "card_id": resolved.get("card_id", ""),
        "agent": _canonical_lane(card.get("source_system"), consumer=card.get("consumer")),
        "source_system": _normalize_source_system(card.get("source_system")),
        "consumer": _clean(card.get("consumer"), limit=120),
        "canonical_window_id": _clean(card.get("canonical_window_id"), limit=200),
        "session_id": _clean(card.get("session_id"), limit=200),
        "declared_reading_area_ids": declared_areas,
        "declared_project_ids": sorted(set([*declared_projects, selected_project])),
        "declared_series_ids": declared_series,
        "project_id": selected_project,
        "evidence_refs": [primary],
        "source_ref": primary,
        "verbatim_excerpt": verbatim,
        "verbatim_sha256": sha,
        "source_mode": "evidence_bound_project_history_digest",
        "source_author": _clean(primary.get("source_author") or primary.get("source_role"), limit=80),
        "request_id": request_key,
        "created_at": now,
        "updated_at": now,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
        "not_a_sixth_shelf": True,
    }
    registry["project_history_records"] = existing_records + [record]
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "record": record,
        "record_id": record_id,
        "project_history_registry_write_performed": True,
        "write_performed": True,
        "reading_area_content_write_performed": False,
    }


def list_project_history_records(
    *,
    project_ids: list[str] | tuple[str, ...] | str | None = None,
    series_ids: list[str] | tuple[str, ...] | str | None = None,
    reading_area_ids: list[str] | tuple[str, ...] | str | None = None,
    statuses: list[str] | tuple[str, ...] | str | None = None,
    limit: int = 20,
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    scoped_projects = set(_string_list(project_ids))
    scoped_series = set(_string_list(series_ids))
    scoped_areas = set(_string_list(reading_area_ids))
    allowed_statuses = set(_string_list(statuses)) or set(PROJECT_HISTORY_VISIBLE_STATUSES)
    matches: list[dict[str, Any]] = []
    for record in registry.get("project_history_records") or []:
        if not isinstance(record, dict):
            continue
        if not _scope_matches_record(record, reading_area_ids=scoped_areas, project_ids=scoped_projects, series_ids=scoped_series):
            continue
        if allowed_statuses and _clean(record.get("status"), limit=40) not in allowed_statuses:
            continue
        copy = dict(record)
        copy["display_line"] = _project_history_display_line(copy)
        matches.append(copy)
    matches.sort(key=lambda item: (_clean(item.get("created_at"), limit=40), _clean(item.get("record_id"), limit=40)), reverse=True)
    visible = matches[: max(1, min(int(limit or 20), 100))]
    return {
        "ok": True,
        "contract": PROJECT_HISTORY_LIST_CONTRACT,
        "registry_path": str(registry_path(path)),
        "read_only": True,
        "write_performed": False,
        "not_a_sixth_shelf": True,
        "record_count": len(matches),
        "visible_record_count": len(visible),
        "records": visible,
        "scope": {
            "reading_area_ids": sorted(scoped_areas),
            "project_ids": sorted(scoped_projects),
            "series_ids": sorted(scoped_series),
        },
        "statuses": sorted(allowed_statuses),
    }


def materialize_project_history_temporary_source_refs(path: str | Path | None = None) -> dict[str, Any]:
    registry = load_registry(path)
    records = registry.get("project_history_records") if isinstance(registry.get("project_history_records"), list) else []
    updated_records: list[dict[str, Any]] = []
    materialized_ids: list[str] = []
    skipped: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            updated_records.append(item)
            continue
        record = dict(item)
        source_ref = record.get("source_ref") if isinstance(record.get("source_ref"), dict) else {}
        source_path = _clean(source_ref.get("source_path"), limit=1200)
        if not _is_temporary_source_path(source_path):
            updated_records.append(record)
            continue
        raw, source_text, read_error = _read_source_slice(source_ref)
        if read_error:
            skipped.append({"record_id": _clean(record.get("record_id"), limit=80), "error": read_error})
            updated_records.append(record)
            continue
        verbatim = str(source_ref.get("verbatim_excerpt") or record.get("verbatim_excerpt") or "")
        if verbatim and verbatim != source_text:
            skipped.append({"record_id": _clean(record.get("record_id"), limit=80), "error": "verbatim_source_mismatch"})
            updated_records.append(record)
            continue
        sha = hashlib.sha256(raw).hexdigest()
        supplied_sha = _clean(source_ref.get("verbatim_sha256") or record.get("verbatim_sha256"), limit=128)
        if supplied_sha and supplied_sha != sha:
            skipped.append({"record_id": _clean(record.get("record_id"), limit=80), "error": "verbatim_sha256_mismatch"})
            updated_records.append(record)
            continue
        materialized = _materialize_project_history_source_ref_if_needed(dict(source_ref), raw=raw, sha=sha, path=path)
        materialized["verbatim_excerpt"] = source_text
        record["source_ref"] = materialized
        record["evidence_refs"] = [materialized]
        record["verbatim_excerpt"] = source_text
        record["verbatim_sha256"] = sha
        record["updated_at"] = ts()
        materialized_ids.append(_clean(record.get("record_id"), limit=80))
        updated_records.append(record)
    registry["project_history_records"] = updated_records
    saved = None
    if materialized_ids:
        saved = save_registry(registry, path)
    return {
        "ok": not skipped,
        "contract": PROJECT_HISTORY_RECORD_CONTRACT,
        "registry_path": str(saved or registry_path(path)),
        "materialized_count": len(materialized_ids),
        "materialized_record_ids": materialized_ids,
        "skipped": skipped,
        "project_history_registry_write_performed": bool(materialized_ids),
        "write_performed": bool(materialized_ids),
        "reading_area_content_write_performed": False,
        "source_persistence": "durable_project_history_evidence_archive",
    }


def create_project_nomination(
    *,
    source_system: str = "",
    canonical_window_id: str = "",
    session_id: str = "",
    source_path: str = "",
    nominated_project: str = "",
    nominated_series: str = "",
    reason: str = "",
    confidence: float = 0.0,
    request_id: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    project_label = _clean(nominated_project, limit=200)
    if not project_label:
        return {"ok": False, "error": "nominated_project_required", "write_performed": False}
    session = _clean(session_id, limit=240)
    canonical = _clean(canonical_window_id, limit=240)
    source = _normalize_source_system(source_system)
    if not source or not (session or canonical or _clean(source_path, limit=1000)):
        return {"ok": False, "error": "nomination_source_identity_required", "write_performed": False}
    request_key = _clean(request_id, limit=160)
    existing_records = registry.get("project_nominations") if isinstance(registry.get("project_nominations"), list) else []
    if request_key:
        for existing in existing_records:
            if isinstance(existing, dict) and _clean(existing.get("request_id"), limit=160) == request_key:
                return {
                    "ok": True,
                    "already_recorded": True,
                    "registry_path": str(registry_path(path)),
                    "nomination": existing,
                    "nomination_id": existing.get("nomination_id", ""),
                    "write_performed": False,
                }
    now = ts()
    nomination_id = _stable_project_nomination_id(
        "|".join([source, canonical, session, _clean(source_path, limit=1000), project_label, request_key or now])
    )
    nomination = {
        "contract": PROJECT_NOMINATION_CONTRACT,
        "nomination_id": nomination_id,
        "status": "pending",
        "source_system": source,
        "canonical_window_id": canonical,
        "session_id": session,
        "source_path": _clean(source_path, limit=1000),
        "nominated_project": project_label,
        "nominated_series": _clean(nominated_series, limit=200),
        "reason": _clean(reason, limit=500),
        "confidence": max(0.0, min(float(confidence or 0.0), 1.0)),
        "inferred": True,
        "declaration_required_to_register": True,
        "project_identity_source": "nomination_only_not_declared_until_claim",
        "request_id": request_key,
        "created_at": now,
        "updated_at": now,
        "read_only": True,
        "write_performed": False,
        "reading_area_content_write_performed": False,
    }
    registry["project_nominations"] = existing_records + [nomination]
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "nomination": nomination,
        "nomination_id": nomination_id,
        "nomination_registry_write_performed": True,
        "write_performed": True,
        "declared_membership_written": False,
    }


def list_project_nominations(
    *,
    statuses: list[str] | tuple[str, ...] | str | None = None,
    project: str = "",
    limit: int = 50,
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    allowed = set(_string_list(statuses)) or {"pending"}
    project_filter = _clean(project, limit=200).lower()
    matches: list[dict[str, Any]] = []
    for record in registry.get("project_nominations") or []:
        if not isinstance(record, dict):
            continue
        if allowed and _clean(record.get("status"), limit=40) not in allowed:
            continue
        if project_filter and project_filter not in _clean(record.get("nominated_project"), limit=200).lower():
            continue
        copy = dict(record)
        copy["display_line"] = _nomination_display_line(copy)
        matches.append(copy)
    matches.sort(key=lambda item: (_clean(item.get("created_at"), limit=40), _clean(item.get("nomination_id"), limit=40)), reverse=True)
    visible = matches[: max(1, min(int(limit or 50), 200))]
    return {
        "ok": True,
        "contract": PROJECT_NOMINATION_LIST_CONTRACT,
        "registry_path": str(registry_path(path)),
        "read_only": True,
        "write_performed": False,
        "nomination_count": len(matches),
        "visible_nomination_count": len(visible),
        "nominations": visible,
        "statuses": sorted(allowed),
        "inference_policy": "inference_creates_nomination_only_claim_required_for_membership",
    }


def claim_project_nomination(
    *,
    nomination_id: str,
    borrowing_card_id: str,
    reading_area: str = "",
    projects: list[str] | tuple[str, ...] | str | None = None,
    series: list[str] | tuple[str, ...] | str | None = None,
    roles: list[str] | tuple[str, ...] | str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    selected_id = _clean(nomination_id, limit=120).upper()
    index = -1
    nomination: dict[str, Any] = {}
    for idx, item in enumerate(registry.get("project_nominations") or []):
        if isinstance(item, dict) and _clean(item.get("nomination_id"), limit=120).upper() == selected_id:
            index = idx
            nomination = item
            break
    if index < 0:
        return {"ok": False, "error": "nomination_not_found", "write_performed": False}
    if _clean(nomination.get("status"), limit=40) == "claimed":
        return {"ok": True, "already_claimed": True, "nomination": nomination, "write_performed": False}
    declared_projects = _string_list(projects) or _string_list(nomination.get("nominated_project"))
    declared_series = _string_list(series) or _string_list(nomination.get("nominated_series"))
    membership = declare_membership(
        card_id=borrowing_card_id,
        reading_area=reading_area,
        projects=declared_projects,
        series=declared_series,
        roles=roles,
        path=path,
    )
    if not membership.get("ok"):
        return {
            "ok": False,
            "error": str(membership.get("error") or "membership_not_declared"),
            "membership_receipt": membership,
            "write_performed": bool(membership.get("write_performed")),
        }
    registry = load_registry(path)
    nominations = registry.get("project_nominations") if isinstance(registry.get("project_nominations"), list) else []
    for idx, item in enumerate(nominations):
        if isinstance(item, dict) and _clean(item.get("nomination_id"), limit=120).upper() == selected_id:
            updated = dict(item)
            updated["status"] = "claimed"
            updated["claimed_at"] = ts()
            updated["claimed_by_card_id"] = _clean(borrowing_card_id, limit=220)
            updated["declared_project_ids"] = membership.get("project_ids", [])
            updated["declared_series_ids"] = membership.get("series_ids", [])
            updated["updated_at"] = updated["claimed_at"]
            nominations[idx] = updated
            registry["project_nominations"] = nominations
            saved_path = save_registry(registry, path)
            return {
                "ok": True,
                "registry_path": str(saved_path),
                "nomination": updated,
                "nomination_id": updated["nomination_id"],
                "membership_receipt": membership,
                "nomination_registry_write_performed": True,
                "declared_membership_written": True,
                "write_performed": True,
                "inferred": False,
            }
    return {"ok": False, "error": "nomination_lost_after_membership", "membership_receipt": membership}


def reject_project_nomination(
    *,
    nomination_id: str,
    borrowing_card_id: str = "",
    reason: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    selected_id = _clean(nomination_id, limit=120).upper()
    nominations = registry.get("project_nominations") if isinstance(registry.get("project_nominations"), list) else []
    for idx, item in enumerate(nominations):
        if not isinstance(item, dict) or _clean(item.get("nomination_id"), limit=120).upper() != selected_id:
            continue
        updated = dict(item)
        updated["status"] = "rejected"
        updated["rejected_at"] = ts()
        updated["rejected_by_card_id"] = _clean(borrowing_card_id, limit=220)
        updated["reject_reason"] = _clean(reason, limit=500)
        updated["updated_at"] = updated["rejected_at"]
        nominations[idx] = updated
        registry["project_nominations"] = nominations
        saved_path = save_registry(registry, path)
        return {
            "ok": True,
            "registry_path": str(saved_path),
            "nomination": updated,
            "nomination_id": updated["nomination_id"],
            "nomination_registry_write_performed": True,
            "declared_membership_written": False,
            "write_performed": True,
        }
    return {"ok": False, "error": "nomination_not_found", "write_performed": False}


def _replace_scope_id(values: Any, from_id: str, to_id: str) -> tuple[list[str], bool]:
    changed = False
    rewritten: list[str] = []
    for value in _string_list(values):
        selected = to_id if value == from_id else value
        changed = changed or selected != value
        if selected not in rewritten:
            rewritten.append(selected)
    return rewritten, changed


def _rewrite_scope_references(registry: dict[str, Any], scope_type: str, from_id: str, to_id: str) -> dict[str, int]:
    bucket = _scope_bucket(scope_type)
    list_key = {
        "reading_area": "declared_reading_area_ids",
        "project": "declared_project_ids",
        "series": "declared_series_ids",
    }[bucket]
    scalar_key = {
        "reading_area": "reading_area_id",
        "project": "project_id",
        "series": "series_id",
    }[bucket]
    counts: dict[str, int] = {}
    stores = (
        ("borrowing_cards", list((registry.get("borrowing_cards") or {}).values())),
        ("borrowing_records", registry.get("borrowing_records") or []),
        ("whiteboard_records", registry.get("whiteboard_records") or []),
        ("project_history_records", registry.get("project_history_records") or []),
        ("project_nominations", registry.get("project_nominations") or []),
    )
    for store_name, records in stores:
        for record in records:
            if not isinstance(record, dict):
                continue
            rewritten, list_changed = _replace_scope_id(record.get(list_key), from_id, to_id)
            scalar_changed = _clean(record.get(scalar_key), limit=160) == from_id
            if list_changed:
                record[list_key] = rewritten
            if scalar_changed:
                record[scalar_key] = to_id
            if list_changed or scalar_changed:
                counts[store_name] = counts.get(store_name, 0) + 1
    return counts


def _redirect_scope_aliases(registry: dict[str, Any], scope_type: str, from_id: str, to_id: str) -> None:
    aliases = registry["aliases"][_scope_bucket(scope_type)]
    for alias, target_id in list(aliases.items()):
        if _clean(target_id, limit=160) == from_id:
            aliases[alias] = to_id


def add_scope_aliases(
    scope_type: str,
    value: str,
    aliases: list[str] | tuple[str, ...] | str,
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    bucket = _scope_bucket(scope_type)
    registry = load_registry(path)
    scope_id = resolve_scope_id(bucket, value, registry=registry)
    if not scope_id:
        return {"ok": False, "error": "scope_not_found", "scope_type": bucket, "write_performed": False}
    store = registry[_scope_store_key(bucket)]
    scope = store.get(scope_id) if isinstance(store.get(scope_id), dict) else {}
    if not scope:
        return {"ok": False, "error": "scope_not_active", "scope_type": bucket, "write_performed": False}
    requested = _string_list(aliases)
    combined = _string_list([*scope.get("aliases", []), scope.get("name"), *requested])
    already_registered = combined == _string_list(scope.get("aliases")) and all(
        registry["aliases"][bucket].get(alias) == scope_id
        and registry["aliases"][bucket].get(alias.lower()) == scope_id
        for alias in combined
    )
    if already_registered:
        return {
            "ok": True,
            "scope_type": bucket,
            "scope_id": scope_id,
            "aliases": combined,
            "already_registered": True,
            "write_performed": False,
        }
    scope["aliases"] = combined
    scope["updated_at"] = ts()
    store[scope_id] = scope
    for alias in combined:
        registry["aliases"][bucket][alias] = scope_id
        registry["aliases"][bucket][alias.lower()] = scope_id
    registry["aliases"][bucket][scope_id] = scope_id
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "scope_type": bucket,
        "scope_id": scope_id,
        "aliases": combined,
        "already_registered": False,
        "write_performed": True,
    }


def rename_scope(
    scope_type: str,
    old_value: str,
    new_name: str,
    *,
    new_id: str = "",
    declared_by_card_id: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    bucket = _scope_bucket(scope_type)
    registry = load_registry(path)
    old_id = resolve_scope_id(bucket, old_value, registry=registry)
    if not old_id:
        return {"ok": False, "error": "scope_not_found", "scope_type": bucket}
    store = registry[_scope_store_key(bucket)]
    old_scope = store.get(old_id) if isinstance(store.get(old_id), dict) else {}
    existing_target_id = resolve_scope_id(bucket, new_name, registry=registry)
    explicit_target_id = _clean(new_id, limit=160)
    target_id = explicit_target_id or existing_target_id
    if target_id and target_id != old_id and target_id in store:
        return merge_scope(
            bucket,
            old_id,
            target_id,
            declared_by_card_id=declared_by_card_id,
            path=path,
        )
    known_id, known_name, known_aliases = _known_scope_identity(bucket, new_name)
    target_id = target_id or known_id or _stable_id(bucket, new_name)
    now = ts()
    aliases = sorted(set(_string_list(old_scope.get("aliases")) + known_aliases + [old_id, old_scope.get("name", ""), old_value, new_name]))
    target = {
        **old_scope,
        "id": target_id,
        "name": known_name or _clean(new_name, limit=200),
        "scope_type": bucket,
        "created_at": old_scope.get("created_at") or now,
        "updated_at": now,
        "aliases": aliases,
        "renamed_from": old_id,
        "self_reported": True,
        "inferred": False,
        "read_only": True,
        "reading_area_content_write_performed": False,
    }
    declared = set(_string_list(target.get("declared_by_card_ids")))
    if declared_by_card_id:
        declared.add(_clean(declared_by_card_id))
    target["declared_by_card_ids"] = sorted(declared)
    store[target_id] = target
    if target_id != old_id:
        store.pop(old_id, None)
    for alias in aliases + [old_id, old_value, new_name, target_id]:
        clean_alias = _clean(alias, limit=200)
        if clean_alias:
            registry["aliases"][bucket][clean_alias] = target_id
            registry["aliases"][bucket][clean_alias.lower()] = target_id
    _redirect_scope_aliases(registry, bucket, old_id, target_id)
    rewritten_references = _rewrite_scope_references(registry, bucket, old_id, target_id)
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "scope_type": bucket,
        "old_id": old_id,
        "new_id": target_id,
        "aliases_preserved": aliases,
        "rewritten_references": rewritten_references,
        "self_reported": True,
        "read_only": True,
        "reading_area_content_write_performed": False,
    }


def merge_scope(
    scope_type: str,
    from_value: str,
    to_value: str,
    *,
    declared_by_card_id: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    bucket = _scope_bucket(scope_type)
    registry = load_registry(path)
    from_id = resolve_scope_id(bucket, from_value, registry=registry)
    to_id = resolve_scope_id(bucket, to_value, registry=registry)
    if not from_id or not to_id:
        return {"ok": False, "error": "scope_not_found", "scope_type": bucket}
    if from_id == to_id:
        return {"ok": True, "scope_type": bucket, "from_id": from_id, "to_id": to_id, "already_merged": True}
    store = registry[_scope_store_key(bucket)]
    source = store.get(from_id) if isinstance(store.get(from_id), dict) else {}
    target = store.get(to_id) if isinstance(store.get(to_id), dict) else {}
    if not source or not target:
        return {"ok": False, "error": "active_scope_not_found", "scope_type": bucket, "write_performed": False}
    aliases = sorted(set(_string_list(target.get("aliases")) + _string_list(source.get("aliases")) + [from_id, from_value]))
    target["aliases"] = aliases
    target["updated_at"] = ts()
    target["declared_by_card_ids"] = sorted(set(_string_list(target.get("declared_by_card_ids")) + _string_list(source.get("declared_by_card_ids")) + _string_list(declared_by_card_id)))
    store[to_id] = target
    store.pop(from_id, None)
    for alias in aliases + [from_id, from_value]:
        clean_alias = _clean(alias, limit=200)
        if clean_alias:
            registry["aliases"][bucket][clean_alias] = to_id
            registry["aliases"][bucket][clean_alias.lower()] = to_id
    registry["merges"][bucket].append({
        "from_id": from_id,
        "to_id": to_id,
        "declared_by_card_id": _clean(declared_by_card_id),
        "merged_at": ts(),
        "self_reported": True,
    })
    _redirect_scope_aliases(registry, bucket, from_id, to_id)
    rewritten_references = _rewrite_scope_references(registry, bucket, from_id, to_id)
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "scope_type": bucket,
        "from_id": from_id,
        "to_id": to_id,
        "aliases_preserved": aliases,
        "rewritten_references": rewritten_references,
        "self_reported": True,
        "read_only": True,
        "reading_area_content_write_performed": False,
    }


def archive_scope(
    scope_type: str,
    from_value: str,
    to_value: str,
    *,
    reason: str = "",
    declared_by_card_id: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    bucket = _scope_bucket(scope_type)
    registry = load_registry(path)
    raw_from = _clean(from_value, limit=200)
    for receipt in registry["archives"][bucket]:
        historical_names = _string_list([
            receipt.get("from_id") if isinstance(receipt, dict) else "",
            receipt.get("from_name") if isinstance(receipt, dict) else "",
            *(receipt.get("from_aliases", []) if isinstance(receipt, dict) else []),
        ])
        if isinstance(receipt, dict) and raw_from in historical_names:
            return {
                "ok": True,
                "scope_type": bucket,
                "from_id": raw_from,
                "to_id": _clean(receipt.get("to_id"), limit=160),
                "already_archived": True,
                "write_performed": False,
            }
    from_id = resolve_scope_id(bucket, from_value, registry=registry)
    to_id = resolve_scope_id(bucket, to_value, registry=registry)
    if not from_id or not to_id:
        return {"ok": False, "error": "scope_not_found", "scope_type": bucket, "write_performed": False}
    if from_id == to_id:
        return {"ok": False, "error": "archive_target_must_differ", "scope_type": bucket, "write_performed": False}
    store = registry[_scope_store_key(bucket)]
    source = store.get(from_id) if isinstance(store.get(from_id), dict) else {}
    target = store.get(to_id) if isinstance(store.get(to_id), dict) else {}
    if not source or not target:
        return {"ok": False, "error": "active_scope_not_found", "scope_type": bucket, "write_performed": False}
    target["declared_by_card_ids"] = _string_list([
        *target.get("declared_by_card_ids", []),
        *source.get("declared_by_card_ids", []),
        declared_by_card_id,
    ])
    target["updated_at"] = ts()
    store[to_id] = target
    store.pop(from_id, None)
    rewritten_references = _rewrite_scope_references(registry, bucket, from_id, to_id)
    for alias, target_id in list(registry["aliases"][bucket].items()):
        if _clean(target_id, limit=160) == from_id:
            registry["aliases"][bucket].pop(alias, None)
    receipt = {
        "from_id": from_id,
        "from_name": _clean(source.get("name"), limit=200),
        "from_aliases": _string_list(source.get("aliases")),
        "to_id": to_id,
        "reason": _clean(reason, limit=500),
        "declared_by_card_id": _clean(declared_by_card_id),
        "archived_at": ts(),
        "reference_policy": "historical_redirect_not_semantic_alias",
        "rewritten_references": rewritten_references,
        "self_reported": True,
    }
    registry["archives"][bucket].append(receipt)
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "scope_type": bucket,
        "from_id": from_id,
        "to_id": to_id,
        "archive_receipt": receipt,
        "rewritten_references": rewritten_references,
        "write_performed": True,
        "reading_area_content_write_performed": False,
    }


def record_borrowing(
    *,
    card_id: str,
    library_ids: list[str] | tuple[str, ...] | str | None = None,
    source_refs: list[Any] | tuple[Any, ...] | Any | None = None,
    request_id: str = "",
    reading_area_id: str = "",
    project_id: str = "",
    series_id: str = "",
    consumer: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    card = registry["borrowing_cards"].get(_clean(card_id))
    if not isinstance(card, dict):
        return {"ok": False, "error": "borrowing_card_not_found", "registry_path": str(registry_path(path))}
    ids = _string_list(library_ids)
    refs = [item for item in _as_list(source_refs) if item not in (None, "", [], {})]
    declared_reading_area_ids = _string_list(card.get("declared_reading_area_ids"))
    declared_project_ids = _string_list(card.get("declared_project_ids"))
    declared_series_ids = _string_list(card.get("declared_series_ids"))
    record = {
        "contract": BORROWING_RECORD_CONTRACT,
        "record_id": "borrow:" + hashlib.sha256("|".join([card_id, request_id, ",".join(ids), ts()]).encode("utf-8")).hexdigest()[:16],
        "card_id": card_id,
        "consumer": _clean(consumer) or card.get("consumer") or "",
        "request_id": _clean(request_id, limit=160),
        "borrowed_at": ts(),
        "reading_area_id": _clean(reading_area_id, limit=160),
        "project_id": _clean(project_id, limit=160),
        "series_id": _clean(series_id, limit=160),
        "declared_reading_area_ids": declared_reading_area_ids,
        "declared_project_ids": declared_project_ids,
        "declared_series_ids": declared_series_ids,
        "declared_scope_identity_source": "borrowing_card_agent_self_report_not_technical_project_id",
        "technical_project_id_used_as_declared_identity": False,
        "used_library_ids": ids,
        "used_source_refs": refs,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "reading_area_content_write_performed": False,
        "final_evidence_authority": "raw_source_refs",
    }
    registry["borrowing_records"].append(record)
    registry["borrowing_records"] = registry["borrowing_records"][-BORROWING_HISTORY_LIMIT:]
    card["last_borrowed_at"] = record["borrowed_at"]
    card["borrowed_library_ids"] = sorted(set(_string_list(card.get("borrowed_library_ids")) + ids))
    card["updated_at"] = ts()
    registry["borrowing_cards"][card_id] = card
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "borrowing_record": record,
        "used_library_ids": ids,
        "used_source_refs": refs,
        "read_only": True,
        "write_performed": False,
        "reading_area_content_write_performed": False,
    }


def _scope_record_counts(records: list[Any], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        for scope_id in _string_list(record.get(key)):
            counts[scope_id] = counts.get(scope_id, 0) + 1
    return dict(sorted(counts.items()))


def summarize_registry(path: str | Path | None = None) -> dict[str, Any]:
    registry = load_registry(path)
    borrowing_records = registry["borrowing_records"]
    return {
        "ok": True,
        "contract": READING_AREA_REGISTRY_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "reading_area_content_write_performed": False,
        "not_a_sixth_shelf": True,
        "borrowing_card_count": len(registry["borrowing_cards"]),
        "reading_area_count": len(registry["reading_areas"]),
        "project_count": len(registry["projects"]),
        "series_count": len(registry["series"]),
        "borrowing_record_count": len(borrowing_records),
        "borrowing_records_with_declared_scope_count": sum(
            1
            for record in borrowing_records
            if isinstance(record, dict)
            and (
                _string_list(record.get("declared_reading_area_ids"))
                or _string_list(record.get("declared_project_ids"))
                or _string_list(record.get("declared_series_ids"))
            )
        ),
        "borrowing_record_scope_counts": {
            "reading_area": _scope_record_counts(borrowing_records, "declared_reading_area_ids"),
            "series": _scope_record_counts(borrowing_records, "declared_series_ids"),
        },
        "project_scope_borrowing_record_count": sum(
            1
            for record in borrowing_records
            if isinstance(record, dict) and _string_list(record.get("declared_project_ids"))
        ),
        "project_scope_breakdown_policy": "aggregate_only_no_project_id_keyed_summary",
        "project_identity_source": "agent_self_report_not_project_id",
        "whiteboard_record_count": len(registry.get("whiteboard_records") or []),
        "project_history_record_count": len(registry.get("project_history_records") or []),
        "project_nomination_count": len(registry.get("project_nominations") or []),
        "projection_revision": int(((registry.get("_meta") or {}).get("projection_revision") or 0)),
    }


__all__ = [
    "READING_AREA_REGISTRY_CONTRACT",
    "BORROWING_CARD_CONTRACT",
    "BORROWING_RECORD_CONTRACT",
    "WHITEBOARD_RECORD_CONTRACT",
    "WHITEBOARD_LIST_CONTRACT",
    "PROJECT_HISTORY_RECORD_CONTRACT",
    "PROJECT_HISTORY_LIST_CONTRACT",
    "PROJECT_NOMINATION_CONTRACT",
    "PROJECT_NOMINATION_LIST_CONTRACT",
    "registry_path",
    "load_registry",
    "save_registry",
    "ensure_borrowing_card",
    "ensure_borrowing_card_for_current_window",
    "declare_membership",
    "resolve_borrowing_card",
    "write_whiteboard_record",
    "list_whiteboard_records",
    "write_project_history_record",
    "list_project_history_records",
    "materialize_project_history_temporary_source_refs",
    "create_project_nomination",
    "list_project_nominations",
    "claim_project_nomination",
    "reject_project_nomination",
    "add_scope_aliases",
    "rename_scope",
    "merge_scope",
    "archive_scope",
    "record_borrowing",
    "resolve_scope_id",
    "summarize_registry",
]
