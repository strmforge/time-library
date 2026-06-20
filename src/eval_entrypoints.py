#!/usr/bin/env python3
"""Profile policy for daily, regression, and offline memory evaluation runs."""

from __future__ import annotations

import json
import os
import platform
import socket
from pathlib import Path
from typing import Any

try:
    from src.eval_resource_ledger import (
        atomic_write_json,
        finish_run_ledger,
        run_resumable_cases,
        start_run_ledger,
    )
    from src.free_memory_benchmark import (
        DEFAULT_FREE_RETRIEVAL_MODE,
        compact_diagnostic_result,
    )
    from src.official_memory_benchmarks import (
        DEFAULT_CACHE_ROOT,
        load_cases,
        resolve_dataset_path,
        run_retrieval_diagnostic,
    )
except Exception:
    from eval_resource_ledger import (
        atomic_write_json,
        finish_run_ledger,
        run_resumable_cases,
        start_run_ledger,
    )
    from free_memory_benchmark import (
        DEFAULT_FREE_RETRIEVAL_MODE,
        compact_diagnostic_result,
    )
    from official_memory_benchmarks import (
        DEFAULT_CACHE_ROOT,
        load_cases,
        resolve_dataset_path,
        run_retrieval_diagnostic,
    )


EVAL_ENTRYPOINTS_CONTRACT = "eval_entrypoints.v2026.6.19"
EVAL_PROFILES = ("daily", "regression", "offline")
EVAL_BENCHMARK_SUITES = ("", "free")


def normalize_profile(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "daily_retrieval": "daily",
        "targeted": "regression",
        "targeted_regression": "regression",
        "offline_benchmark": "offline",
        "full": "offline",
    }
    text = aliases.get(text, text)
    if text not in EVAL_PROFILES:
        raise ValueError(f"unknown evaluation profile: {value}")
    return text


def detect_host_label(hostname: str | None = None, system: str | None = None, explicit: str = "") -> str:
    if explicit:
        return str(explicit).strip().lower()
    name = (hostname or socket.gethostname() or "").strip().lower()
    sysname = (system or platform.system() or "").strip().lower()
    if name == "r730xd" or "r730xd" in name:
        return "r730xd"
    if name == "desktop-5cjomia":
        return "windows123"
    if name == "desktop-8pbantb":
        return "windows191"
    if sysname == "darwin":
        return "macmini"
    if sysname == "windows":
        return "windows"
    return "other"


def _int(value: Any, default: int, minimum: int = 0, maximum: int = 1_000_000) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def build_eval_plan(
    *,
    profile: str,
    host_label: str = "",
    dataset: str = "",
    split: str = "",
    sample_count: int | None = None,
    max_questions: int | None = None,
    top_k: int | None = None,
    retrieval_mode: str = "",
    benchmark_suite: str = "",
    judge_requested: bool = False,
    override: bool = False,
    watcher_active: bool | None = None,
    watcher_active_source: str = "",
) -> dict[str, Any]:
    normalized = normalize_profile(profile)
    host = detect_host_label(explicit=host_label)
    count = _int(sample_count if sample_count is not None else max_questions, 0)
    k = _int(top_k, 3 if normalized == "daily" else 5, minimum=1, maximum=200)
    suite = normalize_benchmark_suite(benchmark_suite)
    reasons: list[str] = []
    warnings: list[str] = []

    if normalized == "daily":
        max_top_k = 5
        max_sample_count = 0
        if k > max_top_k:
            reasons.append("daily_retrieval_top_k_too_high")
        if count > 0:
            reasons.append("daily_retrieval_refuses_dataset_scan")
        if judge_requested:
            reasons.append("daily_retrieval_refuses_judge")
        if suite:
            reasons.append("daily_retrieval_refuses_benchmark_suite")
    elif normalized == "regression":
        max_top_k = 20
        max_sample_count = 100
        if k > max_top_k:
            reasons.append("targeted_regression_top_k_too_high")
        if count > max_sample_count:
            reasons.append("targeted_regression_requires_small_sample")
        if suite and count <= 0:
            reasons.append("targeted_regression_requires_explicit_sample_count")
        if suite and str(dataset or "").strip().lower() in {"", "free", "suite", "all"}:
            warnings.append("free_suite_sample_count_applies_per_dataset")
    else:
        max_top_k = 200
        max_sample_count = 0
        if host != "r730xd" and not override:
            reasons.append("offline_benchmark_refuses_workstation_without_override")
        if watcher_active is None and not override:
            reasons.append("offline_benchmark_requires_confirmed_watcher_state")
        if watcher_active and not override:
            reasons.append("offline_benchmark_refuses_watcher_concurrency")
        if suite and count <= 0 and not override:
            reasons.append("offline_benchmark_requires_explicit_sample_count_or_override")
        if count and count < 20:
            warnings.append("offline_profile_with_small_sample_is_smoke_only")
        if suite and str(dataset or "").strip().lower() in {"", "free", "suite", "all"}:
            warnings.append("free_suite_sample_count_applies_per_dataset")

    ok = not reasons
    return {
        "ok": ok,
        "contract": EVAL_ENTRYPOINTS_CONTRACT,
        "profile": normalized,
        "host_label": host,
        "dataset": str(dataset or ""),
        "split": str(split or ""),
        "sample_count": count,
        "retrieval_mode": str(retrieval_mode or ""),
        "benchmark_suite": suite,
        "top_k": k,
        "max_top_k": max_top_k,
        "max_sample_count": max_sample_count,
        "judge_requested": bool(judge_requested),
        "override": bool(override),
        "watcher_active": watcher_active,
        "watcher_active_source": str(watcher_active_source or ""),
        "blocked": not ok,
        "blocked_reasons": reasons,
        "warnings": warnings,
        "resource_ledger_required": normalized in {"regression", "offline"},
        "resume_required": normalized in {"regression", "offline"},
        "daily_use_safe": normalized == "daily" and ok,
        "offline_host_required": "r730xd" if normalized == "offline" else "",
    }


