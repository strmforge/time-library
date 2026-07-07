#!/usr/bin/env python3
"""
Codex local source connector.

Read-only source side:
- discovers local Codex rollout JSONL files under ~/.codex/sessions
- reads session metadata and thread names from Codex's official thread index
  (~/.codex/state_5.sqlite) when present, with session_index.jsonl as fallback

Write side:
- archives an independent raw copy into memory/<node>/codex/codex_session_jsonl/<project>/<session>.jsonl
- uses the shared memcore checkpoint for incremental appends
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config_loader import checkpoint_file, memory_root, node_id
try:
    from src.raw_archive_layout import preferred_raw_archive_path
except ImportError:
    from raw_archive_layout import preferred_raw_archive_path
try:
    from src.window_binding_registry import register_current_window
except ImportError:
    from window_binding_registry import register_current_window
try:
    from src.canonical_dialogue_runtime import (
        canonical_dialogue_sidecar_path,
        forensic_runtime_manifest_path,
        materialize_canonical_dialogue,
    )
except ImportError:
    from canonical_dialogue_runtime import (
        canonical_dialogue_sidecar_path,
        forensic_runtime_manifest_path,
        materialize_canonical_dialogue,
    )

UTC = timezone.utc
SOURCE_SYSTEM = "codex"
NATIVE_ARTIFACT_FORMAT = "codex_session_jsonl"
SESSION_GLOB = "*.jsonl"
DEFAULT_SYNC_INTERVAL_MS = 250
MIN_SYNC_INTERVAL_MS = 50
MAX_SYNC_INTERVAL_MS = 3_600_000
DEFAULT_WATCH_SCAN_LIMIT = 8
DEFAULT_TAIL_CATCHUP_BUDGET_MS = 900
DEFAULT_TAIL_CATCHUP_MAX_PASSES = 6
DEFAULT_RAW_LAG_SLA_MS = 1000


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def codex_sessions_root() -> Path:
    override = os.environ.get("CODEX_SESSIONS_DIR", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex" / "sessions"


def codex_home_root() -> Path:
    override = os.environ.get("CODEX_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex"


def codex_session_index_path() -> Path:
    override = os.environ.get("CODEX_SESSION_INDEX", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex" / "session_index.jsonl"


def codex_state_db_path() -> Path:
    override = os.environ.get("CODEX_STATE_DB", "").strip()
    return Path(override).expanduser() if override else codex_home_root() / "state_5.sqlite"


def _safe_segment(value: str, fallback: str = "unknown") -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-_")
    return text[:80] or fallback


def _public_path_label(path: str) -> str:
    path = str(path or "")
    if not path:
        return ""
    try:
        p = Path(path).expanduser()
        home = Path.home().resolve()
        resolved = p.resolve()
        try:
            rel = resolved.relative_to(home)
            return "~/" + str(rel)
        except ValueError:
            return p.name or path
    except Exception:
        return Path(path).name or path


def _milliseconds_setting(
    env_ms_name: str,
    default_ms: int,
    *,
    legacy_env_seconds_name: str = "",
    minimum: int = MIN_SYNC_INTERVAL_MS,
    maximum: int = MAX_SYNC_INTERVAL_MS,
) -> int:
    raw = os.environ.get(env_ms_name)
    if raw is None and legacy_env_seconds_name:
        raw_seconds = os.environ.get(legacy_env_seconds_name)
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
        DEFAULT_SYNC_INTERVAL_MS,
        legacy_env_seconds_name="MEMCORE_WATCHER_POLL_INTERVAL_SECONDS",
    )


def watch_scan_limit() -> int:
    raw = os.environ.get("MEMCORE_CODEX_WATCH_SCAN_LIMIT")
    try:
        value = int(raw if raw is not None else DEFAULT_WATCH_SCAN_LIMIT)
    except Exception:
        value = DEFAULT_WATCH_SCAN_LIMIT
    return max(1, min(value, 200))


def tail_catchup_budget_milliseconds() -> int:
    return _milliseconds_setting(
        "MEMCORE_CODEX_TAIL_CATCHUP_BUDGET_MS",
        DEFAULT_TAIL_CATCHUP_BUDGET_MS,
        minimum=0,
        maximum=30_000,
    )


def tail_catchup_max_passes() -> int:
    raw = os.environ.get("MEMCORE_CODEX_TAIL_CATCHUP_MAX_PASSES")
    try:
        value = int(raw if raw is not None else DEFAULT_TAIL_CATCHUP_MAX_PASSES)
    except Exception:
        value = DEFAULT_TAIL_CATCHUP_MAX_PASSES
    return max(1, min(value, 100))


def raw_lag_sla_milliseconds() -> int:
    return _milliseconds_setting(
        "MEMCORE_CODEX_RAW_LAG_SLA_MS",
        DEFAULT_RAW_LAG_SLA_MS,
        minimum=0,
        maximum=3_600_000,
    )


def project_id_from_cwd(cwd: str) -> str:
    if not cwd:
        return "no-cwd"
    expanded = os.path.expanduser(cwd)
    name = Path(expanded).name or "project"
    digest = hashlib.sha1(expanded.encode("utf-8")).hexdigest()[:8]
    return _safe_segment(f"{name}-{digest}", "project")


def _clean_path_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("\\\\?\\"):
        return text[4:]
    if text.startswith("//?/"):
        return text[4:]
    return text


def _path_key(value: Any) -> str:
    text = _clean_path_text(value).replace("\\", "/").rstrip("/")
    return text.lower()


def _epoch_to_iso(value: Any) -> str:
    try:
        ts_value = float(value)
    except Exception:
        return str(value or "")
    if ts_value <= 0:
        return ""
    return datetime.fromtimestamp(ts_value, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_hash(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size > 50 * 1024 * 1024:
        return f"sha256_skipped_large_file:{size}"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_session_index() -> Dict[str, dict]:
    index_path = codex_session_index_path()
    result: Dict[str, dict] = {}
    if not index_path.exists():
        return result
    try:
        with index_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                sid = str(item.get("id") or "")
                if sid:
                    result[sid] = item
    except OSError:
        return result
    return result


def _sqlite_ro_uri(path: Path) -> str:
    try:
        return path.resolve().as_uri() + "?mode=ro"
    except Exception:
        return f"file:{path}?mode=ro"


def _load_state_thread_index() -> Dict[str, Any]:
    """Read Codex Desktop/CLI's official thread table without touching chat bodies."""
    state_path = codex_state_db_path()
    result: Dict[str, Any] = {
        "by_id": {},
        "by_path": {},
        "state_db_path": str(state_path),
        "read_ok": False,
        "error": "",
    }
    if not state_path.exists():
        return result
    try:
        conn = sqlite3.connect(_sqlite_ro_uri(state_path), uri=True, timeout=1)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        columns = {row[1] for row in cur.execute("pragma table_info(threads)").fetchall()}
        wanted = [
            name
            for name in (
                "id",
                "rollout_path",
                "created_at",
                "updated_at",
                "source",
                "model_provider",
                "cwd",
                "title",
                "cli_version",
                "thread_source",
                "model",
                "reasoning_effort",
                "archived",
                "has_user_event",
            )
            if name in columns
        ]
        if not wanted or "id" not in wanted:
            conn.close()
            return result
        rows = cur.execute(f"select {','.join(wanted)} from threads").fetchall()
        conn.close()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    for row in rows:
        item = dict(row)
        sid = str(item.get("id") or "").strip()
        rollout_path = _clean_path_text(item.get("rollout_path"))
        normalized = {
            "id": sid,
            "session_id": sid,
            "native_thread_id": sid,
            "rollout_path": rollout_path,
            "thread_name": str(item.get("title") or ""),
            "thread_updated_at": _epoch_to_iso(item.get("updated_at")),
            "thread_created_at": _epoch_to_iso(item.get("created_at")),
            "codex_source": str(item.get("source") or ""),
            "model_provider": str(item.get("model_provider") or ""),
            "project_root": _clean_path_text(item.get("cwd")),
            "cli_version": str(item.get("cli_version") or ""),
            "thread_source": str(item.get("thread_source") or ""),
            "model": str(item.get("model") or ""),
            "reasoning_effort": str(item.get("reasoning_effort") or ""),
            "archived": bool(item.get("archived")) if item.get("archived") is not None else False,
            "has_user_event": bool(item.get("has_user_event")) if item.get("has_user_event") is not None else False,
            "state_db_path": str(state_path),
            "index_source": "codex_state_5_threads",
        }
        if sid:
            result["by_id"][sid] = normalized
        if rollout_path:
            result["by_path"][_path_key(rollout_path)] = normalized
    result["read_ok"] = True
    return result


