#!/usr/bin/env python3
"""Zhiyi usage-log observation layer under Time River.

Tiandao contract: this module owns dry-run usage-log event construction, light
prompt taxonomy, append-gate planning, and read-only usage-log query. It is an
observation/receipt layer for Zhiyi use, not the model runtime controller and
not raw origin.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any, Callable, Dict

try:
    from src.config_loader import base_path
except Exception:
    from config_loader import base_path
try:
    from src.zhiyi_archive import archive_card
except Exception:
    from zhiyi_archive import archive_card

MEMCORE_ROOT = base_path()
ZHIYI_USAGE_LOG_CONTRACT = "tiandao_zhiyi_usage_log_observation.v1"
ZHIYI_USAGE_LIGHT_PROMPT_POLICY_VERSION = "p1-6b.1"
ZHIYI_USAGE_LOG_APPLY_GATE_VERSION = "p1-8.1"
_model_binding_plan_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def configure_zhiyi_usage_log(memcore_root=None, model_binding_plan_builder=None) -> None:
    global MEMCORE_ROOT, _model_binding_plan_builder
    if memcore_root is not None:
        MEMCORE_ROOT = str(memcore_root)
    if model_binding_plan_builder is not None:
        _model_binding_plan_builder = model_binding_plan_builder


def get_zhiyi_usage_log_contract() -> Dict[str, Any]:
    return {
        "ok": True,
        "contract": ZHIYI_USAGE_LOG_CONTRACT,
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "console_layer": "zhiyi_usage_log_observation",
        "derived_layer": "zhiyi",
        "not_raw_origin": True,
        "read_only_by_default": True,
        "write_capable": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "usage_log_write_performed": False,
        "authorization_required_for_write": True,
        "raw_origin_policy": "usage logs are observation receipts and never replace source raw records",
    }


def _build_model_binding_plan(body=None) -> dict[str, Any]:
    if _model_binding_plan_builder is not None:
        return _model_binding_plan_builder(body or {})
    try:
        from src.p6_zhiyi_model_runtime import build_zhiyi_model_binding_plan
    except Exception:
        from p6_zhiyi_model_runtime import build_zhiyi_model_binding_plan
    return build_zhiyi_model_binding_plan(body or {})


def build_zhiyi_usage_log_dry_run(body=None):
    """Build a user-facing Zhiyi usage log record without appending it."""
    body = body or {}
    query = str(body.get("query", "") or "").strip()
    scope_filter = str(body.get("scope_filter", "") or "").strip()
    trigger_type = str(body.get("trigger_type") or body.get("trigger") or "manual_preview")
    route = str(body.get("route") or "zhiyi_recall_preview")
    top_k = min(int(body.get("top_k", 5) or 5), 20)
    threshold = float(body.get("threshold", 0.5) or 0.5)
    model_id = str(body.get("model_id") or "")
    target_log_path = os.path.join(str(MEMCORE_ROOT), "logs", "zhiyi_usage.jsonl")

    model_plan = _build_model_binding_plan({"model_id": model_id})
    recall_result = body.get("recall_result")
    recall_error = ""
    recall_executed = False
    if not isinstance(recall_result, dict):
        recall_executed = True
        try:
            import sys as _sys
            _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from p3_recall import handle_recall
            recall_result = handle_recall({
                "query": query,
                "scope_filter": scope_filter,
                "top_k": top_k,
                "threshold": threshold,
            })
        except Exception as e:
            recall_result = {"matched_memories": [], "total_matched": 0, "returned": 0}
            recall_error = str(e)

    matched = recall_result.get("matched_memories", []) if isinstance(recall_result, dict) else []
    if not isinstance(matched, list):
        matched = []

    def parse_refs(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return json.loads(value)
            except Exception:
                return {"raw": value}
        return {}

    evidence_items = []
    injectable_count = 0
    for memory in matched[:5]:
        if not isinstance(memory, dict):
            continue
        refs = parse_refs(memory.get("source_refs", {}))
        if memory.get("should_inject"):
            injectable_count += 1
        exp_id = memory.get("exp_id", "") or memory.get("id", "")
        card = memory.get("archive_card") if isinstance(memory.get("archive_card"), dict) else archive_card(memory)
        catalog_id = memory.get("catalog_id", "") or card.get("catalog_id", "")
        library_card = memory.get("library_card") if isinstance(memory.get("library_card"), dict) else card.get("library_card", {})
        if not isinstance(library_card, dict):
            library_card = {}
        evidence_items.append({
            "catalog_id": catalog_id,
            "library_id": memory.get("library_id", "") or card.get("library_id", "") or library_card.get("library_id", ""),
            "library_shelf": memory.get("library_shelf", "") or card.get("library_shelf", "") or library_card.get("shelf", ""),
            "exp_id": exp_id,
            "type": memory.get("type") or memory.get("_type") or "",
            "title": card.get("title", ""),
            "status": card.get("status", ""),
            "evidence_level": card.get("evidence_level", ""),
            "matched_by": memory.get("matched_by", []) or library_card.get("matched_by", []),
            "rank_reason": memory.get("rank_reason", "") or library_card.get("rank_reason", ""),
            "library_card": library_card,
            "summary": memory.get("summary", "") or memory.get("detail", ""),
            "detail": memory.get("detail", ""),
            "injectable_context": memory.get("injectable_context", ""),
            "confidence": memory.get("confidence", 0),
            "should_inject": bool(memory.get("should_inject", False)),
            "source_refs": refs,
            "source_refs_count": len(refs) if isinstance(refs, list) else (1 if refs else 0),
            "raw_detail_endpoint": f"/api/v1/zhiyi/memories/{exp_id}" if exp_id else "",
        })

    if recall_error:
        result_status = "error"
    elif not matched:
        result_status = "no_match"
    elif injectable_count:
        result_status = "matched_ready"
    else:
        result_status = "matched_not_injectable"

    selected_option = model_plan.get("selected_option", {}) if isinstance(model_plan, dict) else {}
    prompt_bundle = build_zhiyi_usage_light_prompt({
        "outcome_status": result_status,
        "recall_error": recall_error,
        "matched_count": len(matched),
        "injectable_count": injectable_count,
        "model_binding_ok": bool(model_plan.get("ok")),
        "model_id": model_id,
        "runtime_binding_ready": bool(model_plan.get("runtime_binding_ready", False)),
        "model_called": False,
    })
    event = {
        "schema_version": "1.0",
        "event_type": "zhiyi_usage_record",
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "trigger": {
            "type": trigger_type,
            "query": query,
            "scope_filter": scope_filter,
            "route": route,
        },
        "outcome": {
            "status": result_status,
            "light_message": prompt_bundle["primary_prompt"]["message"],
            "light_prompt": prompt_bundle["primary_prompt"],
            "prompt_policy_version": prompt_bundle["policy_version"],
            "used_in_answer": False,
            "applied_to_platform": False,
            "dry_run_only": True,
        },
        "recall": {
            "executed": recall_executed,
            "total_matched": recall_result.get("total_matched", 0) if isinstance(recall_result, dict) else 0,
            "returned": recall_result.get("returned", len(matched)) if isinstance(recall_result, dict) else 0,
            "matched_memories_count": len(matched),
            "injectable_count": injectable_count,
            "evidence_items": evidence_items,
            "used_library_ids": [
                item.get("library_id", "")
                for item in evidence_items
                if item.get("library_id")
            ],
            "used_source_refs": [
                item.get("source_refs", {})
                for item in evidence_items
                if item.get("source_refs")
            ],
            "explainability": {
                "enabled": True,
                "matched_by_available": True,
                "rank_reason_available": True,
                "write_performed": False,
            },
            "error": recall_error,
        },
        "model_call": {
            "requested_option_id": model_id,
            "binding_plan_ok": bool(model_plan.get("ok")),
            "provider": selected_option.get("provider", ""),
            "provider_id": selected_option.get("provider_id", ""),
            "model_name": selected_option.get("model_name", ""),
            "runtime_binding_ready": bool(model_plan.get("runtime_binding_ready", False)),
            "runtime_binding_status": model_plan.get("runtime_binding_status", ""),
            "called": False,
            "not_called_reason": "runtime_binding_not_applied",
            "light_prompt": prompt_bundle["model_prompt"],
        },
        "source_refs_policy": {
            "usage_log_contains_source_refs": True,
            "raw_detail_endpoint_available": True,
            "saved_user_content_preserved": True,
            "hash_only_replacement_allowed": False,
            "redaction_performed": False,
        },
    }
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "target_log_path": target_log_path,
        "event": event,
        "would_append_event": event,
        "model_binding_plan": {
            "ok": model_plan.get("ok"),
            "model_id": model_plan.get("model_id"),
            "runtime_binding_ready": model_plan.get("runtime_binding_ready"),
            "runtime_binding_status": model_plan.get("runtime_binding_status"),
            "write_performed": model_plan.get("write_performed"),
            "error": model_plan.get("error", ""),
        },
        "notes": [
            "usage_log_dry_run_only",
            "browser_or_api_preview_does_not_append_logs",
            "model_call_not_executed_until_runtime_binding",
        ],
    }


def get_zhiyi_usage_light_prompt_policy():
    """Return the first-version light prompt taxonomy for Zhiyi usage events."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "policy_version": ZHIYI_USAGE_LIGHT_PROMPT_POLICY_VERSION,
        "principles": [
            "answer_flow_first",
            "no_engineering_error_dump_to_user",
            "log_detail_for_later_review",
            "do_not_write_raw_text_into_usage_log",
        ],
        "outcome_prompts": {
            "matched_ready": {
                "category": "success_silent",
                "severity": "info",
                "display_mode": "log_only",
                "message": "已找到可用经验，等待接入回答链路。",
                "can_continue": True,
                "next_action": "continue_answer_flow",
            },
            "matched_not_injectable": {
                "category": "soft_blocked",
                "severity": "notice",
                "display_mode": "quiet_note",
                "message": "找到了经验，但当前还不能接入回答。",
                "can_continue": True,
                "next_action": "continue_without_injection",
            },
            "no_match": {
                "category": "no_memory",
                "severity": "notice",
                "display_mode": "quiet_note",
                "message": "这次没找到可用经验，我会先按当前对话继续。",
                "can_continue": True,
                "next_action": "continue_without_memory",
            },
            "error": {
                "category": "recall_unavailable",
                "severity": "warn",
                "display_mode": "quiet_note",
                "message": "本地记忆链路暂时没接上，我会先按当前对话继续。",
                "can_continue": True,
                "next_action": "continue_and_log_error_for_review",
            },
        },
        "model_prompts": {
            "model_option_hidden": {
                "category": "model_option_hidden",
                "severity": "notice",
                "display_mode": "settings_note",
                "message": "当前模型不属于第一版知意可选项，本次不会调用它。",
                "can_continue": True,
                "next_action": "use_visible_model_option_or_platform_default",
            },
            "runtime_binding_not_applied": {
                "category": "model_runtime_not_applied",
                "severity": "notice",
                "display_mode": "log_only",
                "message": "模型选择还没接入运行链路，本次只记录未调用模型。",
                "can_continue": True,
                "next_action": "wait_for_runtime_adapter",
            },
            "model_called": {
                "category": "model_called",
                "severity": "info",
                "display_mode": "log_only",
                "message": "模型调用已记录。",
                "can_continue": True,
                "next_action": "record_model_call",
            },
        },
        "completion_claim": {
            "first_version_usage_log_done": False,
            "production_prompting_done": False,
            "live_9850_updated": False,
        },
    }