def normalize_benchmark_suite(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "none": "",
        "no": "",
        "false": "",
        "free_retrieval": "free",
        "free_benchmark": "free",
        "free_memory_benchmark": "free",
    }
    text = aliases.get(text, text)
    if text not in EVAL_BENCHMARK_SUITES:
        raise ValueError(f"unknown benchmark suite: {value}")
    return text


def load_jsonl_cases(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path:
        return rows
    for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def dry_case_runner(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "retrieval_mode": str(case.get("retrieval_mode") or "dry_run"),
        "top_k": int(case.get("top_k") or 0),
        "source_refs_count": len(case.get("source_refs") or []),
        "hypothesis_written": bool(case.get("hypothesis")),
    }


def _selected_free_datasets(dataset: str) -> list[str]:
    text = str(dataset or "").strip().lower()
    if text in {"", "free", "suite", "all"}:
        return ["locomo", "longmemeval"]
    if text in {"locomo", "longmemeval"}:
        return [text]
    raise ValueError(f"unsupported free benchmark dataset: {dataset}")


def load_free_benchmark_cases(
    *,
    dataset: str = "",
    split: str = "oracle",
    locomo_data_path: str | Path | None = None,
    longmemeval_data_path: str | Path | None = None,
    download: bool = False,
    force_download: bool = False,
    cache_root: str | Path | None = None,
    max_conversations: int | None = None,
    max_questions: int | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    root = cache_root or DEFAULT_CACHE_ROOT
    for name in _selected_free_datasets(dataset):
        data_path = locomo_data_path if name == "locomo" else longmemeval_data_path
        path = resolve_dataset_path(
            dataset=name,
            split=split,
            data_path=data_path,
            download=download,
            cache_root=root,
            force_download=force_download,
        )
        cases = load_cases(
            dataset=name,
            split=split,
            data_path=path,
            max_conversations=max_conversations if name == "locomo" else None,
            max_questions=max_questions,
        )
        for case in cases:
            copy = dict(case)
            question_id = str(copy.get("question_id") or "")
            copy["case_id"] = f"{name}:{question_id or len(rows) + 1}"
            copy["benchmark_dataset"] = name
            copy["benchmark_split"] = split if name == "longmemeval" else "locomo10"
            rows.append(copy)
    return rows


def free_benchmark_case_runner(
    case: dict[str, Any],
    *,
    top_k: int,
    retrieval_mode: str,
) -> dict[str, Any]:
    result = run_retrieval_diagnostic(
        [case],
        top_k_values=[int(top_k)],
        retrieval_mode=retrieval_mode or DEFAULT_FREE_RETRIEVAL_MODE,
    )
    compact = compact_diagnostic_result(
        {
            **result,
            "dataset": case.get("benchmark_dataset") or case.get("dataset"),
            "split": case.get("benchmark_split") or case.get("metadata", {}).get("split", ""),
        },
        label=f"{case.get('benchmark_dataset') or case.get('dataset')} case",
        top_k=int(top_k),
    )
    top_results = []
    if result.get("per_case"):
        top_results = result["per_case"][0].get("top_results") or []
    metrics = compact.get("metrics", {})
    return {
        "status": "ok" if result.get("ok") else "failed",
        "dataset": compact.get("dataset"),
        "split": compact.get("split"),
        "question_id": case.get("question_id", ""),
        "question_type": case.get("question_type", ""),
        "retrieval_mode": result.get("retrieval_mode") or retrieval_mode,
        "top_k": int(top_k),
        "source_refs_count": len(top_results),
        "hypothesis_written": False,
        "judge_verdict": "",
        "metrics": metrics,
        "official_leaderboard_score": False,
        "no_api_key_required": True,
        "no_model_call": True,
        "no_memory_write": True,
    }


def summarize_free_case_ledger(path: str | Path, *, run_id: str, top_k: int) -> dict[str, Any]:
    target = Path(path).expanduser()
    by_dataset: dict[str, dict[str, Any]] = {}
    if not target.exists():
        return {"ok": False, "reason": "case_ledger_missing", "results": []}
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("run_id") or "") != str(run_id):
            continue
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        if row.get("status") != "ok" or not result:
            continue
        dataset = str(result.get("dataset") or "unknown")
        bucket = by_dataset.setdefault(
            dataset,
            {
                "dataset": dataset,
                "split": str(result.get("split") or ""),
                "case_count": 0,
                "top_k": int(top_k),
                "exact_source_hits": 0,
                "bundled_source_hits": 0,
                "near_source_hits": 0,
                "answer_supported_hits": 0,
                "exact_miss_answer_supported_hits": 0,
                "exact_hit_answer_unsupported_hits": 0,
                "answer_support_level_counts": {},
                "session_hits": 0,
                "gold_anchor_hits": 0,
            },
        )
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        bucket["case_count"] += 1
        bucket["exact_source_hits"] += 1 if float(metrics.get("exact_source_recall") or 0) > 0 else 0
        bucket["bundled_source_hits"] += 1 if float(metrics.get("bundled_source_recall") or 0) > 0 else 0
        bucket["near_source_hits"] += 1 if float(metrics.get("near_source_recall") or 0) > 0 else 0
        bucket["answer_supported_hits"] += 1 if float(metrics.get("answer_supported_recall") or 0) > 0 else 0
        bucket["exact_miss_answer_supported_hits"] += int(metrics.get("exact_miss_answer_supported_hits") or 0)
        bucket["exact_hit_answer_unsupported_hits"] += int(metrics.get("exact_hit_answer_unsupported_hits") or 0)
        for level, level_count in (metrics.get("answer_support_level_counts") or {}).items():
            level_key = str(level)
            bucket["answer_support_level_counts"][level_key] = int(bucket["answer_support_level_counts"].get(level_key, 0)) + int(level_count or 0)
        bucket["session_hits"] += 1 if float(metrics.get("session_recall") or 0) > 0 else 0
        bucket["gold_anchor_hits"] += 1 if float(metrics.get("gold_anchor_recall") or 0) > 0 else 0
    results = []
    for bucket in by_dataset.values():
        count = max(int(bucket.get("case_count") or 0), 1)
        results.append(
            {
                **bucket,
                "exact_source_recall": round(bucket["exact_source_hits"] / count, 4),
                "bundled_source_recall": round(bucket["bundled_source_hits"] / count, 4),
                "near_source_recall": round(bucket["near_source_hits"] / count, 4),
                "answer_supported_recall": round(bucket["answer_supported_hits"] / count, 4),
                "session_recall": round(bucket["session_hits"] / count, 4),
                "gold_anchor_recall": round(bucket["gold_anchor_hits"] / count, 4),
            }
        )
    return {
        "ok": True,
        "mode": "free_retrieval_benchmark_small_sample",
        "top_k": int(top_k),
        "benchmark_count": len(results),
        "results": sorted(results, key=lambda item: item.get("dataset", "")),
        "boundary": {
            "no_api_key_required": True,
            "no_model_call": True,
            "no_memory_write": True,
            "official_leaderboard_score": False,
        },
    }


def default_eval_run_dir(repo_root: str | Path | None, run_id: str) -> Path:
    root = Path(repo_root or os.getcwd()).expanduser()
    return root / "benchmarks" / "eval-runs" / run_id


def execute_eval_entrypoint(
    *,
    profile: str,
    host_label: str = "",
    dataset: str = "",
    split: str = "",
    sample_count: int | None = None,
    max_questions: int | None = None,
    top_k: int | None = None,
    retrieval_mode: str = "",
    benchmark_suite: str = "",
    judge_requested: bool = False,
    override: bool = False,
    watcher_active: bool | None = None,
    watcher_active_source: str = "",
    checkpoint_path: str | Path | None = None,
    case_ledger_path: str | Path | None = None,
    run_ledger_path: str | Path | None = None,
    case_list_path: str | Path | None = None,
    locomo_data_path: str | Path | None = None,
    longmemeval_data_path: str | Path | None = None,
    download: bool = False,
    force_download: bool = False,
    cache_root: str | Path | None = None,
    max_conversations: int | None = None,
    resume: bool = True,
    force: bool = False,
    sleep_ms_between_cases: int = 0,
    max_runtime_minutes: float = 0,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    plan = build_eval_plan(
        profile=profile,
        host_label=host_label,
        dataset=dataset,
        split=split,
        sample_count=sample_count,
        max_questions=max_questions,
        top_k=top_k,
        retrieval_mode=retrieval_mode or (DEFAULT_FREE_RETRIEVAL_MODE if normalize_benchmark_suite(benchmark_suite) == "free" else ""),
        benchmark_suite=benchmark_suite,
        judge_requested=judge_requested,
        override=override,
        watcher_active=watcher_active,
        watcher_active_source=watcher_active_source,
    )
    ledger = start_run_ledger(
        profile=plan["profile"],
        host_label=plan["host_label"],
        dataset=dataset,
        split=split,
        sample_count=plan["sample_count"],
        retrieval_mode=plan["retrieval_mode"],
        top_k=plan["top_k"],
        resume_enabled=resume,
        checkpoint_path=checkpoint_path,
        watcher_active_at_start=watcher_active,
        watcher_active_source=watcher_active_source,
        judge="requested" if judge_requested else "",
        repo_root=repo_root,
    )
    suite = plan["benchmark_suite"]
    ledger["benchmark_suite"] = suite
    if plan["blocked"]:
        finish_run_ledger(
            ledger,
            status="blocked",
            block_reason=",".join(plan["blocked_reasons"]),
        )
        if run_ledger_path:
            atomic_write_json(run_ledger_path, ledger)
        return {"ok": False, "plan": plan, "ledger": ledger}

    case_stats = {}
    benchmark_result = {}
    try:
        if suite == "free":
            run_dir = default_eval_run_dir(repo_root, ledger["run_id"])
            checkpoint_path = checkpoint_path or run_dir / "checkpoint.json"
            case_ledger_path = case_ledger_path or run_dir / "case-ledger.jsonl"
            run_ledger_path = run_ledger_path or run_dir / "run-ledger.json"
            ledger["checkpoint_path"] = str(checkpoint_path)
            ledger["case_ledger_path"] = str(case_ledger_path)
            ledger["run_ledger_path"] = str(run_ledger_path)
            max_q = plan["sample_count"] or max_questions
            cases = load_free_benchmark_cases(
                dataset=dataset,
                split=split or "oracle",
                locomo_data_path=locomo_data_path,
                longmemeval_data_path=longmemeval_data_path,
                download=download,
                force_download=force_download,
                cache_root=cache_root,
                max_conversations=max_conversations,
                max_questions=max_q,
            )
            ledger["requested_sample_count"] = int(plan["sample_count"] or 0)
            ledger["actual_case_count"] = len(cases)
            runner = lambda case: free_benchmark_case_runner(  # noqa: E731
                case,
                top_k=plan["top_k"],
                retrieval_mode=plan["retrieval_mode"] or DEFAULT_FREE_RETRIEVAL_MODE,
            )
            case_stats = run_resumable_cases(
                cases,
                run_id=ledger["run_id"],
                checkpoint_path=checkpoint_path,
                case_ledger_path=case_ledger_path,
                runner=runner,
                resume=resume,
                force=force,
                retrieval_mode=plan["retrieval_mode"] or DEFAULT_FREE_RETRIEVAL_MODE,
                top_k=plan["top_k"],
                sleep_ms_between_cases=max(0, int(sleep_ms_between_cases or 0)),
                max_runtime_minutes=float(max_runtime_minutes or 0),
            )
            benchmark_result = summarize_free_case_ledger(
                case_ledger_path,
                run_id=ledger["run_id"],
                top_k=plan["top_k"],
            )
        elif case_list_path and checkpoint_path and case_ledger_path:
            cases = load_jsonl_cases(case_list_path)
            ledger["actual_case_count"] = len(cases)
            case_stats = run_resumable_cases(
                cases,
                run_id=ledger["run_id"],
                checkpoint_path=checkpoint_path,
                case_ledger_path=case_ledger_path,
                runner=dry_case_runner,
                resume=resume,
                force=force,
                retrieval_mode=plan["retrieval_mode"] or "dry_run",
                top_k=plan["top_k"],
                sleep_ms_between_cases=max(0, int(sleep_ms_between_cases or 0)),
                max_runtime_minutes=float(max_runtime_minutes or 0),
            )
        finish_run_ledger(ledger, status="ok")
    except Exception as exc:
        finish_run_ledger(ledger, status="failed", failure_reason=str(exc))
        if run_ledger_path:
            atomic_write_json(run_ledger_path, ledger)
        return {"ok": False, "plan": plan, "ledger": ledger, "case_stats": case_stats, "error": str(exc)}
    if run_ledger_path:
        atomic_write_json(run_ledger_path, ledger)
    return {
        "ok": True,
        "plan": plan,
        "ledger": ledger,
        "case_stats": case_stats,
        "benchmark_result": benchmark_result,
    }
