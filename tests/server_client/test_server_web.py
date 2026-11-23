"""Signing in from a browser, the pages the server serves, and the overview."""

from __future__ import annotations

import http.client
import json
import threading
import time

import pytest

from tl_server.app import LOGIN_MAX_FAILURES, SESSION_COOKIE, create_server

PASSWORD = "test-password-for-local-dev"


@pytest.fixture()
def web(tmp_path):
    httpd = create_server(str(tmp_path), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def call(method, path, body=None, cookie=None, token=None, origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = f"{SESSION_COOKIE}={cookie}"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if origin:
            headers["Origin"] = origin
        try:
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            set_cookie = response.getheader("Set-Cookie") or ""
            session = ""
            if set_cookie.startswith(f"{SESSION_COOKIE}="):
                session = set_cookie.split(";")[0].split("=", 1)[1]
            is_json = (response.getheader("Content-Type") or "").startswith("application/json")
            return response.status, (json.loads(raw) if is_json else raw), session, response
        finally:
            conn.close()

    call.port = port
    call.data_dir = tmp_path
    call.admin = (tmp_path / "admin_token.txt").read_text().strip()
    yield call
    httpd.shutdown()
    httpd.server_close()
    httpd.store.close()


def sign_up(web) -> str:
    status, _body, session, _ = web("POST", "/api/v1/admin/session/setup", {"password": PASSWORD})
    assert status == 200 and session.startswith("tls_")
    return session


def test_the_page_and_its_assets_are_served_with_a_strict_policy(web):
    status, body, _, response = web("GET", "/")
    assert status == 200 and b"<title>" in body
    policy = response.getheader("Content-Security-Policy")
    assert "default-src 'self'" in policy and "unsafe-inline" not in policy
    assert web("GET", "/assets/app.js")[0] == 200
    assert web("GET", "/assets/app.css")[0] == 200
    assert web("GET", "/assets/../store.py")[0] == 404
    assert web("GET", "/assets/nope.js")[0] == 404


def test_first_visitor_sets_the_password_once(web):
    assert web("GET", "/api/v1/admin/session")[1] == {"setup_needed": True, "signed_in": False}
    status, body, _, _ = web("POST", "/api/v1/admin/session/setup", {"password": "short"})
    assert (status, body["error"]) == (400, "password_too_short")

    session = sign_up(web)
    assert web("GET", "/api/v1/admin/session", cookie=session)[1] == {"setup_needed": False, "signed_in": True}
    status, body, _, _ = web("POST", "/api/v1/admin/session/setup", {"password": "another-password"})
    assert (status, body["error"]) == (409, "already_set_up")

    stored = b"".join(path.read_bytes() for path in web.data_dir.glob("server.db*"))
    assert PASSWORD.encode() not in stored and session.encode() not in stored


def test_a_session_opens_the_admin_routes_and_sign_out_closes_them(web):
    assert web("GET", "/api/v1/admin/devices")[0] == 401
    session = sign_up(web)
    assert web("GET", "/api/v1/admin/devices", cookie=session)[0] == 200
    assert web("GET", "/api/v1/admin/devices", cookie="tls_not-a-session")[0] == 401
    assert web("POST", "/api/v1/admin/pairing-tokens", {}, cookie=session)[0] == 200

    assert web("POST", "/api/v1/admin/session/logout", {}, cookie=session)[0] == 200
    assert web("GET", "/api/v1/admin/devices", cookie=session)[0] == 401
    # The admin token keeps working for command-line use.
    assert web("GET", "/api/v1/admin/devices", token=web.admin)[0] == 200


def test_signing_in_with_the_password(web):
    sign_up(web)
    status, body, _, _ = web("POST", "/api/v1/admin/session/login", {"password": "wrong-password"})
    assert (status, body["error"]) == (401, "wrong_password")
    status, _, session, _ = web("POST", "/api/v1/admin/session/login", {"password": PASSWORD})
    assert status == 200
    assert web("GET", "/api/v1/admin/devices", cookie=session)[0] == 200


def test_repeated_wrong_passwords_are_slowed_down(web):
    sign_up(web)
    for _ in range(LOGIN_MAX_FAILURES):
        assert web("POST", "/api/v1/admin/session/login", {"password": "wrong-password"})[0] == 401
    status, body, _, _ = web("POST", "/api/v1/admin/session/login", {"password": PASSWORD})
    assert (status, body["error"]) == (429, "too_many_attempts")


def test_another_site_cannot_drive_a_signed_in_browser(web):
    session = sign_up(web)
    here = f"http://127.0.0.1:{web.port}"
    status, body, _, _ = web("POST", "/api/v1/admin/pairing-tokens", {}, cookie=session, origin="http://evil.example")
    assert (status, body["error"]) == (403, "cross_site_request")
    assert web("POST", "/api/v1/admin/pairing-tokens", {}, cookie=session, origin=here)[0] == 200
    status, body, _, _ = web("POST", "/api/v1/admin/session/login", {"password": PASSWORD}, origin="http://evil.example")
    assert (status, body["error"]) == (403, "cross_site_request")


def test_overview_counts_today_and_knows_who_is_online(web):
    session = sign_up(web)
    _, minted, _, _ = web("POST", "/api/v1/admin/pairing-tokens", {}, cookie=session)
    _, paired, _, _ = web(
        "POST", "/api/v1/pair",
        {"pairing_token": minted["pairing_token"], "device": {"device_uid": "device-uid-0001", "name": "Mac mini", "os": "macOS"}},
    )
    token = paired["device_token"]
    _, agent, _, _ = web("POST", "/api/v1/agents/report", {"agent": {"name": "Claude Code"}}, token=token)
    segments = [
        {"segment_uid": f"uid-{i:06d}", "session_id": "s", "source_file": "a.jsonl", "position": i,
         "role": "user", "text": "十个字的一句话啊啊啊", "ts": ""}
        for i in range(3)
    ]
    assert web("POST", "/api/v1/ingest", {"agent_id": agent["agent_id"], "segments": segments}, token=token)[0] == 200

    _, overview, _, _ = web("GET", f"/api/v1/admin/overview?since={time.time() - 3600}", cookie=session)
    assert (overview["segments_today"], overview["chars_today"], overview["segments_total"]) == (3, 30, 3)
    assert (overview["devices_total"], overview["devices_online"], overview["agents_total"]) == (1, 1, 1)
    assert overview["storage"]["total_bytes"] > overview["storage"]["free_bytes"] > 0
    assert [(r["device"], r["agent"], r["today"]) for r in overview["recent"]] == [("Mac mini", "Claude Code", 3)]

    _, later, _, _ = web("GET", f"/api/v1/admin/overview?since={time.time() + 3600}", cookie=session)
    assert (later["segments_today"], later["segments_total"]) == (0, 3)
    _, listing, _, _ = web("GET", "/api/v1/admin/devices", cookie=session)
    assert listing["devices"][0]["online"] is True


def test_the_password_is_changed_with_the_old_one_and_other_browsers_sign_in_again(web):
    first = sign_up(web)
    other = web("POST", "/api/v1/admin/session/login", {"password": PASSWORD})[2]
    new = "a-new-password-2026"
    status, body, _, _ = web("POST", "/api/v1/admin/session/password", {"old": "wrong-password", "password": new}, cookie=first)
    assert (status, body["error"]) == (401, "wrong_password")
    status, body, _, _ = web("POST", "/api/v1/admin/session/password", {"old": PASSWORD, "password": "short"}, cookie=first)
    assert (status, body["error"]) == (400, "password_too_short")
    assert web("POST", "/api/v1/admin/session/password", {"old": PASSWORD, "password": new})[0] == 401  # signed in only

    status, _, kept, _ = web("POST", "/api/v1/admin/session/password", {"old": PASSWORD, "password": new}, cookie=first)
    assert status == 200 and kept
    assert web("GET", "/api/v1/admin/devices", cookie=kept)[0] == 200  # this browser stays in
    assert web("GET", "/api/v1/admin/devices", cookie=other)[0] == 401  # the other one signs in again
    assert web("POST", "/api/v1/admin/session/login", {"password": PASSWORD})[0] == 401
    assert web("POST", "/api/v1/admin/session/login", {"password": new})[0] == 200


def test_a_forgotten_password_is_set_again_with_the_server_key_from_the_data_folder(web):
    old_session = sign_up(web)
    new = "set-again-with-the-key"
    status, body, _, _ = web("POST", "/api/v1/admin/session/reset", {"token": "tla_not-the-key", "password": new})
    assert (status, body["error"]) == (401, "wrong_server_key")
    status, body, _, _ = web("POST", "/api/v1/admin/session/reset", {"token": web.admin, "password": new},
                             origin="http://evil.example")
    assert (status, body["error"]) == (403, "cross_site_request")

    status, _, session, _ = web("POST", "/api/v1/admin/session/reset", {"token": web.admin + "\n", "password": new})
    assert status == 200 and web("GET", "/api/v1/admin/devices", cookie=session)[0] == 200
    assert web("GET", "/api/v1/admin/devices", cookie=old_session)[0] == 401
    assert web("POST", "/api/v1/admin/session/login", {"password": new})[0] == 200
    for _ in range(LOGIN_MAX_FAILURES):
        web("POST", "/api/v1/admin/session/reset", {"token": "tla_guess", "password": new})
    assert web("POST", "/api/v1/admin/session/reset", {"token": web.admin, "password": new})[0] == 429  # guessing is slowed down


def test_a_caller_hanging_up_mid_answer_is_not_logged_as_an_error(web, capfd):
    import socket

    for _ in range(3):
        with socket.create_connection(("127.0.0.1", web.port)) as conn:
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")  # reset on close
            conn.sendall(b"GET /assets/app.js HTTP/1.1\r\nHost: x\r\n\r\n")
    time.sleep(0.5)
    assert web("GET", "/api/v1/health")[0] == 200
    err = capfd.readouterr().err
    assert "Traceback" not in err and "Exception occurred" not in err


def test_every_sentence_on_the_admin_page_has_its_english(web):
    import re
    from pathlib import Path

    web_dir = Path(__file__).resolve().parents[2] / "tl_server" / "web"
    page = (web_dir / "app.js").read_text(encoding="utf-8")
    lookup = (web_dir / "i18n.js").read_text(encoding="utf-8")
    table = json.loads(lookup.split("window.TL_I18N = ", 1)[1].rstrip().rstrip(";"))
    keys = {key.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8") if "\\" in key else key
            for key in re.findall(r"\bt\('((?:[^'\\]|\\.)*)'", page)}
    missing = sorted(key for key in keys if key not in table["en"])
    assert not missing, missing[:10]
    for zh, en in list(table["en"].items()) + list(table["server"].items()):
        assert sorted(set(re.findall(r"\{\d+\}", zh))) == sorted(set(re.findall(r"\{\d+\}", en))), zh
    assert web("GET", "/assets/i18n.js")[0] == 200
    assert web("GET", "/assets/logo-en.png")[0] == 200 and web("GET", "/assets/logo-zh.png")[0] == 200
