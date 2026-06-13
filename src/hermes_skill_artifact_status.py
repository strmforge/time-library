#!/usr/bin/env python3
"""Hermes skill artifact status observation under Tiandao.

This module turns Hermes native skill-generation probe receipts into reviewable
status receipts. It never adopts a Hermes skill, writes raw/Zhiyi/Xingce memory,
or claims production experience adoption.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_ARTIFACT_STATUS_SCHEMA_VERSION = "2026.6.1"
HERMES_SKILL_ARTIFACT_STATUS_CONTRACT = "tiandao_hermes_skill_artifact_status_observation.v1"


def get_hermes_skill_artifact_status_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": HERMES_SKILL_ARTIFACT_STATUS_CONTRACT,
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "workbench_id": "experience_governance",
        "governance_layer": "hermes_skill_artifact_status",
        "derived_layer": "hermes_native_learning",
        "not_raw_origin": True,
        "read_only_by_default": True,
        "write_capable": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "platform_write_performed": False,
        "hermes_skill_write_performed_by_yifanchen": False,
        "production_experience_write_performed": False,
        "authorization_required_for_write": True,
        "authorized_write_scopes": ["hermes_skill_artifact_status_receipt"],
        "forbidden_write_scopes": [
            "raw_record",
            "zhiyi_memory",
            "xingce_memory",
            "hermes_native_skill_file",
            "production_experience_adoption",
        ],
        "raw_origin_policy": "skill artifact status observes Hermes probe results but never replaces Time Origin",
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "ok"}


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_text(value: Any, max_chars: int = 1200) -> str:
    text = str(value or "").replace(chr(13), " ").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)] + "…"


def _skill_probe_receipts_dir(memcore_root: str | Path | None) -> Path | None:
    if not memcore_root:
        return None
    return Path(memcore_root).expanduser() / "output" / "hermes_native_learning" / "skill_generation_probes"


def _skill_artifact_status_dir(memcore_root: str | Path | None) -> Path | None:
    if not memcore_root:
        return None
    return Path(memcore_root).expanduser() / "output" / "hermes_native_learning" / "skill_artifact_status"


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


def _skill_probe_receipt_summary(data: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    trigger = data.get("hermes_trigger", {}) if isinstance(data.get("hermes_trigger"), dict) else {}
    observation = data.get("skill_generation_observation", {}) if isinstance(data.get("skill_generation_observation"), dict) else {}
    write_boundary = data.get("write_boundary", {}) if isinstance(data.get("write_boundary"), dict) else {}
    return {
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


def _first_changed_skill_artifact(probe_receipt: dict[str, Any]) -> dict[str, Any]:
    diff = probe_receipt.get("skill_file_diff", {}) if isinstance(probe_receipt.get("skill_file_diff"), dict) else {}
    for key in ("non_yifanchen_changed", "added", "modified"):
        values = diff.get(key, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict):
                return dict(item)
    observation = probe_receipt.get("skill_generation_observation", {})
    if isinstance(observation, dict):
        changed = observation.get("changed_skill_files")
        if isinstance(changed, list):
            for item in changed:
                if isinstance(item, dict):
                    return dict(item)
    return {}


def _skill_artifact_status_summary(data: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    write_boundary = data.get("write_boundary", {}) if isinstance(data.get("write_boundary"), dict) else {}
    return {
        "status_id": str(data.get("status_id") or ""),
        "artifact_type": str(data.get("artifact_type") or ""),
        "status": str(data.get("status") or ""),
        "recorded_at": str(data.get("recorded_at") or ""),
        "requested_by": str(data.get("requested_by") or ""),
        "reason": str(data.get("reason") or ""),
        "source_path": str(path) if path else "",
        "skill_artifact_status": str(data.get("skill_artifact_status") or ""),
        "probe_id": str(data.get("probe_id") or ""),
        "probe_receipt_path": str(data.get("probe_receipt_path") or ""),
        "skill_relative_path": str(data.get("skill_relative_path") or ""),
        "skill_path": str(data.get("skill_path") or ""),
        "skill_sha256": str(data.get("skill_sha256") or ""),
        "summary": str(data.get("summary") or ""),
        "write_boundary": write_boundary,
        "status_receipt_write_performed": bool(write_boundary.get("status_receipt_write_performed", False)),
        "raw_write_performed": bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_performed": bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_performed": bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_skill_write_performed_by_yifanchen": bool(write_boundary.get("hermes_skill_write_performed_by_yifanchen", False)),
        "production_experience_write_performed": bool(write_boundary.get("production_experience_write_performed", False)),
    }



def build_hermes_skill_artifact_status_dry_run(
    body: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a stable recallable status artifact from the latest skill probe.

    This is status/review only. It does not adopt the generated skill and does
    not write raw, Zhiyi, Xingce, production experience, or Hermes skill files.
    """
    body = body if isinstance(body, dict) else {}
    probe_receipt, probe_path, probe_error = _read_latest_skill_probe_receipt(
        memcore_root,
        body.get("probe_receipt_path") or body.get("receipt_path") or None,
    )
    observation = probe_receipt.get("skill_generation_observation", {}) if isinstance(probe_receipt.get("skill_generation_observation"), dict) else {}
    artifact = _first_changed_skill_artifact(probe_receipt)
    probe_id = str(probe_receipt.get("probe_id") or body.get("probe_id") or "").strip()
    skill_relative_path = str(
        body.get("skill_relative_path")
        or artifact.get("relative_path")
        or artifact.get("latest_relative_path")
        or ""
    ).strip()
    skill_path = str(body.get("skill_path") or artifact.get("path") or "").strip()
    skill_sha256 = str(body.get("skill_sha256") or artifact.get("sha256") or "").strip()
    generation_success = bool(observation.get("skill_generation_success", False))
    skill_artifact_status = str(
        body.get("skill_artifact_status")
        or body.get("verdict")
        or ("probe_only_not_adopted" if generation_success else "probe_failed_no_skill_artifact")
    ).strip()
    status_seed = "|".join([
        probe_id,
        skill_artifact_status,
        skill_relative_path,
        skill_sha256,
        str(probe_path or ""),
    ])
    status_id = "hermes-skill-artifact-status-" + hashlib.sha256(status_seed.encode("utf-8")).hexdigest()[:16]
    summary = _bounded_text(
        body.get("summary")
        or (
            f"Hermes native skill artifact status: {skill_artifact_status}; "
            f"probe_id={probe_id or 'unknown'}; "
            f"skill={skill_relative_path or skill_path or 'not_observed'}."
        ),
        800,
    )
    current_state = _bounded_text(
        body.get("current_state")
        or (
            "Hermes native runtime produced or changed a skill artifact, but Yifanchen only records "
            "a status artifact. The skill remains probe-only and is not adopted."
            if generation_success
            else "The latest Hermes skill generation probe did not prove a stable skill artifact change."
        ),
        1200,
    )
    next_step = _bounded_text(
        body.get("next_step")
        or "Review the generated skill against raw evidence and direct recall/MCP behavior before any adoption.",
        1200,
    )
    completed = body.get("completed") if isinstance(body.get("completed"), list) else [
        "Hermes native skill generation probe receipt observed.",
        "Skill artifact status draft built as a review-only project status artifact.",
    ]
    remaining = body.get("remaining") if isinstance(body.get("remaining"), list) else [
        "Do not adopt the generated skill until quality review passes.",
        "Verify future recall/MCP can surface this status before relying on the skill.",
    ]
    limitations = body.get("limitations") if isinstance(body.get("limitations"), list) else [
        "This status artifact is not raw/Zhiyi/Xingce memory adoption.",
        "Yifanchen did not write or modify the Hermes skill artifact.",
        "A generated skill file alone does not prove the skill is useful or adopted.",
    ]
    evidence_refs = body.get("evidence_refs") if isinstance(body.get("evidence_refs"), list) else []
    if probe_path:
        evidence_refs.append({
            "kind": "hermes_skill_generation_probe_receipt",
            "source_path": str(probe_path),
            "probe_id": probe_id,
        })
    if skill_path:
        evidence_refs.append({
            "kind": "hermes_native_skill_artifact",
            "source_path": skill_path,
            "relative_path": skill_relative_path,
            "sha256": skill_sha256,
        })
    status_draft = {
        "artifact_type": "hermes_skill_artifact_status",
        "schema_version": SKILL_ARTIFACT_STATUS_SCHEMA_VERSION,
        "status_id": status_id,
        "status": "current",
        "project": body.get("project") or "memcore-cloud / 忆凡尘",
        "skill_artifact_status": skill_artifact_status,
        "probe_id": probe_id,
        "probe_receipt_path": str(probe_path or ""),
        "skill_relative_path": skill_relative_path,
        "skill_path": skill_path,
        "skill_sha256": skill_sha256,
        "skill_generation_success": generation_success,
        "skill_generation_stage": str(observation.get("skill_generation_stage") or ""),
        "summary": summary,
        "current_state": current_state,
        "next_step": next_step,
        "completed": completed,
        "remaining": remaining,
        "limitations": limitations,
        "evidence_refs": evidence_refs,
        "score": 1.0,
        "lifecycle_version": 1,
        "write_boundary": {
            "status_receipt_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed_by_yifanchen": False,
            "hermes_skill_write_performed_by_yifanchen": False,
            "production_experience_write_performed": False,
            "openclaw_write_performed": False,
            "platform_write_performed_by_yifanchen": False,
        },
    }
    ready = bool(probe_receipt and not probe_error and probe_id)
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "status_receipt_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_skill_write_performed_by_yifanchen": False,
        "production_experience_write_performed": False,
        "schema_version": SKILL_ARTIFACT_STATUS_SCHEMA_VERSION,
        "ready_for_record": ready,
        "guard_failures": [probe_error] if probe_error else [],
        "status_draft": status_draft,
        "record_endpoint": "/api/v1/hermes/native-learning/skill-artifact-status/record",
        "query_endpoint": "/api/v1/hermes/native-learning/skill-artifact-statuses",
        "authorization_required": [
            "confirm_record_hermes_skill_artifact_status",
            "confirm_no_raw_zhiyi_xingce_write",
            "confirm_no_hermes_skill_write_by_yifanchen",
            "confirm_no_production_experience_adoption",
            "operator",
            "reason",
        ],
        "latest_probe_receipt": _skill_probe_receipt_summary(probe_receipt, probe_path) if probe_receipt else {},
        "write_boundary": status_draft["write_boundary"],
        "notes": [
            "status_only",
            "does_not_adopt_hermes_skill",
            "does_not_write_raw_zhiyi_xingce",
            "makes_probe_verdict_recallable",
        ],
    }


