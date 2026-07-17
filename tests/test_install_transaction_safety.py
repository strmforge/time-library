import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _heredoc(installer: str, function_name: str, next_function_name: str) -> str:
    function = installer.split(f"{function_name}() {{", 1)[1].split(
        f"{next_function_name}() {{", 1
    )[0]
    return function.split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]


def test_transaction_snapshot_restores_existing_absent_directory_and_symlink(tmp_path):
    module = _load_tool("install_transaction_snapshot")
    source = tmp_path / "source"
    source.mkdir()
    existing = source / "existing.txt"
    existing.write_text("before", encoding="utf-8")
    directory = source / "directory"
    directory.mkdir()
    (directory / "child.txt").write_text("child-before", encoding="utf-8")
    link = source / "link"
    link.symlink_to("existing.txt")
    absent = source / "absent.txt"
    snapshot = tmp_path / "snapshot"

    module.capture(snapshot, [existing, directory, link, absent])
    existing.write_text("after", encoding="utf-8")
    (directory / "child.txt").write_text("child-after", encoding="utf-8")
    link.unlink()
    link.write_text("not-a-link", encoding="utf-8")
    absent.write_text("created", encoding="utf-8")

    result = module.restore(snapshot)

    assert result["restored_count"] == 4
    assert existing.read_text(encoding="utf-8") == "before"
    assert (directory / "child.txt").read_text(encoding="utf-8") == "child-before"
    assert link.is_symlink() and os.readlink(link) == "existing.txt"
    assert not absent.exists()


