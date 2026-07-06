from src.platform_delivery_liveness import (
    PLATFORM_DELIVERY_LIVENESS_CONTRACT,
    build_platform_delivery_liveness_audit,
)


def test_platform_delivery_liveness_is_findings_only_and_not_delivery():
    payload = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "openclaw",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "content_gate": "verified_format_collector_required",
                    "actions": [{"action": "capability_check", "status": "ready"}],
                },
                {
                    "system": "hermes",
                    "status": "detected",
                    "connectable_now": False,
                    "intent_signal_detected": False,
                    "content_gate": "raw_pointer_consumption_only_no_platform_write",
                    "actions": [{"action": "auto_connect", "status": "auto_connect_ready"}],
                },
            ],
        },
        preflight_payload={
            "recall_status": "preflight_surface_required",
            "memory_scope": "active",
            "source_refs_count": 1,
            "raw_items_count": 1,
            "cross_window_read": False,
        },
        platforms=("openclaw", "hermes"),
    )

    assert payload["contract"] == PLATFORM_DELIVERY_LIVENESS_CONTRACT
    assert payload["read_only"] is True
    assert payload["findings_only"] is True
    assert payload["write_performed"] is False
    assert payload["platform_write_performed"] is False
    assert payload["model_call_performed"] is False
    assert payload["not_a_delivery_mechanism"] is True
    assert payload["not_a_model_answerer"] is True
    assert payload["final_evidence_authority"] == "raw_source_refs"
    assert payload["counts"]["platforms_with_source_refs_visible"] == 2
    assert payload["counts"]["platforms_with_model_delivery_observed"] == 0

    openclaw = next(item for item in payload["platforms"] if item["platform"] == "openclaw")
    hermes = next(item for item in payload["platforms"] if item["platform"] == "hermes")
    assert openclaw["passive_state"] == "connection_ready"
    assert openclaw["delivered_to_model"] == "not_measured"
    assert "connection_signal_only_not_delivery_proof" in openclaw["risk"]
    assert openclaw["recommended_next_contract"] == "run_live_passive_delivery_probe"
    assert hermes["passive_state"] == "detected_without_connection"
    assert hermes["boundary_metadata"]["content_gate"] == "raw_pointer_consumption_only_no_platform_write"


def test_platform_delivery_liveness_infers_platforms_from_autodiscovery():
    payload = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "openclaw",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                },
                {
                    "system": "claude_code_cli",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                },
                {
                    "system": "pi",
                    "status": "detected",
                    "connectable_now": False,
                    "intent_signal_detected": False,
                    "actions": [{"action": "auto_connect", "status": "auto_connect_ready"}],
                },
                {"system": "memcore_cloud", "status": "active", "connectable_now": True},
                {"system": "unused", "status": "not_found", "connectable_now": False, "intent_signal_detected": False},
            ],
        },
        preflight_payload={},
    )

    assert [item["platform"] for item in payload["platforms"]] == ["openclaw", "claude_code_cli", "pi"]
    assert payload["counts"]["platforms_total"] == 3


def test_platform_delivery_liveness_flags_local_fallback_answer_owner():
    payload = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "openclaw",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                }
            ],
        },
        preflight_payload={
            "source_refs_count": 0,
            "raw_items_count": 0,
            "scope_missing": True,
            "recall_status": "window_identity_required",
        },
        dialog_result={
            "answer": "local fallback",
            "answer_source": "zhiyi_direct_natural_fallback_after_model_no_answer",
            "platform_delivery": {"requested": True, "executed": False, "reason": "platform_delivery_not_enabled"},
            "answer_debug": {
                "model_call": {
                    "requested": True,
                    "called": False,
                    "request_sent": True,
                    "fallback_applied": True,
                },
                "evidence": [],
            },
        },
        platforms=("openclaw",),
    )

    finding = payload["platforms"][0]
    assert finding["answer_owner"] == "zhiyi_direct_natural_fallback_after_model_no_answer"
    assert finding["local_draft_detected"] is True
    assert "local_draft_or_fallback_answer_detected" in finding["risk"]
    assert "source_refs_not_visible" in finding["risk"]
    assert finding["recommended_next_contract"] == "expose_answer_owner_and_block_local_draft_as_think"
    assert payload["counts"]["platforms_with_local_draft_detected"] == 1


