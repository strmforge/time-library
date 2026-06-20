import importlib.util
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_release_artifact.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_release_artifact_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_release_artifact_builder_defaults_to_head_and_writes_zip_checksum():
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'default="head"' in text
    assert "git\", \"archive\"" in text
    assert "working-tree" in text
    assert "git\", \"ls-files\"" in text
    assert ".sha256" in text
    assert "memcore-cloud-{version}" in text
    assert "EXCLUDED_PATH_PARTS" in text
    assert "EXCLUDED_TOP_LEVEL_FILES" in text
    assert "EXCLUDED_RELATIVE_PATHS" in text
    assert "EXCLUDED_RELATIVE_PREFIXES" in text
    assert '"AGENTS.md"' in text
    assert '"docs/github-positioning-2026.6.16.md"' in text
    assert '"benchmarks/eval-runs/"' in text


def test_release_artifact_working_tree_package_excludes_ignored_runtime_data(tmp_path):
    builder = _load_builder()
    if not (ROOT / ".git").exists():
        return

    result = builder.build_artifact(source="working-tree", output_dir=tmp_path)

    zip_path = Path(result["zip"])
    sha_path = Path(result["sha256"])
    assert zip_path.exists()
    assert sha_path.exists()
    assert result["checksum"] in sha_path.read_text(encoding="ascii")
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    assert any(name.endswith("/VERSION") for name in names)
    assert any(name.endswith("/tools/build_release_artifact.py") for name in names)
    assert any(name.endswith("/config/memcore.json") for name in names)
    assert any(name.endswith("/config/default_model_config.json") for name in names)
    assert any(name.endswith("/config/default_feature_flags.json") for name in names)
    assert any(name.endswith("/config/intent_router_rules.json") for name in names)
    assert not any("/.git/" in name or name.endswith("/.checkpoint") for name in names)
    assert not any("/memory/" in name or "/logs/" in name or "/output/" in name for name in names)
    assert not any("/runtime/" in name for name in names)
    assert not any(name.endswith("/raw") for name in names)
    assert not any("/release/" in name for name in names)
    assert not any(name.endswith("/AGENTS.md") for name in names)
    assert not any(name.endswith("/docs/github-positioning-2026.6.16.md") for name in names)
    assert not any("/benchmarks/cache/" in name for name in names)
    assert not any("/benchmarks/eval-runs/" in name for name in names)
    assert not any("/benchmarks/results/" in name for name in names)
    assert not any(name.endswith("/config/window_binding_registry.json") for name in names)


def test_release_artifact_contains_dialog_entry_lan_safety_contract(tmp_path):
    builder = _load_builder()
    if not (ROOT / ".git").exists():
        return

    result = builder.build_artifact(source="working-tree", output_dir=tmp_path)
    with zipfile.ZipFile(Path(result["zip"])) as archive:
        payload = {
            name.split("/", 1)[1]: archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.endswith((
                "install.ps1",
                "Memcore Cloud Installer.command",
                "Memcore Cloud Installer.cmd",
                "tools/windows_full_install.ps1",
                "tools/windows_double_click_install.ps1",
                "tools/windows_guardian.ps1",
                "tools/macos_full_install.sh",
                "tools/linux_full_install.sh",
                "system/openclaw/plugins/memcore-zhiyi-native/index.js",
            ))
        }

    assert "DialogEntryHost" in payload["install.ps1"]
    assert "DialogEntryEndpointUrl" in payload["install.ps1"]
    assert "DialogEntryToken" in payload["install.ps1"]
    assert "bash ./install.sh" in payload["Memcore Cloud Installer.command"]
    assert "windows_double_click_install.ps1" in payload["Memcore Cloud Installer.cmd"]
    assert "FolderBrowserDialog" in payload["tools/windows_double_click_install.ps1"]
    assert "-Dir $installRoot" in payload["tools/windows_double_click_install.ps1"]
    assert "Ensure-DialogEntryToken" in payload["tools/windows_full_install.ps1"]
    assert "Backup-InstallFilesBestEffort" in payload["tools/windows_full_install.ps1"]
    assert "Copy-Item -Path $InstallRoot -Destination $backup -Recurse -Force" not in payload["tools/windows_full_install.ps1"]
    assert '"memory", "raw", "zhiyi"' in payload["tools/windows_full_install.ps1"]
    assert "Get-DialogEntryHost" in payload["tools/windows_guardian.ps1"]
    assert "--host $dialogEntryHost --port 9860" in payload["tools/windows_guardian.ps1"]
    assert "ensure_dialog_entry_token" in payload["tools/macos_full_install.sh"]
    assert "ensure_dialog_entry_token" in payload["tools/linux_full_install.sh"]
    assert "dialogEntryToken" in payload["system/openclaw/plugins/memcore-zhiyi-native/index.js"]
    assert "headers.Authorization" in payload["system/openclaw/plugins/memcore-zhiyi-native/index.js"]
