from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from src.time_library_delivery_spine import (
    DELIVERY_STAGES,
    OBSERVABILITY_CELLS,
    OBSERVABILITY_STATES,
    build_experience_candidate_route,
    build_platform_observability_matrix,
    decide_intervention,
    delivery_route_profile,
    validate_delivery_chain,
    validate_delivery_event,
    validate_delivery_transition,
)


BASE_TIME = datetime(2026, 7, 13, tzinfo=timezone.utc)


def _source_ref(token: str = "memory-1"):
    return {"source_system": "synthetic_host", "artifact_id": token}


def _time(index: int) -> str:
    return (BASE_TIME + timedelta(minutes=index)).isoformat().replace("+00:00", "Z")


def _event(
    stage: str,
    index: int,
    *,
    audience: str = "agent",
    form: str = "context",
    previous_event_id: str = "",
):
    event = {
        "delivery_event_id": "event-%d" % index,
        "retrieval_id": "retrieval-1",
        "platform": "codex",
        "delivery_audience": audience,
        "delivery_form": form,
        "delivery_stage": stage,
        "observed_at": _time(index),
        "recorded_at": _time(index),
        "evidence_ref": "evidence-%d" % index,
        "source_refs": [_source_ref()],
    }
    if previous_event_id:
        event["previous_event_id"] = previous_event_id
    if stage == "selected":
        event["selection_observation"] = {
            "decision": "silent" if form == "silent" else "emit",
            "policy_ref": "policy-1",
        }
    if stage in ("delivered", "used", "helped"):
        event["delivery_observation"] = (
            {
                "kind": "platform_model_request",
                "observed": True,
                "evidence_ref": "request-evidence-1",
                "request_id": "request-1",
                "source_refs": [_source_ref()],
                "evidence_authority": "host_self_report",
                "independent_model_delivery_proven": False,
                "platform_delivery_proof_kind": "host_attested_append_only_chain",
            }
            if audience == "agent"
            else {
                "kind": "user_visible_delivery",
                "observed": True,
                "evidence_ref": "user-delivery-evidence-1",
                "delivery_id": "delivery-1",
                "source_refs": [_source_ref()],
            }
        )
    if stage in ("used", "helped"):
        event["adoption_evidence"] = {
            "kind": "response_source_refs",
            "observed": True,
            "evidence_ref": "response-1",
            "evidence_authority": "host_self_report",
            "independent_model_delivery_proven": False,
            "platform_delivery_proof_kind": "host_attested_append_only_chain",
        }
        event["used_source_refs"] = [_source_ref()]
    if stage == "helped":
        event["help_evidence"] = {
            "kind": "task_outcome",
            "observed": True,
            "evidence_ref": "outcome-evidence-1",
            "outcome_id": "outcome-1",
        }
    return event


def _chain(*, audience: str = "agent", form: str = "context"):
    events = []
    previous = ""
    for index, stage in enumerate(DELIVERY_STAGES):
        event = _event(stage, index, audience=audience, form=form, previous_event_id=previous)
        events.append(event)
        previous = event["delivery_event_id"]
    return events


def test_six_stage_chain_is_ordered_append_only_and_input_is_unchanged():
    events = _chain()
    original = deepcopy(events)

    result = validate_delivery_chain(events)

    assert result["ok"] is True
    assert result["event_count"] == 6
    assert result["latest_proven_stage"] == "helped"
    assert result["immutable_append_only"] is True
    assert result["events_remain_orderable"] is True
    assert result["source_refs_required_not_replacement"] is True
    assert result["write_performed"] is False
    assert events == original


@pytest.mark.parametrize(
    ("previous_stage", "current_stage"),
    list(zip(DELIVERY_STAGES, DELIVERY_STAGES[1:])),
)
def test_each_adjacent_delivery_transition_is_legal(previous_stage, current_stage):
    previous_index = DELIVERY_STAGES.index(previous_stage)
    current_index = previous_index + 1
    previous = _event(previous_stage, previous_index)
    current = _event(current_stage, current_index, previous_event_id=previous["delivery_event_id"])

    assert validate_delivery_transition(previous, current)["ok"] is True


def test_delivery_chain_must_start_at_stored_without_a_previous_link():
    retrieved = _event("retrieved", 1)
    result = validate_delivery_transition(None, retrieved)
    assert result["ok"] is False
    assert "delivery_chain_must_start_at_stored" in result["errors"]

    stored = _event("stored", 0, previous_event_id="earlier-event")
    result = validate_delivery_transition(None, stored)
    assert result["ok"] is False
    assert "first_event_must_not_have_previous_event_id" in result["errors"]


