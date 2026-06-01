import importlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_openclaw_raw_archive_preserves_platform_record_verbatim(tmp_path, monkeypatch):
    memcore_root = tmp_path / "memcore"
    openclaw_agents = tmp_path / "openclaw" / "agents"
    session_dir = openclaw_agents / "main" / "sessions"
    session_dir.mkdir(parents=True)
    source_path = session_dir / "session-001.jsonl"
    marker = "OpenClaw 原文 token=USER_OWN_TEXT_1234567890 password=只是聊天内容，不能脱敏。"
    source_path.write_text(
        json.dumps({
            "id": "msg-001",
            "type": "message",
            "message": {"role": "user", "content": marker},
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("OPENCLAW_AGENTS_DIR", str(openclaw_agents))
    for name in ["config_loader", "src.config_loader", "src.scanner"]:
        sys.modules.pop(name, None)

    scanner = importlib.import_module("src.scanner")
    record = scanner.scan_openclaw_transcripts()[0]
    dest, status, *_ = scanner.archive_record(record, dry_run=False)

    assert status == "copied"
    assert "/memory/local/openclaw/openclaw_session_jsonl/main/session-001.jsonl" in str(dest)
    assert marker in Path(dest).read_text(encoding="utf-8")
    assert Path(dest).read_bytes() == source_path.read_bytes()
    meta = json.loads(Path(str(dest) + ".meta.json").read_text(encoding="utf-8"))
    assert meta["raw_archive_layout"] == "computer_first"
    assert meta["native_artifact_format"] == "openclaw_session_jsonl"
