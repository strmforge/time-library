#!/usr/bin/env python3
"""Hermes native learning liveness checks and self-review signal receipts.

Liveness checks are read-only. The optional receipt writer records that
Time Library produced a self-review signal; it does not trigger Hermes, write
Hermes skills, or mutate raw/Zhiyi/Xingce memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from .hermes_paths import resolve_hermes_home
except Exception:  # pragma: no cover - direct script import fallback
    from hermes_paths import resolve_hermes_home

try:
    from .source_system_runtime_declarations import (
        source_system_generation_cadence,
        source_system_generation_model_hint,
        source_system_generation_scope,
        source_system_native_generation_trigger_kind,
    )
except Exception:  # pragma: no cover - direct script import fallback
    from source_system_runtime_declarations import (
        source_system_generation_cadence,
        source_system_generation_model_hint,
        source_system_generation_scope,
        source_system_native_generation_trigger_kind,
    )


NATIVE_REVIEW_PATTERNS = (
    "background_review",
    "Background review",
    "review_skills",
)
SKILL_MANAGE_PATTERNS = (
    "skill_manage",
)
LEARNING_PATTERNS = NATIVE_REVIEW_PATTERNS + SKILL_MANAGE_PATTERNS
YIFANCHEN_SKILL_MARKERS = (
    "time_library/time-library",
    "time-library",
)
SIGNAL_RECEIPT_SCHEMA_VERSION = "2026.6.1"
TRIGGER_RECEIPT_SCHEMA_VERSION = "2026.6.1"
SKILL_GENERATION_PROBE_SCHEMA_VERSION = "2026.6.1"
SKILL_ARTIFACT_STATUS_SCHEMA_VERSION = "2026.6.1"
DEFAULT_TRIGGER_TIMEOUT_SECONDS = 180
DEFAULT_TRIGGER_MAX_TURNS = 3
MAX_TRIGGER_MAX_TURNS = 12
DEFAULT_SKILL_PROBE_TIMEOUT_SECONDS = 420
DEFAULT_SKILL_PROBE_MAX_TURNS = 8
MAX_SKILL_PROBE_MAX_TURNS = 20


def _iso_from_timestamp(value: float | None) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_info(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {
            "path": str(path),
            "exists": False,
            "mtime": "",
            "size": 0,
        }
    return {
        "path": str(path),
        "exists": True,
        "mtime": _iso_from_timestamp(stat.st_mtime),
        "size": stat.st_size,
    }


def _read_text(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(max(0, size - max_bytes))
            data = f.read(max_bytes)
        return data.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _pattern_summary(text: str, patterns: tuple[str, ...]) -> dict[str, Any]:
    lines = text.splitlines()
    result: dict[str, Any] = {
        pattern: {"count": 0, "latest_line": 0}
        for pattern in patterns
    }
    for idx, line in enumerate(lines, start=1):
        for pattern in patterns:
            if pattern in line:
                result[pattern]["count"] += 1
                result[pattern]["latest_line"] = idx
    return result


def _sum_counts(summary: dict[str, Any], patterns: tuple[str, ...]) -> int:
    return sum(int(summary.get(pattern, {}).get("count", 0) or 0) for pattern in patterns)


def _latest_skill_file(hermes_home: Path) -> dict[str, Any]:
    skills_dir = hermes_home / "skills"
    result = {
        "skills_dir": str(skills_dir),
        "skills_dir_exists": skills_dir.is_dir(),
        "skill_file_count": 0,
        "latest_path": "",
        "latest_relative_path": "",
        "latest_mtime": "",
        "latest_size": 0,
        "latest_looks_like_time_library_install": False,
    }
    if not skills_dir.is_dir():
        return result

    latest_path: Path | None = None
    latest_mtime = 0.0
    count = 0
    for path in skills_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name != "SKILL.md" and "references" not in path.parts:
            continue
        count += 1
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_path = path

    result["skill_file_count"] = count
    if latest_path:
        try:
            relative = latest_path.relative_to(skills_dir).as_posix()
        except ValueError:
            relative = latest_path.as_posix()
        text_path = latest_path.as_posix()
        result.update({
            "latest_path": text_path,
            "latest_relative_path": relative,
            "latest_mtime": _iso_from_timestamp(latest_mtime),
            "latest_size": latest_path.stat().st_size,
            "latest_looks_like_time_library_install": any(marker in text_path for marker in YIFANCHEN_SKILL_MARKERS),
        })
    return result


def _file_sha(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            remaining = max_bytes
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                h.update(chunk)
                remaining -= len(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _skill_file_snapshot(hermes_home: Path) -> dict[str, Any]:
    skills_dir = hermes_home / "skills"
    result: dict[str, Any] = {
        "skills_dir": str(skills_dir),
        "skills_dir_exists": skills_dir.is_dir(),
        "file_count": 0,
        "files": {},
    }
    if not skills_dir.is_dir():
        return result

    files: dict[str, Any] = {}
    for path in sorted(skills_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name != "SKILL.md" and "references" not in path.parts:
            continue
        try:
            stat = path.stat()
            rel = path.relative_to(skills_dir).as_posix()
        except OSError:
            continue
        files[rel] = {
            "relative_path": rel,
            "path": str(path),
            "mtime": _iso_from_timestamp(stat.st_mtime),
            "size": stat.st_size,
            "sha256": _file_sha(path),
            "looks_like_time_library_install": any(marker in rel for marker in YIFANCHEN_SKILL_MARKERS),
        }
    result["file_count"] = len(files)
    result["files"] = files
    return result


def _skill_snapshot_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_files = before.get("files", {}) if isinstance(before.get("files"), dict) else {}
    after_files = after.get("files", {}) if isinstance(after.get("files"), dict) else {}
    added: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []

    for rel, after_item in after_files.items():
        before_item = before_files.get(rel)
        if not before_item:
            added.append(after_item)
            continue
        if (
            before_item.get("sha256") != after_item.get("sha256")
            or before_item.get("size") != after_item.get("size")
            or before_item.get("mtime") != after_item.get("mtime")
        ):
            modified.append(after_item)
    for rel, before_item in before_files.items():
        if rel not in after_files:
            removed.append(before_item)

    changed = added + modified
    non_time_library_changed = [
        item for item in changed
        if not item.get("looks_like_time_library_install")
    ]
    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "added_count": len(added),
        "modified_count": len(modified),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "non_time_library_changed_count": len(non_time_library_changed),
        "non_time_library_changed": non_time_library_changed,
    }


def _latest_json_artifact(directory: Path, pattern: str, id_field: str) -> dict[str, Any]:
    result = {
        "dir": str(directory),
        "dir_exists": directory.is_dir(),
        "latest_path": "",
        "latest_mtime": "",
        "latest_id": "",
        "latest_status": "",
        "experience_upgrade_ready": False,
        "production_experience_write_performed": False,
    }
    if not directory.is_dir():
        return result
    latest_path: Path | None = None
    latest_mtime = 0.0
    for path in directory.glob(pattern):
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_path = path
    if not latest_path:
        return result
    result["latest_path"] = str(latest_path)
    result["latest_mtime"] = _iso_from_timestamp(latest_mtime)
    try:
        data = json.loads(latest_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if isinstance(data, dict):
        result["latest_id"] = str(data.get(id_field, "") or "")
        result["latest_status"] = str(
            data.get("upgrade_input_status", "")
            or data.get("lifecycle_status", "")
            or data.get("action_status", "")
            or ""
        )
        result["experience_upgrade_ready"] = bool(data.get("experience_upgrade_ready", False))
        result["production_experience_write_performed"] = bool(data.get("production_experience_write_performed", False))
    return result


def _feedback_artifacts(memcore_root: str | Path | None) -> dict[str, Any]:
    if not memcore_root:
        return {
            "available": False,
            "reason": "memcore_root_not_provided",
        }
    root = Path(memcore_root)
    base = root / "output" / "hermes_experience_feedback"
    candidates = _latest_json_artifact(base / "candidates", "hermes-feedback-*.json", "candidate_id")
    upgrades = _latest_json_artifact(base / "upgrade_inputs", "hermes-upgrade-input-*.json", "upgrade_input_id")
    return {
        "available": True,
        "base_dir": str(base),
        "candidates": candidates,
        "upgrade_inputs": upgrades,
    }


def _signal_receipts_dir(memcore_root: str | Path | None) -> Path | None:
    if not memcore_root:
        return None
    return Path(memcore_root).expanduser() / "output" / "hermes_native_learning" / "self_review_signals"


def _safe_token(value: Any, fallback: str = "operator") -> str:
    raw = str(value or "").strip().lower()
    safe = re.sub(r"[^a-z0-9._-]+", "-", raw).strip(".-_")
    return safe[:80] or fallback


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "确认", "是"}


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_text(value: Any, max_chars: int = 1200) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 16)].rstrip() + "\n...[truncated]"


def _resolve_hermes_cli(explicit_path: str = "") -> str:
    candidates = []
    if explicit_path:
        candidates.append(explicit_path)
    env_path = os.environ.get("HERMES_CLI_PATH", "")
    if env_path:
        candidates.append(env_path)
    which = shutil.which("hermes")
    if which:
        candidates.append(which)
    candidates.extend([
        str(Path.home() / ".local" / "bin" / "hermes"),
        "/usr/local/bin/hermes",
        "/opt/homebrew/bin/hermes",
    ])
    for candidate in candidates:
        expanded = os.path.expanduser(str(candidate or ""))
        if expanded and os.path.exists(expanded):
            return expanded
    return ""


def _latest_signal_receipt(memcore_root: str | Path | None) -> dict[str, Any]:
    directory = _signal_receipts_dir(memcore_root)
    result = {
        "available": bool(directory),
        "dir": str(directory) if directory else "",
        "dir_exists": bool(directory and directory.is_dir()),
        "latest_path": "",
        "latest_receipt_id": "",
        "latest_signal_id": "",
        "latest_status": "",
        "latest_mtime": "",
    }
    if not directory or not directory.is_dir():
        return result
    latest_path: Path | None = None
    latest_mtime = 0.0
    for path in directory.glob("hermes-self-review-receipt-*.json"):
        if not path.is_file():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_path = path
    if not latest_path:
        return result
    result["latest_path"] = str(latest_path)
    result["latest_mtime"] = _iso_from_timestamp(latest_mtime)
    try:
        data = json.loads(latest_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if isinstance(data, dict):
        result["latest_receipt_id"] = str(data.get("receipt_id") or "")
        result["latest_signal_id"] = str(data.get("signal_id") or "")
        result["latest_status"] = str(data.get("receipt_status") or "")
    return result


def _trigger_receipts_dir(memcore_root: str | Path | None) -> Path | None:
    if not memcore_root:
        return None
    return Path(memcore_root).expanduser() / "output" / "hermes_native_learning" / "triggers"


def _skill_probe_receipts_dir(memcore_root: str | Path | None) -> Path | None:
    if not memcore_root:
        return None
    return Path(memcore_root).expanduser() / "output" / "hermes_native_learning" / "skill_generation_probes"


def _skill_artifact_status_dir(memcore_root: str | Path | None) -> Path | None:
    if not memcore_root:
        return None
    return Path(memcore_root).expanduser() / "output" / "hermes_native_learning" / "skill_artifact_status"


def _trigger_receipt_summary(data: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    trigger = data.get("hermes_trigger", {}) if isinstance(data.get("hermes_trigger"), dict) else {}
    before = data.get("liveness_before", {}) if isinstance(data.get("liveness_before"), dict) else {}
    after = data.get("liveness_after", {}) if isinstance(data.get("liveness_after"), dict) else {}
    native = data.get("native_observation", {}) if isinstance(data.get("native_observation"), dict) else {}
    return {
        "trigger_id": str(data.get("trigger_id") or ""),
        "receipt_status": str(data.get("receipt_status") or ""),
        "recorded_at": str(data.get("recorded_at") or ""),
        "requested_by": str(data.get("requested_by") or ""),
        "reason": str(data.get("reason") or ""),
        "source_path": str(path or ""),
        "hermes_trigger_called": bool(trigger.get("called", False)),
        "exit_code": trigger.get("exit_code"),
        "timed_out": bool(trigger.get("timed_out", False)),
        "elapsed_seconds": trigger.get("elapsed_seconds", 0),
        "stdout_excerpt": _bounded_text(trigger.get("stdout_excerpt", ""), 800),
        "stderr_excerpt": _bounded_text(trigger.get("stderr_excerpt", ""), 600),
        "runtime_error": str(trigger.get("error") or ""),
        "liveness_before_status": str(before.get("status") or ""),
        "liveness_after_status": str(after.get("status") or ""),
        "native_skill_write_observed_after_trigger": bool(native.get("skill_write_observed_after_trigger", False)),
        "feedback_candidates_dir_exists": bool(native.get("feedback_candidates_dir_exists", False)),
        "upgrade_inputs_dir_exists": bool(native.get("upgrade_inputs_dir_exists", False)),
        "write_boundary": data.get("write_boundary", {}) if isinstance(data.get("write_boundary"), dict) else {},
    }


def _latest_trigger_receipt(memcore_root: str | Path | None) -> dict[str, Any]:
    directory = _trigger_receipts_dir(memcore_root)
    result = {
        "available": bool(directory),
        "dir": str(directory) if directory else "",
        "dir_exists": bool(directory and directory.is_dir()),
        "latest_path": "",
        "latest_trigger_id": "",
        "latest_status": "",
        "latest_exit_code": None,
        "latest_mtime": "",
        "latest_summary": {},
    }
    if not directory or not directory.is_dir():
        return result
    latest_path = directory / "latest.json"
    if not latest_path.exists():
        candidates = [path for path in directory.glob("*.json") if path.name != "latest.json"]
        candidates.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
        latest_path = candidates[0] if candidates else latest_path
    if not latest_path.exists():
        return result
    result["latest_path"] = str(latest_path)
    try:
        result["latest_mtime"] = _iso_from_timestamp(latest_path.stat().st_mtime)
        data = json.loads(latest_path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if isinstance(data, dict):
        summary = _trigger_receipt_summary(data, latest_path)
        result["latest_summary"] = summary
        result["latest_trigger_id"] = summary.get("trigger_id", "")
        result["latest_status"] = summary.get("receipt_status", "")
        result["latest_exit_code"] = summary.get("exit_code")
    return result


def _skill_probe_receipt_summary(data: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    trigger = data.get("hermes_trigger", {}) if isinstance(data.get("hermes_trigger"), dict) else {}
    observation = data.get("skill_generation_observation", {}) if isinstance(data.get("skill_generation_observation"), dict) else {}
    write_boundary = data.get("write_boundary", {}) if isinstance(data.get("write_boundary"), dict) else {}
    result = {
        "probe_id": str(data.get("probe_id") or ""),
        "receipt_path": str(path) if path else "",
        "recorded_at": str(data.get("recorded_at") or ""),
        "requested_by": str(data.get("requested_by") or ""),
        "reason": str(data.get("reason") or ""),
        "hermes_trigger_called": bool(trigger.get("called", False)),
        "exit_code": trigger.get("exit_code"),
        "timed_out": bool(trigger.get("timed_out", False)),
        "elapsed_seconds": trigger.get("elapsed_seconds", 0),
        "runtime_error": str(trigger.get("error") or ""),
        "stdout_excerpt": _bounded_text(trigger.get("stdout_excerpt", ""), 600),
        "stderr_excerpt": _bounded_text(trigger.get("stderr_excerpt", ""), 600),
        "background_review_seen": bool(observation.get("background_review_seen", False)),
        "skill_manage_seen": bool(observation.get("skill_manage_seen", False)),
        "skill_file_changed": bool(observation.get("skill_file_changed", False)),
        "skill_generation_success": bool(observation.get("skill_generation_success", False)),
        "skill_generation_stage": str(observation.get("skill_generation_stage") or ""),
        "changed_skill_file_count": observation.get("changed_skill_file_count", 0),
        "write_boundary": write_boundary,
    }
    return result


def _read_latest_skill_probe_receipt(
    memcore_root: str | Path | None,
    explicit_path: str | Path | None = None,
) -> tuple[dict[str, Any], Path | None, str]:
    path: Path | None = None
    if explicit_path:
        path = Path(explicit_path).expanduser()
    else:
        directory = _skill_probe_receipts_dir(memcore_root)
        path = directory / "latest.json" if directory else None
    if not path:
        return {}, None, "memcore_root_required"
    if not path.exists():
        return {}, path, "skill_generation_probe_receipt_not_found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, path, f"skill_generation_probe_receipt_parse_error:{str(exc)[:120]}"
    if not isinstance(data, dict):
        return {}, path, "skill_generation_probe_receipt_not_object"
    return data, path, ""



def query_hermes_self_review_triggers(
    *,
    memcore_root: str | Path | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Read recorded Hermes self-review trigger receipts without mutation."""
    directory = _trigger_receipts_dir(memcore_root)
    limit = _safe_int(limit, 20, 1, 100)
    items: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    if directory and directory.is_dir():
        paths = [path for path in directory.glob("*.json") if path.name != "latest.json"]
        paths.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
        for path in paths[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                parse_errors.append({"path": str(path), "error": str(exc)[:160]})
                continue
            if isinstance(data, dict):
                items.append(_trigger_receipt_summary(data, path))
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "trigger_receipt_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed_by_time_library": False,
        "hermes_skill_write_performed_by_time_library": False,
        "dir": str(directory) if directory else "",
        "dir_exists": bool(directory and directory.is_dir()),
        "latest": _latest_trigger_receipt(memcore_root),
        "items": items,
        "count": len(items),
        "parse_errors": parse_errors,
        "notes": [
            "trigger_receipts_are_observation_records",
            "trigger_called_hermes_but_time_library_did_not_write_hermes_skill",
            "detected_model_facts_are_not_runnable_proof",
        ],
    }


