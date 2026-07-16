#!/usr/bin/env python3
"""Platform Guard surface scanning and adapter draft construction under Tiandao."""

from __future__ import annotations

import time

try:
    from src.platform_guard_catalog import *
except Exception:  # pragma: no cover - direct script import fallback
    from platform_guard_catalog import *
try:
    from src.platform_guard_model_identity import *
except Exception:  # pragma: no cover - direct script import fallback
    from platform_guard_model_identity import *
try:
    from src.source_system_runtime_declarations import source_system_native_delivery_shape
except Exception:  # pragma: no cover - direct script import fallback
    from source_system_runtime_declarations import source_system_native_delivery_shape

PLATFORM_GUARD_SURFACE_SCAN_CONTRACT = "tiandao_platform_guard_surface_scan.v1"
SMART_FILESYSTEM_SCAN_BUDGET_SECONDS = 2.5
HOST_SELF_INSTALL_REQUIRED_STATUS = "host_self_install_required"
HOST_ACTION_REQUIRED_STATUS = "host_action_required"
AUTOCONNECT_TARGET_SELECTION_DECLARATIONS = {
    "codex": {"required_filename": "config.toml", "limit": 1},
}
APPLY_ENDPOINT_STATUS_DECLARATIONS = {
    "codex": "implemented_for_codex_cli_mcp_bridge",
}


def get_platform_guard_surface_scan_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": PLATFORM_GUARD_SURFACE_SCAN_CONTRACT,
        "zh_name": "平台守护表面扫描",
        "en_name": "Platform Guard Surface Scan",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "workbench_id": "platform_guard",
        "console_layer": "platform_guard_surface_scan",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "surface_scan_finds_platform_inlets_and_candidate_collectors_only",
        "adapter_draft_policy": "drafts_require_verified_collectors_before_chat_body_ingest",
    }


