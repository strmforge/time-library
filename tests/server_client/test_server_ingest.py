"""Server side of the server/client redesign: pairing, self-report, ingest.

These tests drive a real HTTP server on a loopback port, the way a client would.
"""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from tl_server import store as store_module
from tl_server.app import MAX_BODY_BYTES, create_server


class Api:
    def __init__(self, port: int) -> None:
        self.port = port

    def call(self, method: str, path: str, body=None, token: str | None = None, raw: bytes | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = raw
        if payload is None and body is not None:
            payload = json.dumps(body).encode("utf-8")
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            conn.close()


@pytest.fixture()
def server(tmp_path):
    httpd = create_server(str(tmp_path), "127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    api = Api(httpd.server_address[1])
    api.admin = (tmp_path / "admin_token.txt").read_text().strip()
    api.data_dir = tmp_path
    api.httpd = httpd
    yield api
    httpd.shutdown()
    httpd.server_close()
    httpd.store.close()


def pair(api: Api, uid: str = "device-uid-0001", name: str = "Mac mini") -> dict:
    status, minted = api.call("POST", "/api/v1/admin/pairing-tokens", {}, token=api.admin)
    assert status == 200
    status, paired = api.call(
        "POST",
        "/api/v1/pair",
        {
            "pairing_token": minted["pairing_token"],
            "device": {"device_uid": uid, "name": name, "os": "macOS", "client_version": "0.1"},
        },
    )
    assert status == 200, paired
    paired["pairing_token"] = minted["pairing_token"]
    return paired


def report(api: Api, device_token: str, name: str = "Claude Code") -> int:
    status, body = api.call(
        "POST",
        "/api/v1/agents/report",
        {
            "agent": {
                "name": name,
                "capabilities": {"mcp": True, "skill": True, "preflight": False},
                "sessions_location": "~/.claude/projects",
                "session_format": "jsonl-messages",
            }
        },
        token=device_token,
    )
    assert status == 200, body
    return body["agent_id"]


def segment(position: int, text: str | None = None, source_file: str = "session-a.jsonl") -> dict:
    return {
        "segment_uid": f"{source_file}:{position:08d}",
        "session_id": "session-a",
        "source_file": source_file,
        "position": position,
        "role": "user" if position % 2 == 0 else "assistant",
        "text": text if text is not None else f"第 {position} 句",
        "ts": "2026-11-16T00:00:00Z",
    }


def test_health_needs_no_token_and_names_the_server(server):
    status, body = server.call("GET", "/api/v1/health")
    assert status == 200
    assert body["ok"] is True and len(body["server_id"]) == 32


def test_everything_else_refuses_without_a_token(server):
    assert server.call("POST", "/api/v1/ingest", {"agent_id": 1, "segments": []})[0] == 401
    assert server.call("POST", "/api/v1/agents/report", {"agent": {"name": "x"}})[0] == 401
    assert server.call("GET", "/api/v1/ingest/cursor?agent_id=1")[0] == 401
    assert server.call("GET", "/api/v1/admin/devices")[0] == 401
    assert server.call("POST", "/api/v1/admin/pairing-tokens", {})[0] == 401
    assert server.call("GET", "/api/v1/admin/devices", token="tla_wrong")[0] == 401


def test_admin_token_file_is_private_and_token_is_not_stored_in_clear(server):
    token_file = server.data_dir / "admin_token.txt"
    assert token_file.stat().st_mode & 0o077 == 0
    assert server.admin.encode() not in (server.data_dir / "server.db").read_bytes()


def test_pairing_token_works_once(server):
    paired = pair(server)
    assert paired["device_token"].startswith("tlc_")
    status, body = server.call(
        "POST",
        "/api/v1/pair",
        {"pairing_token": paired["pairing_token"], "device": {"device_uid": "device-uid-0002", "name": "other"}},
    )
    assert (status, body["error"]) == (401, "pairing_token_used")


def test_unknown_and_expired_pairing_tokens_are_refused(server, monkeypatch):
    device = {"device_uid": "device-uid-0001", "name": "Mac mini"}
    status, body = server.call("POST", "/api/v1/pair", {"pairing_token": "tlp_nope", "device": device})
    assert (status, body["error"]) == (401, "pairing_token_invalid")

    monkeypatch.setattr(store_module, "PAIRING_TTL_SECONDS", -1)
    _, minted = server.call("POST", "/api/v1/admin/pairing-tokens", {}, token=server.admin)
    status, body = server.call(
        "POST", "/api/v1/pair", {"pairing_token": minted["pairing_token"], "device": device}
    )
    assert (status, body["error"]) == (401, "pairing_token_expired")


def test_identity_is_computer_plus_agent_both_self_reported(server):
    paired = pair(server, name="Mac mini")
    claude = report(server, paired["device_token"], "Claude Code")
    codex = report(server, paired["device_token"], "Codex")
    assert claude != codex
    assert report(server, paired["device_token"], "Claude Code") == claude  # re-report keeps identity

    _, listing = server.call("GET", "/api/v1/admin/devices", token=server.admin)
    (device,) = listing["devices"]
    assert device["name"] == "Mac mini" and device["os"] == "macOS"
    assert [agent["name"] for agent in device["agents"]] == ["Claude Code", "Codex"]
    # "not supported" is recorded as reported, not dropped and not guessed.
    assert device["agents"][0]["capabilities"] == {"mcp": True, "skill": True, "preflight": False}


def test_ingest_is_idempotent_and_cursor_lets_a_client_resume(server):
    paired = pair(server)
    token = paired["device_token"]
    agent_id = report(server, token)

    batch = [segment(0), segment(1), segment(2)]
    status, body = server.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": batch}, token=token)
    assert (status, body) == (200, {"accepted": 3, "duplicates": 0})

    # A retry after a dropped connection, or a reinstalled client rescanning.
    retry = batch + [segment(3), segment(0, text="另一个会话里的话", source_file="session-b.jsonl")]
    status, body = server.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": retry}, token=token)
    assert (status, body) == (200, {"accepted": 2, "duplicates": 3})

    status, body = server.call("GET", f"/api/v1/ingest/cursor?agent_id={agent_id}", token=token)
    assert (status, body) == (200, {"cursor": {"session-a.jsonl": 3, "session-b.jsonl": 0}})

    _, listing = server.call("GET", "/api/v1/admin/devices", token=server.admin)
    assert listing["devices"][0]["agents"][0]["segments_total"] == 5


def test_a_device_cannot_touch_another_devices_agent(server):
    first = pair(server, uid="device-uid-0001", name="Mac mini")
    second = pair(server, uid="device-uid-0002", name="Office PC")
    agent_id = report(server, first["device_token"])
    status, body = server.call(
        "POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": [segment(0)]}, token=second["device_token"]
    )
    assert (status, body["error"]) == (404, "agent_not_found")
    status, _ = server.call("GET", f"/api/v1/ingest/cursor?agent_id={agent_id}", token=second["device_token"])
    assert status == 404


@pytest.mark.parametrize(
    "broken",
    [
        {"role": "system"},
        {"position": -1},
        {"position": True},
        {"text": ""},
        {"segment_uid": "short"},
        {"source_file": ""},
    ],
)
def test_malformed_segments_are_refused_and_nothing_is_stored(server, broken):
    paired = pair(server)
    token = paired["device_token"]
    agent_id = report(server, token)
    bad = {**segment(1), **broken}
    status, body = server.call(
        "POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": [segment(0), bad]}, token=token
    )
    assert (status, body["error"]) == (400, "invalid_field")
    _, cursor = server.call("GET", f"/api/v1/ingest/cursor?agent_id={agent_id}", token=token)
    assert cursor == {"cursor": {}}


