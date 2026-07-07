"""MCP JSON-RPC protocol helpers for raw_consumption_gateway.

This module is intentionally protocol-only: it has no recall, catalog, vector,
FTS5, freshness, or runtime-sync dependencies.
"""

from __future__ import annotations

from typing import Any, Dict


MCP_PROTOCOL_VERSION = "2025-06-18"


def _mcp_response_id(request_id: Any) -> str | int | float:
    if isinstance(request_id, bool):
        return "unknown"
    if isinstance(request_id, (str, int, float)):
        return request_id
    return "unknown"


def _mcp_request_id(data: Any) -> Any:
    if not isinstance(data, dict):
        return None
    request_id = data.get("id")
    if isinstance(request_id, bool):
        return None
    if isinstance(request_id, (str, int, float)) or request_id is None:
        return request_id
    return None


def mcp_success(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": _mcp_response_id(request_id), "result": result}


def mcp_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": _mcp_response_id(request_id),
        "error": {"code": code, "message": message},
    }


def mcp_tools_payload(
    *,
    max_limit: int,
    max_excerpt: int,
    hermes_broad_context_workflows,
) -> Dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {
                "type": "string",
                "description": "Recall query, continuation request, or a Time Library library_id such as ZX-RAW-...",
            },
            "library_id": {
                "type": "string",
                "description": "Directly borrow a Time Library catalog card by library_id. This bypasses fuzzy recall and returns the bounded source-backed card.",
            },
            "mode": {
                "type": "string",
                "enum": ["recall", "raw", "preflight", "work_preflight", "agent_work_preflight", "capability_check"],
                "description": "Use preflight before task answers; use work_preflight before coding/ops work; use capability_check to verify tool availability without querying memory.",
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
            "series_id": {
                "type": "string",
                "description": "Optional declared reading-area series id for direct library_id borrow scoping.",
            },
            "reading_area_id": {
                "type": "string",
                "description": "Optional declared reading-area id for direct library_id borrow receipts.",
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
            "deep_work_preflight": {
                "type": "boolean",
                "description": "Explicit opt-in for slower full work_preflight recall; default work_preflight stays on the current-window fast index.",
            },
            "full_work_preflight": {
                "type": "boolean",
                "description": "Alias for deep_work_preflight.",
            },
            "allow_full_work_preflight": {
                "type": "boolean",
                "description": "Alias for deep_work_preflight.",
            },
            "allow_cold_work_preflight": {
                "type": "boolean",
                "description": "Alias for deep_work_preflight.",
            },
            "allow_cross_window_recall": {
                "type": "boolean",
                "description": "Required for ordinary raw_pool/shared recall so a normal client, including normal Hermes recall, does not silently read another window.",
            },
            "cross_window_reason": {
                "type": "string",
                "enum": sorted(hermes_broad_context_workflows),
                "description": "Explicit workflow reason for narrow exceptions such as Hermes skill generation or self-review.",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": max_limit},
            "excerpt_chars": {"type": "integer", "minimum": 1, "maximum": max_excerpt},
            "consumer": {"type": "string"},
            "request_id": {"type": "string"},
            "recall_mode": {
                "type": "string",
                "enum": ["", "substring", "vector"],
                "description": "Recall mode: substring uses keyword/BM25/FTS5 where available; vector uses embedding recall. Default empty string uses service default.",
            },
            "fts5_recall": {
                "type": "boolean",
                "description": "Explicitly enable the SQLite FTS5/BM25 leg for substring recall when the service supports it. Default false; this never changes vector recall into a full freshness claim.",
            },
            "enable_fts5_recall": {
                "type": "boolean",
                "description": "Alias for fts5_recall.",
            },
        },
        "required": [],
    }
    reading_area_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "issue_borrowing_card",
                    "declare_membership",
                    "self_report_connect",
                    "whiteboard_write",
                    "whiteboard_list",
                    "project_history_write",
                    "project_history_list",
                    "nomination_create",
                    "nomination_list",
                    "claim_nomination",
                    "reject_nomination",
                ],
                "description": "Issue a borrowing card, declare reading-area membership, or complete the self-report connection proof for the current window.",
            },
            "source_system": {
                "type": "string",
                "description": "Self-reported source system, such as codex, claude_code_cli, mimocode, minimax, or another client id.",
            },
            "platform_name": {"type": "string"},
            "consumer": {"type": "string"},
            "client_name": {"type": "string"},
            "client_version": {"type": "string"},
            "client_surface": {"type": "string"},
            "canonical_window_id": {
                "type": "string",
                "description": "Self-reported stable window id. Required unless session_id is provided.",
            },
            "session_id": {
                "type": "string",
                "description": "Self-reported session id. Required unless canonical_window_id is provided.",
            },
            "native_window_id": {"type": "string"},
            "title": {"type": "string"},
            "borrowing_card_id": {
                "type": "string",
                "description": "Existing borrowing card id for declare_membership.",
            },
            "reading_area": {
                "type": "string",
                "description": "Self-reported reading area name.",
            },
            "declared_project_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Self-reported project names or ids. These are declaration ids, not technical project_id anchors.",
            },
            "declared_series_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Self-reported series/system names or ids.",
            },
            "declared_roles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Self-reported roles for this window, such as 施工 / 二签 / 出稿.",
            },
            "aliases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional aliases for the declared reading area.",
            },
            "record_type": {
                "type": "string",
                "enum": ["claim_task", "checkpoint", "handoff"],
                "description": "Whiteboard record type.",
            },
            "task_id": {"type": "string"},
            "task_name": {"type": "string"},
            "summary": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["active", "superseded", "completed", "blocked", "handoff", "cancelled"],
            },
            "role": {"type": "string"},
            "next_owner": {"type": "string"},
            "supersedes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "library_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "source_refs": {
                "type": "array",
                "items": {"type": ["object", "string"]},
            },
            "history_type": {
                "type": "string",
                "enum": ["milestone", "decision", "handoff", "checkpoint"],
                "description": "Project history record type. Project history is a project-page record, not a sixth shelf.",
            },
            "nomination_id": {"type": "string"},
            "nominated_project": {"type": "string"},
            "nominated_series": {"type": "string"},
            "source_path": {"type": "string"},
            "reason": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "statuses": {
                "type": "array",
                "items": {"type": "string"},
            },
            "skill_surface_status": {
                "type": "string",
                "description": "Self-reported skill/custom-instruction surface status.",
            },
            "config_write_authority": {
                "type": "boolean",
                "description": "Whether platform config writing is explicitly authorized. False is an accepted explicit answer.",
            },
            "proof_library_id": {
                "type": "string",
                "description": "A ZX-* library_id to borrow as the real recall proof after capability_check.",
            },
            "request_id": {"type": "string"},
        },
        "required": ["action"],
        "oneOf": [
            {
                "properties": {"action": {"const": "issue_borrowing_card"}},
                "required": ["action", "source_system"],
                "anyOf": [
                    {"required": ["canonical_window_id"]},
                    {"required": ["session_id"]},
                ],
            },
            {
                "properties": {"action": {"const": "declare_membership"}},
                "required": ["action", "borrowing_card_id"],
            },
            {
                "properties": {"action": {"const": "whiteboard_write"}},
                "required": ["action", "record_type", "task_id", "summary"],
                "anyOf": [
                    {"required": ["borrowing_card_id"]},
                    {"required": ["canonical_window_id", "source_system"]},
                    {"required": ["session_id", "source_system"]}
                ],
            },
            {
                "properties": {"action": {"const": "whiteboard_list"}},
                "required": ["action"],
            },
            {
                "properties": {"action": {"const": "project_history_write"}},
                "required": ["action", "title", "summary", "source_refs"],
                "anyOf": [
                    {"required": ["borrowing_card_id"]},
                    {"required": ["canonical_window_id", "source_system"]},
                    {"required": ["session_id", "source_system"]}
                ],
            },
            {
                "properties": {"action": {"const": "project_history_list"}},
                "required": ["action"],
            },
            {
                "properties": {"action": {"const": "nomination_create"}},
                "required": ["action", "source_system", "nominated_project"],
                "anyOf": [
                    {"required": ["canonical_window_id"]},
                    {"required": ["session_id"]},
                    {"required": ["source_path"]},
                ],
            },
            {
                "properties": {"action": {"const": "nomination_list"}},
                "required": ["action"],
            },
            {
                "properties": {"action": {"const": "claim_nomination"}},
                "required": ["action", "nomination_id", "borrowing_card_id"],
            },
            {
                "properties": {"action": {"const": "reject_nomination"}},
                "required": ["action", "nomination_id"],
            },
            {
                "properties": {"action": {"const": "self_report_connect"}},
                "required": [
                    "action",
                    "source_system",
                    "skill_surface_status",
                    "config_write_authority",
                    "proof_library_id",
                ],
                "anyOf": [
                    {"required": ["canonical_window_id"]},
                    {"required": ["session_id"]},
                ],
                "allOf": [
                    {
                        "anyOf": [
                            {"required": ["reading_area"]},
                            {"required": ["declared_project_ids"]},
                            {"required": ["declared_series_ids"]},
                        ]
                    }
                ],
            },
        ],
    }
    description = (
        "Read Time Library source-backed local memory. "
        "If library_id is provided, or query is a ZX-* library_id, directly borrow that catalog card. "
        "Returns compact catalog/source refs by default; raw excerpts require "
        "response_budget=raw or include_raw_excerpt=true. "
        "Use mode=preflight before task answers to surface compact preference/work guidance. "
        "Use mode=work_preflight for Agent Work Preflight classification before coding or operational work. "
        "Use mode=capability_check for install smoke tests without recall. Read-only."
    )
    legacy_description = f"{description} Legacy alias for migration; prefer time_library_recall."
    return {
        "tools": [
            {
                "name": "time_library_recall",
                "description": description,
                "inputSchema": schema,
            },
            {
                "name": "zhiyi_recall",
                "description": legacy_description,
                "inputSchema": schema,
            },
            {
                "name": "time_library_reading_area",
                "description": (
                    "Create or update a Time Library reading-area borrowing card from an agent's self-report, "
                    "declare project/series membership, and optionally prove connection with capability_check plus one library_id borrow. "
                    "This writes only the local reading-area registry; it does not write platform config, raw records, memory cards, or chat body."
                ),
                "inputSchema": reading_area_schema,
            },
        ]
    }
