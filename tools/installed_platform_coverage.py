#!/usr/bin/env python3
"""Build the read-only installed-platform coverage matrix."""

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

from installed_platform_coverage import build_installed_platform_coverage  # noqa: E402


def _load_json(path: str) -> dict:
    if not path:
        return {}
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return json.loads(text) if text.strip() else {}


def _load_json_list(paths: list[str]) -> list[dict]:
    items: list[dict] = []
    for path in paths:
        payload = _load_json(path)
        if isinstance(payload, dict):
            items.append(payload)
        elif isinstance(payload, list):
            items.extend(item for item in payload if isinstance(item, dict))
    return items


def _print_text(payload: dict) -> None:
    gate = payload.get("release_candidate_gate", {}) if isinstance(payload.get("release_candidate_gate"), dict) else {}
    print("# Installed Platform Coverage")
    print()
    print(f"contract: {payload.get('contract', '')}")
    print(f"read only: {payload.get('read_only', True)}")
    print(f"platform write: {payload.get('platform_write_performed', False)}")
    print(f"model call: {payload.get('model_call_performed', False)}")
    print(f"all required detected: {gate.get('all_required_targets_detected', False)}")
    if gate.get("required_detection_gaps"):
        print(f"required detection gaps: {', '.join(gate.get('required_detection_gaps', []))}")
    print()
    for row in payload.get("matrix", []):
        print(
            f"- {row.get('system')}: installed={row.get('installed_state')} "
            f"consumer={row.get('consumer_connection_state')} "
            f"delivery={row.get('delivery_proof_state')} "
            f"runtime={row.get('runtime_turn_loop_state')} "
            f"coverage={row.get('coverage_state')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build read-only installed-platform coverage matrix.")
    parser.add_argument("--input", default="", help="Optional combined JSON payload.")
    parser.add_argument("--autodiscovery", default="", help="Autodiscovery JSON payload.")
    parser.add_argument("--delivery-matrix", default="", help="Platform delivery matrix JSON payload.")
    parser.add_argument("--remote-probe", action="append", default=[], help="Remote probe JSON payload. Repeatable.")
    parser.add_argument("--runtime-status", default="", help="Runtime status JSON object by platform.")
    parser.add_argument("--required-targets", default="", help="Comma-separated required targets.")
    parser.add_argument("--no-generic", action="store_true", help="Skip generic autodiscovery when live-building.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    args = parser.parse_args()

    payload = _load_json(args.input)
    autodiscovery = _load_json(args.autodiscovery)
    delivery_matrix = _load_json(args.delivery_matrix)
    remote_probes = _load_json_list(args.remote_probe)
    runtime_status = _load_json(args.runtime_status)
    if payload:
        payload = dict(payload)
        if autodiscovery:
            payload["autodiscovery"] = autodiscovery
        if delivery_matrix:
            payload["delivery_matrix"] = delivery_matrix
        if remote_probes:
            payload["remote_probes"] = remote_probes
        if runtime_status:
            payload["runtime_status"] = runtime_status
    required_targets = [item.strip() for item in args.required_targets.split(",") if item.strip()] if args.required_targets else None
    matrix = build_installed_platform_coverage(
        payload,
        autodiscovery_payload=None if payload else autodiscovery or None,
        delivery_matrix_payload=None if payload else delivery_matrix or None,
        remote_probes=None if payload else remote_probes or None,
        runtime_status=None if payload else runtime_status or None,
        required_targets=required_targets,
        include_generic=not args.no_generic,
    )
    if args.json:
        print(json.dumps(matrix, ensure_ascii=False, indent=2))
    else:
        _print_text(matrix)
    return 0 if matrix.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