def query_hermes_skill_generation_probes(
    *,
    memcore_root: str | Path | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Read recorded Hermes skill generation probe receipts without mutation."""
    directory = _skill_probe_receipts_dir(memcore_root)
    items: list[dict[str, Any]] = []
    if directory and directory.is_dir():
        for path in sorted(directory.glob("*.json"), reverse=True):
            if path.name == "latest.json":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append(_skill_probe_receipt_summary(data, path))
            if len(items) >= limit:
                break
    latest: dict[str, Any] = {
        "available": False,
        "latest_path": "",
        "latest_probe_id": "",
    }
    latest_path = directory / "latest.json" if directory else None
    if latest_path and latest_path.exists():
        try:
            data = json.loads(latest_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if isinstance(data, dict):
            summary = _skill_probe_receipt_summary(data, latest_path)
            latest.update(summary)
            latest["available"] = True
            latest["latest_path"] = str(latest_path)
            latest["latest_probe_id"] = summary.get("probe_id", "")
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "probe_receipt_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed_by_time_library": False,
        "hermes_skill_write_performed_by_time_library": False,
        "directory": str(directory) if directory else "",
        "directory_exists": bool(directory and directory.is_dir()),
        "latest": latest,
        "items": items,
        "count": len(items),
        "notes": [
            "skill_generation_probe_receipts_are_observation_records",
            "probe_called_hermes_but_time_library_did_not_write_hermes_skill",
        ],
    }


try:
    from .hermes_skill_artifact_status import (
        HERMES_SKILL_ARTIFACT_STATUS_CONTRACT,
        get_hermes_skill_artifact_status_contract,
        build_hermes_skill_artifact_status_dry_run,
        record_hermes_skill_artifact_status,
        query_hermes_skill_artifact_statuses,
    )
except Exception:  # pragma: no cover - direct script import fallback
    from hermes_skill_artifact_status import (
        HERMES_SKILL_ARTIFACT_STATUS_CONTRACT,
        get_hermes_skill_artifact_status_contract,
        build_hermes_skill_artifact_status_dry_run,
        record_hermes_skill_artifact_status,
        query_hermes_skill_artifact_statuses,
    )

# Hermes skill artifact status lives in hermes_skill_artifact_status.py under
# tiandao_hermes_skill_artifact_status_observation.v1. Names are re-exported
# here for compatibility with existing console and experience callers.

def _native_review_signal(
    *,
    hermes_home: Path,
    memcore_root: str | Path | None,
    cold_after_hours: int,
    liveness_status: str,
    cold_reasons: list[str],
    latest_skill: dict[str, Any],
    checked_at: str,
) -> dict[str, Any]:
    signal_seed = "|".join(
        [
            str(hermes_home),
            str(memcore_root or ""),
            str(cold_after_hours),
            liveness_status,
            ",".join(cold_reasons),
            str(latest_skill.get("latest_path") or ""),
            checked_at,
        ]
    )
    signal_id = "hermes-self-review-" + hashlib.sha256(signal_seed.encode("utf-8")).hexdigest()[:16]
    root = Path(memcore_root).expanduser() if memcore_root else None
    logical_roots = [
        "raw/",
        "memory/",
        "zhiyi/",
        "output/hermes_experience_feedback/",
    ]
    local_roots = []
    if root is not None:
        for rel in ("raw", "memory", "zhiyi", "output/hermes_experience_feedback"):
            candidate = root / rel
            if candidate.exists():
                local_roots.append(str(candidate))
    return {
        "signal_id": signal_id,
        "signal_type": "hermes_self_review_signal",
        "signal_version": "1.0",
        "signal_status": "wake_signal" if liveness_status == "cold" else "monitor_signal",
        "read_only": True,
        "write_performed": False,
        "scope": {
            "read_scope": "all_raw_memory",
            "read_hint": "这一片都是你该去读的原始记忆",
            "cold_after_hours": cold_after_hours,
            "logical_roots": logical_roots,
            "local_roots": local_roots,
        },
        "pointers": {
            "agent_log": {
                "path": str(hermes_home / "logs" / "agent.log"),
                "kind": "log",
            },
            "errors_log": {
                "path": str(hermes_home / "logs" / "errors.log"),
                "kind": "log",
            },
            "latest_skill_file": {
                "path": latest_skill.get("latest_path", ""),
                "relative_path": latest_skill.get("latest_relative_path", ""),
                "kind": "skill_file",
            },
            "feedback_candidates_dir": {
                "path": str((Path(memcore_root) if memcore_root else Path("")) / "output" / "hermes_experience_feedback" / "candidates"),
                "kind": "directory",
            },
            "feedback_upgrade_inputs_dir": {
                "path": str((Path(memcore_root) if memcore_root else Path("")) / "output" / "hermes_experience_feedback" / "upgrade_inputs"),
                "kind": "directory",
            },
        },
        "instructions": [
            "Hermes should inspect the underlying raw/source_refs itself.",
            "This whole area is yours to read.",
            "Do not treat this as a summary pack.",
            "Do not install, activate, or write from this signal.",
        ],
        "notes": [
            "signal_only",
            "no_summary_pack",
            "raw_paths_not_content",
            "hermes_reads_itself",
            "time_library_observes_native_feedback_only",
        ],
    }


def build_hermes_self_review_wake_dry_run(
    *,
    hermes_home: str | Path | None = None,
    memcore_root: str | Path | None = None,
    cold_after_hours: int = 72,
    requested_by: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Build an observable wake plan without triggering Hermes or writing files."""
    liveness = build_hermes_native_learning_liveness(
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
    )
    signal = liveness.get("self_review_signal", {})
    signal_id = str(signal.get("signal_id") or "")
    receipt_seed = "|".join([
        signal_id,
        _safe_token(requested_by, "operator"),
        str(cold_after_hours),
    ])
    receipt_id = "hermes-self-review-receipt-" + hashlib.sha256(receipt_seed.encode("utf-8")).hexdigest()[:16]
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "signal_receipt_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "schema_version": SIGNAL_RECEIPT_SCHEMA_VERSION,
        "liveness_status": liveness.get("liveness_status", ""),
        "cold_reasons": liveness.get("cold_reasons", []),
        "self_review_signal": signal,
        "receipt_draft": {
            "receipt_id": receipt_id,
            "receipt_status": "draft_ready_for_authorized_record",
            "signal_id": signal_id,
            "requested_by": requested_by,
            "reason": reason,
            "target_dir": str(_signal_receipts_dir(memcore_root) or ""),
        },
        "wake_plan": {
            "plan_type": "hermes_self_review_wake_signal",
            "ready_for_receipt": bool(signal_id),
            "delivery_state": "not_delivered",
            "requires_authorization_to_record_receipt": True,
            "requires_separate_runtime_integration_to_trigger_hermes": True,
            "does_not_package_zhiyi_summary": True,
            "does_not_limit_to_platform": True,
            "read_scope": signal.get("scope", {}).get("read_scope", ""),
            "read_hint": signal.get("scope", {}).get("read_hint", ""),
        },
        "latest_receipt": _latest_signal_receipt(memcore_root),
        "notes": [
            "dry_run_only",
            "does_not_trigger_hermes",
            "does_not_write_hermes_skill",
            "receipt_recording_is_separate_from_native_review",
        ],
    }