@pytest.mark.parametrize(
    ("previous_stage", "current_stage"),
    [
        ("stored", "selected"),
        ("retrieved", "delivered"),
        ("selected", "used"),
        ("delivered", "helped"),
        ("helped", "stored"),
    ],
)
def test_delivery_transition_rejects_stage_jumps(previous_stage, current_stage):
    previous = _event(previous_stage, 0)
    current = _event(current_stage, 1, previous_event_id=previous["delivery_event_id"])

    result = validate_delivery_transition(previous, current)

    assert result["ok"] is False
    assert any("illegal_delivery_stage_transition" in error for error in result["errors"])


def test_unknown_gap_is_visible_and_can_only_resolve_the_same_next_stage():
    events = _chain()[:3]
    unknown = _event("unknown", 3, previous_event_id=events[-1]["delivery_event_id"])
    unknown.update({"unknown_for_stage": "delivered", "unknown_reason": "model_request_not_observable"})
    events.append(unknown)

    unresolved = validate_delivery_chain(events)
    assert unresolved["ok"] is True
    assert unresolved["latest_proven_stage"] == "selected"
    assert unresolved["unknown_targets"] == ["delivered"]

    delivered = _event("delivered", 4, previous_event_id=unknown["delivery_event_id"])
    assert validate_delivery_chain(events + [delivered])["ok"] is True

    used = _event("used", 4, previous_event_id=unknown["delivery_event_id"])
    rejected = validate_delivery_chain(events + [used])
    assert rejected["ok"] is False
    assert any("unknown_transition_must_resolve_same_target_stage" in error for error in rejected["errors"])


def test_invalid_suffix_cannot_overstate_latest_proven_stage():
    events = [_event("stored", 0), _event("helped", 1, previous_event_id="event-0")]

    result = validate_delivery_chain(events)

    assert result["ok"] is False
    assert result["validated_prefix_event_count"] == 1
    assert result["latest_proven_stage"] == "stored"


def test_chain_rejects_duplicate_ids_broken_links_and_time_regression():
    events = _chain()[:2]
    events[1]["delivery_event_id"] = events[0]["delivery_event_id"]
    events[1]["previous_event_id"] = "not-the-previous-event"
    events[1]["observed_at"] = "2026-07-12T23:59:00Z"
    events[1]["recorded_at"] = "2026-07-12T23:59:00Z"

    result = validate_delivery_chain(events)

    assert result["ok"] is False
    assert any("duplicate_delivery_event_id" in error for error in result["errors"])
    assert any("previous_event_id_must_link_immediate_predecessor" in error for error in result["errors"])
    assert any("observed_at_must_be_monotonic" in error for error in result["errors"])
    assert any("recorded_at_must_be_monotonic" in error for error in result["errors"])


@pytest.mark.parametrize("events", [[None], ["not-an-event"]])
def test_chain_reports_malformed_events_without_raising(events):
    result = validate_delivery_chain(events)

    assert result["ok"] is False
    assert any("delivery_event_must_be_object" in error for error in result["errors"])


def test_transition_reports_malformed_previous_event_without_raising():
    current = _event("stored", 0)
    result = validate_delivery_transition("not-an-event", current)

    assert result["ok"] is False
    assert "previous:delivery_event_must_be_object" in result["errors"]


