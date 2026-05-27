#!/usr/bin/env python3
"""
platform_adapters/windows_adapter: Windows package building (stub)
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def build_package(version, output_dir=None):
    """Windows package: stub - not implemented in N1A."""
    raise NotImplementedError("Windows packaging not implemented in N1A")


def is_supported():
    """Check if Windows packaging is supported on this platform."""
    import sys
    return sys.platform == "win32"
