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
    from raw_origin_event import attach_origin_events, origin_summary
except ImportError:  # pragma: no cover
    from src.raw_origin_event import attach_origin_events, origin_summary

UTC = timezone.utc
RAW_RECORD_GUARDIAN_CONTRACT = "raw_record_guardian.v1"
CANONICAL_RECORD_INDEX_CONTRACT = "canonical_record_index.v2"
CANONICAL_MESSAGE_INDEX_SOURCE_SYSTEMS = {
    "codex",
    "claude_code_cli",
    "claude_desktop",
    "openclaw",
    "hermes",
    "kiro",
}
CANONICAL_MESSAGE_RAW_AS_SOURCE_SYSTEMS = {"claude_desktop", "hermes", "kiro"}
SESSION_WINDOW_ID_SOURCE_SYSTEMS = {"codex", "claude_code_cli"}
DEFAULT_JSONL_OVERSIZE_BYTES = 1024 * 1024
DEFAULT_CANONICAL_INDEX_CHUNK_CHARS = 4096
DEFAULT_CANONICAL_INDEX_MAX_JSON_LINE_BYTES = 16 * 1024 * 1024
RAW_BACKFILL_CONTRACT = "raw_record_backfill.v1"
DEFAULT_BACKFILL_RECOMMEND_AFTER_MS = 5000
CLAUDE_DESKTOP_AUTHORIZED_RAW_FORMAT = "claude_desktop_authorized_local_store_jsonl"
CLAUDE_DESKTOP_PROJECTS_JSONL_RAW_FORMAT = "claude_projects_jsonl_desktop_entrypoint"
CLAUDE_DESKTOP_LEGACY_PROJECTS_JSONL_RAW_FORMAT = "ccswitch_claude_provider_projects_jsonl"
CLAUDE_DESKTOP_RAW_FORMATS = (
    CLAUDE_DESKTOP_AUTHORIZED_RAW_FORMAT,
    CLAUDE_DESKTOP_PROJECTS_JSONL_RAW_FORMAT,
    CLAUDE_DESKTOP_LEGACY_PROJECTS_JSONL_RAW_FORMAT,
)
OPENCLAW_NATIVE_RAW_FORMAT = "openclaw_session_jsonl"
HERMES_STATE_DB_RAW_FORMAT = "hermes_state_db_messages_jsonl"
GUARDED_CONNECTORS = (
    ("codex", "codex_local_connector"),
    ("claude_code_cli", "claude_code_local_connector"),
    ("kiro", "kiro_local_connector"),
)
IMPLEMENTED_SOURCE_GUARDIANS = {item[0] for item in GUARDED_CONNECTORS} | {"openclaw", "hermes"}
KNOWN_GAP_SOURCES = ("claude_desktop", "openclaw", "hermes", "kiro")


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
        "ccswitch_claude_provider_projects_jsonl": "claude_projects_jsonl_desktop_entrypoint",
        "ccswitch_gateway": "local_relay_gateway",
        "ccswitch_proxy": "local_relay_proxy",
        "ccswitch": "local_relay",
        "CC Switch": "Local Relay",
        "cc-switch": "local-relay",
        "com.ccswitch": "local.relay",
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

    if source_system in SESSION_WINDOW_ID_SOURCE_SYSTEMS and session_id:
        if canonical_window_id and canonical_window_id != session_id:
            normalized.setdefault("source_refs_canonical_window_id", canonical_window_id)
            if not project_id:
                project_id = canonical_window_id
        canonical_window_id = session_id

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


def _canonical_index_chunk_chars() -> int:
    raw = os.environ.get("MEMCORE_CANONICAL_INDEX_CHUNK_CHARS", "")
    try:
        value = int(raw)
    except Exception:
        value = DEFAULT_CANONICAL_INDEX_CHUNK_CHARS
    return max(512, min(value, 64 * 1024))


def _canonical_index_max_json_line_bytes() -> int:
    raw = os.environ.get("MEMCORE_CANONICAL_INDEX_MAX_JSON_LINE_BYTES", "")
    try:
        value = int(raw)
    except Exception:
        value = DEFAULT_CANONICAL_INDEX_MAX_JSON_LINE_BYTES
    return max(1024, min(value, 512 * 1024 * 1024))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return str(value)


def _role_and_content_from_record(source_system: str, record: dict[str, Any]) -> tuple[str, bool]:
    source = _safe_str(source_system)
    if source == "codex":
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        role = _safe_str(payload.get("role") or record.get("role"))
        content = payload.get("content") if "content" in payload else record.get("content")
        nested = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        if not role and nested:
            role = _safe_str(nested.get("role"))
        if content is None and nested:
            content = nested.get("content")
        return role, bool(_text_from_content(content).strip())

    if source == "claude_code_cli":
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
    source = _safe_str(source_system)
    if source == "openclaw":
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
    if source_system == "codex":
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
    if source_system == "claude_code_cli":
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
    if source_system == "kiro":
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


def hermes_backfill_recommendation(*, limit: int = 80) -> dict[str, Any]:
    """Fast read-only check for Hermes sessions that still need raw export."""
    records = _hermes_records(
        limit=max(1, min(int(limit or 80), 200)),
        oversize_bytes=DEFAULT_JSONL_OVERSIZE_BYTES,
        scan_mode="fast",
    )
    recommended = [
        item for item in records
        if item.get("source_system") == "hermes" and item.get("backfill_recommended")
    ]
    return {
        "ok": True,
        "source_system": "hermes",
        "recommended_count": len(recommended),
        "session_ids": [item.get("session_id", "") for item in recommended[:20]],
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
    }


