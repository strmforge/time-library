#!/usr/bin/env python3
"""Run the no-key Memcore Cloud benchmark suite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from runtime_bootstrap import ensure_repo_import_paths  # noqa: E402

ROOT = ensure_repo_import_paths(__file__)

from free_memory_benchmark import (  # noqa: E402
    DEFAULT_FREE_RETRIEVAL_MODE,
    DEFAULT_FREE_TOP_K,
    compact_suite_summary,
    render_free_benchmark_markdown,
    run_free_memory_benchmark_suite,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run LoCoMo and LongMemEval retrieval diagnostics without an API key."
    )
    parser.add_argument("--locomo-data", default="", help="Path to locomo10.json. Defaults to the cache or --download.")
    parser.add_argument("--longmemeval-data", default="", help="Path to longmemeval_oracle.json. Defaults to the cache or --download.")
    parser.add_argument("--download", action="store_true", help="Download public benchmark data to the local cache if needed.")
    parser.add_argument("--force-download", action="store_true", help="Refresh cached public benchmark data.")
    parser.add_argument("--cache-root", default="", help="Benchmark cache root.")
    parser.add_argument("--retrieval-mode", default=DEFAULT_FREE_RETRIEVAL_MODE)
    parser.add_argument("--top-k", type=int, default=DEFAULT_FREE_TOP_K)
    parser.add_argument("--max-conversations", type=int, default=None)
    parser.add_argument("--max-questions", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="Print full JSON.")
    parser.add_argument("--summary-json", action="store_true", help="Print compact JSON.")
    args = parser.parse_args(argv)

    payload = run_free_memory_benchmark_suite(
        locomo_data_path=args.locomo_data or None,
        longmemeval_data_path=args.longmemeval_data or None,
        download=args.download,
        force_download=args.force_download,
        cache_root=args.cache_root or None,
        retrieval_mode=args.retrieval_mode,
        top_k=args.top_k,
        max_conversations=args.max_conversations,
        max_questions=args.max_questions,
    )
    if args.summary_json:
        print(json.dumps(compact_suite_summary(payload), ensure_ascii=False, indent=2, sort_keys=True))
    elif args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_free_benchmark_markdown(payload), end="")
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
