import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "install_config_merge_under_test",
        ROOT / "tools" / "install_config_merge.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_state_migrate_module():
    spec = importlib.util.spec_from_file_location(
        "install_state_migrate_under_test",
        ROOT / "tools" / "install_state_migrate.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_config_merge_preserves_user_state_and_copies_missing_defaults(tmp_path):
    module = _load_module()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "model_config.json").write_text('{"provider":"package"}\n', encoding="utf-8")
    (source / "default_model_config.json").write_text('{"provider":"default"}\n', encoding="utf-8")
    (source / "intent_router_rules.json").write_text('{"version":"new"}\n', encoding="utf-8")
    (target / "model_config.json").write_text('{"provider":"user"}\n', encoding="utf-8")
    (target / "intent_router_rules.json").write_text('{"version":"old"}\n', encoding="utf-8")
    (target / "window_binding_registry.json").write_text('{"bindings":{"kept":{}}}\n', encoding="utf-8")

    result = module.merge_config(source, target)

    assert json.loads((target / "model_config.json").read_text(encoding="utf-8")) == {"provider": "user"}
    assert json.loads((target / "window_binding_registry.json").read_text(encoding="utf-8")) == {
        "bindings": {"kept": {}}
    }
    assert json.loads((target / "default_model_config.json").read_text(encoding="utf-8")) == {
        "provider": "default"
    }
    assert json.loads((target / "intent_router_rules.json").read_text(encoding="utf-8")) == {
        "version": "new"
    }
    assert result == {
        "copied": ["default_model_config.json"],
        "preserved_existing": ["model_config.json"],
        "updated": ["intent_router_rules.json"],
    }


def test_all_installers_preserve_config_and_full_runtime_families():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    for installer in (mac, linux):
        assert "--exclude 'config/'" in installer
        assert installer.count("--exclude '.playwright-cli/'") >= 2
        assert installer.count("--exclude '.codex_nas_pending/'") >= 2
        assert ".codex_nas_pending" in installer.split("copy_runtime_data()", 1)[1].split("backup_program_files()", 1)[0]
        assert 'rm -rf -- "${INSTALL_ROOT}/.playwright-cli"' in installer
        assert "merge_packaged_config" in installer
        assert '"${SOURCE_ROOT}/tools/install_config_merge.py"' in installer
        assert '"${SOURCE_ROOT}/tools/install_state_migrate.py"' in installer
        assert "migrate_legacy_state_paths" in installer
        assert '"$migrated_legacy" == "0"' in installer
        for name in ("raw", "data", "state", "input", "update_staging", "update_history.jsonl"):
            assert name in installer

    assert '"config", "logs", "runtime"' in windows
    assert windows.count('".playwright-cli"') >= 3
    assert windows.count('".codex_nas_pending"') >= 3
    assert 'Remove-Tree -Path (Join-Path $InstallRoot ".playwright-cli")' in windows
    windows_backup = windows.split("function Backup-InstallFilesBestEffort", 1)[1].split(
        "function Stop-Port", 1
    )[0]
    for path in ("memory", "raw", "zhiyi", "experience_lancedb", "runtime", "data", "state", "input", "output"):
        assert f'"{path}"' in windows_backup
    assert "Merge-PackagedConfig" in windows
    assert '"tools\\install_config_merge.py"' in windows
    assert '"tools\\install_state_migrate.py"' in windows
    assert "Migrate-LegacyStatePaths" in windows
    assert "(-not $migratedLegacy)" in windows
    for name in ("raw", "data", "state", "input", "update_staging", "update_history.jsonl"):
        assert f'"{name}"' in windows


def test_unix_regular_reinstall_backup_excludes_large_runtime_data():
    for name in ("macos_full_install.sh", "linux_full_install.sh"):
        installer = (ROOT / "tools" / name).read_text(encoding="utf-8")
        backup = installer.split("backup_program_files() {", 1)[1].split("\n}", 1)[0]
        for path in ("memory/", "raw/", "zhiyi/", "experience_lancedb/", "runtime/", "output/", ".playwright-cli/"):
            assert f"--exclude '{path}'" in backup


def test_state_migration_rewrites_roots_and_keeps_highest_checkpoint_offset(tmp_path):
    module = _load_state_migrate_module()
    legacy = tmp_path / "memcore-cloud"
    install = tmp_path / "time-library"
    install.mkdir()
    old_raw = legacy / "memory/node/codex/session.jsonl"
    new_raw = install / "memory/node/codex/session.jsonl"
    (install / ".checkpoint_p2.json").write_text(
        json.dumps(
            {
                str(old_raw): {"offset": 900, "last_update": "old"},
                str(new_raw): {"offset": 400, "last_update": "new"},
            }
        ),
        encoding="utf-8",
    )
    new_raw.parent.mkdir(parents=True)
    new_raw.write_bytes(b"x" * 500)
    (install / ".checkpoint").write_text(
        json.dumps({"codex:/source.jsonl": {"offset": 10, "archived_to": str(old_raw)}}),
        encoding="utf-8",
    )
    config = install / "config"
    config.mkdir()
    (config / "window_binding_registry.json").write_text(
        json.dumps({"current_windows": {"codex": {"source_path": str(old_raw)}}}),
        encoding="utf-8",
    )
    (config / "reading_area_registry.json").write_text(
        json.dumps({"projects": {"project:one": {"source_path": str(old_raw)}}}),
        encoding="utf-8",
    )

    result = module.migrate_install_state(install, legacy)

    p2 = json.loads((install / ".checkpoint_p2.json").read_text(encoding="utf-8"))
    assert list(p2) == [str(new_raw)]
    assert p2[str(new_raw)]["offset"] == 500
    assert p2[str(new_raw)]["migration_source_regression_offset_before"] == 900
    assert p2[str(new_raw)]["migration_status"] == "source_regression_cursor_clamped_to_preserved_raw_size"
    p0 = json.loads((install / ".checkpoint").read_text(encoding="utf-8"))
    assert p0["codex:/source.jsonl"]["archived_to"] == str(new_raw)
    registry = json.loads((config / "window_binding_registry.json").read_text(encoding="utf-8"))
    assert registry["current_windows"]["codex"]["source_path"] == str(new_raw)
    reading_registry = json.loads((config / "reading_area_registry.json").read_text(encoding="utf-8"))
    assert reading_registry["projects"]["project:one"]["source_path"] == str(new_raw)
    assert result["changed_count"] == 4
    assert len(list(install.glob(".checkpoint*.pre-root-migration.*.json"))) == 2

    second = module.migrate_install_state(install, legacy)
    assert second["changed_count"] == 0
