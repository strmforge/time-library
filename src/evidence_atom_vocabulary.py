"""Shared evidence atom vocabulary.

This module only defines terms used by search packets, think packets, delivery
receipts, and future memory atoms. It does not write memory, rewrite raw
records, call models, or create a sixth memory layer.
"""

from __future__ import annotations

from typing import Any


EVIDENCE_ATOM_VOCABULARY_CONTRACT = "evidence_atom_vocabulary.v2026.6.21"
EVIDENCE_ATOM_SCHEMA_CONTRACT = "memory_atom_schema.v2026.6.21"

SHARED_EVIDENCE_TERMS = (
    "source_refs",
    "source_span",
    "library_id",
    "shelf",
    "semantic_type",
    "answer_bearing",
    "confidence",
    "stale_signal",
    "conflict_group",
    "supersedes",
    "errata_refs",
    "raw_expand_available",
)

MEMORY_ATOM_FIELDS = (
    "atom_id",
    "library_id",
    "shelf",
    "status",
    "semantic_type",
    "content",
    "source_refs",
    "source_span",
    "verbatim_excerpt_required",
    "confidence",
    "answer_bearing",
    "relation_refs",
    "conflict_group",
    "supersedes",
    "superseded_by",
    "last_verified_at",
    "expires_at",
    "errata_refs",
)

VALID_SHELVES = ("raw", "zhiyi", "xingce", "toolbook", "errata")
VALID_ANSWER_BEARING = ("answer_bearing", "supporting_context", "candidate_only", "not_answer_bearing")
VALID_STALE_SIGNAL = ("fresh", "stale", "expired", "unknown")


def vocabulary_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": EVIDENCE_ATOM_VOCABULARY_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "model_call_performed": False,
        "not_a_memory_layer": True,
        "final_evidence_authority": "raw_source_refs",
        "shared_terms": list(SHARED_EVIDENCE_TERMS),
        "memory_atom_fields": list(MEMORY_ATOM_FIELDS),
        "valid_shelves": list(VALID_SHELVES),
        "valid_answer_bearing": list(VALID_ANSWER_BEARING),
        "valid_stale_signal": list(VALID_STALE_SIGNAL),
        "usage": {
            "phase0": "platform_delivery_liveness_findings",
            "phase1": "search_think_packets_and_delivery_receipts",
            "phase2": "future_memory_atom_projection",
        },
    }


def validate_source_span(value: Any) -> tuple[bool, str]:
    if value in (None, "", []):
        return True, ""
    if not isinstance(value, dict):
        return False, "source_span_must_be_object"
    allowed = {
        "text",
        "byte_start",
        "byte_end",
        "line_start",
        "line_end",
        "chunk_id",
        "section_path",
        "asset_refs",
    }
    unknown = sorted(str(key) for key in value.keys() if key not in allowed)
    if unknown:
        return False, "unknown_source_span_fields=" + ",".join(unknown)
    return True, ""


def validate_memory_atom_shape(atom: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(atom, dict):
        return {
            "ok": False,
            "contract": EVIDENCE_ATOM_SCHEMA_CONTRACT,
            "errors": ["memory_atom_must_be_object"],
            "warnings": [],
        }
    for field in ("atom_id", "shelf", "semantic_type", "source_refs", "confidence", "answer_bearing"):
        if field not in atom:
            errors.append(f"missing_required_field:{field}")
    if atom.get("shelf") and atom.get("shelf") not in VALID_SHELVES:
        errors.append("invalid_shelf")
    if atom.get("answer_bearing") and atom.get("answer_bearing") not in VALID_ANSWER_BEARING:
        errors.append("invalid_answer_bearing")
    if "source_refs" in atom and not atom.get("source_refs"):
        errors.append("source_refs_required")
    if "confidence" in atom:
        try:
            confidence = float(atom.get("confidence"))
        except Exception:
            errors.append("confidence_must_be_numeric")
        else:
            if confidence < 0 or confidence > 1:
                errors.append("confidence_must_be_0_to_1")
    ok_span, span_error = validate_source_span(atom.get("source_span"))
    if not ok_span:
        errors.append(span_error)
    if atom.get("content") and not atom.get("source_span"):
        warnings.append("content_without_source_span")
    return {
        "ok": not errors,
        "contract": EVIDENCE_ATOM_SCHEMA_CONTRACT,
        "errors": errors,
        "warnings": warnings,
        "read_only": True,
        "write_performed": False,
        "final_evidence_authority": "raw_source_refs",
    }


__all__ = [
    "EVIDENCE_ATOM_VOCABULARY_CONTRACT",
    "EVIDENCE_ATOM_SCHEMA_CONTRACT",
    "SHARED_EVIDENCE_TERMS",
    "MEMORY_ATOM_FIELDS",
    "vocabulary_contract",
    "validate_memory_atom_shape",
    "validate_source_span",
]
