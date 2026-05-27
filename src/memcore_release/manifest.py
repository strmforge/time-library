#!/usr/bin/env python3
"""
memcore_release.manifest: Manage releases.json catalog (platform-independent)
"""
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent.parent
RELEASE_DIR = ROOT / "release"


def get_releases_catalog():
    """Read releases.json or return empty catalog."""
    catalog_path = RELEASE_DIR / "releases.json"
    if catalog_path.exists():
        with open(catalog_path) as f:
            return json.load(f)
    return {"releases": [], "generated_at": None}


def update_releases_catalog(metadata_path):
    """
    Add a new release to releases.json catalog.
    Platform-independent.
    """
    catalog_path = RELEASE_DIR / "releases.json"
    catalog = get_releases_catalog()

    with open(metadata_path) as f:
        new_release = json.load(f)

    # Avoid duplicates
    existing = [r for r in catalog.get("releases", [])
                if r.get("version") == new_release.get("version")
                and r.get("platform") == new_release.get("platform")]
    if not existing:
        catalog.setdefault("releases", []).append(new_release)
        catalog["generated_at"] = datetime.now(timezone.utc).isoformat()
        with open(catalog_path, "w") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)

    return catalog


if __name__ == "__main__":
    from .version import get_current_version
    v = get_current_version()
    print(f"Version: {v}")
    cat = get_releases_catalog()
    print(f"Releases in catalog: {len(cat.get('releases', []))}")
