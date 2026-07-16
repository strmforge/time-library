import importlib
import json
import os
import subprocess
import sys
import threading
import types
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reload_dialog(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv(
        "MEMCORE_CONFIG",
        str(ROOT / "config" / "memcore.json"),
    )
    for name in ["config_loader", "src.config_loader", "dialog_entry_proxy", "src.dialog_entry_proxy"]:
        sys.modules.pop(name, None)
    return importlib.import_module("dialog_entry_proxy")


def _reload_p6(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv(
        "MEMCORE_CONFIG",
        str(ROOT / "config" / "memcore.json"),
    )
    for name in ["config_loader", "src.config_loader", "p6_console", "src.p6_console"]:
        sys.modules.pop(name, None)
    return importlib.import_module("p6_console")


def test_dialog_entry_defaults_loopback_and_requires_token_for_lan(tmp_path, monkeypatch):
    proxy = _reload_dialog(tmp_path, monkeypatch)

    assert proxy.DEFAULT_BIND_HOST == "127.0.0.1"
    assert proxy._is_loopback_client(("127.0.0.1", 12345)) is True
    assert proxy._is_loopback_client(("::1", 12345, 0, 0)) is True
    assert proxy._is_loopback_client(("192.0.2.10", 12345)) is False

    headers = types.SimpleNamespace(get=lambda name, default="": "")
    assert proxy._management_request_allowed(("127.0.0.1", 12345), headers) is True
    assert proxy._management_request_allowed(("192.0.2.10", 12345), headers) is False
    assert proxy._entry_request_allowed("/entry/openclaw-before-dispatch", ("127.0.0.1", 12345), headers) is True
    assert proxy._entry_request_allowed("/entry/openclaw-before-dispatch", ("192.0.2.10", 12345), headers) is False

    monkeypatch.setenv("MEMCORE_DIALOG_ENTRY_TOKEN", "lan-secret")
    bearer_headers = types.SimpleNamespace(
        get=lambda name, default="": "Bearer lan-secret" if name == "Authorization" else default
    )
    assert proxy._entry_request_allowed(
        "/entry/openclaw-before-dispatch",
        ("192.0.2.10", 12345),
        bearer_headers,
    ) is True
    assert proxy._entry_request_allowed("/flags", ("192.0.2.10", 12345), bearer_headers) is False


def test_dialog_entry_writes_runtime_token_for_lan_clients(tmp_path, monkeypatch):
    proxy = _reload_dialog(tmp_path, monkeypatch)
    token_path = Path(proxy.DIALOG_ENTRY_TOKEN_PATH)

    assert not token_path.exists()
    token = proxy._dialog_entry_token()

    assert token
    assert token_path.exists()
    assert token_path.read_text(encoding="utf-8").strip() == token


def test_dialog_entry_env_token_seeds_runtime_token_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_DIALOG_ENTRY_TOKEN", "env-lan-secret")
    proxy = _reload_dialog(tmp_path, monkeypatch)
    token_path = Path(proxy.DIALOG_ENTRY_TOKEN_PATH)

    assert proxy._dialog_entry_token() == "env-lan-secret"
    assert token_path.read_text(encoding="utf-8").strip() == "env-lan-secret"


def test_dialog_entry_rejects_cross_origin_and_bad_host_without_breaking_lan_token(tmp_path, monkeypatch):
    proxy = _reload_dialog(tmp_path, monkeypatch)

    def headers(values):
        return types.SimpleNamespace(get=lambda name, default="": values.get(name, default))

    assert proxy._entry_request_allowed(
        "/entry/openclaw-before-dispatch",
        ("127.0.0.1", 12345),
        headers({}),
    ) is True
    assert proxy._entry_request_allowed(
        "/entry/openclaw-before-dispatch",
        ("127.0.0.1", 12345),
        headers({"Origin": "http://evil.example", "Host": "127.0.0.1:9860"}),
    ) is False
    assert proxy._entry_request_allowed(
        "/entry/openclaw-before-dispatch",
        ("127.0.0.1", 12345),
        headers({"Origin": "http://127.0.0.1:9860", "Host": "192.0.2.10:9860"}),
    ) is False
    assert proxy._management_request_allowed(
        ("127.0.0.1", 12345),
        headers({"Origin": "http://evil.example", "Host": "127.0.0.1:9860"}),
    ) is False

    monkeypatch.setenv("MEMCORE_DIALOG_ENTRY_TOKEN", "lan-secret")
    assert proxy._entry_request_allowed(
        "/entry/openclaw-before-dispatch",
        ("192.0.2.10", 12345),
        headers({
            "Authorization": "Bearer lan-secret",
            "Origin": "http://192.0.2.20:18789",
            "Host": "192.0.2.10:9860",
        }),
    ) is True
    assert proxy._entry_request_allowed(
        "/entry/openclaw-before-dispatch",
        ("192.0.2.10", 12345),
        headers({
            "Authorization": "Bearer lan-secret",
            "Origin": "http://evil.example",
            "Host": "192.0.2.10:9860",
        }),
    ) is False


def test_p6_console_rejects_cross_origin_browser_post(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    token = p6.CONSOLE_CSRF_TOKEN

    def headers(values):
        return types.SimpleNamespace(get=lambda name, default="": values.get(name, default))

    assert p6._browser_post_allowed(
        headers({}),
        ("127.0.0.1", 12345),
    ) is True
    assert p6._browser_post_allowed(
        headers({
            "Origin": "http://127.0.0.1:9850",
            "Host": "127.0.0.1:9850",
            "X-Memcore-Console-Token": token,
        }),
        ("127.0.0.1", 12345),
    ) is True
    assert p6._browser_post_allowed(
        headers({
            "Origin": "http://evil.example",
            "Host": "127.0.0.1:9850",
            "X-Memcore-Console-Token": token,
        }),
        ("127.0.0.1", 12345),
    ) is False
    assert p6._browser_post_allowed(
        headers({
            "Origin": "http://127.0.0.1:9850",
            "Host": "127.0.0.1:9850",
        }),
        ("127.0.0.1", 12345),
    ) is False
    assert p6._browser_post_allowed(
        headers({
            "Origin": "http://127.0.0.1:9850",
            "Host": "127.0.0.1:9850",
            "X-Memcore-Console-Token": token,
        }),
        ("192.0.2.10", 12345),
    ) is False


def test_p6_console_writes_runtime_token_for_local_helpers(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    token_path = Path(p6.CONSOLE_TOKEN_PATH)

    assert token_path.exists()
    assert token_path.read_text(encoding="utf-8").strip() == p6.CONSOLE_CSRF_TOKEN


def test_p6_sensitive_action_posts_require_console_token(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    token = p6.CONSOLE_CSRF_TOKEN

    def headers(values):
        return types.SimpleNamespace(get=lambda name, default="": values.get(name, default))

    assert p6._action_post_requires_console_token("/api/v1/records/guardian/backfill") is True
    assert p6._action_post_requires_console_token("/api/v1/source-systems/claude_desktop/raw-ingest") is True
    assert p6._action_post_requires_console_token("/api/v1/zhiyi/experiences/exp-1/recycle") is True
    assert p6._action_post_requires_console_token("/api/v1/hermes/feedback-candidates/c1/actions") is True
    assert p6._action_post_requires_console_token("/api/v1/hermes/native-learning/autonomous-loop/run") is True
    assert p6._action_post_requires_console_token("/api/v1/update/apply") is True
    assert p6._action_post_requires_console_token("/api/v1/zhixing/replay/dry-run") is False
    assert p6._action_post_requires_console_token("/api/v1/source-systems/claude_desktop/raw-ingest/dry-run") is False

    assert p6._strict_action_post_allowed(
        headers({
            "Origin": "http://127.0.0.1:9850",
            "Host": "127.0.0.1:9850",
            "X-Memcore-Console-Token": token,
        }),
        ("127.0.0.1", 12345),
    ) is True
    assert p6._strict_action_post_allowed(headers({}), ("127.0.0.1", 12345)) is False
    assert p6._strict_action_post_allowed(
        headers({
            "Origin": "http://127.0.0.1:9850",
            "Host": "127.0.0.1:9850",
        }),
        ("127.0.0.1", 12345),
    ) is False
    assert p6._strict_action_post_allowed(
        headers({
            "Origin": "http://evil.example",
            "Host": "127.0.0.1:9850",
            "X-Memcore-Console-Token": token,
        }),
        ("127.0.0.1", 12345),
    ) is False
    assert p6._strict_action_post_allowed(
        headers({
            "Origin": "http://127.0.0.1:9850",
            "Host": "192.0.2.10:9850",
            "X-Memcore-Console-Token": token,
        }),
        ("127.0.0.1", 12345),
    ) is False
    assert p6._strict_action_post_allowed(
        headers({
            "Origin": "http://127.0.0.1:9850",
            "Host": "127.0.0.1:9850",
            "X-Memcore-Console-Token": token,
        }),
        ("192.0.2.10", 12345),
    ) is False


def test_p6_sensitive_action_http_post_gate_blocks_missing_token(tmp_path, monkeypatch):
    p6 = _reload_p6(tmp_path, monkeypatch)
    server = p6.ThreadingHTTPServer(("127.0.0.1", 0), p6.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post_json(path, body, headers=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req_headers = {"Content-Type": "application/json"}
        req_headers.update(headers or {})
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}{path}",
            data=data,
            headers=req_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8"))
            except Exception:
                return exc.code, {}

    try:
        status, blocked = post_json("/api/v1/records/guardian/backfill", {
            "limit": 1,
            "source_systems": ["unsupported_test_source"],
        })
        assert status == 403
        if blocked:
            assert blocked["error"] == "local console action token required"

        status, allowed = post_json(
            "/api/v1/records/guardian/backfill",
            {
                "limit": 1,
                "source_systems": ["unsupported_test_source"],
            },
            {
                "Origin": f"http://127.0.0.1:{server.server_address[1]}",
                "X-Memcore-Console-Token": p6.CONSOLE_CSRF_TOKEN,
            },
        )
        assert status == 400
        assert allowed["results"][0]["error"] == "backfill_not_implemented_for_source_system"
    finally:
        server.shutdown()
        server.server_close()


def test_console_record_guardian_backfill_is_explicit_post_action():
    console = (ROOT / "src" / "p6_console.py").read_text(encoding="utf-8")

    assert 'self.path == "/api/v1/records/guardian/backfill"' in console
    assert "run_raw_backfill" in console
    assert 'path == "/api/v1/records/guardian/status"' in console
    assert 'write_index=False' in console
    assert "SENSITIVE_ACTION_POST_PATHS" in console
    assert '"/api/v1/records/guardian/backfill"' in console
    assert "reject_unsafe_action_post" in console


def test_authorization_contract_does_not_claim_without_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in ["platform_autodiscovery", "src.platform_autodiscovery"]:
        sys.modules.pop(name, None)
    autodiscovery = importlib.import_module("platform_autodiscovery")

    report = autodiscovery.build_autodiscovery({})
    contract = report["authorization_contract"]

    assert "can_auto_connect_without_authorization" not in contract
    assert "can_write_platform_config_without_authorization" not in contract
    assert "can_parse_chat_bodies_without_authorization" not in contract
    assert contract["host_self_install_receipt_required"] is True
    assert contract["time_library_platform_config_write_supported"] is False
    assert contract["chat_body_parser_requires_verified_collector"] is True
    assert contract["chat_body_parser_requires_separate_authorization"] is True


def test_dialog_entry_lan_install_path_is_explicit_and_tokened():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    guardian = (ROOT / "tools" / "windows_guardian.ps1").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    plugin = (ROOT / "system" / "openclaw" / "plugins" / "time-library-native" / "index.js").read_text(encoding="utf-8")

    for text in (windows, guardian, linux, mac):
        assert "MEMCORE_DIALOG_ENTRY_TOKEN" in text
        assert "--host" in text
        assert "dialog_entry_host" in text
        assert "dialog_entry_token" in text

    assert "[string]$DialogEntryHost = \"127.0.0.1\"" in windows
    assert "[string]$DialogEntryToken = \"\"" in windows
    assert "Ensure-DialogEntryToken" in windows
    assert "New-DialogEntryTokenValue" in windows
    assert "IncludeDialogEntryToken" in windows
    assert "IncludeDialogEntryToken" in guardian
    assert "if ($IncludeDialogEntryToken -and $DialogEntryToken)" in windows
    assert "if ($IncludeDialogEntryToken -and $DialogEntryToken)" in guardian
    assert "-IncludeDialogEntryToken" in windows
    assert "-IncludeDialogEntryToken" in guardian
    assert 'dialog_entry_token and log_name == "dialog-entry"' in linux
    assert 'dialog_entry_token and log_name == "dialog-entry"' in mac
    assert "$dialogHost = Get-DialogEntryHost" in guardian
    assert "$host = Get-DialogEntryHost" not in guardian
    assert "$host = [string]$cfg.services.dialog_entry_host" not in guardian
    assert "dialogEntryToken" in windows
    assert '"runtime"' in windows
    assert "authToken" in plugin
    assert "headers.Authorization = `Bearer ${authToken}`" in plugin
    assert "--dialog-entry-host HOST" in linux
    assert "--dialog-entry-token TOKEN" in linux
    assert "ensure_dialog_entry_token" in linux
    assert "--exclude 'runtime/'" in linux
    assert "--dialog-entry-host HOST" in mac
    assert "--dialog-entry-token TOKEN" in mac
    assert "ensure_dialog_entry_token" in mac
    assert "--exclude 'runtime/'" in mac


def test_openclaw_zhiyi_native_is_passive_by_default():
    plugin = (ROOT / "system" / "openclaw" / "plugins" / "time-library-native" / "index.js").read_text(encoding="utf-8")
    manifest = (ROOT / "system" / "openclaw" / "plugins" / "time-library-native" / "openclaw.plugin.json").read_text(encoding="utf-8")

    assert "const DEFAULT_FORCE_ZHIYI_DIRECT = false;" in plugin
    assert "enabled: asBool(cfg.enabled, false)" in plugin
    assert "enableModelCall: asBool(cfg.enableModelCall, false)" in plugin
    assert "forceZhiyiDirect: asBool(cfg.forceZhiyiDirect, DEFAULT_FORCE_ZHIYI_DIRECT)" in plugin
    assert '"default": false' in manifest
    assert "DEFAULT_FORCE_ZHIYI_DIRECT = true" not in plugin
    assert "enableModelCall: asBool(cfg.enableModelCall, true)" not in plugin


def test_installers_do_not_enable_openclaw_zhiyi_takeover_by_default():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    feature_flags = json.loads((ROOT / "config" / "feature_flags.json").read_text(encoding="utf-8"))
    default_feature_flags = json.loads((ROOT / "config" / "default_feature_flags.json").read_text(encoding="utf-8"))

    for key in ("zhiyi_direct", "zhiyi_inject", "openclaw_passive_auto_inject", "openclaw_rpc", "fts5_recall"):
        assert feature_flags[key] is False
        assert default_feature_flags[key] is False

    for script in (linux, mac):
        assert "openclaw plugins enable time-library-native" not in script
        assert '"zhiyi_direct": False' in script
        assert '"zhiyi_inject": False' in script
        assert '"openclaw_passive_auto_inject": False' in script
        assert '"openclaw_rpc": False' in script
        assert '"enableModelCall": False' in script
        assert '"forceZhiyiDirect": False' in script
        assert 'entry["enabled"] = False' in script
        assert '"enableModelCall": True' not in script
        assert '"forceZhiyiDirect": True' not in script

    assert "openclaw plugins enable time-library-native" not in windows
    assert "$passiveFlags = [ordered]@{" in windows
    assert "zhiyi_direct = $false" in windows
    assert "zhiyi_inject = $false" in windows
    assert "openclaw_passive_auto_inject = $false" in windows
    assert "openclaw_rpc = $false" in windows
    assert '"enableModelCall": False' in windows
    assert '"forceZhiyiDirect": False' in windows
    assert 'entry["enabled"] = False' in windows
    assert '"enableModelCall": True' not in windows
    assert '"forceZhiyiDirect": True' not in windows


def test_installers_record_passive_delivery_migration_for_existing_flags():
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    for script, source_name in ((linux, "linux_full_install"), (mac, "macos_full_install")):
        assert "passive_delivery_migration" in script
        assert source_name in script
        assert "changed_keys = [key for key, value in passive_flags.items() if flags.get(key) != value]" in script
        assert ".time_library-passive-migration." in script
        assert "logs\" / \"passive_delivery_migration.jsonl" in script
        assert "Safety migration after OpenClaw direct-answer boundary fix" in script
        assert "explicit opt-in must be re-enabled intentionally after install" in script

    assert "passive_delivery_migration" in windows
    assert "windows_full_install" in windows
    assert "$passiveFlags = [ordered]@{" in windows
    assert "$flags.Contains($key)" in windows
    assert ".time_library-passive-migration." in windows
    assert "logs\\passive_delivery_migration.jsonl" in windows
    assert "Safety migration after OpenClaw direct-answer boundary fix" in windows
    assert "explicit opt-in must be re-enabled intentionally after install" in windows


def test_dialog_entry_default_flags_do_not_enable_active_chains(tmp_path, monkeypatch):
    proxy = _reload_dialog(tmp_path, monkeypatch)

    assert proxy.get_flags()["zhiyi_direct"] is False
    assert proxy.get_flags()["zhiyi_inject"] is False
    assert proxy.get_flags()["openclaw_passive_auto_inject"] is False
    assert proxy.get_flags()["fts5_recall"] is False
    assert proxy.get_flags()["openclaw_rpc"] is False
    assert proxy.get_flags()["passthrough"] is True
    assert proxy.is_enabled("zhiyi_direct") is False
    assert proxy.is_enabled("openclaw_rpc") is False


def test_openclaw_before_dispatch_does_not_handle_ordinary_chat(tmp_path, monkeypatch):
    proxy = _reload_dialog(tmp_path, monkeypatch)
    handler = object.__new__(proxy.DialogEntryHandler)

    result = handler.handle_openclaw_before_dispatch({
        "message": "现在的磁盘问题是 27 个盘全在机箱里，不知道哪个盘有问题",
        "session_key": "openclaw-test",
        "channel": "webchat",
    })

    assert result["handled"] is False
    assert result["text"] == ""
    assert result["reason"] == "openclaw_before_dispatch_requires_explicit_zhiyi_entry"
    assert result["action"] == "pass_through"
    assert result["openclaw_write_performed"] is False
    assert result["memory_authority"]["granted_authority"] == "passive"
    assert result["memory_authority"]["can_direct_answer"] is False
    assert result["memory_authority"]["can_platform_act"] is False


def test_openclaw_before_dispatch_explicit_entry_still_respects_disabled_flag(tmp_path, monkeypatch):
    proxy = _reload_dialog(tmp_path, monkeypatch)
    handler = object.__new__(proxy.DialogEntryHandler)

    result = handler.handle_openclaw_before_dispatch({
        "message": "/zhiyi 继续这个项目",
        "session_key": "openclaw-test",
        "channel": "webchat",
    })

    assert result["handled"] is False
    assert result["text"] == ""
    assert result["status"] == "disabled"
    assert result["chain"] == "F3_zhiyi_direct"
    assert result["reason"] == "flag zhiyi_direct=false"
    assert result["platform_reply_returned"] is False
    assert result["memory_authority"]["granted_authority"] == "direct_answer"
    assert result["memory_authority"]["can_platform_act"] is False


def test_platform_delivery_requires_separate_platform_act_authorization(tmp_path, monkeypatch):
    proxy = _reload_dialog(tmp_path, monkeypatch)
    handler = object.__new__(proxy.DialogEntryHandler)
    called = {"value": False}

    def fake_forward(*_args, **_kwargs):
        called["value"] = True
        return {"ok": True}

    handler._forward_to_openclaw = fake_forward
    result = handler.maybe_deliver_platform_answer(
        {
            "platform_delivery": {
                "enabled": True,
                "platform": "openclaw",
                "delivery_runtime_kind": "ws_rpc_forward",
                "session_key": "agent:test:session",
            }
        },
        "/zhiyi 继续",
        "agent:test:session",
        {
            "status": "ok",
            "chain": "F3_zhiyi_direct",
            "answer": "本地上下文",
            "audit": {"zhiyi_entry": {"requested": True}},
        },
    )

    assert called["value"] is False
    assert result["platform_delivery"]["executed"] is False
    assert result["platform_delivery"]["reason"] == "platform_act_requires_explicit_authorization"
    assert result["platform_delivery"]["memory_authority"]["granted_authority"] == "direct_answer"
    assert result["platform_delivery"]["memory_authority"]["can_platform_act"] is False


def test_platform_delivery_request_requires_explicit_runtime_and_session_capabilities(tmp_path, monkeypatch):
    proxy = _reload_dialog(tmp_path, monkeypatch)

    request = proxy._platform_delivery_request(
        {
            "platform_delivery": {
                "enabled": True,
                "platform": "openclaw",
                "delivery_runtime_kind": "ws_rpc_forward",
                "session_key": "agent:test:session",
            },
        },
        session_id="agent:test:session",
    )

    assert request["requested"] is True
    assert request["enabled"] is True
    assert request["platform"] == "openclaw"
    assert request["runtime_kind"] == "ws_rpc_forward"
    assert request["session_key"] == "agent:test:session"


def test_openclaw_native_event_does_not_abort_or_deliver_without_platform_act_authorization(tmp_path, monkeypatch):
    proxy = _reload_dialog(tmp_path, monkeypatch)
    handler = object.__new__(proxy.DialogEntryHandler)
    called = {"forward": False, "abort": False}

    def fake_abort(*_args, **_kwargs):
        called["abort"] = True
        return {"attempted": True, "aborted": True}

    def fake_forward(*_args, **_kwargs):
        called["forward"] = True
        return {"ok": True}

    handler._abort_openclaw_active_run = fake_abort
    handler._forward_to_openclaw = fake_forward
    result = handler.handle_openclaw_native_event(
        {
            "event": {
                "id": "event-1",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "/zhiyi 继续"}],
                },
            },
            "session_key": "agent:test:session",
            "confirm_platform_act": True,
        }
    )

    assert called["abort"] is False
    assert called["forward"] is False
    assert result["openclaw_pre_delivery_abort"]["attempted"] is False
    assert result["openclaw_pre_delivery_abort"]["reason"] == "platform_act_requires_explicit_authorization"
    assert result["platform_delivery"]["executed"] is False
    assert result["platform_delivery"]["reason"] == "platform_delivery_capability_not_declared"
    assert result["platform_delivery"]["memory_authority"]["can_platform_act"] is False


def test_openclaw_native_event_uses_explicit_delivery_capability_independent_of_platform_name(tmp_path, monkeypatch):
    proxy = _reload_dialog(tmp_path, monkeypatch)
    handler = object.__new__(proxy.DialogEntryHandler)
    forwards = []
    aborts = []

    handler.handle_memory_direct = lambda *_args, **_kwargs: {
        "status": "ok",
        "chain": "F3_zhiyi_direct",
        "answer": "source-backed answer",
        "audit": {"zhiyi_entry": {"requested": True}},
    }
    handler._abort_openclaw_active_run = lambda session_key: aborts.append(session_key) or {
        "attempted": True,
        "ok": True,
        "aborted": True,
        "run_ids": [],
    }

    def fake_forward(message, session_key, idempotency_key=None):
        forwards.append((message, session_key, idempotency_key))
        return {"ok": True, "visible_reply_checked": True, "visible_reply_ok": True}

    handler._forward_to_openclaw = fake_forward
    monkeypatch.setattr(proxy, "maybe_run_zhiyi_live_model_call", lambda _body, _message, result: result)
    monkeypatch.setattr(proxy, "record_zhiyi_usage_log", lambda *_args, **_kwargs: {"write_performed": False})
    monkeypatch.setattr(proxy, "audit_log", lambda *_args, **_kwargs: None)

    def dispatch(platform, event_id):
        return handler.handle_openclaw_native_event(
            {
                "event": {
                    "id": event_id,
                    "message": {
                        "role": "user",
                        "content": [{"type": "text", "text": "/zhiyi continue"}],
                    },
                },
                "session_key": "agent:test:session",
                "platform_delivery": {
                    "enabled": True,
                    "authorized": True,
                    "platform": platform,
                    "delivery_runtime_kind": "ws_rpc_forward",
                    "session_binding": "native_event",
                    "idempotency_key": f"delivery-{event_id}",
                },
            }
        )

    named = dispatch("openclaw", "event-known")
    unknown = dispatch("unlisted_host", "event-unknown")

    assert named["platform_delivery"]["executed"] is True
    assert unknown["platform_delivery"]["executed"] is True
    assert named["platform_delivery"]["delivery_ok"] is True
    assert unknown["platform_delivery"]["delivery_ok"] is True
    assert aborts == ["agent:test:session", "agent:test:session"]
    assert forwards == [
        ("source-backed answer", "agent:test:session", "delivery-event-known"),
        ("source-backed answer", "agent:test:session", "delivery-event-unknown"),
    ]


def test_update_restart_preserves_single_port_topology_from_config():
    update_source = (ROOT / "src" / "update_source.py").read_text(encoding="utf-8")

    assert "def read_service_config()" in update_source
    assert '"front_door_port": 9850' in update_source
    assert '"internal_p3_port": 19300' in update_source
    assert '"internal_p4_port": 19400' in update_source
    assert '"internal_p6_port": 19500' in update_source
    assert '"internal_raw_port": 19510' in update_source
    assert '"internal_dialog_port": 19600' in update_source
    assert '"single_port_runtime.py"' in update_source
    assert '"--preferred-port", str(SERVICE_CONFIG["front_door_port"])' in update_source
    assert '"--host", "127.0.0.1", "--port", str(SERVICE_CONFIG["internal_dialog_port"])' in update_source


def test_update_restart_uses_runtime_python_path(tmp_path, monkeypatch):
    update_source = importlib.import_module("update_source")

    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    fake_python = install_root / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_python.chmod(0o755)
    (runtime / "python_path").write_text(str(fake_python), encoding="utf-8")
    (install_root / "config").mkdir(parents=True)
    (install_root / "config" / "memcore.json").write_text("{}", encoding="utf-8")

    calls = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append({"cmd": cmd, "kwargs": kwargs})

    monkeypatch.setattr(update_source.subprocess, "Popen", FakePopen)

    result = update_source.schedule_restart(str(install_root))
    script_text = Path(result["script"]).read_text(encoding="utf-8")

    assert result["python"] == str(fake_python.resolve())
    assert calls[0]["cmd"][0] == str(fake_python.resolve())
    assert f"PYTHON = {str(fake_python.resolve())!r}" in script_text
    assert '"single_port_runtime.py"' in script_text
    assert '"internal_p3_port": 19300' in script_text
    assert '"internal_p4_port": 19400' in script_text
    assert '"internal_p6_port": 19500' in script_text
    assert '"internal_raw_port": 19510' in script_text
    assert '"internal_dialog_port": 19600' in script_text
    assert '"--port", "9830"' not in script_text
    assert '"--port", "9840"' not in script_text
    assert '"--port", "9860"' not in script_text


def test_hotfix_bundle_import_check_includes_dialog_entry_hard_dependencies():
    checker = (ROOT / "tools" / "hotfix_bundle_import_check.py").read_text(encoding="utf-8")

    assert '"src/dialog_entry_proxy.py"' in checker
    assert '"src/evidence_bound_model.py"' in checker
    assert '"src/memory_authority_policy.py"' in checker
    assert "BASE_IMPORT_CLOSURE_PATHS" in checker
    assert '"src/config_loader.py"' in checker
    assert '"src/dialog_intent_router.py"' in checker
    assert '"src/openclaw_routing_resolver.py"' in checker
    assert '"src/openclaw_ws_rpc_client.py"' in checker
    assert '"src/zhiyi_entry_intent.py"' in checker
    assert "importlib.import_module" in checker
    assert 'default="v2026.6.16"' in checker


def test_update_passive_migration_rewrites_active_feature_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)
    monkeypatch.delenv("MEMCORE_OPENCLAW_CONFIG", raising=False)
    update_source = importlib.import_module("update_source")
    install_root = tmp_path / "memcore"
    flags_path = install_root / "config" / "feature_flags.json"
    flags_path.parent.mkdir(parents=True)
    flags_path.write_text(json.dumps({
        "zhiyi_direct": True,
        "zhiyi_inject": True,
        "openclaw_passive_auto_inject": True,
        "openclaw_rpc": True,
        "passthrough": False,
        "audit_log": False,
        "unrelated_user_flag": "keep",
    }), encoding="utf-8")
    steps = []

    update_source._enforce_passive_delivery_defaults(install_root, steps)

    migrated = json.loads(flags_path.read_text(encoding="utf-8"))
    assert migrated["zhiyi_direct"] is False
    assert migrated["zhiyi_inject"] is False
    assert migrated["openclaw_passive_auto_inject"] is False
    assert migrated["openclaw_rpc"] is False
    assert migrated["passthrough"] is True
    assert migrated["audit_log"] is True
    assert migrated["unrelated_user_flag"] == "keep"
    assert steps[-1]["action"] == "passive_delivery_migration"
    assert set(steps[-1]["feature_flags"]["changed_keys"]) == {
        "zhiyi_direct",
        "zhiyi_inject",
        "openclaw_passive_auto_inject",
        "openclaw_rpc",
        "passthrough",
        "audit_log",
    }


def test_update_passive_migration_rewrites_active_openclaw_plugin_config(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)
    monkeypatch.delenv("MEMCORE_OPENCLAW_CONFIG", raising=False)
    update_source = importlib.import_module("update_source")
    cfg_path = home / ".openclaw" / "openclaw.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({
        "plugins": {
            "entries": {
                "time-library-native": {
                    "enabled": True,
                    "config": {
                        "enabled": True,
                        "enableModelCall": True,
                        "forceZhiyiDirect": True,
                        "passiveAutoInject": True,
                        "endpointUrl": "http://127.0.0.1:9860/entry/openclaw-before-dispatch",
                        "dialogEntryToken": "keep-token",
                    },
                }
            }
        }
    }), encoding="utf-8")
    steps = []

    update_source._enforce_passive_delivery_defaults(tmp_path / "memcore", steps)

    migrated = json.loads(cfg_path.read_text(encoding="utf-8"))
    entry = migrated["plugins"]["entries"]["time-library-native"]
    plugin_cfg = entry["config"]
    assert entry["enabled"] is False
    assert plugin_cfg["enabled"] is False
    assert plugin_cfg["enableModelCall"] is False
    assert plugin_cfg["forceZhiyiDirect"] is False
    assert plugin_cfg["passiveAutoInject"] is False
    assert plugin_cfg["endpointUrl"] == "http://127.0.0.1:9860/entry/openclaw-before-dispatch"
    assert plugin_cfg["dialogEntryToken"] == "keep-token"
    assert list(cfg_path.parent.glob("openclaw.json.time_library-passive-migration.*"))
    assert steps[-1]["openclaw_configs"][0]["changed"] is True
    assert "explicit opt-in must be re-enabled intentionally after update" in steps[-1]["note"]


