"""Projects are declared by agents per folder; the catalog lists the current project first."""

from __future__ import annotations

import json
import threading
import time

import pytest

import tl_client.__main__ as cli
from tl_client.api import Api
from tl_client.formats import BUILTIN_FORMATS, extract_cwd
from tl_client.recall import McpServer
from tl_client.state import State
from tl_client.sync import sync_all
from tl_server.app import create_server

PROJECT = "/Users/me/code/time-library"
OTHER = "/Users/me/code/novel"


def claude(session, cwd, role, text, n):
    return json.dumps({"type": role, "sessionId": session, "cwd": cwd, "timestamp": f"2026-11-17T00:00:{n:02d}Z",
                       "message": {"role": role, "content": text}}, ensure_ascii=False)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "machine_uid", lambda: "projects-test-device-01")
    httpd = create_server(str(tmp_path / "server"), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    admin = Api(url, (tmp_path / "server" / "admin_token.txt").read_text().strip())
    home = tmp_path / "client"
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "a.jsonl").write_text("\n".join([
        claude("s-tl", PROJECT, "user", "服务端放在 NAS 上", 1), claude("s-tl", PROJECT, "assistant", "好", 2)]) + "\n", encoding="utf-8")
    (sessions / "b.jsonl").write_text("\n".join([
        claude("s-sub", PROJECT + "/tl_client", "user", "客户端只用标准库", 3)]) + "\n", encoding="utf-8")
    (sessions / "c.jsonl").write_text(claude("s-novel", OTHER, "user", "第三章要改结尾", 4) + "\n", encoding="utf-8")
    token = admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert cli.main(["--home", str(home), "pair", "--server", url, "--token", token, "--name", "Mac"]) == 0
    assert cli.main(["--home", str(home), "report-agent", "--name", "Claude Code", "--sessions", str(sessions),
                     "--format", "message_envelope_content_blocks"]) == 0
    state = State(home)
    sync_all(Api(state.config["server_url"], state.config["device_token"]), state)

    store = httpd.store
    agent_id = state.config["agents"]["Claude Code"]["agent_id"]
    memories = [
        ("s-tl", "decision", "忆凡尘服务端部署在 NAS 的 Docker 应用层,不装进系统底层"),
        ("s-sub", "lesson", "客户端只能用 Python 标准库,不能要求用户装依赖"),
        ("s-novel", "decision", "小说第三章的结尾改成开放式"),
        ("s-novel", "preference", "用户希望回答先给结论再展开"),
    ]
    ids = []
    with store._tx() as db:
        for session, kind, statement in memories:
            ids.append(db.execute(
                "INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at) VALUES(?,?,?,?,?,?)",
                (statement, statement, kind, agent_id, session, time.time())).lastrowid)
            said = db.execute("SELECT id, text FROM segments WHERE session_id = ? AND role = 'user' ORDER BY id LIMIT 1", (session,)).fetchone()
            db.execute("INSERT INTO memory_evidence(memory_id, segment_id, quote) VALUES(?,?,?)", (ids[-1], said["id"], said["text"]))
            db.execute("UPDATE memories SET user_quoted = 1 WHERE id = ?", (ids[-1],))  # as saving a memory records it
    w = type("W", (), {})()
    w.httpd, w.home, w.state, w.ids, w.sessions, w.tmp = httpd, home, state, ids, sessions, tmp_path
    w.api = Api(state.config["server_url"], state.config["device_token"])
    yield w
    httpd.distiller.shutdown()
    httpd.shutdown()
    httpd.server_close()
    httpd.store.close()


def test_sessions_arrive_with_the_folder_they_worked_in(world):
    with world.httpd.store.reading() as db:
        folders = dict(db.execute("SELECT session_id, cwd FROM sessions").fetchall())
    assert folders == {"s-tl": PROJECT, "s-sub": PROJECT + "/tl_client", "s-novel": OTHER}


