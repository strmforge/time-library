#!/usr/bin/env python3
"""MCP runtime orchestration for raw_consumption_gateway.

This module keeps MCP initialize/tool dispatch, reading-area registry actions,
platform self-report receipts, and direct library_id borrowing outside the raw
HTTP recall gateway hot path. It is intentionally an orchestration layer; raw
recall, preflight, response budgeting, and Tiandao payload construction stay in
raw_consumption_gateway.
"""

from __future__ import annotations

import importlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

try:
    from src.p4_provider import DEFAULT_CATALOG_TARGET_TOKENS as P4_DEFAULT_CATALOG_TARGET_TOKENS
except Exception:
    try:
        from p4_provider import DEFAULT_CATALOG_TARGET_TOKENS as P4_DEFAULT_CATALOG_TARGET_TOKENS
    except Exception:
        P4_DEFAULT_CATALOG_TARGET_TOKENS = 1500
try:
    from src.raw_gateway_mcp import (
        MCP_PROTOCOL_VERSION,
        _mcp_request_id,
        mcp_error,
        mcp_success,
    )
except Exception:
    from raw_gateway_mcp import (
        MCP_PROTOCOL_VERSION,
        _mcp_request_id,
        mcp_error,
        mcp_success,
    )
try:
    from src.source_system_runtime_declarations import source_system_from_consumer_name
except Exception:
    from source_system_runtime_declarations import source_system_from_consumer_name

UTC = timezone.utc
MCP_SERVER_NAME = "time-library"
MCP_LEGACY_SERVER_NAMES = ("yifanchen-zhiyi",)
STARTUP_CATALOG_TARGET_TOKENS = P4_DEFAULT_CATALOG_TARGET_TOKENS
STARTUP_CATALOG_DELIVERY_RECEIPT_CONTRACT = "time_library_startup_catalog_delivery_receipt.v1"
PLATFORM_HANDSHAKE_RECEIPT_CONTRACT = "time_library_platform_handshake_receipt.v1"
PLATFORM_SELF_REPORT_QUESTIONS_CONTRACT = "time_library_platform_self_report_questions.v1"
PLATFORM_SELF_REPORT_RECEIPT_CONTRACT = "time_library_platform_self_report_receipt.v1"
READING_AREA_TOOL_ALLOWED_KEYS = {
    "action",
    "source_system",
    "platform_name",
    "consumer",
    "client_name",
    "client_version",
    "client_surface",
    "canonical_window_id",
    "session_id",
    "native_window_id",
    "title",
    "borrowing_card_id",
    "card_id",
    "reading_area",
    "declared_project_ids",
    "declared_series_ids",
    "declared_roles",
    "aliases",
    "record_type",
    "task_id",
    "task_name",
    "summary",
    "status",
    "role",
    "next_owner",
    "supersedes",
    "library_ids",
    "source_refs",
    "history_type",
    "nomination_id",
    "nominated_project",
    "nominated_series",
    "source_path",
    "reason",
    "confidence",
    "projects",
    "series",
    "limit",
    "statuses",
    "skill_surface_status",
    "config_write_authority",
    "proof_library_id",
    "request_id",
}


def _gateway():
    try:
        return importlib.import_module("src.raw_consumption_gateway")
    except Exception:
        return importlib.import_module("raw_consumption_gateway")


def _service_version() -> str:
    return str(getattr(_gateway(), "SERVICE_VERSION", ""))


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _truthy(value: Any) -> bool:
    return _gateway()._truthy(value)


def _records_db_path_for_gateway():
    return _gateway()._records_db_path_for_gateway()


def _consumer_receipt(*args, **kwargs):
    return _gateway()._consumer_receipt(*args, **kwargs)


def _is_raw_evidence_status(status: str) -> bool:
    return _gateway()._is_raw_evidence_status(status)


def _is_capability_check_request(args: Dict[str, Any]) -> bool:
    return _gateway()._is_capability_check_request(args)


def _is_preflight_request(args: Dict[str, Any]) -> bool:
    return _gateway()._is_preflight_request(args)


def _is_work_preflight_request(args: Dict[str, Any]) -> bool:
    return _gateway()._is_work_preflight_request(args)


def _preflight_kwargs_from_args(args: Dict[str, Any], *, consumer_default: str, limit_default: int, excerpt_default: int) -> Dict[str, Any]:
    return _gateway()._preflight_kwargs_from_args(
        args,
        consumer_default=consumer_default,
        limit_default=limit_default,
        excerpt_default=excerpt_default,
    )


def _work_preflight_from_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return _gateway()._work_preflight_from_kwargs(kwargs)


def capability_check_payload(*args, **kwargs):
    return _gateway().capability_check_payload(*args, **kwargs)


def preflight_payload(*args, **kwargs):
    return _gateway().preflight_payload(*args, **kwargs)


