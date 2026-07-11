"""Shared runtime path bootstrap for Time Library tools.

Small command-line entry points live in different folders, but they should agree
on the same repository root and import path setup. Keeping that logic here avoids
new tools growing their own sys.path snippets.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable


ROOT_MARKERS = ("VERSION", "requirements-core.txt", "src")


def repo_root_from_file(file: str | os.PathLike[str]) -> Path:
    """Find the repository/install root that owns a script or module file."""
    start = Path(file).resolve()
    current = start if start.is_dir() else start.parent
    for candidate in (current, *current.parents):
        if all((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return current


def _prepend_unique(paths: Iterable[Path]) -> None:
    for path in reversed([p for p in paths if p.exists()]):
        text = str(path)
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)


def ensure_repo_import_paths(
    file: str | os.PathLike[str],
    *,
    include_tools: bool = False,
) -> Path:
    """Put the repo root and src directory on sys.path, then return the root."""
    root = repo_root_from_file(file)
    paths = [root, root / "src"]
    if include_tools:
        paths.append(root / "tools")
    _prepend_unique(paths)
    os.environ.setdefault("MEMCORE_REPO_ROOT", str(root))
    return root


def memcore_root(default_file: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the runtime state root without changing global process state."""
    value = str(os.environ.get("MEMCORE_ROOT") or "").strip()
    if value:
        return Path(value).expanduser()
    if default_file is not None:
        return repo_root_from_file(default_file)
    return Path.cwd()
