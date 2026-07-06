#!/usr/bin/env python3
"""Build the P3 SQLite FTS5 recall index from the current zhiyi memories."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.fts5_recall_index import build_index, default_index_path  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build P3 FTS5 recall index.")
    parser.add_argument("--index-path", default="", help="Output sqlite index path.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()

    import src.p3_recall as p3_recall  # noqa: WPS433

    memcore_root = os.environ.get("MEMCORE_ROOT") or os.environ.get("MEMCORE_INSTALL_ROOT") or str(ROOT)
    index_path = args.index_path or os.environ.get("MEMCORE_FTS5_RECALL_INDEX_PATH") or default_index_path(memcore_root)
    memories = p3_recall.get_memories()
    report = build_index(memories, index_path=index_path)
    report["memory_count"] = len(memories)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"ok={report.get('ok')} index_path={report.get('index_path')} doc_count={report.get('doc_count')} error={report.get('error')}")
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
