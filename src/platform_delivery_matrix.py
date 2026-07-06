"""Compact findings-only matrix for platform delivery liveness."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from src.platform_delivery_liveness import (
        DEFAULT_PLATFORMS,
        PLATFORM_DELIVERY_LIVENESS_CONTRACT,
        build_platform_delivery_liveness_audit,
    )
except Exception:  # pragma: no cover - direct script import fallback
    from platform_delivery_liveness import (
        DEFAULT_PLATFORMS,
        PLATFORM_DELIVERY_LIVENESS_CONTRACT,
        build_platform_delivery_liveness_audit,
    )


PLATFORM_DELIVERY_MATRIX_CONTRACT = "platform_delivery_liveness_matrix.v2026.6.21"
PLATFORM_DELIVERY_7OF7_GATE_CONTRACT = "platform_delivery_7of7_gate.v2026.6.25"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _extract_proof_scope_matrix(source: dict[str, Any]) -> dict[str, Any]:
    direct = _dict(source.get("proof_scope_matrix"))
    if direct:
        return direct
    for key in ("trusted_memory_trust_metrics", "trust_metrics"):
        nested = _dict(source.get(key))
        if nested:
            matrix = _dict(nested.get("proof_scope_matrix"))
            if matrix:
                return matrix
    return {}


def _proof_scope_rows(matrix: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("proof_scope") or ""): row
        for row in _items(matrix.get("rows"))
        if str(row.get("proof_scope") or "")
    }


def _proof_scope_row_projection(row: dict[str, Any]) -> dict[str, Any]:
    if not row:
        return {
            "proof_state": "not_reported",
            "cases_checked": 0,
            "scope_count": 0,
            "record_kinds": [],
            "model_delivery_observed_cases": 0,
            "claim_boundary": "",
        }
    return {
        "proof_state": str(row.get("proof_state") or ""),
        "evidence_source": str(row.get("evidence_source") or ""),
        "cases_checked": int(row.get("cases_checked") or 0),
        "scope_count": int(row.get("scope_count") or 0),
        "record_kinds": [
            str(item)
            for item in (row.get("record_kinds") if isinstance(row.get("record_kinds"), list) else [])
        ],
        "reads_installed_user_work_records": bool(row.get("reads_installed_user_work_records", False)),
        "model_delivery_observed_cases": int(row.get("model_delivery_observed_cases") or 0),
        "platform_wide": bool(row.get("platform_wide", False)),
        "broad_all_records": bool(row.get("broad_all_records", False)),
        "claim_boundary": str(row.get("claim_boundary") or ""),
        "non_claims": [
            str(item)
            for item in (row.get("non_claims") if isinstance(row.get("non_claims"), list) else [])
        ],
    }


def _proof_scope_projection(matrix: dict[str, Any]) -> dict[str, Any]:
    if not matrix:
        return {
            "available": False,
            "scope_or_casefile_proof_is_not_platform_wide_proof": True,
            "platform_matrix_can_only_mark_platform_proven_from_platform_traces": True,
            "rows": {},
        }
    rows = _proof_scope_rows(matrix)
    scoped = _proof_scope_row_projection(rows.get("scoped_installed_zhiyi_xingce_user_work_records", {}))
    platform = _proof_scope_row_projection(rows.get("platform_wide_delivery", {}))
    all_records = _proof_scope_row_projection(rows.get("all_records_all_scopes", {}))
    return {
        "available": True,
        "contract": str(matrix.get("contract") or ""),
        "public_claim_rule": str(matrix.get("public_claim_rule") or ""),
        "scope_filters": [
            str(item)
            for item in (matrix.get("scope_filters") if isinstance(matrix.get("scope_filters"), list) else [])
        ],
        "casefile_cases": [
            str(item)
            for item in (matrix.get("casefile_cases") if isinstance(matrix.get("casefile_cases"), list) else [])
        ],
        "scoped_installed_user_work_records": scoped,
        "platform_wide_delivery": platform,
        "all_records_all_scopes": all_records,
        "scope_or_casefile_proof_is_not_platform_wide_proof": True,
        "platform_matrix_can_only_mark_platform_proven_from_platform_traces": True,
        "platform_wide_claim_allowed": platform.get("proof_state") == "platform_wide_delivery_proven",
    }


def _risk_level(item: dict[str, Any]) -> str:
    risks = set(item.get("risk") or [])
    if (
        "local_draft_or_fallback_answer_detected" in risks
        or "platform_act_delivery_is_not_passive" in risks
        or "forbidden_substitute_delivery_proof" in risks
    ):
        return "blocker"
    if "platform_not_detected" in risks or "source_refs_not_visible" in risks:
        return "attention"
    if "connection_signal_only_not_delivery_proof" in risks or "scope_missing_or_unbound_window" in risks:
        return "unproven"
    return "ready"


def _platform_proof_state(item: dict[str, Any]) -> str:
    if item.get("local_draft_detected"):
        return "blocked_by_local_draft"
    if item.get("forbidden_substitutes_present"):
        return "blocked_by_forbidden_substitute"
    if item.get("definition_of_proven_observed") is True:
        return "platform_delivery_proven"
    if str(item.get("delivered_to_model") or "") in {"not_measured", "unknown", ""}:
        return "platform_delivery_unproven_model_not_measured"
    if str(item.get("trusted_memory_trace_status") or "") == "unproven":
        return "platform_delivery_unproven_missing_definition_cells"
    if item.get("trusted_memory_trace_present"):
        return "platform_delivery_unproven_trace_incomplete"
    return "platform_delivery_unproven_no_trace"


def _platform_row(item: dict[str, Any]) -> dict[str, Any]:
    proof_state = _platform_proof_state(item)
    return {
        "platform": str(item.get("platform") or ""),
        "passive_state": str(item.get("passive_state") or ""),
        "recall_trigger": str(item.get("recall_trigger") or ""),
        "source_refs_visible": bool(item.get("source_refs_visible", False)),
        "raw_expand_path": str(item.get("raw_expand_path") or ""),
        "delivered_to_model": str(item.get("delivered_to_model") or "not_measured"),
        "delivered_to_user": str(item.get("delivered_to_user") or "not_measured"),
        "answer_owner": str(item.get("answer_owner") or ""),
        "local_draft_detected": bool(item.get("local_draft_detected", False)),
        "platform_proof_state": proof_state,
        "platform_delivery_proven": proof_state == "platform_delivery_proven",
        "trusted_memory_trace_present": bool(item.get("trusted_memory_trace_present", False)),
        "trusted_memory_trace_status": str(item.get("trusted_memory_trace_status") or ""),
        "trusted_memory_model_delivery_state": str(item.get("trusted_memory_model_delivery_state") or ""),
        "forbidden_substitutes_present": [
            str(item)
            for item in (
                item.get("forbidden_substitutes_present")
                if isinstance(item.get("forbidden_substitutes_present"), list)
                else []
            )
        ],
        "definition_of_proven_observed": bool(item.get("definition_of_proven_observed", False)),
        "definition_of_proven_cells": item.get("definition_of_proven_cells") if isinstance(item.get("definition_of_proven_cells"), dict) else {},
        "definition_of_proven_missing_cells": [
            str(cell)
            for cell in (item.get("definition_of_proven_missing_cells") if isinstance(item.get("definition_of_proven_missing_cells"), list) else [])
        ],
        "risk_level": _risk_level(item),
        "risk": [str(risk) for risk in item.get("risk", [])],
        "gap": [str(gap) for gap in item.get("gap", [])],
        "recommended_next_contract": str(item.get("recommended_next_contract") or ""),
    }


def _next_actions(rows: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if any(row["local_draft_detected"] for row in rows):
        actions.append("block_local_draft_or_fallback_as_think_answer")
    if any(row["delivered_to_model"] in {"not_measured", "unknown"} for row in rows):
        actions.append("run_platform_specific_passive_delivery_probe_before_claiming_model_delivery")
    if any(row["platform_proof_state"] == "platform_delivery_unproven_missing_definition_cells" for row in rows):
        actions.append("complete_all_definition_of_proven_cells_before_claiming_platform_proof")
    if any(row["forbidden_substitutes_present"] for row in rows):
        actions.append("remove_fixture_endpoint_or_gateway_substitutes_from_delivery_proof")
    if any(not row["source_refs_visible"] for row in rows):
        actions.append("add_or_fix_delivery_receipt_source_refs_for_platforms_missing_refs")
    if any(row["platform_proof_state"] != "platform_delivery_proven" for row in rows):
        actions.append("complete_7of7_platform_delivery_gate_before_release_claim")
    if any(row["risk_level"] == "ready" for row in rows):
        actions.append("use_ready_rows_only_as_search_think_contract_design_input")
    if not actions:
        actions.append("ready_for_platform_delivery_ui_or_contract_design")
    return actions


def _canonical_platform(value: Any) -> str:
    platform = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "claude": "claude_desktop",
        "claude_desktop": "claude_desktop",
        "claude_code": "claude_code_cli",
        "claude_code_cli": "claude_code_cli",
        "open_claw": "openclaw",
    }
    return aliases.get(platform, platform)


def _required_platform_list(value: Any = None) -> list[str]:
    raw = value if isinstance(value, (list, tuple)) else DEFAULT_PLATFORMS
    result: list[str] = []
    for item in raw:
        platform = _canonical_platform(item)
        if platform and platform not in result:
            result.append(platform)
    return result


def _build_7of7_gate(rows: list[dict[str, Any]], *, required_platforms: Any = None) -> dict[str, Any]:
    required = _required_platform_list(required_platforms)
    by_platform: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        platform = _canonical_platform(row.get("platform"))
        if not platform:
            continue
        if platform in by_platform and platform not in duplicates:
            duplicates.append(platform)
        by_platform.setdefault(platform, row)

    observed = list(by_platform.keys())
    missing = [platform for platform in required if platform not in by_platform]
    extra = [platform for platform in observed if platform not in required]
    unproven = [
        platform
        for platform in required
        if platform in by_platform and not by_platform[platform].get("platform_delivery_proven")
    ]
    model_not_observed = [
        platform
        for platform in required
        if platform in by_platform and by_platform[platform].get("delivered_to_model") != "observed"
    ]
    user_receipt_not_observed = [
        platform
        for platform in required
        if platform in by_platform and by_platform[platform].get("delivered_to_user") != "observed"
    ]
    blocked = [
        platform
        for platform in required
        if platform in by_platform and by_platform[platform].get("risk_level") == "blocker"
    ]
    forbidden = {
        platform: list(by_platform[platform].get("forbidden_substitutes_present") or [])
        for platform in required
        if platform in by_platform and by_platform[platform].get("forbidden_substitutes_present")
    }
    fail_reasons: list[str] = []
    if missing:
        fail_reasons.append("missing_required_platforms")
    if duplicates:
        fail_reasons.append("duplicate_platform_rows")
    if unproven:
        fail_reasons.append("unproven_required_platforms")
    if model_not_observed:
        fail_reasons.append("model_delivery_not_observed")
    if user_receipt_not_observed:
        fail_reasons.append("user_receipt_not_observed")
    if blocked:
        fail_reasons.append("blocked_platform_rows")
    if forbidden:
        fail_reasons.append("forbidden_substitute_present")

    proven = not fail_reasons and len(required) == 7
    return {
        "contract": PLATFORM_DELIVERY_7OF7_GATE_CONTRACT,
        "platform_delivery_7_of_7_proven": proven,
        "proof_state": "platform_delivery_7_of_7_proven" if proven else "7_of_7_not_proven",
        "required_platforms": required,
        "required_count": len(required),
        "observed_platforms": observed,
        "observed_count": len(observed),
        "proven_platforms": [
            platform
            for platform in required
            if platform in by_platform and by_platform[platform].get("platform_delivery_proven")
        ],
        "missing_platforms": missing,
        "extra_platforms": extra,
        "duplicate_platforms": duplicates,
        "unproven_platforms": unproven,
        "model_delivery_not_observed": model_not_observed,
        "user_receipt_not_observed": user_receipt_not_observed,
        "blocked_platforms": blocked,
        "forbidden_substitutes_by_platform": forbidden,
        "fail_reasons": fail_reasons,
        "proof_rule": "all seven required platforms must have observed real platform model delivery, observed user receipt, all Definition-of-Proven cells true, and no forbidden substitutes",
        "non_claims": [
            "capability_check_is_not_delivery_proof",
            "skill_installed_is_not_delivery_proof",
            "endpoint_or_fixture_success_is_not_platform_delivery_proof",
            "source_refs_visible_locally_is_not_answer_use",
            "one_platform_proof_does_not_imply_7of7",
        ],
    }


def build_platform_delivery_matrix(
    payload: dict[str, Any] | None = None,
    *,
    autodiscovery_payload: dict[str, Any] | None = None,
    preflight_payload: dict[str, Any] | None = None,
    dialog_result: dict[str, Any] | None = None,
    observed_platforms: dict[str, dict[str, Any]] | None = None,
    platforms: list[str] | tuple[str, ...] | None = None,
    required_platforms: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    source = _dict(payload)
    audit = _dict(source.get("platform_delivery_liveness"))
    if not audit and source.get("contract") == PLATFORM_DELIVERY_LIVENESS_CONTRACT:
        audit = source
    if not audit:
        audit = build_platform_delivery_liveness_audit(
            autodiscovery_payload=autodiscovery_payload,
            preflight_payload=preflight_payload,
            dialog_result=dialog_result,
            observed_platforms=observed_platforms,
            platforms=platforms,
        )
    proof_scope_matrix = _extract_proof_scope_matrix(source)
    rows = [_platform_row(item) for item in _items(audit.get("platforms"))]
    risks = sorted({risk for row in rows for risk in row.get("risk", [])})
    unproven = [
        row["platform"]
        for row in rows
        if row["delivered_to_model"] in {"not_measured", "unknown"}
        or row["delivered_to_user"] in {"not_measured", "unknown"}
    ]
    proven_rows = [row for row in rows if row.get("platform_delivery_proven")]
    proof_states = {row["platform"]: row["platform_proof_state"] for row in rows}
    seven_of_seven_gate = _build_7of7_gate(
        rows,
        required_platforms=source.get("required_platforms") or required_platforms,
    )
    return {
        "ok": True,
        "contract": PLATFORM_DELIVERY_MATRIX_CONTRACT,
        "source_contract": audit.get("contract", ""),
        "created_at": _now(),
        "read_only": True,
        "findings_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "not_a_delivery_mechanism": True,
        "not_a_model_answerer": True,
        "matrix": rows,
        "platform_proof": {
            "proof_rule": "platform proven only when trusted memory trace status is proven, model delivery is observed, and all five Definition-of-Proven cells are true",
            "model_not_measured_means_unproven": True,
            "scope_or_casefile_proof_is_not_platform_wide_proof": True,
            "seven_of_seven_gate": seven_of_seven_gate,
            "platform_delivery_7_of_7_proven": seven_of_seven_gate["platform_delivery_7_of_7_proven"],
            "proof_scope_projection": _proof_scope_projection(proof_scope_matrix),
            "platforms_proven": [row["platform"] for row in proven_rows],
            "platforms_unproven": [
                row["platform"]
                for row in rows
                if not row.get("platform_delivery_proven")
            ],
            "proof_states": proof_states,
        },
        "counts": {
            "platforms_total": len(rows),
            "source_refs_visible": sum(1 for row in rows if row["source_refs_visible"]),
            "raw_expand_available": sum(1 for row in rows if bool(row["raw_expand_path"])),
            "model_delivery_observed": sum(1 for row in rows if row["delivered_to_model"] == "observed"),
            "user_delivery_observed": sum(1 for row in rows if row["delivered_to_user"] == "observed"),
            "platform_delivery_proven": len(proven_rows),
            "platform_delivery_7_of_7_proven": int(seven_of_seven_gate["platform_delivery_7_of_7_proven"]),
            "unproven_delivery_platforms": len(unproven),
            "local_draft_detected": sum(1 for row in rows if row["local_draft_detected"]),
        },
        "unproven_delivery_platforms": unproven,
        "risks": risks,
        "next_actions": _next_actions(rows),
        "final_evidence_authority": "raw_source_refs",
        "limitations": [
            "matrix_is_projection_of_findings_not_new_probe",
            "connection_ready_does_not_prove_model_received_memory",
            "source_refs_visible_does_not_prove_answer_used_memory",
            "scoped_installed_user_work_proof_does_not_prove_platform_wide_delivery",
            "7of7_requires_all_required_platform_rows_not_a_subset",
        ],
    }


__all__ = [
    "PLATFORM_DELIVERY_MATRIX_CONTRACT",
    "PLATFORM_DELIVERY_7OF7_GATE_CONTRACT",
    "build_platform_delivery_matrix",
]
