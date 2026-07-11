#!/usr/bin/env python3
"""Preflight and Tiandao context payload builders for raw recall."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _binding_metadata(binding: Dict[str, Any]) -> Dict[str, Any]:
    metadata = binding.get("metadata") if isinstance(binding.get("metadata"), dict) else {}
    return metadata


def _tiandao_memory_mode_impl(
    namespace: Dict[str, Any],
    memory_scope: str,
    active_layers_used: List[str],
    cross_window_read: bool,
) -> str:
    memory_context_mode_for_routing = namespace["memory_context_mode_for_routing"]
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


def _build_tiandao_context_package_impl(
    namespace: Dict[str, Any],
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
    ACTIVE_MEMORY_ROUTING_CONTRACT = namespace["ACTIVE_MEMORY_ROUTING_CONTRACT"]
    ContextPackage = namespace["ContextPackage"]
    IntentMode = namespace["IntentMode"]
    MemoryContextMode = namespace["MemoryContextMode"]
    SERVICE_VERSION = namespace["SERVICE_VERSION"]
    TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT = namespace["TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT"]
    _is_raw_evidence_status = namespace["_is_raw_evidence_status"]
    _validate_tiandao_context_package = namespace["_validate_tiandao_context_package"]
    active_memory_routing_contract_descriptor = namespace["active_memory_routing_contract_descriptor"]
    if ContextPackage is None or IntentMode is None or MemoryContextMode is None:
        return {
            "schema": "tiandao_context_package.v1",
            "query": query,
            "query_hash": hashlib.sha256((query or "").encode("utf-8")).hexdigest(),
            "source_system": source_system or consumer or "unknown",
            "canonical_window_id": canonical_window_id,
            "session_id": session_id,
            "intent_mode": "evidence",
            "memory_context_mode": _tiandao_memory_mode_impl(namespace, memory_scope, active_layers_used, cross_window_read),
            "active_memory_routing_contract": TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
            "active_layers_used": active_layers_used or [],
            "current_window_binding_applied": bool(binding_applied_fields),
            "cross_window_read": bool(cross_window_read),
            "cross_window_read_allowed": bool(cross_window_read_allowed),
            "tiandao_scope": "tiandao_candidate_projection",
            "private_architecture_subsystem": "time_library",
            "tiandao_face": "memory_context",
            "contract_role": "memory_context_candidate",
            "scope_enforced": True,
            "injection_blocked": bool(scope_missing),
            "block_reason": block_reason,
            "memory_write": False,
            "overclaim_boundary": "does_not_claim_tiandao_runtime_orchestration_system_sync_route_or_central_node",
        }

    mode = _tiandao_memory_mode_impl(namespace, memory_scope, active_layers_used, cross_window_read)
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
        "private_architecture_subsystem": "time_library",
        "tiandao_face": "memory_context",
        "tiandao_routing_contract": active_memory_routing_contract_descriptor()
        if active_memory_routing_contract_descriptor is not None
        else {"contract": TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT},
        "contract_role": "memory_context_candidate",
        "consumer": consumer or "unknown",
        "memory_scope": memory_scope,
        "memory_base_scope": memory_base_scope,
        "overclaim_boundary": "does_not_claim_tiandao_runtime_orchestration_system_sync_route_or_central_node",
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


def capability_check_payload_impl(
    namespace: Dict[str, Any],
    consumer: str = "",
    request_id: str = "",
    source: str = "",
) -> Dict[str, Any]:
    SERVICE_NAME = namespace["SERVICE_NAME"]
    SERVICE_VERSION = namespace["SERVICE_VERSION"]
    _consumer_receipt = namespace["_consumer_receipt"]
    library_manifest = namespace["library_manifest"]
    receipt = _consumer_receipt(consumer, request_id, 0, 0, 0, [])
    receipt["receipt_scope"] = "capability_check_no_recall"
    return {
        "ok": True,
        "mode": "capability_check",
        "service": SERVICE_NAME,
        "server": "time-library",
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


def preflight_payload_impl(
    namespace: Dict[str, Any],
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
    force_task_preflight: bool = False,
    fast_window_preflight: bool = True,
) -> Dict[str, Any]:
    _preflight_has_active_anchor = namespace["_preflight_has_active_anchor"]
    build_zhixing_preflight = namespace["build_zhixing_preflight"]
    classify_prompt = namespace["classify_prompt"]
    hybrid_recall_manifest = namespace["hybrid_recall_manifest"]
    library_manifest = namespace["library_manifest"]
    query_raw_source_refs = namespace["query_raw_source_refs"]
    prompt = classify_prompt(query)
    if force_task_preflight and not bool(prompt.get("should_recall")):
        prompt = {"prompt_class": "task", "should_recall": True, "skip_reason": ""}
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
            prompt_override=prompt,
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
            prompt_override=prompt,
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
        fast_window_preflight=fast_window_preflight,
    )
    preflight = build_zhixing_preflight(
        query,
        recall_payload=recall_payload,
        consumer=consumer or recall_payload.get("consumer", ""),
        request_id=request_id,
        prompt_override=prompt,
    )
    preflight.update({
        "source_system_filter": recall_payload.get("source_system_filter", ""),
        "source_system_filter_aliases": recall_payload.get("source_system_filter_aliases", []),
        "source_collection_filter": recall_payload.get("source_collection_filter", ""),
        "claude_collection_alias_applied": recall_payload.get("claude_collection_alias_applied", False),
        "claude_collection_alias_boundary": recall_payload.get("claude_collection_alias_boundary", ""),
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
        "raw_fallback_status": recall_payload.get("raw_fallback_status", ""),
        "active_empty_window_project_fallback_used": recall_payload.get("active_empty_window_project_fallback_used", False),
        "active_empty_window_project_fallback_status": recall_payload.get("active_empty_window_project_fallback_status", ""),
        "active_empty_window_project_fallback_policy": recall_payload.get("active_empty_window_project_fallback_policy", ""),
        "active_empty_window_project_fallback_source_system_filters": recall_payload.get("active_empty_window_project_fallback_source_system_filters", []),
        "active_empty_window_project_fallback_index_status": recall_payload.get("active_empty_window_project_fallback_index_status", ""),
        "active_empty_window_project_fallback_candidate_count": recall_payload.get("active_empty_window_project_fallback_candidate_count", 0),
        "active_empty_window_project_fallback_routed_count": recall_payload.get("active_empty_window_project_fallback_routed_count", 0),
        "active_empty_window_project_fallback_layers_used": recall_payload.get("active_empty_window_project_fallback_layers_used", []),
        "zhixing_library": recall_payload.get("zhixing_library") or library_manifest(),
        "hybrid_recall": recall_payload.get("hybrid_recall") or hybrid_recall_manifest(),
    })
    return preflight
