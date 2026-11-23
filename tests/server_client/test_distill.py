"""Distillation: memories that carry real quotes, and progress that never repeats."""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from fake_model_server import GOOD_KEY, start_fake_model_server
from tl_server import distill
from tl_server.app import create_server


@pytest.fixture()
def fake():
    httpd = start_fake_model_server()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def lab(tmp_path, fake):
    httpd = create_server(str(tmp_path), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    admin_token = (tmp_path / "admin_token.txt").read_text().strip()

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

    minted = call("POST", "/api/v1/admin/pairing-tokens", {})[1]["pairing_token"]
    paired = call("POST", "/api/v1/pair", {"pairing_token": minted, "device": {"device_uid": "device-uid-0001", "name": "Mac mini"}}, token=None)[1]
    device_token = paired["device_token"]
    agent_id = call("POST", "/api/v1/agents/report", {"agent": {"name": "Claude Code"}}, token=device_token)[1]["agent_id"]
    positions = {"next": 0}

    def say(session, *turns, origin=None, ts="2026-11-16T00:00:00Z", cwd=None, agent=None):
        segments = []
        for role, text in turns:
            position = positions["next"]
            positions["next"] += 1
            segments.append({"segment_uid": f"uid-{position:08d}", "session_id": session, "source_file": f"{session}.jsonl",
                             "position": position, "role": role, "text": text, "ts": ts, **({"cwd": cwd} if cwd else {})})
        body = {"agent_id": agent or agent_id, "segments": segments}
        if origin:
            body["origin"] = origin
        assert call("POST", "/api/v1/ingest", body, token=device_token)[0] == 200

    def source(name="中转", key=GOOD_KEY, protocol="responses"):
        return call("POST", "/api/v1/admin/models/sources",
                    {"name": name, "base_url": fake.base_url, "protocol": protocol, "api_key": key, "model": "alpha-mini"})[1]["id"]

    def run(**body):
        status, reply = call("POST", "/api/v1/admin/distill/run", body)
        assert status == 200, reply
        httpd.distiller.wait()
        return call("GET", "/api/v1/admin/distill")[1]

    lab = type("Lab", (), {})()
    lab.call, lab.say, lab.source, lab.run, lab.fake, lab.distiller = call, say, source, run, fake, httpd.distiller
    lab.device = lambda method, path, body=None: call(method, path, body, token=device_token)
    lab.evolution = httpd.evolution
    lab.server = httpd
    lab.assign = lambda sid, role="main", slot="daily": call("POST", "/api/v1/admin/models/slots", {"slot": slot, "role": role, "source_id": sid})
    lab.status = lambda: call("GET", "/api/v1/admin/distill")[1]
    lab.prompts = lambda: [entry[3]["input"] for entry in fake.seen if entry[0] == "POST" and "对话:" in str(entry[3].get("input", ""))]
    yield lab
    httpd.doctor.shutdown()
    httpd.vectors.disable()
    httpd.evolution.shutdown()
    httpd.distiller.shutdown()
    httpd.shutdown()
    httpd.server_close()
    httpd.store.close()


def reply(*memories) -> str:
    return json.dumps({"memories": list(memories)}, ensure_ascii=False)


def memory(statement, *evidence, kind="decision"):
    return {"statement": statement, "kind": kind, "evidence": [{"n": n, "quote": quote} for n, quote in evidence]}


NAS = "服务端放在 NAS 的飞牛 Docker 应用层,不要装进系统底层"
FREE = "这个不定死，我可以自由搭配"


def test_a_memory_is_kept_only_if_its_quote_is_really_in_the_dialogue(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS), ("assistant", "好的,记下了"), ("user", FREE))
    lab.fake.replies.append(reply(
        memory("忆凡尘服务端部署在 NAS 的飞牛 Docker 应用层", (1, "服务端放在 NAS 的飞牛 Docker 应用层")),
        memory("用户喜欢蓝色界面", (1, "我最喜欢蓝色")),                       # the quote was made up
        memory("模型按任务自由搭配,不写死", (3, "“这个不定死，我可以自由搭配”"), kind="preference"),  # wrapped in quote marks
        memory("段落编号不存在", (9, "这个不定死")),                           # points at nothing
        memory("没有证据的说法"),                                               # no evidence at all
    ))
    status = lab.run()
    last = status["runs"][0]
    assert (last["status"], last["windows"], last["segments"], last["memories"], last["rejected"]) == ("done", 1, 3, 2, 3)
    assert last["input_tokens"] == 7 and last["model"] == "中转 · alpha-mini"
    assert status["pending"] == {"sessions": 0, "segments": 0, "chars": 0} and status["memories"] == {"active": 2, "expired": 0, "folded": 0}

    listing = lab.call("GET", "/api/v1/admin/memories")[1]
    assert [(m["statement"], m["kind"], m["device"], m["agent"]) for m in listing["memories"]] == [
        ("模型按任务自由搭配,不写死", "preference", "Mac mini", "Claude Code"),
        ("忆凡尘服务端部署在 NAS 的飞牛 Docker 应用层", "decision", "Mac mini", "Claude Code"),
    ]
    detail = lab.call("GET", f"/api/v1/admin/memories/{listing['memories'][0]['id']}")[1]
    assert [(e["quote"], e["role"]) for e in detail["evidence"]] == [(FREE, "user")]
    assert detail["evidence"][0]["quote"] in FREE  # stored quote is a real substring, marks stripped


def test_the_prompt_numbers_the_turns_and_carries_the_instructions(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS), ("assistant", "好的"))
    lab.fake.replies.append(reply())
    lab.run()
    sent = [entry[3] for entry in lab.fake.seen if entry[0] == "POST" and "对话:" in str(entry[3].get("input", ""))][0]
    assert sent["input"] == f"对话:\n\n[1] 用户: {NAS}\n\n[2] 助手: 好的"
    assert "逐字复制" in sent["instructions"] and "只输出 JSON" in sent["instructions"]


