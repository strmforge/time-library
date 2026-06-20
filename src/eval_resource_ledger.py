#!/usr/bin/env python3
"""Resource ledger helpers for Memcore evaluation entrypoints."""

from __future__ import annotations

import json
import os
import platform
import resource
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


EVAL_RESOURCE_LEDGER_CONTRACT = "eval_resource_ledger.v2026.6.19"
EVAL_CASE_LEDGER_CONTRACT = "eval_case_resource_ledger.v2026.6.19"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ru_maxrss_bytes(ru_maxrss: int) -> int:
    if platform.system().lower() == "darwin":
        return int(ru_maxrss)
    return int(ru_maxrss) * 1024


def resource_sample() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "sampled_at": utc_now(),
        "cpu_user_seconds": round(float(usage.ru_utime), 6),
        "cpu_system_seconds": round(float(usage.ru_stime), 6),
        "rss_peak_bytes": _ru_maxrss_bytes(int(usage.ru_maxrss)),
    }


def child_resource_sample() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "sampled_at": utc_now(),
        "cpu_user_seconds": round(float(usage.ru_utime), 6),
        "cpu_system_seconds": round(float(usage.ru_stime), 6),
        "rss_peak_bytes": _ru_maxrss_bytes(int(usage.ru_maxrss)),
    }


def git_state(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root or os.environ.get("MEMCORE_REPO_ROOT") or os.getcwd())
    state = {"commit": "", "dirty": None, "root": str(root)}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if commit.returncode == 0:
            state["commit"] = commit.stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if status.returncode == 0:
            state["dirty"] = bool(status.stdout.strip())
    except Exception as exc:
        state["error"] = str(exc)
    return state


