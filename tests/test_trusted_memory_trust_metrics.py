import json
from pathlib import Path

from src.trusted_memory_trust_metrics import (
    CASE_EXPECTED_METRIC_FIELDS,
    TRUSTED_MEMORY_PROOF_SCOPE_MATRIX_CONTRACT,
    TRUSTED_MEMORY_TRUST_METRICS_CONTRACT,
    build_trusted_memory_trust_metrics,
)
from src.trusted_memory_status_consistency import check_trusted_memory_status_consistency
from tools import trusted_memory_trust_metrics as cli

ROOT = Path(__file__).resolve().parents[1]
USER_WORK_CASEFILE = ROOT / "docs" / "fixtures" / "trusted-memory-user-work-cases.example.json"
TRUSTED_MEMORY_STATUS = ROOT / "docs" / "wiki" / "Trusted-Memory-And-Delivery-Status.md"


def _probe(contract: str, *, controlled: bool = False) -> dict:
    prefix = "real" if controlled else "live"
    return {
        "ok": True,
        "contract": contract,
        "fixture_backed": not controlled,
        "controlled_temp_memory": controlled,
        "user_work_records_read": False,
        "platform_action_performed": False,
        "cases": [
            {
                "case": "source_backed",
                "ordinary_handled": False,
                "explicit_handled": True,
                "answer": "先核对 NAS，再实施下一刀。",
                "answer_source": "evidence_bound_model_call",
                "model_called": True,
                "request_sent": True,
                "evidence_packet_refs": [f"exp-{prefix}-trace-next"],
                "used_source_refs": [f"exp-{prefix}-trace-next"],
                "source_refs": [{"library_id": f"exp-{prefix}-trace-next", "source_path": "/tmp/source.jsonl"}],
                "receipt_status": "source_backed",
                "unknown_boundary": False,
                "trace_status": "proven",
                "model_delivery_state": "observed",
            },
            {
                "case": "unknown",
                "ordinary_handled": False,
                "explicit_handled": True,
                "answer": "UNKNOWN",
                "answer_source": "evidence_bound_model_call",
                "model_called": True,
                "request_sent": True,
                "evidence_packet_refs": [f"exp-{prefix}-trace-gap"],
                "used_source_refs": [],
                "source_refs": [{"library_id": f"exp-{prefix}-trace-gap", "source_path": "/tmp/gap.jsonl"}],
                "receipt_status": "unknown",
                "unknown_boundary": True,
                "trace_status": "proven",
                "model_delivery_state": "observed",
            },
        ],
    }


def _expected_case_metrics(**overrides: object) -> dict:
    metrics = {
        "ordinary_chats_checked": 2,
        "source_claims_checked": 1,
        "unknown_cases_checked": 1,
        "hijack_rate": "0/2",
        "unsupported_answer_rate": "0/1",
        "unknown_discipline": "1/1",
        "source_reachability": "1/1",
        "receipt_visibility": "2/2",
    }
    metrics.update(overrides)
    return metrics


