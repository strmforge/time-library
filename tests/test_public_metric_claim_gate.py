from src.public_metric_claim_gate import (
    PUBLIC_METRIC_CLAIM_GATE_CONTRACT,
    gate_public_metric_claim,
    scan_public_metric_claim_text,
)


def test_public_metric_claim_gate_accepts_retrieval_recall_with_source_envelope():
    result = gate_public_metric_claim(
        {
            "benchmark": "LongMemEval-S",
            "split": "s",
            "metric": "recall_any@5",
            "score": 95.2,
            "measured_by": "external_project_report",
            "reproducible_command": "python eval.py --metric recall_any@5",
            "dataset_source": "LongMemEval cleaned S split",
            "evaluation_scope": "retrieval",
            "public_wording": "LongMemEval-S retrieval recall_any@5 = 95.2%; retrieval-only, not a generated-answer metric.",
            "claim_source_url": "https://example.test/report",
            "measured_at": "2026-06-21",
            "result_artifact": "runs/longmemeval-s-recall-any-5.json",
            "independent_reproduction": True,
            "judge_or_evaluator": "deterministic retrieval scorer",
            "prompt_or_config": "top_k=5",
            "token_budget": "not_qa_generation",
        }
    )

    assert result["contract"] == PUBLIC_METRIC_CLAIM_GATE_CONTRACT
    assert result["ok"] is True
    assert result["is_publication_ready"] is True
    assert result["metric_boundary"] == "retrieval_recall_not_qa_accuracy"
    assert result["read_only"] is True
    assert result["model_call_performed"] is False
    assert result["publication_label"] == "retrieval_recall_with_source_gate"
    assert "not a generated-answer metric" in result["safe_public_wording"]
    assert result["public_wording_scan"]["ok"] is True


def test_public_metric_claim_gate_blocks_retrieval_metric_as_qa_accuracy():
    result = gate_public_metric_claim(
        {
            "benchmark": "LongMemEval-S",
            "split": "s",
            "metric": "recall_any@5",
            "score": 95.2,
            "measured_by": "self",
            "reproducible_command": "python eval.py",
            "dataset_source": "LongMemEval cleaned S split",
            "evaluation_scope": "end_to_end_qa_accuracy",
            "public_wording": "LongMemEval-S 95.2% QA accuracy, 三大榜单第一。",
            "claim_source_url": "https://example.test/report",
            "measured_at": "2026-06-21",
            "result_artifact": "runs/longmemeval-s.json",
            "self_eval": True,
        }
    )

    assert result["ok"] is False
    assert "retrieval_recall_must_not_be_labeled_qa_accuracy" in result["errors"]
    assert "retrieval_recall_public_wording_must_not_claim_qa_or_answer_accuracy" in result["errors"]
    assert "public_metric_wording_must_not_claim_sota_or_leaderboard_first" in result["errors"]
    assert "self_eval_claim_requires_independent_reproduction_before_public_homepage" in result["errors"]
    assert "internal_or_self_measured_public_claim_requires_independent_reproduction" in result["errors"]
    assert result["is_publication_ready"] is False
    assert result["publication_label"] == "blocked_until_source_gate_passes"


def test_public_metric_claim_gate_blocks_end_to_end_accuracy_scope_without_qa_word():
    result = gate_public_metric_claim(
        {
            "benchmark": "LongMemEval-S",
            "split": "s",
            "metric": "recall_any@5",
            "score": 95.2,
            "measured_by": "external_project_report",
            "reproducible_command": "python eval.py --metric recall_any@5",
            "dataset_source": "LongMemEval cleaned S split",
            "evaluation_scope": "end_to_end_accuracy",
            "public_wording": "LongMemEval-S retrieval recall_any@5 = 95.2%; retrieval-only, not a generated-answer metric.",
            "claim_source_url": "https://example.test/report",
            "measured_at": "2026-06-21",
            "result_artifact": "runs/longmemeval-s-recall-any-5.json",
            "independent_reproduction": True,
        }
    )

    assert result["ok"] is False
    assert "retrieval_recall_must_not_be_labeled_qa_accuracy" in result["errors"]


def test_public_metric_claim_gate_requires_public_source_fields():
    result = gate_public_metric_claim({"benchmark": "LongMemEval-S", "metric": "recall_any@5"})

    assert result["ok"] is False
    assert "missing_required_field:measured_by" in result["errors"]
    assert "missing_required_field:reproducible_command" in result["errors"]
    assert "missing_required_field:evaluation_scope" in result["errors"]
    assert "missing_required_field:public_wording" in result["errors"]
    assert "missing_provenance_field_one_of:claim_source_url|source_refs" in result["errors"]
    assert "missing_provenance_field_one_of:measured_at|source_date" in result["errors"]
    assert "missing_provenance_field_one_of:reproduction_artifact|result_artifact" in result["errors"]


def test_public_metric_claim_text_scan_allows_metric_specific_retrieval_wording():
    result = scan_public_metric_claim_text(
        "LongMemEval-S retrieval recall_any@5 = 95.2%; not answer accuracy.",
        {"benchmark": "LongMemEval-S", "metric": "recall_any@5"},
    )

    assert result["ok"] is False
    assert "retrieval_recall_public_wording_must_not_claim_qa_or_answer_accuracy" in result["errors"]


def test_public_metric_claim_text_scan_accepts_retrieval_boundary_without_accuracy_word():
    result = scan_public_metric_claim_text(
        "LongMemEval-S retrieval recall_any@5 = 95.2%; retrieval-only, not a generated-answer metric.",
        {"benchmark": "LongMemEval-S", "metric": "recall_any@5"},
    )

    assert result["ok"] is True
    assert result["errors"] == []


def test_public_metric_claim_gate_blocks_95_2_retrieval_rate_without_metric_name():
    result = gate_public_metric_claim(
        {
            "benchmark": "LongMemEval-S",
            "split": "s",
            "metric": "recall_any@5",
            "score": 95.2,
            "measured_by": "external_project_report",
            "reproducible_command": "python eval.py --metric recall_any@5",
            "dataset_source": "LongMemEval cleaned S split",
            "evaluation_scope": "retrieval",
            "public_wording": "LongMemEval-S 95.2% 检索率。",
            "source_refs": [{"source_path": "notes/external.md", "byte_offsets": [10, 40]}],
            "source_date": "2026-06-21",
            "reproduction_artifact": "runs/longmemeval-s-recall-any-5.json",
            "independent_reproduction": True,
        }
    )

    assert result["ok"] is False
    assert "retrieval_rate_wording_must_name_recall_any_metric" in result["errors"]
