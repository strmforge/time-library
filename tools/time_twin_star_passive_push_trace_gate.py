#!/usr/bin/env python3
"""Read-only gate for OpenClaw passive auto-injection smoke traces."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.runtime_bootstrap import ensure_repo_import_paths  # noqa: E402

ROOT = ensure_repo_import_paths(__file__)

from tiandao import (  # noqa: E402
    time_twin_star_passive_push_trace_gate_definition,
    time_twin_star_passive_push_trace_gate_from_observation,
)


def _load_trace(path: str | None) -> dict[str, Any]:
    if not path or path == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return {}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise SystemExit("trace JSON must be an object")
    return payload


def _print_text(payload: dict[str, Any]) -> None:
    print("# Time Twin Star Passive Push Trace Gate")
    print()
    print(f"- contract: `{payload.get('contract', '')}`")
    print(f"- gate status: `{payload.get('gate_status', '')}`")
    print(f"- behavior status: `{payload.get('push_behavior_status', '')}`")
    print(f"- sufficient: `{payload.get('trace_sufficient_for_passive_push_proven', False)}`")
    print(f"- coverage delta: `{payload.get('push_coverage_delta', '')}`")
    print()
    print("Missing observations:")
    for item in payload.get("missing_observations", []):
        print(f"- `{item}`")
    print()
    print("Forbidden substitutes present:")
    for item in payload.get("forbidden_substitutes_present", []):
        print(f"- `{item}`")


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify an OpenClaw passive auto-injection smoke trace.")
    parser.add_argument("--trace-json", help="path to a trace JSON file; use '-' for stdin")
    parser.add_argument("--definition", action="store_true", help="print the gate definition instead of classifying")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()

    if args.definition:
        payload = time_twin_star_passive_push_trace_gate_definition()
    else:
        payload = time_twin_star_passive_push_trace_gate_from_observation(_load_trace(args.trace_json))

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
