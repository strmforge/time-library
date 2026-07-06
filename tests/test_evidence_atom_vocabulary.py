from src.evidence_atom_vocabulary import (
    EVIDENCE_ATOM_VOCABULARY_CONTRACT,
    validate_memory_atom_shape,
    vocabulary_contract,
)


def test_evidence_atom_vocabulary_is_read_only_and_shared():
    payload = vocabulary_contract()

    assert payload["contract"] == EVIDENCE_ATOM_VOCABULARY_CONTRACT
    assert payload["read_only"] is True
    assert payload["write_performed"] is False
    assert payload["model_call_performed"] is False
    assert payload["not_a_memory_layer"] is True
    assert payload["final_evidence_authority"] == "raw_source_refs"
    for field in (
        "source_refs",
        "source_span",
        "semantic_type",
        "answer_bearing",
        "conflict_group",
        "errata_refs",
        "raw_expand_available",
    ):
        assert field in payload["shared_terms"]
    assert payload["usage"]["phase1"] == "search_think_packets_and_delivery_receipts"


def test_memory_atom_shape_requires_source_backed_fields():
    result = validate_memory_atom_shape(
        {
            "atom_id": "atom-1",
            "library_id": "lib-1",
            "shelf": "zhiyi",
            "semantic_type": "task_boundary",
            "content": "think answer must be model-owned",
            "source_refs": [{"source_system": "codex", "source_path": "raw/session.jsonl"}],
            "source_span": {"line_start": 10, "line_end": 12},
            "confidence": 0.9,
            "answer_bearing": "answer_bearing",
        }
    )

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["read_only"] is True
    assert result["write_performed"] is False


def test_memory_atom_rejects_unbacked_or_invalid_shape():
    result = validate_memory_atom_shape(
        {
            "atom_id": "atom-2",
            "shelf": "sixth_layer",
            "semantic_type": "claim",
            "source_refs": [],
            "confidence": 1.2,
            "answer_bearing": "surely_true",
            "source_span": {"paragraph": 3},
        }
    )

    assert result["ok"] is False
    assert "invalid_shelf" in result["errors"]
    assert "source_refs_required" in result["errors"]
    assert "confidence_must_be_0_to_1" in result["errors"]
    assert "invalid_answer_bearing" in result["errors"]
    assert "unknown_source_span_fields=paragraph" in result["errors"]
