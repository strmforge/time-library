#!/usr/bin/env python3
"""Materialize canonical dialogue sidecars and emit block3 migration receipts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from src.canonical_dialogue_runtime import build_canonical_dialogue_migration_report
except ImportError:  # pragma: no cover
    from canonical_dialogue_runtime import build_canonical_dialogue_migration_report  # type: ignore


def _write_receipt(root: Path, payload: dict, receipt_dir: str = "") -> Path:
    directory = Path(receipt_dir).expanduser() if receipt_dir else root / "output" / "canonical_dialogue_migration" / "receipts"
    directory.mkdir(parents=True, exist_ok=True)
    stem = Path(str(payload.get("raw_path") or "session")).stem or "session"
    session_id = str(payload.get("session_id") or payload.get("canonical_window_id") or "session").replace("/", "-")
    filename = f"canonical-dialogue-migration-{stem}-{session_id}.json"
    path = directory / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize canonical dialogue and emit a migration report.")
    parser.add_argument("raw_path")
    parser.add_argument("--source-system", required=True)
    parser.add_argument("--session-id", default="")
    parser.add_argument("--canonical-window-id", default="")
    parser.add_argument("--native-artifact-format", default="")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--raw-order", type=int, default=1)
    parser.add_argument("--receipt-dir", default="")
    args = parser.parse_args()

    report = build_canonical_dialogue_migration_report(
        args.raw_path,
        source_system=args.source_system,
        session_id=args.session_id,
        canonical_window_id=args.canonical_window_id,
        native_artifact_format=args.native_artifact_format,
        reset=bool(args.reset),
        raw_order=int(args.raw_order or 1),
    )
    receipt = _write_receipt(Path.cwd(), report, receipt_dir=args.receipt_dir)
    report["receipt_path"] = str(receipt)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
