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


def _load_p2(tmp_path):
    os.environ["MEMCORE_ROOT"] = str(tmp_path / "memcore")
    os.environ["MEMCORE_CONFIG"] = str(ROOT / "config" / "memcore.json")
    os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "memcore" / "zhiyi")
    for name in ["config_loader", "src.config_loader", "p2_extract", "src.p2_extract"]:
        sys.modules.pop(name, None)
    return importlib.import_module("p2_extract")


def _message(content):
    return {
        "role": "user",
        "content": content,
        "id": "msg-1",
        "source_offset": 0,
        "source_end_offset": max(1, len(content.encode("utf-8"))),
    }


def test_qclaw_contextual_disambiguation_is_not_preference(tmp_path):
    p2 = _load_p2(tmp_path)
    text = "我现在说的是windows原生安装的openclaw，那个我会称呼QClaw，不会和openclaw混说"

    intent = p2.classify_preference_intent(text)
    prefs = p2.extract_preference([_message(text)], "session-qclaw", "window-qclaw", str(tmp_path / "s.jsonl"))

    assert intent["intent_type"] == "correction_disambiguation"
    assert intent["write_preference"] is False
    assert "deictic_reference" in intent["flags"]
    assert prefs == []


def test_p2_load_checkpoint_recovers_corrupt_file(tmp_path, monkeypatch):
    checkpoint = tmp_path / "p2.checkpoint.json"
    checkpoint.write_bytes(b"\x00\x00not-json")
    monkeypatch.setenv("MEMCORE_P2_CHECKPOINT", str(checkpoint))
    p2 = _load_p2(tmp_path)

    assert p2.load_p2_checkpoint() == {}
    assert not checkpoint.exists()
    backups = list(tmp_path.glob("p2.checkpoint.json.corrupt-backup-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"\x00\x00not-json"

    p2.save_p2_checkpoint({"raw.jsonl": {"offset": 34}})
    assert p2.load_p2_checkpoint()["raw.jsonl"]["offset"] == 34


def test_later_qclaw_errata_with_another_tool_is_not_attributed_as_preference(tmp_path):
    p2 = _load_p2(tmp_path)
    text = "我现在说的是 windows 原生安装的 openclaw，另一个工具我会称呼 QClaw，不会和 openclaw 混说"

    intent = p2.classify_preference_intent(text)
    prefs = p2.extract_preference([_message(text)], "session-qclaw-errata", "window-qclaw", str(tmp_path / "s.jsonl"))

    assert intent["intent_type"] == "correction_disambiguation"
    assert intent["target_shelf"] == "errata_or_toolbook"
    assert prefs == []


def test_dream_diary_prompt_is_not_preference(tmp_path):
    p2 = _load_p2(tmp_path)
    text = "[Sun 2026-04-26 03:00 GMT+8] Write a dream diary entry from these memory fragments: - remembered ports and tests"

    intent = p2.classify_preference_intent(text)
    prefs = p2.extract_preference([_message(text)], "session-dream", "window-dream", str(tmp_path / "s.jsonl"))

    assert intent["intent_type"] == "creative_prompt"
    assert prefs == []


def test_long_audit_relay_is_review_not_preference(tmp_path):
    p2 = _load_p2(tmp_path)
    text = (
        "这里有一份审计报告给你看，里面提到称呼和端口边界。"
        "报告认为这不是用户偏好，而是施工组需要复核的工具书事实。" * 4
    )

    intent = p2.classify_preference_intent(text)
    prefs = p2.extract_preference([_message(text)], "session-audit", "window-audit", str(tmp_path / "s.jsonl"))

    assert intent["intent_type"] == "third_party_relay"
    assert prefs == []


def test_public_relay_keywords_are_generic_review_terms(tmp_path):
    p2 = _load_p2(tmp_path)

    assert p2.THIRD_PARTY_RELAY_KW == [
        "审计", "顾问", "报告", "任务书", "外部建议", "评审意见",
        "下面是", "这里有份", "这里有一份",
    ]


def test_private_relay_keywords_can_be_loaded_from_environment(tmp_path, monkeypatch):
    p2 = _load_p2(tmp_path)
    monkeypatch.setenv("MEMCORE_PRIVATE_RELAY_KW", "private-reviewer")
    text = (
        "private-reviewer 发来一段评审材料，里面提到称呼和偏好。"
        "这是一段外部转述，不应该直接进入长期用户偏好。" * 4
    )

    intent = p2.classify_preference_intent(text)
    prefs = p2.extract_preference([_message(text)], "session-private-relay", "window-private-relay", str(tmp_path / "s.jsonl"))

    assert intent["intent_type"] == "third_party_relay"
    assert prefs == []


def test_strong_user_preference_is_still_extracted(tmp_path):
    p2 = _load_p2(tmp_path)
    text = "我不喜欢复杂设置，以后按一行命令能跑通的方式来。"

    intent = p2.classify_preference_intent(text)
    prefs = p2.extract_preference([_message(text)], "session-pref", "window-pref", str(tmp_path / "s.jsonl"))

    assert intent["intent_type"] == "preference"
    assert len(prefs) == 1
    assert prefs[0]["type"] == "preference_memory"
    assert prefs[0]["extract_intent"]["write_preference"] is True
    refs = json.loads(prefs[0]["source_refs"])
    assert refs["canonical_window_id"] == "window-pref"
