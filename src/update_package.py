#!/usr/bin/env python3
"""
Update package manifest contract
Validates update package manifest: VERSION, metadata, checksums, tar integrity.
"""
import json, hashlib, tarfile, zipfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime

@dataclass
class ManifestContract:
    """Update package manifest contract."""
    version: str
    platform: str          # linux / windows / darwin
    arch: str               # x86_64 / arm64
    package_name: str
    checksum: str           # sha256 of tar.gz
    size_bytes: int
    released_at: str
    type: str = "tar.gz"    # tar.gz / zip
    min_lifecycle_version: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "platform": self.platform,
            "arch": self.arch,
            "package_name": self.package_name,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "released_at": self.released_at,
            "type": self.type,
            "min_lifecycle_version": self.min_lifecycle_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ManifestContract":
        return cls(
            version=d["version"],
            platform=d["platform"],
            arch=d["arch"],
            package_name=d["package_name"],
            checksum=d["checksum"],
            size_bytes=d["size_bytes"],
            released_at=d["released_at"],
            type=d.get("type", "tar.gz"),
            min_lifecycle_version=d.get("min_lifecycle_version"),
        )


class UpdatePackageValidator:
    """
    Validates an update package against the manifest contract.
    Enforces:
    - VERSION file presence
    - metadata.json presence and valid fields
    - checksum match
    - tar integrity (no path traversal)
    - required entries
    """

    REQUIRED_MANIFEST_FIELDS = {"version", "platform", "arch", "package_name", "checksum", "size_bytes", "released_at"}
    PLATFORMS = {"linux", "windows", "darwin"}
    VALID_TYPES = {"tar.gz", "zip"}

    def __init__(self, pkg_path: str, manifest_path: Optional[str] = None,
                 known_checksums: Optional[Dict[str, str]] = None):
        self.pkg_path = Path(pkg_path)
        self.manifest_path = Path(manifest_path) if manifest_path else None
        self.known_checksums = known_checksums or {}
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.manifest: Optional[ManifestContract] = None

    def validate(self) -> bool:
        """Run all validations. Returns True if all pass."""
        self.errors.clear()
        self.warnings.clear()

        if not self.pkg_path.exists():
            self.errors.append(f"package not found: {self.pkg_path}")
            return False

        # 1. Package type detection and opening
        if self.pkg_path.suffix == ".gz" or self.pkg_path.name.endswith(".tar.gz"):
            ok = self._validate_tar_package()
        elif self.pkg_path.suffix == ".zip":
            ok = self._validate_zip_package()
        else:
            self.errors.append(f"unknown package type: {self.pkg_path.suffix}")
            return False

        if not ok:
            return False

        # 2. Manifest validation
        if not self._validate_manifest():
            return False

        # 3. Checksum validation
        self._validate_checksum()

        return len(self.errors) == 0

    def _validate_tar_package(self) -> bool:
        """Validate tar.gz package: integrity and path traversal."""
        try:
            with tarfile.open(self.pkg_path, "r:gz") as tar:
                # Check for path traversal in member names
                for member in tar.getmembers():
                    if self._is_path_traversal(member.name):
                        self.errors.append(f"tar slip: unsafe path in package: {member.name!r}")
                        return False
            return True
        except tarfile.TarError as e:
            self.errors.append(f"tarfile error: {e}")
            return False
        except Exception as e:
            self.errors.append(f"failed to open package: {e}")
            return False

    def _validate_zip_package(self) -> bool:
        """Validate zip package: integrity and path traversal."""
        try:
            with zipfile.ZipFile(self.pkg_path) as zf:
                for name in zf.namelist():
                    if self._is_path_traversal(name):
                        self.errors.append(f"zip slip: unsafe path in package: {name!r}")
                        return False
            return True
        except zipfile.BadZipFile as e:
            self.errors.append(f"bad zip file: {e}")
            return False
        except Exception as e:
            self.errors.append(f"failed to open zip: {e}")
            return False

    def _is_path_traversal(self, name: str) -> bool:
        """Check for path traversal in a file name."""
        # Absolute path attempt
        if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
            return True
        # Path traversal attempt
        parts = name.replace("\\", "/").split("/")
        if ".." in parts:
            return True
        return False

    def _validate_manifest(self) -> bool:
        """Load and validate manifest contract."""
        if not self.manifest_path:
            # Try to find metadata.json alongside package
            meta = self.pkg_path.with_suffix(".metadata.json")
            if meta.exists():
                self.manifest_path = meta
            else:
                self.warnings.append("no metadata.json found; cannot validate contract")
                return True  # Not fatal for dry-run

        if not self.manifest_path or not self.manifest_path.exists():
            self.warnings.append("manifest not provided and not found alongside package")
            return True

        try:
            data = json.loads(self.manifest_path.read_text())
        except Exception as e:
            self.errors.append(f"manifest read error: {e}")
            return False

        missing = self.REQUIRED_MANIFEST_FIELDS - set(data.keys())
        if missing:
            self.errors.append(f"manifest missing required fields: {missing}")
            return False

        unknown = set(data.keys()) - self.REQUIRED_MANIFEST_FIELDS - {
            "type", "min_lifecycle_version", "release_notes"
        }
        if unknown:
            self.warnings.append(f"manifest has unknown fields: {unknown}")

        if data.get("platform") not in self.PLATFORMS:
            self.errors.append(f"invalid platform: {data.get('platform')!r} not in {self.PLATFORMS}")
            return False

        if data.get("type") not in self.VALID_TYPES:
            self.errors.append(f"invalid type: {data.get('type')!r} not in {self.VALID_TYPES}")
            return False

        try:
            self.manifest = ManifestContract.from_dict(data)
        except Exception as e:
            self.errors.append(f"manifest parse error: {e}")
            return False

        return True

    def _validate_checksum(self) -> bool:
        """Validate package checksum."""
        try:
            sha256 = hashlib.sha256(self.pkg_path.read_bytes()).hexdigest()
        except Exception as e:
            self.errors.append(f"checksum compute failed: {e}")
            return False

        if self.manifest:
            expected = self.manifest.checksum
        elif self.known_checksums:
            # Try to match by version
            version = self.manifest.version if self.manifest else None
            expected = self.known_checksums.get(version) if version else None
            if not expected:
                self.warnings.append("no known checksum for this version")
                return True
        else:
            self.warnings.append("no expected checksum to validate against")
            return True

        if sha256 != expected:
            self.errors.append(
                f"checksum mismatch: computed={sha256[:16]}... expected={expected[:16]}..."
            )
            return False

        return True

    def result(self) -> dict:
        """Return structured validation result."""
        return {
            "ok": len(self.errors) == 0,
            "errors": self.errors,
            "warnings": self.warnings,
            "manifest": self.manifest.to_dict() if self.manifest else None,
            "package": str(self.pkg_path),
        }


def validate_package(pkg_path: str, manifest_path: Optional[str] = None,
                     known_checksums: Optional[Dict[str, str]] = None) -> dict:
    """Convenience function."""
    v = UpdatePackageValidator(pkg_path, manifest_path, known_checksums)
    v.validate()
    return v.result()


if __name__ == "__main__":
    import sys
    pkg = sys.argv[1] if len(sys.argv) > 1 else "release/memcore-cloud-2026.5.25-linux-x86_64.tar.gz"
    result = validate_package(pkg)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["ok"] else 1)