def test_trusted_memory_trust_metrics_reports_trust_axis():
    result = build_trusted_memory_trust_metrics(
        [
            _probe("trusted_memory_live_trace_probe.v2026.6.21"),
            _probe("trusted_memory_real_memory_trace_probe.v2026.6.21", controlled=True),
        ],
        generated_by="test",
    )

    assert result["ok"] is True
    assert result["contract"] == TRUSTED_MEMORY_TRUST_METRICS_CONTRACT
    assert result["read_only"] is True
    assert result["user_work_records_read"] is False
    assert result["platform_action_performed"] is False
    assert result["not_installed_user_work_record_proof"] is True
    assert result["not_platform_wide_delivery_proof"] is True
    assert result["counts"]["cases_total"] == 4
    assert result["counts"]["source_backed_cases_expected"] == 2
    assert result["counts"]["source_backed_cases_proven"] == 2
    assert result["counts"]["model_delivery_observed_cases"] == 4
    assert result["metrics"]["hijack_rate"]["percent"] == 0.0
    assert result["metrics"]["unsupported_answer_rate"]["percent"] == 0.0
    assert result["metrics"]["unknown_discipline"]["percent"] == 100.0
    assert result["metrics"]["source_reachability"]["percent"] == 100.0
    assert result["metrics"]["receipt_visibility"]["percent"] == 100.0
    matrix = result["proof_scope_matrix"]
    assert matrix["contract"] == TRUSTED_MEMORY_PROOF_SCOPE_MATRIX_CONTRACT
    rows = {row["proof_scope"]: row for row in matrix["rows"]}
    assert rows["fixture_backed_answer_path"]["proof_state"] == "observed_trace_passed"
    assert rows["controlled_temp_memory_answer_path"]["proof_state"] == "controlled_temp_memory_passed"
    assert rows["scoped_installed_zhiyi_xingce_user_work_records"]["proof_state"] == "not_performed"
    assert rows["platform_wide_delivery"]["proof_state"] == "platform_wide_delivery_unproven"
    assert rows["all_records_all_scopes"]["proof_state"] == "broad_all_records_unproven"
    assert rows["platform_wide_delivery"]["platform_wide"] is True
    assert rows["all_records_all_scopes"]["broad_all_records"] is True
    assert result["failure_examples"]["hijacked_cases"] == []
    assert result["failure_examples"]["failed_source_backed_cases"] == []
    assert result["failure_diagnostics"]["hijacked_cases"] == []
    assert result["failure_diagnostics"]["failed_source_backed_cases"] == []


def test_trusted_memory_trust_metrics_flags_hijack_and_unsupported_answer():
    probe = _probe("trusted_memory_live_trace_probe.v2026.6.21")
    probe["cases"][0]["ordinary_handled"] = True
    probe["cases"][0]["used_source_refs"] = []

    result = build_trusted_memory_trust_metrics([probe])

    assert result["ok"] is False
    assert "hijack_rate_above_zero" in result["errors"]
    assert "unsupported_answer_rate_above_zero" in result["errors"]
    assert result["metrics"]["hijack_rate"]["numerator"] == 1
    assert result["metrics"]["unsupported_answer_rate"]["numerator"] == 1
    assert result["failure_examples"]["hijacked_cases"]
    assert result["failure_examples"]["unsupported_answer_cases"]


def test_trusted_memory_trust_metrics_flags_source_backed_expectation_failure():
    probe = _probe("trusted_memory_user_work_trace_probe.v2026.6.21")
    probe["cases"][0]["case"] = "source_backed"
    probe["cases"][0]["casefile_case"] = "exampletool-preference-scope-proof"
    probe["cases"][0]["casefile_record_kind"] = "user_preference"
    probe["cases"][0]["authorized_scope_filter"] = "window/fixture-window-7f60287b"
    probe["cases"][0]["receipt_status"] = "unknown"
    probe["cases"][0]["answer"] = "UNKNOWN"
    probe["cases"][0]["unknown_boundary"] = True
    probe["cases"][0]["used_source_refs"] = []
    probe["cases"][0]["model_verdict"] = "insufficient_evidence"
    probe["cases"][0]["unknown_reason"] = "missing_remote_release_receipt"
    probe["cases"][0]["model_validation_error"] = "used refs missing"
    probe["cases"][0]["missing_cells"] = ["answer_evidence_observed"]
    probe["cases"][0]["recall_count"] = 1

    result = build_trusted_memory_trust_metrics([probe])

    assert result["ok"] is False
    assert "source_backed_expectation_failed" in result["errors"]
    assert result["counts"]["source_backed_cases_expected"] == 1
    assert result["counts"]["source_backed_cases_proven"] == 0
    assert result["failure_examples"]["failed_source_backed_cases"] == [
        "trusted_memory_user_work_trace_probe.v2026.6.21:source_backed"
    ]
    diagnostic = result["failure_diagnostics"]["failed_source_backed_cases"][0]
    assert diagnostic["case_id"] == "trusted_memory_user_work_trace_probe.v2026.6.21:source_backed"
    assert diagnostic["casefile_case"] == "exampletool-preference-scope-proof"
    assert diagnostic["casefile_record_kind"] == "user_preference"
    assert diagnostic["authorized_scope_filter"] == "window/fixture-window-7f60287b"
    assert diagnostic["model_verdict"] == "insufficient_evidence"
    assert diagnostic["model_validation_error"] == "used refs missing"
    assert diagnostic["unknown_reason"] == "missing_remote_release_receipt"
    assert diagnostic["receipt_status"] == "unknown"
    assert diagnostic["trace_status"] == "proven"
    assert diagnostic["model_delivery_state"] == "observed"
    assert diagnostic["recall_count"] == 1
    assert diagnostic["used_source_refs"] == []
    assert diagnostic["evidence_packet_refs"] == ["exp-live-trace-next"]
    assert diagnostic["missing_cells"] == ["answer_evidence_observed"]
    assert diagnostic["ordinary_handled"] is False
    assert diagnostic["explicit_handled"] is True
    assert diagnostic["unknown_boundary"] is True


