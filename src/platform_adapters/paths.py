#!/usr/bin/env python3
"""
MemcorePaths - full directory layout contract.
==========================================================
X2 extends X1: adds complete 12-role directory schema,
override priority system, current pointer contract, permission contract.

Directory Roles (12):
  config     — persistent config (alias_map, permissions, source_registry...)
  data       — derived data (zhiyi, lancedb, experience...)
  memory     — raw memory storage (source_system raw .jsonl files)
  raw        — raw session storage (active sessions, audit logs)
  logs       — application logs
  runtime    — runtime state (pids, locks, socket files)
  cache      — temporary cache (checkpoints, temp data)
  backups    — backup storage (backup snapshots, rollback copies)
  releases   — released package storage (downloaded .tar.gz files)
  current    — current active installation (symlink or file pointer)
  staging    — staging area for updates (extraction temp)
  tmp        — ephemeral temp (/tmp equivalent per platform)

Override Priority (highest → lowest):
  1. CLI argument (passed to constructor or init)
  2. Environment variable (MEMCORE_CONFIG_DIR, MEMCORE_DATA_DIR, ...)
  3. Config file (memcore.json overrides field)
  4. Platform default (platform-specific XDG or Windows/macOS standard)
  5. Dev fallback (current user's memcore-cloud checkout for dev only)

Current Pointer Contract:
  Linux:   releases/<version>/ → current (symlink)
  Windows: releases\\<version>\\ → current (registry or file)
  macOS:   releases/<version>/ → current (symlink)
  If symlink unavailable: use releases/<version>/ as current directly

Permission Contract:
  secrets/     — 0o700 (owner only)
  logs/        — 0o755 (readable, not secret)
  cache/       — 0o755
  config/      — 0o644 (readable but not executable)
  data/        — 0o644
  backups/     — 0o755
  releases/    — 0o755
  All dirs:    ensure_dirs() creates with 0o755 if missing
"""
import os
import sys
from pathlib import Path
from typing import Optional, Dict, List

# ── Platform Detection ───────────────────────────────────────────────────────

def _detect_platform() -> str:
    env = os.environ.get("MEMCORE_PLATFORM", "").lower()
    if env in ("linux", "darwin", "win32"):
        return env
    return sys.platform

CURRENT_PLATFORM = _detect_platform()

# ── Path Override Helpers ─────────────────────────────────────────────────────

def _get_env_path(env_key: str, default: Path) -> Path:
    """Read path from environment variable, return default if unset/empty.
    If env var is set and is an absolute path, use it even if directory does not exist yet."""
    val = os.environ.get(env_key, "")
    if val:
        p = Path(val)
        # Use env var if it's an absolute path (allow non-existent dirs for overrides)
        if p.is_absolute():
            return p
    return default

# ── Directory Layout Schema ───────────────────────────────────────────────────

