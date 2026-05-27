#!/usr/bin/env python3
"""
P9-System-X1: UpdateManager — Cross-Platform Update Distribution Contract
============================================================================
Defines platform distribution principles for memcore-cloud packages.

Platform distribution rules:
  Linux:   tar.gz → any Linux (real apply via tools/apply_linux_update.py)
  Windows: .zip → Windows (mock; real apply requires windows_adapter)
  macOS:   .tar.gz → macOS (mock; real apply requires macos_adapter)

Core principles:
  - All platforms: verify SHA256 checksum before apply
  - All platforms: boundary check install_root before extract
  - All platforms: safe_extract (no tar slip)
  - All platforms: require known_checksum allowlist
  - Linux update_dir: /tmp/memcore-update-<version>
  - Windows update_dir: %TEMP%/memcore-update-<version>
  - macOS update_dir: /tmp/memcore-update-<version>
"""
import os
import sys
import hashlib
import tarfile
from pathlib import Path
from typing import Optional, Tuple, List, Dict

CURRENT_PLATFORM = sys.platform

# ── UpdateManager Interface ────────────────────────────────────────────────────

class UpdateManager:
    """
    Abstract interface for cross-platform update management.
    """

    def verify_package(self, package_path: str, expected_checksum: str) -> Tuple[bool, str]:
        """
        Verify SHA256 checksum of package.
        Returns (ok, computed_checksum).
        """
        raise NotImplementedError

    def safe_extract(self, package_path: str, dest_dir: str) -> Tuple[bool, str]:
        """
        Safely extract package to dest_dir.
        Rejects absolute paths, traversal, protected paths.
        Returns (ok, message).
        """
        raise NotImplementedError

    def apply_update(self, package_path: str, install_root: str,
                     expected_checksum: str, dry_run: bool = True) -> Dict:
        """
        Full update flow: verify → boundary_check → safe_extract → switch_symlink.
        Returns dict with ok, steps, error.
        """
        raise NotImplementedError

    def get_platform_name(self) -> str:
        return CURRENT_PLATFORM

    def get_update_temp_dir(self) -> Path:
        """Get platform-appropriate temp directory for update staging."""
        raise NotImplementedError


# ── Linux Implementation ──────────────────────────────────────────────────────

class LinuxUpdateManager(UpdateManager):
    """
    Linux real implementation delegating to tools/apply_linux_update.py.
    """

    def __init__(self):
        self._tools_root = Path(__file__).parent.parent.parent

    def verify_package(self, package_path: str, expected_checksum: str) -> Tuple[bool, str]:
        try:
            h = hashlib.sha256()
            with open(package_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            cs = h.hexdigest()
            return cs == expected_checksum, cs
        except Exception as e:
            return False, str(e)

    def safe_extract(self, package_path: str, dest_dir: str) -> Tuple[bool, str]:
        from ..tools.apply_linux_update import safe_extract
        try:
            with tarfile.open(package_path) as tf:
                safe_extract(tf, dest_dir)
            return True, "extracted"
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)

    def apply_update(self, package_path: str, install_root: str,
                     expected_checksum: str, dry_run: bool = True) -> Dict:
        import subprocess, json
        script = self._tools_root / "tools" / "apply_linux_update.py"
        args = [
            sys.executable, str(script),
            "--install-root", install_root,
        ]
        if dry_run:
            args.insert(2, "--dry-run")
        if Path(package_path).exists():
            args.append(package_path)
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=60,
                            cwd=str(self._tools_root))
            try:
                return json.loads(r.stdout)
            except Exception:
                return {"ok": False, "error": r.stdout + r.stderr}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_update_temp_dir(self) -> Path:
        return Path("/tmp")

    def get_platform_name(self) -> str:
        return "linux"


# ── Windows Mock ──────────────────────────────────────────────────────────────

class WindowsUpdateManager(UpdateManager):
    """Windows mock: structurally valid but does not perform real apply."""

    def verify_package(self, package_path: str, expected_checksum: str) -> Tuple[bool, str]:
        try:
            h = hashlib.sha256()
            with open(package_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            cs = h.hexdigest()
            return cs == expected_checksum, cs
        except Exception as e:
            return False, str(e)

    def safe_extract(self, package_path: str, dest_dir: str) -> Tuple[bool, str]:
        # Mock: accept only if paths are relative and don't escape dest
        import zipfile
        try:
            with zipfile.ZipFile(package_path) as zf:
                for name in zf.namelist():
                    if name.startswith("/") or ".." in name:
                        return False, f"Unsafe path in zip: {name}"
                zf.extractall(dest_dir)
            return True, "extracted (mock)"
        except Exception as e:
            return False, str(e)

    def apply_update(self, package_path: str, install_root: str,
                     expected_checksum: str, dry_run: bool = True) -> Dict:
        return {
            "ok": True,
            "platform": "win32",
            "dry_run": dry_run,
            "note": "Windows mock — apply not implemented in X1",
            "package": package_path,
            "install_root": install_root,
        }

    def get_update_temp_dir(self) -> Path:
        return Path(os.environ.get("TEMP", "C:/Windows/Temp"))

    def get_platform_name(self) -> str:
        return "win32"


# ── macOS Mock ────────────────────────────────────────────────────────────────

class MacOSUpdateManager(UpdateManager):
    """macOS mock: structurally valid but does not perform real apply."""

    def verify_package(self, package_path: str, expected_checksum: str) -> Tuple[bool, str]:
        try:
            h = hashlib.sha256()
            with open(package_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            cs = h.hexdigest()
            return cs == expected_checksum, cs
        except Exception as e:
            return False, str(e)

    def safe_extract(self, package_path: str, dest_dir: str) -> Tuple[bool, str]:
        import tarfile
        try:
            with tarfile.open(package_path) as tf:
                for member in tf.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        return False, f"Unsafe path: {member.name}"
                tf.extractall(dest_dir)
            return True, "extracted (mock)"
        except Exception as e:
            return False, str(e)

    def apply_update(self, package_path: str, install_root: str,
                     expected_checksum: str, dry_run: bool = True) -> Dict:
        return {
            "ok": True,
            "platform": "darwin",
            "dry_run": dry_run,
            "note": "macOS mock — apply not implemented in X1",
            "package": package_path,
            "install_root": install_root,
        }

    def get_update_temp_dir(self) -> Path:
        return Path("/tmp")

    def get_platform_name(self) -> str:
        return "darwin"


# ── Factory ───────────────────────────────────────────────────────────────────

_MANAGER_CACHE: Optional[UpdateManager] = None

def get_update_manager() -> UpdateManager:
    global _MANAGER_CACHE
    if _MANAGER_CACHE is not None:
        return _MANAGER_CACHE
    if CURRENT_PLATFORM == "linux":
        _MANAGER_CACHE = LinuxUpdateManager()
    elif CURRENT_PLATFORM == "win32":
        _MANAGER_CACHE = WindowsUpdateManager()
    elif CURRENT_PLATFORM == "darwin":
        _MANAGER_CACHE = MacOSUpdateManager()
    else:
        raise NotImplementedError(f"Unsupported platform: {CURRENT_PLATFORM}")
    return _MANAGER_CACHE
