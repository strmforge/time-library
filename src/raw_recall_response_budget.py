"""Response-budget projection for source-backed raw recall.

The raw gateway keeps full evidence internally. This module owns the public
exit projection so MCP and HTTP callers get compact source anchors by default,
while explicit raw requests can still expand bounded original evidence.
"""

from __future__ import annotations

from typing import Any, Dict


MAX_COMPACT_ITEMS = 5


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def response_budget_mode(args: Dict[str, Any] | None) -> str:
    args = args if isinstance(args, dict) else {}
    mode = _clean_text(args.get("response_budget") or args.get("budget") or "").lower()
    request_mode = _clean_text(args.get("mode") or "").lower()
    if mode in {"raw", "full", "verbatim", "audit"} or request_mode == "raw":
        return "raw"
    if mode in {"standard", "default"}:
        return "standard"
    return "compact"


def include_raw_excerpt(args: Dict[str, Any] | None) -> bool:
    args = args if isinstance(args, dict) else {}
    if response_budget_mode(args) == "raw":
        return True
    return _truthy(args.get("include_raw_excerpt")) or _truthy(args.get("include_raw"))


def _compact_gateway_item(item: Any, *, include_raw_excerpt: bool = False) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    compact: Dict[str, Any] = {}
    for key in (
        "library_id",
        "library_shelf",
        "type",
        "memory_type",
        "exp_id",
        "summary",
        "should_inject",
        "confidence",
        "source_system",
        "computer_name",
        "canonical_window_id",
        "source_refs_canonical_window_id",
        "session_id",
        "project_id",
        "project_root",
        "workstream_id",
        "task_id",
        "active_memory_layer",
        "native_session_key",
        "source_path",
        "msg_ids",
        "evidence_hash",
        "created_at",
        "raw_evidence_status",
        "zhiyi_experience_used_as_raw",
        "matched_by",
        "rank_reason",
        "context_bundle_contract",
        "context_bundle_policy",
        "context_bundle_window",
        "context_bundle_available",
        "context_bundle_status",
        "context_bundle_size",
        "library_index_projection_used",
        "library_index_projection_contract",
        "library_index_projection_policy",
        "library_index_projection_kind",
        "library_index_projection_authority",
        "library_index_projection_status",
    ):
        value = item.get(key)
        if value not in ("", None, [], {}):
            compact[key] = value
    bundle_refs = item.get("context_bundle_refs") if isinstance(item.get("context_bundle_refs"), list) else []
    if bundle_refs:
        compact["context_bundle_refs"] = [
            {
                key: ref.get(key)
                for key in (
                    "ref_id",
                    "source_system",
                    "computer_name",
                    "canonical_window_id",
                    "source_refs_canonical_window_id",
                    "session_id",
                    "project_id",
                    "project_root",
                    "workstream_id",
                    "task_id",
                    "source_path",
                    "artifact_type",
                    "msg_ids",
                    "distance",
                    "neighbor_direction",
                    "bundle_role",
                    "role",
                    "timestamp",
                    "byte_offsets",
                    "evidence_hash",
                    "raw_evidence_status",
                )
                if isinstance(ref, dict) and ref.get(key) not in ("", None, [], {})
            }
            for ref in bundle_refs
        ]
    if include_raw_excerpt and item.get("raw_excerpt"):
        compact["raw_excerpt"] = item.get("raw_excerpt")
    for nested_key in ("project_status", "xingce_candidate"):
        value = item.get(nested_key)
        if isinstance(value, dict):
            compact[nested_key] = {
                key: nested_value
                for key, nested_value in value.items()
                if nested_value not in ("", None, [], {})
            }
    return compact


def _compact_tiandao_context_package(
    package: Any,
    *,
    include_raw_projection: bool = False,
) -> Dict[str, Any]:
    if not isinstance(package, dict):
        return {}
    compact: Dict[str, Any] = {}
    for key in (
        "schema",
        "query_hash",
        "source_system",
        "canonical_window_id",
        "session_id",
        "intent_mode",
        "memory_context_mode",
        "ttl_seconds",
        "scope_enforced",
        "injection_blocked",
        "block_reason",
        "memory_write",
        "tiandao_scope",
        "honghuang_subsystem",
        "tiandao_face",
        "contract_role",
        "overclaim_boundary",
        "consumer",
        "memory_scope",
        "memory_base_scope",
        "active_layers_used",
        "current_window_binding_applied",
        "current_window_binding_key",
        "current_window_binding_fields",
        "cross_window_read",
        "cross_window_read_allowed",
        "injection_boundary",
        "validation",
    ):
        value = package.get(key)
        if value not in ("", None, [], {}):
            compact[key] = value
    refs = package.get("source_refs") if isinstance(package.get("source_refs"), list) else []
    if refs:
        compact["source_refs"] = [
            {
                key: ref.get(key)
                for key in (
                    "ref_id",
                    "source_system",
                    "artifact_type",
                    "ref_path",
                    "artifact_id",
                    "captured_at",
                    "msg_ids",
                    "evidence_hash",
                    "raw_evidence_status",
                    "auth_required",
                    "auth_granted",
                )
                if isinstance(ref, dict) and ref.get(key) not in ("", None, [], {})
            }
            for ref in refs[:MAX_COMPACT_ITEMS]
        ]
    for key in ("permission_boundary", "capability_profile", "adapter_verdict"):
        value = package.get(key)
        if isinstance(value, dict):
            compact[key] = {
                nested_key: nested_value
                for nested_key, nested_value in value.items()
                if nested_value not in ("", None, [], {})
            }
    if include_raw_projection and isinstance(package.get("raw_projection"), dict):
        compact["raw_projection"] = package["raw_projection"]
    return compact


