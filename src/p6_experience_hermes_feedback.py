#!/usr/bin/env python3
"""Hermes feedback governance under the Experience Governance workbench.

Tiandao contract: this module owns Hermes-derived feedback queues,
consumption receipts, self-review/probe receipts, and candidate action
receipts. It is a derived governance layer: raw records remain the Time
Origin, and this module never writes Hermes native skills, raw archives,
platform stores, or production Zhiyi case memory.
"""

from __future__ import annotations

import datetime
import glob
import json
import os
from typing import Any

try:
    from src.config_loader import base_path
except Exception:  # pragma: no cover
    from config_loader import base_path
try:
    from src.hermes_native_liveness import (
        build_hermes_native_learning_liveness,
        build_hermes_self_review_wake_dry_run,
        persist_hermes_self_review_signal_receipt,
        build_hermes_self_review_trigger_plan,
        trigger_hermes_self_review,
        query_hermes_self_review_triggers,
        build_hermes_skill_generation_probe_plan,
        trigger_hermes_skill_generation_probe,
        query_hermes_skill_generation_probes,
        build_hermes_skill_artifact_status_dry_run,
        record_hermes_skill_artifact_status,
        query_hermes_skill_artifact_statuses,
    )
except Exception:  # pragma: no cover
    from hermes_native_liveness import (
        build_hermes_native_learning_liveness,
        build_hermes_self_review_wake_dry_run,
        persist_hermes_self_review_signal_receipt,
        build_hermes_self_review_trigger_plan,
        trigger_hermes_self_review,
        query_hermes_self_review_triggers,
        build_hermes_skill_generation_probe_plan,
        trigger_hermes_skill_generation_probe,
        query_hermes_skill_generation_probes,
        build_hermes_skill_artifact_status_dry_run,
        record_hermes_skill_artifact_status,
        query_hermes_skill_artifact_statuses,
    )
try:
    from src.hermes_autonomous_loop import (
        build_hermes_autonomous_loop_plan,
        load_hermes_autonomous_loop_state,
        query_hermes_autonomous_loop_runs,
        run_hermes_autonomous_loop_once,
    )
except Exception:  # pragma: no cover
    from hermes_autonomous_loop import (
        build_hermes_autonomous_loop_plan,
        load_hermes_autonomous_loop_state,
        query_hermes_autonomous_loop_runs,
        run_hermes_autonomous_loop_once,
    )
try:
    from src.p6_zhiyi_model_runtime import _compact_text, _usage_log_positive_int
except Exception:  # pragma: no cover
    from p6_zhiyi_model_runtime import _compact_text, _usage_log_positive_int

MEMCORE_ROOT = str(base_path())
EXPERIENCE_HERMES_FEEDBACK_CONTRACT = "tiandao_experience_hermes_feedback_governance.v1"


def configure_experience_hermes_feedback(memcore_root):
    global MEMCORE_ROOT
    MEMCORE_ROOT = str(memcore_root)


def get_experience_hermes_feedback_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": EXPERIENCE_HERMES_FEEDBACK_CONTRACT,
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "workbench_id": "experience_governance",
        "governance_layer": "hermes_feedback_governance",
        "source_authority": "experience_governance_workbench",
        "read_only_by_default": True,
        "write_capable": True,
        "authorization_required_for_write": True,
        "not_raw_origin": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "raw_origin_policy": "Hermes feedback governance stores derived receipts only; raw/time origin remains authoritative",
        "authorized_write_scopes": [
            "hermes_consumption_receipt",
            "hermes_feedback_action_receipt",
            "hermes_self_review_signal_receipt",
            "hermes_self_review_trigger_receipt",
            "hermes_skill_generation_probe_receipt",
            "hermes_skill_artifact_status_receipt",
        ],
        "forbidden_write_scopes": [
            "raw_archive",
            "hermes_native_skill_file",
            "hermes_native_memory_store",
            "platform_config",
            "production_zhiyi_case_memory",
        ],
    }


def _hermes_feedback_candidates_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "hermes_experience_feedback", "candidates")


def _hermes_feedback_actions_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "hermes_experience_feedback", "actions")


def _hermes_feedback_upgrade_inputs_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "hermes_experience_feedback", "upgrade_inputs")


def _hermes_consumption_receipts_dir():
    return os.path.join(str(MEMCORE_ROOT), "output", "hermes_consumption", "turn_receipts")


def query_hermes_native_learning_liveness(params=None):
    params = params or {}
    cold_after_hours = 72
    try:
        cold_after_hours = int(params.get("cold_after_hours", cold_after_hours))
    except Exception:
        cold_after_hours = 72
    return build_hermes_native_learning_liveness(
        hermes_home=params.get("hermes_home") or None,
        memcore_root=str(MEMCORE_ROOT),
        cold_after_hours=cold_after_hours,
    )


