import importlib
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_p6_status():
    sys.modules.pop("p6_console_status", None)
    return importlib.import_module("p6_console_status")


def _load_memcore_cloud():
    path = SRC / "memcore-cloud.py"
    spec = importlib.util.spec_from_file_location("memcore_cloud_pid_hygiene_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_macos_watcher_status_prefers_launchd_over_stale_pid_file(tmp_path, monkeypatch):
    p6 = _load_p6_status()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "p0-watcher.pid").write_text("65374\n", encoding="ascii")
    p6.MEMCORE_ROOT = str(tmp_path)
    monkeypatch.setattr(p6.sys, "platform", "darwin")
    monkeypatch.setattr(p6, "get_service_manager", lambda: SimpleNamespace(is_active=lambda name: False))

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["launchctl", "list"]:
            return SimpleNamespace(
                returncode=0,
                stdout='\n'.join(
                    [
                        '{',
                        '  "StandardOutPath" = "<home>/Library/Logs/memcore-cloud/p0-watcher.out.log";',
                        '  "StandardErrorPath" = "<home>/Library/Logs/memcore-cloud/p0-watcher.err.log";',
                        '  "PID" = 9853;',
                        '};',
                    ]
                ),
                stderr="",
            )
        if cmd[:3] == ["ps", "-p", "9853"]:
            return SimpleNamespace(returncode=0, stdout="/venv/bin/python /app/src/memcore-cloud.py --watch\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(p6.subprocess, "run", fake_run)

    status = p6.get_watcher_status_detail()

    assert status["active"] is True
    assert status["method"] == "macos_launchd"
    assert status["pid"] == "9853"
    assert status["stdout_path"].endswith("/Library/Logs/memcore-cloud/p0-watcher.out.log")


def test_macos_watcher_status_reports_stale_pid_as_inactive(tmp_path, monkeypatch):
    p6 = _load_p6_status()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / "p0-watcher.pid").write_text("65374\n", encoding="ascii")
    p6.MEMCORE_ROOT = str(tmp_path)
    monkeypatch.setattr(p6.sys, "platform", "darwin")
    monkeypatch.setattr(p6, "get_service_manager", lambda: SimpleNamespace(is_active=lambda name: False))

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["launchctl", "list"]:
            return SimpleNamespace(returncode=113, stdout="", stderr="not found")
        if cmd[:2] == ["ps", "axo"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(p6.subprocess, "run", fake_run)

    status = p6.get_watcher_status_detail()

    assert status["active"] is False
    assert status["method"] == "macos_launchd"
    assert status["pid"] == "65374"
    assert "ignored stale runtime/p0-watcher.pid" in status["detail"]


def test_watcher_pid_file_write_and_owner_cleanup(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    pid_path = tmp_path / "runtime" / "p0-watcher.pid"
    monkeypatch.setenv("MEMCORE_P0_WATCHER_PID_PATH", str(pid_path))

    module._write_watcher_pid_file()

    assert pid_path.read_text(encoding="ascii") == f"{os.getpid()}\n"

    module._clear_watcher_pid_file()

    assert not pid_path.exists()


def test_watcher_pid_cleanup_does_not_remove_another_process_pid(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    pid_path = tmp_path / "runtime" / "p0-watcher.pid"
    pid_path.parent.mkdir()
    pid_path.write_text("999999\n", encoding="ascii")
    monkeypatch.setenv("MEMCORE_P0_WATCHER_PID_PATH", str(pid_path))

    module._clear_watcher_pid_file()

    assert pid_path.read_text(encoding="ascii") == "999999\n"
