#!/usr/bin/env python3
"""OpenClaw chat-send console inlet under Tiandao platform-guard rules."""

from __future__ import annotations

import datetime
import uuid

OPENCLAW_CONSOLE_CONTRACT = "tiandao_openclaw_console_inlet.v1"


def get_openclaw_console_contract():
    return {
        "ok": True,
        "contract": OPENCLAW_CONSOLE_CONTRACT,
        "zh_name": "OpenClaw 活动作入口",
        "en_name": "OpenClaw Console Inlet",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "console_layer": "platform_guard_inlet",
        "read_only_by_default": True,
        "write_capable": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "openclaw_write_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "openclaw_inlet_may_trigger_platform_action_but_never_replaces_time_origin",
        "authorization_required": [
            "confirm_live_openclaw_chat_send",
            "confirm_openclaw_active_session_write",
            "confirm_no_memcore_raw_zhiyi_xingce_hermes_write",
            "operator",
            "reason",
        ],
    }


def _truthy(value):
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "confirmed", "confirm", "on"}
    return bool(value)


def _openclaw_chat_send_bool(value):
    return _truthy(value)


def _openclaw_chat_send_present(value):
    return bool(str(value or "").strip())


def _openclaw_chat_send_session_ms(session):
    if not isinstance(session, dict):
        return 0
    value = session.get("updatedAt")
    if value is None:
        value = session.get("updatedAtMs")
    try:
        return int(value or 0)
    except Exception:
        return 0


def _openclaw_chat_send_session_iso(ms):
    if not ms:
        return ""
    try:
        return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _openclaw_chat_send_parse_key(key):
    parts = str(key or "").split(":")
    result = {
        "agent_id": "",
        "session_id": "",
        "session_key_shape": "unknown",
        "canonical_window_id": "",
    }
    if len(parts) >= 3 and parts[0] == "agent":
        result["agent_id"] = parts[1]
        result["canonical_window_id"] = parts[1]
        result["session_id"] = ":".join(parts[2:])
        result["session_key_shape"] = parts[2] if parts[2] in ("chat", "cron", "dashboard") else "direct"
    return result


def _openclaw_chat_send_session_summary(session):
    key = str(session.get("key") or "") if isinstance(session, dict) else ""
    parsed = _openclaw_chat_send_parse_key(key)
    updated_ms = _openclaw_chat_send_session_ms(session)
    label = (
        session.get("displayName")
        or session.get("label")
        or parsed.get("session_id")
        or key
    )
    return {
        "key": key,
        "label": str(label or ""),
        "agent_id": parsed.get("agent_id", ""),
        "canonical_window_id": parsed.get("canonical_window_id", ""),
        "session_id": str(session.get("sessionId") or parsed.get("session_id", "")),
        "session_key_shape": parsed.get("session_key_shape", "unknown"),
        "kind": str(session.get("kind") or ""),
        "chat_type": str(session.get("chatType") or ""),
        "updated_at_ms": updated_ms,
        "updated_at": _openclaw_chat_send_session_iso(updated_ms),
        "model_provider": str(session.get("modelProvider") or ""),
        "model": str(session.get("model") or ""),
        "has_active_run": bool(session.get("hasActiveRun", False)),
        "total_tokens": session.get("totalTokens"),
        "total_tokens_fresh": bool(session.get("totalTokensFresh", False)),
        "ready_for_authorized_chat_send": bool(key and not session.get("hasActiveRun", False)),
    }


def query_openclaw_chat_send_targets(params=None, client_factory=None):
    """Read OpenClaw session targets for a future authorized chat.send."""
    params = params or {}
    try:
        page = max(1, int(params.get("page", 1)))
    except Exception:
        page = 1
    try:
        page_size = max(1, min(int(params.get("page_size", 12)), 50))
    except Exception:
        page_size = 12

    if client_factory is None:
        try:
            from openclaw_ws_rpc_client import OpenClawWsRpcClient
        except Exception:
            from src.openclaw_ws_rpc_client import OpenClawWsRpcClient
        client_factory = OpenClawWsRpcClient

    client = client_factory()
    try:
        if not client.connect(timeout=5):
            return {
                "ok": False,
                "read_only": True,
                "write_performed": False,
                "openclaw_chat_send_called": False,
                "openclaw_active_session_write": False,
                "openclaw_write_performed": False,
                "live_gateway_connected": False,
                "sessions_list_called": False,
                "ready_for_authorized_chat_send": False,
                "items": [],
                "total": 0,
                "error": "openclaw_connect_failed",
            }
        sessions_result = client.sessions_list(timeout=5)
        if not sessions_result.get("ok"):
            return {
                "ok": False,
                "read_only": True,
                "write_performed": False,
                "openclaw_chat_send_called": False,
                "openclaw_active_session_write": False,
                "openclaw_write_performed": False,
                "live_gateway_connected": True,
                "sessions_list_called": True,
                "ready_for_authorized_chat_send": False,
                "items": [],
                "total": 0,
                "openclaw_result": sessions_result,
                "error": "openclaw_sessions_list_failed",
            }
        raw_sessions = sessions_result.get("payload", {}).get("sessions", [])
        if not isinstance(raw_sessions, list):
            raw_sessions = []
        summaries = [
            _openclaw_chat_send_session_summary(session)
            for session in raw_sessions
            if isinstance(session, dict) and str(session.get("key") or "").strip() not in ("", "gateway", "unknown")
        ]
        summaries.sort(key=lambda item: item.get("updated_at_ms") or 0, reverse=True)
        start = (page - 1) * page_size
        items = summaries[start:start + page_size]
        ready_count = sum(1 for item in summaries if item.get("ready_for_authorized_chat_send"))
        return {
            "ok": True,
            "read_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_chat_send_called": False,
            "openclaw_active_session_write": False,
            "openclaw_write_performed": False,
            "memcore_config_write_performed": False,
            "live_gateway_connected": True,
            "sessions_list_called": True,
            "page": page,
            "page_size": page_size,
            "total": len(summaries),
            "ready_count": ready_count,
            "items": items,
            "ready_for_authorized_chat_send": ready_count > 0,
            "execution_endpoint": "/api/v1/openclaw/chat-send/authorized",
            "authorization_required": [
                "confirm_live_openclaw_chat_send",
                "confirm_openclaw_active_session_write",
                "confirm_no_memcore_raw_zhiyi_xingce_hermes_write",
                "operator",
                "reason",
            ],
            "request_required": ["session_key", "message", "idempotency_key"],
        }
    except Exception as exc:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "openclaw_chat_send_called": False,
            "openclaw_active_session_write": False,
            "openclaw_write_performed": False,
            "items": [],
            "total": 0,
            "ready_for_authorized_chat_send": False,
            "error": f"openclaw_chat_send_targets_failed:{str(exc)[:160]}",
        }
    finally:
        try:
            client.close()
        except Exception:
            pass


