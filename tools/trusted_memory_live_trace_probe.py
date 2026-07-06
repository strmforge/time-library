#!/usr/bin/env python3
"""Repeatable fixture-backed trusted-memory live trace probe.

The probe exercises the same dialog before-dispatch style answer path used by
the product code. It does not read the user's real Zhiyi/Xingce records and
does not deliver platform actions. It verifies two cases: source-backed answer
and evidence-bound UNKNOWN.
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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from src.trusted_memory_delivery_trace import build_trusted_memory_delivery_artifacts
except Exception:  # pragma: no cover - direct script import fallback
    from trusted_memory_delivery_trace import build_trusted_memory_delivery_artifacts


def _model_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "provider": "minimax",
        "confirm_live_model_call": True,
        "model": os.environ.get("MINIMAX_MODEL") or os.environ.get("MINIMAX_CN_MODEL") or "MiniMax-M2.7-highspeed",
        "debug": True,
        "timeout_seconds": 90,
    }


def _reload_dialog(memcore_root: Path):
    os.environ["MEMCORE_ROOT"] = str(memcore_root)
    os.environ["MEMCORE_CONFIG"] = str(ROOT / "config" / "memcore.json")
    for name in ["config_loader", "src.config_loader", "dialog_entry_proxy", "src.dialog_entry_proxy"]:
        sys.modules.pop(name, None)
    return importlib.import_module("dialog_entry_proxy")


def _fixture_memory(case: str, audit: dict[str, Any]) -> dict[str, Any]:
    if case == "unknown":
        summary = "这条测试证据只说明：用户喜欢证据优先的记忆系统。没有说明远端发布是否完成。"
        exp_id = "exp-live-trace-gap"
        source_path = "fixture://trusted-memory/live-trace-gap"
    else:
        summary = "根据这条测试证据，下一步是先核对 NAS，再实施下一刀。"
        exp_id = "exp-live-trace-next"
        source_path = "fixture://trusted-memory/live-trace"
    return {
        "status": "ok",
        "chain": "F3_zhiyi_direct",
        "answer": "旧草案",
        "zhiyi_context": {
            "matched_memories": [
                {
                    "exp_id": exp_id,
                    "summary": summary,
                    "source_refs": {
                        "source_system": "trusted_trace_fixture",
                        "source_path": source_path,
                        "library_id": exp_id,
                    },
                    "score": 0.99,
                }
            ],
        },
        "source_refs": [
            {
                "source_system": "trusted_trace_fixture",
                "source_path": source_path,
                "library_id": exp_id,
            }
        ],
        "recall_count": 1,
        "audit": audit,
    }


def _run_case(handler: Any, proxy: Any, case: str) -> dict[str, Any]:
    def fixture_memory_direct(_message, _scope_filter, audit):
        return _fixture_memory(case, audit)

    handler.handle_memory_direct = fixture_memory_direct
    ordinary = handler.handle_openclaw_before_dispatch(
        {
            "message": f"ordinary chat for {case} must pass through",
            "session_key": f"trusted-trace-{case}",
            "channel": "webchat",
        }
    )
    if case == "unknown":
        message = "/zhiyi 根据证据，远端发布已经完成了吗？"
    else:
        message = "/zhiyi 根据证据，下一步是什么？"
    observations = {
        "passive_gate_result": ordinary,
        "security_gate": {
            "observed": True,
            "source": "trusted_memory_live_trace_probe",
            "tests": ["tests/test_security_boundaries.py", "tests/test_trusted_memory_delivery_trace.py"],
        },
    }
    result = handler.handle_openclaw_before_dispatch(
        {
            "message": message,
            "session_key": f"trusted-trace-{case}",
            "channel": "webchat",
            "model_call": _model_config(),
            "trusted_memory_trace": observations,
        }
    )
    if not isinstance(result.get("trusted_memory_delivery_trace"), dict):
        artifacts = build_trusted_memory_delivery_artifacts(
            platform="openclaw",
            question=message,
            dialog_result=result,
            observations=observations,
        )
        result = {**result, **artifacts}
    trace = result.get("trusted_memory_delivery_trace", {})
    model_call = result.get("model_call", {})
    return {
        "case": case,
        "ordinary_handled": ordinary.get("handled"),
        "ordinary_reason": ordinary.get("reason"),
        "explicit_handled": result.get("handled"),
        "answer": result.get("answer", ""),
        "answer_source": result.get("answer_source", ""),
        "model_called": model_call.get("called"),
        "request_sent": model_call.get("request_sent"),
        "model_verdict": model_call.get("model_verdict"),
        "model_validation_error": model_call.get("model_validation_error"),
        "unknown_reason": model_call.get("unknown_reason", ""),
        "evidence_packet_refs": model_call.get("evidence_packet_refs", []),
        "used_source_refs": result.get("used_source_refs", []),
        "receipt_status": result.get("delivery_receipt_view", {}).get("status", ""),
        "unknown_boundary": result.get("delivery_receipt_view", {}).get("unknown_boundary", False),
        "trace_status": trace.get("status"),
        "model_delivery_state": trace.get("model_delivery_state"),
        "missing_cells": trace.get("missing_cells", []),
        "cells": trace.get("cells", {}),
    }


def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="memcore-trusted-trace-") as tmp:
        proxy = _reload_dialog(Path(tmp) / "memcore")
        proxy._flags = {**proxy.DEFAULT_FEATURE_FLAGS, "zhiyi_direct": True}
        proxy.record_zhiyi_usage_log = lambda *_args, **_kwargs: {"usage_log_write_performed": False}
        proxy.audit_log = lambda *_args, **_kwargs: None
        proxy.remember_openclaw_before_dispatch_handled = lambda *_args, **_kwargs: {"ok": True, "write_performed": False}
        proxy.remember_openclaw_before_dispatch_raw = lambda *_args, **_kwargs: {"ok": True, "write_performed": False}
        handler = object.__new__(proxy.DialogEntryHandler)
        cases = [_run_case(handler, proxy, "source_backed"), _run_case(handler, proxy, "unknown")]
    ok = all(
        item.get("ordinary_handled") is False
        and item.get("explicit_handled") is True
        and item.get("trace_status") == "proven"
        and item.get("model_delivery_state") == "observed"
        and not item.get("missing_cells")
        for item in cases
    )
    unknown = next(item for item in cases if item["case"] == "unknown")
    ok = ok and unknown.get("answer") == "UNKNOWN" and bool(unknown.get("unknown_boundary"))
    return {
        "ok": ok,
        "contract": "trusted_memory_live_trace_probe.v2026.6.21",
        "fixture_backed": True,
        "user_work_records_read": False,
        "platform_action_performed": False,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fixture-backed trusted memory live trace probe.")
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
