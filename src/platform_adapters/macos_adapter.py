#!/usr/bin/env python3
"""
platform_adapters/macos_adapter: macOS package building (stub)
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def build_package(version, output_dir=None):
    """macOS package: stub - not implemented in N1A."""
    raise NotImplementedError("macOS packaging not implemented in N1A")


def is_supported():
    """Check if macOS packaging is supported on this platform."""
    import sys
    return sys.platform == "darwin"
