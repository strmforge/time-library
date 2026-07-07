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


CATALOG_PUSH_CONTRACT = "zhixing_catalog_push.v1"
CATALOG_SHELF_PRIORITY = {"zhiyi": 0, "xingce": 1, "toolbook": 2, "raw": 3, "errata": 4}
CATALOG_SHELF_FALLBACK_PRIORITY = {"raw": 0, "errata": 1, "toolbook": 2, "zhiyi": 3, "xingce": 4}


_WINDOW_ID_RE = re.compile(
    r"^(ssh-|local-|[0-9a-f]{8}-[0-9a-f]{4}-|canonical_window|test-window)"
    r"|openclaw\s+local(\s|$)"
    r"|\b(window|session|canonical)\b.*\b(id|-[0-9a-f]{6,})\b",
    re.IGNORECASE,
)


def _looks_like_window_id(text: str) -> bool:
    compact = text.strip().lower()
    if not compact:
        return False
    if _WINDOW_ID_RE.search(compact):
        return True
    parts = compact.split()
    if len(parts) <= 3 and all(re.match(r"^[a-z0-9._-]+$", p) for p in parts):
        if any(len(p) >= 8 and re.search(r"[0-9a-f]{6,}", p) for p in parts):
            return True
    return False


def _looks_like_scope_label_only(text: str) -> bool:
    compact = text.strip().lower().replace("-", "_")
    return compact in {
        "codex",
        "opus",
        "mimo",
        "mimocode",
        "claude",
        "claude_code",
        "claude_code_cli",
        "hermes",
        "openclaw",
        "source_testing",
        "local",
    }


def _when_to_use_for(record: dict, card: dict) -> str:
    for field in ("when_to_use", "applies_when", "trigger_signal"):
        value = card.get(field) or record.get(field)
        if value:
            text = _clean_text(str(value))[:120]
            if not _looks_like_window_id(text) and not _looks_like_scope_label_only(text):
                return text
    work = card.get("work_experience") if isinstance(card.get("work_experience"), dict) else {}
    for field in ("applicable_scope", "work_scenario"):
        value = work.get(field) or record.get(field)
        if value:
            text = _clean_text(str(value))[:120]
            if not _looks_like_window_id(text) and not _looks_like_scope_label_only(text):
                return text
    title = str(card.get("title") or record.get("title") or "").strip()
    if title and not _looks_like_window_id(title):
        return _clean_text(title)[:120]
    for field in ("rank_reason", "summary"):
        value = card.get(field) or record.get(field)
        if value:
            text = _clean_text(str(value))
            for sep in ("。", ".", "；", ";"):
                if sep in text[:120]:
                    candidate = text.split(sep, 1)[0][:120]
                    if not _looks_like_window_id(candidate):
                        return candidate
            if not _looks_like_window_id(text[:120]):
                return text[:120]
    return ""


def _source_ref_compact(refs) -> str:
    if isinstance(refs, dict):
        source_path = _clean_text(refs.get("source_path"))
        if source_path:
            basename = source_path.rsplit("/", 1)[-1] if "/" in source_path else source_path
            byte_offsets = refs.get("byte_offsets") if isinstance(refs.get("byte_offsets"), dict) else {}
            start = byte_offsets.get("start")
            end = byte_offsets.get("end")
            if start is None and isinstance(byte_offsets.get("_computed_verbatim"), dict):
                cv = byte_offsets["_computed_verbatim"]
                start = cv.get("start")
                end = cv.get("end")
            if start is not None:
                return f"{basename}:{start}-{end if end is not None else '?'}"
            return basename
        return _clean_text(refs.get("source_system", ""))
    if isinstance(refs, list):
        for item in refs:
            if isinstance(item, dict):
                source_path = _clean_text(item.get("source_path"))
                if source_path:
                    return source_path.rsplit("/", 1)[-1] if "/" in source_path else source_path
            elif isinstance(item, str) and item.strip():
                return item.rsplit("/", 1)[-1] if "/" in item else item
    return ""