def test_event_requires_timezone_evidence_and_source_refs():
    event = _event("stored", 0)
    event["observed_at"] = "2026-07-13T00:00:00"
    event["recorded_at"] = "invalid"
    event["evidence_ref"] = ""
    event["source_refs"] = []

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert "missing_required_field:evidence_ref" in result["errors"]
    assert "source_refs_required" in result["errors"]
    assert "observed_at_must_be_timezone_aware_iso8601" in result["errors"]
    assert "recorded_at_must_be_timezone_aware_iso8601" in result["errors"]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"delivery_audience": "service"}, "invalid_delivery_audience"),
        ({"delivery_form": "popup"}, "invalid_delivery_form"),
        ({"delivery_stage": "opened"}, "invalid_delivery_stage"),
        ({"recorded_at": "2026-07-12T23:59:00Z"}, "recorded_at_precedes_observed_at"),
        ({"source_refs": ["not-an-object"]}, "source_refs_0_must_be_object"),
        ({"source_refs": [{"artifact_id": "a"}]}, "source_refs_0_source_system_required"),
        ({"source_refs": [{"source_system": "synthetic"}]}, "source_refs_0_locator_required"),
    ],
)
def test_event_reports_invalid_base_contract_fields(mutation, expected):
    event = _event("stored", 0)
    event.update(mutation)

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert expected in result["errors"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("delivery_event_id", {"not": "text"}),
        ("retrieval_id", ["not", "text"]),
        ("platform", {"not": "text"}),
        ("evidence_ref", 7),
        ("previous_event_id", {"not": "text"}),
    ],
)
def test_event_identity_and_evidence_fields_must_be_text(field, value):
    event = _event("retrieved", 1, previous_event_id="event-0")
    event[field] = value

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert "%s_must_be_text" % field in result["errors"]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"selection_observation": None}, "selected_requires_intervention_policy_observation"),
        (
            {"selection_observation": {"decision": "silent", "policy_ref": "policy-1"}},
            "selection_decision_must_match_delivery_form",
        ),
        (
            {"selection_observation": {"decision": "emit", "policy_ref": ""}},
            "selection_policy_ref_required",
        ),
    ],
)
def test_selected_requires_a_real_policy_observation(mutation, expected):
    event = _event("selected", 2)
    event.update(mutation)

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert expected in result["errors"]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"delivery_observation": None}, "delivered_or_later_requires_delivery_observation"),
        (
            {"delivery_observation": {"kind": "platform_model_request", "request_id": "r", "source_refs": [_source_ref()]}},
            "delivery_observation_must_be_observed",
        ),
        (
            {"delivery_observation": {"kind": "platform_model_request", "observed": True, "request_id": "r", "source_refs": [_source_ref()]}},
            "delivery_observation_evidence_ref_required",
        ),
        (
            {"delivery_observation": {"kind": "platform_model_request", "observed": True, "evidence_ref": "e", "source_refs": [_source_ref()]}},
            "agent_delivery_request_id_required",
        ),
    ],
)
def test_delivered_requires_complete_observation_fields(mutation, expected):
    event = _event("delivered", 3)
    event.update(mutation)

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert expected in result["errors"]


def test_delivery_observation_must_carry_the_actual_event_source_refs():
    event = _event("delivered", 3)
    event["delivery_observation"]["source_refs"] = [_source_ref("different-memory")]

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert "delivery_observation_must_preserve_event_source_refs" in result["errors"]


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("evidence_authority", "runtime_guess", "agent_delivery_evidence_authority_must_be_host_self_report"),
        ("independent_model_delivery_proven", True, "agent_delivery_must_not_claim_independent_model_delivery"),
        ("platform_delivery_proof_kind", "independent_capture", "agent_delivery_proof_kind_must_be_host_attested_append_only_chain"),
    ],
)
def test_agent_delivery_hard_codes_host_attestation_boundary(field, value, expected):
    event = _event("delivered", 3)
    event["delivery_observation"][field] = value

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert expected in result["errors"]


def test_delivery_chain_may_add_but_never_drop_source_refs():
    stored = _event("stored", 0)
    stored["source_refs"].append(_source_ref("supporting-memory"))
    retrieved = _event("retrieved", 1, previous_event_id="event-0")

    dropped = validate_delivery_transition(stored, retrieved)

    assert dropped["ok"] is False
    assert "delivery_chain_dropped_source_ref" in dropped["errors"]

    retrieved["source_refs"].append(_source_ref("supporting-memory"))
    assert validate_delivery_transition(stored, retrieved)["ok"] is True


def test_source_ref_enrichment_is_preservation_but_locator_change_is_not():
    stored = _event("stored", 0)
    enriched = _event("retrieved", 1, previous_event_id="event-0")
    enriched["source_refs"][0]["line_start"] = 12

    assert validate_delivery_transition(stored, enriched)["ok"] is True

    enriched["source_refs"][0]["artifact_id"] = "different-memory"
    result = validate_delivery_transition(stored, enriched)
    assert result["ok"] is False
    assert "delivery_chain_dropped_source_ref" in result["errors"]


def test_delivery_request_evidence_cannot_change_when_used_is_appended():
    delivered = _event("delivered", 3)
    used = _event("used", 4, previous_event_id="event-3")
    used["delivery_observation"]["request_id"] = "different-request"

    result = validate_delivery_transition(delivered, used)

    assert result["ok"] is False
    assert "delivery_chain_changed_delivery_observation:request_id" in result["errors"]


def test_delivery_request_evidence_cannot_change_across_unknown_gap():
    events = _chain()[:4]
    unknown = _event("unknown", 4, previous_event_id=events[-1]["delivery_event_id"])
    unknown.update({"unknown_for_stage": "used", "unknown_reason": "response_not_observable"})
    used = _event("used", 5, previous_event_id=unknown["delivery_event_id"])
    used["delivery_observation"]["request_id"] = "different-request"

    result = validate_delivery_chain(events + [unknown, used])

    assert result["ok"] is False
    assert result["latest_proven_stage"] == "delivered"
    assert any(
        "delivery_chain_changed_delivery_observation:request_id" in error
        for error in result["errors"]
    )


