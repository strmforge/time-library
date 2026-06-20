#!/usr/bin/env python3
"""Read-only Zhixing library dashboard and experience-flow preview.

This module owns library-shaped read models for the local console. It does not
own adoption writes, rollback writes, or raw records. Those remain in the
experience governance and raw-origin modules.
"""

from __future__ import annotations

import datetime
import json
import os

try:
    from src.zhixing_library import (
        attach_library_card,
        build_active_bookmarks_dry_run,
        build_experience_apply_package_dry_run,
        build_experience_apply_receipt_schema_dry_run,
        build_experience_evolution_candidates_dry_run,
        build_experience_flow_overview_dry_run,
        build_experience_review_apply_gate_dry_run,
        build_experience_review_actions_dry_run,
        build_experience_review_queue_dry_run,
        build_experience_validation_receipt_schema_dry_run,
        build_experience_validation_report_dry_run,
        build_experience_history_dry_run,
        build_library_index_projection_dry_run,
        build_library_trust_doctor_dry_run,
        hybrid_recall_manifest,
        library_manifest,
        zhixing_loop_manifest,
    )
except Exception:  # pragma: no cover
    from zhixing_library import (
        attach_library_card,
        build_active_bookmarks_dry_run,
        build_experience_apply_package_dry_run,
        build_experience_apply_receipt_schema_dry_run,
        build_experience_evolution_candidates_dry_run,
        build_experience_flow_overview_dry_run,
        build_experience_review_apply_gate_dry_run,
        build_experience_review_actions_dry_run,
        build_experience_review_queue_dry_run,
        build_experience_validation_receipt_schema_dry_run,
        build_experience_validation_report_dry_run,
        build_experience_history_dry_run,
        build_library_index_projection_dry_run,
        build_library_trust_doctor_dry_run,
        hybrid_recall_manifest,
        library_manifest,
        zhixing_loop_manifest,
    )
try:
    from src.p6_zhiyi_model_runtime import _compact_text, _usage_log_positive_int
except Exception:  # pragma: no cover
    from p6_zhiyi_model_runtime import _compact_text, _usage_log_positive_int


MEMCORE_ROOT = ""
_load_zhiyi_objects_callback = None
_get_zhiyi_stats_callback = None
_raw_evidence_for_refs_callback = None
_query_xingce_candidates_callback = None
_zhiyi_recycle_overlay_callback = None


def configure_zhixing_library_dashboard(
    memcore_root,
    *,
    load_zhiyi_objects=None,
    get_zhiyi_stats=None,
    raw_evidence_for_refs=None,
    query_xingce_candidates=None,
    zhiyi_recycle_overlay=None,
):
    global MEMCORE_ROOT
    global _load_zhiyi_objects_callback, _get_zhiyi_stats_callback, _raw_evidence_for_refs_callback
    global _query_xingce_candidates_callback, _zhiyi_recycle_overlay_callback
    MEMCORE_ROOT = str(memcore_root)
    if load_zhiyi_objects is not None:
        _load_zhiyi_objects_callback = load_zhiyi_objects
    if get_zhiyi_stats is not None:
        _get_zhiyi_stats_callback = get_zhiyi_stats
    if raw_evidence_for_refs is not None:
        _raw_evidence_for_refs_callback = raw_evidence_for_refs
    if query_xingce_candidates is not None:
        _query_xingce_candidates_callback = query_xingce_candidates
    if zhiyi_recycle_overlay is not None:
        _zhiyi_recycle_overlay_callback = zhiyi_recycle_overlay


def _get_zhiyi_stats():
    if _get_zhiyi_stats_callback is None:
        return {}
    return _get_zhiyi_stats_callback()


def _load_zhiyi_objects(limit=None):
    if _load_zhiyi_objects_callback is None:
        return []
    return _load_zhiyi_objects_callback(limit=limit)


def _raw_evidence_for_refs(refs, excerpt_chars=220):
    if _raw_evidence_for_refs_callback is None:
        return {"raw_excerpt": "", "source_path": ""}
    return _raw_evidence_for_refs_callback(refs, excerpt_chars=excerpt_chars)


