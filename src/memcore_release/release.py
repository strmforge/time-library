#!/usr/bin/env python3
"""
memcore_release.release: Generate latest.json and manage release catalog (platform-independent)
"""
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent.parent
RELEASE_DIR = ROOT / "release"


def generate_latest_from_metadata(metadata_path, output_path=None):
    """
    Read a metadata file and generate latest.json.
    Platform-independent.
    """
    if output_path is None:
        output_path = RELEASE_DIR / "latest.json"
    output_path = Path(output_path)

    with open(metadata_path) as f:
        metadata = json.load(f)

    latest_json = {
        "latest_version": metadata["version"],
        "releases": [metadata],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with open(output_path, "w") as f:
        json.dump(latest_json, f, ensure_ascii=False, indent=2)

    return latest_json


def get_all_releases():
    """Return all releases from release directory."""
    releases = []
    for mf in sorted(RELEASE_DIR.glob("*.metadata.json")):
        with open(mf) as f:
            releases.append(json.load(f))
    return releases


def get_latest_release():
    """Return the latest release by version."""
    releases = get_all_releases()
    if not releases:
        return None
    return max(releases, key=lambda r: r["released_at"])


if __name__ == "__main__":
    from .version import get_current_version
    v = get_current_version()
    print(f"Current version: {v}")
    releases = get_all_releases()
    print(f"Total releases: {len(releases)}")