def test_adoption_evidence_cannot_change_when_helped_is_appended():
    used = _event("used", 4)
    helped = _event("helped", 5, previous_event_id="event-4")
    helped["adoption_evidence"]["evidence_ref"] = "different-adoption"

    result = validate_delivery_transition(used, helped)

    assert result["ok"] is False
    assert "delivery_chain_changed_adoption_evidence:evidence_ref" in result["errors"]


@pytest.mark.parametrize(
    "forbidden_kind",
    ["capability_check", "endpoint_200", "fixture_endpoint", "gateway_result", "generated_catalog", "ui_control"],
)
def test_agent_delivered_rejects_forbidden_delivery_substitutes(forbidden_kind):
    event = _event("delivered", 3)
    event["delivery_observation"]["kind"] = forbidden_kind

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert "forbidden_delivery_substitute:%s" % forbidden_kind in result["errors"]
    assert "agent_delivery_requires_platform_model_request" in result["errors"]


def test_user_digest_delivery_requires_visible_user_observation_not_model_request():
    event = _event("delivered", 3, audience="user", form="digest")
    assert validate_delivery_event(event)["ok"] is True

    event["delivery_observation"] = {
        "kind": "platform_model_request",
        "observed": True,
        "evidence_ref": "request-1",
        "request_id": "request-1",
        "source_refs": [_source_ref()],
    }
    result = validate_delivery_event(event)
    assert result["ok"] is False
    assert "user_delivery_requires_visible_delivery_observation" in result["errors"]


def test_used_requires_response_refs_or_auditable_platform_adoption_trace():
    event = _event("used", 4)
    del event["adoption_evidence"]
    del event["used_source_refs"]
    assert "used_or_later_requires_adoption_evidence" in validate_delivery_event(event)["errors"]

    traced = _event("used", 4)
    traced["adoption_evidence"] = {
        "kind": "platform_adoption_trace",
        "observed": True,
        "evidence_ref": "adoption-1",
        "trace_id": "trace-1",
        "evidence_authority": "host_self_report",
        "independent_model_delivery_proven": False,
        "platform_delivery_proof_kind": "host_attested_append_only_chain",
    }
    del traced["used_source_refs"]
    assert validate_delivery_event(traced)["ok"] is True

    mismatched = _event("used", 4)
    mismatched["used_source_refs"] = [_source_ref("not-delivered")]
    result = validate_delivery_event(mismatched)
    assert result["ok"] is False
    assert "used_source_refs_must_come_from_delivery_source_refs" in result["errors"]


@pytest.mark.parametrize(
    ("adoption_evidence", "expected"),
    [
        ({"kind": "response_source_refs", "evidence_ref": "e"}, "adoption_evidence_must_be_observed"),
        ({"kind": "response_source_refs", "observed": True}, "adoption_evidence_ref_required"),
        ({"kind": "platform_adoption_trace", "observed": True, "evidence_ref": "e"}, "platform_adoption_trace_id_required"),
        ({"kind": "claim", "observed": True, "evidence_ref": "e"}, "invalid_adoption_evidence_kind"),
    ],
)
def test_used_rejects_incomplete_adoption_evidence(adoption_evidence, expected):
    event = _event("used", 4)
    event["adoption_evidence"] = adoption_evidence

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert expected in result["errors"]


@pytest.mark.parametrize(
    ("kind", "identifier"),
    [
        ("task_outcome", "outcome_id"),
        ("explicit_user_feedback", "feedback_id"),
        ("controlled_ab", "experiment_id"),
    ],
)
def test_helped_accepts_only_outcome_feedback_or_controlled_ab(kind, identifier):
    event = _event("helped", 5)
    event["help_evidence"] = {
        "kind": kind,
        "observed": True,
        "evidence_ref": "help-1",
        identifier: "proof-1",
    }
    assert validate_delivery_event(event)["ok"] is True

    event["help_evidence"]["kind"] = "used_event_only"
    result = validate_delivery_event(event)
    assert result["ok"] is False
    assert "invalid_help_evidence_kind" in result["errors"]


@pytest.mark.parametrize(
    ("help_evidence", "expected"),
    [
        (None, "helped_requires_outcome_evidence"),
        ({"kind": "task_outcome", "evidence_ref": "e", "outcome_id": "o"}, "help_evidence_must_be_observed"),
        ({"kind": "task_outcome", "observed": True, "outcome_id": "o"}, "help_evidence_ref_required"),
        ({"kind": "task_outcome", "observed": True, "evidence_ref": "e"}, "help_evidence_outcome_id_required"),
    ],
)
def test_helped_rejects_incomplete_outcome_evidence(help_evidence, expected):
    event = _event("helped", 5)
    event["help_evidence"] = help_evidence

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert expected in result["errors"]