def build_zhiyi_usage_light_prompt(body=None):
    """Classify user-facing light prompts without writing logs or raw data."""
    body = body or {}
    policy = get_zhiyi_usage_light_prompt_policy()
    outcome_status = str(body.get("outcome_status") or body.get("status") or "no_match")
    outcome_prompts = policy["outcome_prompts"]
    primary = dict(outcome_prompts.get(outcome_status) or outcome_prompts["no_match"])
    primary["status"] = outcome_status

    model_called = bool(body.get("model_called", False))
    model_binding_ok = bool(body.get("model_binding_ok", True))
    runtime_ready = bool(body.get("runtime_binding_ready", False))
    if model_called:
        model_key = "model_called"
    elif not model_binding_ok:
        model_key = "model_option_hidden"
    elif not runtime_ready:
        model_key = "runtime_binding_not_applied"
    else:
        model_key = "runtime_binding_not_applied"
    model_prompt = dict(policy["model_prompts"][model_key])
    model_prompt["reason"] = model_key
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "policy_version": policy["policy_version"],
        "primary_prompt": primary,
        "model_prompt": model_prompt,
        "inputs": {
            "outcome_status": outcome_status,
            "recall_error_present": bool(body.get("recall_error")),
            "matched_count": int(body.get("matched_count", 0) or 0),
            "injectable_count": int(body.get("injectable_count", 0) or 0),
            "model_id": str(body.get("model_id", "") or ""),
            "model_binding_ok": model_binding_ok,
            "runtime_binding_ready": runtime_ready,
            "model_called": model_called,
        },
        "completion_claim": policy["completion_claim"],
        "notes": [
            "light_prompt_taxonomy_only",
            "do_not_interrupt_answer_flow_by_default",
            "saved_user_content_preserved",
        ],
    }


