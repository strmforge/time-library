import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import eval_entrypoints as eval_entrypoints_module
from eval_entrypoints import build_eval_plan, execute_eval_entrypoint
from eval_resource_ledger import (
    EVAL_CASE_LEDGER_CONTRACT,
    EVAL_RESOURCE_LEDGER_CONTRACT,
    finish_run_ledger,
    start_run_ledger,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_daily_profile_refuses_dataset_scan_and_judge():
    plan = build_eval_plan(
        profile="daily",
        host_label="macmini",
        max_questions=1,
        top_k=20,
        judge_requested=True,
    )

    assert plan["blocked"] is True
    assert "daily_retrieval_top_k_too_high" in plan["blocked_reasons"]
    assert "daily_retrieval_refuses_dataset_scan" in plan["blocked_reasons"]
    assert "daily_retrieval_refuses_judge" in plan["blocked_reasons"]


def test_daily_profile_refuses_benchmark_suite():
    plan = build_eval_plan(
        profile="daily",
        host_label="macmini",
        top_k=3,
        benchmark_suite="free",
    )

    assert plan["blocked"] is True
    assert "daily_retrieval_refuses_benchmark_suite" in plan["blocked_reasons"]


def test_regression_free_suite_requires_explicit_sample_count():
    plan = build_eval_plan(
        profile="regression",
        host_label="macmini",
        top_k=5,
        benchmark_suite="free",
    )

    assert plan["blocked"] is True
    assert "targeted_regression_requires_explicit_sample_count" in plan["blocked_reasons"]


def test_free_suite_warns_sample_count_is_per_dataset():
    plan = build_eval_plan(
        profile="regression",
        host_label="macmini",
        dataset="free",
        sample_count=1,
        top_k=5,
        benchmark_suite="free",
    )

    assert plan["ok"] is True
    assert "free_suite_sample_count_applies_per_dataset" in plan["warnings"]


def test_offline_free_suite_requires_sample_count_or_override_on_r730xd():
    plan = build_eval_plan(
        profile="offline",
        host_label="r730xd",
        top_k=5,
        watcher_active=False,
        benchmark_suite="free",
    )

    assert plan["blocked"] is True
    assert "offline_benchmark_requires_explicit_sample_count_or_override" in plan["blocked_reasons"]


def test_offline_profile_requires_confirmed_watcher_state():
    plan = build_eval_plan(
        profile="offline",
        host_label="r730xd",
        max_questions=20,
        top_k=5,
        watcher_active=None,
        watcher_active_source="auto_pgrep_unknown",
    )

    assert plan["blocked"] is True
    assert "offline_benchmark_requires_confirmed_watcher_state" in plan["blocked_reasons"]
    assert plan["watcher_active_source"] == "auto_pgrep_unknown"


def test_offline_profile_blocks_workstation_and_watcher_by_default():
    plan = build_eval_plan(
        profile="offline",
        host_label="macmini",
        max_questions=500,
        top_k=50,
        watcher_active=True,
    )

    assert plan["blocked"] is True
    assert "offline_benchmark_refuses_workstation_without_override" in plan["blocked_reasons"]
    assert "offline_benchmark_refuses_watcher_concurrency" in plan["blocked_reasons"]
    assert plan["offline_host_required"] == "r730xd"


def test_offline_profile_allows_r730xd_with_resource_ledger_required():
    plan = build_eval_plan(
        profile="offline",
        host_label="r730xd",
        max_questions=100,
        top_k=50,
        watcher_active=False,
        watcher_active_source="cli_explicit",
    )

    assert plan["ok"] is True
    assert plan["resource_ledger_required"] is True
    assert plan["resume_required"] is True
    assert plan["watcher_active_source"] == "cli_explicit"


def test_resource_ledger_records_run_fields():
    ledger = start_run_ledger(
        profile="regression",
        host_label="macmini",
        dataset="longmemeval",
        split="oracle",
        sample_count=3,
        retrieval_mode="dry_run",
        top_k=5,
        watcher_active_at_start=False,
        repo_root=ROOT,
    )
    finished = finish_run_ledger(ledger, status="ok")

    assert finished["contract"] == EVAL_RESOURCE_LEDGER_CONTRACT
    assert finished["run_id"]
    assert finished["profile"] == "regression"
    assert finished["hostname"]
    assert finished["git_commit"] is not None
    assert finished["elapsed_ms"] >= 0
    assert finished["cpu_user_seconds"] >= 0
    assert finished["cpu_system_seconds"] >= 0
    assert finished["rss_peak_bytes"] >= 0
    assert "_perf_started" not in finished


def test_regression_entrypoint_resumes_completed_cases(tmp_path):
    cases_path = tmp_path / "cases.jsonl"
    checkpoint_path = tmp_path / "checkpoint.json"
    case_ledger_path = tmp_path / "cases-ledger.jsonl"
    _write_jsonl(
        cases_path,
        [
            {"case_id": "c1", "question_id": "q1", "source_refs": ["r1"], "hypothesis": "a"},
            {"case_id": "c2", "question_id": "q2", "source_refs": ["r2"]},
            {"case_id": "c3", "question_id": "q3"},
        ],
    )
    checkpoint_path.write_text(json.dumps({"completed_case_ids": ["c1"]}), encoding="utf-8")

    payload = execute_eval_entrypoint(
        profile="regression",
        host_label="macmini",
        dataset="fixture",
        sample_count=3,
        top_k=5,
        retrieval_mode="dry_run",
        checkpoint_path=checkpoint_path,
        case_ledger_path=case_ledger_path,
        case_list_path=cases_path,
        repo_root=ROOT,
    )

    assert payload["ok"] is True
    assert payload["ledger"]["status"] == "ok"
    assert payload["case_stats"]["ran"] == 2
    assert payload["case_stats"]["skipped"] == 1

    rows = [json.loads(line) for line in case_ledger_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert rows[0]["contract"] == EVAL_CASE_LEDGER_CONTRACT
    assert rows[0]["case_id"] == "c1"
    assert rows[0]["resume_skipped"] is True
    assert rows[1]["case_id"] == "c2"
    assert rows[1]["resume_skipped"] is False

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint["completed_case_ids"] == ["c1", "c2", "c3"]


def test_offline_entrypoint_returns_blocked_ledger_on_workstation():
    payload = execute_eval_entrypoint(
        profile="offline",
        host_label="macmini",
        dataset="longmemeval",
        sample_count=500,
        top_k=50,
        watcher_active=True,
        watcher_active_source="auto_pgrep",
        repo_root=ROOT,
    )

    assert payload["ok"] is False
    assert payload["ledger"]["status"] == "blocked"
    assert payload["ledger"]["watcher_active_source"] == "auto_pgrep"
    assert "offline_benchmark_refuses_workstation_without_override" in payload["ledger"]["block_reason"]


def test_regression_free_benchmark_writes_ledgers_and_summary(tmp_path, monkeypatch):
    checkpoint_path = tmp_path / "checkpoint.json"
    case_ledger_path = tmp_path / "case-ledger.jsonl"
    run_ledger_path = tmp_path / "run-ledger.json"

    def fake_load_free_cases(**kwargs):
        assert kwargs["max_questions"] == 2
        return [
            {"case_id": "locomo:q1", "question_id": "q1", "benchmark_dataset": "locomo"},
            {"case_id": "longmemeval:q1", "question_id": "q1", "benchmark_dataset": "longmemeval"},
        ]

    def fake_case_runner(case, *, top_k, retrieval_mode):
        return {
            "status": "ok",
            "dataset": case["benchmark_dataset"],
            "split": "oracle" if case["benchmark_dataset"] == "longmemeval" else "locomo10",
            "retrieval_mode": retrieval_mode,
            "top_k": top_k,
            "source_refs_count": 2,
            "hypothesis_written": False,
            "judge_verdict": "",
            "metrics": {
                "exact_source_recall": 1.0,
                "bundled_source_recall": 1.0,
                "near_source_recall": 1.0,
                "answer_supported_recall": 1.0,
                "answer_supported_hits": 1,
                "exact_miss_answer_supported_hits": 0,
                "exact_hit_answer_unsupported_hits": 0,
                "answer_support_level_counts": {"top_result": 1},
                "session_recall": 1.0,
                "gold_anchor_recall": 1.0,
            },
            "official_leaderboard_score": False,
            "no_api_key_required": True,
            "no_model_call": True,
            "no_memory_write": True,
        }

    monkeypatch.setattr(eval_entrypoints_module, "load_free_benchmark_cases", fake_load_free_cases)
    monkeypatch.setattr(eval_entrypoints_module, "free_benchmark_case_runner", fake_case_runner)

    payload = execute_eval_entrypoint(
        profile="regression",
        host_label="macmini",
        dataset="free",
        sample_count=2,
        top_k=5,
        benchmark_suite="free",
        watcher_active_source="cli_explicit",
        checkpoint_path=checkpoint_path,
        case_ledger_path=case_ledger_path,
        run_ledger_path=run_ledger_path,
        repo_root=ROOT,
    )

    assert payload["ok"] is True
    assert payload["plan"]["benchmark_suite"] == "free"
    assert payload["plan"]["retrieval_mode"] == "fused_library_index_bm25"
    assert payload["ledger"]["status"] == "ok"
    assert payload["ledger"]["benchmark_suite"] == "free"
    assert payload["ledger"]["watcher_active_source"] == "cli_explicit"
    assert payload["ledger"]["requested_sample_count"] == 2
    assert payload["ledger"]["actual_case_count"] == 2
    assert payload["case_stats"]["ran"] == 2
    assert payload["benchmark_result"]["mode"] == "free_retrieval_benchmark_small_sample"
    assert {item["dataset"] for item in payload["benchmark_result"]["results"]} == {"locomo", "longmemeval"}
    first_result = payload["benchmark_result"]["results"][0]
    assert "answer_supported_recall" in first_result
    assert "answer_support_level_counts" in first_result
    assert run_ledger_path.exists()

    rows = [json.loads(line) for line in case_ledger_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["result"]["no_api_key_required"] is True
    assert rows[0]["result"]["no_model_call"] is True

    run_ledger = json.loads(run_ledger_path.read_text(encoding="utf-8"))
    assert run_ledger["status"] == "ok"
    assert run_ledger["watcher_active_source"] == "cli_explicit"
    assert run_ledger["case_ledger_path"] == str(case_ledger_path)


def test_regression_free_benchmark_resume_skips_completed(tmp_path, monkeypatch):
    checkpoint_path = tmp_path / "checkpoint.json"
    case_ledger_path = tmp_path / "case-ledger.jsonl"
    checkpoint_path.write_text(json.dumps({"completed_case_ids": ["locomo:q1"]}), encoding="utf-8")

    monkeypatch.setattr(
        eval_entrypoints_module,
        "load_free_benchmark_cases",
        lambda **kwargs: [
            {"case_id": "locomo:q1", "question_id": "q1", "benchmark_dataset": "locomo"},
            {"case_id": "locomo:q2", "question_id": "q2", "benchmark_dataset": "locomo"},
        ],
    )
    monkeypatch.setattr(
        eval_entrypoints_module,
        "free_benchmark_case_runner",
        lambda case, *, top_k, retrieval_mode: {
            "status": "ok",
            "dataset": "locomo",
            "split": "locomo10",
            "retrieval_mode": retrieval_mode,
            "top_k": top_k,
            "metrics": {
                "exact_source_recall": 1.0,
                "bundled_source_recall": 1.0,
                "near_source_recall": 1.0,
                "session_recall": 1.0,
                "gold_anchor_recall": 1.0,
            },
        },
    )

    payload = execute_eval_entrypoint(
        profile="regression",
        host_label="macmini",
        dataset="locomo",
        sample_count=2,
        top_k=5,
        benchmark_suite="free",
        checkpoint_path=checkpoint_path,
        case_ledger_path=case_ledger_path,
        repo_root=ROOT,
    )

    assert payload["ok"] is True
    assert payload["case_stats"]["skipped"] == 1
    assert payload["case_stats"]["ran"] == 1

    rows = [json.loads(line) for line in case_ledger_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["case_id"] == "locomo:q1"
    assert rows[0]["resume_skipped"] is True
    assert rows[1]["case_id"] == "locomo:q2"
