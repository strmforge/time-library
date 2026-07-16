import importlib
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _legacy_local_relay_token() -> str:
    return "cc" + "switch"


def _legacy_local_relay_dashed() -> str:
    return "cc" + "-switch"


def _legacy_local_relay_display() -> str:
    return "CC" + " Switch"


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
    (skill_root / "skills" / "time-library").mkdir(parents=True)
    (skill_root / ".claude-plugin" / "plugin.json").write_text('{"name":"test-skills"}', encoding="utf-8")
    (skill_root / "manifest.json").write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "skillId": "time-library",
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
                    "time-library": {
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
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(tmp_path / "missing-claude-projects"))
    monkeypatch.setenv("CLAUDE_DESKTOP_CODE_SESSIONS_DIR", str(tmp_path / "missing-desktop-code-sessions"))
    monkeypatch.setenv("LOCAL_RELAY_HOME", str(tmp_path / "missing-local-relay"))
    monkeypatch.delenv("LOCAL_RELAY_DB", raising=False)
    monkeypatch.setenv(
        "MEMCORE_WINDOW_BINDING_REGISTRY",
        str(tmp_path / "memcore" / "config" / "window_binding_registry.json"),
    )
    return home


def _write_local_relay_claude_desktop_proxy_db(tmp_path, monkeypatch):
    local_relay_home = tmp_path / "local-relay"
    local_relay_home.mkdir()
    db_path = local_relay_home / "local-relay.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE proxy_request_logs (
                request_id TEXT PRIMARY KEY,
                app_type TEXT NOT NULL,
                model TEXT NOT NULL,
                request_model TEXT,
                status_code INTEGER NOT NULL,
                session_id TEXT,
                created_at INTEGER NOT NULL,
                data_source TEXT NOT NULL DEFAULT 'proxy'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO proxy_request_logs
                (request_id, app_type, model, request_model, status_code, session_id, created_at, data_source)
            VALUES
                ('desktop-ok', 'claude-desktop', 'claude-3-5-sonnet', 'claude-3-5-sonnet', 200, 'desktop-session-a', 1780000000, 'proxy'),
                ('desktop-error', 'claude-desktop', 'claude-3-5-sonnet', 'claude-3-7-sonnet', 502, 'desktop-session-a', 1780000010, 'proxy'),
                ('claude-code-unrelated', 'claude', 'claude-3-5-sonnet', 'claude-3-5-sonnet', 200, 'code-session-a', 1780000020, 'proxy')
            """
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("LOCAL_RELAY_HOME", str(local_relay_home))
    monkeypatch.delenv("LOCAL_RELAY_DB", raising=False)
    return db_path


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


def _write_cowork_fixture(home):
    account_root = home / "local-agent-mode-sessions" / "acct-a" / "org-a"
    desktop_session_id = "local_3a56aca4-01c0-458a-a528-3cbdd1baf121"
    cli_session_id = "d52af095-5243-40a4-af60-d1e4a10a9b7a"
    session_meta = account_root / f"{desktop_session_id}.json"
    session_dir = account_root / desktop_session_id
    session_dir.mkdir(parents=True)
    session_meta.write_text(
        json.dumps(
            {
                "sessionId": desktop_session_id,
                "processName": "claude-cowork-agent",
                "cliSessionId": cli_session_id,
                "cwd": str(session_dir / "outputs"),
                "createdAt": 1780940000000,
                "lastActivityAt": 1780940003000,
                "model": "claude-sonnet-4-6",
                "title": "Pattern identification",
                "initialMessage": "这是什么模式？",
                "systemPrompt": "metadata only; not transcript",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    audit_path = session_dir / "audit.jsonl"
    audit_path.write_text(
        "\n".join([
            json.dumps({
                "type": "user",
                "session_id": desktop_session_id.removeprefix("local_"),
                "uuid": "cowork-user-1",
                "timestamp": "2026-06-08T16:25:47Z",
                "message": {"role": "user", "content": "这是什么模式？"},
            }, ensure_ascii=False),
            json.dumps({
                "type": "assistant",
                "session_id": desktop_session_id.removeprefix("local_"),
                "uuid": "cowork-assistant-1",
                "timestamp": "2026-06-08T16:25:53Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "这是 Cowork 模式。"}],
                },
            }, ensure_ascii=False),
            "",
        ]),
        encoding="utf-8",
    )
    project = session_dir / ".claude" / "projects" / "-local-agent-output"
    project.mkdir(parents=True)
    project_path = project / f"{cli_session_id}.jsonl"
    project_path.write_text(
        "\n".join([
            json.dumps({
                "type": "user",
                "entrypoint": "local-agent",
                "sessionId": cli_session_id,
                "cwd": str(session_dir / "outputs"),
                "uuid": "cowork-project-user-1",
                "timestamp": "2026-06-08T16:25:47Z",
                "message": {"role": "user", "content": "Cowork project JSONL user body"},
            }, ensure_ascii=False),
            json.dumps({
                "type": "assistant",
                "entrypoint": "local-agent",
                "sessionId": cli_session_id,
                "cwd": str(session_dir / "outputs"),
                "uuid": "cowork-project-assistant-1",
                "timestamp": "2026-06-08T16:25:53Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Cowork project JSONL assistant body"}],
                },
            }, ensure_ascii=False),
            "",
        ]),
        encoding="utf-8",
    )
    return session_meta, audit_path, project_path


def _write_desktop_entrypoint_claude_project_fixture(tmp_path, monkeypatch):
    projects_root = tmp_path / ".claude" / "projects"
    project = projects_root / "-Users-example-orchestration_system"
    project.mkdir(parents=True)
    session_id = "desktop-entrypoint-visible-session"
    source_path = project / f"{session_id}.jsonl"
    source_path.write_text(
        "\n".join([
            json.dumps({
                "type": "user",
                "entrypoint": "claude-desktop",
                "sessionId": session_id,
                "cwd": str(tmp_path / "orchestration_system"),
                "timestamp": "2026-06-08T02:00:00Z",
                "message": {
                    "role": "user",
                    "content": "Claude projects JSONL contains this Desktop entrypoint body",
                },
            }, ensure_ascii=False),
            json.dumps({
                "type": "assistant",
                "entrypoint": "claude-desktop",
                "sessionId": session_id,
                "cwd": str(tmp_path / "orchestration_system"),
                "timestamp": "2026-06-08T02:00:01Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Assistant body is in projects JSONL."}],
                },
            }, ensure_ascii=False),
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CLAUDE_DESKTOP_CODE_SESSIONS_DIR", str(tmp_path / "missing-desktop-code-sessions"))
    return source_path


def _write_desktop_entrypoint_project_jsonl(
    project,
    *,
    filename,
    session_id,
    cwd,
    user_text,
    assistant_text,
):
    source_path = project / filename
    source_path.write_text(
        "\n".join([
            json.dumps({
                "type": "user",
                "entrypoint": "claude-desktop",
                "sessionId": session_id,
                "cwd": cwd,
                "timestamp": "2026-06-08T13:00:00Z",
                "message": {
                    "role": "user",
                    "content": user_text,
                },
            }, ensure_ascii=False),
            json.dumps({
                "type": "assistant",
                "entrypoint": "claude-desktop",
                "sessionId": session_id,
                "cwd": cwd,
                "timestamp": "2026-06-08T13:00:01Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": assistant_text}],
                },
            }, ensure_ascii=False),
            "",
        ]),
        encoding="utf-8",
    )
    return source_path


def _write_plain_claude_code_project_fixture(tmp_path, monkeypatch):
    projects_root = tmp_path / ".claude-plain" / "projects"
    project = projects_root / "-Users-example-plain"
    project.mkdir(parents=True)
    session_id = "plain-claude-code-session"
    source_path = project / f"{session_id}.jsonl"
    source_path.write_text(
        "\n".join([
            json.dumps({
                "type": "user",
                "sessionId": session_id,
                "cwd": str(tmp_path / "plain"),
                "message": {"role": "user", "content": "plain claude code user"},
            }, ensure_ascii=False),
            json.dumps({
                "type": "assistant",
                "sessionId": session_id,
                "cwd": str(tmp_path / "plain"),
                "message": {"role": "assistant", "content": "plain claude code assistant"},
            }, ensure_ascii=False),
            "",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CLAUDE_DESKTOP_CODE_SESSIONS_DIR", str(tmp_path / "missing-desktop-code-sessions"))
    return source_path


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


def _write_claude_desktop_user_only_body_fixture(home):
    leveldb = home / "IndexedDB" / "https_claude.ai_0.indexeddb.leveldb"
    leveldb.mkdir(parents=True, exist_ok=True)
    payload = {
        "conversation_id": "claude-official-user-only",
        "title": "Claude Desktop user-only local fragment",
        "messages": [
            {
                "id": "msg-user-only-1",
                "role": "user",
                "content": "只有用户话的本地残片 token=CLAUDE_DESKTOP_USER_ONLY。",
                "created_at": "2026-06-02T01:00:00Z",
            }
        ],
    }
    (leveldb / "000002.log").write_bytes(
        b"\x00leveldb-prefix\x00"
        + json.dumps(payload, ensure_ascii=False).encode("utf-8")
        + b"\x00leveldb-suffix"
    )


def test_claude_desktop_home_override_keeps_log_discovery_inside_override(tmp_path, monkeypatch):
    home = tmp_path / "ClaudeOverride"
    log_home = home / "logs"
    log_home.mkdir(parents=True)

    monkeypatch.setenv("CLAUDE_DESKTOP_HOME", str(home))
    monkeypatch.delenv("CLAUDE_DESKTOP_LOG_HOME", raising=False)
    monkeypatch.setenv("MEMCORE_PLATFORM", "darwin")
    connector = _load_connector()

    assert connector.claude_log_home_candidates() == [log_home]
    assert connector.resolve_claude_log_home() == log_home


def test_claude_desktop_status_uses_live_sync_not_export_as_primary(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
    connector = _load_connector()

    status = connector.status()

    assert status["source_system"] == "claude_desktop"
    assert status["status"] == "detected"
    assert status["primary_sync_mode"] == "live_local_user_space_sync"
    assert status["export_role"] == "cold_start_or_backfill_fallback_only"
    assert status["config"]["time_library_mcp_detected"] is True
    assert status["consumer_connection"]["recall_connection_ready"] is True
    assert status["consumer_connection"]["readiness"] == "ready_with_mcp"
    assert status["consumer_connection"]["skill_detected"] is True
    assert status["local_storage"]["preferred_raw_source"] == "live_local_sync_manifest_then_authorized_parser"
    assert status["local_storage"]["content_parser_gate"] == "explicit_authorized_parser_required"
    assert status["local_storage"]["conversation_body_parser_status"] == "complete_conversation_source_not_verified"
    assert status["local_storage"]["raw_body_readiness"] == "no_conversation_body_candidate_found"
    assert status["local_storage"]["complete_conversation_candidate_count"] == 0
    assert status["local_storage"]["assistant_reply_persistence"] == "unverified"
    assert status["local_storage"]["current_window_memory_registerable"] is False
    assert status["raw_body_readiness"] == "no_conversation_body_candidate_found"
    assert status["current_window_memory_registerable"] is False
    assert status["claude_projects_jsonl_reference"]["boundary"] == "claude_projects_jsonl_reads_claude_projects_jsonl_not_relay_or_proxy_db_chat_body"
    assert status["claude_projects_jsonl_reference"]["relay_db_is_transcript_store"] is False
    assert status["conversation_body_probe_endpoint"] == "/api/v1/source-systems/claude_desktop/conversation-body-probe"
    assert status["sync_state"]["sync_scope"] == "system_level_local_user_space_memory_sync"
    assert status["sync_state"]["state_path"]
    assert status["sync_manifest_live_item_count"] >= 5
    assert status["export_candidates_count"] == 1
    assert status["write_performed"] is False
    assert status["platform_write_performed"] is False


def test_claude_desktop_status_surfaces_claude_projects_jsonl_body(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
    source_path = _write_desktop_entrypoint_claude_project_fixture(tmp_path, monkeypatch)
    connector = _load_connector()

    ref = connector.claude_projects_jsonl_reference(public=False)
    status = connector.status()

    assert ref["ok"] is True
    assert ref["reference"] == "claude_projects_jsonl_desktop_entrypoint"
    assert ref["provider_source_glob"] == "projects/**/*.jsonl"
    assert ref["relay_db_is_transcript_store"] is False
    assert ref["development_reference_is_required_dependency"] is False
    assert ref["ordinary_desktop_browser_store_claimed_complete"] is False
    assert ref["desktop_linked_session_count"] == 1
    assert ref["desktop_linked_complete_conversation_count"] == 1
    assert ref["desktop_linked_assistant_reply_persistence"] == "verified"
    assert ref["latest_desktop_linked"][0]["source_path"] == str(source_path)
    assert ref["latest_desktop_linked"][0]["conversation_origin"] == "claude_desktop_entrypoint_claude_code_session"
    assert status["raw_body_readiness"] == "no_conversation_body_candidate_found"
    assert status["claude_projects_jsonl_desktop_linked_complete_conversation_count"] == 1
    assert status["claude_projects_jsonl_reference"]["desktop_linked_complete_conversation_count"] == 1
    assert status["surface_summary"]["surfaces"]["chat"]["source_surface"] == "claude_ai_web_chat"
    assert status["surface_summary"]["surfaces"]["chat"]["canonical_store"] == "anthropic_cloud"
    assert status["surface_summary"]["surfaces"]["code"]["source_surface"] == "claude_desktop_code_or_agent"
    assert status["surface_summary"]["surfaces"]["code"]["complete_conversation_candidate_count"] == 1


def test_claude_desktop_authorized_apply_mirrors_claude_projects_jsonl(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
    source_path = _write_desktop_entrypoint_claude_project_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    result = connector.ingest_authorized_raw(
        {
            "limit": 5,
            "apply": True,
            "confirm_authorized_parser": True,
            "confirm_user_owns_claude_desktop_data": True,
            "confirm_write_time_library_raw": True,
            "confirm_no_claude_platform_write": True,
        },
        public=False,
    )

    assert result["ok"] is True
    assert result["candidate_count"] == 1
    assert result["raw_write"]["records_written"] == 2
    assert result["raw_write"]["window_bindings_registered"] == 1
    assert result["stats"]["claude_projects_jsonl_candidate_count"] == 1
    assert result["stats"]["claude_projects_jsonl_complete_candidate_count"] == 1
    raw_files = list(
        (tmp_path / "memcore" / "memory").glob(
            "*/claude_desktop/claude_projects_jsonl_desktop_entrypoint/*/*.jsonl"
        )
    )
    assert len(raw_files) == 1
    raw_text = raw_files[0].read_text(encoding="utf-8")
    assert "Claude projects JSONL contains this Desktop entrypoint body" in raw_text
    assert "Assistant body is in projects JSONL" in raw_text
    assert raw_text == source_path.read_text(encoding="utf-8")
    meta = json.loads(Path(str(raw_files[0]) + ".meta.json").read_text(encoding="utf-8"))
    assert meta["source_path"] == str(source_path)
    assert meta["native_artifact_format"] == "claude_projects_jsonl_desktop_entrypoint"
    assert meta["conversation_origin"] == "claude_desktop_entrypoint_claude_code_session"
    assert meta["body_storage_owner"] == "claude_code_session_store"
    assert meta["desktop_metadata_is_conversation_body"] is False
    registry = json.loads((tmp_path / "memcore" / "config" / "window_binding_registry.json").read_text(encoding="utf-8"))
    current = registry["current_windows"]["claude_desktop"]
    assert current["session_id"] == "desktop-entrypoint-visible-session"
    assert current["metadata"]["native_artifact_format"] == "claude_projects_jsonl_desktop_entrypoint"


def test_claude_desktop_surface_summary_splits_chat_cowork_and_code(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_cowork_fixture(home)
    _write_desktop_entrypoint_claude_project_fixture(tmp_path, monkeypatch)
    connector = _load_connector()

    summary = connector.surface_summary(limit=10)

    assert summary["surface_contract"] == "claude_desktop_three_surfaces.v1"
    chat = summary["surfaces"]["chat"]
    cowork = summary["surfaces"]["cowork"]
    code = summary["surfaces"]["code"]
    assert chat["source_surface"] == "claude_ai_web_chat"
    assert chat["canonical_store"] == "anthropic_cloud"
    assert chat["desktop_local_role"] == "browser_cache_and_local_state"
    assert chat["complete_conversation_candidate_count"] == 0
    assert cowork["source_surface"] == "claude_desktop_cowork"
    assert cowork["session_metadata_count"] == 1
    assert cowork["jsonl_candidate_count"] == 2
    assert cowork["complete_conversation_candidate_count"] == 2
    assert {item["artifact_type"] for item in cowork["latest"]} == {
        "claude_desktop_cowork_audit_jsonl",
        "claude_desktop_cowork_projects_jsonl",
    }
    assert code["source_surface"] == "claude_desktop_code_or_agent"
    assert code["native_root"]
    assert code["complete_conversation_candidate_count"] == 1


def test_claude_desktop_authorized_dry_run_includes_cowork_as_separate_surface(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_cowork_fixture(home)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    result = connector.raw_ingest_dry_run(
        {
            "limit": 10,
            "confirm_authorized_parser": True,
            "confirm_user_owns_claude_desktop_data": True,
        },
        public=True,
    )

    assert result["ok"] is True
    assert result["stats"]["cowork_jsonl_candidate_count"] == 2
    cowork = [
        item for item in result["candidates"]
        if item["source_surface"] == "claude_desktop_cowork"
    ]
    assert len(cowork) == 2
    assert {item["artifact_type"] for item in cowork} == {
        "claude_desktop_cowork_audit_jsonl",
        "claude_desktop_cowork_projects_jsonl",
    }
    assert all(item["conversation_origin"] == "claude_desktop_cowork" for item in cowork)
    assert all(item["body_storage_owner"] == "claude_desktop_cowork_local_agent_store" for item in cowork)
    assert all(item["roles"] == ["assistant", "user"] for item in cowork)


def test_claude_desktop_authorized_apply_mirrors_cowork_jsonl_without_touching_chat_cache(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _, audit_path, project_path = _write_cowork_fixture(home)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    result = connector.ingest_authorized_raw(
        {
            "limit": 10,
            "apply": True,
            "confirm_authorized_parser": True,
            "confirm_user_owns_claude_desktop_data": True,
            "confirm_write_time_library_raw": True,
            "confirm_no_claude_platform_write": True,
        },
        public=False,
    )

    assert result["ok"] is True
    assert result["stats"]["cowork_jsonl_candidate_count"] == 2
    assert result["raw_write"]["cowork_jsonl_write"]["sessions_written"] == 2
    raw_files = sorted(
        (tmp_path / "memcore" / "memory").glob(
            "*/claude_desktop/claude_desktop_cowork_*_jsonl/*/*.jsonl"
        )
    )
    assert len(raw_files) == 2
    raw_payloads = {path.read_text(encoding="utf-8") for path in raw_files}
    assert audit_path.read_text(encoding="utf-8") in raw_payloads
    assert project_path.read_text(encoding="utf-8") in raw_payloads
    metas = [
        json.loads(Path(str(path) + ".meta.json").read_text(encoding="utf-8"))
        for path in raw_files
    ]
    assert {meta["source_surface"] for meta in metas} == {"claude_desktop_cowork"}
    assert {meta["conversation_origin"] for meta in metas} == {"claude_desktop_cowork"}
    assert {meta["body_storage_owner"] for meta in metas} == {"claude_desktop_cowork_local_agent_store"}
    assert len({meta["raw_artifact_id"] for meta in metas}) == 2
    assert not list(
        (tmp_path / "memcore" / "memory").glob(
            "*/claude_desktop/claude_ai_web_chat*/*/*.jsonl"
        )
    )


def test_claude_desktop_projects_jsonl_same_session_id_keeps_source_files_separate(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
    projects_root = tmp_path / ".claude" / "projects"
    project = projects_root / "G--codexpro"
    project.mkdir(parents=True)
    session_id = "887e36f9-ebe1-4a72-acee-68765dc8ed2d"
    cwd = "G:\\codexpro"
    first_source = _write_desktop_entrypoint_project_jsonl(
        project,
        filename="887e36f9-ebe1-4a72-acee-68765dc8ed2d.jsonl",
        session_id=session_id,
        cwd=cwd,
        user_text="first native Desktop JSONL source body",
        assistant_text="first source assistant reply",
    )
    second_source = _write_desktop_entrypoint_project_jsonl(
        project,
        filename="4d85513c-9144-4f82-8809-a39e989c3677.jsonl",
        session_id=session_id,
        cwd=cwd,
        user_text="second native Desktop JSONL source body",
        assistant_text="second source assistant reply",
    )
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CLAUDE_DESKTOP_CODE_SESSIONS_DIR", str(tmp_path / "missing-desktop-code-sessions"))
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    result = connector.ingest_authorized_raw(
        {
            "limit": 5,
            "apply": True,
            "confirm_authorized_parser": True,
            "confirm_user_owns_claude_desktop_data": True,
            "confirm_write_time_library_raw": True,
            "confirm_no_claude_platform_write": True,
        },
        public=False,
    )

    assert result["ok"] is True
    assert result["candidate_count"] == 2
    assert result["raw_write"]["records_written"] == 4
    raw_files = sorted(
        (tmp_path / "memcore" / "memory").glob(
            "*/claude_desktop/claude_projects_jsonl_desktop_entrypoint/*/*.jsonl"
        )
    )
    assert len(raw_files) == 2
    assert len({path.name for path in raw_files}) == 2
    raw_payloads = {path.read_text(encoding="utf-8") for path in raw_files}
    assert first_source.read_text(encoding="utf-8") in raw_payloads
    assert second_source.read_text(encoding="utf-8") in raw_payloads
    metas = [
        json.loads(Path(str(path) + ".meta.json").read_text(encoding="utf-8"))
        for path in raw_files
    ]
    assert {meta["session_id"] for meta in metas} == {session_id}
    assert len({meta["raw_artifact_id"] for meta in metas}) == 2
    assert {
        meta["source_path"]
        for meta in metas
    } == {str(first_source), str(second_source)}
    for path, meta in zip(raw_files, metas):
        assert meta["raw_artifact_id_schema"] == "claude_projects_jsonl_raw_artifact_id.v1"
        assert meta["source_refs"]["raw_artifact_id"] == meta["raw_artifact_id"]
        assert meta["source_refs"]["raw_session_path"] == str(path)
        assert meta["project_root"] == cwd


def test_claude_desktop_authorized_ingest_does_not_import_plain_claude_code_projects(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_plain_claude_code_project_fixture(tmp_path, monkeypatch)
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
    assert result["candidate_count"] == 0
    assert result["stats"]["claude_projects_jsonl_candidate_count"] == 0
    serialized = json.dumps(result, ensure_ascii=False)
    assert "plain claude code user" not in serialized
    assert "plain claude code assistant" not in serialized


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


def test_claude_desktop_sync_manifest_includes_local_relay_proxy_metadata_not_chat_body(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_local_relay_claude_desktop_proxy_db(tmp_path, monkeypatch)
    connector = _load_connector()

    manifest = connector.build_sync_manifest(public=True)
    proxy_items = [
        item for item in manifest["items"]
        if item["artifact_type"] == "local_relay_proxy_request_logs_db"
    ]
    status = connector.status()

    assert len(proxy_items) == 1
    item = proxy_items[0]
    summary = item["relay_proxy_request_summary"]
    assert item["source_surface"] == "claude_desktop_local_relay_request_log"
    assert item["storage_owner"] == "local_relay"
    assert item["body_storage_owner"] == "not_complete_conversation_body"
    assert item["conversation_origin"] == "claude_desktop_local_relay_request"
    assert item["relay_owner"] == "local_relay_gateway"
    assert item["visibility_boundary"] == "request_metadata_not_chat_body"
    assert item["surface_readability"]["request_metadata_available"] is True
    assert item["surface_readability"]["complete_conversation_body"] is False
    assert summary["request_count"] == 2
    assert summary["success_count"] == 1
    assert summary["error_count"] == 1
    assert summary["latest_status_code"] == 502
    assert summary["latest_session_id"] == "desktop-session-a"
    assert summary["latest_data_source"] == "proxy"
    assert summary["message_text_returned"] is False
    assert summary["raw_excerpt_returned"] is False
    assert status["relay_gateway_request_log_detected"] is True
    assert status["relay_gateway_request_count"] == 2
    assert status["relay_gateway_latest_status_code"] == 502
    assert status["relay_gateway_visibility_boundary"] == "request_metadata_not_chat_body"
    public_payload = json.dumps({"manifest": manifest, "status": status}, ensure_ascii=False)
    assert _legacy_local_relay_display() not in public_payload
    assert _legacy_local_relay_dashed() not in public_payload
    assert _legacy_local_relay_token() not in public_payload


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
    assert manifest["attribution_policy"]["desktop_installer_includes_cli"] is False
    assert manifest["attribution_policy"]["cli_installation_boundary"] == "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
    assert manifest["attribution_policy"]["desktop_cli_relationship"] == "user_installed_cli_independent_but_desktop_may_manage_local_agent_runtime"
    assert manifest["attribution_policy"]["desktop_managed_runtime_policy"] == "desktop_managed_runtime_is_distinct_from_user_installed_path_cli"
    assert manifest["attribution_policy"]["desktop_code_session_policy"] == "metadata_only_links_desktop_session_to_claude_code_jsonl_body"
    assert manifest["related_item_count"] >= 3
    assert session_item["source_family"] == "claude"
    assert session_item["source_collection"] == "claude_all"
    assert session_item["collection_mode"] == "aggregate_all_claude_surfaces_preserve_attribution"
    assert session_item["collection_does_not_imply_shared_platform_memory"] is True
    assert session_item["attribution_mode"] == "dual"
    assert session_item["source_surface"] == "claude_desktop_code_or_agent"
    assert session_item["storage_owner"] == "claude_desktop"
    assert session_item["body_storage_owner"] == "claude_code_session_store"
    assert session_item["conversation_origin"] == "claude_desktop_managed_claude_code_session"
    assert session_item["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert session_item["desktop_installer_includes_cli"] is False
    assert session_item["cli_installation_boundary"] == "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
    assert session_item["desktop_cli_relationship"] == "user_installed_cli_independent_but_desktop_may_manage_local_agent_runtime"
    assert session_item["user_installed_cli_independent"] is True
    assert session_item["user_installed_path_cli_required"] is False
    assert session_item["desktop_managed_runtime_detected"] is True
    assert session_item["desktop_managed_runtime_owner"] == "claude_desktop"
    assert session_item["desktop_managed_runtime_policy"] == "desktop_managed_runtime_is_distinct_from_user_installed_path_cli"
    assert session_item["desktop_managed_runtime_is_user_installed_cli"] is False
    assert session_item["desktop_metadata_is_conversation_body"] is False
    assert session_item["desktop_code_session_policy"] == "metadata_only_links_desktop_session_to_claude_code_jsonl_body"
    assert session_item["relay_owner"] == "claude_desktop_managed_local_agent"
    assert session_item["visibility_boundary"] == "isolated_surfaces"
    assert session_item["cross_surface_memory_shared"] is False
    assert session_item["official_relay_interop"] is False
    assert session_item["surface_readability"]["desktop_metadata_is_conversation_body"] is False
    assert session_item["surface_readability"]["desktop_managed_runtime_is_user_installed_cli"] is False
    assert session_item["surface_readability"]["ordinary_claude_desktop_chat_store_is_separate"] is True
    assert session_item["source_systems"] == ["claude_desktop", "claude_code_cli"]
    assert "claude_desktop_managed_local_agent" in session_item["co_source_systems"]
    assert refs["attribution_mode"] == "dual"
    assert refs["source_collection"] == "claude_all"
    assert refs["collection_does_not_imply_shared_platform_memory"] is True
    assert refs["storage_owner"] == "claude_desktop"
    assert refs["body_storage_owner"] == "claude_code_session_store"
    assert refs["conversation_origin"] == "claude_desktop_managed_claude_code_session"
    assert refs["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert refs["desktop_installer_includes_cli"] is False
    assert refs["cli_installation_boundary"] == "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
    assert refs["desktop_cli_relationship"] == "user_installed_cli_independent_but_desktop_may_manage_local_agent_runtime"
    assert refs["desktop_managed_runtime_detected"] is True
    assert refs["desktop_managed_runtime_owner"] == "claude_desktop"
    assert refs["desktop_managed_runtime_policy"] == "desktop_managed_runtime_is_distinct_from_user_installed_path_cli"
    assert refs["desktop_managed_runtime_is_user_installed_cli"] is False
    assert refs["desktop_metadata_is_conversation_body"] is False
    assert refs["desktop_code_session_policy"] == "metadata_only_links_desktop_session_to_claude_code_jsonl_body"
    assert refs["relay_owner"] == "claude_desktop_managed_local_agent"
    assert refs["visibility_boundary"] == "isolated_surfaces"
    assert refs["cross_surface_memory_shared"] is False

    runtime_item = related["claude_code_runtime_bundle"]
    assert runtime_item["attribution_mode"] == "dual"
    assert runtime_item["conversation_origin"] == "not_conversation_memory"
    assert runtime_item["body_storage_owner"] == "not_conversation_memory"
    assert runtime_item["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert runtime_item["desktop_installer_includes_cli"] is False
    assert runtime_item["desktop_managed_runtime_detected"] is True
    assert runtime_item["desktop_managed_runtime_is_user_installed_cli"] is False


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
    assert state["attribution_policy"]["desktop_installer_includes_cli"] is False
    assert state["attribution_policy"]["cli_installation_boundary"] == "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
    assert state["attribution_policy"]["desktop_cli_relationship"] == "user_installed_cli_independent_but_desktop_may_manage_local_agent_runtime"
    assert state["attribution_policy"]["desktop_managed_runtime_policy"] == "desktop_managed_runtime_is_distinct_from_user_installed_path_cli"
    assert state["related_item_count"] >= 3
    assert session_item["sync_status"] == "new"
    assert session_item["source_collection"] == "claude_all"
    assert session_item["attribution_mode"] == "dual"
    assert session_item["storage_owner"] == "claude_desktop"
    assert session_item["body_storage_owner"] == "claude_code_session_store"
    assert session_item["conversation_origin"] == "claude_desktop_managed_claude_code_session"
    assert session_item["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert session_item["desktop_installer_includes_cli"] is False
    assert session_item["cli_installation_boundary"] == "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
    assert session_item["desktop_cli_relationship"] == "user_installed_cli_independent_but_desktop_may_manage_local_agent_runtime"
    assert session_item["desktop_managed_runtime_detected"] is True
    assert session_item["desktop_managed_runtime_is_user_installed_cli"] is False
    assert session_item["desktop_metadata_is_conversation_body"] is False
    assert session_item["desktop_code_session_policy"] == "metadata_only_links_desktop_session_to_claude_code_jsonl_body"
    assert session_item["visibility_boundary"] == "isolated_surfaces"
    assert session_item["official_relay_interop"] is False
    assert session_item["source_refs"]["attribution_mode"] == "dual"
    assert session_item["source_refs"]["storage_owner"] == "claude_desktop"
    assert session_item["source_refs"]["body_storage_owner"] == "claude_code_session_store"
    assert session_item["source_refs"]["conversation_origin"] == "claude_desktop_managed_claude_code_session"
    assert session_item["source_refs"]["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert session_item["source_refs"]["desktop_installer_includes_cli"] is False
    assert session_item["source_refs"]["cli_installation_boundary"] == "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
    assert session_item["source_refs"]["desktop_managed_runtime_detected"] is True
    assert session_item["source_refs"]["desktop_managed_runtime_is_user_installed_cli"] is False
    assert session_item["source_refs"]["visibility_boundary"] == "isolated_surfaces"

    applied = connector.build_sync_state(public=False, apply=True)
    saved = json.loads(Path(applied["state_path"]).read_text(encoding="utf-8"))
    saved_related = [
        item for item in saved["items_by_key"].values()
        if item.get("artifact_type") == "claude_code_sessions_dir"
    ]
    assert saved_related
    assert saved_related[0]["attribution_mode"] == "dual"
    assert saved_related[0]["source_refs"]["conversation_origin"] == "claude_desktop_managed_claude_code_session"
    assert saved_related[0]["source_refs"]["runtime_consumer"] == "claude_desktop_managed_claude_code_runtime"
    assert saved_related[0]["source_refs"]["desktop_installer_includes_cli"] is False
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

    assert summary["time_library_mcp_detected"] is True
    assert summary["redacted_config"]["mcpServers"]["time-library"]["apiKey"] == "<redacted>"
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
    assert "no Time Library MCP" in consumer["likely_rejection_reason"]


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
        '{"mcpServers":{"time-library":{"command":"python","args":["bridge.py"]}}}',
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
    assert status["config"]["time_library_mcp_detected"] is True


def test_claude_desktop_prefers_windows_store_data_over_light_config_dir(tmp_path, monkeypatch):
    appdata = tmp_path / "Roaming"
    localappdata = tmp_path / "Local"
    light_home = localappdata / "Claude"
    store_home = localappdata / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    light_home.mkdir(parents=True)
    store_home.mkdir(parents=True)
    (light_home / "claude_desktop_config.json").write_text(
        '{"mcpServers":{"time-library":{"command":"python","args":["bridge.py"]}}}',
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
    assert result["current_window_capture_status"] == "complete_conversation_candidates_verified"
    assert result["assistant_reply_persistence"] == "verified"
    assert result["current_window_binding_status"] == "registerable_after_apply"
    assert result["capture_diagnostic"]["complete_candidate_count"] == 1
    assert result["capture_diagnostic"]["incomplete_candidate_count"] == 0
    assert result["capture_diagnostic"]["current_window_binding_registered"] is False
    assert result["capture_diagnostic"]["not_no_memory"] is False
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
    assert refs["conversation_origin"] == "claude_ai_web_chat"
    assert refs["runtime_consumer"] == "claude_desktop"
    assert refs["official_relay_interop"] is False
    assert "claude-code-should-not-parse" not in json.dumps(result, ensure_ascii=False)
    assert not (tmp_path / "memcore" / "memory").exists()


def test_claude_desktop_status_reports_complete_body_probe_separately_from_mcp(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_claude_desktop_body_fixture(home)
    connector = _load_connector()

    status = connector.status()

    assert status["consumer_connection"]["recall_connection_ready"] is True
    assert status["local_storage"]["raw_body_readiness"] == "complete_conversation_verified"
    assert status["local_storage"]["conversation_body_parser_status"] == "complete_conversation_candidates_verified"
    assert status["local_storage"]["complete_conversation_candidate_count"] == 1
    assert status["local_storage"]["user_only_candidate_count"] == 0
    assert status["local_storage"]["assistant_reply_persistence"] == "verified"
    assert status["local_storage"]["current_window_memory_registerable"] is True
    assert status["local_storage"]["raw_body_probe"]["message_text_returned"] is False
    assert status["local_storage"]["raw_body_probe"]["raw_excerpt_returned"] is False


def test_claude_desktop_conversation_body_probe_reports_user_only_as_partial_without_text(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_claude_desktop_user_only_body_fixture(home)
    connector = _load_connector()

    probe = connector.conversation_body_probe(limit=5)

    assert probe["ok"] is True
    assert probe["raw_body_readiness"] == "partial_fragments_only"
    assert probe["probe_status"] == "complete_conversation_source_not_verified"
    assert probe["candidate_count"] == 1
    assert probe["complete_conversation_candidate_count"] == 0
    assert probe["user_only_candidate_count"] == 1
    assert probe["assistant_reply_persistence"] == "unverified"
    assert probe["current_window_memory_registerable"] is False
    assert probe["message_text_returned"] is False
    assert probe["raw_excerpt_returned"] is False
    serialized = json.dumps(probe, ensure_ascii=False)
    assert "CLAUDE_DESKTOP_USER_ONLY" not in serialized
    assert "candidates" not in probe


def test_claude_desktop_authorized_dry_run_reports_unverified_when_no_complete_candidate(tmp_path, monkeypatch):
    _write_claude_desktop_fixture(tmp_path, monkeypatch)
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
    assert result["candidate_count"] == 0
    assert result["current_window_capture_status"] == "complete_conversation_source_not_verified"
    assert result["assistant_reply_persistence"] == "unverified"
    assert result["current_window_binding_status"] == "not_registerable_without_complete_candidate"
    assert result["capture_diagnostic"]["complete_candidate_count"] == 0
    assert result["capture_diagnostic"]["tiandao_conversation_evidence_contract"] == "tiandao_conversation_evidence.v1"
    assert result["capture_diagnostic"]["conversation_capture_verdict"]["complete_conversation_candidate"] is False
    assert result["capture_diagnostic"]["conversation_capture_verdict"]["not_no_memory"] is False
    assert result["capture_diagnostic"]["not_no_memory"] is True
    assert result["memory_write_performed"] is False
    assert not (tmp_path / "memcore" / "memory").exists()


def test_claude_desktop_user_only_candidate_does_not_verify_assistant_persistence(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_claude_desktop_user_only_body_fixture(home)
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
    assert result["candidate_count"] == 1
    assert result["current_window_capture_status"] == "complete_conversation_source_not_verified"
    assert result["assistant_reply_persistence"] == "unverified"
    assert result["current_window_binding_status"] == "not_registerable_without_complete_candidate"
    assert result["capture_diagnostic"]["complete_candidate_count"] == 0
    assert result["capture_diagnostic"]["incomplete_candidate_count"] == 1
    assert result["capture_diagnostic"]["user_only_candidate_count"] == 1
    assert result["capture_diagnostic"]["assistant_only_candidate_count"] == 0
    assert result["capture_diagnostic"]["tiandao_conversation_evidence_contract"] == "tiandao_conversation_evidence.v1"
    assert result["capture_diagnostic"]["conversation_capture_verdict"]["complete_conversation_candidate"] is False
    assert result["capture_diagnostic"]["conversation_capture_verdict"]["partial_source_policy"] == "evidence_only_not_current_window_memory"
    assert result["capture_diagnostic"]["not_no_memory"] is True
    assert result["candidates"][0]["roles"] == ["user"]
    assert not (tmp_path / "memcore" / "memory").exists()


def test_claude_desktop_authorized_apply_writes_time_library_raw_only(tmp_path, monkeypatch):
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
            "confirm_write_time_library_raw": True,
            "confirm_no_claude_platform_write": True,
        },
        public=False,
    )

    assert result["ok"] is True
    assert result["dry_run"] is False
    assert result["platform_write_performed"] is False
    assert result["memory_write_performed"] is True
    assert result["raw_write"]["records_written"] == 2
    assert result["raw_write"]["window_bindings_registered"] == 1
    assert result["raw_write"]["window_bindings_skipped_incomplete"] == 0
    assert result["current_window_capture_status"] == "complete_conversation_candidates_verified"
    assert result["assistant_reply_persistence"] == "verified"
    assert result["current_window_binding_status"] == "registered"
    assert result["capture_diagnostic"]["current_window_binding_registered"] is True
    raw_files = list(
        (tmp_path / "memcore" / "memory").glob(
            "*/claude_desktop/claude_desktop_authorized_local_store_jsonl/claude-official-1/claude-official-1.jsonl"
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
    assert refs["canonical_window_id"] == "claude-official-1"
    assert refs["session_id"] == "claude-official-1"
    assert refs["raw_session_path"] == str(raw_files[0])
    assert refs["raw_archive_layout"] == "computer_first"
    assert refs["native_artifact_format"] == "claude_desktop_authorized_local_store_jsonl"
    assert refs["source_collection"] == "claude_all"
    assert refs["storage_owner"] == "claude_desktop"
    assert refs["conversation_origin"] == "claude_ai_web_chat"
    assert refs["runtime_consumer"] == "claude_desktop"
    assert refs["visibility_boundary"] == "ordinary_chat_browser_store_parser_gated"
    assert refs["official_relay_interop"] is False
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    current = registry["current_windows"]["claude_desktop"]
    assert current["canonical_window_id"] == "claude-official-1"
    assert current["session_id"] == "claude-official-1"
    assert current["current_window_only"] is True
    assert current["cross_window_read_allowed"] is False
    assert "claude" not in registry["current_windows"]
    assert registry["bindings"]["claude_desktop:current"]["canonical_window_id"] == "claude-official-1"
    assert (home / "claude_desktop_config.json").exists()


def test_claude_desktop_user_only_apply_writes_raw_but_does_not_bind_current_window(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_claude_desktop_user_only_body_fixture(home)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    result = connector.ingest_authorized_raw(
        {
            "limit": 5,
            "apply": True,
            "confirm_authorized_parser": True,
            "confirm_user_owns_claude_desktop_data": True,
            "confirm_write_time_library_raw": True,
            "confirm_no_claude_platform_write": True,
        },
        public=False,
    )

    assert result["ok"] is True
    assert result["candidate_count"] == 1
    assert result["raw_write"]["records_written"] == 1
    assert result["raw_write"]["window_bindings_registered"] == 0
    assert result["raw_write"]["window_bindings_skipped_incomplete"] == 1
    assert result["current_window_capture_status"] == "complete_conversation_source_not_verified"
    assert result["assistant_reply_persistence"] == "unverified"
    assert result["current_window_binding_status"] == "not_registerable_without_complete_candidate"
    assert result["capture_diagnostic"]["current_window_binding_registered"] is False
    assert not (tmp_path / "memcore" / "config" / "window_binding_registry.json").exists()
    raw_files = list(
        (tmp_path / "memcore" / "memory").glob(
            "*/claude_desktop/claude_desktop_authorized_local_store_jsonl/claude-official-user-only/claude-official-user-only.jsonl"
        )
    )
    assert raw_files
    text = raw_files[0].read_text(encoding="utf-8")
    assert "CLAUDE_DESKTOP_USER_ONLY" in text


def test_claude_desktop_authorized_apply_dedupes_stable_messages(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_claude_desktop_body_fixture(home)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    body = {
        "limit": 5,
        "apply": True,
        "confirm_authorized_parser": True,
        "confirm_user_owns_claude_desktop_data": True,
        "confirm_write_time_library_raw": True,
        "confirm_no_claude_platform_write": True,
    }
    first = connector.ingest_authorized_raw(body, public=False)
    second = connector.ingest_authorized_raw(body, public=False)

    assert first["raw_write"]["records_written"] == 2
    assert second["raw_write"]["records_written"] == 0
    assert second["raw_write"]["window_bindings_registered"] == 1
    raw_files = list(
        (tmp_path / "memcore" / "memory").glob(
            "*/claude_desktop/claude_desktop_authorized_local_store_jsonl/claude-official-1/claude-official-1.jsonl"
        )
    )
    assert raw_files
    lines = [json.loads(line) for line in raw_files[0].read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    keys = [line["raw_ingest"]["message_dedupe_key"] for line in lines]
    assert len(keys) == len(set(keys))


def test_claude_desktop_authorized_apply_migrates_legacy_fixed_window_scope(tmp_path, monkeypatch):
    home = _write_claude_desktop_fixture(tmp_path, monkeypatch)
    _write_claude_desktop_body_fixture(home)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    connector = _load_connector()

    old_raw_path = connector._legacy_fixed_scope_raw_session_path("claude-official-1")
    old_raw_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_record = {
        "timestamp": "2026-06-01T01:00:00Z",
        "id": "legacy-msg",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "legacy fixed scope content"}],
        },
        "source_refs": {
            "source_system": "claude_desktop",
            "computer_name": connector._computer_name(),
            "canonical_window_id": "claude_desktop",
            "session_id": "claude-official-1",
            "msg_ids": ["legacy-msg"],
        },
        "raw_ingest": {
            "conversation_id": "claude-official-1",
            "message_index": 0,
            "message_content_hash": connector._message_content_hash("legacy fixed scope content"),
            "message_dedupe_key": connector._stable_message_dedupe_key(
                "claude-official-1",
                "legacy-msg",
                "user",
                connector._message_content_hash("legacy fixed scope content"),
            ),
        },
    }
    old_raw_path.write_text(json.dumps(legacy_record, ensure_ascii=False) + "\n", encoding="utf-8")

    result = connector.ingest_authorized_raw(
        {
            "limit": 5,
            "apply": True,
            "confirm_authorized_parser": True,
            "confirm_user_owns_claude_desktop_data": True,
            "confirm_write_time_library_raw": True,
            "confirm_no_claude_platform_write": True,
        },
        public=False,
    )

    new_raw_path = connector._raw_session_path("claude-official-1", "claude-official-1")
    assert result["raw_write"]["legacy_records_migrated"] == 1
    assert str(old_raw_path) in result["raw_write"]["legacy_raw_paths"]
    assert new_raw_path.exists()
    lines = [json.loads(line) for line in new_raw_path.read_text(encoding="utf-8").splitlines()]
    migrated = next(line for line in lines if line.get("id") == "legacy-msg")
    assert migrated["source_refs"]["canonical_window_id"] == "claude-official-1"
    assert migrated["source_refs"]["session_id"] == "claude-official-1"
    assert migrated["source_refs"]["raw_session_path"] == str(new_raw_path)
