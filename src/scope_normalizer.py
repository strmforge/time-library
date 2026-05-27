#!/usr/bin/env python3
"""
scope normalizer

scope 读取统一入口：
1. 优先读取 obj.scope_metadata（嵌套对象，future API/UI format）
2. 若不存在，则从顶层字段组装：canonical_window_id / session_id / computer_id / source_system

所有读取 zhiyi 对象 scope 的代码应使用此 normalizer，
以保证当前格式（顶层字段）和未来格式（嵌套对象）兼容。
"""

import json
from typing import Optional, Dict, Any


def get_scope_metadata(obj: dict) -> dict:
    """
    统一获取 zhiyi 对象的 scope metadata。

    规则（按优先级）：
    1. 若顶层字段 canonical_window_id 存在，优先使用（当前落地格式）
    2. 若 scope_metadata 嵌套对象存在，使用嵌套对象（未来格式）
    3. 若 scope 字符串字段存在，解析 "window/<id>" 格式（兼容旧数据）
    4. 若都没有，返回全空 dict

    Returns:
        dict with keys: source_system, computer_id, canonical_window_id, session_id
    """
    # 优先1：使用顶层字段（当前落地格式）
    top_level_window = obj.get("canonical_window_id", "")
    if top_level_window:
        return {
            "source_system": obj.get("source_system", ""),
            "computer_id": obj.get("computer_id", ""),
            "canonical_window_id": top_level_window,
            "session_id": obj.get("session_id", ""),
        }

    # 回退2：嵌套 scope_metadata 对象（未来格式）
    if "scope_metadata" in obj and obj["scope_metadata"]:
        sm = obj["scope_metadata"]
        if isinstance(sm, str):
            try:
                sm = json.loads(sm)
            except (json.JSONDecodeError, TypeError):
                sm = {}
        if isinstance(sm, dict):
            return {
                "source_system": sm.get("source_system", ""),
                "computer_id": sm.get("computer_id", ""),
                "canonical_window_id": sm.get("canonical_window_id", ""),
                "session_id": sm.get("session_id", ""),
            }

    # 回退3：解析 scope 字符串字段 "window/<id>"（兼容旧数据）
    scope_str = obj.get("scope", "")
    if isinstance(scope_str, str) and scope_str.startswith("window/"):
        window_from_str = scope_str.split("/", 1)[1]
        if window_from_str:
            return {
                "source_system": "",
                "computer_id": "",
                "canonical_window_id": window_from_str,
                "session_id": "",
            }

    # 都没有
    return {
        "source_system": "",
        "computer_id": "",
        "canonical_window_id": "",
        "session_id": "",
    }


def get_scope_string(obj: dict) -> str:
    """
    获取 scope 字符串表示（window/<canonical_window_id>）。
    用于 filter_by_scope 等接受字符串格式的函数。
    """
    sm = get_scope_metadata(obj)
    window = sm.get("canonical_window_id", "")
    if window:
        return f"window/{window}"
    return ""


def has_valid_scope(obj: dict) -> bool:
    """检查对象是否有有效的 scope（canonical_window_id 非空）"""
    sm = get_scope_metadata(obj)
    return bool(sm.get("canonical_window_id"))


# Test
if __name__ == "__main__":
    # Test: 当前格式（顶层字段）
    obj_top_level = {
        "exp_id": "test",
        "canonical_window_id": "sg",
        "session_id": "sess-123",
        "computer_id": "local",
        "source_system": "openclaw",
        "scope": "window/sg",
    }
    sm = get_scope_metadata(obj_top_level)
    print("顶层字段格式:", sm)
    assert sm["canonical_window_id"] == "sg"
    assert sm["computer_id"] == "local"

    # Test: 未来格式（嵌套对象）
    obj_nested = {
        "exp_id": "test2",
        "scope_metadata": {
            "canonical_window_id": "sy_agent",
            "session_id": "sess-456",
            "computer_id": "local",
            "source_system": "openclaw",
        },
    }
    sm2 = get_scope_metadata(obj_nested)
    print("嵌套对象格式:", sm2)
    assert sm2["canonical_window_id"] == "sy_agent"

    # Test: 混合（顶层优先）
    obj_mixed = {
        "canonical_window_id": "sg",
        "scope_metadata": {"canonical_window_id": "sy_agent"},
    }
    sm3 = get_scope_metadata(obj_mixed)
    print("混合格式（顶层优先）:", sm3)
    assert sm3["canonical_window_id"] == "sg"  # 顶层优先

    # Test: scope 字符串
    print("scope 字符串:", get_scope_string(obj_top_level))
    assert get_scope_string(obj_top_level) == "window/sg"

    print("scope_normalizer: all tests passed ✅")