def persist_hermes_consumption_receipt(body=None):
    body = body if isinstance(body, dict) else {}
    import uuid

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt_id = "hermes-consumption-" + uuid.uuid4().hex[:16]
    last_prefetch = body.get("last_prefetch", {}) if isinstance(body.get("last_prefetch"), dict) else {}
    last_queue_prefetch = body.get("last_queue_prefetch", {}) if isinstance(body.get("last_queue_prefetch"), dict) else {}
    messages = body.get("messages", []) if isinstance(body.get("messages"), list) else []
    receipt = {
        "schema_version": "1.0",
        "receipt_id": receipt_id,
        "created_at": now_iso,
        "event_type": str(body.get("event_type") or "hermes_turn_consumption_receipt"),
        "provider": str(body.get("provider") or "time_library"),
        "session_id": str(body.get("session_id") or ""),
        "memory_scope": str(body.get("memory_scope") or ""),
        "user_content": str(body.get("user_content") or ""),
        "assistant_content": str(body.get("assistant_content") or ""),
        "messages": messages,
        "last_prefetch": last_prefetch,
        "last_queue_prefetch": last_queue_prefetch,
        "consumption_summary": {
            "prefetch_ok": bool(last_prefetch.get("ok", False)),
            "prefetch_matched_count": int(last_prefetch.get("matched_count", 0) or 0),
            "prefetch_source_refs_count": int(last_prefetch.get("source_refs_count", 0) or 0),
            "queue_prefetch_ok": bool(last_queue_prefetch.get("ok", False)),
            "queue_prefetch_matched_count": int(last_queue_prefetch.get("matched_count", 0) or 0),
        },
        "write_boundary": {
            "consumption_receipt_write_performed": True,
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
            "hermes_sync_turn_consumption_receipt",
            "receipt_is_not_raw_archive",
            "no_hermes_skill_or_memory_write",
            "no_production_experience_write",
        ],
    }
    receipts_dir = _hermes_consumption_receipts_dir()
    os.makedirs(receipts_dir, exist_ok=True)
    receipt_path = os.path.join(receipts_dir, f"{now_iso.replace(':', '').replace('-', '')}-{receipt_id}.jsonl")
    _jsonl_append(receipt_path, receipt)
    latest_path = os.path.join(receipts_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "consumption_receipt_write_performed": True,
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
        "receipt_id": receipt_id,
        "receipt_path": receipt_path,
        "latest_path": latest_path,
        "receipt": receipt,
    }


def query_hermes_consumption_receipts(params=None):
    params = params or {}
    limit = _usage_log_positive_int(params.get("limit", 20), 20, 100)
    receipts_dir = _hermes_consumption_receipts_dir()
    items = []
    parse_errors = []
    if os.path.isdir(receipts_dir):
        try:
            names = sorted(os.listdir(receipts_dir), reverse=True)
        except Exception as exc:
            names = []
            parse_errors.append({"path": receipts_dir, "error": str(exc)[:120]})
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(receipts_dir, name)
            records = _read_jsonl_records(path)
            for record in records:
                record["_source_path"] = path
                items.append(record)
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
    latest_path = os.path.join(receipts_dir, "latest.json")
    latest, latest_err = _read_hermes_feedback_json(latest_path)
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "receipts_dir": receipts_dir,
        "receipts_dir_exists": os.path.isdir(receipts_dir),
        "latest_path": latest_path,
        "latest": latest if not latest_err else {},
        "items": items,
        "count": len(items),
        "parse_errors": parse_errors,
        "notes": [
            "hermes_consumption_receipts_are_read_only_here",
            "receipt_items_are_not_raw_archive_records",
        ],
    }


def build_hermes_self_review_wake_http_dry_run(body=None):
    body = body if isinstance(body, dict) else {}
    cold_after_hours = 72
    try:
        cold_after_hours = int(body.get("cold_after_hours", cold_after_hours))
    except Exception:
        cold_after_hours = 72
    return build_hermes_self_review_wake_dry_run(
        hermes_home=body.get("hermes_home") or None,
        memcore_root=str(MEMCORE_ROOT),
        cold_after_hours=cold_after_hours,
        requested_by=str(body.get("requested_by") or body.get("operator") or ""),
        reason=str(body.get("reason") or ""),
    )


