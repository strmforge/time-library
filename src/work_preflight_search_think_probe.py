"""Read-only bridge from work_preflight findings to search/think dry-run.

This probe observes the local work_preflight return shape, converts compact
source anchors into evidence items, then runs the search/think/receipt dry-run.
It is not a platform delivery proof and does not call a model by default.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

try:
    from src.evidence_bound_model import EvidenceBoundModelConfig
    from src.platform_delivery_probe import (
        DEFAULT_WORK_PREFLIGHT_ENDPOINT as _PLATFORM_DEFAULT_WORK_PREFLIGHT_ENDPOINT,
        _run_work_preflight_probe as _run_platform_work_preflight_probe,
    )
    from src.search_think_dry_run import run_search_think_dry_run
    from src.source_ref_compact_evidence import (
        DEFAULT_COMPACT_EVIDENCE_CHARS,
        build_source_ref_compact_evidence_probe,
        source_refs_from_surface,
    )
except Exception:  # pragma: no cover - direct script import fallback
    from evidence_bound_model import EvidenceBoundModelConfig
    from platform_delivery_probe import (
        DEFAULT_WORK_PREFLIGHT_ENDPOINT as _PLATFORM_DEFAULT_WORK_PREFLIGHT_ENDPOINT,
        _run_work_preflight_probe as _run_platform_work_preflight_probe,
    )
    from search_think_dry_run import run_search_think_dry_run
    from source_ref_compact_evidence import (
        DEFAULT_COMPACT_EVIDENCE_CHARS,
        build_source_ref_compact_evidence_probe,
        source_refs_from_surface,
    )


WORK_PREFLIGHT_SEARCH_THINK_PROBE_CONTRACT = "work_preflight_search_think_probe.v2026.6.21"
WORK_PREFLIGHT_ENTRY_PROBE_CONTRACT = "work_preflight_search_think_entry_probe.v2026.6.21"
CONTROLLED_THINK_EXECUTION_CONTRACT = "controlled_evidence_bound_think_execution.v2026.6.21"
DEFAULT_WORK_PREFLIGHT_ENDPOINT = _PLATFORM_DEFAULT_WORK_PREFLIGHT_ENDPOINT


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _run_work_preflight_probe(body: dict[str, Any]) -> dict[str, Any]:
    probe_body = {
        **body,
        "consumer": body.get("consumer") or "work-preflight-search-think-probe",
    }
    probe = _run_platform_work_preflight_probe(probe_body)
    return {**probe, "contract": WORK_PREFLIGHT_ENTRY_PROBE_CONTRACT}


def _controlled_think_execution(
    body: dict[str, Any],
    *,
    client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    force_execute: bool = False,
) -> dict[str, Any]:
    execute_requested = bool(force_execute or _bool(body.get("execute_think") or body.get("execute") or body.get("call_model"), False))
    confirmed = _bool(body.get("confirm_model_call") or body.get("confirm_think_execution"), False)
    client_supplied = client is not None
    allowed = bool(force_execute or (execute_requested and confirmed))
    blocked_reasons: list[str] = []
    if execute_requested and not allowed:
        blocked_reasons.append("confirm_model_call_required")
    return {
        "contract": CONTROLLED_THINK_EXECUTION_CONTRACT,
        "execute_requested": execute_requested,
        "confirm_model_call": confirmed,
        "client_supplied": client_supplied,
        "allowed": allowed,
        "default_no_model_call": not execute_requested,
        "blocked_reasons": blocked_reasons,
        "answer_owner_if_executed": "evidence_bound_model",
        "local_answer_synthesis_allowed": False,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
    }


def _source_refs_for_surface(item: dict[str, Any]) -> dict[str, Any]:
    refs = source_refs_from_surface(item)
    return {key: value for key, value in refs.items() if value}


def _has_answer_text(item: dict[str, Any]) -> bool:
    return bool(_text(item.get("title")) or _text(item.get("summary")) or _text(item.get("rank_reason")))


def _work_preflight_surfaces(response: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = _dict(response)
    surfaces = [item for item in _items(payload.get("must_surface")) if isinstance(item, dict)]
    if not surfaces:
        surfaces = [item for item in _items(payload.get("library_index_projection_refs")) if isinstance(item, dict)]
    return surfaces[:3]


def evidence_items_from_work_preflight_response(
    response: dict[str, Any] | None = None,
    *,
    backtrace_source_refs: bool = True,
    compact_evidence_chars: int = DEFAULT_COMPACT_EVIDENCE_CHARS,
    memcore_root: str = "",
) -> list[dict[str, Any]]:
    """Convert compact work_preflight source anchors into dry-run evidence.

    Default mode resolves source refs into bounded compact evidence for the
    evidence-bound model packet, but never exposes raw excerpts as frontend raw
    text. Pass backtrace_source_refs=False to inspect only the compact
    work_preflight surface.
    """

    surfaces = _work_preflight_surfaces(response)
    if backtrace_source_refs:
        probe = build_source_ref_compact_evidence_probe(
            surfaces,
            limit=3,
            excerpt_chars=compact_evidence_chars,
            memcore_root=memcore_root,
        )
        return [item for item in _items(probe.get("items")) if isinstance(item, dict)]

    evidence: list[dict[str, Any]] = []
    for index, surface in enumerate(surfaces[:3], start=1):
        source_refs = _source_refs_for_surface(surface)
        library_id = _text(surface.get("library_id")) or f"work-preflight-{index}"
        evidence_ref = _text(surface.get("evidence_ref")) or library_id
        has_answer_text = _has_answer_text(surface)
        text_parts = [
            _text(surface.get("title")),
            _text(surface.get("summary")),
            _text(surface.get("rank_reason")),
            _text(surface.get("source_path")),
        ]
        text = " | ".join(part for part in text_parts if part)
        if not text:
            text = f"work_preflight source anchor {index}"
        evidence.append(
            {
                "source_id": evidence_ref,
                "evidence_ref": evidence_ref,
                "library_id": library_id,
                "shelf": _text(surface.get("library_shelf")),
                "semantic_type": "work_preflight_surface",
                "answer_bearing": "supporting_context" if has_answer_text else "candidate_only",
                "text": text,
                "matched_by": ",".join(str(item) for item in _items(surface.get("matched_by"))) or "work_preflight",
                "rank_reason": _text(surface.get("rank_reason")),
                "source_refs": source_refs,
                "raw_expand_available": bool(source_refs.get("source_path")),
                "raw_excerpt_exposed_by_default": False,
            }
        )
    return evidence


def _compact_search_think_dry_run(dry_run: dict[str, Any]) -> dict[str, Any]:
    payload = _dict(dry_run)
    model_result = _dict(payload.get("evidence_bound_model_result"))
    search_result = _dict(payload.get("search_result"))
    think_request = _dict(payload.get("think_request"))
    think_result = _dict(payload.get("think_result"))
    validation = _dict(payload.get("think_validation"))
    receipt = _dict(payload.get("delivery_receipt"))
    return {
        "ok": bool(payload.get("ok")),
        "contract": payload.get("contract", ""),
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "search_owner": payload.get("search_owner", ""),
        "think_owner": payload.get("think_owner", ""),
        "model_call_performed": bool(payload.get("model_call_performed", False)),
        "local_answer_synthesis_allowed": bool(payload.get("local_answer_synthesis_allowed", False)),
        "answer_synthesized_by_local": bool(payload.get("answer_synthesized_by_local", False)),
        "search_result": {
            "contract": search_result.get("contract", ""),
            "owner": search_result.get("owner", ""),
            "query": search_result.get("query", ""),
            "evidence_items_count": len(_items(search_result.get("evidence_items"))),
            "library_ids": search_result.get("library_ids") or [],
            "source_refs_count": len(_items(search_result.get("source_refs"))),
            "missing_evidence": search_result.get("missing_evidence") or [],
            "raw_available": bool(search_result.get("raw_available", False)),
        },
        "think_request": {
            "contract": think_request.get("contract", ""),
            "think_owner": think_request.get("think_owner", ""),
            "evidence_items_count": len(_items(think_request.get("evidence_items"))),
            "gap": think_request.get("gap") or [],
            "conflict": think_request.get("conflict") or [],
            "stale": think_request.get("stale") or [],
            "local_may_synthesize_answer": bool(think_request.get("local_may_synthesize_answer", False)),
        },
        "evidence_bound_model_result": {
            "contract": model_result.get("contract", ""),
            "schema": model_result.get("schema", ""),
            "provider": model_result.get("provider", ""),
            "model": model_result.get("model", ""),
            "api_key_present": bool(model_result.get("api_key_present", False)),
            "model_call_performed": bool(model_result.get("model_call_performed", False)),
            "evidence_count": int(model_result.get("evidence_count") or 0),
            "answer": model_result.get("answer", ""),
            "verdict": model_result.get("verdict", ""),
            "supporting_refs": model_result.get("supporting_refs") or [],
            "unknown_reason": model_result.get("unknown_reason", ""),
            "prompt_messages_omitted": "compact_probe_output",
        },
        "think_result": {
            "contract": think_result.get("contract", ""),
            "owner": think_result.get("owner", ""),
            "answer_source": think_result.get("answer_source", ""),
            "answer": think_result.get("answer", ""),
            "verdict": think_result.get("verdict", ""),
            "used_source_refs": think_result.get("used_source_refs") or [],
            "gap": think_result.get("gap") or [],
            "unknown": bool(think_result.get("unknown", False)),
            "unknown_reason": think_result.get("unknown_reason", ""),
        },
        "think_validation": {
            "ok": bool(validation.get("ok")),
            "errors": validation.get("errors") or [],
            "warnings": validation.get("warnings") or [],
        },
        "delivery_receipt": {
            "contract": receipt.get("contract", ""),
            "recalled_records_count": int(receipt.get("recalled_records_count") or 0),
            "used_records_count": int(receipt.get("used_records_count") or 0),
            "library_ids": receipt.get("library_ids") or [],
            "gaps": receipt.get("gaps") or [],
            "unknown_boundary": bool(receipt.get("unknown_boundary", False)),
            "answer_owner": receipt.get("answer_owner", ""),
        },
        "delivery_receipt_view": payload.get("delivery_receipt_view") or {},
        "boundary": payload.get("boundary") or {},
        "final_evidence_authority": "raw_source_refs",
    }


def build_work_preflight_search_think_probe(
    body: dict[str, Any] | None = None,
    *,
    execute: bool = False,
    client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    query = _text(body.get("query") or body.get("work_preflight_query") or "继续，开工前先查已有机制")
    work_probe = _run_work_preflight_probe(
        {
            **body,
            "endpoint": body.get("endpoint") or body.get("work_preflight_endpoint") or DEFAULT_WORK_PREFLIGHT_ENDPOINT,
            "query": query,
        }
    )
    response = _dict(work_probe.get("response"))
    execution_gate = _controlled_think_execution(body, client=client, force_execute=execute)
    surfaces = _work_preflight_surfaces(response)
    source_ref_compact_evidence_probe = build_source_ref_compact_evidence_probe(
        surfaces,
        limit=3,
        excerpt_chars=int(body.get("compact_evidence_chars") or DEFAULT_COMPACT_EVIDENCE_CHARS),
        memcore_root=_text(body.get("memcore_root")),
    )
    evidence = [item for item in _items(source_ref_compact_evidence_probe.get("items")) if isinstance(item, dict)]
    missing_evidence: list[str] = []
    if not response.get("ok"):
        missing_evidence.append("work_preflight_response_not_ok")
    if response.get("scope_missing"):
        missing_evidence.append("work_preflight_scope_missing")
    if not evidence:
        missing_evidence.append("work_preflight_no_compact_evidence_items")
    elif all(str(item.get("answer_bearing") or "") == "candidate_only" for item in evidence):
        missing_evidence.append("work_preflight_source_anchors_only_no_answer_text")
    execute_allowed = bool(execution_gate.get("allowed"))
    dry_run = run_search_think_dry_run(
        query=query,
        scope={
            "canonical_window_id": _dict(work_probe.get("request")).get("canonical_window_id", ""),
            "source_system": _dict(work_probe.get("request")).get("source_system", ""),
            "work_preflight_contract": response.get("contract", ""),
            "fast_recall_path": response.get("fast_recall_path", ""),
        },
        evidence_items=evidence,
        missing_evidence=missing_evidence,
        task_kind="work_preflight_evidence_answer",
        answer_id=_text(body.get("answer_id") or "work-preflight-dry-run"),
        execute=execute_allowed,
        client=client if execute_allowed else None,
        model_config=body.get("model_config"),
    )
    compact_dry_run = _compact_search_think_dry_run(dry_run)
    return {
        "ok": bool(work_probe.get("ok")) and bool(dry_run.get("ok")),
        "contract": WORK_PREFLIGHT_SEARCH_THINK_PROBE_CONTRACT,
        "created_at": _now(),
        "read_only": True,
        "findings_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": bool(dry_run.get("model_call_performed")),
        "platform_chat_delivery_attempted": False,
        "not_platform_delivery_proof": True,
        "not_a_model_answerer_by_default": not bool(execute or execution_gate.get("allowed") or client),
        "controlled_think_execution": {
            **execution_gate,
            "model_call_performed": bool(dry_run.get("model_call_performed")),
        },
        "work_preflight_probe": work_probe,
        "source_ref_compact_evidence_probe": {
            "contract": source_ref_compact_evidence_probe.get("contract", ""),
            "ok": bool(source_ref_compact_evidence_probe.get("ok")),
            "read_only": True,
            "findings_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "model_call_performed": False,
            "raw_excerpt_exposed": False,
            "compact_evidence_for_model_only": True,
            "items_count": int(source_ref_compact_evidence_probe.get("items_count") or 0),
            "answer_bearing_items_count": int(source_ref_compact_evidence_probe.get("answer_bearing_items_count") or 0),
            "raw_backtrace_hits_count": int(source_ref_compact_evidence_probe.get("raw_backtrace_hits_count") or 0),
        },
        "evidence_items_count": len(evidence),
        "evidence_items": evidence,
        "missing_evidence": missing_evidence,
        "search_think_dry_run": compact_dry_run,
        "delivery_receipt_view": compact_dry_run.get("delivery_receipt_view") or {},
        "boundary": {
            "local_memcore_search_only": True,
            "think_answer_model_owned": True,
            "default_no_model_call": not bool(execute or execution_gate.get("allowed") or client),
            "controlled_model_call_requires_explicit_gate": True,
            "receipt_projection_only": True,
            "source_refs_are_local_entry_evidence_not_platform_model_receipt": True,
            "raw_excerpt_not_exposed_by_default": True,
            "compact_evidence_for_model_only": True,
        },
        "final_evidence_authority": "raw_source_refs",
    }


__all__ = [
    "WORK_PREFLIGHT_SEARCH_THINK_PROBE_CONTRACT",
    "build_work_preflight_search_think_probe",
    "evidence_items_from_work_preflight_response",
]
