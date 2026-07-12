#!/usr/bin/env python3
"""Copy packaged config files without overwriting local user state."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


PRESERVE_EXISTING_FILES = {
    "alias_map.json",
    "feature_flags.json",
    "lancedb_v2_metadata.json",
    "memcore.json",
    "model_config.json",
    "platform_storage_patterns.verified.json",
    "reading_area_registry.json",
    "source_system_registry.json",
    "window_binding_registry.json",
}


def _copy_atomic(source: Path, target: Path) -> None:
    temporary = target.with_name(target.name + ".time-library-install.tmp")
    temporary.unlink(missing_ok=True)
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


def merge_config(source_dir: Path, target_dir: Path) -> dict[str, list[str]]:
    copied: list[str] = []
    preserved: list[str] = []
    updated: list[str] = []
    target_dir.mkdir(parents=True, exist_ok=True)
    if not source_dir.is_dir():
        return {"copied": copied, "preserved_existing": preserved, "updated": updated}

    for source in sorted(source_dir.iterdir(), key=lambda path: path.name):
        if not source.is_file() or source.is_symlink():
            continue
        target = target_dir / source.name
        if target.is_symlink() or target.is_dir() or (
            target.exists() and source.name in PRESERVE_EXISTING_FILES
        ):
            preserved.append(source.name)
            continue
        existed = target.exists()
        _copy_atomic(source, target)
        (updated if existed else copied).append(source.name)
    return {"copied": copied, "preserved_existing": preserved, "updated": updated}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("target_dir", type=Path)
    args = parser.parse_args()
    result = merge_config(args.source_dir, args.target_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