def apply_openclaw_chat_send_authorized(body=None, client_factory=None):
    """Execute OpenClaw chat.send only with explicit live authorization."""
    body = body or {}
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    session_key = str(body.get("session_key") or body.get("sessionKey") or "").strip()
    message = str(body.get("message") or "").strip()
    idempotency_key = str(body.get("idempotency_key") or body.get("idempotencyKey") or "").strip()

    def confirmed(name):
        return _openclaw_chat_send_bool(authorization.get(name, body.get(name)))

    def present(name):
        return _openclaw_chat_send_present(authorization.get(name, body.get(name)))

    authorization_checks = {
        "confirm_live_openclaw_chat_send": confirmed("confirm_live_openclaw_chat_send"),
        "confirm_openclaw_active_session_write": confirmed("confirm_openclaw_active_session_write"),
        "confirm_no_memcore_raw_zhiyi_xingce_hermes_write": confirmed("confirm_no_memcore_raw_zhiyi_xingce_hermes_write"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    request_checks = {
        "session_key_present": bool(session_key),
        "message_present": bool(message),
        "idempotency_key_present": bool(idempotency_key),
        "session_key_control_chars_absent": not any(ord(ch) < 32 for ch in session_key),
        "message_within_limit": len(message) <= 12000,
    }
    missing = [name for name, ok in authorization_checks.items() if not ok]
    request_failures = [name for name, ok in request_checks.items() if not ok]
    if missing or request_failures:
        return {
            "ok": False,
            "read_only": False,
            "write_capable": True,
            "write_performed": False,
            "openclaw_chat_send_called": False,
            "openclaw_active_session_write": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
            "memcore_config_write_performed": False,
            "authorization_complete": not missing,
            "authorization_missing": missing,
            "authorization_checks": authorization_checks,
            "request_checks": request_checks,
            "request_failures": request_failures,
            "error": "blocked_missing_authorization_or_request_fields",
        }

    if client_factory is None:
        try:
            from openclaw_ws_rpc_client import OpenClawWsRpcClient
        except Exception:
            from src.openclaw_ws_rpc_client import OpenClawWsRpcClient
        client_factory = OpenClawWsRpcClient

    import uuid
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = client_factory()
    try:
        if not client.connect(timeout=5):
            return {
                "ok": False,
                "read_only": False,
                "write_capable": True,
                "write_performed": False,
                "openclaw_chat_send_called": False,
                "openclaw_active_session_write": False,
                "openclaw_write_performed": False,
                "session_key": session_key,
                "error": "openclaw_connect_failed",
            }
        sessions_result = client.sessions_list(timeout=5)
        sessions = sessions_result.get("payload", {}).get("sessions", []) if sessions_result.get("ok") else []
        valid_keys = {str(item.get("key", "")) for item in sessions if isinstance(item, dict)}
        if session_key not in valid_keys:
            return {
                "ok": False,
                "read_only": False,
                "write_capable": True,
                "write_performed": False,
                "openclaw_chat_send_called": False,
                "openclaw_active_session_write": False,
                "openclaw_write_performed": False,
                "session_key": session_key,
                "available_sessions_count": len(valid_keys),
                "error": "session_key_not_found_in_openclaw_sessions",
            }
        result = client.chat_send(
            session_key=session_key,
            message=message,
            idempotency_key=idempotency_key or f"memcore-openclaw-{uuid.uuid4().hex}",
            timeout=30,
        )
        ok = bool(result.get("ok"))
        return {
            "ok": ok,
            "read_only": False,
            "write_capable": True,
            "write_performed": ok,
            "openclaw_chat_send_called": True,
            "openclaw_active_session_write": ok,
            "openclaw_write_performed": ok,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "memcore_config_write_performed": False,
            "session_key": session_key,
            "idempotency_key": idempotency_key,
            "created_at": now,
            "authorization_checks": authorization_checks,
            "request_checks": request_checks,
            "openclaw_result": result,
            "notes": [
                "live_openclaw_chat_send_authorized",
                "writes_openclaw_active_session_only_when_openclaw_returns_ok",
                "does_not_write_memcore_raw_zhiyi_xingce_hermes",
            ],
        }
    except Exception as exc:
        return {
            "ok": False,
            "read_only": False,
            "write_capable": True,
            "write_performed": False,
            "openclaw_chat_send_called": False,
            "openclaw_active_session_write": False,
            "openclaw_write_performed": False,
            "session_key": session_key,
            "error": f"openclaw_chat_send_failed:{str(exc)[:160]}",
        }
    finally:
        try:
            client.close()
        except Exception:
            pass

