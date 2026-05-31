#!/usr/bin/env python3
"""Zhiyi natural-language correction candidate helpers."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict

try:
    from dialog_intent_router import classify_fine_intent, ROUTE_CORRECTION_ERRATA
except Exception:
    from src.dialog_intent_router import classify_fine_intent, ROUTE_CORRECTION_ERRATA


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _errata_candidate_id(text: str, target: str = "") -> str:
    seed = f"{text}|{target}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"zhiyi-errata-{digest}"


def build_zhiyi_errata_candidate(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a review-only Zhiyi errata candidate without mutating raw memory."""
    body = body if isinstance(body, dict) else {}
    correction_text = _clean_text(body.get("correction_text") or body.get("message") or body.get("text"))
    target = body.get("target") if isinstance(body.get("target"), dict) else {}
    target_ref = _clean_text(
        body.get("target_ref")
        or target.get("library_id")
        or target.get("catalog_id")
        or target.get("memory_id")
        or target.get("source_ref")
    )
    source_refs = body.get("source_refs") if isinstance(body.get("source_refs"), (dict, list)) else target.get("source_refs", [])
    route = classify_fine_intent(correction_text)
    is_correction = route.get("route") == ROUTE_CORRECTION_ERRATA
    candidate_id = _errata_candidate_id(correction_text, target_ref)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidate = {
        "candidate_id": candidate_id,
        "candidate_type": "zhiyi_errata_candidate",
        "library_shelf": "errata",
        "status": "candidate",
        "created_at": now_iso,
        "correction_text": correction_text,
        "verbatim_feedback": correction_text,
        "target_ref": target_ref,
        "target": target,
        "source_refs": source_refs,
        "matched_intent": route,
        "recommended_action": "review_memory_interpretation",
        "review_required": True,
        "requires_authorization": True,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "errata_write_performed": False,
        "platform_write_performed": False,
        "notes": [
            "candidate_only",
            "raw_records_must_not_be_rewritten",
            "existing_zhiyi_or_xingce_records_must_not_be_silently_edited",
        ],
    }
    missing = []
    if not correction_text:
        missing.append("correction_text")
    if not is_correction:
        missing.append("correction_intent")
    return {
        "ok": not missing,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "candidate_created": not missing,
        "candidate": candidate if not missing else None,
        "candidate_id": candidate_id if not missing else "",
        "missing": missing,
        "intent": route,
        "error": "not_a_memory_correction" if missing else "",
    }
