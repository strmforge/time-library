#!/usr/bin/env python3
"""Codex-assisted local judge for memory benchmark QA artifacts.

This module is deliberately separate from the official evaluator runner. It can
use the local Codex CLI account as an internal judge, but it never claims a
LoCoMo or LongMemEval leaderboard score.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


CODEX_JUDGE_CONTRACT = "codex_assisted_memory_judge.v2026.6.17"
LAYERED_SCORE_REPORT_CONTRACT = "memcore_layered_benchmark_report.v2026.6.17"
CODEX_JUDGE_SAMPLE_TIERS = {
    "smoke": 3,
    "pilot": 20,
    "standard": 50,
    "deep": 100,
    "full": None,
}
LONGMEMEVAL_DIFFICULTY_ORDER = (
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "temporal-reasoning",
    "multi-session",
    "knowledge-update",
)
LAYERED_SCORE_NAMES = (
    "retrieval_score",
    "projection_score",
    "preflight_score",
    "answer_synthesis_score",
    "gap_score",
    "progressive_retrieval_score",
    "ingestion_quality_score",
    "self_improvement_loop_score",
)


def _compact(text: Any, limit: int = 400) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(limit - 1, 0)].rstrip() + "..."


def _path_probe(path: str | Path | None, *, kind: str) -> dict:
    if not path:
        return {"path": "", "exists": False, "kind": kind, "ok": False, "reason": "missing_path"}
    resolved = Path(path).expanduser()
    exists = resolved.exists()
    if kind == "dir":
        ok = exists and resolved.is_dir()
    elif kind == "file":
        ok = exists and resolved.is_file()
    else:
        ok = exists
    reason = "ok" if ok else ("wrong_kind" if exists else "missing")
    return {"path": str(resolved), "exists": exists, "kind": kind, "ok": ok, "reason": reason}


def _shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _read_jsonl(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _reference_by_question_id(reference_rows: list[dict]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for row in reference_rows:
        if not isinstance(row, dict):
            continue
        question_id = str(row.get("question_id") or "")
        if question_id:
            by_id[question_id] = row
    return by_id


def load_longmemeval_judge_items(
    *,
    hypothesis_path: str | Path,
    reference_path: str | Path,
    max_questions: int | None = None,
) -> list[dict]:
    """Pair LongMemEval hypothesis rows with reference answers."""

    hypotheses = _read_jsonl(hypothesis_path)
    references = _read_json(reference_path)
    if not isinstance(references, list):
        raise ValueError("LongMemEval reference file must be a JSON list")
    by_id = _reference_by_question_id(references)
    items: list[dict] = []
    for row in hypotheses:
        if max_questions is not None and len(items) >= max_questions:
            break
        question_id = str(row.get("question_id") or "")
        reference = by_id.get(question_id, {})
        items.append(
            {
                "question_id": question_id,
                "question": reference.get("question", ""),
                "question_type": reference.get("question_type", ""),
                "reference_answer": reference.get("answer", ""),
                "hypothesis": row.get("hypothesis", ""),
                "memcore_context": row.get("memcore_context", []),
                "reference_found": bool(reference),
            }
        )
    return items


def select_longmemeval_judge_sample(
    items: list[dict],
    *,
    sample_tier: str = "",
    max_questions: int | None = None,
) -> tuple[list[dict], dict]:
    """Select a deterministic judge sample.

    The legacy path keeps first-N behavior. Named tiers use a fixed
    difficulty-ramp strategy so larger tiers add broader and harder LongMemEval
    question types instead of only taking the first rows.
    """

    available = list(items)
    tier = (sample_tier or "").strip().lower()
    if tier:
        if tier not in CODEX_JUDGE_SAMPLE_TIERS:
            raise ValueError(f"unknown sample tier: {sample_tier}")
        requested = CODEX_JUDGE_SAMPLE_TIERS[tier]
        selected = _difficulty_ramp_sample(available, requested)
        strategy = "fixed_difficulty_ramp_v1"
    else:
        requested = max_questions
        selected = available[:max_questions] if max_questions is not None else available
        strategy = "first_n_legacy"
    plan = _sample_plan(
        available=available,
        selected=selected,
        tier=tier or "custom",
        requested=requested,
        strategy=strategy,
    )
    return selected, plan


def _difficulty_ramp_sample(items: list[dict], requested: int | None) -> list[dict]:
    if requested is None:
        return list(items)
    if requested <= 0:
        return []
    by_type: dict[str, list[dict]] = {question_type: [] for question_type in LONGMEMEVAL_DIFFICULTY_ORDER}
    other: list[dict] = []
    for item in items:
        question_type = str(item.get("question_type") or "")
        if question_type in by_type:
            by_type[question_type].append(item)
        else:
            other.append(item)

    selected: list[dict] = []
    seen_ids: set[str] = set()
    round_index = 0
    while len(selected) < requested:
        progressed = False
        for question_type in LONGMEMEVAL_DIFFICULTY_ORDER:
            group = by_type.get(question_type, [])
            if round_index < len(group):
                item = group[round_index]
                question_id = str(item.get("question_id") or "")
                if question_id not in seen_ids:
                    selected.append(item)
                    seen_ids.add(question_id)
                    progressed = True
                    if len(selected) >= requested:
                        break
        if len(selected) >= requested:
            break
        if round_index < len(other):
            item = other[round_index]
            question_id = str(item.get("question_id") or "")
            if question_id not in seen_ids:
                selected.append(item)
                seen_ids.add(question_id)
                progressed = True
        if not progressed:
            break
        round_index += 1
    return selected


def _sample_plan(
    *,
    available: list[dict],
    selected: list[dict],
    tier: str,
    requested: int | None,
    strategy: str,
) -> dict:
    available_type_counts: dict[str, int] = {}
    selected_type_counts: dict[str, int] = {}
    for item in available:
        question_type = str(item.get("question_type") or "unknown")
        available_type_counts[question_type] = available_type_counts.get(question_type, 0) + 1
    for item in selected:
        question_type = str(item.get("question_type") or "unknown")
        selected_type_counts[question_type] = selected_type_counts.get(question_type, 0) + 1
    requested_count = len(available) if requested is None else int(requested)
    has_enough_available = requested is None or len(available) >= requested_count
    return {
        "tier": tier,
        "requested_questions": requested_count,
        "selected_questions": len(selected),
        "available_questions": len(available),
        "complete": len(selected) >= requested_count if requested is not None else len(selected) == len(available),
        "has_enough_available_questions": has_enough_available,
        "truncated_by_available_questions": not has_enough_available,
        "selection_strategy": strategy,
        "difficulty_order": list(LONGMEMEVAL_DIFFICULTY_ORDER),
        "question_type_counts": dict(sorted(selected_type_counts.items())),
        "available_question_type_counts": dict(sorted(available_type_counts.items())),
        "question_ids": [str(item.get("question_id") or "") for item in selected[:100]],
        "question_ids_truncated": len(selected) > 100,
    }


def longmemeval_reference_alignment(
    *,
    hypothesis_path: str | Path,
    reference_path: str | Path,
    max_questions: int | None = None,
) -> dict:
    items = load_longmemeval_judge_items(
        hypothesis_path=hypothesis_path,
        reference_path=reference_path,
        max_questions=max_questions,
    )
    matched = sum(1 for item in items if item.get("reference_found"))
    missing = [str(item.get("question_id") or "") for item in items if not item.get("reference_found")]
    total = len(items)
    ratio = (matched / total) if total else 0.0
    return {
        "ok": bool(total) and matched == total,
        "total": total,
        "matched": matched,
        "missing": len(missing),
        "match_ratio": round(ratio, 4),
        "missing_question_ids": missing[:10],
        "reason": "ok" if bool(total) and matched == total else "hypothesis_reference_question_id_mismatch",
    }


def codex_judge_schema(question_ids: list[str] | None = None) -> dict:
    question_id_schema: dict[str, Any] = {"type": "string"}
    if question_ids:
        question_id_schema["enum"] = [str(question_id) for question_id in question_ids]
    return {
        "type": "object",
        "properties": {
            "contract": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question_id": question_id_schema,
                        "verdict": {
                            "type": "string",
                            "enum": ["correct", "partial", "incorrect", "unjudgeable"],
                        },
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["question_id", "verdict", "confidence", "reason"],
                    "additionalProperties": False,
                },
            },
            "summary": {
                "type": "object",
                "properties": {
                    "correct": {"type": "integer"},
                    "partial": {"type": "integer"},
                    "incorrect": {"type": "integer"},
                    "unjudgeable": {"type": "integer"},
                    "total": {"type": "integer"},
                },
                "required": ["correct", "partial", "incorrect", "unjudgeable", "total"],
                "additionalProperties": False,
            },
        },
        "required": ["contract", "items", "summary"],
        "additionalProperties": False,
    }


def build_codex_judge_prompt(items: list[dict]) -> str:
    payload = [
        {
            "question_id": item.get("question_id", ""),
            "question": item.get("question", ""),
            "question_type": item.get("question_type", ""),
            "reference_answer": item.get("reference_answer", ""),
            "hypothesis": item.get("hypothesis", ""),
            "reference_found": bool(item.get("reference_found")),
        }
        for item in items
    ]
    return (
        "You are an internal memory-benchmark judge for Memcore Cloud.\n"
        "Judge whether each hypothesis answers the reference answer for the same question.\n"
        "Use only the supplied question, reference_answer, and hypothesis. Do not use outside knowledge.\n"
        "Copy each question_id exactly as supplied; do not shorten, normalize, or rewrite IDs.\n"
        "This judge follows the LongMemEval official evaluator spirit: the public metric is a yes/no label, not a partial-credit score.\n"
        "Use `correct` only when the hypothesis would deserve a yes label under these rules:\n"
        "- single-session-user, single-session-assistant, and multi-session: correct if it contains the complete correct answer or all intermediate steps needed to derive it; a subset is not correct.\n"
        "- temporal-reasoning: correct if it contains the correct temporal answer; off-by-one errors for days/weeks/months are acceptable.\n"
        "- knowledge-update: correct if the required updated answer is present, even when older previous information is also mentioned.\n"
        "- single-session-preference: correct if it recalls and uses the user's personal information correctly; it does not need to cover every rubric point.\n"
        "- question_id ending with `_abs`: correct only when the hypothesis identifies that the requested information is unavailable or incomplete.\n"
        "`partial` is for internal diagnostics only; it is counted as a miss by the official-like binary score.\n"
        "The top-level JSON object must contain an `items` array. Do not use aliases such as `judgment`, `result`, or `verdicts`.\n"
        "Each item must contain exactly these fields: question_id, verdict, confidence, reason.\n"
        "Verdicts:\n"
        "- correct: the hypothesis fully answers the reference.\n"
        "- partial: the hypothesis is directionally useful but incomplete.\n"
        "- incorrect: the hypothesis is wrong or does not answer.\n"
        "- unjudgeable: the reference or hypothesis is missing or malformed.\n"
        f"Return JSON matching the schema. Set contract to {CODEX_JUDGE_CONTRACT!r}.\n\n"
        "Items:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
    )


def codex_judge_preflight(
    *,
    codex_bin: str = "codex",
    hypothesis_path: str | Path | None = None,
    reference_path: str | Path | None = None,
) -> dict:
    resolved = shutil.which(codex_bin) if not Path(str(codex_bin)).exists() else str(Path(codex_bin).expanduser())
    codex_present = bool(resolved)
    help_ok = False
    help_excerpt = ""
    if codex_present:
        completed = subprocess.run(
            [resolved or codex_bin, "exec", "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        help_ok = completed.returncode == 0 and "--output-schema" in completed.stdout and "--ephemeral" in completed.stdout
        help_excerpt = _compact(completed.stdout or completed.stderr, 1200)
    checks = {
        "codex_cli": {
            "ok": codex_present,
            "path": resolved or "",
            "reason": "ok" if codex_present else "missing_codex_cli",
        },
        "codex_exec_schema_support": {
            "ok": bool(help_ok),
            "reason": "ok" if help_ok else "codex_exec_help_missing_output_schema_or_ephemeral",
        },
        "hypothesis_file": _path_probe(hypothesis_path, kind="file") if hypothesis_path else {
            "path": "",
            "exists": False,
            "kind": "file",
            "ok": False,
            "reason": "missing_path",
        },
        "reference_file": _path_probe(reference_path, kind="file") if reference_path else {
            "path": "",
            "exists": False,
            "kind": "file",
            "ok": False,
            "reason": "missing_path",
        },
    }
    if checks["hypothesis_file"].get("ok") and checks["reference_file"].get("ok"):
        try:
            checks["reference_alignment"] = longmemeval_reference_alignment(
                hypothesis_path=hypothesis_path or "",
                reference_path=reference_path or "",
            )
        except Exception as exc:  # pragma: no cover - defensive diagnostics
            checks["reference_alignment"] = {
                "ok": False,
                "reason": f"alignment_probe_failed:{type(exc).__name__}",
                "error": _compact(str(exc), 500),
            }
    else:
        checks["reference_alignment"] = {
            "ok": False,
            "reason": "requires_hypothesis_and_reference_files",
        }
    ready = all(bool(item.get("ok")) for item in checks.values())
    return {
        "ok": True,
        "contract": CODEX_JUDGE_CONTRACT,
        "mode": "codex_assisted_judge_preflight",
        "ready_to_run": ready,
        "checks": checks,
        "blocked_reasons": [key for key, item in checks.items() if not bool(item.get("ok"))],
        "codex_help_excerpt": help_excerpt,
        "official_leaderboard_score": False,
        "score_type": "codex_assisted_local_judge_diagnostic",
        "uses_openai_platform_api_key": False,
        "uses_codex_cli_auth": True,
        "model_call_required_when_run": True,
        "notes": [
            "can_use_chatgpt_codex_auth_for_internal_local_judge_when_codex_cli_is_logged_in",
            "not_a_drop_in_replacement_for_official_benchmark_evaluator_environment",
            "not_official_leaderboard_score",
        ],
    }


def run_codex_assisted_judge(
    *,
    hypothesis_path: str | Path,
    reference_path: str | Path,
    max_questions: int = 5,
    codex_bin: str = "codex",
    model: str = "",
    reasoning_effort: str = "",
    sample_tier: str = "",
    run: bool = False,
    timeout_seconds: int = 900,
    workdir: str | Path | None = None,
    batch_size: int = 0,
) -> dict:
    preflight = codex_judge_preflight(
        codex_bin=codex_bin,
        hypothesis_path=hypothesis_path,
        reference_path=reference_path,
    )
    all_items = load_longmemeval_judge_items(
        hypothesis_path=hypothesis_path,
        reference_path=reference_path,
    )
    items, sample_plan = select_longmemeval_judge_sample(
        all_items,
        sample_tier=sample_tier,
        max_questions=max_questions,
    )
    result: dict[str, Any] = {
        "ok": True,
        "contract": CODEX_JUDGE_CONTRACT,
        "mode": "codex_assisted_judge",
        "run_requested": bool(run),
        "ready_to_run": bool(preflight.get("ready_to_run")),
        "blocked_reasons": preflight.get("blocked_reasons", []),
        "preflight": preflight,
        "reference_alignment": preflight.get("checks", {}).get("reference_alignment", {}),
        "question_count": len(items),
        "sample_plan": sample_plan,
        "official_leaderboard_score": False,
        "score_type": "codex_assisted_local_judge_diagnostic",
        "judge_profile": {
            "model": model or "",
            "reasoning_effort": reasoning_effort or "",
            "profile_label": _judge_profile_label(model=model, reasoning_effort=reasoning_effort),
        },
        "uses_openai_platform_api_key": False,
        "uses_codex_cli_auth": True,
        "boundary": {
            "official_leaderboard_score": False,
            "official_evaluator_replacement": False,
            "internal_quality_signal": True,
            "memory_write_performed": False,
            "raw_write_performed": False,
            "platform_write_performed": False,
        },
        "notes": [
            "Codex can judge small local samples through codex exec when the CLI is authenticated.",
            "This uses the local Codex account path, not OPENAI_API_KEY.",
            "Public benchmark claims still require the benchmark official evaluator or accepted submission harness.",
        ],
    }
    normalized_batch_size = max(int(batch_size or 0), 0)
    if normalized_batch_size:
        result["batch_size"] = normalized_batch_size
    if not run:
        result["run_status"] = "preflight_only"
        result["prompt_preview"] = _compact(build_codex_judge_prompt(items), 3000)
        _attach_layered_score_report(result)
        return result
    if not preflight.get("ready_to_run"):
        result["ok"] = False
        result["run_status"] = "blocked_preflight_failed"
        _attach_layered_score_report(result)
        return result

    codex_path = preflight["checks"]["codex_cli"]["path"] or codex_bin
    if normalized_batch_size and len(items) > normalized_batch_size:
        chunks = list(_chunk_items(items, normalized_batch_size))
        result["batched_judge"] = True
        result["batch_count"] = len(chunks)
        result["command_display"] = (
            f"batched {len(chunks)} codex exec calls; batch_size={normalized_batch_size}; "
            "see batch_results for per-batch command displays"
        )
        merged_items: list[dict] = []
        batch_results: list[dict] = []
        all_batches_ok = True
        for batch_index, chunk in enumerate(chunks, start=1):
            invocation = _run_codex_judge_invocation(
                codex_path=codex_path,
                items=chunk,
                model=model,
                reasoning_effort=reasoning_effort,
                timeout_seconds=timeout_seconds,
                workdir=workdir,
            )
            verdict = invocation.get("judge_output") if isinstance(invocation.get("judge_output"), dict) else {}
            batch_diagnostics = _judge_diagnostics(verdict, chunk) if verdict else {
                "item_count": 0,
                "expected_item_count": len(chunk),
                "complete_item_coverage": False,
            }
            batch_score = _judge_score(verdict) if verdict else {"answer_acceptance": 0.0, "total": 0, "score_source": "none"}
            batch_record = {
                "batch_index": batch_index,
                "batch_count": len(chunks),
                "question_count": len(chunk),
                "returncode": invocation.get("returncode"),
                "run_status": invocation.get("run_status"),
                "command_display": invocation.get("command_display", ""),
                "stdout_excerpt": invocation.get("stdout_excerpt", ""),
                "stderr_excerpt": invocation.get("stderr_excerpt", ""),
                "codex_judge_score": batch_score,
                "judge_diagnostics": {
                    key: batch_diagnostics.get(key)
                    for key in [
                        "item_count",
                        "expected_item_count",
                        "complete_item_coverage",
                        "missing_judge_question_id_count",
                        "unresolved_question_id_count",
                        "question_id_resolution_counts",
                    ]
                },
            }
            if invocation.get("parse_error"):
                batch_record["parse_error"] = invocation.get("parse_error")
            if verdict and isinstance(verdict.get("items"), list):
                merged_items.extend(row for row in verdict["items"] if isinstance(row, dict))
            batch_results.append(batch_record)
            if (
                invocation.get("returncode") != 0
                or not verdict
                or not bool(batch_diagnostics.get("complete_item_coverage"))
            ):
                all_batches_ok = False
                break

        merged_verdict = {
            "contract": CODEX_JUDGE_CONTRACT,
            "items": merged_items,
            "summary": _verdict_item_summary(merged_items),
        }
        result["batch_results"] = batch_results
        result["judge_output"] = merged_verdict
        result["codex_judge_score"] = _judge_score(merged_verdict)
        result["judge_diagnostics"] = _judge_diagnostics(merged_verdict, items)
        _attach_task_averaged_binary_score(result["codex_judge_score"], result["judge_diagnostics"])
        _attach_layered_score_report(result)
        result["run_status"] = "completed" if all_batches_ok else "failed_batch"
        result["ok"] = (
            all_batches_ok
            and bool(result["judge_diagnostics"].get("complete_item_coverage"))
            and len(batch_results) == len(chunks)
        )
        return result

    invocation = _run_codex_judge_invocation(
        codex_path=codex_path,
        items=items,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
    )
    result.update(invocation)
    verdict = result.get("judge_output") if isinstance(result.get("judge_output"), dict) else {}
    if verdict:
        result["codex_judge_score"] = _judge_score(verdict)
        result["judge_diagnostics"] = _judge_diagnostics(verdict, items)
        _attach_task_averaged_binary_score(result["codex_judge_score"], result["judge_diagnostics"])
        _attach_layered_score_report(result)
    result["ok"] = (
        result.get("returncode") == 0
        and bool(verdict)
        and bool(result.get("judge_diagnostics", {}).get("complete_item_coverage"))
    )
    if result.get("returncode") == 0 and verdict and not result["ok"]:
        result["run_status"] = "completed_incomplete_coverage"
    if "layered_score_report" not in result:
        _attach_layered_score_report(result)
    return result


def _chunk_items(items: list[dict], batch_size: int) -> list[list[dict]]:
    size = max(int(batch_size), 1)
    return [items[index : index + size] for index in range(0, len(items), size)]


def _run_codex_judge_invocation(
    *,
    codex_path: str,
    items: list[dict],
    model: str = "",
    reasoning_effort: str = "",
    timeout_seconds: int = 900,
    workdir: str | Path | None = None,
) -> dict:
    prompt = build_codex_judge_prompt(items)
    with tempfile.TemporaryDirectory(prefix="memcore-codex-judge-") as tmp:
        tmp_path = Path(tmp)
        schema_path = tmp_path / "schema.json"
        output_path = tmp_path / "judge.json"
        schema_path.write_text(
            json.dumps(
                codex_judge_schema([str(item.get("question_id") or "") for item in items]),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        command = [
            codex_path,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
        ]
        if model:
            command.extend(["--model", model])
        if reasoning_effort:
            command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        command.append(prompt)
        result: dict[str, Any] = {"command_display": _shell_join([*command[:-1], "<prompt>"])}
        completed = subprocess.run(
            command,
            cwd=str(Path(workdir).expanduser() if workdir else Path.cwd()),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(int(timeout_seconds), 1),
            check=False,
        )
        result["returncode"] = completed.returncode
        result["stdout_excerpt"] = _compact(completed.stdout, 4000)
        result["stderr_excerpt"] = _compact(completed.stderr, 4000)
        result["run_status"] = "completed" if completed.returncode == 0 else "failed"
        if output_path.exists():
            try:
                verdict = json.loads(output_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                result["ok"] = False
                result["parse_error"] = str(exc)
                return result
            result["judge_output"] = verdict
        return result


def _judge_score(verdict: dict) -> dict:
    model_summary = verdict.get("summary") if isinstance(verdict.get("summary"), dict) else {}
    item_summary = _verdict_item_summary(verdict.get("items"))
    summary = item_summary if item_summary.get("total", 0) > 0 else _coerce_summary(model_summary)
    total = int(summary.get("total") or 0)
    correct = int(summary.get("correct") or 0)
    partial = int(summary.get("partial") or 0)
    if total <= 0:
        return {
            "answer_acceptance": 0.0,
            "answer_acceptance_100": 0.0,
            "official_like_binary_accuracy": 0.0,
            "official_like_binary_accuracy_100": 0.0,
            "total": 0,
            "score_source": "none",
        }
    coerced_model_summary = _coerce_summary(model_summary)
    answer_acceptance = round((correct + 0.5 * partial) / total, 4)
    official_like_binary_accuracy = round(correct / total, 4)
    return {
        "answer_acceptance": answer_acceptance,
        "answer_acceptance_100": round(answer_acceptance * 100.0, 1),
        "official_like_binary_accuracy": official_like_binary_accuracy,
        "official_like_binary_accuracy_100": round(official_like_binary_accuracy * 100.0, 1),
        "correct": correct,
        "partial": partial,
        "incorrect": int(summary.get("incorrect") or 0),
        "unjudgeable": int(summary.get("unjudgeable") or 0),
        "total": total,
        "score_source": "item_verdicts" if item_summary.get("total", 0) > 0 else "model_summary",
        "model_summary": coerced_model_summary,
        "summary_consistent": _summary_counts_equal(summary, coerced_model_summary),
    }


def _attach_task_averaged_binary_score(score: dict, diagnostics: dict) -> None:
    if not isinstance(score, dict) or not isinstance(diagnostics, dict):
        return
    task_avg = diagnostics.get("official_like_task_averaged_accuracy")
    by_type = diagnostics.get("official_like_accuracy_by_question_type")
    if task_avg is not None:
        score["official_like_task_averaged_accuracy"] = task_avg
        score["official_like_task_averaged_accuracy_100"] = round(float(task_avg) * 100.0, 1)
    if isinstance(by_type, dict):
        score["official_like_accuracy_by_question_type"] = by_type


def _attach_layered_score_report(result: dict) -> None:
    score = result.get("codex_judge_score") if isinstance(result.get("codex_judge_score"), dict) else {}
    diagnostics = result.get("judge_diagnostics") if isinstance(result.get("judge_diagnostics"), dict) else {}
    result["layered_score_report"] = _layered_score_report(score=score, diagnostics=diagnostics, result=result)


def _layered_score_report(*, score: dict, diagnostics: dict, result: dict) -> dict:
    item_count = int(diagnostics.get("item_count") or score.get("total") or 0)
    expected_item_count = int(diagnostics.get("expected_item_count") or result.get("question_count") or item_count or 0)
    measured_answer = bool(score) and int(score.get("total") or 0) > 0
    measured_diagnostics = bool(diagnostics) and item_count > 0
    primary_bottlenecks = _primary_bottlenecks(diagnostics, item_count)
    layers = {
        "retrieval_score": _not_measured_layer(
            "Requires no-key retrieval diagnostics or official evaluator artifacts; Codex judge sees completed answers."
        ),
        "projection_score": _not_measured_layer(
            "Requires projection-specific retrieval traces such as fused_library_index_bm25; this judge result only scores answers."
        ),
        "preflight_score": _not_measured_layer(
            "Requires live Agent Work Preflight health samples; this judge run is offline over benchmark artifacts."
        ),
        "answer_synthesis_score": {
            "status": "measured" if measured_answer else "not_measured",
            "score_source": score.get("score_source", "none"),
            "question_count": int(score.get("total") or 0),
            "official_like_binary_accuracy_100": score.get("official_like_binary_accuracy_100"),
            "official_like_task_averaged_accuracy_100": score.get("official_like_task_averaged_accuracy_100"),
            "internal_half_credit_100": score.get("answer_acceptance_100"),
            "correct": score.get("correct"),
            "partial": score.get("partial"),
            "incorrect": score.get("incorrect"),
            "unjudgeable": score.get("unjudgeable"),
        },
        "gap_score": _gap_layer(diagnostics, item_count),
        "progressive_retrieval_score": _not_measured_layer(
            "Requires staged recall traces showing L0/L1/L2 escalation and whether later stages changed the answer."
        ),
        "ingestion_quality_score": _not_measured_layer(
            "Requires write/capture fixtures with raw preservation, extraction quality, dedupe, conflict, and version signals."
        ),
        "self_improvement_loop_score": _self_improvement_layer(diagnostics, item_count),
    }
    not_measured_layers = [
        name
        for name in LAYERED_SCORE_NAMES
        if layers.get(name, {}).get("status") == "not_measured"
    ]
    measured_layers = [
        name
        for name in LAYERED_SCORE_NAMES
        if layers.get(name, {}).get("status") != "not_measured"
    ]
    return {
        "contract": LAYERED_SCORE_REPORT_CONTRACT,
        "score_type": "derived_diagnostic_not_official_score",
        "official_leaderboard_score": False,
        "question_count": expected_item_count,
        "coverage": {
            "item_count": item_count,
            "expected_item_count": expected_item_count,
            "complete_item_coverage": bool(diagnostics.get("complete_item_coverage")) if diagnostics else False,
        },
        "layers": layers,
        "measured_layers": measured_layers,
        "not_measured_layers": not_measured_layers,
        "primary_bottlenecks": primary_bottlenecks,
        "notes": [
            "This report explains the layer coverage of the local judge result; it does not replace the benchmark score.",
            "Only measured layers may carry numeric scores; unmeasured layers are intentionally left as diagnostic gaps.",
            "Raw/source-backed retrieval and projection scores should come from the free benchmark suite, not this answer judge.",
        ],
    }


def _not_measured_layer(reason: str) -> dict:
    return {
        "status": "not_measured",
        "score_100": None,
        "reason": reason,
    }


def _gap_layer(diagnostics: dict, item_count: int) -> dict:
    if not diagnostics or item_count <= 0:
        return _not_measured_layer("Requires judged missed cases with failure buckets or tags.")
    bucket_counts = diagnostics.get("failure_bucket_counts") if isinstance(diagnostics.get("failure_bucket_counts"), dict) else {}
    tag_counts = diagnostics.get("failure_tag_counts") if isinstance(diagnostics.get("failure_tag_counts"), dict) else {}
    explicit_gap_misses = int(bucket_counts.get("insufficient_information") or tag_counts.get("insufficient_information") or 0)
    miss_rate = round(explicit_gap_misses / item_count, 4) if item_count else 0.0
    return {
        "status": "measured_from_missed_case_tags",
        "score_100": round((1.0 - miss_rate) * 100.0, 1),
        "explicit_gap_miss_count": explicit_gap_misses,
        "explicit_gap_miss_rate": miss_rate,
        "missed_case_count": int(diagnostics.get("missed_case_count") or 0),
        "source": "failure_bucket_counts.insufficient_information or failure_tag_counts.insufficient_information",
    }


def _self_improvement_layer(diagnostics: dict, item_count: int) -> dict:
    if not diagnostics or item_count <= 0:
        return _not_measured_layer("Requires judge diagnostics with missed-case buckets and suggested next steps.")
    suggested = diagnostics.get("suggested_next_step_counts") if isinstance(diagnostics.get("suggested_next_step_counts"), dict) else {}
    status = "diagnostic_loop_ready" if bool(diagnostics.get("complete_item_coverage")) else "diagnostic_loop_incomplete_coverage"
    return {
        "status": status,
        "score_100": None,
        "missed_case_count": int(diagnostics.get("missed_case_count") or 0),
        "suggested_next_step_counts": dict(sorted(suggested.items())),
        "primary_bottlenecks": _primary_bottlenecks(diagnostics, item_count),
        "source": "judge_diagnostics.missed_cases",
    }


def _primary_bottlenecks(diagnostics: dict, item_count: int) -> list[dict]:
    if not diagnostics or item_count <= 0:
        return []
    counts = diagnostics.get("failure_bucket_counts") if isinstance(diagnostics.get("failure_bucket_counts"), dict) else {}
    missed_cases = diagnostics.get("missed_cases") if isinstance(diagnostics.get("missed_cases"), list) else []
    next_steps_by_bucket: dict[str, dict[str, int]] = {}
    for case in missed_cases:
        if not isinstance(case, dict):
            continue
        bucket = str(case.get("failure_bucket") or "")
        next_step = str(case.get("suggested_next_step") or "")
        if not bucket or not next_step:
            continue
        bucket_steps = next_steps_by_bucket.setdefault(bucket, {})
        bucket_steps[next_step] = bucket_steps.get(next_step, 0) + 1
    bottlenecks: list[dict] = []
    for bucket, count in sorted(counts.items(), key=lambda item: (-int(item[1] or 0), str(item[0]))):
        count_int = int(count or 0)
        steps = next_steps_by_bucket.get(str(bucket), {})
        suggested_next_step = ""
        if steps:
            suggested_next_step = sorted(steps.items(), key=lambda item: (-int(item[1] or 0), str(item[0])))[0][0]
        bottlenecks.append(
            {
                "failure_bucket": str(bucket),
                "count": count_int,
                "miss_rate": round(count_int / item_count, 4),
                "suggested_next_step": suggested_next_step,
            }
        )
    return bottlenecks[:8]


def _verdict_item_summary(items: Any) -> dict:
    if not isinstance(items, list):
        return {"correct": 0, "partial": 0, "incorrect": 0, "unjudgeable": 0, "total": 0}
    counts = {"correct": 0, "partial": 0, "incorrect": 0, "unjudgeable": 0}
    for row in items:
        if not isinstance(row, dict):
            continue
        verdict = str(row.get("verdict") or "unjudgeable")
        if verdict not in counts:
            verdict = "unjudgeable"
        counts[verdict] += 1
    counts["total"] = sum(counts.values())
    return counts


def _coerce_summary(summary: Any) -> dict:
    value = summary if isinstance(summary, dict) else {}
    return {
        "correct": int(value.get("correct") or 0),
        "partial": int(value.get("partial") or 0),
        "incorrect": int(value.get("incorrect") or 0),
        "unjudgeable": int(value.get("unjudgeable") or 0),
        "total": int(value.get("total") or 0),
    }


def _summary_counts_equal(left: dict, right: dict) -> bool:
    keys = ("correct", "partial", "incorrect", "unjudgeable", "total")
    return all(int(left.get(key) or 0) == int(right.get(key) or 0) for key in keys)


def _judge_diagnostics(verdict: dict, items: list[dict]) -> dict:
    by_id = {str(item.get("question_id") or ""): item for item in items}
    expected_ids = set(by_id)
    verdict_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    type_verdict_counts: dict[str, dict[str, int]] = {}
    missed_cases: list[dict] = []
    failure_bucket_counts: dict[str, int] = {}
    failure_tag_counts: dict[str, int] = {}
    suggested_next_step_counts: dict[str, int] = {}
    id_resolution_counts: dict[str, int] = {}
    unresolved_question_ids: list[str] = []
    resolved_question_ids: list[str] = []
    rows = verdict.get("items") if isinstance(verdict.get("items"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        reported_question_id = str(row.get("question_id") or "")
        question_id, id_resolution = _resolve_judge_question_id(reported_question_id, by_id)
        item = by_id.get(question_id, {})
        id_resolution_counts[id_resolution] = id_resolution_counts.get(id_resolution, 0) + 1
        if id_resolution == "unresolved":
            unresolved_question_ids.append(reported_question_id)
        else:
            resolved_question_ids.append(question_id)
        question_type = str(item.get("question_type") or "unknown")
        row_verdict = str(row.get("verdict") or "unjudgeable")
        verdict_counts[row_verdict] = verdict_counts.get(row_verdict, 0) + 1
        type_counts[question_type] = type_counts.get(question_type, 0) + 1
        per_type = type_verdict_counts.setdefault(question_type, {})
        per_type[row_verdict] = per_type.get(row_verdict, 0) + 1
        if row_verdict != "correct":
            failure = _failure_diagnostics_for_missed_case(item, row)
            failure_bucket_counts[failure["failure_bucket"]] = failure_bucket_counts.get(failure["failure_bucket"], 0) + 1
            suggested_next_step_counts[failure["suggested_next_step"]] = suggested_next_step_counts.get(failure["suggested_next_step"], 0) + 1
            for tag in failure["failure_tags"]:
                failure_tag_counts[tag] = failure_tag_counts.get(tag, 0) + 1
            missed_cases.append(
                {
                    "question_id": question_id,
                    "reported_question_id": reported_question_id,
                    "question_id_resolution": id_resolution,
                    "question_type": question_type,
                    "verdict": row_verdict,
                    "confidence": row.get("confidence"),
                    "question": _compact(item.get("question"), 220),
                    "reference_answer": _compact(item.get("reference_answer"), 220),
                    "hypothesis": _compact(item.get("hypothesis"), 220),
                    "reason": _compact(row.get("reason"), 260),
                    **failure,
                }
            )
    official_like_by_type = _official_like_accuracy_by_type(type_verdict_counts)
    return {
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "question_type_counts": dict(sorted(type_counts.items())),
        "question_type_verdict_counts": {
            question_type: dict(sorted(counts.items()))
            for question_type, counts in sorted(type_verdict_counts.items())
        },
        "official_like_accuracy_by_question_type": official_like_by_type,
        "official_like_task_averaged_accuracy": (
            round(sum(official_like_by_type.values()) / len(official_like_by_type), 4)
            if official_like_by_type
            else 0.0
        ),
        "item_count": len(rows),
        "expected_item_count": len(items),
        "unique_resolved_question_id_count": len(set(resolved_question_ids)),
        "duplicate_resolved_question_ids": _duplicates(resolved_question_ids)[:20],
        "missing_judge_question_ids": sorted(expected_ids - set(resolved_question_ids))[:20],
        "missing_judge_question_id_count": len(expected_ids - set(resolved_question_ids)),
        "complete_item_coverage": len(rows) == len(items)
        and len(set(resolved_question_ids)) == len(expected_ids)
        and not unresolved_question_ids,
        "question_id_resolution_counts": dict(sorted(id_resolution_counts.items())),
        "unresolved_question_ids": unresolved_question_ids[:20],
        "unresolved_question_id_count": len(unresolved_question_ids),
        "missed_case_count": len(missed_cases),
        "failure_bucket_counts": dict(sorted(failure_bucket_counts.items())),
        "failure_tag_counts": dict(sorted(failure_tag_counts.items())),
        "suggested_next_step_counts": dict(sorted(suggested_next_step_counts.items())),
        "missed_cases": missed_cases,
    }


def _official_like_accuracy_by_type(type_verdict_counts: dict[str, dict[str, int]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for question_type, counts in sorted(type_verdict_counts.items()):
        total = sum(int(value or 0) for value in counts.values())
        if total <= 0:
            continue
        scores[question_type] = round(int(counts.get("correct") or 0) / total, 4)
    return scores


def _failure_diagnostics_for_missed_case(item: dict, row: dict) -> dict:
    question = str(item.get("question") or "")
    question_type = str(item.get("question_type") or "unknown")
    reference_answer = str(item.get("reference_answer") or "")
    hypothesis = str(item.get("hypothesis") or "")
    reason = str(row.get("reason") or "")
    q_lower = question.lower()
    ref_lower = reference_answer.lower()
    hyp_lower = hypothesis.lower()
    combined = f"{q_lower}\n{ref_lower}\n{hyp_lower}\n{reason.lower()}"
    tags: set[str] = set()

    if re.search(r"\bhow many\b|\bnumber of\b|\bcount\b|\bdifferent\b", q_lower):
        tags.add("count")
    if any(term in q_lower for term in ("how much", "total cost", "total amount", "total money", "spent")) or "$" in question or "$" in reference_answer:
        tags.add("sum_money")
    if any(term in q_lower for term in ("in total", "combined", "total")) and any(unit in q_lower for unit in ("hour", "day", "week", "month")):
        tags.add("sum_duration")
    if "how many days" in q_lower and any(term in q_lower for term in ("between", "before", "after", "since", "take")):
        tags.add("days_difference")
    if "how many months" in q_lower or "months ago" in q_lower:
        tags.add("months_ago")
    if "had i been" in q_lower or "have i been" in q_lower or "how long" in q_lower:
        tags.add("how_long_had_been")
    if "which" in q_lower and any(term in q_lower for term in ("first", "earlier", "before", "latest", "most recent")):
        tags.add("which_first")
    if len(hypothesis) > 220 or "\n" in hypothesis or hyp_lower.startswith(("user:", "assistant:")):
        tags.add("copied_context")
    if (
        "object" in reason.lower()
        or "wrong number" in reason.lower()
        or any(term in q_lower for term in ("including", "different", "total", "cost of", "types of"))
    ) and tags.intersection({"count", "sum_money", "sum_duration"}):
        tags.add("missing_object_bound")
    if re.search(r"\b(?:\d+|\$\d+)\b", hypothesis) and re.search(r"\b(?:\d+|\$\d+)\b", reference_answer) and hypothesis.strip() != reference_answer.strip():
        tags.add("wrong_number")
    if any(term in ref_lower for term in ("no information available", "not mentioned", "not enough information", "unknown", "cannot determine")):
        tags.add("insufficient_information")
    if any(term in q_lower for term in ("current", "currently", "most recent", "latest", "now", "still")) or question_type == "knowledge-update":
        tags.add("latest_state")
    if "prefer" in q_lower or "preference" in question_type:
        tags.add("preference")

    if "insufficient_information" in tags:
        bucket = "insufficient_information"
        next_step = "add_or_tighten_evidence_gap_gate"
    elif question_type == "multi-session" and tags.intersection({"count", "sum_money", "sum_duration"}):
        bucket = "multi_session_object_aggregation"
        next_step = "add_object_bound_count_or_sum_operator"
    elif question_type == "temporal-reasoning" or tags.intersection({"days_difference", "months_ago", "how_long_had_been", "which_first"}):
        bucket = "temporal_long_tail"
        next_step = "add_source_date_aware_temporal_operator"
    elif "latest_state" in tags:
        bucket = "latest_state_update"
        next_step = "add_latest_state_selection_operator"
    elif "preference" in tags:
        bucket = "preference_direct_answer"
        next_step = "turn_preference_context_into_direct_recommendation"
    elif "copied_context" in tags:
        bucket = "assistant_context_extraction"
        next_step = "extract_short_answer_instead_of_returning_context"
    elif question_type.startswith("single-session"):
        bucket = "single_fact_extraction"
        next_step = "add_targeted_single_fact_extractor"
    elif "not found" in combined or "missing" in combined:
        bucket = "insufficient_information"
        next_step = "inspect_retrieval_coverage_or_gap_gate"
    else:
        bucket = "other"
        next_step = "inspect_missed_case_manually"

    return {
        "failure_bucket": bucket,
        "failure_tags": sorted(tags),
        "suggested_next_step": next_step,
    }


def _resolve_judge_question_id(reported_question_id: str, by_id: dict[str, dict]) -> tuple[str, str]:
    if reported_question_id in by_id:
        return reported_question_id, "exact"
    if reported_question_id:
        matches = [question_id for question_id in by_id if question_id.startswith(reported_question_id)]
        if len(matches) == 1:
            return matches[0], "unique_prefix"
    return reported_question_id, "unresolved"


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _judge_profile_label(*, model: str = "", reasoning_effort: str = "") -> str:
    normalized_model = (model or "").strip().lower()
    normalized_effort = (reasoning_effort or "").strip().lower()
    if normalized_model in {"gpt-5.5", "gpt5.5"} and normalized_effort == "xhigh":
        return "codex_gpt5_5_xhigh_internal_judge"
    if normalized_model or normalized_effort:
        return "codex_custom_internal_judge"
    return "codex_default_internal_judge"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Codex-assisted local memory benchmark judge.")
    parser.add_argument("--hypothesis", required=True, help="LongMemEval hypothesis JSONL path.")
    parser.add_argument("--reference", required=True, help="LongMemEval reference JSON path.")
    parser.add_argument("--max-questions", type=int, default=5)
    parser.add_argument(
        "--sample-tier",
        choices=sorted(CODEX_JUDGE_SAMPLE_TIERS),
        default="",
        help="Fixed judge tier: smoke=3, pilot=20, standard=50, deep=100, full=all. Overrides max questions.",
    )
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model", default="")
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        default="",
        help="Codex reasoning effort to pass as model_reasoning_effort.",
    )
    parser.add_argument("--run-codex", action="store_true", help="Actually call codex exec. Omit for preflight only.")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="When running Codex, split selected questions into batches of this size and aggregate item verdicts.",
    )
    parser.add_argument("--workdir", default="")
    parser.add_argument("--output-json", default="", help="Write the full judge result JSON to this path.")
    parser.add_argument("--missed-cases-jsonl", default="", help="Write missed cases as JSONL to this path.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--summary-json", action="store_true")
    return parser


def _summary_json(result: dict) -> dict:
    keys = [
        "ok",
        "contract",
        "mode",
        "run_requested",
        "run_status",
        "ready_to_run",
        "blocked_reasons",
        "question_count",
        "batched_judge",
        "batch_size",
        "batch_count",
        "reference_alignment",
        "sample_plan",
        "score_type",
        "judge_profile",
        "codex_judge_score",
        "judge_diagnostics",
        "layered_score_report",
        "official_leaderboard_score",
        "uses_openai_platform_api_key",
        "uses_codex_cli_auth",
        "boundary",
        "notes",
    ]
    return {key: result.get(key) for key in keys if key in result}


def _print_text(result: dict) -> None:
    print("# Memcore Cloud Codex-Assisted Judge")
    print()
    print(f"- mode: {result.get('mode')}")
    print(f"- ready to run: {str(bool(result.get('ready_to_run'))).lower()}")
    print(f"- run requested: {str(bool(result.get('run_requested'))).lower()}")
    print(f"- run status: {result.get('run_status', '')}")
    print(f"- questions: {result.get('question_count')}")
    if result.get("sample_plan"):
        plan = result["sample_plan"]
        print(f"- sample tier: {plan.get('tier')}")
        print(f"- sample strategy: {plan.get('selection_strategy')}")
    if result.get("batched_judge"):
        print(f"- batched judge: true")
        print(f"- batch size: {result.get('batch_size')}")
        print(f"- batch count: {result.get('batch_count')}")
    print("- uses OPENAI_API_KEY: false")
    print("- uses Codex CLI auth: true")
    print("- official leaderboard score: false")
    if result.get("judge_profile"):
        profile = result["judge_profile"]
        print(f"- judge profile: {profile.get('profile_label', '')}")
        if profile.get("model"):
            print(f"- model: {profile.get('model')}")
        if profile.get("reasoning_effort"):
            print(f"- reasoning effort: {profile.get('reasoning_effort')}")
    if result.get("blocked_reasons"):
        print(f"- blocked reasons: {result.get('blocked_reasons')}")
    if result.get("codex_judge_score"):
        score = result["codex_judge_score"]
        print(
            "- Codex-assisted answer acceptance: "
            f"{score.get('answer_acceptance_100', 0):.1f}/100 "
            f"({score.get('answer_acceptance', 0):.4f})"
        )
        print(
            "- Official-like binary accuracy: "
            f"{score.get('official_like_binary_accuracy_100', 0):.1f}/100 "
            f"({score.get('official_like_binary_accuracy', 0):.4f})"
        )
    if result.get("layered_score_report"):
        report = result["layered_score_report"]
        print(f"- layered score report: {report.get('contract')}")
        if report.get("primary_bottlenecks"):
            labels = [
                f"{item.get('failure_bucket')}={item.get('count')}"
                for item in report.get("primary_bottlenecks", [])[:5]
                if isinstance(item, dict)
            ]
            print(f"- primary bottlenecks: {', '.join(labels)}")
        if report.get("not_measured_layers"):
            print(f"- not measured layers: {', '.join(report.get('not_measured_layers', []))}")
    print()
    print("This is an internal Codex-assisted local judge, not an official benchmark evaluator.")


def write_codex_judge_outputs(
    result: dict,
    *,
    output_json: str | Path | None = None,
    missed_cases_jsonl: str | Path | None = None,
) -> dict:
    writes: dict[str, dict] = {}
    if output_json:
        output_path = Path(output_json).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        writes["output_json"] = {
            "path": str(output_path),
            "ok": True,
            "bytes": output_path.stat().st_size,
        }
    if missed_cases_jsonl:
        missed_path = Path(missed_cases_jsonl).expanduser()
        missed_path.parent.mkdir(parents=True, exist_ok=True)
        missed_cases = (
            result.get("judge_diagnostics", {}).get("missed_cases", [])
            if isinstance(result.get("judge_diagnostics"), dict)
            else []
        )
        with missed_path.open("w", encoding="utf-8") as handle:
            for row in missed_cases:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        writes["missed_cases_jsonl"] = {
            "path": str(missed_path),
            "ok": True,
            "rows": len(missed_cases),
            "bytes": missed_path.stat().st_size,
        }
    return writes


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    result = run_codex_assisted_judge(
        hypothesis_path=args.hypothesis,
        reference_path=args.reference,
        max_questions=args.max_questions,
        codex_bin=args.codex_bin,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        sample_tier=args.sample_tier,
        run=args.run_codex,
        timeout_seconds=args.timeout,
        workdir=args.workdir or None,
        batch_size=args.batch_size,
    )
    writes = write_codex_judge_outputs(
        result,
        output_json=args.output_json or None,
        missed_cases_jsonl=args.missed_cases_jsonl or None,
    )
    if writes:
        result["written_outputs"] = writes
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.summary_json:
        print(json.dumps(_summary_json(result), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_text(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
