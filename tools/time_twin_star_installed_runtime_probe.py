#!/usr/bin/env python3
"""Read-only probe for the installed Time Twin Star p6 console route."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.runtime_bootstrap import ensure_repo_import_paths  # noqa: E402

ROOT = ensure_repo_import_paths(__file__)

from tiandao import (  # noqa: E402
    TIME_TWIN_STAR_DEFAULT_CONSOLE_URL,
    probe_time_twin_star_installed_runtime,
)


def _print_text(payload: dict) -> None:
    health = payload.get("health_check", {}) if isinstance(payload.get("health_check"), dict) else {}
    endpoint = payload.get("endpoint_check", {}) if isinstance(payload.get("endpoint_check"), dict) else {}
    print("# Time Twin Star Installed Runtime Probe")
    print()
    print(f"- contract: `{payload.get('contract', '')}`")
    print(f"- installed runtime: `{payload.get('installed_runtime_status', '')}`")
    print(f"- platform delivery: `{payload.get('platform_delivery_status', '')}`")
    print(f"- agent turn loop: `{payload.get('agent_turn_loop_status', '')}`")
    print(f"- console: `{payload.get('console_url', '')}`")
    print(f"- health: `{health.get('status_code', 0)}` ok=`{health.get('ok', False)}`")
    print(f"- endpoint: `{endpoint.get('status_code', 0)}` ok=`{endpoint.get('ok', False)}`")
    print()
    print("Non-claims:")
    for item in payload.get("non_claims", []):
        print(f"- `{item}`")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe installed p6 console for Time Twin Star route.")
    parser.add_argument("--console-url", default=TIME_TWIN_STAR_DEFAULT_CONSOLE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=3.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = probe_time_twin_star_installed_runtime(
        console_url=args.console_url,
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
