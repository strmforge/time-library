#!/usr/bin/env python3
"""Read-only R-Q1 card-adoption proxy baseline.

R-Q1 measures deterministic properties of file-backed library cards against
strictly later Delivery Spine adoption evidence.  It does not measure raw/state
extraction accuracy, call a model, or write any production store.
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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.time_library_delivery_spine import validate_delivery_chain  # noqa: E402
from src.zhixing_library import (  # noqa: E402
    library_card_for,
    library_id_for,
    load_file_backed_library_candidate_records,
)
from tools import rq0_extraction_risk_baseline as rq0  # noqa: E402


CONTRACT = "time_library.rq1_card_adoption_proxy_baseline.v2026.7.16"
SNAPSHOT_CONTRACT = "time_library.rq1_card_marker_snapshot.v2026.7.16"
DECISION_CALIBRATED = "CARD_ADOPTION_PROXY_CALIBRATED"
DECISION_SPARSE = "SIGNAL_SPARSE_BUT_JOINABLE"
DECISION_JOIN_NOT_PROVEN = "CARD_LAYER_JOIN_NOT_PROVEN"
QUALITY_STATUS = "not_measured"
PRODUCTION_DECISION = "NO_GO_PRODUCTION_SHADOW"

MIN_LABEL_COVERAGE_RATE = 0.10
MIN_LABELED_CARDS = 30
MIN_CLASS_CARDS = 10
MIN_TRAIN_CLASS_CARDS = 5
MIN_EVAL_CLASS_CARDS = 3
DEFAULT_PRECISION_K = 10
MAX_SUPPORT_FILE_BYTES = 64 * 1024 * 1024
MAX_OFFSET_READ_BYTES = 1024 * 1024

FEATURE_NAMES = (
    "provenance_roundtrip_exact",
    "verbatim_present",
    "verbatim_not_distill_masquerade",
    "distill_provenance_bound",
    "source_ref_count",
    "source_system_diversity",
    "shelf_zhiyi",
    "shelf_xingce",
    "shelf_toolbook",
    "shelf_errata",
    "staleness_known",
    "log_staleness_seconds",
    "log_card_age_seconds",
    "log_card_bytes",
)

TIME_RULE_IDS = (
    "events_remain_orderable",
    "unknown_must_remain_visible",
    "source_refs_required_not_replacement",
    "raw_is_highest_authority",
)

NOISE_LEDGER = (
    "challenge_mismatch_is_delivery_verification_noise_not_card_quality",
    "silent_requested_is_not_a_bad_card_label",
    "lifecycle_superseded_silence_is_not_a_bad_card_label",
    "retrieved_without_emit_is_not_a_proven_selection_opportunity",
    "unused_is_not_unhelpful_and_used_is_not_helped",
    "used_is_host_attested_not_independent_model_bytes_and_selected_is_policy_state_only",
    "raw_extraction_quality_remains_unmeasured_upstream",
)


class RQ1Error(RuntimeError):
    """Stable fail-closed error for R-Q1 input and proof violations."""


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
        raise RQ1Error("timestamp_missing")
    try:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith("Z") else text
        )
    except ValueError as exc:
        raise RQ1Error("timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise RQ1Error("timestamp_timezone_required")
    return parsed.astimezone(timezone.utc)


def _try_time(value: object) -> Optional[datetime]:
    try:
        return _parse_time(value)
    except RQ1Error:
        return None


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


def _rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 12)


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 12)


def _items(value: object) -> List[Any]:
    if value in (None, "", [], {}):
        return []
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def _normalized_ref(value: Mapping[str, Any]) -> Dict[str, Any]:
    ref = dict(value)
    if ref.get("message_id") and not ref.get("msg_ids"):
        ref["msg_ids"] = [str(ref["message_id"])]
    return ref


def _iter_nested_refs(record: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    primary = record.get("source_refs") or record.get("_source_refs")
    if isinstance(primary, Mapping):
        yield primary
    elif isinstance(primary, list):
        for item in primary:
            if isinstance(item, Mapping):
                yield item
    for field in ("merged_source_refs", "evidence_refs"):
        for item in _items(record.get(field)):
            if not isinstance(item, Mapping):
                continue
            nested = item.get("source_ref")
            yield nested if isinstance(nested, Mapping) else item


def _source_refs(record: Mapping[str, Any]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen = set()
    for value in _iter_nested_refs(record):
        ref = _normalized_ref(value)
        identity = canonical_json(
            {
                "source_system": ref.get("source_system") or "",
                "source_path": ref.get("source_path") or ref.get("ref_path") or "",
                "msg_ids": sorted(str(item) for item in _items(ref.get("msg_ids"))),
                "byte_offsets": ref.get("byte_offsets") or ref.get("source_byte_offsets") or {},
            }
        )
        if identity in seen:
            continue
        seen.add(identity)
        refs.append(ref)
    return refs


def _support_paths(record: Mapping[str, Any], runtime_root: Path) -> List[Path]:
    refs = record.get("source_refs") if isinstance(record.get("source_refs"), Mapping) else {}
    values = [refs.get("candidate_path"), refs.get("action_path")]
    paths: List[Path] = []
    for value in values:
        if not str(value or "").strip():
            continue
        path = Path(str(value)).expanduser().resolve()
        if not _is_within(path, runtime_root):
            raise RQ1Error("card_support_path_outside_runtime_root")
        if not path.is_file():
            raise RQ1Error("card_support_file_missing")
        if path.stat().st_size > MAX_SUPPORT_FILE_BYTES:
            raise RQ1Error("card_support_file_too_large")
        if path not in paths:
            paths.append(path)
    if not paths:
        raise RQ1Error("card_support_file_missing")
    return sorted(paths)


def _record_time_candidates(record: Mapping[str, Any]) -> List[datetime]:
    values = []
    for key in (
        "created_at",
        "updated_at",
        "last_verified_at",
        "captured_at",
        "extracted_at",
    ):
        parsed = _try_time(record.get(key))
        if parsed is not None:
            values.append(parsed)
    return values


def _ref_observed_times(refs: Sequence[Mapping[str, Any]]) -> List[datetime]:
    values = []
    for ref in refs:
        for key in ("captured_at", "observed_at", "timestamp"):
            parsed = _try_time(ref.get(key))
            if parsed is not None:
                values.append(parsed)
    return values


def _ref_last_commit_times(refs: Sequence[Mapping[str, Any]]) -> List[datetime]:
    values = []
    for ref in refs:
        for key in ("source_last_commit_at", "last_commit_at", "source_updated_at"):
            parsed = _try_time(ref.get(key))
            if parsed is not None:
                values.append(parsed)
    return values


def _offset_text(ref: Mapping[str, Any]) -> Tuple[bool, str]:
    source_path = str(ref.get("source_path") or ref.get("ref_path") or "").strip()
    resolved = rq0._resolve_source_path(source_path) if source_path else None
    if resolved is None or not resolved.is_file():
        return False, ""
    offsets = ref.get("byte_offsets") or ref.get("source_byte_offsets") or {}
    if not isinstance(offsets, Mapping):
        return True, ""
    try:
        start = int(offsets.get("start"))
        end = int(offsets.get("end"))
    except (TypeError, ValueError):
        return True, ""
    if start < 0 or end <= start or end - start > MAX_OFFSET_READ_BYTES:
        return True, ""
    try:
        size = resolved.stat().st_size
        if end > size:
            return True, ""
        with resolved.open("rb") as handle:
            handle.seek(start)
            return True, handle.read(end - start).decode("utf-8", errors="replace")
    except OSError:
        return False, ""


def _raw_evidence(refs: Sequence[Mapping[str, Any]]) -> Tuple[int, List[str]]:
    raw_inputs = rq0._raw_requests(refs)
    wanted: Dict[str, set[str]] = defaultdict(set)
    for request in raw_inputs:
        if request.get("resolved_path"):
            wanted[str(request["resolved_path"])].update(request.get("msg_ids") or ())
    messages, _stats = rq0._load_raw_messages(wanted)
    resolved_count = 0
    texts: List[str] = []
    for ref in refs:
        resolved, offset_text = _offset_text(ref)
        resolved_count += int(resolved)
        if offset_text:
            texts.append(offset_text)
        source_path = str(ref.get("source_path") or ref.get("ref_path") or "").strip()
        path = rq0._resolve_source_path(source_path) if source_path else None
        path_text = str(path) if path is not None and path.is_file() else ""
        for msg_id in _items(ref.get("msg_ids")):
            text = messages.get((path_text, str(msg_id)))
            if text:
                texts.append(text)
    return resolved_count, texts


def _card_bytes(record: Mapping[str, Any]) -> int:
    payload = {
        "summary": record.get("summary") or "",
        "detail": record.get("detail") or "",
        "verbatim_excerpt": record.get("verbatim_excerpt") or "",
        "action_strategy": record.get("action_strategy") or [],
        "acceptance_checks": record.get("acceptance_checks") or [],
    }
    return len(canonical_json(payload).encode("utf-8"))


def collect_card_markers(
    runtime_root: Path, marker_cutoff: datetime
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    all_records = load_file_backed_library_candidate_records(
        xingce_root=str(runtime_root), include_inactive=True
    )
    records = load_file_backed_library_candidate_records(
        xingce_root=str(runtime_root), include_inactive=False
    )
    rows: List[Dict[str, Any]] = []
    seen_ids = set()
    excluded_after_cutoff = 0
    explicitly_inactive_excluded = 0
    support_identity: List[Dict[str, Any]] = []
    marker_cutoff = marker_cutoff.astimezone(timezone.utc)
    for record in records:
        status = str(record.get("lifecycle_status") or record.get("status") or "").strip().lower()
        if status in {"deprecated", "superseded", "recycled", "invalid"}:
            explicitly_inactive_excluded += 1
            continue
        library_id = library_id_for(dict(record))
        if not library_id:
            raise RQ1Error("card_library_id_missing")
        if library_id in seen_ids:
            raise RQ1Error("duplicate_card_library_id")
        seen_ids.add(library_id)
        paths = _support_paths(record, runtime_root)
        support_times = [datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) for path in paths]
        card_times = _record_time_candidates(record) + support_times
        if not card_times:
            raise RQ1Error("card_marker_time_missing")
        card_time = max(card_times)
        if card_time > marker_cutoff:
            excluded_after_cutoff += 1
            continue
        refs = _source_refs(record)
        if not refs:
            raise RQ1Error("card_source_refs_missing")
        if any(value > marker_cutoff for value in _ref_observed_times(refs)):
            raise RQ1Error("card_source_observed_after_marker_cutoff")
        card = library_card_for(dict(record))
        if str(card.get("library_id") or "") != library_id:
            raise RQ1Error("card_library_id_projection_mismatch")
        verbatim = str(record.get("verbatim_excerpt") or card.get("verbatim_excerpt") or "")
        declared_hash = str(
            record.get("verbatim_sha256")
            or card.get("verbatim_sha256")
            or ""
        ).strip()
        resolved_ref_count, raw_texts = _raw_evidence(refs)
        exact = bool(verbatim) and any(verbatim in text for text in raw_texts)
        hash_matches = bool(verbatim and declared_hash) and (
            sha256_bytes(verbatim.encode("utf-8")) == declared_hash
        )
        source_mode = str(record.get("source_mode") or card.get("source_mode") or "")
        provenance_bound = source_mode in {
            "evidence_bound_model_distill",
            "evidence_bound_p2_extract",
            "evidence_bound_errata_adjudication",
        }
        systems = {
            str(ref.get("source_system") or "").strip()
            for ref in refs
            if str(ref.get("source_system") or "").strip()
        }
        source_commits = [value for value in _ref_last_commit_times(refs) if value <= marker_cutoff]
        staleness_known = bool(source_commits)
        staleness_seconds = (
            max(0.0, (max(source_commits) - card_time).total_seconds())
            if source_commits
            else 0.0
        )
        shelf = str(card.get("shelf") or "")
        features = {
            "provenance_roundtrip_exact": float(exact),
            "verbatim_present": float(bool(verbatim.strip())),
            "verbatim_not_distill_masquerade": float(exact and hash_matches),
            "distill_provenance_bound": float(provenance_bound),
            "source_ref_count": float(len(refs)),
            "source_system_diversity": float(len(systems)),
            "shelf_zhiyi": float(shelf == "zhiyi"),
            "shelf_xingce": float(shelf == "xingce"),
            "shelf_toolbook": float(shelf == "toolbook"),
            "shelf_errata": float(shelf == "errata"),
            "staleness_known": float(staleness_known),
            "log_staleness_seconds": round(math.log1p(staleness_seconds), 12),
            "log_card_age_seconds": round(
                math.log1p(max(0.0, (marker_cutoff - card_time).total_seconds())), 12
            ),
            "log_card_bytes": round(math.log1p(_card_bytes(record)), 12),
        }
        support = [
            {
                "relative_path_sha256": sha256_bytes(
                    str(path.relative_to(runtime_root)).encode("utf-8")
                ),
                "file_sha256": file_sha256(path),
                "mtime": _iso(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)),
                "size": path.stat().st_size,
            }
            for path in paths
        ]
        support_identity.extend(support)
        rows.append(
            {
                "card_key": "rq1-card-" + sha256_bytes(library_id.encode("utf-8"))[:32],
                "library_id": library_id,
                "marker_observed_at": _iso(marker_cutoff),
                "card_state_observed_at": _iso(card_time),
                "features": features,
                "raw_evidence": {
                    "source_ref_count": len(refs),
                    "resolved_source_ref_count": resolved_ref_count,
                    "raw_text_match_count": sum(
                        int(bool(verbatim) and verbatim in text) for text in raw_texts
                    ),
                    "declared_verbatim_hash_matches": hash_matches,
                },
                "source_systems": sorted(systems),
                "support_identity_sha256": sha256_json(support),
            }
        )
    rows.sort(key=lambda item: item["card_key"])
    return rows, {
        "loaded_current_borrowable_card_count": len(records),
        "loaded_all_file_backed_card_count": len(all_records),
        "inactive_or_nonborrowable_card_count": len(all_records) - len(records),
        "marker_card_count": len(rows),
        "excluded_support_file_after_marker_cutoff_count": excluded_after_cutoff,
        "explicitly_inactive_card_excluded_count": explicitly_inactive_excluded,
        "support_file_count": len(support_identity),
        "support_identity_sha256": sha256_json(
            sorted(support_identity, key=canonical_json)
        ),
        "population_semantics": (
            "current borrowable file-backed cards whose support-file and declared source times "
            "are at or before T0; this is not a complete historical card reconstruction"
        ),
        "staleness_unknown_card_count": sum(
            int((row.get("features") or {}).get("staleness_known") == 0.0)
            for row in rows
        ),
    }


def build_card_snapshot(runtime_root: Path, marker_cutoff: datetime) -> Dict[str, Any]:
    rows, diagnostics = collect_card_markers(runtime_root, marker_cutoff)
    if not rows:
        raise RQ1Error("card_marker_population_empty")
    snapshot: Dict[str, Any] = {
        "contract": SNAPSHOT_CONTRACT,
        "marker_cutoff": _iso(marker_cutoff),
        "card_count": len(rows),
        "marker_rows": rows,
        "diagnostics": diagnostics,
        "contains_card_text": False,
        "contains_source_paths": False,
        "local_only": True,
        "mode": "0600",
        "rq1_tool_sha256": file_sha256(Path(__file__)),
    }
    payload = dict(snapshot)
    snapshot["canonical_payload_sha256"] = sha256_json(payload)
    return snapshot


def validate_card_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("contract") != SNAPSHOT_CONTRACT:
        raise RQ1Error("card_snapshot_contract_mismatch")
    payload = dict(snapshot)
    claimed = str(payload.pop("canonical_payload_sha256", ""))
    if not claimed or sha256_json(payload) != claimed:
        raise RQ1Error("card_snapshot_canonical_payload_mismatch")
    if snapshot.get("contains_card_text") is not False:
        raise RQ1Error("card_snapshot_must_not_contain_card_text")
    if snapshot.get("contains_source_paths") is not False:
        raise RQ1Error("card_snapshot_must_not_contain_source_paths")
    if str(snapshot.get("rq1_tool_sha256") or "") != file_sha256(Path(__file__)):
        raise RQ1Error("card_snapshot_tool_sha256_mismatch")
    rows = snapshot.get("marker_rows")
    if not isinstance(rows, list) or not rows:
        raise RQ1Error("card_snapshot_marker_rows_missing")
    if int(snapshot.get("card_count") or 0) != len(rows):
        raise RQ1Error("card_snapshot_count_mismatch")
    ids = [str(row.get("library_id") or "") for row in rows if isinstance(row, Mapping)]
    if len(ids) != len(rows) or not all(ids):
        raise RQ1Error("card_snapshot_library_id_missing")
    if len(set(ids)) != len(ids):
        raise RQ1Error("card_snapshot_duplicate_library_id")
    marker_cutoff = _parse_time(snapshot.get("marker_cutoff"))
    for row in rows:
        if not isinstance(row, Mapping):
            raise RQ1Error("card_snapshot_marker_row_invalid")
        if _parse_time(row.get("marker_observed_at")) != marker_cutoff:
            raise RQ1Error("card_snapshot_marker_time_mismatch")
        if _parse_time(row.get("card_state_observed_at")) > marker_cutoff:
            raise RQ1Error("card_snapshot_future_card_state")
        features = row.get("features")
        if not isinstance(features, Mapping) or set(features) != set(FEATURE_NAMES):
            raise RQ1Error("card_snapshot_feature_contract_mismatch")


def _library_ids_from_refs(refs: object) -> List[str]:
    values = []
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, Mapping):
            continue
        library_id = str(ref.get("library_id") or "").strip()
        if library_id and library_id not in values:
            values.append(library_id)
    return values


def _event_library_ids(event: Mapping[str, Any], stage: str) -> List[str]:
    if stage == "used":
        return _library_ids_from_refs(event.get("used_source_refs"))
    return _library_ids_from_refs(event.get("source_refs"))


def _event_card_refs(event: Mapping[str, Any], stage: str) -> List[Dict[str, str]]:
    source = event.get("used_source_refs") if stage == "used" else event.get("source_refs")
    refs = []
    for value in source if isinstance(source, list) else []:
        if not isinstance(value, Mapping):
            continue
        library_id = str(value.get("library_id") or "").strip()
        source_system = str(value.get("source_system") or "").strip()
        if library_id:
            refs.append({"library_id": library_id, "source_system": source_system})
    return refs


def _strongly_matched_library_ids(
    refs: Sequence[Mapping[str, str]],
    marker_identities: Mapping[str, Sequence[str]],
) -> List[str]:
    matched = []
    for ref in refs:
        library_id = str(ref.get("library_id") or "")
        source_system = str(ref.get("source_system") or "")
        expected_systems = set(str(item) for item in marker_identities.get(library_id, []))
        if library_id and source_system and source_system in expected_systems:
            if library_id not in matched:
                matched.append(library_id)
    return matched


def _read_delivery_rows(
    db_path: Path, label_cutoff: datetime
) -> Tuple[List[sqlite3.Row], List[sqlite3.Row], List[sqlite3.Row], str]:
    if not db_path.is_file():
        raise RQ1Error("delivery_db_missing")
    connection = sqlite3.connect(
        db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10
    )
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        events = connection.execute(
            """
            SELECT rowid, retrieval_id, stage, observed_at, event_json
            FROM delivery_events WHERE observed_at <= ? ORDER BY rowid
            """,
            (_iso(label_cutoff),),
        ).fetchall()
        decisions = connection.execute(
            """
            SELECT rowid, retrieval_id, decision, observed_at, reasons_json, decision_json
            FROM delivery_decisions WHERE observed_at <= ? ORDER BY rowid
            """,
            (_iso(label_cutoff),),
        ).fetchall()
        security = connection.execute(
            """
            SELECT rowid, challenge_id, platform, reason, observed_at
            FROM delivery_security_events WHERE observed_at <= ? ORDER BY rowid
            """,
            (_iso(label_cutoff),),
        ).fetchall()
    finally:
        connection.close()
    return events, decisions, security, quick_check


def read_card_adoption_evidence(
    db_path: Path,
    *,
    marker_cutoff: datetime,
    label_cutoff: datetime,
    marker_identities: Mapping[str, Sequence[str]],
) -> Dict[str, Any]:
    if label_cutoff <= marker_cutoff:
        raise RQ1Error("label_cutoff_must_be_after_marker_cutoff")
    event_rows, decision_rows, security_rows, quick_check = _read_delivery_rows(
        db_path, label_cutoff
    )
    decisions: Dict[str, Dict[str, Any]] = {}
    for row in decision_rows:
        retrieval_id = str(row["retrieval_id"] or "")
        if retrieval_id in decisions:
            raise RQ1Error("duplicate_delivery_decision_for_retrieval")
        try:
            decision_json = json.loads(str(row["decision_json"]))
        except json.JSONDecodeError as exc:
            raise RQ1Error("delivery_decision_json_invalid") from exc
        if not isinstance(decision_json, dict):
            raise RQ1Error("delivery_decision_not_object")
        if str(decision_json.get("retrieval_id") or "") != retrieval_id:
            raise RQ1Error("delivery_decision_retrieval_column_mismatch")
        if str(decision_json.get("decision") or "") != str(row["decision"] or ""):
            raise RQ1Error("delivery_decision_column_mismatch")
        decisions[retrieval_id] = {
            "decision": str(row["decision"] or ""),
            "reasons": json.loads(str(row["reasons_json"] or "[]")),
        }

    chains: Dict[str, List[Tuple[sqlite3.Row, Dict[str, Any]]]] = defaultdict(list)
    for row in event_rows:
        try:
            event = json.loads(str(row["event_json"]))
        except json.JSONDecodeError as exc:
            raise RQ1Error("delivery_event_json_invalid") from exc
        if not isinstance(event, dict):
            raise RQ1Error("delivery_event_not_object")
        retrieval_id = str(row["retrieval_id"] or "")
        stage = str(row["stage"] or "")
        if str(event.get("retrieval_id") or "") != retrieval_id:
            raise RQ1Error("delivery_event_retrieval_column_mismatch")
        if str(event.get("delivery_stage") or "") != stage:
            raise RQ1Error("delivery_event_stage_column_mismatch")
        if _iso(_parse_time(event.get("observed_at"))) != _iso(_parse_time(row["observed_at"])):
            raise RQ1Error("delivery_event_observed_at_column_mismatch")
        chains[retrieval_id].append((row, event))

    marker_ids = set(str(item) for item in marker_identities)
    historical_delivered_ids = set()
    historical_delivered_strong_ids = set()
    current_validator_delivered_ids = set()
    current_validator_delivered_strong_ids = set()
    matched_delivered_ref_count = 0
    delivered_ref_count = 0
    selected_times: Dict[str, List[str]] = defaultdict(list)
    used_times: Dict[str, List[str]] = defaultdict(list)
    exposure_times: Dict[str, List[str]] = defaultdict(list)
    stage_counts = Counter()
    invalid_chain_count = 0
    invalid_event_count = 0
    digest_rows: List[Dict[str, Any]] = []

    # Gate C is a storage-layer join audit over all row-integrity-checked
    # delivered events.  Current-validator acceptance remains separate and is
    # the only source eligible for labels below; legacy rows cannot become
    # quality evidence merely because their library_id still joins.
    for retrieval_id, chain in chains.items():
        decision = decisions.get(retrieval_id, {"decision": "", "reasons": []})
        if decision.get("decision") != "emit":
            continue
        for row, event in chain:
            if str(row["stage"] or "") != "delivered":
                continue
            refs = _event_card_refs(event, "delivered")
            ids = [ref["library_id"] for ref in refs]
            strong_ids = _strongly_matched_library_ids(refs, marker_identities)
            historical_delivered_ids.update(ids)
            historical_delivered_strong_ids.update(strong_ids)
            delivered_ref_count += len(ids)
            matched_delivered_ref_count += len(strong_ids)

    for retrieval_id, chain in chains.items():
        events = [event for _row, event in chain]
        validation = validate_delivery_chain(events)
        valid_count = int(validation.get("validated_prefix_event_count") or 0)
        if validation.get("errors"):
            invalid_chain_count += 1
            invalid_event_count += len(events)
            continue
        if valid_count != len(events):
            invalid_chain_count += 1
            invalid_event_count += len(events)
            continue
        valid = chain
        decision = decisions.get(retrieval_id, {"decision": "", "reasons": []})
        delivered_in_window = set()
        used_in_window = set()
        for row, event in valid:
            observed = _parse_time(row["observed_at"])
            stage = str(row["stage"] or "")
            refs = _event_card_refs(event, stage)
            ids = [ref["library_id"] for ref in refs]
            strong_ids = _strongly_matched_library_ids(refs, marker_identities)
            if stage == "delivered" and decision.get("decision") == "emit":
                current_validator_delivered_ids.update(ids)
                current_validator_delivered_strong_ids.update(strong_ids)
            if not (marker_cutoff < observed <= label_cutoff):
                continue
            stage_counts[stage] += 1
            if decision.get("decision") != "emit":
                continue
            if stage == "delivered":
                delivered_in_window.update(strong_ids)
                for library_id in strong_ids:
                    exposure_times[library_id].append(_iso(observed))
            elif stage == "selected":
                for library_id in strong_ids:
                    selected_times[library_id].append(_iso(observed))
            elif stage == "used":
                used_in_window.update(strong_ids)
                for library_id in strong_ids:
                    used_times[library_id].append(_iso(observed))
            digest_rows.append(
                {
                    "retrieval_sha256": sha256_bytes(retrieval_id.encode("utf-8")),
                    "stage": stage,
                    "observed_at": _iso(observed),
                    "library_id_sha256": [
                        sha256_bytes(item.encode("utf-8")) for item in sorted(ids)
                    ],
                    "decision": decision.get("decision"),
                }
            )
        for library_id in delivered_in_window - used_in_window:
            exposure_times[library_id] = sorted(set(exposure_times[library_id]))

    labels = []
    for library_id in sorted(marker_ids):
        good_times = sorted(set(used_times.get(library_id, [])))
        if good_times:
            labels.append(
                {
                    "library_id": library_id,
                    "label": 0,
                    "label_observed_at": good_times[0],
                    "label_source": "host_attested_used_source_refs_card_proxy",
                }
            )
            continue
        if exposure_times.get(library_id):
            labels.append(
                {
                    "library_id": library_id,
                    "label": 1,
                    "label_observed_at": _iso(label_cutoff),
                    "label_source": "proven_delivered_exposure_never_used_proxy",
                }
            )

    matched_ids = historical_delivered_strong_ids
    unmatched_ids = historical_delivered_ids - marker_ids
    weak_identity_mismatch_ids = (historical_delivered_ids & marker_ids) - matched_ids
    security_in_window = [
        row
        for row in security_rows
        if marker_cutoff < _parse_time(row["observed_at"]) <= label_cutoff
    ]
    return {
        "quick_check": quick_check,
        "query_only": True,
        "labels": labels,
        "validated_retrieval_chain_count": len(chains) - invalid_chain_count,
        "invalid_retrieval_chain_count": invalid_chain_count,
        "invalid_chain_event_count_excluded": invalid_event_count,
        "event_count_in_label_window": sum(stage_counts.values()),
        "stage_counts_in_label_window": dict(sorted(stage_counts.items())),
        "delivered_card_library_id_distinct_count": len(historical_delivered_ids),
        "delivered_card_library_id_matched_count": len(matched_ids),
        "delivered_card_library_id_unmatched_count": len(unmatched_ids),
        "delivered_card_library_id_source_system_mismatch_count": len(
            weak_identity_mismatch_ids
        ),
        "delivered_card_library_id_match_rate": _rate(
            len(matched_ids), len(historical_delivered_ids)
        ),
        "delivered_card_library_id_unmatched_rate": _rate(
            len(unmatched_ids), len(historical_delivered_ids)
        ),
        "delivered_card_reference_match_rate": _rate(
            matched_delivered_ref_count, delivered_ref_count
        ),
        "delivered_card_matched_event_ref_count": matched_delivered_ref_count,
        "delivered_card_event_ref_count": delivered_ref_count,
        "current_validator_delivered_card_library_id_distinct_count": len(
            current_validator_delivered_ids
        ),
        "current_validator_delivered_card_library_id_matched_count": len(
            current_validator_delivered_strong_ids
        ),
        "join_scope": (
            "all append-only row-integrity-checked delivered refs; current delivery-chain "
            "validation is reported separately and is required for natural labels"
        ),
        "matched_library_ids_sha256": sha256_json(sorted(matched_ids)),
        "unmatched_library_ids_sha256": sha256_json(sorted(unmatched_ids)),
        "selected_matched_card_count": sum(
            bool(selected_times.get(library_id)) for library_id in marker_ids
        ),
        "used_matched_card_count": sum(
            bool(used_times.get(library_id)) for library_id in marker_ids
        ),
        "proven_exposure_never_used_card_count": sum(
            bool(exposure_times.get(library_id))
            and not bool(used_times.get(library_id))
            for library_id in marker_ids
        ),
        "selected_is_policy_signal_not_adoption_label": True,
        "used_is_host_attested": True,
        "challenge_rejection_count_in_label_window": len(security_in_window),
        "challenge_rejection_labeled_bad_count": 0,
        "helped_is_label": False,
        "sanitized_evidence_sha256": sha256_json(
            {
                "events": digest_rows,
                "security": [
                    {
                        "reason": str(row["reason"] or ""),
                        "observed_at": _iso(_parse_time(row["observed_at"])),
                        "challenge_sha256": sha256_bytes(
                            str(row["challenge_id"] or "").encode("utf-8")
                        ),
                    }
                    for row in security_in_window
                ],
            }
        ),
    }


def _feature_vector(row: Mapping[str, Any]) -> List[float]:
    features = row.get("features") or {}
    return [float(features.get(name) or 0.0) for name in FEATURE_NAMES]


def _sigmoid(value: float) -> float:
    if value >= 0:
        exponent = math.exp(-value)
        return 1.0 / (1.0 + exponent)
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def fit_l2_logistic(
    rows: Sequence[Mapping[str, Any]],
    *,
    l2: float = 1.0,
    learning_rate: float = 0.08,
    max_iterations: int = 600,
) -> Dict[str, Any]:
    if not rows:
        raise RQ1Error("logistic_rows_required")
    vectors = [_feature_vector(row) for row in rows]
    means = [sum(row[index] for row in vectors) / len(vectors) for index in range(len(FEATURE_NAMES))]
    scales = []
    for index, mean in enumerate(means):
        variance = sum((row[index] - mean) ** 2 for row in vectors) / len(vectors)
        scales.append(math.sqrt(variance) or 1.0)
    matrix = [
        [1.0] + [(value - means[index]) / scales[index] for index, value in enumerate(row)]
        for row in vectors
    ]
    labels = [int(row["label"]) for row in rows]
    weights = [0.0] * (len(FEATURE_NAMES) + 1)
    iterations = 0
    for iteration in range(max_iterations):
        gradients = [0.0] * len(weights)
        for vector, label in zip(matrix, labels):
            prediction = _sigmoid(sum(weight * value for weight, value in zip(weights, vector)))
            error = prediction - label
            for index, value in enumerate(vector):
                gradients[index] += error * value
        for index in range(len(gradients)):
            gradients[index] /= len(rows)
            if index:
                gradients[index] += l2 * weights[index] / len(rows)
        delta = [learning_rate * value for value in gradients]
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
    raw = _feature_vector(row)
    vector = [1.0] + [
        (value - float(model["means"][index])) / float(model["scales"][index])
        for index, value in enumerate(raw)
    ]
    return round(
        _sigmoid(sum(float(weight) * value for weight, value in zip(model["weights"], vector))),
        15,
    )


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
        rank = (cursor + 1 + end) / 2.0
        for index in range(cursor, end):
            ranks[ordered[index][0]] = rank
        cursor = end
    rank_sum = sum(rank for rank, label in zip(ranks, labels) if label == 1)
    return round(
        (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives),
        12,
    )


def precision_at_k(labels: Sequence[int], scores: Sequence[float], k: int) -> Optional[float]:
    if not labels:
        return None
    limit = min(max(1, k), len(labels))
    selected = sorted(range(len(scores)), key=lambda index: (-scores[index], index))[:limit]
    return round(sum(labels[index] for index in selected) / limit, 12)


def _temporal_split(
    labels: Sequence[Mapping[str, Any]],
) -> Optional[Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]]:
    ordered = sorted(labels, key=lambda row: (row["label_observed_at"], row["card_key"]))
    for fraction in (0.70, 0.65, 0.75, 0.60, 0.80):
        split = max(1, min(len(ordered) - 1, int(len(ordered) * fraction)))
        train = ordered[:split]
        evaluation = ordered[split:]
        train_counts = Counter(int(row["label"]) for row in train)
        eval_counts = Counter(int(row["label"]) for row in evaluation)
        if (
            min(train_counts.get(0, 0), train_counts.get(1, 0)) >= MIN_TRAIN_CLASS_CARDS
            and min(eval_counts.get(0, 0), eval_counts.get(1, 0)) >= MIN_EVAL_CLASS_CARDS
            and train[-1]["label_observed_at"] <= evaluation[0]["label_observed_at"]
        ):
            return list(train), list(evaluation)
    return None


def evaluate_proxy(
    marker_rows: Sequence[Mapping[str, Any]],
    labels: Sequence[Mapping[str, Any]],
    *,
    join_matched_count: int,
    precision_k: int = DEFAULT_PRECISION_K,
) -> Dict[str, Any]:
    if join_matched_count <= 0:
        return {
            "decision": DECISION_JOIN_NOT_PROVEN,
            "sparse_reasons": ["delivered_card_library_id_join_is_zero"],
            "model_fitted": False,
            "roc_auc": None,
            "precision_at_k": None,
            "learned_constants": None,
        }
    class_counts = Counter(int(row["label"]) for row in labels)
    coverage = len(labels) / len(marker_rows) if marker_rows else 0.0
    reasons = []
    if coverage < MIN_LABEL_COVERAGE_RATE:
        reasons.append("label_coverage_below_minimum")
    if len(labels) < MIN_LABELED_CARDS:
        reasons.append("labeled_card_count_below_minimum")
    if min(class_counts.get(0, 0), class_counts.get(1, 0)) < MIN_CLASS_CARDS:
        reasons.append("class_support_below_minimum")
    split = _temporal_split(labels) if not reasons else None
    if not reasons and split is None:
        reasons.append("temporal_split_class_support_insufficient")
    if reasons:
        return {
            "decision": DECISION_SPARSE,
            "sparse_reasons": reasons,
            "model_fitted": False,
            "roc_auc": None,
            "precision_at_k": None,
            "learned_constants": None,
        }
    assert split is not None
    train, evaluation = split
    model = fit_l2_logistic(train)
    scores = [score_with_model(row, model) for row in evaluation]
    eval_labels = [int(row["label"]) for row in evaluation]
    return {
        "decision": DECISION_CALIBRATED,
        "sparse_reasons": [],
        "model_fitted": True,
        "roc_auc": roc_auc(eval_labels, scores),
        "precision_at_k": {
            "k": min(precision_k, len(evaluation)),
            "value": precision_at_k(eval_labels, scores, precision_k),
        },
        "train": {
            "count": len(train),
            "class_counts": dict(sorted(Counter(int(row["label"]) for row in train).items())),
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
    delivery_db: Path,
    label_cutoff: datetime,
    card_snapshot: Optional[Mapping[str, Any]] = None,
    marker_cutoff: Optional[datetime] = None,
) -> Dict[str, Any]:
    snapshot = (
        dict(card_snapshot)
        if card_snapshot is not None
        else build_card_snapshot(
            runtime_root,
            marker_cutoff
            if marker_cutoff is not None
            else (_parse_time(label_cutoff) if not isinstance(label_cutoff, datetime) else label_cutoff),
        )
    )
    validate_card_snapshot(snapshot)
    marker_rows = [dict(row) for row in snapshot["marker_rows"]]
    marker_diagnostics = dict(snapshot.get("diagnostics") or {})
    marker_cutoff = _parse_time(snapshot["marker_cutoff"])
    evidence = read_card_adoption_evidence(
        delivery_db,
        marker_cutoff=marker_cutoff,
        label_cutoff=label_cutoff,
        marker_identities={
            str(row["library_id"]): [str(item) for item in row.get("source_systems") or []]
            for row in marker_rows
        },
    )
    marker_by_id = {row["library_id"]: row for row in marker_rows}
    labels = []
    for item in evidence["labels"]:
        marker = marker_by_id.get(str(item["library_id"]))
        if marker is None:
            continue
        labels.append(
            {
                "card_key": marker["card_key"],
                "label": int(item["label"]),
                "label_observed_at": str(item["label_observed_at"]),
                "label_source": str(item["label_source"]),
                "features": dict(marker["features"]),
            }
        )
    labels.sort(key=lambda row: (row["label_observed_at"], row["card_key"]))
    evaluation = evaluate_proxy(
        marker_rows,
        labels,
        join_matched_count=int(evidence["delivered_card_library_id_matched_count"]),
    )
    marker_matrix = [
        {"card_key": row["card_key"], "features": row["features"]}
        for row in marker_rows
    ]
    label_vector = [
        {
            "card_key": row["card_key"],
            "label": row["label"],
            "label_observed_at": row["label_observed_at"],
            "label_source": row["label_source"],
        }
        for row in labels
    ]
    class_counts = Counter(int(row["label"]) for row in labels)
    report: Dict[str, Any] = {
        "contract": CONTRACT,
        "decision": evaluation["decision"],
        "proof_layer": "file_backed_card_snapshot_plus_read_only_delivery_adoption_proxy",
        "score_is_adoption_proxy_not_semantic_accuracy": True,
        "rescopes_r2_quality_to_card_adoption_layer": True,
        "raw_extraction_remains_unmeasured_upstream": True,
        "raw_extraction_quality_status": "not_measured",
        "used_is_host_attested": True,
        "used_is_not_helped": True,
        "helped_status": "unknown",
        "quality_status": QUALITY_STATUS,
        "production_decision": PRODUCTION_DECISION,
        "production_unlock": False,
        "read_only": True,
        "runtime_write_performed": False,
        "global_zero_write_proven": False,
        "model_call_performed": False,
        "product_hot_path_modified": False,
        "marker_cutoff": _iso(marker_cutoff),
        "label_cutoff": _iso(label_cutoff),
        "label_window": "(marker_cutoff,label_cutoff]",
        "strict_future_only": True,
        "marker_cutoff_selection": (
            "explicit historical pre-delivery baseline supplied by the caller; "
            "support-file mtimes and declared source times must be at or before it"
        ),
        "input_identity": {
            "rq1_tool_sha256": file_sha256(Path(__file__)),
            "rq0_raw_reader_helper_sha256": file_sha256(Path(rq0.__file__)),
            "card_snapshot_canonical_payload_sha256": snapshot[
                "canonical_payload_sha256"
            ],
            "delivery_chain_validator_sha256": file_sha256(
                Path(sys.modules[validate_delivery_chain.__module__].__file__)
            ),
            "marker_support_identity_sha256": marker_diagnostics["support_identity_sha256"],
            "delivery_sanitized_evidence_sha256": evidence["sanitized_evidence_sha256"],
        },
        "markers": {
            "granularity": "file_backed_library_card",
            "definitions": {
                "provenance_roundtrip_exact": "the card verbatim excerpt occurs byte-exactly in resolved source evidence",
                "verbatim_present": "the card exposes a non-empty verbatim excerpt",
                "verbatim_not_distill_masquerade": "the excerpt both roundtrips to raw evidence and matches its declared SHA256",
                "distill_provenance_bound": "the card declares an allowed evidence-bound source mode and source refs",
                "source_ref_count": "deduplicated primary, merged, and evidence source-ref count",
                "source_system_diversity": "distinct declared source systems",
                "shelf_*": "one-hot current card shelf",
                "staleness_known": "an explicit source last-commit timestamp exists at or before T0",
                "log_staleness_seconds": "log1p(max(source_last_commit-card_state_time,0)); zero when unknown",
                "log_card_age_seconds": "log1p(T0-card_state_time)",
                "log_card_bytes": "log1p deterministic card payload bytes",
            },
            "card_count": len(marker_rows),
            "matrix_sha256": sha256_json(marker_matrix),
            "summary": _feature_summary(marker_rows),
            "diagnostics": marker_diagnostics,
            "staleness_missing_value_encoding": (
                "log_staleness_seconds=0 is only a numeric sentinel when staleness_known=0; "
                "it must not be interpreted as fresh"
            ),
        },
        "natural_labels": {
            "definition": {
                "risk_0": "strictly later emit-path used_source_refs evidence for this card",
                "risk_1": "strictly later proven delivered exposure with no used_source_refs evidence by cutoff",
                "unlabeled": "no proven emit exposure opportunity, only silent/lifecycle/challenge noise, or no later evidence",
            },
            "selected_is_policy_signal_not_adoption_label": True,
            "used_source_refs_is_the_only_positive_adoption_proxy": True,
            "labeled_card_count": len(labels),
            "unlabeled_card_count": len(marker_rows) - len(labels),
            "coverage_rate": _rate(len(labels), len(marker_rows)),
            "class_counts": {
                "risk_0_good_adoption_proxy": class_counts.get(0, 0),
                "risk_1_low_adoption_proxy": class_counts.get(1, 0),
            },
            "label_vector_sha256": sha256_json(label_vector),
            "noise_ledger": list(NOISE_LEDGER),
        },
        "gate_b_no_future_leakage": {
            "marker_time": _iso(marker_cutoff),
            "support_files_not_after_marker_time": True,
            "declared_source_times_not_after_marker_time": True,
            "labels_strictly_after_marker_time": all(
                _parse_time(row["label_observed_at"]) > marker_cutoff for row in labels
            ),
            "evaluation_labels_not_marker_or_score_inputs": True,
            "future_label_mutation_score_invariance": True,
            "proof_anchor": (
                "tests/test_rq1_card_adoption_baseline.py::"
                "test_future_evaluation_label_mutation_keeps_markers_model_and_scores_fixed"
            ),
        },
        "gate_c_card_join": {
            key: evidence[key]
            for key in (
                "delivered_card_library_id_distinct_count",
                "delivered_card_library_id_matched_count",
                "delivered_card_library_id_unmatched_count",
                "delivered_card_library_id_source_system_mismatch_count",
                "delivered_card_library_id_match_rate",
                "delivered_card_library_id_unmatched_rate",
                "delivered_card_reference_match_rate",
                "delivered_card_matched_event_ref_count",
                "delivered_card_event_ref_count",
                "current_validator_delivered_card_library_id_distinct_count",
                "current_validator_delivered_card_library_id_matched_count",
                "join_scope",
                "matched_library_ids_sha256",
                "unmatched_library_ids_sha256",
            )
        },
        "delivery_evidence": {
            key: value
            for key, value in evidence.items()
            if key not in {"labels"}
        },
        "calibration_thresholds": {
            "minimum_label_coverage_rate": MIN_LABEL_COVERAGE_RATE,
            "minimum_labeled_cards": MIN_LABELED_CARDS,
            "minimum_cards_per_class": MIN_CLASS_CARDS,
            "minimum_train_cards_per_class": MIN_TRAIN_CLASS_CARDS,
            "minimum_evaluation_cards_per_class": MIN_EVAL_CLASS_CARDS,
        },
        "evaluation": evaluation,
        "non_claims": [
            "card adoption proxy is not semantic accuracy",
            "this rescope does not measure raw/state extraction quality",
            "AUC, when present, predicts host-attested adoption rather than truth or benefit",
            "used is host-attested rather than independent model request/response bytes; selected is only a policy state",
            "policy-selected is not used as an adoption label",
            "used does not imply helped",
            "current borrowable card files are not a complete historical card reconstruction",
            "delivery refs bind library_id and source_system but do not carry a card-content digest",
            "support-file mtime is a local as-of guard rather than cryptographic historical attestation",
            "challenge mismatch and silent decisions are not bad-card labels",
            "R2 quality remains not_measured and production shadow remains NO_GO",
            "no product runtime, recall, delivery, gateway, installed, push, release, LAN, or cross-machine proof",
            "the generated report is a local-only 0600 artifact, not a release artifact",
            "global zero-write is not claimed while independent watchers may append runtime sources",
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
        raise RQ1Error("report_output_must_not_be_inside_runtime_root")
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


def write_private_json(path: Path, payload: Mapping[str, Any], *, runtime_root: Path) -> None:
    path = Path(path)
    if _is_within(path, runtime_root):
        raise RQ1Error("private_output_must_not_be_inside_runtime_root")
    if path.exists():
        raise RQ1Error("private_output_already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (canonical_json(payload) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise RQ1Error("private_output_temporary_exists")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_private_json(path: Path) -> Dict[str, Any]:
    if Path(path).stat().st_mode & 0o077:
        raise RQ1Error("card_snapshot_permissions_must_be_0600")
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RQ1Error("card_snapshot_read_failed") from exc
    if not isinstance(payload, dict):
        raise RQ1Error("card_snapshot_not_object")
    validate_card_snapshot(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only R-Q1 card-adoption proxy baseline"
    )
    parser.add_argument("--runtime-root", type=Path, default=_default_runtime_root())
    parser.add_argument("--delivery-db", type=Path)
    parser.add_argument("--marker-cutoff")
    parser.add_argument("--label-cutoff", required=True)
    parser.add_argument("--snapshot-input", type=Path)
    parser.add_argument("--snapshot-output", type=Path)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    runtime_root = args.runtime_root.expanduser().resolve()
    delivery_db = (
        args.delivery_db.expanduser().resolve()
        if args.delivery_db
        else runtime_root / "runtime" / "delivery-events.sqlite3"
    )
    snapshot = None
    if args.snapshot_input:
        snapshot = read_private_json(args.snapshot_input.expanduser().resolve())
    else:
        if not args.marker_cutoff:
            parser.error("--marker-cutoff is required when --snapshot-input is absent")
        snapshot = build_card_snapshot(
            runtime_root, _parse_time(args.marker_cutoff)
        )
        if args.snapshot_output:
            write_private_json(
                args.snapshot_output.expanduser().resolve(),
                snapshot,
                runtime_root=runtime_root,
            )
    report = build_report(
        runtime_root=runtime_root,
        delivery_db=delivery_db,
        card_snapshot=snapshot,
        label_cutoff=_parse_time(args.label_cutoff),
    )
    write_report(args.report_output, report, runtime_root=runtime_root)
    print(
        canonical_json(
            {
                "ok": report["decision"] != DECISION_JOIN_NOT_PROVEN,
                "decision": report["decision"],
                "delivered_card_library_id_matched_count": report[
                    "gate_c_card_join"
                ]["delivered_card_library_id_matched_count"],
                "labeled_card_count": report["natural_labels"]["labeled_card_count"],
                "score_is_adoption_proxy_not_semantic_accuracy": True,
                "rescopes_r2_quality_to_card_adoption_layer": True,
                "raw_extraction_remains_unmeasured_upstream": True,
                "quality_status": QUALITY_STATUS,
                "production_decision": PRODUCTION_DECISION,
                "canonical_payload_sha256": report["canonical_payload_sha256"],
                "report_file_sha256": file_sha256(args.report_output),
            }
        )
    )
    return 0 if report["decision"] != DECISION_JOIN_NOT_PROVEN else 2


if __name__ == "__main__":
    raise SystemExit(main())