def test_trusted_memory_trust_metrics_rejects_insufficient_source_backed_verdict():
    probe = _probe("trusted_memory_user_work_trace_probe.v2026.6.21")
    probe["cases"][0]["case"] = "source_backed"
    probe["cases"][0]["casefile_case"] = "time_library-positioning-scoped-preference-proof"
    probe["cases"][0]["casefile_record_kind"] = "user_preference"
    probe["cases"][0]["authorized_scope_filter"] = "window/fixture-window-7f60287b"
    probe["cases"][0]["model_verdict"] = "insufficient_evidence"
    probe["cases"][0]["unknown_reason"] = "知意行策的定位信息在证据中不完整"

    result = build_trusted_memory_trust_metrics([probe])

    assert result["ok"] is False
    assert "unsupported_answer_rate_above_zero" in result["errors"]
    assert "source_backed_expectation_failed" in result["errors"]
    assert result["counts"]["source_claims_checked"] == 0
    assert result["counts"]["source_backed_cases_expected"] == 1
    assert result["counts"]["source_backed_cases_proven"] == 0
    diagnostic = result["failure_diagnostics"]["failed_source_backed_cases"][0]
    assert diagnostic["casefile_case"] == "time_library-positioning-scoped-preference-proof"
    assert diagnostic["model_verdict"] == "insufficient_evidence"
    assert diagnostic["unknown_reason"] == "知意行策的定位信息在证据中不完整"


def test_trusted_memory_trust_metrics_counts_omitted_source_backed_answer_claim():
    probe = _probe("trusted_memory_user_work_trace_probe.v2026.6.21")
    probe["cases"][0]["answer"] = ""
    probe["cases"][0]["answer_omitted"] = True

    result = build_trusted_memory_trust_metrics([probe])

    assert result["ok"] is True
    assert result["counts"]["source_claims_checked"] == 1
    assert result["metrics"]["source_reachability"]["denominator"] == 1
    assert result["metrics"]["source_reachability"]["ok"] is True


def test_trusted_memory_trust_metrics_cli_uses_repeatable_probes(monkeypatch):
    called = {"live": 0, "controlled": 0}

    def live_probe():
        called["live"] += 1
        return _probe("fixture")

    def controlled_probe():
        called["controlled"] += 1
        return _probe("controlled", controlled=True)

    monkeypatch.setattr(cli.trusted_memory_live_trace_probe, "run_probe", live_probe)
    monkeypatch.setattr(cli.trusted_memory_real_memory_trace_probe, "run_probe", controlled_probe)

    result = cli.run_metrics()

    assert result["ok"] is True
    assert result["generated_by"] == "tools/trusted_memory_trust_metrics.py"
    assert result["deterministic_contract_fixture"] is True
    assert result["live_model_probe_performed"] is False
    assert called == {"live": 0, "controlled": 0}
    assert result["counts"]["probes_total"] == 2
    assert result["counts"]["cases_total"] == 4
    assert "deterministic_contract_fixture_is_not_a_live_model_probe" in result["limitations"]


def test_trusted_memory_trust_metrics_cli_can_run_live_probes(monkeypatch):
    monkeypatch.setattr(cli.trusted_memory_live_trace_probe, "run_probe", lambda: _probe("fixture"))
    monkeypatch.setattr(cli.trusted_memory_real_memory_trace_probe, "run_probe", lambda: _probe("controlled", controlled=True))

    result = cli.run_metrics(live_probes=True)

    assert result["ok"] is True
    assert result["generated_by"] == "tools/trusted_memory_trust_metrics.py --live-probes"
    assert result["deterministic_contract_fixture"] is False
    assert result["live_model_probe_performed"] is True
    assert result["counts"]["probes_total"] == 2
    assert result["counts"]["cases_total"] == 4


