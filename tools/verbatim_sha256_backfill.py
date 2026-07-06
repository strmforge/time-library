#!/usr/bin/env python3
"""Backfill missing verbatim_sha256 on evidence-bound candidate files.

The tool only writes when the stored verbatim excerpt is byte-equivalent to the
declared source slice. Mismatches stay untouched and visible in the report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

try:
    from src.distill_automation import _populate_candidate_verbatim_sha256  # noqa: WPS450
except Exception:  # pragma: no cover
    import sys

    sys.path.insert(0, str(ROOT))
    from src.distill_automation import _populate_candidate_verbatim_sha256  # noqa: WPS450


BACKFILL_CONTRACT = "time_library_verbatim_sha256_backfill.v1"


def _candidate_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for relative in (
        "output/zhiyi_preference_cards/candidates",
        "output/xingce_work_experience/candidates",
    ):
        directory = root / relative
        if directory.exists():
            paths.extend(sorted(directory.glob("*.json")))
    return paths


def _candidate_label(candidate: dict[str, Any], path: Path) -> str:
    return str(
        candidate.get("library_id")
        or candidate.get("exp_id")
        or candidate.get("candidate_id")
        or path.stem
    )


def backfill(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).expanduser()
    scanned = 0
    backfilled = 0
    already_present = 0
    skipped: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    for path in _candidate_paths(root_path):
        scanned += 1
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            skipped.append({"path": str(path), "reason": f"json_unreadable:{type(exc).__name__}"})
            continue
        if not isinstance(candidate, dict):
            skipped.append({"path": str(path), "reason": "candidate_not_object"})
            continue
        label = _candidate_label(candidate, path)
        if str(candidate.get("verbatim_sha256") or "").strip():
            already_present += 1
            continue
        if not str(candidate.get("verbatim_excerpt") or ""):
            skipped.append({"path": str(path), "candidate": label, "reason": "verbatim_missing"})
            continue
        before = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
        sha = _populate_candidate_verbatim_sha256(candidate)
        if not sha:
            skipped.append({"path": str(path), "candidate": label, "reason": "source_slice_mismatch_or_unavailable"})
            continue
        after = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
        if after != before:
            path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            backfilled += 1
            updated.append({"path": str(path), "candidate": label, "verbatim_sha256": sha})
        else:
            already_present += 1
    return {
        "ok": True,
        "contract": BACKFILL_CONTRACT,
        "root": str(root_path),
        "scanned": scanned,
        "backfilled": backfilled,
        "already_present": already_present,
        "skipped_count": len(skipped),
        "updated": updated,
        "skipped": skipped,
        "write_performed": bool(backfilled),
        "raw_write_performed": False,
        "memory_write_performed": bool(backfilled),
        "platform_write_performed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    print(json.dumps(backfill(args.root), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