def _query_xingce_work_experience_candidates(params=None):
    if _query_xingce_candidates_callback is None:
        return {"items": [], "total": 0}
    return _query_xingce_candidates_callback(params or {})


def _zhiyi_experience_recycle_overlay():
    if _zhiyi_recycle_overlay_callback is None:
        return {}
    return _zhiyi_recycle_overlay_callback()


def _source_refs_from_record(record):
    refs = record.get("_source_refs") if isinstance(record.get("_source_refs"), dict) else record.get("source_refs")
    if isinstance(refs, dict):
        return refs
    if isinstance(refs, str) and refs.strip():
        try:
            parsed = json.loads(refs)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _record_text_field(record, keys):
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            text = "; ".join(str(item).strip() for item in value if str(item).strip())
            if text:
                return text
    return ""


def _experience_type_label(ftype):
    return {
        "case_memory": "case experience",
        "error_memory": "error experience",
        "preference_memory": "preference experience",
    }.get(ftype, "experience")


def _experience_text(obj):
    if not isinstance(obj, dict):
        return ""
    for key in ("title", "name", "summary", "content", "text", "memory", "description", "answer", "insight"):
        value = obj.get(key)
        if value:
            return _compact_text(value, 260)
    for value in obj.values():
        if isinstance(value, str) and len(value.strip()) >= 8:
            return _compact_text(value, 260)
    return ""


def _experience_title(obj, ftype, index):
    text = _experience_text(obj)
    if text:
        for sep in (".", ";", ":", "。", "，", "；"):
            if sep in text[:48]:
                text = text.split(sep, 1)[0]
                break
        return _compact_text(text, 30)
    return f"{_experience_type_label(ftype)} {index + 1}"


def _zhiyi_record_from_object(obj, index=0, *, shelf=None, overlay=None):
    ftype = str(obj.get("_type") or obj.get("type") or "case_memory").strip() or "case_memory"
    refs = _source_refs_from_record(obj)
    exp_id = str(obj.get("exp_id") or obj.get("id") or obj.get("memory_id") or obj.get("candidate_id") or "").strip()
    title = _record_text_field(obj, ["title", "name", "query"]) or _experience_title(obj, ftype, index)
    summary = _record_text_field(obj, ["summary", "content", "memory", "text", "value", "preference", "lesson", "answer"])
    detail = _record_text_field(obj, ["detail", "rationale", "evidence", "context", "reason"])
    verbatim = _record_text_field(obj, ["verbatim_excerpt", "raw_excerpt", "original_text", "source_excerpt", "content"])
    record = {
        "_type": ftype,
        "type": ftype,
        "library_shelf": shelf or obj.get("library_shelf") or "zhiyi",
        "library_id": obj.get("library_id") or "",
        "exp_id": exp_id,
        "title": title,
        "summary": summary or title,
        "detail": detail,
        "source_refs": refs,
        "verbatim_excerpt": verbatim or summary,
        "status": obj.get("status") or obj.get("lifecycle_status") or "active",
        "lifecycle_status": obj.get("lifecycle_status") or obj.get("status") or "active",
        "supersedes": obj.get("supersedes") if isinstance(obj.get("supersedes"), list) else [],
        "conflicts_with": obj.get("conflicts_with") if isinstance(obj.get("conflicts_with"), list) else [],
    }
    if overlay:
        record.update({
            "library_shelf": "errata",
            "status": overlay.get("status") or overlay.get("deleted_state") or "recycled",
            "lifecycle_status": overlay.get("status") or overlay.get("deleted_state") or "recycled",
            "detail": overlay.get("reason") or record.get("detail") or "",
            "supersedes": [record.get("exp_id") or record.get("library_id") or ""],
            "conflicts_with": [record.get("exp_id") or record.get("library_id") or ""],
            "errata_reason": overlay.get("reason") or overlay.get("action") or "recycle",
            "errata_action_id": overlay.get("action_id", ""),
        })
    return record


