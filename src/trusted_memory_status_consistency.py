"""Consistency checks for Trusted Memory status docs and scoped casefiles.

This checker is deliberately read-only. It keeps the public status page aligned
with the checked-in scoped user/work casefile without reading installed memory,
writing raw records, or making platform/model calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TRUSTED_MEMORY_STATUS_CONSISTENCY_CONTRACT = "trusted_memory_status_consistency.v2026.6.21"
ALLOWED_USER_WORK_RECORD_KINDS = ("user_preference", "work_record")
FORBIDDEN_TRUSTED_MEMORY_FRAMING = (
    "私人记忆",
    "private memory",
    "用户授权私人",
    "consent-gated",
    "per-read authorization",
    "per-read consent",
    "用户授权读取",
    "读取需要用户授权",
)
FORBIDDEN_CASE_SOURCE_QUERIES = (
    "忆凡尘和知意行策的定位是什么？",
)
FORBIDDEN_CASE_NAMES = (
    "yifanchen-positioning-scoped-preference-proof",
)
REQUIRED_CODEX_HISTORY_UNKNOWN_QUERY = (
    "Codex 历史恢复是否已经发布到 GitHub release tag memcore-v2099.1.1，并且发布包 SHA256 是 "
    "0000000000000000000000000000000000000000000000000000000000000000？"
)
FORBIDDEN_CODEX_HISTORY_UNKNOWN_QUERIES = (
    "Codex 历史恢复的远端发布回执已经完成了吗？",
)
REQUIRED_CASE_EXPECTED_METRICS = {
    "ordinary_chats_checked": 2,
    "source_claims_checked": 1,
    "unknown_cases_checked": 1,
    "hijack_rate": "0/2",
    "unsupported_answer_rate": "0/1",
    "unknown_discipline": "1/1",
    "source_reachability": "1/1",
    "receipt_visibility": "2/2",
}


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return {"ok": False, "error": f"failed_to_read_casefile:{exc}"}
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"failed_to_parse_casefile:{exc}"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "casefile_root_must_be_object"}
    return {"ok": True, "payload": payload}


def _load_text(path: Path) -> dict[str, Any]:
    try:
        return {"ok": True, "text": path.read_text(encoding="utf-8")}
    except OSError as exc:
        return {"ok": False, "error": f"failed_to_read_status:{exc}"}


def _case_values(case: Any) -> dict[str, str]:
    if not isinstance(case, dict):
        return {}
    return {
        "name": str(case.get("name") or "").strip(),
        "record_kind": str(case.get("record_kind") or "").strip(),
        "observed_at": str(case.get("observed_at") or "").strip(),
        "evidence_command": str(case.get("evidence_command") or "").strip(),
        "scope_filter": str(case.get("scope_filter") or "").strip(),
        "source_query": str(case.get("source_query") or "").strip(),
        "unknown_query": str(case.get("unknown_query") or "").strip(),
    }


def _case_expected_metrics(case: Any) -> dict[str, Any]:
    if not isinstance(case, dict):
        return {}
    metrics = case.get("expected_metrics")
    return metrics if isinstance(metrics, dict) else {}


def _expected_status_strings(case_count: int, scope_count: int) -> dict[str, str]:
    explicit_cases = case_count * 2
    scope_phrase = "two window scopes" if scope_count == 2 else f"{scope_count} window scopes"
    return {
        "user_work_case_count": f"`user_work_case_count={case_count}`",
        "user_work_scope_count": f"`user_work_scope_count={scope_count}`",
        "ordinary_chats_checked": f"`ordinary_chats_checked={explicit_cases}`",
        "source_claims_checked": f"`source_claims_checked={case_count}`",
        "unknown_cases_checked": f"`unknown_cases_checked={case_count}`",
        "hijack_rate": f"`hijack_rate=0/{explicit_cases}`",
        "unsupported_answer_rate": f"`unsupported_answer_rate=0/{case_count}`",
        "unknown_discipline": f"`unknown_discipline={case_count}/{case_count}`",
        "source_reachability": f"`source_reachability={case_count}/{case_count}`",
        "receipt_visibility": f"`receipt_visibility={explicit_cases}/{explicit_cases}`",
        "casefile_observed_at": "`observed_at`",
        "casefile_evidence_command": "`evidence_command`",
        "casefile_expected_metrics": "`expected_metrics`",
        "user_work_case_evidence_field": "`user_work_case_evidence`",
        "user_work_case_metric_evidence_field": "`user_work_case_metric_evidence`",
        "casefile_observed_metrics": "`observed_metrics`",
        "casefile_expected_metrics_match": "`expected_metrics_match`",
        "casefile_repeat_requested": "`user_work_casefile_repeat_requested`",
        "casefile_repeat_completed": "`user_work_casefile_repeat_completed`",
        "casefile_stable": "`user_work_casefile_stable`",
        "casefile_metric_evidence_runs": "`user_work_case_metric_evidence_runs`",
        "proof_scope_matrix": "`proof_scope_matrix`",
        "proof_scope_fixture": "`fixture_backed_answer_path`",
        "proof_scope_controlled": "`controlled_temp_memory_answer_path`",
        "proof_scope_scoped_installed": "`scoped_installed_zhiyi_xingce_user_work_records`",
        "proof_scope_platform_wide": "`platform_wide_delivery`",
        "proof_scope_all_records": "`all_records_all_scopes`",
        "proof_scope_public_claim_rule": "`public_claim_rule`",
        "casefile_repeat_command": "--user-work-casefile-repeat 2",
        "casefile_repeat_requested_value": "`user_work_casefile_repeat_requested=2`",
        "casefile_repeat_completed_value": "`user_work_casefile_repeat_completed=2`",
        "casefile_stable_value": "`user_work_casefile_stable=true`",
        "casefile_expected_metrics_match_value": "`user_work_case_expected_metrics_match=true`",
        "casefile_case_evidence_observed_at": "`casefile_observed_at`",
        "casefile_case_evidence_command": "`casefile_evidence_command`",
        "scope_phrase": scope_phrase,
        "not_all_record": "not all-record",
        "platform_wide_proof": "platform-wide proof",
        "user_preference": "user_preference",
        "work_record": "work_record",
        "failure_diagnostics": "`failure_diagnostics`",
        "diagnostic_casefile_case": "`casefile_case`",
        "diagnostic_authorized_scope_filter": "`authorized_scope_filter`",
        "diagnostic_model_verdict": "`model_verdict`",
        "diagnostic_missing_cells": "`missing_cells`",
        "insufficient_evidence_not_source_backed": "`model_verdict=insufficient_evidence`",
        "zhiyi_xingce_positioning_gap": "Zhiyi/Xingce positioning remains a documented evidence gap",
        "yifanchen_positioning_case": "yifanchen-positioning-preference-proof",
        "code_change_tiandao_source_audit": "code-change Tiandao source audit",
        "code_change_complete_command": "tools/code_change_tiandao_audit.py --max-refs 0 --require-complete --json",
        "code_change_complete_source_refs": "`complete_source_refs=true`",
        "code_change_no_truncation": "`source_refs_truncated=false`",
        "code_change_source_refs_only": "`source_refs_only_until_raw_origin`",
        "code_change_verification_source_refs": "`verification_source_refs`",
        "code_change_test_output_not_supplied": "`test_output_evidence_status=not_supplied`",
        "code_change_test_output_source_refs_only": "`test_output_evidence_status=source_refs_only`",
        "code_change_not_memory_sediment": "not automatic memory sediment",
        "code_change_not_release_proof": "release proof",
        "recall_before_installed_authoritative": "`authoritative_anchor_surfaced`",
        "recall_before_installed_decision_surface": "`decision=surface`",
        "recall_before_installed_source_refs": "`source_refs_count=5`",
        "recall_before_installed_preflight_surface_required": "`preflight_surface_required`",
        "recall_before_service_source_status": "`service_source_status=matches_working_tree`",
        "recall_before_service_refresh_not_required": "`service_refresh_required=false`",
        "recall_before_not_model_delivery": "does not prove model answer delivery",
        "recall_before_scoped_recall_boundary": "scoped-recall-boundary",
        "recall_before_installed_local_trust_boundary": "`installed local trust boundary`",
        "recall_before_context_inject": "`context_inject`",
        "recall_before_direct_answer": "`direct_answer`",
        "recall_before_platform_act": "`platform_act`",
        "platform_proof_state": "`platform_proof_state`",
        "platform_proof": "`platform_proof`",
        "platform_delivery_proven_count": "`platform_delivery_proven`",
        "proof_scope_projection": "`proof_scope_projection`",
        "scoped_installed_user_work_projection": "`scoped_installed_user_work_records`",
        "definition_cells_all_true": "all five Definition-of-Proven cells are true",
        "scope_or_casefile": "scope or casefile",
    }


def _expected_plan_strings() -> dict[str, str]:
    return {
        "casefile_command": "tools/trusted_memory_trust_metrics.py --json --user-work-casefile docs/fixtures/trusted-memory-user-work-cases.example.json",
        "scoped_probe_reads_installed_records": "reads installed",
        "scope_count_field": "`scope_count`",
        "scope_filters_field": "`scope_filters`",
        "user_work_scope_count_field": "`user_work_scope_count`",
        "user_work_scope_filters_field": "`user_work_scope_filters`",
        "user_work_case_evidence_field": "`user_work_case_evidence`",
        "user_work_case_metric_evidence_field": "`user_work_case_metric_evidence`",
        "casefile_observed_metrics": "`observed_metrics`",
        "casefile_expected_metrics_match": "`expected_metrics_match`",
        "casefile_repeat_requested": "`user_work_casefile_repeat_requested`",
        "casefile_repeat_completed": "`user_work_casefile_repeat_completed`",
        "casefile_stable": "`user_work_casefile_stable`",
        "casefile_metric_evidence_runs": "`user_work_case_metric_evidence_runs`",
        "proof_scope_matrix": "`proof_scope_matrix`",
        "proof_scope_fixture": "`fixture_backed_answer_path`",
        "proof_scope_controlled": "`controlled_temp_memory_answer_path`",
        "proof_scope_scoped_installed": "`scoped_installed_zhiyi_xingce_user_work_records`",
        "proof_scope_platform_wide": "`platform_wide_delivery`",
        "proof_scope_all_records": "`all_records_all_scopes`",
        "proof_scope_public_claim_rule": "`public_claim_rule`",
        "casefile_repeat_command": "--user-work-casefile-repeat 2",
        "casefile_repeat_requested_value": "`user_work_casefile_repeat_requested=2`",
        "casefile_repeat_completed_value": "`user_work_casefile_repeat_completed=2`",
        "casefile_stable_value": "`user_work_casefile_stable=true`",
        "casefile_expected_metrics_match_value": "`user_work_case_expected_metrics_match=true`",
        "user_preference": "user_preference",
        "work_record": "work_record",
        "no_generic_memory_layer": "extra generic memory layer",
        "not_all_records": "does not prove all records",
        "not_all_scopes": "all scopes",
        "not_all_platforms": "all platforms",
        "requires_real_command_evidence": "requires real command",
        "casefile_observed_at": "`observed_at`",
        "casefile_evidence_command": "`evidence_command`",
        "casefile_expected_metrics": "`expected_metrics`",
        "casefile_expected_metrics_checked": "status consistency gate checks each case's expected metrics",
        "casefile_case_evidence_observed_at": "`casefile_observed_at`",
        "casefile_case_evidence_command": "`casefile_evidence_command`",
        "source_backed_expectation_failed": "source_backed_expectation_failed",
        "failed_source_backed_cases": "failed_source_backed_cases",
        "failure_diagnostics": "`failure_diagnostics`",
        "diagnostic_casefile_case": "`casefile_case`",
        "diagnostic_casefile_record_kind": "`casefile_record_kind`",
        "diagnostic_authorized_scope_filter": "`authorized_scope_filter`",
        "diagnostic_model_verdict": "`model_verdict`",
        "insufficient_evidence_not_source_backed": "`model_verdict=insufficient_evidence`",
        "zhiyi_xingce_positioning_gap": "Zhiyi/Xingce positioning remains a separate evidence gap",
        "yifanchen_only_positioning_query": "`忆凡尘的定位是什么？`",
        "diagnostic_unknown_reason": "`unknown_reason`",
        "diagnostic_used_source_refs": "`used_source_refs`",
        "diagnostic_evidence_packet_refs": "`evidence_packet_refs`",
        "diagnostic_missing_cells": "`missing_cells`",
        "code_change_tiandao_source_audit_command": "tools/code_change_tiandao_audit.py --json",
        "code_change_complete_tiandao_source_audit_command": "tools/code_change_tiandao_audit.py --max-refs 0 --require-complete --json",
        "code_change_complete_source_refs": "`complete_source_refs=true`",
        "code_change_no_truncation": "`source_refs_truncated=false`",
        "code_change_require_complete": "`--require-complete`",
        "code_change_source_refs_only": "`source_refs_only_until_raw_origin`",
        "code_change_verification_output_flag": "--verification-output",
        "code_change_verification_command_flag": "--verification-command",
        "code_change_verification_source_refs": "`verification_source_refs`",
        "code_change_test_output_not_supplied": "`test_output_evidence_status=not_supplied`",
        "code_change_test_output_source_refs_only": "`test_output_evidence_status=source_refs_only`",
        "code_change_not_auto_adopt": "does not auto-adopt code changes into",
        "code_change_not_release_claims": "not release claims",
        "recall_before_liveness_command": "tools/recall_before_judgment_liveness_probe.py --json",
        "recall_before_installed_authoritative": "`authoritative_anchor_surfaced`",
        "recall_before_installed_decision_surface": "`decision=surface`",
        "recall_before_installed_source_refs": "`source_refs_count=5`",
        "recall_before_installed_preflight_surface_required": "`preflight_surface_required`",
        "recall_before_service_source_status": "`service_source_status=matches_working_tree`",
        "recall_before_service_refresh_not_required": "`service_refresh_required=false`",
        "recall_before_not_model_delivery": "does not prove model answer delivery",
        "recall_before_scoped_recall_boundary": "scoped-recall-boundary",
        "recall_before_installed_local_trust_boundary": "`installed local trust boundary`",
        "recall_before_context_inject": "`context_inject`",
        "recall_before_direct_answer": "`direct_answer`",
        "recall_before_platform_act": "`platform_act`",
        "platform_proof_state": "`platform_proof_state`",
        "platform_proof": "`platform_proof`",
        "platform_delivery_proven_count": "`platform_delivery_proven`",
        "proof_scope_projection": "`proof_scope_projection`",
        "scoped_installed_user_work_projection": "`scoped_installed_user_work_records`",
        "definition_cells_all_true": "all five Definition-of-Proven cells are true",
        "scope_or_casefile": "scope or casefile",
    }


def check_trusted_memory_status_consistency(
    *,
    repo_root: str | Path,
    casefile: str | Path = "docs/fixtures/trusted-memory-user-work-cases.example.json",
    status_page: str | Path = "docs/wiki/Trusted-Memory-And-Delivery-Status.md",
    plan_page: str | Path = "docs/decisions/2026-06-21-trusted-memory-next-plan.md",
) -> dict[str, Any]:
    """Check status/plan numbers and boundaries against the scoped casefile."""

    root = Path(repo_root).expanduser().resolve()
    casefile_path = (root / casefile).resolve() if not Path(casefile).is_absolute() else Path(casefile)
    status_path = (root / status_page).resolve() if not Path(status_page).is_absolute() else Path(status_page)
    plan_path = (root / plan_page).resolve() if not Path(plan_page).is_absolute() else Path(plan_page)

    errors: list[str] = []
    case_load = _load_json(casefile_path)
    status_load = _load_text(status_path)
    plan_load = _load_text(plan_path)
    if not case_load.get("ok"):
        errors.append(str(case_load.get("error")))
    if not status_load.get("ok"):
        errors.append(str(status_load.get("error")))
    if not plan_load.get("ok"):
        errors.append(str(plan_load.get("error")))
    if errors:
        return {
            "ok": False,
            "contract": TRUSTED_MEMORY_STATUS_CONSISTENCY_CONTRACT,
            "repo_root": str(root),
            "casefile": str(casefile_path),
            "status_page": str(status_path),
            "plan_page": str(plan_path),
            "read_only": True,
            "write_performed": False,
            "user_work_records_read": False,
            "platform_action_performed": False,
            "errors": errors,
        }

    payload = case_load["payload"]
    cases_raw = payload.get("cases")
    cases = cases_raw if isinstance(cases_raw, list) else []
    if not isinstance(cases_raw, list):
        errors.append("casefile_cases_must_be_list")

    normalized_cases = [_case_values(case) for case in cases]
    expected_metric_cases = [_case_expected_metrics(case) for case in cases]
    for index, case in enumerate(normalized_cases, start=1):
        for field in ("name", "record_kind", "observed_at", "evidence_command", "scope_filter", "source_query", "unknown_query"):
            if not case.get(field):
                errors.append(f"case_{index}_missing_{field}")
        evidence_command = case.get("evidence_command", "")
        if evidence_command:
            if "tools/trusted_memory_user_work_trace_probe.py" not in evidence_command:
                errors.append(f"case_{index}_evidence_command_not_probe")
            for field in ("scope_filter", "source_query", "unknown_query"):
                value = case.get(field, "")
                if value and value not in evidence_command:
                    errors.append(f"case_{index}_evidence_command_missing_{field}")
        source_query = case.get("source_query", "")
        if source_query in FORBIDDEN_CASE_SOURCE_QUERIES:
            errors.append(f"case_{index}_forbidden_source_query:{source_query}")
        if case.get("name", "") in FORBIDDEN_CASE_NAMES:
            errors.append(f"case_{index}_forbidden_case_name:{case['name']}")
        if case.get("name", "") == "codex-history-provider-filter-work-proof":
            unknown_query = case.get("unknown_query", "")
            if unknown_query != REQUIRED_CODEX_HISTORY_UNKNOWN_QUERY:
                errors.append("codex_history_case_missing_release_tag_sha_unknown_query")
            for forbidden_unknown in FORBIDDEN_CODEX_HISTORY_UNKNOWN_QUERIES:
                if unknown_query == forbidden_unknown:
                    errors.append(f"codex_history_case_forbidden_unknown_query:{forbidden_unknown}")
        metrics = expected_metric_cases[index - 1] if index - 1 < len(expected_metric_cases) else {}
        if not metrics:
            errors.append(f"case_{index}_missing_expected_metrics")
        for metric_name, expected_value in REQUIRED_CASE_EXPECTED_METRICS.items():
            if metrics.get(metric_name) != expected_value:
                errors.append(f"case_{index}_expected_metric_mismatch:{metric_name}")

    scopes = {case["scope_filter"] for case in normalized_cases if case.get("scope_filter")}
    record_kinds = {case["record_kind"] for case in normalized_cases if case.get("record_kind")}
    case_count = len(normalized_cases)
    scope_count = len(scopes)
    expected_metric_totals = {
        "ordinary_chats_checked": sum(
            int(metrics.get("ordinary_chats_checked") or 0)
            for metrics in expected_metric_cases
            if metrics
        ),
        "source_claims_checked": sum(
            int(metrics.get("source_claims_checked") or 0)
            for metrics in expected_metric_cases
            if metrics
        ),
        "unknown_cases_checked": sum(
            int(metrics.get("unknown_cases_checked") or 0)
            for metrics in expected_metric_cases
            if metrics
        ),
    }
    if expected_metric_totals["ordinary_chats_checked"] != case_count * 2:
        errors.append("casefile_expected_metrics_ordinary_total_mismatch")
    if expected_metric_totals["source_claims_checked"] != case_count:
        errors.append("casefile_expected_metrics_source_total_mismatch")
    if expected_metric_totals["unknown_cases_checked"] != case_count:
        errors.append("casefile_expected_metrics_unknown_total_mismatch")
    if case_count < 3:
        errors.append("casefile_must_have_at_least_3_cases")
    if scope_count < 2:
        errors.append("casefile_must_have_at_least_2_scopes")
    for required_kind in ALLOWED_USER_WORK_RECORD_KINDS:
        if required_kind not in record_kinds:
            errors.append(f"casefile_missing_{required_kind}_coverage")
    for record_kind in sorted(record_kinds):
        if record_kind not in ALLOWED_USER_WORK_RECORD_KINDS:
            errors.append(f"casefile_unsupported_record_kind:{record_kind}")

    status_text = str(status_load["text"])
    expected = _expected_status_strings(case_count, scope_count)
    missing_status_strings = [
        label
        for label, needle in expected.items()
        if needle not in status_text
    ]
    for label in missing_status_strings:
        errors.append(f"status_page_missing_{label}")

    plan_text = str(plan_load["text"])
    expected_plan = _expected_plan_strings()
    missing_plan_strings = [
        label
        for label, needle in expected_plan.items()
        if needle not in plan_text
    ]
    for label in missing_plan_strings:
        errors.append(f"plan_page_missing_{label}")

    checked_texts = {
        "status_page": status_text,
        "plan_page": plan_text,
    }
    forbidden_framing_hits: list[dict[str, str]] = []
    for label, text in checked_texts.items():
        lowered = text.lower()
        for term in FORBIDDEN_TRUSTED_MEMORY_FRAMING:
            haystack = lowered if term.isascii() else text
            needle = term.lower() if term.isascii() else term
            if needle in haystack:
                forbidden_framing_hits.append({"surface": label, "term": term})
    for hit in forbidden_framing_hits:
        errors.append(f"{hit['surface']}_forbidden_trusted_memory_framing:{hit['term']}")

    return {
        "ok": not errors,
        "contract": TRUSTED_MEMORY_STATUS_CONSISTENCY_CONTRACT,
        "repo_root": str(root),
        "casefile": str(casefile_path),
        "status_page": str(status_path),
        "plan_page": str(plan_path),
        "case_count": case_count,
        "scope_count": scope_count,
        "record_kinds": sorted(record_kinds),
        "case_expected_metric_totals": expected_metric_totals,
        "ordinary_chats_expected": case_count * 2,
        "source_claims_expected": case_count,
        "unknown_cases_expected": case_count,
        "receipt_visibility_expected": case_count * 2,
        "expected_status_strings": expected,
        "expected_plan_strings": expected_plan,
        "missing_status_strings": missing_status_strings,
        "missing_plan_strings": missing_plan_strings,
        "forbidden_framing_hits": forbidden_framing_hits,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "user_work_records_read": False,
        "platform_action_performed": False,
        "limitations": [
            "checks_checked_in_casefile_and_status_page_only",
            "status_consistency_checker_does_not_read_installed_records",
            "does_not_prove_all_records_or_platform_wide_delivery",
        ],
        "errors": errors,
    }


__all__ = [
    "ALLOWED_USER_WORK_RECORD_KINDS",
    "TRUSTED_MEMORY_STATUS_CONSISTENCY_CONTRACT",
    "check_trusted_memory_status_consistency",
]
