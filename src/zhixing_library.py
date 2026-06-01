#!/usr/bin/env python3
"""
Zhixing library helpers.

Raw records remain the source text. This module only adds library-style
classification, stable ids, typed edges, and explainable recall metadata for
Zhiyi and Xingce consumers.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


LIBRARY_VERSION = "2026.6.1"
ZHIXING_SHELVES = {
    "raw": "Original source records and direct raw excerpts.",
    "zhiyi": "Preference, intent, wording, correction, and user-understanding experience.",
    "xingce": "Work experience, action strategy, validation paths, and project gotchas.",
    "toolbook": "Operational notes about platforms, tools, environment, setup, and runbooks.",
    "errata": "Deprecated, superseded, conflicting, or invalidated library records.",
}
EXPERIENCE_STATUSES = ["candidate", "pending_review", "adopted", "deprecated", "superseded"]
NODE_TYPES = ["user", "project", "platform", "task", "preference", "work_experience", "tool"]
EDGE_TYPES = ["belongs_to", "caused_by", "fixed_by", "blocked_by", "supersedes", "uses_preference"]
TOOLBOOK_RAW_SOURCES = {
    "external_docs": "raw/external_docs/",
    "probe_logs": "raw/probe_logs/",
}
ZHIXING_LOOP_STEPS = [
    {
        "id": "preserve_raw",
        "order": 1,
        "shelf": "raw",
        "name": "Preserve raw source text",
        "zh_name": "原样保存",
        "required_evidence": ["source_refs", "verbatim_excerpt"],
    },
    {
        "id": "zhiyi_source_backed_recall",
        "order": 2,
        "shelf": "zhiyi",
        "name": "Return to source-backed Zhiyi evidence",
        "zh_name": "知意回源",
        "required_evidence": ["library_id", "source_refs", "verbatim_excerpt"],
    },
    {
        "id": "xingce_work_experience",
        "order": 3,
        "shelf": "xingce",
        "name": "Shape work experience and action strategy",
        "zh_name": "行策沉淀",
        "required_evidence": ["work_scenario", "action_strategy", "acceptance_checks"],
    },
    {
        "id": "toolbook_platform_facts",
        "order": 4,
        "shelf": "toolbook",
        "name": "Add toolbook facts from docs or probes",
        "zh_name": "工具书补事实",
        "required_evidence": ["toolbook_raw_source", "observed_behavior", "environment"],
    },
    {
        "id": "errata_conflict_handling",
        "order": 5,
        "shelf": "errata",
        "name": "Handle conflicts, deprecations, and supersession",
        "zh_name": "勘误处理冲突",
        "required_evidence": ["status", "supersedes", "conflicts_with"],
    },
    {
        "id": "replay_validation",
        "order": 6,
        "shelf": "evaluation",
        "name": "Replay the same task across memory modes",
        "zh_name": "Replay 验证",
        "required_evidence": ["deterministic_metrics", "comparison_sets"],
    },
    {
        "id": "feed_next_recall_or_action",
        "order": 7,
        "shelf": "delivery",
        "name": "Feed validated experience into later recall or action",
        "zh_name": "反哺召回 / 行动",
        "required_evidence": ["usage_receipt", "rank_reason", "proactive_resurfacing"],
    },
]
FLIGHT_METRICS = [
    {
        "id": "fewer_repeated_questions",
        "kind": "defense",
        "zh_name": "少问重复问题",
        "description": "The agent should not ask again for context that source-backed memory already provides.",
    },
    {
        "id": "fewer_repeated_mistakes",
        "kind": "defense",
        "zh_name": "少踩旧坑",
        "description": "The agent should avoid mistakes already documented in prior work experience.",
    },
    {
        "id": "user_habit_followed",
        "kind": "defense",
        "zh_name": "按用户习惯推进",
        "description": "The agent should follow known user preferences and correction history.",
    },
    {
        "id": "source_backed_answer_rate",
        "kind": "defense",
        "zh_name": "能回到原话出处",
        "description": "Important claims should point back to source refs or state that source text is unavailable.",
    },
    {
        "id": "proactive_resurfacing",
        "kind": "offense",
        "zh_name": "主动浮现过去做对过的东西",
        "description": "The agent should surface a relevant prior successful pattern even when the user did not explicitly ask for it.",
    },
]
REPLAY_COMPARISON_SETS = ["no_memory", "zhiyi_only", "zhiyi_plus_xingce"]
BENCHMARK_REQUIRED_CASE_FIELDS = [
    "case_id",
    "query",
    "expected_source_refs",
    "expected_behavior_markers",
    "forbidden_repeated_mistakes",
    "required_acceptance_checks",
    "expected_proactive_resurfacing",
]


def _compact_text(value: Any, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "..."


def _slug(value: Any, limit: int = 48) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return (text or "toolbook")[:limit].strip("-") or "toolbook"


def _parse_refs(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in ("", None):
        return []
    return [value]


def memory_type(record: dict) -> str:
    return str(record.get("type") or record.get("_type") or record.get("memory_type") or "memory").strip() or "memory"


def _stable_seed(record: dict) -> str:
    refs = _parse_refs(record.get("_source_refs") or record.get("source_refs") or {})
    parts = [
        memory_type(record),
        str(record.get("exp_id") or record.get("memory_id") or ""),
        str(record.get("summary") or ""),
        str(record.get("detail") or ""),
        str(refs.get("source_path") or ""),
        str(refs.get("session_id") or ""),
    ]
    return "|".join(parts)


def library_id_for(record: dict) -> str:
    existing = str(record.get("library_id") or "").strip()
    if existing:
        return existing
    shelf = shelf_for(record)
    digest = hashlib.sha256(_stable_seed(record).encode("utf-8")).hexdigest()[:10].upper()
    prefix = {
        "raw": "RAW",
        "zhiyi": "ZHIYI",
        "xingce": "XINGCE",
        "toolbook": "TOOL",
        "errata": "ERRATA",
    }.get(shelf, "ITEM")
    return f"ZX-{prefix}-{digest}"


def title_for(record: dict, limit: int = 52) -> str:
    title = str(record.get("title") or "").strip()
    if title:
        return _compact_text(title, limit)
    text = str(record.get("summary") or record.get("detail") or record.get("raw_excerpt") or "").strip()
    if not text:
        return library_id_for(record)
    for sep in ("。", "，", ".", ";", "；", ":"):
        if sep in text[:100]:
            text = text.split(sep, 1)[0]
            break
    return _compact_text(text, limit)


def lifecycle_status_for(record: dict) -> str:
    lifecycle = record.get("_lifecycle") if isinstance(record.get("_lifecycle"), dict) else {}
    xingce = record.get("_xingce") if isinstance(record.get("_xingce"), dict) else {}
    for value in (
        record.get("lifecycle_status"),
        xingce.get("lifecycle_status"),
        record.get("status"),
        lifecycle.get("status"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return "active"


def source_refs_for(record: dict) -> dict:
    refs = _parse_refs(record.get("_source_refs") or record.get("source_refs") or {})
    if refs:
        return refs
    source_path = str(record.get("source_path") or "").strip()
    if not source_path:
        return {}
    return {
        "source_system": record.get("source_system", ""),
        "computer_name": record.get("computer_name", ""),
        "canonical_window_id": record.get("canonical_window_id", ""),
        "session_id": record.get("session_id", ""),
        "source_path": source_path,
        "msg_ids": record.get("msg_ids", []) or [],
        "artifact_type": record.get("artifact_type", ""),
    }


def _is_toolbook_raw_source(source_path: str) -> bool:
    source_path = str(source_path or "")
    return any(
        source_path.startswith(prefix) or f"/{prefix}" in source_path
        for prefix in TOOLBOOK_RAW_SOURCES.values()
    )


def shelf_for(record: dict) -> str:
    mtype = memory_type(record)
    lifecycle_status = lifecycle_status_for(record)
    conflict = str(record.get("conflict_decision") or "").strip()
    if lifecycle_status in ("deprecated", "deprecrated", "superseded", "invalid", "recycled") or conflict:
        return "errata"
    if mtype == "raw_jsonl" or record.get("raw_mapping_mode") == "raw_jsonl_fallback":
        return "raw"
    if record.get("raw_evidence_status") in ("raw", "raw_direct") and not record.get("summary"):
        return "raw"
    if (
        mtype == "toolbook_candidate"
        or record.get("candidate_type") == "toolbook_candidate"
        or record.get("library_shelf") == "toolbook"
    ):
        return "toolbook"
    if mtype == "xingce_work_experience_candidate" or isinstance(record.get("_xingce"), dict):
        return "xingce"
    lower = " ".join(
        str(record.get(key, "") or "").lower()
        for key in ("summary", "detail", "artifact_type")
    )
    if mtype == "yifanchen_project_status":
        return "toolbook"
    if any(term in lower for term in ("install", "config", "runtime", "hermes", "openclaw", "codex", "mcp", "skill")):
        return "toolbook"
    if mtype in ("preference_memory", "case_memory", "error_memory"):
        return "zhiyi"
    return "zhiyi"


def xingce_lifecycle_for(record: dict) -> dict:
    xingce = record.get("_xingce") if isinstance(record.get("_xingce"), dict) else {}
    status = lifecycle_status_for(record)
    if status == "active":
        status = "candidate" if xingce else status
    return {
        "status": status,
        "allowed_statuses": EXPERIENCE_STATUSES,
        "candidate_id": xingce.get("candidate_id", record.get("candidate_id", "")),
        "action_status": xingce.get("action_status", record.get("action_status", "")),
        "review_required": status in ("candidate", "pending_review", ""),
        "production_experience_write_performed": bool(xingce.get("production_experience_write_performed", False)),
    }


def xingce_work_fields_for(record: dict) -> dict:
    xingce = record.get("_xingce") if isinstance(record.get("_xingce"), dict) else {}
    detail = str(record.get("detail") or "")
    summary = str(record.get("summary") or "")
    return {
        "work_scenario": record.get("work_scenario") or title_for(record),
        "action_strategy": record.get("action_strategy") or record.get("recommended_procedure") or _compact_text(detail or summary, 360),
        "avoid_conditions": record.get("avoid_conditions") or record.get("gotchas") or [],
        "acceptance_checks": record.get("acceptance_checks") or record.get("verification_steps") or [],
        "applicable_scope": record.get("applicable_scope") or record.get("scope") or "",
        "candidate_id": xingce.get("candidate_id", record.get("candidate_id", "")),
        "not_a_user_preference": True,
    }


def typed_graph_for(record: dict) -> dict:
    refs = source_refs_for(record)
    shelf = shelf_for(record)
    library_id = library_id_for(record)
    nodes: List[Dict[str, str]] = []
    edges: List[Dict[str, str]] = []

    def add_node(node_id: str, node_type: str, label: str) -> None:
        if not node_id:
            return
        if not any(node.get("id") == node_id for node in nodes):
            nodes.append({"id": node_id, "type": node_type, "label": _compact_text(label, 80)})

    if shelf == "toolbook":
        primary_node_type = "tool"
    elif shelf == "xingce":
        primary_node_type = "work_experience"
    else:
        primary_node_type = "preference"
    add_node(library_id, primary_node_type, title_for(record))
    platform = str(refs.get("source_system") or record.get("source_system") or "").strip()
    if platform:
        platform_id = f"platform:{platform}"
        add_node(platform_id, "platform", platform)
        edges.append({"from": library_id, "to": platform_id, "type": "belongs_to"})
    project = str(refs.get("canonical_window_id") or record.get("scope") or "").strip()
    if project:
        project_id = "project:" + hashlib.sha256(project.encode("utf-8")).hexdigest()[:10]
        add_node(project_id, "project", project)
        edges.append({"from": library_id, "to": project_id, "type": "belongs_to"})
    if shelf in ("xingce", "toolbook"):
        edges.append({"from": library_id, "to": "zhiyi:preferences", "type": "uses_preference"})
        add_node("zhiyi:preferences", "preference", "Zhiyi preference evidence")
    supersedes = record.get("supersedes") or record.get("superseded_by") or ""
    if supersedes:
        target = f"library:{supersedes}"
        add_node(target, "work_experience", str(supersedes))
        edges.append({"from": library_id, "to": target, "type": "supersedes"})
    return {
        "schema_version": "2026.6.1",
        "node_types": NODE_TYPES,
        "edge_types": EDGE_TYPES,
        "nodes": nodes[:8],
        "edges": edges[:8],
    }


def matched_by_for(record: dict, query: str = "", raw_status: str = "") -> list[str]:
    methods: list[str] = []
    refs = source_refs_for(record)
    if refs:
        methods.append("source_refs")
    if query:
        text = " ".join(str(record.get(key, "") or "") for key in ("summary", "detail", "raw_excerpt"))
        if query in text:
            methods.append("keyword")
        else:
            methods.append("substring_recall")
    if raw_status:
        methods.append(raw_status)
    if shelf_for(record) in ("xingce", "toolbook"):
        methods.append("typed_graph")
    result: list[str] = []
    for method in methods:
        if method and method not in result:
            result.append(method)
    return result or ["library_card"]


def rank_reason_for(record: dict, query: str = "", raw_status: str = "") -> str:
    parts = []
    if query:
        parts.append("query matched existing memory text")
    refs = source_refs_for(record)
    if refs.get("source_path"):
        parts.append("source_refs available")
    if raw_status:
        parts.append(f"raw_status={raw_status}")
    shelf = shelf_for(record)
    parts.append(f"shelf={shelf}")
    return "; ".join(parts)


def _verbatim_excerpt_for(record: dict, raw_excerpt: str = "") -> str:
    for value in (
        raw_excerpt,
        record.get("verbatim_excerpt"),
        record.get("raw_excerpt"),
        record.get("quote_excerpt"),
    ):
        text = str(value or "")
        if text:
            return text
    return ""


def evidence_contract_for(record: dict, *, raw_excerpt: str = "") -> dict:
    refs = source_refs_for(record)
    excerpt = _verbatim_excerpt_for(record, raw_excerpt)
    status = lifecycle_status_for(record)
    supersedes = _as_list(record.get("supersedes"))
    conflicts_with = _as_list(record.get("conflicts_with"))
    required = {
        "source_refs": bool(refs),
        "verbatim_excerpt": bool(excerpt),
        "status": bool(status),
        "supersedes": isinstance(supersedes, list),
        "conflicts_with": isinstance(conflicts_with, list),
    }
    missing = [name for name, ok in required.items() if not ok]
    shelf = shelf_for(record)
    toolbook_source_ok = True
    if shelf == "toolbook":
        source_path = str(refs.get("source_path") or "")
        toolbook_source_ok = _is_toolbook_raw_source(source_path)
        if not toolbook_source_ok:
            missing.append("toolbook_raw_source")
    return {
        "schema_version": LIBRARY_VERSION,
        "required_fields": ["source_refs", "verbatim_excerpt", "status", "supersedes", "conflicts_with"],
        "required": required,
        "valid_experience_record": not missing,
        "missing_fields": missing,
        "source_refs_required": True,
        "verbatim_excerpt_required": True,
        "status_required": True,
        "supersedes_required": True,
        "conflicts_with_required": True,
        "toolbook_raw_source_required": shelf == "toolbook",
        "toolbook_raw_source_ok": toolbook_source_ok,
        "toolbook_raw_sources": TOOLBOOK_RAW_SOURCES,
    }


def library_card_for(record: dict, *, query: str = "", raw_status: str = "", raw_excerpt: str = "") -> dict:
    refs = source_refs_for(record)
    shelf = shelf_for(record)
    excerpt = _verbatim_excerpt_for(record, raw_excerpt)
    supersedes = _as_list(record.get("supersedes"))
    conflicts_with = _as_list(record.get("conflicts_with"))
    card = {
        "library_id": library_id_for(record),
        "library_version": LIBRARY_VERSION,
        "shelf": shelf,
        "shelf_label": ZHIXING_SHELVES.get(shelf, shelf),
        "type": memory_type(record),
        "title": title_for(record),
        "summary": str(record.get("summary") or "")[:800],
        "status": lifecycle_status_for(record),
        "version": record.get("lifecycle_version") or record.get("version") or 1,
        "source_refs": refs,
        "source_ref_status": "available" if refs else "missing",
        "raw_available": bool(refs.get("source_path") or excerpt),
        "verbatim_excerpt": excerpt,
        "last_verified_at": record.get("last_verified_at") or record.get("updated_at") or "",
        "conflicts_with": conflicts_with,
        "supersedes": supersedes,
        "evidence_contract": evidence_contract_for(record, raw_excerpt=excerpt),
        "matched_by": matched_by_for(record, query=query, raw_status=raw_status),
        "rank_reason": rank_reason_for(record, query=query, raw_status=raw_status),
        "typed_graph": typed_graph_for(record),
        "created_at": record.get("created_at") or record.get("extracted_at") or record.get("captured_at") or "",
        "updated_at": record.get("updated_at") or record.get("extracted_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    if shelf == "xingce":
        card["xingce_lifecycle"] = xingce_lifecycle_for(record)
        card["work_experience"] = xingce_work_fields_for(record)
    return card


def attach_library_card(record: dict, *, query: str = "", raw_status: str = "", raw_excerpt: str = "") -> dict:
    result = dict(record)
    card = library_card_for(result, query=query, raw_status=raw_status, raw_excerpt=raw_excerpt)
    result["library_id"] = card["library_id"]
    result["library_shelf"] = card["shelf"]
    result["library_card"] = card
    result["matched_by"] = card["matched_by"]
    result["rank_reason"] = card["rank_reason"]
    result["typed_graph"] = card["typed_graph"]
    if card.get("work_experience"):
        result["work_experience"] = card["work_experience"]
    return result


def library_manifest() -> dict:
    return {
        "enabled": True,
        "version": LIBRARY_VERSION,
        "name": "Zhixing Library",
        "zh_name": "知行图书馆",
        "shelves": ZHIXING_SHELVES,
        "node_types": NODE_TYPES,
        "edge_types": EDGE_TYPES,
        "experience_statuses": EXPERIENCE_STATUSES,
        "experience_required_fields": ["source_refs", "verbatim_excerpt", "status", "supersedes", "conflicts_with"],
        "toolbook_raw_sources": TOOLBOOK_RAW_SOURCES,
        "raw_is_source_text": True,
        "zhiyi_role": "preference and intent experience",
        "xingce_role": "work experience and toolbooks",
        "static_structure": "five_shelves",
        "dynamic_loop": "zhixing_evidence_loop",
    }


def zhixing_loop_manifest() -> dict:
    return {
        "enabled": True,
        "version": LIBRARY_VERSION,
        "name": "Zhixing Evidence Loop",
        "zh_name": "知行闭环",
        "static_structure": "Zhixing Library v2 five shelves",
        "dynamic_flow": "seven steps crossing the five shelves",
        "steps": ZHIXING_LOOP_STEPS,
        "flight_metrics": FLIGHT_METRICS,
        "metric_shape": {
            "defense_count": sum(1 for metric in FLIGHT_METRICS if metric["kind"] == "defense"),
            "offense_count": sum(1 for metric in FLIGHT_METRICS if metric["kind"] == "offense"),
            "offense_metric": "proactive_resurfacing",
            "offense_metric_must_not_be_diluted": True,
        },
        "connector_persona": {
            "name": "Jieyin",
            "zh_name": "接引者",
            "role": "visible entry point and gatekeeper; not Zhiyi itself",
            "actions": ["summon", "hint", "guard", "guide"],
            "zh_actions": ["召唤", "提示", "守门", "引路"],
            "zhiyi_remains_implicit": True,
        },
    }


def replay_plan() -> dict:
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "version": LIBRARY_VERSION,
        "name": "Zhiyi/Xingce Evidence Loop Replay",
        "zh_name": "知行闭环回放",
        "comparison_sets": REPLAY_COMPARISON_SETS,
        "metrics": [metric["id"] for metric in FLIGHT_METRICS],
        "metric_contract": FLIGHT_METRICS,
        "scoring": {
            "judge": "deterministic_rules",
            "ai_self_judging_allowed": False,
            "human_review_optional": True,
            "case_contract": [
                "expected_source_refs",
                "expected_library_ids",
                "expected_behavior_markers",
                "forbidden_repeated_mistakes",
                "required_acceptance_checks",
                "expected_proactive_resurfacing",
            ],
        },
        "sample_task_shape": {
            "query": "same user task replayed under each memory mode",
            "required_evidence": ["library_id", "source_refs", "raw_excerpt_or_unavailable_reason"],
            "required_xingce_fields": ["work_scenario", "action_strategy", "avoid_conditions", "acceptance_checks"],
            "optional_offense_field": "expected_proactive_resurfacing",
        },
        "status": "dry_run_runner_ready",
        "implemented_now": "read_only_plan_and_deterministic_dry_run",
        "loop": zhixing_loop_manifest(),
    }


def benchmark_plan() -> dict:
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "version": LIBRARY_VERSION,
        "name": "Zhiyi/Xingce Real Task Benchmark",
        "zh_name": "知意 / 行策真实任务集验证",
        "purpose": "Check whether Zhiyi plus Xingce improves real task handling before building a feedback queue.",
        "comparison_sets": REPLAY_COMPARISON_SETS,
        "metrics": [metric["id"] for metric in FLIGHT_METRICS],
        "metric_contract": FLIGHT_METRICS,
        "case_contract": {
            "required_fields": BENCHMARK_REQUIRED_CASE_FIELDS,
            "recommended_case_count": {"minimum": 5, "target": "10-20"},
            "case_sources": [
                "real_project_handoff",
                "repeated_gotcha",
                "platform_boundary",
                "source_backed_correction",
                "proactive_resurfacing",
            ],
        },
        "scoring": {
            "judge": "deterministic_rules",
            "ai_self_judging_allowed": False,
            "model_call_performed": False,
            "write_performed": False,
        },
        "promotion_rule": {
            "queue_should_wait_for_benchmark": True,
            "minimum_signal": "zhiyi_plus_xingce must beat zhiyi_only on total score or proactive resurfacing wins",
            "do_not_overclaim": "dry-run benchmark is evidence for direction, not proof that machine ascension is complete",
        },
        "sample_case": {
            "case_id": "platform-profile-gotcha",
            "query": "Continue a platform configuration task without repeating old mistakes.",
            "expected_source_refs": ["raw/probe_logs/hermes-profile-effective-config.jsonl"],
            "expected_behavior_markers": ["check the profile-level config first"],
            "forbidden_repeated_mistakes": ["treat root config as inherited default"],
            "required_acceptance_checks": ["profile show"],
            "expected_proactive_resurfacing": ["profile without config shows auto"],
        },
    }


def _normalize_expected_values(value: Any) -> list[str]:
    return [str(item or "").strip() for item in _as_list(value) if str(item or "").strip()]


def _record_text(record: dict) -> str:
    card = record.get("library_card") if isinstance(record.get("library_card"), dict) else {}
    parts = [
        record.get("library_id", ""),
        record.get("exp_id", ""),
        record.get("summary", ""),
        record.get("detail", ""),
        record.get("raw_excerpt", ""),
        record.get("verbatim_excerpt", ""),
        card.get("library_id", ""),
        card.get("verbatim_excerpt", ""),
    ]
    return "\n".join(str(part or "") for part in parts)


def _records_for_mode(memory_mode: str, records: list[dict]) -> list[dict]:
    if memory_mode == "no_memory":
        return []
    attached = [attach_library_card(record) for record in records if isinstance(record, dict)]
    if memory_mode == "zhiyi_only":
        return [record for record in attached if record.get("library_shelf") == "zhiyi"]
    if memory_mode == "zhiyi_plus_xingce":
        return attached
    return attached


def _score_replay_mode(case: dict, memory_mode: str, records: list[dict]) -> dict:
    active_records = _records_for_mode(memory_mode, records)
    text = "\n".join(_record_text(record) for record in active_records)
    ids = {
        str(record.get("library_id") or record.get("library_card", {}).get("library_id") or "")
        for record in active_records
    }
    source_refs_available = any(source_refs_for(record) for record in active_records)
    expected_source_refs = _normalize_expected_values(case.get("expected_source_refs"))
    expected_library_ids = _normalize_expected_values(case.get("expected_library_ids"))
    expected_behavior_markers = _normalize_expected_values(case.get("expected_behavior_markers"))
    forbidden_repeated_mistakes = _normalize_expected_values(case.get("forbidden_repeated_mistakes"))
    required_acceptance_checks = _normalize_expected_values(case.get("required_acceptance_checks"))
    expected_proactive = _normalize_expected_values(case.get("expected_proactive_resurfacing"))
    checks = {
        "source_backed_answer_rate": (not expected_source_refs) or source_refs_available,
        "fewer_repeated_questions": (not expected_source_refs) or source_refs_available,
        "fewer_repeated_mistakes": not any(marker and marker in text for marker in forbidden_repeated_mistakes),
        "user_habit_followed": all(marker in text for marker in expected_behavior_markers),
        "expected_library_ids": all(library_id in ids for library_id in expected_library_ids),
        "workflow_step_followed": all(marker in text for marker in expected_behavior_markers),
        "project_boundary_respected": not any(marker and marker in text for marker in forbidden_repeated_mistakes),
        "acceptance_check_completed": all(marker in text for marker in required_acceptance_checks),
        "proactive_resurfacing": bool(expected_proactive) and all(marker in text for marker in expected_proactive),
    }
    passed = [name for name, ok in checks.items() if ok]
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "memory_mode": memory_mode,
        "matched_records_count": len(active_records),
        "used_library_ids": sorted(library_id for library_id in ids if library_id),
        "source_refs_available": source_refs_available,
        "checks": checks,
        "passed": passed,
        "failed": failed,
        "score": len(passed),
        "max_score": len(checks),
        "offense_metric": {
            "id": "proactive_resurfacing",
            "passed": checks["proactive_resurfacing"],
            "expected": expected_proactive,
            "kind": "offense",
        },
    }


def _feedback_candidate_id(case_id: str, kind: str, value: str) -> str:
    seed = f"{case_id}|{kind}|{value}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"replay-{kind}-{digest}"


def replay_feedback_candidates(case: dict, results: list[dict]) -> dict:
    case_id = str(case.get("case_id") or case.get("id") or "replay-case")
    by_mode = {item.get("memory_mode", ""): item for item in results if isinstance(item, dict)}
    zhiyi_plus = by_mode.get("zhiyi_plus_xingce", {})
    no_memory = by_mode.get("no_memory", {})
    improvement = int(zhiyi_plus.get("score", 0)) - int(no_memory.get("score", 0))
    used_library_ids = [
        value for value in _as_list(zhiyi_plus.get("used_library_ids"))
        if str(value or "").strip()
    ]
    proactive = zhiyi_plus.get("offense_metric", {}) if isinstance(zhiyi_plus.get("offense_metric"), dict) else {}
    proactive_expected = _normalize_expected_values(proactive.get("expected"))
    candidates: list[dict] = []

    if improvement > 0 and used_library_ids:
        for library_id in used_library_ids:
            candidates.append({
                "candidate_id": _feedback_candidate_id(case_id, "adopt", str(library_id)),
                "candidate_type": "replay_adoption_candidate",
                "target_library_id": library_id,
                "recommended_action": "review_for_adoption_or_keep_active",
                "reason": "zhiyi_plus_xingce_outperformed_no_memory",
                "evidence": {
                    "case_id": case_id,
                    "best_mode": "zhiyi_plus_xingce",
                    "improvement_over_no_memory": improvement,
                    "passed": zhiyi_plus.get("passed", []),
                    "failed": zhiyi_plus.get("failed", []),
                },
                "write_performed": False,
                "requires_authorization": True,
            })

    if proactive.get("passed"):
        for expected in proactive_expected:
            candidates.append({
                "candidate_id": _feedback_candidate_id(case_id, "proactive", expected),
                "candidate_type": "proactive_resurfacing_candidate",
                "target_metric": "proactive_resurfacing",
                "recommended_action": "allow_future_proactive_hint_review",
                "reason": "past_successful_pattern_was_available_without_explicit_user_request",
                "resurfacing_marker": expected,
                "source_library_ids": used_library_ids,
                "write_performed": False,
                "requires_authorization": True,
            })

    failed = _as_list(zhiyi_plus.get("failed"))
    if failed:
        candidates.append({
            "candidate_id": _feedback_candidate_id(case_id, "errata", "|".join(str(item) for item in failed)),
            "candidate_type": "replay_errata_candidate",
            "recommended_action": "review_missing_or_conflicting_evidence",
            "reason": "zhiyi_plus_xingce_failed_replay_checks",
            "failed_checks": failed,
            "case_id": case_id,
            "write_performed": False,
            "requires_authorization": True,
        })

    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "candidate_types": sorted({candidate["candidate_type"] for candidate in candidates}),
        "authorization_required_for_apply": True,
        "notes": [
            "replay_feedback_candidates_are_review_only",
            "no_adoption_errata_or_proactive_hint_written",
            "apply_requires_future_explicit_authorization",
        ],
    }


def run_replay_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    case = body.get("case") if isinstance(body.get("case"), dict) else body
    records = body.get("records") if isinstance(body.get("records"), list) else case.get("records", [])
    if not isinstance(records, list):
        records = []
    results = [
        _score_replay_mode(case, memory_mode, records)
        for memory_mode in REPLAY_COMPARISON_SETS
    ]
    by_mode = {item["memory_mode"]: item for item in results}
    zhiyi_plus = by_mode.get("zhiyi_plus_xingce", {})
    no_memory = by_mode.get("no_memory", {})
    feedback = replay_feedback_candidates(case, results)
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "version": LIBRARY_VERSION,
        "case_id": str(case.get("case_id") or case.get("id") or "replay-case"),
        "query": str(case.get("query") or ""),
        "comparison_sets": REPLAY_COMPARISON_SETS,
        "loop": zhixing_loop_manifest(),
        "plan": replay_plan(),
        "results": results,
        "summary": {
            "best_mode": max(results, key=lambda item: item["score"])["memory_mode"] if results else "",
            "zhiyi_plus_xingce_score": zhiyi_plus.get("score", 0),
            "no_memory_score": no_memory.get("score", 0),
            "improvement_over_no_memory": int(zhiyi_plus.get("score", 0)) - int(no_memory.get("score", 0)),
            "proactive_resurfacing_passed": bool(
                zhiyi_plus.get("offense_metric", {}).get("passed", False)
            ),
            "offense_metric_must_not_be_diluted": True,
        },
        "feedback_candidates": feedback,
        "notes": [
            "deterministic_dry_run_only",
            "no_model_call",
            "no_memory_or_platform_write",
            "feedback_candidates_are_review_only",
            "proactive_resurfacing_is_the_offense_metric",
        ],
    }


def _benchmark_cases_from_body(body: dict) -> list[dict]:
    cases = body.get("cases") if isinstance(body.get("cases"), list) else []
    if cases:
        return [case for case in cases if isinstance(case, dict)]
    case = body.get("case") if isinstance(body.get("case"), dict) else {}
    return [case] if case else []


def _case_records(case: dict, shared_records: list[dict]) -> list[dict]:
    records = case.get("records") if isinstance(case.get("records"), list) else None
    if records is not None:
        return [record for record in records if isinstance(record, dict)]
    return [record for record in shared_records if isinstance(record, dict)]


def _case_contract_status(case: dict) -> dict:
    missing = []
    for field in BENCHMARK_REQUIRED_CASE_FIELDS:
        value = case.get(field)
        if field in ("expected_source_refs", "expected_behavior_markers", "forbidden_repeated_mistakes", "required_acceptance_checks", "expected_proactive_resurfacing"):
            if not _normalize_expected_values(value):
                missing.append(field)
        elif not str(value or "").strip():
            missing.append(field)
    return {
        "ok": not missing,
        "missing_fields": missing,
        "required_fields": BENCHMARK_REQUIRED_CASE_FIELDS,
    }


def run_benchmark_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    cases = _benchmark_cases_from_body(body)
    shared_records = body.get("records") if isinstance(body.get("records"), list) else []
    case_results = []
    totals = {
        mode: {
            "score": 0,
            "max_score": 0,
            "wins": 0,
            "proactive_resurfacing_passed": 0,
            "source_backed_answer_rate_passed": 0,
            "case_count": 0,
        }
        for mode in REPLAY_COMPARISON_SETS
    }
    contract_failures = []

    for index, case in enumerate(cases):
        case_id = str(case.get("case_id") or case.get("id") or f"benchmark-case-{index + 1}")
        records = _case_records(case, shared_records)
        replay = run_replay_dry_run({"case": case, "records": records})
        contract = _case_contract_status(case)
        if not contract["ok"]:
            contract_failures.append({"case_id": case_id, "missing_fields": contract["missing_fields"]})
        by_mode = {item["memory_mode"]: item for item in replay.get("results", [])}
        best_score = max((item.get("score", 0) for item in replay.get("results", [])), default=0)
        winning_modes = [
            item.get("memory_mode", "")
            for item in replay.get("results", [])
            if item.get("score", 0) == best_score
        ]
        for mode, result in by_mode.items():
            totals[mode]["score"] += int(result.get("score", 0))
            totals[mode]["max_score"] += int(result.get("max_score", 0))
            totals[mode]["wins"] += 1 if mode in winning_modes else 0
            totals[mode]["case_count"] += 1
            if result.get("offense_metric", {}).get("passed"):
                totals[mode]["proactive_resurfacing_passed"] += 1
            if result.get("checks", {}).get("source_backed_answer_rate"):
                totals[mode]["source_backed_answer_rate_passed"] += 1
        case_results.append({
            "case_id": case_id,
            "query": str(case.get("query") or ""),
            "contract": contract,
            "best_mode": replay.get("summary", {}).get("best_mode", ""),
            "zhiyi_plus_xingce_score": replay.get("summary", {}).get("zhiyi_plus_xingce_score", 0),
            "proactive_resurfacing_passed": replay.get("summary", {}).get("proactive_resurfacing_passed", False),
            "results": replay.get("results", []),
            "feedback_candidates": replay.get("feedback_candidates", {}),
        })

    zhiyi_only_score = totals["zhiyi_only"]["score"]
    zhiyi_plus_score = totals["zhiyi_plus_xingce"]["score"]
    no_memory_score = totals["no_memory"]["score"]
    proactive_delta = (
        totals["zhiyi_plus_xingce"]["proactive_resurfacing_passed"]
        - totals["zhiyi_only"]["proactive_resurfacing_passed"]
    )
    has_cases = bool(cases)
    xingce_signal = has_cases and ((zhiyi_plus_score > zhiyi_only_score) or proactive_delta > 0)
    if not has_cases:
        recommendation = "provide_real_task_cases_before_benchmark"
    elif zhiyi_plus_score > zhiyi_only_score:
        recommendation = "proceed_to_replay_feedback_queue_design"
    elif proactive_delta > 0:
        recommendation = "inspect_proactive_resurfacing_cases_before_queue"
    else:
        recommendation = "improve_xingce_records_or_recall_before_queue"

    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "model_call_performed": False,
        "version": LIBRARY_VERSION,
        "plan": benchmark_plan(),
        "case_count": len(cases),
        "comparison_sets": REPLAY_COMPARISON_SETS,
        "totals": totals,
        "summary": {
            "best_mode": max(totals.items(), key=lambda item: item[1]["score"])[0] if has_cases else "",
            "zhiyi_plus_xingce_score": zhiyi_plus_score,
            "zhiyi_only_score": zhiyi_only_score,
            "no_memory_score": no_memory_score,
            "improvement_over_zhiyi_only": zhiyi_plus_score - zhiyi_only_score,
            "improvement_over_no_memory": zhiyi_plus_score - no_memory_score,
            "proactive_resurfacing_delta_over_zhiyi_only": proactive_delta,
            "xingce_signal_detected": xingce_signal,
            "recommendation": recommendation,
            "queue_should_wait_for_benchmark": True,
            "machine_ascension_not_claimed": True,
        },
        "contract": {
            "ok": not contract_failures,
            "case_failures": contract_failures,
            "required_fields": BENCHMARK_REQUIRED_CASE_FIELDS,
        },
        "case_results": case_results,
        "notes": [
            "deterministic_task_set_benchmark_only",
            "no_model_call",
            "no_memory_or_platform_write",
            "use_real_cases_before_building_replay_feedback_queue",
        ],
    }


def hybrid_recall_manifest() -> dict:
    return {
        "enabled": True,
        "version": LIBRARY_VERSION,
        "methods": ["source_refs", "keyword", "vector_ready", "typed_graph", "time_project_filter", "rrf_ready"],
        "pipeline_order": ["source_refs_exact", "bm25_or_keyword", "vector", "typed_graph", "time_project_filter", "rrf_merge"],
        "implemented_now": ["source_refs", "keyword", "vector_ready", "typed_graph", "time_project_filter"],
        "rrf_applied": False,
        "bm25_applied": False,
        "vector_is_not_authority": True,
        "source_refs_are_primary": True,
        "notes": "The manifest exposes the hybrid recall contract; the current gateway still uses existing substring/vector recall plus source_refs and library graph metadata.",
    }


def validate_toolbook_candidate(candidate: dict) -> dict:
    candidate = candidate if isinstance(candidate, dict) else {}
    card = library_card_for(candidate)
    contract = card.get("evidence_contract", {})
    checks = {
        "candidate_type": candidate.get("candidate_type") == "toolbook_candidate",
        "platform": bool(str(candidate.get("platform") or "").strip()),
        "observed_behavior": bool(str(candidate.get("observed_behavior") or "").strip()),
        "environment": bool(str(candidate.get("environment") or "").strip()),
        "source_refs": bool(card.get("source_refs")),
        "verbatim_excerpt": bool(card.get("verbatim_excerpt")),
        "toolbook_raw_source": bool(contract.get("toolbook_raw_source_ok")),
        "write_performed_false": not bool(candidate.get("write_performed", False)),
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "ok": not missing,
        "schema_version": LIBRARY_VERSION,
        "checks": checks,
        "missing": missing,
        "candidate_id": candidate.get("candidate_id", ""),
        "library_id": card.get("library_id", ""),
        "library_card": card,
        "write_performed": False,
        "toolbook_raw_sources": TOOLBOOK_RAW_SOURCES,
    }


def build_toolbook_candidate(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    platform = str(body.get("platform") or "").strip()
    observed_behavior = str(body.get("observed_behavior") or body.get("summary") or "").strip()
    environment = str(body.get("environment") or "").strip()
    raw_source_path = str(body.get("raw_source_path") or body.get("source_path") or "").strip()
    transcript_ref = str(body.get("command_transcript_ref") or "").strip()
    if not raw_source_path and transcript_ref:
        raw_source_path = transcript_ref
    source_refs = body.get("source_refs") if isinstance(body.get("source_refs"), dict) else {}
    if raw_source_path and not source_refs:
        source_refs = {
            "source_system": "probe" if "raw/probe_logs/" in raw_source_path else "external_doc",
            "source_path": raw_source_path,
            "artifact_type": "toolbook_probe_log" if "raw/probe_logs/" in raw_source_path else "toolbook_external_doc",
            "msg_ids": _as_list(body.get("msg_ids")),
        }
    verbatim_excerpt = str(body.get("verbatim_excerpt") or body.get("raw_excerpt") or "").strip()
    title = str(body.get("title") or observed_behavior or platform or "Toolbook candidate").strip()
    seed = json.dumps(
        {
            "platform": platform,
            "observed_behavior": observed_behavior,
            "environment": environment,
            "source_path": source_refs.get("source_path", ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    candidate_id = str(body.get("candidate_id") or f"toolbook-{_slug(platform)}-{digest}").strip()
    candidate = {
        "candidate_type": "toolbook_candidate",
        "_type": "toolbook_candidate",
        "type": "toolbook_candidate",
        "candidate_id": candidate_id,
        "exp_id": candidate_id,
        "title": title,
        "summary": observed_behavior,
        "detail": str(body.get("detail") or observed_behavior),
        "platform": platform,
        "observed_behavior": observed_behavior,
        "environment": environment,
        "command_transcript_ref": transcript_ref or source_refs.get("source_path", ""),
        "source_refs": source_refs,
        "verbatim_excerpt": verbatim_excerpt,
        "status": str(body.get("status") or "candidate"),
        "lifecycle_status": str(body.get("lifecycle_status") or body.get("status") or "candidate"),
        "supersedes": _as_list(body.get("supersedes")),
        "conflicts_with": _as_list(body.get("conflicts_with")),
        "applicable_scope": str(body.get("applicable_scope") or platform),
        "confidence": body.get("confidence", 0.7),
        "write_performed": False,
        "raw_write_performed": False,
        "toolbook_write_performed": False,
        "created_at": body.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    candidate = attach_library_card(candidate)
    validation = validate_toolbook_candidate(candidate)
    return {
        "ok": validation["ok"],
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "candidate": candidate,
        "validation": validation,
        "notes": [
            "toolbook_candidate_dry_run_only",
            "raw_probe_or_external_doc_required",
            "no_file_created_or_appended",
        ],
    }
