#!/usr/bin/env python3
"""Automatic full/incremental distillation coverage runner.

This module is source/offline product plumbing: it tracks canonical sessions,
runs bounded distillation windows through an injected model/distiller, writes
evidence-bound candidates, and emits self-check receipts. It does not read raw
outside the captured store and does not install or restart runtime services.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from src.relay_voiceprint import apply_annotation
    from src.source_system_taxonomy import canonical_reading_area_lane
    from src.source_system_runtime_declarations import (
        source_system_distill_priority,
        source_system_distillable,
        source_system_filter_matches,
        source_system_filter_query_tokens,
        source_system_for_distill_checkpoint_adapter,
        source_system_required_coverage_source_for_distill_target_shape,
        source_system_supports_distill_target_shape,
    )
    from src import reading_area_raw_index
    from src.toolbook_quality import is_low_quality_toolbook_record, is_one_time_status_report
    from src.zhixing_library import library_id_for
except Exception:  # pragma: no cover
    from relay_voiceprint import apply_annotation
    from source_system_taxonomy import canonical_reading_area_lane
    from source_system_runtime_declarations import (
        source_system_distill_priority,
        source_system_distillable,
        source_system_filter_matches,
        source_system_filter_query_tokens,
        source_system_for_distill_checkpoint_adapter,
        source_system_required_coverage_source_for_distill_target_shape,
        source_system_supports_distill_target_shape,
    )
    reading_area_raw_index = None
    from toolbook_quality import is_low_quality_toolbook_record, is_one_time_status_report
    from zhixing_library import library_id_for


DISTILL_AUTOMATION_CONTRACT = "time_library_distill_automation.v1"
DISTILL_COVERAGE_LEDGER_CONTRACT = "time_library_distill_coverage_ledger.v1"
DISTILL_RUNNER_CONTRACT = "time_library_distill_runner.v1"
DISTILL_SELF_CHECK_CONTRACT = "time_library_distill_window_self_check.v1"
DISTILL_SCHEDULER_CONTRACT = "time_library_distill_scheduler.v1"
DEFAULT_DISTILL_VERSION = "2026-07-02.auto.v1"

_QUEUE_STATUSES = {"queued", "failed", "pending_model_config", "self_check_failed"}
_PENDING_SELF_CHECK_STATUS = "coverage_pending_self_check"
_NO_EVIDENCE_SKIP_REASONS = {
    "no_evidence_bound_candidates",
    "insufficient_evidence",
    "no_clean_owner_sample",
    "candidate_matches_inactive_record",
}
_INACTIVE_CANDIDATE_STATUSES = {"deprecated", "superseded", "recycled", "invalid"}
_PROBE_PHRASES = (
    "say ok only.",
    "say ok only",
    "respond ok only",
    "respond with ok only",
    "reply ok only",
    "return ok only",
)
PROJECT_HISTORY_TARGET_SHAPE = "project_history_digest"
DEEP_DISTILL_TARGET_SHAPE = "deep_distill"
MIMOCODE_DEEP_DISTILL_TARGET_SHAPE = "mimocode_deep_distill"
MIMOCODE_SOURCE_SYSTEM = source_system_for_distill_checkpoint_adapter("checkpoint_markdown_sections") or "mimocode"
DEEP_DISTILL_MIN_SOURCE_BYTES = 1_000_000
DEEP_DISTILL_MIN_INDEXED_MESSAGES = 1_000


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value: Any, *, limit: int = 500) -> str:
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


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _write_jsonl_atomic(path: str | Path, rows: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                f.write("\n")
        os.replace(tmp_name, p)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def session_key_for(session: dict[str, Any]) -> str:
    seed = "|".join(
        [
            _clean(session.get("source_system"), limit=120),
            _clean(session.get("record_id"), limit=240),
            _clean(session.get("session_id"), limit=240),
            _clean(session.get("canonical_window_id"), limit=240),
            _clean(session.get("source_path") or session.get("raw_path"), limit=1000),
        ]
    )
    return "session:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"pragma table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def load_canonical_sessions(
    records_db_path: str | Path,
    *,
    source_systems: list[str] | tuple[str, ...] | str | None = None,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """Load canonical session rows that define distillation coverage."""

    db_path = Path(records_db_path).expanduser()
    if not db_path.exists():
        return []
    wanted = [
        "record_id",
        "source_system",
        "session_id",
        "canonical_window_id",
        "raw_artifact_id",
        "project_id",
        "project_root",
        "thread_name",
        "source_path",
        "raw_path",
        "source_size_bytes",
        "raw_size_bytes",
        "indexed_message_count",
        "raw_offset_coverage_count",
        "index_status",
        "updated_at",
    ]
    filters = set(source_system_filter_query_tokens(_as_list(source_systems)))
    with sqlite3.connect(db_path) as conn:
        columns = _existing_columns(conn, "canonical_sessions")
        selected = [col for col in wanted if col in columns]
        if not selected:
            return []
        sql = f"select {', '.join(selected)} from canonical_sessions"
        params: list[Any] = []
        if filters and "source_system" in selected:
            placeholders = ",".join("?" for _ in filters)
            sql += f" where source_system in ({placeholders})"
            params.extend(sorted(filters))
        if "updated_at" in selected:
            sql += " order by updated_at desc"
        if limit:
            sql += " limit ?"
            params.append(int(limit))
        rows = conn.execute(sql, params).fetchall()
    sessions: list[dict[str, Any]] = []
    for row in rows:
        session = dict(zip(selected, row))
        session["session_key"] = session_key_for(session)
        session["canonical_lane"] = canonical_reading_area_lane(session.get("source_system"))
        sessions.append(session)
    return sessions


def _root_from_records_db(records_db_path: str | Path) -> Path:
    path = Path(records_db_path).expanduser()
    if path.name == "records.db" and len(path.parents) >= 3:
        return path.parents[2]
    return Path(os.environ.get("MEMCORE_ROOT") or os.environ.get("MEMCORE_INSTALL_ROOT") or ".").expanduser()


def _default_reading_area_registry_path(records_db_path: str | Path) -> Path:
    return _root_from_records_db(records_db_path) / "config" / "reading_area_registry.json"


def load_declared_mimocode_sessions(
    records_db_path: str | Path,
    *,
    reading_area_registry_path: str | Path | None = None,
    mimocode_root: str | Path | None = None,
    project_ids: list[str] | tuple[str, ...] | str | None = None,
    series_ids: list[str] | tuple[str, ...] | str | None = None,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """Load declared MiMo checkpoint sessions for coverage without mutating store.

    MiMo checkpoints currently live outside ``canonical_sessions``.  They may
    enter coverage only through an existing borrowing-card declaration, so the
    project boundary stays self-reported rather than inferred from filesystem
    presence.
    """

    if reading_area_raw_index is None:
        return []
    registry_path = Path(reading_area_registry_path).expanduser() if reading_area_registry_path else _default_reading_area_registry_path(records_db_path)
    if not registry_path.exists():
        return []
    try:
        registry = reading_area_raw_index._load_registry(registry_path)
        declared_project_filter = reading_area_raw_index._resolve_scope_values("project", project_ids, registry)
        declared_series_filter = reading_area_raw_index._resolve_scope_values("series", series_ids, registry)
        cards = [
            card
            for card in reading_area_raw_index._declared_cards(registry)
            if reading_area_raw_index._scope_allowed(
                card,
                project_ids=declared_project_filter,
                series_ids=declared_series_filter,
            )
        ]
        raw_records: list[dict[str, Any]] = []
        for card in cards:
            for session in reading_area_raw_index._mimocode_session_rows_for_card(card, mimocode_root=mimocode_root):
                raw_records.append(reading_area_raw_index._record_for_session(card, session, reading_area_raw_index._session_level_source_message(session)))
                if limit and len(raw_records) >= int(limit):
                    break
            if limit and len(raw_records) >= int(limit):
                break
    except Exception:
        return []
    sessions: list[dict[str, Any]] = []
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        refs = record.get("source_refs") if isinstance(record.get("source_refs"), dict) else {}
        source_path = _clean(refs.get("source_path"), limit=1000)
        if not source_path:
            continue
        path = Path(source_path).expanduser()
        if not path.is_file():
            continue
        source_system = _clean(record.get("origin_source_system") or refs.get("source_system") or MIMOCODE_SOURCE_SYSTEM, limit=120)
        session = {
            "record_id": _clean(record.get("library_id") or record.get("session_id") or source_path, limit=240),
            "source_system": source_system,
            "session_id": _clean(record.get("session_id"), limit=240),
            "canonical_window_id": _clean(record.get("canonical_window_id") or record.get("session_id"), limit=240),
            "raw_artifact_id": _clean(record.get("library_id"), limit=240),
            "project_id": "",
            "project_root": "",
            "thread_name": _clean(record.get("title") or record.get("summary"), limit=240),
            "source_path": str(path),
            "raw_path": "",
            "source_size_bytes": path.stat().st_size,
            "raw_size_bytes": 0,
            "indexed_message_count": 0,
            "raw_offset_coverage_count": 1 if isinstance(refs.get("byte_offsets"), dict) else 0,
            "index_status": _clean(refs.get("source_ref_kind") or "mimocode_checkpoint_source_path_fallback", limit=120),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "coverage_source": "reading_area_declared_mimocode_checkpoint",
            "declared_project_ids": record.get("declared_project_ids") or [],
            "declared_series_ids": record.get("declared_series_ids") or [],
            "declared_reading_area_ids": record.get("declared_reading_area_ids") or [],
        }
        session["session_key"] = session_key_for(session)
        session["canonical_lane"] = canonical_reading_area_lane(source_system)
        sessions.append(session)
    return sessions


def load_coverage_sessions(
    records_db_path: str | Path,
    *,
    source_systems: list[str] | tuple[str, ...] | str | None = None,
    reading_area_registry_path: str | Path | None = None,
    mimocode_root: str | Path | None = None,
    project_ids: list[str] | tuple[str, ...] | str | None = None,
    series_ids: list[str] | tuple[str, ...] | str | None = None,
) -> list[dict[str, Any]]:
    sessions = load_canonical_sessions(records_db_path, source_systems=source_systems)
    if reading_area_registry_path:
        _apply_declared_registry_scope_to_sessions(sessions, reading_area_registry_path)
    filters = set(source_system_filter_query_tokens(_as_list(source_systems)))
    include_declared_checkpoint_adapter = source_system_filter_matches(MIMOCODE_SOURCE_SYSTEM, filters)
    if include_declared_checkpoint_adapter:
        sessions.extend(
            load_declared_mimocode_sessions(
                records_db_path,
                reading_area_registry_path=reading_area_registry_path,
                mimocode_root=mimocode_root,
                project_ids=project_ids,
                series_ids=series_ids,
            )
        )
    by_key: dict[str, dict[str, Any]] = {}
    for session in sessions:
        key = session.get("session_key")
        if not key:
            continue
        # Canonical store rows are loaded before declared checkpoint projections.
        # If a future MiMo connector writes the same session into canonical store,
        # keep the canonical row as the coverage authority and avoid double-counts.
        by_key.setdefault(key, session)
    return sorted(by_key.values(), key=lambda session: (str(session.get("source_system") or ""), str(session.get("session_key") or "")))


def _apply_declared_registry_scope_to_sessions(sessions: list[dict[str, Any]], registry_path: str | Path) -> None:
    try:
        from src import reading_area_registry as registry
    except Exception:  # pragma: no cover
        import reading_area_registry as registry
    try:
        reg = registry.load_registry(registry_path)
    except Exception:
        return
    cards = [card for card in (reg.get("borrowing_cards") or {}).values() if isinstance(card, dict)]
    for session in sessions:
        source = _clean(session.get("source_system"), limit=120).lower().replace("-", "_")
        session_id = _clean(session.get("session_id"), limit=240)
        window_id = _clean(session.get("canonical_window_id"), limit=240)
        for card in cards:
            if _clean(card.get("source_system"), limit=120).lower().replace("-", "_") != source:
                continue
            card_session = _clean(card.get("session_id"), limit=240)
            card_window = _clean(card.get("canonical_window_id"), limit=240)
            if session_id and card_session and session_id != card_session:
                continue
            if window_id and card_window and window_id != card_window:
                continue
            projects = _as_list(card.get("declared_project_ids"))
            series = _as_list(card.get("declared_series_ids"))
            areas = _as_list(card.get("declared_reading_area_ids"))
            if projects:
                session["declared_project_ids"] = projects
            if series:
                session["declared_series_ids"] = series
            if areas:
                session["declared_reading_area_ids"] = areas
            break


def _source_system_matches_filter(source_system: Any, source_systems: list[str] | tuple[str, ...] | str | None) -> bool:
    filters = {_clean(item, limit=120).lower() for item in _as_list(source_systems) if _clean(item, limit=120)}
    if not filters:
        return True
    return source_system_filter_matches(_clean(source_system, limit=120), filters)


def _session_source_sha256(session: dict[str, Any]) -> str:
    source_path = _clean(session.get("source_path") or session.get("raw_path"), limit=1000)
    if not source_path:
        return ""
    path = Path(source_path).expanduser()
    if not path.is_file():
        return ""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _session_duplicate_rank(session: dict[str, Any]) -> tuple[Any, ...]:
    return (
        source_system_distill_priority(_clean(session.get("source_system"), limit=120)),
        -int(session.get("source_size_bytes") or session.get("raw_size_bytes") or 0),
        -int(session.get("indexed_message_count") or 0),
        _clean(session.get("source_path") or session.get("raw_path"), limit=1000),
    )


def _annotate_content_duplicates(sessions: list[dict[str, Any]]) -> None:
    by_fingerprint: dict[str, list[dict[str, Any]]] = {}
    for session in sessions:
        has_source = bool(_clean(session.get("source_path") or session.get("raw_path"), limit=1000))
        if not has_source:
            continue
        sha = _session_source_sha256(session)
        if not sha:
            continue
        session["source_content_sha256"] = sha
        by_fingerprint.setdefault(sha, []).append(session)
    for sha, group in by_fingerprint.items():
        if len(group) < 2:
            continue
        systems = {_clean(session.get("source_system"), limit=120).lower() for session in group}
        paths = [_clean(session.get("source_path") or session.get("raw_path"), limit=1000) for session in group]
        has_same_path_duplicate = len(paths) != len(set(paths))
        has_cross_system_duplicate = len(systems) > 1
        if not has_same_path_duplicate and not has_cross_system_duplicate:
            continue
        canonical = sorted(group, key=_session_duplicate_rank)[0]
        canonical_key = _clean(canonical.get("session_key"), limit=120)
        canonical_ref = "|".join(
            item
            for item in (
                _clean(canonical.get("source_system"), limit=120),
                _clean(canonical.get("session_id"), limit=240),
                _clean(canonical.get("record_id"), limit=240),
            )
            if item
        )
        duplicate_group = f"sha256:{sha}"
        for session in group:
            session["content_duplicate_group"] = duplicate_group
            session["content_duplicate_canonical_session_key"] = canonical_key
            session["content_duplicate_canonical_ref"] = canonical_ref
            if session is not canonical:
                session["content_duplicate_of"] = canonical_key


def _entry_from_session(session: dict[str, Any], *, distill_version: str) -> dict[str, Any]:
    has_source = bool(_clean(session.get("source_path") or session.get("raw_path"), limit=1000))
    exclusion_reason = _session_exclusion_reason(session) if has_source else ""
    if not exclusion_reason and _clean(session.get("content_duplicate_of"), limit=120):
        exclusion_reason = "duplicate_content_already_enrolled"
    entry = {
        "contract": DISTILL_COVERAGE_LEDGER_CONTRACT,
        "session_key": session["session_key"],
        "status": "excluded" if exclusion_reason else ("queued" if has_source else "skipped"),
        "distill_version": distill_version,
        "source_system": _clean(session.get("source_system"), limit=120),
        "canonical_lane": canonical_reading_area_lane(session.get("source_system")),
        "record_id": _clean(session.get("record_id"), limit=240),
        "session_id": _clean(session.get("session_id"), limit=240),
        "canonical_window_id": _clean(session.get("canonical_window_id"), limit=240),
        "source_path": _clean(session.get("source_path"), limit=1000),
        "raw_path": _clean(session.get("raw_path"), limit=1000),
        "source_size_bytes": int(session.get("source_size_bytes") or 0),
        "raw_size_bytes": int(session.get("raw_size_bytes") or 0),
        "indexed_message_count": int(session.get("indexed_message_count") or 0),
        "raw_offset_coverage_count": int(session.get("raw_offset_coverage_count") or 0),
        "source_updated_at": _clean(session.get("updated_at"), limit=80),
        "coverage_source": _clean(session.get("coverage_source") or "canonical_sessions", limit=160),
        "declared_project_ids": _as_list(session.get("declared_project_ids")),
        "declared_series_ids": _as_list(session.get("declared_series_ids")),
        "declared_reading_area_ids": _as_list(session.get("declared_reading_area_ids")),
        "source_content_sha256": _clean(session.get("source_content_sha256"), limit=128),
        "content_duplicate_group": _clean(session.get("content_duplicate_group"), limit=160),
        "content_duplicate_of": _clean(session.get("content_duplicate_of"), limit=120),
        "content_duplicate_canonical_session_key": _clean(session.get("content_duplicate_canonical_session_key"), limit=120),
        "content_duplicate_canonical_ref": _clean(session.get("content_duplicate_canonical_ref"), limit=500),
        "attempt_count": 0,
        "candidate_ids": [],
        "library_ids": [],
        "reject_reasons": [],
        "queued_at": _now(),
        "updated_at": _now(),
    }
    if not has_source:
        entry["skip_reason"] = "missing_source_path"
    if exclusion_reason:
        entry["exclude_reason"] = exclusion_reason
    return entry


def _initial_target_shape_status(row: dict[str, Any], target_shape: str) -> tuple[str, str, str]:
    base_status = str(row.get("status") or "")
    if base_status == "excluded":
        return "excluded", "exclude_reason", _clean(row.get("exclude_reason"), limit=240)
    if target_shape == MIMOCODE_DEEP_DISTILL_TARGET_SHAPE:
        source_system = _clean(row.get("source_system"), limit=120)
        if not source_system_supports_distill_target_shape(source_system, target_shape):
            return "excluded", "exclude_reason", "mimocode_deep_distill_source_system_not_mimocode"
        required_coverage = source_system_required_coverage_source_for_distill_target_shape(source_system, target_shape)
        if required_coverage and _clean(row.get("coverage_source"), limit=200) != required_coverage:
            return "excluded", "exclude_reason", "mimocode_deep_distill_requires_declared_checkpoint"
        if not _clean(row.get("source_path"), limit=1000):
            return "skipped", "skip_reason", "missing_source_path"
        return "queued", "queued_at", _now()
    if base_status != "covered":
        return "skipped", "skip_reason", f"base_status_not_covered:{base_status}"
    if target_shape == DEEP_DISTILL_TARGET_SHAPE:
        size = int(row.get("source_size_bytes") or row.get("raw_size_bytes") or 0)
        indexed = int(row.get("indexed_message_count") or 0)
        if size < DEEP_DISTILL_MIN_SOURCE_BYTES and indexed < DEEP_DISTILL_MIN_INDEXED_MESSAGES:
            return "skipped", "skip_reason", "deep_distill_not_large_session"
    return "queued", "queued_at", _now()


def _session_exclusion_reason(session: dict[str, Any]) -> str:
    """Conservatively exclude tiny probe/smoke sessions from model spend."""

    if _clean(session.get("content_duplicate_of"), limit=120):
        return "duplicate_content_already_enrolled"
    source_system = _clean(session.get("source_system"), limit=120).lower()
    if source_system and not source_system_distillable(source_system):
        return "source_system_not_in_current_distill_scope"
    size = int(session.get("source_size_bytes") or session.get("raw_size_bytes") or 0)
    if size <= 0 or size > 16_384:
        return ""
    source_path = _clean(session.get("source_path") or session.get("raw_path"), limit=1000)
    if not source_path:
        return ""
    try:
        text = Path(source_path).expanduser().read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return ""
    compact = re.sub(r"\s+", " ", text)
    if any(phrase in compact for phrase in _PROBE_PHRASES):
        return "tiny_probe_or_smoke_session"
    return ""


def reconcile_coverage_ledger(
    *,
    records_db_path: str | Path,
    ledger_path: str | Path,
    distill_version: str = DEFAULT_DISTILL_VERSION,
    source_systems: list[str] | tuple[str, ...] | str | None = None,
    reading_area_registry_path: str | Path | None = None,
    mimocode_root: str | Path | None = None,
    project_ids: list[str] | tuple[str, ...] | str | None = None,
    series_ids: list[str] | tuple[str, ...] | str | None = None,
) -> dict[str, Any]:
    """Make the coverage ledger match canonical_sessions without losing state."""

    sessions = load_coverage_sessions(
        records_db_path,
        source_systems=source_systems,
        reading_area_registry_path=reading_area_registry_path,
        mimocode_root=mimocode_root,
        project_ids=project_ids,
        series_ids=series_ids,
    )
    _annotate_content_duplicates(sessions)
    canonical_session_count = len(load_canonical_sessions(records_db_path, source_systems=source_systems))
    declared_mimocode_session_count = sum(1 for session in sessions if session.get("coverage_source") == "reading_area_declared_mimocode_checkpoint")
    existing_rows = _read_jsonl(ledger_path)
    by_key = {row.get("session_key"): dict(row) for row in existing_rows if row.get("session_key")}
    added = 0
    marked_for_redistill = 0
    for session in sessions:
        key = session["session_key"]
        if key not in by_key:
            by_key[key] = _entry_from_session(session, distill_version=distill_version)
            added += 1
            continue
        entry = by_key[key]
        entry.update(
            {
                "source_system": _clean(session.get("source_system"), limit=120),
                "canonical_lane": canonical_reading_area_lane(session.get("source_system")),
                "record_id": _clean(session.get("record_id"), limit=240),
                "session_id": _clean(session.get("session_id"), limit=240),
                "canonical_window_id": _clean(session.get("canonical_window_id"), limit=240),
                "source_path": _clean(session.get("source_path"), limit=1000),
                "raw_path": _clean(session.get("raw_path"), limit=1000),
                "source_size_bytes": int(session.get("source_size_bytes") or 0),
                "raw_size_bytes": int(session.get("raw_size_bytes") or 0),
                "indexed_message_count": int(session.get("indexed_message_count") or 0),
                "raw_offset_coverage_count": int(session.get("raw_offset_coverage_count") or 0),
                "source_updated_at": _clean(session.get("updated_at"), limit=80),
                "coverage_source": _clean(session.get("coverage_source") or "canonical_sessions", limit=160),
                "declared_project_ids": _as_list(session.get("declared_project_ids")),
                "declared_series_ids": _as_list(session.get("declared_series_ids")),
                "declared_reading_area_ids": _as_list(session.get("declared_reading_area_ids")),
                "source_content_sha256": _clean(session.get("source_content_sha256"), limit=128),
                "content_duplicate_group": _clean(session.get("content_duplicate_group"), limit=160),
                "content_duplicate_of": _clean(session.get("content_duplicate_of"), limit=120),
                "content_duplicate_canonical_session_key": _clean(session.get("content_duplicate_canonical_session_key"), limit=120),
                "content_duplicate_canonical_ref": _clean(session.get("content_duplicate_canonical_ref"), limit=500),
            }
        )
        exclusion_reason = _session_exclusion_reason(session)
        if exclusion_reason and entry.get("status") in {"queued", "skipped", "excluded"}:
            entry["previous_status"] = entry.get("status")
            entry["status"] = "excluded"
            entry["exclude_reason"] = exclusion_reason
            entry["updated_at"] = _now()
        elif entry.get("status") == "excluded" and entry.get("exclude_reason") == "source_system_not_in_current_distill_scope":
            entry["previous_status"] = "excluded"
            entry["previous_exclude_reason"] = "source_system_not_in_current_distill_scope"
            entry["status"] = "queued" if _clean(session.get("source_path") or session.get("raw_path"), limit=1000) else "skipped"
            entry.pop("exclude_reason", None)
            if entry["status"] == "skipped":
                entry["skip_reason"] = "missing_source_path"
            entry["updated_at"] = _now()
        if entry.get("distill_version") != distill_version and entry.get("status") == "covered":
            entry["previous_status"] = "covered"
            entry["status"] = "queued"
            entry["distill_version"] = distill_version
            entry["updated_at"] = _now()
            marked_for_redistill += 1
    rows = sorted(by_key.values(), key=_coverage_ledger_sort_key)
    _write_jsonl_atomic(ledger_path, rows)
    statuses: dict[str, int] = {}
    for row in rows:
        statuses[row.get("status", "unknown")] = statuses.get(row.get("status", "unknown"), 0) + 1
    return {
        "ok": True,
        "contract": DISTILL_COVERAGE_LEDGER_CONTRACT,
        "records_db_path": str(records_db_path),
        "ledger_path": str(ledger_path),
        "session_count": len(sessions),
        "canonical_session_count": canonical_session_count,
        "declared_mimocode_session_count": declared_mimocode_session_count,
        "ledger_row_count": len(rows),
        "added": added,
        "marked_for_redistill": marked_for_redistill,
        "status_counts": statuses,
        "write_performed": True,
    }


def _coverage_ledger_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    status = str(row.get("status") or "")
    active = 0 if status in _QUEUE_STATUSES else 1
    return (
        str(row.get("source_system") or ""),
        active,
        -int(row.get("source_size_bytes") or row.get("raw_size_bytes") or 0),
        -int(row.get("indexed_message_count") or 0),
        str(row.get("source_updated_at") or ""),
        str(row.get("session_key") or ""),
    )


def load_distill_model_config(config: dict[str, Any] | None = None, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or os.environ
    cfg = dict(config or {})
    provider = _clean(cfg.get("provider") or env.get("TIME_LIBRARY_DISTILL_PROVIDER"), limit=120)
    model = _clean(cfg.get("model") or env.get("TIME_LIBRARY_DISTILL_MODEL"), limit=160)
    api_key_env = _clean(cfg.get("api_key_env") or env.get("TIME_LIBRARY_DISTILL_API_KEY_ENV"), limit=120)
    api_key = _clean(
        cfg.get("api_key")
        or env.get("TIME_LIBRARY_DISTILL_API_KEY")
        or (env.get(api_key_env) if api_key_env else ""),
        limit=400,
    )
    model_available = bool(provider and model and (api_key or provider in {"local", "ollama", "none"}))
    blockers: list[str] = []
    if not provider:
        blockers.append("provider_missing")
    if not model:
        blockers.append("model_missing")
    if provider not in {"local", "ollama", "none"} and not api_key:
        blockers.append("api_key_missing")
    return {
        "provider": provider,
        "model": model,
        "api_key_env": api_key_env,
        "api_key_present": bool(api_key),
        "model_available": model_available,
        "blockers": blockers,
        "budget_tokens_per_window": int(cfg.get("budget_tokens_per_window") or env.get("TIME_LIBRARY_DISTILL_WINDOW_TOKENS") or 0),
        "target_shape": _clean(cfg.get("target_shape") or env.get("TIME_LIBRARY_DISTILL_TARGET_SHAPE"), limit=80),
        "target_shapes": [_clean(item, limit=80) for item in _as_list(cfg.get("target_shapes")) if _clean(item, limit=80)],
    }


def _candidate_dir(root: str | Path, shelf: str) -> Path:
    base = Path(root)
    if shelf == "xingce":
        return base / "output" / "xingce_work_experience" / "candidates"
    if shelf == "toolbook":
        return base / "output" / "toolbook_platform_facts" / "candidates"
    return base / "output" / "zhiyi_preference_cards" / "candidates"


def _candidate_path(root: str | Path, candidate: dict[str, Any]) -> Path:
    shelf = _candidate_shelf(candidate)
    cid = _clean(candidate.get("candidate_id") or candidate.get("exp_id") or hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12], limit=160)
    suffix = "-candidate.json" if shelf == "xingce" and not cid.endswith("-candidate") else ".json"
    return _candidate_dir(root, shelf) / f"{cid}{suffix}"


def _candidate_shelf(candidate: dict[str, Any]) -> str:
    return _clean(
        candidate.get("library_shelf")
        or ("toolbook" if candidate.get("candidate_type") == "toolbook_candidate" else "")
        or ("xingce" if candidate.get("candidate_type") == "xingce_work_experience" else "zhiyi"),
        limit=40,
    )


def _candidate_dedupe_key(candidate: dict[str, Any]) -> str:
    explicit = _clean(candidate.get("dedupe_key"), limit=240).lower()
    if re.fullmatch(r"[0-9a-f]{20}", explicit):
        return explicit
    raw = _clean(
        explicit
        or candidate.get("preference_statement")
        or candidate.get("observed_behavior")
        or candidate.get("work_scenario")
        or candidate.get("platform")
        or candidate.get("title")
        or candidate.get("summary"),
        limit=240,
    ).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20] if raw else ""


def _candidate_evidence_dedupe_key(candidate: dict[str, Any]) -> str:
    refs = _candidate_source_refs(candidate)
    offsets = _candidate_byte_offsets(refs)
    source_path = _clean(refs.get("resolved_source_path") or refs.get("source_path"), limit=1000)
    try:
        start = int(offsets.get("start"))
        end = int(offsets.get("end"))
    except (TypeError, ValueError):
        return ""
    if not source_path or start < 0 or end <= start:
        return ""
    seed = "|".join(
        [
            "evidence",
            _candidate_shelf(candidate),
            source_path,
            str(start),
            str(end),
            hashlib.sha256(str(candidate.get("verbatim_excerpt") or "").encode("utf-8")).hexdigest(),
        ]
    )
    return "evidence:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _candidate_index_keys(candidate: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for key in (_candidate_dedupe_key(candidate), _candidate_evidence_dedupe_key(candidate)):
        if key and key not in keys:
            keys.append(key)
    return keys


def _candidate_inactive_match_keys(candidate: dict[str, Any]) -> list[str]:
    shelf = _candidate_shelf(candidate)
    keys: list[str] = []
    verbatim_sha = _clean(candidate.get("verbatim_sha256"), limit=128)
    if not verbatim_sha:
        verbatim = str(candidate.get("verbatim_excerpt") or "")
        if verbatim:
            verbatim_sha = hashlib.sha256(verbatim.encode("utf-8")).hexdigest()
    if verbatim_sha:
        keys.append(f"inactive-verbatim:{shelf}:{verbatim_sha}")
    for value in (
        candidate.get("preference_statement"),
        candidate.get("work_scenario"),
        candidate.get("observed_behavior"),
        candidate.get("title"),
        candidate.get("summary"),
    ):
        topic = _clean(value, limit=240).lower()
        if topic:
            keys.append(f"inactive-topic:{shelf}:{hashlib.sha256(topic.encode('utf-8')).hexdigest()[:20]}")
    deduped: list[str] = []
    for key in keys:
        if key not in deduped:
            deduped.append(key)
    return deduped


def _candidate_inactive_status(candidate: dict[str, Any]) -> str:
    return _clean(candidate.get("lifecycle_status") or candidate.get("status"), limit=80).lower()


def _avoid_candidate_path_collision(root: str | Path, candidate: dict[str, Any], *, dedupe_key: str, session_key: str) -> None:
    path = _candidate_path(root, candidate)
    if not path.exists():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        existing = {}
    if isinstance(existing, dict) and _candidate_dedupe_key(existing) == dedupe_key:
        return
    base_id = _clean(candidate.get("candidate_id") or candidate.get("exp_id") or "distill-auto", limit=130)
    refs = _candidate_source_refs(candidate)
    seed = json.dumps(
        {
            "base_id": base_id,
            "dedupe_key": dedupe_key,
            "session_key": session_key,
            "source_path": refs.get("source_path") or refs.get("resolved_source_path"),
            "byte_offsets": _candidate_byte_offsets(refs),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    for attempt in range(6):
        suffix = hashlib.sha256(f"{seed}|{attempt}".encode("utf-8")).hexdigest()[:10]
        candidate["candidate_id"] = f"{base_id}-{suffix}"
        if _candidate_shelf(candidate) == "zhiyi":
            candidate["exp_id"] = candidate["candidate_id"]
        if not _candidate_path(root, candidate).exists():
            return


def _load_candidate_index(root: str | Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for directory in (
        Path(root) / "output" / "zhiyi_preference_cards" / "candidates",
        Path(root) / "output" / "xingce_work_experience" / "candidates",
        Path(root) / "output" / "toolbook_platform_facts" / "candidates",
    ):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                candidate = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for key in _candidate_index_keys(candidate):
                index.setdefault(key, {"candidate": candidate, "path": path})
            if _candidate_inactive_status(candidate) in _INACTIVE_CANDIDATE_STATUSES:
                for key in _candidate_inactive_match_keys(candidate):
                    index.setdefault(key, {"candidate": candidate, "path": path})
    return index


def _valid_evidence_bound_candidate(candidate: dict[str, Any]) -> tuple[bool, str]:
    _populate_candidate_verbatim_sha256(candidate)
    allowed_source_modes = {"evidence_bound_model_distill"}
    if _candidate_shelf(candidate) == "toolbook":
        allowed_source_modes.add("evidence_bound_p2_extract")
    if candidate.get("source_mode") not in allowed_source_modes:
        return False, "source_mode_not_evidence_bound_model_distill"
    shelf = _candidate_shelf(candidate)
    source_author = _candidate_source_author(candidate)
    if not source_author:
        return False, "source_author_missing"
    if shelf == "zhiyi" and source_author != "user":
        return False, "source_author_not_user"
    if shelf == "xingce" and source_author not in {"assistant", "source_testing", "user"}:
        return False, "source_author_not_allowed_for_xingce"
    if shelf == "toolbook" and source_author not in {"assistant", "source_testing", "user", "tool", "system"}:
        return False, "source_author_not_allowed_for_toolbook"
    if shelf == "toolbook" and _toolbook_noisy_attachment_payload(candidate):
        return False, "toolbook_noisy_attachment_payload"
    if shelf == "toolbook" and _toolbook_low_quality_summary(candidate):
        return False, "toolbook_low_quality_summary"
    if not _clean(candidate.get("verbatim_excerpt"), limit=4000):
        return False, "verbatim_missing"
    refs = _candidate_source_refs(candidate)
    offsets = _candidate_byte_offsets(refs)
    source_path = refs.get("resolved_source_path") or refs.get("source_path")
    if not source_path:
        return False, "source_path_missing"
    if "start" not in offsets or "end" not in offsets:
        return False, "byte_offsets_missing"
    try:
        start = int(offsets.get("start"))
        end = int(offsets.get("end"))
    except (TypeError, ValueError):
        return False, "byte_offsets_invalid"
    if start < 0 or end <= start:
        return False, "byte_offsets_invalid"
    source_file = Path(str(source_path)).expanduser()
    if not source_file.is_file():
        return False, "source_path_unreadable"
    if source_file.stat().st_size < end:
        return False, "byte_offsets_out_of_range"
    try:
        with source_file.open("rb") as f:
            f.seek(start)
            raw = f.read(end - start)
    except OSError:
        return False, "source_path_unreadable"
    source_text = raw.decode("utf-8", errors="ignore")
    if str(candidate.get("verbatim_excerpt") or "") != source_text:
        return False, "verbatim_source_mismatch"
    expected_sha = _clean(candidate.get("verbatim_sha256"), limit=128)
    if not expected_sha:
        return False, "verbatim_sha256_missing"
    if expected_sha != hashlib.sha256(raw).hexdigest():
        return False, "verbatim_sha256_mismatch"
    return True, ""


def _candidate_verbatim_source_slice(candidate: dict[str, Any]) -> tuple[bytes, str]:
    refs = _candidate_source_refs(candidate)
    offsets = _candidate_byte_offsets(refs)
    source_path = refs.get("resolved_source_path") or refs.get("source_path")
    if not source_path or "start" not in offsets or "end" not in offsets:
        return b"", ""
    try:
        start = int(offsets.get("start"))
        end = int(offsets.get("end"))
    except (TypeError, ValueError):
        return b"", ""
    if start < 0 or end <= start:
        return b"", ""
    source_file = Path(str(source_path)).expanduser()
    if not source_file.is_file():
        return b"", ""
    try:
        if source_file.stat().st_size < end:
            return b"", ""
        with source_file.open("rb") as f:
            f.seek(start)
            raw = f.read(end - start)
    except OSError:
        return b"", ""
    return raw, raw.decode("utf-8", errors="ignore")


def _populate_candidate_verbatim_sha256(candidate: dict[str, Any]) -> str:
    existing = _clean(candidate.get("verbatim_sha256"), limit=128)
    if existing:
        return existing
    raw, source_text = _candidate_verbatim_source_slice(candidate)
    if not raw or str(candidate.get("verbatim_excerpt") or "") != source_text:
        return ""
    sha = hashlib.sha256(raw).hexdigest()
    candidate["verbatim_sha256"] = sha
    refs = candidate.get("source_refs")
    if isinstance(refs, dict):
        refs = dict(refs)
        refs.setdefault("verbatim_sha256", sha)
        candidate["source_refs"] = refs
    evidence_refs = candidate.get("evidence_refs")
    if isinstance(evidence_refs, list):
        updated = []
        applied = False
        for item in evidence_refs:
            if isinstance(item, dict):
                item = dict(item)
                if not applied and (item.get("source_path") or item.get("resolved_source_path")):
                    item.setdefault("verbatim_sha256", sha)
                    applied = True
            updated.append(item)
        candidate["evidence_refs"] = updated
    return sha


def _candidate_source_ref_label(candidate: dict[str, Any]) -> str:
    refs = _candidate_source_refs(candidate)
    offsets = _candidate_byte_offsets(refs)
    source_path = _clean(refs.get("source_path") or refs.get("resolved_source_path"), limit=1000)
    if not source_path:
        return ""
    start = offsets.get("start")
    end = offsets.get("end")
    if start is None or end is None:
        return source_path
    return f"{source_path}:{start}-{end}"


def _user_author_verbatim_report(candidate: dict[str, Any], write_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "library_id": _clean(write_result.get("library_id"), limit=80),
        "candidate_id": _clean(write_result.get("candidate_id"), limit=180),
        "shelf": _candidate_shelf(candidate),
        "title": _clean(candidate.get("title"), limit=240),
        "source_author": _candidate_source_author(candidate),
        "source_ref": _candidate_source_ref_label(candidate),
        "verbatim_sha256": _clean(candidate.get("verbatim_sha256"), limit=128),
        "verbatim_excerpt": str(candidate.get("verbatim_excerpt") or ""),
        "write_status": "merged" if write_result.get("merged") else "written",
    }


def _candidate_source_author(candidate: dict[str, Any]) -> str:
    refs = _candidate_source_refs(candidate)
    return _clean(
        candidate.get("source_author")
        or candidate.get("source_role")
        or refs.get("source_author")
        or refs.get("source_role"),
        limit=80,
    ).lower()


def _candidate_project_id(candidate: dict[str, Any], session: dict[str, Any]) -> str:
    for value in (
        candidate.get("project_id"),
        candidate.get("declared_project_id"),
        candidate.get("declared_project_ids"),
        session.get("declared_project_ids"),
    ):
        for item in _as_list(value):
            text = _clean(item, limit=160)
            if text:
                return text
    return ""


def _valid_project_history_candidate(candidate: dict[str, Any], session: dict[str, Any]) -> tuple[bool, str]:
    if candidate.get("source_mode") != "evidence_bound_project_history_digest":
        return False, "source_mode_not_evidence_bound_project_history_digest"
    if not _clean(candidate.get("title"), limit=200):
        return False, "title_missing"
    if not _clean(candidate.get("summary"), limit=600):
        return False, "summary_missing"
    if not _candidate_project_id(candidate, session):
        return False, "declared_project_id_missing"
    if not _clean(candidate.get("verbatim_excerpt"), limit=4000):
        return False, "verbatim_missing"
    refs = _candidate_source_refs(candidate)
    offsets = _candidate_byte_offsets(refs)
    source_path = refs.get("resolved_source_path") or refs.get("source_path")
    if not source_path:
        return False, "source_path_missing"
    if "start" not in offsets or "end" not in offsets:
        return False, "byte_offsets_missing"
    try:
        start = int(offsets.get("start"))
        end = int(offsets.get("end"))
    except (TypeError, ValueError):
        return False, "byte_offsets_invalid"
    if start < 0 or end <= start:
        return False, "byte_offsets_invalid"
    source_file = Path(str(source_path)).expanduser()
    if not source_file.is_file():
        return False, "source_path_unreadable"
    try:
        if source_file.stat().st_size < end:
            return False, "byte_offsets_out_of_range"
        with source_file.open("rb") as f:
            f.seek(start)
            raw = f.read(end - start)
    except OSError:
        return False, "source_path_unreadable"
    source_text = raw.decode("utf-8", errors="ignore")
    if str(candidate.get("verbatim_excerpt") or "") != source_text:
        return False, "verbatim_source_mismatch"
    sha = _clean(candidate.get("verbatim_sha256"), limit=128)
    if not sha:
        return False, "verbatim_sha256_missing"
    if sha != hashlib.sha256(raw).hexdigest():
        return False, "verbatim_sha256_mismatch"
    return True, ""


def _project_history_source_ref(candidate: dict[str, Any]) -> dict[str, Any]:
    refs = _candidate_source_refs(candidate)
    offsets = _candidate_byte_offsets(refs)
    out = dict(refs)
    out["byte_offsets"] = dict(offsets)
    out.setdefault("source_mode", "evidence_bound_project_history_digest")
    out.setdefault("source_author", _candidate_source_author(candidate))
    out.setdefault("verbatim_excerpt", str(candidate.get("verbatim_excerpt") or ""))
    out.setdefault("verbatim_sha256", _clean(candidate.get("verbatim_sha256"), limit=128))
    return out


def _write_project_history_record_from_candidate(
    candidate: dict[str, Any],
    *,
    session: dict[str, Any],
    session_key: str,
    reading_area_registry_path: str | Path | None,
) -> dict[str, Any]:
    try:
        from src import reading_area_registry as registry
    except Exception:  # pragma: no cover
        import reading_area_registry as registry
    source_system = _clean(session.get("source_system"), limit=120)
    canonical_window_id = _clean(session.get("canonical_window_id"), limit=240)
    session_id = _clean(session.get("session_id"), limit=240)
    project_id = _candidate_project_id(candidate, session)
    card = registry.resolve_borrowing_card(
        source_system=source_system,
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        path=reading_area_registry_path,
    )
    if not card.get("ok"):
        return {
            "written": False,
            "merged": False,
            "error": "declared_borrowing_card_required_for_project_history",
        }
    else:
        card_id = str(card.get("card_id") or "")
    result = registry.write_project_history_record(
        borrowing_card_id=card_id,
        history_type=_clean(candidate.get("history_type"), limit=60) or "milestone",
        project_id=project_id,
        title=_clean(candidate.get("title"), limit=160),
        summary=_clean(candidate.get("summary"), limit=500),
        source_refs=[_project_history_source_ref(candidate)],
        request_id=_clean(candidate.get("request_id") or candidate.get("candidate_id") or session_key, limit=160),
        path=reading_area_registry_path,
    )
    if not result.get("ok"):
        return {"written": False, "merged": False, "error": str(result.get("error") or "project_history_write_failed")}
    return {
        "written": not bool(result.get("already_recorded")),
        "merged": False,
        "candidate_id": _clean(candidate.get("candidate_id"), limit=180),
        "library_id": result.get("record_id", ""),
        "path": str(reading_area_registry_path or ""),
        "record_id": result.get("record_id", ""),
        "project_history": True,
    }


def _toolbook_noisy_attachment_payload(candidate: dict[str, Any]) -> bool:
    text = "\n".join(
        str(candidate.get(key) or "")
        for key in ("title", "summary", "detail", "observed_behavior", "verbatim_excerpt")
    ).lower()
    return any(
        marker in text
        for marker in (
            "# files mentioned by the user:",
            "files mentioned by the user",
            "<image name=",
            "data:image/",
            "input_image",
            "base64,",
            "<environment_context>",
            "<filesystem>",
            "<current_date>",
        )
    )


def _toolbook_low_quality_summary(candidate: dict[str, Any]) -> bool:
    summary = _clean(candidate.get("summary") or candidate.get("observed_behavior") or candidate.get("title"), limit=1200).strip("。.!！ ")
    if summary in {"记好了", "收到", "成了", "好的", "明白"}:
        return True
    return is_low_quality_toolbook_record(candidate)


def _candidate_source_refs(candidate: dict[str, Any]) -> dict[str, Any]:
    refs = candidate.get("source_refs")
    if isinstance(refs, dict):
        return dict(refs)
    evidence_refs = candidate.get("evidence_refs")
    if isinstance(evidence_refs, list):
        for item in evidence_refs:
            if isinstance(item, dict) and (item.get("source_path") or item.get("resolved_source_path")):
                return dict(item)
    return {}


def _candidate_byte_offsets(refs: dict[str, Any]) -> dict[str, Any]:
    offsets = refs.get("byte_offsets") if isinstance(refs.get("byte_offsets"), dict) else {}
    computed = offsets.get("_computed_verbatim") if isinstance(offsets.get("_computed_verbatim"), dict) else {}
    if computed:
        return computed
    if "start" in offsets or "end" in offsets:
        return offsets
    resolution = refs.get("resolution_report") if isinstance(refs.get("resolution_report"), dict) else {}
    computed = resolution.get("computed_byte_offsets") if isinstance(resolution.get("computed_byte_offsets"), dict) else {}
    return computed if computed else {}


def _normalize_candidate_source_fields(candidate: dict[str, Any]) -> None:
    refs = _candidate_source_refs(candidate)
    offsets = _candidate_byte_offsets(refs)
    source_path = _clean(refs.get("resolved_source_path") or refs.get("source_path"), limit=1000)
    if source_path:
        candidate.setdefault("source_path", source_path)
    if offsets:
        candidate["byte_offsets"] = dict(offsets)
    if source_path and offsets.get("start") is not None and offsets.get("end") is not None:
        candidate.setdefault("source_ref", f"{source_path}:{offsets.get('start')}-{offsets.get('end')}")
    sha = _clean(candidate.get("verbatim_sha256"), limit=128)
    if refs and sha:
        refs = dict(refs)
        refs.setdefault("verbatim_sha256", sha)
        candidate["source_refs"] = refs


def _write_or_merge_candidate(root: str | Path, candidate: dict[str, Any], *, session_key: str, existing_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidate = dict(candidate)
    _populate_candidate_verbatim_sha256(candidate)
    _normalize_candidate_source_fields(candidate)
    candidate.setdefault("source_author", _candidate_source_author(candidate))
    candidate.setdefault("candidate_id", "distill-auto-" + hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12])
    shelf = _candidate_shelf(candidate)
    if shelf == "xingce":
        candidate.setdefault("library_shelf", "xingce")
    if shelf == "toolbook":
        candidate.setdefault("library_shelf", "toolbook")
        candidate.setdefault("_type", "toolbook_candidate")
        candidate.setdefault("type", "toolbook_candidate")
        candidate.setdefault("exp_id", candidate.get("candidate_id"))
    if shelf == "zhiyi":
        candidate.setdefault("_type", "zhiyi_preference_card")
        candidate.setdefault("type", "preference_memory")
        candidate.setdefault("exp_id", candidate.get("candidate_id"))
    candidate.setdefault("lifecycle_status", "active" if shelf == "zhiyi" else "candidate")
    candidate.setdefault("coverage_session_keys", [])
    candidate["coverage_session_keys"] = sorted(set([*_as_list(candidate.get("coverage_session_keys")), session_key]))
    key = _candidate_dedupe_key(candidate)
    existing_key = next((item for item in [*_candidate_index_keys(candidate), *_candidate_inactive_match_keys(candidate)] if item in existing_index), "")
    if existing_key:
        existing = dict(existing_index[existing_key]["candidate"])
        existing_valid, _ = _valid_evidence_bound_candidate(existing)
        if not existing_valid:
            existing_index.pop(existing_key, None)
        else:
            existing_status = _clean(existing.get("lifecycle_status") or existing.get("status"), limit=80).lower()
            if existing_status in _INACTIVE_CANDIDATE_STATUSES:
                path = Path(existing_index[existing_key]["path"])
                return {
                    "written": False,
                    "merged": False,
                    "skipped": True,
                    "skip_reason": "candidate_matches_inactive_record",
                    "inactive_lifecycle_status": existing_status,
                    "candidate_id": existing.get("candidate_id") or existing.get("exp_id"),
                    "library_id": library_id_for(existing),
                    "path": str(path),
                }
            refs = existing.get("merged_source_refs") if isinstance(existing.get("merged_source_refs"), list) else []
            refs.append(candidate.get("source_refs", {}))
            existing["merged_source_refs"] = refs
            existing["coverage_session_keys"] = sorted(set([*_as_list(existing.get("coverage_session_keys")), session_key]))
            existing["dedupe_merged"] = True
            existing["updated_at"] = _now()
            path = Path(existing_index[existing_key]["path"])
            path.write_text(json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            library_id = library_id_for(existing)
            return {"written": False, "merged": True, "candidate_id": existing.get("candidate_id") or existing.get("exp_id"), "library_id": library_id, "path": str(path)}
    candidate = apply_annotation(candidate)
    path = _candidate_path(root, candidate)
    _avoid_candidate_path_collision(root, candidate, dedupe_key=key, session_key=session_key)
    path = _candidate_path(root, candidate)
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate["dedupe_key"] = key
    candidate.setdefault("created_at", _now())
    candidate.setdefault("updated_at", _now())
    path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    action_path = ""
    if shelf == "xingce":
        action_path = _write_xingce_auto_action(root, candidate, path)
    for index_key in _candidate_index_keys(candidate):
        existing_index.setdefault(index_key, {"candidate": candidate, "path": path})
    library_id = library_id_for(candidate)
    result = {"written": True, "merged": False, "candidate_id": candidate.get("candidate_id") or candidate.get("exp_id"), "library_id": library_id, "path": str(path)}
    if action_path:
        result["action_path"] = action_path
    return result


def _is_no_evidence_skip_reason(reason: str) -> bool:
    clean = _clean(reason, limit=160)
    return clean in _NO_EVIDENCE_SKIP_REASONS or clean.startswith("no_evidence")


def _distill_report_summary(reports: list[Any]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        steps = report.get("steps") if isinstance(report.get("steps"), dict) else {}
        s0 = steps.get("S0_select") if isinstance(steps.get("S0_select"), dict) else {}
        s2 = steps.get("S2_distill") or steps.get("S2_model_distill") or {}
        if not isinstance(s2, dict):
            s2 = {}
        s3 = steps.get("S3_validate") if isinstance(steps.get("S3_validate"), dict) else {}
        summary.append(
            {
                "shelf": _clean(report.get("shelf"), limit=40),
                "input_records": int(report.get("input_records") or 0),
                "candidate_object_count": int(report.get("candidate_object_count") or 0),
                "owner_sample_count": int(report.get("owner_sample_count") or 0),
                "s0_selected": int(s0.get("selected") or s0.get("worthy") or 0),
                "s0_rejected": int(s0.get("rejected") or 0),
                "s2_cards_or_refined": int(s2.get("cards") or s2.get("refined") or 0),
                "s3_passed": int(s3.get("passed") or 0),
                "s3_fail_reasons": dict(s3.get("fail_reasons") or {}) if isinstance(s3.get("fail_reasons"), dict) else {},
            }
        )
    return summary[:4]


def _empty_window_sample_for_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_key": _clean(row.get("session_key"), limit=120),
        "skip_reason": _clean(row.get("skip_reason"), limit=240),
        "source_system": _clean(row.get("source_system"), limit=120),
        "canonical_window_id": _clean(row.get("canonical_window_id"), limit=240),
        "source_path": _clean(row.get("source_path"), limit=1000),
        "source_size_bytes": int(row.get("source_size_bytes") or row.get("raw_size_bytes") or 0),
        "indexed_message_count": int(row.get("indexed_message_count") or 0),
        "raw_offset_coverage_count": int(row.get("raw_offset_coverage_count") or 0),
        "false_negative_sample_result": "no_true_card_found_by_distill_reports",
        "false_negative_found": False,
        "distill_report_summary": _distill_report_summary(_as_list(row.get("distill_reports"))),
    }


def _recent_empty_window_samples_from_rows(
    rows: list[dict[str, Any]],
    *,
    status_key: str,
    current_samples: list[dict[str, Any]],
    limit: int = 3,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in current_samples:
        if not isinstance(sample, dict):
            continue
        key = _clean(sample.get("session_key"), limit=240)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        samples.append(sample)
        if len(samples) >= limit:
            return samples
    sample_key = f"{status_key}_empty_window_sample"
    for row in reversed(rows):
        sample = row.get(sample_key)
        if not isinstance(sample, dict):
            continue
        key = _clean(sample.get("session_key"), limit=240)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        samples.append(sample)
        if len(samples) >= limit:
            break
    return samples


def _write_xingce_auto_action(root: str | Path, candidate: dict[str, Any], candidate_path: Path) -> str:
    actions_dir = Path(root) / "output" / "xingce_work_experience" / "actions"
    actions_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = _clean(candidate.get("candidate_id") or "", limit=160)
    safe_id = "".join(ch for ch in candidate_id if ch.isalnum() or ch in ("-", "_"))[:160]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    action_path = actions_dir / f"{stamp}-{safe_id}-auto_adopt.jsonl"
    receipt = {
        "schema_version": "1.0",
        "action_id": "xingce-action-" + uuid.uuid4().hex[:16],
        "created_at": _now(),
        "candidate_id": safe_id,
        "candidate_type": candidate.get("candidate_type", ""),
        "action": "auto_adopt",
        "action_status": "auto_adopted_evidence_bound",
        "operator": "distill_automation_runner",
        "reason": "auto-adopted by evidence-bound coverage runner; no human review gate",
        "source_candidate_path": str(candidate_path),
        "source_mode": candidate.get("source_mode", ""),
        "write_boundary": {
            "action_receipt_write_performed": True,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "notes": [
            "auto_distill_action_receipt",
            "evidence_bound_auto_adopted",
            "no_human_review_gate",
            "candidate_artifact_not_modified",
        ],
    }
    with action_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        f.write("\n")
    return str(action_path)


def _empty_self_check_for_window(result: dict[str, Any], *, reason: str) -> dict[str, Any]:
    self_check = run_window_self_check(
        result,
        catalog_library_ids=[],
        borrow_results={},
        instructions_char_count=0,
        contains_body_markers=False,
    )
    blockers = list(self_check.get("blockers", []))
    blockers.append(reason)
    self_check["ok"] = False
    self_check["blockers"] = sorted(set(blockers))
    return self_check


def _mark_window_rows_self_check_failed(
    ledger_path: str | Path,
    *,
    session_keys: list[str],
    blockers: list[str],
    status_key: str = "status",
) -> None:
    if not session_keys:
        return
    failed_keys = set(session_keys)
    rows = _read_jsonl(ledger_path)
    changed = False
    for row in rows:
        if row.get("session_key") not in failed_keys or row.get(status_key) not in {"covered", _PENDING_SELF_CHECK_STATUS}:
            continue
        row[f"previous_{status_key}"] = row.get(status_key)
        row[status_key] = "self_check_failed"
        row[f"{status_key}_self_check_blockers"] = list(blockers)
        row["updated_at"] = _now()
        changed = True
    if changed:
        _write_jsonl_atomic(ledger_path, rows)


def _mark_window_rows_self_check_passed(
    ledger_path: str | Path,
    *,
    session_keys: list[str],
    status_key: str = "status",
) -> None:
    if not session_keys:
        return
    passed_keys = set(session_keys)
    rows = _read_jsonl(ledger_path)
    changed = False
    for row in rows:
        if row.get("session_key") not in passed_keys or row.get(status_key) != _PENDING_SELF_CHECK_STATUS:
            continue
        row[status_key] = "covered"
        row.pop(f"previous_{status_key}", None)
        row.pop(f"{status_key}_self_check_blockers", None)
        row["updated_at"] = _now()
        changed = True
    if changed:
        _write_jsonl_atomic(ledger_path, rows)


def _resolve_self_check_payload(
    self_check_inputs: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    if callable(self_check_inputs):
        return self_check_inputs(result) or {}
    if isinstance(self_check_inputs, dict):
        return dict(self_check_inputs)
    result["self_check_inputs_missing"] = True
    return {
        "catalog_library_ids": [],
        "borrow_results": {},
        "instructions_char_count": 0,
        "contains_body_markers": False,
    }


def _run_post_window_self_check(
    result: dict[str, Any],
    self_check_inputs: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> dict[str, Any]:
    self_check_payload = _resolve_self_check_payload(self_check_inputs, result)
    if str(result.get("target_shape") or "") == PROJECT_HISTORY_TARGET_SHAPE:
        return run_project_history_window_self_check(
            result,
            project_history_record_ids=self_check_payload.get("project_history_record_ids") or [],
            project_page_history_ids=self_check_payload.get("project_page_history_ids") or [],
            borrow_results=self_check_payload.get("borrow_results") or {},
            instructions_char_count=int(self_check_payload.get("instructions_char_count") or 0),
            contains_body_markers=bool(self_check_payload.get("contains_body_markers", False)),
            char_budget=int(self_check_payload.get("char_budget") or 1500),
        )
    return run_window_self_check(
        result,
        catalog_library_ids=self_check_payload.get("catalog_library_ids") or [],
        borrow_results=self_check_payload.get("borrow_results") or {},
        instructions_char_count=int(self_check_payload.get("instructions_char_count") or 0),
        contains_body_markers=bool(self_check_payload.get("contains_body_markers", False)),
        char_budget=int(self_check_payload.get("char_budget") or 1500),
    )


def _with_failed_self_check(result: dict[str, Any], self_check: dict[str, Any]) -> dict[str, Any]:
    result["post_window_self_check"] = self_check
    if not self_check.get("ok"):
        result["ok"] = False
        result["status"] = "self_check_failed"
        result["self_check_blockers"] = self_check.get("blockers", [])
    return result


def run_distill_window(
    *,
    records_db_path: str | Path,
    ledger_path: str | Path,
    candidate_root: str | Path,
    model_config: dict[str, Any] | None = None,
    distill_session: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    distill_version: str = DEFAULT_DISTILL_VERSION,
    source_systems: list[str] | tuple[str, ...] | str | None = None,
    reading_area_registry_path: str | Path | None = None,
    mimocode_root: str | Path | None = None,
    project_ids: list[str] | tuple[str, ...] | str | None = None,
    series_ids: list[str] | tuple[str, ...] | str | None = None,
    max_sessions: int = 20,
    self_check_inputs: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    target_shape: str = "",
) -> dict[str, Any]:
    """Run one bounded automatic distillation window."""

    reconcile = reconcile_coverage_ledger(
        records_db_path=records_db_path,
        ledger_path=ledger_path,
        distill_version=distill_version,
        source_systems=source_systems,
        reading_area_registry_path=reading_area_registry_path,
        mimocode_root=mimocode_root,
        project_ids=project_ids,
        series_ids=series_ids,
    )
    rows = _read_jsonl(ledger_path)
    target_shape = _clean(target_shape or (model_config or {}).get("target_shape"), limit=80)
    status_key = "status"
    target_prefix = ""
    if target_shape:
        target_prefix = f"{target_shape}_"
        status_key = f"{target_shape}_status"
        initialized = False
        for row in rows:
            if row.get(status_key):
                continue
            initial_status, reason_key, reason_value = _initial_target_shape_status(row, target_shape)
            row[status_key] = initial_status
            if reason_value:
                row[f"{target_prefix}{reason_key}"] = reason_value
            initialized = True
        if initialized:
            _write_jsonl_atomic(ledger_path, rows)
    model = load_distill_model_config({**(model_config or {}), "target_shape": target_shape} if target_shape else model_config)
    if not model["model_available"]:
        for row in rows:
            if row.get(status_key) in _QUEUE_STATUSES:
                row[status_key] = "pending_model_config"
                row["model_blockers"] = model["blockers"]
                row["updated_at"] = _now()
        _write_jsonl_atomic(ledger_path, rows)
        result = {
            "ok": False,
            "contract": DISTILL_RUNNER_CONTRACT,
            "reconcile": reconcile,
            "status": "pending_model_config",
            "target_shape": target_shape,
            "model_blockers": model["blockers"],
            "processed_session_count": 0,
            "produced_candidate_count": 0,
            "write_performed": True,
        }
        result["post_window_self_check"] = _empty_self_check_for_window(result, reason="model_config_pending_no_distillation_window")
        return result
    if distill_session is None:
        result = {
            "ok": False,
            "contract": DISTILL_RUNNER_CONTRACT,
            "reconcile": reconcile,
            "status": "distiller_not_configured",
            "target_shape": target_shape,
            "processed_session_count": 0,
            "produced_candidate_count": 0,
            "write_performed": False,
        }
        result["post_window_self_check"] = _empty_self_check_for_window(result, reason="distiller_not_configured_no_distillation_window")
        return result

    session_map = {
        session["session_key"]: session
        for session in load_coverage_sessions(
            records_db_path,
            source_systems=source_systems,
            reading_area_registry_path=reading_area_registry_path,
            mimocode_root=mimocode_root,
            project_ids=project_ids,
            series_ids=series_ids,
        )
    }
    existing_index = _load_candidate_index(candidate_root)
    processed = 0
    produced = 0
    merged = 0
    rejected = 0
    failures = 0
    produced_library_ids: list[str] = []
    produced_project_history_ids: list[str] = []
    user_author_new_card_verbatims: list[dict[str, Any]] = []
    processed_keys: list[str] = []
    skip_reason_counts: dict[str, int] = {}
    empty_window_skip_samples: list[dict[str, Any]] = []
    for row in rows:
        if row.get(status_key) not in _QUEUE_STATUSES:
            continue
        if not _source_system_matches_filter(row.get("source_system"), source_systems):
            continue
        if max_sessions and processed >= int(max_sessions):
            break
        session = session_map.get(row.get("session_key"))
        if not session:
            row["status"] = "skipped"
            row["skip_reason"] = "session_missing_from_store"
            row["updated_at"] = _now()
            continue
        processed += 1
        processed_keys.append(str(row.get("session_key") or ""))
        attempt_key = f"{target_prefix}attempt_count" if target_prefix else "attempt_count"
        row[attempt_key] = int(row.get(attempt_key) or 0) + 1
        stale_keys = ("failure_reason", "skip_reason", "reject_reasons", "model_blockers") if not target_prefix else (
            f"{target_prefix}failure_reason",
            f"{target_prefix}skip_reason",
            f"{target_prefix}reject_reasons",
            f"{target_prefix}candidate_ids",
            f"{target_prefix}library_ids",
            f"{target_prefix}candidate_paths",
            f"{target_prefix}merged_candidate_count",
            f"previous_{status_key}",
            f"{status_key}_self_check_blockers",
            "model_blockers",
        )
        for stale_key in stale_keys:
            row.pop(stale_key, None)
        try:
            outcome = distill_session(session, model) or {}
        except Exception as exc:
            row[status_key] = "failed"
            row[f"{target_prefix}failure_reason" if target_prefix else "failure_reason"] = f"{type(exc).__name__}:{exc}"
            row["updated_at"] = _now()
            failures += 1
            continue
        candidates = [item for item in _as_list(outcome.get("candidates")) if isinstance(item, dict)]
        row["distill_reports"] = [item for item in _as_list(outcome.get("reports")) if isinstance(item, dict)]
        valid_results: list[dict[str, Any]] = []
        reject_reasons: list[str] = []
        for candidate in candidates:
            if target_shape == PROJECT_HISTORY_TARGET_SHAPE:
                valid, reason = _valid_project_history_candidate(candidate, session)
            else:
                valid, reason = _valid_evidence_bound_candidate(candidate)
            if not valid:
                rejected += 1
                reject_reasons.append(reason)
                continue
            if target_shape == PROJECT_HISTORY_TARGET_SHAPE:
                write_result = _write_project_history_record_from_candidate(
                    candidate,
                    session=session,
                    session_key=str(row["session_key"]),
                    reading_area_registry_path=reading_area_registry_path,
                )
                if write_result.get("error"):
                    rejected += 1
                    reject_reasons.append(str(write_result.get("error")))
                    continue
            else:
                write_result = _write_or_merge_candidate(candidate_root, candidate, session_key=row["session_key"], existing_index=existing_index)
            if write_result.get("skipped"):
                rejected += 1
                reject_reasons.append(str(write_result.get("skip_reason") or "candidate_write_skipped"))
                continue
            valid_results.append(write_result)
            produced_library_ids.append(write_result["library_id"])
            if target_shape == PROJECT_HISTORY_TARGET_SHAPE:
                produced_project_history_ids.append(write_result["library_id"])
            if _candidate_source_author(candidate) == "user":
                user_author_new_card_verbatims.append(_user_author_verbatim_report(candidate, write_result))
            if write_result["merged"]:
                merged += 1
            else:
                produced += 1
        if valid_results:
            row[status_key] = _PENDING_SELF_CHECK_STATUS
            row[f"{target_prefix}candidate_ids" if target_prefix else "candidate_ids"] = [item["candidate_id"] for item in valid_results if item.get("candidate_id")]
            row[f"{target_prefix}library_ids" if target_prefix else "library_ids"] = [item["library_id"] for item in valid_results if item.get("library_id")]
            row[f"{target_prefix}candidate_paths" if target_prefix else "candidate_paths"] = [item["path"] for item in valid_results if item.get("path")]
            row[f"{target_prefix}merged_candidate_count" if target_prefix else "merged_candidate_count"] = sum(1 for item in valid_results if item.get("merged"))
            row["updated_at"] = _now()
        else:
            row[status_key] = "skipped"
            row[f"{target_prefix}skip_reason" if target_prefix else "skip_reason"] = outcome.get("skip_reason") or (reject_reasons[0] if reject_reasons else "no_evidence_bound_candidates")
            row[f"{target_prefix}reject_reasons" if target_prefix else "reject_reasons"] = reject_reasons or _as_list(outcome.get("reject_reasons"))
            row["updated_at"] = _now()
            reason = _clean(row.get(f"{target_prefix}skip_reason" if target_prefix else "skip_reason"), limit=240)
            skip_reason_counts[reason] = skip_reason_counts.get(reason, 0) + 1
            if len(empty_window_skip_samples) < 3 and _is_no_evidence_skip_reason(reason):
                sample = _empty_window_sample_for_row(row)
                empty_window_skip_samples.append(sample)
                if target_prefix:
                    row[f"{status_key}_empty_window_sample"] = sample
    _write_jsonl_atomic(ledger_path, rows)
    if not produced_library_ids and processed:
        empty_window_skip_samples = _recent_empty_window_samples_from_rows(
            rows,
            status_key=status_key,
            current_samples=empty_window_skip_samples,
        )
    target_status_counts_after: dict[str, int] = {}
    for row in rows:
        status_value = str(row.get(status_key) or "unknown")
        target_status_counts_after[status_value] = target_status_counts_after.get(status_value, 0) + 1
    target_queue_remaining_count = sum(
        target_status_counts_after.get(status, 0)
        for status in _QUEUE_STATUSES
    )
    result = {
        "ok": True,
        "contract": DISTILL_RUNNER_CONTRACT,
        "reconcile": reconcile,
        "status": "budget_exhausted" if max_sessions and processed >= int(max_sessions) else "window_complete",
        "target_shape": target_shape,
        "ledger_status_key": status_key,
        "processed_session_count": processed,
        "produced_candidate_count": produced,
        "merged_candidate_count": merged,
        "rejected_candidate_count": rejected,
        "failed_session_count": failures,
        "produced_library_ids": sorted(set(produced_library_ids)),
        "produced_project_history_ids": sorted(set(produced_project_history_ids)),
        "user_author_new_card_verbatims": user_author_new_card_verbatims,
        "user_author_new_card_verbatim_count": len(user_author_new_card_verbatims),
        "skip_reason_counts": skip_reason_counts,
        "empty_window_skip_samples": empty_window_skip_samples if not produced_library_ids and processed else [],
        "empty_window_skip_sample_count": len(empty_window_skip_samples) if not produced_library_ids and processed else 0,
        "target_status_counts_after": target_status_counts_after,
        "target_queue_remaining_count": target_queue_remaining_count,
        "terminal_target_queue_exhausted": target_queue_remaining_count == 0,
        "ledger_path": str(ledger_path),
        "candidate_root": str(candidate_root),
        "write_performed": True,
    }
    self_check = _run_post_window_self_check(result, self_check_inputs)
    result["post_window_self_check"] = self_check
    if not self_check.get("ok"):
        _mark_window_rows_self_check_failed(
            ledger_path,
            session_keys=[key for key in processed_keys if key],
            blockers=list(self_check.get("blockers", [])),
            status_key=status_key,
        )
        result["ok"] = False
        result["status"] = "self_check_failed"
        result["self_check_blockers"] = self_check.get("blockers", [])
    else:
        _mark_window_rows_self_check_passed(
            ledger_path,
            session_keys=[key for key in processed_keys if key],
            status_key=status_key,
        )
    return result


def build_nightly_schedule_plan(config: dict[str, Any] | None = None, *, now: datetime | None = None, manual: bool = False) -> dict[str, Any]:
    cfg = dict(config or {})
    current = now or datetime.now()
    start_text = str(cfg.get("start") or "01:00")
    end_text = str(cfg.get("end") or "05:00")

    def parse_hhmm(value: str) -> tuple[time | None, str]:
        try:
            hour_text, minute_text = value.split(":", 1)
            hour = int(hour_text)
            minute = int(minute_text)
        except (AttributeError, TypeError, ValueError):
            return None, "invalid_hhmm"
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None, "invalid_hhmm"
        return time(hour, minute), ""

    start, start_error = parse_hhmm(start_text)
    end, end_error = parse_hhmm(end_text)
    blockers: list[str] = []
    if start_error:
        blockers.append("window_start_invalid_hhmm")
    if end_error:
        blockers.append("window_end_invalid_hhmm")
    if start is not None and end is not None and start == end:
        blockers.append("window_start_equals_end")
    if blockers:
        return {
            "ok": False,
            "contract": DISTILL_SCHEDULER_CONTRACT,
            "mode": "manual_now" if manual else "nightly_idle_window",
            "window_start": start_text,
            "window_end": end_text,
            "evaluated_at": current.isoformat(),
            "current_time": current.time().isoformat(timespec="seconds"),
            "should_run": False,
            "manual_override": bool(manual),
            "blockers": blockers,
            "write_performed": False,
        }
    current_time = current.time()
    assert start is not None and end is not None
    if start <= end:
        in_window = start <= current_time < end
        is_overnight = False
    else:
        in_window = current_time >= start or current_time < end
        is_overnight = True
    should_run = bool(manual or in_window)
    return {
        "ok": True,
        "contract": DISTILL_SCHEDULER_CONTRACT,
        "mode": "manual_now" if manual else "nightly_idle_window",
        "window_start": start_text,
        "window_end": end_text,
        "window_semantics": "[start,end)",
        "is_overnight_window": is_overnight,
        "evaluated_at": current.isoformat(),
        "current_time": current_time.isoformat(timespec="seconds"),
        "should_run": should_run,
        "manual_override": bool(manual),
        "max_sessions_per_window": int(cfg.get("max_sessions_per_window") or 20),
        "max_minutes_per_window": int(cfg.get("max_minutes_per_window") or 120),
        "max_tokens_per_window": int(cfg.get("max_tokens_per_window") or 0),
        "idle_required": bool(cfg.get("idle_required", True)),
    }


def build_scheduler_registration_plan(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Describe the installable scheduler without mutating launchd/cron/runtime."""

    cfg = dict(config or {})
    repo_root = _clean(cfg.get("repo_root") or str(Path(__file__).resolve().parents[1]), limit=1000)
    command = [
        _clean(cfg.get("python") or "python3", limit=160),
        str(Path(repo_root) / "tools" / "distill_automation.py"),
        "--root",
        repo_root,
        "run-window",
    ]
    source_systems = [_clean(item, limit=120) for item in _as_list(cfg.get("source_systems")) if _clean(item, limit=120)]
    for source_system in source_systems:
        command.extend(["--source-system", source_system])
    distiller_callable = _clean(cfg.get("distiller_callable"), limit=500)
    self_check_json = _clean(cfg.get("self_check_json"), limit=1000)
    blockers: list[str] = []
    if distiller_callable:
        command.extend(["--distiller-callable", distiller_callable])
    else:
        blockers.append("distiller_callable_required_before_install")
    if self_check_json:
        command.extend(["--self-check-json", self_check_json])
    else:
        blockers.append("self_check_json_required_before_install")
    return {
        "ok": True,
        "contract": DISTILL_SCHEDULER_CONTRACT,
        "mode": "scheduler_registration_plan",
        "write_performed": False,
        "plan_only": True,
        "requires_installed_authorization": True,
        "ready_to_install": not blockers,
        "blockers_before_install": blockers,
        "scheduler_kind": _clean(cfg.get("scheduler_kind") or "nightly_idle_window", limit=120),
        "window_start": _clean(cfg.get("start") or "01:00", limit=20),
        "window_end": _clean(cfg.get("end") or "05:00", limit=20),
        "max_sessions_per_window": int(cfg.get("max_sessions_per_window") or 20),
        "max_minutes_per_window": int(cfg.get("max_minutes_per_window") or 120),
        "command": command,
        "non_claims": [
            "not_installed",
            "not_enabled",
            "not_restarted",
            "no_runtime_distillation_run",
        ],
    }


