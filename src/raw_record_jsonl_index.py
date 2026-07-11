#!/usr/bin/env python3
"""JSONL parsing and message chunking for the canonical raw-record index."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from src.source_system_runtime_declarations import source_system_canonical_index_kind
except ImportError:  # pragma: no cover
    from source_system_runtime_declarations import source_system_canonical_index_kind

UTC = timezone.utc


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


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
    canonical_kind = source_system_canonical_index_kind(source)
    if canonical_kind == "response_item_payload_message":
        native_type = _safe_str(payload.get("type") or record.get("type") or message.get("type"))
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
    elif canonical_kind == "message_envelope_content_blocks":
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
    if source_system_canonical_index_kind(source) == "message_snapshot_batch":
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
