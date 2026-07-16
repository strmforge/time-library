import ast
import copy
import json
from pathlib import Path
import subprocess
import sys

from tools.r2_state_extractor_eval import _faithful_span, evaluate_experiment


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/r2_state_extractor_eval_fixture.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _controlled_fixture():
    fixture = _fixture()
    fixture["owner_gate"] = {
        "approved": True,
        "budget_cap_usd": 1.0,
        "quality_thresholds": {
            "minimum_per_arm": {
                "coverage_rate": 0.95,
                "preservation_rate": 0.95,
            },
            "maximum_per_arm": {
                "activation_violation_count": 0,
                "verifier_false_pass_count": 0,
                "unexpected_atom_count": 0,
            },
            "local_max_drop_vs_cloud": {
                "coverage_rate": 0.03,
                "preservation_rate": 0.03,
            },
        },
    }
    for arm in fixture["arms"]:
        arm["proof_layer"] = "controlled_model_eval"
        arm["model_call_performed"] = True
    return fixture


def test_fixture_scores_all_strata_but_keeps_r2_no_go():
    report = evaluate_experiment(_fixture())

    assert report["ok"] is True
    assert report["decision"] == "NO_GO"
    assert report["case_count"] == 6
    assert report["missing_strata"] == []
    assert report["comparison_status"] == "fixture_only_not_quality_evidence"
    assert report["no_overall_score"] is True
    assert "owner_quality_and_budget_gate_not_approved" in report["decision_reasons"]
    assert "owner_quality_thresholds_missing" in report["decision_reasons"]
    assert "fixture_results_are_not_model_quality_evidence" in report["decision_reasons"]
    assert "local_vs_cloud_model_results_missing" in report["decision_reasons"]
    assert len(report["arms"]) == 2
    for arm in report["arms"]:
        assert arm["non_negotiable_safety_invariants_pass"] is True
        assert arm["metrics"]["coverage_rate"] == 1.0
        assert arm["metrics"]["preservation_rate"] == 1.0
        assert arm["metrics"]["faithfulness_rate"] == 1.0
        assert arm["metrics"]["source_ref_retention_rate"] == 1.0
        assert arm["metrics"]["activation_violation_count"] == 0
    assert report["write_boundary"] == {
        "evaluator_model_call_performed": False,
        "network_call_performed": False,
        "production_shadow_write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
    }


def test_bad_span_reverses_faithfulness_and_catches_false_pass():
    fixture = _fixture()
    fixture["arms"][0]["results"][0]["atoms"][0]["source_span"]["text"] = "light"

    report = evaluate_experiment(fixture)
    arm = report["arms"][0]

    assert arm["metrics"]["faithfulness_rate"] == 0.833333
    assert arm["metrics"]["verifier_false_pass_count"] == 2
    assert arm["non_negotiable_safety_invariants_pass"] is False
    assert "non_negotiable_safety_invariant_failed" in report["decision_reasons"]


def test_source_ref_loss_is_a_hard_failure():
    fixture = _fixture()
    fixture["arms"][1]["results"][2]["atoms"][0]["source_refs"].pop()

    report = evaluate_experiment(fixture)
    arm = report["arms"][1]

    assert arm["metrics"]["source_ref_retention_rate"] == 0.833333
    assert arm["non_negotiable_safety_invariants_pass"] is False


def test_utf8_source_span_uses_byte_offsets_not_character_offsets():
    atom = {
        "source_span": {"byte_start": 9, "byte_end": 15, "text": "深色"},
    }

    assert _faithful_span("主题是深色。", atom) is True
    atom["source_span"]["byte_start"] = 3
    assert _faithful_span("主题是深色。", atom) is False


def test_evaluator_aligns_answer_key_blind_atom_ids_by_unique_ref_and_span():
    fixture = _fixture()
    expected = fixture["cases"][0]["expected_atoms"][0]
    actual = fixture["arms"][0]["results"][0]["atoms"][0]
    expected["source_refs"] = copy.deepcopy(actual["source_refs"])
    expected["source_span"] = copy.deepcopy(actual["source_span"])
    actual["atom_id"] = "atom-runtime-generated-without-answer-key"
    actual["source_span"] = copy.deepcopy(expected["source_span"])
    actual["source_span"]["byte_end"] += 1
    actual["source_span"]["text"] = fixture["cases"][0]["source_text"].encode("utf-8")[
        actual["source_span"]["byte_start"]:actual["source_span"]["byte_end"]
    ].decode("utf-8")

    arm = evaluate_experiment(fixture)["arms"][0]

    assert arm["cases"][0]["coverage_ok"] is True
    assert arm["cases"][0]["preservation_ok"] is True
    assert arm["cases"][0]["unexpected_atom_count"] == 0


