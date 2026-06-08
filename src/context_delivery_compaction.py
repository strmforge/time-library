#!/usr/bin/env python3
"""Context delivery compaction planning helpers.

The compaction layer is a delivery optimization plan. It never rewrites raw
records, never compresses user intent, and never installs a platform proxy.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List


CONTEXT_DELIVERY_COMPACTION_VERSION = "2026.6.8"
CONTEXT_DELIVERY_COMPACTION_CONTRACT = "zhixing_context_delivery_compaction.v1"
MIN_COMPACTION_TOKENS = 200
DEFAULT_TARGET_TOKENS = 1200
LOG_SEVERITIES = ["fatal", "error", "exception", "traceback", "warn", "warning", "failed", "panic"]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in ("", None):
        return []
    return [value]


def _source_refs_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return 1 if value else 0
    return 0


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, (ascii_chars // 4) + (non_ascii_chars // 2))


def _candidate_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"context-compaction-{digest}"


def _messages_to_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    chunks: List[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = _clean_text(item.get("role"))
        content = item.get("content")
        if isinstance(content, list):
            content_text = "\n".join(_clean_text(part.get("text") if isinstance(part, dict) else part) for part in content)
        else:
            content_text = _clean_text(content)
        if content_text:
            chunks.append(f"[{role or 'message'}] {content_text}")
    return "\n".join(chunks)


def _first_payload(body: Dict[str, Any]) -> str:
    for key in ("content", "tool_output", "log", "text", "payload"):
        value = _clean_text(body.get(key))
        if value:
            return value
    return _messages_to_text(body.get("messages"))


def _has_user_messages(body: Dict[str, Any]) -> bool:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return False
    return any(isinstance(item, dict) and _clean_text(item.get("role")).lower() == "user" for item in messages)


def _looks_like_code(text: str) -> bool:
    lowered = text.lower()
    code_markers = [
        "def ",
        "class ",
        "import ",
        "from ",
        "function ",
        "const ",
        "let ",
        "var ",
        "#include",
        "public class",
    ]
    if any(marker in lowered for marker in code_markers):
        return True
    return bool(re.search(r"[{};]\s*$", text, re.MULTILINE))


def _looks_like_log(text: str) -> bool:
    lowered = text.lower()
    severity_hits = sum(1 for token in LOG_SEVERITIES if token in lowered)
    timestamp_hits = len(re.findall(r"\b\d{4}-\d{2}-\d{2}[t\s]\d{2}:\d{2}:\d{2}", text.lower()))
    bracket_level_hits = len(re.findall(r"\b(INFO|WARN|WARNING|ERROR|FATAL|DEBUG)\b", text))
    return severity_hits > 0 or timestamp_hits >= 2 or bracket_level_hits >= 2


def _json_profile(text: str) -> Dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if isinstance(parsed, list):
        return {
            "kind": "json_array",
            "items": len(parsed),
            "strategy": "schema_sample_anomaly_tail_preservation",
        }
    if isinstance(parsed, dict):
        return {
            "kind": "json_object",
            "items": len(parsed),
            "strategy": "key_path_factoring_with_value_boundaries",
        }
    return {
        "kind": "json_scalar",
        "items": 1,
        "strategy": "pass_through",
    }


def _classify_content(text: str, explicit: str = "") -> Dict[str, Any]:
    explicit = explicit.strip().lower()
    if explicit:
        return {
            "content_type": explicit,
            "strategy": _strategy_for_type(explicit),
            "detected_by": "explicit_content_type",
        }
    profile = _json_profile(text)
    if profile:
        return {
            "content_type": profile["kind"],
            "strategy": profile["strategy"],
            "detected_by": "json_parse",
            "items": profile["items"],
        }
    lowered = text.lower()
    if "<html" in lowered or ("<body" in lowered and "</" in lowered):
        return {
            "content_type": "html",
            "strategy": "visible_text_extraction_with_source_ref",
            "detected_by": "html_markers",
        }
    if _looks_like_code(text):
        return {
            "content_type": "code",
            "strategy": "pass_through_by_default_ast_outline_only_when_authorized",
            "detected_by": "code_markers",
        }
    if _looks_like_log(text):
        return {
            "content_type": "log",
            "strategy": "pattern_cluster_keep_errors_tail_and_stack",
            "detected_by": "log_markers",
        }
    return {
        "content_type": "natural_text",
        "strategy": "outline_with_quotes_and_source_refs",
        "detected_by": "fallback_text",
    }


def _strategy_for_type(content_type: str) -> str:
    if content_type in {"json", "json_array", "json_object", "structured"}:
        return "schema_sample_anomaly_tail_preservation"
    if content_type in {"log", "logs", "trace"}:
        return "pattern_cluster_keep_errors_tail_and_stack"
    if content_type in {"code", "source_code"}:
        return "pass_through_by_default_ast_outline_only_when_authorized"
    if content_type in {"html", "xml"}:
        return "visible_text_extraction_with_source_ref"
    return "outline_with_quotes_and_source_refs"


def _try_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _content_preview(text: str, limit: int = 180) -> str:
    normalized = " ".join(text.split())
    return normalized[:limit]


def get_context_delivery_compaction_contract() -> Dict[str, Any]:
    """Return the read-only contract for context delivery compaction plans."""
    return {
        "ok": True,
        "version": CONTEXT_DELIVERY_COMPACTION_VERSION,
        "contract": CONTEXT_DELIVERY_COMPACTION_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "candidate_type": "context_delivery_compaction_plan",
        "endpoint": "/api/v1/zhixing/context-delivery-compaction/dry-run",
        "context_package_role": "delivery_optimization_only",
        "raw_authority_preserved": True,
        "not_a_memory_source": True,
        "third_party_tool_dependency": False,
        "network_call_performed": False,
        "cache_write_performed": False,
        "raw_write_performed": False,
        "required_fields": ["content_or_messages"],
        "recommended_fields": ["source_refs", "raw_refs", "max_tokens", "target_tokens", "content_type"],
        "content_router_types": ["json_array", "json_object", "log", "code", "html", "natural_text"],
        "compaction_stages": [
            "stable_prefix_boundary",
            "content_type_router",
            "evidence_preserving_compaction_plan",
            "deferred_raw_retrieval_plan",
        ],
        "forbidden_by_default": [
            "compress_user_intent",
            "rewrite_raw_record",
            "delete_original",
            "store_summary_as_raw",
            "irreversible_drop_without_source_refs",
            "install_platform_proxy",
            "write_platform_config",
        ],
        "notes": [
            "compaction belongs to context delivery, not raw storage",
            "user messages and system instructions are preserved",
            "dropped or summarized material needs source refs for retrieval",
        ],
    }


def build_context_delivery_compaction_dry_run(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a dry-run context delivery compaction plan."""
    body = body if isinstance(body, dict) else {}
    text = _first_payload(body)
    explicit_type = _clean_text(body.get("content_type"))
    source_refs = body.get("source_refs") if isinstance(body.get("source_refs"), (dict, list)) else {}
    raw_refs = body.get("raw_refs") if isinstance(body.get("raw_refs"), (dict, list)) else {}
    max_tokens = _try_int(body.get("max_tokens"), DEFAULT_TARGET_TOKENS * 2)
    target_tokens = _try_int(body.get("target_tokens"), DEFAULT_TARGET_TOKENS)
    allow_code_compaction = bool(body.get("allow_code_compaction"))
    allow_lossy = bool(body.get("allow_lossy"))
    preserve_user_messages = body.get("preserve_user_messages", True) is not False
    source_count = _source_refs_count(source_refs) + _source_refs_count(raw_refs)
    tokens = _estimate_tokens(text)
    profile = _classify_content(text, explicit_type) if text else {
        "content_type": "unknown",
        "strategy": "no_content",
        "detected_by": "empty",
    }
    has_user_messages = _has_user_messages(body)
    code_requires_pass_through = profile["content_type"] in {"code", "source_code"} and not allow_code_compaction
    short_content = tokens < MIN_COMPACTION_TOKENS
    over_budget = tokens > max_tokens or tokens > target_tokens
    compaction_recommended = bool(text and not short_content and not code_requires_pass_through and (over_budget or profile["content_type"] in {"log", "json_array", "json_object", "html"}))
    reversible_ready = source_count > 0

    missing: List[str] = []
    if not text:
        missing.append("content_or_messages")

    if code_requires_pass_through:
        recommended_action = "pass_through_code_unless_explicit_compaction_enabled"
    elif short_content:
        recommended_action = "pass_through_short_content"
    elif compaction_recommended and not reversible_ready:
        recommended_action = "capture_source_refs_before_compaction"
    elif compaction_recommended:
        recommended_action = "compact_for_delivery_with_deferred_retrieval"
    else:
        recommended_action = "pass_through_or_trim_only_if_context_window_requires"

    candidate_id = _candidate_id("|".join([profile["content_type"], str(tokens), text[:512]]))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidate = {
        "candidate_id": candidate_id,
        "candidate_type": "context_delivery_compaction_plan",
        "schema_version": CONTEXT_DELIVERY_COMPACTION_VERSION,
        "status": "candidate",
        "created_at": now_iso,
        "context_package_role": "delivery_optimization_only",
        "content_profile": {
            "content_type": profile["content_type"],
            "detected_by": profile["detected_by"],
            "strategy": profile["strategy"],
            "estimated_tokens": tokens,
            "preview": _content_preview(text),
        },
        "budget": {
            "max_tokens": max_tokens,
            "target_tokens": target_tokens,
            "estimated_tokens": tokens,
            "minimum_compaction_tokens": MIN_COMPACTION_TOKENS,
            "over_budget": over_budget,
            "short_content": short_content,
        },
        "source_refs_count": source_count,
        "reversibility": {
            "required_for_compaction": True,
            "ready": reversible_ready,
            "retrieval_anchor": "source_refs_or_raw_refs",
            "local_cache_required_for_dropped_material": True,
            "retrieve_contract": "context_delivery_retrieve_by_source_ref",
            "cache_write_performed": False,
        },
        "preservation_policy": {
            "raw_authority_preserved": True,
            "raw_record_mutation_allowed": False,
            "user_message_compaction_allowed": False,
            "system_instruction_compaction_allowed": False,
            "preserve_user_messages": preserve_user_messages,
            "has_user_messages": has_user_messages,
            "lossy_compaction_allowed": allow_lossy,
            "summary_may_replace_raw": False,
        },
        "compaction_plan": [
            {
                "stage": "stable_prefix_boundary",
                "action": "keep_system_and_memory_contract_stable_move_volatile_context_to_tail",
                "write_performed": False,
            },
            {
                "stage": "content_type_router",
                "action": profile["strategy"],
                "content_type": profile["content_type"],
                "write_performed": False,
            },
            {
                "stage": "evidence_preserving_compaction_plan",
                "action": "keep_errors_anomalies_recent_tail_and_schema_before_sampling",
                "requires_source_refs": True,
                "write_performed": False,
            },
            {
                "stage": "deferred_raw_retrieval_plan",
                "action": "return_source_refs_for_full_material_on_demand",
                "requires_source_refs": True,
                "write_performed": False,
            },
        ],
        "compaction_recommended": compaction_recommended,
        "recommended_action": recommended_action,
        "review_required": compaction_recommended,
        "delivery_only": True,
        "not_a_memory_source": True,
        "third_party_tool_dependency": False,
        "activation_allowed": False,
        "install_allowed": False,
        "read_only": True,
        "write_performed": False,
        "network_call_performed": False,
        "cache_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "platform_write_performed": False,
    }
    return {
        "ok": not missing,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "network_call_performed": False,
        "cache_write_performed": False,
        "raw_write_performed": False,
        "platform_write_performed": False,
        "contract": CONTEXT_DELIVERY_COMPACTION_CONTRACT,
        "version": CONTEXT_DELIVERY_COMPACTION_VERSION,
        "candidate_created": not missing,
        "candidate_id": candidate_id if not missing else "",
        "candidate": candidate if not missing else None,
        "compaction_recommended": compaction_recommended if not missing else False,
        "missing": missing,
        "error": "invalid_context_delivery_compaction_plan" if missing else "",
    }
