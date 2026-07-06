from src.search_think_contract import (
    SEARCH_OWNER,
    THINK_OWNER,
    boundary_contract,
    build_search_result,
    build_think_request,
    validate_think_result,
)
from src.evidence_atom_vocabulary import EVIDENCE_ATOM_VOCABULARY_CONTRACT


def test_search_think_boundary_makes_think_model_owned():
    contract = boundary_contract()

    assert contract["search_owner"] == SEARCH_OWNER
    assert contract["think_owner"] == THINK_OWNER
    assert contract["read_only"] is True
    assert contract["write_performed"] is False
    assert contract["model_call_performed"] is False
    assert "synthesize_answer" in contract["local_forbidden_after_think"]
    assert "validate_used_source_refs" in contract["local_allowed_after_think"]
    assert contract["evidence_atom_vocabulary_contract"] == EVIDENCE_ATOM_VOCABULARY_CONTRACT
    assert "source_span" in contract["shared_evidence_terms"]
    assert "answer_bearing" in contract["shared_evidence_terms"]
    assert "conflict_group" in contract["shared_evidence_terms"]
    assert contract["final_evidence_authority"] == "raw_source_refs"


def test_search_result_packages_evidence_without_answer_synthesis():
    search = build_search_result(
        query="发布完成了吗",
        scope={"canonical_window_id": "codex-current"},
        evidence_items=[
            {
                "source_id": "E1",
                "evidence_ref": "E1",
                "library_id": "lib-1",
                "matched_by": "bm25",
                "rank_reason": "local test receipt",
                "text": "本地测试通过",
                "source_refs": {"source_system": "codex", "source_path": "raw/session.jsonl"},
                "raw_expand_available": True,
            }
        ],
        missing_evidence=["remote_release_receipt_missing"],
    )
    request = build_think_request(search)

    assert search["owner"] == SEARCH_OWNER
    assert search["answer_synthesized"] is False
    assert search["model_call_performed"] is False
    assert search["source_refs"]
    assert search["library_ids"] == ["lib-1"]
    assert search["evidence_atom_vocabulary_contract"] == EVIDENCE_ATOM_VOCABULARY_CONTRACT
    assert "source_span" in search["shared_evidence_terms"]
    assert request["think_owner"] == THINK_OWNER
    assert request["local_may_synthesize_answer"] is False
    assert request["unknown_required"] is False
    assert request["gap"] == ["remote_release_receipt_missing"]
    assert request["evidence_atom_vocabulary_contract"] == EVIDENCE_ATOM_VOCABULARY_CONTRACT
    assert "answer_bearing" in request["shared_evidence_terms"]


def test_validate_think_result_accepts_evidence_bound_answer_with_seen_refs():
    search = build_search_result(
        query="发布完成了吗",
        evidence_items=[
            {
                "source_id": "E1",
                "evidence_ref": "E1",
                "text": "本地候选构建完成",
                "source_refs": {"source_system": "codex", "source_path": "raw/session.jsonl"},
            }
        ],
    )
    request = build_think_request(search)

    validation = validate_think_result(
        {
            "owner": THINK_OWNER,
            "answer_source": "evidence_bound_model_call",
            "answer": "只能确认本地候选，远端发布状态 UNKNOWN。",
            "used_source_refs": ["E1"],
        },
        think_request=request,
    )

    assert validation["ok"] is True
    assert validation["errors"] == []


def test_validate_think_result_accepts_seen_catalog_id_refs():
    search = build_search_result(
        query="这条目录卡能用吗",
        evidence_items=[
            {
                "source_id": "E1",
                "catalog_id": "CAT-ZHIYI-1",
                "text": "目录卡有 source ref 和 library id。",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "raw/session.jsonl",
                    "catalog_id": "CAT-ZHIYI-1",
                },
            }
        ],
    )
    request = build_think_request(search)

    validation = validate_think_result(
        {
            "owner": THINK_OWNER,
            "answer_source": "evidence_bound_model_call",
            "answer": "这条目录卡可用。",
            "used_source_refs": ["CAT-ZHIYI-1"],
        },
        think_request=request,
    )

    assert validation["ok"] is True
    assert validation["errors"] == []


def test_validate_think_result_rejects_unseen_catalog_id_refs():
    search = build_search_result(
        query="这条目录卡能用吗",
        evidence_items=[
            {
                "source_id": "E1",
                "text": "目录卡有 source ref 和 library id。",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "raw/session.jsonl",
                    "catalog_id": "CAT-ZHIYI-1",
                },
            }
        ],
    )
    request = build_think_request(search)

    validation = validate_think_result(
        {
            "owner": THINK_OWNER,
            "answer_source": "evidence_bound_model_call",
            "answer": "这条目录卡可用。",
            "used_source_refs": ["CAT-ZHIYI-MADE-UP"],
        },
        think_request=request,
    )

    assert validation["ok"] is False
    assert "used_source_refs_not_in_search_result" in validation["errors"]


def test_validate_think_result_does_not_accept_top_level_catalog_id_only():
    search = build_search_result(
        query="这条目录卡能用吗",
        evidence_items=[
            {
                "source_id": "E1",
                "catalog_id": "CAT-TOP-ONLY",
                "text": "目录卡有顶层 catalog id，但 source_refs 没有。",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "raw/session.jsonl",
                },
            }
        ],
    )
    request = build_think_request(search)

    validation = validate_think_result(
        {
            "owner": THINK_OWNER,
            "answer_source": "evidence_bound_model_call",
            "answer": "这条目录卡可用。",
            "used_source_refs": ["CAT-TOP-ONLY"],
        },
        think_request=request,
    )

    assert validation["ok"] is False
    assert "used_source_refs_not_in_search_result" in validation["errors"]


def test_validate_think_result_rejects_evidence_item_miswired_as_source_ref_catalog_id():
    search = build_search_result(
        query="这条目录卡能用吗",
        evidence_items=[
            {
                "source_id": "E1",
                "catalog_id": "CAT-TOP-MISWIRED",
                "text": "这是完整 evidence item，不是 source_refs 对象。",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "raw/session.jsonl",
                },
            }
        ],
    )
    request = build_think_request(search)
    request["source_refs"] = list(search["evidence_items"])

    validation = validate_think_result(
        {
            "owner": THINK_OWNER,
            "answer_source": "evidence_bound_model_call",
            "answer": "这条目录卡可用。",
            "used_source_refs": ["CAT-TOP-MISWIRED"],
        },
        think_request=request,
    )

    assert validation["ok"] is False
    assert "used_source_refs_not_in_search_result" in validation["errors"]


def test_validate_think_result_blocks_local_fallback_or_unseen_refs():
    search = build_search_result(query="发布完成了吗", evidence_items=[])
    request = build_think_request(search)

    validation = validate_think_result(
        {
            "owner": "local_memcore",
            "answer_source": "zhiyi_direct_natural_fallback_after_model_no_answer",
            "answer": "已经发布",
            "used_source_refs": ["made-up"],
            "local_draft_detected": True,
        },
        think_request=request,
    )

    assert validation["ok"] is False
    assert "think_answer_owner_must_be_evidence_bound_model" in validation["errors"]
    assert "answer_source_must_be_evidence_bound_model_call" in validation["errors"]
    assert "local_draft_or_fallback_cannot_be_think_answer" in validation["errors"]
    assert "unknown_required_but_model_answered" in validation["errors"]
