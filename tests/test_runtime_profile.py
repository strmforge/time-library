import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_runtime_profile():
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
