"""Pure R1 Delivery Spine contracts for Time Library.

This module validates append-only delivery events and makes intervention and
observability decisions. It has no store, platform, model, or runtime side
effects. Existing delivery receipts and liveness audits remain the source of
runtime observations.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from src.time_library_vnext_contract import DELIVERY_AUDIENCES, DELIVERY_FORMS


DELIVERY_SPINE_CONTRACT = "time_library.delivery_spine.v2026.7.15"
DELIVERY_EVENT_CONTRACT = "time_library.delivery_event.v2026.7.15"
DELIVERY_TRANSITION_CONTRACT = "time_library.delivery_transition.v2026.7.15"
INTERVENTION_POLICY_CONTRACT = "time_library.intervention_policy.v2026.7.13"
PLATFORM_OBSERVABILITY_CONTRACT = "time_library.platform_observability.v2026.7.13"
HERMES_EXPERIENCE_ROUTE_CONTRACT = "time_library.hermes_experience_route.v2026.7.13"
EXPERIENCE_CANDIDATE_ROUTE_CONTRACT = "time_library.experience_candidate_route.v2026.7.15"

DELIVERY_STAGES = ("stored", "retrieved", "selected", "delivered", "used", "helped")
UNKNOWN_STAGE = "unknown"
UNKNOWN_TARGET_STAGES = ("delivered", "used", "helped")
OBSERVABILITY_STATES = ("observable", "unavailable", "unknown")
OBSERVABILITY_CELLS = ("delivered", "used", "helped")
HOST_SELF_REPORT_EVIDENCE_AUTHORITY = "host_self_report"
HOST_ATTESTED_PLATFORM_DELIVERY_PROOF_KIND = "host_attested_append_only_chain"

FORBIDDEN_DELIVERY_SUBSTITUTES = {
    "capability_check",
    "endpoint_200",
    "fixture_endpoint",
    "gateway_result",
    "generated_catalog",
    "repository_test",
    "ui_control",
}

DELIVERY_ROUTE_PROFILES = {
    "morning_report": {"delivery_audience": "user", "delivery_form": "digest"},
    "user_notification": {"delivery_audience": "user", "delivery_form": "context"},
    "agent_context": {"delivery_audience": "agent", "delivery_form": "context"},
    "agent_startup_catalog": {"delivery_audience": "agent", "delivery_form": "catalog"},
}

_NEXT_STAGE = dict(zip(DELIVERY_STAGES, DELIVERY_STAGES[1:]))
_SOURCE_LOCATORS = ("source_path", "ref_path", "artifact_id", "library_id", "evidence_ref")
_HELP_EVIDENCE_IDENTIFIERS = {
    "task_outcome": "outcome_id",
    "explicit_user_feedback": "feedback_id",
    "controlled_ab": "experiment_id",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _items(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _unique(errors: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(str(error) for error in errors if str(error)))


def _text_field_errors(value: Mapping[str, Any], fields: Iterable[str]) -> List[str]:
    errors: List[str] = []
    for field in fields:
        if field not in value or value.get(field) in (None, "", []):
            continue
        supplied = value.get(field)
        if not isinstance(supplied, str):
            errors.append("%s_must_be_text" % field)
        elif not supplied.strip():
            errors.append("%s_must_be_nonempty_text" % field)
    return errors


def _strict_bool(value: Any, *, field: str, errors: List[str], invalid_default: bool) -> bool:
    if isinstance(value, bool):
        return value
    errors.append("%s_must_be_boolean" % field)
    return invalid_default


def _result(contract: str, errors: Iterable[str], **extra: Any) -> Dict[str, Any]:
    normalized = _unique(errors)
    return {
        "ok": not normalized,
        "contract": contract,
        "errors": normalized,
        "proof_layer": "source_test_contract_only",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "delivery_performed": False,
        **extra,
    }


def _parse_timestamp(value: Any) -> Optional[datetime]:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _source_ref_errors(value: Any, *, field: str = "source_refs") -> List[str]:
    refs = _items(value)
    if not refs:
        return ["%s_required" % field]
    errors: List[str] = []
    for index, ref in enumerate(refs):
        if not isinstance(ref, dict):
            errors.append("%s_%d_must_be_object" % (field, index))
            continue
        if not _text(ref.get("source_system")):
            errors.append("%s_%d_source_system_required" % (field, index))
        if not any(_text(ref.get(locator)) for locator in _SOURCE_LOCATORS):
            errors.append("%s_%d_locator_required" % (field, index))
    return errors


def _source_ref_matches(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    if _text(previous.get("source_system")) != _text(current.get("source_system")):
        return False
    previous_locators = {
        locator: _text(previous.get(locator))
        for locator in _SOURCE_LOCATORS
        if _text(previous.get(locator))
    }
    if not previous_locators:
        return False
    return all(_text(current.get(locator)) == value for locator, value in previous_locators.items())


def _missing_preserved_refs(previous: Any, current: Any) -> List[Dict[str, Any]]:
    previous_refs = [ref for ref in _items(previous) if isinstance(ref, dict)]
    current_refs = [ref for ref in _items(current) if isinstance(ref, dict)]
    return [
        ref
        for ref in previous_refs
        if not any(_source_ref_matches(ref, candidate) for candidate in current_refs)
    ]


def _preserved_mapping_errors(
    previous: Any,
    current: Any,
    *,
    field: str,
    identity_fields: Iterable[str],
    source_refs_field: str = "",
) -> List[str]:
    if not isinstance(previous, Mapping):
        return []
    if not isinstance(current, Mapping):
        return ["delivery_chain_dropped_%s" % field]
    errors: List[str] = []
    for identity_field in identity_fields:
        previous_value = _text(previous.get(identity_field))
        if previous_value and _text(current.get(identity_field)) != previous_value:
            errors.append("delivery_chain_changed_%s:%s" % (field, identity_field))
    if source_refs_field and _missing_preserved_refs(
        previous.get(source_refs_field),
        current.get(source_refs_field),
    ):
        errors.append("delivery_chain_dropped_%s_source_ref" % field)
    return errors


def _prior_stage_evidence_errors(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> List[str]:
    previous_stage = _text(previous.get("delivery_stage"))
    if _text(current.get("delivery_stage")) == UNKNOWN_STAGE:
        return []
    errors: List[str] = []
    if previous_stage in ("delivered", "used", "helped"):
        errors.extend(
            _preserved_mapping_errors(
                previous.get("delivery_observation"),
                current.get("delivery_observation"),
                field="delivery_observation",
                identity_fields=("kind", "evidence_ref", "request_id", "delivery_id", "surface_id"),
                source_refs_field="source_refs",
            )
        )
    if previous_stage in ("used", "helped"):
        errors.extend(
            _preserved_mapping_errors(
                previous.get("adoption_evidence"),
                current.get("adoption_evidence"),
                field="adoption_evidence",
                identity_fields=("kind", "evidence_ref", "trace_id"),
            )
        )
        if _missing_preserved_refs(previous.get("used_source_refs"), current.get("used_source_refs")):
            errors.append("delivery_chain_dropped_used_source_ref")
    return errors


def _delivery_observation_errors(event: Mapping[str, Any]) -> List[str]:
    observation = event.get("delivery_observation")
    if not isinstance(observation, dict):
        return ["delivered_or_later_requires_delivery_observation"]
    errors: List[str] = []
    kind = _text(observation.get("kind"))
    if kind in FORBIDDEN_DELIVERY_SUBSTITUTES:
        errors.append("forbidden_delivery_substitute:%s" % kind)
    if observation.get("observed") is not True:
        errors.append("delivery_observation_must_be_observed")
    if not _text(observation.get("evidence_ref")):
        errors.append("delivery_observation_evidence_ref_required")
    observation_refs = observation.get("source_refs")
    errors.extend(_source_ref_errors(observation_refs, field="delivery_observation_source_refs"))
    if _missing_preserved_refs(event.get("source_refs"), observation_refs):
        errors.append("delivery_observation_must_preserve_event_source_refs")
    if event.get("delivery_audience") == "agent":
        if observation.get("evidence_authority") != HOST_SELF_REPORT_EVIDENCE_AUTHORITY:
            errors.append("agent_delivery_evidence_authority_must_be_host_self_report")
        if observation.get("independent_model_delivery_proven") is not False:
            errors.append("agent_delivery_must_not_claim_independent_model_delivery")
        if observation.get("platform_delivery_proof_kind") != HOST_ATTESTED_PLATFORM_DELIVERY_PROOF_KIND:
            errors.append("agent_delivery_proof_kind_must_be_host_attested_append_only_chain")
        if kind != "platform_model_request":
            errors.append("agent_delivery_requires_platform_model_request")
        if not _text(observation.get("request_id")):
            errors.append("agent_delivery_request_id_required")
    elif event.get("delivery_audience") == "user":
        if kind != "user_visible_delivery":
            errors.append("user_delivery_requires_visible_delivery_observation")
        if not _text(observation.get("delivery_id") or observation.get("surface_id")):
            errors.append("user_delivery_id_required")
    return errors


def _adoption_evidence_errors(event: Mapping[str, Any]) -> List[str]:
    adoption = event.get("adoption_evidence")
    if not isinstance(adoption, dict):
        return ["used_or_later_requires_adoption_evidence"]
    errors: List[str] = []
    kind = _text(adoption.get("kind"))
    if adoption.get("observed") is not True:
        errors.append("adoption_evidence_must_be_observed")
    if not _text(adoption.get("evidence_ref")):
        errors.append("adoption_evidence_ref_required")
    if event.get("delivery_audience") == "agent":
        if adoption.get("evidence_authority") != HOST_SELF_REPORT_EVIDENCE_AUTHORITY:
            errors.append("agent_adoption_evidence_authority_must_be_host_self_report")
        if adoption.get("independent_model_delivery_proven") is not False:
            errors.append("agent_adoption_must_not_claim_independent_model_delivery")
        if adoption.get("platform_delivery_proof_kind") != HOST_ATTESTED_PLATFORM_DELIVERY_PROOF_KIND:
            errors.append("agent_adoption_proof_kind_must_be_host_attested_append_only_chain")
    if kind == "response_source_refs":
        errors.extend(_source_ref_errors(event.get("used_source_refs"), field="used_source_refs"))
        if _missing_preserved_refs(event.get("used_source_refs"), event.get("source_refs")):
            errors.append("used_source_refs_must_come_from_delivery_source_refs")
    elif kind == "platform_adoption_trace":
        if not _text(adoption.get("trace_id")):
            errors.append("platform_adoption_trace_id_required")
    else:
        errors.append("invalid_adoption_evidence_kind")
    return errors


def _help_evidence_errors(event: Mapping[str, Any]) -> List[str]:
    evidence = event.get("help_evidence")
    if not isinstance(evidence, dict):
        return ["helped_requires_outcome_evidence"]
    errors: List[str] = []
    kind = _text(evidence.get("kind"))
    identifier = _HELP_EVIDENCE_IDENTIFIERS.get(kind)
    if not identifier:
        errors.append("invalid_help_evidence_kind")
    elif not _text(evidence.get(identifier)):
        errors.append("help_evidence_%s_required" % identifier)
    if evidence.get("observed") is not True:
        errors.append("help_evidence_must_be_observed")
    if not _text(evidence.get("evidence_ref")):
        errors.append("help_evidence_ref_required")
    return errors


def validate_delivery_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate one immutable event shape without changing the supplied value."""
    if not isinstance(event, Mapping):
        return _result(DELIVERY_EVENT_CONTRACT, ["delivery_event_must_be_object"])

    required = (
        "delivery_event_id",
        "retrieval_id",
        "platform",
        "delivery_audience",
        "delivery_form",
        "delivery_stage",
        "observed_at",
        "recorded_at",
        "evidence_ref",
        "source_refs",
    )
    errors = [
        "missing_required_field:%s" % field
        for field in required
        if field not in event or event.get(field) in (None, "", [])
    ]
    errors.extend(_text_field_errors(event, required[:-1]))
    if "previous_event_id" in event and event.get("previous_event_id") not in (None, ""):
        errors.extend(_text_field_errors(event, ("previous_event_id",)))
    if event.get("delivery_audience") not in DELIVERY_AUDIENCES:
        errors.append("invalid_delivery_audience")
    if event.get("delivery_form") not in DELIVERY_FORMS:
        errors.append("invalid_delivery_form")
    stage = _text(event.get("delivery_stage"))
    if stage not in DELIVERY_STAGES + (UNKNOWN_STAGE,):
        errors.append("invalid_delivery_stage")
    errors.extend(_source_ref_errors(event.get("source_refs")))

    observed_at = _parse_timestamp(event.get("observed_at"))
    recorded_at = _parse_timestamp(event.get("recorded_at"))
    if observed_at is None:
        errors.append("observed_at_must_be_timezone_aware_iso8601")
    if recorded_at is None:
        errors.append("recorded_at_must_be_timezone_aware_iso8601")
    if observed_at is not None and recorded_at is not None and recorded_at < observed_at:
        errors.append("recorded_at_precedes_observed_at")

    form = event.get("delivery_form")
    if form == "silent" and stage in ("delivered", "used", "helped"):
        errors.append("silent_route_cannot_advance_beyond_selected")
    if stage == "selected":
        selection = event.get("selection_observation")
        if not isinstance(selection, dict):
            errors.append("selected_requires_intervention_policy_observation")
        else:
            expected = "silent" if form == "silent" else "emit"
            if selection.get("decision") != expected:
                errors.append("selection_decision_must_match_delivery_form")
            if not _text(selection.get("policy_ref")):
                errors.append("selection_policy_ref_required")
            if form == "direct_answer":
                if selection.get("explicit_time_library_entry") is not True:
                    errors.append("direct_answer_requires_explicit_time_library_entry_observation")
                if not _text(selection.get("entry_ref")):
                    errors.append("direct_answer_entry_ref_required")

    if stage in ("delivered", "used", "helped"):
        errors.extend(_delivery_observation_errors(event))
    if stage in ("used", "helped"):
        errors.extend(_adoption_evidence_errors(event))
    if stage == "helped":
        errors.extend(_help_evidence_errors(event))
    if stage == UNKNOWN_STAGE:
        target = _text(event.get("unknown_for_stage"))
        if target not in UNKNOWN_TARGET_STAGES:
            errors.append("unknown_for_stage_must_be_delivered_used_or_helped")
        if not _text(event.get("unknown_reason")):
            errors.append("unknown_reason_required")

    return _result(
        DELIVERY_EVENT_CONTRACT,
        errors,
        event_id=_text(event.get("delivery_event_id")),
        stage=stage,
        append_only_candidate=True,
    )


