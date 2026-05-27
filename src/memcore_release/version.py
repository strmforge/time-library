#!/usr/bin/env python3
"""
memcore_release.version: Read current version from VERSION file
Platform-independent.
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # memcore-cloud root


def get_current_version():
    """Read version from VERSION file at project root."""
    version_file = ROOT / "VERSION"
    if not version_file.exists():
        return None
    return version_file.read_text().strip()


def get_version_parts():
    """Return (major, minor, patch) tuple."""
    v = get_current_version()
    if not v:
        return None, None, None
    parts = v.split(".")
    return tuple(parts + [None] * (3 - len(parts)))


if __name__ == "__main__":
    v = get_current_version()
    print(f"memcore-cloud version: {v}")
