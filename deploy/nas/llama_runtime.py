"""Put the pinned llama.cpp server (llama-server) and the libraries it needs in a folder.

    python deploy/nas/llama_runtime.py --dest deploy/nas/vendor/llama
        fetch beforehand, for a NAS that cannot reach GitHub while building
    python llama_runtime.py --dest /opt/llama --prefetched /ctx/llama
        inside the image build: use the prefetched copy if there is one

The archive is checked against a pinned sha256 either way.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

BUILD = "b12413"
SHA256 = "9974ee0a75fd84337e4bcb817050e5c71f96390215fb3231e568d23fc6d06697"
NAME = f"llama-{BUILD}-bin-ubuntu-x64.tar.gz"
URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{BUILD}/{NAME}"


def needed(entry: str) -> bool:
    """llama-server, its licence and shared libraries, but not the other tools' own libraries."""
    if entry in ("llama-server", "LICENSE"):
        return True
    if not (entry.startswith("lib") and ".so" in entry):
        return False
    if entry.startswith("libllama-server-impl"):
        return True
    return not (entry.startswith("libllama-") and "-impl.so" in entry)


def fetch(dest: Path, tarball: Path | None = None) -> None:
    data = tarball.read_bytes() if tarball else urllib.request.urlopen(URL, timeout=600).read()
    actual = hashlib.sha256(data).hexdigest()
    if actual != SHA256:
        sys.exit(f"hash mismatch for {NAME}: expected {SHA256}, got {actual}")
    with tempfile.TemporaryDirectory() as work:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(work)
        root = Path(work) / f"llama-{BUILD}"
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for entry in sorted(os.listdir(root)):
            if not needed(entry):
                continue
            source = root / entry
            if source.is_symlink():
                os.symlink(os.readlink(source), dest / entry)
            else:
                shutil.copy2(source, dest / entry)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", required=True)
    parser.add_argument("--prefetched", help="a folder already holding llama-server (used as is)")
    parser.add_argument("--tarball", help=f"a downloaded {NAME} instead of fetching it")
    args = parser.parse_args()
    dest = Path(args.dest)
    prefetched = Path(args.prefetched) if args.prefetched else None
    if prefetched and (prefetched / "llama-server").is_file():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(prefetched, dest, symlinks=True)
    else:
        fetch(dest, Path(args.tarball) if args.tarball else None)
    if not os.access(dest / "llama-server", os.X_OK):
        sys.exit("llama-server is missing or not executable")
    print(f"llama-server {BUILD} ready in {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