def test_a_folder_declared_once_holds_its_subfolders_and_leads_the_catalog(world):
    undeclared = world.api.catalog(PROJECT)
    assert undeclared["project"] is None and "还没声明" in undeclared["text"]
    done = world.api.declare(PROJECT, "time-library", "tools", agent="Claude Code")
    assert (done["project"], done["sessions"]) == ("time-library", 2)
    world.api.declare(OTHER, "网文", agent="Codex")

    catalog = world.api.catalog(PROJECT + "/tl_server")  # a window opened in a subfolder
    text = catalog["text"]
    assert catalog["project"] == {"name": "time-library", "series": "tools"}
    assert "当前项目:time-library(属于 tools),共 2 条" in text and "各 agent:Claude Code 2" in text
    assert text.index(f"#{world.ids[0]}") < text.index("跨项目的偏好") < text.index("其他项目:网文(2)")
    assert f"#{world.ids[3]} [偏好] 用户希望回答先给结论再展开 · 网文" in text  # preferences hold everywhere
    assert "Docker 应用层" in text and "要看原话用 time_library_source" in text
    assert len(text) <= 2000
    # Not isolation: the other project's memories are named, and the full catalog lists them.
    assert f"#{world.ids[2]}" in world.api.catalog(PROJECT, full=True)["text"]


def test_the_catalog_stays_short_and_says_what_it_left_out(world):
    store = world.httpd.store
    agent_id = world.state.config["agents"]["Claude Code"]["agent_id"]
    with store._tx() as db:
        for n in range(200):
            statement = f"time-library 的第 {n} 条决定:这是一条比较长的陈述,用来把书单撑满,看它会不会如实说明省略了多少"
            db.execute("INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at) VALUES(?,?,?,?,?,?)",
                       (statement, statement, "decision", agent_id, "s-tl", time.time()))
    world.api.declare(PROJECT, "time-library")
    catalog = world.api.catalog(PROJECT)
    assert len(catalog["text"]) <= 2000 + 80 and catalog["listed"] < catalog["total"]
    assert f"另有 {catalog['total'] - catalog['listed']} 条没列出" in catalog["text"]
    # A full project still leaves room for preferences, and no heading stands empty.
    lines = catalog["text"].splitlines()
    assert f"#{world.ids[3]} [偏好]" in catalog["text"]
    for index, line in enumerate(lines):
        if line.endswith(":") and line != lines[-1]:
            assert lines[index + 1].startswith("#"), line


def test_a_window_opens_with_the_catalog_and_can_declare_its_folder(world, monkeypatch):
    monkeypatch.chdir(world.tmp)
    server = McpServer(State(world.home), agent="Claude Code")
    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert "时间图书馆书单" in init["result"]["instructions"] and "time_library_declare" in init["result"]["instructions"]
    said = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                          "params": {"name": "time_library_declare", "arguments": {"project": "scratch"}}})["result"]
    assert said["isError"] is False and "scratch" in said["content"][0]["text"]
    again = McpServer(State(world.home), agent="Claude Code").handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert "当前项目:scratch" in again["result"]["instructions"]
    full = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "time_library_catalog", "arguments": {}}})
    assert "时间图书馆书单" in full["result"]["content"][0]["text"]


def test_a_shape_that_names_the_folder_once_at_the_start_still_places_every_message():
    spec = BUILTIN_FORMATS["response_item_payload_message"]
    assert extract_cwd({"type": "session_meta", "payload": {"cwd": "/w/proj"}}, spec) == "/w/proj"
    assert extract_cwd({"type": "response_item", "payload": {"type": "message", "role": "user"}}, spec) == ""
    from tl_client.sync import segments_for_line

    folder: dict = {}
    segments_for_line(json.dumps({"type": "session_meta", "payload": {"cwd": "/w/proj"}}).encode(), spec=spec,
                      source_file="x.jsonl", line_start=0, redact_categories=None, folder=folder)
    later = segments_for_line(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user",
                              "content": [{"type": "input_text", "text": "继续"}]}}).encode(), spec=spec,
                              source_file="x.jsonl", line_start=10, redact_categories=None, folder=folder)
    assert later[0]["cwd"] == "/w/proj"


def test_sessions_sent_before_folders_existed_get_their_folder_once(world):
    with world.httpd.store._tx() as db:
        db.execute("DELETE FROM sessions")
    agent = world.state.config["agents"]["Claude Code"]
    agent.pop("folders_reported", None)
    world.state.save_config()
    state = State(world.home)
    sync_all(Api(state.config["server_url"], state.config["device_token"]), state)
    with world.httpd.store.reading() as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3
    assert State(world.home).config["agents"]["Claude Code"]["folders_reported"] is True
