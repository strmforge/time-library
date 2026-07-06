"""Read-only platform delivery liveness findings.

This module does not deliver messages, call models, read chat bodies, or write
platform configuration. It normalizes existing diagnostics into one
findings-only contract so search/think work can be designed from observed
delivery behavior instead of assumptions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


PLATFORM_DELIVERY_LIVENESS_CONTRACT = "platform_delivery_liveness_audit.v2026.6.21"
PLATFORM_DELIVERY_FINDING_CONTRACT = "platform_delivery_liveness_finding.v2026.6.21"
DEFAULT_PLATFORMS = ("openclaw", "hermes", "codex", "claude_desktop", "claude_code_cli", "cursor", "pi")
DEFINITION_OF_PROVEN_CELLS = (
    "passive_gate_observed",
    "model_evidence_receipt_observed",
    "answer_evidence_observed",
    "receipt_visibility_observed",
    "security_gate_observed",
)
FORBIDDEN_DELIVERY_SUBSTITUTES = (
    "fixture_backed_model_trace_only",
    "direct_endpoint_controlled_smoke_only",
    "fixture_evidence_bound_model",
    "gateway_injected_model_only",
    "capability_check_only",
    "installed_endpoint_only",
    "repository_tests_only",
    "source_route_only",
    "substring_success_masquerading_as_vector",
    "positive_arm_only",
    "negative_arm_only",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in ("", None):
        return False
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _system_key(platform: str) -> str:
    platform = str(platform or "").strip().lower()
    if platform in {"claude", "claude_desktop", "claude_code"}:
        return "claude_desktop"
    return platform


def _find_autodiscovery_system(autodiscovery: dict[str, Any], platform: str) -> dict[str, Any]:
    wanted = _system_key(platform)
    for item in _items(autodiscovery.get("systems")):
        if str(item.get("system") or "") == wanted:
            return item
    return {}


def _platforms_from_autodiscovery(autodiscovery: dict[str, Any]) -> tuple[str, ...]:
    systems: list[str] = []
    for item in _items(autodiscovery.get("systems")):
        system = str(item.get("system") or "").strip()
        if not system or system == "memcore_cloud":
            continue
        status = str(item.get("status") or "not_found")
        if status == "not_found" and not item.get("connectable_now") and not item.get("intent_signal_detected"):
            continue
        if system not in systems:
            systems.append(system)
    return tuple(systems)


def _action_names(system: dict[str, Any]) -> set[str]:
    return {
        str(action.get("action") or "")
        for action in _items(system.get("actions"))
        if str(action.get("action") or "")
    }


def _passive_state(system: dict[str, Any]) -> str:
    if not system:
        return "unknown"
    status = str(system.get("status") or "not_found")
    if status == "not_found":
        return "not_found"
    if _bool(system.get("connectable_now")):
        return "connection_ready"
    if _bool(system.get("intent_signal_detected")):
        return "partial_connection_signal"
    return "detected_without_connection"


def _recall_trigger(system: dict[str, Any]) -> str:
    actions = _action_names(system)
    if "capability_check" in actions:
        return "capability_check_ready"
    if "auto_connect_missing_thin_adapter" in actions:
        return "auto_connect_missing_thin_adapter"
    if "auto_connect" in actions:
        return "auto_connect_required"
    if "observe_only" in actions:
        return "observe_only"
    return "unknown"


def _source_refs_visible(preflight: dict[str, Any], dialog: dict[str, Any], observed: dict[str, Any]) -> bool:
    if "source_refs_visible" in observed:
        return _bool(observed.get("source_refs_visible"))
    if int(preflight.get("source_refs_count") or 0) > 0:
        return True
    answer_debug = _dict(dialog.get("answer_debug"))
    for item in _items(answer_debug.get("evidence")):
        if _bool(item.get("source_refs_present")):
            return True
    if dialog.get("source_refs"):
        return True
    return False


def _raw_expand_path(preflight: dict[str, Any], observed: dict[str, Any]) -> str:
    if observed.get("raw_expand_path"):
        return str(observed.get("raw_expand_path"))
    if int(preflight.get("raw_items_count") or 0) > 0:
        return "explicit_raw_budget_or_raw_expand_available"
    if _bool(preflight.get("raw_excerpt_returned")):
        return "raw_excerpt_returned"
    return ""


def _dialog_delivery_state(platform: str, dialog: dict[str, Any], observed: dict[str, Any]) -> tuple[str, str]:
    if observed.get("delivered_to_model") or observed.get("delivered_to_user"):
        return (
            str(observed.get("delivered_to_model") or "unknown"),
            str(observed.get("delivered_to_user") or "unknown"),
        )
    delivery = _dict(dialog.get("platform_delivery"))
    trusted_trace = _dict(dialog.get("trusted_memory_delivery_trace"))
    if not trusted_trace and isinstance(dialog.get("trusted_memory_delivery"), dict):
        trusted_trace = _dict(dialog.get("trusted_memory_delivery", {}).get("trace"))
    if trusted_trace.get("model_delivery_state") == "observed":
        return ("observed", "observed" if _bool(delivery.get("visible_reply_ok")) else "not_measured")
    answer_debug = _dict(dialog.get("answer_debug"))
    model_call = _dict(dialog.get("model_call") or answer_debug.get("model_call"))
    if str(platform) == "openclaw" and delivery.get("delivery_method") == "before_dispatch_return":
        return ("preempted_provider_model", "observed" if _bool(delivery.get("visible_reply_ok")) else "not_observed")
    if _bool(model_call.get("called")) or _bool(model_call.get("request_sent")):
        return ("observed", "not_measured")
    if delivery:
        if _bool(delivery.get("executed")) or _bool(delivery.get("visible_reply_ok")):
            return ("not_measured", "observed")
        return ("not_measured", "not_observed")
    return ("not_measured", "not_measured")


def _trusted_memory_trace(dialog: dict[str, Any]) -> dict[str, Any]:
    trace = _dict(dialog.get("trusted_memory_delivery_trace"))
    if trace:
        return trace
    trusted_delivery = _dict(dialog.get("trusted_memory_delivery"))
    return _dict(trusted_delivery.get("trace"))


def _definition_of_proven_metadata(dialog: dict[str, Any]) -> dict[str, Any]:
    trace = _trusted_memory_trace(dialog)
    cells = _dict(trace.get("cells"))
    normalized_cells = {
        name: bool(cells.get(name, False))
        for name in DEFINITION_OF_PROVEN_CELLS
    }
    missing_cells = [
        str(item)
        for item in (trace.get("missing_cells") if isinstance(trace.get("missing_cells"), list) else [])
        if str(item)
    ]
    if cells and not missing_cells:
        missing_cells = [name for name, value in normalized_cells.items() if not value]
    trace_status = str(trace.get("status") or "")
    model_state = str(trace.get("model_delivery_state") or trace.get("delivered_to_model") or "")
    forbidden_present = [
        str(item)
        for item in (
            trace.get("forbidden_substitutes_present")
            if isinstance(trace.get("forbidden_substitutes_present"), list)
            else []
        )
        if str(item)
    ]
    for key in FORBIDDEN_DELIVERY_SUBSTITUTES:
        if _bool(trace.get(key)) and key not in forbidden_present:
            forbidden_present.append(key)
    observed = bool(
        trace
        and trace_status == "proven"
        and model_state == "observed"
        and normalized_cells
        and all(normalized_cells.values())
        and not forbidden_present
    )
    return {
        "trusted_memory_trace_present": bool(trace),
        "trusted_memory_trace_status": trace_status,
        "trusted_memory_model_delivery_state": model_state,
        "forbidden_substitutes_present": forbidden_present,
        "definition_of_proven_cells": normalized_cells,
        "definition_of_proven_missing_cells": missing_cells,
        "definition_of_proven_observed": observed,
    }


def _answer_owner(dialog: dict[str, Any], observed: dict[str, Any]) -> tuple[str, bool]:
    if observed.get("answer_owner"):
        owner = str(observed.get("answer_owner"))
        return owner, "fallback" in owner or "draft" in owner or owner.startswith("local_")
    answer_debug = _dict(dialog.get("answer_debug"))
    model_call = _dict(dialog.get("model_call") or answer_debug.get("model_call"))
    source = str(dialog.get("answer_source") or answer_debug.get("answer_source") or "")
    if source:
        local_fallback = source in {
            "zhiyi_direct_natural_fallback_after_model_no_answer",
            "local_draft",
            "draft",
        } or "fallback" in source
        return source, local_fallback
    if _bool(model_call.get("called")):
        return "model_call_without_answer_source", False
    if _bool(model_call.get("fallback_applied")):
        return "model_fallback_applied_without_answer_source", True
    if dialog.get("answer"):
        return "unattributed_answer", True
    return "none_observed", False


def _boundary_metadata(preflight: dict[str, Any], autodiscovery_system: dict[str, Any], dialog: dict[str, Any]) -> dict[str, Any]:
    delivery = _dict(dialog.get("platform_delivery"))
    return {
        "memory_scope": preflight.get("memory_scope", ""),
        "memory_base_scope": preflight.get("memory_base_scope", ""),
        "recall_status": preflight.get("recall_status", ""),
        "scope_missing": bool(preflight.get("scope_missing", False)),
        "cross_window_read": bool(preflight.get("cross_window_read", False)),
        "cross_window_read_allowed": bool(preflight.get("cross_window_read_allowed", True)),
        "active_layers_used": preflight.get("active_layers_used") or [],
        "content_gate": autodiscovery_system.get("content_gate", ""),
        "connectable_now": bool(autodiscovery_system.get("connectable_now", False)),
        "platform_delivery_executed": bool(delivery.get("executed", False)),
        "platform_delivery_reason": delivery.get("reason", ""),
    }


def _risks(
    *,
    platform: str,
    system: dict[str, Any],
    preflight: dict[str, Any],
    delivered_to_model: str,
    source_refs_visible: bool,
    local_draft_detected: bool,
    dialog: dict[str, Any],
) -> list[str]:
    risks: list[str] = []
    if not system or str(system.get("status") or "") == "not_found":
        risks.append("platform_not_detected")
    elif delivered_to_model in {"not_measured", "unknown"}:
        risks.append("connection_signal_only_not_delivery_proof")
    if not source_refs_visible:
        risks.append("source_refs_not_visible")
    if local_draft_detected:
        risks.append("local_draft_or_fallback_answer_detected")
    if _bool(preflight.get("scope_missing")):
        risks.append("scope_missing_or_unbound_window")
    if _bool(preflight.get("cross_window_read")):
        risks.append("cross_window_read_observed")
    delivery = _dict(dialog.get("platform_delivery"))
    if delivery and _bool(delivery.get("executed")):
        risks.append("platform_act_delivery_is_not_passive")
    if platform == "hermes" and _bool(preflight.get("cross_window_read")):
        risks.append("hermes_should_remain_current_window_or_explicit_raw_pool")
    return risks


def _recommended_next_contract(risks: list[str]) -> str:
    if "local_draft_or_fallback_answer_detected" in risks:
        return "expose_answer_owner_and_block_local_draft_as_think"
    if "source_refs_not_visible" in risks:
        return "add_delivery_receipt_source_refs"
    if "connection_signal_only_not_delivery_proof" in risks:
        return "run_live_passive_delivery_probe"
    if "scope_missing_or_unbound_window" in risks:
        return "surface_scope_binding_gap"
    if "platform_act_delivery_is_not_passive" in risks:
        return "separate_platform_act_from_passive_delivery_audit"
    return "ready_for_search_think_contract_design"


def _finding(
    platform: str,
    *,
    autodiscovery: dict[str, Any],
    preflight: dict[str, Any],
    dialog: dict[str, Any],
    observed: dict[str, Any],
) -> dict[str, Any]:
    system = _find_autodiscovery_system(autodiscovery, platform)
    delivered_to_model, delivered_to_user = _dialog_delivery_state(platform, dialog, observed)
    source_refs_visible = _source_refs_visible(preflight, dialog, observed)
    answer_owner, local_draft = _answer_owner(dialog, observed)
    proof_metadata = _definition_of_proven_metadata(dialog)
    risks = _risks(
        platform=platform,
        system=system,
        preflight=preflight,
        delivered_to_model=delivered_to_model,
        source_refs_visible=source_refs_visible,
        local_draft_detected=local_draft,
        dialog=dialog,
    )
    observed_forbidden = [
        str(item)
        for item in (
            observed.get("forbidden_substitutes_present")
            if isinstance(observed.get("forbidden_substitutes_present"), list)
            else []
        )
        if str(item)
    ]
    if observed_forbidden:
        merged = list(proof_metadata.get("forbidden_substitutes_present") or [])
        for item in observed_forbidden:
            if item not in merged:
                merged.append(item)
        proof_metadata["forbidden_substitutes_present"] = merged
    if proof_metadata.get("forbidden_substitutes_present"):
        risks.append("forbidden_substitute_delivery_proof")
    return {
        "contract": PLATFORM_DELIVERY_FINDING_CONTRACT,
        "platform": platform,
        "passive_state": observed.get("passive_state") or _passive_state(system),
        "recall_trigger": observed.get("recall_trigger") or _recall_trigger(system),
        "delivered_to_model": delivered_to_model,
        "delivered_to_user": delivered_to_user,
        "source_refs_visible": source_refs_visible,
        "raw_expand_path": _raw_expand_path(preflight, observed),
        "answer_owner": answer_owner,
        "local_draft_detected": local_draft,
        **proof_metadata,
        "boundary_metadata": _boundary_metadata(preflight, system, dialog),
        "gap": risks[:],
        "risk": risks,
        "recommended_next_contract": _recommended_next_contract(risks),
    }


def build_platform_delivery_liveness_audit(
    *,
    autodiscovery_payload: dict[str, Any] | None = None,
    preflight_payload: dict[str, Any] | None = None,
    dialog_result: dict[str, Any] | None = None,
    observed_platforms: dict[str, dict[str, Any]] | None = None,
    platforms: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Build a read-only Phase-0 delivery liveness audit from existing signals."""
    autodiscovery = _dict(autodiscovery_payload)
    preflight = _dict(preflight_payload)
    dialog = _dict(dialog_result)
    observed = observed_platforms if isinstance(observed_platforms, dict) else {}
    selected = tuple(platforms or _platforms_from_autodiscovery(autodiscovery) or DEFAULT_PLATFORMS)
    findings = [
        _finding(
            str(platform),
            autodiscovery=autodiscovery,
            preflight=preflight,
            dialog=dialog,
            observed=_dict(observed.get(str(platform))),
        )
        for platform in selected
    ]
    risks = sorted({risk for item in findings for risk in item.get("risk", [])})
    return {
        "ok": True,
        "contract": PLATFORM_DELIVERY_LIVENESS_CONTRACT,
        "created_at": _now(),
        "mode": "platform_delivery_liveness_audit",
        "phase": "phase0_findings_only",
        "read_only": True,
        "findings_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "not_a_delivery_mechanism": True,
        "not_a_model_answerer": True,
        "final_evidence_authority": "raw_source_refs",
        "platforms": findings,
        "counts": {
            "platforms_total": len(findings),
            "platforms_with_source_refs_visible": sum(1 for item in findings if item.get("source_refs_visible")),
            "platforms_with_model_delivery_observed": sum(1 for item in findings if item.get("delivered_to_model") == "observed"),
            "platforms_with_user_delivery_observed": sum(1 for item in findings if item.get("delivered_to_user") == "observed"),
            "platforms_with_local_draft_detected": sum(1 for item in findings if item.get("local_draft_detected")),
            "risk_count": len(risks),
        },
        "risks": risks,
        "next_action": (
            "resolve_phase0_delivery_findings_before_search_think_work"
            if risks
            else "ready_for_search_think_contract_design"
        ),
    }


__all__ = [
    "PLATFORM_DELIVERY_LIVENESS_CONTRACT",
    "PLATFORM_DELIVERY_FINDING_CONTRACT",
    "DEFAULT_PLATFORMS",
    "build_platform_delivery_liveness_audit",
]
