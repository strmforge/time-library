"""Read-only liveness probe for recall-before-judgment.

This probe checks whether an agent would see enough source-backed anchors
before making a product or engineering judgment. It does not answer, inject
context into a host platform, call a model, or write memory.
"""

from __future__ import annotations

import json
import hashlib
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

try:
    from src.source_system_runtime_declarations import default_work_preflight_source_system
except Exception:
    try:
        from source_system_runtime_declarations import default_work_preflight_source_system
    except Exception:
        default_work_preflight_source_system = None


RECALL_BEFORE_JUDGMENT_LIVENESS_CONTRACT = "recall_before_judgment_liveness.v2026.6.21"
DEFAULT_ENDPOINT = "http://127.0.0.1:9851/api/v1/raw/query"
DEFAULT_QUERY = "Trusted Memory 安装后的 scoped recall 权限边界是什么，哪些动作需要升级授权？"
DEFAULT_REQUIRED_TERMS = (
    "memory_authority_policy",
    "recall_only",
    "installed local trust boundary",
    "context_inject",
    "direct_answer",
    "platform_act",
    "投影不脱敏",
    "299_2026-06-21_TrustedMemory授权模型纠偏",
    "scope_and_queries_required",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


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


def _default_work_preflight_source_system() -> str:
    if default_work_preflight_source_system is None:
        return ""
    try:
        return str(default_work_preflight_source_system() or "").strip()
    except Exception:
        return ""


def _compact(value: Any, limit: int = 280) -> str:
    text = _text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _health_url_for_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint or DEFAULT_ENDPOINT)
    if not parsed.scheme or not parsed.netloc:
        parsed = urlparse(DEFAULT_ENDPOINT)
    return urlunparse((parsed.scheme, parsed.netloc, "/health", "", "", ""))


def _service_identity_diagnostic(body: dict[str, Any], call: dict[str, Any], timeout: float) -> dict[str, Any]:
    endpoint = str(call.get("endpoint") or body.get("endpoint") or DEFAULT_ENDPOINT)
    health_url = _health_url_for_endpoint(endpoint)
    health_timeout = min(max(float(timeout or 3), 0.5), 3.0)
    health: dict[str, Any] = {}
    error = ""
    try:
        request = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(request, timeout=health_timeout) as response:
            health = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        health = {}

    project_root = str(body.get("project_root") or "").strip()
    working_tree_source_path = ""
    working_tree_source_sha256 = ""
    if project_root:
        candidate = Path(project_root).expanduser().resolve() / "src" / "raw_consumption_gateway.py"
        working_tree_source_path = str(candidate)
        working_tree_source_sha256 = _sha256_file(candidate)

    service_source_sha256 = str(health.get("source_sha256") or "").strip()
    service_source_path = str(health.get("source_path") or "").strip()
    can_compare = bool(service_source_sha256 and working_tree_source_sha256)
    matches = service_source_sha256 == working_tree_source_sha256 if can_compare else None
    if can_compare and matches:
        status = "matches_working_tree"
    elif can_compare and not matches:
        status = "differs_from_working_tree"
    elif health.get("ok"):
        status = "working_tree_hash_unavailable"
    elif error:
        status = "health_unavailable"
    else:
        status = "not_checked"

    return {
        "service_health_checked": True,
        "service_health_url": health_url,
        "service_health_ok": bool(health.get("ok")),
        "service_health_error": error,
        "service_identity_contract": str(health.get("identity_contract") or ""),
        "service_name": str(health.get("service") or ""),
        "service_version": str(health.get("version") or ""),
        "service_source_path": service_source_path,
        "service_source_sha256": service_source_sha256,
        "working_tree_source_path": working_tree_source_path,
        "working_tree_source_sha256": working_tree_source_sha256,
        "service_source_matches_working_tree": matches,
        "service_source_status": status,
        "service_refresh_required": status == "differs_from_working_tree",
    }


def _required_terms(value: Any) -> list[str]:
    if isinstance(value, str):
        parsed = [item.strip() for item in value.split(",") if item.strip()]
        return parsed or list(DEFAULT_REQUIRED_TERMS)
    if isinstance(value, (list, tuple)):
        parsed = [str(item).strip() for item in value if str(item).strip()]
        return parsed or list(DEFAULT_REQUIRED_TERMS)
    return list(DEFAULT_REQUIRED_TERMS)


