#!/usr/bin/env python3
"""stdio bridge for Codex -> Yifanchen MCP.

Codex can register HTTP MCP servers directly, but direct HTTP does not carry
the current Codex thread/session identity. This bridge keeps recall anchored by
injecting `consumer=codex`, `memory_scope=active`, and the current session or
window id when Codex exposes one through the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from claude_desktop_mcp_bridge import (
    DEFAULT_RECALL_EXCERPT_CHARS,
    DEFAULT_RECALL_LIMIT,
    DEFAULT_TIMEOUT_SECONDS,
    _compact_consumer_receipt,
    _compact_item,
    _compact_tiandao_context_package,
    _is_jsonrpc_response,
    _is_zhiyi_recall_call,
    _mcp_error,
    _normalize_jsonrpc_response,
    _read_message,
    _truncate,
    _write_message,
)


MAX_COMPACT_ITEMS = 5
DEFAULT_BINDING_KEYS = ("codex", "codex_cli")


def _log(message: str) -> None:
    print(f"[yifanchen-codex-mcp] {message}", file=sys.stderr, flush=True)


def _window_binding_registry_path(explicit: str = "") -> Path:
    value = str(explicit or os.environ.get("MEMCORE_WINDOW_BINDING_REGISTRY") or "").strip()
    if value:
        return Path(value).expanduser()
    root = str(os.environ.get("MEMCORE_ROOT") or "").strip()
    if root:
        return Path(root).expanduser() / "config" / "window_binding_registry.json"
    try:
        return Path(__file__).resolve().parents[1] / "config" / "window_binding_registry.json"
    except Exception:
        return Path("config") / "window_binding_registry.json"


def _current_window_binding_from_registry(
    *,
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, str]:
    path = _window_binding_registry_path(registry_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"canonical_window_id": "", "session_id": ""}
    current_windows = data.get("current_windows") if isinstance(data, dict) else {}
    if not isinstance(current_windows, dict):
        return {"canonical_window_id": "", "session_id": ""}
    keys: list[str] = []
    for key in (
        binding_key,
        os.environ.get("MEMCORE_CODEX_BINDING_KEY"),
        *DEFAULT_BINDING_KEYS,
    ):
        text = str(key or "").strip().lower().replace("-", "_")
        if text and text not in keys:
            keys.append(text)
    for key in keys:
        entry = current_windows.get(key)
        if not isinstance(entry, dict):
            continue
        session_id = str(entry.get("session_id") or "").strip()
        canonical_window_id = str(entry.get("canonical_window_id") or "").strip()
        if canonical_window_id or session_id:
            return {
                "canonical_window_id": canonical_window_id,
                "session_id": session_id,
            }
    return {"canonical_window_id": "", "session_id": ""}


def _current_window_binding(
    *,
    canonical_window_id: str = "",
    session_id: str = "",
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, str]:
    explicit_canonical = str(
        canonical_window_id
        or os.environ.get("MEMCORE_CODEX_CANONICAL_WINDOW_ID")
        or ""
    ).strip()
    explicit_session = str(
        session_id
        or os.environ.get("MEMCORE_CODEX_SESSION_ID")
        or os.environ.get("MEMCORE_CODEX_THREAD_ID")
        or os.environ.get("CODEX_THREAD_ID")
        or ""
    ).strip()
    if explicit_canonical or explicit_session:
        return {
            "canonical_window_id": explicit_canonical,
            "session_id": explicit_session,
        }
    registry_binding = _current_window_binding_from_registry(
        registry_path=registry_path,
        binding_key=binding_key,
    )
    if registry_binding["canonical_window_id"] or registry_binding["session_id"]:
        return registry_binding
    return {"canonical_window_id": "", "session_id": ""}


def _budget_zhiyi_request(
    data: dict[str, Any],
    *,
    canonical_window_id: str = "",
    session_id: str = "",
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, Any]:
    if not _is_zhiyi_recall_call(data):
        return data
    params = dict(data.get("params") if isinstance(data.get("params"), dict) else {})
    args = dict(params.get("arguments") if isinstance(params.get("arguments"), dict) else {})
    mode = str(args.get("mode") or "").strip().lower()
    if mode == "capability_check" or args.get("capability_check") or args.get("no_recall"):
        return data
    args.setdefault("consumer", "codex")
    args.setdefault("memory_scope", "active")
    binding = _current_window_binding(
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        registry_path=registry_path,
        binding_key=binding_key,
    )
    if binding["canonical_window_id"]:
        args.setdefault("canonical_window_id", binding["canonical_window_id"])
    if binding["session_id"]:
        args.setdefault("session_id", binding["session_id"])
    args.setdefault("limit", DEFAULT_RECALL_LIMIT)
    args.setdefault("excerpt_chars", DEFAULT_RECALL_EXCERPT_CHARS)
    params["arguments"] = args
    budgeted = dict(data)
    budgeted["params"] = params
    return budgeted


def _compact_recall_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mode") == "capability_check":
        keys = (
            "ok",
            "mode",
            "service",
            "server",
            "version",
            "source",
            "read_only",
            "write_performed",
            "platform_write_performed",
            "recall_performed",
            "raw_excerpt_returned",
            "raw_query_path",
            "mcp_path",
            "mcp_tools",
            "matched_count",
            "source_refs_count",
            "raw_items_count",
        )
        compact = {key: payload.get(key) for key in keys if key in payload}
        compact["consumer_receipt"] = _compact_consumer_receipt(payload.get("consumer_receipt"))
        return compact

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    compact = {
        "ok": payload.get("ok"),
        "consumer": payload.get("consumer"),
        "query": payload.get("query"),
        "source_system_filter": payload.get("source_system_filter"),
        "memory_scope": payload.get("memory_scope"),
        "memory_base_scope": payload.get("memory_base_scope"),
        "scope_missing": payload.get("scope_missing"),
        "recall_status": payload.get("recall_status"),
        "window_binding_hint": payload.get("window_binding_hint"),
        "missing_scope_fields": payload.get("missing_scope_fields"),
        "cross_window_read": payload.get("cross_window_read"),
        "cross_window_read_allowed": payload.get("cross_window_read_allowed"),
        "canonical_window_id_filter": payload.get("canonical_window_id_filter"),
        "project_id_filter": payload.get("project_id_filter"),
        "project_root_filter": payload.get("project_root_filter"),
        "workstream_id_filter": payload.get("workstream_id_filter"),
        "task_id_filter": payload.get("task_id_filter"),
        "current_window_binding_applied": payload.get("current_window_binding_applied"),
        "current_window_binding_key": payload.get("current_window_binding_key"),
        "current_window_binding_fields": payload.get("current_window_binding_fields"),
        "active_layers_used": payload.get("active_layers_used"),
        "agent_boundary": payload.get("agent_boundary"),
        "injection_boundary": payload.get("injection_boundary"),
        "tiandao_context_package_valid": payload.get("tiandao_context_package_valid"),
        "tiandao_context_package": _compact_tiandao_context_package(payload.get("tiandao_context_package")),
        "recall_performed": payload.get("recall_performed"),
        "raw_excerpt_returned": payload.get("raw_excerpt_returned"),
        "matched_count": payload.get("matched_count"),
        "source_refs_count": payload.get("source_refs_count"),
        "raw_items_count": payload.get("raw_items_count"),
        "raw_evidence_status": payload.get("raw_evidence_status"),
        "zhiyi_experience_used_as_raw": payload.get("zhiyi_experience_used_as_raw"),
        "items": [_compact_item(item) for item in items[:MAX_COMPACT_ITEMS]],
        "response_budget": {
            "mode": "codex_compact",
            "items_returned": min(len(items), MAX_COMPACT_ITEMS),
            "items_available": len(items),
            "omitted_large_fields": ["zhixing_library", "hybrid_recall", "library_card", "typed_graph", "tiandao_context_package.matched_memories", "tiandao_context_package.raw_projection"],
        },
        "consumer_receipt": _compact_consumer_receipt(payload.get("consumer_receipt")),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _compact_zhiyi_response(response: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    if not _is_zhiyi_recall_call(request):
        return response
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    if result.get("isError"):
        return response
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        return response

    compact_payload = _compact_recall_payload(structured)
    compact_result = dict(result)
    compact_result["structuredContent"] = compact_payload
    compact_result["content"] = [
        {
            "type": "text",
            "text": json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":")),
        }
    ]
    compact_response = dict(response)
    compact_response["result"] = compact_result
    return compact_response


def _forward(
    endpoint: str,
    data: dict[str, Any],
    timeout: float,
    compact_recall: bool,
    *,
    canonical_window_id: str = "",
    session_id: str = "",
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, Any] | None:
    forwarded = (
        _budget_zhiyi_request(
            data,
            canonical_window_id=canonical_window_id,
            session_id=session_id,
            registry_path=registry_path,
            binding_key=binding_key,
        )
        if compact_recall
        else data
    )
    body = json.dumps(forwarded, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 202:
                return None
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
            return _normalize_jsonrpc_response(parsed, data.get("id"), raw[:200] or str(exc))
        except Exception:
            return _mcp_error(data.get("id"), -32603, raw[:200] or str(exc))
    except Exception as exc:
        return _mcp_error(
            data.get("id"),
            -32000,
            f"Yifanchen MCP gateway unavailable at {endpoint}: {type(exc).__name__}: {exc}",
        )
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return _mcp_error(data.get("id"), -32603, "Invalid gateway response")
        normalized = _normalize_jsonrpc_response(parsed, data.get("id"), "Invalid gateway JSON-RPC response")
        return _compact_zhiyi_response(normalized, data) if compact_recall else normalized
    except Exception:
        return _mcp_error(data.get("id"), -32603, "Invalid gateway JSON response")


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex stdio bridge for Yifanchen MCP")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9851/mcp")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--canonical-window-id",
        default="",
        help="Explicit Codex project/window id for window-scoped recall.",
    )
    parser.add_argument(
        "--session-id",
        default="",
        help="Explicit Codex thread/session id for window-scoped recall.",
    )
    parser.add_argument(
        "--window-binding-registry",
        default="",
        help="Path to Memcore Cloud window_binding_registry.json.",
    )
    parser.add_argument(
        "--binding-key",
        default="",
        help="Current-window registry key for this Codex bridge.",
    )
    parser.add_argument(
        "--full-recall-response",
        dest="compact_recall",
        action="store_false",
        help="Forward the full raw gateway recall payload instead of the compact payload.",
    )
    parser.set_defaults(compact_recall=True)
    args = parser.parse_args()

    _log(f"bridge started -> {args.endpoint} timeout={args.timeout}s compact_recall={args.compact_recall}")
    while True:
        data = _read_message()
        if data is None:
            return 0
        method = str(data.get("method") or "")
        if method == "__parse_error__":
            _write_message(_mcp_error(data.get("id"), -32700, "Parse error"))
            continue
        if method == "__invalid_request__":
            _write_message(_mcp_error(data.get("id"), -32600, "Invalid Request"))
            continue
        response = _forward(
            args.endpoint,
            data,
            args.timeout,
            args.compact_recall,
            canonical_window_id=args.canonical_window_id,
            session_id=args.session_id,
            registry_path=args.window_binding_registry,
            binding_key=args.binding_key,
        )
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())