def _stable_identity_errors(previous: Mapping[str, Any], current: Mapping[str, Any]) -> List[str]:
    errors = []
    for field in ("retrieval_id", "platform", "delivery_audience"):
        if previous.get(field) != current.get(field):
            errors.append("delivery_chain_identity_changed:%s" % field)
    if (
        previous.get("delivery_form") != current.get("delivery_form")
        and current.get("delivery_stage") != "selected"
    ):
        errors.append("delivery_chain_identity_changed:delivery_form")
    if _missing_preserved_refs(previous.get("source_refs"), current.get("source_refs")):
        errors.append("delivery_chain_dropped_source_ref")
    errors.extend(_prior_stage_evidence_errors(previous, current))
    return errors


def validate_delivery_transition(
    previous: Optional[Mapping[str, Any]],
    current: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate an append-only transition, including visible unknown gaps."""
    current_validation = validate_delivery_event(current)
    errors = ["current:%s" % error for error in current_validation["errors"]]
    if not isinstance(current, Mapping):
        return _result(DELIVERY_TRANSITION_CONTRACT, errors, transition="invalid_current_event")
    if previous is None:
        if current.get("delivery_stage") != "stored":
            errors.append("delivery_chain_must_start_at_stored")
        if _text(current.get("previous_event_id")):
            errors.append("first_event_must_not_have_previous_event_id")
        return _result(DELIVERY_TRANSITION_CONTRACT, errors, transition="start_to_%s" % current.get("delivery_stage"))

    previous_validation = validate_delivery_event(previous)
    errors.extend("previous:%s" % error for error in previous_validation["errors"])
    if not isinstance(previous, Mapping):
        return _result(DELIVERY_TRANSITION_CONTRACT, errors, transition="invalid_previous_event")
    errors.extend(_stable_identity_errors(previous, current))
    if current.get("delivery_event_id") == previous.get("delivery_event_id"):
        errors.append("delivery_event_id_must_be_unique")
    if current.get("previous_event_id") != previous.get("delivery_event_id"):
        errors.append("previous_event_id_must_link_immediate_predecessor")

    previous_observed = _parse_timestamp(previous.get("observed_at"))
    current_observed = _parse_timestamp(current.get("observed_at"))
    previous_recorded = _parse_timestamp(previous.get("recorded_at"))
    current_recorded = _parse_timestamp(current.get("recorded_at"))
    if previous_observed and current_observed and current_observed < previous_observed:
        errors.append("observed_at_must_be_monotonic")
    if previous_recorded and current_recorded and current_recorded < previous_recorded:
        errors.append("recorded_at_must_be_monotonic")

    previous_stage = _text(previous.get("delivery_stage"))
    current_stage = _text(current.get("delivery_stage"))
    if previous.get("delivery_form") == "silent" and previous_stage == "selected":
        errors.append("silent_selected_is_terminal")
    elif previous_stage == UNKNOWN_STAGE:
        unresolved = _text(previous.get("unknown_for_stage"))
        if current_stage == UNKNOWN_STAGE:
            if current.get("unknown_for_stage") != unresolved:
                errors.append("unknown_transition_changed_target_stage")
        elif current_stage != unresolved:
            errors.append("unknown_transition_must_resolve_same_target_stage")
    else:
        expected = _NEXT_STAGE.get(previous_stage)
        if current_stage == UNKNOWN_STAGE:
            if not expected or current.get("unknown_for_stage") != expected:
                errors.append("unknown_transition_must_target_next_stage")
        elif current_stage != expected:
            errors.append("illegal_delivery_stage_transition:%s_to_%s" % (previous_stage, current_stage))

    return _result(
        DELIVERY_TRANSITION_CONTRACT,
        errors,
        transition="%s_to_%s" % (previous_stage, current_stage),
    )


def validate_delivery_chain(events: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate a complete chain while leaving every supplied event untouched."""
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)) or not events:
        return _result(DELIVERY_SPINE_CONTRACT, ["delivery_chain_requires_events"])

    errors: List[str] = []
    event_ids: List[str] = []
    latest_proven_stage = ""
    unknown_targets: List[str] = []
    validated_prefix_event_count = 0
    valid_prefix = True
    last_proven_event: Optional[Mapping[str, Any]] = None
    previous: Optional[Mapping[str, Any]] = None
    for index, event in enumerate(events):
        transition = validate_delivery_transition(previous, event)
        step_errors = ["event_%d:%s" % (index, error) for error in transition["errors"]]
        event_id = _text(event.get("delivery_event_id")) if isinstance(event, Mapping) else ""
        if event_id in event_ids:
            step_errors.append("event_%d:duplicate_delivery_event_id" % index)
        event_ids.append(event_id)
        stage = _text(event.get("delivery_stage")) if isinstance(event, Mapping) else ""
        if (
            valid_prefix
            and not step_errors
            and stage in DELIVERY_STAGES
            and last_proven_event is not None
            and isinstance(previous, Mapping)
            and _text(previous.get("delivery_stage")) == UNKNOWN_STAGE
        ):
            step_errors.extend(
                "event_%d:%s" % (index, error)
                for error in _prior_stage_evidence_errors(last_proven_event, event)
            )
        if valid_prefix and not step_errors:
            validated_prefix_event_count += 1
            if stage == UNKNOWN_STAGE:
                unknown_targets.append(_text(event.get("unknown_for_stage")))
            elif stage in DELIVERY_STAGES:
                latest_proven_stage = stage
                last_proven_event = event
        else:
            valid_prefix = False
        errors.extend(step_errors)
        previous = event

    return _result(
        DELIVERY_SPINE_CONTRACT,
        errors,
        event_count=len(events),
        validated_prefix_event_count=validated_prefix_event_count,
        latest_proven_stage=latest_proven_stage,
        unknown_targets=unknown_targets,
        immutable_append_only=True,
        events_remain_orderable=True,
        source_refs_required_not_replacement=True,
    )


