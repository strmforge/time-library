from src.delivery_receipt import (
    DELIVERY_RECEIPT_CONTRACT,
    DELIVERY_RECEIPT_VIEW_CONTRACT,
    build_delivery_receipt,
    build_delivery_receipt_view_model,
)
from src.search_think_contract import THINK_OWNER, build_search_result


def test_delivery_receipt_is_user_visible_projection_not_delivery_mechanism():
    search = build_search_result(
        query="发布完成了吗",
        scope={"canonical_window_id": "codex-current"},
        evidence_items=[
            {
                "source_id": "E1",
                "evidence_ref": "E1",
                "library_id": "lib-1",
                "source_refs": {"source_system": "codex", "source_path": "raw/session.jsonl"},
                "raw_expand_available": True,
            }
        ],
        missing_evidence=["remote_release_receipt_missing"],
    )

    receipt = build_delivery_receipt(
        answer_id="ans-1",
        search_result=search,
        think_result={
            "owner": THINK_OWNER,
            "answer": "本地候选完成，远端发布 UNKNOWN。",
            "used_source_refs": ["E1"],
            "gap": ["remote_release_receipt_missing"],
        },
    )

    assert receipt["contract"] == DELIVERY_RECEIPT_CONTRACT
    assert receipt["read_only"] is True
    assert receipt["write_performed"] is False
    assert receipt["model_call_performed"] is False
    assert receipt["not_a_delivery_mechanism"] is True
    assert receipt["recalled_records_count"] == 1
    assert receipt["used_records_count"] == 1
    assert receipt["library_ids"] == ["lib-1"]
    assert receipt["used_library_ids"] == ["lib-1"]
    assert receipt["raw_expand_available"] is True
    assert receipt["unknown_boundary"] is True
    assert receipt["answer_owner"] == THINK_OWNER
    assert receipt["final_evidence_authority"] == "raw_source_refs"


def test_delivery_receipt_view_model_frontloads_unknown_gap_and_raw_expand():
    receipt = {
        "answer_id": "ans-1",
        "recalled_records_count": 2,
        "used_records_count": 1,
        "source_refs": [
            {"source_system": "codex", "source_path": "raw/session.jsonl", "line": 7},
            {"source_system": "codex", "source_path": "raw/session.jsonl", "line": 9},
        ],
        "used_source_refs": ["E1"],
        "library_ids": ["lib-1"],
        "gaps": ["remote_release_receipt_missing"],
        "conflicts": [],
        "unknown_boundary": True,
        "raw_expand_available": True,
        "answer_owner": THINK_OWNER,
        "scope": {"canonical_window_id": "codex-current"},
    }

    view = build_delivery_receipt_view_model(receipt)

    assert view["contract"] == DELIVERY_RECEIPT_VIEW_CONTRACT
    assert view["read_only"] is True
    assert view["write_performed"] is False
    assert view["platform_write_performed"] is False
    assert view["model_call_performed"] is False
    assert view["not_a_delivery_mechanism"] is True
    assert view["projection_only"] is True
    assert view["status"] == "unknown"
    assert view["headline_code"] == "unknown_boundary_visible"
    assert view["counts"]["recalled_records"] == 2
    assert view["counts"]["used_records"] == 1
    assert view["visible_source_refs"][0]["source_system"] == "codex"
    assert view["gaps"] == ["remote_release_receipt_missing"]
    assert view["actions"]["expand_raw"]["available"] is True
    assert view["actions"]["expand_raw"]["write_performed"] is False
    assert view["answer_owner"] == THINK_OWNER
    assert view["final_evidence_authority"] == "raw_source_refs"
    assert view["used_library_ids"] == []


def test_delivery_receipt_accepts_explicit_used_library_ids():
    receipt = build_delivery_receipt(
        answer_id="ans-2",
        search_result={
            "evidence_items": [
                {"source_id": "E1", "evidence_ref": "E1", "library_id": "lib-1"},
                {"source_id": "E2", "evidence_ref": "E2", "library_id": "lib-2"},
            ],
            "library_ids": ["lib-1", "lib-2"],
        },
        think_result={
            "used_source_refs": ["E2"],
            "used_library_ids": ["lib-2"],
        },
    )

    assert receipt["library_ids"] == ["lib-1", "lib-2"]
    assert receipt["used_library_ids"] == ["lib-2"]


def test_delivery_receipt_view_preserves_structured_used_source_refs():
    receipt = {
        "answer_id": "ans-structured",
        "recalled_records_count": 1,
        "used_records_count": 1,
        "source_refs": [],
        "used_source_refs": [
            {
                "source_system": "codex",
                "source_path": "raw/session.jsonl",
                "library_id": "lib-1",
                "byte_offsets": {"start": 10, "end": 80},
            }
        ],
        "library_ids": ["lib-1"],
        "used_library_ids": ["lib-1"],
        "raw_expand_available": True,
    }

    view = build_delivery_receipt_view_model(receipt)

    assert view["visible_used_source_refs"] == [
        {
            "source_system": "codex",
            "source_path": "raw/session.jsonl",
            "library_id": "lib-1",
            "byte_offsets": {"start": 10, "end": 80},
        }
    ]
    assert view["used_source_refs"][0].startswith("{")
    assert view["actions"]["inspect_sources"]["available"] is True