def test_trusted_memory_trust_metrics_user_work_probe_requires_scope_and_queries():
    result = cli.run_metrics(user_work_probe=True)

    assert result["ok"] is False
    assert result["generated_by"] == "tools/trusted_memory_trust_metrics.py --user-work-probe"
    assert result["evaluation_scope"] == "scoped_installed_zhiyi_xingce_user_work_record_probe"
    assert result["deterministic_contract_fixture"] is False
    assert result["installed_user_work_probe_performed"] is False
    assert result["user_work_records_read"] is False
    assert "one_or_more_probe_inputs_not_ok" in result["errors"]
    assert "no_probe_cases_supplied" in result["errors"]
    assert "user_work_probe_requires_scope_filter_and_two_queries" in result["limitations"]


def test_trusted_memory_trust_metrics_can_include_scoped_user_work_probe(monkeypatch):
    monkeypatch.setattr(
        cli.trusted_memory_user_work_trace_probe,
        "run_probe",
        lambda **kwargs: {
            **_probe("trusted_memory_user_work_trace_probe.v2026.6.21"),
            "fixture_backed": False,
            "controlled_temp_memory": False,
            "user_work_records_read": True,
            "model_call_performed": True,
            "authorized_scope_filter": kwargs["scope_filter"],
            "authorized_caller_scope": {
                "canonical_window_id": kwargs["scope_filter"],
                "source_system": "trusted_memory_probe",
                "computer_id": "local",
            },
        },
    )

    result = cli.run_metrics(
        user_work_probe=True,
        scope_filter="current-window",
        source_query="用户偏好是什么？",
        unknown_query="远端发布完成了吗？",
    )

    assert result["ok"] is True
    assert result["generated_by"] == "tools/trusted_memory_trust_metrics.py --user-work-probe"
    assert result["deterministic_contract_fixture"] is False
    assert result["live_model_probe_performed"] is True
    assert result["installed_user_work_probe_performed"] is True
    assert result["user_work_records_read"] is True
    assert result["not_installed_user_work_record_proof"] is False
    assert result["user_work_scope_filter"] == "current-window"
    assert result["user_work_caller_scope"]["canonical_window_id"] == "current-window"
    assert "installed_user_work_probe_is_scope_limited_not_platform_wide" in result["limitations"]