def query_raw_source_refs(*args, **kwargs):
    return _gateway().query_raw_source_refs(*args, **kwargs)


def compact_recall_payload(*args, **kwargs):
    return _gateway().compact_recall_payload(*args, **kwargs)


def _response_budget_mode(args: Dict[str, Any]) -> str:
    return _gateway()._response_budget_mode(args)


def _include_raw_excerpt(args: Dict[str, Any]) -> bool:
    return _gateway()._include_raw_excerpt(args)


def mcp_tools_payload() -> Dict[str, Any]:
    return _gateway().mcp_tools_payload()

def _library_id_from_args(args: Dict[str, Any]) -> str:
    pattern = r"(?:ZX|WB|PH)-[A-Z0-9]+(?:-[A-Z0-9]+)*"
    value = _clean_text(args.get("library_id"))
    if re.fullmatch(pattern, value.upper()):
        return value.upper()
    query = _clean_text(args.get("query") or args.get("q"))
    if re.fullmatch(pattern, query.upper()):
        return query.upper()
    return ""


def _catalog_card_item_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    card = result.get("card") if isinstance(result.get("card"), dict) else {}
    refs = result.get("source_refs") if isinstance(result.get("source_refs"), dict) else {}
    excerpt_ref = result.get("raw_source_excerpt_ref") if isinstance(result.get("raw_source_excerpt_ref"), dict) else {}
    source_path = _first_text(
        refs.get("resolved_source_path"),
        refs.get("source_path"),
        excerpt_ref.get("source_path"),
    )
    byte_offsets = refs.get("byte_offsets") if isinstance(refs.get("byte_offsets"), dict) else {}
    if not byte_offsets and isinstance(excerpt_ref.get("byte_offsets"), dict):
        byte_offsets = excerpt_ref.get("byte_offsets")
    raw_excerpt = _first_text(result.get("raw_source_excerpt"), result.get("verbatim_excerpt"))
    return {
        "library_id": result.get("library_id", ""),
        "library_shelf": result.get("shelf") or card.get("shelf", ""),
        "type": card.get("type", ""),
        "memory_type": card.get("type", ""),
        "summary": card.get("summary") or card.get("title") or "",
        "source_system": refs.get("source_system", ""),
        "computer_name": refs.get("computer_name") or refs.get("computer_id", ""),
        "canonical_window_id": refs.get("canonical_window_id", ""),
        "session_id": refs.get("session_id", ""),
        "project_id": refs.get("project_id", ""),
        "project_root": refs.get("project_root") or refs.get("workspace_root") or refs.get("cwd") or "",
        "source_path": source_path,
        "msg_ids": refs.get("msg_ids", []) or ([refs.get("message_id")] if refs.get("message_id") else []),
        "byte_offsets": byte_offsets,
        "artifact_type": refs.get("artifact_type") or card.get("artifact_type", ""),
        "raw_excerpt": raw_excerpt,
        "raw_evidence_status": "raw" if raw_excerpt else "not_raw",
        "zhiyi_experience_used_as_raw": False,
        "matched_by": ["library_id_exact"],
        "rank_reason": "library_id_exact_borrow",
    }


def _catalog_card_borrow_payload(
    library_id: str,
    *,
    consumer: str,
    request_id: str,
    project_id: str = "",
    series_id: str = "",
    reading_area_id: str = "",
) -> Dict[str, Any]:
    try:
        from src.p4_provider import fetch_catalog_card_by_library_id
    except Exception:
        from p4_provider import fetch_catalog_card_by_library_id

    result = fetch_catalog_card_by_library_id(
        library_id,
        records_db_path=str(_records_db_path_for_gateway()),
        reading_area_registry_path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", ""),
        include_raw_index=True,
        project_ids=[project_id] if project_id else None,
        series_ids=[series_id] if series_id else None,
        consumer=consumer,
        request_id=request_id,
        reading_area_id=reading_area_id,
        project_id=project_id,
        series_id=series_id,
    )
    item = _catalog_card_item_from_result(result) if result.get("ok") else {}
    items = [item] if item else []
    source_refs_count = 1 if item.get("source_path") else 0
    raw_items_count = 1 if _is_raw_evidence_status(item.get("raw_evidence_status", "")) else 0
    receipt = _consumer_receipt(
        consumer,
        request_id,
        len(items),
        source_refs_count,
        raw_items_count,
        items,
    )
    receipt["query_path"] = "/catalog-card"
    receipt["receipt_scope"] = "library_id_direct_borrow"
    return {
        "ok": bool(result.get("ok")),
        "mode": "library_card_borrow",
        "query": library_id,
        "library_id": library_id,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "recall_performed": False,
        "matched_count": len(items),
        "source_refs_count": source_refs_count,
        "raw_items_count": raw_items_count,
        "raw_excerpt_returned": bool(item.get("raw_excerpt")),
        "catalog_card": result,
        "items": items,
        "consumer_receipt": receipt,
        "response_budget": {
            "mode": "library_card_borrow",
            "items_returned": len(items),
            "items_available": len(items),
            "raw_excerpt_returned": bool(item.get("raw_excerpt")),
            "omitted_large_fields": [],
        },
        "error": result.get("error", ""),
    }

