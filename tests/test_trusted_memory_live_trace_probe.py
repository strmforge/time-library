import json

from tools import trusted_memory_live_trace_probe as probe


def test_trusted_memory_live_trace_probe_covers_source_backed_and_unknown(monkeypatch):
    def fake_model_answer(question, evidence_items, **kwargs):
        ref = evidence_items[0]["evidence_ref"]
        if ref == "exp-live-trace-gap":
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
        return {
            "ok": True,
            "contract": "evidence_bound_model.v2026.6.18",
            "model_call_performed": True,
            "answer": "先核对 NAS，再实施下一刀。",
            "verdict": "answered",
            "confidence": 0.9,
            "supporting_refs": ["exp-live-trace-next"],
            "evidence_count": 1,
            "unknown_reason": "",
        }

    original_reload = probe._reload_dialog

    def patched_reload(memcore_root):
        proxy = original_reload(memcore_root)
        monkeypatch.setattr(proxy, "run_evidence_bound_answer", fake_model_answer)
        return proxy

    monkeypatch.setattr(probe, "_reload_dialog", patched_reload)

    result = probe.run_probe()
    by_case = {item["case"]: item for item in result["cases"]}

    assert result["ok"] is True
    assert result["fixture_backed"] is True
    assert result["user_work_records_read"] is False
    assert result["platform_action_performed"] is False
    assert by_case["source_backed"]["trace_status"] == "proven"
    assert by_case["source_backed"]["used_source_refs"] == ["exp-live-trace-next"]
    assert by_case["source_backed"]["receipt_status"] == "source_backed"
    assert by_case["unknown"]["trace_status"] == "proven"
    assert by_case["unknown"]["answer"] == "UNKNOWN"
    assert by_case["unknown"]["used_source_refs"] == []
    assert by_case["unknown"]["receipt_status"] == "unknown"
    assert by_case["unknown"]["unknown_boundary"] is True
    json.dumps(result, ensure_ascii=False)
