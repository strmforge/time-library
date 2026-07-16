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


def test_p3_recall_does_not_block_saved_user_secret_like_words(tmp_path):
    p3 = _reload_p3(tmp_path)
    memcore = tmp_path / "memcore"
    raw_path = memcore / "memory" / "codex" / "local" / "p" / "s.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("{}", encoding="utf-8")
    marker = "用户保存内容 token=USER_OWN_TEXT_1234567890 password=只是聊天内容。"
    zhiyi_path = memcore / "zhiyi" / "case_memory" / "case_memory.jsonl"
    zhiyi_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "exp_id": "exp-secret-like-verbatim",
        "type": "case_memory",
        "summary": "原样召回测试",
        "detail": marker,
        "score": 0.8,
        "scope": "window/project-a",
        "source_refs": {
            "source_system": "codex",
            "source_path": str(raw_path),
            "msg_ids": ["msg-1"],
        },
    }
    zhiyi_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    result = p3.handle_recall({
        "query": "原样召回测试",
        "recall_mode": "substring",
        "top_k": 3,
    })

    assert result["matched_memories"]
    assert result["matched_memories"][0]["detail"] == marker
    assert "REDACTED" not in json.dumps(result, ensure_ascii=False)


def test_p3_recall_scope_uses_only_explicit_source_filter(tmp_path):
    p3 = _reload_p3(tmp_path)

    scoped = p3._recall_request_scope(canonical_window_id_filter="window-a")
    explicit = p3._recall_request_scope(canonical_window_id_filter="window-a", source_system_filter="hermes")
    from_scope = p3._recall_request_scope(scope_filter="window/window-b")

    assert scoped["source_system"] == ""
    assert explicit["source_system"] == "hermes"
    assert from_scope["canonical_window_id"] == "window-b"
    assert from_scope["source_system"] == ""


def test_p3_xingce_projection_never_invents_a_platform_source(tmp_path):
    p3 = _reload_p3(tmp_path)
    base = {
        "candidate_id": "candidate-source-boundary",
        "title": "source boundary",
        "evidence_refs": [{"source_path": "/tmp/evidence.jsonl"}],
    }

    unknown = p3._xingce_candidate_to_memory(base, "/tmp/candidate.json", {})
    declared = p3._xingce_candidate_to_memory(
        {**base, "candidate_id": "candidate-declared", "source_system": "declared_origin"},
        "/tmp/candidate-declared.json",
        {},
    )

    assert unknown["source_refs"].get("source_system", "") == ""
    assert declared["source_refs"]["source_system"] == "declared_origin"


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


def test_dialog_entry_supports_evidence_bound_model_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in ["config_loader", "src.config_loader", "dialog_entry_proxy", "src.dialog_entry_proxy"]:
        sys.modules.pop(name, None)
    proxy = importlib.import_module("dialog_entry_proxy")

    def fake_model_answer(question, evidence_items, **kwargs):
        assert question == "下一步是什么？"
        assert evidence_items[0]["evidence_ref"] == "exp-next"
        return {
            "ok": True,
            "contract": "evidence_bound_model.v2026.6.18",
            "model_call_performed": True,
            "answer": "先核对 NAS，再实施下一刀。",
            "verdict": "answered",
            "confidence": 0.88,
            "supporting_refs": ["exp-next"],
            "evidence_count": 1,
            "api_key_env": "MINIMAX_API_KEY",
            "api_key_present": True,
            "transparency_recorded": False,
            "transparency_error": "OSError: ledger lock timeout",
            "transparency_warning": "model_call_succeeded_but_transparency_ledger_write_failed",
        }

    monkeypatch.setattr(proxy, "run_evidence_bound_answer", fake_model_answer)
    result = {
        "status": "ok",
        "chain": "F3_zhiyi_direct",
        "answer": "旧草案",
        "zhiyi_context": {
            "summary": "下一步纪律",
            "matched_memories": [
                {
                    "exp_id": "exp-next",
                    "summary": "先核对 NAS，再实施下一刀。",
                    "source_refs": {"source_system": "nas"},
                    "score": 0.9,
                }
            ],
        },
        "source_refs": [{"source_system": "nas"}],
        "recall_count": 1,
    }

    updated = proxy.maybe_run_zhiyi_live_model_call(
        {
            "model_call": {
                "enabled": True,
                "provider": "minimax",
                "confirm_live_model_call": True,
                "model": "MiniMax-M2",
                "debug": True,
            }
        },
        "下一步是什么？",
        result,
    )
    event = proxy.build_zhiyi_usage_log_event("下一步是什么？", updated, {})

    assert updated["answer"] == "先核对 NAS，再实施下一刀。"
    assert updated["answer_source"] == "evidence_bound_model_call"
    assert updated["model_call"]["transport"] == "openai_compatible_http"
    assert updated["model_call"]["supporting_refs"] == ["exp-next"]
    assert updated["model_call"]["used_source_refs"] == ["exp-next"]
    assert updated["model_call"]["evidence_packet_refs"] == ["exp-next"]
    assert updated["model_call"]["transparency_recorded"] is False
    assert updated["model_call"]["transparency_error"] == "OSError: ledger lock timeout"
    assert updated["model_call"]["transparency_warning"] == "model_call_succeeded_but_transparency_ledger_write_failed"
    assert updated["used_source_refs"] == ["exp-next"]
    assert updated["answer_debug"]["contract"] == "dialog_entry_answer_debug.v2026.6.18"
    assert updated["answer_debug"]["read_only"] is True
    assert updated["answer_debug"]["draft_answer"] == "旧草案"
    assert updated["answer_debug"]["final_answer"] == "先核对 NAS，再实施下一刀。"
    assert updated["answer_debug"]["model_call"]["called"] is True
    assert updated["answer_debug"]["model_call"]["supporting_refs"] == ["exp-next"]
    assert updated["answer_debug"]["model_call"]["evidence_packet_refs"] == ["exp-next"]
    assert updated["answer_debug"]["evidence"][0]["evidence_ref"] == "exp-next"
    assert updated["answer_debug"]["evidence"][0]["source_refs"] == {"source_system": "nas"}
    assert event["model_call"]["model_contract"] == "evidence_bound_model.v2026.6.18"
    assert event["model_call"]["supporting_refs"] == ["exp-next"]
    assert event["model_call"]["transparency_recorded"] is False
    assert event["model_call"]["transparency_error"] == "OSError: ledger lock timeout"
    assert event["model_call"]["transparency_warning"] == "model_call_succeeded_but_transparency_ledger_write_failed"


