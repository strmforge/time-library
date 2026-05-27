#!/usr/bin/env python3
"""Read-only HTTP endpoint for cross-agent raw experience provider.

GET /raw-experience/pack
  ?consumer=hermes|openclaw|codex|unknown
  &runtime_mode=auto|mixed_n100_windows|wsl_all_in_one|...
  &limit=5
  &include_raw_excerpt=true|false

Returns structured raw experience pack.
Does NOT write Hermes skill/memory, OpenClaw session, or production data.
"""
from __future__ import annotations

import json
import os
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.raw_direct_experience_pool import (
    query_raw_direct, build_raw_direct_pack,
)
from src.raw_experience_provider import (filter_items_for_consumer,filter_items_for_consumer,
    build_raw_experience_pack, build_item,
    CONSUMER_HERMES, CONSUMER_OPENCLAW, CONSUMER_CODEX, CONSUMER_UNKNOWN,
    EVENT_FAILURE, EVENT_CORRECTION, EVENT_SELF_FIX, EVENT_SUCCESS,
    NOISE_USEFUL, NOISE_FAILED, NOISE_CORRECTION,
)

PORT = 9860
DEFAULT_HOST = "127.0.0.1"
MAX_LIMIT = 20
DEFAULT_LIMIT = 5
TOKEN_ENV = "MEMCORE_PROVIDER_TOKEN"


def _sample_hermes_items():
    return [
        build_item("WSL venv creation failed: ensurepip not available. Required: apt install python3-venv.", source_system="hermes", event_type=EVENT_FAILURE, noise_label=NOISE_FAILED),
        build_item("sudo apt-get install -y python3-venv python3-pip resolved the issue.", source_system="hermes", event_type=EVENT_CORRECTION, noise_label=NOISE_CORRECTION),
        build_item("Apt lock held by background update, waited 30s, retried successfully.", source_system="hermes", event_type=EVENT_SELF_FIX, noise_label=NOISE_USEFUL),
        build_item("7/7 modules syntax check passed (config_loader, memcore-cloud, p2_extract, runtime_topology, zhiyi_gateway, dialog_entry_proxy, dialog_intent_router).", source_system="hermes", event_type=EVENT_SUCCESS, noise_label=NOISE_USEFUL),
        build_item("SMB /mnt/Y/ not accessible from WSL. Workaround: use /mnt/c/ for cross-mount file transfer.", source_system="hermes", event_type=EVENT_SELF_FIX, noise_label=NOISE_USEFUL),
    ]


def _sample_openclaw_items():
    return [
        build_item("OpenClaw session archive extracted successfully via P2 incremental extract.", source_system="openclaw", event_type=EVENT_SUCCESS, noise_label=NOISE_USEFUL),
        build_item("Checkpoint offset tracking works: 38 JSONL files tracked with offset/last_update.", source_system="openclaw", event_type=EVENT_SUCCESS, noise_label=NOISE_USEFUL),
        build_item("Gateway 18789 health check failed initially due to timeout, retry succeeded.", source_system="openclaw", event_type=EVENT_FAILURE, noise_label=NOISE_FAILED),
    ]


FIXTURE_MAP = {
    CONSUMER_HERMES: _sample_hermes_items,
    CONSUMER_OPENCLAW: _sample_openclaw_items,
    CONSUMER_CODEX: _sample_hermes_items,
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/raw-experience/direct-query":
            self._handle_direct_query(qs)
            return
        if parsed.path != "/raw-experience/pack":
            self._json(404, {"ok": False, "error": "not_found"})
            return

        if not self._authorized():
            return

        consumer = qs.get("consumer", [CONSUMER_UNKNOWN])[0]
        if consumer not in (CONSUMER_HERMES, CONSUMER_OPENCLAW, CONSUMER_CODEX, CONSUMER_UNKNOWN):
            consumer = CONSUMER_UNKNOWN

        try:
            limit = min(int(qs.get("limit", [DEFAULT_LIMIT])[0]), MAX_LIMIT)
        except (ValueError, TypeError):
            limit = DEFAULT_LIMIT

        include_raw = qs.get("include_raw_excerpt", ["true"])[0].lower() == "true"
        query_hint = qs.get("query_hint", [""])[0]
        source_system = qs.get("source_system", [""])[0]
        noise_filter = qs.get("noise_filter", [""])[0]
        since = qs.get("since", [""])[0]

        fixture_fn = FIXTURE_MAP.get(consumer, _sample_hermes_items)
        items = fixture_fn()
        items = filter_items_for_consumer(items, consumer, query_hint, source_system, noise_filter, since)
        items = items[:limit]

        if not include_raw:
            for item in items:
                item.pop("raw_excerpt", None)

        pack = build_raw_experience_pack(items, consumer=consumer)
        pack["ok"] = True
        pack["production_write"] = False
        del pack["_production_write"]
        del pack["_hermes_skill_write"]
        del pack["_openclaw_session_write"]

        self._json(200, pack)

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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        pass

    def _handle_direct_query(self, qs):
        query_hint = qs.get("query_hint", [""])[0]
        consumer = (qs.get("consumer") or [""])[0]
        if consumer not in ("hermes", "openclaw", "codex", "zhiyi", "unknown"):
            consumer = "unknown"
        source_system = qs.get("source_system", ["openclaw"])[0]
        computer_name = qs.get("computer_name", ["local"])[0]
        canonical_window_id = qs.get("canonical_window_id", [""])[0]
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
        pack = build_raw_direct_pack(items, consumer=consumer, query_hint=query_hint)
        pack["ok"] = True
        self._json(200, pack)

    def do_POST(self):
        self._json(405, {"ok": False, "error": "read_only_endpoint"})


def run(port=PORT, host=DEFAULT_HOST):
    server = HTTPServer((host, port), Handler)
    auth_mode = "token_required" if os.environ.get(TOKEN_ENV, "").strip() else "dev_no_token"
    print(f"[raw-experience-endpoint] listening on {host}:{port}")
    print(f"[raw-experience-endpoint] GET /raw-experience/pack")
    print(f"[raw-experience-endpoint] not_skill_gate=true not_skill_writer=true")
    print(f"[raw-experience-endpoint] auth={auth_mode}")
    server.serve_forever()


if __name__ == "__main__":
    run()
