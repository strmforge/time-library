"""Answering only from memory: an answer names what it rests on, or it is UNKNOWN."""

from __future__ import annotations

import json

from test_distill import fake, lab, memory, reply  # noqa: F401  (fixtures)
from test_doctor import SAID, three_memories
from tl_client.recall import format_answer


def ask(lab, question, *answers):
    lab.fake.replies += [json.dumps(answer, ensure_ascii=False) for answer in answers]
    status, body = lab.device("POST", "/api/v1/answer", {"question": question, "agent": "Codex"})
    assert status == 200, body
    lab.server.recall.flush()
    return body


def lent(lab, memory_id):
    return lab.call("GET", f"/api/v1/admin/memories/{memory_id}")[1]["lent"]


def test_an_answer_rests_on_memories_it_was_given_and_only_those_are_lent(lab):
    ids = three_memories(lab)
    nas = ids["用户定下:" + SAID[0][0]]
    found = ask(lab, "服务端装在 NAS 的哪一层", {"answer": "装在 NAS 的 Docker 应用层,不装进系统底层", "used": [nas]})
    assert (found["verdict"], found["used"]) == ("answered", [nas]) and "Docker 应用层" in found["answer"]
    assert found["memories"][0]["evidence"][0]["quote"] == SAID[0][0]
    prompt = str(lab.fake.seen[-1][3]["input"])
    assert f"记忆 {nas}" in prompt and SAID[0][0] in prompt  # it was handed the original words
    assert lent(lab, nas) == 1 and all(lent(lab, other) == 0 for other in ids.values() if other != nas)
    text = format_answer(found)
    assert text.startswith("回答:装在 NAS") and f"记忆编号 {nas}" in text


def test_unknown_when_memory_does_not_say_or_the_answer_cannot_be_checked(lab):
    ids = three_memories(lab)
    nas = ids["用户定下:" + SAID[0][0]]
    said_no = ask(lab, "服务端用的是哪个端口", {"answer": "UNKNOWN", "used": [], "unknown_reason": "记忆里没提端口号"})
    assert (said_no["verdict"], said_no["answer"], said_no["unknown_reason"]) == ("unknown", "UNKNOWN", "记忆里没提端口号")
    assert format_answer(said_no).startswith("UNKNOWN:记忆里没提端口号")

    invented = ask(lab, "服务端装在哪", {"answer": "装在系统底层", "used": [nas, 999999]})
    assert invented["verdict"] == "unknown" and "没交给它" in invented["unknown_reason"]
    unsupported = ask(lab, "服务端装在哪", {"answer": "装在 Docker 应用层", "used": []})
    assert unsupported["verdict"] == "unknown" and "依据" in unsupported["unknown_reason"]
    assert all(lent(lab, memory_id) == 0 for memory_id in ids.values())  # nothing rested on them

    calls = len(lab.fake.seen)
    nothing = ask(lab, "量子色动力学的渐近自由")
    assert nothing["verdict"] == "unknown" and len(lab.fake.seen) == calls  # no memory, no model call
    assert lab.device("POST", "/api/v1/answer", {"question": "  "})[0] == 400


def test_a_question_about_several_things_gets_the_parts_memory_says(lab):
    """Asked for three things with one missing, a whole UNKNOWN would withhold the other two."""
    ids = three_memories(lab)
    nas = ids["用户定下:" + SAID[0][0]]
    found = ask(lab, "服务端装在哪一层,用哪个端口", {"answer": "装在 NAS 的 Docker 应用层", "used": [nas], "missing": "记忆里没提端口"})
    assert (found["verdict"], found["missing"]) == ("answered", "记忆里没提端口") and lent(lab, nas) == 1
    text = format_answer(found)
    assert text.startswith("回答:装在 NAS") and "记忆没说到的(别猜,需要就问用户):记忆里没提端口" in text
    assert "缺一件不等于整个答不了" in str(lab.fake.seen[-1][3])  # what the model is told
    plain = ask(lab, "服务端装在哪一层", {"answer": "装在 Docker 应用层", "used": [nas]})
    assert plain["missing"] == "" and "记忆没说到的" not in format_answer(plain)