def apply_hermes_self_review_signal_receipt_http(body=None):
    body = body if isinstance(body, dict) else {}
    cold_after_hours = 72
    try:
        cold_after_hours = int(body.get("cold_after_hours", cold_after_hours))
    except Exception:
        cold_after_hours = 72
    return persist_hermes_self_review_signal_receipt(
        body,
        hermes_home=body.get("hermes_home") or None,
        memcore_root=str(MEMCORE_ROOT),
        cold_after_hours=cold_after_hours,
    )


def build_hermes_self_review_trigger_http_dry_run(body=None):
    body = body if isinstance(body, dict) else {}
    cold_after_hours = 72
    try:
        cold_after_hours = int(body.get("cold_after_hours", cold_after_hours))
    except Exception:
        cold_after_hours = 72
    return build_hermes_self_review_trigger_plan(
        body,
        hermes_home=body.get("hermes_home") or None,
        memcore_root=str(MEMCORE_ROOT),
        cold_after_hours=cold_after_hours,
    )


def apply_hermes_self_review_trigger_http(body=None):
    body = body if isinstance(body, dict) else {}
    cold_after_hours = 72
    try:
        cold_after_hours = int(body.get("cold_after_hours", cold_after_hours))
    except Exception:
        cold_after_hours = 72
    return trigger_hermes_self_review(
        body,
        hermes_home=body.get("hermes_home") or None,
        memcore_root=str(MEMCORE_ROOT),
        cold_after_hours=cold_after_hours,
    )


def query_hermes_self_review_triggers_http(params=None):
    params = params or {}
    limit = 20
    try:
        limit = int(params.get("limit", limit))
    except Exception:
        limit = 20
    return query_hermes_self_review_triggers(
        memcore_root=str(MEMCORE_ROOT),
        limit=limit,
    )


def build_hermes_skill_generation_probe_http_dry_run(body=None):
    body = body if isinstance(body, dict) else {}
    cold_after_hours = 72
    try:
        cold_after_hours = int(body.get("cold_after_hours", cold_after_hours))
    except Exception:
        cold_after_hours = 72
    return build_hermes_skill_generation_probe_plan(
        body,
        hermes_home=body.get("hermes_home") or None,
        memcore_root=str(MEMCORE_ROOT),
        cold_after_hours=cold_after_hours,
    )


def apply_hermes_skill_generation_probe_http(body=None):
    body = body if isinstance(body, dict) else {}
    cold_after_hours = 72
    try:
        cold_after_hours = int(body.get("cold_after_hours", cold_after_hours))
    except Exception:
        cold_after_hours = 72
    return trigger_hermes_skill_generation_probe(
        body,
        hermes_home=body.get("hermes_home") or None,
        memcore_root=str(MEMCORE_ROOT),
        cold_after_hours=cold_after_hours,
    )


def query_hermes_skill_generation_probes_http(params=None):
    params = params or {}
    limit = 20
    try:
        limit = int(params.get("limit", limit))
    except Exception:
        limit = 20
    return query_hermes_skill_generation_probes(
        memcore_root=str(MEMCORE_ROOT),
        limit=limit,
    )


def build_hermes_skill_artifact_status_http_dry_run(body=None):
    body = body if isinstance(body, dict) else {}
    return build_hermes_skill_artifact_status_dry_run(
        body,
        memcore_root=str(MEMCORE_ROOT),
    )


def record_hermes_skill_artifact_status_http(body=None):
    body = body if isinstance(body, dict) else {}
    return record_hermes_skill_artifact_status(
        body,
        memcore_root=str(MEMCORE_ROOT),
    )


def query_hermes_skill_artifact_statuses_http(params=None):
    params = params or {}
    limit = 20
    try:
        limit = int(params.get("limit", limit))
    except Exception:
        limit = 20
    return query_hermes_skill_artifact_statuses(
        memcore_root=str(MEMCORE_ROOT),
        limit=limit,
    )


def query_hermes_autonomous_loop_state_http(params=None):
    return load_hermes_autonomous_loop_state(
        memcore_root=str(MEMCORE_ROOT),
    )


def build_hermes_autonomous_loop_http_dry_run(body=None):
    body = body if isinstance(body, dict) else {}
    return build_hermes_autonomous_loop_plan(
        body,
        memcore_root=str(MEMCORE_ROOT),
        source_system=str(body.get("source_system") or "hermes"),
    )


def apply_hermes_autonomous_loop_http(body=None):
    body = body if isinstance(body, dict) else {}
    return run_hermes_autonomous_loop_once(
        body,
        hermes_home=body.get("hermes_home") or None,
        memcore_root=str(MEMCORE_ROOT),
    )


def query_hermes_autonomous_loop_runs_http(params=None):
    params = params or {}
    limit = 20
    try:
        limit = int(params.get("limit", limit))
    except Exception:
        limit = 20
    return query_hermes_autonomous_loop_runs(
        memcore_root=str(MEMCORE_ROOT),
        limit=limit,
    )


