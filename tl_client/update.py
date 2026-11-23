"""The client keeps itself at the version its server hands out.

The server serves the client package, so the server is the authority: when the
version it advertises differs from this one, the running client fetches the
package from the server, checks it, writes the new files over its own and starts
again. Only a client installed from the package does this; a client running from
a source checkout (a developer's) is never overwritten.
"""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path

from . import CLIENT_VERSION

PACKAGE_PATH = "/client/time-library-client.zip"


def installed_app_dir() -> Path | None:
    """The package's app/ folder, when this client was installed from the package."""
    app = Path(__file__).resolve().parent.parent
    if app.name == "app" and (app.parent / "tl.py").is_file():
        return app
    return None


def packaged_version(archive: zipfile.ZipFile) -> str:
    text = archive.read("app/tl_client/__init__.py").decode("utf-8")
    match = re.search(r'^CLIENT_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def apply_package(data: bytes, app: Path, expected_version: str) -> None:
    """Check the package, then write it over app/ (file by file: no folder renames,
    which a running process's working folder would block on Windows)."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    if archive.testzip() is not None:
        raise ValueError("the package is damaged")
    names = archive.namelist()
    if "app/tl_client/__main__.py" not in names or packaged_version(archive) != expected_version:
        raise ValueError("the package is not the advertised client version")
    staging = app.parent / "app.update"
    shutil.rmtree(staging, ignore_errors=True)
    for name in names:
        if name.startswith("app/") and not name.endswith("/"):
            archive.extract(name, staging)
    fresh = staging / "app" / "tl_client"
    current = app / "tl_client"
    wanted = {path.relative_to(fresh) for path in fresh.rglob("*") if path.is_file()}
    for relative in sorted(wanted):
        target = current / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fresh / relative, target)
    for path in sorted(current.rglob("*"), reverse=True):
        relative = path.relative_to(current)
        if "__pycache__" in relative.parts:
            continue
        if path.is_file() and relative not in wanted:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if "tl.py" in names:
        (app.parent / "tl.py").write_bytes(archive.read("tl.py"))
    shutil.rmtree(staging, ignore_errors=True)


def update_if_needed(api, advertised: str | None, app: Path | None = None) -> bool:
    """Returns True when new files were written (the caller should start again)."""
    app = app or installed_app_dir()
    if app is None or not advertised or advertised == CLIENT_VERSION:
        return False
    apply_package(api.download(PACKAGE_PATH), app, advertised)
    return True
