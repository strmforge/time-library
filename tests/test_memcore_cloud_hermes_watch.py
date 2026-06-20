import importlib.util
import sys
import queue
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_memcore_cloud():
    path = SRC / "memcore-cloud.py"
    spec = importlib.util.spec_from_file_location("memcore_cloud_p0_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_memcore_cloud_watch_defaults_to_codex_light_source(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.delenv("MEMCORE_WATCHER_SOURCE_DEFAULT", raising=False)
    monkeypatch.setattr(module, "config_get", lambda path, default=None: default)

    assert module.watcher_source_default() == "codex"
    assert module.watcher_resource_profile() == "light"
    assert module.watcher_poll_interval_milliseconds() == 5000


def test_memcore_cloud_watch_source_default_can_be_overridden(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setenv("MEMCORE_WATCHER_SOURCE_DEFAULT", "all")
    monkeypatch.setenv("MEMCORE_WATCHER_RESOURCE_PROFILE", "heavy")
    monkeypatch.setenv("MEMCORE_WATCHER_INTERVAL_MS", "250")
    monkeypatch.setattr(module, "config_get", lambda path, default=None: default)

    assert module.watcher_source_default() == "all"
    assert module.watcher_resource_profile() == "heavy"
    assert module.watcher_poll_interval_milliseconds() == 250


def test_memcore_cloud_watch_supports_hermes_state_db_backfill(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    state_db = tmp_path / "hermes" / "state.db"
    state_db.parent.mkdir(parents=True)
    state_db.write_bytes(b"sqlite fixture")

    monkeypatch.setattr(module, "config_get", lambda path, default=None: default)
    monkeypatch.setattr(module, "hermes_raw_backfill_enabled", lambda: True)
    monkeypatch.setattr(module, "hermes_raw_backfill_limit", lambda: 7)

    hermes_paths = SimpleNamespace(hermes_state_db_path=lambda: state_db)
    monkeypatch.setitem(sys.modules, "hermes_paths", hermes_paths)

    calls = []

    def fake_backfill(*, limit, source_systems):
        calls.append((limit, source_systems))
        return {
            "ok": True,
            "results": [
                {
                    "source_system": "hermes",
                    "changed": 1,
                    "raw_sync": {
                        "status": "hermes_state_db_messages_exported_to_raw",
                        "items_checked": 1,
                    },
                }
            ],
        }

    raw_record_guardian = SimpleNamespace(run_raw_backfill=fake_backfill)
    monkeypatch.setitem(sys.modules, "raw_record_guardian", raw_record_guardian)

    args = SimpleNamespace(source="hermes")

    roots = module._watch_root_candidates(args)
    assert ("hermes", state_db.parent) in roots

    did_work = module._run_hermes_sync_once(args, signature_cache={}, force=True)

    assert did_work is True
    assert calls == [(7, ["hermes"])]


def test_memcore_cloud_watch_skips_hermes_when_state_db_signature_unchanged_without_backfill_recommendation(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    state_db = tmp_path / "hermes" / "state.db"
    state_db.parent.mkdir(parents=True)
    state_db.write_bytes(b"sqlite fixture")

    monkeypatch.setattr(module, "hermes_raw_backfill_enabled", lambda: True)
    hermes_paths = SimpleNamespace(hermes_state_db_path=lambda: state_db)
    monkeypatch.setitem(sys.modules, "hermes_paths", hermes_paths)

    calls = []

    def fake_backfill(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "results": [
                {
                    "source_system": "hermes",
                    "changed": 1,
                    "raw_sync": {"status": "hermes_state_db_messages_exported_to_raw"},
                }
            ],
        }

    recommendation_calls = []

    def fake_recommendation(**kwargs):
        recommendation_calls.append(kwargs)
        return {
            "ok": True,
            "source_system": "hermes",
            "recommended_count": 0,
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }

    raw_record_guardian = SimpleNamespace(
        run_raw_backfill=fake_backfill,
        hermes_backfill_recommendation=fake_recommendation,
    )
    monkeypatch.setitem(sys.modules, "raw_record_guardian", raw_record_guardian)

    args = SimpleNamespace(source="hermes")
    signature_cache = {}

    assert module._run_hermes_sync_once(args, signature_cache=signature_cache, force=False) is True
    assert module._run_hermes_sync_once(
        args,
        signature_cache=signature_cache,
        force=False,
        retry_pending=True,
    ) is False
    assert len(calls) == 1
    assert recommendation_calls == [{"limit": 80}]


def test_memcore_cloud_watch_backfills_hermes_when_signature_unchanged_but_guardian_recommends(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    state_db = tmp_path / "hermes" / "state.db"
    state_db.parent.mkdir(parents=True)
    state_db.write_bytes(b"sqlite fixture")

    monkeypatch.setattr(module, "hermes_raw_backfill_enabled", lambda: True)
    monkeypatch.setattr(module, "hermes_raw_backfill_limit", lambda: 80)
    hermes_paths = SimpleNamespace(hermes_state_db_path=lambda: state_db)
    monkeypatch.setitem(sys.modules, "hermes_paths", hermes_paths)

    calls = []

    def fake_backfill(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "results": [
                {
                    "source_system": "hermes",
                    "changed": 7,
                    "raw_sync": {
                        "status": "hermes_state_db_messages_exported_to_raw",
                        "items_checked": 27,
                    },
                }
            ],
        }

    recommendation_calls = []

    def fake_recommendation(**kwargs):
        recommendation_calls.append(kwargs)
        return {
            "ok": True,
            "source_system": "hermes",
            "recommended_count": 7,
            "session_ids": ["20260525_122249_732cba"],
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }

    raw_record_guardian = SimpleNamespace(
        run_raw_backfill=fake_backfill,
        hermes_backfill_recommendation=fake_recommendation,
    )
    monkeypatch.setitem(sys.modules, "raw_record_guardian", raw_record_guardian)

    args = SimpleNamespace(source="hermes")
    signature_cache = {}

    assert module._run_hermes_sync_once(args, signature_cache=signature_cache, force=False) is True
    assert module._run_hermes_sync_once(
        args,
        signature_cache=signature_cache,
        force=False,
        retry_pending=True,
    ) is True
    assert calls == [
        {"limit": 80, "source_systems": ["hermes"]},
        {"limit": 80, "source_systems": ["hermes"]},
    ]
    assert recommendation_calls == [{"limit": 80}]


def test_memcore_cloud_watch_refreshes_canonical_index_after_source_work(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "_run_openclaw_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_codex_sync_once", lambda *args, **kwargs: True)
    monkeypatch.setattr(module, "_run_claude_code_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_claude_desktop_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_kiro_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_hermes_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "claude_desktop_raw_ingest_interval_seconds", lambda: 60.0)
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: True)
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 13)
    monkeypatch.setattr(module, "canonical_index_interval_seconds", lambda: 30.0)

    refresh_calls = []

    def fake_refresh(**kwargs):
        refresh_calls.append(kwargs)
        return {"ok": True, "index_update": {"records_upserted": 1}}

    monkeypatch.setattr(module, "_refresh_canonical_record_index", fake_refresh)

    state = {"last_canonical_record_index": 9999999999.0}
    did_work = module._run_sync_once(
        SimpleNamespace(source="all"),
        signature_cache={},
        state=state,
        force=False,
    )

    assert did_work is True
    assert refresh_calls == [{"limit": 13, "scan_mode": "fast"}]
    assert state["last_canonical_record_index"] != 9999999999.0


def test_memcore_cloud_watch_skips_canonical_index_when_disabled(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "_run_openclaw_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_codex_sync_once", lambda *args, **kwargs: True)
    monkeypatch.setattr(module, "_run_claude_code_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_claude_desktop_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_kiro_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_hermes_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "claude_desktop_raw_ingest_interval_seconds", lambda: 60.0)
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: False)

    refresh_calls = []
    monkeypatch.setattr(module, "_refresh_canonical_record_index", lambda **kwargs: refresh_calls.append(kwargs))

    did_work = module._run_sync_once(
        SimpleNamespace(source="all"),
        signature_cache={},
        state={},
        force=False,
    )

    assert did_work is True
    assert refresh_calls == []


def test_memcore_cloud_scan_refreshes_canonical_index_only_after_non_dry_run(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "OPENCLAW_ROOT", "/path/that/does/not/exist")
    monkeypatch.setattr(module.os.path, "exists", lambda path: False)
    monkeypatch.setattr(module.os, "listdir", lambda path: [])
    monkeypatch.setattr(module, "_run_hermes_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 17)

    refresh_calls = []

    def fake_refresh(**kwargs):
        refresh_calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(module, "_refresh_canonical_record_index", fake_refresh)

    module.cmd_scan(SimpleNamespace(source="none", dry_run=True))
    module.cmd_scan(SimpleNamespace(source="none", dry_run=False))

    assert refresh_calls == [{"limit": 17, "scan_mode": "fast"}]


def test_memcore_cloud_canonical_refresh_writes_from_full_guardian_records(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: True)
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 19)

    guardian_calls = []

    def fake_guardian(**kwargs):
        guardian_calls.append(kwargs)
        return {
            "ok": True,
            "index_update": {
                "records_upserted": 1,
                "canonical_messages_upserted": 2,
                "canonical_chunks_upserted": 3,
            },
        }

    monkeypatch.setitem(sys.modules, "raw_record_guardian", SimpleNamespace(build_guardian_status=fake_guardian))

    result = module._refresh_canonical_record_index(quiet=True)

    assert result["ok"] is True
    assert guardian_calls == [
        {
            "limit": 19,
            "include_gaps": False,
            "scan_mode": "fast",
            "write_index": True,
            "compact": False,
            "public": True,
        }
    ]


def test_memcore_cloud_event_watch_runs_signature_sync_on_fallback_tick(monkeypatch, tmp_path):
    module = _load_memcore_cloud()

    class FakeQueue:
        def get(self, timeout=None):
            raise queue.Empty

        def get_nowait(self):
            raise queue.Empty

        def put_nowait(self, item):
            pass

    class FakeObserver:
        def __init__(self):
            self.started = False

        def schedule(self, handler, root, recursive=True):
            assert recursive is True

        def start(self):
            self.started = True

        def stop(self):
            pass

        def join(self):
            pass

    class FakeHandler:
        pass

    roots = [("codex", tmp_path)]
    monkeypatch.setattr(module, "_watch_root_candidates", lambda args: roots)
    monkeypatch.setattr(module.queue, "Queue", lambda: FakeQueue())
    monkeypatch.setattr(module, "watcher_poll_interval_seconds", lambda: 0.01)
    monkeypatch.setattr(module, "watcher_poll_interval_milliseconds", lambda: 10)

    calls = []

    def fake_run_sync_once(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) >= 2:
            raise KeyboardInterrupt
        return False

    monkeypatch.setattr(module, "_run_sync_once", fake_run_sync_once)
    monkeypatch.setitem(
        sys.modules,
        "watchdog.events",
        SimpleNamespace(FileSystemEventHandler=FakeHandler),
    )
    monkeypatch.setitem(
        sys.modules,
        "watchdog.observers",
        SimpleNamespace(Observer=FakeObserver),
    )

    try:
        module.watch_file_events(SimpleNamespace(source="all"))
    except KeyboardInterrupt:
        pass

    assert len(calls) == 2
    assert calls[0]["retry_pending"] is True
    assert calls[1]["force"] is False
    assert calls[1]["retry_pending"] is False
