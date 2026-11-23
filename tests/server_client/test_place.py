"""Recall knows where the asking window works: that project's memories come first, and nothing is shut out."""

from __future__ import annotations

import time

import pytest

from test_recall import world as recall_world  # noqa: F401  (fixture)
from tl_client.recall import McpServer, preflight
from tl_client.state import State
from tl_server.projects import nested


@pytest.fixture()
def world(recall_world):
    w = recall_world
    agent_id = State(w.home).config["agents"]["Claude Code"]["agent_id"]
    with w.httpd.store.reading() as db:
        w.device_id = db.execute("SELECT device_id FROM agents WHERE id = ?", (agent_id,)).fetchone()[0]

    def remember(session, folder, statements, kind="decision"):
        row = {"segment_uid": f"{session}-00000001", "session_id": session, "source_file": f"{session}.jsonl", "position": 1, "role": "user",
               "text": "。".join(statements), "ts": "2026-11-01T08:00:00Z", "cwd": folder}
        assert w.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": [row]}, token=w.device_token)[0] == 200
        with w.httpd.store._tx() as db:
            segment = db.execute("SELECT id FROM segments WHERE session_id = ?", (session,)).fetchone()[0]
            for n, statement in enumerate(statements):
                memory = db.execute(
                    "INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at, said_at) VALUES(?,?,?,?,?,?,?)",
                    (statement, statement, kind if n == 0 else "lesson", agent_id, session, time.time(), "2026-11-01T08:00:00Z")).lastrowid
                db.execute("INSERT INTO memory_evidence(memory_id, segment_id, quote) VALUES(?,?,?)", (memory, segment, statement))

    def two_projects():
        folders = {"alpha": "D:/work/alpha", "beta": "D:/work/beta"}
        remember("s-alpha", folders["alpha"], ["甲项目的数据库备份放在 NAS 上", "甲项目备份前先停服务"])
        remember("s-beta", folders["beta"], ["乙项目的数据库备份放在移动硬盘"])
        remember("s-beta-docs", folders["beta"] + "/docs", ["乙项目的数据库备份每周一次"])
        return folders

    def ask(query, folder="", only=None, token="", whole=False):
        status, body = w.call("POST", "/api/v1/recall", {"query": query, "limit": 10, "folder": folder, "only": only or {}, "agent": "Codex"},
                              token=token or w.device_token)
        assert status == 200, body
        return body if whole else body["memories"]

    def other_device(folder, project):
        pairing = w.call("POST", "/api/v1/admin/pairing-tokens", {})[1]["pairing_token"]
        paired = w.call("POST", "/api/v1/pair", {"pairing_token": pairing, "device": {"device_uid": "second-device-000001", "name": "Office", "os": "Linux", "client_version": "1"}}, token="")[1]
        assert w.call("POST", "/api/v1/projects/declare", {"folder": folder, "project": project, "agent": "Codex"}, token=paired["device_token"])[0] == 200
        return paired["device_token"]

    w.two_projects, w.ask, w.other_device = two_projects, ask, other_device
    return w


def test_a_drive_or_a_home_folder_is_not_a_place():
    assert nested("D:/work/alpha", "D:/work/alpha/src") and nested("D:/work/alpha/src", "D:/work/alpha") and nested("D:/work", "D:/work")
    assert not nested("D:/work/alpha", "D:/work/alphabet")
    for general in ("/", "D:/", "C:/Users/me", "/Users/me", "/Users/me/Documents", "/home/me", "/root", "C:/Users/me/Desktop"):
        assert not nested(general, general.rstrip("/") + "/some/project") and not nested(general, general), general


def test_the_prompt_hook_says_where_the_window_works(world, monkeypatch):
    folders = world.two_projects()
    asked = []
    monkeypatch.setattr("tl_client.api.Api.recall_result", lambda self, query, **extra: asked.append(extra.get("folder")) or {"memories": []})
    state = State(world.home)
    preflight(state, ('{"prompt": "数据库备份放在哪里了", "cwd": "%s"}' % folders["beta"]).encode(), "Claude Code")
    preflight(state, "数据库备份放在哪里了".encode(), "Claude Code")  # plain text: where the hook itself runs
    assert asked[0] == folders["beta"] and asked[1]


