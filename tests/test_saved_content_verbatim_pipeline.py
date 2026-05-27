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


def _reload_p3(tmp_path):
    os.environ["MEMCORE_ROOT"] = str(tmp_path / "memcore")
    os.environ["MEMCORE_CONFIG"] = str(ROOT / "config" / "memcore.json")
    os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "memcore" / "zhiyi")
    for name in ["config_loader", "src.config_loader", "src.p3_recall"]:
        sys.modules.pop(name, None)
    p3 = importlib.import_module("src.p3_recall")
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    return p3


def test_p3_recall_keeps_saved_detail_verbatim_in_injection(tmp_path):
    p3 = _reload_p3(tmp_path)
    marker = "用户保存内容 token=USER_OWN_TEXT_1234567890 password=只是聊天内容。"
    long_detail = "前缀" + ("x" * 260) + marker
    memory = {
        "_type": "case_memory",
        "summary": "保存内容验证",
        "detail": long_detail,
        "score": 0.8,
        "scope": "window/project-a",
        "exp_id": "exp-verbatim",
    }

    formatted = p3.format_memory(memory, "保存内容")

    assert formatted["detail"] == long_detail
    assert marker in formatted["injectable_context"]
    assert "REDACTED" not in formatted["injectable_context"]


def test_dialog_audit_log_preserves_message_verbatim(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in ["config_loader", "src.config_loader", "dialog_entry_proxy", "src.dialog_entry_proxy"]:
        sys.modules.pop(name, None)
    proxy = importlib.import_module("dialog_entry_proxy")
    proxy._flags = {"audit_log": True}
    marker = "用户消息 token=USER_OWN_TEXT_1234567890 password=只是聊天内容。"

    proxy.audit_log({"type": "entry_request", "message": marker, "flags": {"kept": True}})

    lines = Path(proxy.AUDIT_LOG_PATH).read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    assert record["message"] == marker
    assert record["flags"] == {"kept": True}
    assert "message_hash" not in record
    assert "REDACTED" not in json.dumps(record, ensure_ascii=False)


def test_p6_zhiyi_detail_preserves_payload_and_source_refs(tmp_path, monkeypatch):
    memcore = tmp_path / "memcore"
    zhiyi_path = memcore / "zhiyi" / "case_memory" / "case_memory.jsonl"
    zhiyi_path.parent.mkdir(parents=True)
    marker = "知意经验内容 token=USER_OWN_TEXT_1234567890 password=只是聊天内容。"
    source_refs = {
        "source_system": "codex",
        "source_path": str(memcore / "memory" / "codex" / "local" / "p" / "s.jsonl"),
        "token": "USER_OWN_TEXT_1234567890",
    }
    record = {
        "exp_id": "exp-p6-verbatim",
        "type": "case_memory",
        "summary": marker,
        "detail": marker,
        "payload": {"message": marker},
        "source_refs": json.dumps(source_refs, ensure_ascii=False),
    }
    zhiyi_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in ["config_loader", "src.config_loader", "p6_console", "src.p6_console"]:
        sys.modules.pop(name, None)

    p6 = importlib.import_module("p6_console")
    detail = p6._m5_get_memory_detail("exp-p6-verbatim")
    refs = p6._m5_get_memory_refs("exp-p6-verbatim")

    assert detail["payload"]["message"] == marker
    assert detail["_source_refs"]["token"] == "USER_OWN_TEXT_1234567890"
    assert refs["_payload_exposed"] is True
    assert refs["_source_refs"]["token"] == "USER_OWN_TEXT_1234567890"


def test_p6_usage_log_keeps_saved_user_content_in_evidence_items(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in ["config_loader", "src.config_loader", "p6_console", "src.p6_console"]:
        sys.modules.pop(name, None)
    p6 = importlib.import_module("p6_console")
    marker = "召回经验 token=USER_OWN_TEXT_1234567890 password=只是聊天内容。"
    recall_result = {
        "matched_memories": [{
            "exp_id": "exp-usage-verbatim",
            "type": "case_memory",
            "summary": "使用记录验证",
            "detail": marker,
            "injectable_context": marker,
            "confidence": 0.9,
            "should_inject": True,
            "source_refs": {"source_system": "codex"},
        }],
        "total_matched": 1,
        "returned": 1,
    }

    result = p6.build_zhiyi_usage_log_dry_run({
        "query": marker,
        "recall_result": recall_result,
    })

    event = result["event"]
    evidence = event["recall"]["evidence_items"][0]
    assert evidence["detail"] == marker
    assert evidence["injectable_context"] == marker
    assert event["source_refs_policy"]["saved_user_content_preserved"] is True
    assert event["source_refs_policy"]["hash_only_replacement_allowed"] is False
    assert event["source_refs_policy"]["redaction_performed"] is False
