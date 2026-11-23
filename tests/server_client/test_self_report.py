"""An agent describes its own sessions and hook, checks the description on its own files, and is read by it."""

from __future__ import annotations

import json

import pytest

from test_client_sync import env, run, stored, sync  # noqa: F401  (fixtures)
from tl_client import recall as client_recall
from tl_client.state import State

ANTIGRAVITY_LIKE = {
    "name": "brain-transcript", "base": "flat_role_content",
    "match": {"type": ["USER_INPUT", "PLANNER_RESPONSE"]},
    "role": ["source"], "role_map": {"USER_EXPLICIT": "user", "MODEL": "assistant"},
    "content": ["content"], "timestamp": ["created_at"],
    "session_id_from_path": "^([^/]+)/",
    "session_skip_if_equals": {"type": ["SYSTEM_MESSAGE"]},
    "unwrap_elements": ["USER_REQUEST"], "runtime_elements": ["ADDITIONAL_METADATA"],
}
GLOB = "*/.system_generated/logs/transcript_full.jsonl"


def brain(env, conversation, *records):
    path = env.sessions / conversation / ".system_generated" / "logs" / "transcript_full.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def said(source, kind, text, at="2026-11-23T08:00:00Z"):
    return {"source": source, "type": kind, "content": text, "created_at": at}


def lay_out(env):
    brain(env, "c1", said("USER_EXPLICIT", "USER_INPUT", "<USER_REQUEST>把数据迁移接着跑完</USER_REQUEST>"
                                                         "<ADDITIONAL_METADATA>cursor at line 3</ADDITIONAL_METADATA>"),
          said("MODEL", "PLANNER_RESPONSE", "好的,从第 12 批接着迁。"), said("MODEL", "TOOL_CALL", "run_command"))
    brain(env, "c2", said("USER_EXPLICIT", "USER_INPUT", "<USER_REQUEST>换成中文回答</USER_REQUEST>"),
          said("MODEL", "PLANNER_RESPONSE", "好,以后用中文。"))
    brain(env, "sub1", said("SYSTEM", "SYSTEM_MESSAGE", "You are a subagent"),
          said("USER_EXPLICIT", "USER_INPUT", "<USER_REQUEST>主代理派的活</USER_REQUEST>"))


def test_the_check_says_what_is_wrong_and_then_that_the_description_reads_right(env, capsys):
    lay_out(env)
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "windows") == 0
    first_try = {key: value for key, value in ANTIGRAVITY_LIKE.items()
                 if key not in ("role_map", "session_id_from_path", "session_skip_if_equals", "unwrap_elements")}
    assert run(env, "check", "--sessions", str(env.sessions), "--glob", GLOB, "--format-json", json.dumps(first_try)) == 1
    out = capsys.readouterr().out
    assert "USER_EXPLICIT" in out and "role_map" in out  # the speaker words it did not understand
    assert "same session id 'transcript_full'" in out and "session_id_from_path" in out
    assert "no user turns at all" in out

    assert run(env, "check", "--sessions", str(env.sessions), "--glob", GLOB, "--format-json", json.dumps(ANTIGRAVITY_LIKE)) == 0
    out = capsys.readouterr().out
    assert "would collect: 2 user turns, 2 assistant turns, in 2 sessions" in out and "left out as whole sessions" in out
    assert "user: 把数据迁移接着跑完" in out and "looks right" in out

    assert run(env, "report-agent", "--name", "Antigravity", "--sessions", str(env.sessions), "--glob", GLOB,
               "--format-json", json.dumps(ANTIGRAVITY_LIKE)) == 0
    sync(env)
    assert sorted(stored(env)) == sorted([("user", "把数据迁移接着跑完"), ("assistant", "好的,从第 12 批接着迁。"),
                                          ("user", "换成中文回答"), ("assistant", "好,以后用中文。")])
    import sqlite3

    db = sqlite3.connect(env.data_dir / "server.db")
    assert sorted(row[0] for row in db.execute("SELECT DISTINCT session_id FROM segments")) == ["c1", "c2"]
    db.close()
    assert run(env, "check", "--agent", "Antigravity") == 0  # the same check on what was reported


