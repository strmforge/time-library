#!/usr/bin/env python3
"""Linux adapter for the canonical Time Library release artifact."""

import hashlib

from . import build_release_package


def get_linux_system_info():
    """Get Linux system info for package naming."""
    import platform, os
    return {
        "os": "linux",
        "arch": platform.machine(),
        "hostname": platform.node(),
        "kernel": platform.release(),
    }


def build_package(version, output_dir=None):
    """Build the same release ZIP used by every supported platform."""
    return build_release_package(version, output_dir)


def get_package_checksum(package_path):
    """SHA256 checksum of package."""
    h = hashlib.sha256()
    with open(package_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