def test_unknown_requires_target_and_reason():
    event = _event("unknown", 3)

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert "unknown_for_stage_must_be_delivered_used_or_helped" in result["errors"]
    assert "unknown_reason_required" in result["errors"]


def test_silent_negative_arm_emits_no_context_or_refs_and_preserves_considered_refs():
    refs = [_source_ref()]
    original = deepcopy(refs)

    result = decide_intervention(
        delivery_audience="agent",
        requested_form="context",
        selection_value=0,
        source_refs=refs,
    )

    assert result["ok"] is True
    assert result["decision"] == "silent"
    assert result["delivery_form"] == "silent"
    assert result["should_emit"] is False
    assert result["should_inject"] is False
    assert result["injected_context"] == ""
    assert result["delivery_payload"] is None
    assert result["emitted_source_refs"] == []
    assert result["considered_source_refs"] == original
    assert refs == original


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"evidence_sufficient": False}, "evidence_insufficient"),
        ({"safety_allowed": False}, "safety_gate_blocked"),
        ({"duplicate": True}, "duplicate_intervention"),
    ],
)
def test_intervention_negative_arms_remain_reachable(kwargs, reason):
    result = decide_intervention(
        delivery_audience="agent",
        requested_form="context",
        selection_value=1,
        source_refs=[_source_ref()],
        **kwargs,
    )
    assert result["decision"] == "silent"
    assert reason in result["silent_reasons"]


def test_policy_silent_decision_can_be_appended_at_selected_stage():
    policy = decide_intervention(
        delivery_audience="agent",
        requested_form="context",
        selection_value=0,
        source_refs=[_source_ref()],
    )
    retrieved = _event("retrieved", 1, form="context", previous_event_id="event-0")
    selected = _event(
        "selected",
        2,
        form=policy["delivery_form"],
        previous_event_id=retrieved["delivery_event_id"],
    )
    selected["selection_observation"] = {
        "decision": policy["decision"],
        "policy_ref": "policy-1",
    }

    result = validate_delivery_transition(retrieved, selected)

    assert policy["decision"] == "silent"
    assert result["ok"] is True


def test_delivery_form_is_locked_after_selection():
    selected = _event("selected", 2, form="context", previous_event_id="event-1")
    delivered = _event("delivered", 3, form="digest", previous_event_id="event-2")

    result = validate_delivery_transition(selected, delivered)

    assert result["ok"] is False
    assert "delivery_chain_identity_changed:delivery_form" in result["errors"]


@pytest.mark.parametrize(
    ("audience", "form", "explicit", "should_inject"),
    [
        ("agent", "catalog", False, False),
        ("agent", "context", False, True),
        ("user", "digest", False, False),
        ("user", "direct_answer", True, False),
        ("user", "silent", False, False),
    ],
)
def test_two_dimensional_policy_covers_both_audiences_and_all_forms(audience, form, explicit, should_inject):
    result = decide_intervention(
        delivery_audience=audience,
        requested_form=form,
        selection_value=1,
        source_refs=[_source_ref()],
        explicit_time_library_entry=explicit,
    )
    if form == "silent":
        assert result["decision"] == "silent"
        assert result["delivery_form"] == "silent"
    else:
        assert result["decision"] == "emit"
        assert result["delivery_form"] == form
    assert result["should_inject"] is should_inject


def test_direct_answer_without_explicit_entry_stays_silent():
    result = decide_intervention(
        delivery_audience="user",
        requested_form="direct_answer",
        selection_value=1,
        source_refs=[_source_ref()],
    )
    assert result["decision"] == "silent"
    assert "direct_answer_requires_explicit_time_library_entry" in result["silent_reasons"]


def test_direct_answer_selected_event_requires_explicit_entry_observation():
    event = _event("selected", 2, audience="user", form="direct_answer")

    result = validate_delivery_event(event)

    assert result["ok"] is False
    assert "direct_answer_requires_explicit_time_library_entry_observation" in result["errors"]
    assert "direct_answer_entry_ref_required" in result["errors"]

    event["selection_observation"].update(
        {
            "explicit_time_library_entry": True,
            "entry_ref": "explicit-entry-1",
        }
    )
    assert validate_delivery_event(event)["ok"] is True


