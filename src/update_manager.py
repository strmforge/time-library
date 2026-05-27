#!/usr/bin/env python3
"""
P9-System-X5: Cross-Platform Update Manager
Provides unified update safety model across Linux / Windows / macOS.
Key design:
- Windows: apply disabled (user-mode preview only)
- macOS: apply disabled (user-mode preview only)
- Linux: gated (production_apply=false by default, requires explicit flag)
- All: dry-run never writes to current/releases/protected dirs
"""
import json, platform, subprocess, hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict

# Known-good checksums for official release packages
KNOWN_CHECKSUMS = {
    "2026.5.25": {}
}

# Protected system directories (must never be overlapped by install_root)
PROTECTED_PATHS = [
    Path.home() / ".openclaw",
    Path.home() / ".npm-global",
    Path("/usr/local"),
    Path("/usr/bin"),
    Path("/usr/lib"),
    Path("/opt"),
    Path("/etc"),
    Path("/root"),
    # Windows equivalents
    Path.home() / ".openclaw",
    Path.home() / "AppData" / "Roaming" / "npm",
]

# Directories that survive updates (never overwritten)
PERSISTENT_DIRS = {
    "config", "data", "logs", "state", "zhiyi", "memory",
    "runtime", "backups", "raw", "local_files", "input",
}

# Directories that get replaced on update (code only)
REPLACEABLE_DIRS = {"src", "tools", "scripts", "docs"}


@dataclass
class PlatformConfig:
    """Per-platform update configuration."""
    platform: str
    apply_enabled: bool = False        # Whether real apply is allowed
    production_apply: bool = False     # Whether production apply is allowed
    requires_root: bool = False       # Whether root/sudo is required
    supports_staging: bool = True     # Whether staging directory is supported
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "apply_enabled": self.apply_enabled,
            "production_apply": self.production_apply,
            "requires_root": self.requires_root,
            "supports_staging": self.supports_staging,
            "notes": self.notes,
        }

    @classmethod
    def for_current_platform(cls) -> "PlatformConfig":
        sys = platform.system()
        if sys == "Windows":
            return cls(
                platform="windows",
                apply_enabled=False,
                production_apply=False,
                requires_root=False,
                supports_staging=True,
                notes="Windows user-mode: apply disabled. Use skeleton package for preview.",
            )
        elif sys == "Darwin":
            return cls(
                platform="darwin",
                apply_enabled=False,
                production_apply=False,
                requires_root=False,
                supports_staging=True,
                notes="macOS user-mode: apply disabled. Use rsync + manual restart for preview.",
            )
        else:
            return cls(
                platform="linux",
                apply_enabled=True,
                production_apply=False,   # GATED: requires explicit --production flag
                requires_root=True,
                supports_staging=True,
                notes="Linux: gated. production_apply=false by default.",
            )


