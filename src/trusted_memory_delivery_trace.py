"""Definition-of-Proven trace for trusted memory delivery.

This module does not recall memory, call models, or deliver messages. It turns
an already executed answer path plus separately observed gates into a compact
trace, so "wired" cannot be mistaken for "proven".
"""

from __future__ import annotations

from typing import Any

try:
    from src.delivery_receipt import build_delivery_receipt, build_delivery_receipt_view_model
    from src.search_think_contract import THINK_OWNER, build_search_result, build_think_request, validate_think_result
except Exception:  # pragma: no cover - direct script import fallback
    from delivery_receipt import build_delivery_receipt, build_delivery_receipt_view_model
    from search_think_contract import THINK_OWNER, build_search_result, build_think_request, validate_think_result


TRUSTED_MEMORY_DELIVERY_TRACE_CONTRACT = "trusted_memory_delivery_trace.v2026.6.21"
TRUSTED_MEMORY_DELIVERY_ARTIFACTS_CONTRACT = "trusted_memory_delivery_artifacts.v2026.6.21"


CELL_NAMES = (
    "passive_gate_observed",
    "model_evidence_receipt_observed",
    "answer_evidence_observed",
    "receipt_visibility_observed",
    "security_gate_observed",
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", []):
        return []
    return [value]


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _string_items(value: Any) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in _items(value):
        if isinstance(item, dict):
            for key in ("evidence_ref", "source_id", "library_id", "catalog_id", "ref", "source_path"):
                raw = item.get(key)
                if raw not in (None, "", []):
                    text = str(raw)
                    break
            else:
                text = ""
        else:
            text = str(item or "")
        if text and text not in seen:
            output.append(text)
            seen.add(text)
    return output


def _evidence_items_from_dialog(dialog: dict[str, Any]) -> list[dict[str, Any]]:
    model_call = _dict(dialog.get("model_call"))
    answer_debug = _dict(dialog.get("answer_debug"))
    debug_items = _items(answer_debug.get("evidence"))
    if debug_items:
        output = []
        for item in debug_items:
            if not isinstance(item, dict):
                continue
            evidence_ref = str(item.get("evidence_ref") or item.get("source_id") or "").strip()
            source_id = str(item.get("source_id") or evidence_ref).strip()
            if not evidence_ref and not source_id:
                continue
            output.append(
                {
                    "source_id": source_id or evidence_ref,
                    "evidence_ref": evidence_ref or source_id,
                    "role": item.get("role", ""),
                    "timestamp": item.get("timestamp", ""),
                    "source_refs": item.get("source_refs") or {},
                    "rank_reason": "dialog_answer_debug_evidence_packet",
                }
            )
        if output:
            return output

    refs = _string_items(model_call.get("evidence_packet_refs"))
    if refs:
        return [
            {
                "source_id": ref,
                "evidence_ref": ref,
                "rank_reason": "dialog_model_evidence_packet",
                "source_refs": {},
            }
            for ref in refs
        ]

    source_refs = _items(dialog.get("source_refs"))
    output = []
    for index, ref in enumerate(source_refs):
        ref_text = _string_items(ref)
        evidence_ref = ref_text[0] if ref_text else f"dialog_source_ref_{index + 1}"
        output.append(
            {
                "source_id": evidence_ref,
                "evidence_ref": evidence_ref,
                "rank_reason": "dialog_source_refs",
                "source_refs": ref,
            }
        )
    return output


def _passive_gate_cell(observations: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    passive = _dict(observations.get("passive_gate_result") or observations.get("ordinary_chat_result"))
    if not passive:
        return False, "not_measured", {"reason": "ordinary_chat_pass_through_not_measured"}
    handled = _bool(passive.get("handled"))
    text = str(passive.get("text") or "")
    pass_through = (handled is False) and text == ""
    reason = str(passive.get("reason") or "")
    if pass_through:
        return True, "observed", {"reason": reason, "handled": False}
    return False, "failed", {"reason": reason or "ordinary_chat_was_handled", "handled": handled}


def _security_gate_cell(observations: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    raw = observations.get("security_gate") or observations.get("security_gate_result")
    if isinstance(raw, bool):
        return raw, "observed" if raw else "failed", {"observed": raw}
    security = _dict(raw)
    if not security:
        return False, "not_measured", {"reason": "security_gate_not_measured"}
    ok = _bool(security.get("observed") or security.get("tests_green") or security.get("ok"))
    return ok, "observed" if ok else "failed", {
        "source": security.get("source", ""),
        "reason": security.get("reason", ""),
        "tests": security.get("tests", []),
    }


def build_trusted_memory_delivery_artifacts(
    *,
    platform: str,
    question: str,
    dialog_result: dict[str, Any],
    observations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build receipt and Definition-of-Proven trace from one live answer path."""

    dialog = _dict(dialog_result)
    observed = _dict(observations)
    model_call = _dict(dialog.get("model_call") or _dict(dialog.get("answer_debug")).get("model_call"))
    evidence_items = _evidence_items_from_dialog(dialog)
    search_result = build_search_result(
        query=str(question or ""),
        scope={
            "platform": str(platform or ""),
            "route": dialog.get("chain", ""),
            "session_id": _dict(dialog.get("native_event")).get("session_key", ""),
        },
        evidence_items=evidence_items,
        missing_evidence=[] if evidence_items else ["no_evidence"],
    )
    used_refs = _string_items(dialog.get("used_source_refs") or model_call.get("used_source_refs") or model_call.get("supporting_refs"))
    answer = str(dialog.get("answer") or dialog.get("text") or "")
    think_request = build_think_request(search_result, question=str(question or ""))
    think_result = {
        "owner": THINK_OWNER,
        "answer": answer,
        "answer_source": dialog.get("answer_source", ""),
        "used_source_refs": used_refs,
        "gap": [] if evidence_items else ["no_evidence"],
        "unknown": answer.upper() == "UNKNOWN",
    }
    think_validation = validate_think_result(think_result, think_request=think_request)
    receipt = build_delivery_receipt(
        answer_id=str(dialog.get("answer_id") or ""),
        search_result=search_result,
        think_result=think_result,
        scope=search_result.get("scope"),
    )
    receipt_view = build_delivery_receipt_view_model(receipt)

    passive_ok, passive_state, passive_detail = _passive_gate_cell(observed)
    security_ok, security_state, security_detail = _security_gate_cell(observed)
    evidence_packet_refs = _string_items(model_call.get("evidence_packet_refs")) or [
        str(item.get("evidence_ref") or item.get("source_id") or "")
        for item in evidence_items
        if str(item.get("evidence_ref") or item.get("source_id") or "")
    ]
    called = _bool(model_call.get("called"))
    request_sent = _bool(model_call.get("request_sent"))
    evidence_count = int(model_call.get("evidence_count") or len(evidence_items) or 0)
    model_receipt_ok = bool(called and request_sent and evidence_count > 0 and evidence_packet_refs)
    non_unknown_answer_ok = bool(
        answer
        and answer.upper() != "UNKNOWN"
        and dialog.get("answer_source") == "evidence_bound_model_call"
        and used_refs
        and think_validation.get("ok")
    )
    unknown_answer_ok = bool(
        answer.upper() == "UNKNOWN"
        and dialog.get("answer_source") == "evidence_bound_model_call"
        and called
        and request_sent
        and think_validation.get("ok")
    )
    answer_evidence_ok = bool(non_unknown_answer_ok or unknown_answer_ok)
    receipt_visible_ok = bool(
        receipt_view.get("status") in {"source_backed", "unknown"}
        and (
            receipt_view.get("used_source_refs")
            or receipt_view.get("unknown_boundary")
            or receipt_view.get("gaps")
        )
    )

    cells = {
        "passive_gate_observed": passive_ok,
        "model_evidence_receipt_observed": model_receipt_ok,
        "answer_evidence_observed": answer_evidence_ok,
        "receipt_visibility_observed": receipt_visible_ok,
        "security_gate_observed": security_ok,
    }
    cell_states = {
        "passive_gate_observed": passive_state,
        "model_evidence_receipt_observed": "observed" if model_receipt_ok else "not_measured",
        "answer_evidence_observed": "observed" if answer_evidence_ok else "failed",
        "receipt_visibility_observed": "observed" if receipt_visible_ok else "not_measured",
        "security_gate_observed": security_state,
    }
    missing = [name for name in CELL_NAMES if not cells.get(name)]
    status = "proven" if not missing else "unproven"
    trace = {
        "ok": status == "proven",
        "contract": TRUSTED_MEMORY_DELIVERY_TRACE_CONTRACT,
        "status": status,
        "platform": str(platform or ""),
        "definition": "observed_end_to_end_trace_all_five_cells_required",
        "model_not_measured_means_unproven": True,
        "read_only": True,
        "write_performed": False,
        "model_call_performed": False,
        "platform_write_performed": False,
        "cells": cells,
        "cell_states": cell_states,
        "cell_details": {
            "passive_gate_observed": passive_detail,
            "model_evidence_receipt_observed": {
                "called": called,
                "request_sent": request_sent,
                "evidence_count": evidence_count,
                "evidence_packet_refs": evidence_packet_refs,
            },
            "answer_evidence_observed": {
                "answer_source": dialog.get("answer_source", ""),
                "used_source_refs": used_refs,
                "think_validation_ok": bool(think_validation.get("ok")),
                "think_validation_errors": think_validation.get("errors", []),
            },
            "receipt_visibility_observed": {
                "receipt_view_contract": receipt_view.get("contract", ""),
                "receipt_status": receipt_view.get("status", ""),
                "unknown_boundary": bool(receipt_view.get("unknown_boundary")),
            },
            "security_gate_observed": security_detail,
        },
        "missing_cells": missing,
        "model_delivery_state": "observed" if model_receipt_ok else "not_measured",
        "delivered_to_model": "observed" if model_receipt_ok else "not_measured",
        "used_source_refs": used_refs,
        "evidence_packet_refs": evidence_packet_refs,
        "receipt_visible": receipt_visible_ok,
        "unknown_boundary": bool(receipt_view.get("unknown_boundary")),
        "final_evidence_authority": "raw_source_refs",
    }
    return {
        "ok": True,
        "contract": TRUSTED_MEMORY_DELIVERY_ARTIFACTS_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "model_call_performed": False,
        "search_result": search_result,
        "think_request": think_request,
        "think_result": think_result,
        "think_validation": think_validation,
        "delivery_receipt": receipt,
        "delivery_receipt_view": receipt_view,
        "trusted_memory_delivery_trace": trace,
    }


__all__ = [
    "TRUSTED_MEMORY_DELIVERY_TRACE_CONTRACT",
    "TRUSTED_MEMORY_DELIVERY_ARTIFACTS_CONTRACT",
    "build_trusted_memory_delivery_artifacts",
]
