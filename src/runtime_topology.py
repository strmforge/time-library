#!/usr/bin/env python3
"""Runtime topology detection for Time Library.

Provides runtime_mode detection, Hermes CLI resolution, and
topology-aware evidence source declarations.

Runtime Modes:
- linux_native: All services on same Linux host (local)
- windows_wsl: Hermes in WSL, memcore not in WSL all-in-one target
- wsl_all_in_one: memcore + Hermes in WSL, OpenClaw as Windows native gateway
- windows_native_future: Future Windows native install (not current)
- mixed_linux_windows: Linux runs Time Library, Windows runs OpenClaw/WSL Hermes
- auto: Auto-detect
- unknown: Cannot determine
"""
from __future__ import annotations
import os
import platform
import shutil
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional


class RuntimeMode(str, Enum):
    LINUX_NATIVE = "linux_native"
    WINDOWS_WSL = "windows_wsl"
    WSL_ALL_IN_ONE = "wsl_all_in_one"
    WINDOWS_NATIVE_FUTURE = "windows_native_future"
    MIXED_LINUX_WINDOWS = "mixed_linux_windows"
    AUTO = "auto"
    UNKNOWN = "unknown"


# Candidate Hermes CLI paths, ordered by priority
_HERMES_CANDIDATES: list[str] = [
    # shutil.which is tried first via resolve_hermes_cli()
    str(Path.home() / ".local" / "bin" / "hermes"),
    str(Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "hermes"),
]

# Evidence source declarations
SOURCE_OF_TRUTH_LOCAL_NODE = "local configured Time Library root"
SOURCE_OF_TRUTH_Y_DRIVE = "mapped source root"
EXCLUDED_EVIDENCE_OLD_WINDOWS = (
    "old Windows native memcore-cloud from prior incomplete install "
    "- excluded from current implementation evidence"
)
OUT_OF_SCOPE_CLOUDFLARE = "Cloudflare Tunnel - out of scope"
OUT_OF_SCOPE_RELEASE = "release_ready = false"
OUT_OF_SCOPE_PRODUCTION = "production_ready = false"


def _running_in_wsl() -> bool:
    """Detect if running inside WSL."""
    if platform.system() != "Linux":
        return False
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower() or "wsl" in f.read().lower()
    except (FileNotFoundError, OSError):
        return False