@pytest.mark.parametrize("selection_value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_selection_value_can_never_emit(selection_value):
    result = decide_intervention(
        delivery_audience="agent",
        requested_form="context",
        selection_value=selection_value,
        source_refs=[_source_ref()],
    )

    assert result["ok"] is False
    assert result["decision"] == "silent"
    assert "selection_value_must_be_finite" in result["errors"]


@pytest.mark.parametrize(
    ("source_refs", "expected"),
    [
        ({"source_system": "synthetic", "artifact_id": "a"}, "source_refs_must_be_array"),
        ([{"source_system": "synthetic"}], "source_refs_0_locator_required"),
    ],
)
def test_intervention_reports_malformed_source_refs(source_refs, expected):
    result = decide_intervention(
        delivery_audience="agent",
        requested_form="context",
        selection_value=1,
        source_refs=source_refs,
    )

    assert result["ok"] is False
    assert result["decision"] == "silent"
    assert expected in result["errors"]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"delivery_audience": "service"}, "invalid_delivery_audience"),
        ({"requested_form": "popup"}, "invalid_delivery_form"),
        ({"selection_value": "not-a-number"}, "selection_value_must_be_numeric"),
    ],
)
def test_intervention_rejects_invalid_contract_inputs(kwargs, expected):
    values = {
        "delivery_audience": "agent",
        "requested_form": "context",
        "selection_value": 1,
        "source_refs": [_source_ref()],
    }
    values.update(kwargs)

    result = decide_intervention(**values)

    assert result["ok"] is False
    assert result["decision"] == "silent"
    assert expected in result["errors"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("evidence_sufficient", "false", "evidence_insufficient"),
        ("safety_allowed", "false", "safety_gate_blocked"),
        ("duplicate", "false", "duplicate_intervention"),
        ("explicit_time_library_entry", "false", "direct_answer_requires_explicit_time_library_entry"),
    ],
)
def test_intervention_boolean_gates_fail_closed(field, value, reason):
    values = {
        "delivery_audience": "user" if field == "explicit_time_library_entry" else "agent",
        "requested_form": "direct_answer" if field == "explicit_time_library_entry" else "context",
        "selection_value": 1,
        "source_refs": [_source_ref()],
        field: value,
    }

    result = decide_intervention(**values)

    assert result["ok"] is False
    assert result["decision"] == "silent"
    assert "%s_must_be_boolean" % field in result["errors"]
    assert reason in result["silent_reasons"]


def test_boolean_selection_value_is_not_a_numeric_emit_score():
    result = decide_intervention(
        delivery_audience="agent",
        requested_form="context",
        selection_value=True,
        source_refs=[_source_ref()],
    )

    assert result["ok"] is False
    assert result["decision"] == "silent"
    assert "selection_value_must_be_numeric" in result["errors"]


def test_extreme_numeric_selection_value_fails_closed_without_raising():
    result = decide_intervention(
        delivery_audience="agent",
        requested_form="context",
        selection_value=10**10000,
        source_refs=[_source_ref()],
    )

    assert result["ok"] is False
    assert result["decision"] == "silent"
    assert "selection_value_must_be_numeric" in result["errors"]


def test_silent_selected_event_is_terminal_and_cannot_claim_delivery():
    events = [
        _event("stored", 0, form="silent"),
        _event("retrieved", 1, form="silent", previous_event_id="event-0"),
        _event("selected", 2, form="silent", previous_event_id="event-1"),
    ]
    assert validate_delivery_chain(events)["ok"] is True

    delivered = _event("delivered", 3, form="silent", previous_event_id="event-2")
    result = validate_delivery_chain(events + [delivered])
    assert result["ok"] is False
    assert any("silent_selected_is_terminal" in error for error in result["errors"])
    assert any("silent_route_cannot_advance_beyond_selected" in error for error in result["errors"])


def test_route_profiles_use_one_audience_by_form_model_without_platform_special_cases():
    assert delivery_route_profile("morning_report")["profile"] == {
        "delivery_audience": "user",
        "delivery_form": "digest",
    }
    assert delivery_route_profile("user_notification")["profile"]["delivery_audience"] == "user"
    assert delivery_route_profile("agent_context")["profile"] == {
        "delivery_audience": "agent",
        "delivery_form": "context",
    }
    startup = delivery_route_profile("agent_startup_catalog")
    assert startup["profile"] == {"delivery_audience": "agent", "delivery_form": "catalog"}
    assert startup["platform_special_case"] is False


def _runtime_evidence(kind: str, *, platform: str = "codex", **extra):
    return {
        "state": "observable",
        "kind": kind,
        "platform": platform,
        "observed": True,
        "proof_layer": "platform_runtime",
        "evidence_ref": "runtime-receipt-1",
        **extra,
    }


