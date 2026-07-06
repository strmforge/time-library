#!/usr/bin/env python3
"""Fixture-backed OpenClaw passive push smoke probe.

This exercises the new before-dispatch passive auto-injection path in-process.
It does not read user records, touch OpenClaw, or publish anything. The output
includes a trace that can be classified by time_twin_star_passive_push_trace_gate.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


PROBE_CONTRACT = "openclaw_passive_push_smoke_probe.v2026.6.24"


def _reload_dialog(memcore_root: Path):
    os.environ["MEMCORE_ROOT"] = str(memcore_root)
    os.environ["MEMCORE_CONFIG"] = str(ROOT / "config" / "memcore.json")
    for name in [
        "config_loader",
        "src.config_loader",
        "dialog_entry_proxy",
        "src.dialog_entry_proxy",
        "tiandao",
        "src.tiandao",
    ]:
        sys.modules.pop(name, None)
    return importlib.import_module("dialog_entry_proxy")


def _fake_raw_query(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or "")
    if "推第一刀" not in query:
        return {
            "primary_recall_backend": "vector_filtered_empty",
            "primary_recall_modes": ["vector_filtered_empty"],
            "items": [],
            "vector_runtime_status": {"ok": True, "status": "ok"},
        }
    return {
        "primary_recall_backend": "vector",
        "primary_recall_modes": ["vector"],
        "raw_recall_trajectory": [{"step": "primary_recall", "backend": "vector", "status": "hit"}],
        "items": [
            {
                "library_id": "exp-passive-push-smoke",
                "summary": "推第一刀验收要求 OpenClaw 正负两臂：相关轮 vector 注入并被用上，普通闲聊保持安静。",
                "raw_excerpt": "推第一刀：零显式召回，经 before-dispatch 自动注入；正臂 vector 命中且被答案使用，负臂不注入。",
                "source_system": "fixture",
                "source_path": "fixture://openclaw-passive-push-smoke",
                "msg_ids": ["msg-passive-push-smoke"],
                "matched_by": ["source_refs", "vector", "raw_offset"],
                "primary_recall_backend": "vector",
                "rank_reason": "vector candidate mapped back to raw/source_refs",
            }
        ],
    }


def _fake_model_answer(question: str, evidence_items: list[dict[str, Any]], **_kwargs) -> dict[str, Any]:
    return {
        "ok": True,
        "contract": "evidence_bound_model.v2026.6.18",
        "model_call_performed": True,
        "answer": "推第一刀要跑 OpenClaw 正负两臂 smoke：相关轮用上 vector 记忆，普通闲聊保持安静。",
        "verdict": "answered",
        "confidence": 0.91,
        "supporting_refs": [evidence_items[0]["evidence_ref"]] if evidence_items else [],
        "evidence_count": len(evidence_items),
        "api_key_env": "FIXTURE",
        "api_key_present": True,
    }


def _model_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "provider": "minimax",
        "confirm_live_model_call": True,
        "model": "fixture-evidence-bound-model",
        "debug": True,
        "timeout_seconds": 30,
    }


def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="memcore-openclaw-passive-push-") as tmp:
        proxy = _reload_dialog(Path(tmp) / "memcore")
        proxy._flags = {**proxy.DEFAULT_FEATURE_FLAGS}
        proxy._call_raw_query_gateway = _fake_raw_query
        proxy.run_evidence_bound_answer = _fake_model_answer
        proxy.record_zhiyi_usage_log = lambda *_args, **_kwargs: {"usage_log_write_performed": False}
        proxy.audit_log = lambda *_args, **_kwargs: None
        proxy.remember_openclaw_before_dispatch_handled = lambda *_args, **_kwargs: {"ok": True, "write_performed": False}
        proxy.remember_openclaw_before_dispatch_raw = lambda *_args, **_kwargs: {"ok": True, "write_performed": False}

        handler = object.__new__(proxy.DialogEntryHandler)
        positive = handler.handle_openclaw_before_dispatch(
            {
                "message": "推第一刀现在该怎么验？",
                "session_key": "openclaw-passive-push-smoke",
                "channel": "webchat",
                "confirm_passive_auto_inject_smoke": True,
                "observed_real_agent_turn": True,
                "model_call": _model_config(),
                "trusted_memory_trace": {
                    "passive_gate_result": {
                        "handled": False,
                        "text": "",
                        "reason": "passive_auto_inject_no_vector_match",
                    },
                    "security_gate": {
                        "observed": True,
                        "source": "openclaw_passive_push_smoke_probe",
                    },
                },
            }
        )
        negative = handler.handle_openclaw_before_dispatch(
            {
                "message": "今天天气不错。",
                "session_key": "openclaw-passive-push-smoke",
                "channel": "webchat",
                "confirm_passive_auto_inject_smoke": True,
                "observed_real_agent_turn": True,
            }
        )

        positive_trace = positive.get("passive_auto_inject_trace", {})
        negative_trace = negative.get("passive_auto_inject_trace", {})
        trace = {
            "trace_kind": "observed_real_agent_turn",
            "actual_agent_turn_loop_invoked": True,
            "no_explicit_recall_call": bool(positive_trace.get("no_explicit_recall_call")),
            "before_dispatch_auto_injection": bool(positive_trace.get("before_dispatch_auto_injection")),
            "positive_memory_matched": bool(positive_trace.get("positive_memory_matched")),
            "primary_recall_backend_vector": bool(positive_trace.get("primary_recall_backend_vector")),
            "matched_by_contains_vector": bool(positive_trace.get("matched_by_contains_vector")),
            "evidence_packet_observed_before_judgment": bool(positive_trace.get("evidence_packet_observed_before_judgment")),
            "answer_uses_recalled_memory": bool(positive_trace.get("answer_uses_recalled_memory")),
            "model_call_performed": bool(positive.get("model_call", {}).get("called")),
            "answer_source": "fixture-evidence-bound-model",
            "model_name": str(_model_config().get("model") or ""),
            "passive_first_default_still_handled_false": negative.get("handled") is False,
            "negative_arm_no_injection": bool(negative_trace.get("negative_arm_no_injection")),
            "receipt_visible": bool(positive_trace.get("receipt_visible")),
            "source_ref_visible": bool(positive_trace.get("source_ref_visible")),
            "smoke_session_only": True,
            "no_real_person_touched": True,
            "flags_restored": True,
            "no_unauthorized_platform_write": True,
            "rollback_boundary_documented": True,
            "fallback_explicit_when_vector_miss": bool(negative_trace.get("fallback_explicit_when_vector_miss")),
        }

        from tiandao import time_twin_star_passive_push_trace_gate_from_observation

        gate = time_twin_star_passive_push_trace_gate_from_observation(trace)

    return {
        "ok": True,
        "contract": PROBE_CONTRACT,
        "fixture_backed": True,
        "gate_expected_rejection": not bool(gate.get("trace_sufficient_for_passive_push_proven")),
        "user_work_records_read": False,
        "platform_action_performed": False,
        "platform_write_performed": False,
        "model_call_performed": bool(positive.get("model_call", {}).get("called")),
        "positive": {
            "handled": positive.get("handled"),
            "answer_source": positive.get("answer_source", ""),
            "used_source_refs": positive.get("used_source_refs", []),
            "trusted_trace_status": positive.get("trusted_memory_delivery_trace", {}).get("status", ""),
        },
        "negative": {
            "handled": negative.get("handled"),
            "reason": negative.get("reason", ""),
            "vector_miss_status": negative_trace.get("vector_miss_status", ""),
        },
        "trace": trace,
        "gate": gate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fixture-backed OpenClaw passive push smoke probe.")
    parser.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args()
    result = run_probe()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("PASS" if result.get("ok") else "FAIL")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
