import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_status():
    sys.modules.pop("continuous_sync_status", None)
    return importlib.import_module("continuous_sync_status")


def test_continuous_sync_status_says_watcher_is_not_install_scan_only(monkeypatch):
    status_module = _load_status()
    monkeypatch.setenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED", "1")
    monkeypatch.delenv("MEMCORE_WATCHER_INTERVAL_MS", raising=False)
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_MS", raising=False)
    monkeypatch.setattr(status_module, "config_get", lambda path, default=None: default)
    def fake_connector_status(name):
        if name == "claude_desktop_connector":
            return {
                "ok": True,
                "reachable": True,
                "raw_body_readiness": "partial_fragments_only",
                "current_window_memory_registerable": False,
                "local_storage": {
                    "assistant_reply_persistence": "unverified",
                },
            }
        return {
            "ok": True,
            "reachable": name == "kiro_local_connector",
            "collector_status": "continuous_incremental_json_snapshot" if name == "kiro_local_connector" else "continuous_incremental",
        }

    monkeypatch.setattr(status_module, "_safe_connector_status", fake_connector_status)
    monkeypatch.setattr(
        status_module,
        "file_event_backend_status",
        lambda: {"available": True, "backend": "watchdog.observers.inotify"},
    )

    result = status_module.build_continuous_sync_status(watcher_active=True, include_generic=False)

    assert result["contract"] == "continuous_local_chat_sync.v1"
    assert result["tiandao_contract"] == "tiandao_continuous_local_sync.v1"
    assert result["tiandao_sync_contract"]["contract"] == "tiandao_continuous_local_sync.v1"
    assert result["tiandao_sync_contract"]["install_scan_only"] is False
    assert result["read_only"] is True
    assert result["watcher"]["active"] is True
    assert result["watcher"]["required_for_local_capture"] is True
    assert result["watcher"]["mode"] == "file_event_or_low_latency_loop"
    assert result["watcher"]["event_driven_available"] is True
    assert result["watcher"]["event_driven_active"] is True
    assert result["watcher"]["event_backend"] == "watchdog.observers.inotify"
    assert result["watcher"]["base_poll_interval_milliseconds"] == 5000
    assert result["watcher"]["base_poll_interval_seconds"] == 5.0
    assert result["watcher"]["fallback_poll_interval_milliseconds"] == 5000
    assert result["watcher"]["target_latency_milliseconds"] == 5000
    assert result["watcher"]["resource_profile"] == "light"
    assert result["watcher"]["source_default"] == "codex"
    assert result["watcher"]["install_scan_only"] is False
    sources = {item["source_system"]: item for item in result["sources"]}
    assert sources["openclaw"]["continuous"] is True
    assert sources["codex"]["continuous"] is True
    assert sources["codex"]["declared_continuous"] is True
    assert sources["codex"]["sync_health"] == "ok"
    assert sources["codex"]["capture_independent_of_mcp"] is True
    assert sources["codex"]["consumer_connection_required"] is False
    assert sources["claude_code_cli"]["continuous"] is True
    assert sources["claude_code_cli"]["declared_continuous"] is True
    assert sources["claude_code_cli"]["capture_independent_of_mcp"] is True
    assert sources["claude_code_cli"]["consumer_connection_required"] is False
    assert sources["kiro"]["continuous"] is True
    assert sources["hermes"]["continuous"] is True
    assert sources["hermes"]["native_artifact_format"] == "hermes_state_db_messages_jsonl"
    assert sources["hermes"]["status_detail"]["source_storage"] == "sqlite_state_db"
    assert sources["hermes"]["status_detail"]["writes_platform_config"] is False
    assert sources["claude_desktop"]["continuous"] is True
    assert sources["claude_desktop"]["status_detail"]["raw_body_readiness"] == "partial_fragments_only"
    assert sources["claude_desktop"]["status_detail"]["assistant_reply_persistence"] == "unverified"
    assert sources["claude_desktop"]["status_detail"]["current_window_memory_registerable"] is False
    assert sources["openclaw"]["poll_interval_milliseconds"] == 5000
    assert sources["codex"]["poll_interval_milliseconds"] == 5000
    assert sources["claude_code_cli"]["poll_interval_milliseconds"] == 5000
    assert sources["kiro"]["poll_interval_milliseconds"] == 5000
    assert sources["claude_desktop"]["poll_interval_milliseconds"] == 5000
    assert sources["hermes"]["poll_interval_milliseconds"] == 5000
    assert sources["openclaw"]["poll_interval_seconds"] == 5.0
    assert all(item["event_driven_available"] for item in sources.values())
    assert all(item["event_driven_active"] for item in sources.values())
    assert all(item["fallback_poll_interval_milliseconds"] == 5000 for item in sources.values())
    assert not any(item["near_real_time"] for item in sources.values())
    assert not any(item["millisecond_level"] for item in sources.values())
    assert result["summary"]["universal_seconds_level_sync"] is False
    assert result["summary"]["core_millisecond_level_sync"] is False
    assert result["summary"]["local_capture_ok"] is True
    assert result["summary"]["millisecond_level_source_count"] == 0
    assert result["summary"]["resource_profile"] == "light"
    assert result["summary"]["source_default"] == "codex"
    assert result["summary"]["low_resource_default"] is True
    assert result["collector_pending"] == []


