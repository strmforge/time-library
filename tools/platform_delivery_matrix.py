#!/usr/bin/env python3
"""Render a compact findings-only platform delivery matrix."""

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

from platform_delivery_matrix import build_platform_delivery_matrix  # noqa: E402


def _load_payload(path: str) -> dict:
    if not path:
        return {}
    if path == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    return json.loads(text) if text.strip() else {}


def _print_text(payload: dict) -> None:
    print("# Platform Delivery Matrix")
    print()
    print(f"contract: {payload.get('contract', '')}")
    print(f"read only: {payload.get('read_only', True)}")
    print(f"model call: {payload.get('model_call_performed', False)}")
    print(f"platform write: {payload.get('platform_write_performed', False)}")
    gate = payload.get("platform_proof", {}).get("seven_of_seven_gate", {})
    if gate:
        print(f"7/7 proven: {gate.get('platform_delivery_7_of_7_proven', False)}")
        print(f"7/7 state: {gate.get('proof_state', '')}")
    print()
    for row in payload.get("matrix", []):
        print(
            f"- {row.get('platform')}: refs={row.get('source_refs_visible')} "
            f"raw={bool(row.get('raw_expand_path'))} "
            f"model={row.get('delivered_to_model')} user={row.get('delivered_to_user')} "
            f"level={row.get('risk_level')} next={row.get('recommended_next_contract')}"
        )
    if payload.get("next_actions"):
        print()
        print("## Next")
        for item in payload.get("next_actions", []):
            print(f"- {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build platform delivery liveness matrix from findings.")
    parser.add_argument("--input", default="", help="JSON payload path or '-' for stdin. Accepts audit/probe payload.")
    parser.add_argument("--platforms", default="", help="Comma-separated platforms when building a blank/static audit.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    args = parser.parse_args()

    payload = _load_payload(args.input)
    platforms = [item.strip() for item in args.platforms.split(",") if item.strip()] if args.platforms else None
    matrix = build_platform_delivery_matrix(payload, platforms=platforms)
    if args.json:
        print(json.dumps(matrix, ensure_ascii=False, indent=2))
    else:
        _print_text(matrix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
