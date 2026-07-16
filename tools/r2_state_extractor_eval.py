#!/usr/bin/env python3
"""Score offline R2 state-extraction results without invoking a model."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any


CONTRACT = "time_library.r2_state_extractor_eval.v2026.7.14"
ATOM_REQUIRED_FIELDS = {
    "atom_id",
    "revision_id",
    "shelf",
    "semantic_type",
    "state_role",
    "content",
    "observed_at",
    "recorded_at",
    "valid_from",
    "valid_to",
    "taint",
    "source_refs",
    "source_span",
    "verifier",
    "activation_allowed",
}
SEMANTIC_TYPES = {"claim", "event", "procedure", "preference"}
SHELVES = {"raw", "zhiyi", "xingce", "toolbook", "errata"}
STATE_ROLES = {
    "candidate",
    "active",
    "superseded",
    "transition",
    "conflicting",
    "unknown",
    "rejected",
}
TAINT_VALUES = {"trusted", "untrusted_content", "instruction_like", "unknown"}
VERIFIER_VALUES = {"pass", "fail", "unknown", "not_measured"}
ARM_KINDS = {"local", "cloud"}
CONTROLLED_PROOF_LAYERS = {"controlled_model_eval"}


def _canonical_ref(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _rate(passed: int, total: int) -> float | None:
    return round(passed / total, 6) if total else None


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(float(ordered[index]), 3)


def _finite_number(value: object, *, minimum: float | None = None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        return None
    return number


def _valid_datetime(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _datetime_value(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _valid_source_ref(ref: object) -> bool:
    if not isinstance(ref, dict) or not str(ref.get("source_system") or "").strip():
        return False
    return any(
        str(ref.get(field) or "").strip()
        for field in ("source_path", "ref_path", "artifact_id", "library_id", "evidence_ref")
    )


def _valid_source_span_shape(span: object) -> bool:
    if not isinstance(span, dict):
        return False
    start = span.get("byte_start")
    end = span.get("byte_end")
    text = span.get("text")
    if isinstance(start, bool) or isinstance(end, bool):
        return False
    return (
        isinstance(start, int)
        and isinstance(end, int)
        and isinstance(text, str)
        and 0 <= start < end
        and bool(text)
    )


def _valid_atom_shape(atom: object) -> bool:
    if not isinstance(atom, dict) or not ATOM_REQUIRED_FIELDS.issubset(atom):
        return False
    if any(not isinstance(atom.get(name), str) or not atom[name].strip() for name in (
        "atom_id",
        "revision_id",
        "content",
    )):
        return False
    if atom.get("shelf") not in SHELVES:
        return False
    if atom.get("semantic_type") not in SEMANTIC_TYPES:
        return False
    if atom.get("state_role") not in STATE_ROLES:
        return False
    if atom.get("taint") not in TAINT_VALUES:
        return False
    if (
        not isinstance(atom.get("source_refs"), list)
        or not atom["source_refs"]
        or not all(_valid_source_ref(ref) for ref in atom["source_refs"])
    ):
        return False
    if not _valid_source_span_shape(atom.get("source_span")):
        return False
    if not all(_valid_datetime(atom.get(name)) for name in (
        "observed_at",
        "recorded_at",
        "valid_from",
    )):
        return False
    valid_to = atom.get("valid_to")
    if valid_to is not None and not _valid_datetime(valid_to):
        return False
    if not isinstance(atom.get("activation_allowed"), bool):
        return False
    verifier = atom.get("verifier")
    return isinstance(verifier, dict) and all(
        verifier.get(name) in VERIFIER_VALUES
        for name in ("coverage", "preservation", "faithfulness")
    )


def _faithful_span(source_text: str, atom: dict[str, Any]) -> bool:
    span = atom.get("source_span")
    if not _valid_source_span_shape(span):
        return False
    start = span["byte_start"]
    end = span["byte_end"]
    text = span["text"]
    source_bytes = source_text.encode("utf-8")
    return end <= len(source_bytes) and source_bytes[start:end] == text.encode("utf-8")


def _temporal_consistent(atom: dict[str, Any]) -> bool:
    if not all(_valid_datetime(atom.get(name)) for name in (
        "observed_at",
        "recorded_at",
        "valid_from",
    )):
        return False
    valid_to = atom.get("valid_to")
    if valid_to is not None and not _valid_datetime(valid_to):
        return False
    observed_at = _datetime_value(atom["observed_at"])
    recorded_at = _datetime_value(atom["recorded_at"])
    valid_from = _datetime_value(atom["valid_from"])
    if recorded_at < observed_at:
        return False
    return valid_to is None or _datetime_value(valid_to) >= valid_from


def _span_overlaps(left: object, right: object) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    left_start = _finite_number(left.get("byte_start"), minimum=0.0)
    left_end = _finite_number(left.get("byte_end"), minimum=0.0)
    right_start = _finite_number(right.get("byte_start"), minimum=0.0)
    right_end = _finite_number(right.get("byte_end"), minimum=0.0)
    if None in (left_start, left_end, right_start, right_end):
        return False
    return left_start < right_end and right_start < left_end


def _expected_alignment_id(
    atom: dict[str, Any], expected: dict[str, dict[str, Any]]
) -> str:
    atom_id = str(atom.get("atom_id") or "")
    if atom_id in expected:
        return atom_id
    actual_refs = {
        _canonical_ref(ref)
        for ref in _list(atom.get("source_refs"))
        if isinstance(ref, dict)
    }
    if not actual_refs:
        return atom_id
    matches = []
    for expected_id, item in expected.items():
        expected_refs = {
            _canonical_ref(ref)
            for ref in _list(item.get("source_refs"))
            if isinstance(ref, dict)
        }
        if not expected_refs or actual_refs != expected_refs:
            continue
        if _span_overlaps(atom.get("source_span"), item.get("source_span")):
            matches.append(expected_id)
    return matches[0] if len(matches) == 1 else atom_id


def _evaluate_case(case: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    atoms = result.get("atoms") if isinstance(result, dict) else []
    atoms = _list(atoms)
    expected = {
        str(item.get("atom_id")): item
        for item in _list(case.get("expected_atoms"))
        if isinstance(item, dict) and item.get("atom_id")
    }
    atom_id_list = [
        _expected_alignment_id(atom, expected)
        for atom in atoms
        if isinstance(atom, dict) and str(atom.get("atom_id") or "")
    ]
    atom_map = {
        _expected_alignment_id(atom, expected): atom
        for atom in atoms
        if isinstance(atom, dict) and str(atom.get("atom_id") or "")
    }
    duplicate_atom_id_count = len(atom_id_list) - len(set(atom_id_list))
    atom_ids = set(atom_map)
    required = {str(value) for value in _list(case.get("required_atom_ids"))}
    preserved = {str(value) for value in _list(case.get("preserved_atom_ids"))}
    forbidden = {str(value) for value in _list(case.get("forbidden_atom_ids"))}
    expected_refs = {_canonical_ref(ref) for ref in _list(case.get("source_refs"))}
    per_atom_refs = [
        {
            _canonical_ref(ref)
            for ref in (atom.get("source_refs") or [])
            if isinstance(ref, dict)
        }
        for atom in atoms
        if isinstance(atom, dict)
    ]
    actual_refs = set().union(*per_atom_refs) if per_atom_refs else set()

    coverage_ok = required.issubset(atom_ids)
    preservation_ok = preserved.issubset(atom_ids) and forbidden.isdisjoint(atom_ids)
    source_refs_ok = (
        bool(expected_refs)
        and len(per_atom_refs) == len(atoms)
        and all(refs and refs.issubset(expected_refs) for refs in per_atom_refs)
        and expected_refs.issubset(actual_refs)
    )
    schema_ok = (
        bool(atoms)
        and duplicate_atom_id_count == 0
        and all(_valid_atom_shape(atom) for atom in atoms)
    )
    faithfulness_ok = bool(atoms) and all(
        isinstance(atom, dict)
        and _faithful_span(str(case.get("source_text") or ""), atom)
        for atom in atoms
    )
    temporal_consistency_ok = bool(atoms) and all(
        isinstance(atom, dict) and _temporal_consistent(atom)
        for atom in atoms
    )
    semantic_type_ok = bool(expected) and all(
        atom_id in atom_map
        and atom_map[atom_id].get("semantic_type") == item.get("semantic_type")
        for atom_id, item in expected.items()
    )
    shelf_ok = bool(expected) and all(
        atom_id in atom_map
        and ("shelf" not in item or atom_map[atom_id].get("shelf") == item.get("shelf"))
        for atom_id, item in expected.items()
    )
    state_role_ok = bool(expected) and all(
        atom_id in atom_map
        and atom_map[atom_id].get("state_role") == item.get("state_role")
        for atom_id, item in expected.items()
    )
    taint_ok = bool(expected) and all(
        atom_id in atom_map and atom_map[atom_id].get("taint") == item.get("taint")
        for atom_id, item in expected.items()
    )
    dual_time_accuracy_ok = bool(expected) and all(
        atom_id in atom_map
        and all(
            name not in item or atom_map[atom_id].get(name) == item.get(name)
            for name in ("observed_at", "recorded_at", "valid_from", "valid_to")
        )
        for atom_id, item in expected.items()
    )
    activation_violations = sum(
        1
        for atom in atoms
        if isinstance(atom, dict) and atom.get("activation_allowed") is not False
    )

    objective = {
        "coverage": coverage_ok,
        "preservation": preservation_ok,
        "faithfulness": faithfulness_ok,
    }
    verifier_false_passes = 0
    for atom in atoms:
        verifier = atom.get("verifier") if isinstance(atom, dict) else None
        if not isinstance(verifier, dict):
            continue
        verifier_false_passes += sum(
            1
            for name, passed in objective.items()
            if verifier.get(name) == "pass" and not passed
        )

    return {
        "case_id": str(case.get("case_id") or ""),
        "stratum": str(case.get("stratum") or ""),
        "result_present": isinstance(result, dict),
        "atom_count": len(atoms),
        "schema_ok": schema_ok,
        "duplicate_atom_id_count": duplicate_atom_id_count,
        "coverage_ok": coverage_ok,
        "preservation_ok": preservation_ok,
        "faithfulness_ok": faithfulness_ok,
        "source_refs_ok": source_refs_ok,
        "shelf_ok": shelf_ok,
        "semantic_type_ok": semantic_type_ok,
        "state_role_ok": state_role_ok,
        "taint_ok": taint_ok,
        "dual_time_accuracy_ok": dual_time_accuracy_ok,
        "temporal_consistency_ok": temporal_consistency_ok,
        "unexpected_atom_count": len(atom_ids - set(expected)),
        "activation_violation_count": activation_violations,
        "verifier_false_pass_count": verifier_false_passes,
    }


def _evaluate_arm(cases: list[dict[str, Any]], arm: dict[str, Any]) -> dict[str, Any]:
    result_items = [item for item in _list(arm.get("results")) if isinstance(item, dict)]
    result_case_ids = [str(item.get("case_id")) for item in result_items if item.get("case_id")]
    duplicate_result_case_count = len(result_case_ids) - len(set(result_case_ids))
    known_case_ids = {str(case.get("case_id")) for case in cases}
    unknown_result_case_count = len(set(result_case_ids) - known_case_ids)
    result_map = {
        str(item.get("case_id")): item
        for item in result_items
        if isinstance(item, dict) and item.get("case_id")
    }
    case_results = [_evaluate_case(case, result_map.get(str(case.get("case_id")))) for case in cases]
    total = len(case_results)
    latency_values = [
        number
        for item in result_map.values()
        if (number := _finite_number(item.get("latency_ms"), minimum=0.0)) is not None
    ]
    latency_measurement_complete = len(latency_values) == len(cases)
    usage_measurement_complete = all(
        isinstance(item.get("usage"), dict)
        and _finite_number(item["usage"].get("input_tokens"), minimum=0.0) is not None
        and _finite_number(item["usage"].get("output_tokens"), minimum=0.0) is not None
        for item in result_map.values()
    ) and len(result_map) == len(cases)
    input_tokens = sum(
        int(number)
        for item in result_map.values()
        if isinstance(item.get("usage"), dict)
        and (number := _finite_number(item["usage"].get("input_tokens"), minimum=0.0)) is not None
    )
    output_tokens = sum(
        int(number)
        for item in result_map.values()
        if isinstance(item.get("usage"), dict)
        and (number := _finite_number(item["usage"].get("output_tokens"), minimum=0.0)) is not None
    )
    price = arm.get("price_usd_per_million") or {}
    input_price = _finite_number(price.get("input"), minimum=0.0) if isinstance(price, dict) else None
    output_price = _finite_number(price.get("output"), minimum=0.0) if isinstance(price, dict) else None
    pricing_complete = input_price is not None and output_price is not None
    estimated_cost = (
        input_tokens * (input_price or 0.0)
        + output_tokens * (output_price or 0.0)
    ) / 1_000_000

    def passed(name: str) -> int:
        return sum(1 for item in case_results if item.get(name) is True)

    activation_violations = sum(item["activation_violation_count"] for item in case_results)
    verifier_false_passes = sum(item["verifier_false_pass_count"] for item in case_results)
    duplicate_atom_ids = sum(item["duplicate_atom_id_count"] for item in case_results)
    unexpected_atoms = sum(item["unexpected_atom_count"] for item in case_results)
    metrics = {
        "case_count": total,
        "result_presence_rate": _rate(passed("result_present"), total),
        "schema_valid_rate": _rate(passed("schema_ok"), total),
        "coverage_rate": _rate(passed("coverage_ok"), total),
        "preservation_rate": _rate(passed("preservation_ok"), total),
        "faithfulness_rate": _rate(passed("faithfulness_ok"), total),
        "source_ref_retention_rate": _rate(passed("source_refs_ok"), total),
        "shelf_accuracy": _rate(passed("shelf_ok"), total),
        "semantic_type_accuracy": _rate(passed("semantic_type_ok"), total),
        "state_role_accuracy": _rate(passed("state_role_ok"), total),
        "taint_accuracy": _rate(passed("taint_ok"), total),
        "dual_time_accuracy": _rate(passed("dual_time_accuracy_ok"), total),
        "temporal_consistency_rate": _rate(passed("temporal_consistency_ok"), total),
        "activation_violation_count": activation_violations,
        "verifier_false_pass_count": verifier_false_passes,
        "duplicate_atom_id_count": duplicate_atom_ids,
        "duplicate_result_case_count": duplicate_result_case_count,
        "unknown_result_case_count": unknown_result_case_count,
        "unexpected_atom_count": unexpected_atoms,
        "latency_p50_ms": _nearest_rank(latency_values, 0.50),
        "latency_p95_ms": _nearest_rank(latency_values, 0.95),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(estimated_cost, 6),
    }
    safety_ok = (
        metrics["result_presence_rate"] == 1.0
        and metrics["schema_valid_rate"] == 1.0
        and metrics["source_ref_retention_rate"] == 1.0
        and metrics["faithfulness_rate"] == 1.0
        and metrics["shelf_accuracy"] == 1.0
        and metrics["semantic_type_accuracy"] == 1.0
        and metrics["state_role_accuracy"] == 1.0
        and metrics["taint_accuracy"] == 1.0
        and metrics["dual_time_accuracy"] == 1.0
        and metrics["temporal_consistency_rate"] == 1.0
        and activation_violations == 0
        and verifier_false_passes == 0
        and duplicate_atom_ids == 0
        and duplicate_result_case_count == 0
        and unknown_result_case_count == 0
        and unexpected_atoms == 0
    )
    report = {
        "arm": str(arm.get("name") or ""),
        "arm_kind": str(arm.get("arm_kind") or ""),
        "model_id": str(arm.get("model_id") or ""),
        "model_revision": str(arm.get("model_revision") or ""),
        "proof_layer": str(arm.get("proof_layer") or "unknown"),
        "input_results_report_model_calls": arm.get("model_call_performed") is True,
        "model_identity_complete": bool(str(arm.get("model_id") or "").strip())
        and bool(str(arm.get("model_revision") or "").strip()),
        "measurement_complete": latency_measurement_complete and usage_measurement_complete,
        "cost_accounting_complete": pricing_complete and usage_measurement_complete,
        "metrics": metrics,
        "non_negotiable_safety_invariants_pass": safety_ok,
        "cases": case_results,
    }
    if arm.get("pipeline_mode") == "hybrid_ambiguity":
        model_call_results = [
            item for item in result_items if item.get("model_call_performed") is True
        ]
        model_latency_values = [
            number
            for item in model_call_results
            if (number := _finite_number(item.get("latency_ms"), minimum=0.0)) is not None
        ]
        rule_candidate_count = sum(
            int(number)
            for item in result_items
            if (number := _finite_number(item.get("rule_candidate_count"), minimum=0.0))
            is not None
        )
        ambiguity_candidate_count = sum(
            int(number)
            for item in result_items
            if (
                number := _finite_number(item.get("ambiguity_candidate_count"), minimum=0.0)
            )
            is not None
        )
        model_decision_count = sum(
            int(number)
            for item in result_items
            if (number := _finite_number(item.get("model_decision_count"), minimum=0.0))
            is not None
        )
        hybrid_measurement_complete = len(result_items) == len(cases) and all(
            _finite_number(item.get("rule_candidate_count"), minimum=0.0) is not None
            and _finite_number(item.get("ambiguity_candidate_count"), minimum=0.0) is not None
            and _finite_number(item.get("model_decision_count"), minimum=0.0) is not None
            and (
                (int(item.get("ambiguity_candidate_count") or 0) == 0
                 and item.get("model_call_performed") is not True
                 and int(item.get("model_decision_count") or 0) == 0)
                or
                (int(item.get("ambiguity_candidate_count") or 0) > 0
                 and item.get("model_call_performed") is True
                 and item.get("model_call_ok") is True
                 and int(item.get("model_decision_count") or 0)
                 == int(item.get("ambiguity_candidate_count") or 0))
            )
            for item in result_items
        )
        metrics.update({
            "model_call_case_count": len(model_call_results),
            "rule_only_case_count": len(result_items) - len(model_call_results),
            "model_call_rate": _rate(len(model_call_results), len(result_items)),
            "rule_candidate_count": rule_candidate_count,
            "ambiguity_candidate_count": ambiguity_candidate_count,
            "model_decision_count": model_decision_count,
            "model_latency_p50_ms": _nearest_rank(model_latency_values, 0.50),
            "model_latency_p95_ms": _nearest_rank(model_latency_values, 0.95),
        })
        report.update({
            "pipeline_mode": "hybrid_ambiguity",
            "hybrid_measurement_complete": hybrid_measurement_complete,
            "input_results_report_model_calls": hybrid_measurement_complete,
        })
    return report


def _quality_gate_reasons(
    arm_reports: list[dict[str, Any]], thresholds: object
) -> list[str]:
    if not isinstance(thresholds, dict):
        return ["owner_quality_thresholds_missing"]
    minimums = thresholds.get("minimum_per_arm")
    maximums = thresholds.get("maximum_per_arm")
    max_local_drop = thresholds.get("local_max_drop_vs_cloud")
    if not any(isinstance(value, dict) and value for value in (minimums, maximums, max_local_drop)):
        return ["owner_quality_thresholds_invalid"]

    reasons: list[str] = []
    for report in arm_reports:
        metrics = report["metrics"]
        arm_name = report["arm"] or "unnamed"
        if isinstance(minimums, dict):
            for metric, threshold in minimums.items():
                expected = _finite_number(threshold)
                actual = _finite_number(metrics.get(metric))
                if expected is None or actual is None or actual < expected:
                    reasons.append("quality_minimum_failed:%s:%s" % (arm_name, metric))
        if isinstance(maximums, dict):
            for metric, threshold in maximums.items():
                expected = _finite_number(threshold, minimum=0.0)
                actual = _finite_number(metrics.get(metric), minimum=0.0)
                if expected is None or actual is None or actual > expected:
                    reasons.append("quality_maximum_failed:%s:%s" % (arm_name, metric))

    by_kind = {report["arm_kind"]: report for report in arm_reports}
    if isinstance(max_local_drop, dict) and max_local_drop:
        local = by_kind.get("local")
        cloud = by_kind.get("cloud")
        if not local or not cloud:
            reasons.append("local_cloud_arm_kinds_required")
        else:
            for metric, threshold in max_local_drop.items():
                allowed = _finite_number(threshold, minimum=0.0)
                local_value = _finite_number(local["metrics"].get(metric))
                cloud_value = _finite_number(cloud["metrics"].get(metric))
                if (
                    allowed is None
                    or local_value is None
                    or cloud_value is None
                    or cloud_value - local_value > allowed
                ):
                    reasons.append("local_quality_drop_exceeded:%s" % metric)
    return reasons


def evaluate_experiment(experiment: dict[str, Any]) -> dict[str, Any]:
    input_is_object = isinstance(experiment, dict)
    experiment = experiment if input_is_object else {}
    cases = [item for item in _list(experiment.get("cases")) if isinstance(item, dict)]
    arms = [item for item in _list(experiment.get("arms")) if isinstance(item, dict)]
    arm_reports = [_evaluate_arm(cases, arm) for arm in arms]
    strata = sorted({str(case.get("stratum") or "") for case in cases if case.get("stratum")})
    required_strata = sorted({str(value) for value in _list(experiment.get("required_strata"))})
    missing_strata = sorted(set(required_strata) - set(strata))
    owner_gate = experiment.get("owner_gate")
    owner_gate = owner_gate if isinstance(owner_gate, dict) else {}
    owner_approved = owner_gate.get("approved") is True
    budget_cap = owner_gate.get("budget_cap_usd")
    valid_budget_cap = _finite_number(budget_cap, minimum=0.0)
    quality_thresholds = owner_gate.get("quality_thresholds")
    reasons: list[str] = []
    if not input_is_object:
        reasons.append("experiment_must_be_object")
    if not owner_approved:
        reasons.append("owner_quality_and_budget_gate_not_approved")
    if valid_budget_cap is None:
        reasons.append("owner_budget_cap_missing")
    reasons.extend(_quality_gate_reasons(arm_reports, quality_thresholds))
    if missing_strata:
        reasons.append("required_strata_missing")
    if any(report["proof_layer"] == "fixture_only" for report in arm_reports):
        reasons.append("fixture_results_are_not_model_quality_evidence")
    arm_kinds = [report["arm_kind"] for report in arm_reports]
    if set(arm_kinds) != ARM_KINDS or len(arm_kinds) != len(set(arm_kinds)):
        reasons.append("local_cloud_arm_kinds_required")
    if any(
        not report["input_results_report_model_calls"]
        or report["proof_layer"] not in CONTROLLED_PROOF_LAYERS
        for report in arm_reports
    ):
        reasons.append("local_vs_cloud_model_results_missing")
    if any(not report["model_identity_complete"] for report in arm_reports):
        reasons.append("model_identity_missing")
    if any(not report["measurement_complete"] for report in arm_reports):
        reasons.append("latency_or_usage_measurement_missing")
    if any(not report["cost_accounting_complete"] for report in arm_reports):
        reasons.append("cost_accounting_incomplete")
    if any(not report["non_negotiable_safety_invariants_pass"] for report in arm_reports):
        reasons.append("non_negotiable_safety_invariant_failed")
    total_estimated_cost = round(
        sum(report["metrics"]["estimated_cost_usd"] for report in arm_reports), 6
    )
    if valid_budget_cap is not None and total_estimated_cost > valid_budget_cap:
        reasons.append("owner_budget_cap_exceeded")

    reasons = list(dict.fromkeys(reasons))

    comparison_status = "ready_for_owner_review"
    if any(report["proof_layer"] == "fixture_only" for report in arm_reports):
        comparison_status = "fixture_only_not_quality_evidence"
    elif "local_vs_cloud_model_results_missing" in reasons:
        comparison_status = "local_vs_cloud_not_measured"
    elif len(arm_reports) < 2:
        comparison_status = "local_vs_cloud_not_measured"

    return {
        "ok": input_is_object,
        "contract": CONTRACT,
        "proof_layer": "offline_result_scoring",
        "decision": "GO" if not reasons else "NO_GO",
        "decision_reasons": reasons,
        "no_overall_score": True,
        "case_count": len(cases),
        "strata": strata,
        "required_strata": required_strata,
        "missing_strata": missing_strata,
        "comparison_status": comparison_status,
        "owner_gate": owner_gate,
        "total_estimated_cost_usd": total_estimated_cost,
        "arms": arm_reports,
        "write_boundary": {
            "evaluator_model_call_performed": False,
            "network_call_performed": False,
            "production_shadow_write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
        },
        "non_claims": [
            "fixture_results_do_not_measure_local_or_cloud_model_quality",
            "evaluator_does_not_independently_verify_external_model_call_receipts",
            "scoring_does_not_authorize_budget_or_model_calls",
            "scoring_does_not_write_or_activate_state_memory",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    experiment = json.loads(args.input.read_text(encoding="utf-8"))
    report = evaluate_experiment(experiment)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