def test_oversized_requests_are_refused(server):
    paired = pair(server)
    token = paired["device_token"]
    agent_id = report(server, token)
    too_many = [segment(i) for i in range(store_module.MAX_BATCH_SEGMENTS + 1)]
    status, body = server.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": too_many}, token=token)
    assert (status, body["error"]) == (413, "batch_too_large")

    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    try:
        conn.putrequest("POST", "/api/v1/ingest")
        conn.putheader("Authorization", f"Bearer {token}")
        conn.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 413
        assert json.loads(response.read())["error"] == "body_too_large"
    finally:
        conn.close()


def test_revoking_a_computer_cuts_off_all_its_agents(server):
    paired = pair(server)
    token = paired["device_token"]
    agent_id = report(server, token)
    assert server.call("POST", f"/api/v1/admin/devices/{paired['device_id']}/revoke", {}, token=server.admin)[0] == 200
    status, body = server.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": [segment(0)]}, token=token)
    assert (status, body["error"]) == (401, "device_token_invalid")
    _, listing = server.call("GET", "/api/v1/admin/devices", token=server.admin)
    assert listing["devices"][0]["revoked"] is True
    assert server.call("POST", "/api/v1/admin/devices/999/revoke", {}, token=server.admin)[0] == 404


def test_disconnecting_one_agent_leaves_its_neighbours_working(server):
    paired = pair(server)
    token = paired["device_token"]
    claude = report(server, token, "Claude Code")
    codex = report(server, token, "Codex")
    assert server.call("POST", f"/api/v1/admin/agents/{codex}/disconnect", {}, token=server.admin)[0] == 200

    status, body = server.call("POST", "/api/v1/ingest", {"agent_id": codex, "segments": [segment(0)]}, token=token)
    assert (status, body["error"]) == (403, "agent_disconnected")
    status, _ = server.call("POST", "/api/v1/ingest", {"agent_id": claude, "segments": [segment(0)]}, token=token)
    assert status == 200

    # Self-reporting again is how an agent comes back.
    assert report(server, token, "Codex") == codex
    status, _ = server.call("POST", "/api/v1/ingest", {"agent_id": codex, "segments": [segment(0)]}, token=token)
    assert status == 200