def _zhiyi_records_for_library(limit):
    records = []
    recycle_overlay = _zhiyi_experience_recycle_overlay()
    for index, obj in enumerate(_load_zhiyi_objects(limit=limit)):
        if not isinstance(obj, dict):
            continue
        exp_id = str(obj.get("exp_id") or "").strip()
        if exp_id and exp_id in recycle_overlay:
            continue
        records.append(_zhiyi_record_from_object(obj, index, shelf="zhiyi"))
        if len(records) >= limit:
            break
    return records


def _errata_records_for_library(limit):
    records = []
    recycle_overlay = _zhiyi_experience_recycle_overlay()
    if not recycle_overlay:
        return records
    by_exp_id = {
        str(obj.get("exp_id") or "").strip(): obj
        for obj in _load_zhiyi_objects(limit=None)
        if isinstance(obj, dict) and str(obj.get("exp_id") or "").strip()
    }
    for index, (exp_id, overlay) in enumerate(recycle_overlay.items()):
        fallback = {"_type": overlay.get("type") or "case_memory", "exp_id": exp_id, "summary": overlay.get("title") or exp_id}
        records.append(_zhiyi_record_from_object(by_exp_id.get(exp_id, fallback), index, shelf="errata", overlay=overlay))
        if len(records) >= limit:
            break
    return records


def _raw_records_from_source_refs(records, limit):
    raw_records = []
    seen = set()
    for index, record in enumerate(records):
        refs = _source_refs_from_record(record)
        source_path = str(refs.get("source_path") or "").strip()
        if not source_path or source_path in seen:
            continue
        seen.add(source_path)
        raw_records.append({
            "_type": "raw_jsonl",
            "type": "raw_jsonl",
            "library_shelf": "raw",
            "library_id": "",
            "exp_id": f"raw-source-{index}",
            "title": source_path,
            "summary": f"Raw source for {record.get('library_id') or record.get('exp_id') or 'library record'}",
            "detail": source_path,
            "source_refs": refs,
            "verbatim_excerpt": record.get("verbatim_excerpt") or record.get("summary") or source_path,
            "status": "active",
            "lifecycle_status": "active",
            "supersedes": [],
            "conflicts_with": [],
            "raw_mapping_mode": "raw_jsonl_fallback",
        })
        if len(raw_records) >= limit:
            break
    return raw_records


def _shelf_counts_for_library_records(records):
    counts = {shelf: 0 for shelf in ["raw", "zhiyi", "xingce", "toolbook", "errata"]}
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            card = attach_library_card(record).get("library_card", {})
            shelf = str(card.get("shelf") or record.get("library_shelf") or "").strip()
        except Exception:
            shelf = str(record.get("library_shelf") or "").strip()
        if shelf in counts:
            counts[shelf] += 1
    return counts


def _shelf_index_preview_for_library_records(records, per_shelf_limit=5):
    try:
        per_shelf_limit = max(1, min(int(per_shelf_limit), 20))
    except Exception:
        per_shelf_limit = 5
    preview = {shelf: {"count": 0, "entries": []} for shelf in ["raw", "zhiyi", "xingce", "toolbook", "errata"]}
    for record in records:
        if not isinstance(record, dict):
            continue
        attached = attach_library_card(record)
        card = attached.get("library_card", {}) if isinstance(attached.get("library_card"), dict) else {}
        shelf = str(card.get("shelf") or attached.get("library_shelf") or record.get("library_shelf") or "").strip()
        if shelf not in preview:
            continue
        preview[shelf]["count"] += 1
        if len(preview[shelf]["entries"]) >= per_shelf_limit:
            continue
        refs = card.get("source_refs") if isinstance(card.get("source_refs"), dict) else _source_refs_from_record(record)
        preview[shelf]["entries"].append({
            "library_id": card.get("library_id") or attached.get("library_id") or record.get("library_id") or "",
            "title": card.get("title") or record.get("title") or record.get("summary") or "",
            "source_path": refs.get("source_path", "") if isinstance(refs, dict) else "",
            "status": card.get("status") or record.get("status") or record.get("lifecycle_status") or "",
        })
    return preview


