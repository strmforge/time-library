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

try:
    from src.time_river_sediment import build_sediment_link, get_time_river_sediment_contract
except Exception:  # pragma: no cover
    from time_river_sediment import build_sediment_link, get_time_river_sediment_contract


LIBRARY_VERSION = "2026.6.1"
LIBRARY_NOTE_PROJECTION_CONTRACT = "zhixing_library_note_projection.v1"
LIBRARY_ADMISSION_CANDIDATE_CONTRACT = "zhixing_library_admission_candidate.v1"
LIBRARY_ACTIVE_BOOKMARKS_CONTRACT = "zhixing_library_active_bookmarks.v1"
LIBRARY_EXPERIENCE_HISTORY_CONTRACT = "zhixing_library_experience_history.v1"
LIBRARY_TRUST_DOCTOR_CONTRACT = "zhixing_library_trust_doctor.v1"
LIBRARY_INDEX_PROJECTION_CONTRACT = "zhixing_library_index_projection.v1"
LIBRARY_EXPERIENCE_EVOLUTION_CONTRACT = "zhixing_library_experience_evolution_candidates.v1"
LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT = "zhixing_library_experience_review_action.v1"
LIBRARY_EXPERIENCE_VALIDATION_REPORT_CONTRACT = "zhixing_library_experience_validation_report.v1"
LIBRARY_EXPERIENCE_VALIDATION_RECEIPT_SCHEMA_CONTRACT = "zhixing_library_experience_validation_receipt_schema.v1"
LIBRARY_EXPERIENCE_REVIEW_QUEUE_CONTRACT = "zhixing_library_experience_review_queue.v1"
LIBRARY_EXPERIENCE_REVIEW_APPLY_GATE_CONTRACT = "zhixing_library_experience_review_apply_gate.v1"
LIBRARY_EXPERIENCE_APPLY_RECEIPT_SCHEMA_CONTRACT = "zhixing_library_experience_apply_receipt_schema.v1"
LIBRARY_EXPERIENCE_APPLY_PACKAGE_CONTRACT = "zhixing_library_experience_apply_package.v1"
LIBRARY_EXPERIENCE_FLOW_OVERVIEW_CONTRACT = "zhixing_library_experience_flow_overview.v1"
AI_READABLE_LIBRARY_PROJECTION_CONTRACT = "zhixing_ai_readable_library_projection.v1"
AI_READABLE_PROJECTION_PROFILE = "five_shelf_ai_readable_projection.v2026.6.17"
ZHIXING_SHELVES = {
    "raw": "Original source records and direct raw excerpts.",
    "zhiyi": "Preference, intent, wording, correction, and user-understanding experience.",
    "xingce": "Work experience, action strategy, validation paths, and project gotchas.",
    "toolbook": "Operational notes about platforms, tools, environment, setup, and runbooks.",
    "errata": "Deprecated, superseded, conflicting, or invalidated library records.",
}
EXPERIENCE_STATUSES = ["candidate", "pending_review", "adopted", "deprecated", "superseded"]
EXPERIENCE_REVIEW_ACTIONS = ["approve", "reject", "defer", "request_evidence"]
EXPERIENCE_REVIEW_APPLY_CONFIRMATIONS = [
    "confirm_review_action_intent",
    "confirm_source_refs_checked",
    "confirm_replay_or_validation_checked",
    "confirm_no_raw_or_markdown_write",
    "operator",
    "reason",
]
NODE_TYPES = ["user", "project", "platform", "task", "preference", "work_experience", "tool"]
EDGE_TYPES = [
    "belongs_to",
    "caused_by",
    "fixed_by",
    "blocked_by",
    "supersedes",
    "uses_preference",
    "relates_to",
    "depends_on",
    "proven_by",
    "contradicts",
]
LIBRARY_NOTE_SECTIONS = [
    "what_this_is",
    "applies_when",
    "procedure_or_judgment",
    "avoid",
    "verification",
    "sources",
]
LIBRARY_RELATION_FIELDS = [
    "relates_to",
    "supersedes",
    "depends_on",
    "blocked_by",
    "proven_by",
    "contradicts",
    "conflicts_with",
]
AI_READABLE_PROJECTION_LAYERS = [
    {
        "id": "L0_library_index_projection",
        "contract": LIBRARY_INDEX_PROJECTION_CONTRACT,
        "role": "compact catalog and navigation hint",
        "authority": "navigation_only_raw_evidence_required",
    },
    {
        "id": "L1_library_note_projection",
        "contract": LIBRARY_NOTE_PROJECTION_CONTRACT,
        "role": "compiled current understanding for a library item",
        "authority": "synthesis_only_raw_evidence_required",
    },
    {
        "id": "L2_raw_source_record",
        "contract": "raw_source_refs",
        "role": "verbatim original record and source coordinates",
        "authority": "source_of_truth",
    },
]
ADMISSION_SOURCE_TYPES = [
    "markdown_note",
    "article",
    "bookmark",
    "pdf",
    "external_document",
    "local_file",
    "web_page",
]
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


def _string_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in _as_list(value) if str(item or "").strip()]


def _frontmatter_scalar(value: Any) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if not text:
        return '""'
    return json.dumps(text, ensure_ascii=False)


def _frontmatter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return _frontmatter_scalar(value)


def _markdown_list(items: Any, *, empty: str = "-") -> list[str]:
    values = _string_list(items)
    if not values:
        return [empty]
    return [f"- {item}" for item in values]


def _markdown_source_refs(refs: dict) -> list[str]:
    if not refs:
        return ["- source_refs: missing"]
    lines = []
    for key in ("source_system", "computer_name", "canonical_window_id", "session_id", "source_path", "raw_session_path", "artifact_type"):
        value = refs.get(key)
        if value not in ("", None, [], {}):
            lines.append(f"- {key}: `{value}`")
    msg_ids = refs.get("msg_ids")
    if msg_ids:
        lines.append(f"- msg_ids: `{json.dumps(msg_ids, ensure_ascii=False)}`")
    return lines or [f"- source_refs: `{json.dumps(refs, ensure_ascii=False, sort_keys=True)}`"]


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
    explicit_shelf = str(record.get("library_shelf") or "").strip().lower()
    if explicit_shelf in ZHIXING_SHELVES:
        return explicit_shelf
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
    relation_map = {
        "relates_to": "relates_to",
        "supersedes": "supersedes",
        "superseded_by": "supersedes",
        "depends_on": "depends_on",
        "blocked_by": "blocked_by",
        "proven_by": "proven_by",
        "conflicts_with": "contradicts",
        "contradicts": "contradicts",
    }
    for field, edge_type in relation_map.items():
        for target_id in _string_list(record.get(field)):
            target = target_id if target_id.startswith("library:") else f"library:{target_id}"
            add_node(target, "work_experience", target_id)
            edges.append({"from": library_id, "to": target, "type": edge_type})
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


def ai_readable_library_projection_contract() -> dict:
    return {
        "ok": True,
        "contract": AI_READABLE_LIBRARY_PROJECTION_CONTRACT,
        "profile": AI_READABLE_PROJECTION_PROFILE,
        "version": LIBRARY_VERSION,
        "zh_name": "AI 可读馆藏投影",
        "en_name": "AI-readable Library Projection",
        "read_only": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "compatible_inspirations": ["OKF", "LLM Wiki", "OpenViking", "GBrain"],
        "projection_layers": AI_READABLE_PROJECTION_LAYERS,
        "l0_layer": "L0_library_index_projection",
        "l1_layer": "L1_library_note_projection",
        "l2_layer": "L2_raw_source_record",
        "source_authority_layer": "L2_raw_source_record",
        "progressive_disclosure_order": [
            "catalog_index_first",
            "library_note_when_needed",
            "raw_source_refs_for_evidence",
            "raw_excerpt_only_when_budget_or_user_request_allows",
        ],
        "frontmatter_policy": {
            "minimum_required": ["type", "library_id", "shelf", "source_refs"],
            "unknown_fields_preserved": True,
            "broken_links_tolerated": True,
            "source_refs_are_citations": True,
            "raw_refs_are_not_replaced_by_markdown": True,
        },
        "receipt_policy": {
            "must_record_projection_layer_used": True,
            "must_record_raw_fallback_or_skip_reason": True,
            "must_record_source_refs_or_gap": True,
            "projection_never_claims_final_authority": True,
        },
        "shelf_mapping": {
            "raw": "verbatim source records and raw coordinates",
            "zhiyi": "identity, preference, habit, correction, and stable understanding notes",
            "xingce": "work experience, strategy, validation path, and gotcha notes",
            "toolbook": "tool, platform, environment, and runbook notes",
            "errata": "superseded, conflicting, deprecated, and correction notes",
        },
        "forbidden_by_default": [
            "create_sixth_layer",
            "treat_projection_as_raw_authority",
            "bind_projection_to_one_note_app",
            "hide_source_refs_behind_summary",
            "auto_adopt_projection_without_review",
        ],
    }


def library_note_projection_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_NOTE_PROJECTION_CONTRACT,
        "ai_readable_projection_profile": AI_READABLE_PROJECTION_PROFILE,
        "projection_layer": "L1_library_note_projection",
        "source_authority_layer": "L2_raw_source_record",
        "version": LIBRARY_VERSION,
        "zh_name": "馆藏注记",
        "en_name": "Library Note Projection",
        "read_only": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "projection_of": "zhixing_library_five_shelves",
        "anchored_by": "library_id",
        "format": "markdown_with_json_compatible_frontmatter",
        "requires_obsidian": False,
        "obsidian_dependency": False,
        "raw_authority_preserved": True,
        "raw_replacement_allowed": False,
        "shelves": list(ZHIXING_SHELVES.keys()),
        "required_frontmatter": [
            "library_id",
            "shelf",
            "status",
            "source_refs",
            "verbatim_excerpt_required",
            "supersedes",
            "conflicts_with",
            "last_verified_at",
        ],
        "sections": LIBRARY_NOTE_SECTIONS,
        "relation_fields": LIBRARY_RELATION_FIELDS,
        "forbidden_by_default": [
            "create_sixth_layer",
            "write_note_as_raw",
            "treat_markdown_as_source_authority",
            "require_obsidian_app_or_cli",
            "promote_admission_candidate_without_review",
        ],
    }


def library_admission_candidate_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_ADMISSION_CANDIDATE_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "入馆候选",
        "en_name": "Library Admission Candidate",
        "read_only": True,
        "write_performed": False,
        "candidate_type": "library_admission_candidate",
        "not_durable_memory": True,
        "promotion_rule": "candidate_only_until_source_review_or_replay_or_user_approval",
        "target_shelves": list(ZHIXING_SHELVES.keys()),
        "source_types": ADMISSION_SOURCE_TYPES,
        "required_fields": ["title_or_text", "source_refs", "verbatim_excerpt"],
        "recommended_fields": ["target_shelf", "summary", "applies_when", "verification", "relations"],
        "forbidden_by_default": [
            "write_raw",
            "write_zhiyi",
            "write_xingce",
            "write_toolbook",
            "write_errata",
            "write_markdown_file",
            "claim_adopted_without_review",
        ],
    }


def library_active_bookmarks_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_ACTIVE_BOOKMARKS_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "活性书签",
        "en_name": "Active Bookmarks",
        "read_only": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "projection_of": "current_task_view_over_library_ids",
        "anchored_by": "library_id",
        "purpose": "Keep only the most relevant five-shelf records active for the current task.",
        "source_pool_required": True,
        "global_memory_scan_performed": False,
        "recall_volume_control": True,
        "errata_first_when_risky": True,
        "requires_obsidian": False,
        "default_limit": 5,
        "bookmark_shape": [
            "library_id",
            "shelf",
            "title",
            "status",
            "priority",
            "reason",
            "source_ref_status",
        ],
        "forbidden_by_default": [
            "create_bookmark_store",
            "write_memory",
            "scan_global_raw_pool_without_permission",
            "promote_bookmark_to_truth",
        ],
    }


def library_experience_history_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_HISTORY_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "经验履历",
        "en_name": "Experience History",
        "read_only": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "projection_of": "xingce_records_and_replay_receipts",
        "anchored_by": "library_id",
        "target_shelf": "xingce",
        "requires_obsidian": False,
        "tracked_fields": [
            "usage_count",
            "accepted_count",
            "rejected_count",
            "replay_count",
            "last_replayed_at",
            "last_accepted_at",
            "last_rejected_at",
            "failure_modes",
            "validation_status",
        ],
        "promotion_rule": "history_explains_but_does_not_adopt_or_reject_by_itself",
        "forbidden_by_default": [
            "change_lifecycle_status",
            "write_xingce",
            "treat_usage_as_truth",
            "hide_failed_replays",
        ],
    }


def library_trust_doctor_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_TRUST_DOCTOR_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "馆藏可信医生",
        "en_name": "Library Trust Doctor",
        "read_only": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "projection_of": "five_shelf_evidence_health",
        "anchored_by": "library_id",
        "requires_obsidian": False,
        "checks": [
            "source_refs_available",
            "verbatim_excerpt_available",
            "raw_authority_preserved",
            "library_note_projection_ready",
            "xingce_has_validation",
            "errata_visible",
            "active_bookmarks_compact",
        ],
        "doctor_is_demo_safe": True,
        "forbidden_by_default": [
            "write_raw",
            "write_memory",
            "rebuild_index",
            "claim_public_benchmark",
        ],
    }


def library_experience_evolution_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_EVOLUTION_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "经验进化候选",
        "en_name": "Experience Evolution Candidates",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "candidate_sources": [
            "library_trust_doctor_attention",
            "experience_history_replay_status",
            "zhixing_replay_feedback",
        ],
        "target_shelves": ["xingce", "toolbook", "errata"],
        "promotion_rule": "candidate_only_until_user_review_and_authorized_adoption_gate",
        "forbidden_by_default": [
            "write_raw",
            "write_zhiyi",
            "write_xingce",
            "write_toolbook",
            "write_errata",
            "write_markdown_file",
            "auto_adopt_experience",
        ],
    }