def test_dialogue_is_never_distilled_twice_and_new_turns_continue_from_where_it_stopped(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS))
    lab.fake.replies.append(reply(memory("服务端在 NAS 上", (1, "服务端放在 NAS"))))
    lab.run()
    assert len(lab.prompts()) == 1

    lab.run()  # nothing new: the model is not called at all
    assert len(lab.prompts()) == 1

    lab.say("s1", ("user", FREE))
    lab.fake.replies.append(reply(memory("模型自由搭配", (1, "我可以自由搭配"))))
    status = lab.run()
    assert lab.prompts()[-1] == f"对话:\n\n[1] 用户: {FREE}"  # only the new turn was sent
    assert status["memories"]["active"] == 2


def test_the_same_memory_proposed_again_is_stored_once(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS))
    lab.say("s2", ("user", "再说一遍:服务端放在 NAS 上"))
    same = memory("服务端在 NAS 上", (1, "服务端放在 NAS"))
    lab.fake.replies += [reply(same), reply(same)]
    status = lab.run()
    assert status["runs"][0]["windows"] == 2 and status["memories"]["active"] == 1


def test_fenced_json_is_accepted_and_an_empty_answer_still_moves_on(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", "你好"))
    lab.say("s2", ("user", NAS))
    lab.fake.replies += ["好的,结果如下:\n```json\n" + reply() + "\n```", "```\n" + reply(memory("服务端在 NAS 上", (1, "服务端放在 NAS"))) + "\n```"]
    status = lab.run()
    assert status["runs"][0]["status"] == "done" and status["pending"]["segments"] == 0 and status["memories"]["active"] == 1


def test_a_conversation_the_model_will_not_answer_properly_is_skipped_and_the_rest_carry_on(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS))
    lab.say("s2", ("user", FREE))
    # s1: not JSON twice (retried once, then skipped); s2: a proper answer.
    lab.fake.replies += ["我觉得没什么好记的", "还是没有 JSON", reply(memory("模型自由搭配", (1, "我可以自由搭配")))]
    status = lab.run()
    last = status["runs"][0]
    assert (last["status"], last["skipped"], last["windows"]) == ("done", 1, 1)
    assert status["pending"]["segments"] == 1 and status["memories"]["active"] == 1  # s1 kept its place
    assert any("只输出 JSON" in prompt for prompt in lab.prompts())  # the retry said what was wrong

    lab.fake.replies.append(reply(memory("服务端在 NAS 上", (1, "服务端放在 NAS"))))
    status = lab.run()
    assert status["runs"][0]["status"] == "done" and status["pending"]["segments"] == 0 and status["memories"]["active"] == 2


def test_when_the_main_model_is_out_of_balance_the_backup_takes_over(lab):
    main, backup = lab.source("主用中转"), lab.source("备用本地", protocol="messages")
    lab.assign(main)
    lab.assign(backup, "backup")
    lab.call("POST", f"/api/v1/admin/models/sources/{main}", {"api_key": "broke-key"})
    lab.say("s1", ("user", NAS))
    lab.fake.replies.append(reply(memory("服务端在 NAS 上", (1, "服务端放在 NAS"))))
    status = lab.run()
    assert status["runs"][0]["status"] == "done" and status["runs"][0]["model"] == "备用本地 · alpha-mini"

    sources = {s["name"]: s for s in lab.call("GET", "/api/v1/admin/models")[1]["sources"]}
    assert (sources["主用中转"]["tested_ok"], sources["主用中转"]["last_error_reason"]) == (False, "quota")

    # Topped up: the next run uses the main model again and clears the mark.
    lab.call("POST", f"/api/v1/admin/models/sources/{main}", {"api_key": GOOD_KEY})
    lab.distiller._models.note_failure(main, distill.ModelError("quota", "余额不足"))
    lab.say("s1", ("user", FREE))
    lab.fake.replies.append(reply())
    status = lab.run()
    assert status["runs"][0]["model"] == "主用中转 · alpha-mini"
    sources = {s["name"]: s for s in lab.call("GET", "/api/v1/admin/models")[1]["sources"]}
    assert (sources["主用中转"]["tested_ok"], sources["主用中转"]["last_error_reason"]) == (True, "")


def test_when_every_model_fails_the_run_stops_with_the_reason_and_resumes_later(lab):
    main = lab.source()
    lab.assign(main)
    lab.call("POST", f"/api/v1/admin/models/sources/{main}", {"api_key": "broke-key"})
    lab.say("s1", ("user", NAS))
    status = lab.run()
    assert (status["runs"][0]["status"], status["runs"][0]["error_reason"]) == ("stopped", "quota")
    assert status["pending"]["segments"] == 1

    lab.call("POST", f"/api/v1/admin/models/sources/{main}", {"api_key": GOOD_KEY})
    lab.fake.replies.append(reply(memory("服务端在 NAS 上", (1, "服务端放在 NAS"))))
    assert lab.run()["pending"]["segments"] == 0


def test_long_conversations_are_read_in_windows_and_a_run_can_be_capped(lab, monkeypatch):
    monkeypatch.setattr(distill, "WINDOW_CHARS", 50)
    lab.assign(lab.source())
    lab.say("s1", *[("user", f"第{index}句话,凑够二十个字符的长度啊啊啊") for index in range(6)])
    lab.fake.reply_text = reply()
    status = lab.run(max_windows=1)
    assert status["runs"][0]["windows"] == 1 and status["pending"]["segments"] == 4
    status = lab.run()
    assert status["runs"][0]["windows"] == 2 and status["pending"]["segments"] == 0
    numbered = [prompt.count("\n\n[") for prompt in lab.prompts()]
    assert numbered == [2, 2, 2]  # each window is numbered from 1 again


