"""Continuous local chat sync contract.

This module is intentionally status-only. It answers one product question:
after install, does Memcore keep watching for new local conversation records,
or did it only scan once?
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config_loader import get as config_get

UTC = timezone.utc
CONTINUOUS_SYNC_CONTRACT = "continuous_local_chat_sync.v1"
WATCHER_POLL_INTERVAL_SECONDS = 5


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _int_setting(env_name: str, config_path: str, default: int, minimum: int = 1, maximum: int = 3600) -> int:
    raw = os.environ.get(env_name)
    if raw is None:
        raw = config_get(config_path, default)
    try:
        value = int(raw)
    except Exception:
        value = default
    return max(minimum, min(value, maximum))


def claude_desktop_raw_ingest_enabled() -> bool:
    if "MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED" in os.environ:
        return _truthy(os.environ.get("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED"))
    return _truthy(config_get("integrations.claude_desktop.raw_ingest.enabled", True))


def claude_desktop_raw_ingest_interval_seconds() -> int:
    return _int_setting(
        "MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS",
        "integrations.claude_desktop.raw_ingest.interval_seconds",
        WATCHER_POLL_INTERVAL_SECONDS,
        minimum=WATCHER_POLL_INTERVAL_SECONDS,
        maximum=3600,
    )


def _safe_connector_status(module_name: str) -> dict[str, Any]:
    try:
        module = __import__(module_name)
        status = module.status()
        return status if isinstance(status, dict) else {"ok": False, "error": "status_not_object"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:160]}"}


def _source(
    *,
    source_system: str,
    native_artifact_format: str,
    collector_status: str,
    poll_interval_seconds: int,
    enabled: bool = True,
    reachable: bool | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail = details or {}
    if reachable is None:
        reachable = bool(detail.get("reachable", False))
    return {
        "source_system": source_system,
        "native_artifact_format": native_artifact_format,
        "enabled_in_p0_watcher": enabled,
        "collector_status": collector_status,
        "continuous": enabled and collector_status in {
            "continuous_incremental",
            "continuous_incremental_json_snapshot",
            "periodic_authorized_raw_ingest",
        },
        "poll_interval_seconds": poll_interval_seconds,
        "near_real_time": enabled and poll_interval_seconds <= WATCHER_POLL_INTERVAL_SECONDS,
        "incremental": collector_status in {"continuous_incremental", "continuous_incremental_json_snapshot"},
        "p2_incremental_after_raw_write": source_system in {"openclaw", "codex", "kiro"},
        "reachable": bool(reachable),
        "status_detail": detail,
    }


def _pending_collectors(include_generic: bool) -> list[dict[str, Any]]:
    if not include_generic:
        return []
    try:
        from platform_thin_adapter_registry import build_platform_discovery_dashboard

        dashboard = build_platform_discovery_dashboard(include_generic=True, public=False)
    except Exception:
        return []

    pending: list[dict[str, Any]] = []
    implemented = {"openclaw", "codex", "claude_desktop", "kiro"}
    for item in dashboard.get("items", []):
        if not isinstance(item, dict):
            continue
        system = str(item.get("system") or "")
        if not system or system in implemented:
            continue
        boundary = item.get("conversation_memory_boundary") if isinstance(item.get("conversation_memory_boundary"), dict) else {}
        if not item.get("content_bearing_store_detected") and not boundary.get("complete_conversation_candidate"):
            continue
        pending.append({
            "source_system": system,
            "display_name": item.get("display_name") or system,
            "collector_status": "collector_pending",
            "continuous": False,
            "near_real_time": False,
            "reason": "storage_shape_detected_without_verified_continuous_collector",
            "complete_conversation_candidate": bool(boundary.get("complete_conversation_candidate")),
            "assistant_replies_may_persist": boundary.get("assistant_replies_may_persist", "unknown"),
            "safe_next_step": "add_verified_collector_then_enable_p0_watch",
        })
    return pending


def build_continuous_sync_status(
    *,
    watcher_active: bool | None = None,
    include_generic: bool = True,
) -> dict[str, Any]:
    codex_status = _safe_connector_status("codex_local_connector")
    kiro_status = _safe_connector_status("kiro_local_connector")
    claude_enabled = claude_desktop_raw_ingest_enabled()
    sources = [
        _source(
            source_system="openclaw",
            native_artifact_format="openclaw_session_jsonl",
            collector_status="continuous_incremental",
            poll_interval_seconds=WATCHER_POLL_INTERVAL_SECONDS,
            enabled=True,
            reachable=True,
            details={"watcher_mode": "inotify_or_poll_fallback", "source_root": "configured_openclaw_agents"},
        ),
        _source(
            source_system="codex",
            native_artifact_format="codex_session_jsonl",
            collector_status="continuous_incremental",
            poll_interval_seconds=WATCHER_POLL_INTERVAL_SECONDS,
            enabled=True,
            details=codex_status,
        ),
        _source(
            source_system="kiro",
            native_artifact_format="kiro_workspace_sessions_json",
            collector_status="continuous_incremental_json_snapshot",
            poll_interval_seconds=WATCHER_POLL_INTERVAL_SECONDS,
            enabled=True,
            details=kiro_status,
        ),
        _source(
            source_system="claude_desktop",
            native_artifact_format="claude_desktop_authorized_local_store_jsonl",
            collector_status="periodic_authorized_raw_ingest" if claude_enabled else "disabled",
            poll_interval_seconds=claude_desktop_raw_ingest_interval_seconds(),
            enabled=claude_enabled,
            details={
                "raw_ingest_enabled": claude_enabled,
                "parser_gate": "authorized_local_store_parser",
                "writes_platform_config": False,
            },
        ),
    ]
    pending = _pending_collectors(include_generic)
    active_sources = [item for item in sources if item["enabled_in_p0_watcher"] and item["continuous"]]
    return {
        "ok": True,
        "contract": CONTINUOUS_SYNC_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "watcher": {
            "active": watcher_active,
            "installed_as": "p0-watcher",
            "mode": "continuous_loop",
            "base_poll_interval_seconds": WATCHER_POLL_INTERVAL_SECONDS,
            "install_scan_only": False,
        },
        "summary": {
            "continuous_source_count": len(active_sources),
            "near_real_time_source_count": sum(1 for item in active_sources if item["near_real_time"]),
            "collector_pending_count": len(pending),
            "universal_seconds_level_sync": False,
            "truth_label": "continuous_core_watchers_plus_pending_collectors",
        },
        "sources": sources,
        "collector_pending": pending,
        "contract_notes": [
            "Install starts a persistent p0 watcher; it is not a one-time scan.",
            "OpenClaw, Codex, and Kiro are polled every 5 seconds for new local records.",
            "Claude Desktop authorized raw ingest now defaults to the same 5 second cadence when enabled.",
            "Detected tools without verified collectors are visible as collector_pending and must not be described as already synced.",
        ],
    }


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Memcore continuous local chat sync status")
    parser.add_argument("--fast", action="store_true", help="skip generic pending collector scan")
    args = parser.parse_args()
    print(json.dumps(build_continuous_sync_status(include_generic=not args.fast), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