def build_hermes_self_review_trigger_plan(
    body: dict[str, Any] | None = None,
    *,
    hermes_home: str | Path | None = None,
    memcore_root: str | Path | None = None,
    cold_after_hours: int = 72,
) -> dict[str, Any]:
    """Describe the authorized live trigger without calling Hermes."""
    body = body if isinstance(body, dict) else {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else {}
    requested_by = str(authorization.get("operator") or body.get("operator") or body.get("requested_by") or "").strip()
    reason = str(authorization.get("reason") or body.get("reason") or "").strip()
    wake = build_hermes_self_review_wake_dry_run(
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
        requested_by=requested_by,
        reason=reason,
    )
    signal = wake.get("self_review_signal", {})
    timeout_seconds = _safe_int(
        body.get("timeout_seconds", authorization.get("timeout_seconds", DEFAULT_TRIGGER_TIMEOUT_SECONDS)),
        DEFAULT_TRIGGER_TIMEOUT_SECONDS,
        15,
        900,
    )
    max_turns = _safe_int(
        body.get("max_turns", authorization.get("max_turns", DEFAULT_TRIGGER_MAX_TURNS)),
        DEFAULT_TRIGGER_MAX_TURNS,
        1,
        MAX_TRIGGER_MAX_TURNS,
    )
    cli = _resolve_hermes_cli(str(body.get("hermes_cli") or authorization.get("hermes_cli") or ""))
    trigger_seed = "|".join([
        str(signal.get("signal_id") or ""),
        _safe_token(requested_by, "operator"),
        reason,
        str(timeout_seconds),
        str(max_turns),
    ])
    trigger_id = "hermes-self-review-trigger-" + hashlib.sha256(trigger_seed.encode("utf-8")).hexdigest()[:16]
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "trigger_id": trigger_id,
        "schema_version": TRIGGER_RECEIPT_SCHEMA_VERSION,
        "hermes_cli": cli,
        "hermes_cli_found": bool(cli),
        "timeout_seconds": timeout_seconds,
        "max_turns": max_turns,
        "wake": wake,
        "self_review_signal": signal,
        "authorization_required": [
            "confirm_live_hermes_trigger",
            "confirm_hermes_may_read_raw_source_refs",
            "confirm_hermes_native_artifacts_allowed",
            "confirm_no_time_library_raw_zhiyi_xingce_write",
            "operator",
            "reason",
        ],
        "write_boundary": {
            "trigger_receipt_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed_by_time_library": False,
            "hermes_native_artifacts_may_be_written_by_hermes": True,
            "hermes_skill_write_performed_by_time_library": False,
            "openclaw_write_performed": False,
            "platform_write_performed_by_time_library": False,
        },
        "notes": [
            "plan_only",
            "trigger_is_separate_from_wake_signal",
            "live_trigger_may_start_hermes",
            "hermes_must_read_raw_source_refs_itself",
            "time_library_does_not_write_hermes_skill",
        ],
    }