def test_trusted_memory_trust_metrics_can_include_user_work_casefile(monkeypatch, tmp_path):
    casefile = tmp_path / "trusted-memory-cases.json"
    casefile.write_text('{"cases":[]}', encoding="utf-8")

    def fake_casefile(**kwargs):
        assert kwargs["casefile"] == str(casefile)
        first = _probe("trusted_memory_user_work_trace_probe.v2026.6.21")
        second = _probe("trusted_memory_user_work_trace_probe.v2026.6.21")
        return {
            "ok": True,
            "contract": "trusted_memory_user_work_trace_probe.v2026.6.21",
            "status": "proven",
            "read_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "model_call_performed": True,
            "user_work_records_read": True,
            "platform_action_performed": False,
            "case_count": 2,
            "scope_count": 2,
            "scope_filters": ["window/a", "window/b"],
            "record_kinds": ["user_preference", "work_record"],
            "case_results": [first, second],
            "cases": [
                {
                    **case,
                    "casefile_case": "pref-exampletool",
                    "casefile_record_kind": "user_preference",
                    "casefile_observed_at": "2026-06-21",
                    "casefile_evidence_command": (
                        "python3 tools/trusted_memory_user_work_trace_probe.py --json "
                        "--scope-filter window/a --source-query ExampleTool --unknown-query release"
                    ),
                    "casefile_expected_metrics": _expected_case_metrics(),
                    "authorized_scope_filter": "window/a",
                }
                for case in first["cases"]
            ] + [
                {
                    **case,
                    "casefile_case": "work-next",
                    "casefile_record_kind": "work_record",
                    "casefile_observed_at": "2026-06-21",
                    "casefile_evidence_command": (
                        "python3 tools/trusted_memory_user_work_trace_probe.py --json "
                        "--scope-filter window/b --source-query Codex --unknown-query release"
                    ),
                    "casefile_expected_metrics": _expected_case_metrics(),
                    "authorized_scope_filter": "window/b",
                }
                for case in second["cases"]
            ],
        }

    monkeypatch.setattr(cli.trusted_memory_user_work_trace_probe, "run_casefile", fake_casefile)

    result = cli.run_metrics(
        user_work_probe=True,
        user_work_casefile=str(casefile),
    )

    assert result["ok"] is True
    assert result["generated_by"] == "tools/trusted_memory_trust_metrics.py --user-work-probe"
    assert result["evaluation_scope"] == "scoped_installed_zhiyi_xingce_user_work_record_probe"
    assert result["installed_user_work_probe_performed"] is True
    assert result["user_work_records_read"] is True
    assert result["user_work_casefile"] == str(casefile)
    assert result["user_work_case_count"] == 2
    assert result["user_work_scope_count"] == 2
    assert result["user_work_scope_filters"] == ["window/a", "window/b"]
    assert result["user_work_record_kinds"] == ["user_preference", "work_record"]
    assert result["user_work_case_evidence"] == [
        {
            "casefile_case": "pref-exampletool",
            "casefile_record_kind": "user_preference",
            "casefile_observed_at": "2026-06-21",
            "casefile_evidence_command": (
                "python3 tools/trusted_memory_user_work_trace_probe.py --json "
                "--scope-filter window/a --source-query ExampleTool --unknown-query release"
            ),
            "casefile_expected_metrics": _expected_case_metrics(),
            "authorized_scope_filter": "window/a",
        },
        {
            "casefile_case": "work-next",
            "casefile_record_kind": "work_record",
            "casefile_observed_at": "2026-06-21",
            "casefile_evidence_command": (
                "python3 tools/trusted_memory_user_work_trace_probe.py --json "
                "--scope-filter window/b --source-query Codex --unknown-query release"
            ),
            "casefile_expected_metrics": _expected_case_metrics(),
            "authorized_scope_filter": "window/b",
        },
    ]
    assert result["user_work_case_expected_metrics_checked"] is True
    assert result["user_work_case_expected_metrics_match"] is True
    rows = {row["proof_scope"]: row for row in result["proof_scope_matrix"]["rows"]}
    assert rows["scoped_installed_zhiyi_xingce_user_work_records"]["proof_state"] == "scoped_installed_user_work_proof"
    assert rows["scoped_installed_zhiyi_xingce_user_work_records"]["cases_checked"] == 4
    assert rows["scoped_installed_zhiyi_xingce_user_work_records"]["scope_count"] == 2
    assert rows["scoped_installed_zhiyi_xingce_user_work_records"]["record_kinds"] == ["user_preference", "work_record"]
    assert rows["scoped_installed_zhiyi_xingce_user_work_records"]["platform_wide"] is False
    assert rows["platform_wide_delivery"]["proof_state"] == "platform_wide_delivery_unproven"
    assert rows["all_records_all_scopes"]["proof_state"] == "broad_all_records_unproven"
    assert result["user_work_case_metric_evidence"] == [
        {
            "casefile_case": "pref-exampletool",
            "casefile_record_kind": "user_preference",
            "casefile_observed_at": "2026-06-21",
            "casefile_evidence_command": (
                "python3 tools/trusted_memory_user_work_trace_probe.py --json "
                "--scope-filter window/a --source-query ExampleTool --unknown-query release"
            ),
            "authorized_scope_filter": "window/a",
            "casefile_expected_metrics": _expected_case_metrics(),
            "observed_metrics": _expected_case_metrics(),
            "expected_metrics_match": True,
            "metric_mismatches": [],
        },
        {
            "casefile_case": "work-next",
            "casefile_record_kind": "work_record",
            "casefile_observed_at": "2026-06-21",
            "casefile_evidence_command": (
                "python3 tools/trusted_memory_user_work_trace_probe.py --json "
                "--scope-filter window/b --source-query Codex --unknown-query release"
            ),
            "authorized_scope_filter": "window/b",
            "casefile_expected_metrics": _expected_case_metrics(),
            "observed_metrics": _expected_case_metrics(),
            "expected_metrics_match": True,
            "metric_mismatches": [],
        },
    ]
    assert set(result["user_work_case_metric_evidence"][0]["observed_metrics"]) == set(CASE_EXPECTED_METRIC_FIELDS)
    assert result["counts"]["cases_total"] == 4
    assert result["counts"]["source_claims_checked"] == 2
    assert result["counts"]["unknown_cases_checked"] == 2
    assert result["metrics"]["hijack_rate"]["numerator"] == 0
    assert result["metrics"]["unsupported_answer_rate"]["numerator"] == 0
    assert result["metrics"]["unknown_discipline"]["numerator"] == 2
    assert result["metrics"]["source_reachability"]["numerator"] == 2
    assert "installed_user_work_casefile_is_scope_limited_not_platform_wide" in result["limitations"]


