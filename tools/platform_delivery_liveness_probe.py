#!/usr/bin/env python3
"""Run the read-only Phase 0 platform delivery liveness probe."""

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

from platform_delivery_probe import build_platform_delivery_liveness_probe  # noqa: E402


def _print_text(payload: dict) -> None:
    audit = payload.get("platform_delivery_liveness", {}) if isinstance(payload.get("platform_delivery_liveness"), dict) else {}
    work_probe = payload.get("work_preflight_probe", {}) if isinstance(payload.get("work_preflight_probe"), dict) else {}
    response = work_probe.get("response", {}) if isinstance(work_probe.get("response"), dict) else {}
    print("# Platform Delivery Liveness Probe")
    print()
    print(f"status: {'ok' if payload.get('ok') else 'attention'}")
    print(f"contract: {payload.get('contract', '')}")
    print(f"phase: {payload.get('phase', '')}")
    print(f"read only: {payload.get('read_only', True)}")
    print(f"model call: {payload.get('model_call_performed', False)}")
    print(f"platform write: {payload.get('platform_write_performed', False)}")
    print()
    print("## Work Preflight")
    print(f"- performed: {payload.get('work_preflight_probe_performed', False)}")
    print(f"- ok: {work_probe.get('ok', False)}")
    print(f"- source refs: {response.get('source_refs_count', 0)}")
    print(f"- raw items: {response.get('raw_items_count', 0)}")
    print(f"- note: local work_preflight is not platform model delivery proof")
    print()
    print("## Platforms")
    for item in audit.get("platforms", []):
        print(
            f"- {item.get('platform')}: passive={item.get('passive_state')} "
            f"model={item.get('delivered_to_model')} user={item.get('delivered_to_user')} "
            f"source_refs={item.get('source_refs_visible')} risk={','.join(item.get('risk', []))}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only platform delivery liveness probe.")
    parser.add_argument("--endpoint", default="", help="Local raw query endpoint. Defaults to 127.0.0.1:9851.")
    parser.add_argument("--query", default="", help="Work preflight query.")
    parser.add_argument("--timeout-seconds", type=float, default=None, help="Work preflight timeout.")
    parser.add_argument("--platforms", default="", help="Comma-separated platform list.")
    parser.add_argument("--include-generic", action="store_true", help="Include generic platform discovery.")
    parser.add_argument("--no-work-preflight", action="store_true", help="Skip local work_preflight probe.")
    parser.add_argument("--session-id", default="", help="Session anchor for work_preflight.")
    parser.add_argument("--canonical-window-id", default="", help="Window anchor for work_preflight.")
    parser.add_argument("--project-root", default="", help="Project root anchor for work_preflight.")
    parser.add_argument("--project-id", default="", help="Project id anchor for work_preflight.")
    parser.add_argument("--workstream-id", default="", help="Workstream anchor for work_preflight.")
    parser.add_argument("--task-id", default="", help="Task anchor for work_preflight.")
    parser.add_argument("--json", action="store_true", help="Print full JSON.")
    args = parser.parse_args()

    body = {
        "include_generic": args.include_generic,
        "run_work_preflight": not args.no_work_preflight,
    }
    for key, value in {
        "endpoint": args.endpoint,
        "query": args.query,
        "platforms": args.platforms,
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

    payload = build_platform_delivery_liveness_probe(body)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
