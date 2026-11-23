"""The client's own Python: the same version on every computer, inside the client's folder.

A computer installed from the server's bundle already has it. One installed
earlier, on a Python it happened to have, gets it with `tl.py runtime install`:
the bundle is fetched from the server, only its python/ folder is taken, the
new interpreter is tried, and the background service is registered again to
run on it. Nothing outside the client's folder changes; the Python the computer
already had is left as it was (agents' MCP and hook commands that name it keep
working: the client still runs on 3.9 and later).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

DOWNLOAD_TIMEOUT = 300
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def platform_key() -> str | None:
    """Which bundle this computer takes, as the server names them."""
    system, machine = platform.system(), platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Darwin":
        return "macos-arm64" if arm else "macos-x86_64"
    if system == "Windows":
        return "windows-arm64" if arm else "windows-amd64"
    if system == "Linux":
        return "linux-aarch64" if arm else ("linux-x86_64" if machine in ("x86_64", "amd64") else None)
    return None


def client_root() -> Path:
    """The folder holding tl.py, app/ and (once installed) python/."""
    return Path(__file__).resolve().parent.parent.parent


def bundled_python(root: Path | None = None) -> Path:
    root = root or client_root()
    return root / "python" / ("python.exe" if platform.system() == "Windows" else "bin/python3")


def running_bundled() -> bool:
    try:
        return Path(sys.executable).resolve().is_relative_to(client_root() / "python")
    except (OSError, ValueError, AttributeError):
        return str(Path(sys.executable).resolve()).startswith(str(client_root() / "python"))


def _safe(member: tarfile.TarInfo) -> bool:
    parts = Path(member.name).parts
    return bool(parts) and parts[0] == "python" and ".." not in parts and not Path(member.name).is_absolute()


def install(server_url: str, root: Path | None = None) -> Path:
    """Fetch this computer's bundle and put its python/ in the client's folder. Returns the interpreter."""
    root = root or client_root()
    key = platform_key()
    if key is None:
        raise RuntimeError(f"no bundle for this kind of computer ({platform.system()} {platform.machine()})")
    with tempfile.TemporaryDirectory(dir=root) as work:
        archive = Path(work) / "bundle.tar.gz"
        with _DIRECT.open(f"{server_url.rstrip('/')}/client/bundle/{key}.tar.gz", timeout=DOWNLOAD_TIMEOUT) as response, \
                archive.open("wb") as out:
            shutil.copyfileobj(response, out, 1 << 20)
        staged = Path(work) / "staged"
        with tarfile.open(archive, "r:gz") as bundle:
            members = [member for member in bundle.getmembers() if _safe(member)]
            if not members:
                raise RuntimeError("the bundle holds no python/ folder")
            bundle.extractall(staged, members=members)
        interpreter = bundled_python(staged)
        tried = subprocess.run([str(interpreter), "-c", "import json, sqlite3, ssl, zipfile, sys; print(sys.version_info[:2])"],
                               capture_output=True, text=True, timeout=60)
        if tried.returncode != 0:
            raise RuntimeError(f"the new Python does not start: {tried.stderr.strip()[-300:]}")
        target = root / "python"
        if target.exists():
            retired = root / "python.old"
            shutil.rmtree(retired, ignore_errors=True)
            target.rename(retired)  # fails while something runs from it: the old one stays, nothing breaks
            shutil.rmtree(retired, ignore_errors=True)
        (staged / "python").rename(target)
    return bundled_python(root)