def _startup_catalog_inject_payload(target_tokens: int = STARTUP_CATALOG_TARGET_TOKENS) -> Dict[str, Any]:
    """Build passive startup catalog delivery for MCP initialize.

    This is the clean split startup path: it reuses the catalog/p4 candidate
    loader and stays silent when no clean catalog exists.
    """
    try:
        from src.p4_provider import build_catalog_inject_from_candidates
    except Exception:
        try:
            from p4_provider import build_catalog_inject_from_candidates
        except Exception as exc:
            return {
                "ok": False,
                "should_inject": False,
                "error": f"catalog_builder_unavailable:{type(exc).__name__}",
            }
    try:
        payload = build_catalog_inject_from_candidates(target_tokens=target_tokens)
    except Exception as exc:
        return {
            "ok": False,
            "should_inject": False,
            "error": f"catalog_build_failed:{type(exc).__name__}:{exc}",
        }
    if not isinstance(payload, dict) or not payload.get("ok") or not payload.get("should_inject"):
        return {
            "ok": False,
            "should_inject": False,
            "error": payload.get("error", "startup_catalog_empty") if isinstance(payload, dict) else "startup_catalog_empty",
            "catalog_entry_count": int(payload.get("catalog_entry_count") or 0) if isinstance(payload, dict) else 0,
        }
    receipt = {
        "ok": True,
        "contract": STARTUP_CATALOG_DELIVERY_RECEIPT_CONTRACT,
        "delivery_layer": "mcp_initialize_instructions",
        "server": MCP_SERVER_NAME,
        "passive_delivery": True,
        "consumer_invoked_tool": False,
        "consumer_called_catalog_endpoint": False,
        "new_window_startup_auto_injection": True,
        "received_by": "naked_mcp_consumer_initialize",
        "delivered_at": ts(),
        "catalog_entry_count": int(payload.get("catalog_entry_count") or 0),
        "catalog_token_count": int(payload.get("catalog_token_count") or 0),
        "inject_token_count": int(payload.get("inject_token_count") or 0),
        "system_prompt_token_count": int(payload.get("system_prompt_token_count") or payload.get("inject_token_count") or 0),
        "startup_instruction_mode": payload.get("startup_instruction_mode", ""),
        "flat_catalog_prompt_omitted": bool(payload.get("flat_catalog_prompt_omitted", False)),
        "instructions_char_count": int(payload.get("instructions_char_count") or 0),
        "instructions_byte_count": int(payload.get("instructions_byte_count") or 0),
        "startup_instructions_char_budget": int(payload.get("startup_instructions_char_budget") or 0),
        "reading_area_project_page_count": int(payload.get("reading_area_project_page_count") or 0),
        "reading_area_toc_token_count": int(payload.get("reading_area_toc_token_count") or 0),
        "reading_area_block_token_count": int(payload.get("reading_area_block_token_count") or 0),
        "reading_area_raw_index": payload.get("reading_area_raw_index", {}),
        "target_tokens": int(payload.get("target_tokens") or target_tokens),
        "contains_body_markers": bool(payload.get("contains_body_markers", False)),
        "reading_area_contains_body_markers": bool(payload.get("reading_area_contains_body_markers", False)),
        "no_window_binding_required": bool(payload.get("no_window_binding_required", True)),
        "library_id_pull_endpoint": "/catalog-card",
        "library_id_pull_available": True,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "body_pushed": False,
    }
    return {
        **payload,
        "startup_catalog_delivery_receipt": receipt,
    }


def _platform_from_client_name(name: str) -> str:
    lowered = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not lowered:
        return "unknown_mcp_client"
    platform = source_system_from_consumer_name(lowered)
    if platform:
        return platform
    return lowered[:80] or "unknown_mcp_client"


