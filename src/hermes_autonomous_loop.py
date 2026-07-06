#!/usr/bin/env python3
"""Value-gated Hermes autonomous native-learning loop.

The loop owns scheduling decisions and receipts only. Time Library may trigger
Hermes with explicit authorization and observe Hermes-owned skill artifacts, but
it never writes Hermes skills or production experience records itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from .hermes_native_liveness import _resolve_hermes_cli, trigger_hermes_skill_generation_probe
    from .hermes_skill_experience_diff import build_hermes_skill_experience_diff_dry_run
    from .raw_recall_catalog_index import records_db_path_for_gateway
    from .source_system_runtime_declarations import (
        source_system_generation_cadence,
        source_system_generation_model_hint,
        source_system_generation_scope,
        source_system_native_generation_trigger_kind,
    )
except Exception:  # pragma: no cover - direct import fallback
    from hermes_native_liveness import _resolve_hermes_cli, trigger_hermes_skill_generation_probe
    from hermes_skill_experience_diff import build_hermes_skill_experience_diff_dry_run
    from raw_recall_catalog_index import records_db_path_for_gateway
    from source_system_runtime_declarations import (
        source_system_generation_cadence,
        source_system_generation_model_hint,
        source_system_generation_scope,
        source_system_native_generation_trigger_kind,
    )


HERMES_AUTONOMOUS_LOOP_SCHEMA_VERSION = "2026.7.1"
DEFAULT_SOURCE_SYSTEM = "hermes"
DEFAULT_MAX_TRIGGERS_PER_CYCLE = 1
DEFAULT_EMPTY_BACKOFF_THRESHOLD = 2
DEFAULT_BASE_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_MAX_BACKOFF_MULTIPLIER = 16
DEFAULT_BACKGROUND_LABEL = "com.memcorecloud.hermes-autonomous-loop"
DEFAULT_BACKGROUND_START_INTERVAL_SECONDS = 60 * 60
DEFAULT_BACKGROUND_DAILY_TRIGGER_BUDGET = 1
DEFAULT_BACKGROUND_DAILY_SPEND_BUDGET = 1


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any, default: int, minimum: int = 0, maximum: int = 10_000_000) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "confirm", "confirmed"}
    return bool(value)


def _sha_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _iso_from_epoch(value: float | int | None) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(float(value), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_from_iso(value: Any) -> float:
    text = _clean_text(value)
    if not text:
        return 0.0
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _loop_root(memcore_root: str | Path | None) -> Path | None:
    if not memcore_root:
        return None
    return Path(memcore_root).expanduser() / "output" / "hermes_native_learning" / "autonomous_loop"


def _state_path(memcore_root: str | Path | None) -> Path | None:
    root = _loop_root(memcore_root)
    return root / "state.json" if root else None


def _runs_dir(memcore_root: str | Path | None) -> Path | None:
    root = _loop_root(memcore_root)
    return root / "runs" if root else None


def _background_config_path(memcore_root: str | Path | None) -> Path | None:
    root = _loop_root(memcore_root)
    return root / "background.json" if root else None


def _background_state_path(memcore_root: str | Path | None) -> Path | None:
    root = _loop_root(memcore_root)
    return root / "background_state.json" if root else None


def _background_ticks_dir(memcore_root: str | Path | None) -> Path | None:
    root = _loop_root(memcore_root)
    return root / "background_ticks" if root else None


def _read_json(path: Path | None) -> tuple[dict[str, Any], str]:
    if path is None:
        return {}, "path_required"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "not_found"
    except Exception as exc:
        return {}, f"read_failed:{str(exc)[:120]}"
    if not isinstance(data, dict):
        return {}, "not_object"
    return data, ""


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _day_key(epoch: float | None = None) -> str:
    value = time.time() if epoch is None else float(epoch)
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d")


def _records_db_snapshot(source_system: str, *, memcore_root: str | Path | None = None) -> dict[str, Any]:
    try:
        db_path = Path(memcore_root).expanduser() / "output" / "records" / "records.db" if memcore_root else records_db_path_for_gateway()
    except Exception:
        db_path = None
    result: dict[str, Any] = {
        "kind": "records_db",
        "path": str(db_path) if db_path else "",
        "exists": bool(db_path and db_path.exists()),
        "source_system": source_system,
        "records_count": 0,
        "canonical_session_count": 0,
        "canonical_message_count": 0,
        "latest_updated_at": "",
        "latest_raw_mtime": "",
        "latest_source_mtime": "",
        "latest_message_timestamp": "",
        "error": "",
    }
    if not result["exists"]:
        result["token"] = _sha_json(result)
        return result
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.2)
        try:
            row = conn.execute(
                """
                select count(*), max(updated_at), max(raw_mtime), max(source_mtime)
                from records
                where source_system = ?
                """,
                (source_system,),
            ).fetchone()
            if row:
                result["records_count"] = int(row[0] or 0)
                result["latest_updated_at"] = row[1] or ""
                result["latest_raw_mtime"] = row[2] or ""
                result["latest_source_mtime"] = row[3] or ""
            row = conn.execute(
                """
                select count(*)
                from canonical_sessions
                where source_system = ?
                """,
                (source_system,),
            ).fetchone()
            if row:
                result["canonical_session_count"] = int(row[0] or 0)
            row = conn.execute(
                """
                select count(*), max(updated_at), max(timestamp)
                from canonical_messages
                where source_system = ?
                """,
                (source_system,),
            ).fetchone()
            if row:
                result["canonical_message_count"] = int(row[0] or 0)
                if row[1] and row[1] > result.get("latest_updated_at", ""):
                    result["latest_updated_at"] = row[1]
                result["latest_message_timestamp"] = row[2] or ""
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "no such table" in message or "no such column" in message:
            result["error"] = "records_db_schema_missing"
        elif "locked" in message or "busy" in message:
            result["error"] = "records_db_busy"
        else:
            result["error"] = "records_db_error"
    except Exception as exc:
        result["error"] = f"records_db_error:{str(exc)[:120]}"
    result["token"] = _sha_json({
        "source_system": source_system,
        "records_count": result["records_count"],
        "canonical_session_count": result["canonical_session_count"],
        "canonical_message_count": result["canonical_message_count"],
        "latest_updated_at": result["latest_updated_at"],
        "latest_raw_mtime": result["latest_raw_mtime"],
        "latest_source_mtime": result["latest_source_mtime"],
        "latest_message_timestamp": result["latest_message_timestamp"],
        "error": result["error"],
    })
    return result


def _raw_files_snapshot(memcore_root: str | Path | None, source_system: str, *, max_paths: int = 8) -> dict[str, Any]:
    root = Path(memcore_root).expanduser() if memcore_root else None
    memory_root = root / "memory" if root else None
    result: dict[str, Any] = {
        "kind": "memory_raw_files",
        "memory_root": str(memory_root) if memory_root else "",
        "exists": bool(memory_root and memory_root.exists()),
        "source_system": source_system,
        "file_count": 0,
        "total_bytes": 0,
        "latest_mtime_epoch": 0.0,
        "latest_mtime": "",
        "latest_path": "",
        "sample_paths": [],
        "error": "",
    }
    signatures: list[str] = []
    if not memory_root or not memory_root.exists():
        result["token"] = _sha_json(result)
        return result
    try:
        paths = [
            path for path in memory_root.rglob("*.jsonl")
            if path.is_file() and source_system in path.parts
        ]
        paths.sort()
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            result["file_count"] += 1
            result["total_bytes"] += int(stat.st_size)
            mtime = float(stat.st_mtime)
            if mtime >= float(result["latest_mtime_epoch"] or 0):
                result["latest_mtime_epoch"] = mtime
                result["latest_mtime"] = _iso_from_epoch(mtime)
                result["latest_path"] = str(path)
            try:
                rel = path.relative_to(memory_root).as_posix()
            except Exception:
                rel = str(path)
            signatures.append(f"{rel}|{int(stat.st_size)}|{int(getattr(stat, 'st_mtime_ns', int(mtime * 1_000_000_000)))}")
        result["sample_paths"] = signatures[-max_paths:]
    except Exception as exc:
        result["error"] = f"raw_file_scan_error:{str(exc)[:120]}"
    result["token"] = hashlib.sha256("\n".join(signatures).encode("utf-8")).hexdigest()
    return result


def build_hermes_raw_watermark(
    *,
    memcore_root: str | Path | None = None,
    source_system: str = DEFAULT_SOURCE_SYSTEM,
) -> dict[str, Any]:
    source = _clean_text(source_system) or DEFAULT_SOURCE_SYSTEM
    records = _records_db_snapshot(source, memcore_root=memcore_root)
    raw_files = _raw_files_snapshot(memcore_root, source)
    source_event_count = int(records.get("records_count", 0) or 0) + int(raw_files.get("file_count", 0) or 0)
    canonical_event_count = int(records.get("canonical_message_count", 0) or 0)
    token = _sha_json({
        "source_system": source,
        "records": records.get("token", ""),
        "raw_files": raw_files.get("token", ""),
    })
    latest = max(
        [
            _clean_text(records.get("latest_updated_at")),
            _clean_text(records.get("latest_raw_mtime")),
            _clean_text(records.get("latest_source_mtime")),
            _clean_text(records.get("latest_message_timestamp")),
            _clean_text(raw_files.get("latest_mtime")),
        ]
    )
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "source_system": source,
        "watermark_token": token,
        "source_event_count": source_event_count,
        "canonical_event_count": canonical_event_count,
        "latest_observed_at": latest,
        "records_db": records,
        "raw_files": raw_files,
        "raw_authority_note": "records_db_is_derived_index; memory_raw_files_are_used_as_source-side_change_signal",
    }


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": HERMES_AUTONOMOUS_LOOP_SCHEMA_VERSION,
        "last_raw_watermark_token": "",
        "last_raw_watermark": {},
        "consecutive_empty_outputs": 0,
        "backoff_multiplier": 1,
        "cadence_state": "baseline",
        "recommended_next_interval_seconds": DEFAULT_BASE_INTERVAL_SECONDS,
        "total_trigger_count": 0,
        "total_hermes_spend_units": 0,
        "last_run_id": "",
        "last_outcome": "",
        "updated_at": "",
    }


def load_hermes_autonomous_loop_state(
    *,
    memcore_root: str | Path | None = None,
) -> dict[str, Any]:
    path = _state_path(memcore_root)
    state, error = _read_json(path)
    if error:
        state = _empty_state()
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "state_path": str(path) if path else "",
        "state_exists": bool(path and path.exists()),
        "state_read_error": "" if error == "not_found" else error,
        "state": state,
    }


def build_default_hermes_background_config(
    *,
    memcore_root: str | Path | None = None,
    install_root: str | Path | None = None,
    python_bin: str | Path | None = None,
    label: str = DEFAULT_BACKGROUND_LABEL,
) -> dict[str, Any]:
    root = str(Path(memcore_root).expanduser()) if memcore_root else ""
    install = str(Path(install_root).expanduser()) if install_root else root
    py = str(Path(python_bin).expanduser()) if python_bin else (
        str(Path(install) / ".venv" / "bin" / "python") if install else ""
    )
    return {
        "schema_version": HERMES_AUTONOMOUS_LOOP_SCHEMA_VERSION,
        "enabled": True,
        "label": _clean_text(label) or DEFAULT_BACKGROUND_LABEL,
        "memcore_root": root,
        "install_root": install,
        "python_bin": py,
        "source_system": DEFAULT_SOURCE_SYSTEM,
        "start_interval_seconds": DEFAULT_BACKGROUND_START_INTERVAL_SECONDS,
        "minimum_interval_seconds": DEFAULT_BASE_INTERVAL_SECONDS,
        "daily_trigger_budget": DEFAULT_BACKGROUND_DAILY_TRIGGER_BUDGET,
        "daily_spend_budget": DEFAULT_BACKGROUND_DAILY_SPEND_BUDGET,
        "max_triggers_per_tick": DEFAULT_MAX_TRIGGERS_PER_CYCLE,
        "empty_backoff_threshold": DEFAULT_EMPTY_BACKOFF_THRESHOLD,
        "base_interval_seconds": DEFAULT_BASE_INTERVAL_SECONDS,
        "max_backoff_multiplier": DEFAULT_MAX_BACKOFF_MULTIPLIER,
        "allow_first_run_bootstrap": False,
        "auto_production_adoption_allowed": False,
        "candidate_delivery": "dry_run_receipt_and_runs_endpoint",
        "receipt_layer": "installed_runtime_background_tick",
        "time_rule_decision": {
            "decision": "attached",
            "rule_ids": [
                "each_runtime_first_witnessed_raw",
                "derived_sediment_must_reference_origin",
                "platforms_are_inlets_not_origin",
                "events_remain_orderable",
            ],
        },
        "non_claims": [
            "background_tick_does_not_auto_adopt_production_experience",
            "background_tick_does_not_write_hermes_skill_by_time_library",
            "launchd_interval_is_wakeup_only_value_gate_controls_spend",
        ],
    }


def _coerce_hermes_background_config(config: dict[str, Any]) -> dict[str, Any]:
    coerced = dict(config)
    coerced["enabled"] = _truthy(coerced.get("enabled"))
    coerced["start_interval_seconds"] = _safe_int(
        coerced.get("start_interval_seconds"),
        DEFAULT_BACKGROUND_START_INTERVAL_SECONDS,
        300,
        7 * 24 * 60 * 60,
    )
    coerced["minimum_interval_seconds"] = _safe_int(
        coerced.get("minimum_interval_seconds"),
        DEFAULT_BASE_INTERVAL_SECONDS,
        60,
        90 * 24 * 60 * 60,
    )
    coerced["daily_trigger_budget"] = _safe_int(
        coerced.get("daily_trigger_budget"),
        DEFAULT_BACKGROUND_DAILY_TRIGGER_BUDGET,
        0,
        20,
    )
    coerced["daily_spend_budget"] = _safe_int(
        coerced.get("daily_spend_budget"),
        DEFAULT_BACKGROUND_DAILY_SPEND_BUDGET,
        0,
        20,
    )
    coerced["max_triggers_per_tick"] = _safe_int(
        coerced.get("max_triggers_per_tick"),
        DEFAULT_MAX_TRIGGERS_PER_CYCLE,
        0,
        5,
    )
    coerced["empty_backoff_threshold"] = _safe_int(
        coerced.get("empty_backoff_threshold"),
        DEFAULT_EMPTY_BACKOFF_THRESHOLD,
        1,
        50,
    )
    coerced["base_interval_seconds"] = _safe_int(
        coerced.get("base_interval_seconds"),
        DEFAULT_BASE_INTERVAL_SECONDS,
        60,
        90 * 24 * 60 * 60,
    )
    coerced["max_backoff_multiplier"] = _safe_int(
        coerced.get("max_backoff_multiplier"),
        DEFAULT_MAX_BACKOFF_MULTIPLIER,
        1,
        1024,
    )
    coerced["allow_first_run_bootstrap"] = _truthy(coerced.get("allow_first_run_bootstrap"))
    coerced["auto_production_adoption_allowed"] = False
    return coerced


def load_hermes_background_config(
    *,
    memcore_root: str | Path | None = None,
    install_root: str | Path | None = None,
    python_bin: str | Path | None = None,
) -> dict[str, Any]:
    path = _background_config_path(memcore_root)
    defaults = build_default_hermes_background_config(
        memcore_root=memcore_root,
        install_root=install_root,
        python_bin=python_bin,
    )
    data, error = _read_json(path)
    config = dict(defaults)
    if data:
        config.update({key: value for key, value in data.items() if key in defaults or key.startswith("x_")})
    config = _coerce_hermes_background_config(config)
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "config_path": str(path) if path else "",
        "config_exists": bool(path and path.exists()),
        "config_read_error": "" if error == "not_found" else error,
        "config": config,
    }


def write_hermes_background_config(
    config: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
    install_root: str | Path | None = None,
    python_bin: str | Path | None = None,
) -> dict[str, Any]:
    path = _background_config_path(memcore_root)
    if not path:
        return {
            "ok": False,
            "write_performed": False,
            "error": "memcore_root_required",
        }
    defaults = build_default_hermes_background_config(
        memcore_root=memcore_root,
        install_root=install_root,
        python_bin=python_bin,
    )
    merged = dict(defaults)
    if isinstance(config, dict):
        merged.update({key: value for key, value in config.items() if key in defaults or key.startswith("x_")})
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, merged)
    loaded = load_hermes_background_config(
        memcore_root=memcore_root,
        install_root=install_root,
        python_bin=python_bin,
    )
    return {
        "ok": True,
        "write_performed": True,
        "config_path": str(path),
        "config": loaded.get("config", merged),
    }


def build_hermes_background_launchd_plist(
    config: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
    install_root: str | Path | None = None,
    python_bin: str | Path | None = None,
) -> dict[str, Any]:
    loaded = load_hermes_background_config(
        memcore_root=memcore_root,
        install_root=install_root,
        python_bin=python_bin,
    ).get("config", {})
    if isinstance(config, dict):
        loaded.update({key: value for key, value in config.items() if key in loaded or key.startswith("x_")})
    root = Path(loaded.get("memcore_root") or memcore_root or "").expanduser()
    install = Path(loaded.get("install_root") or install_root or root).expanduser()
    py = Path(loaded.get("python_bin") or python_bin or install / ".venv" / "bin" / "python").expanduser()
    logs = root / "logs"
    start_interval = _safe_int(
        loaded.get("start_interval_seconds"),
        DEFAULT_BACKGROUND_START_INTERVAL_SECONDS,
        300,
        7 * 24 * 60 * 60,
    )
    tool = install / "tools" / "hermes_autonomous_loop.py"
    label = _clean_text(loaded.get("label")) or DEFAULT_BACKGROUND_LABEL
    plist = {
        "Label": label,
        "ProgramArguments": [
            str(py),
            str(tool),
            "--root",
            str(root),
            "--install-root",
            str(install),
            "tick",
        ],
        "EnvironmentVariables": {
            "MEMCORE_ROOT": str(root),
            "MEMCORE_INSTALL_ROOT": str(install),
        },
        "RunAtLoad": False,
        "StartInterval": start_interval,
        "KeepAlive": False,
        "StandardOutPath": str(logs / "hermes-autonomous-loop.out.log"),
        "StandardErrorPath": str(logs / "hermes-autonomous-loop.err.log"),
    }
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "label": label,
        "plist": plist,
        "launchd_boundary": {
            "run_at_load": False,
            "keep_alive": False,
            "start_interval_seconds": start_interval,
            "value_gate_controls_spend": True,
            "daily_trigger_budget": loaded.get("daily_trigger_budget", DEFAULT_BACKGROUND_DAILY_TRIGGER_BUDGET),
            "daily_spend_budget": loaded.get("daily_spend_budget", DEFAULT_BACKGROUND_DAILY_SPEND_BUDGET),
        },
    }


def write_hermes_background_launchd_plist(
    config: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
    install_root: str | Path | None = None,
    python_bin: str | Path | None = None,
    plist_path: str | Path | None = None,
) -> dict[str, Any]:
    plan = build_hermes_background_launchd_plist(
        config,
        memcore_root=memcore_root,
        install_root=install_root,
        python_bin=python_bin,
    )
    label = plan.get("label") or DEFAULT_BACKGROUND_LABEL
    target = Path(plist_path).expanduser() if plist_path else Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plistlib.dumps(plan["plist"], sort_keys=False))
    return {
        "ok": True,
        "write_performed": True,
        "plist_path": str(target),
        "label": label,
        "plist": plan["plist"],
        "launchd_boundary": plan.get("launchd_boundary", {}),
    }


def _body_options(body: dict[str, Any]) -> dict[str, Any]:
    max_triggers = _safe_int(body.get("max_triggers_per_cycle"), DEFAULT_MAX_TRIGGERS_PER_CYCLE, 0, 20)
    empty_threshold = _safe_int(body.get("empty_backoff_threshold"), DEFAULT_EMPTY_BACKOFF_THRESHOLD, 1, 50)
    base_interval = _safe_int(body.get("base_interval_seconds"), DEFAULT_BASE_INTERVAL_SECONDS, 60, 90 * 24 * 60 * 60)
    max_backoff = _safe_int(body.get("max_backoff_multiplier"), DEFAULT_MAX_BACKOFF_MULTIPLIER, 1, 1024)
    return {
        "max_triggers_per_cycle": max_triggers,
        "empty_backoff_threshold": empty_threshold,
        "base_interval_seconds": base_interval,
        "max_backoff_multiplier": max_backoff,
        "allow_first_run_bootstrap": _truthy(body.get("allow_first_run_bootstrap")),
    }


def _trigger_declaration(source_system: str) -> dict[str, Any]:
    return {
        "source_system": source_system,
        "native_generation_trigger_kind": source_system_native_generation_trigger_kind(source_system),
        "generation_cadence": source_system_generation_cadence(source_system),
        "generation_model_hint": source_system_generation_model_hint(source_system),
        "generation_scope": source_system_generation_scope(source_system),
    }


def build_hermes_autonomous_loop_plan(
    body: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
    source_system: str = DEFAULT_SOURCE_SYSTEM,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    source = _clean_text(body.get("source_system") or source_system) or DEFAULT_SOURCE_SYSTEM
    options = _body_options(body)
    state_result = load_hermes_autonomous_loop_state(memcore_root=memcore_root)
    state = state_result.get("state", {}) if isinstance(state_result.get("state"), dict) else _empty_state()
    watermark = build_hermes_raw_watermark(memcore_root=memcore_root, source_system=source)
    last_token = _clean_text(state.get("last_raw_watermark_token"))
    current_token = _clean_text(watermark.get("watermark_token"))
    source_event_count = int(watermark.get("source_event_count", 0) or 0)
    hermes_cli = _resolve_hermes_cli(_clean_text(body.get("hermes_cli")))
    raw_changed_since_state = bool(current_token and current_token != last_token)
    first_run = not bool(last_token)
    if source_event_count <= 0:
        decision = "skip_no_source_raw"
        should_trigger = False
    elif first_run and not options["allow_first_run_bootstrap"]:
        decision = "skip_bootstrap_baseline_without_spend"
        should_trigger = False
    elif not raw_changed_since_state:
        decision = "skip_no_new_raw"
        should_trigger = False
    elif options["max_triggers_per_cycle"] <= 0:
        decision = "skip_cost_cap_reached"
        should_trigger = False
    elif source_system_native_generation_trigger_kind(source) in {"", "none"}:
        decision = "skip_no_declared_native_generation_trigger"
        should_trigger = False
    elif not hermes_cli:
        decision = "skip_hermes_cli_not_found"
        should_trigger = False
    else:
        decision = "trigger_once"
        should_trigger = True

    consecutive_empty = int(state.get("consecutive_empty_outputs", 0) or 0)
    cadence_state = _clean_text(state.get("cadence_state")) or "baseline"
    if consecutive_empty >= options["empty_backoff_threshold"]:
        cadence_state = "backoff"
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "schema_version": HERMES_AUTONOMOUS_LOOP_SCHEMA_VERSION,
        "loop_kind": "hermes_value_gated_autonomous_native_learning",
        "source_system": source,
        "trigger_declaration": _trigger_declaration(source),
        "hermes_cli": hermes_cli,
        "hermes_cli_found": bool(hermes_cli),
        "state": state,
        "state_path": state_result.get("state_path", ""),
        "state_exists": state_result.get("state_exists", False),
        "raw_watermark": watermark,
        "change_gate": {
            "raw_changed_since_state": raw_changed_since_state,
            "first_run": first_run,
            "allow_first_run_bootstrap": options["allow_first_run_bootstrap"],
            "source_event_count": source_event_count,
            "decision": decision,
            "should_trigger_hermes": should_trigger,
            "estimated_hermes_spend_units": 1 if should_trigger else 0,
        },
        "value_adaptation": {
            "cadence_state": cadence_state,
            "consecutive_empty_outputs": consecutive_empty,
            "backoff_multiplier": int(state.get("backoff_multiplier", 1) or 1),
            "recommended_next_interval_seconds": int(
                state.get("recommended_next_interval_seconds", DEFAULT_BASE_INTERVAL_SECONDS)
                or DEFAULT_BASE_INTERVAL_SECONDS
            ),
            "empty_backoff_threshold": options["empty_backoff_threshold"],
        },
        "cost_cap": {
            "max_triggers_per_cycle": options["max_triggers_per_cycle"],
            "trigger_count_planned": 1 if should_trigger else 0,
            "cap_enforced": True,
        },
        "write_boundary": {
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "hermes_skill_write_performed_by_yifanchen": False,
            "production_experience_write_performed": False,
            "cron_registered": False,
            "unbounded_cron_registered": False,
        },
        "non_claims": [
            "dry_run_does_not_trigger_hermes",
            "does_not_register_cron",
            "does_not_write_hermes_skill",
            "does_not_write_time_library_raw_or_shelves",
        ],
    }


def _authorization_result(body: dict[str, Any]) -> dict[str, Any]:
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else {}

    def confirmed(name: str) -> bool:
        return _truthy(authorization.get(name, body.get(name)))

    operator = _clean_text(authorization.get("operator") or body.get("operator"))
    reason = _clean_text(authorization.get("reason") or body.get("reason"))
    checks = {
        "confirm_run_hermes_autonomous_loop": confirmed("confirm_run_hermes_autonomous_loop"),
        "confirm_hermes_may_read_raw_source_refs": confirmed("confirm_hermes_may_read_raw_source_refs"),
        "confirm_hermes_native_skill_artifacts_allowed": confirmed("confirm_hermes_native_skill_artifacts_allowed"),
        "confirm_no_yifanchen_raw_zhiyi_xingce_write": confirmed("confirm_no_yifanchen_raw_zhiyi_xingce_write"),
        "confirm_no_unbounded_cron": confirmed("confirm_no_unbounded_cron"),
        "operator": bool(operator),
        "reason": bool(reason),
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "ok": not missing,
        "checks": checks,
        "missing": missing,
        "operator": operator,
        "reason": reason,
    }


def _next_state(
    *,
    previous: dict[str, Any],
    watermark: dict[str, Any],
    outcome: str,
    useful_output: bool,
    trigger_called: bool,
    options: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    state = dict(previous or _empty_state())
    empty = int(state.get("consecutive_empty_outputs", 0) or 0)
    multiplier = max(1, int(state.get("backoff_multiplier", 1) or 1))
    if useful_output:
        empty = 0
        multiplier = 1
        cadence_state = "fast" if trigger_called else "normal"
    elif trigger_called:
        empty += 1
        if empty >= int(options["empty_backoff_threshold"]):
            multiplier = min(int(options["max_backoff_multiplier"]), max(2, multiplier * 2))
            cadence_state = "backoff"
        else:
            cadence_state = "normal"
    else:
        cadence_state = _clean_text(state.get("cadence_state")) or "baseline"
    state.update({
        "schema_version": HERMES_AUTONOMOUS_LOOP_SCHEMA_VERSION,
        "last_raw_watermark_token": watermark.get("watermark_token", ""),
        "last_raw_watermark": watermark,
        "consecutive_empty_outputs": empty,
        "backoff_multiplier": multiplier,
        "cadence_state": cadence_state,
        "recommended_next_interval_seconds": int(options["base_interval_seconds"]) * multiplier,
        "total_trigger_count": int(state.get("total_trigger_count", 0) or 0) + (1 if trigger_called else 0),
        "total_hermes_spend_units": int(state.get("total_hermes_spend_units", 0) or 0) + (1 if trigger_called else 0),
        "last_run_id": run_id,
        "last_outcome": outcome,
        "updated_at": _ts(),
    })
    return state


def _empty_background_state(now_epoch: float | None = None) -> dict[str, Any]:
    return {
        "schema_version": HERMES_AUTONOMOUS_LOOP_SCHEMA_VERSION,
        "last_tick_id": "",
        "last_tick_at": "",
        "last_tick_epoch": 0.0,
        "last_tick_decision": "",
        "last_loop_run_id": "",
        "daily_budget": {
            "day": _day_key(now_epoch),
            "trigger_count": 0,
            "spend_units": 0,
        },
        "updated_at": "",
    }


def load_hermes_background_state(
    *,
    memcore_root: str | Path | None = None,
) -> dict[str, Any]:
    path = _background_state_path(memcore_root)
    state, error = _read_json(path)
    if error:
        state = _empty_background_state()
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "state_path": str(path) if path else "",
        "state_exists": bool(path and path.exists()),
        "state_read_error": "" if error == "not_found" else error,
        "state": state,
    }


def _normalize_daily_budget(state: dict[str, Any], now_epoch: float) -> dict[str, Any]:
    current_day = _day_key(now_epoch)
    daily = state.get("daily_budget") if isinstance(state.get("daily_budget"), dict) else {}
    if daily.get("day") != current_day:
        return {
            "day": current_day,
            "trigger_count": 0,
            "spend_units": 0,
        }
    return {
        "day": current_day,
        "trigger_count": int(daily.get("trigger_count", 0) or 0),
        "spend_units": int(daily.get("spend_units", 0) or 0),
    }


def _build_background_tick_receipt(
    *,
    tick_id: str,
    config: dict[str, Any],
    state_before: dict[str, Any],
    state_after: dict[str, Any],
    decision: str,
    reason: str,
    plan: dict[str, Any],
    run_result: dict[str, Any] | None,
    started: float,
) -> dict[str, Any]:
    called = bool(run_result and run_result.get("hermes_trigger_called", False))
    loop_receipt = run_result.get("receipt", {}) if isinstance(run_result, dict) else {}
    return {
        "schema_version": HERMES_AUTONOMOUS_LOOP_SCHEMA_VERSION,
        "tick_id": tick_id,
        "recorded_at": _ts(),
        "source_system": config.get("source_system", DEFAULT_SOURCE_SYSTEM),
        "background_controller": {
            "controller_kind": "value_gated_launchd_background_loop",
            "enabled": bool(config.get("enabled", False)),
            "label": config.get("label", DEFAULT_BACKGROUND_LABEL),
            "start_interval_seconds": config.get("start_interval_seconds", DEFAULT_BACKGROUND_START_INTERVAL_SECONDS),
            "minimum_interval_seconds": config.get("minimum_interval_seconds", DEFAULT_BASE_INTERVAL_SECONDS),
            "daily_trigger_budget": config.get("daily_trigger_budget", DEFAULT_BACKGROUND_DAILY_TRIGGER_BUDGET),
            "daily_spend_budget": config.get("daily_spend_budget", DEFAULT_BACKGROUND_DAILY_SPEND_BUDGET),
            "auto_production_adoption_allowed": False,
            "unbounded_cron_registered": False,
        },
        "decision": decision,
        "reason": reason,
        "plan": {
            "decision": plan.get("change_gate", {}).get("decision", ""),
            "should_trigger_hermes": bool(plan.get("change_gate", {}).get("should_trigger_hermes", False)),
            "estimated_hermes_spend_units": int(plan.get("change_gate", {}).get("estimated_hermes_spend_units", 0) or 0),
            "raw_changed_since_state": bool(plan.get("change_gate", {}).get("raw_changed_since_state", False)),
            "source_event_count": int(plan.get("change_gate", {}).get("source_event_count", 0) or 0),
            "value_adaptation": plan.get("value_adaptation", {}),
            "raw_watermark": plan.get("raw_watermark", {}),
        },
        "run": {
            "called": bool(run_result),
            "ok": bool(run_result.get("ok", False)) if isinstance(run_result, dict) else False,
            "run_id": run_result.get("run_id", "") if isinstance(run_result, dict) else "",
            "outcome": run_result.get("outcome", "") if isinstance(run_result, dict) else "",
            "receipt_path": run_result.get("receipt_path", "") if isinstance(run_result, dict) else "",
            "hermes_trigger_called": called,
            "skill_generation_success": bool((loop_receipt.get("trigger") or {}).get("skill_generation_success", False)),
            "candidate_count": int(
                ((((loop_receipt.get("experience_candidate_delivery") or {}).get("diff_summary") or {}).get("candidate_count", 0)) or 0)
            ),
        },
        "state_before": state_before,
        "state_after": state_after,
        "elapsed_seconds": round(time.time() - started, 3),
        "write_boundary": {
            "background_tick_receipt_write_performed": True,
            "background_state_write_performed": True,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "hermes_skill_write_performed_by_yifanchen": False,
            "hermes_native_artifacts_may_be_written_by_hermes": called,
            "production_experience_write_performed": False,
            "auto_production_adoption_allowed": False,
            "unbounded_cron_registered": False,
        },
        "time_rule_decision": config.get("time_rule_decision", {}),
        "non_claims": [
            "background_loop_is_bounded_by_daily_budget_and_minimum_interval",
            "background_loop_does_not_auto_adopt_production_experience",
            "background_loop_does_not_write_hermes_skill_by_time_library",
            "launchd_wakeup_does_not_imply_each_tick_spends",
        ],
    }


def run_hermes_autonomous_loop_background_tick(
    config: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
    install_root: str | Path | None = None,
    python_bin: str | Path | None = None,
    hermes_home: str | Path | None = None,
    runner: Callable[..., Any] | None = None,
    diff_builder: Callable[..., dict[str, Any]] | None = None,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    started = time.time()
    now = time.time() if now_epoch is None else float(now_epoch)
    loaded_config = load_hermes_background_config(
        memcore_root=memcore_root,
        install_root=install_root,
        python_bin=python_bin,
    ).get("config", {})
    if isinstance(config, dict):
        loaded_config.update({key: value for key, value in config.items() if key in loaded_config or key.startswith("x_")})
        loaded_config = load_hermes_background_config(
            memcore_root=memcore_root,
            install_root=install_root,
            python_bin=python_bin,
        ).get("config", loaded_config) | {
            key: value for key, value in config.items() if key in loaded_config or key.startswith("x_")
        }
        loaded_config["enabled"] = _truthy(loaded_config.get("enabled"))
        loaded_config["auto_production_adoption_allowed"] = False
    state_path = _background_state_path(memcore_root)
    ticks_dir = _background_ticks_dir(memcore_root)
    if not memcore_root or not state_path or not ticks_dir:
        return {
            "ok": False,
            "write_performed": False,
            "error": "memcore_root_required",
        }

    state_result = load_hermes_background_state(memcore_root=memcore_root)
    state_before = state_result.get("state", {}) if isinstance(state_result.get("state"), dict) else _empty_background_state(now)
    daily = _normalize_daily_budget(state_before, now)
    last_tick_epoch = float(state_before.get("last_tick_epoch", 0) or 0)
    loop_state = load_hermes_autonomous_loop_state(memcore_root=memcore_root).get("state", {})
    last_loop_updated_epoch = _epoch_from_iso(loop_state.get("updated_at", "")) if isinstance(loop_state, dict) else 0.0
    interval_anchor = max(last_tick_epoch, last_loop_updated_epoch)
    seconds_since_anchor = now - interval_anchor if interval_anchor else 0

    body = {
        "source_system": loaded_config.get("source_system") or DEFAULT_SOURCE_SYSTEM,
        "hermes_cli": loaded_config.get("hermes_cli", ""),
        "allow_first_run_bootstrap": bool(loaded_config.get("allow_first_run_bootstrap", False)),
        "max_triggers_per_cycle": int(loaded_config.get("max_triggers_per_tick", DEFAULT_MAX_TRIGGERS_PER_CYCLE) or 0),
        "empty_backoff_threshold": int(loaded_config.get("empty_backoff_threshold", DEFAULT_EMPTY_BACKOFF_THRESHOLD) or 1),
        "base_interval_seconds": int(loaded_config.get("base_interval_seconds", DEFAULT_BASE_INTERVAL_SECONDS) or DEFAULT_BASE_INTERVAL_SECONDS),
        "max_backoff_multiplier": int(loaded_config.get("max_backoff_multiplier", DEFAULT_MAX_BACKOFF_MULTIPLIER) or 1),
    }
    plan = build_hermes_autonomous_loop_plan(
        body,
        memcore_root=memcore_root,
        source_system=body["source_system"],
    )

    decision = "skip_unknown"
    reason = ""
    run_result: dict[str, Any] | None = None
    if not _truthy(loaded_config.get("enabled")):
        decision = "skip_disabled"
        reason = "background_config_disabled"
    elif interval_anchor and seconds_since_anchor < int(loaded_config.get("minimum_interval_seconds", DEFAULT_BASE_INTERVAL_SECONDS) or DEFAULT_BASE_INTERVAL_SECONDS):
        decision = "skip_interval_not_due"
        reason = "minimum_interval_not_elapsed"
    elif daily["trigger_count"] >= int(loaded_config.get("daily_trigger_budget", DEFAULT_BACKGROUND_DAILY_TRIGGER_BUDGET) or 0):
        decision = "skip_daily_trigger_budget_reached"
        reason = "daily_trigger_budget_reached"
    elif daily["spend_units"] >= int(loaded_config.get("daily_spend_budget", DEFAULT_BACKGROUND_DAILY_SPEND_BUDGET) or 0):
        decision = "skip_daily_spend_budget_reached"
        reason = "daily_spend_budget_reached"
    elif not bool(plan.get("change_gate", {}).get("should_trigger_hermes", False)):
        plan_decision = plan.get("change_gate", {}).get("decision", "skip_no_trigger")
        if plan_decision == "skip_bootstrap_baseline_without_spend":
            decision = "baseline_without_spend"
            reason = "first_background_tick_records_watermark_baseline_without_hermes_spend"
            run_body = dict(body)
            run_body["scheduled_by"] = loaded_config.get("label", DEFAULT_BACKGROUND_LABEL)
            run_body["authorization"] = {
                "operator": loaded_config.get("label", DEFAULT_BACKGROUND_LABEL),
                "reason": "bounded Hermes autonomous background baseline without spend",
                "confirm_run_hermes_autonomous_loop": True,
                "confirm_hermes_may_read_raw_source_refs": True,
                "confirm_hermes_native_skill_artifacts_allowed": True,
                "confirm_no_yifanchen_raw_zhiyi_xingce_write": True,
                "confirm_no_unbounded_cron": True,
            }
            run_result = run_hermes_autonomous_loop_once(
                run_body,
                memcore_root=memcore_root,
                hermes_home=hermes_home,
                runner=runner,
                diff_builder=diff_builder,
            )
        else:
            decision = plan_decision
            reason = "value_gate_declined"
    else:
        decision = "trigger_background_once"
        reason = "value_gate_due_and_budget_available"
        run_body = dict(body)
        run_body["scheduled_by"] = loaded_config.get("label", DEFAULT_BACKGROUND_LABEL)
        run_body["authorization"] = {
            "operator": loaded_config.get("label", DEFAULT_BACKGROUND_LABEL),
            "reason": "bounded Hermes autonomous background tick",
            "confirm_run_hermes_autonomous_loop": True,
            "confirm_hermes_may_read_raw_source_refs": True,
            "confirm_hermes_native_skill_artifacts_allowed": True,
            "confirm_no_yifanchen_raw_zhiyi_xingce_write": True,
            "confirm_no_unbounded_cron": True,
        }
        run_result = run_hermes_autonomous_loop_once(
            run_body,
            memcore_root=memcore_root,
            hermes_home=hermes_home,
            runner=runner,
            diff_builder=diff_builder,
        )
        if bool(run_result.get("hermes_trigger_called", False)):
            daily["trigger_count"] += 1
            daily["spend_units"] += 1

    tick_seed = "|".join([
        str(time.time_ns()),
        loaded_config.get("label", DEFAULT_BACKGROUND_LABEL),
        decision,
        str(daily.get("day", "")),
    ])
    tick_id = "hermes-autonomous-background-" + hashlib.sha256(tick_seed.encode("utf-8")).hexdigest()[:16]
    state_after = dict(state_before or _empty_background_state(now))
    state_after.update({
        "schema_version": HERMES_AUTONOMOUS_LOOP_SCHEMA_VERSION,
        "last_tick_id": tick_id,
        "last_tick_at": _ts(),
        "last_tick_epoch": now,
        "last_tick_decision": decision,
        "last_loop_run_id": run_result.get("run_id", "") if isinstance(run_result, dict) else _clean_text(state_before.get("last_loop_run_id", "")),
        "daily_budget": daily,
        "updated_at": _ts(),
    })
    receipt = _build_background_tick_receipt(
        tick_id=tick_id,
        config=loaded_config,
        state_before=state_before,
        state_after=state_after,
        decision=decision,
        reason=reason,
        plan=plan,
        run_result=run_result,
        started=started,
    )
    ticks_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = ticks_dir / f"{receipt['recorded_at'].replace(':', '').replace('-', '')}-{tick_id}.json"
    _write_json(receipt_path, receipt)
    _write_json(ticks_dir / "latest.json", receipt)
    _write_json(state_path, state_after)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "receipt_write_performed": True,
        "state_write_performed": True,
        "tick_id": tick_id,
        "decision": decision,
        "reason": reason,
        "hermes_trigger_called": bool(run_result and run_result.get("hermes_trigger_called", False)),
        "run_id": run_result.get("run_id", "") if isinstance(run_result, dict) else "",
        "receipt_path": str(receipt_path),
        "latest_path": str(ticks_dir / "latest.json"),
        "state_path": str(state_path),
        "receipt": receipt,
    }


def _summarize_diff(diff: dict[str, Any]) -> dict[str, Any]:
    upgrades = diff.get("upgrade_candidates", {}) if isinstance(diff.get("upgrade_candidates"), dict) else {}
    candidates = upgrades.get("candidates", []) if isinstance(upgrades.get("candidates"), list) else []
    candidate_summaries = []
    for item in candidates[:10]:
        if not isinstance(item, dict):
            continue
        skill = item.get("skill", {}) if isinstance(item.get("skill"), dict) else {}
        candidate_summaries.append({
            "candidate_id": item.get("candidate_id", ""),
            "candidate_type": item.get("candidate_type", ""),
            "recommended_action": item.get("recommended_action", ""),
            "activation_allowed": bool(item.get("activation_allowed", False)),
            "skill_id": skill.get("skill_id", ""),
            "skill_source_refs": skill.get("source_refs", {}),
        })
    return {
        "ok": bool(diff.get("ok", False)),
        "read_only": bool(diff.get("read_only", True)),
        "write_performed": bool(diff.get("write_performed", False)),
        "candidate_count": int(upgrades.get("candidate_count", 0) or 0),
        "summary": diff.get("summary", {}) if isinstance(diff.get("summary"), dict) else {},
        "candidate_summaries": candidate_summaries,
    }


def run_hermes_autonomous_loop_once(
    body: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
    hermes_home: str | Path | None = None,
    runner: Callable[..., Any] | None = None,
    diff_builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    source = _clean_text(body.get("source_system")) or DEFAULT_SOURCE_SYSTEM
    authorization = _authorization_result(body)
    options = _body_options(body)
    plan = build_hermes_autonomous_loop_plan(body, memcore_root=memcore_root, source_system=source)
    runs_dir = _runs_dir(memcore_root)
    state_path = _state_path(memcore_root)
    guard_failures: list[str] = []
    if not memcore_root or not runs_dir or not state_path:
        guard_failures.append("memcore_root_required")
    if source_system_native_generation_trigger_kind(source) in {"", "none"}:
        guard_failures.append("declared_native_generation_trigger_required")
    if authorization["missing"] or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_capable": True,
            "write_performed": False,
            "receipt_write_performed": False,
            "state_write_performed": False,
            "hermes_trigger_called": False,
            "missing_authorization": authorization["missing"],
            "guard_failures": guard_failures,
            "plan": plan,
            "write_boundary": plan.get("write_boundary", {}),
        }

    assert runs_dir is not None
    assert state_path is not None
    started = time.time()
    run_seed = "|".join([
        str(time.time_ns()),
        source,
        plan["raw_watermark"].get("watermark_token", ""),
        authorization["operator"],
    ])
    run_id = "hermes-autonomous-loop-" + hashlib.sha256(run_seed.encode("utf-8")).hexdigest()[:16]
    decision = plan.get("change_gate", {}).get("decision", "skip_unknown")
    should_trigger = bool(plan.get("change_gate", {}).get("should_trigger_hermes", False))
    trigger_result: dict[str, Any] = {}
    diff_result: dict[str, Any] = {}
    trigger_called = False
    useful_output = False
    outcome = decision
    delivery_status = "not_attempted"
    if should_trigger:
        trigger_body = dict(body)
        trigger_body["authorization"] = {
            "operator": authorization["operator"],
            "reason": authorization["reason"],
            "confirm_live_hermes_skill_generation_probe": True,
            "confirm_hermes_may_read_raw_source_refs": True,
            "confirm_hermes_native_skill_artifacts_allowed": True,
            "confirm_no_yifanchen_raw_zhiyi_xingce_write": True,
        }
        trigger_result = trigger_hermes_skill_generation_probe(
            trigger_body,
            hermes_home=hermes_home or body.get("hermes_home") or None,
            memcore_root=memcore_root,
            runner=runner,
        )
        trigger_called = bool(trigger_result.get("hermes_trigger_called", False))
        if trigger_result.get("skill_generation_success"):
            builder = diff_builder or build_hermes_skill_experience_diff_dry_run
            diff_result = builder(
                {
                    "hermes_home": str(hermes_home or body.get("hermes_home") or ""),
                    "max_skills": body.get("max_skills", 20),
                    "max_experiences": body.get("max_experiences", 200),
                },
                hermes_home=hermes_home or body.get("hermes_home") or None,
                memcore_root=memcore_root,
            )
            delivery_status = "candidate_dry_run_built" if diff_result.get("ok") else "candidate_dry_run_failed"
        else:
            delivery_status = "blocked_no_skill_generation_success"
        diff_summary = _summarize_diff(diff_result)
        candidate_count = int(diff_summary.get("candidate_count", 0) or 0)
        useful_output = bool(trigger_result.get("skill_generation_success") or candidate_count > 0)
        outcome = "useful_output" if useful_output else "empty_output"
    else:
        diff_summary = _summarize_diff(diff_result)

    previous_state = plan.get("state", {}) if isinstance(plan.get("state"), dict) else _empty_state()
    next_state = _next_state(
        previous=previous_state,
        watermark=plan.get("raw_watermark", {}),
        outcome=outcome,
        useful_output=useful_output,
        trigger_called=trigger_called,
        options=options,
        run_id=run_id,
    )
    receipt = {
        "schema_version": HERMES_AUTONOMOUS_LOOP_SCHEMA_VERSION,
        "run_id": run_id,
        "recorded_at": _ts(),
        "source_system": source,
        "requested_by": authorization["operator"],
        "reason": authorization["reason"],
        "trigger_declaration": plan.get("trigger_declaration", {}),
        "change_gate": plan.get("change_gate", {}),
        "cost_cap": plan.get("cost_cap", {}),
        "autonomous_controller": {
            "controller_kind": "value_gated_run_once",
            "does_not_register_cron": True,
            "unbounded_cron_registered": False,
            "scheduled_by_external_runtime": _clean_text(body.get("scheduled_by") or ""),
        },
        "trigger": {
            "called": trigger_called,
            "result_ok": bool(trigger_result.get("ok", False)),
            "skill_generation_success": bool(trigger_result.get("skill_generation_success", False)),
            "skill_generation_stage": trigger_result.get("skill_generation_stage", ""),
            "probe_id": trigger_result.get("probe_id", ""),
            "receipt_path": trigger_result.get("receipt_path", ""),
            "skill_generation_observation": trigger_result.get("skill_generation_observation", {}),
            "skill_file_diff": trigger_result.get("skill_file_diff", {}),
        },
        "experience_candidate_delivery": {
            "delivery_status": delivery_status,
            "delivery_surface": "autonomous_loop_receipt_and_runs_endpoint",
            "diff_summary": diff_summary,
            "activation_allowed": False,
            "production_experience_write_performed": False,
        },
        "value_adaptation": {
            "useful_output": useful_output,
            "outcome": outcome,
            "previous_consecutive_empty_outputs": int(previous_state.get("consecutive_empty_outputs", 0) or 0),
            "next_consecutive_empty_outputs": int(next_state.get("consecutive_empty_outputs", 0) or 0),
            "previous_backoff_multiplier": int(previous_state.get("backoff_multiplier", 1) or 1),
            "next_backoff_multiplier": int(next_state.get("backoff_multiplier", 1) or 1),
            "next_cadence_state": next_state.get("cadence_state", ""),
            "recommended_next_interval_seconds": next_state.get("recommended_next_interval_seconds", 0),
        },
        "raw_watermark": plan.get("raw_watermark", {}),
        "state_before": previous_state,
        "state_after": next_state,
        "authorization": authorization["checks"],
        "elapsed_seconds": round(time.time() - started, 3),
        "write_boundary": {
            "write_performed": True,
            "autonomous_loop_receipt_write_performed": True,
            "autonomous_loop_state_write_performed": True,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "hermes_write_performed_by_yifanchen": False,
            "hermes_skill_write_performed_by_yifanchen": False,
            "hermes_native_artifacts_may_be_written_by_hermes": bool(trigger_called),
            "production_experience_write_performed": False,
            "cron_registered": False,
            "unbounded_cron_registered": False,
        },
        "time_rule_decision": {
            "decision": "attached",
            "rule_ids": [
                "each_runtime_first_witnessed_raw",
                "derived_sediment_must_reference_origin",
                "platforms_are_inlets_not_origin",
                "events_remain_orderable",
            ],
        },
        "non_claims": [
            "run_once_controller_receipt_is_not_a_standing_background_trace_by_itself",
            "does_not_register_unbounded_cron",
            "does_not_write_hermes_skill_by_time_library",
            "does_not_auto_install_or_adopt_skill_candidate",
            "does_not_write_raw_zhiyi_xingce_toolbook_errata",
        ],
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = runs_dir / f"{receipt['recorded_at'].replace(':', '').replace('-', '')}-{run_id}.json"
    _write_json(receipt_path, receipt)
    latest_path = runs_dir / "latest.json"
    _write_json(latest_path, receipt)
    _write_json(state_path, next_state)
    return {
        "ok": bool(outcome in {"useful_output", "empty_output", "skip_no_new_raw", "skip_bootstrap_baseline_without_spend", "skip_no_source_raw", "skip_cost_cap_reached"}),
        "read_only": False,
        "write_capable": True,
        "write_performed": True,
        "receipt_write_performed": True,
        "state_write_performed": True,
        "hermes_trigger_called": trigger_called,
        "run_id": run_id,
        "outcome": outcome,
        "receipt_path": str(receipt_path),
        "latest_path": str(latest_path),
        "state_path": str(state_path),
        "receipt": receipt,
    }


def query_hermes_autonomous_loop_runs(
    *,
    memcore_root: str | Path | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    directory = _runs_dir(memcore_root)
    limit = _safe_int(limit, 20, 1, 100)
    items: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    if directory and directory.is_dir():
        paths = [path for path in directory.glob("*.json") if path.name != "latest.json"]
        paths.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
        for path in paths[:limit]:
            data, error = _read_json(path)
            if error:
                parse_errors.append({"path": str(path), "error": error})
                continue
            items.append({
                "run_id": data.get("run_id", ""),
                "recorded_at": data.get("recorded_at", ""),
                "source_system": data.get("source_system", ""),
                "outcome": (data.get("value_adaptation") or {}).get("outcome", ""),
                "hermes_trigger_called": bool((data.get("trigger") or {}).get("called", False)),
                "skill_generation_success": bool((data.get("trigger") or {}).get("skill_generation_success", False)),
                "candidate_count": int((((data.get("experience_candidate_delivery") or {}).get("diff_summary") or {}).get("candidate_count", 0)) or 0),
                "cadence_state": ((data.get("value_adaptation") or {}).get("next_cadence_state", "")),
                "receipt_path": str(path),
            })
    latest_path = directory / "latest.json" if directory else None
    latest, latest_error = _read_json(latest_path)
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "runs_dir": str(directory) if directory else "",
        "runs_dir_exists": bool(directory and directory.is_dir()),
        "latest_path": str(latest_path) if latest_path else "",
        "latest": latest if not latest_error else {},
        "latest_error": "" if latest_error == "not_found" else latest_error,
        "items": items,
        "count": len(items),
        "parse_errors": parse_errors,
    }


__all__ = [
    "HERMES_AUTONOMOUS_LOOP_SCHEMA_VERSION",
    "build_hermes_raw_watermark",
    "load_hermes_autonomous_loop_state",
    "build_hermes_autonomous_loop_plan",
    "run_hermes_autonomous_loop_once",
    "query_hermes_autonomous_loop_runs",
]
