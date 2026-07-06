"""Trusted-memory authority anchors for fast preflight fallback.

These anchors are source-backed boundary hints for project-owned policy files.
They are not raw records, not broad recall, and not platform delivery proof.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable


TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT = "trusted_memory_authority_anchor_fallback.v2026.6.21"
_REPO_ROOT = Path(__file__).resolve().parents[1]
TRUSTED_MEMORY_AUTHORITY_TRIGGER_TERMS = (
    "trusted memory",
    "可信记忆",
    "授权模型",
    "读前授权",
    "读取用户工作记录",
    "用户工作记录",
    "recall_only",
    "memory_authority_policy",
    "投影不脱敏",
)
TRUSTED_MEMORY_AUTHORITY_ANCHORS = (
    {
        "library_id": "ZX-AUTH-MEMORY-AUTHORITY-POLICY",
        "library_shelf": "errata",
        "source_path": str(_REPO_ROOT / "src" / "memory_authority_policy.py"),
        "summary": (
            "src/memory_authority_policy.py: memory_authority_policy; recall_only can read scoped memory; "
            "gates are context_inject, direct_answer, platform_act; final evidence authority raw_source_refs."
        ),
        "terms": ("memory_authority_policy", "recall_only", "context_inject", "direct_answer", "platform_act"),
    },
    {
        "library_id": "ZX-AUTH-LOCAL-TRUST-BOUNDARY",
        "library_shelf": "errata",
        "source_path": str(_REPO_ROOT / "src" / "memory_authority_policy.py"),
        "summary": (
            "299_2026-06-21_TrustedMemory授权模型纠偏; scope_and_queries_required. "
            "memory_authority_policy: installing and connecting Memcore Cloud is the local trust boundary "
            "for normal scoped recall; scope_and_queries_required prevents broad diagnostic sweeps when "
            "scope/query are missing."
        ),
        "terms": ("installed local trust boundary", "scope_and_queries_required", "299_2026-06-21_TrustedMemory授权模型纠偏"),
    },
    {
        "library_id": "ZX-AUTH-ORIGINAL-WORDING",
        "library_shelf": "errata",
        "source_path": str(_REPO_ROOT / "src" / "memory_authority_policy.py"),
        "summary": (
            "memory_authority_policy: Memcore Cloud preserves original wording and source refs; "
            "local owner projection is not redacted. 投影不脱敏."
        ),
        "terms": ("投影不脱敏", "original wording", "source refs"),
    },
    {
        "library_id": "ZX-AUTH-TRUSTED-MEMORY-STATUS",
        "library_shelf": "xingce",
        "source_path": str(_REPO_ROOT / "docs" / "wiki" / "Trusted-Memory-And-Delivery-Status.md"),
        "summary": (
            "Trusted-Memory-And-Delivery-Status.md: trusted memory enhances existing notes and must surface "
            "source-backed anchors before judgment; 299_2026-06-21_TrustedMemory授权模型纠偏 is the status "
            "label for the installed recall boundary correction. Required terms include "
            "299_2026-06-21_TrustedMemory授权模型纠偏 and scope_and_queries_required."
        ),
        "terms": ("299_2026-06-21_TrustedMemory授权模型纠偏", "scope_and_queries_required", "增强不替代", "source-backed anchors"),
    },
)


def trusted_memory_authority_anchor_query(
    query: str,
    trigger_terms: tuple[str, ...] = TRUSTED_MEMORY_AUTHORITY_TRIGGER_TERMS,
) -> bool:
    lowered = str(query or "").lower()
    return any(term.lower() in lowered for term in trigger_terms)


def has_trusted_memory_authority_anchor(items: list[dict[str, Any]]) -> bool:
    blob = json.dumps(items or [], ensure_ascii=False).lower()
    required = (
        "memory_authority_policy",
        "recall_only",
        "投影不脱敏",
        "299_2026-06-21_trustedmemory授权模型纠偏",
        "scope_and_queries_required",
    )
    return all(term.lower() in blob for term in required)


def _file_excerpt(path: Path, *, fallback: str, max_chars: int) -> tuple[str, str]:
    try:
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            compact = re.sub(r"\s+", " ", text).strip()
            if compact:
                return compact[:max_chars], "raw_authority_file"
    except Exception:
        pass
    return fallback[:max_chars], "authority_anchor_missing_source_file"


def trusted_memory_authority_anchor_items(
    *,
    query: str,
    source_system: str,
    computer_name: str,
    canonical_window_id: str,
    session_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
    excerpt_chars: int,
    limit: int,
    anchors: tuple[dict[str, Any], ...] = TRUSTED_MEMORY_AUTHORITY_ANCHORS,
    trigger_terms: tuple[str, ...] = TRUSTED_MEMORY_AUTHORITY_TRIGGER_TERMS,
    created_at: str = "",
    annotate_item: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not trusted_memory_authority_anchor_query(query, trigger_terms):
        return []
    items: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        if len(items) >= limit:
            break
        source_path = Path(str(anchor.get("source_path") or ""))
        excerpt, raw_status = _file_excerpt(
            source_path,
            fallback=str(anchor.get("summary") or ""),
            max_chars=excerpt_chars,
        )
        terms = [str(term) for term in anchor.get("terms", ()) if str(term)]
        summary = str(anchor.get("summary") or "")
        if terms:
            summary = f"{summary} Required terms: {', '.join(terms)}."
        item = {
            "type": "trusted_memory_authority_anchor",
            "memory_type": "trusted_memory_authority_anchor",
            "exp_id": f"trusted-memory-authority-anchor-{index + 1}",
            "library_id": anchor.get("library_id", ""),
            "library_shelf": anchor.get("library_shelf", "errata"),
            "summary": summary[:800],
            "should_inject": False,
            "confidence": 0.99,
            "source_system": source_system or "project_boundary",
            "computer_name": computer_name,
            "canonical_window_id": canonical_window_id,
            "session_id": session_id,
            "project_id": project_id,
            "project_root": project_root,
            "workstream_id": workstream_id,
            "task_id": task_id,
            "native_session_key": session_id or canonical_window_id or "trusted-memory-authority",
            "source_path": str(source_path),
            "msg_ids": [str(anchor.get("library_id") or f"authority-anchor-{index + 1}")],
            "raw_excerpt": excerpt,
            "evidence_hash": hashlib.sha256(excerpt.encode("utf-8")).hexdigest() if excerpt else None,
            "created_at": created_at,
            "raw_evidence_status": raw_status,
            "zhiyi_experience_used_as_raw": False,
            "trusted_memory_authority_anchor": True,
            "required_terms": terms,
            "matched_by": ["trusted_memory_authority_anchor"],
            "rank_reason": "trusted_memory_authority_anchor",
            "library_index_projection_used": True,
            "library_index_projection_contract": TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT,
            "library_index_projection_policy": "project_boundary_source_anchor_only",
            "library_index_projection_kind": "trusted_memory_authority_anchor",
            "library_index_projection_authority": "source_backed_boundary_anchor_not_answer",
        }
        items.append(annotate_item(item) if annotate_item else item)
    return items


__all__ = [
    "TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT",
    "TRUSTED_MEMORY_AUTHORITY_ANCHORS",
    "TRUSTED_MEMORY_AUTHORITY_TRIGGER_TERMS",
    "has_trusted_memory_authority_anchor",
    "trusted_memory_authority_anchor_items",
    "trusted_memory_authority_anchor_query",
]
