#!/usr/bin/env python3
"""CLI for comparing baseline and fast evidence-bound model matrix runs."""

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

from model_matrix_compare import (  # noqa: E402
    compare_model_matrix_summaries,
    render_model_matrix_compare_markdown,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a baseline model matrix run with a fast-mode run.")
    parser.add_argument("baseline_summary")
    parser.add_argument("fast_summary")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--example-limit", type=int, default=8)
    args = parser.parse_args(argv)

    report = compare_model_matrix_summaries(
        args.baseline_summary,
        args.fast_summary,
        example_limit=args.example_limit,
    )
    text = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if args.json
        else render_model_matrix_compare_markdown(report)
    )
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
