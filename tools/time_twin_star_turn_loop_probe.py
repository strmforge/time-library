#!/usr/bin/env python3
"""Read-only Time Twin Star turn-loop probe.

This probe exercises the in-process OpenClaw before-dispatch entry shape. It is
not a real platform delivery proof and not a real agent behavior trace.
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


def _fixture_memory_direct(_message: str, _scope_filter: dict, audit: dict) -> dict[str, Any]:
    return {
        "status": "ok",
        "chain": "F3_zhiyi_direct",
        "answer": "时间双子星 turn-loop 探针：只读入口已到达，未证明真实行为改变。",
        "zhiyi_context": {
            "summary": "只读探针上下文。",
            "matched_memories": [
                {
                    "exp_id": "time-turn-loop-probe-fixture",
                    "summary": "只读探针上下文。",
                    "source_refs": {
                        "source_system": "fixture",
                        "source_path": "fixture://time-twin-star/turn-loop-probe",
                        "library_id": "time-turn-loop-probe-fixture",
                    },
                }
            ],
        },
        "source_refs": [
            {
                "source_system": "fixture",
                "source_path": "fixture://time-twin-star/turn-loop-probe",
                "library_id": "time-turn-loop-probe-fixture",
            }
        ],
        "raw_refs": [],
        "recall_count": 1,
        "audit": audit,
    }


def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="memcore-time-turn-loop-") as tmp:
        proxy = _reload_dialog(Path(tmp) / "memcore")
        from tiandao import (
            time_twin_star_turn_loop_definition_of_proven,
            time_twin_star_turn_loop_probe_from_observations,
        )

        writes = {
            "usage_log_write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "model_call_performed": False,
            "platform_action_performed": False,
            "openclaw_rpc_performed": False,
        }
        proxy._flags = {**proxy.DEFAULT_FEATURE_FLAGS, "zhiyi_direct": True}
        proxy.record_zhiyi_usage_log = lambda *_args, **_kwargs: {"usage_log_write_performed": False}
        proxy.audit_log = lambda *_args, **_kwargs: None
        proxy.remember_openclaw_before_dispatch_handled = (
            lambda *_args, **_kwargs: {"ok": True, "write_performed": False}
        )
        proxy.remember_openclaw_before_dispatch_raw = (
            lambda *_args, **_kwargs: {"ok": True, "write_performed": False}
        )
        handler = object.__new__(proxy.DialogEntryHandler)
        handler.handle_memory_direct = _fixture_memory_direct

        ordinary = handler.handle_openclaw_before_dispatch(
            {
                "message": "普通聊天必须默认放行，不由时间双子星抢答",
                "session_key": "time-turn-loop-probe",
                "channel": "webchat",
            }
        )
        explicit = handler.handle_openclaw_before_dispatch(
            {
                "message": "/zhiyi 时间双子星 turn-loop 探针",
                "session_key": "time-turn-loop-probe",
                "channel": "webchat",
            }
        )

        classification = time_twin_star_turn_loop_probe_from_observations(
            ordinary_result=ordinary,
            explicit_result=explicit,
            write_observations=writes,
        )
        definition = time_twin_star_turn_loop_definition_of_proven()

    return {
        "ok": bool(classification.get("ok")),
        "contract": classification.get("contract"),
        "turn_loop_probe_status": classification.get("turn_loop_probe_status"),
        "agent_turn_loop_status": classification.get("agent_turn_loop_status"),
        "turn_loop_behavior_status": classification.get("turn_loop_behavior_status"),
        "definition_of_proven": definition,
        "classification": classification,
        "fixture_backed": True,
        "installed_runtime_touched": False,
        "platform_action_performed": False,
        "model_call_performed": False,
        "user_work_records_read": False,
        "read_only": True,
        "write_performed": False,
        "ordinary": ordinary,
        "explicit": explicit,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the read-only Time Twin Star turn-loop probe.")
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