def test_evaluator_does_not_align_one_runtime_span_across_two_expected_atoms():
    fixture = _fixture()
    case = fixture["cases"][0]
    actual_atoms = fixture["arms"][0]["results"][0]["atoms"]
    for expected, atom in zip(case["expected_atoms"], actual_atoms):
        expected["source_refs"] = copy.deepcopy(atom["source_refs"])
        expected["source_span"] = copy.deepcopy(atom["source_span"])
    actual = actual_atoms[0]
    actual["atom_id"] = "atom-crosses-two-answer-units"
    actual["source_span"] = {
        "byte_start": case["expected_atoms"][0]["source_span"]["byte_start"],
        "byte_end": case["expected_atoms"][1]["source_span"]["byte_end"],
        "text": case["source_text"].encode("utf-8")[
            case["expected_atoms"][0]["source_span"]["byte_start"]:
            case["expected_atoms"][1]["source_span"]["byte_end"]
        ].decode("utf-8"),
    }

    case_result = evaluate_experiment(fixture)["arms"][0]["cases"][0]

    assert case_result["coverage_ok"] is False
    assert case_result["unexpected_atom_count"] == 1


def test_schema_state_taint_time_and_activation_are_hard_safety_gates():
    mutations = [
        ("semantic_type", "unknown-type", "schema_valid_rate"),
        ("state_role", "superseded", "state_role_accuracy"),
        ("taint", "unknown", "taint_accuracy"),
        ("recorded_at", "2026-07-13T23:59:59Z", "temporal_consistency_rate"),
        ("activation_allowed", True, "activation_violation_count"),
    ]
    for field, value, metric in mutations:
        fixture = _fixture()
        fixture["arms"][0]["results"][0]["atoms"][0][field] = value

        arm = evaluate_experiment(fixture)["arms"][0]

        assert arm["non_negotiable_safety_invariants_pass"] is False
        if metric == "activation_violation_count":
            assert arm["metrics"][metric] > 0
        else:
            assert arm["metrics"][metric] < 1.0


def test_expected_shelf_and_dual_time_are_hard_safety_gates_when_keyed():
    fixture = _fixture()
    expected = fixture["cases"][0]["expected_atoms"][0]
    actual = fixture["arms"][0]["results"][0]["atoms"][0]
    expected.update({
        "shelf": actual["shelf"],
        "observed_at": actual["observed_at"],
        "recorded_at": actual["recorded_at"],
        "valid_from": actual["valid_from"],
        "valid_to": actual["valid_to"],
    })
    fixture["arms"][0]["results"][0]["atoms"][0]["valid_from"] = "2026-07-13T00:00:00Z"

    arm = evaluate_experiment(fixture)["arms"][0]

    assert arm["metrics"]["shelf_accuracy"] == 1.0
    assert arm["metrics"]["dual_time_accuracy"] == 0.833333
    assert arm["non_negotiable_safety_invariants_pass"] is False


def test_owner_approval_cannot_turn_fixture_results_into_model_evidence():
    fixture = _fixture()
    fixture["owner_gate"] = {
        "approved": True,
        "budget_cap_usd": 1.0,
        "quality_thresholds": {
            "minimum_per_arm": {"coverage_rate": 1.0},
            "maximum_per_arm": {"activation_violation_count": 0},
            "local_max_drop_vs_cloud": {"coverage_rate": 0.0},
        },
    }

    report = evaluate_experiment(fixture)

    assert report["decision"] == "NO_GO"
    assert report["total_estimated_cost_usd"] == 0.000258
    assert "fixture_results_are_not_model_quality_evidence" in report["decision_reasons"]
    assert "local_vs_cloud_model_results_missing" in report["decision_reasons"]


def test_decision_gate_can_open_for_complete_controlled_receipt_metadata():
    fixture = _controlled_fixture()

    report = evaluate_experiment(fixture)

    assert report["decision"] == "GO"
    assert report["decision_reasons"] == []
    assert report["comparison_status"] == "ready_for_owner_review"


def test_budget_quality_and_structural_gaps_stay_explicit():
    fixture = _controlled_fixture()
    fixture["owner_gate"]["budget_cap_usd"] = 0.0001
    fixture["arms"][0]["results"][0]["atoms"].pop()
    fixture["arms"][0]["results"].append(copy.deepcopy(fixture["arms"][0]["results"][1]))
    fixture["arms"][0]["results"].append({"case_id": "not-in-manifest", "atoms": []})

    report = evaluate_experiment(fixture)
    local = report["arms"][0]

    assert report["decision"] == "NO_GO"
    assert "owner_budget_cap_exceeded" in report["decision_reasons"]
    assert "quality_minimum_failed:local_fixture:coverage_rate" in report["decision_reasons"]
    assert "non_negotiable_safety_invariant_failed" in report["decision_reasons"]
    assert local["metrics"]["duplicate_result_case_count"] == 1
    assert local["metrics"]["unknown_result_case_count"] == 1


