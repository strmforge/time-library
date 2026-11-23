"""Recall: how agents reach their memories, through the client, from the server."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import tl_client.__main__ as cli
from tl_client.recall import McpServer, preflight
from tl_client.state import State
from tl_server import recall as recall_module
from tl_server.app import create_server

REPO = Path(__file__).resolve().parents[2]

TURNS = [
    ("user", "这次改造我想做成类似网络游戏那样的服务端和客户端。服务端放在 NAS 的飞牛 Docker 应用层,不要通过 ssh 装进系统底层。"),
    ("assistant", "明白。服务端唯一权威,每台电脑只留一个轻客户端。"),
    ("user", "模型分工这个不定死,我可以自由搭配。中转比 DeepSeek 便宜。"),
    ("assistant", "好,按任务分槽:历史导入、日常提炼、深度归纳,每个槽从已配好的模型里任选。"),
    ("user", "服务端的 UI 不沿用现在的旧 UI,现在的太丑了。"),
    ("assistant", "好的,新界面重新设计。"),
]

MEMORIES = [
    ("忆凡尘服务端部署在 NAS 的飞牛 Docker 应用层,不通过 ssh 装进系统底层", "decision", 1, "服务端放在 NAS 的飞牛 Docker 应用层"),
    ("模型按任务分槽自由搭配,不写死", "preference", 3, "模型分工这个不定死,我可以自由搭配"),
    ("用户认为 GPT 中转比 DeepSeek 便宜", "fact", 3, "中转比 DeepSeek 便宜"),
    ("服务端界面重新设计,不沿用旧界面", "decision", 5, "服务端的 UI 不沿用现在的旧 UI"),
]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "machine_uid", lambda: "recall-test-device-0001")
    httpd = create_server(str(tmp_path / "server"), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    admin_token = (tmp_path / "server" / "admin_token.txt").read_text().strip()

    def call(method, path, body=None, token=admin_token):
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=30)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
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

    home = tmp_path / "client"
    pairing = call("POST", "/api/v1/admin/pairing-tokens", {})[1]["pairing_token"]
    assert cli.main(["--home", str(home), "pair", "--server", url, "--token", pairing, "--name", "Mac mini"]) == 0
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    assert cli.main(["--home", str(home), "report-agent", "--name", "Claude Code", "--sessions", str(sessions),
                     "--format", "flat_role_content"]) == 0
    state = State(home)
    device_token = state.config["device_token"]
    agent_id = state.config["agents"]["Claude Code"]["agent_id"]
    segments = [
        {"segment_uid": f"uid-{index:08d}", "session_id": "s1", "source_file": "s1.jsonl", "position": index,
         "role": role, "text": text, "ts": "2026-11-15T13:00:00Z"}
        for index, (role, text) in enumerate(TURNS)
    ]
    assert call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": segments}, token=device_token)[0] == 200

    store = httpd.store
    with store._lock:
        segment_ids = [row["id"] for row in store._db.execute("SELECT id FROM segments ORDER BY id")]
    ids = []
    with store._tx() as db:
        for statement, kind, turn, quote in MEMORIES:
            memory_id = db.execute(
                "INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at) VALUES(?,?,?,?,?,?)",
                (statement, statement, kind, agent_id, "s1", time.time()),
            ).lastrowid
            db.execute("INSERT INTO memory_evidence(memory_id, segment_id, quote) VALUES(?,?,?)",
                       (memory_id, segment_ids[turn - 1], quote))
            ids.append(memory_id)

    w = type("World", (), {})()
    w.httpd, w.call, w.url, w.home, w.device_token, w.ids, w.tmp = httpd, call, url, home, device_token, ids, tmp_path
    w.recall = lambda query, **extra: call("POST", "/api/v1/recall", {"query": query, **extra}, token=device_token)
    yield w
    httpd.distiller.shutdown()
    httpd.shutdown()
    httpd.server_close()
    httpd.store.close()


def statements(reply):
    return [memory["statement"] for memory in reply[1]["memories"]]


# ---- the server -------------------------------------------------------------------


def test_chinese_text_is_matched_by_meaning_bearing_pieces():
    assert recall_module.tokens("飞牛 Docker 应用层") == ["飞牛", "docker", "应用", "用层"]
    assert "这个" not in recall_module.tokens("这个不定死")  # common filler is ignored


def test_search_ranks_the_matching_memory_first_and_carries_its_evidence(world):
    status, body = world.recall("服务端装在 NAS 哪一层")
    assert status == 200
    top = body["memories"][0]
    assert top["statement"].startswith("忆凡尘服务端部署在 NAS")
    assert top["evidence"] == [{"quote": "服务端放在 NAS 的飞牛 Docker 应用层", "role": "user", "voice": "user", "ts": "2026-11-15T13:00:00Z"}]
    assert (top["device"], top["agent"], top["kind"]) == ("Mac mini", "Claude Code", "decision")
    assert statements(world.recall("模型怎么搭配"))[0] == "模型按任务分槽自由搭配,不写死"
    assert statements(world.recall("DeepSeek"))[0] == "用户认为 GPT 中转比 DeepSeek 便宜"
    assert world.recall("完全无关的天气预报")[1]["memories"] == []
    assert len(world.recall("服务端", limit=1)[1]["memories"]) == 1


def test_preflight_only_speaks_up_for_a_clear_match(world):
    relevant = "我们之前定的服务端是装在 NAS 的飞牛 Docker 里还是系统底层?"
    assert statements(world.recall(relevant, mode="preflight"))[0].startswith("忆凡尘服务端部署在 NAS")
    for prompt in ("继续", "好的,开始吧", "帮我写一个快速排序的函数,用 Python", "今天天气怎么样,适合出门吗"):
        assert world.recall(prompt, mode="preflight")[1]["memories"] == [], prompt
    assert len(world.recall("服务端 NAS Docker 模型 搭配 界面 旧 UI DeepSeek 中转", mode="preflight", limit=10)[1]["memories"]) <= 3


def test_expired_memories_are_not_recalled_and_new_ones_are(world):
    world.call("POST", f"/api/v1/admin/memories/{world.ids[3]}/expire", {})
    assert "服务端界面重新设计,不沿用旧界面" not in statements(world.recall("界面 旧 UI"))
    with world.httpd.store._tx() as db:
        db.execute(
            "INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at) "
            "SELECT 'x', '提炼每晚两点自动开始', 'fact', agent_id, session_id, created_at FROM memories LIMIT 1"
        )
    assert statements(world.recall("每晚几点提炼"))[0] == "提炼每晚两点自动开始"


def test_recall_is_counted_on_the_memory(world):
    world.recall("服务端装在 NAS 哪一层", limit=1)
    world.recall("服务端装在 NAS 哪一层", limit=1)
    listing = world.call("GET", "/api/v1/admin/memories")[1]["memories"]
    counted = {memory["statement"]: memory["recall_count"] for memory in listing}
    assert counted["忆凡尘服务端部署在 NAS 的飞牛 Docker 应用层,不通过 ssh 装进系统底层"] == 2
    assert counted["服务端界面重新设计,不沿用旧界面"] == 0


def test_source_shows_the_turns_around_the_evidence(world):
    status, source = world.call("GET", f"/api/v1/memories/{world.ids[1]}/source", token=world.device_token)
    assert status == 200 and source["statement"] == "模型按任务分槽自由搭配,不写死"
    (item,) = source["evidence"]
    assert item["quote"] == "模型分工这个不定死,我可以自由搭配"
    assert [turn["role"] for turn in item["before"]] == ["user", "assistant"]
    assert item["turn"]["text"] == TURNS[2][1] and item["turn"]["role"] == "user"
    assert [turn["text"] for turn in item["after"]] == [TURNS[3][1], TURNS[4][1]]
    assert world.call("GET", "/api/v1/memories/9999/source", token=world.device_token)[0] == 404


def test_recall_needs_a_paired_computer(world):
    assert world.call("POST", "/api/v1/recall", {"query": "服务端"}, token=None)[0] == 401
    assert world.call("GET", f"/api/v1/memories/{world.ids[0]}/source", token="tlc_wrong")[0] == 401
    assert world.call("POST", "/api/v1/recall", {"query": ""}, token=world.device_token)[0] == 400


# ---- the client: MCP ------------------------------------------------------------------


def rpc(server, method, params=None, id_=1):
    message = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        message["params"] = params
    return server.handle(message)


def test_mcp_handshake_and_tools(world):
    server = McpServer(State(world.home), agent="Claude Code")
    init = rpc(server, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "x"}})
    assert init["result"]["protocolVersion"] == "2025-03-26" and init["result"]["serverInfo"]["name"] == "time-library"
    assert rpc(server, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert rpc(server, "ping")["result"] == {}
    assert [tool["name"] for tool in rpc(server, "tools/list")["result"]["tools"]] == ["time_library_recall", "time_library_answer", "time_library_source", "time_library_declare", "time_library_catalog", "time_library_whiteboard", "time_library_return"]
    assert rpc(server, "nope")["error"]["code"] == -32601

    found = rpc(server, "tools/call", {"name": "time_library_recall", "arguments": {"query": "服务端装在 NAS 哪一层"}})["result"]
    text = found["content"][0]["text"]
    assert found["isError"] is False
    assert "[决定] 忆凡尘服务端部署在 NAS" in text and "原话(用户、2026-11-15):「服务端放在 NAS 的飞牛 Docker 应用层」" in text
    assert f"记忆编号 {world.ids[0]}" in text

    shown = rpc(server, "tools/call", {"name": "time_library_source", "arguments": {"memory_id": str(world.ids[1])}})["result"]
    assert shown["isError"] is False and "▶ 用户(2026-11-15):模型分工这个不定死" in shown["content"][0]["text"]

    nothing = rpc(server, "tools/call", {"name": "time_library_recall", "arguments": {"query": "天气预报"}})["result"]
    assert nothing["isError"] is False and nothing["content"][0]["text"] == "没有找到相关的记忆。"
    missing = rpc(server, "tools/call", {"name": "time_library_source", "arguments": {"memory_id": 9999}})["result"]
    assert missing["isError"] is True
    bad = rpc(server, "tools/call", {"name": "time_library_recall", "arguments": {}})["result"]
    assert bad["isError"] is True


def test_mcp_says_so_at_once_when_the_server_is_away(world):
    state = State(world.home)
    state.config["server_url"] = "http://127.0.0.1:9"
    state.save_config()
    started = time.monotonic()
    result = rpc(McpServer(State(world.home)), "tools/call", {"name": "time_library_recall", "arguments": {"query": "服务端"}})["result"]
    assert result["isError"] is True and "连不上" in result["content"][0]["text"]
    assert time.monotonic() - started < 3

    unpaired = McpServer(State(world.tmp / "nobody"))
    result = rpc(unpaired, "tools/call", {"name": "time_library_recall", "arguments": {"query": "服务端"}})["result"]
    assert result["isError"] is True and "还没接入" in result["content"][0]["text"]


def test_mcp_over_real_stdio(world):
    process = subprocess.Popen(
        [sys.executable, "-m", "tl_client", "--home", str(world.home), "mcp", "--agent", "Claude Code"],
        cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "time_library_recall", "arguments": {"query": "模型怎么搭配"}}},
    ]
    payload = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages).encode("utf-8") + b"not json\n"
    out, err = process.communicate(payload, timeout=30)
    replies = [json.loads(line) for line in out.decode("utf-8").splitlines()]
    assert [reply.get("id") for reply in replies] == [1, 2, 3, None]  # the notification got no answer
    assert "模型按任务分槽自由搭配" in replies[2]["result"]["content"][0]["text"]
    assert replies[3]["error"]["code"] == -32700
    assert process.returncode == 0 and err == b""


# ---- the client: preflight ----------------------------------------------------------------


def run_preflight(world, stdin: bytes) -> tuple[int, str, float]:
    started = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-m", "tl_client", "--home", str(world.home), "preflight", "--agent", "Claude Code"],
        cwd=REPO, input=stdin, capture_output=True, timeout=30,
    )
    return done.returncode, done.stdout.decode("utf-8"), time.monotonic() - started


def test_preflight_prints_related_memories_for_a_hook(world):
    hook = json.dumps({"session_id": "x", "hook_event_name": "UserPromptSubmit",
                       "prompt": "我们之前定的服务端是装在 NAS 的飞牛 Docker 里还是系统底层?"}, ensure_ascii=False).encode("utf-8")
    code, out, _ = run_preflight(world, hook)
    assert code == 0
    assert out.startswith("<time-library-memory>\n") and out.rstrip().endswith("</time-library-memory>")
    assert "忆凡尘服务端部署在 NAS 的飞牛 Docker 应用层" in out and "time_library_source" not in out


def test_preflight_is_silent_when_nothing_matches_or_anything_fails(world):
    assert run_preflight(world, json.dumps({"prompt": "继续"}).encode())[:2] == (0, "")
    assert run_preflight(world, "帮我写一个快速排序".encode("utf-8"))[:2] == (0, "")
    assert run_preflight(world, b"\xff\xfe not utf8 and not json")[:2] == (0, "")

    state = State(world.home)
    state.config["server_url"] = "http://127.0.0.1:9"
    state.save_config()
    code, out, took = run_preflight(world, json.dumps({"prompt": "服务端装在 NAS 哪一层"}, ensure_ascii=False).encode())
    assert (code, out) == (0, "") and took < 10


def test_our_own_recall_block_never_goes_back_up_as_dialogue():
    from tl_client.formats import BUILTIN_FORMATS, extract_message

    spec = BUILTIN_FORMATS["flat_role_content"]
    text = "<time-library-memory>\n1. [决定] 某条记忆\n</time-library-memory>\n真正的问题在这里"
    assert extract_message({"role": "user", "content": text}, spec).text == "真正的问题在这里"
    assert preflight(State(Path(os.devnull).parent / "no-such-home-xyz"), b'{"prompt": "x"}') == ""


# ---- borrowing and returning ----------------------------------------------------


def test_a_recall_is_a_loan_and_a_return_carries_the_verdict(world):
    reply = world.recall("服务端装在 NAS 哪一层", limit=1, agent="Codex")[1]
    assert reply["delivery_id"] and reply["memories"][0]["returns"] == {"useful": 0, "useless": 0, "misleading": 0}
    first = world.ids[0]
    status, body = world.call("POST", "/api/v1/returns", {"agent": "Codex", "returns": [
        {"memory_id": first, "outcome": "useful", "note": "照它把服务端放进了 Docker 应用层"}]}, token=world.device_token)
    assert (status, body["recorded"]) == (200, [{"memory_id": first, "outcome": "useful"}])
    # A return with no loan we know of is still a verdict.
    world.call("POST", "/api/v1/returns", {"returns": [{"memory_id": first, "outcome": "misleading", "note": "已经改了"}]},
               token=world.device_token)
    again = world.recall("服务端装在 NAS 哪一层", limit=1)[1]["memories"][0]
    assert again["returns"] == {"useful": 1, "useless": 0, "misleading": 1}

    detail = world.call("GET", f"/api/v1/admin/memories/{first}")[1]
    assert detail["lent"] == 2 and detail["returns"]["useful"] == 1
    notes = [(loan["agent"], loan["outcome"], loan["note"], loan["device"]) for loan in detail["loans"] if loan["outcome"]]
    assert ("Codex", "useful", "照它把服务端放进了 Docker 应用层", "Mac mini") in notes
    listing = {m["id"]: m["returns"] for m in world.call("GET", "/api/v1/admin/memories")[1]["memories"]}
    assert listing[first]["misleading"] == 1


def test_returns_are_checked(world):
    bad = [
        {"returns": []},
        {"returns": [{"memory_id": world.ids[0], "outcome": "great"}]},
        {"returns": [{"memory_id": "x", "outcome": "useful"}]},
        {"returns": [{"memory_id": world.ids[0], "outcome": "useful", "note": 5}]},
    ]
    for body in bad:
        assert world.call("POST", "/api/v1/returns", body, token=world.device_token)[0] == 400, body
    assert world.call("POST", "/api/v1/returns", {"returns": [{"memory_id": 99999, "outcome": "useful"}]},
                      token=world.device_token)[0] == 404
    assert world.call("POST", "/api/v1/returns", {"returns": [{"memory_id": world.ids[0], "outcome": "useful"}]}, token=None)[0] == 401


def test_an_agent_returns_through_mcp_and_sees_earlier_verdicts(world):
    server = McpServer(State(world.home), agent="Claude Code")
    rpc(server, "tools/call", {"name": "time_library_recall", "arguments": {"query": "服务端装在 NAS 哪一层"}})
    done = rpc(server, "tools/call", {"name": "time_library_return",
                                      "arguments": {"memory_id": world.ids[0], "outcome": "misleading", "note": "过时了"}})["result"]
    assert done["isError"] is False and "误导" in done["content"][0]["text"]
    text = rpc(server, "tools/call", {"name": "time_library_recall", "arguments": {"query": "服务端装在 NAS 哪一层"}})["result"]["content"][0]["text"]
    assert "以前借用后的评价:误导 1" in text
    wrong = rpc(server, "tools/call", {"name": "time_library_return", "arguments": {"memory_id": world.ids[0], "outcome": "meh"}})["result"]
    assert wrong["isError"] is True


def test_recall_does_not_wait_behind_a_slow_write(world):
    store = world.httpd.store
    world.recall("服务端装在 NAS 哪一层", limit=1)  # build the index first
    held, release = threading.Event(), threading.Event()

    def slow_write():
        with store._lock:  # what a write waiting on a slow disk sync looks like
            held.set()
            release.wait(10)

    threading.Thread(target=slow_write, daemon=True).start()
    held.wait(5)
    try:
        started = time.monotonic()
        status, reply = world.recall("服务端装在 NAS 哪一层", limit=1)
        source = world.call("GET", f"/api/v1/memories/{world.ids[0]}/source", token=world.device_token)
        took = time.monotonic() - started
    finally:
        release.set()
    assert status == 200 and reply["memories"] and source[0] == 200
    assert took < 1.0, f"recall waited {took:.2f}s behind a write"
    # The loans are written once the disk is free again.
    listing = {m["id"]: m["recall_count"] for m in world.call("GET", "/api/v1/admin/memories")[1]["memories"]}
    assert listing[world.ids[0]] == 2



def test_preflight_writes_utf8_whatever_the_console_encoding(monkeypatch):
    import io

    from tl_client import recall as client_recall

    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="gbk")  # a hook on Windows without PYTHONUTF8
    monkeypatch.setattr(client_recall.sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"prompt": "x"}'), encoding="utf-8"))
    monkeypatch.setattr(client_recall.sys, "stdout", console)
    monkeypatch.setattr(client_recall, "preflight", lambda state, data, agent="": "<time-library-memory>\n忆凡尘 ✅\n</time-library-memory>")
    assert client_recall.run_preflight(None, "WorkBuddy") == 0
    assert raw.getvalue().decode("utf-8") == "<time-library-memory>\n忆凡尘 ✅\n</time-library-memory>\n"


def test_the_names_and_how_to_ask_are_told_to_the_agent(world):
    hello = McpServer(State(world.home), "Codex").handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    told = hello["result"]["instructions"]
    assert all(name in told for name in ("Time Library", "时间图书馆", "忆凡尘"))  # one system, whatever the user calls it
    tools = McpServer(State(world.home), "Codex").handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    recall = next(tool for tool in tools if tool["name"] == "time_library_recall")
    assert "忆凡尘" in recall["description"] and "keywords" in recall["inputSchema"]["properties"]["query"]["description"]
    skill = (REPO / "system" / "skills" / "time-library" / "SKILL.md").read_text(encoding="utf-8")
    assert "忆凡尘" in skill and "string of keywords" in skill


def test_a_prompt_hook_is_believed_only_when_it_is_seen_at_work(world):
    """What an agent says it supports is its own word. The server shows what it really saw, and says so when
    the user's latest prompts all came without the hook asking."""
    from datetime import datetime, timezone

    store = world.httpd.store
    report = {"agent": {"name": "Claude Code", "capabilities": {"preflight": True}, "sessions_location": "~", "session_format": "x"}}
    agent_id = world.call("POST", "/api/v1/agents/report", report, token=world.device_token)[1]["agent_id"]
    count = iter(range(1000))

    def prompt(text, at, **extra):
        stamp = datetime.fromtimestamp(at, timezone.utc).isoformat()
        n = next(count)
        row = {"segment_uid": f"prompt-{n:06d}", "session_id": "live", "source_file": "live.jsonl", "position": n,
               "role": "user", "text": text, "ts": stamp}
        assert world.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": [row], **extra}, token=world.device_token)[0] == 200

    def seen():
        world.httpd.recall.flush()
        devices = world.call("GET", "/api/v1/admin/devices")[1]["devices"]
        return next(a for d in devices for a in d["agents"] if a["name"] == "Claude Code")["preflight"]

    now = time.time()
    prompt("我们之前定的番茄方案是什么", now - 100 * 86400)  # an upload catching up: not asked just now
    prompt("导入的历史里的一句提问内容", now, origin="import")
    prompt("继续", now - 5)  # too short to be looked up before an answer
    assert (seen()["quiet"], seen()["last_at"]) == (0, None)
    for at in (now - 600, now - 400):
        prompt(f"这是一句真实的提问内容 {at}", at)
    assert seen()["quiet"] == 0  # too few to tell
    prompt("这是第三句真实的提问内容", now - 200)
    assert (seen()["quiet"], seen()["calls"], seen()["last_at"]) == (3, 0, None)
    assert world.call("POST", "/api/v1/admin/doctor/run", {})[0] == 200
    world.httpd.doctor.wait()
    checks = {c["key"]: c for c in world.call("GET", "/api/v1/admin/doctor")[1]["checkup"]["checks"]}
    assert checks["preflight"]["status"] == "warn" and "Claude Code" in checks["preflight"]["label"]

    # A request that finds nothing is still a request, and only this agent's on this computer counts.
    assert world.recall("继续", mode="preflight", agent="Codex")[1]["memories"] == []
    assert seen()["quiet"] == 3
    assert world.recall("今天天气怎么样,适合出门吗", mode="preflight", agent="Claude Code")[1]["memories"] == []
    prompt("今天天气怎么样,适合出门吗", time.time())
    assert (seen()["quiet"], seen()["calls"], seen()["handed"]) == (0, 1, 0) and seen()["last_at"]
    world.recall("我们之前定的服务端是装在 NAS 的飞牛 Docker 里还是系统底层?", mode="preflight", agent="Claude Code")
    assert (seen()["calls"], seen()["handed"]) == (2, 1)

    # A server's own look-ups are not an agent's: nothing is noted.
    world.httpd.recall.recall("服务端", lend=False, device_id=1, agent="Claude Code")
    assert seen()["calls"] == 2
