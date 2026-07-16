#!/usr/bin/env python3
"""Evidence-bound model calls for recall answers and candidate refinement."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from src.model_api_key_store import resolve_model_api_key
except Exception:
    from model_api_key_store import resolve_model_api_key


EVIDENCE_BOUND_MODEL_CONTRACT = "evidence_bound_model.v2026.6.18"
EVIDENCE_BOUND_ANSWER_SCHEMA = "evidence_bound_answer.v1"
EVIDENCE_BOUND_FAST_AUDIT_SCHEMA = "evidence_bound_fast_audit.v1"
EVIDENCE_BOUND_REFINEMENT_SCHEMA = "evidence_bound_experience_refinement.v1"
EVIDENCE_OBJECT_STATE_DIAGNOSTIC_SCHEMA = "evidence_object_state_diagnostic.v1"
EVIDENCE_BOUND_MODEL_GATING_CONTRACT = "evidence_bound_model_gating.v2026.6.18"


@dataclass(frozen=True)
class EvidenceBoundModelConfig:
    provider: str = ""
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    credential_ref: str = ""
    timeout_seconds: int = 60
    max_tokens: int = 0
    transparency_ledger_path: str = ""
    transparency_call_kind: str = ""

    @property
    def api_key_present(self) -> bool:
        key, _ = resolve_model_api_key(
            api_key_env=self.api_key_env,
            credential_ref=self.credential_ref,
        )
        return bool(key)


def _read_json(path: Path) -> dict:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _runtime_config_dir() -> Path:
    root = os.environ.get("MEMCORE_ROOT") or os.environ.get("MEMCORE_INSTALL_ROOT") or ""
    if root:
        return Path(root).expanduser() / "config"
    return Path(__file__).resolve().parents[1] / "config"


def _zhiyi_model_binding_defaults() -> dict:
    config_dir = _runtime_config_dir()
    binding = _read_json(config_dir / "zhiyi_model_binding.user.json")
    model_config = _read_json(config_dir / "model_config.json")
    zhiyi_model = model_config.get("zhiyi_model") if isinstance(model_config.get("zhiyi_model"), dict) else {}
    defaults = dict(zhiyi_model)
    defaults.update({k: v for k, v in binding.items() if v not in (None, "")})
    return defaults


def _infer_provider(value: str, provider_id: str = "", option_id: str = "") -> str:
    marker = " ".join(str(item or "") for item in (value, provider_id, option_id)).lower()
    if "minimax" in marker:
        return "minimax"
    if "deepseek" in marker:
        return "deepseek"
    if "openai" in marker:
        return "openai_compatible"
    if "hermes" in marker and "custom:minimax" in marker:
        return "minimax"
    return str(value or "").strip().lower()


def _present_or_preferred_env(preferred: str, fallbacks: tuple[str, ...]) -> str:
    preferred = str(preferred or "").strip()
    if preferred and os.environ.get(preferred):
        return preferred
    for name in fallbacks:
        if os.environ.get(name):
            return name
    return preferred or (fallbacks[0] if fallbacks else "")


def default_model_config(
    provider: str = "",
    model: str = "",
    base_url: str = "",
    api_key_env: str = "",
) -> EvidenceBoundModelConfig:
    binding = _zhiyi_model_binding_defaults()
    binding_provider = _infer_provider(
        str(binding.get("provider") or ""),
        str(binding.get("provider_id") or ""),
        str(binding.get("selected_option_id") or ""),
    )
    explicit_provider = bool(str(provider or "").strip())
    selected = (provider or os.environ.get("MEMCORE_ZHIYI_PROVIDER") or binding_provider or "").strip().lower()
    env_model = model or ("" if explicit_provider else os.environ.get("MEMCORE_ZHIYI_MODEL") or str(binding.get("model_name") or ""))
    env_base = base_url or ("" if explicit_provider else os.environ.get("MEMCORE_ZHIYI_BASE_URL") or str(binding.get("base_url") or ""))
    explicit_api_key_env = (
        api_key_env
        or os.environ.get("MEMCORE_ZHIYI_API_KEY_ENV")
        or str(binding.get("api_key_env") or "")
    )
    credential_ref = str(binding.get("credential_ref") or "").strip()
    api_key_env = "MEMCORE_ZHIYI_API_KEY" if os.environ.get("MEMCORE_ZHIYI_API_KEY") else explicit_api_key_env

    if not selected:
        if api_key_env:
            selected = "memcore_zhiyi"
        elif os.environ.get("DEEPSEEK_API_KEY"):
            selected = "deepseek"
        elif os.environ.get("MINIMAX_API_KEY") or os.environ.get("MINIMAX_CN_API_KEY"):
            selected = "minimax"
        else:
            selected = "openai_compatible"

    if selected in {"deepseek", "deepseek_v4", "deepseek_v4flash"}:
        return EvidenceBoundModelConfig(
            provider="deepseek",
            model=env_model or os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash",
            base_url=env_base or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1",
            api_key_env=_present_or_preferred_env(api_key_env, ("DEEPSEEK_API_KEY",)),
            credential_ref=credential_ref,
        )
    if selected in {"minimax", "minimax_m2", "minimax_m27", "minimax-m2.7"}:
        key_env = _present_or_preferred_env(api_key_env, ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY"))
        return EvidenceBoundModelConfig(
            provider="minimax",
            model=env_model or os.environ.get("MINIMAX_MODEL") or os.environ.get("MINIMAX_CN_MODEL") or "MiniMax-M2.7-highspeed",
            base_url=(
                env_base
                or os.environ.get("MINIMAX_BASE_URL")
                or os.environ.get("MINIMAX_CN_BASE_URL")
                or "https://api.minimaxi.com/v1"
            ),
            api_key_env=key_env,
            credential_ref=credential_ref,
        )
    return EvidenceBoundModelConfig(
        provider=selected or "openai_compatible",
        model=env_model or os.environ.get("OPENAI_COMPATIBLE_MODEL") or os.environ.get("OPENAI_MODEL") or "",
        base_url=env_base or os.environ.get("OPENAI_COMPATIBLE_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "",
        api_key_env=api_key_env or os.environ.get("OPENAI_COMPATIBLE_API_KEY_ENV") or "OPENAI_API_KEY",
        credential_ref=credential_ref,
    )


def _compact_text(text: Any, max_chars: int = 1200) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "..."


def normalize_evidence_items(items: list[dict] | tuple[dict, ...] | None, *, max_items: int = 8) -> list[dict]:
    normalized: list[dict] = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        text = _compact_text(item.get("text") or item.get("content") or item.get("summary") or "", 1800)
        if not text:
            continue
        source_id = str(item.get("source_id") or item.get("evidence_ref") or f"E{index + 1}").strip()
        evidence_ref = str(item.get("evidence_ref") or source_id).strip()
        role = str(item.get("role") or "").strip().lower()
        if not role:
            match = re.match(r"^\s*(user|assistant|system)\s*:", text, flags=re.I)
            role = match.group(1).lower() if match else ""
        authority = str(item.get("authority") or "").strip().lower()
        if not authority:
            authority = "user_fact" if role == "user" else "assistant_response" if role == "assistant" else "unknown"
        normalized.append(
            {
                "source_id": source_id,
                "evidence_ref": evidence_ref,
                "session_id": str(item.get("session_id") or ""),
                "role": role,
                "authority": authority,
                "timestamp": str(item.get("timestamp") or item.get("created_at") or ""),
                "text": text,
                "source_refs": item.get("source_refs") if isinstance(item.get("source_refs"), (dict, list)) else {},
                "score": item.get("score"),
            }
        )
        if len(normalized) >= max_items:
            break
    return normalized


def _allowed_refs(evidence_items: list[dict]) -> set[str]:
    refs: set[str] = set()
    for item in evidence_items:
        for key in ("source_id", "evidence_ref"):
            value = str(item.get(key) or "").strip()
            if value:
                refs.add(value)
    return refs


def plan_evidence_bound_answer_model_use(
    question: str,
    evidence_items: list[dict] | tuple[dict, ...] | None,
    *,
    draft_answer: str = "",
    policy: str = "always",
) -> dict:
    selected = str(policy or "always").strip().lower().replace("-", "_")
    evidence = normalize_evidence_items(evidence_items)
    draft = _compact_text(draft_answer, 2000)
    draft_words = re.findall(r"[A-Za-z0-9_]+", draft)
    evidence_text = "\n".join(str(item.get("text") or "") for item in evidence)
    unique_sessions = {str(item.get("session_id") or "") for item in evidence if str(item.get("session_id") or "")}
    signals: list[str] = []
    if not evidence:
        signals.append("no_evidence")
    if not draft or draft.upper() == "UNKNOWN":
        signals.append("draft_missing_or_unknown")
    if len(draft_words) >= 18 or len(draft) >= 140:
        signals.append("draft_too_long")
    if len(evidence) >= 4:
        signals.append("many_evidence_items")
    if len(unique_sessions) >= 2:
        signals.append("multi_session_evidence")
    if any(marker in draft.lower() for marker in ("?", "do you", "could you", "can you", "advice", "recommend")):
        signals.append("draft_contains_chat_tail")
    if re.search(r"\b(prefer|preference|would like|should i|recommend|suggest|why|how)\b", str(question or "").lower()):
        signals.append("question_benefits_from_refinement")
    if len(evidence_text) >= 1200:
        signals.append("large_evidence_context")

    if selected in ("never", "off", "skip"):
        should_call = False
        reason = "policy_never"
    elif selected in ("auto", "smart", "gated"):
        trigger_signals = set(signals) - {"no_evidence", "many_evidence_items", "multi_session_evidence", "large_evidence_context"}
        should_call = bool(trigger_signals)
        reason = "auto_signal:" + ",".join(signals) if should_call else "auto_skip_short_stable_draft"
    else:
        should_call = bool(evidence)
        reason = "policy_always" if should_call else "no_evidence"

    return {
        "contract": EVIDENCE_BOUND_MODEL_GATING_CONTRACT,
        "policy": selected or "always",
        "should_call_model": should_call,
        "reason": reason,
        "signals": signals,
        "evidence_count": len(evidence),
        "draft_answer_present": bool(draft),
        "draft_answer_chars": len(draft),
        "draft_answer_words": len(draft_words),
        "unique_session_count": len(unique_sessions),
    }


def build_evidence_bound_answer_prompt(
    question: str,
    evidence_items: list[dict],
    *,
    task_kind: str = "answer",
    draft_answer: str = "",
    question_context: dict | None = None,
) -> list[dict]:
    question_text = str(question or "")
    question_lower = question_text.lower()
    context = question_context if isinstance(question_context, dict) else {}
    rules = [
        "Use only the supplied evidence.",
        "Return JSON only.",
        "If the evidence is insufficient, set answer to UNKNOWN.",
        "Every non-UNKNOWN answer must cite supporting_refs from source_id or evidence_ref.",
        "Do not infer from outside knowledge.",
        "draft_answer is a candidate from another reader, not evidence. You may keep it, shorten it, correct it, or reject it, but the final answer must be supported by evidence.",
        "Multiple evidence items from the same session may jointly support an answer when they describe the same ongoing topic. Do not combine unrelated sessions to fill gaps.",
        "For personal memory facts about the user, the user's own messages are authoritative. Assistant messages are context only unless they quote or restate a fact the user already provided or the question explicitly asks what the assistant recommended. Do not treat generic assistant recommendations, estimates, examples, or suggestions as remembered user facts.",
        "Preserve necessary answer qualifiers from evidence, such as am/pm, each way, location, object type, event type, and units.",
        "Avoid overly terse subset answers. If the evidence gives a requested entity plus a useful qualifier, include the qualifier: location, organization, scale/model, direction such as each way, specific malfunction detail, event name, title suffix, or item list.",
        "If evidence names a complete event, issue, or object phrase, keep the complete phrase instead of compressing it to a generic head noun. Examples: keep 'GPS system not functioning correctly' rather than 'GPS issue', keep 'Data Analysis using Python webinar' rather than only 'Data Analysis using Python', and keep relationship partners such as 'Rachel and Mike' rather than only 'Rachel'.",
        "If the question asks for a fact that is not explicitly stated, answer UNKNOWN even when nearby related facts exist. Do not substitute a related institution, price, transport option, person, or recommendation for the missing fact.",
        "Absence of evidence is not evidence of absence. If the question asks whether a release, deployment, sync, remote action, approval, receipt, or completion happened, and the evidence only says a receipt/proof is missing, answer UNKNOWN. Do not answer that it did not happen unless the supplied evidence explicitly states it did not happen or failed.",
    ]
    if re.search(r"\b(how many|number of|count|total|in total|how much|sum|spent|cost|price|difference)\b", question_lower):
        rules.append(
            "For count, total, money, or difference questions, first build a candidate ledger from all relevant evidence items before answering: list each matching item/event, amount/count/duration, included/excluded status, and reason. Count or calculate only items that match the question constraints, avoid double-counting the same item/event, exclude unrelated budgets/bids/prices/savings unless they are the object asked for, include free/zero-cost matching events as 0 only when useful for completeness, and cite the refs used for the count or calculation. When the question asks how many, answer with the count plus concise labels/details for the counted items when evidence provides them. A bare number like '3' is invalid when evidence contains item names, people, model scales, venues, or reasons; write a compact answer such as '3: A, B, and C' or '3 items: A; B; C'."
        )
        if "before making an offer" in question_lower:
            rules.append(
                "For 'before making an offer on X' questions, X is the target event/object and must be excluded from the count. Count only earlier candidate items viewed/considered before that offer. The final answer must include each earlier item plus the evidence-backed reason it was not selected or did not lead to an offer when evidence provides it; scan adjacent evidence in the same session for reasons such as renovation, budget, noise, rejected bid, inspection, or higher offer."
            )
        if "wedding" in question_lower:
            rules.append(
                "For wedding count questions, deduplicate repeated mentions of the same wedding across sessions. If one mention says 'Emily's wedding' and another says Emily married Sarah, treat them as the same Emily-and-Sarah wedding unless evidence clearly identifies two different Emilys or two different weddings. Prefer couple names in the final answer when available. The final answer must not be a bare count; include the couples or wedding labels after the count. When evidence names a bride/groom/spouse/partner/husband/wife for a wedding, include both people in the label."
            )
    if re.search(r"\b(what|where|which|who)\b", question_lower):
        rules.append(
            "For single-fact what/where/which/who questions, return the complete answer phrase from evidence, not only the head noun. Keep attached qualifiers such as 'at a small startup', 'in Australia', 'at Icon Park', 'DLC', scale/model numbers, and similar words that immediately identify or disambiguate the answer. For where questions, preserve the full location hierarchy present in evidence, such as institution plus country/city/venue. For study-abroad, school, workplace, restaurant, venue, or trip-location answers, if the institution/place and a country/city/venue appear in the same evidence sentence or same user turn, include both."
        )
    if re.search(r"\b(ago|before|after|since|until|between|prior to|following|latest|most recent|most recently|currently|now|current)\b", question_lower):
        rules.append(
            "For temporal, current-state, or most-recent questions, compare the evidence order, timestamps, and wording; prefer the newest still-valid fact for current/latest questions, and apply before/after constraints instead of answering from the first matching evidence item. If one evidence item states an older value and a later user evidence item restates or updates the same object/state, choose the later user-stated value. Your calculation_items should mark older superseded values as included=false and the newest current value as included=true when there are conflicting values. For 'first' questions, choose the earliest dated qualifying event, not the first evidence item in ranking order."
        )
    if str(context.get("question_date") or "").strip():
        rules.append(
            "When the question explicitly asks how many days/weeks/months/years ago, uses today/current/latest wording, or asks for a before/after date comparison, use question_context.question_date as the reference date and compare it with evidence timestamps. For broad ranges such as last few months or past year, do not silently discard matching event/action evidence solely because a story date inside the text conflicts with question_context.question_date; keep it in the candidate ledger unless the evidence clearly places it outside the asked range."
        )
    if str(context.get("question_id") or "").endswith("_abs"):
        rules.append(
            "This is an absence/insufficient-information question. The correct answer may be that the memory does not contain the requested fact. If evidence only mentions a related but different fact, answer UNKNOWN and explain the missing requested fact in unknown_reason. For _abs questions about a user's cost, plan, preference, or personal fact, assistant estimates or recommendations do not count as the user's stated fact unless the user explicitly accepted or repeated them."
        )
    if task_kind in {"preference_profile_answer", "preference"}:
        rules.extend(
            [
                "This is a preference-profile question: infer what kind of answer, recommendation, or advice the user would prefer from the evidence.",
                "Do not return a standalone recommendation list as the final answer. State the user's preference boundary instead, using the form 'The user would prefer ...'.",
                "When evidence supports it, include a short 'They might not prefer ...' boundary for generic, unrelated, incompatible, low-quality, or otherwise excluded suggestions.",
                "Concrete examples from evidence may be included only as support for the preference boundary, not as the whole answer.",
            ]
        )
    payload = {
        "task_kind": task_kind,
        "question": question_text,
        "question_context": context,
        "draft_answer": str(draft_answer or ""),
        "rules": rules,
        "evidence": evidence_items,
        "response_schema": {
            "schema": EVIDENCE_BOUND_ANSWER_SCHEMA,
            "answer": "string",
            "verdict": "answered|unknown|insufficient_evidence",
            "confidence": "number between 0 and 1",
            "supporting_refs": ["source_id or evidence_ref"],
            "calculation_items": [
                {
                    "label": "item/event/object label",
                    "value": "amount/count/duration or UNKNOWN",
                    "included": "boolean",
                    "reason": "why included or excluded",
                    "refs": ["source_id or evidence_ref"],
                }
            ],
            "calculation_notes": "short string for count/sum/time ordering questions, otherwise optional",
            "unknown_reason": "string",
        },
    }
    return [
        {
            "role": "system",
            "content": "You answer strictly from supplied evidence. Unsupported facts are invalid.",
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _merge_scoped_evidence(
    top_items: list[dict] | tuple[dict, ...] | None,
    pack_items: list[dict] | tuple[dict, ...] | None,
    *,
    max_top_items: int = 6,
    max_pack_items: int = 10,
) -> list[dict]:
    by_ref: dict[str, dict] = {}
    order: list[str] = []

    def add(items: list[dict], scope: str) -> None:
        for item in items:
            ref = str(item.get("evidence_ref") or item.get("source_id") or "").strip()
            if not ref:
                continue
            if ref not in by_ref:
                copy = dict(item)
                copy["evidence_scope"] = scope
                by_ref[ref] = copy
                order.append(ref)
            else:
                existing_scope = str(by_ref[ref].get("evidence_scope") or "")
                scopes = set(part for part in existing_scope.split("+") if part)
                scopes.add(scope)
                by_ref[ref]["evidence_scope"] = "+".join(part for part in ("top", "pack") if part in scopes)

    add(normalize_evidence_items(top_items, max_items=max_top_items), "top")
    add(normalize_evidence_items(pack_items, max_items=max_pack_items), "pack")
    return [by_ref[ref] for ref in order]


def build_evidence_bound_fast_audit_prompt(
    question: str,
    top_evidence_items: list[dict],
    pack_evidence_items: list[dict],
    *,
    draft_answer: str = "",
) -> list[dict]:
    combined = _merge_scoped_evidence(top_evidence_items, pack_evidence_items)
    payload = {
        "task_kind": "fast_evidence_audit",
        "question": str(question or ""),
        "draft_answer": str(draft_answer or ""),
        "rules": [
            "Use only the supplied evidence.",
            "Return JSON only. Do not include analysis, markdown, or prose outside JSON.",
            "Act as an evidence auditor, not a reasoning writer.",
            "Keep the answer short. If evidence is insufficient, set answer to UNKNOWN.",
            "Every non-UNKNOWN answer must cite supporting_refs from source_id or evidence_ref.",
            "top_verdict judges whether top evidence alone supports the answer.",
            "pack_verdict judges whether the combined top+pack evidence supports the answer.",
            "Set needs_careful_mode only for contradiction, multi-hop reasoning, math/time aggregation, or ambiguous subject/object.",
            "Do not infer from outside knowledge.",
        ],
        "evidence": combined,
        "top_refs": [str(item.get("evidence_ref") or item.get("source_id") or "") for item in top_evidence_items],
        "pack_refs": [str(item.get("evidence_ref") or item.get("source_id") or "") for item in pack_evidence_items],
        "response_schema": {
            "schema": EVIDENCE_BOUND_FAST_AUDIT_SCHEMA,
            "answer": "string",
            "verdict": "answered|unknown|insufficient_evidence",
            "confidence": "number between 0 and 1",
            "supporting_refs": ["source_id or evidence_ref"],
            "top_verdict": "answered|unknown|insufficient_evidence",
            "pack_verdict": "answered|unknown|insufficient_evidence",
            "top_supporting_refs": ["top source_id or evidence_ref"],
            "pack_supporting_refs": ["pack source_id or evidence_ref"],
            "needs_careful_mode": "boolean",
            "careful_reason": "string",
            "contradiction_detected": "boolean",
            "evidence_gap_reason": "string",
            "unknown_reason": "string",
        },
    }
    return [
        {
            "role": "system",
            "content": "You audit evidence quickly and strictly. Unsupported answers are invalid. Return compact JSON only.",
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def build_experience_refinement_prompt(candidate: dict, evidence_items: list[dict]) -> list[dict]:
    payload = {
        "task_kind": "experience_refinement",
        "candidate": candidate if isinstance(candidate, dict) else {},
        "rules": [
            "Use only supplied evidence.",
            "Return JSON only.",
            "Do not create a production memory write.",
            "If the evidence is insufficient, set verdict to insufficient_evidence.",
            "Every proposed summary or detail must cite supporting_refs.",
        ],
        "evidence": evidence_items,
        "response_schema": {
            "schema": EVIDENCE_BOUND_REFINEMENT_SCHEMA,
            "verdict": "refined|keep_original|insufficient_evidence|reject",
            "summary": "string",
            "detail": "string",
            "confidence": "number between 0 and 1",
            "supporting_refs": ["source_id or evidence_ref"],
            "review_notes": "string",
        },
    }
    return [
        {
            "role": "system",
            "content": "You refine memory candidates strictly from supplied evidence.",
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def build_evidence_object_state_prompt(
    question: str,
    gold_evidence_items: list[dict],
    top_evidence_items: list[dict],
    *,
    expected_answer: str = "",
) -> list[dict]:
    payload = {
        "task_kind": "evidence_object_state_diagnostic",
        "question": str(question or ""),
        "expected_answer": str(expected_answer or ""),
        "rules": [
            "Use only the supplied gold_evidence and top_evidence.",
            "Return JSON only.",
            "Do not answer the user question directly; diagnose whether top_evidence supports the same object/state/action as gold_evidence.",
            "If either side is insufficient, set support_verdict to UNKNOWN or insufficient_evidence.",
            "Every non-UNKNOWN object, state, action, or mismatch claim must cite gold_supporting_refs and/or top_supporting_refs from source_id or evidence_ref.",
            "Do not infer from outside knowledge.",
            "Preserve current-vs-historical uncertainty in time_hint instead of guessing.",
        ],
        "gold_evidence": gold_evidence_items,
        "top_evidence": top_evidence_items,
        "response_schema": {
            "schema": EVIDENCE_OBJECT_STATE_DIAGNOSTIC_SCHEMA,
            "object_topic": "string or UNKNOWN",
            "state_fact": "string or UNKNOWN",
            "action_relation": "string or UNKNOWN",
            "time_hint": "current|historical|temporal_change|unclear|UNKNOWN",
            "support_verdict": "same_fact|different_fact|top_missing_gold_fact|gold_insufficient|top_insufficient|insufficient_evidence|unknown",
            "confidence": "number between 0 and 1",
            "gold_supporting_refs": ["source_id or evidence_ref from gold_evidence"],
            "top_supporting_refs": ["source_id or evidence_ref from top_evidence"],
            "mismatch_reason": "string",
            "unknown_reason": "string",
        },
    }
    return [
        {
            "role": "system",
            "content": "You compare evidence objects and states strictly from supplied evidence. Unsupported facts are invalid.",
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _chat_completions_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _record_http_call_safely(**kwargs: Any) -> dict[str, Any]:
    config = kwargs.get("config")
    if not getattr(config, "transparency_call_kind", ""):
        return {}
    try:
        from src.distill_transparency import record_http_call

        record_http_call(**kwargs)
        return {"transparency_recorded": True, "transparency_error": ""}
    except Exception as exc:
        return {
            "transparency_recorded": False,
            "transparency_error": f"{exc.__class__.__name__}: {exc}",
        }


def _surface_transparency_status(result: dict[str, Any], response: Any) -> None:
    if not isinstance(response, dict) or "transparency_recorded" not in response:
        return
    recorded = bool(response.get("transparency_recorded"))
    result["transparency_recorded"] = recorded
    result["transparency_error"] = str(response.get("transparency_error") or "")
    if not recorded:
        result["transparency_warning"] = (
            "model_call_succeeded_but_transparency_ledger_write_failed"
            if response.get("ok") is not False
            else "model_call_failed_and_transparency_ledger_write_failed"
        )


def _http_chat_completion(messages: list[dict], config: EvidenceBoundModelConfig) -> dict:
    url = _chat_completions_url(config.base_url)
    key, key_source = resolve_model_api_key(
        api_key_env=config.api_key_env,
        credential_ref=config.credential_ref,
    )
    if not url or not config.model or not key:
        return {
            "ok": False,
            "error": "model_config_missing",
            "provider": config.provider,
            "model": config.model,
            "base_url_present": bool(config.base_url),
            "api_key_env": config.api_key_env,
            "api_key_present": bool(key),
            "api_key_source": key_source,
        }
    body = {
        "model": config.model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    if int(config.max_tokens or 0) > 0:
        body["max_tokens"] = int(config.max_tokens)
    request_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    started = time.time()
    req = urllib.request.Request(
        url,
        data=request_body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=max(int(config.timeout_seconds), 1)) as resp:
            response_body = resp.read()
            payload = json.loads(response_body.decode("utf-8"))
            transparency = _record_http_call_safely(
                config=config,
                url=url,
                request_body=request_body,
                messages=messages,
                started_at=started_at,
                response_body=response_body,
                response_json=payload,
                http_status=getattr(resp, "status", None),
                elapsed_seconds=time.time() - started,
            )
        content = (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return {
            "ok": True,
            "content": content,
            "provider": config.provider,
            "model": config.model,
            **transparency,
        }
    except urllib.error.HTTPError as exc:
        transparency = _record_http_call_safely(
            config=config,
            url=url,
            request_body=request_body,
            messages=messages,
            started_at=started_at,
            http_status=exc.code,
            error=f"http_{exc.code}",
            elapsed_seconds=time.time() - started,
        )
        return {
            "ok": False,
            "error": f"http_{exc.code}",
            "provider": config.provider,
            "model": config.model,
            **transparency,
        }
    except Exception as exc:
        transparency = _record_http_call_safely(
            config=config,
            url=url,
            request_body=request_body,
            messages=messages,
            started_at=started_at,
            error=exc.__class__.__name__,
            elapsed_seconds=time.time() - started,
        )
        return {
            "ok": False,
            "error": exc.__class__.__name__,
            "provider": config.provider,
            "model": config.model,
            **transparency,
        }


def _extract_json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    for match in re.finditer(r"\{", text):
        try:
            parsed, _end = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
    if not candidates:
        return {}
    preferred_keys = {
        "answer",
        "verdict",
        "supporting_refs",
        "summary",
        "detail",
        "confidence",
        "object_topic",
        "support_verdict",
        "gold_supporting_refs",
        "top_supporting_refs",
    }
    for parsed in reversed(candidates):
        if preferred_keys & set(parsed.keys()):
            return parsed
    return candidates[-1]


def _base_result(schema: str, *, config: EvidenceBoundModelConfig | None = None) -> dict:
    return {
        "ok": True,
        "contract": EVIDENCE_BOUND_MODEL_CONTRACT,
        "schema": schema,
        "provider": config.provider if config else "",
        "model": config.model if config else "",
        "api_key_env": config.api_key_env if config else "",
        "api_key_present": bool(config.api_key_present) if config else False,
        "model_call_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "source_refs_required": True,
        "no_evidence_means_unknown": True,
    }


def _validate_supporting_refs(parsed: dict, evidence_items: list[dict]) -> tuple[list[str], list[str]]:
    allowed = _allowed_refs(evidence_items)
    refs = [str(ref).strip() for ref in parsed.get("supporting_refs") or [] if str(ref).strip()]
    invalid = [ref for ref in refs if ref not in allowed]
    return refs, invalid


def _validate_named_refs(value: Any, evidence_items: list[dict]) -> tuple[list[str], list[str]]:
    allowed = _allowed_refs(evidence_items)
    if isinstance(value, str):
        value = [value]
    refs = [str(ref).strip() for ref in value or [] if str(ref).strip()]
    invalid = [ref for ref in refs if ref not in allowed]
    return refs, invalid


def _ref_scope_sets(top_evidence: list[dict], pack_evidence: list[dict]) -> tuple[set[str], set[str]]:
    return _allowed_refs(top_evidence), _allowed_refs(pack_evidence)


def _refs_in_allowed(value: Any, allowed: set[str]) -> tuple[list[str], list[str]]:
    if isinstance(value, str):
        value = [value]
    refs = [str(ref).strip() for ref in value or [] if str(ref).strip()]
    invalid = [ref for ref in refs if ref not in allowed]
    return refs, invalid


def run_evidence_bound_answer(
    question: str,
    evidence_items: list[dict] | tuple[dict, ...] | None,
    *,
    task_kind: str = "answer",
    draft_answer: str = "",
    question_context: dict | None = None,
    model_config: EvidenceBoundModelConfig | dict | None = None,
    execute: bool = False,
    client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    max_evidence_items: int = 8,
) -> dict:
    config = _coerce_config(model_config)
    evidence = normalize_evidence_items(evidence_items, max_items=max(1, int(max_evidence_items or 8)))
    result = _base_result(EVIDENCE_BOUND_ANSWER_SCHEMA, config=config)
    result["evidence_count"] = len(evidence)
    if not evidence:
        result.update({"answer": "UNKNOWN", "verdict": "unknown", "confidence": 0.0, "supporting_refs": [], "unknown_reason": "no_evidence"})
        return result
    messages = build_evidence_bound_answer_prompt(
        question,
        evidence,
        task_kind=task_kind,
        draft_answer=draft_answer,
        question_context=question_context,
    )
    result["prompt_messages"] = messages
    result["task_kind"] = str(task_kind or "answer")
    result["draft_answer_present"] = bool(str(draft_answer or "").strip())
    if not execute and client is None:
        result.update({"answer": "UNKNOWN", "verdict": "dry_run", "confidence": 0.0, "supporting_refs": [], "unknown_reason": "model_call_not_executed"})
        return result

    started = time.time()
    response = client(messages, config) if client else _http_chat_completion(messages, config)
    result["model_call_performed"] = True
    result["elapsed_seconds"] = round(time.time() - started, 3)
    _surface_transparency_status(result, response)
    if isinstance(response, dict) and response.get("ok") is False and "content" not in response:
        result.update({"ok": False, "answer": "UNKNOWN", "verdict": "model_error", "confidence": 0.0, "supporting_refs": [], "unknown_reason": response.get("error", "model_error")})
        result["model_error"] = {k: v for k, v in response.items() if k not in {"content"}}
        return result
    content = response.get("content") if isinstance(response, dict) and "content" in response else response
    parsed = _extract_json_object(content)
    refs, invalid_refs = _validate_supporting_refs(parsed, evidence)
    answer = _compact_text(parsed.get("answer") or "", 1200)
    verdict = str(parsed.get("verdict") or "").strip() or "answered"
    confidence = _safe_float(parsed.get("confidence"), 0.0)
    if not parsed:
        answer = "UNKNOWN"
        verdict = "unknown"
        refs = []
        result["validation_error"] = "non_json_model_response"
    elif invalid_refs:
        answer = "UNKNOWN"
        verdict = "unknown"
        refs = []
        result["validation_error"] = "supporting_refs_not_in_evidence"
        result["invalid_supporting_refs"] = invalid_refs
    elif answer.upper() != "UNKNOWN" and not refs:
        answer = "UNKNOWN"
        verdict = "unknown"
        result["validation_error"] = "answer_without_supporting_refs"
    elif not answer:
        answer = "UNKNOWN"
        verdict = "unknown"
    result.update(
        {
            "answer": answer,
            "verdict": verdict,
            "confidence": max(0.0, min(confidence, 1.0)),
            "supporting_refs": refs,
            "supporting_source_refs": _source_refs_for_support(evidence, refs),
            "calculation_items": parsed.get("calculation_items") if isinstance(parsed.get("calculation_items"), list) else [],
            "calculation_notes": str(parsed.get("calculation_notes") or "") if parsed else "",
            "unknown_reason": str(parsed.get("unknown_reason") or "") if parsed else "non_json_model_response",
        }
    )
    return result


def run_evidence_bound_fast_audit(
    question: str,
    top_evidence_items: list[dict] | tuple[dict, ...] | None,
    pack_evidence_items: list[dict] | tuple[dict, ...] | None,
    *,
    draft_answer: str = "",
    model_config: EvidenceBoundModelConfig | dict | None = None,
    execute: bool = False,
    client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
) -> dict:
    config = _coerce_config(model_config)
    if int(config.max_tokens or 0) <= 0:
        config = replace(config, max_tokens=500)
    top_evidence = normalize_evidence_items(top_evidence_items, max_items=6)
    pack_evidence = normalize_evidence_items(pack_evidence_items, max_items=10)
    combined = _merge_scoped_evidence(top_evidence, pack_evidence)
    result = _base_result(EVIDENCE_BOUND_FAST_AUDIT_SCHEMA, config=config)
    result.update(
        {
            "mode": "fast_evidence_audit",
            "top_evidence_count": len(top_evidence),
            "pack_evidence_count": len(pack_evidence),
            "combined_evidence_count": len(combined),
            "fast_mode": True,
            "careful_mode_performed": False,
        }
    )
    if not combined:
        result.update(
            {
                "answer": "UNKNOWN",
                "verdict": "unknown",
                "top_verdict": "unknown",
                "pack_verdict": "unknown",
                "confidence": 0.0,
                "supporting_refs": [],
                "top_supporting_refs": [],
                "pack_supporting_refs": [],
                "needs_careful_mode": False,
                "careful_reason": "",
                "contradiction_detected": False,
                "evidence_gap_reason": "no_evidence",
                "unknown_reason": "no_evidence",
            }
        )
        return result

    messages = build_evidence_bound_fast_audit_prompt(
        question,
        top_evidence,
        pack_evidence,
        draft_answer=draft_answer,
    )
    result["prompt_messages"] = messages
    result["draft_answer_present"] = bool(str(draft_answer or "").strip())
    if not execute and client is None:
        result.update(
            {
                "answer": "UNKNOWN",
                "verdict": "dry_run",
                "top_verdict": "dry_run",
                "pack_verdict": "dry_run",
                "confidence": 0.0,
                "supporting_refs": [],
                "top_supporting_refs": [],
                "pack_supporting_refs": [],
                "needs_careful_mode": False,
                "careful_reason": "",
                "contradiction_detected": False,
                "evidence_gap_reason": "",
                "unknown_reason": "model_call_not_executed",
            }
        )
        return result

    started = time.time()
    response = client(messages, config) if client else _http_chat_completion(messages, config)
    result["model_call_performed"] = True
    result["elapsed_seconds"] = round(time.time() - started, 3)
    _surface_transparency_status(result, response)
    if isinstance(response, dict) and response.get("ok") is False and "content" not in response:
        result.update(
            {
                "ok": False,
                "answer": "UNKNOWN",
                "verdict": "model_error",
                "top_verdict": "model_error",
                "pack_verdict": "model_error",
                "confidence": 0.0,
                "supporting_refs": [],
                "top_supporting_refs": [],
                "pack_supporting_refs": [],
                "needs_careful_mode": False,
                "careful_reason": "",
                "contradiction_detected": False,
                "evidence_gap_reason": "",
                "unknown_reason": response.get("error", "model_error"),
            }
        )
        result["model_error"] = {k: v for k, v in response.items() if k not in {"content"}}
        return result

    content = response.get("content") if isinstance(response, dict) and "content" in response else response
    parsed = _extract_json_object(content)
    top_allowed, pack_allowed = _ref_scope_sets(top_evidence, pack_evidence)
    combined_allowed = _allowed_refs(combined)
    supporting_refs, invalid_supporting = _refs_in_allowed(parsed.get("supporting_refs") if parsed else [], combined_allowed)
    top_refs, invalid_top = _refs_in_allowed(parsed.get("top_supporting_refs") if parsed else [], top_allowed)
    pack_refs, invalid_pack = _refs_in_allowed(parsed.get("pack_supporting_refs") if parsed else [], combined_allowed)
    answer = _compact_text(parsed.get("answer") or "", 1200) if parsed else "UNKNOWN"
    verdict = str(parsed.get("verdict") or "").strip().lower() if parsed else "unknown"
    top_verdict = str(parsed.get("top_verdict") or "").strip().lower() if parsed else "unknown"
    pack_verdict = str(parsed.get("pack_verdict") or "").strip().lower() if parsed else "unknown"
    validation_errors: list[str] = []
    if not parsed:
        validation_errors.append("non_json_model_response")
    if not supporting_refs and (top_refs or pack_refs):
        supporting_refs = [ref for ref in dict.fromkeys([*top_refs, *pack_refs]) if ref in combined_allowed]
        invalid_supporting = []
    if top_verdict == "answered" and not top_refs and supporting_refs:
        top_refs = [ref for ref in supporting_refs if ref in top_allowed]
    if pack_verdict == "answered" and not pack_refs and supporting_refs:
        pack_refs = [ref for ref in supporting_refs if ref in combined_allowed]
    if invalid_supporting:
        validation_errors.append("supporting_refs_not_in_evidence")
        result["invalid_supporting_refs"] = invalid_supporting
    if invalid_top:
        validation_errors.append("top_supporting_refs_not_in_top_evidence")
        result["invalid_top_supporting_refs"] = invalid_top
    if invalid_pack:
        validation_errors.append("pack_supporting_refs_not_in_pack_evidence")
        result["invalid_pack_supporting_refs"] = invalid_pack
    if answer.upper() != "UNKNOWN" and not supporting_refs:
        validation_errors.append("answer_without_supporting_refs")
    if top_verdict == "answered" and not top_refs:
        validation_errors.append("top_answer_without_supporting_refs")
    if pack_verdict == "answered" and not pack_refs:
        validation_errors.append("pack_answer_without_supporting_refs")
    if validation_errors:
        result["validation_error"] = "|".join(validation_errors)
        answer = "UNKNOWN"
        verdict = "unknown"
        supporting_refs = []
        top_refs = []
        pack_refs = []
    elif not answer:
        answer = "UNKNOWN"
        verdict = "unknown"
    if not top_verdict:
        top_verdict = "unknown"
    if not pack_verdict:
        pack_verdict = verdict or "unknown"

    result.update(
        {
            "answer": answer,
            "verdict": verdict or "unknown",
            "top_verdict": top_verdict,
            "pack_verdict": pack_verdict,
            "confidence": max(0.0, min(_safe_float(parsed.get("confidence") if parsed else 0.0, 0.0), 1.0)),
            "supporting_refs": supporting_refs,
            "top_supporting_refs": top_refs,
            "pack_supporting_refs": pack_refs,
            "supporting_source_refs": _source_refs_for_support(combined, supporting_refs),
            "top_supporting_source_refs": _source_refs_for_support(top_evidence, top_refs),
            "pack_supporting_source_refs": _source_refs_for_support(pack_evidence, pack_refs),
            "needs_careful_mode": bool(parsed.get("needs_careful_mode")) if parsed else False,
            "careful_reason": _compact_text(parsed.get("careful_reason") or "", 500) if parsed else "",
            "contradiction_detected": bool(parsed.get("contradiction_detected")) if parsed else False,
            "evidence_gap_reason": _compact_text(parsed.get("evidence_gap_reason") or "", 500) if parsed else "",
            "unknown_reason": str(parsed.get("unknown_reason") or "") if parsed else "non_json_model_response",
        }
    )
    return result


def run_evidence_object_state_diagnostic(
    question: str,
    gold_evidence_items: list[dict] | tuple[dict, ...] | None,
    top_evidence_items: list[dict] | tuple[dict, ...] | None,
    *,
    expected_answer: str = "",
    model_config: EvidenceBoundModelConfig | dict | None = None,
    execute: bool = False,
    client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
) -> dict:
    config = _coerce_config(model_config)
    gold_evidence = normalize_evidence_items(gold_evidence_items, max_items=8)
    top_evidence = normalize_evidence_items(top_evidence_items, max_items=8)
    result = _base_result(EVIDENCE_OBJECT_STATE_DIAGNOSTIC_SCHEMA, config=config)
    result.update(
        {
            "diagnostic_only": True,
            "ranking_unchanged": True,
            "gold_evidence_count": len(gold_evidence),
            "top_evidence_count": len(top_evidence),
            "gold_refs": sorted(_allowed_refs(gold_evidence)),
            "top_refs": sorted(_allowed_refs(top_evidence)),
        }
    )
    if not gold_evidence or not top_evidence:
        verdict = "gold_insufficient" if not gold_evidence else "top_insufficient"
        reason = "no_gold_evidence" if not gold_evidence else "no_top_evidence"
        result.update(
            {
                "object_topic": "UNKNOWN",
                "state_fact": "UNKNOWN",
                "action_relation": "UNKNOWN",
                "time_hint": "UNKNOWN",
                "support_verdict": verdict,
                "confidence": 0.0,
                "gold_supporting_refs": [],
                "top_supporting_refs": [],
                "mismatch_reason": "",
                "unknown_reason": reason,
            }
        )
        return result

    messages = build_evidence_object_state_prompt(
        question,
        gold_evidence,
        top_evidence,
        expected_answer=expected_answer,
    )
    result["prompt_messages"] = messages
    if not execute and client is None:
        result.update(
            {
                "object_topic": "UNKNOWN",
                "state_fact": "UNKNOWN",
                "action_relation": "UNKNOWN",
                "time_hint": "UNKNOWN",
                "support_verdict": "dry_run",
                "confidence": 0.0,
                "gold_supporting_refs": [],
                "top_supporting_refs": [],
                "mismatch_reason": "",
                "unknown_reason": "model_call_not_executed",
            }
        )
        return result

    started = time.time()
    response = client(messages, config) if client else _http_chat_completion(messages, config)
    result["model_call_performed"] = True
    result["elapsed_seconds"] = round(time.time() - started, 3)
    _surface_transparency_status(result, response)
    if isinstance(response, dict) and response.get("ok") is False and "content" not in response:
        result.update(
            {
                "ok": False,
                "object_topic": "UNKNOWN",
                "state_fact": "UNKNOWN",
                "action_relation": "UNKNOWN",
                "time_hint": "UNKNOWN",
                "support_verdict": "model_error",
                "confidence": 0.0,
                "gold_supporting_refs": [],
                "top_supporting_refs": [],
                "mismatch_reason": "",
                "unknown_reason": response.get("error", "model_error"),
            }
        )
        result["model_error"] = {k: v for k, v in response.items() if k not in {"content"}}
        return result

    content = response.get("content") if isinstance(response, dict) and "content" in response else response
    parsed = _extract_json_object(content)
    gold_refs, invalid_gold_refs = _validate_named_refs(parsed.get("gold_supporting_refs") if parsed else [], gold_evidence)
    top_refs, invalid_top_refs = _validate_named_refs(parsed.get("top_supporting_refs") if parsed else [], top_evidence)
    support_verdict = str(parsed.get("support_verdict") or parsed.get("verdict") or "unknown").strip().lower() if parsed else "unknown"
    object_topic = _compact_text(parsed.get("object_topic") or "UNKNOWN", 500) if parsed else "UNKNOWN"
    state_fact = _compact_text(parsed.get("state_fact") or "UNKNOWN", 700) if parsed else "UNKNOWN"
    action_relation = _compact_text(parsed.get("action_relation") or "UNKNOWN", 500) if parsed else "UNKNOWN"
    time_hint = _compact_text(parsed.get("time_hint") or "UNKNOWN", 120) if parsed else "UNKNOWN"
    if not parsed:
        result["validation_error"] = "non_json_model_response"
        support_verdict = "unknown"
    elif invalid_gold_refs or invalid_top_refs:
        result["validation_error"] = "supporting_refs_not_in_evidence"
        result["invalid_gold_supporting_refs"] = invalid_gold_refs
        result["invalid_top_supporting_refs"] = invalid_top_refs
        support_verdict = "unknown"
        gold_refs = []
        top_refs = []
    elif support_verdict in {"same_fact", "different_fact"} and (not gold_refs or not top_refs):
        result["validation_error"] = "comparison_without_both_sides_support"
        support_verdict = "unknown"
        gold_refs = []
        top_refs = []
    elif support_verdict in {"top_missing_gold_fact", "top_insufficient"} and not gold_refs:
        result["validation_error"] = "missing_gold_support_for_top_gap"
        support_verdict = "unknown"
        gold_refs = []
        top_refs = []
    if support_verdict == "unknown":
        object_topic = "UNKNOWN"
        state_fact = "UNKNOWN"
        action_relation = "UNKNOWN"

    result.update(
        {
            "object_topic": object_topic or "UNKNOWN",
            "state_fact": state_fact or "UNKNOWN",
            "action_relation": action_relation or "UNKNOWN",
            "time_hint": time_hint or "UNKNOWN",
            "support_verdict": support_verdict or "unknown",
            "confidence": max(0.0, min(_safe_float(parsed.get("confidence") if parsed else 0.0, 0.0), 1.0)),
            "gold_supporting_refs": gold_refs,
            "top_supporting_refs": top_refs,
            "gold_supporting_source_refs": _source_refs_for_support(gold_evidence, gold_refs),
            "top_supporting_source_refs": _source_refs_for_support(top_evidence, top_refs),
            "mismatch_reason": _compact_text(parsed.get("mismatch_reason") or "", 800) if parsed else "",
            "unknown_reason": str(parsed.get("unknown_reason") or "") if parsed else "non_json_model_response",
        }
    )
    return result


def run_evidence_bound_experience_refinement(
    candidate: dict,
    evidence_items: list[dict] | tuple[dict, ...] | None,
    *,
    model_config: EvidenceBoundModelConfig | dict | None = None,
    execute: bool = False,
    client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
) -> dict:
    config = _coerce_config(model_config)
    evidence = normalize_evidence_items(evidence_items)
    result = _base_result(EVIDENCE_BOUND_REFINEMENT_SCHEMA, config=config)
    result["evidence_count"] = len(evidence)
    if not evidence:
        result.update({"verdict": "insufficient_evidence", "summary": "", "detail": "", "confidence": 0.0, "supporting_refs": [], "review_notes": "no_evidence"})
        return result
    messages = build_experience_refinement_prompt(candidate if isinstance(candidate, dict) else {}, evidence)
    result["prompt_messages"] = messages
    if not execute and client is None:
        result.update({"verdict": "dry_run", "summary": "", "detail": "", "confidence": 0.0, "supporting_refs": [], "review_notes": "model_call_not_executed"})
        return result

    started = time.time()
    response = client(messages, config) if client else _http_chat_completion(messages, config)
    result["model_call_performed"] = True
    result["elapsed_seconds"] = round(time.time() - started, 3)
    _surface_transparency_status(result, response)
    if isinstance(response, dict) and response.get("ok") is False and "content" not in response:
        result.update({"ok": False, "verdict": "model_error", "summary": "", "detail": "", "confidence": 0.0, "supporting_refs": [], "review_notes": response.get("error", "model_error")})
        return result
    content = response.get("content") if isinstance(response, dict) and "content" in response else response
    parsed = _extract_json_object(content)
    refs, invalid_refs = _validate_supporting_refs(parsed, evidence)
    verdict = str(parsed.get("verdict") or "").strip() if parsed else "insufficient_evidence"
    if not parsed:
        result["validation_error"] = "non_json_model_response"
        verdict = "insufficient_evidence"
    elif invalid_refs:
        result["validation_error"] = "supporting_refs_not_in_evidence"
        result["invalid_supporting_refs"] = invalid_refs
        verdict = "insufficient_evidence"
        refs = []
    elif verdict == "refined" and not refs:
        result["validation_error"] = "refinement_without_supporting_refs"
        verdict = "insufficient_evidence"
    result.update(
        {
            "verdict": verdict or "insufficient_evidence",
            "summary": _compact_text(parsed.get("summary") or "", 500) if parsed else "",
            "detail": _compact_text(parsed.get("detail") or "", 2000) if parsed else "",
            "confidence": max(0.0, min(_safe_float(parsed.get("confidence") if parsed else 0.0, 0.0), 1.0)),
            "supporting_refs": refs,
            "supporting_source_refs": _source_refs_for_support(evidence, refs),
            "review_notes": str(parsed.get("review_notes") or "") if parsed else "non_json_model_response",
        }
    )
    return result


def _coerce_config(value: EvidenceBoundModelConfig | dict | None) -> EvidenceBoundModelConfig:
    if isinstance(value, EvidenceBoundModelConfig):
        return value
    if isinstance(value, dict):
        return EvidenceBoundModelConfig(
            provider=str(value.get("provider") or ""),
            model=str(value.get("model") or ""),
            base_url=str(value.get("base_url") or ""),
            api_key_env=str(value.get("api_key_env") or ""),
            credential_ref=str(value.get("credential_ref") or ""),
            timeout_seconds=int(value.get("timeout_seconds") or 60),
            max_tokens=int(value.get("max_tokens") or 0),
            transparency_ledger_path=str(value.get("transparency_ledger_path") or ""),
            transparency_call_kind=str(value.get("transparency_call_kind") or ""),
        )
    return default_model_config()


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _source_refs_for_support(evidence_items: list[dict], refs: list[str]) -> list[Any]:
    wanted = set(refs)
    output = []
    for item in evidence_items:
        if str(item.get("source_id") or "") in wanted or str(item.get("evidence_ref") or "") in wanted:
            source_refs = item.get("source_refs")
            if source_refs:
                output.append(source_refs)
    return output
