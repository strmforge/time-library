#!/usr/bin/env python3
"""Productized local proof loops for Time Library.

This module is intentionally only an aggregator. It does not create a new
memory layer; it makes the existing library/doctor/preflight/benchmark/receipt
and experience-governance paths visible in one read-only payload.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from src.memcore_version import SERVICE_VERSION as PRODUCTIZED_LOOPS_VERSION
    from src.agent_work_preflight import build_agent_work_preflight
    from src.hermes_skill_experience_diff import build_hermes_skill_experience_diff_dry_run
    from src.p6_experience_hermes_feedback import (
        configure_experience_hermes_feedback,
        query_hermes_consumption_receipts,
    )
    from src.p6_zhiyi_usage_log import configure_zhiyi_usage_log, query_zhiyi_usage_log_dry_run
    from src.platform_thin_adapter_registry import build_authorized_auto_connect_dry_run
    from src.record_chain_doctor import build_record_doctor
    from src.zhixing_library import (
        attach_library_card,
        build_experience_apply_package_dry_run,
        build_experience_apply_receipt_schema_dry_run,
        build_experience_evolution_candidates_dry_run,
        build_experience_flow_overview_dry_run,
        build_experience_review_actions_dry_run,
        build_experience_review_apply_gate_dry_run,
        build_experience_review_queue_dry_run,
        build_experience_validation_receipt_schema_dry_run,
        build_experience_validation_report_dry_run,
        run_benchmark_dry_run,
        run_replay_dry_run,
    )
except Exception:  # pragma: no cover - direct script import fallback
    from memcore_version import SERVICE_VERSION as PRODUCTIZED_LOOPS_VERSION
    from agent_work_preflight import build_agent_work_preflight
    from hermes_skill_experience_diff import build_hermes_skill_experience_diff_dry_run
    from p6_experience_hermes_feedback import (
        configure_experience_hermes_feedback,
        query_hermes_consumption_receipts,
    )
    from p6_zhiyi_usage_log import configure_zhiyi_usage_log, query_zhiyi_usage_log_dry_run
    from platform_thin_adapter_registry import build_authorized_auto_connect_dry_run
    from record_chain_doctor import build_record_doctor
    from zhixing_library import (
        attach_library_card,
        build_experience_apply_package_dry_run,
        build_experience_apply_receipt_schema_dry_run,
        build_experience_evolution_candidates_dry_run,
        build_experience_flow_overview_dry_run,
        build_experience_review_actions_dry_run,
        build_experience_review_apply_gate_dry_run,
        build_experience_review_queue_dry_run,
        build_experience_validation_receipt_schema_dry_run,
        build_experience_validation_report_dry_run,
        run_benchmark_dry_run,
        run_replay_dry_run,
    )


PRODUCTIZED_LOOPS_CONTRACT = "productized_loops_doctor.v2026.6.20"
BORROWING_RECEIPTS_CONTRACT = "productized_borrowing_receipts_view.v2026.6.20"
EXPERIENCE_EVOLUTION_DEMO_CONTRACT = "productized_experience_evolution_demo.v2026.6.20"

LOOP_IDS = [
    "connect_doctor",
    "hot_path_preflight",
    "recall_experience_benchmark",
    "borrowing_receipts",
    "experience_evolution_demo",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int(value: Any, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(1, min(parsed, maximum))


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _write_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "model_call_performed": False,
    }


def _contract_id(payload: dict[str, Any]) -> str:
    contract = payload.get("contract")
    if isinstance(contract, str):
        return contract
    if isinstance(contract, dict):
        return str(contract.get("contract") or contract.get("source") or "inline_contract")
    return ""


def _configure_runtime_root(memcore_root: str | Path | None) -> str:
    root = str(memcore_root or "").strip()
    if not root:
        return ""
    try:
        configure_zhiyi_usage_log(root)
    except Exception:
        pass
    try:
        configure_experience_hermes_feedback(root)
    except Exception:
        pass
    return root


def _benchmark_case(records: list[dict[str, Any]]) -> dict[str, Any]:
    cards = [
        attached.get("library_card", {})
        for record in records
        if isinstance((attached := attach_library_card(record)), dict)
    ]
    library_ids = [str(card.get("library_id") or "") for card in cards if card.get("library_id")]
    source_paths = [
        str((card.get("source_refs") or {}).get("source_path") or "")
        for card in cards
        if isinstance(card.get("source_refs"), dict) and (card.get("source_refs") or {}).get("source_path")
    ]
    return {
        "case_id": "productized-loops-provided-records" if records else "productized-loops-no-records",
        "query": "Check available source-backed memory before changing recall.",
        "expected_source_refs": source_paths,
        "expected_library_ids": library_ids,
        "expected_behavior_markers": [],
        "forbidden_repeated_mistakes": [],
        "required_acceptance_checks": [],
        "expected_proactive_resurfacing": [],
        "records": records,
    }


def _sample_preflight_payload(query: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    surfaces = []
    for record in records:
        card = attach_library_card(record, query=query).get("library_card", {})
        if not isinstance(card, dict):
            continue
        surfaces.append({
            "library_id": card.get("library_id", ""),
            "library_shelf": card.get("shelf", ""),
            "title": card.get("title", ""),
            "summary": record.get("summary", ""),
            "rank_reason": card.get("rank_reason", ""),
            "matched_by": card.get("matched_by", []),
            "source_system": (card.get("source_refs") or {}).get("source_system", ""),
            "source_path": (card.get("source_refs") or {}).get("source_path", ""),
            "session_id": (card.get("source_refs") or {}).get("session_id", ""),
            "raw_evidence_status": "raw_index",
            "score": 90 if card.get("shelf") == "xingce" else 70,
        })
    return {
        "ok": True,
        "mode": "preflight",
        "contract": "zhixing_preflight.v2026.6.20",
        "consumer": "productized-loops",
        "query": query,
        "decision": "surface",
        "prompt_class": "task",
        "auto_entry_state": "enter",
        "recall_status": "preflight_surface_required",
        "should_surface": True,
        "memory_scope": "window",
        "active_layers_used": ["current_window", "project"],
        "must_surface": surfaces,
        "reason": "matched already built source-backed Zhiyi/Xingce evidence should be surfaced before answering",
        "do_not_repeat": ["do not create a sixth knowledge layer"],
        "acceptance_checks": ["productized loops doctor passed"],
        "source_refs_count": len([item for item in surfaces if item.get("source_path")]),
        "raw_items_count": len(surfaces),
        "consumer_receipt": {
            "consumer": "productized-loops",
            "receipt_scope": "zhixing_preflight_read_only",
            "read_only": True,
            "write_performed": False,
            "used_library_ids": [item["library_id"] for item in surfaces if item.get("library_id")],
        },
    }


def build_connect_doctor_dry_run(
    body: dict[str, Any] | None = None,
    *,
    home: str | Path | None = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    limit = _int(body.get("record_limit") or body.get("limit"), 10, 100)
    include_generic = _bool(body.get("include_generic"), False)
    skip_platform_scan = _bool(body.get("skip_platform_scan"), False)
    if skip_platform_scan:
        auto_connect = {
            "ok": True,
            "contract": "authorized_auto_connect_dry_run.v1",
            "read_only": True,
            "dry_run": True,
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "scan_mode": "skipped_by_request",
            "plan_count": 0,
            "plans": [],
        }
    else:
        auto_connect = build_authorized_auto_connect_dry_run(
            home=Path(home).expanduser() if home else None,
            include_generic=include_generic,
        )
    record_doctor = build_record_doctor(limit=limit, scan_mode="fast", public=True)
    statuses = {
        "auto_connect_plan_count": int(auto_connect.get("plan_count") or 0),
        "record_doctor_status": record_doctor.get("doctor_status", ""),
        "detected_connectable": sum(
            1
            for plan in _items(auto_connect.get("plans"))
            if plan.get("status") in {"ready_for_capability_check", "auto_connect_ready"}
        ),
    }
    return {
        "ok": True,
        "loop_id": "connect_doctor",
        "contract": "productized_connect_doctor.v2026.6.20",
        **_write_boundary(),
        "classification": "already_built_but_not_productized_together",
        "auto_connect": auto_connect,
        "record_doctor": record_doctor,
        "statuses": statuses,
        "attention": {
            "auto_connect_ok": bool(auto_connect.get("ok")),
            "record_doctor_ok": bool(record_doctor.get("ok", True)),
            "record_doctor_status": record_doctor.get("doctor_status", ""),
        },
        "next_action": "connect_or_fix_detected_agent_wiring_before_claiming_memory_empty",
    }


def build_borrowing_receipts_view_dry_run(
    body: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
    demo_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    _configure_runtime_root(memcore_root)
    limit = _int(body.get("limit"), 10, 50)
    records = demo_records if isinstance(demo_records, list) else _items(body.get("records"))
    demo_items = []
    used_library_ids = []
    used_source_refs = []
    for rank, record in enumerate(records, start=1):
        card = attach_library_card(record).get("library_card", {})
        if not isinstance(card, dict):
            continue
        source_refs = card.get("source_refs") if isinstance(card.get("source_refs"), dict) else {}
        library_id = str(card.get("library_id") or "")
        if library_id:
            used_library_ids.append(library_id)
        if source_refs:
            used_source_refs.append(source_refs)
        demo_items.append({
            "rank": rank,
            "library_id": library_id,
            "library_shelf": card.get("shelf", ""),
            "title": card.get("title", ""),
            "rank_reason": card.get("rank_reason", ""),
            "matched_by": card.get("matched_by", []),
            "source_refs": source_refs,
            "raw_evidence_status": "raw_index" if source_refs else "source_missing",
            "raw_excerpt_available": bool(card.get("verbatim_excerpt")),
            "verbatim_excerpt": card.get("verbatim_excerpt", ""),
            "consumer": body.get("consumer") or "productized-loops",
            "receipt_scope": "borrowing_receipt_demo_read_only",
            "write_performed": False,
        })
    zhiyi_usage = query_zhiyi_usage_log_dry_run({"page_size": limit})
    hermes_receipts = query_hermes_consumption_receipts({"limit": limit})
    return {
        "ok": True,
        "loop_id": "borrowing_receipts",
        "contract": BORROWING_RECEIPTS_CONTRACT,
        **_write_boundary(),
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "receipt_sources": [
            "zhiyi_usage_log_query",
            "hermes_consumption_receipts",
            "provided_record_receipts",
        ],
        "demo_receipts": demo_items,
        "demo_receipt_count": len(demo_items),
        "zhiyi_usage_log": {
            "ok": zhiyi_usage.get("ok"),
            "target_log_exists": zhiyi_usage.get("target_log_exists", False),
            "total": zhiyi_usage.get("total", 0),
            "items": zhiyi_usage.get("items", []),
            "read_only": zhiyi_usage.get("read_only", True),
            "write_performed": zhiyi_usage.get("write_performed", False),
        },
        "hermes_consumption": {
            "ok": hermes_receipts.get("ok"),
            "receipts_dir_exists": hermes_receipts.get("receipts_dir_exists", False),
            "count": hermes_receipts.get("count", 0),
            "latest": hermes_receipts.get("latest", {}),
            "items": hermes_receipts.get("items", []),
            "read_only": hermes_receipts.get("read_only", True),
            "write_performed": hermes_receipts.get("write_performed", False),
        },
        "consumer_receipt": {
            "consumer": body.get("consumer") or "productized-loops",
            "request_id": str(body.get("request_id") or ""),
            "consumed_at": _now(),
            "receipt_scope": "productized_borrowing_receipts_read_only",
            "read_only": True,
            "write_performed": False,
            "used_library_ids": used_library_ids,
            "used_source_refs": used_source_refs,
            "source_refs_count": len(used_source_refs),
        },
        "notes": [
            "borrowing_receipts_show_what_the_agent_used",
            "missing_history_is_not_failure_before_receipts_exist",
            "provided_items_require_source_backed_library_cards",
        ],
    }


def build_experience_evolution_demo_dry_run(
    body: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    records = _items(body.get("records"))
    case = _dict(body.get("case")) or _benchmark_case(records)
    if records:
        replay = run_replay_dry_run({"case": case, "records": records})
    else:
        replay = {
            "ok": True,
            **_write_boundary(),
            "status": "not_measured_no_records",
            "case_id": case.get("case_id", ""),
            "records_count": 0,
            "feedback_candidates": {
                "candidate_count": 0,
                "candidate_types": [],
                "candidates": [],
            },
        }
    history = _dict(body.get("experience_history")) or {"histories": []}
    trust = _dict(body.get("trust_doctor")) or {
        "xingce_needs_validation": [],
        "attention": [],
        "experience_history": history,
    }
    evolution = build_experience_evolution_candidates_dry_run({
        "records": records,
        "trust_doctor": trust,
        "replay": replay,
        "experience_history": history,
    })
    candidates = _items(evolution.get("candidates"))
    actions = _items(body.get("actions"))
    review = build_experience_review_actions_dry_run({
        "experience_evolution": evolution if actions else {"candidates": []},
        "actions": actions,
    })
    validation_report = build_experience_validation_report_dry_run({
        "experience_review_actions": review,
        "records": records,
        "experience_history": history,
        "replay": replay,
    })
    validation_receipts = build_experience_validation_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": validation_report,
    })
    review_queue = build_experience_review_queue_dry_run({
        "experience_evolution": evolution,
        "experience_review_actions": review,
        "experience_validation_report": validation_report,
    })
    authorization = _dict(body.get("authorization"))
    apply_gate = build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
        "experience_validation_receipt_schema": validation_receipts,
        "authorization": authorization,
    })
    apply_receipts = build_experience_apply_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_review_apply_gate": apply_gate,
        "operator": str(body.get("operator") or "productized-loops"),
        "reason": str(body.get("reason") or "read-only preview without authorization"),
    })
    apply_package = build_experience_apply_package_dry_run({
        "experience_review_actions": review,
        "experience_validation_receipt_schema": validation_receipts,
        "experience_review_apply_gate": apply_gate,
        "experience_apply_receipt_schema": apply_receipts,
    })
    flow = build_experience_flow_overview_dry_run({
        "experience_evolution": evolution,
        "experience_review_actions": review,
        "experience_validation_report": validation_report,
        "experience_validation_receipt_schema": validation_receipts,
        "experience_review_queue": review_queue,
        "experience_review_apply_gate": apply_gate,
        "experience_apply_receipt_schema": apply_receipts,
        "experience_apply_package": apply_package,
    })
    hermes_diff = build_hermes_skill_experience_diff_dry_run({
        "skills": _items(body.get("skills")),
        "scan_installed_skills": False,
        "experiences": records,
    }, memcore_root=memcore_root)
    return {
        "ok": True,
        "loop_id": "experience_evolution_demo",
        "contract": EXPERIENCE_EVOLUTION_DEMO_CONTRACT,
        **_write_boundary(),
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "records": records,
        "replay": replay,
        "experience_evolution": evolution,
        "review_actions": review,
        "validation_report": validation_report,
        "validation_receipts": validation_receipts,
        "review_queue": review_queue,
        "apply_gate": apply_gate,
        "apply_receipts": apply_receipts,
        "apply_package": apply_package,
        "flow_overview": flow,
        "hermes_skill_experience_diff": hermes_diff,
        "summary": {
            "candidate_count": int(evolution.get("candidate_count") or 0),
            "review_action_count": int(review.get("action_count") or 0),
            "validation_report_passed": bool(validation_report.get("report_passed")),
            "apply_package_status": apply_package.get("package_status", ""),
            "ready_for_authorized_apply": bool(apply_package.get("ready_for_authorized_apply")),
            "hermes_upgrade_candidate_count": int(
                (_dict(hermes_diff.get("upgrade_candidates"))).get("candidate_count") or 0
            ),
        },
        "notes": [
            "experience_can_evolve_into_candidates",
            "adoption_stays_blocked_behind_authorized_apply",
            "hermes_skills_are_compared_before_becoming_cross_agent_experience",
        ],
    }


def build_productized_loops_doctor(
    body: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
    home: str | Path | None = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    root = _configure_runtime_root(memcore_root)
    query = str(body.get("query") or "start work by checking already built memory and experience mechanisms")
    records = _items(body.get("records"))
    connect = build_connect_doctor_dry_run(body, home=home)
    preflight = build_agent_work_preflight(
        query,
        preflight_payload=_dict(body.get("preflight_payload")) or _sample_preflight_payload(query, records),
        consumer=str(body.get("consumer") or "productized-loops"),
        request_id=str(body.get("request_id") or ""),
    )
    benchmark = run_benchmark_dry_run({"cases": [_benchmark_case(records)]})
    borrowing = build_borrowing_receipts_view_dry_run(
        body,
        memcore_root=root or memcore_root,
        demo_records=records,
    )
    evolution_demo = build_experience_evolution_demo_dry_run(
        {"records": records},
        memcore_root=root or memcore_root,
    )
    loops = {
        "connect_doctor": connect,
        "hot_path_preflight": preflight,
        "recall_experience_benchmark": benchmark,
        "borrowing_receipts": borrowing,
        "experience_evolution_demo": evolution_demo,
    }
    loop_statuses = {
        name: {
            "ok": bool(payload.get("ok", True)),
            "read_only": bool(payload.get("read_only", True)),
            "write_performed": bool(payload.get("write_performed", False)),
            "contract": _contract_id(payload),
        }
        for name, payload in loops.items()
    }
    return {
        "ok": all(item["ok"] for item in loop_statuses.values()),
        "contract": PRODUCTIZED_LOOPS_CONTRACT,
        "version": PRODUCTIZED_LOOPS_VERSION,
        "generated_at": _now(),
        **_write_boundary(),
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "loop_count": len(LOOP_IDS),
        "loop_ids": LOOP_IDS,
        "classification": "already_built_but_not_productized_together",
        "finding": "storage_is_strong; connection_intervention_and_visible_receipts_need_one_entrypoint",
        "evidence_status": "provided_records" if records else "no_records_not_measured",
        "summary": {
            "connect_doctor_plans": int(connect.get("auto_connect", {}).get("plan_count") or 0),
            "preflight_classification": preflight.get("classification", ""),
            "benchmark_best_mode": benchmark.get("summary", {}).get("best_mode", ""),
            "benchmark_xingce_signal_detected": bool(benchmark.get("summary", {}).get("xingce_signal_detected")),
            "borrowing_demo_receipts": int(borrowing.get("demo_receipt_count") or 0),
            "experience_candidate_count": int(
                evolution_demo.get("summary", {}).get("candidate_count") or 0
            ),
            "experience_apply_package_status": evolution_demo.get("summary", {}).get("apply_package_status", ""),
            "hermes_upgrade_candidate_count": int(
                evolution_demo.get("summary", {}).get("hermes_upgrade_candidate_count") or 0
            ),
        },
        "loop_statuses": loop_statuses,
        "loops": loops,
        "receipts": {
            "work_preflight": preflight.get("consumer_receipt", {}),
            "borrowing": borrowing.get("consumer_receipt", {}),
        },
        "notes": [
            "one_payload_for_connect_preflight_benchmark_receipts_and_experience_evolution",
            "all_sections_are_read_only_or_dry_run",
            "public_product_surface_should_show_features_not_internal_phase_codes",
        ],
    }


__all__ = [
    "BORROWING_RECEIPTS_CONTRACT",
    "EXPERIENCE_EVOLUTION_DEMO_CONTRACT",
    "PRODUCTIZED_LOOPS_CONTRACT",
    "PRODUCTIZED_LOOPS_VERSION",
    "build_borrowing_receipts_view_dry_run",
    "build_connect_doctor_dry_run",
    "build_experience_evolution_demo_dry_run",
    "build_productized_loops_doctor",
]