def test_trusted_memory_trust_metrics_user_work_casefile_fails_on_expected_metric_mismatch(monkeypatch, tmp_path):
    casefile = tmp_path / "trusted-memory-cases.json"
    casefile.write_text('{"cases":[]}', encoding="utf-8")

    def fake_casefile(**_kwargs):
        first = _probe("trusted_memory_user_work_trace_probe.v2026.6.21")
        return {
            "ok": True,
            "contract": "trusted_memory_user_work_trace_probe.v2026.6.21",
            "status": "proven",
            "read_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "model_call_performed": True,
            "user_work_records_read": True,
            "platform_action_performed": False,
            "case_count": 1,
            "scope_count": 1,
            "scope_filters": ["window/a"],
            "record_kinds": ["user_preference"],
            "case_results": [first],
            "cases": [
                {
                    **case,
                    "casefile_case": "pref-exampletool",
                    "casefile_record_kind": "user_preference",
                    "casefile_observed_at": "2026-06-21",
                    "casefile_evidence_command": "python3 tools/trusted_memory_user_work_trace_probe.py --json --scope-filter window/a --source-query ExampleTool --unknown-query release",
                    "casefile_expected_metrics": _expected_case_metrics(source_reachability="0/1"),
                    "authorized_scope_filter": "window/a",
                }
                for case in first["cases"]
            ],
        }

    monkeypatch.setattr(cli.trusted_memory_user_work_trace_probe, "run_casefile", fake_casefile)

    result = cli.run_metrics(
        user_work_probe=True,
        user_work_casefile=str(casefile),
    )

    assert result["ok"] is False
    assert result["user_work_case_expected_metrics_checked"] is True
    assert result["user_work_case_expected_metrics_match"] is False
    assert "user_work_case_expected_metric_mismatch:pref-exampletool:source_reachability" in result["errors"]
    assert result["user_work_case_metric_evidence"][0]["metric_mismatches"] == ["source_reachability"]
    assert result["user_work_case_metric_evidence"][0]["observed_metrics"]["source_reachability"] == "1/1"
    assert result["user_work_case_metric_evidence"][0]["casefile_expected_metrics"]["source_reachability"] == "0/1"


def test_trusted_memory_trust_metrics_user_work_casefile_repeat_marks_stable(monkeypatch, tmp_path):
    casefile = tmp_path / "trusted-memory-cases.json"
    casefile.write_text('{"cases":[]}', encoding="utf-8")
    calls = {"count": 0}

    def fake_casefile(**_kwargs):
        calls["count"] += 1
        first = _probe("trusted_memory_user_work_trace_probe.v2026.6.21")
        return {
            "ok": True,
            "contract": "trusted_memory_user_work_trace_probe.v2026.6.21",
            "status": "proven",
            "read_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "model_call_performed": True,
            "user_work_records_read": True,
            "platform_action_performed": False,
            "case_count": 1,
            "scope_count": 1,
            "scope_filters": ["window/a"],
            "record_kinds": ["user_preference"],
            "case_results": [first],
            "cases": [
                {
                    **case,
                    "casefile_case": "pref-exampletool",
                    "casefile_record_kind": "user_preference",
                    "casefile_observed_at": "2026-06-21",
                    "casefile_evidence_command": "python3 tools/trusted_memory_user_work_trace_probe.py --json --scope-filter window/a --source-query ExampleTool --unknown-query release",
                    "casefile_expected_metrics": _expected_case_metrics(),
                    "authorized_scope_filter": "window/a",
                }
                for case in first["cases"]
            ],
        }

    monkeypatch.setattr(cli.trusted_memory_user_work_trace_probe, "run_casefile", fake_casefile)

    result = cli.run_metrics(
        user_work_probe=True,
        user_work_casefile=str(casefile),
        user_work_casefile_repeat=2,
    )

    assert calls["count"] == 2
    assert result["ok"] is True
    assert result["generated_by"] == "tools/trusted_memory_trust_metrics.py --user-work-probe --user-work-casefile-repeat 2"
    assert result["user_work_casefile_repeat_requested"] == 2
    assert result["user_work_casefile_repeat_completed"] == 2
    assert result["user_work_casefile_stable"] is True
    assert result["user_work_case_expected_metrics_match"] is True
    assert len(result["user_work_case_metric_evidence_runs"]) == 2
    assert [run["repeat_index"] for run in result["user_work_case_metric_evidence_runs"]] == [1, 2]
    assert all(run["expected_metrics_match"] is True for run in result["user_work_case_metric_evidence_runs"])
    assert result["counts"]["cases_total"] == 4
    assert "user_work_casefile_repeat_is_live_stability_diagnostic_not_broad_proof" in result["limitations"]


