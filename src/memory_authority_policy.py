#!/usr/bin/env python3
"""Memory authority policy shared by agent entrypoints."""

from __future__ import annotations

from typing import Any


MEMORY_AUTHORITY_POLICY_CONTRACT = "memory_authority_policy.v2026.6.19"
MEMORY_AUTHORITY_LEVELS = (
    "passive",
    "recall_only",
    "context_inject",
    "direct_answer",
    "platform_act",
)
MEMORY_AUTHORITY_BOUNDARY_NOTES = (
    "recall_only can read scoped Zhiyi/Xingce records after Memcore Cloud is installed and connected",
    "installing and connecting Memcore Cloud is the local trust boundary for normal scoped recall",
    "scope_and_queries_required prevents broad diagnostic sweeps when scope or query inputs are missing",
    "gates protect context_inject, direct_answer, platform_act, writes, adoption, and scope widening",
    "Memcore Cloud preserves original wording and source refs; local owner projection is not redacted",
    "final evidence authority is raw_source_refs",
)


def normalize_authority(value: Any, default: str = "passive") -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in MEMORY_AUTHORITY_LEVELS:
        return text
    return default if default in MEMORY_AUTHORITY_LEVELS else "passive"


def authority_rank(value: Any) -> int:
    return MEMORY_AUTHORITY_LEVELS.index(normalize_authority(value))


def authority_allows(granted: Any, required: Any) -> bool:
    return authority_rank(granted) >= authority_rank(required)


def memory_authority_receipt(
    *,
    requested_authority: str,
    granted_authority: str,
    reason: str,
    source: str = "",
    explicit_zhiyi_entry: bool = False,
    platform_action_authorized: bool = False,
) -> dict[str, Any]:
    requested = normalize_authority(requested_authority)
    granted = normalize_authority(granted_authority)
    return {
        "contract": MEMORY_AUTHORITY_POLICY_CONTRACT,
        "source": str(source or ""),
        "levels": list(MEMORY_AUTHORITY_LEVELS),
        "requested_authority": requested,
        "granted_authority": granted,
        "reason": str(reason or ""),
        "denied": not authority_allows(granted, requested),
        "explicit_zhiyi_entry": bool(explicit_zhiyi_entry),
        "platform_action_authorized": bool(platform_action_authorized),
        "can_read_memory": authority_allows(granted, "recall_only"),
        "can_inject_context": authority_allows(granted, "context_inject"),
        "can_direct_answer": authority_allows(granted, "direct_answer"),
        "can_platform_act": authority_allows(granted, "platform_act"),
        "read_only": not authority_allows(granted, "platform_act"),
        "final_evidence_authority": "raw_source_refs",
        "memory_summary_authority": "candidate_context_not_final_truth",
    }


def decide_memory_authority(
    *,
    source: str = "",
    requested_authority: str = "",
    zhiyi_entry: bool = False,
    explicit_direct_authorized: bool = False,
    context_inject_requested: bool = False,
    platform_action_requested: bool = False,
    platform_action_authorized: bool = False,
) -> dict[str, Any]:
    if requested_authority:
        requested = normalize_authority(requested_authority)
    elif platform_action_requested:
        requested = "platform_act"
    elif zhiyi_entry or explicit_direct_authorized:
        requested = "direct_answer"
    elif context_inject_requested:
        requested = "context_inject"
    else:
        requested = "passive"

    direct_ok = bool(zhiyi_entry or explicit_direct_authorized)
    platform_ok = bool(platform_action_requested and platform_action_authorized)

    if requested == "platform_act":
        if platform_ok:
            granted = "platform_act"
            reason = "platform_act_explicitly_authorized"
        elif direct_ok:
            granted = "direct_answer"
            reason = "platform_act_requires_explicit_authorization"
        else:
            granted = "passive"
            reason = "platform_act_requires_explicit_authorization"
    elif requested == "direct_answer":
        if direct_ok:
            granted = "direct_answer"
            reason = "direct_answer_explicitly_authorized"
        else:
            granted = "passive"
            reason = "direct_answer_requires_explicit_zhiyi_entry"
    elif requested == "context_inject":
        if context_inject_requested:
            granted = "context_inject"
            reason = "context_inject_explicitly_requested"
        else:
            granted = "recall_only"
            reason = "context_inject_requires_explicit_request"
    elif requested == "recall_only":
        granted = "recall_only"
        reason = "recall_only_context_allowed"
    else:
        granted = "passive"
        reason = "passive_observe_only"

    return memory_authority_receipt(
        requested_authority=requested,
        granted_authority=granted,
        reason=reason,
        source=source,
        explicit_zhiyi_entry=zhiyi_entry,
        platform_action_authorized=platform_action_authorized,
    )


def attach_memory_authority(payload: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(receipt, dict):
        payload["memory_authority"] = receipt
    return payload