def test_continuous_sync_status_marks_codex_lag_when_raw_archive_is_behind(monkeypatch):
    status_module = _load_status()
    monkeypatch.setattr(status_module, "config_get", lambda path, default=None: default)
    monkeypatch.setattr(
        status_module,
        "file_event_backend_status",
        lambda: {"available": True, "backend": "watchdog.observers.winapi"},
    )

    def fake_connector_status(name):
        if name == "codex_local_connector":
            return {
                "ok": True,
                "reachable": True,
                "collector_status": "continuous_incremental",
                "raw_sync": {
                    "status": "raw_lagging_sla_breach",
                    "missing_or_stale_count": 1,
                    "independent_of_mcp": True,
                },
            }
        return {"ok": True, "collector_status": "continuous_incremental"}

    monkeypatch.setattr(status_module, "_safe_connector_status", fake_connector_status)

    result = status_module.build_continuous_sync_status(watcher_active=True, include_generic=False)
    codex = next(item for item in result["sources"] if item["source_system"] == "codex")

    assert codex["declared_continuous"] is True
    assert codex["sync_health"] == "raw_lagging"
    assert codex["raw_sync"]["missing_or_stale_count"] == 1
    assert result["summary"]["raw_lagging_source_count"] == 1
    assert result["summary"]["local_capture_ok"] is False


def test_continuous_sync_status_treats_codex_catching_up_as_not_failed(monkeypatch):
    status_module = _load_status()
    monkeypatch.setattr(status_module, "config_get", lambda path, default=None: default)
    monkeypatch.setattr(
        status_module,
        "file_event_backend_status",
        lambda: {"available": True, "backend": "watchdog.observers.fsevents"},
    )

    def fake_connector_status(name):
        if name == "codex_local_connector":
            return {
                "ok": True,
                "reachable": True,
                "collector_status": "continuous_incremental",
                "raw_sync": {
                    "status": "raw_catching_up",
                    "missing_or_stale_count": 1,
                    "raw_archive_max_lag_milliseconds": 39,
                    "raw_lag_sla_milliseconds": 1000,
                    "independent_of_mcp": True,
                },
            }
        return {"ok": True, "collector_status": "continuous_incremental"}

    monkeypatch.setattr(status_module, "_safe_connector_status", fake_connector_status)

    result = status_module.build_continuous_sync_status(watcher_active=True, include_generic=False)
    codex = next(item for item in result["sources"] if item["source_system"] == "codex")

    assert codex["sync_health"] == "raw_catching_up"
    assert result["summary"]["raw_lagging_source_count"] == 0
    assert result["summary"]["local_capture_ok"] is True


def test_continuous_sync_status_does_not_claim_active_when_watcher_is_dead(monkeypatch):
    status_module = _load_status()
    monkeypatch.setattr(status_module, "config_get", lambda path, default=None: default)
    monkeypatch.setattr(status_module, "_safe_connector_status", lambda name: {
        "ok": True,
        "reachable": True,
        "collector_status": "continuous_incremental",
    })
    monkeypatch.setattr(
        status_module,
        "file_event_backend_status",
        lambda: {"available": True, "backend": "watchdog.observers.winapi"},
    )

    result = status_module.build_continuous_sync_status(watcher_active=False, include_generic=False)
    codex = next(item for item in result["sources"] if item["source_system"] == "codex")

    assert codex["declared_continuous"] is True
    assert codex["continuous"] is False
    assert codex["sync_health"] == "watcher_inactive"
    assert result["summary"]["watcher_inactive_source_count"] >= 1
    assert result["summary"]["local_capture_ok"] is False


