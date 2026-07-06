#!/usr/bin/env python3
"""Run read-only work_preflight -> search/think dry-run probe."""

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

from work_preflight_search_think_probe import build_work_preflight_search_think_probe  # noqa: E402


def _print_text(payload: dict) -> None:
    receipt = payload.get("delivery_receipt_view", {}) if isinstance(payload.get("delivery_receipt_view"), dict) else {}
    dry_run = payload.get("search_think_dry_run", {}) if isinstance(payload.get("search_think_dry_run"), dict) else {}
    print("# Work Preflight Search/Think Probe")
    print()
    print(f"status: {'ok' if payload.get('ok') else 'attention'}")
    print(f"contract: {payload.get('contract', '')}")
    print(f"read only: {payload.get('read_only', True)}")
    print(f"model call: {payload.get('model_call_performed', False)}")
    gate = payload.get("controlled_think_execution", {}) if isinstance(payload.get("controlled_think_execution"), dict) else {}
    print(f"think execution allowed: {gate.get('allowed', False)}")
    print(f"platform write: {payload.get('platform_write_performed', False)}")
    print(f"evidence items: {payload.get('evidence_items_count', 0)}")
    print()
    print("## Receipt View")
    print(f"- status: {receipt.get('status', '')}")
    print(f"- headline: {receipt.get('headline_code', '')}")
    print(f"- unknown: {receipt.get('unknown_boundary', False)}")
    print(f"- raw expand: {(receipt.get('actions') or {}).get('expand_raw', {}).get('available', False)}")
    print()
    print("## Boundary")
    print(f"- search owner: {dry_run.get('search_owner', '')}")
    print(f"- think owner: {dry_run.get('think_owner', '')}")
    print("- note: source_refs are local entry evidence, not platform model delivery proof")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only work_preflight search/think dry-run probe.")
    parser.add_argument("--endpoint", default="", help="Local raw query endpoint. Defaults to 127.0.0.1:9851.")
    parser.add_argument("--query", default="", help="Work preflight query.")
    parser.add_argument("--timeout-seconds", type=float, default=None, help="Work preflight timeout.")
    parser.add_argument("--session-id", default="", help="Session anchor for work_preflight.")
    parser.add_argument("--canonical-window-id", default="", help="Window anchor for work_preflight.")
    parser.add_argument("--project-root", default="", help="Project root anchor for work_preflight.")
    parser.add_argument("--project-id", default="", help="Project id anchor for work_preflight.")
    parser.add_argument("--workstream-id", default="", help="Workstream anchor for work_preflight.")
    parser.add_argument("--task-id", default="", help="Task anchor for work_preflight.")
    parser.add_argument("--execute-think", action="store_true", help="Allow a controlled evidence-bound model think call when evidence exists.")
    parser.add_argument("--confirm-model-call", action="store_true", help="Required with --execute-think for real model calls.")
    parser.add_argument("--json", action="store_true", help="Print full JSON.")
    args = parser.parse_args()

    body = {}
    for key, value in {
        "endpoint": args.endpoint,
        "query": args.query,
        "session_id": args.session_id,
        "canonical_window_id": args.canonical_window_id,
        "project_root": args.project_root,
        "project_id": args.project_id,
        "workstream_id": args.workstream_id,
        "task_id": args.task_id,
    }.items():
        if value:
            body[key] = value
    if args.timeout_seconds is not None:
        body["timeout_seconds"] = args.timeout_seconds
    if args.execute_think:
        body["execute_think"] = True
    if args.confirm_model_call:
        body["confirm_model_call"] = True

    payload = build_work_preflight_search_think_probe(body)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
