"""Dry-run chain for local search, model-owned think, and delivery receipt.

This module intentionally stays thin. Local Memcore may build the search
packet, call the evidence-bound model, validate the returned source refs, and
project a user-visible receipt. It must not synthesize or repair the final
answer locally.
"""

from __future__ import annotations

from typing import Any, Callable

try:
    from src.delivery_receipt import build_delivery_receipt, build_delivery_receipt_view_model
    from src.evidence_bound_model import EvidenceBoundModelConfig, run_evidence_bound_answer
    from src.search_think_contract import (
        LOCAL_ALLOWED_AFTER_THINK,
        LOCAL_FORBIDDEN_AFTER_THINK,
        SEARCH_OWNER,
        THINK_OWNER,
        build_search_result,
        build_think_request,
        validate_think_result,
    )
except Exception:  # pragma: no cover - direct script import fallback
    from delivery_receipt import build_delivery_receipt, build_delivery_receipt_view_model
    from evidence_bound_model import EvidenceBoundModelConfig, run_evidence_bound_answer
    from search_think_contract import (
        LOCAL_ALLOWED_AFTER_THINK,
        LOCAL_FORBIDDEN_AFTER_THINK,
        SEARCH_OWNER,
        THINK_OWNER,
        build_search_result,
        build_think_request,
        validate_think_result,
    )


SEARCH_THINK_DRY_RUN_CONTRACT = "search_think_delivery_receipt_dry_run.v2026.6.21"
THINK_RESULT_CONTRACT = "evidence_bound_think_result.v2026.6.21"


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def dry_run_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": SEARCH_THINK_DRY_RUN_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "search_owner": SEARCH_OWNER,
        "think_owner": THINK_OWNER,
        "local_answer_synthesis_allowed": False,
        "local_allowed_after_think": list(LOCAL_ALLOWED_AFTER_THINK),
        "local_forbidden_after_think": list(LOCAL_FORBIDDEN_AFTER_THINK),
        "receipt_is_projection_only": True,
        "final_evidence_authority": "raw_source_refs",
    }


def _model_result_to_think_result(
    model_result: dict[str, Any],
    *,
    think_request: dict[str, Any],
) -> dict[str, Any]:
    answer = _text(model_result.get("answer")) or "UNKNOWN"
    supporting_refs = _items(model_result.get("supporting_refs"))
    gaps = _items(think_request.get("gap"))
    unknown_reason = _text(model_result.get("unknown_reason"))
    validation_error = _text(model_result.get("validation_error"))
    unknown = (
        answer.upper() == "UNKNOWN"
        or bool(gaps)
        or _text(model_result.get("verdict")).lower() in {"unknown", "dry_run", "model_error"}
        or bool(validation_error)
    )
    return {
        "ok": bool(model_result.get("ok", True)),
        "contract": THINK_RESULT_CONTRACT,
        "owner": THINK_OWNER,
        "answer_source": "evidence_bound_model_call",
        "answer": answer,
        "verdict": _text(model_result.get("verdict")),
        "confidence": model_result.get("confidence", 0.0),
        "used_source_refs": supporting_refs,
        "supporting_refs": supporting_refs,
        "supporting_source_refs": _items(model_result.get("supporting_source_refs")),
        "gap": gaps,
        "conflict": _items(think_request.get("conflict")),
        "stale": _items(think_request.get("stale")),
        "unknown": unknown,
        "unknown_reason": unknown_reason or (";".join(str(item) for item in gaps) if gaps else ""),
        "model_call_performed": bool(model_result.get("model_call_performed", False)),
        "evidence_bound_model_contract": model_result.get("contract", ""),
        "evidence_bound_model_schema": model_result.get("schema", ""),
        "validation_error": validation_error,
        "invalid_supporting_refs": _items(model_result.get("invalid_supporting_refs")),
        "local_draft_detected": False,
        "local_answer_synthesis_performed": False,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "final_evidence_authority": "raw_source_refs",
    }


def run_search_think_dry_run(
    *,
    query: str,
    scope: dict[str, Any] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
    missing_evidence: list[str] | None = None,
    stale_signals: list[str] | None = None,
    conflict_signals: list[str] | None = None,
    task_kind: str = "answer",
    answer_id: str = "",
    execute: bool = False,
    client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    model_config: EvidenceBoundModelConfig | dict | None = None,
    max_evidence_items: int = 8,
) -> dict[str, Any]:
    search_result = build_search_result(
        query=query,
        scope=scope or {},
        evidence_items=evidence_items or [],
        missing_evidence=missing_evidence,
        stale_signals=stale_signals,
        conflict_signals=conflict_signals,
    )
    think_request = build_think_request(search_result, question=query)
    question_context = {
        "scope": scope or {},
        "gap": think_request.get("gap") or [],
        "conflict": think_request.get("conflict") or [],
        "stale": think_request.get("stale") or [],
        "source_refs": think_request.get("source_refs") or [],
        "local_may_synthesize_answer": False,
        "final_evidence_authority": "raw_source_refs",
    }
    model_result = run_evidence_bound_answer(
        _text(query),
        think_request.get("evidence_items") or [],
        task_kind=task_kind,
        question_context=question_context,
        model_config=model_config,
        execute=execute,
        client=client,
        max_evidence_items=max_evidence_items,
    )
    think_result = _model_result_to_think_result(_dict(model_result), think_request=think_request)
    validation = validate_think_result(think_result, think_request=think_request)
    receipt = build_delivery_receipt(
        answer_id=answer_id,
        search_result=search_result,
        think_result=think_result,
        scope=scope or {},
    )
    receipt_view = build_delivery_receipt_view_model(receipt)
    ok = bool(model_result.get("ok", True)) and bool(validation.get("ok"))
    return {
        "ok": ok,
        "contract": SEARCH_THINK_DRY_RUN_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "search_owner": SEARCH_OWNER,
        "think_owner": THINK_OWNER,
        "model_call_performed": bool(model_result.get("model_call_performed", False)),
        "local_answer_synthesis_allowed": False,
        "local_answer_synthesis_performed": False,
        "answer_synthesized_by_local": False,
        "no_local_fallback_answer": True,
        "search_result": search_result,
        "think_request": think_request,
        "evidence_bound_model_result": model_result,
        "think_result": think_result,
        "think_validation": validation,
        "delivery_receipt": receipt,
        "delivery_receipt_view": receipt_view,
        "boundary": {
            "search_is_local": True,
            "think_answer_is_model_owned": True,
            "local_after_think_is_validation_only": True,
            "receipt_is_projection_only": True,
            "raw_source_refs_are_final_authority": True,
        },
        "local_allowed_after_think": list(LOCAL_ALLOWED_AFTER_THINK),
        "local_forbidden_after_think": list(LOCAL_FORBIDDEN_AFTER_THINK),
        "final_evidence_authority": "raw_source_refs",
    }


__all__ = [
    "SEARCH_THINK_DRY_RUN_CONTRACT",
    "THINK_RESULT_CONTRACT",
    "dry_run_contract",
    "run_search_think_dry_run",
]
