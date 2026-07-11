#!/usr/bin/env python3
"""Single source of truth for the installed Time Library version."""

from __future__ import annotations

import os
from pathlib import Path


def memcore_root_from_file(anchor: str | os.PathLike[str] | None = None) -> Path:
    if os.environ.get("MEMCORE_ROOT"):
        return Path(os.environ["MEMCORE_ROOT"]).expanduser()
    source = Path(anchor or __file__).resolve()
    if source.name == "VERSION":
        return source.parent
    for parent in source.parents:
        if (parent / "VERSION").is_file() and (parent / "src").is_dir():
            return parent
    return Path(__file__).resolve().parents[1]


def read_memcore_version(root: str | os.PathLike[str] | None = None, default: str = "unknown") -> str:
    base = Path(root).expanduser() if root else memcore_root_from_file()
    try:
        version = (base / "VERSION").read_text(encoding="utf-8-sig").strip()
    except OSError:
        return default
    return version or default


SERVICE_VERSION = read_memcore_version()
