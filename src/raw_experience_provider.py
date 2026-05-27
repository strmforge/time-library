#!/usr/bin/env python3
"""Cross-agent raw experience provider for memcore-cloud.

Provides read-only raw evidence packs for any agent (Hermes, OpenClaw, Codex, etc.)
to consume for their own learning, skill generation, or behavior improvement.

This module does NOT:
- Write Hermes skill/memory/config
- Write OpenClaw session
- Write production data
- Gatekeep or judge agent skill quality
- Replace agent-native skill/curator systems
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

UTC = timezone.utc
PROVIDER_CONTRACT_VERSION = "0.1.0"
RAW_OUTPUT_POLICY_VERBATIM = "verbatim_default"
REDACTION_NONE = "none"
REDACTION_LEGACY_SECRET_LIKE = "legacy_secret_like"

CONSUMER_HERMES = "hermes"
CONSUMER_OPENCLAW = "openclaw"
CONSUMER_CODEX = "codex"
CONSUMER_UNKNOWN = "unknown"
ALL_CONSUMERS = (CONSUMER_HERMES, CONSUMER_OPENCLAW, CONSUMER_CODEX, CONSUMER_UNKNOWN)

EVENT_FAILURE = "failure"
EVENT_CORRECTION = "correction"
EVENT_SELF_FIX = "self_fix"
EVENT_COMMAND_OUTPUT = "command_output"
EVENT_SUCCESS = "success"
EVENT_USER_INSTRUCTION = "user_instruction"
EVENT_UNKNOWN = "unknown"
ALL_EVENT_TYPES = (EVENT_FAILURE, EVENT_CORRECTION, EVENT_SELF_FIX, EVENT_COMMAND_OUTPUT, EVENT_SUCCESS, EVENT_USER_INSTRUCTION, EVENT_UNKNOWN)

NOISE_USEFUL = "useful_noise"
NOISE_CONFLICT = "conflict"
NOISE_FAILED = "failed_attempt"
NOISE_CORRECTION = "correction"
NOISE_UNKNOWN = "unknown"
ALL_NOISE_LABELS = (NOISE_USEFUL, NOISE_CONFLICT, NOISE_FAILED, NOISE_CORRECTION, NOISE_UNKNOWN)

_SECRET_PATTERNS = [
    r"(?i)(sk-[a-zA-Z0-9]{20,})",
    r"(?i)(api[-_]?key\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{16,})",
    r"(?i)(token\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{16,})",
    r"(?i)(secret\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{16,})",
    r"(?i)(password\s*[=:]\s*['\"]?[a-zA-Z0-9_-]+)",
    r"-----BEGIN (RSA |EC )?PRIVATE KEY-----",
]


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_evidence_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def redact_secret_like_fields(text: str) -> str:
    if not text:
        return text
    result = text
    for pattern in _SECRET_PATTERNS:
        result = re.sub(pattern, "[REDACTED]", result)
    return result


def build_item(raw_excerpt, source_system="", session_id="", event_type=EVENT_UNKNOWN, noise_label=NOISE_UNKNOWN, computer_name="", source_refs=None, redaction_policy=REDACTION_NONE):
    raw_text = raw_excerpt if isinstance(raw_excerpt, str) else str(raw_excerpt or "")
    if redaction_policy == REDACTION_LEGACY_SECRET_LIKE:
        output_text = redact_secret_like_fields(raw_text)
    else:
        redaction_policy = REDACTION_NONE
        output_text = raw_text
    bounded = output_text[:800]
    return {
        "item_id": compute_evidence_hash(bounded),
        "event_type": event_type if event_type in ALL_EVENT_TYPES else EVENT_UNKNOWN,
        "raw_excerpt": bounded,
        "source_refs": source_refs or {},
        "evidence_hash": compute_evidence_hash(bounded),
        "noise_label": noise_label if noise_label in ALL_NOISE_LABELS else NOISE_UNKNOWN,
        "platform_context": {"agent": source_system, "runtime_mode": ""},
        "raw_output_policy": RAW_OUTPUT_POLICY_VERBATIM,
        "_redaction_policy": redaction_policy,
        "_redaction_applied": output_text != raw_text,
    }


def filter_items_for_consumer(items, consumer, query_hint="", source_system="", noise_filter="", since=""):
    items = filter_by_query(items, query_hint)
    items = filter_by_source_system(items, source_system)
    items = filter_by_noise(items, noise_filter)
    items = filter_by_since(items, since)
    return items
    return items


def filter_by_query(items, query_hint):
    if not query_hint:
        return items
    hint = query_hint.lower()
    result = []
    for item in items:
        excerpt = item.get("raw_excerpt", "").lower()
        if hint in excerpt:
            result.append(item)
    return result

def filter_by_source_system(items, source_system):
    if not source_system:
        return items
    return [it for it in items if it.get("platform_context", {}).get("agent", "") == source_system]

def filter_by_noise(items, noise_filter):
    if not noise_filter:
        return items
    return [it for it in items if it.get("noise_label", "") == noise_filter]

def filter_by_since(items, since):
    if not since:
        return items
    # ISO timestamp match: if item has timestamp field, compare
    # For now, since items have no timestamp, return all
    return items

def build_raw_experience_pack(items, consumer=CONSUMER_UNKNOWN, source_systems=None):
    return {
        "pack_id": "pack-" + compute_evidence_hash(json.dumps(items, sort_keys=True)),
        "purpose": "cross_agent_raw_experience",
        "consumer_hint": consumer if consumer in ALL_CONSUMERS else CONSUMER_UNKNOWN,
        "source_systems": source_systems or [],
        "noise_policy": "preserve_with_labels",
        "not_clean_summary": True,
        "not_skill_gate": True,
        "not_skill_writer": True,
        "raw_output_policy": RAW_OUTPUT_POLICY_VERBATIM,
        "default_redaction": False,
        "provider_contract_version": PROVIDER_CONTRACT_VERSION,
        "generated_at": _ts(),
        "items_count": len(items),
        "items": items,
        "_production_write": False,
        "_hermes_skill_write": False,
        "_openclaw_session_write": False,
    }