def test_heartbeat_records_backlog_per_agent(server):
    paired = pair(server)
    token = paired["device_token"]
    agent_id = report(server, token)
    status, _ = server.call(
        "POST", "/api/v1/heartbeat", {"client_version": "0.2", "backlog": {str(agent_id): 7}}, token=token
    )
    assert status == 200
    _, listing = server.call("GET", "/api/v1/admin/devices", token=server.admin)
    device = listing["devices"][0]
    assert device["client_version"] == "0.2" and device["agents"][0]["backlog"] == 7


def test_data_and_tokens_survive_a_restart(tmp_path):
    def start():
        httpd = create_server(str(tmp_path), "127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        api = Api(httpd.server_address[1])
        api.admin = (tmp_path / "admin_token.txt").read_text().strip()
        return httpd, api

    def stop(httpd):
        httpd.shutdown()
        httpd.server_close()
        httpd.store.close()

    httpd, api = start()
    server_id = api.call("GET", "/api/v1/health")[1]["server_id"]
    paired = pair(api)
    agent_id = report(api, paired["device_token"])
    api.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": [segment(0), segment(1)]}, token=paired["device_token"])
    stop(httpd)

    httpd, api = start()
    try:
        assert api.call("GET", "/api/v1/health")[1]["server_id"] == server_id
        status, body = api.call("GET", f"/api/v1/ingest/cursor?agent_id={agent_id}", token=paired["device_token"])
        assert (status, body) == (200, {"cursor": {"session-a.jsonl": 1}})
        assert api.call("GET", "/api/v1/admin/devices", token=api.admin)[0] == 200
    finally:
        stop(httpd)


def test_a_copy_of_a_message_in_another_session_file_is_stored_once(server):
    paired = pair(server)
    token = paired["device_token"]
    agent_id = report(server, token)
    original = [segment(0, "第一句"), segment(1, "第二句")]
    # A resumed session: a new file that starts with a copy of the old messages.
    copy = [dict(item, segment_uid=f"copy-{item['position']:08d}", source_file="session-b.jsonl") for item in original]
    copy.append({**segment(2, "续上之后的新话"), "segment_uid": "copy-00000002", "source_file": "session-b.jsonl"})
    assert server.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": original}, token=token)[1] == {"accepted": 2, "duplicates": 0}
    assert server.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": copy}, token=token)[1] == {"accepted": 1, "duplicates": 2}
    # Without a timestamp a message cannot be told from a different one that reads the same: kept.
    untimed = [{**segment(5, "好"), "ts": ""}, {**segment(6, "好"), "ts": ""}]
    assert server.call("POST", "/api/v1/ingest", {"agent_id": agent_id, "segments": untimed}, token=token)[1]["accepted"] == 2


def test_copies_already_stored_are_cleaned_up_and_what_cited_them_follows(tmp_path):
    from tl_server.store import Store

    store = Store(tmp_path)
    with store._tx() as db:
        db.execute("INSERT INTO devices(device_uid, name, token_hash, created_at) VALUES('d-00000001', 'Mac', 'x', 0)")
        db.execute("INSERT INTO agents(device_id, name, created_at, last_report_at) VALUES(1, 'Claude Code', 0, 0)")
        for uid, source in (("a-1", "a.jsonl"), ("b-1", "b.jsonl")):
            db.execute(
                "INSERT INTO segments(agent_id, segment_uid, session_id, source_file, position, role, text, ts, received_at, content_key) "
                "VALUES(1, ?, 's', ?, 0, 'user', '同一句话', '2026-11-16T00:00:00Z', 0, '')",
                (uid, source),
            )
        db.execute("CREATE TABLE IF NOT EXISTS memory_evidence (id INTEGER PRIMARY KEY, memory_id INTEGER, segment_id INTEGER, quote TEXT)")
        db.execute("INSERT INTO memory_evidence(memory_id, segment_id, quote) VALUES(7, 2, '同一句话')")
        db.execute("DELETE FROM meta WHERE key = 'segments_content_keyed'")  # a database from before the cleanup existed
    store.close()

    store = Store(tmp_path)  # what an upgraded server does when it starts
    with store._lock:
        assert [row["id"] for row in store._db.execute("SELECT id FROM segments")] == [1]
        assert store._db.execute("SELECT segment_id FROM memory_evidence").fetchone()["segment_id"] == 1
    store.close()


def test_unknown_paths_and_wrong_methods(server):
    assert server.call("GET", "/api/v1/nope")[0] == 404
    assert server.call("GET", "/api/v1/ingest", token=server.admin)[0] == 405
    status, body = server.call("POST", "/api/v1/pair", raw=b"{not json")
    assert (status, body["error"]) == (400, "invalid_json")


def test_writes_are_never_held_back_by_folding_the_log(tmp_path):
    """The background fold uses PASSIVE checkpoints only; the log file is capped instead of truncated."""
    import inspect

    from tl_server import store as store_module
    from tl_server.store import Store

    source = inspect.getsource(store_module.Store._checkpoint_loop)
    assert "PASSIVE" in source and "TRUNCATE" not in source and "RESTART" not in source
    store = Store(tmp_path)
    try:
        assert store._db.execute("PRAGMA journal_size_limit").fetchone()[0] == store_module.WAL_SHRINK_BYTES
    finally:
        store.close()