def _connector_backfill(source_system: str, module_name: str, *, limit: int) -> dict[str, Any]:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        return {
            "source_system": source_system,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        if hasattr(module, "catch_up_latest_sessions"):
            result = module.catch_up_latest_sessions(limit=limit)
        elif hasattr(module, "scan_sessions"):
            result = module.scan_sessions(dry_run=False, limit=limit, public=False)
        else:
            return {
                "source_system": source_system,
                "ok": False,
                "error": "connector_has_no_backfill_method",
            }
    except Exception as exc:
        return {
            "source_system": source_system,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "source_system": source_system,
        "ok": bool(result.get("ok", True)),
        "changed": int(result.get("changed", 0) or 0),
        "raw_sync": result.get("raw_sync") or {},
        "result": result,
    }


def _openclaw_backfill(*, limit: int) -> dict[str, Any]:
    import shutil

    def file_hash(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    changed = 0
    items: list[dict[str, Any]] = []
    for artifact in _openclaw_source_artifacts(limit):
        try:
            src = Path(str(artifact.get("source_path") or "")).expanduser()
            dest = _openclaw_raw_path_for_artifact(artifact)
            src_stat = src.stat()
            src_hash = file_hash(src)
            dest_hash = file_hash(dest) if dest.exists() else ""
            copied = src_hash != dest_hash
            if copied:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                meta = {
                    "source_system": "openclaw",
                    "source_path": str(src),
                    "source_mtime": src_stat.st_mtime,
                    "source_checksum": src_hash,
                    "archived_at": ts(),
                    "source_computer": node_id(),
                    "source_window": artifact.get("canonical_window_id", ""),
                    "source_session": artifact.get("session_id", ""),
                    "native_artifact_format": OPENCLAW_NATIVE_RAW_FORMAT,
                    "raw_archive_layout": "computer_first",
                }
                with Path(str(dest) + ".meta.json").open("w", encoding="utf-8") as handle:
                    json.dump(meta, handle, ensure_ascii=False, indent=2)
            if copied:
                changed += 1
            items.append({
                "session_id": artifact.get("session_id", ""),
                "raw_path": str(dest),
                "changed": copied,
                "write_performed": copied,
                "platform_write_performed": False,
                "memory_write_performed": copied,
            })
        except Exception as exc:
            items.append({
                "session_id": artifact.get("session_id", ""),
                "ok": False,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "platform_write_performed": False,
            })
    return {
        "source_system": "openclaw",
        "ok": all(item.get("ok", True) is not False for item in items),
        "changed": changed,
        "raw_sync": {
            "status": "openclaw_source_jsonl_copied_to_raw",
            "items_checked": len(items),
            "missing_or_stale_count": len([item for item in items if item.get("changed")]),
        },
        "result": {
            "items": items,
            "write_performed": bool(changed),
            "platform_write_performed": False,
            "memory_write_performed": bool(changed),
        },
    }


def _json_text_or_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def _hermes_message_select_columns(conn: sqlite3.Connection) -> list[str]:
    columns = [row[1] for row in conn.execute("pragma table_info(messages)")]
    wanted = [
        "id",
        "session_id",
        "role",
        "content",
        "tool_call_id",
        "tool_calls",
        "tool_name",
        "timestamp",
        "token_count",
        "finish_reason",
        "reasoning",
        "reasoning_content",
        "reasoning_details",
        "codex_reasoning_items",
        "codex_message_items",
        "platform_message_id",
        "observed",
        "active",
    ]
    return [column for column in wanted if column in columns]


def _hermes_read_session_messages(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    columns = _hermes_message_select_columns(conn)
    if not columns:
        return []
    order_column = "id" if "id" in columns else "timestamp"
    rows = conn.execute(
        f"select {', '.join(columns)} from messages where session_id=? order by {order_column} asc",
        (session_id,),
    ).fetchall()
    messages: list[dict[str, Any]] = []
    for row in rows:
        item = dict(zip(columns, row))
        for key in (
            "tool_calls",
            "reasoning_details",
            "codex_reasoning_items",
            "codex_message_items",
        ):
            if key in item:
                item[key] = _json_text_or_value(item.get(key))
        messages.append(item)
    return messages


def _hermes_session_metadata(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    columns = [row[1] for row in conn.execute("pragma table_info(sessions)")]
    wanted = [
        column for column in (
            "id",
            "source",
            "user_id",
            "model",
            "model_config",
            "parent_session_id",
            "started_at",
            "ended_at",
            "end_reason",
            "message_count",
            "title",
            "cwd",
        )
        if column in columns
    ]
    if not wanted:
        return {"id": session_id}
    row = conn.execute(
        f"select {', '.join(wanted)} from sessions where id=?",
        (session_id,),
    ).fetchone()
    if not row:
        return {"id": session_id}
    data = dict(zip(wanted, row))
    if "model_config" in data:
        data["model_config"] = _json_text_or_value(data.get("model_config"))
    return data


def _hermes_raw_record_from_message(
    *,
    db_path: Path,
    raw_path: Path,
    session_meta: dict[str, Any],
    message: dict[str, Any],
) -> dict[str, Any]:
    role = _safe_str(message.get("role"))
    message_id = _safe_str(message.get("id") or message.get("platform_message_id"))
    session_id = _safe_str(message.get("session_id") or session_meta.get("id"))
    content = message.get("content") or ""
    timestamp = (
        _iso_from_epochish(message.get("timestamp"))
        or _iso_from_epochish(session_meta.get("started_at"))
        or "1970-01-01T00:00:00Z"
    )
    text_type = "input_text" if role in {"user", "human"} else "output_text"
    payload_content = [{"type": text_type, "text": str(content)}] if content != "" else []
    record_id_basis = "|".join([
        "hermes",
        str(db_path),
        session_id,
        message_id,
        _safe_str(message.get("timestamp")),
    ])
    return {
        "timestamp": timestamp,
        "id": "hermes-" + hashlib.sha256(record_id_basis.encode("utf-8")).hexdigest()[:24],
        "type": "response_item",
        "source_system": "hermes",
        "payload": {
            "type": "message",
            "role": role,
            "content": payload_content,
        },
        "hermes": {
            "message_id": message.get("id"),
            "platform_message_id": message.get("platform_message_id"),
            "tool_call_id": message.get("tool_call_id"),
            "tool_name": message.get("tool_name"),
            "tool_calls": message.get("tool_calls"),
            "token_count": message.get("token_count"),
            "finish_reason": message.get("finish_reason"),
            "reasoning": message.get("reasoning"),
            "reasoning_content": message.get("reasoning_content"),
            "reasoning_details": message.get("reasoning_details"),
            "codex_reasoning_items": message.get("codex_reasoning_items"),
            "codex_message_items": message.get("codex_message_items"),
            "observed": message.get("observed"),
            "active": message.get("active"),
            "session": session_meta,
        },
        "source_refs": {
            "source_system": "hermes",
            "source_path": str(db_path),
            "source_table": "messages",
            "source_row_id": message.get("id"),
            "session_id": session_id,
            "canonical_window_id": session_id,
            "raw_session_path": str(raw_path),
            "native_artifact_format": HERMES_STATE_DB_RAW_FORMAT,
            "raw_archive_layout": "computer_first",
            "source_storage": "sqlite_state_db",
        },
    }


def _write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> tuple[bool, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records)
    payload_bytes = payload.encode("utf-8")
    new_hash = hashlib.sha256(payload_bytes).hexdigest()
    old_hash = ""
    if path.exists():
        try:
            old_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            old_hash = ""
    if old_hash == new_hash:
        return False, new_hash
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload_bytes)
    tmp.replace(path)
    return True, new_hash


def _hermes_backfill(*, limit: int) -> dict[str, Any]:
    db_summary = _hermes_state_db_summary()
    if not db_summary.get("exists"):
        return {
            "source_system": "hermes",
            "ok": False,
            "changed": 0,
            "error": "hermes_state_db_missing",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }
    db_path = Path(db_summary.get("path", "")).expanduser()
    session_summaries = [
        item for item in db_summary.get("session_summaries", [])
        if isinstance(item, dict) and item.get("session_id")
    ]
    session_ids = [
        _safe_str(item.get("session_id"))
        for item in session_summaries[: max(1, int(limit or 20))]
    ]
    if not session_ids and db_summary.get("session_id"):
        session_ids = [_safe_str(db_summary.get("session_id"))]
    changed = 0
    items: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
        try:
            for session_id in session_ids:
                try:
                    raw_path = _hermes_raw_paths_for_session(session_id)[0]
                    session_meta = _hermes_session_metadata(conn, session_id)
                    messages = _hermes_read_session_messages(conn, session_id)
                    records = [
                        _hermes_raw_record_from_message(
                            db_path=db_path,
                            raw_path=raw_path,
                            session_meta=session_meta,
                            message=message,
                        )
                        for message in messages
                    ]
                    wrote, checksum = _write_jsonl_atomic(raw_path, records)
                    if wrote:
                        changed += 1
                        meta = {
                            "source_system": "hermes",
                            "source_path": str(db_path),
                            "source_checksum": checksum,
                            "archived_at": ts(),
                            "source_computer": node_id(),
                            "source_session": session_id,
                            "native_artifact_format": HERMES_STATE_DB_RAW_FORMAT,
                            "raw_archive_layout": "computer_first",
                            "source_storage": "sqlite_state_db",
                            "message_count": len(messages),
                            "platform_write_performed": False,
                        }
                        with Path(str(raw_path) + ".meta.json").open("w", encoding="utf-8") as handle:
                            json.dump(meta, handle, ensure_ascii=False, indent=2)
                    items.append({
                        "session_id": session_id,
                        "raw_path": str(raw_path),
                        "message_count": len(messages),
                        "changed": wrote,
                        "write_performed": wrote,
                        "platform_write_performed": False,
                        "memory_write_performed": wrote,
                    })
                except Exception as exc:
                    items.append({
                        "session_id": session_id,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                        "platform_write_performed": False,
                    })
        finally:
            conn.close()
    except Exception as exc:
        return {
            "source_system": "hermes",
            "ok": False,
            "changed": 0,
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }
    return {
        "source_system": "hermes",
        "ok": all(item.get("ok", True) is not False for item in items),
        "changed": changed,
        "write_performed": bool(changed),
        "platform_write_performed": False,
        "memory_write_performed": bool(changed),
        "raw_sync": {
            "status": "hermes_state_db_messages_exported_to_raw",
            "items_checked": len(items),
            "missing_or_stale_count": len([item for item in items if item.get("changed")]),
            "source_storage": "sqlite_state_db",
        },
        "result": {
            "items": items,
            "write_performed": bool(changed),
            "platform_write_performed": False,
            "memory_write_performed": bool(changed),
        },
    }


def run_raw_backfill(*, limit: int = 20, source_systems: list[str] | None = None) -> dict[str, Any]:
    requested = set(source_systems or [])
    supported = {source_system for source_system, _ in GUARDED_CONNECTORS} | {"openclaw", "hermes"}
    results = []
    for source_system, module_name in GUARDED_CONNECTORS:
        if requested and source_system not in requested:
            continue
        results.append(_connector_backfill(source_system, module_name, limit=limit))
    if not requested or "openclaw" in requested:
        results.append(_openclaw_backfill(limit=limit))
    if not requested or "hermes" in requested:
        results.append(_hermes_backfill(limit=limit))
    for source_system in sorted(requested - supported):
        results.append({
            "source_system": source_system,
            "ok": False,
            "changed": 0,
            "error": "backfill_not_implemented_for_source_system",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        })
    return {
        "ok": all(item.get("ok") for item in results),
        "contract": RAW_BACKFILL_CONTRACT,
        "generated_at": ts(),
        "write_performed": True,
        "platform_write_performed": False,
        "memory_write_performed": True,
        "limit": limit,
        "source_systems": [item.get("source_system") for item in results],
        "results": results,
    }


def _source_gap_status(source_system: str) -> dict[str, Any]:
    if source_system == "claude_desktop":
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
                or status.get("ccswitch_gateway_request_log_detected")
            ),
            "relay_gateway_request_count": int(
                status.get("relay_gateway_request_count")
                or status.get("ccswitch_gateway_request_count")
                or 0
            ),
            "relay_gateway_latest_status_code": (
                status.get("relay_gateway_latest_status_code")
                if status.get("relay_gateway_latest_status_code") is not None
                else status.get("ccswitch_gateway_latest_status_code")
            ),
            "relay_gateway_visibility_boundary": (
                status.get("relay_gateway_visibility_boundary")
                or status.get("ccswitch_gateway_visibility_boundary", "")
            ),
        }
    if source_system == "kiro":
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
    if source_system == "openclaw":
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
    if source_system == "hermes":
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
        if item.get("source_system") == "claude_desktop"
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
    desktop_gap = next((item for item in gaps if item.get("source_system") == "claude_desktop"), {})
    metadata_count = int(code_status.get("desktop_session_metadata_count") or 0)
    proxy_count = int(
        desktop_status.get("relay_gateway_request_count")
        or desktop_gap.get("relay_gateway_request_count")
        or desktop_status.get("ccswitch_gateway_request_count")
        or desktop_gap.get("ccswitch_gateway_request_count")
        or 0
    )
    proxy_detected = bool(
        desktop_status.get("relay_gateway_request_log_detected")
        or desktop_gap.get("relay_gateway_request_log_detected")
        or desktop_status.get("ccswitch_gateway_request_log_detected")
        or desktop_gap.get("ccswitch_gateway_request_log_detected")
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
            or desktop_status.get("ccswitch_gateway_visibility_boundary")
            or desktop_gap.get("ccswitch_gateway_visibility_boundary")
            or "request_metadata_not_chat_body"
        ),
        "latest_proxy_status_code": (
            desktop_status.get("relay_gateway_latest_status_code")
            if desktop_status.get("relay_gateway_latest_status_code") is not None
            else (
                desktop_gap.get("relay_gateway_latest_status_code")
                if desktop_gap.get("relay_gateway_latest_status_code") is not None
                else (
                    desktop_status.get("ccswitch_gateway_latest_status_code")
                    if desktop_status.get("ccswitch_gateway_latest_status_code") is not None
                    else desktop_gap.get("ccswitch_gateway_latest_status_code")
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


def records_db_path() -> Path:
    override = os.environ.get("MEMCORE_RECORDS_DB", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(get_memcore_root()).expanduser() / "output" / "records" / "records.db"


def records_db_busy_timeout_milliseconds() -> int:
    raw = os.environ.get("MEMCORE_RECORDS_DB_BUSY_TIMEOUT_MS", "").strip()
    if raw:
        try:
            return max(1000, min(int(raw), 120_000))
        except ValueError:
            pass
    return 30_000


def _connect_records_db(path: Path) -> sqlite3.Connection:
    timeout_ms = records_db_busy_timeout_milliseconds()
    conn = sqlite3.connect(path, timeout=timeout_ms / 1000)
    conn.execute(f"pragma busy_timeout={timeout_ms}")
    try:
        conn.execute("pragma journal_mode=wal")
    except sqlite3.OperationalError:
        pass
    return conn


def _is_sqlite_locked(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def _record_id(item: dict[str, Any]) -> str:
    basis = "|".join([
        _safe_str(item.get("source_system")),
        _safe_str(item.get("session_id")),
        _safe_str(item.get("raw_artifact_id")),
        _safe_str(item.get("source_path")),
        _safe_str(item.get("raw_path")),
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _ensure_index_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists records (
            record_id text primary key,
            source_system text not null,
            session_id text,
            raw_artifact_id text,
            canonical_window_id text,
            project_id text,
            source_path text,
            raw_path text,
            source_mtime text,
            raw_mtime text,
            source_size_bytes integer,
            raw_size_bytes integer,
            user_turn_count integer,
            assistant_turn_count integer,
            bad_json_line_count integer,
            oversize_record_count integer,
            metadata_ok integer,
            has_user_and_assistant integer,
            raw_current integer,
            recoverable_from_raw integer,
            guard_status text,
            updated_at text,
            payload_json text
        )
        """
    )
    conn.execute("create index if not exists idx_records_source_system on records(source_system)")
    conn.execute("create index if not exists idx_records_guard_status on records(guard_status)")
    conn.execute("create index if not exists idx_records_session on records(session_id)")
    conn.execute(
        """
        create table if not exists canonical_sessions (
            record_id text primary key,
            source_system text not null,
            session_id text,
            raw_artifact_id text,
            canonical_window_id text,
            project_id text,
            project_root text,
            thread_name text,
            source_path text,
            raw_path text,
            source_mtime text,
            raw_mtime text,
            source_size_bytes integer,
            raw_size_bytes integer,
            source_line_count integer,
            raw_line_count integer,
            indexed_message_count integer,
            indexed_chunk_count integer,
            raw_indexed_message_count integer,
            raw_offset_coverage_count integer,
            bad_json_line_count integer,
            oversized_line_count integer,
            index_status text,
            updated_at text,
            payload_json text
        )
        """
    )
    conn.execute(
        """
        create table if not exists canonical_messages (
            message_id text primary key,
            record_id text not null,
            source_system text not null,
            session_id text,
            canonical_window_id text,
            project_id text,
            project_root text,
            source_path text,
            raw_path text,
            role text,
            native_type text,
            native_id text,
            timestamp text,
            line_no integer,
            raw_line_no integer,
            source_offset_start integer,
            source_offset_end integer,
            raw_offset_start integer,
            raw_offset_end integer,
            content_chars integer,
            content_hash text,
            line_hash text,
            content_preview text,
            raw_available integer,
            updated_at text,
            payload_json text
        )
        """
    )
    conn.execute(
        """
        create table if not exists canonical_chunks (
            chunk_id text primary key,
            message_id text not null,
            record_id text not null,
            source_system text not null,
            session_id text,
            canonical_window_id text,
            role text,
            chunk_index integer,
            chunk_start_char integer,
            chunk_end_char integer,
            source_offset_start integer,
            source_offset_end integer,
            raw_offset_start integer,
            raw_offset_end integer,
            content_hash text,
            chunk_text text,
            updated_at text
        )
        """
    )
    conn.execute(
        """
        create table if not exists canonical_line_health (
            line_health_id text primary key,
            record_id text not null,
            source_system text not null,
            session_id text,
            source_path text,
            file_side text,
            line_no integer,
            offset_start integer,
            offset_end integer,
            bytes integer,
            health_status text,
            error text,
            updated_at text
        )
        """
    )
    conn.execute(
        """
        create table if not exists origin_events (
            origin_id text primary key,
            record_id text not null,
            origin_contract text not null,
            origin_event_contract text not null,
            time_river_contract text,
            origin_layer text,
            origin_status text,
            origin_label text,
            origin_seen integer,
            source_system text,
            computer_id text,
            native_session_key text,
            session_id text,
            canonical_window_id text,
            source_path text,
            raw_path text,
            event_time text,
            captured_at text,
            audit_time text,
            content_hash text,
            byte_offset integer,
            line_no integer,
            source_refs_json text,
            payload_json text,
            updated_at text
        )
        """
    )
    conn.execute("create index if not exists idx_canonical_sessions_source on canonical_sessions(source_system)")
    conn.execute("create index if not exists idx_canonical_sessions_session on canonical_sessions(session_id)")
    conn.execute("create index if not exists idx_canonical_messages_record on canonical_messages(record_id)")
    conn.execute("create index if not exists idx_canonical_messages_source_session on canonical_messages(source_system, session_id)")
    conn.execute("create index if not exists idx_canonical_messages_source_session_time on canonical_messages(source_system, session_id, timestamp desc, line_no desc)")
    conn.execute("create index if not exists idx_canonical_messages_source_window_time on canonical_messages(source_system, canonical_window_id, timestamp desc, line_no desc)")
    conn.execute("create index if not exists idx_canonical_messages_offsets on canonical_messages(source_path, source_offset_start)")
    conn.execute("create index if not exists idx_canonical_chunks_record on canonical_chunks(record_id)")
    conn.execute("create index if not exists idx_canonical_chunks_message on canonical_chunks(message_id)")
    conn.execute("create index if not exists idx_canonical_line_health_record on canonical_line_health(record_id)")
    conn.execute("create index if not exists idx_origin_events_record on origin_events(record_id)")
    conn.execute("create index if not exists idx_origin_events_status on origin_events(origin_status)")
    conn.execute("create index if not exists idx_origin_events_source_session on origin_events(source_system, session_id)")


def _repair_session_window_identity_drift(conn: sqlite3.Connection) -> int:
    repaired = 0
    sources = tuple(sorted(SESSION_WINDOW_ID_SOURCE_SYSTEMS))
    placeholders = ",".join("?" for _ in sources)
    for table in ("records", "canonical_sessions", "canonical_messages"):
        cur = conn.execute(
            f"""
            update {table}
            set
                project_id = case
                    when (project_id is null or project_id = '')
                         and canonical_window_id is not null
                         and canonical_window_id != ''
                         and canonical_window_id != session_id
                    then canonical_window_id
                    else project_id
                end,
                canonical_window_id = session_id
            where source_system in ({placeholders})
              and session_id is not null
              and session_id != ''
              and canonical_window_id is not null
              and canonical_window_id != ''
              and canonical_window_id != session_id
            """,
            sources,
        )
        repaired += max(cur.rowcount or 0, 0)
    for table in ("canonical_chunks", "origin_events"):
        cur = conn.execute(
            f"""
            update {table}
            set canonical_window_id = session_id
            where source_system in ({placeholders})
              and session_id is not null
              and session_id != ''
              and canonical_window_id is not null
              and canonical_window_id != ''
              and canonical_window_id != session_id
            """,
            sources,
        )
        repaired += max(cur.rowcount or 0, 0)
    return repaired


def _jsonl_record_role_text(source_system: str, record: dict[str, Any]) -> dict[str, Any] | None:
    source = _safe_str(source_system)
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    nested_message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    native_type = _safe_str(record.get("type") or payload.get("type") or message.get("type"))
    native_id = _safe_str(
        record.get("id")
        or record.get("uuid")
        or payload.get("id")
        or payload.get("call_id")
        or message.get("id")
        or message.get("uuid")
        or nested_message.get("id")
    )
    timestamp = _safe_str(
        record.get("timestamp")
        or record.get("created_at")
        or record.get("createdAt")
        or payload.get("timestamp")
        or payload.get("created_at")
        or payload.get("createdAt")
        or message.get("timestamp")
        or message.get("created_at")
        or message.get("createdAt")
    )

    role = ""
    content: Any = None
    if source == "codex":
        role = _safe_str(payload.get("role") or record.get("role") or nested_message.get("role"))
        content = payload.get("content") if "content" in payload else record.get("content")
        if content is None and nested_message:
            content = nested_message.get("content")
        if content is None:
            content = payload.get("output") or payload.get("text") or record.get("text")
        if not role and native_type in {"function_call_output", "tool_result"}:
            role = "tool"
        if not role and native_type in {"user_message", "input_message"}:
            role = "user"
    elif source == "claude_code_cli":
        role = _safe_str(message.get("role") or record.get("role") or record.get("type"))
        content = message.get("content") if "content" in message else record.get("content")
        if role == "user" and isinstance(content, list) and content and all(
            isinstance(item, dict) and _safe_str(item.get("type")) == "tool_result"
            for item in content
        ):
            role = "tool"
    else:
        role = _safe_str(record.get("role") or message.get("role") or payload.get("role"))
        content = record.get("content")
        if content is None:
            content = message.get("content")
        if content is None:
            content = payload.get("content")
        if content is None:
            content = record.get("text") or payload.get("text") or message.get("text")

    role = role.lower().strip()
    if role == "human":
        role = "user"
    elif role in {"ai", "model"}:
        role = "assistant"
    text = _text_from_content(content).strip()
    if not role and not text:
        return None
    if not text:
        return None
    return {
        "role": role or "unknown",
        "content": text,
        "native_type": native_type,
        "native_id": native_id,
        "timestamp": timestamp,
    }


def _jsonl_record_canonical_messages(source_system: str, record: dict[str, Any]) -> list[dict[str, Any]]:
    source = _safe_str(source_system)
    if source == "openclaw":
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        messages = data.get("messagesSnapshot")
        if not isinstance(messages, list):
            messages = record.get("messages")
        extracted: list[dict[str, Any]] = []
        if isinstance(messages, list):
            base_type = _safe_str(record.get("type") or "openclaw_message_snapshot")
            base_id = _safe_str(record.get("id") or record.get("uuid") or record.get("sessionId"))
            base_timestamp = _safe_str(record.get("timestamp") or data.get("timestamp"))
            for index, message in enumerate(messages):
                if not isinstance(message, dict):
                    continue
                role = _safe_str(message.get("role") or message.get("type")).lower()
                if role == "human":
                    role = "user"
                elif role in {"ai", "model"}:
                    role = "assistant"
                if role == "custom":
                    continue
                content = _text_from_content(message.get("content")).strip()
                if not role or not content:
                    continue
                native_id = _safe_str(
                    message.get("id")
                    or message.get("uuid")
                    or message.get("messageId")
                    or f"{base_id or 'openclaw'}:{index}"
                )
                extracted.append({
                    "role": role,
                    "content": content,
                    "native_type": base_type,
                    "native_id": native_id,
                    "timestamp": _safe_str(message.get("timestamp") or message.get("createdAt") or base_timestamp),
                    "message_index_in_record": index,
                })
        if extracted:
            return extracted

    single = _jsonl_record_role_text(source_system, record)
    return [single] if single else []


def _stream_jsonl_canonical_entries(
    path: str | Path,
    *,
    source_system: str,
    file_side: str,
    max_json_line_bytes: int,
    start_offset: int = 0,
    start_line_no: int = 0,
) -> dict[str, Any]:
    raw_path = Path(path).expanduser()
    messages: list[dict[str, Any]] = []
    line_health: list[dict[str, Any]] = []
    try:
        stat = raw_path.stat()
    except OSError as exc:
        return {
            "exists": False,
            "path": str(raw_path),
            "messages": messages,
            "line_health": [{
                "file_side": file_side,
                "line_no": 0,
                "offset_start": 0,
                "offset_end": 0,
                "bytes": 0,
                "health_status": "missing_file",
                "error": str(exc),
            }],
            "line_count": 0,
            "bad_json_line_count": 0,
            "oversized_line_count": 0,
            "size_bytes": 0,
            "mtime": "",
        }
    start_offset = max(0, int(start_offset or 0))
    line_no = max(0, int(start_line_no or 0))
    bad_json_line_count = 0
    oversized_line_count = 0
    offset = start_offset
    try:
        with raw_path.open("rb") as handle:
            if start_offset:
                handle.seek(start_offset)
            while True:
                start = offset
                raw_line = handle.readline()
                if not raw_line:
                    break
                offset += len(raw_line)
                if not raw_line.strip():
                    continue
                line_no += 1
                end = offset
                line_bytes = len(raw_line)
                if line_bytes > max_json_line_bytes:
                    oversized_line_count += 1
                    line_health.append({
                        "file_side": file_side,
                        "line_no": line_no,
                        "offset_start": start,
                        "offset_end": end,
                        "bytes": line_bytes,
                        "health_status": "oversized_json_line_skipped",
                        "error": f"line exceeds {max_json_line_bytes} byte canonical index parse limit",
                    })
                    continue
                try:
                    decoded = raw_line.decode("utf-8")
                    record = json.loads(decoded)
                except Exception as exc:
                    bad_json_line_count += 1
                    line_health.append({
                        "file_side": file_side,
                        "line_no": line_no,
                        "offset_start": start,
                        "offset_end": end,
                        "bytes": line_bytes,
                        "health_status": "bad_json_line",
                        "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                    })
                    continue
                if not isinstance(record, dict):
                    continue
                extracted_messages = _jsonl_record_canonical_messages(source_system, record)
                if not extracted_messages:
                    continue
                line_hash = hashlib.sha256(raw_line).hexdigest()
                for extracted in extracted_messages:
                    content = extracted["content"]
                    messages.append({
                        "file_side": file_side,
                        "line_no": line_no,
                        "message_index_in_record": int(extracted.get("message_index_in_record", 0) or 0),
                        "offset_start": start,
                        "offset_end": end,
                        "line_bytes": line_bytes,
                        "line_hash": line_hash,
                        "role": extracted["role"],
                        "content": content,
                        "content_chars": len(content),
                        "content_hash": _sha256_text(content),
                        "native_type": extracted["native_type"],
                        "native_id": extracted["native_id"],
                        "timestamp": extracted["timestamp"],
                        "record_preview": content[:500],
                    })
    except OSError as exc:
        line_health.append({
            "file_side": file_side,
            "line_no": line_no,
            "offset_start": offset,
            "offset_end": offset,
            "bytes": 0,
            "health_status": "read_error",
            "error": str(exc),
        })
    return {
        "exists": True,
        "path": str(raw_path),
        "messages": messages,
        "line_health": line_health,
        "line_count": line_no,
        "bad_json_line_count": bad_json_line_count,
        "oversized_line_count": oversized_line_count,
        "size_bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_offset": start_offset,
        "start_line_no": start_line_no,
    }


def _raw_message_matches(raw_messages: list[dict[str, Any]]) -> tuple[dict[tuple[int, int, str, str], dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    by_line: dict[tuple[int, int, str, str], dict[str, Any]] = {}
    by_hash: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for msg in raw_messages:
        line_key = (
            int(msg.get("line_no", 0) or 0),
            int(msg.get("message_index_in_record", 0) or 0),
            _safe_str(msg.get("role")),
            _safe_str(msg.get("content_hash")),
        )
        by_line.setdefault(line_key, msg)
        hash_key = (_safe_str(msg.get("role")), _safe_str(msg.get("content_hash")))
        by_hash.setdefault(hash_key, []).append(msg)
    return by_line, by_hash


def _chunks_for_message(message: dict[str, Any], *, chunk_chars: int) -> list[dict[str, Any]]:
    text = _safe_str(message.get("content"))
    if not text:
        return []
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_chars)
        chunk_text = text[start:end]
        source_start = int(message.get("source_offset_start", 0) or 0)
        raw_start = message.get("raw_offset_start")
        chunk = {
            "chunk_index": len(chunks),
            "chunk_start_char": start,
            "chunk_end_char": end,
            "source_offset_start": source_start,
            "source_offset_end": int(message.get("source_offset_end", 0) or 0),
            "raw_offset_start": int(raw_start) if raw_start is not None else None,
            "raw_offset_end": int(message.get("raw_offset_end")) if message.get("raw_offset_end") is not None else None,
            "content_hash": _sha256_text(chunk_text),
            "chunk_text": chunk_text,
        }
        chunks.append(chunk)
        start = end
    return chunks


def _repair_missing_raw_offsets_for_record(
    conn: sqlite3.Connection,
    *,
    record_id: str,
    source_system: str,
    session_id: str,
    raw_path: str,
    chunk_chars: int,
    updated_at: str,
    max_json_line_bytes: int,
) -> int:
    if not raw_path:
        return 0
    missing_rows = conn.execute(
        """
        select message_id, role, content_hash, line_no, source_offset_start,
               source_offset_end, payload_json
        from canonical_messages
        where record_id=? and raw_available=0
        order by line_no
        """,
        (record_id,),
    ).fetchall()
    if not missing_rows:
        return 0
    min_line_no = min(int(row[3] or 0) for row in missing_rows)
    start_line_no = max(0, min_line_no - 1)
    start_offset = min(max(0, int(row[4] or 0)) for row in missing_rows)
    raw_entries = _stream_jsonl_canonical_entries(
        raw_path,
        source_system=source_system,
        file_side="raw",
        max_json_line_bytes=max_json_line_bytes,
        start_offset=start_offset,
        start_line_no=start_line_no,
    )
    raw_by_line, raw_by_hash = _raw_message_matches(raw_entries.get("messages", []))
    repaired = 0
    for row in missing_rows:
        message_id = _safe_str(row[0])
        role = _safe_str(row[1])
        content_hash = _safe_str(row[2])
        line_no = int(row[3] or 0)
        raw_match = raw_by_line.get((line_no, 0, role, content_hash))
        if raw_match is None:
            candidates = raw_by_hash.get((role, content_hash), [])
            raw_match = candidates.pop(0) if candidates else None
        if raw_match is None:
            continue
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(row[6] or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        source_line = payload.get("source_line") if isinstance(payload.get("source_line"), dict) else {}
        payload["raw_line"] = raw_match
        raw_offset_start = int(raw_match.get("offset_start", 0) or 0)
        raw_offset_end = int(raw_match.get("offset_end", 0) or 0)
        conn.execute(
            """
            update canonical_messages
            set raw_line_no=?, raw_offset_start=?, raw_offset_end=?,
                raw_available=1, updated_at=?, payload_json=?
            where message_id=?
            """,
            (
                int(raw_match.get("line_no", 0) or 0),
                raw_offset_start,
                raw_offset_end,
                updated_at,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                message_id,
            ),
        )
        source_offset_start = int(row[4] or 0)
        source_offset_end = int(row[5] or 0)
        if source_line:
            message_for_chunks = {
                **source_line,
                "source_offset_start": source_offset_start,
                "source_offset_end": source_offset_end,
                "raw_offset_start": raw_offset_start,
                "raw_offset_end": raw_offset_end,
            }
            for chunk in _chunks_for_message(message_for_chunks, chunk_chars=chunk_chars):
                chunk_index = int(chunk.get("chunk_index", 0) or 0)
                conn.execute(
                    """
                    update canonical_chunks
                    set raw_offset_start=?, raw_offset_end=?, updated_at=?
                    where message_id=? and chunk_index=?
                    """,
                    (
                        chunk.get("raw_offset_start"),
                        chunk.get("raw_offset_end"),
                        updated_at,
                        message_id,
                        chunk_index,
                    ),
                )
        repaired += 1
    return repaired


def _canonical_index_record(conn: sqlite3.Connection, item: dict[str, Any], *, updated_at: str) -> dict[str, Any]:
    item = _normalize_record_identity(item)
    source_system = _safe_str(item.get("source_system"))
    record_id = _record_id(item)
    if source_system not in CANONICAL_MESSAGE_INDEX_SOURCE_SYSTEMS:
        return {
            "record_id": record_id,
            "source_system": source_system,
            "sessions_indexed": 0,
            "messages_indexed": 0,
            "chunks_indexed": 0,
            "skipped": "source_system_not_enabled_for_message_index",
        }

    raw_path = _safe_str(item.get("raw_path"))
    source_path = _safe_str(item.get("source_path"))
    if source_system in CANONICAL_MESSAGE_RAW_AS_SOURCE_SYSTEMS and raw_path:
        # Some native sources are SQLite, LevelDB/log evidence, or structured
        # JSON. Once the authorized collector exports a raw JSONL transcript,
        # use that transcript as the canonical message body while the records
        # table still keeps the native source_path for provenance.
        source_path = raw_path
    elif not source_path:
        source_path = raw_path
    previous = conn.execute(
        """
        select source_size_bytes, raw_size_bytes, source_line_count,
               raw_line_count, indexed_message_count, indexed_chunk_count,
               raw_indexed_message_count, raw_offset_coverage_count,
               bad_json_line_count, oversized_line_count
        from canonical_sessions
        where record_id=?
        """,
        (record_id,),
    ).fetchone()
    try:
        source_size = Path(source_path).expanduser().stat().st_size if source_path else 0
    except OSError:
        source_size = 0
    try:
        raw_size = Path(raw_path).expanduser().stat().st_size if raw_path else 0
    except OSError:
        raw_size = 0
    append_only = False
    source_start_offset = 0
    raw_start_offset = 0
    source_start_line_no = 0
    raw_start_line_no = 0
    previous_counts = {
        "indexed_message_count": 0,
        "indexed_chunk_count": 0,
        "raw_indexed_message_count": 0,
        "raw_offset_coverage_count": 0,
        "bad_json_line_count": 0,
        "oversized_line_count": 0,
    }
    if previous is not None:
        prev_source_size = int(previous[0] or 0)
        prev_raw_size = int(previous[1] or 0)
        if (
            source_size >= prev_source_size > 0
            and (not raw_path or raw_size >= prev_raw_size > 0)
        ):
            append_only = True
            source_start_offset = prev_source_size
            raw_start_offset = prev_raw_size if raw_path else 0
            source_start_line_no = int(previous[2] or 0)
            raw_start_line_no = int(previous[3] or 0)
            previous_counts = {
                "indexed_message_count": int(previous[4] or 0),
                "indexed_chunk_count": int(previous[5] or 0),
                "raw_indexed_message_count": int(previous[6] or 0),
                "raw_offset_coverage_count": int(previous[7] or 0),
                "bad_json_line_count": int(previous[8] or 0),
                "oversized_line_count": int(previous[9] or 0),
            }
    source_entries = _stream_jsonl_canonical_entries(
        source_path,
        source_system=source_system,
        file_side="source",
        max_json_line_bytes=_canonical_index_max_json_line_bytes(),
        start_offset=source_start_offset,
        start_line_no=source_start_line_no,
    )
    raw_entries = _stream_jsonl_canonical_entries(
        raw_path,
        source_system=source_system,
        file_side="raw",
        max_json_line_bytes=_canonical_index_max_json_line_bytes(),
        start_offset=raw_start_offset,
        start_line_no=raw_start_line_no,
    ) if raw_path else {
        "exists": False,
        "messages": [],
        "line_health": [],
        "line_count": 0,
        "bad_json_line_count": 0,
        "oversized_line_count": 0,
        "size_bytes": 0,
        "mtime": "",
    }

    if not append_only:
        conn.execute("delete from canonical_chunks where record_id=?", (record_id,))
        conn.execute("delete from canonical_messages where record_id=?", (record_id,))
        conn.execute("delete from canonical_line_health where record_id=?", (record_id,))

    raw_by_line, raw_by_hash = _raw_message_matches(raw_entries.get("messages", []))
    raw_offset_coverage_count = 0
    new_raw_offset_coverage_count = 0
    chunk_count = 0
    chunk_chars = _canonical_index_chunk_chars()
    session_id = _safe_str(item.get("session_id"))
    canonical_window_id = _safe_str(item.get("canonical_window_id"))
    project_id = _safe_str(item.get("project_id"))
    project_root = _safe_str(item.get("project_root"))

    for idx, source_msg in enumerate(source_entries.get("messages", [])):
        raw_match = raw_by_line.get((
            int(source_msg.get("line_no", 0) or 0),
            int(source_msg.get("message_index_in_record", 0) or 0),
            _safe_str(source_msg.get("role")),
            _safe_str(source_msg.get("content_hash")),
        ))
        if raw_match is None:
            candidates = raw_by_hash.get((
                _safe_str(source_msg.get("role")),
                _safe_str(source_msg.get("content_hash")),
            ), [])
            raw_match = candidates.pop(0) if candidates else None
        raw_available = raw_match is not None
        if raw_available:
            raw_offset_coverage_count += 1
            new_raw_offset_coverage_count += 1
        basis = "|".join([
            record_id,
            str(source_msg.get("line_no", "")),
            str(source_msg.get("message_index_in_record", "")),
            _safe_str(source_msg.get("role")),
            _safe_str(source_msg.get("native_id")),
            _safe_str(source_msg.get("content_hash")),
        ])
        message_id = hashlib.sha256(basis.encode("utf-8")).hexdigest()
        content = _safe_str(source_msg.get("content"))
        preview = " ".join(content[:240].split())
        message_payload = {
            "source_line": source_msg,
            "raw_line": raw_match,
        }
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_chars, content_hash,
                line_hash, content_preview, raw_available, updated_at, payload_json
            ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(message_id) do update set
                raw_line_no=excluded.raw_line_no,
                raw_offset_start=excluded.raw_offset_start,
                raw_offset_end=excluded.raw_offset_end,
                raw_available=excluded.raw_available,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (
                message_id,
                record_id,
                source_system,
                session_id,
                canonical_window_id,
                project_id,
                project_root,
                source_path,
                raw_path,
                source_msg.get("role", ""),
                source_msg.get("native_type", ""),
                source_msg.get("native_id", ""),
                source_msg.get("timestamp", ""),
                int(source_msg.get("line_no", 0) or 0),
                int(raw_match.get("line_no", 0) or 0) if raw_match else None,
                int(source_msg.get("offset_start", 0) or 0),
                int(source_msg.get("offset_end", 0) or 0),
                int(raw_match.get("offset_start", 0) or 0) if raw_match else None,
                int(raw_match.get("offset_end", 0) or 0) if raw_match else None,
                int(source_msg.get("content_chars", 0) or 0),
                source_msg.get("content_hash", ""),
                source_msg.get("line_hash", ""),
                preview,
                1 if raw_available else 0,
                updated_at,
                json.dumps(message_payload, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        message_for_chunks = {
            **source_msg,
            "source_offset_start": int(source_msg.get("offset_start", 0) or 0),
            "source_offset_end": int(source_msg.get("offset_end", 0) or 0),
            "raw_offset_start": int(raw_match.get("offset_start", 0) or 0) if raw_match else None,
            "raw_offset_end": int(raw_match.get("offset_end", 0) or 0) if raw_match else None,
        }
        conn.execute("delete from canonical_chunks where message_id=?", (message_id,))
        for chunk in _chunks_for_message(message_for_chunks, chunk_chars=chunk_chars):
            chunk_basis = f"{message_id}|{chunk['chunk_index']}|{chunk['content_hash']}"
            chunk_id = hashlib.sha256(chunk_basis.encode("utf-8")).hexdigest()
            conn.execute(
                """
                insert into canonical_chunks (
                    chunk_id, message_id, record_id, source_system, session_id,
                    canonical_window_id, role, chunk_index, chunk_start_char,
                    chunk_end_char, source_offset_start, source_offset_end,
                    raw_offset_start, raw_offset_end, content_hash, chunk_text,
                    updated_at
                ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    chunk_id,
                    message_id,
                    record_id,
                    source_system,
                    session_id,
                    canonical_window_id,
                    source_msg.get("role", ""),
                    int(chunk.get("chunk_index", 0) or 0),
                    int(chunk.get("chunk_start_char", 0) or 0),
                    int(chunk.get("chunk_end_char", 0) or 0),
                    int(chunk.get("source_offset_start", 0) or 0),
                    int(chunk.get("source_offset_end", 0) or 0),
                    chunk.get("raw_offset_start"),
                    chunk.get("raw_offset_end"),
                    chunk.get("content_hash", ""),
                    chunk.get("chunk_text", ""),
                    updated_at,
                ),
            )
            chunk_count += 1

    raw_offset_repairs_count = 0
    if append_only:
        raw_offset_repairs_count = _repair_missing_raw_offsets_for_record(
            conn,
            record_id=record_id,
            source_system=source_system,
            session_id=session_id,
            raw_path=raw_path,
            chunk_chars=chunk_chars,
            updated_at=updated_at,
            max_json_line_bytes=_canonical_index_max_json_line_bytes(),
        )

    for side_entries in (source_entries, raw_entries):
        for health in side_entries.get("line_health", []):
            line_health_id = hashlib.sha256(
                "|".join([
                    record_id,
                    _safe_str(health.get("file_side")),
                    str(health.get("line_no", "")),
                    str(health.get("offset_start", "")),
                    _safe_str(health.get("health_status")),
                    _safe_str(health.get("error")),
                ]).encode("utf-8")
            ).hexdigest()
            conn.execute(
                """
                insert into canonical_line_health (
                    line_health_id, record_id, source_system, session_id,
                    source_path, file_side, line_no, offset_start, offset_end,
                    bytes, health_status, error, updated_at
                ) values (?,?,?,?,?,?,?,?,?,?,?,?,?)
                on conflict(line_health_id) do update set
                    bytes=excluded.bytes,
                    health_status=excluded.health_status,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    line_health_id,
                    record_id,
                    source_system,
                    session_id,
                    source_path if health.get("file_side") == "source" else raw_path,
                    health.get("file_side", ""),
                    int(health.get("line_no", 0) or 0),
                    int(health.get("offset_start", 0) or 0),
                    int(health.get("offset_end", 0) or 0),
                    int(health.get("bytes", 0) or 0),
                    health.get("health_status", ""),
                    health.get("error", ""),
                    updated_at,
                ),
            )

    new_message_count = len(source_entries.get("messages", []))
    new_raw_message_count = len(raw_entries.get("messages", []))
    new_bad_count = int(source_entries.get("bad_json_line_count", 0) or 0) + int(raw_entries.get("bad_json_line_count", 0) or 0)
    new_oversized_count = int(source_entries.get("oversized_line_count", 0) or 0) + int(raw_entries.get("oversized_line_count", 0) or 0)
    new_chunk_count = chunk_count
    if append_only:
        message_count = previous_counts["indexed_message_count"] + new_message_count
        raw_message_count = previous_counts["raw_indexed_message_count"] + new_raw_message_count
        raw_offset_coverage_count = previous_counts["raw_offset_coverage_count"] + raw_offset_coverage_count + raw_offset_repairs_count
        chunk_count = previous_counts["indexed_chunk_count"] + chunk_count
        bad_count = previous_counts["bad_json_line_count"] + new_bad_count
        oversized_count = previous_counts["oversized_line_count"] + new_oversized_count
    else:
        message_count = new_message_count
        raw_message_count = new_raw_message_count
        bad_count = new_bad_count
        oversized_count = new_oversized_count
    if not source_entries.get("exists"):
        index_status = "source_missing"
    elif message_count == 0:
        index_status = "no_indexable_messages"
    elif not raw_entries.get("exists"):
        index_status = "raw_missing"
    elif raw_offset_coverage_count == message_count:
        index_status = "raw_offsets_complete"
    else:
        index_status = "raw_offsets_partial"
    session_payload = {
        "guardian_record": item,
        "chunk_chars": chunk_chars,
        "source_entries": {
            key: value for key, value in source_entries.items()
            if key not in {"messages", "line_health"}
        },
        "raw_entries": {
            key: value for key, value in raw_entries.items()
            if key not in {"messages", "line_health"}
        },
        "incremental": {
            "append_only": append_only,
            "source_start_offset": source_start_offset,
            "raw_start_offset": raw_start_offset,
            "new_messages_indexed": new_message_count,
            "new_raw_messages_indexed": new_raw_message_count,
            "raw_offset_repairs_count": raw_offset_repairs_count,
        },
    }
    conn.execute(
        """
        insert into canonical_sessions (
            record_id, source_system, session_id, raw_artifact_id,
            canonical_window_id, project_id, project_root, thread_name,
            source_path, raw_path, source_mtime, raw_mtime,
            source_size_bytes, raw_size_bytes, source_line_count, raw_line_count,
            indexed_message_count, indexed_chunk_count, raw_indexed_message_count,
            raw_offset_coverage_count, bad_json_line_count, oversized_line_count,
            index_status, updated_at, payload_json
        ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        on conflict(record_id) do update set
            source_mtime=excluded.source_mtime,
            raw_mtime=excluded.raw_mtime,
            source_size_bytes=excluded.source_size_bytes,
            raw_size_bytes=excluded.raw_size_bytes,
            source_line_count=excluded.source_line_count,
            raw_line_count=excluded.raw_line_count,
            indexed_message_count=excluded.indexed_message_count,
            indexed_chunk_count=excluded.indexed_chunk_count,
            raw_indexed_message_count=excluded.raw_indexed_message_count,
            raw_offset_coverage_count=excluded.raw_offset_coverage_count,
            bad_json_line_count=excluded.bad_json_line_count,
            oversized_line_count=excluded.oversized_line_count,
            index_status=excluded.index_status,
            updated_at=excluded.updated_at,
            payload_json=excluded.payload_json
        """,
        (
            record_id,
            source_system,
            session_id,
            item.get("raw_artifact_id", ""),
            canonical_window_id,
            project_id,
            project_root,
            item.get("thread_name", ""),
            source_path,
            raw_path,
            source_entries.get("mtime", ""),
            raw_entries.get("mtime", ""),
            int(source_entries.get("size_bytes", 0) or 0),
            int(raw_entries.get("size_bytes", 0) or 0),
            int(source_entries.get("line_count", 0) or 0),
            int(raw_entries.get("line_count", 0) or 0),
            message_count,
            chunk_count,
            raw_message_count,
            raw_offset_coverage_count,
            bad_count,
            oversized_count,
            index_status,
            updated_at,
            json.dumps(session_payload, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    return {
        "record_id": record_id,
        "source_system": source_system,
        "session_id": session_id,
        "index_status": index_status,
        "sessions_indexed": 1,
        "messages_indexed": message_count,
        "chunks_indexed": chunk_count,
        "raw_indexed_messages": raw_message_count,
        "raw_offset_coverage_count": raw_offset_coverage_count,
        "bad_json_line_count": bad_count,
        "oversized_line_count": oversized_count,
        "append_only": append_only,
        "new_messages_indexed": new_message_count,
        "new_chunks_indexed": new_chunk_count,
        "new_raw_offset_coverage_count": new_raw_offset_coverage_count,
        "raw_offset_repairs_count": raw_offset_repairs_count,
    }


def _upsert_origin_event(
    conn: sqlite3.Connection,
    *,
    record_id: str,
    item: dict[str, Any],
    updated_at: str,
) -> int:
    event = item.get("origin_event") if isinstance(item.get("origin_event"), dict) else {}
    if not event or not event.get("origin_id"):
        return 0
    refs = event.get("source_refs") if isinstance(event.get("source_refs"), dict) else {}
    conn.execute(
        """
        insert into origin_events (
            origin_id, record_id, origin_contract, origin_event_contract,
            time_river_contract, origin_layer, origin_status, origin_label,
            origin_seen, source_system, computer_id, native_session_key,
            session_id, canonical_window_id, source_path, raw_path,
            event_time, captured_at, audit_time, content_hash, byte_offset,
            line_no, source_refs_json, payload_json, updated_at
        ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        on conflict(origin_id) do update set
            origin_status=excluded.origin_status,
            origin_label=excluded.origin_label,
            origin_seen=excluded.origin_seen,
            source_path=excluded.source_path,
            raw_path=excluded.raw_path,
            event_time=excluded.event_time,
            captured_at=excluded.captured_at,
            audit_time=excluded.audit_time,
            content_hash=excluded.content_hash,
            source_refs_json=excluded.source_refs_json,
            payload_json=excluded.payload_json,
            updated_at=excluded.updated_at
        """,
        (
            event.get("origin_id", ""),
            record_id,
            event.get("origin_contract", ""),
            event.get("contract", ""),
            event.get("time_river_contract", ""),
            event.get("origin_layer", ""),
            event.get("origin_status", ""),
            event.get("origin_label", ""),
            1 if event.get("origin_seen") else 0,
            event.get("source_system", ""),
            event.get("computer_id", ""),
            event.get("native_session_key", ""),
            refs.get("session_id", item.get("session_id", "")),
            refs.get("canonical_window_id", item.get("canonical_window_id", "")),
            event.get("source_path", ""),
            event.get("raw_path", ""),
            event.get("event_time", ""),
            event.get("captured_at", ""),
            event.get("audit_time", ""),
            event.get("content_hash", ""),
            event.get("byte_offset"),
            event.get("line_no"),
            json.dumps(refs, ensure_ascii=False, separators=(",", ":")),
            json.dumps(event, ensure_ascii=False, separators=(",", ":")),
            updated_at,
        ),
    )
    return 1


def _update_records_index_once(report: dict[str, Any], db_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(db_path).expanduser() if db_path else records_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect_records_db(path)
    try:
        _ensure_index_schema(conn)
        identity_drift_repairs = _repair_session_window_identity_drift(conn)
        changed = 0
        canonical_session_upserts = 0
        canonical_message_upserts = 0
        canonical_chunk_upserts = 0
        canonical_raw_offset_coverage = 0
        origin_event_upserts = 0
        canonical_results: list[dict[str, Any]] = []
        for item in report.get("records", []):
            if not isinstance(item, dict) or not (item.get("source_path") or item.get("raw_path")):
                continue
            item = _normalize_record_identity(item)
            source_scan = item.get("source_scan") if isinstance(item.get("source_scan"), dict) else {}
            raw_scan = item.get("raw_scan") if isinstance(item.get("raw_scan"), dict) else {}
            record_id = _record_id(item)
            conn.execute(
                """
                insert into records (
                    record_id, source_system, session_id, raw_artifact_id,
                    canonical_window_id, project_id, source_path, raw_path,
                    source_mtime, raw_mtime, source_size_bytes, raw_size_bytes,
                    user_turn_count, assistant_turn_count, bad_json_line_count,
                    oversize_record_count, metadata_ok, has_user_and_assistant,
                    raw_current, recoverable_from_raw, guard_status, updated_at,
                    payload_json
                ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                on conflict(record_id) do update set
                    source_mtime=excluded.source_mtime,
                    raw_mtime=excluded.raw_mtime,
                    source_size_bytes=excluded.source_size_bytes,
                    raw_size_bytes=excluded.raw_size_bytes,
                    user_turn_count=excluded.user_turn_count,
                    assistant_turn_count=excluded.assistant_turn_count,
                    bad_json_line_count=excluded.bad_json_line_count,
                    oversize_record_count=excluded.oversize_record_count,
                    metadata_ok=excluded.metadata_ok,
                    has_user_and_assistant=excluded.has_user_and_assistant,
                    raw_current=excluded.raw_current,
                    recoverable_from_raw=excluded.recoverable_from_raw,
                    guard_status=excluded.guard_status,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    record_id,
                    item.get("source_system", ""),
                    item.get("session_id", ""),
                    item.get("raw_artifact_id", ""),
                    item.get("canonical_window_id", ""),
                    item.get("project_id", ""),
                    item.get("source_path", ""),
                    item.get("raw_path", ""),
                    source_scan.get("mtime", ""),
                    raw_scan.get("mtime", ""),
                    int(source_scan.get("size_bytes", 0) or 0),
                    int(raw_scan.get("size_bytes", 0) or 0),
                    int(source_scan.get("user_turn_count", 0) or 0),
                    int(source_scan.get("assistant_turn_count", 0) or 0),
                    int(source_scan.get("bad_json_line_count", 0) or 0),
                    int(source_scan.get("oversize_record_count", 0) or 0),
                    1 if source_scan.get("metadata_ok") else 0,
                    1 if source_scan.get("has_user_and_assistant") else 0,
                    1 if item.get("raw_current") else 0,
                    1 if item.get("recoverable_from_raw") else 0,
                    item.get("guard_status", ""),
                    ts(),
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            changed += 1
            updated_at = ts()
            origin_event_upserts += _upsert_origin_event(
                conn,
                record_id=record_id,
                item=item,
                updated_at=updated_at,
            )
            canonical_result = _canonical_index_record(conn, item, updated_at=updated_at)
            canonical_results.append(canonical_result)
            canonical_session_upserts += int(canonical_result.get("sessions_indexed", 0) or 0)
            canonical_message_upserts += int(canonical_result.get("new_messages_indexed", canonical_result.get("messages_indexed", 0)) or 0)
            canonical_chunk_upserts += int(canonical_result.get("new_chunks_indexed", canonical_result.get("chunks_indexed", 0)) or 0)
            if canonical_result.get("append_only"):
                canonical_raw_offset_coverage += (
                    int(canonical_result.get("new_raw_offset_coverage_count", 0) or 0)
                    + int(canonical_result.get("raw_offset_repairs_count", 0) or 0)
                )
            else:
                canonical_raw_offset_coverage += int(canonical_result.get("raw_offset_coverage_count", 0) or 0)
        conn.commit()
        total = conn.execute("select count(*) from records").fetchone()[0]
        canonical_sessions_total = conn.execute("select count(*) from canonical_sessions").fetchone()[0]
        canonical_messages_total = conn.execute("select count(*) from canonical_messages").fetchone()[0]
        canonical_chunks_total = conn.execute("select count(*) from canonical_chunks").fetchone()[0]
        origin_events_total = conn.execute("select count(*) from origin_events").fetchone()[0]
    finally:
        conn.close()
    return {
        "ok": True,
        "contract": CANONICAL_RECORD_INDEX_CONTRACT,
        "db_path": str(path),
        "db_path_label": _public_path_label(path),
        "records_upserted": changed,
        "records_total": total,
        "canonical_sessions_upserted": canonical_session_upserts,
        "canonical_messages_upserted": canonical_message_upserts,
        "canonical_chunks_upserted": canonical_chunk_upserts,
        "canonical_raw_offset_coverage_count": canonical_raw_offset_coverage,
        "origin_events_upserted": origin_event_upserts,
        "identity_drift_repairs": identity_drift_repairs,
        "canonical_sessions_total": canonical_sessions_total,
        "canonical_messages_total": canonical_messages_total,
        "canonical_chunks_total": canonical_chunks_total,
        "origin_events_total": origin_events_total,
        "canonical_results": canonical_results,
        "write_performed": True,
    }


def update_records_index(report: dict[str, Any], db_path: str | Path | None = None) -> dict[str, Any]:
    attempts = int(os.environ.get("MEMCORE_RECORDS_DB_WRITE_ATTEMPTS", "4") or "4")
    attempts = max(1, min(attempts, 10))
    last_error = ""
    for attempt in range(attempts):
        try:
            result = _update_records_index_once(report, db_path=db_path)
            if attempt:
                result["retry_attempts"] = attempt
            return result
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_locked(exc) or attempt == attempts - 1:
                raise
            last_error = str(exc)
            time.sleep(0.15 * (attempt + 1))
    return {
        "ok": False,
        "contract": CANONICAL_RECORD_INDEX_CONTRACT,
        "error": "records_db_locked",
        "last_error": last_error,
        "write_performed": False,
    }


def query_records_index(
    *,
    source_system: str = "",
    session_id: str = "",
    query: str = "",
    limit: int = 20,
    db_path: str | Path | None = None,
    public: bool = True,
) -> dict[str, Any]:
    path = Path(db_path).expanduser() if db_path else records_db_path()
    if not path.exists():
        return {
            "ok": False,
            "contract": CANONICAL_RECORD_INDEX_CONTRACT,
            "db_path": str(path),
            "db_path_label": _public_path_label(path),
            "error": "records_db_missing",
            "sessions": [],
            "messages": [],
        }
    conn = _connect_records_db(path)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_index_schema(conn)
        where: list[str] = []
        params: list[Any] = []
        if source_system:
            where.append("source_system = ?")
            params.append(source_system)
        if session_id:
            where.append("session_id = ?")
            params.append(session_id)
        where_sql = (" where " + " and ".join(where)) if where else ""
        session_rows = conn.execute(
            f"""
            select record_id, source_system, session_id, canonical_window_id,
                   project_id, project_root, thread_name, source_path, raw_path,
                   source_mtime, raw_mtime, source_size_bytes, raw_size_bytes,
                   indexed_message_count, indexed_chunk_count,
                   raw_offset_coverage_count, bad_json_line_count,
                   oversized_line_count, index_status, updated_at
            from canonical_sessions
            {where_sql}
            order by source_mtime desc, updated_at desc
            limit ?
            """,
            (*params, max(1, min(int(limit or 20), 500))),
        ).fetchall()
        message_where = list(where)
        message_params = list(params)
        if query:
            message_where.append("content_preview like ?")
            message_params.append(f"%{query}%")
        message_where_sql = (" where " + " and ".join(message_where)) if message_where else ""
        message_rows = conn.execute(
            f"""
            select message_id, record_id, source_system, session_id,
                   canonical_window_id, project_id, project_root, source_path,
                   raw_path, role, native_type, native_id, timestamp, line_no,
                   raw_line_no, source_offset_start, source_offset_end,
                   raw_offset_start, raw_offset_end, content_chars, content_hash,
                   line_hash, content_preview, raw_available, updated_at
            from canonical_messages
            {message_where_sql}
            order by timestamp desc, line_no desc
            limit ?
            """,
            (*message_params, max(1, min(int(limit or 20), 500))),
        ).fetchall()
        origin_rows = conn.execute(
            f"""
            select origin_id, record_id, origin_contract, origin_event_contract,
                   time_river_contract, origin_layer, origin_status,
                   origin_label, origin_seen, source_system, computer_id,
                   native_session_key, session_id, canonical_window_id,
                   source_path, raw_path, event_time, captured_at, audit_time,
                   content_hash, byte_offset, line_no, updated_at
            from origin_events
            {where_sql}
            order by event_time desc, updated_at desc
            limit ?
            """,
            (*params, max(1, min(int(limit or 20), 500))),
        ).fetchall()
        totals = {
            "records": int(conn.execute("select count(*) from records").fetchone()[0] or 0),
            "canonical_sessions": int(conn.execute("select count(*) from canonical_sessions").fetchone()[0] or 0),
            "canonical_messages": int(conn.execute("select count(*) from canonical_messages").fetchone()[0] or 0),
            "canonical_chunks": int(conn.execute("select count(*) from canonical_chunks").fetchone()[0] or 0),
            "origin_events": int(conn.execute("select count(*) from origin_events").fetchone()[0] or 0),
        }
    finally:
        conn.close()

    def clean_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        if public:
            for key in ("source_path", "raw_path", "project_root"):
                if key in data:
                    data[f"{key}_label"] = _public_path_label(data.get(key, ""))
                    data.pop(key, None)
        return data

    return {
        "ok": True,
        "contract": CANONICAL_RECORD_INDEX_CONTRACT,
        "db_path": str(path),
        "db_path_label": _public_path_label(path),
        "read_only": True,
        "write_performed": False,
        "source_system": source_system,
        "session_id": session_id,
        "query": query,
        "totals": totals,
        "sessions": [clean_row(row) for row in session_rows],
        "messages": [clean_row(row) for row in message_rows],
        "origin_events": [clean_row(row) for row in origin_rows],
    }


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
) -> dict[str, Any]:
    scan_mode = "fast" if str(scan_mode or "").lower() in {"fast", "stat", "quick"} else "full"
    backfill_result: dict[str, Any] | None = None
    if auto_backfill:
        backfill_result = run_raw_backfill(limit=limit)

    records: list[dict[str, Any]] = []
    for source_system, module_name in GUARDED_CONNECTORS:
        records.extend(_connector_records(
            source_system,
            module_name,
            limit=limit,
            oversize_bytes=oversize_bytes,
            scan_mode=scan_mode,
        ))
    records.extend(_claude_desktop_authorized_raw_records(
        limit=limit,
        oversize_bytes=oversize_bytes,
        scan_mode=scan_mode,
    ))
    records.extend(_openclaw_records(
        limit=limit,
        oversize_bytes=oversize_bytes,
        scan_mode=scan_mode,
    ))
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
        report["index_update"] = update_records_index(report)
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