def test_the_same_memory_twice_in_one_answer_is_kept_once_with_its_evidence(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS), ("user", FREE))
    lab.fake.replies.append(reply(
        memory("忆凡尘服务端部署在 NAS 的飞牛 Docker 应用层", (1, "飞牛 Docker 应用层")),
        memory("服务端部署在 NAS 飞牛的 Docker 应用层,不进系统底层", (1, "服务端放在 NAS 的飞牛 Docker 应用层"), (2, "我可以自由搭配")),
    ))
    status = lab.run()
    assert status["memories"]["active"] == 1 and status["runs"][0]["merged"] == 1
    (only,) = lab.call("GET", "/api/v1/admin/memories")[1]["memories"]
    quotes = [e["quote"] for e in lab.call("GET", f"/api/v1/admin/memories/{only['id']}")[1]["evidence"]]
    assert quotes == ["飞牛 Docker 应用层", "我可以自由搭配"]  # the contained quote is not repeated


def test_duplicates_already_stored_are_folded_when_the_server_starts(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS), ("user", FREE))
    lab.fake.replies.append(reply(
        memory("忆凡尘服务端部署在 NAS 的飞牛 Docker 应用层", (1, "服务端放在 NAS 的飞牛 Docker 应用层")),
        memory("模型按任务自由搭配", (2, "我可以自由搭配")),
    ))
    lab.run()
    store = lab.distiller._store
    with store._tx() as db:
        agent_id, session_id = db.execute("SELECT agent_id, session_id FROM memories LIMIT 1").fetchone()
        first_segment = db.execute("SELECT MIN(id) FROM segments").fetchone()[0]
        # A paraphrase of the first memory, resting on the same words (as from distilling a copy) ...
        twin = db.execute(
            "INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at, recall_count) VALUES('t', ?, 'decision', ?, ?, 0, 3)",
            ("服务端装在 NAS 飞牛 Docker 应用层而不是系统底层", agent_id, session_id),
        ).lastrowid
        db.execute("INSERT INTO memory_evidence(memory_id, segment_id, quote) VALUES(?, ?, '不要装进系统底层')", (twin, first_segment))
        db.execute("INSERT INTO memory_evidence(memory_id, segment_id, quote) VALUES(?, ?, '服务端放在 NAS 的飞牛 Docker 应用层')", (twin, first_segment))
        # ... and a different memory that cites the same message for another point.
        other = db.execute(
            "INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at) VALUES('o', '升级时不能被飞牛抹掉', 'lesson', ?, ?, 0)",
            (agent_id, session_id),
        ).lastrowid
        db.execute("INSERT INTO memory_evidence(memory_id, segment_id, quote) VALUES(?, ?, '服务端放在 NAS 的飞牛 Docker 应用层')", (other, first_segment))

    folded = lab.distiller.merge_duplicates()  # what runs when the server starts
    assert [removed for _, removed in folded] == [twin]
    listing = {m["statement"]: m for m in lab.call("GET", "/api/v1/admin/memories")[1]["memories"]}
    assert set(listing) == {"忆凡尘服务端部署在 NAS 的飞牛 Docker 应用层", "模型按任务自由搭配", "升级时不能被飞牛抹掉"}
    kept = listing["忆凡尘服务端部署在 NAS 的飞牛 Docker 应用层"]
    assert kept["recall_count"] == 3
    quotes = [e["quote"] for e in lab.call("GET", f"/api/v1/admin/memories/{kept['id']}")[1]["evidence"]]
    assert quotes == ["服务端放在 NAS 的飞牛 Docker 应用层", "不要装进系统底层"]
    with store._lock:
        assert store._db.execute("SELECT folded_statement FROM memory_folds").fetchone()[0] == "服务端装在 NAS 飞牛 Docker 应用层而不是系统底层"
    assert lab.distiller.merge_duplicates() == []  # nothing left to fold


def test_a_busy_endpoint_is_tried_again_before_the_round_gives_up(lab, monkeypatch):
    monkeypatch.setattr(distill, "RETRY_DELAYS", (0, 0))
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS))
    lab.fake.fail_next = 2  # busy twice, then fine
    lab.fake.replies.append(reply(memory("服务端在 NAS 上", (1, "服务端放在 NAS"))))
    status = lab.run()
    assert status["runs"][0]["status"] == "done" and status["memories"]["active"] == 1

    lab.say("s1", ("user", FREE))
    lab.fake.fail_next = 3  # busy every time: give up after the retries, keep the place
    status = lab.run()
    assert (status["runs"][0]["status"], status["runs"][0]["error_reason"]) == ("stopped", "http")
    assert status["pending"]["segments"] == 1
    lab.fake.fail_next = 0


def test_after_topping_up_the_server_carries_on_by_itself(lab, monkeypatch):
    main = lab.source()
    lab.assign(main)
    lab.call("POST", f"/api/v1/admin/models/sources/{main}", {"api_key": "broke-key"})
    lab.say("s1", ("user", NAS))
    assert lab.run()["runs"][0]["error_reason"] == "quota"

    monkeypatch.setattr(distill, "NIGHTLY_HOUR", -1)  # not night time
    assert lab.distiller.tick() == ""  # too soon to try again
    monkeypatch.setattr(distill, "RESUME_AFTER_SECONDS", 0)
    lab.call("POST", f"/api/v1/admin/models/sources/{main}", {"api_key": GOOD_KEY})  # topped up
    lab.fake.replies.append(reply(memory("服务端在 NAS 上", (1, "服务端放在 NAS"))))
    assert lab.distiller.tick() == "resume"
    lab.distiller.wait()
    status = lab.call("GET", "/api/v1/admin/distill")[1]
    assert (status["runs"][0]["trigger"], status["runs"][0]["status"]) == ("resume", "done")
    assert status["pending"]["segments"] == 0 and lab.distiller.tick() == ""


def test_the_nightly_round_runs_once_a_night(lab, monkeypatch):
    import time as clock

    lab.assign(lab.source())
    lab.say("s1", ("user", NAS))
    lab.fake.reply_text = reply()
    monkeypatch.setattr(distill, "NIGHTLY_HOUR", clock.localtime().tm_hour)
    assert lab.distiller.tick() == "nightly"
    lab.distiller.wait()
    lab.say("s1", ("user", FREE))
    assert lab.distiller.tick() == ""  # already ran tonight