def _extract_source_ref_from_record(record: dict, card: dict) -> str:
    evidence_refs = record.get("evidence_refs") if isinstance(record.get("evidence_refs"), list) else []
    for eref in evidence_refs:
        if not isinstance(eref, dict):
            continue
        source_path = _clean_text(eref.get("source_path"))
        byte_offsets = eref.get("byte_offsets") if isinstance(eref.get("byte_offsets"), dict) else {}
        if source_path:
            basename = source_path.rsplit("/", 1)[-1] if "/" in source_path else source_path
            start = byte_offsets.get("start")
            end = byte_offsets.get("end")
            if start is None and isinstance(byte_offsets.get("_computed_verbatim"), dict):
                cv = byte_offsets["_computed_verbatim"]
                start = cv.get("start")
                end = cv.get("end")
            if start is not None:
                return f"{basename}:{start}-{end if end is not None else '?'}"
            return basename
    refs = card.get("source_refs") if isinstance(card.get("source_refs"), (dict, list)) else None
    if refs:
        compact = _source_ref_compact(refs)
        if compact:
            return compact
    raw_refs = record.get("source_refs")
    if isinstance(raw_refs, list):
        compact = _source_ref_compact(raw_refs)
        if compact:
            return compact
    elif isinstance(raw_refs, dict):
        compact = _source_ref_compact(raw_refs)
        if compact:
            return compact
    return ""


def _catalog_line_for_entry(entry: dict) -> str:
    headline = entry["title"] or entry["library_id"]
    line = f"- [{entry['library_id']}] {headline} | when_to_use: {entry['when_to_use']}"
    if entry["source_ref"]:
        line += f" | source: {entry['source_ref']}"
    return line


def _catalog_lines_and_tokens(catalog: list[dict]) -> tuple[list[str], str, int]:
    lines = [_catalog_line_for_entry(entry) for entry in catalog]
    catalog_text = "\n".join(lines)
    return lines, catalog_text, _estimate_tokens(catalog_text)


def _trim_catalog_preserving_shelf_handles(
    catalog: list[dict],
    target_tokens: int,
    *,
    preserve_library_ids: set[str] | None = None,
) -> tuple[list[dict], list[str], str, int, bool, list[str]]:
    """Trim catalog metadata while keeping one structured handle per non-empty shelf.

    Startup prompt text can omit full flat catalog lines, but structured
    startupCatalog.catalog[] remains the library_id -> source_ref borrowing
    surface. If zhiyi/xingce grow, plain tail-pop trimming can silently remove
    raw/toolbook/errata whole shelves from that structured surface. Keep one
    compact handle per shelf before dropping optional entries.
    """

    trimmed_catalog = list(catalog)
    lines, catalog_text, token_count = _catalog_lines_and_tokens(trimmed_catalog)
    trimmed = False
    if token_count <= target_tokens:
        return trimmed_catalog, lines, catalog_text, token_count, trimmed, []

    source_shelves = {str(entry.get("shelf") or "") for entry in catalog if entry.get("shelf")}
    explicit_preserve_ids = {str(item or "").strip() for item in (preserve_library_ids or set()) if str(item or "").strip()}

    def protected_ids_for(items: list[dict]) -> set[str]:
        current_ids = {str(entry.get("library_id") or "") for entry in items}
        protected: set[str] = explicit_preserve_ids & current_ids
        for shelf in source_shelves:
            shelf_entries = [entry for entry in items if entry.get("shelf") == shelf]
            if not shelf_entries:
                continue
            keep = sorted(
                shelf_entries,
                key=lambda entry: (
                    CATALOG_SHELF_FALLBACK_PRIORITY.get(str(entry.get("shelf") or ""), 9),
                    str(entry.get("library_id") or ""),
                ),
            )[0]
            protected.add(str(keep.get("library_id") or ""))
        return protected

    while token_count > target_tokens and len(trimmed_catalog) > 1:
        protected = protected_ids_for(trimmed_catalog)
        removable_indexes = [
            index
            for index, entry in enumerate(trimmed_catalog)
            if str(entry.get("library_id") or "") not in protected
        ]
        if not removable_indexes:
            break
        # Prefer dropping lower-priority later shelves first, but never remove
        # the last handle of any shelf.
        remove_index = max(
            removable_indexes,
            key=lambda index: (
                CATALOG_SHELF_PRIORITY.get(str(trimmed_catalog[index].get("shelf") or ""), 9),
                index,
            ),
        )
        trimmed_catalog.pop(remove_index)
        lines, catalog_text, token_count = _catalog_lines_and_tokens(trimmed_catalog)
        trimmed = True

    omitted_shelves = sorted(source_shelves - {str(entry.get("shelf") or "") for entry in trimmed_catalog})
    return trimmed_catalog, lines, catalog_text, token_count, trimmed, omitted_shelves


