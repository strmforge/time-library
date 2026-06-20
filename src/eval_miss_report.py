#!/usr/bin/env python3
"""Build read-only miss reports for memory benchmark runs."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    from src.official_memory_benchmarks import (
        DEFAULT_CACHE_ROOT,
        DEFAULT_RETRIEVAL_MODE,
        _source_sort_key,
        _session_units,
        load_cases,
        rank_source_units,
        run_official_memory_diagnostic,
    )
    from src.evidence_bound_model import (
        EvidenceBoundModelConfig,
        default_model_config,
        run_evidence_bound_answer,
        run_evidence_object_state_diagnostic,
    )
except Exception:
    from official_memory_benchmarks import (
        DEFAULT_CACHE_ROOT,
        DEFAULT_RETRIEVAL_MODE,
        _source_sort_key,
        _session_units,
        load_cases,
        rank_source_units,
        run_official_memory_diagnostic,
    )
    from evidence_bound_model import (
        EvidenceBoundModelConfig,
        default_model_config,
        run_evidence_bound_answer,
        run_evidence_object_state_diagnostic,
    )


EVAL_MISS_REPORT_CONTRACT = "eval_miss_report.v2026.6.19"
ENTITY_SUBJECT_SESSION_REPORT_CONTRACT = "entity_subject_session_report.v2026.6.19"
EVIDENCE_OBJECT_STATE_REPORT_CONTRACT = "evidence_object_state_report.v2026.6.19"
MULTI_EVIDENCE_AGGREGATION_REPORT_CONTRACT = "multi_evidence_aggregation_report.v2026.6.19"
EVIDENCE_PACK_CANDIDATE_REPORT_CONTRACT = "evidence_pack_candidate_report.v2026.6.19"
PACK_AWARE_ANSWER_SUPPORT_REPORT_CONTRACT = "pack_aware_answer_support_report.v2026.6.19"
PACK_TRIGGER_GATE_REPORT_CONTRACT = "pack_trigger_gate_report.v2026.6.19"
PACK_GATE_MODEL_PROBE_REPORT_CONTRACT = "pack_gate_model_probe_report.v2026.6.19"
PACK_GATE_MODEL_CALIBRATION_REPORT_CONTRACT = "pack_gate_model_calibration_report.v2026.6.19"
PACK_GATE_MODEL_FEATURE_REPORT_CONTRACT = "pack_gate_model_feature_report.v2026.6.19"
PACK_GATE_RUNTIME_CANDIDATE_REPORT_CONTRACT = "pack_gate_runtime_candidate_report.v2026.6.19"

_QUESTION_STOPWORDS = {
    "a",
    "about",
    "an",
    "after",
    "and",
    "are",
    "before",
    "be",
    "can",
    "could",
    "did",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "her",
    "him",
    "his",
    "how",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "she",
    "that",
    "the",
    "their",
    "they",
    "to",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "would",
    "should",
    "with",
    "you",
    "your",
}

_MONTH_TOKENS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
}

_TEMPORAL_SIGNAL_TERMS = {
    "after",
    "ago",
    "before",
    "date",
    "day",
    "earlier",
    "earliest",
    "first",
    "last",
    "later",
    "latest",
    "month",
    "next",
    "previous",
    "recent",
    "recently",
    "then",
    "time",
    "today",
    "tomorrow",
    "week",
    "when",
    "year",
    "yesterday",
}

_OBJECT_SIGNAL_STOPWORDS = {
    "answer",
    "ask",
    "asked",
    "current",
    "decide",
    "decided",
    "did",
    "does",
    "for",
    "go",
    "gone",
    "had",
    "has",
    "have",
    "likely",
    "long",
    "many",
    "mention",
    "mentioned",
    "name",
    "said",
    "tell",
    "times",
    "would",
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _compact(text: Any, limit: int = 160) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 1, 0)].rstrip() + "..."


def _tokens(text: Any) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(token) > 1 and token not in _QUESTION_STOPWORDS
    ]


def _proper_phrase_tokens(text: Any) -> list[str]:
    phrases: list[str] = []
    for match in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", str(text or "")):
        first = match.split()[0].lower()
        normalized = match.lower()
        if first in _QUESTION_STOPWORDS or normalized in _MONTH_TOKENS:
            continue
        phrases.append(normalized)
    return sorted(set(phrases))


def _question_subject_terms(question: Any) -> dict[str, Any]:
    proper_phrases = _proper_phrase_tokens(question)
    proper_tokens: list[str] = []
    for phrase in proper_phrases:
        proper_tokens.extend(_tokens(phrase))
    lexical_tokens = [
        token
        for token in _tokens(question)
        if token not in _TEMPORAL_SIGNAL_TERMS and not token.isdigit()
    ]
    proper_token_set = set(proper_tokens)
    object_tokens = [
        token
        for token in lexical_tokens
        if token not in proper_token_set and token not in _OBJECT_SIGNAL_STOPWORDS
    ]
    month_or_year = bool(re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", str(question or ""), re.I))
    has_temporal_signal = bool(
        set(_tokens(question)) & _TEMPORAL_SIGNAL_TERMS
        or month_or_year
        or re.search(r"\b(19|20)\d{2}\b", str(question or ""))
        or re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", str(question or ""))
    )
    return {
        "proper_phrases": proper_phrases,
        "proper_tokens": sorted(set(proper_tokens)),
        "lexical_tokens": sorted(set(lexical_tokens)),
        "object_tokens": sorted(set(object_tokens)),
        "has_entity_signal": bool(proper_phrases),
        "has_object_signal": bool(object_tokens),
        "has_temporal_signal": has_temporal_signal,
    }


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _top_k_values(values: Iterable[int] | None, focus_top_k: int) -> list[int]:
    selected = {int(focus_top_k)}
    for value in values or []:
        parsed = int(value)
        if parsed > 0:
            selected.add(parsed)
    return sorted(selected)


def infer_options_from_run_dir(run_dir: str | Path | None) -> dict[str, Any]:
    if not run_dir:
        return {}
    root = Path(run_dir).expanduser()
    summary = _load_json(root / "summary.json")
    ledger = _load_json(root / "run-ledger.json")
    results = summary.get("benchmark_result", {}).get("results", [])
    result = results[0] if results and isinstance(results[0], dict) else {}
    dataset = str(result.get("dataset") or ledger.get("dataset") or "").lower()
    split = str(result.get("split") or ledger.get("split") or "oracle").lower()
    if dataset == "locomo":
        split = "locomo10"
    return {
        "run_dir": str(root),
        "dataset": dataset,
        "split": split,
        "retrieval_mode": str(ledger.get("retrieval_mode") or ""),
        "top_k": _int(result.get("top_k") or ledger.get("top_k"), 0),
        "max_questions": _int(
            result.get("case_count") or ledger.get("actual_case_count") or ledger.get("sample_count"),
            0,
        ),
        "host_label": ledger.get("host_label", summary.get("host_label", "")),
        "run_id": ledger.get("run_id", summary.get("run_id", "")),
        "summary": summary,
        "ledger": ledger,
    }


def _classification_summary(per_case: list[dict[str, Any]], k: int) -> dict[str, Any]:
    key = str(k)
    primary_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    by_question_type: dict[str, Counter[str]] = {}
    for item in per_case:
        classification = item.get("miss_classification", {}).get(key, {})
        primary = str(classification.get("primary") or "unknown")
        primary_counts[primary] += 1
        qtype = str(item.get("question_type") or "unknown")
        by_question_type.setdefault(qtype, Counter())[primary] += 1
        if primary != "exact_hit":
            for tag in classification.get("tags", []):
                tag_counts[str(tag)] += 1
    return {
        "top_k": k,
        "primary_counts": dict(sorted(primary_counts.items())),
        "tag_counts": dict(sorted(tag_counts.items())),
        "by_question_type": {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(by_question_type.items())
        },
    }


def _recovery_counts(per_case: list[dict[str, Any]], *, focus_top_k: int, top_k_values: list[int]) -> dict[str, Any]:
    focus_key = str(focus_top_k)
    larger = [value for value in top_k_values if value > focus_top_k]
    exact_recovered: Counter[str] = Counter()
    anchor_recovered: Counter[str] = Counter()
    for item in per_case:
        focus_hit = item.get("hits", {}).get(focus_key, {})
        if not focus_hit.get("exact_source_hit"):
            for k in larger:
                if item.get("hits", {}).get(str(k), {}).get("exact_source_hit"):
                    exact_recovered[f"top{k}"] += 1
                    break
        if not focus_hit.get("gold_anchor_hit"):
            for k in larger:
                if item.get("hits", {}).get(str(k), {}).get("gold_anchor_hit"):
                    anchor_recovered[f"top{k}"] += 1
                    break
    return {
        "focus_top_k": focus_top_k,
        "exact_source_misses_recovered_by_larger_k": dict(sorted(exact_recovered.items())),
        "gold_anchor_misses_recovered_by_larger_k": dict(sorted(anchor_recovered.items())),
    }


def _example_row(item: dict[str, Any], *, k: int) -> dict[str, Any]:
    classification = item.get("miss_classification", {}).get(str(k), {})
    top_results = []
    for result in item.get("top_results", [])[:k]:
        top_results.append(
            {
                "source_id": result.get("source_id", ""),
                "evidence_ref": result.get("evidence_ref", ""),
                "session_id": result.get("session_id", ""),
                "score": result.get("score", 0),
                "projection_raw_target": bool(result.get("library_index_projection_raw_target_used")),
                "text": _compact(result.get("text", ""), 120),
            }
        )
    return {
        "question_id": item.get("question_id", ""),
        "question_type": item.get("question_type", ""),
        "primary": classification.get("primary", ""),
        "tags": classification.get("tags", []),
        "question": _compact(item.get("question", ""), 220),
        "answer": _compact(item.get("answer", ""), 180),
        "expected_source_refs": item.get("expected_source_refs", []),
        "expected_session_ids": item.get("expected_session_ids", []),
        "top_results": top_results,
    }


def _miss_examples(per_case: list[dict[str, Any]], *, k: int, limit: int) -> dict[str, list[dict[str, Any]]]:
    exact: list[dict[str, Any]] = []
    anchor: list[dict[str, Any]] = []
    for item in per_case:
        hit = item.get("hits", {}).get(str(k), {})
        if item.get("expected_source_refs") and not hit.get("exact_source_hit") and len(exact) < limit:
            exact.append(_example_row(item, k=k))
        if (item.get("expected_source_refs") or item.get("expected_session_ids")) and not hit.get("gold_anchor_hit") and len(anchor) < limit:
            anchor.append(_example_row(item, k=k))
    return {
        "exact_source_misses": exact,
        "gold_anchor_misses": anchor,
    }


def _expected_session_ids(case: dict[str, Any]) -> set[str]:
    return {str(value) for value in case.get("expected_session_ids") or [] if str(value)}


def _unique_session_ranking(ranked_units: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    sessions: list[dict[str, Any]] = []
    for rank, item in enumerate(ranked_units, start=1):
        session_id = str(item.get("session_id") or item.get("evidence_ref") or "")
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        sessions.append(
            {
                "session_id": session_id,
                "rank": rank,
                "score": item.get("score", 0),
                "source_id": item.get("source_id", ""),
                "retrieval_mode": item.get("retrieval_mode", ""),
            }
        )
        if len(sessions) >= limit:
            break
    return sessions


def _rank_raw_sessions(case: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    source_units = case.get("source_units") if isinstance(case.get("source_units"), list) else []
    sessions = _session_units(source_units)
    if not sessions:
        return []
    ranked = rank_source_units(
        str(case.get("question") or ""),
        sessions,
        top_k=max(limit, 1),
        retrieval_mode="bm25",
    )
    return _unique_session_ranking(ranked, limit=limit)


def _rank_projection_sessions(case: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    projection_units = case.get("library_index_units") if isinstance(case.get("library_index_units"), list) else []
    if not projection_units:
        return []
    ranked = rank_source_units(
        str(case.get("question") or ""),
        projection_units,
        top_k=max(limit * 8, 50),
        retrieval_mode="bm25",
    )
    return _unique_session_ranking(ranked, limit=limit)


def _fuse_session_rankings(rankings: dict[str, list[dict[str, Any]]], *, limit: int) -> list[dict[str, Any]]:
    by_session: dict[str, dict[str, Any]] = {}
    for source, ranked in rankings.items():
        for rank, item in enumerate(ranked, start=1):
            session_id = str(item.get("session_id") or "")
            if not session_id:
                continue
            slot = by_session.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "score": 0.0,
                    "contributions": {},
                    "source_ranks": {},
                },
            )
            slot["score"] = float(slot.get("score") or 0.0) + (1.0 / (60.0 + rank))
            slot["contributions"][source] = round(1.0 / (60.0 + rank), 8)
            slot["source_ranks"][source] = rank
    fused = list(by_session.values())
    fused.sort(key=lambda item: (-float(item.get("score") or 0.0), item.get("session_id", "")))
    for rank, item in enumerate(fused[:limit], start=1):
        item["rank"] = rank
        item["score"] = round(float(item.get("score") or 0.0), 8)
        item["retrieval_mode"] = "fused_session_rrf"
    return fused[:limit]


def _session_text_index(case: dict[str, Any]) -> dict[str, str]:
    by_session: dict[str, list[str]] = defaultdict(list)
    for unit in case.get("source_units") if isinstance(case.get("source_units"), list) else []:
        session_id = str(unit.get("session_id") or "")
        if not session_id:
            continue
        by_session[session_id].append(str(unit.get("searchable_text") or unit.get("text") or ""))
    for unit in case.get("library_index_units") if isinstance(case.get("library_index_units"), list) else []:
        session_id = str(unit.get("session_id") or "")
        if not session_id:
            continue
        by_session[session_id].append(str(unit.get("searchable_text") or unit.get("text") or ""))
    return {
        session_id: " ".join(parts)
        for session_id, parts in by_session.items()
    }


def _evidence_text_index(case: dict[str, Any]) -> dict[str, str]:
    by_ref: dict[str, str] = {}
    for unit in case.get("source_units") if isinstance(case.get("source_units"), list) else []:
        text = str(unit.get("searchable_text") or unit.get("text") or "")
        for key in (unit.get("evidence_ref"), unit.get("source_id")):
            value = str(key or "")
            if value:
                by_ref[value] = text
    return by_ref


def _source_order_index(case: dict[str, Any]) -> tuple[dict[str, int], dict[str, str]]:
    order: dict[str, int] = {}
    sessions: dict[str, str] = {}
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in case.get("source_units") if isinstance(case.get("source_units"), list) else []:
        if isinstance(unit, dict):
            by_session[str(unit.get("session_id") or "")].append(unit)
    for session_id, units in by_session.items():
        units.sort(key=lambda item: _source_sort_key(item.get("source_id") or item.get("evidence_ref")))
        for index, unit in enumerate(units):
            for key in (unit.get("source_id"), unit.get("evidence_ref")):
                value = str(key or "")
                if value:
                    order[value] = index
                    sessions[value] = session_id
    return order, sessions


def _session_term_hits(session_text: str, terms: Iterable[str]) -> list[str]:
    lowered = f" {str(session_text or '').lower()} "
    hits: list[str] = []
    for term in terms:
        value = str(term or "").strip().lower()
        if not value:
            continue
        if " " in value:
            if value in lowered:
                hits.append(value)
            continue
        if re.search(rf"\b{re.escape(value)}\b", lowered):
            hits.append(value)
    return sorted(set(hits))


def _case_top_session_ids(per_case_by_id: dict[str, dict[str, Any]], question_id: str, focus_top_k: int) -> list[str]:
    row = per_case_by_id.get(question_id, {})
    top_results = row.get("top_results") if isinstance(row.get("top_results"), list) else []
    seen: set[str] = set()
    sessions: list[str] = []
    for item in top_results[: max(int(focus_top_k), 1)]:
        session_id = str(item.get("session_id") or "")
        if session_id and session_id not in seen:
            seen.add(session_id)
            sessions.append(session_id)
    return sessions


def _case_top_refs(per_case_by_id: dict[str, dict[str, Any]], question_id: str, focus_top_k: int) -> list[str]:
    row = per_case_by_id.get(question_id, {})
    top_results = row.get("top_results") if isinstance(row.get("top_results"), list) else []
    refs: list[str] = []
    for item in top_results[: max(int(focus_top_k), 1)]:
        for key in (item.get("evidence_ref"), item.get("source_id")):
            value = str(key or "")
            if value and value not in refs:
                refs.append(value)
    return refs


def _case_primary(per_case_by_id: dict[str, dict[str, Any]], question_id: str, focus_top_k: int) -> str:
    row = per_case_by_id.get(question_id, {})
    classification = row.get("miss_classification", {}).get(str(focus_top_k), {})
    return str(classification.get("primary") or "unknown")


def _subject_route_label(
    *,
    primary: str,
    expected_subject_hits: list[str],
    top_subject_hits: list[str],
    expected_object_hits: list[str],
    top_object_hits: list[str],
    terms: dict[str, Any],
) -> str:
    if primary == "exact_hit":
        return "exact_hit"
    if not (terms.get("has_entity_signal") or terms.get("has_object_signal") or terms.get("has_temporal_signal")):
        return "no_explicit_subject_signal"
    if expected_object_hits and not top_object_hits:
        return "top_missing_expected_object"
    if expected_object_hits and top_object_hits and not (set(expected_object_hits) & set(top_object_hits)):
        return "object_mismatch"
    if expected_subject_hits and not top_subject_hits:
        return "top_missing_expected_subject"
    if expected_subject_hits and top_subject_hits and not (set(expected_subject_hits) & set(top_subject_hits)):
        return "subject_mismatch"
    if top_object_hits and not expected_object_hits:
        return "top_object_without_gold_object"
    if top_subject_hits and not expected_subject_hits:
        return "top_subject_without_gold_subject"
    if terms.get("has_temporal_signal") and primary != "exact_hit":
        return "temporal_route_suspect"
    return "subject_signal_inconclusive"


def _evidence_route_label(
    *,
    label: str,
    expected_object_hits: list[str],
    top_object_hits: list[str],
    expected_subject_hits: list[str],
    top_subject_hits: list[str],
) -> str:
    if label == "exact_hit":
        return "exact_hit"
    if expected_object_hits and not top_object_hits:
        return "top_evidence_missing_expected_object"
    if expected_object_hits and top_object_hits and not (set(expected_object_hits) & set(top_object_hits)):
        return "top_evidence_object_mismatch"
    if expected_subject_hits and not top_subject_hits:
        return "top_evidence_missing_expected_subject"
    if expected_subject_hits and top_subject_hits and not (set(expected_subject_hits) & set(top_subject_hits)):
        return "top_evidence_subject_mismatch"
    return label


def build_entity_subject_session_report(
    cases: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    example_limit: int = 8,
) -> dict[str, Any]:
    per_case_by_id = {str(item.get("question_id") or ""): item for item in per_case}
    label_counts: Counter[str] = Counter()
    evidence_label_counts: Counter[str] = Counter()
    primary_by_label: dict[str, Counter[str]] = defaultdict(Counter)
    question_type_by_label: dict[str, Counter[str]] = defaultdict(Counter)
    signal_counts: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows: list[dict[str, Any]] = []

    for case in cases:
        question_id = str(case.get("question_id") or "")
        terms = _question_subject_terms(case.get("question", ""))
        primary = _case_primary(per_case_by_id, question_id, focus_top_k)
        expected_sessions = [str(value) for value in case.get("expected_session_ids") or [] if str(value)]
        expected_refs = [str(value) for value in case.get("expected_source_refs") or [] if str(value)]
        top_sessions = _case_top_session_ids(per_case_by_id, question_id, focus_top_k)
        top_refs = _case_top_refs(per_case_by_id, question_id, focus_top_k)
        session_texts = _session_text_index(case)
        evidence_texts = _evidence_text_index(case)
        subject_terms = list(terms.get("proper_phrases") or []) + list(terms.get("proper_tokens") or [])
        object_terms = list(terms.get("object_tokens") or [])[:8]
        expected_subject_hits = sorted(
            {
                hit
                for session_id in expected_sessions
                for hit in _session_term_hits(session_texts.get(session_id, ""), subject_terms)
            }
        )
        top_subject_hits = sorted(
            {
                hit
                for session_id in top_sessions
                for hit in _session_term_hits(session_texts.get(session_id, ""), subject_terms)
            }
        )
        expected_object_hits = sorted(
            {
                hit
                for session_id in expected_sessions
                for hit in _session_term_hits(session_texts.get(session_id, ""), object_terms)
            }
        )
        top_object_hits = sorted(
            {
                hit
                for session_id in top_sessions
                for hit in _session_term_hits(session_texts.get(session_id, ""), object_terms)
            }
        )
        expected_evidence_subject_hits = sorted(
            {
                hit
                for ref in expected_refs
                for hit in _session_term_hits(evidence_texts.get(ref, ""), subject_terms)
            }
        )
        top_evidence_subject_hits = sorted(
            {
                hit
                for ref in top_refs
                for hit in _session_term_hits(evidence_texts.get(ref, ""), subject_terms)
            }
        )
        expected_evidence_object_hits = sorted(
            {
                hit
                for ref in expected_refs
                for hit in _session_term_hits(evidence_texts.get(ref, ""), object_terms)
            }
        )
        top_evidence_object_hits = sorted(
            {
                hit
                for ref in top_refs
                for hit in _session_term_hits(evidence_texts.get(ref, ""), object_terms)
            }
        )
        label = _subject_route_label(
            primary=primary,
            expected_subject_hits=expected_subject_hits,
            top_subject_hits=top_subject_hits,
            expected_object_hits=expected_object_hits,
            top_object_hits=top_object_hits,
            terms=terms,
        )
        evidence_label = _evidence_route_label(
            label=label,
            expected_object_hits=expected_evidence_object_hits,
            top_object_hits=top_evidence_object_hits,
            expected_subject_hits=expected_evidence_subject_hits,
            top_subject_hits=top_evidence_subject_hits,
        )
        label_counts[label] += 1
        evidence_label_counts[evidence_label] += 1
        primary_by_label[label][primary] += 1
        question_type_by_label[str(case.get("question_type") or "unknown")][label] += 1
        if terms.get("has_entity_signal"):
            signal_counts["entity_signal"] += 1
        if terms.get("has_object_signal"):
            signal_counts["object_signal"] += 1
        if terms.get("has_temporal_signal"):
            signal_counts["temporal_signal"] += 1
        if primary == "wrong_session":
            signal_counts["wrong_session"] += 1
            if label in {
                "top_missing_expected_object",
                "object_mismatch",
                "top_missing_expected_subject",
                "subject_mismatch",
                "temporal_route_suspect",
            }:
                signal_counts["wrong_session_subject_route_suspect"] += 1
            if evidence_label != label:
                signal_counts["wrong_session_evidence_route_suspect"] += 1
        row = {
            "question_id": question_id,
            "question_type": case.get("question_type", ""),
            "primary": primary,
            "label": label,
            "evidence_label": evidence_label,
            "question": _compact(case.get("question", ""), 220),
            "expected_source_refs": expected_refs,
            "top_refs": top_refs,
            "expected_session_ids": expected_sessions,
            "top_session_ids": top_sessions,
            "proper_phrases": terms.get("proper_phrases", []),
            "object_tokens": object_terms,
            "has_temporal_signal": bool(terms.get("has_temporal_signal")),
            "expected_subject_hits": expected_subject_hits,
            "top_subject_hits": top_subject_hits,
            "expected_object_hits": expected_object_hits,
            "top_object_hits": top_object_hits,
            "expected_evidence_subject_hits": expected_evidence_subject_hits,
            "top_evidence_subject_hits": top_evidence_subject_hits,
            "expected_evidence_object_hits": expected_evidence_object_hits,
            "top_evidence_object_hits": top_evidence_object_hits,
        }
        rows.append(row)
        if primary != "exact_hit" and len(examples[label]) < example_limit:
            examples[label].append(row)

    return {
        "contract": ENTITY_SUBJECT_SESSION_REPORT_CONTRACT,
        "focus_top_k": focus_top_k,
        "case_count": len(cases),
        "label_counts": dict(sorted(label_counts.items())),
        "evidence_label_counts": dict(sorted(evidence_label_counts.items())),
        "signal_counts": dict(sorted(signal_counts.items())),
        "primary_by_label": {
            label: dict(sorted(counter.items()))
            for label, counter in sorted(primary_by_label.items())
        },
        "question_type_by_label": {
            qtype: dict(sorted(counter.items()))
            for qtype, counter in sorted(question_type_by_label.items())
        },
        "examples": dict(sorted(examples.items())),
        "rows": rows,
        "boundary": {
            "official_leaderboard_score": False,
            "no_model_call": True,
            "no_memory_write": True,
            "read_only": True,
            "ranking_unchanged": True,
        },
    }


def _source_unit_lookup(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for unit in case.get("source_units") if isinstance(case.get("source_units"), list) else []:
        if not isinstance(unit, dict):
            continue
        for key in (unit.get("source_id"), unit.get("evidence_ref")):
            value = str(key or "")
            if value:
                lookup[value] = unit
    return lookup


def _ordered_unique_refs(refs: Iterable[str], order_index: dict[str, int]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for ref in refs:
        value = str(ref or "")
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    output.sort(key=lambda ref: (order_index.get(ref, 10**9), ref))
    return output


def _canonical_ref(value: Any, lookup: dict[str, dict[str, Any]]) -> str:
    text = str(value or "")
    unit = lookup.get(text)
    if unit:
        return str(unit.get("evidence_ref") or unit.get("source_id") or text)
    return text


def _evidence_item_from_unit(unit: dict[str, Any], *, score: Any = None) -> dict[str, Any]:
    return {
        "source_id": str(unit.get("source_id") or unit.get("evidence_ref") or ""),
        "evidence_ref": str(unit.get("evidence_ref") or unit.get("source_id") or ""),
        "session_id": str(unit.get("session_id") or ""),
        "role": str(unit.get("role") or ""),
        "timestamp": str(unit.get("timestamp") or ""),
        "text": str(unit.get("text") or unit.get("searchable_text") or ""),
        "source_refs": unit.get("source_refs") if isinstance(unit.get("source_refs"), (dict, list)) else {},
        "score": score if score is not None else unit.get("score"),
    }


def _case_gold_evidence_items(case: dict[str, Any], *, max_items: int = 8) -> list[dict[str, Any]]:
    lookup = _source_unit_lookup(case)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in case.get("expected_source_refs") or []:
        value = str(ref or "")
        unit = lookup.get(value)
        if not unit:
            continue
        stable_ref = str(unit.get("evidence_ref") or unit.get("source_id") or value)
        if stable_ref in seen:
            continue
        seen.add(stable_ref)
        items.append(_evidence_item_from_unit(unit))
        if len(items) >= max_items:
            break
    return items


def _case_top_evidence_items(
    case: dict[str, Any],
    per_case_by_id: dict[str, dict[str, Any]],
    question_id: str,
    focus_top_k: int,
    *,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    lookup = _source_unit_lookup(case)
    row = per_case_by_id.get(question_id, {})
    top_results = row.get("top_results") if isinstance(row.get("top_results"), list) else []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in top_results[: max(int(focus_top_k), 1)]:
        if not isinstance(result, dict):
            continue
        source_id = str(result.get("source_id") or "")
        evidence_ref = str(result.get("evidence_ref") or "")
        unit = lookup.get(evidence_ref) or lookup.get(source_id)
        if unit:
            item = _evidence_item_from_unit(unit, score=result.get("score"))
        else:
            item = {
                "source_id": source_id or evidence_ref,
                "evidence_ref": evidence_ref or source_id,
                "session_id": str(result.get("session_id") or ""),
                "role": str(result.get("role") or ""),
                "timestamp": str(result.get("timestamp") or ""),
                "text": str(result.get("text") or ""),
                "source_refs": result.get("source_refs") if isinstance(result.get("source_refs"), (dict, list)) else {},
                "score": result.get("score"),
            }
        stable_ref = str(item.get("evidence_ref") or item.get("source_id") or "")
        if not stable_ref or stable_ref in seen:
            continue
        seen.add(stable_ref)
        items.append(item)
        if len(items) >= max_items:
            break
    return items


def _evidence_items_for_refs(
    case: dict[str, Any],
    refs: list[str],
    *,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    lookup = _source_unit_lookup(case)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        value = str(ref or "")
        unit = lookup.get(value)
        if not unit:
            continue
        stable_ref = str(unit.get("evidence_ref") or unit.get("source_id") or value)
        if stable_ref in seen:
            continue
        seen.add(stable_ref)
        items.append(_evidence_item_from_unit(unit))
        if len(items) >= max_items:
            break
    return items


def _diagnostic_model_config(model_config: EvidenceBoundModelConfig | dict | None = None) -> EvidenceBoundModelConfig:
    if isinstance(model_config, EvidenceBoundModelConfig):
        return model_config
    if isinstance(model_config, dict):
        return EvidenceBoundModelConfig(
            provider=str(model_config.get("provider") or ""),
            model=str(model_config.get("model") or ""),
            base_url=str(model_config.get("base_url") or ""),
            api_key_env=str(model_config.get("api_key_env") or ""),
            timeout_seconds=int(model_config.get("timeout_seconds") or 60),
        )
    return default_model_config()


def build_evidence_object_state_report(
    cases: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    max_model_cases: int = 20,
    execute_model: bool = False,
    model_config: EvidenceBoundModelConfig | dict | None = None,
    model_client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    example_limit: int = 8,
) -> dict[str, Any]:
    per_case_by_id = {str(item.get("question_id") or ""): item for item in per_case}
    selected_cases: list[dict[str, Any]] = []
    for case in cases:
        question_id = str(case.get("question_id") or "")
        primary = _case_primary(per_case_by_id, question_id, focus_top_k)
        if primary == "exact_hit":
            continue
        selected_cases.append(case)
        if max_model_cases is not None and int(max_model_cases) >= 0 and len(selected_cases) >= int(max_model_cases):
            break

    rows: list[dict[str, Any]] = []
    verdict_counts: Counter[str] = Counter()
    primary_by_verdict: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    model_call_count = 0
    config = _diagnostic_model_config(model_config)

    for case in selected_cases:
        question_id = str(case.get("question_id") or "")
        primary = _case_primary(per_case_by_id, question_id, focus_top_k)
        gold_evidence = _case_gold_evidence_items(case)
        top_evidence = _case_top_evidence_items(
            case,
            per_case_by_id,
            question_id,
            focus_top_k,
        )
        diagnostic = run_evidence_object_state_diagnostic(
            str(case.get("question") or ""),
            gold_evidence,
            top_evidence,
            expected_answer=str(case.get("answer") or ""),
            model_config=config,
            execute=execute_model,
            client=model_client,
        )
        if diagnostic.get("model_call_performed"):
            model_call_count += 1
        verdict = str(diagnostic.get("support_verdict") or "unknown")
        verdict_counts[verdict] += 1
        primary_by_verdict[verdict][primary] += 1
        top_refs = [str(item.get("evidence_ref") or item.get("source_id") or "") for item in top_evidence]
        gold_refs = [str(item.get("evidence_ref") or item.get("source_id") or "") for item in gold_evidence]
        row = {
            "question_id": question_id,
            "question_type": case.get("question_type", ""),
            "primary": primary,
            "question": _compact(case.get("question", ""), 220),
            "answer": _compact(case.get("answer", ""), 180),
            "expected_source_refs": case.get("expected_source_refs", []),
            "gold_refs": gold_refs,
            "top_refs": top_refs,
            "gold_sessions": sorted({str(item.get("session_id") or "") for item in gold_evidence if str(item.get("session_id") or "")}),
            "top_sessions": sorted({str(item.get("session_id") or "") for item in top_evidence if str(item.get("session_id") or "")}),
            "gold_evidence_count": len(gold_evidence),
            "top_evidence_count": len(top_evidence),
            "diagnostic": {
                key: value
                for key, value in diagnostic.items()
                if key not in {"prompt_messages"}
            },
            "gold_evidence_preview": [
                {
                    "ref": item.get("evidence_ref") or item.get("source_id"),
                    "session_id": item.get("session_id", ""),
                    "text": _compact(item.get("text", ""), 180),
                }
                for item in gold_evidence[:3]
            ],
            "top_evidence_preview": [
                {
                    "ref": item.get("evidence_ref") or item.get("source_id"),
                    "session_id": item.get("session_id", ""),
                    "text": _compact(item.get("text", ""), 180),
                }
                for item in top_evidence[:3]
            ],
        }
        rows.append(row)
        if len(examples[verdict]) < example_limit:
            examples[verdict].append(row)

    provider = getattr(config, "provider", "") if not isinstance(config, dict) else str(config.get("provider") or "")
    model = getattr(config, "model", "") if not isinstance(config, dict) else str(config.get("model") or "")
    api_key_env = getattr(config, "api_key_env", "") if not isinstance(config, dict) else str(config.get("api_key_env") or "")
    api_key_present = bool(getattr(config, "api_key_present", False)) if not isinstance(config, dict) else False
    return {
        "contract": EVIDENCE_OBJECT_STATE_REPORT_CONTRACT,
        "focus_top_k": focus_top_k,
        "case_count": len(cases),
        "selected_case_count": len(selected_cases),
        "max_model_cases": max_model_cases,
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "primary_by_verdict": {
            verdict: dict(sorted(counter.items()))
            for verdict, counter in sorted(primary_by_verdict.items())
        },
        "model": {
            "provider": provider,
            "model": model,
            "api_key_env": api_key_env,
            "api_key_present": api_key_present,
        },
        "model_call_count": model_call_count,
        "examples": dict(sorted(examples.items())),
        "rows": rows,
        "boundary": {
            "official_leaderboard_score": False,
            "diagnostic_only": True,
            "read_only": True,
            "no_memory_write": True,
            "ranking_unchanged": True,
            "model_call_allowed": bool(execute_model or model_client is not None),
            "model_call_performed": model_call_count > 0,
            "raw_evidence_required": True,
        },
    }


def build_session_routing_report(
    cases: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    top_k_values: Iterable[int] | None = None,
    example_limit: int = 8,
) -> dict[str, Any]:
    top_values = _top_k_values(top_k_values or [focus_top_k, 5, 10, 20], focus_top_k)
    max_k = max(top_values) if top_values else max(int(focus_top_k), 1)
    routes = ("raw_session_bm25", "projection_session_bm25", "fused_session_rrf")
    counts = {
        route: {
            str(k): {
                "gold_questions": 0,
                "session_hits": 0,
            }
            for k in top_values
        }
        for route in routes
    }
    examples: dict[str, list[dict[str, Any]]] = {route: [] for route in routes}

    for case in cases:
        expected = _expected_session_ids(case)
        if not expected:
            continue
        raw_ranked = _rank_raw_sessions(case, limit=max_k)
        projection_ranked = _rank_projection_sessions(case, limit=max_k)
        route_rankings = {
            "raw_session_bm25": raw_ranked,
            "projection_session_bm25": projection_ranked,
            "fused_session_rrf": _fuse_session_rankings(
                {
                    "raw_session_bm25": raw_ranked,
                    "projection_session_bm25": projection_ranked,
                },
                limit=max_k,
            ),
        }
        for route, ranked in route_rankings.items():
            ranked_ids = [str(item.get("session_id") or "") for item in ranked]
            for k in top_values:
                counts[route][str(k)]["gold_questions"] += 1
                if expected & set(ranked_ids[:k]):
                    counts[route][str(k)]["session_hits"] += 1
            if not (expected & set(ranked_ids[:focus_top_k])) and len(examples[route]) < example_limit:
                examples[route].append(
                    {
                        "question_id": case.get("question_id", ""),
                        "question_type": case.get("question_type", ""),
                        "question": _compact(case.get("question", ""), 220),
                        "expected_session_ids": sorted(expected),
                        "top_sessions": ranked[:focus_top_k],
                    }
                )

    metrics: dict[str, dict[str, Any]] = {}
    for route, by_k in counts.items():
        metrics[route] = {}
        for key, row in by_k.items():
            gold = int(row.get("gold_questions") or 0)
            hits = int(row.get("session_hits") or 0)
            metrics[route][key] = {
                **row,
                "session_recall": round(hits / gold, 4) if gold else 0.0,
            }
    return {
        "contract": "session_routing_report.v2026.6.19",
        "focus_top_k": focus_top_k,
        "top_k": top_values,
        "case_count": len(cases),
        "routes": list(routes),
        "metrics": metrics,
        "examples": examples,
        "boundary": {
            "official_leaderboard_score": False,
            "no_model_call": True,
            "no_memory_write": True,
            "read_only": True,
        },
    }


def _aggregation_question_signals(question: Any) -> list[str]:
    text = str(question or "").lower()
    signals: list[str] = []
    if re.search(r"\b(how many|number of|count|times)\b", text):
        signals.append("count")
    if re.search(r"\b(what|which|where|who)\b", text) and re.search(r"\b(and|or|all|activities|events|places|fields|kids|things)\b", text):
        signals.append("list_or_set")
    if re.search(r"\b(events|activities|places|fields|kids|relationship|status|identity)\b", text):
        signals.append("state_or_relation")
    if re.search(r"\b(when|recent|recently|current|last|before|after|in 20\d\d|january|february|march|april|may|june|july|august|september|october|november|december)\b", text):
        signals.append("temporal")
    return sorted(set(signals))


def _neighbor_refs_for_top_result(
    case: dict[str, Any],
    top_result: dict[str, Any],
    order_index: dict[str, int],
    ref_sessions: dict[str, str],
) -> set[str]:
    source_units = case.get("source_units") if isinstance(case.get("source_units"), list) else []
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in source_units:
        if isinstance(unit, dict):
            by_session[str(unit.get("session_id") or "")].append(unit)
    for units in by_session.values():
        units.sort(key=lambda item: _source_sort_key(item.get("source_id") or item.get("evidence_ref")))
    ref = str(top_result.get("evidence_ref") or top_result.get("source_id") or "")
    session_id = str(top_result.get("session_id") or ref_sessions.get(ref) or "")
    if not ref or not session_id:
        return set()
    window = max(_int(top_result.get("context_window"), 0), 0)
    if window <= 0:
        return {ref}
    index = order_index.get(ref)
    if index is None:
        return {ref}
    units = by_session.get(session_id, [])
    refs: set[str] = set()
    for unit in units[max(index - window, 0): min(index + window + 1, len(units))]:
        for key in (unit.get("source_id"), unit.get("evidence_ref")):
            value = str(key or "")
            if value:
                refs.add(value)
    return refs


def _turn_distance_summary(
    gold_refs: list[str],
    top_results: list[dict[str, Any]],
    order_index: dict[str, int],
    ref_sessions: dict[str, str],
) -> dict[str, Any]:
    distances: list[int] = []
    same_session_pairs = 0
    for gold_ref in gold_refs:
        gold_session = ref_sessions.get(str(gold_ref))
        gold_index = order_index.get(str(gold_ref))
        if gold_session is None or gold_index is None:
            continue
        for top in top_results:
            top_ref = str(top.get("evidence_ref") or top.get("source_id") or "")
            top_session = str(top.get("session_id") or ref_sessions.get(top_ref) or "")
            top_index = order_index.get(top_ref)
            if top_session != gold_session or top_index is None:
                continue
            same_session_pairs += 1
            distances.append(abs(int(top_index) - int(gold_index)))
    if not distances:
        return {
            "same_session_pairs": same_session_pairs,
            "min_turn_distance": None,
            "near_turn_distance_le_2": False,
            "near_turn_distance_le_4": False,
        }
    minimum = min(distances)
    return {
        "same_session_pairs": same_session_pairs,
        "min_turn_distance": minimum,
        "near_turn_distance_le_2": minimum <= 2,
        "near_turn_distance_le_4": minimum <= 4,
    }


def _aggregation_label(
    *,
    primary: str,
    expected_count: int,
    exact_top_overlap_count: int,
    neighbor_overlap_count: int,
    same_session_gold_count: int,
    distance: dict[str, Any],
    question_signals: list[str],
) -> str:
    if primary == "exact_hit":
        return "exact_hit"
    if expected_count <= 0:
        return "no_gold_refs"
    if exact_top_overlap_count >= expected_count:
        return "all_gold_in_top"
    if neighbor_overlap_count >= expected_count and expected_count > 1:
        return "all_gold_in_neighbor_pack"
    if neighbor_overlap_count > 0 and expected_count > 1:
        return "partial_gold_in_neighbor_pack"
    if exact_top_overlap_count > 0 and expected_count > 1:
        return "partial_gold_in_top"
    if same_session_gold_count >= expected_count and expected_count > 1:
        return "all_gold_sessions_present_missing_turns"
    if same_session_gold_count > 0:
        if distance.get("near_turn_distance_le_2"):
            return "same_session_near_turn"
        return "same_session_wrong_turn"
    if {"list_or_set", "count"} & set(question_signals):
        return "aggregation_candidate_missing_gold"
    return "not_aggregation_explained"


def build_multi_evidence_aggregation_report(
    cases: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    example_limit: int = 8,
) -> dict[str, Any]:
    per_case_by_id = {str(item.get("question_id") or ""): item for item in per_case}
    label_counts: Counter[str] = Counter()
    primary_by_label: dict[str, Counter[str]] = defaultdict(Counter)
    signal_counts: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows: list[dict[str, Any]] = []
    target_primaries = {"bundle_only", "right_session_wrong_turn"}

    for case in cases:
        question_id = str(case.get("question_id") or "")
        primary = _case_primary(per_case_by_id, question_id, focus_top_k)
        if primary not in target_primaries:
            continue
        row = per_case_by_id.get(question_id, {})
        top_results = row.get("top_results") if isinstance(row.get("top_results"), list) else []
        top_results = top_results[: max(int(focus_top_k), 1)]
        gold_refs = [str(value) for value in case.get("expected_source_refs") or [] if str(value)]
        top_refs = _case_top_refs(per_case_by_id, question_id, focus_top_k)
        order_index, ref_sessions = _source_order_index(case)
        top_ref_set = set(top_refs)
        gold_ref_set = set(gold_refs)
        exact_top_overlap = sorted(gold_ref_set & top_ref_set)
        neighbor_refs: set[str] = set()
        for top in top_results:
            neighbor_refs.update(_neighbor_refs_for_top_result(case, top, order_index, ref_sessions))
            for ref in top.get("context_bundle_refs") or []:
                value = str(ref or "")
                if value:
                    neighbor_refs.add(value)
        neighbor_overlap = sorted(gold_ref_set & neighbor_refs)
        top_sessions = {str(item.get("session_id") or "") for item in top_results if str(item.get("session_id") or "")}
        gold_sessions_by_ref = {ref: ref_sessions.get(ref, "") for ref in gold_refs}
        same_session_gold_refs = sorted(
            ref
            for ref, session_id in gold_sessions_by_ref.items()
            if session_id and session_id in top_sessions
        )
        distance = _turn_distance_summary(gold_refs, top_results, order_index, ref_sessions)
        question_signals = _aggregation_question_signals(case.get("question", ""))
        label = _aggregation_label(
            primary=primary,
            expected_count=len(gold_refs),
            exact_top_overlap_count=len(exact_top_overlap),
            neighbor_overlap_count=len(neighbor_overlap),
            same_session_gold_count=len(same_session_gold_refs),
            distance=distance,
            question_signals=question_signals,
        )
        label_counts[label] += 1
        primary_by_label[label][primary] += 1
        if len(gold_refs) > 1:
            signal_counts["multi_gold_ref"] += 1
        for signal in question_signals:
            signal_counts[f"question_signal:{signal}"] += 1
        if neighbor_overlap:
            signal_counts["gold_in_neighbor_pack"] += 1
        if same_session_gold_refs:
            signal_counts["gold_session_in_top"] += 1
        result_row = {
            "question_id": question_id,
            "question_type": case.get("question_type", ""),
            "primary": primary,
            "label": label,
            "question": _compact(case.get("question", ""), 220),
            "answer": _compact(case.get("answer", ""), 180),
            "expected_source_refs": gold_refs,
            "expected_ref_count": len(gold_refs),
            "top_refs": top_refs,
            "top_session_ids": sorted(top_sessions),
            "gold_sessions_by_ref": gold_sessions_by_ref,
            "exact_top_overlap": exact_top_overlap,
            "neighbor_overlap": neighbor_overlap,
            "same_session_gold_refs": same_session_gold_refs,
            "turn_distance": distance,
            "question_signals": question_signals,
            "top_results": [
                {
                    "ref": item.get("evidence_ref") or item.get("source_id"),
                    "session_id": item.get("session_id", ""),
                    "context_window": item.get("context_window", 0),
                    "context_distance": item.get("context_distance", 0),
                    "text": _compact(item.get("text", ""), 140),
                }
                for item in top_results
            ],
        }
        rows.append(result_row)
        if len(examples[label]) < example_limit:
            examples[label].append(result_row)

    return {
        "contract": MULTI_EVIDENCE_AGGREGATION_REPORT_CONTRACT,
        "focus_top_k": focus_top_k,
        "case_count": len(cases),
        "target_primary": sorted(target_primaries),
        "selected_case_count": len(rows),
        "label_counts": dict(sorted(label_counts.items())),
        "primary_by_label": {
            label: dict(sorted(counter.items()))
            for label, counter in sorted(primary_by_label.items())
        },
        "signal_counts": dict(sorted(signal_counts.items())),
        "examples": dict(sorted(examples.items())),
        "rows": rows,
        "boundary": {
            "official_leaderboard_score": False,
            "no_model_call": True,
            "no_memory_write": True,
            "read_only": True,
            "ranking_unchanged": True,
            "diagnostic_only": True,
            "raw_evidence_required": True,
        },
    }


def _answer_support_label(
    case: dict[str, Any],
    refs: list[str],
    units_by_ref: dict[str, dict[str, Any]],
    *,
    scope: str,
) -> str:
    answer = str(case.get("answer") or "")
    if not answer or not refs:
        return "not_measured"
    answer_tokens = {
        token
        for token in _tokens(answer)
        if token not in _QUESTION_STOPWORDS and len(token) > 2
    }
    answer_numbers = set(re.findall(r"\d+(?:\.\d+)?", answer.lower()))
    evidence_text = " ".join(str(units_by_ref.get(ref, {}).get("text") or "") for ref in refs).lower()
    if answer.lower() and answer.lower() in evidence_text:
        return f"answer_phrase_in_{scope}"
    if answer_numbers and answer_numbers & set(re.findall(r"\d+(?:\.\d+)?", evidence_text)):
        return f"answer_number_in_{scope}"
    if answer_tokens:
        evidence_tokens = set(_tokens(evidence_text))
        overlap = answer_tokens & evidence_tokens
        if len(overlap) >= min(3, len(answer_tokens)):
            return f"answer_token_overlap_in_{scope}"
    return "none"


def _pack_support_label(case: dict[str, Any], pack_refs: list[str], units_by_ref: dict[str, dict[str, Any]]) -> str:
    return _answer_support_label(case, pack_refs, units_by_ref, scope="pack")


def _support_is_positive(label: str) -> bool:
    return str(label or "").startswith(
        (
            "answer_phrase_in_",
            "answer_number_in_",
            "answer_token_overlap_in_",
        )
    )


def _tokenish_count(text: Any) -> int:
    return len(re.findall(r"\S+", str(text or "")))


def _refs_tokenish_count(refs: list[str], units_by_ref: dict[str, dict[str, Any]]) -> int:
    return sum(_tokenish_count(units_by_ref.get(ref, {}).get("text", "")) for ref in refs)


def _pack_cost_band(pack_size: int, pack_tokenish: int) -> str:
    if pack_size <= 5 and pack_tokenish <= 400:
        return "low"
    if pack_size <= 12 and pack_tokenish <= 1200:
        return "medium"
    return "high"


def _support_delta_label(top_label: str, pack_label: str) -> str:
    top_supported = _support_is_positive(top_label)
    pack_supported = _support_is_positive(pack_label)
    if pack_supported and not top_supported:
        return "pack_improved"
    if pack_supported and top_supported:
        return "both_supported"
    if top_supported and not pack_supported:
        return "top_only_supported"
    if top_label == "not_measured" or pack_label == "not_measured":
        return "not_measured"
    return "pack_no_gain"


def _pack_trigger_gate_decision(row: dict[str, Any]) -> dict[str, Any]:
    primary = str(row.get("primary") or "")
    support_delta = str(row.get("support_delta") or "")
    cost_band = str(row.get("cost_band") or "")
    question_signals = set(row.get("question_signals") if isinstance(row.get("question_signals"), list) else [])
    pack_overlap = bool(row.get("pack_overlap"))
    pack_supported = bool(row.get("pack_supported"))
    top_supported = bool(row.get("top_supported"))
    pack_size = _int(row.get("pack_size"), 0)
    incremental_tokenish = _int(row.get("incremental_tokenish"), 0)
    reasons: list[str] = []

    if primary in {"wrong_session", "coverage_gap"} and not pack_overlap:
        reasons.append("route_or_gold_missing")
    if support_delta == "both_supported":
        reasons.append("top_already_supported")
    if support_delta == "pack_no_gain":
        reasons.append("pack_no_answer_gain")
    if cost_band == "high" and not pack_supported:
        reasons.append("high_cost_without_support")
    if primary not in {"bundle_only", "right_session_wrong_turn"} and not pack_overlap:
        reasons.append("not_target_primary_without_gold")

    trigger = False
    trigger_reasons: list[str] = []
    if support_delta == "pack_improved" and pack_supported and not top_supported:
        if primary in {"bundle_only", "right_session_wrong_turn"}:
            trigger = True
            trigger_reasons.append("pack_improved_target_primary")
        elif pack_overlap and cost_band != "high":
            trigger = True
            trigger_reasons.append("pack_improved_non_high_cost_gold")
    if not trigger and pack_supported and pack_overlap and cost_band == "low":
        trigger = True
        trigger_reasons.append("low_cost_supported_gold")

    expected_gain_bucket = "none"
    if support_delta == "pack_improved":
        expected_gain_bucket = "observed_pack_improved"
    elif support_delta == "both_supported":
        expected_gain_bucket = "redundant_support"
    elif pack_overlap:
        expected_gain_bucket = "gold_without_answer_gain"
    elif pack_supported:
        expected_gain_bucket = "unsupported_by_gold_signal"

    expected_cost_bucket = "small" if cost_band == "low" else "moderate" if cost_band == "medium" else "large"
    if pack_size <= 0:
        expected_cost_bucket = "empty"
    elif incremental_tokenish <= 120 and cost_band != "high":
        expected_cost_bucket = "small"

    if trigger:
        skip_reason = ""
    elif reasons:
        skip_reason = "|".join(sorted(set(reasons)))
    else:
        skip_reason = "no_trigger_rule"

    return {
        "would_trigger": trigger,
        "trigger_reasons": sorted(set(trigger_reasons)),
        "would_skip_reason": skip_reason,
        "expected_gain_bucket": expected_gain_bucket,
        "expected_cost_bucket": expected_cost_bucket,
        "target_primary": primary in {"bundle_only", "right_session_wrong_turn"},
        "has_aggregation_signal": bool(question_signals & {"list_or_set", "count", "state_or_relation", "temporal"}),
        "runtime_candidate": False,
    }


def build_pack_trigger_gate_report(
    cases: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    pack_window: int = 2,
    example_limit: int = 8,
) -> dict[str, Any]:
    support_report = build_pack_aware_answer_support_report(
        cases,
        per_case,
        focus_top_k=focus_top_k,
        pack_window=pack_window,
        example_limit=example_limit,
    )
    rows: list[dict[str, Any]] = []
    trigger_counts: Counter[str] = Counter()
    skip_reason_counts: Counter[str] = Counter()
    gain_bucket_counts: Counter[str] = Counter()
    cost_bucket_counts: Counter[str] = Counter()
    primary_by_trigger: dict[str, Counter[str]] = defaultdict(Counter)
    delta_by_trigger: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total_improved = 0
    triggered_improved = 0
    total_no_gain_high_cost = 0
    skipped_no_gain_high_cost = 0
    triggered_count = 0
    triggered_no_gain = 0
    triggered_high_cost = 0

    for row in support_report.get("rows", []):
        if not isinstance(row, dict):
            continue
        decision = _pack_trigger_gate_decision(row)
        result_row = {
            key: row.get(key)
            for key in (
                "question_id",
                "question_type",
                "primary",
                "question",
                "answer",
                "expected_source_refs",
                "top_refs",
                "pack_refs",
                "pack_overlap",
                "pack_missing_refs",
                "top_support_label",
                "pack_support_label",
                "support_delta",
                "pack_size",
                "pack_tokenish",
                "incremental_tokenish",
                "cost_band",
                "question_signals",
            )
        }
        result_row.update(decision)
        rows.append(result_row)
        trigger_key = "trigger" if decision.get("would_trigger") else "skip"
        trigger_counts[trigger_key] += 1
        primary_by_trigger[trigger_key][str(row.get("primary") or "")] += 1
        delta_by_trigger[trigger_key][str(row.get("support_delta") or "")] += 1
        gain_bucket_counts[str(decision.get("expected_gain_bucket") or "")] += 1
        cost_bucket_counts[str(decision.get("expected_cost_bucket") or "")] += 1
        if decision.get("would_skip_reason"):
            for reason in str(decision.get("would_skip_reason") or "").split("|"):
                if reason:
                    skip_reason_counts[reason] += 1
        if row.get("support_delta") == "pack_improved":
            total_improved += 1
            triggered_improved += int(bool(decision.get("would_trigger")))
        no_gain_high_cost = row.get("support_delta") == "pack_no_gain" and row.get("cost_band") == "high"
        if no_gain_high_cost:
            total_no_gain_high_cost += 1
            skipped_no_gain_high_cost += int(not bool(decision.get("would_trigger")))
        if decision.get("would_trigger"):
            triggered_count += 1
            triggered_no_gain += int(row.get("support_delta") == "pack_no_gain")
            triggered_high_cost += int(row.get("cost_band") == "high")
        example_key = trigger_key
        if row.get("support_delta") == "pack_improved":
            example_key = f"{trigger_key}_pack_improved"
        elif no_gain_high_cost:
            example_key = f"{trigger_key}_no_gain_high_cost"
        if len(examples[example_key]) < example_limit:
            examples[example_key].append(result_row)

    selected_count = len(rows)
    return {
        "contract": PACK_TRIGGER_GATE_REPORT_CONTRACT,
        "focus_top_k": focus_top_k,
        "pack_window": pack_window,
        "case_count": len(cases),
        "selected_case_count": selected_count,
        "trigger_counts": dict(sorted(trigger_counts.items())),
        "skip_reason_counts": dict(sorted(skip_reason_counts.items())),
        "gain_bucket_counts": dict(sorted(gain_bucket_counts.items())),
        "cost_bucket_counts": dict(sorted(cost_bucket_counts.items())),
        "primary_by_trigger": {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(primary_by_trigger.items())
        },
        "delta_by_trigger": {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(delta_by_trigger.items())
        },
        "metrics": {
            "triggered_count": triggered_count,
            "triggered_rate": round(triggered_count / selected_count, 4) if selected_count else 0.0,
            "pack_improved_total": total_improved,
            "pack_improved_triggered": triggered_improved,
            "pack_improved_capture_rate": round(triggered_improved / total_improved, 4) if total_improved else 0.0,
            "no_gain_high_cost_total": total_no_gain_high_cost,
            "no_gain_high_cost_skipped": skipped_no_gain_high_cost,
            "no_gain_high_cost_skip_rate": round(skipped_no_gain_high_cost / total_no_gain_high_cost, 4) if total_no_gain_high_cost else 0.0,
            "triggered_no_gain_count": triggered_no_gain,
            "triggered_high_cost_count": triggered_high_cost,
        },
        "examples": dict(sorted(examples.items())),
        "rows": rows,
        "boundary": {
            "official_leaderboard_score": False,
            "no_model_call": True,
            "no_memory_write": True,
            "read_only": True,
            "ranking_unchanged": True,
            "diagnostic_only": True,
            "daily_entry_integrated": False,
            "runtime_policy": False,
            "uses_expected_answer_for_diagnostic": True,
        },
    }


def _select_pack_gate_model_probe_rows(
    rows: list[dict[str, Any]],
    *,
    max_cases: int,
) -> list[dict[str, Any]]:
    buckets = [
        ("triggered_pack_improved", lambda row: row.get("would_trigger") and row.get("support_delta") == "pack_improved"),
        ("skipped_no_gain_high_cost", lambda row: (not row.get("would_trigger")) and row.get("support_delta") == "pack_no_gain" and row.get("cost_band") == "high"),
        ("skipped_both_supported", lambda row: (not row.get("would_trigger")) and row.get("support_delta") == "both_supported"),
    ]
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_bucket_limit = max(1, int(max_cases) // len(buckets)) if max_cases else 0
    for bucket, predicate in buckets:
        count = 0
        for row in rows:
            question_id = str(row.get("question_id") or "")
            if not question_id or question_id in seen or not predicate(row):
                continue
            selected_row = dict(row)
            selected_row["probe_bucket"] = bucket
            selected.append(selected_row)
            seen.add(question_id)
            count += 1
            if count >= per_bucket_limit:
                break
    if len(selected) < max_cases:
        for row in rows:
            question_id = str(row.get("question_id") or "")
            if not question_id or question_id in seen:
                continue
            selected_row = dict(row)
            selected_row["probe_bucket"] = "fill"
            selected.append(selected_row)
            seen.add(question_id)
            if len(selected) >= max_cases:
                break
    return selected[: max(int(max_cases), 0)]


def _model_answer_supported(result: dict[str, Any]) -> bool:
    verdict = str(result.get("verdict") or "").lower()
    answer = str(result.get("answer") or "").strip().upper()
    refs = result.get("supporting_refs") if isinstance(result.get("supporting_refs"), list) else []
    return verdict == "answered" and answer != "UNKNOWN" and bool(refs)


def _runtime_probe_verdict(top_result: dict[str, Any], pack_result: dict[str, Any]) -> str:
    top_supported = _model_answer_supported(top_result)
    pack_supported = _model_answer_supported(pack_result)
    if pack_result.get("verdict") == "dry_run" or top_result.get("verdict") == "dry_run":
        return "dry_run"
    if pack_supported and not top_supported:
        return "pack_model_improved"
    if pack_supported and top_supported:
        return "both_model_supported"
    if top_supported and not pack_supported:
        return "top_model_only"
    if pack_result.get("ok") is False or top_result.get("ok") is False:
        return "model_error"
    return "model_no_support"


def build_pack_gate_model_probe_report(
    cases: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    pack_window: int = 2,
    max_model_cases: int = 9,
    execute_model: bool = False,
    model_config: EvidenceBoundModelConfig | dict | None = None,
    model_client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    example_limit: int = 8,
) -> dict[str, Any]:
    cases_by_id = {str(case.get("question_id") or ""): case for case in cases}
    gate_report = build_pack_trigger_gate_report(
        cases,
        per_case,
        focus_top_k=focus_top_k,
        pack_window=pack_window,
        example_limit=example_limit,
    )
    selected_rows = _select_pack_gate_model_probe_rows(
        [row for row in gate_report.get("rows", []) if isinstance(row, dict)],
        max_cases=max_model_cases,
    )
    config = _diagnostic_model_config(model_config)
    rows: list[dict[str, Any]] = []
    verdict_counts: Counter[str] = Counter()
    bucket_by_verdict: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    model_call_count = 0
    model_error_count = 0

    for selected in selected_rows:
        question_id = str(selected.get("question_id") or "")
        case = cases_by_id.get(question_id, {})
        top_evidence = _evidence_items_for_refs(case, [str(ref) for ref in selected.get("top_refs") or []], max_items=8)
        pack_evidence = _evidence_items_for_refs(case, [str(ref) for ref in selected.get("pack_refs") or []], max_items=12)
        question = str(case.get("question") or selected.get("question") or "")
        expected_answer = str(case.get("answer") or selected.get("answer") or "")
        top_result = run_evidence_bound_answer(
            question,
            top_evidence,
            draft_answer=expected_answer,
            model_config=config,
            execute=execute_model,
            client=model_client,
        )
        pack_result = run_evidence_bound_answer(
            question,
            pack_evidence,
            draft_answer=expected_answer,
            model_config=config,
            execute=execute_model,
            client=model_client,
        )
        model_call_count += int(bool(top_result.get("model_call_performed"))) + int(bool(pack_result.get("model_call_performed")))
        model_error_count += int(top_result.get("ok") is False) + int(pack_result.get("ok") is False)
        verdict = _runtime_probe_verdict(top_result, pack_result)
        verdict_counts[verdict] += 1
        bucket = str(selected.get("probe_bucket") or "unknown")
        bucket_by_verdict[verdict][bucket] += 1
        row = {
            "question_id": question_id,
            "probe_bucket": bucket,
            "primary": selected.get("primary", ""),
            "would_trigger": bool(selected.get("would_trigger")),
            "support_delta": selected.get("support_delta", ""),
            "cost_band": selected.get("cost_band", ""),
            "question": _compact(question, 220),
            "expected_answer": _compact(expected_answer, 180),
            "top_refs": selected.get("top_refs", []),
            "pack_refs": selected.get("pack_refs", []),
            "pack_overlap": selected.get("pack_overlap", []),
            "top_evidence_count": len(top_evidence),
            "pack_evidence_count": len(pack_evidence),
            "pack_size": selected.get("pack_size", 0),
            "pack_tokenish": selected.get("pack_tokenish", 0),
            "incremental_tokenish": selected.get("incremental_tokenish", 0),
            "question_signals": selected.get("question_signals", []),
            "model_verdict": verdict,
            "top_model": {
                "answer": _compact(top_result.get("answer", ""), 180),
                "verdict": top_result.get("verdict", ""),
                "confidence": top_result.get("confidence", 0.0),
                "supporting_refs": top_result.get("supporting_refs", []),
                "unknown_reason": _compact(top_result.get("unknown_reason", ""), 160),
                "validation_error": top_result.get("validation_error", ""),
                "ok": top_result.get("ok", True),
            },
            "pack_model": {
                "answer": _compact(pack_result.get("answer", ""), 180),
                "verdict": pack_result.get("verdict", ""),
                "confidence": pack_result.get("confidence", 0.0),
                "supporting_refs": pack_result.get("supporting_refs", []),
                "unknown_reason": _compact(pack_result.get("unknown_reason", ""), 160),
                "validation_error": pack_result.get("validation_error", ""),
                "ok": pack_result.get("ok", True),
            },
        }
        rows.append(row)
        if len(examples[verdict]) < example_limit:
            examples[verdict].append(row)

    provider = getattr(config, "provider", "") if not isinstance(config, dict) else str(config.get("provider") or "")
    model = getattr(config, "model", "") if not isinstance(config, dict) else str(config.get("model") or "")
    api_key_env = getattr(config, "api_key_env", "") if not isinstance(config, dict) else str(config.get("api_key_env") or "")
    api_key_present = bool(getattr(config, "api_key_present", False)) if not isinstance(config, dict) else False
    return {
        "contract": PACK_GATE_MODEL_PROBE_REPORT_CONTRACT,
        "focus_top_k": focus_top_k,
        "pack_window": pack_window,
        "case_count": len(cases),
        "selected_case_count": len(selected_rows),
        "max_model_cases": max_model_cases,
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "bucket_by_verdict": {
            verdict: dict(sorted(counter.items()))
            for verdict, counter in sorted(bucket_by_verdict.items())
        },
        "model": {
            "provider": provider,
            "model": model,
            "api_key_env": api_key_env,
            "api_key_present": api_key_present,
        },
        "model_call_count": model_call_count,
        "model_error_count": model_error_count,
        "examples": dict(sorted(examples.items())),
        "rows": rows,
        "boundary": {
            "official_leaderboard_score": False,
            "diagnostic_only": True,
            "read_only": True,
            "no_memory_write": True,
            "ranking_unchanged": True,
            "daily_entry_integrated": False,
            "runtime_policy": False,
            "expected_answer_as_draft_only": True,
            "model_call_allowed": bool(execute_model or model_client is not None),
            "model_call_performed": model_call_count > 0,
            "raw_evidence_required": True,
        },
    }


def _calibration_model_class(verdict: str) -> str:
    value = str(verdict or "")
    if value == "pack_model_improved":
        return "model_pack_improved"
    if value == "both_model_supported":
        return "model_both_supported"
    if value == "top_model_only":
        return "model_top_only"
    if value == "model_no_support":
        return "model_no_support"
    if value == "dry_run":
        return "dry_run"
    if value == "model_error":
        return "model_error"
    return "model_other"


def _supporting_ref_density(row: dict[str, Any]) -> float:
    pack_refs = row.get("pack_refs") if isinstance(row.get("pack_refs"), list) else []
    supporting = row.get("pack_model", {}).get("supporting_refs") if isinstance(row.get("pack_model"), dict) else []
    if not pack_refs:
        return 0.0
    return round(len(supporting or []) / len(pack_refs), 4)


def build_pack_gate_model_calibration_report(
    cases: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    pack_window: int = 2,
    max_model_cases: int = 18,
    execute_model: bool = False,
    model_config: EvidenceBoundModelConfig | dict | None = None,
    model_client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    example_limit: int = 8,
) -> dict[str, Any]:
    probe = build_pack_gate_model_probe_report(
        cases,
        per_case,
        focus_top_k=focus_top_k,
        pack_window=pack_window,
        max_model_cases=max_model_cases,
        execute_model=execute_model,
        model_config=model_config,
        model_client=model_client,
        example_limit=example_limit,
    )
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    bucket_confusion: dict[str, Counter[str]] = defaultdict(Counter)
    primary_confusion: dict[str, Counter[str]] = defaultdict(Counter)
    cost_confusion: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows: list[dict[str, Any]] = []
    trigger_total = 0
    trigger_pack_improved = 0
    skip_total = 0
    skip_pack_improved = 0
    model_pack_improved_total = 0
    model_no_gain_total = 0
    top_only_total = 0
    dry_run_total = 0
    supporting_density_values: list[float] = []

    for row in probe.get("rows", []):
        if not isinstance(row, dict):
            continue
        heuristic = "heuristic_trigger" if row.get("would_trigger") else "heuristic_skip"
        model_class = _calibration_model_class(str(row.get("model_verdict") or ""))
        confusion[heuristic][model_class] += 1
        bucket_confusion[str(row.get("probe_bucket") or "unknown")][model_class] += 1
        primary_confusion[str(row.get("primary") or "unknown")][model_class] += 1
        cost_confusion[str(row.get("cost_band") or "unknown")][model_class] += 1
        density = _supporting_ref_density(row)
        supporting_density_values.append(density)
        trigger_total += int(heuristic == "heuristic_trigger")
        skip_total += int(heuristic == "heuristic_skip")
        trigger_pack_improved += int(heuristic == "heuristic_trigger" and model_class == "model_pack_improved")
        skip_pack_improved += int(heuristic == "heuristic_skip" and model_class == "model_pack_improved")
        model_pack_improved_total += int(model_class == "model_pack_improved")
        model_no_gain_total += int(model_class in {"model_no_support", "model_both_supported"})
        top_only_total += int(model_class == "model_top_only")
        dry_run_total += int(model_class == "dry_run")
        result_row = {
            "question_id": row.get("question_id", ""),
            "probe_bucket": row.get("probe_bucket", ""),
            "primary": row.get("primary", ""),
            "cost_band": row.get("cost_band", ""),
            "support_delta": row.get("support_delta", ""),
            "heuristic_decision": heuristic,
            "model_class": model_class,
            "model_verdict": row.get("model_verdict", ""),
            "pack_supporting_ref_density": density,
            "top_supporting_refs": row.get("top_model", {}).get("supporting_refs", []),
            "pack_supporting_refs": row.get("pack_model", {}).get("supporting_refs", []),
            "top_unknown_reason": row.get("top_model", {}).get("unknown_reason", ""),
            "pack_unknown_reason": row.get("pack_model", {}).get("unknown_reason", ""),
            "question": row.get("question", ""),
        }
        rows.append(result_row)
        if len(examples[model_class]) < example_limit:
            examples[model_class].append(result_row)

    selected_count = len(rows)
    precision = round(trigger_pack_improved / trigger_total, 4) if trigger_total else 0.0
    recall = round(trigger_pack_improved / model_pack_improved_total, 4) if model_pack_improved_total else 0.0
    skip_miss_rate = round(skip_pack_improved / skip_total, 4) if skip_total else 0.0
    avg_density = round(sum(supporting_density_values) / selected_count, 4) if selected_count else 0.0
    return {
        "contract": PACK_GATE_MODEL_CALIBRATION_REPORT_CONTRACT,
        "focus_top_k": focus_top_k,
        "pack_window": pack_window,
        "case_count": len(cases),
        "selected_case_count": selected_count,
        "max_model_cases": max_model_cases,
        "confusion_matrix": {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(confusion.items())
        },
        "bucket_confusion": {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(bucket_confusion.items())
        },
        "primary_confusion": {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(primary_confusion.items())
        },
        "cost_confusion": {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(cost_confusion.items())
        },
        "metrics": {
            "heuristic_trigger_total": trigger_total,
            "heuristic_skip_total": skip_total,
            "model_pack_improved_total": model_pack_improved_total,
            "trigger_pack_improved": trigger_pack_improved,
            "skip_pack_improved": skip_pack_improved,
            "trigger_precision_for_model_pack_improved": precision,
            "trigger_recall_for_model_pack_improved": recall,
            "skip_miss_rate_for_model_pack_improved": skip_miss_rate,
            "model_no_gain_total": model_no_gain_total,
            "top_only_total": top_only_total,
            "dry_run_total": dry_run_total,
            "avg_pack_supporting_ref_density": avg_density,
        },
        "probe_model": probe.get("model", {}),
        "probe_model_call_count": probe.get("model_call_count", 0),
        "probe_model_error_count": probe.get("model_error_count", 0),
        "examples": dict(sorted(examples.items())),
        "rows": rows,
        "boundary": {
            "official_leaderboard_score": False,
            "diagnostic_only": True,
            "read_only": True,
            "no_memory_write": True,
            "ranking_unchanged": True,
            "daily_entry_integrated": False,
            "runtime_policy": False,
            "model_call_allowed": bool(execute_model or model_client is not None),
            "model_call_performed": bool(probe.get("boundary", {}).get("model_call_performed")),
            "expected_answer_as_draft_only": True,
            "calibrates_heuristic_gate_only": True,
        },
    }


def _supporting_density_bucket(value: float) -> str:
    density = float(value or 0.0)
    if density <= 0:
        return "density_zero"
    if density < 0.1:
        return "density_low"
    if density < 0.2:
        return "density_medium"
    return "density_high"


def _pack_size_bucket(value: Any) -> str:
    size = _int(value, 0)
    if size <= 0:
        return "pack_empty"
    if size <= 5:
        return "pack_tiny"
    if size <= 10:
        return "pack_small"
    if size <= 15:
        return "pack_medium"
    return "pack_large"


def _incremental_tokenish_bucket(value: Any) -> str:
    tokenish = _int(value, 0)
    if tokenish <= 0:
        return "incremental_none"
    if tokenish <= 120:
        return "incremental_tiny"
    if tokenish <= 300:
        return "incremental_small"
    if tokenish <= 700:
        return "incremental_medium"
    return "incremental_large"


def _answered_state(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return "not_answered"
    if result.get("verdict") == "dry_run":
        return "dry_run"
    if _model_answer_supported(result):
        return "answered"
    if result.get("ok") is False:
        return "model_error"
    return "not_answered"


def _unknown_reason_bucket(text: Any) -> str:
    value = str(text or "").lower()
    if not value:
        return "none"
    if "no evidence" in value or "does not contain" in value or "not mention" in value or "insufficient" in value:
        return "insufficient_evidence"
    if "contradict" in value or "conflict" in value or "not " in value or "instead" in value:
        return "contradiction_or_negation"
    if "wrong" in value or "different" in value or "caroline" in value or "melanie" in value:
        return "subject_or_object_mismatch"
    return "other_unknown"


def _feature_hit_rate(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if not total:
        return 0.0
    return round(int(counter.get("model_pack_improved") or 0) / total, 4)


def _feature_bucket_rows(feature_counts: dict[str, Counter[str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket, counter in sorted(feature_counts.items()):
        total = sum(counter.values())
        rows.append(
            {
                "bucket": bucket,
                "total": total,
                "model_counts": dict(sorted(counter.items())),
                "model_pack_improved_rate": _feature_hit_rate(counter),
            }
        )
    return rows


def build_pack_gate_model_feature_report(
    cases: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    pack_window: int = 2,
    max_model_cases: int = 24,
    execute_model: bool = False,
    model_config: EvidenceBoundModelConfig | dict | None = None,
    model_client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    example_limit: int = 8,
) -> dict[str, Any]:
    probe = build_pack_gate_model_probe_report(
        cases,
        per_case,
        focus_top_k=focus_top_k,
        pack_window=pack_window,
        max_model_cases=max_model_cases,
        execute_model=execute_model,
        model_config=model_config,
        model_client=model_client,
        example_limit=example_limit,
    )
    feature_counts: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows: list[dict[str, Any]] = []
    feature_keys = [
        "heuristic_decision",
        "probe_bucket",
        "primary",
        "cost_band",
        "support_delta_diagnostic",
        "pack_size_bucket",
        "incremental_tokenish_bucket",
        "pack_supporting_ref_density_bucket",
        "top_answered_state",
        "pack_answered_state",
        "answer_state_pair",
        "pack_unknown_reason_bucket",
    ]

    for probe_row in probe.get("rows", []):
        if not isinstance(probe_row, dict):
            continue
        model_class = _calibration_model_class(str(probe_row.get("model_verdict") or ""))
        density = _supporting_ref_density(probe_row)
        top_model = probe_row.get("top_model", {}) if isinstance(probe_row.get("top_model"), dict) else {}
        pack_model = probe_row.get("pack_model", {}) if isinstance(probe_row.get("pack_model"), dict) else {}
        top_state = _answered_state(top_model)
        pack_state = _answered_state(pack_model)
        features = {
            "heuristic_decision": "heuristic_trigger" if probe_row.get("would_trigger") else "heuristic_skip",
            "probe_bucket": str(probe_row.get("probe_bucket") or "unknown"),
            "primary": str(probe_row.get("primary") or "unknown"),
            "cost_band": str(probe_row.get("cost_band") or "unknown"),
            "support_delta_diagnostic": str(probe_row.get("support_delta") or "unknown"),
            "pack_size_bucket": _pack_size_bucket(probe_row.get("pack_size") or probe_row.get("pack_evidence_count")),
            "incremental_tokenish_bucket": _incremental_tokenish_bucket(probe_row.get("incremental_tokenish")),
            "pack_supporting_ref_density_bucket": _supporting_density_bucket(density),
            "top_answered_state": top_state,
            "pack_answered_state": pack_state,
            "answer_state_pair": f"top_{top_state}__pack_{pack_state}",
            "pack_unknown_reason_bucket": _unknown_reason_bucket(pack_model.get("unknown_reason", "")),
        }
        for key, value in features.items():
            feature_counts[f"{key}:{value}"][model_class] += 1
        result_row = {
            "question_id": probe_row.get("question_id", ""),
            "model_class": model_class,
            "model_verdict": probe_row.get("model_verdict", ""),
            "pack_supporting_ref_density": density,
            "top_supporting_refs": top_model.get("supporting_refs", []),
            "pack_supporting_refs": pack_model.get("supporting_refs", []),
            "features": features,
            "question": probe_row.get("question", ""),
        }
        rows.append(result_row)
        if len(examples[model_class]) < example_limit:
            examples[model_class].append(result_row)

    by_feature: dict[str, list[dict[str, Any]]] = {}
    for key in feature_keys:
        relevant = {
            bucket.split(":", 1)[1]: counter
            for bucket, counter in feature_counts.items()
            if bucket.startswith(f"{key}:")
        }
        by_feature[key] = _feature_bucket_rows(relevant)
    candidate_positive_signals = [
        row
        for row in sorted(
            _feature_bucket_rows(feature_counts),
            key=lambda item: (
                float(item.get("model_pack_improved_rate") or 0.0),
                int(item.get("total") or 0),
                str(item.get("bucket") or ""),
            ),
            reverse=True,
        )
        if row.get("model_counts", {}).get("model_pack_improved")
    ][:12]
    candidate_negative_signals = [
        row
        for row in sorted(
            _feature_bucket_rows(feature_counts),
            key=lambda item: (
                -float(item.get("model_pack_improved_rate") or 0.0),
                int(item.get("total") or 0),
                str(item.get("bucket") or ""),
            ),
        )
        if not row.get("model_counts", {}).get("model_pack_improved")
    ][:12]
    return {
        "contract": PACK_GATE_MODEL_FEATURE_REPORT_CONTRACT,
        "focus_top_k": focus_top_k,
        "pack_window": pack_window,
        "case_count": len(cases),
        "selected_case_count": len(rows),
        "max_model_cases": max_model_cases,
        "feature_keys": feature_keys,
        "by_feature": by_feature,
        "candidate_positive_signals": candidate_positive_signals,
        "candidate_negative_signals": candidate_negative_signals,
        "probe_model": probe.get("model", {}),
        "probe_model_call_count": probe.get("model_call_count", 0),
        "probe_model_error_count": probe.get("model_error_count", 0),
        "examples": dict(sorted(examples.items())),
        "rows": rows,
        "boundary": {
            "official_leaderboard_score": False,
            "diagnostic_only": True,
            "read_only": True,
            "no_memory_write": True,
            "ranking_unchanged": True,
            "daily_entry_integrated": False,
            "runtime_policy": False,
            "model_call_allowed": bool(execute_model or model_client is not None),
            "model_call_performed": bool(probe.get("boundary", {}).get("model_call_performed")),
            "expected_answer_as_draft_only": True,
            "runtime_available_features_only_for_policy": False,
            "contains_gold_diagnostic_features": True,
        },
    }


def _runtime_candidate_policy(features: dict[str, Any], density: float) -> dict[str, Any]:
    top_state = str(features.get("top_answered_state") or "")
    pack_state = str(features.get("pack_answered_state") or "")
    unknown_bucket = str(features.get("pack_unknown_reason_bucket") or "")
    size_bucket = str(features.get("pack_size_bucket") or "")
    tokenish_bucket = str(features.get("incremental_tokenish_bucket") or "")
    reasons: list[str] = []
    decision = "observe_only"
    confidence = "low"

    if top_state == "dry_run" or pack_state == "dry_run":
        reasons.append("dry_run_no_policy")
    elif pack_state == "not_answered" or density <= 0 or unknown_bucket in {"insufficient_evidence", "subject_or_object_mismatch"}:
        decision = "stop_no_support"
        confidence = "high" if density <= 0 or unknown_bucket == "insufficient_evidence" else "medium"
        if pack_state == "not_answered":
            reasons.append("pack_not_answered")
        if density <= 0:
            reasons.append("density_zero")
        if unknown_bucket and unknown_bucket != "none":
            reasons.append(f"pack_unknown:{unknown_bucket}")
    elif top_state == "not_answered" and pack_state == "answered" and density > 0:
        decision = "trigger_candidate"
        confidence = "medium"
        reasons.append("top_not_answered_pack_answered")
        reasons.append("density_positive")
        if size_bucket in {"pack_large"} or tokenish_bucket in {"incremental_large"}:
            confidence = "low"
            reasons.append("cost_guard_required")
    elif top_state == "answered" and pack_state == "answered":
        decision = "skip_redundant"
        confidence = "medium"
        reasons.append("top_already_answered")
    elif top_state == "answered" and pack_state != "answered":
        decision = "skip_pack_degrades"
        confidence = "high"
        reasons.append("top_answered_pack_not_answered")
    else:
        reasons.append("no_policy_signal")

    return {
        "decision": decision,
        "confidence": confidence,
        "reasons": sorted(set(reasons)),
        "runtime_candidate": decision == "trigger_candidate",
    }


def build_pack_gate_runtime_candidate_report(
    cases: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    pack_window: int = 2,
    max_model_cases: int = 24,
    execute_model: bool = False,
    model_config: EvidenceBoundModelConfig | dict | None = None,
    model_client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    example_limit: int = 8,
) -> dict[str, Any]:
    feature_report = build_pack_gate_model_feature_report(
        cases,
        per_case,
        focus_top_k=focus_top_k,
        pack_window=pack_window,
        max_model_cases=max_model_cases,
        execute_model=execute_model,
        model_config=model_config,
        model_client=model_client,
        example_limit=example_limit,
    )
    decision_counts: Counter[str] = Counter()
    model_by_decision: dict[str, Counter[str]] = defaultdict(Counter)
    confidence_by_decision: dict[str, Counter[str]] = defaultdict(Counter)
    reason_counts: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows: list[dict[str, Any]] = []
    trigger_total = 0
    trigger_pack_improved = 0
    trigger_no_support = 0
    stopped_total = 0
    stopped_pack_improved = 0
    skip_total = 0
    skip_pack_improved = 0

    for feature_row in feature_report.get("rows", []):
        if not isinstance(feature_row, dict):
            continue
        features = feature_row.get("features") if isinstance(feature_row.get("features"), dict) else {}
        density = float(feature_row.get("pack_supporting_ref_density") or 0.0)
        policy = _runtime_candidate_policy(features, density)
        decision = str(policy.get("decision") or "observe_only")
        model_class = str(feature_row.get("model_class") or "unknown")
        decision_counts[decision] += 1
        model_by_decision[decision][model_class] += 1
        confidence_by_decision[decision][str(policy.get("confidence") or "")] += 1
        for reason in policy.get("reasons") or []:
            reason_counts[str(reason)] += 1
        is_trigger = decision == "trigger_candidate"
        is_stopped = decision == "stop_no_support"
        is_skip = decision.startswith("skip_")
        trigger_total += int(is_trigger)
        trigger_pack_improved += int(is_trigger and model_class == "model_pack_improved")
        trigger_no_support += int(is_trigger and model_class == "model_no_support")
        stopped_total += int(is_stopped)
        stopped_pack_improved += int(is_stopped and model_class == "model_pack_improved")
        skip_total += int(is_skip)
        skip_pack_improved += int(is_skip and model_class == "model_pack_improved")
        result_row = {
            "question_id": feature_row.get("question_id", ""),
            "decision": decision,
            "confidence": policy.get("confidence", ""),
            "reasons": policy.get("reasons", []),
            "model_class": model_class,
            "pack_supporting_ref_density": density,
            "features": {
                key: features.get(key, "")
                for key in (
                    "primary",
                    "cost_band",
                    "pack_size_bucket",
                    "incremental_tokenish_bucket",
                    "pack_supporting_ref_density_bucket",
                    "top_answered_state",
                    "pack_answered_state",
                    "answer_state_pair",
                    "pack_unknown_reason_bucket",
                )
            },
            "question": feature_row.get("question", ""),
        }
        rows.append(result_row)
        if len(examples[decision]) < example_limit:
            examples[decision].append(result_row)

    selected_count = len(rows)
    return {
        "contract": PACK_GATE_RUNTIME_CANDIDATE_REPORT_CONTRACT,
        "focus_top_k": focus_top_k,
        "pack_window": pack_window,
        "case_count": len(cases),
        "selected_case_count": selected_count,
        "max_model_cases": max_model_cases,
        "decision_counts": dict(sorted(decision_counts.items())),
        "model_by_decision": {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(model_by_decision.items())
        },
        "confidence_by_decision": {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(confidence_by_decision.items())
        },
        "reason_counts": dict(sorted(reason_counts.items())),
        "metrics": {
            "trigger_candidate_total": trigger_total,
            "trigger_candidate_rate": round(trigger_total / selected_count, 4) if selected_count else 0.0,
            "trigger_candidate_pack_improved": trigger_pack_improved,
            "trigger_candidate_precision": round(trigger_pack_improved / trigger_total, 4) if trigger_total else 0.0,
            "trigger_candidate_no_support": trigger_no_support,
            "stop_no_support_total": stopped_total,
            "stop_no_support_pack_improved": stopped_pack_improved,
            "skip_total": skip_total,
            "skip_pack_improved": skip_pack_improved,
        },
        "probe_model": feature_report.get("probe_model", {}),
        "probe_model_call_count": feature_report.get("probe_model_call_count", 0),
        "probe_model_error_count": feature_report.get("probe_model_error_count", 0),
        "examples": dict(sorted(examples.items())),
        "rows": rows,
        "boundary": {
            "official_leaderboard_score": False,
            "diagnostic_only": True,
            "read_only": True,
            "no_memory_write": True,
            "ranking_unchanged": True,
            "daily_entry_integrated": False,
            "runtime_policy": False,
            "runtime_candidate_report_only": True,
            "model_call_allowed": bool(execute_model or model_client is not None),
            "model_call_performed": bool(feature_report.get("boundary", {}).get("model_call_performed")),
            "uses_gold_expected_answer": False,
            "excludes_gold_diagnostic_policy_fields": True,
        },
    }


def build_evidence_pack_candidate_report(
    cases: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    pack_window: int = 2,
    example_limit: int = 8,
) -> dict[str, Any]:
    per_case_by_id = {str(item.get("question_id") or ""): item for item in per_case}
    label_counts: Counter[str] = Counter()
    primary_by_label: dict[str, Counter[str]] = defaultdict(Counter)
    support_counts: Counter[str] = Counter()
    pack_sizes: list[int] = []
    rows: list[dict[str, Any]] = []
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    gold_questions = 0
    top_exact_hits = 0
    pack_exact_hits = 0
    pack_full_hits = 0
    selected_primary = {"bundle_only", "right_session_wrong_turn", "wrong_session", "coverage_gap"}

    for case in cases:
        question_id = str(case.get("question_id") or "")
        primary = _case_primary(per_case_by_id, question_id, focus_top_k)
        if primary not in selected_primary:
            continue
        gold_refs = [str(value) for value in case.get("expected_source_refs") or [] if str(value)]
        if not gold_refs:
            continue
        row = per_case_by_id.get(question_id, {})
        top_results = row.get("top_results") if isinstance(row.get("top_results"), list) else []
        top_results = top_results[: max(int(focus_top_k), 1)]
        order_index, ref_sessions = _source_order_index(case)
        lookup = _source_unit_lookup(case)
        pack_ref_candidates: list[str] = []
        top_refs: list[str] = []
        for top in top_results:
            top_ref = str(top.get("evidence_ref") or top.get("source_id") or "")
            if top_ref:
                top_refs.append(_canonical_ref(top_ref, lookup))
            synthetic_top = dict(top)
            synthetic_top["context_window"] = max(_int(top.get("context_window"), 0), int(pack_window))
            pack_ref_candidates.extend(
                _canonical_ref(ref, lookup)
                for ref in _neighbor_refs_for_top_result(case, synthetic_top, order_index, ref_sessions)
            )
        pack_refs = _ordered_unique_refs(pack_ref_candidates, order_index)
        gold_set = set(gold_refs)
        top_overlap = sorted(gold_set & set(top_refs))
        pack_overlap = sorted(gold_set & set(pack_refs))
        if gold_set and gold_set <= set(top_refs):
            label = "top_already_full_gold"
        elif gold_set and gold_set <= set(pack_refs):
            label = "pack_full_gold"
        elif pack_overlap:
            label = "pack_partial_gold"
        else:
            label = "pack_missing_gold"
        label_counts[label] += 1
        primary_by_label[label][primary] += 1
        gold_questions += 1
        top_exact_hits += int(bool(top_overlap))
        pack_exact_hits += int(bool(pack_overlap))
        pack_full_hits += int(bool(gold_set and gold_set <= set(pack_refs)))
        pack_sizes.append(len(pack_refs))
        support_label = _pack_support_label(case, pack_refs, lookup)
        support_counts[support_label] += 1
        result_row = {
            "question_id": question_id,
            "question_type": case.get("question_type", ""),
            "primary": primary,
            "label": label,
            "question": _compact(case.get("question", ""), 220),
            "answer": _compact(case.get("answer", ""), 180),
            "expected_source_refs": gold_refs,
            "top_refs": top_refs,
            "pack_refs": pack_refs,
            "pack_size": len(pack_refs),
            "top_overlap": top_overlap,
            "pack_overlap": pack_overlap,
            "pack_missing_refs": sorted(gold_set - set(pack_refs)),
            "pack_support_label": support_label,
            "question_signals": _aggregation_question_signals(case.get("question", "")),
            "pack_preview": [
                {
                    "ref": ref,
                    "session_id": ref_sessions.get(ref, ""),
                    "text": _compact(lookup.get(ref, {}).get("text", ""), 140),
                }
                for ref in pack_refs[:12]
            ],
        }
        rows.append(result_row)
        if len(examples[label]) < example_limit:
            examples[label].append(result_row)

    avg_pack_size = round(sum(pack_sizes) / len(pack_sizes), 2) if pack_sizes else 0.0
    return {
        "contract": EVIDENCE_PACK_CANDIDATE_REPORT_CONTRACT,
        "focus_top_k": focus_top_k,
        "pack_window": pack_window,
        "case_count": len(cases),
        "selected_case_count": len(rows),
        "label_counts": dict(sorted(label_counts.items())),
        "primary_by_label": {
            label: dict(sorted(counter.items()))
            for label, counter in sorted(primary_by_label.items())
        },
        "support_counts": dict(sorted(support_counts.items())),
        "metrics": {
            "gold_questions": gold_questions,
            "top_any_gold_recall": round(top_exact_hits / gold_questions, 4) if gold_questions else 0.0,
            "pack_any_gold_recall": round(pack_exact_hits / gold_questions, 4) if gold_questions else 0.0,
            "pack_full_gold_recall": round(pack_full_hits / gold_questions, 4) if gold_questions else 0.0,
            "avg_pack_size": avg_pack_size,
            "max_pack_size": max(pack_sizes) if pack_sizes else 0,
        },
        "examples": dict(sorted(examples.items())),
        "rows": rows,
        "boundary": {
            "official_leaderboard_score": False,
            "no_model_call": True,
            "no_memory_write": True,
            "read_only": True,
            "ranking_unchanged": True,
            "diagnostic_only": True,
            "raw_evidence_required": True,
        },
    }


def build_pack_aware_answer_support_report(
    cases: list[dict[str, Any]],
    per_case: list[dict[str, Any]],
    *,
    focus_top_k: int = 3,
    pack_window: int = 2,
    example_limit: int = 8,
) -> dict[str, Any]:
    per_case_by_id = {str(item.get("question_id") or ""): item for item in per_case}
    selected_primary = {"bundle_only", "right_session_wrong_turn", "wrong_session", "coverage_gap"}
    top_support_counts: Counter[str] = Counter()
    pack_support_counts: Counter[str] = Counter()
    support_delta_counts: Counter[str] = Counter()
    primary_by_delta: dict[str, Counter[str]] = defaultdict(Counter)
    question_signal_by_delta: dict[str, Counter[str]] = defaultdict(Counter)
    cost_band_counts: Counter[str] = Counter()
    cost_band_by_delta: dict[str, Counter[str]] = defaultdict(Counter)
    rows: list[dict[str, Any]] = []
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pack_sizes: list[int] = []
    pack_tokenish_values: list[int] = []
    incremental_tokenish_values: list[int] = []
    improved_pack_sizes: list[int] = []
    improved_pack_tokenish_values: list[int] = []
    top_supported_count = 0
    pack_supported_count = 0
    pack_improved_count = 0

    for case in cases:
        question_id = str(case.get("question_id") or "")
        primary = _case_primary(per_case_by_id, question_id, focus_top_k)
        if primary not in selected_primary:
            continue
        gold_refs = [str(value) for value in case.get("expected_source_refs") or [] if str(value)]
        if not gold_refs:
            continue
        row = per_case_by_id.get(question_id, {})
        top_results = row.get("top_results") if isinstance(row.get("top_results"), list) else []
        top_results = top_results[: max(int(focus_top_k), 1)]
        order_index, ref_sessions = _source_order_index(case)
        lookup = dict(_source_unit_lookup(case))
        for top in top_results:
            if not isinstance(top, dict):
                continue
            source_id = str(top.get("source_id") or "")
            evidence_ref = str(top.get("evidence_ref") or source_id)
            if evidence_ref and evidence_ref not in lookup:
                lookup[evidence_ref] = top
            if source_id and source_id not in lookup:
                lookup[source_id] = top
        pack_ref_candidates: list[str] = []
        top_refs: list[str] = []
        for top in top_results:
            if not isinstance(top, dict):
                continue
            top_ref = _canonical_ref(top.get("evidence_ref") or top.get("source_id") or "", lookup)
            if top_ref:
                top_refs.append(top_ref)
            synthetic_top = dict(top)
            synthetic_top["context_window"] = max(_int(top.get("context_window"), 0), int(pack_window))
            pack_ref_candidates.extend(
                _canonical_ref(ref, lookup)
                for ref in _neighbor_refs_for_top_result(case, synthetic_top, order_index, ref_sessions)
            )
        top_refs = _ordered_unique_refs(top_refs, order_index)
        pack_refs = _ordered_unique_refs(pack_ref_candidates, order_index)
        top_label = _answer_support_label(case, top_refs, lookup, scope="top")
        pack_label = _answer_support_label(case, pack_refs, lookup, scope="pack")
        delta = _support_delta_label(top_label, pack_label)
        top_supported = _support_is_positive(top_label)
        pack_supported = _support_is_positive(pack_label)
        top_supported_count += int(top_supported)
        pack_supported_count += int(pack_supported)
        pack_improved_count += int(delta == "pack_improved")
        top_support_counts[top_label] += 1
        pack_support_counts[pack_label] += 1
        support_delta_counts[delta] += 1
        primary_by_delta[delta][primary] += 1
        pack_size = len(pack_refs)
        top_tokenish = _refs_tokenish_count(top_refs, lookup)
        pack_tokenish = _refs_tokenish_count(pack_refs, lookup)
        incremental_refs = [ref for ref in pack_refs if ref not in set(top_refs)]
        incremental_tokenish = _refs_tokenish_count(incremental_refs, lookup)
        cost_band = _pack_cost_band(pack_size, pack_tokenish)
        cost_band_counts[cost_band] += 1
        cost_band_by_delta[delta][cost_band] += 1
        pack_sizes.append(pack_size)
        pack_tokenish_values.append(pack_tokenish)
        incremental_tokenish_values.append(incremental_tokenish)
        if delta == "pack_improved":
            improved_pack_sizes.append(pack_size)
            improved_pack_tokenish_values.append(pack_tokenish)
        question_signals = _aggregation_question_signals(case.get("question", ""))
        for signal in question_signals or ["none"]:
            question_signal_by_delta[delta][signal] += 1
        gold_set = set(gold_refs)
        pack_overlap = sorted(gold_set & set(pack_refs))
        result_row = {
            "question_id": question_id,
            "question_type": case.get("question_type", ""),
            "primary": primary,
            "question": _compact(case.get("question", ""), 220),
            "answer": _compact(case.get("answer", ""), 180),
            "expected_source_refs": gold_refs,
            "top_refs": top_refs,
            "pack_refs": pack_refs,
            "incremental_refs": incremental_refs,
            "pack_overlap": pack_overlap,
            "pack_missing_refs": sorted(gold_set - set(pack_refs)),
            "top_support_label": top_label,
            "pack_support_label": pack_label,
            "top_supported": top_supported,
            "pack_supported": pack_supported,
            "support_delta": delta,
            "pack_size": pack_size,
            "top_tokenish": top_tokenish,
            "pack_tokenish": pack_tokenish,
            "incremental_tokenish": incremental_tokenish,
            "cost_band": cost_band,
            "question_signals": question_signals,
            "pack_preview": [
                {
                    "ref": ref,
                    "session_id": ref_sessions.get(ref, ""),
                    "text": _compact(lookup.get(ref, {}).get("text", ""), 140),
                }
                for ref in pack_refs[:12]
            ],
        }
        rows.append(result_row)
        if len(examples[delta]) < example_limit:
            examples[delta].append(result_row)

    selected_count = len(rows)
    avg_pack_size = round(sum(pack_sizes) / selected_count, 2) if selected_count else 0.0
    avg_pack_tokenish = round(sum(pack_tokenish_values) / selected_count, 2) if selected_count else 0.0
    avg_incremental_tokenish = round(sum(incremental_tokenish_values) / selected_count, 2) if selected_count else 0.0
    return {
        "contract": PACK_AWARE_ANSWER_SUPPORT_REPORT_CONTRACT,
        "focus_top_k": focus_top_k,
        "pack_window": pack_window,
        "case_count": len(cases),
        "selected_case_count": selected_count,
        "selected_primary": sorted(selected_primary),
        "top_support_counts": dict(sorted(top_support_counts.items())),
        "pack_support_counts": dict(sorted(pack_support_counts.items())),
        "support_delta_counts": dict(sorted(support_delta_counts.items())),
        "primary_by_delta": {
            delta: dict(sorted(counter.items()))
            for delta, counter in sorted(primary_by_delta.items())
        },
        "question_signal_by_delta": {
            delta: dict(sorted(counter.items()))
            for delta, counter in sorted(question_signal_by_delta.items())
        },
        "cost_band_counts": dict(sorted(cost_band_counts.items())),
        "cost_band_by_delta": {
            delta: dict(sorted(counter.items()))
            for delta, counter in sorted(cost_band_by_delta.items())
        },
        "metrics": {
            "top_supported_count": top_supported_count,
            "top_supported_rate": round(top_supported_count / selected_count, 4) if selected_count else 0.0,
            "pack_supported_count": pack_supported_count,
            "pack_supported_rate": round(pack_supported_count / selected_count, 4) if selected_count else 0.0,
            "pack_improved_count": pack_improved_count,
            "pack_improved_rate": round(pack_improved_count / selected_count, 4) if selected_count else 0.0,
            "avg_pack_size": avg_pack_size,
            "max_pack_size": max(pack_sizes) if pack_sizes else 0,
            "avg_pack_tokenish": avg_pack_tokenish,
            "max_pack_tokenish": max(pack_tokenish_values) if pack_tokenish_values else 0,
            "avg_incremental_tokenish": avg_incremental_tokenish,
            "max_incremental_tokenish": max(incremental_tokenish_values) if incremental_tokenish_values else 0,
            "avg_improved_pack_size": round(sum(improved_pack_sizes) / len(improved_pack_sizes), 2) if improved_pack_sizes else 0.0,
            "avg_improved_pack_tokenish": round(sum(improved_pack_tokenish_values) / len(improved_pack_tokenish_values), 2) if improved_pack_tokenish_values else 0.0,
        },
        "examples": dict(sorted(examples.items())),
        "rows": rows,
        "boundary": {
            "official_leaderboard_score": False,
            "no_model_call": True,
            "no_memory_write": True,
            "read_only": True,
            "ranking_unchanged": True,
            "diagnostic_only": True,
            "raw_evidence_required": True,
            "daily_entry_integrated": False,
        },
    }


def build_eval_miss_report(
    *,
    run_dir: str | Path | None = None,
    dataset: str = "",
    split: str = "oracle",
    data_path: str | Path | None = None,
    download: bool = False,
    cache_root: str | Path | None = None,
    force_download: bool = False,
    max_conversations: int | None = None,
    max_questions: int | None = None,
    retrieval_mode: str = "",
    focus_top_k: int = 3,
    compare_top_k_values: Iterable[int] | None = None,
    example_limit: int = 8,
    include_evidence_object_state: bool = False,
    evidence_object_state_max_cases: int = 20,
    evidence_object_state_execute_model: bool = False,
    evidence_object_state_model_config: EvidenceBoundModelConfig | dict | None = None,
    evidence_object_state_model_client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    include_pack_gate_model_probe: bool = False,
    pack_gate_model_probe_max_cases: int = 9,
    pack_gate_model_probe_execute_model: bool = False,
    pack_gate_model_probe_model_config: EvidenceBoundModelConfig | dict | None = None,
    pack_gate_model_probe_model_client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    include_pack_gate_model_calibration: bool = False,
    pack_gate_model_calibration_max_cases: int = 18,
    pack_gate_model_calibration_execute_model: bool = False,
    pack_gate_model_calibration_model_config: EvidenceBoundModelConfig | dict | None = None,
    pack_gate_model_calibration_model_client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    include_pack_gate_model_feature: bool = False,
    pack_gate_model_feature_max_cases: int = 24,
    pack_gate_model_feature_execute_model: bool = False,
    pack_gate_model_feature_model_config: EvidenceBoundModelConfig | dict | None = None,
    pack_gate_model_feature_model_client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
    include_pack_gate_runtime_candidate: bool = False,
    pack_gate_runtime_candidate_max_cases: int = 24,
    pack_gate_runtime_candidate_execute_model: bool = False,
    pack_gate_runtime_candidate_model_config: EvidenceBoundModelConfig | dict | None = None,
    pack_gate_runtime_candidate_model_client: Callable[[list[dict], EvidenceBoundModelConfig], Any] | None = None,
) -> dict[str, Any]:
    inferred = infer_options_from_run_dir(run_dir)
    dataset = str(dataset or inferred.get("dataset") or "").lower()
    if not dataset:
        raise ValueError("dataset is required when --run-dir does not provide one")
    split = str(split or inferred.get("split") or "oracle").lower()
    if dataset == "locomo":
        split = "locomo10"
    retrieval_mode = str(
        retrieval_mode
        or inferred.get("retrieval_mode")
        or DEFAULT_RETRIEVAL_MODE
    )
    focus_top_k = _int(focus_top_k or inferred.get("top_k"), 3)
    max_questions = max_questions if max_questions is not None else (inferred.get("max_questions") or None)
    top_values = _top_k_values(compare_top_k_values or [focus_top_k, 5, 10, 20], focus_top_k)
    result = run_official_memory_diagnostic(
        dataset=dataset,
        split=split if dataset == "longmemeval" else "oracle",
        data_path=data_path,
        download=download,
        cache_root=cache_root or DEFAULT_CACHE_ROOT,
        force_download=force_download,
        max_conversations=max_conversations,
        max_questions=max_questions,
        top_k_values=top_values,
        retrieval_mode=retrieval_mode,
    )
    per_case = result.get("per_case", [])
    cases = load_cases(
        dataset=dataset,
        split=split if dataset == "longmemeval" else "oracle",
        data_path=result.get("data_path", ""),
        max_conversations=max_conversations if dataset == "locomo" else None,
        max_questions=max_questions,
    )
    report = {
        "ok": True,
        "contract": EVAL_MISS_REPORT_CONTRACT,
        "dataset": dataset,
        "split": result.get("split", split),
        "data_path": result.get("data_path", ""),
        "source_run": {
            "run_dir": inferred.get("run_dir", ""),
            "run_id": inferred.get("run_id", ""),
            "host_label": inferred.get("host_label", ""),
        },
        "retrieval_mode": retrieval_mode,
        "focus_top_k": focus_top_k,
        "compare_top_k": top_values,
        "case_count": result.get("case_count", 0),
        "source_unit_count": result.get("source_unit_count", 0),
        "metrics": result.get("metrics", {}),
        "focus_miss_classification": _classification_summary(per_case, focus_top_k),
        "candidate_pool_recovery": _recovery_counts(
            per_case,
            focus_top_k=focus_top_k,
            top_k_values=top_values,
        ),
        "session_routing": build_session_routing_report(
            cases,
            focus_top_k=focus_top_k,
            top_k_values=top_values,
            example_limit=example_limit,
        ),
        "entity_subject_session": build_entity_subject_session_report(
            cases,
            per_case,
            focus_top_k=focus_top_k,
            example_limit=example_limit,
        ),
        "multi_evidence_aggregation": build_multi_evidence_aggregation_report(
            cases,
            per_case,
            focus_top_k=focus_top_k,
            example_limit=example_limit,
        ),
        "evidence_pack_candidate": build_evidence_pack_candidate_report(
            cases,
            per_case,
            focus_top_k=focus_top_k,
            example_limit=example_limit,
        ),
        "pack_aware_answer_support": build_pack_aware_answer_support_report(
            cases,
            per_case,
            focus_top_k=focus_top_k,
            example_limit=example_limit,
        ),
        "pack_trigger_gate": build_pack_trigger_gate_report(
            cases,
            per_case,
            focus_top_k=focus_top_k,
            example_limit=example_limit,
        ),
        "examples": _miss_examples(per_case, k=focus_top_k, limit=max(int(example_limit), 0)),
        "boundary": {
            "official_leaderboard_score": False,
            "no_model_call": True,
            "no_memory_write": True,
            "read_only": True,
        },
    }
    if include_evidence_object_state:
        report["evidence_object_state"] = build_evidence_object_state_report(
            cases,
            per_case,
            focus_top_k=focus_top_k,
            max_model_cases=evidence_object_state_max_cases,
            execute_model=evidence_object_state_execute_model,
            model_config=evidence_object_state_model_config,
            model_client=evidence_object_state_model_client,
            example_limit=example_limit,
        )
        report["boundary"]["no_model_call"] = not bool(
            report["evidence_object_state"]["boundary"].get("model_call_performed")
        )
    if include_pack_gate_model_probe:
        report["pack_gate_model_probe"] = build_pack_gate_model_probe_report(
            cases,
            per_case,
            focus_top_k=focus_top_k,
            max_model_cases=pack_gate_model_probe_max_cases,
            execute_model=pack_gate_model_probe_execute_model,
            model_config=pack_gate_model_probe_model_config,
            model_client=pack_gate_model_probe_model_client,
            example_limit=example_limit,
        )
        if report["pack_gate_model_probe"]["boundary"].get("model_call_performed"):
            report["boundary"]["no_model_call"] = False
    if include_pack_gate_model_calibration:
        report["pack_gate_model_calibration"] = build_pack_gate_model_calibration_report(
            cases,
            per_case,
            focus_top_k=focus_top_k,
            max_model_cases=pack_gate_model_calibration_max_cases,
            execute_model=pack_gate_model_calibration_execute_model,
            model_config=pack_gate_model_calibration_model_config,
            model_client=pack_gate_model_calibration_model_client,
            example_limit=example_limit,
        )
        if report["pack_gate_model_calibration"]["boundary"].get("model_call_performed"):
            report["boundary"]["no_model_call"] = False
    if include_pack_gate_model_feature:
        report["pack_gate_model_feature"] = build_pack_gate_model_feature_report(
            cases,
            per_case,
            focus_top_k=focus_top_k,
            max_model_cases=pack_gate_model_feature_max_cases,
            execute_model=pack_gate_model_feature_execute_model,
            model_config=pack_gate_model_feature_model_config,
            model_client=pack_gate_model_feature_model_client,
            example_limit=example_limit,
        )
        if report["pack_gate_model_feature"]["boundary"].get("model_call_performed"):
            report["boundary"]["no_model_call"] = False
    if include_pack_gate_runtime_candidate:
        report["pack_gate_runtime_candidate"] = build_pack_gate_runtime_candidate_report(
            cases,
            per_case,
            focus_top_k=focus_top_k,
            max_model_cases=pack_gate_runtime_candidate_max_cases,
            execute_model=pack_gate_runtime_candidate_execute_model,
            model_config=pack_gate_runtime_candidate_model_config,
            model_client=pack_gate_runtime_candidate_model_client,
            example_limit=example_limit,
        )
        if report["pack_gate_runtime_candidate"]["boundary"].get("model_call_performed"):
            report["boundary"]["no_model_call"] = False
    return report


def render_eval_miss_report_markdown(report: dict[str, Any]) -> str:
    boundary = report.get("boundary", {})
    lines = [
        "# Memcore Eval Miss Report",
        "",
        f"- dataset: {report.get('dataset', '')}",
        f"- retrieval_mode: {report.get('retrieval_mode', '')}",
        f"- focus_top_k: {report.get('focus_top_k', '')}",
        f"- cases: {report.get('case_count', 0)}",
        "- official_leaderboard_score: false",
        f"- no_model_call: {str(bool(boundary.get('no_model_call', True))).lower()}",
        "- no_memory_write: true",
        "",
        "## Candidate Pool",
        "| top_k | exact | bundled | session | gold anchor |",
        "|---:|---:|---:|---:|---:|",
    ]
    for k in report.get("compare_top_k", []):
        row = report.get("metrics", {}).get(str(k), {})
        lines.append(
            "| {k} | {exact:.4f} | {bundled:.4f} | {session:.4f} | {anchor:.4f} |".format(
                k=k,
                exact=float(row.get("exact_source_recall") or 0),
                bundled=float(row.get("bundled_source_recall") or 0),
                session=float(row.get("session_recall") or 0),
                anchor=float(row.get("gold_anchor_recall") or 0),
            )
        )
    miss = report.get("focus_miss_classification", {})
    lines.extend(
        [
            "",
            "## Focus Misses",
            f"- primary: {miss.get('primary_counts', {})}",
            f"- tags: {miss.get('tag_counts', {})}",
            f"- recovered by larger k: {report.get('candidate_pool_recovery', {})}",
            "",
            "## Session Routing",
            "| route | top_k | session recall | hits / gold |",
            "|---|---:|---:|---:|",
        ]
    )
    session_routing = report.get("session_routing", {})
    for route, by_k in session_routing.get("metrics", {}).items():
        for k in session_routing.get("top_k", []):
            row = by_k.get(str(k), {})
            lines.append(
                "| {route} | {k} | {recall:.4f} | {hits} / {gold} |".format(
                    route=route,
                    k=k,
                    recall=float(row.get("session_recall") or 0),
                    hits=int(row.get("session_hits") or 0),
                    gold=int(row.get("gold_questions") or 0),
                )
            )
    lines.extend(
        [
            "",
            "## Entity / Subject Session Diagnostic",
            f"- label_counts: {report.get('entity_subject_session', {}).get('label_counts', {})}",
            f"- evidence_label_counts: {report.get('entity_subject_session', {}).get('evidence_label_counts', {})}",
            f"- signal_counts: {report.get('entity_subject_session', {}).get('signal_counts', {})}",
            "",
            "## Multi Evidence Aggregation Diagnostic",
            f"- label_counts: {report.get('multi_evidence_aggregation', {}).get('label_counts', {})}",
            f"- signal_counts: {report.get('multi_evidence_aggregation', {}).get('signal_counts', {})}",
            f"- selected_cases: {report.get('multi_evidence_aggregation', {}).get('selected_case_count', 0)}",
            "",
            "## Evidence Pack Candidate",
            f"- label_counts: {report.get('evidence_pack_candidate', {}).get('label_counts', {})}",
            f"- support_counts: {report.get('evidence_pack_candidate', {}).get('support_counts', {})}",
            f"- metrics: {report.get('evidence_pack_candidate', {}).get('metrics', {})}",
            "",
            "## Pack Aware Answer Support",
            f"- support_delta_counts: {report.get('pack_aware_answer_support', {}).get('support_delta_counts', {})}",
            f"- top_support_counts: {report.get('pack_aware_answer_support', {}).get('top_support_counts', {})}",
            f"- pack_support_counts: {report.get('pack_aware_answer_support', {}).get('pack_support_counts', {})}",
            f"- cost_band_counts: {report.get('pack_aware_answer_support', {}).get('cost_band_counts', {})}",
            f"- metrics: {report.get('pack_aware_answer_support', {}).get('metrics', {})}",
            "",
            "## Pack Trigger Gate Diagnostic",
            f"- trigger_counts: {report.get('pack_trigger_gate', {}).get('trigger_counts', {})}",
            f"- skip_reason_counts: {report.get('pack_trigger_gate', {}).get('skip_reason_counts', {})}",
            f"- gain_bucket_counts: {report.get('pack_trigger_gate', {}).get('gain_bucket_counts', {})}",
            f"- cost_bucket_counts: {report.get('pack_trigger_gate', {}).get('cost_bucket_counts', {})}",
            f"- metrics: {report.get('pack_trigger_gate', {}).get('metrics', {})}",
            "",
        ]
    )
    if report.get("evidence_object_state"):
        state_report = report.get("evidence_object_state", {})
        state_boundary = state_report.get("boundary", {})
        lines.extend(
            [
                "## Evidence Object / State Diagnostic",
                f"- contract: {state_report.get('contract', '')}",
                f"- selected_cases: {state_report.get('selected_case_count', 0)} / {state_report.get('case_count', 0)}",
                f"- model_call_performed: {str(bool(state_boundary.get('model_call_performed'))).lower()}",
                f"- ranking_unchanged: {str(bool(state_boundary.get('ranking_unchanged', True))).lower()}",
                f"- raw_evidence_required: {str(bool(state_boundary.get('raw_evidence_required', True))).lower()}",
                f"- verdict_counts: {state_report.get('verdict_counts', {})}",
                f"- primary_by_verdict: {state_report.get('primary_by_verdict', {})}",
                "",
            ]
        )
        for verdict, examples in list((state_report.get("examples") or {}).items())[:6]:
            lines.append(f"### {verdict}")
            for item in examples[:3]:
                diagnostic = item.get("diagnostic", {})
                lines.append(
                    "- {qid}: {primary} | gold={gold} | top={top} | confidence={confidence:.2f}".format(
                        qid=item.get("question_id", ""),
                        primary=item.get("primary", ""),
                        gold=item.get("gold_refs", []),
                        top=item.get("top_refs", []),
                        confidence=float(diagnostic.get("confidence") or 0.0),
                    )
                )
                reason = diagnostic.get("mismatch_reason") or diagnostic.get("unknown_reason") or ""
                if reason:
                    lines.append(f"  reason: {_compact(reason, 180)}")
            lines.append("")
    if report.get("pack_gate_model_probe"):
        probe_report = report.get("pack_gate_model_probe", {})
        probe_boundary = probe_report.get("boundary", {})
        lines.extend(
            [
                "## Pack Gate Model Probe",
                f"- contract: {probe_report.get('contract', '')}",
                f"- selected_cases: {probe_report.get('selected_case_count', 0)} / {probe_report.get('case_count', 0)}",
                f"- model_call_performed: {str(bool(probe_boundary.get('model_call_performed'))).lower()}",
                f"- ranking_unchanged: {str(bool(probe_boundary.get('ranking_unchanged', True))).lower()}",
                f"- runtime_policy: {str(bool(probe_boundary.get('runtime_policy'))).lower()}",
                f"- expected_answer_as_draft_only: {str(bool(probe_boundary.get('expected_answer_as_draft_only', True))).lower()}",
                f"- verdict_counts: {probe_report.get('verdict_counts', {})}",
                f"- bucket_by_verdict: {probe_report.get('bucket_by_verdict', {})}",
                "",
            ]
        )
        for verdict, examples in list((probe_report.get("examples") or {}).items())[:6]:
            lines.append(f"### probe {verdict}")
            for item in examples[:3]:
                top_model = item.get("top_model", {})
                pack_model = item.get("pack_model", {})
                lines.append(
                    "- {qid}: bucket={bucket} | gate={gate} | delta={delta} | top={top_verdict} | pack={pack_verdict}".format(
                        qid=item.get("question_id", ""),
                        bucket=item.get("probe_bucket", ""),
                        gate=str(bool(item.get("would_trigger"))).lower(),
                        delta=item.get("support_delta", ""),
                        top_verdict=top_model.get("verdict", ""),
                        pack_verdict=pack_model.get("verdict", ""),
                    )
                )
                lines.append(f"  Q: {item.get('question', '')}")
                lines.append(
                    "  top_refs={refs} supporting={supporting} reason={reason}".format(
                        refs=item.get("top_refs", []),
                        supporting=top_model.get("supporting_refs", []),
                        reason=_compact(top_model.get("unknown_reason", ""), 140),
                    )
                )
                lines.append(
                    "  pack_refs={refs} supporting={supporting} reason={reason}".format(
                        refs=item.get("pack_refs", []),
                        supporting=pack_model.get("supporting_refs", []),
                        reason=_compact(pack_model.get("unknown_reason", ""), 140),
                    )
                )
            lines.append("")
    if report.get("pack_gate_model_calibration"):
        calibration = report.get("pack_gate_model_calibration", {})
        calibration_boundary = calibration.get("boundary", {})
        lines.extend(
            [
                "## Pack Gate Model Calibration",
                f"- contract: {calibration.get('contract', '')}",
                f"- selected_cases: {calibration.get('selected_case_count', 0)} / {calibration.get('case_count', 0)}",
                f"- model_call_performed: {str(bool(calibration_boundary.get('model_call_performed'))).lower()}",
                f"- runtime_policy: {str(bool(calibration_boundary.get('runtime_policy'))).lower()}",
                f"- confusion_matrix: {calibration.get('confusion_matrix', {})}",
                f"- bucket_confusion: {calibration.get('bucket_confusion', {})}",
                f"- cost_confusion: {calibration.get('cost_confusion', {})}",
                f"- metrics: {calibration.get('metrics', {})}",
                "",
            ]
        )
        for model_class, examples in list((calibration.get("examples") or {}).items())[:6]:
            lines.append(f"### calibration {model_class}")
            for item in examples[:3]:
                lines.append(
                    "- {qid}: {heuristic} -> {model_class} | bucket={bucket} | density={density:.4f}".format(
                        qid=item.get("question_id", ""),
                        heuristic=item.get("heuristic_decision", ""),
                        model_class=item.get("model_class", ""),
                        bucket=item.get("probe_bucket", ""),
                        density=float(item.get("pack_supporting_ref_density") or 0.0),
                    )
                )
                lines.append(f"  Q: {item.get('question', '')}")
                if item.get("pack_unknown_reason"):
                    lines.append(f"  pack_reason: {_compact(item.get('pack_unknown_reason', ''), 160)}")
            lines.append("")
    if report.get("pack_gate_model_feature"):
        feature_report = report.get("pack_gate_model_feature", {})
        feature_boundary = feature_report.get("boundary", {})
        lines.extend(
            [
                "## Pack Gate Model Feature Diagnostic",
                f"- contract: {feature_report.get('contract', '')}",
                f"- selected_cases: {feature_report.get('selected_case_count', 0)} / {feature_report.get('case_count', 0)}",
                f"- model_call_performed: {str(bool(feature_boundary.get('model_call_performed'))).lower()}",
                f"- runtime_policy: {str(bool(feature_boundary.get('runtime_policy'))).lower()}",
                f"- runtime_available_features_only_for_policy: {str(bool(feature_boundary.get('runtime_available_features_only_for_policy'))).lower()}",
                f"- contains_gold_diagnostic_features: {str(bool(feature_boundary.get('contains_gold_diagnostic_features'))).lower()}",
                "- candidate_positive_signals:",
            ]
        )
        for item in (feature_report.get("candidate_positive_signals") or [])[:8]:
            lines.append(
                "  - {bucket}: total={total} rate={rate:.4f} counts={counts}".format(
                    bucket=item.get("bucket", ""),
                    total=int(item.get("total") or 0),
                    rate=float(item.get("model_pack_improved_rate") or 0.0),
                    counts=item.get("model_counts", {}),
                )
            )
        lines.append("- candidate_negative_signals:")
        for item in (feature_report.get("candidate_negative_signals") or [])[:8]:
            lines.append(
                "  - {bucket}: total={total} rate={rate:.4f} counts={counts}".format(
                    bucket=item.get("bucket", ""),
                    total=int(item.get("total") or 0),
                    rate=float(item.get("model_pack_improved_rate") or 0.0),
                    counts=item.get("model_counts", {}),
                )
            )
        lines.append("")
        for model_class, examples in list((feature_report.get("examples") or {}).items())[:6]:
            lines.append(f"### feature {model_class}")
            for item in examples[:3]:
                features = item.get("features", {})
                lines.append(
                    "- {qid}: density={density:.4f} | {state_pair} | {primary} | {cost}".format(
                        qid=item.get("question_id", ""),
                        density=float(item.get("pack_supporting_ref_density") or 0.0),
                        state_pair=features.get("answer_state_pair", ""),
                        primary=features.get("primary", ""),
                        cost=features.get("cost_band", ""),
                    )
                )
                lines.append(f"  Q: {item.get('question', '')}")
            lines.append("")
    if report.get("pack_gate_runtime_candidate"):
        runtime_report = report.get("pack_gate_runtime_candidate", {})
        runtime_boundary = runtime_report.get("boundary", {})
        lines.extend(
            [
                "## Pack Gate Runtime Candidate Diagnostic",
                f"- contract: {runtime_report.get('contract', '')}",
                f"- selected_cases: {runtime_report.get('selected_case_count', 0)} / {runtime_report.get('case_count', 0)}",
                f"- model_call_performed: {str(bool(runtime_boundary.get('model_call_performed'))).lower()}",
                f"- runtime_policy: {str(bool(runtime_boundary.get('runtime_policy'))).lower()}",
                f"- runtime_candidate_report_only: {str(bool(runtime_boundary.get('runtime_candidate_report_only'))).lower()}",
                f"- uses_gold_expected_answer: {str(bool(runtime_boundary.get('uses_gold_expected_answer'))).lower()}",
                f"- excludes_gold_diagnostic_policy_fields: {str(bool(runtime_boundary.get('excludes_gold_diagnostic_policy_fields'))).lower()}",
                f"- decision_counts: {runtime_report.get('decision_counts', {})}",
                f"- model_by_decision: {runtime_report.get('model_by_decision', {})}",
                f"- reason_counts: {runtime_report.get('reason_counts', {})}",
                f"- metrics: {runtime_report.get('metrics', {})}",
                "",
            ]
        )
        for decision, examples in list((runtime_report.get("examples") or {}).items())[:6]:
            lines.append(f"### runtime candidate {decision}")
            for item in examples[:3]:
                features = item.get("features", {})
                lines.append(
                    "- {qid}: model={model} | confidence={confidence} | density={density:.4f} | reasons={reasons}".format(
                        qid=item.get("question_id", ""),
                        model=item.get("model_class", ""),
                        confidence=item.get("confidence", ""),
                        density=float(item.get("pack_supporting_ref_density") or 0.0),
                        reasons=item.get("reasons", []),
                    )
                )
                lines.append(
                    "  states={state_pair} primary={primary} cost={cost}".format(
                        state_pair=features.get("answer_state_pair", ""),
                        primary=features.get("primary", ""),
                        cost=features.get("cost_band", ""),
                    )
                )
                lines.append(f"  Q: {item.get('question', '')}")
            lines.append("")
    lines.append("## First Exact Misses")
    for item in report.get("examples", {}).get("exact_source_misses", []):
        top = [
            f"{result.get('evidence_ref') or result.get('source_id')}@{result.get('session_id')}"
            for result in item.get("top_results", [])[:3]
        ]
        lines.append(
            f"- {item.get('question_id')}: {item.get('primary')} | expected={item.get('expected_source_refs')} | top={top}"
        )
        lines.append(f"  Q: {item.get('question', '')}")
    lines.extend(["", "## First Gold Anchor Misses"])
    for item in report.get("examples", {}).get("gold_anchor_misses", []):
        top = [
            f"{result.get('evidence_ref') or result.get('source_id')}@{result.get('session_id')}"
            for result in item.get("top_results", [])[:3]
        ]
        lines.append(
            f"- {item.get('question_id')}: {item.get('primary')} | expected_sessions={item.get('expected_session_ids')} | top={top}"
        )
        lines.append(f"  Q: {item.get('question', '')}")
    return "\n".join(lines) + "\n"
