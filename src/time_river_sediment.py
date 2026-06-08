#!/usr/bin/env python3
"""Time river sediment helpers.

The sediment link is a read-only descriptor that connects derived Zhiyi,
Xingce, Toolbook, and Errata records back to the raw origin event. It does not
write raw records, platform config, or production memory.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

try:
    from tiandao.memory_routing import (
        TIANDAO_TIME_ORIGIN_CONTRACT,
        TIANDAO_TIME_RIVER_CONTRACT,
        TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT,
        time_river_sediment_contract_descriptor,
    )
except ImportError:  # pragma: no cover
    from src.tiandao.memory_routing import (
        TIANDAO_TIME_ORIGIN_CONTRACT,
        TIANDAO_TIME_RIVER_CONTRACT,
        TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT,
        time_river_sediment_contract_descriptor,
    )


SEDIMENT_STATUS_ORIGIN_LINKED = "origin_linked"
SEDIMENT_STATUS_SOURCE_REFS_ONLY = "source_refs_only"
SEDIMENT_STATUS_ORIGIN_MISSING_CANDIDATE = "origin_missing_candidate"
SEDIMENT_STATUS_RAW_UNAVAILABLE_UNTRUSTED = "raw_unavailable_untrusted"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return str(value)


def _parse_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _origin_event_from_record(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("origin_event", "time_origin", "raw_origin_event"):
        value = record.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _source_refs_from_record(record: dict[str, Any]) -> dict[str, Any]:
    refs = _parse_dict(record.get("_source_refs") or record.get("source_refs") or {})
    if refs:
        return refs
    source_path = _safe_str(record.get("source_path"))
    raw_path = _safe_str(record.get("raw_path") or record.get("raw_session_path"))
    if not source_path and not raw_path:
        return {}
    refs = {
        "source_system": record.get("source_system", ""),
        "computer_name": record.get("computer_name", ""),
        "canonical_window_id": record.get("canonical_window_id", ""),
        "session_id": record.get("session_id", ""),
        "source_path": source_path,
        "raw_session_path": raw_path,
        "artifact_type": record.get("artifact_type", ""),
    }
    return {key: value for key, value in refs.items() if value not in ("", None, [])}


def _merged_source_refs(record: dict[str, Any], origin_event: dict[str, Any]) -> dict[str, Any]:
    refs = _source_refs_from_record(record)
    origin_refs = _parse_dict(origin_event.get("source_refs") or {})
    merged = dict(origin_refs)
    merged.update({key: value for key, value in refs.items() if value not in ("", None, [])})
    for key in ("source_path", "raw_path"):
        value = _safe_str(origin_event.get(key))
        if value:
            merged.setdefault("raw_session_path" if key == "raw_path" else key, value)
    return merged


def sediment_status_for(*, source_refs: dict[str, Any], origin_event: dict[str, Any]) -> str:
    origin_status = _safe_str(origin_event.get("origin_status"))
    if origin_status == "origin_witnessed" and source_refs:
        return SEDIMENT_STATUS_ORIGIN_LINKED
    if origin_status in ("lost_raw", "origin_unavailable"):
        return SEDIMENT_STATUS_RAW_UNAVAILABLE_UNTRUSTED
    if source_refs:
        return SEDIMENT_STATUS_SOURCE_REFS_ONLY
    return SEDIMENT_STATUS_ORIGIN_MISSING_CANDIDATE


def sediment_status_label(status: str) -> str:
    if status == SEDIMENT_STATUS_ORIGIN_LINKED:
        return "起源已挂接"
    if status == SEDIMENT_STATUS_SOURCE_REFS_ONLY:
        return "仅有回源线索"
    if status == SEDIMENT_STATUS_RAW_UNAVAILABLE_UNTRUSTED:
        return "raw 不可用，未受信"
    return "起源缺失候选"


def _stable_sediment_id(
    *,
    library_id: str,
    sediment_layer: str,
    source_refs: dict[str, Any],
    origin_event: dict[str, Any],
    record: dict[str, Any],
) -> str:
    basis = "|".join([
        _safe_str(library_id),
        _safe_str(sediment_layer),
        _safe_str(origin_event.get("origin_id")),
        _safe_str(source_refs.get("source_system")),
        _safe_str(source_refs.get("session_id")),
        _safe_str(source_refs.get("source_path")),
        _safe_str(source_refs.get("raw_session_path")),
        _safe_str(record.get("summary")),
        _safe_str(record.get("exp_id") or record.get("memory_id")),
    ])
    return "sediment_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def get_time_river_sediment_contract() -> dict[str, Any]:
    payload = time_river_sediment_contract_descriptor()
    payload.update({
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
    })
    return payload


def build_sediment_link(
    record: dict[str, Any] | None,
    *,
    library_id: str = "",
    sediment_layer: str = "",
    source_refs: dict[str, Any] | None = None,
    origin_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = dict(record or {})
    origin = dict(origin_event or _origin_event_from_record(item))
    refs = dict(source_refs or _merged_source_refs(item, origin))
    layer = _safe_str(sediment_layer or item.get("library_shelf") or item.get("shelf") or "zhiyi")
    lib_id = _safe_str(library_id or item.get("library_id") or item.get("exp_id") or item.get("memory_id"))
    status = sediment_status_for(source_refs=refs, origin_event=origin)
    origin_id = _safe_str(origin.get("origin_id") or item.get("origin_id"))
    trusted = status == SEDIMENT_STATUS_ORIGIN_LINKED
    raw_available = trusted or bool(
        refs.get("raw_session_path")
        or item.get("verbatim_excerpt")
        or item.get("raw_excerpt")
        or origin.get("raw_exists")
    )
    return {
        "contract": TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT,
        "time_origin_contract": TIANDAO_TIME_ORIGIN_CONTRACT,
        "time_river_contract": TIANDAO_TIME_RIVER_CONTRACT,
        "sediment_id": _stable_sediment_id(
            library_id=lib_id,
            sediment_layer=layer,
            source_refs=refs,
            origin_event=origin,
            record=item,
        ),
        "sediment_layer": layer,
        "library_id": lib_id,
        "source_refs": refs,
        "source_refs_available": bool(refs),
        "origin_id": origin_id,
        "origin_status": _safe_str(origin.get("origin_status") or item.get("origin_status")),
        "origin_status_label": _safe_str(origin.get("origin_label") or item.get("origin_label")),
        "origin_event_available": bool(origin),
        "sediment_status": status,
        "sediment_status_label": sediment_status_label(status),
        "trusted_sediment": trusted,
        "raw_available": bool(raw_available),
        "candidate_until_origin_linked": not trusted,
        "raw_authority_policy": "raw_source_text_is_highest_authority",
        "summary_policy": "summaries_are_navigation_not_source_replacement",
        "origin_link_policy": "derived_sediment_must_reference_origin",
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "created_at": _safe_str(item.get("created_at") or item.get("extracted_at") or ""),
        "audited_at": ts(),
    }


def build_time_river_sediment_dry_run(body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(body or {})
    record = payload.get("record") if isinstance(payload.get("record"), dict) else payload
    origin_event = payload.get("origin_event") if isinstance(payload.get("origin_event"), dict) else None
    link = build_sediment_link(
        record,
        library_id=_safe_str(payload.get("library_id")),
        sediment_layer=_safe_str(payload.get("sediment_layer")),
        origin_event=origin_event,
    )
    return {
        "ok": True,
        "dry_run": True,
        "read_only": True,
        "contract": TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT,
        "time_origin_contract": TIANDAO_TIME_ORIGIN_CONTRACT,
        "time_river_contract": TIANDAO_TIME_RIVER_CONTRACT,
        "sediment": link,
        "trusted_sediment": link["trusted_sediment"],
        "sediment_status": link["sediment_status"],
        "raw_authority_policy": link["raw_authority_policy"],
        "summary_policy": link["summary_policy"],
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
    }
