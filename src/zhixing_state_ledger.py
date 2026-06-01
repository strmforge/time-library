#!/usr/bin/env python3
"""Read-only State Ledger and Temporal Index helpers for Zhixing."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List


STATE_LEDGER_VERSION = "2026.6.1"
TRUSTED_STATUS_VALUES = {"adopted", "current", "active", "accepted"}
NEEDS_REVIEW_STATUS_VALUES = {"candidate", "pending_review", "needs_review", "draft", "unknown", ""}
DEPRECATED_STATUS_VALUES = {"deprecated", "invalidated", "rejected"}
SUPERSEDED_STATUS_VALUES = {"superseded", "replaced"}
STATUS_CATEGORIES = ["current", "superseded", "deprecated", "conflicting", "needs_review"]


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


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_text(obj: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean_text(obj.get(key))
        if value:
            return value
    return ""


def _status_for(record: Dict[str, Any]) -> str:
    lifecycle = _dict(record.get("_lifecycle"))
    xingce = _dict(record.get("_xingce"))
    for value in (
        record.get("state_status"),
        record.get("lifecycle_status"),
        record.get("status"),
        lifecycle.get("status"),
        xingce.get("lifecycle_status"),
    ):
        text = _clean_text(value).lower()
        if text:
            return text
    return "unknown"


def _source_refs_for(record: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("source_refs", "_source_refs"):
        value = record.get(key)
        if isinstance(value, dict):
            return dict(value)
    source_path = _clean_text(record.get("source_path"))
    if not source_path:
        return {}
    return {
        "source_system": record.get("source_system", ""),
        "source_path": source_path,
        "session_id": record.get("session_id", ""),
        "canonical_window_id": record.get("canonical_window_id", ""),
    }


def _record_id_for(record: Dict[str, Any]) -> str:
    for key in ("library_id", "state_id", "exp_id", "memory_id", "candidate_id", "id"):
        text = _clean_text(record.get(key))
        if text:
            return text
    seed = "|".join([
        _first_text(record, "title", "summary", "detail", "verbatim_excerpt"),
        _clean_text(_source_refs_for(record).get("source_path")),
        _clean_text(record.get("created_at") or record.get("updated_at")),
    ])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"state-record-{digest}"


def _title_for(record: Dict[str, Any]) -> str:
    title = _first_text(record, "title", "state_key", "topic", "summary", "detail", "verbatim_excerpt")
    return title[:120].strip() or _record_id_for(record)


def _time_for(record: Dict[str, Any]) -> str:
    refs = _source_refs_for(record)
    for value in (
        record.get("updated_at"),
        record.get("created_at"),
        record.get("observed_at"),
        record.get("timestamp"),
        refs.get("timestamp"),
        refs.get("created_at"),
    ):
        text = _clean_text(value)
        if text:
            return text
    return ""


def _category_for(record: Dict[str, Any]) -> str:
    status = _status_for(record)
    conflicts = _as_list(record.get("conflicts_with"))
    if conflicts or status == "conflicting":
        return "conflicting"
    if status in SUPERSEDED_STATUS_VALUES:
        return "superseded"
    if status in DEPRECATED_STATUS_VALUES:
        return "deprecated"
    if status in TRUSTED_STATUS_VALUES:
        return "current"
    if status in NEEDS_REVIEW_STATUS_VALUES:
        return "needs_review"
    return "needs_review"


def _trust_score(record: Dict[str, Any]) -> int:
    category = _category_for(record)
    status = _status_for(record)
    source_refs = _source_refs_for(record)
    excerpt = _clean_text(record.get("verbatim_excerpt") or record.get("raw_excerpt"))
    score = {
        "current": 70,
        "needs_review": 35,
        "conflicting": 20,
        "superseded": 10,
        "deprecated": 5,
    }.get(category, 0)
    if status == "adopted":
        score += 20
    if source_refs:
        score += 7
    if excerpt:
        score += 3
    return score


def _state_key_for(record: Dict[str, Any], fallback: str = "") -> str:
    return (
        _first_text(record, "state_key", "topic", "project", "library_id", "exp_id")
        or fallback
        or "general"
    )


def _sort_key(item: Dict[str, Any]) -> tuple:
    return (item.get("trust_score", 0), item.get("observed_at") or "", item.get("record_id") or "")


def _temporal_item(record: Dict[str, Any], topic: str) -> Dict[str, Any]:
    source_refs = _source_refs_for(record)
    return {
        "record_id": _record_id_for(record),
        "state_key": _state_key_for(record, topic),
        "title": _title_for(record),
        "status": _status_for(record),
        "status_category": _category_for(record),
        "observed_at": _time_for(record),
        "trust_score": _trust_score(record),
        "source_refs": source_refs,
        "verbatim_excerpt": _clean_text(record.get("verbatim_excerpt") or record.get("raw_excerpt")),
        "supersedes": _as_list(record.get("supersedes")),
        "conflicts_with": _as_list(record.get("conflicts_with")),
    }


def get_state_ledger_plan() -> Dict[str, Any]:
    """Return the State Ledger / Temporal Index read-only contract."""
    return {
        "ok": True,
        "version": STATE_LEDGER_VERSION,
        "read_only": True,
        "write_performed": False,
        "name": "Zhixing State Ledger / Temporal Index MVP",
        "zh_name": "状态账本 / 时间索引 MVP",
        "endpoint": "/api/v1/zhixing/state-ledger/dry-run",
        "purpose": "answer_latest_trusted_judgment_without_overwriting_raw",
        "status_categories": STATUS_CATEGORIES,
        "trusted_status_values": sorted(TRUSTED_STATUS_VALUES),
        "required_for_promotion_later": ["source_refs", "verbatim_excerpt", "status", "supersedes", "conflicts_with"],
        "temporal_index_role": "navigation_only_not_authority",
        "raw_authority": True,
        "forbidden_by_default": [
            "mutate_raw_records",
            "silently_replace_old_judgment",
            "promote_without_source_refs",
            "treat_temporal_index_as_truth",
        ],
        "notes": [
            "old judgments are downgraded or superseded, not deleted",
            "latest trusted judgment must still expose its source refs",
            "conflicting records remain visible for errata review",
        ],
    }


def build_temporal_index_dry_run(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a deterministic temporal index from supplied records."""
    body = body if isinstance(body, dict) else {}
    topic = _clean_text(body.get("topic") or body.get("state_key") or body.get("query"))
    records = [item for item in _as_list(body.get("records")) if isinstance(item, dict)]
    items = [_temporal_item(record, topic) for record in records]
    items = sorted(items, key=_sort_key, reverse=True)
    category_counts = {category: 0 for category in STATUS_CATEGORIES}
    for item in items:
        category_counts[item["status_category"]] = category_counts.get(item["status_category"], 0) + 1
    return {
        "ok": True,
        "version": STATE_LEDGER_VERSION,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "topic": topic,
        "records_count": len(records),
        "temporal_index": items,
        "status_counts": category_counts,
        "raw_authority": True,
        "temporal_index_role": "navigation_only_not_authority",
    }