def test_flat_update_forces_passive_delivery_when_existing_config_is_active(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)
    monkeypatch.delenv("MEMCORE_OPENCLAW_CONFIG", raising=False)
    update_source = importlib.import_module("update_source")

    install_root = tmp_path / "install"
    (install_root / "config").mkdir(parents=True)
    (install_root / "VERSION").write_text("2026.6.16\n", encoding="utf-8")
    (install_root / "config" / "feature_flags.json").write_text(json.dumps({
        "zhiyi_direct": True,
        "zhiyi_inject": True,
        "openclaw_passive_auto_inject": True,
        "openclaw_rpc": True,
        "passthrough": False,
        "audit_log": False,
    }), encoding="utf-8")

    openclaw_cfg = home / ".openclaw" / "openclaw.json"
    openclaw_cfg.parent.mkdir(parents=True)
    openclaw_cfg.write_text(json.dumps({
        "plugins": {
            "entries": {
                "time-library-native": {
                    "enabled": True,
                    "config": {
                        "enabled": True,
                        "enableModelCall": True,
                        "forceZhiyiDirect": True,
                        "passiveAutoInject": True,
                    },
                }
            }
        }
    }), encoding="utf-8")

    package = tmp_path / "time-library-2026.6.20.zip"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("time-library-2026.6.20/VERSION", "2026.6.20\n")
        zf.writestr("time-library-2026.6.20/src/dummy.py", "# update payload\n")
        zf.writestr("time-library-2026.6.20/config/default_feature_flags.json", json.dumps({
            "zhiyi_direct": False,
            "zhiyi_inject": False,
            "openclaw_passive_auto_inject": False,
            "openclaw_rpc": False,
            "passthrough": True,
            "audit_log": True,
        }))

    result = update_source.apply_flat_update(str(install_root), str(package), target_version="2026.6.20")

    assert result["ok"] is True
    assert result["stage"] == "applied"
    flags = json.loads((install_root / "config" / "feature_flags.json").read_text(encoding="utf-8"))
    assert flags["zhiyi_direct"] is False
    assert flags["zhiyi_inject"] is False
    assert flags["openclaw_passive_auto_inject"] is False
    assert flags["openclaw_rpc"] is False
    assert flags["passthrough"] is True
    assert flags["audit_log"] is True

    migrated_openclaw = json.loads(openclaw_cfg.read_text(encoding="utf-8"))
    entry = migrated_openclaw["plugins"]["entries"]["time-library-native"]
    assert entry["enabled"] is False
    assert entry["config"]["enabled"] is False
    assert entry["config"]["enableModelCall"] is False
    assert entry["config"]["forceZhiyiDirect"] is False
    assert entry["config"]["passiveAutoInject"] is False
    migration_steps = [step for step in result["steps"] if step["action"] == "passive_delivery_migration"]
    assert migration_steps
    assert "explicit opt-in must be re-enabled intentionally after update" in migration_steps[0]["note"]


