"""Searching the original words: found by words, narrowed, shown with what surrounds them."""

from __future__ import annotations

import time

import pytest

from test_recall import world  # noqa: F401  (fixture)
from tl_client.recall import McpServer, format_search
from tl_client.state import State
from tl_server import words as words_module
from tl_server.words import WordIndex


@pytest.fixture()
def said(world):
    """A conversation of a year ago, most of which never became a memory."""
    agent_id = State(world.home).config["agents"]["Claude Code"]["agent_id"]

    def say(session, rows, cwd="", day="2025-11-0", **extra):
        segments = [
            {"segment_uid": f"{session}-{n:06d}", "session_id": session, "source_file": f"{session}.jsonl", "position": n, "role": role,
             "text": text, "ts": f"{day}{n + 1}T08:00:00Z", "cwd": cwd} for n, (role, text) in enumerate(rows)]
        assert world.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": segments, **extra}, token=world.device_token)[0] == 200

    say("old", [("user", "路由器的后台地址记一下,是 tplogin 那个页面"), ("assistant", "好的。报错是 E4031 permission denied,先检查共享文件夹的权限。"),
                ("user", "改成 0750 以后就好了,端口用 18443"), ("assistant", "收到,0750,端口 18443。"), ("user", "今天先到这里")], cwd="/work/router", day="2025-11-1")
    world.say = say
    world.httpd.words.catch_up()
    world.search = lambda query, **extra: world.call("POST", "/api/v1/search", {"query": query, "asking": "Codex", **extra}, token=world.device_token)
    return world


def found(reply):
    assert reply[0] == 200, reply
    return [hit["text"] for hit in reply[1]["hits"]]


def test_what_never_became_a_memory_is_found_in_the_original_words(said):
    assert said.recall("E4031 permission denied")[1]["memories"] == []  # no memory holds it
    hits = said.search("E4031 权限")[1]["hits"]
    assert "E4031 permission denied" in hits[0]["text"]
    assert (hits[0]["role"], hits[0]["voice"], hits[0]["agent"], hits[0]["folder"]) == ("assistant", "assistant", "Claude Code", "/work/router")
    assert found(said.search("18443 0750"))[0].startswith("改成 0750")  # the user's own words before an assistant saying them again
    assert found(said.search("端口 18443"))[0].startswith("收到")  # said exactly so
    assert found(said.search("这句话谁都没说过 zzqx")) == []


def test_it_can_be_narrowed_by_who_when_and_where(said):
    assert all(hit["role"] == "user" for hit in said.search("18443", who="user")[1]["hits"])
    assert found(said.search("18443", who="assistant"))[0].startswith("收到")
    assert found(said.search("18443", since="2025-11-14")) and not found(said.search("18443", until="2025-11-11"))
    assert found(said.search("18443", agent="claude")) and not found(said.search("18443", agent="Codex"))
    assert found(said.search("18443", computer="Mac")) and not found(said.search("18443", computer="Office"))
    assert said.search("18443", since="last week")[0] == 400
    assert said.search("  ")[0] == 400
    assert said.call("POST", "/api/v1/search", {"query": "18443"}, token="")[0] == 401


def test_the_conversation_around_a_turn(said):
    hit = said.search("18443", who="user")[1]["hits"][0]
    around = said.call("GET", f"/api/v1/segments/{hit['segment']}/around", token=said.device_token)[1]
    assert around["turn"]["text"].startswith("改成 0750")
    assert [turn["text"][:3] for turn in around["before"]] == ["路由器", "好的。"] and around["after"][0]["text"].startswith("收到")
    assert said.call("GET", "/api/v1/segments/999999/around", token=said.device_token)[0] == 404
    # The admin page reads the same.
    status, body = said.call("GET", "/api/v1/admin/search?query=18443&who=user")
    assert status == 200 and body["hits"][0]["segment"] == hit["segment"]


def test_an_agent_searches_through_mcp_and_opens_a_turn(said):
    server = McpServer(State(said.home), "Codex")

    def call(name, arguments):
        reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
        return reply["result"]["content"][0]["text"]

    text = call("time_library_search", {"query": "共享文件夹的权限 E4031"})
    assert "原话里找到" in text and "助手、2025-11-1" in text and "turn_id=" in text
    turn = int(text.split("turn_id=")[1].split()[0])
    opened = call("time_library_source", {"turn_id": turn})
    assert "▶ 助手" in opened and "用户:路由器的后台地址" in opened
    assert "memory_id" in call("time_library_source", {})
    assert call("time_library_search", {"query": "没人说过的 zzqx"}).startswith("原话里没有找到")
    said.httpd.recall.flush()
    with said.httpd.store.reading() as db:
        assert tuple(db.execute("SELECT calls, handed FROM agent_use WHERE agent='Codex' AND mode='words'").fetchone()) == (2, 1)


def test_what_the_asking_agent_is_being_told_right_now_is_left_out(said):
    said.say("now", [("user", "帮我找找 blackbird 那个密码本在哪")], day=time.strftime("%Y-%m-") + "0")
    said.httpd.words.catch_up()
    assert found(said.search("blackbird")) != []  # another agent may find it
    assert found(said.call("POST", "/api/v1/search", {"query": "blackbird", "asking": "Claude Code"}, token=said.device_token)) == []


def test_the_index_is_built_newest_first_and_can_be_built_again(said, tmp_path, monkeypatch):
    monkeypatch.setattr(words_module, "BATCH", 2)
    index = WordIndex(said.httpd.store, tmp_path)
    assert index.step() and not index.status()["ready"]
    newest = index.search("今天先到这里")["hits"]
    assert newest and not index.search("tplogin")["hits"] and "还在建" in format_search(index.search("tplogin"))
    index.catch_up()
    assert index.status()["ready"] and index.search("tplogin")["hits"]
    count = index.status()["indexed"]
    said.say("more", [("user", "后来又说到 tplogin 一次")])
    assert index.step() and index.status()["indexed"] == count + 1  # what is new comes on its own
    index.shutdown()
    monkeypatch.setattr(words_module, "INDEX_VERSION", "2")  # the words changed: built again
    again = WordIndex(said.httpd.store, tmp_path)
    assert again.status()["indexed"] == 0
    again.catch_up()
    assert again.search("tplogin")["hits"]
    again.shutdown()
    (tmp_path / "search.db").write_bytes(b"not a database" * 500)  # damaged: built again
    damaged = WordIndex(said.httpd.store, tmp_path)
    damaged.catch_up()
    assert damaged.search("tplogin")["hits"]
    damaged.shutdown()


def test_one_long_conversation_does_not_crowd_out_the_others(said):
    said.say("long", [("user", f"cormorant 第 {n} 次提到") for n in range(8)], day="2025-10-0")
    said.say("other", [("user", "cormorant 在另一个对话里也提到")], day="2025-09-0")
    said.httpd.words.catch_up()
    hits = said.search("cormorant", limit=10)[1]["hits"]
    assert sum(hit["session"] == "long" for hit in hits) == 3 and any(hit["session"] == "other" for hit in hits)
