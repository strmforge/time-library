#!/usr/bin/env python3
"""Explainability helpers for raw recall.

This module owns diagnostic projections around raw recall: adjacent context
refs, library-index projection receipts, and recall trajectories. It is not a
raw origin, not a memory writer, and not an HTTP/MCP gateway.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

try:
    from src.raw_evidence_excerpt import MAX_RAW_STREAM_SCAN_BYTES, _resolve_source_path
    from src.raw_text_decode import iter_decoded_jsonl_lines as _iter_decoded_jsonl_lines
except Exception:  # pragma: no cover - direct script import fallback
    from raw_evidence_excerpt import MAX_RAW_STREAM_SCAN_BYTES, _resolve_source_path
    from raw_text_decode import iter_decoded_jsonl_lines as _iter_decoded_jsonl_lines


CONTEXT_BUNDLE_WINDOW = 1
CONTEXT_BUNDLE_CONTRACT = "raw_context_bundle_refs.v2026.6.20"
CONTEXT_BUNDLE_POLICY = "anchor_plus_adjacent_raw_refs_no_excerpt"
LIBRARY_INDEX_PROJECTION_CONTRACT = "library_index_projection_receipt.v2026.6.17"
LIBRARY_INDEX_PROJECTION_POLICY = "navigation_hint_only_raw_evidence_required"
RAW_RECALL_TRAJECTORY_CONTRACT = "raw_recall_trajectory.v2026.6.17"
RAW_RECALL_TRAJECTORY_POLICY = "retrieval_steps_are_diagnostics_not_evidence"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _jsonl_obj_candidate_msg_ids(obj: Dict[str, Any], start: int) -> List[str]:
    candidates: List[str] = []

    def add(value: Any) -> None:
        text = _clean_text(value)
        if text and text not in candidates:
            candidates.append(text)

    add(obj.get("id"))
    payload = obj.get("payload", {}) if isinstance(obj.get("payload"), dict) else {}
    add(payload.get("turn_id"))
    add(obj.get("timestamp"))
    if isinstance(obj.get("messages"), list):
        for idx, _ in enumerate(obj["messages"]):
            add(f"msg_{idx + 1:03d}")
    add(f"offset:{start}")
    return candidates


def _jsonl_obj_role(obj: Dict[str, Any]) -> str:
    if obj.get("type") == "message":
        message = obj.get("message", {}) if isinstance(obj.get("message"), dict) else {}
        return _clean_text(message.get("role")) or "unknown"
    payload = obj.get("payload", {}) if isinstance(obj.get("payload"), dict) else {}
    payload_type = _clean_text(payload.get("type"))
    if payload_type == "user_message":
        return "user"
    if payload_type == "agent_message":
        return "assistant"
    if payload_type == "function_call_output":
        return "tool"
    if payload_type == "message":
        return _clean_text(payload.get("role")) or "unknown"
    if obj.get("type") == "human":
        return "user"
    if obj.get("type") == "ai":
        return "assistant"
    if isinstance(obj.get("messages"), list):
        return "batch"
    return "unknown"


def _jsonl_obj_timestamp(obj: Dict[str, Any]) -> str:
    payload = obj.get("payload", {}) if isinstance(obj.get("payload"), dict) else {}
    return _first_text(
        obj.get("timestamp"),
        obj.get("created_at"),
        payload.get("timestamp"),
        payload.get("created_at"),
    )


def _context_bundle_ref(
    *,
    item: Dict[str, Any],
    source_path: str,
    record: Dict[str, Any],
    distance: int,
) -> Dict[str, Any]:
    direction = "anchor"
    if distance < 0:
        direction = "previous"
    elif distance > 0:
        direction = "next"
    ref_seed = "|".join([
        _clean_text(item.get("source_system")),
        source_path,
        str(record.get("start", "")),
        str(record.get("end", "")),
        ",".join(str(mid) for mid in (record.get("msg_ids") or [])),
    ])
    ref: Dict[str, Any] = {
        "ref_id": hashlib.sha256(ref_seed.encode("utf-8")).hexdigest()[:24],
        "source_system": item.get("source_system", ""),
        "computer_name": item.get("computer_name", ""),
        "canonical_window_id": item.get("canonical_window_id", ""),
        "source_refs_canonical_window_id": item.get("source_refs_canonical_window_id", ""),
        "session_id": item.get("session_id", ""),
        "project_id": item.get("project_id", ""),
        "project_root": item.get("project_root", ""),
        "workstream_id": item.get("workstream_id", ""),
        "task_id": item.get("task_id", ""),
        "source_path": source_path,
        "artifact_type": item.get("artifact_type") or f"{item.get('source_system', 'source')}_raw_record",
        "msg_ids": record.get("msg_ids") or [],
        "distance": distance,
        "neighbor_direction": direction,
        "bundle_role": "anchor" if distance == 0 else "neighbor",
        "role": record.get("role", ""),
        "timestamp": record.get("timestamp", ""),
        "byte_offsets": {"start": record.get("start", 0), "end": record.get("end", 0)},
        "evidence_hash": record.get("evidence_hash", ""),
        "raw_evidence_status": "raw_context_ref",
    }
    return {key: value for key, value in ref.items() if value not in ("", None, [], {})}


def context_bundle_for_item(
    item: Dict[str, Any],
    *,
    window: int = CONTEXT_BUNDLE_WINDOW,
) -> Dict[str, Any]:
    source_path = _clean_text(item.get("source_path"))
    anchor_ids = [str(mid) for mid in (item.get("msg_ids") or []) if str(mid)]
    if not source_path:
        return {"status": "missing_source_path", "refs": []}
    if not anchor_ids:
        return {"status": "missing_msg_ids", "refs": []}
    resolved = _resolve_source_path(source_path)
    if resolved is None or not resolved.exists():
        return {"status": "missing_source_path", "refs": []}
    try:
        if resolved.stat().st_size > MAX_RAW_STREAM_SCAN_BYTES:
            return {"status": "skipped_large_source_path", "refs": []}
    except Exception:
        return {"status": "source_stat_error", "refs": []}

    records: List[Dict[str, Any]] = []
    anchor_index = -1
    anchor_set = set(anchor_ids)
    try:
        for start, end, line in _iter_decoded_jsonl_lines(resolved):
            text = line.strip()
            if not text or not text.startswith("{"):
                continue
            try:
                obj = json.loads(text)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            msg_ids = _jsonl_obj_candidate_msg_ids(obj, start)
            record = {
                "start": start,
                "end": end,
                "msg_ids": msg_ids,
                "role": _jsonl_obj_role(obj),
                "timestamp": _jsonl_obj_timestamp(obj),
                "evidence_hash": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest(),
            }
            if anchor_index < 0 and anchor_set.intersection(msg_ids):
                anchor_index = len(records)
            records.append(record)
    except Exception:
        return {"status": "read_error", "refs": []}

    if anchor_index < 0:
        return {"status": "anchor_not_found", "refs": []}
    start_index = max(0, anchor_index - max(0, window))
    end_index = min(len(records), anchor_index + max(0, window) + 1)
    refs = [
        _context_bundle_ref(
            item=item,
            source_path=source_path,
            record=records[index],
            distance=index - anchor_index,
        )
        for index in range(start_index, end_index)
    ]
    return {
        "status": "hit",
        "refs": refs,
        "anchor_index": anchor_index,
        "records_scanned": len(records),
    }


def attach_context_bundles_to_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    items_count = 0
    refs_count = 0
    statuses: Dict[str, int] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if item.get("context_bundle_refs"):
            refs = item.get("context_bundle_refs") if isinstance(item.get("context_bundle_refs"), list) else []
            if refs:
                items_count += 1
                refs_count += len(refs)
            continue
        bundle = context_bundle_for_item(item)
        status = _clean_text(bundle.get("status")) or "unknown"
        statuses[status] = statuses.get(status, 0) + 1
        refs = bundle.get("refs") if isinstance(bundle.get("refs"), list) else []
        item["context_bundle_contract"] = CONTEXT_BUNDLE_CONTRACT
        item["context_bundle_policy"] = CONTEXT_BUNDLE_POLICY
        item["context_bundle_window"] = CONTEXT_BUNDLE_WINDOW
        item["context_bundle_available"] = bool(refs)
        item["context_bundle_status"] = status
        if refs:
            item["context_bundle_refs"] = refs
            item["context_bundle_size"] = len(refs)
            items_count += 1
            refs_count += len(refs)
        else:
            item["context_bundle_size"] = 0
    return {
        "context_bundle_policy": CONTEXT_BUNDLE_POLICY,
        "context_bundle_contract": CONTEXT_BUNDLE_CONTRACT,
        "context_bundle_window": CONTEXT_BUNDLE_WINDOW,
        "context_bundle_items_count": items_count,
        "context_bundle_refs_count": refs_count,
        "context_bundle_status_counts": statuses,
    }


def library_index_projection_refs(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if not item.get("library_index_projection_used") and item.get("matched_by") != ["catalog_index"]:
            matched_by = item.get("matched_by") if isinstance(item.get("matched_by"), list) else []
            if "catalog_index" not in matched_by and item.get("rank_reason") != "catalog_index":
                continue
        key = (
            str(item.get("source_system", "")),
            str(item.get("source_path", "")),
            str(item.get("session_id", "")),
            tuple(item.get("msg_ids") or []),
        )
        if key in seen:
            continue
        seen.add(key)
        refs.append({
            "projection_contract": LIBRARY_INDEX_PROJECTION_CONTRACT,
            "projection_policy": LIBRARY_INDEX_PROJECTION_POLICY,
            "projection_kind": "library_index_projection",
            "authority": "navigation_hint_only_raw_evidence_required",
            "source_system": item.get("source_system", ""),
            "computer_name": item.get("computer_name", ""),
            "canonical_window_id": item.get("canonical_window_id", ""),
            "source_refs_canonical_window_id": item.get("source_refs_canonical_window_id", ""),
            "session_id": item.get("session_id", ""),
            "project_id": item.get("project_id", ""),
            "project_root": item.get("project_root", ""),
            "workstream_id": item.get("workstream_id", ""),
            "task_id": item.get("task_id", ""),
            "source_path": item.get("source_path", ""),
            "msg_ids": item.get("msg_ids", []) or [],
            "library_id": item.get("library_id", ""),
            "library_shelf": item.get("library_shelf", ""),
            "raw_evidence_status": item.get("raw_evidence_status", ""),
        })
    return [
        {key: value for key, value in ref.items() if value not in ("", None, [], {})}
        for ref in refs
    ]


def mark_library_index_projection_item(item: Dict[str, Any], *, status: str = "") -> Dict[str, Any]:
    item["library_index_projection_used"] = True
    item["library_index_projection_contract"] = LIBRARY_INDEX_PROJECTION_CONTRACT
    item["library_index_projection_policy"] = LIBRARY_INDEX_PROJECTION_POLICY
    item["library_index_projection_kind"] = "canonical_catalog_index"
    item["library_index_projection_authority"] = "navigation_hint_only_raw_evidence_required"
    if status:
        item["library_index_projection_status"] = status
    return item


def raw_recall_trajectory(
    *,
    scope: Dict[str, Any],
    source_system_filters: List[str],
    primary_recall_items_count: int,
    primary_recall_backend: str,
    needs_more_candidates: bool,
    catalog_index_eligible: bool,
    catalog_index_used: bool,
    catalog_index_status: str,
    catalog_index_items_count: int,
    raw_fallback_eligible: bool,
    raw_fallback_stats: Dict[str, Any],
    active_scope: bool,
    active_layers_used: List[str],
    context_bundle_stats: Dict[str, Any],
    matched_count: int,
    source_refs_count: int,
    raw_items_count: int,
    raw_evidence_status: str,
) -> List[Dict[str, Any]]:
    memory_scope = _clean_text(scope.get("memory_scope")) or "unknown"
    steps: List[Dict[str, Any]] = [
        {
            "step": "primary_recall",
            "layer": "candidate_records",
            "status": "hit" if primary_recall_items_count else "miss",
            "backend": primary_recall_backend,
            "items_count": primary_recall_items_count,
            "memory_scope": memory_scope,
            "source_system_filters": source_system_filters,
            "authority": "candidate_source_refs_not_final_evidence",
        },
        {
            "step": "catalog_index_projection",
            "layer": "L1_library_index_projection",
            "status": catalog_index_status if catalog_index_eligible else "skipped_not_eligible",
            "eligible": catalog_index_eligible,
            "used": catalog_index_used,
            "items_count": catalog_index_items_count,
            "authority": LIBRARY_INDEX_PROJECTION_POLICY,
            "policy": LIBRARY_INDEX_PROJECTION_POLICY,
        },
        {
            "step": "raw_fallback",
            "layer": "L2_raw_records",
            "status": raw_fallback_stats.get("raw_fallback_status") or "unknown",
            "eligible": raw_fallback_eligible,
            "used": bool(raw_fallback_stats.get("raw_fallback_used")),
            "scanned_files": int(raw_fallback_stats.get("raw_fallback_scanned_files") or 0),
            "scanned_lines": int(raw_fallback_stats.get("raw_fallback_scanned_lines") or 0),
            "truncated": bool(raw_fallback_stats.get("raw_fallback_truncated")),
            "timed_out": bool(raw_fallback_stats.get("raw_fallback_timed_out")),
            "authority": "raw_records_are_final_evidence",
        },
        {
            "step": "active_layer_routing",
            "layer": "active_memory_layers",
            "status": "applied" if active_scope else "not_active_scope",
            "active_scope": active_scope,
            "active_layers_used": active_layers_used,
            "needs_more_candidates_before_routing": needs_more_candidates,
            "authority": "routing_only_not_evidence",
        },
        {
            "step": "context_bundle_refs",
            "layer": "adjacent_raw_refs",
            "status": "hit" if int(context_bundle_stats.get("context_bundle_refs_count") or 0) else "miss",
            "items_count": int(context_bundle_stats.get("context_bundle_items_count") or 0),
            "refs_count": int(context_bundle_stats.get("context_bundle_refs_count") or 0),
            "policy": CONTEXT_BUNDLE_POLICY,
            "authority": "adjacent_raw_refs_no_excerpt",
        },
        {
            "step": "final_receipt",
            "layer": "borrow_receipt",
            "status": raw_evidence_status,
            "matched_count": matched_count,
            "source_refs_count": source_refs_count,
            "raw_items_count": raw_items_count,
            "authority": "source_refs_and_raw_offsets",
        },
    ]
    return [
        {key: value for key, value in step.items() if value not in ("", None, [], {})}
        for step in steps
    ]


def consumer_receipt(
    *,
    consumer: str,
    request_id: str,
    items_count: int,
    source_refs_count: int,
    raw_items_count: int,
    items: List[Dict[str, Any]] | None = None,
    raw_trajectory: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    used_items = items or []
    used_library_ids = [
        str(item.get("library_id") or "")
        for item in used_items
        if str(item.get("library_id") or "")
    ]
    used_source_refs = [
        {
            "library_id": item.get("library_id", ""),
            "source_system": item.get("source_system", ""),
            "source_path": item.get("source_path", ""),
            "session_id": item.get("session_id", ""),
            "msg_ids": item.get("msg_ids", []) or [],
        }
        for item in used_items
        if item.get("source_path")
    ]
    context_bundle_refs_count = sum(
        len(item.get("context_bundle_refs") or [])
        for item in used_items
        if isinstance(item, dict) and isinstance(item.get("context_bundle_refs"), list)
    )
    projection_refs = library_index_projection_refs(used_items)
    return {
        "consumer": consumer or "unknown",
        "request_id": request_id or "",
        "consumed_at": ts(),
        "query_path": "/api/v1/raw/query",
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "skill_write": False,
        "memory_write": False,
        "config_write": False,
        "items_count": items_count,
        "source_refs_count": source_refs_count,
        "raw_items_count": raw_items_count,
        "context_bundle_refs_count": context_bundle_refs_count,
        "library_index_projection_used": bool(projection_refs),
        "library_index_projection_refs_count": len(projection_refs),
        "library_index_projection_policy": LIBRARY_INDEX_PROJECTION_POLICY,
        "library_index_projection_refs": projection_refs,
        "raw_recall_trajectory_contract": RAW_RECALL_TRAJECTORY_CONTRACT,
        "raw_recall_trajectory_policy": RAW_RECALL_TRAJECTORY_POLICY,
        "raw_recall_trajectory": raw_trajectory or [],
        "used_library_ids": used_library_ids,
        "used_source_refs": used_source_refs,
        "matched_by": {
            item.get("library_id", ""): item.get("matched_by", [])
            for item in used_items
            if item.get("library_id")
        },
        "rank_reason": {
            item.get("library_id", ""): item.get("rank_reason", "")
            for item in used_items
            if item.get("library_id")
        },
        "receipt_scope": "raw_source_refs_live_gateway",
    }


def build_query_payload_from_items(
    *,
    query: str,
    consumer: str,
    request_id: str,
    effective_source_system: str,
    scope: Dict[str, Any],
    effective_window_id: str,
    effective_session_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
    binding: Dict[str, Any],
    binding_applied_fields: List[str],
    active_layers_used: List[str],
    items: List[Dict[str, Any]],
    injection_boundary: str,
    tiandao_context_builder: Callable[..., Dict[str, Any]],
    library_manifest_payload: Dict[str, Any],
    hybrid_recall_manifest_payload: Dict[str, Any],
    raw_status_fn: Callable[[str], bool],
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    context_bundle_stats = attach_context_bundles_to_items(items)
    projection_refs = library_index_projection_refs(items)
    projection_stats = {
        "library_index_projection_contract": LIBRARY_INDEX_PROJECTION_CONTRACT,
        "library_index_projection_policy": LIBRARY_INDEX_PROJECTION_POLICY,
        "library_index_projection_used": bool(projection_refs),
        "library_index_projection_refs_count": len(projection_refs),
        "library_index_projection_refs": projection_refs,
    }
    source_refs_count = sum(1 for item in items if item.get("source_path"))
    raw_items_count = sum(1 for item in items if raw_status_fn(item.get("raw_evidence_status", "")))
    raw_evidence_status = "raw" if raw_items_count > 0 else "not_raw"
    extra = extra or {}
    source_system_filters = extra.get("raw_recall_source_system_filters")
    if not isinstance(source_system_filters, list):
        source_system_filters = [effective_source_system] if effective_source_system else []
    raw_fallback_stats = extra.get("raw_fallback_stats")
    if not isinstance(raw_fallback_stats, dict):
        raw_fallback_stats = {
            "raw_fallback_used": bool(extra.get("raw_fallback_used", False)),
            "raw_fallback_status": str(extra.get("raw_fallback_status") or "not_attempted"),
            "raw_fallback_scanned_files": int(extra.get("raw_fallback_scanned_files") or 0),
            "raw_fallback_scanned_lines": int(extra.get("raw_fallback_scanned_lines") or 0),
            "raw_fallback_truncated": bool(extra.get("raw_fallback_truncated", False)),
            "raw_fallback_timed_out": bool(extra.get("raw_fallback_timed_out", False)),
        }
    primary_recall_items_count = (
        int(extra.get("raw_recall_primary_items_count") or 0)
        if "raw_recall_primary_items_count" in extra
        else len(items)
    )
    trajectory = raw_recall_trajectory(
        scope=scope,
        source_system_filters=source_system_filters,
        primary_recall_items_count=primary_recall_items_count,
        primary_recall_backend=str(extra.get("raw_recall_primary_backend") or extra.get("primary_recall_backend") or ""),
        needs_more_candidates=bool(extra.get("raw_recall_needs_more_candidates", False)),
        catalog_index_eligible=bool(extra.get("catalog_index_eligible", False)),
        catalog_index_used=bool(extra.get("catalog_index_used", False)),
        catalog_index_status=str(extra.get("catalog_index_status") or "not_attempted"),
        catalog_index_items_count=int(extra.get("catalog_index_items_count") or 0),
        raw_fallback_eligible=bool(extra.get("raw_fallback_eligible", False)),
        raw_fallback_stats=raw_fallback_stats,
        active_scope=scope["memory_scope"] == "active",
        active_layers_used=active_layers_used,
        context_bundle_stats=context_bundle_stats,
        matched_count=len(items),
        source_refs_count=source_refs_count,
        raw_items_count=raw_items_count,
        raw_evidence_status=raw_evidence_status,
    )
    tiandao_context_package = tiandao_context_builder(
        query=query,
        source_system=effective_source_system,
        consumer=consumer,
        canonical_window_id=effective_window_id,
        session_id=effective_session_id,
        items=items,
        memory_scope=scope["memory_scope"],
        memory_base_scope=scope["memory_base_scope"],
        scope_missing=False,
        active_layers_used=active_layers_used,
        binding=binding,
        binding_applied_fields=binding_applied_fields,
        cross_window_read=scope["cross_window_read"],
        cross_window_read_allowed=scope["cross_window_read_allowed"],
        injection_boundary=injection_boundary,
    )
    payload = {
        "ok": True,
        "consumer": consumer or "unknown",
        "query": query,
        "source_system_filter": effective_source_system or "all",
        "requested_source_system": scope["requested_source_system"],
        "inferred_source_system": scope["inferred_source_system"],
        "memory_scope": scope["memory_scope"],
        "memory_base_scope": scope["memory_base_scope"],
        "scope_missing": False,
        "missing_scope_fields": [],
        "cross_window_read": scope["cross_window_read"],
        "cross_window_read_allowed": scope["cross_window_read_allowed"],
        "hermes_global_exception": scope["hermes_global_exception"],
        "hermes_plain_recall_is_global_exception": scope.get("hermes_plain_recall_is_global_exception", False),
        "hermes_broad_context_workflow": scope.get("hermes_broad_context_workflow", False),
        "cross_window_reason": scope.get("cross_window_reason", ""),
        "canonical_window_id_filter": effective_window_id,
        "project_id_filter": project_id,
        "project_root_filter": project_root,
        "workstream_id_filter": workstream_id,
        "task_id_filter": task_id,
        "current_window_binding_applied": bool(binding_applied_fields),
        "current_window_binding_key": binding.get("binding_key", "") if binding else "",
        "current_window_binding_fields": binding_applied_fields,
        "active_layers_used": active_layers_used,
        "agent_boundary": "active_window_first_explicit_broad_scope",
        "injection_boundary": injection_boundary,
        "tiandao_context_package": tiandao_context_package,
        "tiandao_context_package_valid": tiandao_context_package.get("validation", {}).get("valid", True),
        "zhixing_library": library_manifest_payload,
        "hybrid_recall": hybrid_recall_manifest_payload,
        "matched_count": len(items),
        "source_refs_count": source_refs_count,
        "raw_items_count": raw_items_count,
        "raw_recall_primary_items_count": primary_recall_items_count,
        "raw_recall_trajectory_contract": RAW_RECALL_TRAJECTORY_CONTRACT,
        "raw_recall_trajectory_policy": RAW_RECALL_TRAJECTORY_POLICY,
        "raw_recall_trajectory": trajectory,
        **projection_stats,
        **context_bundle_stats,
        "items": items,
        "raw_evidence_status": raw_evidence_status,
        "zhiyi_experience_used_as_raw": False,
        "consumer_receipt": consumer_receipt(
            consumer=consumer,
            request_id=request_id,
            items_count=len(items),
            source_refs_count=source_refs_count,
            raw_items_count=raw_items_count,
            items=items,
            raw_trajectory=trajectory,
        ),
    }
    if extra:
        payload.update({
            key: value
            for key, value in extra.items()
            if not str(key).startswith("raw_recall_")
            and key not in {"raw_fallback_stats", "catalog_index_eligible", "raw_fallback_eligible"}
        })
    return payload