def _library_records_from_query(library_payload):
    existing_records = library_payload.get("records") if isinstance(library_payload.get("records"), list) else None
    if existing_records is not None:
        return [record for record in existing_records if isinstance(record, dict)]
    xingce = library_payload.get("xingce") if isinstance(library_payload.get("xingce"), dict) else {}
    items = xingce.get("items") if isinstance(xingce.get("items"), list) else []
    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        card = item.get("library_card") if isinstance(item.get("library_card"), dict) else {}
        shelf = item.get("library_shelf") or card.get("shelf") or "xingce"
        records.append({
            "_type": "xingce_work_experience_candidate",
            "type": "xingce_work_experience_candidate",
            "library_shelf": shelf,
            "library_id": item.get("library_id") or card.get("library_id") or item.get("candidate_id") or "",
            "exp_id": item.get("candidate_id") or item.get("exp_id") or item.get("library_id") or "",
            "title": item.get("title") or card.get("title") or item.get("work_scenario") or "",
            "summary": item.get("summary") or card.get("summary") or "",
            "detail": item.get("detail") or item.get("action_strategy") or "",
            "source_refs": card.get("source_refs") or item.get("source_refs") or {},
            "verbatim_excerpt": card.get("verbatim_excerpt") or item.get("verbatim_excerpt") or "",
            "status": item.get("lifecycle_status") or item.get("status") or card.get("status") or "candidate",
            "lifecycle_status": item.get("lifecycle_status") or item.get("status") or card.get("status") or "candidate",
            "supersedes": item.get("supersedes") or card.get("supersedes") or [],
            "conflicts_with": item.get("conflicts_with") or card.get("conflicts_with") or [],
            "work_scenario": item.get("work_scenario") or "",
            "action_strategy": item.get("action_strategy") or "",
            "avoid_conditions": item.get("avoid_conditions") or [],
            "acceptance_checks": item.get("acceptance_checks") or [],
            "applicable_scope": item.get("applicable_scope") or "",
            "usage_count": item.get("usage_count") or 0,
            "_xingce": {
                "candidate_id": item.get("candidate_id") or item.get("library_id") or "",
                "lifecycle_status": item.get("lifecycle_status") or "candidate",
                "production_experience_write_performed": False,
            },
        })
    return records


def query_zhixing_library(params=None):
    params = params or {}
    page = params.get("page", 1)
    page_size = _usage_log_positive_int(params.get("page_size") or params.get("limit") or 10, 10, 50)
    xingce = _query_xingce_work_experience_candidates({"page": page, "page_size": page_size})
    xingce_records = _library_records_from_query({"xingce": {"items": xingce.get("items", [])}})
    derived_records = _zhiyi_records_for_library(page_size) + xingce_records + _errata_records_for_library(page_size)
    records = _raw_records_from_source_refs(derived_records, page_size) + derived_records
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "version": "2026.6.20",
        "library": library_manifest(),
        "loop": zhixing_loop_manifest(),
        "hybrid_recall": hybrid_recall_manifest(),
        "shelf_contract": {
            "raw": "source texts and direct excerpts",
            "zhiyi": "user preference, intent, wording, correction, and background experience",
            "xingce": "work experience, action strategy, toolbooks, gotchas, and validation paths",
            "toolbook": "operational runbooks and environment notes",
            "errata": "deprecated, superseded, conflicting, or invalidated records",
        },
        "experience_required_fields": ["source_refs", "verbatim_excerpt", "status", "supersedes", "conflicts_with"],
        "toolbook_raw_sources": {"external_docs": "raw/external_docs/", "probe_logs": "raw/probe_logs/"},
        "xingce": {"total": xingce.get("total", 0), "items": xingce.get("items", [])},
        "records": records,
        "record_count": len(records),
        "shelf_counts": _shelf_counts_for_library_records(records),
        "shelf_index_preview": _shelf_index_preview_for_library_records(records, per_shelf_limit=min(5, page_size)),
        "data_source": "real_zhixing_library",
        "explainability": {"used_library_ids": True, "used_source_refs": True, "matched_by": True, "rank_reason": True},
        "notes": [
            "raw_records_are_source_texts",
            "zhiyi_keeps_preference_and_intent_experience",
            "xingce_keeps_work_experience_and_toolbooks",
            "toolbook_candidates_use_dry_run_validation_before_any_write",
            "skill_is_delivery_workflow_not_the_experience_layer",
        ],
    }


