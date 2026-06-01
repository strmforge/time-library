import importlib
import json
import os
import plistlib
import sys
import time
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_module():
    sys.modules.pop("platform_autodiscovery", None)
    return importlib.import_module("platform_autodiscovery")


def test_platform_autodiscovery_is_read_only_and_thin_adapter_based():
    autodiscovery = _load_module()
    profile = {
        "memcore_cloud": {"status": "active", "instances": [{}]},
        "openclaw": {"status": "not_found", "instances": []},
        "hermes": {"status": "detected", "instances": [{}]},
        "claude_desktop": {
            "status": "detected",
            "instances": [{}, {}],
            "consumer_connection": {
                "skill_detected": True,
                "mcp_detected": False,
                "recall_connection_ready": False,
            },
            "read_boundary": {"content_parser_gate": "explicit_authorized_parser_required"},
        },
    }

    result = autodiscovery.build_autodiscovery(profile)
    claude = next(item for item in result["systems"] if item["system"] == "claude_desktop")

    assert result["name"] == "Memcore Cloud"
    assert result["codename"] == "Yifanchen"
    assert result["read_only"] is True
    assert result["platform_write_performed"] is False
    assert result["architecture"]["adapter_strategy"] == "tiandao_plus_thin_adapters"
    assert result["architecture"]["adapter_registry"] == "platform_thin_adapter_registry"
    assert "cursor" in result["known_adapter_targets"]
    assert "claude_code_cli" in result["known_adapter_targets"]
    assert result["thin_adapter_registry"]["read_only"] is True
    assert result["thin_adapter_registry"]["platform_write_performed"] is False
    assert result["authorization_contract"]["skill_installation_is_consent_signal"] is True
    assert result["authorization_contract"]["skill_installation_is_not_body_read_consent"] is True
    assert result["authorization_contract"]["can_parse_chat_bodies_without_authorization"] is False
    assert claude["thin_adapter"] is True
    assert claude["intent_signal_detected"] is True
    assert claude["connectable_now"] is False
    assert claude["content_gate"] == "explicit_authorized_parser_required"
    assert any(action["action"] == "register_missing_thin_adapter" for action in claude["actions"])
    assert any(action["action"] == "raw_parser_gate" and action["status"] == "locked" for action in claude["actions"])


def test_authorized_auto_connect_plan_never_applies_by_default():
    autodiscovery = _load_module()
    profile = {
        "memcore_cloud": {"status": "active", "instances": [{}]},
        "openclaw": {"status": "detected", "instances": [{}]},
        "hermes": {"status": "not_found", "instances": []},
        "claude_desktop": {
            "status": "detected",
            "instances": [{}],
            "consumer_connection": {
                "skill_detected": True,
                "mcp_detected": False,
                "recall_connection_ready": False,
            },
        },
    }

    plan = autodiscovery.build_authorized_autoconnect_plan(profile)

    assert plan["read_only"] is True
    assert plan["dry_run"] is True
    assert plan["platform_write_performed"] is False
    assert plan["apply_endpoint_status"] == "not_implemented"
    assert "confirm_user_requested_auto_connect" in plan["required_confirmations"]
    assert any(item["system"] == "claude_desktop" for item in plan["planned_actions"])


