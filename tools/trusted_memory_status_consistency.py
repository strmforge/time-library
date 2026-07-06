#!/usr/bin/env python3
"""Check Trusted Memory status page and scoped casefile consistency."""

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

from src.trusted_memory_status_consistency import check_trusted_memory_status_consistency  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Trusted Memory status/casefile consistency.")
    parser.add_argument("--repo-root", default=str(ROOT), help="repository root to inspect")
    parser.add_argument(
        "--casefile",
        default="docs/fixtures/trusted-memory-user-work-cases.example.json",
        help="scoped user/work casefile path, relative to repo root unless absolute",
    )
    parser.add_argument(
        "--status-page",
        default="docs/wiki/Trusted-Memory-And-Delivery-Status.md",
        help="Trusted Memory status page, relative to repo root unless absolute",
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()

    report = check_trusted_memory_status_consistency(
        repo_root=args.repo_root,
        casefile=args.casefile,
        status_page=args.status_page,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report.get("ok") else "ATTENTION"
        print("# Trusted Memory Status Consistency")
        print()
        print(f"- Contract: `{report.get('contract')}`")
        print(f"- Status: `{status}`")
        print(f"- Case count: `{report.get('case_count', 0)}`")
        print(f"- Scope count: `{report.get('scope_count', 0)}`")
        print(f"- Record kinds: `{', '.join(report.get('record_kinds') or [])}`")
        for error in report.get("errors") or []:
            print(f"- Error: `{error}`")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