def build_state_ledger_snapshot(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a read-only State Ledger snapshot from supplied records."""
    body = body if isinstance(body, dict) else {}
    index = build_temporal_index_dry_run(body)
    items = index["temporal_index"]
    current = [item for item in items if item["status_category"] == "current"]
    needs_review = [item for item in items if item["status_category"] == "needs_review"]
    conflicts = [item for item in items if item["status_category"] == "conflicting"]
    latest = current[0] if current else None
    warnings: List[str] = []
    if not items:
        warnings.append("no_records_supplied")
    if not latest and needs_review:
        warnings.append("no_current_trusted_judgment_only_needs_review")
    if conflicts:
        warnings.append("conflicting_records_visible_for_errata_review")
    if latest and not latest.get("source_refs"):
        warnings.append("latest_trusted_judgment_missing_source_refs")
    if latest and not latest.get("verbatim_excerpt"):
        warnings.append("latest_trusted_judgment_missing_verbatim_excerpt")
    return {
        "ok": True,
        "version": STATE_LEDGER_VERSION,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "topic": index["topic"],
        "records_count": index["records_count"],
        "latest_trusted_judgment": latest,
        "latest_trusted_judgment_found": latest is not None,
        "state_ledger": {
            "current": current,
            "needs_review": needs_review,
            "conflicting": conflicts,
            "superseded": [item for item in items if item["status_category"] == "superseded"],
            "deprecated": [item for item in items if item["status_category"] == "deprecated"],
        },
        "temporal_index": items,
        "status_counts": index["status_counts"],
        "warnings": warnings,
        "raw_authority": True,
        "write_flags": {
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "platform_write_performed": False,
        },
        "notes": [
            "state_ledger_answers_current_judgment_only_from_supplied_records",
            "temporal_index_is_navigation_not_truth",
            "promotion_or_errata_requires_a_separate_authorized_gate",
        ],
    }