def _hermes_feedback_action_bool(value):
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "confirmed", "confirm")
    return False


def _read_hermes_feedback_json(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data, ""
        return {}, "candidate_json_not_object"
    except FileNotFoundError:
        return {}, "candidate_not_found"
    except Exception as exc:
        return {}, f"candidate_read_failed:{str(exc)[:120]}"


def _safe_hermes_candidate_id(candidate_id):
    candidate_id = str(candidate_id or "").strip()
    if candidate_id.endswith(".json"):
        candidate_id = candidate_id[:-5]
    safe = "".join(ch for ch in candidate_id if ch.isalnum() or ch in ("-", "_"))
    if not safe or safe != candidate_id:
        return ""
    return safe

def _jsonl_append(path, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _read_jsonl_records(path):
    records = []
    if not os.path.exists(path):
        return records
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, 1):
                text = line.strip()
                if not text:
                    continue
                try:
                    rec = json.loads(text)
                except Exception:
                    continue
                if isinstance(rec, dict):
                    rec["_line_no"] = line_no
                    records.append(rec)
    except Exception:
        return records
    return records


def _hermes_feedback_candidate_summary(candidate, source_path="", latest_candidate_id=""):
    comparison = candidate.get("comparison_result", {}) if isinstance(candidate.get("comparison_result"), dict) else {}
    write_boundary = candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {}
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    candidate_id = candidate.get("candidate_id", "")
    return {
        "candidate_id": candidate_id,
        "candidate_type": candidate.get("candidate_type", ""),
        "title": candidate.get("title", ""),
        "summary": _compact_text(candidate.get("summary", ""), 360),
        "created_at": candidate.get("created_at", ""),
        "platform": candidate.get("platform", ""),
        "lifecycle_status": candidate.get("lifecycle_status", ""),
        "frontstage_surface": candidate.get("frontstage_surface", ""),
        "source_mode": candidate.get("source_mode", ""),
        "source_observer": candidate.get("source_observer", ""),
        "change_class": comparison.get("change_class", ""),
        "native_skill_learning_feedback_closed": bool(comparison.get("native_skill_learning_feedback_closed", False)),
        "confidence": candidate.get("confidence", 0),
        "requested_session_ids": candidate.get("requested_session_ids", []),
        "evidence_refs_count": len(evidence_refs),
        "source_refs_count": len(source_refs),
        "recommended_actions_count": len(candidate.get("recommended_experience_service_actions", []) or []),
        "write_boundary": write_boundary,
        "production_experience_write_performed": bool(write_boundary.get("production_experience_write_performed", False)),
        "raw_write_performed": bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_performed": bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_performed": bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_performed": bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_performed": bool(write_boundary.get("openclaw_write_performed", False)),
        "source_path": source_path,
        "is_latest": bool(candidate_id and candidate_id == latest_candidate_id),
        "detail_endpoint": f"/api/v1/hermes/feedback-candidates/{candidate_id}" if candidate_id else "",
    }


def _hermes_feedback_upgrade_input_summary(upgrade_input, source_path="", latest_upgrade_input_id=""):
    write_boundary = upgrade_input.get("write_boundary", {}) if isinstance(upgrade_input.get("write_boundary"), dict) else {}
    fresh = upgrade_input.get("fresh_observation", {}) if isinstance(upgrade_input.get("fresh_observation"), dict) else {}
    flags = fresh.get("observed_write_flags", {}) if isinstance(fresh.get("observed_write_flags"), dict) else {}
    comparison = upgrade_input.get("comparison_result", {}) if isinstance(upgrade_input.get("comparison_result"), dict) else {}
    source_action = upgrade_input.get("source_action", {}) if isinstance(upgrade_input.get("source_action"), dict) else {}
    source_candidate = upgrade_input.get("source_candidate", {}) if isinstance(upgrade_input.get("source_candidate"), dict) else {}
    upgrade_input_id = upgrade_input.get("upgrade_input_id", "")
    return {
        "upgrade_input_id": upgrade_input_id,
        "candidate_id": upgrade_input.get("candidate_id", ""),
        "candidate_type": upgrade_input.get("candidate_type", ""),
        "source_mode": upgrade_input.get("source_mode", ""),
        "created_at": upgrade_input.get("created_at", ""),
        "upgrade_input_status": upgrade_input.get("upgrade_input_status", ""),
        "experience_upgrade_ready": bool(upgrade_input.get("experience_upgrade_ready", False)),
        "production_experience_write_performed": bool(upgrade_input.get("production_experience_write_performed", False)),
        "fresh_requested_sessions_observed": bool(fresh.get("requested_sessions_observed", False)),
        "fresh_write_flags": {
            "skill": bool(flags.get("skill", False)),
            "learning": bool(flags.get("learning", False)),
            "memory": bool(flags.get("memory", False)),
        },
        "previous_change_class": comparison.get("previous_change_class", ""),
        "fresh_change_class": comparison.get("fresh_change_class", ""),
        "native_change_observed_after_action": bool(comparison.get("native_change_observed_after_action", False)),
        "source_action_status": source_action.get("action_status", ""),
        "source_action": source_action.get("action", ""),
        "source_candidate_change_class": source_candidate.get("change_class", ""),
        "write_boundary": write_boundary,
        "raw_write_performed": bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_performed": bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_performed": bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_performed": bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_performed": bool(write_boundary.get("openclaw_write_performed", False)),
        "source_path": source_path,
        "is_latest": bool(upgrade_input_id and upgrade_input_id == latest_upgrade_input_id),
        "detail_endpoint": f"/api/v1/hermes/feedback-upgrade-inputs/{upgrade_input_id}" if upgrade_input_id else "",
    }


def _latest_hermes_feedback_candidate_id(candidates_dir):
    latest_path = os.path.join(candidates_dir, "latest.json")
    latest, err = _read_hermes_feedback_json(latest_path)
    if err:
        return "", latest_path, {}
    return str(latest.get("candidate_id", "") or ""), latest_path, latest


def _latest_hermes_feedback_upgrade_input_id(upgrade_inputs_dir):
    latest_path = os.path.join(upgrade_inputs_dir, "latest.json")
    latest, err = _read_hermes_feedback_json(latest_path)
    if err:
        return "", latest_path, {}
    return str(latest.get("upgrade_input_id", "") or ""), latest_path, latest


def _hermes_feedback_action_history(candidate_id="", limit=20):
    actions_dir = _hermes_feedback_actions_dir()
    items = []
    parse_errors = []
    if not os.path.isdir(actions_dir):
        return items, parse_errors
    try:
        names = sorted(os.listdir(actions_dir), reverse=True)
    except Exception as exc:
        return items, [{"path": actions_dir, "error": str(exc)[:120]}]
    safe_id = _safe_hermes_candidate_id(candidate_id)
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(actions_dir, name)
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                line = f.readline().strip()
            if not line:
                continue
            item = json.loads(line)
        except Exception as exc:
            parse_errors.append({"path": path, "error": str(exc)[:120]})
            continue
        if safe_id and item.get("candidate_id") != safe_id:
            continue
        item["_source_path"] = path
        items.append(item)
        if len(items) >= limit:
            break
    return items, parse_errors


def query_hermes_feedback_candidates(params=None):
    """Expose generated Hermes observation feedback candidates without mutating state."""
    params = params or {}
    candidates_dir = _hermes_feedback_candidates_dir()
    candidates_dir_exists = os.path.isdir(candidates_dir)
    latest_candidate_id, latest_path, latest_candidate = _latest_hermes_feedback_candidate_id(candidates_dir)
    page = _usage_log_positive_int(params.get("page", 1), 1, 1000000)
    page_size = _usage_log_positive_int(params.get("page_size", 20), 20, 50)
    status_filter = str(params.get("lifecycle_status", "") or "").strip()
    source_mode_filter = str(params.get("source_mode", "") or "").strip()

    items = []
    parse_errors = []
    seen = set()
    if candidates_dir_exists:
        for path in sorted(glob.glob(os.path.join(candidates_dir, "hermes-feedback-*.json"))):
            candidate, err = _read_hermes_feedback_json(path)
            if err:
                parse_errors.append({"path": path, "error": err})
                continue
            candidate_id = str(candidate.get("candidate_id", "") or "")
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            items.append(_hermes_feedback_candidate_summary(candidate, path, latest_candidate_id))

    if latest_candidate and latest_candidate_id and latest_candidate_id not in seen:
        items.append(_hermes_feedback_candidate_summary(latest_candidate, latest_path, latest_candidate_id))

    def sort_key(item):
        return (item.get("created_at") or "", item.get("candidate_id") or "")

    items.sort(key=sort_key, reverse=True)
    if status_filter:
        items = [item for item in items if item.get("lifecycle_status") == status_filter]
    if source_mode_filter:
        items = [item for item in items if item.get("source_mode") == source_mode_filter]
    for item in items:
        history, _ = _hermes_feedback_action_history(item.get("candidate_id", ""), limit=1)
        item["action_count"] = len(_hermes_feedback_action_history(item.get("candidate_id", ""), limit=1000000)[0])
        item["latest_action"] = history[0] if history else None
        item["action_endpoint"] = f"/api/v1/hermes/feedback-candidates/{item.get('candidate_id', '')}/actions"

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidates_dir": candidates_dir,
        "candidates_dir_exists": candidates_dir_exists,
        "latest_candidate_id": latest_candidate_id,
        "latest_path": latest_path,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "items": items[start:end],
        "parse_errors": parse_errors,
        "filters": {
            "lifecycle_status": status_filter,
            "source_mode": source_mode_filter,
        },
        "query_contract": {
            "schema_version": "1.0",
            "source": "output/hermes_experience_feedback/candidates/*.json",
            "order": "newest_first",
            "method": "GET",
            "write_performed": False,
        },
        "notes": [
            "candidate_artifact_read_only",
            "no_raw_zhiyi_xingce_hermes_openclaw_write",
            "production_experience_upgrade_not_applied_by_this_api",
        ],
    }