def _candidate_connection_status(system: str, surface: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    del system
    config_paths = list(surface.get("config_paths") or [])
    supports_mcp = bool(result.get("supports_mcp_likely")) or bool(surface.get("mcp_config_detected"))
    if surface.get("connectable_now") or surface.get("memcore_mcp_detected"):
        next_step = "run_capability_check"
    elif supports_mcp and config_paths:
        next_step = "host_configures_own_mcp_then_self_reports"
    elif supports_mcp:
        next_step = "host_declares_mcp_and_skill_capabilities"
    else:
        next_step = "observe_storage_shape"
    return {
        "supports_mcp_likely": supports_mcp,
        "skill_surface_likely": bool(result.get("skill_surface_likely")),
        "config_paths": config_paths,
        "auto_connect_supported_now": False,
        "apply_endpoint_status": "host_self_install_receipt_only",
        "next_step": next_step,
        "identity_inference_role": "non_authoritative_discovery_hint",
        "host_owns_config_write_and_rollback": True,
        "time_library_platform_write_supported": False,
    }


def _candidate_native_artifact_format(system: str, surface: dict[str, Any]) -> str:
    preferred_roles = {"content_store", "app_data", "project_artifacts", "workspace"}
    signals = [signal for signal in surface.get("signals", []) if isinstance(signal, dict)]
    for signal in signals:
        artifact_format = str(signal.get("artifact_format") or "").strip()
        if artifact_format and signal.get("complete_conversation_candidate") is True:
            return artifact_format
    for signal in signals:
        artifact_format = str(signal.get("artifact_format") or "").strip()
        role = str(signal.get("role") or "").strip()
        if artifact_format and role in preferred_roles:
            return artifact_format
    for storage_item in _verified_storage_patterns(system):
        role = str(storage_item.get("role") or "").strip()
        artifact_format = str(storage_item.get("artifact_format") or "").strip()
        if artifact_format and role in preferred_roles:
            return artifact_format
    return f"{_slug(system)}_native_store"


def _candidate_next_actions(connection: dict[str, Any], collector_status: str, boundary: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    next_step = str(connection.get("next_step") or "")
    if next_step:
        actions.append(next_step)
    if collector_status == "verified_collector_required":
        actions.append("create_verified_format_collector")
    if boundary.get("complete_conversation_candidate"):
        actions.append("verify_assistant_reply_roundtrip")
    actions.append("write_computer_first_raw_archive_after_verified_collection")
    return list(dict.fromkeys(actions))


def _build_adapter_draft(
    *,
    system: str,
    display_name: str,
    surface: dict[str, Any],
    result: dict[str, Any],
    connection: dict[str, Any],
    recognized_by: str,
    recognition_mode: str,
    confidence: float,
    native_delivery_shape: str = "",
) -> dict[str, Any]:
    content_store_paths = list(surface.get("content_store_paths") or [])
    workspace_paths = list(surface.get("workspace_paths") or [])
    boundary = surface.get("conversation_memory_boundary") or _conversation_memory_boundary(
        system,
        [*content_store_paths, *workspace_paths],
    )
    collector_required = bool(content_store_paths or workspace_paths or boundary.get("complete_conversation_candidate"))
    collector_status = "verified_collector_required" if collector_required else "no_content_store_detected"
    native_artifact_format = _candidate_native_artifact_format(system, surface)
    return {
        "contract": ADAPTER_DRAFT_CONTRACT,
        "draft_type": "local_ai_tool_adapter_draft",
        "draft_id": _slug(f"{system}-{display_name}-draft"),
        "status": "draft_ready",
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "recognition": {
            "recognized_by": recognized_by,
            "recognition_mode": recognition_mode,
            "confidence": round(confidence, 2),
            "model_status": result.get("status", ""),
            "reason": result.get("reason", ""),
        },
        "mcp": {
            "supports_mcp_likely": bool(connection.get("supports_mcp_likely")),
            "skill_surface_likely": bool(connection.get("skill_surface_likely")),
            "config_paths": list(surface.get("config_paths") or []),
            "candidate_config_patterns": list(_catalog_mcp_config_patterns(system))[:12],
            "auto_connect_supported_now": bool(connection.get("auto_connect_supported_now")),
            "apply_endpoint_status": connection.get("apply_endpoint_status", ""),
            "next_step": connection.get("next_step", ""),
        },
        "native_delivery": {
            "shape": native_delivery_shape or source_system_native_delivery_shape(system),
            "install_once_aware": True,
            "already_running_probe": "front_door_discovery_health_or_install_marker",
        },
        "collector": {
            "collector_status": collector_status,
            "collector_kind": "verified_format_collector",
            "parser_gate": boundary.get("parser_gate", "verified_format_collector_required"),
            "native_artifact_format": native_artifact_format,
            "storage_candidate": result.get("storage_candidate") or _storage_candidate_for_surface(surface),
            "content_store_paths": content_store_paths,
            "workspace_paths": workspace_paths,
            "complete_conversation_candidate": bool(boundary.get("complete_conversation_candidate")),
            "assistant_replies_may_persist": boundary.get("assistant_replies_may_persist", False),
            "assistant_reply_persistence": boundary.get("assistant_reply_persistence", "unverified"),
            "content_read": False,
            "chat_body_included": False,
            "raw_excerpt_included": False,
        },
        "raw_archive": {
            "layout": "computer_first",
            "effective_from_version": "2026.6.1",
            "segment_order": ["computer_name", "source_system", "native_artifact_format"],
            "source_system": system,
            "native_artifact_format": native_artifact_format,
            "preferred_template": "memory/{computer_name}/{source_system}/{native_artifact_format}/{native_scope}/{session_id}.jsonl",
            "legacy_layout_allowed_for_new_writes": False,
        },
        "conversation_memory_boundary": boundary,
        "next_actions": _candidate_next_actions(connection, collector_status, boundary),
    }


def _build_provisional_adapter_candidate(surface: dict[str, Any]) -> dict[str, Any]:
    system = str(surface.get("system") or "unknown_surface")
    identification = surface.get("model_identification") if isinstance(surface.get("model_identification"), dict) else {}
    result = identification.get("result") if isinstance(identification.get("result"), dict) else _rule_identification_result(surface)
    mode = str(identification.get("mode") or "fallback_rules")
    recognized_by = "model" if mode == "configured_model" and result.get("status") == "identified_by_model" else "local_rules"
    display_name = str(result.get("likely_name") or surface.get("display_name") or system)
    category = str(result.get("category") or surface.get("platform_family") or "unknown")
    confidence = result.get("confidence", 0.0)
    try:
        confidence_value = float(confidence)
    except Exception:
        confidence_value = 0.0
    connection = _candidate_connection_status(system, surface, result)
    content_store_paths = list(surface.get("content_store_paths") or [])
    workspace_paths = list(surface.get("workspace_paths") or [])
    adapter_draft = _build_adapter_draft(
        system=system,
        display_name=display_name,
        surface=surface,
        result=result,
        connection=connection,
        recognized_by=recognized_by,
        recognition_mode=mode,
        confidence=confidence_value,
        native_delivery_shape=source_system_native_delivery_shape(system),
    )
    candidate = {
        "contract": PROVISIONAL_ADAPTER_CANDIDATE_CONTRACT,
        "candidate_type": "provisional_adapter_candidate",
        "candidate_id": _slug(f"{system}-{display_name}"),
        "system": system,
        "display_name": display_name,
        "source_surface": surface.get("source", ""),
        "recognized_by": recognized_by,
        "recognition_mode": mode,
        "confidence": round(confidence_value, 2),
        "category": category,
        "reason": result.get("reason", ""),
        "status": "candidate_ready",
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "connection": connection,
        "adapter_draft": adapter_draft,
        "storage": {
            "storage_candidate": result.get("storage_candidate") or _storage_candidate_for_surface(surface),
            "content_store_paths": content_store_paths,
            "workspace_paths": workspace_paths,
            "conversation_memory_boundary": surface.get("conversation_memory_boundary") or _conversation_memory_boundary(
                system,
                [*content_store_paths, *workspace_paths],
            ),
            "parser_gate": "verified_format_collector_required",
            "content_read": False,
            "chat_body_included": False,
            "raw_excerpt_included": False,
        },
        "next_step": connection["next_step"],
    }
    return candidate


def _refresh_catalog_surface_metadata(surface: dict[str, Any], system: str) -> None:
    entry = _catalog_entry(system)
    if not entry:
        return
    surface["display_name"] = entry.get("display_name") or surface.get("display_name") or system
    surface["catalog_driven"] = True
    surface["catalog_entry"] = _catalog_entry_summary(system)
    surface["platform_family"] = entry.get("family", surface.get("platform_family"))


def build_generic_local_ai_surfaces(
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    execute_model_identification: bool = False,
    scan_mode: str = "deep",
    model_execute_limit: int | None = None,
    include_software_probe: bool | None = None,
    scan_deadline_seconds: float | None = None,
) -> dict[str, Any]:
    resolved_scan_mode = _normalize_generic_scan_mode(scan_mode)
    software_probe = resolved_scan_mode == "deep" if include_software_probe is None else bool(include_software_probe)
    scan_started = time.monotonic()
    filesystem_scan_budget_seconds: float | None = None
    if resolved_scan_mode == "smart":
        requested_budget = SMART_FILESYSTEM_SCAN_BUDGET_SECONDS if scan_deadline_seconds is None else scan_deadline_seconds
        try:
            filesystem_scan_budget_seconds = max(0.05, min(float(requested_budget), 30.0))
        except (TypeError, ValueError):
            filesystem_scan_budget_seconds = SMART_FILESYSTEM_SCAN_BUDGET_SECONDS
    filesystem_scan_deadline = (
        scan_started + filesystem_scan_budget_seconds
        if filesystem_scan_budget_seconds is not None
        else None
    )
    execute_limit = _normalize_execute_limit(
        model_execute_limit,
        default=DEFAULT_MODEL_IDENTIFICATION_EXECUTE_LIMIT,
    )
    remaining_model_calls = execute_limit
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    roots = _generic_scan_roots(resolved_home, resolved_env)
    package_inventory = build_package_manager_agent_inventory(home=resolved_home, env=resolved_env)
    surfaces: dict[str, dict[str, Any]] = {}
    seen_config_paths: set[str] = set()
    for system in _verified_storage_systems():
        if _scan_deadline_reached(filesystem_scan_deadline):
            break
        for storage_item in _verified_storage_patterns(system):
            paths = storage_item.get("paths") if isinstance(storage_item.get("paths"), list) else []
            for pattern in [str(path) for path in paths if _looks_like_path_pattern(str(path))]:
                if _scan_deadline_reached(filesystem_scan_deadline):
                    break
                for path in _expanded_catalog_pattern_paths(
                    pattern,
                    home=resolved_home,
                    env=resolved_env,
                    roots=roots,
                    deadline_monotonic=filesystem_scan_deadline,
                    max_results=200 if filesystem_scan_deadline is not None else None,
                ):
                    if _scan_deadline_reached(filesystem_scan_deadline):
                        break
                    if not _safe_exists(path):
                        continue
                    surface = surfaces.setdefault(system, _generic_surface_record(system, source="verified_storage_patterns"))
                    _refresh_catalog_surface_metadata(surface, system)
                    _record_verified_storage_path(
                        surface,
                        system=system,
                        path=path,
                        storage_item=storage_item,
                        path_pattern=pattern,
                    )
                    if str(path) in surface.get("config_paths", []):
                        seen_config_paths.add(str(path))
    for system, path in _iter_catalog_config_candidates(
        roots,
        resolved_home,
        resolved_env,
        deadline_monotonic=filesystem_scan_deadline,
    ):
        probe = _config_probe(path)
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="catalog_mcp_config_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        path_text = str(path)
        seen_config_paths.add(path_text)
        if path_text not in surface["config_paths"]:
            surface["config_paths"].append(path_text)
        surface["signals"].append({**probe, "catalog_driven": True})
        surface["mcp_config_detected"] = surface["mcp_config_detected"] or bool(probe.get("mcp_detected"))
        surface["memcore_mcp_detected"] = surface["memcore_mcp_detected"] or bool(probe.get("memcore_mcp_detected"))
        surface["intent_signal_detected"] = surface["intent_signal_detected"] or bool(probe.get("intent_signal_detected"))
        surface["connectable_now"] = surface["connectable_now"] or bool(probe.get("memcore_mcp_detected"))
    if resolved_scan_mode == "deep":
        generic_config_candidates = _iter_generic_config_candidates(roots)
        generic_workspace_candidates = _iter_generic_workspace_candidates(roots)
        git_repo_candidates = _iter_git_repo_candidates(roots)
        limits = {
            "max_depth": 5,
            "max_dirs": 500,
            "max_workspace_dirs": 3000,
            "max_files": 800,
        }
    elif resolved_scan_mode == "smart":
        generic_config_candidates = _iter_generic_config_candidates(
            roots,
            max_depth=2,
            max_dirs=160,
            max_files=300,
            deadline_monotonic=filesystem_scan_deadline,
        )
        generic_workspace_candidates = _iter_generic_workspace_candidates(
            roots,
            max_depth=2,
            max_dirs=260,
            deadline_monotonic=filesystem_scan_deadline,
        )
        git_repo_candidates = _iter_git_repo_candidates(
            roots,
            max_depth=2,
            max_dirs=260,
            deadline_monotonic=filesystem_scan_deadline,
        )
        limits = {
            "max_depth": 2,
            "max_dirs": 160,
            "max_workspace_dirs": 260,
            "max_files": 300,
        }
    else:
        generic_config_candidates = []
        generic_workspace_candidates = []
        git_repo_candidates = []
        limits = {
            "full_scan_endpoint": "/api/v1/platforms/generic-local-ai-surfaces?scan=full",
        }
    for path in generic_config_candidates:
        if str(path) in seen_config_paths:
            continue
        probe = _config_probe(path)
        if not probe.get("mcp_detected") and not probe.get("intent_signal_detected"):
            continue
        system = _infer_surface_id(path, resolved_home)
        if _is_infrastructure_surface_id(system):
            continue
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="generic_mcp_config_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        path_text = str(path)
        if path_text not in surface["config_paths"]:
            surface["config_paths"].append(path_text)
        surface["signals"].append(probe)
        surface["mcp_config_detected"] = surface["mcp_config_detected"] or bool(probe.get("mcp_detected"))
        surface["memcore_mcp_detected"] = surface["memcore_mcp_detected"] or bool(probe.get("memcore_mcp_detected"))
        surface["intent_signal_detected"] = surface["intent_signal_detected"] or bool(probe.get("intent_signal_detected"))
        surface["connectable_now"] = surface["connectable_now"] or bool(probe.get("memcore_mcp_detected"))
    for path in generic_workspace_candidates:
        system = _infer_surface_id(path, resolved_home)
        if _is_infrastructure_surface_id(system):
            continue
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="generic_workspace_surface_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        _record_workspace_surface_path(surface, path)
        augmenter = VERIFIED_STORAGE_AUGMENTERS.get(system)
        if augmenter is not None:
            augmenter(surface, path)
    for repo_path in git_repo_candidates:
        system = _catalog_system_for_repo(repo_path)
        if not system:
            continue
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="github_watchlist_repo_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        path_text = str(repo_path)
        if path_text not in surface["workspace_paths"]:
            surface["workspace_paths"].append(path_text)
        surface["signals"].append({
            "kind": "github_watchlist_repo",
            "path": path_text,
            "repo_config_read": True,
            "source_read": False,
            "parser_gate": "not_applicable_repo_metadata_only",
        })
    for match in package_inventory.get("matches", []):
        system = str(match.get("system") or "")
        if not system:
            continue
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="package_manager_inventory"))
        _refresh_catalog_surface_metadata(surface, system)
        install_path = str(match.get("path") or "")
        if install_path and install_path not in surface["installation_paths"]:
            surface["installation_paths"].append(install_path)
        surface["signals"].append({
            "kind": "package_manager_install",
            "manager": match.get("manager", ""),
            "name": match.get("name", ""),
            "path": install_path,
            "version": match.get("version", ""),
            "source_read": False,
            "content_read": False,
        })
    for system in _platform_catalog_entries():
        if system in surfaces:
            continue
        app = _app_bundle_metadata(system, resolved_home, resolved_env) if software_probe else {
            "installed": False,
            "bundle_path": "",
            "version": "",
            "build": "",
            "modified_at": "",
            "age_days": None,
            "freshness": "unknown",
            "probe_skipped": True,
        }
        cli = _cli_version_metadata(system, resolved_home, resolved_env) if software_probe else {
            "installed": False,
            "path": "",
            "version": "",
            "raw": "",
            "probe_skipped": True,
        }
        if not app.get("installed") and not cli.get("installed"):
            continue
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="catalog_installed_software_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        surface["signals"].append({
            "kind": "catalog_installed_software",
            "app_installed": bool(app.get("installed")),
            "cli_installed": bool(cli.get("installed")),
            "content_read": False,
        })
    for system, surface in surfaces.items():
        activity_records = [
            ("config", Path(path))
            for path in surface.get("config_paths", [])
        ] + [
            ("content_store", Path(path))
            for path in surface.get("content_store_paths", [])
        ] + [
            ("workspace", Path(path))
            for path in surface.get("workspace_paths", [])
        ] + [
            ("installation", Path(path))
            for path in surface.get("installation_paths", [])
            if path
        ]
        app = _app_bundle_metadata(system, resolved_home, resolved_env) if software_probe else {
            "installed": False,
            "bundle_path": "",
            "version": "",
            "build": "",
            "modified_at": "",
            "age_days": None,
            "freshness": "unknown",
            "probe_skipped": True,
        }
        cli = _cli_version_metadata(system, resolved_home, resolved_env) if software_probe else {
            "installed": False,
            "path": "",
            "version": "",
            "raw": "",
            "probe_skipped": True,
        }
        if app.get("installed") and app.get("bundle_path"):
            activity_records.append(("app_bundle", Path(str(app["bundle_path"]))))
        if cli.get("installed") and cli.get("path"):
            activity_records.append(("cli_binary", Path(str(cli["path"]))))
        surface["software"] = {
            "app": app,
            "cli": cli,
        }
        surface["activity"] = _activity_snapshot(activity_records)
        _refresh_conversation_memory_boundary(surface)
        execute_this_surface = bool(execute_model_identification and remaining_model_calls > 0)
        surface["model_identification"] = _build_model_identification(
            surface,
            resolved_env,
            execute_model=execute_this_surface,
        )
        attempted_model_execution = (
            execute_this_surface
            and surface["model_identification"].get("mode") == "configured_model"
            and bool(surface["model_identification"].get("enabled"))
        )
        if execute_model_identification and _surface_needs_model_identification(surface):
            surface["model_identification"]["execution_deferred"] = True
            surface["model_identification"]["deferred_reason"] = "model_execute_limit_reached"
        if attempted_model_execution:
            remaining_model_calls -= 1
        surface["provisional_adapter_candidate"] = _build_provisional_adapter_candidate(surface)
    model_identifications = [
        surface.get("model_identification")
        for surface in surfaces.values()
        if isinstance(surface.get("model_identification"), dict)
    ]
    return {
        "ok": True,
        "contract": GENERIC_DISCOVERY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "scan_mode": resolved_scan_mode,
        "software_probe_mode": "enabled" if software_probe else "skipped_for_bounded_scan",
        "filesystem_scan_budget_seconds": filesystem_scan_budget_seconds,
        "filesystem_scan_deadline_exhausted": _scan_deadline_reached(filesystem_scan_deadline),
        "scan_elapsed_seconds": round(time.monotonic() - scan_started, 6),
        "scan_roots": [str(root) for root in roots],
        "surface_count": len(surfaces),
        "surfaces": list(surfaces.values()),
        "model_identification": {
            "contract": MODEL_IDENTIFICATION_CONTRACT,
            "read_only": True,
            "dry_run": True,
            "input_kind": "local_metadata_only",
            "model_call_performed": False,
            "execution_requested": bool(execute_model_identification),
            "execute_limit": execute_limit,
            "deferred_model_surface_count": sum(
                1 for item in model_identifications
                if bool(item.get("execution_deferred"))
            ),
            "executed_model_surface_count": sum(
                1 for item in model_identifications
                if bool(item.get("model_call_performed"))
            ),
            "configured_model_available": any(
                bool(item.get("configured_model", {}).get("configured"))
                for item in model_identifications
            ),
            "configured_model_surface_count": sum(
                1 for item in model_identifications
                if item.get("mode") == "configured_model"
            ),
            "fallback_rules_surface_count": sum(
                1 for item in model_identifications
                if item.get("mode") == "fallback_rules"
            ),
            "rules_confident_surface_count": sum(
                1 for item in model_identifications
                if item.get("mode") == "rules_confident"
            ),
        },
        "catalog": {
            "contract": PLATFORM_CATALOG_CONTRACT,
            "entry_count": load_platform_catalog().get("entry_count", 0),
            "github_watchlist_entry_count": load_platform_catalog().get("github_watchlist_entry_count", 0),
        },
        "package_manager_inventory": {
            "contract": package_inventory.get("contract"),
            "item_count": package_inventory.get("item_count", 0),
            "match_count": package_inventory.get("match_count", 0),
        },
        "limits": limits,
    }


