import json
import os
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
    dest = Path(payload["items"][0]["dest"])
    assert dest.exists()
    assert "/memory/local/codex/codex_session_jsonl/" in str(dest)

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
