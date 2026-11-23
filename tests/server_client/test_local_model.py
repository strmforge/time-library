"""The built-in local model: download, check, run, register: all by the server itself."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import threading

import pytest

from local_model_fakes import free_port, port_open, start_download_host, wait_until, write_stub_runtime
from tl_server import local_model
from tl_server.app import create_server

PAYLOAD = os.urandom(300_000)


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    host = start_download_host(PAYLOAD)
    write_stub_runtime(tmp_path / "llama")
    monkeypatch.setattr(local_model, "LLAMA_DIR", str(tmp_path / "llama"))
    monkeypatch.setattr(local_model, "PORT", free_port())
    # The first host cannot be reached: the mirror must be tried without anyone configuring it.
    monkeypatch.setattr(local_model, "HOSTS", ("http://127.0.0.1:9", host.url))
    monkeypatch.setattr(local_model, "CATALOG", [{
        "id": "tiny", "label": "Tiny", "repo": "org/tiny", "file": "tiny.gguf",
        "bytes": len(PAYLOAD), "sha256": hashlib.sha256(PAYLOAD).hexdigest(), "ram_bytes": 1,
    }])
    servers = []

    def boot():
        httpd = create_server(str(tmp_path / "data"), "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        token = (tmp_path / "data" / "admin_token.txt").read_text().strip()

        def call(method, path, body=None):
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=60)
            headers = {"Authorization": f"Bearer {token}"}
            payload = None
            if body is not None:
                payload = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            try:
                conn.request(method, path, body=payload, headers=headers)
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()

        return httpd, call

    def stop(httpd):
        httpd.local_model.shutdown()
        httpd.distiller.shutdown()
        httpd.shutdown()
        httpd.server_close()
        httpd.store.close()
        servers.remove(httpd)

    httpd, call = boot()
    rig = type("Rig", (), {})()
    rig.httpd, rig.call, rig.host, rig.boot, rig.stop = httpd, call, host, boot, stop
    rig.local, rig.models_dir, rig.runtime_dir, rig.monkeypatch = httpd.local_model, tmp_path / "data" / "models", tmp_path / "llama", monkeypatch

    def switch_on(local=None):
        status, body = call("POST", "/api/v1/admin/local-model/enable", {"model_id": "tiny"})
        assert status == 200, body
        (local or rig.local).wait(30)
        return call("GET", "/api/v1/admin/local-model")[1]

    rig.switch_on = switch_on
    yield rig
    for server in list(servers):
        stop(server)
    host.shutdown()
    host.server_close()


def builtin_source(rig):
    sources = [s for s in rig.call("GET", "/api/v1/admin/models")[1]["sources"] if s["builtin"]]
    return sources[0] if sources else None


def test_switching_it_on_downloads_checks_runs_and_registers_it(rig):
    before = rig.call("GET", "/api/v1/admin/local-model")[1]
    assert (before["available"], before["phase"], before["source_id"]) == (True, "off", None)
    assert before["catalog"] == [{"id": "tiny", "label": "Tiny", "bytes": len(PAYLOAD), "ram_bytes": 1}]

    status = rig.switch_on()
    assert (status["phase"], status["error"], status["model_id"]) == ("ready", "", "tiny")
    assert (rig.models_dir / "tiny.gguf").read_bytes() == PAYLOAD
    assert not (rig.models_dir / "tiny.gguf.part").exists()
    assert port_open(local_model.PORT)

    source = builtin_source(rig)
    assert source["name"] == "本机模型" and source["tested_ok"] is True and source["key_set"] is False
    assert (source["base_url"], source["protocol"], source["model"]) == (f"http://127.0.0.1:{local_model.PORT}/v1", "responses", "tiny")
    assert status["source_id"] == source["id"]

    argv = json.loads((rig.runtime_dir / "argv.json").read_text())
    assert argv[argv.index("-m") + 1].endswith("tiny.gguf") and argv[argv.index("--alias") + 1] == "tiny"
    assert argv[argv.index("--host") + 1] == "127.0.0.1"  # never exposed outside the server
    assert argv[argv.index("--reasoning-budget") + 1] == "0"
    assert argv[argv.index("--sleep-idle-seconds") + 1] == str(local_model.IDLE_SECONDS)

    # It is a model source like any other: a job can be given to it.
    status, slot = rig.call("POST", "/api/v1/admin/models/slots", {"slot": "daily", "role": "main", "source_id": source["id"]})
    assert status == 200 and slot["main"] == {"source_id": source["id"], "model": "tiny"}
    chain = rig.httpd.models.resolve("daily")
    assert chain[0]["builtin"] is True and rig.httpd.models.prepare(source["id"]) > 240


def test_a_partial_download_is_resumed_not_restarted(rig):
    rig.models_dir.mkdir(parents=True)
    (rig.models_dir / "tiny.gguf.part").write_bytes(PAYLOAD[:100_000])
    assert rig.call("GET", "/api/v1/admin/local-model")[1]["downloaded_bytes"] == 0  # nothing chosen yet
    status = rig.switch_on()
    assert status["phase"] == "ready"
    assert rig.host.ranges == ["bytes=100000-"]
    assert (rig.models_dir / "tiny.gguf").read_bytes() == PAYLOAD


def test_a_file_that_is_not_the_expected_one_is_discarded(rig):
    rig.monkeypatch.setitem(local_model.CATALOG[0], "sha256", "0" * 64)
    status = rig.switch_on()
    assert status["phase"] == "error" and "hash" in status["error"]
    assert not (rig.models_dir / "tiny.gguf").exists() and not (rig.models_dir / "tiny.gguf.part").exists()
    assert builtin_source(rig) is None and not port_open(local_model.PORT)


def test_a_download_can_be_paused_and_picked_up_again(rig):
    rig.host.slow = True
    assert rig.call("POST", "/api/v1/admin/local-model/enable", {"model_id": "tiny"})[0] == 200
    assert wait_until(lambda: rig.call("GET", "/api/v1/admin/local-model")[1]["downloaded_bytes"] > 0)
    status, body = rig.call("POST", "/api/v1/admin/local-model/enable", {"model_id": "tiny"})
    assert (status, body["error"]) == (409, "already_running")

    paused = rig.call("POST", "/api/v1/admin/local-model/cancel", {})[1]
    assert paused["phase"] == "off" and 0 < paused["downloaded_bytes"] < len(PAYLOAD)
    assert builtin_source(rig) is None

    rig.host.slow = False
    assert rig.switch_on()["phase"] == "ready"
    assert rig.host.ranges[-1] == f"bytes={paused['downloaded_bytes']}-"
    assert (rig.models_dir / "tiny.gguf").read_bytes() == PAYLOAD


def test_switching_it_off_removes_the_file_the_process_and_its_jobs(rig):
    rig.switch_on()
    source = builtin_source(rig)
    rig.call("POST", "/api/v1/admin/models/slots", {"slot": "daily", "role": "main", "source_id": source["id"]})

    removed = rig.call("POST", "/api/v1/admin/local-model/remove", {})[1]
    assert (removed["phase"], removed["model_id"], removed["source_id"]) == ("off", "", None)
    assert not (rig.models_dir / "tiny.gguf").exists()
    assert wait_until(lambda: not port_open(local_model.PORT))
    listing = rig.call("GET", "/api/v1/admin/models")[1]
    assert listing["sources"] == [] and listing["slots"]["daily"]["main"] is None


def test_the_built_in_source_is_not_edited_or_deleted_like_an_ordinary_one(rig):
    rig.switch_on()
    sid = builtin_source(rig)["id"]
    status, body = rig.call("POST", f"/api/v1/admin/models/sources/{sid}", {"base_url": "http://elsewhere.example/v1"})
    assert (status, body["error"]) == (409, "builtin_source")
    status, body = rig.call("POST", f"/api/v1/admin/models/sources/{sid}/delete", {})
    assert (status, body["error"]) == (409, "builtin_source")
    assert rig.call("POST", f"/api/v1/admin/models/sources/{sid}/test", {})[1]["ok"] is True


def test_it_comes_back_by_itself_after_the_server_restarts(rig):
    rig.switch_on()
    rig.stop(rig.httpd)
    assert wait_until(lambda: not port_open(local_model.PORT))

    httpd, call = rig.boot()
    assert call("GET", "/api/v1/admin/local-model")[1]["phase"] == "off"  # not yet started
    httpd.local_model.resume_on_boot()
    httpd.local_model.wait(30)
    status = call("GET", "/api/v1/admin/local-model")[1]
    assert status["phase"] == "ready" and port_open(local_model.PORT)
    assert rig.host.ranges == [None]  # the file was not downloaded a second time


def test_a_runtime_that_died_is_started_again_before_it_is_needed(rig):
    rig.switch_on()
    sid = builtin_source(rig)["id"]
    rig.local._process.kill()
    rig.local._process.wait(5)
    assert wait_until(lambda: not port_open(local_model.PORT))
    assert rig.call("POST", f"/api/v1/admin/models/sources/{sid}/test", {})[1]["ok"] is True
    assert port_open(local_model.PORT)


def test_a_build_without_the_runtime_says_so(rig):
    rig.monkeypatch.setattr(local_model, "LLAMA_DIR", str(rig.runtime_dir / "missing"))
    assert rig.call("GET", "/api/v1/admin/local-model")[1]["available"] is False
    status, body = rig.call("POST", "/api/v1/admin/local-model/enable", {"model_id": "tiny"})
    assert (status, body["error"]) == (409, "local_model_unavailable")
    status, body = rig.call("POST", "/api/v1/admin/local-model/enable", {"model_id": "tiny"})
    assert status == 409


def test_unknown_models_are_refused(rig):
    status, body = rig.call("POST", "/api/v1/admin/local-model/enable", {"model_id": "not-in-catalog"})
    assert (status, body["error"]) == (400, "invalid_field")
