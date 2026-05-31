#!/usr/bin/env python3
"""Zhixing external method signal candidate helpers."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List

try:
    from dialog_intent_router import classify_fine_intent, ROUTE_METHOD_SIGNAL
except Exception:
    from src.dialog_intent_router import classify_fine_intent, ROUTE_METHOD_SIGNAL


METHOD_SIGNAL_VERSION = "2026.5.31"
DEFAULT_PLACEMENT_CANDIDATES = ["toolbook", "xingce", "errata", "replay_eval", "adapter_overlay"]


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


def _refs_from_body(body: Dict[str, Any]) -> Any:
    refs = body.get("source_refs")
    if isinstance(refs, (dict, list)):
        return refs
    source = body.get("source") if isinstance(body.get("source"), dict) else {}
    refs = source.get("source_refs")
    if isinstance(refs, (dict, list)):
        return refs
    source_url = _clean_text(body.get("source_url") or source.get("url"))
    source_path = _clean_text(body.get("source_path") or source.get("path"))
    source_type = _clean_text(body.get("source_type") or source.get("type") or "external_signal")
    out: Dict[str, Any] = {"source_type": source_type}
    if source_url:
        out["source_url"] = source_url
    if source_path:
        out["source_path"] = source_path
    return out if len(out) > 1 else {}


def _candidate_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"method-signal-{digest}"


def _infer_placement_candidates(text: str) -> List[str]:
    lowered = text.lower()
    placements: List[str] = []
    if any(token in lowered for token in ["工具", "平台", "端口", "安装", "配置", "mcp", "auth", "tool", "runbook"]):
        placements.append("toolbook")
    if any(token in lowered for token in ["行策", "经验", "工作流", "踩坑", "workflow", "method", "strategy"]):
        placements.append("xingce")
    if any(token in lowered for token in ["纠错", "错", "勘误", "errata", "correction"]):
        placements.append("errata")
    if any(token in lowered for token in ["replay", "benchmark", "评测", "回放", "eval"]):
        placements.append("replay_eval")
    if any(token in lowered for token in ["codex", "openclaw", "hermes", "claude", "adapter", "overlay"]):
        placements.append("adapter_overlay")
    for item in DEFAULT_PLACEMENT_CANDIDATES:
        if item not in placements:
            placements.append(item)
    return placements


def build_method_signal_candidate(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a review-only method candidate from an external or prior signal."""
    body = body if isinstance(body, dict) else {}
    signal_text = _first_text(body, "signal", "message", "text", "query", "verbatim_excerpt")
    title = _first_text(body, "title") or signal_text[:80].strip()
    verbatim_excerpt = _first_text(body, "verbatim_excerpt", "raw_excerpt") or signal_text
    source = body.get("source") if isinstance(body.get("source"), dict) else {}
    source_label = _first_text(body, "source_label", "source_name") or _clean_text(source.get("label") or source.get("name"))
    source_url = _clean_text(body.get("source_url") or source.get("url"))
    source_path = _clean_text(body.get("source_path") or source.get("path"))
    source_refs = _refs_from_body(body)
    proposed_trigger = _first_text(body, "proposed_trigger", "trigger", "recall_cue")
    proposed_mechanism = _first_text(body, "proposed_mechanism", "mechanism")
    initial_scope = _first_text(body, "initial_scope", "scope") or "needs_review"
    known_failure_modes = _string_list(body.get("known_failure_modes") or body.get("failure_modes"))
    verification_needed = _string_list(body.get("verification_needed") or body.get("verification"))
    placement_candidates = _string_list(body.get("placement_candidates"))
    if not placement_candidates:
        placement_candidates = _infer_placement_candidates(" ".join([signal_text, proposed_mechanism, initial_scope]))
    contraindications = _string_list(body.get("contraindications") or body.get("contraindication"))
    evidence = _string_list(body.get("evidence"))
    route = classify_fine_intent(signal_text or title)
    is_method_signal = route.get("route") == ROUTE_METHOD_SIGNAL
    candidate_id = _candidate_id("|".join([title, signal_text, source_url, source_path]))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidate = {
        "candidate_id": candidate_id,
        "candidate_type": "external_method_signal_candidate",
        "schema_version": METHOD_SIGNAL_VERSION,
        "library_shelf": "incubator",
        "status": "candidate",
        "created_at": now_iso,
        "title": title,
        "signal": signal_text,
        "source": {
            "label": source_label,
            "url": source_url,
            "path": source_path,
        },
        "source_refs": source_refs,
        "verbatim_excerpt": verbatim_excerpt,
        "proposed_trigger": proposed_trigger,
        "proposed_mechanism": proposed_mechanism,
        "initial_scope": initial_scope,
        "known_failure_modes": known_failure_modes,
        "verification_needed": verification_needed,
        "placement_candidates": placement_candidates,
        "contraindications": contraindications,
        "evidence": evidence,
        "matched_intent": route,
        "recommended_action": "review_signal_before_promotion",
        "promotion_path": [
            "signal",
            "method_card_candidate",
            "toolbook_or_xingce_or_errata_candidate",
            "replay_or_benchmark",
            "adopted_or_deprecated_or_superseded",
        ],
        "review_required": True,
        "requires_authorization": True,
        "activation_allowed": False,
        "install_allowed": False,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "skill_write_performed": False,
        "platform_write_performed": False,
        "notes": [
            "candidate_only",
            "external_or_prior_signal_is_not_authority",
            "do_not_install_or_activate_from_signal",
            "recall_before_judgment_when_user_mentions_prior_idea",
        ],
    }
    missing = []
    if not signal_text:
        missing.append("signal")
    if not verbatim_excerpt:
        missing.append("verbatim_excerpt")
    if not source_refs:
        missing.append("source_refs")
    if not is_method_signal and not body.get("allow_non_route_signal"):
        missing.append("method_signal_intent")
    return {
        "ok": not missing,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "candidate_created": not missing,
        "candidate": candidate if not missing else None,
        "candidate_id": candidate_id if not missing else "",
        "missing": missing,
        "intent": route,
        "error": "invalid_method_signal_candidate" if missing else "",
    }


def get_method_signal_contract() -> Dict[str, Any]:
    """Return the read-only contract for external method signal candidates."""
    return {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "version": METHOD_SIGNAL_VERSION,
        "candidate_type": "external_method_signal_candidate",
        "endpoint": "/api/v1/zhixing/method-signals/dry-run",
        "required_fields": ["signal", "source_refs", "verbatim_excerpt"],
        "recommended_fields": [
            "title",
            "source",
            "proposed_trigger",
            "proposed_mechanism",
            "initial_scope",
            "known_failure_modes",
            "verification_needed",
            "placement_candidates",
        ],
        "placement_candidates": DEFAULT_PLACEMENT_CANDIDATES,
        "promotion_path": [
            "signal",
            "method_card_candidate",
            "toolbook_or_xingce_or_errata_candidate",
            "replay_or_benchmark",
            "adopted_or_deprecated_or_superseded",
        ],
        "forbidden_by_default": [
            "install_or_activate_skill",
            "write_durable_memory",
            "write_platform_config",
            "claim_promotion_without_replay_or_benchmark",
        ],
        "notes": [
            "external feed and repository text are signals, not authority",
            "prior user concepts still need source_refs and verbatim_excerpt",
            "this contract supports recall-before-judgment but does not perform recall",
        ],
    }