def library_experience_review_action_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "经验候选复核动作",
        "en_name": "Experience Candidate Review Action",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "source_contract": LIBRARY_EXPERIENCE_EVOLUTION_CONTRACT,
        "allowed_actions": EXPERIENCE_REVIEW_ACTIONS,
        "target_shelves": ["xingce", "toolbook", "errata"],
        "action_rule": "dry_run_receipt_only_until_separate_authorized_apply_gate",
        "forbidden_by_default": [
            "write_raw",
            "write_zhiyi",
            "write_xingce",
            "write_toolbook",
            "write_errata",
            "write_markdown_file",
            "auto_adopt_experience",
            "change_candidate_status",
        ],
    }


def library_experience_review_apply_gate_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_REVIEW_APPLY_GATE_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "经验复核采纳门禁",
        "en_name": "Experience Review Apply Gate",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "source_contract": LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
        "authorization_required": EXPERIENCE_REVIEW_APPLY_CONFIRMATIONS,
        "ready_means": "authorization_complete_for_future_apply_only",
        "target_shelves": ["xingce", "toolbook", "errata"],
        "forbidden_by_default": [
            "write_raw",
            "write_zhiyi",
            "write_xingce",
            "write_toolbook",
            "write_errata",
            "write_markdown_file",
            "auto_adopt_experience",
        ],
    }


def library_experience_validation_report_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_VALIDATION_REPORT_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "经验采纳验证报告",
        "en_name": "Experience Validation Report",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "source_contracts": [
            LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
            LIBRARY_EXPERIENCE_HISTORY_CONTRACT,
            "zhixing_replay_dry_run",
        ],
        "validation_sources": [
            "source_refs",
            "verbatim_excerpt",
            "acceptance_checks",
            "experience_history",
            "replay_summary",
        ],
        "gate_rule": "future_apply_should_use_report_passed_before_authorized_apply",
        "forbidden_by_default": [
            "write_raw",
            "write_zhiyi",
            "write_xingce",
            "write_toolbook",
            "write_errata",
            "write_markdown_file",
            "auto_adopt_experience",
            "treat_boolean_confirmation_as_validation_evidence",
        ],
    }


def library_experience_validation_receipt_schema_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_VALIDATION_RECEIPT_SCHEMA_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "经验验证回执格式",
        "en_name": "Experience Validation Receipt Schema",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "source_contract": LIBRARY_EXPERIENCE_VALIDATION_REPORT_CONTRACT,
        "optional_source_contracts": [
            LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
            LIBRARY_EXPERIENCE_REVIEW_QUEUE_CONTRACT,
        ],
        "receipt_types": ["experience_validation_receipt"],
        "schema_rule": "receipt_shapes_only_no_validation_or_candidate_status_write",
        "forbidden_by_default": [
            "write_raw",
            "write_zhiyi",
            "write_xingce",
            "write_toolbook",
            "write_errata",
            "write_markdown_file",
            "write_validation_result",
            "change_candidate_status",
            "auto_adopt_experience",
        ],
    }


def library_experience_review_queue_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_REVIEW_QUEUE_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "经验候选复核队列",
        "en_name": "Experience Review Queue",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "source_contracts": [
            LIBRARY_EXPERIENCE_EVOLUTION_CONTRACT,
            LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
            LIBRARY_EXPERIENCE_VALIDATION_REPORT_CONTRACT,
        ],
        "queue_buckets": [
            "ready_for_review",
            "needs_validation",
            "needs_source_evidence",
            "should_errata",
            "defer",
        ],
        "queue_rule": "triage_only_no_candidate_status_change",
        "forbidden_by_default": [
            "write_raw",
            "write_zhiyi",
            "write_xingce",
            "write_toolbook",
            "write_errata",
            "write_markdown_file",
            "auto_adopt_experience",
            "change_candidate_status",
        ],
    }


def library_experience_apply_receipt_schema_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_APPLY_RECEIPT_SCHEMA_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "经验采纳回执格式",
        "en_name": "Experience Apply Receipt Schema",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "source_contract": LIBRARY_EXPERIENCE_REVIEW_APPLY_GATE_CONTRACT,
        "receipt_types": [
            "experience_apply_receipt",
            "experience_rollback_receipt",
            "experience_supersede_receipt",
            "experience_errata_receipt",
        ],
        "target_shelves": ["xingce", "toolbook", "errata"],
        "schema_rule": "receipt_shapes_only_no_durable_write",
        "forbidden_by_default": [
            "write_raw",
            "write_zhiyi",
            "write_xingce",
            "write_toolbook",
            "write_errata",
            "write_markdown_file",
            "auto_adopt_experience",
        ],
    }


def library_experience_apply_package_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_APPLY_PACKAGE_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "经验采纳包",
        "en_name": "Experience Apply Package",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "source_contracts": [
            LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
            LIBRARY_EXPERIENCE_VALIDATION_RECEIPT_SCHEMA_CONTRACT,
            LIBRARY_EXPERIENCE_REVIEW_APPLY_GATE_CONTRACT,
            LIBRARY_EXPERIENCE_APPLY_RECEIPT_SCHEMA_CONTRACT,
        ],
        "package_rule": "final_preview_only_ready_does_not_apply",
        "target_shelves": ["xingce", "toolbook", "errata"],
        "forbidden_by_default": [
            "write_raw",
            "write_zhiyi",
            "write_xingce",
            "write_toolbook",
            "write_errata",
            "write_markdown_file",
            "write_apply_receipt",
            "change_candidate_status",
            "auto_adopt_experience",
        ],
    }


def _experience_flow_stage_contracts() -> list[dict]:
    return [
        {
            "stage": "experience_evolution",
            "order": 1,
            "contract": LIBRARY_EXPERIENCE_EVOLUTION_CONTRACT,
            "function": "build_experience_evolution_candidates_dry_run",
            "role": "source_backed_candidate_generation",
            "writes_allowed": False,
            "required_before_next": ["candidate_id", "target_shelf", "source_refs", "verbatim_excerpt"],
        },
        {
            "stage": "review_action",
            "order": 2,
            "contract": LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
            "function": "build_experience_review_actions_dry_run",
            "role": "human_review_intent_preview",
            "writes_allowed": False,
            "required_before_next": ["review_action_id", "requested_action", "planned_lifecycle_status"],
        },
        {
            "stage": "validation_report",
            "order": 3,
            "contract": LIBRARY_EXPERIENCE_VALIDATION_REPORT_CONTRACT,
            "function": "build_experience_validation_report_dry_run",
            "role": "source_history_replay_evidence_report",
            "writes_allowed": False,
            "required_before_next": ["source_refs", "verbatim_excerpt", "acceptance_checks", "history_or_replay_evidence"],
        },
        {
            "stage": "validation_receipt",
            "order": 4,
            "contract": LIBRARY_EXPERIENCE_VALIDATION_RECEIPT_SCHEMA_CONTRACT,
            "function": "build_experience_validation_receipt_schema_dry_run",
            "role": "validation_result_receipt_preview",
            "writes_allowed": False,
            "required_before_next": ["validation_receipt_id", "would_allow_apply_gate"],
        },
        {
            "stage": "review_queue",
            "order": 5,
            "contract": LIBRARY_EXPERIENCE_REVIEW_QUEUE_CONTRACT,
            "function": "build_experience_review_queue_dry_run",
            "role": "candidate_triage_without_status_change",
            "writes_allowed": False,
            "required_before_next": ["bucket", "recommended_next_step"],
        },
        {
            "stage": "apply_gate",
            "order": 6,
            "contract": LIBRARY_EXPERIENCE_REVIEW_APPLY_GATE_CONTRACT,
            "function": "build_experience_review_apply_gate_dry_run",
            "role": "authorization_and_validation_receipt_gate",
            "writes_allowed": False,
            "required_before_next": ["authorization_complete", "validation_receipts_allow_gate", "status"],
        },
        {
            "stage": "apply_receipt_schema",
            "order": 7,
            "contract": LIBRARY_EXPERIENCE_APPLY_RECEIPT_SCHEMA_CONTRACT,
            "function": "build_experience_apply_receipt_schema_dry_run",
            "role": "apply_rollback_supersede_errata_receipt_shapes",
            "writes_allowed": False,
            "required_before_next": ["receipt_id", "rollback_plan", "source_evidence_complete"],
        },
        {
            "stage": "apply_package",
            "order": 8,
            "contract": LIBRARY_EXPERIENCE_APPLY_PACKAGE_CONTRACT,
            "function": "build_experience_apply_package_dry_run",
            "role": "final_preview_before_future_authorized_apply",
            "writes_allowed": False,
            "required_before_next": ["package_id", "ready_for_authorized_apply", "authorized_apply_performed_false"],
        },
    ]


def library_experience_flow_overview_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_FLOW_OVERVIEW_CONTRACT,
        "version": LIBRARY_VERSION,
        "zh_name": "经验链路总览",
        "en_name": "Experience Flow Overview",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "stage_count": 8,
        "stages": _experience_flow_stage_contracts(),
        "forbidden_everywhere": [
            "write_raw",
            "write_zhiyi",
            "write_xingce",
            "write_toolbook",
            "write_errata",
            "write_markdown_file",
            "write_apply_receipt",
            "change_candidate_status",
            "auto_adopt_experience",
        ],
        "route_rule": "overview_only_not_live_apply",
    }


def library_index_projection_contract() -> dict:
    return {
        "ok": True,
        "contract": LIBRARY_INDEX_PROJECTION_CONTRACT,
        "ai_readable_projection_profile": AI_READABLE_PROJECTION_PROFILE,
        "projection_layer": "L0_library_index_projection",
        "source_authority_layer": "L2_raw_source_record",
        "version": LIBRARY_VERSION,
        "zh_name": "馆藏目录投影",
        "en_name": "Library Index Projection",
        "read_only": True,
        "write_performed": False,
        "not_a_new_memory_layer": True,
        "projection_of": "five_shelf_library_catalog",
        "anchored_by": "library_id",
        "format": "markdown_index_with_json_compatible_frontmatter",
        "requires_obsidian": False,
        "raw_authority_preserved": True,
        "purpose": "Give humans and agents a compact first page before opening specific library notes.",
        "shelves": list(ZHIXING_SHELVES.keys()),
        "index_sections": ["overview", "shelves", "active_attention", "sources_policy"],
        "forbidden_by_default": [
            "create_sixth_layer",
            "write_markdown_file",
            "replace_raw_or_source_refs",
            "require_obsidian_app_or_cli",
            "scan_global_raw_pool_without_permission",
        ],
    }


def _library_note_slug(card: dict) -> str:
    return "-".join([
        str(card.get("shelf") or "library"),
        _slug(card.get("library_id") or card.get("title") or "note", 64),
    ]).strip("-") + ".md"


def library_note_projection_for_card(card: dict) -> dict:
    refs = card.get("source_refs") if isinstance(card.get("source_refs"), dict) else {}
    evidence = card.get("evidence_contract") if isinstance(card.get("evidence_contract"), dict) else {}
    relations = {
        "relates_to": _string_list(card.get("relates_to")),
        "supersedes": _string_list(card.get("supersedes")),
        "depends_on": _string_list(card.get("depends_on")),
        "blocked_by": _string_list(card.get("blocked_by")),
        "proven_by": _string_list(card.get("proven_by")),
        "contradicts": _string_list(card.get("contradicts")),
        "conflicts_with": _string_list(card.get("conflicts_with")),
    }
    return {
        "contract": LIBRARY_NOTE_PROJECTION_CONTRACT,
        "ai_readable_projection_profile": AI_READABLE_PROJECTION_PROFILE,
        "projection_layer": "L1_library_note_projection",
        "source_authority_layer": "L2_raw_source_record",
        "projection_type": "library_note_projection",
        "not_a_new_memory_layer": True,
        "requires_obsidian": False,
        "format": "markdown",
        "path_hint": _library_note_slug(card),
        "library_id": card.get("library_id", ""),
        "shelf": card.get("shelf", ""),
        "status": card.get("status", ""),
        "source_refs_available": bool(refs),
        "raw_authority_preserved": True,
        "verbatim_excerpt_required": bool(evidence.get("verbatim_excerpt_required", True)),
        "valid_experience_record": bool(evidence.get("valid_experience_record")),
        "relations": relations,
        "sections": LIBRARY_NOTE_SECTIONS,
        "write_performed": False,
    }


def _projection_card_from_record(record: dict, *, query: str = "", raw_status: str = "", raw_excerpt: str = "") -> dict:
    if isinstance(record.get("library_card"), dict):
        return dict(record["library_card"])
    if record.get("library_id") and record.get("shelf") and isinstance(record.get("evidence_contract"), dict):
        return dict(record)
    return library_card_for(record, query=query, raw_status=raw_status, raw_excerpt=raw_excerpt)


