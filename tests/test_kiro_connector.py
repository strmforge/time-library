import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_kiro(tmp_path, monkeypatch, session_root):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("KIRO_WORKSPACE_SESSIONS_DIR", str(session_root))
    monkeypatch.setenv("APPDATA", str(tmp_path / "home" / "AppData" / "Roaming"))
    for name in [
        "config_loader",
        "src.config_loader",
        "raw_archive_layout",
        "src.raw_archive_layout",
        "kiro_local_connector",
        "src.kiro_local_connector",
    ]:
        sys.modules.pop(name, None)
    return importlib.import_module("kiro_local_connector")


def _write_session(path, messages):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "workspace": {"name": path.parent.name},
        "messages": [
            {
                "message": {
                    "id": item["id"],
                    "role": item["role"],
                    "content": item["content"],
                    "createdAt": item.get("created_at", "2026-06-03T01:00:00Z"),
                }
            }
            for item in messages
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_kiro_scan_archives_complete_session_and_incrementally_appends(tmp_path, monkeypatch):
    session_root = tmp_path / "AppData" / "Roaming" / "Kiro" / "User" / "globalStorage" / "kiro.kiroagent" / "workspace-sessions"
    session_path = session_root / "workspace-alpha" / "session.json"
    _write_session(
        session_path,
        [
            {"id": "u1", "role": "user", "content": "Kiro 这条用户消息要被持续同步。"},
            {"id": "a1", "role": "assistant", "content": "Kiro 助手回复也已经持久化。"},
        ],
    )
    kiro = _load_kiro(tmp_path, monkeypatch, session_root)

    first = kiro.scan_sessions()
    assert first["source_system"] == "kiro"
    assert first["native_artifact_format"] == "kiro_workspace_sessions_json"
    assert first["discovered"] == 1
    assert first["changed"] == 1
    assert first["complete_conversation_candidates"] == 1
    assert first["window_bindings_registered"] == 1
    dest = Path(first["items"][0]["dest"])
    assert "/memory/local/kiro/kiro_workspace_sessions_json/workspace-alpha/workspace-alpha.jsonl" in str(dest)
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    current = registry["current_windows"]["kiro"]
    assert current["canonical_window_id"] == "workspace-alpha"
    assert current["session_id"] == "workspace-alpha"
    assert current["source_path"] == str(dest)
    assert current["current_window_only"] is True
    assert current["cross_window_read_allowed"] is False
    assert current["metadata"]["workspace_id"] == "workspace-alpha"
    assert current["metadata"]["project_id"] == "workspace-alpha"
    assert registry["bindings"]["kiro:current"]["canonical_window_id"] == "workspace-alpha"

    records = _read_jsonl(dest)
    assert [item["payload"]["role"] for item in records] == ["user", "assistant"]
    assert "Kiro 这条用户消息要被持续同步。" in json.dumps(records[0], ensure_ascii=False)
    assert "Kiro 助手回复也已经持久化。" in json.dumps(records[1], ensure_ascii=False)
    refs = records[0]["source_refs"]
    assert refs["source_system"] == "kiro"
    assert refs["computer_name"] == "local"
    assert refs["canonical_window_id"] == "workspace-alpha"
    assert refs["session_id"] == "workspace-alpha"
    assert refs["source_path"] == str(session_path)
    assert refs["native_artifact_format"] == "kiro_workspace_sessions_json"
    assert refs["raw_archive_layout"] == "computer_first"
    assert records[0]["raw_ingest"]["saved_content_preserved_verbatim"] is True

    second = kiro.scan_sessions()
    assert second["changed"] == 0
    assert second["window_bindings_registered"] == 0
    assert second["items"][0]["records_written"] == 0
    assert len(_read_jsonl(dest)) == 2

    _write_session(
        session_path,
        [
            {"id": "u1", "role": "user", "content": "Kiro 这条用户消息要被持续同步。"},
            {"id": "a1", "role": "assistant", "content": "Kiro 助手回复也已经持久化。"},
            {"id": "u2", "role": "user", "content": "关闭窗口前又追加了一轮。"},
            {"id": "a2", "role": "assistant", "content": "增量 collector 只写新增消息，不重复旧记录。"},
        ],
    )

    third = kiro.scan_sessions()
    assert third["changed"] == 1
    assert third["window_bindings_registered"] == 1
    assert third["items"][0]["records_written"] == 2
    records = _read_jsonl(dest)
    assert len(records) == 4
    assert "增量 collector 只写新增消息" in json.dumps(records[-1], ensure_ascii=False)


def test_kiro_user_only_local_record_is_evidence_not_complete_conversation(tmp_path, monkeypatch):
    session_root = tmp_path / "kiro-workspace-sessions"
    session_path = session_root / "workspace-user-only" / "session.json"
    _write_session(
        session_path,
        [
            {"id": "u1", "role": "user", "content": "如果本地只保存用户消息，不能宣称完整召回。"},
        ],
    )
    kiro = _load_kiro(tmp_path, monkeypatch, session_root)

    result = kiro.scan_sessions()

    assert result["discovered"] == 1
    assert result["complete_conversation_candidates"] == 0
    assert result["window_bindings_registered"] == 0
    item = result["items"][0]
    assert item["roles"] == ["user"]
    assert item["complete_conversation_candidate"] is False
    assert item["tiandao_conversation_evidence_contract"] == "tiandao_conversation_evidence.v1"
    assert item["conversation_capture_verdict"]["complete_conversation_candidate"] is False
    assert item["conversation_capture_verdict"]["partial_source_policy"] == "evidence_only_not_current_window_memory"
    records = _read_jsonl(item["dest"])
    assert len(records) == 1
    assert records[0]["payload"]["role"] == "user"
    assert not (tmp_path / "memcore" / "config" / "window_binding_registry.json").exists()


def test_kiro_status_reports_continuous_millisecond_level_collector(tmp_path, monkeypatch):
    session_root = tmp_path / "kiro-workspace-sessions"
    _write_session(
        session_root / "workspace-status" / "session.json",
        [
            {"id": "u1", "role": "user", "content": "status user"},
            {"id": "a1", "role": "assistant", "content": "status assistant"},
        ],
    )
    kiro = _load_kiro(tmp_path, monkeypatch, session_root)

    status = kiro.status()

    assert status["ok"] is True
    assert status["source_system"] == "kiro"
    assert status["reachable"] is True
    assert status["collector_status"] == "continuous_incremental_json_snapshot"
    assert status["poll_interval_milliseconds"] == 250
    assert status["poll_interval_seconds"] == 0.25
    assert status["target_latency_milliseconds"] == 250
    assert status["millisecond_level"] is True
    assert status["latest"][0]["read_only_probe"] is True