def _has_wsl_on_windows() -> bool:
    """Detect if running on Windows with WSL available."""
    if platform.system() != "Windows":
        return False
    try:
        r = subprocess.run(
            ["wsl", "echo", "wsl_available"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        return r.returncode == 0 and "wsl_available" in (r.stdout or "")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _hostname_is_local_node() -> bool:
    return platform.node().lower().startswith("local")


def _cwd_is_y_drive() -> bool:
    try:
        return Path.cwd().drive.upper() == "Y:"
    except OSError:
        return False


def _is_linux_style_path(path: str) -> bool:
    return path.startswith("/")


def detect_runtime_mode(override: Optional[str] = None) -> RuntimeMode:
    """Detect current runtime mode.

    Args:
        override: Explicit mode string. If provided, used directly.

    Returns:
        RuntimeMode enum value.
    """
    if override and override != "auto":
        try:
            return RuntimeMode(override)
        except ValueError:
            return RuntimeMode.UNKNOWN

    # Environment override (MEMCORE_RUNTIME_MODE)
    env_mode = os.environ.get("MEMCORE_RUNTIME_MODE")
    if env_mode and env_mode != "auto":
        try:
            return RuntimeMode(env_mode)
        except ValueError:
            return RuntimeMode.UNKNOWN

    # Linux native (local)
    if platform.system() == "Linux" and not _running_in_wsl():
        return RuntimeMode.LINUX_NATIVE

    # Mixed local + Windows: Y: is the SMB-mapped authoritative memcore checkout.
    if platform.system() == "Windows" and _cwd_is_y_drive():
        return RuntimeMode.MIXED_LINUX_WINDOWS

    # Mixed local + Windows: Windows host + WSL Hermes + likely remote memcore.
    if platform.system() == "Windows" and _has_wsl_on_windows():
        return RuntimeMode.MIXED_LINUX_WINDOWS

    # WSL all-in-one: memcore + Hermes in WSL, OpenClaw Windows native gateway
    if _running_in_wsl() and os.environ.get("MEMCORE_RUNTIME_MODE") == "wsl_all_in_one":
        return RuntimeMode.WSL_ALL_IN_ONE

    # Windows with WSL (Hermes in WSL, memcore elsewhere)
    if _running_in_wsl():
        return RuntimeMode.WINDOWS_WSL

    # Windows without WSL - could be future native
    if platform.system() == "Windows":
        return RuntimeMode.WINDOWS_NATIVE_FUTURE

    return RuntimeMode.UNKNOWN


def resolve_hermes_cli(
    runtime_mode: RuntimeMode = RuntimeMode.AUTO,
    explicit_path: Optional[str] = None,
) -> Optional[str]:
    """Resolve Hermes CLI path.

    Resolution order:
    1. explicit_path (--hermes-cli argument)
    2. MEMCORE_HERMES_CLI environment variable
    3. shutil.which("hermes") (cross-platform PATH lookup)
    4. Platform-specific candidates

    Args:
        runtime_mode: Current runtime mode for platform-specific resolution.
        explicit_path: Explicit CLI path from user argument.

    Returns:
        Absolute path to hermes CLI, or None if not found.
    """
    # 1. Explicit path from arg
    if explicit_path:
        if os.path.exists(explicit_path):
            return os.path.abspath(explicit_path)
        return None

    # 2. Environment variable
    env_path = os.environ.get("MEMCORE_HERMES_CLI")
    if env_path:
        if os.path.exists(env_path):
            return os.path.abspath(env_path)
        return None

    # 3. shutil.which (cross-platform PATH lookup)
    which_path = shutil.which("hermes")
    if which_path:
        return os.path.abspath(which_path)

    # 4. Platform candidates
    for path in _HERMES_CANDIDATES:
        if os.path.exists(path):
            return path

    # 5. WSL-specific: try to find Hermes via wsl.exe
    if runtime_mode == RuntimeMode.MIXED_LINUX_WINDOWS and platform.system() == "Windows":
        try:
            r = subprocess.run(
                ["wsl", "which", "hermes"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Try common WSL paths
        wsl_home = subprocess.run(
            ["wsl", "echo", "$HOME"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        ).stdout.strip()
        if wsl_home:
            for candidate in [
                f"{wsl_home}/.local/bin/hermes",
                f"{wsl_home}/.hermes/hermes-agent/venv/bin/hermes",
            ]:
                r = subprocess.run(
                    ["wsl", "test", "-f", candidate, "&&", "echo", "exists"],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                )
                if r.returncode == 0 and "exists" in (r.stdout or ""):
                    return candidate

    return None


def describe_runtime_topology() -> dict:
    """Generate a runtime topology report dict.

    Returns a dict with mode, hermes availability, and evidence source
    declarations suitable for inclusion in probe/audit reports.
    """
    mode = detect_runtime_mode()
    hermes_cli = resolve_hermes_cli(mode)

    report = {
        "runtime_mode": mode.value,
        "runtime_mode_via": "auto_detect",
        "platform": platform.system(),
        "hostname": platform.node(),
        "in_wsl": _running_in_wsl(),
        "has_wsl_on_windows": _has_wsl_on_windows(),
        "hermes_cli_available": hermes_cli is not None,
        "hermes_cli_path": hermes_cli or "",
        "hermes_cli_resolution": (
            "explicit" if hermes_cli and os.environ.get("MEMCORE_HERMES_CLI") else
            "which_path" if hermes_cli and shutil.which("hermes") else
            "wsl_path" if hermes_cli and platform.system() == "Windows" and _is_linux_style_path(hermes_cli) else
            "candidate_list" if hermes_cli else
            "not_found"
        ),
        "current_authoritative_memcore": (
            SOURCE_OF_TRUTH_LOCAL_NODE
            if _hostname_is_local_node() or platform.system() == "Linux"
            else SOURCE_OF_TRUTH_Y_DRIVE
        ),
        "old_windows_native_memcore_excluded_from_evidence": True,
        "cloudflare_tunnel_out_of_scope": True,
        "windows_native_future_not_current": (
            mode != RuntimeMode.WINDOWS_NATIVE_FUTURE
        ),
        "memcore_runtime": (
            "wsl" if mode == RuntimeMode.WSL_ALL_IN_ONE else
            "linux_native" if mode == RuntimeMode.LINUX_NATIVE else
            "windows_native_future" if mode == RuntimeMode.WINDOWS_NATIVE_FUTURE else
            "remote_linux" if mode == RuntimeMode.MIXED_LINUX_WINDOWS else
            "wsl_detected" if mode == RuntimeMode.WINDOWS_WSL else
            "unknown"
        ),
        "hermes_runtime": (
            "wsl" if mode in (RuntimeMode.WSL_ALL_IN_ONE, RuntimeMode.WINDOWS_WSL) else
            "linux_native" if mode == RuntimeMode.LINUX_NATIVE else
            "wsl_detected" if mode == RuntimeMode.MIXED_LINUX_WINDOWS else
            "unknown"
        ),
        "openclaw_runtime": (
            "windows_native_gateway" if mode == RuntimeMode.WSL_ALL_IN_ONE else
            "windows_native" if mode in (RuntimeMode.WINDOWS_WSL, RuntimeMode.WINDOWS_NATIVE_FUTURE) else
            "linux_native" if mode == RuntimeMode.LINUX_NATIVE else
            "remote_linux" if mode == RuntimeMode.MIXED_LINUX_WINDOWS else
            "unknown"
        ),
        "production_ready": False,
        "release_ready": False,
        "installer_ready": False,
    }

    return report
