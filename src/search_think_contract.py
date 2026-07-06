"""Search/think boundary contracts.

Local Memcore owns search and evidence packaging. The final think answer is
owned by the evidence-bound model. This module only builds and validates packet
shapes; it does not call models or synthesize answers.
"""

from __future__ import annotations

from typing import Any

try:
    from src.evidence_atom_vocabulary import EVIDENCE_ATOM_VOCABULARY_CONTRACT, SHARED_EVIDENCE_TERMS
except Exception:  # pragma: no cover - direct script import fallback
    from evidence_atom_vocabulary import EVIDENCE_ATOM_VOCABULARY_CONTRACT, SHARED_EVIDENCE_TERMS


SEARCH_THINK_CONTRACT = "search_think_boundary.v2026.6.21"
SEARCH_RESULT_CONTRACT = "memory_search_result.v2026.6.21"
THINK_REQUEST_CONTRACT = "evidence_bound_think_request.v2026.6.21"
THINK_RESULT_VALIDATION_CONTRACT = "evidence_bound_think_validation.v2026.6.21"

SEARCH_OWNER = "local_memcore"
THINK_OWNER = "evidence_bound_model"

LOCAL_ALLOWED_AFTER_THINK = (
    "validate_used_source_refs",
    "validate_unknown_boundary",
    "validate_no_unseen_evidence_claim",
)

LOCAL_FORBIDDEN_AFTER_THINK = (
    "synthesize_answer",
    "rewrite_answer",
    "fill_missing_evidence",
    "replace_model_judgment_with_draft",
)


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _ref_key(ref: Any) -> str:
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        for key in ("evidence_ref", "source_id", "library_id", "ref_id", "source_path"):
            value = ref.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _source_ref_keys(refs: Any) -> set[str]:
    if isinstance(refs, dict):
        key = _ref_key(refs)
        return {key} if key else set()
    if isinstance(refs, list):
        return {key for key in (_ref_key(item) for item in refs) if key}
    return set()


def _source_ref_catalog_ids(refs: Any) -> set[str]:
    """Return catalog ids only from structured source-ref objects.

    Top-level evidence-item catalog ids are display/navigation handles. For the
    model-used-ref validator they count only when they are attached to a
    source_refs object that also carries source evidence shape.
    """

    if isinstance(refs, dict):
        if any(key in refs for key in ("text", "matched_by", "rank_reason", "raw_expand_available")):
            return set()
        catalog_id = str(refs.get("catalog_id") or "").strip()
        has_source_shape = any(refs.get(key) not in (None, "", []) for key in ("source_path", "evidence_ref"))
        return {catalog_id} if catalog_id and has_source_shape else set()
    if isinstance(refs, list):
        out: set[str] = set()
        for item in refs:
            out.update(_source_ref_catalog_ids(item))
        return out
    return set()


def boundary_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": SEARCH_THINK_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "model_call_performed": False,
        "search_owner": SEARCH_OWNER,
        "think_owner": THINK_OWNER,
        "local_allowed_after_think": list(LOCAL_ALLOWED_AFTER_THINK),
        "local_forbidden_after_think": list(LOCAL_FORBIDDEN_AFTER_THINK),
        "evidence_atom_vocabulary_contract": EVIDENCE_ATOM_VOCABULARY_CONTRACT,
        "shared_evidence_terms": list(SHARED_EVIDENCE_TERMS),
        "final_evidence_authority": "raw_source_refs",
    }


def build_search_result(
    *,
    query: str,
    scope: dict[str, Any] | None = None,
    evidence_items: list[dict[str, Any]] | None = None,
    missing_evidence: list[str] | None = None,
    stale_signals: list[str] | None = None,
    conflict_signals: list[str] | None = None,
) -> dict[str, Any]:
    items = _items(evidence_items)
    source_refs: list[Any] = []
    library_ids: list[str] = []
    for item in items:
        if item.get("source_refs") not in (None, "", []):
            source_refs.append(item.get("source_refs"))
        if item.get("library_id"):
            library_ids.append(str(item.get("library_id")))
    return {
        "ok": True,
        "contract": SEARCH_RESULT_CONTRACT,
        "owner": SEARCH_OWNER,
        "query": str(query or ""),
        "scope": scope or {},
        "evidence_items": items,
        "source_refs": source_refs,
        "library_ids": library_ids,
        "matched_by": sorted({str(item.get("matched_by") or "unknown") for item in items}),
        "rank_reason": [str(item.get("rank_reason") or "") for item in items if item.get("rank_reason")],
        "stale_signals": stale_signals or [],
        "conflict_signals": conflict_signals or [],
        "missing_evidence": missing_evidence or ([] if items else ["no_evidence"]),
        "evidence_atom_vocabulary_contract": EVIDENCE_ATOM_VOCABULARY_CONTRACT,
        "shared_evidence_terms": list(SHARED_EVIDENCE_TERMS),
        "raw_available": any(bool(item.get("raw_expand_available") or item.get("raw_excerpt") or item.get("source_refs")) for item in items),
        "answer_synthesized": False,
        "model_call_performed": False,
        "write_performed": False,
        "final_evidence_authority": "raw_source_refs",
    }


