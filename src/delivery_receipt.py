"""User-visible delivery receipt shape.

The receipt is a compact projection for frontends. It shows what evidence was
used, what was missing, and whether raw evidence can be expanded. It is not a
delivery mechanism and does not perform writes or model calls.
"""

from __future__ import annotations

from typing import Any


DELIVERY_RECEIPT_CONTRACT = "memory_delivery_receipt.v2026.6.21"
DELIVERY_RECEIPT_VIEW_CONTRACT = "memory_delivery_receipt_view.v2026.6.21"


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value in (None, "") else [value])


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact_ref(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"ref": value}
    if not isinstance(value, dict):
        return {"ref": str(value)}
    keys = (
        "source_system",
        "source_path",
        "source_id",
        "evidence_ref",
        "library_id",
        "catalog_id",
        "session_id",
        "canonical_window_id",
        "line",
        "line_start",
        "line_end",
        "byte_offsets",
    )
    compact = {key: value.get(key) for key in keys if value.get(key) not in (None, "", [])}
    if not compact and value:
        compact["ref"] = str(value)
    return compact


def _flatten_refs(value: Any, *, limit: int = 3) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in _items(value):
        if isinstance(item, list):
            refs.extend(_compact_ref(child) for child in item)
        else:
            refs.append(_compact_ref(item))
        if len(refs) >= limit:
            break
    return refs[:limit]


def _used_library_ids(search: dict[str, Any], think: dict[str, Any], used_refs: list[Any]) -> list[str]:
    explicit = _items(think.get("used_library_ids") or think.get("supporting_library_ids") or search.get("used_library_ids"))
    if explicit:
        return [str(item) for item in explicit if str(item)]
    ref_to_library_id: dict[str, str] = {}
    for item in _items(search.get("evidence_items")):
        if not isinstance(item, dict):
            continue
        library_id = str(item.get("library_id") or "").strip()
        if not library_id:
            continue
        for key in ("source_id", "evidence_ref", "ref", "id"):
            ref = str(item.get(key) or "").strip()
            if ref:
                ref_to_library_id[ref] = library_id
    used_ids: list[str] = []
    for ref in used_refs:
        key = str(ref.get("evidence_ref") if isinstance(ref, dict) else ref).strip()
        library_id = ref_to_library_id.get(key)
        if library_id and library_id not in used_ids:
            used_ids.append(library_id)
    return used_ids


def build_delivery_receipt(
    *,
    answer_id: str = "",
    search_result: dict[str, Any] | None = None,
    think_result: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    search = search_result if isinstance(search_result, dict) else {}
    think = think_result if isinstance(think_result, dict) else {}
    evidence_items = _items(search.get("evidence_items"))
    used_refs = _items(think.get("used_source_refs") or think.get("supporting_refs"))
    used_library_ids = _used_library_ids(search, think, used_refs)
    gaps = _items(think.get("gap") or search.get("missing_evidence"))
    conflicts = _items(think.get("conflict") or search.get("conflict_signals"))
    return {
        "ok": True,
        "contract": DELIVERY_RECEIPT_CONTRACT,
        "answer_id": str(answer_id or think.get("answer_id") or ""),
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "not_a_delivery_mechanism": True,
        "recalled_records_count": len(evidence_items),
        "used_records_count": len(used_refs),
        "source_refs": search.get("source_refs") or [],
        "used_source_refs": used_refs,
        "library_ids": search.get("library_ids") or [],
        "used_library_ids": used_library_ids,
        "scope": scope or search.get("scope") or {},
        "compacted": True,
        "raw_expand_available": bool(search.get("raw_available")),
        "gaps": gaps,
        "conflicts": conflicts,
        "unknown_boundary": bool(think.get("unknown") or str(think.get("answer") or "").upper() == "UNKNOWN" or gaps),
        "answer_owner": think.get("owner") or think.get("think_owner") or "",
        "final_evidence_authority": "raw_source_refs",
    }


def build_delivery_receipt_view_model(
    receipt: dict[str, Any] | None = None,
    *,
    max_source_refs: int = 3,
    max_gaps: int = 3,
    max_conflicts: int = 3,
) -> dict[str, Any]:
    """Build a compact front-end projection of a delivery receipt.

    This is only a display contract. It does not fetch raw records, deliver
    context to a platform, call a model, or write a receipt.
    """

    value = _dict(receipt)
    used_count = int(value.get("used_records_count") or 0)
    recalled_count = int(value.get("recalled_records_count") or 0)
    unknown = bool(value.get("unknown_boundary", False))
    gaps = _items(value.get("gaps"))[:max_gaps]
    conflicts = _items(value.get("conflicts"))[:max_conflicts]
    raw_expand_available = bool(value.get("raw_expand_available", False))
    if unknown:
        status = "unknown"
        headline_code = "unknown_boundary_visible"
    elif used_count:
        status = "source_backed"
        headline_code = "answered_with_memory_sources"
    elif recalled_count:
        status = "memory_recalled_not_used"
        headline_code = "memory_recalled_but_not_used"
    else:
        status = "no_memory_used"
        headline_code = "no_memory_evidence_used"
    return {
        "ok": True,
        "contract": DELIVERY_RECEIPT_VIEW_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "not_a_delivery_mechanism": True,
        "projection_only": True,
        "status": status,
        "headline_code": headline_code,
        "answer_id": str(value.get("answer_id") or ""),
        "answer_owner": str(value.get("answer_owner") or ""),
        "unknown_boundary": unknown,
        "counts": {
            "recalled_records": recalled_count,
            "used_records": used_count,
            "visible_source_refs": min(max_source_refs, len(_items(value.get("source_refs")))),
            "gaps": len(gaps),
            "conflicts": len(conflicts),
        },
        "library_ids": [str(item) for item in _items(value.get("library_ids")) if str(item)],
        "used_library_ids": [str(item) for item in _items(value.get("used_library_ids")) if str(item)],
        "used_source_refs": [str(item) for item in _items(value.get("used_source_refs")) if str(item)],
        "visible_used_source_refs": _flatten_refs(value.get("used_source_refs"), limit=max_source_refs),
        "visible_source_refs": _flatten_refs(value.get("source_refs"), limit=max_source_refs),
        "gaps": [str(item) for item in gaps],
        "conflicts": [str(item) for item in conflicts],
        "raw_expand_available": raw_expand_available,
        "actions": {
            "expand_raw": {
                "available": raw_expand_available,
                "requires_source_refs": True,
                "write_performed": False,
            },
            "inspect_sources": {
                "available": bool(value.get("source_refs") or value.get("used_source_refs")),
                "write_performed": False,
            },
        },
        "scope": _dict(value.get("scope")),
        "final_evidence_authority": "raw_source_refs",
    }


__all__ = [
    "DELIVERY_RECEIPT_CONTRACT",
    "DELIVERY_RECEIPT_VIEW_CONTRACT",
    "build_delivery_receipt",
    "build_delivery_receipt_view_model",
]
