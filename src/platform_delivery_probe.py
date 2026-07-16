"""Findings-only live probe for platform delivery liveness.

The probe may call the local raw gateway in work_preflight mode to observe
read-only source-ref delivery shape. It never sends chat to a platform, never
writes platform configuration, never calls a model, and never treats a local
preflight response as proof that a platform model received the evidence.
"""

from __future__ import annotations

import json
import time
import urllib.request

try:
    from src.port_discovery import resolve_client_url
except Exception:
    from port_discovery import resolve_client_url
from datetime import datetime, timezone
from typing import Any

try:
    from src.platform_autodiscovery import build_autodiscovery
    from src.platform_delivery_liveness import build_platform_delivery_liveness_audit
except Exception:  # pragma: no cover - direct script import fallback
    from platform_autodiscovery import build_autodiscovery
    from platform_delivery_liveness import build_platform_delivery_liveness_audit


PLATFORM_DELIVERY_PROBE_CONTRACT = "platform_delivery_liveness_probe.v2026.6.21"
WORK_PREFLIGHT_PROBE_CONTRACT = "platform_delivery_work_preflight_probe.v2026.6.21"
DEFAULT_WORK_PREFLIGHT_ENDPOINT = ""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _compact_text(value: Any, limit: int = 300) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _compact_surface(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "library_id": str(item.get("library_id") or ""),
        "library_shelf": str(item.get("library_shelf") or item.get("shelf") or ""),
        "title": _compact_text(item.get("title") or item.get("summary"), 160),
        "summary": _compact_text(item.get("summary") or item.get("detail"), 360),
        "rank_reason": _compact_text(item.get("rank_reason"), 200),
        "matched_by": item.get("matched_by") if isinstance(item.get("matched_by"), list) else [],
        "source_system": str(item.get("source_system") or ""),
        "source_path": str(item.get("source_path") or ""),
        "msg_ids": item.get("msg_ids") if isinstance(item.get("msg_ids"), list) else [],
        "byte_offsets": item.get("byte_offsets") if isinstance(item.get("byte_offsets"), dict) else {},
        "line_offsets": item.get("line_offsets") if isinstance(item.get("line_offsets"), dict) else {},
        "session_id": str(item.get("session_id") or ""),
        "canonical_window_id": str(item.get("canonical_window_id") or ""),
        "source_refs_canonical_window_id": str(item.get("source_refs_canonical_window_id") or ""),
        "raw_evidence_status": str(item.get("raw_evidence_status") or ""),
        "artifact_type": str(item.get("artifact_type") or ""),
        "score": item.get("score"),
    }


def _compact_surfaces(value: Any, *, limit: int = 3) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    surfaces = [_compact_surface(item) for item in value[:limit]]
    return [item for item in surfaces if item]


