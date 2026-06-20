#!/usr/bin/env python3
"""Run model-heavy QA trials with per-case checkpoint and resource ledger."""

from __future__ import annotations

import argparse
import json
import os
import re
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

from eval_resource_ledger import (  # noqa: E402
    append_jsonl,
    atomic_write_json,
    finish_run_ledger,
    load_checkpoint,
    mark_case_completed,
    resource_sample,
    save_checkpoint,
    start_run_ledger,
)
from official_memory_benchmarks import (  # noqa: E402
    DEFAULT_ANSWER_MODE,
    DEFAULT_ANSWER_MODEL_LOCAL_POSTPROCESS_POLICY,
    DEFAULT_CACHE_ROOT,
    DEFAULT_CONTEXT_DECAY,
    DEFAULT_CONTEXT_ROUTE_AGGRESSIVE_DECAY,
    DEFAULT_CONTEXT_ROUTE_UNIT_THRESHOLD,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_QA_TRIAL_MODEL_KEY,
    DEFAULT_RETRIEVAL_MODE,
    DEFAULT_SESSION_CANDIDATES,
    _answer_model_call_stats,
    _answer_synthesis_for_mode,
    _as_list,
    _dict,
    _longmemeval_local_rough_alignment,
    _locomo_official_like_f1,
    _rank_case_for_qa_trial,
    _summary_json,
    load_cases,
    load_json,
    resolve_dataset_path,
    run_official_qa_trial,
)


MODEL_HEAVY_QA_RUNNER_CONTRACT = "model_heavy_qa_runner.v2026.6.20"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())[:120] or "run"


def _case_id(case: dict[str, Any]) -> str:
    return str(case.get("case_id") or case.get("question_id") or "")