def run_window_self_check(
    window_result: dict[str, Any],
    *,
    catalog_library_ids: list[str] | tuple[str, ...] | set[str],
    borrow_results: dict[str, dict[str, Any]],
    instructions_char_count: int,
    contains_body_markers: bool,
    char_budget: int = 1500,
) -> dict[str, Any]:
    produced_ids = [str(item) for item in _as_list(window_result.get("produced_library_ids")) if str(item)]
    visible = set(str(item) for item in catalog_library_ids)
    produced_visible = [item for item in produced_ids if item in visible]
    missing_visible = [item for item in produced_ids if item not in visible]
    borrow_ok: list[str] = []
    borrow_failed: list[str] = []
    for library_id in produced_ids:
        result = borrow_results.get(library_id) or {}
        excerpt = result.get("raw_source_excerpt") or result.get("verbatim_excerpt") or result.get("raw_excerpt") or ""
        if result.get("ok") is True and excerpt:
            borrow_ok.append(library_id)
        else:
            borrow_failed.append(library_id)
    processed_count = int(window_result.get("processed_session_count") or 0)
    terminal_no_queue_window = (
        not bool(produced_ids)
        and processed_count == 0
        and str(window_result.get("status") or "") == "window_complete"
    )
    empty_window = not bool(produced_ids) and processed_count > 0
    empty_samples = [item for item in _as_list(window_result.get("empty_window_skip_samples")) if isinstance(item, dict)]
    skip_reason_counts = window_result.get("skip_reason_counts") if isinstance(window_result.get("skip_reason_counts"), dict) else {}
    non_no_evidence_skip_count = 0
    for reason, count in skip_reason_counts.items():
        if not _is_no_evidence_skip_reason(str(reason)):
            non_no_evidence_skip_count += int(count or 0)
    false_negative_found = any(bool(sample.get("false_negative_found")) for sample in empty_samples)
    consecutive_empty_window_count = int(window_result.get("consecutive_empty_window_count") or 1)
    terminal_small_empty_window = (
        str(window_result.get("target_shape") or "") == MIMOCODE_DEEP_DISTILL_TARGET_SHAPE
        and empty_window
        and str(window_result.get("status") or "") == "window_complete"
        and bool(window_result.get("terminal_target_queue_exhausted"))
        and 0 < len(empty_samples) == processed_count < 3
        and non_no_evidence_skip_count == 0
        and not false_negative_found
    )
    empty_window_receipt_ok = (
        empty_window
        and (len(empty_samples) >= 3 or terminal_small_empty_window)
        and non_no_evidence_skip_count == 0
        and not (false_negative_found and consecutive_empty_window_count >= 2)
    )
    grave_one_ok = (bool(produced_ids) and not missing_visible) or empty_window_receipt_ok or terminal_no_queue_window
    grave_two_ok = (
        (bool(produced_ids) and not borrow_failed) or empty_window_receipt_ok or terminal_no_queue_window
    ) and int(instructions_char_count or 0) <= int(char_budget) and not bool(contains_body_markers)
    blockers: list[str] = []
    if empty_window and not empty_window_receipt_ok:
        blockers.append("grave_one_empty_window_no_true_cards")
        if len(empty_samples) < 3:
            blockers.append("empty_window_false_negative_samples_missing")
        if non_no_evidence_skip_count:
            blockers.append("empty_window_non_no_evidence_skip_reasons")
        if false_negative_found and consecutive_empty_window_count >= 2:
            blockers.append("empty_window_false_negative_found_after_consecutive_empty_windows")
    if missing_visible:
        blockers.append("grave_one_candidates_not_visible_in_catalog")
    if borrow_failed:
        blockers.append("grave_two_new_cards_not_borrowable")
    if int(instructions_char_count or 0) > int(char_budget):
        blockers.append("grave_two_startup_instructions_over_budget")
    if contains_body_markers:
        blockers.append("grave_two_startup_instructions_contains_body")
    return {
        "ok": grave_one_ok and grave_two_ok,
        "contract": DISTILL_SELF_CHECK_CONTRACT,
        "grave_one_output_visible": grave_one_ok,
        "grave_two_delivery_borrowable": grave_two_ok,
        "empty_window": empty_window,
        "terminal_no_queue_window": terminal_no_queue_window,
        "terminal_small_empty_window": terminal_small_empty_window,
        "terminal_target_queue_exhausted": bool(window_result.get("terminal_target_queue_exhausted")),
        "target_queue_remaining_count": int(window_result.get("target_queue_remaining_count") or 0),
        "empty_window_receipt_visible": empty_window_receipt_ok,
        "empty_window_auto_continue_allowed": empty_window_receipt_ok,
        "empty_window_skip_samples": empty_samples[:3],
        "empty_window_skip_sample_count": len(empty_samples),
        "empty_window_skip_reason_counts": dict(skip_reason_counts),
        "empty_window_non_no_evidence_skip_count": non_no_evidence_skip_count,
        "consecutive_empty_window_count": consecutive_empty_window_count if empty_window else 0,
        "empty_window_false_negative_found": false_negative_found,
        "produced_library_ids": produced_ids,
        "visible_library_ids": sorted(visible),
        "produced_visible_library_ids": produced_visible,
        "missing_visible_library_ids": missing_visible,
        "borrow_ok_library_ids": borrow_ok,
        "borrow_failed_library_ids": borrow_failed,
        "instructions_char_count": int(instructions_char_count or 0),
        "char_budget": int(char_budget),
        "contains_body_markers": bool(contains_body_markers),
        "blockers": blockers,
    }


