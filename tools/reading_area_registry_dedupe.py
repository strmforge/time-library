#!/usr/bin/env python3
"""Migrate known Time Library project registry duplicates without touching raw data."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import reading_area_registry as registry


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _project_references(value: dict[str, Any], project_id: str) -> bool:
    return project_id in value.get("declared_project_ids", []) or value.get("project_id") == project_id


def build_manifest(path: str | Path, *, history_record_id: str = "") -> dict[str, Any]:
    resolved = Path(path).expanduser()
    data = registry.load_registry(resolved)
    project_refs: dict[str, list[str]] = {}
    stores = (
        ("borrowing_cards", data["borrowing_cards"].items()),
        ("borrowing_records", ((str(item.get("record_id") or index), item) for index, item in enumerate(data["borrowing_records"]))),
        ("whiteboard_records", ((str(item.get("record_id") or index), item) for index, item in enumerate(data["whiteboard_records"]))),
        ("project_history_records", ((str(item.get("record_id") or index), item) for index, item in enumerate(data["project_history_records"]))),
        ("project_nominations", ((str(item.get("nomination_id") or index), item) for index, item in enumerate(data["project_nominations"]))),
    )
    for store_name, items in stores:
        for record_id, value in items:
            if not isinstance(value, dict):
                continue
            referenced_ids = list(value.get("declared_project_ids", []))
            if value.get("project_id"):
                referenced_ids.append(value["project_id"])
            for project_id in dict.fromkeys(referenced_ids):
                project_refs.setdefault(project_id, []).append(f"{store_name}:{record_id}")
    history = next(
        (item for item in data["project_history_records"] if item.get("record_id") == history_record_id),
        {},
    ) if history_record_id else {}
    return {
        "registry_path": str(resolved),
        "sha256": _sha256(resolved) if resolved.exists() else "",
        "projection_revision": int(data["_meta"].get("projection_revision") or 0),
        "counts": {
            "borrowing_cards": len(data["borrowing_cards"]),
            "projects": len(data["projects"]),
            "borrowing_records": len(data["borrowing_records"]),
            "whiteboard_records": len(data["whiteboard_records"]),
            "project_history_records": len(data["project_history_records"]),
            "project_nominations": len(data["project_nominations"]),
        },
        "project_ids": list(data["projects"]),
        "project_aliases": data["aliases"]["project"],
        "project_refs": project_refs,
        "project_merges": data["merges"]["project"],
        "project_archives": data["archives"]["project"],
        "history_anchor": {
            "record_id": history.get("record_id", ""),
            "project_id": history.get("project_id", ""),
            "declared_project_ids": history.get("declared_project_ids", []),
            "source_ref": history.get("source_ref", {}),
            "evidence_refs": history.get("evidence_refs", []),
            "verbatim_excerpt": history.get("verbatim_excerpt", ""),
            "verbatim_sha256": history.get("verbatim_sha256", ""),
        },
    }


def migrate(
    path: str | Path,
    *,
    canonical_project_id: str,
    merge_project_id: str,
    archive_project_id: str,
    aliases: list[str],
    history_record_id: str = "",
    archive_reason: str = "top-level work item archived into the canonical project history",
    backup_dir: str | Path = "",
) -> dict[str, Any]:
    resolved = Path(path).expanduser()
    before = build_manifest(resolved, history_record_id=history_record_id)
    backup_path = Path()
    if backup_dir:
        backup_root = Path(backup_dir).expanduser()
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_path = backup_root / f"reading_area_registry.before-{_timestamp()}.json"
        shutil.copy2(resolved, backup_path)

    merge_result = registry.merge_scope("project", merge_project_id, canonical_project_id, path=resolved)
    if not merge_result.get("ok"):
        raise RuntimeError(f"ghost merge failed: {merge_result}")
    alias_result = registry.add_scope_aliases(
        "project",
        canonical_project_id,
        aliases,
        path=resolved,
    )
    if not alias_result.get("ok"):
        raise RuntimeError(f"alias registration failed: {alias_result}")
    archive_result = registry.archive_scope(
        "project",
        archive_project_id,
        canonical_project_id,
        reason=archive_reason,
        path=resolved,
    )
    if not archive_result.get("ok"):
        raise RuntimeError(f"work-item archive failed: {archive_result}")

    after = build_manifest(resolved, history_record_id=history_record_id)
    dangling_references = {
        project_id: refs
        for project_id, refs in after["project_refs"].items()
        if project_id not in after["project_ids"]
    }
    dangling_aliases = {
        alias: target_id
        for alias, target_id in after["project_aliases"].items()
        if target_id not in after["project_ids"]
    }
    canonical_aliases = {
        alias: registry.resolve_scope_id("project", alias, path=resolved)
        for alias in aliases
    }
    history_checks = {
        "history_record_preserved": after["history_anchor"]["record_id"] == before["history_anchor"]["record_id"],
        "history_source_preserved": after["history_anchor"]["source_ref"] == before["history_anchor"]["source_ref"],
        "history_evidence_preserved": after["history_anchor"]["evidence_refs"] == before["history_anchor"]["evidence_refs"],
        "history_verbatim_preserved": (
            after["history_anchor"]["verbatim_excerpt"] == before["history_anchor"]["verbatim_excerpt"]
            and after["history_anchor"]["verbatim_sha256"] == before["history_anchor"]["verbatim_sha256"]
        ),
        "history_reassigned_canonical": after["history_anchor"]["project_id"] == canonical_project_id,
    } if history_record_id else {}
    checks = {
        "one_active_project": after["project_ids"] == [canonical_project_id],
        "counts_preserved": all(
            after["counts"][key] == before["counts"][key]
            for key in (
                "borrowing_cards",
                "borrowing_records",
                "whiteboard_records",
                "project_history_records",
                "project_nominations",
            )
        ),
        "zero_dangling_references": not dangling_references and not dangling_aliases,
        "known_aliases_resolve_canonical": set(canonical_aliases.values()) == {canonical_project_id},
        "archived_scope_not_semantic_alias": archive_project_id not in after["project_aliases"],
        **history_checks,
    }
    return {
        "ok": all(checks.values()),
        "contract": "time_library_reading_area_registry_dedupe.v1",
        "registry_path": str(resolved),
        "backup_path": str(backup_path) if backup_dir else "",
        "before": before,
        "operations": {
            "merge": merge_result,
            "aliases": alias_result,
            "archive": archive_result,
        },
        "after": after,
        "canonical_aliases": canonical_aliases,
        "dangling_references": dangling_references,
        "dangling_aliases": dangling_aliases,
        "checks": checks,
        "write_performed": before["sha256"] != after["sha256"],
        "raw_write_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--canonical-project-id", required=True)
    parser.add_argument("--merge-project-id", required=True)
    parser.add_argument("--archive-project-id", required=True)
    parser.add_argument("--alias", action="append", default=[])
    parser.add_argument("--history-record-id", default="")
    parser.add_argument("--archive-reason", default="top-level work item archived into the canonical project history")
    parser.add_argument("--backup-dir", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    receipt = migrate(
        args.registry,
        canonical_project_id=args.canonical_project_id,
        merge_project_id=args.merge_project_id,
        archive_project_id=args.archive_project_id,
        aliases=args.alias,
        history_record_id=args.history_record_id,
        archive_reason=args.archive_reason,
        backup_dir=args.backup_dir,
    )
    text = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
