#!/usr/bin/env python3
"""stdio bridge for Claude Desktop -> Time Library MCP.

Claude Desktop launches local MCP servers as child processes through
`claude_desktop_config.json`. Time Library's MCP endpoint is resolved through
the local front-door discovery file, so this bridge keeps Claude
Desktop on the official local-server shape while reusing the same read-only
current `time_library_recall` implementation and its migration alias.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

TOOLS_DIR = Path(__file__).resolve().parent
INSTALL_ROOT = TOOLS_DIR.parent
for _path in (str(INSTALL_ROOT), str(INSTALL_ROOT / "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    from src.port_discovery import resolve_client_url
except Exception:
    from port_discovery import resolve_client_url


DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_RECALL_LIMIT = 3
DEFAULT_RECALL_EXCERPT_CHARS = 240
MAX_COMPACT_ITEMS = 5
MAX_COMPACT_TEXT_CHARS = 1200
DEFAULT_BINDING_KEYS = ("claude_desktop", "claude_desktop_windows", "claude")
MCP_SESSION_REJECTION_CONTRACT = "time_library.mcp_session_rejection.v1"
MCP_RESUME_REJECTION_CONTRACT = "time_library.mcp_resume_rejection.v1"
PLATFORM_SELF_REPORT_RECEIPT_CONTRACT = "time_library_platform_self_report_receipt.v1"
HOST_CONNECTION_RECEIPT_CONTRACT = "time_library.host_connection_receipt.v1"
SESSION_RECOVERY_BACKOFF_MAX_SECONDS = 30.0


def _log(message: str) -> None:
    print(f"[time_library-claude-mcp] {message}", file=sys.stderr, flush=True)


def _read_message() -> dict[str, Any] | None:
    first = sys.stdin.buffer.readline()
    if not first:
        return None
    if first.startswith(b"Content-Length:"):
        try:
            length = int(first.split(b":", 1)[1].strip())
        except Exception:
            return {"jsonrpc": "2.0", "id": None, "method": "__parse_error__"}
        while True:
            line = sys.stdin.buffer.readline()
            if line in {b"\r\n", b"\n", b""}:
                break
        raw = sys.stdin.buffer.read(length)
    else:
        raw = first
    try:
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {"jsonrpc": "2.0", "id": None, "method": "__invalid_request__"}
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "method": "__parse_error__"}


def _write_message(data: dict[str, Any]) -> None:
    payload = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    stdout_buffer = getattr(sys.stdout, "buffer", None)
    if stdout_buffer is not None:
        stdout_buffer.write(payload)
        stdout_buffer.flush()
        return
    sys.stdout.write(payload.decode("utf-8"))
    sys.stdout.flush()


def _mcp_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": _response_id(request_id), "error": {"code": code, "message": message}}


class _McpHttpSession:
    def __init__(self) -> None:
        self.endpoint = ""
        self.session_id = ""
        self.resume_session_id = ""
        self.initialize_request: dict[str, Any] | None = None
        self.initialized_notification: dict[str, Any] | None = None
        self.verified_connection = False
        self.recovery_failures = 0
        self.next_recovery_at = 0.0

    @staticmethod
    def _clone_request(data: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(data, ensure_ascii=False))

    def set_endpoint(self, endpoint: str) -> bool:
        changed = endpoint != self.endpoint
        if changed:
            self.endpoint = endpoint
            self.session_id = ""
            self.resume_session_id = ""
            self.verified_connection = False
            self.recovery_failures = 0
            self.next_recovery_at = 0.0
        return changed

    def remember_request(self, data: dict[str, Any]) -> None:
        method = str(data.get("method") or "")
        if method == "initialize":
            self.initialize_request = self._clone_request(data)
            self.initialized_notification = None
            self.session_id = ""
            self.resume_session_id = ""
            self.verified_connection = False
            self.recovery_failures = 0
            self.next_recovery_at = 0.0
        elif method == "notifications/initialized":
            self.initialized_notification = self._clone_request(data)

    def clear_session(self, endpoint: str, *, preserve_for_resume: bool = True) -> None:
        if preserve_for_resume and self.session_id:
            self.resume_session_id = self.session_id
        elif not preserve_for_resume:
            self.resume_session_id = ""
        self.endpoint = endpoint
        self.session_id = ""

    def recovery_session(self) -> str:
        return self.resume_session_id or self.session_id

    def can_recover(self) -> bool:
        return time.monotonic() >= self.next_recovery_at

    def mark_recovery_failure(self, endpoint: str, *, preserve_resume: bool = True) -> None:
        self.clear_session(endpoint, preserve_for_resume=preserve_resume)
        self.recovery_failures += 1
        delay = min(
            SESSION_RECOVERY_BACKOFF_MAX_SECONDS,
            0.5 * (2 ** min(self.recovery_failures - 1, 6)),
        )
        self.next_recovery_at = time.monotonic() + delay

    def mark_recovery_success(self) -> None:
        self.resume_session_id = ""
        self.recovery_failures = 0
        self.next_recovery_at = 0.0

    def require_reverification(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.session_id = ""
        self.resume_session_id = ""
        self.verified_connection = False
        self.recovery_failures = 0
        self.next_recovery_at = 0.0

    def request_headers(self, endpoint: str) -> dict[str, str]:
        self.set_endpoint(endpoint)
        return {"Mcp-Session-Id": self.session_id} if self.session_id else {}

    def observe(self, endpoint: str, headers: Any) -> None:
        self.set_endpoint(endpoint)
        session_id = str(headers.get("Mcp-Session-Id") or "").strip() if headers is not None else ""
        if session_id:
            self.session_id = session_id

    def observe_response(
        self,
        request: dict[str, Any],
        response: dict[str, Any] | None,
    ) -> None:
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if not (
            request.get("method") == "tools/call"
            and params.get("name") == "time_library_reading_area"
            and arguments.get("action") == "self_report_connect"
            and isinstance(response, dict)
            and self.session_id
        ):
            return
        result = response.get("result") if isinstance(response.get("result"), dict) else {}
        structured = (
            result.get("structuredContent")
            if isinstance(result.get("structuredContent"), dict)
            else {}
        )
        connection_receipt = (
            structured.get("connection_receipt")
            if isinstance(structured.get("connection_receipt"), dict)
            else {}
        )
        session_sha256 = hashlib.sha256(self.session_id.encode("utf-8")).hexdigest()
        if (
            structured.get("contract") == PLATFORM_SELF_REPORT_RECEIPT_CONTRACT
            and structured.get("self_report_verified") is True
            and connection_receipt.get("ok") is True
            and connection_receipt.get("contract") == HOST_CONNECTION_RECEIPT_CONTRACT
            and connection_receipt.get("transport_session_sha256") == session_sha256
        ):
            self.verified_connection = True


def _valid_response_id(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (str, int, float))


def _response_id(value: Any) -> str | int | float:
    return value if _valid_response_id(value) else "unknown"


def _coerce_error_code(value: Any, fallback: int = -32603) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except Exception:
        return fallback


def _is_jsonrpc_response(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("jsonrpc") != "2.0":
        return False
    if not _valid_response_id(value.get("id")):
        return False
    has_result = "result" in value
    has_error = "error" in value
    if has_result == has_error:
        return False
    if has_error:
        error = value.get("error")
        return (
            isinstance(error, dict)
            and not isinstance(error.get("code"), bool)
            and isinstance(error.get("code"), int)
            and isinstance(error.get("message"), str)
        )
    return True


def _normalize_jsonrpc_response(value: Any, request_id: Any, fallback_message: str) -> dict[str, Any]:
    if _is_jsonrpc_response(value):
        return value
    if isinstance(value, dict) and value.get("jsonrpc") == "2.0" and "error" in value:
        error = value.get("error") if isinstance(value.get("error"), dict) else {}
        return _mcp_error(
            request_id,
            _coerce_error_code(error.get("code")),
            str(error.get("message") or fallback_message),
        )
    if isinstance(value, dict):
        if value.get("ok") is False:
            raw_error = value.get("error") or value.get("message") or fallback_message
            if isinstance(raw_error, dict):
                return _mcp_error(
                    request_id,
                    _coerce_error_code(raw_error.get("code")),
                    str(raw_error.get("message") or fallback_message),
                )
            return _mcp_error(request_id, -32603, str(raw_error))
        if "error" in value:
            return _mcp_error(request_id, -32603, str(value.get("error") or fallback_message))
    return _mcp_error(request_id, -32603, fallback_message)


def _truncate(value: Any, limit: int = MAX_COMPACT_TEXT_CHARS) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 15)] + "...[truncated]"


def _compact_consumer_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        return {}
    keys = (
        "consumer",
        "request_id",
        "consumed_at",
        "read_only",
        "write_performed",
        "platform_write_performed",
        "platform_write",
        "skill_write",
        "memory_write",
        "config_write",
        "items_count",
        "source_refs_count",
        "raw_items_count",
        "receipt_scope",
        "library_index_projection_used",
        "library_index_projection_refs_count",
        "library_index_projection_policy",
        "library_index_projection_soft_weight_policy",
        "library_index_projection_soft_weight",
        "preflight_score_policy",
        "raw_recall_trajectory_contract",
        "raw_recall_trajectory_policy",
        "used_library_ids",
    )
    return {key: receipt.get(key) for key in keys if key in receipt}


def _compact_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in (
        "library_id",
        "library_shelf",
        "type",
        "memory_type",
        "exp_id",
        "source_system",
        "computer_name",
        "canonical_window_id",
        "session_id",
        "project_id",
        "project_root",
        "workstream_id",
        "task_id",
        "active_memory_layer",
        "native_session_key",
        "source_path",
        "msg_ids",
        "raw_evidence_status",
        "evidence_hash",
        "matched_by",
        "rank_reason",
    ):
        value = item.get(key)
        if value not in ("", None, [], {}):
            compact[key] = value
    if item.get("summary"):
        compact["summary"] = _truncate(item.get("summary"))
    if isinstance(item.get("project_status"), dict):
        compact["project_status"] = {
            key: item["project_status"].get(key)
            for key in (
                "artifact_type",
                "status",
                "project",
                "probe_id",
                "skill_artifact_status",
                "status_receipt_write_performed",
                "production_experience_write_performed",
                "raw_write_performed",
                "zhiyi_write_performed",
                "xingce_write_performed",
                "hermes_write_performed",
                "openclaw_write_performed",
            )
            if key in item["project_status"]
        }
    if isinstance(item.get("xingce_candidate"), dict):
        compact["xingce_candidate"] = {
            key: item["xingce_candidate"].get(key)
            for key in (
                "candidate_id",
                "candidate_type",
                "action_status",
                "lifecycle_status",
                "production_experience_write_performed",
                "raw_write_performed",
                "zhiyi_write_performed",
                "xingce_write_performed",
                "hermes_write_performed",
                "openclaw_write_performed",
            )
            if key in item["xingce_candidate"]
        }
    return compact


def _compact_tiandao_context_package(package: Any) -> dict[str, Any]:
    if not isinstance(package, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in (
        "schema",
        "query_hash",
        "source_system",
        "canonical_window_id",
        "session_id",
        "intent_mode",
        "memory_context_mode",
        "ttl_seconds",
        "scope_enforced",
        "injection_blocked",
        "block_reason",
        "memory_write",
        "tiandao_scope",
        "private_architecture_subsystem",
        "tiandao_face",
        "contract_role",
        "overclaim_boundary",
        "consumer",
        "memory_scope",
        "memory_base_scope",
        "active_layers_used",
        "current_window_binding_applied",
        "current_window_binding_key",
        "current_window_binding_fields",
        "cross_window_read",
        "cross_window_read_allowed",
        "injection_boundary",
        "validation",
    ):
        value = package.get(key)
        if value not in ("", None, [], {}):
            compact[key] = value
    refs = package.get("source_refs") if isinstance(package.get("source_refs"), list) else []
    if refs:
        compact["source_refs"] = [
            {
                key: ref.get(key)
                for key in (
                    "ref_id",
                    "source_system",
                    "artifact_type",
                    "ref_path",
                    "artifact_id",
                    "captured_at",
                    "evidence_hash",
                    "raw_evidence_status",
                )
                if isinstance(ref, dict) and ref.get(key) not in ("", None, [], {})
            }
            for ref in refs[:MAX_COMPACT_ITEMS]
        ]
    for key in ("permission_boundary", "capability_profile", "adapter_verdict"):
        value = package.get(key)
        if isinstance(value, dict):
            compact[key] = {
                nested_key: nested_value
                for nested_key, nested_value in value.items()
                if nested_value not in ("", None, [], {})
            }
    return compact


def _compact_capability_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "ok",
        "mode",
        "service",
        "server",
        "version",
        "source",
        "read_only",
        "write_performed",
        "platform_write_performed",
        "recall_performed",
        "raw_excerpt_returned",
        "raw_query_path",
        "mcp_path",
        "mcp_tools",
        "matched_count",
        "source_refs_count",
        "raw_items_count",
    )
    compact = {key: payload.get(key) for key in keys if key in payload}
    compact["consumer_receipt"] = _compact_consumer_receipt(payload.get("consumer_receipt"))
    return compact


def _compact_preflight_surface(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in (
        "library_id",
        "library_shelf",
        "source_system",
        "canonical_window_id",
        "session_id",
        "project_id",
        "active_memory_layer",
        "source_path",
        "msg_ids",
        "raw_evidence_status",
        "matched_by",
        "rank_reason",
        "why_surface",
        "score",
        "library_index_projection_soft_weight_applied",
        "library_index_projection_soft_weight",
        "library_index_projection_soft_weight_policy",
    ):
        value = item.get(key)
        if value not in ("", None, [], {}):
            compact[key] = value
    for key in ("title", "summary"):
        if item.get(key):
            compact[key] = _truncate(item.get(key), 400)
    return compact


def _compact_preflight_payload(
    payload: dict[str, Any],
    *,
    response_budget_mode: str = "claude_desktop_preflight_compact",
) -> dict[str, Any]:
    surfaces = payload.get("must_surface") if isinstance(payload.get("must_surface"), list) else []
    keys = (
        "ok",
        "mode",
        "version",
        "contract",
        "auto_entry_contract",
        "auto_entry_state",
        "auto_entry_allowed",
        "auto_retreat_allowed",
        "auto_entry_reason",
        "auto_entry_triggered_by",
        "auto_retreat_reason",
        "context_delivery_mode",
        "next_action",
        "agent_instruction",
        "consumer",
        "query",
        "read_only",
        "write_performed",
        "raw_write_performed",
        "zhiyi_write_performed",
        "xingce_write_performed",
        "platform_write_performed",
        "model_call_performed",
        "recall_performed",
        "raw_excerpt_returned",
        "decision",
        "prompt_class",
        "confidence",
        "min_surface_score",
        "top_score",
        "preflight_score_policy",
        "library_index_projection_soft_weight_policy",
        "library_index_projection_soft_weight",
        "preflight_score_profile",
        "silence_reason",
        "should_recall",
        "should_surface",
        "source_refs_required",
        "proactive_resurfacing_required",
        "zhiyi_focus",
        "xingce_focus",
        "do_not_repeat",
        "acceptance_checks",
        "recall_status",
        "reason",
        "memory_scope",
        "memory_base_scope",
        "scope_missing",
        "missing_scope_fields",
        "cross_window_read",
        "cross_window_read_allowed",
        "active_layers_used",
        "matched_count",
        "source_refs_count",
        "raw_items_count",
        "catalog_index_used",
        "catalog_index_status",
        "catalog_index_items_count",
        "raw_fallback_used",
        "raw_fallback_status",
        "raw_fallback_scanned_files",
        "raw_fallback_scanned_bytes",
        "raw_fallback_scanned_lines",
        "raw_fallback_truncated",
        "raw_fallback_timed_out",
        "raw_evidence_status",
        "raw_recall_trajectory_contract",
        "raw_recall_trajectory_policy",
        "raw_recall_trajectory",
        "library_index_projection_contract",
        "library_index_projection_policy",
        "library_index_projection_used",
        "library_index_projection_refs_count",
        "library_index_projection_refs",
        "source_system_filter",
        "source_system_filter_aliases",
        "source_collection_filter",
        "claude_collection_alias_applied",
        "claude_collection_alias_boundary",
        "canonical_window_id_filter",
        "project_id_filter",
        "project_root_filter",
        "workstream_id_filter",
        "task_id_filter",
        "current_window_binding_applied",
        "current_window_binding_key",
        "current_window_binding_fields",
        "agent_boundary",
        "injection_boundary",
        "tiandao_context_package_valid",
        "fast_window_preflight",
        "fast_recall_path",
        "fast_window_index_status",
        "zhiyi_layer_skipped_for_fast_preflight",
    )
    compact = {key: payload.get(key) for key in keys if key in payload}
    compact["must_surface"] = [
        _compact_preflight_surface(item)
        for item in surfaces[:MAX_COMPACT_ITEMS]
    ]
    compact["response_budget"] = {
        "mode": response_budget_mode,
        "items_returned": min(len(surfaces), MAX_COMPACT_ITEMS),
        "items_available": len(surfaces),
        "omitted_large_fields": ["zhixing_library", "hybrid_recall", "raw_excerpt", "library_card", "typed_graph"],
    }
    compact["consumer_receipt"] = _compact_consumer_receipt(payload.get("consumer_receipt"))
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _compact_work_preflight_payload(
    payload: dict[str, Any],
    *,
    response_budget_mode: str = "claude_desktop_work_preflight_compact",
) -> dict[str, Any]:
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
    keys = (
        "ok",
        "mode",
        "version",
        "contract",
        "source_preflight_contract",
        "created_at",
        "consumer",
        "request_id",
        "query",
        "read_only",
        "write_performed",
        "raw_write_performed",
        "zhiyi_write_performed",
        "xingce_write_performed",
        "platform_write_performed",
        "model_call_performed",
        "classification",
        "classification_options",
        "should_intervene",
        "intervention_level",
        "decision",
        "prompt_class",
        "auto_entry_state",
        "recall_status",
        "scope_missing",
        "memory_scope",
        "active_layers_used",
        "do_not_repeat",
        "acceptance_checks",
        "changed_behavior",
        "agent_instruction",
        "next_action",
        "source_refs_required",
        "raw_excerpt_returned",
        "source_system_filter",
        "source_system_filter_aliases",
        "source_collection_filter",
        "requested_source_system",
        "inferred_source_system",
        "canonical_window_id_filter",
        "project_id_filter",
        "project_root_filter",
        "workstream_id_filter",
        "task_id_filter",
        "current_window_binding_applied",
        "current_window_binding_key",
        "current_window_binding_fields",
        "agent_boundary",
        "injection_boundary",
        "fast_window_preflight",
        "fast_recall_path",
        "fast_window_index_status",
        "zhiyi_layer_skipped_for_fast_preflight",
        "raw_recall_trajectory_contract",
        "raw_recall_trajectory_policy",
        "raw_recall_trajectory",
        "library_index_projection_contract",
        "library_index_projection_policy",
        "library_index_projection_used",
        "library_index_projection_refs_count",
        "library_index_projection_refs",
        "preflight_score_policy",
        "library_index_projection_soft_weight_policy",
        "library_index_projection_soft_weight",
        "preflight_score_profile",
    )
    compact = {key: payload.get(key) for key in keys if key in payload}
    compact["evidence"] = [
        _compact_preflight_surface(item)
        for item in evidence[:MAX_COMPACT_ITEMS]
    ]
    compact["response_budget"] = {
        "mode": response_budget_mode,
        "items_returned": min(len(evidence), MAX_COMPACT_ITEMS),
        "items_available": len(evidence),
        "omitted_large_fields": ["preflight_receipt", "zhixing_library", "hybrid_recall", "raw_excerpt", "library_card", "typed_graph"],
    }
    compact["consumer_receipt"] = _compact_consumer_receipt(payload.get("consumer_receipt"))
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _compact_recall_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mode") == "capability_check":
        return _compact_capability_payload(payload)
    if payload.get("mode") == "preflight":
        return _compact_preflight_payload(payload)
    if payload.get("mode") == "work_preflight":
        return _compact_work_preflight_payload(payload)

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    compact = {
        "ok": payload.get("ok"),
        "consumer": payload.get("consumer"),
        "query": payload.get("query"),
        "source_system_filter": payload.get("source_system_filter"),
        "source_system_filter_aliases": payload.get("source_system_filter_aliases"),
        "source_collection_filter": payload.get("source_collection_filter"),
        "claude_collection_alias_applied": payload.get("claude_collection_alias_applied"),
        "claude_collection_alias_boundary": payload.get("claude_collection_alias_boundary"),
        "memory_scope": payload.get("memory_scope"),
        "memory_base_scope": payload.get("memory_base_scope"),
        "scope_missing": payload.get("scope_missing"),
        "recall_status": payload.get("recall_status"),
        "window_binding_hint": payload.get("window_binding_hint"),
        "missing_scope_fields": payload.get("missing_scope_fields"),
        "cross_window_read": payload.get("cross_window_read"),
        "cross_window_read_allowed": payload.get("cross_window_read_allowed"),
        "canonical_window_id_filter": payload.get("canonical_window_id_filter"),
        "project_id_filter": payload.get("project_id_filter"),
        "project_root_filter": payload.get("project_root_filter"),
        "workstream_id_filter": payload.get("workstream_id_filter"),
        "task_id_filter": payload.get("task_id_filter"),
        "current_window_binding_applied": payload.get("current_window_binding_applied"),
        "current_window_binding_key": payload.get("current_window_binding_key"),
        "current_window_binding_fields": payload.get("current_window_binding_fields"),
        "active_layers_used": payload.get("active_layers_used"),
        "agent_boundary": payload.get("agent_boundary"),
        "injection_boundary": payload.get("injection_boundary"),
        "tiandao_context_package_valid": payload.get("tiandao_context_package_valid"),
        "tiandao_context_package": _compact_tiandao_context_package(payload.get("tiandao_context_package")),
        "recall_performed": payload.get("recall_performed"),
        "raw_excerpt_returned": payload.get("raw_excerpt_returned"),
        "matched_count": payload.get("matched_count"),
        "source_refs_count": payload.get("source_refs_count"),
        "raw_items_count": payload.get("raw_items_count"),
        "catalog_index_used": payload.get("catalog_index_used"),
        "catalog_index_status": payload.get("catalog_index_status"),
        "catalog_index_items_count": payload.get("catalog_index_items_count"),
        "raw_fallback_used": payload.get("raw_fallback_used"),
        "raw_fallback_status": payload.get("raw_fallback_status"),
        "raw_fallback_scanned_files": payload.get("raw_fallback_scanned_files"),
        "raw_fallback_scanned_bytes": payload.get("raw_fallback_scanned_bytes"),
        "raw_fallback_scanned_lines": payload.get("raw_fallback_scanned_lines"),
        "raw_fallback_truncated": payload.get("raw_fallback_truncated"),
        "raw_fallback_timed_out": payload.get("raw_fallback_timed_out"),
        "raw_evidence_status": payload.get("raw_evidence_status"),
        "zhiyi_experience_used_as_raw": payload.get("zhiyi_experience_used_as_raw"),
        "items": [_compact_item(item) for item in items[:MAX_COMPACT_ITEMS]],
        "response_budget": {
            "mode": "claude_desktop_compact",
            "items_returned": min(len(items), MAX_COMPACT_ITEMS),
            "items_available": len(items),
            "omitted_large_fields": ["zhixing_library", "hybrid_recall", "library_card", "typed_graph", "items.raw_excerpt", "tiandao_context_package.matched_memories", "tiandao_context_package.raw_projection"],
        },
        "consumer_receipt": _compact_consumer_receipt(payload.get("consumer_receipt")),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _is_zhiyi_recall_call(data: dict[str, Any]) -> bool:
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    return (
        str(data.get("method") or "") == "tools/call"
        and str(params.get("name") or "") in {"time_library_recall", "zhiyi_recall"}
    )


def _window_binding_registry_path(explicit: str = "") -> Path:
    value = str(explicit or os.environ.get("MEMCORE_WINDOW_BINDING_REGISTRY") or "").strip()
    if value:
        return Path(value).expanduser()
    root = str(os.environ.get("MEMCORE_ROOT") or "").strip()
    if root:
        return Path(root).expanduser() / "config" / "window_binding_registry.json"
    try:
        return Path(__file__).resolve().parents[1] / "config" / "window_binding_registry.json"
    except Exception:
        return Path("config") / "window_binding_registry.json"


def _current_window_binding_from_registry(
    *,
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, str]:
    path = _window_binding_registry_path(registry_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"canonical_window_id": "", "session_id": ""}
    current_windows = data.get("current_windows") if isinstance(data, dict) else {}
    if not isinstance(current_windows, dict):
        return {"canonical_window_id": "", "session_id": ""}
    keys = []
    for key in (
        binding_key,
        os.environ.get("MEMCORE_CLAUDE_DESKTOP_BINDING_KEY"),
        *DEFAULT_BINDING_KEYS,
    ):
        text = str(key or "").strip().lower().replace("-", "_")
        if text and text not in keys:
            keys.append(text)
    for key in keys:
        entry = current_windows.get(key)
        if not isinstance(entry, dict):
            continue
        session_id = str(entry.get("session_id") or "").strip()
        canonical_window_id = str(entry.get("canonical_window_id") or session_id or "").strip()
        if canonical_window_id or session_id:
            return {
                "canonical_window_id": canonical_window_id,
                "session_id": session_id,
            }
    return {"canonical_window_id": "", "session_id": ""}


def _current_window_binding(
    *,
    canonical_window_id: str = "",
    session_id: str = "",
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, str]:
    env_binding = {
        "canonical_window_id": str(
            canonical_window_id
            or os.environ.get("MEMCORE_CLAUDE_DESKTOP_CANONICAL_WINDOW_ID")
            or os.environ.get("MEMCORE_CLAUDE_DESKTOP_SESSION_ID")
            or ""
        ).strip(),
        "session_id": str(
            session_id
            or os.environ.get("MEMCORE_CLAUDE_DESKTOP_SESSION_ID")
            or ""
        ).strip(),
    }
    if env_binding["canonical_window_id"] or env_binding["session_id"]:
        return env_binding
    registry_binding = _current_window_binding_from_registry(
        registry_path=registry_path,
        binding_key=binding_key,
    )
    if registry_binding["canonical_window_id"] or registry_binding["session_id"]:
        return registry_binding
    return {
        "canonical_window_id": "",
        "session_id": "",
    }


def _budget_zhiyi_request(
    data: dict[str, Any],
    *,
    consumer: str = "claude_desktop",
    canonical_window_id: str = "",
    session_id: str = "",
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, Any]:
    if not _is_zhiyi_recall_call(data):
        return data
    params = dict(data.get("params") if isinstance(data.get("params"), dict) else {})
    args = dict(params.get("arguments") if isinstance(params.get("arguments"), dict) else {})
    mode = str(args.get("mode") or "").strip().lower()
    if mode == "capability_check" or args.get("capability_check") or args.get("no_recall"):
        return data
    args.setdefault("consumer", consumer)
    binding = _current_window_binding(
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        registry_path=registry_path,
        binding_key=binding_key,
    )
    has_window_binding = bool(binding["canonical_window_id"] or binding["session_id"])
    if not str(args.get("memory_scope") or "").strip():
        args["memory_scope"] = "window" if mode in {"preflight", "work_preflight", "agent_work_preflight"} and has_window_binding else "active"
    if binding["canonical_window_id"]:
        args.setdefault("canonical_window_id", binding["canonical_window_id"])
    if binding["session_id"]:
        args.setdefault("session_id", binding["session_id"])
    args.setdefault("limit", DEFAULT_RECALL_LIMIT)
    args.setdefault("excerpt_chars", DEFAULT_RECALL_EXCERPT_CHARS)
    args.setdefault("response_budget", "compact")
    params["arguments"] = args
    budgeted = dict(data)
    budgeted["params"] = params
    return budgeted


def _compact_zhiyi_response(response: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    if not _is_zhiyi_recall_call(request):
        return response
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    if result.get("isError"):
        return response
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        return response

    request_args = {}
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    if isinstance(params.get("arguments"), dict):
        request_args = params["arguments"]
    if (
        str(request_args.get("response_budget") or "").strip().lower() == "raw"
        or str(request_args.get("mode") or "").strip().lower() == "raw"
        or bool(request_args.get("include_raw_excerpt"))
    ):
        return response

    compact_payload = _compact_recall_payload(structured)
    compact_result = dict(result)
    compact_result["structuredContent"] = compact_payload
    compact_result["content"] = [
        {
            "type": "text",
            "text": json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":")),
        }
    ]
    compact_response = dict(response)
    compact_response["result"] = compact_result
    return compact_response


def _send_once(
    endpoint: str,
    data: dict[str, Any],
    timeout: float,
    *,
    http_session: _McpHttpSession | None = None,
    include_session: bool = True,
    session_id_override: str = "",
) -> tuple[dict[str, Any] | None, int, str]:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if session_id_override:
        headers["Mcp-Session-Id"] = session_id_override
    elif http_session is not None and include_session:
        headers.update(http_session.request_headers(endpoint))
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if http_session is not None:
                http_session.observe(endpoint, resp.headers)
            if resp.status == 202:
                return None, 202, ""
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if http_session is not None:
            http_session.observe(endpoint, exc.headers)
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
            return _normalize_jsonrpc_response(parsed, data.get("id"), raw[:200] or str(exc)), exc.code, raw
        except Exception:
            return _mcp_error(data.get("id"), -32603, raw[:200] or str(exc)), exc.code, raw
    except Exception as exc:
        message = f"Time Library MCP gateway unavailable at {endpoint}: {type(exc).__name__}: {exc}"
        return _mcp_error(data.get("id"), -32000, message), 0, message
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return _mcp_error(data.get("id"), -32603, "Invalid gateway response"), 200, raw
        return _normalize_jsonrpc_response(parsed, data.get("id"), "Invalid gateway JSON-RPC response"), 200, raw
    except Exception:
        return _mcp_error(data.get("id"), -32603, "Invalid gateway JSON response"), 200, raw


def _is_session_rejection(status: int, response: dict[str, Any] | None, raw: str) -> bool:
    error = response.get("error") if isinstance(response, dict) and isinstance(response.get("error"), dict) else {}
    details = error.get("data") if isinstance(error.get("data"), dict) else {}
    return bool(
        status == 404
        and error.get("code") == -32001
        and details.get("contract") == MCP_SESSION_REJECTION_CONTRACT
        and details.get("reason") == "session_not_found"
        and details.get("request_dispatched") is False
        and details.get("safe_to_retry_after_initialize") is True
    )


def _resume_rejection_reason(status: int, response: dict[str, Any] | None) -> str:
    error = response.get("error") if isinstance(response, dict) and isinstance(response.get("error"), dict) else {}
    details = error.get("data") if isinstance(error.get("data"), dict) else {}
    reason = str(details.get("reason") or "").strip()
    if (
        status == 409
        and error.get("code") == -32002
        and details.get("contract") == MCP_RESUME_REJECTION_CONTRACT
        and reason
        and details.get("request_dispatched") is False
        and details.get("session_issued") is False
        and details.get("safe_to_retry_without_user_reverification") is False
    ):
        return reason
    return ""


def _mcp_reverification_required(request_id: Any, reason: str) -> dict[str, Any]:
    response = _mcp_error(
        request_id,
        -32002,
        "Time Library verified MCP connection must be re-verified; original request was not sent",
    )
    response["error"]["data"] = {
        "contract": MCP_RESUME_REJECTION_CONTRACT,
        "reason": reason,
        "request_dispatched": False,
        "session_issued": False,
        "reverification_required": True,
        "safe_to_retry_without_user_reverification": False,
    }
    return response


def _reinitialize_session(
    endpoint: str,
    timeout: float,
    http_session: _McpHttpSession,
    *,
    replay_initialized_notification: bool = True,
    log: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    logger = log or _log
    initialize_request = http_session.initialize_request
    if not isinstance(initialize_request, dict):
        logger("MCP session recovery skipped stage=initialize reason=request_not_cached")
        return False, ""
    if not http_session.can_recover():
        logger(
            "MCP session recovery deferred stage=initialize reason=backoff "
            f"failures={http_session.recovery_failures}"
        )
        return False, ""
    if http_session.verified_connection and not http_session.recovery_session():
        reason = "verified_host_resume_bearer_missing"
        http_session.require_reverification(endpoint)
        logger(
            "MCP session recovery stopped stage=initialize mode=verified_resume "
            f"reason={reason} reverification_required=true"
        )
        return False, reason
    recovery_mode = "verified_resume" if http_session.verified_connection else "fresh_initialize"
    resume_session_id = http_session.recovery_session() if http_session.verified_connection else ""
    logger(f"MCP session recovery started mode={recovery_mode}")
    http_session.clear_session(endpoint)
    response, status, _raw = _send_once(
        endpoint,
        initialize_request,
        timeout,
        http_session=http_session,
        include_session=False,
        session_id_override=resume_session_id,
    )
    resume_rejection_reason = _resume_rejection_reason(status, response)
    if recovery_mode == "verified_resume" and resume_rejection_reason:
        http_session.require_reverification(endpoint)
        logger(
            "MCP session recovery stopped stage=initialize mode=verified_resume "
            f"reason={resume_rejection_reason} reverification_required=true"
        )
        return False, resume_rejection_reason
    if status < 200 or status >= 300 or not http_session.session_id:
        http_session.mark_recovery_failure(endpoint)
        logger(
            "MCP session recovery failed stage=initialize "
            f"mode={recovery_mode} status={status} failures={http_session.recovery_failures}"
        )
        return False, ""
    if not isinstance(response, dict) or not isinstance(response.get("result"), dict):
        http_session.mark_recovery_failure(endpoint)
        logger(
            "MCP session recovery failed stage=initialize_response "
            f"mode={recovery_mode} failures={http_session.recovery_failures}"
        )
        return False, ""
    http_session.resume_session_id = http_session.session_id
    notification = http_session.initialized_notification
    if replay_initialized_notification and isinstance(notification, dict):
        _notification_response, notification_status, _notification_raw = _send_once(
            endpoint,
            notification,
            timeout,
            http_session=http_session,
        )
        if notification_status < 200 or notification_status >= 300:
            http_session.mark_recovery_failure(endpoint)
            logger(
                "MCP session recovery failed stage=initialized_notification "
                f"mode={recovery_mode} status={notification_status} "
                f"failures={http_session.recovery_failures}"
            )
            return False, ""
    logger(f"MCP session recovery initialized mode={recovery_mode}")
    return True, ""


def _forward(
    endpoint: str,
    data: dict[str, Any],
    timeout: float,
    compact_recall: bool,
    *,
    http_session: _McpHttpSession | None = None,
    consumer: str = "claude_desktop",
    canonical_window_id: str = "",
    session_id: str = "",
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, Any] | None:
    forwarded = (
        _budget_zhiyi_request(
            data,
            consumer=consumer,
            canonical_window_id=canonical_window_id,
            session_id=session_id,
            registry_path=registry_path,
            binding_key=binding_key,
        )
        if compact_recall
        else data
    )
    method = str(forwarded.get("method") or "")
    recovery_performed = False
    if http_session is not None:
        http_session.set_endpoint(endpoint)
        http_session.remember_request(forwarded)
        if (
            method != "initialize"
            and not http_session.session_id
            and http_session.initialize_request is not None
        ):
            recovery_performed, reverification_reason = _reinitialize_session(
                endpoint,
                timeout,
                http_session,
                replay_initialized_notification=method != "notifications/initialized",
                log=_log,
            )
            if not recovery_performed:
                if reverification_reason:
                    return _mcp_reverification_required(
                        forwarded.get("id"),
                        reverification_reason,
                    )
                return _mcp_error(
                    forwarded.get("id"),
                    -32000,
                    "Time Library MCP session recovery failed; original request was not sent",
                )
    response, status, raw = _send_once(
        endpoint,
        forwarded,
        timeout,
        http_session=http_session,
    )
    if (
        http_session is not None
        and method != "initialize"
        and not recovery_performed
        and _is_session_rejection(status, response, raw)
    ):
        recovery_performed, reverification_reason = _reinitialize_session(
            endpoint,
            timeout,
            http_session,
            replay_initialized_notification=method != "notifications/initialized",
            log=_log,
        )
        if not recovery_performed and reverification_reason:
            return _mcp_reverification_required(
                forwarded.get("id"),
                reverification_reason,
            )
        if recovery_performed:
            response, status, raw = _send_once(
                endpoint,
                forwarded,
                timeout,
                http_session=http_session,
            )
    if http_session is not None and recovery_performed:
        if _is_session_rejection(status, response, raw):
            preserve_verified_bearer = bool(
                http_session.verified_connection and http_session.session_id
            )
            http_session.mark_recovery_failure(
                endpoint,
                preserve_resume=preserve_verified_bearer,
            )
            _log(
                "MCP session recovery failed stage=original_request "
                f"failures={http_session.recovery_failures} "
                f"verified_bearer_preserved={str(preserve_verified_bearer).lower()}"
            )
        else:
            http_session.mark_recovery_success()
            _log("MCP session recovery completed")
    if http_session is not None:
        http_session.observe_response(forwarded, response)
    if response is None:
        return None
    return _compact_zhiyi_response(response, data) if compact_recall else response


def _forward_discovered(
    configured_endpoint: str,
    data: dict[str, Any],
    timeout: float,
    compact_recall: bool,
    **kwargs: Any,
) -> dict[str, Any] | None:
    try:
        endpoint = resolve_client_url(
            "/mcp",
            endpoint=configured_endpoint,
            root=os.environ.get("MEMCORE_ROOT"),
            wait_timeout=min(max(0.0, timeout), 3.0),
        )
    except RuntimeError as exc:
        return _mcp_error(data.get("id"), -32000, str(exc))
    return _forward(endpoint, data, timeout, compact_recall, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Desktop stdio bridge for Time Library MCP")
    parser.add_argument(
        "--endpoint",
        default="",
        help="Optional explicit endpoint; omitted or legacy loopback endpoints use the front-door discovery file.",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--consumer", default="claude_desktop")
    parser.add_argument(
        "--canonical-window-id",
        default="",
        help="Explicit Claude Desktop conversation/window id for window-scoped recall.",
    )
    parser.add_argument(
        "--session-id",
        default="",
        help="Explicit Claude Desktop session id for window-scoped recall.",
    )
    parser.add_argument(
        "--window-binding-registry",
        default="",
        help="Path to the Time Library window_binding_registry.json.",
    )
    parser.add_argument(
        "--binding-key",
        default="",
        help="Current-window registry key for this Claude Desktop bridge.",
    )
    parser.add_argument(
        "--full-recall-response",
        dest="compact_recall",
        action="store_false",
        help="Forward the full raw gateway recall payload instead of the Claude Desktop compact payload.",
    )
    parser.set_defaults(compact_recall=True)
    args = parser.parse_args()

    _log(f"bridge started -> per-request front-door discovery timeout={args.timeout}s compact_recall={args.compact_recall}")
    http_session = _McpHttpSession()
    while True:
        data = _read_message()
        if data is None:
            return 0
        method = str(data.get("method") or "")
        if method == "__parse_error__":
            _write_message(_mcp_error(data.get("id"), -32700, "Parse error"))
            continue
        if method == "__invalid_request__":
            _write_message(_mcp_error(data.get("id"), -32600, "Invalid Request"))
            continue
        response = _forward_discovered(
            args.endpoint,
            data,
            args.timeout,
            args.compact_recall,
            http_session=http_session,
            consumer=args.consumer,
            canonical_window_id=args.canonical_window_id,
            session_id=args.session_id,
            registry_path=args.window_binding_registry,
            binding_key=args.binding_key,
        )
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())
