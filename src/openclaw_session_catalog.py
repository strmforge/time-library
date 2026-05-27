"""
openclaw_session_catalog.py
P9-System-H H1: Session Catalog - 只读扫描OpenClaw session列表，输出结构化信息

不写任何文件，不修改session状态。
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SESSION_KEYS_TO_EXCLUDE = {"gateway", "unknown", ""}
WINDOW_ID_INFERRED_FROM_KEY = True


def parse_session_key(key: str) -> dict:
    """
    解析 session key，提取结构化字段。
    格式: agent:<agent_id>:<session_id>
    或:   agent:<agent_id>:chat:<group_session_id>
    """
    parts = key.split(":")
    if len(parts) >= 3:
        if parts[2] == "chat":
            # group session: agent:group-example--main:chat:group-session-example-1776733674126
            return {
                "key": key,
                "agent_id": parts[1],
                "session_type": "group",
                "session_id": ":".join(parts[2:]),
                "canonical_window_id": parts[1],  # group agent id as window proxy
            }
        else:
            # direct session: agent:main:test-g6
            return {
                "key": key,
                "agent_id": parts[1],
                "session_type": "direct",
                "session_id": parts[2],
                "canonical_window_id": parts[1],
            }
    return {
        "key": key,
        "agent_id": "unknown",
        "session_type": "unknown",
        "session_id": key,
        "canonical_window_id": "unknown",
    }


def build_catalog() -> dict:
    from openclaw_ws_rpc_client import OpenClawWsRpcClient

    client = OpenClawWsRpcClient(max_retries=1)
    if not client.connect(timeout=5):
        return {"ok": False, "error": str(client.last_error)}

    result = client.sessions_list(timeout=5)
    client.close()

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error")}

    sessions = result.get("payload", {}).get("sessions", [])
    catalog_entries = []
    for s in sessions:
        key = s.get("key", "")
        if not key or key in SESSION_KEYS_TO_EXCLUDE:
            continue
        parsed = parse_session_key(key)
        entry = {
            "key": key,
            "agent_id": parsed["agent_id"],
            "session_type": parsed["session_type"],
            "canonical_window_id": parsed["canonical_window_id"],
            "mode": s.get("mode"),
            "updated_at_ms": s.get("updatedAtMs"),
        }
        catalog_entries.append(entry)

    catalog_entries.sort(key=lambda x: x.get("updated_at_ms") or 0, reverse=True)
    return {
        "ok": True,
        "catalog": catalog_entries,
        "total": len(catalog_entries),
        "inferred_window": WINDOW_ID_INFERRED_FROM_KEY,
    }


def print_catalog(catalog: dict):
    if not catalog.get("ok"):
        print(f"ERROR: {catalog.get('error')}")
        return
    entries = catalog.get("catalog", [])
    print(f"=== Session Catalog ({catalog.get('total')} sessions) ===")
    for e in entries:
        print(f"  [{e['session_type']:7}] key={e['key']}")
        print(f"           agent={e['agent_id']} window={e['canonical_window_id']}")


if __name__ == "__main__":
    catalog = build_catalog()
    print_catalog(catalog)
