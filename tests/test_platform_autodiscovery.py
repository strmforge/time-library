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


RAW_ARCHIVE_SEGMENT_ORDER = [
    "computer_name",
    "source_system",
    "native_artifact_format",
]


def _assert_adapter_draft_plan_shape(plan, *, system):
    assert plan["plan_source"] == "adapter_draft"
    assert plan["adapter_draft_consumed"] is True
    assert plan["adapter_draft"]["contract"] == "local_ai_tool_adapter_draft.v1"
    assert plan["next_actions"] == plan["adapter_draft"]["next_actions"]
    assert plan["mcp_plan"]["plan_source"] == "adapter_draft"
    assert plan["mcp_plan"]["would_write"] == plan["would_write"]
    assert plan["mcp_plan"]["capability_check_payload"]["mode"] == "capability_check"
    assert plan["collector_plan"]["plan_source"] == "adapter_draft"
    assert plan["collector_plan"]["content_read"] is False
    assert plan["collector_plan"]["chat_body_included"] is False
    assert plan["collector_plan"]["raw_excerpt_included"] is False
    assert plan["raw_archive_plan"]["plan_source"] == "adapter_draft"
    assert plan["raw_archive_plan"]["layout"] == "computer_first"
    assert plan["raw_archive_plan"]["effective_from_version"] == "2026.6.1"
    assert plan["raw_archive_plan"]["segment_order"] == RAW_ARCHIVE_SEGMENT_ORDER
    assert plan["raw_archive_plan"]["source_system"] == system
    assert plan["raw_archive_plan"]["legacy_layout_allowed_for_new_writes"] is False


def _assert_adapter_draft_receipt_shape(receipt, *, system):
    assert receipt["plan_source"] == "adapter_draft"
    assert receipt["adapter_draft_consumed"] is True
    assert receipt["adapter_draft_id"]
    assert receipt["mcp_plan"]["plan_source"] == "adapter_draft"
    assert receipt["mcp_plan"]["capability_check_payload"]["mode"] == "capability_check"
    assert receipt["collector_plan"]["plan_source"] == "adapter_draft"
    assert receipt["collector_plan"]["content_read"] is False
    assert receipt["collector_plan"]["chat_body_included"] is False
    assert receipt["collector_plan"]["raw_excerpt_included"] is False
    assert receipt["raw_archive_plan"]["plan_source"] == "adapter_draft"
    assert receipt["raw_archive_plan"]["layout"] == "computer_first"
    assert receipt["raw_archive_plan"]["segment_order"] == RAW_ARCHIVE_SEGMENT_ORDER
    assert receipt["raw_archive_plan"]["source_system"] == system
    assert receipt["raw_archive_plan"]["legacy_layout_allowed_for_new_writes"] is False


def _write_official_codex_native_host(home, codex_home, fake_cli):
    native_host = codex_home / "chrome-native-hosts-v2.json"
    native_host.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "entries": [
                    {
                        "schemaVersion": 2,
                        "appVersion": "26.601.21317",
                        "cliVersion": "26.601.21317",
                        "nativeHostVersion": "26.601.21317",
                        "extensionIds": ["hehggadaopoacecdllhhajmbjkdcmajg"],
                        "nativeHostNames": ["com.openai.codexextension"],
                        "paths": {
                            "codexCliPath": str(fake_cli),
                            "codexHome": str(codex_home),
                            "nodeReplPath": str(fake_cli.parent / "node_repl.exe"),
                            "resourcesPath": str(home / "WindowsApps" / "OpenAI.Codex" / "app" / "resources"),
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return native_host


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
            "read_boundary": {"content_parser_gate": "verified_format_collector_required"},
        },
    }

    result = autodiscovery.build_autodiscovery(profile)
    claude = next(item for item in result["systems"] if item["system"] == "claude_desktop")

    assert result["name"] == "Time Library"
    assert result["codename"] == "Time Library"
    assert result["read_only"] is True
    assert result["platform_write_performed"] is False
    assert result["architecture"]["adapter_strategy"] == "tiandao_plus_thin_adapters"
    assert result["architecture"]["adapter_registry"] == "platform_thin_adapter_registry"
    assert "cursor" in result["known_adapter_targets"]
    assert "claude_code_cli" in result["known_adapter_targets"]
    assert result["thin_adapter_registry"]["read_only"] is True
    assert result["thin_adapter_registry"]["platform_write_performed"] is False
    assert result["connection_contract"]["default_connection_mode"] == "auto_discover_and_auto_connect"
    assert result["connection_contract"]["skill_installation_is_connection_signal"] is True
    assert result["connection_contract"]["conversation_import_mode"] == "verified_format_collectors"
    assert claude["thin_adapter"] is True
    assert claude["intent_signal_detected"] is True
    assert claude["connectable_now"] is False
    assert claude["content_gate"] == "verified_format_collector_required"
    assert any(action["action"] == "auto_connect_missing_thin_adapter" for action in claude["actions"])
    assert any(action["action"] == "verified_format_collector" and action["status"] == "collector_required" for action in claude["actions"])


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
    assert plan["apply_endpoint_status"] == "implemented_by_platform_auto_connect_endpoints"
    assert plan["required_confirmations"] == list(autodiscovery.APPLY_GATE_CONFIRMATIONS)
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
    assert cursor_plan["chat_body_parser_requires_verified_collector"] is True
    assert any(action["action"] == "capability_check" and action["status"] == "ready" for action in cursor_plan["actions"])
    assert cursor_plan["signals"][0]["redacted_mcp_servers"]["memcore-cloud"]["apiKey"] == "<redacted>"
    assert claude_code_plan["detected"] is True
    assert claude_code_plan["current_focus"] is True
    assert claude_code_plan["support_level"] == "adapter_candidate_separate_claude_surface"
    assert any(action["action"] == "auto_connect" for action in claude_code_plan["actions"])


def test_platform_catalog_loads_curated_and_github_watchlist_entries():
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")

    catalog = registry_module.load_platform_catalog()
    ids = {item["id"] for item in catalog["entries"]}

    assert catalog["contract"] == "platform_catalog.v1"
    assert catalog["read_only"] is True
    assert catalog["platform_write_performed"] is False
    assert catalog["curated_entry_count"] >= 12
    assert catalog["github_watchlist_entry_count"] >= 99
    assert catalog["entry_count"] >= 99
    assert "gemini_cli" in ids
    assert "windsurf" in ids
    assert "vscode_copilot" in ids
    assert any(item.get("catalog_level") == "github_top100_watchlist" for item in catalog["entries"])
    assert all(item.get("source_urls") for item in catalog["entries"][:12])


def test_verified_storage_patterns_keep_official_codex_native_paths():
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")

    storage = registry_module.load_platform_storage_patterns()
    machines = {item["computer_name"]: item for item in storage["observed_machines"]}
    codex_patterns = storage["entries"]["codex"]["verified_storage_patterns"]
    pattern_paths = {
        path
        for item in codex_patterns
        for path in item.get("paths", [])
    }
    state_patterns = {
        (item.get("os"), item.get("artifact_format")): item
        for item in codex_patterns
        if item.get("artifact_format") == "codex_state_threads_sqlite"
    }
    session_patterns = {
        (item.get("os"), item.get("artifact_format")): item
        for item in codex_patterns
        if item.get("artifact_format") == "codex_session_jsonl"
    }

    assert storage["schema_version"] == "platform_storage_patterns.v2026.6.20"
    assert storage["product_policy"]["archive_layout_order"] == RAW_ARCHIVE_SEGMENT_ORDER
    assert "windows-codex-fixture" in machines
    assert "macos-codex-fixture" in machines
    assert machines["windows-codex-fixture"]["os"] == "windows"
    assert machines["macos-codex-fixture"]["os"] == "macos"
    assert "%USERPROFILE%/.codex/state_5.sqlite" in pattern_paths
    assert "~/.codex/state_5.sqlite" in pattern_paths
    assert "%USERPROFILE%/.codex/chrome-native-hosts-v2.json" in pattern_paths
    assert "%LOCALAPPDATA%/OpenAI/Codex/chrome-native-hosts-v2.json" in pattern_paths
    assert "~/.codex/chrome-native-hosts-v2.json" in pattern_paths
    assert "~/Library/Application Support/OpenAI/Codex/chrome-native-hosts-v2.json" in pattern_paths
    assert "~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.openai.codexextension.json" in pattern_paths
    assert state_patterns[("windows", "codex_state_threads_sqlite")]["complete_conversation_candidate"] is False
    assert state_patterns[("macos", "codex_state_threads_sqlite")]["assistant_replies_may_persist"] is False
    assert session_patterns[("windows", "codex_session_jsonl")]["complete_conversation_candidate"] is True
    assert session_patterns[("macos", "codex_session_jsonl")]["assistant_replies_may_persist"] is True


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
    inventory = registry_module.build_package_manager_agent_inventory(home=home, env=env, scan_mode="full")
    matches = {(item["system"], item["manager"]) for item in inventory["matches"]}

    assert inventory["contract"] == "package_manager_agent_inventory.v1"
    assert inventory["read_only"] is True
    assert inventory["platform_write_performed"] is False
    assert inventory["global_guarantees"]["does_not_install_packages"] is True
    assert ("opencode", "npm_global") in matches
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
            scan_mode="full",
        )
        dashboard = registry_module.build_platform_discovery_dashboard(
            {},
            home=home,
            env={"LOCALAPPDATA": str(home / "AppData" / "Local")},
        )

    matches = {(item["system"], item["manager"]) for item in inventory["matches"]}
    assert inventory["scan_mode"] == "full"
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
    assert any(action["action"] == "auto_connect" for action in continue_plan["actions"])


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
    assert dashboard_cursor["version"] == "1.2.3"
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
    assert result["global_guarantees"]["backup_and_receipt_on_apply"] is True
    assert result["global_guarantees"]["conversation_import_mode"] == "verified_format_collectors"
    assert plan["system"] == "cursor"
    assert plan["status"] == "auto_connect_ready"
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
    _assert_adapter_draft_plan_shape(plan, system="cursor")


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
    assert plan["chat_body_parser_requires_verified_collector"] is True
    _assert_adapter_draft_plan_shape(plan, system="cursor")


