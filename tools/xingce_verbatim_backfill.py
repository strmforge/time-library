#!/usr/bin/env python3
"""Backfill Xingce candidates so verbatim fields are true source byte slices.

This tool is append-only: it writes superseding candidate/action files and a
supersede action for the original candidate. It never edits the original
candidate JSON.

The corrected candidate intentionally preserves the old public library_id. The
candidate artifact id changes, but the borrowing handle remains stable so
existing catalog references open the corrected source-byte card instead of a
404 or the stale projection.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from src.zhixing_library import library_id_for
except Exception:  # pragma: no cover
    from zhixing_library import library_id_for


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_id(value: str, limit: int = 180) -> str:
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in ("-", "_"))[:limit]


def _root(path: str) -> Path:
    if path:
        return Path(path).expanduser()
    env_root = os.environ.get("MEMCORE_ROOT") or os.environ.get("MEMCORE_XINGCE_ROOT_OVERRIDE")
    if env_root:
        return Path(env_root).expanduser()
    return _REPO_ROOT


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                item["_source_path"] = str(path)
                rows.append(item)
    except Exception:
        return rows
    return rows


def _latest_action(actions_dir: Path, candidate_id: str) -> dict[str, Any]:
    for path in sorted(actions_dir.glob("*.jsonl"), reverse=True):
        for item in _iter_jsonl(path):
            if str(item.get("candidate_id") or "") == candidate_id:
                return item
    return {}


def _is_consumable_action(action: dict[str, Any]) -> bool:
    return action.get("action_status") in {
        "queued_for_experience_service_review",
        "queued_for_experience_upgrade_review",
        "auto_adopted_evidence_bound",
    }


def _first_evidence_ref(candidate: dict[str, Any]) -> dict[str, Any]:
    refs = candidate.get("evidence_refs")
    if isinstance(refs, list):
        for item in refs:
            if isinstance(item, dict) and (item.get("resolved_source_path") or item.get("source_path")):
                return item
    refs = candidate.get("source_refs")
    if isinstance(refs, dict):
        return refs
    return {}


def _byte_offsets(ref: dict[str, Any]) -> dict[str, int]:
    offsets = ref.get("byte_offsets") if isinstance(ref.get("byte_offsets"), dict) else {}
    if "start" in offsets and "end" in offsets:
        return {"start": int(offsets["start"]), "end": int(offsets["end"])}
    nested = offsets.get("_computed_verbatim") if isinstance(offsets.get("_computed_verbatim"), dict) else {}
    if "start" in nested and "end" in nested:
        return {"start": int(nested["start"]), "end": int(nested["end"])}
    report = ref.get("resolution_report") if isinstance(ref.get("resolution_report"), dict) else {}
    computed = report.get("computed_byte_offsets") if isinstance(report.get("computed_byte_offsets"), dict) else {}
    if "start" in computed and "end" in computed:
        return {"start": int(computed["start"]), "end": int(computed["end"])}
    return {}


def _read_source_slice(ref: dict[str, Any]) -> tuple[str, str, dict[str, int], str]:
    source_path = str(ref.get("resolved_source_path") or ref.get("source_path") or "").strip()
    offsets = _byte_offsets(ref)
    if not source_path:
        raise ValueError("missing_source_path")
    if "start" not in offsets or "end" not in offsets:
        raise ValueError("missing_byte_offsets")
    start, end = int(offsets["start"]), int(offsets["end"])
    if start < 0 or end <= start:
        raise ValueError("invalid_byte_offsets")
    with open(source_path, "rb") as f:
        f.seek(start)
        raw = f.read(end - start)
    if len(raw) != end - start:
        raise ValueError("byte_offsets_out_of_range")
    return raw.decode("utf-8", errors="ignore"), hashlib.sha256(raw).hexdigest(), {"start": start, "end": end}, source_path


def _already_backfilled(candidate: dict[str, Any]) -> bool:
    # A backfill is complete only after the corrected candidate persists the
    # preserved public library_id. Older interim backfills without library_id are
    # intentionally eligible for one more append-only preserve-id pass.
    meta = candidate.get("verbatim_backfill")
    if isinstance(meta, dict) and meta.get("old_candidate_id") and candidate.get("library_id"):
        return True
    ref = _first_evidence_ref(candidate)
    offsets = ref.get("byte_offsets") if isinstance(ref.get("byte_offsets"), dict) else {}
    return bool(candidate.get("library_id") and candidate.get("verbatim_sha256") and "start" in offsets and "end" in offsets)


def _action_receipt(candidate: dict[str, Any], candidate_path: Path, *, operator: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "action_id": "xingce-action-" + uuid.uuid4().hex[:16],
        "created_at": _now(),
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "candidate_type": candidate.get("candidate_type", "xingce_work_experience"),
        "action": "auto_adopt",
        "action_status": "auto_adopted_evidence_bound",
        "operator": operator,
        "reason": reason,
        "source_candidate_path": str(candidate_path),
        "source_mode": candidate.get("source_mode", ""),
        "write_boundary": {
            "action_receipt_write_performed": True,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "notes": [
            "xingce_verbatim_backfill",
            "evidence_bound_auto_adopted",
            "no_human_review_gate",
            "original_candidate_artifact_not_modified",
        ],
    }


def _supersede_receipt(old_candidate: dict[str, Any], old_path: Path, new_candidate: dict[str, Any], new_path: Path) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "action_id": "xingce-action-" + uuid.uuid4().hex[:16],
        "created_at": _now(),
        "candidate_id": str(old_candidate.get("candidate_id") or ""),
        "candidate_type": old_candidate.get("candidate_type", "xingce_work_experience"),
        "action": "supersede",
        "action_status": "superseded_by_verbatim_backfill",
        "operator": "xingce_verbatim_backfill",
        "reason": "old candidate projected distilled text in verbatim slot or lacked flat source-byte evidence fields",
        "source_candidate_path": str(old_path),
        "superseded_by_candidate_id": str(new_candidate.get("candidate_id") or ""),
        "superseded_by_candidate_path": str(new_path),
        "write_boundary": {
            "action_receipt_write_performed": True,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "notes": [
            "old_candidate_hidden_from_catalog_by_non_consumable_latest_action",
            "original_candidate_artifact_not_modified",
        ],
    }


def _write_action(actions_dir: Path, receipt: dict[str, Any], suffix: str) -> Path:
    candidate_id = _safe_id(str(receipt.get("candidate_id") or "xingce-candidate"))
    path = actions_dir / f"{_stamp()}-{candidate_id}-{suffix}.jsonl"
    actions_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def backfill(root: str | Path) -> dict[str, Any]:
    root = Path(root).expanduser()
    candidates_dir = root / "output" / "xingce_work_experience" / "candidates"
    actions_dir = root / "output" / "xingce_work_experience" / "actions"
    report: dict[str, Any] = {
        "ok": True,
        "root": str(root),
        "scanned": 0,
        "backfilled": 0,
        "skipped": 0,
        "errors": [],
        "mappings": [],
        "write_performed": True,
        "original_candidates_modified": False,
    }
    for old_path in sorted(candidates_dir.glob("xingce-*-candidate.json")):
        old_candidate = _read_json(old_path)
        if old_candidate.get("candidate_type") != "xingce_work_experience":
            continue
        old_id = str(old_candidate.get("candidate_id") or "").strip()
        if not old_id:
            continue
        report["scanned"] += 1
        latest = _latest_action(actions_dir, old_id)
        if not _is_consumable_action(latest):
            report["skipped"] += 1
            continue
        if _already_backfilled(old_candidate):
            report["skipped"] += 1
            continue
        try:
            ref = _first_evidence_ref(old_candidate)
            verbatim, verbatim_sha, offsets, source_path = _read_source_slice(ref)
        except Exception as exc:
            report["errors"].append({"candidate_id": old_id, "error": str(exc), "path": str(old_path)})
            report["ok"] = False
            continue

        backfill_meta = old_candidate.get("verbatim_backfill") if isinstance(old_candidate.get("verbatim_backfill"), dict) else {}
        public_base_id = str(backfill_meta.get("old_candidate_id") or old_id)
        old_library_id = library_id_for({"_type": "xingce_work_experience_candidate", "exp_id": public_base_id, "library_shelf": "xingce"})
        new_candidate = copy.deepcopy(old_candidate)
        suffix = hashlib.sha256((public_base_id + verbatim_sha).encode("utf-8")).hexdigest()[:12]
        tag = "preserve" if backfill_meta else "verbatim"
        new_id = f"{public_base_id}-{tag}-{suffix}"
        new_candidate["candidate_id"] = new_id
        new_candidate["library_id"] = old_library_id
        new_candidate["verbatim_excerpt"] = verbatim
        new_candidate["verbatim_sha256"] = verbatim_sha
        new_candidate["supersedes"] = sorted(set([old_id, *[str(v) for v in old_candidate.get("supersedes", []) if v]]))
        new_candidate.setdefault("source_mode", old_candidate.get("source_mode") or latest.get("source_mode") or "")
        new_candidate["updated_at"] = _now()
        new_candidate["verbatim_backfill"] = {
            "old_candidate_id": old_id,
            "public_base_candidate_id": public_base_id,
            "preserved_library_id": old_library_id,
            "public_handle_preserved": True,
            "old_candidate_path": str(old_path),
            "source_path": source_path,
            "byte_offsets": offsets,
            "verbatim_sha256": verbatim_sha,
            "backfilled_at": _now(),
            "append_only": True,
            "original_candidate_modified": False,
        }
        evidence_refs = new_candidate.get("evidence_refs") if isinstance(new_candidate.get("evidence_refs"), list) else []
        if evidence_refs:
            first = dict(evidence_refs[0])
            first["source_path"] = first.get("source_path") or source_path
            first["resolved_source_path"] = first.get("resolved_source_path") or source_path
            first["byte_offsets"] = dict(offsets)
            first["verbatim_sha256"] = verbatim_sha
            evidence_refs[0] = first
            new_candidate["evidence_refs"] = evidence_refs
        else:
            new_candidate["evidence_refs"] = [{
                "source_path": source_path,
                "resolved_source_path": source_path,
                "byte_offsets": dict(offsets),
                "verbatim_sha256": verbatim_sha,
            }]

        new_path = candidates_dir / f"{_safe_id(new_id)}-candidate.json"
        _write_json(new_path, new_candidate)
        auto_path = _write_action(
            actions_dir,
            _action_receipt(
                new_candidate,
                new_path,
                operator="xingce_verbatim_backfill",
                reason="auto-adopted corrected source-byte verbatim backfill; no human review gate",
            ),
            "auto_adopt",
        )
        supersede_path = _write_action(
            actions_dir,
            _supersede_receipt(old_candidate, old_path, new_candidate, new_path),
            "superseded",
        )
        report["backfilled"] += 1
        report["mappings"].append({
            "old_candidate_id": old_id,
            "new_candidate_id": new_id,
            "public_base_candidate_id": public_base_id,
            "old_library_id": old_library_id,
            "preserved_library_id": old_library_id,
            "new_library_id": library_id_for(new_candidate),
            "public_handle_preserved": True,
            "source_path": source_path,
            "byte_offsets": offsets,
            "verbatim_sha256": verbatim_sha,
            "new_candidate_path": str(new_path),
            "auto_action_path": str(auto_path),
            "supersede_action_path": str(supersede_path),
        })
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="", help="Time Library root; defaults to MEMCORE_ROOT or repo root")
    parser.add_argument("--receipt", default="", help="Optional JSON receipt path")
    args = parser.parse_args()
    result = backfill(_root(args.root))
    if args.receipt:
        _write_json(Path(args.receipt).expanduser(), result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
