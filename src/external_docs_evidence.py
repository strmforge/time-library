#!/usr/bin/env python3
"""External documentation evidence planning helpers.

This module intentionally does not depend on a named documentation provider.
It only decides whether a question should be checked against current external
documentation and returns a read-only evidence plan for later review.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List


EXTERNAL_DOCS_EVIDENCE_VERSION = "2026.6.8"
EXTERNAL_DOCS_EVIDENCE_CONTRACT = "zhixing_external_docs_evidence.v1"
RAW_SOURCE_ROOT = "raw/external_docs/"
DEFAULT_TTL_HOURS = 168

ENGLISH_DOC_SIGNALS = [
    "api",
    "sdk",
    "cli",
    "docs",
    "documentation",
    "release",
    "release notes",
    "changelog",
    "version",
    "upgrade",
    "migration",
    "deprecated",
    "breaking change",
    "dependency",
    "package",
    "import",
    "error",
    "stack trace",
    "config",
    "mcp",
    "endpoint",
    "base url",
]

CHINESE_DOC_SIGNALS = [
    "接口",
    "文档",
    "官方",
    "版本",
    "升级",
    "迁移",
    "依赖",
    "配置",
    "报错",
    "错误",
    "更新",
    "下线",
    "弃用",
    "变更",
    "接入",
    "安装",
    "模型",
]

SOURCE_TYPES = [
    "official_docs",
    "release_notes",
    "migration_guides",
    "local_docs_cache",
    "user_configured_docs_provider",
]

DEPENDENCY_STOPWORDS = {
    "after",
    "before",
    "since",
    "from",
    "with",
    "using",
    "version",
    "upgrade",
    "upgrading",
    "error",
    "the",
}


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


def _string_list(value: Any) -> List[str]:
    return [_clean_text(item) for item in _as_list(value) if _clean_text(item)]


def _first_text(body: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean_text(body.get(key))
        if value:
            return value
    return ""


def _candidate_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"external-docs-{digest}"


def _slugify(value: str) -> str:
    lowered = value.lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", lowered).strip("-")
    if not slug:
        slug = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return slug[:80]


def _detect_signals(text: str) -> List[str]:
    lowered = text.lower()
    matched: List[str] = []
    for token in ENGLISH_DOC_SIGNALS:
        if token in lowered:
            matched.append(token)
    for token in CHINESE_DOC_SIGNALS:
        if token in text:
            matched.append(token)
    return matched


def _extract_dependency(body: Dict[str, Any], text: str) -> str:
    explicit = _first_text(body, "dependency", "package", "library", "framework", "tool", "platform")
    if explicit:
        return explicit
    patterns = [
        r"\b([a-zA-Z][a-zA-Z0-9_.-]+)\s+(?:v(?:ersion)?\s*)?(\d+(?:\.\d+){1,3})\b",
        r"\b([a-zA-Z][a-zA-Z0-9_.-]+)@(\d+(?:\.\d+){1,3})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group(1).strip()
            if name.lower() in DEPENDENCY_STOPWORDS:
                continue
            return f"{name} {match.group(2)}"
    return ""


def _build_reason(recommended: bool, signals: List[str], dependency: str, version: str) -> str:
    if recommended:
        parts = ["question_contains_doc_drift_signals"]
        if signals:
            parts.append("signals=" + ",".join(signals[:6]))
        if dependency:
            parts.append("dependency=" + dependency)
        if version:
            parts.append("version=" + version)
        return "; ".join(parts)
    return "no_current_external_docs_signal_detected"


def _build_query_terms(query: str, dependency: str, version: str) -> List[str]:
    terms: List[str] = []
    if dependency:
        terms.append(dependency)
    if version and version not in dependency:
        terms.append(version)
    if query:
        terms.append(query[:180])
    if dependency:
        terms.append(f"{dependency} official docs")
        terms.append(f"{dependency} release notes")
    return terms[:6]


def _build_raw_target(query: str, dependency: str, version: str) -> str:
    seed = " ".join([dependency, version, query]).strip() or "external-docs-evidence"
    return f"{RAW_SOURCE_ROOT}{_slugify(seed)}.jsonl"


def get_external_docs_evidence_contract() -> Dict[str, Any]:
    """Return the read-only contract for external docs evidence planning."""
    return {
        "ok": True,
        "version": EXTERNAL_DOCS_EVIDENCE_VERSION,
        "contract": EXTERNAL_DOCS_EVIDENCE_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "candidate_type": "external_docs_evidence_plan",
        "endpoint": "/api/v1/zhixing/external-docs-evidence/dry-run",
        "raw_source_root": RAW_SOURCE_ROOT,
        "library_shelf": "toolbook",
        "evidence_scope": "toolbook",
        "not_a_memory_source": True,
        "third_party_tool_dependency": False,
        "network_call_performed": False,
        "required_fields": ["query_or_question"],
        "optional_fields": [
            "project",
            "dependency",
            "version",
            "preferred_sources",
            "source_refs",
        ],
        "source_types": SOURCE_TYPES,
        "ttl_policy": {
            "default_hours": DEFAULT_TTL_HOURS,
            "refresh_on_version_change": True,
            "refresh_on_breaking_change_signal": True,
        },
        "forbidden_by_default": [
            "brand_named_provider_dependency",
            "network_call_without_user_config",
            "store_summary_as_raw",
            "platform_config_write",
            "memory_recall_substitution",
        ],
        "notes": [
            "external documentation evidence is a toolbook evidence layer",
            "dry-run only plans source checks and source refs",
            "raw authority requires captured source text plus source refs",
        ],
    }


def build_external_docs_evidence_dry_run(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a read-only plan for current external documentation evidence."""
    body = body if isinstance(body, dict) else {}
    query = _first_text(body, "query", "question", "message", "text")
    project = _first_text(body, "project", "workspace", "repo")
    version = _first_text(body, "version", "doc_version")
    dependency = _extract_dependency(body, query)
    source_refs = body.get("source_refs") if isinstance(body.get("source_refs"), (dict, list)) else []
    preferred_sources = _string_list(body.get("preferred_sources"))
    signals = _detect_signals(" ".join([query, dependency, version]))
    external_docs_recommended = bool(signals or dependency or version or preferred_sources)
    candidate_id = _candidate_id("|".join([query, project, dependency, version]))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw_target = _build_raw_target(query, dependency, version)

    missing: List[str] = []
    if not query:
        missing.append("query_or_question")

    query_plan = [
        {
            "order": index + 1,
            "source_type": source_type,
            "query_terms": _build_query_terms(query, dependency, version),
            "must_capture_source_text": True,
            "must_record_source_ref": True,
            "network_call_allowed_in_dry_run": False,
        }
        for index, source_type in enumerate(SOURCE_TYPES)
    ]

    candidate = {
        "candidate_id": candidate_id,
        "candidate_type": "external_docs_evidence_plan",
        "schema_version": EXTERNAL_DOCS_EVIDENCE_VERSION,
        "status": "candidate",
        "created_at": now_iso,
        "query": query,
        "project": project,
        "dependency": dependency,
        "version": version,
        "external_docs_recommended": external_docs_recommended,
        "reason": _build_reason(external_docs_recommended, signals, dependency, version),
        "evidence_kind": "external_docs_evidence",
        "evidence_scope": "toolbook",
        "library_shelf": "toolbook",
        "raw_source_root": RAW_SOURCE_ROOT,
        "raw_target": raw_target,
        "not_a_memory_source": True,
        "query_plan": query_plan,
        "preferred_sources_count": len(preferred_sources),
        "existing_source_refs_count": len(source_refs) if isinstance(source_refs, list) else (1 if source_refs else 0),
        "source_ref_template": {
            "source_system": "external_docs",
            "source_type": "official_or_user_configured_docs",
            "source_url": "<captured_doc_url>",
            "source_title": "<captured_doc_title>",
            "retrieved_at": "<utc_timestamp>",
            "doc_version": version or "<detected_or_unknown>",
            "content_hash": "<sha256_of_captured_source_text>",
            "ttl_expires_at": f"<retrieved_at+{DEFAULT_TTL_HOURS}h>",
        },
        "ttl_policy": {
            "default_hours": DEFAULT_TTL_HOURS,
            "refresh_on_version_change": True,
            "refresh_on_breaking_change_signal": True,
        },
        "recommended_action": (
            "collect_external_docs_evidence_before_answer"
            if external_docs_recommended
            else "answer_without_external_docs_evidence_unless_user_requests"
        ),
        "review_required": external_docs_recommended,
        "activation_allowed": False,
        "install_allowed": False,
        "third_party_tool_dependency": False,
        "read_only": True,
        "write_performed": False,
        "network_call_performed": False,
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
        "raw_write_performed": False,
        "platform_write_performed": False,
        "contract": EXTERNAL_DOCS_EVIDENCE_CONTRACT,
        "version": EXTERNAL_DOCS_EVIDENCE_VERSION,
        "candidate_created": not missing,
        "candidate_id": candidate_id if not missing else "",
        "candidate": candidate if not missing else None,
        "external_docs_recommended": external_docs_recommended if not missing else False,
        "missing": missing,
        "error": "invalid_external_docs_evidence_plan" if missing else "",
    }
