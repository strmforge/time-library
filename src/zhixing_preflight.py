#!/usr/bin/env python3
"""
Read-only Zhiyi/Xingce preflight planner.

Preflight is the small proactive layer before an agent answers a task-like
prompt. It does not write memory, raw records, platform config, or skills. It
only turns already recalled source-backed items into a compact decision about
what should be surfaced before acting.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

try:
    from src.memcore_version import SERVICE_VERSION as PREFLIGHT_VERSION
except Exception:
    from memcore_version import SERVICE_VERSION as PREFLIGHT_VERSION
try:
    from src.evidence_bound_model import (
        EVIDENCE_BOUND_MODEL_CONTRACT,
        EVIDENCE_BOUND_MODEL_GATING_CONTRACT,
        default_model_config,
    )
except Exception:  # pragma: no cover - direct script import fallback
    try:
        from evidence_bound_model import (
            EVIDENCE_BOUND_MODEL_CONTRACT,
            EVIDENCE_BOUND_MODEL_GATING_CONTRACT,
            default_model_config,
        )
    except Exception:  # pragma: no cover - preflight can still run without model module
        EVIDENCE_BOUND_MODEL_CONTRACT = "evidence_bound_model.v2026.6.18"
        EVIDENCE_BOUND_MODEL_GATING_CONTRACT = "evidence_bound_model_gating.v2026.6.18"
        default_model_config = None


PREFLIGHT_CONTRACT = "zhixing_preflight.v2026.6.20"
AUTO_ENTRY_CONTRACT = "zhixing_auto_entry.v2026.6.20"
PREFLIGHT_ANSWER_DEBUG_CAPABILITY_CONTRACT = "preflight_answer_debug_capability.v2026.6.18"
DIALOG_ENTRY_ANSWER_DEBUG_CONTRACT = "dialog_entry_answer_debug.v2026.6.18"
MAX_SURFACE_ITEMS = 3
MAX_TEXT = 220
MIN_SURFACE_SCORE = 55
MIN_TASK_SURFACE_SCORE = 45
LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT = 6
LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT_POLICY = "soft_rank_signal_only_raw_evidence_required"

ZHIXING_SHELVES = {"zhiyi", "xingce", "toolbook", "errata"}

CONTINUATION_TERMS = {
    "继续",
    "接下来",
    "下一步",
    "还有",
    "然后呢",
    "还有吗",
    "之前",
    "上次",
    "已经",
    "完成",
    "没完成",
    "continue",
    "next",
    "what else",
    "then what",
    "already",
    "status",
}
ACTION_TERMS = {
    "做",
    "干",
    "开工",
    "推进",
    "修",
    "改",
    "测试",
    "验证",
    "发布",
    "安装",
    "同步",
    "部署",
    "fix",
    "run",
    "test",
    "verify",
    "release",
    "install",
    "deploy",
}
BOUNDARY_TERMS = {
    "边界",
    "定论",
    "不要",
    "不能",
    "不是",
    "错",
    "纠错",
    "误解",
    "忘了",
    "boundary",
    "decision",
    "do not",
    "don't",
    "wrong",
    "mistake",
    "forgot",
    "correction",
}
PREFERENCE_TERMS = {
    "偏好",
    "习惯",
    "要求",
    "我的想法",
    "我觉得",
    "为主",
    "preference",
    "habit",
    "requirement",
}
TRIVIAL_TERMS = {
    "ok",
    "好",
    "好的",
    "嗯",
    "收到",
    "谢谢",
    "thanks",
    "thank you",
    "hi",
    "hello",
    "hey",
}
STATUS_TERMS = {
    "状态",
    "进度",
    "完成了吗",
    "做到哪",
    "还剩",
    "status",
    "progress",
    "done",
    "left",
}
UNSAFE_TERMS = {
    "忽略之前",
    "忽略上面",
    "ignore previous",
    "ignore all previous",
    "泄露",
    "secret",
    "token",
    "password",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact(value: Any, limit: int = MAX_TEXT) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in ("", None):
        return []
    return [value]


def _terms_in(text: str, terms: Iterable[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def _normalized_query(query: str) -> str:
    return re.sub(r"\s+", " ", str(query or "")).strip()


def _answer_debug_capability() -> Dict[str, Any]:
    config = None
    if default_model_config:
        try:
            config = default_model_config()
        except Exception:
            config = None
    api_key_env = str(getattr(config, "api_key_env", "") or "")
    api_key_present = bool(getattr(config, "api_key_present", False))
    model_name = str(getattr(config, "model", "") or "")
    base_url_present = bool(str(getattr(config, "base_url", "") or ""))
    return {
        "contract": PREFLIGHT_ANSWER_DEBUG_CAPABILITY_CONTRACT,
        "available": True,
        "read_only": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "request_sent": False,
        "requires_explicit_answer_debug": True,
        "explicit_debug_flags": ["answer_debug=true", "model_call.debug=true"],
        "requires_confirm_live_model_call": True,
        "dialog_entry_answer_debug_contract": DIALOG_ENTRY_ANSWER_DEBUG_CONTRACT,
        "evidence_bound_model_contract": EVIDENCE_BOUND_MODEL_CONTRACT,
        "evidence_bound_model_gating_contract": EVIDENCE_BOUND_MODEL_GATING_CONTRACT,
        "default_model_call_policy": "auto",
        "supported_model_call_policies": ["auto", "always", "never"],
        "provider": str(getattr(config, "provider", "") or ""),
        "model_name": model_name,
        "base_url_present": base_url_present,
        "api_key_env": api_key_env,
        "api_key_present": api_key_present,
        "runtime_binding_ready": bool(api_key_present and model_name and base_url_present),
        "final_evidence_authority": "raw_source_refs",
        "draft_and_model_answer_policy": "not_evidence_without_supporting_refs",
    }


def classify_prompt(query: str) -> Dict[str, Any]:
    """Classify whether preflight should run before a task answer."""
    text = _normalized_query(query)
    lowered = text.lower()
    if not text:
        return {
            "prompt_class": "empty",
            "should_recall": False,
            "skip_reason": "empty_prompt",
        }
    if len(text) <= 12 and lowered in {term.lower() for term in TRIVIAL_TERMS}:
        return {
            "prompt_class": "trivial",
            "should_recall": False,
            "skip_reason": "trivial_prompt",
        }
    if _terms_in(text, UNSAFE_TERMS):
        return {
            "prompt_class": "unsafe",
            "should_recall": False,
            "skip_reason": "unsafe_or_secret_seeking_prompt",
        }
    if _terms_in(text, BOUNDARY_TERMS):
        return {"prompt_class": "correction", "should_recall": True, "skip_reason": ""}
    if _terms_in(text, CONTINUATION_TERMS):
        return {"prompt_class": "continuation", "should_recall": True, "skip_reason": ""}
    if _terms_in(text, STATUS_TERMS):
        return {"prompt_class": "status", "should_recall": True, "skip_reason": ""}
    if _terms_in(text, PREFERENCE_TERMS):
        return {"prompt_class": "preference", "should_recall": True, "skip_reason": ""}
    if _terms_in(text, ACTION_TERMS):
        return {"prompt_class": "task", "should_recall": True, "skip_reason": ""}
    return {
        "prompt_class": "ordinary",
        "should_recall": False,
        "skip_reason": "ordinary_prompt_without_memory_signal",
    }


def _card(item: Dict[str, Any]) -> Dict[str, Any]:
    card = item.get("library_card")
    return card if isinstance(card, dict) else {}


def _shelf(item: Dict[str, Any]) -> str:
    for value in (
        item.get("library_shelf"),
        _card(item).get("shelf"),
    ):
        text = str(value or "").strip().lower()
        if text:
            return text
    mtype = str(item.get("memory_type") or item.get("type") or "").strip().lower()
    if "xingce" in mtype:
        return "xingce"
    if "toolbook" in mtype or "project_status" in mtype:
        return "toolbook"
    if "errata" in mtype or "error" in mtype:
        return "errata"
    return "zhiyi"


def _item_text(item: Dict[str, Any]) -> str:
    card = _card(item)
    work = item.get("work_experience") if isinstance(item.get("work_experience"), dict) else {}
    parts = [
        item.get("summary"),
        item.get("raw_excerpt"),
        item.get("rank_reason"),
        item.get("type"),
        item.get("memory_type"),
        card.get("title"),
        card.get("summary"),
        work.get("work_scenario"),
        work.get("action_strategy"),
        work.get("avoid_conditions"),
        work.get("acceptance_checks"),
    ]
    return "\n".join(str(part or "") for part in parts)


def _work_experience(item: Dict[str, Any]) -> Dict[str, Any]:
    work = item.get("work_experience") if isinstance(item.get("work_experience"), dict) else {}
    if work:
        return work
    card_work = _card(item).get("work_experience")
    return card_work if isinstance(card_work, dict) else {}


def _uses_library_index_projection(item: Dict[str, Any]) -> bool:
    matched_by = item.get("matched_by") if isinstance(item.get("matched_by"), list) else []
    return bool(
        item.get("library_index_projection_used")
        or item.get("library_index_projection_kind")
        or "catalog_index" in matched_by
        or item.get("rank_reason") == "catalog_index"
    )


def _score_item_profile(item: Dict[str, Any], query: str) -> Dict[str, Any]:
    shelf = _shelf(item)
    text = _item_text(item)
    score = 0
    components: List[Dict[str, Any]] = []

    def add(name: str, value: int, reason: str) -> None:
        nonlocal score
        if value <= 0:
            return
        score += value
        components.append({"name": name, "value": value, "reason": reason})

    if shelf == "xingce":
        add("shelf", 55, "xingce action strategy")
    elif shelf == "toolbook":
        add("shelf", 45, "toolbook operational fact")
    elif shelf == "errata":
        add("shelf", 50, "errata or known mistake")
    elif shelf == "zhiyi":
        add("shelf", 35, "zhiyi user intent or preference")
    if item.get("source_path"):
        add("source_refs", 10, "source path available")
    if str(item.get("raw_evidence_status") or "").startswith("raw"):
        add("raw_evidence", 8, "raw evidence status is raw-like")
    if item.get("active_memory_layer") in {"current_window", "current_session"}:
        add("active_layer", 10, "current window/session")
    elif item.get("active_memory_layer"):
        add("active_layer", 5, "active memory layer")
    if query and query in text:
        add("query_match", 15, "query text matched item text")
    if _terms_in(query, ACTION_TERMS) and shelf in {"xingce", "toolbook"}:
        add("prompt_shelf_fit", 12, "action prompt fits xingce/toolbook")
    if _terms_in(query, BOUNDARY_TERMS) and shelf in {"zhiyi", "errata"}:
        add("prompt_shelf_fit", 12, "boundary prompt fits zhiyi/errata")
    if _terms_in(query, PREFERENCE_TERMS) and shelf == "zhiyi":
        add("prompt_shelf_fit", 10, "preference prompt fits zhiyi")
    base_score = score
    if _uses_library_index_projection(item):
        add(
            "library_index_projection",
            LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT,
            "navigation hint soft boost; final evidence still requires raw/source refs",
        )
    return {
        "score": score,
        "base_score": base_score,
        "components": components,
        "library_index_projection_soft_weight_applied": _uses_library_index_projection(item),
        "library_index_projection_soft_weight": (
            LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT
            if _uses_library_index_projection(item)
            else 0
        ),
        "library_index_projection_soft_weight_policy": LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT_POLICY,
    }


def _score_item(item: Dict[str, Any], query: str) -> int:
    return int(_score_item_profile(item, query).get("score") or 0)


def _score_profile_for_ranked(
    ranked: List[tuple[int, Dict[str, Any], Dict[str, Any]]],
    *,
    min_surface_score: int,
) -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    for score, item, profile in ranked[:MAX_SURFACE_ITEMS]:
        base_score = int(profile.get("base_score") or score)
        profiles.append({
            "library_id": item.get("library_id") or _card(item).get("library_id", ""),
            "library_shelf": _shelf(item),
            "score": score,
            "base_score": base_score,
            "surface_eligibility_score": base_score,
            "surface_eligible": base_score >= min_surface_score,
            "library_index_projection_soft_weight_applied": bool(
                profile.get("library_index_projection_soft_weight_applied")
            ),
            "library_index_projection_soft_weight": int(
                profile.get("library_index_projection_soft_weight") or 0
            ),
            "library_index_projection_soft_weight_policy": LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT_POLICY,
            "components": profile.get("components") or [],
        })
    return profiles


def _confidence_from_score(score: int) -> float:
    if score <= 0:
        return 0.0
    return round(min(0.99, score / 100.0), 2)


def _surface_threshold(prompt_class: str) -> int:
    if prompt_class in {"correction", "continuation", "status"}:
        return MIN_TASK_SURFACE_SCORE
    return MIN_SURFACE_SCORE


def _extract_avoid_markers(item: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    work = _work_experience(item)
    values.extend(str(value or "") for value in _as_list(work.get("avoid_conditions")))
    text = _item_text(item)
    patterns = [
        r"不要[^。；;\n]{1,80}",
        r"不能[^。；;\n]{1,80}",
        r"不要再[^。；;\n]{1,80}",
        r"避免[^。；;\n]{1,80}",
        r"do not [^.;\n]{1,80}",
        r"don't [^.;\n]{1,80}",
        r"avoid [^.;\n]{1,80}",
        r"must not [^.;\n]{1,80}",
    ]
    for pattern in patterns:
        values.extend(match.group(0) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    return _dedupe_compact(values, limit=6)


def _extract_acceptance_checks(item: Dict[str, Any]) -> List[str]:
    work = _work_experience(item)
    values = [str(value or "") for value in _as_list(work.get("acceptance_checks"))]
    text = _item_text(item)
    patterns = [
        r"验收[^。；;\n]{1,100}",
        r"检查[^。；;\n]{1,100}",
        r"验证[^。；;\n]{1,100}",
        r"acceptance check[^.;\n]{0,100}",
        r"verify [^.;\n]{1,100}",
        r"check [^.;\n]{1,100}",
    ]
    for pattern in patterns:
        values.extend(match.group(0) for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    return _dedupe_compact(values, limit=6)


def _dedupe_compact(values: Iterable[Any], *, limit: int) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        text = _compact(value, 160)
        key = text.lower()
        if not text or key in seen:
            continue
        result.append(text)
        seen.add(key)
        if len(result) >= limit:
            break
    return result


def _focus_from_items(query: str, items: List[Dict[str, Any]]) -> tuple[List[str], List[str]]:
    shelves = {_shelf(item) for item in items}
    zhiyi_focus: List[str] = []
    xingce_focus: List[str] = []
    if "zhiyi" in shelves:
        zhiyi_focus.append("source_backed_intent")
    if "errata" in shelves or _terms_in(query, BOUNDARY_TERMS):
        zhiyi_focus.append("correction_or_boundary")
        xingce_focus.append("avoid_old_mistake")
    if _terms_in(query, PREFERENCE_TERMS):
        zhiyi_focus.append("preference")
    if "xingce" in shelves:
        xingce_focus.append("action_strategy")
    if "toolbook" in shelves:
        xingce_focus.append("tool_fact")
    if _terms_in(query, ACTION_TERMS):
        xingce_focus.append("acceptance_checks")
    if _terms_in(query, CONTINUATION_TERMS):
        xingce_focus.append("continuation_state")
    return _dedupe_compact(zhiyi_focus, limit=5), _dedupe_compact(xingce_focus, limit=5)


def _surface_item(item: Dict[str, Any], score: int) -> Dict[str, Any]:
    card = _card(item)
    work = _work_experience(item)
    profile = _score_item_profile(item, "")
    return {
        "library_id": item.get("library_id") or card.get("library_id", ""),
        "library_shelf": _shelf(item),
        "title": _compact(card.get("title") or item.get("summary") or item.get("type"), 120),
        "summary": _compact(item.get("summary") or card.get("summary"), 220),
        "source_system": item.get("source_system", ""),
        "canonical_window_id": item.get("canonical_window_id", ""),
        "source_refs_canonical_window_id": item.get("source_refs_canonical_window_id", ""),
        "session_id": item.get("session_id", ""),
        "project_id": item.get("project_id", ""),
        "active_memory_layer": item.get("active_memory_layer", ""),
        "source_path": item.get("source_path", ""),
        "msg_ids": item.get("msg_ids") or [],
        "raw_evidence_status": item.get("raw_evidence_status", ""),
        "matched_by": item.get("matched_by") or [],
        "rank_reason": _compact(item.get("rank_reason"), 180),
        "why_surface": _compact(work.get("work_scenario") or card.get("shelf_label") or item.get("rank_reason"), 180),
        "score": score,
        "library_index_projection_soft_weight_applied": bool(
            profile.get("library_index_projection_soft_weight_applied")
        ),
        "library_index_projection_soft_weight": int(
            profile.get("library_index_projection_soft_weight") or 0
        ),
        "library_index_projection_soft_weight_policy": LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT_POLICY,
    }


def _auto_entry_triggered_by(
    *,
    prompt_class: str,
    query: str,
    top: List[tuple[int, Dict[str, Any]]],
    source_refs_count: int,
    raw_items_count: int,
) -> List[str]:
    triggers: List[str] = []
    if prompt_class:
        triggers.append(f"prompt:{prompt_class}")
    if _terms_in(query, CONTINUATION_TERMS):
        triggers.append("continuation_signal")
    if _terms_in(query, ACTION_TERMS):
        triggers.append("action_signal")
    if _terms_in(query, BOUNDARY_TERMS):
        triggers.append("boundary_or_correction_signal")
    if _terms_in(query, PREFERENCE_TERMS):
        triggers.append("preference_signal")
    for _, item in top:
        shelf = _shelf(item)
        if shelf:
            triggers.append(f"shelf:{shelf}")
        layer = str(item.get("active_memory_layer") or "").strip()
        if layer:
            triggers.append(f"layer:{layer}")
    if source_refs_count:
        triggers.append("source_refs_available")
    if raw_items_count:
        triggers.append("raw_evidence_available")
    return _dedupe_compact(triggers, limit=10)


def _auto_entry_plan(
    *,
    decision: str,
    prompt_class: str,
    query: str,
    should_surface: bool,
    proactive_required: bool,
    silence_reason: str,
    top: List[tuple[int, Dict[str, Any]]],
    source_refs_count: int,
    raw_items_count: int,
) -> Dict[str, Any]:
    """Translate preflight scoring into an explicit enter/retreat contract."""
    triggered_by = _auto_entry_triggered_by(
        prompt_class=prompt_class,
        query=query,
        top=top,
        source_refs_count=source_refs_count,
        raw_items_count=raw_items_count,
    )
    if decision == "surface" and should_surface:
        state = "enter"
        return {
            "auto_entry_contract": AUTO_ENTRY_CONTRACT,
            "auto_entry_state": state,
            "auto_entry_allowed": True,
            "auto_retreat_allowed": False,
            "auto_entry_reason": (
                "proactive_resurfacing_required"
                if proactive_required
                else "source_backed_surface_required"
            ),
            "auto_entry_triggered_by": triggered_by,
            "auto_retreat_reason": "",
            "context_delivery_mode": "compact_source_anchors",
            "next_action": "apply_must_surface_before_answer",
            "agent_instruction": (
                "Use must_surface, do_not_repeat, and acceptance_checks before answering; "
                "do not expose raw excerpts."
            ),
        }
    if decision == "scope_required":
        return {
            "auto_entry_contract": AUTO_ENTRY_CONTRACT,
            "auto_entry_state": "bind_required",
            "auto_entry_allowed": False,
            "auto_retreat_allowed": True,
            "auto_entry_reason": "scope_binding_or_permission_required",
            "auto_entry_triggered_by": triggered_by,
            "auto_retreat_reason": silence_reason or "scope_missing",
            "context_delivery_mode": "no_context_injection",
            "next_action": "report_binding_gap_without_claiming_memory_empty",
            "agent_instruction": (
                "Do not claim memory is empty; report the binding or permission gap "
                "if the answer depends on prior context."
            ),
        }
    if decision == "skip":
        return {
            "auto_entry_contract": AUTO_ENTRY_CONTRACT,
            "auto_entry_state": "skip",
            "auto_entry_allowed": False,
            "auto_retreat_allowed": True,
            "auto_entry_reason": "prompt_does_not_need_memory",
            "auto_entry_triggered_by": triggered_by,
            "auto_retreat_reason": silence_reason or "no_memory_signal",
            "context_delivery_mode": "no_context_injection",
            "next_action": "answer_normally_without_memory_preamble",
            "agent_instruction": "Proceed normally and do not mention memory.",
        }
    return {
        "auto_entry_contract": AUTO_ENTRY_CONTRACT,
        "auto_entry_state": "retreat",
        "auto_entry_allowed": False,
        "auto_retreat_allowed": True,
        "auto_entry_reason": "no_strong_source_backed_surface_rule",
        "auto_entry_triggered_by": triggered_by,
        "auto_retreat_reason": silence_reason or "silent",
        "context_delivery_mode": "no_context_injection",
        "next_action": "answer_normally_keep_uncertainty_if_prior_context_matters",
        "agent_instruction": (
            "Do not surface memory. Proceed normally; state uncertainty only if "
            "the task depends on prior context."
        ),
    }


def build_zhixing_preflight(
    query: str,
    *,
    recall_payload: Dict[str, Any] | None = None,
    consumer: str = "",
    request_id: str = "",
    prompt_override: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a compact, source-backed preflight decision from recall output."""
    recall_payload = recall_payload if isinstance(recall_payload, dict) else {}
    items = recall_payload.get("items") if isinstance(recall_payload.get("items"), list) else []
    query = _normalized_query(query)
    consumer = str(consumer or recall_payload.get("consumer") or "unknown")
    request_id = str(request_id or "")
    prompt = prompt_override if isinstance(prompt_override, dict) else classify_prompt(query)
    prompt_class = str(prompt.get("prompt_class") or "ordinary")
    should_recall = bool(prompt.get("should_recall"))
    scope_missing = bool(recall_payload.get("scope_missing"))
    scored_with_profiles = [
        (_score_item_profile(item, query), item)
        for item in items
        if isinstance(item, dict)
    ]
    scored = sorted(
        [(int(profile.get("score") or 0), item, profile) for profile, item in scored_with_profiles],
        key=lambda row: row[0],
        reverse=True,
    )
    top_score = scored[0][0] if scored else 0
    min_surface_score = _surface_threshold(prompt_class)
    confidence = _confidence_from_score(top_score)
    top = [
        (score, item)
        for score, item, profile in scored
        if int(profile.get("base_score") or score) >= min_surface_score
    ][:MAX_SURFACE_ITEMS]
    preflight_score_profile = _score_profile_for_ranked(
        scored,
        min_surface_score=min_surface_score,
    )
    shelves = {_shelf(item) for _, item in top}
    prompt_requires_memory = prompt_class in {"task", "continuation", "correction", "status", "preference"}
    should_surface = bool(top) and should_recall and (
        prompt_requires_memory
        or bool({"xingce", "toolbook", "errata"} & shelves)
    )
    zhiyi_focus, xingce_focus = _focus_from_items(query, [item for _, item in top])
    do_not_repeat: List[str] = []
    acceptance_checks: List[str] = []
    for _, item in top:
        do_not_repeat.extend(_extract_avoid_markers(item))
        acceptance_checks.extend(_extract_acceptance_checks(item))
    do_not_repeat = _dedupe_compact(do_not_repeat, limit=6)
    acceptance_checks = _dedupe_compact(acceptance_checks, limit=6)
    proactive_required = bool(
        should_surface and (
            {"xingce", "toolbook", "errata"} & shelves
            or "avoid_old_mistake" in xingce_focus
            or "continuation_state" in xingce_focus
        )
    )
    if not should_recall:
        decision = "skip"
        recall_status = f"preflight_skipped_{prompt.get('skip_reason') or 'no_memory_signal'}"
        reason = "preflight skipped because the prompt does not need source-backed memory"
        silence_reason = str(prompt.get("skip_reason") or "no_memory_signal")
    elif scope_missing:
        decision = "scope_required"
        recall_status = recall_payload.get("recall_status") or "scope_missing"
        reason = "preflight could not inspect memory because recall scope is not bound or not authorized"
        silence_reason = "scope_missing"
    elif should_surface:
        decision = "surface"
        recall_status = "preflight_surface_required"
        reason = "matched source-backed Zhiyi/Xingce evidence should be surfaced before answering"
        silence_reason = ""
    elif items:
        decision = "silent"
        recall_status = "preflight_evidence_available_no_forced_surface"
        reason = "memory exists but no strong proactive surfacing rule fired"
        silence_reason = "below_surface_threshold"
    else:
        decision = "silent"
        recall_status = "preflight_no_relevant_evidence"
        reason = "no relevant source-backed item was returned for this preflight"
        silence_reason = "no_relevant_evidence"
    source_refs_count = int(recall_payload.get("source_refs_count") or 0)
    raw_items_count = int(recall_payload.get("raw_items_count") or 0)
    recall_performed = bool(recall_payload.get("recall_performed", should_recall and not scope_missing))
    library_index_projection_refs = (
        recall_payload.get("library_index_projection_refs")
        if isinstance(recall_payload.get("library_index_projection_refs"), list)
        else []
    )
    raw_recall_trajectory = (
        recall_payload.get("raw_recall_trajectory")
        if isinstance(recall_payload.get("raw_recall_trajectory"), list)
        else []
    )
    auto_entry = _auto_entry_plan(
        decision=decision,
        prompt_class=prompt_class,
        query=query,
        should_surface=should_surface,
        proactive_required=proactive_required,
        silence_reason=silence_reason,
        top=top,
        source_refs_count=source_refs_count,
        raw_items_count=raw_items_count,
    )
    answer_debug_capability = _answer_debug_capability()
    return {
        "ok": True,
        "mode": "preflight",
        "version": PREFLIGHT_VERSION,
        "contract": PREFLIGHT_CONTRACT,
        **auto_entry,
        "created_at": _now(),
        "consumer": consumer,
        "request_id": request_id,
        "query": query,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "answer_debug_available": bool(answer_debug_capability.get("available")),
        "answer_debug_capability_contract": answer_debug_capability.get("contract", ""),
        "dialog_entry_answer_debug_contract": answer_debug_capability.get("dialog_entry_answer_debug_contract", ""),
        "evidence_bound_model_contract": answer_debug_capability.get("evidence_bound_model_contract", ""),
        "evidence_bound_model_gating_contract": answer_debug_capability.get("evidence_bound_model_gating_contract", ""),
        "answer_model_call_policy": answer_debug_capability.get("default_model_call_policy", ""),
        "answer_debug_capability": answer_debug_capability,
        "recall_performed": recall_performed,
        "raw_excerpt_returned": False,
        "decision": decision,
        "prompt_class": prompt_class,
        "confidence": confidence,
        "min_surface_score": min_surface_score,
        "top_score": top_score,
        "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
        "library_index_projection_soft_weight_policy": LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT_POLICY,
        "library_index_projection_soft_weight": LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT,
        "preflight_score_profile": preflight_score_profile,
        "silence_reason": silence_reason,
        "should_recall": should_recall,
        "should_surface": should_surface,
        "source_refs_required": True,
        "proactive_resurfacing_required": proactive_required,
        "zhiyi_focus": zhiyi_focus,
        "xingce_focus": xingce_focus,
        "must_surface": [_surface_item(item, score) for score, item in top] if should_surface else [],
        "do_not_repeat": do_not_repeat,
        "acceptance_checks": acceptance_checks,
        "recall_status": recall_status,
        "reason": reason,
        "memory_scope": recall_payload.get("memory_scope", ""),
        "memory_base_scope": recall_payload.get("memory_base_scope", ""),
        "scope_missing": scope_missing,
        "missing_scope_fields": recall_payload.get("missing_scope_fields") or [],
        "cross_window_read": bool(recall_payload.get("cross_window_read", False)),
        "cross_window_read_allowed": bool(recall_payload.get("cross_window_read_allowed", True)),
        "active_layers_used": recall_payload.get("active_layers_used") or [],
        "matched_count": int(recall_payload.get("matched_count") or len(items)),
        "source_refs_count": source_refs_count,
        "raw_items_count": raw_items_count,
        "raw_evidence_status": "raw" if raw_items_count else "not_raw",
        "raw_recall_trajectory_contract": recall_payload.get("raw_recall_trajectory_contract", ""),
        "raw_recall_trajectory_policy": recall_payload.get("raw_recall_trajectory_policy", ""),
        "raw_recall_trajectory": raw_recall_trajectory,
        "library_index_projection_contract": recall_payload.get("library_index_projection_contract", ""),
        "library_index_projection_policy": recall_payload.get("library_index_projection_policy", ""),
        "library_index_projection_used": bool(recall_payload.get("library_index_projection_used", False)),
        "library_index_projection_refs_count": int(recall_payload.get("library_index_projection_refs_count") or 0),
        "library_index_projection_refs": library_index_projection_refs,
        "context_bundle_contract": recall_payload.get("context_bundle_contract", ""),
        "context_bundle_policy": recall_payload.get("context_bundle_policy", ""),
        "context_bundle_window": recall_payload.get("context_bundle_window", 0),
        "context_bundle_items_count": int(recall_payload.get("context_bundle_items_count") or 0),
        "context_bundle_refs_count": int(recall_payload.get("context_bundle_refs_count") or 0),
        "context_bundle_status_counts": recall_payload.get("context_bundle_status_counts") or {},
        "consumer_receipt": {
            "consumer": consumer,
            "request_id": request_id,
            "consumed_at": _now(),
            "read_only": True,
            "write_performed": False,
            "platform_write_performed": False,
            "skill_write": False,
            "memory_write": False,
            "config_write": False,
            "items_count": len(top) if should_surface else 0,
            "source_refs_count": source_refs_count,
            "raw_items_count": raw_items_count,
            "receipt_scope": "zhixing_preflight_read_only",
            "library_index_projection_used": bool(recall_payload.get("library_index_projection_used", False)),
            "library_index_projection_refs_count": int(recall_payload.get("library_index_projection_refs_count") or 0),
            "library_index_projection_policy": recall_payload.get("library_index_projection_policy", ""),
            "library_index_projection_soft_weight_policy": LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT_POLICY,
            "library_index_projection_soft_weight": LIBRARY_INDEX_PROJECTION_SOFT_WEIGHT,
            "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
            "raw_recall_trajectory_contract": recall_payload.get("raw_recall_trajectory_contract", ""),
            "raw_recall_trajectory_policy": recall_payload.get("raw_recall_trajectory_policy", ""),
            "answer_debug_available": bool(answer_debug_capability.get("available")),
            "answer_debug_capability_contract": answer_debug_capability.get("contract", ""),
            "dialog_entry_answer_debug_contract": answer_debug_capability.get("dialog_entry_answer_debug_contract", ""),
            "evidence_bound_model_contract": answer_debug_capability.get("evidence_bound_model_contract", ""),
            "evidence_bound_model_gating_contract": answer_debug_capability.get("evidence_bound_model_gating_contract", ""),
            "answer_model_call_policy": answer_debug_capability.get("default_model_call_policy", ""),
            "used_library_ids": [
                surface.get("library_id")
                for surface in [_surface_item(item, score) for score, item in top]
                if should_surface and surface.get("library_id")
            ],
        },
    }
