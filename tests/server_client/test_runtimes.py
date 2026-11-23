"""The client with its own Python: one archive per kind of computer, fetched once, checked, unpacked."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import tarfile
import threading
import urllib.request
import zipfile

import pytest

from tl_server import runtimes
from tl_server.app import create_server


def fake_pbs(tmp_path):
    """A stand-in for a python-build-standalone archive: python/bin/python3 that answers like one."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as out:
        script = b"#!/bin/sh\necho '(3, 14)'\n"
        info = tarfile.TarInfo("python/bin/python3")
        info.size, info.mode = len(script), 0o755
        out.addfile(info, io.BytesIO(script))
    path = tmp_path / "pbs.tar.gz"
    path.write_bytes(buffer.getvalue())
    return path


def fake_embed(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr("python.exe", b"MZ")
        out.writestr("python314._pth", "python314.zip\r\n.\r\n")
    path = tmp_path / "embed.zip"
    path.write_bytes(buffer.getvalue())
    return path


@pytest.fixture()
def server(tmp_path, monkeypatch):
    pbs, embed = fake_pbs(tmp_path), fake_embed(tmp_path)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()  # noqa: E731
    monkeypatch.setattr(runtimes, "RUNTIMES", {
        "macos-arm64": {"name": "pbs.tar.gz", "urls": ["http://127.0.0.1:9/unreachable", pbs.as_uri()], "sha256": digest(pbs), "kind": "tar"},
        "windows-amd64": {"name": "embed.zip", "urls": [embed.as_uri()], "sha256": digest(embed), "kind": "zip"},
        "linux-x86_64": {"name": "bad.tar.gz", "urls": [pbs.as_uri()], "sha256": "0" * 64, "kind": "tar"},
    })
    import tl_server.app as app_module

    monkeypatch.setattr(app_module, "RUNTIMES", runtimes.RUNTIMES)
    httpd = create_server(str(tmp_path / "data"), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield httpd
    httpd.shutdown()
    httpd.server_close()
    httpd.store.close()


def fetch(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_each_kind_of_computer_gets_the_client_with_its_own_python(server, tmp_path):
    status, data = fetch(f"{server.url}/client/bundle/macos-arm64.tar.gz")
    assert status == 200
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as bundle:
        names = set(bundle.getnames())
        assert {"python/bin/python3", "tl.py", "INSTALL.md", "app/tl_client/__init__.py"} <= names
        assert bundle.getmember("python/bin/python3").mode & stat.S_IXUSR
    assert (tmp_path / "data" / "runtimes" / "pbs.tar.gz").exists()  # fetched once (past a source that did not answer), kept

    status, data = fetch(f"{server.url}/client/bundle/windows-amd64.tar.gz")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as bundle:
        pth = bundle.extractfile("python/python314._pth").read().decode()
    assert status == 200 and "..\\app" in pth  # the embeddable Python is told where the client is

    assert fetch(f"{server.url}/client/bundle/linux-x86_64.tar.gz")[0] == 503  # its checksum did not match: not used
    assert fetch(f"{server.url}/client/bundle/haiku-ppc.tar.gz")[0] == 404


@pytest.mark.skipif(os.name == "nt", reason="the stand-in interpreter is a shell script")
def test_a_computer_set_up_earlier_moves_onto_the_clients_own_python(server, tmp_path, monkeypatch):
    from tl_client import runtime

    monkeypatch.setattr(runtime, "platform_key", lambda: "macos-arm64")
    monkeypatch.setattr(runtime.platform, "system", lambda: "Darwin")
    root = tmp_path / "client"
    root.mkdir()
    interpreter = runtime.install(server.url, root)
    assert interpreter == root / "python" / "bin" / "python3" and interpreter.exists()
    assert not [path for path in root.iterdir() if path.name != "python"]  # nothing else left behind
    again = runtime.install(server.url, root)  # installing again replaces it cleanly
    assert again.exists() and not (root / "python.old").exists()
