"""Neutral Tiandao active-memory routing and capture contracts."""

from __future__ import annotations

from typing import Any, Iterable


TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT = "tiandao_active_memory_routing.v1"
TIANDAO_CONVERSATION_EVIDENCE_CONTRACT = "tiandao_conversation_evidence.v1"
TIANDAO_CONTINUOUS_LOCAL_SYNC_CONTRACT = "tiandao_continuous_local_sync.v1"
TIANDAO_MEMORY_EXPERIENCE_LAYERING_CONTRACT = "tiandao_memory_experience_layering.v1"
TIANDAO_TIME_ORIGIN_CONTRACT = "tiandao_time_origin.v1"
TIANDAO_TIME_RIVER_CONTRACT = "tiandao_time_river.v1"
TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT = "tiandao_time_river_sediment.v1"

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

RAW_SOURCE_LAYER = "raw_source_evidence"
ZHIYI_LAYER = "zhiyi_user_understanding"
XINGCE_LAYER = "xingce_work_strategy"
TOOLBOOK_LAYER = "toolbook_operational_fact"
MEMORY_EXPERIENCE_LAYERS = ("raw", "zhiyi", "xingce", "toolbook")
TIME_ORIGIN_LAYER = "raw"
TIME_ORIGIN_EVENT_REQUIRED = True
TIME_ORIGIN_STATUSES = (
    "origin_witnessed",
    "lost_source",
    "lost_raw",
    "origin_unavailable",
)
TIME_ORIGIN_LOST_LABELS = {
    "lost_source": "遗失源",
    "lost_raw": "遗失 raw",
}
TIME_RIVER_STAGES = (
    "source_event",
    "raw_preservation",
    "experience_sedimentation",
    "context_delivery",
    "audit_receipt",
    "replay_validation",
    "errata_or_supersession",
)
TIME_RIVER_REQUIRED_ANCHORS = (
    "event_time",
    "source_refs",
    "library_id",
    "lifecycle_status",
    "audit_event",
)
TIME_RIVER_SEDIMENT_LAYERS = (
    "raw",
    "zhiyi",
    "xingce",
    "toolbook",
    "errata",
)
TIME_RIVER_SEDIMENT_STATUSES = (
    "origin_linked",
    "source_refs_only",
    "origin_missing_candidate",
    "raw_unavailable_untrusted",
)
TIME_RIVER_REPLAY_METRICS = (
    "fewer_repeated_questions",
    "fewer_repeated_mistakes",
    "user_habit_followed",
    "source_backed_answer_rate",
    "proactive_resurfacing",
)

ZHIYI_SIGNAL_HINTS = {
    "active_memory",
    "preference",
    "correction",
    "intent",
    "user_profile",
    "standing_preference",
}
XINGCE_SIGNAL_HINTS = {
    "rollout_summary",
    "raw_memory",
    "project_instruction",
    "claude_md",
    "agent_rule",
    "skill",
    "debugging_insight",
    "workflow",
    "tool_usage",
    "runbook",
}
TOOLBOOK_SIGNAL_HINTS = {
    "tool_fact",
    "config",
    "environment",
    "setup",
    "install",
    "path",
}
RAW_SIGNAL_HINTS = {
    "raw",
    "source",
    "transcript",
    "source_ref",
    "raw_excerpt",
}


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


def classify_memory_signal_layer(signal_kind: Any = "", fallback_layer: Any = "xingce") -> str:
    kind = str(signal_kind or "").strip().lower().replace("-", "_")
    if kind in ZHIYI_SIGNAL_HINTS:
        return "zhiyi"
    if kind in XINGCE_SIGNAL_HINTS:
        return "xingce"
    if kind in TOOLBOOK_SIGNAL_HINTS:
        return "toolbook"
    if kind in RAW_SIGNAL_HINTS:
        return "raw"
    fallback = str(fallback_layer or "").strip().lower()
    return fallback if fallback in MEMORY_EXPERIENCE_LAYERS else "xingce"


def memory_experience_layering_contract_descriptor() -> dict[str, Any]:
    return {
        "contract": TIANDAO_MEMORY_EXPERIENCE_LAYERING_CONTRACT,
        "raw_source_layer": RAW_SOURCE_LAYER,
        "derived_layers": [ZHIYI_LAYER, XINGCE_LAYER, TOOLBOOK_LAYER],
        "all_queryable_layers": list(MEMORY_EXPERIENCE_LAYERS),
        "platform_is_not_memory_layer": True,
        "platform_capability_policy": "platforms_may_use_any_subset_of_neutral_capabilities",
        "classification_rule": "content_signal_not_platform_identity",
        "raw_source_policy": "derived_zhiyi_xingce_toolbook_must_keep_source_refs",
        "adapter_boundary_policy": "platform_private_protocol_stays_in_thin_adapter",
        "platform_mapping_policy": "outside_tiandao_in_adapter_or_product_layer",
        "global_recall_policy": "explicit_only",
    }


