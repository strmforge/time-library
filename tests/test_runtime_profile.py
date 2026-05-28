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
        "103 /Users/test/.hermes/hermes-agent/venv/bin/python3 /Users/test/.hermes/hermes-agent/venv/bin/hermes chat",
    ])

    openclaw = runtime_profile._processes_containing("openclaw")
    hermes = runtime_profile._processes_containing("hermes")

    assert [item["pid"] for item in openclaw] == [100]
    assert [item["pid"] for item in hermes] == [103]


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