def build_generic_local_ai_surfaces_snapshot() -> dict[str, Any]:
    catalog = load_platform_catalog()
    return {
        "ok": True,
        "contract": GENERIC_DISCOVERY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "scan_mode": "fast_snapshot",
        "surface_count": 0,
        "surfaces": [],
        "catalog": {
            "contract": PLATFORM_CATALOG_CONTRACT,
            "entry_count": catalog.get("entry_count", 0),
            "github_watchlist_entry_count": catalog.get("github_watchlist_entry_count", 0),
        },
        "limits": {
            "full_scan_endpoint": "/api/v1/platforms/generic-local-ai-surfaces?scan=full",
        },
    }


def _dir_signal_text(path: Path, limit: int = 60) -> str:
    names = [child.name for child in _safe_iterdir(path, limit=limit)]
    return " ".join(names)


def _path_descriptor(path: Path, path_role: str) -> dict[str, Any] | None:
    is_dir = _safe_is_dir(path)
    is_file = _safe_is_file(path)
    if not is_dir and not is_file:
        return None
    descriptor: dict[str, Any] = {
        "type": path_role,
        "path": str(path),
        "is_dir": is_dir,
        "is_file": is_file,
    }
    stat = _stat_snapshot(path)
    if stat:
        descriptor["modified_at"] = stat["modified_at"]
        descriptor["age_days"] = stat["age_days"]
        descriptor["freshness"] = stat["freshness"]
    if is_file:
        file_stat = _safe_stat(path)
        descriptor["size"] = file_stat.st_size if file_stat else None
    return descriptor