def _sanitize_client_info_field(value: Any, *, max_chars: int = 120) -> str:
    text = str(value or "")
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _platform_self_report_questions(inferred_platform: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": "platform_identity",
            "question": "Which host platform and client surface are you connecting from?",
            "expected_answer": "platform_name_and_client_surface",
            "required_before_registration": True,
        },
        {
            "id": "mcp_capability",
            "question": "Can this client call the Time Library MCP tools after initialize?",
            "expected_answer": "capability_check_result_only_no_memory_recall",
            "required_before_registration": True,
        },
        {
            "id": "skill_surface",
            "question": "Does this client expose a skill/custom-instruction surface for Time Library guidance?",
            "expected_answer": "skill_or_instruction_surface_status",
            "required_before_registration": True,
        },
        {
            "id": "config_write_authority",
            "question": "Is platform config writing explicitly authorized for this session?",
            "expected_answer": "explicit_authorization_status",
            "required_before_registration": True,
        },
        {
            "id": "declared_project_series",
            "question": "Which reading-area project and series does this window declare?",
            "expected_answer": "declared_project_ids_and_series_ids",
            "required_before_registration": True,
        },
        {
            "id": "post_connect_proof",
            "question": "After connect, can the client perform capability_check and one real recall without exposing chat body?",
            "expected_answer": "proof_receipts_after_connect",
            "required_before_registration": True,
        },
    ]


def _platform_self_report_policy(client_info_present: bool, inferred_platform: str) -> Dict[str, Any]:
    questions = _platform_self_report_questions(inferred_platform) if client_info_present else []
    return {
        "contract": PLATFORM_SELF_REPORT_QUESTIONS_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "question_source": "static_read_only_handshake_contract",
        "answers_expected_from": "connecting_platform_or_client_after_initialize",
        "answers_observed": False,
        "answers_verified": False,
        "question_count": len(questions),
        "no_user_prompt_performed": True,
        "registration_effect": "questions_do_not_register_without_capability_check_and_real_recall",
        "questions": questions,
        "blockers": ["self_report_answers_not_observed", "self_report_not_verified"] if questions else [],
    }


def _platform_handshake_receipt(params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    params = params if isinstance(params, dict) else {}
    client_info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
    client_name = _sanitize_client_info_field(client_info.get("name"))
    client_version = _sanitize_client_info_field(client_info.get("version"))
    client_info_present = bool(client_name or client_version)
    inferred_platform = _platform_from_client_name(client_name)
    self_report_policy = _platform_self_report_policy(client_info_present, inferred_platform)
    blockers = []
    if not client_info_present:
        blockers.append("clientInfo_missing_from_mcp_initialize")
    blockers.extend([
        "handshake_not_verified_beyond_client_info",
        "capability_check_not_performed",
        "real_recall_not_proven",
    ])
    blockers.extend(self_report_policy.get("blockers", []))
    return {
        "contract": PLATFORM_HANDSHAKE_RECEIPT_CONTRACT,
        "evidence_source": "mcp_initialize.params.clientInfo",
        "client_info_present": client_info_present,
        "client_name": client_name,
        "client_version": client_version,
        "inferred_platform": inferred_platform,
        "current_stage": "client_info_observed" if client_info_present else "client_info_missing",
        "lifecycle_order": [
            "discovered",
            "client_info_observed",
            "handshake_verified",
            "capability_check_proven",
            "real_recall_proven",
            "registered",
        ],
        "handshake_observed": client_info_present,
        "handshake_verified": False,
        "verification_level": "client_info_observed_only" if client_info_present else "none",
        "capability_check_performed": False,
        "real_recall_performed": False,
        "recall_proven": False,
        "registered": False,
        "registration_blockers": blockers,
        "next_actions": [
            "run_capability_check_after_connect",
            "run_real_recall_before_marking_registered",
        ],
        "read_only": True,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "chat_body_included": False,
        "raw_excerpt_included": False,
        "client_info_redaction_policy": "name_version_only",
        "client_info_sanitized": True,
        "self_report_policy": {
            key: value for key, value in self_report_policy.items() if key != "questions"
        },
        "platform_self_report_questions": self_report_policy["questions"],
        "self_report_answers_observed": False,
        "self_report_verified": False,
        "self_report_blockers": self_report_policy["blockers"],
    }


def build_mcp_initialize_result(params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": MCP_SERVER_NAME,
            "version": _service_version(),
            "legacyNames": MCP_LEGACY_SERVER_NAMES,
        },
        "platformHandshakeReceipt": _platform_handshake_receipt(params),
    }
    catalog = _startup_catalog_inject_payload()
    if catalog.get("ok") and catalog.get("should_inject") and catalog.get("system_prompt"):
        result["instructions"] = str(catalog.get("system_prompt") or "")
        result["startupCatalog"] = {
            "ok": True,
            "delivery": "passive_mcp_initialize_instructions",
            "catalog_entry_count": catalog.get("catalog_entry_count", 0),
            "catalog_token_count": catalog.get("catalog_token_count", 0),
            "inject_token_count": catalog.get("inject_token_count", 0),
            "system_prompt_token_count": catalog.get("system_prompt_token_count", catalog.get("inject_token_count", 0)),
            "startup_instruction_mode": catalog.get("startup_instruction_mode", ""),
            "flat_catalog_prompt_omitted": catalog.get("flat_catalog_prompt_omitted", False),
            "instructions_char_count": catalog.get("instructions_char_count", 0),
            "instructions_byte_count": catalog.get("instructions_byte_count", 0),
            "startup_instructions_char_budget": catalog.get("startup_instructions_char_budget", 0),
            "reading_area_project_page_count": catalog.get("reading_area_project_page_count", 0),
            "reading_area_toc_token_count": catalog.get("reading_area_toc_token_count", 0),
            "reading_area_block_token_count": catalog.get("reading_area_block_token_count", 0),
            "reading_area_raw_index": catalog.get("reading_area_raw_index", {}),
            "reading_area_contains_body_markers": catalog.get("reading_area_contains_body_markers", False),
            "target_tokens": catalog.get("target_tokens", STARTUP_CATALOG_TARGET_TOKENS),
            "contains_body_markers": catalog.get("contains_body_markers", False),
            "no_window_binding_required": catalog.get("no_window_binding_required", True),
            "catalog": catalog.get("catalog", []),
        }
        result["startupCatalogDeliveryReceipt"] = catalog.get("startup_catalog_delivery_receipt", {})
    return result