def test_platform_observability_matrix_has_no_fixed_platform_rows():
    matrix = build_platform_observability_matrix()

    assert matrix["ok"] is True
    assert matrix["rows"] == []
    assert matrix["no_overall_score"] is True
    assert matrix["platform_delivery_proven"] is False
    for row in matrix["rows"]:
        assert set(row["observability"]) == set(OBSERVABILITY_CELLS)
        assert set(row["observability"].values()) == {"unknown"}
        assert set(row["observability"].values()) <= set(OBSERVABILITY_STATES)


def test_platform_observability_promotes_only_qualified_runtime_evidence():
    matrix = build_platform_observability_matrix(
        {
            "codex": {
                "delivered": _runtime_evidence(
                    "platform_model_request",
                    request_id="request-1",
                    source_refs=[_source_ref()],
                ),
                "used": _runtime_evidence(
                    "response_source_refs",
                    source_refs=[_source_ref()],
                ),
                "helped": _runtime_evidence(
                    "explicit_user_feedback",
                    feedback_id="feedback-1",
                ),
            }
        }
    )
    row = next(row for row in matrix["rows"] if row["platform"] == "codex")
    assert row["observability"] == {
        "delivered": "observable",
        "used": "observable",
        "helped": "observable",
    }
    assert set(row["evidence_refs"]) == set(OBSERVABILITY_CELLS)
    assert matrix["platform_delivery_proven"] is False


def test_platform_observability_rejects_evidence_transplanted_from_another_platform():
    matrix = build_platform_observability_matrix(
        {
            "codex": {
                "delivered": _runtime_evidence(
                    "platform_model_request",
                    platform="hermes",
                    request_id="request-1",
                    source_refs=[_source_ref()],
                )
            }
        }
    )
    row = next(row for row in matrix["rows"] if row["platform"] == "codex")

    assert matrix["ok"] is False
    assert row["observability"]["delivered"] == "unknown"
    assert "observation_platform_must_match_row" in row["reasons"]["delivered"]


@pytest.mark.parametrize(
    "kind",
    ["capability_check", "endpoint_200", "fixture_endpoint", "gateway_result", "generated_catalog", "ui_control"],
)
def test_observability_matrix_does_not_promote_forbidden_substitutes(kind):
    matrix = build_platform_observability_matrix(
        {
            "codex": {
                "delivered": _runtime_evidence(
                    kind,
                    request_id="request-1",
                    source_refs=[_source_ref()],
                )
            }
        }
    )
    row = next(row for row in matrix["rows"] if row["platform"] == "codex")
    assert matrix["ok"] is False
    assert row["observability"]["delivered"] == "unknown"
    assert "forbidden_delivery_substitute" in row["reasons"]["delivered"]
    assert "observability_claim_rejected:codex:delivered" in matrix["errors"]


def test_observability_unavailable_requires_an_explicit_reason():
    matrix = build_platform_observability_matrix(
        {
            "claude_desktop": {
                "used": {"state": "unavailable", "reason": "host_response_trace_not_exposed"},
                "helped": {"state": "unavailable"},
            }
        }
    )
    row = next(row for row in matrix["rows"] if row["platform"] == "claude_desktop")
    assert matrix["ok"] is False
    assert row["observability"]["used"] == "unavailable"
    assert row["observability"]["helped"] == "unknown"
    assert row["reasons"]["helped"] == "unavailable_requires_reason"
    assert "observability_claim_rejected:claude_desktop:helped" in matrix["errors"]


def test_observability_matrix_accepts_unknown_clients_but_rejects_unknown_cells():
    matrix = build_platform_observability_matrix(
        {
            "codx": {"delivered": {"state": "unknown"}},
            "codex": {"deliverd": {"state": "unknown"}},
        }
    )

    assert matrix["ok"] is False
    assert matrix["unknown_platforms"] == []
    assert {row["platform"] for row in matrix["rows"]} == {"codx", "codex"}
    assert matrix["unknown_cells_by_platform"] == {"codex": ["deliverd"]}
    assert "unknown_observability_cell:codex:deliverd" in matrix["errors"]


@pytest.mark.parametrize(
    ("observations", "expected"),
    [
        ([], "observations_must_be_object"),
        ({"codex": []}, "platform_observations_must_be_object:codex"),
        ({"codex": {"delivered": "observable"}}, "observability_cell_must_be_object:codex:delivered"),
    ],
)
def test_observability_matrix_reports_malformed_shapes(observations, expected):
    matrix = build_platform_observability_matrix(observations)

    assert matrix["ok"] is False
    assert expected in matrix["errors"]