def render_library_note_markdown(record: dict, *, query: str = "", raw_status: str = "", raw_excerpt: str = "") -> str:
    card = _projection_card_from_record(record, query=query, raw_status=raw_status, raw_excerpt=raw_excerpt)
    refs = card.get("source_refs") if isinstance(card.get("source_refs"), dict) else {}
    evidence = card.get("evidence_contract") if isinstance(card.get("evidence_contract"), dict) else {}
    work = card.get("work_experience") if isinstance(card.get("work_experience"), dict) else {}
    projection = library_note_projection_for_card(card)
    title = str(card.get("title") or card.get("library_id") or "Library Note").strip()
    summary = str(card.get("summary") or "").strip()
    excerpt = str(card.get("verbatim_excerpt") or "").strip()
    frontmatter = {
        "type": "Library Note Projection",
        "contract": LIBRARY_NOTE_PROJECTION_CONTRACT,
        "ai_readable_projection_profile": AI_READABLE_PROJECTION_PROFILE,
        "projection_layer": "L1_library_note_projection",
        "source_authority_layer": "L2_raw_source_record",
        "library_id": card.get("library_id", ""),
        "shelf": card.get("shelf", ""),
        "status": card.get("status", ""),
        "version": card.get("version", 1),
        "source_refs": refs,
        "verbatim_excerpt_required": bool(evidence.get("verbatim_excerpt_required", True)),
        "raw_authority_preserved": True,
        "not_a_new_memory_layer": True,
        "supersedes": _string_list(card.get("supersedes")),
        "conflicts_with": _string_list(card.get("conflicts_with")),
        "last_verified_at": card.get("last_verified_at") or "",
        "path_hint": projection["path_hint"],
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {_frontmatter_value(value)}")
    lines.extend(["---", "", f"# {title}", ""])
    lines.extend([
        "## What This Is",
        summary or card.get("shelf_label", "") or "-",
        "",
        "## Applies When",
    ])
    applies = work.get("applicable_scope") or card.get("rank_reason") or ""
    lines.extend(_markdown_list(applies))
    lines.extend(["", "## Procedure Or Judgment"])
    if work:
        lines.extend(_markdown_list(work.get("action_strategy") or summary))
    elif card.get("shelf") == "raw":
        lines.append("This note points to raw source evidence and should not rewrite it.")
    else:
        lines.append(summary or "-")
    lines.extend(["", "## Avoid"])
    avoid = work.get("avoid_conditions") or card.get("conflicts_with") or []
    if card.get("shelf") == "errata":
        avoid = avoid or ["Do not use superseded or conflicting records without checking source refs."]
    lines.extend(_markdown_list(avoid))
    lines.extend(["", "## Verification"])
    verification = work.get("acceptance_checks") or []
    if evidence.get("missing_fields"):
        verification = _string_list(verification) + [f"Missing evidence fields: {', '.join(evidence.get('missing_fields') or [])}"]
    lines.extend(_markdown_list(verification))
    lines.extend(["", "## Sources"])
    lines.extend(_markdown_source_refs(refs))
    if excerpt:
        lines.extend(["", "### Verbatim Excerpt", excerpt])
    lines.extend(["", "## Relations"])
    relation_lines = []
    relations = projection["relations"]
    for key in LIBRARY_RELATION_FIELDS:
        values = relations.get(key) if isinstance(relations, dict) else []
        if values:
            relation_lines.append(f"- {key}: `{json.dumps(values, ensure_ascii=False)}`")
    lines.extend(relation_lines or ["- none"])
    return "\n".join(lines) + "\n"


def build_library_note_projection_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    record = body.get("record") if isinstance(body.get("record"), dict) else body
    card = _projection_card_from_record(
        record,
        query=str(body.get("query") or ""),
        raw_status=str(body.get("raw_status") or ""),
        raw_excerpt=str(body.get("raw_excerpt") or ""),
    )
    markdown = render_library_note_markdown(card)
    projection = library_note_projection_for_card(card)
    return {
        "ok": bool(card.get("library_id")),
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "contract": LIBRARY_NOTE_PROJECTION_CONTRACT,
        "ai_readable_projection_profile": AI_READABLE_PROJECTION_PROFILE,
        "source_authority_layer": "L2_raw_source_record",
        "projection": projection,
        "library_card": card,
        "markdown": markdown,
        "notes": [
            "library_note_projection_is_not_a_sixth_layer",
            "markdown_is_a_readable_projection_not_raw_authority",
            "no_file_created_or_appended",
        ],
    }


def library_card_for(record: dict, *, query: str = "", raw_status: str = "", raw_excerpt: str = "") -> dict:
    refs = source_refs_for(record)
    shelf = shelf_for(record)
    library_id = library_id_for(record)
    excerpt = _verbatim_excerpt_for(record, raw_excerpt)
    supersedes = _as_list(record.get("supersedes"))
    conflicts_with = _as_list(record.get("conflicts_with"))
    sediment = build_sediment_link(
        record,
        library_id=library_id,
        sediment_layer=shelf,
        source_refs=refs,
    )
    card = {
        "library_id": library_id,
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
        "time_river_sediment": sediment,
        "matched_by": matched_by_for(record, query=query, raw_status=raw_status),
        "rank_reason": rank_reason_for(record, query=query, raw_status=raw_status),
        "typed_graph": typed_graph_for(record),
        "created_at": record.get("created_at") or record.get("extracted_at") or record.get("captured_at") or "",
        "updated_at": record.get("updated_at") or record.get("extracted_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    for relation_field in ("relates_to", "depends_on", "blocked_by", "proven_by", "contradicts"):
        values = _string_list(record.get(relation_field))
        if values:
            card[relation_field] = values
    if shelf == "xingce":
        card["xingce_lifecycle"] = xingce_lifecycle_for(record)
        card["work_experience"] = xingce_work_fields_for(record)
    card["library_note_projection"] = library_note_projection_for_card(card)
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


def _records_from_body(body: dict) -> list[dict]:
    records = body.get("records") if isinstance(body.get("records"), list) else []
    if records:
        return [record for record in records if isinstance(record, dict)]
    record = body.get("record") if isinstance(body.get("record"), dict) else {}
    return [record] if record else []


def _query_terms(query: str) -> list[str]:
    compact = str(query or "").strip().lower()
    if not compact:
        return []
    terms = re.split(r"[\s,，。；;:：/\\|]+", compact)
    return [term for term in terms if term]


def _record_search_text(record: dict, card: dict) -> str:
    work = card.get("work_experience") if isinstance(card.get("work_experience"), dict) else {}
    parts = [
        record.get("library_id", ""),
        record.get("exp_id", ""),
        record.get("summary", ""),
        record.get("detail", ""),
        record.get("raw_excerpt", ""),
        record.get("verbatim_excerpt", ""),
        card.get("library_id", ""),
        card.get("title", ""),
        card.get("summary", ""),
        card.get("verbatim_excerpt", ""),
        work.get("work_scenario", ""),
        work.get("applicable_scope", ""),
        " ".join(_string_list(work.get("action_strategy"))),
        " ".join(_string_list(work.get("avoid_conditions"))),
        " ".join(_string_list(work.get("acceptance_checks"))),
    ]
    return "\n".join(str(part or "") for part in parts).lower()


def _is_risky_query(query: str, body: dict) -> bool:
    if bool(body.get("risk_high") or body.get("errata_first")):
        return True
    lowered = str(query or "").lower()
    risk_markers = [
        "不对",
        "错",
        "纠错",
        "勘误",
        "冲突",
        "覆盖",
        "废弃",
        "superseded",
        "deprecated",
        "conflict",
        "errata",
        "security",
        "安全",
        "token",
        "secret",
    ]
    return any(marker in lowered for marker in risk_markers)


def _active_bookmark_score(record: dict, card: dict, *, query: str, body: dict) -> tuple[int, list[str]]:
    current_ids = set(_string_list(body.get("current_library_ids") or body.get("library_ids")))
    terms = _query_terms(query)
    text = _record_search_text(record, card)
    score = 0
    reasons: list[str] = []
    library_id = str(card.get("library_id") or "")
    if library_id in current_ids:
        score += 80
        reasons.append("explicit_current_library_id")
    matched_terms = [term for term in terms if term and term in text]
    if matched_terms:
        score += min(len(matched_terms), 6) * 12
        reasons.append("query_terms_matched")
    if card.get("source_refs"):
        score += 8
        reasons.append("source_refs_available")
    if card.get("verbatim_excerpt"):
        score += 8
        reasons.append("verbatim_excerpt_available")
    if card.get("evidence_contract", {}).get("valid_experience_record"):
        score += 6
        reasons.append("evidence_contract_valid")
    shelf = str(card.get("shelf") or "")
    if shelf == "xingce":
        score += 8
        reasons.append("work_experience_shelf")
    if shelf == "toolbook":
        score += 4
        reasons.append("tool_fact_shelf")
    if _is_risky_query(query, body) and shelf == "errata":
        score += 120
        reasons.append("errata_first_for_risky_query")
    if (
        card.get("conflicts_with")
        or card.get("supersedes")
        or card.get("contradicts")
        or record.get("conflicts_with")
        or record.get("supersedes")
        or record.get("contradicts")
    ):
        score += 10
        reasons.append("relation_warning_available")
    if not reasons:
        reasons.append("candidate_from_supplied_source_pool")
    return score, reasons


def build_active_bookmarks_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    records = _records_from_body(body)
    query = str(body.get("query") or body.get("task") or body.get("message") or "").strip()
    task_id = str(body.get("task_id") or body.get("case_id") or "current-task").strip()
    try:
        limit = int(body.get("limit") or 5)
    except Exception:
        limit = 5
    limit = max(1, min(limit, 20))
    candidates = []
    for index, record in enumerate(records):
        attached = attach_library_card(record, query=query)
        card = attached.get("library_card", {})
        score, reasons = _active_bookmark_score(attached, card, query=query, body=body)
        candidates.append({
            "index": index,
            "score": score,
            "reasons": reasons,
            "record": attached,
            "card": card,
        })
    candidates.sort(
        key=lambda item: (
            1 if item["card"].get("shelf") == "errata" and _is_risky_query(query, body) else 0,
            item["score"],
            -item["index"],
        ),
        reverse=True,
    )
    selected = candidates[:limit]
    bookmarks = []
    compact_context = []
    for rank, item in enumerate(selected, start=1):
        card = item["card"]
        bookmark = {
            "rank": rank,
            "library_id": card.get("library_id", ""),
            "shelf": card.get("shelf", ""),
            "title": card.get("title", ""),
            "status": card.get("status", ""),
            "priority": item["score"],
            "reason": "; ".join(item["reasons"]),
            "source_ref_status": card.get("source_ref_status", ""),
            "raw_available": bool(card.get("raw_available")),
            "valid_experience_record": bool(card.get("evidence_contract", {}).get("valid_experience_record")),
            "not_a_new_memory_layer": True,
        }
        bookmarks.append(bookmark)
        compact_context.append({
            "library_id": bookmark["library_id"],
            "shelf": bookmark["shelf"],
            "title": bookmark["title"],
            "why_active": bookmark["reason"],
            "source_refs": card.get("source_refs", {}),
        })
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "contract": LIBRARY_ACTIVE_BOOKMARKS_CONTRACT,
        "task_id": task_id,
        "query": query,
        "limit": limit,
        "source_pool_count": len(records),
        "global_memory_scan_performed": False,
        "not_a_new_memory_layer": True,
        "recall_volume_control": {
            "input_count": len(records),
            "output_count": len(bookmarks),
            "dropped_count": max(len(records) - len(bookmarks), 0),
            "limit_applied": len(records) > len(bookmarks),
        },
        "errata_first_applied": bool(_is_risky_query(query, body)),
        "bookmarks": bookmarks,
        "compact_context": compact_context,
        "notes": [
            "active_bookmarks_are_current_task_view_only",
            "bookmarks_reference_existing_library_ids",
            "no_bookmark_store_or_memory_write",
        ],
    }


def _events_for_library_id(events: list[dict], library_id: str) -> list[dict]:
    result = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if str(event.get("library_id") or event.get("target_library_id") or "").strip() == library_id:
            result.append(event)
    return result


def _max_timestamp(values: list[Any]) -> str:
    strings = [str(value or "").strip() for value in values if str(value or "").strip()]
    return max(strings) if strings else ""


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _experience_history_for_record(record: dict, events: list[dict]) -> dict:
    attached = attach_library_card(record)
    card = attached.get("library_card", {})
    library_id = str(card.get("library_id") or "")
    embedded = record.get("experience_history") if isinstance(record.get("experience_history"), dict) else {}
    xingce = record.get("_xingce") if isinstance(record.get("_xingce"), dict) else {}
    related_events = _events_for_library_id(events, library_id)
    event_types = [str(event.get("event_type") or event.get("type") or "").strip() for event in related_events]
    accepted_events = [event for event in related_events if str(event.get("event_type") or event.get("type") or "") in ("accepted", "adopted", "validation_passed")]
    rejected_events = [event for event in related_events if str(event.get("event_type") or event.get("type") or "") in ("rejected", "validation_failed")]
    replay_events = [event for event in related_events if "replay" in str(event.get("event_type") or event.get("type") or "")]
    failure_modes = _string_list(embedded.get("failure_modes") or record.get("failure_modes"))
    for event in related_events:
        failure_modes.extend(_string_list(event.get("failure_mode") or event.get("failure_modes")))
    failure_modes = list(dict.fromkeys(failure_modes))
    usage_count = _safe_int(embedded.get("usage_count") or record.get("usage_count") or xingce.get("usage_count")) + len(related_events)
    accepted_count = _safe_int(embedded.get("accepted_count") or record.get("accepted_count") or xingce.get("accepted_count")) + len(accepted_events)
    rejected_count = _safe_int(embedded.get("rejected_count") or record.get("rejected_count") or xingce.get("rejected_count")) + len(rejected_events)
    replay_count = _safe_int(embedded.get("replay_count") or record.get("replay_count") or xingce.get("replay_count")) + len(replay_events)
    validation_status = str(
        embedded.get("validation_status")
        or record.get("validation_status")
        or xingce.get("validation_status")
        or ""
    ).strip()
    if not validation_status:
        if rejected_count:
            validation_status = "has_failed_replay"
        elif accepted_count or replay_count:
            validation_status = "validated"
        else:
            validation_status = "needs_replay"
    history = {
        "contract": LIBRARY_EXPERIENCE_HISTORY_CONTRACT,
        "library_id": library_id,
        "shelf": card.get("shelf", ""),
        "title": card.get("title", ""),
        "status": card.get("status", ""),
        "usage_count": usage_count,
        "accepted_count": accepted_count,
        "rejected_count": rejected_count,
        "replay_count": replay_count,
        "last_replayed_at": embedded.get("last_replayed_at") or record.get("last_replayed_at") or _max_timestamp([event.get("at") or event.get("created_at") for event in replay_events]),
        "last_accepted_at": embedded.get("last_accepted_at") or record.get("last_accepted_at") or _max_timestamp([event.get("at") or event.get("created_at") for event in accepted_events]),
        "last_rejected_at": embedded.get("last_rejected_at") or record.get("last_rejected_at") or _max_timestamp([event.get("at") or event.get("created_at") for event in rejected_events]),
        "failure_modes": failure_modes,
        "validation_status": validation_status,
        "event_types": sorted({event_type for event_type in event_types if event_type}),
        "write_performed": False,
        "not_a_new_memory_layer": True,
    }
    return history


def build_experience_history_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    records = _records_from_body(body)
    events = body.get("events") if isinstance(body.get("events"), list) else []
    histories = []
    skipped = []
    for record in records:
        attached = attach_library_card(record)
        card = attached.get("library_card", {})
        if card.get("shelf") != "xingce":
            skipped.append({
                "library_id": card.get("library_id", ""),
                "shelf": card.get("shelf", ""),
                "reason": "experience_history_targets_xingce_records",
            })
            continue
        histories.append(_experience_history_for_record(attached, events))
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "contract": LIBRARY_EXPERIENCE_HISTORY_CONTRACT,
        "not_a_new_memory_layer": True,
        "history_count": len(histories),
        "skipped_count": len(skipped),
        "histories": histories,
        "skipped": skipped,
        "summary": {
            "needs_replay_count": sum(1 for item in histories if item.get("validation_status") == "needs_replay"),
            "validated_count": sum(1 for item in histories if item.get("validation_status") == "validated"),
            "failed_replay_count": sum(1 for item in histories if item.get("validation_status") == "has_failed_replay"),
        },
        "notes": [
            "experience_history_is_read_only_projection",
            "usage_does_not_equal_truth",
            "lifecycle_status_not_changed",
        ],
    }


def _doctor_check(check_id: str, ok: bool, message: str) -> dict:
    return {
        "id": check_id,
        "status": "pass" if ok else "attention",
        "ok": bool(ok),
        "message": message,
    }


def build_library_trust_doctor_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    records = _records_from_body(body)
    query = str(body.get("query") or body.get("task") or "").strip()
    attached = [attach_library_card(record, query=query) for record in records]
    cards = [record.get("library_card", {}) for record in attached]
    by_shelf = {shelf: 0 for shelf in ZHIXING_SHELVES}
    for card in cards:
        shelf = str(card.get("shelf") or "")
        if shelf in by_shelf:
            by_shelf[shelf] += 1
    missing_source_refs = [card.get("library_id", "") for card in cards if not card.get("source_refs")]
    missing_excerpts = [card.get("library_id", "") for card in cards if not card.get("verbatim_excerpt")]
    invalid_evidence = [
        card.get("library_id", "")
        for card in cards
        if not card.get("evidence_contract", {}).get("valid_experience_record")
    ]
    xingce_cards = [card for card in cards if card.get("shelf") == "xingce"]
    xingce_needs_validation = [
        card.get("library_id", "")
        for card in xingce_cards
        if not _string_list(card.get("work_experience", {}).get("acceptance_checks"))
    ]
    note_ready = [
        card.get("library_id", "")
        for card in cards
        if card.get("library_note_projection", {}).get("not_a_new_memory_layer")
    ]
    active = build_active_bookmarks_dry_run({
        "records": attached,
        "query": query,
        "limit": body.get("bookmark_limit") or body.get("limit") or 5,
        "risk_high": body.get("risk_high"),
        "errata_first": body.get("errata_first"),
    })
    history = build_experience_history_dry_run({
        "records": attached,
        "events": body.get("events") if isinstance(body.get("events"), list) else [],
    })
    checks = [
        _doctor_check("source_refs_available", not missing_source_refs, f"missing source refs: {len(missing_source_refs)}"),
        _doctor_check("verbatim_excerpt_available", not missing_excerpts, f"missing verbatim excerpts: {len(missing_excerpts)}"),
        _doctor_check("raw_authority_preserved", True, "library notes remain projection only"),
        _doctor_check("library_note_projection_ready", len(note_ready) == len(cards), f"projection ready: {len(note_ready)}/{len(cards)}"),
        _doctor_check("xingce_has_validation", not xingce_needs_validation, f"xingce records without acceptance checks: {len(xingce_needs_validation)}"),
        _doctor_check("errata_visible", by_shelf.get("errata", 0) > 0 or not _is_risky_query(query, body), f"errata records visible: {by_shelf.get('errata', 0)}"),
        _doctor_check("active_bookmarks_compact", active["recall_volume_control"]["output_count"] <= active["limit"], f"bookmarks: {active['recall_volume_control']['output_count']}/{active['source_pool_count']}"),
    ]
    passed = [check["id"] for check in checks if check["ok"]]
    attention = [check["id"] for check in checks if not check["ok"]]
    if not records:
        doctor_status = "provide_records"
    elif attention:
        doctor_status = "attention_needed"
    else:
        doctor_status = "records_guarded"
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "contract": LIBRARY_TRUST_DOCTOR_CONTRACT,
        "doctor_status": doctor_status,
        "not_a_new_memory_layer": True,
        "record_count": len(records),
        "by_shelf": by_shelf,
        "checks": checks,
        "passed": passed,
        "attention": attention,
        "missing_source_refs": missing_source_refs,
        "missing_verbatim_excerpt": missing_excerpts,
        "invalid_evidence": invalid_evidence,
        "xingce_needs_validation": xingce_needs_validation,
        "active_bookmarks": active,
        "experience_history": history,
        "notes": [
            "library_trust_doctor_is_read_only_demo_safe",
            "doctor_checks_supplied_records_only",
            "no_raw_memory_index_or_markdown_write",
        ],
    }


