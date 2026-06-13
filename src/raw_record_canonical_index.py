#!/usr/bin/env python3
"""Canonical record index for raw record guardian.

Tiandao contract: this module is the canonical index layer under the
Time River. It stores searchable, recoverable derivatives from guarded
source/raw records, but it is not the raw origin and does not decide
whether a source record is guarded.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from config_loader import get_memcore_root
except ImportError:  # pragma: no cover
    from src.config_loader import get_memcore_root

UTC = timezone.utc
CANONICAL_RECORD_INDEX_CONTRACT = "canonical_record_index.v2"
TIANDAO_CANONICAL_INDEX_CONTRACT = "tiandao_raw_record_canonical_index.v1"
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
DEFAULT_CANONICAL_INDEX_CHUNK_CHARS = 4096
DEFAULT_CANONICAL_INDEX_MAX_JSON_LINE_BYTES = 16 * 1024 * 1024


def get_raw_record_canonical_index_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": TIANDAO_CANONICAL_INDEX_CONTRACT,
        "index_contract": CANONICAL_RECORD_INDEX_CONTRACT,
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "index_layer": "canonical_record_index",
        "source_authority": "raw_record_guardian",
        "not_raw_origin": True,
        "read_only_by_default": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "raw_origin_policy": "raw/time origin remains the source of truth; canonical index stores searchable derivatives only",
    }


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize_public_text(text: str) -> str:
    legacy_relay_display = "".join(("CC", " Switch"))
    legacy_relay_token = "".join(("cc", "switch"))
    legacy_relay_dashed = "".join(("cc", "-switch"))
    legacy_relay_bundle = "".join(("com.", "cc", "switch"))
    replacements = {
        f"{legacy_relay_token}_claude_provider_projects_jsonl": "claude_projects_jsonl_desktop_entrypoint",
        legacy_relay_display: "Local Relay",
        legacy_relay_dashed: "local-relay",
        legacy_relay_token: "local_relay",
        legacy_relay_bundle: "local.relay",
    }
    result = str(text)
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


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
