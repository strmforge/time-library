"""Trust metrics for trusted-memory delivery probes.

These metrics measure the axis Time Library is trying to win: ordinary chat
must not be hijacked, answers must stay evidence-bound, and missing evidence
must stay visible as UNKNOWN. This module is a report builder, not a delivery
mechanism.
"""

from __future__ import annotations

from typing import Any


TRUSTED_MEMORY_TRUST_METRICS_CONTRACT = "trusted_memory_trust_metrics.v2026.6.21"
TRUSTED_MEMORY_PROOF_SCOPE_MATRIX_CONTRACT = "trusted_memory_proof_scope_matrix.v2026.6.21"
CASE_EXPECTED_METRIC_FIELDS = (
    "ordinary_chats_checked",
    "source_claims_checked",
    "unknown_cases_checked",
    "hijack_rate",
    "unsupported_answer_rate",
    "unknown_discipline",
    "source_reachability",
    "receipt_visibility",
)


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value in (None, "") else [value])


def _case_id(probe_name: str, case: dict[str, Any]) -> str:
    return f"{probe_name}:{case.get('case') or 'unknown_case'}"


def _diagnostic_case(case: dict[str, Any]) -> dict[str, Any]:
    """Return bounded, source-oriented diagnostics for a failed probe case."""

    return {
        "case_id": _case_id(case.get("probe", ""), case),
        "case": str(case.get("case") or ""),
        "casefile_case": str(case.get("casefile_case") or ""),
        "casefile_record_kind": str(case.get("casefile_record_kind") or ""),
        "authorized_scope_filter": str(case.get("authorized_scope_filter") or case.get("scope_filter") or ""),
        "model_verdict": str(case.get("model_verdict") or ""),
        "model_validation_error": str(case.get("model_validation_error") or ""),
        "unknown_reason": str(case.get("unknown_reason") or ""),
        "answer_source": str(case.get("answer_source") or ""),
        "receipt_status": str(case.get("receipt_status") or ""),
        "trace_status": str(case.get("trace_status") or ""),
        "model_delivery_state": str(case.get("model_delivery_state") or ""),
        "recall_count": int(case.get("recall_count") or 0),
        "used_source_refs": [str(item) for item in _items(case.get("used_source_refs")) if str(item)][:5],
        "evidence_packet_refs": [str(item) for item in _items(case.get("evidence_packet_refs")) if str(item)][:5],
        "missing_cells": [str(item) for item in _items(case.get("missing_cells")) if str(item)][:8],
        "ordinary_handled": case.get("ordinary_handled"),
        "explicit_handled": case.get("explicit_handled"),
        "unknown_boundary": case.get("unknown_boundary"),
    }


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def _ratio(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator}"


def _source_refs_reachable(case: dict[str, Any]) -> bool:
    used_refs = [str(item) for item in _items(case.get("used_source_refs")) if str(item)]
    if not used_refs:
        return False
    evidence_refs = {str(item) for item in _items(case.get("evidence_packet_refs")) if str(item)}
    source_refs = _items(case.get("source_refs"))
    source_library_ids = {
        str(item.get("library_id") or item.get("source_id") or item.get("evidence_ref") or "")
        for item in source_refs
        if isinstance(item, dict)
    }
    source_library_ids.discard("")
    reachable_refs = evidence_refs | source_library_ids
    return bool(reachable_refs) and all(ref in reachable_refs for ref in used_refs)


def _case_is_unknown(case: dict[str, Any]) -> bool:
    return (
        str(case.get("case") or "").lower() == "unknown"
        or str(case.get("answer") or "").upper() == "UNKNOWN"
        or case.get("receipt_status") == "unknown"
        or case.get("unknown_boundary") is True
    )


def _case_is_source_claim(case: dict[str, Any]) -> bool:
    return (
        case.get("answer_source") == "evidence_bound_model_call"
        and case.get("receipt_status") == "source_backed"
        and _source_backed_verdict_is_supported(case)
        and bool(_items(case.get("used_source_refs")))
    )