def _index_entry_for_card(card: dict) -> dict:
    evidence = card.get("evidence_contract") if isinstance(card.get("evidence_contract"), dict) else {}
    projection = card.get("library_note_projection") if isinstance(card.get("library_note_projection"), dict) else library_note_projection_for_card(card)
    attention = []
    if not card.get("source_refs"):
        attention.append("missing_source_refs")
    if not card.get("verbatim_excerpt"):
        attention.append("missing_verbatim_excerpt")
    if evidence.get("missing_fields"):
        attention.extend(_string_list(evidence.get("missing_fields")))
    if card.get("shelf") == "errata":
        attention.append("errata_record")
    if card.get("conflicts_with"):
        attention.append("has_conflict")
    if card.get("supersedes"):
        attention.append("supersedes_other_record")
    attention = list(dict.fromkeys(attention))
    return {
        "library_id": card.get("library_id", ""),
        "shelf": card.get("shelf", ""),
        "title": card.get("title", ""),
        "status": card.get("status", ""),
        "summary": _compact_text(card.get("summary") or card.get("verbatim_excerpt") or "", 160),
        "source_ref_status": card.get("source_ref_status", ""),
        "valid_experience_record": bool(evidence.get("valid_experience_record")),
        "path_hint": projection.get("path_hint", ""),
        "attention": attention,
    }


def render_library_index_markdown(index: dict) -> str:
    title = str(index.get("title") or "Zhixing Library Index").strip()
    frontmatter = {
        "type": "Library Index Projection",
        "contract": LIBRARY_INDEX_PROJECTION_CONTRACT,
        "ai_readable_projection_profile": AI_READABLE_PROJECTION_PROFILE,
        "projection_layer": "L0_library_index_projection",
        "source_authority_layer": "L2_raw_source_record",
        "version": LIBRARY_VERSION,
        "not_a_new_memory_layer": True,
        "raw_authority_preserved": True,
        "record_count": index.get("record_count", 0),
        "shelves": list(ZHIXING_SHELVES.keys()),
    }
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {_frontmatter_value(value)}")
    lines.extend([
        "---",
        "",
        f"# {title}",
        "",
        "## Overview",
        "Five-shelf catalog projection.",
        "",
        "## Shelves",
    ])
    shelf_index = index.get("shelf_index") if isinstance(index.get("shelf_index"), dict) else {}
    for shelf in ZHIXING_SHELVES:
        shelf_block = shelf_index.get(shelf, {}) if isinstance(shelf_index.get(shelf), dict) else {}
        entries = shelf_block.get("entries") if isinstance(shelf_block.get("entries"), list) else []
        lines.extend([
            "",
            f"### {shelf}",
            f"- count: {shelf_block.get('count', 0)}",
        ])
        if not entries:
            lines.append("- empty")
            continue
        for entry in entries:
            attention = ",".join(_string_list(entry.get("attention"))) or "none"
            lines.append(
                f"- `{entry.get('library_id', '')}` {entry.get('title', '')} "
                f"[{entry.get('status', '')}; source={entry.get('source_ref_status', '')}; attention={attention}]"
            )
    attention_items = index.get("attention") if isinstance(index.get("attention"), list) else []
    lines.extend(["", "## Active Attention"])
    if attention_items:
        for item in attention_items:
            lines.append(f"- `{item.get('library_id', '')}`: {', '.join(_string_list(item.get('attention')))}")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Sources Policy",
        "- raw remains the authority",
        "- markdown index and notes are readable projections only",
        "- source refs and verbatim excerpts are required for trust",
    ])
    return "\n".join(lines) + "\n"


def build_library_index_projection_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    records = _records_from_body(body)
    title = str(body.get("title") or "Zhixing Library Index").strip()
    try:
        per_shelf_limit = int(body.get("per_shelf_limit") or 8)
    except Exception:
        per_shelf_limit = 8
    per_shelf_limit = max(1, min(per_shelf_limit, 50))
    cards = [attach_library_card(record).get("library_card", {}) for record in records]
    shelf_index = {}
    attention = []
    for shelf in ZHIXING_SHELVES:
        shelf_cards = [card for card in cards if card.get("shelf") == shelf]
        entries = [_index_entry_for_card(card) for card in shelf_cards]
        entries.sort(key=lambda entry: (entry["status"] != "active", entry["library_id"]))
        visible_entries = entries[:per_shelf_limit]
        shelf_index[shelf] = {
            "shelf": shelf,
            "label": ZHIXING_SHELVES[shelf],
            "count": len(entries),
            "visible_count": len(visible_entries),
            "truncated": len(entries) > len(visible_entries),
            "entries": visible_entries,
        }
        attention.extend(
            {"library_id": entry["library_id"], "shelf": shelf, "attention": entry["attention"]}
            for entry in entries
            if entry["attention"]
        )
    index = {
        "contract": LIBRARY_INDEX_PROJECTION_CONTRACT,
        "ai_readable_projection_profile": AI_READABLE_PROJECTION_PROFILE,
        "projection_layer": "L0_library_index_projection",
        "source_authority_layer": "L2_raw_source_record",
        "title": title,
        "record_count": len(records),
        "shelf_index": shelf_index,
        "attention": attention[:50],
        "not_a_new_memory_layer": True,
        "requires_obsidian": False,
        "raw_authority_preserved": True,
    }
    markdown = render_library_index_markdown(index)
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "markdown_write_performed": False,
        "contract": LIBRARY_INDEX_PROJECTION_CONTRACT,
        "ai_readable_projection_profile": AI_READABLE_PROJECTION_PROFILE,
        "projection_layer": "L0_library_index_projection",
        "source_authority_layer": "L2_raw_source_record",
        "not_a_new_memory_layer": True,
        "requires_obsidian": False,
        "record_count": len(records),
        "per_shelf_limit": per_shelf_limit,
        "index": index,
        "markdown": markdown,
        "notes": [
            "library_index_projection_is_first_page_only",
            "index_entries_reference_existing_library_ids",
            "no_index_file_created_or_appended",
        ],
    }


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
        "ai_readable_projection": ai_readable_library_projection_contract(),
        "library_note_projection": library_note_projection_contract(),
        "admission_candidate": library_admission_candidate_contract(),
        "active_bookmarks": library_active_bookmarks_contract(),
        "experience_history": library_experience_history_contract(),
        "trust_doctor": library_trust_doctor_contract(),
        "index_projection": library_index_projection_contract(),
        "experience_evolution": library_experience_evolution_contract(),
        "experience_review_action": library_experience_review_action_contract(),
        "experience_validation_report": library_experience_validation_report_contract(),
        "experience_validation_receipt_schema": library_experience_validation_receipt_schema_contract(),
        "experience_review_queue": library_experience_review_queue_contract(),
        "experience_review_apply_gate": library_experience_review_apply_gate_contract(),
        "experience_apply_receipt_schema": library_experience_apply_receipt_schema_contract(),
        "experience_apply_package": library_experience_apply_package_contract(),
        "experience_flow_overview": library_experience_flow_overview_contract(),
        "time_river_sediment": get_time_river_sediment_contract(),
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


def _evolution_candidate_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"experience-evolution|{kind}|{value}".encode("utf-8")).hexdigest()[:12]
    return f"evolution-{kind}-{digest}"


def _first_source_refs_from_records(records: list[dict], library_id: str = "") -> dict:
    for record in records:
        if not isinstance(record, dict):
            continue
        attached = attach_library_card(record)
        card = attached.get("library_card", {}) if isinstance(attached.get("library_card"), dict) else {}
        if library_id:
            current_id = card.get("library_id") or attached.get("library_id") or record.get("library_id") or ""
            if current_id != library_id:
                continue
        refs = source_refs_for(attached)
        if refs:
            return refs
    return {}


def _first_verbatim_excerpt_from_records(records: list[dict], library_id: str = "") -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        attached = attach_library_card(record)
        card = attached.get("library_card", {}) if isinstance(attached.get("library_card"), dict) else {}
        if library_id:
            current_id = card.get("library_id") or attached.get("library_id") or record.get("library_id") or ""
            if current_id != library_id:
                continue
        excerpt = _verbatim_excerpt_for(attached) or str(card.get("verbatim_excerpt") or "").strip()
        if excerpt:
            return excerpt
    return ""


def _first_acceptance_checks_from_records(records: list[dict], library_id: str = "") -> list[str]:
    for record in records:
        if not isinstance(record, dict):
            continue
        attached = attach_library_card(record)
        card = attached.get("library_card", {}) if isinstance(attached.get("library_card"), dict) else {}
        if library_id:
            current_id = card.get("library_id") or attached.get("library_id") or record.get("library_id") or ""
            if current_id != library_id:
                continue
        checks = _string_list(
            attached.get("acceptance_checks")
            or attached.get("_xingce", {}).get("acceptance_checks")
            or card.get("work_experience", {}).get("acceptance_checks")
        )
        if checks:
            return checks
    return []


def _candidate_base(candidate_type: str, target_shelf: str, reason: str, source_refs: dict | None = None) -> dict:
    candidate_id = _evolution_candidate_id(candidate_type, reason)
    return {
        "candidate_id": candidate_id,
        "candidate_type": candidate_type,
        "library_shelf": target_shelf,
        "target_shelf": target_shelf,
        "status": "candidate",
        "lifecycle_status": "candidate",
        "reason": reason,
        "source_refs": source_refs if isinstance(source_refs, dict) else {},
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "requires_authorization": True,
    }


