#!/usr/bin/env python3
"""Inspect the local Time Library distillation transparency ledger."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.distill_transparency import default_ledger_path, get_entry, ledger_status, read_entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "list", "show"), nargs="?", default="list")
    parser.add_argument("call_id", nargs="?")
    parser.add_argument(
        "--root",
        default=(
            os.environ.get("MEMCORE_ROOT")
            or os.environ.get("MEMCORE_INSTALL_ROOT")
            or str(ROOT)
        ),
    )
    parser.add_argument("--ledger", default="")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    ledger = Path(args.ledger).expanduser() if args.ledger else default_ledger_path(args.root or None)

    if args.command == "status":
        print(json.dumps(ledger_status(ledger), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "show":
        item = get_entry(args.call_id or "", ledger)
        if item is None:
            print(json.dumps({"ok": False, "error": "transparency_entry_not_found"}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    items = [
        {key: value for key, value in item.items() if key != "payload_text"}
        for item in read_entries(ledger, limit=max(1, min(int(args.limit or 20), 200)))
    ]
    print(json.dumps({"ok": True, "ledger_path": str(ledger), "items": items}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
