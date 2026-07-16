"""Compatibility registry plus host-owned self-install receipts.

The read-only platform-guard core lives in platform_thin_adapter_core.py under
the Tiandao platform_guard workbench. This module keeps dashboard composition
and generic host capability declarations. Time Library never writes host config.
"""

from __future__ import annotations

try:
    from src.platform_thin_adapter_core import *
except Exception:  # pragma: no cover - direct script import fallback
    from platform_thin_adapter_core import *

try:
    from src.source_system_runtime_declarations import source_system_native_delivery_shape
except Exception:  # pragma: no cover - direct script import fallback
    from source_system_runtime_declarations import source_system_native_delivery_shape

HOST_SELF_INSTALL_CONTRACT = "time_library.host_self_install.v1"
HOST_SELF_INSTALL_REQUIRED_CAPABILITIES = (
    "mcp_capability",
    "skill_surface",
    "config_write_owner",
    "startup_catalog_policy",
)


def _public_discovery_dashboard(full: dict[str, Any]) -> dict[str, Any]:
    counts = full.get("counts") if isinstance(full.get("counts"), dict) else {}
    public_summary = full.get("public_summary") if isinstance(full.get("public_summary"), dict) else {}
    host_action_required = int(
        counts.get("host_self_install_required")
        or counts.get("auto_connect_ready")
        or counts.get("needs_authorization")
        or 0
    )
    items = []
    for source in full.get("items", []):
        if not isinstance(source, dict):
            continue
        item = _public_dashboard_item(source)
        if item.get("status") == AUTO_CONNECT_READY_STATUS:
            item["status"] = "host_self_install_required"
            item["auto_connect_ready"] = False
            item["safe_next_step"] = "ask_host_agent_to_install_then_self_report"
        items.append(item)
    return {
        "ok": bool(full.get("ok", True)),
        "contract": full.get("contract", DISCOVERY_DASHBOARD_CONTRACT),
        "view": "public",
        "generated_at": full.get("generated_at", ts()),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "name": "Time Library",
        "default_policy": "observe_compatibility_then_verify_host_self_install",
        "dashboard_goal": "show_local_ai_tools_and_generic_connection_state",
        "counts": {
            "total": int(counts.get("total") or 0),
            "detected": int(counts.get("detected") or 0),
            "ready_for_capability_check": int(counts.get("ready_for_capability_check") or 0),
            "host_self_install_required": host_action_required,
            "auto_connect_ready": 0,
            "other_local_tools": int(public_summary.get("other_local_tools") or 0),
            "recently_quiet_tools": int(public_summary.get("recently_quiet_tools") or 0),
        },
        "public_summary": {
            "local_ai_tools": int(counts.get("total") or 0),
            "detected_tools": int(counts.get("detected") or 0),
            "ready_for_safe_check": int(counts.get("ready_for_capability_check") or 0),
            "host_self_install_required": host_action_required,
            "auto_connect_ready": 0,
            "other_local_tools": int(public_summary.get("other_local_tools") or 0),
            "recently_quiet_tools": int(public_summary.get("recently_quiet_tools") or 0),
        },
        "items": items,
        "global_guarantees": {
            "auto_connect_supported_skill_mcp_surfaces": False,
            "time_library_platform_write_supported": False,
            "host_owns_platform_config_and_rollback": True,
            "host_self_install_receipt_required": True,
            "unknown_clients_admitted_by_generic_self_report": True,
            "conversation_import_mode": "verified_format_collectors",
            "capability_check_after_connect": True,
            "new_memory_layout": "computer_first",
            "legacy_memory_layout": "read_compatibility_only",
        },
    }


def _host_owned_dashboard_item(source: dict[str, Any]) -> dict[str, Any]:
    item = dict(source)
    if item.get("status") == AUTO_CONNECT_READY_STATUS:
        item["status"] = "host_self_install_required"
        item["safe_next_step"] = "ask_host_agent_to_install_then_self_report"
        item["auto_connect_ready"] = False
    return item