def _surface_text(surface: dict[str, Any]) -> str:
    parts = [
        surface.get("library_id"),
        surface.get("library_shelf"),
        surface.get("title"),
        surface.get("summary"),
        surface.get("required_terms"),
        surface.get("rank_reason"),
        surface.get("matched_by"),
        surface.get("source_system"),
        surface.get("source_path"),
        surface.get("raw_evidence_status"),
    ]
    return "\n".join(str(part or "") for part in parts)


def _source_ref_text(surface: dict[str, Any]) -> str:
    parts = [
        surface.get("source_system"),
        surface.get("source_path"),
        surface.get("session_id"),
        surface.get("canonical_window_id"),
        surface.get("source_refs_canonical_window_id"),
        surface.get("raw_evidence_status"),
    ]
    return "\n".join(str(part or "") for part in parts)


def _compact_surface(surface: dict[str, Any], required_terms: list[str]) -> dict[str, Any]:
    blob = (_surface_text(surface) + "\n" + _source_ref_text(surface)).lower()
    matched_terms = [term for term in required_terms if term.lower() in blob]
    return {
        "library_id": _text(surface.get("library_id")),
        "library_shelf": _text(surface.get("library_shelf") or surface.get("shelf")),
        "title": _compact(surface.get("title") or surface.get("summary"), 160),
        "summary": _compact(surface.get("summary") or surface.get("detail"), 360),
        "rank_reason": _compact(surface.get("rank_reason"), 220),
        "source_system": _text(surface.get("source_system")),
        "source_path": _text(surface.get("source_path")),
        "session_id": _text(surface.get("session_id")),
        "canonical_window_id": _text(surface.get("canonical_window_id")),
        "raw_evidence_status": _text(surface.get("raw_evidence_status")),
        "matched_required_terms": matched_terms,
        "has_source_ref": bool(_text(surface.get("source_path")) or _text(surface.get("source_system"))),
    }


def _surfaces_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    surfaces: list[dict[str, Any]] = []
    for key in ("must_surface", "evidence", "library_index_projection_refs"):
        for item in _items(response.get(key)):
            if isinstance(item, dict):
                surfaces.append(item)
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for surface in surfaces:
        marker = (
            _text(surface.get("library_id")),
            _text(surface.get("source_path")),
            _text(surface.get("session_id")),
        )
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(surface)
    return unique[:10]