def build_experience_evolution_candidates_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    records = body.get("records") if isinstance(body.get("records"), list) else []
    trust = body.get("trust_doctor") if isinstance(body.get("trust_doctor"), dict) else {}
    replay = body.get("replay") if isinstance(body.get("replay"), dict) else {}
    history = body.get("experience_history") if isinstance(body.get("experience_history"), dict) else {}
    if not trust and records:
        trust = build_library_trust_doctor_dry_run({
            "query": body.get("query") or body.get("task") or "",
            "records": records,
            "events": body.get("events") if isinstance(body.get("events"), list) else [],
        })
    if not history and trust:
        history = trust.get("experience_history") if isinstance(trust.get("experience_history"), dict) else {}

    candidates: list[dict] = []
    missing_source = _as_list(trust.get("missing_source_refs"))
    missing_excerpt = _as_list(trust.get("missing_verbatim_excerpt"))
    invalid_evidence = _as_list(trust.get("invalid_evidence"))
    xingce_needs_validation = _as_list(trust.get("xingce_needs_validation"))
    attention = _as_list(trust.get("attention"))

    for library_id in missing_source + missing_excerpt + invalid_evidence:
        if not str(library_id or "").strip():
            continue
        candidate = _candidate_base(
            "experience_errata_candidate",
            "errata",
            f"trust_doctor_attention:{library_id}",
            _first_source_refs_from_records(records, str(library_id)),
        )
        candidate.update({
            "target_library_id": library_id,
            "recommended_action": "review_source_refs_or_demote_until_evidence_is_restored",
            "attention": sorted(set([*missing_source, *missing_excerpt, *invalid_evidence]) & {library_id}),
            "verbatim_excerpt_required": True,
            "verbatim_excerpt": _first_verbatim_excerpt_from_records(records, str(library_id)),
        })
        candidates.append(candidate)

    for library_id in xingce_needs_validation:
        if not str(library_id or "").strip():
            continue
        candidate = _candidate_base(
            "experience_xingce_validation_candidate",
            "xingce",
            f"xingce_missing_validation:{library_id}",
            _first_source_refs_from_records(records, str(library_id)),
        )
        candidate.update({
            "target_library_id": library_id,
            "recommended_action": "add_or_verify_acceptance_checks_before_adoption",
            "required_fields": ["acceptance_checks", "source_refs", "verbatim_excerpt"],
            "verbatim_excerpt": _first_verbatim_excerpt_from_records(records, str(library_id)),
            "acceptance_checks": _first_acceptance_checks_from_records(records, str(library_id)),
        })
        candidates.append(candidate)

    histories = history.get("histories") if isinstance(history.get("histories"), list) else []
    for item in histories:
        if not isinstance(item, dict):
            continue
        status = str(item.get("validation_status") or "").strip()
        if status not in ("needs_replay", "has_failed_replay"):
            continue
        library_id = str(item.get("library_id") or "").strip()
        candidate = _candidate_base(
            "experience_replay_validation_candidate",
            "xingce" if status == "needs_replay" else "errata",
            f"experience_history:{status}:{library_id}",
            _first_source_refs_from_records(records, library_id),
        )
        candidate.update({
            "target_library_id": library_id,
            "recommended_action": "run_replay_before_promotion" if status == "needs_replay" else "review_failed_replay_before_future_recall",
            "validation_status": status,
            "event_count": item.get("event_count", 0),
            "verbatim_excerpt": _first_verbatim_excerpt_from_records(records, library_id),
            "acceptance_checks": _first_acceptance_checks_from_records(records, library_id),
        })
        candidates.append(candidate)

    replay_feedback = replay.get("feedback_candidates") if isinstance(replay.get("feedback_candidates"), dict) else {}
    for item in replay_feedback.get("candidates", []) if isinstance(replay_feedback.get("candidates"), list) else []:
        if not isinstance(item, dict):
            continue
        ctype = str(item.get("candidate_type") or "")
        if ctype == "replay_errata_candidate":
            target_shelf = "errata"
            evolution_type = "experience_replay_errata_candidate"
        elif ctype == "proactive_resurfacing_candidate":
            target_shelf = "xingce"
            evolution_type = "experience_proactive_resurfacing_candidate"
        elif ctype == "replay_adoption_candidate":
            target_shelf = "xingce"
            evolution_type = "experience_replay_adoption_candidate"
        else:
            continue
        marker = item.get("target_library_id") or item.get("resurfacing_marker") or item.get("candidate_id") or ctype
        candidate = _candidate_base(
            evolution_type,
            target_shelf,
            f"replay_feedback:{ctype}:{marker}",
            _first_source_refs_from_records(records, str(item.get("target_library_id") or "")),
        )
        candidate.update({
            "source_feedback_candidate_id": item.get("candidate_id", ""),
            "target_library_id": item.get("target_library_id", ""),
            "recommended_action": item.get("recommended_action") or "review_replay_feedback",
            "replay_reason": item.get("reason", ""),
            "resurfacing_marker": item.get("resurfacing_marker", ""),
            "verbatim_excerpt": _first_verbatim_excerpt_from_records(records, str(item.get("target_library_id") or "")),
            "acceptance_checks": _first_acceptance_checks_from_records(records, str(item.get("target_library_id") or "")),
        })
        candidates.append(candidate)

    unique = {}
    for candidate in candidates:
        unique.setdefault(candidate["candidate_id"], candidate)
    candidates = list(unique.values())
    for candidate in candidates:
        candidate["library_card"] = library_card_for(candidate)

    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "markdown_write_performed": False,
        "contract": LIBRARY_EXPERIENCE_EVOLUTION_CONTRACT,
        "not_a_new_memory_layer": True,
        "candidate_count": len(candidates),
        "candidate_types": sorted({candidate["candidate_type"] for candidate in candidates}),
        "target_shelf_counts": {
            shelf: sum(1 for candidate in candidates if candidate.get("target_shelf") == shelf)
            for shelf in ["xingce", "toolbook", "errata"]
        },
        "candidates": candidates,
        "attention_sources": {
            "trust_doctor": attention,
            "history_count": len(histories),
            "replay_feedback_count": replay_feedback.get("candidate_count", 0),
        },
        "authorization_required_for_apply": True,
        "notes": [
            "experience_evolution_candidates_are_review_only",
            "no_raw_memory_platform_or_markdown_write",
            "promotion_requires_separate_authorized_gate",
        ],
    }


def _review_action_id(candidate_id: str, action: str, reason: str) -> str:
    seed = f"{candidate_id}|{action}|{reason}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"review-{digest}"