def build_platform_discovery_dashboard(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    include_generic: bool = True,
    public: bool = True,
) -> dict[str, Any]:
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    catalog = load_platform_catalog()
    package_inventory = build_package_manager_agent_inventory(home=resolved_home, env=resolved_env) if include_generic else {
        "contract": PACKAGE_MANAGER_INVENTORY_CONTRACT,
        "item_count": 0,
        "match_count": 0,
        "scan_mode": "skipped_for_fast_snapshot",
    }
    registry = build_thin_adapter_registry(
        runtime_profile,
        home=resolved_home,
        env=resolved_env,
        include_generic=include_generic,
    )
    known_items = [
        _host_owned_dashboard_item(_dashboard_item_from_adapter(adapter))
        for adapter in registry.get("adapters", [])
    ]
    generic_items = [
        _host_owned_dashboard_item(_dashboard_item_from_generic_surface(surface))
        for surface in registry.get("generic_surface_discovery", {}).get("surfaces", [])
    ]
    order = {
        "ready_for_capability_check": 0,
        "host_self_install_required": 1,
        "parked_not_current_focus": 2,
        "not_detected": 3,
    }
    freshness_order = {
        "active_recent": 0,
        "warm": 1,
        "unknown": 2,
        "stale": 3,
        "dormant": 4,
    }
    items = sorted(
        known_items + generic_items,
        key=lambda item: (
            freshness_order.get(str(item.get("freshness") or "unknown"), 9),
            order.get(str(item.get("status")), 9),
            str(item.get("surface_type")),
            str(item.get("display_name")),
        ),
    )
    counts = {
        "total": len(items),
        "detected": sum(1 for item in items if item.get("detected")),
        "ready_for_capability_check": sum(1 for item in items if item.get("status") == "ready_for_capability_check"),
        "auto_connect_ready": sum(1 for item in items if item.get("status") == AUTO_CONNECT_READY_STATUS),
        "host_self_install_required": sum(1 for item in items if item.get("status") == "host_self_install_required"),
        "needs_authorization": 0,
        "generic_surfaces": sum(1 for item in items if item.get("surface_type") == "generic_local_ai_surface"),
        "catalog_entries": int(catalog.get("entry_count") or 0),
        "catalog_watchlist": int(catalog.get("github_watchlist_entry_count") or 0),
        "catalog_detected": sum(1 for item in items if item.get("catalog_driven") and item.get("detected")),
        "package_manager_matches": int(package_inventory.get("match_count") or 0),
        "parked_not_current_focus": sum(1 for item in items if item.get("status") == "parked_not_current_focus"),
        "verified_collectors_needed": sum(1 for item in items if item.get("chat_body_parser_requires_verified_collector")),
        "parser_gates_locked": sum(1 for item in items if item.get("chat_body_parser_requires_verified_collector")),
        "stale": sum(1 for item in items if item.get("freshness") == "stale"),
        "dormant": sum(1 for item in items if item.get("freshness") == "dormant"),
    }
    public_summary = {
        "local_ai_tools": counts["total"],
        "detected_tools": counts["detected"],
        "ready_for_safe_check": counts["ready_for_capability_check"],
        "auto_connect_ready": counts["auto_connect_ready"],
        "host_self_install_required": counts["host_self_install_required"],
        "other_local_tools": counts["generic_surfaces"],
        "recently_quiet_tools": counts["stale"] + counts["dormant"],
        "install_record_matches": counts["package_manager_matches"],
    }
    full_payload = {
        "ok": True,
        "contract": DISCOVERY_DASHBOARD_CONTRACT,
        "view": "internal",
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "name": "Time Library",
        "codename": "Time Library",
        "default_policy": "observe_compatibility_then_verify_host_self_install",
        "dashboard_goal": "show_local_ai_tools_and_generic_connection_state",
        "counts": counts,
        "public_summary": public_summary,
        "platform_catalog": {
            "contract": catalog.get("contract"),
            "catalog_version": catalog.get("catalog_version"),
            "watchlist_version": catalog.get("watchlist_version"),
            "entry_count": catalog.get("entry_count"),
            "curated_entry_count": catalog.get("curated_entry_count"),
            "github_watchlist_entry_count": catalog.get("github_watchlist_entry_count"),
        },
        "package_manager_inventory": {
            "contract": package_inventory.get("contract"),
            "item_count": package_inventory.get("item_count"),
            "match_count": package_inventory.get("match_count"),
        },
        "items": items,
        "global_guarantees": {
            "auto_connect_supported_skill_mcp_surfaces": False,
            "time_library_platform_write_supported": False,
            "host_owns_platform_config_and_rollback": True,
            "host_self_install_receipt_required": True,
            "unknown_clients_admitted_by_generic_self_report": True,
            "conversation_import_mode": "verified_format_collectors",
            "does_not_recall_real_memory": True,
            "skill_installation_is_not_body_read_consent": True,
            "capability_check_only_when_connectable": True,
            "raw_archive_layout_order": ["computer_name", "source_system", "native_artifact_format"],
            "raw_archive_primary_partition_key": "computer_name",
            "raw_archive_secondary_partition_key": "source_system",
            "raw_archive_effective_from_version": "2026.6.1",
            "raw_archive_new_install_default_layout": "computer_first",
            "raw_archive_legacy_layout_status": "read_compatibility_only",
            "raw_archive_legacy_layout_allowed_for_new_writes": False,
        },
        "links": {
            "thin_adapter_registry": "/api/v1/platforms/thin-adapter-registry",
            "platform_catalog": "/api/v1/platforms/catalog",
            "package_manager_inventory": "/api/v1/platforms/package-manager-inventory",
            "generic_local_ai_surfaces": "/api/v1/platforms/generic-local-ai-surfaces",
            "authorized_auto_connect_dry_run": "/api/v1/platforms/authorized-auto-connect/dry-run",
        },
    }
    if public:
        return _public_discovery_dashboard(full_payload)
    return full_payload