def query_hermes_feedback_actions(params=None):
    params = params or {}
    candidate_id = str(params.get("candidate_id", "") or "").strip()
    limit = _usage_log_positive_int(params.get("limit", 20), 20, 100)
    items, parse_errors = _hermes_feedback_action_history(candidate_id, limit=limit)
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "actions_dir": _hermes_feedback_actions_dir(),
        "candidate_id": candidate_id,
        "total": len(items),
        "items": items,
        "parse_errors": parse_errors,
    }


def query_hermes_feedback_upgrade_inputs(params=None):
    """Expose Hermes feedback upgrade inputs without mutating state."""
    params = params or {}
    upgrade_inputs_dir = _hermes_feedback_upgrade_inputs_dir()
    upgrade_inputs_dir_exists = os.path.isdir(upgrade_inputs_dir)
    latest_upgrade_input_id, latest_path, latest_upgrade_input = _latest_hermes_feedback_upgrade_input_id(upgrade_inputs_dir)
    page = _usage_log_positive_int(params.get("page", 1), 1, 1000000)
    page_size = _usage_log_positive_int(params.get("page_size", 20), 20, 50)
    status_filter = str(params.get("upgrade_input_status", "") or "").strip()
    candidate_filter = str(params.get("candidate_id", "") or "").strip()

    items = []
    parse_errors = []
    seen = set()
    if upgrade_inputs_dir_exists:
        for path in sorted(glob.glob(os.path.join(upgrade_inputs_dir, "hermes-upgrade-input-*.json"))):
            upgrade_input, err = _read_hermes_feedback_json(path)
            if err:
                parse_errors.append({"path": path, "error": err})
                continue
            upgrade_input_id = str(upgrade_input.get("upgrade_input_id", "") or "")
            if upgrade_input_id in seen:
                continue
            seen.add(upgrade_input_id)
            items.append(_hermes_feedback_upgrade_input_summary(upgrade_input, path, latest_upgrade_input_id))

    if latest_upgrade_input and latest_upgrade_input_id and latest_upgrade_input_id not in seen:
        items.append(_hermes_feedback_upgrade_input_summary(latest_upgrade_input, latest_path, latest_upgrade_input_id))

    items.sort(key=lambda item: (item.get("created_at") or "", item.get("upgrade_input_id") or ""), reverse=True)
    if status_filter:
        items = [item for item in items if item.get("upgrade_input_status") == status_filter]
    if candidate_filter:
        items = [item for item in items if item.get("candidate_id") == candidate_filter]

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "upgrade_inputs_dir": upgrade_inputs_dir,
        "upgrade_inputs_dir_exists": upgrade_inputs_dir_exists,
        "latest_upgrade_input_id": latest_upgrade_input_id,
        "latest_path": latest_path,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "items": items[start:end],
        "parse_errors": parse_errors,
        "filters": {
            "upgrade_input_status": status_filter,
            "candidate_id": candidate_filter,
        },
        "query_contract": {
            "schema_version": "1.0",
            "source": "output/hermes_experience_feedback/upgrade_inputs/*.json",
            "order": "newest_first",
            "method": "GET",
            "write_performed": False,
        },
        "notes": [
            "upgrade_input_artifact_read_only",
            "no_raw_zhiyi_xingce_hermes_openclaw_write",
            "production_experience_upgrade_not_applied_by_this_api",
        ],
    }