def test_running_needs_a_model_and_the_admin(lab):
    status, body = lab.call("POST", "/api/v1/admin/distill/run", {})
    assert (status, body["error"]) == (409, "no_model")
    assert lab.call("GET", "/api/v1/admin/distill", token=None)[0] == 401
    assert lab.call("GET", "/api/v1/admin/memories", token=None)[0] == 401
    assert lab.call("POST", "/api/v1/admin/distill/run", {"max_windows": 0})[0] == 400
    assert lab.call("GET", "/api/v1/admin/distill")[1]["has_model"] is False


def test_searching_expiring_restoring_and_clearing_memories(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS), ("user", FREE))
    lab.fake.replies.append(reply(
        memory("服务端部署在 NAS 的 Docker 应用层", (1, "飞牛 Docker 应用层")),
        memory("模型按任务自由搭配", (2, "我可以自由搭配"), kind="preference"),
    ))
    lab.run()
    found = lambda **params: [m["statement"] for m in lab.call("GET", "/api/v1/admin/memories?" + "&".join(f"{k}={v}" for k, v in params.items()))[1]["memories"]]  # noqa: E731
    from urllib.parse import quote

    assert found(query=quote("Docker")) == ["服务端部署在 NAS 的 Docker 应用层"]
    assert found(query=quote("我可以")) == ["模型按任务自由搭配"]  # found through its quote
    assert found(query=quote("没有这个词")) == []

    docker_id = lab.call("GET", "/api/v1/admin/memories?query=Docker")[1]["memories"][0]["id"]
    assert lab.call("POST", f"/api/v1/admin/memories/{docker_id}/expire", {})[0] == 200
    listing = lab.call("GET", "/api/v1/admin/memories")[1]
    assert listing["counts"] == {"active": 1, "expired": 1, "folded": 0, "superseded": 0}
    expired = [m for m in listing["memories"] if m["status"] == "expired"][0]
    assert expired["expire_reason"] == "manual" and expired["expired_at"] and listing["retention_days"] == 30
    assert found(status="expired") == ["服务端部署在 NAS 的 Docker 应用层"]
    assert found(status="active") == ["模型按任务自由搭配"]

    assert lab.call("POST", f"/api/v1/admin/memories/{docker_id}/restore", {})[0] == 200
    assert lab.call("GET", "/api/v1/admin/memories")[1]["counts"] == {"active": 2, "expired": 0, "folded": 0, "superseded": 0}

    lab.call("POST", f"/api/v1/admin/memories/{docker_id}/expire", {})
    assert lab.distiller.purge_expired(retention_days=30) == 0   # still inside its keep-by period
    assert lab.distiller.purge_expired(retention_days=-1) == 1   # past it: gone for good
    assert lab.call("GET", f"/api/v1/admin/memories/{docker_id}")[0] == 404

    other = lab.call("GET", "/api/v1/admin/memories")[1]["memories"][0]["id"]
    assert lab.call("POST", f"/api/v1/admin/memories/{other}/purge", {})[0] == 200
    assert lab.call("GET", "/api/v1/admin/memories")[1]["memories"] == []
    assert lab.call("POST", f"/api/v1/admin/memories/{other}/purge", {})[0] == 404


# ---- history brought in after the fact -----------------------------------------


def wait_for(predicate, timeout=10.0):
    import time as clock

    deadline = clock.time() + timeout
    while clock.time() < deadline:
        if predicate():
            return
        clock.sleep(0.02)
    raise AssertionError("timed out waiting")


def test_imported_history_is_held_until_the_owner_starts_it(lab, monkeypatch):
    import time as clock

    main = lab.source()
    lab.assign(main)
    lab.assign(main, slot="import")
    lab.say("live", ("user", NAS))
    lab.say("old", ("user", FREE), ("assistant", "好"), origin="import")
    old_chars = len(FREE) + 1

    status = lab.status()
    assert status["pending"]["segments"] == 1
    held = status["held"]
    assert (held["sessions"], held["segments"], held["chars"], held["total_chars"]) == (1, 2, old_chars, old_chars)
    assert held["agents"] == [{"device": "Mac mini", "agent": "Claude Code", "sessions": 1, "segments": 2, "chars": old_chars}]
    assert held["estimate"] == {
        "input_tokens": round(old_chars * distill.DEFAULT_INPUT_TOKENS_PER_CHAR),
        "output_tokens": round(old_chars * distill.DEFAULT_OUTPUT_TOKENS_PER_CHAR),
        "seconds": None,
        "measured": False,
    }
    assert held["model"] == "中转 · alpha-mini"
    # Imported history is not today's collection.
    assert lab.call("GET", "/api/v1/admin/overview?since=0")[1]["segments_today"] == 1

    # Neither a round started by hand nor the nightly one touches it.
    lab.fake.reply_text = reply()
    status = lab.run()
    assert status["pending"]["segments"] == 0 and status["held"]["segments"] == 2
    lab.say("live", ("assistant", "收到"))
    monkeypatch.setattr(distill, "NIGHTLY_HOUR", clock.localtime().tm_hour)
    assert lab.distiller.tick() == "nightly"
    lab.distiller.wait()
    assert lab.status()["held"]["segments"] == 2
    assert all(FREE not in prompt for prompt in lab.prompts())

    # Started by the owner, it runs on its own slot and keeps its own place.
    lab.fake.replies.append(reply(memory("模型按任务自由搭配", (1, "这个不定死"), kind="preference")))
    status = lab.run(job="import")
    last = status["held"]["runs"][0]
    assert (last["kind"], last["status"], last["windows"], last["chars"], last["memories"]) == ("import", "done", 1, old_chars, 1)
    assert status["held"]["segments"] == 0 and status["pending"]["segments"] == 0
    assert all(run["kind"] == "daily" for run in status["runs"])
    assert FREE in lab.prompts()[-1] and NAS not in lab.prompts()[-1]

    # Once a round has been measured, the estimate uses what it really cost.
    monkeypatch.setattr(distill, "MIN_MEASURED_CHARS", 1)
    lab.say("older", ("user", "旧UI太丑"), origin="import")
    estimate = lab.status()["held"]["estimate"]
    assert estimate["measured"] is True and estimate["input_tokens"] == round(len("旧UI太丑") * 7 / old_chars)