def _read_session_meta(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for _ in range(80):
                line = f.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "session_meta" and isinstance(obj.get("payload"), dict):
                    return obj["payload"]
    except OSError:
        return {}
    return {}


def _session_id_from_path(path: Path, meta: dict) -> str:
    sid = str(meta.get("id") or "").strip()
    if sid:
        return sid
    stem = path.stem
    if stem.startswith("rollout-"):
        parts = stem.split("-")
        if len(parts) >= 6:
            return "-".join(parts[-5:])
    return stem


def artifact_from_path(
    path: Path,
    index: Optional[Dict[str, dict]] = None,
    thread_index: Optional[Dict[str, Any]] = None,
) -> dict:
    path = path.expanduser()
    meta = _read_session_meta(path)
    session_id = _session_id_from_path(path, meta)
    index = index if index is not None else _load_session_index()
    thread_index = thread_index if thread_index is not None else _load_state_thread_index()
    thread_by_id = thread_index.get("by_id", {}) if isinstance(thread_index, dict) else {}
    thread_by_path = thread_index.get("by_path", {}) if isinstance(thread_index, dict) else {}
    official_thread = thread_by_id.get(session_id) or thread_by_path.get(_path_key(path))
    indexed = index.get(session_id, {})
    cwd = _clean_path_text(meta.get("cwd") or (official_thread or {}).get("project_root") or indexed.get("cwd") or "")
    project_id = project_id_from_cwd(cwd)
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": "codex_session_jsonl",
        "source_path": str(path),
        "filename": path.name,
        "session_id": session_id,
        "native_thread_id": session_id,
        "canonical_window_id": project_id,
        "project_id": project_id,
        "project_root": cwd,
        "thread_name": (official_thread or {}).get("thread_name") or indexed.get("thread_name", ""),
        "thread_updated_at": (official_thread or {}).get("thread_updated_at") or indexed.get("updated_at", ""),
        "thread_index_source": (official_thread or {}).get("index_source") or ("session_index_jsonl" if indexed else ""),
        "codex_source": meta.get("source") or (official_thread or {}).get("codex_source", ""),
        "thread_source": meta.get("thread_source") or (official_thread or {}).get("thread_source", ""),
        "model_provider": meta.get("model_provider") or (official_thread or {}).get("model_provider", ""),
        "cli_version": meta.get("cli_version") or (official_thread or {}).get("cli_version", ""),
        "codex_model": (official_thread or {}).get("model", ""),
        "reasoning_effort": (official_thread or {}).get("reasoning_effort", ""),
        "official_thread_index_detected": bool(official_thread),
        "state_db_path": (official_thread or {}).get("state_db_path", ""),
        "computer_name": node_id(),
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 3),
        "mtime": mtime,
        "capture_classification": "SHADOW",
        "scope_level": "project",
        "read_only_probe": True,
    }


