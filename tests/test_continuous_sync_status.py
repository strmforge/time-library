import importlib
import sys
from types import SimpleNamespace


def _load_status():
    sys.modules.pop("continuous_sync_status", None)
    return importlib.import_module("continuous_sync_status")


def test_continuous_sync_status_says_watcher_is_not_install_scan_only(monkeypatch):
    status_module = _load_status()
    monkeypatch.setenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED", "1")
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr(status_module, "config_get", lambda path, default=None: default)
    monkeypatch.setattr(status_module, "_safe_connector_status", lambda name: {
        "ok": True,
        "reachable": name == "kiro_local_connector",
        "collector_status": "continuous_incremental_json_snapshot" if name == "kiro_local_connector" else "continuous_incremental",
    })

    result = status_module.build_continuous_sync_status(watcher_active=True, include_generic=False)

    assert result["contract"] == "continuous_local_chat_sync.v1"
    assert result["read_only"] is True
    assert result["watcher"]["active"] is True
    assert result["watcher"]["mode"] == "continuous_loop"
    assert result["watcher"]["base_poll_interval_seconds"] == 5
    assert result["watcher"]["install_scan_only"] is False
    sources = {item["source_system"]: item for item in result["sources"]}
    assert sources["openclaw"]["continuous"] is True
    assert sources["codex"]["continuous"] is True
    assert sources["kiro"]["continuous"] is True
    assert sources["claude_desktop"]["continuous"] is True
    assert sources["openclaw"]["poll_interval_seconds"] == 5
    assert sources["codex"]["poll_interval_seconds"] == 5
    assert sources["kiro"]["poll_interval_seconds"] == 5
    assert sources["claude_desktop"]["poll_interval_seconds"] == 5
    assert all(item["near_real_time"] for item in sources.values())
    assert result["summary"]["universal_seconds_level_sync"] is False
    assert result["collector_pending"] == []


def test_continuous_sync_status_defaults_claude_to_continuous_local_capture(monkeypatch):
    status_module = _load_status()
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED", raising=False)
    monkeypatch.setattr(status_module, "config_get", lambda path, default=None: default)

    result = status_module.build_continuous_sync_status(include_generic=False)
    claude = next(item for item in result["sources"] if item["source_system"] == "claude_desktop")

    assert claude["collector_status"] == "periodic_authorized_raw_ingest"
    assert claude["enabled_in_p0_watcher"] is True
    assert claude["continuous"] is True
    assert claude["poll_interval_seconds"] == 5
    assert claude["status_detail"]["raw_ingest_enabled"] is True
    assert claude["status_detail"]["writes_platform_config"] is False


def test_continuous_sync_status_marks_claude_disabled_when_explicitly_disabled(monkeypatch):
    status_module = _load_status()
    monkeypatch.setenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED", "0")
    monkeypatch.setattr(status_module, "config_get", lambda path, default=None: default)

    result = status_module.build_continuous_sync_status(include_generic=False)
    claude = next(item for item in result["sources"] if item["source_system"] == "claude_desktop")

    assert claude["collector_status"] == "disabled"
    assert claude["enabled_in_p0_watcher"] is False
    assert claude["continuous"] is False
    assert claude["poll_interval_seconds"] == 5


def test_p6_continuous_sync_and_kiro_status_apis_are_visible(tmp_path, monkeypatch):
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(root / "config" / "memcore.json"))
    for name in ["config_loader", "src.config_loader", "p6_console", "src.p6_console"]:
        sys.modules.pop(name, None)
    p6 = importlib.import_module("p6_console")
    monkeypatch.setattr(p6, "get_watcher_status", lambda: True)
    monkeypatch.setitem(sys.modules, "kiro_local_connector", SimpleNamespace(status=lambda: {
        "ok": True,
        "source_system": "kiro",
        "collector_status": "continuous_incremental_json_snapshot",
        "poll_interval_seconds": 5,
    }))

    sent = []

    class Dummy:
        path = "/api/v1/source-systems/continuous-sync/status"

        def send_json(self, data, code=200):
            sent.append((code, data))

    p6.Handler.do_GET_api_v1(Dummy(), "/api/v1/source-systems/continuous-sync/status")
    assert sent[-1][0] == 200
    assert sent[-1][1]["watcher"]["install_scan_only"] is False

    dummy = Dummy()
    dummy.path = "/api/v1/source-systems/kiro/status"
    p6.Handler.do_GET_api_v1(dummy, "/api/v1/source-systems/kiro/status")
    assert sent[-1][1]["source_system"] == "kiro"
    assert sent[-1][1]["poll_interval_seconds"] == 5