def test_a_live_copy_of_imported_history_is_not_held(lab):
    lab.say("old", ("user", NAS), ("user", FREE), origin="import")
    lab.say("live", ("user", NAS))  # the same message, still in a live session file
    status = lab.status()
    assert (status["pending"]["segments"], status["held"]["segments"]) == (1, 1)


def test_an_import_round_needs_its_own_model_and_a_known_job(lab):
    lab.assign(lab.source())
    lab.say("old", ("user", NAS), origin="import")
    status, body = lab.call("POST", "/api/v1/admin/distill/run", {"job": "import"})
    assert (status, body["error"]) == (409, "no_import_model")
    assert lab.call("POST", "/api/v1/admin/distill/run", {"job": "everything"})[0] == 400
    assert lab.call("POST", "/api/v1/admin/distill/pause", {})[1]["error"] == "not_running"
    assert lab.status()["has_import_model"] is False


def _three_old_conversations(lab):
    main = lab.source()
    lab.assign(main)
    lab.assign(main, slot="import")
    for session, text in (("old1", NAS), ("old2", FREE), ("old3", "旧UI太丑")):
        lab.say(session, ("user", text), origin="import")
    lab.fake.reply_text = reply()
    lab.fake.gate = threading.Event()


def test_an_import_round_pauses_after_the_stretch_in_hand_and_stays_paused(lab, monkeypatch):
    monkeypatch.setattr(distill, "PARALLEL", {"daily": 1, "import": 1})
    monkeypatch.setattr(distill, "NIGHTLY_HOUR", -1)
    _three_old_conversations(lab)
    assert lab.call("POST", "/api/v1/admin/distill/run", {"job": "import"})[0] == 200
    wait_for(lambda: len(lab.prompts()) == 1)
    assert lab.call("POST", "/api/v1/admin/distill/pause", {"job": "import"})[0] == 200
    assert lab.status()["lives"]["import"]["pausing"] is True
    lab.fake.gate.set()
    lab.distiller.wait()
    status = lab.status()
    assert (status["held"]["runs"][0]["status"], status["held"]["runs"][0]["windows"], status["held"]["sessions"]) == ("paused", 1, 2)
    assert lab.distiller.tick() == ""
    assert lab.call("POST", "/api/v1/admin/distill/pause", {"job": "import"})[1]["error"] == "not_running"


def test_with_online_models_the_nightly_round_runs_beside_an_import(lab, monkeypatch):
    import time as clock

    monkeypatch.setattr(distill, "NIGHTLY_HOUR", -1)
    _three_old_conversations(lab)
    lab.say("live", ("user", "今晚的新对话"))
    assert lab.call("POST", "/api/v1/admin/distill/run", {"job": "import"})[0] == 200
    wait_for(lambda: len(lab.prompts()) == 3)  # several conversations at once
    assert lab.status()["lives"]["import"]["parallel"] == 4
    monkeypatch.setattr(distill, "NIGHTLY_HOUR", clock.localtime().tm_hour)
    assert lab.distiller.tick() == "nightly"  # no stepping aside: both run
    wait_for(lambda: len(lab.prompts()) == 4)
    assert set(lab.status()["lives"]) == {"import", "daily"}
    lab.fake.gate.set()
    lab.distiller.wait()
    status = lab.status()
    assert status["held"]["runs"][0]["status"] == "done" and status["runs"][0]["trigger"] == "nightly"
    assert (status["held"]["segments"], status["pending"]["segments"]) == (0, 0)


def test_when_both_jobs_use_the_machines_own_model_history_steps_aside(lab, monkeypatch):
    import time as clock

    monkeypatch.setattr(distill, "NIGHTLY_HOUR", -1)
    monkeypatch.setattr(distill.Distiller, "_uses_local", lambda self, job: True)
    _three_old_conversations(lab)
    lab.say("live", ("user", "今晚的新对话"))
    assert lab.call("POST", "/api/v1/admin/distill/run", {"job": "import"})[0] == 200
    wait_for(lambda: len(lab.prompts()) == 1)
    assert lab.status()["lives"]["import"]["parallel"] == 1  # one at a time on this machine
    assert lab.call("POST", "/api/v1/admin/distill/run", {})[1]["error"] == "local_model_busy"
    monkeypatch.setattr(distill, "NIGHTLY_HOUR", clock.localtime().tm_hour)
    assert lab.distiller.tick() == ""  # asks history to step aside
    lab.fake.gate.set()
    lab.distiller.wait()
    assert lab.status()["held"]["runs"][0]["status"] == "yielded"
    assert lab.distiller.tick() == "nightly"
    lab.distiller.wait()
    assert lab.status()["pending"]["segments"] == 0
    assert lab.distiller.tick() == "resume"
    lab.distiller.wait()
    status = lab.status()
    assert (status["held"]["runs"][0]["trigger"], status["held"]["runs"][0]["status"]) == ("resume", "done")
    assert status["held"]["segments"] == 0 and lab.distiller.tick() == ""


def test_an_import_round_cut_off_by_a_restart_carries_on(lab, monkeypatch):
    main = lab.source()
    lab.assign(main, slot="import")
    lab.say("old", ("user", NAS), origin="import")
    with lab.distiller._store._tx() as db:
        db.execute("INSERT INTO distill_runs(trigger, started_at, finished_at, status, kind) VALUES('manual', 0, 0, 'interrupted', 'import')")
    monkeypatch.setattr(distill, "NIGHTLY_HOUR", -1)
    lab.fake.reply_text = reply()
    assert lab.distiller.tick() == "resume"
    lab.distiller.wait()
    assert lab.status()["held"]["segments"] == 0