def build_think_request(search_result: dict[str, Any], *, question: str = "") -> dict[str, Any]:
    evidence_items = _items(search_result.get("evidence_items"))
    return {
        "ok": True,
        "contract": THINK_REQUEST_CONTRACT,
        "search_owner": search_result.get("owner") or SEARCH_OWNER,
        "think_owner": THINK_OWNER,
        "question": str(question or search_result.get("query") or ""),
        "evidence_items": evidence_items,
        "source_refs": search_result.get("source_refs") or [],
        "gap": search_result.get("missing_evidence") or [],
        "conflict": search_result.get("conflict_signals") or [],
        "stale": search_result.get("stale_signals") or [],
        "unknown_required": not bool(evidence_items),
        "evidence_atom_vocabulary_contract": search_result.get("evidence_atom_vocabulary_contract") or EVIDENCE_ATOM_VOCABULARY_CONTRACT,
        "shared_evidence_terms": search_result.get("shared_evidence_terms") or list(SHARED_EVIDENCE_TERMS),
        "local_may_synthesize_answer": False,
        "model_call_performed": False,
        "write_performed": False,
        "final_evidence_authority": "raw_source_refs",
    }


def validate_think_result(
    think_result: dict[str, Any],
    *,
    think_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = think_result if isinstance(think_result, dict) else {}
    request = think_request if isinstance(think_request, dict) else {}
    errors: list[str] = []
    warnings: list[str] = []
    owner = str(result.get("owner") or result.get("think_owner") or "")
    if owner != THINK_OWNER:
        errors.append("think_answer_owner_must_be_evidence_bound_model")
    answer = str(result.get("answer") or "")
    if result.get("answer_source") and result.get("answer_source") != "evidence_bound_model_call":
        errors.append("answer_source_must_be_evidence_bound_model_call")
    if result.get("local_draft_detected") or str(result.get("answer_source") or "").startswith("local_") or "fallback" in str(result.get("answer_source") or ""):
        errors.append("local_draft_or_fallback_cannot_be_think_answer")
    evidence_keys = set()
    for item in _items(request.get("evidence_items")):
        for key in (_ref_key(item), _ref_key(item.get("source_refs"))):
            if key:
                evidence_keys.add(key)
        evidence_keys.update(_source_ref_catalog_ids(item.get("source_refs")))
    evidence_keys.update(_source_ref_keys(request.get("source_refs")))
    evidence_keys.update(_source_ref_catalog_ids(request.get("source_refs")))
    used_refs = _source_ref_keys(result.get("used_source_refs") or result.get("supporting_refs"))
    used_refs.update(_source_ref_catalog_ids(result.get("used_source_refs") or result.get("supporting_refs")))
    invalid_refs = sorted(ref for ref in used_refs if evidence_keys and ref not in evidence_keys)
    if invalid_refs:
        errors.append("used_source_refs_not_in_search_result")
    if answer and answer.upper() != "UNKNOWN" and not used_refs:
        errors.append("non_unknown_answer_requires_used_source_refs")
    if request.get("unknown_required") and answer.upper() != "UNKNOWN":
        errors.append("unknown_required_but_model_answered")
    if not answer:
        warnings.append("empty_answer")
    return {
        "ok": not errors,
        "contract": THINK_RESULT_VALIDATION_CONTRACT,
        "errors": errors,
        "warnings": warnings,
        "owner": owner,
        "read_only": True,
        "write_performed": False,
        "model_call_performed": False,
        "local_allowed_after_think": list(LOCAL_ALLOWED_AFTER_THINK),
        "local_forbidden_after_think": list(LOCAL_FORBIDDEN_AFTER_THINK),
        "final_evidence_authority": "raw_source_refs",
    }


__all__ = [
    "SEARCH_THINK_CONTRACT",
    "SEARCH_RESULT_CONTRACT",
    "THINK_REQUEST_CONTRACT",
    "THINK_RESULT_VALIDATION_CONTRACT",
    "SEARCH_OWNER",
    "THINK_OWNER",
    "boundary_contract",
    "build_search_result",
    "build_think_request",
    "validate_think_result",
]