def _source_backed_verdict_is_supported(case: dict[str, Any]) -> bool:
    verdict = str(case.get("model_verdict") or "").strip().lower()
    validation_error = str(case.get("model_validation_error") or "").strip()
    if validation_error:
        return False
    if not verdict:
        return True
    return verdict not in {
        "unknown",
        "insufficient_evidence",
        "model_error",
        "dry_run",
        "gated",
        "non_json_model_response",
    }


def _unique_nonempty(values: list[Any]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value or "").strip()})


def _case_metric_ok(cases: list[dict[str, Any]]) -> bool:
    observation = build_case_expected_metrics_observation(cases)
    return (
        observation.get("hijack_rate") == "0/" + str(observation.get("ordinary_chats_checked", 0))
        and observation.get("unsupported_answer_rate") == "0/" + str(observation.get("source_claims_checked", 0))
        and str(observation.get("unknown_discipline") or "").startswith(str(observation.get("unknown_cases_checked", 0)) + "/")
        and str(observation.get("source_reachability") or "").startswith(str(observation.get("source_claims_checked", 0)) + "/")
    )


def build_proof_scope_matrix(
    *,
    probes: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Describe what a trust-metrics report proves without broadening claims."""

    active_errors = [str(error) for error in (errors or []) if str(error)]
    fixture_probes = [probe for probe in probes if probe.get("fixture_backed")]
    controlled_probes = [probe for probe in probes if probe.get("controlled_temp_memory")]
    user_work_probes = [probe for probe in probes if probe.get("user_work_records_read")]
    fixture_cases = [case for case in cases if any(case.get("probe") == probe.get("name") for probe in fixture_probes)]
    controlled_cases = [case for case in cases if any(case.get("probe") == probe.get("name") for probe in controlled_probes)]
    user_work_cases = [case for case in cases if any(case.get("probe") == probe.get("name") for probe in user_work_probes)]
    scoped_case_names = _unique_nonempty([case.get("casefile_case") for case in user_work_cases])
    scoped_record_kinds = _unique_nonempty([case.get("casefile_record_kind") for case in user_work_cases])
    scoped_filters = _unique_nonempty([
        case.get("authorized_scope_filter") or case.get("scope_filter")
        for case in user_work_cases
    ])

    def row(
        *,
        proof_scope: str,
        proof_state: str,
        evidence_source: str,
        cases_checked: int,
        reads_installed_user_work_records: bool,
        model_delivery_observed: int,
        claim_boundary: str,
        non_claims: list[str],
        scope_count: int = 0,
        record_kinds: list[str] | None = None,
        deterministic_contract_fixture: bool = False,
    ) -> dict[str, Any]:
        return {
            "proof_scope": proof_scope,
            "proof_state": proof_state,
            "evidence_source": evidence_source,
            "cases_checked": cases_checked,
            "scope_count": scope_count,
            "record_kinds": record_kinds or [],
            "reads_installed_user_work_records": reads_installed_user_work_records,
            "deterministic_contract_fixture": deterministic_contract_fixture,
            "model_delivery_observed_cases": model_delivery_observed,
            "platform_wide": False,
            "broad_all_records": False,
            "claim_boundary": claim_boundary,
            "non_claims": non_claims,
        }

    rows: list[dict[str, Any]] = []
    fixture_deterministic = any(probe.get("deterministic_contract_fixture") for probe in fixture_probes)
    fixture_model_observed = sum(1 for case in fixture_cases if case.get("model_delivery_state") == "observed")
    rows.append(row(
        proof_scope="fixture_backed_answer_path",
        proof_state=(
            "contract_fixture_passed"
            if fixture_deterministic and fixture_cases and _case_metric_ok(fixture_cases)
            else ("observed_trace_passed" if fixture_cases and _case_metric_ok(fixture_cases) else "not_proven")
        ),
        evidence_source="fixture_backed_probe",
        cases_checked=len(fixture_cases),
        reads_installed_user_work_records=False,
        model_delivery_observed=fixture_model_observed,
        deterministic_contract_fixture=fixture_deterministic,
        claim_boundary=(
            "deterministic trust-axis fixture only"
            if fixture_deterministic
            else "fixture-backed observed answer-path trace only"
        ),
        non_claims=[
            "not installed Zhiyi/Xingce user/work-record proof",
            "not platform-wide proof",
            "not all-record proof",
        ],
    ))

    controlled_model_observed = sum(1 for case in controlled_cases if case.get("model_delivery_state") == "observed")
    rows.append(row(
        proof_scope="controlled_temp_memory_answer_path",
        proof_state="controlled_temp_memory_passed" if controlled_cases and _case_metric_ok(controlled_cases) else "not_proven",
        evidence_source="temporary_MEMCORE_ROOT_case_memory_probe",
        cases_checked=len(controlled_cases),
        reads_installed_user_work_records=False,
        model_delivery_observed=controlled_model_observed,
        claim_boundary="temporary non-sensitive case_memory diagnostic only",
        non_claims=[
            "not installed Zhiyi/Xingce user/work-record proof",
            "not platform-wide proof",
            "not broad user memory proof",
        ],
    ))

    user_work_model_observed = sum(1 for case in user_work_cases if case.get("model_delivery_state") == "observed")
    user_work_state = "not_performed"
    if user_work_cases:
        user_work_state = "scoped_installed_user_work_proof" if not active_errors and _case_metric_ok(user_work_cases) else "scoped_installed_user_work_failed"
    rows.append(row(
        proof_scope="scoped_installed_zhiyi_xingce_user_work_records",
        proof_state=user_work_state,
        evidence_source="installed_scoped_user_work_probe_or_casefile",
        cases_checked=len(user_work_cases),
        scope_count=len(scoped_filters),
        record_kinds=scoped_record_kinds,
        reads_installed_user_work_records=bool(user_work_cases),
        model_delivery_observed=user_work_model_observed,
        claim_boundary="only the supplied scope/query pairs and record kinds",
        non_claims=[
            "not all installed records",
            "not all scopes",
            "not all platforms",
            "not platform-wide delivery proof",
        ],
    ))

    platform_row = row(
        proof_scope="platform_wide_delivery",
        proof_state="platform_wide_delivery_unproven",
        evidence_source="platform_specific_live_probes_required",
        cases_checked=0,
        reads_installed_user_work_records=False,
        model_delivery_observed=0,
        claim_boundary="requires per-platform observed delivery traces",
        non_claims=[
            "fixture-backed proof is not platform-wide proof",
            "controlled-temp proof is not platform-wide proof",
            "scoped user/work proof is not platform-wide proof",
        ],
    )
    platform_row["platform_wide"] = True
    rows.append(platform_row)

    all_record_row = row(
        proof_scope="all_records_all_scopes",
        proof_state="broad_all_records_unproven",
        evidence_source="not_measured_by_this_runner",
        cases_checked=0,
        reads_installed_user_work_records=False,
        model_delivery_observed=0,
        claim_boundary="requires separate broad coverage design and evidence",
        non_claims=[
            "scoped casefile is not all-record proof",
            "trust metrics are not a broad/global recall sweep",
        ],
    )
    all_record_row["broad_all_records"] = True
    rows.append(all_record_row)

    return {
        "contract": TRUSTED_MEMORY_PROOF_SCOPE_MATRIX_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "scope_filters": scoped_filters,
        "casefile_cases": scoped_case_names,
        "rows": rows,
        "public_claim_rule": (
            "cite only rows whose proof_state is passed/proof, and preserve each row's claim_boundary"
        ),
    }


def build_case_expected_metrics_observation(cases: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Summarize one scoped casefile trace in the same metric vocabulary."""

    scoped_cases = [case for case in (cases or []) if isinstance(case, dict)]
    ordinary_count = len(scoped_cases)
    hijacked_cases = [
        _case_id(case.get("probe", ""), case)
        for case in scoped_cases
        if case.get("ordinary_handled") is not False
    ]
    explicit_cases = [case for case in scoped_cases if case.get("explicit_handled") is True]
    non_unknown_answer_cases = [
        case
        for case in explicit_cases
        if not _case_is_unknown(case)
    ]
    unsupported_answer_cases = [
        _case_id(case.get("probe", ""), case)
        for case in non_unknown_answer_cases
        if not _items(case.get("used_source_refs"))
        or case.get("answer_source") != "evidence_bound_model_call"
        or case.get("trace_status") != "proven"
        or not _source_backed_verdict_is_supported(case)
    ]
    unknown_cases = [
        case
        for case in explicit_cases
        if _case_is_unknown(case)
    ]
    failed_unknown_cases = [
        _case_id(case.get("probe", ""), case)
        for case in unknown_cases
        if str(case.get("answer") or "").upper() != "UNKNOWN"
        or case.get("unknown_boundary") is not True
        or case.get("answer_source") != "evidence_bound_model_call"
        or case.get("trace_status") != "proven"
    ]
    source_claim_cases = [
        case
        for case in explicit_cases
        if _case_is_source_claim(case)
    ]
    unreachable_source_cases = [
        _case_id(case.get("probe", ""), case)
        for case in source_claim_cases
        if not _source_refs_reachable(case)
    ]
    receipt_missing_cases = [
        _case_id(case.get("probe", ""), case)
        for case in explicit_cases
        if case.get("receipt_status") not in {"source_backed", "unknown"}
    ]
    return {
        "ordinary_chats_checked": ordinary_count,
        "source_claims_checked": len(source_claim_cases),
        "unknown_cases_checked": len(unknown_cases),
        "hijack_rate": _ratio(len(hijacked_cases), ordinary_count),
        "unsupported_answer_rate": _ratio(len(unsupported_answer_cases), len(non_unknown_answer_cases)),
        "unknown_discipline": _ratio(len(unknown_cases) - len(failed_unknown_cases), len(unknown_cases)),
        "source_reachability": _ratio(len(source_claim_cases) - len(unreachable_source_cases), len(source_claim_cases)),
        "receipt_visibility": _ratio(len(explicit_cases) - len(receipt_missing_cases), len(explicit_cases)),
    }


def build_trusted_memory_trust_metrics(
    probe_results: list[dict[str, Any]] | None = None,
    *,
    generated_by: str = "",
) -> dict[str, Any]:
    """Build reproducible trust metrics from trusted-memory probe outputs."""

    results = probe_results if isinstance(probe_results, list) else []
    cases: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            continue
        probe_name = str(result.get("contract") or f"probe_{index + 1}")
        probes.append(
            {
                "name": probe_name,
                "ok": bool(result.get("ok")),
                "fixture_backed": bool(result.get("fixture_backed")),
                "controlled_temp_memory": bool(result.get("controlled_temp_memory")),
                "deterministic_contract_fixture": bool(result.get("deterministic_contract_fixture")),
                "user_work_records_read": bool(result.get("user_work_records_read")),
                "platform_action_performed": bool(result.get("platform_action_performed")),
            }
        )
        for case in _items(result.get("cases")):
            if isinstance(case, dict):
                cases.append({"probe": probe_name, **case})

    ordinary_count = len(cases)
    hijacked_cases = [
        _case_id(case.get("probe", ""), case)
        for case in cases
        if case.get("ordinary_handled") is not False
    ]
    explicit_cases = [case for case in cases if case.get("explicit_handled") is True]
    non_unknown_answer_cases = [
        case
        for case in explicit_cases
        if not _case_is_unknown(case)
    ]
    unsupported_answer_cases = [
        _case_id(case.get("probe", ""), case)
        for case in non_unknown_answer_cases
        if not _items(case.get("used_source_refs"))
        or case.get("answer_source") != "evidence_bound_model_call"
        or case.get("trace_status") != "proven"
        or not _source_backed_verdict_is_supported(case)
    ]
    unknown_cases = [
        case
        for case in explicit_cases
        if _case_is_unknown(case)
    ]
    failed_unknown_cases = [
        _case_id(case.get("probe", ""), case)
        for case in unknown_cases
        if str(case.get("answer") or "").upper() != "UNKNOWN"
        or case.get("unknown_boundary") is not True
        or case.get("answer_source") != "evidence_bound_model_call"
        or case.get("trace_status") != "proven"
    ]
    source_claim_cases = [
        case
        for case in explicit_cases
        if _case_is_source_claim(case)
    ]
    expected_source_backed_cases = [
        case
        for case in explicit_cases
        if str(case.get("case") or "").lower() == "source_backed"
    ]
    failed_source_backed_cases = [
        _case_id(case.get("probe", ""), case)
        for case in expected_source_backed_cases
        if not _case_is_source_claim(case)
    ]
    unreachable_source_cases = [
        _case_id(case.get("probe", ""), case)
        for case in source_claim_cases
        if not _source_refs_reachable(case)
    ]
    receipt_cases = [
        case
        for case in explicit_cases
        if case.get("receipt_status") in {"source_backed", "unknown"}
    ]
    receipt_missing_cases = [
        _case_id(case.get("probe", ""), case)
        for case in explicit_cases
        if case.get("receipt_status") not in {"source_backed", "unknown"}
    ]
    failed_case_diagnostics = {
        "hijacked_cases": [
            _diagnostic_case(case)
            for case in cases
            if case.get("ordinary_handled") is not False
        ][:5],
        "unsupported_answer_cases": [
            _diagnostic_case(case)
            for case in non_unknown_answer_cases
            if not _items(case.get("used_source_refs"))
            or case.get("answer_source") != "evidence_bound_model_call"
            or case.get("trace_status") != "proven"
            or not _source_backed_verdict_is_supported(case)
        ][:5],
        "failed_unknown_cases": [
            _diagnostic_case(case)
            for case in unknown_cases
            if str(case.get("answer") or "").upper() != "UNKNOWN"
            or case.get("unknown_boundary") is not True
            or case.get("answer_source") != "evidence_bound_model_call"
            or case.get("trace_status") != "proven"
        ][:5],
        "failed_source_backed_cases": [
            _diagnostic_case(case)
            for case in expected_source_backed_cases
            if not _case_is_source_claim(case)
        ][:5],
        "unreachable_source_cases": [
            _diagnostic_case(case)
            for case in source_claim_cases
            if not _source_refs_reachable(case)
        ][:5],
        "receipt_missing_cases": [
            _diagnostic_case(case)
            for case in explicit_cases
            if case.get("receipt_status") not in {"source_backed", "unknown"}
        ][:5],
    }
    observed_model_cases = [
        case
        for case in explicit_cases
        if case.get("model_delivery_state") == "observed"
        and case.get("model_called") is True
        and case.get("request_sent") is True
    ]

    user_work_records_read = any(probe.get("user_work_records_read") for probe in probes)
    platform_action_performed = any(probe.get("platform_action_performed") for probe in probes)
    errors: list[str] = []
    if hijacked_cases:
        errors.append("hijack_rate_above_zero")
    if unsupported_answer_cases:
        errors.append("unsupported_answer_rate_above_zero")
    if failed_unknown_cases:
        errors.append("unknown_discipline_failed")
    if failed_source_backed_cases:
        errors.append("source_backed_expectation_failed")
    if unreachable_source_cases:
        errors.append("source_reachability_below_target")
    if receipt_missing_cases:
        errors.append("receipt_visibility_below_target")
    if not cases:
        errors.append("no_probe_cases_supplied")
    if not all(probe.get("ok") for probe in probes):
        errors.append("one_or_more_probe_inputs_not_ok")

    proof_scope_matrix = build_proof_scope_matrix(probes=probes, cases=cases, errors=errors)

    return {
        "ok": not errors,
        "contract": TRUSTED_MEMORY_TRUST_METRICS_CONTRACT,
        "generated_by": generated_by,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "user_work_records_read": user_work_records_read,
        "platform_action_performed": platform_action_performed,
        "evaluation_scope": "fixture_backed_and_controlled_temp_memory_trusted_memory_probes",
        "not_installed_user_work_record_proof": not user_work_records_read,
        "not_platform_wide_delivery_proof": True,
        "probes": probes,
        "counts": {
            "probes_total": len(probes),
            "cases_total": len(cases),
            "ordinary_chats_checked": ordinary_count,
            "explicit_memory_answers_checked": len(explicit_cases),
            "non_unknown_answers_checked": len(non_unknown_answer_cases),
            "unknown_cases_checked": len(unknown_cases),
            "source_claims_checked": len(source_claim_cases),
            "source_backed_cases_expected": len(expected_source_backed_cases),
            "source_backed_cases_proven": len(expected_source_backed_cases) - len(failed_source_backed_cases),
            "model_delivery_observed_cases": len(observed_model_cases),
            "receipt_visible_cases": len(receipt_cases),
        },
        "metrics": {
            "hijack_rate": {
                "target": 0,
                "numerator": len(hijacked_cases),
                "denominator": ordinary_count,
                "percent": _pct(len(hijacked_cases), ordinary_count),
                "ok": not hijacked_cases,
            },
            "unsupported_answer_rate": {
                "target": 0,
                "numerator": len(unsupported_answer_cases),
                "denominator": len(non_unknown_answer_cases),
                "percent": _pct(len(unsupported_answer_cases), len(non_unknown_answer_cases)),
                "ok": not unsupported_answer_cases,
            },
            "unknown_discipline": {
                "target": 100,
                "numerator": len(unknown_cases) - len(failed_unknown_cases),
                "denominator": len(unknown_cases),
                "percent": _pct(len(unknown_cases) - len(failed_unknown_cases), len(unknown_cases)),
                "ok": bool(unknown_cases) and not failed_unknown_cases,
            },
            "source_reachability": {
                "target": 100,
                "numerator": len(source_claim_cases) - len(unreachable_source_cases),
                "denominator": len(source_claim_cases),
                "percent": _pct(len(source_claim_cases) - len(unreachable_source_cases), len(source_claim_cases)),
                "ok": bool(source_claim_cases) and not unreachable_source_cases,
            },
            "receipt_visibility": {
                "target": 100,
                "numerator": len(explicit_cases) - len(receipt_missing_cases),
                "denominator": len(explicit_cases),
                "percent": _pct(len(explicit_cases) - len(receipt_missing_cases), len(explicit_cases)),
                "ok": bool(explicit_cases) and not receipt_missing_cases,
            },
        },
        "failure_examples": {
            "hijacked_cases": hijacked_cases[:5],
            "unsupported_answer_cases": unsupported_answer_cases[:5],
            "failed_unknown_cases": failed_unknown_cases[:5],
            "failed_source_backed_cases": failed_source_backed_cases[:5],
            "unreachable_source_cases": unreachable_source_cases[:5],
            "receipt_missing_cases": receipt_missing_cases[:5],
        },
        "failure_diagnostics": failed_case_diagnostics,
        "errors": errors,
        "limitations": [
            "metrics_are_built_from_repeatable_probes_not_broad_user_work_records",
            "controlled_temp_memory_is_not_installed_user_work_record_trace",
            "platform_by_platform_delivery_still_requires_platform_specific_verification",
        ],
        "public_claim_boundary": (
            "Can cite these trust metrics only for fixture-backed and controlled-temp-memory "
            "trusted-memory probes, not for all installed Zhiyi/Xingce user/work-record traces or all platforms."
        ),
        "proof_scope_matrix": proof_scope_matrix,
    }


__all__ = [
    "CASE_EXPECTED_METRIC_FIELDS",
    "TRUSTED_MEMORY_PROOF_SCOPE_MATRIX_CONTRACT",
    "TRUSTED_MEMORY_TRUST_METRICS_CONTRACT",
    "build_case_expected_metrics_observation",
    "build_proof_scope_matrix",
    "build_trusted_memory_trust_metrics",
]
