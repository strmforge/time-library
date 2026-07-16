"""Read-only release-compatibility discovery.

Discovery may observe known local tool/config/storage shapes for diagnostics and
source ingestion. It never admits clients and never writes host configuration.
Consumer onboarding is the generic host-owned install plus verified self-report
contract. Source conversation import remains a separate verified-parser concern.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

CORE_NAME = "Time Library"
CODENAME = "Time Library"
DISCOVERY_CONTRACT = "tiandao_thin_adapter_autodiscovery.v1"
APPLY_GATE_CONFIRMATIONS: tuple[str, ...] = ()
HOST_SELF_INSTALL_REQUIREMENTS = (
    "host_configures_its_own_mcp_and_skill_surface",
    "host_reports_capabilities_and_identity",
    "verified_connection_receipt",
    "real_recall_then_delivery_challenge_ack",
)

# These declarations describe release-compatibility observations only. They do
# not admit clients or select onboarding/Delivery behavior.
PROFILE_COMPATIBILITY_DECLARATIONS: dict[str, dict[str, Any]] = {
    "memcore_cloud": {
        "is_time_library_service": True,
        "connectable_statuses": ("active", "detected"),
        "intent_statuses": ("active", "detected"),
        "content_gate": "not_applicable",
    },
    "claude_desktop": {
        "connectable_flag_path": ("consumer_connection", "recall_connection_ready"),
        "intent_flag_paths": (
            ("consumer_connection", "skill_detected"),
            ("consumer_connection", "mcp_detected"),
        ),
        "content_gate_path": ("read_boundary", "content_parser_gate"),
        "content_gate": "verified_format_collector_required",
        "collector_required_when_detected": True,
    },
    "codex": {
        "intent_statuses": ("active", "detected"),
        "content_gate": "verified_format_collector_required",
    },
    "openclaw": {
        "content_gate": "verified_format_collector_required",
    },
    "hermes": {
        "content_gate": "raw_pointer_consumption_only_no_platform_write",
    },
}


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_runtime_profile() -> dict[str, Any]:
    try:
        from tools.runtime_profile import build_all_profile
    except Exception:
        try:
            from runtime_profile import build_all_profile
        except Exception as exc:
            return {
                "generated_at": ts(),
                "profile_error": f"{type(exc).__name__}: {exc}",
                "memcore_cloud": {},
                "openclaw": {},
                "hermes": {},
                "claude_desktop": {},
            }
    return build_all_profile()


def _status_from_profile(profile: dict[str, Any]) -> str:
    status = str(profile.get("status") or "not_found")
    if status in {"active", "detected", "not_found"}:
        return status
    return "detected" if profile.get("instances") else "not_found"


def _instance_count(profile: dict[str, Any]) -> int:
    instances = profile.get("instances")
    return len(instances) if isinstance(instances, list) else 0


def _compatibility_declaration(system: str) -> dict[str, Any]:
    declaration = PROFILE_COMPATIBILITY_DECLARATIONS.get(str(system or ""))
    return declaration if isinstance(declaration, dict) else {}


def _profile_value(profile: dict[str, Any], path: Any) -> Any:
    current: Any = profile
    for key in path if isinstance(path, (list, tuple)) else ():
        if not isinstance(current, dict):
            return None
        current = current.get(str(key))
    return current


def _connectable_from_profile(system: str, profile: dict[str, Any]) -> bool:
    declaration = _compatibility_declaration(system)
    flag_path = declaration.get("connectable_flag_path")
    if flag_path:
        return bool(_profile_value(profile, flag_path))
    statuses = declaration.get("connectable_statuses") or ("active",)
    return _status_from_profile(profile) in set(statuses)


def _intent_signal_from_profile(system: str, profile: dict[str, Any]) -> bool:
    declaration = _compatibility_declaration(system)
    flag_paths = declaration.get("intent_flag_paths") or ()
    if flag_paths:
        return any(bool(_profile_value(profile, path)) for path in flag_paths)
    statuses = declaration.get("intent_statuses") or ()
    if statuses:
        return _status_from_profile(profile) in set(statuses)
    return _connectable_from_profile(system, profile)


def _content_gate_for_system(system: str, profile: dict[str, Any]) -> str:
    declaration = _compatibility_declaration(system)
    declared_path = declaration.get("content_gate_path")
    observed = _profile_value(profile, declared_path) if declared_path else None
    return str(observed or declaration.get("content_gate") or "not_applicable")


def _plan_for_system(system: str, profile: dict[str, Any]) -> dict[str, Any]:
    declaration = _compatibility_declaration(system)
    status = _status_from_profile(profile)
    connectable = _connectable_from_profile(system, profile)
    intent_signal = _intent_signal_from_profile(system, profile)
    actions: list[dict[str, Any]] = []
    if status == "not_found":
        actions.append({
            "action": "observe_only",
            "status": "blocked",
            "reason": "platform_not_detected",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    elif connectable:
        actions.append({
            "action": "capability_check",
            "status": "ready",
            "reason": "connection_signal_detected",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    elif intent_signal:
        actions.append({
            "action": "await_host_self_install_and_self_report",
            "status": "host_action_required",
            "reason": "skill_or_partial_connection_signal_detected",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    else:
        actions.append({
            "action": "await_host_self_install_and_self_report",
            "status": "host_action_required",
            "reason": "platform_detected_without_memcore_signal",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })

    if declaration.get("collector_required_when_detected") and status != "not_found":
        actions.append({
            "action": "verified_format_collector",
            "status": "collector_required",
            "reason": "content_bearing_browser_stores_need_a_verified_local_collector",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })

    return {
        "system": system,
        "is_time_library_service": bool(declaration.get("is_time_library_service")),
        "status": status,
        "thin_adapter": True,
        "intent_signal_detected": intent_signal,
        "connectable_now": connectable,
        "instance_count": _instance_count(profile),
        "selected_runtime": profile.get("selected_runtime"),
        "content_gate": _content_gate_for_system(system, profile),
        "actions": actions,
    }


def _fast_registry_snapshot(
    runtime_profile: dict[str, Any],
    build_thin_adapter_registry: Any,
) -> dict[str, Any]:
    if not build_thin_adapter_registry:
        return {
            "ok": False,
            "read_only": True,
            "platform_write_performed": False,
            "adapters": [],
        }
    try:
        return build_thin_adapter_registry(
            runtime_profile,
            include_generic=False,
            include_software_probe=False,
        )
    except TypeError:
        return build_thin_adapter_registry(runtime_profile)


def build_autodiscovery(runtime_profile: dict[str, Any] | None = None, *, include_generic: bool = False) -> dict[str, Any]:
    profile = runtime_profile or _load_runtime_profile()
    try:
        from platform_thin_adapter_registry import build_thin_adapter_registry, load_platform_catalog
    except Exception:
        build_thin_adapter_registry = None
        load_platform_catalog = None
    systems = {
        "memcore_cloud": profile.get("memcore_cloud") or {},
        "openclaw": profile.get("openclaw") or {},
        "hermes": profile.get("hermes") or {},
        "claude_desktop": profile.get("claude_desktop") or {},
    }
    plans = [_plan_for_system(system, data) for system, data in systems.items()]
    registry = (
        build_thin_adapter_registry(profile) if include_generic
        else _fast_registry_snapshot(profile, build_thin_adapter_registry)
    )
    catalog = load_platform_catalog() if load_platform_catalog else {"entry_count": 0, "github_watchlist_entry_count": 0}
    registered_systems = {item.get("system") for item in registry.get("adapters", [])}
    detected = [item for item in plans if item["status"] != "not_found"]
    ready = [item for item in plans if item["connectable_now"]]
    host_action_required = [
        item
        for item in plans
        if any(action.get("status") == "host_action_required" for action in item.get("actions", []))
        and item["status"] != "not_found"
    ]
    return {
        "ok": True,
        "name": CORE_NAME,
        "codename": CODENAME,
        "contract": DISCOVERY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "default_policy": "observe_compatibility_then_verify_host_self_install",
        "scan_mode": "full" if include_generic else "fast_snapshot",
        "architecture": {
            "core": "source_backed_memory_core",
            "adapter_strategy": "compatibility_observation_plus_generic_self_report",
            "adapter_registry": "platform_thin_adapter_registry",
            "skill_signal_role": "connection_signal",
            "mcp_role": "tool_connection_layer",
        },
        "counts": {
            "systems_total": len(plans),
            "systems_detected": len(detected),
            "systems_connectable_now": len(ready),
            "systems_auto_connect_ready": 0,
            "systems_host_action_required": len(host_action_required),
            "systems_needing_authorization": 0,
            "registered_thin_adapters": len(registered_systems),
            "platform_catalog_entries": catalog.get("entry_count", 0),
            "github_watchlist_entries": catalog.get("github_watchlist_entry_count", 0),
            "registered_adapters_detected": registry.get("detected_adapter_count", 0),
        },
        "systems": plans,
        "thin_adapter_registry": registry,
        "platform_catalog": {
            "contract": catalog.get("contract"),
            "catalog_version": catalog.get("catalog_version"),
            "watchlist_version": catalog.get("watchlist_version"),
            "entry_count": catalog.get("entry_count"),
            "github_watchlist_entry_count": catalog.get("github_watchlist_entry_count"),
        },
        "known_adapter_targets": sorted(system for system in registered_systems if system),
        "connection_contract": {
            "can_auto_discover": True,
            "discovery_role": "release_compatibility_observation_only",
            "default_connection_mode": "host_self_install_then_verified_self_report",
            "can_auto_connect_supported_configs": False,
            "time_library_writes_host_config": False,
            "host_owns_config_write_and_rollback": True,
            "unknown_clients_admitted_by_generic_self_report": True,
            "conversation_import_mode": "verified_format_collectors",
            "window_memory_scope_default": "current_window_first",
            "skill_installation_is_connection_signal": True,
            "receipts_required_for_writes": True,
            "backup_required_before_platform_config_write": False,
        },
        "authorization_contract": {
            "can_auto_discover": True,
            "host_self_install_receipt_required": True,
            "chat_body_parser_requires_verified_collector": True,
            "chat_body_parser_requires_separate_authorization": True,
            "time_library_platform_config_write_supported": False,
            "skill_installation_is_consent_signal": True,
            "skill_installation_is_not_body_read_consent": True,
            "receipts_required_for_writes": True,
            "backup_required_before_platform_config_write": False,
        },
        "notes": [
            "Discovery is read-only in this endpoint and may inspect local config metadata.",
            "The host agent configures its own Skill/MCP surface; Time Library verifies the connection and records a receipt.",
            "Source conversation import uses verified local format collectors.",
            "Capability check stays no-recall; real recall happens only when an agent calls recall.",
        ],
    }


def build_authorized_autoconnect_plan(runtime_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    discovery = build_autodiscovery(runtime_profile)
    planned_actions = []
    for system in discovery["systems"]:
        for action in system.get("actions", []):
            if action.get("status") == "host_action_required":
                planned_actions.append({
                    "system": system["system"],
                    **action,
                })
    for adapter in discovery.get("thin_adapter_registry", {}).get("adapters", []):
        for action in adapter.get("actions", []):
            if action.get("status") == "host_action_required":
                planned_actions.append({
                    "system": adapter["system"],
                    "display_name": adapter.get("display_name"),
                    "support_level": adapter.get("support_level"),
                    "adapter_registry_action": True,
                    **action,
                })
    return {
        "ok": True,
        "name": CORE_NAME,
        "codename": CODENAME,
        "contract": "authorized_auto_connect_plan.v1",
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "planned_action_count": len(planned_actions),
        "planned_actions": planned_actions,
        "apply_endpoint_status": "host_self_install_receipt_only",
        "required_confirmations": list(APPLY_GATE_CONFIRMATIONS),
        "required_host_actions": list(HOST_SELF_INSTALL_REQUIREMENTS),
        "default_connection_mode": "host_self_install_then_verified_self_report",
        "time_library_platform_write_supported": False,
        "does_not_admit_or_reject_clients": True,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Time Library platform autodiscovery")
    parser.add_argument("--plan", action="store_true", help="show authorized auto-connect plan")
    args = parser.parse_args()
    payload = build_authorized_autoconnect_plan() if args.plan else build_autodiscovery()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
