#!/usr/bin/env python3
"""Convert Hermes self-review trigger reports into review-only upgrade inputs."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .hermes_paths import hermes_state_db_path
except Exception:  # pragma: no cover - direct script import fallback
    from hermes_paths import hermes_state_db_path


SELF_REVIEW_REPORT_VERSION = "2026.6.1"


def _sha(value: Any, size: int = 16) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:size]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact(value: Any, limit: int = 800) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 14)].rstrip() + " ...[truncated]"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "确认", "是"}


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "not_found"
    except Exception as exc:
        return {}, f"read_failed:{str(exc)[:120]}"
    if isinstance(data, dict):
        return data, ""
    return {}, "json_not_object"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _trigger_dir(memcore_root: str | Path | None) -> Path | None:
    if not memcore_root:
        return None
    return Path(memcore_root).expanduser() / "output" / "hermes_native_learning" / "triggers"


def _feedback_base(memcore_root: str | Path | None) -> Path | None:
    if not memcore_root:
        return None
    return Path(memcore_root).expanduser() / "output" / "hermes_experience_feedback"


def _load_trigger_receipt(body: dict[str, Any], memcore_root: str | Path | None) -> tuple[dict[str, Any], str, str]:
    explicit = str(body.get("trigger_receipt_path") or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        data, err = _read_json(path)
        return data, str(path), err
    directory = _trigger_dir(memcore_root)
    if not directory:
        return {}, "", "memcore_root_required"
    latest = directory / "latest.json"
    data, err = _read_json(latest)
    return data, str(latest), err


def _review_text_from_receipt(receipt: dict[str, Any], body: dict[str, Any]) -> tuple[str, str]:
    supplied = str(body.get("review_text") or body.get("report_text") or "").strip()
    if supplied:
        return supplied, "body_override"
    trigger = receipt.get("hermes_trigger", {}) if isinstance(receipt.get("hermes_trigger"), dict) else {}
    return str(trigger.get("stdout_excerpt") or "").strip(), "stdout_excerpt"


def _looks_like_self_review_report(text: str) -> bool:
    compact = str(text or "").strip()
    if not compact:
        return False
    lowered = compact.lower()
    has_report_title = "忆凡尘原始记忆自审" in compact or "self-review" in lowered or "review report" in lowered
    has_report_body = any(marker in compact for marker in ("候选", "已读取", "原始记忆", "经验")) or "candidate" in lowered
    has_failure_marker = any(marker in lowered for marker in (
        "failed to initialize",
        "traceback",
        "exception",
        "error:",
        "install it with",
        "package is required",
    ))
    return bool(has_report_title and has_report_body and not has_failure_marker)


def _extract_session_id(receipt: dict[str, Any]) -> str:
    trigger = receipt.get("hermes_trigger", {}) if isinstance(receipt.get("hermes_trigger"), dict) else {}
    text = "\n".join([str(trigger.get("stderr_excerpt") or ""), str(trigger.get("stdout_excerpt") or "")])
    match = re.search(r"session_id\s*[:=]\s*([-A-Za-z0-9_.:]+)", text)
    return match.group(1) if match else ""


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return _content_text(json.loads(stripped))
            except Exception:
                return value
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for part in value:
            text = _content_text(part)
            if text:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        for key in ("text", "content", "message", "thinking"):
            if key in value:
                return _content_text(value.get(key))
        return json.dumps(value, ensure_ascii=False)
    return str(value) if value is not None else ""


def _state_db_path_from_body(body: dict[str, Any]) -> Path:
    explicit = str(body.get("hermes_state_db_path") or body.get("state_db_path") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return hermes_state_db_path()


def _read_self_review_report_from_state_db(
    *,
    session_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "found": False,
        "review_text": "",
        "state_db_path": "",
        "error": "",
        "message_id": "",
    }
    if not session_id:
        result["error"] = "session_id_required"
        return result

    db_path = _state_db_path_from_body(body)
    result["state_db_path"] = str(db_path)
    if not db_path.exists():
        result["error"] = "state_db_not_found"
        return result

    try:
        import sqlite3

        uri = db_path.resolve().as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=1)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT id, role, content, timestamp
            FROM messages
            WHERE session_id = ? AND role = 'assistant'
            ORDER BY timestamp DESC, id DESC
            LIMIT 20
            """,
            (session_id,),
        ).fetchall()
        con.close()
    except Exception as exc:
        result["error"] = f"state_db_read_failed:{str(exc)[:120]}"
        return result

    for row in rows:
        text = _content_text(row["content"]).strip()
        if _looks_like_self_review_report(text):
            result.update({
                "found": True,
                "review_text": text,
                "message_id": str(row["id"] or ""),
                "error": "",
            })
            return result

    result["error"] = "self_review_report_not_found"
    return result


