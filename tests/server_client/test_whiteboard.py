"""The whiteboard: work in flight, written by the agents doing it, seen by the next window."""

from __future__ import annotations

import pytest

from test_projects import OTHER, PROJECT, world  # noqa: F401  (fixture)
from tl_client.api import ServerRefused
from tl_client.recall import McpServer
from tl_client.state import State
from tl_server import whiteboard


def write(world, **body):
    return world.api.whiteboard_write({"folder": PROJECT, **body})


def refused(world, **body) -> ServerRefused:
    with pytest.raises(ServerRefused) as caught:
        world.api.whiteboard_write({"folder": PROJECT, **body})
    return caught.value


def test_a_handoff_reaches_the_next_window_and_is_taken_over_without_relaying(world, monkeypatch):
    world.api.declare(PROJECT, "time-library", "tools", agent="Codex")
    task = write(world, action="claim", task="白板功能施工", role="施工", agent="Codex")["task"]
    assert task["id"].startswith("WB-") and task["state"] == "进行中"
    write(world, action="progress", task_id=task["id"], summary="服务端和测试完成", agent="Codex", role="施工")
    write(world, action="handoff", task_id=task["id"], summary="施工完成,请二签复核", next_owner="二签",
          agent="Codex", role="施工", memory_ids=[world.ids[0]])

    # A new window in the project (a subfolder) opens with it, before anything else.
    text = world.api.catalog(PROJECT + "/tl_server")["text"]
    line = f"在飞:{task['id']} 白板功能施工 · 施工/Codex → 待接棒,交接给 二签:施工完成,请二签复核"
    assert line in text and text.index(line) < text.index(f"#{world.ids[0]}")
    assert len(text) <= 2000

    # The next agent takes it over through MCP, by the number it saw.
    monkeypatch.chdir(world.tmp)
    world.api.declare(str(world.tmp), "time-library", agent="Claude Code")
    server = McpServer(State(world.home), agent="Claude Code")
    taken = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "time_library_whiteboard", "arguments": {"action": "claim", "task_id": task["id"], "role": "二签"}}})["result"]
    assert taken["isError"] is False and "二签/Claude Code → 进行中" in taken["content"][0]["text"]
    assert "二签/Claude Code → 进行中" in world.api.catalog(PROJECT)["text"]

    thread = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "time_library_whiteboard", "arguments": {"action": "list", "task_id": task["id"]}}})["result"]["content"][0]["text"]
    assert thread.count("\n  ") == 4 and f"依据记忆 {world.ids[0]}" in thread and "(交接给 二签)" in thread

    write(world, action="done", task_id=task["id"], summary="二签通过,已上线", agent="Claude Code", role="二签")
    assert "在飞:" not in world.api.catalog(PROJECT)["text"]  # done work leaves the startup lines
    assert f"{task['id']} 白板功能施工 → 完成:二签通过,已上线" in world.api.catalog(PROJECT, full=True)["text"]


def test_a_mistake_is_answered_with_what_was_wrong_and_a_call_that_works(world):
    undeclared = refused(world, action="claim", task="x")
    assert undeclared.code == "folder_not_declared" and "time_library_declare" in undeclared.message
    world.api.declare(PROJECT, "time-library")
    world.api.declare(OTHER, "网文")
    for body, needle in (
        ({"action": "start"}, "claim / progress"),
        ({"action": "progress", "summary": "做完一半"}, "task_id"),
        ({"action": "claim"}, "task"),
        ({"action": "handoff", "task_id": "WB-999", "summary": "交接"}, "next_owner"),
        ({"action": "progress", "task_id": "WB-999", "summary": "x"}, "没有 WB-999"),
        ({"action": "claim", "task": "x", "memory_ids": [999999]}, "没有这些记忆"),
        ({"action": "claim", "task": "x", "memory_ids": "1,2"}, "记忆编号"),
        ({"action": "progress", "task_id": "twelve", "summary": "x"}, "WB-12"),
    ):
        error = refused(world, **body)
        assert needle in error.message, (body, error.message)
        if error.code == "invalid_field":
            assert "例如: {" in error.message
    elsewhere = world.api.whiteboard_write({"folder": OTHER, "action": "claim", "task": "第三章"})["task"]["id"]
    assert refused(world, action="progress", task_id=elsewhere, summary="x").code == "other_project"


def test_the_same_role_claiming_the_same_task_twice_is_marked_and_both_kept(world):
    world.api.declare(PROJECT, "time-library")
    task = write(world, action="claim", task="迁移数据库", role="施工", agent="Codex")["task"]["id"]
    second = write(world, action="claim", task_id=task, role="施工", agent="Claude Code")
    assert "同一角色" in second["warning"]
    first_record = second["task"]["records"][0]["record_id"]
    assert second["task"]["records"][1]["collision_with"] == first_record
    assert "warning" not in write(world, action="claim", task_id=task, role="二签", agent="Hermes")


def test_startup_shows_three_lines_handoffs_first_and_leaves_out_what_went_quiet(world):
    world.api.declare(PROJECT, "time-library")
    ids = [write(world, action="claim", task=f"任务{n}", agent="Codex")["task"]["id"] for n in range(5)]
    write(world, action="handoff", task_id=ids[0], summary="交给二签", next_owner="二签", agent="Codex")
    with world.httpd.store._tx() as db:  # the oldest claim went quiet two weeks ago
        db.execute("UPDATE whiteboard_records SET created_at = created_at - ? WHERE task_id = ?",
                   ((whiteboard.STALE_DAYS + 1) * 86400, int(ids[1][3:])))
    lines = [line for line in world.api.catalog(PROJECT)["text"].splitlines() if line.startswith(("在飞:", "(白板"))]
    assert len(lines) == 4 and lines[0].startswith(f"在飞:{ids[0]}") and "还有 1 件在飞" in lines[3]
    assert all(ids[1] not in line for line in lines)
    pages = world.httpd.projects.pages()["pages"]
    (page,) = pages
    assert len(page["whiteboard"]) == 5 and [task["stale"] for task in page["whiteboard"] if task["id"] == ids[1]] == [True]


def test_the_admin_sees_each_project_its_folders_agents_whiteboard_and_what_is_undeclared(world):
    import http.client
    import json

    world.api.declare(PROJECT, "time-library", "tools", agent="Claude Code")
    write(world, action="claim", task="后台项目页", agent="Claude Code", role="施工")
    port = world.httpd.server_address[1]
    token = (world.tmp / "server" / "admin_token.txt").read_text().strip()

    def admin(path):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", path, headers={"Authorization": f"Bearer {token}"})
        return json.loads(conn.getresponse().read())

    found = admin("/api/v1/admin/projects")
    (page,) = found["pages"]
    assert (page["project"], page["series"], page["memories"]) == ("time-library", "tools", 2)
    assert page["lanes"] == {"Claude Code": 2} and page["folders"][0]["declared_by"] == "Claude Code"
    assert [task["title"] for task in page["whiteboard"]] == ["后台项目页"]
    assert found["undeclared_folders"] == 1 and found["undeclared"][0]["folder"] == OTHER

    listing = admin("/api/v1/admin/memories?project=time-library")["memories"]
    assert sorted(m["id"] for m in listing) == sorted(world.ids[:2]) and {m["project"] for m in listing} == {"time-library"}
    detail = admin(f"/api/v1/admin/memories/{world.ids[2]}")
    assert detail["project"] == "" and detail["folder"] == OTHER