def get_hermes_feedback_upgrade_input(upgrade_input_id):
    upgrade_inputs_dir = _hermes_feedback_upgrade_inputs_dir()
    safe_id = _safe_hermes_candidate_id(upgrade_input_id)
    latest_upgrade_input_id, latest_path, latest_upgrade_input = _latest_hermes_feedback_upgrade_input_id(upgrade_inputs_dir)
    if safe_id == "latest":
        upgrade_input = latest_upgrade_input
        source_path = latest_path
    elif safe_id:
        source_path = os.path.join(upgrade_inputs_dir, f"{safe_id}.json")
        upgrade_input, err = _read_hermes_feedback_json(source_path)
        if err and safe_id == latest_upgrade_input_id and latest_upgrade_input:
            upgrade_input = latest_upgrade_input
            source_path = latest_path
    else:
        upgrade_input = {}
        source_path = ""
    if not upgrade_input:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "error": "upgrade_input_not_found",
            "upgrade_input_id": upgrade_input_id,
            "upgrade_inputs_dir": upgrade_inputs_dir,
        }
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "upgrade_input_id": upgrade_input.get("upgrade_input_id", safe_id),
        "latest_upgrade_input_id": latest_upgrade_input_id,
        "upgrade_inputs_dir": upgrade_inputs_dir,
        "source_path": source_path,
        "summary": _hermes_feedback_upgrade_input_summary(upgrade_input, source_path, latest_upgrade_input_id),
        "write_boundary": upgrade_input.get("write_boundary", {}) if isinstance(upgrade_input.get("write_boundary"), dict) else {},
        "upgrade_input": upgrade_input,
    }


