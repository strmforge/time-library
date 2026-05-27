"""
src/sandbox_policy.py
Sandbox Policy Guards
"""
from pathlib import Path
from typing import Tuple

SANDBOX_MARKER = ".memcore-sandbox-root"
SANDBOX_APPLY_MARKER = ".memcore-apply-sandbox-root"
PROTECTED_ROOTS = {
    "/opt/memcore-cloud",
    "/usr/local/memcore-cloud",
    str(Path.home() / "memcore-cloud"),
}
PROTECTED_SUBDIRS = {"config", "data", "logs", "memory", "output", "schemas"}


def is_protected_path(path: str) -> bool:
    """Check if path is a protected production root."""
    p = Path(path).resolve()
    for prot in PROTECTED_ROOTS:
        prot_path = Path(prot).resolve()
        if p == prot_path or p.is_relative_to(prot_path):
            return True
    return False


def check_sandbox_root(sandbox_root: str) -> Tuple[bool, str]:
    """Verify sandbox root is valid and not a protected path."""
    sr = Path(sandbox_root).resolve()

    # Check marker
    marker = sr / SANDBOX_MARKER
    if not marker.exists():
        return False, f"sandbox marker missing: {marker}"

    # Check not protected
    if is_protected_path(sandbox_root):
        return False, f"BLOCKED: sandbox_root is a protected production path: {sandbox_root}"

    # Check not overlapping protected roots
    for prot in PROTECTED_ROOTS:
        prot_p = Path(prot).resolve()
        try:
            sr.relative_to(prot_p)
            return False, f"BLOCKED: sandbox_root is inside protected path: {prot}"
        except ValueError:
            pass

    return True, "sandbox root valid"


def check_protected_dirs_overlap(sandbox_root: str, install_root: str) -> Tuple[bool, str]:
    """Check if sandbox install would overlap protected dirs."""
    sr = Path(sandbox_root).resolve()
    ir = Path(install_root).resolve()
    try:
        ir.relative_to(sr)
        return True, "install_root inside sandbox_root: OK"
    except ValueError:
        pass
    if is_protected_path(install_root):
        return False, f"BLOCKED: install_root is protected: {install_root}"
    return True, "install_root not protected"


def verify_sandbox_marker_dir(sandbox_root: str) -> Tuple[bool, str]:
    """Verify the exact sandbox marker file exists."""
    marker_path = Path(sandbox_root) / SANDBOX_MARKER
    if not marker_path.exists():
        return False, f"marker not found: {marker_path}"
    if not marker_path.is_file():
        return False, f"marker is not a file: {marker_path}"
    return True, "marker verified"


def get_sandbox_marker_version(sandbox_root: str) -> str:
    """Read version from sandbox marker if present."""
    marker_path = Path(sandbox_root) / SANDBOX_MARKER
    if marker_path.exists():
        return marker_path.read_text().strip()
    return ""