def _capability_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _startup_catalog_policy(value: Any) -> str:
    policy = str(value or "").strip().lower()
    return policy if policy in {"full", "deferred", "none"} else ""


def _mcp_url_for_capabilities(_capabilities: dict[str, Any]) -> str:
    return ""


def _mcp_path_for_capabilities(capabilities: dict[str, Any]) -> str:
    if _startup_catalog_policy(capabilities.get("startup_catalog_policy")) == "deferred":
        return f"{MEMCORE_MCP_PATH}?startup_catalog=deferred"
    return MEMCORE_MCP_PATH


def _declared_host_capabilities(
    adapter_draft: dict[str, Any] | None = None,
    supplied: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del adapter_draft
    provided = _capability_dict(supplied)
    skill_surface = provided.get("skill_surface")
    if not str(skill_surface or "").strip():
        skill_surface = "not_declared"
    return {
        "mcp_capability": provided.get("mcp_capability") is True,
        "skill_surface": str(skill_surface),
        "config_write_owner": str(provided.get("config_write_owner") or "host"),
        "startup_catalog_policy": _startup_catalog_policy(provided.get("startup_catalog_policy")) or "host_declared",
        "post_connect_proof": str(
            provided.get("post_connect_proof")
            or "capability_check_then_real_recall_then_delivery_challenge_ack"
        ),
    }


def _write_strategy_for_capabilities(capabilities: dict[str, Any]) -> str:
    if capabilities.get("mcp_capability"):
        return "host_self_configures_time_library_mcp"
    return "host_capability_declaration_required"


def _apply_endpoint_status_for_capabilities(capabilities: dict[str, Any]) -> str:
    return "host_self_install_receipt_only" if capabilities.get("mcp_capability") else "capability_declaration_required"


def _adapter_draft_for_plan(adapter: dict[str, Any]) -> dict[str, Any]:
    candidate = adapter.get("provisional_adapter_candidate")
    if isinstance(candidate, dict) and isinstance(candidate.get("adapter_draft"), dict):
        return candidate["adapter_draft"]
    system = str(adapter.get("system") or "")
    display_name = str(adapter.get("display_name") or system)
    config_paths = _existing_paths(adapter, "config")
    content_store_paths = _existing_paths(adapter, "content_store")
    workspace_paths = _existing_paths(adapter, "workspace")
    surface = {
        "system": system,
        "display_name": display_name,
        "source": "known_thin_adapter",
        "platform_family": adapter.get("platform_family", ""),
        "catalog_driven": bool(adapter.get("catalog_driven")),
        "config_paths": config_paths,
        "content_store_paths": content_store_paths,
        "workspace_paths": workspace_paths,
        "signals": adapter.get("signals", []),
        "mcp_config_detected": bool(adapter.get("mcp_config_detected")),
        "memcore_mcp_detected": bool(adapter.get("memcore_mcp_detected")),
        "intent_signal_detected": bool(adapter.get("intent_signal_detected")),
        "conversation_memory_boundary": adapter.get("conversation_memory_boundary") or _conversation_memory_boundary(
            system,
            [*content_store_paths, *workspace_paths],
        ),
    }
    result = {
        "likely_name": display_name,
        "category": _category_from_family(adapter.get("platform_family")),
        "supports_mcp_likely": bool(config_paths or _catalog_mcp_config_patterns(system) or system in _implemented_apply_systems()),
        "skill_surface_likely": bool(adapter.get("skill_signal_detected")),
        "storage_candidate": _storage_candidate_for_surface(surface),
        "confidence": 0.9 if adapter.get("detected") else 0.5,
        "reason": "known thin adapter plan",
    }
    connection = _candidate_connection_status(system, surface, result)
    native_delivery_shape = source_system_native_delivery_shape(system)
    return _build_adapter_draft(
        system=system,
        display_name=display_name,
        surface=surface,
        result=result,
        connection=connection,
        recognized_by="known_thin_adapter",
        recognition_mode="known_adapter",
        confidence=float(result["confidence"]),
        native_delivery_shape=native_delivery_shape,
    )


def _native_delivery_plan(adapter_draft: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any]:
    del adapter_draft
    return {
        "plan_source": "host_capability_declaration",
        "native_delivery_shape_hint": "host_declared",
        "install_once_aware": True,
        "already_running_probe": "front_door_discovery_health_or_install_marker",
        "config_write_owner": capabilities.get("config_write_owner", "host"),
        "skill_surface": capabilities.get("skill_surface", "not_declared"),
        "post_connect_proof": capabilities.get("post_connect_proof", ""),
        "hook_install_supported_now": False,
        "time_library_platform_write_supported": False,
    }


def _mcp_plan_from_adapter_draft(
    adapter_draft: dict[str, Any],
    *,
    capabilities: dict[str, Any],
    write_strategy: str,
    would_write: list[str],
) -> dict[str, Any]:
    mcp = adapter_draft.get("mcp") if isinstance(adapter_draft.get("mcp"), dict) else {}
    return {
        "plan_source": "adapter_draft" if adapter_draft else "legacy_plan",
        "supports_mcp_likely": bool(mcp.get("supports_mcp_likely")),
        "skill_surface_likely": bool(mcp.get("skill_surface_likely")),
        "auto_connect_supported_now": False,
        "apply_endpoint_status": _apply_endpoint_status_for_capabilities(capabilities),
        "next_step": "host_configures_own_mcp_then_returns_receipt",
        "write_strategy": write_strategy,
        "detected_config_paths": list(mcp.get("config_paths") or []),
        "candidate_config_patterns": list(mcp.get("candidate_config_patterns") or []),
        "would_write": would_write,
        "endpoint": _mcp_url_for_capabilities(capabilities),
        "endpoint_path": _mcp_path_for_capabilities(capabilities),
        "discovery_file": MEMCORE_MCP_DISCOVERY_FILE,
        "endpoint_resolution": "host_reads_discovery_file_then_uses_supported_transport",
        "startup_catalog_policy": capabilities.get("startup_catalog_policy", "host_declared"),
        "config_write_owner": capabilities.get("config_write_owner", "host"),
        "time_library_platform_write_supported": False,
        "capability_check_after_connect": True,
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
    }


def _collector_plan_from_adapter_draft(adapter_draft: dict[str, Any]) -> dict[str, Any]:
    collector = adapter_draft.get("collector") if isinstance(adapter_draft.get("collector"), dict) else {}
    collector_status = str(collector.get("collector_status") or "no_content_store_detected")
    return {
        "plan_source": "adapter_draft" if adapter_draft else "legacy_plan",
        "collector_status": collector_status,
        "collector_kind": collector.get("collector_kind", "verified_format_collector"),
        "required_before_real_recall": collector_status == "verified_collector_required",
        "parser_gate": collector.get("parser_gate", "verified_format_collector_required"),
        "native_artifact_format": collector.get("native_artifact_format", ""),
        "storage_candidate": collector.get("storage_candidate", ""),
        "content_store_paths": list(collector.get("content_store_paths") or []),
        "workspace_paths": list(collector.get("workspace_paths") or []),
        "complete_conversation_candidate": bool(collector.get("complete_conversation_candidate")),
        "assistant_replies_may_persist": collector.get("assistant_replies_may_persist", False),
        "assistant_reply_persistence": collector.get("assistant_reply_persistence", "unverified"),
        "content_read": False,
        "chat_body_included": False,
        "raw_excerpt_included": False,
    }


def _raw_archive_plan_from_adapter_draft(adapter_draft: dict[str, Any], system: str) -> dict[str, Any]:
    raw_archive = adapter_draft.get("raw_archive") if isinstance(adapter_draft.get("raw_archive"), dict) else {}
    return {
        "plan_source": "adapter_draft" if adapter_draft else "legacy_plan",
        "layout": raw_archive.get("layout", "computer_first"),
        "effective_from_version": raw_archive.get("effective_from_version", "2026.6.1"),
        "segment_order": list(raw_archive.get("segment_order") or ["computer_name", "source_system", "native_artifact_format"]),
        "source_system": raw_archive.get("source_system", system),
        "native_artifact_format": raw_archive.get("native_artifact_format", f"{_slug(system)}_native_store"),
        "preferred_template": raw_archive.get(
            "preferred_template",
            "memory/{computer_name}/{source_system}/{native_artifact_format}/{native_scope}/{session_id}.jsonl",
        ),
        "legacy_layout_allowed_for_new_writes": bool(raw_archive.get("legacy_layout_allowed_for_new_writes", False)),
    }


def _build_adapter_autoconnect_plan(
    adapter: dict[str, Any],
    *,
    home: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    system = str(adapter.get("system") or "")
    status = _plan_status(adapter)
    adapter_draft = _adapter_draft_for_plan(adapter)
    capabilities = _declared_host_capabilities(adapter_draft)
    write_strategy = _write_strategy_for_capabilities(capabilities)
    would_write: list[str] = []
    if status == AUTO_CONNECT_READY_STATUS:
        status = "host_self_install_required"
    mcp_plan = _mcp_plan_from_adapter_draft(
        adapter_draft,
        capabilities=capabilities,
        write_strategy=write_strategy,
        would_write=would_write,
    )
    collector_plan = _collector_plan_from_adapter_draft(adapter_draft)
    raw_archive_plan = _raw_archive_plan_from_adapter_draft(adapter_draft, system)
    native_delivery_plan = _native_delivery_plan(adapter_draft, capabilities)
    conversation_boundary = adapter_draft.get("conversation_memory_boundary") or adapter.get("conversation_memory_boundary") or _conversation_memory_boundary(system)
    return {
        "system": system,
        "display_name": adapter.get("display_name"),
        "support_level": adapter.get("support_level"),
        "plan_source": "adapter_draft",
        "adapter_draft_consumed": True,
        "status": status,
        "detected": bool(adapter.get("detected")),
        "connectable_now": bool(adapter.get("connectable_now")),
        "intent_signal_detected": bool(adapter.get("intent_signal_detected")),
        "software": adapter.get("software", {}),
        "activity": adapter.get("activity", {}),
        "freshness": (adapter.get("activity") or {}).get("freshness", "unknown"),
        "missing": _missing_for_adapter(adapter),
        "write_strategy": write_strategy,
        "would_write": would_write,
        "would_create_parent_dirs": [
            str(Path(path).parent)
            for path in would_write
            if not _safe_is_dir(Path(path).parent)
        ],
        "backup_required": bool(would_write),
        "backup_plan": "copy_each_existing_config_before_write" if would_write else "not_applicable",
        "receipt_required": True,
        "restart_required": False,
        "capability_check_after_connect": True,
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        "real_recall_after_connect": False,
        "mcp_plan": mcp_plan,
        "collector_plan": collector_plan,
        "raw_archive_plan": raw_archive_plan,
        "native_delivery_plan": native_delivery_plan,
        "next_actions": list(adapter_draft.get("next_actions") or []),
        "parser_gate": collector_plan.get("parser_gate") or adapter.get("content_gate"),
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": conversation_boundary,
        "provisional_adapter_candidate": adapter.get("provisional_adapter_candidate", {}),
        "adapter_draft": adapter_draft,
        "rollback_plan": "host_owns_platform_config_rollback",
        "apply_endpoint_status": _apply_endpoint_status_for_capabilities(capabilities),
        "host_capabilities": capabilities,
        "host_install_contract": HOST_SELF_INSTALL_CONTRACT,
        "host_self_install_required": status == "host_self_install_required",
        "time_library_platform_write_supported": False,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
    }


def build_authorized_auto_connect_dry_run(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    system: str | None = None,
    include_generic: bool = True,
) -> dict[str, Any]:
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    registry = build_thin_adapter_registry(
        runtime_profile,
        home=resolved_home,
        env=resolved_env,
        include_generic=include_generic,
    )
    adapters = registry.get("adapters", [])
    generic_surfaces = registry.get("generic_surface_discovery", {}).get("surfaces", [])
    if system:
        adapters = [item for item in adapters if item.get("system") == system]
        generic_surfaces = [item for item in generic_surfaces if item.get("system") == system]
        if not include_generic and not adapters and system not in _known_adapter_systems():
            generic = build_generic_local_ai_surfaces(home=resolved_home, env=resolved_env)
            generic_surfaces = [
                item for item in generic.get("surfaces", [])
                if item.get("system") == system
            ]
    plans = [
        _build_adapter_autoconnect_plan(adapter, home=resolved_home, env=resolved_env)
        for adapter in adapters
    ]
    for surface in generic_surfaces:
        adapter_like = {
            "system": surface.get("system"),
            "display_name": surface.get("display_name"),
            "support_level": "generic_surface_candidate",
            "detected": surface.get("detected"),
            "connectable_now": surface.get("connectable_now"),
            "intent_signal_detected": surface.get("intent_signal_detected"),
            "content_gate": "verified_format_collector_required",
            "conversation_memory_boundary": surface.get("conversation_memory_boundary") or _conversation_memory_boundary(
                str(surface.get("system") or ""),
                [
                    *list(surface.get("content_store_paths") or []),
                    *list(surface.get("workspace_paths") or []),
                ],
            ),
            "current_focus": True,
            "instances": [{"type": "config", "path": path} for path in surface.get("config_paths", [])],
            "software": surface.get("software", {}),
            "activity": surface.get("activity", {}),
            "provisional_adapter_candidate": surface.get("provisional_adapter_candidate", {}),
        }
        plans.append(_build_adapter_autoconnect_plan(adapter_like, home=resolved_home, env=resolved_env))
    return {
        "ok": bool(plans) or system is None,
        "contract": AUTOCONNECT_DRY_RUN_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "system_filter": system or "",
        "scan_mode": "full" if include_generic else "fast_known_adapters_only",
        "plan_count": len(plans),
        "plans": plans,
        "apply_endpoint_status": "host_self_install_receipt_only",
        "host_install_contract": HOST_SELF_INSTALL_CONTRACT,
        "required_host_capabilities": list(HOST_SELF_INSTALL_REQUIRED_CAPABILITIES),
        "implemented_apply_systems": [],
        "authorization_required_before_apply": ["host_install_performed", "host_install_receipt"],
        "conditional_authorization_required_before_apply": {},
        "global_guarantees": {
            "dry_run_only": True,
            "host_owns_platform_config_and_rollback": True,
            "time_library_records_host_receipt_only": True,
            "time_library_platform_write_supported": False,
            "conversation_import_mode": "verified_format_collectors",
            "real_recall_after_connect": False,
            "user_or_installer_approval_required_before_apply": True,
        },
    }


def _confirmation_enabled(body: dict[str, Any], name: str) -> bool:
    value = body.get(name)
    if value is True:
        return True
    confirmations = body.get("confirmations")
    if isinstance(confirmations, dict) and confirmations.get(name) is True:
        return True
    if isinstance(confirmations, list) and name in confirmations:
        return True
    return False


def build_authorized_auto_connect_apply_gate_dry_run(
    body: dict[str, Any] | None = None,
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    memcore_root: Path | None = None,
    include_generic: bool = False,
) -> dict[str, Any]:
    payload = body or {}
    system = str(payload.get("system") or payload.get("target_system") or "").strip() or None
    discovery = build_authorized_auto_connect_dry_run(
        runtime_profile,
        home=home,
        env=env,
        system=system,
        include_generic=include_generic,
    )
    plans = discovery.get("plans", [])
    planned = dict(plans[0]) if plans else {
        "system": system or "",
        "display_name": system or "",
        "status": "host_self_install_required",
        "plan_source": "host_capability_declaration",
        "would_write": [],
        "mcp_plan": {},
        "collector_plan": {},
        "raw_archive_plan": {},
        "native_delivery_plan": {},
    }
    supplied_capabilities = _capability_dict(payload.get("host_capabilities"))
    capabilities = _declared_host_capabilities(
        planned.get("adapter_draft") if isinstance(planned.get("adapter_draft"), dict) else {},
        supplied_capabilities,
    )
    missing_capabilities: list[str] = []
    if supplied_capabilities.get("mcp_capability") is not True:
        missing_capabilities.append("mcp_capability")
    if not str(supplied_capabilities.get("skill_surface") or "").strip():
        missing_capabilities.append("skill_surface")
    if str(supplied_capabilities.get("config_write_owner") or "").strip().lower() != "host":
        missing_capabilities.append("config_write_owner_host")
    if not _startup_catalog_policy(supplied_capabilities.get("startup_catalog_policy")):
        missing_capabilities.append("startup_catalog_policy")
    host_install_performed = payload.get("host_install_performed") is True
    host_install_receipt = str(payload.get("host_install_receipt") or "").strip()[:1000]
    connection_receipt_id = str(payload.get("connection_receipt_id") or "").strip()[:240]
    verified_connection_receipt: dict[str, Any] = {}
    if connection_receipt_id and system:
        try:
            try:
                from src.time_library_delivery_runtime import query_verified_host_connections
            except Exception:
                from time_library_delivery_runtime import query_verified_host_connections
            for candidate in query_verified_host_connections(memcore_root=memcore_root):
                if (
                    str(candidate.get("receipt_id") or "") == connection_receipt_id
                    and str(candidate.get("platform") or "") == _slug(system)
                ):
                    verified_connection_receipt = candidate
                    break
        except Exception:
            verified_connection_receipt = {}
    blocked_reasons: list[str] = []
    if not system:
        blocked_reasons.append("system_required")
    if missing_capabilities:
        blocked_reasons.append("host_capability_declaration_incomplete")
    if not host_install_performed:
        blocked_reasons.append("host_install_not_reported")
    if not host_install_receipt:
        blocked_reasons.append("host_install_receipt_missing")
    if not connection_receipt_id:
        blocked_reasons.append("verified_connection_receipt_id_missing")
    elif not verified_connection_receipt:
        blocked_reasons.append("verified_connection_receipt_not_found_or_identity_mismatch")
    ready = not blocked_reasons
    planned.update({
        "status": "host_self_install_recordable" if ready else "host_self_install_required",
        "write_strategy": _write_strategy_for_capabilities(capabilities),
        "would_write": [],
        "backup_required": False,
        "receipt_required": True,
        "restart_required": False,
        "rollback_plan": "host_owns_platform_config_rollback",
        "apply_endpoint_status": _apply_endpoint_status_for_capabilities(capabilities),
        "host_capabilities": capabilities,
        "host_install_contract": HOST_SELF_INSTALL_CONTRACT,
        "time_library_platform_write_supported": False,
    })
    mcp_plan = dict(planned.get("mcp_plan") or {})
    mcp_plan.update({
        "endpoint": _mcp_url_for_capabilities(capabilities),
        "endpoint_path": _mcp_path_for_capabilities(capabilities),
        "discovery_file": MEMCORE_MCP_DISCOVERY_FILE,
        "endpoint_resolution": "host_reads_discovery_file_then_uses_supported_transport",
        "startup_catalog_policy": capabilities.get("startup_catalog_policy"),
        "config_write_owner": "host",
        "write_strategy": _write_strategy_for_capabilities(capabilities),
        "would_write": [],
        "time_library_platform_write_supported": False,
    })
    planned["mcp_plan"] = mcp_plan
    receipt = {
        "receipt_type": "host_self_install_apply_gate",
        "contract": HOST_SELF_INSTALL_CONTRACT,
        "system": system or "",
        "plan_source": planned.get("plan_source", "host_capability_declaration"),
        "adapter_draft_consumed": bool(planned.get("adapter_draft_consumed")),
        "write_strategy": planned.get("write_strategy"),
        "would_write": [],
        "mcp_plan": planned.get("mcp_plan", {}),
        "collector_plan": planned.get("collector_plan", {}),
        "raw_archive_plan": planned.get("raw_archive_plan", {}),
        "next_actions": planned.get("next_actions", []),
        "adapter_draft_id": (planned.get("adapter_draft") or {}).get("draft_id", ""),
        "backup_plan": "host_owned",
        "rollback_plan": "host_owns_platform_config_rollback",
        "capability_check_payload": planned.get("capability_check_payload") or CAPABILITY_CHECK_PAYLOAD,
        "freshness": planned.get("freshness", "unknown"),
        "host_capabilities": capabilities,
        "host_install_performed": host_install_performed,
        "host_install_receipt": host_install_receipt,
        "connection_receipt_id": connection_receipt_id,
        "verified_connection_receipt": verified_connection_receipt,
        "stale_or_dormant_confirmation_required": False,
        "stale_or_dormant_notice": False,
        "real_recall_after_connect": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": planned.get("conversation_memory_boundary") or _conversation_memory_boundary(system or ""),
    }
    return {
        "ok": True,
        "contract": AUTOCONNECT_APPLY_GATE_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "system": system or "",
        "status": "ready_to_record_host_self_install" if ready else "blocked",
        "ready_for_auto_connect": False,
        "ready_to_record_host_self_install": ready,
        "ready_after_authorization": ready,
        "missing_confirmations": [],
        "missing_host_capabilities": missing_capabilities,
        "blocked_reasons": blocked_reasons,
        "plan": planned,
        "receipt_preview": receipt,
        "apply_endpoint_status": _apply_endpoint_status_for_capabilities(capabilities),
        "global_guarantees": {
            "host_owns_platform_config_and_rollback": True,
            "receipt_after_host_install": True,
            "time_library_platform_write_supported": False,
            "conversation_import_mode": "verified_format_collectors",
            "real_recall_after_connect": False,
            "consumer_connection_requires_native_parser": False,
        },
    }


def _platform_apply_receipts_dir(memcore_root: Path | None) -> Path:
    root = memcore_root or Path.cwd()
    return root / "output" / "platform_auto_connect" / "receipts"


def _persist_platform_apply_receipt(receipt: dict[str, Any], *, memcore_root: Path | None) -> str:
    receipts_dir = _platform_apply_receipts_dir(memcore_root)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipts_dir.chmod(0o700)
    safe_system = _slug(str(receipt.get("system") or "unknown"))
    receipt_id = str(receipt.get("receipt_id") or f"{_stamp()}-{safe_system}")
    receipt_path = receipts_dir / f"{receipt_id}.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt_path.chmod(0o600)
    latest_path = receipts_dir / "latest.json"
    latest_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest_path.chmod(0o600)
    return str(receipt_path)


def apply_authorized_auto_connect(
    body: dict[str, Any] | None = None,
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    memcore_root: Path | None = None,
) -> dict[str, Any]:
    """Record a host-owned installation without writing host configuration."""
    payload = body or {}
    system = str(payload.get("system") or payload.get("target_system") or "").strip()
    gate = build_authorized_auto_connect_apply_gate_dry_run(
        payload,
        runtime_profile,
        home=home,
        env=env,
        memcore_root=memcore_root,
        include_generic=bool(payload.get("include_generic") or payload.get("scan") in {"full", "deep"}),
    )
    if not system or not gate.get("ready_to_record_host_self_install"):
        blocked = list(gate.get("blocked_reasons") or [])
        return {
            **gate,
            "ok": False,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "host_install_contract": HOST_SELF_INSTALL_CONTRACT,
            "read_only": False,
            "dry_run": False,
            "status": "blocked",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "error": blocked[0] if blocked else "host_self_install_gate_blocked",
        }

    planned = gate.get("plan") if isinstance(gate.get("plan"), dict) else {}
    capabilities = _capability_dict(planned.get("host_capabilities"))
    endpoint = _mcp_url_for_capabilities(capabilities)
    host_receipt = str(payload.get("host_install_receipt") or "").strip()[:1000]
    connection_receipt_id = str(payload.get("connection_receipt_id") or "").strip()[:240]
    receipt = {
        "receipt_id": f"{_stamp()}-{_slug(system)}",
        "receipt_type": "host_self_install_record",
        "contract": HOST_SELF_INSTALL_CONTRACT,
        "recorded_at": ts(),
        "system": system,
        "display_name": planned.get("display_name") or system,
        "status": "host_self_install_recorded",
        "plan_source": "host_capability_declaration",
        "host_capabilities": capabilities,
        "host_install_performed": True,
        "host_install_receipt": host_receipt,
        "connection_receipt_id": connection_receipt_id,
        "connection_proof": "initialize_bound_self_report_plus_real_recall",
        "platform_config_owner": "host",
        "platform_config_registered_by": "host",
        "time_library_platform_write_supported": False,
        "mcp_plan": {
            "server_name": MEMCORE_MCP_SERVER_NAME,
            "endpoint": endpoint,
            "endpoint_path": _mcp_path_for_capabilities(capabilities),
            "discovery_file": MEMCORE_MCP_DISCOVERY_FILE,
            "endpoint_resolution": "host_reads_discovery_file_then_uses_supported_transport",
            "startup_catalog_policy": capabilities.get("startup_catalog_policy"),
            "config_write_owner": "host",
            "write_strategy": "host_self_configures_time_library_mcp",
            "post_connect_proof": capabilities.get("post_connect_proof"),
        },
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        "capability_check_after_connect": True,
        "real_recall_after_connect": False,
        "delivery_challenge_after_positive_recall": True,
        "consumer_connection_requires_native_parser": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "read_chat_bodies": False,
        "receipt_write_performed": True,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "rollback_plan": "host_owns_platform_config_rollback",
        "time_rule_decision": {
            "status": "attached",
            "rules": [
                "platforms_are_inlets_not_origin",
                "events_remain_orderable",
                "unknown_must_remain_visible",
                "source_refs_required_not_replacement",
                "raw_is_highest_authority",
            ],
        },
    }
    receipt_path = _persist_platform_apply_receipt(receipt, memcore_root=memcore_root)
    return {
        "ok": True,
        "contract": AUTOCONNECT_APPLY_CONTRACT,
        "host_install_contract": HOST_SELF_INSTALL_CONTRACT,
        "generated_at": ts(),
        "read_only": False,
        "dry_run": False,
        "system": system,
        "status": "host_self_install_recorded",
        "write_performed": True,
        "receipt_write_performed": True,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "host_install_performed": True,
        "host_capabilities": capabilities,
        "host_install_receipt": host_receipt,
        "connection_receipt_id": connection_receipt_id,
        "receipt_path": receipt_path,
        "receipt": receipt,
        "target_path": "",
        "backup_path": "",
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        "mcp_plan": receipt["mcp_plan"],
        "collector_plan": planned.get("collector_plan", {}),
        "raw_archive_plan": planned.get("raw_archive_plan", {}),
        "native_delivery_plan": planned.get("native_delivery_plan", {}),
        "consumer_connection_requires_native_parser": False,
        "real_recall_after_connect": False,
    }