def _zhiyi_usage_log_path():
    return os.path.join(str(MEMCORE_ROOT), "logs", "zhiyi_usage.jsonl")


def _usage_log_positive_int(value, default, maximum):
    try:
        number = int(value)
    except Exception:
        return default
    if number < 1:
        return default
    return min(number, maximum)


def get_zhiyi_usage_log_apply_gate_policy():
    """Return the no-write authorization gate for future usage log appends."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "policy_version": ZHIYI_USAGE_LOG_APPLY_GATE_VERSION,
        "dry_run_endpoint": "/api/v1/zhiyi/usage-log/apply-gate/dry-run",
        "future_apply_endpoint": "/api/v1/zhiyi/usage-log/apply",
        "live_apply_endpoint_enabled": False,
        "required_authorization": [
            "confirm_write_usage_log",
            "confirm_single_jsonl_append",
            "confirm_preserve_saved_user_content",
            "operator",
            "reason",
        ],
        "guards": [
            "event_type_must_be_zhiyi_usage_record",
            "schema_version_must_be_1_0",
            "target_must_be_memcore_logs_zhiyi_usage_jsonl",
            "append_line_must_be_valid_json",
            "saved_user_content_must_not_be_replaced_by_hash_or_stars",
        ],
        "append_contract": {
            "format": "jsonl",
            "encoding": "utf-8",
            "open_mode": "append",
            "newline_terminated": True,
            "file_mode_after_create": "0600",
        },
        "completion_claim": {
            "production_append_endpoint_done": False,
            "live_9850_updated": False,
            "usage_log_history_done": False,
        },
    }


def build_zhiyi_usage_log_apply_gate_dry_run(body=None):
    """Check whether a future usage-log append has enough authorization.

    This endpoint never appends the log. It only explains why an append is still
    blocked or whether the supplied event would be ready for a later authorized
    production endpoint.
    """
    body = body or {}
    supplied_event = body.get("event")
    persist_body = {"event": supplied_event} if isinstance(supplied_event, dict) else body
    persist_plan = build_zhiyi_usage_log_persist_dry_run(persist_body)
    event = persist_plan.get("would_append_event", {})
    append = persist_plan.get("append_contract", {})
    target_log_path = persist_plan.get("target_log_path") or _zhiyi_usage_log_path()
    raw_policy = persist_plan.get("source_refs_policy", {})
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        value = authorization.get(name, body.get(name))
        if value is True:
            return True
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "confirmed", "confirm")
        return False

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    required_checks = {
        "confirm_write_usage_log": confirmed("confirm_write_usage_log"),
        "confirm_single_jsonl_append": confirmed("confirm_single_jsonl_append"),
        "confirm_preserve_saved_user_content": confirmed("confirm_preserve_saved_user_content"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    event_type_ok = isinstance(event, dict) and event.get("event_type") == "zhiyi_usage_record"
    schema_version_ok = isinstance(event, dict) and str(event.get("schema_version", "")) == "1.0"
    try:
        parsed_append = json.loads(str(append.get("append_line", "")))
        append_line_valid_json = isinstance(parsed_append, dict)
    except Exception:
        append_line_valid_json = False
    expected_target = os.path.abspath(_zhiyi_usage_log_path())
    actual_target = os.path.abspath(str(target_log_path))
    target_ok = actual_target == expected_target
    saved_content_preserved = bool(raw_policy.get("saved_user_content_preserved", True))
    hash_only_replacement_blocked = bool(raw_policy.get("hash_only_replacement_allowed", False)) is False
    redaction_not_performed = bool(raw_policy.get("redaction_performed", False)) is False

    guard_checks = {
        "event_type": event_type_ok,
        "schema_version": schema_version_ok,
        "target_log_path": target_ok,
        "append_line_json": append_line_valid_json,
        "saved_user_content_preserved": saved_content_preserved,
        "hash_only_replacement_blocked": hash_only_replacement_blocked,
        "redaction_not_performed": redaction_not_performed,
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    authorization_complete = not missing
    future_authorized_append_ready = authorization_complete and not guard_failures
    if guard_failures:
        gate_status = "blocked_guard_failure"
    elif not authorization_complete:
        gate_status = "blocked_missing_authorization"
    else:
        gate_status = "ready_for_future_authorized_append"

    result = dict(persist_plan)
    result.update({
        "ok": not guard_failures,
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "apply_performed": False,
        "append_performed": False,
        "apply_allowed": False,
        "future_authorized_append_ready": future_authorized_append_ready,
        "live_apply_endpoint_enabled": False,
        "policy_version": ZHIYI_USAGE_LOG_APPLY_GATE_VERSION,
        "gate_status": gate_status,
        "authorization_complete": authorization_complete,
        "authorization_missing": missing,
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "guard_failures": guard_failures,
        "required_authorization": get_zhiyi_usage_log_apply_gate_policy()["required_authorization"],
        "future_apply_endpoint": "/api/v1/zhiyi/usage-log/apply",
        "dry_run_endpoint": "/api/v1/zhiyi/usage-log/apply-gate/dry-run",
        "notes": [
            "apply_gate_dry_run_only",
            "no_log_file_created_or_appended",
            "future_live_append_endpoint_not_enabled",
            "saved_user_content_remains_verbatim_in_usage_log",
        ],
    })
    return result


def build_zhiyi_usage_log_persist_dry_run(body=None):
    """Build the append artifact for a Zhiyi usage log record without writing it."""
    body = body or {}
    supplied_event = body.get("event")
    if isinstance(supplied_event, dict) and supplied_event.get("event_type") == "zhiyi_usage_record":
        event = supplied_event
        draft = {
            "ok": True,
            "dry_run": True,
            "event": event,
            "model_binding_plan": {},
        }
    else:
        draft = build_zhiyi_usage_log_dry_run(body)
        event = draft.get("event", {})

    target_log_path = _zhiyi_usage_log_path()
    parent_dir = os.path.dirname(target_log_path)
    append_line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    append_bytes = len((append_line + "\n").encode("utf-8"))
    raw_policy = event.get("source_refs_policy", {}) if isinstance(event, dict) else {}
    return {
        "ok": bool(draft.get("ok", True)),
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "target_log_path": target_log_path,
        "target_log_exists": os.path.exists(target_log_path),
        "target_parent_dir": parent_dir,
        "target_parent_exists": os.path.isdir(parent_dir),
        "would_create_parent_dir": not os.path.isdir(parent_dir),
        "would_append_event": event,
        "append_contract": {
            "schema_version": "1.0",
            "format": "jsonl",
            "encoding": "utf-8",
            "open_mode": "append",
            "newline_terminated": True,
            "file_mode_after_create": "0600",
            "append_bytes": append_bytes,
            "append_line": append_line,
            "append_requires_authorization": True,
        },
        "query_api_plan": {
            "endpoint": "/api/v1/zhiyi/usage-log/query/dry-run",
            "method": "GET",
            "default_order": "newest_first",
            "supports": ["page", "page_size", "status", "query"],
            "write_performed": False,
        },
        "source_refs_policy": {
            "usage_log_contains_source_refs": bool(raw_policy.get("usage_log_contains_source_refs", True)),
            "raw_detail_endpoint_available": bool(raw_policy.get("raw_detail_endpoint_available", True)),
            "saved_user_content_preserved": bool(raw_policy.get("saved_user_content_preserved", True)),
            "hash_only_replacement_allowed": bool(raw_policy.get("hash_only_replacement_allowed", False)),
            "redaction_performed": bool(raw_policy.get("redaction_performed", False)),
        },
        "model_binding_plan": draft.get("model_binding_plan", {}),
        "notes": [
            "persistence_artifact_only",
            "no_log_file_created_or_appended",
            "apply_requires_later_authorization",
        ],
    }


def query_zhiyi_usage_log_dry_run(params=None):
    """Read the planned Zhiyi usage log shape without mutating state."""
    params = params or {}
    page = _usage_log_positive_int(params.get("page", 1), 1, 1000000)
    page_size = _usage_log_positive_int(params.get("page_size", 20), 20, 100)
    status_filter = str(params.get("status", "") or "").strip()
    query_filter = str(params.get("query", "") or "").strip().lower()
    target_log_path = _zhiyi_usage_log_path()
    target_exists = os.path.exists(target_log_path)
    entries = []
    parse_errors = 0
    if target_exists:
        try:
            with open(target_log_path, encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, 1):
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        item = json.loads(text)
                    except Exception:
                        parse_errors += 1
                        continue
                    if not isinstance(item, dict) or item.get("event_type") != "zhiyi_usage_record":
                        parse_errors += 1
                        continue
                    item["_line_no"] = line_no
                    entries.append(item)
        except Exception:
            parse_errors += 1

    entries.sort(key=lambda item: item.get("ts", ""), reverse=True)
    filtered = []
    for item in entries:
        outcome = item.get("outcome", {}) if isinstance(item.get("outcome"), dict) else {}
        trigger = item.get("trigger", {}) if isinstance(item.get("trigger"), dict) else {}
        if status_filter and outcome.get("status") != status_filter:
            continue
        if query_filter and query_filter not in str(trigger.get("query", "")).lower():
            continue
        filtered.append(item)

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "usage_log_write_performed": False,
        "target_log_path": target_log_path,
        "target_log_exists": target_exists,
        "read_performed": target_exists,
        "read_only": True,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "items": filtered[start:end],
        "parse_errors": parse_errors,
        "filters": {
            "status": status_filter,
            "query": query_filter,
        },
        "empty_reason": "" if target_exists else "usage_log_not_created",
        "query_contract": {
            "schema_version": "1.0",
            "source": "logs/zhiyi_usage.jsonl",
            "order": "newest_first",
            "raw_text_expected_in_items": False,
        },
        "notes": [
            "query_dry_run_read_only",
            "missing_log_is_not_failure_before_persistence_apply",
        ],
    }



__all__ = [
    "ZHIYI_USAGE_LOG_CONTRACT",
    "ZHIYI_USAGE_LIGHT_PROMPT_POLICY_VERSION",
    "ZHIYI_USAGE_LOG_APPLY_GATE_VERSION",
    "configure_zhiyi_usage_log",
    "get_zhiyi_usage_log_contract",
    "build_zhiyi_usage_log_dry_run",
    "get_zhiyi_usage_light_prompt_policy",
    "build_zhiyi_usage_light_prompt",
    "_zhiyi_usage_log_path",
    "_usage_log_positive_int",
    "get_zhiyi_usage_log_apply_gate_policy",
    "build_zhiyi_usage_log_apply_gate_dry_run",
    "build_zhiyi_usage_log_persist_dry_run",
    "query_zhiyi_usage_log_dry_run",
]