def test_an_agent_asks_with_conditions_through_mcp(world):
    world.two_projects()
    server = McpServer(State(world.home), "Codex")

    def call(arguments):
        reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "time_library_recall", "arguments": arguments}})
        return reply["result"]["content"][0]["text"]

    assert "找到" in call({"query": "数据库备份放在哪里", "kind": "decision"})
    said = call({"query": "数据库备份放在哪里", "computer": "no such computer"})
    assert "按这些条件没有找到(computer=no such computer)" in said and "去掉条件能找到" in said


def test_memories_of_the_project_worked_in_come_first_and_others_are_not_shut_out(world):
    """Filtering by place loses most of what should be found; it only lifts."""
    folders = world.two_projects()
    q = "数据库备份放在哪里"
    neutral = [m["statement"] for m in world.ask(q)]
    here = world.ask(q, folder=folders["beta"])
    there = world.ask(q, folder=folders["alpha"])
    assert set(neutral) == {m["statement"] for m in here} == {m["statement"] for m in there}  # nothing lost
    assert here[0]["statement"].startswith("乙项目") and here[0]["here"] and not here[-1]["here"]
    assert there[0]["statement"].startswith("甲项目")
    inside = world.ask(q, folder=folders["beta"] + "/src/deep")  # a folder inside it is the same place
    assert inside[0]["statement"].startswith("乙项目")
    home = [m["statement"] for m in world.ask(q, folder="C:/Users/me")]  # a home folder says nothing
    assert home == neutral and not any(m["here"] for m in world.ask(q, folder="C:/Users/me"))


def test_the_same_project_on_another_computer_is_the_same_place_once_it_is_declared(world):
    folders = world.two_projects()
    status, body = world.call("POST", "/api/v1/admin/projects/assign", {"device_id": world.device_id, "folder": folders["beta"], "project": "乙"})
    assert status == 200 and body["project"] == "乙"
    other = world.other_device(folder="/mnt/beta-copy", project="乙")
    first = world.ask("数据库备份放在哪里", folder="/mnt/beta-copy", token=other)[0]
    assert first["statement"].startswith("乙项目") and first["project"] == "乙"
    # The owner takes it out again: no longer the same place.
    assert world.call("POST", "/api/v1/admin/projects/assign", {"device_id": world.device_id, "folder": folders["beta"], "project": ""})[0] == 200
    assert not any(m["here"] for m in world.ask("数据库备份放在哪里", folder="/mnt/beta-copy", token=other))
    assert world.call("POST", "/api/v1/admin/projects/assign", {"device_id": 999, "folder": "/x", "project": "y"})[0] == 404


def test_conditions_asked_for_are_kept_and_an_empty_answer_says_what_there_is_without_them(world):
    folders = world.two_projects()
    world.call("POST", "/api/v1/admin/projects/assign", {"device_id": world.device_id, "folder": folders["alpha"], "project": "甲"})
    q = "数据库备份放在哪里"
    only = world.ask(q, only={"project": "甲"})
    assert only and all(m["project"] == "甲" for m in only)
    assert world.ask(q, only={"agent": "no such agent"}) == []
    assert world.ask(q, only={"agent": "no such agent"}, whole=True)["without_conditions"] >= 2
    assert all(m["kind"] == "lesson" for m in world.ask(q, only={"kind": "lesson"}))
    assert world.ask(q, only={"until": "2001-01-01"}) == [] and world.ask(q, only={"since": "2001-01-01"})
    assert world.call("POST", "/api/v1/recall", {"query": q, "only": {"since": "yesterday"}}, token=world.device_token)[0] == 400


def test_folders_inside_another_are_counted_with_it_on_the_admin_page(world):
    folders = world.two_projects()
    page = world.call("GET", "/api/v1/admin/projects")[1]
    listed = {item["folder"]: item for item in page["undeclared"]}
    assert folders["beta"] in listed and folders["beta"] + "/docs" not in listed
    assert listed[folders["beta"]]["inside"] == 1 and listed[folders["beta"]]["memories"] >= 2
