#!/usr/bin/env python3
"""Capture and restore small installer-owned files for transactional rollback."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any


MANIFEST = "manifest.json"


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def capture(snapshot_root: Path, paths: list[Path]) -> dict[str, Any]:
    snapshot_root = snapshot_root.expanduser().resolve()
    if snapshot_root.exists() and any(snapshot_root.iterdir()):
        raise ValueError(f"snapshot directory is not empty: {snapshot_root}")
    snapshot_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(snapshot_root, 0o700)
    entries = []
    seen = set()
    for index, raw_path in enumerate(paths):
        path = raw_path.expanduser()
        if not path.is_absolute():
            raise ValueError(f"snapshot path must be absolute: {path}")
        path_text = str(path)
        if path_text in seen:
            continue
        seen.add(path_text)
        backup = snapshot_root / f"item-{index:04d}"
        if path.is_symlink():
            entry = {"path": path_text, "kind": "symlink", "target": os.readlink(path)}
        elif path.is_file():
            shutil.copy2(path, backup)
            entry = {"path": path_text, "kind": "file", "backup": backup.name}
        elif path.is_dir():
            shutil.copytree(path, backup, symlinks=True)
            entry = {"path": path_text, "kind": "directory", "backup": backup.name}
        else:
            entry = {"path": path_text, "kind": "absent"}
        entries.append(entry)
    result = {"contract": "time_library_install_transaction_snapshot.v1", "entries": entries}
    (snapshot_root / MANIFEST).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def restore(snapshot_root: Path) -> dict[str, Any]:
    snapshot_root = snapshot_root.expanduser().resolve()
    manifest = json.loads((snapshot_root / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("contract") != "time_library_install_transaction_snapshot.v1":
        raise ValueError("transaction snapshot contract mismatch")
    restored = []
    for entry in manifest.get("entries") or []:
        path = Path(entry["path"])
        kind = entry["kind"]
        _remove(path)
        if kind == "absent":
            restored.append({"path": str(path), "kind": kind})
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "symlink":
            path.symlink_to(entry["target"])
        elif kind == "file":
            shutil.copy2(snapshot_root / entry["backup"], path)
        elif kind == "directory":
            shutil.copytree(snapshot_root / entry["backup"], path, symlinks=True)
        else:
            raise ValueError(f"unsupported snapshot kind: {kind}")
        restored.append({"path": str(path), "kind": kind})
    return {
        "contract": "time_library_install_transaction_restore.v1",
        "restored_count": len(restored),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--snapshot-root", type=Path, required=True)
    capture_parser.add_argument("--path", type=Path, action="append", default=[])
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--snapshot-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "capture":
        result = capture(args.snapshot_root, args.path)
    else:
        result = restore(args.snapshot_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
