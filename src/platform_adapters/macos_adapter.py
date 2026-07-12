#!/usr/bin/env python3
"""macOS adapter for the canonical Time Library release artifact."""

from . import build_release_package


def build_package(version, output_dir=None):
    """Build the same release ZIP used by every supported platform."""
    return build_release_package(version, output_dir)


def is_supported():
    """Check if macOS packaging is supported on this platform."""
    import sys
    return sys.platform == "darwin"
