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
try:
    from src.tiandao.memory_routing import (
        DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS,
        SYNC_INSTALL_SCAN_ONLY,
        SYNC_MODE_FILE_EVENT_OR_LOW_LATENCY,
        TIANDAO_CONTINUOUS_LOCAL_SYNC_CONTRACT,
        continuous_local_sync_contract_descriptor,
    )
except Exception:
    from tiandao.memory_routing import (
        DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS,
        SYNC_INSTALL_SCAN_ONLY,
        SYNC_MODE_FILE_EVENT_OR_LOW_LATENCY,
        TIANDAO_CONTINUOUS_LOCAL_SYNC_CONTRACT,
        continuous_local_sync_contract_descriptor,
    )

UTC = timezone.utc
CONTINUOUS_SYNC_CONTRACT = "continuous_local_chat_sync.v1"
DEFAULT_SYNC_INTERVAL_MS = DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS
MIN_SYNC_INTERVAL_MS = 50
MAX_SYNC_INTERVAL_MS = 3_600_000


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


def _milliseconds_setting(
    env_ms_name: str,
    config_ms_path: str,
    default_ms: int,
    *,
    legacy_env_seconds_name: str = "",
    legacy_config_seconds_path: str = "",
    minimum: int = MIN_SYNC_INTERVAL_MS,
    maximum: int = MAX_SYNC_INTERVAL_MS,
) -> int:
    raw = os.environ.get(env_ms_name)
    if raw is None:
        raw = config_get(config_ms_path, None)
    if raw is None and legacy_env_seconds_name:
        raw_seconds = os.environ.get(legacy_env_seconds_name)
        if raw_seconds is not None:
            try:
                raw = int(float(raw_seconds) * 1000)
            except Exception:
                raw = None
    if raw is None and legacy_config_seconds_path:
        raw_seconds = config_get(legacy_config_seconds_path, None)
        if raw_seconds is not None:
            try:
                raw = int(float(raw_seconds) * 1000)
            except Exception:
                raw = None
    try:
        value = int(float(raw if raw is not None else default_ms))
    except Exception:
        value = default_ms
    return max(minimum, min(value, maximum))


def watcher_interval_milliseconds() -> int:
    return _milliseconds_setting(
        "MEMCORE_WATCHER_INTERVAL_MS",
        "services.p0_watcher_interval_milliseconds",
        DEFAULT_SYNC_INTERVAL_MS,
        legacy_env_seconds_name="MEMCORE_WATCHER_POLL_INTERVAL_SECONDS",
    )


def claude_desktop_raw_ingest_enabled() -> bool:
    if "MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED" in os.environ:
        return _truthy(os.environ.get("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED"))
    return _truthy(config_get("integrations.claude_desktop.raw_ingest.enabled", True))


def claude_desktop_raw_ingest_interval_milliseconds() -> int:
    return _milliseconds_setting(
        "MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_MS",
        "integrations.claude_desktop.raw_ingest.interval_milliseconds",
        DEFAULT_SYNC_INTERVAL_MS,
        legacy_env_seconds_name="MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS",
    )


def hermes_raw_backfill_enabled() -> bool:
    if "MEMCORE_HERMES_RAW_BACKFILL_ENABLED" in os.environ:
        return _truthy(os.environ.get("MEMCORE_HERMES_RAW_BACKFILL_ENABLED"))
    return _truthy(config_get("integrations.hermes.raw_backfill.enabled", True))


def _safe_connector_status(module_name: str) -> dict[str, Any]:
    try:
        module = __import__(module_name)
        status = module.status()
        return status if isinstance(status, dict) else {"ok": False, "error": "status_not_object"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:160]}"}


def file_event_backend_status() -> dict[str, Any]:
    try:
        from watchdog.observers import Observer
    except Exception as exc:
        return {
            "available": False,
            "backend": "unavailable",
            "error": f"{type(exc).__name__}:{str(exc)[:120]}",
        }
    return {
        "available": True,
        "backend": getattr(Observer, "__module__", "watchdog.observers"),
    }


