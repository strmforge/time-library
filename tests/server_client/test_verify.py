"""Nothing missed: an agent's own files against what the server has, and what is missing sent."""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

import tl_client.__main__ as cli
from tl_client import verify as module
from tl_client.api import Api
from tl_client.state import State
from tl_client.sync import sync_all
from tl_client.verify import content_key, verify_round
from tl_server import store as store_module
from tl_server.app import create_server


def line(n, role="user", text=None):
    return json.dumps({"role": role, "content": text or f"第 {n} 句话,说的是不一样的事", "timestamp": f"2026-11-20T08:{n // 60:02d}:{n % 60:02d}Z"}, ensure_ascii=False)


@pytest.fixture()
def box(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "machine_uid", lambda: "verify-test-device-01")
    httpd = create_server(str(tmp_path / "server"), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    admin = Api(url, (tmp_path / "server" / "admin_token.txt").read_text().strip())
    home, sessions = tmp_path / "client", tmp_path / "sessions"
    sessions.mkdir()
    for name, count in (("a", 8), ("b", 5)):
        (sessions / f"{name}.jsonl").write_text("\n".join(line(n, text=f"{name} 的第 {n} 句") for n in range(count)) + "\n", encoding="utf-8")
    token = admin._call("POST", "/api/v1/admin/pairing-tokens", {})["pairing_token"]
    assert cli.main(["--home", str(home), "pair", "--server", url, "--token", token, "--name", "Mac"]) == 0
    assert cli.main(["--home", str(home), "report-agent", "--name", "Codex", "--sessions", str(sessions), "--format", "flat_role_content"]) == 0
    b = type("Box", (), {})()
    b.httpd, b.home, b.sessions, b.admin = httpd, home, sessions, admin

    def state():
        return State(home)

    def api():
        s = state()
        return Api(s.config["server_url"], s.config["device_token"])

    b.state, b.api = state, api
    b.sync = lambda: (lambda s: sync_all(api(), s))(state())
    b.stored = lambda: httpd.store._db.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
    b.seen = lambda: next(a for d in admin._call("GET", "/api/v1/admin/devices")["devices"] for a in d["agents"] if a["name"] == "Codex")["verified"]
    b.sync()
    yield b
    httpd.shutdown()
    httpd.server_close()
    httpd.store.close()


def lose(box, where):
    with box.httpd.store._tx() as db:
        db.execute(f"DELETE FROM segments WHERE {where}")


def test_the_same_identity_on_both_sides():
    for args in (("user", "2026-11-20T08:00:00Z", "说的话"), ("assistant", "", "x"), ("user", "2026-11-20T08:00:00Z", "说的话", 3)):
        assert content_key(*args) == store_module.content_key(*args)


def test_nothing_missed_is_said_so(box):
    assert box.stored() == 13
    found = verify_round(box.api(), box.state())["Codex"]
    assert (found["files"], found["read"], found["segments"], found["missing"]) == (2, 2, 13, 0)
    seen = box.seen()
    assert (seen["files"], seen["looked"], seen["segments"], seen["missing"], seen["repaired_ever"]) == (2, 2, 13, 0, 0) and seen["at"]
    assert verify_round(box.api(), box.state())["Codex"]["read"] == 0  # looked at and unchanged: not again
    with (box.sessions / "b.jsonl").open("a", encoding="utf-8") as out:
        out.write(line(40, text="b 又说了一句") + "\n")
    box.sync()
    assert verify_round(box.api(), box.state())["Codex"]["read"] == 1  # only the one that changed


def test_what_never_arrived_is_found_and_sent(box):
    lose(box, "text IN ('a 的第 3 句', 'b 的第 0 句')")
    assert box.sync()[0].accepted == 0  # uploading trusts how far it read
    found = verify_round(box.api(), box.state())["Codex"]
    assert (found["missing"], found["repaired"], found["held_back"]) == (2, 2, 0) and box.stored() == 13
    assert box.seen()["repaired_ever"] == 2 and box.seen()["missing"] == 0


def test_far_too_much_missing_is_reported_and_only_sent_when_asked(box, monkeypatch, capsys):
    monkeypatch.setattr(module, "REPAIR_AT_ONCE", 3)
    lose(box, "text LIKE 'a 的%'")
    found = verify_round(box.api(), box.state())["Codex"]
    assert (found["missing"], found["repaired"], found["held_back"]) == (8, 0, 8) and box.stored() == 5
    assert box.seen()["missing"] == 8
    box.httpd.doctor.run_now() if hasattr(box.httpd.doctor, "run_now") else box.admin._call("POST", "/api/v1/admin/doctor/run", {})
    box.httpd.doctor.wait()
    checks = {c["key"]: c for c in box.admin._call("GET", "/api/v1/admin/doctor")["checkup"]["checks"]}
    assert checks["missed"]["status"] == "warn" and "Codex" in checks["missed"]["label"]
    assert cli.main(["--home", str(box.home), "verify"]) == 1 and "held back" in capsys.readouterr().out
    assert cli.main(["--home", str(box.home), "verify", "--repair"]) == 0
    assert box.stored() == 13 and box.seen()["missing"] == 0


def test_a_turn_kept_under_another_file_is_not_missing(box):
    (box.sessions / "copy.jsonl").write_text((box.sessions / "a.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    box.sync()
    assert box.stored() == 13  # the same turns, kept once
    found = verify_round(box.api(), box.state())["Codex"]
    assert found["missing"] == 0 and found["segments"] == 21


def test_a_file_that_is_gone_is_counted_and_stays_on_the_server(box):
    verify_round(box.api(), box.state())
    (box.sessions / "b.jsonl").unlink()
    with (box.sessions / "a.jsonl").open("a", encoding="utf-8") as out:
        out.write(line(50, text="a 又一句") + "\n")
    box.sync()
    assert verify_round(box.api(), box.state())["Codex"]["gone"] == 1
    assert box.seen()["gone"] == 1 and box.stored() == 14


def test_what_has_not_been_uploaded_yet_is_the_uploads_business(box):
    (box.sessions / "new.jsonl").write_text(line(1, text="还没传的一句") + "\n", encoding="utf-8")
    found = verify_round(box.api(), box.state())["Codex"]
    assert found["files"] == 2 and found["missing"] == 0


def test_a_round_is_small(box, monkeypatch):
    monkeypatch.setattr(module, "ROUND_BYTES", 1)
    assert verify_round(box.api(), box.state())["Codex"]["read"] == 1
    assert verify_round(box.api(), box.state())["Codex"]["read"] == 1  # the other one, next time
    assert verify_round(box.api(), box.state())["Codex"]["read"] == 0


def test_sessions_kept_in_a_database_are_compared_too(box, tmp_path):
    path = tmp_path / "chats.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp TEXT)")
    db.executemany("INSERT INTO messages(session_id, role, content, timestamp) VALUES('s', 'user', ?, ?)",
                   [(f"库里的第 {n} 句", f"2026-11-21T09:00:{n:02d}Z") for n in range(6)])
    db.commit()
    db.close()
    spec = {"base": "flat_role_content", "store": "sqlite", "table": "messages", "order": "id", "session_id": ["session_id"], "timestamp": ["timestamp"]}
    assert cli.main(["--home", str(box.home), "report-agent", "--name", "Hermes", "--sessions", str(path), "--format-json", json.dumps(spec)]) == 0
    box.sync()
    lose(box, "text = '库里的第 2 句'")
    found = verify_round(box.api(), box.state(), only="Hermes")["Hermes"]
    assert (found["segments"], found["missing"], found["repaired"]) == (6, 1, 1)