def _bounded_self_report_text(value: Any, *, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _self_report_list(value: Any) -> List[str]:
    raw = value if isinstance(value, list) else ([] if value in (None, "") else [value])
    seen: set[str] = set()
    result: List[str] = []
    for item in raw:
        original = re.sub(r"\s+", " ", str(item or "")).strip()
        if original and original not in seen:
            seen.add(original)
            result.append(original[:160])
    return result


def _import_reading_area_registry():
    try:
        from src import reading_area_registry as registry
    except Exception:
        import reading_area_registry as registry
    return registry


def _issue_reading_area_borrowing_card(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    client_name = _sanitize_client_info_field(args.get("client_name"))
    source_system = _bounded_self_report_text(
        args.get("source_system")
        or args.get("platform_name")
        or _platform_from_client_name(client_name)
        or args.get("consumer"),
        limit=120,
    ).lower().replace("-", "_")
    consumer = _bounded_self_report_text(args.get("consumer") or source_system, limit=120)
    result = registry.ensure_borrowing_card(
        source_system=source_system,
        consumer=consumer,
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        native_window_id=_bounded_self_report_text(args.get("native_window_id"), limit=200),
        title=_bounded_self_report_text(args.get("title") or client_name, limit=200),
        declared_by="mcp_platform_self_report",
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "reading_area_borrowing_card",
        "contract": "time_library_reading_area_borrowing_card_mcp.v1",
        "registry_write_performed": bool(result.get("ok")),
        "write_performed": bool(result.get("ok")),
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
    }


def _declare_reading_area_membership(args: Dict[str, Any], *, card_id: str = "") -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    selected_card_id = _bounded_self_report_text(card_id or args.get("borrowing_card_id") or args.get("card_id"), limit=220)
    result = registry.declare_membership(
        card_id=selected_card_id,
        reading_area=_bounded_self_report_text(args.get("reading_area"), limit=200),
        projects=_self_report_list(args.get("declared_project_ids") or args.get("projects")),
        series=_self_report_list(args.get("declared_series_ids") or args.get("series")),
        roles=_self_report_list(args.get("declared_roles") or args.get("roles")),
        aliases=_self_report_list(args.get("aliases")),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "reading_area_membership",
        "contract": "time_library_reading_area_membership_mcp.v1",
        "registry_write_performed": bool(result.get("ok")),
        "write_performed": bool(result.get("ok")),
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
        "technical_project_id_used_as_declared_identity": False,
    }


def _whiteboard_write_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.write_whiteboard_record(
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        source_system=_bounded_self_report_text(args.get("source_system"), limit=120),
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        consumer=_bounded_self_report_text(args.get("consumer"), limit=120),
        record_type=_bounded_self_report_text(args.get("record_type"), limit=60),
        task_id=_bounded_self_report_text(args.get("task_id"), limit=120),
        task_name=_bounded_self_report_text(args.get("task_name"), limit=120),
        summary=_bounded_self_report_text(args.get("summary"), limit=240),
        status=_bounded_self_report_text(args.get("status"), limit=60),
        role=_bounded_self_report_text(args.get("role"), limit=80),
        next_owner=_bounded_self_report_text(args.get("next_owner"), limit=120),
        supersedes=_self_report_list(args.get("supersedes")),
        library_ids=_self_report_list(args.get("library_ids")),
        source_refs=args.get("source_refs"),
        request_id=_bounded_self_report_text(args.get("request_id"), limit=160),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "whiteboard_write",
        "contract": "time_library_whiteboard_write_receipt.v1",
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
    }


def _whiteboard_list_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.list_whiteboard_records(
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        source_system=_bounded_self_report_text(args.get("source_system"), limit=120),
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        consumer=_bounded_self_report_text(args.get("consumer"), limit=120),
        reading_area_ids=_self_report_list(args.get("reading_area") or args.get("declared_reading_area_ids")),
        project_ids=_self_report_list(args.get("declared_project_ids") or args.get("projects")),
        series_ids=_self_report_list(args.get("declared_series_ids") or args.get("series")),
        statuses=_self_report_list(args.get("statuses")),
        limit=int(args.get("limit") or 20),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "whiteboard_list",
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
    }


def _project_history_write_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.write_project_history_record(
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        source_system=_bounded_self_report_text(args.get("source_system"), limit=120),
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        consumer=_bounded_self_report_text(args.get("consumer"), limit=120),
        history_type=_bounded_self_report_text(args.get("history_type"), limit=60),
        project_id=_bounded_self_report_text(args.get("project_id"), limit=160),
        title=_bounded_self_report_text(args.get("title"), limit=160),
        summary=_bounded_self_report_text(args.get("summary"), limit=500),
        source_refs=args.get("source_refs"),
        request_id=_bounded_self_report_text(args.get("request_id"), limit=160),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "project_history_write",
        "contract": "time_library_project_history_write_receipt.v1",
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
        "not_a_sixth_shelf": True,
    }


def _project_history_list_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.list_project_history_records(
        project_ids=_self_report_list(args.get("declared_project_ids") or args.get("projects") or args.get("project_id")),
        series_ids=_self_report_list(args.get("declared_series_ids") or args.get("series")),
        reading_area_ids=_self_report_list(args.get("reading_area") or args.get("declared_reading_area_ids")),
        statuses=_self_report_list(args.get("statuses")),
        limit=int(args.get("limit") or 20),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "project_history_list",
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
        "not_a_sixth_shelf": True,
    }


def _nomination_create_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.create_project_nomination(
        source_system=_bounded_self_report_text(args.get("source_system"), limit=120),
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        source_path=_bounded_self_report_text(args.get("source_path"), limit=1000),
        nominated_project=_bounded_self_report_text(args.get("nominated_project") or args.get("project_id"), limit=200),
        nominated_series=_bounded_self_report_text(args.get("nominated_series"), limit=200),
        reason=_bounded_self_report_text(args.get("reason"), limit=500),
        confidence=float(args.get("confidence") or 0.0),
        request_id=_bounded_self_report_text(args.get("request_id"), limit=160),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "nomination_create",
        "contract": "time_library_project_nomination_create_receipt.v1",
        "declared_membership_written": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
    }


def _nomination_list_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.list_project_nominations(
        statuses=_self_report_list(args.get("statuses")),
        project=_bounded_self_report_text(args.get("nominated_project") or args.get("project_id"), limit=200),
        limit=int(args.get("limit") or 50),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {**result, "mode": "nomination_list"}


def _claim_nomination_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.claim_project_nomination(
        nomination_id=_bounded_self_report_text(args.get("nomination_id"), limit=120),
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        reading_area=_bounded_self_report_text(args.get("reading_area"), limit=200),
        projects=_self_report_list(args.get("declared_project_ids") or args.get("projects")),
        series=_self_report_list(args.get("declared_series_ids") or args.get("series")),
        roles=_self_report_list(args.get("declared_roles") or args.get("roles")),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "claim_nomination",
        "contract": "time_library_project_nomination_claim_receipt.v1",
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "technical_project_id_used_as_declared_identity": False,
    }


def _reject_nomination_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.reject_project_nomination(
        nomination_id=_bounded_self_report_text(args.get("nomination_id"), limit=120),
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        reason=_bounded_self_report_text(args.get("reason"), limit=500),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "reject_nomination",
        "contract": "time_library_project_nomination_reject_receipt.v1",
        "declared_membership_written": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
    }


def _platform_self_report_connect_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    request_id = _bounded_self_report_text(args.get("request_id"), limit=160)
    consumer = _bounded_self_report_text(args.get("consumer") or args.get("source_system") or "mcp", limit=120)
    client_name = _sanitize_client_info_field(args.get("client_name"))
    client_version = _sanitize_client_info_field(args.get("client_version"))
    source_system = _bounded_self_report_text(
        args.get("source_system") or args.get("platform_name") or _platform_from_client_name(client_name) or consumer,
        limit=120,
    ).lower().replace("-", "_")
    capability = capability_check_payload(
        consumer=consumer or source_system,
        request_id=request_id,
        source="mcp_self_report_connect",
    )
    proof_library_id = _library_id_from_args({"library_id": args.get("proof_library_id")})
    answer_blockers: List[str] = []
    if not _bounded_self_report_text(args.get("source_system"), limit=120):
        answer_blockers.append("source_system_not_self_reported")
    if not (args.get("canonical_window_id") or args.get("session_id")):
        answer_blockers.append("window_identity_not_self_reported")
    if "config_write_authority" not in args:
        answer_blockers.append("config_write_authority_answer_missing")
    if not _bounded_self_report_text(args.get("skill_surface_status"), limit=160):
        answer_blockers.append("skill_surface_answer_missing")
    if not (
        _bounded_self_report_text(args.get("reading_area"), limit=200)
        or _self_report_list(args.get("declared_project_ids") or args.get("projects"))
        or _self_report_list(args.get("declared_series_ids") or args.get("series"))
    ):
        answer_blockers.append("declared_project_series_missing")
    proof = (
        _catalog_card_borrow_payload(
            proof_library_id,
            consumer=consumer or source_system,
            request_id=request_id,
        )
        if proof_library_id
        else {
            "ok": False,
            "mode": "library_card_borrow",
            "error": "proof_library_id_required",
            "raw_excerpt_returned": False,
        }
    )
    blockers: List[str] = list(answer_blockers)
    if not proof.get("ok") or not proof.get("raw_excerpt_returned"):
        blockers.append("real_recall_not_proven")
    if not capability.get("ok"):
        blockers.append("capability_check_failed")
    card: Dict[str, Any] = {
        "ok": False,
        "status": "not_attempted_until_self_report_and_recall_proof_pass",
        "registry_write_performed": False,
        "write_performed": False,
    }
    membership: Dict[str, Any] = {
        "ok": False,
        "status": "not_attempted_until_borrowing_card_issued",
        "registry_write_performed": False,
        "write_performed": False,
    }
    if not blockers:
        card = _issue_reading_area_borrowing_card({
            **args,
            "source_system": source_system,
            "consumer": consumer or source_system,
            "client_name": client_name,
        })
        if not card.get("ok"):
            blockers.append(str(card.get("error") or "borrowing_card_not_issued"))
        else:
            membership = _declare_reading_area_membership(args, card_id=str(card.get("card_id") or ""))
            if not membership.get("ok"):
                blockers.append(str(membership.get("error") or "membership_not_declared"))
    registry_ready = not blockers
    registry_write_performed = bool(card.get("ok") or membership.get("ok"))
    return {
        "ok": registry_ready,
        "mode": "platform_self_report_connect",
        "contract": PLATFORM_SELF_REPORT_RECEIPT_CONTRACT,
        "read_only": False,
        "write_performed": registry_write_performed,
        "registry_write_performed": registry_write_performed,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
        "chat_body_included": False,
        "raw_excerpt_included_in_self_report": False,
        "registry_metadata_written_fields": ["borrowing_card", "declared_reading_area_ids", "declared_project_ids", "declared_series_ids"] if registry_write_performed else [],
        "client_info": {
            "client_name": client_name,
            "client_version": client_version,
            "client_surface": _bounded_self_report_text(args.get("client_surface"), limit=160),
            "inferred_platform": source_system,
            "sanitized": True,
            "identity_authority": "agent_self_reported_unverified_host_neutral",
            "host_neutral_no_platform_allowlist": True,
        },
        "answers_observed": not bool(answer_blockers),
        "self_report_verified": registry_ready,
        "reading_area_registered": registry_ready,
        "platform_config_registered": False,
        "registration_scope": "reading_area_registry_only_no_platform_config_write",
        "registration_blockers": blockers,
        "connection_proof_method": "capability_check_no_recall_plus_library_id_borrow",
        "capability_check_advert": {
            "ok": bool(capability.get("ok")),
            "recall_performed": bool(capability.get("recall_performed")),
            "raw_excerpt_returned": bool(capability.get("raw_excerpt_returned")),
        },
        "real_recall_proof": {
            "ok": bool(proof.get("ok")),
            "library_id": proof_library_id,
            "mode": proof.get("mode", ""),
            "matched_count": int(proof.get("matched_count") or 0),
            "raw_excerpt_returned": bool(proof.get("raw_excerpt_returned")),
            "source_refs_count": int(proof.get("source_refs_count") or 0),
        },
        "borrowing_card_receipt": card,
        "membership_receipt": membership,
        "next_actions": [] if registry_ready else ["provide_missing_self_report_answers_and_one_library_id_borrow_proof"],
    }


def _reading_area_tool_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    extra_keys = sorted(set(args.keys()) - READING_AREA_TOOL_ALLOWED_KEYS)
    if extra_keys:
        return {
            "ok": False,
            "mode": "reading_area",
            "error": "unknown_reading_area_arguments",
            "unknown_arguments": extra_keys,
            "write_performed": False,
            "registry_write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "raw_write_performed": False,
        }
    action = str(args.get("action") or "").strip().lower()
    if action == "issue_borrowing_card":
        return _issue_reading_area_borrowing_card(args)
    if action == "declare_membership":
        return _declare_reading_area_membership(args)
    if action == "whiteboard_write":
        return _whiteboard_write_payload(args)
    if action == "whiteboard_list":
        return _whiteboard_list_payload(args)
    if action == "project_history_write":
        return _project_history_write_payload(args)
    if action == "project_history_list":
        return _project_history_list_payload(args)
    if action == "nomination_create":
        return _nomination_create_payload(args)
    if action == "nomination_list":
        return _nomination_list_payload(args)
    if action == "claim_nomination":
        return _claim_nomination_payload(args)
    if action == "reject_nomination":
        return _reject_nomination_payload(args)
    if action == "self_report_connect":
        return _platform_self_report_connect_payload(args)
    return {
        "ok": False,
        "mode": "reading_area",
        "error": "unknown_reading_area_action",
        "allowed_actions": [
            "issue_borrowing_card",
            "declare_membership",
            "self_report_connect",
            "whiteboard_write",
            "whiteboard_list",
            "project_history_write",
            "project_history_list",
            "nomination_create",
            "nomination_list",
            "claim_nomination",
            "reject_nomination",
        ],
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
    }


def mcp_call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == "time_library_reading_area":
        result = _reading_area_tool_payload(arguments if isinstance(arguments, dict) else {})
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "structuredContent": result,
            "isError": not bool(result.get("ok")),
        }
    if name not in ("time_library_recall", "zhiyi_recall"):
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        }
    args = arguments if isinstance(arguments, dict) else {}
    if _is_capability_check_request(args):
        result = capability_check_payload(
            consumer=str(args.get("consumer") or "mcp"),
            request_id=str(args.get("request_id") or ""),
            source="mcp",
        )
    elif _is_work_preflight_request(args):
        result = _work_preflight_from_kwargs(_preflight_kwargs_from_args(args, consumer_default="mcp", limit_default=3, excerpt_default=180))
    elif _is_preflight_request(args):
        result = preflight_payload(**_preflight_kwargs_from_args(args, consumer_default="mcp", limit_default=3, excerpt_default=180))
    else:
        direct_library_id = _library_id_from_args(args)
        if direct_library_id:
            result = _catalog_card_borrow_payload(
                direct_library_id,
                consumer=str(args.get("consumer") or "mcp"),
                request_id=str(args.get("request_id") or ""),
                project_id=str(args.get("project_id") or ""),
                series_id=str(args.get("series_id") or args.get("declared_series_id") or ""),
                reading_area_id=str(args.get("reading_area_id") or ""),
            )
        else:
            result = query_raw_source_refs(
                query=str(args.get("query") or ""),
                source_system=str(args.get("source_system") or ""),
                computer_name=str(args.get("computer_name") or ""),
                session_id=str(args.get("session_id") or ""),
                limit=args.get("limit", 5),
                excerpt_chars=args.get("excerpt_chars", 300),
                consumer=str(args.get("consumer") or "mcp"),
                request_id=str(args.get("request_id") or ""),
                memory_scope=str(args.get("memory_scope") or ""),
                canonical_window_id=str(args.get("canonical_window_id") or ""),
                allow_cross_window_recall=_truthy(args.get("allow_cross_window_recall")),
                cross_window_reason=str(args.get("cross_window_reason") or args.get("workflow_reason") or ""),
                project_id=str(args.get("project_id") or ""),
                project_root=str(args.get("project_root") or args.get("workspace_root") or args.get("cwd") or ""),
                workstream_id=str(args.get("workstream_id") or args.get("workstream") or ""),
                task_id=str(args.get("task_id") or args.get("task") or ""),
                recall_mode=str(args.get("recall_mode") or ""),
                fts5_recall=_truthy(args.get("fts5_recall")) or _truthy(args.get("enable_fts5_recall")),
            )
            result = compact_recall_payload(
                result,
                response_budget_mode=_response_budget_mode(args),
                include_raw_excerpt=_include_raw_excerpt(args),
            )
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False),
            }
        ],
        "structuredContent": result,
        "isError": False,
    }


def handle_mcp_request(data: Dict[str, Any]) -> Dict[str, Any] | None:
    request_id = _mcp_request_id(data)
    method = str(data.get("method") or "")
    params = data.get("params", {}) if isinstance(data.get("params"), dict) else {}

    if method == "initialize":
        return mcp_success(request_id, build_mcp_initialize_result(params))
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return mcp_success(request_id, mcp_tools_payload())
    if method == "tools/call":
        try:
            result = mcp_call_tool(
                str(params.get("name") or ""),
                params.get("arguments", {}) if isinstance(params.get("arguments"), dict) else {},
            )
        except Exception as exc:
            return mcp_error(
                request_id,
                -32603,
                f"Internal error while calling tool: {type(exc).__name__}: {exc}",
            )
        return mcp_success(request_id, result)
    if method == "ping":
        return mcp_success(request_id, {})
    return mcp_error(request_id, -32601, f"Method not found: {method}")