def get_hermes_feedback_candidate(candidate_id):
    candidates_dir = _hermes_feedback_candidates_dir()
    safe_id = _safe_hermes_candidate_id(candidate_id)
    latest_candidate_id, latest_path, latest_candidate = _latest_hermes_feedback_candidate_id(candidates_dir)
    if safe_id == "latest":
        candidate = latest_candidate
        source_path = latest_path
    elif safe_id:
        source_path = os.path.join(candidates_dir, f"{safe_id}.json")
        candidate, err = _read_hermes_feedback_json(source_path)
        if err and safe_id == latest_candidate_id and latest_candidate:
            candidate = latest_candidate
            source_path = latest_path
    else:
        candidate = {}
        source_path = ""
    if not candidate:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "error": "candidate_not_found",
            "candidate_id": candidate_id,
            "candidates_dir": candidates_dir,
        }
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "api_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": candidate.get("candidate_id", safe_id),
        "latest_candidate_id": latest_candidate_id,
        "candidates_dir": candidates_dir,
        "source_path": source_path,
        "summary": _hermes_feedback_candidate_summary(candidate, source_path, latest_candidate_id),
        "write_boundary": candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {},
        "actions": _hermes_feedback_action_history(candidate.get("candidate_id", safe_id), limit=20)[0],
        "candidate": candidate,
    }