def test_trusted_memory_trust_metrics_user_work_casefile_repeat_surfaces_variance(monkeypatch, tmp_path):
    casefile = tmp_path / "trusted-memory-cases.json"
    casefile.write_text('{"cases":[]}', encoding="utf-8")
    calls = {"count": 0}

    def fake_casefile(**_kwargs):
        calls["count"] += 1
        first = _probe("trusted_memory_user_work_trace_probe.v2026.6.21")
        expected = _expected_case_metrics()
        if calls["count"] == 2:
            expected = _expected_case_metrics(source_reachability="0/1")
        return {
            "ok": True,
            "contract": "trusted_memory_user_work_trace_probe.v2026.6.21",
            "status": "proven",
            "read_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "model_call_performed": True,
            "user_work_records_read": True,
            "platform_action_performed": False,
            "case_count": 1,
            "scope_count": 1,
            "scope_filters": ["window/a"],
            "record_kinds": ["user_preference"],
            "case_results": [first],
            "cases": [
                {
                    **case,
                    "casefile_case": "pref-exampletool",
                    "casefile_record_kind": "user_preference",
                    "casefile_observed_at": "2026-06-21",
                    "casefile_evidence_command": "python3 tools/trusted_memory_user_work_trace_probe.py --json --scope-filter window/a --source-query ExampleTool --unknown-query release",
                    "casefile_expected_metrics": expected,
                    "authorized_scope_filter": "window/a",
                }
                for case in first["cases"]
            ],
        }

    monkeypatch.setattr(cli.trusted_memory_user_work_trace_probe, "run_casefile", fake_casefile)

    result = cli.run_metrics(
        user_work_probe=True,
        user_work_casefile=str(casefile),
        user_work_casefile_repeat=2,
    )

    assert calls["count"] == 2
    assert result["ok"] is False
    assert result["user_work_casefile_stable"] is False
    assert result["user_work_case_expected_metrics_match"] is False
    assert "user_work_casefile_repeat_2:user_work_case_expected_metric_mismatch:pref-exampletool:source_reachability" in result["errors"]
    assert "user_work_casefile_repeat_not_stable" in result["errors"]
    assert result["user_work_case_metric_evidence_runs"][0]["expected_metrics_match"] is True
    assert result["user_work_case_metric_evidence_runs"][1]["expected_metrics_match"] is False
    assert result["user_work_case_metric_evidence_runs"][1]["case_metric_evidence"][0]["metric_mismatches"] == ["source_reachability"]


def test_user_work_casefile_status_numbers_stay_in_sync():
    report = check_trusted_memory_status_consistency(repo_root=ROOT)

    assert report["contract"] == "trusted_memory_status_consistency.v2026.6.21"
    assert report["case_count"] >= 3
    assert report["scope_count"] >= 2
    assert "user_preference" in report["record_kinds"]
    assert "work_record" in report["record_kinds"]
    assert report["user_work_records_read"] is False
    assert report["write_performed"] is False
    assert report["platform_action_performed"] is False
