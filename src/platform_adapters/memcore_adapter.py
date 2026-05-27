#!/usr/bin/env python3
"""
P9-System-X1: MemcoreAdapter — Unified Cross-Platform Adapter
==============================================================
Aggregates all platform contracts into a single entry point:
  - MemcorePaths
  - RuntimeProfileProvider
  - SecretStore
  - UpdateManager

Usage:
    from platform_adapters.memcore_adapter import get_adapter
    adapter = get_adapter()
    profile = adapter.get_runtime_profile()
    paths = adapter.get_paths()
    secrets = adapter.get_secret_store()
    updater = adapter.get_update_manager()
"""
from .paths import MemcorePaths, get_memcore_paths, CURRENT_PLATFORM
from .runtime_profile_provider import (
    RuntimeProfileProvider,
    get_runtime_profile_provider,
    LinuxRuntimeProfileProvider,
    WindowsRuntimeProfileProvider,
    MacOSRuntimeProfileProvider,
)
from .secret_store import SecretStore, get_secret_store
from .update_manager import UpdateManager, get_update_manager


class MemcoreAdapter:
    """
    Unified cross-platform adapter.
    Single entry point for all platform-specific operations.
    """

    def __init__(self):
        self._paths: MemcorePaths = get_memcore_paths()
        self._provider = get_runtime_profile_provider()
        self._secrets = get_secret_store()
        self._updater = get_update_manager()

    # ── Paths ─────────────────────────────────────────────────────────────────

    @property
    def paths(self) -> MemcorePaths:
        return self._paths

    def get_paths(self) -> MemcorePaths:
        return self._paths

    # ── Runtime Profile ────────────────────────────────────────────────────────

    def get_runtime_profile(self) -> dict:
        return self._provider.get_runtime_profile()

    def get_memcore_instances(self) -> list:
        return self._provider.get_memcore_instances()

    def get_openclaw_instances(self) -> list:
        return self._provider.get_openclaw_instances()

    def get_hermes_instances(self) -> list:
        return self._provider.get_hermes_instances()

    def is_real_implementation(self) -> bool:
        return self._provider.is_real_implementation()

    # ── Secrets ──────────────────────────────────────────────────────────────

    def get_secret_store(self) -> SecretStore:
        return self._secrets

    # ── Updates ───────────────────────────────────────────────────────────────

    def get_update_manager(self) -> UpdateManager:
        return self._updater

    # ── Info ──────────────────────────────────────────────────────────────────

    def get_platform(self) -> str:
        return CURRENT_PLATFORM

    def is_linux(self) -> bool:
        return CURRENT_PLATFORM == "linux"

    def is_windows(self) -> bool:
        return CURRENT_PLATFORM == "win32"

    def is_macos(self) -> bool:
        return CURRENT_PLATFORM == "darwin"

    def __repr__(self):
        return f"MemcoreAdapter(platform={CURRENT_PLATFORM}, real={self.is_real_implementation()})"


_ADAPTER_CACHE = None

def get_adapter() -> MemcoreAdapter:
    global _ADAPTER_CACHE
    if _ADAPTER_CACHE is None:
        _ADAPTER_CACHE = MemcoreAdapter()
    return _ADAPTER_CACHE
