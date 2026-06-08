#!/usr/bin/env python3
"""Second Brain orchestration helpers.

Second Brain is the first large module under the Time River Tiandao line. It
orchestrates material intake, evidence planning, context units, method signals,
delivery compaction, sediment links, and a review receipt. It does not replace
raw records and does not write durable memory by itself.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List

try:
    from src.material_processing_pipeline import build_material_processing_pipeline_dry_run
    from src.external_docs_evidence import build_external_docs_evidence_dry_run
    from src.context_delivery_compaction import build_context_delivery_compaction_dry_run
    from src.zhixing_context_unit import build_context_budget_unit_candidate
    from src.zhixing_method_signal import build_method_signal_candidate
    from src.time_river_sediment import build_sediment_link
except Exception:  # pragma: no cover
    from material_processing_pipeline import build_material_processing_pipeline_dry_run
    from external_docs_evidence import build_external_docs_evidence_dry_run
    from context_delivery_compaction import build_context_delivery_compaction_dry_run
    from zhixing_context_unit import build_context_budget_unit_candidate
    from zhixing_method_signal import build_method_signal_candidate
    from time_river_sediment import build_sediment_link


SECOND_BRAIN_VERSION = "2026.6.8"
SECOND_BRAIN_CONTRACT = "tiandao_second_brain.v1"
SECOND_BRAIN_ZH_NAME = "第二大脑"
SECOND_BRAIN_EN_NAME = "Second Brain"
DEFAULT_PLAN_LIMIT = 20


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


def _first_text(body: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean_text(body.get(key))
        if value:
            return value
    return ""


def _stable_id(prefix: str, seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _source_refs_for(source: Dict[str, Any]) -> Dict[str, Any]:
    refs = source.get("source_refs")
    if isinstance(refs, dict):
        return dict(refs)
    path = _clean_text(source.get("path") or source.get("source_path") or source.get("path_or_url"))
    url = _clean_text(source.get("url") or source.get("source_url"))
    if not path and not url:
        return {}
    out: Dict[str, Any] = {"source_system": _clean_text(source.get("source_system")) or "second_brain_material"}
    if path:
        out["source_path"] = path
    if url:
        out["source_url"] = url
    return out


def _source_text(source: Dict[str, Any]) -> str:
    parts = [
        _clean_text(source.get("title") or source.get("name")),
        _clean_text(source.get("summary") or source.get("metadata_summary") or source.get("description")),
        _clean_text(source.get("content") or source.get("text") or source.get("body") or source.get("full_text")),
    ]
    return "\n".join(part for part in parts if part)


def _source_title(source: Dict[str, Any], fallback: str) -> str:
    return _clean_text(source.get("title") or source.get("name") or source.get("source_id") or fallback)


def _high_signal_sources(material_pipeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    sources = material_pipeline.get("registered_sources")
    if not isinstance(sources, list):
        return []
    return [
        item for item in sources
        if isinstance(item, dict)
        and (item.get("screening") or {}).get("full_text_recommended")
    ]


def _source_by_id(sources: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for item in sources:
        if not isinstance(item, dict):
            continue
        source_id = _clean_text(item.get("source_id") or item.get("id"))
        if source_id:
            result[source_id] = item
    return result


def _original_source_for(registered: Dict[str, Any], original_by_id: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    source_id = _clean_text(registered.get("source_id"))
    return original_by_id.get(source_id, registered)


def _build_context_unit_for_source(need: str, source: Dict[str, Any], registered: Dict[str, Any]) -> Dict[str, Any]:
    text = _source_text(source) or _clean_text(registered.get("metadata_summary")) or _source_title(source, registered.get("source_id", ""))
    source_refs = _source_refs_for(source) or registered.get("source_refs") or {}
    return build_context_budget_unit_candidate({
        "unit_text": text[:1200],
        "verbatim_excerpt": text[:1200],
        "source_refs": source_refs,
        "objective_link": need,
        "unit_kind": "context_snippet",
        "context_slot": "current_task",
    })


def _build_method_signal_for_source(need: str, source: Dict[str, Any], registered: Dict[str, Any]) -> Dict[str, Any]:
    text = _source_text(source) or _clean_text(registered.get("metadata_summary"))
    source_refs = _source_refs_for(source) or registered.get("source_refs") or {}
    title = _source_title(source, registered.get("source_id", ""))
    return build_method_signal_candidate({
        "title": title,
        "signal": text or title,
        "verbatim_excerpt": text or title,
        "source_refs": source_refs,
        "proposed_trigger": need,
        "proposed_mechanism": "material enters Second Brain review queue before promotion",
        "initial_scope": "second_brain_material_review",
        "allow_non_route_signal": True,
    })


def _build_external_docs_for_source(need: str, source: Dict[str, Any], registered: Dict[str, Any]) -> Dict[str, Any]:
    text = " ".join([
        need,
        _source_title(source, registered.get("source_id", "")),
        _clean_text(registered.get("metadata_summary")),
    ]).strip()
    return build_external_docs_evidence_dry_run({
        "query": text,
        "source_refs": _source_refs_for(source) or registered.get("source_refs") or {},
    })


def _build_compaction_for_source(source: Dict[str, Any], registered: Dict[str, Any]) -> Dict[str, Any]:
    text = _source_text(source)
    if not text:
        text = _clean_text(registered.get("metadata_summary"))
    return build_context_delivery_compaction_dry_run({
        "content": text,
        "source_refs": _source_refs_for(source) or registered.get("source_refs") or {},
        "target_tokens": 1200,
        "max_tokens": 2400,
    })


def _build_sediment_for_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    return build_sediment_link({
        "library_id": candidate.get("candidate_id", ""),
        "library_shelf": "toolbook",
        "source_refs": candidate.get("source_refs") or {},
        "summary": candidate.get("source_id", ""),
        "status": "candidate",
    })


def get_second_brain_contract() -> Dict[str, Any]:
    return {
        "ok": True,
        "version": SECOND_BRAIN_VERSION,
        "contract": SECOND_BRAIN_CONTRACT,
        "zh_name": SECOND_BRAIN_ZH_NAME,
        "en_name": SECOND_BRAIN_EN_NAME,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "network_call_performed": False,
        "time_river_module": True,
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "first_major_module_under_time_river": True,
        "not_raw_origin": True,
        "not_a_platform_adapter": True,
        "orchestration_role": "material_to_candidate_to_sediment_review",
        "endpoint": "/api/v1/tiandao/second-brain/dry-run",
        "required_fields": ["need_or_question", "sources"],
        "orchestrated_modules": [
            "material_processing_pipeline",
            "external_docs_evidence",
            "context_budget_unit",
            "method_signal",
            "context_delivery_compaction",
            "time_river_sediment",
        ],
        "output_sections": [
            "material_pipeline",
            "evidence_plans",
            "context_units",
            "method_signals",
            "compaction_plans",
            "sediment_links",
            "receipt",
        ],
        "forbidden_by_default": [
            "write_summary_as_raw",
            "write_durable_memory",
            "write_platform_config",
            "claim_adoption_without_replay_or_sample_check",
            "replace_raw_origin",
        ],
    }


def build_second_brain_dry_run(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    need = _first_text(body, "need", "question", "query", "task", "goal")
    raw_sources = body.get("sources")
    if not isinstance(raw_sources, list):
        raw_sources = _as_list(raw_sources)
    sources = [item for item in raw_sources if isinstance(item, dict)]
    plan_limit = int(body.get("plan_limit") or DEFAULT_PLAN_LIMIT)
    plan_limit = max(1, min(100, plan_limit))
    material_pipeline = build_material_processing_pipeline_dry_run({
        "need": need,
        "sources": sources,
        "batch_size": body.get("batch_size"),
        "wip_limit": body.get("wip_limit"),
        "sample_rate": body.get("sample_rate"),
    })
    registered = material_pipeline.get("registered_sources") if isinstance(material_pipeline.get("registered_sources"), list) else []
    high_signal = _high_signal_sources(material_pipeline)[:plan_limit]
    original_by_id = _source_by_id(sources)
    evidence_plans: List[Dict[str, Any]] = []
    context_units: List[Dict[str, Any]] = []
    method_signals: List[Dict[str, Any]] = []
    compaction_plans: List[Dict[str, Any]] = []
    for item in high_signal:
        original = _original_source_for(item, original_by_id)
        evidence_plans.append(_build_external_docs_for_source(need, original, item))
        context_units.append(_build_context_unit_for_source(need, original, item))
        method_signals.append(_build_method_signal_for_source(need, original, item))
        compaction_plans.append(_build_compaction_for_source(original, item))
    sediment_links = [
        _build_sediment_for_candidate(candidate)
        for candidate in material_pipeline.get("main_library_candidates", [])[:plan_limit]
        if isinstance(candidate, dict)
    ]
    candidate_id = _stable_id("second-brain", "|".join([need, str(len(sources)), str(plan_limit)]))
    missing: List[str] = []
    if not need:
        missing.append("need_or_question")
    if not sources:
        missing.append("sources")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ready_candidates = sum(1 for item in sediment_links if item.get("source_refs_available"))
    trusted_sediments = sum(1 for item in sediment_links if item.get("trusted_sediment"))
    return {
        "ok": not missing and bool(material_pipeline.get("ok")),
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "network_call_performed": False,
        "version": SECOND_BRAIN_VERSION,
        "contract": SECOND_BRAIN_CONTRACT,
        "zh_name": SECOND_BRAIN_ZH_NAME,
        "en_name": SECOND_BRAIN_EN_NAME,
        "candidate_id": candidate_id if not missing else "",
        "created_at": now_iso,
        "need": need,
        "missing": missing,
        "error": "invalid_second_brain_input" if missing else "",
        "material_pipeline": material_pipeline,
        "evidence_plans": evidence_plans,
        "context_units": context_units,
        "method_signals": method_signals,
        "compaction_plans": compaction_plans,
        "sediment_links": sediment_links,
        "summary": {
            "source_count": len(sources),
            "high_signal_count": len(high_signal),
            "evidence_plan_count": len(evidence_plans),
            "context_unit_count": len(context_units),
            "method_signal_count": len(method_signals),
            "compaction_plan_count": len(compaction_plans),
            "sediment_link_count": len(sediment_links),
            "source_refs_ready_candidate_count": ready_candidates,
            "trusted_sediment_count": trusted_sediments,
            "sample_check_required": bool((material_pipeline.get("summary") or {}).get("sample_check_required")),
        },
        "receipt": {
            "receipt_id": _stable_id("second-brain-receipt", "|".join([candidate_id, now_iso])),
            "contract": "second_brain_receipt.v1",
            "created_at": now_iso,
            "read_only": True,
            "write_performed": False,
            "need": need,
            "pipeline_candidate_id": material_pipeline.get("candidate_id", ""),
            "batch_count": (material_pipeline.get("summary") or {}).get("batch_count", 0),
            "worker_queue_count": len(material_pipeline.get("worker_queue") or []),
            "sample_check": material_pipeline.get("sample_check", {}),
            "promotion_gate": "sample_check_and_replay_before_adoption",
            "raw_authority_policy": "raw_source_text_is_highest_authority",
            "summary_policy": "summaries_are_navigation_not_source_replacement",
        },
        "policies": {
            "parent_tiandao_contract": "tiandao_time_river.v1",
            "raw_origin_policy": "second_brain_does_not_replace_time_origin",
            "orchestration_policy": "compose_existing_candidates_do_not_duplicate_authority",
            "promotion_policy": "candidate_before_main_library_refinement",
            "global_recall_policy": "explicit_only",
        },
    }
