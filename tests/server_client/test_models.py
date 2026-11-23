"""Model sources: native protocols, listing models, testing, and assigning jobs."""

from __future__ import annotations

import http.client
import json
import threading

import pytest

from tl_server import model_client
from tl_server.app import create_server
from tl_server.model_client import ModelError

from fake_model_server import GOOD_KEY, MODELS, start_fake_model_server


@pytest.fixture()
def fake():
    httpd = start_fake_model_server()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def admin(tmp_path):
    httpd = create_server(str(tmp_path), "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    token = (tmp_path / "admin_token.txt").read_text().strip()

    def call(method, path, body=None, auth=True, token=token):
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=30)
        headers = {"Authorization": f"Bearer {token}"} if auth and token else {}
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

    call.data_dir = tmp_path
    call.models = httpd.models
    yield call
    httpd.shutdown()
    httpd.server_close()
    httpd.store.close()


# ---- the three protocols, spoken natively -----------------------------------


@pytest.mark.parametrize("protocol", ["responses", "messages", "chat"])
def test_each_protocol_completes_and_lists_models(fake, protocol):
    reply = model_client.complete(fake.base_url, protocol, GOOD_KEY, "alpha-mini", "hi", system="be brief")
    assert reply["text"] == "OK" and (reply["input_tokens"], reply["output_tokens"]) == (7, 2)
    assert model_client.list_models(fake.base_url, protocol, GOOD_KEY) == MODELS


def test_requests_use_each_protocols_own_path_headers_and_body(fake):
    for protocol in ("responses", "messages", "chat"):
        model_client.complete(fake.base_url, protocol, GOOD_KEY, "alpha-mini", "hi", system="sys")
    posts = {
        entry[1]: (entry[0], entry[1], {name.lower(): value for name, value in entry[2].items()}, entry[3])
        for entry in fake.seen
        if entry[0] == "POST"
    }

    _, _, headers, body = posts["/v1/responses"]
    assert headers["authorization"] == f"Bearer {GOOD_KEY}" and "x-api-key" not in headers
    assert body["input"] == "hi" and body["instructions"] == "sys" and "messages" not in body

    _, _, headers, body = posts["/v1/messages"]
    assert headers["x-api-key"] == GOOD_KEY and headers["anthropic-version"] and "authorization" not in headers
    assert body["system"] == "sys" and body["messages"] == [{"role": "user", "content": "hi"}] and body["max_tokens"] > 0

    _, _, headers, body = posts["/v1/chat/completions"]
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def test_failures_are_named_by_what_the_owner_can_do_about_them(fake):
    def reason(**kwargs):
        args = {"base_url": fake.base_url, "protocol": "responses", "api_key": GOOD_KEY, "model": "alpha-mini"}
        args.update(kwargs)
        with pytest.raises(ModelError) as caught:
            model_client.probe(**args)
        return caught.value.reason

    assert reason(api_key="wrong") == "auth"
    assert reason(api_key="") == "auth"
    assert reason(api_key="broke-key") == "quota"
    assert reason(model="missing-model") == "not_found"
    assert reason(base_url="http://127.0.0.1:9/v1") == "unreachable"
    assert reason(base_url=fake.base_url.replace("/v1", "/weird/v1")) == "bad_response"
    assert reason(base_url=fake.base_url.replace("/v1", "/nowhere")) == "not_found"


# ---- sources ----------------------------------------------------------------


def make_source(admin, fake, **overrides):
    fields = {"name": "测试中转", "base_url": fake.base_url, "protocol": "responses", "api_key": GOOD_KEY, "model": "alpha-mini"}
    fields.update(overrides)
    status, source = admin("POST", "/api/v1/admin/models/sources", fields)
    assert status == 200, source
    return source


def test_model_routes_need_the_admin(admin):
    assert admin("GET", "/api/v1/admin/models", auth=False)[0] == 401
    assert admin("POST", "/api/v1/admin/models/sources", {"name": "x"}, auth=False)[0] == 401
    assert admin("GET", "/api/v1/admin/models/sources/1/key", auth=False)[0] == 401


def test_a_key_is_kept_out_of_the_database_and_out_of_listings(admin, fake):
    source = make_source(admin, fake)
    assert source["key_set"] is True and source["key_hint"] == "••••-123" and "api_key" not in source
    _, listing = admin("GET", "/api/v1/admin/models")
    assert GOOD_KEY not in json.dumps(listing)

    database = b"".join(path.read_bytes() for path in admin.data_dir.glob("server.db*"))
    assert GOOD_KEY.encode() not in database
    key_file = admin.data_dir / "model_keys.json"
    assert key_file.stat().st_mode & 0o077 == 0

    # Showing it again is an explicit, admin-only request.
    assert admin("GET", f"/api/v1/admin/models/sources/{source['id']}/key")[1] == {"api_key": GOOD_KEY}


