#!/usr/bin/env python3
"""
Read-only raw/source_refs HTTP and MCP-compatible gateway for AI clients.

This module does NOT write Hermes skill/memory, does NOT modify platform config,
and does NOT treat zhiyi experience layer as raw evidence.
"""

from __future__ import annotations

import json
import hashlib
import ipaddress
import os
import re
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

try:
    from src.hermes_paths import hermes_state_db_path
except Exception:
    from hermes_paths import hermes_state_db_path
try:
    from src.raw_text_decode import (
        decode_text_bytes as _decode_text_bytes,
        iter_decoded_jsonl_lines as _iter_decoded_jsonl_lines,
        jsonl_line_separator_for_sample as _jsonl_line_separator_for_sample,
    )
except Exception:
    from raw_text_decode import (
        decode_text_bytes as _decode_text_bytes,
        iter_decoded_jsonl_lines as _iter_decoded_jsonl_lines,
        jsonl_line_separator_for_sample as _jsonl_line_separator_for_sample,
    )
try:
    from src.raw_evidence_excerpt import (
        DEFAULT_RAW_SEGMENT_BYTES,
        DEFAULT_RAW_SEGMENT_MAX_SEGMENTS,
        FORBIDDEN_STATE_DIR_PARTS,
        MAX_RAW_OFFSET_READ_BYTES,
        MAX_RAW_SEGMENT_BYTES,
        MAX_RAW_SEGMENT_MAX_SEGMENTS,
        MAX_RAW_STREAM_SCAN_BYTES,
        RAW_SEGMENT_OVERLAP_BYTES,
        TIANDAO_RAW_EVIDENCE_EXCERPT_CONTRACT,
        _append_jsonl_obj_excerpt,
        _extract_bounded_raw_excerpt,
        _extract_bounded_raw_excerpt_by_cursor_segments,
        _extract_bounded_raw_excerpt_by_offsets,
        _extract_content_text,
        _is_safe_raw_gateway_state_dir,
        _load_raw_offset_index,
        _load_raw_segment_state,
        _raw_segment_state_dir,
        _resolve_source_path,
        get_raw_evidence_excerpt_contract,
    )
except Exception:
    from raw_evidence_excerpt import (
        DEFAULT_RAW_SEGMENT_BYTES,
        DEFAULT_RAW_SEGMENT_MAX_SEGMENTS,
        FORBIDDEN_STATE_DIR_PARTS,
        MAX_RAW_OFFSET_READ_BYTES,
        MAX_RAW_SEGMENT_BYTES,
        MAX_RAW_SEGMENT_MAX_SEGMENTS,
        MAX_RAW_STREAM_SCAN_BYTES,
        RAW_SEGMENT_OVERLAP_BYTES,
        TIANDAO_RAW_EVIDENCE_EXCERPT_CONTRACT,
        _append_jsonl_obj_excerpt,
        _extract_bounded_raw_excerpt,
        _extract_bounded_raw_excerpt_by_cursor_segments,
        _extract_bounded_raw_excerpt_by_offsets,
        _extract_content_text,
        _is_safe_raw_gateway_state_dir,
        _load_raw_offset_index,
        _load_raw_segment_state,
        _raw_segment_state_dir,
        _resolve_source_path,
        get_raw_evidence_excerpt_contract,
    )
try:
    from src.zhixing_library import attach_library_card, hybrid_recall_manifest, library_manifest
except Exception:
    from zhixing_library import attach_library_card, hybrid_recall_manifest, library_manifest
try:
    from src.zhixing_preflight import build_zhixing_preflight, classify_prompt
except Exception:
    from zhixing_preflight import build_zhixing_preflight, classify_prompt
try:
    from src.raw_recall_response_budget import (
        compact_recall_payload,
        include_raw_excerpt as _include_raw_excerpt,
        response_budget_mode as _response_budget_mode,
    )
except Exception:
    from raw_recall_response_budget import (
        compact_recall_payload,
        include_raw_excerpt as _include_raw_excerpt,
        response_budget_mode as _response_budget_mode,
    )
try:
    from src.active_memory_routing import (
        DEFAULT_MEMORY_SCOPE,
        HERMES_BROAD_CONTEXT_WORKFLOWS,
        active_memory_routing_status as _active_memory_routing_status,
        resolve_recall_scope as _routing_resolve_recall_scope,
        scope_missing_status as _routing_scope_missing_status,
        truthy as _routing_truthy,
    )
except Exception:
    from active_memory_routing import (
        DEFAULT_MEMORY_SCOPE,
        HERMES_BROAD_CONTEXT_WORKFLOWS,
        active_memory_routing_status as _active_memory_routing_status,
        resolve_recall_scope as _routing_resolve_recall_scope,
        scope_missing_status as _routing_scope_missing_status,
        truthy as _routing_truthy,
    )
try:
    from src.window_binding_registry import get_current_window_binding
except Exception:
    try:
        from window_binding_registry import get_current_window_binding
    except Exception:
        get_current_window_binding = None
try:
    from src.tiandao import ContextPackage, IntentMode, MemoryContextMode
    from src.tiandao.memory_routing import (
        TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
        active_memory_routing_contract_descriptor,
        memory_context_mode_for_routing,
    )
    from src.tiandao.validators import validate_context_package as _validate_tiandao_context_package
except Exception:
    try:
        from tiandao import ContextPackage, IntentMode, MemoryContextMode
        from tiandao.memory_routing import (
            TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
            active_memory_routing_contract_descriptor,
            memory_context_mode_for_routing,
        )
        from tiandao.validators import validate_context_package as _validate_tiandao_context_package
    except Exception:
        ContextPackage = None
        IntentMode = None
        MemoryContextMode = None
        TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT = "tiandao_active_memory_routing.v1"
        active_memory_routing_contract_descriptor = None
        memory_context_mode_for_routing = None
        _validate_tiandao_context_package = None


def _load_handle_recall():
    try:
        from src.p3_recall import handle_recall
    except Exception:
        from p3_recall import handle_recall
    return handle_recall


UTC = timezone.utc
PORT = 9851
MAX_LIMIT = 20
MAX_EXCERPT = 800
ACTIVE_RECALL_CANDIDATE_MAX = 80
PROJECT_STATUS_EXCERPT_CHARS = 800
SERVICE_NAME = "raw_consumption_gateway"
SERVICE_VERSION = "2026.6.14"
HEALTH_IDENTITY_CONTRACT = "raw_gateway_health_identity.v1"
ACTIVE_MEMORY_ROUTING_CONTRACT = "active_memory_routing.v2026.6.14"
MCP_PROTOCOL_VERSION = "2025-06-18"
HTTPServer = ThreadingHTTPServer
SESSION_WINDOW_ID_SOURCE_SYSTEMS = {"codex", "claude_code_cli"}

def _service_source_path() -> Path:
    return Path(__file__).resolve()