def test_runtime_quiescence_rejects_foreign_writer_under_install_root(tmp_path):
    module = _load_tool("install_runtime_quiescence")
    target = tmp_path / "held-open.txt"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import pathlib,sys,time; f=pathlib.Path(sys.argv[1]).open('w'); print('ready',flush=True); time.sleep(30)",
            str(target),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "ready"
        result = module.check([tmp_path])
        assert result["ok"] is False
        assert result["writer_count"] >= 1
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.parametrize("installer_name", ["linux_full_install.sh", "macos_full_install.sh"])
def test_openclaw_migration_removes_only_known_product_paths(installer_name, tmp_path):
    installer = (ROOT / "tools" / installer_name).read_text(encoding="utf-8")
    code = _heredoc(installer, "install_openclaw_plugin", "install_hermes_plugin")
    install_root = tmp_path / "time-library"
    legacy_root = tmp_path / "memcore-cloud"
    plugin_src = install_root / "system/openclaw/plugins/time-library-native"
    custom_same_name = tmp_path / "custom/time-library-native"
    custom_legacy_name = tmp_path / ("custom/" + "memcore-" + "zhiyi-native")
    config = tmp_path / "openclaw.json"
    legacy_id = "memcore-" + "zhiyi-native"
    config.write_text(
        json.dumps(
            {
                "plugins": {
                    "entries": {legacy_id: {"enabled": True}, "time-library-native": {"enabled": True}},
                    "load": {
                        "paths": [
                            str(custom_same_name),
                            str(custom_legacy_name),
                            str(legacy_root / "system/openclaw/plugins" / legacy_id),
                            str(legacy_root / "system/openclaw/plugins/time-library-native"),
                        ]
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-",
            str(config),
            str(plugin_src),
            "",
            "",
            str(install_root),
            str(legacy_root),
        ],
        input=code,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    migrated = json.loads(config.read_text(encoding="utf-8"))
    paths = migrated["plugins"]["load"]["paths"]
    assert paths == [str(custom_same_name), str(custom_legacy_name), str(plugin_src)]
    assert legacy_id not in migrated["plugins"]["entries"]
    assert migrated["plugins"]["entries"]["time-library-native"]["enabled"] is False


@pytest.mark.parametrize("installer_name", ["linux_full_install.sh", "macos_full_install.sh"])
def test_hermes_migration_removes_legacy_provider_and_fails_closed_without_yaml(
    installer_name, tmp_path
):
    yaml = pytest.importorskip("yaml")
    installer = (ROOT / "tools" / installer_name).read_text(encoding="utf-8")
    code = _heredoc(installer, "install_hermes_plugin", "install_codex_skill")
    legacy_id = "memcore_" + "yifan" + "chen"
    home = tmp_path / "hermes"
    home.mkdir()
    config = home / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "memory": {"provider": legacy_id},
                "plugins": {
                    "enabled": [legacy_id, "time_library"],
                    legacy_id: {"provider_url": "legacy"},
                    "time_library": {"provider_url": "current"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-", str(home)],
        input=code,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    migrated = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert migrated["memory"]["provider"] == "time_library"
    assert migrated["plugins"]["enabled"] == ["time_library"]
    assert legacy_id not in migrated["plugins"]

    original = config.read_bytes()
    no_yaml = subprocess.run(
        [sys.executable, "-S", "-", str(home)],
        input=code,
        text=True,
        capture_output=True,
        check=False,
    )
    assert no_yaml.returncode != 0
    assert "PyYAML is required" in no_yaml.stderr
    assert config.read_bytes() == original


@pytest.mark.skipif(sys.platform != "linux", reason="Linux installer rollback behavior")
def test_linux_installer_restores_old_service_and_config_when_quiesced_copy_fails(tmp_path):
    no_start = os.environ.get("TIME_LIBRARY_TEST_NO_START") == "1"
    home = tmp_path / "home"
    legacy = home / ".local/share/memcore-cloud"
    install = home / ".local/share/time-library"
    unit_dir = home / ".config/systemd/user"
    unit_dir.mkdir(parents=True)
    legacy_memory = legacy / "memory"
    legacy_memory.mkdir(parents=True)
    (legacy_memory / "record.jsonl").write_text('{"kept":true}\n', encoding="utf-8")
    (legacy / "VERSION").write_text("2026.7.11\n", encoding="utf-8")
    unit = unit_dir / "time-library-p0-watcher.service"
    unit_text = (
        "[Service]\n"
        f"ExecStart={legacy}/.venv/bin/python {legacy}/src/memcore-cloud.py --watch --source all\n"
    )
    unit.write_text(unit_text, encoding="utf-8")
    openclaw = home / ".openclaw/openclaw.json"
    openclaw.parent.mkdir(parents=True)
    openclaw.write_text('{"plugins":{"sentinel":"before"}}\n', encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    systemctl_log = tmp_path / "systemctl.log"
    systemctl = fake_bin / "systemctl"
    systemctl.write_text(
        """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
unit = os.environ["TEST_UNIT"]
legacy = os.environ["TEST_LEGACY"]
with open(os.environ["SYSTEMCTL_LOG"], "a", encoding="utf-8") as handle:
    handle.write(" ".join(args) + "\\n")
if "status" in args and "show" not in args:
    raise SystemExit(0)
if "show" in args:
    target = args[args.index("show") + 1]
    if "--property=LoadState" in args:
        print("loaded" if target == unit else "not-found")
    elif "--property=ExecStart" in args and target == unit:
        print(f"{{ path={legacy}/.venv/bin/python ; argv[]={legacy}/.venv/bin/python {legacy}/src/memcore-cloud.py --watch --source all ; ignore_errors=no ; }}")
    raise SystemExit(0)
if "is-enabled" in args:
    print("enabled")
    raise SystemExit(0)
if "is-active" in args:
    if "--quiet" not in args:
        print("active")
    raise SystemExit(0)
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    rsync = fake_bin / "rsync"
    rsync.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
    rsync.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "SYSTEMCTL_LOG": str(systemctl_log),
            "TEST_UNIT": unit.name,
            "TEST_LEGACY": str(legacy),
        }
    )

    command = [
            "bash",
            str(ROOT / "tools/linux_full_install.sh"),
            "--skip-openclaw",
            "--skip-hermes",
            "--skip-codex",
            "--skip-claude-desktop",
            "--no-smoke",
        ]
    if no_start:
        command.append("--no-start")
    completed = subprocess.run(
        command,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 42, (
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
    assert not install.exists()
    assert unit.read_text(encoding="utf-8") == unit_text
    assert openclaw.read_text(encoding="utf-8") == '{"plugins":{"sentinel":"before"}}\n'
    assert (legacy_memory / "record.jsonl").read_text(encoding="utf-8") == '{"kept":true}\n'
    calls = systemctl_log.read_text(encoding="utf-8") if systemctl_log.exists() else ""
    if no_start:
        assert f"stop {unit.name}" not in calls
        assert f"start {unit.name}" not in calls
    else:
        assert f"stop {unit.name}" in calls
        assert f"start {unit.name}" in calls


@pytest.mark.skipif(sys.platform != "linux", reason="Linux installer no-start behavior")
def test_linux_installer_no_start_failure_does_not_touch_host_services(tmp_path, monkeypatch):
    monkeypatch.setenv("TIME_LIBRARY_TEST_NO_START", "1")
    test_linux_installer_restores_old_service_and_config_when_quiesced_copy_fails(tmp_path)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS installer rollback behavior")
def test_macos_installer_restores_old_launchagent_and_config_when_quiesced_copy_fails(
    tmp_path,
):
    import plistlib

    home = tmp_path / "home"
    legacy = home / "Library/Application Support/memcore-cloud"
    install = home / "Library/Application Support/time-library"
    launchagent_dir = home / "Library/LaunchAgents"
    launchagent_dir.mkdir(parents=True)
    legacy_memory = legacy / "memory"
    legacy_memory.mkdir(parents=True)
    (legacy_memory / "record.jsonl").write_text('{"kept":true}\n', encoding="utf-8")
    (legacy / "VERSION").write_text("2026.7.11\n", encoding="utf-8")
    label = "com.memcorecloud.p0-watcher"
    plist = launchagent_dir / f"{label}.plist"
    plist_bytes = plistlib.dumps(
        {
            "Label": label,
            "ProgramArguments": [
                str(legacy / ".venv/bin/python"),
                str(legacy / "src/memcore-cloud.py"),
                "--watch",
                "--source",
                "all",
            ],
        }
    )
    plist.write_bytes(plist_bytes)
    openclaw = home / ".openclaw/openclaw.json"
    openclaw.parent.mkdir(parents=True)
    openclaw.write_text('{"plugins":{"sentinel":"before"}}\n', encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    launchctl_log = tmp_path / "launchctl.log"
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        """#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
label = os.environ["TEST_LABEL"]
legacy = os.environ["TEST_LEGACY"]
with open(os.environ["LAUNCHCTL_LOG"], "a", encoding="utf-8") as handle:
    handle.write(" ".join(args) + "\\n")
if args[:2] == ["print", f"gui/{os.getuid()}/{label}"]:
    print(f"program = {legacy}/.venv/bin/python")
    print("arguments = {")
    print(f"    {legacy}/.venv/bin/python")
    print(f"    {legacy}/src/memcore-cloud.py")
    print("    --watch")
    print("    --source")
    print("    all")
    print("}")
    raise SystemExit(0)
if args and args[0] == "print":
    raise SystemExit(1)
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    rsync = fake_bin / "rsync"
    rsync.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
    rsync.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "LAUNCHCTL_LOG": str(launchctl_log),
            "TEST_LABEL": label,
            "TEST_LEGACY": str(legacy),
        }
    )

    completed = subprocess.run(
        [
            "bash",
            str(ROOT / "tools/macos_full_install.sh"),
            "--skip-openclaw",
            "--skip-hermes",
            "--skip-codex",
            "--skip-claude-desktop",
            "--no-smoke",
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 42
    assert not install.exists()
    assert plist.read_bytes() == plist_bytes
    assert openclaw.read_text(encoding="utf-8") == '{"plugins":{"sentinel":"before"}}\n'
    assert (legacy_memory / "record.jsonl").read_text(encoding="utf-8") == '{"kept":true}\n'
    calls = launchctl_log.read_text(encoding="utf-8")
    assert f"bootout gui/{os.getuid()}/{label}" in calls
    assert f"bootstrap gui/{os.getuid()} {plist}" in calls
