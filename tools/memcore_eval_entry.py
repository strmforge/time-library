#!/usr/bin/env python3
"""Route memory evaluation work through safe profiles."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_bootstrap import ensure_repo_import_paths  # noqa: E402

ROOT = ensure_repo_import_paths(__file__)

from eval_entrypoints import execute_eval_entrypoint  # noqa: E402


def _bool_arg(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _detect_watcher_active() -> bool | None:
    try:
        proc = subprocess.run(
            ["pgrep", "-af", "memcore-cloud.*--watch"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    if proc.returncode == 0:
        return bool(proc.stdout.strip())
    if proc.returncode == 1:
        return False
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Memcore evaluation through daily/regression/offline profiles.")
    sub = parser.add_subparsers(dest="profile", required=True)
    for name in ("daily", "regression", "offline"):
        item = sub.add_parser(name)
        item.add_argument("--host-label", default="")
        item.add_argument("--dataset", default="")
        item.add_argument("--split", default="")
        item.add_argument("--sample-count", type=int, default=None)
        item.add_argument("--max-questions", type=int, default=None)
        item.add_argument("--top-k", type=int, default=None)
        item.add_argument("--retrieval-mode", default="")
        item.add_argument("--benchmark-suite", choices=["none", "free"], default="none")
        item.add_argument("--judge", action="store_true")
        item.add_argument("--override", action="store_true")
        item.add_argument("--watcher-active", choices=["true", "false", "unknown"], default="unknown")
        item.add_argument("--checkpoint", default="")
        item.add_argument("--case-ledger", default="")
        item.add_argument("--run-ledger", default="")
        item.add_argument("--case-list", default="")
        item.add_argument("--locomo-data", default="")
        item.add_argument("--longmemeval-data", default="")
        item.add_argument("--download", action="store_true")
        item.add_argument("--force-download", action="store_true")
        item.add_argument("--cache-root", default="")
        item.add_argument("--max-conversations", type=int, default=None)
        item.add_argument("--no-resume", action="store_true")
        item.add_argument("--force", action="store_true")
        item.add_argument("--sleep-ms-between-cases", type=int, default=0)
        item.add_argument("--max-runtime-minutes", type=float, default=0)
        item.add_argument("--json", action="store_true")
        item.add_argument("--summary-json", action="store_true")
    return parser


def _print_text(payload: dict) -> None:
    plan = payload.get("plan", {})
    ledger = payload.get("ledger", {})
    print("# Memcore Evaluation Entry")
    print()
    print(f"- ok: {str(bool(payload.get('ok'))).lower()}")
    print(f"- profile: {plan.get('profile', '')}")
    print(f"- host: {plan.get('host_label', '')}")
    print(f"- blocked: {str(bool(plan.get('blocked'))).lower()}")
    if plan.get("blocked_reasons"):
        print(f"- blocked reasons: {', '.join(plan.get('blocked_reasons', []))}")
    print(f"- run id: {ledger.get('run_id', '')}")
    print(f"- status: {ledger.get('status', '')}")
    print(f"- elapsed ms: {ledger.get('elapsed_ms', 0)}")
    print(f"- rss peak bytes: {ledger.get('rss_peak_bytes', 0)}")
    if payload.get("case_stats"):
        stats = payload["case_stats"]
        print(f"- cases: ran={stats.get('ran', 0)} skipped={stats.get('skipped', 0)} failed={stats.get('failed', 0)}")
    if payload.get("benchmark_result"):
        result = payload["benchmark_result"]
        print(f"- benchmark: {result.get('mode', '')}")
        for item in result.get("results", []):
            print(
                "- {dataset}: cases={cases} exact={exact:.4f} bundled={bundled:.4f} anchor={anchor:.4f}".format(
                    dataset=item.get("dataset", ""),
                    cases=item.get("case_count", 0),
                    exact=float(item.get("exact_source_recall") or 0),
                    bundled=float(item.get("bundled_source_recall") or 0),
                    anchor=float(item.get("gold_anchor_recall") or 0),
                )
            )


def _summary(payload: dict) -> dict:
    plan = payload.get("plan", {})
    ledger = payload.get("ledger", {})
    return {
        "ok": payload.get("ok", False),
        "profile": plan.get("profile", ""),
        "host_label": plan.get("host_label", ""),
        "blocked": plan.get("blocked", False),
        "blocked_reasons": plan.get("blocked_reasons", []),
        "run_id": ledger.get("run_id", ""),
        "status": ledger.get("status", ""),
        "block_reason": ledger.get("block_reason", ""),
        "failure_reason": ledger.get("failure_reason", ""),
        "watcher_active_at_start": ledger.get("watcher_active_at_start"),
        "watcher_active_source": ledger.get("watcher_active_source", ""),
        "elapsed_ms": ledger.get("elapsed_ms", 0),
        "rss_peak_bytes": ledger.get("rss_peak_bytes", 0),
        "case_stats": payload.get("case_stats", {}),
        "benchmark_result": payload.get("benchmark_result", {}),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.watcher_active == "unknown":
        watcher_active = _detect_watcher_active()
        watcher_active_source = "auto_pgrep" if watcher_active is not None else "auto_pgrep_unknown"
    else:
        watcher_active = _bool_arg(args.watcher_active)
        watcher_active_source = "cli_explicit"
    payload = execute_eval_entrypoint(
        profile=args.profile,
        host_label=args.host_label,
        dataset=args.dataset,
        split=args.split,
        sample_count=args.sample_count,
        max_questions=args.max_questions,
        top_k=args.top_k,
        retrieval_mode=args.retrieval_mode,
        benchmark_suite=args.benchmark_suite,
        judge_requested=args.judge,
        override=args.override,
        watcher_active=watcher_active,
        watcher_active_source=watcher_active_source,
        checkpoint_path=args.checkpoint or None,
        case_ledger_path=args.case_ledger or None,
        run_ledger_path=args.run_ledger or None,
        case_list_path=args.case_list or None,
        locomo_data_path=args.locomo_data or None,
        longmemeval_data_path=args.longmemeval_data or None,
        download=args.download,
        force_download=args.force_download,
        cache_root=args.cache_root or None,
        max_conversations=args.max_conversations,
        resume=not args.no_resume,
        force=args.force,
        sleep_ms_between_cases=args.sleep_ms_between_cases,
        max_runtime_minutes=args.max_runtime_minutes,
        repo_root=ROOT,
    )
    if args.summary_json:
        print(json.dumps(_summary(payload), ensure_ascii=False, indent=2, sort_keys=True))
    elif args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
