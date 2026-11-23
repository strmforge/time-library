"""What was sent to a model, byte for byte: the ledger holds what really went out, and no key."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat

import pytest

from fake_model_server import GOOD_KEY
from test_distill import fake, lab, memory, reply  # noqa: F401  (fixtures)
from tl_server import ledger as ledger_module
from tl_server.ledger import Ledger, scope_of


def sent(lab, **query):
    from urllib.parse import urlencode

    return lab.call("GET", "/api/v1/admin/sent" + ("?" + urlencode(query) if query else ""))[1]


@pytest.mark.parametrize("protocol", ["responses", "messages", "chat"])
def test_the_ledger_holds_the_very_bytes_that_went_out_and_no_key(lab, protocol):
    lab.assign(lab.source(protocol=protocol))
    lab.say("s1", ("user", "每次发版前先跑完全部测试,一个都不能跳过"))
    lab.fake.replies.append(reply(memory("发版前跑完全部测试", (1, "每次发版前先跑完全部测试"), kind="lesson")))
    before = len(lab.fake.raw)
    lab.run()
    arrived = lab.fake.raw[before:]
    calls = [call for call in sent(lab)["calls"] if call["task"] == "daily"]
    assert len(calls) == len(arrived) == 1 and calls[0]["status"] == "ok" and calls[0]["protocol"] == protocol
    assert "body" not in calls[0]  # the list says where and how much, not the words
    one = lab.call("GET", f"/api/v1/admin/sent/{calls[0]['id']}")[1]
    assert one["body"].encode("utf-8") == arrived[0]  # byte for byte what the model server received
    assert (one["bytes"], one["sha256"], one["intact"]) == (len(arrived[0]), hashlib.sha256(arrived[0]).hexdigest(), True)
    assert "发版前跑完全部测试" in one["answer"] and one["scope"] == "nas"
    with open(lab.server.ledger._path, "rb") as raw:
        assert GOOD_KEY.encode() not in raw.read()
    assert stat.S_IMODE(os.stat(lab.server.ledger._path).st_mode) == 0o600


def test_every_kind_of_request_is_there_also_the_ones_that_failed(lab):
    source = lab.source()
    lab.call("POST", f"/api/v1/admin/models/sources/{source}/test", {})
    lab.assign(source)
    lab.call("POST", "/api/v1/admin/models/sources", {"name": "坏的", "base_url": "http://127.0.0.1:9/v1", "protocol": "chat", "api_key": "x", "model": "m"})
    bad = lab.call("GET", "/api/v1/admin/models")[1]["sources"][-1]["id"]
    lab.call("POST", f"/api/v1/admin/models/sources/{bad}/test", {})
    found = sent(lab)
    assert {call["task"] for call in found["calls"]} == {"test"} and found["missed"] == 0
    assert sorted({call["status"] for call in found["calls"]}) == ["error:unreachable", "ok"]
    assert found["today"][0]["calls"] == len(found["calls"]) and sent(lab, task="daily")["calls"] == [] and sent(lab, scope="outside")["calls"] == []
    assert lab.call("GET", "/api/v1/admin/sent/999999")[0] == 404
    assert lab.call("GET", "/api/v1/admin/sent", token=None)[0] == 401


def test_where_a_request_went():
    assert scope_of("127.0.0.1") == scope_of("localhost") == scope_of("host.docker.internal") == "nas"
    assert scope_of("192.168.1.20") == scope_of("10.0.0.3") == "lan"
    assert scope_of("api.example.com") == scope_of("8.8.8.8") == "outside"


def test_old_texts_go_and_the_lines_about_them_stay(tmp_path, monkeypatch):
    clock = {"now": 1_000_000_000.0}
    book = Ledger(tmp_path, clock=lambda: clock["now"])
    record = book.recorder(task="daily", source="s", protocol="chat", model="m")
    for _ in range(3):
        record("https://api.example.com/v1/chat", b"x" * 400)("ok", "y" * 50)
        clock["now"] += 20 * 86400
    book.tidy()
    assert [call["kept"] for call in book.listing()["calls"]] == [1, 0, 0] or [call["kept"] for call in book.listing()["calls"]] == [1, 1, 0]
    oldest = book.one(book.listing()["calls"][-1]["id"])
    assert oldest["body"] is None and oldest["bytes"] == 400 and len(oldest["sha256"]) == 64 and not oldest["intact"]
    monkeypatch.setattr(ledger_module, "RETAIN_BYTES", 1)  # too much kept: the oldest texts go first
    book.tidy()
    assert all(not call["kept"] for call in book.listing()["calls"])
    clock["now"] += 400 * 86400
    book.tidy()
    assert book.listing()["total"] == 0
    book.close()


def test_a_ledger_that_cannot_be_written_is_said_not_hidden(tmp_path):
    book = Ledger(tmp_path)
    book._db.execute("DROP TABLE calls")
    book.recorder(task="daily", source="s", protocol="chat", model="m")("http://127.0.0.1/v1", b"{}")("ok", "x")
    assert book.missed == 1
    book.close()


def test_a_text_that_was_changed_is_shown_as_changed(lab):
    lab.call("POST", f"/api/v1/admin/models/sources/{lab.source()}/test", {})
    call = sent(lab)["calls"][0]["id"]
    with sqlite3.connect(lab.server.ledger._path) as db:
        import zlib

        db.execute("UPDATE calls SET body = ? WHERE id = ?", (zlib.compress(json.dumps({"model": "other"}).encode()), call))
    assert lab.call("GET", f"/api/v1/admin/sent/{call}")[1]["intact"] is False
