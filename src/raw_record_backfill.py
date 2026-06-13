#!/usr/bin/env python3
"""Raw record backfill repair layer under Time Origin.

Tiandao contract: this module owns authorized raw backfill repair actions. It
may mirror source records into raw archives when explicitly invoked, but it is
not the raw origin and does not replace the guardian's read-only diagnostics.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from config_loader import node_id
except ImportError:  # pragma: no cover
    from src.config_loader import node_id

UTC = timezone.utc
RAW_BACKFILL_CONTRACT = "raw_record_backfill.v1"
RAW_RECORD_BACKFILL_REPAIR_CONTRACT = "tiandao_raw_record_backfill_repair.v1"
HERMES_STATE_DB_RAW_FORMAT = "hermes_state_db_messages_jsonl"
OPENCLAW_NATIVE_RAW_FORMAT = "openclaw_session_jsonl"


def _guardian_module():
    names = (
        ("src.raw_record_guardian", "raw_record_guardian")
        if __name__.startswith("src.")
        else ("raw_record_guardian", "src.raw_record_guardian")
    )
    last_error: Exception | None = None
    for name in names:
        try:
            return importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - fallback path
            last_error = exc
    if last_error:
        raise last_error
    raise ImportError("raw_record_guardian")


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_raw_record_backfill_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": RAW_RECORD_BACKFILL_REPAIR_CONTRACT,
        "backfill_contract": RAW_BACKFILL_CONTRACT,
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "repair_layer": "raw_record_backfill",
        "source_authority": "raw_record_guardian",
        "not_raw_origin": True,
        "read_only_by_default": True,
        "write_capable": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "authorization_required_for_write": True,
        "authorized_write_scopes": [
            "raw_archive_backfill",
            "raw_archive_meta_sidecar",
        ],
        "forbidden_write_scopes": [
            "source_platform_store",
            "platform_config",
            "memory_recall_summary",
        ],
        "raw_origin_policy": "backfill repairs raw archive continuity but never becomes Time Origin",
    }


def hermes_backfill_recommendation(*, limit: int = 80) -> dict[str, Any]:
    """Fast read-only check for Hermes sessions that still need raw export."""
    guardian = _guardian_module()
    records = guardian._hermes_records(
        limit=max(1, min(int(limit or 80), 200)),
        oversize_bytes=guardian.DEFAULT_JSONL_OVERSIZE_BYTES,
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

    guardian = _guardian_module()

    def file_hash(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    changed = 0
    items: list[dict[str, Any]] = []
    for artifact in guardian._openclaw_source_artifacts(limit):
        try:
            src = Path(str(artifact.get("source_path") or "")).expanduser()
            dest = guardian._openclaw_raw_path_for_artifact(artifact)
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


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


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
    guardian = _guardian_module()
    db_summary = guardian._hermes_state_db_summary()
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
                    raw_path = guardian._hermes_raw_paths_for_session(session_id)[0]
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
    guardian = _guardian_module()
    requested = set(source_systems or [])
    supported = {source_system for source_system, _ in guardian.GUARDED_CONNECTORS} | {"openclaw", "hermes"}
    results = []
    for source_system, module_name in guardian.GUARDED_CONNECTORS:
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


__all__ = [
    "RAW_BACKFILL_CONTRACT",
    "RAW_RECORD_BACKFILL_REPAIR_CONTRACT",
    "get_raw_record_backfill_contract",
    "hermes_backfill_recommendation",
    "_connector_backfill",
    "_openclaw_backfill",
    "_json_text_or_value",
    "_hermes_message_select_columns",
    "_hermes_read_session_messages",
    "_hermes_session_metadata",
    "_hermes_raw_record_from_message",
    "_write_jsonl_atomic",
    "_hermes_backfill",
    "run_raw_backfill",
]
