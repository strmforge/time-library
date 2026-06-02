#!/usr/bin/env python3
"""Raw-direct experience pool for memcore-cloud.

Reads directly from memory/<node>/<source_system>/<native_format>/*.jsonl without going through
recall index, experience layer, or Zhiyi-specific processing.

This module provides:
  - iter_raw_records: stream raw JSONL records from filesystem
  - query_raw_direct: scan + filter + query_hint substring match
  - build_raw_direct_pack: wrap results in standard contract

One Land, Different Flowers. This is the raw-direct service for all consumers.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Generator, Optional

from src.raw_text_decode import iter_decoded_jsonl_lines

UTC = timezone.utc

LEGACY_WINDOWS_RAW_ROOT = "Y:\\memory\\openclaw\\local"
MAX_LIMIT = 20
MAX_EXCERPT_CHARS = 800
DEFAULT_EXCERPT_CHARS = 400
MAX_FILES_SCANNED = 50
MAX_BYTES_SCANNED = 50 * 1024 * 1024  # 50 MB


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_evidence_hash(text: str) -> str:
    """SHA256[:16] for provenance tracking."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _default_raw_root() -> str:
    """Return the raw memory base root from the unified project config."""
    try:
        from src.config_loader import memory_root
    except ImportError:
        try:
            from config_loader import memory_root
        except ImportError:
            return "memory"
    return memory_root()


def _parse_role(record: dict) -> str:
    """Extract role from various OpenClaw/Codex JSONL formats."""
    msg = record.get("message", {})
    if isinstance(msg, dict):
        role = msg.get("role", "unknown")
        if role in ("user", "assistant", "system", "tool"):
            return role
    payload = record.get("payload", {})
    if isinstance(payload, dict):
        role = payload.get("role", "")
        if role in ("user", "assistant", "system", "tool", "developer"):
            return role
        if payload.get("type") == "user_message":
            return "user"
        if payload.get("type") == "agent_message":
            return "assistant"
    # batch format: {"messages": [{...}]}
    msgs = record.get("messages", [])
    if msgs and isinstance(msgs, list) and len(msgs) > 0:
        role = msgs[0].get("role", "unknown")
        if role in ("user", "assistant", "system", "tool"):
            return role
    return "unknown"


def _extract_content_text(record: dict) -> str:
    """Extract human-readable text content from various message formats."""
    payload = record.get("payload", {})
    if isinstance(payload, dict):
        ptype = payload.get("type")
        if ptype in ("user_message", "agent_message"):
            return str(payload.get("message") or "")
        if ptype == "message":
            content = payload.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = []
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text") or part.get("thinking") or ""
                        if text:
                            texts.append(str(text))
                return " ".join(texts)
    msg = record.get("message", {})
    if not isinstance(msg, dict):
        # try batch format
        msgs = record.get("messages", [])
        if isinstance(msgs, list) and msgs:
            msg = msgs[0]
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(part.get("text", ""))
        return " ".join(texts)
    return str(content) if content else ""