def _service_source_sha256(path: Path | None = None) -> str:
    source_path = path or _service_source_path()
    h = hashlib.sha256()
    try:
        with source_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def _json_loads_maybe(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _normalize_path_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    return text.replace("\\", "/").rstrip("/").lower()


def _item_project_id(item: Dict[str, Any]) -> str:
    return _first_text(item.get("project_id"), item.get("project"))


def _item_project_root(item: Dict[str, Any]) -> str:
    return _first_text(item.get("project_root"), item.get("workspace_root"), item.get("cwd"))


def _item_workstream_id(item: Dict[str, Any]) -> str:
    return _first_text(item.get("workstream_id"), item.get("workstream"), item.get("task_stream"))


def _item_task_id(item: Dict[str, Any]) -> str:
    return _first_text(item.get("task_id"), item.get("task"), item.get("ticket_id"))


def _item_legacy_window_id(item: Dict[str, Any]) -> str:
    return _first_text(item.get("source_refs_canonical_window_id"), item.get("legacy_canonical_window_id"))


def _active_layer_for_item(
    item: Dict[str, Any],
    *,
    session_id: str,
    canonical_window_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
) -> str:
    if session_id and _clean_text(item.get("session_id")) == session_id:
        return "current_window"
    if canonical_window_id and _clean_text(item.get("canonical_window_id")) == canonical_window_id:
        return "current_window"
    if canonical_window_id and _item_legacy_window_id(item) == canonical_window_id:
        return "current_window"
    if project_id and _item_project_id(item) == project_id:
        return "same_project_workspace"
    if project_root and _normalize_path_text(_item_project_root(item)) == _normalize_path_text(project_root):
        return "same_project_workspace"
    if workstream_id and _item_workstream_id(item) == workstream_id:
        return "same_workstream_task"
    if task_id and _item_task_id(item) == task_id:
        return "same_workstream_task"
    memory_type = _clean_text(item.get("memory_type") or item.get("type")).lower()
    stable_types = {
        "preference_memory",
        "tool_fact",
        "tool_facts",
        "toolbook",
        "toolbook_candidate",
        "model_fact",
        "source_system_fact",
        "source_system_profile",
    }
    if (
        memory_type in stable_types
        or memory_type.startswith("tool")
        or memory_type.endswith("_fact")
    ):
        return "stable_user_preferences_tool_facts"
    return ""


def _apply_active_layered_routing(
    items: List[Dict[str, Any]],
    *,
    limit: int,
    session_id: str,
    canonical_window_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    order = [
        "current_window",
        "current_session",
        "same_project_workspace",
        "same_workstream_task",
        "stable_user_preferences_tool_facts",
    ]
    layered: Dict[str, List[Dict[str, Any]]] = {layer: [] for layer in order}
    seen_keys = set()
    for item in items:
        layer = _active_layer_for_item(
            item,
            session_id=session_id,
            canonical_window_id=canonical_window_id,
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
        )
        if not layer:
            continue
        key = (
            str(item.get("source_path", "")),
            tuple(item.get("msg_ids") or []),
            str(item.get("exp_id", "")),
            str(item.get("raw_excerpt", "")),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        routed = dict(item)
        routed["active_memory_layer"] = layer
        layered[layer].append(routed)

    selected: List[Dict[str, Any]] = []
    used_layers: List[str] = []
    for layer in order:
        for item in layered[layer]:
            selected.append(item)
            if layer not in used_layers:
                used_layers.append(layer)
            if len(selected) >= limit:
                return selected, used_layers
    return selected, used_layers


def _current_computer_name() -> str:
    try:
        from src.config_loader import node_id
    except ImportError:
        try:
            from config_loader import node_id
        except ImportError:
            node_id = None
    if node_id:
        try:
            value = str(node_id()).strip()
            if value:
                return value
        except Exception:
            pass
    return "local"


def _hermes_state_db_path() -> Path:
    return hermes_state_db_path()


def _hermes_query_terms(query: str) -> List[str]:
    q = str(query or "").strip()
    if not q:
        return []
    terms: List[str] = []

    def add(term: str) -> None:
        term = str(term or "").strip()
        if term and term not in terms:
            terms.append(term)

    add(q)
    for term in q.replace("，", " ").replace(",", " ").replace("。", " ").replace("；", " ").replace(";", " ").split():
        add(term)
    return terms[:6]


def _query_hermes_state_db(
    query: str,
    computer_name: str,
    session_id: str,
    limit: int,
    excerpt_chars: int,
) -> List[Dict[str, Any]]:
    current_computer = _current_computer_name()
    if computer_name and computer_name != current_computer:
        return []

    db_path = _hermes_state_db_path()
    if not db_path.exists():
        return []

    terms = _hermes_query_terms(query)
    if not terms and not session_id:
        return []

    where: List[str] = []
    params: List[Any] = []
    if session_id:
        where.append("m.session_id = ?")
        params.append(session_id)
    if terms:
        where.append("(" + " OR ".join(["m.content LIKE ?"] * len(terms)) + ")")
        params.extend([f"%{term}%" for term in terms])
    where_sql = " AND ".join(where) if where else "1=1"

    try:
        import sqlite3

        uri = "file:{}?mode=ro".format(db_path.resolve())
        con = sqlite3.connect(uri, uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT
                m.id AS message_id,
                m.session_id AS session_id,
                m.role AS role,
                m.content AS content,
                m.timestamp AS timestamp,
                s.source AS source,
                s.model AS model
            FROM messages m
            LEFT JOIN sessions s ON s.id = m.session_id
            WHERE {}
            ORDER BY m.timestamp DESC, m.id DESC
            LIMIT ?
            """.format(where_sql),
            params + [limit],
        ).fetchall()
        con.close()
    except Exception:
        return []

    items: List[Dict[str, Any]] = []
    source_path = str(db_path)
    for row in rows:
        content = _extract_content_text(row["content"])
        raw_excerpt = f"[{row['role'] or 'unknown'}] {content}"[:excerpt_chars]
        evidence_hash = hashlib.sha256(raw_excerpt.encode("utf-8")).hexdigest() if raw_excerpt else None
        msg_id = "messages:{}".format(row["message_id"])
        sid = str(row["session_id"] or "")
        items.append({
            "source_system": "hermes",
            "computer_name": current_computer,
            "session_id": sid,
            "native_session_key": sid,
            "source_path": source_path,
            "msg_ids": [msg_id],
            "artifact_type": "hermes_state_db",
            "raw_excerpt": raw_excerpt,
            "evidence_hash": evidence_hash,
            "created_at": ts(),
            "raw_evidence_status": "raw",
            "raw_mapping_mode": "hermes_state_db_readonly",
            "zhiyi_experience_used_as_raw": False,
            "hermes_source": row["source"] or "",
            "hermes_model": row["model"] or "",
        })
    return items


def _query_raw_jsonl_fallback(
    query: str,
    source_system: str,
    computer_name: str,
    session_id: str,
    canonical_window_id: str,
    limit: int,
    excerpt_chars: int,
) -> List[Dict[str, Any]]:
    query_text = str(query or "").strip()
    query_terms = _raw_fallback_query_terms(query_text)
    canonical_window_id = str(canonical_window_id or "").strip()
    if not query_text and not session_id and not canonical_window_id:
        return []

    try:
        from src.config_loader import memory_root
    except ImportError:
        try:
            from config_loader import memory_root
        except ImportError:
            memory_root = None
    if memory_root is None:
        return []

    root = Path(memory_root()).expanduser()
    if not root.exists():
        return []

    candidates: List[Path] = []
    current_patterns: List[str]
    if source_system and computer_name:
        current_patterns = [f"{computer_name}/{source_system}/*/*/*.jsonl"]
    elif source_system:
        current_patterns = [f"*/{source_system}/*/*/*.jsonl"]
    else:
        current_patterns = ["*/*/*/*/*.jsonl"]

    legacy_patterns: List[str]
    if source_system:
        legacy_patterns = [f"{source_system}/*/*/*.jsonl"]
    else:
        legacy_patterns = ["*/*/*.jsonl"]

    for pattern in current_patterns + legacy_patterns:
        for path in root.glob(pattern):
            parts = path.relative_to(root).parts
            if len(parts) >= 5:
                comp = parts[0]
                src = parts[1]
            elif len(parts) >= 4:
                src = parts[0]
                comp = parts[1]
            else:
                continue
            if source_system and src != source_system:
                continue
            if computer_name and comp != computer_name:
                continue
            if session_id and path.stem != session_id:
                continue
            if canonical_window_id:
                if len(parts) >= 5:
                    window = parts[3]
                elif len(parts) >= 4:
                    window = parts[2]
                else:
                    window = ""
                session_matches = bool(
                    session_id
                    and path.stem == session_id
                    and src in SESSION_WINDOW_ID_SOURCE_SYSTEMS
                )
                if not session_matches and window != canonical_window_id:
                    continue
            candidates.append(path)
    candidates = list(dict.fromkeys(candidates))

    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    items: List[Dict[str, Any]] = []
    for path in candidates:
        try:
            rel = path.relative_to(root).parts
        except Exception:
            rel = ()
        if len(rel) >= 5:
            comp = rel[0]
            src = rel[1]
            native_format = rel[2]
            window = rel[3]
            layout = "computer_first"
        elif len(rel) >= 4:
            src = rel[0]
            comp = rel[1]
            native_format = ""
            window = rel[2]
            layout = "legacy_source_first"
        else:
            continue
        sid = path.stem
        meta_text = _raw_fallback_meta_text(path, root)
        try:
            for start, end, text in _iter_decoded_jsonl_lines(path):
                if len(items) >= limit:
                    break
                text = text.strip()
                if not text:
                    continue
                if query_terms and not _raw_fallback_matches(query_terms, text, meta_text):
                    continue
                try:
                    obj = json.loads(text)
                except Exception:
                    obj = {}
                excerpt_parts: List[str] = []
                if isinstance(obj, dict):
                    _append_jsonl_obj_excerpt(obj, [], excerpt_parts)
                raw_excerpt = " | ".join(excerpt_parts).strip() or text
                bounded = raw_excerpt[:excerpt_chars]
                evidence_hash = hashlib.sha256(bounded.encode("utf-8")).hexdigest() if bounded else None
                msg_id = ""
                project_id = ""
                project_root = ""
                workstream_id = ""
                task_id = ""
                if isinstance(obj, dict):
                    payload = obj.get("payload", {}) if isinstance(obj.get("payload"), dict) else {}
                    source_refs = obj.get("source_refs", {}) if isinstance(obj.get("source_refs"), dict) else {}
                    msg_id = str(
                        obj.get("id")
                        or payload.get("turn_id")
                        or obj.get("timestamp")
                        or f"offset:{start}"
                    )
                    project_id = _first_text(
                        obj.get("project_id"),
                        payload.get("project_id"),
                        source_refs.get("project_id"),
                        window if src in SESSION_WINDOW_ID_SOURCE_SYSTEMS and window != sid else "",
                    )
                    project_root = _first_text(
                        obj.get("project_root"),
                        obj.get("workspace_root"),
                        obj.get("cwd"),
                        payload.get("project_root"),
                        payload.get("workspace_root"),
                        payload.get("cwd"),
                        source_refs.get("project_root"),
                        source_refs.get("workspace_root"),
                        source_refs.get("cwd"),
                    )
                    workstream_id = _first_text(
                        obj.get("workstream_id"),
                        obj.get("workstream"),
                        payload.get("workstream_id"),
                        payload.get("workstream"),
                        source_refs.get("workstream_id"),
                        source_refs.get("workstream"),
                    )
                    task_id = _first_text(
                        obj.get("task_id"),
                        obj.get("task"),
                        payload.get("task_id"),
                        payload.get("task"),
                        source_refs.get("task_id"),
                        source_refs.get("task"),
                    )
                item_window_id = window
                legacy_window_id = ""
                if src in SESSION_WINDOW_ID_SOURCE_SYSTEMS and sid:
                    if not project_id and window and window != sid:
                        project_id = window
                    if window and window != sid:
                        legacy_window_id = window
                    item_window_id = sid
                item = {
                    "memory_type": "raw_jsonl",
                    "exp_id": "raw-{}".format(hashlib.sha256(f"{path}:{start}:{end}".encode()).hexdigest()[:16]),
                    "summary": bounded[:200],
                    "should_inject": False,
                    "confidence": None,
                    "source_system": src,
                    "computer_name": comp,
                    "canonical_window_id": item_window_id,
                    "session_id": sid,
                    "project_id": project_id,
                    "project_root": project_root,
                    "workstream_id": workstream_id,
                    "task_id": task_id,
                    "native_session_key": sid,
                    "native_artifact_format": native_format,
                    "raw_archive_layout": layout,
                    "source_path": str(path),
                    "msg_ids": [msg_id] if msg_id else [],
                    "byte_offsets": {"start": start, "end": end},
                    "artifact_type": native_format or f"{src}_session_jsonl",
                    "raw_excerpt": bounded,
                    "evidence_hash": evidence_hash,
                    "created_at": ts(),
                    "raw_evidence_status": "raw_direct",
                    "raw_mapping_mode": "raw_jsonl_fallback",
                    "zhiyi_experience_used_as_raw": False,
                }
                if legacy_window_id:
                    item["source_refs_canonical_window_id"] = legacy_window_id
                items.append(item)
                if len(items) >= limit:
                    break
        except Exception:
            continue
        if len(items) >= limit:
            break
    return items


def _records_db_path_for_gateway() -> Path:
    override = os.environ.get("MEMCORE_RECORDS_DB", "").strip()
    if override:
        return Path(override).expanduser()
    root_override = os.environ.get("MEMCORE_ROOT", "").strip()
    root = Path(root_override).expanduser() if root_override else _project_root()
    return root / "output" / "records" / "records.db"


def _preflight_recent_context_allowed(query: str) -> bool:
    text = _clean_text(query)
    if not text:
        return False
    prompt = classify_prompt(text)
    if not bool(prompt.get("should_recall")):
        return False
    prompt_class = str(prompt.get("prompt_class") or "")
    if prompt_class not in {"continuation", "status", "task", "preference", "correction"}:
        return False
    compact_text = re.sub(r"\s+", "", text)
    query_terms = _raw_fallback_query_terms(text)
    if len(compact_text) <= 32:
        return True
    return (
        len(compact_text) <= 48
        and 0 < len(query_terms) <= 2
        and all(len(term) <= 16 for term in query_terms)
    )


def _canonical_window_index_item(
    row: sqlite3.Row,
    *,
    canonical_window_id: str,
    session_id: str,
    excerpt_chars: int,
    mapping_mode: str,
) -> Dict[str, Any] | None:
    preview = _clean_text(row["content_preview"])
    if not preview:
        return None
    bounded = preview[:excerpt_chars]
    source_path = _clean_text(row["raw_path"]) or _clean_text(row["source_path"])
    offset_start = row["raw_offset_start"] if row["raw_offset_start"] is not None else row["source_offset_start"]
    offset_end = row["raw_offset_end"] if row["raw_offset_end"] is not None else row["source_offset_end"]
    msg_id = _first_text(row["native_id"], row["timestamp"], row["message_id"])
    evidence_hash = hashlib.sha256(bounded.encode("utf-8")).hexdigest() if bounded else None
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
        "evidence_hash": evidence_hash,
        "created_at": row["timestamp"] or row["updated_at"] or ts(),
        "active_memory_layer": "current_window",
        "raw_evidence_status": "raw_index",
        "raw_mapping_mode": mapping_mode,
        "zhiyi_experience_used_as_raw": False,
    }
    if legacy_window_id:
        item["source_refs_canonical_window_id"] = legacy_window_id
    return item


def _canonical_window_row_mismatches_requested_window(
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


def _query_canonical_window_index(
    query: str,
    source_system: str,
    session_id: str,
    canonical_window_id: str,
    limit: int,
    excerpt_chars: int,
) -> Tuple[List[Dict[str, Any]], str]:
    """Fast read-only path for automatic window preflight.

    This intentionally does not create schema or fall back to broad scans. The
    preflight hook is on the user's main request path, so a missing/stale index
    must become a quick silent miss instead of a cold recall.
    """
    source_system = _clean_text(source_system)
    session_id = _clean_text(session_id)
    canonical_window_id = _clean_text(canonical_window_id)
    if not source_system or not (session_id or canonical_window_id):
        return [], "identity_required"
    db_path = _records_db_path_for_gateway()
    if not db_path.exists():
        return [], "records_db_missing"

    where = ["source_system = ?"]
    params: List[Any] = [source_system]
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    elif canonical_window_id:
        where.append("canonical_window_id = ?")
        params.append(canonical_window_id)

    row_limit = max(limit * 20, 40)
    row_limit = min(row_limit, 200)
    query_terms = _raw_fallback_query_terms(query)
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

    items: List[Dict[str, Any]] = []
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
        if query_terms and not _raw_fallback_matches(query_terms, preview, meta_text):
            continue
        if _canonical_window_row_mismatches_requested_window(
            row,
            session_id=session_id,
            canonical_window_id=canonical_window_id,
        ):
            window_mismatch = True
        item = _canonical_window_index_item(
            row,
            canonical_window_id=canonical_window_id,
            session_id=session_id,
            excerpt_chars=excerpt_chars,
            mapping_mode="canonical_window_index",
        )
        if item is None:
            continue
        items.append(item)
        if len(items) >= limit:
            break
    if items:
        return items, "hit_session_window_mismatch" if window_mismatch else "hit"
    if rows and _preflight_recent_context_allowed(query):
        for row in rows:
            if _canonical_window_row_mismatches_requested_window(
                row,
                session_id=session_id,
                canonical_window_id=canonical_window_id,
            ):
                window_mismatch = True
            item = _canonical_window_index_item(
                row,
                canonical_window_id=canonical_window_id,
                session_id=session_id,
                excerpt_chars=excerpt_chars,
                mapping_mode="canonical_window_recent_context",
            )
            if item is None:
                continue
            items.append(item)
            if len(items) >= limit:
                break
        if items:
            status = "hit_recent_context"
            if window_mismatch:
                status = "hit_recent_context_session_window_mismatch"
            return items, status
    return [], "miss_content_filter" if rows else "miss_identity"


def _raw_fallback_query_terms(query: str) -> List[str]:
    terms: List[str] = []
    for term in re.findall(r"[\w\-.:\u4e00-\u9fff]+", str(query or "").lower()):
        cleaned = term.strip("._:-")
        if len(cleaned) >= 2 and cleaned not in terms:
            terms.append(cleaned)
    return terms


def _raw_fallback_meta_text(path: Path, root: Path) -> str:
    parts: List[str] = []
    try:
        parts.extend(str(part) for part in path.relative_to(root).parts)
    except Exception:
        parts.append(str(path))
    meta_path = Path(str(path) + ".meta.json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception:
            meta = {}
        if isinstance(meta, dict):
            for key in (
                "thread_name",
                "project_id",
                "project_root",
                "session_id",
                "conversation_origin",
                "runtime_consumer",
                "storage_owner",
                "body_storage_owner",
                "desktop_session_id",
            ):
                value = meta.get(key)
                if value:
                    parts.append(str(value))
    return "\n".join(parts).lower()


def _raw_fallback_matches(query_terms: List[str], line_text: str, meta_text: str) -> bool:
    haystack = (str(line_text or "") + "\n" + str(meta_text or "")).lower()
    if not query_terms:
        return True
    matched = sum(1 for term in query_terms if term in haystack)
    if matched == len(query_terms):
        return True
    if matched >= max(2, min(len(query_terms), 3)):
        return True
    return False


def _consumer_receipt(
    consumer: str,
    request_id: str,
    items_count: int,
    source_refs_count: int,
    raw_items_count: int,
    items: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    used_items = items or []
    used_library_ids = [
        str(item.get("library_id") or "")
        for item in used_items
        if str(item.get("library_id") or "")
    ]
    used_source_refs = [
        {
            "library_id": item.get("library_id", ""),
            "source_system": item.get("source_system", ""),
            "source_path": item.get("source_path", ""),
            "session_id": item.get("session_id", ""),
            "msg_ids": item.get("msg_ids", []) or [],
        }
        for item in used_items
        if item.get("source_path")
    ]
    return {
        'consumer': consumer or 'unknown',
        'request_id': request_id or '',
        'consumed_at': ts(),
        'query_path': '/api/v1/raw/query',
        'read_only': True,
        'write_performed': False,
        'platform_write_performed': False,
        'skill_write': False,
        'memory_write': False,
        'config_write': False,
        'items_count': items_count,
        'source_refs_count': source_refs_count,
        'raw_items_count': raw_items_count,
        'used_library_ids': used_library_ids,
        'used_source_refs': used_source_refs,
        'matched_by': {
            item.get("library_id", ""): item.get("matched_by", [])
            for item in used_items
            if item.get("library_id")
        },
        'rank_reason': {
            item.get("library_id", ""): item.get("rank_reason", "")
            for item in used_items
            if item.get("library_id")
        },
        'receipt_scope': 'raw_source_refs_live_gateway',
    }


def _truthy(value: Any) -> bool:
    return _routing_truthy(value)


def _resolve_recall_scope(
    *,
    source_system: str,
    consumer: str,
    memory_scope: str,
    canonical_window_id: str,
    session_id: str,
    allow_cross_window_recall: bool = False,
    cross_window_reason: str = "",
) -> Dict[str, Any]:
    return _routing_resolve_recall_scope(
        source_system=source_system,
        consumer=consumer,
        memory_scope=memory_scope,
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        allow_cross_window_recall=allow_cross_window_recall,
        cross_window_reason=cross_window_reason,
    )


def _scope_missing_status(scope: Dict[str, Any]) -> Dict[str, str]:
    return _routing_scope_missing_status(scope)


def _is_capability_check_request(args: Dict[str, Any]) -> bool:
    mode = str(args.get("mode") or "").strip().lower()
    return (
        mode == "capability_check"
        or _truthy(args.get("capability_check"))
        or _truthy(args.get("no_recall"))
    )


def _is_preflight_request(args: Dict[str, Any]) -> bool:
    return str(args.get("mode") or "").strip().lower() == "preflight"


def _preflight_has_active_anchor(
    *,
    session_id: str,
    canonical_window_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
) -> bool:
    return any(
        _clean_text(value)
        for value in (
            session_id,
            canonical_window_id,
            project_id,
            project_root,
            workstream_id,
            task_id,
        )
    )


def _current_window_binding_anchor(source_system: str, consumer: str) -> Dict[str, Any]:
    if get_current_window_binding is None:
        return {}
    try:
        binding = get_current_window_binding(source_system, consumer=consumer)
    except Exception:
        return {}
    return binding if isinstance(binding, dict) else {}


def _binding_metadata(binding: Dict[str, Any]) -> Dict[str, Any]:
    metadata = binding.get("metadata") if isinstance(binding.get("metadata"), dict) else {}
    return metadata


def _tiandao_memory_mode(memory_scope: str, active_layers_used: List[str], cross_window_read: bool) -> str:
    if memory_context_mode_for_routing is not None:
        return str(memory_context_mode_for_routing(memory_scope, active_layers_used, cross_window_read))
    if memory_scope in {"raw_pool", "platform"} or cross_window_read:
        return "mode_c"
    active_layers = set(active_layers_used or [])
    if active_layers and active_layers <= {"current_window", "current_session"}:
        return "mode_a"
    if active_layers:
        return "mode_b"
    return "mode_a"


def _tiandao_source_refs(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for index, item in enumerate(items or []):
        source_path = _clean_text(item.get("source_path"))
        if not source_path:
            continue
        ref_seed = "|".join([
            _clean_text(item.get("source_system")),
            source_path,
            ",".join(str(msg_id) for msg_id in (item.get("msg_ids") or [])),
        ])
        refs.append({
            "ref_id": hashlib.sha256(ref_seed.encode("utf-8")).hexdigest()[:24],
            "source_system": item.get("source_system", ""),
            "artifact_type": item.get("artifact_type") or f"{item.get('source_system', 'source')}_raw_record",
            "ref_path": source_path,
            "artifact_id": item.get("native_session_key") or item.get("session_id") or item.get("exp_id") or str(index),
            "captured_at": item.get("created_at", ""),
            "msg_ids": item.get("msg_ids") or [],
            "evidence_hash": item.get("evidence_hash"),
            "raw_evidence_status": item.get("raw_evidence_status", ""),
            "auth_required": False,
            "auth_granted": True,
        })
    return refs


def _tiandao_matched_memories(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for item in items or []:
        matched.append({
            "library_id": item.get("library_id", ""),
            "library_shelf": item.get("library_shelf", ""),
            "memory_type": item.get("memory_type", ""),
            "exp_id": item.get("exp_id", ""),
            "source_system": item.get("source_system", ""),
            "computer_name": item.get("computer_name", ""),
            "canonical_window_id": item.get("canonical_window_id", ""),
            "session_id": item.get("session_id", ""),
            "project_id": item.get("project_id", ""),
            "project_root": item.get("project_root", ""),
            "workstream_id": item.get("workstream_id", ""),
            "task_id": item.get("task_id", ""),
            "active_memory_layer": item.get("active_memory_layer", ""),
            "raw_evidence_status": item.get("raw_evidence_status", ""),
            "raw_excerpt_returned": bool(item.get("raw_excerpt")),
            "evidence_hash": item.get("evidence_hash"),
        })
    return matched


def _build_tiandao_context_package(
    *,
    query: str,
    source_system: str,
    consumer: str,
    canonical_window_id: str,
    session_id: str,
    items: List[Dict[str, Any]],
    memory_scope: str,
    memory_base_scope: str,
    scope_missing: bool,
    active_layers_used: List[str],
    binding: Dict[str, Any],
    binding_applied_fields: List[str],
    cross_window_read: bool,
    cross_window_read_allowed: bool,
    injection_boundary: str,
    block_reason: str = "",
) -> Dict[str, Any]:
    if ContextPackage is None or IntentMode is None or MemoryContextMode is None:
        return {
            "schema": "tiandao_context_package.v1",
            "query": query,
            "query_hash": hashlib.sha256((query or "").encode("utf-8")).hexdigest(),
            "source_system": source_system or consumer or "unknown",
            "canonical_window_id": canonical_window_id,
            "session_id": session_id,
            "intent_mode": "evidence",
            "memory_context_mode": _tiandao_memory_mode(memory_scope, active_layers_used, cross_window_read),
            "active_memory_routing_contract": TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
            "active_layers_used": active_layers_used or [],
            "current_window_binding_applied": bool(binding_applied_fields),
            "cross_window_read": bool(cross_window_read),
            "cross_window_read_allowed": bool(cross_window_read_allowed),
            "tiandao_scope": "tiandao_candidate_projection",
            "honghuang_subsystem": "yifanchen",
            "tiandao_face": "memory_context",
            "contract_role": "memory_context_candidate",
            "scope_enforced": True,
            "injection_blocked": bool(scope_missing),
            "block_reason": block_reason,
            "memory_write": False,
            "overclaim_boundary": "does_not_claim_tiandao_runtime_nantianmen_liudao_or_central_node",
        }

    mode = _tiandao_memory_mode(memory_scope, active_layers_used, cross_window_read)
    package = ContextPackage(
        query=query or "zhiyi recall",
        source_system=source_system or consumer or "unknown",
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        intent_mode=IntentMode.EVIDENCE,
        memory_context_mode=MemoryContextMode(mode),
        matched_memories=_tiandao_matched_memories(items),
        source_refs=_tiandao_source_refs(items),
        raw_projection={
            "policy": "source_refs_and_bounded_excerpts",
            "raw_excerpt_location": "items.raw_excerpt",
            "raw_items_count": sum(1 for item in items or [] if _is_raw_evidence_status(item.get("raw_evidence_status", ""))),
        },
        active_memory_routing_contract=TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
        active_layers_used=active_layers_used or [],
        current_window_binding_applied=bool(binding_applied_fields),
        cross_window_read=bool(cross_window_read),
        cross_window_read_allowed=bool(cross_window_read_allowed),
        scope_enforced=True,
        injection_blocked=bool(scope_missing),
        block_reason=block_reason or None,
        memory_write=False,
    ).to_dict()
    package.update({
        "tiandao_scope": "tiandao_candidate_projection",
        "honghuang_subsystem": "yifanchen",
        "tiandao_face": "memory_context",
        "tiandao_routing_contract": active_memory_routing_contract_descriptor()
        if active_memory_routing_contract_descriptor is not None
        else {"contract": TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT},
        "contract_role": "memory_context_candidate",
        "consumer": consumer or "unknown",
        "memory_scope": memory_scope,
        "memory_base_scope": memory_base_scope,
        "overclaim_boundary": "does_not_claim_tiandao_runtime_nantianmen_liudao_or_central_node",
        "active_layers_used": active_layers_used or [],
        "current_window_binding_applied": bool(binding_applied_fields),
        "current_window_binding_key": binding.get("binding_key", "") if binding else "",
        "current_window_binding_fields": binding_applied_fields,
        "cross_window_read": bool(cross_window_read),
        "cross_window_read_allowed": bool(cross_window_read_allowed),
        "injection_boundary": injection_boundary,
        "permission_boundary": {
            "memory_write_enabled": False,
            "skill_write_enabled": False,
            "platform_write_enabled": False,
            "context_delivery_executed": False,
            "apply_to_platform_blocked": True,
            "read_only": True,
        },
        "capability_profile": {
            "adapter": "RawConsumptionGateway",
            "version": SERVICE_VERSION,
            "source_system": source_system or consumer or "unknown",
            "can_write_memory": False,
            "can_write_skill": False,
            "is_production_ready": True,
            "production_ready_scope": "raw_consumption_gateway_adapter_only",
            "raw_projection_supported": True,
            "active_memory_routing_contract": ACTIVE_MEMORY_ROUTING_CONTRACT,
            "tiandao_active_memory_routing_contract": TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
        },
        "adapter_verdict": {
            "adapter": "RawConsumptionGateway",
            "version": SERVICE_VERSION,
            "production_ready": True,
            "production_ready_scope": "raw_consumption_gateway_adapter_only",
            "memory_write_enabled": False,
            "skill_write_enabled": False,
            "context_delivery_executed": False,
            "adapter_verdict": "READY_FOR_MEMORY_CONTEXT_CANDIDATE",
        },
    })
    if _validate_tiandao_context_package is not None:
        valid, violations = _validate_tiandao_context_package(package)
        package["validation"] = {"valid": valid, "violations": violations}
    return package


def capability_check_payload(
    consumer: str = "",
    request_id: str = "",
    source: str = "",
) -> Dict[str, Any]:
    receipt = _consumer_receipt(consumer, request_id, 0, 0, 0, [])
    receipt["receipt_scope"] = "capability_check_no_recall"
    return {
        "ok": True,
        "mode": "capability_check",
        "service": SERVICE_NAME,
        "server": "yifanchen-zhiyi",
        "version": SERVICE_VERSION,
        "source": source or "unknown",
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "recall_performed": False,
        "raw_excerpt_returned": False,
        "raw_query_path": "/api/v1/raw/query",
        "mcp_path": "/mcp",
        "mcp_tools": ["zhiyi_recall"],
        "zhixing_library": library_manifest(),
        "matched_count": 0,
        "source_refs_count": 0,
        "raw_items_count": 0,
        "items": [],
        "consumer_receipt": receipt,
    }


def preflight_payload(
    query: str,
    source_system: str = '',
    computer_name: str = '',
    session_id: str = '',
    limit: int = 3,
    excerpt_chars: int = 180,
    consumer: str = '',
    request_id: str = '',
    memory_scope: str = '',
    canonical_window_id: str = '',
    allow_cross_window_recall: bool = False,
    cross_window_reason: str = '',
    project_id: str = '',
    project_root: str = '',
    workstream_id: str = '',
    task_id: str = '',
) -> Dict[str, Any]:
    prompt = classify_prompt(query)
    if not bool(prompt.get("should_recall")):
        preflight = build_zhixing_preflight(
            query,
            recall_payload={
                "ok": True,
                "consumer": consumer,
                "memory_scope": memory_scope,
                "items": [],
                "matched_count": 0,
                "source_refs_count": 0,
                "raw_items_count": 0,
            },
            consumer=consumer,
            request_id=request_id,
        )
        preflight.update({
            "source_system_filter": source_system,
            "requested_source_system": source_system,
            "canonical_window_id_filter": canonical_window_id,
            "project_id_filter": project_id,
            "project_root_filter": project_root,
            "workstream_id_filter": workstream_id,
            "task_id_filter": task_id,
            "current_window_binding_applied": False,
            "current_window_binding_key": "",
            "current_window_binding_fields": [],
            "agent_boundary": "active_window_first_explicit_broad_scope",
            "injection_boundary": "active_layered_source_refs_only",
            "tiandao_context_package_valid": True,
            "zhixing_library": library_manifest(),
            "hybrid_recall": hybrid_recall_manifest(),
        })
        return preflight
    if (
        not _preflight_has_active_anchor(
            session_id=session_id,
            canonical_window_id=canonical_window_id,
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
        )
        and not allow_cross_window_recall
    ):
        preflight = build_zhixing_preflight(
            query,
            recall_payload={
                "ok": True,
                "consumer": consumer,
                "memory_scope": memory_scope or "active",
                "memory_base_scope": "active_layered",
                "scope_missing": True,
                "recall_status": "active_preflight_anchor_required",
                "missing_scope_fields": ["session_id", "canonical_window_id", "project_id", "project_root", "workstream_id", "task_id"],
                "cross_window_read": False,
                "cross_window_read_allowed": False,
                "items": [],
                "matched_count": 0,
                "source_refs_count": 0,
                "raw_items_count": 0,
                "recall_performed": False,
            },
            consumer=consumer,
            request_id=request_id,
        )
        preflight.update({
            "source_system_filter": source_system,
            "requested_source_system": source_system,
            "canonical_window_id_filter": canonical_window_id,
            "project_id_filter": project_id,
            "project_root_filter": project_root,
            "workstream_id_filter": workstream_id,
            "task_id_filter": task_id,
            "current_window_binding_applied": False,
            "current_window_binding_key": "",
            "current_window_binding_fields": [],
            "agent_boundary": "active_window_first_explicit_broad_scope",
            "injection_boundary": "active_layered_source_refs_only",
            "tiandao_context_package_valid": True,
            "zhixing_library": library_manifest(),
            "hybrid_recall": hybrid_recall_manifest(),
        })
        return preflight
    recall_payload = query_raw_source_refs(
        query=query,
        source_system=source_system,
        computer_name=computer_name,
        session_id=session_id,
        limit=limit,
        excerpt_chars=excerpt_chars,
        consumer=consumer,
        request_id=request_id,
        memory_scope=memory_scope,
        canonical_window_id=canonical_window_id,
        allow_cross_window_recall=allow_cross_window_recall,
        cross_window_reason=cross_window_reason,
        project_id=project_id,
        project_root=project_root,
        workstream_id=workstream_id,
        task_id=task_id,
        fast_window_preflight=True,
    )
    preflight = build_zhixing_preflight(
        query,
        recall_payload=recall_payload,
        consumer=consumer or recall_payload.get("consumer", ""),
        request_id=request_id,
    )
    preflight.update({
        "source_system_filter": recall_payload.get("source_system_filter", ""),
        "requested_source_system": recall_payload.get("requested_source_system", ""),
        "inferred_source_system": recall_payload.get("inferred_source_system", ""),
        "canonical_window_id_filter": recall_payload.get("canonical_window_id_filter", ""),
        "project_id_filter": recall_payload.get("project_id_filter", ""),
        "project_root_filter": recall_payload.get("project_root_filter", ""),
        "workstream_id_filter": recall_payload.get("workstream_id_filter", ""),
        "task_id_filter": recall_payload.get("task_id_filter", ""),
        "current_window_binding_applied": recall_payload.get("current_window_binding_applied", False),
        "current_window_binding_key": recall_payload.get("current_window_binding_key", ""),
        "current_window_binding_fields": recall_payload.get("current_window_binding_fields", []),
        "agent_boundary": recall_payload.get("agent_boundary", "active_window_first_explicit_broad_scope"),
        "injection_boundary": recall_payload.get("injection_boundary", "active_layered_source_refs_only"),
        "tiandao_context_package_valid": recall_payload.get("tiandao_context_package_valid", True),
        "fast_window_preflight": recall_payload.get("fast_window_preflight", False),
        "fast_recall_path": recall_payload.get("fast_recall_path", ""),
        "fast_window_index_status": recall_payload.get("fast_window_index_status", ""),
        "zhiyi_layer_skipped_for_fast_preflight": recall_payload.get("zhiyi_layer_skipped_for_fast_preflight", False),
        "zhixing_library": recall_payload.get("zhixing_library") or library_manifest(),
        "hybrid_recall": recall_payload.get("hybrid_recall") or hybrid_recall_manifest(),
    })
    return preflight


def _is_raw_evidence_status(status: str) -> bool:
    status = str(status or "")
    return status == "raw" or status.startswith("raw_")


def _annotate_gateway_item(item: Dict[str, Any], query: str = "") -> Dict[str, Any]:
    raw_status = str(item.get("raw_evidence_status") or "")
    raw_excerpt = str(item.get("raw_excerpt") or "")
    annotated = attach_library_card(item, query=query, raw_status=raw_status, raw_excerpt=raw_excerpt)
    card = annotated.get("library_card", {})
    annotated["library_id"] = card.get("library_id", annotated.get("library_id", ""))
    annotated["library_shelf"] = card.get("shelf", annotated.get("library_shelf", ""))
    annotated["matched_by"] = card.get("matched_by", annotated.get("matched_by", []))
    annotated["rank_reason"] = card.get("rank_reason", annotated.get("rank_reason", ""))
    annotated["typed_graph"] = card.get("typed_graph", annotated.get("typed_graph", {}))
    return annotated


def _query_payload_from_items(
    *,
    query: str,
    consumer: str,
    request_id: str,
    effective_source_system: str,
    scope: Dict[str, Any],
    effective_window_id: str,
    effective_session_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
    binding: Dict[str, Any],
    binding_applied_fields: List[str],
    active_layers_used: List[str],
    items: List[Dict[str, Any]],
    injection_boundary: str,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    source_refs_count = sum(1 for i in items if i.get('source_path'))
    raw_items_count = sum(1 for i in items if _is_raw_evidence_status(i.get('raw_evidence_status', '')))
    tiandao_context_package = _build_tiandao_context_package(
        query=query,
        source_system=effective_source_system,
        consumer=consumer,
        canonical_window_id=effective_window_id,
        session_id=effective_session_id,
        items=items,
        memory_scope=scope["memory_scope"],
        memory_base_scope=scope["memory_base_scope"],
        scope_missing=False,
        active_layers_used=active_layers_used,
        binding=binding,
        binding_applied_fields=binding_applied_fields,
        cross_window_read=scope["cross_window_read"],
        cross_window_read_allowed=scope["cross_window_read_allowed"],
        injection_boundary=injection_boundary,
    )
    payload = {
        'ok': True,
        'consumer': consumer or 'unknown',
        'query': query,
        'source_system_filter': effective_source_system or 'all',
        'requested_source_system': scope["requested_source_system"],
        'inferred_source_system': scope["inferred_source_system"],
        'memory_scope': scope["memory_scope"],
        'memory_base_scope': scope["memory_base_scope"],
        'scope_missing': False,
        'missing_scope_fields': [],
        'cross_window_read': scope["cross_window_read"],
        'cross_window_read_allowed': scope["cross_window_read_allowed"],
        'hermes_global_exception': scope["hermes_global_exception"],
        'hermes_plain_recall_is_global_exception': scope.get("hermes_plain_recall_is_global_exception", False),
        'hermes_broad_context_workflow': scope.get("hermes_broad_context_workflow", False),
        'cross_window_reason': scope.get("cross_window_reason", ""),
        'canonical_window_id_filter': effective_window_id,
        'project_id_filter': project_id,
        'project_root_filter': project_root,
        'workstream_id_filter': workstream_id,
        'task_id_filter': task_id,
        'current_window_binding_applied': bool(binding_applied_fields),
        'current_window_binding_key': binding.get("binding_key", "") if binding else "",
        'current_window_binding_fields': binding_applied_fields,
        'active_layers_used': active_layers_used,
        'agent_boundary': 'active_window_first_explicit_broad_scope',
        'injection_boundary': injection_boundary,
        'tiandao_context_package': tiandao_context_package,
        'tiandao_context_package_valid': tiandao_context_package.get("validation", {}).get("valid", True),
        'zhixing_library': library_manifest(),
        'hybrid_recall': hybrid_recall_manifest(),
        'matched_count': len(items),
        'source_refs_count': source_refs_count,
        'raw_items_count': raw_items_count,
        'items': items,
        'raw_evidence_status': 'raw' if raw_items_count > 0 else 'not_raw',
        'zhiyi_experience_used_as_raw': False,
        'consumer_receipt': _consumer_receipt(
            consumer,
            request_id,
            len(items),
            source_refs_count,
            raw_items_count,
            items,
        ),
    }
    if extra:
        payload.update(extra)
    return payload


def query_raw_source_refs(
    query: str,
    source_system: str = '',
    computer_name: str = '',
    session_id: str = '',
    limit: int = 5,
    excerpt_chars: int = 300,
    consumer: str = '',
    request_id: str = '',
    memory_scope: str = '',
    canonical_window_id: str = '',
    allow_cross_window_recall: bool = False,
    cross_window_reason: str = '',
    project_id: str = '',
    project_root: str = '',
    workstream_id: str = '',
    task_id: str = '',
    fast_window_preflight: bool = False,
) -> Dict[str, Any]:
    limit = _safe_int(str(limit), 5, 1, MAX_LIMIT)
    excerpt_chars = _safe_int(str(excerpt_chars), 300, 1, MAX_EXCERPT)
    consumer = _clean_text(consumer)
    source_system = _clean_text(source_system)
    computer_name = _clean_text(computer_name)
    canonical_window_id = _clean_text(canonical_window_id)
    session_id = _clean_text(session_id)
    project_id = _clean_text(project_id)
    project_root = _clean_text(project_root)
    workstream_id = _clean_text(workstream_id)
    task_id = _clean_text(task_id)
    binding = _current_window_binding_anchor(source_system, consumer)
    binding_meta = _binding_metadata(binding)
    binding_applied_fields: List[str] = []
    if binding:
        if not source_system and _clean_text(binding.get("source_system")):
            source_system = _clean_text(binding.get("source_system"))
            binding_applied_fields.append("source_system")
        if not canonical_window_id and _clean_text(binding.get("canonical_window_id")):
            canonical_window_id = _clean_text(binding.get("canonical_window_id"))
            binding_applied_fields.append("canonical_window_id")
        if not session_id and _clean_text(binding.get("session_id")):
            session_id = _clean_text(binding.get("session_id"))
            binding_applied_fields.append("session_id")
        if not project_id:
            value = _first_text(binding.get("project_id"), binding_meta.get("project_id"))
            if value:
                project_id = value
                binding_applied_fields.append("project_id")
        if not project_root:
            value = _first_text(
                binding.get("project_root"),
                binding.get("workspace_root"),
                binding.get("cwd"),
                binding_meta.get("project_root"),
                binding_meta.get("workspace_root"),
                binding_meta.get("cwd"),
            )
            if value:
                project_root = value
                binding_applied_fields.append("project_root")
        if not workstream_id:
            value = _first_text(binding.get("workstream_id"), binding.get("workstream"), binding_meta.get("workstream_id"), binding_meta.get("workstream"))
            if value:
                workstream_id = value
                binding_applied_fields.append("workstream_id")
        if not task_id:
            value = _first_text(binding.get("task_id"), binding.get("task"), binding_meta.get("task_id"), binding_meta.get("task"))
            if value:
                task_id = value
                binding_applied_fields.append("task_id")
    scope = _resolve_recall_scope(
        source_system=source_system,
        consumer=consumer,
        memory_scope=memory_scope,
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        allow_cross_window_recall=allow_cross_window_recall,
        cross_window_reason=cross_window_reason,
    )
    effective_source_system = scope["effective_source_system"]
    effective_session_id = scope["session_id"]
    effective_window_id = scope["canonical_window_id"]
    active_scope = scope["memory_scope"] == "active"
    recall_session_filter = "" if active_scope else effective_session_id
    recall_window_filter = "" if active_scope else effective_window_id
    recall_limit = (
        min(ACTIVE_RECALL_CANDIDATE_MAX, max(limit * 8, limit))
        if active_scope
        else limit
    )

    if scope["scope_missing"]:
        scope_status = _scope_missing_status(scope)
        injection_boundary = 'window_scope_required_for_default_recall'
        tiandao_context_package = _build_tiandao_context_package(
            query=query,
            source_system=effective_source_system,
            consumer=consumer,
            canonical_window_id=effective_window_id,
            session_id=effective_session_id,
            items=[],
            memory_scope=scope["memory_scope"],
            memory_base_scope=scope["memory_base_scope"],
            scope_missing=True,
            active_layers_used=[],
            binding=binding,
            binding_applied_fields=binding_applied_fields,
            cross_window_read=scope["cross_window_read"],
            cross_window_read_allowed=scope["cross_window_read_allowed"],
            injection_boundary=injection_boundary,
            block_reason=scope_status["recall_status"],
        )
        return {
            'ok': True,
            'consumer': consumer or 'unknown',
            'query': query,
            'source_system_filter': effective_source_system or 'unresolved',
            'requested_source_system': scope["requested_source_system"],
            'inferred_source_system': scope["inferred_source_system"],
            'memory_scope': scope["memory_scope"],
            'memory_base_scope': scope["memory_base_scope"],
            'scope_missing': True,
            'recall_status': scope_status["recall_status"],
            'window_binding_hint': scope_status["window_binding_hint"],
            'missing_scope_fields': scope["missing_scope_fields"],
            'cross_window_read': scope["cross_window_read"],
            'cross_window_read_allowed': scope["cross_window_read_allowed"],
            'hermes_global_exception': scope["hermes_global_exception"],
            'hermes_plain_recall_is_global_exception': scope.get("hermes_plain_recall_is_global_exception", False),
            'hermes_broad_context_workflow': scope.get("hermes_broad_context_workflow", False),
            'cross_window_reason': scope.get("cross_window_reason", ""),
            'canonical_window_id_filter': effective_window_id,
            'project_id_filter': project_id,
            'project_root_filter': project_root,
            'workstream_id_filter': workstream_id,
            'task_id_filter': task_id,
            'current_window_binding_applied': bool(binding_applied_fields),
            'current_window_binding_key': binding.get("binding_key", "") if binding else "",
            'current_window_binding_fields': binding_applied_fields,
            'active_layers_used': [],
            'agent_boundary': 'active_window_first_explicit_broad_scope',
            'injection_boundary': injection_boundary,
            'tiandao_context_package': tiandao_context_package,
            'tiandao_context_package_valid': tiandao_context_package.get("validation", {}).get("valid", True),
            'zhixing_library': library_manifest(),
            'hybrid_recall': hybrid_recall_manifest(),
            'matched_count': 0,
            'source_refs_count': 0,
            'raw_items_count': 0,
            'items': [],
            'recall_performed': False,
            'raw_excerpt_returned': False,
            'raw_evidence_status': 'not_raw',
            'zhiyi_experience_used_as_raw': False,
            'consumer_receipt': _consumer_receipt(
                consumer,
                request_id,
                0,
                0,
                0,
                [],
            ),
        }

    if (
        fast_window_preflight
        and scope["memory_scope"] == "window"
        and (effective_window_id or effective_session_id)
        and not scope["cross_window_read"]
    ):
        indexed_items, index_status = _query_canonical_window_index(
            query=query or '',
            source_system=effective_source_system or '',
            session_id=effective_session_id or '',
            canonical_window_id=effective_window_id or '',
            limit=limit,
            excerpt_chars=excerpt_chars,
        )
        items = [_annotate_gateway_item(item, query or '') for item in indexed_items]
        active_layers_used = ["current_window"] if items else []
        return _query_payload_from_items(
            query=query,
            consumer=consumer,
            request_id=request_id,
            effective_source_system=effective_source_system,
            scope=scope,
            effective_window_id=effective_window_id,
            effective_session_id=effective_session_id,
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
            binding=binding,
            binding_applied_fields=binding_applied_fields,
            active_layers_used=active_layers_used,
            items=items,
            injection_boundary='explicit_window_scope',
            extra={
                'recall_performed': bool(items),
                'raw_excerpt_returned': bool(items),
                'fast_window_preflight': True,
                'fast_recall_path': 'canonical_window_index',
                'fast_window_index_status': index_status,
                'zhiyi_layer_skipped_for_fast_preflight': True,
            },
        )

    handle_recall = _load_handle_recall()
    result = handle_recall({
        'query': query or '',
        'scope_filter': '',
        'type_filter': [],
        'top_k': recall_limit,
        'recall_mode': 'substring',
        'source_system_filter': effective_source_system,
        'computer_name_filter': computer_name,
        'session_id_filter': recall_session_filter,
        'canonical_window_id_filter': recall_window_filter,
    })
    matched = result.get('matched_memories', []) or []

    items = []
    for m in matched:
        sr = _json_loads_maybe(m.get('source_refs', {}))
        sr_source_system = sr.get('source_system', '')
        sr_computer_name = sr.get('computer_name', '') or sr.get('computer_id', '')
        sr_session_id = sr.get('session_id', '')
        sr_window_id = sr.get('canonical_window_id', '') or m.get('canonical_window_id', '')
        sr_legacy_window_id = sr.get('source_refs_canonical_window_id', '') or m.get('source_refs_canonical_window_id', '')
        sr_project_id = _first_text(sr.get('project_id'), m.get('project_id'))
        if sr_source_system in SESSION_WINDOW_ID_SOURCE_SYSTEMS and sr_session_id:
            if sr_window_id and sr_window_id != sr_session_id:
                sr_legacy_window_id = sr_legacy_window_id or sr_window_id
            if not sr_project_id and sr_legacy_window_id:
                sr_project_id = sr_legacy_window_id
            sr_window_id = sr_session_id
        sr_project_root = _first_text(
            sr.get('project_root'),
            sr.get('workspace_root'),
            sr.get('cwd'),
            m.get('project_root'),
            m.get('workspace_root'),
            m.get('cwd'),
        )
        sr_workstream_id = _first_text(
            sr.get('workstream_id'),
            sr.get('workstream'),
            m.get('workstream_id'),
            m.get('workstream'),
        )
        sr_task_id = _first_text(
            sr.get('task_id'),
            sr.get('task'),
            m.get('task_id'),
            m.get('task'),
        )

        if effective_source_system and sr_source_system != effective_source_system:
            continue
        if computer_name and sr_computer_name != computer_name:
            continue
        if recall_session_filter and sr_session_id != recall_session_filter:
            continue
        session_matched = bool(recall_session_filter and sr_session_id == recall_session_filter)
        window_matched = bool(
            recall_window_filter
            and (
                sr_window_id == recall_window_filter
                or sr_legacy_window_id == recall_window_filter
                or sr_project_id == recall_window_filter
            )
        )
        if recall_window_filter and not session_matched and not window_matched:
            continue

        source_path = sr.get('source_path', '')
        msg_ids = sr.get('msg_ids', []) or []
        raw_excerpt, raw_status, evidence_hash = _extract_bounded_raw_excerpt(source_path, msg_ids, excerpt_chars, sr)
        xingce_meta = m.get('_xingce', {}) if isinstance(m.get('_xingce'), dict) else {}
        project_status_meta = m.get('_project_status', {}) if isinstance(m.get('_project_status'), dict) else {}
        if project_status_meta and not raw_excerpt:
            status_excerpt_chars = max(excerpt_chars, PROJECT_STATUS_EXCERPT_CHARS)
            raw_excerpt = str(m.get('injectable_context') or m.get('summary') or '')[:status_excerpt_chars]
            raw_status = 'artifact'
            evidence_hash = hashlib.sha256(raw_excerpt.encode('utf-8')).hexdigest() if raw_excerpt else None
        item = {
            'type': m.get('type', '') or m.get('_type', ''),
            'memory_type': m.get('type', '') or m.get('_type', ''),
            'exp_id': m.get('exp_id', ''),
            'summary': str(m.get('summary') or '')[:800],
            'should_inject': bool(m.get('should_inject', False)),
            'confidence': m.get('confidence'),
            'source_system': sr_source_system,
            'computer_name': sr_computer_name,
            'canonical_window_id': sr_window_id,
            'session_id': sr_session_id,
            'project_id': sr_project_id,
            'project_root': sr_project_root,
            'workstream_id': sr_workstream_id,
            'task_id': sr_task_id,
            'native_session_key': sr_session_id or m.get('exp_id', ''),
            'source_path': source_path,
            'msg_ids': msg_ids,
            'raw_excerpt': raw_excerpt,
            'evidence_hash': evidence_hash,
            'created_at': ts(),
            'raw_evidence_status': raw_status if source_path else 'not_raw',
            'zhiyi_experience_used_as_raw': False,
        }
        if sr_legacy_window_id:
            item['source_refs_canonical_window_id'] = sr_legacy_window_id
        if xingce_meta:
            item['xingce_candidate'] = {
                'candidate_id': xingce_meta.get('candidate_id', ''),
                'candidate_type': xingce_meta.get('candidate_type', ''),
                'action_status': xingce_meta.get('action_status', ''),
                'lifecycle_status': xingce_meta.get('lifecycle_status', ''),
                'production_experience_write_performed': bool(xingce_meta.get('production_experience_write_performed', False)),
                'raw_write_performed': bool(xingce_meta.get('raw_write_performed', False)),
                'zhiyi_write_performed': bool(xingce_meta.get('zhiyi_write_performed', False)),
                'xingce_write_performed': bool(xingce_meta.get('xingce_write_performed', False)),
                'hermes_write_performed': bool(xingce_meta.get('hermes_write_performed', False)),
                'openclaw_write_performed': bool(xingce_meta.get('openclaw_write_performed', False)),
                'work_experience': m.get('work_experience', {}),
            }
        if project_status_meta:
            item['project_status'] = {
                'status_id': project_status_meta.get('status_id', ''),
                'artifact_type': project_status_meta.get('artifact_type', ''),
                'status': project_status_meta.get('status', ''),
                'project': project_status_meta.get('project', ''),
                'skill_artifact_status': project_status_meta.get('skill_artifact_status', ''),
                'probe_id': project_status_meta.get('probe_id', ''),
                'probe_receipt_path': project_status_meta.get('probe_receipt_path', ''),
                'skill_relative_path': project_status_meta.get('skill_relative_path', ''),
                'skill_path': project_status_meta.get('skill_path', ''),
                'skill_sha256': project_status_meta.get('skill_sha256', ''),
                'status_receipt_write_performed': bool(project_status_meta.get('status_receipt_write_performed', False)),
                'production_experience_write_performed': bool(project_status_meta.get('production_experience_write_performed', False)),
                'raw_write_performed': bool(project_status_meta.get('raw_write_performed', False)),
                'zhiyi_write_performed': bool(project_status_meta.get('zhiyi_write_performed', False)),
                'xingce_write_performed': bool(project_status_meta.get('xingce_write_performed', False)),
                'hermes_write_performed': bool(project_status_meta.get('hermes_write_performed', False)),
                'hermes_skill_write_performed_by_yifanchen': bool(project_status_meta.get('hermes_skill_write_performed_by_yifanchen', False)),
                'openclaw_write_performed': bool(project_status_meta.get('openclaw_write_performed', False)),
            }
        items.append(_annotate_gateway_item(item, query or ''))
        if len(items) >= limit:
            if active_scope:
                continue
            break

    candidate_target = recall_limit if active_scope else limit
    active_preview_count = 0
    if active_scope:
        active_preview, _ = _apply_active_layered_routing(
            items,
            limit=limit,
            session_id=effective_session_id,
            canonical_window_id=effective_window_id,
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
        )
        active_preview_count = len(active_preview)
    needs_more_candidates = (
        active_preview_count < limit
        if active_scope
        else len(items) < limit
    )
    has_project_status = any(
        item.get('memory_type') == 'yifanchen_project_status' for item in items
    )
    if needs_more_candidates and not has_project_status and effective_source_system in ('', 'hermes'):
        remaining = max(limit, candidate_target - len(items))
        items.extend(
            _annotate_gateway_item(item, query or '')
            for item in _query_hermes_state_db(
            query=query or '',
            computer_name=computer_name or '',
            session_id=recall_session_filter or '',
            limit=remaining,
            excerpt_chars=excerpt_chars,
            )
        )

    if needs_more_candidates or not any(_is_raw_evidence_status(item.get('raw_evidence_status', '')) for item in items):
        existing_raw_keys = {
            (str(item.get("source_path", "")), tuple(item.get("msg_ids") or []), str(item.get("raw_excerpt", "")))
            for item in items
        }
        remaining = max(limit, candidate_target - len(items))
        for fallback_item in _query_raw_jsonl_fallback(
            query=query or '',
            source_system=effective_source_system or '',
            computer_name=computer_name or '',
            session_id=recall_session_filter or '',
            canonical_window_id=recall_window_filter or '',
            limit=remaining,
            excerpt_chars=excerpt_chars,
        ):
            key = (
                str(fallback_item.get("source_path", "")),
                tuple(fallback_item.get("msg_ids") or []),
                str(fallback_item.get("raw_excerpt", "")),
            )
            if key in existing_raw_keys:
                continue
            items.append(_annotate_gateway_item(fallback_item, query or ''))
            existing_raw_keys.add(key)
            if len(items) >= candidate_target:
                break

    active_layers_used: List[str] = []
    if active_scope:
        items, active_layers_used = _apply_active_layered_routing(
            items,
            limit=limit,
            session_id=effective_session_id,
            canonical_window_id=effective_window_id,
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
        )
    elif len(items) > limit:
        items = items[:limit]

    source_refs_count = sum(1 for i in items if i.get('source_path'))
    raw_items_count = sum(1 for i in items if _is_raw_evidence_status(i.get('raw_evidence_status', '')))
    injection_boundary = (
        'explicit_window_scope'
        if scope["memory_scope"] == 'window'
        else 'active_layered_source_refs_only'
        if scope["memory_scope"] == 'active'
        else 'source_refs_only_no_cross_agent_window_write'
    )
    tiandao_context_package = _build_tiandao_context_package(
        query=query,
        source_system=effective_source_system,
        consumer=consumer,
        canonical_window_id=effective_window_id,
        session_id=effective_session_id,
        items=items,
        memory_scope=scope["memory_scope"],
        memory_base_scope=scope["memory_base_scope"],
        scope_missing=False,
        active_layers_used=active_layers_used,
        binding=binding,
        binding_applied_fields=binding_applied_fields,
        cross_window_read=scope["cross_window_read"],
        cross_window_read_allowed=scope["cross_window_read_allowed"],
        injection_boundary=injection_boundary,
    )
    return {
        'ok': True,
        'consumer': consumer or 'unknown',
        'query': query,
        'source_system_filter': effective_source_system or 'all',
        'requested_source_system': scope["requested_source_system"],
        'inferred_source_system': scope["inferred_source_system"],
        'memory_scope': scope["memory_scope"],
        'memory_base_scope': scope["memory_base_scope"],
        'scope_missing': False,
        'missing_scope_fields': [],
        'cross_window_read': scope["cross_window_read"],
        'cross_window_read_allowed': scope["cross_window_read_allowed"],
        'hermes_global_exception': scope["hermes_global_exception"],
        'hermes_plain_recall_is_global_exception': scope.get("hermes_plain_recall_is_global_exception", False),
        'hermes_broad_context_workflow': scope.get("hermes_broad_context_workflow", False),
        'cross_window_reason': scope.get("cross_window_reason", ""),
        'canonical_window_id_filter': effective_window_id,
        'project_id_filter': project_id,
        'project_root_filter': project_root,
        'workstream_id_filter': workstream_id,
        'task_id_filter': task_id,
        'current_window_binding_applied': bool(binding_applied_fields),
        'current_window_binding_key': binding.get("binding_key", "") if binding else "",
        'current_window_binding_fields': binding_applied_fields,
        'active_layers_used': active_layers_used,
        'agent_boundary': 'active_window_first_explicit_broad_scope',
        'injection_boundary': injection_boundary,
        'tiandao_context_package': tiandao_context_package,
        'tiandao_context_package_valid': tiandao_context_package.get("validation", {}).get("valid", True),
        'zhixing_library': library_manifest(),
        'hybrid_recall': hybrid_recall_manifest(),
        'matched_count': len(items),
        'source_refs_count': source_refs_count,
        'raw_items_count': raw_items_count,
        'items': items,
        'raw_evidence_status': 'raw' if raw_items_count > 0 else 'not_raw',
        'zhiyi_experience_used_as_raw': False,
        'consumer_receipt': _consumer_receipt(
            consumer,
            request_id,
            len(items),
            source_refs_count,
            raw_items_count,
            items,
        ),
    }


def health_payload() -> Dict[str, Any]:
    source_path = _service_source_path()
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "port": PORT,
        "loopback_only": True,
        "read_only": True,
        "write_performed": False,
        "production_write_performed": False,
        "state_dir_guard": True,
        "raw_query_path": "/api/v1/raw/query",
        "raw_query_methods": ["GET", "POST"],
        "mcp_path": "/mcp",
        "mcp_tools": ["zhiyi_recall"],
        "capability_check": True,
        "capability_check_modes": ["mode=capability_check", "capability_check=true"],
        "preflight": True,
        "preflight_modes": ["mode=preflight"],
        "consumer_receipt": True,
        "identity_contract": HEALTH_IDENTITY_CONTRACT,
        "source_path": str(source_path),
        "source_sha256": _service_source_sha256(source_path),
        "zhixing_library": library_manifest(),
    }


def active_memory_routing_status() -> Dict[str, Any]:
    return _active_memory_routing_status()


def mcp_tools_payload() -> Dict[str, Any]:
    return {
        "tools": [
            {
                "name": "zhiyi_recall",
                "description": (
                    "Read Memcore Cloud Zhiyi source-backed local memory. "
                    "Returns compact catalog/source refs by default; raw excerpts require "
                    "response_budget=raw or include_raw_excerpt=true. "
                    "Use mode=preflight before task answers to surface compact Zhiyi/Xingce guidance. "
                    "Use mode=capability_check for install smoke tests without recall. Read-only."
                ),
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Recall query or continuation request.",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["recall", "raw", "preflight", "capability_check"],
                            "description": "Use preflight before task answers; use capability_check to verify tool availability without querying memory.",
                        },
                        "response_budget": {
                            "type": "string",
                            "enum": ["compact", "standard", "raw"],
                            "description": "Default compact omits raw excerpts; raw returns full source-backed evidence fields.",
                        },
                        "include_raw_excerpt": {
                            "type": "boolean",
                            "description": "Explicitly include bounded raw excerpts in recall items. Default false.",
                        },
                        "capability_check": {
                            "type": "boolean",
                            "description": "When true, reports Skill/MCP/read-only capability without recall or raw excerpts.",
                        },
                        "no_recall": {
                            "type": "boolean",
                            "description": "Alias for capability_check, intended for smoke tests.",
                        },
                        "source_system": {
                            "type": "string",
                            "description": "Optional source filter such as openclaw, hermes, codex, or claude_desktop.",
                        },
                        "memory_scope": {
                            "type": "string",
                            "enum": ["active", "window", "platform", "raw_pool", "shared", "dual"],
                            "description": "Default active recall is window-first, then same project/workspace, same workstream/task, and stable preferences/tool facts. raw_pool/shared is explicit.",
                        },
                        "canonical_window_id": {"type": "string"},
                        "computer_name": {"type": "string"},
                        "session_id": {"type": "string"},
                        "project_id": {
                            "type": "string",
                            "description": "Optional project/workspace id for active layered continuation.",
                        },
                        "project_root": {
                            "type": "string",
                            "description": "Optional local project/workspace root for active layered continuation.",
                        },
                        "workstream_id": {
                            "type": "string",
                            "description": "Optional task/workstream id for active layered continuation.",
                        },
                        "task_id": {
                            "type": "string",
                            "description": "Optional task id for active layered continuation.",
                        },
                        "allow_cross_window_recall": {
                            "type": "boolean",
                            "description": "Required for ordinary raw_pool/shared recall so a normal client, including normal Hermes recall, does not silently read another window.",
                        },
                        "cross_window_reason": {
                            "type": "string",
                            "enum": sorted(HERMES_BROAD_CONTEXT_WORKFLOWS),
                            "description": "Explicit workflow reason for narrow exceptions such as Hermes skill generation or self-review.",
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                        "excerpt_chars": {"type": "integer", "minimum": 1, "maximum": MAX_EXCERPT},
                        "consumer": {"type": "string"},
                        "request_id": {"type": "string"},
                    },
                    "required": ["query"],
                },
            }
        ]
    }


def _mcp_response_id(request_id: Any) -> str | int | float:
    if isinstance(request_id, bool):
        return "unknown"
    if isinstance(request_id, (str, int, float)):
        return request_id
    return "unknown"


def mcp_success(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": _mcp_response_id(request_id), "result": result}


def mcp_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": _mcp_response_id(request_id), "error": {"code": code, "message": message}}


def _mcp_request_id(data: Any) -> Any:
    if not isinstance(data, dict):
        return None
    request_id = data.get("id")
    if isinstance(request_id, bool):
        return None
    if isinstance(request_id, (str, int, float)) or request_id is None:
        return request_id
    return None


def mcp_call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name != "zhiyi_recall":
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        }
    args = arguments if isinstance(arguments, dict) else {}
    if _is_capability_check_request(args):
        result = capability_check_payload(
            consumer=str(args.get("consumer") or "mcp"),
            request_id=str(args.get("request_id") or ""),
            source="mcp",
        )
    elif _is_preflight_request(args):
        result = preflight_payload(
            query=str(args.get("query") or ""),
            source_system=str(args.get("source_system") or ""),
            computer_name=str(args.get("computer_name") or ""),
            session_id=str(args.get("session_id") or ""),
            limit=args.get("limit", 3),
            excerpt_chars=args.get("excerpt_chars", 180),
            consumer=str(args.get("consumer") or "mcp"),
            request_id=str(args.get("request_id") or ""),
            memory_scope=str(args.get("memory_scope") or ""),
            canonical_window_id=str(args.get("canonical_window_id") or ""),
            allow_cross_window_recall=_truthy(args.get("allow_cross_window_recall")),
            cross_window_reason=str(args.get("cross_window_reason") or args.get("workflow_reason") or ""),
            project_id=str(args.get("project_id") or ""),
            project_root=str(args.get("project_root") or args.get("workspace_root") or args.get("cwd") or ""),
            workstream_id=str(args.get("workstream_id") or args.get("workstream") or ""),
            task_id=str(args.get("task_id") or args.get("task") or ""),
        )
    else:
        result = query_raw_source_refs(
            query=str(args.get("query") or ""),
            source_system=str(args.get("source_system") or ""),
            computer_name=str(args.get("computer_name") or ""),
            session_id=str(args.get("session_id") or ""),
            limit=args.get("limit", 5),
            excerpt_chars=args.get("excerpt_chars", 300),
            consumer=str(args.get("consumer") or "mcp"),
            request_id=str(args.get("request_id") or ""),
            memory_scope=str(args.get("memory_scope") or ""),
            canonical_window_id=str(args.get("canonical_window_id") or ""),
            allow_cross_window_recall=_truthy(args.get("allow_cross_window_recall")),
            cross_window_reason=str(args.get("cross_window_reason") or args.get("workflow_reason") or ""),
            project_id=str(args.get("project_id") or ""),
            project_root=str(args.get("project_root") or args.get("workspace_root") or args.get("cwd") or ""),
            workstream_id=str(args.get("workstream_id") or args.get("workstream") or ""),
            task_id=str(args.get("task_id") or args.get("task") or ""),
        )
        result = compact_recall_payload(
            result,
            response_budget_mode=_response_budget_mode(args),
            include_raw_excerpt=_include_raw_excerpt(args),
        )
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False),
            }
        ],
        "structuredContent": result,
        "isError": False,
    }


def handle_mcp_request(data: Dict[str, Any]) -> Dict[str, Any] | None:
    request_id = _mcp_request_id(data)
    method = str(data.get("method") or "")
    params = data.get("params", {}) if isinstance(data.get("params"), dict) else {}

    if method == "initialize":
        return mcp_success(request_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "yifanchen-zhiyi", "version": SERVICE_VERSION},
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return mcp_success(request_id, mcp_tools_payload())
    if method == "tools/call":
        try:
            result = mcp_call_tool(
                str(params.get("name") or ""),
                params.get("arguments", {}) if isinstance(params.get("arguments"), dict) else {},
            )
        except Exception as exc:
            return mcp_error(
                request_id,
                -32603,
                f"Internal error while calling tool: {type(exc).__name__}: {exc}",
            )
        return mcp_success(request_id, result)
    if method == "ping":
        return mcp_success(request_id, {})
    return mcp_error(request_id, -32601, f"Method not found: {method}")


def _is_loopback_host(host: str) -> bool:
    raw = str(host or "").strip()
    if not raw:
        return False
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if raw.lower() == "localhost":
        return True
    try:
        parsed = ipaddress.ip_address(raw)
    except ValueError:
        return False
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped:
        return bool(mapped.is_loopback)
    return bool(parsed.is_loopback)


def _is_loopback_client(client_address: Any) -> bool:
    if isinstance(client_address, (list, tuple)) and client_address:
        return _is_loopback_host(str(client_address[0]))
    return _is_loopback_host(str(client_address or ""))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, data: Dict[str, Any], code: int = 200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def reject_non_loopback(self) -> bool:
        if _is_loopback_client(getattr(self, "client_address", None)):
            return False
        self.send_json({"ok": False, "error": "loopback clients only"}, 403)
        return True

    def do_GET(self):
        if self.reject_non_loopback():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json(health_payload())
            return
        if parsed.path == "/api/v1/memory-routing/status":
            self.send_json(active_memory_routing_status())
            return
        if parsed.path == "/mcp":
            self.send_json({
                "ok": True,
                "service": "yifanchen-zhiyi-mcp",
                "protocol": "jsonrpc",
                "transport": "streamable_http",
                "tools": mcp_tools_payload()["tools"],
            })
            return
        if parsed.path != '/api/v1/raw/query':
            self.send_json({'ok': False, 'error': 'not found'}, 404)
            return
        qs = parse_qs(parsed.query)
        query = (qs.get('query') or qs.get('q') or [''])[0]
        source_system = (qs.get('source_system') or [''])[0]
        memory_scope = (qs.get('memory_scope') or [''])[0]
        canonical_window_id = (qs.get('canonical_window_id') or [''])[0]
        computer_name = (qs.get('computer_name') or [''])[0]
        session_id = (qs.get('session_id') or [''])[0]
        limit = (qs.get('limit') or ['5'])[0]
        excerpt_chars = (qs.get('excerpt_chars') or ['300'])[0]
        consumer = (qs.get('consumer') or [''])[0]
        request_id = (qs.get('request_id') or [''])[0]
        mode = (qs.get('mode') or [''])[0]
        capability_check = (qs.get('capability_check') or [''])[0]
        no_recall = (qs.get('no_recall') or [''])[0]
        response_budget = (qs.get('response_budget') or qs.get('budget') or [''])[0]
        include_raw_excerpt = (qs.get('include_raw_excerpt') or qs.get('include_raw') or [''])[0]
        allow_cross_window_recall = (qs.get('allow_cross_window_recall') or [''])[0]
        cross_window_reason = (qs.get('cross_window_reason') or qs.get('workflow_reason') or [''])[0]
        project_id = (qs.get('project_id') or [''])[0]
        project_root = (qs.get('project_root') or qs.get('workspace_root') or qs.get('cwd') or [''])[0]
        workstream_id = (qs.get('workstream_id') or qs.get('workstream') or [''])[0]
        task_id = (qs.get('task_id') or qs.get('task') or [''])[0]
        if _is_capability_check_request({
            "mode": mode,
            "capability_check": capability_check,
            "no_recall": no_recall,
        }):
            self.send_json(capability_check_payload(consumer, request_id, "http_get"))
            return
        if _is_preflight_request({"mode": mode}):
            self.send_json(preflight_payload(
                query,
                source_system,
                computer_name,
                session_id,
                limit,
                excerpt_chars,
                consumer,
                request_id,
                memory_scope,
                canonical_window_id,
                _truthy(allow_cross_window_recall),
                cross_window_reason,
                project_id,
                project_root,
                workstream_id,
                task_id,
            ))
            return
        recall_args = {
            "mode": mode,
            "response_budget": response_budget,
            "include_raw_excerpt": include_raw_excerpt,
        }
        result = query_raw_source_refs(
            query,
            source_system,
            computer_name,
            session_id,
            limit,
            excerpt_chars,
            consumer,
            request_id,
            memory_scope,
            canonical_window_id,
            _truthy(allow_cross_window_recall),
            cross_window_reason,
            project_id,
            project_root,
            workstream_id,
            task_id,
        )
        self.send_json(compact_recall_payload(
            result,
            response_budget_mode=_response_budget_mode(recall_args),
            include_raw_excerpt=_include_raw_excerpt(recall_args),
        ))

    def do_POST(self):
        if self.reject_non_loopback():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            length = _safe_int(self.headers.get('Content-Length', '0'), 0, 0, 1024 * 1024)
            try:
                body = self.rfile.read(length).decode('utf-8') if length else '{}'
                data = json.loads(body) if body.strip() else {}
            except Exception:
                self.send_json(mcp_error(None, -32700, "Parse error"), 400)
                return
            if not isinstance(data, dict):
                self.send_json(mcp_error(None, -32600, "Invalid Request"), 400)
                return
            response = handle_mcp_request(data)
            if response is None:
                self.send_response(202)
                self.end_headers()
                return
            self.send_json(response)
            return
        if parsed.path != '/api/v1/raw/query':
            self.send_json({'ok': False, 'error': 'not found'}, 404)
            return
        length = _safe_int(self.headers.get('Content-Length', '0'), 0, 0, 1024 * 1024)
        try:
            body = self.rfile.read(length).decode('utf-8') if length else '{}'
            data = json.loads(body) if body.strip() else {}
        except Exception:
            self.send_json({'ok': False, 'error': 'invalid json'}, 400)
            return
        if not isinstance(data, dict):
            self.send_json({'ok': False, 'error': 'json body must be object'}, 400)
            return
        query = str(data.get('query') or data.get('q') or '')
        source_system = str(data.get('source_system') or '')
        memory_scope = str(data.get('memory_scope') or '')
        canonical_window_id = str(data.get('canonical_window_id') or '')
        computer_name = str(data.get('computer_name') or '')
        session_id = str(data.get('session_id') or '')
        project_id = str(data.get('project_id') or '')
        project_root = str(data.get('project_root') or data.get('workspace_root') or data.get('cwd') or '')
        workstream_id = str(data.get('workstream_id') or data.get('workstream') or '')
        task_id = str(data.get('task_id') or data.get('task') or '')
        limit = data.get('limit', 5)
        excerpt_chars = data.get('excerpt_chars', 300)
        consumer = str(data.get('consumer') or '')
        request_id = str(data.get('request_id') or '')
        if _is_capability_check_request(data):
            self.send_json(capability_check_payload(consumer, request_id, "http_post"))
            return
        if _is_preflight_request(data):
            self.send_json(preflight_payload(
                query,
                source_system,
                computer_name,
                session_id,
                limit,
                excerpt_chars,
                consumer,
                request_id,
                memory_scope,
                canonical_window_id,
                _truthy(data.get("allow_cross_window_recall")),
                str(data.get("cross_window_reason") or data.get("workflow_reason") or ""),
                project_id,
                project_root,
                workstream_id,
                task_id,
            ))
            return
        result = query_raw_source_refs(
            query,
            source_system,
            computer_name,
            session_id,
            limit,
            excerpt_chars,
            consumer,
            request_id,
            memory_scope,
            canonical_window_id,
            _truthy(data.get("allow_cross_window_recall")),
            str(data.get("cross_window_reason") or data.get("workflow_reason") or ""),
            project_id,
            project_root,
            workstream_id,
            task_id,
        )
        self.send_json(compact_recall_payload(
            result,
            response_budget_mode=_response_budget_mode(data),
            include_raw_excerpt=_include_raw_excerpt(data),
        ))


def run(port: int = PORT):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'[raw_consumption_gateway] running on http://127.0.0.1:{port}')
    server.serve_forever()


if __name__ == '__main__':
    run()
