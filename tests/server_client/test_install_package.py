"""One sentence: the agent fetches the client from the server and connects itself."""

from __future__ import annotations

import http.client
import io
import json
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest

from tl_client import service
from tl_server.app import create_server

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def server(tmp_path):
    httpd = create_server(str(tmp_path / "server"), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def get(path):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            conn.close()

    def admin(path, body):
        token = (tmp_path / "server" / "admin_token.txt").read_text().strip()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            conn.request("POST", path, body=json.dumps(body), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            return json.loads(conn.getresponse().read())
        finally:
            conn.close()

    yield type("S", (), {"get": staticmethod(get), "admin": staticmethod(admin), "url": f"http://127.0.0.1:{port}"})
    httpd.distiller.shutdown()
    httpd.shutdown()
    httpd.server_close()
    httpd.store.close()


def test_the_guide_names_this_server_and_the_package_carries_the_new_skill(server):
    status, kind, body = server.get("/client/install.md")
    guide = body.decode("utf-8")
    assert status == 200 and kind.startswith("text/markdown")
    assert f"{server.url}/client/time-library-client.zip" in guide and f"--server {server.url}" in guide
    for step in ("report-agent", "service install", "skill --into", "preflight --agent", "mcp --agent"):
        assert step in guide

    status, kind, body = server.get("/client/time-library-client.zip")
    assert status == 200 and kind == "application/zip"
    names = set(zipfile.ZipFile(io.BytesIO(body)).namelist())
    assert {"tl.py", "INSTALL.md", "app/tl_client/__main__.py", "app/tl_client/agent_skill/SKILL.md",
            "app/tl_client/agent_skill/agents/openai.yaml"} <= names
    assert not any("__pycache__" in name for name in names)
    packaged = zipfile.ZipFile(io.BytesIO(body)).read("app/tl_client/agent_skill/SKILL.md")
    assert packaged == (REPO / "system" / "skills" / "time-library" / "SKILL.md").read_bytes()
    for retired in (b"time_library_delivery_ack", b"time_library_reading_area", b"zhiyi_recall", b"capability_check"):
        assert retired not in packaged


def test_an_agent_installs_from_the_package_alone(server, tmp_path):
    """What an agent does after reading the sentence and the guide, with nothing but the package."""
    home = tmp_path / "home"
    home.mkdir()
    zipfile.ZipFile(io.BytesIO(server.get("/client/time-library-client.zip")[2])).extractall(home)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "s1.jsonl").write_text(json.dumps({"role": "user", "content": "装好了"}, ensure_ascii=False) + "\n", encoding="utf-8")
    token = server.admin("/api/v1/admin/pairing-tokens", {})["pairing_token"]

    def tl(*args, stdin=None):
        return subprocess.run([sys.executable, str(home / "tl.py"), "--home", str(home / "state"), *args],
                              input=stdin, capture_output=True, cwd=tmp_path, timeout=60)

    assert tl("pair", "--server", server.url, "--token", token, "--name", "新电脑").returncode == 0
    assert tl("report-agent", "--name", "Some Agent", "--sessions", str(sessions), "--format", "flat_role_content",
              "--capability", "mcp=true", "--capability", "skill=true").returncode == 0
    assert tl("sync").returncode == 0
    skills = tmp_path / "agent-skills"
    assert tl("skill", "--into", str(skills)).returncode == 0
    assert (skills / "time-library" / "SKILL.md").read_bytes() == (REPO / "system" / "skills" / "time-library" / "SKILL.md").read_bytes()
    listed = tl("mcp", "--agent", "Some Agent", stdin=(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n").encode())
    tools = [tool["name"] for tool in json.loads(listed.stdout.decode().splitlines()[0])["result"]["tools"]]
    assert tools == ["time_library_recall", "time_library_answer", "time_library_search", "time_library_source", "time_library_declare", "time_library_catalog", "time_library_whiteboard", "time_library_return"]
    assert "Some Agent" in tl("status").stdout.decode()


def test_the_background_service_is_described_per_system_not_per_agent(tmp_path):
    log = tmp_path / "client.log"
    plist = service.macos_plist(log)
    assert "<string>tl_client</string>" in plist and "<string>run</string>" in plist and str(log) in plist
    assert f"<string>{service.app_dir()}</string>" in plist and "<key>KeepAlive</key>" in plist
    unit = service.systemd_unit(log)
    assert f"WorkingDirectory={service.app_dir()}" in unit and "-m tl_client run" in unit and "Restart=always" in unit
    script = service.windows_script(log)
    assert "Register-ScheduledTask -TaskName 'TimeLibraryClient'" in script and "-UserId $env:USERNAME" in script
    assert "-m tl_client run --interval 15 --log" in script


def test_the_skill_has_one_source(tmp_path):
    import tl_client.__main__ as cli

    assert cli.skill_source() == REPO / "system" / "skills" / "time-library"
    assert not (REPO / "tl_client" / "agent_skill").exists()


def test_an_installed_client_follows_the_version_its_server_hands_out(server, tmp_path):
    from tl_client import CLIENT_VERSION
    from tl_client.update import installed_app_dir

    home = tmp_path / "home"
    zipfile.ZipFile(io.BytesIO(server.get("/client/time-library-client.zip")[2])).extractall(home)
    init = home / "app" / "tl_client" / "__init__.py"
    init.write_text(init.read_text(encoding="utf-8").replace(f'"{CLIENT_VERSION}"', '"0.0.1"'), encoding="utf-8")
    (home / "app" / "tl_client" / "retired_module.py").write_text("OLD = True\n", encoding="utf-8")
    token = server.admin("/api/v1/admin/pairing-tokens", {})["pairing_token"]
    run = lambda *args: subprocess.run([sys.executable, str(home / "tl.py"), "--home", str(home / "state"), *args],  # noqa: E731
                                       capture_output=True, cwd=tmp_path, timeout=60)
    assert run("pair", "--server", server.url, "--token", token).returncode == 0

    script = (
        "import sys, json; sys.path.insert(0, sys.argv[1]);"
        "from tl_client.api import Api; from tl_client.state import State; from tl_client.update import update_if_needed;"
        "s = State(sys.argv[2]); api = Api(s.config['server_url'], s.config['device_token']);"
        "reply = api.heartbeat({}); print(json.dumps([reply['client']['version'], update_if_needed(api, reply['client']['version'])]))"
    )
    out = subprocess.run([sys.executable, "-c", script, str(home / "app"), str(home / "state")], capture_output=True, cwd=tmp_path, timeout=60)
    assert json.loads(out.stdout.decode().strip().splitlines()[-1]) == [CLIENT_VERSION, True], out.stderr.decode()
    assert f'"{CLIENT_VERSION}"' in init.read_text(encoding="utf-8")
    assert not (home / "app" / "tl_client" / "retired_module.py").exists()
    assert (home / "app" / "tl_client" / "agent_skill" / "SKILL.md").exists() and not (home / "app.update").exists()
    # The same client again: nothing to do.
    again = subprocess.run([sys.executable, "-c", script, str(home / "app"), str(home / "state")], capture_output=True, cwd=tmp_path, timeout=60)
    assert json.loads(again.stdout.decode().strip().splitlines()[-1]) == [CLIENT_VERSION, False]
    # A source checkout (a developer's) is never overwritten.
    assert installed_app_dir() is None


def test_a_damaged_or_wrong_package_is_refused(tmp_path):
    from tl_client.update import apply_package

    app = tmp_path / "app"
    (app / "tl_client").mkdir(parents=True)
    (app / "tl_client" / "__main__.py").write_text("print('mine')\n", encoding="utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("app/tl_client/__main__.py", "print('theirs')\n")
        archive.writestr("app/tl_client/__init__.py", 'CLIENT_VERSION = "9.9.9"\n')
    with pytest.raises(ValueError):
        apply_package(buffer.getvalue(), app, "1.0.0")  # not the advertised version
    with pytest.raises(Exception):
        apply_package(b"not a zip", app, "9.9.9")
    assert (app / "tl_client" / "__main__.py").read_text(encoding="utf-8") == "print('mine')\n"


def test_the_service_process_restarts_the_worker_after_an_update(tmp_path, monkeypatch):
    """The process the service manager watches never exits on an update: it starts the worker again."""
    import subprocess as sp

    import tl_client.__main__ as cli

    calls = []
    results = iter([cli.UPDATED_EXIT, cli.UPDATED_EXIT, KeyboardInterrupt()])

    def fake_run(command, check=False):
        calls.append(command)
        outcome = next(results)
        if isinstance(outcome, BaseException):
            raise outcome
        return type("Done", (), {"returncode": outcome})()

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: (_ for _ in ()).throw(AssertionError("no pause after an update")))
    args = type("A", (), {"home": str(tmp_path), "interval": 15.0, "log": str(tmp_path / "c.log")})()
    assert cli._supervise(args) == 0
    assert len(calls) == 3 and all("--worker" in command and "run" in command for command in calls)
    assert calls[0][calls[0].index("--home") + 1] == str(tmp_path)