def query_zhixing_library_trust_dashboard(params=None):
    params = params or {}
    try:
        page_size = int(params.get("page_size") or params.get("limit") or 12)
    except Exception:
        page_size = 12
    page_size = max(1, min(page_size, 50))
    query = str(params.get("query") or "status-page-library-trust").strip()
    library_payload = query_zhixing_library({"page": 1, "page_size": page_size})
    records = _library_records_from_query(library_payload)
    body = {
        "query": query,
        "records": records,
        "events": [
            {
                "library_id": record.get("library_id", ""),
                "event_type": "replay_pending",
                "at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for record in records
            if record.get("library_id")
        ],
        "bookmark_limit": min(5, page_size),
        "per_shelf_limit": min(8, page_size),
    }
    trust = build_library_trust_doctor_dry_run(body)
    index = build_library_index_projection_dry_run(body)
    active = build_active_bookmarks_dry_run(body)
    history = build_experience_history_dry_run(body)
    evolution = build_experience_evolution_candidates_dry_run({
        "query": query,
        "records": records,
        "trust_doctor": trust,
        "experience_history": history,
    })
    review_actions = build_experience_review_actions_dry_run({"experience_evolution": evolution})
    validation_report = build_experience_validation_report_dry_run({
        "experience_review_actions": review_actions,
        "records": records,
        "experience_history": history,
    })
    review_queue = build_experience_review_queue_dry_run({
        "experience_evolution": evolution,
        "experience_review_actions": review_actions,
        "experience_validation_report": validation_report,
    })
    validation_receipts = build_experience_validation_receipt_schema_dry_run({
        "experience_review_actions": review_actions,
        "experience_validation_report": validation_report,
        "experience_review_queue": review_queue,
    })
    apply_gate = build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review_actions,
        "experience_validation_report": validation_report,
        "experience_validation_receipt_schema": validation_receipts,
    })
    apply_receipts = build_experience_apply_receipt_schema_dry_run({
        "experience_review_actions": review_actions,
        "experience_review_apply_gate": apply_gate,
    })
    apply_package = build_experience_apply_package_dry_run({
        "experience_review_actions": review_actions,
        "experience_validation_receipt_schema": validation_receipts,
        "experience_review_apply_gate": apply_gate,
        "experience_apply_receipt_schema": apply_receipts,
    })
    flow_overview = build_experience_flow_overview_dry_run({
        "experience_evolution": evolution,
        "experience_review_actions": review_actions,
        "experience_validation_report": validation_report,
        "experience_validation_receipt_schema": validation_receipts,
        "experience_review_queue": review_queue,
        "experience_review_apply_gate": apply_gate,
        "experience_apply_receipt_schema": apply_receipts,
        "experience_apply_package": apply_package,
    })
    shelf_counts = {
        shelf: int((index.get("index", {}).get("shelf_index", {}).get(shelf, {}) or {}).get("count", 0))
        for shelf in ["raw", "zhiyi", "xingce", "toolbook", "errata"]
    }
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "markdown_write_performed": False,
        "contract": "zhixing_library_trust_dashboard.v1",
        "data_source": "real_zhixing_library",
        "demo_fallback_used": False,
        "record_count": len(records),
        "shelf_counts": shelf_counts,
        "library": library_payload,
        "trust_doctor": trust,
        "index_projection": index,
        "active_bookmarks": active,
        "experience_history": history,
        "experience_evolution": evolution,
        "experience_review_actions": review_actions,
        "experience_validation_report": validation_report,
        "experience_validation_receipt_schema": validation_receipts,
        "experience_review_queue": review_queue,
        "experience_review_apply_gate": apply_gate,
        "experience_apply_receipt_schema": apply_receipts,
        "experience_apply_package": apply_package,
        "experience_flow_overview": flow_overview,
        "notes": [
            "dashboard_uses_read_only_zhixing_library_query",
            "no_raw_memory_platform_or_markdown_write",
            "empty_real_library_returns_empty_dashboard_not_fake_success",
        ],
    }


__all__ = [
    "configure_zhixing_library_dashboard",
    "query_zhixing_library",
    "query_zhixing_library_trust_dashboard",
]