def _candidate_lookup_id(candidate: dict) -> str:
    for key in ("candidate_id", "source_feedback_candidate_id", "target_library_id", "library_id"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return ""


def _candidate_verbatim_excerpt(candidate: dict) -> str:
    for key in ("verbatim_excerpt", "raw_excerpt", "source_excerpt", "excerpt"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    card = candidate.get("library_card") if isinstance(candidate.get("library_card"), dict) else {}
    value = str(card.get("verbatim_excerpt") or "").strip()
    if value:
        return value
    return str(candidate.get("reason") or "").strip()


def _experience_review_candidates_from_body(body: dict) -> list[dict]:
    candidates: list[dict] = []
    candidate = body.get("candidate")
    if isinstance(candidate, dict):
        candidates.append(candidate)
    raw_candidates = body.get("candidates") if isinstance(body.get("candidates"), list) else []
    candidates.extend(item for item in raw_candidates if isinstance(item, dict))
    evolution = body.get("experience_evolution") if isinstance(body.get("experience_evolution"), dict) else {}
    evolution_candidates = evolution.get("candidates") if isinstance(evolution.get("candidates"), list) else []
    candidates.extend(item for item in evolution_candidates if isinstance(item, dict))
    unique: dict[str, dict] = {}
    for item in candidates:
        key = _candidate_lookup_id(item)
        if key:
            unique.setdefault(key, item)
    return list(unique.values())


def _experience_review_actions_from_body(body: dict, candidates: list[dict]) -> list[dict]:
    raw_actions = body.get("actions") if isinstance(body.get("actions"), list) else []
    actions = [item for item in raw_actions if isinstance(item, dict)]
    if not actions and (body.get("action") or body.get("candidate_id")):
        actions = [body]
    if not actions and candidates:
        actions = [
            {
                "candidate_id": _candidate_lookup_id(candidate),
                "action": "defer",
                "reason": "review_requested_without_explicit_action",
            }
            for candidate in candidates
            if _candidate_lookup_id(candidate)
        ]
    return actions


def _planned_status_for_review_action(action: str) -> str:
    return {
        "approve": "pending_authorized_adoption",
        "reject": "pending_authorized_rejection",
        "defer": "pending_review",
        "request_evidence": "pending_evidence",
    }.get(action, "invalid_action")


def build_experience_review_actions_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    candidates = _experience_review_candidates_from_body(body)
    candidate_by_id = {_candidate_lookup_id(candidate): candidate for candidate in candidates if _candidate_lookup_id(candidate)}
    actions = _experience_review_actions_from_body(body, candidates)
    reviewer = str(body.get("reviewer") or body.get("reviewed_by") or "").strip()
    plans: list[dict] = []
    missing_candidate_ids: list[str] = []
    invalid_actions: list[str] = []

    for item in actions:
        candidate_id = str(item.get("candidate_id") or item.get("id") or "").strip()
        action = str(item.get("action") or item.get("review_action") or "").strip()
        reason = str(item.get("reason") or item.get("note") or "").strip()
        candidate = candidate_by_id.get(candidate_id, {})
        valid_action = action in EXPERIENCE_REVIEW_ACTIONS
        candidate_known = bool(candidate)
        if not candidate_known and candidate_id:
            missing_candidate_ids.append(candidate_id)
        if action and not valid_action:
            invalid_actions.append(action)
        target_shelf = str(candidate.get("target_shelf") or candidate.get("library_shelf") or item.get("target_shelf") or "").strip()
        if target_shelf not in ("xingce", "toolbook", "errata"):
            target_shelf = "errata" if action in ("reject", "request_evidence") else "xingce"
        planned_status = _planned_status_for_review_action(action)
        plan = {
            "review_action_id": _review_action_id(candidate_id, action, reason),
            "candidate_id": candidate_id,
            "candidate_known": candidate_known,
            "candidate_type": candidate.get("candidate_type", ""),
            "target_library_id": candidate.get("target_library_id", ""),
            "target_shelf": target_shelf,
            "requested_action": action,
            "valid_action": valid_action,
            "allowed_actions": EXPERIENCE_REVIEW_ACTIONS,
            "planned_lifecycle_status": planned_status,
            "reviewer": str(item.get("reviewer") or reviewer or "").strip(),
            "reason": reason,
            "source_refs": candidate.get("source_refs") if isinstance(candidate.get("source_refs"), dict) else {},
            "verbatim_excerpt": _candidate_verbatim_excerpt(candidate),
            "acceptance_checks": _string_list(candidate.get("acceptance_checks")),
            "receipt_preview": {
                "receipt_type": "experience_candidate_review_intent",
                "source_contract": LIBRARY_EXPERIENCE_EVOLUTION_CONTRACT,
                "review_contract": LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
                "candidate_id": candidate_id,
                "action": action,
                "planned_lifecycle_status": planned_status,
                "target_shelf": target_shelf,
                "would_write": False,
                "requires_authorized_apply_gate": True,
            },
            "requires_authorization": True,
            "apply_gate_required": True,
            "write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "markdown_write_performed": False,
        }
        if action == "approve":
            plan["adoption_status"] = "not_adopted_in_dry_run"
            plan["required_followup"] = ["authorized_apply_gate", "source_review_or_replay_validation"]
        elif action == "reject":
            plan["required_followup"] = ["authorized_errata_or_rejection_receipt"]
        elif action == "request_evidence":
            plan["required_followup"] = ["restore_source_refs_or_verbatim_excerpt"]
        else:
            plan["required_followup"] = ["keep_candidate_in_review_queue"]
        plans.append(plan)

    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "contract": LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
        "source_contract": LIBRARY_EXPERIENCE_EVOLUTION_CONTRACT,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "allowed_actions": EXPERIENCE_REVIEW_ACTIONS,
        "action_count": len(plans),
        "review_actions": plans,
        "missing_candidate_ids": sorted(set(missing_candidate_ids)),
        "invalid_actions": sorted(set(invalid_actions)),
        "target_shelf_counts": {
            shelf: sum(1 for plan in plans if plan.get("target_shelf") == shelf)
            for shelf in ["xingce", "toolbook", "errata"]
        },
        "authorization_required_for_apply": True,
        "all_writes_blocked": True,
        "notes": [
            "review_action_is_receipt_preview_only",
            "approve_does_not_adopt_without_separate_authorized_gate",
            "no_raw_memory_platform_or_markdown_write",
        ],
    }


def _history_by_library_id(history: dict) -> dict[str, dict]:
    histories = history.get("histories") if isinstance(history.get("histories"), list) else []
    return {
        str(item.get("library_id") or "").strip(): item
        for item in histories
        if isinstance(item, dict) and str(item.get("library_id") or "").strip()
    }


def _records_by_library_id(records: list[dict]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        attached = attach_library_card(record)
        card = attached.get("library_card", {}) if isinstance(attached.get("library_card"), dict) else {}
        library_id = str(card.get("library_id") or attached.get("library_id") or record.get("library_id") or "").strip()
        if library_id:
            by_id.setdefault(library_id, attached)
    return by_id


def _replay_validation_evidence(replay: dict, library_id: str) -> dict:
    if not isinstance(replay, dict):
        return {"available": False, "passed": False, "reason": "missing_replay_report"}
    used = False
    passed = False
    for result in replay.get("results", []) if isinstance(replay.get("results"), list) else []:
        if not isinstance(result, dict):
            continue
        used_ids = [str(item or "").strip() for item in _as_list(result.get("used_library_ids"))]
        if library_id and library_id in used_ids:
            used = True
            failed = _as_list(result.get("failed"))
            passed = passed or not failed
    summary = replay.get("summary") if isinstance(replay.get("summary"), dict) else {}
    return {
        "available": bool(replay),
        "passed": bool(used and passed),
        "library_id_used": bool(used),
        "best_mode": summary.get("best_mode", ""),
        "proactive_resurfacing_passed": bool(summary.get("proactive_resurfacing_passed", False)),
    }


def build_experience_validation_report_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    review_payload = body.get("experience_review_actions") if isinstance(body.get("experience_review_actions"), dict) else {}
    review_actions = body.get("review_actions") if isinstance(body.get("review_actions"), list) else []
    if not review_actions and isinstance(review_payload.get("review_actions"), list):
        review_actions = review_payload.get("review_actions")
    review_actions = [item for item in review_actions if isinstance(item, dict)]
    records = body.get("records") if isinstance(body.get("records"), list) else []
    history = body.get("experience_history") if isinstance(body.get("experience_history"), dict) else {}
    if not history and records:
        history = build_experience_history_dry_run({
            "records": records,
            "events": body.get("events") if isinstance(body.get("events"), list) else [],
        })
    replay = body.get("replay") if isinstance(body.get("replay"), dict) else {}
    histories_by_id = _history_by_library_id(history)
    records_by_id = _records_by_library_id(records)
    reports: list[dict] = []
    issue_reports: list[dict] = []
    for action_item in review_actions:
        candidate_id = str(action_item.get("candidate_id") or "").strip()
        target_library_id = str(action_item.get("target_library_id") or "").strip()
        record = records_by_id.get(target_library_id, {})
        record_card = record.get("library_card", {}) if isinstance(record.get("library_card"), dict) else {}
        source_refs = action_item.get("source_refs") if isinstance(action_item.get("source_refs"), dict) else {}
        if not source_refs and isinstance(record_card.get("source_refs"), dict):
            source_refs = record_card.get("source_refs")
        verbatim_excerpt = str(action_item.get("verbatim_excerpt") or record_card.get("verbatim_excerpt") or "").strip()
        acceptance_checks = _string_list(
            action_item.get("acceptance_checks")
            or record.get("acceptance_checks")
            or record_card.get("work_experience", {}).get("acceptance_checks")
        )
        history_item = histories_by_id.get(target_library_id, {})
        history_status = str(history_item.get("validation_status") or "").strip()
        replay_evidence = _replay_validation_evidence(replay, target_library_id)
        checks = {
            "source_refs": bool(source_refs),
            "verbatim_excerpt": bool(verbatim_excerpt),
            "acceptance_checks": bool(acceptance_checks),
            "history_validated": history_status == "validated",
            "replay_passed": bool(replay_evidence.get("passed", False)),
        }
        validation_passed = (
            checks["source_refs"]
            and checks["verbatim_excerpt"]
            and checks["acceptance_checks"]
            and (checks["history_validated"] or checks["replay_passed"])
        )
        missing = [name for name, ok in checks.items() if not ok]
        report = {
            "candidate_id": candidate_id,
            "review_action_id": action_item.get("review_action_id", ""),
            "requested_action": action_item.get("requested_action") or action_item.get("action") or "",
            "target_library_id": target_library_id,
            "target_shelf": action_item.get("target_shelf", ""),
            "validation_passed": validation_passed,
            "validation_status": "passed" if validation_passed else "blocked",
            "checks": checks,
            "missing": missing,
            "source_refs": source_refs,
            "verbatim_excerpt": verbatim_excerpt,
            "acceptance_checks": acceptance_checks,
            "history": history_item,
            "replay_evidence": replay_evidence,
            "write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "markdown_write_performed": False,
        }
        if not validation_passed:
            issue_reports.append({
                "candidate_id": candidate_id,
                "target_library_id": target_library_id,
                "missing": missing,
                "recommended_action": "run_replay_or_restore_acceptance_checks_before_apply",
            })
        reports.append(report)
    report_passed = bool(reports) and not issue_reports
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_VALIDATION_REPORT_CONTRACT,
        "source_contract": LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "durable_write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "report_passed": report_passed,
        "validation_report_count": len(reports),
        "validation_issue_count": len(issue_reports),
        "validation_issues": issue_reports,
        "validation_reports": reports,
        "notes": [
            "validation_report_is_read_only",
            "boolean_confirmation_is_not_validation_evidence",
            "future_apply_should_reference_this_report",
        ],
    }


def _validation_report_by_candidate(validation_report: dict) -> dict[str, dict]:
    reports = validation_report.get("validation_reports") if isinstance(validation_report.get("validation_reports"), list) else []
    return {
        str(item.get("candidate_id") or "").strip(): item
        for item in reports
        if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
    }


def _validation_receipt_next_step(missing: list[str], validation_passed: bool) -> str:
    if validation_passed:
        return "attach_validation_receipt_to_apply_gate_after_human_authorization"
    if any(item in missing for item in ("source_refs", "verbatim_excerpt")):
        return "restore_source_evidence_before_validation_receipt"
    if "acceptance_checks" in missing:
        return "add_acceptance_checks_before_validation_receipt"
    return "run_replay_or_attach_history_validation_before_apply_gate"


def _queue_by_candidate(review_queue: dict) -> dict[str, dict]:
    buckets = review_queue.get("buckets") if isinstance(review_queue.get("buckets"), dict) else {}
    by_candidate: dict[str, dict] = {}
    for items in buckets.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id") or "").strip()
            if candidate_id:
                by_candidate.setdefault(candidate_id, item)
    return by_candidate


def build_experience_validation_receipt_schema_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    validation_report = body.get("experience_validation_report") if isinstance(body.get("experience_validation_report"), dict) else {}
    review_payload = body.get("experience_review_actions") if isinstance(body.get("experience_review_actions"), dict) else {}
    review_queue = body.get("experience_review_queue") if isinstance(body.get("experience_review_queue"), dict) else {}
    if not validation_report:
        validation_report = build_experience_validation_report_dry_run({
            "experience_review_actions": review_payload,
            "records": body.get("records") if isinstance(body.get("records"), list) else [],
            "experience_history": body.get("experience_history") if isinstance(body.get("experience_history"), dict) else {},
            "replay": body.get("replay") if isinstance(body.get("replay"), dict) else {},
        })
    review_actions = review_payload.get("review_actions") if isinstance(review_payload.get("review_actions"), list) else []
    review_by_candidate = {
        str(item.get("candidate_id") or "").strip(): item
        for item in review_actions
        if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
    }
    queue_by_candidate = _queue_by_candidate(review_queue)
    reports = validation_report.get("validation_reports") if isinstance(validation_report.get("validation_reports"), list) else []
    receipts: list[dict] = []
    issue_receipts: list[dict] = []
    allow_apply_gate_count = 0
    for report in reports:
        if not isinstance(report, dict):
            continue
        candidate_id = str(report.get("candidate_id") or "").strip()
        action_item = review_by_candidate.get(candidate_id, {})
        queue_item = queue_by_candidate.get(candidate_id, {})
        checks = report.get("checks") if isinstance(report.get("checks"), dict) else {}
        missing = _as_list(report.get("missing"))
        validation_passed = bool(report.get("validation_passed"))
        blocking_missing = [] if validation_passed else missing
        history_or_replay = bool(checks.get("history_validated") or checks.get("replay_passed"))
        would_allow_apply_gate = validation_passed
        if would_allow_apply_gate:
            allow_apply_gate_count += 1
        receipt = {
            "validation_receipt_id": _receipt_schema_id("experience_validation_receipt", candidate_id, str(report.get("validation_status") or "")),
            "receipt_type": "experience_validation_receipt",
            "candidate_id": candidate_id,
            "review_action_id": report.get("review_action_id") or action_item.get("review_action_id", ""),
            "requested_action": report.get("requested_action") or action_item.get("requested_action") or action_item.get("action") or "",
            "target_library_id": report.get("target_library_id") or action_item.get("target_library_id", ""),
            "target_shelf": report.get("target_shelf") or action_item.get("target_shelf", ""),
            "queue_bucket": queue_item.get("bucket", ""),
            "validation_status": report.get("validation_status") or ("passed" if validation_passed else "blocked"),
            "source_refs_checked": bool(checks.get("source_refs")),
            "verbatim_excerpt_checked": bool(checks.get("verbatim_excerpt")),
            "acceptance_checks_checked": bool(checks.get("acceptance_checks")),
            "history_or_replay_evidence": history_or_replay,
            "source_refs": report.get("source_refs") if isinstance(report.get("source_refs"), dict) else {},
            "verbatim_excerpt": str(report.get("verbatim_excerpt") or ""),
            "acceptance_checks": _string_list(report.get("acceptance_checks")),
            "validation_issues": blocking_missing,
            "non_blocking_validation_notes": missing if validation_passed else [],
            "recommended_next_step": _validation_receipt_next_step(blocking_missing, validation_passed),
            "would_allow_apply_gate": would_allow_apply_gate,
            "durable_write_performed": False,
            "write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "markdown_write_performed": False,
        }
        if blocking_missing:
            issue_receipts.append({
                "validation_receipt_id": receipt["validation_receipt_id"],
                "candidate_id": candidate_id,
                "target_library_id": receipt["target_library_id"],
                "validation_status": receipt["validation_status"],
                "missing": blocking_missing,
                "recommended_next_step": receipt["recommended_next_step"],
            })
        receipts.append(receipt)
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_VALIDATION_RECEIPT_SCHEMA_CONTRACT,
        "source_contract": LIBRARY_EXPERIENCE_VALIDATION_REPORT_CONTRACT,
        "optional_source_contracts": [
            LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
            LIBRARY_EXPERIENCE_REVIEW_QUEUE_CONTRACT,
        ],
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "durable_write_performed": False,
        "validation_result_write_performed": False,
        "candidate_status_change_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "validation_report_attached": bool(validation_report),
        "validation_report_passed": bool(validation_report.get("report_passed")) if validation_report else False,
        "receipt_count": len(receipts),
        "validation_receipts": receipts,
        "validation_issue_count": len(issue_receipts),
        "validation_issues": issue_receipts,
        "would_allow_apply_gate_count": allow_apply_gate_count,
        "all_writes_blocked": True,
        "notes": [
            "validation_receipt_schema_only_no_durable_write",
            "validation_result_is_not_written",
            "candidate_status_is_not_changed",
            "future_apply_gate_should_reference_passed_validation_receipts",
        ],
    }


def _review_queue_bucket(action_item: dict, validation_item: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    action = str(action_item.get("requested_action") or action_item.get("action") or "").strip()
    target_shelf = str(action_item.get("target_shelf") or "").strip()
    if action in ("reject", "request_evidence") or target_shelf == "errata":
        reasons.append("review_action_routes_to_errata")
        return "should_errata", reasons
    missing_validation = _as_list(validation_item.get("missing")) if validation_item else []
    if any(item in missing_validation for item in ("source_refs", "verbatim_excerpt")):
        reasons.append("source_evidence_missing")
        return "needs_source_evidence", reasons
    if validation_item and not validation_item.get("validation_passed"):
        reasons.append("validation_report_not_passed")
        return "needs_validation", reasons
    if action == "defer":
        reasons.append("review_action_defer")
        return "defer", reasons
    if action == "approve":
        reasons.append("ready_for_human_review_before_apply_gate")
        return "ready_for_review", reasons
    reasons.append("no_explicit_review_action")
    return "defer", reasons


def build_experience_review_queue_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    evolution = body.get("experience_evolution") if isinstance(body.get("experience_evolution"), dict) else {}
    review_payload = body.get("experience_review_actions") if isinstance(body.get("experience_review_actions"), dict) else {}
    validation_report = body.get("experience_validation_report") if isinstance(body.get("experience_validation_report"), dict) else {}
    if not review_payload:
        review_payload = build_experience_review_actions_dry_run({"experience_evolution": evolution})
    if not validation_report:
        validation_report = build_experience_validation_report_dry_run({
            "experience_review_actions": review_payload,
            "records": body.get("records") if isinstance(body.get("records"), list) else [],
            "experience_history": body.get("experience_history") if isinstance(body.get("experience_history"), dict) else {},
            "replay": body.get("replay") if isinstance(body.get("replay"), dict) else {},
        })
    review_actions = review_payload.get("review_actions") if isinstance(review_payload.get("review_actions"), list) else []
    validation_by_candidate = _validation_report_by_candidate(validation_report)
    buckets: dict[str, list[dict]] = {
        "ready_for_review": [],
        "needs_validation": [],
        "needs_source_evidence": [],
        "should_errata": [],
        "defer": [],
    }
    for action_item in review_actions:
        if not isinstance(action_item, dict):
            continue
        candidate_id = str(action_item.get("candidate_id") or "").strip()
        validation_item = validation_by_candidate.get(candidate_id, {})
        bucket, reasons = _review_queue_bucket(action_item, validation_item)
        item = {
            "candidate_id": candidate_id,
            "review_action_id": action_item.get("review_action_id", ""),
            "candidate_type": action_item.get("candidate_type", ""),
            "requested_action": action_item.get("requested_action") or action_item.get("action") or "",
            "planned_lifecycle_status": action_item.get("planned_lifecycle_status", ""),
            "target_library_id": action_item.get("target_library_id", ""),
            "target_shelf": action_item.get("target_shelf", ""),
            "bucket": bucket,
            "reasons": reasons,
            "validation_status": validation_item.get("validation_status", "missing_validation_report"),
            "validation_missing": validation_item.get("missing", []),
            "recommended_next_step": {
                "ready_for_review": "review_then_attach_authorized_apply_gate",
                "needs_validation": "run_replay_or_attach_history_validation",
                "needs_source_evidence": "restore_source_refs_or_verbatim_excerpt",
                "should_errata": "prepare_errata_or_rejection_receipt",
                "defer": "keep_candidate_in_review_queue",
            }[bucket],
            "write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "markdown_write_performed": False,
        }
        buckets[bucket].append(item)
    bucket_counts = {name: len(items) for name, items in buckets.items()}
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_REVIEW_QUEUE_CONTRACT,
        "source_contracts": [
            LIBRARY_EXPERIENCE_EVOLUTION_CONTRACT,
            LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
            LIBRARY_EXPERIENCE_VALIDATION_REPORT_CONTRACT,
        ],
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "durable_write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "queue_count": sum(bucket_counts.values()),
        "bucket_counts": bucket_counts,
        "buckets": buckets,
        "all_writes_blocked": True,
        "notes": [
            "review_queue_is_triage_only",
            "candidate_status_is_not_changed",
            "future_apply_still_requires_validation_report_and_apply_gate",
        ],
    }