def test_dialog_entry_accepts_evidence_bound_model_unknown_as_final_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in ["config_loader", "src.config_loader", "dialog_entry_proxy", "src.dialog_entry_proxy"]:
        sys.modules.pop(name, None)
    proxy = importlib.import_module("dialog_entry_proxy")

    def fake_model_unknown(question, evidence_items, **kwargs):
        assert question == "远端发布完成了吗？"
        assert evidence_items[0]["evidence_ref"] == "exp-gap"
        return {
            "ok": True,
            "contract": "evidence_bound_model.v2026.6.18",
            "model_call_performed": True,
            "answer": "UNKNOWN",
            "verdict": "unknown",
            "confidence": 0.0,
            "supporting_refs": [],
            "evidence_count": 1,
            "unknown_reason": "remote_release_receipt_missing",
            "api_key_env": "MINIMAX_API_KEY",
            "api_key_present": True,
        }

    monkeypatch.setattr(proxy, "run_evidence_bound_answer", fake_model_unknown)
    result = {
        "status": "ok",
        "chain": "F3_zhiyi_direct",
        "answer": "旧草案",
        "zhiyi_context": {
            "matched_memories": [
                {
                    "exp_id": "exp-gap",
                    "summary": "只有本地测试证据，没有远端发布回执。",
                    "source_refs": {"source_system": "fixture"},
                    "score": 0.9,
                }
            ],
        },
        "source_refs": [{"source_system": "fixture"}],
        "recall_count": 1,
    }

    updated = proxy.maybe_run_zhiyi_live_model_call(
        {
            "model_call": {
                "enabled": True,
                "provider": "minimax",
                "confirm_live_model_call": True,
                "model": "MiniMax-M2",
                "debug": True,
            }
        },
        "远端发布完成了吗？",
        result,
    )

    assert updated["answer"] == "UNKNOWN"
    assert updated["answer_source"] == "evidence_bound_model_call"
    assert updated["used_source_refs"] == []
    assert updated["model_call"]["called"] is True
    assert updated["model_call"]["request_sent"] is True
    assert updated["model_call"]["usable_answer_received"] is True
    assert updated["model_call"]["unknown_answer"] is True
    assert updated["model_call"]["unknown_reason"] == "remote_release_receipt_missing"
    assert updated["answer_debug"]["final_answer"] == "UNKNOWN"


def test_dialog_entry_auto_policy_can_skip_evidence_bound_model_call(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in ["config_loader", "src.config_loader", "dialog_entry_proxy", "src.dialog_entry_proxy"]:
        sys.modules.pop(name, None)
    proxy = importlib.import_module("dialog_entry_proxy")

    monkeypatch.setattr(
        proxy,
        "run_evidence_bound_answer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("auto policy should skip short stable answer")),
    )
    result = {
        "status": "ok",
        "chain": "F3_zhiyi_direct",
        "answer": "NAS first",
        "zhiyi_context": {
            "matched_memories": [
                {
                    "exp_id": "exp-nas",
                    "summary": "NAS first",
                    "source_refs": {"source_system": "nas"},
                    "score": 0.9,
                }
            ],
        },
        "source_refs": [{"source_system": "nas"}],
        "recall_count": 1,
    }

    updated = proxy.maybe_run_zhiyi_live_model_call(
        {
            "model_call": {
                "enabled": True,
                "provider": "minimax",
                "confirm_live_model_call": True,
                "model": "MiniMax-M2",
                "call_policy": "auto",
                "debug": True,
            }
        },
        "What comes first?",
        result,
    )
    event = proxy.build_zhiyi_usage_log_event("What comes first?", updated, {})

    assert updated["answer"] == "NAS first"
    assert updated.get("answer_source") != "evidence_bound_model_call"
    assert updated["model_call"]["called"] is False
    assert updated["model_call"]["request_sent"] is False
    assert updated["model_call"]["model_gating_policy"] == "auto"
    assert updated["model_call"]["model_gating_reason"] == "auto_skip_short_stable_draft"
    assert updated["answer_debug"]["model_call"]["called"] is False
    assert updated["answer_debug"]["model_call"]["request_sent"] is False
    assert updated["answer_debug"]["model_call"]["gating_policy"] == "auto"
    assert updated["answer_debug"]["model_call"]["gating_reason"] == "auto_skip_short_stable_draft"
    assert updated["answer_debug"]["draft_answer"] == "NAS first"
    assert updated["answer_debug"]["final_answer"] == "NAS first"
    assert updated["answer_debug"]["raw_write_performed"] is False
    assert updated["answer_debug"]["memory_write_performed"] is False
    assert updated["answer_debug"]["platform_write_performed"] is False
    assert event["model_call"]["model_gating_policy"] == "auto"
    assert event["model_call"]["model_gating_reason"] == "auto_skip_short_stable_draft"


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
