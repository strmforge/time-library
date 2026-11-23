"""Proof: the nightly checkup, recall measured, and memory switched on and off."""

from __future__ import annotations

import json

from test_distill import fake, lab, memory, reply  # noqa: F401  (fixtures)
from tl_server import doctor as doctor_module

SAID = [("服务端放在 NAS 的 Docker 应用层,不要装进系统底层", "decision"), ("回答问题的时候先给结论,再展开讲细节和理由", "preference"),
        ("每次发版之前都要把全部测试跑完,一个都不能跳过", "lesson")]


def three_memories(lab):
    lab.assign(lab.source())
    lab.say("s1", *[("user", text) for text, _ in SAID])
    lab.fake.replies.append(reply(*[memory(f"用户定下:{text}", (n, text), kind=kind) for n, (text, kind) in enumerate(SAID, start=1)]))
    lab.run()
    return {m["statement"]: m["id"] for m in lab.call("GET", "/api/v1/admin/memories")[1]["memories"]}


def questions(*texts):
    return json.dumps({"questions": [{"n": n, "q": text} for n, text in enumerate(texts, start=1)]}, ensure_ascii=False)


def numbered(key, field, values):
    return json.dumps({key: [{"n": n, field: value} for n, value in enumerate(values, start=1)]}, ensure_ascii=False)


def checkup(lab):
    assert lab.call("POST", "/api/v1/admin/doctor/run", {})[0] == 200
    lab.server.doctor.wait()
    return lab.call("GET", "/api/v1/admin/doctor")[1]["checkup"]


def test_the_checkup_says_what_is_sound_and_measures_recall(lab):
    ids = three_memories(lab)
    lab.fake.replies.append(questions("服务端装在 NAS 哪一层", "回答时先说什么", "发版之前要做什么"))
    report = checkup(lab)
    checks = {check["key"]: check for check in report["checks"]}
    assert checks["evidence"]["status"] == "ok" and "3 条有效记忆的原话都能逐字找回" in checks["evidence"]["label"]
    assert checks["vectors"]["status"] == "warn"  # recall by meaning is off on this server
    assert report["probe"]["questions"] == 3 and checks["recall"]["label"].startswith("召回抽测 3 题")
    assert [check["status"] for check in report["checks"]] == sorted(
        (check["status"] for check in report["checks"]), key=lambda status: {"bad": 0, "warn": 1, "ok": 2}[status])

    # A conversation changed under a memory: its words can no longer be found.
    with lab.distiller._store._tx() as db:
        db.execute("UPDATE segments SET text = '被改掉了' WHERE text = ?", (SAID[0][0],))
    report = checkup(lab)
    assert report["worst"] == "bad" and report["checks"][0]["key"] == "evidence"
    assert report["checks"][0]["examples"] == [ids["用户定下:" + SAID[0][0]]]
    assert lab.call("GET", "/api/v1/admin/doctor")[1]["probes"] == 3  # the questions are written once


def test_memory_on_and_off_is_measured_on_the_owners_own_questions(lab):
    three_memories(lab)
    lab.fake.replies += [
        questions("服务端装在 NAS 哪一层", "回答时先说什么", "发版之前要做什么"),
        numbered("answers", "a", ["不知道", "不知道", "先测试吧"]),           # without memory
        numbered("answers", "a", ["Docker 应用层", "先给结论", "跑完全部测试"]),  # with what recall hands it
        numbered("verdicts", "v", ["unknown", "unknown", "right"]),
        numbered("verdicts", "v", ["right", "right", "right"]),
    ]
    assert lab.call("POST", "/api/v1/admin/doctor/compare", {"questions": 5})[0] == 200
    lab.server.doctor.wait()
    result = lab.call("GET", "/api/v1/admin/doctor")[1]["compare"]
    assert (result["status"], result["questions"], result["off_right"], result["on_right"]) == ("done", 3, 1, 3)
    assert result["found"] >= 1 and result["details"][0]["question"]
    asked = [entry[3]["input"] for entry in lab.fake.seen if entry[0] == "POST"]
    with_memory = next(prompt for prompt in asked if "记忆:" in str(prompt))
    assert "用户定下" in str(with_memory)  # the answers with memory were given what recall found
    assert lab.call("POST", "/api/v1/admin/doctor/compare", {"questions": 1})[0] == 400
    # The look-ups were the server's own: nothing was lent to an agent.
    assert lab.call("GET", f"/api/v1/admin/memories/{result['details'][0]['memory_id']}")[1]["lent"] == 0


def test_the_checkup_runs_once_a_night(lab, monkeypatch):
    import time as clock

    from tl_server import distill

    three_memories(lab)
    lab.fake.reply_text = questions("一", "二", "三")
    now = clock.localtime(lab.distiller._store._clock())
    monkeypatch.setattr(distill, "NIGHTLY_HOUR", (now.tm_hour + 12) % 24)
    assert lab.server.doctor.tick() == ""
    monkeypatch.setattr(distill, "NIGHTLY_HOUR", now.tm_hour)
    assert lab.server.doctor.tick() == "nightly"
    lab.server.doctor.wait()
    assert lab.server.doctor.tick() == ""
    assert doctor_module.Doctor(lab.distiller._store, lab.distiller, lab.server.recall).tick() == ""


def test_a_memory_shows_its_history(lab):
    ids = three_memories(lab)
    memory_id = ids["用户定下:" + SAID[1][0]]
    lab.device("POST", "/api/v1/recall", {"query": "回答先给结论", "agent": "Codex"})
    lab.server.recall.flush()
    history = lab.call("GET", f"/api/v1/admin/memories/{memory_id}")[1]["history"]
    assert history["first_said"].startswith("2026-11-16") and history["conversations"] == 1
    assert history["borrowers"] == {"Codex": 1}