def _signal_detected(path: Path) -> bool:
    if INTENT_SIGNAL_RE.search(str(path)):
        return True
    if _safe_is_file(path):
        return bool(INTENT_SIGNAL_RE.search(_read_small_text(path)))
    if _safe_is_dir(path):
        return bool(INTENT_SIGNAL_RE.search(_dir_signal_text(path)))
    return False


def _activity_snapshot(records: list[tuple[str, Path]]) -> dict[str, Any]:
    by_role: dict[str, list[dict[str, Any]]] = {}
    for role, path in records:
        stat = _stat_snapshot(path)
        if not stat:
            continue
        by_role.setdefault(role, []).append({**stat, "role": role})
    latest_by_role: dict[str, dict[str, Any]] = {}
    for role, items in by_role.items():
        latest_by_role[role] = min(items, key=lambda item: int(item.get("age_days") or 0))
    primary_role = ""
    for candidate in ("content_store", "workspace", "config", "installation", "skill", "app_bundle", "cli_binary"):
        if candidate in latest_by_role:
            primary_role = candidate
            break
    primary = latest_by_role.get(primary_role, {})
    age = primary.get("age_days") if primary else None
    return {
        "primary_source": primary_role,
        "primary_path": primary.get("path", ""),
        "primary_last_seen_at": primary.get("modified_at", ""),
        "primary_age_days": age,
        "freshness": _freshness_from_age(age if isinstance(age, int) else None),
        "latest_by_role": latest_by_role,
    }


def _status_from_profile(profile: dict[str, Any]) -> str:
    status = str(profile.get("status") or "not_found")
    if status in {"active", "detected", "not_found"}:
        return status
    return "detected" if profile.get("instances") else "not_found"


def _profile_instances(profile: dict[str, Any]) -> list[dict[str, Any]]:
    instances = profile.get("instances")
    return list(instances) if isinstance(instances, list) else []


