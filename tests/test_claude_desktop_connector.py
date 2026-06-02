import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _load_connector():
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    sys.modules.pop("claude_desktop_connector", None)
    return importlib.import_module("claude_desktop_connector")


def _write_claude_desktop_fixture(tmp_path, monkeypatch):
    home = tmp_path / "Claude"
    home.mkdir()
    (home / "IndexedDB" / "https_claude.ai_0.indexeddb.leveldb").mkdir(parents=True)
    (home / "IndexedDB" / "https_claude.ai_0.indexeddb.blob").mkdir(parents=True)
    (home / "Local Storage" / "leveldb").mkdir(parents=True)
    (home / "Session Storage").mkdir()
    (home / "Preferences").write_text('{"theme":"dark","authToken":"SECRET"}', encoding="utf-8")
    skill_root = home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    (skill_root / ".claude-plugin").mkdir(parents=True)
    (skill_root / "skills" / "yifanchen-zhiyi").mkdir(parents=True)
    (skill_root / ".claude-plugin" / "plugin.json").write_text('{"name":"test-skills"}', encoding="utf-8")
    (skill_root / "manifest.json").write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "skillId": "yifanchen-zhiyi",
                        "name": "Memcore Cloud Zhiyi",
                        "description": "Use Memcore Cloud local memory library.",
                        "enabled": True,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (home / "claude_desktop_config.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "yifanchen-zhiyi": {
                        "command": "node",
                        "args": ["http://127.0.0.1:9851/mcp"],
                        "apiKey": "SECRET_TOKEN",
                    }
                },
                "preferences": {"coworkUserFilesPath": str(tmp_path / "ClaudeFiles")},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    log_home = tmp_path / "ClaudeLogs"
    log_home.mkdir()
    (log_home / "main.log").write_text("metadata only", encoding="utf-8")
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    (export_dir / "claude-data-export.zip").write_bytes(b"fake export")

    monkeypatch.setenv("CLAUDE_DESKTOP_HOME", str(home))
    monkeypatch.setenv("CLAUDE_DESKTOP_LOG_HOME", str(log_home))
    monkeypatch.setenv("CLAUDE_EXPORT_DIR", str(export_dir))
    return home


def _write_related_claude_code_fixture(home):
    sessions = home / "claude-code-sessions"
    runtime = home / "claude-code"
    vm = home / "claude-code-vm"
    sessions.mkdir()
    runtime.mkdir()
    vm.mkdir()
    (sessions / "session.jsonl").write_text(
        '{"surface":"claude-code","relay":"desktop"}\n',
        encoding="utf-8",
    )
    (runtime / "claude.exe").write_text("runtime marker", encoding="utf-8")
    (vm / "bundle.txt").write_text("vm marker", encoding="utf-8")
    return sessions, runtime, vm