def decide_intervention(
    *,
    delivery_audience: str,
    requested_form: str,
    selection_value: float,
    source_refs: Sequence[Mapping[str, Any]],
    evidence_sufficient: bool = True,
    safety_allowed: bool = True,
    duplicate: bool = False,
    explicit_time_library_entry: bool = False,
) -> Dict[str, Any]:
    """Choose emit or silent without constructing or injecting any payload."""
    errors: List[str] = []
    if delivery_audience not in DELIVERY_AUDIENCES:
        errors.append("invalid_delivery_audience")
    if requested_form not in DELIVERY_FORMS:
        errors.append("invalid_delivery_form")
    evidence_sufficient = _strict_bool(
        evidence_sufficient,
        field="evidence_sufficient",
        errors=errors,
        invalid_default=False,
    )
    safety_allowed = _strict_bool(
        safety_allowed,
        field="safety_allowed",
        errors=errors,
        invalid_default=False,
    )
    duplicate = _strict_bool(
        duplicate,
        field="duplicate",
        errors=errors,
        invalid_default=True,
    )
    explicit_time_library_entry = _strict_bool(
        explicit_time_library_entry,
        field="explicit_time_library_entry",
        errors=errors,
        invalid_default=False,
    )
    refs = deepcopy(_items(source_refs))
    ref_errors = _source_ref_errors(refs)
    if not isinstance(source_refs, (list, tuple)):
        errors.append("source_refs_must_be_array")
    elif refs and ref_errors:
        errors.extend(ref_errors)
    try:
        if isinstance(selection_value, bool):
            raise TypeError
        numeric_value = float(selection_value)
    except (OverflowError, TypeError, ValueError):
        numeric_value = 0.0
        errors.append("selection_value_must_be_numeric")
    if not math.isfinite(numeric_value):
        numeric_value = 0.0
        errors.append("selection_value_must_be_finite")

    silent_reasons: List[str] = []
    if requested_form == "silent":
        silent_reasons.append("silent_requested")
    if numeric_value <= 0:
        silent_reasons.append("no_selection_value")
    if ref_errors:
        silent_reasons.append("source_refs_unavailable")
    if not evidence_sufficient:
        silent_reasons.append("evidence_insufficient")
    if not safety_allowed:
        silent_reasons.append("safety_gate_blocked")
    if duplicate:
        silent_reasons.append("duplicate_intervention")
    if requested_form == "direct_answer" and not explicit_time_library_entry:
        silent_reasons.append("direct_answer_requires_explicit_time_library_entry")

    should_emit = not errors and not silent_reasons
    form = requested_form if should_emit else "silent"
    return _result(
        INTERVENTION_POLICY_CONTRACT,
        errors,
        decision="emit" if should_emit else "silent",
        should_emit=should_emit,
        should_inject=should_emit and form == "context",
        delivery_audience=delivery_audience,
        delivery_form=form,
        considered_source_refs=refs,
        emitted_source_refs=deepcopy(refs) if should_emit else [],
        silent_reasons=silent_reasons,
        injected_context="",
        delivery_payload=None,
        policy_is_pure=True,
    )