def _locomo_rows_by_question_id(raw_data: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_sample: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        sample_id = str(_dict(case.get("metadata")).get("sample_id") or str(case.get("question_id") or "").split(":q", 1)[0])
        by_sample.setdefault(sample_id, []).append(case)

    rows: dict[str, dict[str, Any]] = {}
    for sample in raw_data:
        if not isinstance(sample, dict):
            continue
        sample_id = str(sample.get("sample_id") or "")
        sample_cases = by_sample.get(sample_id, [])
        for index, qa in enumerate((sample.get("qa") or [])[: len(sample_cases)]):
            if isinstance(qa, dict) and index < len(sample_cases):
                rows[str(sample_cases[index].get("question_id") or "")] = dict(qa)
    return rows


def _read_completed_output(path: Path, *, dataset: str, prediction_key: str = "") -> dict[str, Any]:
    if not path.exists():
        return {}
    if dataset == "longmemeval":
        rows: dict[str, Any] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            rows[str(row.get("question_id") or "")] = row
        return rows
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows: dict[str, Any] = {}
    for sample in payload if isinstance(payload, list) else []:
        if not isinstance(sample, dict):
            continue
        for qa in sample.get("qa") or []:
            if isinstance(qa, dict):
                qid = str(qa.get("question_id") or qa.get("id") or "")
                if not qid and prediction_key:
                    qid = str(qa.get("_memcore_question_id") or "")
                if qid:
                    rows[qid] = qa
    return rows


def _load_case_id_filter(path: str = "", value: str = "") -> set[str]:
    ids: set[str] = set()
    for part in re.split(r"[\s,，]+", str(value or "")):
        cleaned = part.strip()
        if cleaned:
            ids.add(cleaned)
    if path:
        source = Path(path).expanduser()
        text = source.read_text(encoding="utf-8")
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            for item in parsed:
                cleaned = str(item or "").strip()
                if cleaned:
                    ids.add(cleaned)
        elif isinstance(parsed, dict):
            for key in ("case_ids", "question_ids", "ids"):
                if isinstance(parsed.get(key), list):
                    for item in parsed[key]:
                        cleaned = str(item or "").strip()
                        if cleaned:
                            ids.add(cleaned)
        else:
            for line in text.splitlines():
                cleaned = line.strip()
                if cleaned and not cleaned.startswith("#"):
                    ids.add(cleaned)
    return ids


def _append_output_row(path: Path, *, dataset: str, row: dict[str, Any], sample_id: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if dataset == "longmemeval":
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return

    payload: list[dict[str, Any]]
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            payload = loaded if isinstance(loaded, list) else []
        except Exception:
            payload = []
    else:
        payload = []
    target_sample = sample_id or "sample"
    sample = next((item for item in payload if isinstance(item, dict) and item.get("sample_id") == target_sample), None)
    if sample is None:
        sample = {"sample_id": target_sample, "qa": []}
        payload.append(sample)
    sample.setdefault("qa", []).append(row)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _stats_from_rows(
    rows: list[dict[str, Any]],
    *,
    dataset: str,
    model_key: str,
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if dataset == "locomo":
        f1_key = f"{model_key}_f1"
        recall_key = f"{model_key}_recall"
        f1_values = [float(row.get(f1_key) or 0.0) for row in rows]
        recall_values = [float(row.get(recall_key) or 0.0) for row in rows]
        category: dict[str, list[float]] = {}
        for row in rows:
            category.setdefault(str(row.get("category") or ""), []).append(float(row.get(f1_key) or 0.0))
        return {
            "question_count": len(rows),
            "official_like_local_f1": round(sum(f1_values) / len(f1_values), 4) if f1_values else 0.0,
            "official_like_local_recall": round(sum(recall_values) / len(recall_values), 4) if recall_values else 0.0,
            "category_f1": {
                key: round(sum(values) / len(values), 4) if values else 0.0
                for key, values in sorted(category.items())
            },
        }
    rough = _longmemeval_local_rough_alignment(rows, cases or [])
    return {
        "question_count": len(rows),
        "local_rough_alignment": rough,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run model-heavy QA with checkpoint/resume.")
    parser.add_argument("--dataset", choices=("locomo", "longmemeval"), required=True)
    parser.add_argument("--split", choices=("oracle", "s", "m"), default="oracle")
    parser.add_argument("--data", default="")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--cache-root", default=str(DEFAULT_CACHE_ROOT))
    parser.add_argument("--max-questions", type=int, default=None)
    parser.add_argument("--case-ids", default="", help="Comma/space separated case ids to run after dataset loading.")
    parser.add_argument("--case-ids-file", default="", help="Text, JSON list, or JSON object with case_ids/question_ids/ids.")
    parser.add_argument("--retrieval-mode", default=DEFAULT_RETRIEVAL_MODE)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--context-window", type=int, default=DEFAULT_CONTEXT_WINDOW)
    parser.add_argument("--context-decay", type=float, default=DEFAULT_CONTEXT_DECAY)
    parser.add_argument("--context-route-unit-threshold", type=int, default=DEFAULT_CONTEXT_ROUTE_UNIT_THRESHOLD)
    parser.add_argument("--context-route-aggressive-decay", type=float, default=DEFAULT_CONTEXT_ROUTE_AGGRESSIVE_DECAY)
    parser.add_argument("--session-candidates", type=int, default=DEFAULT_SESSION_CANDIDATES)
    parser.add_argument("--library-index-candidates", type=int, default=5)
    parser.add_argument("--qa-output", default="")
    parser.add_argument("--qa-model-key", default=DEFAULT_QA_TRIAL_MODEL_KEY)
    parser.add_argument("--answer-mode", choices=("extractive", "evidence-bound-model"), default=DEFAULT_ANSWER_MODE)
    parser.add_argument("--run-answer-model", action="store_true")
    parser.add_argument("--answer-model-provider", default="")
    parser.add_argument("--answer-model-name", default="")
    parser.add_argument("--answer-model-base-url", default="")
    parser.add_argument("--answer-model-call-policy", choices=("always", "auto", "never"), default="always")
    parser.add_argument("--answer-model-max-evidence-items", type=int, default=20)
    parser.add_argument(
        "--answer-model-evidence-pack-mode",
        choices=("ranked", "entity-token", "entity_token", "adaptive-aggregation", "adaptive_aggregation"),
        default="ranked",
    )
    parser.add_argument(
        "--answer-model-local-postprocess-policy",
        choices=("off", "minimal", "guarded", "legacy"),
        default=DEFAULT_ANSWER_MODEL_LOCAL_POSTPROCESS_POLICY,
        help="Local answer rewrite policy after model answering. off leaves model output untouched; legacy reproduces old draft/expander/count behavior.",
    )
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep-ms-between-cases", type=int, default=0)
    parser.add_argument("--max-runtime-minutes", type=float, default=0)
    parser.add_argument("--summary-json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_slug = f"model-heavy-{args.dataset}-{_safe_name(args.answer_model_name or args.answer_model_provider or 'model')}"
    out_dir = Path(args.out_dir).expanduser() if args.out_dir else ROOT / "benchmarks" / "eval-runs" / run_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.qa_output).expanduser() if args.qa_output else out_dir / ("hypotheses.jsonl" if args.dataset == "longmemeval" else "qa.json")
    checkpoint_path = out_dir / "checkpoint.json"
    case_ledger_path = out_dir / "case-ledger.jsonl"
    summary_path = out_dir / "summary.json"
    run_ledger_path = out_dir / "run-ledger.json"

    path = resolve_dataset_path(
        dataset=args.dataset,
        split=args.split,
        data_path=args.data or None,
        download=args.download,
        cache_root=args.cache_root,
    )
    cases = load_cases(
        dataset=args.dataset,
        split=args.split,
        data_path=path,
        max_questions=args.max_questions,
    )
    case_id_filter = _load_case_id_filter(args.case_ids_file, args.case_ids)
    if case_id_filter:
        cases = [case for case in cases if (_case_id(case) or "") in case_id_filter]
    raw_data = load_json(path)
    locomo_rows = _locomo_rows_by_question_id(raw_data, cases) if args.dataset == "locomo" else {}
    completed_outputs = _read_completed_output(output_path, dataset=args.dataset, prediction_key=args.qa_model_key)

    ledger = start_run_ledger(
        profile="model_heavy_qa",
        host_label="",
        dataset=args.dataset,
        split=args.split,
        sample_count=len(cases),
        retrieval_mode=args.retrieval_mode,
        top_k=args.top_k,
        answerer=args.answer_model_name or args.answer_model_provider,
        model_profile=args.answer_model_call_policy,
        resume_enabled=args.resume,
        checkpoint_path=checkpoint_path,
        repo_root=ROOT,
        run_id=run_slug,
    )
    atomic_write_json(run_ledger_path, ledger)
    checkpoint = load_checkpoint(checkpoint_path)
    completed = set(str(item) for item in checkpoint.get("completed_case_ids") or [])
    rows_for_stats: list[dict[str, Any]] = list(completed_outputs.values())
    stats = {"case_count": len(cases), "ran": 0, "skipped": 0, "failed": 0}
    started = time.perf_counter()

    for index, case in enumerate(cases, start=1):
        case_id = _case_id(case) or str(index)
        if args.resume and not args.force and (case_id in completed or case_id in completed_outputs):
            stats["skipped"] += 1
            continue
        if args.max_runtime_minutes and (time.perf_counter() - started) > args.max_runtime_minutes * 60:
            stats["stopped_reason"] = "max_runtime_minutes"
            break

        before = resource_sample()
        case_started = time.perf_counter()
        status = "ok"
        result: dict[str, Any] = {}
        try:
            ranked = _rank_case_for_qa_trial(
                case,
                top_k=args.top_k,
                retrieval_mode=args.retrieval_mode,
                context_window=args.context_window,
                context_decay=args.context_decay,
                context_route_unit_threshold=args.context_route_unit_threshold,
                context_route_aggressive_decay=args.context_route_aggressive_decay,
                session_candidates=args.session_candidates,
                library_index_candidates=args.library_index_candidates,
            )
            synthesis = _answer_synthesis_for_mode(
                case,
                ranked,
                answer_mode=args.answer_mode,
                run_answer_model=args.run_answer_model,
                answer_model_provider=args.answer_model_provider,
                answer_model_name=args.answer_model_name,
                answer_model_base_url=args.answer_model_base_url,
                answer_model_call_policy=args.answer_model_call_policy,
                answer_model_max_evidence_items=args.answer_model_max_evidence_items,
                answer_model_evidence_pack_mode=args.answer_model_evidence_pack_mode,
                answer_model_local_postprocess_policy=args.answer_model_local_postprocess_policy,
            )
            context_refs = [str(item.get("evidence_ref") or item.get("source_id") or "") for item in ranked if str(item.get("evidence_ref") or item.get("source_id") or "")]
            if args.dataset == "locomo":
                qa = dict(locomo_rows.get(case_id) or {})
                qa["_memcore_question_id"] = case_id
                qa[f"{args.qa_model_key}_prediction"] = str(synthesis.get("answer") or "")
                qa[f"{args.qa_model_key}_context"] = context_refs
                expected = [str(ref) for ref in _as_list(qa.get("evidence")) if str(ref)]
                recall = (len(set(expected) & set(context_refs)) / len(expected)) if expected else 1.0
                f1 = _locomo_official_like_f1(qa[f"{args.qa_model_key}_prediction"], qa.get("answer", ""), qa.get("category"))
                qa[f"{args.qa_model_key}_f1"] = round(f1, 3)
                qa[f"{args.qa_model_key}_recall"] = round(recall, 3)
                qa[f"{args.qa_model_key}_answer_strategy"] = synthesis.get("strategy", "")
                qa[f"{args.qa_model_key}_model_call_performed"] = bool(synthesis.get("model_call_performed"))
                qa[f"{args.qa_model_key}_model_verdict"] = synthesis.get("model_verdict", "")
                qa[f"{args.qa_model_key}_model_evidence_count"] = synthesis.get("model_evidence_count", 0)
                qa[f"{args.qa_model_key}_model_max_evidence_items"] = synthesis.get("model_max_evidence_items", 0)
                qa[f"{args.qa_model_key}_model_evidence_pack_mode"] = synthesis.get("model_evidence_pack_mode", "")
                qa[f"{args.qa_model_key}_model_local_postprocess_policy"] = synthesis.get("model_local_postprocess_policy", "")
                qa[f"{args.qa_model_key}_model_source_phrase_expander_applied"] = bool(synthesis.get("model_source_phrase_expander_applied"))
                qa[f"{args.qa_model_key}_model_source_phrase_expander_original_answer"] = synthesis.get("model_source_phrase_expander_original_answer", "")
                qa[f"{args.qa_model_key}_model_source_phrase_expander_answer"] = synthesis.get("model_source_phrase_expander_answer", "")
                qa[f"{args.qa_model_key}_model_source_phrase_expander_ref"] = synthesis.get("model_source_phrase_expander_ref", "")
                qa[f"{args.qa_model_key}_model_source_phrase_expander_reason"] = synthesis.get("model_source_phrase_expander_reason", "")
                qa[f"{args.qa_model_key}_model_count_answer_completion_applied"] = bool(synthesis.get("model_count_answer_completion_applied"))
                qa[f"{args.qa_model_key}_model_count_answer_completion_original_answer"] = synthesis.get("model_count_answer_completion_original_answer", "")
                qa[f"{args.qa_model_key}_model_count_answer_completion_answer"] = synthesis.get("model_count_answer_completion_answer", "")
                qa[f"{args.qa_model_key}_model_count_answer_completion_reason"] = synthesis.get("model_count_answer_completion_reason", "")
                row = qa
                sample_id = str(_dict(case.get("metadata")).get("sample_id") or "sample")
                _append_output_row(output_path, dataset=args.dataset, row=row, sample_id=sample_id)
            else:
                row = {
                    "question_id": case_id,
                    "hypothesis": synthesis.get("answer", ""),
                    "memcore_answer_strategy": synthesis.get("strategy", ""),
                    "memcore_answer_mode": synthesis.get("answer_mode", args.answer_mode),
                    "memcore_answer_model_call_performed": bool(synthesis.get("model_call_performed")),
                    "memcore_answer_model_verdict": synthesis.get("model_verdict", ""),
                    "memcore_answer_model_evidence_count": synthesis.get("model_evidence_count", 0),
                    "memcore_answer_model_max_evidence_items": synthesis.get("model_max_evidence_items", 0),
                    "memcore_answer_model_evidence_pack_mode": synthesis.get("model_evidence_pack_mode", ""),
                    "memcore_answer_model_local_postprocess_policy": synthesis.get("model_local_postprocess_policy", ""),
                    "memcore_answer_model_local_postprocess_flags": synthesis.get("model_local_postprocess_flags", {}),
                    "memcore_answer_model_draft_fallback_applied": bool(synthesis.get("model_draft_fallback_applied")),
                    "memcore_answer_model_aggregation_draft_guardrail_applied": bool(synthesis.get("model_aggregation_draft_guardrail_applied")),
                    "memcore_answer_model_calculation_items": synthesis.get("model_calculation_items", []),
                    "memcore_answer_model_calculation_notes": synthesis.get("model_calculation_notes", ""),
                    "memcore_answer_model_source_phrase_expander_applied": bool(synthesis.get("model_source_phrase_expander_applied")),
                    "memcore_answer_model_source_phrase_expander_original_answer": synthesis.get("model_source_phrase_expander_original_answer", ""),
                    "memcore_answer_model_source_phrase_expander_answer": synthesis.get("model_source_phrase_expander_answer", ""),
                    "memcore_answer_model_source_phrase_expander_ref": synthesis.get("model_source_phrase_expander_ref", ""),
                    "memcore_answer_model_source_phrase_expander_reason": synthesis.get("model_source_phrase_expander_reason", ""),
                    "memcore_answer_model_count_answer_completion_applied": bool(synthesis.get("model_count_answer_completion_applied")),
                    "memcore_answer_model_count_answer_completion_original_answer": synthesis.get("model_count_answer_completion_original_answer", ""),
                    "memcore_answer_model_count_answer_completion_answer": synthesis.get("model_count_answer_completion_answer", ""),
                    "memcore_answer_model_count_answer_completion_reason": synthesis.get("model_count_answer_completion_reason", ""),
                    "memcore_extractive_draft_answer": synthesis.get("extractive_draft_answer", ""),
                    "memcore_extractive_draft_strategy": synthesis.get("extractive_draft_strategy", ""),
                    "memcore_answer_supporting_refs": synthesis.get("supporting_refs", []),
                    "memcore_context": [
                        {
                            "source_id": item.get("source_id", ""),
                            "session_id": item.get("session_id", ""),
                            "evidence_ref": item.get("evidence_ref", ""),
                            "text": str(item.get("text", ""))[:300],
                        }
                        for item in ranked
                    ],
                }
                _append_output_row(output_path, dataset=args.dataset, row=row)
            result = {
                "status": status,
                "question_id": case_id,
                "retrieval_mode": args.retrieval_mode,
                "top_k": args.top_k,
                "source_refs_count": len(context_refs),
                "hypothesis_written": True,
                "answer_strategy": synthesis.get("strategy", ""),
                "model_call_performed": bool(synthesis.get("model_call_performed")),
                "model_verdict": synthesis.get("model_verdict", ""),
                "model_evidence_count": synthesis.get("model_evidence_count", 0),
                "model_max_evidence_items": synthesis.get("model_max_evidence_items", 0),
                "model_local_postprocess_policy": synthesis.get("model_local_postprocess_policy", ""),
                "source_phrase_expander_applied": bool(synthesis.get("model_source_phrase_expander_applied")),
                "count_answer_completion_applied": bool(synthesis.get("model_count_answer_completion_applied")),
            }
            rows_for_stats.append(row)
            stats["ran"] += 1
        except Exception as exc:
            status = "failed"
            stats["failed"] += 1
            result = {"status": status, "question_id": case_id, "error": f"{type(exc).__name__}: {exc}"}
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
            {
                "contract": "model_heavy_qa_case_ledger.v2026.6.20",
                "run_id": run_slug,
                "case_id": case_id,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "cpu_seconds_delta": round(cpu_delta, 6),
                "rss_bytes_sample": int(after.get("rss_peak_bytes") or 0),
                "result": result,
            },
        )
        if status == "ok":
            mark_case_completed(checkpoint, case_id)
            save_checkpoint(checkpoint_path, checkpoint)
        if args.sleep_ms_between_cases > 0:
            time.sleep(args.sleep_ms_between_cases / 1000.0)

    metrics = _stats_from_rows(rows_for_stats, dataset=args.dataset, model_key=args.qa_model_key, cases=cases)
    summary = {
        "ok": stats["failed"] == 0,
        "contract": MODEL_HEAVY_QA_RUNNER_CONTRACT,
        "official_leaderboard_score": False,
        "dataset": args.dataset,
        "split": args.split if args.dataset == "longmemeval" else "locomo10",
        "data_path": str(path),
        "output_path": str(output_path),
        "checkpoint_path": str(checkpoint_path),
        "case_ledger_path": str(case_ledger_path),
        "retrieval_mode": args.retrieval_mode,
        "top_k": args.top_k,
        "answer_mode": args.answer_mode,
        "answer_model_name": args.answer_model_name,
        "answer_model_call_policy": args.answer_model_call_policy,
        "answer_model_max_evidence_items": args.answer_model_max_evidence_items,
        "answer_model_evidence_pack_mode": args.answer_model_evidence_pack_mode,
        "answer_model_local_postprocess_policy": args.answer_model_local_postprocess_policy,
        "case_stats": stats,
        "case_id_filter_count": len(case_id_filter),
        "case_id_filter_applied": bool(case_id_filter),
        "metrics": metrics,
        "notes": [
            "checkpointed_model_heavy_diagnostic",
            "not_official_leaderboard_score",
            "secret_values_not_serialized",
        ],
    }
    atomic_write_json(summary_path, summary)
    finish_run_ledger(ledger, status="ok" if summary["ok"] else "failed")
    atomic_write_json(run_ledger_path, ledger)
    if args.summary_json:
        print(json.dumps(_summary_json(summary), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
