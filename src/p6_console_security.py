#!/usr/bin/env python3
"""P6 console action security gate under Tiandao jurisdiction."""

from __future__ import annotations

import ipaddress
import secrets
import urllib.parse

CONSOLE_SECURITY_CONTRACT = "tiandao_console_action_gate.v1"


def get_console_security_contract():
    return {
        "ok": True,
        "contract": CONSOLE_SECURITY_CONTRACT,
        "zh_name": "人间入口动作门禁",
        "en_name": "Console Action Gate",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "console_layer": "action_security_gate",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "security_gate_never_creates_or_replaces_raw_origin",
        "guarded_by": ["loopback_client", "host_origin_check", "local_console_token"],
        "lan_policy": "lan_entrypoints_must_be_explicit_and_tokened_elsewhere",
    }


def _is_loopback_host(host: str) -> bool:
    raw = str(host or "").strip()
    if not raw:
        return False
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if raw.lower() == "localhost":
        return True
    try:
        parsed = ipaddress.ip_address(raw)
    except ValueError:
        return False
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped:
        return bool(mapped.is_loopback)
    return bool(parsed.is_loopback)


def _is_loopback_client(client_address) -> bool:
    if isinstance(client_address, (list, tuple)) and client_address:
        return _is_loopback_host(str(client_address[0]))
    return _is_loopback_host(str(client_address or ""))


def _request_host_name(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw if "://" in raw else f"http://{raw}")
    return parsed.hostname or ""


def _same_origin_or_local(origin: str, host_header: str) -> bool:
    if not origin:
        return True
    origin_host = _request_host_name(origin)
    request_host = _request_host_name(host_header)
    if not origin_host:
        return False
    if _is_loopback_host(origin_host):
        return True
    return bool(request_host and origin_host.lower() == request_host.lower())


SENSITIVE_ACTION_POST_PATHS = {
    "/api/v1/source-systems/claude_desktop/raw-ingest",
    "/api/v1/records/guardian/backfill",
    "/api/v1/platforms/authorized-auto-connect/apply",
    "/api/v1/zhiyi/model-binding/apply",
    "/api/v1/hermes/native-learning/self-review/receipts",
    "/api/v1/hermes/native-learning/self-review/trigger",
    "/api/v1/hermes/native-learning/skill-generation/probe",
    "/api/v1/hermes/native-learning/skill-artifact-status/record",
    "/api/v1/hermes/native-learning/autonomous-loop/run",
    "/api/v1/hermes/native-learning/self-review/report/record",
    "/api/v1/hermes/consumption-receipts",
    "/api/v1/zhixing/replay/feedback-candidates/apply",
    "/api/v1/openclaw/chat-send/authorized",
    "/api/v1/update/download",
    "/api/v1/update/one-click",
    "/api/v1/update/source",
    "/api/v1/source-systems/local_files/ingest",
    "/api/v1/update/plan",
    "/api/v1/update/apply",
}

SENSITIVE_ACTION_POST_PREFIX_SUFFIXES = (
    ("/api/v1/zhiyi/experiences/", "/recycle"),
    ("/api/v1/zhiyi/experiences/", "/restore"),
    ("/api/v1/hermes/feedback-candidates/", "/actions"),
    ("/api/v1/xingce/work-experience-candidates/", "/actions"),
    ("/api/v1/experience-service/xingce-candidates/", "/adopt"),
    ("/api/v1/experience-service/case-memories/", "/rollback"),
    ("/api/v1/experience-service/hermes-upgrade-inputs/", "/apply"),
)


def _action_post_requires_console_token(path: str) -> bool:
    parsed_path = urllib.parse.urlparse(str(path or "")).path
    if parsed_path in SENSITIVE_ACTION_POST_PATHS:
        return True
    return any(
        parsed_path.startswith(prefix) and parsed_path.endswith(suffix)
        for prefix, suffix in SENSITIVE_ACTION_POST_PREFIX_SUFFIXES
    )


def _strict_action_post_allowed(headers, client_address, console_token: str = "") -> bool:
    if not _is_loopback_client(client_address):
        return False
    host = str(headers.get("Host", "") if headers else "").strip()
    if host and not _is_loopback_host(_request_host_name(host)):
        return False
    origin = str(headers.get("Origin", "") if headers else "").strip()
    if origin and not _same_origin_or_local(origin, host):
        return False
    provided = str(headers.get("X-Memcore-Console-Token", "") if headers else "").strip()
    return secrets.compare_digest(provided, str(console_token or ""))


def _browser_post_allowed(headers, client_address, console_token: str = "") -> bool:
    if not _is_loopback_client(client_address):
        return False
    origin = str(headers.get("Origin", "") if headers else "").strip()
    host = str(headers.get("Host", "") if headers else "").strip()
    if origin and not _same_origin_or_local(origin, host):
        return False
    if origin:
        provided = str(headers.get("X-Memcore-Console-Token", "") if headers else "").strip()
        return secrets.compare_digest(provided, str(console_token or ""))
    return True