def test_distillation_streams_and_asks_for_the_jobs_thinking_level(lab):
    lab.assign(lab.source())
    assert lab.call("POST", "/api/v1/admin/models/slots/effort", {"slot": "daily", "effort": "low"})[0] == 200
    lab.say("s1", ("user", NAS))
    lab.fake.reply_text = reply()
    assert lab.run()["runs"][0]["status"] == "done"
    sent = [entry[3] for entry in lab.fake.seen if entry[0] == "POST" and "对话:" in str(entry[3].get("input", ""))][-1]
    assert sent["stream"] is True and sent["reasoning"] == {"effort": "low"}


# ---- the same thing said again in another conversation -------------------------

FIRST = "用户希望模型按任务自由搭配,不要写死在固定的中转上"
AGAIN = "用户希望模型按任务自由搭配,不要写死在某一个中转上"


def test_a_restatement_from_another_conversation_folds_into_the_earlier_memory_and_can_be_taken_out(lab):
    lab.assign(lab.source())
    lab.say("s1", ("assistant", "我理解你的意思是模型按任务自由搭配"))
    lab.fake.replies.append(reply(memory(FIRST, (1, "模型按任务自由搭配"), kind="preference")))
    lab.run()
    (first,) = lab.call("GET", "/api/v1/admin/memories")[1]["memories"]
    assert first["note"] == "没有用户原话,是助手的转述"  # only the assistant's words so far

    lab.say("s2", ("user", "这个不定死，我可以自由搭配"))
    lab.fake.replies.append(reply(memory(AGAIN, (1, "我可以自由搭配"), kind="preference")))
    status = lab.run()
    assert status["memories"] == {"active": 1, "expired": 0, "folded": 1} and status["runs"][0]["merged"] == 1

    (kept,) = lab.call("GET", "/api/v1/admin/memories")[1]["memories"]
    assert kept["id"] == first["id"] and kept["restated"] == 1 and kept["note"] == ""  # the user's words came with it
    detail = lab.call("GET", f"/api/v1/admin/memories/{kept['id']}")[1]
    assert [e["quote"] for e in detail["evidence"]] == ["模型按任务自由搭配", "我可以自由搭配"]
    (again,) = detail["restatements"]
    assert again["statement"] == AGAIN and again["similarity"] >= 0.6

    found = lab.device("POST", "/api/v1/recall", {"query": "模型自由搭配"})[1]["memories"]
    assert [m["id"] for m in found] == [kept["id"]]  # the restatement is on file, not handed out twice
    assert lab.device("GET", f"/api/v1/memories/{again['id']}/source")[1]["folded_into"] == kept["id"]
    assert lab.call("GET", "/api/v1/admin/memories?status=folded")[1]["memories"][0]["id"] == again["id"]
    assert lab.call("POST", f"/api/v1/admin/memories/{again['id']}/expire", {})[0] == 409

    assert lab.call("POST", f"/api/v1/admin/memories/{again['id']}/unfold", {})[0] == 200
    assert lab.status()["memories"] == {"active": 2, "expired": 0, "folded": 0}
    restored = lab.call("GET", f"/api/v1/admin/memories/{kept['id']}")[1]
    assert [e["quote"] for e in restored["evidence"]] == ["模型按任务自由搭配"] and restored["restatements"] == []
    assert lab.call("POST", f"/api/v1/admin/memories/{again['id']}/unfold", {})[0] == 409


def test_statements_that_name_different_things_or_say_not_stay_apart(lab):
    lab.assign(lab.source())
    pairs = [("向量索引使用 Granite 模型 v17 版本", "向量索引使用 Granite 模型 v18 版本"),
             ("日常提炼使用 NAS 本机模型完成", "日常提炼不使用 NAS 本机模型完成")]
    for number, (one, other) in enumerate(pairs):
        lab.say(f"a{number}", ("user", one))
        lab.fake.replies.append(reply(memory(one, (1, one))))
        lab.run()
        lab.say(f"b{number}", ("user", other))
        lab.fake.replies.append(reply(memory(other, (1, other))))
        lab.run()
    assert lab.status()["memories"] == {"active": 4, "expired": 0, "folded": 0}


def test_memories_resting_on_the_same_words_from_another_conversation_fold_together(lab):
    lab.assign(lab.source())
    bridge = "把文章卡片作为用户提供的新资料直接处理"  # the same words, said again in each conversation
    lab.say("s1", ("user", bridge))
    lab.fake.replies.append(reply(memory("用户要求把微信转发来的文章卡片当作新资料直接处理", (1, bridge), kind="preference")))
    lab.run()
    lab.say("s2", ("user", "又一篇文章。" + bridge))
    lab.fake.replies.append(reply(memory("转发来的文章卡片按新资料处理,进入固定任务", (1, bridge), kind="preference")))
    lab.run()
    assert lab.status()["memories"] == {"active": 1, "expired": 0, "folded": 1}

    # A short stock reply is not "the same words": these stay apart.
    lab.say("s3", ("user", "可以"))
    lab.fake.replies.append(reply(memory("用户同意先部署服务端再改客户端", (1, "可以"))))
    lab.run()
    lab.say("s4", ("user", "可以吧"))
    lab.fake.replies.append(reply(memory("用户同意按建议把旧版删除", (1, "可以"))))
    lab.run()
    assert lab.status()["memories"] == {"active": 3, "expired": 0, "folded": 1}


