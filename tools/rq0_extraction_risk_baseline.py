#!/usr/bin/env python3
"""Read-only R-Q0 extraction-risk proxy baseline.

The tool computes deterministic extraction markers at a frozen R2 cutoff and
joins only strictly later Delivery/supersession evidence. It never writes the
runtime, calls a model, changes recall, or claims semantic accuracy.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import state_memory_extraction_candidate as candidate_rules  # noqa: E402
from src.raw_evidence_excerpt import (  # noqa: E402
    _append_jsonl_obj_excerpt,
    _extract_content_text,
    _resolve_source_path,
)
from src.raw_recall_explainability import _jsonl_obj_candidate_msg_ids  # noqa: E402
from src.raw_text_decode import iter_decoded_jsonl_lines  # noqa: E402
from src.time_library_delivery_spine import validate_delivery_chain  # noqa: E402
from src.zhixing_library import library_id_for  # noqa: E402
from tools import r2_real_distribution_shadow_audit as r2_audit  # noqa: E402


CONTRACT = "time_library.rq0_extraction_risk_proxy_baseline.v2026.7.16"
REPORT_DECISION_CALIBRATED = "CALIBRATED_RISK_PROXY_BASELINE"
REPORT_DECISION_SPARSE = "SIGNAL_TOO_SPARSE_NOT_CALIBRATED"
QUALITY_STATUS = "not_measured"
PRODUCTION_DECISION = "NO_GO_PRODUCTION_SHADOW"

MIN_LABEL_COVERAGE_RATE = 0.01
MIN_LABELED_RECORDS = 100
MIN_CLASS_RECORDS = 20
MIN_TRAIN_CLASS_RECORDS = 10
MIN_EVAL_CLASS_RECORDS = 5
DEFAULT_PRECISION_K = 20
MAX_RAW_SOURCE_BYTES = 256 * 1024 * 1024
MAX_JSONL_LINE_BYTES = 8 * 1024 * 1024

FEATURE_NAMES = (
    "marker_build_succeeded",
    "span_exactness",
    "source_ref_resolvable",
    "roundtrip_byte_exact",
    "unknown_honesty",
    "overconfidence_rate",
    "atom_redundancy",
    "ambiguity_flag_rate",
    "empty_extraction_on_stateful",
    "log_record_bytes",
    "log_atom_count",
)

TIME_RULE_IDS = (
    "events_remain_orderable",
    "unknown_must_remain_visible",
    "source_refs_required_not_replacement",
    "raw_is_highest_authority",
)

NOISE_LEDGER = (
    "not_selected_is_unlabeled_without_a_proven_exposure_opportunity",
    "not_used_does_not_mean_semantically_wrong",
    "challenge_rejection_is_delivery_verification_noise_not_memory_quality",
    "supersession_without_an_explicit_correction_reason_is_ambiguous_world_change",
    "used_is_host_attested_and_not_independent_model_request_or_response_bytes",
    "proxy_labels_do_not_replace_independent_human_semantic_labels",
)


class RQ0Error(RuntimeError):
    """Stable fail-closed error for R-Q0 input and proof violations."""


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: object) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_time(value: object) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise RQ0Error("timestamp_missing")
    try:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith("Z") else text
        )
    except ValueError as exc:
        raise RQ0Error("timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise RQ0Error("timestamp_timezone_required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _default_runtime_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "time-library"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "time-library"
    return Path.home() / ".local" / "share" / "time-library"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _as_list(value: object) -> List[Any]:
    if value in (None, "", [], {}):
        return []
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def _normalized(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 12)


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 12)


def _record_key(
    cutoff_identity: str, kind: str, line_number: int, record: Mapping[str, Any]
) -> str:
    payload = {
        "cutoff_identity_sha256": cutoff_identity,
        "kind": kind,
        "line_number": line_number,
        "native_id": str(record.get("exp_id") or record.get("memory_id") or ""),
    }
    return "rq0-record-" + sha256_json(payload)[:32]


def _source_ref_id(refs: Sequence[Mapping[str, Any]]) -> str:
    return "rq0-source-" + sha256_json(list(refs))[:32]


def _identity_group_for_record(record: Mapping[str, Any], library_id: str) -> str:
    native_id = str(record.get("exp_id") or record.get("memory_id") or "").strip()
    if native_id:
        identity = {"kind": "native_id", "value": native_id}
    else:
        refs = r2_audit._parse_source_refs(record.get("source_refs"))
        identity = {
            "kind": "source_refs" if refs else "library_id",
            "value": refs if refs else library_id,
        }
    return "rq0-group-" + sha256_json(identity)[:32]


def _stateful_text(text: str) -> bool:
    normalized = candidate_rules._normalized_text(text)
    if candidate_rules._preference_source(normalized):
        return True
    if candidate_rules._unknown_statement(normalized):
        return True
    if candidate_rules._has_update_cue(normalized) or candidate_rules._has_explicit_end(
        normalized
    ):
        return True
    for _start, _end, sentence in candidate_rules._sentence_segments(text):
        semantic, _ambiguities, trace = candidate_rules._semantic_guess(
            candidate_rules._normalized_text(sentence),
            source_is_preference=candidate_rules._preference_source(normalized),
        )
        if semantic != "claim" or trace != ["default_claim_rule"]:
            return True
    return False


def _raw_requests(refs: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    requests: List[Dict[str, Any]] = []
    seen = set()
    for ref in refs:
        source_path = str(ref.get("source_path") or ref.get("ref_path") or "").strip()
        msg_ids = tuple(str(item) for item in _as_list(ref.get("msg_ids")) if str(item))
        resolved = _resolve_source_path(source_path) if source_path else None
        resolved_text = (
            str(resolved) if resolved is not None and resolved.is_file() else ""
        )
        key = (resolved_text, msg_ids)
        if key in seen:
            continue
        seen.add(key)
        requests.append(
            {
                "resolved_path": resolved_text,
                "msg_ids": msg_ids,
                "path_resolved": bool(resolved_text),
            }
        )
    return requests


def _plan_for_record(
    kind: str,
    line_number: int,
    record: Mapping[str, Any],
    *,
    t0: datetime,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str, List[Dict[str, Any]]]:
    refs = r2_audit._parse_source_refs(record.get("source_refs"))
    if not refs:
        raise RQ0Error("source_refs_invalid")
    projection = r2_audit._text_projection(dict(record))
    text = str(projection.get("text") or "")
    if not text:
        raise RQ0Error("source_text_empty")
    recorded_at, _mode = r2_audit._normalized_recorded_at(record.get("extracted_at"))
    if not recorded_at:
        raise RQ0Error("recorded_at_invalid")
    observed_at, _fallback = r2_audit._observed_at(refs, recorded_at)
    if not r2_audit._valid_datetime(observed_at):
        raise RQ0Error("observed_at_invalid")
    if _parse_time(observed_at) > t0:
        raise RQ0Error("source_observed_after_t0")
    plan = candidate_rules.build_hybrid_plan(
        {
            "recorded_at": recorded_at,
            "sources": [
                {
                    "source_ref_id": _source_ref_id(refs),
                    "observed_at": observed_at,
                    "text": text,
                }
            ],
        }
    )
    candidates = [
        item for item in plan.get("candidates") or [] if isinstance(item, dict)
    ]
    return plan, candidates, text, _raw_requests(refs)


def _base_marker_features(
    plan: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]], text: str
) -> Dict[str, float]:
    candidate_count = len(candidates)
    span_exact = sum(
        int(
            r2_audit._projection_span_exact(
                str(plan.get("source_text") or ""), dict(item)
            )
        )
        for item in candidates
    )
    unknown_cues = 0
    unknown_guesses = 0
    default_active_trusted = 0
    ambiguous = 0
    normalized_contents: List[str] = []
    for candidate in candidates:
        content = str(candidate.get("content") or "")
        normalized_contents.append(_normalized(content))
        has_unknown_cue = candidate_rules._unknown_statement(
            candidate_rules._normalized_text(content)
        )
        unknown_cues += int(has_unknown_cue)
        unknown_guesses += int(
            has_unknown_cue and candidate.get("state_role") != "unknown"
        )
        traces = {str(item) for item in candidate.get("rule_trace") or []}
        default_active_trusted += int(
            "default_claim_rule" in traces
            and candidate.get("state_role") == "active"
            and candidate.get("taint") == "trusted"
        )
        ambiguous += int(bool(candidate.get("ambiguities")))
    duplicates = sum(
        count - 1 for count in Counter(normalized_contents).values() if count > 1
    )
    return {
        "marker_build_succeeded": 1.0,
        "span_exactness": _rate(span_exact, candidate_count) or 0.0,
        "source_ref_resolvable": 0.0,
        "roundtrip_byte_exact": 0.0,
        "unknown_honesty": round(1.0 - (unknown_guesses / max(1, unknown_cues)), 12),
        "overconfidence_rate": _rate(default_active_trusted, candidate_count) or 0.0,
        "atom_redundancy": _rate(duplicates, candidate_count) or 0.0,
        "ambiguity_flag_rate": _rate(ambiguous, candidate_count) or 0.0,
        "empty_extraction_on_stateful": float(
            bool(_stateful_text(text) and not candidates)
        ),
        "log_record_bytes": round(math.log1p(len(text.encode("utf-8"))), 12),
        "log_atom_count": round(math.log1p(candidate_count), 12),
    }


def _failed_marker_features(record: Mapping[str, Any]) -> Dict[str, float]:
    projection = r2_audit._text_projection(dict(record))
    text = str(projection.get("text") or "")
    return {
        "marker_build_succeeded": 0.0,
        "span_exactness": 0.0,
        "source_ref_resolvable": 0.0,
        "roundtrip_byte_exact": 0.0,
        "unknown_honesty": 0.0,
        "overconfidence_rate": 0.0,
        "atom_redundancy": 0.0,
        "ambiguity_flag_rate": 0.0,
        "empty_extraction_on_stateful": float(bool(text and _stateful_text(text))),
        "log_record_bytes": round(math.log1p(len(text.encode("utf-8"))), 12),
        "log_atom_count": 0.0,
    }


def _message_texts_for_object(obj: Mapping[str, Any], start: int) -> Dict[str, str]:
    results: Dict[str, str] = {}
    messages = obj.get("messages")
    if isinstance(messages, list):
        for index, message in enumerate(messages):
            msg_id = "msg_%03d" % (index + 1)
            content = (
                message.get("content", "") if isinstance(message, dict) else message
            )
            results[msg_id] = _extract_content_text(content)
        return results

    parts: List[str] = []
    _append_jsonl_obj_excerpt(dict(obj), [], parts)
    if not parts:
        return results
    text = "\n".join(parts)
    for msg_id in _jsonl_obj_candidate_msg_ids(dict(obj), start):
        results[msg_id] = text
    return results


def _load_raw_messages(
    wanted_by_path: Mapping[str, set[str]],
) -> Tuple[Dict[Tuple[str, str], str], Dict[str, int]]:
    found: Dict[Tuple[str, str], str] = {}
    stats = Counter()
    for path_text in sorted(wanted_by_path):
        wanted = set(wanted_by_path[path_text])
        if not path_text or not wanted:
            continue
        path = Path(path_text)
        try:
            size = path.stat().st_size
        except OSError:
            stats["source_stat_error"] += 1
            continue
        if size > MAX_RAW_SOURCE_BYTES:
            stats["source_too_large"] += 1
            continue
        stats["source_files_scanned"] += 1
        try:
            for start, _end, line in iter_decoded_jsonl_lines(path):
                if not wanted:
                    break
                text = line.strip()
                if not text.startswith("{"):
                    continue
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    stats["raw_json_errors"] += 1
                    continue
                if not isinstance(obj, dict):
                    continue
                for msg_id, content in _message_texts_for_object(obj, start).items():
                    if msg_id in wanted:
                        found[(path_text, msg_id)] = content
                        wanted.discard(msg_id)
        except (OSError, UnicodeError):
            stats["source_read_error"] += 1
        stats["message_ids_missing"] += len(wanted)
    stats["message_ids_found"] = len(found)
    return found, dict(sorted(stats.items()))


def collect_marker_rows(
    runtime_root: Path, cutoff: Mapping[str, Any]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    r2_audit.validate_cutoff(dict(cutoff))
    cutoff_identity = str(cutoff.get("cutoff_identity_sha256") or "")
    t0 = _parse_time(cutoff.get("captured_at"))
    pending_rows: List[Dict[str, Any]] = []
    wanted_by_path: Dict[str, set[str]] = defaultdict(set)
    status_counts = Counter()

    for kind, line_number, record, line_error in r2_audit._iter_cutoff_lines(
        runtime_root, dict(cutoff)
    ):
        if line_error or record is None:
            status_counts["line_error"] += 1
            continue
        library_id = library_id_for(dict(record))
        base_row = {
            "record_key": _record_key(cutoff_identity, kind, line_number, record),
            "native_id": str(record.get("exp_id") or record.get("memory_id") or ""),
            "library_id": library_id,
            "identity_group": _identity_group_for_record(record, library_id),
            "kind": kind,
        }
        try:
            plan, candidates, text, requests = _plan_for_record(
                kind, line_number, record, t0=t0
            )
        except Exception as exc:
            status_counts["unprocessable"] += 1
            if isinstance(exc, RQ0Error):
                status_counts[str(exc)] += 1
            pending_rows.append(
                {
                    **base_row,
                    "features": _failed_marker_features(record),
                    "candidate_contents": (),
                    "raw_requests": [],
                }
            )
            continue
        for request in requests:
            path_text = str(request.get("resolved_path") or "")
            for msg_id in request.get("msg_ids") or ():
                if path_text:
                    wanted_by_path[path_text].add(str(msg_id))
        pending_rows.append(
            {
                **base_row,
                "features": _base_marker_features(plan, candidates, text),
                "candidate_contents": tuple(
                    str(item.get("content") or "") for item in candidates
                ),
                "raw_requests": requests,
            }
        )
        status_counts["processed"] += 1

    raw_messages, raw_stats = _load_raw_messages(wanted_by_path)
    for row in pending_rows:
        requests = row.pop("raw_requests")
        candidate_contents = row.pop("candidate_contents")
        resolved_requests = 0
        raw_texts: List[str] = []
        for request in requests:
            path_text = str(request.get("resolved_path") or "")
            msg_ids = tuple(request.get("msg_ids") or ())
            if not path_text or not msg_ids:
                continue
            found_for_request = [
                raw_messages[(path_text, msg_id)]
                for msg_id in msg_ids
                if (path_text, msg_id) in raw_messages
            ]
            if len(found_for_request) == len(msg_ids):
                resolved_requests += 1
            raw_texts.extend(found_for_request)
        row["features"]["source_ref_resolvable"] = (
            _rate(resolved_requests, len(requests)) or 0.0
        )
        raw_text = "\n".join(raw_texts)
        exact_candidates = sum(
            int(bool(content) and content in raw_text) for content in candidate_contents
        )
        row["features"]["roundtrip_byte_exact"] = (
            _rate(exact_candidates, len(candidate_contents)) or 0.0
        )

    return pending_rows, {
        "status_counts": dict(sorted(status_counts.items())),
        "raw_resolution": raw_stats,
    }


def _library_ids_from_refs(refs: object) -> List[str]:
    ids = []
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, Mapping):
            continue
        library_id = str(ref.get("library_id") or "").strip()
        if library_id and library_id not in ids:
            ids.append(library_id)
    return ids


def _delivery_library_ids(event: Mapping[str, Any], *, stage: str) -> List[str]:
    if stage == "used":
        return _library_ids_from_refs(event.get("used_source_refs"))
    return _library_ids_from_refs(event.get("source_refs"))


def read_delivery_evidence(
    db_path: Path, *, t0: datetime, label_cutoff: datetime
) -> Dict[str, Any]:
    if label_cutoff <= t0:
        raise RQ0Error("label_cutoff_must_be_after_t0")
    if not db_path.is_file():
        raise RQ0Error("delivery_db_missing")
    connection = sqlite3.connect(
        db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        rows = connection.execute(
            """
            SELECT rowid, retrieval_id, stage, observed_at, event_json
            FROM delivery_events
            WHERE observed_at <= ?
            ORDER BY rowid
            """,
            (_iso(label_cutoff),),
        ).fetchall()
        security_rows = connection.execute(
            """
            SELECT security.rowid, security.challenge_id, security.platform,
                   security.reason, security.observed_at, challenges.retrieval_id
            FROM delivery_security_events AS security
            LEFT JOIN delivery_challenges AS challenges
              ON challenges.challenge_id = security.challenge_id
            WHERE security.observed_at > ? AND security.observed_at <= ?
            ORDER BY security.rowid
            """,
            (_iso(t0), _iso(label_cutoff)),
        ).fetchall()
    finally:
        connection.close()

    by_library: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    chains: Dict[str, List[Tuple[sqlite3.Row, Dict[str, Any]]]] = defaultdict(list)
    retrieval_used_times: Dict[str, List[datetime]] = defaultdict(list)
    digest_rows: List[Dict[str, Any]] = []
    stage_counts = Counter()
    for row in rows:
        try:
            event = json.loads(str(row["event_json"]))
        except json.JSONDecodeError as exc:
            raise RQ0Error("delivery_event_json_invalid") from exc
        if not isinstance(event, dict):
            raise RQ0Error("delivery_event_not_object")
        stage = str(row["stage"] or "")
        retrieval_id = str(row["retrieval_id"] or "")
        if str(event.get("retrieval_id") or "") != retrieval_id:
            raise RQ0Error("delivery_event_retrieval_column_mismatch")
        if str(event.get("delivery_stage") or "") != stage:
            raise RQ0Error("delivery_event_stage_column_mismatch")
        if _iso(_parse_time(event.get("observed_at"))) != _iso(
            _parse_time(row["observed_at"])
        ):
            raise RQ0Error("delivery_event_observed_at_column_mismatch")
        chains[retrieval_id].append((row, event))

    invalid_chain_count = 0
    excluded_invalid_event_count = 0
    telemetry_present_at_or_before_t0 = False
    for retrieval_id, chain_rows in chains.items():
        events = [event for _row, event in chain_rows]
        validation = validate_delivery_chain(events)
        valid_count = int(validation.get("validated_prefix_event_count") or 0)
        if validation.get("errors"):
            invalid_chain_count += 1
            excluded_invalid_event_count += len(events) - valid_count
        for row, event in chain_rows[:valid_count]:
            observed = _parse_time(row["observed_at"])
            telemetry_present_at_or_before_t0 = (
                telemetry_present_at_or_before_t0 or observed <= t0
            )
            if not (t0 < observed <= label_cutoff):
                continue
            stage = str(row["stage"] or "")
            library_ids = _delivery_library_ids(event, stage=stage)
            stage_counts[stage] += 1
            if stage == "used":
                retrieval_used_times[retrieval_id].append(observed)
            for library_id in library_ids:
                by_library[library_id][stage].append(_iso(observed))
            digest_rows.append(
                {
                    "retrieval_sha256": sha256_bytes(retrieval_id.encode("utf-8")),
                    "stage": stage,
                    "observed_at": _iso(observed),
                    "library_id_sha256": [
                        sha256_bytes(item.encode("utf-8"))
                        for item in sorted(library_ids)
                    ],
                }
            )

    challenge_rejection_count = len(security_rows)
    security_then_used_count = 0
    unmatched_challenge_count = 0
    security_digest_rows: List[Dict[str, Any]] = []
    for row in security_rows:
        challenge_id = str(row["challenge_id"] or "")
        if not challenge_id:
            unmatched_challenge_count += 1
            continue
        observed = _parse_time(row["observed_at"])
        retrieval_id = str(row["retrieval_id"] or "")
        if not retrieval_id:
            unmatched_challenge_count += 1
        else:
            security_then_used_count += int(
                any(
                    used_at > observed
                    for used_at in retrieval_used_times.get(retrieval_id, [])
                )
            )
        security_digest_rows.append(
            {
                "challenge_sha256": sha256_bytes(challenge_id.encode("utf-8")),
                "retrieval_sha256": sha256_bytes(retrieval_id.encode("utf-8")),
                "reason": str(row["reason"] or ""),
                "observed_at": _iso(observed),
            }
        )

    return {
        "quick_check": str(quick_check),
        "query_only": True,
        "by_library": {key: dict(value) for key, value in by_library.items()},
        "event_count_in_label_window": sum(stage_counts.values()),
        "stage_counts": dict(sorted(stage_counts.items())),
        "distinct_library_ids": len(by_library),
        "telemetry_present_at_or_before_t0": telemetry_present_at_or_before_t0,
        "validated_retrieval_chain_count": len(chains) - invalid_chain_count,
        "invalid_retrieval_chain_count": invalid_chain_count,
        "invalid_chain_event_count_excluded": excluded_invalid_event_count,
        "challenge_rejection_count": challenge_rejection_count,
        "challenge_rejection_labeled_bad_count": 0,
        "challenge_rejection_then_same_retrieval_used_count": security_then_used_count,
        "challenge_rejection_unmatched_challenge_count": unmatched_challenge_count,
        "sanitized_evidence_sha256": sha256_json(
            {
                "delivery": digest_rows,
                "security": security_digest_rows,
            }
        ),
    }


def _tail_targets(record: Mapping[str, Any]) -> Tuple[List[str], List[str]]:
    corrective: List[str] = []
    ambiguous: List[str] = []
    for key in ("correction_of", "corrects", "errata_for"):
        corrective.extend(str(item) for item in _as_list(record.get(key)) if str(item))
    for key in ("supersedes", "superseded_by", "conflicts_with"):
        ambiguous.extend(str(item) for item in _as_list(record.get(key)) if str(item))
    return sorted(set(corrective)), sorted(set(ambiguous))


def read_post_cutoff_relations(
    runtime_root: Path,
    cutoff: Mapping[str, Any],
    *,
    t0: datetime,
    label_cutoff: datetime,
) -> Dict[str, Any]:
    corrective_targets: List[Tuple[str, str]] = []
    ambiguous_targets: List[Tuple[str, str]] = []
    tail_records = 0
    backfilled_old_fact_records = 0
    relation_time_unusable_records = 0
    for item in cutoff.get("files") or []:
        kind = str(item.get("kind") or "")
        relative = r2_audit.RECORD_PATHS.get(kind)
        if relative is None:
            continue
        path = runtime_root / relative
        if not path.is_file():
            continue
        start = int(item.get("cutoff_bytes") or 0)
        snapshot_size = path.stat().st_size
        if snapshot_size <= start:
            continue
        with path.open("rb") as handle:
            handle.seek(start)
            while handle.tell() < snapshot_size:
                remaining = snapshot_size - handle.tell()
                raw = handle.readline(min(remaining, MAX_JSONL_LINE_BYTES + 1))
                if not raw:
                    break
                if len(raw) > MAX_JSONL_LINE_BYTES or not raw.endswith(b"\n"):
                    raise RQ0Error("post_cutoff_line_invalid")
                try:
                    record = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict):
                    continue
                recorded_text, _mode = r2_audit._normalized_recorded_at(
                    record.get("extracted_at")
                )
                if not recorded_text:
                    relation_time_unusable_records += 1
                    continue
                recorded = _parse_time(recorded_text)
                if not (t0 < recorded <= label_cutoff):
                    continue
                refs = r2_audit._parse_source_refs(record.get("source_refs"))
                if not refs:
                    relation_time_unusable_records += 1
                    continue
                source_observed_text, _fallback = r2_audit._observed_at(
                    refs, recorded_text
                )
                if not r2_audit._valid_datetime(source_observed_text):
                    relation_time_unusable_records += 1
                    continue
                source_observed = _parse_time(source_observed_text)
                if source_observed <= t0:
                    backfilled_old_fact_records += 1
                    continue
                tail_records += 1
                corrective, ambiguous = _tail_targets(record)
                for target in corrective:
                    corrective_targets.append((target, _iso(recorded)))
                for target in ambiguous:
                    ambiguous_targets.append((target, _iso(recorded)))
    digest_payload = {
        "corrective": [
            (sha256_bytes(target.encode("utf-8")), time)
            for target, time in corrective_targets
        ],
        "ambiguous": [
            (sha256_bytes(target.encode("utf-8")), time)
            for target, time in ambiguous_targets
        ],
    }
    return {
        "tail_records_observed": tail_records,
        "backfilled_old_fact_records_excluded": backfilled_old_fact_records,
        "relation_time_unusable_records_excluded": relation_time_unusable_records,
        "corrective_targets": corrective_targets,
        "ambiguous_targets": ambiguous_targets,
        "corrective_target_count": len(corrective_targets),
        "ambiguous_target_count": len(ambiguous_targets),
        "sanitized_relations_sha256": sha256_json(digest_payload),
    }


def build_natural_labels(
    marker_rows: Sequence[Mapping[str, Any]],
    delivery: Mapping[str, Any],
    relations: Mapping[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    by_library: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    by_native: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    by_group: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in marker_rows:
        library_id = str(row.get("library_id") or "")
        native_id = str(row.get("native_id") or "")
        identity_group = str(row.get("identity_group") or "")
        if library_id:
            by_library[library_id].append(row)
        if native_id:
            by_native[native_id].append(row)
        if identity_group:
            by_group[identity_group].append(row)

    corrective: Dict[str, List[str]] = defaultdict(list)
    for target, observed_at in relations.get("corrective_targets") or []:
        corrective[str(target)].append(str(observed_at))

    evidence_by_record: Dict[str, Dict[str, Any]] = {}
    record_rows: Dict[str, Mapping[str, Any]] = {
        str(row["record_key"]): row for row in marker_rows
    }
    ambiguous_conflicting_proxy = 0
    mapping_collision_targets = 0
    duplicate_identity_group_targets = 0
    unmatched_delivery = 0
    for library_id, stages in (delivery.get("by_library") or {}).items():
        matched = by_library.get(str(library_id), [])
        if not matched:
            unmatched_delivery += 1
            continue
        if len(matched) != 1:
            mapping_collision_targets += 1
            continue
        row = matched[0]
        if len(by_group.get(str(row.get("identity_group") or ""), [])) != 1:
            duplicate_identity_group_targets += 1
            continue
        good_times = sorted(
            set(list(stages.get("selected") or []) + list(stages.get("used") or []))
        )
        if not good_times:
            continue
        record_key = str(row["record_key"])
        evidence_by_record.setdefault(record_key, {"good": [], "bad": []})[
            "good"
        ].extend(good_times)

    unmatched_correction = 0
    for target, times in corrective.items():
        matched_by_key: Dict[str, Mapping[str, Any]] = {}
        for row in by_library.get(target, []) + by_native.get(target, []):
            matched_by_key[str(row["record_key"])] = row
        matched = list(matched_by_key.values())
        if not matched:
            unmatched_correction += 1
            continue
        if len(matched) != 1:
            mapping_collision_targets += 1
            continue
        row = matched[0]
        if len(by_group.get(str(row.get("identity_group") or ""), [])) != 1:
            duplicate_identity_group_targets += 1
            continue
        record_key = str(row["record_key"])
        evidence_by_record.setdefault(record_key, {"good": [], "bad": []})[
            "bad"
        ].extend(times)

    labels: List[Dict[str, Any]] = []
    good_count = 0
    bad_count = 0
    for record_key, evidence in evidence_by_record.items():
        good_times = sorted(set(evidence["good"]))
        bad_times = sorted(set(evidence["bad"]))
        if good_times and bad_times:
            ambiguous_conflicting_proxy += 1
            continue
        row = record_rows[record_key]
        if good_times:
            labels.append(
                {
                    "record_key": record_key,
                    "identity_group": row["identity_group"],
                    "label": 0,
                    "label_observed_at": good_times[0],
                    "label_source": "delivery_selected_or_used_host_attested_proxy",
                    "features": dict(row["features"]),
                }
            )
            good_count += 1
        elif bad_times:
            labels.append(
                {
                    "record_key": record_key,
                    "identity_group": row["identity_group"],
                    "label": 1,
                    "label_observed_at": bad_times[0],
                    "label_source": "explicit_structured_correction_proxy",
                    "features": dict(row["features"]),
                }
            )
            bad_count += 1

    labels.sort(key=lambda item: (item["label_observed_at"], item["record_key"]))
    return labels, {
        "good_proxy_count": good_count,
        "bad_proxy_count": bad_count,
        "ambiguous_conflicting_proxy_count": ambiguous_conflicting_proxy,
        "ambiguous_lifecycle_relation_count": len(
            relations.get("ambiguous_targets") or []
        ),
        "mapping_collision_target_count": mapping_collision_targets,
        "duplicate_identity_group_target_count": duplicate_identity_group_targets,
        "unmatched_delivery_library_id_count": unmatched_delivery,
        "unmatched_correction_target_count": unmatched_correction,
        "unselected_records_labeled_bad": 0,
        "challenge_rejections_labeled_bad": 0,
        "effective_independent_labeled_record_count": len(labels),
    }


def _feature_vector(row: Mapping[str, Any]) -> List[float]:
    features = row.get("features") or {}
    return [float(features.get(name) or 0.0) for name in FEATURE_NAMES]


def _standardize_fit(
    rows: Sequence[Mapping[str, Any]],
) -> Tuple[List[float], List[float]]:
    vectors = [_feature_vector(row) for row in rows]
    means = [
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(len(FEATURE_NAMES))
    ]
    scales = []
    for index, mean in enumerate(means):
        variance = sum((vector[index] - mean) ** 2 for vector in vectors) / len(vectors)
        scales.append(math.sqrt(variance) or 1.0)
    return means, scales


def _standardized_vector(
    row: Mapping[str, Any], means: Sequence[float], scales: Sequence[float]
) -> List[float]:
    raw = _feature_vector(row)
    return [1.0] + [
        (value - means[index]) / scales[index] for index, value in enumerate(raw)
    ]


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp = math.exp(-value)
        return 1.0 / (1.0 + exp)
    exp = math.exp(value)
    return exp / (1.0 + exp)


def fit_l2_logistic(
    rows: Sequence[Mapping[str, Any]],
    *,
    l2: float = 1.0,
    learning_rate: float = 0.08,
    max_iterations: int = 600,
) -> Dict[str, Any]:
    if not rows:
        raise RQ0Error("logistic_rows_required")
    means, scales = _standardize_fit(rows)
    matrix = [_standardized_vector(row, means, scales) for row in rows]
    labels = [int(row["label"]) for row in rows]
    weights = [0.0] * (len(FEATURE_NAMES) + 1)
    iterations = 0
    for iteration in range(max_iterations):
        gradients = [0.0] * len(weights)
        for vector, label in zip(matrix, labels):
            prediction = _sigmoid(
                sum(weight * value for weight, value in zip(weights, vector))
            )
            error = prediction - label
            for index, value in enumerate(vector):
                gradients[index] += error * value
        for index in range(len(gradients)):
            gradients[index] /= len(rows)
            if index:
                gradients[index] += l2 * weights[index] / len(rows)
        delta = [learning_rate * gradient for gradient in gradients]
        weights = [weight - change for weight, change in zip(weights, delta)]
        iterations = iteration + 1
        if max(abs(change) for change in delta) < 1e-12:
            break
    return {
        "feature_names": list(FEATURE_NAMES),
        "means": [round(value, 15) for value in means],
        "scales": [round(value, 15) for value in scales],
        "weights": [round(value, 15) for value in weights],
        "l2": l2,
        "learning_rate": learning_rate,
        "iterations": iterations,
    }


def score_with_model(row: Mapping[str, Any], model: Mapping[str, Any]) -> float:
    vector = _standardized_vector(row, model["means"], model["scales"])
    value = sum(
        float(weight) * feature for weight, feature in zip(model["weights"], vector)
    )
    return round(_sigmoid(value), 15)


def roc_auc(labels: Sequence[int], scores: Sequence[float]) -> Optional[float]:
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    ordered = sorted(enumerate(scores), key=lambda item: item[1])
    ranks = [0.0] * len(scores)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        average_rank = (cursor + 1 + end) / 2.0
        for index in range(cursor, end):
            ranks[ordered[index][0]] = average_rank
        cursor = end
    positive_rank_sum = sum(rank for rank, label in zip(ranks, labels) if label == 1)
    auc = (positive_rank_sum - positives * (positives + 1) / 2.0) / (
        positives * negatives
    )
    return round(auc, 12)


def precision_at_k(
    labels: Sequence[int], scores: Sequence[float], k: int
) -> Optional[float]:
    if not labels:
        return None
    limit = min(max(1, k), len(labels))
    selected = sorted(range(len(scores)), key=lambda index: (-scores[index], index))[
        :limit
    ]
    return round(sum(labels[index] for index in selected) / limit, 12)


def _rank(values: Sequence[float]) -> List[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        average = (cursor + 1 + end) / 2.0
        for index in range(cursor, end):
            ranks[ordered[index][0]] = average
        cursor = end
    return ranks


def _solve_linear(matrix: List[List[float]], vector: List[float]) -> List[float]:
    size = len(vector)
    augmented = [list(matrix[row]) + [vector[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return [0.0] * size
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                current - factor * base
                for current, base in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(size)]


def _residualize(
    values: Sequence[float], controls: Sequence[Sequence[float]]
) -> List[float]:
    design = [
        [1.0] + [float(control[index]) for control in controls]
        for index in range(len(values))
    ]
    width = len(design[0])
    xtx = [[0.0] * width for _ in range(width)]
    xty = [0.0] * width
    for row, target in zip(design, values):
        for left in range(width):
            xty[left] += row[left] * target
            for right in range(width):
                xtx[left][right] += row[left] * row[right]
    coefficients = _solve_linear(xtx, xty)
    return [
        target
        - sum(coefficient * value for coefficient, value in zip(coefficients, row))
        for target, row in zip(values, design)
    ]


def _pearson(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_scale = math.sqrt(sum((a - left_mean) ** 2 for a in left))
    right_scale = math.sqrt(sum((b - right_mean) ** 2 for b in right))
    if left_scale == 0 or right_scale == 0:
        return None
    return round(numerator / (left_scale * right_scale), 12)


def partial_spearman(
    labels: Sequence[int],
    scores: Sequence[float],
    size_controls: Sequence[Sequence[float]],
) -> Optional[float]:
    if len(labels) < 3:
        return None
    ranked_labels = _rank([float(value) for value in labels])
    ranked_scores = _rank(scores)
    ranked_controls = [_rank(control) for control in size_controls]
    return _pearson(
        _residualize(ranked_labels, ranked_controls),
        _residualize(ranked_scores, ranked_controls),
    )


def _temporal_split(
    labels: Sequence[Mapping[str, Any]],
) -> Optional[Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]]:
    ordered = sorted(
        labels, key=lambda item: (item["label_observed_at"], item["record_key"])
    )
    for fraction in (0.70, 0.65, 0.75, 0.60, 0.80):
        split = max(1, min(len(ordered) - 1, int(len(ordered) * fraction)))
        train = ordered[:split]
        evaluation = ordered[split:]
        train_counts = Counter(int(item["label"]) for item in train)
        eval_counts = Counter(int(item["label"]) for item in evaluation)
        if (
            min(train_counts.get(0, 0), train_counts.get(1, 0))
            >= MIN_TRAIN_CLASS_RECORDS
            and min(eval_counts.get(0, 0), eval_counts.get(1, 0))
            >= MIN_EVAL_CLASS_RECORDS
            and train[-1]["label_observed_at"] <= evaluation[0]["label_observed_at"]
        ):
            return list(train), list(evaluation)
    return None


def evaluate_proxy(
    marker_rows: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
    *,
    precision_k: int = DEFAULT_PRECISION_K,
) -> Dict[str, Any]:
    total = len(marker_rows)
    labeled = len(labels)
    class_counts = Counter(int(item["label"]) for item in labels)
    coverage = labeled / total if total else 0.0
    sparse_reasons = []
    if coverage < MIN_LABEL_COVERAGE_RATE:
        sparse_reasons.append("label_coverage_below_minimum")
    if labeled < MIN_LABELED_RECORDS:
        sparse_reasons.append("labeled_record_count_below_minimum")
    if min(class_counts.get(0, 0), class_counts.get(1, 0)) < MIN_CLASS_RECORDS:
        sparse_reasons.append("class_support_below_minimum")
    split = _temporal_split(labels) if not sparse_reasons else None
    if not sparse_reasons and split is None:
        sparse_reasons.append("temporal_split_class_support_insufficient")

    if sparse_reasons:
        return {
            "decision": REPORT_DECISION_SPARSE,
            "sparse_reasons": sparse_reasons,
            "model_fitted": False,
            "roc_auc": None,
            "precision_at_k": None,
            "partial_spearman_controlling_size": None,
            "learned_constants": None,
        }

    assert split is not None
    train, evaluation = split
    model = fit_l2_logistic(train)
    scores = [score_with_model(row, model) for row in evaluation]
    eval_labels = [int(row["label"]) for row in evaluation]
    controls = [
        [
            float((row.get("features") or {}).get("log_record_bytes") or 0.0)
            for row in evaluation
        ],
        [
            float((row.get("features") or {}).get("log_atom_count") or 0.0)
            for row in evaluation
        ],
    ]
    return {
        "decision": REPORT_DECISION_CALIBRATED,
        "sparse_reasons": [],
        "model_fitted": True,
        "roc_auc": roc_auc(eval_labels, scores),
        "precision_at_k": {
            "k": min(precision_k, len(evaluation)),
            "value": precision_at_k(eval_labels, scores, precision_k),
        },
        "partial_spearman_controlling_size": partial_spearman(
            eval_labels, scores, controls
        ),
        "train": {
            "count": len(train),
            "class_counts": dict(
                sorted(Counter(int(row["label"]) for row in train).items())
            ),
            "label_time_max": train[-1]["label_observed_at"],
        },
        "evaluation": {
            "count": len(evaluation),
            "class_counts": dict(sorted(Counter(eval_labels).items())),
            "label_time_min": evaluation[0]["label_observed_at"],
            "scores_sha256": sha256_json(scores),
        },
        "learned_constants": model,
    }


def _feature_summary(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    summary = {}
    for name in FEATURE_NAMES:
        values = [float((row.get("features") or {}).get(name) or 0.0) for row in rows]
        summary[name] = {
            "mean": _mean(values),
            "min": round(min(values), 12) if values else None,
            "max": round(max(values), 12) if values else None,
            "nonzero_count": sum(value != 0.0 for value in values),
        }
    return summary


def build_report(
    *,
    runtime_root: Path,
    cutoff_path: Path,
    prereg_path: Path,
    delivery_db: Path,
    label_cutoff: datetime,
) -> Dict[str, Any]:
    cutoff = json.loads(cutoff_path.read_text(encoding="utf-8"))
    r2_audit.validate_cutoff(cutoff)
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    current_extractor_sha256 = file_sha256(Path(candidate_rules.__file__))
    if prereg.get("rules_frozen") is not True:
        raise RQ0Error("preregistered_extractor_rules_not_frozen")
    if str(prereg.get("cutoff_file_sha256") or "") != file_sha256(cutoff_path):
        raise RQ0Error("preregistered_cutoff_file_sha256_mismatch")
    if str(prereg.get("cutoff_identity_sha256") or "") != str(
        cutoff.get("cutoff_identity_sha256") or ""
    ):
        raise RQ0Error("preregistered_cutoff_identity_mismatch")
    if str(prereg.get("extractor_sha256") or "") != current_extractor_sha256:
        raise RQ0Error("frozen_extractor_sha256_mismatch")
    t0 = _parse_time(cutoff["captured_at"])
    if label_cutoff <= t0:
        raise RQ0Error("label_cutoff_must_be_after_t0")

    marker_rows, marker_diagnostics = collect_marker_rows(runtime_root, cutoff)
    cutoff_record_count = sum(
        int(item.get("newline_count") or 0) for item in cutoff["files"]
    )
    if len(marker_rows) != cutoff_record_count:
        raise RQ0Error("marker_population_incomplete")
    delivery = read_delivery_evidence(delivery_db, t0=t0, label_cutoff=label_cutoff)
    relations = read_post_cutoff_relations(
        runtime_root,
        cutoff,
        t0=t0,
        label_cutoff=label_cutoff,
    )
    labels, label_diagnostics = build_natural_labels(marker_rows, delivery, relations)
    evaluation = evaluate_proxy(marker_rows, labels)

    marker_matrix = [
        {
            "record_key": row["record_key"],
            "features": {name: row["features"][name] for name in FEATURE_NAMES},
        }
        for row in sorted(marker_rows, key=lambda item: item["record_key"])
    ]
    label_vector = [
        {
            "record_key": row["record_key"],
            "label": row["label"],
            "label_observed_at": row["label_observed_at"],
            "label_source": row["label_source"],
        }
        for row in labels
    ]
    class_counts = Counter(int(item["label"]) for item in labels)
    report: Dict[str, Any] = {
        "contract": CONTRACT,
        "decision": evaluation["decision"],
        "proof_layer": "frozen_real_distribution_read_only_proxy_measurement",
        "score_is_risk_proxy_not_semantic_accuracy": True,
        "proxy_granularity": "record",
        "candidate_semantic_accuracy": "not_measured",
        "production_unlock": False,
        "quality_status": QUALITY_STATUS,
        "production_decision": PRODUCTION_DECISION,
        "read_only": True,
        "runtime_write_performed": False,
        "global_zero_write_proven": False,
        "model_call_performed": False,
        "product_hot_path_modified": False,
        "t0": _iso(t0),
        "label_cutoff": _iso(label_cutoff),
        "label_window": "(T0,label_cutoff]",
        "strict_future_only": True,
        "feature_builder_reads_label_fields": False,
        "input_identity": {
            "cutoff_file_sha256": file_sha256(cutoff_path),
            "cutoff_identity_sha256": cutoff["cutoff_identity_sha256"],
            "cutoff_record_count": cutoff_record_count,
            "preregistration_file_sha256": file_sha256(prereg_path),
            "preregistered_source_commit": prereg.get("source_commit"),
            "extractor_contract": prereg.get("extractor_contract"),
            "extractor_sha256": current_extractor_sha256,
            "extractor_rules_frozen": True,
            "rq0_tool_sha256": file_sha256(Path(__file__)),
            "r2_audit_tool_sha256": file_sha256(Path(r2_audit.__file__)),
            "delivery_chain_validator_sha256": file_sha256(
                Path(sys.modules[validate_delivery_chain.__module__].__file__)
            ),
            "delivery_sanitized_evidence_sha256": delivery["sanitized_evidence_sha256"],
            "post_cutoff_relations_sha256": relations["sanitized_relations_sha256"],
        },
        "markers": {
            "definitions": {
                "marker_build_succeeded": "the frozen extractor produced a deterministic plan for this record",
                "span_exactness": "candidate source span is byte-exact within the frozen record projection",
                "source_ref_resolvable": "declared raw path resolves and every declared msg_id is found",
                "roundtrip_byte_exact": "candidate content occurs byte-exactly in resolved referenced raw text",
                "unknown_honesty": "unknown-cue candidates remain unknown instead of being guessed",
                "overconfidence_rate": "default-claim active trusted candidates divided by atom count",
                "atom_redundancy": "duplicate normalized candidate contents divided by atom count",
                "ambiguity_flag_rate": "candidates with explicit ambiguity fields divided by atom count",
                "empty_extraction_on_stateful": "stateful-looking record produced zero candidates",
                "log_record_bytes": "log1p UTF-8 bytes control",
                "log_atom_count": "log1p atom count control",
            },
            "record_count": len(marker_rows),
            "frozen_population_coverage_rate": _rate(
                len(marker_rows), cutoff_record_count
            ),
            "matrix_sha256": sha256_json(marker_matrix),
            "summary": _feature_summary(marker_rows),
            "diagnostics": marker_diagnostics,
            "canonical_raw_roundtrip_boundary": (
                "raw matching is exact substring evidence for the referenced messages; "
                "it is not an authored semantic ground truth label"
            ),
        },
        "natural_labels": {
            "definition": {
                "risk_0": "strictly later host-attested selected or used evidence for a uniquely mapped frozen record",
                "risk_1": "strictly later explicit structured correction targeting the frozen record",
                "unlabeled": "no explicit downstream evidence or only ambiguous delivery/lifecycle evidence",
            },
            "dispatch_conflict_resolution": (
                "the dispatch shorthand called never-selected/challenge-rejected records poor candidates, "
                "but its honesty boundary says non-use is not semantic error; the stricter honesty boundary governs"
            ),
            "eligible_negative_supported": False,
            "record_level_proxy_only": True,
            "candidate_level_semantic_accuracy": "not_measured",
            "labeled_record_count": len(labels),
            "unlabeled_record_count": len(marker_rows) - len(labels),
            "coverage_rate": _rate(len(labels), len(marker_rows)),
            "raw_frozen_population_coverage_rate": _rate(
                len(labels), cutoff_record_count
            ),
            "class_counts": {
                "risk_0_good_proxy": class_counts.get(0, 0),
                "risk_1_bad_proxy": class_counts.get(1, 0),
            },
            "label_vector_sha256": sha256_json(label_vector),
            "delivery": {
                key: value for key, value in delivery.items() if key != "by_library"
            },
            "post_cutoff_relations": {
                key: value
                for key, value in relations.items()
                if key not in {"corrective_targets", "ambiguous_targets"}
            },
            "diagnostics": label_diagnostics,
            "noise_ledger": list(NOISE_LEDGER),
        },
        "calibration_thresholds": {
            "minimum_label_coverage_rate": MIN_LABEL_COVERAGE_RATE,
            "minimum_labeled_records": MIN_LABELED_RECORDS,
            "minimum_records_per_class": MIN_CLASS_RECORDS,
            "minimum_train_records_per_class": MIN_TRAIN_CLASS_RECORDS,
            "minimum_evaluation_records_per_class": MIN_EVAL_CLASS_RECORDS,
        },
        "evaluation": evaluation,
        "gate_b_no_future_leakage": {
            "marker_time": _iso(t0),
            "marker_source_refs_not_after_t0": True,
            "labels_strictly_after_marker_time": all(
                _parse_time(item["label_observed_at"]) > t0 for item in labels
            ),
            "evaluation_labels_not_model_inputs": True,
            "future_label_mutation_score_invariance": True,
            "proof_anchor": (
                "tests/test_rq0_extraction_risk_baseline.py::"
                "test_future_evaluation_label_mutation_keeps_markers_model_and_scores_fixed"
            ),
        },
        "non_claims": [
            "risk proxy is not semantic accuracy",
            "AUC, when present, predicts the natural proxy rather than truth",
            "selected and used evidence is host-attested rather than independent request/response bytes",
            "record-level adoption cannot establish candidate-level semantic correctness",
            "unselected and unused records are not automatically negative labels",
            "challenge mismatch is not memory-quality evidence",
            "human blind labels remain required for semantic calibration",
            "R2 quality remains not_measured and production shadow remains NO_GO",
            "no product runtime, recall, delivery, gateway, installed, push, release, LAN, or cross-machine proof",
            "the generated report is a local-only 0600 measurement artifact, not a release artifact",
            "global zero-write is not claimed while independent watchers may append production sources",
            "external raw source immutability since T0 is not proven without historical raw-prefix hashes",
        ],
        "time_rule_decision": {
            "decision": "attached",
            "rule_ids": list(TIME_RULE_IDS),
        },
    }
    payload = dict(report)
    report["canonical_payload_sha256"] = sha256_json(payload)
    return report


def write_report(path: Path, report: Mapping[str, Any], *, runtime_root: Path) -> None:
    path = Path(path)
    if _is_within(path, runtime_root):
        raise RQ0Error("report_output_must_not_be_inside_runtime_root")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (canonical_json(report) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only R-Q0 extraction-risk proxy baseline"
    )
    parser.add_argument("--runtime-root", type=Path, default=_default_runtime_root())
    parser.add_argument("--cutoff-input", type=Path, required=True)
    parser.add_argument("--prereg-input", type=Path, required=True)
    parser.add_argument("--delivery-db", type=Path)
    parser.add_argument("--label-cutoff", required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()

    runtime_root = args.runtime_root.expanduser().resolve()
    cutoff_path = args.cutoff_input.expanduser().resolve()
    prereg_path = args.prereg_input.expanduser().resolve()
    delivery_db = (
        args.delivery_db.expanduser().resolve()
        if args.delivery_db
        else runtime_root / "runtime" / "delivery-events.sqlite3"
    )
    report = build_report(
        runtime_root=runtime_root,
        cutoff_path=cutoff_path,
        prereg_path=prereg_path,
        delivery_db=delivery_db,
        label_cutoff=_parse_time(args.label_cutoff),
    )
    write_report(args.report_output, report, runtime_root=runtime_root)
    print(
        canonical_json(
            {
                "ok": True,
                "decision": report["decision"],
                "score_is_risk_proxy_not_semantic_accuracy": True,
                "quality_status": QUALITY_STATUS,
                "production_decision": PRODUCTION_DECISION,
                "labeled_record_count": report["natural_labels"][
                    "labeled_record_count"
                ],
                "coverage_rate": report["natural_labels"]["coverage_rate"],
                "canonical_payload_sha256": report["canonical_payload_sha256"],
                "report_file_sha256": file_sha256(args.report_output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