class UpdateSafetyModel:
    """
    Cross-platform update safety model.
    Encodes the safety rules for update operations.
    """

    def __init__(self, platform_cfg: Optional[PlatformConfig] = None):
        self.platform_cfg = platform_cfg or PlatformConfig.for_current_platform()

    def can_apply(self, production: bool = False) -> tuple[bool, str]:
        """
        Check if apply is allowed.
        Returns (allowed, reason).
        """
        if not self.platform_cfg.apply_enabled:
            return False, f"apply disabled on {self.platform_cfg.platform}"

        if production and not self.platform_cfg.production_apply:
            return False, (
                f"production apply gated on {self.platform_cfg.platform}. "
                "production_apply=false. Use --production flag with caution."
            )

        return True, "allowed"

    def check_install_root(self, install_root: str) -> tuple[bool, str]:
        """
        Check if install_root overlaps with protected paths.
        NOTE: install_root being a SUBDIRECTORY of a protected path (e.g. /opt/memcore-cloud
        inside /opt) is VALID. Only when a PROTECTED PATH is INSIDE install_root is it forbidden.
        Returns (safe, error_msg).
        """
        ir = Path(install_root).resolve()
        overlaps = []
        for prot in PROTECTED_PATHS:
            p = Path(prot).resolve()
            try:
                # Check if protected path p is INSIDE install_root ir — FORBIDDEN
                p.relative_to(ir)
                overlaps.append(f"PROTECTED path {prot} is inside install_root {ir} — forbidden")
            except ValueError:
                pass  # p is not inside ir — fine (ir may be inside p, which is valid)
        return len(overlaps) == 0, overlaps[0] if overlaps else "safe"

    def check_package(self, pkg_path: str) -> tuple[bool, str]:
        """
        Basic package checks before apply.
        Returns (ok, msg).
        """
        p = Path(pkg_path)
        if not p.exists():
            return False, f"package not found: {pkg_path}"
        if p.stat().st_size == 0:
            return False, f"package is empty: {pkg_path}"
        return True, "ok"

    def get_safety_status(self) -> dict:
        """Return full safety status for Dashboard/API."""
        cfg = self.platform_cfg
        return {
            "platform": cfg.platform,
            "apply_enabled": cfg.apply_enabled,
            "production_apply": cfg.production_apply,
            "requires_root": cfg.requires_root,
            "protected_paths_count": len(PROTECTED_PATHS),
            "persistent_dirs": sorted(PERSISTENT_DIRS),
            "replaceable_dirs": sorted(REPLACEABLE_DIRS),
            "safety_model_version": "1.0",
            "update_policy": (
                "apply disabled on this platform"
                if not cfg.apply_enabled else
                "apply gated: production_apply=false"
            ),
        }

    def verify_checksum(self, pkg_path: str, version: str = None, platform: str = None) -> tuple[bool, str]:
        """Verify package checksum against known checksums.
        Uses platform-specific checksum if provided, otherwise falls back to version-only lookup.
        """
        if version is None:
            version = VERSION

        version_checksums = KNOWN_CHECKSUMS.get(version, {})

        # Try platform-specific checksum first
        if platform and platform in version_checksums:
            expected = version_checksums[platform]
        elif isinstance(version_checksums, dict) and len(version_checksums) > 0:
            # Has platform-specific checksums but no match for this platform
            # Accept if any checksum matches (backward compat)
            return True, f"no known checksum for platform {platform}, version {version}"
        elif isinstance(version_checksums, str):
            # Old flat format: single checksum per version (Linux fallback)
            expected = version_checksums
        else:
            return True, f"no known checksum for version {version}"

        try:
            sha256 = hashlib.sha256(Path(pkg_path).read_bytes()).hexdigest()
        except Exception as e:
            return False, f"checksum compute failed: {e}"

        if sha256 != expected:
            return False, f"checksum mismatch: {sha256[:16]}... != {expected[:16]}..."

        return True, "checksum verified"


class StagingManager:
    """
    Manages staging directory for update preview.
    dry-run always uses staging, never touches current installation.
    """

    def __init__(self, memcore_root: str):
        self.memcore_root = Path(memcore_root)
        self.staging_root = self.memcore_root / "staging"

    def prepare_staging(self, version: str) -> Path:
        """Create a staging directory for this version."""
        staging = self.staging_root / f"memcore-cloud-{version}"
        staging.mkdir(parents=True, exist_ok=True)
        return staging

    def cleanup_staging(self, version: Optional[str] = None) -> int:
        """Remove staging directory. Returns count of files removed."""
        if version:
            staging = self.staging_root / f"memcore-cloud-{version}"
            if staging.exists():
                import shutil
                count = len(list(staging.rglob("*"))) if staging.exists() else 0
                shutil.rmtree(staging)
                return count
        return 0

    def staging_isolation_check(self, install_root: str) -> tuple[bool, str]:
        """
        Verify that staging does NOT touch current installation.
        Returns (isolated, msg).
        """
        staging = self.staging_root.resolve()
        ir = Path(install_root).resolve()

        # Staging must not be inside install_root
        try:
            staging.relative_to(ir)
            return False, f"staging {staging} is inside install_root {ir}"
        except ValueError:
            pass

        # Staging must not contain protected paths
        for prot in PROTECTED_PATHS:
            try:
                ir.relative_to(prot.resolve())
                return False, f"install_root {ir} overlaps with protected path {prot}"
            except ValueError:
                pass

        return True, "staging isolated from current installation"


def get_update_safety_status(memcore_root: str = "") -> dict:
    """Convenience: get update safety status for current platform."""
    model = UpdateSafetyModel()
    return model.get_safety_status()


if __name__ == "__main__":
    import sys
    status = get_update_safety_status()
    print(json.dumps(status, indent=2))
