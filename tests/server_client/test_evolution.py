"""Evolution: memories replaced by newer ones, judged wrong, drawn up into experience."""

from __future__ import annotations

import json

from test_distill import fake, lab, memory, reply  # noqa: F401  (fixtures)
from tl_server import evolution


def evolve(lab):
    status, answer = lab.call("POST", "/api/v1/admin/evolution/run", {})
    assert status == 200, answer
    lab.evolution.wait()
    return lab.call("GET", "/api/v1/admin/evolution")[1]


def ids_by_statement(lab, **params):
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return {m["statement"]: m["id"] for m in lab.call("GET", f"/api/v1/admin/memories?{query}")[1]["memories"]}


def models(lab):
    source = lab.source()
    lab.assign(source)
    lab.assign(source, slot="reflect")


OLD = "向量索引使用 Granite 模型 v17 版本"
NEW = "向量索引使用 Granite 模型 v18 版本"


def test_a_newer_memory_that_changes_a_detail_replaces_the_older_one_and_can_be_taken_back(lab):
    models(lab)
    lab.say("s1", ("user", OLD), ts="2026-07-10T08:00:00Z")
    lab.fake.replies.append(reply(memory(OLD, (1, OLD))))
    lab.run()
    lab.say("s2", ("user", NEW), ts="2026-11-20T08:00:00Z")
    lab.fake.replies.append(reply(memory(NEW, (1, NEW))))
    lab.run()
    ids = ids_by_statement(lab)
    assert set(ids) == {OLD, NEW}  # not folded: they name different versions

    lab.fake.replies.append(json.dumps({"pairs": [{"n": 1, "verdict": "replaces", "reason": "版本从 v17 换成了 v18"}]}, ensure_ascii=False))
    status = evolve(lab)
    assert status["runs"][0]["status"] == "done" and status["runs"][0]["replaced"] == 1 and status["waiting_pairs"] == 0
    prompt = lab.fake.seen[-1][3]["input"]
    assert prompt.index("2026-07-10") < prompt.index("2026-11-20")  # older first, by when it was said

    assert ids_by_statement(lab) == {NEW: ids[NEW]}
    assert ids_by_statement(lab, shelf="corrected") == {OLD: ids[OLD]}
    found = lab.device("POST", "/api/v1/recall", {"query": "Granite 向量索引"})[1]["memories"]
    assert [m["id"] for m in found] == [ids[NEW]]
    source = lab.device("GET", f"/api/v1/memories/{ids[OLD]}/source")[1]
    assert source["status"] == "superseded" and source["replaced_by"] == {"id": ids[NEW], "reason": "版本从 v17 换成了 v18"}
    (link,) = lab.call("GET", f"/api/v1/admin/memories/{ids[OLD]}")[1]["links"]["replaced_by"]
    assert link["id"] == ids[NEW] and link["reason"] == "版本从 v17 换成了 v18"
    assert lab.call("POST", f"/api/v1/admin/memories/{ids[OLD]}/restore", {})[0] == 409  # taken back through the link

    assert lab.call("POST", f"/api/v1/admin/links/{link['link_id']}/undo", {})[0] == 200
    assert set(ids_by_statement(lab)) == {OLD, NEW}
    assert lab.call("POST", f"/api/v1/admin/links/{link['link_id']}/undo", {})[0] == 409


def test_a_pair_judged_the_same_is_folded_and_one_judged_both_stays(lab):
    models(lab)
    for session, text, ts in (("s1", OLD, "2026-07-10T08:00:00Z"), ("s2", NEW, "2026-11-20T08:00:00Z")):
        lab.say(session, ("user", text), ts=ts)
        lab.fake.replies.append(reply(memory(text, (1, text))))
        lab.run()
    lab.fake.replies.append(json.dumps({"pairs": [{"n": 1, "verdict": "same", "reason": "说的是同一件事"}]}, ensure_ascii=False))
    assert evolve(lab)["runs"][0]["folded"] == 1
    assert list(ids_by_statement(lab)) == [OLD]
    assert list(ids_by_statement(lab, status="folded")) == [NEW]


