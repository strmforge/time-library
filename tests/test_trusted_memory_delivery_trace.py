from src.trusted_memory_delivery_trace import (
    TRUSTED_MEMORY_DELIVERY_TRACE_CONTRACT,
    build_trusted_memory_delivery_artifacts,
)


def _dialog_result():
    return {
        "status": "ok",
        "chain": "F3_zhiyi_direct",
        "answer": "先核对 NAS，再实施下一刀。",
        "answer_source": "evidence_bound_model_call",
        "used_source_refs": ["exp-next"],
        "source_refs": [{"source_system": "nas", "source_path": "/tmp/nas.jsonl"}],
        "model_call": {
            "called": True,
            "request_sent": True,
            "supporting_refs": ["exp-next"],
            "used_source_refs": ["exp-next"],
            "evidence_packet_refs": ["exp-next"],
            "evidence_count": 1,
        },
        "platform_delivery": {
            "delivery_method": "before_dispatch_return",
            "visible_reply_ok": True,
            "write_performed": False,
        },
    }


def _observations():
    return {
        "passive_gate_result": {
            "handled": False,
            "text": "",
            "reason": "openclaw_before_dispatch_requires_explicit_zhiyi_entry",
        },
        "security_gate": {
            "observed": True,
            "source": "tests/test_security_boundaries.py",
            "tests": ["test_openclaw_before_dispatch_does_not_handle_ordinary_chat"],
        },
    }


def test_trusted_memory_delivery_trace_requires_all_five_cells():
    artifacts = build_trusted_memory_delivery_artifacts(
        platform="openclaw",
        question="下一步是什么？",
        dialog_result=_dialog_result(),
        observations=_observations(),
    )

    trace = artifacts["trusted_memory_delivery_trace"]

    assert trace["contract"] == TRUSTED_MEMORY_DELIVERY_TRACE_CONTRACT
    assert trace["status"] == "proven"
    assert trace["model_delivery_state"] == "observed"
    assert trace["delivered_to_model"] == "observed"
    assert trace["cells"]["passive_gate_observed"] is True
    assert trace["cells"]["model_evidence_receipt_observed"] is True
    assert trace["cells"]["answer_evidence_observed"] is True
    assert trace["cells"]["receipt_visibility_observed"] is True
    assert trace["cells"]["security_gate_observed"] is True
    assert trace["missing_cells"] == []
    assert trace["used_source_refs"] == ["exp-next"]
    assert trace["evidence_packet_refs"] == ["exp-next"]
    assert artifacts["think_validation"]["ok"] is True
    assert artifacts["delivery_receipt_view"]["status"] == "source_backed"


def test_trusted_memory_delivery_trace_keeps_model_not_measured_unproven():
    dialog = _dialog_result()
    dialog["model_call"] = {"called": False, "request_sent": False, "evidence_count": 1}

    artifacts = build_trusted_memory_delivery_artifacts(
        platform="openclaw",
        question="下一步是什么？",
        dialog_result=dialog,
        observations=_observations(),
    )
    trace = artifacts["trusted_memory_delivery_trace"]

    assert trace["status"] == "unproven"
    assert trace["model_delivery_state"] == "not_measured"
    assert trace["cell_states"]["model_evidence_receipt_observed"] == "not_measured"
    assert "model_evidence_receipt_observed" in trace["missing_cells"]


def test_trusted_memory_delivery_trace_does_not_prove_without_security_gate():
    artifacts = build_trusted_memory_delivery_artifacts(
        platform="openclaw",
        question="下一步是什么？",
        dialog_result=_dialog_result(),
        observations={
            "passive_gate_result": {
                "handled": False,
                "text": "",
                "reason": "openclaw_before_dispatch_requires_explicit_zhiyi_entry",
            }
        },
    )
    trace = artifacts["trusted_memory_delivery_trace"]

    assert trace["status"] == "unproven"
    assert trace["model_delivery_state"] == "observed"
    assert "security_gate_observed" in trace["missing_cells"]


def test_trusted_memory_delivery_trace_does_not_prove_when_passive_gate_handles_chat():
    observations = _observations()
    observations["passive_gate_result"] = {
        "handled": True,
        "text": "ordinary chat was intercepted",
        "reason": "ordinary_chat_was_handled",
    }

    artifacts = build_trusted_memory_delivery_artifacts(
        platform="openclaw",
        question="普通聊天",
        dialog_result=_dialog_result(),
        observations=observations,
    )
    trace = artifacts["trusted_memory_delivery_trace"]

    assert trace["status"] == "unproven"
    assert trace["cell_states"]["passive_gate_observed"] == "failed"
    assert "passive_gate_observed" in trace["missing_cells"]


def test_trusted_memory_delivery_trace_accepts_unknown_answer_boundary_when_observed():
    dialog = _dialog_result()
    dialog["answer"] = "UNKNOWN"

    artifacts = build_trusted_memory_delivery_artifacts(
        platform="openclaw",
        question="远端发布了吗？",
        dialog_result=dialog,
        observations=_observations(),
    )
    trace = artifacts["trusted_memory_delivery_trace"]

    assert trace["status"] == "proven"
    assert trace["unknown_boundary"] is True
    assert artifacts["delivery_receipt_view"]["status"] == "unknown"