def _adapter_actions(
    *,
    detected: bool,
    intent_signal: bool,
    connectable_now: bool,
    content_bearing_store_detected: bool,
    current_focus: bool,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if not current_focus:
        actions.append({
            "action": "document_boundary_only",
            "status": "parked",
            "reason": "known_platform_but_not_current_product_focus",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
        return actions
    if not detected:
        actions.append({
            "action": "observe_only",
            "status": "waiting",
            "reason": "known_adapter_target_not_detected",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    elif connectable_now:
        actions.append({
            "action": "capability_check",
            "status": "ready",
            "reason": "memcore_mcp_or_tool_connection_detected",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    elif intent_signal:
        actions.append({
            "action": "await_host_self_install_and_self_report",
            "status": HOST_ACTION_REQUIRED_STATUS,
            "reason": "memcore_skill_or_mcp_signal_detected",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    else:
        actions.append({
            "action": "await_host_self_install_and_self_report",
            "status": HOST_ACTION_REQUIRED_STATUS,
            "reason": "platform_detected_without_memcore_signal",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    if content_bearing_store_detected:
        actions.append({
            "action": "verified_format_collector",
            "status": "collector_required",
            "reason": "content_bearing_store_detected_and_waiting_for_verified_collector",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    return actions


def _probe_spec(
    spec: AdapterSpec,
    *,
    runtime_profile: dict[str, Any],
    home: Path,
    env: dict[str, str],
    include_software_probe: bool = True,
) -> dict[str, Any]:
    profile = runtime_profile.get(spec.system) if isinstance(runtime_profile.get(spec.system), dict) else {}
    profile_status = _status_from_profile(profile)
    profile_instances = _profile_instances(profile)
    instances: list[dict[str, Any]] = list(profile_instances)
    seen_paths = {str(item.get("path")) for item in instances if item.get("path")}
    intent_signal = False
    connectable_now = False
    mcp_config_detected = False
    memcore_mcp_detected = False
    skill_signal_detected = False
    content_bearing_store_detected = False
    signals: list[dict[str, Any]] = []
    activity_records: list[tuple[str, Path]] = []
    config_patterns = tuple(dict.fromkeys((*spec.config_paths, *_catalog_mcp_config_patterns(spec.system))))

    for role, patterns in (
        ("config", config_patterns),
        ("skill", spec.skill_paths),
        ("content_store", spec.content_paths),
    ):
        for pattern in patterns:
            path = _expand_path(pattern, home, env)
            if path is None:
                continue
            descriptor = _path_descriptor(path, role)
            if descriptor is None:
                continue
            activity_records.append((role, path))
            if descriptor.get("path") not in seen_paths:
                instances.append(descriptor)
                seen_paths.add(str(descriptor.get("path")))
            if role == "content_store":
                content_bearing_store_detected = True
                signals.append({
                    "kind": "content_store",
                    "path": str(path),
                    "content_read": False,
                    "parser_gate": spec.content_gate,
                })
            config_probes: list[dict[str, Any]] = []
            descriptor_is_file = bool(descriptor.get("is_file"))
            descriptor_is_dir = bool(descriptor.get("is_dir"))
            if role in {"config", "skill"} and descriptor_is_file:
                config_probes.append(_config_probe(path))
            elif role in {"config", "skill"} and descriptor_is_dir:
                config_probes.extend(_dir_config_probe(path))
            for probe in config_probes:
                signals.append(probe)
                mcp_config_detected = mcp_config_detected or bool(probe.get("mcp_detected"))
                memcore_mcp_detected = memcore_mcp_detected or bool(probe.get("memcore_mcp_detected"))
                intent_signal = intent_signal or bool(probe.get("intent_signal_detected"))
            signal_detected = _signal_detected(path)
            if role == "skill" and signal_detected:
                skill_signal_detected = True
                intent_signal = True
            elif signal_detected:
                intent_signal = True

    profile_consumer = profile.get("consumer_connection") if isinstance(profile.get("consumer_connection"), dict) else {}
    if profile_consumer.get("skill_detected") or profile_consumer.get("mcp_detected"):
        intent_signal = True
        skill_signal_detected = skill_signal_detected or bool(profile_consumer.get("skill_detected"))
        mcp_config_detected = mcp_config_detected or bool(profile_consumer.get("mcp_detected"))
    if profile_consumer.get("recall_connection_ready") or memcore_mcp_detected:
        connectable_now = True
    app = _app_bundle_metadata(spec.system, home, env) if include_software_probe else {
        "installed": False,
        "bundle_path": "",
        "version": "",
        "build": "",
        "modified_at": "",
        "age_days": None,
        "freshness": "unknown",
        "probe_skipped": True,
    }
    cli = _cli_version_metadata(spec.system, home, env) if include_software_probe else {
        "installed": False,
        "path": "",
        "version": "",
        "raw": "",
        "probe_skipped": True,
    }
    if app.get("installed") and app.get("bundle_path"):
        activity_records.append(("app_bundle", Path(str(app["bundle_path"]))))
    if cli.get("installed") and cli.get("path"):
        activity_records.append(("cli_binary", Path(str(cli["path"]))))
    conversation_boundary = _conversation_memory_boundary(
        spec.system,
        [str(path) for _role, path in activity_records],
    )
    detected = profile_status != "not_found" or bool(instances)
    status = profile_status if profile_status != "not_found" else ("detected" if instances else "not_found")
    actions = _adapter_actions(
        detected=detected,
        intent_signal=intent_signal,
        connectable_now=connectable_now,
        content_bearing_store_detected=content_bearing_store_detected,
        current_focus=spec.current_focus,
    )
    return {
        "system": spec.system,
        "display_name": spec.display_name,
        "support_level": spec.support_level,
        "platform_family": spec.platform_family,
        "status": status,
        "detected": detected,
        "thin_adapter": True,
        "current_focus": spec.current_focus,
        "read_only": True,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "connection_surfaces": list(spec.connection_surfaces),
        "instance_count": len(instances),
        "instances": instances,
        "signals": signals,
        "mcp_config_detected": mcp_config_detected,
        "memcore_mcp_detected": memcore_mcp_detected,
        "skill_signal_detected": skill_signal_detected,
        "intent_signal_detected": intent_signal,
        "connectable_now": connectable_now,
        "content_bearing_store_detected": content_bearing_store_detected,
        "content_gate": spec.content_gate,
        "software": {
            "app": app,
            "cli": cli,
        },
        "activity": _activity_snapshot(activity_records),
        "catalog_driven": bool(_catalog_entry(spec.system)),
        "catalog_entry": _catalog_entry_summary(spec.system),
        "skill_installation_is_intent_signal_only": True,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": conversation_boundary,
        "actions": actions,
        "notes": list(spec.notes),
    }


def build_thin_adapter_registry(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    include_generic: bool = True,
    include_software_probe: bool | None = None,
    execute_model_identification: bool = False,
    generic_scan_mode: str = "deep",
    model_execute_limit: int | None = None,
) -> dict[str, Any]:
    profile = runtime_profile or {}
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    catalog = load_platform_catalog()
    software_probe = (
        bool(include_generic and _normalize_generic_scan_mode(generic_scan_mode) == "deep")
        if include_software_probe is None
        else bool(include_software_probe)
    )
    adapters = [
        _probe_spec(
            spec,
            runtime_profile=profile,
            home=resolved_home,
            env=resolved_env,
            include_software_probe=software_probe,
        )
        for spec in ADAPTER_SPECS
    ]
    generic = build_generic_local_ai_surfaces(
        home=resolved_home,
        env=resolved_env,
        execute_model_identification=execute_model_identification,
        scan_mode=generic_scan_mode,
        model_execute_limit=model_execute_limit,
        include_software_probe=software_probe,
    ) if include_generic else {
        "ok": True,
        "contract": GENERIC_DISCOVERY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "scan_mode": "skipped_for_fast_snapshot",
        "software_probe_mode": "skipped_for_fast_snapshot",
        "filesystem_scan_budget_seconds": None,
        "filesystem_scan_deadline_exhausted": False,
        "scan_elapsed_seconds": 0.0,
        "surface_count": 0,
        "surfaces": [],
        "limits": {},
    }
    known_systems = {adapter["system"] for adapter in adapters}
    generic_surfaces = [
        surface for surface in generic.get("surfaces", [])
        if surface.get("system") not in known_systems
    ]
    detected = [item for item in adapters if item["detected"]]
    host_action_required = [
        item for item in adapters
        if any(action.get("status") == HOST_ACTION_REQUIRED_STATUS for action in item.get("actions", []))
    ]
    return {
        "ok": True,
        "contract": REGISTRY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "default_policy": "observe_compatibility_then_verify_host_self_install",
        "scan_mode": "full" if include_generic else "fast_known_adapters_only",
        "software_probe_mode": "enabled" if software_probe else "skipped_for_fast_snapshot",
        "adapter_count": len(adapters),
        "catalog_entry_count": catalog.get("entry_count", 0),
        "github_watchlist_entry_count": catalog.get("github_watchlist_entry_count", 0),
        "detected_adapter_count": len(detected),
        "generic_surface_count": len(generic_surfaces),
        "generic_surface_memcore_ready_count": sum(1 for item in generic_surfaces if item.get("connectable_now")),
        "auto_connect_ready_count": 0,
        "host_self_install_required_count": len(host_action_required),
        "authorization_needed_count": 0,
        "registry_scope": [
            "release compatibility observations",
            "host-owned self-install hints",
            "generic editor and MCP surfaces",
            "content-bearing stores as locked parser gates",
        ],
        "global_guarantees": {
            "time_library_platform_write_supported": False,
            "host_owns_platform_config_and_rollback": True,
            "unknown_clients_admitted_by_generic_self_report": True,
            "known_platform_catalog_is_not_an_admission_allowlist": True,
        },
        "adapters": adapters,
        "platform_catalog": {
            "contract": catalog.get("contract"),
            "catalog_version": catalog.get("catalog_version"),
            "watchlist_version": catalog.get("watchlist_version"),
            "entry_count": catalog.get("entry_count"),
            "curated_entry_count": catalog.get("curated_entry_count"),
            "github_watchlist_entry_count": catalog.get("github_watchlist_entry_count"),
        },
        "generic_surface_discovery": {
            **generic,
            "surfaces": generic_surfaces,
            "surface_count": len(generic_surfaces),
        },
        "model_identification": {
            "contract": MODEL_IDENTIFICATION_CONTRACT,
            "read_only": True,
            "dry_run": True,
            "input_kind": "local_metadata_only",
            "model_call_performed": False,
            "execution_requested": bool(execute_model_identification),
            "execute_limit": _normalize_execute_limit(model_execute_limit),
            "deferred_model_surface_count": int(
                sum(
                    1 for item in generic_surfaces
                    if ((item.get("model_identification") or {}).get("execution_deferred"))
                )
            ),
            "executed_model_surface_count": int(
                sum(
                    1 for item in generic_surfaces
                    if ((item.get("model_identification") or {}).get("model_call_performed"))
                )
            ),
            "configured_model_available": bool(
                any(
                    bool(((item.get("model_identification") or {}).get("configured_model") or {}).get("configured"))
                    for item in generic_surfaces
                )
            ),
            "configured_model_surface_count": int(
                sum(
                    1 for item in generic_surfaces
                    if (item.get("model_identification") or {}).get("mode") == "configured_model"
                )
            ),
            "fallback_rules_surface_count": int(
                sum(
                    1 for item in generic_surfaces
                    if (item.get("model_identification") or {}).get("mode") == "fallback_rules"
                )
            ),
            "rules_confident_surface_count": int(
                sum(
                    1 for item in generic_surfaces
                    if (item.get("model_identification") or {}).get("mode") == "rules_confident"
                )
            ),
        },
        "authorization_contract": {
            "can_auto_discover": True,
            "default_connection_mode": "auto_discover_and_auto_connect",
            "can_auto_connect_supported_configs": True,
            "conversation_import_mode": "verified_format_collectors",
            "window_memory_scope_default": "current_window_first",
            "skill_installation_is_connection_signal": True,
            "receipts_required_for_writes": True,
            "backup_required_before_platform_config_write": True,
        },
    }


def build_model_identification_report(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    include_generic: bool = True,
    execute: bool = False,
    scan_mode: str = "smart",
    model_execute_limit: int | None = None,
) -> dict[str, Any]:
    resolved_scan_mode = "fast_snapshot" if not include_generic else _normalize_generic_scan_mode(scan_mode)
    software_probe = bool(include_generic and resolved_scan_mode == "deep")
    registry = build_thin_adapter_registry(
        runtime_profile,
        home=home,
        env=env,
        include_generic=include_generic,
        include_software_probe=software_probe,
        execute_model_identification=execute and include_generic,
        generic_scan_mode=resolved_scan_mode,
        model_execute_limit=model_execute_limit,
    )
    surfaces = registry.get("generic_surface_discovery", {}).get("surfaces", [])
    items: list[dict[str, Any]] = []
    for surface in surfaces:
        if not isinstance(surface, dict):
            continue
        identification = surface.get("model_identification") if isinstance(surface.get("model_identification"), dict) else {}
        result = identification.get("result") if isinstance(identification.get("result"), dict) else {}
        envelope = identification.get("request_envelope") if isinstance(identification.get("request_envelope"), dict) else {}
        metadata = identification.get("local_metadata") if isinstance(identification.get("local_metadata"), dict) else {}
        candidate = surface.get("provisional_adapter_candidate") if isinstance(surface.get("provisional_adapter_candidate"), dict) else {}
        items.append({
            "system": surface.get("system", ""),
            "display_name": surface.get("display_name", ""),
            "source": surface.get("source", ""),
            "mode": identification.get("mode", "unknown"),
            "enabled": bool(identification.get("enabled")),
            "reason": identification.get("reason", ""),
            "configured_model": identification.get("configured_model", {}),
            "executor": identification.get("executor", ""),
            "model_call_performed": bool(identification.get("model_call_performed")),
            "result": result,
            "execution": identification.get("execution", {}),
            "request_envelope": envelope,
            "local_metadata": metadata,
            "provisional_adapter_candidate": candidate,
            "chat_body_included": bool(identification.get("chat_body_included", False)),
            "raw_excerpt_included": bool(identification.get("raw_excerpt_included", False)),
        })
    summary = registry.get("model_identification", {}) if isinstance(registry.get("model_identification"), dict) else {}
    generic_discovery = registry.get("generic_surface_discovery", {}) if isinstance(registry.get("generic_surface_discovery"), dict) else {}
    return {
        "ok": True,
        "contract": MODEL_IDENTIFICATION_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": not execute,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "input_kind": "local_metadata_only",
        "scan_mode": resolved_scan_mode,
        "software_probe_mode": registry.get("software_probe_mode", "skipped_for_fast_snapshot"),
        "filesystem_scan_budget_seconds": generic_discovery.get("filesystem_scan_budget_seconds"),
        "filesystem_scan_deadline_exhausted": bool(generic_discovery.get("filesystem_scan_deadline_exhausted")),
        "scan_elapsed_seconds": generic_discovery.get("scan_elapsed_seconds", 0.0),
        "execute_requested": bool(execute),
        "execute_limit": _normalize_execute_limit(model_execute_limit),
        "model_call_performed": any(item["model_call_performed"] for item in items),
        "summary": {
            "surface_count": len(items),
            "configured_model_available": bool(summary.get("configured_model_available")),
            "configured_model_surface_count": int(summary.get("configured_model_surface_count") or 0),
            "fallback_rules_surface_count": int(summary.get("fallback_rules_surface_count") or 0),
            "rules_confident_surface_count": int(summary.get("rules_confident_surface_count") or 0),
            "executed_model_surface_count": int(summary.get("executed_model_surface_count") or 0),
            "deferred_model_surface_count": int(summary.get("deferred_model_surface_count") or 0),
            "provisional_adapter_candidate_count": sum(
                1 for item in items
                if item.get("provisional_adapter_candidate")
            ),
        },
        "items": items,
        "public_summary": {
            "local_tools_checked": len(items),
            "ready_for_model_identification": sum(1 for item in items if item.get("mode") == "configured_model"),
            "using_rule_fallback": sum(1 for item in items if item.get("mode") == "fallback_rules"),
            "recognized_from_local_signals": sum(1 for item in items if item.get("mode") == "rules_confident"),
        },
    }


_PUBLIC_STRATEGY_TOKEN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("github_watchlist", "known_repo_reference"),
    ("GitHub Watchlist", "Known Repo Reference"),
    ("github_top100", "known_repo_reference"),
    ("GitHub100", "known repo reference"),
    ("catalog_watchlist", "catalog_reference"),
    ("watchlist", "reference_list"),
    ("platform_catalog", "tool_reference"),
    ("thin_adapter", "tool_adapter"),
    ("泛发现", "本地发现"),
    ("平台字典", "工具识别"),
    ("orchestration system", "orchestration system"),
    ("调度系统", "调度系统"),
    ("Tiandao", "public rules"),
    ("公共规则", "公共规则"),
)


def _public_text_without_strategy_terms(value: str) -> str:
    result = value
    for old, new in _PUBLIC_STRATEGY_TOKEN_REPLACEMENTS:
        result = result.replace(old, new)
    return result


def _public_payload_without_strategy_terms(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            _public_text_without_strategy_terms(str(key)): _public_payload_without_strategy_terms(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_public_payload_without_strategy_terms(item) for item in value]
    if isinstance(value, tuple):
        return [_public_payload_without_strategy_terms(item) for item in value]
    if isinstance(value, str):
        return _public_text_without_strategy_terms(value)
    return value


def public_tool_discovery_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a product-facing copy without internal discovery strategy names."""
    sanitized = _public_payload_without_strategy_terms(payload)
    return sanitized if isinstance(sanitized, dict) else {}


def build_provisional_adapter_candidates_report(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    include_generic: bool = True,
    execute: bool = False,
    scan_mode: str = "smart",
    model_execute_limit: int | None = None,
) -> dict[str, Any]:
    identification = build_model_identification_report(
        runtime_profile,
        home=home,
        env=env,
        include_generic=include_generic,
        execute=execute,
        scan_mode=scan_mode,
        model_execute_limit=model_execute_limit,
    )
    candidates = [
        item.get("provisional_adapter_candidate")
        for item in identification.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("provisional_adapter_candidate"), dict)
    ]
    return {
        "ok": True,
        "contract": PROVISIONAL_ADAPTER_CANDIDATE_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": not execute,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "scan_mode": identification.get("scan_mode", "fast_snapshot"),
        "filesystem_scan_budget_seconds": identification.get("filesystem_scan_budget_seconds"),
        "filesystem_scan_deadline_exhausted": bool(identification.get("filesystem_scan_deadline_exhausted")),
        "scan_elapsed_seconds": identification.get("scan_elapsed_seconds", 0.0),
        "execute_requested": bool(execute),
        "execute_limit": identification.get("execute_limit", DEFAULT_MODEL_IDENTIFICATION_EXECUTE_LIMIT),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "summary": {
            "auto_connect_supported_now": sum(
                1 for candidate in candidates
                if (candidate.get("connection") or {}).get("auto_connect_supported_now")
            ),
            "adapter_draft_count": sum(
                1 for candidate in candidates
                if isinstance(candidate.get("adapter_draft"), dict)
            ),
            "verified_collectors_needed": sum(
                1 for candidate in candidates
                if ((candidate.get("adapter_draft") or {}).get("collector") or {}).get("collector_status")
                == "verified_collector_required"
            ),
            "complete_conversation_candidates": sum(
                1 for candidate in candidates
                if ((candidate.get("adapter_draft") or {}).get("collector") or {}).get("complete_conversation_candidate")
            ),
            "computer_first_archive_ready": sum(
                1 for candidate in candidates
                if ((candidate.get("adapter_draft") or {}).get("raw_archive") or {}).get("layout") == "computer_first"
            ),
            "needs_thin_adapter": sum(
                1 for candidate in candidates
                if candidate.get("next_step") == "create_thin_adapter_from_candidate"
            ),
            "needs_mcp_config_location": sum(
                1 for candidate in candidates
                if candidate.get("next_step") == "locate_mcp_config_surface"
            ),
        },
    }


def _existing_paths(adapter: dict[str, Any], role: str | None = None) -> list[str]:
    paths: list[str] = []
    for item in adapter.get("instances", []):
        if role is not None and item.get("type") != role:
            continue
        path = item.get("path")
        if path:
            paths.append(str(path))
    return paths


def _expanded_autoconnect_targets(
    system: str,
    *,
    adapter: dict[str, Any],
    home: Path,
    env: dict[str, str],
) -> list[str]:
    existing_config_paths = _existing_paths(adapter, "config")
    selection = AUTOCONNECT_TARGET_SELECTION_DECLARATIONS.get(system) or {}
    required_filename = str(selection.get("required_filename") or "").lower()
    if required_filename:
        targets = [
            path for path in existing_config_paths
            if Path(path).name.lower() == required_filename
        ]
        for pattern in AUTOCONNECT_TARGET_PATTERNS.get(system, ()):
            path = _expand_path(pattern, home, env)
            if path is not None and path.name.lower() == required_filename:
                text = str(path)
                if text not in targets:
                    targets.append(text)
        limit = max(1, int(selection.get("limit") or 1))
        return targets[:limit]
    targets = [path for path in existing_config_paths if _safe_is_file(Path(path))]
    patterns = tuple(dict.fromkeys((
        *AUTOCONNECT_TARGET_PATTERNS.get(system, ()),
        *_catalog_mcp_config_patterns(system),
    )))
    for pattern in patterns:
        roots = _generic_scan_roots(home, env)
        paths = _expanded_catalog_pattern_paths(pattern, home=home, env=env, roots=roots)
        if not paths:
            path = _expand_path(pattern, home, env)
            paths = [path] if path is not None else []
        for path in paths:
            if "*" in str(path):
                continue
            if Path(path).suffix.lower() != ".json" and "mcp" not in Path(path).name.lower():
                continue
            text = str(path)
            if text not in targets:
                targets.append(text)
    return targets[:3]


def _missing_for_adapter(adapter: dict[str, Any]) -> list[str]:
    if adapter.get("connectable_now"):
        return []
    missing: list[str] = []
    if not adapter.get("detected"):
        missing.append("platform_detection")
    if adapter.get("detected") and not adapter.get("memcore_mcp_detected"):
        missing.append("memcore_mcp_registration")
    if adapter.get("detected") and not adapter.get("connectable_now"):
        missing.append("capability_check_connection")
    return missing


def _plan_status(adapter: dict[str, Any]) -> str:
    if not adapter.get("current_focus", True):
        return "parked_not_current_focus"
    if not adapter.get("detected"):
        return "not_detected"
    if adapter.get("connectable_now"):
        return "ready_for_capability_check"
    return HOST_SELF_INSTALL_REQUIRED_STATUS


def _safe_next_step(status: str, item: dict[str, Any]) -> str:
    if status == "ready_for_capability_check":
        return "run_capability_check"
    if status == HOST_SELF_INSTALL_REQUIRED_STATUS:
        return "ask_host_agent_to_install_then_self_report"
    if status == "parked_not_current_focus":
        return "document_boundary_only"
    if status == "not_detected":
        return "observe_only"
    if item.get("content_bearing_store_detected"):
        return "parser_gate_locked"
    return "observe_only"


def _dashboard_item_from_adapter(adapter: dict[str, Any]) -> dict[str, Any]:
    status = _plan_status(adapter)
    safe_next_step = _safe_next_step(status, adapter)
    system = str(adapter.get("system") or "")
    return {
        "system": system,
        "display_name": adapter.get("display_name") or system,
        "surface_type": "known_thin_adapter",
        "support_level": adapter.get("support_level"),
        "platform_family": adapter.get("platform_family"),
        "status": status,
        "detected": bool(adapter.get("detected")),
        "connectable_now": bool(adapter.get("connectable_now")),
        "current_focus": bool(adapter.get("current_focus", True)),
        "intent_signal_detected": bool(adapter.get("intent_signal_detected")),
        "mcp_config_detected": bool(adapter.get("mcp_config_detected")),
        "memcore_mcp_detected": bool(adapter.get("memcore_mcp_detected")),
        "skill_signal_detected": bool(adapter.get("skill_signal_detected")),
        "content_bearing_store_detected": bool(adapter.get("content_bearing_store_detected")),
        "parser_gate": adapter.get("content_gate"),
        "software": adapter.get("software", {}),
        "activity": adapter.get("activity", {}),
        "freshness": (adapter.get("activity") or {}).get("freshness", "unknown"),
        "catalog_driven": bool(adapter.get("catalog_driven")),
        "catalog_entry": adapter.get("catalog_entry", {}),
        "safe_next_step": safe_next_step,
        "authorized_connect_plan_endpoint": f"/api/v1/platforms/{system}/authorized-connect-plan",
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD if status == "ready_for_capability_check" else {},
        "writes_now": False,
        "reads_chat_bodies": False,
        "real_recall_now": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": adapter.get("conversation_memory_boundary") or _conversation_memory_boundary(system),
        "instance_count": int(adapter.get("instance_count") or 0),
        "config_paths": _existing_paths(adapter, "config"),
    }


def _dashboard_item_from_generic_surface(surface: dict[str, Any]) -> dict[str, Any]:
    system = str(surface.get("system") or "")
    config_paths = list(surface.get("config_paths") or [])
    content_store_paths = list(surface.get("content_store_paths") or [])
    workspace_paths = list(surface.get("workspace_paths") or [])
    installation_paths = list(surface.get("installation_paths") or [])
    adapter_like = {
        "system": system,
        "detected": surface.get("detected"),
        "connectable_now": surface.get("connectable_now"),
        "current_focus": True,
    }
    status = _plan_status(adapter_like)
    safe_next_step = _safe_next_step(status, adapter_like)
    return {
        "system": system,
        "display_name": surface.get("display_name") or system,
        "surface_type": "generic_local_ai_surface",
        "support_level": "generic_surface_candidate",
        "platform_family": surface.get("platform_family") or "generic_mcp_or_config_surface",
        "status": status,
        "detected": bool(surface.get("detected")),
        "connectable_now": bool(surface.get("connectable_now")),
        "current_focus": True,
        "intent_signal_detected": bool(surface.get("intent_signal_detected")),
        "mcp_config_detected": bool(surface.get("mcp_config_detected")),
        "memcore_mcp_detected": bool(surface.get("memcore_mcp_detected")),
        "skill_signal_detected": False,
        "content_bearing_store_detected": bool(content_store_paths),
        "parser_gate": "verified_format_collector_required",
        "software": surface.get("software", {}),
        "activity": surface.get("activity", {}),
        "freshness": (surface.get("activity") or {}).get("freshness", "unknown"),
        "catalog_driven": bool(surface.get("catalog_driven")),
        "catalog_entry": surface.get("catalog_entry", {}),
        "safe_next_step": safe_next_step,
        "authorized_connect_plan_endpoint": f"/api/v1/platforms/{system}/authorized-connect-plan",
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD if status == "ready_for_capability_check" else {},
        "writes_now": False,
        "reads_chat_bodies": False,
        "real_recall_now": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": surface.get("conversation_memory_boundary") or _conversation_memory_boundary(
            system,
            [*content_store_paths, *workspace_paths],
        ),
        "model_identification": surface.get("model_identification", {}),
        "provisional_adapter_candidate": surface.get("provisional_adapter_candidate", {}),
        "instance_count": len(config_paths) + len(content_store_paths) + len(workspace_paths) + len(installation_paths),
        "config_paths": config_paths,
        "content_store_paths": content_store_paths,
        "workspace_paths": workspace_paths,
        "installation_paths": installation_paths,
    }


def _public_tool_type(item: dict[str, Any]) -> str:
    if item.get("surface_type") == "generic_local_ai_surface":
        return "local_tool"
    return "recognized_tool"


def _public_safe_next_step(value: str) -> str:
    mapping = {
        "auto_connect": "ask_host_agent_to_install_then_self_report",
        "host_configures_own_mcp_then_self_reports": "ask_host_agent_to_install_then_self_report",
        "document_boundary_only": "review_boundary",
        "observe_only": "keep_observing",
        "parser_gate_locked": "verified_collector",
    }
    return mapping.get(value, value)


def _public_recognition_status(item: dict[str, Any]) -> dict[str, Any]:
    identification = item.get("model_identification") if isinstance(item.get("model_identification"), dict) else {}
    mode = str(identification.get("mode") or "")
    if mode == "configured_model":
        return {
            "recognized_by": "model",
            "recognition_status": "ready_for_model_identification",
            "model_call_performed": False,
        }
    if mode == "fallback_rules":
        return {
            "recognized_by": "local_rules",
            "recognition_status": "fallback_rules",
            "model_call_performed": False,
        }
    return {
        "recognized_by": "local_rules",
        "recognition_status": "recognized_from_local_signals",
        "model_call_performed": False,
    }


def _public_dashboard_item(item: dict[str, Any]) -> dict[str, Any]:
    activity = item.get("activity") if isinstance(item.get("activity"), dict) else {}
    software = item.get("software") if isinstance(item.get("software"), dict) else {}
    app = software.get("app") if isinstance(software.get("app"), dict) else {}
    cli = software.get("cli") if isinstance(software.get("cli"), dict) else {}
    version = str(app.get("version") or cli.get("version") or "")
    recognition = _public_recognition_status(item)
    return {
        "system": item.get("system", ""),
        "display_name": item.get("display_name", ""),
        "tool_type": _public_tool_type(item),
        "status": item.get("status", "unknown"),
        "detected": bool(item.get("detected")),
        "ready_for_safe_check": item.get("status") == "ready_for_capability_check",
        "auto_connect_ready": False,
        "host_self_install_required": item.get("status") == HOST_SELF_INSTALL_REQUIRED_STATUS,
        "connectable_now": bool(item.get("connectable_now")),
        "memcore_connected": bool(item.get("memcore_mcp_detected")),
        "connection_signal_detected": bool(item.get("intent_signal_detected")),
        "version": version,
        "freshness": item.get("freshness") or activity.get("freshness") or "unknown",
        "last_seen_at": activity.get("primary_last_seen_at", ""),
        "recognized_by": recognition["recognized_by"],
        "recognition_status": recognition["recognition_status"],
        "model_call_performed": recognition["model_call_performed"],
        "safe_next_step": _public_safe_next_step(str(item.get("safe_next_step", "observe_only"))),
        "capability_check_payload": item.get("capability_check_payload", {}),
        "writes_now": False,
        "reads_chat_bodies": False,
        "real_recall_now": False,
        "chat_body_parser_requires_verified_collector": bool(
            item.get("chat_body_parser_requires_verified_collector")
        ),
    }


def _public_discovery_dashboard(full: dict[str, Any]) -> dict[str, Any]:
    counts = full.get("counts") if isinstance(full.get("counts"), dict) else {}
    public_summary = full.get("public_summary") if isinstance(full.get("public_summary"), dict) else {}
    public_items = [
        _public_dashboard_item(item)
        for item in full.get("items", [])
        if isinstance(item, dict)
    ]
    host_self_install_required = sum(
        1 for item in public_items if item.get("host_self_install_required")
    )
    public_counts = {
        "total": int(counts.get("total") or 0),
        "detected": int(counts.get("detected") or 0),
        "ready_for_capability_check": int(counts.get("ready_for_capability_check") or 0),
        "auto_connect_ready": 0,
        "host_self_install_required": int(
            host_self_install_required
            or counts.get("host_self_install_required")
            or counts.get("auto_connect_ready")
            or counts.get("needs_authorization")
            or 0
        ),
        "other_local_tools": int(public_summary.get("other_local_tools") or 0),
        "recently_quiet_tools": int(public_summary.get("recently_quiet_tools") or 0),
    }
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
        "counts": public_counts,
        "public_summary": {
            "local_ai_tools": public_counts["total"],
            "detected_tools": public_counts["detected"],
            "ready_for_safe_check": public_counts["ready_for_capability_check"],
            "auto_connect_ready": public_counts["auto_connect_ready"],
            "host_self_install_required": public_counts["host_self_install_required"],
            "other_local_tools": public_counts["other_local_tools"],
            "recently_quiet_tools": public_counts["recently_quiet_tools"],
        },
        "items": public_items,
        "global_guarantees": {
            "auto_connect_supported_skill_mcp_surfaces": False,
            "time_library_platform_write_supported": False,
            "host_owns_platform_config_and_rollback": True,
            "unknown_clients_admitted_by_generic_self_report": True,
            "conversation_import_mode": "verified_format_collectors",
            "capability_check_after_connect": True,
            "new_memory_layout": "computer_first",
            "legacy_memory_layout": "read_compatibility_only",
        },
    }




def _apply_endpoint_status_for_system(system: str) -> str:
    del system
    return "host_self_install_receipt_only"



__all__ = [name for name in globals() if not name.startswith("__")]