def delivery_route_profile(route: str) -> Dict[str, Any]:
    profile = DELIVERY_ROUTE_PROFILES.get(_text(route))
    errors = [] if profile else ["unknown_delivery_route"]
    return _result(
        INTERVENTION_POLICY_CONTRACT,
        errors,
        route=_text(route),
        profile=deepcopy(profile) if profile else {},
        platform_special_case=False,
    )


def _runtime_observation_errors(
    stage: str,
    evidence: Mapping[str, Any],
    *,
    expected_platform: str,
) -> List[str]:
    errors: List[str] = []
    kind = _text(evidence.get("kind"))
    if kind in FORBIDDEN_DELIVERY_SUBSTITUTES:
        errors.append("forbidden_delivery_substitute:%s" % kind)
    if evidence.get("observed") is not True:
        errors.append("observation_must_be_true")
    if _text(evidence.get("proof_layer")) not in {"connected_runtime", "installed_runtime", "platform_runtime"}:
        errors.append("runtime_proof_layer_required")
    if not _text(evidence.get("evidence_ref")):
        errors.append("evidence_ref_required")
    if _text(evidence.get("platform")) != expected_platform:
        errors.append("observation_platform_must_match_row")
    if stage == "delivered":
        if kind != "platform_model_request":
            errors.append("delivered_observability_requires_model_request")
        if not _text(evidence.get("request_id")):
            errors.append("request_id_required")
        errors.extend(_source_ref_errors(evidence.get("source_refs")))
    elif stage == "used":
        if kind not in {"response_source_refs", "platform_adoption_trace"}:
            errors.append("used_observability_requires_adoption_trace")
        if kind == "response_source_refs":
            errors.extend(_source_ref_errors(evidence.get("source_refs")))
        elif not _text(evidence.get("trace_id")):
            errors.append("trace_id_required")
    elif stage == "helped":
        identifier = _HELP_EVIDENCE_IDENTIFIERS.get(kind)
        if not identifier:
            errors.append("helped_observability_requires_outcome_evidence")
        elif not _text(evidence.get(identifier)):
            errors.append("%s_required" % identifier)
    return errors


