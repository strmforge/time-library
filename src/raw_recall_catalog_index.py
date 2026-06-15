#!/usr/bin/env python3
"""Read-only canonical catalog lookup for recall.

This is the catalog/card path for existing raw records. It reads the canonical
record index and returns source-backed anchors; it does not scan raw JSONL files
and does not create another memory layer.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
SESSION_WINDOW_ID_SOURCE_SYSTEMS = {"codex", "claude_code_cli"}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def records_db_path_for_gateway() -> Path:
    override = os.environ.get("MEMCORE_RECORDS_DB", "").strip()
    if override:
        return Path(override).expanduser()
    root_override = os.environ.get("MEMCORE_ROOT", "").strip()
    if root_override:
        root = Path(root_override).expanduser()
    else:
        try:
            from src.config_loader import get_memcore_root
        except Exception:
            from config_loader import get_memcore_root
        root = Path(get_memcore_root()).expanduser()
    return root / "output" / "records" / "records.db"


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for term in re.findall(r"[\w\-.:\u4e00-\u9fff]+", str(query or "").lower()):
        cleaned = term.strip("._:-")
        if len(cleaned) >= 2 and cleaned not in terms:
            terms.append(cleaned)
    return terms


def _matches(query_terms: list[str], line_text: str, meta_text: str) -> bool:
    haystack = (str(line_text or "") + "\n" + str(meta_text or "")).lower()
    if not query_terms:
        return True
    matched = sum(1 for term in query_terms if term in haystack)
    if matched == len(query_terms):
        return True
    if matched >= max(2, min(len(query_terms), 3)):
        return True
    return False


def _index_item(
    row: sqlite3.Row,
    *,
    canonical_window_id: str,
    session_id: str,
    excerpt_chars: int,
    mapping_mode: str,
) -> dict[str, Any] | None:
    preview = _clean_text(row["content_preview"])
    if not preview:
        return None
    bounded = preview[:excerpt_chars]
    source_path = _clean_text(row["raw_path"]) or _clean_text(row["source_path"])
    offset_start = row["raw_offset_start"] if row["raw_offset_start"] is not None else row["source_offset_start"]
    offset_end = row["raw_offset_end"] if row["raw_offset_end"] is not None else row["source_offset_end"]
    msg_id = _first_text(row["native_id"], row["timestamp"], row["message_id"])
    row_source_system = _clean_text(row["source_system"])
    row_session_id = _clean_text(row["session_id"]) or session_id
    row_window_id = _clean_text(row["canonical_window_id"])
    project_id = _clean_text(row["project_id"])
    legacy_window_id = ""
    if row_source_system in SESSION_WINDOW_ID_SOURCE_SYSTEMS and row_session_id:
        if row_window_id and row_window_id != row_session_id and not project_id:
            project_id = row_window_id
        if row_window_id and row_window_id != row_session_id:
            legacy_window_id = row_window_id
        row_window_id = row_session_id
    item = {
        "memory_type": "case_memory",
        "source_kind": "raw_jsonl",
        "exp_id": f"raw-index-{hashlib.sha256(str(row['message_id']).encode('utf-8')).hexdigest()[:16]}",
        "summary": bounded[:200],
        "should_inject": False,
        "confidence": None,
        "source_system": row_source_system,
        "computer_name": "",
        "canonical_window_id": row_window_id or canonical_window_id,
        "session_id": row_session_id,
        "project_id": project_id,
        "project_root": row["project_root"] or "",
        "workstream_id": "",
        "task_id": "",
        "native_session_key": row["session_id"] or session_id,
        "native_artifact_format": row["native_type"] or "",
        "raw_archive_layout": "canonical_record_index",
        "source_path": source_path,
        "source_path_indexed": row["source_path"] or "",
        "raw_path_indexed": row["raw_path"] or "",
        "msg_ids": [msg_id] if msg_id else [],
        "byte_offsets": {"start": offset_start, "end": offset_end},
        "artifact_type": row["native_type"] or f"{row['source_system']}_canonical_message",
        "raw_excerpt": bounded,
        "evidence_hash": hashlib.sha256(bounded.encode("utf-8")).hexdigest() if bounded else None,
        "created_at": row["timestamp"] or row["updated_at"] or _ts(),
        "active_memory_layer": "current_window",
        "raw_evidence_status": "raw_index",
        "raw_mapping_mode": mapping_mode,
        "zhiyi_experience_used_as_raw": False,
    }
    if legacy_window_id:
        item["source_refs_canonical_window_id"] = legacy_window_id
    return item


def _row_mismatches_requested_window(
    row: sqlite3.Row,
    *,
    session_id: str,
    canonical_window_id: str,
) -> bool:
    if session_id and _clean_text(row["session_id"]) == session_id:
        return False
    return bool(
        session_id
        and canonical_window_id
        and _clean_text(row["canonical_window_id"])
        and _clean_text(row["canonical_window_id"]) != canonical_window_id
    )


def query_canonical_window_index(
    *,
    query: str,
    source_system: str,
    session_id: str,
    canonical_window_id: str,
    limit: int,
    excerpt_chars: int,
    allow_recent_context: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """Read canonical message cards for a single active window/session."""
    source_system = _clean_text(source_system)
    session_id = _clean_text(session_id)
    canonical_window_id = _clean_text(canonical_window_id)
    if not source_system or not (session_id or canonical_window_id):
        return [], "identity_required"
    db_path = records_db_path_for_gateway()
    if not db_path.exists():
        return [], "records_db_missing"

    where = ["source_system = ?"]
    params: list[Any] = [source_system]
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    elif canonical_window_id:
        where.append("canonical_window_id = ?")
        params.append(canonical_window_id)

    row_limit = min(max(limit * 20, 40), 200)
    query_terms = _query_terms(query)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.1)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"""
                select message_id, record_id, source_system, session_id,
                       canonical_window_id, project_id, project_root, source_path,
                       raw_path, role, native_type, native_id, timestamp, line_no,
                       raw_line_no, source_offset_start, source_offset_end,
                       raw_offset_start, raw_offset_end, content_preview,
                       updated_at
                from canonical_messages
                where {" and ".join(where)}
                order by timestamp desc, line_no desc
                limit ?
                """,
                (*params, row_limit),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "no such table" in message:
            return [], "canonical_messages_missing"
        if "locked" in message or "busy" in message:
            return [], "records_db_busy"
        return [], "records_db_error"
    except Exception:
        return [], "records_db_error"

    items: list[dict[str, Any]] = []
    window_mismatch = False
    for row in rows:
        preview = _clean_text(row["content_preview"])
        if not preview:
            continue
        meta_text = "\n".join(
            _clean_text(value)
            for value in (
                row["source_system"],
                row["session_id"],
                row["canonical_window_id"],
                row["project_id"],
                row["project_root"],
                row["source_path"],
                row["raw_path"],
                row["native_type"],
            )
            if _clean_text(value)
        )
        if query_terms and not _matches(query_terms, preview, meta_text):
            continue
        if _row_mismatches_requested_window(row, session_id=session_id, canonical_window_id=canonical_window_id):
            window_mismatch = True
        item = _index_item(
            row,
            canonical_window_id=canonical_window_id,
            session_id=session_id,
            excerpt_chars=excerpt_chars,
            mapping_mode="canonical_window_index",
        )
        if item is not None:
            items.append(item)
        if len(items) >= limit:
            break
    if items:
        return items, "hit_session_window_mismatch" if window_mismatch else "hit"

    if rows and allow_recent_context:
        for row in rows:
            if _row_mismatches_requested_window(row, session_id=session_id, canonical_window_id=canonical_window_id):
                window_mismatch = True
            item = _index_item(
                row,
                canonical_window_id=canonical_window_id,
                session_id=session_id,
                excerpt_chars=excerpt_chars,
                mapping_mode="canonical_window_recent_context",
            )
            if item is not None:
                items.append(item)
            if len(items) >= limit:
                break
        if items:
            status = "hit_recent_context"
            if window_mismatch:
                status = "hit_recent_context_session_window_mismatch"
            return items, status
    return [], "miss_content_filter" if rows else "miss_identity"