def test_generic_local_ai_surface_scan_detects_kiro_mcp_without_hardcoded_adapter(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    kiro_settings = home / ".kiro" / "settings"
    kiro_settings.mkdir(parents=True)
    (kiro_settings / "mcp.json").write_text(
        '{"mcpServers":{"time-library":{"url":"http://127.0.0.1:9851/mcp","apiKey":"SECRET"}}}',
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
    mcp_signal = next(signal for signal in surfaces["kiro"]["signals"] if "redacted_mcp_servers" in signal)
    assert mcp_signal["redacted_mcp_servers"]["time-library"]["apiKey"] == "<redacted>"

    registry = registry_module.build_thin_adapter_registry({}, home=home, env={})
    generic_registry = {item["system"]: item for item in registry["generic_surface_discovery"]["surfaces"]}
    assert "kiro" in generic_registry


def test_generic_unknown_surface_uses_rule_fallback_when_model_is_not_configured(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    unknown_sessions = home / ".mystery-agent" / "sessions"
    unknown_sessions.mkdir(parents=True)
    (unknown_sessions / "conversation.json").write_text(
        '{"user":"do not include this chat body","assistant":"also private"}',
        encoding="utf-8",
    )

    generic = registry_module.build_generic_local_ai_surfaces(home=home, env={"MEMCORE_ROOT": str(tmp_path / "memcore")})
    surfaces = {item["system"]: item for item in generic["surfaces"]}
    identification = surfaces["mystery_agent"]["model_identification"]

    assert generic["model_identification"]["contract"] == "local_ai_tool_model_identification.v1"
    assert generic["model_identification"]["fallback_rules_surface_count"] >= 1
    assert identification["enabled"] is False
    assert identification["mode"] == "fallback_rules"
    assert identification["reason"] == "model_not_configured"
    assert identification["input_kind"] == "local_metadata_only"
    assert identification["chat_body_included"] is False
    assert identification["raw_excerpt_included"] is False
    assert "request_envelope" not in identification


def test_generic_unknown_surface_builds_model_identification_envelope_when_model_is_configured(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    unknown_sessions = home / ".mystery-agent" / "sessions"
    unknown_sessions.mkdir(parents=True)
    (unknown_sessions / "conversation.json").write_text(
        '{"user":"do not include this chat body","assistant":"also private"}',
        encoding="utf-8",
    )

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={
            "MEMCORE_ROOT": str(tmp_path / "memcore"),
            "MEMCORE_MODEL_IDENTIFICATION_PROVIDER": "minimax-cn",
            "MEMCORE_MODEL_IDENTIFICATION_MODEL": "MiniMax-M2.7",
        },
    )
    surfaces = {item["system"]: item for item in generic["surfaces"]}
    identification = surfaces["mystery_agent"]["model_identification"]
    envelope = identification["request_envelope"]
    serialized_envelope = json.dumps(envelope, ensure_ascii=False)

    assert generic["model_identification"]["configured_model_available"] is True
    assert generic["model_identification"]["configured_model_surface_count"] >= 1
    assert identification["enabled"] is True
    assert identification["mode"] == "configured_model"
    assert identification["configured_model"]["provider_id"] == "minimax-cn"
    assert identification["configured_model"]["model_name"] == "MiniMax-M2.7"
    assert envelope["request_kind"] == "local_ai_tool_identification"
    assert envelope["request_sent"] is False
    assert envelope["model_call_performed"] is False
    assert identification["local_metadata"]["chat_body_included"] is False
    assert identification["local_metadata"]["identity_hints"]["surface_id"] == "mystery_agent"
    assert "mystery_agent" in identification["local_metadata"]["identity_hints"]["visible_identifier_variants"]
    assert "mystery-agent" in serialized_envelope
    assert "do not include this chat body" not in serialized_envelope
    assert "also private" not in serialized_envelope


def test_model_identification_prompt_prefers_visible_identity_and_normalizes_confidence(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    unknown_sessions = home / ".trae-agent" / "sessions"
    unknown_sessions.mkdir(parents=True)
    (unknown_sessions / "conversation.json").write_text(
        '{"user":"private user body","assistant":"private assistant body"}',
        encoding="utf-8",
    )
    command = tmp_path / "identify.py"
    command.write_text(
        "import json, sys\n"
        "payload = json.load(sys.stdin)\n"
        "messages = payload['request_envelope']['messages']\n"
        "body = messages[-1]['content']\n"
        "assert 'private user body' not in body\n"
        "assert 'private assistant body' not in body\n"
        "assert 'identity_hints' in body\n"
        "print(json.dumps({\n"
        "  'likely_name': 'Trae Agent',\n"
        "  'category': 'agent_cli',\n"
        "  'supports_mcp_likely': True,\n"
        "  'skill_surface_likely': False,\n"
        "  'storage_candidate': '.trae-agent/sessions',\n"
        "  'confidence': 'high',\n"
        "  'reason': 'recognized from visible path identity'\n"
        "}))\n",
        encoding="utf-8",
    )

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={
            "MEMCORE_ROOT": str(tmp_path / "memcore"),
            "MEMCORE_ZHIYI_PROVIDER": "test-provider",
            "MEMCORE_ZHIYI_MODEL": "test-model",
            "MEMCORE_ZHIYI_MODEL_COMMAND": f"{sys.executable} {command}",
        },
        execute_model_identification=True,
    )
    identification = {item["system"]: item for item in generic["surfaces"]}["trae_agent"]["model_identification"]
    candidate = {item["system"]: item for item in generic["surfaces"]}["trae_agent"]["provisional_adapter_candidate"]

    assert identification["result"]["status"] == "identified_by_model"
    assert identification["result"]["likely_name"] == "Trae Agent"
    assert identification["result"]["confidence"] == 0.85
    assert candidate["confidence"] == 0.85
    assert candidate["display_name"] == "Trae Agent"


def test_model_identification_repairs_unknown_model_name_with_visible_identity(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    unknown_sessions = home / ".trae-agent" / "sessions"
    unknown_sessions.mkdir(parents=True)
    (unknown_sessions / "conversation.json").write_text(
        '{"user":"private user body","assistant":"private assistant body"}',
        encoding="utf-8",
    )
    command = tmp_path / "identify.py"
    command.write_text(
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({\n"
        "  'likely_name': 'Unknown local AI tool',\n"
        "  'category': 'unknown',\n"
        "  'supports_mcp_likely': True,\n"
        "  'skill_surface_likely': False,\n"
        "  'storage_candidate': '.trae-agent/sessions',\n"
        "  'confidence': 'very high',\n"
        "  'reason': 'model was too cautious'\n"
        "}))\n",
        encoding="utf-8",
    )

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={
            "MEMCORE_ROOT": str(tmp_path / "memcore"),
            "MEMCORE_ZHIYI_PROVIDER": "test-provider",
            "MEMCORE_ZHIYI_MODEL": "test-model",
            "MEMCORE_ZHIYI_MODEL_COMMAND": f"{sys.executable} {command}",
        },
        execute_model_identification=True,
    )
    identification = {item["system"]: item for item in generic["surfaces"]}["trae_agent"]["model_identification"]
    candidate = {item["system"]: item for item in generic["surfaces"]}["trae_agent"]["provisional_adapter_candidate"]

    assert identification["result"]["likely_name"] == "Trae Agent"
    assert identification["result"]["visible_identity_fallback_applied"] is True
    assert identification["result"]["category"] == "agent_config_surface"
    assert identification["result"]["confidence"] == 0.78
    assert candidate["display_name"] == "Trae Agent"
    assert candidate["confidence"] == 0.78


def test_model_identification_report_defaults_to_smart_scan_without_empty_snapshot(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    (home / ".mystery-agent" / "sessions").mkdir(parents=True)

    report = registry_module.build_model_identification_report(
        home=home,
        env={"MEMCORE_ROOT": str(tmp_path / "memcore")},
    )
    fast = registry_module.build_model_identification_report(
        home=home,
        env={"MEMCORE_ROOT": str(tmp_path / "memcore")},
        include_generic=False,
    )

    assert report["scan_mode"] == "smart"
    assert report["summary"]["surface_count"] >= 1
    assert any(item["system"] == "mystery_agent" for item in report["items"])
    assert fast["scan_mode"] == "fast_snapshot"
    assert fast["summary"]["surface_count"] == 0


def test_deep_scan_keeps_nested_project_artifact_discovery_explicit(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    kiro_specs = home / "Desktop" / "workspaceStorage" / "Project" / ".kiro" / "specs"
    kiro_specs.mkdir(parents=True)
    (kiro_specs / "requirements.md").write_text("# requirements", encoding="utf-8")

    smart = registry_module.build_model_identification_report(
        home=home,
        env={"MEMCORE_ROOT": str(tmp_path / "memcore")},
    )
    deep = registry_module.build_model_identification_report(
        home=home,
        env={"MEMCORE_ROOT": str(tmp_path / "memcore")},
        scan_mode="deep",
    )

    smart_systems = {item["system"] for item in smart["items"]}
    deep_systems = {item["system"] for item in deep["items"]}

    assert smart["scan_mode"] == "smart"
    assert "kiro" not in smart_systems
    assert deep["scan_mode"] == "deep"
    assert "kiro" in deep_systems


def test_model_identification_uses_user_binding_before_configured_model(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    memcore_root = tmp_path / "memcore"
    config_dir = memcore_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "zhiyi_model_binding.user.json").write_text(
        json.dumps({
            "provider": "user-provider",
            "provider_id": "user-provider-id",
            "model_name": "user-model",
            "transport": "openai_compatible_http",
            "base_url": "https://user.example.test/v1",
            "api_key_env": "USER_MODEL_KEY",
        }),
        encoding="utf-8",
    )
    (config_dir / "model_config.json").write_text(
        json.dumps({
            "local_tool_identification": {
                "provider": "config-provider",
                "model_name": "config-model",
            },
        }),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    (home / ".mystery-agent" / "sessions").mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={"MEMCORE_ROOT": str(memcore_root)},
    )
    identification = {item["system"]: item for item in generic["surfaces"]}["mystery_agent"]["model_identification"]
    chain = identification["configured_model"]["provider_chain"]

    assert identification["configured_model"]["source"] == "zhiyi_model_binding.user.json"
    assert identification["configured_model"]["provider"] == "user-provider"
    assert identification["configured_model"]["model_name"] == "user-model"
    assert identification["request_envelope"]["base_url"] == "https://user.example.test/v1"
    assert identification["request_envelope"]["api_key_env"] == "USER_MODEL_KEY"
    assert chain[-1]["source"] == "zhiyi_model_binding.user.json"
    assert all(item["source"] != "model_config.local_tool_identification" for item in chain)


def test_model_identification_uses_memcore_config_before_tiandao_center(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    memcore_root = tmp_path / "memcore"
    config_dir = memcore_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "model_config.json").write_text(
        json.dumps({
            "local_tool_identification": {
                "provider": "memcore-provider",
                "provider_id": "memcore-provider-id",
                "model_name": "memcore-model",
                "base_url": "https://memcore.example.test/v1",
                "api_key_env": "MEMCORE_PROVIDER_KEY",
            },
            "tiandao_model_center": {
                "selected_model": "deepseek-chat",
                "endpoints": [{
                    "id": "ep-tiandao",
                    "name": "Tiandao Shared",
                    "providerName": "deepseek",
                    "providerType": "openai",
                    "baseUrl": "https://tiandao.example.test/v1",
                    "platform": "openclaw",
                }],
                "models": [{
                    "id": "ep-tiandao/deepseek-chat",
                    "endpointId": "ep-tiandao",
                    "modelName": "deepseek-chat",
                    "capabilities": ["chat"],
                }],
            },
        }),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    (home / ".mystery-agent" / "sessions").mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={"MEMCORE_ROOT": str(memcore_root)},
    )
    identification = {item["system"]: item for item in generic["surfaces"]}["mystery_agent"]["model_identification"]
    chain = identification["configured_model"]["provider_chain"]

    assert identification["configured_model"]["source"] == "model_config.local_tool_identification"
    assert identification["configured_model"]["provider"] == "memcore-provider"
    assert identification["configured_model"]["model_name"] == "memcore-model"
    assert identification["request_envelope"]["base_url"] == "https://memcore.example.test/v1"
    assert identification["request_envelope"]["api_key_env"] == "MEMCORE_PROVIDER_KEY"
    assert all(item["role"] != "shared_tiandao_identity" for item in chain)


def test_model_identification_prefers_unified_zhiyi_model_config(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    memcore_root = tmp_path / "memcore"
    config_dir = memcore_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "model_config.json").write_text(
        json.dumps({
            "zhiyi_model": {
                "provider": "zhiyi-provider",
                "provider_id": "zhiyi-provider-id",
                "model_name": "zhiyi-model",
                "base_url": "https://zhiyi.example.test/v1",
                "api_key_env": "MEMCORE_ZHIYI_API_KEY",
            },
            "local_tool_identification": {
                "provider": "legacy-provider",
                "provider_id": "legacy-provider-id",
                "model_name": "legacy-model",
                "base_url": "https://legacy.example.test/v1",
                "api_key_env": "LEGACY_MODEL_KEY",
            },
        }),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    (home / ".mystery-agent" / "sessions").mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={"MEMCORE_ROOT": str(memcore_root)},
    )
    identification = {item["system"]: item for item in generic["surfaces"]}["mystery_agent"]["model_identification"]
    chain = identification["configured_model"]["provider_chain"]

    assert identification["configured_model"]["source"] == "model_config.zhiyi_model"
    assert identification["configured_model"]["provider"] == "zhiyi-provider"
    assert identification["configured_model"]["model_name"] == "zhiyi-model"
    assert identification["request_envelope"]["base_url"] == "https://zhiyi.example.test/v1"
    assert identification["request_envelope"]["api_key_env"] == "MEMCORE_ZHIYI_API_KEY"
    assert all(item["source"] != "model_config.local_tool_identification" for item in chain)


def test_model_identification_env_uses_unified_zhiyi_names(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    (home / ".mystery-agent" / "sessions").mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={
            "MEMCORE_ROOT": str(tmp_path / "memcore"),
            "MEMCORE_ZHIYI_PROVIDER": "DeepSeek",
            "MEMCORE_ZHIYI_MODEL": "deepseek-chat",
            "MEMCORE_ZHIYI_BASE_URL": "https://api.deepseek.com/v1",
        },
    )
    identification = {item["system"]: item for item in generic["surfaces"]}["mystery_agent"]["model_identification"]
    envelope = identification["request_envelope"]

    assert identification["configured_model"]["source"] == "env"
    assert identification["configured_model"]["provider"] == "DeepSeek"
    assert identification["configured_model"]["model_name"] == "deepseek-chat"
    assert envelope["base_url"] == "https://api.deepseek.com/v1"
    assert envelope["api_key_env"] == "MEMCORE_ZHIYI_API_KEY"


def test_model_identification_can_use_tiandao_model_identity(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    memcore_root = tmp_path / "memcore"
    config_dir = memcore_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "model_config.json").write_text(
        json.dumps({
            "tiandao_model_center": {
                "selected_model": "deepseek-chat",
                "api_key_env": "TIANDAO_MODEL_KEY",
                "endpoints": [{
                    "id": "ep-tiandao",
                    "name": "Tiandao Shared",
                    "providerName": "deepseek",
                    "providerType": "openai",
                    "baseUrl": "https://tiandao.example.test/v1",
                    "platform": "openclaw",
                }],
                "models": [{
                    "id": "ep-tiandao/deepseek-chat",
                    "endpointId": "ep-tiandao",
                    "modelName": "deepseek-chat",
                    "capabilities": ["chat"],
                }],
            },
        }),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    (home / ".mystery-agent" / "sessions").mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={"MEMCORE_ROOT": str(memcore_root)},
    )
    identification = {item["system"]: item for item in generic["surfaces"]}["mystery_agent"]["model_identification"]
    configured = identification["configured_model"]
    envelope = identification["request_envelope"]
    chain = configured["provider_chain"]

    assert configured["source"] == "model_config.tiandao_model_center"
    assert configured["provider"] == "deepseek"
    assert configured["provider_id"] == "ep-tiandao"
    assert configured["model_name"] == "deepseek/deepseek-chat"
    assert configured["transport"] == "openai_compatible_http"
    assert configured["independent"] is True
    assert chain[-1]["role"] == "shared_tiandao_identity"
    assert chain[-1]["independent"] is True
    assert envelope["base_url"] == "https://tiandao.example.test/v1"
    assert envelope["api_key_env"] == "TIANDAO_MODEL_KEY"
    assert envelope["provider_chain"][-1]["source"] == "model_config.tiandao_model_center"


def test_model_identification_keeps_openclaw_and_hermes_as_inherited_options(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    memcore_root = tmp_path / "memcore"
    config_dir = memcore_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "model_config.json").write_text(
        json.dumps({
            "recall": {
                "openclaw_model": {
                    "selected_provider": "minimax-cn",
                    "selected_model": "MiniMax-M2.7",
                    "base_url": "https://api.minimaxi.com/v1",
                    "api_key_env": "MINIMAX_CN_API_KEY",
                },
                "hermes_model": {
                    "selected_provider": "deepseek",
                    "selected_model": "deepseek-chat",
                },
            },
        }),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    (home / ".mystery-agent" / "sessions").mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={"MEMCORE_ROOT": str(memcore_root)},
    )
    identification = {item["system"]: item for item in generic["surfaces"]}["mystery_agent"]["model_identification"]
    configured = identification["configured_model"]
    envelope = identification["request_envelope"]
    chain = configured["provider_chain"]

    assert configured["source"] == "model_config.openclaw_model"
    assert configured["provider"] == "OpenClaw"
    assert configured["provider_id"] == "minimax-cn"
    assert configured["model_name"] == "MiniMax-M2.7"
    assert configured["transport"] == "inherited_openclaw_model"
    assert configured["independent"] is False
    assert chain[-1]["role"] == "optional_inherited"
    assert envelope["independent_provider"] is False
    assert envelope["base_url"] == "https://api.minimaxi.com/v1"
    assert envelope["api_key_env"] == "MINIMAX_CN_API_KEY"


def test_generic_unknown_surface_can_execute_model_identification_with_local_command(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    unknown_sessions = home / ".mystery-agent" / "sessions"
    unknown_sessions.mkdir(parents=True)
    (unknown_sessions / "conversation.json").write_text(
        '{"user":"private user text","assistant":"private assistant text"}',
        encoding="utf-8",
    )
    command = tmp_path / "identify.py"
    command.write_text(
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({\n"
        "  'likely_name': 'Mystery Agent',\n"
        "  'category': 'agent_app',\n"
        "  'supports_mcp_likely': True,\n"
        "  'skill_surface_likely': False,\n"
        "  'storage_candidate': '.mystery-agent/sessions',\n"
        "  'confidence': 0.91,\n"
        "  'reason': 'recognized from local metadata'\n"
        "}))\n",
        encoding="utf-8",
    )

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={
            "MEMCORE_ROOT": str(tmp_path / "memcore"),
            "MEMCORE_MODEL_IDENTIFICATION_PROVIDER": "test-provider",
            "MEMCORE_MODEL_IDENTIFICATION_MODEL": "test-model",
            "MEMCORE_MODEL_IDENTIFICATION_COMMAND": f"{sys.executable} {command}",
        },
        execute_model_identification=True,
    )
    surfaces = {item["system"]: item for item in generic["surfaces"]}
    identification = surfaces["mystery_agent"]["model_identification"]
    candidate = surfaces["mystery_agent"]["provisional_adapter_candidate"]
    serialized_identification = json.dumps(identification, ensure_ascii=False)

    assert generic["model_identification"]["executed_model_surface_count"] >= 1
    assert identification["mode"] == "configured_model"
    assert identification["executor"] == "local_command"
    assert identification["model_call_performed"] is True
    assert identification["request_envelope"]["request_sent"] is True
    assert identification["request_envelope"]["response_received"] is True
    assert identification["result"]["status"] == "identified_by_model"
    assert identification["result"]["likely_name"] == "Mystery Agent"
    assert identification["result"]["confidence"] == 0.91
    assert candidate["contract"] == "provisional_adapter_candidates.v1"
    assert candidate["candidate_type"] == "provisional_adapter_candidate"
    assert candidate["display_name"] == "Mystery Agent"
    assert candidate["recognized_by"] == "model"
    assert candidate["confidence"] == 0.91
    assert candidate["connection"]["supports_mcp_likely"] is True
    assert candidate["adapter_draft"]["contract"] == "local_ai_tool_adapter_draft.v1"
    assert candidate["adapter_draft"]["recognition"]["recognized_by"] == "model"
    assert candidate["adapter_draft"]["mcp"]["supports_mcp_likely"] is True
    assert candidate["adapter_draft"]["collector"]["collector_status"] == "verified_collector_required"
    assert candidate["adapter_draft"]["collector"]["native_artifact_format"] == "mystery_agent_native_store"
    assert candidate["adapter_draft"]["collector"]["content_read"] is False
    assert candidate["adapter_draft"]["collector"]["chat_body_included"] is False
    assert candidate["adapter_draft"]["raw_archive"]["layout"] == "computer_first"
    assert candidate["adapter_draft"]["raw_archive"]["segment_order"] == [
        "computer_name",
        "source_system",
        "native_artifact_format",
    ]
    assert candidate["adapter_draft"]["raw_archive"]["source_system"] == "mystery_agent"
    assert candidate["adapter_draft"]["raw_archive"]["legacy_layout_allowed_for_new_writes"] is False
    assert "create_verified_format_collector" in candidate["adapter_draft"]["next_actions"]
    assert candidate["storage"]["content_read"] is False
    assert candidate["storage"]["chat_body_included"] is False
    assert "private user text" not in serialized_identification
    assert "private assistant text" not in serialized_identification

    report = registry_module.build_provisional_adapter_candidates_report(
        home=home,
        env={
            "MEMCORE_ROOT": str(tmp_path / "memcore"),
            "MEMCORE_MODEL_IDENTIFICATION_PROVIDER": "test-provider",
            "MEMCORE_MODEL_IDENTIFICATION_MODEL": "test-model",
            "MEMCORE_MODEL_IDENTIFICATION_COMMAND": f"{sys.executable} {command}",
        },
        include_generic=True,
        execute=True,
    )
    report_candidates = {item["system"]: item for item in report["candidates"]}
    assert report["contract"] == "provisional_adapter_candidates.v1"
    assert report["read_only"] is True
    assert report["platform_write_performed"] is False
    assert report["summary"]["adapter_draft_count"] >= 1
    assert report["summary"]["verified_collectors_needed"] >= 1
    assert report["summary"]["computer_first_archive_ready"] >= 1
    assert report_candidates["mystery_agent"]["display_name"] == "Mystery Agent"
    assert report_candidates["mystery_agent"]["adapter_draft"]["collector"]["content_read"] is False


def test_model_identification_executes_unified_zhiyi_command_and_parses_fenced_json(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    unknown_sessions = home / ".mystery-agent" / "sessions"
    unknown_sessions.mkdir(parents=True)
    command = tmp_path / "identify.py"
    command.write_text(
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print('Here is the JSON:')\n"
        "print('```json')\n"
        "print(json.dumps({\n"
        "  'likely_name': 'Fenced Mystery Agent',\n"
        "  'category': 'agent_cli',\n"
        "  'supports_mcp_likely': False,\n"
        "  'skill_surface_likely': True,\n"
        "  'storage_candidate': '.mystery-agent/sessions',\n"
        "  'confidence': 0.88,\n"
        "  'reason': 'recognized from fenced model JSON'\n"
        "}))\n"
        "print('```')\n",
        encoding="utf-8",
    )

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={
            "MEMCORE_ROOT": str(tmp_path / "memcore"),
            "MEMCORE_ZHIYI_PROVIDER": "test-provider",
            "MEMCORE_ZHIYI_MODEL": "test-model",
            "MEMCORE_ZHIYI_MODEL_COMMAND": f"{sys.executable} {command}",
        },
        execute_model_identification=True,
    )
    identification = {item["system"]: item for item in generic["surfaces"]}["mystery_agent"]["model_identification"]

    assert identification["executor"] == "local_command"
    assert identification["model_call_performed"] is True
    assert identification["result"]["status"] == "identified_by_model"
    assert identification["result"]["likely_name"] == "Fenced Mystery Agent"
    assert identification["result"]["confidence"] == 0.88


def test_model_identification_execute_limit_defers_extra_surfaces(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    for name in (".alpha-agent", ".beta-agent", ".gamma-agent"):
        sessions = home / name / "sessions"
        sessions.mkdir(parents=True)
        (home / name / "mcp.json").write_text(
            '{"mcpServers":{"memcore-cloud":{"url":"http://127.0.0.1:9851/mcp"}}}',
            encoding="utf-8",
        )
    command = tmp_path / "identify.py"
    counter = tmp_path / "counter.txt"
    counter_literal = repr(str(counter))
    command.write_text(
        "import json, os, sys\n"
        "json.load(sys.stdin)\n"
        f"counter = {counter_literal}\n"
        "try:\n"
        "    current = int(open(counter, 'r', encoding='utf-8').read() or '0')\n"
        "except Exception:\n"
        "    current = 0\n"
        "open(counter, 'w', encoding='utf-8').write(str(current + 1))\n"
        "print(json.dumps({\n"
        "  'likely_name': 'Limited Agent',\n"
        "  'category': 'agent_config_surface',\n"
        "  'supports_mcp_likely': True,\n"
        "  'skill_surface_likely': False,\n"
        "  'storage_candidate': '.limited-agent',\n"
        "  'confidence': 0.8,\n"
        "  'reason': 'limited model execution'\n"
        "}))\n",
        encoding="utf-8",
    )

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={
            "MEMCORE_ROOT": str(tmp_path / "memcore"),
            "MEMCORE_ZHIYI_PROVIDER": "test-provider",
            "MEMCORE_ZHIYI_MODEL": "test-model",
            "MEMCORE_ZHIYI_MODEL_COMMAND": f"{sys.executable} {command}",
        },
        execute_model_identification=True,
        model_execute_limit=1,
    )
    identifications = [
        item["model_identification"]
        for item in generic["surfaces"]
        if item["system"] in {"alpha_agent", "beta_agent", "gamma_agent"}
    ]

    assert generic["model_identification"]["execute_limit"] == 1
    assert generic["model_identification"]["executed_model_surface_count"] == 1
    assert generic["model_identification"]["deferred_model_surface_count"] >= 2
    assert counter.read_text(encoding="utf-8") == "1"
    assert sum(1 for item in identifications if item.get("model_call_performed")) == 1
    assert sum(1 for item in identifications if item.get("execution_deferred")) >= 2


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

    assert generic["catalog"]["github_watchlist_entry_count"] >= 99
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
    opencode = surfaces["opencode"]

    assert opencode["catalog_driven"] is True
    assert opencode["catalog_entry"]["catalog_level"] == "curated"
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
    opencode = surfaces["opencode"]

    assert generic["package_manager_inventory"]["match_count"] >= 1
    assert opencode["catalog_entry"]["catalog_level"] == "curated"
    assert str(opencode_pkg) in opencode["installation_paths"]
    assert any(signal["kind"] == "package_manager_install" and signal["manager"] == "npm_global" for signal in opencode["signals"])


def test_current_open_source_agent_wave_is_curated_and_detected_without_body_reads(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    npm_root = tmp_path / "npm" / "lib" / "node_modules"
    for package_name in ("opencode", "@block/goose"):
        package_root = npm_root / package_name
        package_root.mkdir(parents=True)
        (package_root / "package.json").write_text(
            json.dumps({"name": package_name, "version": "1.0.0"}),
            encoding="utf-8",
        )
    pipx_root = tmp_path / "pipx" / "venvs"
    for app_name in ("aider", "openhands"):
        (pipx_root / app_name).mkdir(parents=True)

    (home / ".opencode").mkdir(parents=True)
    (home / ".goose").mkdir(parents=True)
    (home / ".aider").mkdir(parents=True)
    (home / ".openhands").mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={
            "MEMCORE_PACKAGE_SCAN_STRICT_ROOTS": "1",
            "MEMCORE_NPM_GLOBAL_ROOT": str(npm_root),
            "MEMCORE_PIPX_HOME": str(tmp_path / "pipx"),
        },
    )
    surfaces = {item["system"]: item for item in generic["surfaces"]}

    for system, display_name in {
        "opencode": "OpenCode",
        "goose": "Goose",
        "aider": "Aider",
        "openhands": "OpenHands",
    }.items():
        surface = surfaces[system]
        assert surface["display_name"] == display_name
        assert surface["catalog_driven"] is True
        assert surface["catalog_entry"]["catalog_level"] == "curated"
        assert surface["content_read"] is False
        assert surface["conversation_memory_boundary"]["parser_gate"] == "verified_format_collector_required"
        assert surface["provisional_adapter_candidate"]["adapter_draft"]["raw_archive"]["layout"] == "computer_first"

    assert generic["package_manager_inventory"]["match_count"] >= 4
    for system in ("opencode", "goose", "aider", "openhands"):
        assert any(
            signal["kind"] == "package_manager_install"
            for signal in surfaces[system]["signals"]
        )


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
    boundary = kiro["conversation_memory_boundary"]
    assert boundary["conversation_capture_mode"] == "project_artifacts_only_observed"
    assert boundary["complete_conversation_candidate"] is False
    assert boundary["assistant_replies_may_persist"] is False
    assert boundary["assistant_reply_persistence"] == "not_claimed_from_project_specs"
    assert boundary["can_recall_assistant_replies_now"] is False
    assert boundary["content_read"] is False

    plan = registry_module.build_authorized_auto_connect_dry_run({}, home=home, env={}, system="kiro")
    assert plan["plans"][0]["status"] == "auto_connect_ready"
    assert plan["plans"][0]["would_write"] == []
    assert plan["plans"][0]["conversation_memory_boundary"]["conversation_capture_mode"] == "project_artifacts_only_observed"

    dashboard = registry_module.build_platform_discovery_dashboard({}, home=home, env={}, public=False)
    items = {item["system"]: item for item in dashboard["items"]}
    assert items["kiro"]["content_bearing_store_detected"] is True
    assert items["kiro"]["content_store_paths"] == [str(kiro_specs.parent)]
    assert items["kiro"]["conversation_memory_boundary"]["complete_conversation_candidate"] is False


def test_windows_kiro_native_workspace_sessions_mark_complete_candidate_without_content_read(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    roaming = home / "AppData" / "Roaming"
    sessions = (
        roaming
        / "Kiro"
        / "User"
        / "globalStorage"
        / "kiro.kiroagent"
        / "workspace-sessions"
        / "ZzpcbmFudGlhbm1lbg__"
    )
    sessions.mkdir(parents=True)
    (sessions / "session.json").write_text(
        json.dumps({
            "history": [
                {"message": {"role": "user", "content": "hidden user text"}},
                {"message": {"role": "assistant", "content": "hidden assistant text"}},
            ],
        }),
        encoding="utf-8",
    )

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={"APPDATA": str(roaming)},
    )
    surfaces = {item["system"]: item for item in generic["surfaces"]}
    kiro = surfaces["kiro"]
    workspace_sessions = sessions.parent

    assert str(roaming / "Kiro") in kiro["content_store_paths"]
    assert str(workspace_sessions) in kiro["content_store_paths"]
    assert kiro["content_read"] is False
    assert any(
        signal["kind"] == "kiro_native_workspace_sessions"
        and signal["path"] == str(workspace_sessions)
        and signal["content_read"] is False
        and signal["assistant_roles_read"] is False
        for signal in kiro["signals"]
    )
    boundary = kiro["conversation_memory_boundary"]
    assert boundary["conversation_capture_mode"] == "native_workspace_sessions_observed"
    assert boundary["complete_conversation_candidate"] is True
    assert boundary["assistant_replies_may_persist"] is True
    assert boundary["assistant_reply_persistence"] == "observed_in_windows_native_workspace_sessions_format"
    assert boundary["assistant_replies_observed_by_current_scan"] is False
    assert boundary["can_recall_assistant_replies_now"] is False
    assert boundary["content_read"] is False
    assert boundary["parser_gate"] == "verified_format_collector_required"
    draft = kiro["provisional_adapter_candidate"]["adapter_draft"]
    assert draft["contract"] == "local_ai_tool_adapter_draft.v1"
    assert draft["collector"]["collector_status"] == "verified_collector_required"
    assert draft["collector"]["native_artifact_format"] == "kiro_workspace_sessions_json"
    assert draft["collector"]["complete_conversation_candidate"] is True
    assert draft["collector"]["assistant_replies_may_persist"] is True
    assert draft["collector"]["content_read"] is False
    assert draft["raw_archive"]["layout"] == "computer_first"
    assert draft["raw_archive"]["source_system"] == "kiro"
    assert draft["raw_archive"]["native_artifact_format"] == "kiro_workspace_sessions_json"
    assert "verify_assistant_reply_roundtrip" in draft["next_actions"]

    dashboard = registry_module.build_platform_discovery_dashboard(
        {},
        home=home,
        env={"APPDATA": str(roaming)},
        public=False,
    )
    items = {item["system"]: item for item in dashboard["items"]}
    assert items["kiro"]["conversation_memory_boundary"]["conversation_capture_mode"] == "native_workspace_sessions_observed"
    assert items["kiro"]["reads_chat_bodies"] is False

    plan = registry_module.build_authorized_auto_connect_dry_run(
        {},
        home=home,
        env={"APPDATA": str(roaming)},
        system="kiro",
    )
    kiro_plan = plan["plans"][0]
    assert kiro_plan["conversation_memory_boundary"]["complete_conversation_candidate"] is True
    assert kiro_plan["chat_body_parser_requires_verified_collector"] is True
    assert kiro_plan["real_recall_after_connect"] is False
    assert kiro_plan["adapter_draft"]["collector"]["native_artifact_format"] == "kiro_workspace_sessions_json"
    assert kiro_plan["adapter_draft"]["raw_archive"]["layout"] == "computer_first"
    _assert_adapter_draft_plan_shape(kiro_plan, system="kiro")
    assert kiro_plan["collector_plan"]["required_before_real_recall"] is True


def test_windows_local_agent_directory_aliases_become_surfaces(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    local_appdata = home / "AppData" / "Local"
    roaming = home / "AppData" / "Roaming"
    for path in (
        home / ".workbuddy",
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

    assert "workbuddy" in surfaces
    assert "clawui" in surfaces
    assert "codebuddy" in surfaces
    assert "codex" in surfaces
    assert "vscode_copilot" in surfaces
    assert "minimax_agent" in surfaces
    assert surfaces["workbuddy"]["display_name"] == "Workbuddy"
    assert surfaces["codebuddy"]["display_name"] == "CodeBuddy"
    assert surfaces["minimax_agent"]["display_name"] == "MiniMax Agent"
    assert str(home / ".workbuddy") in surfaces["workbuddy"]["workspace_paths"]
    assert str(home / ".codebuddycn") in surfaces["codebuddy"]["workspace_paths"]
    assert str(roaming / "Codex++") in surfaces["codex"]["workspace_paths"]
    assert "ima_copilot" in surfaces
    assert str(local_appdata / "ima.copilot") in surfaces["ima_copilot"]["content_store_paths"]
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
        home / ".exampletool-backups",
        appdata_local / "Temp" / "WorkBuddy-3.16.0-updater-fnwUHX",
        appdata_local / "Temp" / "deepseek_rlm_ctx",
        appdata_local / "Temp" / "DeepSeek-Reasonix-main-v2-readonly",
        appdata_local / "Temp" / "agentskills-r59",
        appdata_roaming / "Kiro",
        home / ".codebuddy",
        home / ".workbuddy",
    ):
        path.mkdir(parents=True)

    generic = registry_module.build_generic_local_ai_surfaces(
        home=home,
        env={"LOCALAPPDATA": str(appdata_local), "APPDATA": str(appdata_roaming)},
    )
    surfaces = {item["system"]: item for item in generic["surfaces"]}

    assert "kiro" in surfaces
    assert "codebuddy" in surfaces
    assert "workbuddy" in surfaces
    assert "openclaw_bak" not in surfaces
    assert "exampletool_backups" not in surfaces
    assert "deepseek_rlm_ctx" not in surfaces
    assert "deepseek_reasonix_main_v2_readonly" not in surfaces
    assert "workbuddy" in surfaces
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
    assert plan["status"] == "auto_connect_ready"
    assert str(kiro_settings / "mcp.json") in plan["would_write"]
    _assert_adapter_draft_plan_shape(plan, system="kiro")


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
    assert plan["status"] == "auto_connect_ready"
    assert str(kiro_settings / "mcp.json") in plan["would_write"]
    assert plan["backup_required"] is True
    assert plan["apply_endpoint_status"] == "implemented_for_json_mcp_surfaces"
    _assert_adapter_draft_plan_shape(plan, system="kiro")


def test_platform_discovery_dashboard_merges_known_and_generic_surfaces(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True)
    (codex_home / "config.toml").write_text(
        '[mcp_servers.time-library]\nurl = "http://127.0.0.1:9851/mcp"\n',
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
    assert dashboard["view"] == "public"
    assert dashboard["name"] == "Time Library"
    assert dashboard["read_only"] is True
    assert dashboard["dashboard_goal"] == "show_local_ai_tools_with_auto_connect_status"
    assert dashboard["platform_write_performed"] is False
    assert dashboard["memory_write_performed"] is False
    assert dashboard["public_summary"]["local_ai_tools"] == dashboard["counts"]["total"]
    assert dashboard["public_summary"]["ready_for_safe_check"] == dashboard["counts"]["ready_for_capability_check"]
    assert dashboard["public_summary"]["auto_connect_ready"] == dashboard["counts"]["auto_connect_ready"]
    assert dashboard["global_guarantees"]["conversation_import_mode"] == "verified_format_collectors"
    assert dashboard["global_guarantees"]["auto_connect_supported_skill_mcp_surfaces"] is True
    assert items["codex"]["tool_type"] == "recognized_tool"
    assert items["codex"]["status"] == "ready_for_capability_check"
    assert items["codex"]["safe_next_step"] == "run_capability_check"
    assert items["codex"]["capability_check_payload"]["mode"] == "capability_check"
    assert items["kiro"]["tool_type"] == "local_tool"
    assert items["kiro"]["status"] == "auto_connect_ready"
    assert items["kiro"]["safe_next_step"] == "auto_connect"
    assert "authorized_connect_plan_endpoint" not in items["kiro"]
    assert all(item["writes_now"] is False for item in dashboard["items"])
    assert all(item["reads_chat_bodies"] is False for item in dashboard["items"])

    serialized_public = json.dumps(dashboard, ensure_ascii=False)
    for hidden_term in [
        "github_watchlist",
        "platform_catalog",
        "thin_adapter",
        "catalog_watchlist",
        "generic_local_ai_surface",
        "known_thin_adapter",
        "support_level",
        "surface_type",
        "mcp_config_detected",
        "memcore_mcp_detected",
        "authorized_connect_plan_endpoint",
        "/api/v1/platforms/thin-adapter-registry",
        "/api/v1/platforms/authorized-auto-connect/dry-run",
    ]:
        assert hidden_term not in serialized_public

    internal_dashboard = registry_module.build_platform_discovery_dashboard(
        {},
        home=home,
        env={"CODEX_HOME": str(codex_home)},
        public=False,
    )
    internal_items = {item["system"]: item for item in internal_dashboard["items"]}
    assert internal_dashboard["view"] == "internal"
    assert internal_dashboard["counts"]["catalog_watchlist"] >= 99
    assert internal_dashboard["links"]["platform_catalog"] == "/api/v1/platforms/catalog"
    assert internal_items["codex"]["surface_type"] == "known_thin_adapter"
    assert internal_items["kiro"]["surface_type"] == "generic_local_ai_surface"
    assert internal_items["kiro"]["safe_next_step"] == "auto_connect"
    assert internal_items["kiro"]["authorized_connect_plan_endpoint"] == "/api/v1/platforms/kiro/authorized-connect-plan"


def test_codex_official_desktop_native_host_detects_bundled_cli_without_path(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True)
    (codex_home / "sessions" / "2026" / "06" / "04").mkdir(parents=True)
    (codex_home / "state_5.sqlite").write_bytes(b"sqlite-index-placeholder")
    (codex_home / "config.toml").write_text(
        "[mcp_servers.node_repl]\ncommand = 'node_repl.exe'\n",
        encoding="utf-8",
    )
    fake_cli = home / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "716dda49c14d31a0" / "codex.exe"
    fake_cli.parent.mkdir(parents=True)
    fake_cli.write_text("#!/bin/sh\nprintf 'codex-cli 0.136.0-alpha.2\\n'\n", encoding="utf-8")
    fake_cli.chmod(0o755)
    native_host = _write_official_codex_native_host(home, codex_home, fake_cli)

    env = {
        "CODEX_HOME": str(codex_home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "PATH": "",
        "MEMCORE_PACKAGE_SCAN_STRICT_ROOTS": "1",
    }
    with patch("platform_thin_adapter_registry.shutil.which", return_value=None):
        generic = registry_module.build_generic_local_ai_surfaces(home=home, env=env)
        registry = registry_module.build_thin_adapter_registry(
            {},
            home=home,
            env=env,
            include_generic=False,
            include_software_probe=True,
        )

    surfaces = {item["system"]: item for item in generic["surfaces"]}
    codex_surface = surfaces["codex"]
    native_signal = next(
        signal
        for signal in codex_surface["signals"]
        if signal.get("kind") == "codex_chrome_native_host"
    )

    assert native_signal["official_bridge_detected"] is True
    assert native_signal["codex_cli_path"] == str(fake_cli)
    assert native_signal["codex_home"] == str(codex_home)
    assert native_signal["extension_ids"] == ["hehggadaopoacecdllhhajmbjkdcmajg"]
    assert native_signal["content_read"] is False
    assert str(native_host) in codex_surface["config_paths"]
    assert str(codex_home / "state_5.sqlite") in codex_surface["content_store_paths"]
    assert codex_surface["software"]["cli"]["installed"] is True
    assert codex_surface["software"]["cli"]["source"] == "codex_chrome_native_host"
    assert codex_surface["software"]["cli"]["path"] == str(fake_cli)
    assert codex_surface["software"]["cli"]["version"] == "codex-cli 0.136.0-alpha.2"
    assert codex_surface["conversation_memory_boundary"]["complete_conversation_candidate"] is True
    assert codex_surface["conversation_memory_boundary"]["content_read"] is False

    adapters = {item["system"]: item for item in registry["adapters"]}
    codex_adapter = adapters["codex"]
    assert codex_adapter["detected"] is True
    assert codex_adapter["software"]["cli"]["source"] == "codex_chrome_native_host"
    assert str(native_host) in [item["path"] for item in codex_adapter["instances"]]


def test_codex_authorized_plan_uses_official_cli_bridge_not_json_toml(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True)
    config_toml = codex_home / "config.toml"
    config_toml.write_text("[mcp_servers.node_repl]\ncommand = 'node_repl.exe'\n", encoding="utf-8")
    fake_cli = home / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "716dda49c14d31a0" / "codex.exe"
    fake_cli.parent.mkdir(parents=True)
    fake_cli.write_text("#!/bin/sh\nprintf 'codex-cli 0.136.0-alpha.2\\n'\n", encoding="utf-8")
    fake_cli.chmod(0o755)
    native_host = _write_official_codex_native_host(home, codex_home, fake_cli)
    env = {
        "CODEX_HOME": str(codex_home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "PATH": "",
        "MEMCORE_PACKAGE_SCAN_STRICT_ROOTS": "1",
    }

    with patch("platform_thin_adapter_registry.shutil.which", return_value=None):
        result = registry_module.build_authorized_auto_connect_dry_run({}, home=home, env=env, system="codex")
    plan = result["plans"][0]

    assert plan["system"] == "codex"
    assert plan["status"] == "auto_connect_ready"
    assert plan["write_strategy"] == "use_codex_mcp_add_stdio_bridge"
    assert plan["would_write"] == [str(config_toml)]
    assert str(native_host) not in plan["would_write"]
    assert plan["apply_endpoint_status"] == "implemented_for_codex_cli_mcp_bridge"
    assert plan["mcp_plan"]["write_strategy"] == "use_codex_mcp_add_stdio_bridge"
    assert plan["software"]["cli"]["path"] == str(fake_cli)
    assert plan["software"]["cli"]["source"] == "codex_chrome_native_host"
    _assert_adapter_draft_plan_shape(plan, system="codex")


def test_authorized_auto_connect_apply_registers_codex_bridge_with_official_cli(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    memcore_root = tmp_path / "memcore"
    codex_home = home / ".codex"
    codex_home.mkdir(parents=True)
    config_toml = codex_home / "config.toml"
    original_toml = "[mcp_servers.node_repl]\ncommand = 'node_repl.exe'\n"
    config_toml.write_text(original_toml, encoding="utf-8")
    fake_cli = home / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "716dda49c14d31a0" / "codex.exe"
    fake_cli.parent.mkdir(parents=True)
    fake_log = tmp_path / "codex-cli-argv.jsonl"
    fake_cli.write_text(
        f"""#!{sys.executable}
import json
import os
import sys
log = os.environ.get("CODEX_FAKE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
if sys.argv[1:] == ["--version"]:
    print("codex-cli 0.136.0-alpha.2")
sys.exit(0)
""",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    _write_official_codex_native_host(home, codex_home, fake_cli)
    env = {
        "CODEX_HOME": str(codex_home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "PATH": "",
        "MEMCORE_PACKAGE_SCAN_STRICT_ROOTS": "1",
        "CODEX_FAKE_LOG": str(fake_log),
    }

    with patch("platform_thin_adapter_registry.shutil.which", return_value=None):
        result = registry_module.apply_authorized_auto_connect(
            {
                "system": "codex",
                "python_executable": sys.executable,
                "confirmations": list(registry_module.APPLY_GATE_CONFIRMATIONS),
            },
            home=home,
            env=env,
            memcore_root=memcore_root,
        )

    calls = [
        json.loads(line)
        for line in fake_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    add_calls = [argv for argv in calls if argv[:3] == ["mcp", "add", "time-library"]]
    remove_calls = [argv for argv in calls if argv[:3] == ["mcp", "remove", "time-library"]]

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert result["system"] == "codex"
    assert result["platform_write_performed"] is True
    assert result["target_path"] == str(config_toml)
    assert config_toml.read_text(encoding="utf-8") == original_toml
    assert Path(result["backup_path"]).exists()
    assert Path(result["receipt_path"]).exists()
    assert remove_calls
    assert add_calls
    add = add_calls[-1]
    assert "codex_mcp_bridge.py" in " ".join(add)
    assert "--window-binding-registry" in add
    assert "--binding-key" in add
    assert "codex" in add
    assert "--url" not in add
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["system"] == "codex"
    assert receipt["write_strategy"] == "use_codex_mcp_add_stdio_bridge"
    assert receipt["applied_mcp_server"]["type"] == "stdio_bridge"
    assert receipt["applied_mcp_server"]["endpoint"] == "http://127.0.0.1:9851/mcp"
    assert receipt["applied_mcp_server"]["command"] == str(fake_cli)
    assert receipt["applied_mcp_server"]["env"]["PYTHONUTF8"] == "1"
    _assert_adapter_draft_receipt_shape(receipt, system="codex")
    assert result["mcp_plan"] == receipt["mcp_plan"]
    assert result["collector_plan"] == receipt["collector_plan"]
    assert result["raw_archive_plan"] == receipt["raw_archive_plan"]


def test_platform_discovery_dashboard_keeps_claude_code_connectable_but_separate(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    claude_home = home / ".claude"
    claude_home.mkdir(parents=True)
    (claude_home / "settings.json").write_text('{"model":"claude"}', encoding="utf-8")

    dashboard = registry_module.build_platform_discovery_dashboard({}, home=home, env={})
    claude_code = next(item for item in dashboard["items"] if item["system"] == "claude_code_cli")

    assert claude_code["status"] == "auto_connect_ready"
    assert claude_code["safe_next_step"] == "auto_connect"
    assert claude_code["tool_type"] == "recognized_tool"
    assert "current_focus" not in claude_code
    assert "support_level" not in claude_code
    assert claude_code["writes_now"] is False
    assert claude_code["reads_chat_bodies"] is False

    internal_dashboard = registry_module.build_platform_discovery_dashboard({}, home=home, env={}, public=False)
    internal_claude_code = next(
        item for item in internal_dashboard["items"]
        if item["system"] == "claude_code_cli"
    )
    assert internal_claude_code["safe_next_step"] == "auto_connect"
    assert internal_claude_code["current_focus"] is True
    assert internal_claude_code["support_level"] == "adapter_candidate_separate_claude_surface"


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
    assert plan["status"] == "auto_connect_ready"
    assert plan["write_strategy"] == "use_claude_mcp_add_or_update_mcp_json"
    assert str(claude_json) in plan["would_write"]
    assert plan["backup_required"] is True
    assert plan["real_recall_after_connect"] is False
    assert plan["chat_body_parser_requires_verified_collector"] is True
    _assert_adapter_draft_plan_shape(plan, system="claude_code_cli")


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
    assert gate["ready_for_auto_connect"] is False
    assert gate["missing_confirmations"] == list(registry_module.APPLY_GATE_CONFIRMATIONS)
    assert "missing_authorization_confirmations" in gate["blocked_reasons"]
    assert gate["receipt_preview"]["would_write"] == [str(cursor / "mcp.json")]
    assert gate["apply_endpoint_status"] == "implemented_for_json_mcp_surfaces"
    _assert_adapter_draft_plan_shape(gate["plan"], system="cursor")
    _assert_adapter_draft_receipt_shape(gate["receipt_preview"], system="cursor")
    assert gate["receipt_preview"]["mcp_plan"]["would_write"] == [str(cursor / "mcp.json")]


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

    assert gate["status"] == "ready_for_auto_connect"
    assert gate["ready_for_auto_connect"] is True
    assert gate["missing_confirmations"] == []
    assert gate["write_performed"] is False
    assert gate["platform_write_performed"] is False
    assert gate["receipt_preview"]["system"] == "claude_code_cli"
    assert gate["receipt_preview"]["real_recall_after_connect"] is False
    assert gate["receipt_preview"]["chat_body_parser_requires_verified_collector"] is True
    assert str(claude_json) in gate["receipt_preview"]["would_write"]
    assert gate["apply_endpoint_status"] == "implemented_for_json_mcp_surfaces"
    _assert_adapter_draft_plan_shape(gate["plan"], system="claude_code_cli")
    _assert_adapter_draft_receipt_shape(gate["receipt_preview"], system="claude_code_cli")


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
    assert blocked["missing_confirmations"] == ["confirm_connect_stale_or_dormant_platform"]
    assert "missing_authorization_confirmations" in blocked["blocked_reasons"]
    assert blocked["receipt_preview"]["stale_or_dormant_notice"] is True
    assert blocked["receipt_preview"]["freshness"] == "dormant"
    assert ready["status"] == "ready_for_auto_connect"
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
    server = saved["mcpServers"]["time-library"]

    assert result["ok"] is True
    assert result["contract"] == "authorized_auto_connect_apply.v1"
    assert result["status"] == "applied"
    assert result["platform_write_performed"] is True
    assert result["memory_write_performed"] is False
    assert result["real_recall_after_connect"] is False
    assert result["chat_body_parser_requires_verified_collector"] is True
    assert server == {"type": "http", "url": "http://127.0.0.1:9851/mcp"}
    assert Path(result["backup_path"]).exists()
    assert Path(result["receipt_path"]).exists()
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["system"] == "claude_code_cli"
    assert receipt["platform_write_performed"] is True
    assert receipt["memory_write_performed"] is False
    _assert_adapter_draft_receipt_shape(receipt, system="claude_code_cli")
    assert result["mcp_plan"] == receipt["mcp_plan"]
    assert result["collector_plan"] == receipt["collector_plan"]
    assert result["raw_archive_plan"] == receipt["raw_archive_plan"]


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
    server = saved["mcpServers"]["time-library"]

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert result["platform_write_performed"] is True
    assert result["memory_write_performed"] is False
    assert server == {"type": "http", "url": "http://127.0.0.1:9851/mcp"}
    assert "other-tool" in saved["mcpServers"]
    assert Path(result["backup_path"]).exists()
    assert Path(result["receipt_path"]).exists()
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    _assert_adapter_draft_receipt_shape(receipt, system="cursor")
    assert result["mcp_plan"] == receipt["mcp_plan"]
    assert result["collector_plan"] == receipt["collector_plan"]
    assert result["raw_archive_plan"] == receipt["raw_archive_plan"]


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
    server = saved["mcpServers"]["time-library"]

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert result["platform_write_performed"] is True
    assert result["memory_write_performed"] is False
    assert server == {"type": "http", "url": "http://127.0.0.1:9851/mcp"}
    assert result["receipt"]["display_name"] == "Kiro"
    assert Path(result["backup_path"]).exists()
    assert Path(result["receipt_path"]).exists()
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    _assert_adapter_draft_receipt_shape(receipt, system="kiro")
    assert receipt["collector_plan"]["required_before_real_recall"] is True
    assert result["mcp_plan"] == receipt["mcp_plan"]
    assert result["collector_plan"] == receipt["collector_plan"]
    assert result["raw_archive_plan"] == receipt["raw_archive_plan"]


def test_authorized_auto_connect_apply_records_already_connected_claude_code(tmp_path):
    sys.modules.pop("platform_thin_adapter_registry", None)
    registry_module = importlib.import_module("platform_thin_adapter_registry")
    home = tmp_path / "home"
    claude_json = home / ".claude.json"
    home.mkdir(parents=True)
    claude_json.write_text(
        json.dumps({
            "mcpServers": {
                "time-library": {
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
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    _assert_adapter_draft_receipt_shape(receipt, system="claude_code_cli")
    assert result["mcp_plan"] == receipt["mcp_plan"]
    assert result["collector_plan"] == receipt["collector_plan"]
    assert result["raw_archive_plan"] == receipt["raw_archive_plan"]


def test_agent_native_entrypoints_preview_is_read_only_and_covers_current_ecosystem(tmp_path):
    sys.modules.pop("platform_native_entrypoints", None)
    entrypoints_module = importlib.import_module("platform_native_entrypoints")

    result = entrypoints_module.build_agent_native_entrypoints_preview(project_root=tmp_path)
    systems = {item["system"]: item for item in result["entrypoints"]}
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["ok"] is True
    assert result["contract"] == "agent_native_entrypoints_preview.v1"
    assert result["read_only"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert result["content_reads_performed"] is False
    assert result["chat_body_included"] is False
    assert result["raw_excerpt_included"] is False
    assert result["model_call_performed"] is False
    assert result["api_key_included"] is False
    assert result["summary"]["writes_planned"] == 0
    assert result["summary"]["model_calls_planned"] == 0
    assert result["capability_check_payload"] == {"query": "capability check", "mode": "capability_check"}
    assert result["active_recall_order"] == [
        "current_window_session",
        "same_project_workspace",
        "same_workstream_task",
        "stable_user_preferences_tool_facts",
        "explicit_raw_pool_global_only_when_requested",
    ]
    assert result["global_guarantees"]["does_not_write_project_files"] is True
    assert result["global_guarantees"]["does_not_read_chat_bodies"] is True
    assert result["global_guarantees"]["does_not_call_model"] is True
    assert result["global_guarantees"]["capability_check_is_no_recall"] is True
    assert result["global_guarantees"]["raw_source_text_remains_source_of_truth"] is True

    assert set(systems) == {
        "codex",
        "claude_code",
        "gemini_cli",
        "github_copilot",
        "cursor",
        "windsurf",
    }
    assert systems["codex"]["target_paths"] == [str(tmp_path / "AGENTS.md")]
    assert str(tmp_path / "CLAUDE.md") in systems["claude_code"]["target_paths"]
    assert str(tmp_path / ".gemini" / "extensions" / "time-library" / "gemini-extension.json") in systems["gemini_cli"]["target_paths"]
    assert str(tmp_path / ".github" / "agents" / "time-library.md") in systems["github_copilot"]["target_paths"]
    assert systems["cursor"]["target_paths"] == [str(tmp_path / ".cursor" / "rules" / "time-library.mdc")]
    assert str(tmp_path / ".devin" / "rules" / "time-library.md") in systems["windsurf"]["target_paths"]
    assert str(tmp_path / ".windsurf" / "rules" / "time-library.md") in systems["windsurf"]["target_paths"]

    for item in result["entrypoints"]:
        assert item["writes_by_default"] is False
        assert item["would_write"] is False
        assert item["content_reads_performed"] is False
        assert item["chat_body_included"] is False
        assert item["raw_excerpt_included"] is False
        assert item["model_call_performed"] is False
        assert item["api_key_included"] is False
        assert item["mcp_server_name"] == "time-library"
        assert item["tool_name"] == "time_library_recall"
        assert item["mcp_url"] == "http://127.0.0.1:9851/mcp"
        assert item["safe_next_step"]
        assert all(file["would_write"] is False for file in item["files"])
        assert all(file["content_reads_performed"] is False for file in item["files"])
        assert all(file["chat_body_included"] is False for file in item["files"])
        assert all(file["raw_excerpt_included"] is False for file in item["files"])

    assert "Use Time Library as the standing memory rule" in serialized
    assert "Before answering questions that depend on prior work" in serialized
    assert "raw-pool/global only when the user explicitly requests it" in serialized
    assert "Summaries are hints, not replacements for original records" in serialized
    assert "Unknown local AI tool" not in serialized


def test_agent_native_entrypoints_preview_can_hide_preview_content(tmp_path):
    sys.modules.pop("platform_native_entrypoints", None)
    entrypoints_module = importlib.import_module("platform_native_entrypoints")

    result = entrypoints_module.build_agent_native_entrypoints_preview(
        project_root=tmp_path,
        include_content=False,
    )

    assert result["summary"]["file_preview_count"] >= 6
    for item in result["entrypoints"]:
        for file in item["files"]:
            assert "preview_content" not in file


def test_agent_event_triggers_preview_is_read_only_and_maps_memory_moments(tmp_path):
    sys.modules.pop("platform_event_triggers", None)
    triggers_module = importlib.import_module("platform_event_triggers")

    result = triggers_module.build_agent_event_triggers_preview(project_root=tmp_path)
    platforms = {item["system"]: item for item in result["platforms"]}
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["ok"] is True
    assert result["contract"] == "agent_event_trigger_preview.v1"
    assert result["read_only"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert result["content_reads_performed"] is False
    assert result["chat_body_included"] is False
    assert result["raw_excerpt_included"] is False
    assert result["model_call_performed"] is False
    assert result["api_key_included"] is False
    assert result["summary"]["writes_planned"] == 0
    assert result["summary"]["model_calls_planned"] == 0
    assert result["summary"]["platform_count"] == 5
    assert result["summary"]["native_event_platform_count"] >= 2
    assert result["summary"]["moment_count"] >= 18
    assert result["capability_check_payload"] == {"query": "capability check", "mode": "capability_check"}
    assert result["global_guarantees"]["does_not_write_project_files"] is True
    assert result["global_guarantees"]["does_not_read_chat_bodies"] is True
    assert result["global_guarantees"]["does_not_call_model"] is True
    assert result["global_guarantees"]["watcher_remains_continuous_not_install_scan_only"] is True

    assert set(platforms) == {
        "claude_code",
        "gemini_cli",
        "codex",
        "cursor",
        "windsurf",
    }
    assert platforms["claude_code"]["native_event_support"] is True
    assert platforms["gemini_cli"]["native_event_support"] is True
    assert platforms["codex"]["native_event_support"] is False
    assert str(tmp_path / ".claude" / "settings.json") in platforms["claude_code"]["target_paths"]
    assert str(tmp_path / ".gemini" / "settings.json") in platforms["gemini_cli"]["target_paths"]
    assert str(tmp_path / "AGENTS.md") in platforms["codex"]["target_paths"]
    assert str(tmp_path / ".cursor" / "rules" / "time-library.mdc") in platforms["cursor"]["target_paths"]
    assert str(tmp_path / ".devin" / "rules" / "time-library.md") in platforms["windsurf"]["target_paths"]

    claude_moments = {item["moment"]: item for item in platforms["claude_code"]["moments"]}
    assert claude_moments["new_session"]["platform_event"] == "SessionStart"
    assert claude_moments["before_tool_use"]["platform_event"] == "PreToolUse"
    assert claude_moments["after_tool_use"]["platform_event"] == "PostToolUse"
    assert claude_moments["before_context_compact"]["platform_event"] == "PreCompact"
    assert "missed records can be caught up" in claude_moments["session_end"]["user_value"]

    gemini_moments = {item["moment"]: item for item in platforms["gemini_cli"]["moments"]}
    assert gemini_moments["before_tool_use"]["platform_event"] == "BeforeTool"
    assert gemini_moments["after_tool_use"]["platform_event"] == "AfterTool"

    for platform in result["platforms"]:
        assert platform["writes_by_default"] is False
        assert platform["would_write"] is False
        assert platform["content_reads_performed"] is False
        assert platform["chat_body_included"] is False
        assert platform["raw_excerpt_included"] is False
        assert platform["model_call_performed"] is False
        assert platform["api_key_included"] is False
        assert platform["mcp_server_name"] == "time-library"
        assert platform["tool_name"] == "time_library_recall"
        assert platform["setup_hint"]
        for moment in platform["moments"]:
            assert moment["would_write"] is False
            assert moment["real_recall_by_default"] is False
            assert moment["content_reads_performed"] is False
            assert moment["chat_body_included"] is False
            assert moment["raw_excerpt_included"] is False
            assert moment["model_call_performed"] is False
            assert moment["user_value"]
            assert moment["memcore_action"]

    assert "new_session" in result["common_moments"]
    assert "before_tool_use" in result["common_moments"]
    assert "session_end" in result["common_moments"]
    assert "A new Claude Code window starts with the memory rule already fresh" in serialized
    assert "Use watcher catch-up rather than a one-time scan" in serialized
    assert "Unknown local AI tool" not in serialized
