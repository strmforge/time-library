import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from src.trusted_memory_status_consistency import (
    ALLOWED_USER_WORK_RECORD_KINDS,
    REQUIRED_CASE_EXPECTED_METRICS,
    TRUSTED_MEMORY_STATUS_CONSISTENCY_CONTRACT,
    check_trusted_memory_status_consistency,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "trusted_memory_status_consistency.py"


def _write_fixture(root: Path, *, status_text: str, cases: list[dict], plan_text: Optional[str] = None) -> None:
    casefile = root / "docs" / "fixtures" / "trusted-memory-user-work-cases.example.json"
    status = root / "docs" / "wiki" / "Trusted-Memory-And-Delivery-Status.md"
    plan = root / "docs" / "decisions" / "2026-06-21-trusted-memory-next-plan.md"
    casefile.parent.mkdir(parents=True)
    status.parent.mkdir(parents=True)
    plan.parent.mkdir(parents=True)
    casefile.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
    status.write_text(status_text, encoding="utf-8")
    plan.write_text(plan_text if plan_text is not None else _plan_text(), encoding="utf-8")


def _cases() -> list[dict]:
    return [
        {
            "name": "one",
            "record_kind": "user_preference",
            "observed_at": "2026-06-21",
            "evidence_command": "python3 tools/trusted_memory_user_work_trace_probe.py --json --scope-filter window/a --source-query A --unknown-query 'A done?'",
            "scope_filter": "window/a",
            "source_query": "A",
            "unknown_query": "A done?",
            "expected_metrics": dict(REQUIRED_CASE_EXPECTED_METRICS),
        },
        {
            "name": "two",
            "record_kind": "user_preference",
            "observed_at": "2026-06-21",
            "evidence_command": "python3 tools/trusted_memory_user_work_trace_probe.py --json --scope-filter window/a --source-query B --unknown-query 'B done?'",
            "scope_filter": "window/a",
            "source_query": "B",
            "unknown_query": "B done?",
            "expected_metrics": dict(REQUIRED_CASE_EXPECTED_METRICS),
        },
        {
            "name": "three",
            "record_kind": "work_record",
            "observed_at": "2026-06-21",
            "evidence_command": (
                "python3 tools/trusted_memory_user_work_trace_probe.py --json --scope-filter window/b "
                "--source-query C --unknown-query 'Codex 历史恢复是否已经发布到 GitHub release tag memcore-v2099.1.1，并且发布包 SHA256 是 0000000000000000000000000000000000000000000000000000000000000000？'"
            ),
            "scope_filter": "window/b",
            "source_query": "C",
            "unknown_query": "Codex 历史恢复是否已经发布到 GitHub release tag memcore-v2099.1.1，并且发布包 SHA256 是 0000000000000000000000000000000000000000000000000000000000000000？",
            "expected_metrics": dict(REQUIRED_CASE_EXPECTED_METRICS),
        },
    ]


def _status_text() -> str:
    return "\n".join(
        [
            "`user_work_case_count=3`",
            "`user_work_scope_count=2`",
            "`ordinary_chats_checked=6`",
            "`source_claims_checked=3`",
            "`unknown_cases_checked=3`",
            "`hijack_rate=0/6`",
            "`unsupported_answer_rate=0/3`",
            "`unknown_discipline=3/3`",
            "`source_reachability=3/3`",
            "`receipt_visibility=6/6`",
            "Each checked case keeps `observed_at` and `evidence_command`.",
            "Each checked case also keeps `expected_metrics`.",
            "The trust metrics runner emits `user_work_case_evidence` with `casefile_observed_at` and `casefile_evidence_command`.",
            "The trust metrics runner emits `user_work_case_metric_evidence` with `observed_metrics` and `expected_metrics_match`.",
            "The trust metrics runner can repeat a casefile and report `user_work_casefile_repeat_requested`, `user_work_casefile_repeat_completed`, `user_work_casefile_stable`, and `user_work_case_metric_evidence_runs`.",
            "The trust metrics runner emits `proof_scope_matrix` with `fixture_backed_answer_path`, `controlled_temp_memory_answer_path`, `scoped_installed_zhiyi_xingce_user_work_records`, `platform_wide_delivery`, `all_records_all_scopes`, and `public_claim_rule`.",
            "Repeat command includes --user-work-casefile-repeat 2 and observed `user_work_casefile_repeat_requested=2`, `user_work_casefile_repeat_completed=2`, `user_work_casefile_stable=true`, and `user_work_case_expected_metrics_match=true`.",
            "three scoped installed cases across two window scopes, with user_preference and work_record coverage, not all-record or platform-wide proof.",
            "`model_verdict=insufficient_evidence` is treated as source-backed failure even when used refs are present.",
            "Zhiyi/Xingce positioning remains a documented evidence gap.",
            "yifanchen-positioning-preference-proof",
            "Failed scoped cases include `failure_diagnostics` with `casefile_case`, `authorized_scope_filter`, `model_verdict`, and `missing_cells`.",
            "Current code-change Tiandao source audit reports code changes with `source_refs_only_until_raw_origin`, not automatic memory sediment or release proof. The complete source ledger command is tools/code_change_tiandao_audit.py --max-refs 0 --require-complete --json and should report `complete_source_refs=true` plus `source_refs_truncated=false`. Saved verification output artifacts appear as `verification_source_refs`; without one, `test_output_evidence_status=not_supplied`, and with one, `test_output_evidence_status=source_refs_only`.",
            "Current installed 9851 recall-before-judgment scoped-recall-boundary status is `authoritative_anchor_surfaced`, with `decision=surface`, `source_refs_count=5`, `preflight_surface_required`, `installed local trust boundary`, `context_inject`, `direct_answer`, and `platform_act`; service identity reports `service_source_status=matches_working_tree` and `service_refresh_required=false`; this does not prove model answer delivery.",
            "The platform delivery matrix now emits `platform_proof` with `platform_proof_state`, `platform_delivery_proven`, and `proof_scope_projection`; the projection includes `scoped_installed_user_work_records`. A platform row is proven only when all five Definition-of-Proven cells are true, and scope or casefile proof is not platform-wide proof.",
        ]
    )


def _plan_text() -> str:
    return "\n".join(
        [
            "tools/trusted_memory_trust_metrics.py --json --user-work-casefile docs/fixtures/trusted-memory-user-work-cases.example.json",
            "This scoped mode reads installed Zhiyi/Xingce records only inside supplied scope/query pairs.",
            "The casefile runner exposes `scope_count` and `scope_filters`.",
            "The trust metrics runner mirrors `user_work_scope_count` and `user_work_scope_filters`.",
            "The trust metrics runner emits `user_work_case_evidence` with `casefile_observed_at` and `casefile_evidence_command`.",
            "The trust metrics runner emits `user_work_case_metric_evidence` with per-case `observed_metrics` and `expected_metrics_match`.",
            "The trust metrics runner can repeat a casefile and report `user_work_casefile_repeat_requested`, `user_work_casefile_repeat_completed`, `user_work_casefile_stable`, and `user_work_case_metric_evidence_runs`.",
            "The trust metrics runner emits `proof_scope_matrix` with `fixture_backed_answer_path`, `controlled_temp_memory_answer_path`, `scoped_installed_zhiyi_xingce_user_work_records`, `platform_wide_delivery`, `all_records_all_scopes`, and `public_claim_rule`.",
            "Repeat command includes --user-work-casefile-repeat 2 and observed `user_work_casefile_repeat_requested=2`, `user_work_casefile_repeat_completed=2`, `user_work_casefile_stable=true`, and `user_work_case_expected_metrics_match=true`.",
            "Allowed record kinds are user_preference and work_record, not an extra generic memory layer.",
            "This does not prove all records, all scopes, or all platforms.",
            "Adding more cases requires real command evidence with `observed_at` and `evidence_command`.",
            "The status consistency gate checks each case's expected metrics through `expected_metrics` before accepting aggregate numbers.",
            "`model_verdict=insufficient_evidence` is treated as source-backed failure even when used refs are present.",
            "Zhiyi/Xingce positioning remains a separate evidence gap.",
            "The source query is `忆凡尘的定位是什么？`.",
            "tools/recall_before_judgment_liveness_probe.py --json shows installed 9851 scoped-recall-boundary `authoritative_anchor_surfaced`, `decision=surface`, `source_refs_count=5`, `preflight_surface_required`, `installed local trust boundary`, `context_inject`, `direct_answer`, `platform_act`, `service_source_status=matches_working_tree`, and `service_refresh_required=false`; this does not prove model answer delivery.",
            "Source-backed drift must report source_backed_expectation_failed and failed_source_backed_cases.",
            "Failures include `failure_diagnostics` with `casefile_case`, `casefile_record_kind`, `authorized_scope_filter`, `model_verdict`, `unknown_reason`, `used_source_refs`, `evidence_packet_refs`, and `missing_cells`.",
            "tools/code_change_tiandao_audit.py --json reports code-change source refs with `source_refs_only_until_raw_origin` and does not auto-adopt code changes into Zhiyi/Xingce/Toolbook records; these are not release claims. The full release-facing ledger command is tools/code_change_tiandao_audit.py --max-refs 0 --require-complete --json, and `--require-complete` requires `complete_source_refs=true` with `source_refs_truncated=false`. Optional saved test output uses --verification-output with --verification-command, emits `verification_source_refs`, and reports `test_output_evidence_status=not_supplied` until a saved artifact is supplied, then `test_output_evidence_status=source_refs_only`.",
            "tools/platform_delivery_matrix.py --json reports `platform_proof`, per-row `platform_proof_state`, the `platform_delivery_proven` count, and `proof_scope_projection` with `scoped_installed_user_work_records`; platform proof requires all five Definition-of-Proven cells are true, and scope or casefile proof is not platform-wide proof.",
        ]
    )


def test_trusted_memory_status_consistency_passes_for_synced_docs(tmp_path):
    _write_fixture(tmp_path, status_text=_status_text(), cases=_cases())

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is True
    assert report["contract"] == TRUSTED_MEMORY_STATUS_CONSISTENCY_CONTRACT
    assert ALLOWED_USER_WORK_RECORD_KINDS == ("user_preference", "work_record")
    assert report["case_count"] == 3
    assert report["scope_count"] == 2
    assert report["record_kinds"] == ["user_preference", "work_record"]
    assert report["case_expected_metric_totals"] == {
        "ordinary_chats_checked": 6,
        "source_claims_checked": 3,
        "unknown_cases_checked": 3,
    }
    assert report["ordinary_chats_expected"] == 6
    assert report["missing_plan_strings"] == []
    assert report["read_only"] is True
    assert report["user_work_records_read"] is False
    assert report["memory_write_performed"] is False
    assert report["platform_action_performed"] is False
    assert "status_consistency_checker_does_not_read_installed_records" in report["limitations"]


def test_trusted_memory_status_consistency_rejects_stale_status_numbers(tmp_path):
    stale = _status_text().replace("`user_work_case_count=3`", "`user_work_case_count=2`")
    _write_fixture(tmp_path, status_text=stale, cases=_cases())

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "status_page_missing_user_work_case_count" in report["errors"]


def test_trusted_memory_status_consistency_rejects_old_combined_positioning_case(tmp_path):
    cases = _cases()
    cases[0]["source_query"] = "忆凡尘和知意行策的定位是什么？"
    cases[0]["evidence_command"] = (
        "python3 tools/trusted_memory_user_work_trace_probe.py --json "
        "--scope-filter window/a --source-query '忆凡尘和知意行策的定位是什么？' --unknown-query 'A done?'"
    )
    _write_fixture(tmp_path, status_text=_status_text(), cases=cases)

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "case_1_forbidden_source_query:忆凡尘和知意行策的定位是什么？" in report["errors"]


def test_trusted_memory_status_consistency_rejects_old_positioning_case_name(tmp_path):
    cases = _cases()
    cases[0]["name"] = "yifanchen-positioning-scoped-preference-proof"
    _write_fixture(tmp_path, status_text=_status_text(), cases=cases)

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "case_1_forbidden_case_name:yifanchen-positioning-scoped-preference-proof" in report["errors"]


def test_trusted_memory_status_consistency_rejects_flaky_codex_history_unknown_query(tmp_path):
    cases = _cases()
    cases[2]["name"] = "codex-history-provider-filter-work-proof"
    cases[2]["unknown_query"] = "Codex 历史恢复的远端发布回执已经完成了吗？"
    cases[2]["evidence_command"] = (
        "python3 tools/trusted_memory_user_work_trace_probe.py --json --scope-filter window/b "
        "--source-query C --unknown-query 'Codex 历史恢复的远端发布回执已经完成了吗？'"
    )
    _write_fixture(tmp_path, status_text=_status_text(), cases=cases)

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "codex_history_case_missing_release_tag_sha_unknown_query" in report["errors"]
    assert "codex_history_case_forbidden_unknown_query:Codex 历史恢复的远端发布回执已经完成了吗？" in report["errors"]


def test_trusted_memory_status_consistency_rejects_missing_boundary_text(tmp_path):
    boundaryless = (
        _status_text()
        .replace("not all-record or platform-wide proof", "scoped proof")
        .replace(
            "The platform delivery matrix now emits `platform_proof` with `platform_proof_state`, `platform_delivery_proven`, and `proof_scope_projection`; the projection includes `scoped_installed_user_work_records`. A platform row is proven only when all five Definition-of-Proven cells are true, and scope or casefile proof is not platform-wide proof.",
            "The platform delivery matrix now emits `platform_proof` with `platform_proof_state` and `platform_delivery_proven`.",
        )
    )
    _write_fixture(tmp_path, status_text=boundaryless, cases=_cases())

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "status_page_missing_not_all_record" in report["errors"]
    assert "status_page_missing_platform_wide_proof" in report["errors"]


def test_trusted_memory_status_consistency_rejects_missing_code_change_tiandao_boundary(tmp_path):
    status_without_code_boundary = _status_text().replace(
        "Current code-change Tiandao source audit reports code changes with `source_refs_only_until_raw_origin`, not automatic memory sediment or release proof. The complete source ledger command is tools/code_change_tiandao_audit.py --max-refs 0 --require-complete --json and should report `complete_source_refs=true` plus `source_refs_truncated=false`. Saved verification output artifacts appear as `verification_source_refs`; without one, `test_output_evidence_status=not_supplied`, and with one, `test_output_evidence_status=source_refs_only`.",
        "",
    )
    plan_without_code_boundary = _plan_text().replace(
        "tools/code_change_tiandao_audit.py --json reports code-change source refs with `source_refs_only_until_raw_origin` and does not auto-adopt code changes into Zhiyi/Xingce/Toolbook records; these are not release claims. The full release-facing ledger command is tools/code_change_tiandao_audit.py --max-refs 0 --require-complete --json, and `--require-complete` requires `complete_source_refs=true` with `source_refs_truncated=false`. Optional saved test output uses --verification-output with --verification-command, emits `verification_source_refs`, and reports `test_output_evidence_status=not_supplied` until a saved artifact is supplied, then `test_output_evidence_status=source_refs_only`.",
        "",
    )
    _write_fixture(
        tmp_path,
        status_text=status_without_code_boundary,
        cases=_cases(),
        plan_text=plan_without_code_boundary,
    )

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "status_page_missing_code_change_tiandao_source_audit" in report["errors"]
    assert "status_page_missing_code_change_complete_command" in report["errors"]
    assert "status_page_missing_code_change_complete_source_refs" in report["errors"]
    assert "status_page_missing_code_change_no_truncation" in report["errors"]
    assert "status_page_missing_code_change_source_refs_only" in report["errors"]
    assert "status_page_missing_code_change_verification_source_refs" in report["errors"]
    assert "status_page_missing_code_change_test_output_not_supplied" in report["errors"]
    assert "status_page_missing_code_change_test_output_source_refs_only" in report["errors"]
    assert "status_page_missing_code_change_not_memory_sediment" in report["errors"]
    assert "status_page_missing_code_change_not_release_proof" in report["errors"]
    assert "plan_page_missing_code_change_tiandao_source_audit_command" in report["errors"]
    assert "plan_page_missing_code_change_complete_tiandao_source_audit_command" in report["errors"]
    assert "plan_page_missing_code_change_complete_source_refs" in report["errors"]
    assert "plan_page_missing_code_change_no_truncation" in report["errors"]
    assert "plan_page_missing_code_change_require_complete" in report["errors"]
    assert "plan_page_missing_code_change_source_refs_only" in report["errors"]
    assert "plan_page_missing_code_change_verification_output_flag" in report["errors"]
    assert "plan_page_missing_code_change_verification_command_flag" in report["errors"]
    assert "plan_page_missing_code_change_verification_source_refs" in report["errors"]
    assert "plan_page_missing_code_change_test_output_not_supplied" in report["errors"]
    assert "plan_page_missing_code_change_test_output_source_refs_only" in report["errors"]
    assert "plan_page_missing_code_change_not_auto_adopt" in report["errors"]
    assert "plan_page_missing_code_change_not_release_claims" in report["errors"]


def test_trusted_memory_status_consistency_rejects_missing_recall_before_installed_liveness_proof(tmp_path):
    status_without_liveness = _status_text().replace(
        "Current installed 9851 recall-before-judgment scoped-recall-boundary status is `authoritative_anchor_surfaced`, with `decision=surface`, `source_refs_count=5`, `preflight_surface_required`, `installed local trust boundary`, `context_inject`, `direct_answer`, and `platform_act`; service identity reports `service_source_status=matches_working_tree` and `service_refresh_required=false`; this does not prove model answer delivery.",
        "",
    )
    plan_without_liveness = _plan_text().replace(
        "tools/recall_before_judgment_liveness_probe.py --json shows installed 9851 scoped-recall-boundary `authoritative_anchor_surfaced`, `decision=surface`, `source_refs_count=5`, `preflight_surface_required`, `installed local trust boundary`, `context_inject`, `direct_answer`, `platform_act`, `service_source_status=matches_working_tree`, and `service_refresh_required=false`; this does not prove model answer delivery.",
        "",
    )
    _write_fixture(
        tmp_path,
        status_text=status_without_liveness,
        cases=_cases(),
        plan_text=plan_without_liveness,
    )

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "status_page_missing_recall_before_installed_authoritative" in report["errors"]
    assert "status_page_missing_recall_before_installed_decision_surface" in report["errors"]
    assert "status_page_missing_recall_before_installed_source_refs" in report["errors"]
    assert "status_page_missing_recall_before_installed_preflight_surface_required" in report["errors"]
    assert "status_page_missing_recall_before_service_source_status" in report["errors"]
    assert "status_page_missing_recall_before_service_refresh_not_required" in report["errors"]
    assert "status_page_missing_recall_before_not_model_delivery" in report["errors"]
    assert "status_page_missing_recall_before_scoped_recall_boundary" in report["errors"]
    assert "status_page_missing_recall_before_installed_local_trust_boundary" in report["errors"]
    assert "status_page_missing_recall_before_context_inject" in report["errors"]
    assert "status_page_missing_recall_before_direct_answer" in report["errors"]
    assert "status_page_missing_recall_before_platform_act" in report["errors"]
    assert "plan_page_missing_recall_before_liveness_command" in report["errors"]
    assert "plan_page_missing_recall_before_installed_authoritative" in report["errors"]
    assert "plan_page_missing_recall_before_service_source_status" in report["errors"]
    assert "plan_page_missing_recall_before_service_refresh_not_required" in report["errors"]
    assert "plan_page_missing_recall_before_not_model_delivery" in report["errors"]
    assert "plan_page_missing_recall_before_scoped_recall_boundary" in report["errors"]
    assert "plan_page_missing_recall_before_installed_local_trust_boundary" in report["errors"]
    assert "plan_page_missing_recall_before_context_inject" in report["errors"]
    assert "plan_page_missing_recall_before_direct_answer" in report["errors"]
    assert "plan_page_missing_recall_before_platform_act" in report["errors"]


def test_trusted_memory_status_consistency_rejects_missing_platform_proof_boundary(tmp_path):
    status_without_platform_proof = _status_text().replace(
        "The platform delivery matrix now emits `platform_proof` with `platform_proof_state`, `platform_delivery_proven`, and `proof_scope_projection`; the projection includes `scoped_installed_user_work_records`. A platform row is proven only when all five Definition-of-Proven cells are true, and scope or casefile proof is not platform-wide proof.",
        "",
    )
    plan_without_platform_proof = _plan_text().replace(
        "tools/platform_delivery_matrix.py --json reports `platform_proof`, per-row `platform_proof_state`, the `platform_delivery_proven` count, and `proof_scope_projection` with `scoped_installed_user_work_records`; platform proof requires all five Definition-of-Proven cells are true, and scope or casefile proof is not platform-wide proof.",
        "",
    )
    _write_fixture(
        tmp_path,
        status_text=status_without_platform_proof,
        cases=_cases(),
        plan_text=plan_without_platform_proof,
    )

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "status_page_missing_platform_proof_state" in report["errors"]
    assert "status_page_missing_platform_proof" in report["errors"]
    assert "status_page_missing_platform_delivery_proven_count" in report["errors"]
    assert "status_page_missing_proof_scope_projection" in report["errors"]
    assert "status_page_missing_scoped_installed_user_work_projection" in report["errors"]
    assert "status_page_missing_definition_cells_all_true" in report["errors"]
    assert "status_page_missing_scope_or_casefile" in report["errors"]
    assert "plan_page_missing_platform_proof_state" in report["errors"]
    assert "plan_page_missing_platform_proof" in report["errors"]
    assert "plan_page_missing_platform_delivery_proven_count" in report["errors"]
    assert "plan_page_missing_proof_scope_projection" in report["errors"]
    assert "plan_page_missing_scoped_installed_user_work_projection" in report["errors"]
    assert "plan_page_missing_definition_cells_all_true" in report["errors"]
    assert "plan_page_missing_scope_or_casefile" in report["errors"]


def test_trusted_memory_status_consistency_rejects_missing_failure_diagnostic_contract(tmp_path):
    status_without_diagnostics = _status_text().replace(
        "Failed scoped cases include `failure_diagnostics` with `casefile_case`, `authorized_scope_filter`, `model_verdict`, and `missing_cells`.",
        "",
    )
    plan_without_diagnostics = _plan_text().replace(
        "Failures include `failure_diagnostics` with `casefile_case`, `casefile_record_kind`, `authorized_scope_filter`, `model_verdict`, `unknown_reason`, `used_source_refs`, `evidence_packet_refs`, and `missing_cells`.",
        "",
    )
    _write_fixture(
        tmp_path,
        status_text=status_without_diagnostics,
        cases=_cases(),
        plan_text=plan_without_diagnostics,
    )

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "status_page_missing_failure_diagnostics" in report["errors"]
    assert "status_page_missing_diagnostic_casefile_case" in report["errors"]
    assert "status_page_missing_diagnostic_authorized_scope_filter" in report["errors"]
    assert "status_page_missing_diagnostic_model_verdict" in report["errors"]
    assert "status_page_missing_diagnostic_missing_cells" in report["errors"]
    assert "plan_page_missing_failure_diagnostics" in report["errors"]
    assert "plan_page_missing_diagnostic_casefile_record_kind" in report["errors"]
    assert "plan_page_missing_diagnostic_unknown_reason" in report["errors"]
    assert "plan_page_missing_diagnostic_used_source_refs" in report["errors"]
    assert "plan_page_missing_diagnostic_evidence_packet_refs" in report["errors"]


def test_trusted_memory_status_consistency_rejects_stale_plan_contract(tmp_path):
    stale_plan = _plan_text().replace("`scope_count` and `scope_filters`", "scope fields")
    _write_fixture(tmp_path, status_text=_status_text(), cases=_cases(), plan_text=stale_plan)

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "plan_page_missing_scope_count_field" in report["errors"]
    assert "plan_page_missing_scope_filters_field" in report["errors"]


def test_trusted_memory_status_consistency_rejects_missing_record_kind(tmp_path):
    cases = _cases()
    cases[0].pop("record_kind")
    _write_fixture(tmp_path, status_text=_status_text(), cases=cases)

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "case_1_missing_record_kind" in report["errors"]


def test_trusted_memory_status_consistency_rejects_missing_or_mismatched_case_evidence(tmp_path):
    cases = _cases()
    cases[0].pop("observed_at")
    cases[1].pop("evidence_command")
    cases[2]["evidence_command"] = "python3 tools/trusted_memory_user_work_trace_probe.py --json --scope-filter window/other --source-query C --unknown-query 'C done?'"
    _write_fixture(tmp_path, status_text=_status_text(), cases=cases)

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "case_1_missing_observed_at" in report["errors"]
    assert "case_2_missing_evidence_command" in report["errors"]
    assert "case_3_evidence_command_missing_scope_filter" in report["errors"]


def test_trusted_memory_status_consistency_rejects_missing_or_mismatched_expected_metrics(tmp_path):
    cases = _cases()
    cases[0].pop("expected_metrics")
    cases[1]["expected_metrics"]["hijack_rate"] = "1/2"
    cases[2]["expected_metrics"]["ordinary_chats_checked"] = 1
    _write_fixture(tmp_path, status_text=_status_text(), cases=cases)

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "case_1_missing_expected_metrics" in report["errors"]
    assert "case_1_expected_metric_mismatch:hijack_rate" in report["errors"]
    assert "case_2_expected_metric_mismatch:hijack_rate" in report["errors"]
    assert "case_3_expected_metric_mismatch:ordinary_chats_checked" in report["errors"]
    assert "casefile_expected_metrics_ordinary_total_mismatch" in report["errors"]


def test_trusted_memory_status_consistency_rejects_wrong_private_memory_framing(tmp_path):
    _write_fixture(
        tmp_path,
        status_text=_status_text(),
        cases=_cases(),
        plan_text="错误口径：私人记忆需要 per-read authorization。\n",
    )

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert {
        "surface": "plan_page",
        "term": "私人记忆",
    } in report["forbidden_framing_hits"]
    assert {
        "surface": "plan_page",
        "term": "per-read authorization",
    } in report["forbidden_framing_hits"]
    assert "plan_page_forbidden_trusted_memory_framing:私人记忆" in report["errors"]
    assert "plan_page_forbidden_trusted_memory_framing:per-read authorization" in report["errors"]


def test_trusted_memory_status_consistency_rejects_missing_work_coverage(tmp_path):
    cases = _cases()
    for case in cases:
        case["record_kind"] = "user_preference"
    missing_work_status = _status_text().replace(" and work_record", "").replace("work_record", "")
    _write_fixture(tmp_path, status_text=missing_work_status, cases=cases)

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "casefile_missing_work_record_coverage" in report["errors"]
    assert "status_page_missing_work_record" in report["errors"]


def test_trusted_memory_status_consistency_rejects_unsupported_record_kind(tmp_path):
    cases = _cases()
    cases[0]["record_kind"] = "private_memory"
    _write_fixture(tmp_path, status_text=_status_text(), cases=cases)

    report = check_trusted_memory_status_consistency(repo_root=tmp_path)

    assert report["ok"] is False
    assert "casefile_missing_user_preference_coverage" not in report["errors"]
    assert "casefile_unsupported_record_kind:private_memory" in report["errors"]


def test_trusted_memory_status_consistency_cli_outputs_json(tmp_path):
    _write_fixture(tmp_path, status_text=_status_text(), cases=_cases())

    result = subprocess.run(
        [sys.executable, str(TOOL), "--repo-root", str(tmp_path), "--json"],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["contract"] == TRUSTED_MEMORY_STATUS_CONSISTENCY_CONTRACT


def test_trusted_memory_status_consistency_cli_is_importable():
    spec = importlib.util.spec_from_file_location("trusted_memory_status_consistency_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert callable(module.main)