@pytest.mark.parametrize(
    ("stage", "evidence"),
    [
        (
            "delivered",
            {
                "state": "observable",
                "kind": "platform_model_request",
                "observed": False,
                "proof_layer": "platform_runtime",
                "evidence_ref": "e",
                "request_id": "r",
                "source_refs": [_source_ref()],
            },
        ),
        (
            "delivered",
            {
                "state": "observable",
                "kind": "platform_model_request",
                "observed": True,
                "proof_layer": "source_test",
                "evidence_ref": "e",
                "request_id": "r",
                "source_refs": [_source_ref()],
            },
        ),
        (
            "used",
            {
                "state": "observable",
                "kind": "platform_adoption_trace",
                "observed": True,
                "proof_layer": "platform_runtime",
                "evidence_ref": "e",
            },
        ),
        (
            "helped",
            {
                "state": "observable",
                "kind": "explicit_user_feedback",
                "observed": True,
                "proof_layer": "platform_runtime",
                "evidence_ref": "e",
            },
        ),
    ],
)
def test_observability_matrix_surfaces_rejected_runtime_claims(stage, evidence):
    matrix = build_platform_observability_matrix({"codex": {stage: evidence}})
    row = next(row for row in matrix["rows"] if row["platform"] == "codex")

    assert matrix["ok"] is False
    assert row["observability"][stage] == "unknown"
    assert "observability_claim_rejected:codex:%s" % stage in matrix["errors"]


def test_observability_matrix_rejects_invalid_state_name():
    matrix = build_platform_observability_matrix(
        {"codex": {"delivered": {"state": "observed"}}}
    )

    assert matrix["ok"] is False
    assert "invalid_observability_state:codex:delivered" in matrix["errors"]


def _hermes_event(event_kind):
    event = {
        "event_id": "hermes-event-1",
        "event_kind": event_kind,
        "platform": "hermes",
        "observed_at": "2026-07-13T00:00:00Z",
        "recorded_at": "2026-07-13T00:01:00Z",
        "evidence_ref": "hermes-trace-1",
        "source_refs": [_source_ref("hermes-source-1")],
    }
    if event_kind == "adoption":
        event["adoption_evidence"] = {
            "kind": "response_source_refs",
            "observed": True,
            "evidence_ref": "hermes-adoption-1",
        }
        event["used_source_refs"] = [_source_ref("hermes-source-1")]
    elif event_kind == "outcome":
        event["outcome_evidence"] = {
            "kind": "task_outcome",
            "observed": True,
            "evidence_ref": "hermes-outcome-1",
            "outcome_id": "outcome-1",
        }
    return event


@pytest.mark.parametrize("event_kind", ["adoption", "outcome"])
def test_hermes_events_stop_at_candidate_and_never_write_production_experience(event_kind):
    event = _hermes_event(event_kind)
    original = deepcopy(event)

    result = build_experience_candidate_route(event)

    assert result["ok"] is True
    assert result["next_stage"] == "experience_candidate"
    assert result["required_route"] == [
        "experience_candidate",
        "coverage_preservation_faithfulness_verifier",
        "review_or_authorized_activation",
    ]
    assert result["production_experience_write_allowed"] is False
    assert result["automatic_activation_allowed"] is False
    assert result["production_experience_write_performed"] is False
    assert result["write_performed"] is False
    assert event == original


@pytest.mark.parametrize(
    "forbidden",
    [
        {"production_experience_write": True},
        {"write_target": "production_experience"},
        {"activation_allowed": True},
    ],
)
def test_hermes_route_rejects_direct_production_or_activation_requests(forbidden):
    event = {**_hermes_event("outcome"), **forbidden}
    result = build_experience_candidate_route(event)
    assert result["ok"] is False
    assert result["next_stage"] == "blocked"
    assert result["production_experience_write_performed"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("production_experience_write", "true"),
        ("activation_allowed", 1),
    ],
)
def test_hermes_route_rejects_non_boolean_write_or_activation_flags(field, value):
    event = {**_hermes_event("outcome"), field: value}

    result = build_experience_candidate_route(event)

    assert result["ok"] is False
    assert result["next_stage"] == "blocked"
    assert "%s_must_be_boolean" % field in result["errors"]


@pytest.mark.parametrize("event_kind", ["adoption", "outcome"])
def test_hermes_route_requires_stage_specific_evidence(event_kind):
    event = _hermes_event(event_kind)
    if event_kind == "adoption":
        del event["adoption_evidence"]
        del event["used_source_refs"]
        expected = "used_or_later_requires_adoption_evidence"
    else:
        del event["outcome_evidence"]
        expected = "helped_requires_outcome_evidence"

    result = build_experience_candidate_route(event)

    assert result["ok"] is False
    assert expected in result["errors"]


def test_experience_route_accepts_any_self_reported_platform():
    event = _hermes_event("adoption")
    event["platform"] = "codex"

    result = build_experience_candidate_route(event)

    assert result["ok"] is True
    assert result["accepted_event"]["platform"] == "codex"
