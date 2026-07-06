"""User-relayed agent voiceprint tagging for Time Library evidence.

The classifier is deliberately conservative and additive. It never deletes or
invalidates cards; it only labels likely relay evidence so readers can downgrade
the attribution when a user message appears to paste an agent report.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RELAY_VOICEPRINT_CONTRACT = "time_library_user_relayed_voiceprint.v1"
ANNOTATION_LEDGER_CONTRACT = "time_library_relay_voiceprint_annotations.v1"

AGENT_FIRST_PERSON_PATTERNS = (
    "我上机",
    "我独立",
    "我核",
    "我亲核",
    "我签",
    "我裸验",
    "我裸窗",
    "我复验",
    "我打端点",
    "我 jq",
    "我 grep",
    "我 dd",
)
REPORT_MARKERS = (
    "opus_confirmed",
    "byte-exact",
    "sha-match",
    "nonclaims",
    "source/test",
    "installed runtime",
    "裸窗",
    "二签",
    "复签",
    "终验",
    "回执",
    "签字",
    "上机核",
    "独立验",
)
STRUCTURAL_REPORT_MARKERS = (
    "✅",
    "🔴",
    "⚠️",
    "## ",
    "| 核点 |",
    "nonClaims:",
    "NonClaims:",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_text(value: Any, *, limit: int = 8000) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def candidate_source_author(candidate: dict[str, Any]) -> str:
    refs = candidate.get("source_refs") if isinstance(candidate.get("source_refs"), dict) else {}
    return clean_text(
        candidate.get("source_author")
        or candidate.get("source_role")
        or refs.get("source_author")
        or refs.get("source_role"),
        limit=80,
    ).lower()


def candidate_identifier(candidate: dict[str, Any]) -> str:
    return clean_text(
        candidate.get("library_id")
        or candidate.get("candidate_id")
        or candidate.get("exp_id")
        or candidate.get("id"),
        limit=220,
    )


def evidence_fingerprint(candidate: dict[str, Any]) -> str:
    refs = candidate.get("source_refs") if isinstance(candidate.get("source_refs"), dict) else {}
    offsets = refs.get("byte_offsets") if isinstance(refs.get("byte_offsets"), dict) else {}
    seed = {
        "candidate": candidate_identifier(candidate),
        "source_path": refs.get("source_path") or candidate.get("source_path") or "",
        "byte_offsets": offsets or candidate.get("byte_offsets") or {},
        "verbatim_sha256": candidate.get("verbatim_sha256") or refs.get("verbatim_sha256") or "",
        "verbatim_excerpt_sha": hashlib.sha256(str(candidate.get("verbatim_excerpt") or "").encode("utf-8")).hexdigest(),
    }
    return hashlib.sha256(json.dumps(seed, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def classify_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return an additive attribution annotation for one candidate card."""

    source_author = candidate_source_author(candidate)
    verbatim = str(candidate.get("verbatim_excerpt") or "")
    compact = clean_text(verbatim, limit=8000)
    lower = compact.lower()
    reasons: list[str] = []

    if source_author != "user":
        return {
            "contract": RELAY_VOICEPRINT_CONTRACT,
            "evidence_attribution": "non_user_source",
            "source_author": source_author,
            "risk_level": "none",
            "user_relayed": False,
            "reasons": [],
            "score": 0,
        }

    if len(compact) >= 220:
        reasons.append("long_user_message")
    if any(marker.lower() in lower for marker in AGENT_FIRST_PERSON_PATTERNS):
        reasons.append("agent_first_person_work_verb")
    if "我上机独立量" in compact or "我上机独立测" in compact:
        reasons.append("known_relayed_verification_voice")
    if any(marker.lower() in lower for marker in REPORT_MARKERS):
        reasons.append("report_or_signoff_marker")
    if any(marker in verbatim for marker in STRUCTURAL_REPORT_MARKERS):
        reasons.append("structured_report_marker")
    if re.search(r"\b(PID|SHA|commit|source==installed|catalog-card|/mcp|/catalog-inject)\b", verbatim):
        reasons.append("runtime_report_technical_marker")

    score = 0
    weights = {
        "long_user_message": 1,
        "agent_first_person_work_verb": 3,
        "known_relayed_verification_voice": 4,
        "report_or_signoff_marker": 2,
        "structured_report_marker": 2,
        "runtime_report_technical_marker": 2,
    }
    for reason in reasons:
        score += weights.get(reason, 1)

    user_relayed = score >= 4 or (
        "agent_first_person_work_verb" in reasons
        and ("report_or_signoff_marker" in reasons or "runtime_report_technical_marker" in reasons)
    )
    risk_level = "user_relayed" if user_relayed else ("watch" if reasons else "none")
    return {
        "contract": RELAY_VOICEPRINT_CONTRACT,
        "evidence_attribution": "user_relayed" if user_relayed else "direct_user",
        "source_author": source_author,
        "risk_level": risk_level,
        "user_relayed": user_relayed,
        "reasons": sorted(set(reasons)),
        "score": score,
    }


