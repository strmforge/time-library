"""
runtime_context — cross-environment detection utility.

Detects the execution environment:
- windows_native: native Windows
- wsl_guest: WSL2/WSL1 guest (Windows host)
- linux_native: native Linux
- macos_native: native macOS
"""
import platform
import os
import re
from pathlib import Path
from typing import Literal

_RuntimeContext = Literal["windows_native", "wsl_guest", "linux_native", "macos_native", "unknown"]

def detect_runtime_context() -> _RuntimeContext:
    """Detect current runtime context."""
    system = platform.system().lower()

    # WSL detection
    is_wsl = False
    try:
        with open("/proc/version", "r") as f:
            content = f.read().lower()
            if "wsl" in content or "microsoft" in content:
                is_wsl = True
    except (FileNotFoundError, PermissionError):
        pass

    # Also check environment variable (WSL2 sets this)
    if os.environ.get("WSL_DISTRO_NAME") or is_wsl:
        return "wsl_guest"

    if system == "windows":
        return "windows_native"
    elif system == "linux":
        return "linux_native"
    elif system == "darwin":
        return "macos_native"
    else:
        return "unknown"


# Windows ↔ WSL path mapping
def wsl_to_windows_path(wsl_path: str) -> str:
    """Convert WSL path (e.g. /mnt/c/Users/...) to Windows path (C:\\Users\\...)."""
    wsl_path = os.path.expanduser(wsl_path)

    # /mnt/c/... -> C:\...
    m = re.match(r"^/mnt/([a-z])/(.*)", wsl_path)
    if m:
        drive = m.group(1).upper()
        rest = m.group(2).replace("/", "\\")
        return f"{drive}:\\{rest}"

    # /home/... mapped paths (WSL distro home)
    home = str(Path.home())
    if wsl_path.startswith(home):
        # Can't deterministically convert WSL home to Windows path without WSL env vars
        return wsl_path

    return wsl_path


def windows_to_wsl_path(windows_path: str) -> str:
    """Convert Windows path (e.g. C:\\Users\\...) to WSL path (/mnt/c/Users/...)."""
    windows_path = windows_path.strip()

    # C:\... -> /mnt/c/...
    m = re.match(r"^([A-Za-z]):\\(.+)", windows_path)
    if m:
        drive = m.group(1).lower()
        rest = m.group(2).replace("\\", "/")
        return f"/mnt/{drive}/{rest}"

    return windows_path


def wsl_windows_path_pair(wsl_home: str = None) -> dict:
    """Return WSL ↔ Windows path mapping pair for current environment.

    For WSL guest: maps WSL home to Windows user profile directory.
    For non-WSL: returns empty mapping.
    """
    ctx = detect_runtime_context()

    if ctx != "wsl_guest":
        return {
            "runtime_context": ctx,
            "is_wsl": False,
            "wsl_home": None,
            "windows_user_profile": None,
            "mappings": [],
        }

    if wsl_home is None:
        wsl_home = str(Path.home())

    # Try to get Windows user profile from WSL environment
    windows_user = os.environ.get("USERPROFILE") or os.environ.get("WIN_USERPROFILE")

    # Common WSL home to Windows mappings
    # WSL home is typically /home/<user>
    user_name = Path(wsl_home).name

    # Windows user profile path
    # In WSL2 with Docker-desktop, Windows paths can be accessed via /mnt/c/Users/<user>
    windows_user_profile = f"/mnt/c/Users/{user_name}"

    return {
        "runtime_context": ctx,
        "is_wsl": True,
        "wsl_home": wsl_home,
        "windows_user_profile": windows_user_profile,
        "mappings": [
            {
                "wsl": wsl_home,
                "windows": windows_user_profile,
                "description": "User home directory",
            },
            {
                "wsl": "/mnt/c",
                "windows": "C:\\",
                "description": "Windows system drive",
            },
        ],
    }


if __name__ == "__main__":
    ctx = detect_runtime_context()
    print(f"runtime_context: {ctx}")

    if ctx == "wsl_guest":
        info = wsl_windows_path_pair()
        import json
        print(json.dumps(info, indent=2, default=str))

    # Test path conversions
    print("\nPath conversion tests:")
    print(f"  /mnt/c/Users/test -> {wsl_to_windows_path('/mnt/c/Users/test')}")
    windows_example = "C:\\Users\\test"
    print(f"  {windows_example} -> {windows_to_wsl_path(windows_example)}")