def _review_apply_authorized(authorization: dict, body: dict, name: str) -> bool:
    value = authorization.get(name, body.get(name))
    if name in ("operator", "reason"):
        return bool(str(value or "").strip())
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "confirm", "confirmed")
    return bool(value)


def _validation_receipt_gate_summary(validation_receipts: dict, review_actions: list[dict]) -> dict:
    receipts = validation_receipts.get("validation_receipts") if isinstance(validation_receipts.get("validation_receipts"), list) else []
    receipts = [item for item in receipts if isinstance(item, dict)]
    expected_candidate_ids = {
        str(item.get("candidate_id") or "").strip()
        for item in review_actions
        if str(item.get("candidate_id") or "").strip()
    }
    receipt_candidate_ids = {
        str(item.get("candidate_id") or "").strip()
        for item in receipts
        if str(item.get("candidate_id") or "").strip()
    }
    missing_candidates = sorted(expected_candidate_ids - receipt_candidate_ids)
    blocked_receipts = [
        {
            "validation_receipt_id": item.get("validation_receipt_id", ""),
            "candidate_id": item.get("candidate_id", ""),
            "validation_status": item.get("validation_status", ""),
            "validation_issues": _as_list(item.get("validation_issues")),
            "recommended_next_step": item.get("recommended_next_step", ""),
        }
        for item in receipts
        if not item.get("would_allow_apply_gate")
    ]
    return {
        "attached": bool(validation_receipts),
        "contract": validation_receipts.get("contract", "") if validation_receipts else "",
        "receipt_count": len(receipts),
        "would_allow_apply_gate_count": sum(1 for item in receipts if item.get("would_allow_apply_gate")),
        "issue_count": int(validation_receipts.get("validation_issue_count", 0)) if validation_receipts else 0,
        "missing_candidate_ids": missing_candidates,
        "blocked_receipts": blocked_receipts,
        "all_receipts_allow_gate": bool(receipts) and not missing_candidates and not blocked_receipts,
    }


def build_experience_review_apply_gate_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else {}
    validation_report = body.get("experience_validation_report") if isinstance(body.get("experience_validation_report"), dict) else {}
    validation_receipts = body.get("experience_validation_receipt_schema") if isinstance(body.get("experience_validation_receipt_schema"), dict) else {}
    review_actions_payload = body.get("experience_review_actions") if isinstance(body.get("experience_review_actions"), dict) else {}
    review_actions = body.get("review_actions") if isinstance(body.get("review_actions"), list) else []
    if not review_actions and isinstance(review_actions_payload.get("review_actions"), list):
        review_actions = review_actions_payload.get("review_actions")
    review_actions = [item for item in review_actions if isinstance(item, dict)]
    missing = [
        name for name in EXPERIENCE_REVIEW_APPLY_CONFIRMATIONS
        if not _review_apply_authorized(authorization, body, name)
    ]
    blocked_reasons: list[str] = []
    if missing:
        blocked_reasons.append("missing_authorization_confirmations")
    if not review_actions:
        blocked_reasons.append("missing_review_actions")
    invalid_actions = [
        str(item.get("requested_action") or item.get("action") or "")
        for item in review_actions
        if str(item.get("requested_action") or item.get("action") or "") not in EXPERIENCE_REVIEW_ACTIONS
    ]
    if invalid_actions:
        blocked_reasons.append("invalid_review_actions")
    validation_receipt_summary = _validation_receipt_gate_summary(validation_receipts, review_actions)
    if validation_receipts and not validation_receipt_summary["all_receipts_allow_gate"]:
        blocked_reasons.append("validation_receipt_not_passed")
    elif validation_report and not validation_report.get("report_passed"):
        blocked_reasons.append("validation_report_not_passed")
    status = "ready" if not blocked_reasons else "blocked"
    target_shelf_counts = {
        shelf: sum(1 for item in review_actions if item.get("target_shelf") == shelf)
        for shelf in ["xingce", "toolbook", "errata"]
    }
    receipt_preview = {
        "receipt_type": "experience_review_apply_gate",
        "source_contract": LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
        "apply_gate_contract": LIBRARY_EXPERIENCE_REVIEW_APPLY_GATE_CONTRACT,
        "status": status,
        "review_action_count": len(review_actions),
        "target_shelf_counts": target_shelf_counts,
        "validation_receipt_attached": bool(validation_receipts),
        "validation_receipt_count": validation_receipt_summary["receipt_count"],
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "would_write": False,
        "future_apply_required": True,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
    }
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_REVIEW_APPLY_GATE_CONTRACT,
        "source_contract": LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "status": status,
        "authorization_complete": not missing,
        "missing_confirmations": missing,
        "authorization_required": EXPERIENCE_REVIEW_APPLY_CONFIRMATIONS,
        "blocked_reasons": blocked_reasons,
        "invalid_actions": sorted(set(filter(None, invalid_actions))),
        "validation_report_required_for_future_apply": True,
        "validation_report_attached": bool(validation_report),
        "validation_report_passed": bool(validation_report.get("report_passed")) if validation_report else False,
        "validation_issue_count": int(validation_report.get("validation_issue_count", 0)) if validation_report else 0,
        "validation_receipt_preferred_for_future_apply": True,
        "validation_receipt_attached": bool(validation_receipts),
        "validation_receipt_contract": validation_receipt_summary["contract"],
        "validation_receipt_count": validation_receipt_summary["receipt_count"],
        "validation_receipt_issue_count": validation_receipt_summary["issue_count"],
        "validation_receipts_allow_gate": validation_receipt_summary["all_receipts_allow_gate"],
        "validation_receipt_missing_candidate_ids": validation_receipt_summary["missing_candidate_ids"],
        "validation_receipt_blocked": validation_receipt_summary["blocked_receipts"],
        "review_action_count": len(review_actions),
        "target_shelf_counts": target_shelf_counts,
        "receipt_preview": receipt_preview,
        "all_writes_blocked": True,
        "notes": [
            "apply_gate_is_dry_run_only",
            "ready_does_not_write_or_adopt",
            "future_apply_must_be_separate_and_authorized",
        ],
    }


def _receipt_schema_id(receipt_type: str, candidate_id: str, action: str) -> str:
    seed = f"{receipt_type}|{candidate_id}|{action}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"receipt-{digest}"


def _receipt_actions_from_gate(body: dict) -> list[dict]:
    gate = body.get("experience_review_apply_gate") if isinstance(body.get("experience_review_apply_gate"), dict) else {}
    review_payload = body.get("experience_review_actions") if isinstance(body.get("experience_review_actions"), dict) else {}
    actions = body.get("review_actions") if isinstance(body.get("review_actions"), list) else []
    if not actions and isinstance(review_payload.get("review_actions"), list):
        actions = review_payload.get("review_actions")
    if not actions and isinstance(gate.get("review_actions"), list):
        actions = gate.get("review_actions")
    return [item for item in actions if isinstance(item, dict)]


def _receipt_type_for_action(action: str, target_shelf: str) -> str:
    if action == "reject":
        return "experience_errata_receipt"
    if action == "request_evidence":
        return "experience_errata_receipt"
    if target_shelf == "errata":
        return "experience_errata_receipt"
    if action == "approve":
        return "experience_apply_receipt"
    return "experience_supersede_receipt" if action == "defer" else "experience_apply_receipt"


def _receipt_evidence_check(action_item: dict, gate: dict) -> dict:
    refs = action_item.get("source_refs") if isinstance(action_item.get("source_refs"), dict) else {}
    excerpt = str(action_item.get("verbatim_excerpt") or "").strip()
    review_action_id = str(action_item.get("review_action_id") or "").strip()
    gate_receipt = gate.get("receipt_preview") if isinstance(gate.get("receipt_preview"), dict) else {}
    gate_status = str(gate.get("status") or "").strip()
    checks = {
        "source_refs": bool(refs),
        "verbatim_excerpt": bool(excerpt),
        "review_action_id": bool(review_action_id),
        "apply_gate_receipt": bool(gate_receipt),
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "checks": checks,
        "missing": missing,
        "complete": not missing,
        "apply_gate_ready": gate_status == "ready",
        "source_refs": refs,
        "verbatim_excerpt": excerpt,
    }


def build_experience_apply_receipt_schema_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    gate = body.get("experience_review_apply_gate") if isinstance(body.get("experience_review_apply_gate"), dict) else {}
    review_actions = _receipt_actions_from_gate(body)
    operator = str(body.get("operator") or (gate.get("receipt_preview") or {}).get("operator") or "").strip()
    reason = str(body.get("reason") or (gate.get("receipt_preview") or {}).get("reason") or "").strip()
    receipts: list[dict] = []
    rollback_plans: list[dict] = []
    evidence_issues: list[dict] = []
    for action_item in review_actions:
        action = str(action_item.get("requested_action") or action_item.get("action") or "").strip()
        candidate_id = str(action_item.get("candidate_id") or "").strip()
        target_shelf = str(action_item.get("target_shelf") or "xingce").strip()
        if target_shelf not in ("xingce", "toolbook", "errata"):
            target_shelf = "errata"
        receipt_type = _receipt_type_for_action(action, target_shelf)
        receipt_id = _receipt_schema_id(receipt_type, candidate_id, action)
        evidence = _receipt_evidence_check(action_item, gate)
        source_refs = evidence["source_refs"]
        if not evidence["complete"]:
            evidence_issues.append({
                "candidate_id": candidate_id,
                "requested_action": action,
                "missing": evidence["missing"],
                "recommended_action": "request_evidence_or_errata_before_apply",
            })
        receipt = {
            "receipt_id": receipt_id,
            "receipt_type": receipt_type,
            "candidate_id": candidate_id,
            "review_action_id": action_item.get("review_action_id", ""),
            "requested_action": action,
            "planned_lifecycle_status": action_item.get("planned_lifecycle_status", ""),
            "target_library_id": action_item.get("target_library_id", ""),
            "target_shelf": target_shelf,
            "operator": operator or action_item.get("reviewer", ""),
            "reason": reason or action_item.get("reason", ""),
            "source_refs": source_refs,
            "verbatim_excerpt": evidence["verbatim_excerpt"],
            "required_source_evidence": ["source_refs", "verbatim_excerpt", "review_action_id", "apply_gate_receipt"],
            "source_evidence_complete": evidence["complete"],
            "source_evidence_missing": evidence["missing"],
            "apply_gate_ready": evidence["apply_gate_ready"],
            "future_apply_allowed_by_schema": evidence["complete"] and evidence["apply_gate_ready"],
            "rollback_receipt_type": "experience_rollback_receipt",
            "supersede_receipt_type": "experience_supersede_receipt",
            "errata_receipt_type": "experience_errata_receipt",
            "durable_write_performed": False,
            "write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "markdown_write_performed": False,
        }
        rollback = {
            "receipt_id": _receipt_schema_id("experience_rollback_receipt", candidate_id, action),
            "receipt_type": "experience_rollback_receipt",
            "rolls_back_receipt_id": receipt_id,
            "candidate_id": candidate_id,
            "target_shelf": target_shelf,
            "rollback_reason_required": True,
            "restore_previous_lifecycle_status": True,
            "source_refs_required": True,
            "durable_write_performed": False,
            "write_performed": False,
        }
        receipt["rollback_plan"] = rollback
        rollback_plans.append(rollback)
        receipts.append(receipt)

    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_APPLY_RECEIPT_SCHEMA_CONTRACT,
        "source_contract": LIBRARY_EXPERIENCE_REVIEW_APPLY_GATE_CONTRACT,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "durable_write_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "gate_status": gate.get("status", ""),
        "receipt_count": len(receipts),
        "receipt_types": sorted({receipt["receipt_type"] for receipt in receipts}),
        "source_evidence_complete": not evidence_issues,
        "source_evidence_issue_count": len(evidence_issues),
        "source_evidence_issues": evidence_issues,
        "receipts": receipts,
        "rollback_plans": rollback_plans,
        "target_shelf_counts": {
            shelf: sum(1 for receipt in receipts if receipt.get("target_shelf") == shelf)
            for shelf in ["xingce", "toolbook", "errata"]
        },
        "notes": [
            "receipt_schema_only_no_durable_write",
            "rollback_supersede_errata_shapes_are_defined_before_live_apply",
            "apply_gate_ready_still_required_before_future_write",
        ],
    }


