#!/usr/bin/env python3
"""
Scope Enforcement Module
P9-System-B: B5

功能：在 recall 查询时强制 scope 边界过滤
约束：所有 recall 必须带有合法 scope，拒绝跨 scope 未授权访问
"""

import json
from pathlib import Path

# ─── Scope Normalizer (P9-System-C C1-Spec-Align) ──────
try:
    from src.scope_normalizer import get_scope_metadata, get_scope_string
    NORMALIZER_AVAILABLE = True
except Exception:
    NORMALIZER_AVAILABLE = False
    # Fallback: use existing scope string field
    def get_scope_metadata(obj):
        return {"canonical_window_id": obj.get("canonical_window_id", "")}
    def get_scope_string(obj):
        return obj.get("scope", "")
from typing import Optional
from src.config_loader import get_memcore_root

MEMCORE_ROOT = Path(get_memcore_root())
POLICY_FILE = MEMCORE_ROOT / "config" / "cross_agent_policy.json"
SCOPE_SCHEMA_FILE = MEMCORE_ROOT / "config" / "scope_schema.json"


def load_policy():
    with open(POLICY_FILE) as f:
        return json.load(f)


def load_scope_schema():
    with open(SCOPE_SCHEMA_FILE) as f:
        return json.load(f)


def get_default_scope() -> str:
    """返回默认 recall scope（window 级别）"""
    schema = load_scope_schema()
    return schema.get("default_isolation", "window")


def validate_scope(scope: dict) -> tuple[bool, Optional[str]]:
    """
    验证 scope 字典合法性。
    返回 (is_valid, error_message)
    """
    schema = load_scope_schema()
    required_fields = [k for k, v in schema["scope_fields"].items() if v.get("required")]

    for field in required_fields:
        if field not in scope or not scope[field]:
            return False, f"Missing required scope field: {field}"

    # canonical_window_id must be string
    if "canonical_window_id" in scope:
        if not isinstance(scope["canonical_window_id"], str):
            return False, "canonical_window_id must be string"

    # session_id must be string
    if "session_id" in scope:
        if not isinstance(scope["session_id"], str):
            return False, "session_id must be string"

    return True, None


def filter_by_scope(recall_results: list, request_scope: dict) -> list:
    """
    对 recall 结果做 scope 过滤。
    只返回与请求 scope 的 canonical_window_id 匹配的结果。
    支持三种格式：
    1. result.scope 字符串（"window/sg"）- 当前落地格式
    2. result.canonical_window_id 顶层字段 - 当前落地格式
    3. result.scope_metadata 嵌套对象 - 未来格式
    """
    if not recall_results:
        return []

    request_window = request_scope.get("canonical_window_id")
    if not request_window:
        # No window specified — return empty (must specify window)
        return []

    filtered = []
    for result in recall_results:
        # Use normalizer for compatibility across all formats
        if NORMALIZER_AVAILABLE:
            sm = get_scope_metadata(result)
            result_window = sm.get("canonical_window_id", "")
        else:
            # Fallback: use existing scope string field
            result_scope = result.get("scope", "")
            if isinstance(result_scope, str) and result_scope.startswith("window/"):
                result_window = result_scope.split("/", 1)[1]
            else:
                result_window = result.get("canonical_window_id", "")

        if result_window == request_window:
            filtered.append(result)

    return filtered


def check_cross_window_access(from_window: str, to_window: str, policy: dict) -> tuple[bool, str]:
    """
    检查跨 window 访问是否被允许。
    返回 (is_allowed, reason)
    """
    if from_window == to_window:
        return True, "same_window"

    # Different windows — check policy
    for rule in policy.get("rules", []):
        if rule.get("action") == "deny" and rule.get("require_explicit_grant"):
            return False, f"cross_window_denied: {rule.get('rule_id')}"

    return False, "cross_window_blocked_by_default_policy"


def build_scope_context(canonical_window_id: str, session_id: Optional[str] = None) -> dict:
    """
    根据 canonical_window_id 构建合法的 scope 上下文。
    """
    ctx = {
        "source_system": "openclaw",
        "computer_id": "local",
        "canonical_window_id": canonical_window_id,
    }
    if session_id:
        ctx["session_id"] = session_id
    return ctx


def enforce_scope_in_inject(inject_context: dict, request_scope: dict) -> dict:
    """
    在生成 inject prompt 之前，过滤掉不符合 scope 的记忆。
    """
    if "recall_result" not in inject_context:
        return inject_context

    original_recall = inject_context["recall_result"]
    filtered_recall = filter_by_scope(
        original_recall.get("matched_memories", []),
        request_scope
    )

    result = dict(inject_context)
    result["recall_result"] = dict(original_recall)
    result["recall_result"]["matched_memories"] = filtered_recall
    result["recall_result"]["returned"] = len(filtered_recall)
    result["recall_result"]["total_matched"] = len(filtered_recall)
    result["_scope_enforced"] = True
    result["_scope_used"] = request_scope

    return result


# Test
if __name__ == "__main__":
    print("Scope enforcement module loaded")
    print(f"Default scope: {get_default_scope()}")
    print(f"Policy loaded: {load_policy()['policy_version']}")
    print(f"Schema loaded: {load_scope_schema()['schema_version']}")

    # Test scope validation
    valid, err = validate_scope({
        "source_system": "openclaw",
        "computer_id": "local",
        "canonical_window_id": "sg",
        "session_id": "test-session"
    })
    print(f"Valid scope: {valid}, error: {err}")

    # Test scope filtering
    test_results = [
        {"type": "error_memory", "scope": "window/sg", "summary": "sg error"},
        {"type": "error_memory", "scope": "window/sy_agent", "summary": "sy_agent error"},
        {"type": "case_memory", "scope": "window/sg", "summary": "sg case"},
    ]
    filtered = filter_by_scope(test_results, {"canonical_window_id": "sg"})
    print(f"Filtered (sg only): {len(filtered)} results")
    for r in filtered:
        print(f"  - {r['scope']}: {r['summary']}")