def test_platform_delivery_liveness_accepts_observed_model_and_user_delivery():
    payload = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "openclaw",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                }
            ],
        },
        preflight_payload={
            "source_refs_count": 2,
            "raw_items_count": 1,
            "cross_window_read": False,
            "cross_window_read_allowed": False,
        },
        dialog_result={
            "answer_source": "evidence_bound_model_call",
            "answer_debug": {
                "model_call": {"called": True, "supporting_refs": ["E1"]},
                "evidence": [{"source_refs_present": True}],
            },
            "platform_delivery": {
                "delivery_method": "before_dispatch_return",
                "visible_reply_ok": True,
                "write_performed": False,
            },
        },
        platforms=("openclaw",),
    )

    finding = payload["platforms"][0]
    assert finding["delivered_to_model"] == "preempted_provider_model"
    assert finding["delivered_to_user"] == "observed"
    assert finding["answer_owner"] == "evidence_bound_model_call"
    assert finding["source_refs_visible"] is True
    assert finding["local_draft_detected"] is False
    assert "source_refs_not_visible" not in finding["risk"]
    assert payload["counts"]["platforms_with_user_delivery_observed"] == 1


def test_platform_delivery_liveness_accepts_trusted_memory_trace_as_model_observed():
    payload = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "openclaw",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                }
            ],
        },
        preflight_payload={
            "source_refs_count": 1,
            "raw_items_count": 1,
        },
        dialog_result={
            "answer_source": "evidence_bound_model_call",
            "trusted_memory_delivery_trace": {
                "status": "proven",
                "model_delivery_state": "observed",
                "used_source_refs": ["E1"],
            },
            "answer_debug": {
                "model_call": {"called": True, "request_sent": True, "supporting_refs": ["E1"]},
                "evidence": [{"source_refs_present": True}],
            },
            "platform_delivery": {
                "delivery_method": "before_dispatch_return",
                "visible_reply_ok": True,
                "write_performed": False,
            },
        },
        platforms=("openclaw",),
    )

    finding = payload["platforms"][0]

    assert finding["delivered_to_model"] == "observed"
    assert finding["delivered_to_user"] == "observed"
    assert "connection_signal_only_not_delivery_proof" not in finding["risk"]
    assert payload["counts"]["platforms_with_model_delivery_observed"] == 1
    assert finding["definition_of_proven_observed"] is False


def test_platform_delivery_liveness_requires_all_definition_cells_for_platform_proof_metadata():
    payload = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "codex",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                }
            ],
        },
        preflight_payload={
            "source_refs_count": 1,
            "raw_items_count": 1,
        },
        dialog_result={
            "answer_source": "evidence_bound_model_call",
            "trusted_memory_delivery_trace": {
                "status": "unproven",
                "model_delivery_state": "observed",
                "cells": {
                    "passive_gate_observed": True,
                    "model_evidence_receipt_observed": True,
                    "answer_evidence_observed": True,
                    "receipt_visibility_observed": True,
                    "security_gate_observed": False,
                },
                "missing_cells": ["security_gate_observed"],
                "used_source_refs": ["E1"],
            },
            "answer_debug": {
                "model_call": {"called": True, "request_sent": True, "supporting_refs": ["E1"]},
                "evidence": [{"source_refs_present": True}],
            },
        },
        platforms=("codex",),
    )

    finding = payload["platforms"][0]

    assert finding["delivered_to_model"] == "observed"
    assert finding["definition_of_proven_observed"] is False
    assert finding["definition_of_proven_missing_cells"] == ["security_gate_observed"]
    assert finding["definition_of_proven_cells"]["security_gate_observed"] is False


def test_platform_delivery_liveness_marks_full_definition_trace_observed():
    payload = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "codex",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                }
            ],
        },
        preflight_payload={"source_refs_count": 1, "raw_items_count": 1},
        dialog_result={
            "answer_source": "evidence_bound_model_call",
            "trusted_memory_delivery_trace": {
                "status": "proven",
                "model_delivery_state": "observed",
                "cells": {
                    "passive_gate_observed": True,
                    "model_evidence_receipt_observed": True,
                    "answer_evidence_observed": True,
                    "receipt_visibility_observed": True,
                    "security_gate_observed": True,
                },
                "missing_cells": [],
                "used_source_refs": ["E1"],
            },
            "answer_debug": {
                "model_call": {"called": True, "request_sent": True, "supporting_refs": ["E1"]},
                "evidence": [{"source_refs_present": True}],
            },
            "platform_delivery": {"visible_reply_ok": True},
        },
        platforms=("codex",),
    )

    finding = payload["platforms"][0]

    assert finding["delivered_to_model"] == "observed"
    assert finding["delivered_to_user"] == "observed"
    assert finding["definition_of_proven_observed"] is True
    assert finding["definition_of_proven_missing_cells"] == []
