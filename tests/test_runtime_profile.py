import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_runtime_profile():
    sys.modules.pop("runtime_profile_under_test", None)
    path = ROOT / "tools" / "runtime_profile.py"
    spec = importlib.util.spec_from_file_location("runtime_profile_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_profile_filters_its_own_probe_processes(monkeypatch):
    runtime_profile = _load_runtime_profile()

    monkeypatch.setattr(runtime_profile, "_ps_lines", lambda: [
        "100 /opt/homebrew/opt/node@24/bin/node /opt/homebrew/lib/node_modules/openclaw/dist/index.js gateway --port 18789",
        "101 /bin/zsh -lc curl -sS --max-time 8 http://127.0.0.1:9850/api/v1/runtime/profile/openclaw | python3 -m json.tool",
        "102 /usr/bin/python3 -c import json; print('openclaw hermes')",
        "103 /example/home/.hermes/hermes-agent/venv/bin/python3 /example/home/.hermes/hermes-agent/venv/bin/hermes chat",
        "104 /usr/bin/python3 src/source_system_profile.py --discover claude_desktop",
    ])

    openclaw = runtime_profile._processes_containing("openclaw")
    hermes = runtime_profile._processes_containing("hermes")
    claude = runtime_profile._processes_containing("claude")

    assert [item["pid"] for item in openclaw] == [100]
    assert [item["pid"] for item in hermes] == [103]
    assert [item["pid"] for item in claude] == []


def test_runtime_profile_uses_windows_localappdata_hermes_home(monkeypatch, tmp_path):
    local_app_data = tmp_path / "AppData" / "Local"
    hermes_home = local_app_data / "hermes"
    (hermes_home / "profiles" / "default").mkdir(parents=True)
    (hermes_home / "profiles" / "default" / "config.yaml").write_text("model:\n  default: m2\n", encoding="utf-8")

    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setenv("MEMCORE_PLATFORM", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    runtime_profile = _load_runtime_profile()
    monkeypatch.setattr(runtime_profile, "_ps_lines", lambda: [])
    monkeypatch.setattr(runtime_profile, "probe_hermes_health", lambda: {"reachable": False})

    profile = runtime_profile.build_hermes_profile()

    assert profile["install_root"] == str(hermes_home)
    assert profile["home_resolution"] == "platform_default"
    assert profile["config"]["path"].endswith("profiles/default/config.yaml")
    assert any(item["type"] == "hermes_config" and "profiles" in item["path"] for item in profile["instances"])


def test_runtime_profile_detects_claude_desktop_as_first_class_source(monkeypatch, tmp_path):
    claude_home = tmp_path / "Claude"
    (claude_home / "IndexedDB" / "https_claude.ai_0.indexeddb.leveldb").mkdir(parents=True)
    (claude_home / "IndexedDB" / "https_claude.ai_0.indexeddb.blob").mkdir(parents=True)
    (claude_home / "Local Storage" / "leveldb").mkdir(parents=True)
    (claude_home / "Session Storage").mkdir()
    skill_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    skill_root.mkdir(parents=True)
    (skill_root / "manifest.json").write_text(
        '{"skills":[{"skillId":"time-library","name":"Memcore Cloud Zhiyi","description":"local memory","enabled":true}]}',
        encoding="utf-8",
    )
    (claude_home / "claude_desktop_config.json").write_text(
        '{"mcpServers":{"time-library":{"url":"http://127.0.0.1:9851/mcp","apiKey":"SECRET"}}}',
        encoding="utf-8",
    )
    log_home = tmp_path / "ClaudeLogs"
    log_home.mkdir()

    monkeypatch.setenv("CLAUDE_DESKTOP_HOME", str(claude_home))
    monkeypatch.setenv("CLAUDE_DESKTOP_LOG_HOME", str(log_home))
    runtime_profile = _load_runtime_profile()
    monkeypatch.setattr(runtime_profile, "_ps_lines", lambda: [])

    profile = runtime_profile.build_claude_desktop_profile()
    instance_types = {item["type"] for item in profile["instances"]}

    assert profile["system"] == "claude_desktop"
    assert profile["status"] == "detected"
    assert profile["primary_sync_mode"] == "live_local_user_space_sync"
    assert profile["export_role"] == "cold_start_or_backfill_fallback_only"
    assert profile["config"]["time_library_mcp_detected"] is True
    assert profile["config"]["redacted_mcp_servers"]["time-library"]["apiKey"] == "<redacted>"
    assert profile["consumer_connection"]["skill_detected"] is True
    assert profile["consumer_connection"]["recall_connection_ready"] is True
    assert "claude_desktop_indexeddb_leveldb" in instance_types
    assert "claude_desktop_indexeddb_blob" in instance_types
    assert "claude_desktop_local_storage_leveldb" in instance_types
    assert "claude_desktop_session_storage" in instance_types
    assert "claude_desktop_skills_plugin" in instance_types
    assert profile["read_boundary"]["preferred_raw_source"] == "live_local_sync_manifest_then_authorized_parser"


def test_runtime_profile_uses_windows_localappdata_claude_config_when_no_store_data(monkeypatch, tmp_path):
    appdata = tmp_path / "Roaming"
    localappdata = tmp_path / "Local"
    (appdata / "Claude").mkdir(parents=True)
    local_home = localappdata / "Claude"
    local_home.mkdir(parents=True)
    (local_home / "claude_desktop_config.json").write_text(
        '{"mcpServers":{"time-library":{"command":"python","args":["bridge.py"]}}}',
        encoding="utf-8",
    )

    monkeypatch.delenv("CLAUDE_DESKTOP_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_DESKTOP_LOG_HOME", raising=False)
    monkeypatch.setenv("MEMCORE_PLATFORM", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    runtime_profile = _load_runtime_profile()
    monkeypatch.setattr(runtime_profile, "_ps_lines", lambda: [])

    profile = runtime_profile.build_claude_desktop_profile()

    assert profile["install_root"] == str(local_home)
    assert profile["config"]["time_library_mcp_detected"] is True
    assert profile["consumer_connection"]["recall_connection_ready"] is True


def test_runtime_profile_prefers_windows_store_claude_data(monkeypatch, tmp_path):
    appdata = tmp_path / "Roaming"
    localappdata = tmp_path / "Local"
    light_home = localappdata / "Claude"
    store_home = localappdata / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    light_home.mkdir(parents=True)
    store_home.mkdir(parents=True)
    (light_home / "claude_desktop_config.json").write_text(
        '{"mcpServers":{"time-library":{"command":"python","args":["bridge.py"]}}}',
        encoding="utf-8",
    )
    (store_home / "claude_desktop_config.json").write_text(
        '{"mcpServers":{"time-library":{"command":"python","args":["bridge.py"]}}}',
        encoding="utf-8",
    )
    (store_home / "IndexedDB" / "https_claude.ai_0.indexeddb.leveldb").mkdir(parents=True)
    (store_home / "Local Storage" / "leveldb").mkdir(parents=True)

    monkeypatch.delenv("CLAUDE_DESKTOP_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_DESKTOP_LOG_HOME", raising=False)
    monkeypatch.setenv("MEMCORE_PLATFORM", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    runtime_profile = _load_runtime_profile()
    monkeypatch.setattr(runtime_profile, "_ps_lines", lambda: [])

    profile = runtime_profile.build_claude_desktop_profile()

    assert profile["install_root"] == str(store_home)
    assert profile["read_boundary"]["indexeddb_detected"] is True