def test_flat_update_then_p3_startup_migrates_legacy_bge_without_touching_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OPENCLAW_CONFIG", raising=False)
    monkeypatch.delenv("MEMCORE_OPENCLAW_CONFIG", raising=False)
    update_source = importlib.import_module("update_source")
    install_root = tmp_path / "install"
    config_dir = install_root / "config"
    config_dir.mkdir(parents=True)
    (install_root / "VERSION").write_text("2026.7.7.2\n", encoding="utf-8")
    (config_dir / "memcore.json").write_bytes((ROOT / "config" / "memcore.json").read_bytes())
    legacy_config = {
        "version": "1.0",
        "recall": {
            "mode": "local_bge_m3",
            "local_bge_m3": {
                "model_name": "BAAI/bge-m3",
                "model_path": str(install_root / "runtime" / "model_cache" / "bge-m3"),
                "embedding_model": "BAAI/bge-m3",
                "embedding_dim": 1024,
                "pooling": "mean_unmasked",
                "table": "experiences_v2",
            },
            "substring": {"table": "experiences"},
        },
    }
    (config_dir / "model_config.json").write_text(json.dumps(legacy_config), encoding="utf-8")
    sentinels = {
        "raw/record.jsonl": b"raw-authority-sentinel\n",
        "zhiyi/case_memory.jsonl": b"zhiyi-sentinel\n",
        "memory/case_memory.json": b'{"memory":"sentinel"}\n',
        "experience_lancedb/experiences_v2.lance/data.bin": b"lancedb-sentinel\x00\x01",
        "runtime/model_cache/bge-m3/config.json": b'{"model":"bge-m3"}\n',
    }
    for relative, content in sentinels.items():
        path = install_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    package = tmp_path / "time-library-2026.7.11.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("time-library-2026.7.11/VERSION", "2026.7.11\n")
        for source in sorted((ROOT / "src").rglob("*.py")):
            relative = source.relative_to(ROOT).as_posix()
            archive.write(source, f"time-library-2026.7.11/{relative}")

    apply_result = update_source.apply_flat_update(
        str(install_root), str(package), target_version="2026.7.11",
    )
    assert apply_result["ok"] is True
    assert apply_result["backup_dir"]
    assert (install_root / "VERSION").read_text(encoding="utf-8").strip() == "2026.7.11"
    for relative, content in sentinels.items():
        assert (install_root / relative).read_bytes() == content

    startup = """
import json, os, sys
root = sys.argv[1]
os.environ['MEMCORE_ROOT'] = root
sys.path.insert(0, root)
from src import p3_recall
class Server:
    def serve_forever(self):
        return None
p3_recall.ThreadingHTTPServer = lambda *args, **kwargs: Server()
p3_recall.vector_runtime_status = lambda load_model=False: {'expected': False, 'ok': True}
p3_recall.get_memories = lambda: []
p3_recall._fts5_build_or_catchup = lambda memories: {'ok': True}
p3_recall.run_server(0)
print(json.dumps(json.load(open(os.path.join(root, 'config', 'model_config.json'), encoding='utf-8'))))
"""
    completed = subprocess.run(
        [sys.executable, "-c", startup, str(install_root)],
        cwd=str(install_root),
        env={**os.environ, "PYTHONPATH": str(install_root)},
        text=True,
        capture_output=True,
        check=True,
    )
    migrated = json.loads(completed.stdout.strip().splitlines()[-1])
    assert migrated["recall"]["mode"] == "substring"
    assert migrated["recall"]["local_vector"]["model_id"] == "ibm-granite/granite-embedding-97m-multilingual-r2"
    assert migrated["recall"]["vector_fallback"]["model_name"] == "BAAI/bge-m3"
    assert list(config_dir.glob("model_config.json.pre-granite-*.bak"))
    for relative, content in sentinels.items():
        assert (install_root / relative).read_bytes() == content
