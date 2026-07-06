import json

from src.search_think_contract import SEARCH_OWNER, THINK_OWNER
from src.search_think_dry_run import SEARCH_THINK_DRY_RUN_CONTRACT, dry_run_contract, run_search_think_dry_run


def test_dry_run_contract_keeps_local_search_and_model_owned_think():
    contract = dry_run_contract()

    assert contract["contract"] == SEARCH_THINK_DRY_RUN_CONTRACT
    assert contract["read_only"] is True
    assert contract["write_performed"] is False
    assert contract["model_call_performed"] is False
    assert contract["search_owner"] == SEARCH_OWNER
    assert contract["think_owner"] == THINK_OWNER
    assert contract["local_answer_synthesis_allowed"] is False
    assert "synthesize_answer" in contract["local_forbidden_after_think"]
    assert contract["final_evidence_authority"] == "raw_source_refs"


def test_search_think_dry_run_accepts_fake_model_answer_and_builds_receipt():
    evidence = [
        {
            "source_id": "E1",
            "evidence_ref": "E1",
            "library_id": "lib-1",
            "text": "发布门禁本地测试通过，但没有远端 release 回执。",
            "source_refs": {"source_system": "codex", "source_path": "raw/session.jsonl"},
            "raw_expand_available": True,
        }
    ]

    def client(messages, config):
        payload = json.loads(messages[1]["content"])
        assert payload["question"] == "发布完成了吗"
        assert payload["question_context"]["local_may_synthesize_answer"] is False
        return {
            "content": json.dumps(
                {
                    "answer": "只能确认本地测试通过；远端发布状态 UNKNOWN。",
                    "verdict": "answered",
                    "confidence": 0.82,
                    "supporting_refs": ["E1"],
                    "unknown_reason": "remote_release_receipt_missing",
                }
            )
        }

    result = run_search_think_dry_run(
        query="发布完成了吗",
        scope={"canonical_window_id": "codex-current"},
        evidence_items=evidence,
        missing_evidence=["remote_release_receipt_missing"],
        execute=True,
        client=client,
        model_config={"provider": "test", "model": "fake", "base_url": "", "api_key_env": ""},
    )

    assert result["ok"] is True
    assert result["search_owner"] == SEARCH_OWNER
    assert result["think_owner"] == THINK_OWNER
    assert result["model_call_performed"] is True
    assert result["local_answer_synthesis_performed"] is False
    assert result["answer_synthesized_by_local"] is False
    assert result["think_result"]["owner"] == THINK_OWNER
    assert result["think_result"]["answer_source"] == "evidence_bound_model_call"
    assert result["think_result"]["used_source_refs"] == ["E1"]
    assert result["think_validation"]["ok"] is True
    assert result["delivery_receipt"]["used_records_count"] == 1
    assert result["delivery_receipt"]["raw_expand_available"] is True
    assert result["delivery_receipt"]["unknown_boundary"] is True
    assert result["delivery_receipt"]["answer_owner"] == THINK_OWNER
    assert result["delivery_receipt_view"]["status"] == "unknown"
    assert result["delivery_receipt_view"]["headline_code"] == "unknown_boundary_visible"
    assert result["delivery_receipt_view"]["actions"]["expand_raw"]["available"] is True
    assert result["delivery_receipt_view"]["projection_only"] is True


def test_search_think_no_evidence_returns_unknown_without_model_call():
    result = run_search_think_dry_run(
        query="远端发布完成了吗",
        evidence_items=[],
        execute=True,
        client=lambda *_: (_ for _ in ()).throw(AssertionError("should not call model without evidence")),
    )

    assert result["ok"] is True
    assert result["model_call_performed"] is False
    assert result["search_result"]["missing_evidence"] == ["no_evidence"]
    assert result["think_result"]["answer"] == "UNKNOWN"
    assert result["think_result"]["unknown"] is True
    assert result["think_result"]["unknown_reason"] == "no_evidence"
    assert result["think_validation"]["ok"] is True
    assert result["delivery_receipt"]["unknown_boundary"] is True
    assert result["delivery_receipt"]["recalled_records_count"] == 0
    assert result["delivery_receipt_view"]["status"] == "unknown"
    assert result["delivery_receipt_view"]["counts"]["used_records"] == 0


def test_search_think_default_dry_run_does_not_call_model_and_preserves_gap():
    evidence = [{"source_id": "E1", "evidence_ref": "E1", "text": "本地候选构建完成。"}]
    result = run_search_think_dry_run(
        query="发布完成了吗",
        evidence_items=evidence,
        missing_evidence=["remote_release_receipt_missing"],
    )

    assert result["ok"] is True
    assert result["model_call_performed"] is False
    assert result["evidence_bound_model_result"]["unknown_reason"] == "model_call_not_executed"
    assert result["think_result"]["answer"] == "UNKNOWN"
    assert result["think_result"]["gap"] == ["remote_release_receipt_missing"]
    assert result["delivery_receipt"]["gaps"] == ["remote_release_receipt_missing"]
    assert result["delivery_receipt"]["unknown_boundary"] is True
    assert result["delivery_receipt_view"]["gaps"] == ["remote_release_receipt_missing"]


def test_search_think_hallucinated_model_ref_is_rejected_to_unknown():
    evidence = [{"source_id": "E1", "evidence_ref": "E1", "text": "用户偏好简洁回答。"}]

    result = run_search_think_dry_run(
        query="用户偏好什么回答风格",
        evidence_items=evidence,
        execute=True,
        client=lambda *_: {
            "content": json.dumps(
                {
                    "answer": "用户偏好冗长回答。",
                    "verdict": "answered",
                    "confidence": 0.9,
                    "supporting_refs": ["E9"],
                }
            )
        },
    )

    assert result["ok"] is True
    assert result["model_call_performed"] is True
    assert result["evidence_bound_model_result"]["validation_error"] == "supporting_refs_not_in_evidence"
    assert result["think_result"]["answer"] == "UNKNOWN"
    assert result["think_result"]["used_source_refs"] == []
    assert result["think_result"]["validation_error"] == "supporting_refs_not_in_evidence"
    assert result["think_validation"]["ok"] is True
    assert result["delivery_receipt"]["unknown_boundary"] is True


def test_local_fallback_answer_cannot_become_think_answer():
    result = run_search_think_dry_run(
        query="发布完成了吗",
        evidence_items=[],
        missing_evidence=["release_receipt_missing"],
    )

    assert result["think_result"]["answer"] == "UNKNOWN"
    assert result["no_local_fallback_answer"] is True
    assert result["local_answer_synthesis_allowed"] is False
    assert result["local_answer_synthesis_performed"] is False
    assert "rewrite_answer" in result["local_forbidden_after_think"]
