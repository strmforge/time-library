#!/usr/bin/env python3
"""OpenAI-compatible model judge for LongMemEval hypothesis artifacts."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

try:
    from src.codex_memory_judge import (
        CODEX_JUDGE_CONTRACT,
        _attach_layered_score_report,
        _attach_task_averaged_binary_score,
        _chunk_items,
        _compact,
        _judge_diagnostics,
        _judge_score,
        _verdict_item_summary,
        build_codex_judge_prompt,
        load_longmemeval_judge_items,
        longmemeval_reference_alignment,
        select_longmemeval_judge_sample,
        write_codex_judge_outputs,
    )
    from src.eval_resource_ledger import (
        append_jsonl,
        atomic_write_json,
        finish_run_ledger,
        load_checkpoint,
        mark_case_completed,
        resource_sample,
        save_checkpoint,
        start_run_ledger,
    )
    from src.evidence_bound_model import (
        EvidenceBoundModelConfig,
        _extract_json_object,
        _http_chat_completion,
        default_model_config,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    from codex_memory_judge import (
        CODEX_JUDGE_CONTRACT,
        _attach_layered_score_report,
        _attach_task_averaged_binary_score,
        _chunk_items,
        _compact,
        _judge_diagnostics,
        _judge_score,
        _verdict_item_summary,
        build_codex_judge_prompt,
        load_longmemeval_judge_items,
        longmemeval_reference_alignment,
        select_longmemeval_judge_sample,
        write_codex_judge_outputs,
    )
    from eval_resource_ledger import (
        append_jsonl,
        atomic_write_json,
        finish_run_ledger,
        load_checkpoint,
        mark_case_completed,
        resource_sample,
        save_checkpoint,
        start_run_ledger,
    )
    from evidence_bound_model import (
        EvidenceBoundModelConfig,
        _extract_json_object,
        _http_chat_completion,
        default_model_config,
    )


MODEL_MEMORY_JUDGE_CONTRACT = "openai_compatible_memory_judge.v2026.6.20"


def _coerce_config(
    *,
    provider: str = "",
    model: str = "",
    base_url: str = "",
    api_key_env: str = "",
    timeout_seconds: int = 120,
    max_tokens: int = 0,
) -> EvidenceBoundModelConfig:
    config = default_model_config(provider=provider, model=model, base_url=base_url)
    if api_key_env:
        config = EvidenceBoundModelConfig(
            provider=config.provider,
            model=config.model,
            base_url=config.base_url,
            api_key_env=api_key_env,
            timeout_seconds=config.timeout_seconds,
            max_tokens=config.max_tokens,
        )
    return EvidenceBoundModelConfig(
        provider=config.provider,
        model=model or config.model,
        base_url=base_url or config.base_url,
        api_key_env=api_key_env or config.api_key_env,
        timeout_seconds=max(int(timeout_seconds or config.timeout_seconds or 120), 1),
        max_tokens=max(int(max_tokens or config.max_tokens or 0), 0),
    )


def _message_from_prompt(prompt: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "You judge memory benchmark answers and return JSON only.",
        },
        {"role": "user", "content": prompt},
    ]


def _run_model_judge_batch(
    *,
    items: list[dict],
    config: EvidenceBoundModelConfig,
) -> dict[str, Any]:
    prompt = build_codex_judge_prompt(items)
    started = time.perf_counter()
    response = _http_chat_completion(_message_from_prompt(prompt), config)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    result: dict[str, Any] = {
        "elapsed_ms": elapsed_ms,
        "model_call_performed": True,
        "provider": config.provider,
        "model": config.model,
        "api_key_env": config.api_key_env,
        "api_key_present": config.api_key_present,
    }
    if not response.get("ok"):
        result.update(
            {
                "ok": False,
                "run_status": "model_error",
                "error": response.get("error", "model_error"),
            }
        )
        return result
    parsed = _extract_json_object(response.get("content", ""))
    if not parsed:
        result.update(
            {
                "ok": False,
                "run_status": "parse_error",
                "parse_error": "non_json_or_empty_model_response",
                "content_excerpt": _compact(response.get("content", ""), 1200),
            }
        )
        return result
    parsed = _normalize_model_judge_output(parsed)
    parsed["contract"] = str(parsed.get("contract") or CODEX_JUDGE_CONTRACT)
    result.update(
        {
            "ok": True,
            "run_status": "completed",
            "judge_output": parsed,
        }
    )
    return result


def _normalize_model_judge_output(parsed: dict) -> dict:
    """Normalize common cheap-model JSON shapes into the judge item schema."""

    normalized = dict(parsed or {})
    raw_items = normalized.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        for alias in ("judgment", "judgements", "judgments", "verdicts", "result", "results"):
            value = normalized.get(alias)
            if isinstance(value, list) and value:
                raw_items = value
                break
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    items: list[dict] = []
    for row in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(row, dict):
            continue
        item = {
            "question_id": str(row.get("question_id") or row.get("id") or ""),
            "verdict": str(row.get("verdict") or row.get("judge_verdict") or row.get("label") or "unjudgeable"),
            "confidence": row.get("confidence", 0.0),
            "reason": str(row.get("reason") or row.get("rationale") or row.get("explanation") or ""),
        }
        if item["verdict"] not in {"correct", "partial", "incorrect", "unjudgeable"}:
            lowered = item["verdict"].strip().lower()
            if lowered in {"yes", "true", "right", "match", "matched", "accurate"}:
                item["verdict"] = "correct"
            elif lowered in {"partially_correct", "partly_correct", "half"}:
                item["verdict"] = "partial"
            elif lowered in {"no", "false", "wrong", "mismatch", "not_correct"}:
                item["verdict"] = "incorrect"
            else:
                item["verdict"] = "unjudgeable"
        if not item["reason"]:
            item["reason"] = "model returned verdict without a reason"
        items.append(item)
    normalized["items"] = items
    if not isinstance(normalized.get("summary"), dict) or int((normalized.get("summary") or {}).get("total") or 0) != len(items):
        normalized["summary"] = _verdict_item_summary(items)
    return normalized


def run_model_memory_judge(
    *,
    hypothesis_path: str | Path,
    reference_path: str | Path,
    max_questions: int = 5,
    sample_tier: str = "",
    provider: str = "",
    model: str = "",
    base_url: str = "",
    api_key_env: str = "",
    timeout_seconds: int = 120,
    max_tokens: int = 0,
    batch_size: int = 10,
    run: bool = False,
    out_dir: str | Path | None = None,
    resume: bool = False,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    config = _coerce_config(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
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
    reference_alignment = longmemeval_reference_alignment(
        hypothesis_path=hypothesis_path,
        reference_path=reference_path,
    )
    resolved_out_dir = Path(out_dir).expanduser() if out_dir else None
    checkpoint_path = (resolved_out_dir / "checkpoint.json") if resolved_out_dir else None
    case_ledger_path = (resolved_out_dir / "case-ledger.jsonl") if resolved_out_dir else None
    run_ledger_path = (resolved_out_dir / "run-ledger.json") if resolved_out_dir else None
    batch_size = max(int(batch_size or 1), 1)
    result: dict[str, Any] = {
        "ok": True,
        "contract": MODEL_MEMORY_JUDGE_CONTRACT,
        "mode": "openai_compatible_memory_judge",
        "run_requested": bool(run),
        "run_status": "preflight_only",
        "ready_to_run": bool(reference_alignment.get("ok") and config.api_key_present and config.base_url and config.model),
        "blocked_reasons": [],
        "hypothesis_path": str(Path(hypothesis_path).expanduser()),
        "reference_path": str(Path(reference_path).expanduser()),
        "reference_alignment": reference_alignment,
        "question_count": len(items),
        "sample_plan": sample_plan,
        "batch_size": batch_size,
        "batch_count": len(_chunk_items(items, batch_size)) if items else 0,
        "official_leaderboard_score": False,
        "score_type": "openai_compatible_local_judge_diagnostic",
        "judge_profile": {
            "provider": config.provider,
            "model": config.model,
            "api_key_env": config.api_key_env,
            "api_key_present": config.api_key_present,
            "base_url_present": bool(config.base_url),
            "uses_openai_platform_api_key": config.api_key_env == "OPENAI_API_KEY",
        },
        "boundary": {
            "official_leaderboard_score": False,
            "official_evaluator_replacement": False,
            "internal_quality_signal": True,
            "model_judge": True,
            "memory_write_performed": False,
            "raw_write_performed": False,
            "platform_write_performed": False,
            "secret_values_returned": False,
        },
        "notes": [
            "This judges LongMemEval hypotheses with an OpenAI-compatible model endpoint.",
            "It is useful for local regression and competitor-style model-heavy scoring.",
            "It is not an official LongMemEval leaderboard score unless run through the accepted official evaluator path.",
        ],
    }
    if not reference_alignment.get("ok"):
        result["blocked_reasons"].append("reference_alignment")
    if not config.api_key_present:
        result["blocked_reasons"].append("api_key_env")
    if not config.base_url:
        result["blocked_reasons"].append("base_url")
    if not config.model:
        result["blocked_reasons"].append("model")
    result["ready_to_run"] = not result["blocked_reasons"]
    if not run:
        result["prompt_preview"] = _compact(build_codex_judge_prompt(items[:batch_size]), 3000)
        _attach_layered_score_report(result)
        return result
    if not result["ready_to_run"]:
        result["ok"] = False
        result["run_status"] = "blocked_preflight_failed"
        _attach_layered_score_report(result)
        return result

    if resolved_out_dir:
        resolved_out_dir.mkdir(parents=True, exist_ok=True)
    ledger = None
    if run_ledger_path:
        ledger = start_run_ledger(
            profile="openai_compatible_memory_judge",
            dataset="longmemeval",
            split="oracle",
            sample_count=len(items),
            judge=config.model,
            model_profile=config.provider,
            resume_enabled=resume,
            checkpoint_path=checkpoint_path,
            repo_root=repo_root,
            run_id=f"model-memory-judge-{config.provider}-{config.model}",
        )
        atomic_write_json(run_ledger_path, ledger)

    checkpoint = load_checkpoint(checkpoint_path) if checkpoint_path else {"completed_case_ids": []}
    completed_ids = set(str(item) for item in checkpoint.get("completed_case_ids") or [])
    chunks = _chunk_items(items, batch_size)
    merged_items: list[dict] = []
    batch_results: list[dict] = []
    all_batches_ok = True

    for batch_index, chunk in enumerate(chunks, start=1):
        batch_id = f"batch-{batch_index:04d}"
        if resume and batch_id in completed_ids:
            batch_results.append(
                {
                    "batch_index": batch_index,
                    "batch_id": batch_id,
                    "run_status": "skipped_resume",
                    "question_count": len(chunk),
                }
            )
            continue
        batch_record, batch_items = _run_logged_judge_chunk(
            chunk=chunk,
            config=config,
            batch_id=batch_id,
            batch_index=batch_index,
            case_ledger_path=case_ledger_path,
        )
        if not batch_record["ok"] and len(chunk) > 1:
            sub_records: list[dict] = []
            sub_items: list[dict] = []
            sub_ok = True
            for sub_index, item in enumerate(chunk, start=1):
                sub_record, judged_items = _run_logged_judge_chunk(
                    chunk=[item],
                    config=config,
                    batch_id=f"{batch_id}.{sub_index}",
                    batch_index=batch_index,
                    case_ledger_path=case_ledger_path,
                    fallback_from=batch_id,
                )
                sub_records.append(sub_record)
                sub_items.extend(judged_items)
                if not sub_record["ok"]:
                    sub_ok = False
                    break
            if sub_ok:
                batch_record = {
                    "batch_index": batch_index,
                    "batch_id": batch_id,
                    "question_count": len(chunk),
                    "ok": True,
                    "run_status": "completed_via_single_item_fallback",
                    "fallback_from_failed_batch": True,
                    "fallback_sub_batch_count": len(sub_records),
                    "fallback_records": sub_records,
                    "judge_score": _judge_score(
                        {
                            "items": sub_items,
                            "summary": _verdict_item_summary(sub_items),
                        }
                    ),
                    "judge_diagnostics": {
                        key: _judge_diagnostics(
                            {
                                "items": sub_items,
                                "summary": _verdict_item_summary(sub_items),
                            },
                            chunk,
                        ).get(key)
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
                batch_items = sub_items
        merged_items.extend(batch_items)
        batch_results.append(batch_record)
        if not batch_record["ok"]:
            all_batches_ok = False
            break
        if checkpoint_path:
            mark_case_completed(checkpoint, batch_id)
            save_checkpoint(checkpoint_path, checkpoint)

    merged_verdict = {
        "contract": CODEX_JUDGE_CONTRACT,
        "items": merged_items,
        "summary": _verdict_item_summary(merged_items),
    }
    result["run_status"] = "completed" if all_batches_ok and len(batch_results) == len(chunks) else "failed_batch"
    result["batch_results"] = batch_results
    result["judge_output"] = merged_verdict
    result["codex_judge_score"] = _judge_score(merged_verdict)
    result["judge_diagnostics"] = _judge_diagnostics(merged_verdict, items)
    _attach_task_averaged_binary_score(result["codex_judge_score"], result["judge_diagnostics"])
    _attach_layered_score_report(result)
    result["ok"] = all_batches_ok and bool(result["judge_diagnostics"].get("complete_item_coverage"))
    if ledger is not None and run_ledger_path:
        finish_run_ledger(ledger, status="ok" if result["ok"] else "failed")
        atomic_write_json(run_ledger_path, ledger)
    return result


def _run_logged_judge_chunk(
    *,
    chunk: list[dict],
    config: EvidenceBoundModelConfig,
    batch_id: str,
    batch_index: int,
    case_ledger_path: Path | None,
    fallback_from: str = "",
) -> tuple[dict, list[dict]]:
    before = resource_sample()
    batch_started = time.perf_counter()
    invocation = _run_model_judge_batch(items=chunk, config=config)
    after = resource_sample()
    elapsed_ms = round((time.perf_counter() - batch_started) * 1000.0, 3)
    verdict = invocation.get("judge_output") if isinstance(invocation.get("judge_output"), dict) else {}
    diagnostics = _judge_diagnostics(verdict, chunk) if verdict else {
        "item_count": 0,
        "expected_item_count": len(chunk),
        "complete_item_coverage": False,
    }
    judged_items = [
        row
        for row in (verdict.get("items") if isinstance(verdict.get("items"), list) else [])
        if isinstance(row, dict)
    ]
    batch_record = {
        "batch_index": batch_index,
        "batch_id": batch_id,
        "question_count": len(chunk),
        "ok": bool(invocation.get("ok")) and bool(diagnostics.get("complete_item_coverage")),
        "run_status": invocation.get("run_status", ""),
        "elapsed_ms": invocation.get("elapsed_ms", elapsed_ms),
        "judge_score": _judge_score(verdict) if verdict else {"total": 0},
        "judge_diagnostics": {
            key: diagnostics.get(key)
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
    if fallback_from:
        batch_record["fallback_from"] = fallback_from
    if invocation.get("error"):
        batch_record["error"] = invocation.get("error")
    if invocation.get("parse_error"):
        batch_record["parse_error"] = invocation.get("parse_error")
    if case_ledger_path:
        cpu_delta = (
            float(after.get("cpu_user_seconds") or 0)
            + float(after.get("cpu_system_seconds") or 0)
            - float(before.get("cpu_user_seconds") or 0)
            - float(before.get("cpu_system_seconds") or 0)
        )
        append_jsonl(
            case_ledger_path,
            {
                "contract": "model_memory_judge_batch_ledger.v2026.6.20",
                "batch_id": batch_id,
                "batch_index": batch_index,
                "status": "ok" if batch_record["ok"] else "failed",
                "elapsed_ms": elapsed_ms,
                "cpu_seconds_delta": round(cpu_delta, 6),
                "rss_bytes_sample": int(after.get("rss_peak_bytes") or 0),
                "question_count": len(chunk),
                "provider": config.provider,
                "model": config.model,
                "fallback_from": fallback_from,
                "result": batch_record,
            },
        )
    return batch_record, judged_items


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an OpenAI-compatible local memory benchmark judge.")
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--max-questions", type=int, default=5)
    parser.add_argument("--sample-tier", choices=["smoke", "pilot", "standard", "deep", "full"], default="")
    parser.add_argument("--provider", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key-env", default="")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-tokens", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--run-model", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--missed-cases-jsonl", default="")
    parser.add_argument("--summary-json", action="store_true")
    parser.add_argument("--json", action="store_true")
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
        "boundary",
        "notes",
    ]
    return {key: result.get(key) for key in keys if key in result}


def _print_text(result: dict) -> None:
    print("# Memcore Cloud Model Judge")
    print()
    print(f"- mode: {result.get('mode')}")
    print(f"- ready to run: {str(bool(result.get('ready_to_run'))).lower()}")
    print(f"- run requested: {str(bool(result.get('run_requested'))).lower()}")
    print(f"- run status: {result.get('run_status', '')}")
    print(f"- questions: {result.get('question_count')}")
    profile = result.get("judge_profile") if isinstance(result.get("judge_profile"), dict) else {}
    print(f"- provider: {profile.get('provider', '')}")
    print(f"- model: {profile.get('model', '')}")
    print(f"- api key present: {str(bool(profile.get('api_key_present'))).lower()}")
    print("- official leaderboard score: false")
    if result.get("codex_judge_score"):
        score = result["codex_judge_score"]
        print(f"- official-like binary accuracy: {score.get('official_like_binary_accuracy_100', 0):.1f}/100")
        print(f"- internal half-credit: {score.get('answer_acceptance_100', 0):.1f}/100")
    if result.get("blocked_reasons"):
        print(f"- blocked reasons: {result.get('blocked_reasons')}")


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = run_model_memory_judge(
        hypothesis_path=args.hypothesis,
        reference_path=args.reference,
        max_questions=args.max_questions,
        sample_tier=args.sample_tier,
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        timeout_seconds=args.timeout,
        max_tokens=args.max_tokens,
        batch_size=args.batch_size,
        run=args.run_model,
        out_dir=args.out_dir or None,
        resume=args.resume,
        repo_root=Path(__file__).resolve().parents[1],
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