def _build_hermes_self_review_prompt(signal: dict[str, Any], reason: str = "") -> str:
    scope = signal.get("scope", {}) if isinstance(signal.get("scope"), dict) else {}
    pointers = signal.get("pointers", {}) if isinstance(signal.get("pointers"), dict) else {}
    local_roots = scope.get("local_roots", []) if isinstance(scope.get("local_roots"), list) else []
    logical_roots = scope.get("logical_roots", []) if isinstance(scope.get("logical_roots"), list) else []
    pointer_lines = []
    for name, value in pointers.items():
        if isinstance(value, dict) and value.get("path"):
            pointer_lines.append(f"- {name}: {value.get('path')}")
    return (
        "你是 Hermes，请做一次Time Library原始记忆自审。\n"
        "这不是摘要包，也不是让Time Library替你写 skill。你需要自己读取下面的 raw/source_refs 区域，"
        "判断是否存在值得沉淀为 Hermes native skill 或经验反馈的内容。\n\n"
        f"触发原因: {reason or 'Hermes native learning liveness is cold'}\n"
        f"read_scope: {scope.get('read_scope', 'all_raw_memory')}\n"
        f"read_hint: {scope.get('read_hint', '这一片都是你该去读的原始记忆')}\n"
        f"logical_roots: {json.dumps(logical_roots, ensure_ascii=False)}\n"
        f"local_roots: {json.dumps(local_roots, ensure_ascii=False)}\n"
        "pointers:\n"
        + ("\n".join(pointer_lines) if pointer_lines else "- none")
        + "\n\n"
        "要求:\n"
        "1. 先检查原始记忆和 source_refs，不要只看知意摘要。\n"
        "2. 如果发现可复用经验，请输出候选标题、来源路径、原话片段、适用场景、验收条件。\n"
        "3. 如果你选择写 Hermes native artifact/skill，必须由 Hermes 自己完成，Time Library不替你写。\n"
        "4. 不要修改Time Library raw/zhiyi/xingce/toolbook/errata。\n"
        "5. 最后用 JSON fenced block 输出 review_status、files_read_count、candidate_count、actions_taken。\n"
    )


def _build_hermes_skill_generation_probe_prompt(signal: dict[str, Any], reason: str = "") -> str:
    scope = signal.get("scope", {}) if isinstance(signal.get("scope"), dict) else {}
    pointers = signal.get("pointers", {}) if isinstance(signal.get("pointers"), dict) else {}
    pointer_lines = []
    for name, value in pointers.items():
        if isinstance(value, dict) and value.get("path"):
            pointer_lines.append(f"- {name}: {value.get('path')}")
    return (
        "你是 Hermes。请做一次 native skill generation probe。\n"
        "这不是让Time Library替你写 skill，也不是输出普通自审报告。"
        "你需要自己读取Time Library raw/source_refs，判断是否存在足够稳定、可复用、可验收的工作方法。\n\n"
        f"触发原因: {reason or 'verify Hermes native skill generation trigger'}\n"
        f"read_scope: {scope.get('read_scope', 'all_raw_memory')}\n"
        f"read_hint: {scope.get('read_hint', '这一片都是你该去读的原始记忆')}\n"
        "pointers:\n"
        + ("\n".join(pointer_lines) if pointer_lines else "- none")
        + "\n\n"
        "任务:\n"
        "1. 先读取原始记忆和 source_refs，不要只看知意摘要。\n"
        "2. 找一条小而稳定的工作方法，适合作为 Hermes native skill candidate。\n"
        "3. 如果 Hermes 运行时允许使用 skill/tool 管理能力，请由 Hermes 自己创建或更新一个 scratch/test skill；"
        "Time Library不得替你写 skill。\n"
        "4. 如果不能创建 skill，请明确说明阻塞原因，例如 tool_call_not_available、policy_not_triggered、"
        "insufficient_evidence、provider_no_tool_use。\n"
        "5. 不要修改Time Library raw/zhiyi/xingce/toolbook/errata。\n"
        "6. 最后用 JSON fenced block 输出: probe_status、files_read_count、candidate_title、"
        "skill_action_attempted、skill_action_result、blocker。\n"
    )