def compact_recall_payload(
    payload: Dict[str, Any],
    *,
    response_budget_mode: str = "compact",
    include_raw_excerpt: bool = False,
) -> Dict[str, Any]:
    """Project full recall payloads into compact or explicit-raw responses."""
    if not isinstance(payload, dict):
        return {}
    if response_budget_mode == "raw":
        full = dict(payload)
        items = full.get("items", []) if isinstance(full.get("items"), list) else []
        full["raw_excerpt_returned"] = any(
            bool(item.get("raw_excerpt"))
            for item in items
            if isinstance(item, dict)
        )
        full["response_budget"] = {
            "mode": "raw",
            "items_returned": len(items),
            "items_available": len(items),
            "raw_excerpt_returned": full["raw_excerpt_returned"],
            "omitted_large_fields": [],
        }
        return full

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    budget = "standard" if response_budget_mode == "standard" else "compact"
    compact: Dict[str, Any] = {}
    for key in (
        "ok",
        "consumer",
        "query",
        "source_system_filter",
        "source_system_filter_aliases",
        "source_collection_filter",
        "claude_collection_alias_applied",
        "claude_collection_alias_boundary",
        "requested_source_system",
        "inferred_source_system",
        "memory_scope",
        "memory_base_scope",
        "scope_missing",
        "recall_status",
        "window_binding_hint",
        "missing_scope_fields",
        "cross_window_read",
        "cross_window_read_allowed",
        "hermes_global_exception",
        "hermes_plain_recall_is_global_exception",
        "hermes_broad_context_workflow",
        "cross_window_reason",
        "canonical_window_id_filter",
        "project_id_filter",
        "project_root_filter",
        "workstream_id_filter",
        "task_id_filter",
        "current_window_binding_applied",
        "current_window_binding_key",
        "current_window_binding_fields",
        "active_layers_used",
        "agent_boundary",
        "injection_boundary",
        "tiandao_context_package_valid",
        "recall_performed",
        "fast_window_preflight",
        "fast_recall_path",
        "fast_window_index_status",
        "zhiyi_layer_skipped_for_fast_preflight",
        "matched_count",
        "source_refs_count",
        "raw_items_count",
        "catalog_index_used",
        "catalog_index_status",
        "catalog_index_items_count",
        "raw_recall_trajectory_contract",
        "raw_recall_trajectory_policy",
        "raw_recall_trajectory",
        "library_index_projection_contract",
        "library_index_projection_policy",
        "library_index_projection_used",
        "library_index_projection_refs_count",
        "library_index_projection_refs",
        "context_bundle_contract",
        "context_bundle_policy",
        "context_bundle_window",
        "context_bundle_items_count",
        "context_bundle_refs_count",
        "context_bundle_status_counts",
        "raw_fallback_used",
        "raw_fallback_status",
        "raw_fallback_scanned_files",
        "raw_fallback_scanned_bytes",
        "raw_fallback_scanned_lines",
        "raw_fallback_truncated",
        "raw_fallback_timed_out",
        "raw_evidence_status",
        "zhiyi_experience_used_as_raw",
        "consumer_receipt",
    ):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            compact[key] = value
    compact["raw_excerpt_returned"] = bool(include_raw_excerpt and any(
        bool(item.get("raw_excerpt"))
        for item in items
        if isinstance(item, dict)
    ))
    compact["items"] = [
        _compact_gateway_item(item, include_raw_excerpt=include_raw_excerpt)
        for item in items[:MAX_COMPACT_ITEMS]
    ]
    tiandao_pkg = _compact_tiandao_context_package(
        payload.get("tiandao_context_package"),
        include_raw_projection=budget == "standard" or include_raw_excerpt,
    )
    if tiandao_pkg:
        compact["tiandao_context_package"] = tiandao_pkg
    compact["response_budget"] = {
        "mode": f"raw_gateway_{budget}",
        "items_returned": min(len(items), MAX_COMPACT_ITEMS),
        "items_available": len(items),
        "raw_excerpt_returned": compact["raw_excerpt_returned"],
        "raw_excerpt_available": any(
            bool(item.get("raw_excerpt"))
            for item in items
            if isinstance(item, dict)
        ),
        "raw_excerpt_expand": "set response_budget=raw or include_raw_excerpt=true",
        "omitted_large_fields": [
            "zhixing_library",
            "hybrid_recall",
            "library_card",
            "typed_graph",
            "tiandao_context_package.matched_memories",
            "tiandao_context_package.raw_projection",
            "items.raw_excerpt",
        ],
    }
    if include_raw_excerpt:
        compact["response_budget"]["omitted_large_fields"] = [
            field for field in compact["response_budget"]["omitted_large_fields"]
            if field != "items.raw_excerpt"
        ]
    return compact
