#!/usr/bin/env python3
"""Context Budget Unit candidate helpers for Zhixing."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List

try:
    from dialog_intent_router import classify_fine_intent, ROUTE_CONTEXT_UNIT
except Exception:
    from src.dialog_intent_router import classify_fine_intent, ROUTE_CONTEXT_UNIT


CONTEXT_UNIT_VERSION = "2026.5.31"
UNIT_KINDS = [
    "raw_memory",
    "correction",
    "tool_fact",
    "method_signal",
    "work_experience",
    "context_snippet",
]
CONTEXT_SLOTS = [
    "identity_signal",
    "current_task",
    "preference_guardrail",
    "work_strategy",
    "tool_fact",
    "errata_warning",
    "method_candidate",
]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in ("", None):
        return []
    return [value]


def _string_list(value: Any) -> List[str]:
    return [_clean_text(item) for item in _as_list(value) if _clean_text(item)]


def _first_text(body: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean_text(body.get(key))
        if value:
            return value
    return ""


def _refs_from_body(body: Dict[str, Any]) -> Dict[str, Any]:
    refs = body.get("source_refs")
    if isinstance(refs, dict):
        return dict(refs)
    source = body.get("source") if isinstance(body.get("source"), dict) else {}
    refs = source.get("source_refs")
    if isinstance(refs, dict):
        return dict(refs)
    source_path = _clean_text(body.get("source_path") or source.get("path"))
    source_url = _clean_text(body.get("source_url") or source.get("url"))
    source_system = _clean_text(body.get("source_system") or source.get("system") or "unknown")
    out: Dict[str, Any] = {"source_system": source_system}
    if source_path:
        out["source_path"] = source_path
    if source_url:
        out["source_url"] = source_url
    return out if len(out) > 1 else {}


def _candidate_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"context-unit-{digest}"


def _infer_unit_kind(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["纠错", "勘误", "记错", "不对", "不是我的", "correction", "errata"]):
        return "correction"
    if any(token in lowered for token in ["工具", "端口", "安装", "配置", "platform", "tool", "runbook"]):
        return "tool_fact"
    if any(token in lowered for token in ["方法", "新方向", "method", "tianlu", "天箓"]):
        return "method_signal"
    if any(token in lowered for token in ["行策", "经验", "验收", "workflow", "work experience"]):
        return "work_experience"
    if any(token in lowered for token in ["raw", "原始", "原话", "source"]):
        return "raw_memory"
    return "context_snippet"


def _infer_context_slot(unit_kind: str, text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["我是忆凡尘", "identity", "记忆图书馆"]):
        return "identity_signal"
    if unit_kind == "correction":
        return "errata_warning"
    if unit_kind == "tool_fact":
        return "tool_fact"
    if unit_kind == "method_signal":
        return "method_candidate"
    if unit_kind == "work_experience":
        return "work_strategy"
    if any(token in lowered for token in ["偏好", "不要", "必须", "preference", "guardrail"]):
        return "preference_guardrail"
    return "current_task"


def _budget_from_body(body: Dict[str, Any], text: str) -> Dict[str, Any]:
    budget = body.get("budget") if isinstance(body.get("budget"), dict) else {}
    max_tokens = body.get("max_tokens") or budget.get("max_tokens") or 256
    try:
        max_tokens = int(max_tokens)
    except Exception:
        max_tokens = 256
    estimated_tokens = max(1, len(text) // 2) if text else 0
    return {
        "max_tokens": max_tokens,
        "estimated_tokens": estimated_tokens,
        "over_budget": estimated_tokens > max_tokens,
    }


def get_context_budget_unit_contract() -> Dict[str, Any]:
    """Return the read-only Context Budget Unit candidate contract."""
    return {
        "ok": True,
        "version": CONTEXT_UNIT_VERSION,
        "read_only": True,
        "write_performed": False,
        "candidate_type": "context_budget_unit_candidate",
        "endpoint": "/api/v1/zhixing/context-units/dry-run",
        "engineering_name": "Context Budget Unit",
        "zh_name": "上下文预算最小单元",
        "aka": ["粒子/离子方向待核验"],
        "required_fields": ["unit_text", "source_refs", "verbatim_excerpt", "objective_link"],
        "recommended_fields": [
            "unit_kind",
            "context_slot",
            "source_trust",
            "retrieval_trigger",
            "verification",
            "expiry_or_review_point",
            "composition",
        ],
        "unit_kinds": UNIT_KINDS,
        "context_slots": CONTEXT_SLOTS,
        "promotion_rule": "candidate_only_until_replay_or_benchmark_or_user_review",
        "raw_authority": True,
        "forbidden_by_default": [
            "compress_without_raw_excerpt",
            "merge_units_without_source_refs",
            "treat_context_unit_as_durable_memory",
            "write_platform_prompt_or_skill",
        ],
        "notes": [
            "this is a minimal composable context unit, not confirmed original user wording",
            "a unit can be recalled, composed, expired, or promoted only through separate gates",
            "context budget is a delivery constraint, not a truth score",
        ],
    }


def build_context_budget_unit_candidate(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a review-only context budget unit candidate."""
    body = body if isinstance(body, dict) else {}
    unit_text = _first_text(body, "unit_text", "text", "message", "signal", "query", "verbatim_excerpt")
    verbatim_excerpt = _first_text(body, "verbatim_excerpt", "raw_excerpt") or unit_text
    unit_kind = _first_text(body, "unit_kind", "kind") or _infer_unit_kind(" ".join([unit_text, verbatim_excerpt]))
    if unit_kind not in UNIT_KINDS:
        unit_kind = "context_snippet"
    context_slot = _first_text(body, "context_slot", "slot") or _infer_context_slot(unit_kind, unit_text)
    if context_slot not in CONTEXT_SLOTS:
        context_slot = "current_task"
    source_refs = _refs_from_body(body)
    objective_link = _first_text(body, "objective_link", "objective", "task_link")
    source_trust = _first_text(body, "source_trust", "trust") or ("source_backed" if source_refs else "unverified")
    retrieval_trigger = _string_list(body.get("retrieval_trigger") or body.get("triggers"))
    verification = _string_list(body.get("verification") or body.get("acceptance_checks"))
    composition = _string_list(body.get("composition") or body.get("composes_with"))
    expiry_or_review_point = _first_text(body, "expiry_or_review_point", "review_point", "expires_at") or "review_before_promotion"
    route = classify_fine_intent(unit_text)
    candidate_id = _candidate_id("|".join([unit_kind, context_slot, unit_text, str(source_refs)]))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidate = {
        "candidate_id": candidate_id,
        "candidate_type": "context_budget_unit_candidate",
        "schema_version": CONTEXT_UNIT_VERSION,
        "status": "candidate",
        "created_at": now_iso,
        "unit_kind": unit_kind,
        "context_slot": context_slot,
        "unit_text": unit_text,
        "source_refs": source_refs,
        "verbatim_excerpt": verbatim_excerpt,
        "objective_link": objective_link,
        "source_trust": source_trust,
        "representation": {
            "format": _first_text(body, "representation_format") or "plain_text",
            "text": unit_text,
            "summary_allowed": False,
            "requires_source_backing": True,
        },
        "budget": _budget_from_body(body, unit_text),
        "expiry_or_review_point": expiry_or_review_point,
        "retrieval_trigger": retrieval_trigger,
        "verification": verification,
        "composition": composition,
        "matched_intent": route,
        "recommended_action": "review_before_composition_or_promotion",
        "promotion_path": [
            "context_unit_candidate",
            "review_or_replay",
            "composed_context_or_shelf_candidate",
            "adopted_or_deprecated_or_superseded",
        ],
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "skill_write_performed": False,
        "platform_write_performed": False,
        "notes": [
            "candidate_only",
            "context_unit_is_not_durable_truth",
            "do_not_compress_without_source_refs_and_verbatim_excerpt",
        ],
    }
    missing = []
    if not unit_text:
        missing.append("unit_text")
    if not source_refs:
        missing.append("source_refs")
    if not verbatim_excerpt:
        missing.append("verbatim_excerpt")
    if not objective_link:
        missing.append("objective_link")
    return {
        "ok": not missing,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "candidate_created": not missing,
        "candidate": candidate if not missing else None,
        "candidate_id": candidate_id if not missing else "",
        "missing": missing,
        "contract": "context_budget_unit_candidate",
        "error": "invalid_context_budget_unit_candidate" if missing else "",
    }
