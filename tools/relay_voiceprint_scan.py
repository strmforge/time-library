#!/usr/bin/env python3
"""Scan existing candidate cards for user-relayed agent voiceprint risk."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.relay_voiceprint import append_annotation, apply_annotation, annotation_path
from src.zhixing_library import library_id_for


SCAN_CONTRACT = "time_library_relay_voiceprint_scan.v1"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _candidate_paths(root: Path) -> list[Path]:
    dirs = [
        root / "output" / "zhiyi_preference_cards" / "candidates",
        root / "output" / "xingce_work_experience" / "candidates",
        root / "output" / "toolbook_platform_facts" / "candidates",
    ]
    paths: list[Path] = []
    for directory in dirs:
        if directory.is_dir():
            paths.extend(sorted(directory.glob("*.json")))
    return sorted(paths)


def _normalize_for_library_id(candidate: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(candidate)
    if normalized.get("candidate_type") == "zhiyi_preference_card":
        normalized.setdefault("_type", "zhiyi_preference_card")
        normalized.setdefault("type", "preference_memory")
        normalized.setdefault("exp_id", normalized.get("candidate_id") or normalized.get("exp_id") or "")
    return normalized


def scan(root: str | Path, *, write: bool = False) -> dict[str, Any]:
    root_path = Path(root).expanduser()
    scanned = 0
    user_source = 0
    relayed = 0
    watch = 0
    direct_user = 0
    non_user = 0
    written = 0
    samples: list[dict[str, Any]] = []
    relayed_items: list[dict[str, Any]] = []
    watch_items: list[dict[str, Any]] = []

    for path in _candidate_paths(root_path):
        candidate = _read_json(path)
        if not candidate:
            continue
        scanned += 1
        candidate = _normalize_for_library_id(candidate)
        annotated = apply_annotation(candidate)
        annotation = annotated.get("relay_voiceprint") if isinstance(annotated.get("relay_voiceprint"), dict) else {}
        attribution = str(annotated.get("evidence_attribution") or annotation.get("evidence_attribution") or "")
        library_id = library_id_for(annotated)
        item = {
            "path": str(path),
            "candidate_id": annotated.get("candidate_id") or annotated.get("exp_id") or "",
            "library_id": library_id,
            "title": annotated.get("title") or "",
            "evidence_attribution": attribution,
            "risk_level": annotation.get("risk_level", ""),
            "reasons": annotation.get("reasons", []),
            "score": annotation.get("score", 0),
            "source_author": annotation.get("source_author", ""),
            "verbatim_excerpt": str(annotated.get("verbatim_excerpt") or "")[:360],
        }
        if annotation.get("source_author") == "user":
            user_source += 1
        if attribution == "user_relayed":
            relayed += 1
            relayed_items.append(item)
        elif attribution == "direct_user":
            direct_user += 1
        else:
            non_user += 1
        if annotation.get("risk_level") == "watch":
            watch += 1
            watch_items.append(item)
        if len(samples) < 12 and (attribution == "user_relayed" or annotation.get("risk_level") == "watch"):
            samples.append(item)
        if write:
            append_annotation(root_path, annotated, candidate_path=str(path), library_id=library_id)
            written += 1

    return {
        "ok": True,
        "contract": SCAN_CONTRACT,
        "root": str(root_path),
        "write": bool(write),
        "write_performed": bool(write),
        "raw_write_performed": False,
        "candidate_delete_performed": False,
        "candidate_status_changed": False,
        "annotation_ledger": str(annotation_path(root_path)),
        "scanned_candidate_count": scanned,
        "user_source_candidate_count": user_source,
        "user_relayed_count": relayed,
        "watch_count": watch,
        "direct_user_count": direct_user,
        "non_user_source_count": non_user,
        "written_annotation_count": written,
        "samples": samples,
        "user_relayed_items": relayed_items,
        "watch_items": watch_items,
        "nonclaims": [
            "heuristic_labels_only_not_owner_adjudication",
            "does_not_delete_or_supersede_cards",
            "does_not_change_raw_or_candidate_status",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan candidate cards for user-relayed voiceprint risk")
    parser.add_argument("--root", default=os.environ.get("MEMCORE_ROOT", "."))
    parser.add_argument("--write", action="store_true", help="Append annotations to output/relay_voiceprint/annotations.jsonl")
    args = parser.parse_args(argv)
    print(json.dumps(scan(args.root, write=args.write), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
