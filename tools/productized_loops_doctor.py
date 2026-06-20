#!/usr/bin/env python3
"""Run the five productized Memcore proof loops in one read-only command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_bootstrap import ensure_repo_import_paths, memcore_root  # noqa: E402

ROOT = ensure_repo_import_paths(__file__)

from productized_loops import build_productized_loops_doctor  # noqa: E402


def _print_text(payload: dict) -> None:
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    print("# Memcore Productized Loops Doctor")
    print()
    print(f"status: {'ok' if payload.get('ok') else 'attention'}")
    print(f"contract: {payload.get('contract', '')}")
    print(f"classification: {payload.get('classification', '')}")
    print()
    print("## Summary")
    print(f"- connect doctor plans: {summary.get('connect_doctor_plans', 0)}")
    print(f"- preflight classification: {summary.get('preflight_classification', '')}")
    print(f"- benchmark best mode: {summary.get('benchmark_best_mode', '')}")
    print(f"- benchmark Xingce signal: {summary.get('benchmark_xingce_signal_detected', False)}")
    print(f"- borrowing demo receipts: {summary.get('borrowing_demo_receipts', 0)}")
    print(f"- experience candidates: {summary.get('experience_candidate_count', 0)}")
    print(f"- apply package status: {summary.get('experience_apply_package_status', '')}")
    print(f"- Hermes skill/experience candidates: {summary.get('hermes_upgrade_candidate_count', 0)}")
    print()
    print("## Loops")
    statuses = payload.get("loop_statuses", {}) if isinstance(payload.get("loop_statuses"), dict) else {}
    for name in payload.get("loop_ids", []):
        status = statuses.get(name, {}) if isinstance(statuses.get(name), dict) else {}
        print(f"- {name}: ok={status.get('ok')} read_only={status.get('read_only')} write={status.get('write_performed')} contract={status.get('contract', '')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the read-only productized loops doctor.")
    parser.add_argument("--query", default="", help="Work query to feed into the visible preflight demo.")
    parser.add_argument("--memcore-root", default="", help="Runtime Memcore root. Defaults to MEMCORE_ROOT or repo root.")
    parser.add_argument("--home", default="", help="Home directory to scan for local agent configs.")
    parser.add_argument("--include-generic", action="store_true", help="Include generic local AI surface discovery.")
    parser.add_argument("--skip-platform-scan", action="store_true", help="Skip local platform scanning for deterministic tests.")
    parser.add_argument("--json", action="store_true", help="Print full JSON instead of a compact text report.")
    args = parser.parse_args()

    body = {
        "query": args.query,
        "include_generic": args.include_generic,
        "skip_platform_scan": args.skip_platform_scan,
    }
    payload = build_productized_loops_doctor(
        body,
        memcore_root=args.memcore_root or memcore_root(__file__),
        home=args.home or None,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