def test_memories_judged_misleading_leave_recall_until_the_owner_keeps_them(lab):
    models(lab)
    lab.say("s1", ("user", "服务端放在 NAS 上"))
    lab.fake.replies.append(reply(memory("服务端部署在 NAS", (1, "服务端放在 NAS 上"))))
    lab.run()
    (memory_id,) = ids_by_statement(lab).values()
    for _ in range(2):
        assert lab.device("POST", "/api/v1/returns", {"returns": [{"memory_id": memory_id, "outcome": "misleading", "note": "已经搬走了"}]})[0] == 200
    assert evolve(lab)["runs"][0]["judged"] == 1
    assert ids_by_statement(lab, shelf="corrected") == {"服务端部署在 NAS": memory_id}
    detail = lab.call("GET", f"/api/v1/admin/memories/{memory_id}")[1]
    assert detail["status"] == "expired" and detail["expire_reason"] == "returns"
    assert detail["links"]["judged"][0]["reason"] == "借用后 2 次被判误导、0 次被判有用"

    assert lab.call("POST", f"/api/v1/admin/memories/{memory_id}/restore", {})[0] == 200
    assert evolve(lab)["runs"][0]["judged"] == 0  # the owner kept it: the verdicts do not drop it again
    assert ids_by_statement(lab) == {"服务端部署在 NAS": memory_id}


def test_a_project_is_drawn_up_into_experience_and_drawn_up_again_as_it_grows(lab, monkeypatch):
    monkeypatch.setattr(evolution, "DIGEST_MIN", 3)
    monkeypatch.setattr(evolution, "DIGEST_GROWTH", 1)
    models(lab)
    said = [("回答先给结论再展开", "preference"), ("改动前先读设计稿", "lesson"), ("发版前必须跑完全部测试", "decision")]
    for number, (text, kind) in enumerate(said):
        lab.say(f"p{number}", ("user", text), cwd="/work/tl")
        lab.fake.replies.append(reply(memory(text, (1, text), kind=kind)))
        lab.run()
    ids = ids_by_statement(lab)
    lab.fake.replies.append(json.dumps({"experiences": [
        {"title": "先对齐再动手", "statement": "动手前先读设计稿、回答先给结论,省掉来回返工。", "when": "开始一项新改动时",
         "derived_from": [ids["改动前先读设计稿"], ids["回答先给结论再展开"]]},
        {"title": "单条复述", "statement": "发版前跑测试。", "when": "发版", "derived_from": [ids["发版前必须跑完全部测试"]]},
        {"title": "编号不在列表里", "statement": "随便说说。", "when": "从不", "derived_from": [99999, ids["发版前必须跑完全部测试"]]},
    ], "keep": []}, ensure_ascii=False))
    status = evolve(lab)
    assert status["runs"][0]["experiences"] == 1 and status["experiences"] == 1 and status["projects"] == 1
    assert "/work/tl" in lab.fake.seen[-1][3]["input"]

    cards = lab.call("GET", "/api/v1/admin/memories?shelf=experience")[1]["memories"]
    (card,) = cards
    assert (card["title"], card["when_to_use"], card["shelf"]) == ("先对齐再动手", "开始一项新改动时", "experience")
    detail = lab.call("GET", f"/api/v1/admin/memories/{card['id']}")[1]
    assert sorted(item["id"] for item in detail["links"]["derived_from"]) == sorted([ids["改动前先读设计稿"], ids["回答先给结论再展开"]])
    assert {e["quote"] for e in detail["evidence"]} == {"改动前先读设计稿", "回答先给结论再展开"}
    drawn = lab.call("GET", f"/api/v1/admin/memories/{ids['改动前先读设计稿']}")[1]["links"]["drawn_into"]
    assert [item["id"] for item in drawn] == [card["id"]]

    found = lab.device("POST", "/api/v1/recall", {"query": "先读设计稿再动手"})[1]["memories"]
    first = found[0]
    assert (first["id"], first["title"], first["when"], first["sources"]) == (card["id"], "先对齐再动手", "开始一项新改动时", 2)
    assert lab.device("GET", f"/api/v1/memories/{card['id']}/source")[1]["derived_from"] == sorted(
        [ids["改动前先读设计稿"], ids["回答先给结论再展开"]])

    # Nothing new: not drawn up again.
    assert evolve(lab)["runs"][0]["groups"] == 0

    # The project grows: drawn up again, and the old card is replaced, not piled up.
    lab.say("p9", ("user", "提交前先自查一遍改动"), cwd="/work/tl")
    lab.fake.replies.append(reply(memory("提交前先自查一遍改动", (1, "提交前先自查一遍改动"), kind="lesson")))
    lab.run()
    ids = ids_by_statement(lab)
    lab.fake.replies.append(json.dumps({"experiences": [
        {"title": "动手前对齐,提交前自查", "statement": "先读设计稿再改,提交前自查一遍。", "when": "开始或提交一项改动时",
         "derived_from": [ids["改动前先读设计稿"], ids["提交前先自查一遍改动"]]}], "keep": []}, ensure_ascii=False))
    assert evolve(lab)["runs"][0]["experiences"] == 1
    (now,) = lab.call("GET", "/api/v1/admin/memories?shelf=experience")[1]["memories"]
    assert now["title"] == "动手前对齐,提交前自查"
    old = lab.call("GET", f"/api/v1/admin/memories/{card['id']}")[1]
    assert old["status"] == "superseded" and old["links"]["replaced_by"][0]["id"] == now["id"]


