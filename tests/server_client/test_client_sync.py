"""Client and server together: pair, self-report, read sessions, upload, resume."""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from types import SimpleNamespace

import pytest

import tl_client.__main__ as cli
from tl_client.api import Api, ServerUnreachable
from tl_client.state import State
from tl_client.sync import sync_all
from tl_server.app import create_server


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "machine_uid", lambda: "fixed-machine-uid-0001")
    data_dir = tmp_path / "server"
    httpd = create_server(str(data_dir), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    env = SimpleNamespace(
        url=url,
        data_dir=data_dir,
        home=tmp_path / "client",
        sessions=sessions,
        admin=Api(url, (data_dir / "admin_token.txt").read_text().strip()),
    )
    yield env
    httpd.shutdown()
    httpd.server_close()
    httpd.store.close()


def run(env, *args) -> int:
    return cli.main(["--home", str(env.home), *args])


def connect(env, agent="Claude Code", fmt="message_envelope_content_blocks", name="Mac mini"):
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", name) == 0
    report(env, agent, fmt)


def report(env, agent="Claude Code", fmt="message_envelope_content_blocks"):
    assert (
        run(env, "report-agent", "--name", agent, "--sessions", str(env.sessions), "--format", fmt,
            "--capability", "mcp=true", "--capability", "preflight=false")
        == 0
    )


def sync(env):
    state = State(env.home)
    return sync_all(Api(state.config["server_url"], state.config["device_token"]), state)


def stored(env) -> list[tuple[str, str]]:
    db = sqlite3.connect(env.data_dir / "server.db")
    try:
        return db.execute("SELECT role, text FROM segments ORDER BY id").fetchall()
    finally:
        db.close()


def user(content, **extra):
    return {"type": "user", "sessionId": "s1", "timestamp": "2026-11-16T00:00:00Z",
            "message": {"role": "user", "content": content}, **extra}


def assistant(content):
    return {"type": "assistant", "sessionId": "s1", "timestamp": "2026-11-16T00:00:01Z",
            "message": {"role": "assistant", "content": content}}


def append(path, *records, newline=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        for index, record in enumerate(records):
            line = json.dumps(record, ensure_ascii=False).encode("utf-8")
            handle.write(line + (b"\n" if newline or index < len(records) - 1 else b""))


def test_only_dialogue_reaches_the_server_and_it_is_redacted(env):
    connect(env)
    append(
        env.sessions / "project-a" / "s1.jsonl",
        user("服务端放在 NAS 上"),
        assistant([
            {"type": "thinking", "thinking": "PRIVATE REASONING"},
            {"type": "text", "text": "好,这样本机不占空间"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "cat ~/.ssh/id_rsa"}},
        ]),
        user([{"type": "tool_result", "content": "TOOL OUTPUT WITH FILE CONTENTS"}]),
        user("<system-reminder>INJECTED CONTEXT</system-reminder>"),
        user("key 是 sk-abcdefghijklmnopqrstuvwxyz123456 记一下"),
        {"type": "attachment", "attachment": {"text": "HOOK CONTEXT"}},
        user("META NOTE", isMeta=True),
    )
    (result,) = sync(env)
    assert (result.accepted, result.duplicates, result.pending) == (3, 0, 0)
    assert stored(env) == [
        ("user", "服务端放在 NAS 上"),
        ("assistant", "好,这样本机不占空间"),
        ("user", "key 是 [已打码:密钥] 记一下"),
    ]

    device = env.admin._call("GET", "/api/v1/admin/devices")["devices"][0]
    assert device["name"] == "Mac mini"
    agent = device["agents"][0]
    assert (agent["name"], agent["segments_total"], agent["backlog"]) == ("Claude Code", 3, 0)
    assert agent["capabilities"] == {"mcp": True, "preflight": False}
    assert agent["session_format"] == "message_envelope_content_blocks"


def test_only_new_complete_lines_are_sent(env):
    connect(env)
    path = env.sessions / "s1.jsonl"
    append(path, user("第一句"), assistant("第二句"))
    append(path, user("第三句还没写完"), newline=False)
    assert sync(env)[0].accepted == 2

    with path.open("ab") as handle:
        handle.write(b"\n")
    assert sync(env)[0].accepted == 1

    again = sync(env)[0]
    assert (again.accepted, again.duplicates, again.files_read) == (0, 0, 0)
    assert [text for _role, text in stored(env)] == ["第一句", "第二句", "第三句还没写完"]


def test_a_reinstalled_client_resumes_from_what_the_server_has(env):
    connect(env)
    path = env.sessions / "s1.jsonl"
    append(path, user("第一句"), assistant("第二句"), {"type": "system", "subtype": "noise"})
    assert sync(env)[0].accepted == 2

    shutil.rmtree(env.home)  # everything the client knew is gone
    connect(env)
    resumed = sync(env)[0]
    assert (resumed.accepted, resumed.duplicates) == (0, 0)  # nothing was sent again

    append(path, user("重装之后的新一句"))
    assert sync(env)[0].accepted == 1
    devices = env.admin._call("GET", "/api/v1/admin/devices")["devices"]
    assert len(devices) == 1 and len(devices[0]["agents"]) == 1  # same computer, same agent
    assert len(stored(env)) == 3


def test_server_unreachable_loses_nothing(env):
    connect(env)
    path = env.sessions / "s1.jsonl"
    append(path, user("第一句"))
    assert sync(env)[0].accepted == 1
    append(path, assistant("断网期间的一句"))

    state = State(env.home)
    before = dict(state.progress["Claude Code"])
    with pytest.raises(ServerUnreachable):
        sync_all(Api("http://127.0.0.1:9", state.config["device_token"]), state)
    assert State(env.home).progress["Claude Code"] == before  # read position did not move

    assert sync(env)[0].accepted == 1
    assert [text for _role, text in stored(env)] == ["第一句", "断网期间的一句"]


def test_proxy_settings_on_the_computer_are_ignored(env, monkeypatch):
    for name in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    connect(env)
    append(env.sessions / "s1.jsonl", user("走直连"))
    assert sync(env)[0].accepted == 1


def test_a_disconnected_agent_stops_and_its_neighbour_carries_on(env):
    connect(env, agent="Claude Code")
    other_sessions = env.sessions.parent / "other"
    other_sessions.mkdir()
    assert run(env, "report-agent", "--name", "Codex", "--sessions", str(other_sessions),
               "--format", "response_item_payload_message") == 0
    append(env.sessions / "s1.jsonl", user("第一句"))
    append(other_sessions / "rollout-1.jsonl",
           {"type": "response_item", "payload": {"type": "message", "role": "developer",
                                                   "content": [{"type": "input_text", "text": "<permissions>x</permissions>"}]}},
           {"type": "response_item", "payload": {"type": "message", "role": "user",
                                                   "content": [{"type": "input_text", "text": "换成本地模型"}]}})

    agents = {a["name"]: a["agent_id"] for a in env.admin._call("GET", "/api/v1/admin/devices")["devices"][0]["agents"]}
    env.admin._call("POST", f"/api/v1/admin/agents/{agents['Claude Code']}/disconnect", {})

    results = {result.agent: result for result in sync(env)}
    assert results["Claude Code"].paused and results["Claude Code"].accepted == 0
    assert results["Codex"].accepted == 1
    assert State(env.home).config["agents"]["Claude Code"]["paused"] is True
    assert stored(env) == [("user", "换成本地模型")]

    report(env, "Claude Code")  # self-reporting again is how it comes back
    results = {result.agent: result for result in sync(env)}
    assert results["Claude Code"].accepted == 1


def test_a_replaced_session_file_is_read_again_without_duplicates(env):
    connect(env)
    path = env.sessions / "s1.jsonl"
    append(path, user("第一句"), assistant("第二句"))
    assert sync(env)[0].accepted == 2

    path.write_bytes(b"")
    append(path, user("第一句"))
    result = sync(env)[0]
    assert (result.accepted, result.duplicates) == (0, 1)
    assert len(stored(env)) == 2


def test_long_turns_are_split_and_survive_intact(env):
    connect(env)
    long_text = "长" * 250_000
    append(env.sessions / "s1.jsonl", user(long_text))
    assert sync(env)[0].accepted == 3
    assert "".join(text for _role, text in stored(env)) == long_text


def test_status_and_unpaired_commands(env, capsys):
    assert run(env, "status") == 0
    assert "not paired" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        run(env, "sync")
    connect(env)
    capsys.readouterr()
    assert run(env, "status") == 0
    out = capsys.readouterr().out
    assert "Mac mini" in out and "Claude Code" in out and "tlc_" not in out


def test_old_history_is_imported_once_and_held_for_the_owner(env, tmp_path, capsys):
    connect(env)
    old = tmp_path / "old-copies" / "2026"
    old.mkdir(parents=True)
    rows = [user("以前定下的方案:服务端放 NAS"), assistant([{"type": "text", "text": "记住了"}])]
    (old / "a.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    args = ["import", "--agent", "Claude Code", "--from", str(old.parent), "--format", "message_envelope_content_blocks"]

    assert run(env, *args, "--dry-run") == 0
    assert stored(env) == [] and "would send 2 dialogue pieces" in capsys.readouterr().out
    assert run(env, *args) == 0
    assert stored(env) == [("user", "以前定下的方案:服务端放 NAS"), ("assistant", "记住了")]
    db = sqlite3.connect(env.data_dir / "server.db")
    try:
        assert db.execute("SELECT DISTINCT imported, source_file FROM segments").fetchall() == [(1, "history/2026/a.jsonl")]
    finally:
        db.close()
    held = env.admin._call("GET", "/api/v1/admin/distill")["held"]
    assert (held["segments"], held["agents"][0]["agent"]) == (2, "Claude Code")
    capsys.readouterr()
    assert run(env, *args) == 0  # nothing new: read from where it stopped
    assert "(0 with something new), sent 0" in capsys.readouterr().out and len(stored(env)) == 2
    with pytest.raises(SystemExit, match="has not reported itself"):
        run(env, "import", "--agent", "Codex", "--from", str(old.parent))


def test_import_takes_several_patterns_and_reads_each_file_once(env, tmp_path, capsys):
    connect(env)
    old = tmp_path / "mirror"
    old.mkdir()
    line = json.dumps(user("一段旧对话"), ensure_ascii=False) + "\n"
    for name in ("0a1b2c3d-1111-2222-3333-444455556666.jsonl", "0a1b2c3d-1111-2222-3333-444455556666.seg2.jsonl",
                 "0a1b2c3d-1111-2222-3333-444455556666.jsonl.canonical_dialogue.jsonl"):
        (old / name).write_text(line.replace("一段旧对话", f"一段旧对话 {name[-12:]}"), encoding="utf-8")
    assert run(env, "import", "--agent", "Claude Code", "--from", str(old), "--format", "message_envelope_content_blocks",
               "--glob", "*-????????????.jsonl", "--glob", "*.seg[0-9].jsonl", "--glob", "*.jsonl") == 0
    assert "3 files" in capsys.readouterr().out
    assert run(env, "import", "--agent", "Claude Code", "--from", str(old), "--format", "message_envelope_content_blocks",
               "--glob", "*-????????????.jsonl", "--glob", "*.seg[0-9].jsonl", "--dry-run") == 0
    assert "2 files" in capsys.readouterr().out


def test_an_import_sends_a_batch_again_when_the_server_was_too_slow(env, tmp_path, monkeypatch):
    import tl_client.history as history

    connect(env)
    old = tmp_path / "slow"
    old.mkdir()
    (old / "a.jsonl").write_text(json.dumps(user("慢服务端也不丢"), ensure_ascii=False) + "\n", encoding="utf-8")
    state = State(env.home)
    real = Api(state.config["server_url"], state.config["device_token"])
    calls = {"n": 0}

    class Flaky:
        def ingest(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ServerUnreachable("timed out")
            return real.ingest(*args, **kwargs)

    monkeypatch.setattr(history, "RETRY_PAUSES", (0,))
    result = history.import_history(Flaky(), state, "Claude Code", str(old), "*.jsonl", "message_envelope_content_blocks")
    assert (calls["n"], result.accepted) == (2, 1) and stored(env) == [("user", "慢服务端也不丢")]
    assert any("sending again" in note for note in result.notes)


def test_the_skill_goes_where_the_agent_reads_skills_and_an_old_one_is_kept(env, tmp_path):
    skills = tmp_path / "skills"
    (skills / "time-library").mkdir(parents=True)
    (skills / "time-library" / "SKILL.md").write_text("old skill: time_library_delivery_ack", encoding="utf-8")
    assert run(env, "skill", "--into", str(skills)) == 0
    written = (skills / "time-library" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: time-library" in written and "time_library_source" in written
    assert "delivery_ack" not in written and "reading_area" not in written and "zhiyi" not in written
    assert (skills / "time-library" / "agents" / "openai.yaml").exists()
    kept = list((env.home / "skill-backups").rglob("SKILL.md"))
    assert len(kept) == 1 and "delivery_ack" in kept[0].read_text(encoding="utf-8")


def test_a_skill_put_into_an_agents_folder_follows_client_updates(env, tmp_path):
    from tl_client.__main__ import refresh_skills

    first, second = tmp_path / "codex-skills", tmp_path / "other-skills"
    for folder in (first, second):
        assert run(env, "skill", "--into", str(folder)) == 0
    assert run(env, "skill", "--into", str(first)) == 0  # installing twice is remembered once
    state = State(env.home)
    assert state.config["skills"] == [str(first / "time-library"), str(second / "time-library")]
    assert refresh_skills(state) == []  # already current: nothing touched

    # An older copy (as left by an earlier client) is brought up to date; a removed one stays removed.
    (first / "time-library" / "SKILL.md").write_text("prompt_version: 8\nold words", encoding="utf-8")
    import shutil
    shutil.rmtree(second / "time-library")
    assert refresh_skills(State(env.home)) == [str(first / "time-library")]
    assert "time_library_whiteboard" in (first / "time-library" / "SKILL.md").read_text(encoding="utf-8")
    assert not (second / "time-library").exists()


def test_an_agents_model_catalog_is_passed_on_once_per_change(env, tmp_path):
    catalog = tmp_path / "models_cache.json"
    catalog.write_text(json.dumps({"models": [{"slug": "gpt-x", "supported_reasoning_levels": [{"effort": "low"}, {"effort": "max"}]}]}), encoding="utf-8")
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token) == 0
    assert run(env, "report-agent", "--name", "Codex", "--sessions", str(env.sessions), "--format", "response_item_payload_message",
               "--model-catalog", str(catalog)) == 0
    from tl_client.sync import report_catalogs

    state = State(env.home)
    api = Api(state.config["server_url"], state.config["device_token"])
    assert report_catalogs(api, state) == 1
    assert report_catalogs(api, State(env.home)) == 0  # unchanged: not sent again
    db = sqlite3.connect(env.data_dir / "server.db")
    try:
        assert db.execute("SELECT model, levels, reported_by FROM reported_levels").fetchall() == [("gpt-x", '["low", "max"]', "Codex @ " + state.config["device_name"])]
    finally:
        db.close()


def test_a_fresh_worker_follows_a_new_client_version_at_once(monkeypatch):
    import tl_client.__main__ as cli
    from tl_client import update

    tried = []
    monkeypatch.setattr(cli, "_last_update_try", None)
    monkeypatch.setattr(cli.time, "monotonic", lambda: 5.0)  # macOS: monotonic time starts near zero
    monkeypatch.setattr(update, "update_if_needed", lambda api, version: tried.append(version) or False)
    api = type("Api", (), {"last_heartbeat": {"client": {"version": "9999.1.1"}}})()
    cli._maybe_update(api)
    assert tried == ["9999.1.1"]
    cli._maybe_update(api)  # tried a moment ago: not again within the hour
    assert tried == ["9999.1.1"]


# ---- agents that keep their sessions in a database, and other shapes they report ----


def hermes_like_db(path):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
                               content TEXT, tool_calls TEXT, timestamp REAL NOT NULL);
    """)
    db.commit()
    return db


def test_an_agent_that_keeps_sessions_in_sqlite_is_read_row_by_row_read_only(env, tmp_path):
    path = tmp_path / "state.db"
    db = hermes_like_db(path)
    db.executemany("INSERT INTO messages(session_id, role, content, tool_calls, timestamp) VALUES(?,?,?,?,?)", [
        ("s1", "user", "以后汇报先给结论", None, 1789667689.25),
        ("s1", "assistant", "", '[{"name": "terminal"}]', 1789667690.0),
        ("s1", "tool", "ls output ...", None, 1789667691.0),
        ("s1", "assistant", "好的,以后先给结论再展开", None, 1789667692.0),
    ])
    db.commit()
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "Mac mini") == 0
    spec = {"base": "flat_role_content", "store": "sqlite", "table": "messages", "order": "id", "match": {"role": ["user", "assistant"]}}
    assert run(env, "report-agent", "--name", "Hermes", "--sessions", str(path), "--format-json", json.dumps(spec)) == 0
    sync(env)
    assert stored(env) == [("user", "以后汇报先给结论"), ("assistant", "好的,以后先给结论再展开")]  # tool rows and empty turns are runtime
    server = sqlite3.connect(env.data_dir / "server.db")
    assert server.execute("SELECT session_id, ts, source_file FROM segments ORDER BY id LIMIT 1").fetchone() == (
        "s1", "2026-09-17T17:54:49.250Z", "state.db#messages")

    # New rows are read from where it stopped, and nothing twice.
    db.execute("INSERT INTO messages(session_id, role, content, timestamp) VALUES('s2', 'user', '换个话题', 1789667700.0)")
    db.commit()
    sync(env)
    assert [text for _, text in stored(env)] == ["以后汇报先给结论", "好的,以后先给结论再展开", "换个话题"]

    # A reinstalled client with no positions asks the server how far it got.
    state = State(env.home)
    state.progress.clear()
    state.save_progress()
    sync(env)
    assert len(stored(env)) == 3
    db.close()


def test_a_reported_flat_shape_with_millisecond_times_and_injected_context(env):
    session = env.sessions / "proj" / "c9c6.jsonl"
    session.parent.mkdir()
    lines = [
        {"type": "session-meta", "sessionId": "c9c6", "timestamp": 1793376100000},
        {"type": "message", "role": "user", "sessionId": "c9c6", "cwd": "C:/Users/me/WorkBuddy", "timestamp": 1793376110253,
         "content": [{"type": "input_text", "text": "<system-reminder>OS Version: Windows</system-reminder>\n凌晨好"}]},
        {"type": "reasoning", "sessionId": "c9c6", "content": [{"type": "text", "text": "thinking..."}]},
        {"type": "function_call", "sessionId": "c9c6", "name": "shell", "arguments": "{}"},
        {"type": "message", "role": "assistant", "sessionId": "c9c6", "cwd": "C:/Users/me/WorkBuddy", "timestamp": 1793376120499,
         "content": [{"type": "output_text", "text": "凌晨好,今天搞哪块?"}]},
    ]
    session.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n", encoding="utf-8")
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "windows") == 0
    spec = {"base": "flat_role_content", "match": {"type": ["message"]}}
    assert run(env, "report-agent", "--name", "WorkBuddy", "--sessions", str(env.sessions), "--format-json", json.dumps(spec)) == 0
    sync(env)
    assert stored(env) == [("user", "凌晨好"), ("assistant", "凌晨好,今天搞哪块?")]
    server = sqlite3.connect(env.data_dir / "server.db")
    assert server.execute("SELECT ts FROM segments ORDER BY id").fetchall() == [("2026-10-30T16:01:50.253Z",), ("2026-10-30T16:02:00.499Z",)]
    assert server.execute("SELECT cwd FROM sessions").fetchone()[0] == "C:/Users/me/WorkBuddy"


DSH_FORMAT = {
    "name": "dsh-session-v4", "base": "flat_role_content",
    "match": {"type": ["user/message", "assistant/message"]},
    "user_match": {"data.source.kind": ["user"]},
    "role": ["data.role", "data.message.role"], "content": ["data.content", "data.message.content"],
    "timestamp": ["time"], "session_id": ["id"], "cwd": ["cwd"], "session_skip_if_equals": {"origin": ["subagent"]},
}


def dsh_records(*said):
    """Records shaped like a harness that writes its own context in the user's name."""
    for seq, (kind, text) in enumerate(said):
        if kind == "assistant":
            yield {"type": "assistant/message", "seq": seq, "time": 1795190944301 + seq, "data": {"turn": 1, "message": {
                "role": "assistant", "content": [{"type": "reasoning", "text": "..."}, {"type": "text", "text": text},
                                                 {"type": "tool-call", "name": "pwsh", "arguments": "{}"}]}}}
        else:
            yield {"type": "user/message", "seq": seq, "time": 1795190941954 + seq,
                   "data": {"role": "user", "source": {"kind": kind}, "content": [{"type": "text", "text": text}]}}
        yield {"type": "tool/result", "seq": seq, "time": 1795190944400 + seq, "data": {"output": "lots of output"}}


def zstd_frames(records) -> bytes:
    """Records compressed the way such a harness writes them: a frame per write."""
    zstandard = pytest.importorskip("zstandard")
    return b"".join(zstandard.ZstdCompressor().compress((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
                    for record in records)


def write_zstd_frames(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(zstd_frames(records))


def test_compressed_session_files_are_read_frame_by_frame_and_only_what_the_user_typed(env):
    pytest.importorskip("zstandard")
    session = env.sessions / "--D-~work--" / "session-0a1b2c3d" / "session.v4.jsonl.zstd"
    write_zstd_frames(session, [{"type": "session", "version": 4, "id": "session-0a1b2c3d", "cwd": "D:\\work\\demo"}])
    said = list(dsh_records(
        ("user-approval", "The user changed the approval policy to never ask."),
        ("time-context", "Time sampled while preparing turn 1: 2026-11-21T00:09:01+08:00"),
        ("user", "帮我把这两个软件拆包完整研究并生成详细的报告"),
        ("subagent-settled", "Background subagent tb-app finished."),
        ("assistant", "先核对文件在不在,再拆包。"),
    ))
    write_zstd_frames(session, said)
    # A subagent's own transcript: the lead agent's task is written there as the user's turn.
    subagent = env.sessions / "--D-~work--" / "9f8e7d6c" / "session.v4.jsonl.zstd"
    write_zstd_frames(subagent, [{"type": "session", "version": 4, "id": "9f8e7d6c", "origin": "subagent", "cwd": "D:\\x"}])
    write_zstd_frames(subagent, dsh_records(("user", "只读静态分析,不要联网"), ("assistant", "分析完成")))
    # An older copy of the same session, in an earlier format version: the same words, stored once.
    write_zstd_frames(session.parent / "session.v3.jsonl.zstd", [{"type": "session", "version": 3, "id": "session-0a1b2c3d"}])
    write_zstd_frames(session.parent / "session.v3.jsonl.zstd", said)
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "windows") == 0
    assert run(env, "report-agent", "--name", "DeepSeek Harness", "--sessions", str(env.sessions),
               "--glob", "**/session*.jsonl.zstd", "--format-json", json.dumps(DSH_FORMAT)) == 0
    sync(env)
    assert stored(env) == [("user", "帮我把这两个软件拆包完整研究并生成详细的报告"), ("assistant", "先核对文件在不在,再拆包。")]
    server = sqlite3.connect(env.data_dir / "server.db")
    assert server.execute("SELECT DISTINCT session_id FROM segments").fetchall() == [("session-0a1b2c3d",)]
    assert server.execute("SELECT cwd FROM sessions").fetchone()[0] == "D:/work/demo"
    assert server.execute("SELECT ts FROM segments ORDER BY id LIMIT 1").fetchone()[0] == "2026-11-20T16:09:01.956Z"

    # Nothing new: the file is not read again. A frame still being written is left for next time.
    assert sync(env)[0].files_read == 0
    write_zstd_frames(session, dsh_records(("user", "报告写成中文")))
    last = zstd_frames(list(dsh_records(("assistant", "好的,写成中文。")))[:1])
    with session.open("ab") as handle:
        handle.write(last[:-5])
    sync(env)
    assert [text for _, text in stored(env)] == [
        "帮我把这两个软件拆包完整研究并生成详细的报告", "先核对文件在不在,再拆包。", "报告写成中文"]

    # The frame is finished: reading carries on mid-file, in the session the file named at its top.
    with session.open("ab") as handle:
        handle.write(last[-5:])
    sync(env)
    assert stored(env)[-1] == ("assistant", "好的,写成中文。")
    assert server.execute("SELECT DISTINCT session_id FROM segments").fetchall() == [("session-0a1b2c3d",)]

    # A reinstalled client resumes from what the server has, positions counting the text, not the file.
    state = State(env.home)
    state.progress.clear()
    state.save_progress()
    sync(env)
    assert len(stored(env)) == 4
    server.close()


def test_compressed_files_need_nothing_installed_and_later_rounds_decode_only_new_frames(env, monkeypatch):
    pytest.importorskip("zstandard")
    from tl_client import zstd

    decoded = []

    def built_in(frame):
        decoded.append(frame)
        return zstd.decode_frame(frame)

    monkeypatch.setattr(zstd, "_decompress", built_in)  # as on a Python with no zstd of its own
    session = env.sessions / "s" / "session.v4.jsonl.zstd"
    write_zstd_frames(session, [{"type": "session", "id": "s-1", "cwd": "/w"}])
    write_zstd_frames(session, dsh_records(("user", "你好"), ("assistant", "你好,要做什么?")))
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "windows") == 0
    assert run(env, "report-agent", "--name", "DeepSeek Harness", "--sessions", str(env.sessions),
               "--glob", "**/*.zstd", "--format-json", json.dumps(DSH_FORMAT)) == 0
    sync(env)
    assert stored(env) == [("user", "你好"), ("assistant", "你好,要做什么?")]
    assert len(decoded) >= 5  # every frame (and the first ones again, for the session's folder)

    decoded.clear()
    write_zstd_frames(session, dsh_records(("user", "写个周报")))
    sync(env)
    assert stored(env)[-1] == ("user", "写个周报")
    assert len(decoded) <= 3  # the last frame already read, and the two new ones: not the whole file again
    kept = State(env.home).progress["DeepSeek Harness"]["s/session.v4.jsonl.zstd"]
    assert kept["size"] == session.stat().st_size and kept["frame"][0] > 0

    # A damaged frame stops reading there, without breaking the round for anyone else.
    with session.open("ab") as handle:
        handle.write(b"\x28\xb5\x2f\xfd\x00\x00\x00\x00garbage")
    (result,) = sync(env)
    assert result.files_read == 1 and len(stored(env)) == 3


def test_words_wrapped_by_the_harness_are_kept_and_its_own_summaries_dropped(env):
    session = env.sessions / "p" / "a1.jsonl"
    session.parent.mkdir()
    lines = [
        {"type": "message", "role": "user", "sessionId": "a1", "timestamp": 1793376110253, "content": [{"type": "input_text", "text":
            '<system-reminder data-role="user_context">OS: Windows</system-reminder>\n<user_query>帮我看看这个公众号能不能直接抓</user_query>'}]},
        {"type": "message", "role": "user", "sessionId": "a1", "timestamp": 1793376110300, "content": [{"type": "input_text", "text":
            "<cb_summary>Summary of the conversation so far ...</cb_summary>"}]},
        {"type": "message", "role": "user", "sessionId": "a1", "timestamp": 1793376110400, "content": [{"type": "input_text", "text":
            "Please continue with the conversation based on the summary."}]},
        {"type": "message", "role": "user", "sessionId": "a1", "timestamp": 1793376110500, "content": [{"type": "input_text", "text":
            '<teammate-message teammate_id="team-lead">done</teammate-message>'}]},
    ]
    session.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n", encoding="utf-8")
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "windows") == 0
    spec = {"base": "flat_role_content", "match": {"type": ["message"]}, "unwrap_elements": ["user_query"],
            "runtime_elements": ["cb_summary", "teammate-message"], "runtime_messages": [r"Please continue with the conversation\b.*"]}
    assert run(env, "report-agent", "--name", "WorkBuddy", "--sessions", str(env.sessions), "--format-json", json.dumps(spec)) == 0
    sync(env)
    assert stored(env) == [("user", "帮我看看这个公众号能不能直接抓")]


def test_an_agent_connected_from_now_on_leaves_its_past_behind(env, tmp_path):
    import os
    import time

    path = tmp_path / "state.db"
    db = hermes_like_db(path)
    db.execute("INSERT INTO messages(session_id, role, content, timestamp) VALUES('old', 'user', '只回答 OK', 1789667689.0)")
    db.commit()
    old_file = env.sessions / "old.jsonl"
    append(old_file, user("很久以前的话"))
    os.utime(old_file, (time.time() - 86400, time.time() - 86400))
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "Mac mini") == 0
    spec = {"base": "flat_role_content", "store": "sqlite", "table": "messages", "order": "id", "match": {"role": ["user", "assistant"]}}
    assert run(env, "report-agent", "--name", "Hermes", "--sessions", str(path), "--format-json", json.dumps(spec), "--since", "now") == 0
    assert run(env, "report-agent", "--name", "Claude Code", "--sessions", str(env.sessions),
               "--format", "message_envelope_content_blocks", "--since", "now") == 0
    assert State(env.home).config["agents"]["Hermes"]["since"].endswith("Z")
    sync(env)
    assert stored(env) == []

    db.execute("INSERT INTO messages(session_id, role, content, timestamp) VALUES('new', 'user', '今天开始用 Hermes 写周报', ?)", (time.time() + 5,))
    db.commit()
    record = user("新开的会话")
    record["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 5))
    append(env.sessions / "new.jsonl", record)
    sync(env)
    assert sorted(text for _, text in stored(env)) == ["今天开始用 Hermes 写周报", "新开的会话"]
    with pytest.raises(SystemExit, match="--since"):
        run(env, "report-agent", "--name", "Hermes", "--sessions", str(path), "--format-json", json.dumps(spec), "--since", "yesterday")
    db.close()


def test_compressed_lines_match_the_plain_file_however_the_frames_fall(tmp_path, monkeypatch):
    zstandard = pytest.importorskip("zstandard")
    import random

    from tl_client import sync as sync_module

    monkeypatch.setattr(sync_module, "MAX_LINE_BYTES", 300)
    rng = random.Random(3)
    text = b"".join((("x" * rng.choice([5, 50, 120, 400])) + f"-{n}\n").encode() for n in range(200))
    plain, packed = tmp_path / "plain.jsonl", tmp_path / "packed.jsonl.zstd"
    plain.write_bytes(text + b"half a li")
    cuts = sorted(rng.sample(range(1, len(text)), 40))
    pieces = [text[a:b] for a, b in zip([0] + cuts, cuts + [len(text)])] + [b"half a li"]
    packed.write_bytes(b"".join(zstandard.ZstdCompressor().compress(piece) for piece in pieces))

    expected = list(sync_module.iter_complete_lines(plain, 0))
    marks: list = []
    assert list(sync_module.iter_complete_lines(packed, 0, marks=marks)) == expected
    assert any(line is None for _, _, line in expected)  # oversized lines are stepped over in both
    # Carrying on from any line, starting at the frame the progress names, gives the rest.
    for start, end, _ in expected[::17]:
        resume = sync_module.resume_point((0, 0), marks, end)
        rest = list(sync_module.iter_complete_lines(packed, end, resume=resume))
        assert rest == [line for line in expected if line[0] >= end]


def test_a_server_that_moved_is_found_again_on_the_home_network_and_only_that_server(env, monkeypatch):
    import ipaddress
    from urllib.parse import urlsplit

    from tl_client import discover

    connect(env)
    state = State(env.home)
    port = urlsplit(env.url).port
    here = [ipaddress.IPv4Network("127.0.0.1/32")]
    monkeypatch.setattr(discover, "home_networks", lambda server_url="": here)

    # Another Time Library on the network is listed, but never taken for this computer's server.
    other = create_server(str(env.data_dir.parent / "other-server"), "127.0.0.1", 0)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        found = discover.find_servers(here, (port, other.server_address[1]), state.config["server_id"])
        assert [item["url"] for item in found] == [env.url, f"http://127.0.0.1:{other.server_address[1]}"]
        assert found[0]["server_id"] == state.config["server_id"] != found[1]["server_id"]

        # The router gave the NAS a new address: what the client knew no longer answers.
        state.config["server_url"] = f"http://127.0.0.9:{port}"
        state.save_config()
        assert cli._find_server_again(State(env.home)) == env.url
        assert State(env.home).config["server_url"] == env.url
        assert sync(env) is not None  # and it carries on there

        # Pointed at the other server's port, it does not move there: wrong server.
        state = State(env.home)
        state.config["server_url"] = f"http://127.0.0.9:{other.server_address[1]}"
        state.save_config()
        monkeypatch.setattr(discover, "DEFAULT_PORT", other.server_address[1])
        assert cli._find_server_again(State(env.home)) == ""
    finally:
        other.shutdown()
        other.server_close()
        other.store.close()


def test_pairing_without_an_address_finds_the_one_server_on_the_network(env, monkeypatch, capsys):
    import ipaddress
    from urllib.parse import urlsplit

    from tl_client import discover

    monkeypatch.setattr(discover, "home_networks", lambda server_url="": [ipaddress.IPv4Network("127.0.0.1/32")])
    monkeypatch.setattr(discover, "DEFAULT_PORT", urlsplit(env.url).port)
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--token", token, "--name", "Mac mini") == 0
    assert State(env.home).config["server_url"] == env.url and "found the server at" in capsys.readouterr().out
    assert run(env, "discover") == 0 and "(this computer's server) - current address" in capsys.readouterr().out


def test_where_a_session_was_started_is_kept_and_shown_beside_the_agent(env):
    connect(env)
    append(env.sessions / "p" / "desk.jsonl", dict(user("桌面上开的会话"), sessionId="desk", entrypoint="claude-desktop"))
    append(env.sessions / "p" / "term.jsonl", dict(user("命令行里开的会话"), sessionId="term", entrypoint="cli"))
    sync(env)
    db = sqlite3.connect(env.data_dir / "server.db")
    assert dict(db.execute("SELECT session_id, surface FROM sessions").fetchall()) == {"desk": "claude-desktop", "term": "cli"}

    # Sessions sent before surfaces were: reported once, from the files' first lines.
    db.execute("UPDATE sessions SET surface = ''")
    db.commit()
    state = State(env.home)
    state.config["agents"]["Claude Code"].pop("surfaces_reported", None)
    state.save_config()
    sync(env)
    assert dict(db.execute("SELECT session_id, surface FROM sessions").fetchall()) == {"desk": "claude-desktop", "term": "cli"}
    db.close()

    from tl_server.store import surface_label
    assert [surface_label(word) for word in ("claude-desktop", "cli", "sdk-ts", "claude-vscode", "", "kiro")] == [
        "桌面", "命令行", "SDK", "编辑器", "", "kiro"]


def test_an_agent_reports_only_what_changed_and_the_rest_stays(env):
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "windows") == 0
    spec = {"base": "flat_role_content", "match": {"type": ["message"]}, "unwrap_elements": ["user_query"]}
    assert run(env, "report-agent", "--name", "WorkBuddy", "--sessions", str(env.sessions), "--format-json", json.dumps(spec)) == 0

    def capabilities():
        (device,) = env.admin._call("GET", "/api/v1/admin/devices")["devices"]
        return {agent["name"]: agent["capabilities"] for agent in device["agents"]}["WorkBuddy"]

    assert capabilities() == {}  # registered for collection; nothing said yet about what it connected
    assert run(env, "report-agent", "--name", "WorkBuddy", "--capability", "mcp=true", "--capability", "skill=true",
               "--capability", "preflight=true") == 0
    assert capabilities() == {"mcp": True, "skill": True, "preflight": True}
    agent = State(env.home).config["agents"]["WorkBuddy"]
    assert (agent["sessions_root"], agent["format"], agent["glob"]) == (str(env.sessions), spec, "**/*.jsonl")

    assert run(env, "report-agent", "--name", "WorkBuddy", "--since", "now") == 0  # says nothing about capabilities
    assert capabilities() == {"mcp": True, "skill": True, "preflight": True}
    with pytest.raises(SystemExit, match="--sessions"):
        run(env, "report-agent", "--name", "NewAgent")


def test_the_search_for_the_server_never_hangs_on_an_address_that_takes_the_call_and_says_nothing(env, monkeypatch):
    import ipaddress
    import socket
    import time as clock
    from urllib.parse import urlsplit

    from tl_client import discover

    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(8)
    held = []

    def take_calls():
        try:
            while True:
                held.append(silent.accept())  # takes the call, never answers
        except OSError:
            pass  # closed at the end of the test

    threading.Thread(target=take_calls, daemon=True).start()
    monkeypatch.setattr(discover, "HEALTH_TIMEOUT", 0.5)
    monkeypatch.setattr(discover, "SEARCH_SECONDS", 3.0)
    started = clock.monotonic()
    found = discover.find_servers([ipaddress.IPv4Network("127.0.0.1/32")],
                                  (silent.getsockname()[1], urlsplit(env.url).port))
    assert clock.monotonic() - started < 4.0
    assert [item["url"] for item in found] == [env.url]
    silent.close()
