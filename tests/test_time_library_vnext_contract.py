import json
from pathlib import Path

from src.time_library_vnext_contract import (
    memory_contract_descriptor,
    validate_delivery_event_candidate,
    validate_evidence_packet_candidate,
    validate_memory_atom_candidate,
    validate_transition_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "src" / "tiandao" / "schemas"


def _source_refs():
    return [
        {
            "source_system": "r0_synthetic",
            "source_path": "tests/fixtures/time_library_r0_baseline_cases.json",
            "artifact_id": "case-1",
        }
    ]


def _verifier(state="pass"):
    return {"coverage": state, "preservation": state, "faithfulness": state}


def test_vnext_descriptor_keeps_dual_time_delivery_and_hermes_route_explicit():
    descriptor = memory_contract_descriptor()

    assert descriptor["status"] == "candidate_not_implemented"
    assert descriptor["read_only"] is True
    assert descriptor["write_performed"] is False
    assert descriptor["final_evidence_authority"] == "raw_source_refs"
    assert descriptor["memory_atom"]["dual_time"] == {
        "observed_time": ["observed_at", "valid_from", "valid_to"],
        "recorded_time": ["recorded_at"],
        "rule": "event_validity_and_system_knowledge_time_must_not_be_collapsed",
    }
    assert descriptor["delivery"]["morning_digest"] == {
        "delivery_audience": "user",
        "delivery_form": "digest",
    }
    assert descriptor["hermes_experience_route"]["stages"] == [
        "adoption_or_outcome",
        "experience_candidate",
        "transition_verifier",
        "review_or_activation",
    ]
    assert descriptor["hermes_experience_route"]["automatic_production_write_allowed"] is False
    assert descriptor["benefit_proof_map"]["memory_poisoning_defense"]["proof_layer"] == "not_proven"
    assert "treat_relay_voiceprint_as_poisoning_defense" in descriptor["forbidden_by_default"]


def test_memory_atom_requires_source_span_dual_time_taint_and_three_verifier_checks():
    atom = {
        "atom_id": "atom-1",
        "revision_id": "revision-1",
        "shelf": "zhiyi",
        "semantic_type": "preference",
        "state_role": "active",
        "content": "Synthetic preference.",
        "observed_at": "2026-07-13T00:00:00Z",
        "recorded_at": "2026-07-13T00:01:00Z",
        "valid_from": "2026-07-13T00:00:00Z",
        "valid_to": None,
        "taint": "trusted",
        "source_refs": _source_refs(),
        "source_span": {"chunk_id": "case-1"},
        "verifier": _verifier(),
    }

    assert validate_memory_atom_candidate(atom)["ok"] is True
    atom["source_refs"] = []
    result = validate_memory_atom_candidate(atom)
    assert result["ok"] is False
    assert "source_refs_required" in result["errors"]


def test_transition_activation_requires_authorization_and_all_verifiers_pass():
    event = {
        "transition_id": "transition-1",
        "atom_id": "atom-1",
        "from_revision_ids": ["revision-1"],
        "to_revision_id": "revision-2",
        "transition_kind": "activate",
        "observed_at": "2026-07-13T00:00:00Z",
        "recorded_at": "2026-07-13T00:01:00Z",
        "source_refs": _source_refs(),
        "verifier": _verifier("unknown"),
        "activation_allowed": True,
    }

    result = validate_transition_candidate(event)
    assert result["ok"] is False
    assert "activation_requires_all_verifier_checks_pass" in result["errors"]
    assert "activation_requires_authorization_ref" in result["errors"]

    event["verifier"] = _verifier()
    event["authorization_ref"] = "owner-approval-1"
    assert validate_transition_candidate(event)["ok"] is True


def test_delivery_separates_audience_form_and_proof_stage():
    morning_digest = {
        "delivery_event_id": "delivery-1",
        "retrieval_id": "retrieval-1",
        "platform": "time-library-console",
        "delivery_audience": "user",
        "delivery_form": "digest",
        "delivery_stage": "selected",
        "observed_at": "2026-07-13T00:00:00Z",
        "recorded_at": "2026-07-13T00:01:00Z",
    }
    assert validate_delivery_event_candidate(morning_digest)["ok"] is True

    morning_digest["delivery_stage"] = "used"
    result = validate_delivery_event_candidate(morning_digest)
    assert result["ok"] is False
    assert "delivered_or_later_requires_delivery_observation" in result["errors"]
    assert "source_refs_required" in result["errors"]

    morning_digest["delivery_stage"] = "unknown"
    result = validate_delivery_event_candidate(morning_digest)
    assert "unknown_stage_requires_reason" in result["errors"]


def test_evidence_packet_keeps_unknown_and_source_authority_fields_required():
    packet = {
        "packet_id": "packet-1",
        "query_intent": "gap",
        "requested_time_view": "current",
        "answer_bearing": [],
        "supporting_context": [],
        "state_transitions": [],
        "conflicts": [],
        "open_gaps": ["state unresolved"],
        "unknown_required": True,
        "source_refs": _source_refs(),
        "raw_expand_available": True,
        "retrieval_trace": {"mode": "synthetic"},
    }
    assert validate_evidence_packet_candidate(packet)["ok"] is True

    packet.pop("unknown_required")
    result = validate_evidence_packet_candidate(packet)
    assert result["ok"] is False
    assert "missing_required_field:unknown_required" in result["errors"]


def test_json_schemas_parse_and_encode_runtime_guard_conditions():
    schemas = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(SCHEMA_ROOT.glob("time-library-*-vnext.schema.json"))
    }

    assert len(schemas) == 4
    atom = schemas["time-library-memory-atom-vnext.schema.json"]
    transition = schemas["time-library-memory-transition-vnext.schema.json"]
    delivery = schemas["time-library-delivery-event-vnext.schema.json"]
    evidence = schemas["time-library-evidence-packet-vnext.schema.json"]
    assert {"observed_at", "recorded_at", "valid_from", "valid_to"}.issubset(atom["required"])
    assert "activation_allowed" in transition["required"]
    assert transition["allOf"]
    assert "recorded_at" in delivery["required"]
    assert len(delivery["allOf"]) == 4
    assert "unknown_required" in evidence["required"]
