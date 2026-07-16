from src import time_library_delivery_runtime as delivery_runtime
from src.platform_delivery_liveness import (
    PLATFORM_DELIVERY_LIVENESS_CONTRACT,
    build_platform_delivery_liveness_audit,
)


def _context(tmp_path, platform):
    context = {
        "transport_session_id": f"liveness:{tmp_path}:{platform}",
        "initialized": True,
        "client_info_present": True,
        "client_name": f"{platform} host",
        "client_version": "1",
        "inferred_platform_hint": "unknown_mcp_client",
    }
    receipt = delivery_runtime.record_verified_host_connection(
        context,
        {
            "ok": True,
            "self_report_verified": True,
            "client_info": {"self_reported_platform": platform},
            "real_recall_proof": {"library_id": "ZX-LIVE", "source_refs_count": 1},
            "borrowing_card_receipt": {"card_id": f"card-{platform}"},
        },
        memcore_root=tmp_path,
    )
    assert receipt["ok"] is True
    return context


def _recall_result():
    return {
        "ok": True,
        "matched_count": 1,
        "items": [
            {
                "library_id": "ZX-LIVE",
                "source_system": "local_files",
                "source_path": "raw/public-safe-proof.jsonl",
            }
        ],
    }


def _tracked(tmp_path, platform, *, delivery_form="context"):
    context = _context(tmp_path, platform)
    result = delivery_runtime.instrument_recall_result(
        _recall_result(),
        {"consumer": platform, "query": "proof", "delivery_form": delivery_form},
        memcore_root=tmp_path,
        connection_context=context,
    )
    return result, context


def _ack(tmp_path, context, challenge, *, wrong=False):
    return delivery_runtime.acknowledge_delivery(
        {
            "challenge_id": challenge["challenge_id"],
            "challenge": "wrong" if wrong else challenge["challenge"],
            "retrieval_id": challenge["retrieval_id"],
            "platform": challenge["platform"],
            "request_id": "host-model-request",
            "used_source_refs": challenge["selected_source_refs"],
            "response_evidence_ref": "host-model-response",
        },
        memcore_root=tmp_path,
        connection_context=context,
    )


def test_platform_delivery_liveness_is_findings_only_and_does_not_promote_discovery(tmp_path):
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
                },
            ],
        },
        preflight_payload={"source_refs_count": 99, "raw_items_count": 99},
        platforms=("openclaw", "hermes"),
        memcore_root=tmp_path,
    )

    assert payload["contract"] == PLATFORM_DELIVERY_LIVENESS_CONTRACT
    assert payload["read_only"] is True
    assert payload["findings_only"] is True
    assert payload["write_performed"] is False
    assert payload["not_a_delivery_mechanism"] is True
    assert payload["counts"]["platforms_with_source_refs_visible"] == 0
    assert payload["counts"]["platforms_with_model_delivery_observed"] == 0
    assert all(item["self_report_verified"] is False for item in payload["platforms"])
    assert all("verified_self_report_receipt_missing" in item["risk"] for item in payload["platforms"])


def test_platform_delivery_liveness_infers_dynamic_platforms_without_a_default_matrix(tmp_path):
    payload = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {"system": "first_host", "status": "active", "connectable_now": True},
                {"system": "second_host", "status": "detected", "intent_signal_detected": True},
                {"system": "time_library", "status": "active", "is_time_library_service": True},
                {"system": "unused", "status": "not_found"},
            ]
        },
        memcore_root=tmp_path,
    )

    assert [item["platform"] for item in payload["platforms"]] == ["first_host", "second_host"]
    empty = build_platform_delivery_liveness_audit(
        autodiscovery_payload={},
        observed_platforms={},
        memcore_root=tmp_path / "empty",
    )
    assert empty["platforms"] == []


def test_caller_supplied_green_booleans_cannot_forge_liveness(tmp_path):
    payload = build_platform_delivery_liveness_audit(
        observed_platforms={
            "future_xyz": {
                "self_report_verified": True,
                "source_refs_visible": True,
                "delivered_to_model": "observed",
                "delivered_to_user": "observed",
            }
        },
        preflight_payload={"source_refs_count": 50},
        memcore_root=tmp_path,
    )

    finding = payload["platforms"][0]
    assert finding["self_report_verified"] is False
    assert finding["source_refs_visible"] is False
    assert finding["delivered_to_model"] == "not_measured"
    assert finding["delivered_to_user"] == "not_measured"
    assert finding["untrusted_caller_claims"]["self_report_verified"] is True


def test_persisted_self_report_receipt_admits_an_unknown_host(tmp_path):
    _context(tmp_path, "future_xyz")

    payload = build_platform_delivery_liveness_audit(memcore_root=tmp_path)

    assert [item["platform"] for item in payload["platforms"]] == ["future_xyz"]
    finding = payload["platforms"][0]
    assert finding["self_report_verified"] is True
    assert finding["passive_state"] == "connection_ready"
    assert finding["delivered_to_model"] == "not_measured"


def test_dialog_claims_and_local_fallback_remain_risks_not_delivery_proof(tmp_path):
    payload = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [{"system": "some_host", "status": "active", "connectable_now": True}]
        },
        dialog_result={
            "answer": "local fallback",
            "answer_source": "zhiyi_direct_natural_fallback_after_model_no_answer",
            "model_call": {"called": True, "request_sent": True},
            "platform_delivery": {"visible_reply_ok": True},
            "trusted_memory_delivery_trace": {
                "status": "proven",
                "model_delivery_state": "observed",
            },
        },
        platforms=("some_host",),
        memcore_root=tmp_path,
    )

    finding = payload["platforms"][0]
    assert finding["answer_owner"] == "zhiyi_direct_natural_fallback_after_model_no_answer"
    assert finding["local_draft_detected"] is True
    assert finding["delivered_to_model"] == "not_measured"
    assert "local_draft_or_fallback_answer_detected" in finding["risk"]


def test_append_only_runtime_recomputes_partial_definition_of_proven(tmp_path):
    tracked, context = _tracked(tmp_path, "future_xyz")
    assert _ack(tmp_path, context, tracked["delivery_runtime"]["challenge"])["ok"] is True

    payload = build_platform_delivery_liveness_audit(memcore_root=tmp_path)
    finding = payload["platforms"][0]

    assert finding["delivered_to_model"] == "observed"
    assert finding["source_refs_visible"] is True
    assert finding["definition_of_proven_observed"] is False
    assert set(finding["definition_of_proven_missing_cells"]) == {
        "passive_gate_observed",
        "security_gate_observed",
    }


def test_append_only_runtime_recomputes_full_definition_of_proven(tmp_path):
    tracked, context = _tracked(tmp_path, "future_xyz")
    assert _ack(tmp_path, context, tracked["delivery_runtime"]["challenge"])["ok"] is True
    _tracked(tmp_path, "future_xyz", delivery_form="silent")
    attacked, attack_context = _tracked(tmp_path, "future_xyz")
    assert _ack(
        tmp_path,
        attack_context,
        attacked["delivery_runtime"]["challenge"],
        wrong=True,
    )["ok"] is False

    payload = build_platform_delivery_liveness_audit(memcore_root=tmp_path)
    finding = payload["platforms"][0]

    assert finding["delivered_to_model"] == "observed"
    assert finding["delivered_to_user"] == "not_measured"
    assert finding["definition_of_proven_observed"] is True
    assert finding["definition_of_proven_missing_cells"] == []