def _build_hermes_native_generation_trigger_prompt(signal: dict[str, Any], *, cadence: str, model_hint: str, generation_scope: str) -> str:
    scope = signal.get("scope", {}) if isinstance(signal.get("scope"), dict) else {}
    pointers = signal.get("pointers", {}) if isinstance(signal.get("pointers"), dict) else {}
    pointer_lines = []
    for name, value in pointers.items():
        if isinstance(value, dict) and value.get("path"):
            pointer_lines.append(f"- {name}: {value.get('path')}")
    return (
        "你是 Hermes。请在夜间例行回顾里做一次 native skill generation。\n"
        "这条提示由 Time Library 生成，用来提醒你读新增 raw/source_refs，"
        "再决定是否由 Hermes 自己生成或升级 native skill。\n\n"
        f"cadence: {cadence or 'nightly'}\n"
        f"model_hint: {model_hint or 'large_model'}\n"
        f"generation_scope: {generation_scope or 'read_only_new_raw'}\n"
        f"read_scope: {scope.get('read_scope', 'all_raw_memory')}\n"
        f"read_hint: {scope.get('read_hint', '这一片都是你该去读的原始记忆')}\n"
        "pointers:\n"
        + ("\n".join(pointer_lines) if pointer_lines else "- none")
        + "\n\n"
        "任务:\n"
        "1. 先读新增 raw/source_refs，不要把知意摘要当原始来源。\n"
        "2. 只挑小而稳定、可复用、可验收的工作方法。\n"
        "3. 如 Hermes 运行时允许，请由 Hermes 自己创建或升级 native skill；Time Library只提供触发计划，不替你写 skill。\n"
        "4. 如果这轮不该产 skill，请明确 blocker，例如 insufficient_evidence、tool_call_not_available、policy_not_triggered。\n"
        "5. 不要修改Time Library raw/zhiyi/xingce/toolbook/errata。\n"
    )


def build_hermes_native_generation_trigger_plan(
    body: dict[str, Any] | None = None,
    *,
    hermes_home: str | Path | None = None,
    memcore_root: str | Path | None = None,
    cold_after_hours: int = 72,
) -> dict[str, Any]:
    """Describe a declaration-driven Hermes native generation trigger without applying cron."""
    body = body if isinstance(body, dict) else {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else {}
    requested_by = str(authorization.get("operator") or body.get("operator") or body.get("requested_by") or "").strip()
    reason = str(authorization.get("reason") or body.get("reason") or "").strip()
    trigger_kind = source_system_native_generation_trigger_kind("hermes")
    cadence = source_system_generation_cadence("hermes") or "nightly"
    model_hint = source_system_generation_model_hint("hermes") or "large_model"
    generation_scope = source_system_generation_scope("hermes") or "read_only_new_raw"
    wake = build_hermes_self_review_wake_dry_run(
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
        requested_by=requested_by,
        reason=reason,
    )
    signal = wake.get("self_review_signal", {})
    prompt = _build_hermes_native_generation_trigger_prompt(
        signal,
        cadence=cadence,
        model_hint=model_hint,
        generation_scope=generation_scope,
    )
    cli = _resolve_hermes_cli(str(body.get("hermes_cli") or authorization.get("hermes_cli") or ""))
    command_preview = []
    if cli and trigger_kind == "hermes_cron":
        command_preview = [
            cli,
            "cron",
            "create",
            "--name",
            "time-library-hermes-native-generation",
            "--schedule",
            cadence,
            "--model",
            model_hint,
            "--source",
            "time-library-hermes-native-generation",
            "--prompt",
            "[native-generation prompt omitted in command preview]",
        ]
    plan_seed = "|".join([
        str(signal.get("signal_id") or ""),
        trigger_kind,
        cadence,
        model_hint,
        generation_scope,
    ])
    plan_id = "hermes-native-generation-trigger-" + hashlib.sha256(plan_seed.encode("utf-8")).hexdigest()[:16]
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "plan_id": plan_id,
        "system": "hermes",
        "native_generation_trigger_kind": trigger_kind,
        "generation_cadence": cadence,
        "generation_model_hint": model_hint,
        "generation_scope": generation_scope,
        "hermes_cli": cli,
        "hermes_cli_found": bool(cli),
        "self_review_signal": signal,
        "wake": wake,
        "prompt": prompt,
        "prompt_preview": _bounded_text(prompt, 1600),
        "command_preview": command_preview,
        "command_family": "hermes_cron_create" if trigger_kind == "hermes_cron" else "none",
        "requires_user_confirmation_before_apply": True,
        "apply_status": "plan_only_confirmation_required",
        "post_trigger_observation_path": {
            "query_skill_generation_probes": "query_hermes_skill_generation_probes",
            "query_skill_artifact_statuses": "query_hermes_skill_artifact_statuses",
            "experience_diff": "hermes_skill_experience_diff",
        },
        "notes": [
            "declaration_driven_trigger_plan",
            "plan_only_no_cron_registration",
            "user_confirmation_required_before_apply",
            "trigger_outputs_flow_into_observation_then_experience_diff",
        ],
        "non_claims": [
            "does_not_register_cron",
            "does_not_trigger_hermes_now",
            "does_not_write_hermes_skill",
            "does_not_write_time_library_raw_or_shelves",
        ],
    }


def build_hermes_skill_generation_probe_plan(
    body: dict[str, Any] | None = None,
    *,
    hermes_home: str | Path | None = None,
    memcore_root: str | Path | None = None,
    cold_after_hours: int = 72,
) -> dict[str, Any]:
    """Describe the authorized Hermes native skill generation probe."""
    body = body if isinstance(body, dict) else {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else {}
    requested_by = str(authorization.get("operator") or body.get("operator") or body.get("requested_by") or "").strip()
    reason = str(authorization.get("reason") or body.get("reason") or "").strip()
    wake = build_hermes_self_review_wake_dry_run(
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
        requested_by=requested_by,
        reason=reason,
    )
    signal = wake.get("self_review_signal", {})
    timeout_seconds = _safe_int(
        body.get("timeout_seconds", authorization.get("timeout_seconds", DEFAULT_SKILL_PROBE_TIMEOUT_SECONDS)),
        DEFAULT_SKILL_PROBE_TIMEOUT_SECONDS,
        30,
        1800,
    )
    max_turns = _safe_int(
        body.get("max_turns", authorization.get("max_turns", DEFAULT_SKILL_PROBE_MAX_TURNS)),
        DEFAULT_SKILL_PROBE_MAX_TURNS,
        1,
        MAX_SKILL_PROBE_MAX_TURNS,
    )
    cli = _resolve_hermes_cli(str(body.get("hermes_cli") or authorization.get("hermes_cli") or ""))
    probe_seed = "|".join([
        str(signal.get("signal_id") or ""),
        _safe_token(requested_by, "operator"),
        reason,
        str(timeout_seconds),
        str(max_turns),
        "native-skill-generation-probe",
    ])
    probe_id = "hermes-skill-generation-probe-" + hashlib.sha256(probe_seed.encode("utf-8")).hexdigest()[:16]
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "probe_id": probe_id,
        "schema_version": SKILL_GENERATION_PROBE_SCHEMA_VERSION,
        "hermes_cli": cli,
        "hermes_cli_found": bool(cli),
        "timeout_seconds": timeout_seconds,
        "max_turns": max_turns,
        "wake": wake,
        "self_review_signal": signal,
        "probe_goal": "verify_whether_hermes_native_background_review_can_create_or_update_skill_from_time_library_raw_source_refs",
        "stage_gates": {
            "a_hermes_trigger_success": "Hermes CLI exits 0",
            "b_native_review_signal": "background_review or skill_manage appears in Hermes logs",
            "c_skill_artifact_change": "non-Time Library skill file is added or modified",
        },
        "authorization_required": [
            "confirm_live_hermes_skill_generation_probe",
            "confirm_hermes_may_read_raw_source_refs",
            "confirm_hermes_native_skill_artifacts_allowed",
            "confirm_no_time_library_raw_zhiyi_xingce_write",
            "operator",
            "reason",
        ],
        "write_boundary": {
            "probe_receipt_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed_by_time_library": False,
            "hermes_native_artifacts_may_be_written_by_hermes": True,
            "hermes_skill_write_performed_by_time_library": False,
            "openclaw_write_performed": False,
            "platform_write_performed_by_time_library": False,
        },
        "notes": [
            "plan_only",
            "probe_may_start_hermes",
            "probe_does_not_claim_skill_success_without_file_diff",
            "time_library_does_not_write_hermes_skill",
        ],
    }


