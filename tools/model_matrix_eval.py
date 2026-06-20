#!/usr/bin/env python3
"""Run an evidence-bound model matrix without printing or storing secrets."""

from __future__ import annotations

import argparse
import json
import os
import re
import resource
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_bootstrap import ensure_repo_import_paths  # noqa: E402

ROOT = ensure_repo_import_paths(__file__)

from eval_miss_report import (  # noqa: E402
    _calibration_model_class,
    _evidence_items_for_refs,
    _neighbor_refs_for_top_result,
    _ordered_unique_refs,
    _runtime_candidate_policy,
    _runtime_probe_verdict,
    _source_order_index,
    run_evidence_bound_answer,
)
from evidence_bound_model import run_evidence_bound_fast_audit  # noqa: E402
from official_memory_benchmarks import load_cases, rank_source_units  # noqa: E402


MODEL_MATRIX_SCHEMA = "model_matrix_eval.v2026.6.19"


def _split_models(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[、,，]", str(value or "")) if part.strip()]


def _provider_from_base_url(base_url: str) -> str:
    value = str(base_url or "").lower()
    if "minimax" in value:
        return "minimax"
    if "deepseek" in value:
        return "deepseek"
    if "mimo" in value or "xiaomi" in value:
        return "mimo"
    return "openai_compatible"


def parse_model_file(path: str | Path) -> list[dict[str, Any]]:
    """Parse the user's private model test file.

    The file is treated as secret-bearing input. Returned rows keep the key in
    memory for this process, but report renderers must not serialize it.
    """
    source = Path(path).expanduser()
    text = source.read_text(encoding="utf-8", errors="ignore")
    raw_lines = [line.strip() for line in text.splitlines()]
    blocks: list[dict[str, Any]] = []
    for index, line in enumerate(raw_lines):
        if not line.startswith("http"):
            continue
        key = ""
        for previous in range(index - 1, -1, -1):
            candidate = raw_lines[previous].strip()
            if candidate:
                key = candidate
                break
        model_line = ""
        for following in range(index + 1, min(len(raw_lines), index + 8)):
            candidate = raw_lines[following].strip()
            if not candidate or candidate == "模型":
                continue
            model_line = candidate
            break
        models = _split_models(model_line)
        if not key or not models:
            continue
        provider = _provider_from_base_url(line)
        blocks.append(
            {
                "provider": provider,
                "base_url": line.rstrip("/"),
                "api_key": key,
                "api_key_present": True,
                "models": models,
            }
        )
    return blocks


def safe_model_inventory(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "provider": str(block.get("provider") or ""),
            "base_url": str(block.get("base_url") or ""),
            "api_key_present": bool(block.get("api_key")),
            "models": list(block.get("models") or []),
        }
        for block in blocks
    ]


def _rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    value = float(usage.ru_maxrss)
    if sys.platform == "darwin":
        return round(value / (1024 * 1024), 2)
    return round(value / 1024, 2)


def _cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return round(float(usage.ru_utime + usage.ru_stime), 3)


def _safe_error(error: Any) -> str:
    text = str(error or "")
    text = re.sub(r"(?i)(api[_-]?key|token|secret|authorization|bearer)[^,\n}]*", r"\1:<redacted>", text)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-<redacted>", text)
    text = re.sub(r"[A-Za-z0-9_-]{32,}", "<long-value-redacted>", text)
    return text[:500]


