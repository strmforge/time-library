import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _env(tmp_path, codex_sessions, session_index):
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(SRC),
        "MEMCORE_ROOT": str(tmp_path / "memcore"),
        "MEMCORE_CONFIG": str(ROOT / "config" / "memcore.json"),
        "CODEX_SESSIONS_DIR": str(codex_sessions),
        "CODEX_SESSION_INDEX": str(session_index),
        "MEMCORE_P2_CHECKPOINT": str(tmp_path / "p2.checkpoint.json"),
    })
    return env


def _append_jsonl(path, records):
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_codex_session(tmp_path):
    sessions = tmp_path / "codex-sessions" / "2026" / "05" / "27"
    sessions.mkdir(parents=True)
    session_path = sessions / "rollout-2026-05-27T10-00-00-test-codex-session.jsonl"
    _append_jsonl(
        session_path,
        [
            {
                "timestamp": "2026-05-27T10:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "test-codex-session",
                    "cwd": str(tmp_path / "project"),
                    "source": "vscode",
                    "thread_source": "user",
                    "model_provider": "token",
                },
            },
            {
                "timestamp": "2026-05-27T10:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "请记住我偏好打开新窗口时用自然话术接上前文。"}],
                },
            },
            {
                "timestamp": "2026-05-27T10:00:02Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "确认：这次 Codex 接入验证通过，关键路径是 Codex rollout JSONL -> memory/local/codex/codex_session_jsonl/project/session.jsonl -> 知意提炼 -> 下一窗口自然续上前文。"}],
                },
            },
        ],
    )
    session_index = tmp_path / "session_index.jsonl"
    session_index.write_text(json.dumps({
        "id": "test-codex-session",
        "thread_name": "忆凡尘 Codex 接入测试",
        "updated_at": "2026-05-27T10:00:00Z",
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    return sessions.parent.parent.parent, session_index, session_path


def test_codex_scan_and_p2_extract(tmp_path):
    codex_sessions, session_index, _ = _write_codex_session(tmp_path)
    env = _env(tmp_path, codex_sessions, session_index)

    scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(scan.stdout)
    assert payload["changed"] == 1
    assert payload["window_bindings_registered"] == 1
    dest = Path(payload["items"][0]["dest"])
    assert dest.exists()
    assert "/memory/local/codex/codex_session_jsonl/" in str(dest)
    meta = json.loads(Path(str(dest) + ".meta.json").read_text(encoding="utf-8"))
    assert meta["main_river_storage"] == "canonical_dialogue"
    assert Path(meta["canonical_dialogue_path"]).exists()
    assert Path(meta["forensic_runtime_manifest_path"]).exists()
    dialogue_records = [
        json.loads(line)
        for line in Path(meta["canonical_dialogue_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["role"] for item in dialogue_records] == ["user", "assistant"]
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    current = registry["current_windows"]["codex"]
    assert current["canonical_window_id"] == "test-codex-session"
    assert current["session_id"] == "test-codex-session"
    assert current["source_path"] == str(dest)
    assert current["current_window_only"] is True
    assert current["cross_window_read_allowed"] is False
    assert current["metadata"]["project_id"] == payload["items"][0]["canonical_window_id"]
    assert current["metadata"]["project_root"] == str(tmp_path / "project")
    assert current["metadata"]["source_refs_canonical_window_id"] == payload["items"][0]["canonical_window_id"]
    assert registry["current_windows"]["codex_cli"]["session_id"] == "test-codex-session"
    assert registry["bindings"]["codex:current"]["canonical_window_id"] == "test-codex-session"

    extract = subprocess.run(
        [sys.executable, str(SRC / "p2_extract.py"), "--incremental", str(dest)],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    assert "case=1" in extract.stdout

    case_path = tmp_path / "memcore" / "zhiyi" / "case_memory" / "case_memory.jsonl"
    record = json.loads(case_path.read_text(encoding="utf-8").splitlines()[0])
    refs = json.loads(record["source_refs"])
    assert record["source_system"] == "codex"
    assert refs["source_system"] == "codex"
    assert refs["raw_archive_layout"] == "computer_first"
    assert refs["native_artifact_format"] == "codex_session_jsonl"
    assert refs["thread_name"] == "忆凡尘 Codex 接入测试"
    assert refs["byte_offsets"]


def test_codex_scan_and_p2_continue_from_saved_offsets(tmp_path):
    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    env = _env(tmp_path, codex_sessions, session_index)

    first_scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    first_payload = json.loads(first_scan.stdout)
    assert first_payload["changed"] == 1
    dest = Path(first_payload["items"][0]["dest"])
    first_dest_size = dest.stat().st_size

    first_extract = subprocess.run(
        [sys.executable, str(SRC / "p2_extract.py"), "--incremental", str(dest)],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    assert "case=1" in first_extract.stdout
    p2_checkpoint = json.loads((tmp_path / "p2.checkpoint.json").read_text(encoding="utf-8"))
    assert p2_checkpoint[str(dest)]["offset"] == first_dest_size

    _append_jsonl(
        session_path,
        [
            {
                "timestamp": "2026-05-27T10:10:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "这个窗口继续追加，要求只读取新增的聊天记录。"}],
                },
            },
            {
                "timestamp": "2026-05-27T10:10:02Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "增量追加验证确认通过：新文件从生成开始归档，后续追加只读取新增字节，P2 只处理新增消息。"}],
                },
            },
        ],
    )

    second_scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    second_payload = json.loads(second_scan.stdout)
    assert second_payload["changed"] == 1
    second_item = second_payload["items"][0]
    assert second_item["status"].startswith("appended(")
    assert dest.stat().st_size > first_dest_size
    assert "增量追加验证确认通过" in dest.read_text(encoding="utf-8")

    raw_checkpoint = json.loads((tmp_path / "memcore" / ".checkpoint").read_text(encoding="utf-8"))
    codex_entries = [value for key, value in raw_checkpoint.items() if key.startswith("codex:")]
    assert codex_entries
    assert codex_entries[0]["offset"] == session_path.stat().st_size

    second_extract = subprocess.run(
        [sys.executable, str(SRC / "p2_extract.py"), "--incremental", str(dest)],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    assert "case=1" in second_extract.stdout
    p2_checkpoint = json.loads((tmp_path / "p2.checkpoint.json").read_text(encoding="utf-8"))
    assert p2_checkpoint[str(dest)]["offset"] == dest.stat().st_size

    case_path = tmp_path / "memcore" / "zhiyi" / "case_memory" / "case_memory.jsonl"
    cases = [json.loads(line) for line in case_path.read_text(encoding="utf-8").splitlines()]
    assert len(cases) == 2
    assert any("增量追加验证确认通过" in item["summary"] for item in cases)
    for item in cases:
        refs = json.loads(item["source_refs"])
        assert refs["byte_offsets"]


def test_codex_scan_rebuilds_polluted_raw_that_is_larger_than_source(tmp_path):
    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    env = _env(tmp_path, codex_sessions, session_index)

    first_scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    first_payload = json.loads(first_scan.stdout)
    dest = Path(first_payload["items"][0]["dest"])
    source_text = session_path.read_text(encoding="utf-8")
    dest.write_text(source_text + '{"bad":1}{"bad":2}\n' + source_text, encoding="utf-8")
    polluted_size = dest.stat().st_size
    assert polluted_size > session_path.stat().st_size

    before = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--status"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    before_payload = json.loads(before.stdout)
    assert before_payload["raw_sync"]["status"] == "raw_rebuild_recommended"
    assert before_payload["raw_sync"]["raw_overrun_count"] == 1
    assert before_payload["raw_sync"]["missing_or_stale_count"] == 1

    second_scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(second_scan.stdout)
    item = payload["items"][0]

    assert payload["changed"] == 1
    assert item["status"].startswith("rebuilt(raw_larger_than_source")
    assert dest.read_text(encoding="utf-8") == source_text
    assert dest.stat().st_size == session_path.stat().st_size
    backups = [
        path for path in dest.parent.glob(dest.name + ".corrupt-backup-*")
        if not path.name.endswith(".meta.json")
    ]
    assert backups
    assert backups[0].stat().st_size == polluted_size

    checkpoint = json.loads((tmp_path / "memcore" / ".checkpoint").read_text(encoding="utf-8"))
    codex_entries = [value for key, value in checkpoint.items() if key.startswith("codex:")]
    assert codex_entries[0]["offset"] == session_path.stat().st_size


def test_codex_checkpoint_write_uses_unique_temp_path(tmp_path):
    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    env = _env(tmp_path, codex_sessions, session_index)
    stale_fixed_tmp = tmp_path / "memcore" / ".checkpoint.tmp"
    stale_fixed_tmp.parent.mkdir(parents=True, exist_ok=True)
    stale_fixed_tmp.write_text("occupied by another writer", encoding="utf-8")

    scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(scan.stdout)
    assert payload["changed"] == 1
    assert stale_fixed_tmp.read_text(encoding="utf-8") == "occupied by another writer"
    checkpoint = json.loads((tmp_path / "memcore" / ".checkpoint").read_text(encoding="utf-8"))
    codex_entries = [value for key, value in checkpoint.items() if key.startswith("codex:")]
    assert codex_entries[0]["offset"] == session_path.stat().st_size


def test_codex_checkpoint_recovered_rebuilds_missing_forensic_manifest_without_duplicate_dialogue(tmp_path):
    codex_sessions, session_index, _ = _write_codex_session(tmp_path)
    env = _env(tmp_path, codex_sessions, session_index)

    first_scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    dest = Path(json.loads(first_scan.stdout)["items"][0]["dest"])
    dialogue_path = Path(str(dest) + ".canonical_dialogue.jsonl")
    manifest_path = Path(str(dest) + ".forensic_runtime.json")
    assert len(dialogue_path.read_text(encoding="utf-8").splitlines()) == 2

    (tmp_path / "memcore" / ".checkpoint").unlink()
    manifest_path.unlink()

    second_scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(second_scan.stdout)

    assert payload["changed"] == 0
    assert "checkpoint_recovered" in payload["items"][0]["status"]
    assert len(dialogue_path.read_text(encoding="utf-8").splitlines()) == 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dialogue_message_count"] == 2


def test_codex_metadata_updated_backfills_main_river_fields_for_existing_archive(tmp_path):
    codex_sessions, session_index, _ = _write_codex_session(tmp_path)
    env = _env(tmp_path, codex_sessions, session_index)

    first_scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    dest = Path(json.loads(first_scan.stdout)["items"][0]["dest"])
    meta_path = Path(str(dest) + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for key in (
        "main_river_storage",
        "forensic_runtime_storage",
        "canonical_dialogue_path",
        "forensic_runtime_manifest_path",
    ):
        meta.pop(key, None)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    second_scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(second_scan.stdout)
    refreshed_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    assert payload["changed"] == 1
    assert payload["items"][0]["status"].startswith("metadata_updated(")
    assert refreshed_meta["main_river_storage"] == "canonical_dialogue"
    assert refreshed_meta["forensic_runtime_storage"] == "full_raw_archive_plus_manifest"
    assert refreshed_meta["canonical_dialogue_path"] == str(dest) + ".canonical_dialogue.jsonl"
    assert refreshed_meta["forensic_runtime_manifest_path"] == str(dest) + ".forensic_runtime.json"


def test_codex_raw_archive_preserves_platform_record_verbatim(tmp_path):
    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    marker = "用户原话里写 token=USER_OWN_TEXT_1234567890 password=不是凭据只是聊天内容，忆凡尘必须原样保存。"
    _append_jsonl(
        session_path,
        [
            {
                "timestamp": "2026-05-27T10:20:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": marker}],
                },
            },
        ],
    )
    env = _env(tmp_path, codex_sessions, session_index)

    scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(scan.stdout)
    dest = Path(payload["items"][0]["dest"])
    assert marker in dest.read_text(encoding="utf-8")
    assert dest.read_bytes() == session_path.read_bytes()


def test_codex_official_state_db_enriches_sessions_without_reading_chat_body(tmp_path):
    sessions = tmp_path / "codex-sessions" / "2026" / "06" / "04"
    sessions.mkdir(parents=True)
    session_path = sessions / "rollout-2026-06-04T01-00-00-official-thread.jsonl"
    _append_jsonl(
        session_path,
        [
            {
                "timestamp": "2026-06-04T01:00:00Z",
                "type": "session_meta",
                "payload": {"id": "official-thread"},
            },
            {
                "timestamp": "2026-06-04T01:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "official state index probe"}],
                },
            },
        ],
    )
    session_index = tmp_path / "missing-session-index.jsonl"
    session_index.write_text("", encoding="utf-8")
    state_db = tmp_path / "state_5.sqlite"
    project_root = tmp_path / "official-project"
    with sqlite3.connect(state_db) as conn:
        conn.execute(
            """
            create table threads (
              id text primary key,
              rollout_path text,
              created_at real,
              updated_at real,
              source text,
              model_provider text,
              cwd text,
              title text,
              cli_version text,
              thread_source text,
              model text,
              reasoning_effort text,
              archived integer,
              has_user_event integer
            )
            """
        )
        conn.execute(
            """
            insert into threads (
              id, rollout_path, created_at, updated_at, source, model_provider,
              cwd, title, cli_version, thread_source, model, reasoning_effort,
              archived, has_user_event
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "official-thread",
                str(session_path),
                1780506000,
                1780506600,
                "desktop",
                "openai",
                str(project_root),
                "Official Codex state index",
                "codex-cli 0.136.0-alpha.2",
                "codex_desktop",
                "gpt-5.5",
                "medium",
                0,
                1,
            ),
        )

    env = _env(tmp_path, sessions.parent.parent.parent, session_index)
    env["CODEX_STATE_DB"] = str(state_db)

    discover = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--discover", "--limit", "1"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    artifact = json.loads(discover.stdout)[0]

    assert artifact["thread_name"] == "Official Codex state index"
    assert artifact["project_root"] == str(project_root)
    assert artifact["thread_index_source"] == "codex_state_5_threads"
    assert artifact["official_thread_index_detected"] is True
    assert artifact["codex_source"] == "desktop"
    assert artifact["model_provider"] == "openai"
    assert artifact["cli_version"] == "codex-cli 0.136.0-alpha.2"
    assert artifact["codex_model"] == "gpt-5.5"
    assert artifact["reasoning_effort"] == "medium"

    status = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--status"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    status_payload = json.loads(status.stdout)
    assert status_payload["state_thread_index_reachable"] is True
    assert status_payload["state_thread_count"] == 1
    assert status_payload["source_kind"] == "codex_official_threads_and_session_records"
    assert status_payload["capture_independent_of_mcp"] is True
    assert status_payload["consumer_connection_required"] is False
    assert status_payload["raw_sync"]["status"] == "raw_missing"
    assert status_payload["raw_sync"]["independent_of_mcp"] is True
    assert status_payload["raw_sync"]["consumer_connection_required"] is False
    assert status_payload["raw_sync"]["missing_or_stale_count"] == 1
    assert status_payload["raw_sync"]["latest_missing_or_stale"][0]["session_id"] == "official-thread"
    assert status_payload["latest"][0]["official_thread_index_detected"] is True


def test_codex_raw_sync_status_turns_current_after_source_archive(tmp_path):
    codex_sessions, session_index, _ = _write_codex_session(tmp_path)
    env = _env(tmp_path, codex_sessions, session_index)

    before = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--status"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    before_payload = json.loads(before.stdout)
    assert before_payload["raw_sync"]["status"] == "raw_missing"
    assert before_payload["capture_independent_of_mcp"] is True

    subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )

    after = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--status"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    after_payload = json.loads(after.stdout)
    assert after_payload["raw_sync"]["status"] == "raw_current"
    assert after_payload["raw_sync"]["missing_or_stale_count"] == 0


def test_codex_catch_up_latest_sessions_chases_active_tail(tmp_path):
    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    env = _env(tmp_path, codex_sessions, session_index)

    first_scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    first_payload = json.loads(first_scan.stdout)
    assert first_payload["changed"] == 1

    _append_jsonl(
        session_path,
        [
            {
                "timestamp": "2026-05-27T10:30:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "活跃长会话继续写入，watcher 必须短窗口追尾。"}],
                },
            },
        ],
    )

    before = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--status"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    before_payload = json.loads(before.stdout)
    assert before_payload["raw_sync"]["missing_or_stale_count"] == 1
    assert before_payload["raw_sync"]["status"] == "raw_catching_up"
    assert before_payload["raw_sync"]["raw_archive_max_lag_bytes"] > 0

    catch_up = subprocess.run(
        [
            sys.executable,
            str(SRC / "codex_local_connector.py"),
            "--catch-up",
            "--limit",
            "1",
            "--budget-ms",
            "1000",
            "--max-passes",
            "4",
        ],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(catch_up.stdout)

    assert payload["changed"] == 1
    assert payload["raw_sync"]["status"] == "raw_current"
    assert payload["raw_sync"]["missing_or_stale_count"] == 0
    assert payload["raw_sync"]["raw_archive_max_lag_bytes"] == 0


def test_p2_zhiyi_experience_detail_preserves_saved_content_verbatim(tmp_path):
    sessions = tmp_path / "codex-sessions" / "2026" / "05" / "27"
    sessions.mkdir(parents=True)
    session_path = sessions / "rollout-2026-05-27T11-00-00-verbatim-detail.jsonl"
    marker = "这段用户输入包含 token=USER_OWN_TEXT_1234567890 password=只是聊天内容，必须在知意经验里完整回到。"
    assistant = "确认方案成立，验证通过，关键路径已经跑通，完整记录必须保留。"
    _append_jsonl(
        session_path,
        [
            {
                "timestamp": "2026-05-27T11:00:00Z",
                "type": "session_meta",
                "payload": {"id": "verbatim-detail-session", "cwd": str(tmp_path / "project")},
            },
            {
                "id": "turn-parent",
                "timestamp": "2026-05-27T11:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": marker}],
                },
            },
            {
                "id": "turn-child",
                "timestamp": "2026-05-27T11:00:02Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": assistant}],
                },
            },
        ],
    )
    session_index = tmp_path / "session_index.jsonl"
    session_index.write_text("", encoding="utf-8")
    env = _env(tmp_path, sessions.parent.parent.parent, session_index)

    scan = subprocess.run(
        [sys.executable, str(SRC / "codex_local_connector.py"), "--scan"],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    dest = Path(json.loads(scan.stdout)["items"][0]["dest"])

    extract = subprocess.run(
        [sys.executable, str(SRC / "p2_extract.py"), "--incremental", str(dest)],
        env=env,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    assert "case=1" in extract.stdout

    case_path = tmp_path / "memcore" / "zhiyi" / "case_memory" / "case_memory.jsonl"
    records = [json.loads(line) for line in case_path.read_text(encoding="utf-8").splitlines()]
    assert any(marker in record["detail"] and assistant in record["detail"] for record in records)
    assert "REDACTED" not in case_path.read_text(encoding="utf-8")