def _observability_cell(stage: str, supplied: Any, *, platform: str) -> Dict[str, Any]:
    if not isinstance(supplied, Mapping):
        return {"state": "unknown", "reason": "runtime_observation_not_supplied", "evidence_ref": ""}
    requested = _text(supplied.get("state")) or "unknown"
    if requested not in OBSERVABILITY_STATES:
        return {"state": "unknown", "reason": "invalid_observability_state", "evidence_ref": ""}
    if requested == "unknown":
        return {
            "state": "unknown",
            "reason": _text(supplied.get("reason")) or "runtime_observation_not_supplied",
            "evidence_ref": "",
        }
    if requested == "unavailable":
        reason = _text(supplied.get("reason"))
        return {
            "state": "unavailable" if reason else "unknown",
            "reason": reason or "unavailable_requires_reason",
            "evidence_ref": "",
        }
    errors = _runtime_observation_errors(stage, supplied, expected_platform=platform)
    return {
        "state": "observable" if not errors else "unknown",
        "reason": "" if not errors else ";".join(errors),
        "evidence_ref": _text(supplied.get("evidence_ref")) if not errors else "",
    }


def build_platform_observability_matrix(
    observations: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build honest rows for the clients that supplied observations."""
    input_errors = []
    if observations is not None and not isinstance(observations, Mapping):
        input_errors.append("observations_must_be_object")
    supplied = observations if isinstance(observations, Mapping) else {}
    platforms = tuple(dict.fromkeys(str(platform).strip() for platform in supplied if str(platform).strip()))
    unknown_platforms: List[str] = []
    errors = list(input_errors)
    unknown_cells_by_platform: Dict[str, List[str]] = {}
    rows = []
    for platform in platforms:
        raw_platform_observations = supplied.get(platform)
        if raw_platform_observations is not None and not isinstance(raw_platform_observations, Mapping):
            errors.append("platform_observations_must_be_object:%s" % platform)
        platform_observations = (
            raw_platform_observations
            if isinstance(raw_platform_observations, Mapping)
            else {}
        )
        unknown_cells = sorted(
            str(cell)
            for cell in platform_observations
            if cell not in OBSERVABILITY_CELLS
        )
        if unknown_cells:
            unknown_cells_by_platform[platform] = unknown_cells
            errors.extend(
                "unknown_observability_cell:%s:%s" % (platform, cell)
                for cell in unknown_cells
            )
        for stage in OBSERVABILITY_CELLS:
            if stage in platform_observations and not isinstance(platform_observations.get(stage), Mapping):
                errors.append("observability_cell_must_be_object:%s:%s" % (platform, stage))
        details = {
            stage: _observability_cell(stage, platform_observations.get(stage), platform=platform)
            for stage in OBSERVABILITY_CELLS
        }
        for stage in OBSERVABILITY_CELLS:
            supplied_cell = platform_observations.get(stage)
            if not isinstance(supplied_cell, Mapping):
                continue
            requested_state = _text(supplied_cell.get("state")) or "unknown"
            normalized_state = details[stage]["state"]
            if requested_state not in OBSERVABILITY_STATES:
                errors.append("invalid_observability_state:%s:%s" % (platform, stage))
            elif requested_state in {"observable", "unavailable"} and normalized_state != requested_state:
                errors.append("observability_claim_rejected:%s:%s" % (platform, stage))
        rows.append(
            {
                "platform": platform,
                "observability": {stage: details[stage]["state"] for stage in OBSERVABILITY_CELLS},
                "reasons": {stage: details[stage]["reason"] for stage in OBSERVABILITY_CELLS},
                "evidence_refs": {
                    stage: details[stage]["evidence_ref"]
                    for stage in OBSERVABILITY_CELLS
                    if details[stage]["evidence_ref"]
                },
            }
        )
    counts = {
        stage: {
            state: sum(1 for row in rows if row["observability"][stage] == state)
            for state in OBSERVABILITY_STATES
        }
        for stage in OBSERVABILITY_CELLS
    }
    return _result(
        PLATFORM_OBSERVABILITY_CONTRACT,
        errors,
        rows=rows,
        counts=counts,
        unknown_platforms=unknown_platforms,
        unknown_cells_by_platform=unknown_cells_by_platform,
        allowed_states=list(OBSERVABILITY_STATES),
        no_overall_score=True,
        capability_or_discovery_is_not_delivery_proof=True,
        platform_delivery_proven=False,
    )


def build_experience_candidate_route(event: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate any host adoption/outcome event and stop at candidate routing."""
    if not isinstance(event, Mapping):
        return _result(EXPERIENCE_CANDIDATE_ROUTE_CONTRACT, ["experience_event_must_be_object"])
    required = (
        "event_id",
        "event_kind",
        "platform",
        "observed_at",
        "recorded_at",
        "evidence_ref",
        "source_refs",
    )
    errors = [
        "missing_required_field:%s" % field
        for field in required
        if field not in event or event.get(field) in (None, "", [])
    ]
    errors.extend(_text_field_errors(event, required[:-1]))
    if event.get("event_kind") not in ("adoption", "outcome"):
        errors.append("experience_event_kind_must_be_adoption_or_outcome")
    errors.extend(_source_ref_errors(event.get("source_refs")))
    if event.get("event_kind") == "adoption":
        errors.extend(_adoption_evidence_errors(event))
    elif event.get("event_kind") == "outcome":
        errors.extend(_help_evidence_errors({"help_evidence": event.get("outcome_evidence")}))
    observed_at = _parse_timestamp(event.get("observed_at"))
    recorded_at = _parse_timestamp(event.get("recorded_at"))
    if observed_at is None:
        errors.append("observed_at_must_be_timezone_aware_iso8601")
    if recorded_at is None:
        errors.append("recorded_at_must_be_timezone_aware_iso8601")
    if observed_at and recorded_at and recorded_at < observed_at:
        errors.append("recorded_at_precedes_observed_at")
    if "production_experience_write" in event and not isinstance(event.get("production_experience_write"), bool):
        errors.append("production_experience_write_must_be_boolean")
    if "activation_allowed" in event and not isinstance(event.get("activation_allowed"), bool):
        errors.append("activation_allowed_must_be_boolean")
    if "write_target" in event and event.get("write_target") not in (None, ""):
        errors.extend(_text_field_errors(event, ("write_target",)))
    if event.get("production_experience_write") is True or event.get("write_target") == "production_experience":
        errors.append("direct_production_experience_write_forbidden")
    if event.get("activation_allowed") is True:
        errors.append("experience_event_cannot_directly_allow_activation")

    return _result(
        EXPERIENCE_CANDIDATE_ROUTE_CONTRACT,
        errors,
        accepted_event=deepcopy(dict(event)) if not errors else {},
        next_stage="experience_candidate" if not errors else "blocked",
        required_route=[
            "experience_candidate",
            "coverage_preservation_faithfulness_verifier",
            "review_or_authorized_activation",
        ],
        production_experience_write_allowed=False,
        automatic_activation_allowed=False,
        production_experience_write_performed=False,
    )


def build_hermes_experience_route(event: Mapping[str, Any]) -> Dict[str, Any]:
    """Backward-compatible alias for the platform-neutral candidate route."""
    return build_experience_candidate_route(event)


__all__ = [
    "DELIVERY_EVENT_CONTRACT",
    "DELIVERY_ROUTE_PROFILES",
    "DELIVERY_SPINE_CONTRACT",
    "DELIVERY_STAGES",
    "DELIVERY_TRANSITION_CONTRACT",
    "EXPERIENCE_CANDIDATE_ROUTE_CONTRACT",
    "HERMES_EXPERIENCE_ROUTE_CONTRACT",
    "INTERVENTION_POLICY_CONTRACT",
    "OBSERVABILITY_CELLS",
    "OBSERVABILITY_STATES",
    "PLATFORM_OBSERVABILITY_CONTRACT",
    "UNKNOWN_STAGE",
    "build_experience_candidate_route",
    "build_hermes_experience_route",
    "build_platform_observability_matrix",
    "decide_intervention",
    "delivery_route_profile",
    "validate_delivery_chain",
    "validate_delivery_event",
    "validate_delivery_transition",
]