def run_project_history_window_self_check(
    window_result: dict[str, Any],
    *,
    project_history_record_ids: list[str] | tuple[str, ...] | set[str],
    project_page_history_ids: list[str] | tuple[str, ...] | set[str],
    borrow_results: dict[str, dict[str, Any]],
    instructions_char_count: int,
    contains_body_markers: bool,
    char_budget: int = 1500,
) -> dict[str, Any]:
    produced_ids = [
        str(item)
        for item in _as_list(window_result.get("produced_project_history_ids") or window_result.get("produced_library_ids"))
        if str(item)
    ]
    processed_count = int(window_result.get("processed_session_count") or 0)
    terminal_no_queue_window = (
        not bool(produced_ids)
        and processed_count == 0
        and str(window_result.get("status") or "") == "window_complete"
    )
    visible = set(str(item) for item in project_page_history_ids)
    produced_visible = [item for item in produced_ids if item in visible]
    missing_visible = [item for item in produced_ids if item not in visible]
    borrow_ok: list[str] = []
    borrow_failed: list[str] = []
    for record_id in produced_ids:
        result = borrow_results.get(record_id) or {}
        excerpt = result.get("raw_source_excerpt") or result.get("verbatim_excerpt") or result.get("raw_excerpt") or ""
        if result.get("ok") is True and excerpt:
            borrow_ok.append(record_id)
        else:
            borrow_failed.append(record_id)
    blockers: list[str] = []
    if processed_count > 0 and not produced_ids:
        blockers.append("project_history_empty_window_no_digest")
    if missing_visible:
        blockers.append("project_history_not_visible_in_project_page")
    if borrow_failed:
        blockers.append("project_history_records_not_borrowable")
    if int(instructions_char_count or 0) > int(char_budget):
        blockers.append("project_history_startup_instructions_over_budget")
    if contains_body_markers:
        blockers.append("project_history_startup_instructions_contains_body")
    return {
        "ok": not blockers,
        "contract": DISTILL_SELF_CHECK_CONTRACT,
        "target_shape": PROJECT_HISTORY_TARGET_SHAPE,
        "grave_one_output_visible": (not missing_visible and bool(produced_ids)) or terminal_no_queue_window,
        "grave_two_delivery_borrowable": (
            ((not borrow_failed and bool(produced_ids)) or terminal_no_queue_window)
            and int(instructions_char_count or 0) <= int(char_budget)
            and not bool(contains_body_markers)
        ),
        "terminal_no_queue_window": terminal_no_queue_window,
        "empty_window": processed_count > 0 and not bool(produced_ids),
        "project_history_record_ids": sorted(set(str(item) for item in project_history_record_ids)),
        "produced_project_history_ids": produced_ids,
        "project_page_history_ids": sorted(visible),
        "produced_visible_project_history_ids": produced_visible,
        "missing_visible_project_history_ids": missing_visible,
        "borrow_ok_project_history_ids": borrow_ok,
        "borrow_failed_project_history_ids": borrow_failed,
        "instructions_char_count": int(instructions_char_count or 0),
        "char_budget": int(char_budget),
        "contains_body_markers": bool(contains_body_markers),
        "blockers": blockers,
    }


__all__ = [
    "DEFAULT_DISTILL_VERSION",
    "DISTILL_AUTOMATION_CONTRACT",
    "DISTILL_COVERAGE_LEDGER_CONTRACT",
    "DISTILL_RUNNER_CONTRACT",
    "DISTILL_SCHEDULER_CONTRACT",
    "DISTILL_SELF_CHECK_CONTRACT",
    "MIMOCODE_DEEP_DISTILL_TARGET_SHAPE",
    "build_scheduler_registration_plan",
    "build_nightly_schedule_plan",
    "load_canonical_sessions",
    "load_distill_model_config",
    "reconcile_coverage_ledger",
    "run_distill_window",
    "run_project_history_window_self_check",
    "run_window_self_check",
    "session_key_for",
]
