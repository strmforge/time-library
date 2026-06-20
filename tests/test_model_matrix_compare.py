import json
from pathlib import Path

from src.model_matrix_compare import (
    MODEL_MATRIX_COMPARE_CONTRACT,
    compare_model_matrix_summaries,
    render_model_matrix_compare_markdown,
)


def _write_summary(path: Path, *, fast: bool, calls: int, elapsed: float, decisions: dict, rows: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "model_matrix_eval.v2026.6.19",
                "dataset": "locomo",
                "fast_mode": fast,
                "results": [
                    {
                        "provider": "deepseek",
                        "model": "deepseek-v4-flash",
                        "fast_mode": fast,
                        "selected_case_count": len(rows),
                        "model_call_count": calls,
                        "elapsed_seconds": elapsed,
                        "local_cpu_seconds": 0.4 if not fast else 0.2,
                        "max_rss_mb": 58.0,
                        "model_error_count": 0,
                        "decision_counts": decisions,
                        "metrics": {
                            "careful_requested_total": 0,
                            "trigger_candidate_no_support": 0,
                        },
                        "model_by_decision": {},
                        "rows": rows,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_model_matrix_compare_reports_speed_and_row_drift(tmp_path):
    baseline = tmp_path / "baseline.json"
    fast = tmp_path / "fast.json"
    _write_summary(
        baseline,
        fast=False,
        calls=4,
        elapsed=20.0,
        decisions={"skip_redundant": 1, "stop_no_support": 1},
        rows=[
            {"question_id": "q1", "decision": "skip_redundant", "model_class": "model_both_supported", "needs_careful_mode": False},
            {"question_id": "q2", "decision": "stop_no_support", "model_class": "model_top_only", "needs_careful_mode": False},
        ],
    )
    _write_summary(
        fast,
        fast=True,
        calls=2,
        elapsed=12.0,
        decisions={"skip_redundant": 1, "trigger_candidate": 1},
        rows=[
            {"question_id": "q1", "decision": "skip_redundant", "model_class": "model_both_supported", "needs_careful_mode": False},
            {"question_id": "q2", "decision": "trigger_candidate", "model_class": "model_pack_improved", "needs_careful_mode": False},
        ],
    )

    report = compare_model_matrix_summaries(baseline, fast)

    assert report["contract"] == MODEL_MATRIX_COMPARE_CONTRACT
    assert report["delta"]["model_call_count"] == -2
    assert report["delta"]["model_call_count_pct"] == -0.5
    assert report["delta"]["elapsed_seconds_pct"] == -0.4
    assert report["decision_drift"]["row_level_available"] is True
    assert report["decision_drift"]["decision_drift_count"] == 1
    assert report["decision_drift"]["model_class_drift_count"] == 1
    assert "row_level_decision_drift_observed" in report["risk_flags"]
    markdown = render_model_matrix_compare_markdown(report)
    assert "Evidence-Bound Fast Mode Compare" in markdown
    assert "official_leaderboard_score: false" in markdown