def _excluded_from_active_catalog(record: dict, card: dict) -> bool:
    source_path = ""
    refs = card.get("source_refs") if isinstance(card.get("source_refs"), dict) else record.get("source_refs")
    if isinstance(refs, dict):
        source_path = str(refs.get("source_path") or "")
    if "quarantined" in source_path.lower():
        return True
    shelf = str(card.get("shelf") or record.get("library_shelf") or "")
    status = str(card.get("status") or record.get("lifecycle_status") or record.get("status") or "")
    if shelf != "errata" and status in ("deprecated", "superseded", "recycled", "invalid"):
        return True
    return False


def _attach_card(record: dict) -> dict:
    try:
        from src.zhixing_library import attach_library_card
    except Exception:
        from zhixing_library import attach_library_card
    result = attach_library_card(record)
    return result.get("library_card", {}) if isinstance(result.get("library_card"), dict) else {}


def _build_library_index_projection(records: list) -> dict:
    try:
        from src.zhixing_library import build_library_index_projection_dry_run
    except Exception:
        try:
            from zhixing_library import build_library_index_projection_dry_run
        except Exception:
            return {}
    try:
        projection = build_library_index_projection_dry_run({
            "records": records,
            "title": "Time Library Catalog Push",
            "per_shelf_limit": 50,
        })
    except Exception:
        return {}
    return projection if isinstance(projection, dict) else {}


def build_library_catalog_push(
    records: list,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    preserve_library_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    trim_to_target_tokens: bool = True,
) -> dict:
    """Build a compact library catalog from records for push delivery.

    Each entry contains: library_id + title + when_to_use + source_ref.
    Only catalog metadata, no content body. Filters out quarantined and inactive
    non-errata records; errata records are first-class catalog entries.
    Returns index_projection_contract/projection_layer for L0 alignment.
    """
    if not isinstance(records, list) or not records:
        return {
            "ok": False,
            "contract": CATALOG_PUSH_CONTRACT,
            "catalog": [],
            "token_count": 0,
            "target_tokens": target_tokens,
            "error": "no_records",
        }

    index_projection = _build_library_index_projection(records)
    seen_ids: set[str] = set()
    catalog: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        card = _attach_card(record)
        library_id = str(card.get("library_id") or record.get("library_id") or "").strip()
        if not library_id or library_id in seen_ids:
            continue
        if _excluded_from_active_catalog(record, card):
            continue
        when_to_use = _when_to_use_for(record, card)
        if not when_to_use:
            continue
        source_ref = _extract_source_ref_from_record(record, card)
        shelf = str(card.get("shelf") or record.get("library_shelf") or "zhiyi")
        title = str(card.get("title") or record.get("title") or "")[:60]
        catalog.append({
            "library_id": library_id,
            "shelf": shelf,
            "title": title,
            "when_to_use": when_to_use,
            "source_ref": source_ref,
            "_sort_key": (CATALOG_SHELF_PRIORITY.get(shelf, 9), library_id),
        })
        seen_ids.add(library_id)

    catalog.sort(key=lambda item: item.pop("_sort_key", (9, "")))

    if trim_to_target_tokens:
        catalog, lines, catalog_text, token_count, trimmed, omitted_shelves = _trim_catalog_preserving_shelf_handles(
            catalog,
            target_tokens,
            preserve_library_ids=set(preserve_library_ids or []),
        )
    else:
        lines, catalog_text, token_count = _catalog_lines_and_tokens(catalog)
        trimmed = False
        omitted_shelves = []

    return {
        "ok": True,
        "contract": CATALOG_PUSH_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "catalog": catalog,
        "catalog_text": catalog_text,
        "token_count": token_count,
        "target_tokens": target_tokens,
        "entry_count": len(catalog),
        "trimmed": trimmed,
        "over_budget": token_count > target_tokens,
        "omitted_shelves": omitted_shelves,
        "trim_to_target_tokens": bool(trim_to_target_tokens),
        "shelf_handle_preservation": "one_structured_catalog_handle_per_non_empty_shelf_when_possible",
        "preserved_library_ids": sorted(set(preserve_library_ids or []) & {entry.get("library_id") for entry in catalog}),
        "index_projection_contract": index_projection.get("contract", "zhixing_library_index_projection.v1"),
        "projection_layer": index_projection.get("projection_layer", "L0_library_index_projection"),
        "library_index_projection": index_projection.get("index", {}),
    }