def apply_hermes_feedback_candidate_action(candidate_id, body=None):
    body = body or {}
    detail = get_hermes_feedback_candidate(candidate_id)
    if not detail.get("ok"):
        return detail
    candidate = detail.get("candidate", {})
    safe_id = _safe_hermes_candidate_id(candidate.get("candidate_id", candidate_id))
    action = str(body.get("action", "") or "").strip()
    aliases = {
        "adopt": "adopt_as_experience",
        "adopt_as_experience": "adopt_as_experience",
        "watch": "watch_for_upgrade",
        "observe": "watch_for_upgrade",
        "watch_for_upgrade": "watch_for_upgrade",
        "recycle": "recycle",
        "recycle_candidate": "recycle",
    }
    action = aliases.get(action, "")
    if action not in ("adopt_as_experience", "watch_for_upgrade", "recycle"):
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "error": "action_must_be_one_of_adopt_as_experience_watch_for_upgrade_recycle",
            "candidate_id": safe_id,
        }

    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        return _hermes_feedback_action_bool(authorization.get(name, body.get(name)))

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    required_checks = {
        "confirm_process_hermes_candidate": confirmed("confirm_process_hermes_candidate"),
        "confirm_write_experience_feedback_action": confirmed("confirm_write_experience_feedback_action"),
        "confirm_no_raw_zhiyi_xingce_hermes_openclaw_write": confirmed("confirm_no_raw_zhiyi_xingce_hermes_openclaw_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    write_boundary = candidate.get("write_boundary", {}) if isinstance(candidate.get("write_boundary"), dict) else {}
    guard_checks = {
        "candidate_id_safe": bool(safe_id),
        "candidate_lifecycle_status": candidate.get("lifecycle_status") == "candidate",
        "candidate_artifact_exists": os.path.isfile(detail.get("source_path", "")),
        "candidate_not_production_written": not bool(write_boundary.get("production_experience_write_performed", False)),
        "raw_write_stays_false": not bool(write_boundary.get("raw_write_performed", False)),
        "zhiyi_write_stays_false": not bool(write_boundary.get("zhiyi_write_performed", False)),
        "xingce_write_stays_false": not bool(write_boundary.get("xingce_write_performed", False)),
        "hermes_write_stays_false": not bool(write_boundary.get("hermes_write_performed", False)),
        "openclaw_write_stays_false": not bool(write_boundary.get("openclaw_write_performed", False)),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if missing or guard_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_performed": False,
            "action_write_performed": False,
            "candidate_id": safe_id,
            "action": action,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": required_checks,
            "guard_checks": guard_checks,
            "guard_failures": guard_failures,
            "error": "blocked_missing_authorization_or_guard_failure",
        }

    import uuid
    actions_dir = _hermes_feedback_actions_dir()
    os.makedirs(actions_dir, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    action_id = "hermes-action-" + uuid.uuid4().hex[:16]
    action_status = {
        "adopt_as_experience": "queued_for_experience_service_adoption",
        "watch_for_upgrade": "watching_for_native_skill_learning_change",
        "recycle": "recycled_from_frontstage_candidate_queue",
    }[action]
    receipt = {
        "schema_version": "1.0",
        "action_id": action_id,
        "created_at": now,
        "candidate_id": safe_id,
        "candidate_type": candidate.get("candidate_type", ""),
        "action": action,
        "action_status": action_status,
        "operator": str(authorization.get("operator", body.get("operator", "")) or ""),
        "reason": str(authorization.get("reason", body.get("reason", "")) or ""),
        "source_candidate_path": detail.get("source_path", ""),
        "source_mode": candidate.get("source_mode", ""),
        "change_class": (candidate.get("comparison_result", {}) if isinstance(candidate.get("comparison_result"), dict) else {}).get("change_class", ""),
        "evidence_refs_count": len(candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []),
        "source_refs_count": len(candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []),
        "write_boundary": {
            "action_receipt_write_performed": True,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "notes": [
            "live_experience_feedback_action_receipt",
            "candidate_artifact_not_modified",
            "no_raw_zhiyi_xingce_hermes_openclaw_write",
        ],
    }
    action_path = os.path.join(actions_dir, f"{now.replace(':', '').replace('-', '')}-{safe_id}-{action}.jsonl")
    with open(action_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
    latest_path = os.path.join(actions_dir, "latest.json")
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "read_only": False,
        "write_performed": True,
        "action_write_performed": True,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_write_performed": False,
        "openclaw_write_performed": False,
        "candidate_id": safe_id,
        "action": action,
        "action_status": action_status,
        "action_id": action_id,
        "action_path": action_path,
        "latest_path": latest_path,
        "receipt": receipt,
    }


__all__ = [
    "EXPERIENCE_HERMES_FEEDBACK_CONTRACT",
    "configure_experience_hermes_feedback",
    "get_experience_hermes_feedback_contract",
    "_hermes_feedback_candidates_dir",
    "_hermes_feedback_actions_dir",
    "_hermes_feedback_upgrade_inputs_dir",
    "_hermes_consumption_receipts_dir",
    "query_hermes_native_learning_liveness",
    "persist_hermes_consumption_receipt",
    "query_hermes_consumption_receipts",
    "build_hermes_self_review_wake_http_dry_run",
    "apply_hermes_self_review_signal_receipt_http",
    "build_hermes_self_review_trigger_http_dry_run",
    "apply_hermes_self_review_trigger_http",
    "query_hermes_self_review_triggers_http",
    "build_hermes_skill_generation_probe_http_dry_run",
    "apply_hermes_skill_generation_probe_http",
    "query_hermes_skill_generation_probes_http",
    "build_hermes_skill_artifact_status_http_dry_run",
    "record_hermes_skill_artifact_status_http",
    "query_hermes_skill_artifact_statuses_http",
    "query_hermes_autonomous_loop_state_http",
    "build_hermes_autonomous_loop_http_dry_run",
    "apply_hermes_autonomous_loop_http",
    "query_hermes_autonomous_loop_runs_http",
    "_hermes_feedback_action_bool",
    "_read_hermes_feedback_json",
    "_safe_hermes_candidate_id",
    "_jsonl_append",
    "_read_jsonl_records",
    "_hermes_feedback_candidate_summary",
    "_hermes_feedback_upgrade_input_summary",
    "_latest_hermes_feedback_candidate_id",
    "_latest_hermes_feedback_upgrade_input_id",
    "_hermes_feedback_action_history",
    "query_hermes_feedback_candidates",
    "query_hermes_feedback_actions",
    "query_hermes_feedback_upgrade_inputs",
    "get_hermes_feedback_upgrade_input",
    "get_hermes_feedback_candidate",
    "apply_hermes_feedback_candidate_action",
]
