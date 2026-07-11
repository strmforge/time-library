#!/usr/bin/env python3
"""One-click Memcore record doctor.

This is the public, read-only "are my records guarded?" check. It does not
trigger backfill, index writes, memory writes, model calls, or platform config
writes.
"""

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
from record_chain_doctor import build_record_doctor, render_doctor_markdown  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the read-only Time Library record doctor.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--mode", choices=("fast", "full"), default="fast")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a short Markdown report.")
    parser.add_argument("--private-paths", action="store_true", help="Include private absolute paths in source payloads.")
    args = parser.parse_args()

    payload = build_record_doctor(
        limit=args.limit,
        scan_mode=args.mode,
        public=not args.private_paths,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_doctor_markdown(payload), end="")
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
