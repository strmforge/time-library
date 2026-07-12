#!/usr/bin/env python3
"""
RuntimeProfileProvider - Cross-platform runtime profile contract.
================================================================================
Defines the interface for probing runtime instances of memcore-cloud / OpenClaw
across Linux / Windows / macOS.

Linux: real implementation via tools/runtime_profile.py
Windows/macOS: explicit unavailable result; native discovery lives elsewhere

Interface contract:
  - get_runtime_profile() -> dict
  - get_memcore_instances() -> list[dict]
  - get_openclaw_instances() -> list[dict]
  - get_hermes_instances() -> list[dict]
  - is_real_implementation() -> bool
"""
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional, List, Dict

CURRENT_PLATFORM = sys.platform

# ── Provider Interface ─────────────────────────────────────────────────────────

class RuntimeProfileProvider:
    """
    Abstract interface for runtime instance discovery.
    All methods return dicts conforming to the same schema across platforms.
    """

    def get_runtime_profile(self) -> Dict:
        """Full runtime profile including all layers."""
        raise NotImplementedError

    def get_memcore_instances(self) -> List[Dict]:
        """Find all memcore-cloud installations."""
        raise NotImplementedError

    def get_openclaw_instances(self) -> List[Dict]:
        """Find all OpenClaw installations."""
        raise NotImplementedError

    def get_hermes_instances(self) -> List[Dict]:
        """Find all Hermes installations."""
        raise NotImplementedError

    def is_real_implementation(self) -> bool:
        """True if this provider performs a real platform probe."""
        raise NotImplementedError

    def get_platform_name(self) -> str:
        return CURRENT_PLATFORM


# ── Linux Real Implementation ──────────────────────────────────────────────────

class LinuxRuntimeProfileProvider(RuntimeProfileProvider):
    """
    Linux real implementation using tools/runtime_profile.py.
    """
    _profile_cache: Optional[Dict] = None

    def get_runtime_profile(self) -> Dict:
        if self._profile_cache is not None:
            return self._profile_cache
        try:
            r = subprocess.run(
                [sys.executable, str(Path(__file__).parent.parent.parent / "tools" / "runtime_profile.py")],
                capture_output=True, text=True, timeout=15, cwd=str(Path(__file__).parent.parent.parent)
            )
            if r.returncode == 0:
                import json
                self._profile_cache = json.loads(r.stdout)
        except Exception:
            pass
        if self._profile_cache is None:
            self._profile_cache = {"status": "unavailable", "platform": "linux"}
        return self._profile_cache

    def get_memcore_instances(self) -> List[Dict]:
        p = self.get_runtime_profile()
        return p.get("memcore_cloud", {}).get("instances", [])

    def get_openclaw_instances(self) -> List[Dict]:
        p = self.get_runtime_profile()
        return p.get("openclaw", {}).get("instances", [])

    def get_hermes_instances(self) -> List[Dict]:
        p = self.get_runtime_profile()
        return p.get("hermes", {}).get("instances", [])

    def is_real_implementation(self) -> bool:
        return True


# ── Windows unavailable legacy provider ──────────────────────────────────────

class WindowsRuntimeProfileProvider(RuntimeProfileProvider):
    """Legacy provider that fails explicitly instead of fabricating a profile."""

    def get_runtime_profile(self) -> Dict:
        return {
            "status": "unavailable",
            "platform": "win32",
            "note": "Use the native platform discovery path for Windows runtime data.",
            "memcore_cloud": {
                "status": "unknown",
                "instances": [],
                "install_root": None,
            },
            "openclaw": {
                "status": "unknown",
                "instances": [],
                "install_root": None,
            },
            "hermes": {
                "status": "experimental",
                "version": None,
                "instances": [],
            },
        }

    def get_memcore_instances(self) -> List[Dict]:
        return []

    def get_openclaw_instances(self) -> List[Dict]:
        return []

    def get_hermes_instances(self) -> List[Dict]:
        return []

    def is_real_implementation(self) -> bool:
        return False


# ── macOS unavailable legacy provider ─────────────────────────────────────────

class MacOSRuntimeProfileProvider(RuntimeProfileProvider):
    """Legacy provider that fails explicitly instead of fabricating a profile."""

    def get_runtime_profile(self) -> Dict:
        return {
            "status": "unavailable",
            "platform": "darwin",
            "note": "Use the native platform discovery path for macOS runtime data.",
            "memcore_cloud": {
                "status": "unknown",
                "instances": [],
                "install_root": None,
            },
            "openclaw": {
                "status": "unknown",
                "instances": [],
                "install_root": None,
            },
            "hermes": {
                "status": "experimental",
                "version": None,
                "instances": [],
            },
        }

    def get_memcore_instances(self) -> List[Dict]:
        return []

    def get_openclaw_instances(self) -> List[Dict]:
        return []

    def get_hermes_instances(self) -> List[Dict]:
        return []

    def is_real_implementation(self) -> bool:
        return False


# ── Factory ───────────────────────────────────────────────────────────────────

_PROVIDER_CACHE: Optional[RuntimeProfileProvider] = None

def get_runtime_profile_provider() -> RuntimeProfileProvider:
    global _PROVIDER_CACHE
    if _PROVIDER_CACHE is not None:
        return _PROVIDER_CACHE

    if CURRENT_PLATFORM == "linux":
        _PROVIDER_CACHE = LinuxRuntimeProfileProvider()
    elif CURRENT_PLATFORM == "win32":
        _PROVIDER_CACHE = WindowsRuntimeProfileProvider()
    elif CURRENT_PLATFORM == "darwin":
        _PROVIDER_CACHE = MacOSRuntimeProfileProvider()
    else:
        raise NotImplementedError(f"Unsupported platform: {CURRENT_PLATFORM}")
    return _PROVIDER_CACHE