def time_origin_contract_descriptor() -> dict[str, Any]:
    return {
        "contract": TIANDAO_TIME_ORIGIN_CONTRACT,
        "zh_name": "时间起源",
        "role": "neutral_raw_origin_contract",
        "origin_layer": TIME_ORIGIN_LAYER,
        "origin_event_required": TIME_ORIGIN_EVENT_REQUIRED,
        "no_raw_no_river": True,
        "raw_authority_policy": "raw_source_text_is_highest_authority",
        "origin_event_policy": "time_origin_begins_when_raw_is_witnessed",
        "derived_sediment_policy": "derived_sediment_must_reference_origin",
        "local_runtime_policy": "each_runtime_has_first_witnessed_raw_event",
        "multi_machine_policy": "source_streams_merge_not_overwrite",
        "platform_policy": "platforms_are_inlets_not_origin",
        "river_endpoint_policy": "time_river_has_no_endpoint",
        "origin_statuses": list(TIME_ORIGIN_STATUSES),
        "lost_source_label": TIME_ORIGIN_LOST_LABELS["lost_source"],
        "lost_raw_label": TIME_ORIGIN_LOST_LABELS["lost_raw"],
    }


def time_river_contract_descriptor() -> dict[str, Any]:
    return {
        "contract": TIANDAO_TIME_RIVER_CONTRACT,
        "zh_name": "时间长河",
        "role": "neutral_temporal_memory_continuity_contract",
        "time_origin_contract": TIANDAO_TIME_ORIGIN_CONTRACT,
        "sediment_contract": TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT,
        "stages": list(TIME_RIVER_STAGES),
        "sediment_layers": list(TIME_RIVER_SEDIMENT_LAYERS),
        "required_anchors": list(TIME_RIVER_REQUIRED_ANCHORS),
        "origin_policy": "time_river_begins_at_raw_origin_event",
        "source_ref_policy": "every_derived_sediment_must_return_to_source_refs_or_state_unavailable",
        "library_identity_policy": "stable_collection_identity_required_for_recallable_sediment",
        "lifecycle_policy": "candidate_pending_review_adopted_deprecated_superseded",
        "audit_policy": "read_write_delivery_and_scope_decisions_emit_receipts",
        "context_delivery_policy": "context_packages_carry_scope_ttl_purpose_and_source_refs",
        "replay_validation_metrics": list(TIME_RIVER_REPLAY_METRICS),
        "platform_policy": "platforms_are_inlets_not_river_laws",
        "platform_capability_policy": "platforms_may_use_any_subset_of_neutral_capabilities",
        "adapter_boundary_policy": "platform_private_protocol_stays_in_thin_adapter",
        "raw_authority_policy": "raw_source_text_is_highest_authority",
        "summary_policy": "summaries_are_navigation_not_source_replacement",
        "time_order_policy": "events_remain_orderable_by_event_time_and_audit_time",
        "endpoint_policy": "time_river_has_no_endpoint",
        "global_recall_policy": "explicit_only",
    }


def time_river_sediment_contract_descriptor() -> dict[str, Any]:
    return {
        "contract": TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT,
        "zh_name": "时间长河沉积链",
        "role": "neutral_derived_memory_origin_link_contract",
        "time_origin_contract": TIANDAO_TIME_ORIGIN_CONTRACT,
        "time_river_contract": TIANDAO_TIME_RIVER_CONTRACT,
        "sediment_layers": list(TIME_RIVER_SEDIMENT_LAYERS),
        "sediment_statuses": list(TIME_RIVER_SEDIMENT_STATUSES),
        "trusted_status": "origin_linked",
        "candidate_statuses": ["source_refs_only", "origin_missing_candidate", "raw_unavailable_untrusted"],
        "origin_link_policy": "derived_sediment_must_reference_origin",
        "source_ref_policy": "source_refs_are_required_but_not_a_source_replacement",
        "raw_authority_policy": "raw_source_text_is_highest_authority",
        "summary_policy": "summaries_are_navigation_not_source_replacement",
        "write_policy": "read_only_descriptor_no_memory_write",
        "platform_policy": "platforms_are_inlets_not_river_laws",
        "global_recall_policy": "explicit_only",
    }