def record_hermes_skill_artifact_status(
    body: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
) -> dict[str, Any]:
    """Persist the Hermes skill artifact status receipt after explicit approval."""
    body = body if isinstance(body, dict) else {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else {}
    requested_by = str(authorization.get("operator") or body.get("operator") or body.get("requested_by") or "").strip()
    reason = str(authorization.get("reason") or body.get("reason") or "").strip()

    def confirmed(name: str) -> bool:
        return _truthy(authorization.get(name, body.get(name)))

    checks = {
        "confirm_record_hermes_skill_artifact_status": confirmed("confirm_record_hermes_skill_artifact_status"),
        "confirm_no_raw_zhiyi_xingce_write": confirmed("confirm_no_raw_zhiyi_xingce_write"),
        "confirm_no_hermes_skill_write_by_yifanchen": confirmed("confirm_no_hermes_skill_write_by_yifanchen"),
        "confirm_no_production_experience_adoption": confirmed("confirm_no_production_experience_adoption"),
        "operator": bool(requested_by),
        "reason": bool(reason),
    }
    missing = [name for name, ok in checks.items() if not ok]
    directory = _skill_artifact_status_dir(memcore_root)
    plan = build_hermes_skill_artifact_status_dry_run(body, memcore_root=memcore_root)
    guard_failures = list(plan.get("guard_failures", []))
    if not directory:
        guard_failures.append("memcore_root_required")
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_capable": True,
            "write_performed": False,
            "status_receipt_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_skill_write_performed_by_yifanchen": False,
            "production_experience_write_performed": False,
            "missing_authorization": missing,
            "guard_failures": guard_failures,
            "plan": plan,
        }

    assert directory is not None
    status = dict(plan.get("status_draft", {}))
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status["recorded_at"] = recorded_at
    status["requested_by"] = requested_by
    status["reason"] = reason
    status["write_boundary"] = {
        "write_performed": True,
        "status_receipt_write_performed": True,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed_by_yifanchen": False,
        "hermes_skill_write_performed_by_yifanchen": False,
        "production_experience_write_performed": False,
        "openclaw_write_performed": False,
        "platform_write_performed_by_yifanchen": False,
    }
    status["authorization"] = {
        "confirm_record_hermes_skill_artifact_status": True,
        "confirm_no_raw_zhiyi_xingce_write": True,
        "confirm_no_hermes_skill_write_by_yifanchen": True,
        "confirm_no_production_experience_adoption": True,
        "operator": requested_by,
        "reason": reason,
    }
    status.setdefault("notes", [])
    status["notes"] = list(status["notes"]) + [
        "recorded_status_only",
        "not_a_skill_adoption",
        "not_a_production_experience_adoption",
    ]
    directory.mkdir(parents=True, exist_ok=True)
    status_id = status.get("status_id") or "hermes-skill-artifact-status"
    path = directory / f"{recorded_at.replace(':', '').replace('-', '')}-{status_id}.json"
    latest_path = directory / "latest.json"
    payload = json.dumps(status, ensure_ascii=False, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    return {
        "ok": True,
        "read_only": False,
        "write_capable": True,
        "write_performed": True,
        "status_receipt_write_performed": True,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_skill_write_performed_by_yifanchen": False,
        "production_experience_write_performed": False,
        "status_id": status.get("status_id", ""),
        "skill_artifact_status": status.get("skill_artifact_status", ""),
        "status_path": str(path),
        "latest_path": str(latest_path),
        "status_artifact": status,
    }


def query_hermes_skill_artifact_statuses(
    *,
    memcore_root: str | Path | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Read Hermes skill artifact status receipts without mutation."""
    directory = _skill_artifact_status_dir(memcore_root)
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
                items.append(_skill_artifact_status_summary(data, path))
    latest: dict[str, Any] = {
        "available": False,
        "latest_path": "",
        "latest_status_id": "",
    }
    latest_path = directory / "latest.json" if directory else None
    if latest_path and latest_path.exists():
        try:
            data = json.loads(latest_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if isinstance(data, dict):
            summary = _skill_artifact_status_summary(data, latest_path)
            latest.update(summary)
            latest["available"] = True
            latest["latest_path"] = str(latest_path)
            latest["latest_status_id"] = summary.get("status_id", "")
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "status_receipt_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_skill_write_performed_by_yifanchen": False,
        "production_experience_write_performed": False,
        "directory": str(directory) if directory else "",
        "directory_exists": bool(directory and directory.is_dir()),
        "latest": latest,
        "items": items,
        "count": len(items),
        "parse_errors": parse_errors,
        "notes": [
            "skill_artifact_statuses_are_review_records",
            "status_does_not_adopt_hermes_skill",
            "status_makes_probe_verdict_recallable",
        ],
    }



__all__ = [
    "SKILL_ARTIFACT_STATUS_SCHEMA_VERSION",
    "HERMES_SKILL_ARTIFACT_STATUS_CONTRACT",
    "get_hermes_skill_artifact_status_contract",
    "_skill_artifact_status_dir",
    "_read_latest_skill_probe_receipt",
    "_skill_probe_receipt_summary",
    "_first_changed_skill_artifact",
    "_skill_artifact_status_summary",
    "build_hermes_skill_artifact_status_dry_run",
    "record_hermes_skill_artifact_status",
    "query_hermes_skill_artifact_statuses",
]