def test_thin_adapter_registry_detects_candidates_without_reading_or_writing(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    cursor = home / ".cursor"
    cursor.mkdir(parents=True)
    (cursor / "mcp.json").write_text(
        '{"mcpServers":{"memcore-cloud":{"url":"http://127.0.0.1:9851/mcp","apiKey":"SECRET"}}}',
        encoding="utf-8",
    )
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text('{"model":"claude"}', encoding="utf-8")

    result = registry_module.build_thin_adapter_registry(
        {},
        home=home,
        env={"CODEX_HOME": str(home / ".codex")},
    )
    adapters = {item["system"]: item for item in result["adapters"]}
    cursor_plan = adapters["cursor"]
    claude_code_plan = adapters["claude_code_cli"]

    assert result["read_only"] is True
    assert result["platform_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert cursor_plan["detected"] is True
    assert cursor_plan["mcp_config_detected"] is True
    assert cursor_plan["memcore_mcp_detected"] is True
    assert cursor_plan["connectable_now"] is True
    assert cursor_plan["intent_signal_detected"] is True
    assert cursor_plan["chat_body_parser_requires_separate_authorization"] is True
    assert any(action["action"] == "capability_check" and action["status"] == "ready" for action in cursor_plan["actions"])
    assert cursor_plan["signals"][0]["redacted_mcp_servers"]["memcore-cloud"]["apiKey"] == "<redacted>"
    assert claude_code_plan["detected"] is True
    assert claude_code_plan["current_focus"] is True
    assert claude_code_plan["support_level"] == "adapter_candidate_separate_claude_surface"
    assert any(action["action"] == "offer_connect_prompt" for action in claude_code_plan["actions"])


def test_platform_catalog_loads_curated_and_github_watchlist_entries():
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")

    catalog = registry_module.load_platform_catalog()
    ids = {item["id"] for item in catalog["entries"]}

    assert catalog["contract"] == "platform_catalog.v1"
    assert catalog["read_only"] is True
    assert catalog["platform_write_performed"] is False
    assert catalog["curated_entry_count"] >= 12
    assert catalog["github_watchlist_entry_count"] == 100
    assert catalog["entry_count"] >= 100
    assert "gemini_cli" in ids
    assert "windsurf" in ids
    assert "vscode_copilot" in ids
    assert any(item.get("catalog_level") == "github_top100_watchlist" for item in catalog["entries"])
    assert all(item.get("source_urls") for item in catalog["entries"][:12])


def test_package_manager_inventory_detects_agent_ecosystem_from_catalog(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"

    npm_root = tmp_path / "npm" / "lib" / "node_modules"
    opencode_pkg = npm_root / "opencode"
    opencode_pkg.mkdir(parents=True)
    (opencode_pkg / "package.json").write_text(
        '{"name":"opencode","version":"1.2.3","description":"open source coding agent"}',
        encoding="utf-8",
    )

    brew_prefix = tmp_path / "brew"
    (brew_prefix / "Cellar" / "gemini-cli" / "0.9.0").mkdir(parents=True)

    docker_list = tmp_path / "docker-images.txt"
    docker_list.write_text("n8nio/n8n:latest\n", encoding="utf-8")

    compose_dir = home / "workspace" / "dify-stack"
    compose_dir.mkdir(parents=True)
    (compose_dir / "compose.yaml").write_text(
        "services:\n  dify:\n    image: langgenius/dify-api:latest\n",
        encoding="utf-8",
    )

    env = {
        "MEMCORE_PACKAGE_SCAN_STRICT_ROOTS": "1",
        "MEMCORE_NPM_GLOBAL_ROOT": str(npm_root),
        "MEMCORE_BREW_PREFIX": str(brew_prefix),
        "MEMCORE_DOCKER_IMAGE_LIST": str(docker_list),
    }
    inventory = registry_module.build_package_manager_agent_inventory(home=home, env=env)
    matches = {(item["system"], item["manager"]) for item in inventory["matches"]}

    assert inventory["contract"] == "package_manager_agent_inventory.v1"
    assert inventory["read_only"] is True
    assert inventory["platform_write_performed"] is False
    assert inventory["global_guarantees"]["does_not_install_packages"] is True
    assert ("github_anomalyco_opencode", "npm_global") in matches
    assert ("gemini_cli", "homebrew") in matches
    assert ("github_n8n_io_n8n", "docker_image") in matches
    assert ("github_langgenius_dify", "docker_compose") in matches


def test_platform_discovery_skips_untrusted_windows_mount_point(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    blocked = home / "AppData" / "Local" / "Temporary Internet Files" / "Content.IE5"
    blocked.mkdir(parents=True)
    compose = home / "workspace" / "dify-stack" / "compose.yaml"
    compose.parent.mkdir(parents=True)
    compose.write_text(
        "services:\n  dify:\n    image: langgenius/dify-api:latest\n",
        encoding="utf-8",
    )
    original_is_file = Path.is_file
    original_is_dir = Path.is_dir

    def guarded_is_file(path):
        if path.name == "Content.IE5":
            raise OSError("[WinError 448] cannot traverse path because it contains an untrusted mount point")
        return original_is_file(path)

    def guarded_is_dir(path):
        if path.name == "Content.IE5":
            raise OSError("[WinError 448] cannot traverse path because it contains an untrusted mount point")
        return original_is_dir(path)

    with patch.object(Path, "is_file", guarded_is_file), patch.object(Path, "is_dir", guarded_is_dir):
        inventory = registry_module.build_package_manager_agent_inventory(
            home=home,
            env={"LOCALAPPDATA": str(home / "AppData" / "Local")},
        )
        dashboard = registry_module.build_platform_discovery_dashboard(
            {},
            home=home,
            env={"LOCALAPPDATA": str(home / "AppData" / "Local")},
        )

    matches = {(item["system"], item["manager"]) for item in inventory["matches"]}
    assert ("github_langgenius_dify", "docker_compose") in matches
    assert dashboard["ok"] is True
    assert dashboard["counts"]["total"] >= 1


def test_thin_adapter_registry_distinguishes_plain_detection_from_memcore_signal(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    continue_home = home / ".continue"
    continue_home.mkdir(parents=True)
    (continue_home / "config.json").write_text(
        '{"models":[{"title":"local"}],"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )

    result = registry_module.build_thin_adapter_registry({}, home=home, env={})
    adapters = {item["system"]: item for item in result["adapters"]}
    continue_plan = adapters["continue"]

    assert continue_plan["detected"] is True
    assert continue_plan["mcp_config_detected"] is True
    assert continue_plan["memcore_mcp_detected"] is False
    assert continue_plan["connectable_now"] is False
    assert continue_plan["intent_signal_detected"] is False
    assert any(action["action"] == "offer_connect_prompt" for action in continue_plan["actions"])


def test_thin_adapter_registry_reports_app_version_and_usage_freshness(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    app_root = tmp_path / "Applications"
    cursor_info = app_root / "Cursor.app" / "Contents" / "Info.plist"
    cursor_info.parent.mkdir(parents=True)
    with cursor_info.open("wb") as fh:
        plistlib.dump({
            "CFBundleShortVersionString": "1.2.3",
            "CFBundleVersion": "456",
        }, fh)
    cursor_home = home / ".cursor"
    cursor_home.mkdir(parents=True)
    (cursor_home / "mcp.json").write_text(
        '{"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )
    workspace_storage = home / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage"
    workspace_storage.mkdir(parents=True)
    old = time.time() - (220 * 86400)
    os.utime(workspace_storage, (old, old))

    result = registry_module.build_thin_adapter_registry(
        {},
        home=home,
        env={"MEMCORE_APP_ROOTS": str(app_root)},
    )
    cursor = {item["system"]: item for item in result["adapters"]}["cursor"]

    assert cursor["software"]["app"]["installed"] is True
    assert cursor["software"]["app"]["version"] == "1.2.3"
    assert cursor["software"]["app"]["build"] == "456"
    assert cursor["activity"]["primary_source"] == "content_store"
    assert cursor["activity"]["freshness"] == "dormant"

    dashboard = registry_module.build_platform_discovery_dashboard(
        {},
        home=home,
        env={"MEMCORE_APP_ROOTS": str(app_root)},
    )
    dashboard_cursor = {item["system"]: item for item in dashboard["items"]}["cursor"]
    assert dashboard_cursor["software"]["app"]["version"] == "1.2.3"
    assert dashboard_cursor["freshness"] == "dormant"


def test_authorized_auto_connect_dry_run_reports_writes_backups_and_rollbacks(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    cursor = home / ".cursor"
    cursor.mkdir(parents=True)
    (cursor / "mcp.json").write_text(
        '{"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )

    result = registry_module.build_authorized_auto_connect_dry_run({}, home=home, env={}, system="cursor")
    plan = result["plans"][0]

    assert result["contract"] == "authorized_auto_connect_dry_run.v1"
    assert result["read_only"] is True
    assert result["platform_write_performed"] is False
    assert result["global_guarantees"]["does_not_write_platform_config"] is True
    assert plan["system"] == "cursor"
    assert plan["status"] == "needs_authorization"
    assert plan["missing"] == ["memcore_mcp_registration", "capability_check_connection"]
    assert plan["write_strategy"] == "register_loopback_mcp_server"
    assert str(cursor / "mcp.json") in plan["would_write"]
    assert plan["backup_required"] is True
    assert plan["receipt_required"] is True
    assert plan["restart_required"] is True
    assert plan["capability_check_after_connect"] is True
    assert plan["real_recall_after_connect"] is False
    assert plan["rollback_plan"] == "restore_backup_file_and_remove_added_mcp_server"
    assert plan["apply_endpoint_status"] == "implemented_for_json_mcp_surfaces"


def test_authorized_auto_connect_dry_run_skips_writes_when_already_connectable(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    cursor = home / ".cursor"
    cursor.mkdir(parents=True)
    (cursor / "mcp.json").write_text(
        '{"mcpServers":{"memcore-cloud":{"url":"http://127.0.0.1:9851/mcp"}}}',
        encoding="utf-8",
    )

    result = registry_module.build_authorized_auto_connect_dry_run({}, home=home, env={}, system="cursor")
    plan = result["plans"][0]

    assert plan["status"] == "ready_for_capability_check"
    assert plan["missing"] == []
    assert plan["would_write"] == []
    assert plan["backup_required"] is False
    assert plan["capability_check_payload"]["mode"] == "capability_check"
    assert plan["chat_body_parser_requires_separate_authorization"] is True


def test_generic_local_ai_surface_scan_detects_kiro_mcp_without_hardcoded_adapter(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    kiro_settings = home / ".kiro" / "settings"
    kiro_settings.mkdir(parents=True)
    (kiro_settings / "mcp.json").write_text(
        '{"mcpServers":{"yifanchen-zhiyi":{"url":"http://127.0.0.1:9851/mcp","apiKey":"SECRET"}}}',
        encoding="utf-8",
    )

    generic = registry_module.build_generic_local_ai_surfaces(home=home, env={})
    surfaces = {item["system"]: item for item in generic["surfaces"]}
    assert generic["contract"] == "generic_local_ai_surface_discovery.v1"
    assert generic["read_only"] is True
    assert generic["platform_write_performed"] is False
    assert "kiro" in surfaces
    assert surfaces["kiro"]["generic_surface"] is True
    assert surfaces["kiro"]["mcp_config_detected"] is True
    assert surfaces["kiro"]["memcore_mcp_detected"] is True
    assert surfaces["kiro"]["connectable_now"] is True
    assert surfaces["kiro"]["content_read"] is False
    assert surfaces["kiro"]["signals"][0]["redacted_mcp_servers"]["yifanchen-zhiyi"]["apiKey"] == "<redacted>"

    registry = registry_module.build_thin_adapter_registry({}, home=home, env={})
    generic_registry = {item["system"]: item for item in registry["generic_surface_discovery"]["surfaces"]}
    assert "kiro" in generic_registry


def test_catalog_driven_scan_detects_gemini_cli_mcp_config(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    gemini = home / ".gemini"
    gemini.mkdir(parents=True)
    (gemini / "settings.json").write_text(
        '{"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )

    generic = registry_module.build_generic_local_ai_surfaces(home=home, env={})
    surfaces = {item["system"]: item for item in generic["surfaces"]}
    gemini_surface = surfaces["gemini_cli"]

    assert generic["catalog"]["github_watchlist_entry_count"] == 100
    assert gemini_surface["catalog_driven"] is True
    assert gemini_surface["catalog_entry"]["display_name"] == "Gemini CLI"
    assert gemini_surface["mcp_config_detected"] is True
    assert gemini_surface["connectable_now"] is False

    plan = registry_module.build_authorized_auto_connect_dry_run({}, home=home, env={}, system="gemini_cli")
    assert plan["plans"][0]["apply_endpoint_status"] == "implemented_for_json_mcp_surfaces"
    assert str(gemini / "settings.json") in plan["plans"][0]["would_write"]


def test_github_watchlist_repo_scan_detects_agent_clone_without_reading_source(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    repo = home / "workspace" / "opencode"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\nurl = https://github.com/anomalyco/opencode.git\n',
        encoding="utf-8",
    )
    (repo / "package.json").write_text('{"name":"opencode"}', encoding="utf-8")

    generic = registry_module.build_generic_local_ai_surfaces(home=home, env={})
    surfaces = {item["system"]: item for item in generic["surfaces"]}
    opencode = surfaces["github_anomalyco_opencode"]

    assert opencode["catalog_driven"] is True
    assert opencode["catalog_entry"]["catalog_level"] == "github_top100_watchlist"
    assert opencode["catalog_entry"]["repo"]["full_name"] == "anomalyco/opencode"
    assert str(repo) in opencode["workspace_paths"]
    assert any(signal["kind"] == "github_watchlist_repo" and signal["source_read"] is False for signal in opencode["signals"])


def test_package_manager_matches_become_generic_surfaces(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    npm_root = tmp_path / "npm" / "lib" / "node_modules"
    opencode_pkg = npm_root / "opencode"
    opencode_pkg.mkdir(parents=True)
    (opencode_pkg / "package.json").write_text('{"name":"opencode","version":"1.2.3"}', encoding="utf-8")

    env = {
        "MEMCORE_PACKAGE_SCAN_STRICT_ROOTS": "1",
        "MEMCORE_NPM_GLOBAL_ROOT": str(npm_root),
    }
    generic = registry_module.build_generic_local_ai_surfaces(home=home, env=env)
    surfaces = {item["system"]: item for item in generic["surfaces"]}
    opencode = surfaces["github_anomalyco_opencode"]

    assert generic["package_manager_inventory"]["match_count"] >= 1
    assert opencode["catalog_entry"]["catalog_level"] == "github_top100_watchlist"
    assert str(opencode_pkg) in opencode["installation_paths"]
    assert any(signal["kind"] == "package_manager_install" and signal["manager"] == "npm_global" for signal in opencode["signals"])


def test_generic_workspace_scan_detects_nested_kiro_without_config_or_content_read(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    kiro_specs = home / "Desktop" / "Project" / ".kiro" / "specs"
    kiro_specs.mkdir(parents=True)
    (kiro_specs / "requirements.md").write_text("# requirements", encoding="utf-8")

    generic = registry_module.build_generic_local_ai_surfaces(home=home, env={})
    surfaces = {item["system"]: item for item in generic["surfaces"]}
    kiro = surfaces["kiro"]

    assert kiro["source"] == "generic_workspace_surface_scan"
    assert kiro["mcp_config_detected"] is False
    assert kiro["memcore_mcp_detected"] is False
    assert kiro["connectable_now"] is False
    assert kiro["content_read"] is False
    assert kiro["config_paths"] == []
    assert str(kiro_specs.parent) in kiro["content_store_paths"]

    plan = registry_module.build_authorized_auto_connect_dry_run({}, home=home, env={}, system="kiro")
    assert plan["plans"][0]["status"] == "needs_authorization"
    assert plan["plans"][0]["would_write"] == []

    dashboard = registry_module.build_platform_discovery_dashboard({}, home=home, env={})
    items = {item["system"]: item for item in dashboard["items"]}
    assert items["kiro"]["content_bearing_store_detected"] is True
    assert items["kiro"]["content_store_paths"] == [str(kiro_specs.parent)]


def test_windows_local_agent_directory_aliases_become_surfaces(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    local_appdata = home / "AppData" / "Local"
    roaming = home / "AppData" / "Roaming"
    for path in (
        home / ".cc-switch",
        home / ".clawui",
        home / ".codebuddycn",
        home / ".codex-pro",
        home / ".copilot",
        home / ".minimax-agent-cn",
        roaming / "Codex++",
        local_appdata / "ima.copilot",
    ):
        path.mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={
            "APPDATA": str(roaming),
            "LOCALAPPDATA": str(local_appdata),
        },
    )
    surfaces = {item["system"]: item for item in generic["surfaces"]}

    assert "cc_switch" in surfaces
    assert "clawui" in surfaces
    assert "codebuddy" in surfaces
    assert "codex" in surfaces
    assert "vscode_copilot" in surfaces
    assert "minimax_agent" in surfaces
    assert surfaces["cc_switch"]["display_name"] == "CC Switch"
    assert surfaces["codebuddy"]["display_name"] == "CodeBuddy"
    assert surfaces["minimax_agent"]["display_name"] == "MiniMax Agent"
    assert str(home / ".cc-switch") in surfaces["cc_switch"]["workspace_paths"]
    assert str(home / ".codebuddycn") in surfaces["codebuddy"]["workspace_paths"]
    assert str(roaming / "Codex++") in surfaces["codex"]["workspace_paths"]
    assert str(local_appdata / "ima.copilot") in surfaces["vscode_copilot"]["workspace_paths"]
    assert all(surface["content_read"] is False for surface in surfaces.values())


def test_generic_scan_filters_project_and_runtime_artifact_directories(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    for name in (
        "ntm-codex-runtime-jobs-123",
        "ntm_codex_crew_run_smoke_abcd",
        "memcore-codex-win-verify",
        "memcore-cloud-2026-6-1-claude-src",
        "aether-codex-review-123",
        "enquire-mcp-r56",
    ):
        (home / "workspace" / name).mkdir(parents=True)
    (home / "workspace" / "real-codex-panel").mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(home=home, env={})
    ids = {item["system"] for item in generic["surfaces"]}

    assert "real_codex_panel" in ids
    assert not any(system.startswith("ntm_codex") for system in ids)
    assert not any(system.startswith("memcore") for system in ids)
    assert not any(system.startswith("aether_codex_review") for system in ids)
    assert not any(system.startswith("enquire_mcp") for system in ids)


def test_generic_scan_filters_backup_temp_and_updater_noise(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    appdata_local = home / "AppData" / "Local"
    appdata_roaming = home / "AppData" / "Roaming"
    for path in (
        home / ".openclaw.bak",
        home / ".qclaw-backups",
        appdata_local / "Temp" / "CC Switch-3.16.0-updater-fnwUHX",
        appdata_local / "Temp" / "deepseek_rlm_ctx",
        appdata_local / "Temp" / "DeepSeek-Reasonix-main-v2-readonly",
        appdata_local / "Temp" / "agentskills-r59",
        appdata_roaming / "Kiro",
        home / ".codebuddy",
        home / ".cc-switch",
    ):
        path.mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={"LOCALAPPDATA": str(appdata_local), "APPDATA": str(appdata_roaming)},
    )
    surfaces = {item["system"]: item for item in generic["surfaces"]}

    assert "kiro" in surfaces
    assert "codebuddy" in surfaces
    assert "cc_switch" in surfaces
    assert "openclaw_bak" not in surfaces
    assert "qclaw_backups" not in surfaces
    assert "deepseek_rlm_ctx" not in surfaces
    assert "deepseek_reasonix_main_v2_readonly" not in surfaces
    assert "cc_switch" in surfaces
    assert all("Temp" not in path for item in surfaces.values() for path in item["workspace_paths"])


def test_nested_generic_mcp_config_uses_hidden_tool_directory_as_surface_id(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    kiro_settings = home / "Desktop" / "Project" / ".kiro" / "settings"
    kiro_settings.mkdir(parents=True)
    (kiro_settings / "mcp.json").write_text(
        '{"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )

    result = registry_module.build_authorized_auto_connect_dry_run({}, home=home, env={}, system="kiro")
    plan = result["plans"][0]

    assert plan["system"] == "kiro"
    assert plan["status"] == "needs_authorization"
    assert str(kiro_settings / "mcp.json") in plan["would_write"]


def test_generic_surface_can_get_authorized_connect_plan(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    kiro_settings = home / ".kiro" / "settings"
    kiro_settings.mkdir(parents=True)
    (kiro_settings / "mcp.json").write_text(
        '{"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )

    result = registry_module.build_authorized_auto_connect_dry_run({}, home=home, env={}, system="kiro")
    plan = result["plans"][0]

    assert result["read_only"] is True
    assert result["platform_write_performed"] is False
    assert plan["system"] == "kiro"
    assert plan["support_level"] == "generic_surface_candidate"
    assert plan["status"] == "needs_authorization"
    assert str(kiro_settings / "mcp.json") in plan["would_write"]
    assert plan["backup_required"] is True
    assert plan["apply_endpoint_status"] == "implemented_for_json_mcp_surfaces"


def test_platform_discovery_dashboard_merges_known_and_generic_surfaces(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True)
    (codex_home / "config.toml").write_text(
        '[mcp_servers.yifanchen-zhiyi]\nurl = "http://127.0.0.1:9851/mcp"\n',
        encoding="utf-8",
    )
    kiro_settings = home / ".kiro" / "settings"
    kiro_settings.mkdir(parents=True)
    (kiro_settings / "mcp.json").write_text(
        '{"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )

    dashboard = registry_module.build_platform_discovery_dashboard(
        {},
        home=home,
        env={"CODEX_HOME": str(codex_home)},
    )
    items = {item["system"]: item for item in dashboard["items"]}

    assert dashboard["contract"] == "platform_discovery_dashboard.v1"
    assert dashboard["name"] == "Memcore Cloud"
    assert dashboard["read_only"] is True
    assert dashboard["dashboard_goal"] == "show_local_ai_tools_with_safe_next_steps"
    assert dashboard["platform_write_performed"] is False
    assert dashboard["memory_write_performed"] is False
    assert dashboard["public_summary"]["local_ai_tools"] == dashboard["counts"]["total"]
    assert dashboard["public_summary"]["ready_for_safe_check"] == dashboard["counts"]["ready_for_capability_check"]
    assert dashboard["public_summary"]["needs_permission_step"] == dashboard["counts"]["needs_authorization"]
    assert dashboard["global_guarantees"]["does_not_parse_chat_bodies"] is True
    assert dashboard["global_guarantees"]["does_not_write_platform_config"] is True
    assert items["codex"]["surface_type"] == "known_thin_adapter"
    assert items["codex"]["status"] == "ready_for_capability_check"
    assert items["codex"]["safe_next_step"] == "run_capability_check"
    assert items["codex"]["capability_check_payload"]["mode"] == "capability_check"
    assert items["kiro"]["surface_type"] == "generic_local_ai_surface"
    assert items["kiro"]["status"] == "needs_authorization"
    assert items["kiro"]["safe_next_step"] == "inspect_authorized_connect_plan"
    assert items["kiro"]["authorized_connect_plan_endpoint"] == "/api/v1/platforms/kiro/authorized-connect-plan"
    assert all(item["writes_now"] is False for item in dashboard["items"])
    assert all(item["reads_chat_bodies"] is False for item in dashboard["items"])


def test_platform_discovery_dashboard_keeps_claude_code_connectable_but_separate(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    claude_home = home / ".claude"
    claude_home.mkdir(parents=True)
    (claude_home / "settings.json").write_text('{"model":"claude"}', encoding="utf-8")

    dashboard = registry_module.build_platform_discovery_dashboard({}, home=home, env={})
    claude_code = next(item for item in dashboard["items"] if item["system"] == "claude_code_cli")

    assert claude_code["status"] == "needs_authorization"
    assert claude_code["safe_next_step"] == "inspect_authorized_connect_plan"
    assert claude_code["current_focus"] is True
    assert claude_code["support_level"] == "adapter_candidate_separate_claude_surface"
    assert claude_code["writes_now"] is False
    assert claude_code["reads_chat_bodies"] is False


def test_claude_code_cli_authorized_plan_targets_official_mcp_config(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    home.mkdir(parents=True)
    claude_json = home / ".claude.json"
    claude_json.write_text('{"projects":{}}', encoding="utf-8")

    result = registry_module.build_authorized_auto_connect_dry_run({}, home=home, env={}, system="claude_code_cli")
    plan = result["plans"][0]

    assert plan["system"] == "claude_code_cli"
    assert plan["status"] == "needs_authorization"
    assert plan["write_strategy"] == "use_claude_mcp_add_or_update_mcp_json"
    assert str(claude_json) in plan["would_write"]
    assert plan["backup_required"] is True
    assert plan["real_recall_after_connect"] is False
    assert plan["chat_body_parser_requires_separate_authorization"] is True


def test_authorized_auto_connect_apply_gate_blocks_without_confirmations(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    cursor = home / ".cursor"
    cursor.mkdir(parents=True)
    (cursor / "mcp.json").write_text(
        '{"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )

    gate = registry_module.build_authorized_auto_connect_apply_gate_dry_run(
        {"system": "cursor"},
        home=home,
        env={},
    )

    assert gate["contract"] == "authorized_auto_connect_apply_gate.v1"
    assert gate["read_only"] is True
    assert gate["platform_write_performed"] is False
    assert gate["status"] == "blocked"
    assert gate["ready_after_authorization"] is False
    assert "missing_authorization_confirmations" in gate["blocked_reasons"]
    assert "confirm_user_requested_auto_connect" in gate["missing_confirmations"]
    assert gate["receipt_preview"]["would_write"] == [str(cursor / "mcp.json")]
    assert gate["apply_endpoint_status"] == "implemented_for_json_mcp_surfaces"


def test_authorized_auto_connect_apply_gate_ready_after_all_confirmations(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    claude_json = home / ".claude.json"
    home.mkdir(parents=True)
    claude_json.write_text('{"projects":{}}', encoding="utf-8")
    confirmations = [
        "confirm_user_requested_auto_connect",
        "confirm_backup_before_platform_config_write",
        "confirm_receipt_after_each_platform_write",
        "confirm_capability_check_only_after_connect",
        "confirm_no_chat_body_parser_without_separate_authorization",
    ]

    gate = registry_module.build_authorized_auto_connect_apply_gate_dry_run(
        {"system": "claude_code_cli", "confirmations": confirmations},
        home=home,
        env={},
    )

    assert gate["status"] == "ready_after_authorization"
    assert gate["ready_after_authorization"] is True
    assert gate["missing_confirmations"] == []
    assert gate["write_performed"] is False
    assert gate["platform_write_performed"] is False
    assert gate["receipt_preview"]["system"] == "claude_code_cli"
    assert gate["receipt_preview"]["real_recall_after_connect"] is False
    assert gate["receipt_preview"]["chat_body_parser_requires_separate_authorization"] is True
    assert str(claude_json) in gate["receipt_preview"]["would_write"]
    assert gate["apply_endpoint_status"] == "implemented_for_json_mcp_surfaces"


def test_authorized_auto_connect_apply_gate_requires_extra_confirmation_for_stale_writes(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    cursor_config = home / ".cursor" / "mcp.json"
    cursor_config.parent.mkdir(parents=True)
    cursor_config.write_text(
        '{"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )
    workspace_storage = home / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage"
    workspace_storage.mkdir(parents=True)
    old = time.time() - (220 * 86400)
    os.utime(workspace_storage, (old, old))
    confirmations = [
        "confirm_user_requested_auto_connect",
        "confirm_backup_before_platform_config_write",
        "confirm_receipt_after_each_platform_write",
        "confirm_capability_check_only_after_connect",
        "confirm_no_chat_body_parser_without_separate_authorization",
    ]

    blocked = registry_module.build_authorized_auto_connect_apply_gate_dry_run(
        {"system": "cursor", "confirmations": confirmations},
        home=home,
        env={},
    )
    ready = registry_module.build_authorized_auto_connect_apply_gate_dry_run(
        {
            "system": "cursor",
            "confirmations": confirmations + ["confirm_connect_stale_or_dormant_platform"],
        },
        home=home,
        env={},
    )

    assert blocked["status"] == "blocked"
    assert "confirm_connect_stale_or_dormant_platform" in blocked["missing_confirmations"]
    assert "stale_or_dormant_platform_requires_intentional_connect" in blocked["blocked_reasons"]
    assert blocked["receipt_preview"]["stale_or_dormant_confirmation_required"] is True
    assert blocked["receipt_preview"]["freshness"] == "dormant"
    assert ready["status"] == "ready_after_authorization"
    assert ready["missing_confirmations"] == []


def test_authorized_auto_connect_apply_writes_claude_code_mcp_with_backup_and_receipt(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    memcore_root = tmp_path / "memcore"
    claude_json = home / ".claude.json"
    home.mkdir(parents=True)
    claude_json.write_text('{"projects":{}}', encoding="utf-8")
    confirmations = [
        "confirm_user_requested_auto_connect",
        "confirm_backup_before_platform_config_write",
        "confirm_receipt_after_each_platform_write",
        "confirm_capability_check_only_after_connect",
        "confirm_no_chat_body_parser_without_separate_authorization",
    ]

    result = registry_module.apply_authorized_auto_connect(
        {"system": "claude_code_cli", "confirmations": confirmations},
        home=home,
        env={},
        memcore_root=memcore_root,
    )

    saved = json.loads(claude_json.read_text(encoding="utf-8"))
    server = saved["mcpServers"]["yifanchen-zhiyi"]

    assert result["ok"] is True
    assert result["contract"] == "authorized_auto_connect_apply.v1"
    assert result["status"] == "applied"
    assert result["platform_write_performed"] is True
    assert result["memory_write_performed"] is False
    assert result["real_recall_after_connect"] is False
    assert result["chat_body_parser_requires_separate_authorization"] is True
    assert server == {"type": "http", "url": "http://127.0.0.1:9851/mcp"}
    assert Path(result["backup_path"]).exists()
    assert Path(result["receipt_path"]).exists()
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["system"] == "claude_code_cli"
    assert receipt["platform_write_performed"] is True
    assert receipt["memory_write_performed"] is False


def test_authorized_auto_connect_apply_refuses_unimplemented_platform(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    home.mkdir(parents=True)
    confirmations = [
        "confirm_user_requested_auto_connect",
        "confirm_backup_before_platform_config_write",
        "confirm_receipt_after_each_platform_write",
        "confirm_capability_check_only_after_connect",
        "confirm_no_chat_body_parser_without_separate_authorization",
    ]

    result = registry_module.apply_authorized_auto_connect(
        {"system": "hermes", "confirmations": confirmations},
        home=home,
        env={},
        memcore_root=tmp_path / "memcore",
    )

    assert result["ok"] is False
    assert result["error"] == "apply_not_implemented_for_system"
    assert result["platform_write_performed"] is False
    assert "claude_code_cli" in result["implemented_apply_systems"]
    assert "cursor" in result["implemented_apply_systems"]
    assert "kiro" in result["implemented_apply_systems"]


def test_authorized_auto_connect_apply_writes_cursor_mcp_with_backup_and_receipt(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    memcore_root = tmp_path / "memcore"
    cursor_config = home / ".cursor" / "mcp.json"
    cursor_config.parent.mkdir(parents=True)
    cursor_config.write_text(
        '{"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )
    confirmations = [
        "confirm_user_requested_auto_connect",
        "confirm_backup_before_platform_config_write",
        "confirm_receipt_after_each_platform_write",
        "confirm_capability_check_only_after_connect",
        "confirm_no_chat_body_parser_without_separate_authorization",
    ]

    result = registry_module.apply_authorized_auto_connect(
        {"system": "cursor", "confirmations": confirmations},
        home=home,
        env={},
        memcore_root=memcore_root,
    )

    saved = json.loads(cursor_config.read_text(encoding="utf-8"))
    server = saved["mcpServers"]["yifanchen-zhiyi"]

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert result["platform_write_performed"] is True
    assert result["memory_write_performed"] is False
    assert server == {"type": "http", "url": "http://127.0.0.1:9851/mcp"}
    assert "other-tool" in saved["mcpServers"]
    assert Path(result["backup_path"]).exists()
    assert Path(result["receipt_path"]).exists()


def test_authorized_auto_connect_apply_writes_generic_kiro_mcp_with_backup_and_receipt(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    memcore_root = tmp_path / "memcore"
    kiro_config = home / ".kiro" / "settings" / "mcp.json"
    kiro_config.parent.mkdir(parents=True)
    kiro_config.write_text(
        '{"mcpServers":{"other-tool":{"url":"http://127.0.0.1:7777/mcp"}}}',
        encoding="utf-8",
    )
    confirmations = [
        "confirm_user_requested_auto_connect",
        "confirm_backup_before_platform_config_write",
        "confirm_receipt_after_each_platform_write",
        "confirm_capability_check_only_after_connect",
        "confirm_no_chat_body_parser_without_separate_authorization",
    ]

    result = registry_module.apply_authorized_auto_connect(
        {"system": "kiro", "confirmations": confirmations},
        home=home,
        env={},
        memcore_root=memcore_root,
    )

    saved = json.loads(kiro_config.read_text(encoding="utf-8"))
    server = saved["mcpServers"]["yifanchen-zhiyi"]

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert result["platform_write_performed"] is True
    assert result["memory_write_performed"] is False
    assert server == {"type": "http", "url": "http://127.0.0.1:9851/mcp"}
    assert result["receipt"]["display_name"] == "Kiro"
    assert Path(result["backup_path"]).exists()
    assert Path(result["receipt_path"]).exists()


def test_authorized_auto_connect_apply_records_already_connected_claude_code(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    claude_json = home / ".claude.json"
    home.mkdir(parents=True)
    claude_json.write_text(
        json.dumps({
            "mcpServers": {
                "yifanchen-zhiyi": {
                    "type": "http",
                    "url": "http://127.0.0.1:9851/mcp",
                },
            },
        }),
        encoding="utf-8",
    )
    confirmations = [
        "confirm_user_requested_auto_connect",
        "confirm_backup_before_platform_config_write",
        "confirm_receipt_after_each_platform_write",
        "confirm_capability_check_only_after_connect",
        "confirm_no_chat_body_parser_without_separate_authorization",
    ]

    result = registry_module.apply_authorized_auto_connect(
        {"system": "claude_code_cli", "confirmations": confirmations},
        home=home,
        env={},
        memcore_root=tmp_path / "memcore",
    )

    assert result["ok"] is True
    assert result["status"] == "already_connected"
    assert result["platform_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert result["target_path"] == str(claude_json)
    assert Path(result["receipt_path"]).exists()