def test_evolution_needs_the_deep_slot(lab):
    lab.assign(lab.source())
    assert lab.call("POST", "/api/v1/admin/evolution/run", {})[0] == 409
    assert lab.call("GET", "/api/v1/admin/evolution")[1]["has_model"] is False


def test_a_trial_run_can_be_capped(lab):
    models(lab)
    for session, text, ts in (("s1", OLD, "2026-07-10T08:00:00Z"), ("s2", NEW, "2026-11-20T08:00:00Z")):
        lab.say(session, ("user", text), ts=ts)
        lab.fake.replies.append(reply(memory(text, (1, text))))
        lab.run()
    asked = len(lab.fake.seen)
    assert lab.call("POST", "/api/v1/admin/evolution/run", {"pairs": 0, "groups": 0})[0] == 200
    lab.evolution.wait()
    status = lab.call("GET", "/api/v1/admin/evolution")[1]
    assert status["runs"][0]["reviewed"] == 0 and status["waiting_pairs"] == 1 and len(lab.fake.seen) == asked
    assert lab.call("POST", "/api/v1/admin/evolution/run", {"pairs": -1})[0] == 400


def test_the_nightly_run_happens_once_a_night_and_never_on_a_daytime_restart(lab, monkeypatch):
    import time as clock

    from tl_server import distill

    models(lab)
    store = lab.distiller._store
    now = clock.localtime(store._clock())
    monkeypatch.setattr(distill, "NIGHTLY_HOUR", (now.tm_hour + 12) % 24)
    assert lab.evolution.tick() == ""  # the middle of the day for this server: nothing starts

    monkeypatch.setattr(distill, "NIGHTLY_HOUR", now.tm_hour)
    assert lab.evolution.tick() == "nightly"
    lab.evolution.wait()
    assert lab.evolution.tick() == ""
    # A restart forgets nothing: the run is on record.
    fresh = evolution.Evolution(store, lab.distiller)
    assert fresh.tick() == ""


def test_a_run_cut_off_by_a_restart_is_marked_so(lab):
    store = lab.distiller._store
    with store._tx() as db:
        db.execute("INSERT INTO evolution_runs(trigger, started_at, status) VALUES('nightly', 0, 'running')")
    evolution.Evolution(store, lab.distiller)
    with store._lock:
        assert store._db.execute("SELECT status FROM evolution_runs").fetchone()[0] == "interrupted"