def _platforms(value: Any) -> tuple[str, ...] | None:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
        return tuple(items) or None
    if isinstance(value, (list, tuple)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return tuple(items) or None
    return None


def _work_preflight_request(body: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "mode": "work_preflight",
        "query": str(body.get("query") or body.get("work_preflight_query") or "继续，开工前先查已有机制"),
        "consumer": str(body.get("consumer") or "platform-delivery-liveness-probe"),
        "source_system": str(body.get("source_system") or ""),
        "limit": _int(body.get("limit") or body.get("work_preflight_limit"), 3),
        "excerpt_chars": _int(body.get("excerpt_chars") or body.get("work_preflight_excerpt_chars"), 180),
    }
    for key in (
        "session_id",
        "canonical_window_id",
        "project_id",
        "project_root",
        "workstream_id",
        "task_id",
        "request_id",
    ):
        if body.get(key) not in (None, ""):
            payload[key] = str(body.get(key))
    if body.get("deep_work_preflight") not in (None, ""):
        payload["deep_work_preflight"] = _bool(body.get("deep_work_preflight"))
    return payload


def _run_work_preflight_probe(body: dict[str, Any]) -> dict[str, Any]:
    configured_endpoint = str(body.get("endpoint") or body.get("work_preflight_endpoint") or DEFAULT_WORK_PREFLIGHT_ENDPOINT)
    try:
        endpoint = resolve_client_url("/api/v1/raw/query", endpoint=configured_endpoint)
    except RuntimeError:
        endpoint = configured_endpoint
    timeout = float(body.get("timeout_seconds") or body.get("work_preflight_timeout_seconds") or 6)
    request_payload = _work_preflight_request(body)
    started = time.perf_counter()
    try:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(request_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_response = json.loads(response.read().decode("utf-8"))
        ok = bool(raw_response.get("ok"))
        error = ""
    except Exception as exc:
        raw_response = {}
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    receipt = _dict(raw_response.get("consumer_receipt"))
    return {
        "contract": WORK_PREFLIGHT_PROBE_CONTRACT,
        "ok": ok,
        "read_only": True,
        "findings_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "not_platform_delivery_proof": True,
        "endpoint": endpoint,
        "timeout_seconds": timeout,
        "elapsed_ms": elapsed_ms,
        "request": {
            "mode": "work_preflight",
            "consumer": request_payload.get("consumer", ""),
            "source_system": request_payload.get("source_system", ""),
            "has_session_id": bool(request_payload.get("session_id")),
            "has_canonical_window_id": bool(request_payload.get("canonical_window_id")),
            "canonical_window_id": str(request_payload.get("canonical_window_id") or ""),
            "has_project_anchor": bool(request_payload.get("project_id") or request_payload.get("project_root")),
            "deep_work_preflight": bool(request_payload.get("deep_work_preflight", False)),
        },
        "response": {
            "ok": bool(raw_response.get("ok")),
            "mode": raw_response.get("mode", ""),
            "contract": raw_response.get("contract", ""),
            "classification": raw_response.get("classification", ""),
            "decision": raw_response.get("decision", ""),
            "recall_status": raw_response.get("recall_status", ""),
            "memory_scope": raw_response.get("memory_scope", ""),
            "memory_base_scope": raw_response.get("memory_base_scope", ""),
            "scope_missing": bool(raw_response.get("scope_missing", False)),
            "cross_window_read": bool(raw_response.get("cross_window_read", False)),
            "cross_window_read_allowed": bool(raw_response.get("cross_window_read_allowed", True)),
            "active_layers_used": raw_response.get("active_layers_used") or [],
            "source_refs_count": _int(raw_response.get("source_refs_count") or receipt.get("source_refs_count")),
            "raw_items_count": _int(raw_response.get("raw_items_count") or receipt.get("raw_items_count")),
            "raw_excerpt_returned": bool(raw_response.get("raw_excerpt_returned", False)),
            "fast_window_preflight": raw_response.get("fast_window_preflight"),
            "fast_recall_path": raw_response.get("fast_recall_path", ""),
            "library_index_projection_used": bool(raw_response.get("library_index_projection_used", False)),
            "library_index_projection_refs_count": _int(raw_response.get("library_index_projection_refs_count")),
            "must_surface": _compact_surfaces(raw_response.get("must_surface")),
            "do_not_repeat": [_compact_text(item, 220) for item in raw_response.get("do_not_repeat", [])[:6]] if isinstance(raw_response.get("do_not_repeat"), list) else [],
            "acceptance_checks": [_compact_text(item, 220) for item in raw_response.get("acceptance_checks", [])[:6]] if isinstance(raw_response.get("acceptance_checks"), list) else [],
            "library_index_projection_refs": _compact_surfaces(raw_response.get("library_index_projection_refs")),
            "consumer_receipt": {
                "receipt_scope": receipt.get("receipt_scope", ""),
                "used_library_ids": receipt.get("used_library_ids", []) if isinstance(receipt.get("used_library_ids"), list) else [],
                "source_refs_count": _int(receipt.get("source_refs_count")),
                "raw_items_count": _int(receipt.get("raw_items_count")),
                "read_only": bool(receipt.get("read_only", True)),
                "write_performed": bool(receipt.get("write_performed", False)),
            },
        },
        "error": error,
        "limitations": [
            "work_preflight_observes_local_memory_entry_shape_only",
            "source_refs_count_does_not_prove_platform_model_received_evidence",
            "no_platform_chat_delivery_was_attempted",
        ],
    }


def _preflight_payload_from_probe(probe: dict[str, Any]) -> dict[str, Any]:
    response = _dict(probe.get("response"))
    return {
        "contract": response.get("contract", ""),
        "mode": response.get("mode", "work_preflight"),
        "decision": response.get("decision", ""),
        "classification": response.get("classification", ""),
        "recall_status": response.get("recall_status", ""),
        "memory_scope": response.get("memory_scope", ""),
        "memory_base_scope": response.get("memory_base_scope", ""),
        "scope_missing": bool(response.get("scope_missing", False)),
        "cross_window_read": bool(response.get("cross_window_read", False)),
        "cross_window_read_allowed": bool(response.get("cross_window_read_allowed", True)),
        "active_layers_used": response.get("active_layers_used") or [],
        "source_refs_count": _int(response.get("source_refs_count")),
        "raw_items_count": _int(response.get("raw_items_count")),
        "raw_excerpt_returned": bool(response.get("raw_excerpt_returned", False)),
        "fast_window_preflight": response.get("fast_window_preflight"),
        "fast_recall_path": response.get("fast_recall_path", ""),
        "library_index_projection_used": bool(response.get("library_index_projection_used", False)),
        "library_index_projection_refs_count": _int(response.get("library_index_projection_refs_count")),
    }


def build_platform_delivery_liveness_probe(
    body: dict[str, Any] | None = None,
    *,
    runtime_profile: dict[str, Any] | None = None,
    memcore_root: Any = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    platforms = _platforms(body.get("platforms") or body.get("delivery_liveness_platforms"))
    autodiscovery = _dict(body.get("autodiscovery_payload")) or build_autodiscovery(
        runtime_profile,
        include_generic=_bool(body.get("include_generic"), False),
    )
    should_run_work_preflight = body.get("run_work_preflight", True) is not False
    work_probe = (
        _run_work_preflight_probe(body)
        if should_run_work_preflight
        else {
            "contract": WORK_PREFLIGHT_PROBE_CONTRACT,
            "ok": False,
            "skipped": True,
            "read_only": True,
            "findings_only": True,
            "write_performed": False,
            "platform_write_performed": False,
            "model_call_performed": False,
            "not_platform_delivery_proof": True,
            "response": {},
            "limitations": ["work_preflight_probe_skipped_by_request"],
        }
    )
    preflight_payload = _dict(body.get("preflight_payload")) or _preflight_payload_from_probe(work_probe)
    audit = build_platform_delivery_liveness_audit(
        autodiscovery_payload=autodiscovery,
        preflight_payload=preflight_payload,
        dialog_result=_dict(body.get("dialog_result")),
        observed_platforms=_dict(body.get("observed_platforms") or body.get("delivery_observations")),
        platforms=platforms,
        memcore_root=memcore_root,
    )
    return {
        "ok": bool(audit.get("ok")),
        "contract": PLATFORM_DELIVERY_PROBE_CONTRACT,
        "created_at": _now(),
        "phase": "phase0_findings_only_live_probe",
        "read_only": True,
        "findings_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "platform_chat_delivery_attempted": False,
        "not_a_delivery_mechanism": True,
        "not_a_model_answerer": True,
        "work_preflight_probe_performed": bool(should_run_work_preflight),
        "work_preflight_probe": work_probe,
        "autodiscovery": autodiscovery,
        "platform_delivery_liveness": audit,
        "final_evidence_authority": "raw_source_refs",
        "limitations": [
            "connection_signal_is_not_delivery_proof",
            "work_preflight_source_refs_are_local_entry_evidence_not_platform_model_receipt",
            "live_platform_chat_delivery_probe_requires_separate_explicit_platform_action_authorization",
        ],
        "next_action": audit.get("next_action", "resolve_phase0_delivery_findings_before_search_think_work"),
    }


__all__ = [
    "PLATFORM_DELIVERY_PROBE_CONTRACT",
    "WORK_PREFLIGHT_PROBE_CONTRACT",
    "DEFAULT_WORK_PREFLIGHT_ENDPOINT",
    "build_platform_delivery_liveness_probe",
]