def _write_claude_desktop_body_fixture(home):
    leveldb = home / "IndexedDB" / "https_claude.ai_0.indexeddb.leveldb"
    leveldb.mkdir(parents=True, exist_ok=True)
    payload = {
        "conversation_id": "claude-official-1",
        "title": "Claude Desktop sync smoke",
        "messages": [
            {
                "id": "msg-user-1",
                "role": "user",
                "content": "Claude Desktop 用户正文 token=CLAUDE_DESKTOP_RAW_USER。",
                "created_at": "2026-06-01T01:00:00Z",
            },
            {
                "id": "msg-assistant-1",
                "role": "assistant",
                "content": [{"type": "text", "text": "Claude Desktop 助手正文 token=CLAUDE_DESKTOP_RAW_ASSISTANT。"}],
                "created_at": "2026-06-01T01:00:02Z",
            },
        ],
    }
    (leveldb / "000001.log").write_bytes(
        b"\x00leveldb-prefix\x00"
        + json.dumps(payload, ensure_ascii=False).encode("utf-8")
        + b"\x00leveldb-suffix"
    )
    (home / ".claude").mkdir(exist_ok=True)
    (home / ".claude" / "claude-code-session.jsonl").write_text(
        json.dumps(
            {
                "conversation_id": "claude-code-should-not-parse",
                "messages": [
                    {
                        "role": "user",
                        "content": "Claude Code CLI 内容不能被 Claude Desktop 正文解析器读入。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_claude_desktop_status_uses_live_sync_not_export_as_primary(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
    connector = _load_connector()

    status = connector.status()

    assert status["source_system"] == "claude_desktop"
    assert status["status"] == "detected"
    assert status["primary_sync_mode"] == "live_local_user_space_sync"
    assert status["export_role"] == "cold_start_or_backfill_fallback_only"
    assert status["config"]["yifanchen_mcp_detected"] is True
    assert status["consumer_connection"]["recall_connection_ready"] is True
    assert status["consumer_connection"]["readiness"] == "ready_with_mcp"
    assert status["consumer_connection"]["skill_detected"] is True
    assert status["local_storage"]["preferred_raw_source"] == "live_local_sync_manifest_then_authorized_parser"
    assert status["local_storage"]["content_parser_gate"] == "explicit_authorized_parser_required"
    assert status["sync_state"]["sync_scope"] == "system_level_local_user_space_memory_sync"
    assert status["sync_state"]["state_path"]
    assert status["sync_manifest_live_item_count"] >= 5
    assert status["export_candidates_count"] == 1
    assert status["write_performed"] is False
    assert status["platform_write_performed"] is False


def test_claude_desktop_sync_manifest_lists_local_stores_and_export_fallback(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
    connector = _load_connector()

    manifest = connector.build_sync_manifest(public=True)
    artifact_types = {item["artifact_type"] for item in manifest["items"]}
    consumer_types = {item["artifact_type"] for item in manifest["consumer_capability_items"]}

    assert manifest["ok"] is True
    assert manifest["primary_sync_mode"] == "live_local_user_space_sync"
    assert manifest["export_role"] == "cold_start_or_backfill_fallback_only"
    assert "claude_desktop_indexeddb_leveldb_dir" in artifact_types
    assert "claude_desktop_indexeddb_blob_dir" in artifact_types
    assert "claude_desktop_local_storage_leveldb_dir" in artifact_types
    assert "claude_desktop_session_storage_dir" in artifact_types
    assert "claude_desktop_log_file" in artifact_types
    assert "claude_desktop_skills_plugin_dir" in consumer_types
    assert "claude_desktop_skills_manifest_json" in consumer_types
    assert manifest["consumer_capability_item_count"] == 2
    assert manifest["export_fallback_count"] == 1
    assert manifest["export_fallback_items"][0]["sync_role"] == "fallback"
    assert manifest["export_fallback_items"][0]["sync_strategy"] == "export_backfill_fallback"
    assert manifest["parser_gates"][0]["status"] == "not_enabled"
    assert all(item["write_performed"] is False for item in manifest["items"])
    assert all(item["platform_write_performed"] is False for item in manifest["items"])


def test_claude_desktop_related_claude_code_artifacts_keep_dual_attribution(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_related_claude_code_fixture(home)
    connector = _load_connector()

    manifest = connector.build_sync_manifest(public=True)
    related = {
        item["artifact_type"]: item
        for item in manifest["related_items"]
    }
    session_item = related["claude_code_sessions_dir"]
    refs = session_item["source_refs"]

    assert manifest["attribution_policy"]["dual_attribution_supported"] is True
    assert manifest["attribution_policy"]["dual_attribution_does_not_mean_interop"] is True
    assert manifest["attribution_policy"]["source_collection"] == "claude_all"
    assert manifest["attribution_policy"]["collection_does_not_imply_shared_platform_memory"] is True
    assert manifest["related_item_count"] >= 3
    assert session_item["source_family"] == "claude"
    assert session_item["source_collection"] == "claude_all"
    assert session_item["collection_mode"] == "aggregate_all_claude_surfaces_preserve_attribution"
    assert session_item["collection_does_not_imply_shared_platform_memory"] is True
    assert session_item["attribution_mode"] == "dual"
    assert session_item["source_surface"] == "claude_code_cli"
    assert session_item["storage_owner"] == "claude_desktop"
    assert session_item["conversation_origin"] == "claude_code_cli"
    assert session_item["runtime_consumer"] == "claude_code_cli"
    assert session_item["relay_owner"] == "claude_desktop_relay"
    assert session_item["visibility_boundary"] == "isolated_surfaces"
    assert session_item["cross_surface_memory_shared"] is False
    assert session_item["official_relay_interop"] is False
    assert session_item["surface_readability"]["official_claude_desktop_reads_relay_chats"] is False
    assert session_item["surface_readability"]["relay_runtime_reads_official_claude_chats"] is False
    assert session_item["source_systems"] == ["claude_desktop", "claude_code_cli"]
    assert "claude_desktop_relay" in session_item["co_source_systems"]
    assert refs["attribution_mode"] == "dual"
    assert refs["source_collection"] == "claude_all"
    assert refs["collection_does_not_imply_shared_platform_memory"] is True
    assert refs["storage_owner"] == "claude_desktop"
    assert refs["conversation_origin"] == "claude_code_cli"
    assert refs["runtime_consumer"] == "claude_code_cli"
    assert refs["relay_owner"] == "claude_desktop_relay"
    assert refs["visibility_boundary"] == "isolated_surfaces"
    assert refs["cross_surface_memory_shared"] is False

    runtime_item = related["claude_code_runtime_bundle"]
    assert runtime_item["attribution_mode"] == "dual"
    assert runtime_item["conversation_origin"] == "not_conversation_memory"
    assert runtime_item["runtime_consumer"] == "claude_code_cli"


def test_claude_desktop_sync_state_preserves_related_dual_attribution(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_related_claude_code_fixture(home)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    state = connector.build_sync_state(public=True, apply=False)
    related = {
        item["artifact_type"]: item
        for item in state["related_items"]
    }
    session_item = related["claude_code_sessions_dir"]

    assert state["attribution_policy"]["dual_attribution_supported"] is True
    assert state["attribution_policy"]["dual_attribution_does_not_mean_interop"] is True
    assert state["attribution_policy"]["source_collection"] == "claude_all"
    assert state["related_item_count"] >= 3
    assert session_item["sync_status"] == "new"
    assert session_item["source_collection"] == "claude_all"
    assert session_item["attribution_mode"] == "dual"
    assert session_item["storage_owner"] == "claude_desktop"
    assert session_item["conversation_origin"] == "claude_code_cli"
    assert session_item["visibility_boundary"] == "isolated_surfaces"
    assert session_item["official_relay_interop"] is False
    assert session_item["source_refs"]["attribution_mode"] == "dual"
    assert session_item["source_refs"]["storage_owner"] == "claude_desktop"
    assert session_item["source_refs"]["conversation_origin"] == "claude_code_cli"
    assert session_item["source_refs"]["visibility_boundary"] == "isolated_surfaces"

    applied = connector.build_sync_state(public=False, apply=True)
    saved = json.loads(Path(applied["state_path"]).read_text(encoding="utf-8"))
    saved_related = [
        item for item in saved["items_by_key"].values()
        if item.get("artifact_type") == "claude_code_sessions_dir"
    ]
    assert saved_related
    assert saved_related[0]["attribution_mode"] == "dual"
    assert saved_related[0]["source_refs"]["conversation_origin"] == "claude_code_cli"
    assert saved_related[0]["official_relay_interop"] is False


def test_claude_desktop_sync_state_tracks_live_stores_without_export_primary(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    first = connector.build_sync_state(public=True, apply=False)
    artifact_types = {item["artifact_type"] for item in first["items"]}

    assert first["sync_scope"] == "system_level_local_user_space_memory_sync"
    assert first["primary_sync_mode"] == "live_local_user_space_sync"
    assert first["export_role"] == "cold_start_or_backfill_fallback_only"
    assert first["write_performed"] is False
    assert first["platform_write_performed"] is False
    assert first["memory_write_performed"] is False
    assert "claude_data_export_candidate" not in artifact_types
    assert "claude_desktop_indexeddb_leveldb_dir" in artifact_types
    assert "claude_desktop_local_storage_leveldb_dir" in artifact_types
    assert first["parser_gates"][0]["status"] == "not_enabled"
    assert any(item["parser_required"] is True for item in first["items"])

    applied = connector.build_sync_state(public=False, apply=True)
    assert applied["state_receipt_write_performed"] is True
    assert Path(applied["state_path"]).exists()

    (home / "Local Storage" / "leveldb" / "000010.log").write_text("metadata change", encoding="utf-8")
    changed = connector.build_sync_state(public=False, apply=False)
    changed_items = [
        item for item in changed["items"]
        if item["artifact_type"] == "claude_desktop_local_storage_leveldb_dir"
    ]
    assert changed_items
    assert changed_items[0]["sync_status"] == "changed"


def test_claude_desktop_config_summary_redacts_sensitive_fields(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
    connector = _load_connector()

    config_artifact = next(
        item for item in connector.discover_artifacts()
        if item["artifact_type"] == "claude_desktop_config_json"
    )
    summary = config_artifact["config_summary"]

    assert summary["yifanchen_mcp_detected"] is True
    assert summary["redacted_config"]["mcpServers"]["yifanchen-zhiyi"]["apiKey"] == "<redacted>"
    assert summary["redacted_config"]["preferences"]["coworkUserFilesPath"]
    assert "mcpServers" in summary["reported_keys"]


def test_claude_desktop_consumer_status_flags_skill_without_mcp_as_not_ready(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    (home / "claude_desktop_config.json").write_text(
        json.dumps({"preferences": {"coworkUserFilesPath": str(tmp_path / "ClaudeFiles")}}),
        encoding="utf-8",
    )
    connector = _load_connector()

    consumer = connector.consumer_status()

    assert consumer["skill_detected"] is True
    assert consumer["mcp_detected"] is False
    assert consumer["recall_connection_ready"] is False
    assert consumer["readiness"] == "skill_signal_without_tool_connection"
    assert "no Yifanchen MCP" in consumer["likely_rejection_reason"]


def test_claude_desktop_profile_is_registered_as_shadow_source(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    sys.modules.pop("source_system_profile", None)
    profile_mod = importlib.import_module("source_system_profile")

    assert "claude_desktop" in profile_mod.list_registered_profiles()
    profile = profile_mod.get_profile("claude_desktop")
    info = profile.profile_info()
    discovered = profile.discover()

    assert profile.capture_classification == "SHADOW"
    assert "live local user-space sync" in info["preferred_raw_source"]
    assert info["sync_flow"].startswith("Claude Desktop app support/log metadata")
    assert any(item["artifact_type"] == "claude_desktop_indexeddb_leveldb_dir" for item in discovered)
    assert any(item["artifact_type"] == "claude_desktop_indexeddb_blob_dir" for item in discovered)
    assert any(item["artifact_type"] == "claude_data_export_candidate" for item in discovered)


def test_claude_desktop_prefers_existing_windows_localappdata_config_when_no_store_data(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    localappdata = tmp_path / "Local"
    roaming_home = appdata / "Claude"
    local_home = localappdata / "Claude"
    roaming_home.mkdir(parents=True)
    local_home.mkdir(parents=True)
    (local_home / "claude_desktop_config.json").write_text(
        '{"mcpServers":{"yifanchen-zhiyi":{"command":"python","args":["bridge.py"]}}}',
        encoding="utf-8",
    )

    monkeypatch.delenv("CLAUDE_DESKTOP_HOME", raising=False)
    monkeypatch.setenv("MEMCORE_PLATFORM", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    connector = _load_connector()

    assert connector.resolve_claude_home() == local_home
    status = connector.status()

    assert status["desktop_home"].endswith("Local/Claude")
    assert status["config"]["yifanchen_mcp_detected"] is True


def test_claude_desktop_prefers_windows_store_data_over_light_config_dir(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    localappdata = tmp_path / "Local"
    light_home = localappdata / "Claude"
    store_home = localappdata / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    light_home.mkdir(parents=True)
    store_home.mkdir(parents=True)
    (light_home / "claude_desktop_config.json").write_text(
        '{"mcpServers":{"yifanchen-zhiyi":{"command":"python","args":["bridge.py"]}}}',
        encoding="utf-8",
    )
    (store_home / "claude_desktop_config.json").write_text('{"deploymentMode":"3p"}', encoding="utf-8")
    (store_home / "IndexedDB" / "https_claude.ai_0.indexeddb.leveldb").mkdir(parents=True)
    (store_home / "Local Storage" / "leveldb").mkdir(parents=True)
    (store_home / "Session Storage").mkdir()

    monkeypatch.delenv("CLAUDE_DESKTOP_HOME", raising=False)
    monkeypatch.setenv("MEMCORE_PLATFORM", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    connector = _load_connector()

    assert connector.resolve_claude_home() == store_home
    manifest = connector.build_sync_manifest(public=False)
    artifact_types = {item["artifact_type"] for item in manifest["items"]}

    assert "claude_desktop_indexeddb_leveldb_dir" in artifact_types
    assert "claude_desktop_local_storage_leveldb_dir" in artifact_types


def test_claude_desktop_windows_candidates_include_local_dash_profiles(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    localappdata = tmp_path / "Local"
    relay_home = localappdata / "Claude-3p"
    relay_home.mkdir(parents=True)
    (relay_home / "claude_desktop_config.json").write_text('{"deploymentMode":"1p"}', encoding="utf-8")

    monkeypatch.delenv("CLAUDE_DESKTOP_HOME", raising=False)
    monkeypatch.setenv("MEMCORE_PLATFORM", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    connector = _load_connector()

    candidates = connector.default_claude_home_candidates()
    assert relay_home in candidates
    assert connector.resolve_claude_home() == relay_home


def test_claude_desktop_parser_gate_blocks_body_read_without_authorization(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_claude_desktop_body_fixture(home)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    gate = connector.parser_gate_policy()
    result = connector.raw_ingest_dry_run({"limit": 5}, public=True)

    assert gate["gate"] == "explicit_authorized_parser_required"
    assert gate["candidate_store_count"] >= 1
    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["error"] == "authorized_parser_required"
    assert result["candidate_count"] == 0
    assert result["memory_write_performed"] is False
    assert not (tmp_path / "memcore" / "memory").exists()


def test_claude_desktop_authorized_dry_run_reads_candidates_without_raw_write(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_claude_desktop_body_fixture(home)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    result = connector.raw_ingest_dry_run(
        {
            "limit": 5,
            "confirm_authorized_parser": True,
            "confirm_user_owns_claude_desktop_data": True,
        },
        public=True,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["candidate_count"] == 1
    assert result["write_performed"] is False
    assert result["memory_write_performed"] is False
    candidate = result["candidates"][0]
    assert candidate["conversation_id"] == "claude-official-1"
    assert candidate["message_count"] == 2
    assert "messages" not in candidate
    assert "message_excerpts" not in candidate
    refs = candidate["source_refs"]
    assert refs["source_system"] == "claude_desktop"
    assert refs["source_collection"] == "claude_all"
    assert refs["storage_owner"] == "claude_desktop"
    assert refs["conversation_origin"] == "claude_desktop"
    assert refs["runtime_consumer"] == "claude_desktop"
    assert refs["official_relay_interop"] is False
    assert "claude-code-should-not-parse" not in json.dumps(result, ensure_ascii=False)
    assert not (tmp_path / "memcore" / "memory").exists()


def test_claude_desktop_authorized_apply_writes_yifanchen_raw_only(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_claude_desktop_body_fixture(home)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    result = connector.ingest_authorized_raw(
        {
            "limit": 5,
            "apply": True,
            "confirm_authorized_parser": True,
            "confirm_user_owns_claude_desktop_data": True,
            "confirm_write_yifanchen_raw": True,
            "confirm_no_claude_platform_write": True,
        },
        public=False,
    )

    assert result["ok"] is True
    assert result["dry_run"] is False
    assert result["platform_write_performed"] is False
    assert result["memory_write_performed"] is True
    assert result["raw_write"]["records_written"] == 2
    raw_files = list(
        (tmp_path / "memcore" / "memory").glob(
            "*/claude_desktop/claude_desktop_authorized_local_store_jsonl/claude_desktop/claude-official-1.jsonl"
        )
    )
    assert raw_files
    lines = [json.loads(line) for line in raw_files[0].read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    text = "\n".join(json.dumps(line, ensure_ascii=False) for line in lines)
    assert "CLAUDE_DESKTOP_RAW_USER" in text
    assert "CLAUDE_DESKTOP_RAW_ASSISTANT" in text
    assert "claude-code-should-not-parse" not in text
    refs = lines[0]["source_refs"]
    assert refs["source_system"] == "claude_desktop"
    assert refs["raw_session_path"] == str(raw_files[0])
    assert refs["raw_archive_layout"] == "computer_first"
    assert refs["native_artifact_format"] == "claude_desktop_authorized_local_store_jsonl"
    assert refs["source_collection"] == "claude_all"
    assert refs["storage_owner"] == "claude_desktop"
    assert refs["conversation_origin"] == "claude_desktop"
    assert refs["runtime_consumer"] == "claude_desktop"
    assert refs["visibility_boundary"] == "single_surface"
    assert refs["official_relay_interop"] is False
    assert (home / "claude_desktop_config.json").exists()