def discover_sessions(limit: int = 0) -> List[dict]:
    root = codex_sessions_root()
    if not root.exists():
        return []
    index = _load_session_index()
    thread_index = _load_state_thread_index()
    files = [p for p in root.rglob(SESSION_GLOB) if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if limit and limit > 0:
        files = files[:limit]
    artifacts = []
    for path in files:
        try:
            artifacts.append(artifact_from_path(path, index=index, thread_index=thread_index))
        except OSError:
            continue
    return artifacts


def source_refs_from_artifact(artifact: dict) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        "computer_name": artifact.get("computer_name") or node_id(),
        "canonical_window_id": artifact.get("canonical_window_id", ""),
        "session_id": artifact.get("session_id", ""),
        "source_path": artifact.get("source_path", ""),
        "msg_ids": artifact.get("msg_ids", []) or [],
        "artifact_type": artifact.get("artifact_type", "codex_session_jsonl"),
        "captured_at": ts(),
        "project_root": artifact.get("project_root", ""),
        "project_id": artifact.get("project_id", artifact.get("canonical_window_id", "")),
        "thread_name": artifact.get("thread_name", ""),
        "native_thread_id": artifact.get("native_thread_id", artifact.get("session_id", "")),
        "thread_index_source": artifact.get("thread_index_source", ""),
    }


def public_artifact(artifact: dict) -> dict:
    """Return status-safe metadata without full local paths."""
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": artifact.get("artifact_type", "codex_session_jsonl"),
        "filename": artifact.get("filename", ""),
        "session_id": artifact.get("session_id", ""),
        "canonical_window_id": artifact.get("canonical_window_id", ""),
        "project_id": artifact.get("project_id", ""),
        "computer_name": artifact.get("computer_name", ""),
        "size_bytes": artifact.get("size_bytes", 0),
        "size_mb": artifact.get("size_mb", 0),
        "mtime": artifact.get("mtime", ""),
        "capture_classification": artifact.get("capture_classification", "SHADOW"),
        "scope_level": artifact.get("scope_level", "project"),
        "thread_index_source": artifact.get("thread_index_source", ""),
        "official_thread_index_detected": bool(artifact.get("official_thread_index_detected")),
        "read_only_probe": True,
    }