def trigger_hermes_skill_generation_probe(
    body: dict[str, Any] | None = None,
    *,
    hermes_home: str | Path | None = None,
    memcore_root: str | Path | None = None,
    cold_after_hours: int = 72,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, Any]:
    """Run a Hermes native skill generation probe and record observation only."""
    body = body if isinstance(body, dict) else {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else {}
    requested_by = str(authorization.get("operator") or body.get("operator") or body.get("requested_by") or "").strip()
    reason = str(authorization.get("reason") or body.get("reason") or "").strip()

    def confirmed(name: str) -> bool:
        return _truthy(authorization.get(name, body.get(name)))

    checks = {
        "confirm_live_hermes_skill_generation_probe": confirmed("confirm_live_hermes_skill_generation_probe"),
        "confirm_hermes_may_read_raw_source_refs": confirmed("confirm_hermes_may_read_raw_source_refs"),
        "confirm_hermes_native_skill_artifacts_allowed": confirmed("confirm_hermes_native_skill_artifacts_allowed"),
        "confirm_no_time_library_raw_zhiyi_xingce_write": confirmed("confirm_no_time_library_raw_zhiyi_xingce_write"),
        "operator": bool(requested_by),
        "reason": bool(reason),
    }
    missing = [name for name, ok in checks.items() if not ok]
    plan = build_hermes_skill_generation_probe_plan(
        body,
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
    )
    directory = _skill_probe_receipts_dir(memcore_root)
    guard_failures = []
    if not directory:
        guard_failures.append("memcore_root_required")
    if not plan.get("hermes_cli"):
        guard_failures.append("hermes_cli_not_found")
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_capable": True,
            "write_performed": False,
            "probe_receipt_write_performed": False,
            "hermes_trigger_called": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed_by_time_library": False,
            "hermes_skill_write_performed_by_time_library": False,
            "openclaw_write_performed": False,
            "missing_authorization": missing,
            "guard_failures": guard_failures,
            "plan": plan,
        }

    assert directory is not None
    home = Path(hermes_home).expanduser() if hermes_home else resolve_hermes_home()
    before_liveness = build_hermes_native_learning_liveness(
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
    )
    before_skills = _skill_file_snapshot(home)
    before_log = _read_text(home / "logs" / "agent.log")
    before_patterns = _pattern_summary(before_log, LEARNING_PATTERNS)
    before_review_count = _sum_counts(before_patterns, NATIVE_REVIEW_PATTERNS)
    before_skill_manage_count = _sum_counts(before_patterns, SKILL_MANAGE_PATTERNS)

    signal = plan.get("self_review_signal", {})
    prompt = _build_hermes_skill_generation_probe_prompt(signal, reason=reason)
    command = [
        str(plan["hermes_cli"]),
        "chat",
        "-q",
        prompt,
        "-Q",
        "--max-turns",
        str(plan.get("max_turns") or DEFAULT_SKILL_PROBE_MAX_TURNS),
        "--source",
        "memcore-time_library-skill-generation-probe",
        "--skills",
        "time-library",
    ]
    provider = str(body.get("provider") or authorization.get("provider") or "").strip()
    model = str(body.get("model") or authorization.get("model") or "").strip()
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])

    started = time.time()
    run_error = ""
    if runner is None:
        runner = subprocess.run
    try:
        proc = runner(
            command,
            capture_output=True,
            text=True,
            timeout=plan.get("timeout_seconds") or DEFAULT_SKILL_PROBE_TIMEOUT_SECONDS,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        exit_code = int(getattr(proc, "returncode", -999))
        stdout = getattr(proc, "stdout", "") or ""
        stderr = getattr(proc, "stderr", "") or ""
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        stdout = exc.stdout.decode("utf-8", errors="ignore") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="ignore") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        timed_out = True
        run_error = "hermes_skill_generation_probe_timeout"
    except Exception as exc:
        exit_code = -2
        stdout = ""
        stderr = ""
        timed_out = False
        run_error = f"hermes_skill_generation_probe_error:{str(exc)[:160]}"

    after_liveness = build_hermes_native_learning_liveness(
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
    )
    after_skills = _skill_file_snapshot(home)
    skill_diff = _skill_snapshot_diff(before_skills, after_skills)
    after_log = _read_text(home / "logs" / "agent.log")
    after_patterns = _pattern_summary(after_log, LEARNING_PATTERNS)
    after_review_count = _sum_counts(after_patterns, NATIVE_REVIEW_PATTERNS)
    after_skill_manage_count = _sum_counts(after_patterns, SKILL_MANAGE_PATTERNS)
    new_review_events = max(0, after_review_count - before_review_count)
    new_skill_manage_events = max(0, after_skill_manage_count - before_skill_manage_count)
    trigger_success = exit_code == 0 and not timed_out
    skill_file_changed = bool(skill_diff.get("non_time_library_changed_count", 0) > 0)
    background_review_seen = bool(new_review_events > 0)
    skill_manage_seen = bool(new_skill_manage_events > 0)
    if skill_file_changed:
        stage = "c_skill_artifact_changed"
    elif skill_manage_seen or background_review_seen:
        stage = "b_native_review_signal_seen"
    elif trigger_success:
        stage = "a_hermes_trigger_success_only"
    else:
        stage = "trigger_failed"
    success = bool(trigger_success and skill_file_changed)
    blockers: list[str] = []
    if not trigger_success:
        blockers.append("hermes_trigger_failed")
    if trigger_success and not background_review_seen:
        blockers.append("no_new_background_review_seen")
    if trigger_success and not skill_manage_seen:
        blockers.append("no_new_skill_manage_seen")
    if trigger_success and not skill_file_changed:
        blockers.append("no_non_time_library_skill_file_change")

    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt = {
        "probe_id": plan.get("probe_id"),
        "receipt_status": "recorded_live_skill_generation_probe",
        "schema_version": SKILL_GENERATION_PROBE_SCHEMA_VERSION,
        "recorded_at": recorded_at,
        "requested_by": requested_by,
        "reason": reason,
        "signal_id": signal.get("signal_id", ""),
        "command_preview": [command[0], "chat", "-q", "[skill-generation-probe prompt]", "-Q", "--max-turns", str(plan.get("max_turns"))],
        "hermes_trigger": {
            "called": True,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "elapsed_seconds": round(time.time() - started, 2),
            "stdout_excerpt": _bounded_text(stdout, 2000),
            "stderr_excerpt": _bounded_text(stderr, 1200),
            "error": run_error,
        },
        "skill_generation_observation": {
            "skill_generation_success": success,
            "skill_generation_stage": stage,
            "trigger_success": trigger_success,
            "background_review_seen": background_review_seen,
            "skill_manage_seen": skill_manage_seen,
            "skill_file_changed": skill_file_changed,
            "new_background_review_event_count": new_review_events,
            "new_skill_manage_event_count": new_skill_manage_events,
            "changed_skill_file_count": skill_diff.get("non_time_library_changed_count", 0),
            "blockers": blockers,
        },
        "skill_snapshot_before": before_skills,
        "skill_snapshot_after": after_skills,
        "skill_file_diff": skill_diff,
        "liveness_before": before_liveness,
        "liveness_after": after_liveness,
        "authorization": {
            "confirm_live_hermes_skill_generation_probe": True,
            "confirm_hermes_may_read_raw_source_refs": True,
            "confirm_hermes_native_skill_artifacts_allowed": True,
            "confirm_no_time_library_raw_zhiyi_xingce_write": True,
            "operator": requested_by,
            "reason": reason,
        },
        "write_boundary": {
            "write_performed": True,
            "probe_receipt_write_performed": True,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed_by_time_library": False,
            "hermes_skill_write_performed_by_time_library": False,
            "hermes_native_artifacts_may_be_written_by_hermes": True,
            "openclaw_write_performed": False,
            "platform_write_performed_by_time_library": False,
        },
        "notes": [
            "live_skill_generation_probe_receipt",
            "skill_success_requires_non_time_library_skill_file_diff",
            "time_library_did_not_write_raw_zhiyi_xingce",
            "time_library_did_not_write_hermes_skill",
        ],
    }
    directory.mkdir(parents=True, exist_ok=True)
    receipt_path = directory / f"{recorded_at.replace(':', '').replace('-', '')}-{plan.get('probe_id')}.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_path = directory / "latest.json"
    latest_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": trigger_success,
        "skill_generation_success": success,
        "skill_generation_stage": stage,
        "read_only": False,
        "write_capable": True,
        "write_performed": True,
        "probe_receipt_write_performed": True,
        "hermes_trigger_called": True,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed_by_time_library": False,
        "hermes_skill_write_performed_by_time_library": False,
        "openclaw_write_performed": False,
        "probe_id": plan.get("probe_id"),
        "receipt_path": str(receipt_path),
        "latest_path": str(latest_path),
        "skill_generation_observation": receipt["skill_generation_observation"],
        "skill_file_diff": skill_diff,
        "receipt": receipt,
        "liveness_before": before_liveness,
        "liveness_after": after_liveness,
        "plan": plan,
    }


