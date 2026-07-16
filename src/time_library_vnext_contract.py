"""Read-only candidate contracts for the Time Library vNext memory path.

R0 defines shapes and proof requirements only. It does not read or write a
memory store, call a model, deliver context, or activate experience candidates.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


MEMORY_CONTRACT = "time_library.memory_contract_candidate.v2026.7.13"
MEMORY_ATOM_CONTRACT = "time_library.memory_atom_candidate.v2026.7.13"
TRANSITION_CONTRACT = "time_library.memory_transition_candidate.v2026.7.13"
EVIDENCE_PACKET_CONTRACT = "time_library.evidence_packet_candidate.v2026.7.13"
DELIVERY_EVENT_CONTRACT = "time_library.delivery_event_candidate.v2026.7.13"

SEMANTIC_TYPES = ("claim", "event", "procedure", "preference")
STATE_ROLES = (
    "candidate",
    "active",
    "superseded",
    "transition",
    "conflicting",
    "unknown",
    "rejected",
)
TAINT_STATES = ("trusted", "untrusted_content", "instruction_like", "unknown")
VERIFIER_STATES = ("pass", "fail", "unknown", "not_measured")
DELIVERY_AUDIENCES = ("agent", "user")
DELIVERY_FORMS = ("silent", "catalog", "context", "digest", "direct_answer")
DELIVERY_STAGES = ("stored", "retrieved", "selected", "delivered", "used", "helped", "unknown")
TRANSITION_KINDS = ("activate", "supersede", "conflict", "reject", "mark_unknown")
SHELVES = ("raw", "zhiyi", "xingce", "toolbook", "errata")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _items(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [] if value in (None, "") else [value]


def _missing_fields(value: Dict[str, Any], required: Iterable[str]) -> List[str]:
    missing = []
    for field in required:
        if field not in value or value.get(field) in (None, "", []):
            missing.append(field)
    return missing


def _validate_source_refs(value: Any) -> List[str]:
    refs = _items(value)
    if not refs:
        return ["source_refs_required"]
    errors = []
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict):
            errors.append("source_ref_%d_must_be_object" % index)
            continue
        if not _text(ref.get("source_system")):
            errors.append("source_ref_%d_source_system_required" % index)
        if not any(
            _text(ref.get(field))
            for field in ("source_path", "ref_path", "artifact_id", "library_id", "evidence_ref")
        ):
            errors.append("source_ref_%d_locator_required" % index)
    return errors


def _validate_source_span(value: Any) -> List[str]:
    if not isinstance(value, dict):
        return ["source_span_required"]
    if not any(
        value.get(field) not in (None, "", [])
        for field in ("byte_start", "byte_end", "line_start", "line_end", "chunk_id", "text")
    ):
        return ["source_span_coordinate_required"]
    return []


def _validate_verifier(value: Any) -> List[str]:
    if not isinstance(value, dict):
        return ["verifier_required"]
    errors = []
    for check in ("coverage", "preservation", "faithfulness"):
        state = _text(value.get(check))
        if state not in VERIFIER_STATES:
            errors.append("invalid_verifier_%s" % check)
    return errors


def _result(contract: str, errors: List[str]) -> Dict[str, Any]:
    return {
        "ok": not errors,
        "contract": contract,
        "errors": errors,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "proof_layer": "candidate_schema_only",
    }


def validate_memory_atom_candidate(atom: Dict[str, Any]) -> Dict[str, Any]:
    errors = []
    if not isinstance(atom, dict):
        return _result(MEMORY_ATOM_CONTRACT, ["memory_atom_must_be_object"])
    errors.extend(
        "missing_required_field:%s" % field
        for field in _missing_fields(
            atom,
            (
                "atom_id",
                "revision_id",
                "shelf",
                "semantic_type",
                "state_role",
                "content",
                "observed_at",
                "recorded_at",
                "valid_from",
                "taint",
                "source_refs",
                "source_span",
                "verifier",
            ),
        )
    )
    if "valid_to" not in atom:
        errors.append("missing_required_field:valid_to")
    if atom.get("shelf") not in SHELVES:
        errors.append("invalid_shelf")
    if atom.get("semantic_type") not in SEMANTIC_TYPES:
        errors.append("invalid_semantic_type")
    if atom.get("state_role") not in STATE_ROLES:
        errors.append("invalid_state_role")
    if atom.get("taint") not in TAINT_STATES:
        errors.append("invalid_taint")
    errors.extend(_validate_source_refs(atom.get("source_refs")))
    errors.extend(_validate_source_span(atom.get("source_span")))
    errors.extend(_validate_verifier(atom.get("verifier")))
    return _result(MEMORY_ATOM_CONTRACT, list(dict.fromkeys(errors)))


def validate_transition_candidate(event: Dict[str, Any]) -> Dict[str, Any]:
    errors = []
    if not isinstance(event, dict):
        return _result(TRANSITION_CONTRACT, ["transition_must_be_object"])
    errors.extend(
        "missing_required_field:%s" % field
        for field in _missing_fields(
            event,
            (
                "transition_id",
                "atom_id",
                "to_revision_id",
                "transition_kind",
                "observed_at",
                "recorded_at",
                "source_refs",
                "verifier",
                "activation_allowed",
            ),
        )
    )
    if "from_revision_ids" not in event:
        errors.append("missing_required_field:from_revision_ids")
    if event.get("transition_kind") not in TRANSITION_KINDS:
        errors.append("invalid_transition_kind")
    errors.extend(_validate_source_refs(event.get("source_refs")))
    errors.extend(_validate_verifier(event.get("verifier")))
    if bool(event.get("activation_allowed")):
        verifier = event.get("verifier") if isinstance(event.get("verifier"), dict) else {}
        if any(verifier.get(check) != "pass" for check in ("coverage", "preservation", "faithfulness")):
            errors.append("activation_requires_all_verifier_checks_pass")
        if not _text(event.get("authorization_ref")):
            errors.append("activation_requires_authorization_ref")
    return _result(TRANSITION_CONTRACT, list(dict.fromkeys(errors)))


def validate_delivery_event_candidate(event: Dict[str, Any]) -> Dict[str, Any]:
    errors = []
    if not isinstance(event, dict):
        return _result(DELIVERY_EVENT_CONTRACT, ["delivery_event_must_be_object"])
    errors.extend(
        "missing_required_field:%s" % field
        for field in _missing_fields(
            event,
            (
                "delivery_event_id",
                "retrieval_id",
                "platform",
                "delivery_audience",
                "delivery_form",
                "delivery_stage",
                "observed_at",
                "recorded_at",
            ),
        )
    )
    if event.get("delivery_audience") not in DELIVERY_AUDIENCES:
        errors.append("invalid_delivery_audience")
    if event.get("delivery_form") not in DELIVERY_FORMS:
        errors.append("invalid_delivery_form")
    if event.get("delivery_stage") not in DELIVERY_STAGES:
        errors.append("invalid_delivery_stage")
    stage = event.get("delivery_stage")
    if stage in ("delivered", "used", "helped") and not isinstance(event.get("delivery_observation"), dict):
        errors.append("delivered_or_later_requires_delivery_observation")
    if stage in ("used", "helped"):
        errors.extend(_validate_source_refs(event.get("used_source_refs")))
    if stage == "helped" and not isinstance(event.get("help_evidence"), dict):
        errors.append("helped_requires_help_evidence")
    if stage == "unknown" and not _text(event.get("unknown_reason")):
        errors.append("unknown_stage_requires_reason")
    return _result(DELIVERY_EVENT_CONTRACT, list(dict.fromkeys(errors)))


def validate_evidence_packet_candidate(packet: Dict[str, Any]) -> Dict[str, Any]:
    errors = []
    if not isinstance(packet, dict):
        return _result(EVIDENCE_PACKET_CONTRACT, ["evidence_packet_must_be_object"])
    errors.extend(
        "missing_required_field:%s" % field
        for field in _missing_fields(
            packet,
            (
                "packet_id",
                "query_intent",
                "requested_time_view",
                "unknown_required",
                "source_refs",
                "raw_expand_available",
                "retrieval_trace",
            ),
        )
    )
    for field in ("answer_bearing", "supporting_context", "state_transitions", "conflicts", "open_gaps"):
        if field not in packet or not isinstance(packet.get(field), list):
            errors.append("%s_must_be_array" % field)
    if packet.get("answer_bearing"):
        errors.extend(_validate_source_refs(packet.get("source_refs")))
    if packet.get("open_gaps") and not bool(packet.get("unknown_required")):
        errors.append("open_gaps_require_unknown_boundary")
    return _result(EVIDENCE_PACKET_CONTRACT, list(dict.fromkeys(errors)))


def memory_contract_descriptor() -> Dict[str, Any]:
    return {
        "ok": True,
        "contract": MEMORY_CONTRACT,
        "status": "candidate_not_implemented",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "final_evidence_authority": "raw_source_refs",
        "not_a_sixth_memory_layer": True,
        "source_contracts": [
            "evidence_atom_vocabulary.v2026.6.21",
            "memory_delivery_receipt.v2026.6.21",
            "Zhixing State Ledger / Temporal Index MVP",
        ],
        "memory_atom": {
            "contract": MEMORY_ATOM_CONTRACT,
            "semantic_types": list(SEMANTIC_TYPES),
            "state_roles": list(STATE_ROLES),
            "taint_states": list(TAINT_STATES),
            "dual_time": {
                "observed_time": ["observed_at", "valid_from", "valid_to"],
                "recorded_time": ["recorded_at"],
                "rule": "event_validity_and_system_knowledge_time_must_not_be_collapsed",
            },
            "source_fields_required": ["source_refs", "source_span"],
            "verifier_checks": ["coverage", "preservation", "faithfulness"],
        },
        "delivery": {
            "contract": DELIVERY_EVENT_CONTRACT,
            "audiences": list(DELIVERY_AUDIENCES),
            "forms": list(DELIVERY_FORMS),
            "two_dimensional_policy": "delivery_audience_x_delivery_form",
            "morning_digest": {"delivery_audience": "user", "delivery_form": "digest"},
            "stages": list(DELIVERY_STAGES),
            "stage_evidence": {
                "stored": "durable_record_and_source_ref",
                "retrieved": "query_trace_hit",
                "selected": "intervention_policy_decision",
                "delivered": "observed_platform_model_or_user_delivery",
                "used": "used_source_refs_or_platform_adoption_trace_else_unknown",
                "helped": "task_outcome_user_feedback_or_controlled_ab_else_unknown",
            },
        },
        "hermes_experience_route": {
            "stages": [
                "adoption_or_outcome",
                "experience_candidate",
                "transition_verifier",
                "review_or_activation",
            ],
            "direct_outcome_to_production_experience_allowed": False,
            "automatic_production_write_allowed": False,
            "activation_requires": [
                "coverage_pass",
                "preservation_pass",
                "faithfulness_pass",
                "authorization_ref",
            ],
        },
        "benefit_proof_map": {
            "current_state_not_mixed": {"phase": "R2_R3", "proof_layer": "unimplemented", "unknown": True},
            "historical_as_of": {"phase": "R2_R3", "proof_layer": "unimplemented", "unknown": True},
            "model_delivery": {"phase": "R1_R5", "proof_layer": "latest_audit_0_of_7", "unknown": True},
            "selective_intervention": {"phase": "R1", "proof_layer": "unimplemented", "unknown": True},
            "conflict_preservation": {"phase": "R2", "proof_layer": "dry_run_primitive_only", "unknown": True},
            "experience_verification": {"phase": "R2_R5", "proof_layer": "partial_existing_activation_gate", "unknown": True},
            "raw_safety": {"phase": "existing_plus_all_phases", "proof_layer": "existing_runtime_and_tests", "unknown": False},
            "memory_poisoning_defense": {"phase": "R0_design_then_R2_R3", "proof_layer": "not_proven", "unknown": True},
            "delivery_truthfulness": {"phase": "R1_R5", "proof_layer": "diagnostic_contracts_exist", "unknown": True},
            "module_decomposition": {"phase": "R6", "proof_layer": "unimplemented", "unknown": True},
        },
        "forbidden_by_default": [
            "mutate_or_replace_raw",
            "collapse_conflict_in_storage",
            "claim_used_without_observation",
            "claim_helped_from_use_alone",
            "auto_activate_experience_from_outcome",
            "treat_relay_voiceprint_as_poisoning_defense",
            "create_sixth_memory_layer",
        ],
    }


__all__ = [
    "DELIVERY_AUDIENCES",
    "DELIVERY_EVENT_CONTRACT",
    "DELIVERY_FORMS",
    "DELIVERY_STAGES",
    "EVIDENCE_PACKET_CONTRACT",
    "MEMORY_ATOM_CONTRACT",
    "MEMORY_CONTRACT",
    "SEMANTIC_TYPES",
    "STATE_ROLES",
    "TAINT_STATES",
    "TRANSITION_CONTRACT",
    "VERIFIER_STATES",
    "memory_contract_descriptor",
    "validate_delivery_event_candidate",
    "validate_evidence_packet_candidate",
    "validate_memory_atom_candidate",
    "validate_transition_candidate",
]
