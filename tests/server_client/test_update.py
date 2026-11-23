"""Updating the server from the admin page: only the code layer of a newer image is fetched, checked,
run on trial, and gone back from when it does not work.

What went wrong in the earlier version is the bar: a check that fails must say so (never "up to date"),
and an update counts only once the new version answered as itself.
"""

from __future__ import annotations

import gzip
import hashlib
import http.client
import http.server
import importlib.util
import io
import json
import os
import re
import sys
import tarfile
import threading
import time
from pathlib import Path

import pytest

from tl_server import SERVER_VERSION
from tl_server import update as update_module
from tl_server.app import create_server
from tl_server.errors import ApiError
from tl_server.update import Updater

REPO = Path(__file__).resolve().parents[2]
NEW = "2099.1.2"


def load_launcher():
    spec = importlib.util.spec_from_file_location("tl_launcher", REPO / "deploy" / "nas" / "launcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def package(version: str = NEW, extra=(), without: str = "") -> bytes:
    """A code layer as the image has it: the repository's own code, saying it is another version."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as out:
        for folder in ("app", "app/tl_server"):
            entry = tarfile.TarInfo(folder)
            entry.type = tarfile.DIRTYPE
            out.addfile(entry)
        for top in ("tl_server", "tl_client", "system/skills/time-library"):
            for path in sorted((REPO / top).rglob("*")):
                if not path.is_file() or "__pycache__" in path.parts:
                    continue
                name = path.relative_to(REPO).as_posix()
                data = path.read_bytes()
                if name == "tl_server/__init__.py":
                    data = re.sub(rb'SERVER_VERSION = "[^"]+"', f'SERVER_VERSION = "{version}"'.encode(), data)
                if name == without:
                    continue
                entry = tarfile.TarInfo("app/" + name)
                entry.size = len(data)
                out.addfile(entry, io.BytesIO(data))
        for entry, data in extra:
            out.addfile(entry, io.BytesIO(data) if data is not None else None)
    return gzip.compress(raw.getvalue(), mtime=0)


class Registry:
    """A stand-in for ghcr.io and api.github.com."""

    def __init__(self) -> None:
        self.release = {"tag_name": f"v{NEW}", "body": "新东西", "html_url": "https://example.invalid/r", "published_at": "2099-01-02T00:00:00Z"}
        self.runtime = "1"
        self.layer = package()
        self.sent_layer: bytes | None = None  # what is really sent, when it differs
        self.down = False
        self.plain = False  # the version is one image, not a list of one per kind of machine
        self.machine = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}[update_module.platform.machine().lower()]
        self.leaked: list[str] = []
        self.gets: list[str] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                outer.gets.append(self.path)
                if outer.down:
                    self.send_error(503)
                    return
                outer.serve(self)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def digest(data: bytes) -> str:
        return "sha256:" + hashlib.sha256(data).hexdigest()

    def parts(self):
        config = json.dumps({"architecture": self.machine, "config": {"Labels": {"org.time-library.runtime": self.runtime}}}).encode()
        manifest = json.dumps({
            "config": {"digest": self.digest(config), "size": len(config)},
            "layers": [{"digest": "sha256:" + "0" * 64, "size": 10, "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip"},
                       {"digest": self.digest(self.layer), "size": len(self.layer), "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip"}],
        }).encode()
        index = json.dumps({"manifests": [
            {"digest": "sha256:" + "1" * 64, "platform": {"os": "unknown", "architecture": "unknown"}},
            {"digest": self.digest(manifest), "platform": {"os": "linux", "architecture": self.machine}}]}).encode()
        return index, manifest, config

    def serve(self, handler) -> None:
        index, manifest, config = self.parts()
        path = handler.path.split("?")[0]
        if path == "/releases/latest":
            body = json.dumps(self.release).encode()
        elif path == "/token":
            body = b'{"token": "anonymous-pull"}'
        elif path.endswith("/manifests/" + self.release["tag_name"][1:]):
            body = manifest if self.plain else index
        elif path.endswith(self.digest(manifest)):
            body = manifest
        elif path.endswith("/blobs/" + self.digest(config)):
            body = config
        elif path.endswith("/blobs/" + self.digest(self.layer)):  # sent on to another host, as ghcr does
            handler.send_response(307)
            handler.send_header("Location", f"http://localhost:{self.port}/cdn/layer")
            handler.end_headers()
            return
        elif path == "/cdn/layer":
            if handler.headers.get("Authorization"):
                self.leaked.append(handler.headers["Authorization"])
            body = self.layer if self.sent_layer is None else self.sent_layer
        else:
            handler.send_error(404)
            return
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)


@pytest.fixture()
def registry(monkeypatch):
    stand_in = Registry()
    monkeypatch.setattr(update_module, "RELEASES_URL", f"http://127.0.0.1:{stand_in.port}/releases/latest")
    monkeypatch.setattr(update_module, "REGISTRY", f"http://127.0.0.1:{stand_in.port}")
    monkeypatch.setattr(update_module, "TRIES", 1)
    monkeypatch.setenv("TL_LAUNCHER", "1")
    monkeypatch.setenv("TL_RUNTIME", "1")
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    yield stand_in
    stand_in.server.shutdown()


class Restarts:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> None:
        self.count += 1


@pytest.fixture()
def updater(tmp_path, registry):
    restarts = Restarts()
    made = Updater(tmp_path, restarts)
    made.restarts = restarts
    made.folder = tmp_path / "app"
    return made


def run(updater) -> dict:
    updater.check()
    updater.start()
    for _ in range(600):
        status = updater.status()
        if not status["busy"] or updater.restarts.count:
            return status
        time.sleep(0.05)
    raise AssertionError("the update did not end")


def test_a_check_that_fails_says_so_and_never_up_to_date(updater, registry):
    """The earlier version showed "up to date" when the check got a 404."""
    registry.down = True
    failed = updater.check()
    assert failed["error"] and failed["latest"] is None and not failed["available"]
    registry.down = False
    registry.release = {"tag_name": "not-a-version"}
    assert "版本号认不出来" in updater.check()["error"]
    registry.release = {"tag_name": f"v{NEW}"}
    found = updater.check()
    assert found["error"] == "" and found["available"] and found["latest"]["version"] == NEW
    registry.down = True  # a later failure keeps what is known, and says it failed
    again = updater.check()
    assert again["error"] and again["latest"]["version"] == NEW and again["available"]
    registry.down = False
    registry.release = {"tag_name": f"v{SERVER_VERSION}"}
    same = updater.check()
    assert same["error"] == "" and not same["available"]
    with pytest.raises(ApiError) as none:
        updater.start()
    assert none.value.code == "nothing_to_update"


def test_only_the_code_layer_is_fetched_checked_and_put_on_trial(updater, registry, tmp_path):
    status = run(updater)
    assert updater.restarts.count == 1 and status["failure"] is None
    code = updater.folder / "versions" / NEW
    assert (code / "tl_client" / "__init__.py").exists() and (code / "system/skills/time-library/SKILL.md").exists()
    state = json.loads((updater.folder / "state.json").read_text())
    assert (state["current"], state["previous"], state["trial"]) == (NEW, "", NEW)
    assert not (updater.folder / "incoming").exists()
    assert not any("0" * 64 in path for path in registry.gets)  # the rest of the image is not fetched
    assert registry.leaked == []  # the pull permission stays with the registry
    launcher = load_launcher()
    assert launcher.version_in(code) == NEW and launcher.intact(code)
    runs = launcher.Launcher(REPO, tmp_path, 1)
    assert runs.choose() == (code, NEW)
    (code / "tl_server" / "answer.py").write_text("raise SystemExit")  # changed afterwards: not run
    assert runs.choose() == (REPO, SERVER_VERSION)
    assert "不完整" in json.loads((updater.folder / "state.json").read_text())["history"][-1]["note"]


def test_a_version_published_as_one_image_is_fetched_the_same(updater, registry):
    registry.plain = True
    assert run(updater)["failure"] is None
    assert json.loads((updater.folder / "state.json").read_text())["current"] == NEW


def test_a_version_for_another_kind_of_machine_is_refused(updater, registry):
    registry.plain, registry.machine = True, "riscv64"
    assert "芯片" in updater.check()["latest"]["problem"]  # said before anything is clicked
    with pytest.raises(ApiError):
        updater.start()


def test_what_does_not_match_its_sha256_is_not_installed(updater, registry):
    registry.sent_layer = package("2099.9.9")
    status = run(updater)
    assert "不一致" in status["failure"]["reason"] and updater.restarts.count == 0
    assert not (updater.folder / "versions").exists() and not (updater.folder / "incoming").exists()


@pytest.mark.parametrize("bad", ["link", "up", "absolute", "elsewhere", "whiteout", "device"])
def test_a_package_with_anything_unexpected_is_refused(updater, registry, bad):
    entry = tarfile.TarInfo({"link": "app/tl_server/link.py", "up": "app/tl_server/../../evil.py", "absolute": "/etc/evil",
                             "elsewhere": "app/evil/x.py", "whiteout": "app/tl_server/.wh.app.py", "device": "app/tl_server/dev"}[bad])
    data: bytes | None = b"x"
    if bad == "link":
        entry.type, entry.linkname, data = tarfile.SYMTYPE, "/etc/passwd", None
    elif bad == "device":
        entry.type, data = tarfile.CHRTYPE, None
    if data is not None:
        entry.size = len(data)
    registry.layer = package(extra=[(entry, data)])
    status = run(updater)
    assert "不该有" in status["failure"]["reason"] and updater.restarts.count == 0
    assert not (updater.folder / "versions").exists()


def test_a_package_that_is_not_what_it_says_or_does_not_load_is_not_switched_to(updater, registry):
    registry.layer = package("2099.1.3")  # the tag says 2099.1.2
    assert "载入不了" in run(updater)["failure"]["reason"]
    registry.layer = package(without="tl_server/recall.py")
    assert "载入不了" in run(updater)["failure"]["reason"]
    assert updater.restarts.count == 0 and not (updater.folder / "versions").exists()


def test_a_version_that_needs_a_newer_image_says_so_before_anything_is_clicked(updater, registry):
    registry.runtime = "2"
    assert updater.check()["latest"]["problem"] == "needs_image"
    with pytest.raises(ApiError) as refused:
        updater.start()
    assert refused.value.code == "update_needs_image" and "docker compose pull" in refused.value.message
    registry.runtime = ""  # an image that does not say
    assert "新镜像" in updater.check()["latest"]["problem"]


def test_a_version_that_failed_before_is_not_tried_again_and_going_back_is_possible(updater, registry, monkeypatch):
    updater.folder.mkdir()
    (updater.folder / "state.json").write_text(json.dumps({"bad": [NEW]}))
    updater.check()
    with pytest.raises(ApiError) as refused:
        updater.start()
    assert refused.value.code == "update_failed_before"
    with pytest.raises(ApiError) as nothing:
        updater.go_back()
    assert nothing.value.code == "nothing_to_go_back"
    (updater.folder / "state.json").write_text(json.dumps({"current": SERVER_VERSION, "previous": "2020.1.1"}))
    assert updater.status()["can_go_back"]
    updater.go_back()
    state = json.loads((updater.folder / "state.json").read_text())
    assert (state["current"], state["trial"]) == ("2020.1.1", "2020.1.1") and updater.restarts.count == 1
    assert (state["history"][-1]["by"], state["history"][-1]["version"]) == ("owner", SERVER_VERSION)


def test_without_the_container_launcher_nothing_can_be_updated(updater, monkeypatch):
    monkeypatch.delenv("TL_LAUNCHER")
    assert updater.status()["supported"] is False
    with pytest.raises(ApiError) as refused:
        updater.start()
    assert refused.value.code == "update_not_supported"


def test_the_admin_page_asks_and_clicks_through_the_server(tmp_path, registry):
    httpd = create_server(str(tmp_path / "data"), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    admin = (tmp_path / "data" / "admin_token.txt").read_text().strip()

    def call(method, path, token=admin):
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=30)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        conn.request(method, path, body=b"{}" if method == "POST" else None, headers={**headers, "Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, json.loads(response.read())

    try:
        assert call("GET", "/api/v1/health", token="")[1]["version"] == SERVER_VERSION
        assert call("POST", "/api/v1/admin/update/start", token="")[0] == 401
        status, body = call("GET", "/api/v1/admin/update?look=1")
        assert status == 200 and body["available"] and body["latest"]["notes"] == "新东西"
        asked = registry.gets.count("/releases/latest")
        assert call("GET", "/api/v1/admin/update?look=1")[1]["available"] and registry.gets.count("/releases/latest") == asked  # looked already
        assert call("POST", "/api/v1/admin/update/start")[0] == 200
        for _ in range(200):
            if httpd.restart_requested.is_set():
                break
            time.sleep(0.05)
        assert httpd.restart_requested.is_set()  # it ends, and the launcher starts the new one
    finally:
        httpd.shutdown()
        httpd.server_close()
        httpd.store.close()


# ---- the launcher: a server that can be anything ----------------------------------------------

FAKE = '''
import http.server, json, os, sys, threading, time
from . import SERVER_VERSION, MODE
if MODE == "crash":
    sys.exit(3)
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = json.dumps({"ok": MODE != "sick", "version": "0.0" if MODE == "liar" else SERVER_VERSION}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
if MODE == "silent":
    time.sleep(600)
s = http.server.ThreadingHTTPServer(("127.0.0.1", int(os.environ["TL_PORT"])), H)
if MODE == "later":
    threading.Thread(target=lambda: (time.sleep(1.2), os._exit(4)), daemon=True).start()
if MODE == "restart":
    threading.Thread(target=lambda: (time.sleep(0.5), os._exit(75)), daemon=True).start()
s.serve_forever()
'''


def fake_code(folder: Path, version: str, mode: str = "ok") -> Path:
    (folder / "tl_server").mkdir(parents=True)
    (folder / "tl_server" / "__init__.py").write_text(f'SERVER_VERSION = "{version}"\nMODE = "{mode}"\n')
    (folder / "tl_server" / "__main__.py").write_text(FAKE)
    return folder


class Box:
    """An image with version 2026.1.1, a data folder, and a launcher running in the background."""

    def __init__(self, tmp_path, monkeypatch):
        import socket

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        monkeypatch.setenv("TL_PORT", str(self.port))
        self.launcher_module = load_launcher()
        for name, value in {"TRIAL_SECONDS": 6, "STABLE_SECONDS": 1, "POLL": 0.05, "STOP_SECONDS": 3, "CRASHES_ALLOWED": 2}.items():
            monkeypatch.setattr(self.launcher_module, name, value)
        self.data = tmp_path / "data"
        self.image = fake_code(tmp_path / "image", "2026.1.1")
        self.launcher = self.launcher_module.Launcher(self.image, self.data, self.port)
        self.thread: threading.Thread | None = None

    def fetched(self, version: str, mode: str = "ok", previous: str = "", trial: bool = True) -> None:
        code = fake_code(self.launcher.state.code(version), version, mode)
        Updater._record(code, version)
        state = self.launcher.state.read()
        state.update({"current": version, "previous": previous, "trial": version if trial else ""})
        self.launcher.state.write(state)

    def start(self) -> None:
        self.thread = threading.Thread(target=self.launcher.run, daemon=True)
        self.thread.start()

    def version(self) -> str:
        return self.launcher._health().get("version", "")

    def until(self, wanted, seconds: float = 20):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if wanted():
                return
            time.sleep(0.05)
        raise AssertionError(f"not reached; state {self.launcher.state.read()} version {self.version()!r}")

    def close(self) -> None:
        self.launcher.stop()
        if self.thread:
            self.thread.join(15)
            assert not self.thread.is_alive()
        assert self.launcher.child is None or self.launcher.child.poll() is not None or os.getpid() == 1


@pytest.fixture()
def box(tmp_path, monkeypatch):
    made = Box(tmp_path, monkeypatch)
    yield made
    made.close()


def test_a_new_version_that_answers_as_itself_is_kept(box):
    box.fetched("2026.2.1")
    box.start()
    box.until(lambda: box.launcher.state.read()["history"])
    state = box.launcher.state.read()
    assert state["history"][-1]["ok"] is True and state["current"] == "2026.2.1" and state["trial"] == ""
    assert box.version() == "2026.2.1"


@pytest.mark.parametrize("mode", ["crash", "liar", "sick", "silent"])
def test_a_new_version_that_does_not_work_is_gone_back_from(box, mode):
    """Answering 200 is not enough: it must answer as the version it is meant to be, and keep doing so."""
    box.fetched("2026.2.1", mode)
    box.start()
    box.until(lambda: box.version() == "2026.1.1", 40)
    state = box.launcher.state.read()
    assert state["history"][-1]["ok"] is False and "已退回" in state["history"][-1]["note"]
    assert state["current"] == "" and "2026.2.1" in state["bad"] and state["trial"] == ""


def test_back_to_the_version_before_not_only_to_the_image(box):
    code = fake_code(box.launcher.state.code("2026.1.5"), "2026.1.5")
    Updater._record(code, "2026.1.5")
    box.fetched("2026.2.1", "crash", previous="2026.1.5")
    box.start()
    box.until(lambda: box.version() == "2026.1.5")
    assert box.launcher.state.read()["current"] == "2026.1.5"


def test_a_version_that_keeps_ending_after_its_trial_is_gone_back_from(box):
    box.fetched("2026.2.1", "later", trial=False)
    box.start()
    box.until(lambda: box.version() == "2026.1.1" and box.launcher.state.read()["history"], 40)
    assert "好几次" in box.launcher.state.read()["history"][-1]["note"]


def test_the_image_can_be_asked_for(box, monkeypatch):
    box.fetched("2026.2.1", trial=False)
    monkeypatch.setenv("TL_USE_IMAGE", "1")
    assert box.launcher.choose() == (box.image, "2026.1.1")
    monkeypatch.setenv("TL_USE_IMAGE", "")
    assert box.launcher.choose()[1] == "2026.2.1"


def test_a_newer_image_takes_over_from_an_older_update(box):
    box.fetched("2025.12.1", trial=False)
    box.start()
    box.until(lambda: box.version() == "2026.1.1")


def test_the_server_asking_to_restart_is_started_from_the_new_choice(box):
    box.fetched("2026.2.1", "restart", trial=False)
    box.start()
    box.until(lambda: box.version() == "2026.2.1")
    box.fetched("2026.3.1", "ok", trial=False)
    box.until(lambda: box.version() == "2026.3.1")


def test_a_state_file_that_cannot_be_read_means_the_image(box):
    box.launcher.state.folder.mkdir(parents=True)
    box.launcher.state.path.write_text("{not json")
    assert box.launcher.choose() == (box.image, "2026.1.1")
    box.launcher.state.path.write_text(json.dumps({"current": "../../etc"}))
    assert box.launcher.choose() == (box.image, "2026.1.1")


# ---- the image ---------------------------------------------------------------------------------

def test_the_image_ends_with_the_servers_code_and_says_what_it_runs_on():
    lines = [line for line in (REPO / "deploy" / "nas" / "Dockerfile").read_text().splitlines() if line.strip() and not line.startswith("#")]
    assert lines[-1] == "COPY --from=app /app /app"  # an update fetches the last layer
    assert 'CMD ["python", "/opt/time-library/launcher.py"]' in lines
    runtime = next(line for line in lines if line.startswith("ARG TL_RUNTIME="))
    assert runtime == "ARG TL_RUNTIME=1"


def test_nothing_about_who_published_goes_out_with_the_image():
    # GitHub's event, which a build record includes, holds the account's e-mail address.
    workflow = (REPO / ".github" / "workflows" / "server-client.yml").read_text()
    assert "provenance: false" in workflow and "sbom: false" in workflow


def test_what_the_code_can_count_on_is_recorded():
    """What an update cannot bring: Python, libraries, llama.cpp, system packages. If this fails, either the
    newer code needs the change: raise TL_RUNTIME in deploy/nas/Dockerfile (such a version then asks for a new
    image), or it does not: then only record the new sum here."""
    docker = (REPO / "deploy" / "nas" / "Dockerfile").read_text()
    base = re.findall(r"^FROM (\S+)", docker, re.MULTILINE)
    packages = re.findall(r"apt-get install -y --no-install-recommends ([^\n]+)", docker)
    llama = re.search(r'^SHA256 = "([0-9a-f]+)"', (REPO / "deploy/nas/llama_runtime.py").read_text(), re.MULTILINE).group(1)
    wheels = (REPO / "requirements-vectors.txt").read_text()
    told = hashlib.sha256("\n".join([*base, *packages, llama, wheels]).encode()).hexdigest()
    assert (re.search(r"^ARG TL_RUNTIME=(\d+)", docker, re.MULTILINE).group(1), told[:16]) == ("1", "8bced74409c2377a")
