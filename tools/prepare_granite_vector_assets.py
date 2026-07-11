#!/usr/bin/env python3
"""Download, verify, and build the install-relative Granite vector assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.granite_vector_assets import prepare_granite_assets  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    args = parser.parse_args()
    result = prepare_granite_assets(args.runtime_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
