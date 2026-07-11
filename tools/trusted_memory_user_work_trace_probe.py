#!/usr/bin/env python3
"""Trusted-memory probe for installed Zhiyi/Xingce records.

Installing/configuring Time Library is the authorization boundary for local
Zhiyi/Xingce record use. This probe still requires a scoped query so it does not
turn into a broad record sweep, and it reuses the same dialog answer path and
Definition-of-Proven trace shape as the controlled probes.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


PROBE_CONTRACT = "trusted_memory_user_work_trace_probe.v2026.6.21"
WORK_PREFLIGHT_EVIDENCE_PATH_CONTRACT = "trusted_memory_user_work_preflight_evidence_path.v2026.6.23"
ALLOWED_RECORD_KINDS = ("user_preference", "work_record")
USER_WORK_PROBE_RAW_FALLBACK_MAX_BYTES = 512 * 1024 * 1024
USER_WORK_PROBE_RAW_FALLBACK_MAX_LINES = 300000
USER_WORK_PROBE_RAW_FALLBACK_DEADLINE_SECONDS = 45
UNSUPPORTED_SOURCE_BACKED_VERDICTS = {
    "unknown",
    "insufficient_evidence",
    "model_error",
    "dry_run",
    "gated",
    "non_json_model_response",
}


def _model_config(args: argparse.Namespace | dict[str, Any]) -> dict[str, Any]:
    get = args.get if isinstance(args, dict) else lambda key, default=None: getattr(args, key, default)
    return {
        "enabled": True,
        "provider": get("provider") or "minimax",
        "confirm_live_model_call": True,
        "model": get("model") or os.environ.get("MINIMAX_MODEL") or os.environ.get("MINIMAX_CN_MODEL") or "MiniMax-M2.7-highspeed",
        "debug": True,
        "timeout_seconds": int(get("timeout_seconds") or 90),
    }


def _no_read_result(reason: str, missing: list[str]) -> dict[str, Any]:
    return {
        "ok": False,
        "contract": PROBE_CONTRACT,
        "status": reason,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "user_work_records_read": False,
        "platform_action_performed": False,
        "install_authorization_model": "installed_connection_is_authorization",
        "missing": missing,
        "cases": [],
        "reason": reason,
    }


def _scope_gate(
    *,
    scope_filter: str,
    source_query: str,
    unknown_query: str,
) -> dict[str, Any]:
    missing: list[str] = []
    if not str(scope_filter or "").strip():
        missing.append("--scope-filter")
    if not str(source_query or "").strip():
        missing.append("--source-query")
    if not str(unknown_query or "").strip():
        missing.append("--unknown-query")
    if missing:
        return _no_read_result("scope_and_queries_required", missing)
    return {"ok": True}


def _casefile_no_read_result(reason: str, *, casefile: str = "", details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result = _no_read_result(reason, [casefile] if casefile else [])
    result["casefile"] = casefile
    result["case_results"] = []
    result["case_count"] = 0
    if details:
        result["casefile_errors"] = details
    return result


def _load_casefile(casefile: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path = Path(casefile).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [], [{"case": "", "error": "casefile_unreadable", "detail": str(exc)}]
    except json.JSONDecodeError as exc:
        return [], [{"case": "", "error": "casefile_invalid_json", "detail": str(exc)}]

    if isinstance(payload, dict):
        raw_cases = payload.get("cases")
    else:
        raw_cases = payload
    if not isinstance(raw_cases, list):
        return [], [{"case": "", "error": "casefile_cases_must_be_list", "detail": ""}]

    cases: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, item in enumerate(raw_cases):
        if not isinstance(item, dict):
            errors.append({"case": str(index), "error": "case_must_be_object", "detail": ""})
            continue
        name = str(item.get("name") or item.get("case_id") or f"case_{index + 1}")
        record_kind = str(item.get("record_kind") or "").strip()
        scope_filter = str(item.get("scope_filter") or "").strip()
        source_query = str(item.get("source_query") or "").strip()
        unknown_query = str(item.get("unknown_query") or "").strip()
        missing = _scope_gate(
            scope_filter=scope_filter,
            source_query=source_query,
            unknown_query=unknown_query,
        )
        if not missing.get("ok"):
            errors.append({
                "case": name,
                "error": "scope_and_queries_required",
                "detail": ",".join(missing.get("missing", [])),
            })
            continue
        if record_kind not in ALLOWED_RECORD_KINDS:
            errors.append({
                "case": name,
                "error": "unsupported_record_kind",
                "detail": record_kind or "missing_record_kind",
            })
            continue
        cases.append({
            "name": name,
            "record_kind": record_kind,
            "observed_at": str(item.get("observed_at") or "").strip(),
            "evidence_command": str(item.get("evidence_command") or "").strip(),
            "expected_metrics": item.get("expected_metrics") if isinstance(item.get("expected_metrics"), dict) else {},
            "scope_filter": scope_filter,
            "source_query": source_query,
            "unknown_query": unknown_query,
            "gateway_url": str(item.get("gateway_url") or ""),
            "provider": str(item.get("provider") or ""),
            "model": str(item.get("model") or ""),
            "timeout_seconds": int(item.get("timeout_seconds") or 0),
        })
    return cases, errors


def _caller_scope_from_scope_filter(scope_filter: str) -> dict[str, str]:
    canonical_window_id = str(scope_filter or "").strip()
    if canonical_window_id.startswith("window/"):
        canonical_window_id = canonical_window_id[len("window/"):].strip()
    return {
        "canonical_window_id": canonical_window_id,
        "source_system": "trusted_memory_probe",
        "computer_id": "local",
    }


def _reset_dialog_modules() -> None:
    for name in ["config_loader", "src.config_loader", "dialog_entry_proxy", "src.dialog_entry_proxy"]:
        sys.modules.pop(name, None)


def _load_dialog_proxy(gateway_url: str = ""):
    _reset_dialog_modules()
    proxy = importlib.import_module("dialog_entry_proxy")
    if gateway_url:
        proxy.ZHIYI_GATEWAY_URL = gateway_url
    return proxy


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}, []):
        return []
    return [value]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _work_preflight_endpoint(gateway_url: str = "") -> str:
    raw = str(gateway_url or "").strip()
    if raw:
        return raw
    return os.environ.get("MEMCORE_RAW_QUERY_ENDPOINT", "").strip() or "http://127.0.0.1:9851/api/v1/raw/query"


def _work_preflight_request(query: str, scope_filter: str, timeout_seconds: int) -> dict[str, Any]:
    caller_scope = _caller_scope_from_scope_filter(scope_filter)
    return {
        "mode": "work_preflight",
        "query": query,
        "consumer": "trusted-memory-user-work-trace-probe",
        "source_system": "codex",
        "canonical_window_id": caller_scope.get("canonical_window_id", ""),
        "limit": 5,
        "excerpt_chars": 720,
        "deep_work_preflight": True,
        "force_raw_fallback": True,
        "raw_fallback_max_files": 20,
        "raw_fallback_max_bytes": USER_WORK_PROBE_RAW_FALLBACK_MAX_BYTES,
        "raw_fallback_max_lines": USER_WORK_PROBE_RAW_FALLBACK_MAX_LINES,
        "raw_fallback_deadline_seconds": min(
            max(int(timeout_seconds or 90), 1),
            USER_WORK_PROBE_RAW_FALLBACK_DEADLINE_SECONDS,
        ),
        "request_id": f"trusted-user-work-{int(time.time() * 1000)}",
        "timeout_seconds": int(timeout_seconds or 90),
    }


def _run_work_preflight(
    *,
    query: str,
    scope_filter: str,
    gateway_url: str = "",
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    endpoint = _work_preflight_endpoint(gateway_url)
    request_payload = _work_preflight_request(query, scope_filter, timeout_seconds)
    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=max(int(timeout_seconds or 90), 1)) as resp:
            response = json.loads(resp.read().decode("utf-8"))
        ok = bool(response.get("ok"))
        error = ""
    except Exception as exc:
        response = {}
        ok = False
        error = f"{type(exc).__name__}: {exc}"
    return {
        "ok": ok,
        "endpoint": endpoint,
        "request": {
            "mode": request_payload["mode"],
            "consumer": request_payload["consumer"],
            "source_system": request_payload["source_system"],
            "canonical_window_id": request_payload["canonical_window_id"],
            "deep_work_preflight": request_payload["deep_work_preflight"],
            "force_raw_fallback": request_payload["force_raw_fallback"],
            "limit": request_payload["limit"],
        },
        "response": response,
        "error": error,
    }


def _work_preflight_surfaces(response: dict[str, Any]) -> list[dict[str, Any]]:
    surfaces = [item for item in _items(response.get("items")) if isinstance(item, dict)]
    if surfaces:
        return surfaces
    surfaces = [item for item in _items(response.get("must_surface")) if isinstance(item, dict)]
    if not surfaces:
        surfaces = [item for item in _items(response.get("library_index_projection_refs")) if isinstance(item, dict)]
    if not surfaces:
        surfaces = [item for item in _items(response.get("evidence")) if isinstance(item, dict)]
    return surfaces


def _compact_evidence_from_work_preflight(response: dict[str, Any], *, query: str = "") -> dict[str, Any]:
    try:
        from src.source_ref_compact_evidence import build_source_ref_compact_evidence_probe
    except Exception:
        from source_ref_compact_evidence import build_source_ref_compact_evidence_probe

    surfaces = _work_preflight_surfaces(response)
    return build_source_ref_compact_evidence_probe(
        surfaces,
        limit=5,
        excerpt_chars=1200,
        memcore_root=os.environ.get("MEMCORE_ROOT", ""),
        query=str(query or response.get("query") or ""),
    )


def _model_config_for_evidence_bound_call(model_config: dict[str, Any]) -> dict[str, Any]:
    try:
        from src.evidence_bound_model import default_model_config
    except Exception:
        from evidence_bound_model import default_model_config

    cfg = default_model_config(
        provider=str(model_config.get("provider") or "minimax"),
        model=str(model_config.get("model") or ""),
    )
    return {
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "api_key_env": cfg.api_key_env,
        "timeout_seconds": int(model_config.get("timeout_seconds") or cfg.timeout_seconds or 90),
        "max_tokens": cfg.max_tokens,
    }


def _run_evidence_answer(
    *,
    query: str,
    evidence: list[dict[str, Any]],
    model_config: dict[str, Any],
) -> dict[str, Any]:
    try:
        from src.evidence_bound_model import run_evidence_bound_answer
    except Exception:
        from evidence_bound_model import run_evidence_bound_answer

    return run_evidence_bound_answer(
        query,
        evidence,
        task_kind="trusted_memory_user_work_answer",
        draft_answer="",
        model_config=_model_config_for_evidence_bound_call(model_config),
        execute=True,
        max_evidence_items=8,
    )


def _source_refs_for_support(evidence: list[dict[str, Any]], supporting_refs: list[str]) -> list[Any]:
    wanted = {str(ref) for ref in supporting_refs if str(ref)}
    refs: list[Any] = []
    seen: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            continue
        ids = {
            str(item.get("source_id") or ""),
            str(item.get("evidence_ref") or ""),
            str(item.get("library_id") or ""),
        }
        if not (wanted & ids):
            continue
        source_refs = item.get("source_refs")
        key = json.dumps(source_refs, ensure_ascii=False, sort_keys=True, default=str)
        if source_refs and key not in seen:
            refs.append(source_refs)
            seen.add(key)
    return refs


def _delivery_artifacts_for_result(
    *,
    query: str,
    ordinary: dict[str, Any],
    answer: str,
    model_result: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        from src.trusted_memory_delivery_trace import build_trusted_memory_delivery_artifacts
    except Exception:
        from trusted_memory_delivery_trace import build_trusted_memory_delivery_artifacts

    supporting_refs = [str(ref) for ref in _items(model_result.get("supporting_refs")) if str(ref)]
    evidence_packet_refs = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("evidence_ref") or item.get("source_id") or item.get("library_id") or "").strip()
        if ref and ref not in evidence_packet_refs:
            evidence_packet_refs.append(ref)
    dialog_result = {
        "status": "ok",
        "chain": "F3_zhiyi_direct",
        "handled": True,
        "answer": answer,
        "answer_source": "evidence_bound_model_call",
        "source_refs": _source_refs_for_support(evidence, supporting_refs),
        "used_source_refs": supporting_refs,
        "model_call": {
            "requested": True,
            "called": bool(model_result.get("model_call_performed")),
            "request_sent": bool(model_result.get("model_call_performed")),
            "model_verdict": model_result.get("verdict", ""),
            "model_confidence": model_result.get("confidence", 0.0),
            "model_validation_error": model_result.get("validation_error", ""),
            "unknown_reason": model_result.get("unknown_reason", ""),
            "supporting_refs": supporting_refs,
            "used_source_refs": supporting_refs,
            "evidence_packet_refs": evidence_packet_refs,
            "evidence_count": len(evidence),
        },
        "answer_debug": {
            "evidence": [
                {
                    "source_id": item.get("source_id", ""),
                    "evidence_ref": item.get("evidence_ref", ""),
                    "role": item.get("role", ""),
                    "timestamp": item.get("timestamp", ""),
                    "source_refs": item.get("source_refs") or {},
                }
                for item in evidence
                if isinstance(item, dict)
            ],
        },
    }
    return build_trusted_memory_delivery_artifacts(
        platform="trusted-memory-user-work-probe",
        question=query,
        dialog_result=dialog_result,
        observations={
            "passive_gate_result": ordinary,
            "security_gate": {
                "observed": True,
                "source": "trusted_memory_user_work_trace_probe",
                "tests": ["tests/test_security_boundaries.py", "tests/test_trusted_memory_delivery_trace.py"],
            },
        },
    )


def _run_source_ref_case(
    ordinary: dict[str, Any],
    *,
    case: str,
    query: str,
    scope_filter: str,
    gateway_url: str,
    model_config: dict[str, Any],
    include_answer: bool,
) -> dict[str, Any]:
    work_preflight = _run_work_preflight(
        query=query,
        scope_filter=scope_filter,
        gateway_url=gateway_url,
        timeout_seconds=int(model_config.get("timeout_seconds") or 90),
    )
    preflight_response = _dict(work_preflight.get("response"))
    compact_probe = _compact_evidence_from_work_preflight(preflight_response, query=query)
    evidence = [item for item in _items(compact_probe.get("items")) if isinstance(item, dict) and item.get("ok")]
    if evidence:
        model_result = _run_evidence_answer(
            query=query,
            evidence=evidence,
            model_config=model_config,
        )
    else:
        model_result = {
            "model_call_performed": False,
            "answer": "UNKNOWN",
            "verdict": "unknown",
            "confidence": 0.0,
            "supporting_refs": [],
            "validation_error": "",
            "unknown_reason": "no_work_preflight_source_ref_evidence",
        }
    answer = str(model_result.get("answer") or "UNKNOWN") or "UNKNOWN"
    artifacts = _delivery_artifacts_for_result(
        query=query,
        ordinary=ordinary,
        answer=answer,
        model_result=model_result,
        evidence=evidence,
    )
    trace = _dict(artifacts.get("trusted_memory_delivery_trace"))
    receipt_view = _dict(artifacts.get("delivery_receipt_view"))
    answer_is_unknown = answer.upper() == "UNKNOWN"
    supporting_refs = [str(ref) for ref in _items(model_result.get("supporting_refs")) if str(ref)]
    evidence_packet_refs = trace.get("evidence_packet_refs") or [
        str(item.get("evidence_ref") or item.get("source_id") or "")
        for item in evidence
        if str(item.get("evidence_ref") or item.get("source_id") or "")
    ]
    return {
        "case": case,
        "ordinary_handled": ordinary.get("handled"),
        "ordinary_reason": ordinary.get("reason"),
        "explicit_handled": True,
        "explicit_status": "ok",
        "explicit_error": work_preflight.get("error", ""),
        "answer_included": bool(include_answer or answer_is_unknown),
        "answer": answer if include_answer or answer_is_unknown else "",
        "answer_omitted": bool(answer and not include_answer and not answer_is_unknown),
        "answer_is_unknown": answer_is_unknown,
        "answer_source": "evidence_bound_model_call",
        "recall_count": int(preflight_response.get("matched_count") or len(evidence) or 0),
        "model_called": bool(model_result.get("model_call_performed")),
        "request_sent": bool(model_result.get("model_call_performed")),
        "model_verdict": model_result.get("verdict", ""),
        "model_validation_error": model_result.get("validation_error", ""),
        "unknown_reason": model_result.get("unknown_reason", ""),
        "evidence_packet_refs": evidence_packet_refs,
        "used_source_refs": supporting_refs,
        "source_refs_count": len(_source_refs_for_support(evidence, supporting_refs)),
        "receipt_status": receipt_view.get("status", ""),
        "unknown_boundary": receipt_view.get("unknown_boundary", False),
        "trace_status": trace.get("status"),
        "model_delivery_state": trace.get("model_delivery_state"),
        "missing_cells": trace.get("missing_cells", []),
        "cells": trace.get("cells", {}),
        "trusted_memory_probe_evidence_path": "work_preflight_source_ref_compact_evidence",
        "work_preflight": {
            "ok": bool(work_preflight.get("ok")),
            "endpoint": work_preflight.get("endpoint", ""),
            "request": work_preflight.get("request", {}),
            "response": {
                "ok": bool(preflight_response.get("ok")),
                "contract": preflight_response.get("contract", ""),
                "classification": preflight_response.get("classification", ""),
                "decision": preflight_response.get("decision", ""),
                "recall_status": preflight_response.get("recall_status", ""),
                "memory_scope": preflight_response.get("memory_scope", ""),
                "scope_missing": bool(preflight_response.get("scope_missing", False)),
                "matched_count": int(preflight_response.get("matched_count") or 0),
                "source_refs_count": int(preflight_response.get("source_refs_count") or 0),
                "raw_items_count": int(preflight_response.get("raw_items_count") or 0),
                "fast_window_preflight": preflight_response.get("fast_window_preflight"),
                "fast_recall_path": preflight_response.get("fast_recall_path", ""),
                "raw_fallback_used": bool(preflight_response.get("raw_fallback_used")),
                "raw_fallback_status": preflight_response.get("raw_fallback_status", ""),
                "raw_fallback_scanned_bytes": int(preflight_response.get("raw_fallback_scanned_bytes") or 0),
                "raw_fallback_scanned_lines": int(preflight_response.get("raw_fallback_scanned_lines") or 0),
                "raw_fallback_timed_out": bool(preflight_response.get("raw_fallback_timed_out")),
            },
            "error": work_preflight.get("error", ""),
        },
        "source_ref_compact_evidence": {
            "contract": compact_probe.get("contract", ""),
            "ok": bool(compact_probe.get("ok")),
            "items_count": int(compact_probe.get("items_count") or 0),
            "answer_bearing_items_count": int(compact_probe.get("answer_bearing_items_count") or 0),
            "raw_backtrace_hits_count": int(compact_probe.get("raw_backtrace_hits_count") or 0),
        },
        "contract": WORK_PREFLIGHT_EVIDENCE_PATH_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "platform_action_performed": False,
    }


def _summarize_case(case: str, ordinary: dict[str, Any], result: dict[str, Any], *, include_answer: bool) -> dict[str, Any]:
    trace = result.get("trusted_memory_delivery_trace", {}) if isinstance(result, dict) else {}
    model_call = result.get("model_call", {}) if isinstance(result, dict) else {}
    answer = str(result.get("answer") or "")
    answer_is_unknown = answer.upper() == "UNKNOWN"
    summary = {
        "case": case,
        "ordinary_handled": ordinary.get("handled"),
        "ordinary_reason": ordinary.get("reason"),
        "explicit_handled": result.get("handled"),
        "explicit_status": result.get("status", ""),
        "explicit_error": result.get("error", ""),
        "answer_included": bool(include_answer or answer_is_unknown),
        "answer": answer if include_answer or answer_is_unknown else "",
        "answer_omitted": bool(answer and not include_answer and not answer_is_unknown),
        "answer_is_unknown": answer_is_unknown,
        "answer_source": result.get("answer_source", ""),
        "recall_count": result.get("recall_count", 0),
        "model_called": model_call.get("called"),
        "request_sent": model_call.get("request_sent"),
        "model_verdict": model_call.get("model_verdict"),
        "model_validation_error": model_call.get("model_validation_error"),
        "unknown_reason": model_call.get("unknown_reason", ""),
        "evidence_packet_refs": model_call.get("evidence_packet_refs", []),
        "used_source_refs": result.get("used_source_refs", []),
        "source_refs_count": len(result.get("source_refs", []) if isinstance(result.get("source_refs"), list) else ([result.get("source_refs")] if result.get("source_refs") else [])),
        "receipt_status": result.get("delivery_receipt_view", {}).get("status", ""),
        "unknown_boundary": result.get("delivery_receipt_view", {}).get("unknown_boundary", False),
        "trace_status": trace.get("status"),
        "model_delivery_state": trace.get("model_delivery_state"),
        "missing_cells": trace.get("missing_cells", []),
        "cells": trace.get("cells", {}),
    }
    return summary


def _source_backed_verdict_is_supported(case: dict[str, Any]) -> bool:
    verdict = str(case.get("model_verdict") or "").strip().lower()
    validation_error = str(case.get("model_validation_error") or "").strip()
    if validation_error:
        return False
    if not verdict:
        return True
    return verdict not in UNSUPPORTED_SOURCE_BACKED_VERDICTS


def _run_case(
    handler: Any,
    *,
    case: str,
    query: str,
    scope_filter: str,
    gateway_url: str = "",
    model_config: dict[str, Any],
    include_answer: bool,
) -> dict[str, Any]:
    ordinary = handler.handle_openclaw_before_dispatch(
        {
            "message": f"ordinary chat for user-work {case} must pass through",
            "session_key": f"trusted-user-work-{case}",
            "channel": "trusted-memory-probe",
        }
    )
    return _run_source_ref_case(
        ordinary,
        case=case,
        query=query,
        scope_filter=scope_filter,
        gateway_url=gateway_url,
        model_config=model_config,
        include_answer=include_answer,
    )
    result = handler.handle_openclaw_before_dispatch(
        {
            "message": "/zhiyi " + query,
            "session_key": f"trusted-user-work-{case}",
            "channel": "trusted-memory-probe",
            "scope_filter": scope_filter,
            "caller_scope": _caller_scope_from_scope_filter(scope_filter),
            "model_call": model_config,
            "trusted_memory_trace": {
                "passive_gate_result": ordinary,
                "security_gate": {
                    "observed": True,
                    "source": "trusted_memory_user_work_trace_probe",
                    "tests": ["tests/test_security_boundaries.py", "tests/test_trusted_memory_delivery_trace.py"],
                },
            },
        }
    )
    return _summarize_case(case, ordinary, result, include_answer=include_answer)


def run_probe(
    *,
    scope_filter: str = "",
    source_query: str = "",
    unknown_query: str = "",
    gateway_url: str = "",
    provider: str = "minimax",
    model: str = "",
    timeout_seconds: int = 90,
    include_answer: bool = False,
) -> dict[str, Any]:
    gate = _scope_gate(
        scope_filter=scope_filter,
        source_query=source_query,
        unknown_query=unknown_query,
    )
    if not gate.get("ok"):
        return gate

    proxy = _load_dialog_proxy(gateway_url)
    proxy._flags = {**proxy.DEFAULT_FEATURE_FLAGS, "zhiyi_direct": True}
    proxy.ZHIYI_GATEWAY_TIMEOUT = max(int(timeout_seconds or 90), int(getattr(proxy, "ZHIYI_GATEWAY_TIMEOUT", 10) or 10))
    proxy.record_zhiyi_usage_log = lambda *_args, **_kwargs: {"usage_log_write_performed": False}
    proxy.audit_log = lambda *_args, **_kwargs: None
    proxy.remember_openclaw_before_dispatch_handled = lambda *_args, **_kwargs: {"ok": True, "write_performed": False}
    proxy.remember_openclaw_before_dispatch_raw = lambda *_args, **_kwargs: {"ok": True, "write_performed": False}
    handler = object.__new__(proxy.DialogEntryHandler)
    model_cfg = _model_config(
        {
            "provider": provider,
            "model": model,
            "timeout_seconds": timeout_seconds,
        }
    )
    cases = [
        _run_case(
            handler,
            case="source_backed",
            query=source_query,
            scope_filter=scope_filter,
            gateway_url=gateway_url,
            model_config=model_cfg,
            include_answer=include_answer,
        ),
        _run_case(
            handler,
            case="unknown",
            query=unknown_query,
            scope_filter=scope_filter,
            gateway_url=gateway_url,
            model_config=model_cfg,
            include_answer=include_answer,
        ),
    ]
    source_backed = next((item for item in cases if item.get("case") == "source_backed"), {})
    ok = all(
        item.get("ordinary_handled") is False
        and item.get("explicit_handled") is True
        and item.get("recall_count", 0) > 0
        and item.get("trace_status") == "proven"
        and item.get("model_delivery_state") == "observed"
        and not item.get("missing_cells")
        for item in cases
    )
    ok = (
        ok
        and source_backed.get("receipt_status") == "source_backed"
        and bool(source_backed.get("used_source_refs"))
        and _source_backed_verdict_is_supported(source_backed)
    )
    unknown = next((item for item in cases if item.get("case") == "unknown"), {})
    ok = ok and (
        unknown.get("answer_is_unknown") is True
        or str(unknown.get("answer") or "").upper() == "UNKNOWN"
    ) and unknown.get("unknown_boundary") is True
    return {
        "ok": ok,
        "contract": PROBE_CONTRACT,
        "status": "proven" if ok else "unproven",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": True,
        "user_work_records_read": True,
        "platform_action_performed": False,
        "install_authorization_model": "installed_connection_is_authorization",
        "authorized_scope_filter": scope_filter,
        "authorized_caller_scope": _caller_scope_from_scope_filter(scope_filter),
        "gateway_url": gateway_url or "default",
        "cases": cases,
        "limitations": [
            "install_probe_scope_is_limited_to_the_supplied_scope_filter",
            "one_authorized_install_trace_is_not_platform_wide_delivery_proof",
        ],
    }


def run_casefile(
    *,
    casefile: str | Path,
    gateway_url: str = "",
    provider: str = "minimax",
    model: str = "",
    timeout_seconds: int = 90,
    include_answer: bool = False,
) -> dict[str, Any]:
    """Run multiple scoped installed-record probes from a JSON casefile."""

    cases, errors = _load_casefile(casefile)
    if errors:
        return _casefile_no_read_result(
            "casefile_invalid",
            casefile=str(casefile),
            details=errors,
        )
    if not cases:
        return _casefile_no_read_result("casefile_empty", casefile=str(casefile))

    results: list[dict[str, Any]] = []
    for case in cases:
        result = run_probe(
            scope_filter=case["scope_filter"],
            source_query=case["source_query"],
            unknown_query=case["unknown_query"],
            gateway_url=case["gateway_url"] or gateway_url,
            provider=case["provider"] or provider,
            model=case["model"] or model,
            timeout_seconds=case["timeout_seconds"] or timeout_seconds,
            include_answer=include_answer,
        )
        result["casefile_case"] = case["name"]
        result["casefile_record_kind"] = case.get("record_kind", "")
        result["casefile_observed_at"] = case.get("observed_at", "")
        result["casefile_evidence_command"] = case.get("evidence_command", "")
        result["casefile_expected_metrics"] = case.get("expected_metrics", {})
        results.append(result)

    ok = bool(results) and all(item.get("ok") for item in results)
    record_kinds = sorted({
        str(item.get("casefile_record_kind") or "")
        for item in results
        if str(item.get("casefile_record_kind") or "")
    })
    scope_filters = sorted({
        str(item.get("authorized_scope_filter") or "")
        for item in results
        if str(item.get("authorized_scope_filter") or "")
    })
    return {
        "ok": ok,
        "contract": PROBE_CONTRACT,
        "status": "proven" if ok else "unproven",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": any(item.get("model_call_performed") for item in results),
        "user_work_records_read": any(item.get("user_work_records_read") for item in results),
        "platform_action_performed": any(item.get("platform_action_performed") for item in results),
        "install_authorization_model": "installed_connection_is_authorization",
        "casefile": str(casefile),
        "case_count": len(results),
        "scope_count": len(scope_filters),
        "scope_filters": scope_filters,
        "record_kinds": record_kinds,
        "case_results": results,
        "cases": [
            {
                **probe_case,
                "casefile_case": item.get("casefile_case", ""),
                "casefile_record_kind": item.get("casefile_record_kind", ""),
                "casefile_observed_at": item.get("casefile_observed_at", ""),
                "casefile_evidence_command": item.get("casefile_evidence_command", ""),
                "casefile_expected_metrics": item.get("casefile_expected_metrics", {}),
                "authorized_scope_filter": item.get("authorized_scope_filter", ""),
            }
            for item in results
            for probe_case in item.get("cases", [])
            if isinstance(probe_case, dict)
        ],
        "limitations": [
            "casefile_runs_multiple_scope_limited_installed_traces",
            "casefile_success_is_not_global_record_or_platform_wide_proof",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a scoped trusted-memory probe against installed Zhiyi/Xingce records.")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--casefile", default="", help="JSON file with scoped installed user/work probe cases")
    parser.add_argument("--scope-filter", default="", help="required scope/window filter; prevents broad record reads")
    parser.add_argument("--source-query", default="", help="required query expected to have enough evidence")
    parser.add_argument("--unknown-query", default="", help="required query expected to produce UNKNOWN from insufficient evidence")
    parser.add_argument("--gateway-url", default="", help="optional existing /inject gateway URL")
    parser.add_argument("--provider", default="minimax", help="evidence-bound model provider")
    parser.add_argument("--model", default="", help="model name override")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--include-answer", action="store_true", help="include non-UNKNOWN answer text in output")
    args = parser.parse_args()
    if args.casefile:
        result = run_casefile(
            casefile=args.casefile,
            gateway_url=args.gateway_url,
            provider=args.provider,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            include_answer=args.include_answer,
        )
    else:
        result = run_probe(
            scope_filter=args.scope_filter,
            source_query=args.source_query,
            unknown_query=args.unknown_query,
            gateway_url=args.gateway_url,
            provider=args.provider,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            include_answer=args.include_answer,
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("PASS" if result.get("ok") else "FAIL")
        if result.get("reason"):
            print(result["reason"])
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
