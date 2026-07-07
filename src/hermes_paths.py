#!/usr/bin/env python3
"""Hermes path helpers shared by Time Library integrations.

Hermes v0.14 can be redirected with HERMES_HOME. Its Windows native home is
under LocalAppData, while Linux, WSL, and macOS keep the historical ~/.hermes
layout. Profile config files may live under profiles/<name>/config.yaml; a
root config.yaml is treated as legacy/optional.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _platform_key() -> str:
    override = os.environ.get("MEMCORE_PLATFORM", "").strip().lower()
    if override in {"windows", "win32"}:
        return "win32"
    if override in {"linux", "darwin"}:
        return override
    if os.name == "nt" or sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def resolve_hermes_home() -> Path:
    override = os.environ.get("HERMES_HOME", "").strip()
    if override:
        return Path(override).expanduser()

    if _platform_key() == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "hermes"
        user_profile = os.environ.get("USERPROFILE", "").strip()
        if user_profile:
            return Path(user_profile) / "AppData" / "Local" / "hermes"
        return Path.home() / "AppData" / "Local" / "hermes"

    return Path.home() / ".hermes"


def hermes_state_db_path() -> Path:
    override = os.environ.get("MEMCORE_HERMES_STATE_DB_OVERRIDE", "").strip()
    if override:
        return Path(override).expanduser()
    return resolve_hermes_home() / "state.db"


def _append_unique(paths: list[Path], path: Path) -> None:
    if path not in paths:
        paths.append(path)


def _profile_name_candidates(active_profile: str | None = None) -> list[str]:
    names: list[str] = []
    for value in (
        active_profile,
        os.environ.get("HERMES_PROFILE"),
        os.environ.get("HERMES_ACTIVE_PROFILE"),
        os.environ.get("HERMES_DEFAULT_PROFILE"),
        "default",
    ):
        name = str(value or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def hermes_config_paths(
    hermes_home: str | Path | None = None,
    *,
    active_profile: str | None = None,
    existing_only: bool = True,
) -> list[Path]:
    home = Path(hermes_home).expanduser() if hermes_home else resolve_hermes_home()
    candidates: list[Path] = []
    profiles_dir = home / "profiles"

    for name in _profile_name_candidates(active_profile):
        _append_unique(candidates, profiles_dir / name / "config.yaml")

    if profiles_dir.is_dir():
        for path in sorted(profiles_dir.glob("*/config.yaml")):
            _append_unique(candidates, path)

    _append_unique(candidates, home / "config.yaml")

    if existing_only:
        return [path for path in candidates if path.exists()]
    return candidates


def hermes_primary_config_path(
    hermes_home: str | Path | None = None,
    *,
    active_profile: str | None = None,
) -> Path:
    existing = hermes_config_paths(
        hermes_home,
        active_profile=active_profile,
        existing_only=True,
    )
    if existing:
        return existing[0]

    home = Path(hermes_home).expanduser() if hermes_home else resolve_hermes_home()
    profiles_dir = home / "profiles"
    for name in _profile_name_candidates(active_profile):
        profile_dir = profiles_dir / name
        if profile_dir.exists() or profiles_dir.exists():
            return profile_dir / "config.yaml"
    return home / "config.yaml"