def test_missing_model_identity_measurements_and_pricing_are_not_ready():
    fixture = _controlled_fixture()
    fixture["arms"][0]["model_id"] = ""
    fixture["arms"][0]["results"][0].pop("latency_ms")
    fixture["arms"][1]["price_usd_per_million"].pop("output")

    report = evaluate_experiment(fixture)

    assert report["decision"] == "NO_GO"
    assert "model_identity_missing" in report["decision_reasons"]
    assert "latency_or_usage_measurement_missing" in report["decision_reasons"]
    assert "cost_accounting_incomplete" in report["decision_reasons"]


def test_hybrid_arm_reports_rule_only_and_model_owned_work_separately():
    fixture = _controlled_fixture()
    for arm in fixture["arms"]:
        arm["pipeline_mode"] = "hybrid_ambiguity"
        for index, result in enumerate(arm["results"]):
            result["model_call_performed"] = index == 0
            result["model_call_ok"] = index == 0
            result["rule_candidate_count"] = len(result["atoms"])
            result["ambiguity_candidate_count"] = 1 if index == 0 else 0
            result["model_decision_count"] = 1 if index == 0 else 0
            if index != 0:
                result["latency_ms"] = 0.0
                result["usage"] = {"input_tokens": 0, "output_tokens": 0}

    report = evaluate_experiment(fixture)

    assert report["decision"] == "GO"
    for arm in report["arms"]:
        assert arm["pipeline_mode"] == "hybrid_ambiguity"
        assert arm["hybrid_measurement_complete"] is True
        assert arm["metrics"]["model_call_case_count"] == 1
        assert arm["metrics"]["rule_only_case_count"] == 5
        assert arm["metrics"]["model_call_rate"] == 0.166667
        assert arm["metrics"]["rule_candidate_count"] == 7
        assert arm["metrics"]["ambiguity_candidate_count"] == 1
        assert arm["metrics"]["model_decision_count"] == 1
        assert arm["metrics"]["model_latency_p50_ms"] is not None


def test_hybrid_failed_model_call_cannot_be_reported_as_complete_or_go():
    fixture = _controlled_fixture()
    for arm in fixture["arms"]:
        arm["pipeline_mode"] = "hybrid_ambiguity"
        for index, result in enumerate(arm["results"]):
            result["model_call_performed"] = index == 0
            result["model_call_ok"] = index == 0
            result["rule_candidate_count"] = len(result["atoms"])
            result["ambiguity_candidate_count"] = 1 if index == 0 else 0
            result["model_decision_count"] = 1 if index == 0 else 0
    fixture["arms"][0]["results"][0]["model_call_ok"] = False

    report = evaluate_experiment(fixture)

    assert report["decision"] == "NO_GO"
    assert "local_vs_cloud_model_results_missing" in report["decision_reasons"]
    assert report["arms"][0]["hybrid_measurement_complete"] is False


def test_malformed_json_shapes_return_no_go_instead_of_crashing():
    malformed_inputs = [
        None,
        [],
        "not-an-object",
        7,
        {"cases": 7, "arms": 8, "required_strata": 9, "owner_gate": 10},
        {"cases": [{}], "arms": [{"results": 11}]},
    ]

    for value in malformed_inputs:
        report = evaluate_experiment(value)
        assert isinstance(report, dict)
        assert report["decision"] == "NO_GO"


def test_cli_writes_the_same_report_as_library_call(tmp_path):
    output = tmp_path / "report.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/r2_state_extractor_eval.py"),
            "--input",
            str(FIXTURE),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert json.loads(output.read_text(encoding="utf-8")) == evaluate_experiment(_fixture())


def test_evaluation_is_deterministic_and_does_not_mutate_input():
    fixture = _fixture()
    before = copy.deepcopy(fixture)

    first = evaluate_experiment(fixture)
    second = evaluate_experiment(fixture)

    assert fixture == before
    assert first == second


def test_evaluator_has_no_network_model_subprocess_or_database_imports():
    path = ROOT / "tools/r2_state_extractor_eval.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"requests", "httpx", "urllib", "socket", "subprocess", "sqlite3"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(forbidden)