def iter_raw_records(
    raw_root: Optional[str] = None,
    source_system: str = "openclaw",
    computer_name: str = "local",
    canonical_window_id: str = "",
    session_id: str = "",
    max_files: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> Generator[dict, None, None]:
    """Stream raw JSONL records from the filesystem.
    Yields dicts with path and line info. Does NOT load entire files.
    Does NOT call recall index or import any Zhiyi module.
    """
    root = raw_root or _default_raw_root()
    if max_files is None:
        max_files = MAX_FILES_SCANNED
    if max_bytes is None:
        max_bytes = MAX_BYTES_SCANNED

    files_scanned = 0
    bytes_scanned = 0

    walk_roots = []
    current_root = os.path.join(root, computer_name, source_system)
    legacy_root = os.path.join(root, source_system, computer_name)
    if canonical_window_id:
        if os.path.isdir(current_root):
            for native_name in sorted(os.listdir(current_root)):
                candidate = os.path.join(current_root, native_name, canonical_window_id)
                if os.path.isdir(candidate):
                    walk_roots.append(candidate)
        walk_roots.append(os.path.join(legacy_root, canonical_window_id))
    else:
        walk_roots.extend([current_root, legacy_root])

    for walk_root in walk_roots:
        if not os.path.isdir(walk_root):
            continue
        for dirpath, dirnames, filenames in os.walk(walk_root):
            # Sort filenames for deterministic ordering
            for fname in sorted(filenames):
                if not fname.endswith(".jsonl"):
                    continue
                if fname.startswith(".meta.") or ".trajectory" in fname:
                    continue
                # Session filter at file level
                if session_id and session_id not in fname:
                    continue

                fpath = os.path.join(dirpath, fname)
                fsize = os.path.getsize(fpath)
                if bytes_scanned + fsize > max_bytes:
                    return

                try:
                    rel_parts = os.path.relpath(fpath, root).split(os.sep)
                    if len(rel_parts) >= 5:
                        comp = rel_parts[0]
                        src = rel_parts[1]
                        native_format = rel_parts[2]
                        window_id = rel_parts[3]
                        layout = "computer_first"
                    elif len(rel_parts) >= 4:
                        src = rel_parts[0]
                        comp = rel_parts[1]
                        native_format = ""
                        window_id = rel_parts[2]
                        layout = "legacy_source_first"
                    else:
                        comp = computer_name
                        src = source_system
                        native_format = ""
                        window_id = os.path.basename(dirpath)
                        layout = "unknown"
                    for line_no, (_, _, raw_line) in enumerate(iter_decoded_jsonl_lines(fpath), start=1):
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        record["_source_path"] = fpath
                        record["_source_fname"] = fname
                        record["_line_no"] = line_no
                        record["_source_system"] = src
                        record["_computer_name"] = comp
                        record["_native_artifact_format"] = native_format
                        record["_raw_archive_layout"] = layout
                        record["_canonical_window_id"] = window_id
                        yield record
                except (IOError, OSError):
                    continue

                files_scanned += 1
                bytes_scanned += fsize
                if files_scanned >= max_files:
                    return


def query_raw_direct(
    query_hint: str = "",
    source_system: str = "openclaw",
    computer_name: str = "local",
    canonical_window_id: str = "",
    session_id: str = "",
    consumer: str = "unknown",
    limit: int = 5,
    excerpt_chars: int = 400,
    raw_root: Optional[str] = None,
    max_files: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> list[dict]:
    """Scan raw land, filter, match query_hint, return bounded items."""
    clamped_limit = min(max(limit, 1), MAX_LIMIT)
    clamped_excerpt = min(max(excerpt_chars, 50), MAX_EXCERPT_CHARS)

    result = []
    hint = query_hint.lower().strip() if query_hint else ""

    for record in iter_raw_records(raw_root, source_system, computer_name,
                                  canonical_window_id, session_id,
                                  max_files, max_bytes):

        content_text = _extract_content_text(record)
        if not content_text:
            continue

        # query_hint filter
        if hint and hint not in content_text.lower():
            continue

        excerpt = content_text[:clamped_excerpt]
        item = {
            "source_system": record.get("_source_system", source_system),
            "computer_name": record.get("_computer_name", computer_name),
            "canonical_window_id": record.get("_canonical_window_id", ""),
            "session_id": record.get("_source_fname", "").replace(".jsonl", ""),
            "native_artifact_format": record.get("_native_artifact_format", ""),
            "raw_archive_layout": record.get("_raw_archive_layout", ""),
            "source_path": record.get("_source_path", ""),
            "line_no": record.get("_line_no", 0),
            "record_type": record.get("type", "message"),
            "role": _parse_role(record),
            "raw_excerpt": excerpt,
            "evidence_hash": compute_evidence_hash(excerpt),
            "raw_evidence_status": "raw",
            "consumer_hint": consumer,
        }
        result.append(item)
        if len(result) >= clamped_limit:
            break

    return result


def build_raw_direct_pack(
    items: list[dict],
    consumer: str = "unknown",
    query_hint: str = "",
    scanned_files: int = 0,
    scanned_bytes: int = 0,
    truncated: bool = False,
) -> dict[str, Any]:
    """Wrap raw-direct results in standard contract."""
    return {
        "ok": True,
        "purpose": "raw_direct_experience_pool",
        "consumer_hint": consumer,
        "query_hint": query_hint,
        "items_count": len(items),
        "items": items,
        "source_mode": "raw_direct",
        "not_clean_summary": True,
        "not_skill_writer": True,
        "not_platform_controller": True,
        "generated_at": _ts(),
        "scanned": {
            "files": scanned_files,
            "bytes": scanned_bytes,
            "truncated_by_limit": truncated,
        },
    }