def _apply_package_id(review_actions: list[dict], gate: dict, apply_receipts: dict) -> str:
    seed = json.dumps({
        "review_action_ids": [item.get("review_action_id", "") for item in review_actions],
        "gate_status": gate.get("status", ""),
        "receipt_ids": [item.get("receipt_id", "") for item in apply_receipts.get("receipts", []) if isinstance(item, dict)],
    }, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"apply-package-{digest}"


def build_experience_apply_package_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    review_payload = body.get("experience_review_actions") if isinstance(body.get("experience_review_actions"), dict) else {}
    validation_receipts = body.get("experience_validation_receipt_schema") if isinstance(body.get("experience_validation_receipt_schema"), dict) else {}
    gate = body.get("experience_review_apply_gate") if isinstance(body.get("experience_review_apply_gate"), dict) else {}
    apply_receipts = body.get("experience_apply_receipt_schema") if isinstance(body.get("experience_apply_receipt_schema"), dict) else {}
    review_actions = body.get("review_actions") if isinstance(body.get("review_actions"), list) else []
    if not review_actions and isinstance(review_payload.get("review_actions"), list):
        review_actions = review_payload.get("review_actions")
    review_actions = [item for item in review_actions if isinstance(item, dict)]
    if not gate:
        gate = build_experience_review_apply_gate_dry_run({
            "experience_review_actions": review_payload,
            "experience_validation_receipt_schema": validation_receipts,
            "authorization": body.get("authorization") if isinstance(body.get("authorization"), dict) else {},
        })
    if not apply_receipts:
        apply_receipts = build_experience_apply_receipt_schema_dry_run({
            "experience_review_actions": review_payload,
            "experience_review_apply_gate": gate,
        })
    receipts = apply_receipts.get("receipts") if isinstance(apply_receipts.get("receipts"), list) else []
    receipts = [item for item in receipts if isinstance(item, dict)]
    validation_items = validation_receipts.get("validation_receipts") if isinstance(validation_receipts.get("validation_receipts"), list) else []
    validation_items = [item for item in validation_items if isinstance(item, dict)]
    rollback_plans = apply_receipts.get("rollback_plans") if isinstance(apply_receipts.get("rollback_plans"), list) else []
    rollback_plans = [item for item in rollback_plans if isinstance(item, dict)]
    blocked_reasons: list[str] = []
    if not review_actions:
        blocked_reasons.append("missing_review_actions")
    if not validation_receipts:
        blocked_reasons.append("missing_validation_receipts")
    elif not validation_receipts.get("would_allow_apply_gate_count"):
        blocked_reasons.append("validation_receipts_do_not_allow_gate")
    if not gate:
        blocked_reasons.append("missing_apply_gate")
    elif gate.get("status") != "ready":
        blocked_reasons.append("apply_gate_not_ready")
    if not apply_receipts:
        blocked_reasons.append("missing_apply_receipts")
    elif not apply_receipts.get("source_evidence_complete"):
        blocked_reasons.append("apply_receipt_source_evidence_missing")
    package_status = "ready" if not blocked_reasons else "blocked"
    target_shelf_counts = {
        shelf: sum(1 for receipt in receipts if receipt.get("target_shelf") == shelf)
        for shelf in ["xingce", "toolbook", "errata"]
    }
    package_items = []
    validation_by_candidate = {
        str(item.get("candidate_id") or "").strip(): item
        for item in validation_items
        if str(item.get("candidate_id") or "").strip()
    }
    for receipt in receipts:
        candidate_id = str(receipt.get("candidate_id") or "").strip()
        validation_item = validation_by_candidate.get(candidate_id, {})
        package_items.append({
            "candidate_id": candidate_id,
            "review_action_id": receipt.get("review_action_id", ""),
            "requested_action": receipt.get("requested_action", ""),
            "target_library_id": receipt.get("target_library_id", ""),
            "target_shelf": receipt.get("target_shelf", ""),
            "validation_receipt_id": validation_item.get("validation_receipt_id", ""),
            "validation_status": validation_item.get("validation_status", ""),
            "apply_receipt_id": receipt.get("receipt_id", ""),
            "apply_receipt_type": receipt.get("receipt_type", ""),
            "rollback_receipt_id": (receipt.get("rollback_plan") or {}).get("receipt_id", "") if isinstance(receipt.get("rollback_plan"), dict) else "",
            "future_apply_allowed_by_schema": bool(receipt.get("future_apply_allowed_by_schema")),
            "would_write": False,
        })
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_APPLY_PACKAGE_CONTRACT,
        "source_contracts": [
            LIBRARY_EXPERIENCE_REVIEW_ACTION_CONTRACT,
            LIBRARY_EXPERIENCE_VALIDATION_RECEIPT_SCHEMA_CONTRACT,
            LIBRARY_EXPERIENCE_REVIEW_APPLY_GATE_CONTRACT,
            LIBRARY_EXPERIENCE_APPLY_RECEIPT_SCHEMA_CONTRACT,
        ],
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "durable_write_performed": False,
        "apply_receipt_write_performed": False,
        "candidate_status_change_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "package_id": _apply_package_id(review_actions, gate, apply_receipts),
        "package_status": package_status,
        "ready_for_authorized_apply": package_status == "ready",
        "authorized_apply_performed": False,
        "blocked_reasons": blocked_reasons,
        "review_action_count": len(review_actions),
        "validation_receipt_count": len(validation_items),
        "apply_receipt_count": len(receipts),
        "rollback_plan_count": len(rollback_plans),
        "gate_status": gate.get("status", ""),
        "target_shelf_counts": target_shelf_counts,
        "package_items": package_items,
        "rollback_plans": rollback_plans,
        "all_writes_blocked": True,
        "notes": [
            "apply_package_is_final_preview_only",
            "ready_does_not_write_or_adopt",
            "future_authorized_apply_must_be_separate",
        ],
    }


def _experience_flow_stage_status(stage: dict, payloads: dict[str, dict]) -> dict:
    name = stage["stage"]
    payload = payloads.get(name, {})
    if name == "experience_evolution":
        count = int(payload.get("candidate_count", 0)) if payload else 0
        ready = count > 0
        issues = [] if ready else ["missing_candidates"]
    elif name == "review_action":
        count = int(payload.get("action_count", 0)) if payload else 0
        ready = count > 0 and not payload.get("invalid_actions")
        issues = [] if ready else ["missing_or_invalid_review_actions"]
    elif name == "validation_report":
        count = int(payload.get("validation_report_count", 0)) if payload else 0
        ready = bool(payload.get("report_passed"))
        issues = [] if ready else ["validation_report_not_passed"]
    elif name == "validation_receipt":
        count = int(payload.get("receipt_count", 0)) if payload else 0
        ready = count > 0 and int(payload.get("would_allow_apply_gate_count", 0)) == count
        issues = [] if ready else ["validation_receipts_not_ready"]
    elif name == "review_queue":
        count = int(payload.get("queue_count", 0)) if payload else 0
        ready = count > 0
        issues = [] if ready else ["review_queue_empty"]
    elif name == "apply_gate":
        count = int(payload.get("review_action_count", 0)) if payload else 0
        ready = payload.get("status") == "ready"
        issues = [] if ready else _as_list(payload.get("blocked_reasons")) or ["apply_gate_not_ready"]
    elif name == "apply_receipt_schema":
        count = int(payload.get("receipt_count", 0)) if payload else 0
        ready = count > 0 and bool(payload.get("source_evidence_complete"))
        issues = [] if ready else ["apply_receipts_not_ready"]
    elif name == "apply_package":
        count = int(payload.get("apply_receipt_count", 0)) if payload else 0
        ready = payload.get("package_status") == "ready"
        issues = [] if ready else _as_list(payload.get("blocked_reasons")) or ["apply_package_not_ready"]
    else:
        count = 0
        ready = False
        issues = ["unknown_stage"]
    return {
        "stage": name,
        "order": stage["order"],
        "contract": stage["contract"],
        "role": stage["role"],
        "writes_allowed": False,
        "ready": ready,
        "status": "ready" if ready else "blocked",
        "item_count": count,
        "issues": issues,
        "write_performed": False,
        "candidate_status_change_performed": False,
    }


def build_experience_flow_overview_dry_run(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    payloads = {
        "experience_evolution": body.get("experience_evolution") if isinstance(body.get("experience_evolution"), dict) else {},
        "review_action": body.get("experience_review_actions") if isinstance(body.get("experience_review_actions"), dict) else {},
        "validation_report": body.get("experience_validation_report") if isinstance(body.get("experience_validation_report"), dict) else {},
        "validation_receipt": body.get("experience_validation_receipt_schema") if isinstance(body.get("experience_validation_receipt_schema"), dict) else {},
        "review_queue": body.get("experience_review_queue") if isinstance(body.get("experience_review_queue"), dict) else {},
        "apply_gate": body.get("experience_review_apply_gate") if isinstance(body.get("experience_review_apply_gate"), dict) else {},
        "apply_receipt_schema": body.get("experience_apply_receipt_schema") if isinstance(body.get("experience_apply_receipt_schema"), dict) else {},
        "apply_package": body.get("experience_apply_package") if isinstance(body.get("experience_apply_package"), dict) else {},
    }
    stages = _experience_flow_stage_contracts()
    stage_statuses = [_experience_flow_stage_status(stage, payloads) for stage in stages]
    blocked = [item for item in stage_statuses if not item["ready"]]
    return {
        "ok": True,
        "contract": LIBRARY_EXPERIENCE_FLOW_OVERVIEW_CONTRACT,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "durable_write_performed": False,
        "candidate_status_change_performed": False,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "stage_count": len(stage_statuses),
        "ready_stage_count": len(stage_statuses) - len(blocked),
        "blocked_stage_count": len(blocked),
        "flow_status": "ready_for_future_authorized_apply" if not blocked else "blocked_preview",
        "stage_statuses": stage_statuses,
        "blocked_stages": blocked,
        "forbidden_everywhere": library_experience_flow_overview_contract()["forbidden_everywhere"],
        "all_writes_blocked": True,
        "notes": [
            "experience_flow_overview_is_internal_route_map",
            "overview_does_not_apply_or_write",
            "ready_flow_still_requires_separate_future_authorized_apply",
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


def _normalize_admission_shelf(value: Any, text: str = "") -> str:
    requested = str(value or "").strip().lower()
    if requested in ZHIXING_SHELVES:
        return requested
    lowered = text.lower()
    if any(token in lowered for token in ["纠错", "勘误", "deprecated", "superseded", "conflict", "errata"]):
        return "errata"
    if any(token in lowered for token in ["安装", "配置", "工具", "平台", "mcp", "api", "runtime", "tool", "config"]):
        return "toolbook"
    if any(token in lowered for token in ["经验", "流程", "踩坑", "验收", "workflow", "procedure", "gotcha"]):
        return "xingce"
    if any(token in lowered for token in ["raw", "原始", "source", "verbatim"]):
        return "raw"
    return "zhiyi"


def build_library_admission_candidate(body: dict | None = None) -> dict:
    body = body if isinstance(body, dict) else {}
    source_type = str(body.get("source_type") or body.get("type") or "local_file").strip()
    if source_type not in ADMISSION_SOURCE_TYPES:
        source_type = "local_file"
    title = str(body.get("title") or body.get("name") or "").strip()
    text = str(body.get("text") or body.get("content") or body.get("summary") or body.get("verbatim_excerpt") or "").strip()
    summary = str(body.get("summary") or _compact_text(text, 240)).strip()
    verbatim_excerpt = str(body.get("verbatim_excerpt") or body.get("raw_excerpt") or text[:1200]).strip()
    refs = body.get("source_refs") if isinstance(body.get("source_refs"), dict) else {}
    source_path = str(body.get("source_path") or body.get("path") or "").strip()
    source_url = str(body.get("source_url") or body.get("url") or "").strip()
    if not refs and (source_path or source_url):
        refs = {
            "source_system": str(body.get("source_system") or source_type).strip(),
            "source_path": source_path,
            "source_url": source_url,
            "artifact_type": f"{source_type}_admission_source",
        }
        refs = {key: value for key, value in refs.items() if value not in ("", None, [], {})}
    target_shelf = _normalize_admission_shelf(body.get("target_shelf") or body.get("shelf"), " ".join([title, summary, text]))
    seed = json.dumps(
        {
            "source_type": source_type,
            "target_shelf": target_shelf,
            "title": title,
            "summary": summary,
            "source_refs": refs,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    candidate_id = str(body.get("candidate_id") or f"admission-{target_shelf}-{digest}").strip()
    record = {
        "candidate_type": "library_admission_candidate",
        "type": body.get("memory_type") or ("xingce_work_experience_candidate" if target_shelf == "xingce" else "toolbook_candidate" if target_shelf == "toolbook" else "raw_jsonl" if target_shelf == "raw" else "case_memory"),
        "_type": body.get("memory_type") or ("xingce_work_experience_candidate" if target_shelf == "xingce" else ""),
        "library_shelf": target_shelf,
        "candidate_id": candidate_id,
        "exp_id": candidate_id,
        "title": title or summary or "Library admission candidate",
        "summary": summary,
        "detail": text or summary,
        "source_refs": refs,
        "verbatim_excerpt": verbatim_excerpt,
        "status": "candidate",
        "lifecycle_status": "candidate",
        "supersedes": _string_list(body.get("supersedes")),
        "conflicts_with": _string_list(body.get("conflicts_with")),
        "relates_to": _string_list(body.get("relates_to")),
        "depends_on": _string_list(body.get("depends_on")),
        "blocked_by": _string_list(body.get("blocked_by")),
        "proven_by": _string_list(body.get("proven_by")),
        "contradicts": _string_list(body.get("contradicts")),
        "source_type": source_type,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "created_at": body.get("created_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if target_shelf == "xingce":
        record["_xingce"] = {
            "candidate_id": candidate_id,
            "lifecycle_status": "candidate",
            "production_experience_write_performed": False,
        }
        record["work_scenario"] = str(body.get("work_scenario") or title or summary).strip()
        record["action_strategy"] = body.get("action_strategy") or summary or text
        record["avoid_conditions"] = _string_list(body.get("avoid_conditions"))
        record["acceptance_checks"] = _string_list(body.get("acceptance_checks") or body.get("verification"))
        record["applicable_scope"] = str(body.get("applicable_scope") or body.get("scope") or "").strip()
    card = library_card_for(record)
    projection = build_library_note_projection_dry_run({"record": card})
    missing = []
    if not (title or text or summary):
        missing.append("title_or_text")
    if not refs:
        missing.append("source_refs")
    if not verbatim_excerpt:
        missing.append("verbatim_excerpt")
    return {
        "ok": not missing,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "contract": LIBRARY_ADMISSION_CANDIDATE_CONTRACT,
        "candidate_type": "library_admission_candidate",
        "candidate_id": candidate_id if not missing else "",
        "target_shelf": target_shelf,
        "source_type": source_type,
        "candidate": attach_library_card(record) if not missing else None,
        "library_note_projection": projection.get("projection") if not missing else None,
        "markdown": projection.get("markdown", "") if not missing else "",
        "missing": missing,
        "promotion_path": [
            "admission_candidate",
            "source_review_or_sample_check",
            "library_note_projection",
            "replay_or_user_approval",
            "adopted_or_deprecated_or_superseded",
        ],
        "notes": [
            "admission_candidate_is_not_durable_memory",
            "no_raw_or_memory_write",
            "markdown_projection_is_review_material_only",
        ],
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