def test_bad_source_fields_are_refused(admin, fake):
    for bad in ({"protocol": "telepathy"}, {"base_url": "ftp://x.example/v1"}, {"name": ""}):
        fields = {"name": "x", "base_url": fake.base_url, "protocol": "chat"}
        fields.update(bad)
        status, body = admin("POST", "/api/v1/admin/models/sources", fields)
        assert (status, body["error"]) == (400, "invalid_field")


def test_pulling_models_and_testing_a_source(admin, fake):
    source = make_source(admin, fake, model="")
    sid = source["id"]
    assert source["tested_ok"] is False

    status, body = admin("POST", f"/api/v1/admin/models/sources/{sid}/test", {})
    assert (status, body["error"]) == (400, "model_required")

    pulled = admin("POST", f"/api/v1/admin/models/sources/{sid}/models", {})[1]
    assert pulled["models"] == MODELS and set(pulled["levels"]) == {"alpha-large"}
    _, updated = admin("POST", f"/api/v1/admin/models/sources/{sid}", {"model": "alpha-mini"})
    assert updated["models"] == MODELS and updated["tested_ok"] is False

    status, result = admin("POST", f"/api/v1/admin/models/sources/{sid}/test", {})
    assert status == 200 and result["ok"] is True and result["latency_ms"] >= 0
    _, listing = admin("GET", "/api/v1/admin/models")
    assert listing["sources"][0]["tested_ok"] is True


def test_changing_anything_that_affects_a_call_requires_testing_again(admin, fake):
    sid = make_source(admin, fake)["id"]
    admin("POST", f"/api/v1/admin/models/sources/{sid}/test", {})
    assert admin("POST", f"/api/v1/admin/models/sources/{sid}", {"name": "改个名字"})[1]["tested_ok"] is True
    for change in ({"protocol": "messages"}, {"model": "alpha-large"}, {"api_key": "another-key"}, {"base_url": fake.base_url + "/"}):
        admin("POST", f"/api/v1/admin/models/sources/{sid}", {"protocol": "responses", "model": "alpha-mini", "api_key": GOOD_KEY})
        admin("POST", f"/api/v1/admin/models/sources/{sid}/test", {})
        tested = admin("POST", f"/api/v1/admin/models/sources/{sid}", change)[1]["tested_ok"]
        # A trailing slash is the same address; everything else is a real change.
        assert tested is ("base_url" in change), change


def test_a_failed_test_says_why(admin, fake):
    sid = make_source(admin, fake, api_key="broke-key")["id"]
    status, result = admin("POST", f"/api/v1/admin/models/sources/{sid}/test", {})
    assert status == 200 and result["ok"] is False and result["reason"] == "quota"
    source = admin("GET", "/api/v1/admin/models")[1]["sources"][0]
    assert source["tested_ok"] is False and source["last_error_reason"] == "quota"

    status, body = admin("POST", f"/api/v1/admin/models/sources/{sid}/models", {})
    assert (status, body["error"]) == (502, "model_quota")


# ---- jobs -------------------------------------------------------------------


def test_jobs_are_assigned_freely_and_only_to_models_that_answer(admin, fake):
    relay = make_source(admin, fake, name="中转")["id"]
    local = make_source(admin, fake, name="本地", protocol="messages", model="alpha-large")["id"]

    _, listing = admin("GET", "/api/v1/admin/models")
    assert listing["slots"] == {slot: {"main": None, "backup": None, "effort": ""} for slot in ("import", "daily", "reflect")}

    status, slot = admin("POST", "/api/v1/admin/models/slots", {"slot": "import", "role": "main", "source_id": relay, "model": "alpha-mini"})
    assert status == 200 and slot["main"] == {"source_id": relay, "model": "alpha-mini"}
    # The same source can serve another job with a different model.
    admin("POST", "/api/v1/admin/models/slots", {"slot": "reflect", "role": "main", "source_id": relay, "model": "alpha-large"})
    admin("POST", "/api/v1/admin/models/slots", {"slot": "import", "role": "backup", "source_id": local})
    admin("POST", "/api/v1/admin/models/slots", {"slot": "daily", "role": "main", "source_id": local})

    slots = admin("GET", "/api/v1/admin/models")[1]["slots"]
    assert slots["import"] == {"main": {"source_id": relay, "model": "alpha-mini"}, "backup": {"source_id": local, "model": "alpha-large"}, "effort": ""}
    assert slots["reflect"]["main"] == {"source_id": relay, "model": "alpha-large"}
    assert slots["daily"] == {"main": {"source_id": local, "model": "alpha-large"}, "backup": None, "effort": ""}

    # A model that does not answer is not accepted, and the old choice stays.
    status, body = admin("POST", "/api/v1/admin/models/slots", {"slot": "import", "role": "main", "source_id": relay, "model": "missing-model"})
    assert (status, body["error"]) == (422, "model_not_found")
    assert admin("GET", "/api/v1/admin/models")[1]["slots"]["import"]["main"]["model"] == "alpha-mini"

    chain = admin.models.resolve("import")
    assert [(step["role"], step["name"], step["protocol"], step["model"], step["api_key"]) for step in chain] == [
        ("main", "中转", "responses", "alpha-mini", GOOD_KEY),
        ("backup", "本地", "messages", "alpha-large", GOOD_KEY),
    ]

    # Clearing a backup, and bad requests.
    assert admin("POST", "/api/v1/admin/models/slots", {"slot": "import", "role": "backup", "source_id": None})[1]["backup"] is None
    assert admin("POST", "/api/v1/admin/models/slots", {"slot": "vector", "role": "main", "source_id": relay})[0] == 400
    assert admin("POST", "/api/v1/admin/models/slots", {"slot": "import", "role": "third", "source_id": relay})[0] == 400