def new_run_id(prefix: str = "eval") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def start_run_ledger(
    *,
    profile: str,
    host_label: str = "",
    dataset: str = "",
    split: str = "",
    sample_count: int | None = None,
    retrieval_mode: str = "",
    top_k: int | None = None,
    context_window: int | None = None,
    context_decay: float | None = None,
    answerer: str = "",
    judge: str = "",
    model_profile: str = "",
    resume_enabled: bool = False,
    checkpoint_path: str | Path | None = None,
    watcher_active_at_start: bool | None = None,
    watcher_active_source: str = "",
    repo_root: str | Path | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    started = time.perf_counter()
    sample = resource_sample()
    child_sample = child_resource_sample()
    git = git_state(repo_root)
    return {
        "contract": EVAL_RESOURCE_LEDGER_CONTRACT,
        "run_id": run_id or new_run_id(profile or "eval"),
        "profile": str(profile or ""),
        "host_label": str(host_label or ""),
        "hostname": socket.gethostname(),
        "git_commit": git.get("commit", ""),
        "git_dirty": git.get("dirty"),
        "git": git,
        "dataset": str(dataset or ""),
        "split": str(split or ""),
        "sample_count": int(sample_count or 0),
        "retrieval_mode": str(retrieval_mode or ""),
        "top_k": int(top_k or 0),
        "context_window": int(context_window or 0),
        "context_decay": float(context_decay or 0.0),
        "answerer": str(answerer or ""),
        "judge": str(judge or ""),
        "model_profile": str(model_profile or ""),
        "resume_enabled": bool(resume_enabled),
        "checkpoint_path": str(checkpoint_path or ""),
        "watcher_active_at_start": watcher_active_at_start,
        "watcher_active_source": str(watcher_active_source or ""),
        "started_at": utc_now(),
        "finished_at": "",
        "elapsed_ms": 0,
        "_perf_started": started,
        "_resource_start": sample,
        "_children_resource_start": child_sample,
        "cpu_user_seconds": 0.0,
        "cpu_system_seconds": 0.0,
        "rss_peak_bytes": int(sample.get("rss_peak_bytes") or 0),
        "process_tree_peak_rss_bytes": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost": 0,
        "status": "running",
        "block_reason": "",
        "failure_reason": "",
    }


def finish_run_ledger(
    ledger: dict[str, Any],
    *,
    status: str = "ok",
    block_reason: str = "",
    failure_reason: str = "",
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    estimated_cost: float | None = None,
) -> dict[str, Any]:
    current = resource_sample()
    children = child_resource_sample()
    start = ledger.get("_resource_start", {}) if isinstance(ledger.get("_resource_start"), dict) else {}
    started = float(ledger.get("_perf_started") or time.perf_counter())
    ledger["finished_at"] = utc_now()
    ledger["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    ledger["cpu_user_seconds"] = round(float(current.get("cpu_user_seconds") or 0) - float(start.get("cpu_user_seconds") or 0), 6)
    ledger["cpu_system_seconds"] = round(float(current.get("cpu_system_seconds") or 0) - float(start.get("cpu_system_seconds") or 0), 6)
    ledger["rss_peak_bytes"] = int(current.get("rss_peak_bytes") or ledger.get("rss_peak_bytes") or 0)
    ledger["process_tree_peak_rss_bytes"] = max(
        int(ledger.get("rss_peak_bytes") or 0),
        int(children.get("rss_peak_bytes") or 0),
    )
    if tokens_in is not None:
        ledger["tokens_in"] = int(tokens_in)
    if tokens_out is not None:
        ledger["tokens_out"] = int(tokens_out)
    if estimated_cost is not None:
        ledger["estimated_cost"] = estimated_cost
    ledger["status"] = str(status or "ok")
    ledger["block_reason"] = str(block_reason or "")
    ledger["failure_reason"] = str(failure_reason or "")
    ledger.pop("_perf_started", None)
    ledger.pop("_resource_start", None)
    ledger.pop("_children_resource_start", None)
    return ledger


def atomic_write_json(path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)
    return {"ok": True, "path": str(target), "bytes": target.stat().st_size}


def append_jsonl(path: str | Path, row: dict[str, Any]) -> dict[str, Any]:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return {"ok": True, "path": str(target), "bytes": target.stat().st_size}


def load_checkpoint(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {"completed_case_ids": []}
    target = Path(path).expanduser()
    if not target.exists():
        return {"completed_case_ids": []}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"completed_case_ids": []}
    except Exception:
        return {"completed_case_ids": []}


def save_checkpoint(path: str | Path, checkpoint: dict[str, Any]) -> dict[str, Any]:
    return atomic_write_json(path, checkpoint)


def mark_case_completed(checkpoint: dict[str, Any], case_id: str) -> dict[str, Any]:
    completed = list(checkpoint.get("completed_case_ids") or [])
    if case_id and case_id not in completed:
        completed.append(case_id)
    checkpoint["completed_case_ids"] = completed
    checkpoint["updated_at"] = utc_now()
    return checkpoint


def case_resource_row(
    *,
    run_id: str,
    case_id: str,
    question_id: str = "",
    status: str = "ok",
    elapsed_ms: float = 0,
    cpu_seconds_delta: float = 0,
    rss_bytes_sample: int = 0,
    retrieval_mode: str = "",
    top_k: int = 0,
    resume_skipped: bool = False,
    source_refs_count: int = 0,
    hypothesis_written: bool = False,
    judge_verdict: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "contract": EVAL_CASE_LEDGER_CONTRACT,
        "run_id": run_id,
        "case_id": case_id,
        "question_id": question_id,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "cpu_seconds_delta": cpu_seconds_delta,
        "rss_bytes_sample": int(rss_bytes_sample or 0),
        "retrieval_mode": retrieval_mode,
        "top_k": int(top_k or 0),
        "resume_skipped": bool(resume_skipped),
        "source_refs_count": int(source_refs_count or 0),
        "hypothesis_written": bool(hypothesis_written),
        "judge_verdict": judge_verdict,
    }
    if extra:
        row.update(extra)
    return row


def run_resumable_cases(
    cases: Iterable[dict[str, Any]],
    *,
    run_id: str,
    checkpoint_path: str | Path,
    case_ledger_path: str | Path,
    runner: Callable[[dict[str, Any]], dict[str, Any]],
    resume: bool = True,
    force: bool = False,
    retrieval_mode: str = "",
    top_k: int = 0,
    sleep_ms_between_cases: int = 0,
    max_runtime_minutes: float = 0,
) -> dict[str, Any]:
    started = time.perf_counter()
    checkpoint = load_checkpoint(checkpoint_path)
    completed = set(str(item) for item in checkpoint.get("completed_case_ids") or [])
    stats = {"case_count": 0, "ran": 0, "skipped": 0, "failed": 0}
    for index, case in enumerate(cases, start=1):
        stats["case_count"] += 1
        case_id = str(case.get("case_id") or case.get("question_id") or index)
        question_id = str(case.get("question_id") or case_id)
        if resume and not force and case_id in completed:
            sample = resource_sample()
            append_jsonl(
                case_ledger_path,
                case_resource_row(
                    run_id=run_id,
                    case_id=case_id,
                    question_id=question_id,
                    status="skipped",
                    retrieval_mode=retrieval_mode,
                    top_k=top_k,
                    resume_skipped=True,
                    rss_bytes_sample=int(sample.get("rss_peak_bytes") or 0),
                ),
            )
            stats["skipped"] += 1
            continue
        if max_runtime_minutes and (time.perf_counter() - started) > max_runtime_minutes * 60:
            stats["stopped_reason"] = "max_runtime_minutes"
            break
        before = resource_sample()
        case_started = time.perf_counter()
        try:
            result = runner(case)
            status = str(result.get("status") or "ok") if isinstance(result, dict) else "ok"
        except Exception as exc:
            result = {"status": "failed", "error": str(exc)}
            status = "failed"
            stats["failed"] += 1
        after = resource_sample()
        elapsed_ms = round((time.perf_counter() - case_started) * 1000.0, 3)
        cpu_delta = (
            float(after.get("cpu_user_seconds") or 0)
            + float(after.get("cpu_system_seconds") or 0)
            - float(before.get("cpu_user_seconds") or 0)
            - float(before.get("cpu_system_seconds") or 0)
        )
        append_jsonl(
            case_ledger_path,
            case_resource_row(
                run_id=run_id,
                case_id=case_id,
                question_id=question_id,
                status=status,
                elapsed_ms=elapsed_ms,
                cpu_seconds_delta=round(cpu_delta, 6),
                rss_bytes_sample=int(after.get("rss_peak_bytes") or 0),
                retrieval_mode=str(result.get("retrieval_mode") or retrieval_mode) if isinstance(result, dict) else retrieval_mode,
                top_k=int(result.get("top_k") or top_k) if isinstance(result, dict) else top_k,
                resume_skipped=False,
                source_refs_count=int(result.get("source_refs_count") or 0) if isinstance(result, dict) else 0,
                hypothesis_written=bool(result.get("hypothesis_written")) if isinstance(result, dict) else False,
                judge_verdict=str(result.get("judge_verdict") or "") if isinstance(result, dict) else "",
                extra={"result": result if isinstance(result, dict) else {}},
            ),
        )
        mark_case_completed(checkpoint, case_id)
        save_checkpoint(checkpoint_path, checkpoint)
        stats["ran"] += 1
        if sleep_ms_between_cases > 0:
            time.sleep(sleep_ms_between_cases / 1000.0)
    stats["checkpoint_path"] = str(Path(checkpoint_path).expanduser())
    stats["case_ledger_path"] = str(Path(case_ledger_path).expanduser())
    return stats
