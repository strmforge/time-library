#!/usr/bin/env python3
"""Compare baseline and fast evidence-bound model matrix summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MODEL_MATRIX_COMPARE_CONTRACT = "model_matrix_compare.v2026.6.19"


def _load_summary(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    if source.is_dir():
        source = source / "summary.json"
    return json.loads(source.read_text(encoding="utf-8"))


def _first_result(summary: dict[str, Any]) -> dict[str, Any]:
    results = summary.get("results") if isinstance(summary.get("results"), list) else []
    return results[0] if results and isinstance(results[0], dict) else {}


def _pct_change(new_value: float, old_value: float) -> float | None:
    if not old_value:
        return None
    return round((new_value - old_value) / old_value, 4)


def _int_metric(row: dict[str, Any], key: str) -> int:
    try:
        return int(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _float_metric(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _decision_counts(row: dict[str, Any]) -> dict[str, int]:
    value = row.get("decision_counts")
    if not isinstance(value, dict):
        return {}
    return {str(key): int(count or 0) for key, count in value.items()}


def _metrics(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metrics")
    return value if isinstance(value, dict) else {}


def _rows_by_question(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = row.get("rows") if isinstance(row.get("rows"), list) else []
    mapped: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("question_id") or "").strip()
        if qid:
            mapped[qid] = item
    return mapped


def _decision_drift(baseline: dict[str, Any], fast: dict[str, Any], *, example_limit: int = 8) -> dict[str, Any]:
    baseline_rows = _rows_by_question(baseline)
    fast_rows = _rows_by_question(fast)
    shared = sorted(set(baseline_rows) & set(fast_rows))
    drift_examples: list[dict[str, Any]] = []
    drift_count = 0
    model_class_drift_count = 0
    careful_added_count = 0
    careful_removed_count = 0
    for qid in shared:
        before = baseline_rows[qid]
        after = fast_rows[qid]
        decision_changed = str(before.get("decision") or "") != str(after.get("decision") or "")
        class_changed = str(before.get("model_class") or "") != str(after.get("model_class") or "")
        careful_before = bool(before.get("needs_careful_mode"))
        careful_after = bool(after.get("needs_careful_mode"))
        drift_count += int(decision_changed)
        model_class_drift_count += int(class_changed)
        careful_added_count += int(careful_after and not careful_before)
        careful_removed_count += int(careful_before and not careful_after)
        if (decision_changed or class_changed or careful_before != careful_after) and len(drift_examples) < example_limit:
            drift_examples.append(
                {
                    "question_id": qid,
                    "baseline_decision": before.get("decision", ""),
                    "fast_decision": after.get("decision", ""),
                    "baseline_model_class": before.get("model_class", ""),
                    "fast_model_class": after.get("model_class", ""),
                    "baseline_careful": careful_before,
                    "fast_careful": careful_after,
                    "question": str(after.get("question") or before.get("question") or "")[:220],
                }
            )
    return {
        "row_level_available": bool(shared),
        "shared_question_count": len(shared),
        "decision_drift_count": drift_count,
        "model_class_drift_count": model_class_drift_count,
        "careful_added_count": careful_added_count,
        "careful_removed_count": careful_removed_count,
        "examples": drift_examples,
    }


def compare_model_matrix_summaries(
    baseline_summary_path: str | Path,
    fast_summary_path: str | Path,
    *,
    example_limit: int = 8,
) -> dict[str, Any]:
    baseline_summary = _load_summary(baseline_summary_path)
    fast_summary = _load_summary(fast_summary_path)
    baseline = _first_result(baseline_summary)
    fast = _first_result(fast_summary)
    baseline_metrics = _metrics(baseline)
    fast_metrics = _metrics(fast)
    baseline_calls = _int_metric(baseline, "model_call_count")
    fast_calls = _int_metric(fast, "model_call_count")
    baseline_elapsed = _float_metric(baseline, "elapsed_seconds")
    fast_elapsed = _float_metric(fast, "elapsed_seconds")
    baseline_cpu = _float_metric(baseline, "local_cpu_seconds")
    fast_cpu = _float_metric(fast, "local_cpu_seconds")
    baseline_rss = _float_metric(baseline, "max_rss_mb")
    fast_rss = _float_metric(fast, "max_rss_mb")
    baseline_errors = _int_metric(baseline, "model_error_count")
    fast_errors = _int_metric(fast, "model_error_count")
    decision_drift = _decision_drift(baseline, fast, example_limit=example_limit)
    risk_flags: list[str] = []
    if fast_errors > baseline_errors:
        risk_flags.append("fast_model_errors_increased")
    if int(fast_metrics.get("careful_requested_total") or 0) > int(baseline_metrics.get("careful_requested_total") or 0):
        risk_flags.append("fast_careful_requests_increased")
    if _decision_counts(fast).get("stop_no_support", 0) > _decision_counts(baseline).get("stop_no_support", 0):
        risk_flags.append("fast_stop_no_support_increased")
    if int(fast_metrics.get("trigger_candidate_no_support") or 0) > int(baseline_metrics.get("trigger_candidate_no_support") or 0):
        risk_flags.append("fast_triggered_unsupported_candidate")
    if decision_drift.get("decision_drift_count"):
        risk_flags.append("row_level_decision_drift_observed")

    return {
        "ok": True,
        "contract": MODEL_MATRIX_COMPARE_CONTRACT,
        "baseline_path": str(Path(baseline_summary_path).expanduser()),
        "fast_path": str(Path(fast_summary_path).expanduser()),
        "dataset": baseline_summary.get("dataset") or fast_summary.get("dataset", ""),
        "model": fast.get("model") or baseline.get("model", ""),
        "provider": fast.get("provider") or baseline.get("provider", ""),
        "case_count": fast.get("selected_case_count") or baseline.get("selected_case_count") or 0,
        "fast_mode_claimed": bool(fast.get("fast_mode") or fast_summary.get("fast_mode")),
        "baseline": {
            "model_call_count": baseline_calls,
            "elapsed_seconds": baseline_elapsed,
            "local_cpu_seconds": baseline_cpu,
            "max_rss_mb": baseline_rss,
            "model_error_count": baseline_errors,
            "decision_counts": _decision_counts(baseline),
            "metrics": baseline_metrics,
            "model_by_decision": baseline.get("model_by_decision", {}),
        },
        "fast": {
            "model_call_count": fast_calls,
            "elapsed_seconds": fast_elapsed,
            "local_cpu_seconds": fast_cpu,
            "max_rss_mb": fast_rss,
            "model_error_count": fast_errors,
            "decision_counts": _decision_counts(fast),
            "metrics": fast_metrics,
            "model_by_decision": fast.get("model_by_decision", {}),
        },
        "delta": {
            "model_call_count": fast_calls - baseline_calls,
            "model_call_count_pct": _pct_change(fast_calls, baseline_calls),
            "elapsed_seconds": round(fast_elapsed - baseline_elapsed, 3),
            "elapsed_seconds_pct": _pct_change(fast_elapsed, baseline_elapsed),
            "local_cpu_seconds": round(fast_cpu - baseline_cpu, 3),
            "local_cpu_seconds_pct": _pct_change(fast_cpu, baseline_cpu),
            "max_rss_mb": round(fast_rss - baseline_rss, 2),
            "model_error_count": fast_errors - baseline_errors,
        },
        "decision_drift": decision_drift,
        "risk_flags": risk_flags,
        "boundary": {
            "official_leaderboard_score": False,
            "diagnostic_only": True,
            "secret_values_returned": False,
            "no_memory_write": True,
            "ranking_changed": False,
        },
    }


def _pct_text(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def render_model_matrix_compare_markdown(report: dict[str, Any]) -> str:
    baseline = report.get("baseline", {}) if isinstance(report.get("baseline"), dict) else {}
    fast = report.get("fast", {}) if isinstance(report.get("fast"), dict) else {}
    delta = report.get("delta", {}) if isinstance(report.get("delta"), dict) else {}
    drift = report.get("decision_drift", {}) if isinstance(report.get("decision_drift"), dict) else {}
    lines = [
        "# Evidence-Bound Fast Mode Compare",
        "",
        f"- contract: {report.get('contract', '')}",
        f"- dataset: {report.get('dataset', '')}",
        f"- model: {report.get('provider', '')} / {report.get('model', '')}",
        f"- cases: {report.get('case_count', 0)}",
        "- official_leaderboard_score: false",
        "- diagnostic: daily usability, not benchmark publication",
        "",
        "| Metric | Baseline top+pack two calls | Fast top+pack one call | Change |",
        "|---|---:|---:|---:|",
        f"| model calls | {baseline.get('model_call_count', 0)} | {fast.get('model_call_count', 0)} | {delta.get('model_call_count', 0)} ({_pct_text(delta.get('model_call_count_pct'))}) |",
        f"| elapsed | {baseline.get('elapsed_seconds', 0)}s | {fast.get('elapsed_seconds', 0)}s | {delta.get('elapsed_seconds', 0)}s ({_pct_text(delta.get('elapsed_seconds_pct'))}) |",
        f"| local CPU | {baseline.get('local_cpu_seconds', 0)}s | {fast.get('local_cpu_seconds', 0)}s | {delta.get('local_cpu_seconds', 0)}s ({_pct_text(delta.get('local_cpu_seconds_pct'))}) |",
        f"| RSS | {baseline.get('max_rss_mb', 0)} MB | {fast.get('max_rss_mb', 0)} MB | {delta.get('max_rss_mb', 0)} MB |",
        f"| errors | {baseline.get('model_error_count', 0)} | {fast.get('model_error_count', 0)} | {delta.get('model_error_count', 0)} |",
        "",
        "## Decision Shape",
        "",
        "| Path | Decisions | Careful requested |",
        "|---|---|---:|",
        f"| baseline | `{json.dumps(baseline.get('decision_counts', {}), ensure_ascii=False, sort_keys=True)}` | {baseline.get('metrics', {}).get('careful_requested_total', 0)} |",
        f"| fast mode | `{json.dumps(fast.get('decision_counts', {}), ensure_ascii=False, sort_keys=True)}` | {fast.get('metrics', {}).get('careful_requested_total', 0)} |",
        "",
        "## Drift",
        "",
        f"- row_level_available: {str(bool(drift.get('row_level_available'))).lower()}",
        f"- shared_question_count: {drift.get('shared_question_count', 0)}",
        f"- decision_drift_count: {drift.get('decision_drift_count', 0)}",
        f"- model_class_drift_count: {drift.get('model_class_drift_count', 0)}",
        f"- careful_added_count: {drift.get('careful_added_count', 0)}",
        f"- risk_flags: `{json.dumps(report.get('risk_flags', []), ensure_ascii=False)}`",
    ]
    examples = drift.get("examples") if isinstance(drift.get("examples"), list) else []
    if examples:
        lines.extend(["", "### Drift Examples", ""])
        for item in examples:
            lines.append(
                "- {qid}: {before} -> {after}; class {before_class} -> {after_class}".format(
                    qid=item.get("question_id", ""),
                    before=item.get("baseline_decision", ""),
                    after=item.get("fast_decision", ""),
                    before_class=item.get("baseline_model_class", ""),
                    after_class=item.get("fast_model_class", ""),
                )
            )
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- This is not an official LoCoMO or LongMemEval score.",
            "- Reports do not serialize API key values.",
            "- Fast mode should not become the daily default until drift is calibrated on wider samples and slower user-selected models.",
        ]
    )
    return "\n".join(lines) + "\n"
