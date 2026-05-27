#!/usr/bin/env python3
"""
Zhiyi archive catalog helpers.

This module keeps Zhiyi in the librarian-archivist lane:
stable catalog ids, evidence anchors, lifecycle status, and concise cards.
It does not replace raw records or rewrite saved user content.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict


TYPE_PREFIX = {
    "case_memory": "CASE",
    "error_memory": "ERR",
    "preference_memory": "PREF",
    "yifanchen_project_status": "PROJ",
    "xingce_work_experience_candidate": "XINGCE",
}


def _compact_text(value: Any, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


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


def memory_type(record: dict) -> str:
    return str(record.get("type") or record.get("_type") or "memory").strip() or "memory"


def catalog_id_for(record: dict) -> str:
    """Return a stable owner-facing Zhiyi catalog id."""
    existing = str(record.get("catalog_id") or "").strip()
    if existing:
        return existing
    mtype = memory_type(record)
    prefix = TYPE_PREFIX.get(mtype, re.sub(r"[^A-Z0-9]+", "-", mtype.upper()).strip("-") or "MEM")
    stable = str(record.get("exp_id") or record.get("memory_id") or "").strip()
    refs = _parse_refs(record.get("_source_refs") or record.get("source_refs") or {})
    if not stable:
        stable = "|".join([
            mtype,
            str(record.get("summary") or ""),
            str(record.get("detail") or ""),
            str(refs.get("source_path") or ""),
            str(refs.get("session_id") or ""),
        ])
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:10].upper()
    return f"ZY-{prefix}-{digest}"


def title_for(record: dict, limit: int = 42) -> str:
    title = str(record.get("title") or "").strip()
    if title:
        return _compact_text(title, limit)
    text = str(record.get("summary") or record.get("detail") or "").strip()
    if not text:
        return catalog_id_for(record)
    for sep in ("。", "，", ".", ";", "；", ":"):
        if sep in text[:80]:
            text = text.split(sep, 1)[0]
            break
    return _compact_text(text, limit)


def lifecycle_for(record: dict) -> dict:
    lifecycle = record.get("_lifecycle") if isinstance(record.get("_lifecycle"), dict) else {}
    deleted_state = str(record.get("_deleted_state") or lifecycle.get("deleted_state") or "").strip()
    status = str(record.get("status") or lifecycle.get("status") or "").strip()
    conflict = str(record.get("conflict_decision") or lifecycle.get("conflict_decision") or "").strip()
    inject_policy = str(record.get("inject_policy") or lifecycle.get("inject_policy") or "").strip()
    if deleted_state == "recycle_bin":
        status = "recycled"
    elif conflict in ("superseded", "deprecated"):
        status = conflict
    elif not status:
        status = "active"
    return {
        "status": status,
        "deleted_state": deleted_state or ("recycle_bin" if status == "recycled" else "active"),
        "lifecycle_version": record.get("lifecycle_version") or lifecycle.get("lifecycle_version") or 1,
        "conflict_decision": conflict,
        "inject_policy": inject_policy,
    }


def evidence_level_for(record: dict) -> str:
    level = str(record.get("evidence_level") or "").strip().lower()
    if level:
        return level
    refs = _parse_refs(record.get("_source_refs") or record.get("source_refs") or {})
    if refs.get("byte_offsets"):
        return "high"
    if refs.get("source_path") and refs.get("msg_ids"):
        return "medium"
    if refs.get("source_path"):
        return "low"
    return "unknown"


def archive_card(record: dict) -> dict:
    refs = _parse_refs(record.get("_source_refs") or record.get("source_refs") or {})
    lifecycle = lifecycle_for(record)
    catalog_id = catalog_id_for(record)
    exp_id = str(record.get("exp_id") or record.get("memory_id") or "").strip()
    detail = str(record.get("detail") or "")
    summary = str(record.get("summary") or "")
    confidence = record.get("confidence", record.get("score", 0))
    try:
        confidence = round(float(confidence), 2)
    except Exception:
        confidence = 0
    return {
        "catalog_id": catalog_id,
        "exp_id": exp_id,
        "type": memory_type(record),
        "title": title_for(record),
        "summary": summary,
        "detail": detail,
        "status": lifecycle["status"],
        "lifecycle": lifecycle,
        "evidence_level": evidence_level_for(record),
        "confidence": confidence,
        "source_refs": refs,
        "source_ref_status": "available" if refs else "missing",
        "raw_available": bool(refs.get("source_path")),
        "byte_offsets_available": bool(refs.get("byte_offsets")),
        "created_at": record.get("created_at") or record.get("extracted_at") or record.get("captured_at") or "",
        "updated_at": record.get("updated_at") or record.get("extracted_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


def attach_archive_card(record: dict) -> dict:
    result = dict(record)
    card = archive_card(result)
    result["catalog_id"] = card["catalog_id"]
    result["archive_card"] = card
    result["evidence_level"] = result.get("evidence_level") or card["evidence_level"]
    result["status"] = card["status"]
    result["deleted_state"] = card["lifecycle"].get("deleted_state", result.get("deleted_state", "active"))
    result["_deleted_state"] = result.get("_deleted_state") or result["deleted_state"]
    result["_lifecycle"] = card["lifecycle"]
    return result