def apply_annotation(candidate: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(candidate)
    annotation = classify_candidate(annotated)
    annotated["evidence_attribution"] = annotation["evidence_attribution"]
    annotated["relay_voiceprint"] = annotation
    refs = annotated.get("source_refs")
    if isinstance(refs, dict):
        refs = dict(refs)
        refs["evidence_attribution"] = annotation["evidence_attribution"]
        refs["relay_voiceprint"] = annotation
        annotated["source_refs"] = refs
    return annotated


def annotation_path(root: str | Path) -> Path:
    return Path(root) / "output" / "relay_voiceprint" / "annotations.jsonl"


def read_annotations(root: str | Path) -> dict[str, dict[str, Any]]:
    path = annotation_path(root)
    result: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return result
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if not isinstance(item, dict):
            continue
        key = str(item.get("candidate_path") or item.get("library_id") or item.get("fingerprint") or "").strip()
        if key:
            result[key] = item
    return result


def _existing_annotation(candidate: dict[str, Any]) -> dict[str, Any]:
    refs = candidate.get("source_refs") if isinstance(candidate.get("source_refs"), dict) else {}
    for container in (candidate, refs):
        annotation = container.get("relay_voiceprint")
        if isinstance(annotation, dict) and annotation:
            preserved = dict(annotation)
            attribution = (
                preserved.get("evidence_attribution")
                or container.get("evidence_attribution")
                or candidate.get("evidence_attribution")
                or refs.get("evidence_attribution")
                or ""
            )
            if attribution:
                preserved["evidence_attribution"] = attribution
            return preserved
    attribution = candidate.get("evidence_attribution") or refs.get("evidence_attribution")
    if attribution:
        return {"evidence_attribution": str(attribution)}
    return {}


def _attach_annotation(candidate: dict[str, Any], annotation: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(candidate)
    preserved = dict(annotation)
    attribution = preserved.get("evidence_attribution") or annotated.get("evidence_attribution") or "direct_user"
    preserved["evidence_attribution"] = attribution
    annotated["evidence_attribution"] = attribution
    annotated["relay_voiceprint"] = preserved
    refs = annotated.get("source_refs")
    if isinstance(refs, dict):
        refs = dict(refs)
        refs["relay_voiceprint"] = preserved
        refs["evidence_attribution"] = attribution
        annotated["source_refs"] = refs
    return annotated


def merge_annotation(candidate: dict[str, Any], *, candidate_path: str = "", root: str | Path = "") -> dict[str, Any]:
    existing = _existing_annotation(candidate)
    if existing:
        return _attach_annotation(candidate, existing)
    annotations = read_annotations(root) if root else {}
    keys = [
        str(candidate_path or "").strip(),
        str(candidate.get("library_id") or "").strip(),
        evidence_fingerprint(candidate),
    ]
    for key in keys:
        if key and key in annotations:
            annotation = annotations[key].get("relay_voiceprint") if isinstance(annotations[key].get("relay_voiceprint"), dict) else {}
            if annotation:
                return _attach_annotation(candidate, annotation)
    return apply_annotation(candidate)


def append_annotation(root: str | Path, candidate: dict[str, Any], *, candidate_path: str = "", library_id: str = "") -> dict[str, Any]:
    annotated = apply_annotation(candidate)
    annotation = dict(annotated.get("relay_voiceprint") or {})
    event = {
        "contract": ANNOTATION_LEDGER_CONTRACT,
        "created_at": now_iso(),
        "candidate_path": str(candidate_path or ""),
        "candidate_id": candidate_identifier(candidate),
        "library_id": str(library_id or candidate.get("library_id") or ""),
        "fingerprint": evidence_fingerprint(candidate),
        "relay_voiceprint": annotation,
        "write_performed": True,
        "raw_write_performed": False,
        "candidate_delete_performed": False,
        "candidate_status_changed": False,
    }
    path = annotation_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event