def build_light_candidates(
    cases: list[dict[str, Any]],
    *,
    focus_top_k: int,
    max_cases: int,
    pack_window: int = 2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.time()
    started_cpu = _cpu_seconds()
    candidates: list[dict[str, Any]] = []
    for case in cases:
        question = str(case.get("question") or "")
        source_units = case.get("source_units") if isinstance(case.get("source_units"), list) else []
        if not question or not source_units:
            continue
        ranked = rank_source_units(question, source_units, top_k=max(int(focus_top_k), 1), retrieval_mode="bm25")
        order_index, ref_sessions = _source_order_index(case)
        top_refs: list[str] = []
        pack_ref_candidates: list[str] = []
        for item in ranked[: max(int(focus_top_k), 1)]:
            ref = str(item.get("evidence_ref") or item.get("source_id") or "")
            if ref:
                top_refs.append(ref)
            synthetic = dict(item)
            synthetic["context_window"] = max(int(pack_window), int(synthetic.get("context_window") or 0))
            pack_ref_candidates.extend(
                _neighbor_refs_for_top_result(case, synthetic, order_index, ref_sessions)
            )
        pack_refs = _ordered_unique_refs(pack_ref_candidates, order_index)
        if not top_refs and not pack_refs:
            continue
        candidates.append(
            {
                "question_id": str(case.get("question_id") or ""),
                "question": question,
                "answer": str(case.get("answer") or ""),
                "top_refs": top_refs,
                "pack_refs": pack_refs,
                "top_evidence": _evidence_items_for_refs(case, top_refs, max_items=8),
                "pack_evidence": _evidence_items_for_refs(case, pack_refs, max_items=12),
                "pack_size": len(pack_refs),
            }
        )
        if max_cases is not None and int(max_cases) >= 0 and len(candidates) >= int(max_cases):
            break
    ledger = {
        "elapsed_seconds": round(time.time() - started, 3),
        "local_cpu_seconds": round(_cpu_seconds() - started_cpu, 3),
        "max_rss_mb": _rss_mb(),
        "candidate_count": len(candidates),
        "candidate_builder": "light_bm25_top_refs_plus_neighbor_pack",
    }
    return candidates, ledger


def _answered_state(model_result: dict[str, Any]) -> str:
    verdict = str(model_result.get("verdict") or "").lower()
    answer = str(model_result.get("answer") or "").strip().upper()
    refs = model_result.get("supporting_refs") if isinstance(model_result.get("supporting_refs"), list) else []
    if verdict == "dry_run":
        return "dry_run"
    if verdict == "answered" and answer != "UNKNOWN" and refs:
        return "answered"
    return "not_answered"


def _unknown_bucket(reason: Any) -> str:
    text = str(reason or "").lower()
    if not text:
        return "none"
    if "insufficient" in text or "no evidence" in text:
        return "insufficient_evidence"
    if "contradict" in text or "negat" in text:
        return "contradiction_or_negation"
    if "subject" in text or "object" in text or "mismatch" in text:
        return "subject_or_object_mismatch"
    return "other"


def _density(result: dict[str, Any], pack_size: int) -> float:
    refs = result.get("supporting_refs") if isinstance(result.get("supporting_refs"), list) else []
    if pack_size <= 0:
        return 0.0
    return round(len(refs) / pack_size, 4)


def _fast_audit_probe_verdict(result: dict[str, Any]) -> str:
    if result.get("verdict") == "dry_run":
        return "dry_run"
    if result.get("ok") is False:
        return "model_error"
    top_supported = str(result.get("top_verdict") or "").lower() == "answered" and bool(result.get("top_supporting_refs"))
    pack_supported = str(result.get("pack_verdict") or "").lower() == "answered" and bool(result.get("pack_supporting_refs"))
    if pack_supported and not top_supported:
        return "pack_model_improved"
    if pack_supported and top_supported:
        return "both_model_supported"
    if top_supported and not pack_supported:
        return "top_model_only"
    return "model_no_support"


def run_model_on_candidates(
    candidates: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    example_limit: int,
    fast_mode: bool = False,
) -> dict[str, Any]:
    decision_counts: dict[str, int] = {}
    model_by_decision: dict[str, dict[str, int]] = {}
    reason_counts: dict[str, int] = {}
    examples: dict[str, list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    model_call_count = 0
    model_error_count = 0
    trigger_total = 0
    trigger_pack_improved = 0
    trigger_no_support = 0
    stop_total = 0
    stop_pack_improved = 0
    skip_total = 0
    skip_pack_improved = 0

    def inc(mapping: dict[str, int], key: str) -> None:
        mapping[key] = mapping.get(key, 0) + 1

    def inc_nested(mapping: dict[str, dict[str, int]], key: str, child: str) -> None:
        bucket = mapping.setdefault(key, {})
        bucket[child] = bucket.get(child, 0) + 1

    for candidate in candidates:
        question = str(candidate.get("question") or "")
        draft = str(candidate.get("answer") or "")
        if fast_mode:
            fast_result = run_evidence_bound_fast_audit(
                question,
                candidate.get("top_evidence") if isinstance(candidate.get("top_evidence"), list) else [],
                candidate.get("pack_evidence") if isinstance(candidate.get("pack_evidence"), list) else [],
                draft_answer=draft,
                model_config=config,
                execute=True,
            )
            top_result = {
                "answer": fast_result.get("answer") if fast_result.get("top_verdict") == "answered" else "UNKNOWN",
                "verdict": fast_result.get("top_verdict", "unknown"),
                "confidence": fast_result.get("confidence", 0.0),
                "supporting_refs": fast_result.get("top_supporting_refs", []),
                "unknown_reason": fast_result.get("evidence_gap_reason") or fast_result.get("unknown_reason", ""),
                "ok": fast_result.get("ok", True),
            }
            pack_result = {
                "answer": fast_result.get("answer"),
                "verdict": fast_result.get("pack_verdict", fast_result.get("verdict", "unknown")),
                "confidence": fast_result.get("confidence", 0.0),
                "supporting_refs": fast_result.get("pack_supporting_refs", []),
                "unknown_reason": fast_result.get("evidence_gap_reason") or fast_result.get("unknown_reason", ""),
                "ok": fast_result.get("ok", True),
                "needs_careful_mode": fast_result.get("needs_careful_mode", False),
                "careful_reason": fast_result.get("careful_reason", ""),
                "contradiction_detected": fast_result.get("contradiction_detected", False),
            }
            model_call_count += int(bool(fast_result.get("model_call_performed")))
            model_error_count += int(fast_result.get("ok") is False)
            model_verdict = _fast_audit_probe_verdict(fast_result)
        else:
            top_result = run_evidence_bound_answer(
                question,
                candidate.get("top_evidence") if isinstance(candidate.get("top_evidence"), list) else [],
                draft_answer=draft,
                model_config=config,
                execute=True,
            )
            pack_result = run_evidence_bound_answer(
                question,
                candidate.get("pack_evidence") if isinstance(candidate.get("pack_evidence"), list) else [],
                draft_answer=draft,
                model_config=config,
                execute=True,
            )
            model_call_count += int(bool(top_result.get("model_call_performed"))) + int(bool(pack_result.get("model_call_performed")))
            model_error_count += int(top_result.get("ok") is False) + int(pack_result.get("ok") is False)
            model_verdict = _runtime_probe_verdict(top_result, pack_result)
        model_class = _calibration_model_class(model_verdict)
        pack_size = int(candidate.get("pack_size") or 0)
        density = _density(pack_result, pack_size)
        top_state = _answered_state(top_result)
        pack_state = _answered_state(pack_result)
        features = {
            "primary": "light_candidate",
            "cost_band": "unknown",
            "pack_size_bucket": "pack_large" if pack_size > 12 else "pack_medium" if pack_size > 5 else "pack_small",
            "incremental_tokenish_bucket": "unknown",
            "pack_supporting_ref_density_bucket": "zero" if density <= 0 else "positive",
            "top_answered_state": top_state,
            "pack_answered_state": pack_state,
            "answer_state_pair": f"top_{top_state}__pack_{pack_state}",
            "pack_unknown_reason_bucket": _unknown_bucket(pack_result.get("unknown_reason", "")),
            "needs_careful_mode": bool(pack_result.get("needs_careful_mode", False)),
        }
        policy = _runtime_candidate_policy(features, density)
        decision = str(policy.get("decision") or "observe_only")
        inc(decision_counts, decision)
        inc_nested(model_by_decision, decision, model_class)
        for reason in policy.get("reasons") or []:
            inc(reason_counts, str(reason))
        is_trigger = decision == "trigger_candidate"
        is_stop = decision == "stop_no_support"
        is_skip = decision.startswith("skip_")
        trigger_total += int(is_trigger)
        trigger_pack_improved += int(is_trigger and model_class == "model_pack_improved")
        trigger_no_support += int(is_trigger and model_class == "model_no_support")
        stop_total += int(is_stop)
        stop_pack_improved += int(is_stop and model_class == "model_pack_improved")
        skip_total += int(is_skip)
        skip_pack_improved += int(is_skip and model_class == "model_pack_improved")
        row = {
            "question_id": candidate.get("question_id", ""),
            "decision": decision,
            "confidence": policy.get("confidence", ""),
            "reasons": policy.get("reasons", []),
            "model_class": model_class,
            "model_verdict": model_verdict,
            "fast_mode": bool(fast_mode),
            "needs_careful_mode": bool(pack_result.get("needs_careful_mode", False)),
            "careful_reason": pack_result.get("careful_reason", ""),
            "contradiction_detected": bool(pack_result.get("contradiction_detected", False)),
            "pack_supporting_ref_density": density,
            "features": features,
            "question": str(candidate.get("question") or "")[:220],
        }
        rows.append(row)
        examples.setdefault(decision, [])
        if len(examples[decision]) < example_limit:
            examples[decision].append(row)

    selected_count = len(rows)
    return {
        "selected_case_count": selected_count,
        "model_call_count": model_call_count,
        "model_error_count": model_error_count,
        "decision_counts": dict(sorted(decision_counts.items())),
        "model_by_decision": {
            key: dict(sorted(value.items()))
            for key, value in sorted(model_by_decision.items())
        },
        "reason_counts": dict(sorted(reason_counts.items())),
        "metrics": {
            "trigger_candidate_total": trigger_total,
            "trigger_candidate_rate": round(trigger_total / selected_count, 4) if selected_count else 0.0,
            "trigger_candidate_pack_improved": trigger_pack_improved,
            "trigger_candidate_precision": round(trigger_pack_improved / trigger_total, 4) if trigger_total else 0.0,
            "trigger_candidate_no_support": trigger_no_support,
            "stop_no_support_total": stop_total,
            "stop_no_support_pack_improved": stop_pack_improved,
            "skip_total": skip_total,
            "skip_pack_improved": skip_pack_improved,
            "fast_mode": bool(fast_mode),
            "careful_requested_total": sum(1 for row in rows if row.get("needs_careful_mode")),
        },
        "examples": examples,
        "rows": rows,
    }


def run_one_model(
    *,
    candidates: list[dict[str, Any]],
    case_count: int,
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
    focus_top_k: int,
    max_model_cases: int,
    example_limit: int,
    timeout_seconds: int,
    fast_mode: bool,
) -> dict[str, Any]:
    env_name = "MEMCORE_MODEL_MATRIX_API_KEY"
    old_value = os.environ.get(env_name)
    os.environ[env_name] = api_key
    started_wall = time.time()
    started_cpu = _cpu_seconds()
    try:
        runtime = run_model_on_candidates(
            candidates,
            config={
                "provider": provider,
                "model": model,
                "base_url": base_url,
                "api_key_env": env_name,
                "timeout_seconds": timeout_seconds,
            },
            example_limit=example_limit,
            fast_mode=fast_mode,
        )
        status = "ok"
        error = ""
    except Exception as exc:
        runtime = {}
        status = "error"
        error = _safe_error(f"{exc.__class__.__name__}: {exc}")
    finally:
        if old_value is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = old_value
    elapsed = round(time.time() - started_wall, 3)
    cpu_used = round(_cpu_seconds() - started_cpu, 3)
    probe_model = runtime.get("probe_model", {}) if isinstance(runtime.get("probe_model"), dict) else {}
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "status": status,
        "error": error,
        "elapsed_seconds": elapsed,
        "local_cpu_seconds": cpu_used,
        "max_rss_mb": _rss_mb(),
        "case_count": case_count,
        "selected_case_count": runtime.get("selected_case_count", 0),
        "model_call_count": runtime.get("model_call_count", 0),
        "model_error_count": runtime.get("model_error_count", 0),
        "decision_counts": runtime.get("decision_counts", {}),
        "model_by_decision": runtime.get("model_by_decision", {}),
        "reason_counts": runtime.get("reason_counts", {}),
        "metrics": runtime.get("metrics", {}),
        "rows": runtime.get("rows", []),
        "examples": runtime.get("examples", {}),
        "fast_mode": bool(fast_mode),
        "probe_model": {
            "provider": probe_model.get("provider", provider),
            "model": probe_model.get("model", model),
            "api_key_present": bool(probe_model.get("api_key_present", bool(api_key))),
            "api_key_value_returned": False,
        },
        "boundary": {
            "secret_values_returned": False,
            "raw_memory_write": False,
            "ranking_unchanged": True,
            "model_side_pressure": True,
            "local_resource_ledger": True,
            "light_candidate_builder": True,
            "fast_audit_single_call": bool(fast_mode),
        },
    }


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Evidence-Bound Model Matrix",
        "",
        f"- schema: {summary.get('schema', '')}",
        f"- dataset: {summary.get('dataset', '')}",
        f"- retrieval_mode: {summary.get('retrieval_mode', '')}",
        f"- max_model_cases: {summary.get('max_model_cases', '')}",
        f"- model_count: {summary.get('model_count', 0)}",
        f"- secret_values_returned: {str(bool(summary.get('secret_values_returned'))).lower()}",
        f"- pressure_target: {summary.get('pressure_target', '')}",
        "",
        "| Provider | Model | Status | Calls | Errors | Elapsed | CPU | Max RSS | Trigger precision | Decisions |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary.get("results", []):
        metrics = row.get("metrics", {}) if isinstance(row.get("metrics"), dict) else {}
        decisions = row.get("decision_counts", {}) if isinstance(row.get("decision_counts"), dict) else {}
        precision = metrics.get("trigger_candidate_precision", 0.0)
        lines.append(
            "| {provider} | {model} | {status} | {calls} | {errors} | {elapsed}s | {cpu}s | {rss} MB | {precision} | `{decisions}` |".format(
                provider=row.get("provider", ""),
                model=row.get("model", ""),
                status=row.get("status", ""),
                calls=row.get("model_call_count", 0),
                errors=row.get("model_error_count", 0),
                elapsed=row.get("elapsed_seconds", 0),
                cpu=row.get("local_cpu_seconds", 0),
                rss=row.get("max_rss_mb", 0),
                precision=_percent(float(precision or 0.0)),
                decisions=json.dumps(decisions, ensure_ascii=False, sort_keys=True),
            )
        )
    lines.extend(["", "## Notes"])
    lines.append("- Local CPU/RSS here is packaging, validation, and HTTP orchestration only; model reasoning is external.")
    if summary.get("fast_mode"):
        lines.append("- Fast mode uses one top+pack evidence audit call per case instead of separate top and pack calls.")
    lines.append("- API keys are read from the private model file into process memory and are not serialized into reports.")
    lines.append("- This is a diagnostic matrix, not an official leaderboard score.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run evidence-bound diagnostics across a private model list.")
    parser.add_argument("--model-file", required=True)
    parser.add_argument("--dataset", default="locomo", choices=("locomo", "longmemeval"))
    parser.add_argument("--data", default="benchmarks/cache/locomo/locomo10.json")
    parser.add_argument("--retrieval-mode", default="two_stage_session_scoped_bm25")
    parser.add_argument("--focus-top-k", type=int, default=3)
    parser.add_argument("--compare-top-k", default="3,5,10,20")
    parser.add_argument("--max-conversations", type=int, default=None)
    parser.add_argument("--max-questions", type=int, default=None)
    parser.add_argument("--max-model-cases", type=int, default=999)
    parser.add_argument("--example-limit", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--fast-mode", action="store_true", help="Use one compact top+pack evidence audit call per case.")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--model-filter", action="append", default=[])
    args = parser.parse_args(argv)

    blocks = parse_model_file(args.model_file)
    filters = {str(item).strip() for item in args.model_filter if str(item).strip()}
    compare_top_k = [int(part.strip()) for part in str(args.compare_top_k).split(",") if part.strip()]
    setup_started = time.time()
    setup_cpu_started = _cpu_seconds()
    cases = load_cases(
        dataset=args.dataset,
        split="oracle",
        data_path=args.data,
        max_conversations=args.max_conversations if args.dataset == "locomo" else None,
        max_questions=args.max_questions,
    )
    candidates, candidate_ledger = build_light_candidates(
        cases,
        focus_top_k=args.focus_top_k,
        max_cases=args.max_model_cases,
    )
    setup_resource_ledger = {
        "elapsed_seconds": round(time.time() - setup_started, 3),
        "local_cpu_seconds": round(_cpu_seconds() - setup_cpu_started, 3),
        "max_rss_mb": _rss_mb(),
        "case_count": len(cases),
        "source_unit_count": sum(len(case.get("source_units") or []) for case in cases if isinstance(case, dict)),
        "top_k_values": compare_top_k,
        "candidate_ledger": candidate_ledger,
        "note": "light shared candidate build before model matrix",
    }
    results: list[dict[str, Any]] = []
    for block in blocks:
        for model in block.get("models") or []:
            if filters and model not in filters:
                continue
            print(f"[model-matrix] running {block.get('provider')} {model}", flush=True)
            results.append(
                run_one_model(
                    candidates=candidates,
                    case_count=len(cases),
                    provider=str(block.get("provider") or ""),
                    base_url=str(block.get("base_url") or ""),
                    model=str(model),
                    api_key=str(block.get("api_key") or ""),
                    focus_top_k=args.focus_top_k,
                    max_model_cases=args.max_model_cases,
                    example_limit=args.example_limit,
                    timeout_seconds=args.timeout_seconds,
                    fast_mode=args.fast_mode,
                )
            )
    summary = {
        "ok": True,
        "schema": MODEL_MATRIX_SCHEMA,
        "model_inventory": safe_model_inventory(blocks),
        "model_count": len(results),
        "dataset": args.dataset,
        "data_path": args.data,
        "retrieval_mode": args.retrieval_mode,
        "focus_top_k": args.focus_top_k,
        "compare_top_k": compare_top_k,
        "max_model_cases": args.max_model_cases,
        "max_conversations": args.max_conversations,
        "max_questions": args.max_questions,
        "shared_retrieval_resource_ledger": setup_resource_ledger,
        "secret_values_returned": False,
        "pressure_target": "external_model",
        "fast_mode": bool(args.fast_mode),
        "results": results,
        "boundary": {
            "official_leaderboard_score": False,
            "diagnostic_only": True,
            "model_side_pressure": True,
            "local_resource_ledger": True,
            "no_memory_write": True,
            "fast_audit_single_call": bool(args.fast_mode),
        },
    }
    if args.output_json:
        Path(args.output_json).expanduser().write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).expanduser().write_text(render_markdown(summary), encoding="utf-8")
    if not args.output_json and not args.output_md:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
