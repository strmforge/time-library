#!/usr/bin/env python3
"""CLI for read-only benchmark miss reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_bootstrap import ensure_repo_import_paths  # noqa: E402

ROOT = ensure_repo_import_paths(__file__)

from eval_miss_report import build_eval_miss_report, render_eval_miss_report_markdown  # noqa: E402
from evidence_bound_model import default_model_config  # noqa: E402


def _parse_top_k(value: str) -> list[int]:
    return [int(part.strip()) for part in str(value or "").split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only miss report for a Memcore benchmark run.")
    parser.add_argument("--run-dir", default="", help="Existing eval run directory with summary.json and run-ledger.json.")
    parser.add_argument("--dataset", choices=("locomo", "longmemeval"), default="")
    parser.add_argument("--split", default="oracle")
    parser.add_argument("--data", default="")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--cache-root", default="")
    parser.add_argument("--max-conversations", type=int, default=None)
    parser.add_argument("--max-questions", type=int, default=None)
    parser.add_argument("--retrieval-mode", default="")
    parser.add_argument("--focus-top-k", type=int, default=3)
    parser.add_argument("--compare-top-k", default="3,5,10,20")
    parser.add_argument("--example-limit", type=int, default=8)
    parser.add_argument("--evidence-object-state", action="store_true", help="Add evidence object/state diagnostic rows.")
    parser.add_argument("--evidence-object-state-max-cases", type=int, default=20)
    parser.add_argument("--pack-gate-model-probe", action="store_true", help="Add small evidence-bound model probe rows for pack gate candidates.")
    parser.add_argument("--pack-gate-model-probe-max-cases", type=int, default=9)
    parser.add_argument("--pack-gate-model-calibration", action="store_true", help="Add model-calibrated confusion matrix for the pack gate.")
    parser.add_argument("--pack-gate-model-calibration-max-cases", type=int, default=18)
    parser.add_argument("--pack-gate-model-feature", action="store_true", help="Add diagnostic feature buckets for model-calibrated pack gate candidates.")
    parser.add_argument("--pack-gate-model-feature-max-cases", type=int, default=24)
    parser.add_argument("--pack-gate-runtime-candidate", action="store_true", help="Add dry-run runtime candidate decisions for pack expansion.")
    parser.add_argument("--pack-gate-runtime-candidate-max-cases", type=int, default=24)
    parser.add_argument("--execute-model", action="store_true", help="Actually call the configured evidence-bound model for diagnostics.")
    parser.add_argument("--model-provider", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key-env", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    model_config = None
    if args.evidence_object_state or args.pack_gate_model_probe or args.pack_gate_model_calibration or args.pack_gate_model_feature or args.pack_gate_runtime_candidate:
        model_config = default_model_config(
            provider=args.model_provider,
            model=args.model,
            base_url=args.base_url,
        )
        if args.api_key_env:
            model_config = {
                "provider": model_config.provider,
                "model": model_config.model,
                "base_url": model_config.base_url,
                "api_key_env": args.api_key_env,
                "timeout_seconds": model_config.timeout_seconds,
            }

    report = build_eval_miss_report(
        run_dir=args.run_dir or None,
        dataset=args.dataset,
        split=args.split,
        data_path=args.data or None,
        download=args.download,
        cache_root=args.cache_root or None,
        force_download=args.force_download,
        max_conversations=args.max_conversations,
        max_questions=args.max_questions,
        retrieval_mode=args.retrieval_mode,
        focus_top_k=args.focus_top_k,
        compare_top_k_values=_parse_top_k(args.compare_top_k),
        example_limit=args.example_limit,
        include_evidence_object_state=args.evidence_object_state,
        evidence_object_state_max_cases=args.evidence_object_state_max_cases,
        evidence_object_state_execute_model=args.execute_model,
        evidence_object_state_model_config=model_config,
        include_pack_gate_model_probe=args.pack_gate_model_probe,
        pack_gate_model_probe_max_cases=args.pack_gate_model_probe_max_cases,
        pack_gate_model_probe_execute_model=args.execute_model,
        pack_gate_model_probe_model_config=model_config,
        include_pack_gate_model_calibration=args.pack_gate_model_calibration,
        pack_gate_model_calibration_max_cases=args.pack_gate_model_calibration_max_cases,
        pack_gate_model_calibration_execute_model=args.execute_model,
        pack_gate_model_calibration_model_config=model_config,
        include_pack_gate_model_feature=args.pack_gate_model_feature,
        pack_gate_model_feature_max_cases=args.pack_gate_model_feature_max_cases,
        pack_gate_model_feature_execute_model=args.execute_model,
        pack_gate_model_feature_model_config=model_config,
        include_pack_gate_runtime_candidate=args.pack_gate_runtime_candidate,
        pack_gate_runtime_candidate_max_cases=args.pack_gate_runtime_candidate_max_cases,
        pack_gate_runtime_candidate_execute_model=args.execute_model,
        pack_gate_runtime_candidate_model_config=model_config,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) if args.json else render_eval_miss_report_markdown(report)
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
