import importlib
import json
import sys
import threading
import types
import urllib.error
import urllib.request
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
    assert proxy._is_loopback_client(("192.168.50.10", 12345)) is False

    headers = types.SimpleNamespace(get=lambda name, default="": "")
    assert proxy._management_request_allowed(("127.0.0.1", 12345), headers) is True
    assert proxy._management_request_allowed(("192.168.50.10", 12345), headers) is False
    assert proxy._entry_request_allowed("/entry/openclaw-before-dispatch", ("127.0.0.1", 12345), headers) is True
    assert proxy._entry_request_allowed("/entry/openclaw-before-dispatch", ("192.168.50.10", 12345), headers) is False

    monkeypatch.setenv("MEMCORE_DIALOG_ENTRY_TOKEN", "lan-secret")
    bearer_headers = types.SimpleNamespace(
        get=lambda name, default="": "Bearer lan-secret" if name == "Authorization" else default
    )
    assert proxy._entry_request_allowed(
        "/entry/openclaw-before-dispatch",
        ("192.168.50.10", 12345),
        bearer_headers,
    ) is True
    assert proxy._entry_request_allowed("/flags", ("192.168.50.10", 12345), bearer_headers) is False


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
        headers({"Origin": "http://127.0.0.1:9860", "Host": "192.168.50.10:9860"}),
    ) is False
    assert proxy._management_request_allowed(
        ("127.0.0.1", 12345),
        headers({"Origin": "http://evil.example", "Host": "127.0.0.1:9860"}),
    ) is False

    monkeypatch.setenv("MEMCORE_DIALOG_ENTRY_TOKEN", "lan-secret")
    assert proxy._entry_request_allowed(
        "/entry/openclaw-before-dispatch",
        ("192.168.50.10", 12345),
        headers({
            "Authorization": "Bearer lan-secret",
            "Origin": "http://192.168.50.20:18789",
            "Host": "192.168.50.10:9860",
        }),
    ) is True
    assert proxy._entry_request_allowed(
        "/entry/openclaw-before-dispatch",
        ("192.168.50.10", 12345),
        headers({
            "Authorization": "Bearer lan-secret",
            "Origin": "http://evil.example",
            "Host": "192.168.50.10:9860",
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
        ("192.168.50.10", 12345),
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
            "Host": "192.168.50.10:9850",
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
        ("192.168.50.10", 12345),
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
    assert contract["auto_connect_requires_user_or_installer_approval"] is True
    assert contract["platform_config_write_requires_authorized_apply"] is True
    assert contract["chat_body_parser_requires_verified_collector"] is True
    assert contract["chat_body_parser_requires_separate_authorization"] is True


def test_dialog_entry_lan_install_path_is_explicit_and_tokened():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    guardian = (ROOT / "tools" / "windows_guardian.ps1").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    plugin = (ROOT / "system" / "openclaw" / "plugins" / "memcore-zhiyi-native" / "index.js").read_text(encoding="utf-8")

    for text in (windows, guardian, linux, mac):
        assert "MEMCORE_DIALOG_ENTRY_TOKEN" in text
        assert "--host" in text
        assert "dialog_entry_host" in text
        assert "dialog_entry_token" in text

    assert "[string]$DialogEntryHost = \"127.0.0.1\"" in windows
    assert "[string]$DialogEntryToken = \"\"" in windows
    assert "Ensure-DialogEntryToken" in windows
    assert "New-DialogEntryTokenValue" in windows
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


def test_update_restart_preserves_dialog_entry_host_from_config():
    update_source = (ROOT / "src" / "update_source.py").read_text(encoding="utf-8")

    assert "def read_dialog_entry_host()" in update_source
    assert "dialog_entry_host" in update_source
    assert '"--host", DIALOG_ENTRY_HOST, "--port", "9860"' in update_source
