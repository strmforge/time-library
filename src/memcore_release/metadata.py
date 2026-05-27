#!/usr/bin/env python3
"""
memcore_release.metadata: Generate release metadata (platform-independent)
"""
import json, hashlib, os
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent.parent


def get_file_checksum(path):
    """SHA256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_release_metadata(package_path, platform="linux", arch="x86_64"):
    """
    Generate release metadata for a package.
    Platform-independent core.
    """
    if not package_path.exists():
        raise FileNotFoundError(f"Package not found: {package_path}")

    checksum = get_file_checksum(package_path)
    size = package_path.stat().st_size

    # Import version
    from .version import get_current_version
    version = get_current_version() or "unknown"

    metadata = {
        "version": version,
        "platform": platform,
        "arch": arch,
        "package_name": package_path.name,
        "checksum": checksum,
        "size_bytes": size,
        "released_at": datetime.now(timezone.utc).isoformat(),
        "type": "tar.gz" if package_path.suffix == ".gz" else "unknown",
    }
    return metadata


def write_release_metadata(metadata, output_path):
    """Write metadata to JSON file."""
    with open(output_path, "w") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def generate_latest_json(releases, output_path):
    """
    Generate latest.json with update info.
    releases: list of metadata dicts.
    """
    if not releases:
        raise ValueError("No releases provided")

    latest = max(releases, key=lambda r: r["released_at"])
    latest_json = {
        "latest_version": latest["version"],
        "releases": releases,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(output_path, "w") as f:
        json.dump(latest_json, f, ensure_ascii=False, indent=2)
    return latest_json


if __name__ == "__main__":
    from .version import get_current_version
    v = get_current_version()
    print(f"Version: {v}")
    print("Use build.py to generate release metadata")