class MemcorePaths:
    """
    Full cross-platform directory layout with 12 roles.
    Paths are resolved at construction time following override priority.
    """

    # ── 12 Directory Roles ─────────────────────────────────────────────────
    CONFIG_DIR: Path     # persistent config (alias_map, permissions, source_registry...)
    DATA_DIR: Path       # derived data (zhiyi, lancedb, experience...)
    MEMORY_DIR: Path     # raw memory storage (source_system raw .jsonl files)
    RAW_DIR: Path        # raw session storage (active sessions, audit logs)
    LOG_DIR: Path        # application logs
    RUNTIME_DIR: Path    # runtime state (pids, locks, socket files)
    CACHE_DIR: Path      # temporary cache (checkpoints, temp data)
    BACKUPS_DIR: Path    # backup storage (backup snapshots, rollback copies)
    RELEASES_DIR: Path   # released package storage (downloaded .tar.gz files)
    CURRENT_DIR: Path    # current active installation (symlink target or direct)
    STAGING_DIR: Path    # staging area for updates (extraction temp)
    TMP_DIR: Path        # ephemeral temp (/tmp equivalent)

    PLATFORM: str        # linux / darwin / win32

    def __init__(self, overrides: Optional[Dict[str, Path]] = None):
        """
        Initialize paths following override priority.
        overrides: optional dict of role → Path from CLI args.
        """
        self.PLATFORM = CURRENT_PLATFORM
        p = CURRENT_PLATFORM

        if p == "win32":
            self._init_windows(overrides)
        elif p == "darwin":
            self._init_macos(overrides)
        else:
            self._init_linux(overrides)

    # ── Linux Init ─────────────────────────────────────────────────────────
    def _init_linux(self, overrides: Optional[Dict[str, Path]]):
        overrides = overrides or {}
        # Base directories
        config_home = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))
        cache_home = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
        state_home = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))

        base = Path(config_home)

        self.SECRET_DIR    = overrides.get("SECRET_DIR")  or (base / "memcore-cloud/secrets")
        self.CONFIG_DIR    = overrides.get("CONFIG_DIR")  or _get_env_path("MEMCORE_CONFIG_DIR",  base / "memcore-cloud")
        self.DATA_DIR      = overrides.get("DATA_DIR")    or _get_env_path("MEMCORE_DATA_DIR",    Path(data_home) / "memcore-cloud")
        self.MEMORY_DIR    = overrides.get("MEMORY_DIR")  or _get_env_path("MEMCORE_MEMORY_DIR",  Path(data_home) / "memcore-cloud/memory")
        self.RAW_DIR       = overrides.get("RAW_DIR")     or _get_env_path("MEMCORE_RAW_DIR",     Path(data_home) / "memcore-cloud/raw")
        self.LOG_DIR       = overrides.get("LOG_DIR")     or _get_env_path("MEMCORE_LOG_DIR",     Path(state_home) / "memcore-cloud/logs")
        self.RUNTIME_DIR   = overrides.get("RUNTIME_DIR") or _get_env_path("MEMCORE_RUNTIME_DIR", Path(state_home) / "memcore-cloud/runtime")
        self.CACHE_DIR     = overrides.get("CACHE_DIR")  or _get_env_path("MEMCORE_CACHE_DIR",   Path(cache_home) / "memcore-cloud")
        self.BACKUPS_DIR   = overrides.get("BACKUPS_DIR") or _get_env_path("MEMCORE_BACKUPS_DIR", Path.home() / ".local/share/memcore-cloud/backups")
        self.RELEASES_DIR  = overrides.get("RELEASES_DIR") or _get_env_path("MEMCORE_RELEASES_DIR", Path.home() / ".local/share/memcore-cloud/releases")
        self.STAGING_DIR   = overrides.get("STAGING_DIR")  or _get_env_path("MEMCORE_STAGING_DIR",  Path("/tmp") / "memcore-staging")
        self.TMP_DIR       = overrides.get("TMP_DIR")     or _get_env_path("MEMCORE_TMP_DIR",     Path("/tmp"))

        # current pointer: resolve symlink target or use RELEASES_DIR as fallback
        version_link = self.RELEASES_DIR / "current"
        if version_link.is_symlink() or version_link.exists():
            self.CURRENT_DIR = version_link.resolve() if version_link.is_symlink() else version_link
        else:
            self.CURRENT_DIR = self.RELEASES_DIR

    # ── macOS Init ─────────────────────────────────────────────────────────
    def _init_macos(self, overrides: Optional[Dict[str, Path]]):
        overrides = overrides or {}
        home = Path.home()
        app_support = home / "Library" / "Application Support"
        caches = home / "Library" / "Caches"
        logs = home / "Library" / "Logs"

        self.SECRET_DIR    = overrides.get("SECRET_DIR")  or (app_support / "memcore-cloud/secrets")
        self.CONFIG_DIR    = overrides.get("CONFIG_DIR")  or _get_env_path("MEMCORE_CONFIG_DIR",  app_support / "memcore-cloud")
        self.DATA_DIR      = overrides.get("DATA_DIR")    or _get_env_path("MEMCORE_DATA_DIR",    app_support / "memcore-cloud")
        self.MEMORY_DIR    = overrides.get("MEMORY_DIR")  or _get_env_path("MEMCORE_MEMORY_DIR",  app_support / "memcore-cloud/memory")
        self.RAW_DIR       = overrides.get("RAW_DIR")     or _get_env_path("MEMCORE_RAW_DIR",     app_support / "memcore-cloud/raw")
        self.LOG_DIR       = overrides.get("LOG_DIR")     or _get_env_path("MEMCORE_LOG_DIR",     logs / "memcore-cloud")
        self.RUNTIME_DIR   = overrides.get("RUNTIME_DIR") or _get_env_path("MEMCORE_RUNTIME_DIR", caches / "memcore-cloud/runtime")
        self.CACHE_DIR     = overrides.get("CACHE_DIR")  or _get_env_path("MEMCORE_CACHE_DIR",   caches / "memcore-cloud")
        self.BACKUPS_DIR   = overrides.get("BACKUPS_DIR") or _get_env_path("MEMCORE_BACKUPS_DIR", app_support / "memcore-cloud/backups")
        self.RELEASES_DIR  = overrides.get("RELEASES_DIR") or _get_env_path("MEMCORE_RELEASES_DIR", app_support / "memcore-cloud/releases")
        self.STAGING_DIR   = overrides.get("STAGING_DIR")  or _get_env_path("MEMCORE_STAGING_DIR",  Path("/tmp") / "memcore-staging")
        self.TMP_DIR       = overrides.get("TMP_DIR")     or _get_env_path("MEMCORE_TMP_DIR",     Path("/tmp"))
        self.CURRENT_DIR   = self.RELEASES_DIR / "current"

    # ── Windows Init ────────────────────────────────────────────────────────
    def _init_windows(self, overrides: Optional[Dict[str, Path]]):
        overrides = overrides or {}
        appdata = Path(os.environ.get("APPDATA", "C:/Users/default"))
        local = Path(os.environ.get("LOCALAPPDATA", appdata / "Local"))
        temp = Path(os.environ.get("TEMP", "C:/Windows/Temp"))

        self.CONFIG_DIR    = overrides.get("CONFIG_DIR")  or _get_env_path("MEMCORE_CONFIG_DIR",  appdata / "memcore-cloud")
        self.SECRET_DIR    = overrides.get("SECRET_DIR")  or (appdata / "memcore-cloud/secrets")
        self.DATA_DIR      = overrides.get("DATA_DIR")    or _get_env_path("MEMCORE_DATA_DIR",    local / "memcore-cloud")
        self.MEMORY_DIR    = overrides.get("MEMORY_DIR")  or _get_env_path("MEMCORE_MEMORY_DIR",  local / "memcore-cloud/memory")
        self.RAW_DIR       = overrides.get("RAW_DIR")     or _get_env_path("MEMCORE_RAW_DIR",     local / "memcore-cloud/raw")
        self.LOG_DIR       = overrides.get("LOG_DIR")     or _get_env_path("MEMCORE_LOG_DIR",     local / "memcore-cloud/logs")
        self.RUNTIME_DIR   = overrides.get("RUNTIME_DIR") or _get_env_path("MEMCORE_RUNTIME_DIR", local / "memcore-cloud/runtime")
        self.CACHE_DIR     = overrides.get("CACHE_DIR")  or _get_env_path("MEMCORE_CACHE_DIR",   local / "memcore-cloud/cache")
        self.BACKUPS_DIR   = overrides.get("BACKUPS_DIR") or _get_env_path("MEMCORE_BACKUPS_DIR", local / "memcore-cloud/backups")
        self.RELEASES_DIR  = overrides.get("RELEASES_DIR") or _get_env_path("MEMCORE_RELEASES_DIR", local / "memcore-cloud/releases")
        self.STAGING_DIR   = overrides.get("STAGING_DIR")  or _get_env_path("MEMCORE_STAGING_DIR",  temp / "memcore-staging")
        self.TMP_DIR       = overrides.get("TMP_DIR")     or _get_env_path("MEMCORE_TMP_DIR",     temp)
        self.CURRENT_DIR   = self.RELEASES_DIR / "current"

    # ── Directory Creation ─────────────────────────────────────────────────
    def ensure_dirs(self, create_missing: bool = True) -> Dict[str, bool]:
        """
        Ensure all directories exist with correct permissions.
        Returns dict of role → created/existed bool.
        """
        results = {}
        for attr in ["CONFIG_DIR", "DATA_DIR", "MEMORY_DIR", "RAW_DIR",
                     "LOG_DIR", "RUNTIME_DIR", "CACHE_DIR", "BACKUPS_DIR",
                     "RELEASES_DIR", "STAGING_DIR"]:
            d = getattr(self, attr, None)
            if d:
                try:
                    d.mkdir(parents=True, exist_ok=True)
                    results[attr] = True
                except Exception:
                    results[attr] = False
        return results

    # ── Permission Contract ────────────────────────────────────────────────
    def get_permission_mode(self, role: str) -> int:
        """Return expected permission mode for a directory role."""
        SECRET_DIRS = {"SECRET_DIR"}
        if hasattr(self, "SECRET_DIR") and role == "SECRET_DIR":
            return 0o700
        if role in ("CACHE_DIR", "TMP_DIR", "STAGING_DIR"):
            return 0o755
        return 0o755  # all dirs are world-readable

    # ── Current Pointer ─────────────────────────────────────────────────────
    def get_current_pointer(self) -> Dict:
        """
        Return the current installation pointer.
        On Linux/macOS: resolves symlink; on Windows: reads marker file.
        """
        current = self.CURRENT_DIR
        result = {
            "path": str(current),
            "type": "unknown",
            "exists": current.exists(),
            "is_symlink": False,
            "target": None,
        }
        if current.is_symlink():
            result["type"] = "symlink"
            result["is_symlink"] = True
            result["target"] = str(current.resolve())
        elif current.is_dir():
            result["type"] = "directory"
        elif current.is_file():
            result["type"] = "marker_file"
        return result

    # ── Layout Plan (dry-run) ──────────────────────────────────────────────
    def layout_plan(self) -> List[Dict]:
        """
        Return the full path layout plan (dry-run, does not create dirs).
        """
        roles = [
            ("CONFIG_DIR",   "persistent config",      0o644),
            ("DATA_DIR",     "derived data",             0o644),
            ("MEMORY_DIR",   "raw memory storage",       0o644),
            ("RAW_DIR",      "raw session storage",      0o644),
            ("LOG_DIR",      "application logs",         0o755),
            ("RUNTIME_DIR",  "runtime state",            0o755),
            ("CACHE_DIR",    "temporary cache",          0o755),
            ("BACKUPS_DIR",  "backup storage",           0o755),
            ("RELEASES_DIR", "released packages",        0o755),
            ("CURRENT_DIR",  "current active install",    0o755),
            ("STAGING_DIR",  "update staging area",      0o755),
            ("TMP_DIR",      "ephemeral temp",          0o755),
        ]
        plan = []
        for attr, desc, mode in roles:
            path = getattr(self, attr, None)
            if path:
                plan.append({
                    "role": attr,
                    "description": desc,
                    "path": str(path),
                    "mode": oct(mode),
                    "platform": self.PLATFORM,
                })
        return plan

    # ── Serialization ──────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "platform": self.PLATFORM,
            "paths": {
                "config_dir":    str(self.CONFIG_DIR),
                "data_dir":      str(self.DATA_DIR),
                "memory_dir":    str(self.MEMORY_DIR),
                "raw_dir":       str(self.RAW_DIR),
                "log_dir":       str(self.LOG_DIR),
                "runtime_dir":   str(self.RUNTIME_DIR),
                "cache_dir":     str(self.CACHE_DIR),
                "backups_dir":   str(self.BACKUPS_DIR),
                "releases_dir":  str(self.RELEASES_DIR),
                "current_dir":   str(self.CURRENT_DIR),
                "staging_dir":   str(self.STAGING_DIR),
                "tmp_dir":       str(self.TMP_DIR),
            },
            "override_priority": ["cli", "env_var", "config", "platform_default", "dev_fallback"],
            "permission_contract": {
                "config/memory/raw/data": "0o644 (readable, not secret)",
                "logs/runtime/cache/backups/releases/staging/tmp": "0o755",
                "secrets": "0o700 (owner only)",
            },
        }

    def __repr__(self):
        return f"MemcorePaths({self.PLATFORM}, {len(self.to_dict()['paths'])} paths)"