def test_restatements_already_stored_are_folded_once(lab):
    lab.say("s1", ("user", "模型按任务自由搭配"), ("user", "我可以自由搭配"), ("user", "第三章要改结尾"))
    store = lab.distiller._store
    with store._tx() as db:
        agent_id = db.execute("SELECT id FROM agents LIMIT 1").fetchone()[0]
        segments = [row[0] for row in db.execute("SELECT id FROM segments ORDER BY id")]
        ids = []
        for number, statement in enumerate([FIRST, AGAIN, "小说第三章的结尾改成开放式"]):
            ids.append(db.execute(
                "INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at) VALUES(?,?,'preference',?,'s1',0)",
                (statement, statement, agent_id)).lastrowid)
            db.execute("INSERT INTO memory_evidence(memory_id, segment_id, quote) VALUES(?,?,'搭配')", (ids[-1], segments[number]))
    lab.distiller._restatements()  # what the server does once after it starts
    assert lab.status()["memories"] == {"active": 2, "expired": 0, "folded": 1}
    with store._lock:
        assert store._db.execute("SELECT folded_into FROM memories WHERE id = ?", (ids[1],)).fetchone()[0] == ids[0]
        assert store._meta("restatements_folded") == distill.FOLD_RULES

    # Later starts only index what is there: nothing is folded twice, and the folded one stays out.
    lab.distiller._restated_ready = False
    lab.distiller._restated = distill.StatementIndex()
    assert len(lab.distiller._restatements()) == 2

    # Clearing a memory clears the restatements folded into it.
    assert lab.call("POST", f"/api/v1/admin/memories/{ids[0]}/purge", {})[0] == 200
    assert lab.status()["memories"] == {"active": 1, "expired": 0, "folded": 0}


def test_a_memory_that_speaks_for_the_user_without_their_words_says_so(lab):
    lab.assign(lab.source())
    lab.say("s1", ("user", "回答先给结论"), ("assistant", "好的，以后先给结论再展开"))
    lab.fake.replies.append(reply(
        memory("用户希望回答先给结论再展开", (1, "回答先给结论"), kind="preference"),
        memory("用户要求回复时先结论后细节", (2, "以后先给结论再展开"), kind="decision"),
        memory("助手决定回复先给结论", (2, "以后先给结论再展开"), kind="decision"),
    ))
    lab.run()
    found = {m["statement"]: m["note"] for m in lab.device("POST", "/api/v1/recall", {"query": "先给结论", "limit": 5})[1]["memories"]}
    assert found == {"用户希望回答先给结论再展开": "", "用户要求回复时先结论后细节": "没有用户原话,是助手的转述", "助手决定回复先给结论": ""}
    catalog = lab.device("GET", "/api/v1/catalog?full=1")[1]["text"]
    assert "[决定·助手转述] 用户要求回复时先结论后细节" in catalog and "[偏好] 用户希望回答先给结论再展开" in catalog


def test_the_prompt_asks_for_the_users_own_words_and_leaves_out_passing_state():
    assert "替用户说话要有用户的原话" in distill.SYSTEM_PROMPT
    assert "当前版本号" in distill.SYSTEM_PROMPT


def test_a_memory_folded_into_another_brings_its_restatements_along(lab):
    lab.say("s1", ("user", "第一句话说得很清楚了"), ("user", "第二句话说得很清楚了"), ("user", "第三句话说得很清楚了"))
    store = lab.distiller._store
    with store._tx() as db:
        agent_id = db.execute("SELECT id FROM agents LIMIT 1").fetchone()[0]
        segments = [row[0] for row in db.execute("SELECT id FROM segments ORDER BY id")]
        x, y, z = (
            db.execute("INSERT INTO memories(fingerprint, statement, kind, agent_id, session_id, created_at) VALUES(?,?,'fact',?,'s1',0)",
                       (name, name, agent_id)).lastrowid
            for name in ("X", "Y", "Z")
        )
        for memory_id, segment in zip((x, y, z), segments):
            db.execute("INSERT INTO memory_evidence(memory_id, segment_id, quote) VALUES(?,?,'说得很清楚了')", (memory_id, segment))
        lab.distiller._fold(db, y, z, 0.7)
        lab.distiller._fold(db, x, y, 0.7)
        assert dict(db.execute("SELECT id, folded_into FROM memories WHERE status = 'folded'").fetchall()) == {y: x, z: x}
        assert {row[0] for row in db.execute("SELECT kept_id FROM memory_folds")} == {x}
        # The same words from other conversations were not piled onto the memory that stays.
        assert db.execute("SELECT COUNT(*) FROM memory_evidence WHERE memory_id = ?", (x,)).fetchone()[0] == 1
        # A chain left by an earlier version is straightened when the server starts.
        db.execute("UPDATE memories SET folded_into = ? WHERE id = ?", (y, z))
        assert lab.distiller._settle_folds(db) == 1
        assert db.execute("SELECT folded_into FROM memories WHERE id = ?", (z,)).fetchone()[0] == x



# ---- choosing which part of the imported history to organise ------------------


def test_a_range_of_imported_history_can_be_chosen_by_time_agent_and_project(lab):
    import time as clock

    def days_ago(days):
        return clock.strftime("%Y-%m-%dT%H:%M:%SZ", clock.gmtime(clock.time() - days * 86400))

    main = lab.source()
    lab.assign(main)
    lab.assign(main, slot="import")
    codex = lab.device("POST", "/api/v1/agents/report", {"agent": {"name": "Codex"}})[1]["agent_id"]
    lab.device("POST", "/api/v1/projects/declare", {"folder": "/work/tl", "project": "时间图书馆"})
    lab.say("recent", ("user", "最近的小说要改结尾"), origin="import", ts=days_ago(10), cwd="/work/novel")
    lab.say("older", ("user", "服务端放在 NAS 上"), origin="import", ts=days_ago(100), cwd="/work/tl/server")
    lab.say("codex", ("user", "Codex 那边的旧话"), origin="import", ts=days_ago(20), cwd="/work/novel", agent=codex)
    lab.fake.reply_text = reply()

    held = lab.status()["held"]
    assert held["scope"]["months"] == 0 and held["scoped"]["sessions"] == 3  # all of it, until a range is chosen
    choices = held["choices"]
    assert [(m["months"], m["sessions"]) for m in choices["months"]] == [(1, 2), (3, 2), (6, 3), (12, 3)]
    assert {g["key"]: g["sessions"] for g in choices["groups"]} == {"folder:/work/novel": 2, "project:时间图书馆": 1}
    assert {a["agent"]: a["sessions"] for a in choices["agents"]} == {"Claude Code": 2, "Codex": 1}

    preview = lab.call("POST", "/api/v1/admin/distill/import-scope/preview", {"scope": {"months": 1, "agents": [codex]}})[1]
    assert (preview["sessions"], preview["chars"]) == (1, len("Codex 那边的旧话"))
    assert lab.call("POST", "/api/v1/admin/distill/import-scope/preview", {"scope": {"months": 2}})[0] == 400

    # Organise the last month only: the older conversation stays held, untouched.
    status = lab.run(job="import", scope={"months": 1})
    assert status["held"]["runs"][0]["status"] == "done" and status["held"]["scoped"]["sessions"] == 0
    assert status["held"]["sessions"] == 1 and "服务端放在 NAS 上" not in "".join(lab.prompts())

    # Then one project: by its declared name, subfolders included.
    status = lab.run(job="import", scope={"months": 0, "groups": ["project:时间图书馆"], "listed": ["project:时间图书馆"]})
    assert status["held"]["sessions"] == 0 and "服务端放在 NAS 上" in lab.prompts()[-1]


