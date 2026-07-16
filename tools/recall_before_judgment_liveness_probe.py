#!/usr/bin/env python3
"""Run the read-only recall-before-judgment liveness probe."""

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

from recall_before_judgment_liveness import build_recall_before_judgment_liveness  # noqa: E402


def _print_text(payload: dict) -> None:
    print("# Recall Before Judgment Liveness")
    print()
    print(f"status: {payload.get('status', '')}")
    print(f"contract: {payload.get('contract', '')}")
    print(f"read only: {payload.get('read_only', True)}")
    print(f"model call: {payload.get('model_call_performed', False)}")
    print(f"platform write: {payload.get('platform_write_performed', False)}")
    print(f"source refs: {payload.get('source_refs_count', 0)}")
    print(f"raw items: {payload.get('raw_items_count', 0)}")
    print(f"matched required terms: {', '.join(payload.get('matched_required_terms', []))}")
    missing = payload.get("missing_required_terms", [])
    if missing:
        print(f"missing required terms: {', '.join(missing)}")
    print(f"next action: {payload.get('next_action', '')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only recall-before-judgment liveness probe.")
    parser.add_argument("--endpoint", default="", help="Local raw query endpoint. Defaults to the local front-door discovery file.")
    parser.add_argument("--query", default="", help="Work preflight query.")
    parser.add_argument("--consumer", default="", help="Consumer identity for work_preflight. Defaults to codex.")
    parser.add_argument("--timeout-seconds", type=float, default=None, help="Work preflight timeout.")
    parser.add_argument("--session-id", default="", help="Session anchor for work_preflight.")
    parser.add_argument("--canonical-window-id", default="", help="Window anchor for work_preflight.")
    parser.add_argument("--project-root", default="", help="Project root anchor for work_preflight.")
    parser.add_argument("--project-id", default="", help="Project id anchor for work_preflight.")
    parser.add_argument("--workstream-id", default="", help="Workstream anchor for work_preflight.")
    parser.add_argument("--task-id", default="", help="Task anchor for work_preflight.")
    parser.add_argument("--required-term", action="append", default=[], help="Authority term that must surface. Repeatable.")
    parser.add_argument("--deep-work-preflight", action="store_true", help="Opt into slower full work_preflight recall.")
    parser.add_argument("--json", action="store_true", help="Print full JSON.")
    args = parser.parse_args()

    body = {}
    for key, value in {
        "endpoint": args.endpoint,
        "query": args.query,
        "consumer": args.consumer,
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
    if args.required_term:
        body["required_terms"] = args.required_term
    if args.deep_work_preflight:
        body["deep_work_preflight"] = True

    payload = build_recall_before_judgment_liveness(body)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
