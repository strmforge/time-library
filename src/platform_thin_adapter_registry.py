"""Thin-adapter registry orchestration and authorized apply paths.

The read-only platform-guard core lives in platform_thin_adapter_core.py under
the Tiandao platform_guard workbench. This module keeps dashboard composition
and explicitly authorized platform-config writes.
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

try:
    from tools.install_claude_code_preflight_hook import install_hook as install_claude_code_preflight_hook
except Exception:  # pragma: no cover - source-only import fallback
    install_claude_code_preflight_hook = None

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
        _dashboard_item_from_adapter(adapter)
        for adapter in registry.get("adapters", [])
    ]
    generic_items = [
        _dashboard_item_from_generic_surface(surface)
        for surface in registry.get("generic_surface_discovery", {}).get("surfaces", [])
    ]
    order = {
        "ready_for_capability_check": 0,
        AUTO_CONNECT_READY_STATUS: 1,
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
        "needs_authorization": sum(1 for item in items if item.get("status") == AUTO_CONNECT_READY_STATUS),
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
        "codename": "忆凡尘",
        "default_policy": "auto_discover_and_auto_connect_supported_surfaces",
        "dashboard_goal": "show_local_ai_tools_with_auto_connect_status",
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
            "auto_connect_supported_skill_mcp_surfaces": True,
            "backup_and_receipt_on_config_write": True,
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


def _write_strategy_for_system(system: str) -> str:
    if system == "claude_desktop":
        return "register_local_stdio_mcp_bridge"
    if system == "codex":
        return "use_codex_mcp_add_stdio_bridge"
    if system == "claude_code_cli":
        return "use_claude_mcp_add_or_update_mcp_json"
    if system == "kiro":
        return "register_generic_json_mcp_server"
    if system in {"codex", "cursor", "continue", "roo_code", "cline"}:
        return "register_loopback_mcp_server"
    if _catalog_json_mcp_apply_supported(system):
        return "register_catalog_json_mcp_server"
    if system in {"openclaw", "hermes"}:
        return "use_installer_default_connector"
    return "manual_review_required"


def _apply_endpoint_status_for_system(system: str) -> str:
    if system == "codex":
        return "implemented_for_codex_cli_mcp_bridge"
    return "implemented_for_json_mcp_surfaces" if system in _implemented_apply_systems() else "not_implemented"


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


def _native_delivery_plan(system: str, adapter_draft: dict[str, Any], *, home: Path) -> dict[str, Any]:
    details = adapter_draft.get("native_delivery") if isinstance(adapter_draft.get("native_delivery"), dict) else {}
    if system == "claude_code_cli":
        hook_script = (_repo_root() / "tools" / "claude_code_preflight_hook.py").resolve(strict=False)
        return {
            "plan_source": "adapter_draft" if adapter_draft else "legacy_plan",
            "native_delivery_shape": details.get("shape") or "user_prompt_submit_hook_and_mcp",
            "install_once_aware": True,
            "already_running_probe": "http_9851_health_or_install_marker",
            "delivery_surface": "UserPromptSubmit",
            "hook_install_supported_now": True,
            "hook_settings_targets": [
                str(home / ".claude" / "settings.json"),
                str(home / ".claude" / "settings.local.json"),
            ],
            "hook_script": str(hook_script),
            "hook_soft_fail_required": True,
        }
    return {
        "plan_source": "adapter_draft" if adapter_draft else "legacy_plan",
        "native_delivery_shape": details.get("shape") or source_system_native_delivery_shape(system),
        "install_once_aware": True,
        "already_running_probe": "http_9851_health_or_install_marker",
        "hook_install_supported_now": False,
    }


def _mcp_plan_from_adapter_draft(
    adapter_draft: dict[str, Any],
    *,
    write_strategy: str,
    would_write: list[str],
) -> dict[str, Any]:
    mcp = adapter_draft.get("mcp") if isinstance(adapter_draft.get("mcp"), dict) else {}
    return {
        "plan_source": "adapter_draft" if adapter_draft else "legacy_plan",
        "supports_mcp_likely": bool(mcp.get("supports_mcp_likely")),
        "skill_surface_likely": bool(mcp.get("skill_surface_likely")),
        "auto_connect_supported_now": bool(mcp.get("auto_connect_supported_now")),
        "apply_endpoint_status": mcp.get("apply_endpoint_status", ""),
        "next_step": mcp.get("next_step", ""),
        "write_strategy": write_strategy,
        "detected_config_paths": list(mcp.get("config_paths") or []),
        "candidate_config_patterns": list(mcp.get("candidate_config_patterns") or []),
        "would_write": would_write,
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
    would_write: list[str] = []
    if status == AUTO_CONNECT_READY_STATUS:
        would_write = _expanded_autoconnect_targets(system, adapter=adapter, home=home, env=env)
    restart_required = system in {"codex", "claude_desktop", "cursor", "continue", "roo_code", "cline"} or _catalog_json_mcp_apply_supported(system)
    adapter_draft = _adapter_draft_for_plan(adapter)
    write_strategy = _write_strategy_for_system(system)
    mcp_plan = _mcp_plan_from_adapter_draft(
        adapter_draft,
        write_strategy=write_strategy,
        would_write=would_write,
    )
    collector_plan = _collector_plan_from_adapter_draft(adapter_draft)
    raw_archive_plan = _raw_archive_plan_from_adapter_draft(adapter_draft, system)
    native_delivery_plan = _native_delivery_plan(system, adapter_draft, home=home)
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
        "receipt_required": bool(would_write),
        "restart_required": restart_required if would_write else False,
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
        "rollback_plan": "restore_backup_file_and_remove_added_mcp_server" if would_write else "not_applicable",
        "apply_endpoint_status": _apply_endpoint_status_for_system(system),
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
    }


def _resolve_claude_code_hook_settings_path(target_path: Path, home: Path) -> Path:
    text = str(target_path)
    if text.endswith(".claude.json"):
        return home / ".claude" / "settings.json"
    return home / ".claude" / "settings.json"


def _apply_claude_code_native_hook(
    *,
    target_path: Path,
    home: Path,
    env: dict[str, str],
    memcore_root: Path | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if install_claude_code_preflight_hook is None:
        raise RuntimeError("claude_code_preflight_hook_installer_not_importable")
    repo_root = _repo_root()
    preferred_hook_script = Path(
        str(
            payload.get("hook_script")
            or (memcore_root or repo_root) / "tools" / "claude_code_preflight_hook.py"
        )
    ).expanduser().resolve(strict=False)
    repo_hook_script = (repo_root / "tools" / "claude_code_preflight_hook.py").resolve(strict=False)
    hook_script = preferred_hook_script if preferred_hook_script.exists() else repo_hook_script
    hook_script_source = "preferred_path" if preferred_hook_script.exists() else "repo_fallback"
    settings_path = _resolve_claude_code_hook_settings_path(target_path, home)
    python_executable = _codex_python_executable(payload, env)
    install_result = install_claude_code_preflight_hook(
        settings_path,
        hook_script,
        python_executable=python_executable,
        endpoint=str(payload.get("preflight_endpoint") or "http://127.0.0.1:9851/api/v1/raw/query"),
        timeout=float(payload.get("preflight_timeout") or 0.75),
        max_context_chars=int(payload.get("preflight_max_context_chars") or 5000),
    )
    if not install_result.get("ok"):
        raise RuntimeError(f"claude_code_preflight_hook_install_failed:{install_result.get('reason')}")
    return {
        "settings_path": str(settings_path),
        "event": install_result.get("event", "UserPromptSubmit"),
        "hook_name": install_result.get("hook_name", "time-library-preflight"),
        "hook_script": str(hook_script),
        "hook_script_source": hook_script_source,
        "endpoint": install_result.get("endpoint") or "http://127.0.0.1:9851/api/v1/raw/query",
        "python_executable": install_result.get("python_executable", python_executable),
        "reason": install_result.get("reason", "installed"),
        "installed": bool(install_result.get("installed", False)),
        "soft_fail_required": True,
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
        "apply_endpoint_status": "implemented_for_json_mcp_surfaces",
        "implemented_apply_systems": _implemented_apply_systems(),
        "authorization_required_before_apply": list(APPLY_GATE_CONFIRMATIONS),
        "conditional_authorization_required_before_apply": {
            "confirm_connect_stale_or_dormant_platform": "required when a target platform is stale or dormant and a config write would occur",
        },
        "global_guarantees": {
            "dry_run_only": True,
            "backup_and_receipt_on_apply": True,
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
    include_generic: bool = False,
) -> dict[str, Any]:
    payload = body or {}
    system = str(payload.get("system") or payload.get("target_system") or "").strip() or None
    plan = build_authorized_auto_connect_dry_run(
        runtime_profile,
        home=home,
        env=env,
        system=system,
        include_generic=include_generic,
    )
    plans = plan.get("plans", [])
    installer_approved = bool(
        payload.get("installer_approved")
        or payload.get("user_approved")
        or payload.get("user_requested_auto_connect")
    )
    missing_confirmations = [
        name for name in APPLY_GATE_CONFIRMATIONS
        if not installer_approved and not _confirmation_enabled(payload, name)
    ]
    blocked_reasons: list[str] = []
    if not system:
        blocked_reasons.append("system_required")
    if not plans:
        blocked_reasons.append("no_connect_plan_found")
    planned = plans[0] if plans else {}
    stale_write_notice = (
        planned.get("freshness") in STALE_OR_DORMANT_FRESHNESS
        and bool(planned.get("would_write"))
        and planned.get("status") == AUTO_CONNECT_READY_STATUS
    )
    stale_confirmation_required = bool(
        stale_write_notice
        and not installer_approved
        and not _confirmation_enabled(payload, STALE_PLATFORM_CONFIRMATION)
    )
    if stale_confirmation_required:
        missing_confirmations.append(STALE_PLATFORM_CONFIRMATION)
    if planned.get("status") == "not_detected":
        blocked_reasons.append("platform_not_detected")
    if planned.get("status") == "parked_not_current_focus":
        blocked_reasons.append("platform_not_current_focus")
    if planned.get("status") == "ready_for_capability_check":
        blocked_reasons.append("already_connectable")
    if planned and not planned.get("would_write"):
        blocked_reasons.append("no_platform_config_target")
    if missing_confirmations:
        blocked_reasons.append("missing_authorization_confirmations")
    ready = not blocked_reasons
    receipt = {
        "receipt_type": "authorized_auto_connect_apply_gate",
        "system": system or "",
        "plan_source": planned.get("plan_source", "adapter_draft" if planned.get("adapter_draft") else "legacy_plan"),
        "adapter_draft_consumed": bool(planned.get("adapter_draft_consumed")),
        "write_strategy": planned.get("write_strategy"),
        "would_write": planned.get("would_write", []),
        "mcp_plan": planned.get("mcp_plan", {}),
        "collector_plan": planned.get("collector_plan", {}),
        "raw_archive_plan": planned.get("raw_archive_plan", {}),
        "next_actions": planned.get("next_actions", []),
        "adapter_draft_id": (planned.get("adapter_draft") or {}).get("draft_id", ""),
        "backup_plan": planned.get("backup_plan"),
        "rollback_plan": planned.get("rollback_plan"),
        "capability_check_payload": planned.get("capability_check_payload") or CAPABILITY_CHECK_PAYLOAD,
        "freshness": planned.get("freshness", "unknown"),
        "stale_or_dormant_confirmation_required": bool(stale_confirmation_required),
        "stale_or_dormant_notice": bool(stale_write_notice),
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
        "status": "ready_for_auto_connect" if ready else "blocked",
        "ready_for_auto_connect": ready,
        "ready_after_authorization": ready,
        "missing_confirmations": missing_confirmations,
        "blocked_reasons": blocked_reasons,
        "plan": planned,
        "receipt_preview": receipt,
        "apply_endpoint_status": _apply_endpoint_status_for_system(system or ""),
        "global_guarantees": {
            "backup_before_write": True,
            "receipt_after_write": True,
            "conversation_import_mode": "verified_format_collectors",
            "real_recall_after_connect": False,
            "adapter_draft_consumed": True,
        },
    }


def _platform_apply_receipts_dir(memcore_root: Path | None) -> Path:
    root = memcore_root or Path.cwd()
    return root / "output" / "platform_auto_connect" / "receipts"


def _backup_platform_config(path: Path, *, memcore_root: Path | None, system: str) -> str:
    backup_dir = (memcore_root or Path.cwd()) / "backups" / "platform_auto_connect" / system
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.name}.{_stamp()}.bak"
    if _safe_is_file(path):
        shutil.copy2(path, backup_path)
    else:
        backup_path.write_text("", encoding="utf-8")
    return str(backup_path)


def _write_json_object(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _mcp_server_section_key(config: dict[str, Any], system: str = "") -> str:
    for key in ("mcpServers", "mcp_servers", "servers"):
        if isinstance(config.get(key), dict):
            return key
    for key in _catalog_config_keys(system):
        return key
    return "mcpServers"


def _apply_json_mcp_server(target_path: Path, *, system: str = "") -> dict[str, Any]:
    config = _load_json_object(target_path)
    section_key = _mcp_server_section_key(config, system)
    servers = config.get(section_key)
    if not isinstance(servers, dict):
        servers = {}
        config[section_key] = servers
    before = servers.get(MEMCORE_MCP_SERVER_NAME)
    desired = {"type": "http", "url": MEMCORE_MCP_HTTP_URL}
    already_configured = before == desired
    servers[MEMCORE_MCP_SERVER_NAME] = desired
    _write_json_object(target_path, config)
    return {
        "target_path": str(target_path),
        "section_key": section_key,
        "server_name": MEMCORE_MCP_SERVER_NAME,
        "server_url": MEMCORE_MCP_HTTP_URL,
        "already_configured": already_configured,
    }


def _resolve_codex_cli(
    *,
    home: Path,
    env: dict[str, str],
    software: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    cli = software.get("cli") if isinstance(software, dict) and isinstance(software.get("cli"), dict) else {}
    configured = str(cli.get("path") or "").strip()
    if configured:
        return configured, str(cli.get("source") or "detected_cli"), {}
    executable = shutil.which("codex", path=env.get("PATH"))
    if executable:
        return executable, "path", {}
    executable, native_host = _codex_cli_from_native_hosts(home, env)
    if executable:
        return executable, "codex_chrome_native_host", native_host
    return "", "", {}


def _resolve_codex_bridge_path(memcore_root: Path | None) -> Path:
    candidates: list[Path] = []
    if memcore_root is not None:
        candidates.append(memcore_root / "tools" / "codex_mcp_bridge.py")
    candidates.append(_repo_root() / "tools" / "codex_mcp_bridge.py")
    for candidate in candidates:
        if _safe_is_file(candidate):
            return candidate
    return candidates[0]


def _codex_python_executable(payload: dict[str, Any], env: dict[str, str]) -> str:
    for key in ("python_executable", "python", "MEMCORE_PYTHON", "PYTHON"):
        value = payload.get(key) if key in payload else env.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return sys.executable


def _apply_codex_mcp_server(
    target_path: Path,
    *,
    home: Path,
    env: dict[str, str],
    memcore_root: Path | None,
    planned: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    software = planned.get("software") if isinstance(planned.get("software"), dict) else {}
    codex_cli, codex_cli_source, native_host = _resolve_codex_cli(
        home=home,
        env=env,
        software=software,
    )
    if not codex_cli:
        raise RuntimeError("codex_cli_not_found")
    bridge = _resolve_codex_bridge_path(memcore_root)
    if not _safe_is_file(bridge):
        raise RuntimeError(f"codex_mcp_bridge_not_found:{bridge}")
    root = memcore_root or _repo_root()
    registry_path = Path(
        str(
            payload.get("window_binding_registry")
            or env.get("MEMCORE_WINDOW_BINDING_REGISTRY")
            or (root / "config" / "window_binding_registry.json")
        )
    ).expanduser()
    python_executable = _codex_python_executable(payload, env)
    already_configured = _config_probe(target_path).get("memcore_mcp_detected") if _safe_is_file(target_path) else False
    bridge_env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "MEMCORE_ROOT": str(root),
        "MEMCORE_WINDOW_BINDING_REGISTRY": str(registry_path),
    }
    run_env = dict(os.environ)
    run_env.update(env)
    run_env.update(bridge_env)
    remove_cmd = [codex_cli, "mcp", "remove", MEMCORE_MCP_SERVER_NAME]
    add_args = [
        "mcp",
        "add",
        MEMCORE_MCP_SERVER_NAME,
        "--env",
        "PYTHONIOENCODING=utf-8",
        "--env",
        "PYTHONUTF8=1",
        "--env",
        f"MEMCORE_ROOT={root}",
        "--env",
        f"MEMCORE_WINDOW_BINDING_REGISTRY={registry_path}",
        "--",
        python_executable,
        str(bridge),
        "--endpoint",
        MEMCORE_MCP_HTTP_URL,
        "--timeout",
        "30",
        "--window-binding-registry",
        str(registry_path),
        "--binding-key",
        "codex",
    ]
    add_cmd = [codex_cli, *add_args]
    remove_result = subprocess.run(
        remove_cmd,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env=run_env,
    )
    add_result = subprocess.run(
        add_cmd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=run_env,
    )
    if add_result.returncode != 0:
        detail = (add_result.stderr or add_result.stdout or "").strip()
        raise RuntimeError(f"codex_mcp_add_failed:{add_result.returncode}:{detail[:500]}")
    return {
        "target_path": str(target_path),
        "server_name": MEMCORE_MCP_SERVER_NAME,
        "type": "stdio_bridge",
        "command": codex_cli,
        "args": add_args,
        "env": bridge_env,
        "python": python_executable,
        "bridge_path": str(bridge),
        "endpoint": MEMCORE_MCP_HTTP_URL,
        "window_binding_registry": str(registry_path),
        "binding_key": "codex",
        "codex_cli_source": codex_cli_source,
        "native_host": native_host,
        "already_configured": bool(already_configured),
        "remove_returncode": remove_result.returncode,
        "add_returncode": add_result.returncode,
        "config_write_mode": "codex_cli_mcp_add",
    }


def _persist_platform_apply_receipt(receipt: dict[str, Any], *, memcore_root: Path | None) -> str:
    receipts_dir = _platform_apply_receipts_dir(memcore_root)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    safe_system = _slug(str(receipt.get("system") or "unknown"))
    receipt_id = str(receipt.get("receipt_id") or f"{_stamp()}-{safe_system}")
    receipt_path = receipts_dir / f"{receipt_id}.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest_path = receipts_dir / "latest.json"
    latest_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(receipt_path)


def _mcp_target_paths_for_system(system: str, home: Path | None, env: dict[str, str] | None) -> list[Path]:
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    targets: list[Path] = []
    roots = _generic_scan_roots(resolved_home, resolved_env)
    patterns = tuple(dict.fromkeys((
        *AUTOCONNECT_TARGET_PATTERNS.get(system, ()),
        *_catalog_mcp_config_patterns(system),
    )))
    for pattern in patterns:
        path = _expand_path(pattern, resolved_home, resolved_env)
        expanded_paths = _expanded_catalog_pattern_paths(pattern, home=resolved_home, env=resolved_env, roots=roots)
        for candidate in ([path] if path is not None else []) + expanded_paths:
            if "*" not in str(candidate):
                targets.append(candidate)
    if system not in AUTOCONNECT_TARGET_PATTERNS:
        generic = build_generic_local_ai_surfaces(home=resolved_home, env=resolved_env)
        for surface in generic.get("surfaces", []):
            if surface.get("system") != system:
                continue
            for path in surface.get("config_paths", []):
                targets.append(Path(str(path)))
    unique: list[Path] = []
    seen = set()
    for path in targets:
        text = str(path)
        if text not in seen:
            unique.append(path)
            seen.add(text)
    return unique


def _connected_mcp_target(system: str, home: Path | None, env: dict[str, str] | None) -> Path | None:
    for path in _mcp_target_paths_for_system(system, home, env):
        if not _safe_is_file(path):
            continue
        probe = _config_probe(path)
        if probe.get("memcore_mcp_detected"):
            return path
    return None


def apply_authorized_auto_connect(
    body: dict[str, Any] | None = None,
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    memcore_root: Path | None = None,
) -> dict[str, Any]:
    payload = body or {}
    system = str(payload.get("system") or payload.get("target_system") or "").strip()
    gate = build_authorized_auto_connect_apply_gate_dry_run(
        payload,
        runtime_profile,
        home=home,
        env=env,
        include_generic=bool(payload.get("include_generic") or payload.get("scan") in {"full", "deep"}),
    )
    if not system:
        return {
            **gate,
            "ok": False,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "read_only": False,
            "dry_run": False,
            "status": "blocked",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "error": "system_required",
        }
    if system not in _implemented_apply_systems():
        return {
            **gate,
            "ok": False,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "read_only": False,
            "dry_run": False,
            "status": "blocked",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "error": "apply_not_implemented_for_system",
            "implemented_apply_systems": _implemented_apply_systems(),
        }
    planned = gate.get("plan") if isinstance(gate.get("plan"), dict) else {}
    if "already_connectable" in gate.get("blocked_reasons", []):
        target_path = _connected_mcp_target(system, home, env)
        receipt = {
            "receipt_id": f"{_stamp()}-{system}-already-connected",
            "receipt_type": "authorized_auto_connect_apply",
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "recorded_at": ts(),
            "system": system,
            "display_name": (gate.get("plan") or {}).get("display_name") or system,
            "status": "already_connected",
            "plan_source": planned.get("plan_source", "adapter_draft" if planned.get("adapter_draft") else "legacy_plan"),
            "adapter_draft_consumed": bool(planned.get("adapter_draft_consumed")),
            "adapter_draft_id": (planned.get("adapter_draft") or {}).get("draft_id", ""),
            "mcp_plan": planned.get("mcp_plan", {}),
            "collector_plan": planned.get("collector_plan", {}),
            "raw_archive_plan": planned.get("raw_archive_plan", {}),
            "next_actions": planned.get("next_actions", []),
            "target_path": str(target_path) if target_path else "",
            "backup_path": "",
            "rollback_plan": "not_applicable_existing_connection_preserved",
            "applied_mcp_server": {
                "name": MEMCORE_MCP_SERVER_NAME,
                "type": "stdio_bridge" if system == "codex" else "http",
                "url": "" if system == "codex" else MEMCORE_MCP_HTTP_URL,
                "endpoint": MEMCORE_MCP_HTTP_URL if system == "codex" else "",
                "already_configured": True,
            },
            "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
            "capability_check_after_connect": True,
            "real_recall_after_connect": False,
            "chat_body_parser_requires_verified_collector": True,
            "chat_body_parser_requires_separate_authorization": True,
            "conversation_memory_boundary": (gate.get("plan") or {}).get("conversation_memory_boundary") or _conversation_memory_boundary(system),
            "read_chat_bodies": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
        }
        receipt_path = _persist_platform_apply_receipt(receipt, memcore_root=memcore_root)
        return {
            "ok": True,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "generated_at": ts(),
            "read_only": False,
            "dry_run": False,
            "system": system,
            "status": "already_connected",
            "write_performed": True,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "chat_body_parser_requires_verified_collector": True,
            "chat_body_parser_requires_separate_authorization": True,
            "real_recall_after_connect": False,
            "target_path": str(target_path) if target_path else "",
            "backup_path": "",
            "receipt_path": receipt_path,
            "receipt": receipt,
            "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
            "mcp_plan": receipt["mcp_plan"],
            "collector_plan": receipt["collector_plan"],
            "raw_archive_plan": receipt["raw_archive_plan"],
        }
    if not gate.get("ready_for_auto_connect"):
        return {
            **gate,
            "ok": False,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "read_only": False,
            "dry_run": False,
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "error": "apply_gate_blocked",
        }

    targets = [Path(path) for path in planned.get("would_write", [])]
    if system == "codex":
        target_path = next((path for path in targets if path.name.lower() == "config.toml"), None)
    elif system == "claude_code_cli":
        target_path = next((path for path in targets if path.name == ".claude.json"), None)
    else:
        target_path = next(
            (path for path in targets if path.suffix.lower() == ".json" or "mcp" in path.name.lower()),
            None,
        )
    if target_path is None and targets:
        target_path = targets[0]
    if target_path is None:
        return {
            **gate,
            "ok": False,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "read_only": False,
            "dry_run": False,
            "status": "blocked",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "error": "codex_mcp_config_not_planned" if system == "codex" else "json_mcp_config_not_planned",
        }

    backup_path = _backup_platform_config(target_path, memcore_root=memcore_root, system=system)
    native_delivery_result = {}
    if system == "codex":
        applied = _apply_codex_mcp_server(
            target_path,
            home=home or Path.home(),
            env=_effective_env(home or Path.home(), env),
            memcore_root=memcore_root,
            planned=planned,
            payload=payload,
        )
    else:
        applied = _apply_json_mcp_server(target_path, system=system)
        if system == "claude_code_cli":
            native_delivery_result = _apply_claude_code_native_hook(
                target_path=target_path,
                home=home or Path.home(),
                env=_effective_env(home or Path.home(), env),
                memcore_root=memcore_root,
                payload=payload,
            )
    receipt = {
        "receipt_id": f"{_stamp()}-{system}",
        "receipt_type": "authorized_auto_connect_apply",
        "contract": AUTOCONNECT_APPLY_CONTRACT,
        "recorded_at": ts(),
        "system": system,
        "display_name": planned.get("display_name") or system,
        "plan_source": planned.get("plan_source", "adapter_draft" if planned.get("adapter_draft") else "legacy_plan"),
        "adapter_draft_consumed": bool(planned.get("adapter_draft_consumed")),
        "adapter_draft_id": (planned.get("adapter_draft") or {}).get("draft_id", ""),
        "write_strategy": planned.get("write_strategy"),
        "mcp_plan": planned.get("mcp_plan", {}),
        "collector_plan": planned.get("collector_plan", {}),
        "raw_archive_plan": planned.get("raw_archive_plan", {}),
        "native_delivery_plan": planned.get("native_delivery_plan", {}),
        "next_actions": planned.get("next_actions", []),
        "target_path": str(target_path),
        "backup_path": backup_path,
        "rollback_plan": "restore_backup_file_and_remove_added_mcp_server",
        "applied_mcp_server": {
            "name": applied["server_name"],
            "type": applied.get("type", "http"),
            "url": applied.get("server_url", ""),
            "endpoint": applied.get("endpoint", applied.get("server_url", "")),
            "command": applied.get("command", ""),
            "args": applied.get("args", []),
            "env": applied.get("env", {}),
            "already_configured": applied["already_configured"],
        },
        "applied_native_delivery": native_delivery_result,
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        "capability_check_after_connect": True,
        "real_recall_after_connect": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": planned.get("conversation_memory_boundary") or _conversation_memory_boundary(system),
        "read_chat_bodies": False,
        "memory_write_performed": False,
        "platform_write_performed": True,
    }
    receipt_path = _persist_platform_apply_receipt(receipt, memcore_root=memcore_root)
    return {
        "ok": True,
        "contract": AUTOCONNECT_APPLY_CONTRACT,
        "generated_at": ts(),
        "read_only": False,
        "dry_run": False,
        "system": system,
        "status": "applied",
        "write_performed": True,
        "platform_write_performed": True,
        "memory_write_performed": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "real_recall_after_connect": False,
        "target_path": str(target_path),
        "backup_path": backup_path,
        "receipt_path": receipt_path,
        "receipt": receipt,
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        "mcp_plan": receipt["mcp_plan"],
        "collector_plan": receipt["collector_plan"],
        "raw_archive_plan": receipt["raw_archive_plan"],
        "native_delivery_plan": receipt["native_delivery_plan"],
    }
