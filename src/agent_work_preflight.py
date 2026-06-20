#!/usr/bin/env python3
"""Agent Work Preflight wrapper over Zhiyi/Xingce preflight.

This is not a memory layer. It converts the existing source-backed preflight
payload into a small execution gate: what the agent should notice before work,
how to classify the situation, and which receipt proves the decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List


WORK_PREFLIGHT_VERSION = "2026.6.20"
WORK_PREFLIGHT_CONTRACT = "agent_work_preflight.v2026.6.20"
PREFLIGHT_ANSWER_DEBUG_CAPABILITY_CONTRACT = "preflight_answer_debug_capability.v2026.6.18"
DIALOG_ENTRY_ANSWER_DEBUG_CONTRACT = "dialog_entry_answer_debug.v2026.6.18"
EVIDENCE_BOUND_MODEL_CONTRACT = "evidence_bound_model.v2026.6.18"
EVIDENCE_BOUND_MODEL_GATING_CONTRACT = "evidence_bound_model_gating.v2026.6.18"
CLASSIFICATIONS = {
    "already_built_but_forgotten",
    "built_but_miswired",
    "diagnostic_gap",
    "actually_missing",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in ("", None):
        return []
    return [value]


def _bool_or_default(mapping: Dict[str, Any], key: str, default: bool) -> bool:
    if key not in mapping:
        return default
    value = mapping.get(key)
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _text_blob(*values: Any) -> str:
    return "\n".join(str(value or "") for value in values).lower()


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _surface_text(surface: Dict[str, Any]) -> str:
    return _text_blob(
        surface.get("library_id"),
        surface.get("library_shelf"),
        surface.get("title"),
        surface.get("summary"),
        surface.get("rank_reason"),
        surface.get("why_surface"),
        surface.get("matched_by"),
    )


def _classification_from_preflight(preflight: Dict[str, Any]) -> str:
    decision = str(preflight.get("decision") or "")
    if decision == "scope_required":
        return "diagnostic_gap"
    if decision in {"skip", "silent"} and not preflight.get("must_surface"):
        return "actually_missing"

    surfaces = preflight.get("must_surface") if isinstance(preflight.get("must_surface"), list) else []
    blob = _text_blob(
        preflight.get("query"),
        preflight.get("recall_status"),
        preflight.get("reason"),
        preflight.get("do_not_repeat"),
        preflight.get("acceptance_checks"),
        *(_surface_text(surface) for surface in surfaces if isinstance(surface, dict)),
    )
    if _contains_any(blob, ("miswired", "wrong config", "错配", "接错", "没接好", "配置漂移", "source_system")):
        return "built_but_miswired"
    if _contains_any(blob, ("already built", "existing mechanism", "已有", "已做", "已经做", "现有", "不是新造", "不要新造")):
        return "already_built_but_forgotten"
    if _contains_any(blob, ("diagnostic", "doctor", "status", "诊断", "自检", "缺诊断", "没有诊断")):
        return "diagnostic_gap"
    if surfaces:
        return "already_built_but_forgotten"
    return "actually_missing"


def _evidence_summary(preflight: Dict[str, Any]) -> List[Dict[str, Any]]:
    surfaces = preflight.get("must_surface") if isinstance(preflight.get("must_surface"), list) else []
    evidence: List[Dict[str, Any]] = []
    for surface in surfaces[:3]:
        if not isinstance(surface, dict):
            continue
        evidence.append({
            "library_id": surface.get("library_id", ""),
            "library_shelf": surface.get("library_shelf", ""),
            "title": _compact(surface.get("title") or surface.get("summary"), 120),
            "summary": _compact(surface.get("summary"), 220),
            "source_system": surface.get("source_system", ""),
            "source_path": surface.get("source_path", ""),
            "session_id": surface.get("session_id", ""),
            "canonical_window_id": surface.get("canonical_window_id", ""),
            "project_id": surface.get("project_id", ""),
            "raw_evidence_status": surface.get("raw_evidence_status", ""),
            "score": surface.get("score"),
        })
    return evidence


def _changed_behavior(classification: str, preflight: Dict[str, Any]) -> List[str]:
    changes: List[str] = []
    if classification == "already_built_but_forgotten":
        changes.append("Check the existing mechanism before creating a new one.")
    elif classification == "built_but_miswired":
        changes.append("Debug wiring, routing, or host-specific config before adding features.")
    elif classification == "diagnostic_gap":
        changes.append("Run or add a narrow diagnostic before claiming the feature is missing.")
    elif classification == "actually_missing":
        changes.append("Proceed as new work only after the source-backed preflight found no relevant mechanism.")
    if preflight.get("do_not_repeat"):
        changes.append("Avoid repeating the surfaced prior mistake or rejected direction.")
    if preflight.get("acceptance_checks"):
        changes.append("Use the surfaced acceptance checks as the first verification checklist.")
    return changes[:5]


def _agent_instruction(classification: str) -> str:
    if classification == "already_built_but_forgotten":
        return "Start from the existing feature, docs, tests, or tool surfaced by memory; do not design a duplicate path first."
    if classification == "built_but_miswired":
        return "Inspect the connection path and host/window binding before changing core behavior."
    if classification == "diagnostic_gap":
        return "Make the missing diagnostic visible, then decide whether code changes are needed."
    return "Treat this as potentially missing, but keep the claim provisional until normal repo/runtime inspection confirms it."


def build_agent_work_preflight(
    query: str,
    *,
    preflight_payload: Dict[str, Any] | None = None,
    consumer: str = "",
    request_id: str = "",
) -> Dict[str, Any]:
    preflight = preflight_payload if isinstance(preflight_payload, dict) else {}
    classification = _classification_from_preflight(preflight)
    evidence = _evidence_summary(preflight)
    do_not_repeat = [_compact(item, 180) for item in _as_list(preflight.get("do_not_repeat")) if str(item or "").strip()][:6]
    acceptance_checks = [_compact(item, 180) for item in _as_list(preflight.get("acceptance_checks")) if str(item or "").strip()][:6]
    consumer = consumer or str(preflight.get("consumer") or "unknown")
    request_id = request_id or str(preflight.get("request_id") or "")
    should_intervene = classification != "actually_missing" or bool(preflight.get("should_surface"))
    answer_debug_available = _bool_or_default(preflight, "answer_debug_available", True)
    answer_debug_capability_contract = (
        preflight.get("answer_debug_capability_contract")
        or PREFLIGHT_ANSWER_DEBUG_CAPABILITY_CONTRACT
    )
    dialog_answer_debug_contract = (
        preflight.get("dialog_entry_answer_debug_contract")
        or DIALOG_ENTRY_ANSWER_DEBUG_CONTRACT
    )
    evidence_model_contract = preflight.get("evidence_bound_model_contract") or EVIDENCE_BOUND_MODEL_CONTRACT
    evidence_gating_contract = (
        preflight.get("evidence_bound_model_gating_contract")
        or EVIDENCE_BOUND_MODEL_GATING_CONTRACT
    )
    answer_model_call_policy = preflight.get("answer_model_call_policy") or "auto"
    receipt = {
        "consumer": consumer,
        "request_id": request_id,
        "consumed_at": _now(),
        "receipt_scope": "agent_work_preflight_read_only",
        "classification": classification,
        "read_only": True,
        "write_performed": False,
        "memory_write": False,
        "platform_write": False,
        "preflight_contract": preflight.get("contract", ""),
        "used_library_ids": [item.get("library_id") for item in evidence if item.get("library_id")],
        "source_refs_count": preflight.get("source_refs_count", 0),
        "raw_items_count": preflight.get("raw_items_count", 0),
        "answer_debug_available": answer_debug_available,
        "answer_debug_capability_contract": answer_debug_capability_contract,
        "dialog_entry_answer_debug_contract": dialog_answer_debug_contract,
        "evidence_bound_model_contract": evidence_model_contract,
        "evidence_bound_model_gating_contract": evidence_gating_contract,
        "answer_model_call_policy": answer_model_call_policy,
        "library_index_projection_used": bool(preflight.get("library_index_projection_used", False)),
        "library_index_projection_refs_count": int(preflight.get("library_index_projection_refs_count") or 0),
        "library_index_projection_policy": preflight.get("library_index_projection_policy", ""),
        "library_index_projection_soft_weight_policy": preflight.get("library_index_projection_soft_weight_policy", ""),
        "library_index_projection_soft_weight": int(preflight.get("library_index_projection_soft_weight") or 0),
        "preflight_score_policy": preflight.get("preflight_score_policy", ""),
        "raw_recall_trajectory_contract": preflight.get("raw_recall_trajectory_contract", ""),
        "raw_recall_trajectory_policy": preflight.get("raw_recall_trajectory_policy", ""),
    }
    return {
        "ok": True,
        "mode": "work_preflight",
        "version": WORK_PREFLIGHT_VERSION,
        "contract": WORK_PREFLIGHT_CONTRACT,
        "source_preflight_contract": preflight.get("contract", ""),
        "created_at": _now(),
        "consumer": consumer,
        "request_id": request_id,
        "query": query or preflight.get("query", ""),
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "answer_debug_available": answer_debug_available,
        "answer_debug_capability_contract": answer_debug_capability_contract,
        "dialog_entry_answer_debug_contract": dialog_answer_debug_contract,
        "evidence_bound_model_contract": evidence_model_contract,
        "evidence_bound_model_gating_contract": evidence_gating_contract,
        "answer_model_call_policy": answer_model_call_policy,
        "answer_debug_capability": (
            preflight.get("answer_debug_capability")
            if isinstance(preflight.get("answer_debug_capability"), dict)
            else {}
        ),
        "classification": classification,
        "classification_options": sorted(CLASSIFICATIONS),
        "should_intervene": should_intervene,
        "intervention_level": "must_surface" if preflight.get("should_surface") else "diagnostic" if classification == "diagnostic_gap" else "provisional",
        "decision": preflight.get("decision", ""),
        "prompt_class": preflight.get("prompt_class", ""),
        "auto_entry_state": preflight.get("auto_entry_state", ""),
        "recall_status": preflight.get("recall_status", ""),
        "scope_missing": bool(preflight.get("scope_missing")),
        "memory_scope": preflight.get("memory_scope", ""),
        "active_layers_used": preflight.get("active_layers_used") or [],
        "fast_window_preflight": preflight.get("fast_window_preflight"),
        "fast_recall_path": preflight.get("fast_recall_path", ""),
        "fast_window_index_status": preflight.get("fast_window_index_status", ""),
        "zhiyi_layer_skipped_for_fast_preflight": preflight.get("zhiyi_layer_skipped_for_fast_preflight"),
        "raw_recall_trajectory_contract": preflight.get("raw_recall_trajectory_contract", ""),
        "raw_recall_trajectory_policy": preflight.get("raw_recall_trajectory_policy", ""),
        "raw_recall_trajectory": preflight.get("raw_recall_trajectory") if isinstance(preflight.get("raw_recall_trajectory"), list) else [],
        "library_index_projection_contract": preflight.get("library_index_projection_contract", ""),
        "library_index_projection_policy": preflight.get("library_index_projection_policy", ""),
        "library_index_projection_used": bool(preflight.get("library_index_projection_used", False)),
        "library_index_projection_refs_count": int(preflight.get("library_index_projection_refs_count") or 0),
        "library_index_projection_refs": (
            preflight.get("library_index_projection_refs")
            if isinstance(preflight.get("library_index_projection_refs"), list)
            else []
        ),
        "preflight_score_policy": preflight.get("preflight_score_policy", ""),
        "library_index_projection_soft_weight_policy": preflight.get("library_index_projection_soft_weight_policy", ""),
        "library_index_projection_soft_weight": int(preflight.get("library_index_projection_soft_weight") or 0),
        "preflight_score_profile": (
            preflight.get("preflight_score_profile")
            if isinstance(preflight.get("preflight_score_profile"), list)
            else []
        ),
        "context_bundle_contract": preflight.get("context_bundle_contract", ""),
        "context_bundle_policy": preflight.get("context_bundle_policy", ""),
        "context_bundle_window": preflight.get("context_bundle_window", 0),
        "context_bundle_items_count": int(preflight.get("context_bundle_items_count") or 0),
        "context_bundle_refs_count": int(preflight.get("context_bundle_refs_count") or 0),
        "context_bundle_status_counts": preflight.get("context_bundle_status_counts") or {},
        "evidence": evidence,
        "do_not_repeat": do_not_repeat,
        "acceptance_checks": acceptance_checks,
        "changed_behavior": _changed_behavior(classification, preflight),
        "agent_instruction": _agent_instruction(classification),
        "next_action": preflight.get("next_action") or (
            "report_binding_gap_without_claiming_memory_empty"
            if preflight.get("scope_missing")
            else
            "inspect_existing_mechanism_before_editing"
            if classification == "already_built_but_forgotten"
            else "inspect_connection_path_before_feature_work"
            if classification == "built_but_miswired"
            else "run_or_add_narrow_diagnostic_before_claiming_missing"
            if classification == "diagnostic_gap"
            else "continue_with_repo_and_runtime_inspection"
        ),
        "source_refs_required": True,
        "raw_excerpt_returned": False,
        "preflight_receipt": preflight.get("consumer_receipt") or {},
        "consumer_receipt": receipt,
    }


def build_gateway_agent_work_preflight(
    *,
    query: str,
    preflight_builder: Callable[..., Dict[str, Any]],
    preflight_kwargs: Dict[str, Any],
    consumer: str = "",
    request_id: str = "",
) -> Dict[str, Any]:
    kwargs = dict(preflight_kwargs or {})
    has_window_anchor = bool(kwargs.get("canonical_window_id") or kwargs.get("session_id"))
    deep_work_preflight_flags = [
        bool(kwargs.pop(key, False))
        for key in (
            "deep_work_preflight",
            "full_work_preflight",
            "allow_full_work_preflight",
            "allow_cold_work_preflight",
        )
    ]
    deep_work_preflight = any(deep_work_preflight_flags)
    kwargs["query"] = query
    kwargs["force_task_preflight"] = True
    kwargs["fast_window_preflight"] = not (has_window_anchor and deep_work_preflight)
    if not str(kwargs.get("memory_scope") or "").strip():
        kwargs["memory_scope"] = "window"
    if not has_window_anchor:
        for key in ("project_id", "project_root", "workstream_id", "task_id"):
            kwargs[key] = ""
    preflight = preflight_builder(**kwargs)
    payload = build_agent_work_preflight(
        query,
        preflight_payload=preflight,
        consumer=consumer or preflight.get("consumer", ""),
        request_id=request_id,
    )
    passthrough_keys = (
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
        "context_bundle_contract",
        "context_bundle_policy",
        "context_bundle_window",
        "context_bundle_items_count",
        "context_bundle_refs_count",
        "context_bundle_status_counts",
    )
    payload.update({key: preflight.get(key) for key in passthrough_keys if key in preflight})
    return payload