def test_continuous_sync_status_defaults_claude_to_continuous_local_capture(monkeypatch):
    status_module = _load_status()
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED", raising=False)
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_MS", raising=False)
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr(status_module, "config_get", lambda path, default=None: default)
    monkeypatch.setattr(status_module, "_safe_connector_status", lambda name: {
        "ok": True,
        "reachable": True,
        "raw_body_readiness": "complete_conversation_verified" if name == "claude_desktop_connector" else "",
        "current_window_memory_registerable": name == "claude_desktop_connector",
        "local_storage": {
            "assistant_reply_persistence": "verified",
        } if name == "claude_desktop_connector" else {},
    })
    monkeypatch.setattr(
        status_module,
        "file_event_backend_status",
        lambda: {"available": False, "backend": "unavailable", "error": "ModuleNotFoundError"},
    )

    result = status_module.build_continuous_sync_status(include_generic=False)
    claude = next(item for item in result["sources"] if item["source_system"] == "claude_desktop")

    assert claude["collector_status"] == "periodic_authorized_raw_ingest"
    assert claude["enabled_in_p0_watcher"] is True
    assert claude["continuous"] is True
    assert claude["poll_interval_milliseconds"] == 5000
    assert claude["event_driven_available"] is False
    assert claude["event_driven_active"] is None
    assert claude["fallback_poll_interval_milliseconds"] == 5000
    assert claude["target_latency_milliseconds"] == 5000
    assert claude["millisecond_level"] is False
    assert claude["status_detail"]["raw_ingest_enabled"] is True
    assert claude["status_detail"]["writes_platform_config"] is False
    assert claude["status_detail"]["raw_body_readiness"] == "complete_conversation_verified"
    assert claude["status_detail"]["assistant_reply_persistence"] == "verified"
    assert claude["status_detail"]["current_window_memory_registerable"] is True


def test_continuous_sync_status_ignores_legacy_config_seconds_for_claude_interval(monkeypatch):
    status_module = _load_status()
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_MS", raising=False)
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr(
        status_module,
        "config_get",
        lambda path, default=None: 30 if path == "integrations.claude_desktop.raw_ingest.interval_seconds" else default,
    )
    monkeypatch.setattr(status_module, "_safe_connector_status", lambda name: {"ok": True, "collector_status": "continuous_incremental"})
    monkeypatch.setattr(
        status_module,
        "file_event_backend_status",
        lambda: {"available": False, "backend": "unavailable", "error": "ModuleNotFoundError"},
    )

    result = status_module.build_continuous_sync_status(watcher_active=True, include_generic=False)
    claude = next(item for item in result["sources"] if item["source_system"] == "claude_desktop")

    assert claude["poll_interval_milliseconds"] == 5000
    assert claude["poll_interval_seconds"] == 5.0
    assert claude["millisecond_level"] is False
    assert result["summary"]["core_millisecond_level_sync"] is False


def test_continuous_sync_status_marks_claude_disabled_when_explicitly_disabled(monkeypatch):
    status_module = _load_status()
    monkeypatch.setenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED", "0")
    monkeypatch.setattr(status_module, "config_get", lambda path, default=None: default)
    monkeypatch.setattr(
        status_module,
        "file_event_backend_status",
        lambda: {"available": True, "backend": "watchdog.observers.fsevents"},
    )

    result = status_module.build_continuous_sync_status(include_generic=False)
    claude = next(item for item in result["sources"] if item["source_system"] == "claude_desktop")

    assert claude["collector_status"] == "disabled"
    assert claude["enabled_in_p0_watcher"] is False
    assert claude["continuous"] is False
    assert claude["event_driven_active"] is False
    assert claude["poll_interval_milliseconds"] == 5000


