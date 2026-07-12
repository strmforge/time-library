#!/usr/bin/env python3
"""Rewrite install-root paths in local state without resetting checkpoints."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any


STATE_PATHS = (
    Path(".checkpoint"),
    Path(".checkpoint_p2.json"),
    Path("config/window_binding_registry.json"),
    Path("config/reading_area_registry.json"),
)


def _progress(value: Any) -> tuple[int, int, str]:
    if not isinstance(value, dict):
        return (-1, -1, "")
    return (
        int(value.get("offset") or -1),
        int(value.get("source_size") or -1),
        str(value.get("last_update") or value.get("updated_at") or ""),
    )


def _merge_collision(existing: Any, incoming: Any) -> Any:
    if isinstance(existing, dict) and isinstance(incoming, dict):
        if "offset" in existing or "offset" in incoming:
            return incoming if _progress(incoming) > _progress(existing) else existing
        merged = dict(existing)
        for key, value in incoming.items():
            merged[key] = _merge_collision(merged[key], value) if key in merged else value
        return merged
    return existing


def _rewrite(value: Any, old_root: str, new_root: str) -> Any:
    if isinstance(value, str):
        return value.replace(old_root, new_root)
    if isinstance(value, list):
        return [_rewrite(item, old_root, new_root) for item in value]
    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        for key, item in value.items():
            new_key = key.replace(old_root, new_root) if isinstance(key, str) else key
            new_value = _rewrite(item, old_root, new_root)
            rewritten[new_key] = (
                _merge_collision(rewritten[new_key], new_value)
                if new_key in rewritten
                else new_value
            )
        return rewritten
    return value


def _repair_p2_regressed_offsets(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    repaired = 0
    for raw_path, checkpoint in value.items():
        if not isinstance(raw_path, str) or not isinstance(checkpoint, dict):
            continue
        try:
            offset = int(checkpoint.get("offset") or 0)
            current_size = Path(raw_path).stat().st_size
        except (OSError, TypeError, ValueError):
            continue
        if offset <= current_size:
            continue
        checkpoint["migration_source_regression_offset_before"] = offset
        checkpoint["offset"] = current_size
        checkpoint["migration_status"] = "source_regression_cursor_clamped_to_preserved_raw_size"
        repaired += 1
    return repaired


def migrate_state_file(path: Path, old_root: Path, new_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "changed": False}
    if not path.is_file():
        result["status"] = "missing"
        return result
    try:
        original = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result.update({"status": "invalid_json", "error": type(exc).__name__})
        return result

    old_text = str(old_root)
    new_text = str(new_root)
    rewritten = _rewrite(original, old_text, new_text)
    repaired_offsets = _repair_p2_regressed_offsets(rewritten) if path.name == ".checkpoint_p2.json" else 0
    payload = json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n"
    original_payload = json.dumps(original, ensure_ascii=False, indent=2) + "\n"
    if payload == original_payload:
        result["status"] = "unchanged"
        return result

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = path.with_name(path.name + f".pre-root-migration.{stamp}.json")
    suffix = 1
    while backup.exists():
        suffix += 1
        backup = path.with_name(path.name + f".pre-root-migration.{stamp}.{suffix}.json")
    shutil.copy2(path, backup)
    temporary = path.with_name(path.name + ".time-library-root-migration.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)
    result.update({
        "status": "migrated",
        "changed": True,
        "backup": str(backup),
        "top_level_count_before": len(original) if isinstance(original, dict) else None,
        "top_level_count_after": len(rewritten) if isinstance(rewritten, dict) else None,
        "legacy_root_occurrences_after": payload.count(old_text),
        "source_regression_offsets_repaired": repaired_offsets,
    })
    return result


def migrate_install_state(install_root: Path, legacy_root: Path) -> dict[str, Any]:
    install_root = install_root.expanduser().resolve()
    legacy_root = legacy_root.expanduser().resolve()
    results = [
        migrate_state_file(install_root / relative, legacy_root, install_root)
        for relative in STATE_PATHS
    ]
    return {
        "contract": "time_library_install_root_state_migration.v1",
        "install_root": str(install_root),
        "legacy_root": str(legacy_root),
        "changed_count": sum(bool(item.get("changed")) for item in results),
        "files": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("install_root", type=Path)
    parser.add_argument("legacy_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(migrate_install_state(args.install_root, args.legacy_root), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