def trigger_hermes_self_review(
    body: dict[str, Any] | None = None,
    *,
    hermes_home: str | Path | None = None,
    memcore_root: str | Path | None = None,
    cold_after_hours: int = 72,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> dict[str, Any]:
    """Run Hermes once with an explicit live authorization and record a trigger receipt.

    Time Library may write its trigger receipt. Hermes may write native artifacts if
    its own runtime decides to do so. Time Library still never writes raw/Zhiyi/
    Xingce or Hermes skill files directly.
    """
    body = body if isinstance(body, dict) else {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else {}
    requested_by = str(authorization.get("operator") or body.get("operator") or body.get("requested_by") or "").strip()
    reason = str(authorization.get("reason") or body.get("reason") or "").strip()

    def confirmed(name: str) -> bool:
        return _truthy(authorization.get(name, body.get(name)))

    checks = {
        "confirm_live_hermes_trigger": confirmed("confirm_live_hermes_trigger"),
        "confirm_hermes_may_read_raw_source_refs": confirmed("confirm_hermes_may_read_raw_source_refs"),
        "confirm_hermes_native_artifacts_allowed": confirmed("confirm_hermes_native_artifacts_allowed"),
        "confirm_no_time_library_raw_zhiyi_xingce_write": confirmed("confirm_no_time_library_raw_zhiyi_xingce_write"),
        "operator": bool(requested_by),
        "reason": bool(reason),
    }
    missing = [name for name, ok in checks.items() if not ok]
    plan = build_hermes_self_review_trigger_plan(
        body,
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
    )
    directory = Path(memcore_root).expanduser() / "output" / "hermes_native_learning" / "triggers" if memcore_root else None
    guard_failures = []
    if not directory:
        guard_failures.append("memcore_root_required")
    if not plan.get("hermes_cli"):
        guard_failures.append("hermes_cli_not_found")
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_capable": True,
            "write_performed": False,
            "trigger_receipt_write_performed": False,
            "hermes_trigger_called": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed_by_time_library": False,
            "hermes_skill_write_performed_by_time_library": False,
            "openclaw_write_performed": False,
            "missing_authorization": missing,
            "guard_failures": guard_failures,
            "plan": plan,
        }

    assert directory is not None
    before = build_hermes_native_learning_liveness(
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
    )
    signal = plan.get("self_review_signal", {})
    prompt = _build_hermes_self_review_prompt(signal, reason=reason)
    command = [
        str(plan["hermes_cli"]),
        "chat",
        "-q",
        prompt,
        "-Q",
        "--max-turns",
        str(plan.get("max_turns") or DEFAULT_TRIGGER_MAX_TURNS),
        "--source",
        "memcore-time_library-self-review",
        "--skills",
        "time-library",
    ]
    provider = str(body.get("provider") or authorization.get("provider") or "").strip()
    model = str(body.get("model") or authorization.get("model") or "").strip()
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])

    started = time.time()
    run_error = ""
    if runner is None:
        runner = subprocess.run
    try:
        proc = runner(
            command,
            capture_output=True,
            text=True,
            timeout=plan.get("timeout_seconds") or DEFAULT_TRIGGER_TIMEOUT_SECONDS,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        exit_code = int(getattr(proc, "returncode", -999))
        stdout = getattr(proc, "stdout", "") or ""
        stderr = getattr(proc, "stderr", "") or ""
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code = -1
        stdout = exc.stdout.decode("utf-8", errors="ignore") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="ignore") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        timed_out = True
        run_error = "hermes_trigger_timeout"
    except Exception as exc:
        exit_code = -2
        stdout = ""
        stderr = ""
        timed_out = False
        run_error = f"hermes_trigger_error:{str(exc)[:160]}"

    after = build_hermes_native_learning_liveness(
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
    )
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt = {
        "trigger_id": plan.get("trigger_id"),
        "receipt_status": "recorded_live_trigger",
        "schema_version": TRIGGER_RECEIPT_SCHEMA_VERSION,
        "recorded_at": recorded_at,
        "requested_by": requested_by,
        "reason": reason,
        "signal_id": signal.get("signal_id", ""),
        "command_preview": [command[0], "chat", "-q", "[self-review prompt]", "-Q", "--max-turns", str(plan.get("max_turns"))],
        "hermes_trigger": {
            "called": True,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "elapsed_seconds": round(time.time() - started, 2),
            "stdout_excerpt": _bounded_text(stdout, 2000),
            "stderr_excerpt": _bounded_text(stderr, 1200),
            "error": run_error,
        },
        "liveness_before": {
            "status": before.get("liveness_status"),
            "native_skill_write_observed": before.get("native_skill_write_observed"),
            "cold_reasons": before.get("cold_reasons", []),
            "latest_skill": before.get("skills", {}).get("latest_relative_path", ""),
        },
        "liveness_after": {
            "status": after.get("liveness_status"),
            "native_skill_write_observed": after.get("native_skill_write_observed"),
            "cold_reasons": after.get("cold_reasons", []),
            "latest_skill": after.get("skills", {}).get("latest_relative_path", ""),
        },
        "native_observation": {
            "skill_write_observed_after_trigger": bool(after.get("native_skill_write_observed")),
            "feedback_candidates_dir_exists": bool(after.get("feedback_artifacts", {}).get("candidates", {}).get("dir_exists", False)),
            "upgrade_inputs_dir_exists": bool(after.get("feedback_artifacts", {}).get("upgrade_inputs", {}).get("dir_exists", False)),
        },
        "authorization": {
            "confirm_live_hermes_trigger": True,
            "confirm_hermes_may_read_raw_source_refs": True,
            "confirm_hermes_native_artifacts_allowed": True,
            "confirm_no_time_library_raw_zhiyi_xingce_write": True,
            "operator": requested_by,
            "reason": reason,
        },
        "write_boundary": {
            "write_performed": True,
            "trigger_receipt_write_performed": True,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed_by_time_library": False,
            "hermes_skill_write_performed_by_time_library": False,
            "hermes_native_artifacts_may_be_written_by_hermes": True,
            "openclaw_write_performed": False,
            "platform_write_performed_by_time_library": False,
        },
        "notes": [
            "live_trigger_receipt",
            "hermes_triggered_to_read_raw_source_refs_itself",
            "time_library_did_not_write_raw_zhiyi_xingce",
            "time_library_did_not_write_hermes_skill",
        ],
    }
    directory.mkdir(parents=True, exist_ok=True)
    receipt_path = directory / f"{recorded_at.replace(':', '').replace('-', '')}-{plan.get('trigger_id')}.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_path = directory / "latest.json"
    latest_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": exit_code == 0 and not timed_out,
        "read_only": False,
        "write_capable": True,
        "write_performed": True,
        "trigger_receipt_write_performed": True,
        "hermes_trigger_called": True,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed_by_time_library": False,
        "hermes_skill_write_performed_by_time_library": False,
        "openclaw_write_performed": False,
        "trigger_id": plan.get("trigger_id"),
        "receipt_path": str(receipt_path),
        "latest_path": str(latest_path),
        "receipt": receipt,
        "liveness_before": before,
        "liveness_after": after,
        "plan": plan,
    }


