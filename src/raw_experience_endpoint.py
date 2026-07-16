#!/usr/bin/env python3
"""Read-only HTTP endpoint for cross-agent raw experience provider.

GET /raw-experience/pack
  ?consumer=<self-reported-client-id>
  &source_system=<explicit-source-id>
  &limit=5
  &include_raw_excerpt=true|false

Returns structured raw experience pack.
Does NOT write Hermes skill/memory, OpenClaw session, or production data.
"""
from __future__ import annotations

import json
import os
import hmac
import ipaddress
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.raw_direct_experience_pool import build_raw_direct_pack, query_raw_direct

PORT = 9860
DEFAULT_HOST = "127.0.0.1"
MAX_LIMIT = 20
DEFAULT_LIMIT = 5
TOKEN_ENV = "MEMCORE_PROVIDER_TOKEN"


def _is_loopback_host(host):
    value = str(host or "").strip()
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _validate_bind_security(host):
    if _is_loopback_host(host) or os.environ.get(TOKEN_ENV, "").strip():
        return
    raise RuntimeError(
        f"{TOKEN_ENV} is required when raw experience binds beyond loopback"
    )


def _path_segment(value, *, field, allow_empty=False):
    segment = str(value or "")
    if allow_empty and not segment:
        return ""
    if (
        not segment
        or len(segment) > 255
        or segment in {".", ".."}
        or "/" in segment
        or "\\" in segment
        or "\x00" in segment
    ):
        raise ValueError(f"invalid_path_segment:{field}")
    return segment


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path not in {"/raw-experience/direct-query", "/raw-experience/pack"}:
            self._json(404, {"ok": False, "error": "not_found"})
            return

        if not self._authorized():
            return
        self._handle_direct_query(qs)

    def _authorized(self):
        expected = os.environ.get(TOKEN_ENV, "").strip()
        if not expected:
            return True
        auth = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not auth.startswith(prefix):
            self._json(401, {"ok": False, "error": "missing_bearer_token"})
            return False
        supplied = auth[len(prefix):].strip()
        if not hmac.compare_digest(supplied, expected):
            self._json(403, {"ok": False, "error": "invalid_bearer_token"})
            return False
        return True

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        pass

    def _handle_direct_query(self, qs):
        query_hint = qs.get("query_hint", [""])[0]
        try:
            consumer = _path_segment(
                (qs.get("consumer") or ["unknown"])[0] or "unknown",
                field="consumer",
            )
            requested_source_system = (qs.get("source_system") or [""])[0]
            if not requested_source_system:
                raise ValueError("source_system_required_no_consumer_inference")
            source_system = _path_segment(
                requested_source_system,
                field="source_system",
            )
            computer_name = _path_segment(
                qs.get("computer_name", ["local"])[0],
                field="computer_name",
            )
            canonical_window_id = _path_segment(
                qs.get("canonical_window_id", [""])[0],
                field="canonical_window_id",
                allow_empty=True,
            )
        except ValueError as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return
        session_id = qs.get("session_id", [""])[0]
        try:
            limit = min(int(qs.get("limit", [5])[0]), 20)
        except (ValueError, TypeError):
            limit = 5
        try:
            excerpt_chars = min(int(qs.get("excerpt_chars", [400])[0]), 800)
        except (ValueError, TypeError):
            excerpt_chars = 400
        items = query_raw_direct(
            query_hint=query_hint, source_system=source_system,
            computer_name=computer_name, canonical_window_id=canonical_window_id,
            session_id=session_id, consumer=consumer,
            limit=limit, excerpt_chars=excerpt_chars)
        if qs.get("include_raw_excerpt", ["true"])[0].lower() != "true":
            for item in items:
                item.pop("raw_excerpt", None)
        pack = build_raw_direct_pack(items, consumer=consumer, query_hint=query_hint)
        pack["ok"] = True
        pack["read_only"] = True
        pack["production_write"] = False
        self._json(200, pack)

    def do_POST(self):
        self._json(405, {"ok": False, "error": "read_only_endpoint"})


def run(port=PORT, host=DEFAULT_HOST):
    _validate_bind_security(host)
    server = HTTPServer((host, port), Handler)
    auth_mode = "token_required" if os.environ.get(TOKEN_ENV, "").strip() else "dev_no_token"
    print(f"[raw-experience-endpoint] listening on {host}:{port}")
    print(f"[raw-experience-endpoint] GET /raw-experience/pack")
    print(f"[raw-experience-endpoint] not_skill_gate=true not_skill_writer=true")
    print(f"[raw-experience-endpoint] auth={auth_mode}")
    server.serve_forever()


if __name__ == "__main__":
    run()