def test_deleting_a_source_frees_its_jobs_and_forgets_its_key(admin, fake):
    sid = make_source(admin, fake)["id"]
    admin("POST", "/api/v1/admin/models/slots", {"slot": "daily", "role": "main", "source_id": sid})
    assert admin("POST", f"/api/v1/admin/models/sources/{sid}/delete", {})[0] == 200
    _, listing = admin("GET", "/api/v1/admin/models")
    assert listing["sources"] == [] and listing["slots"]["daily"]["main"] is None
    assert GOOD_KEY not in (admin.data_dir / "model_keys.json").read_text()
    assert admin("POST", f"/api/v1/admin/models/sources/{sid}/test", {})[0] == 404
    assert admin.models.resolve("daily") == []



# ---- streaming and thinking ------------------------------------------------------


@pytest.mark.parametrize("protocol", ["responses", "messages", "chat"])
def test_answers_are_streamed_in_each_protocol(fake, protocol):
    from tl_server import model_client

    fake.reply_text = "流式回答:服务端在 NAS 上。"
    reply = model_client.complete(fake.base_url, protocol, GOOD_KEY, "alpha-mini", "问", system="规则", max_tokens=100)
    assert reply["text"] == "流式回答:服务端在 NAS 上。"
    assert (reply["input_tokens"], reply["output_tokens"]) == (7, 2)
    sent = [entry[3] for entry in fake.seen if entry[0] == "POST"][-1]
    assert sent["stream"] is True
    assert ("stream_options" in sent) == (protocol == "chat")


@pytest.mark.parametrize(
    "protocol, field, check",
    [
        ("responses", "reasoning", lambda body: body["reasoning"] == {"effort": "ultra"} and body["max_output_tokens"] == 100 + 32000),
        ("messages", "output_config", lambda body: body["thinking"] == {"type": "adaptive"} and body["output_config"] == {"effort": "ultra"}
         and body["max_tokens"] == 100 + 32000 and "budget_tokens" not in json.dumps(body)),
        ("chat", "reasoning_effort", lambda body: body["reasoning_effort"] == "ultra" and body["max_tokens"] == 100 + 32000),
    ],
)
def test_the_models_own_level_word_is_sent_as_is_in_the_protocols_field(fake, protocol, field, check):
    from tl_server import model_client

    fake.reply_text = "好"
    reply = model_client.complete(fake.base_url, protocol, GOOD_KEY, "alpha-mini", "问", max_tokens=100, effort="ultra")
    assert reply["text"] == "好"  # thinking is never part of the answer
    sent = [entry[3] for entry in fake.seen if entry[0] == "POST"][-1]
    assert check(sent)
    model_client.complete(fake.base_url, protocol, GOOD_KEY, "alpha-mini", "问", max_tokens=100)
    plain = [entry[3] for entry in fake.seen if entry[0] == "POST"][-1]
    assert field not in plain and "thinking" not in plain  # the model's default unless a level was chosen