def test_continuous_sync_status_reports_event_backend_unavailable(monkeypatch):
    status_module = _load_status()
    monkeypatch.setattr(status_module, "config_get", lambda path, default=None: default)
    monkeypatch.setattr(status_module, "_safe_connector_status", lambda name: {"ok": True, "collector_status": "continuous_incremental"})
    monkeypatch.setattr(
        status_module,
        "file_event_backend_status",
        lambda: {"available": False, "backend": "unavailable", "error": "ModuleNotFoundError"},
    )

    result = status_module.build_continuous_sync_status(watcher_active=True, include_generic=False)
    sources = {item["source_system"]: item for item in result["sources"]}

    assert result["watcher"]["event_driven_available"] is False
    assert result["watcher"]["event_driven_active"] is False
    assert result["watcher"]["event_backend"] == "unavailable"
    assert result["watcher"]["fallback_poll_interval_milliseconds"] == 5000
    assert sources["codex"]["event_driven_available"] is False
    assert sources["codex"]["event_driven_active"] is False
    assert sources["codex"]["continuous"] is True
    assert sources["codex"]["near_real_time"] is False
    assert sources["codex"]["millisecond_level"] is False
    assert sources["codex"]["sync_health"] == "ok"
    assert sources["codex"]["fallback_poll_interval_milliseconds"] == 5000
    assert sources["claude_code_cli"]["event_driven_available"] is False
    assert sources["claude_code_cli"]["event_driven_active"] is False
    assert sources["claude_code_cli"]["continuous"] is True
    assert sources["claude_code_cli"]["near_real_time"] is False
    assert sources["claude_code_cli"]["millisecond_level"] is False
    assert sources["claude_code_cli"]["sync_health"] == "ok"
    assert sources["claude_code_cli"]["fallback_poll_interval_milliseconds"] == 5000
    assert result["summary"]["core_millisecond_level_sync"] is False
    assert result["summary"]["continuous_source_count"] == 6
    assert result["summary"]["millisecond_level_source_count"] == 0
    assert result["summary"]["watcher_inactive_source_count"] == 0


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
        "poll_interval_milliseconds": 250,
    }))
    monkeypatch.setitem(sys.modules, "claude_code_local_connector", SimpleNamespace(
        status=lambda: {
            "ok": True,
            "source_system": "claude_code_cli",
            "collector_status": "continuous_incremental",
            "reachable": True,
            "raw_sync": {"status": "raw_current"},
        },
        scan_sessions=lambda dry_run=True, limit=20, public=True: {
            "ok": True,
            "source_system": "claude_code_cli",
            "dry_run": dry_run,
            "items": [],
        },
    ))
    monkeypatch.setitem(sys.modules, "claude_desktop_connector", SimpleNamespace(
        status=lambda: {
            "ok": True,
            "source_system": "claude_desktop",
            "reachable": True,
            "raw_body_readiness": "partial_fragments_only",
            "current_window_memory_registerable": False,
            "local_storage": {
                "assistant_reply_persistence": "unverified",
            },
        },
        conversation_body_probe=lambda: {
            "ok": True,
            "source_system": "claude_desktop",
            "raw_body_readiness": "partial_fragments_only",
            "complete_conversation_candidate_count": 0,
            "user_only_candidate_count": 1,
            "assistant_reply_persistence": "unverified",
            "message_text_returned": False,
            "raw_excerpt_returned": False,
        },
    ))

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
    assert sent[-1][1]["poll_interval_milliseconds"] == 250

    dummy.path = "/api/v1/source-systems/claude_desktop/conversation-body-probe"
    p6.Handler.do_GET_api_v1(dummy, "/api/v1/source-systems/claude_desktop/conversation-body-probe")
    assert sent[-1][0] == 200
    assert sent[-1][1]["source_system"] == "claude_desktop"
    assert sent[-1][1]["raw_body_readiness"] == "partial_fragments_only"
    assert sent[-1][1]["message_text_returned"] is False

    dummy.path = "/api/v1/source-systems/claude_code_cli/status"
    p6.Handler.do_GET_api_v1(dummy, "/api/v1/source-systems/claude_code_cli/status")
    assert sent[-1][0] == 200
    assert sent[-1][1]["source_system"] == "claude_code_cli"
