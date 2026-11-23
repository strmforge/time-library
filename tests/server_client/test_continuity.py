"""A new window, and the user only says "continue": it is handed where the work was left."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

from test_distill import fake, lab  # noqa: F401  (fixtures)
from tl_server import continuity as module
from tl_server.continuity import _checked, asks_to_continue


def stamp(seconds_ago):
    return datetime.fromtimestamp(time.time() - seconds_ago, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def desk(lab):
    """Yesterday in D:/work/novel with one agent; something else elsewhere."""
    lab.say("s-old", ("user", "把第一卷的大纲列出来"), ("assistant", "好,列了十二章。"), ts=stamp(3 * 86400), cwd="D:/work/novel")
    lab.say("s-last", ("user", "第三章的结尾改成开放式"), ("assistant", "改好了,存在 ch03.md。下一步:第四章开头要接上雨夜。"),
            ("user", "第四章先写八百字"), ("assistant", "写了八百二十字,还没送审。等你定要不要保留旁白。"), ("user", "可以"), ts=stamp(86400), cwd="D:/work/novel")
    lab.say("s-else", ("user", "给路由器换个端口"), ("assistant", "换成 18443 了"), ts=stamp(3600), cwd="D:/work/router")

    def hook(prompt, session="new-window", folder="D:/work/novel", agent="Claude Code"):
        status, body = lab.device("POST", "/api/v1/recall", {"query": prompt, "mode": "preflight", "agent": agent, "folder": folder, "session": session})
        assert status == 200, body
        return (body.get("continue") or {}).get("text", "")

    lab.hook = hook
    return lab


def test_what_asks_to_continue():
    for prompt in ("继续", "继续吧", "接着做", "下一步做什么", "做到哪了", "这个项目还剩哪些没做", "然后呢", "continue", "What's next?", "where were we"):
        assert asks_to_continue(prompt), prompt
    for prompt in ("", "好的", "帮我写一个快速排序", "把这段继续扩写成两千字,人物的动机要更清楚一些,结尾留一个悬念给下一章"):
        assert not asks_to_continue(prompt), prompt


def test_a_new_window_that_says_continue_is_handed_where_it_was_left(desk):
    text = desk.hook("继续")
    assert "第四章先写八百字" in text and "等你定要不要保留旁白" in text and "开头:第三章的结尾改成开放式" in text
    assert "更早:" in text and "把第一卷的大纲列出来" in text and "turn_id=" in text
    assert "用户最后说:「可以」" in text  # a bare yes, after what it was said to
    assert "18443" not in text and len(text) <= module.PACK_CHARS  # another project's is not mixed in
    assert desk.hook("继续") == ""  # once in a window
    assert desk.hook("继续", session="another-window") != ""
    assert desk.hook("帮我看看这段代码哪里不对", session="third") == ""


def test_in_the_middle_of_a_conversation_nothing_is_handed_over(desk, monkeypatch):
    monkeypatch.setattr(module, "KNOWN_SECONDS", -5)  # what was just uploaded counts as said before
    assert desk.hook("继续", session="s-last") == ""
    assert desk.hook("继续", session="never-seen") != ""


def test_a_window_that_cannot_be_told_apart_gets_it_once_in_a_while(desk):
    assert desk.hook("继续", session="") and desk.hook("下一步", session="") == ""
    assert desk.hook("继续", session="", folder="D:/work/router")  # another project


def test_a_window_whose_folder_says_nothing_gets_this_agents_last_conversation_and_is_told_so(desk):
    text = desk.hook("继续", folder="C:/Users/me")
    assert "认不出是哪个项目" in text and "18443" in text
    assert desk.hook("继续", folder="D:/work/never-used") == ""  # a folder of its own with nothing in it: nothing to hand over


def test_this_very_window_is_not_where_it_was_left(desk):
    desk.say("s-now", ("user", "继续"), ts=stamp(5), cwd="D:/work/novel")
    assert "第四章先写八百字" in desk.hook("继续", session="")


def test_the_tool_and_the_catalog_say_it_too(desk):
    status, body = desk.device("POST", "/api/v1/continue", {"agent": "Codex", "folder": "D:/work/novel/src"})
    assert status == 200 and "第四章先写八百字" in body["continue"]["text"]
    assert desk.device("POST", "/api/v1/continue", {"agent": "Codex", "folder": "D:/work/empty"})[1]["continue"] is None
    desk.device("POST", "/api/v1/projects/declare", {"folder": "D:/work/novel", "project": "小说", "agent": "Codex"})
    catalog = desk.device("GET", "/api/v1/catalog?folder=D:/work/novel")[1]["text"]
    assert "上次在这里:" in catalog and "time_library_continue" in catalog


def test_decisions_of_the_last_weeks_come_with_it(desk):
    with desk.distiller._store._tx() as db:
        agent_id = db.execute("SELECT id FROM agents LIMIT 1").fetchone()[0]
        for statement, session, day in (("旁白全部删掉", "s-last", stamp(86400)), ("端口定为 18443", "s-else", stamp(3600)), ("很久以前定的事", "s-old", "2020-01-01T00:00:00Z")):
            db.execute("INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at, said_at) VALUES(?,?,'decision',?,?,0,?)",
                       (statement, statement, agent_id, session, day))
    text = desk.hook("继续")
    assert "最近定下的:" in text and "旁白全部删掉" in text and "端口定为" not in text and "很久以前" not in text


# ---- notes of conversations that went quiet -----------------------------------------------------


def ids(lab, session):
    with lab.distiller._store.reading() as db:
        return [row["id"] for row in db.execute("SELECT id FROM segments WHERE session_id = ? ORDER BY id", (session,))]


def note_of(*turns):
    third, fourth, written = turns
    return json.dumps({
        "goal": {"text": "写完第四章开头", "turn": fourth, "quote": "第四章先写八百字"},
        "done": [{"text": "第三章结尾改好", "turn": written - 2, "quote": "改好了,存在 ch03.md"}, {"text": "编出来的", "turn": third, "quote": "对话里没有这句"}],
        "left": [{"text": "送审", "turn": written, "quote": "还没送审"}], "blocked": [{"text": "要不要保留旁白", "turn": 999999, "quote": "保留旁白"}],
        "next": {"text": "定旁白去留", "turn": written, "quote": "等你定要不要保留旁白"}}, ensure_ascii=False)


def test_a_quiet_conversation_gets_a_note_whose_lines_quote_their_turns(desk, monkeypatch):
    monkeypatch.setattr(module, "NOTE_WITHIN", 2 * 86400)
    assert desk.server.continuity.tick() == 0  # no model yet: nothing is done
    desk.assign(desk.source())
    turns = ids(desk, "s-last")
    monkeypatch.setattr(desk.server.continuity, "_due", lambda: [(_agent(desk), "s-last", 0)])
    desk.fake.replies.append(note_of(turns[0], turns[2], turns[3]))
    assert desk.server.continuity.tick() == 1
    text = desk.hook("继续")
    assert "目标:写完第四章开头(turn_id=" in text and "还剩:送审" in text and "下一步:定旁白去留" in text
    assert "编出来的" not in text and "卡在:" not in text  # a quote that is not in its turn, a turn that was not given
    sent = str(desk.fake.seen[-1][3])
    assert "第三章的结尾改成开放式" in sent and f"[轮次 {turns[2]} 用户]" in sent
    listed = desk.call("GET", "/api/v1/admin/notes")[1]
    assert listed["enabled"] and listed["total"] == 1 and listed["notes"][0]["folder"] == "D:/work/novel"
    assert all(line["quote"] for line in listed["notes"][0]["lines"])
    # The owner sees it, deletes it, and switches it off.
    assert desk.call("POST", f"/api/v1/admin/notes/{listed['notes'][0]['id']}/delete", {})[1]["total"] == 0
    assert desk.call("POST", "/api/v1/admin/notes/switch", {"enabled": False})[1]["enabled"] is False
    assert desk.server.continuity.tick() == 0


def _agent(lab):
    with lab.distiller._store.reading() as db:
        return db.execute("SELECT id FROM agents ORDER BY id LIMIT 1").fetchone()[0]


def test_which_conversations_are_due(desk, monkeypatch):
    due = lambda: [session for _, session, _ in desk.server.continuity._due()]  # noqa: E731
    monkeypatch.setattr(module, "NOTE_USER_TURNS", 1)
    assert due() == ["s-else"] or set(due()) == {"s-else", "s-last"}  # within a day; s-old is too long ago
    desk.say("s-live", ("user", "刚说的第一句"), ("user", "刚说的第二句"), ts=stamp(30), cwd="D:/work/novel")
    assert "s-live" not in due()  # still going on
    desk.say("s-imported", ("user", "导入的一句"), ("user", "导入的第二句"), ts=stamp(7200), origin="import")
    assert "s-imported" not in due()
    monkeypatch.setattr(module, "NOTE_USER_TURNS", 2)
    assert "s-else" not in due()  # a single question needs no note


def test_a_note_that_is_not_json_is_empty_and_not_tried_again_at_once(desk):
    assert _checked("not json", {1: "x"}) == {} and _checked("[]", {1: "x"}) == {}
    assert _checked(json.dumps({"goal": {"text": "a", "turn": "1", "quote": "这几个字"}}), {1: "有这几个字"})["goal"][0]["turn"] == 1


def test_a_long_conversation_is_known_by_what_it_is_about_now(desk):
    desk.say("s-long", ("user", "很久以前开的头:先装环境"), *[("user", f"中间的第 {n} 件事情说明") for n in range(14)], ("user", "现在在做第九章的对白"),
             ("assistant", "第九章对白改完了,共三处。" + "细节说明" * 60 + "下一步等你看旁白。"), ("user", "可以"), ("assistant", "Now the tests:"), ts=stamp(600), cwd="D:/work/novel")
    text = desk.hook("继续")
    assert "最近在说:现在在做第九章的对白" in text and "很久以前开的头" not in text
    assert "助手最近一次完整说:「第九章对白改完了" in text and "下一步等你看旁白" in text and "Now the tests" not in text