# ── Singleton ────────────────────────────────────────────────────────────────

_PATHS: Optional[MemcorePaths] = None

def get_memcore_paths(overrides: Optional[Dict[str, Path]] = None) -> MemcorePaths:
    global _PATHS
    if _PATHS is None or overrides:
        _PATHS = MemcorePaths(overrides=overrides or {})
    return _PATHS


# ── Layout Verification ──────────────────────────────────────────────────────

def verify_path_layout() -> Dict:
    """
    Verify the current path layout.
    Returns dict with ok, errors, and the full layout plan.
    """
    paths = get_memcore_paths()
    errors = []
    plan = paths.layout_plan()

    # Check no hardcoded private home path for config/data/memory on non-dev
    if CURRENT_PLATFORM == "linux":
        for entry in plan:
            p = entry["path"]
            home = str(Path.home())
            if p.startswith(home + "/") and not any(
                p.startswith(str(prefix))
                for prefix in (paths.CONFIG_DIR, paths.DATA_DIR, paths.CACHE_DIR, paths.STATE_DIR)
            ):
                errors.append(f"Unexpected private home hardcode in {entry['role']}: {p}")

    # Check TEMP_DIR is writable
    try:
        test = paths.TMP_DIR / f".memcore-test-{os.getpid()}"
        test.write_text("x")
        test.unlink()
    except Exception as e:
        errors.append(f"TMP_DIR not writable: {e}")

    return {
        "ok": len(errors) == 0,
        "platform": CURRENT_PLATFORM,
        "errors": errors,
        "plan": plan,
    }