def test_a_session_kept_as_one_json_document_is_read_entry_by_entry(env):
    path = env.sessions / "chats" / "session-2026-11-23.json"
    path.parent.mkdir(parents=True)
    document = {"sessionId": "g1", "messages": [
        {"type": "user", "content": "用中文写提交说明", "timestamp": "2026-11-23T08:00:00Z"},
        {"type": "gemini", "content": "好的,提交说明用中文。", "timestamp": "2026-11-23T08:00:05Z"}]}
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    spec = {"base": "flat_role_content", "store": "json", "records": "messages", "role": ["type"],
            "role_map": {"gemini": "assistant"}, "content": ["content"]}
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "mac") == 0
    assert run(env, "check", "--sessions", str(env.sessions), "--glob", "chats/*.json", "--format-json", json.dumps(spec)) == 0
    assert run(env, "report-agent", "--name", "Gemini", "--sessions", str(env.sessions), "--glob", "chats/*.json",
               "--format-json", json.dumps(spec)) == 0
    sync(env)
    assert stored(env) == [("user", "用中文写提交说明"), ("assistant", "好的,提交说明用中文。")]
    document["messages"].append({"type": "user", "content": "再加一句测试说明", "timestamp": "2026-11-23T08:01:00Z"})  # the tool rewrites the whole file
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    sync(env)
    assert [text for _, text in stored(env)] == ["用中文写提交说明", "好的,提交说明用中文。", "再加一句测试说明"]
    assert sync(env)[0].files_read == 0  # unchanged: not read again


HOOK = {"prompt": ["lastUserInput"], "output": {"injectSteps": [{"systemMessage": {"systemMessage": "{text}"}}]},
        "empty": "{}", "once_per": ["conversationId", "initialNumSteps"]}


class FakeApi:
    def __init__(self):
        self.asked = []

    def recall(self, query, limit=3, mode="search", agent="", folder=""):
        self.asked.append(query)
        self.folder = folder
        return [{"id": 7, "kind": "decision", "statement": "数据迁移从断点接着跑", "evidence": [], "device": "pc", "agent": "Antigravity"}]


def test_a_hook_with_its_own_protocol_needs_no_script_of_its_own(env, monkeypatch, capsys):
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "windows") == 0
    lay_out(env)
    assert run(env, "report-agent", "--name", "Antigravity", "--sessions", str(env.sessions), "--glob", GLOB,
               "--format-json", json.dumps(ANTIGRAVITY_LIKE), "--hook-json", json.dumps(HOOK)) == 0
    sample = json.dumps({"lastUserInput": "<USER_REQUEST>数据迁移跑到哪了</USER_REQUEST><ADDITIONAL_METADATA>x</ADDITIONAL_METADATA>",
                         "conversationId": "c1", "initialNumSteps": 5, "invocationNum": 0})
    assert run(env, "check", "--agent", "Antigravity", "--hook-sample", sample) == 0
    out = capsys.readouterr().out
    assert "would look up: 数据迁移跑到哪了" in out and '"injectSteps"' in out and "when nothing is found: {}" in out

    fake = FakeApi()
    monkeypatch.setattr(client_recall, "_api", lambda state, timeout: fake)
    state = State(env.home)
    printed = json.loads(client_recall.preflight(state, sample.encode("utf-8"), "Antigravity"))
    text = printed["injectSteps"][0]["systemMessage"]["systemMessage"]
    assert text.startswith("<time-library-memory>") and "数据迁移从断点接着跑" in text
    assert fake.asked == ["数据迁移跑到哪了"]  # its own wrappers taken off, as its format says
    # The hook runs on every model call of a turn: the memories are handed over once.
    again = json.loads(sample) | {"invocationNum": 1}
    assert client_recall.preflight(state, json.dumps(again).encode("utf-8"), "Antigravity") == "{}"
    assert len(fake.asked) == 1
    with pytest.raises(SystemExit, match="{text}"):
        run(env, "report-agent", "--name", "Antigravity", "--hook-json", json.dumps({"output": {"x": "no slot"}}))


def test_descriptions_can_be_given_in_a_file(env, tmp_path):
    lay_out(env)
    description = tmp_path / "format.json"
    description.write_text(json.dumps(ANTIGRAVITY_LIKE, ensure_ascii=False), encoding="utf-8-sig")  # as Windows tools write it
    hook = tmp_path / "hook.json"
    hook.write_text(json.dumps(HOOK), encoding="utf-8")
    token = env.admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert run(env, "pair", "--server", env.url, "--token", token, "--name", "windows") == 0
    assert run(env, "check", "--sessions", str(env.sessions), "--glob", GLOB, "--format-json", f"@{description}") == 0
    assert run(env, "report-agent", "--name", "Antigravity", "--sessions", str(env.sessions), "--glob", GLOB,
               "--format-json", f"@{description}", "--hook-json", f"@{hook}") == 0
    assert State(env.home).config["agents"]["Antigravity"]["hook"] == HOOK


def test_records_with_nothing_said_are_not_mistaken_for_words_lost_to_wrappers(env, capsys):
    lay_out(env)
    brain(env, "c1", *[{"source": "MODEL", "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run"}], "created_at": "2026-11-23T08:00:00Z"}
                       for _ in range(30)])
    assert run(env, "check", "--sessions", str(env.sessions), "--glob", GLOB, "--format-json", json.dumps(ANTIGRAVITY_LIKE)) == 0
    out = capsys.readouterr().out
    assert "no_words ×30" in out and "nothing left after removing wrappers" not in out