def persist_hermes_self_review_signal_receipt(
    body: dict[str, Any] | None = None,
    *,
    hermes_home: str | Path | None = None,
    memcore_root: str | Path | None = None,
    cold_after_hours: int = 72,
) -> dict[str, Any]:
    """Record a Time Library signal receipt with an explicit authorization gate."""
    body = body if isinstance(body, dict) else {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else {}
    requested_by = str(
        authorization.get("operator")
        or body.get("operator")
        or body.get("requested_by")
        or ""
    ).strip()
    reason = str(authorization.get("reason") or body.get("reason") or "").strip()

    checks = {
        "confirm_record_signal_receipt": _truthy(authorization.get("confirm_record_signal_receipt", body.get("confirm_record_signal_receipt"))),
        "confirm_no_hermes_write": _truthy(authorization.get("confirm_no_hermes_write", body.get("confirm_no_hermes_write"))),
        "confirm_no_raw_zhiyi_xingce_write": _truthy(authorization.get("confirm_no_raw_zhiyi_xingce_write", body.get("confirm_no_raw_zhiyi_xingce_write"))),
        "operator": bool(requested_by),
        "reason": bool(reason),
    }
    missing = [name for name, ok in checks.items() if not ok]
    dry_run = build_hermes_self_review_wake_dry_run(
        hermes_home=hermes_home,
        memcore_root=memcore_root,
        cold_after_hours=cold_after_hours,
        requested_by=requested_by,
        reason=reason,
    )
    signal = dry_run.get("self_review_signal", {})
    receipt_draft = dry_run.get("receipt_draft", {})
    receipt_id = str(receipt_draft.get("receipt_id") or "")
    directory = _signal_receipts_dir(memcore_root)
    guard_failures = []
    if not directory:
        guard_failures.append("memcore_root_required")
    if not receipt_id:
        guard_failures.append("receipt_id_required")
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "signal_receipt_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "schema_version": SIGNAL_RECEIPT_SCHEMA_VERSION,
            "missing_authorization": missing,
            "guard_failures": guard_failures,
            "dry_run": dry_run,
        }

    assert directory is not None
    directory.mkdir(parents=True, exist_ok=True)
    receipt_path = directory / f"{receipt_id}.json"
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt = {
        "receipt_id": receipt_id,
        "receipt_status": "recorded_signal_only",
        "schema_version": SIGNAL_RECEIPT_SCHEMA_VERSION,
        "recorded_at": recorded_at,
        "requested_by": requested_by,
        "reason": reason,
        "signal_id": signal.get("signal_id", ""),
        "signal_type": signal.get("signal_type", ""),
        "signal_status": signal.get("signal_status", ""),
        "read_scope": signal.get("scope", {}).get("read_scope", ""),
        "read_hint": signal.get("scope", {}).get("read_hint", ""),
        "signal": signal,
        "authorization": {
            "confirm_record_signal_receipt": True,
            "confirm_no_hermes_write": True,
            "confirm_no_raw_zhiyi_xingce_write": True,
            "operator": requested_by,
            "reason": reason,
        },
        "write_boundary": {
            "write_performed": True,
            "signal_receipt_write_performed": True,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "platform_write_performed": False,
            "skill_write_performed": False,
        },
        "notes": [
            "signal_receipt_only",
            "does_not_trigger_hermes",
            "does_not_write_hermes_skill",
            "does_not_package_zhiyi_summary",
            "hermes_must_read_raw_source_refs_itself",
        ],
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "signal_receipt_write_performed": True,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "platform_write_performed": False,
        "skill_write_performed": False,
        "schema_version": SIGNAL_RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "receipt_path": str(receipt_path),
        "receipt": receipt,
        "dry_run": dry_run,
    }


def build_hermes_native_learning_liveness(
    *,
    hermes_home: str | Path | None = None,
    memcore_root: str | Path | None = None,
    cold_after_hours: int = 72,
) -> dict[str, Any]:
    home = Path(hermes_home).expanduser() if hermes_home else resolve_hermes_home()
    agent_log = home / "logs" / "agent.log"
    errors_log = home / "logs" / "errors.log"
    text = _read_text(agent_log)
    pattern_counts = _pattern_summary(text, LEARNING_PATTERNS)
    native_review_count = _sum_counts(pattern_counts, NATIVE_REVIEW_PATTERNS)
    skill_manage_count = _sum_counts(pattern_counts, SKILL_MANAGE_PATTERNS)
    latest_skill = _latest_skill_file(home)
    now = datetime.now(timezone.utc)

    latest_skill_mtime = latest_skill.get("latest_mtime") or ""
    days_since_skill_write: float | None = None
    if latest_skill_mtime:
        try:
            latest_dt = datetime.strptime(latest_skill_mtime, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            days_since_skill_write = round((now - latest_dt).total_seconds() / 86400, 3)
        except ValueError:
            days_since_skill_write = None

    native_skill_write_observed = bool(skill_manage_count > 0 and latest_skill.get("latest_path") and not latest_skill.get("latest_looks_like_time_library_install"))
    cold_reasons: list[str] = []
    if not home.exists():
        cold_reasons.append("hermes_home_missing")
    if not agent_log.exists():
        cold_reasons.append("agent_log_missing")
    if native_review_count == 0:
        cold_reasons.append("no_background_review_seen")
    if skill_manage_count == 0:
        cold_reasons.append("no_skill_manage_seen")
    if not latest_skill.get("latest_path"):
        cold_reasons.append("no_skill_file_seen")
    if latest_skill.get("latest_looks_like_time_library_install"):
        cold_reasons.append("latest_skill_write_looks_like_time_library_install")
    if days_since_skill_write is not None and days_since_skill_write * 24 >= cold_after_hours:
        cold_reasons.append("latest_skill_write_older_than_threshold")

    liveness_status = "native_skill_write_observed" if native_skill_write_observed else "cold"
    if not home.exists() or not agent_log.exists():
        liveness_status = "unknown"

    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "schema_version": "1.0",
        "liveness_status": liveness_status,
        "native_skill_write_observed": native_skill_write_observed,
        "cold": liveness_status != "native_skill_write_observed",
        "cold_after_hours": cold_after_hours,
        "cold_reasons": cold_reasons,
        "hermes_home": str(home),
        "logs": {
            "agent_log": _path_info(agent_log),
            "errors_log": _path_info(errors_log),
            "pattern_counts": pattern_counts,
            "native_review_event_count": native_review_count,
            "skill_manage_event_count": skill_manage_count,
        },
        "skills": latest_skill,
        "timing": {
            "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "days_since_latest_skill_file_write": days_since_skill_write,
        },
        "self_review_signal": _native_review_signal(
            hermes_home=home,
            memcore_root=memcore_root,
            cold_after_hours=cold_after_hours,
            liveness_status=liveness_status,
            cold_reasons=cold_reasons,
            latest_skill=latest_skill,
            checked_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
        "feedback_artifacts": _feedback_artifacts(memcore_root),
        "self_review_signal_receipts": _latest_signal_receipt(memcore_root),
        "self_review_trigger_receipts": _latest_trigger_receipt(memcore_root),
        "notes": [
            "read_only_liveness_probe",
            "does_not_trigger_hermes",
            "does_not_write_hermes_skill",
            "codex_or_openclaw_chat_does_not_imply_hermes_native_review",
        ],
    }
