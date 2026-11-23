"""The client together with its own Python, one archive per kind of computer.

Every computer runs the client on the same Python, installed inside the
client's folder (nothing system-wide, no PATH change, no administrator), so a
computer without Python can be connected with the tools it already has (curl
and tar; Windows 10 and later have both).

The server does not carry the runtimes in its image. The first time a kind of
computer asks, it fetches the official build (python.org for Windows,
python-build-standalone for macOS and Linux) from the first source that
answers, checks it against the checksum pinned here, and keeps it in the data
folder. A server that can fetch nothing answers 503, and the install guide
falls back to a Python already on the computer.
"""

from __future__ import annotations

import hashlib
import io
import logging
import tarfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import client_package

log = logging.getLogger("tl_server.runtimes")

PYTHON_VERSION = "3.14.10"
_PBS = "20261110"
_PBS_NAME = "cpython-3.14.10%2B20261110-{target}-install_only_stripped.tar.gz"
_PBS_SOURCES = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/" + _PBS + "/",
    "https://registry.npmmirror.com/-/binary/python-build-standalone/" + _PBS + "/",
)
_EMBED_SOURCES = (
    "https://www.python.org/ftp/python/" + PYTHON_VERSION + "/",
    "https://registry.npmmirror.com/-/binary/python/" + PYTHON_VERSION + "/",
)


def _pbs(target: str, sha256: str) -> dict:
    name = _PBS_NAME.format(target=target)
    return {"name": name.replace("%2B", "+"), "urls": [base + name for base in _PBS_SOURCES], "sha256": sha256, "kind": "tar"}


def _embed(arch: str, sha256: str) -> dict:
    name = f"python-{PYTHON_VERSION}-embed-{arch}.zip"
    return {"name": name, "urls": [base + name for base in _EMBED_SOURCES], "sha256": sha256, "kind": "zip"}


RUNTIMES: dict[str, dict] = {
    "macos-arm64": _pbs("aarch64-apple-darwin", "f15ec3d15460dd66c2eb88639b152cd9040e7d1ece11e38bf89e8f53f0171e02"),
    "macos-x86_64": _pbs("x86_64-apple-darwin", "85f8e54798e8e6aa58d2253f013d815c5616343cc0d15cbea882fca78bdfeae2"),
    "linux-x86_64": _pbs("x86_64-unknown-linux-gnu", "c2ff2e97422f5d3896a16e0317fd212ba977bbf2688d93a6f7a03d817506bd30"),
    "linux-aarch64": _pbs("aarch64-unknown-linux-gnu", "38fd50f07170adc29d481913d1c30b17ecb538fbe290315fe1f83d84fdd5b694"),
    "windows-amd64": _embed("amd64", "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159"),
    "windows-arm64": _embed("arm64", "bbe116bb1248820359cbf25127ac5c7794ea161869d83686cfbc9a45203ff836"),
}
FETCH_TIMEOUT = 20  # per read; a source that does not answer is skipped for the next
RETRY_AFTER = 600  # seconds before a failed fetch is tried again
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Runtimes:
    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir) / "runtimes"
        self._locks = {platform: threading.Lock() for platform in RUNTIMES}
        self._failed: dict[str, float] = {}

    def runtime(self, platform: str) -> Path | None:
        """The official Python for this kind of computer, fetched once and checked; None if it can't be had."""
        entry = RUNTIMES[platform]
        target = self._dir / entry["name"]
        if target.exists():
            return target
        with self._locks[platform]:
            if target.exists():
                return target
            if time.monotonic() - self._failed.get(platform, -RETRY_AFTER) < RETRY_AFTER:
                return None
            self._dir.mkdir(parents=True, exist_ok=True)
            for url in entry["urls"]:
                partial = target.with_suffix(target.suffix + ".part")
                try:
                    digest = hashlib.sha256()
                    with _DIRECT.open(url, timeout=FETCH_TIMEOUT) as response, partial.open("wb") as out:
                        while True:
                            chunk = response.read(1 << 20)
                            if not chunk:
                                break
                            digest.update(chunk)
                            out.write(chunk)
                    if digest.hexdigest() != entry["sha256"]:
                        log.warning("python for %s from %s does not match its checksum; not used", platform, url)
                        partial.unlink(missing_ok=True)
                        continue
                    partial.replace(target)
                    log.info("python %s for %s fetched from %s", PYTHON_VERSION, platform, url)
                    return target
                except OSError as error:
                    log.info("python for %s not fetched from %s: %s", platform, url, error)
                    partial.unlink(missing_ok=True)
            self._failed[platform] = time.monotonic()
            return None

    def bundle(self, platform: str) -> Path | None:
        """client + its Python, as one .tar.gz for this kind of computer (kept per client version)."""
        runtime = self.runtime(platform)
        if runtime is None:
            return None
        version = client_package.client_version() or "dev"
        target = self._dir / f"time-library-client-{version}-{platform}.tar.gz"
        if target.exists():
            return target
        with self._locks[platform]:
            if target.exists():
                return target
            partial = target.with_suffix(".part")
            with tarfile.open(partial, "w:gz", compresslevel=6) as out:
                _add_runtime(out, runtime, RUNTIMES[platform]["kind"])
                with zipfile.ZipFile(io.BytesIO(client_package.package())) as package:
                    for info in package.infolist():
                        if not info.is_dir():
                            _add_bytes(out, info.filename, package.read(info), 0o755 if info.filename == "tl.py" else 0o644)
            partial.replace(target)
            for old in self._dir.glob(f"time-library-client-*-{platform}.tar.gz"):
                if old != target:
                    old.unlink(missing_ok=True)  # bundles of older client versions
            return target


def _add_bytes(out: tarfile.TarFile, name: str, data: bytes, mode: int) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(data), mode, int(time.time())
    out.addfile(info, io.BytesIO(data))


def _add_runtime(out: tarfile.TarFile, runtime: Path, kind: str) -> None:
    if kind == "tar":
        with tarfile.open(runtime, "r:gz") as source:
            for member in source.getmembers():  # already under python/
                out.addfile(member, source.extractfile(member) if member.isfile() else None)
        return
    with zipfile.ZipFile(runtime) as source:  # Windows' embeddable package: files at its root
        for info in source.infolist():
            if info.is_dir():
                continue
            data = source.read(info)
            if info.filename.endswith("._pth"):
                # The embeddable Python only looks where this file says: let it find the client.
                data = data.rstrip(b"\r\n") + b"\r\n..\\app\r\n"
            _add_bytes(out, "python/" + info.filename, data, 0o755 if info.filename.endswith(".exe") else 0o644)
