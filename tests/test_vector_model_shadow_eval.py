from tools.vector_model_shadow_eval import build_query_set, gate_reports


def _memory(index, *, text="中文记忆内容", kind="case_memory", extracted_at="2026-07-10"):
    if any("a" <= char.lower() <= "z" for char in text):
        summary = f"{text} summary {index} with enough text for a real retrieval query"
        detail = f"{text} detail {index} with source-backed context and enough content"
    else:
        summary = f"{text}摘要第{index}条，包含足够完整的真实召回查询内容"
        detail = f"{text}详情第{index}条，包含可回源上下文和足够长度的正文内容"
    return {
        "exp_id": f"exp-{index}",
        "type": kind,
        "summary": summary,
        "detail": detail,
        "source_refs": {"source_path": f"/raw/{index}.jsonl"},
        "extracted_at": extracted_at,
    }


def test_query_set_is_deterministic_and_keeps_non_chinese_cases():
    memories = [_memory(index) for index in range(20)]
    memories.extend(_memory(100 + index, text="English retrieval memory") for index in range(8))
    first = build_query_set(memories, query_count=16, seed=7)
    second = build_query_set(memories, query_count=16, seed=7)
    assert first == second
    assert len(first) == 16
    assert {item["language_bucket"] for item in first} >= {"cjk", "latin"}
    assert len({item["expected_exp_id"] for item in first}) == 16


def _report(*, top1=0.9, top5=0.98, mrr=0.94, p50=1.0, p95=1.2, fresh=1.5):
    return {
        "retrieval": {
            "top1_rate": top1,
            "top5_rate": top5,
            "mrr": mrr,
            "recent_top1_rate": top1,
        },
        "latency": {
            "single_query_encode_p50_seconds": p50,
            "single_query_encode_p95_seconds": p95,
        },
        "freshness": {"visible_top5": True, "encode_to_visible_seconds": fresh},
        "source_refs_parity": {"exact": True},
        "corpus_signature": "same-corpus",
        "source_refs_signature": "same-refs",
        "python": "3.9.6",
        "storage": "LanceDB",
    }


def test_gate_requires_candidate_not_worse_on_every_axis():
    baseline = _report()
    passing = _report(top1=0.91, top5=0.99, mrr=0.95, p50=0.4, p95=0.5, fresh=0.8)
    assert gate_reports(baseline, passing)["passed"] is True

    slower = _report(top1=0.91, top5=0.99, mrr=0.95, p50=1.1, p95=1.3, fresh=0.8)
    result = gate_reports(baseline, slower)
    assert result["passed"] is False
    assert result["decision"] == "keep_baseline_default"
    assert result["checks"]["single_query_p50_not_slower"] is False
