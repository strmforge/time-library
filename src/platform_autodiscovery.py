"""Read-only platform discovery and automatic connection planning.

Time Library / 忆凡尘 keeps the memory core platform-neutral. Platform
integrations are thin adapters: discovery observes local tool/config/storage
signals, then plans automatic native delivery/MCP connection wherever a
supported surface exists. Source conversation import still goes through
verified local format collectors.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

CORE_NAME = "Time Library"
CODENAME = "忆凡尘"
DISCOVERY_CONTRACT = "tiandao_thin_adapter_autodiscovery.v1"
APPLY_GATE_CONFIRMATIONS = (
    "confirm_user_requested_auto_connect",
    "confirm_backup_before_platform_config_write",
    "confirm_receipt_after_each_platform_write",
    "confirm_capability_check_only_after_connect",
    "confirm_no_chat_body_parser_without_separate_authorization",
)


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


def _connectable_from_profile(system: str, profile: dict[str, Any]) -> bool:
    if system == "memcore_cloud":
        return _status_from_profile(profile) in {"active", "detected"}
    if system == "claude_desktop":
        consumer = profile.get("consumer_connection") if isinstance(profile.get("consumer_connection"), dict) else {}
        return bool(consumer.get("recall_connection_ready"))
    return _status_from_profile(profile) == "active"


def _intent_signal_from_profile(system: str, profile: dict[str, Any]) -> bool:
    if system == "claude_desktop":
        consumer = profile.get("consumer_connection") if isinstance(profile.get("consumer_connection"), dict) else {}
        return bool(consumer.get("skill_detected") or consumer.get("mcp_detected"))
    if system == "codex":
        return _status_from_profile(profile) in {"active", "detected"}
    return _connectable_from_profile(system, profile)


def _content_gate_for_system(system: str, profile: dict[str, Any]) -> str:
    if system == "claude_desktop":
        read_boundary = profile.get("read_boundary") if isinstance(profile.get("read_boundary"), dict) else {}
        return str(read_boundary.get("content_parser_gate") or "verified_format_collector_required")
    if system in {"codex", "openclaw"}:
        return "verified_format_collector_required"
    if system == "hermes":
        return "raw_pointer_consumption_only_no_platform_write"
    return "not_applicable"


def _plan_for_system(system: str, profile: dict[str, Any]) -> dict[str, Any]:
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
            "action": "auto_connect_missing_thin_adapter",
            "status": "auto_connect_ready",
            "reason": "skill_or_partial_connection_signal_detected",
            "requires_user_authorization": False,
            "writes_platform_config": True,
        })
    else:
        actions.append({
            "action": "auto_connect",
            "status": "auto_connect_ready",
            "reason": "platform_detected_without_memcore_signal",
            "requires_user_authorization": False,
            "writes_platform_config": True,
        })

    if system == "claude_desktop" and status != "not_found":
        actions.append({
            "action": "verified_format_collector",
            "status": "collector_required",
            "reason": "content_bearing_browser_stores_need_a_verified_local_collector",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })

    return {
        "system": system,
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
    auto_connect_ready = [
        item
        for item in plans
        if any(action.get("status") == "auto_connect_ready" for action in item.get("actions", []))
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
        "default_policy": "auto_discover_and_auto_connect_supported_surfaces",
        "scan_mode": "full" if include_generic else "fast_snapshot",
        "architecture": {
            "core": "source_backed_memory_core",
            "adapter_strategy": "tiandao_plus_thin_adapters",
            "adapter_registry": "platform_thin_adapter_registry",
            "skill_signal_role": "connection_signal",
            "mcp_role": "tool_connection_layer",
        },
        "counts": {
            "systems_total": len(plans),
            "systems_detected": len(detected),
            "systems_connectable_now": len(ready),
            "systems_auto_connect_ready": len(auto_connect_ready),
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
            "default_connection_mode": "auto_discover_and_auto_connect",
            "can_auto_connect_supported_configs": True,
            "conversation_import_mode": "verified_format_collectors",
            "window_memory_scope_default": "current_window_first",
            "skill_installation_is_connection_signal": True,
            "receipts_required_for_writes": True,
            "backup_required_before_platform_config_write": True,
        },
        "authorization_contract": {
            "can_auto_discover": True,
            "auto_connect_requires_user_or_installer_approval": True,
            "chat_body_parser_requires_verified_collector": True,
            "chat_body_parser_requires_separate_authorization": True,
            "platform_config_write_requires_authorized_apply": True,
            "skill_installation_is_consent_signal": True,
            "skill_installation_is_not_body_read_consent": True,
            "receipts_required_for_writes": True,
            "backup_required_before_platform_config_write": True,
        },
        "notes": [
            "Discovery is read-only in this endpoint and may inspect local config metadata.",
            "Installers and apply endpoints can auto-connect supported Skill/MCP surfaces with backup and receipt.",
            "Source conversation import uses verified local format collectors.",
            "Capability check stays no-recall; real recall happens only when an agent calls recall.",
        ],
    }


def build_authorized_autoconnect_plan(runtime_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    discovery = build_autodiscovery(runtime_profile)
    planned_actions = []
    for system in discovery["systems"]:
        for action in system.get("actions", []):
            if action.get("status") == "auto_connect_ready":
                planned_actions.append({
                    "system": system["system"],
                    **action,
                })
    for adapter in discovery.get("thin_adapter_registry", {}).get("adapters", []):
        for action in adapter.get("actions", []):
            if action.get("status") == "auto_connect_ready":
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
        "apply_endpoint_status": "implemented_by_platform_auto_connect_endpoints",
        "required_confirmations": list(APPLY_GATE_CONFIRMATIONS),
        "default_connection_mode": "auto_discover_and_auto_connect",
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