def _resolve_review_text(
    receipt: dict[str, Any],
    body: dict[str, Any],
    *,
    trigger_success: bool,
    session_id: str,
) -> dict[str, Any]:
    review_text, source = _review_text_from_receipt(receipt, body)
    state_lookup = {
        "found": False,
        "review_text": "",
        "state_db_path": "",
        "error": "",
        "message_id": "",
    }
    if trigger_success and session_id and source == "stdout_excerpt" and not _looks_like_self_review_report(review_text):
        state_lookup = _read_self_review_report_from_state_db(session_id=session_id, body=body)
        if state_lookup.get("found"):
            review_text = str(state_lookup.get("review_text") or "")
            source = "hermes_state_db"
    return {
        "review_text": review_text,
        "review_text_source": source,
        "review_state_db_path": state_lookup.get("state_db_path", ""),
        "review_state_db_error": state_lookup.get("error", ""),
        "review_state_db_message_id": state_lookup.get("message_id", ""),
    }


def _extract_report_items(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    lines = str(text or "").splitlines()
    current: dict[str, Any] | None = None
    for line in lines:
        stripped = line.strip()
        title_match = re.match(r"^#{3,5}\s*候选\s*#?\d*[:：]\s*(.+)$", stripped)
        if title_match:
            if current:
                items.append(current)
            current = {
                "title": title_match.group(1).strip("「」 "),
                "source_path": "",
                "verbatim_excerpt": "",
                "acceptance_checks": [],
            }
            continue
        if current is None:
            continue
        source_match = re.search(r"来源路径\**\s*[:：]\s*`?([^`]+?)`?\s*$", stripped)
        if source_match:
            current["source_path"] = source_match.group(1).strip()
            continue
        if "验收" in stripped and ("条件" in stripped or "标准" in stripped):
            text_part = stripped.split(":", 1)[-1].split("：", 1)[-1].strip(" -*")
            if text_part:
                current.setdefault("acceptance_checks", []).append(text_part)
            continue
        if stripped.startswith(">"):
            excerpt = stripped.lstrip("> ").strip()
            if excerpt:
                existing = str(current.get("verbatim_excerpt") or "")
                current["verbatim_excerpt"] = _compact((existing + "\n" + excerpt).strip(), 1200)
    if current:
        items.append(current)
    if items:
        return items[:20]
    fallback_title = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("##") and "Review Report" not in stripped and "自审" not in stripped:
            fallback_title = stripped.lstrip("#").strip()
            break
    return [{
        "title": fallback_title or "Hermes self-review report",
        "source_path": "",
        "verbatim_excerpt": _compact(text, 1200),
        "acceptance_checks": [],
    }] if text.strip() else []


def get_hermes_self_review_report_plan() -> dict[str, Any]:
    return {
        "ok": True,
        "version": SELF_REVIEW_REPORT_VERSION,
        "read_only": True,
        "write_performed": False,
        "name": "Hermes Self-Review Report Candidate",
        "zh_name": "Hermes 自审报告升级材料",
        "dry_run_endpoint": "/api/v1/hermes/native-learning/self-review/report/dry-run",
        "record_endpoint": "/api/v1/hermes/native-learning/self-review/report/record",
        "inputs": [
            "latest trigger receipt",
            "optional trigger_receipt_path",
            "optional review_text override",
        ],
        "outputs": [
            "hermes_self_review_report_candidate",
            "hermes_self_review_report_upgrade_input",
        ],
        "authorization_required_for_record": [
            "confirm_record_self_review_report_candidate",
            "confirm_no_raw_zhiyi_xingce_write",
            "confirm_no_hermes_skill_write",
            "operator",
            "reason",
        ],
        "forbidden_by_default": [
            "write_hermes_skill",
            "write_hermes_memory",
            "write_raw",
            "write_production_zhiyi_or_xingce",
            "adopt_without_review",
        ],
    }


def build_hermes_self_review_report_dry_run(
    body: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    receipt, receipt_path, receipt_error = _load_trigger_receipt(body, memcore_root)
    trigger = receipt.get("hermes_trigger", {}) if isinstance(receipt.get("hermes_trigger"), dict) else {}
    native = receipt.get("native_observation", {}) if isinstance(receipt.get("native_observation"), dict) else {}
    trigger_id = str(receipt.get("trigger_id") or body.get("trigger_id") or "")
    exit_code = trigger.get("exit_code")
    timed_out = bool(trigger.get("timed_out", False))
    trigger_success = exit_code == 0 and not timed_out
    session_id = _extract_session_id(receipt)
    review_resolution = _resolve_review_text(
        receipt,
        body,
        trigger_success=trigger_success,
        session_id=session_id,
    )
    review_text = str(review_resolution.get("review_text") or "").strip()
    review_text_source = str(review_resolution.get("review_text_source") or "")
    review_state_db_path = str(review_resolution.get("review_state_db_path") or "")
    review_state_db_error = str(review_resolution.get("review_state_db_error") or "")
    review_state_db_message_id = str(review_resolution.get("review_state_db_message_id") or "")
    report_hash = _sha("|".join([trigger_id, review_text]))
    candidate_id = "hermes-feedback-self-review-" + report_hash
    upgrade_input_id = "hermes-upgrade-input-self-review-" + report_hash
    native_skill_observed = bool(native.get("skill_write_observed_after_trigger", False))
    report_available = bool(trigger_success and _looks_like_self_review_report(review_text))
    diagnostic_available = bool(review_text.strip() and not report_available)
    report_items = _extract_report_items(review_text) if report_available else []
    ready = bool(trigger_success and report_available)
    created_at = _now_iso()
    source_refs = [{
        "source_system": "hermes",
        "artifact_type": "hermes_self_review_trigger_receipt",
        "source_path": receipt_path,
        "trigger_id": trigger_id,
        "session_id": session_id,
    }]
    if review_text_source == "hermes_state_db" and review_state_db_path:
        source_refs.append({
            "source_system": "hermes",
            "artifact_type": "hermes_state_db_self_review_report",
            "source_path": review_state_db_path,
            "trigger_id": trigger_id,
            "session_id": session_id,
            "message_id": review_state_db_message_id,
            "read_mode": "sqlite_ro",
        })
    for item in report_items:
        source_path = str(item.get("source_path") or "").strip()
        if source_path:
            source_refs.append({
                "source_system": "yifanchen",
                "artifact_type": "self_review_report_source_path",
                "source_path": source_path,
                "trigger_id": trigger_id,
            })
    candidate = {
        "candidate_id": candidate_id,
        "candidate_type": "hermes_self_review_report_candidate",
        "schema_version": SELF_REVIEW_REPORT_VERSION,
        "title": "Hermes self-review report -> experience review",
        "summary": _compact(review_text, 600),
        "created_at": created_at,
        "platform": "hermes",
        "lifecycle_status": "candidate",
        "frontstage_surface": "experience_service",
        "source_mode": "hermes_self_review_report",
        "source_observer": "hermes_self_review_trigger",
        "trigger_id": trigger_id,
        "trigger_receipt_path": receipt_path,
        "review_text_source": review_text_source,
        "review_session_id": session_id,
        "review_state_db_path": review_state_db_path,
        "review_state_db_error": review_state_db_error,
        "review_state_db_message_id": review_state_db_message_id,
        "requested_session_ids": [session_id] if session_id else [],
        "report_items": report_items,
        "evidence_refs": source_refs,
        "source_refs": source_refs,
        "verbatim_excerpt": _compact(review_text, 1200),
        "comparison_result": {
            "change_class": "self_review_report_without_native_skill_write"
            if not native_skill_observed else "self_review_report_with_native_skill_write",
            "native_skill_learning_feedback_closed": False,
            "trigger_exit_code": exit_code,
            "trigger_timed_out": timed_out,
            "trigger_success": trigger_success,
            "report_available": report_available,
            "diagnostic_available": diagnostic_available,
            "report_item_count": len(report_items),
            "review_text_source": review_text_source,
            "native_skill_write_observed_after_trigger": native_skill_observed,
        },
        "confidence": 0.7 if ready else 0.3,
        "recommended_experience_service_actions": [
            "review_self_review_report",
            "compare_report_items_with_existing_experience",
            "route_accepted_items_to_existing_upgrade_gate",
        ],
        "write_boundary": {
            "write_performed": False,
            "candidate_artifact_write_performed": False,
            "upgrade_input_artifact_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "hermes_write_performed": False,
            "hermes_skill_write_performed": False,
            "openclaw_write_performed": False,
            "platform_write_performed": False,
            "production_experience_write_performed": False,
        },
        "notes": [
            "candidate_only",
            "self_review_report_not_auto_adopted",
            "yifanchen_did_not_write_hermes_skill",
        ],
    }
    upgrade_input = {
        "upgrade_input_id": upgrade_input_id,
        "candidate_id": candidate_id,
        "candidate_type": "hermes_self_review_report_upgrade_input",
        "schema_version": SELF_REVIEW_REPORT_VERSION,
        "source_mode": "hermes_self_review_report",
        "created_at": created_at,
        "upgrade_input_status": "ready_for_experience_review_self_review_report_observed" if ready else "blocked_no_successful_report",
        "experience_upgrade_ready": ready,
        "production_experience_write_performed": False,
        "source_candidate": candidate,
        "source_action": {
            "action": "record_self_review_report_for_review",
            "action_status": "draft",
            "trigger_id": trigger_id,
        },
        "fresh_observation": {
            "requested_sessions_observed": bool(session_id),
            "review_text_source": review_text_source,
            "review_session_id": session_id,
            "review_state_db_path": review_state_db_path,
            "review_state_db_error": review_state_db_error,
            "observed_write_flags": {
                "skill": native_skill_observed,
                "learning": False,
                "memory": False,
            },
        },
        "comparison_result": {
            "previous_change_class": "",
            "fresh_change_class": candidate["comparison_result"]["change_class"],
            "native_change_observed_after_action": native_skill_observed,
            "self_review_report_observed": report_available,
            "diagnostic_available": diagnostic_available,
            "report_item_count": len(report_items),
            "review_text_source": review_text_source,
        },
        "write_boundary": dict(candidate["write_boundary"]),
        "notes": [
            "review_input_only",
            "not_a_production_experience_write",
            "not_a_hermes_skill_write",
        ],
    }
    return {
        "ok": not bool(receipt_error) and report_available,
        "version": SELF_REVIEW_REPORT_VERSION,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "candidate_artifact_write_performed": False,
        "upgrade_input_artifact_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "hermes_skill_write_performed": False,
        "openclaw_write_performed": False,
        "production_experience_write_performed": False,
        "trigger_receipt_path": receipt_path,
        "trigger_receipt_error": receipt_error,
        "trigger_id": trigger_id,
        "trigger_exit_code": exit_code,
        "trigger_success": trigger_success,
        "review_text_source": review_text_source,
        "review_session_id": session_id,
        "review_state_db_path": review_state_db_path,
        "review_state_db_error": review_state_db_error,
        "review_state_db_message_id": review_state_db_message_id,
        "report_available": report_available,
        "diagnostic_available": diagnostic_available,
        "diagnostic_excerpt": _compact(review_text, 600) if diagnostic_available else "",
        "report_item_count": len(report_items),
        "candidate": candidate,
        "upgrade_input": upgrade_input,
        "notes": [
            "dry_run_only",
            "self_review_report_to_review_material",
            "no_memory_or_platform_write",
        ],
    }


def record_hermes_self_review_report_candidate(
    body: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else body
    required = {
        "confirm_record_self_review_report_candidate": _truthy(authorization.get("confirm_record_self_review_report_candidate")),
        "confirm_no_raw_zhiyi_xingce_write": _truthy(authorization.get("confirm_no_raw_zhiyi_xingce_write")),
        "confirm_no_hermes_skill_write": _truthy(authorization.get("confirm_no_hermes_skill_write")),
        "operator": bool(str(authorization.get("operator") or "").strip()),
        "reason": bool(str(authorization.get("reason") or "").strip()),
    }
    missing = [name for name, ok in required.items() if not ok]
    dry_run = build_hermes_self_review_report_dry_run(body, memcore_root=memcore_root)
    base = _feedback_base(memcore_root)
    guard_failures = []
    if not base:
        guard_failures.append("memcore_root_required")
    if not dry_run.get("report_available"):
        guard_failures.append("self_review_report_required")
    if not dry_run.get("trigger_success"):
        guard_failures.append("successful_trigger_required")
    if not dry_run.get("trigger_id"):
        guard_failures.append("trigger_id_required")
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "candidate_artifact_write_performed": False,
            "upgrade_input_artifact_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "hermes_skill_write_performed": False,
            "openclaw_write_performed": False,
            "production_experience_write_performed": False,
            "missing_authorization": missing,
            "guard_failures": guard_failures,
            "dry_run": dry_run,
        }
    assert base is not None
    candidate = dict(dry_run["candidate"])
    upgrade_input = dict(dry_run["upgrade_input"])
    candidate["write_boundary"] = dict(candidate.get("write_boundary", {}))
    candidate["write_boundary"].update({
        "write_performed": True,
        "candidate_artifact_write_performed": True,
    })
    upgrade_input["write_boundary"] = dict(upgrade_input.get("write_boundary", {}))
    upgrade_input["write_boundary"].update({
        "write_performed": True,
        "candidate_artifact_write_performed": True,
        "upgrade_input_artifact_write_performed": True,
    })
    candidate["record_authorization"] = {
        "operator": str(authorization.get("operator") or ""),
        "reason": str(authorization.get("reason") or ""),
        "confirm_record_self_review_report_candidate": True,
        "confirm_no_raw_zhiyi_xingce_write": True,
        "confirm_no_hermes_skill_write": True,
    }
    upgrade_input["record_authorization"] = dict(candidate["record_authorization"])
    candidates_dir = base / "candidates"
    upgrade_inputs_dir = base / "upgrade_inputs"
    candidate_path = candidates_dir / f"{candidate['candidate_id']}.json"
    upgrade_input_path = upgrade_inputs_dir / f"{upgrade_input['upgrade_input_id']}.json"
    _write_json(candidate_path, candidate)
    _write_json(candidates_dir / "latest.json", candidate)
    _write_json(upgrade_input_path, upgrade_input)
    _write_json(upgrade_inputs_dir / "latest.json", upgrade_input)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "candidate_artifact_write_performed": True,
        "upgrade_input_artifact_write_performed": True,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "hermes_skill_write_performed": False,
        "openclaw_write_performed": False,
        "platform_write_performed": False,
        "production_experience_write_performed": False,
        "candidate_id": candidate["candidate_id"],
        "upgrade_input_id": upgrade_input["upgrade_input_id"],
        "candidate_path": str(candidate_path),
        "upgrade_input_path": str(upgrade_input_path),
        "latest_candidate_path": str(candidates_dir / "latest.json"),
        "latest_upgrade_input_path": str(upgrade_inputs_dir / "latest.json"),
        "candidate": candidate,
        "upgrade_input": upgrade_input,
        "dry_run": dry_run,
    }