def test_the_levels_a_model_reports_are_pulled_with_the_model_list(admin, fake):
    relay = make_source(admin, fake, name="中转")["id"]
    status, fetched = admin("POST", f"/api/v1/admin/models/sources/{relay}/models", {})
    assert status == 200 and fetched["levels"] == {"alpha-large": {"levels": ["low", "xhigh"], "default": "low"}}
    claude = make_source(admin, fake, name="官方", protocol="messages", model="alpha-mini")["id"]
    fetched = admin("POST", f"/api/v1/admin/models/sources/{claude}/models", {})[1]
    assert fetched["levels"] == {"alpha-mini": {"levels": ["low", "max"], "default": ""}}  # unsupported levels left out
    listed = {source["id"]: source for source in admin("GET", "/api/v1/admin/models")[1]["sources"]}
    assert listed[relay]["levels"]["alpha-large"]["levels"] == ["low", "xhigh"]


def test_an_endpoint_that_will_not_stream_still_answers(fake):
    from tl_server import model_client

    fake.reply_text = "整段回答"
    fake.ignore_stream = True
    assert model_client.complete(fake.base_url, "responses", GOOD_KEY, "alpha-mini", "问")["text"] == "整段回答"
    fake.ignore_stream, fake.refuse_stream = False, True
    assert model_client.complete(fake.base_url, "chat", GOOD_KEY, "alpha-mini", "问")["text"] == "整段回答"
    assert [entry[3].get("stream") for entry in fake.seen if entry[0] == "POST"][-2:] == [True, None]


def test_each_job_keeps_its_own_thinking_level_once_the_model_answered_with_it(admin, fake):
    relay = make_source(admin, fake, name="中转")["id"]
    admin("POST", "/api/v1/admin/models/slots", {"slot": "daily", "role": "main", "source_id": relay, "model": "alpha-mini"})
    status, slot = admin("POST", "/api/v1/admin/models/slots/effort", {"slot": "daily", "effort": "xhigh"})
    assert (status, slot["effort"]) == (200, "xhigh")
    sent = [entry[3] for entry in fake.seen if entry[0] == "POST"][-1]
    assert sent["reasoning"] == {"effort": "xhigh"}  # the level was tried for real before it was kept
    refused = admin("POST", "/api/v1/admin/models/slots/effort", {"slot": "daily", "effort": "bogus"})
    assert refused[0] == 422
    after = admin("GET", "/api/v1/admin/models")[1]
    assert after["slots"]["daily"]["effort"] == "xhigh"  # not replaced by a level the model refused
    assert next(s for s in after["sources"] if s["id"] == relay)["tested_ok"] is True  # the source is still fine
    assert admin("POST", "/api/v1/admin/models/slots/effort", {"slot": "daily", "effort": "Not A Level!"})[0] == 400
    assert admin("POST", "/api/v1/admin/models/slots/effort", {"slot": "daily", "effort": ""})[1]["effort"] == ""
    assert after["slots"]["import"]["effort"] == ""


def test_levels_from_an_agents_model_catalog_become_choices_for_a_relay_that_reports_none(admin, fake, tmp_path):
    from tl_client.catalogs import read_catalog

    catalog = tmp_path / "models_cache.json"
    catalog.write_text(json.dumps({"fetched_at": "x", "models": [
        {"slug": "alpha-mini", "default_reasoning_level": "low",
         "supported_reasoning_levels": [{"effort": "low"}, {"effort": "medium"}, {"effort": "xhigh"}, {"effort": "ultra"}]},
        {"slug": "no-levels"},
    ]}), encoding="utf-8")
    pulled = read_catalog(str(catalog))
    assert pulled == [{"id": "alpha-mini", "levels": ["low", "medium", "xhigh", "ultra"], "default": "low"}]
    assert read_catalog(str(tmp_path / "missing.json")) == []

    relay = make_source(admin, fake, name="中转", model="alpha-mini")["id"]
    admin("POST", f"/api/v1/admin/models/sources/{relay}/models", {})
    token = admin("POST", "/api/v1/admin/pairing-tokens", {})[1]["pairing_token"]
    device = admin("POST", "/api/v1/pair", {"pairing_token": token, "device": {"device_uid": "levels-device-01", "name": "Mac"}}, token=None)[1]
    status, done = admin("POST", "/api/v1/model-levels", {"models": pulled, "agent": "Codex"}, token=device["device_token"])
    assert (status, done["recorded"]) == (200, 1)
    source = next(s for s in admin("GET", "/api/v1/admin/models")[1]["sources"] if s["id"] == relay)
    assert source["levels"]["alpha-mini"] == {"levels": ["low", "medium", "xhigh", "ultra"], "default": "low", "from": "Codex @ Mac"}
    # The endpoint's own report wins over an agent's catalog.
    assert source["levels"]["alpha-large"]["from"] == "endpoint"
    assert admin("POST", "/api/v1/model-levels", {"models": [{"id": "x", "levels": ["Not A Level"]}]}, token=device["device_token"])[0] == 400
