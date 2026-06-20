import json
import os
from pathlib import Path

from src import model_memory_judge
from src.model_memory_judge import (
    MODEL_MEMORY_JUDGE_CONTRACT,
    _normalize_model_judge_output,
    run_model_memory_judge,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_model_memory_judge_preflight_blocks_missing_key(tmp_path, monkeypatch):
    monkeypatch.delenv("MISSING_JUDGE_KEY", raising=False)
    reference = tmp_path / "ref.json"
    hypothesis = tmp_path / "hyp.jsonl"
    reference.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question": "What car issue?",
                    "question_type": "single-session-user",
                    "answer": "GPS issue",
                }
            ]
        ),
        encoding="utf-8",
    )
    _write_jsonl(hypothesis, [{"question_id": "q1", "hypothesis": "GPS issue"}])

    result = run_model_memory_judge(
        hypothesis_path=hypothesis,
        reference_path=reference,
        provider="deepseek",
        model="deepseek-v4-flash",
        api_key_env="MISSING_JUDGE_KEY",
        run=False,
    )

    assert result["contract"] == MODEL_MEMORY_JUDGE_CONTRACT
    assert result["ready_to_run"] is False
    assert "api_key_env" in result["blocked_reasons"]
    assert result["official_leaderboard_score"] is False
    assert result["boundary"]["secret_values_returned"] is False


def test_model_memory_judge_runs_batched_with_resume_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_JUDGE_KEY", "secret-value-not-serialized")
    reference = tmp_path / "ref.json"
    hypothesis = tmp_path / "hyp.jsonl"
    reference.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question": "What issue?",
                    "question_type": "single-session-user",
                    "answer": "GPS issue",
                },
                {
                    "question_id": "q2",
                    "question": "What theme?",
                    "question_type": "single-session-preference",
                    "answer": "The user would prefer dark mode.",
                },
            ]
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        hypothesis,
        [
            {"question_id": "q1", "hypothesis": "GPS issue"},
            {"question_id": "q2", "hypothesis": "The user would prefer dark mode."},
        ],
    )

    def fake_http(messages, config):
        payload = json.loads(messages[1]["content"].split("Items:\n", 1)[1])
        items = [
            {
                "question_id": row["question_id"],
                "verdict": "correct",
                "confidence": 0.9,
                "reason": "matches",
            }
            for row in payload
        ]
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "contract": "codex_assisted_memory_judge.v2026.6.17",
                    "items": items,
                    "summary": {
                        "correct": len(items),
                        "partial": 0,
                        "incorrect": 0,
                        "unjudgeable": 0,
                        "total": len(items),
                    },
                }
            ),
        }

    monkeypatch.setattr(model_memory_judge, "_http_chat_completion", fake_http)

    result = run_model_memory_judge(
        hypothesis_path=hypothesis,
        reference_path=reference,
        provider="openai_compatible",
        model="fake-judge",
        base_url="https://example.test/v1",
        api_key_env="FAKE_JUDGE_KEY",
        batch_size=1,
        run=True,
        out_dir=tmp_path / "run",
        repo_root=tmp_path,
    )

    assert result["ok"] is True
    assert result["codex_judge_score"]["official_like_binary_accuracy_100"] == 100.0
    assert result["judge_diagnostics"]["complete_item_coverage"] is True
    assert len(result["batch_results"]) == 2
    assert (tmp_path / "run" / "case-ledger.jsonl").exists()
    assert (tmp_path / "run" / "run-ledger.json").exists()
    assert "secret-value-not-serialized" not in json.dumps(result, ensure_ascii=False)


def test_model_memory_judge_normalizes_judgment_alias_from_cheap_models():
    normalized = _normalize_model_judge_output(
        {
            "judgment": [
                {
                    "question_id": "q1",
                    "verdict": "yes",
                    "confidence": 0.8,
                }
            ],
            "summary": {"correct": 0, "partial": 0, "incorrect": 0, "unjudgeable": 0, "total": 0},
        }
    )

    assert normalized["items"] == [
        {
            "question_id": "q1",
            "verdict": "correct",
            "confidence": 0.8,
            "reason": "model returned verdict without a reason",
        }
    ]
    assert normalized["summary"]["correct"] == 1
    assert normalized["summary"]["total"] == 1


def test_model_memory_judge_normalizes_result_and_judge_verdict_alias():
    normalized = _normalize_model_judge_output(
        {
            "result": [
                {
                    "question_id": "q2",
                    "judge_verdict": "correct",
                    "confidence": 1,
                    "explanation": "same answer",
                }
            ]
        }
    )

    assert normalized["items"][0]["question_id"] == "q2"
    assert normalized["items"][0]["verdict"] == "correct"
    assert normalized["items"][0]["reason"] == "same answer"
    assert normalized["summary"]["correct"] == 1
