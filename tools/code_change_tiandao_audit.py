#!/usr/bin/env python3
"""Report repository code changes as a read-only Tiandao source inlet."""

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

from src.code_change_tiandao_source import (  # noqa: E402
    build_code_change_tiandao_source_report,
    render_code_change_tiandao_source_markdown,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit code changes as Tiandao source refs.")
    parser.add_argument("--repo-root", default=str(ROOT), help="repository root to inspect")
    parser.add_argument("--max-refs", type=int, default=200, help="maximum changed-file refs to include; use 0 for all refs")
    parser.add_argument("--require-complete", action="store_true", help="fail if changed-file source refs are truncated")
    parser.add_argument(
        "--verification-output",
        action="append",
        default=[],
        help="path to a saved test or verification output artifact to include as a read-only source ref",
    )
    parser.add_argument(
        "--verification-command",
        action="append",
        default=[],
        help="reproduction command for the matching verification output artifact",
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()

    report = build_code_change_tiandao_source_report(
        repo_root=args.repo_root,
        max_refs=args.max_refs,
        require_complete=args.require_complete,
        verification_outputs=args.verification_output,
        verification_commands=args.verification_command,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_code_change_tiandao_source_markdown(report), end="")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
