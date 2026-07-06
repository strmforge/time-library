import json

from tools import trusted_memory_real_memory_trace_probe as probe


def test_trusted_memory_real_memory_trace_probe_uses_temp_case_memory(monkeypatch):
    def fake_model_answer(question, evidence_items, **kwargs):
        ref = evidence_items[0]["evidence_ref"]
        source_refs = evidence_items[0].get("source_refs", {})
        assert source_refs.get("source_system") == "trusted_memory_probe"
        assert source_refs.get("source_path")
        if ref == "exp-real-trace-gap":
            return {
                "ok": True,
                "contract": "evidence_bound_model.v2026.6.18",
                "model_call_performed": True,
                "answer": "UNKNOWN",
                "verdict": "unknown",
                "confidence": 0.0,
                "supporting_refs": [],
                "evidence_count": 1,
                "unknown_reason": "remote_release_receipt_missing",
            }
        assert ref == "exp-real-trace-next"
        return {
            "ok": True,
            "contract": "evidence_bound_model.v2026.6.18",
            "model_call_performed": True,
            "answer": "先核对 NAS，再实施下一刀。",
            "verdict": "answered",
            "confidence": 0.9,
            "supporting_refs": ["exp-real-trace-next"],
            "evidence_count": 1,
            "unknown_reason": "",
        }

    original_load = probe._load_with_temp_memory

    def patched_load(memcore_root, gateway_port):
        p3, p4, proxy = original_load(memcore_root, gateway_port)
        monkeypatch.setattr(proxy, "run_evidence_bound_answer", fake_model_answer)
        return p3, p4, proxy

    monkeypatch.setattr(probe, "_load_with_temp_memory", patched_load)

    result = probe.run_probe()
    by_case = {item["case"]: item for item in result["cases"]}

    assert result["ok"] is True
    assert result["fixture_backed"] is False
    assert result["controlled_temp_memory"] is True
    assert result["user_work_records_read"] is False
    assert result["platform_action_performed"] is False
    assert result["temporary_gateway"] is True
    assert result["inserted_case_memory_count"] == 2
    assert result["loaded_memory_count"] >= 2
    assert by_case["source_backed"]["recall_count"] > 0
    assert by_case["source_backed"]["trace_status"] == "proven"
    assert by_case["source_backed"]["evidence_packet_refs"] == ["exp-real-trace-next"]
    assert by_case["source_backed"]["used_source_refs"] == ["exp-real-trace-next"]
    assert by_case["source_backed"]["receipt_status"] == "source_backed"
    assert by_case["unknown"]["recall_count"] > 0
    assert by_case["unknown"]["trace_status"] == "proven"
    assert by_case["unknown"]["evidence_packet_refs"] == ["exp-real-trace-gap"]
    assert by_case["unknown"]["answer"] == "UNKNOWN"
    assert by_case["unknown"]["used_source_refs"] == []
    assert by_case["unknown"]["receipt_status"] == "unknown"
    assert by_case["unknown"]["unknown_boundary"] is True
    json.dumps(result, ensure_ascii=False)