def _iso_to_epoch(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _file_mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return ""


def _stat_mtime_ms(stat_result: Optional[os.stat_result]) -> int:
    if stat_result is None:
        return 0
    try:
        return int(stat_result.st_mtime_ns // 1_000_000)
    except Exception:
        return int(float(getattr(stat_result, "st_mtime", 0.0) or 0.0) * 1000)


def _epoch_ms_to_iso(value: int) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(value / 1000.0, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _raw_sync_item(artifact: dict) -> dict:
    src = Path(artifact.get("source_path", "")).expanduser()
    dest = _raw_dest_for_artifact(artifact)
    src_stat = None
    dest_stat = None
    observed_at_ms = int(time.time() * 1000)
    try:
        src_stat = src.stat()
        source_size = src_stat.st_size
        source_mtime = datetime.fromtimestamp(src_stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        source_size = 0
        source_mtime = artifact.get("mtime", "")
    try:
        dest_stat = dest.stat()
        raw_size = dest_stat.st_size
        raw_mtime = datetime.fromtimestamp(dest_stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        raw_size = 0
        raw_mtime = ""
    missing = not dest.exists()
    overrun = bool(dest.exists()) and raw_size > source_size
    stale = bool(dest.exists()) and raw_size < source_size
    source_mtime_ms = _stat_mtime_ms(src_stat)
    raw_mtime_ms = _stat_mtime_ms(dest_stat)
    raw_mtime_gap_ms = max(0, source_mtime_ms - raw_mtime_ms) if stale and source_mtime_ms and raw_mtime_ms else 0
    lag_ms = max(0, observed_at_ms - source_mtime_ms) if stale and source_mtime_ms else 0
    lag_bytes = max(0, source_size - raw_size)
    return {
        "session_id": artifact.get("session_id", ""),
        "project_id": artifact.get("project_id", ""),
        "thread_name": artifact.get("thread_name", ""),
        "source_mtime": source_mtime,
        "source_mtime_ms": source_mtime_ms,
        "source_mtime_precise": _epoch_ms_to_iso(source_mtime_ms),
        "source_size_bytes": source_size,
        "raw_mtime": raw_mtime,
        "raw_mtime_ms": raw_mtime_ms,
        "raw_mtime_precise": _epoch_ms_to_iso(raw_mtime_ms),
        "raw_size_bytes": raw_size,
        "raw_exists": dest.exists(),
        "raw_missing": missing,
        "raw_stale": stale,
        "raw_overrun": overrun,
        "raw_rebuild_recommended": overrun,
        "raw_archive_lag_bytes": lag_bytes,
        "raw_archive_lag_milliseconds": lag_ms,
        "raw_source_mtime_gap_milliseconds": raw_mtime_gap_ms,
        "lag_observed_at_ms": observed_at_ms,
        "lag_observed_at": _epoch_ms_to_iso(observed_at_ms),
        "source_path_label": _public_path_label(str(src)),
        "raw_path_label": _public_path_label(str(dest)),
    }


def raw_sync_snapshot(limit: int = 20) -> dict:
    """Compare Codex source records with Time Library raw archives without writing.

    This is deliberately independent from Codex Skill/MCP state. Skill/MCP is a
    consumption path; local session capture reads the Codex files directly.
    """
    artifacts = discover_sessions(limit=limit)
    items = [_raw_sync_item(artifact) for artifact in artifacts]
    missing_or_stale = [
        item for item in items
        if item.get("raw_missing") or item.get("raw_stale")
    ]
    rebuild_items = [item for item in items if item.get("raw_rebuild_recommended")]
    missing_items = [item for item in items if item.get("raw_missing")]
    lagging_items = [item for item in items if item.get("raw_stale")]
    max_lag_bytes = max((int(item.get("raw_archive_lag_bytes", 0) or 0) for item in lagging_items), default=0)
    max_lag_ms = max((int(item.get("raw_archive_lag_milliseconds", 0) or 0) for item in lagging_items), default=0)
    total_lag_bytes = sum(int(item.get("raw_archive_lag_bytes", 0) or 0) for item in lagging_items)
    sla_ms = raw_lag_sla_milliseconds()
    sla_breaches = [
        item for item in lagging_items
        if int(item.get("raw_archive_lag_milliseconds", 0) or 0) > sla_ms
        or (sla_ms == 0 and int(item.get("raw_archive_lag_bytes", 0) or 0) > 0)
    ]
    source_epochs = [_iso_to_epoch(item.get("source_mtime", "")) for item in items]
    raw_epochs = [_iso_to_epoch(item.get("raw_mtime", "")) for item in items if item.get("raw_mtime")]
    latest_source_epoch = max(source_epochs) if source_epochs else 0.0
    latest_raw_epoch = max(raw_epochs) if raw_epochs else 0.0
    latest_source_mtime = datetime.fromtimestamp(latest_source_epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if latest_source_epoch else ""
    latest_raw_mtime = datetime.fromtimestamp(latest_raw_epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if latest_raw_epoch else ""
    lag_seconds = (
        int(max(0, latest_source_epoch - latest_raw_epoch))
        if latest_source_epoch and latest_raw_epoch
        else None
    )
    if not codex_sessions_root().exists():
        status_text = "source_unreachable"
    elif not artifacts:
        status_text = "no_source_records"
    elif missing_items:
        status_text = "raw_missing"
    elif rebuild_items:
        status_text = "raw_rebuild_recommended"
    elif sla_breaches:
        status_text = "raw_lagging_sla_breach"
    elif missing_or_stale:
        status_text = "raw_catching_up"
    else:
        status_text = "raw_current"
    return {
        "ok": status_text != "source_unreachable",
        "read_only": True,
        "source_system": SOURCE_SYSTEM,
        "artifact_type": NATIVE_ARTIFACT_FORMAT,
        "status": status_text,
        "independent_of_mcp": True,
        "consumer_connection_required": False,
        "source_root_reachable": codex_sessions_root().exists(),
        "source_count_sample": len(artifacts),
        "latest_source_mtime": latest_source_mtime,
        "latest_raw_mtime": latest_raw_mtime,
        "raw_archive_lag_seconds": lag_seconds,
        "raw_archive_max_lag_bytes": max_lag_bytes,
        "raw_archive_total_lag_bytes": total_lag_bytes,
        "raw_archive_max_lag_milliseconds": max_lag_ms,
        "raw_lag_sla_milliseconds": sla_ms,
        "raw_lag_sla_breach_count": len(sla_breaches),
        "raw_missing_count": len(missing_items),
        "raw_overrun_count": len(rebuild_items),
        "raw_catching_up_count": len(lagging_items) - len(sla_breaches),
        "missing_or_stale_count": len(missing_or_stale) + len(rebuild_items),
        "latest_missing_or_stale": (rebuild_items + missing_or_stale)[:5],
    }


def catch_up_latest_sessions(
    *,
    limit: Optional[int] = None,
    budget_ms: Optional[int] = None,
    max_passes: Optional[int] = None,
) -> dict:
    """Bounded chase loop for the most recent Codex JSONL records."""
    scan_limit = limit if limit is not None else watch_scan_limit()
    budget = tail_catchup_budget_milliseconds() if budget_ms is None else max(0, int(budget_ms))
    passes_cap = tail_catchup_max_passes() if max_passes is None else max(1, int(max_passes))
    deadline = time.monotonic() + (budget / 1000.0)
    passes = 0
    changed = 0
    items: list[dict[str, Any]] = []
    final_snapshot: dict[str, Any] = {}

    while passes < passes_cap:
        passes += 1
        result = scan_sessions(dry_run=False, limit=scan_limit, public=False)
        changed += int(result.get("changed", 0) or 0)
        items.extend(result.get("items", []))
        final_snapshot = raw_sync_snapshot(limit=scan_limit)
        if final_snapshot.get("missing_or_stale_count", 0) == 0:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    return {
        "ok": final_snapshot.get("missing_or_stale_count", 0) == 0 if final_snapshot else True,
        "source_system": SOURCE_SYSTEM,
        "limit": scan_limit,
        "budget_ms": budget,
        "max_passes": passes_cap,
        "passes": passes,
        "changed": changed,
        "items": items,
        "raw_sync": final_snapshot,
    }


def load_checkpoint() -> dict:
    path = checkpoint_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def save_checkpoint(data: dict) -> None:
    path = checkpoint_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _checkpoint_key(source_path: str) -> str:
    return f"{SOURCE_SYSTEM}:{os.path.abspath(os.path.expanduser(source_path))}"


def _raw_dest_for_artifact(artifact: dict) -> Path:
    project_id = _safe_segment(artifact.get("canonical_window_id") or artifact.get("project_id"), "project")
    session_id = _safe_segment(artifact.get("session_id"), "session")
    return preferred_raw_archive_path(
        memory_root(),
        computer_name=artifact.get("computer_name") or node_id(),
        source_system=SOURCE_SYSTEM,
        native_format=artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
        native_scope=project_id,
        session_id=session_id,
    )


def _write_meta(dest: Path, artifact: dict, src_stat: os.stat_result, offset: int, raw_order: int) -> None:
    meta = {
        "source_system": SOURCE_SYSTEM,
        "source_path": artifact.get("source_path", ""),
        "source_inode": src_stat.st_ino,
        "source_mtime": src_stat.st_mtime,
        "source_checksum": _file_hash(Path(artifact["source_path"])),
        "file_offset": offset,
        "raw_order": raw_order,
        "archived_to": str(dest),
        "native_artifact_format": artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
        "raw_archive_layout": "computer_first",
        "session_id": artifact.get("session_id", ""),
        "project_id": artifact.get("project_id", ""),
        "project_root": artifact.get("project_root", ""),
        "thread_name": artifact.get("thread_name", ""),
        "main_river_storage": "canonical_dialogue",
        "forensic_runtime_storage": "full_raw_archive_plus_manifest",
        "canonical_dialogue_path": str(dest) + ".canonical_dialogue.jsonl",
        "forensic_runtime_manifest_path": str(dest) + ".forensic_runtime.json",
        "last_update": ts(),
    }
    with open(str(dest) + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _meta_needs_update(dest: Path, artifact: dict, src_stat: os.stat_result, offset: int, raw_order: int) -> bool:
    meta_path = Path(str(dest) + ".meta.json")
    if not meta_path.exists():
        return True
    try:
        existing = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return True
    wanted = {
        "source_system": SOURCE_SYSTEM,
        "source_path": artifact.get("source_path", ""),
        "source_inode": src_stat.st_ino,
        "source_mtime": src_stat.st_mtime,
        "file_offset": offset,
        "raw_order": raw_order,
        "archived_to": str(dest),
        "native_artifact_format": artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
        "raw_archive_layout": "computer_first",
        "session_id": artifact.get("session_id", ""),
        "project_id": artifact.get("project_id", ""),
        "project_root": artifact.get("project_root", ""),
        "thread_name": artifact.get("thread_name", ""),
        "main_river_storage": "canonical_dialogue",
        "forensic_runtime_storage": "full_raw_archive_plus_manifest",
        "canonical_dialogue_path": str(dest) + ".canonical_dialogue.jsonl",
        "forensic_runtime_manifest_path": str(dest) + ".forensic_runtime.json",
    }
    for key, value in wanted.items():
        if existing.get(key) != value:
            return True
    return False


def _backup_polluted_raw(dest: Path) -> str:
    if not dest.exists():
        return ""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = dest.with_name(f"{dest.name}.corrupt-backup-{stamp}")
    counter = 1
    while backup.exists():
        backup = dest.with_name(f"{dest.name}.corrupt-backup-{stamp}-{counter}")
        counter += 1
    shutil.move(str(dest), str(backup))
    meta = Path(str(dest) + ".meta.json")
    if meta.exists():
        shutil.move(str(meta), str(backup) + ".meta.json")
    return str(backup)


def _register_current_window_for_artifact(artifact: dict, dest: str) -> dict:
    session_id = str(artifact.get("session_id") or "").strip()
    project_id = str(artifact.get("project_id") or artifact.get("canonical_window_id") or "").strip()
    return register_current_window(
        source_system=SOURCE_SYSTEM,
        consumer=SOURCE_SYSTEM,
        canonical_window_id=session_id or project_id,
        session_id=session_id,
        native_window_id=str(artifact.get("native_thread_id") or session_id),
        title=str(artifact.get("thread_name") or ""),
        source_path=str(dest or ""),
        binding_source="codex_session_jsonl_incremental_capture",
        confidence="observed_codex_session_change",
        metadata={
            "project_id": project_id,
            "project_root": artifact.get("project_root", ""),
            "source_refs_canonical_window_id": artifact.get("canonical_window_id", ""),
            "native_artifact_format": artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
            "raw_archive_layout": "computer_first",
            "thread_index_source": artifact.get("thread_index_source", ""),
            "codex_source": artifact.get("codex_source", ""),
            "model_provider": artifact.get("model_provider", ""),
        },
    )


def archive_session_incremental(source_path: str, dry_run: bool = False, artifact: Optional[dict] = None) -> tuple[str, str]:
    src = Path(source_path).expanduser()
    if artifact is None:
        artifact = artifact_from_path(src)
    dest = _raw_dest_for_artifact(artifact)

    try:
        src_stat = src.stat()
    except OSError:
        return str(dest), "error: cannot stat source"

    checkpoint = load_checkpoint()
    key = _checkpoint_key(str(src))
    prior = checkpoint.get(key, {})
    last_offset = int(prior.get("offset", 0) or 0)
    is_rotation = bool(prior) and prior.get("source_inode") != src_stat.st_ino
    if is_rotation:
        last_offset = 0
    elif prior and not dest.exists():
        last_offset = 0

    if not prior and dest.exists():
        try:
            dest_size = dest.stat().st_size
        except OSError:
            dest_size = 0
        if 0 < dest_size < src_stat.st_size:
            last_offset = dest_size
        if dest_size == src_stat.st_size:
            checkpoint[key] = {
                "offset": src_stat.st_size,
                "archived_to": str(dest),
                "source_inode": src_stat.st_ino,
                "source_size": src_stat.st_size,
                "source_mtime": src_stat.st_mtime,
                "raw_order": 1,
                "source_system": SOURCE_SYSTEM,
                "last_update": ts(),
                "recovered_from_existing_dest": True,
            }
            save_checkpoint(checkpoint)
            materialize_canonical_dialogue(
                dest,
                source_system=SOURCE_SYSTEM,
                session_id=str(artifact.get("session_id") or ""),
                canonical_window_id=str(artifact.get("canonical_window_id") or ""),
                native_artifact_format=artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
                reset=False,
                raw_order=1,
            )
            _write_meta(dest, artifact, src_stat, src_stat.st_size, 1)
            return str(dest), f"up_to_date(offset={src_stat.st_size}, checkpoint_recovered)"

    raw_order = int(prior.get("raw_order", 0) or 0) + (1 if is_rotation or not prior else 0)
    raw_order = max(raw_order, 1)

    rebuild_reason = ""
    backup_path = ""
    if dest.exists():
        try:
            dest_size_for_rebuild = dest.stat().st_size
        except OSError:
            dest_size_for_rebuild = 0
        if dest_size_for_rebuild > src_stat.st_size:
            rebuild_reason = f"raw_larger_than_source({dest_size_for_rebuild}>{src_stat.st_size})"
        elif last_offset > src_stat.st_size:
            rebuild_reason = f"checkpoint_ahead_of_source({last_offset}>{src_stat.st_size})"
        if rebuild_reason:
            if dry_run:
                return str(dest), f"dry_run_rebuild_needed({rebuild_reason})"
            backup_path = _backup_polluted_raw(dest)
            last_offset = 0
            raw_order += 1
            is_rotation = True

    if src_stat.st_size <= last_offset and not is_rotation:
        raw_order = int(prior.get("raw_order", 1) or 1)
        if not dry_run and dest.exists():
            dialogue_path = canonical_dialogue_sidecar_path(dest)
            forensic_path = forensic_runtime_manifest_path(dest)
            if not dialogue_path.exists() or not forensic_path.exists():
                materialize_canonical_dialogue(
                    dest,
                    source_system=SOURCE_SYSTEM,
                    session_id=str(artifact.get("session_id") or ""),
                    canonical_window_id=str(artifact.get("canonical_window_id") or ""),
                    native_artifact_format=artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
                    reset=False,
                    raw_order=raw_order,
                )
            if _meta_needs_update(dest, artifact, src_stat, last_offset, raw_order):
                _write_meta(dest, artifact, src_stat, last_offset, raw_order)
                return str(dest), f"metadata_updated(offset={last_offset})"
        return str(dest), f"up_to_date(offset={last_offset})"

    if dry_run:
        return str(dest), f"dry_run(offset={last_offset}/{src_stat.st_size})"

    dest.parent.mkdir(parents=True, exist_ok=True)

    bytes_written = 0
    lines_written = 0
    with src.open("rb") as inp, dest.open("ab") as out:
        inp.seek(last_offset)
        while True:
            chunk = inp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            bytes_written += len(chunk)
            lines_written += chunk.count(b"\n")
        new_offset = inp.tell()

    if bytes_written == 0:
        return str(dest), f"empty_append(offset={new_offset})"

    checkpoint[key] = {
        "offset": new_offset,
        "archived_to": str(dest),
        "source_inode": src_stat.st_ino,
        "source_size": src_stat.st_size,
        "source_mtime": src_stat.st_mtime,
        "raw_order": raw_order,
        "source_system": SOURCE_SYSTEM,
        "last_update": ts(),
    }
    save_checkpoint(checkpoint)
    materialize_canonical_dialogue(
        dest,
        source_system=SOURCE_SYSTEM,
        session_id=str(artifact.get("session_id") or ""),
        canonical_window_id=str(artifact.get("canonical_window_id") or ""),
        native_artifact_format=artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
        reset=is_rotation or last_offset == 0,
        raw_order=raw_order,
    )
    _write_meta(dest, artifact, src_stat, new_offset, raw_order)

    if is_rotation:
        if rebuild_reason:
            return str(dest), f"rebuilt({rebuild_reason}, backup={backup_path}, {lines_written} lines, {bytes_written} bytes)"
        return str(dest), f"rotation_detected(appended {lines_written} lines, {bytes_written} bytes)"
    if last_offset == 0:
        return str(dest), f"archived({lines_written} lines, {bytes_written} bytes)"
    return str(dest), f"appended({lines_written} lines, {bytes_written} bytes, {last_offset}->{new_offset})"


def scan_sessions(dry_run: bool = False, limit: int = 0, public: bool = False) -> dict:
    artifacts = discover_sessions(limit=limit)
    items = []
    changed = 0
    would_change = 0
    window_bindings = []
    window_binding_skipped = 0
    current_window_registered = False
    for artifact in artifacts:
        dest, status = archive_session_incremental(artifact["source_path"], dry_run=dry_run, artifact=artifact)
        changed_status = status.startswith(("archived", "appended", "rotation", "rebuilt", "metadata_updated"))
        if dry_run and status.startswith("dry_run"):
            would_change += 1
        elif changed_status:
            changed += 1
            if not current_window_registered:
                binding = _register_current_window_for_artifact(artifact, dest)
                if binding.get("ok"):
                    window_bindings.append(binding)
                    current_window_registered = True
                else:
                    window_binding_skipped += 1
        items.append({
            "source_path": _public_path_label(artifact["source_path"]) if public else artifact["source_path"],
            "dest": _public_path_label(dest) if public else dest,
            "status": status,
            "session_id": artifact.get("session_id", ""),
            "canonical_window_id": artifact.get("canonical_window_id", ""),
            "project_root": _public_path_label(artifact.get("project_root", "")) if public else artifact.get("project_root", ""),
            "thread_name": artifact.get("thread_name", ""),
        })
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "sessions_root": str(codex_sessions_root()),
        "discovered": len(artifacts),
        "changed": changed,
        "would_change": would_change,
        "window_bindings_registered": len(window_bindings),
        "window_bindings": window_bindings,
        "window_binding_skipped": window_binding_skipped,
        "dry_run": dry_run,
        "items": items,
    }


def status() -> dict:
    artifacts = discover_sessions(limit=20)
    state_index = _load_state_thread_index()
    interval_ms = watcher_interval_milliseconds()
    raw_sync = raw_sync_snapshot(limit=20)
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "sessions_root": _public_path_label(str(codex_sessions_root())),
        "session_index": _public_path_label(str(codex_session_index_path())),
        "state_thread_index": _public_path_label(str(codex_state_db_path())),
        "state_thread_index_reachable": bool(state_index.get("read_ok")),
        "state_thread_count": len(state_index.get("by_id", {})) if isinstance(state_index.get("by_id"), dict) else 0,
        "reachable": codex_sessions_root().exists(),
        "artifact_count_sample": len(artifacts),
        "latest": [public_artifact(item) for item in artifacts[:5]],
        "read_only": True,
        "source_kind": "codex_official_threads_and_session_records",
        "collector_status": "continuous_incremental",
        "capture_independent_of_mcp": True,
        "consumer_connection_required": False,
        "raw_sync": raw_sync,
        "event_driven_preferred": True,
        "poll_interval_milliseconds": interval_ms,
        "poll_interval_seconds": interval_ms / 1000.0,
        "target_latency_milliseconds": interval_ms,
        "millisecond_level": interval_ms < 1000,
        "watch_scan_limit": watch_scan_limit(),
        "tail_catchup_budget_milliseconds": tail_catchup_budget_milliseconds(),
        "tail_catchup_max_passes": tail_catchup_max_passes(),
        "raw_lag_sla_milliseconds": raw_lag_sla_milliseconds(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex local session connector")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--catch-up", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget-ms", type=int, default=None)
    parser.add_argument("--max-passes", type=int, default=None)
    args = parser.parse_args()
    if args.discover:
        print(json.dumps(discover_sessions(limit=args.limit), ensure_ascii=False, indent=2))
    elif args.catch_up:
        print(json.dumps(
            catch_up_latest_sessions(
                limit=args.limit or None,
                budget_ms=args.budget_ms,
                max_passes=args.max_passes,
            ),
            ensure_ascii=False,
            indent=2,
        ))
    elif args.scan:
        print(json.dumps(scan_sessions(dry_run=args.dry_run, limit=args.limit), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
