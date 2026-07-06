#!/usr/bin/env python3
"""Repeatable real-memory-safe trusted-memory live trace probe.

This probe writes non-sensitive case-memory records into a temporary
MEMCORE_ROOT, serves the normal /inject gateway against that temporary root,
and exercises the same before-dispatch style answer path as the product code.
It does not read the user's real Zhiyi/Xingce records and does not perform
platform actions.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import HTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _reset_modules() -> None:
    for name in [
        "config_loader",
        "src.config_loader",
        "p3_recall",
        "src.p3_recall",
        "p4_provider",
        "src.p4_provider",
        "dialog_entry_proxy",
        "src.dialog_entry_proxy",
    ]:
        sys.modules.pop(name, None)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )


def _prepare_temp_memory(memcore_root: Path) -> dict[str, Any]:
    raw_dir = memcore_root / "memory" / "trusted_memory_probe" / "local" / "trusted-memory-real-trace"
    source_raw_path = raw_dir / "source-backed.jsonl"
    unknown_raw_path = raw_dir / "unknown-gap.jsonl"
    source_raw_path.parent.mkdir(parents=True, exist_ok=True)
    source_raw_path.write_text(
        json.dumps(
            {
                "id": "raw-real-trace-next",
                "text": "根据这条受控测试记录，下一步是先核对 NAS，再实施下一刀。",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    unknown_raw_path.write_text(
        json.dumps(
            {
                "id": "raw-real-trace-gap",
                "text": "这条受控测试记录只说明用户偏好证据优先；没有远端发布回执。",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    records = [
        {
            "exp_id": "exp-real-trace-next",
            "type": "case_memory",
            "summary": "真实记忆安全探针：下一步是先核对 NAS，再实施下一刀。",
            "detail": "根据这条受控非敏感记忆记录，下一步是先核对 NAS，再实施下一刀。",
            "scope": "window/trusted-real-trace-next",
            "score": 0.95,
            "lifecycle_version": 1,
            "source_refs": {
                "source_system": "trusted_memory_probe",
                "source_path": str(source_raw_path),
                "library_id": "exp-real-trace-next",
                "canonical_window_id": "trusted-real-trace-next",
                "session_id": "trusted-real-trace-source-backed",
                "msg_ids": ["raw-real-trace-next"],
            },
        },
        {
            "exp_id": "exp-real-trace-gap",
            "type": "case_memory",
            "summary": "真实记忆安全探针：只有本地偏好证据，没有远端发布回执。",
            "detail": "这条受控非敏感记忆记录只说明用户偏好证据优先；没有远端发布回执。",
            "scope": "window/trusted-real-trace-gap",
            "score": 0.95,
            "lifecycle_version": 1,
            "source_refs": {
                "source_system": "trusted_memory_probe",
                "source_path": str(unknown_raw_path),
                "library_id": "exp-real-trace-gap",
                "canonical_window_id": "trusted-real-trace-gap",
                "session_id": "trusted-real-trace-unknown",
                "msg_ids": ["raw-real-trace-gap"],
            },
        },
    ]
    _write_jsonl(memcore_root / "zhiyi" / "case_memory" / "case_memory.jsonl", records)
    return {
        "inserted_case_memory_count": len(records),
        "zhiyi_path": str(memcore_root / "zhiyi" / "case_memory" / "case_memory.jsonl"),
        "raw_paths": [str(source_raw_path), str(unknown_raw_path)],
        "exp_ids": [record["exp_id"] for record in records],
    }


def _load_with_temp_memory(memcore_root: Path, gateway_port: int):
    os.environ["MEMCORE_ROOT"] = str(memcore_root)
    os.environ["MEMCORE_CONFIG"] = str(ROOT / "config" / "memcore.json")
    os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(memcore_root / "zhiyi")
    _reset_modules()
    p3 = importlib.import_module("src.p3_recall")
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    p4 = importlib.import_module("src.p4_provider")
    proxy = importlib.import_module("dialog_entry_proxy")
    proxy.ZHIYI_GATEWAY_URL = f"http://127.0.0.1:{gateway_port}/inject"
    proxy.ZHIYI_GATEWAY_TIMEOUT = 5
    return p3, p4, proxy


class _Gateway:
    def __init__(self, handler, port: int):
        self.server = HTTPServer(("127.0.0.1", port), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _run_case(handler: Any, case: str) -> dict[str, Any]:
    ordinary = handler.handle_openclaw_before_dispatch(
        {
            "message": f"ordinary chat for real-memory {case} must pass through",
            "session_key": f"trusted-real-trace-{case}",
            "channel": "webchat",
        }
    )
    if case == "unknown":
        message = "/zhiyi 真实记忆安全探针：远端发布已经完成了吗？"
        scope_filter = "trusted-real-trace-gap"
    else:
        message = "/zhiyi 真实记忆安全探针：下一步是什么？"
        scope_filter = "trusted-real-trace-next"
    observations = {
        "passive_gate_result": ordinary,
        "security_gate": {
            "observed": True,
            "source": "trusted_memory_real_memory_trace_probe",
            "tests": ["tests/test_security_boundaries.py", "tests/test_trusted_memory_delivery_trace.py"],
        },
    }
    result = handler.handle_openclaw_before_dispatch(
        {
            "message": message,
            "session_key": f"trusted-real-trace-{case}",
            "channel": "webchat",
            "scope_filter": scope_filter,
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
        "recall_count": result.get("recall_count", 0),
        "model_called": model_call.get("called"),
        "request_sent": model_call.get("request_sent"),
        "model_verdict": model_call.get("model_verdict"),
        "model_validation_error": model_call.get("model_validation_error"),
        "unknown_reason": model_call.get("unknown_reason", ""),
        "evidence_packet_refs": model_call.get("evidence_packet_refs", []),
        "used_source_refs": result.get("used_source_refs", []),
        "source_refs": result.get("source_refs", []),
        "receipt_status": result.get("delivery_receipt_view", {}).get("status", ""),
        "unknown_boundary": result.get("delivery_receipt_view", {}).get("unknown_boundary", False),
        "trace_status": trace.get("status"),
        "model_delivery_state": trace.get("model_delivery_state"),
        "missing_cells": trace.get("missing_cells", []),
        "cells": trace.get("cells", {}),
    }


def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="memcore-trusted-real-memory-") as tmp:
        memcore_root = Path(tmp) / "memcore"
        fixture = _prepare_temp_memory(memcore_root)
        port = _free_loopback_port()
        p3, p4, proxy = _load_with_temp_memory(memcore_root, port)
        proxy._flags = {**proxy.DEFAULT_FEATURE_FLAGS, "zhiyi_direct": True}
        proxy.record_zhiyi_usage_log = lambda *_args, **_kwargs: {"usage_log_write_performed": False}
        proxy.audit_log = lambda *_args, **_kwargs: None
        proxy.remember_openclaw_before_dispatch_handled = lambda *_args, **_kwargs: {"ok": True, "write_performed": False}
        proxy.remember_openclaw_before_dispatch_raw = lambda *_args, **_kwargs: {"ok": True, "write_performed": False}
        handler = object.__new__(proxy.DialogEntryHandler)
        with _Gateway(p4.Handler, port):
            cases = [_run_case(handler, "source_backed"), _run_case(handler, "unknown")]
            health_count = len(p3.get_memories())

    by_case = {item.get("case"): item for item in cases}
    source_case = by_case.get("source_backed", {})
    unknown_case = by_case.get("unknown", {})
    ok = all(
        item.get("ordinary_handled") is False
        and item.get("explicit_handled") is True
        and item.get("recall_count", 0) > 0
        and item.get("trace_status") == "proven"
        and item.get("model_delivery_state") == "observed"
        and not item.get("missing_cells")
        for item in cases
    )
    ok = ok and source_case.get("used_source_refs") == ["exp-real-trace-next"]
    ok = ok and unknown_case.get("answer") == "UNKNOWN" and bool(unknown_case.get("unknown_boundary"))
    ok = ok and health_count >= fixture["inserted_case_memory_count"]
    return {
        "ok": ok,
        "contract": "trusted_memory_real_memory_trace_probe.v2026.6.21",
        "fixture_backed": False,
        "controlled_temp_memory": True,
        "user_work_records_read": False,
        "platform_action_performed": False,
        "temporary_gateway": True,
        "inserted_case_memory_count": fixture["inserted_case_memory_count"],
        "loaded_memory_count": health_count,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real-memory-safe trusted memory live trace probe.")
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