def _source(
    *,
    source_system: str,
    native_artifact_format: str,
    collector_status: str,
    poll_interval_milliseconds: int,
    enabled: bool = True,
    event_driven_preferred: bool = True,
    event_driven_active: bool | None = None,
    event_backend: str = "",
    watcher_active: bool | None = None,
    fallback_poll_interval_milliseconds: int | None = None,
    reachable: bool | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail = details or {}
    if reachable is None:
        reachable = bool(detail.get("reachable", False))
    raw_sync = detail.get("raw_sync") if isinstance(detail.get("raw_sync"), dict) else {}
    poll_interval_seconds = poll_interval_milliseconds / 1000.0
    millisecond_level = enabled and poll_interval_milliseconds < 1000
    active = bool(enabled and collector_status in {
        "continuous_incremental",
        "continuous_incremental_json_snapshot",
        "periodic_authorized_raw_ingest",
    })
    if watcher_active is False:
        active = False
    lagging = raw_sync.get("status") in {"raw_missing", "raw_lagging_sla_breach"} if raw_sync else False
    catching_up = raw_sync.get("status") == "raw_catching_up" if raw_sync else False
    health = "ok"
    if enabled and watcher_active is False:
        health = "watcher_inactive"
    if lagging:
        health = "raw_lagging"
    elif catching_up:
        health = "raw_catching_up"
    return {
        "source_system": source_system,
        "native_artifact_format": native_artifact_format,
        "enabled_in_p0_watcher": enabled,
        "collector_status": collector_status,
        "continuous": active,
        "declared_continuous": enabled and collector_status in {
            "continuous_incremental",
            "continuous_incremental_json_snapshot",
            "periodic_authorized_raw_ingest",
        },
        "sync_health": health,
        "event_driven_preferred": bool(event_driven_preferred),
        "event_driven_available": bool(event_backend),
        "event_driven_active": event_driven_active,
        "event_backend": event_backend,
        "fallback_poll_interval_milliseconds": fallback_poll_interval_milliseconds
        if fallback_poll_interval_milliseconds is not None
        else poll_interval_milliseconds,
        "poll_interval_milliseconds": poll_interval_milliseconds,
        "poll_interval_seconds": poll_interval_seconds,
        "target_latency_milliseconds": poll_interval_milliseconds,
        "millisecond_level": millisecond_level,
        "near_real_time": active and poll_interval_milliseconds <= 1000,
        "incremental": collector_status in {"continuous_incremental", "continuous_incremental_json_snapshot"},
        "p2_incremental_after_raw_write": source_system in {"openclaw", "codex", "claude_code_cli", "kiro"},
        "reachable": bool(reachable),
        "capture_independent_of_mcp": source_system in {"codex", "claude_code_cli"},
        "consumer_connection_required": False if source_system in {"codex", "claude_code_cli"} else None,
        "raw_sync": raw_sync,
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
    implemented = {"openclaw", "codex", "claude_code_cli", "claude_desktop", "kiro"}
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
    claude_code_status = _safe_connector_status("claude_code_local_connector")
    kiro_status = _safe_connector_status("kiro_local_connector")
    claude_status = _safe_connector_status("claude_desktop_connector")
    hermes_status = _safe_connector_status("raw_record_guardian")
    claude_enabled = claude_desktop_raw_ingest_enabled()
    hermes_enabled = hermes_raw_backfill_enabled()
    interval_ms = watcher_interval_milliseconds()
    claude_interval_ms = claude_desktop_raw_ingest_interval_milliseconds()
    event_backend = file_event_backend_status()
    event_available = bool(event_backend.get("available"))
    event_backend_name = str(event_backend.get("backend") or "")
    event_active = bool(watcher_active) and event_available if watcher_active is not None else None
    sources = [
        _source(
            source_system="openclaw",
            native_artifact_format="openclaw_session_jsonl",
            collector_status="continuous_incremental",
            poll_interval_milliseconds=interval_ms,
            enabled=True,
            reachable=True,
            event_driven_preferred=True,
            event_driven_active=event_active,
            event_backend=event_backend_name if event_available else "",
            watcher_active=watcher_active,
            fallback_poll_interval_milliseconds=interval_ms,
            details={"watcher_mode": "file_event_or_low_latency_poll", "source_root": "configured_openclaw_agents"},
        ),
        _source(
            source_system="codex",
            native_artifact_format="codex_session_jsonl",
            collector_status="continuous_incremental",
            poll_interval_milliseconds=interval_ms,
            enabled=True,
            event_driven_preferred=True,
            event_driven_active=event_active,
            event_backend=event_backend_name if event_available else "",
            watcher_active=watcher_active,
            fallback_poll_interval_milliseconds=interval_ms,
            details=codex_status,
        ),
        _source(
            source_system="claude_code_cli",
            native_artifact_format="claude_code_session_jsonl",
            collector_status="continuous_incremental",
            poll_interval_milliseconds=interval_ms,
            enabled=True,
            event_driven_preferred=True,
            event_driven_active=event_active,
            event_backend=event_backend_name if event_available else "",
            watcher_active=watcher_active,
            fallback_poll_interval_milliseconds=interval_ms,
            details=claude_code_status,
        ),
        _source(
            source_system="kiro",
            native_artifact_format="kiro_workspace_sessions_json",
            collector_status="continuous_incremental_json_snapshot",
            poll_interval_milliseconds=int(kiro_status.get("poll_interval_milliseconds") or interval_ms),
            enabled=True,
            event_driven_preferred=True,
            event_driven_active=event_active,
            event_backend=event_backend_name if event_available else "",
            watcher_active=watcher_active,
            fallback_poll_interval_milliseconds=interval_ms,
            details=kiro_status,
        ),
        _source(
            source_system="claude_desktop",
            native_artifact_format="claude_desktop_authorized_local_store_jsonl",
            collector_status="periodic_authorized_raw_ingest" if claude_enabled else "disabled",
            poll_interval_milliseconds=claude_interval_ms,
            enabled=claude_enabled,
            event_driven_preferred=True,
            event_driven_active=event_active if claude_enabled else False,
            event_backend=event_backend_name if event_available else "",
            watcher_active=watcher_active if claude_enabled else False,
            fallback_poll_interval_milliseconds=claude_interval_ms,
            details={
                "raw_ingest_enabled": claude_enabled,
                "parser_gate": "authorized_local_store_parser",
                "writes_platform_config": False,
                "connector_status": claude_status,
                "raw_body_readiness": claude_status.get("raw_body_readiness", ""),
                "current_window_memory_registerable": bool(claude_status.get("current_window_memory_registerable")),
                "assistant_reply_persistence": (
                    (claude_status.get("local_storage") or {}).get("assistant_reply_persistence")
                    if isinstance(claude_status.get("local_storage"), dict)
                    else ""
                ),
            },
        ),
        _source(
            source_system="hermes",
            native_artifact_format="hermes_state_db_messages_jsonl",
            collector_status="continuous_incremental" if hermes_enabled else "disabled",
            poll_interval_milliseconds=interval_ms,
            enabled=hermes_enabled,
            event_driven_preferred=True,
            event_driven_active=event_active if hermes_enabled else False,
            event_backend=event_backend_name if event_available else "",
            watcher_active=watcher_active if hermes_enabled else False,
            fallback_poll_interval_milliseconds=interval_ms,
            reachable=True,
            details={
                "source_storage": "sqlite_state_db",
                "parser_gate": "read_only_sqlite_messages_exporter",
                "writes_platform_config": False,
                "platform_write_performed": False,
                "connector_status": hermes_status,
            },
        ),
    ]
    pending = _pending_collectors(include_generic)
    active_sources = [item for item in sources if item["enabled_in_p0_watcher"] and item["continuous"]]
    declared_sources = [item for item in sources if item["enabled_in_p0_watcher"] and item["declared_continuous"]]
    lagging_sources = [item for item in sources if item.get("sync_health") == "raw_lagging"]
    inactive_sources = [item for item in sources if item.get("sync_health") == "watcher_inactive"]
    return {
        "ok": True,
        "contract": CONTINUOUS_SYNC_CONTRACT,
        "tiandao_contract": TIANDAO_CONTINUOUS_LOCAL_SYNC_CONTRACT,
        "tiandao_sync_contract": continuous_local_sync_contract_descriptor(),
        "generated_at": ts(),
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "watcher": {
            "active": watcher_active,
            "required_for_local_capture": True,
            "installed_as": "p0-watcher",
            "mode": SYNC_MODE_FILE_EVENT_OR_LOW_LATENCY,
            "event_driven_preferred": True,
            "event_driven_available": event_available,
            "event_driven_active": event_active,
            "event_backend": event_backend_name,
            "event_backend_status": event_backend,
            "base_poll_interval_milliseconds": interval_ms,
            "base_poll_interval_seconds": interval_ms / 1000.0,
            "fallback_poll_interval_milliseconds": interval_ms,
            "target_latency_milliseconds": interval_ms,
            "install_scan_only": SYNC_INSTALL_SCAN_ONLY,
        },
        "summary": {
            "continuous_source_count": len(active_sources),
            "declared_continuous_source_count": len(declared_sources),
            "near_real_time_source_count": sum(1 for item in active_sources if item["near_real_time"]),
            "millisecond_level_source_count": sum(1 for item in active_sources if item["millisecond_level"]),
            "collector_pending_count": len(pending),
            "raw_lagging_source_count": len(lagging_sources),
            "watcher_inactive_source_count": len(inactive_sources),
            "universal_seconds_level_sync": False,
            "core_millisecond_level_sync": bool(active_sources)
            and all(item["millisecond_level"] for item in active_sources),
            "local_capture_ok": watcher_active is not False and not lagging_sources,
            "truth_label": "event_driven_preferred_millisecond_core_watchers_plus_pending_collectors",
        },
        "sources": sources,
        "collector_pending": pending,
        "contract_notes": [
            "Install starts a persistent p0 watcher; it is not a one-time scan.",
            "Core sources target millisecond-level sync through file events where available and low-latency polling as fallback.",
            "Claude Desktop authorized raw ingest follows the same millisecond-level target when enabled.",
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