def build_catalog_compaction(catalog_result: dict, *, target_tokens: int = DEFAULT_TARGET_TOKENS) -> dict:
    """Pass catalog through context_delivery_compaction for push packaging."""
    if not isinstance(catalog_result, dict) or not catalog_result.get("ok"):
        return {
            "ok": False,
            "contract": CONTEXT_DELIVERY_COMPACTION_CONTRACT,
            "error": "invalid_catalog_input",
        }
    catalog_text = catalog_result.get("catalog_text", "")
    if not catalog_text:
        return {
            "ok": False,
            "contract": CONTEXT_DELIVERY_COMPACTION_CONTRACT,
            "error": "empty_catalog_text",
        }
    return build_context_delivery_compaction_dry_run({
        "content": catalog_text,
        "content_type": "catalog_index",
        "target_tokens": target_tokens,
        "max_tokens": target_tokens * 2,
    })


def build_catalog_inject_prompt(catalog_result: dict) -> dict:
    """Build an injectable prompt from catalog for push into new window context."""
    if not isinstance(catalog_result, dict) or not catalog_result.get("ok"):
        return {
            "ok": False,
            "should_inject": False,
            "error": "invalid_catalog_input",
        }
    entries = catalog_result.get("catalog", [])
    if not entries:
        return {
            "ok": False,
            "should_inject": False,
            "error": "empty_catalog",
        }

    lines: list[str] = []
    for entry in entries:
        headline = entry.get("title") or entry["library_id"]
        line = f"- [{entry['library_id']}] {headline} | when_to_use: {entry['when_to_use']}"
        if entry.get("source_ref"):
            line += f" | source: {entry['source_ref']}"
        lines.append(line)
    catalog_text = "\n".join(lines)

    system_prompt = (
        "以下是本机 Time Library（时间图书馆）的馆藏书单（仅目录，不含正文）。\n"
        "每条记录的 library_id 是召回把手：当用户聊到相关话题时，\n"
        "可根据 when_to_use 触发信号，用 library_id 拉取对应真卡。\n\n"
        f"{catalog_text}\n\n"
        "使用规则：\n"
        "1. 书单仅供导航，不包含经验正文；需要详情时用 library_id 拉取。\n"
        "2. 无关话题不要主动提及书单内容。\n"
        "3. 用户聊到匹配 when_to_use 的话题时，可用 library_id 拉真卡后回答。"
    )

    return {
        "ok": True,
        "contract": CATALOG_PUSH_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "should_inject": True,
        "system_prompt": system_prompt,
        "entry_count": len(entries),
        "token_count": _estimate_tokens(system_prompt),
    }