def test_the_range_cannot_change_under_a_running_import(lab):
    _three_old_conversations(lab)
    assert lab.call("POST", "/api/v1/admin/distill/run", {"job": "import"})[0] == 200
    assert lab.call("POST", "/api/v1/admin/distill/import-scope", {"scope": {"months": 3}})[0] == 409
    lab.fake.gate.set()
    lab.distiller.wait()
    assert lab.call("POST", "/api/v1/admin/distill/import-scope", {"scope": {"months": 3}})[1]["scope"]["months"] == 3
    assert lab.call("POST", "/api/v1/admin/distill/import-scope", {"scope": None})[1]["scope"]["months"] == 0



def test_an_answer_broken_off_by_the_relay_is_tried_again_not_a_stopped_round(lab, monkeypatch):
    monkeypatch.setattr(distill, "RETRY_DELAYS", (0, 0))
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS))
    lab.fake.replies += ["STREAM_ERROR", reply(memory("服务端部署在 NAS 的 Docker 应用层", (1, "飞牛 Docker 应用层")))]
    status = lab.run()
    assert status["runs"][0]["status"] == "done" and status["memories"]["active"] == 1


def test_a_saved_memory_keeps_when_it_was_said_and_whether_the_user_said_it(lab):
    lab.assign(lab.source())
    lab.say("s1", ("assistant", "我理解你的意思是模型按任务自由搭配"), ts="2026-11-10T08:00:00Z")
    lab.fake.replies.append(reply(memory(FIRST, (1, "模型按任务自由搭配"), kind="preference")))
    lab.run()
    lab.say("s2", ("user", "这个不定死，我可以自由搭配"), ts="2026-11-20T09:00:00Z")
    lab.fake.replies.append(reply(memory(AGAIN, (1, "我可以自由搭配"), kind="preference")))
    lab.run()
    with lab.distiller._store._lock:
        rows = lab.distiller._store._db.execute("SELECT statement, status, said_at, user_quoted FROM memories ORDER BY id").fetchall()
    kept, folded = (tuple(row) for row in rows)
    assert folded == (AGAIN, "folded", "2026-11-20T09:00:00Z", 1)
    assert kept == (FIRST, "active", "2026-11-20T09:00:00Z", 1)  # the restatement brought the user's words and a later date


def test_a_memory_shows_where_its_session_was_started(lab):
    lab.assign(lab.source())
    segments = [{"segment_uid": "uid-surface-1", "session_id": "desk-1", "source_file": "desk-1.jsonl", "position": 0,
                 "role": "user", "text": "以后回答都先给结论", "ts": "2026-11-23T00:00:00Z", "surface": "claude-desktop"}]
    agent_id = lab.device("POST", "/api/v1/agents/report", {"agent": {"name": "Claude Code"}})[1]["agent_id"]
    assert lab.device("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": segments})[0] == 200
    lab.fake.replies.append(reply(memory("用户要求回答先给结论", (1, "以后回答都先给结论"), kind="preference")))
    lab.run()
    (found,) = lab.device("POST", "/api/v1/recall", {"query": "回答先给结论"})[1]["memories"]
    assert (found["agent"], found["surface"]) == ("Claude Code", "桌面")
    assert lab.call("GET", f"/api/v1/admin/memories/{found['id']}")[1]["surface"] == "桌面"


def test_a_large_library_answers_from_the_index_in_hand_while_a_fresh_one_is_built(lab, monkeypatch):
    import time as clock

    from tl_server import recall as recall_module

    monkeypatch.setattr(recall_module, "BACKGROUND_REBUILD_FROM", 1)
    monkeypatch.setattr(recall_module, "REBUILD_AT_MOST_EVERY", 0)
    lab.assign(lab.source())
    lab.say("s1", ("user", NAS))
    lab.fake.replies.append(reply(memory("服务端放在 NAS 的 Docker 应用层", (1, NAS))))
    lab.run()
    assert len(lab.device("POST", "/api/v1/recall", {"query": "NAS Docker"})[1]["memories"]) == 1
    lab.say("s2", ("user", "Docker 镜像拉不下来就走飞牛的镜像站"))
    lab.fake.replies.append(reply(memory("Docker 镜像拉不下来时改用飞牛镜像站", (1, "Docker 镜像拉不下来就走飞牛的镜像站"), kind="lesson")))
    lab.run()
    first = lab.device("POST", "/api/v1/recall", {"query": "Docker 镜像"})[1]["memories"]  # not waited on
    deadline = clock.time() + 5
    while clock.time() < deadline:
        found = lab.device("POST", "/api/v1/recall", {"query": "Docker 镜像"})[1]["memories"]
        if any("镜像站" in m["statement"] for m in found):
            break
        clock.sleep(0.05)
    else:
        raise AssertionError("the fresh index never arrived")
    assert len(first) <= len(found)
    # The rebuild read and split only the new memory: the others' words were kept.
    words = lab.server.recall._words
    assert len(words) == 2 and all(isinstance(counts, recall_module.Counter) for _, counts in words.values())
