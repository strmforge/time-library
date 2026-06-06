"""Neutral Tiandao active-memory routing and capture contracts."""

from __future__ import annotations

from typing import Any, Iterable


TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT = "tiandao_active_memory_routing.v1"
TIANDAO_CONVERSATION_EVIDENCE_CONTRACT = "tiandao_conversation_evidence.v1"
TIANDAO_CONTINUOUS_LOCAL_SYNC_CONTRACT = "tiandao_continuous_local_sync.v1"

CURRENT_WINDOW_LAYER = "current_window"
CURRENT_SESSION_LAYER = "current_session"
SAME_PROJECT_WORKSPACE_LAYER = "same_project_workspace"
SAME_WORKSTREAM_TASK_LAYER = "same_workstream_task"
STABLE_USER_PREFERENCES_TOOL_FACTS_LAYER = "stable_user_preferences_tool_facts"
EXPLICIT_RAW_POOL_GLOBAL_LAYER = "explicit_raw_pool_global_only_when_requested"

ACTIVE_MEMORY_LAYER_ORDER = (
    CURRENT_WINDOW_LAYER,
    CURRENT_SESSION_LAYER,
    SAME_PROJECT_WORKSPACE_LAYER,
    SAME_WORKSTREAM_TASK_LAYER,
    STABLE_USER_PREFERENCES_TOOL_FACTS_LAYER,
)
ACTIVE_MEMORY_DEFAULT_RECALL_ORDER = ACTIVE_MEMORY_LAYER_ORDER + (
    EXPLICIT_RAW_POOL_GLOBAL_LAYER,
)

WINDOW_IDENTITY_FIELDS = ("canonical_window_id", "session_id")
CROSS_WINDOW_RECALL_FLAG = "allow_cross_window_recall"
BROAD_MEMORY_SCOPES = ("platform", "raw_pool")
COMPLETE_CONVERSATION_REQUIRED_ROLES = ("user", "assistant")

DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS = 250
SYNC_MODE_FILE_EVENT_OR_LOW_LATENCY = "file_event_or_low_latency_loop"
SYNC_INSTALL_SCAN_ONLY = False


def active_memory_default_recall_order() -> list[str]:
    return list(ACTIVE_MEMORY_DEFAULT_RECALL_ORDER)


def active_memory_layer_order() -> list[str]:
    return list(ACTIVE_MEMORY_LAYER_ORDER)


def memory_context_mode_for_routing(
    memory_scope: str,
    active_layers_used: Iterable[str] | None = None,
    cross_window_read: bool = False,
) -> str:
    scope = str(memory_scope or "").strip().lower()
    if scope in BROAD_MEMORY_SCOPES or cross_window_read:
        return "mode_c"
    layers = set(str(layer or "") for layer in (active_layers_used or []) if str(layer or ""))
    if layers and layers <= {CURRENT_WINDOW_LAYER, CURRENT_SESSION_LAYER}:
        return "mode_a"
    if layers:
        return "mode_b"
    return "mode_a"


def is_complete_conversation_roles(roles: Iterable[Any]) -> bool:
    normalized = {str(role or "").strip().lower() for role in roles}
    return set(COMPLETE_CONVERSATION_REQUIRED_ROLES).issubset(normalized)


def conversation_capture_verdict(roles: Iterable[Any], candidate_count: int = 1) -> dict[str, Any]:
    complete = is_complete_conversation_roles(roles)
    return {
        "contract": TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
        "complete_conversation_candidate": complete,
        "required_roles": list(COMPLETE_CONVERSATION_REQUIRED_ROLES),
        "roles_observed": sorted({str(role or "").strip().lower() for role in roles if str(role or "").strip()}),
        "assistant_reply_persistence": "verified" if complete else "unverified",
        "current_window_memory_registerable": complete,
        "not_no_memory": bool(candidate_count) and not complete,
        "partial_source_policy": "evidence_only_not_current_window_memory" if not complete else "",
    }


def active_memory_routing_contract_descriptor() -> dict[str, Any]:
    return {
        "contract": TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
        "default_recall_order": active_memory_default_recall_order(),
        "window_identity_fields": list(WINDOW_IDENTITY_FIELDS),
        "cross_window_flag": CROSS_WINDOW_RECALL_FLAG,
        "broad_memory_scopes": list(BROAD_MEMORY_SCOPES),
        "missing_window_identity_is_not_no_memory": True,
        "raw_pool_or_global_policy": "explicit_only",
    }


def continuous_local_sync_contract_descriptor() -> dict[str, Any]:
    return {
        "contract": TIANDAO_CONTINUOUS_LOCAL_SYNC_CONTRACT,
        "install_scan_only": SYNC_INSTALL_SCAN_ONLY,
        "mode": SYNC_MODE_FILE_EVENT_OR_LOW_LATENCY,
        "default_target_latency_milliseconds": DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS,
        "event_driven_preferred": True,
        "fallback_policy": "low_latency_poll",
    }
