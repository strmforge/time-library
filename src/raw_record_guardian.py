#!/usr/bin/env python3
"""Raw record guardian.

The guardian answers the record-first question:

Can Memcore prove that a local source conversation record exists, has been
mirrored into raw storage, contains both user and assistant turns, and is not
obviously corrupt?

It deliberately separates "platform entry detected" from "record guarded".
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from config_loader import get_memcore_root, memory_root, node_id, openclaw_agents
except ImportError:  # pragma: no cover
    from src.config_loader import get_memcore_root, memory_root, node_id, openclaw_agents
try:
    from raw_archive_layout import preferred_raw_archive_path
except ImportError:  # pragma: no cover
    from src.raw_archive_layout import preferred_raw_archive_path
try:
    from source_system_runtime_declarations import (
        declared_guarded_source_systems,
        declared_guardian_connectors,
        declared_source_systems_with_gap_probe,
        normalize_source_system_window_identity,
        source_system_gap_probe_kind,
        source_system_raw_validation_kind,
        source_system_source_scan_kind,
    )
except ImportError:  # pragma: no cover
    from src.source_system_runtime_declarations import (
        declared_guarded_source_systems,
        declared_guardian_connectors,
        declared_source_systems_with_gap_probe,
        normalize_source_system_window_identity,
        source_system_gap_probe_kind,
        source_system_raw_validation_kind,
        source_system_source_scan_kind,
    )
try:
    from raw_origin_event import attach_origin_events, origin_summary
except ImportError:  # pragma: no cover
    from src.raw_origin_event import attach_origin_events, origin_summary
try:
    from raw_record_canonical_index import (
        CANONICAL_RECORD_INDEX_CONTRACT,
        _canonical_index_record,
        _chunks_for_message,
        _connect_records_db,
        _ensure_index_schema,
        _is_sqlite_locked,
        _jsonl_record_canonical_messages,
        _jsonl_record_role_text,
        _raw_message_matches,
        _record_id,
        _repair_missing_raw_offsets_for_record,
        _repair_session_window_identity_drift,
        _stream_jsonl_canonical_entries,
        _update_records_index_once,
        _upsert_origin_event,
        get_raw_record_canonical_index_contract,
        query_records_index,
        records_db_busy_timeout_milliseconds,
        records_db_path,
        update_records_index,
    )
except ImportError:  # pragma: no cover
    from src.raw_record_canonical_index import (
        CANONICAL_RECORD_INDEX_CONTRACT,
        _canonical_index_record,
        _chunks_for_message,
        _connect_records_db,
        _ensure_index_schema,
        _is_sqlite_locked,
        _jsonl_record_canonical_messages,
        _jsonl_record_role_text,
        _raw_message_matches,
        _record_id,
        _repair_missing_raw_offsets_for_record,
        _repair_session_window_identity_drift,
        _stream_jsonl_canonical_entries,
        _update_records_index_once,
        _upsert_origin_event,
        get_raw_record_canonical_index_contract,
        query_records_index,
        records_db_busy_timeout_milliseconds,
        records_db_path,
        update_records_index,
    )

try:
    from raw_record_backfill import (
        RAW_BACKFILL_CONTRACT,
        _connector_backfill,
        _hermes_backfill,
        _hermes_message_select_columns,
        _hermes_raw_record_from_message,
        _hermes_read_session_messages,
        _hermes_session_metadata,
        _json_text_or_value,
        _openclaw_backfill,
        _write_jsonl_atomic,
        get_raw_record_backfill_contract,
        hermes_backfill_recommendation,
        run_raw_backfill,
    )
except ImportError:  # pragma: no cover
    from src.raw_record_backfill import (
        RAW_BACKFILL_CONTRACT,
        _connector_backfill,
        _hermes_backfill,
        _hermes_message_select_columns,
        _hermes_raw_record_from_message,
        _hermes_read_session_messages,
        _hermes_session_metadata,
        _json_text_or_value,
        _openclaw_backfill,
        _write_jsonl_atomic,
        get_raw_record_backfill_contract,
        hermes_backfill_recommendation,
        run_raw_backfill,
    )

UTC = timezone.utc
RAW_RECORD_GUARDIAN_CONTRACT = "raw_record_guardian.v1"
DEFAULT_JSONL_OVERSIZE_BYTES = 1024 * 1024
DEFAULT_BACKFILL_RECOMMEND_AFTER_MS = 5000
CLAUDE_DESKTOP_AUTHORIZED_RAW_FORMAT = "claude_desktop_authorized_local_store_jsonl"
CLAUDE_DESKTOP_PROJECTS_JSONL_RAW_FORMAT = "claude_projects_jsonl_desktop_entrypoint"
LEGACY_LOCAL_RELAY_TOKEN = "cc" + "switch"
LEGACY_LOCAL_RELAY_DASHED = "cc" + "-switch"
LEGACY_LOCAL_RELAY_DISPLAY = "CC" + " Switch"
LEGACY_LOCAL_RELAY_BUNDLE = "com." + LEGACY_LOCAL_RELAY_TOKEN
CLAUDE_DESKTOP_LEGACY_PROJECTS_JSONL_RAW_FORMAT = f"{LEGACY_LOCAL_RELAY_TOKEN}_claude_provider_projects_jsonl"
CLAUDE_DESKTOP_RAW_FORMATS = (
    CLAUDE_DESKTOP_AUTHORIZED_RAW_FORMAT,
    CLAUDE_DESKTOP_PROJECTS_JSONL_RAW_FORMAT,
    CLAUDE_DESKTOP_LEGACY_PROJECTS_JSONL_RAW_FORMAT,
)
OPENCLAW_NATIVE_RAW_FORMAT = "openclaw_session_jsonl"
HERMES_STATE_DB_RAW_FORMAT = "hermes_state_db_messages_jsonl"
GUARDED_CONNECTORS = declared_guardian_connectors()
IMPLEMENTED_SOURCE_GUARDIANS = set(declared_guarded_source_systems())
KNOWN_GAP_SOURCES = declared_source_systems_with_gap_probe()


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _public_path_label(path: str | Path) -> str:
    text = str(path or "")
    if not text:
        return ""
    try:
        p = Path(text).expanduser()
        home = Path.home().resolve()
        resolved = p.resolve(strict=False)
        try:
            rel = resolved.relative_to(home)
            return _sanitize_public_text("~/" + str(rel))
        except ValueError:
            return _sanitize_public_text(str(p))
    except Exception:
        return _sanitize_public_text(text)


def _sanitize_public_text(text: str) -> str:
    replacements = {
        CLAUDE_DESKTOP_LEGACY_PROJECTS_JSONL_RAW_FORMAT: "claude_projects_jsonl_desktop_entrypoint",
        "local_relay_gateway": "local_relay_gateway",
        "local_relay_proxy": "local_relay_proxy",
        "local_relay": "local_relay",
        "Local Relay": "Local Relay",
        "local-relay": "local-relay",
        "com.localrelay": "local.relay",
        LEGACY_LOCAL_RELAY_DISPLAY: "Local Relay",
        LEGACY_LOCAL_RELAY_DASHED: "local-relay",
        LEGACY_LOCAL_RELAY_TOKEN: "local_relay",
        LEGACY_LOCAL_RELAY_BUNDLE: "local.relay",
    }
    result = str(text)
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def _sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_public_text(value)
    if isinstance(value, list):
        return [_sanitize_public_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_public_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            _sanitize_public_text(str(key)): _sanitize_public_payload(item)
            for key, item in value.items()
        }
    return value


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_record_identity(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    source_system = _safe_str(normalized.get("source_system"))
    session_id = _safe_str(normalized.get("session_id"))
    canonical_window_id = _safe_str(normalized.get("canonical_window_id"))
    project_id = _safe_str(normalized.get("project_id"))

    normalized_identity = normalize_source_system_window_identity(
        source_system=source_system,
        session_id=session_id,
        canonical_window_id=canonical_window_id,
        project_id=project_id,
    )
    session_id = normalized_identity["session_id"]
    canonical_window_id = normalized_identity["canonical_window_id"]
    project_id = normalized_identity["project_id"]
    if normalized_identity["source_refs_canonical_window_id"]:
        normalized.setdefault("source_refs_canonical_window_id", normalized_identity["source_refs_canonical_window_id"])

    normalized["session_id"] = session_id
    normalized["canonical_window_id"] = canonical_window_id
    normalized["project_id"] = project_id
    normalized["project_root"] = _safe_str(normalized.get("project_root"))
    event = normalized.get("origin_event") if isinstance(normalized.get("origin_event"), dict) else None
    if event:
        event = dict(event)
        refs = event.get("source_refs") if isinstance(event.get("source_refs"), dict) else {}
        refs = dict(refs)
        if session_id:
            refs["session_id"] = session_id
        if canonical_window_id:
            refs["canonical_window_id"] = canonical_window_id
        if project_id:
            refs["project_id"] = project_id
        if normalized.get("source_refs_canonical_window_id"):
            refs.setdefault("source_refs_canonical_window_id", normalized["source_refs_canonical_window_id"])
        event["source_refs"] = refs
        normalized["origin_event"] = event
    return normalized


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("text", "content", "value", "markdown"):
                    value = item.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                        break
                    if isinstance(value, list):
                        nested = _text_from_content(value)
                        if nested:
                            parts.append(nested)
                            break
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        for key in ("text", "content", "value", "markdown"):
            value = content.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return _text_from_content(value)
    return ""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _role_and_content_from_record(source_system: str, record: dict[str, Any]) -> tuple[str, bool]:
    validation_kind = source_system_raw_validation_kind(source_system)
    if validation_kind == "response_item_payload_message":
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        role = _safe_str(payload.get("role") or record.get("role"))
        content = payload.get("content") if "content" in payload else record.get("content")
        nested = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        if not role and nested:
            role = _safe_str(nested.get("role"))
        if content is None and nested:
            content = nested.get("content")
        return role, bool(_text_from_content(content).strip())

    if validation_kind == "message_envelope_content_blocks":
        rec_type = _safe_str(record.get("type"))
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        role = _safe_str(message.get("role") or rec_type)
        content = message.get("content")
        if role == "user" and isinstance(content, list) and content and all(
            isinstance(item, dict) and _safe_str(item.get("type")) == "tool_result"
            for item in content
        ):
            role = "tool"
        return role, bool(_text_from_content(content).strip())

    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    role = _safe_str(record.get("role") or message.get("role") or payload.get("role"))
    content = record.get("content")
    if content is None:
        content = message.get("content")
    if content is None:
        content = payload.get("content")
    return role, bool(_text_from_content(content).strip())


def _role_content_pairs_from_record(source_system: str, record: dict[str, Any]) -> list[tuple[str, bool]]:
    if source_system_raw_validation_kind(source_system) == "message_snapshot_batch":
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        messages = data.get("messagesSnapshot")
        if not isinstance(messages, list):
            messages = record.get("messages")
        pairs: list[tuple[str, bool]] = []
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                role = _safe_str(message.get("role") or message.get("type"))
                if role == "custom":
                    continue
                content = message.get("content")
                text_present = bool(_text_from_content(content).strip())
                if role and text_present:
                    pairs.append((role, text_present))
            if pairs:
                return pairs
        final_prompt = data.get("finalPromptText")
        if isinstance(final_prompt, str) and final_prompt.strip():
            return [("user", True)]
    return [_role_and_content_from_record(source_system, record)]


def _expected_metadata(source_system: str, first_record: dict[str, Any] | None, session_seen: bool) -> dict[str, Any]:
    validation_kind = source_system_raw_validation_kind(source_system)
    if validation_kind == "response_item_payload_message":
        ok = bool(
            isinstance(first_record, dict)
            and first_record.get("type") == "session_meta"
            and isinstance(first_record.get("payload"), dict)
            and first_record["payload"].get("id")
        )
        return {
            "metadata_ok": ok,
            "metadata_rule": "first_nonempty_line_session_meta_with_payload_id",
            "missing_session_meta": not ok,
        }
    if validation_kind == "message_envelope_content_blocks":
        return {
            "metadata_ok": bool(session_seen),
            "metadata_rule": "sessionId_observed_in_jsonl_records",
            "missing_session_meta": False,
        }
    return {
        "metadata_ok": bool(first_record),
        "metadata_rule": "first_valid_json_record_present",
        "missing_session_meta": False,
    }


def scan_jsonl_record(
    path: str | Path,
    *,
    source_system: str,
    oversize_bytes: int = DEFAULT_JSONL_OVERSIZE_BYTES,
    max_bad_line_samples: int = 8,
) -> dict[str, Any]:
    raw_path = Path(path).expanduser()
    stat = None
    try:
        stat = raw_path.stat()
    except OSError:
        return {
            "ok": False,
            "path": str(raw_path),
            "path_label": _public_path_label(raw_path),
            "exists": False,
            "health_status": "missing_file",
            "metadata_ok": False,
            "has_user_and_assistant": False,
        }

    line_count = 0
    valid_json_line_count = 0
    bad_json_line_count = 0
    oversize_record_count = 0
    max_line_bytes = 0
    first_record: dict[str, Any] | None = None
    first_record_type = ""
    session_seen = False
    user_turn_count = 0
    assistant_turn_count = 0
    tool_turn_count = 0
    content_message_count = 0
    bad_line_samples: list[dict[str, Any]] = []
    oversize_samples: list[dict[str, Any]] = []

    try:
        with raw_path.open("rb") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                line_count += 1
                line_bytes = len(raw_line)
                max_line_bytes = max(max_line_bytes, line_bytes)
                if line_bytes > oversize_bytes:
                    oversize_record_count += 1
                    if len(oversize_samples) < max_bad_line_samples:
                        oversize_samples.append({
                            "line": line_number,
                            "bytes": line_bytes,
                        })
                try:
                    record = json.loads(raw_line.decode("utf-8"))
                except Exception as exc:
                    bad_json_line_count += 1
                    if len(bad_line_samples) < max_bad_line_samples:
                        bad_line_samples.append({
                            "line": line_number,
                            "error": f"{type(exc).__name__}: {str(exc)[:120]}",
                        })
                    continue
                if not isinstance(record, dict):
                    continue
                valid_json_line_count += 1
                if first_record is None:
                    first_record = record
                    first_record_type = _safe_str(record.get("type"))
                if record.get("sessionId") or (
                    isinstance(record.get("payload"), dict) and record["payload"].get("id")
                ):
                    session_seen = True
                for role, content_present in _role_content_pairs_from_record(source_system, record):
                    if role in {"user", "human"}:
                        user_turn_count += 1
                    elif role in {"assistant", "ai", "model"}:
                        assistant_turn_count += 1
                    elif role == "tool" or "tool" in _safe_str(record.get("type")).lower():
                        tool_turn_count += 1
                    if role and content_present:
                        content_message_count += 1
    except OSError as exc:
        return {
            "ok": False,
            "path": str(raw_path),
            "path_label": _public_path_label(raw_path),
            "exists": True,
            "health_status": "read_error",
            "error": str(exc),
            "metadata_ok": False,
            "has_user_and_assistant": False,
        }

    metadata = _expected_metadata(source_system, first_record, session_seen)
    has_user_and_assistant = bool(user_turn_count and assistant_turn_count)
    health_status = "ok"
    if bad_json_line_count:
        health_status = "corrupt_jsonl"
    elif oversize_record_count:
        health_status = "oversized_records"
    elif not metadata["metadata_ok"]:
        health_status = "metadata_incomplete"
    elif user_turn_count and not assistant_turn_count:
        health_status = "user_only"
    elif assistant_turn_count and not user_turn_count:
        health_status = "assistant_only"
    elif not has_user_and_assistant:
        health_status = "no_complete_conversation"

    return {
        "ok": health_status == "ok",
        "path": str(raw_path),
        "path_label": _public_path_label(raw_path),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_epoch": stat.st_mtime,
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "line_count": line_count,
        "valid_json_line_count": valid_json_line_count,
        "bad_json_line_count": bad_json_line_count,
        "bad_line_samples": bad_line_samples,
        "oversize_record_count": oversize_record_count,
        "oversize_threshold_bytes": oversize_bytes,
        "oversize_samples": oversize_samples,
        "max_line_bytes": max_line_bytes,
        "first_record_type": first_record_type,
        "metadata_ok": metadata["metadata_ok"],
        "metadata_rule": metadata["metadata_rule"],
        "missing_session_meta": metadata["missing_session_meta"],
        "user_turn_count": user_turn_count,
        "assistant_turn_count": assistant_turn_count,
        "tool_turn_count": tool_turn_count,
        "content_message_count": content_message_count,
        "message_count": user_turn_count + assistant_turn_count,
        "has_user_and_assistant": has_user_and_assistant,
        "health_status": health_status,
    }


def _item_guard_status(source_scan: dict[str, Any], raw_scan: dict[str, Any], sync_item: dict[str, Any]) -> str:
    if sync_item.get("raw_missing"):
        return "raw_missing"
    if sync_item.get("raw_lag_sla_breach"):
        return "raw_lagging"
    if sync_item.get("raw_stale"):
        return "raw_catching_up"
    if source_scan.get("bad_json_line_count"):
        return "source_corrupt"
    if raw_scan.get("bad_json_line_count"):
        return "raw_corrupt"
    if not source_scan.get("metadata_ok"):
        return "source_metadata_incomplete"
    if not source_scan.get("has_user_and_assistant"):
        return "source_partial_conversation"
    if not raw_scan.get("has_user_and_assistant"):
        return "raw_partial_conversation"
    return "record_guarded"


def _item_health_warnings(source_scan: dict[str, Any], raw_scan: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if source_scan.get("oversize_record_count"):
        warnings.append("source_oversized")
    if raw_scan.get("oversize_record_count"):
        warnings.append("raw_oversized")
    return warnings


def _fast_jsonl_stat(path: str | Path, *, source_system: str) -> dict[str, Any]:
    raw_path = Path(path).expanduser()
    try:
        stat = raw_path.stat()
    except OSError:
        return {
            "ok": False,
            "path": str(raw_path),
            "path_label": _public_path_label(raw_path),
            "exists": False,
            "health_status": "missing_file",
            "metadata_ok": None,
            "has_user_and_assistant": None,
            "fast_stat_only": True,
        }
    return {
        "ok": True,
        "path": str(raw_path),
        "path_label": _public_path_label(raw_path),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_epoch": stat.st_mtime,
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "health_status": "stat_only",
        "metadata_ok": None,
        "has_user_and_assistant": None,
        "bad_json_line_count": None,
        "oversize_record_count": None,
        "user_turn_count": None,
        "assistant_turn_count": None,
        "message_count": None,
        "fast_stat_only": True,
        "source_system": source_system,
    }


def scan_kiro_session_json(path: str | Path) -> dict[str, Any]:
    raw_path = Path(path).expanduser()
    try:
        stat = raw_path.stat()
    except OSError:
        return {
            "ok": False,
            "path": str(raw_path),
            "path_label": _public_path_label(raw_path),
            "exists": False,
            "health_status": "missing_file",
            "metadata_ok": False,
            "has_user_and_assistant": False,
            "source_system": "kiro",
            "native_artifact_format": "kiro_workspace_sessions_json",
        }
    bad_json = False
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8-sig"))
    except Exception:
        data = {}
        bad_json = True
    messages: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        msg = value.get("message") if isinstance(value.get("message"), dict) else value
        role = _safe_str(msg.get("role") or value.get("role")).lower() if isinstance(msg, dict) else ""
        if role == "human":
            role = "user"
        elif role in {"ai", "agent", "bot"}:
            role = "assistant"
        if role in {"user", "assistant"}:
            content = msg.get("content") if isinstance(msg, dict) and "content" in msg else (
                msg.get("text") if isinstance(msg, dict) else None
            )
            if content is None:
                content = value.get("content") or value.get("text")
            if _text_from_content(content).strip():
                messages.append({"role": role})
                return
        for key in ("history", "messages", "turns", "entries", "items", "children"):
            if key in value:
                visit(value.get(key))

    if isinstance(data, dict):
        visit(data)
    user_turn_count = len([item for item in messages if item.get("role") == "user"])
    assistant_turn_count = len([item for item in messages if item.get("role") == "assistant"])
    has_user_and_assistant = bool(user_turn_count and assistant_turn_count)
    health_status = "ok"
    if bad_json:
        health_status = "bad_json"
    elif not messages:
        health_status = "no_conversation_messages"
    elif not has_user_and_assistant:
        health_status = "partial_conversation"
    return {
        "ok": not bad_json and bool(messages),
        "path": str(raw_path),
        "path_label": _public_path_label(raw_path),
        "exists": True,
        "size_bytes": stat.st_size,
        "mtime_epoch": stat.st_mtime,
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "health_status": health_status,
        "metadata_ok": not bad_json and isinstance(data, dict),
        "metadata_rule": "kiro_session_json_parseable_object",
        "missing_session_meta": False,
        "bad_json_line_count": 1 if bad_json else 0,
        "oversize_record_count": 0,
        "user_turn_count": user_turn_count,
        "assistant_turn_count": assistant_turn_count,
        "tool_turn_count": 0,
        "content_message_count": len(messages),
        "message_count": user_turn_count + assistant_turn_count,
        "has_user_and_assistant": has_user_and_assistant,
        "source_system": "kiro",
        "native_artifact_format": "kiro_workspace_sessions_json",
    }


def _source_scan_for_artifact(
    source_path: str | Path,
    *,
    source_system: str,
    oversize_bytes: int,
    scan_mode: str,
) -> dict[str, Any]:
    if scan_mode == "fast":
        return _fast_jsonl_stat(source_path, source_system=source_system)
    if source_system_source_scan_kind(source_system) == "workspace_session_json_document":
        return scan_kiro_session_json(source_path)
    return scan_jsonl_record(source_path, source_system=source_system, oversize_bytes=oversize_bytes)


def _connector_records(
    source_system: str,
    module_name: str,
    *,
    limit: int,
    oversize_bytes: int,
    scan_mode: str = "full",
) -> list[dict[str, Any]]:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        return [{
            "source_system": source_system,
            "guard_status": "connector_unavailable",
            "error": f"{type(exc).__name__}: {exc}",
        }]
    if not hasattr(module, "discover_sessions"):
        return [{
            "source_system": source_system,
            "guard_status": "connector_missing_discover_sessions",
        }]
    try:
        artifacts = module.discover_sessions(limit=limit)
    except Exception as exc:
        return [{
            "source_system": source_system,
            "guard_status": "connector_scan_error",
            "error": f"{type(exc).__name__}: {exc}",
        }]

    records: list[dict[str, Any]] = []
    for artifact in artifacts:
        source_path = artifact.get("source_path", "")
        sync_item = {}
        if hasattr(module, "_raw_sync_item"):
            try:
                sync_item = module._raw_sync_item(artifact)
            except Exception:
                sync_item = {}
        raw_path = sync_item.get("raw_path") or ""
        if hasattr(module, "_raw_dest_for_artifact"):
            try:
                raw_path = str(module._raw_dest_for_artifact(artifact))
            except Exception:
                if not raw_path:
                    raw_path = ""
        if scan_mode == "fast":
            source_scan = _fast_jsonl_stat(source_path, source_system=source_system)
            raw_scan = _fast_jsonl_stat(raw_path, source_system=source_system) if raw_path else {
                "exists": False,
                "health_status": "missing_file",
                "metadata_ok": None,
                "has_user_and_assistant": None,
                "fast_stat_only": True,
            }
        else:
            source_scan = _source_scan_for_artifact(
                source_path,
                source_system=source_system,
                oversize_bytes=oversize_bytes,
                scan_mode=scan_mode,
            )
            raw_scan = scan_jsonl_record(raw_path, source_system=source_system, oversize_bytes=oversize_bytes) if raw_path else {
                "exists": False,
                "health_status": "missing_file",
                "metadata_ok": False,
                "has_user_and_assistant": False,
            }
        if "raw_missing" not in sync_item:
            sync_item["raw_missing"] = not raw_scan.get("exists")
        if sync_item.get("raw_stale_authoritative"):
            sync_item["raw_stale"] = bool(sync_item.get("raw_stale"))
        elif "raw_stale" not in sync_item:
            sync_item["raw_stale"] = bool(
                raw_scan.get("exists")
                and source_scan.get("size_bytes", 0) > raw_scan.get("size_bytes", 0)
            )
        else:
            # Connector snapshots are taken before the heavier guardian scan. On
            # active long-running JSONL files, the raw mirror may catch up during
            # the scan itself; trust the later source/raw scan for freshness.
            sync_item["raw_stale"] = bool(
                raw_scan.get("exists")
                and source_scan.get("size_bytes", 0) > raw_scan.get("size_bytes", 0)
            )
        lag_ms = int(sync_item.get("raw_archive_lag_milliseconds", 0) or 0)
        lag_bytes = int(sync_item.get("raw_archive_lag_bytes", 0) or 0)
        try:
            sla_ms = int(getattr(module, "raw_lag_sla_milliseconds")())
        except Exception:
            sla_ms = 1000
        recommend_after_ms = max(DEFAULT_BACKFILL_RECOMMEND_AFTER_MS, sla_ms * 5)
        sync_item["raw_lag_sla_milliseconds"] = sla_ms
        sync_item["backfill_recommend_after_milliseconds"] = recommend_after_ms
        sync_item["raw_lag_sla_breach"] = bool(
            sync_item.get("raw_stale")
            and (lag_ms > sla_ms or (sla_ms == 0 and lag_bytes > 0))
        )
        sync_item["backfill_recommendation_breach"] = bool(
            sync_item.get("raw_missing")
            or (
                sync_item.get("raw_stale")
                and (lag_ms > recommend_after_ms or (recommend_after_ms == 0 and lag_bytes > 0))
            )
        )
        if scan_mode == "fast":
            if sync_item.get("raw_missing"):
                guard_status = "raw_missing"
            elif sync_item.get("raw_lag_sla_breach"):
                guard_status = "raw_lagging"
            elif sync_item.get("raw_stale"):
                guard_status = "raw_catching_up"
            elif raw_scan.get("exists") and source_scan.get("exists"):
                guard_status = "record_stat_guarded"
            else:
                guard_status = "stat_incomplete"
        else:
            guard_status = _item_guard_status(source_scan, raw_scan, sync_item)
        health_warnings = _item_health_warnings(source_scan, raw_scan)
        record = {
            "source_system": source_system,
            "artifact_type": artifact.get("artifact_type") or artifact.get("native_artifact_format") or "",
            "session_id": artifact.get("session_id", ""),
            "raw_artifact_id": artifact.get("raw_artifact_id", artifact.get("session_id", "")),
            "canonical_window_id": artifact.get("canonical_window_id", ""),
            "project_id": artifact.get("project_id", ""),
            "project_root": artifact.get("project_root", ""),
            "thread_name": artifact.get("thread_name", ""),
            "source_path": source_path,
            "source_path_label": _public_path_label(source_path),
            "raw_path": raw_path,
            "raw_path_label": _public_path_label(raw_path),
            "co_source_systems": artifact.get("co_source_systems", []),
            "conversation_origin": artifact.get("conversation_origin", ""),
            "runtime_consumer": artifact.get("runtime_consumer", ""),
            "desktop_entrypoint_detected": bool(artifact.get("desktop_entrypoint_detected")),
            "desktop_entrypoint_policy": artifact.get("desktop_entrypoint_policy", ""),
            "desktop_metadata_is_conversation_body": bool(artifact.get("desktop_metadata_is_conversation_body")),
            "source_scan": source_scan,
            "raw_scan": raw_scan,
            "raw_current": guard_status in {"record_guarded", "record_stat_guarded"},
            "recoverable_from_raw": bool(raw_scan.get("exists") and raw_scan.get("has_user_and_assistant")),
            "guard_status": guard_status,
            "health_warnings": health_warnings,
            "scan_mode": scan_mode,
            "sync": {
                "raw_missing": bool(sync_item.get("raw_missing")),
                "raw_stale": bool(sync_item.get("raw_stale")),
                "raw_lag_sla_breach": bool(sync_item.get("raw_lag_sla_breach")),
                "raw_archive_lag_bytes": lag_bytes,
                "raw_archive_lag_milliseconds": lag_ms,
                "raw_lag_sla_milliseconds": sla_ms,
                "backfill_recommend_after_milliseconds": recommend_after_ms,
                "raw_source_mtime_gap_milliseconds": int(sync_item.get("raw_source_mtime_gap_milliseconds", 0) or 0),
            },
            "backfill_recommended": bool(sync_item.get("backfill_recommendation_breach")),
        }
        records.append(_normalize_record_identity(record))
    return records


def _jsonl_source_refs(path: str | Path, *, max_records: int = 80) -> dict[str, Any]:
    raw_path = Path(path).expanduser()
    source_paths: list[str] = []
    source_path_exists = False
    source_path_mtime = ""
    session_ids: list[str] = []
    canonical_window_ids: list[str] = []
    raw_session_paths: list[str] = []
    native_formats: list[str] = []
    record_count = 0
    try:
        with raw_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if record_count >= max_records:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if not isinstance(record, dict):
                    continue
                record_count += 1
                refs = record.get("source_refs") if isinstance(record.get("source_refs"), dict) else {}
                if not refs:
                    refs = record.get("_source_refs") if isinstance(record.get("_source_refs"), dict) else {}
                source_path = _safe_str(refs.get("source_path"))
                if source_path and source_path not in source_paths:
                    source_paths.append(source_path)
                session_id = _safe_str(refs.get("session_id"))
                if session_id and session_id not in session_ids:
                    session_ids.append(session_id)
                window_id = _safe_str(refs.get("canonical_window_id"))
                if window_id and window_id not in canonical_window_ids:
                    canonical_window_ids.append(window_id)
                raw_session_path = _safe_str(refs.get("raw_session_path"))
                if raw_session_path and raw_session_path not in raw_session_paths:
                    raw_session_paths.append(raw_session_path)
                native_format = _safe_str(refs.get("native_artifact_format"))
                if native_format and native_format not in native_formats:
                    native_formats.append(native_format)
    except OSError:
        pass

    meta_path = Path(str(raw_path) + ".meta.json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception:
            meta = {}
        if isinstance(meta, dict):
            source_path = _safe_str(meta.get("source_path") or (meta.get("source_refs") or {}).get("source_path"))
            if source_path and source_path not in source_paths:
                source_paths.append(source_path)
            session_id = _safe_str(meta.get("session_id") or (meta.get("source_refs") or {}).get("session_id"))
            if session_id and session_id not in session_ids:
                session_ids.append(session_id)
            window_id = _safe_str(meta.get("canonical_window_id") or (meta.get("source_refs") or {}).get("canonical_window_id"))
            if window_id and window_id not in canonical_window_ids:
                canonical_window_ids.append(window_id)
            native_format = _safe_str(meta.get("native_artifact_format") or (meta.get("source_refs") or {}).get("native_artifact_format"))
            if native_format and native_format not in native_formats:
                native_formats.append(native_format)
            raw_session_path = _safe_str(meta.get("archived_to") or (meta.get("source_refs") or {}).get("raw_session_path"))
            if raw_session_path and raw_session_path not in raw_session_paths:
                raw_session_paths.append(raw_session_path)

    first_source_path = source_paths[0] if source_paths else ""
    if first_source_path:
        try:
            stat = Path(first_source_path).expanduser().stat()
            source_path_exists = True
            source_path_mtime = datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except OSError:
            source_path_exists = False
    return {
        "source_paths": source_paths,
        "source_path": first_source_path,
        "source_path_label": _public_path_label(first_source_path),
        "source_path_exists": source_path_exists,
        "source_path_mtime": source_path_mtime,
        "session_ids": session_ids,
        "canonical_window_ids": canonical_window_ids,
        "raw_session_paths": raw_session_paths,
        "native_artifact_formats": native_formats,
        "record_refs_scanned": record_count,
    }


def _claude_desktop_authorized_raw_paths(limit: int) -> list[Path]:
    root = Path(memory_root()).expanduser()
    if not root.exists():
        return []
    paths: list[Path] = []
    try:
        for native_format in CLAUDE_DESKTOP_RAW_FORMATS:
            pattern = f"*/claude_desktop/{native_format}/*/*.jsonl"
            paths.extend(path for path in root.glob(pattern) if path.is_file())
    except OSError:
        return []
    unique = list({str(path): path for path in paths}.values())
    unique.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    return unique[: max(1, int(limit or 20))]


def _claude_desktop_source_scan_from_raw(raw_path: Path, raw_scan: dict[str, Any], refs: dict[str, Any]) -> dict[str, Any]:
    source_exists = bool(refs.get("source_path_exists"))
    metadata_ok = bool(refs.get("source_paths") and refs.get("native_artifact_formats"))
    health_status = "authorized_parser_source_evidence"
    if not refs.get("source_paths"):
        health_status = "source_refs_missing"
    elif not source_exists:
        health_status = "source_path_missing_after_authorized_ingest"
    elif not metadata_ok:
        health_status = "source_refs_incomplete"
    return {
        "ok": source_exists and metadata_ok,
        "path": refs.get("source_path", ""),
        "path_label": refs.get("source_path_label", ""),
        "exists": source_exists,
        "mtime": refs.get("source_path_mtime", ""),
        "health_status": health_status,
        "metadata_ok": metadata_ok,
        "metadata_rule": "authorized_raw_source_refs_include_source_path_and_native_artifact_format",
        "missing_session_meta": False,
        "source_evidence_kind": "source_refs_in_authorized_claude_desktop_raw",
        "source_path_count": len(refs.get("source_paths") or []),
        "raw_refs_scanned": refs.get("record_refs_scanned", 0),
        "user_turn_count": raw_scan.get("user_turn_count"),
        "assistant_turn_count": raw_scan.get("assistant_turn_count"),
        "message_count": raw_scan.get("message_count"),
        "has_user_and_assistant": raw_scan.get("has_user_and_assistant"),
    }


def _claude_desktop_authorized_guard_status(source_scan: dict[str, Any], raw_scan: dict[str, Any]) -> str:
    if not raw_scan.get("exists"):
        return "raw_missing"
    if raw_scan.get("bad_json_line_count"):
        return "raw_corrupt"
    if not raw_scan.get("metadata_ok"):
        return "raw_metadata_incomplete"
    if not raw_scan.get("has_user_and_assistant"):
        return "raw_partial_conversation"
    if not source_scan.get("metadata_ok"):
        return "source_metadata_incomplete"
    if not source_scan.get("exists"):
        return "authorized_raw_recoverable_source_missing"
    return "record_guarded"


def _claude_desktop_authorized_raw_records(
    *,
    limit: int,
    oversize_bytes: int,
    scan_mode: str = "full",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_path in _claude_desktop_authorized_raw_paths(limit):
        refs = _jsonl_source_refs(raw_path)
        if scan_mode == "fast":
            raw_scan = _fast_jsonl_stat(raw_path, source_system="claude_desktop")
            source_scan = {
                "ok": bool(refs.get("source_path_exists")),
                "path": refs.get("source_path", ""),
                "path_label": refs.get("source_path_label", ""),
                "exists": bool(refs.get("source_path_exists")),
                "mtime": refs.get("source_path_mtime", ""),
                "health_status": "authorized_parser_source_ref_stat",
                "metadata_ok": bool(refs.get("source_paths")),
                "has_user_and_assistant": None,
                "fast_stat_only": True,
                "source_evidence_kind": "source_refs_in_authorized_claude_desktop_raw",
            }
            guard_status = "record_stat_guarded" if raw_scan.get("exists") and source_scan.get("exists") else "authorized_raw_source_unverified"
            recoverable = False
        else:
            raw_scan = scan_jsonl_record(raw_path, source_system="claude_desktop", oversize_bytes=oversize_bytes)
            source_scan = _claude_desktop_source_scan_from_raw(raw_path, raw_scan, refs)
            guard_status = _claude_desktop_authorized_guard_status(source_scan, raw_scan)
            recoverable = bool(raw_scan.get("exists") and raw_scan.get("has_user_and_assistant"))
        session_id = (refs.get("session_ids") or [raw_path.stem])[0]
        window_id = (refs.get("canonical_window_ids") or [session_id])[0]
        records.append({
            "source_system": "claude_desktop",
            "artifact_type": (refs.get("native_artifact_formats") or [CLAUDE_DESKTOP_AUTHORIZED_RAW_FORMAT])[0],
            "session_id": session_id,
            "raw_artifact_id": session_id,
            "canonical_window_id": window_id,
            "project_id": "",
            "project_root": "",
            "thread_name": raw_path.stem,
            "source_path": refs.get("source_path", ""),
            "source_path_label": refs.get("source_path_label", ""),
            "raw_path": str(raw_path),
            "raw_path_label": _public_path_label(raw_path),
            "source_scan": source_scan,
            "raw_scan": raw_scan,
            "raw_current": guard_status in {"record_guarded", "record_stat_guarded"},
            "recoverable_from_raw": recoverable,
            "guard_status": guard_status,
            "health_warnings": _item_health_warnings(source_scan, raw_scan),
            "scan_mode": scan_mode,
            "sync": {
                "raw_missing": False,
                "raw_stale": False,
                "raw_lag_sla_breach": False,
                "raw_archive_lag_bytes": 0,
                "raw_archive_lag_milliseconds": 0,
                "raw_lag_sla_milliseconds": 0,
                "backfill_recommend_after_milliseconds": DEFAULT_BACKFILL_RECOMMEND_AFTER_MS,
                "raw_source_mtime_gap_milliseconds": 0,
                "raw_current_scope": "authorized_ingest_snapshot",
            },
            "backfill_recommended": False,
        })
    return records


def _safe_segment(value: str, fallback: str = "unknown") -> str:
    import re
    text = str(value or "").strip() or fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-_")
    return text[:96] or fallback


def _openclaw_source_artifacts(limit: int) -> list[dict[str, Any]]:
    root = Path(openclaw_agents()).expanduser()
    artifacts: list[dict[str, Any]] = []
    if not root.exists():
        return artifacts
    try:
        agent_dirs = [path for path in root.iterdir() if path.is_dir()]
    except OSError:
        return artifacts
    for agent_dir in sorted(agent_dirs, key=lambda path: path.name):
        sessions_dir = agent_dir / "sessions"
        if not sessions_dir.is_dir():
            continue
        try:
            session_files = [path for path in sessions_dir.glob("*.jsonl") if path.is_file()]
        except OSError:
            continue
        session_files.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
        for path in session_files:
            artifacts.append({
                "source_system": "openclaw",
                "artifact_type": OPENCLAW_NATIVE_RAW_FORMAT,
                "session_id": path.name[:-6] if path.name.endswith(".jsonl") else path.stem,
                "canonical_window_id": agent_dir.name,
                "agent_id": agent_dir.name,
                "source_path": str(path),
            })
            if len(artifacts) >= max(1, int(limit or 20)):
                return artifacts
    return artifacts


def _openclaw_raw_path_for_artifact(artifact: dict[str, Any]) -> Path:
    return preferred_raw_archive_path(
        memory_root(),
        computer_name=node_id(),
        source_system="openclaw",
        native_format=OPENCLAW_NATIVE_RAW_FORMAT,
        native_scope=_safe_segment(artifact.get("canonical_window_id", ""), "main"),
        session_id=_safe_segment(artifact.get("session_id", ""), "session"),
    )


def _openclaw_legacy_raw_path_for_artifact(artifact: dict[str, Any]) -> Path:
    return (
        Path(memory_root()).expanduser()
        / "openclaw"
        / node_id()
        / _safe_segment(artifact.get("canonical_window_id", ""), "main")
        / f"{_safe_segment(artifact.get('session_id', ''), 'session')}.jsonl"
    )


def _openclaw_records(*, limit: int, oversize_bytes: int, scan_mode: str = "full") -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for artifact in _openclaw_source_artifacts(limit):
        source_path = artifact.get("source_path", "")
        raw_path = _openclaw_raw_path_for_artifact(artifact)
        legacy_raw_path = _openclaw_legacy_raw_path_for_artifact(artifact)
        raw_layout = "computer_first"
        if not raw_path.exists() and legacy_raw_path.exists():
            raw_path = legacy_raw_path
            raw_layout = "legacy_source_first"
        if scan_mode == "fast":
            source_scan = _fast_jsonl_stat(source_path, source_system="openclaw")
            raw_scan = _fast_jsonl_stat(raw_path, source_system="openclaw")
            if not raw_scan.get("exists"):
                guard_status = "raw_missing"
            elif raw_scan.get("exists") and source_scan.get("exists"):
                guard_status = "record_stat_guarded"
            else:
                guard_status = "stat_incomplete"
            recoverable = False
        else:
            source_scan = scan_jsonl_record(source_path, source_system="openclaw", oversize_bytes=oversize_bytes)
            raw_scan = scan_jsonl_record(raw_path, source_system="openclaw", oversize_bytes=oversize_bytes)
            sync_item = {
                "raw_missing": not raw_scan.get("exists"),
                "raw_stale": bool(
                    raw_scan.get("exists")
                    and source_scan.get("size_bytes", 0) > raw_scan.get("size_bytes", 0)
                ),
            }
            guard_status = _item_guard_status(source_scan, raw_scan, sync_item)
            recoverable = bool(raw_scan.get("exists") and raw_scan.get("has_user_and_assistant"))
        lag_bytes = max(0, int(source_scan.get("size_bytes", 0) or 0) - int(raw_scan.get("size_bytes", 0) or 0))
        raw_missing = not raw_scan.get("exists")
        raw_stale = bool(raw_scan.get("exists") and lag_bytes > 0)
        records.append({
            "source_system": "openclaw",
            "artifact_type": OPENCLAW_NATIVE_RAW_FORMAT,
            "session_id": artifact.get("session_id", ""),
            "raw_artifact_id": artifact.get("session_id", ""),
            "canonical_window_id": artifact.get("canonical_window_id", ""),
            "project_id": artifact.get("canonical_window_id", ""),
            "project_root": "",
            "thread_name": artifact.get("session_id", ""),
            "source_path": source_path,
            "source_path_label": _public_path_label(source_path),
            "raw_path": str(raw_path),
            "raw_path_label": _public_path_label(raw_path),
            "raw_archive_layout": raw_layout,
            "source_scan": source_scan,
            "raw_scan": raw_scan,
            "raw_current": guard_status in {"record_guarded", "record_stat_guarded"},
            "recoverable_from_raw": recoverable,
            "guard_status": guard_status,
            "health_warnings": _item_health_warnings(source_scan, raw_scan),
            "scan_mode": scan_mode,
            "sync": {
                "raw_missing": raw_missing,
                "raw_stale": raw_stale,
                "raw_lag_sla_breach": False,
                "raw_archive_lag_bytes": lag_bytes,
                "raw_archive_lag_milliseconds": 0,
                "raw_lag_sla_milliseconds": 1000,
                "backfill_recommend_after_milliseconds": DEFAULT_BACKFILL_RECOMMEND_AFTER_MS,
                "raw_source_mtime_gap_milliseconds": 0,
            },
            "backfill_recommended": raw_missing,
        })
    return records


def _hermes_state_db_summary() -> dict[str, Any]:
    try:
        from hermes_paths import hermes_state_db_path
    except Exception as exc:
        return {"exists": False, "error": f"{type(exc).__name__}: {exc}"}
    db_path = Path(hermes_state_db_path()).expanduser()
    if not db_path.exists():
        return {
            "exists": False,
            "path": str(db_path),
            "path_label": _public_path_label(db_path),
            "health_status": "missing_state_db",
        }
    try:
        stat = db_path.stat()
    except OSError as exc:
        return {
            "exists": True,
            "path": str(db_path),
            "path_label": _public_path_label(db_path),
            "health_status": "stat_error",
            "error": str(exc),
        }
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            tables = {
                row[0]
                for row in conn.execute("select name from sqlite_master where type='table'")
            }
            if not {"sessions", "messages"}.issubset(tables):
                return {
                    "exists": True,
                    "path": str(db_path),
                    "path_label": _public_path_label(db_path),
                    "size_bytes": stat.st_size,
                    "mtime_epoch": stat.st_mtime,
                    "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "health_status": "schema_incomplete",
                    "metadata_ok": False,
                    "has_user_and_assistant": False,
                    "tables": sorted(tables),
                }
            session_columns = {
                row[1]
                for row in conn.execute("pragma table_info(sessions)")
            }
            message_columns = {
                row[1]
                for row in conn.execute("pragma table_info(messages)")
            }
            message_count = int(conn.execute("select count(*) from messages").fetchone()[0] or 0)
            user_turn_count = int(conn.execute(
                "select count(*) from messages where lower(role) in ('user','human')"
            ).fetchone()[0] or 0)
            assistant_turn_count = int(conn.execute(
                "select count(*) from messages where lower(role) in ('assistant','ai','model')"
            ).fetchone()[0] or 0)
            session_count = int(conn.execute("select count(*) from sessions").fetchone()[0] or 0)
            latest_order_column = "id" if "id" in message_columns else "timestamp"
            latest = conn.execute(
                f"select session_id from messages order by {latest_order_column} desc limit 1"
            ).fetchone()
            latest_session_id = str(latest[0] or "") if latest else ""
            session_summaries = _hermes_state_db_session_summaries(
                conn,
                db_path=db_path,
                stat=stat,
                session_columns=session_columns,
                message_columns=message_columns,
            )
        finally:
            conn.close()
    except Exception as exc:
        return {
            "exists": True,
            "path": str(db_path),
            "path_label": _public_path_label(db_path),
            "size_bytes": stat.st_size,
            "mtime_epoch": stat.st_mtime,
            "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "health_status": "sqlite_read_error",
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            "metadata_ok": False,
            "has_user_and_assistant": False,
        }
    has_user_and_assistant = bool(user_turn_count and assistant_turn_count)
    health_status = "ok" if has_user_and_assistant else "no_complete_conversation"
    return {
        "ok": health_status == "ok",
        "exists": True,
        "path": str(db_path),
        "path_label": _public_path_label(db_path),
        "size_bytes": stat.st_size,
        "mtime_epoch": stat.st_mtime,
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "health_status": health_status,
        "metadata_ok": True,
        "metadata_rule": "hermes_state_db_has_sessions_and_messages_tables",
        "missing_session_meta": False,
        "session_id": latest_session_id,
        "session_count": session_count,
        "message_count": message_count,
        "source_message_count": message_count,
        "user_turn_count": user_turn_count,
        "assistant_turn_count": assistant_turn_count,
        "has_user_and_assistant": has_user_and_assistant,
        "source_evidence_kind": "sqlite_state_db_read_only_counts",
        "session_summaries": session_summaries,
    }


def _iso_from_epochish(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        stamp = float(value)
    except Exception:
        return str(value)
    if stamp > 10_000_000_000:
        stamp = stamp / 1000.0
    try:
        return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(value)


def _hermes_state_db_session_summaries(
    conn: sqlite3.Connection,
    *,
    db_path: Path,
    stat: os.stat_result,
    session_columns: set[str],
    message_columns: set[str],
    limit: int = 200,
) -> list[dict[str, Any]]:
    if "session_id" not in message_columns:
        return []
    latest_expr = "max(id)" if "id" in message_columns else "max(timestamp)"
    try:
        latest_rows = conn.execute(
            f"""
            select session_id, count(*) as message_count, {latest_expr} as latest_order
            from messages
            group by session_id
            order by latest_order desc
            limit ?
            """,
            (max(1, int(limit or 200)),),
        ).fetchall()
    except Exception:
        latest_rows = []
    summaries: list[dict[str, Any]] = []
    for session_id_value, total_messages, _latest_order in latest_rows:
        session_id = str(session_id_value or "").strip()
        if not session_id:
            continue
        user_turn_count = int(conn.execute(
            "select count(*) from messages where session_id=? and lower(role) in ('user','human')",
            (session_id,),
        ).fetchone()[0] or 0)
        assistant_turn_count = int(conn.execute(
            "select count(*) from messages where session_id=? and lower(role) in ('assistant','ai','model')",
            (session_id,),
        ).fetchone()[0] or 0)
        content_message_count = int(conn.execute(
            "select count(*) from messages where session_id=? and content is not null and trim(content) != ''",
            (session_id,),
        ).fetchone()[0] or 0)
        latest_message = conn.execute(
            "select timestamp from messages where session_id=? order by id desc limit 1",
            (session_id,),
        ).fetchone() if "id" in message_columns and "timestamp" in message_columns else None
        session_row: dict[str, Any] = {}
        wanted = [
            column for column in (
                "id",
                "source",
                "model",
                "title",
                "cwd",
                "started_at",
                "ended_at",
                "parent_session_id",
            )
            if column in session_columns
        ]
        if wanted:
            row = conn.execute(
                f"select {', '.join(wanted)} from sessions where id=?",
                (session_id,),
            ).fetchone()
            if row:
                session_row = dict(zip(wanted, row))
        has_user_and_assistant = bool(user_turn_count and assistant_turn_count)
        health_status = "ok" if has_user_and_assistant else "no_complete_conversation"
        message_pair_count = user_turn_count + assistant_turn_count
        summaries.append({
            "ok": health_status == "ok",
            "exists": True,
            "path": str(db_path),
            "path_label": _public_path_label(db_path),
            "size_bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mtime_epoch": stat.st_mtime,
            "health_status": health_status,
            "metadata_ok": True,
            "metadata_rule": "hermes_state_db_session_row_plus_messages",
            "missing_session_meta": False,
            "session_id": session_id,
            "session_source": _safe_str(session_row.get("source")),
            "model": _safe_str(session_row.get("model")),
            "thread_name": _safe_str(session_row.get("title") or session_id),
            "project_root": _safe_str(session_row.get("cwd")),
            "started_at": _iso_from_epochish(session_row.get("started_at")),
            "ended_at": _iso_from_epochish(session_row.get("ended_at")),
            "latest_message_at": _iso_from_epochish(latest_message[0] if latest_message else ""),
            "message_count": message_pair_count,
            "source_message_count": int(total_messages or 0),
            "content_message_count": content_message_count,
            "user_turn_count": user_turn_count,
            "assistant_turn_count": assistant_turn_count,
            "has_user_and_assistant": has_user_and_assistant,
            "source_evidence_kind": "sqlite_state_db_read_only_session_counts",
        })
    return summaries


def _hermes_raw_paths_for_session(session_id: str) -> list[Path]:
    safe_session = _safe_segment(session_id, "state-db")
    root = Path(memory_root()).expanduser()
    return [
        preferred_raw_archive_path(
            root,
            computer_name=node_id(),
            source_system="hermes",
            native_format=HERMES_STATE_DB_RAW_FORMAT,
            native_scope=safe_session,
            session_id=safe_session,
        ),
        root / "hermes" / node_id() / safe_session / f"{safe_session}.jsonl",
    ]


def _hermes_record_item(
    source_scan: dict[str, Any],
    *,
    oversize_bytes: int,
    scan_mode: str,
) -> dict[str, Any]:
    session_id = _safe_str(source_scan.get("session_id") or "state-db")
    raw_candidates = _hermes_raw_paths_for_session(session_id)
    raw_path = next((path for path in raw_candidates if path.exists()), raw_candidates[0])
    if scan_mode == "fast":
        raw_scan = _fast_jsonl_stat(raw_path, source_system="hermes")
        source_scan = {
            **source_scan,
            "fast_stat_only": True,
        }
        if not raw_scan.get("exists"):
            guard_status = "raw_missing"
        elif raw_scan.get("exists") and source_scan.get("exists"):
            guard_status = "record_stat_guarded"
        else:
            guard_status = "stat_incomplete"
        recoverable = False
    else:
        raw_scan = scan_jsonl_record(raw_path, source_system="hermes", oversize_bytes=oversize_bytes)
        raw_stale = bool(
            raw_scan.get("exists")
            and float(raw_scan.get("mtime_epoch", 0) or 0) < float(source_scan.get("mtime_epoch", 0) or 0)
            and int(source_scan.get("source_message_count", source_scan.get("message_count", 0)) or 0)
            > int(raw_scan.get("valid_json_line_count", 0) or 0)
        )
        sync_item = {
            "raw_missing": not raw_scan.get("exists"),
            "raw_stale": raw_stale,
        }
        guard_status = _item_guard_status(source_scan, raw_scan, sync_item)
        recoverable = bool(raw_scan.get("exists") and raw_scan.get("has_user_and_assistant"))
    raw_missing = not raw_scan.get("exists")
    source_message_count = int(source_scan.get("source_message_count", source_scan.get("message_count", 0)) or 0)
    raw_message_count = int(raw_scan.get("valid_json_line_count", raw_scan.get("message_count", 0)) or 0)
    lag_messages = max(0, source_message_count - raw_message_count) if raw_scan.get("exists") else source_message_count
    return {
        "source_system": "hermes",
        "artifact_type": "hermes_state_db",
        "session_id": session_id,
        "raw_artifact_id": session_id,
        "canonical_window_id": session_id,
        "project_id": _safe_segment(source_scan.get("project_root", ""), "") if source_scan.get("project_root") else "",
        "project_root": source_scan.get("project_root", ""),
        "thread_name": source_scan.get("thread_name", session_id),
        "source_path": source_scan.get("path", ""),
        "source_path_label": source_scan.get("path_label", ""),
        "raw_path": str(raw_path),
        "raw_path_label": _public_path_label(raw_path),
        "raw_archive_layout": "computer_first",
        "source_scan": source_scan,
        "raw_scan": raw_scan,
        "raw_current": guard_status in {"record_guarded", "record_stat_guarded"},
        "recoverable_from_raw": recoverable,
        "guard_status": guard_status,
        "health_warnings": _item_health_warnings(source_scan, raw_scan),
        "scan_mode": scan_mode,
        "sync": {
            "raw_missing": raw_missing,
            "raw_stale": guard_status == "raw_catching_up",
            "raw_lag_sla_breach": False,
            "raw_archive_lag_bytes": int(source_scan.get("size_bytes", 0) or 0) if raw_missing else 0,
            "raw_archive_lag_messages": lag_messages,
            "raw_archive_lag_milliseconds": 0,
            "raw_lag_sla_milliseconds": 1000,
            "backfill_recommend_after_milliseconds": DEFAULT_BACKFILL_RECOMMEND_AFTER_MS,
            "raw_source_mtime_gap_milliseconds": 0,
            "source_storage": "sqlite_state_db",
        },
        "backfill_recommended": raw_missing or guard_status == "raw_catching_up",
    }


def _hermes_records(*, limit: int, oversize_bytes: int, scan_mode: str = "full") -> list[dict[str, Any]]:
    db_summary = _hermes_state_db_summary()
    if not db_summary.get("exists"):
        return []
    session_summaries = [
        item for item in db_summary.get("session_summaries", [])
        if isinstance(item, dict)
    ]
    if not session_summaries:
        session_summaries = [db_summary]
    records: list[dict[str, Any]] = []
    for source_scan in session_summaries[: max(1, int(limit or 20))]:
        records.append(_hermes_record_item(
            source_scan,
            oversize_bytes=oversize_bytes,
            scan_mode=scan_mode,
        ))
    return records



# Raw backfill repair actions live in raw_record_backfill.py under
# tiandao_raw_record_backfill_repair.v1. Names are re-exported here for
# compatibility with existing callers and tests.

def _source_gap_status(source_system: str) -> dict[str, Any]:
    gap_probe_kind = source_system_gap_probe_kind(source_system)
    if gap_probe_kind == "desktop_local_store_status":
        try:
            mod = importlib.import_module("claude_desktop_connector")
            status = mod.status()
        except Exception as exc:
            status = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {
            "source_system": source_system,
            "guard_status": "entry_detected_body_unverified",
            "reason": "ordinary_desktop_chat_body_not_verified",
            "raw_body_readiness": status.get("raw_body_readiness", ""),
            "current_window_memory_registerable": bool(status.get("current_window_memory_registerable")),
            "assistant_reply_persistence": (
                (status.get("local_storage") or {}).get("assistant_reply_persistence")
                if isinstance(status.get("local_storage"), dict)
                else ""
            ),
            "relay_gateway_request_log_detected": bool(
                status.get("relay_gateway_request_log_detected")
                or status.get("local_relay_gateway_request_log_detected")
            ),
            "relay_gateway_request_count": int(
                status.get("relay_gateway_request_count")
                or status.get("local_relay_gateway_request_count")
                or 0
            ),
            "relay_gateway_latest_status_code": (
                status.get("relay_gateway_latest_status_code")
                if status.get("relay_gateway_latest_status_code") is not None
                else status.get("local_relay_gateway_latest_status_code")
            ),
            "relay_gateway_visibility_boundary": (
                status.get("relay_gateway_visibility_boundary")
                or status.get("local_relay_gateway_visibility_boundary", "")
            ),
        }
    if gap_probe_kind == "workspace_session_connector_status":
        try:
            mod = importlib.import_module("kiro_local_connector")
            status = mod.status()
        except Exception as exc:
            status = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if status.get("reachable") and status.get("artifact_count_sample"):
            return {
                "source_system": source_system,
                "guard_status": "connector_present_run_guardian_needed",
                "reason": "kiro_connector_exists_but_not_in_guarded_connector_set_yet",
                "artifact_count_sample": status.get("artifact_count_sample", 0),
            }
        return {
            "source_system": source_system,
            "guard_status": "no_live_source_sample",
            "reason": "connector_present_but_no_local_kiro_sample_detected",
            "artifact_count_sample": status.get("artifact_count_sample", 0),
        }
    if gap_probe_kind == "session_source_sample":
        artifacts = _openclaw_source_artifacts(limit=1)
        if not artifacts:
            return {
                "source_system": source_system,
                "guard_status": "no_live_source_sample",
                "reason": "openclaw_guardian_implemented_but_no_local_session_sample_detected",
                "artifact_count_sample": 0,
            }
        return {
            "source_system": source_system,
            "guard_status": "guardian_gap",
            "reason": "openclaw_source_sample_detected_but_no_guarded_record_observed",
            "artifact_count_sample": len(artifacts),
        }
    if gap_probe_kind == "state_db_presence":
        summary = _hermes_state_db_summary()
        if not summary.get("exists"):
            return {
                "source_system": source_system,
                "guard_status": "no_live_source_sample",
                "reason": "hermes_guardian_implemented_but_state_db_missing",
                "source_path": summary.get("path", ""),
                "artifact_count_sample": 0,
            }
        return {
            "source_system": source_system,
            "guard_status": "guardian_gap",
            "reason": "hermes_state_db_detected_but_no_guarded_record_observed",
            "source_path": summary.get("path", ""),
            "health_status": summary.get("health_status", ""),
            "artifact_count_sample": int(summary.get("session_count", 0) or 1),
        }
    return {
        "source_system": source_system,
        "guard_status": "guardian_gap",
        "reason": "no_source_raw_pair_guardian_implemented_yet",
    }


def _coverage_source_systems(item: dict[str, Any]) -> set[str]:
    sources = {_safe_str(item.get("source_system"))}
    for value in item.get("co_source_systems") or []:
        text = _safe_str(value)
        if text:
            sources.add(text)
    if item.get("desktop_entrypoint_detected") or _safe_str(item.get("conversation_origin")) == "claude_desktop_entrypoint_claude_code_session":
        sources.add("claude_desktop")
    sources.discard("")
    return sources


def _optional_connector_status(module_name: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(module_name)
        status_fn = getattr(module, "status", None)
        if not callable(status_fn):
            return {"ok": False, "error": "status_not_available"}
        status = status_fn()
        return status if isinstance(status, dict) else {"ok": False, "error": "status_returned_non_object"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _claude_desktop_evidence_summary(records: list[dict[str, Any]], gaps: list[dict[str, Any]]) -> dict[str, Any]:
    def _is_desktop_local_store_source(item: dict[str, Any]) -> bool:
        return source_system_gap_probe_kind(_safe_str(item.get("source_system"))) == "desktop_local_store_status"

    entrypoint_records = [
        item for item in records
        if item.get("desktop_entrypoint_detected")
        or _safe_str(item.get("conversation_origin")) == "claude_desktop_entrypoint_claude_code_session"
    ]
    entrypoint_guarded = [
        item for item in entrypoint_records
        if item.get("guard_status") in {"record_guarded", "record_stat_guarded", "raw_partial_conversation"}
    ]
    authorized_raw_records = [
        item for item in records
        if _is_desktop_local_store_source(item)
        and item.get("artifact_type") in CLAUDE_DESKTOP_RAW_FORMATS
    ]
    authorized_raw_guarded = [
        item for item in authorized_raw_records
        if item.get("guard_status") in {
            "record_guarded",
            "record_stat_guarded",
            "raw_partial_conversation",
            "authorized_raw_recoverable_source_missing",
        }
    ]

    code_status = _optional_connector_status("claude_code_local_connector")
    desktop_status = _optional_connector_status("claude_desktop_connector")
    desktop_gap = next((item for item in gaps if _is_desktop_local_store_source(item)), {})
    metadata_count = int(code_status.get("desktop_session_metadata_count") or 0)
    proxy_count = int(
        desktop_status.get("relay_gateway_request_count")
        or desktop_gap.get("relay_gateway_request_count")
        or desktop_status.get("local_relay_gateway_request_count")
        or desktop_gap.get("local_relay_gateway_request_count")
        or 0
    )
    proxy_detected = bool(
        desktop_status.get("relay_gateway_request_log_detected")
        or desktop_gap.get("relay_gateway_request_log_detected")
        or desktop_status.get("local_relay_gateway_request_log_detected")
        or desktop_gap.get("local_relay_gateway_request_log_detected")
        or proxy_count
    )
    body_guarded_count = len(entrypoint_guarded) + len(authorized_raw_guarded)
    body_candidate_count = len(entrypoint_records) + len(authorized_raw_records)
    body_guarded = body_guarded_count > 0
    return {
        "source_system": "claude_desktop",
        "body_guarded": body_guarded,
        "body_guarded_count": body_guarded_count,
        "body_candidate_count": body_candidate_count,
        "entrypoint_jsonl_guarded_count": len(entrypoint_guarded),
        "entrypoint_jsonl_candidate_count": len(entrypoint_records),
        "entrypoint_jsonl_is_full_body": True,
        "authorized_raw_guarded_count": len(authorized_raw_guarded),
        "authorized_raw_candidate_count": len(authorized_raw_records),
        "authorized_raw_is_full_body": True,
        "metadata_link_count": metadata_count,
        "metadata_detected": metadata_count > 0,
        "metadata_is_conversation_body": False,
        "metadata_boundary": code_status.get("desktop_metadata_policy", "metadata_links_session_to_cli_session_not_chat_body"),
        "proxy_request_evidence_count": proxy_count,
        "proxy_request_evidence_detected": proxy_detected,
        "proxy_request_log_is_conversation_body": False,
        "proxy_request_visibility_boundary": (
            desktop_status.get("relay_gateway_visibility_boundary")
            or desktop_gap.get("relay_gateway_visibility_boundary")
            or desktop_status.get("local_relay_gateway_visibility_boundary")
            or desktop_gap.get("local_relay_gateway_visibility_boundary")
            or "request_metadata_not_chat_body"
        ),
        "latest_proxy_status_code": (
            desktop_status.get("relay_gateway_latest_status_code")
            if desktop_status.get("relay_gateway_latest_status_code") is not None
            else (
                desktop_gap.get("relay_gateway_latest_status_code")
                if desktop_gap.get("relay_gateway_latest_status_code") is not None
                else (
                    desktop_status.get("local_relay_gateway_latest_status_code")
                    if desktop_status.get("local_relay_gateway_latest_status_code") is not None
                    else desktop_gap.get("local_relay_gateway_latest_status_code")
                )
            )
        ),
        "record_boundary": "full_body_requires_entrypoint_jsonl_or_authorized_raw_not_metadata_or_proxy_log",
        "evidence_order": [
            "entrypoint_jsonl_full_body",
            "authorized_raw_full_body",
            "desktop_metadata_link",
            "local_relay_proxy_request_log",
        ],
    }



# Canonical record index lives in raw_record_canonical_index.py under
# tiandao_raw_record_canonical_index.v1. Names are re-exported here for
# compatibility with existing callers and tests.

def build_guardian_status(
    *,
    limit: int = 20,
    include_gaps: bool = True,
    oversize_bytes: int = DEFAULT_JSONL_OVERSIZE_BYTES,
    write_index: bool = False,
    auto_backfill: bool = False,
    scan_mode: str = "full",
    compact: bool = False,
    public: bool = True,
    source_systems: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    scan_mode = "fast" if str(scan_mode or "").lower() in {"fast", "stat", "quick"} else "full"
    source_filter = {
        str(value or "").strip()
        for value in (source_systems or [])
        if str(value or "").strip()
    }
    backfill_result: dict[str, Any] | None = None
    if auto_backfill:
        backfill_result = run_raw_backfill(limit=limit)

    records: list[dict[str, Any]] = []
    for source_system, module_name in GUARDED_CONNECTORS:
        if source_filter and source_system not in source_filter:
            continue
        records.extend(_connector_records(
            source_system,
            module_name,
            limit=limit,
            oversize_bytes=oversize_bytes,
            scan_mode=scan_mode,
        ))
    if not source_filter or "claude_desktop" in source_filter:
        records.extend(_claude_desktop_authorized_raw_records(
            limit=limit,
            oversize_bytes=oversize_bytes,
            scan_mode=scan_mode,
        ))
    if not source_filter or "openclaw" in source_filter:
        records.extend(_openclaw_records(
            limit=limit,
            oversize_bytes=oversize_bytes,
            scan_mode=scan_mode,
        ))
    if not source_filter or "hermes" in source_filter:
        records.extend(_hermes_records(
            limit=limit,
            oversize_bytes=oversize_bytes,
            scan_mode=scan_mode,
        ))
    attach_origin_events(records, computer_id=node_id())
    time_origin = origin_summary(records)

    guarded_source_systems = set()
    observed_source_systems = set()
    for item in records:
        observed_source_systems.update(_coverage_source_systems(item))
        if item.get("guard_status") in {
            "record_guarded",
            "record_stat_guarded",
            "raw_partial_conversation",
            "authorized_raw_recoverable_source_missing",
        }:
            guarded_source_systems.update(_coverage_source_systems(item))
    gaps = [
        _source_gap_status(source)
        for source in KNOWN_GAP_SOURCES
        if source not in guarded_source_systems and source not in observed_source_systems
    ] if include_gaps else []
    inactive_sources = [
        item for item in gaps
        if item.get("guard_status") == "no_live_source_sample"
    ]
    actionable_gaps = [
        item for item in gaps
        if item.get("guard_status") != "no_live_source_sample"
    ]
    claude_desktop_evidence = _claude_desktop_evidence_summary(records, gaps)
    guarded = [item for item in records if item.get("guard_status") in {"record_guarded", "record_stat_guarded"}]
    recoverable = [item for item in records if item.get("recoverable_from_raw")]
    unhealthy = [
        item for item in records
        if item.get("guard_status") not in {"record_guarded", "record_stat_guarded"}
    ]
    corrupt = [
        item for item in records
        if item.get("guard_status") in {"source_corrupt", "raw_corrupt"}
    ]
    oversized = [
        item for item in records
        if any("oversized" in warning for warning in item.get("health_warnings", []))
    ]
    partial = [
        item for item in records
        if "partial" in _safe_str(item.get("guard_status"))
        or item.get("guard_status") in {"source_metadata_incomplete"}
    ]
    lagging = [
        item for item in records
        if item.get("guard_status") in {"raw_missing", "raw_lagging"}
    ]
    catching_up = [
        item for item in records
        if item.get("guard_status") == "raw_catching_up"
    ]
    raw_not_current = [
        item for item in records
        if item.get("guard_status") in {"raw_missing", "raw_lagging", "raw_catching_up"}
    ]
    backfill_recommended = [
        item for item in records if item.get("backfill_recommended")
    ]
    attention_records = [
        item for item in records
        if item.get("guard_status") in {"raw_missing", "source_corrupt", "raw_corrupt"}
        or item.get("backfill_recommended")
    ]
    report: dict[str, Any] = {
        "ok": not corrupt and not attention_records,
        "contract": RAW_RECORD_GUARDIAN_CONTRACT,
        "generated_at": ts(),
        "read_only": not write_index and not auto_backfill,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": bool(auto_backfill),
        "index_contract": CANONICAL_RECORD_INDEX_CONTRACT,
        "backfill_contract": RAW_BACKFILL_CONTRACT,
        "time_origin_contract": time_origin.get("contract"),
        "raw_origin_event_contract": time_origin.get("raw_origin_event_contract"),
        "scan_mode": scan_mode,
        "fast_status_only": scan_mode == "fast",
        "records_db_path": _public_path_label(records_db_path()) if public else str(records_db_path()),
        "source_system_filter": sorted(source_filter),
        "guarded_sources": sorted(IMPLEMENTED_SOURCE_GUARDIANS | guarded_source_systems),
        "gap_sources": [item.get("source_system") for item in actionable_gaps],
        "inactive_sources": [item.get("source_system") for item in inactive_sources],
        "summary": {
            "record_count": len(records),
            "record_guarded_count": len(guarded),
            "record_stat_guarded_count": len([item for item in records if item.get("guard_status") == "record_stat_guarded"]),
            "unhealthy_record_count": len(unhealthy),
            "raw_not_current_count": len(raw_not_current),
            "raw_lagging_or_missing_count": len(lagging),
            "raw_catching_up_count": len(catching_up),
            "raw_active_catching_up_count": len(catching_up),
            "raw_attention_count": len(attention_records),
            "corrupt_record_count": len(corrupt),
            "oversized_record_count": len(oversized),
            "partial_record_count": len(partial),
            "recoverable_from_raw_count": len(recoverable),
            "gap_source_count": len(actionable_gaps),
            "inactive_source_count": len(inactive_sources),
            "backfill_recommended_count": len(backfill_recommended),
            "origin_event_count": time_origin.get("origin_event_count", 0),
            "origin_witnessed_count": time_origin.get("origin_witnessed_count", 0),
            "lost_source_count": time_origin.get("lost_source_count", 0),
            "lost_raw_count": time_origin.get("lost_raw_count", 0),
            "source_without_origin_count": time_origin.get("source_without_origin_count", 0),
            "origin_without_raw_count": time_origin.get("origin_without_raw_count", 0),
            "raw_without_origin_count": time_origin.get("raw_without_origin_count", 0),
            "recoverable_origin_count": time_origin.get("recoverable_origin_count", 0),
            "max_origin_lag_milliseconds": time_origin.get("max_origin_lag_milliseconds", 0),
            "lost_labels": time_origin.get("lost_labels", {}),
            "max_raw_lag_bytes": max((
                int(((item.get("sync") or {}).get("raw_archive_lag_bytes", 0)) or 0)
                for item in records
            ), default=0),
            "max_raw_lag_milliseconds": max((
                int(((item.get("sync") or {}).get("raw_archive_lag_milliseconds", 0)) or 0)
                for item in records
            ), default=0),
        },
        "time_origin": time_origin,
        "compact": bool(compact),
        "source_evidence": {
            "claude_desktop": claude_desktop_evidence,
        },
        "claude_desktop_evidence": claude_desktop_evidence,
        "records": _compact_records(records) if compact else records,
        "record_details_truncated": bool(compact),
        "record_detail_count": len(records),
        "gaps": actionable_gaps,
        "source_gaps": actionable_gaps,
        "inactive_source_details": inactive_sources,
        "notes": [
            "record_guarded means source and raw both exist, raw is current, metadata is sane, and user+assistant turns are present.",
            "record_stat_guarded is a fast status-page check: source and raw files exist and sizes are current, but full JSONL body health was not scanned.",
            "时间起源 means raw has been witnessed; source without a raw origin is 遗失 raw, and raw without its source anchor is 遗失源.",
            "entry_detected_body_unverified means the platform entry exists but complete conversation text is not proven.",
            "guardian_gap means a source/raw pair scanner is not implemented for that platform yet.",
            "no_live_source_sample means this machine has no local sample for an implemented connector; it is listed as inactive, not as a record guard gap.",
        ],
    }
    if write_index:
        report["index_update"] = update_records_index(
            report,
            repair_missing_raw_offsets=scan_mode != "fast",
            repair_identity_drift=scan_mode != "fast",
        )
        report["write_performed"] = True
    if backfill_result is not None:
        report["backfill"] = backfill_result
        report["write_performed"] = True
    if public:
        report = _sanitize_public_payload(report)
    return report


def status() -> dict[str, Any]:
    """Lightweight connector-style status for dashboards."""
    report = build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        compact=True,
        public=True,
    )
    summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
    return {
        "ok": bool(report.get("ok")),
        "source_system": "raw_record_guardian",
        "collector_status": "continuous_incremental",
        "reachable": True,
        "record_count": summary.get("record_count", 0),
        "record_guarded_count": summary.get("record_guarded_count", 0),
        "raw_not_current_count": summary.get("raw_not_current_count", 0),
        "raw_attention_count": summary.get("raw_attention_count", summary.get("raw_lagging_or_missing_count", 0)),
        "raw_catching_up_count": summary.get("raw_catching_up_count", 0),
        "origin_event_count": summary.get("origin_event_count", 0),
        "lost_source_count": summary.get("lost_source_count", 0),
        "lost_raw_count": summary.get("lost_raw_count", 0),
        "backfill_recommended_count": summary.get("backfill_recommended_count", 0),
        "guarded_sources": report.get("guarded_sources", []),
        "gap_sources": report.get("gap_sources", []),
        "raw_sync": {
            "status": "raw_lagging_sla_breach" if summary.get("backfill_recommended_count") else "ok",
            "missing_or_stale_count": summary.get("raw_attention_count", summary.get("backfill_recommended_count", 0)),
            "catching_up_count": summary.get("raw_catching_up_count", 0),
        },
    }


def _compact_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return status-page friendly records without heavy scan payloads."""
    compacted: list[dict[str, Any]] = []
    for item in records:
        guard_status = item.get("guard_status")
        if guard_status in {"record_guarded", "record_stat_guarded"} and not item.get("backfill_recommended"):
            continue
        source_scan = item.get("source_scan") if isinstance(item.get("source_scan"), dict) else {}
        raw_scan = item.get("raw_scan") if isinstance(item.get("raw_scan"), dict) else {}
        compacted.append({
            "source_system": item.get("source_system", ""),
            "artifact_type": item.get("artifact_type", ""),
            "session_id": item.get("session_id", ""),
            "raw_artifact_id": item.get("raw_artifact_id", ""),
            "canonical_window_id": item.get("canonical_window_id", ""),
            "project_id": item.get("project_id", ""),
            "thread_name": item.get("thread_name", ""),
            "guard_status": guard_status,
            "origin_id": item.get("origin_id", ""),
            "origin_status": item.get("origin_status", ""),
            "origin_label": item.get("origin_label", ""),
            "origin_seen": bool(item.get("origin_seen")),
            "raw_current": bool(item.get("raw_current")),
            "recoverable_from_raw": bool(item.get("recoverable_from_raw")),
            "backfill_recommended": bool(item.get("backfill_recommended")),
            "source_path_label": item.get("source_path_label", ""),
            "raw_path_label": item.get("raw_path_label", ""),
            "source_exists": bool(source_scan.get("exists")),
            "raw_exists": bool(raw_scan.get("exists")),
            "source_health_status": source_scan.get("health_status", ""),
            "raw_health_status": raw_scan.get("health_status", ""),
            "source_size_bytes": int(source_scan.get("size_bytes", 0) or 0),
            "raw_size_bytes": int(raw_scan.get("size_bytes", 0) or 0),
            "health_warnings": item.get("health_warnings", []),
            "sync": item.get("sync") or {},
            "scan_mode": item.get("scan_mode", ""),
        })
    return compacted


def main() -> int:
    parser = argparse.ArgumentParser(description="Memcore raw record guardian")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--oversize-bytes", type=int, default=DEFAULT_JSONL_OVERSIZE_BYTES)
    parser.add_argument("--write-index", action="store_true")
    parser.add_argument("--auto-backfill", action="store_true")
    parser.add_argument("--mode", choices=("full", "fast"), default="full")
    parser.add_argument("--no-gaps", action="store_true")
    parser.add_argument("--private-paths", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    payload = build_guardian_status(
        limit=args.limit,
        include_gaps=not args.no_gaps,
        oversize_bytes=args.oversize_bytes,
        write_index=args.write_index,
        auto_backfill=args.auto_backfill,
        scan_mode=args.mode,
        public=not args.private_paths,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
