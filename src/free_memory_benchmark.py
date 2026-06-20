#!/usr/bin/env python3
"""No-key benchmark suite for source-backed memory retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from .official_memory_benchmarks import (
        DEFAULT_CACHE_ROOT,
        run_official_memory_diagnostic,
    )
except ImportError:  # pragma: no cover - used by direct script execution
    from official_memory_benchmarks import (
        DEFAULT_CACHE_ROOT,
        run_official_memory_diagnostic,
    )


FREE_BENCHMARK_CONTRACT = "free_memory_benchmark_suite.v2026.6.17"
DEFAULT_FREE_RETRIEVAL_MODE = "fused_library_index_bm25"
DEFAULT_FREE_TOP_K = 5


def _score_100(value: Any) -> float:
    try:
        return round(float(value) * 100.0, 1)
    except (TypeError, ValueError):
        return 0.0


def _score_100_text(value: Any) -> str:
    return f"{_score_100(value):.1f}/100"


def _metric_row(result: dict, top_k: int) -> dict:
    row = result.get("metrics", {}).get(str(top_k), {})
    exact = row.get("exact_source_recall", row.get("source_recall", 0.0))
    bundled = row.get("bundled_source_recall", 0.0)
    near = row.get("near_source_recall", 0.0)
    answer_supported = row.get("answer_supported_recall", 0.0)
    session = row.get("session_recall", 0.0)
    gold_anchor = row.get("gold_anchor_recall", row.get("evidence_recall", 0.0))
    return {
        "exact_source_recall": exact,
        "exact_source_recall_100": _score_100(exact),
        "bundled_source_recall": bundled,
        "bundled_source_recall_100": _score_100(bundled),
        "near_source_recall": near,
        "near_source_recall_100": _score_100(near),
        "answer_supported_recall": answer_supported,
        "answer_supported_recall_100": _score_100(answer_supported),
        "session_recall": session,
        "session_recall_100": _score_100(session),
        "gold_anchor_recall": gold_anchor,
        "gold_anchor_recall_100": _score_100(gold_anchor),
        "exact_source_hits": row.get("exact_source_hits", row.get("source_hits", 0)),
        "bundled_source_hits": row.get("bundled_source_hits", 0),
        "answer_supported_hits": row.get("answer_supported_hits", 0),
        "exact_miss_answer_supported_hits": row.get("exact_miss_answer_supported_hits", 0),
        "exact_hit_answer_unsupported_hits": row.get("exact_hit_answer_unsupported_hits", 0),
        "answer_support_level_counts": row.get("answer_support_level_counts", {}),
        "gold_questions": row.get("gold_questions", 0),
    }


def _compact_result(result: dict, *, label: str, top_k: int) -> dict:
    miss = result.get("miss_classification_at_max_k", {})
    return {
        "label": label,
        "dataset": result.get("dataset"),
        "split": result.get("split"),
        "case_count": result.get("case_count", 0),
        "source_unit_count": result.get("source_unit_count", 0),
        "retrieval_mode": result.get("retrieval_mode"),
        "top_k": top_k,
        "metrics": _metric_row(result, top_k),
        "miss_classification": {
            "primary_counts": miss.get("primary_counts", {}),
            "tag_counts": miss.get("tag_counts", {}),
            "actionable_next_step_counts": miss.get("actionable_next_step_counts", {}),
        },
        "official_leaderboard_score": False,
        "no_api_key_required": True,
        "no_model_call": True,
        "no_memory_write": True,
    }


def compact_diagnostic_result(result: dict, *, label: str, top_k: int) -> dict:
    return _compact_result(result, label=label, top_k=top_k)


def run_free_memory_benchmark_suite(
    *,
    locomo_data_path: str | Path | None = None,
    longmemeval_data_path: str | Path | None = None,
    download: bool = False,
    force_download: bool = False,
    cache_root: str | Path | None = None,
    retrieval_mode: str = DEFAULT_FREE_RETRIEVAL_MODE,
    top_k: int = DEFAULT_FREE_TOP_K,
    max_conversations: int | None = None,
    max_questions: int | None = None,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    """Run LoCoMo and LongMemEval evidence retrieval diagnostics without a judge key."""

    cache_root = cache_root or DEFAULT_CACHE_ROOT
    top_k_values = [int(top_k)]
    locomo = run_official_memory_diagnostic(
        dataset="locomo",
        data_path=locomo_data_path,
        download=download,
        cache_root=cache_root,
        force_download=force_download,
        max_conversations=max_conversations,
        max_questions=max_questions,
        top_k_values=top_k_values,
        retrieval_mode=retrieval_mode,
    )
    longmemeval = run_official_memory_diagnostic(
        dataset="longmemeval",
        split="oracle",
        data_path=longmemeval_data_path,
        download=download,
        cache_root=cache_root,
        force_download=force_download,
        max_conversations=max_conversations,
        max_questions=max_questions,
        top_k_values=top_k_values,
        retrieval_mode=retrieval_mode,
    )
    results = [
        _compact_result(locomo, label="LoCoMo locomo10", top_k=int(top_k)),
        _compact_result(longmemeval, label="LongMemEval oracle", top_k=int(top_k)),
    ]
    payload = {
        "ok": True,
        "contract": FREE_BENCHMARK_CONTRACT,
        "mode": "free_retrieval_benchmark_suite",
        "retrieval_mode": retrieval_mode,
        "top_k": int(top_k),
        "benchmark_count": len(results),
        "results": results,
        "boundary": {
            "no_api_key_required": True,
            "no_model_call": True,
            "no_memory_write": True,
            "official_leaderboard_score": False,
            "score_type": "evidence_retrieval_diagnostic",
            "not_final_qa_accuracy": True,
            "not_gpt4o_judge": True,
        },
        "notes": [
            "free_reproducible_retrieval_benchmark",
            "uses_public_benchmark_data",
            "does_not_call_openai_or_other_judge_model",
            "does_not_claim_official_leaderboard_score",
        ],
    }
    if include_diagnostics:
        payload["diagnostics"] = {
            "locomo": locomo,
            "longmemeval": longmemeval,
        }
    return payload


def compact_suite_summary(payload: dict) -> dict:
    """Return the stable public summary shape for CLI JSON output."""

    return {
        "ok": payload.get("ok", False),
        "contract": payload.get("contract"),
        "mode": payload.get("mode"),
        "retrieval_mode": payload.get("retrieval_mode"),
        "top_k": payload.get("top_k"),
        "benchmark_count": payload.get("benchmark_count"),
        "boundary": payload.get("boundary", {}),
        "results": payload.get("results", []),
        "notes": payload.get("notes", []),
    }


def render_free_benchmark_markdown(payload: dict) -> str:
    lines = [
        "# Memcore Cloud Free Benchmark",
        "",
        f"status: {'ok' if payload.get('ok') else 'attention'}",
        f"contract: {payload.get('contract', '')}",
        f"retrieval_mode: {payload.get('retrieval_mode', '')}",
        f"top_k: {payload.get('top_k', '')}",
        "",
        "## Boundary",
        "- no_api_key_required: true",
        "- no_model_call: true",
        "- no_memory_write: true",
        "- official_leaderboard_score: false",
        "- score_type: evidence_retrieval_diagnostic",
        "",
        "## Results",
        "| dataset | cases | exact source recall | bundled source recall | session / gold anchor recall |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in payload.get("results", []):
        metrics = item.get("metrics", {})
        exact = metrics.get("exact_source_recall", 0.0)
        bundled = metrics.get("bundled_source_recall", 0.0)
        anchor = metrics.get("gold_anchor_recall", metrics.get("session_recall", 0.0))
        lines.append(
            "| {label} | {cases} | {exact} | {bundled} | {anchor} |".format(
                label=item.get("label", ""),
                cases=item.get("case_count", 0),
                exact=_score_100_text(exact),
                bundled=_score_100_text(bundled),
                anchor=_score_100_text(anchor),
            )
        )
    lines.extend(
        [
            "",
            "This is a no-key evidence retrieval benchmark on public data. It is not a LoCoMo or LongMemEval official leaderboard score.",
        ]
    )
    return "\n".join(lines) + "\n"


def dumps_summary(payload: dict) -> str:
    return json.dumps(compact_suite_summary(payload), ensure_ascii=False, indent=2, sort_keys=True)