def _call_work_preflight(body: dict[str, Any]) -> tuple[dict[str, Any], float, str]:
    endpoint = str(body.get("endpoint") or DEFAULT_ENDPOINT)
    timeout = float(body.get("timeout_seconds") or 8)
    request_payload = {
        "mode": "work_preflight",
        "query": str(body.get("query") or DEFAULT_QUERY),
        "consumer": str(body.get("consumer") or _default_work_preflight_source_system()),
        "source_system": str(body.get("source_system") or _default_work_preflight_source_system()),
        "limit": _int(body.get("limit"), 5),
        "excerpt_chars": _int(body.get("excerpt_chars"), 220),
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
            request_payload[key] = str(body.get(key))
    if body.get("deep_work_preflight") not in (None, ""):
        request_payload["deep_work_preflight"] = _bool(body.get("deep_work_preflight"))
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
        error = ""
    except Exception as exc:
        raw_response = {}
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    return {
        "endpoint": endpoint,
        "timeout_seconds": timeout,
        "payload": request_payload,
        "response": raw_response,
    }, elapsed_ms, error


def build_recall_before_judgment_liveness(
    body: dict[str, Any] | None = None,
    *,
    work_preflight_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    required_terms = _required_terms(body.get("required_terms"))
    called = work_preflight_response is None
    call: dict[str, Any] = {}
    elapsed_ms = 0.0
    error = ""
    if called:
        call, elapsed_ms, error = _call_work_preflight(body)
        response = _dict(call.get("response"))
    else:
        response = _dict(work_preflight_response)
    surfaces = _surfaces_from_response(response)
    compact_surfaces = [_compact_surface(surface, required_terms) for surface in surfaces]
    all_matched_terms = sorted({term for surface in compact_surfaces for term in surface["matched_required_terms"]})
    missing_terms = [term for term in required_terms if term not in all_matched_terms]
    source_ref_count = _int(response.get("source_refs_count") or _dict(response.get("consumer_receipt")).get("source_refs_count"))
    raw_items_count = _int(response.get("raw_items_count") or _dict(response.get("consumer_receipt")).get("raw_items_count"))
    surfaced = str(response.get("decision") or "") == "surface" or bool(response.get("should_intervene"))
    has_source_refs = bool(source_ref_count or any(surface.get("has_source_ref") for surface in compact_surfaces))
    service_identity = _service_identity_diagnostic(
        body,
        call,
        float(_dict(call.get("payload")).get("timeout_seconds") or body.get("timeout_seconds") or 3),
    ) if called else {
        "service_health_checked": False,
        "service_refresh_required": False,
        "service_source_matches_working_tree": None,
        "service_source_status": "not_checked",
    }
    matched_authoritative_anchor = bool(all_matched_terms) and not missing_terms
    if not bool(response.get("ok")):
        status = "work_preflight_unavailable"
    elif not surfaced:
        status = "not_surfaced_before_judgment"
    elif matched_authoritative_anchor:
        status = "authoritative_anchor_surfaced"
    elif has_source_refs:
        status = "weak_anchor_surfaced"
    else:
        status = "source_refs_missing"

    ok = status == "authoritative_anchor_surfaced"
    return {
        "ok": ok,
        "contract": RECALL_BEFORE_JUDGMENT_LIVENESS_CONTRACT,
        "created_at": _now(),
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
        "status": status,
        "query": str(body.get("query") or response.get("query") or DEFAULT_QUERY),
        "required_terms": required_terms,
        "matched_required_terms": all_matched_terms,
        "missing_required_terms": missing_terms,
        "elapsed_ms": elapsed_ms,
        "work_preflight_called": called,
        "work_preflight_ok": bool(response.get("ok")),
        "work_preflight_contract": response.get("contract", ""),
        "decision": response.get("decision", ""),
        "classification": response.get("classification", ""),
        "recall_status": response.get("recall_status", ""),
        "memory_scope": response.get("memory_scope", ""),
        "fast_window_preflight": response.get("fast_window_preflight"),
        "fast_recall_path": response.get("fast_recall_path", ""),
        "source_refs_count": source_ref_count,
        "raw_items_count": raw_items_count,
        "surfaces_count": len(compact_surfaces),
        "surfaces": compact_surfaces[:5],
        "call_request": {
            "endpoint": call.get("endpoint", ""),
            "mode": _dict(call.get("payload")).get("mode", "work_preflight"),
            "consumer": _dict(call.get("payload")).get("consumer", ""),
            "source_system": _dict(call.get("payload")).get("source_system", ""),
            "has_session_id": bool(_dict(call.get("payload")).get("session_id")),
            "has_canonical_window_id": bool(_dict(call.get("payload")).get("canonical_window_id")),
            "canonical_window_id": _dict(call.get("payload")).get("canonical_window_id", ""),
            "has_project_anchor": bool(_dict(call.get("payload")).get("project_id") or _dict(call.get("payload")).get("project_root")),
            "deep_work_preflight": bool(_dict(call.get("payload")).get("deep_work_preflight")),
        },
        "service_identity": service_identity,
        "service_refresh_required": bool(service_identity.get("service_refresh_required")),
        "service_source_status": service_identity.get("service_source_status", ""),
        "error": error,
        "diagnosis": (
            "recall_before_judgment_surfaced_authoritative_boundary"
            if ok
            else "preflight_returned_source_refs_but_not_the_required_authoritative_boundary"
            if status == "weak_anchor_surfaced"
            else status
        ),
        "next_action": (
            "keep_using_preflight_before_judgment"
            if ok
            else "inspect_indexing_scope_or_add_authoritative_boundary_anchors_to_the_preflight_surface"
            if status == "weak_anchor_surfaced"
            else "wire_or_repair_work_preflight_before_claiming_agent_memory_liveness"
        ),
        "boundary": {
            "passive_read_only_preflight": True,
            "automatic_answer_injection": False,
            "local_answer_synthesis": False,
            "source_refs_are_required_for_judgment": True,
            "strong_liveness_requires_authoritative_anchor": True,
        },
    }


__all__ = [
    "DEFAULT_QUERY",
    "DEFAULT_REQUIRED_TERMS",
    "RECALL_BEFORE_JUDGMENT_LIVENESS_CONTRACT",
    "build_recall_before_judgment_liveness",
]
