#!/usr/bin/env python3
"""stdio bridge for Claude Desktop -> Yifanchen MCP.

Claude Desktop launches local MCP servers as child processes through
`claude_desktop_config.json`. Yifanchen's existing MCP endpoint lives on the
loopback raw gateway (`http://127.0.0.1:9851/mcp`), so this bridge keeps Claude
Desktop on the official local-server shape while reusing the same read-only
`zhiyi_recall` implementation.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_RECALL_LIMIT = 3
DEFAULT_RECALL_EXCERPT_CHARS = 240
MAX_COMPACT_ITEMS = 5
MAX_COMPACT_TEXT_CHARS = 1200


def _log(message: str) -> None:
    print(f"[yifanchen-claude-mcp] {message}", file=sys.stderr, flush=True)


def _read_message() -> dict[str, Any] | None:
    first = sys.stdin.buffer.readline()
    if not first:
        return None
    if first.startswith(b"Content-Length:"):
        try:
            length = int(first.split(b":", 1)[1].strip())
        except Exception:
            return {"jsonrpc": "2.0", "id": None, "method": "__parse_error__"}
        while True:
            line = sys.stdin.buffer.readline()
            if line in {b"\r\n", b"\n", b""}:
                break
        raw = sys.stdin.buffer.read(length)
    else:
        raw = first
    try:
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {"jsonrpc": "2.0", "id": None, "method": "__invalid_request__"}
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "method": "__parse_error__"}


def _write_message(data: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _mcp_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _truncate(value: Any, limit: int = MAX_COMPACT_TEXT_CHARS) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 15)] + "...[truncated]"


def _compact_consumer_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        return {}
    keys = (
        "consumer",
        "request_id",
        "consumed_at",
        "read_only",
        "write_performed",
        "platform_write_performed",
        "skill_write",
        "memory_write",
        "config_write",
        "items_count",
        "source_refs_count",
        "raw_items_count",
        "receipt_scope",
        "used_library_ids",
    )
    return {key: receipt.get(key) for key in keys if key in receipt}


def _compact_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in (
        "library_id",
        "library_shelf",
        "type",
        "memory_type",
        "exp_id",
        "source_system",
        "computer_name",
        "session_id",
        "native_session_key",
        "source_path",
        "msg_ids",
        "raw_evidence_status",
        "evidence_hash",
        "matched_by",
        "rank_reason",
    ):
        value = item.get(key)
        if value not in ("", None, [], {}):
            compact[key] = value
    for key in ("summary", "raw_excerpt"):
        if item.get(key):
            compact[key] = _truncate(item.get(key))
    if isinstance(item.get("project_status"), dict):
        compact["project_status"] = {
            key: item["project_status"].get(key)
            for key in (
                "artifact_type",
                "status",
                "project",
                "probe_id",
                "skill_artifact_status",
                "status_receipt_write_performed",
                "production_experience_write_performed",
                "raw_write_performed",
                "zhiyi_write_performed",
                "xingce_write_performed",
                "hermes_write_performed",
                "openclaw_write_performed",
            )
            if key in item["project_status"]
        }
    if isinstance(item.get("xingce_candidate"), dict):
        compact["xingce_candidate"] = {
            key: item["xingce_candidate"].get(key)
            for key in (
                "candidate_id",
                "candidate_type",
                "action_status",
                "lifecycle_status",
                "production_experience_write_performed",
                "raw_write_performed",
                "zhiyi_write_performed",
                "xingce_write_performed",
                "hermes_write_performed",
                "openclaw_write_performed",
            )
            if key in item["xingce_candidate"]
        }
    return compact


def _compact_capability_payload(payload: dict[str, Any]) -> dict[str, Any]:
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


def _compact_recall_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mode") == "capability_check" or payload.get("recall_performed") is False:
        return _compact_capability_payload(payload)

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    compact = {
        "ok": payload.get("ok"),
        "consumer": payload.get("consumer"),
        "query": payload.get("query"),
        "source_system_filter": payload.get("source_system_filter"),
        "memory_base_scope": payload.get("memory_base_scope"),
        "agent_boundary": payload.get("agent_boundary"),
        "injection_boundary": payload.get("injection_boundary"),
        "matched_count": payload.get("matched_count"),
        "source_refs_count": payload.get("source_refs_count"),
        "raw_items_count": payload.get("raw_items_count"),
        "raw_evidence_status": payload.get("raw_evidence_status"),
        "zhiyi_experience_used_as_raw": payload.get("zhiyi_experience_used_as_raw"),
        "items": [_compact_item(item) for item in items[:MAX_COMPACT_ITEMS]],
        "response_budget": {
            "mode": "claude_desktop_compact",
            "items_returned": min(len(items), MAX_COMPACT_ITEMS),
            "items_available": len(items),
            "omitted_large_fields": ["zhixing_library", "hybrid_recall", "library_card", "typed_graph"],
        },
        "consumer_receipt": _compact_consumer_receipt(payload.get("consumer_receipt")),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _is_zhiyi_recall_call(data: dict[str, Any]) -> bool:
    params = data.get("params") if isinstance(data.get("params"), dict) else {}
    return (
        str(data.get("method") or "") == "tools/call"
        and str(params.get("name") or "") == "zhiyi_recall"
    )


def _budget_zhiyi_request(data: dict[str, Any]) -> dict[str, Any]:
    if not _is_zhiyi_recall_call(data):
        return data
    params = dict(data.get("params") if isinstance(data.get("params"), dict) else {})
    args = dict(params.get("arguments") if isinstance(params.get("arguments"), dict) else {})
    mode = str(args.get("mode") or "").strip().lower()
    if mode == "capability_check" or args.get("capability_check") or args.get("no_recall"):
        return data
    args.setdefault("limit", DEFAULT_RECALL_LIMIT)
    args.setdefault("excerpt_chars", DEFAULT_RECALL_EXCERPT_CHARS)
    params["arguments"] = args
    budgeted = dict(data)
    budgeted["params"] = params
    return budgeted


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


def _forward(endpoint: str, data: dict[str, Any], timeout: float, compact_recall: bool) -> dict[str, Any] | None:
    forwarded = _budget_zhiyi_request(data) if compact_recall else data
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
            return parsed if isinstance(parsed, dict) else _mcp_error(data.get("id"), -32603, raw[:200])
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
        return _compact_zhiyi_response(parsed, data) if compact_recall else parsed
    except Exception:
        return _mcp_error(data.get("id"), -32603, "Invalid gateway JSON response")


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Desktop stdio bridge for Yifanchen MCP")
    parser.add_argument("--endpoint", default="http://127.0.0.1:9851/mcp")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--full-recall-response",
        dest="compact_recall",
        action="store_false",
        help="Forward the full raw gateway recall payload instead of the Claude Desktop compact payload.",
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
        response = _forward(args.endpoint, data, args.timeout, args.compact_recall)
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())
