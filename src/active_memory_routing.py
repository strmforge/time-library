#!/usr/bin/env python3
"""
Lightweight active-memory routing contract.

This module is intentionally independent from recall/index code so UI and
diagnostic endpoints can report the window-first memory contract without
loading the full retrieval pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

try:
    from src.memcore_version import SERVICE_VERSION
except Exception:
    from memcore_version import SERVICE_VERSION
try:
    from src.tiandao.memory_routing import (
        ACTIVE_MEMORY_LAYER_ORDER,
        CROSS_WINDOW_RECALL_FLAG,
        EXPLICIT_RAW_POOL_GLOBAL_LAYER,
        TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
        active_memory_default_recall_order,
        active_memory_routing_contract_descriptor,
        classify_memory_signal_layer,
        memory_experience_layering_contract_descriptor,
        time_river_contract_descriptor,
    )
except Exception:
    from tiandao.memory_routing import (
        ACTIVE_MEMORY_LAYER_ORDER,
        CROSS_WINDOW_RECALL_FLAG,
        EXPLICIT_RAW_POOL_GLOBAL_LAYER,
        TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
        active_memory_default_recall_order,
        active_memory_routing_contract_descriptor,
        classify_memory_signal_layer,
        memory_experience_layering_contract_descriptor,
        time_river_contract_descriptor,
    )
try:
    from src.source_system_runtime_declarations import (
        source_system_from_consumer_name,
    )
except Exception:
    from source_system_runtime_declarations import (
        source_system_from_consumer_name,
    )


UTC = timezone.utc
SERVICE_NAME = "raw_consumption_gateway"
ACTIVE_MEMORY_ROUTING_CONTRACT = "active_memory_routing.v2026.7.15"
DEFAULT_MEMORY_SCOPE = "active"
SHARED_MEMORY_SCOPES = {"raw_pool", "shared", "all", "global"}
VALID_MEMORY_SCOPES = {"active", "window", "platform", "dual"} | SHARED_MEMORY_SCOPES


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_memory_scope(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return DEFAULT_MEMORY_SCOPE
    if text in {"default", "auto", "layered", "active_layered"}:
        return "active"
    if text in {"source", "source_system", "platform_only"}:
        return "platform"
    if text in {"window_only", "session", "session_window"}:
        return "window"
    if text in SHARED_MEMORY_SCOPES:
        return "raw_pool"
    if text in VALID_MEMORY_SCOPES:
        return text
    return DEFAULT_MEMORY_SCOPE


def source_system_from_consumer(consumer: str) -> str:
    return source_system_from_consumer_name(consumer)


def normalize_cross_window_reason(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def resolve_recall_scope(
    *,
    source_system: str,
    consumer: str,
    memory_scope: str,
    canonical_window_id: str,
    session_id: str,
    allow_cross_window_recall: bool = False,
    cross_window_reason: str = "",
) -> Dict[str, Any]:
    scope = normalize_memory_scope(memory_scope)
    requested_source = str(source_system or "").strip()
    inferred_source = source_system_from_consumer(consumer)
    effective_source = requested_source
    scope_missing = False
    missing: List[str] = []
    explicit_cross_window_permission = allow_cross_window_recall is True

    if scope == "dual":
        scope = "window"

    if scope == "raw_pool":
        effective_source = requested_source
        memory_base_scope = "shared" if not effective_source else "filtered"
        if not explicit_cross_window_permission:
            scope_missing = True
            missing.append(CROSS_WINDOW_RECALL_FLAG)
    elif scope == "platform":
        effective_source = requested_source
        memory_base_scope = "filtered" if effective_source else "platform_unresolved"
        if not effective_source:
            scope_missing = True
            missing.append("source_system")
        if not explicit_cross_window_permission:
            scope_missing = True
            missing.append(CROSS_WINDOW_RECALL_FLAG)
    elif scope == "active":
        effective_source = requested_source
        memory_base_scope = "active_layered"
    else:
        scope = "window"
        effective_source = requested_source
        memory_base_scope = "window"
        if not (str(canonical_window_id or "").strip() or str(session_id or "").strip()):
            scope_missing = True
            missing.extend(["canonical_window_id", "session_id"])

    return {
        "memory_scope": scope,
        "requested_source_system": requested_source,
        "inferred_source_system": inferred_source,
        "effective_source_system": effective_source,
        "source_filter_authority": "explicit_request_or_verified_window_binding",
        "consumer_name_inference_used_for_routing": False,
        "memory_base_scope": memory_base_scope,
        "scope_missing": scope_missing,
        "missing_scope_fields": missing,
        "cross_window_read": scope in {"platform", "raw_pool"},
        "cross_window_read_allowed": bool(
            scope not in {"platform", "raw_pool"}
            or explicit_cross_window_permission
        ),
        "cross_window_permission_explicit": bool(
            scope in {"platform", "raw_pool"} and explicit_cross_window_permission
        ),
        "cross_window_reason_is_authorization": False,
        "active_layered_continuation": bool(scope == "active"),
        "cross_window_reason": normalize_cross_window_reason(cross_window_reason),
        "canonical_window_id": str(canonical_window_id or "").strip(),
        "session_id": str(session_id or "").strip(),
    }


def scope_missing_status(scope: Dict[str, Any]) -> Dict[str, str]:
    missing = set(scope.get("missing_scope_fields") or [])
    memory_scope = str(scope.get("memory_scope") or "")
    if memory_scope == "active":
        return {
            "recall_status": "active_layered",
            "window_binding_hint": (
                "Active recall is window-first, then project/workspace, "
                "workstream/task, and stable preferences/tool facts. It does "
                "not read the raw pool unless explicitly requested."
            ),
        }
    if memory_scope == "window" and {"canonical_window_id", "session_id"} & missing:
        return {
            "recall_status": "window_identity_required",
            "window_binding_hint": (
                "Current-window recall is the default, but this client did not "
                "provide a canonical_window_id or session_id. This is not proof "
                "that memory is empty; bind the current window/session and retry."
            ),
        }
    if CROSS_WINDOW_RECALL_FLAG in missing:
        return {
            "recall_status": "cross_window_permission_required",
            "window_binding_hint": (
                "This recall would read across windows. Every client must pass "
                "allow_cross_window_recall=true explicitly. cross_window_reason "
                "is retained for audit context and never grants permission."
            ),
        }
    if "source_system" in missing:
        return {
            "recall_status": "source_system_required",
            "window_binding_hint": (
                "Platform recall needs a source_system when the consumer cannot "
                "be mapped to a known local source."
            ),
        }
    return {
        "recall_status": "scope_binding_required",
        "window_binding_hint": "Provide current-window identity or an explicit cross-window recall flag.",
    }


def active_memory_routing_status() -> Dict[str, Any]:
    """Read-only status for the current-window-first memory routing contract."""
    ordinary_active = resolve_recall_scope(
        source_system="",
        consumer="client_a",
        memory_scope="",
        canonical_window_id="",
        session_id="",
    )
    ordinary_window_missing = resolve_recall_scope(
        source_system="",
        consumer="client_a",
        memory_scope="window",
        canonical_window_id="",
        session_id="",
    )
    client_a_raw_pool_without_flag = resolve_recall_scope(
        source_system="",
        consumer="client_a",
        memory_scope="raw_pool",
        canonical_window_id="",
        session_id="",
    )
    client_b_raw_pool_without_flag = resolve_recall_scope(
        source_system="",
        consumer="client_b",
        memory_scope="raw_pool",
        canonical_window_id="",
        session_id="",
    )
    client_a_raw_pool_with_flag = resolve_recall_scope(
        source_system="",
        consumer="client_a",
        memory_scope="raw_pool",
        canonical_window_id="",
        session_id="",
        allow_cross_window_recall=True,
        cross_window_reason="skill_generation",
    )
    client_b_raw_pool_with_flag = resolve_recall_scope(
        source_system="",
        consumer="client_b",
        memory_scope="raw_pool",
        canonical_window_id="",
        session_id="",
        allow_cross_window_recall=True,
        cross_window_reason="skill_generation",
    )
    return {
        "ok": True,
        "contract": ACTIVE_MEMORY_ROUTING_CONTRACT,
        "tiandao_contract": TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
        "tiandao_routing_contract": active_memory_routing_contract_descriptor(),
        "tiandao_memory_experience_layering_contract": memory_experience_layering_contract_descriptor(),
        "tiandao_time_river_contract": time_river_contract_descriptor(),
        "all_queryable_memory_layers": ["raw", "zhiyi", "xingce", "toolbook"],
        "platform_is_not_memory_layer": True,
        "example_signal_layering": {
            "preference": classify_memory_signal_layer("preference"),
            "workflow": classify_memory_signal_layer("workflow"),
            "correction": classify_memory_signal_layer("correction"),
            "skill": classify_memory_signal_layer("skill"),
            "tool_fact": classify_memory_signal_layer("tool_fact"),
        },
        "generated_at": ts(),
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "recall_performed": False,
        "raw_excerpt_returned": False,
        "default_memory_scope": DEFAULT_MEMORY_SCOPE,
        "default_recall_order": active_memory_default_recall_order(),
        "ordinary_client_contract": {
            "default_scope": "active",
            "requires_current_window_identity": False,
            "identity_fields": ["canonical_window_id", "session_id"],
            "missing_identity_status": scope_missing_status(ordinary_active)["recall_status"],
            "missing_identity_is_not_no_memory": True,
            "window_scope_is_strict_when_explicit": True,
            "active_recall_is_window_first_not_window_only": True,
            "cross_window_requires_explicit_flag": True,
            "cross_window_flag": CROSS_WINDOW_RECALL_FLAG,
        },
        "scope_modes": {
            "active": {
                "memory_base_scope": "active_layered",
                "cross_window_read": False,
                "requires_any_identity": [],
                "fallback_order": list(ACTIVE_MEMORY_LAYER_ORDER),
                "raw_pool_or_global": "explicit_only",
                "raw_pool_or_global_layer": EXPLICIT_RAW_POOL_GLOBAL_LAYER,
            },
            "window": {
                "memory_base_scope": "window",
                "cross_window_read": False,
                "requires_any_identity": ["canonical_window_id", "session_id"],
            },
            "platform": {
                "memory_base_scope": "filtered",
                "cross_window_read": True,
                "ordinary_clients_require_explicit_flag": True,
            },
            "raw_pool": {
                "memory_base_scope": "shared",
                "cross_window_read": True,
                "ordinary_clients_require_explicit_flag": True,
            },
        },
        "cross_window_authorization": {
            "identity_based_exceptions": [],
            "required_flag": CROSS_WINDOW_RECALL_FLAG,
            "cross_window_reason_role": "audit_only_not_authorization",
            "same_contract_for_every_client": True,
        },
        "example_resolutions": {
            "ordinary_active_without_identity": {
                "memory_scope": ordinary_active["memory_scope"],
                "scope_missing": ordinary_active["scope_missing"],
                "recall_status": scope_missing_status(ordinary_active)["recall_status"],
                "missing_scope_fields": ordinary_active["missing_scope_fields"],
                "cross_window_read": ordinary_active["cross_window_read"],
                "cross_window_read_allowed": ordinary_active["cross_window_read_allowed"],
                "active_layered_continuation": ordinary_active["active_layered_continuation"],
            },
            "ordinary_window_without_identity": {
                "memory_scope": ordinary_window_missing["memory_scope"],
                "scope_missing": ordinary_window_missing["scope_missing"],
                "recall_status": scope_missing_status(ordinary_window_missing)["recall_status"],
                "missing_scope_fields": ordinary_window_missing["missing_scope_fields"],
                "cross_window_read": ordinary_window_missing["cross_window_read"],
                "cross_window_read_allowed": ordinary_window_missing["cross_window_read_allowed"],
            },
            "ordinary_raw_pool_without_flag": {
                "memory_scope": client_a_raw_pool_without_flag["memory_scope"],
                "scope_missing": client_a_raw_pool_without_flag["scope_missing"],
                "recall_status": scope_missing_status(client_a_raw_pool_without_flag)["recall_status"],
                "missing_scope_fields": client_a_raw_pool_without_flag["missing_scope_fields"],
                "cross_window_read": client_a_raw_pool_without_flag["cross_window_read"],
                "cross_window_read_allowed": client_a_raw_pool_without_flag["cross_window_read_allowed"],
            },
            "second_client_raw_pool_without_flag": {
                "memory_scope": client_b_raw_pool_without_flag["memory_scope"],
                "scope_missing": client_b_raw_pool_without_flag["scope_missing"],
                "recall_status": scope_missing_status(client_b_raw_pool_without_flag)["recall_status"],
                "missing_scope_fields": client_b_raw_pool_without_flag["missing_scope_fields"],
                "cross_window_read": client_b_raw_pool_without_flag["cross_window_read"],
                "cross_window_read_allowed": client_b_raw_pool_without_flag["cross_window_read_allowed"],
            },
            "raw_pool_with_explicit_flag": {
                "memory_scope": client_a_raw_pool_with_flag["memory_scope"],
                "scope_missing": client_a_raw_pool_with_flag["scope_missing"],
                "cross_window_read": client_a_raw_pool_with_flag["cross_window_read"],
                "cross_window_read_allowed": client_a_raw_pool_with_flag["cross_window_read_allowed"],
                "cross_window_permission_explicit": client_a_raw_pool_with_flag["cross_window_permission_explicit"],
                "cross_window_reason": client_a_raw_pool_with_flag["cross_window_reason"],
                "same_result_for_second_client": (
                    client_a_raw_pool_with_flag["cross_window_read_allowed"]
                    == client_b_raw_pool_with_flag["cross_window_read_allowed"]
                    and client_a_raw_pool_with_flag["scope_missing"]
                    == client_b_raw_pool_with_flag["scope_missing"]
                ),
            },
        },
    }


# Backward-compatible private names used by the raw gateway.
_normalize_memory_scope = normalize_memory_scope
_source_system_from_consumer = source_system_from_consumer
_resolve_recall_scope = resolve_recall_scope
_scope_missing_status = scope_missing_status
_normalize_cross_window_reason = normalize_cross_window_reason
_truthy = truthy
