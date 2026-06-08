#!/usr/bin/env python3
"""Material processing pipeline dry-run helpers.

This module turns large inbound material sets into a staged, reviewable plan:
register sources, screen batches, extract high-signal text, review in small
batches, sample-check, then promote only candidates. It is deliberately
read-only and does not write raw records, durable memory, platform config, or
knowledge-base files.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List


MATERIAL_PROCESSING_PIPELINE_VERSION = "2026.6.8"
MATERIAL_PROCESSING_PIPELINE_CONTRACT = "zhixing_material_processing_pipeline.v1"
DEFAULT_BATCH_SIZE = 20
DEFAULT_WIP_LIMIT = 3
DEFAULT_SAMPLE_RATE = 0.1
DEFAULT_FULL_TEXT_THRESHOLD = 55

PIPELINE_STAGES = [
    "need_question",
    "source_registration",
    "batch_level_screening",
    "high_signal_text_extraction",
    "small_batch_review",
    "controller_sample_check",
    "main_library_candidate",
    "main_library_refinement",
]

SOURCE_REGISTRATION_FIELDS = [
    "source_id",
    "title",
    "path_or_url",
    "source_type",
    "batch_id",
    "source_refs",
    "metadata_summary",
]

SCREENING_FIELDS = [
    "title",
    "path_or_url",
    "metadata_summary",
    "keywords",
    "source_type",
    "mtime",
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


def _try_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 500) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _try_float(value: Any, default: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _slug(value: str, fallback: str = "material") -> str:
    text = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff._-]+", "-", value).strip("-")
    if not text:
        return fallback
    return text[:80]


def _stable_id(prefix: str, seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _source_value(source: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean_text(source.get(key))
        if value:
            return value
    return ""


def _source_refs_for(source: Dict[str, Any]) -> Any:
    refs = source.get("source_refs")
    if isinstance(refs, (dict, list)):
        return refs
    path = _source_value(source, "path", "source_path", "file")
    url = _source_value(source, "url", "source_url")
    if not path and not url:
        return {}
    out: Dict[str, Any] = {"source_type": _source_value(source, "source_type", "type") or "material"}
    if path:
        out["source_path"] = path
    if url:
        out["source_url"] = url
    return out


def _text_for_screening(source: Dict[str, Any]) -> str:
    parts = [
        _source_value(source, "title", "name"),
        _source_value(source, "path", "source_path", "url", "source_url"),
        _source_value(source, "summary", "abstract", "description", "metadata_summary"),
        " ".join(_string_list(source.get("keywords"))),
        _source_value(source, "source_type", "type"),
    ]
    return " ".join(part for part in parts if part)


def _need_terms(need: str) -> List[str]:
    lowered = need.lower()
    ascii_terms = re.findall(r"[a-zA-Z0-9_.-]{3,}", lowered)
    chinese_terms = re.findall(r"[\u4e00-\u9fff]{2,}", need)
    terms: List[str] = []
    for term in ascii_terms + chinese_terms:
        if term not in terms:
            terms.append(term)
    return terms[:24]


def _score_source(source: Dict[str, Any], need_terms: List[str]) -> Dict[str, Any]:
    text = _text_for_screening(source)
    lowered = text.lower()
    keyword_hits = [
        term for term in need_terms
        if term and (term.lower() in lowered or term in text)
    ]
    explicit_priority = _source_value(source, "priority", "importance").lower()
    priority_bonus = 0
    if explicit_priority in {"high", "p0", "p1", "重要", "高"}:
        priority_bonus = 25
    elif explicit_priority in {"medium", "p2", "中"}:
        priority_bonus = 10
    has_body = bool(_source_value(source, "content", "text", "body", "full_text"))
    has_refs = bool(_source_refs_for(source))
    title_or_path = bool(_source_value(source, "title", "name") or _source_value(source, "path", "url"))
    score = min(100, len(keyword_hits) * 18 + priority_bonus + (10 if has_body else 0) + (8 if has_refs else 0) + (5 if title_or_path else 0))
    if score >= DEFAULT_FULL_TEXT_THRESHOLD:
        action = "full_text_review"
    elif score >= 25:
        action = "metadata_keep_for_later"
    else:
        action = "exclude_with_reason"
    return {
        "relevance_score": score,
        "matched_terms": keyword_hits[:8],
        "recommended_action": action,
        "full_text_recommended": action == "full_text_review",
        "exclude_reason": "" if action != "exclude_with_reason" else "low_metadata_signal",
    }


def _normalize_source(source: Dict[str, Any], index: int, need_terms: List[str], batch_size: int) -> Dict[str, Any]:
    title = _source_value(source, "title", "name") or f"source-{index + 1}"
    path_or_url = _source_value(source, "path", "source_path", "url", "source_url", "file")
    source_type = _source_value(source, "source_type", "type") or "unknown_material"
    seed = "|".join([title, path_or_url, source_type, str(index)])
    source_id = _source_value(source, "source_id", "id") or _stable_id("material", seed)
    batch_id = f"batch-{(index // batch_size) + 1:04d}"
    score = _score_source(source, need_terms)
    return {
        "source_id": source_id,
        "title": title,
        "path_or_url": path_or_url,
        "source_type": source_type,
        "batch_id": batch_id,
        "metadata_summary": _source_value(source, "summary", "abstract", "description", "metadata_summary")[:500],
        "keywords": _string_list(source.get("keywords"))[:12],
        "source_refs": _source_refs_for(source),
        "has_full_text": bool(_source_value(source, "content", "text", "body", "full_text")),
        "screening": score,
    }


def _make_batches(sources: List[Dict[str, Any]], batch_size: int) -> List[Dict[str, Any]]:
    batches: List[Dict[str, Any]] = []
    for index in range(0, len(sources), batch_size):
        chunk = sources[index:index + batch_size]
        batch_id = f"batch-{(index // batch_size) + 1:04d}"
        full_text_count = sum(1 for item in chunk if item["screening"]["full_text_recommended"])
        batches.append({
            "batch_id": batch_id,
            "source_count": len(chunk),
            "full_text_recommended_count": full_text_count,
            "metadata_keep_count": sum(1 for item in chunk if item["screening"]["recommended_action"] == "metadata_keep_for_later"),
            "exclude_count": sum(1 for item in chunk if item["screening"]["recommended_action"] == "exclude_with_reason"),
            "batch_status": "ready_for_review" if full_text_count else "metadata_screened",
            "cursor": chunk[-1]["source_id"] if chunk else "",
        })
    return batches


def _sample_plan(sources: List[Dict[str, Any]], sample_rate: float) -> Dict[str, Any]:
    reviewed = [item for item in sources if item["screening"]["recommended_action"] != "exclude_with_reason"]
    excluded = [item for item in sources if item["screening"]["recommended_action"] == "exclude_with_reason"]
    review_sample = max(1, int(round(len(reviewed) * sample_rate))) if reviewed else 0
    exclusion_sample = max(1, int(round(len(excluded) * sample_rate))) if excluded else 0
    return {
        "sample_rate": sample_rate,
        "review_sample_count": min(review_sample, len(reviewed)),
        "exclusion_sample_count": min(exclusion_sample, len(excluded)),
        "sample_source_ids": [item["source_id"] for item in (reviewed[:review_sample] + excluded[:exclusion_sample])],
        "controller_must_record_decisions": True,
    }


def get_material_processing_pipeline_contract() -> Dict[str, Any]:
    return {
        "ok": True,
        "version": MATERIAL_PROCESSING_PIPELINE_VERSION,
        "contract": MATERIAL_PROCESSING_PIPELINE_CONTRACT,
        "zh_name": "资料处理流水线",
        "read_only": True,
        "write_performed": False,
        "candidate_type": "material_processing_pipeline_plan",
        "endpoint": "/api/v1/zhixing/material-processing-pipeline/dry-run",
        "tiandao_candidate": True,
        "not_a_memory_layer": True,
        "raw_authority_preserved": True,
        "summary_is_not_raw": True,
        "third_party_tool_dependency": False,
        "network_call_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "required_fields": ["need_or_question", "sources"],
        "source_registration_fields": SOURCE_REGISTRATION_FIELDS,
        "screening_fields": SCREENING_FIELDS,
        "pipeline_stages": PIPELINE_STAGES,
        "default_batch_size": DEFAULT_BATCH_SIZE,
        "default_wip_limit": DEFAULT_WIP_LIMIT,
        "default_sample_rate": DEFAULT_SAMPLE_RATE,
        "promotion_policy": "main_library_candidate_before_refinement",
        "forbidden_by_default": [
            "full_text_read_before_metadata_screening",
            "item_level_review_for_all_sources",
            "write_summary_as_raw",
            "claim_main_library_adoption_without_sample_check",
            "unbounded_parallel_review",
            "platform_config_write",
        ],
        "notes": [
            "process material for throughput before refinement",
            "batch-level screening comes before full text extraction",
            "worker review is limited by cursor, batch size, and WIP",
            "controller sample check gates main library candidates",
        ],
    }


def build_material_processing_pipeline_dry_run(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    need = _first_text(body, "need", "question", "query", "task", "goal")
    raw_sources = body.get("sources")
    if not isinstance(raw_sources, list):
        raw_sources = _as_list(raw_sources)
    source_dicts = [item for item in raw_sources if isinstance(item, dict)]
    batch_size = _try_int(body.get("batch_size"), DEFAULT_BATCH_SIZE, minimum=1, maximum=200)
    wip_limit = _try_int(body.get("wip_limit"), DEFAULT_WIP_LIMIT, minimum=1, maximum=20)
    sample_rate = _try_float(body.get("sample_rate"), DEFAULT_SAMPLE_RATE, minimum=0.01, maximum=1.0)
    terms = _need_terms(need)
    normalized = [
        _normalize_source(source, index, terms, batch_size)
        for index, source in enumerate(source_dicts)
    ]
    batches = _make_batches(normalized, batch_size)
    high_signal = [item for item in normalized if item["screening"]["full_text_recommended"]]
    metadata_keep = [item for item in normalized if item["screening"]["recommended_action"] == "metadata_keep_for_later"]
    excluded = [item for item in normalized if item["screening"]["recommended_action"] == "exclude_with_reason"]
    candidate_id = _stable_id("material-pipeline", "|".join([need, str(len(normalized)), str(batch_size), str(wip_limit)]))
    missing: List[str] = []
    if not need:
        missing.append("need_or_question")
    if not normalized:
        missing.append("sources")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "ok": not missing,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "network_call_performed": False,
        "contract": MATERIAL_PROCESSING_PIPELINE_CONTRACT,
        "version": MATERIAL_PROCESSING_PIPELINE_VERSION,
        "candidate_type": "material_processing_pipeline_plan",
        "candidate_id": candidate_id if not missing else "",
        "created_at": now_iso,
        "missing": missing,
        "error": "invalid_material_processing_pipeline_input" if missing else "",
        "need": need,
        "controls": {
            "batch_size": batch_size,
            "wip_limit": wip_limit,
            "sample_rate": sample_rate,
            "full_text_threshold": DEFAULT_FULL_TEXT_THRESHOLD,
            "unbounded_parallel_review_allowed": False,
        },
        "summary": {
            "source_count": len(normalized),
            "batch_count": len(batches),
            "high_signal_count": len(high_signal),
            "metadata_keep_count": len(metadata_keep),
            "excluded_count": len(excluded),
            "main_library_candidate_count": len(high_signal),
            "sample_check_required": bool(normalized),
        },
        "stages": [
            {"stage": "need_question", "status": "complete" if need else "missing", "output": "review_need"},
            {"stage": "source_registration", "status": "ready" if normalized else "missing", "output": "registered_sources"},
            {"stage": "batch_level_screening", "status": "ready" if normalized else "blocked", "output": "screened_batches"},
            {"stage": "high_signal_text_extraction", "status": "planned" if high_signal else "no_high_signal", "output": "full_text_queue"},
            {"stage": "small_batch_review", "status": "planned" if high_signal else "waiting", "output": "worker_batches"},
            {"stage": "controller_sample_check", "status": "required" if normalized else "blocked", "output": "sample_decisions"},
            {"stage": "main_library_candidate", "status": "candidate_only" if high_signal else "none", "output": "candidate_records"},
            {"stage": "main_library_refinement", "status": "not_performed_in_dry_run", "output": "none"},
        ],
        "registered_sources": normalized[:200],
        "batches": batches,
        "worker_queue": [
            {
                "queue_id": f"worker-{index + 1:02d}",
                "batch_id": batch["batch_id"],
                "source_ids": [
                    item["source_id"]
                    for item in normalized
                    if item["batch_id"] == batch["batch_id"]
                    and item["screening"]["full_text_recommended"]
                ],
                "active_batch_allowed": index < wip_limit,
                "cursor": batch["cursor"],
            }
            for index, batch in enumerate(batches)
            if batch["full_text_recommended_count"]
        ],
        "sample_check": _sample_plan(normalized, sample_rate),
        "main_library_candidates": [
            {
                "candidate_id": _stable_id("main-library-candidate", item["source_id"]),
                "source_id": item["source_id"],
                "library_shelf_candidates": ["toolbook", "xingce"],
                "status": "candidate",
                "requires_verbatim_excerpt": True,
                "requires_source_refs": True,
                "requires_sample_check": True,
                "write_performed": False,
            }
            for item in high_signal[:100]
        ],
        "policies": {
            "raw_authority_policy": "raw_source_text_is_highest_authority",
            "summary_policy": "summaries_are_navigation_not_source_replacement",
            "throughput_policy": "minimum_viable_processing_before_refinement",
            "screening_policy": "metadata_before_full_text",
            "review_policy": "small_batches_with_wip_limit",
            "sample_check_policy": "controller_samples_included_and_excluded_items",
            "promotion_policy": "candidate_before_main_library_refinement",
        },
    }
