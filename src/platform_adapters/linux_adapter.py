#!/usr/bin/env python3
"""
platform_adapters/linux_adapter: Linux package building (real implementation)
"""
import os, tarfile, hashlib, subprocess
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent.parent
RELEASE_DIR = ROOT / "release"
SRC_DIR = ROOT / "src"


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
    """
    Build Linux tar.gz package.
    Returns: package_path
    """
    if output_dir is None:
        output_dir = RELEASE_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)

    package_name = f"memcore-cloud-{version}-linux-x86_64.tar.gz"
    package_path = output_dir / package_name

    # Files to include in package
    include_dirs = [
        (SRC_DIR, "src"),
    ]
    include_files = [
        (ROOT / "VERSION", "VERSION"),
        (ROOT / "config", "config"),
        (ROOT / "data", "data"),
        (ROOT / "docs", "docs"),
        (ROOT / "tools", "tools"),
        (ROOT / "AGENTS.md", "AGENTS.md"),
        (ROOT / "CURRENT_STATE.md", "CURRENT_STATE.md"),
    ]

    # Build tar.gz
    with tarfile.open(package_path, "w:gz") as tar:
        # Add VERSION
        v_path = ROOT / "VERSION"
        tar.add(v_path, arcname=f"memcore-cloud-{version}/VERSION")

        # Add src/
        src_path = SRC_DIR
        for item in src_path.iterdir():
            if item.is_file() and not item.name.startswith("."):
                tar.add(item, arcname=f"memcore-cloud-{version}/src/{item.name}")

        # Add config/
        cfg_path = ROOT / "config"
        if cfg_path.exists():
            for item in cfg_path.iterdir():
                if item.is_file() and item.suffix == ".json":
                    tar.add(item, arcname=f"memcore-cloud-{version}/config/{item.name}")

        # Add tools/
        tools_path = ROOT / "tools"
        if tools_path.exists():
            for item in tools_path.iterdir():
                if item.is_file() and item.suffix == ".py":
                    tar.add(item, arcname=f"memcore-cloud-{version}/tools/{item.name}")

    return package_path


def get_package_checksum(package_path):
    """SHA256 checksum of package."""
    h = hashlib.sha256()
    with open(package_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


if __name__ == "__main__":
    from ..memcore_release.version import get_current_version
    v = get_current_version()
    print(f"Building Linux package for version {v}...")
    p = build_package(v)
    cs = get_package_checksum(p)
    print(f"Package: {p.name}")
    print(f"Checksum: {cs}")
