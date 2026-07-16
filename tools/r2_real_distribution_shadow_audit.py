#!/usr/bin/env python3
"""Read-only workload audit for the R2 rule-first state extractor.

Reads a preregistered complete-record prefix and emits a deterministic, k-safe
aggregate plus a local-only opaque holdout. It never calls or writes a model.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import resource
import secrets
import sys
import tempfile
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

try:
    from src import state_memory_extraction_candidate as candidate_rules
except Exception:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src import state_memory_extraction_candidate as candidate_rules


CONTRACT = "time_library.r2_real_distribution_shadow_audit.v2026.7.14.15"
CUTOFF_CONTRACT = "time_library.r2_real_distribution_cutoff.v2026.7.14.2"
HOLDOUT_CONTRACT = "time_library.r2_real_distribution_opaque_holdout.v2026.7.14.2"
HOLDOUT_KEY_CONTRACT = "time_library.r2_real_distribution_holdout_key.v2026.7.14"
PREREGISTRATION_CONTRACT = "time_library.r2_real_distribution_preregistration.v2026.7.14"
RUN_RECEIPT_CONTRACT = "time_library.r2_real_distribution_run_receipt.v2026.7.14"
PRIVATE_PATH_MARKERS = (
    "/" + "Users" + "/",
    "/" + "Volumes" + "/",
    "\\" + "Users" + "\\",
)

DEFAULT_HOLDOUT_COUNT = 120
DEFAULT_PRIVACY_K = 5
MAX_JSONL_LINE_BYTES = 8 * 1024 * 1024
SELECTION_ALGORITHM = "hmac_sha256_round_robin_strata_v2"
CROSS_TABULATION_POLICY = "withheld_not_preregistered_and_small_cell_risk"
SMALL_CELL_POLICY = (
    "withhold distributions or subset count-rate pairs when any cell, "
    "subset or complement, or known cross-marginal subset difference "
    "is nonzero below k; apply complementary dependency suppression so "
    "withheld values cannot be reconstructed from remaining public fields"
)
PROJECTION_POLICY = "exact_or_contained_summary_detail_is_deduplicated_before_extraction"
LEGACY_NAIVE_UTC_POLICY = (
    "p2_extract legacy naive timestamps are explicitly interpreted as UTC"
)
TIME_RULE_IDS = [
    "raw_is_highest_authority",
    "source_refs_required_not_replacement",
    "events_remain_orderable",
    "unknown_must_remain_visible",
    "derived_sediment_must_reference_origin",
    "platforms_are_inlets_not_origin",
]
BASE_DECISION_REASONS = [
    "independent_blind_quality_labels_not_measured",
    "canonical_source_ref_retention_resolvability_and_semantics_not_measured",
    "raw_source_span_not_measured_projection_span_only",
    "cross_record_state_relations_not_measured",
    "default_claim_can_be_active_trusted_without_independent_verification",
    "production_shadow_not_owner_authorized",
    "actual_model_calls_zero_by_design",
]
NON_CLAIMS = [
    "engine no-ambiguity flag is not confidence, correctness, or safe automation",
    "rule matches do not prove correctness",
    "existing record kind is not a gold semantic label",
    "single-record extraction cannot measure cross-record conflict or supersession",
    "source-ref digest echo does not prove canonical retention or semantic support",
    "projection span exactness does not prove a raw-source byte span",
    "opaque holdout has no independent labels in this cut",
    "derived zhiyi objects are not the full raw-dialogue distribution",
    "measurement does not authorize production State Memory shadow",
]
RECORD_PATHS = {
    "preference": Path("zhiyi/preference_memory/preference_memory.jsonl"),
    "case": Path("zhiyi/case_memory/case_memory.jsonl"),
    "error": Path("zhiyi/error_memory/error_memory.jsonl"),
}
KNOWN_SOURCE_SYSTEMS = {
    "claude_code",
    "claude_code_cli",
    "claude_desktop",
    "codex",
    "cursor",
    "hermes",
    "openclaw",
    "pi",
}
RELATIONSHIP_TRACES = {
    "cross_source_conflict",
    "explicit_end_superseded",
    "newer_update_active",
    "newer_update_supersedes",
}

RULE_TRACES = {
    "action_procedure_rule",
    "cross_source_conflict",
    "default_claim_rule",
    "descriptive_schedule_rule",
    "event_claim_ambiguity",
    "explicit_end_superseded",
    "explicit_event_rule",
    "instruction_like_claim",
    "newer_update_active",
    "newer_update_supersedes",
    "preference_rule",
}

SKIP_REASONS = {
    "source_refs_invalid",
    "source_text_empty",
    "recorded_at_invalid",
    "observed_at_invalid",
}

ERROR_REASONS = {
    "extractor_error",
    "jsonl_line_too_large",
    "jsonl_parse_error",
    "jsonl_record_not_object",
    "jsonl_utf8_decode_error",
    "partial_line_inside_complete_prefix",
}

ALLOWED_DISTRIBUTION_LABELS = {
    "processing_outcome": {"processed", "skipped", "error"},
    "skip_reason": SKIP_REASONS,
    "error_reason": ERROR_REASONS,
    "record_kind": set(RECORD_PATHS),
    "semantic_type": {"claim", "event", "procedure", "preference", "missing", "other"},
    "state_role": {
        "active",
        "candidate",
        "conflicting",
        "missing",
        "other",
        "rejected",
        "superseded",
        "transition",
        "unknown",
    },
    "shelf": {"errata", "missing", "other", "toolbook", "xingce", "zhiyi"},
    "taint": {
        "instruction_like",
        "missing",
        "other",
        "trusted",
        "unknown",
        "untrusted_content",
    },
    "rule_trace": RULE_TRACES | {"other"},
    "literal_family": {
        "explicit_end",
        "explicit_event",
        "instruction",
        "preference_domain",
        "procedure_action",
        "unknown",
        "update",
    },
    "source_system_bucket": KNOWN_SOURCE_SYSTEMS | {"mixed_or_unknown", "other"},
    "language_bucket": {"en_or_other", "zh"},
    "length_band": {"long_gt_2048", "medium_257_2048", "short_le_256"},
}

RECORD_SUBSET_NAMES = (
    "engine_ambiguity_flagged",
    "actual_model_calls",
    "conservative_review_required",
    "review_or_unprocessable",
    "with_literal_family_hit",
    "summary_detail_overlap",
    "zero_candidate",
    "observed_at_fallback",
    "recorded_at_legacy_naive_utc",
    "preference_source_triggered",
)
CANDIDATE_PARTITION_NAMES = (
    "default_claim_only",
    "default_claim_plus_intra_record_relationship",
    "lexical_semantic_or_safety",
)
CANDIDATE_DISTRIBUTION_NAMES = (
    "literal_family",
    "rule_trace",
    "semantic_type",
    "state_role",
    "shelf",
    "taint",
)
CANDIDATE_DISTRIBUTION_ALIAS_NAMES = (
    "engine_ambiguity_flagged",
    "conservative_review_required",
    "with_literal_family_hit",
    "default_claim_active_trusted",
    "preference_source_triggered",
)
CANDIDATE_RECORD_ALIAS_NAMES = (
    "engine_ambiguity_flagged",
    "actual_model_calls",
    "with_literal_family_hit",
    "preference_source_triggered",
)


class ShadowAuditError(RuntimeError):
    """Stable fail-closed error for cutoff and evidence violations."""


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _measurement_identity_payload(
    provenance: Dict[str, Any],
    metrics: Dict[str, Any],
    holdout_manifest_sha256: str,
) -> Dict[str, Any]:
    return {
        "contract": CONTRACT,
        "provenance": provenance,
        "metrics": metrics,
        "holdout_manifest_sha256": holdout_manifest_sha256,
        "quality_status": "not_measured",
        "decision": "NO_GO_PRODUCTION_SHADOW",
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hmac_hex(key: bytes, *values: object) -> str:
    digest = hmac.new(key, digestmod=hashlib.sha256)
    for value in values:
        encoded = str(value).encode("utf-8", errors="replace")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _valid_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _valid_commit(value: object) -> bool:
    text = str(value or "")
    return 7 <= len(text) <= 64 and all(char in "0123456789abcdef" for char in text)


def _valid_datetime(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _normalized_recorded_at(value: object) -> Tuple[str, str]:
    text = str(value or "").strip()
    if _valid_datetime(text):
        return text, "explicit_timezone"
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "", "invalid"
    # p2_extract writes this legacy shape from datetime.now(timezone.utc).
    return parsed.replace(tzinfo=timezone.utc).isoformat(), "legacy_naive_utc"


def _rate(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _prefix_facts_from_handle(handle: Any, limit: int) -> Dict[str, Any]:
    if limit < 0:
        raise ShadowAuditError("cutoff_bytes_invalid")
    handle.seek(0)
    digest = hashlib.sha256()
    consumed = 0
    newline_count = 0
    last_newline_end = 0
    while consumed < limit:
        chunk = handle.read(min(1024 * 1024, limit - consumed))
        if not chunk:
            raise ShadowAuditError("file_shorter_than_declared_cutoff")
        digest.update(chunk)
        base = consumed
        newline_count += chunk.count(b"\n")
        last = chunk.rfind(b"\n")
        if last >= 0:
            last_newline_end = base + last + 1
        consumed += len(chunk)
    return {
        "prefix_sha256": digest.hexdigest(),
        "newline_count": newline_count,
        "complete_prefix_bytes": last_newline_end,
        "trailing_partial_bytes": max(0, limit - last_newline_end),
    }


def _capture_file(path: Path) -> Dict[str, Any]:
    for _attempt in range(3):
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            facts = _prefix_facts_from_handle(handle, before.st_size)
            after = os.fstat(handle.fileno())
        stable = (
            before.st_dev == after.st_dev
            and before.st_ino == after.st_ino
            and before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns
            and before.st_ctime_ns == after.st_ctime_ns
        )
        if stable:
            return {
                "exists": True,
                "cutoff_bytes": before.st_size,
                "mtime_ns_at_cutoff": before.st_mtime_ns,
                "ctime_ns_at_cutoff": before.st_ctime_ns,
                "device_at_cutoff": before.st_dev,
                "inode_at_cutoff": before.st_ino,
                **facts,
            }
    raise ShadowAuditError("source_changed_during_cutoff_capture")


def _cutoff_identity_payload(cutoff: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "contract": cutoff.get("contract"),
        "captured_at": cutoff.get("captured_at"),
        "max_jsonl_line_bytes": cutoff.get("max_jsonl_line_bytes"),
        "files": cutoff.get("files"),
    }


def capture_cutoff(runtime_root: Path) -> Dict[str, Any]:
    runtime_root = Path(runtime_root)
    files: List[Dict[str, Any]] = []
    for kind, relative in sorted(RECORD_PATHS.items()):
        path = runtime_root / relative
        if not path.is_file():
            files.append({
                "kind": kind,
                "exists": False,
                "cutoff_bytes": 0,
                "complete_prefix_bytes": 0,
                "trailing_partial_bytes": 0,
                "newline_count": 0,
                "prefix_sha256": None,
                "mtime_ns_at_cutoff": None,
                "ctime_ns_at_cutoff": None,
                "device_at_cutoff": None,
                "inode_at_cutoff": None,
            })
            continue
        files.append({"kind": kind, **_capture_file(path)})
    cutoff = {
        "contract": CUTOFF_CONTRACT,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_jsonl_line_bytes": MAX_JSONL_LINE_BYTES,
        "files": files,
        "paths_emitted": False,
        "read_only": True,
        "write_performed": False,
    }
    cutoff["cutoff_identity_sha256"] = sha256_json(_cutoff_identity_payload(cutoff))
    return cutoff


def validate_cutoff(cutoff: Dict[str, Any]) -> None:
    if not isinstance(cutoff, dict) or cutoff.get("contract") != CUTOFF_CONTRACT:
        raise ShadowAuditError("cutoff_contract_invalid")
    if not _valid_datetime(cutoff.get("captured_at")):
        raise ShadowAuditError("cutoff_captured_at_invalid")
    if cutoff.get("max_jsonl_line_bytes") != MAX_JSONL_LINE_BYTES:
        raise ShadowAuditError("cutoff_line_limit_mismatch")
    if cutoff.get("paths_emitted") is not False:
        raise ShadowAuditError("cutoff_paths_policy_invalid")
    files = cutoff.get("files")
    if not isinstance(files, list) or not files:
        raise ShadowAuditError("cutoff_files_missing")
    if sha256_json(_cutoff_identity_payload(cutoff)) != str(
        cutoff.get("cutoff_identity_sha256") or ""
    ):
        raise ShadowAuditError("cutoff_identity_mismatch")
    seen = set()
    for item in files:
        if not isinstance(item, dict):
            raise ShadowAuditError("cutoff_file_invalid")
        if "relative_path" in item or "source_path" in item:
            raise ShadowAuditError("cutoff_path_field_forbidden")
        kind = str(item.get("kind") or "")
        if kind not in RECORD_PATHS or kind in seen:
            raise ShadowAuditError("cutoff_kind_invalid")
        seen.add(kind)
        exists = item.get("exists")
        if exists not in (True, False):
            raise ShadowAuditError("cutoff_exists_invalid")
        numeric_fields = (
            "cutoff_bytes",
            "complete_prefix_bytes",
            "trailing_partial_bytes",
            "newline_count",
        )
        values = {}
        for field in numeric_fields:
            value = item.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ShadowAuditError("cutoff_numeric_field_invalid")
            values[field] = value
        if values["complete_prefix_bytes"] > values["cutoff_bytes"]:
            raise ShadowAuditError("complete_prefix_exceeds_cutoff")
        if (
            values["trailing_partial_bytes"]
            != values["cutoff_bytes"] - values["complete_prefix_bytes"]
        ):
            raise ShadowAuditError("trailing_partial_bytes_inconsistent")
        if values["complete_prefix_bytes"] == 0 and values["newline_count"] != 0:
            raise ShadowAuditError("cutoff_newline_count_inconsistent")
        if values["complete_prefix_bytes"] > 0 and values["newline_count"] <= 0:
            raise ShadowAuditError("cutoff_newline_count_inconsistent")
        if not exists:
            if any(values.values()) or item.get("prefix_sha256") is not None:
                raise ShadowAuditError("missing_cutoff_file_has_content_facts")
            continue
        if not _valid_sha256(item.get("prefix_sha256")):
            raise ShadowAuditError("cutoff_prefix_sha_invalid")
        for field in (
            "mtime_ns_at_cutoff",
            "ctime_ns_at_cutoff",
            "device_at_cutoff",
            "inode_at_cutoff",
        ):
            value = item.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ShadowAuditError("cutoff_generation_field_invalid")
    if seen != set(RECORD_PATHS):
        raise ShadowAuditError("cutoff_kinds_incomplete")


def _iter_cutoff_lines(
    runtime_root: Path, cutoff: Dict[str, Any]
) -> Iterator[Tuple[str, int, Optional[Dict[str, Any]], Optional[str]]]:
    validate_cutoff(cutoff)
    for item in cutoff["files"]:
        kind = str(item["kind"])
        if item.get("exists") is not True:
            raise ShadowAuditError("source_file_missing_at_cutoff")
        path = Path(runtime_root) / RECORD_PATHS[kind]
        try:
            handle = path.open("rb")
        except FileNotFoundError as exc:
            raise ShadowAuditError("source_file_missing_after_cutoff") from exc
        with handle:
            before = os.fstat(handle.fileno())
            if (
                before.st_dev != item.get("device_at_cutoff")
                or before.st_ino != item.get("inode_at_cutoff")
            ):
                raise ShadowAuditError("source_generation_changed_after_cutoff")
            cutoff_bytes = int(item["cutoff_bytes"])
            complete_bytes = int(item["complete_prefix_bytes"])
            if before.st_size < cutoff_bytes:
                raise ShadowAuditError("source_file_regressed_after_cutoff")
            expected = {
                "prefix_sha256": item.get("prefix_sha256"),
                "newline_count": item.get("newline_count"),
                "complete_prefix_bytes": complete_bytes,
                "trailing_partial_bytes": item.get("trailing_partial_bytes"),
            }
            handle.seek(0)
            digest = hashlib.sha256()
            consumed = 0
            newline_count = 0
            last_newline_end = 0

            def account(chunk: bytes) -> None:
                nonlocal consumed, newline_count, last_newline_end
                digest.update(chunk)
                base = consumed
                newline_count += chunk.count(b"\n")
                last = chunk.rfind(b"\n")
                if last >= 0:
                    last_newline_end = base + last + 1
                consumed += len(chunk)

            line_number = 0
            while consumed < complete_bytes:
                remaining = complete_bytes - consumed
                raw = handle.readline(min(remaining, MAX_JSONL_LINE_BYTES + 1))
                if not raw:
                    break
                account(raw)
                line_number += 1
                if len(raw) > MAX_JSONL_LINE_BYTES:
                    if not raw.endswith(b"\n"):
                        while consumed < complete_bytes:
                            chunk = handle.readline(
                                min(1024 * 1024, complete_bytes - consumed)
                            )
                            if not chunk:
                                break
                            account(chunk)
                            if chunk.endswith(b"\n"):
                                break
                    yield kind, line_number, None, "jsonl_line_too_large"
                    continue
                if not raw.endswith(b"\n"):
                    yield kind, line_number, None, "partial_line_inside_complete_prefix"
                    break
                try:
                    decoded = raw.decode("utf-8")
                except UnicodeDecodeError:
                    yield kind, line_number, None, "jsonl_utf8_decode_error"
                    continue
                try:
                    record = json.loads(decoded)
                except json.JSONDecodeError:
                    yield kind, line_number, None, "jsonl_parse_error"
                    continue
                if not isinstance(record, dict):
                    yield kind, line_number, None, "jsonl_record_not_object"
                    continue
                yield kind, line_number, record, None
            if consumed != complete_bytes or handle.tell() != complete_bytes:
                raise ShadowAuditError("complete_prefix_not_fully_consumed")
            while consumed < cutoff_bytes:
                chunk = handle.read(min(1024 * 1024, cutoff_bytes - consumed))
                if not chunk:
                    raise ShadowAuditError("file_shorter_than_declared_cutoff")
                account(chunk)
            current = {
                "prefix_sha256": digest.hexdigest(),
                "newline_count": newline_count,
                "complete_prefix_bytes": last_newline_end,
                "trailing_partial_bytes": cutoff_bytes - last_newline_end,
            }
            if current != expected:
                raise ShadowAuditError("source_prefix_facts_changed_after_cutoff")
            after_fd = os.fstat(handle.fileno())
            try:
                after_path = path.stat()
            except FileNotFoundError as exc:
                raise ShadowAuditError("source_file_deleted_during_audit") from exc
            for observed in (after_fd, after_path):
                if (
                    observed.st_dev != item.get("device_at_cutoff")
                    or observed.st_ino != item.get("inode_at_cutoff")
                ):
                    raise ShadowAuditError("source_generation_changed_during_audit")
                if observed.st_size < cutoff_bytes:
                    raise ShadowAuditError("source_file_regressed_during_audit")


def _parse_source_refs(value: object) -> List[Dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    values = value if isinstance(value, list) else [value]
    if not values or any(not isinstance(item, dict) for item in values):
        return []
    refs = list(values)
    for ref in refs:
        if not str(ref.get("source_system") or "").strip():
            return []
        if not any(
            ref.get(key)
            for key in (
                "source_path",
                "ref_path",
                "artifact_id",
                "library_id",
                "evidence_ref",
            )
        ):
            return []
    return refs


def _text_projection(record: Dict[str, Any]) -> Dict[str, Any]:
    summary = str(record.get("summary") or "").strip()
    detail = str(record.get("detail") or "").strip()
    raw = "\n".join(value for value in (summary, detail) if value)
    left = summary.casefold()
    right = detail.casefold()
    mode = "no_overlap"
    if left and right and left == right:
        text = summary
        mode = "exact_overlap_deduplicated"
    elif left and right and left in right:
        text = detail
        mode = "summary_contained_in_detail_deduplicated"
    elif left and right and right in left:
        text = summary
        mode = "detail_contained_in_summary_deduplicated"
    else:
        text = raw
    return {
        "text": text,
        "raw_text": raw,
        "overlap_mode": mode,
        "raw_sentence_count": len(candidate_rules._sentence_segments(raw)),
        "deduplicated_sentence_count": len(candidate_rules._sentence_segments(text)),
    }


def _language_bucket(text: str) -> str:
    return "zh" if any("\u4e00" <= char <= "\u9fff" for char in text) else "en_or_other"


def _length_band(text: str) -> str:
    size = len(text)
    if size <= 256:
        return "short_le_256"
    if size <= 2048:
        return "medium_257_2048"
    return "long_gt_2048"


def _source_system_bucket(refs: Iterable[Dict[str, Any]]) -> str:
    systems = sorted({str(ref.get("source_system") or "").strip().casefold() for ref in refs})
    if len(systems) != 1:
        return "mixed_or_unknown"
    return systems[0] if systems[0] in KNOWN_SOURCE_SYSTEMS else "other"


def _observed_at(refs: Iterable[Dict[str, Any]], fallback: str) -> Tuple[str, bool]:
    values = [str(ref.get("captured_at") or "").strip() for ref in refs]
    valid = [value for value in values if _valid_datetime(value)]
    return (max(valid), False) if valid else (fallback, True)


def _literal_family_hits(text: str) -> List[str]:
    normalized = candidate_rules._normalized_text(text)
    hits = []
    if candidate_rules._contains_any(normalized, candidate_rules._PREFERENCE_DOMAIN_PATTERNS):
        hits.append("preference_domain")
    if candidate_rules._contains_any(normalized, candidate_rules._PROCEDURE_ACTION_PATTERNS):
        hits.append("procedure_action")
    if candidate_rules._instruction_like(normalized):
        hits.append("instruction")
    if candidate_rules._unknown_statement(normalized):
        hits.append("unknown")
    if candidate_rules._has_update_cue(normalized):
        hits.append("update")
    if candidate_rules._has_explicit_end(normalized):
        hits.append("explicit_end")
    # This family is intentionally narrower than the extractor's composite
    # explicit-event helper so the public 55/90 leakage anchor cannot drift.
    if candidate_rules._contains_any(normalized, candidate_rules._EXPLICIT_EVENT_PATTERNS):
        hits.append("explicit_event")
    return hits


def _projection_span_exact(source_text: str, candidate: Dict[str, Any]) -> bool:
    span = candidate.get("source_span")
    if not isinstance(span, dict):
        return False
    try:
        start = int(span.get("byte_start"))
        end = int(span.get("byte_end"))
    except (TypeError, ValueError):
        return False
    source_bytes = source_text.encode("utf-8")
    expected = str(span.get("text") or "").encode("utf-8")
    return 0 <= start < end <= len(source_bytes) and source_bytes[start:end] == expected


def _safe_distribution(
    counter: Counter,
    *,
    name: str,
    privacy_k: int,
) -> Dict[str, Any]:
    allowed = ALLOWED_DISTRIBUTION_LABELS[name]
    clean = Counter()
    for raw_label, count in counter.items():
        label = str(raw_label)
        clean[label if label in allowed else "other"] += int(count)
    nonzero = {label: count for label, count in clean.items() if count > 0}
    if any(count < privacy_k for count in nonzero.values()):
        return {
            "status": "withheld_due_to_small_cells",
            "k": privacy_k,
            "counts": {},
        }
    return {
        "status": "published",
        "k": privacy_k,
        "counts": dict(sorted(nonzero.items())),
    }


def _safe_subset_metric(
    numerator: int, denominator: int, *, privacy_k: int
) -> Dict[str, Any]:
    complement = denominator - numerator
    if denominator < 0 or numerator < 0 or complement < 0:
        raise ShadowAuditError("subset_metric_denominator_invalid")
    if any(0 < value < privacy_k for value in (numerator, complement)):
        return {
            "status": "withheld_due_to_small_subset_or_complement",
            "count": None,
            "rate": None,
            "denominator": denominator,
        }
    return {
        "status": "published",
        "count": numerator,
        "rate": _rate(numerator, denominator),
        "denominator": denominator,
    }


def _withheld_subset_metric(denominator: int) -> Dict[str, Any]:
    return {
        "status": "withheld_due_to_small_subset_or_complement",
        "count": None,
        "rate": None,
        "denominator": denominator,
    }


def _dependency_withheld_subset_metric() -> Dict[str, Any]:
    return {
        "status": "withheld_due_to_dependency_closure",
        "count": None,
        "rate": None,
        "denominator": None,
    }


def _withheld_distribution(privacy_k: int) -> Dict[str, Any]:
    return {
        "status": "withheld_due_to_small_cells",
        "k": privacy_k,
        "counts": {},
    }


def _apply_known_cross_marginal_privacy(
    metrics: Dict[str, Any],
    *,
    privacy_k: int,
    relation_values: Dict[str, int],
) -> None:
    expected = {
        "candidate_conservative_overlap_memberships",
        "candidate_conservative_minus_ambiguity",
        "candidate_conservative_minus_default_claim",
        "candidate_conservative_minus_preference_source",
        "default_trace_lexical_memberships",
        "default_trace_not_active_trusted",
        "default_trace_extra_over_record_default_only",
        "default_active_trusted_frechet_lower_slack",
        "candidate_ambiguity_extra_memberships",
        "candidate_conservative_extra_memberships",
        "candidate_literal_extra_memberships",
        "candidate_preference_source_extra_memberships",
        "candidate_record_extra_memberships",
        "conservative_extra_minus_ambiguity_extra_memberships",
        "conservative_extra_minus_preference_source_extra_memberships",
        "extra_non_conservative_candidate_memberships",
        "extra_non_literal_candidate_memberships",
        "lexical_partition_minus_candidate_ambiguity",
        "literal_family_extra_memberships",
        "literal_union_minus_explicit_end",
        "literal_union_minus_explicit_event",
        "literal_union_minus_instruction",
        "literal_union_minus_preference_domain",
        "literal_union_minus_procedure_action",
        "literal_union_minus_unknown",
        "literal_union_minus_update",
        "newer_update_supersedes_minus_active",
        "preference_source_domain_or_instruction_overlap",
        "record_conservative_minus_ambiguity",
        "record_conservative_minus_preference_source",
        "record_conservative_minus_zero_candidate",
        "record_default_only_conservative",
        "record_nonzero_conservative_minus_ambiguity",
        "record_nonzero_conservative_minus_preference_source",
        "record_with_candidates_minus_literal",
        "relationship_trace_extra_memberships",
        "semantic_claim_minus_instruction_literal",
        "semantic_event_minus_candidate_ambiguity",
        "literal_explicit_end_extra_memberships",
        "state_active_minus_default_claim_active_trusted",
        "taint_trusted_minus_default_claim_active_trusted",
    }
    if set(relation_values) != expected:
        raise ShadowAuditError("cross_marginal_relation_registry_invalid")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in relation_values.values()
    ):
        raise ShadowAuditError("cross_marginal_subset_invariant_failed")

    candidates = metrics["candidates"]
    records = metrics["records"]
    distributions = metrics["distributions"]
    candidate_total = int(candidates["total"])

    if 0 < relation_values["candidate_conservative_overlap_memberships"] < privacy_k:
        candidates["conservative_review_required"] = _withheld_subset_metric(
            candidate_total
        )
    if any(
        0 < relation_values[name] < privacy_k
        for name in (
            "candidate_conservative_minus_ambiguity",
            "candidate_conservative_minus_default_claim",
            "candidate_conservative_minus_preference_source",
        )
    ):
        candidates["conservative_review_required"] = _withheld_subset_metric(
            candidate_total
        )
    if 0 < relation_values["default_trace_lexical_memberships"] < privacy_k:
        distributions["rule_trace"] = _withheld_distribution(privacy_k)
    if 0 < relation_values["default_trace_not_active_trusted"] < privacy_k:
        candidates["default_claim_active_trusted"] = _withheld_subset_metric(
            candidate_total
        )
    if 0 < relation_values["default_active_trusted_frechet_lower_slack"] < privacy_k:
        candidates["default_claim_active_trusted"] = _withheld_subset_metric(
            candidate_total
        )
    if 0 < relation_values["default_trace_extra_over_record_default_only"] < privacy_k:
        distributions["rule_trace"] = _withheld_distribution(privacy_k)
    if 0 < relation_values["candidate_ambiguity_extra_memberships"] < privacy_k:
        records["engine_ambiguity_flagged"] = _withheld_subset_metric(
            int(records["engine_ambiguity_flagged"]["denominator"])
        )
    if 0 < relation_values["candidate_conservative_extra_memberships"] < privacy_k:
        candidates["conservative_review_required"] = _withheld_subset_metric(
            candidate_total
        )
    if 0 < relation_values["candidate_literal_extra_memberships"] < privacy_k:
        records["with_literal_family_hit"] = _withheld_subset_metric(
            int(records["with_literal_family_hit"]["denominator"])
        )
    if (
        0
        < relation_values["candidate_preference_source_extra_memberships"]
        < privacy_k
    ):
        candidates["preference_source_triggered"] = _withheld_subset_metric(
            candidate_total
        )
    if 0 < relation_values["candidate_record_extra_memberships"] < privacy_k:
        records["zero_candidate"] = _withheld_subset_metric(
            int(records["zero_candidate"]["denominator"])
        )
    if any(
        0 < relation_values[name] < privacy_k
        for name in (
            "conservative_extra_minus_ambiguity_extra_memberships",
            "conservative_extra_minus_preference_source_extra_memberships",
        )
    ):
        records["conservative_review_required"] = _withheld_subset_metric(
            int(records["conservative_review_required"]["denominator"])
        )
    if 0 < relation_values["record_default_only_conservative"] < privacy_k:
        records["conservative_review_required"] = _withheld_subset_metric(
            int(records["conservative_review_required"]["denominator"])
        )
    if (
        0
        < relation_values["extra_non_conservative_candidate_memberships"]
        < privacy_k
    ):
        records["conservative_review_required"] = _withheld_subset_metric(
            int(records["conservative_review_required"]["denominator"])
        )
    if 0 < relation_values["extra_non_literal_candidate_memberships"] < privacy_k:
        records["with_literal_family_hit"] = _withheld_subset_metric(
            int(records["with_literal_family_hit"]["denominator"])
        )
    if (
        0
        < relation_values["lexical_partition_minus_candidate_ambiguity"]
        < privacy_k
    ):
        candidates["lexical_semantic_or_safety"] = _withheld_subset_metric(
            candidate_total
        )
    if 0 < relation_values["literal_family_extra_memberships"] < privacy_k:
        distributions["literal_family"] = _withheld_distribution(privacy_k)
    if any(
        0 < relation_values[name] < privacy_k
        for name in (
            "newer_update_supersedes_minus_active",
            "relationship_trace_extra_memberships",
        )
    ):
        distributions["rule_trace"] = _withheld_distribution(privacy_k)
    if any(
        0 < relation_values[name] < privacy_k
        for name in (
            "literal_union_minus_explicit_end",
            "literal_union_minus_explicit_event",
            "literal_union_minus_instruction",
            "literal_union_minus_preference_domain",
            "literal_union_minus_procedure_action",
            "literal_union_minus_unknown",
            "literal_union_minus_update",
        )
    ):
        candidates["with_literal_family_hit"] = _withheld_subset_metric(
            candidate_total
        )
    if (
        0
        < relation_values["preference_source_domain_or_instruction_overlap"]
        < privacy_k
    ):
        distributions["literal_family"] = _withheld_distribution(privacy_k)
    if any(
        0 < relation_values[name] < privacy_k
        for name in (
            "record_conservative_minus_ambiguity",
            "record_conservative_minus_preference_source",
            "record_conservative_minus_zero_candidate",
            "record_nonzero_conservative_minus_ambiguity",
            "record_nonzero_conservative_minus_preference_source",
        )
    ):
        records["conservative_review_required"] = _withheld_subset_metric(
            int(records["conservative_review_required"]["denominator"])
        )
    if 0 < relation_values["record_with_candidates_minus_literal"] < privacy_k:
        records["with_literal_family_hit"] = _withheld_subset_metric(
            int(records["with_literal_family_hit"]["denominator"])
        )
    if any(
        0 < relation_values[name] < privacy_k
        for name in (
            "semantic_claim_minus_instruction_literal",
            "semantic_event_minus_candidate_ambiguity",
            "literal_explicit_end_extra_memberships",
        )
    ):
        distributions["semantic_type"] = _withheld_distribution(privacy_k)
    if any(
        0 < relation_values[name] < privacy_k
        for name in (
            "state_active_minus_default_claim_active_trusted",
            "taint_trusted_minus_default_claim_active_trusted",
        )
    ):
        candidates["default_claim_active_trusted"] = _withheld_subset_metric(
            candidate_total
        )


def _safe_kind_metrics(values: Counter, *, privacy_k: int) -> Dict[str, Any]:
    named = {
        "seen": int(values["seen"]),
        "processed": int(values["processed"]),
        "skipped": int(values["skipped"]),
        "error": int(values["error"]),
    }
    has_small_cell = any(0 < count < privacy_k for count in named.values())
    return {
        "status": (
            "withheld_due_to_small_cells" if has_small_cell else "published"
        ),
        **{
            key: (None if has_small_cell else count)
            for key, count in named.items()
        },
        "conservation_pass": (
            values["seen"]
            == values["processed"] + values["skipped"] + values["error"]
        ),
    }


def _withheld_kind_metrics(value: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "withheld_due_to_small_cells",
        "seen": None,
        "processed": None,
        "skipped": None,
        "error": None,
        "conservation_pass": bool(value["conservation_pass"]),
    }


def _apply_candidate_record_alias_privacy(
    records: Dict[str, Any],
    candidates: Dict[str, Any],
    *,
    outcome_visible: bool,
) -> None:
    for name in CANDIDATE_RECORD_ALIAS_NAMES:
        if (
            candidates[name]["status"] == "published"
            and records[name]["status"] == "published"
        ):
            continue
        candidates[name] = _withheld_subset_metric(int(candidates["total"]))
        if outcome_visible:
            records[name] = _withheld_subset_metric(
                int(records[name]["denominator"])
            )
        else:
            records[name] = _dependency_withheld_subset_metric()


def _apply_dependency_privacy_closure(
    metrics: Dict[str, Any], *, privacy_k: int
) -> None:
    records = metrics["records"]
    candidates = metrics["candidates"]
    distributions = metrics["distributions"]

    if any(
        value["status"] != "published" for value in records["by_kind"].values()
    ):
        records["by_kind"] = {
            kind: _withheld_kind_metrics(value)
            for kind, value in records["by_kind"].items()
        }

    outcome_visible = records["processing_outcome"]["status"] == "published"
    if not outcome_visible:
        records["by_kind"] = {
            kind: _withheld_kind_metrics(value)
            for kind, value in records["by_kind"].items()
        }
        records["skip_reasons"] = _withheld_distribution(privacy_k)
        records["error_reasons"] = _withheld_distribution(privacy_k)
        for name in RECORD_SUBSET_NAMES:
            records[name] = _dependency_withheld_subset_metric()
        for name in (
            "source_system_bucket",
            "language_bucket",
            "length_band",
        ):
            distributions[name] = _withheld_distribution(privacy_k)

    _apply_candidate_record_alias_privacy(
        records, candidates, outcome_visible=outcome_visible
    )

    if any(
        candidates[name]["status"] != "published"
        for name in CANDIDATE_PARTITION_NAMES
    ):
        for name in CANDIDATE_PARTITION_NAMES:
            candidates[name] = _withheld_subset_metric(int(candidates["total"]))

    if any(
        distributions[name]["status"] != "published"
        for name in CANDIDATE_DISTRIBUTION_NAMES
    ) or any(
        candidates[name]["status"] != "published"
        for name in CANDIDATE_DISTRIBUTION_ALIAS_NAMES
    ):
        for name in CANDIDATE_DISTRIBUTION_NAMES:
            distributions[name] = _withheld_distribution(privacy_k)

    def hide_candidate_conservative_algebra() -> None:
        for name in (
            "conservative_review_required",
            "engine_ambiguity_flagged",
            "preference_source_triggered",
            *CANDIDATE_PARTITION_NAMES,
        ):
            candidates[name] = _withheld_subset_metric(int(candidates["total"]))
        for name in CANDIDATE_DISTRIBUTION_NAMES:
            distributions[name] = _withheld_distribution(privacy_k)

    candidate_conservative_algebra = (
        candidates["conservative_review_required"],
        candidates["engine_ambiguity_flagged"],
        candidates["preference_source_triggered"],
        *(candidates[name] for name in CANDIDATE_PARTITION_NAMES),
        distributions["rule_trace"],
    )
    if any(
        value["status"] != "published"
        for value in candidate_conservative_algebra
    ):
        hide_candidate_conservative_algebra()

    conservative_group = (
        candidates["conservative_review_required"],
        records["conservative_review_required"],
        records["review_or_unprocessable"],
        records["zero_candidate"],
    )
    if any(value["status"] != "published" for value in conservative_group):
        candidates["conservative_review_required"] = _withheld_subset_metric(
            int(candidates["total"])
        )
        if outcome_visible:
            records["conservative_review_required"] = _withheld_subset_metric(
                int(records["conservative_review_required"]["denominator"])
            )
            records["review_or_unprocessable"] = _withheld_subset_metric(
                int(records["review_or_unprocessable"]["denominator"])
            )
            records["zero_candidate"] = _withheld_subset_metric(
                int(records["zero_candidate"]["denominator"])
            )
        else:
            records["conservative_review_required"] = (
                _dependency_withheld_subset_metric()
            )
            records["review_or_unprocessable"] = (
                _dependency_withheld_subset_metric()
            )
            records["zero_candidate"] = _dependency_withheld_subset_metric()
    if candidates["conservative_review_required"]["status"] != "published":
        hide_candidate_conservative_algebra()
    _apply_candidate_record_alias_privacy(
        records, candidates, outcome_visible=outcome_visible
    )

    mechanical = metrics["mechanical_projection_checks"]
    if any(
        mechanical[name]["status"] != "published"
        for name in (
            "projection_span_exactness_failures",
            "source_ref_digest_echo_failures",
        )
    ):
        mechanical["all_pass"] = None
    safety = metrics["safety_invariants"]
    if safety["activation_denial_violations"]["status"] != "published":
        safety["all_pass"] = None

    sentences = metrics["sentences"]
    if sentences["duplicate_projection_sentences_avoided"]["status"] != "published":
        sentences["raw_summary_plus_detail_count"] = None
        sentences["deduplicated_projection_count"] = None
        sentences["duplicate_projection_sentences_avoided"] = (
            _dependency_withheld_subset_metric()
        )


def _holdout_manifest(
    cutoff_identity: str,
    descriptors: List[Dict[str, str]],
    *,
    key: bytes,
    seed: str,
    exact_count: int,
) -> Dict[str, Any]:
    groups: Dict[Tuple[str, str, str, str], List[Dict[str, str]]] = defaultdict(list)
    for item in descriptors:
        group = (
            item["kind"],
            item["source_system_bucket"],
            item["language_bucket"],
            item["length_band"],
        )
        groups[group].append(item)
    for items in groups.values():
        items.sort(key=lambda item: _hmac_hex(key, "selection", seed, item["opaque_record_id"]))

    selected: List[Dict[str, str]] = []
    cursor = 0
    ordered_groups = sorted(
        groups,
        key=lambda group: _hmac_hex(key, "group", seed, "|".join(group)),
    )
    while len(selected) < exact_count:
        progressed = False
        for group in ordered_groups:
            items = groups[group]
            if cursor < len(items):
                selected.append(items[cursor])
                progressed = True
                if len(selected) >= exact_count:
                    break
        if not progressed:
            break
        cursor += 1

    records = [{"opaque_record_id": item["opaque_record_id"]} for item in selected]
    value = {
        "contract": HOLDOUT_CONTRACT,
        "source_cutoff_identity_sha256": cutoff_identity,
        "selection_algorithm": SELECTION_ALGORITHM,
        "selection_seed_sha256": hashlib.sha256(seed.encode("ascii")).hexdigest(),
        "exact_count": exact_count,
        "holdout_count": len(records),
        "selection_complete": len(records) == exact_count,
        "records": records,
        "contains_source_text": False,
        "contains_text_hashes": False,
        "contains_answer_labels": False,
        "contains_private_paths_or_native_ids": False,
        "opaque_id_scheme": "keyed_hmac_sha256",
        "independent_labels_status": "not_measured",
        "local_only_not_shared_with_rule_author_or_antagonist": True,
        "read_only": True,
        "write_performed": False,
    }
    value["holdout_manifest_sha256"] = sha256_json(value)
    return value


def _code_identity() -> Dict[str, str]:
    tool_path = Path(__file__).resolve()
    extractor_path = Path(candidate_rules.__file__).resolve()
    return {
        "tool_sha256": file_sha256(tool_path),
        "extractor_sha256": file_sha256(extractor_path),
        "extractor_contract": candidate_rules.HYBRID_EXTRACTION_CONTRACT,
    }


def _repository_head(repository_root: Path) -> str:
    git_entry = Path(repository_root) / ".git"
    git_dir = git_entry
    if git_entry.is_file():
        text = git_entry.read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir:"):
            raise ShadowAuditError("git_directory_pointer_invalid")
        git_dir = (git_entry.parent / text.split(":", 1)[1].strip()).resolve()
    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        raise ShadowAuditError("git_head_missing")
    head = head_path.read_text(encoding="utf-8").strip()
    if not head.startswith("ref:"):
        if not _valid_commit(head):
            raise ShadowAuditError("git_head_invalid")
        return head
    ref = head.split(":", 1)[1].strip()
    ref_path = git_dir / ref
    if ref_path.is_file():
        value = ref_path.read_text(encoding="utf-8").strip()
        if not _valid_commit(value):
            raise ShadowAuditError("git_ref_invalid")
        return value
    packed_refs = git_dir / "packed-refs"
    if packed_refs.is_file():
        for line in packed_refs.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith(("#", "^")):
                continue
            value, candidate_ref = line.split(" ", 1)
            if candidate_ref == ref and _valid_commit(value):
                return value
    raise ShadowAuditError("git_ref_missing")


def validate_preregistration(
    preregistration: Dict[str, Any],
    *,
    preregistration_file_sha256: str,
    cutoff: Dict[str, Any],
    cutoff_file_sha256: str,
    holdout_key_file_sha256: str,
    actual_source_commit: str,
) -> Dict[str, Any]:
    if (
        not isinstance(preregistration, dict)
        or preregistration.get("contract") != PREREGISTRATION_CONTRACT
    ):
        raise ShadowAuditError("preregistration_contract_invalid")
    code = _code_identity()
    required = {
        "source_commit": preregistration.get("source_commit"),
        "tool_sha256": preregistration.get("tool_sha256"),
        "extractor_sha256": preregistration.get("extractor_sha256"),
        "extractor_contract": preregistration.get("extractor_contract"),
        "cutoff_file_sha256": preregistration.get("cutoff_file_sha256"),
        "cutoff_identity_sha256": preregistration.get("cutoff_identity_sha256"),
        "holdout_key_file_sha256": preregistration.get("holdout_key_file_sha256"),
        "holdout_exact_count": preregistration.get("holdout_exact_count"),
        "selection_algorithm": preregistration.get("selection_algorithm"),
        "independent_seed": preregistration.get("independent_seed"),
        "privacy_k": preregistration.get("privacy_k"),
        "max_jsonl_line_bytes": preregistration.get("max_jsonl_line_bytes"),
        "rules_frozen": preregistration.get("rules_frozen"),
    }
    if not _valid_commit(required["source_commit"]):
        raise ShadowAuditError("preregistration_source_commit_invalid")
    if required["source_commit"] != actual_source_commit:
        raise ShadowAuditError("preregistration_source_commit_mismatch")
    if required["tool_sha256"] != code["tool_sha256"]:
        raise ShadowAuditError("preregistration_tool_sha_mismatch")
    if required["extractor_sha256"] != code["extractor_sha256"]:
        raise ShadowAuditError("preregistration_extractor_sha_mismatch")
    if required["extractor_contract"] != code["extractor_contract"]:
        raise ShadowAuditError("preregistration_extractor_contract_mismatch")
    if required["cutoff_file_sha256"] != cutoff_file_sha256:
        raise ShadowAuditError("preregistration_cutoff_file_sha_mismatch")
    if required["cutoff_identity_sha256"] != cutoff.get("cutoff_identity_sha256"):
        raise ShadowAuditError("preregistration_cutoff_identity_mismatch")
    if required["holdout_key_file_sha256"] != holdout_key_file_sha256:
        raise ShadowAuditError("preregistration_holdout_key_sha_mismatch")
    if required["holdout_exact_count"] != DEFAULT_HOLDOUT_COUNT:
        raise ShadowAuditError("preregistration_holdout_count_invalid")
    if required["selection_algorithm"] != SELECTION_ALGORITHM:
        raise ShadowAuditError("preregistration_selection_algorithm_invalid")
    seed = str(required["independent_seed"] or "")
    if len(seed) != 64 or any(char not in "0123456789abcdef" for char in seed):
        raise ShadowAuditError("preregistration_seed_invalid")
    if required["privacy_k"] != DEFAULT_PRIVACY_K:
        raise ShadowAuditError("preregistration_privacy_k_invalid")
    if required["max_jsonl_line_bytes"] != MAX_JSONL_LINE_BYTES:
        raise ShadowAuditError("preregistration_line_limit_invalid")
    if required["rules_frozen"] is not True:
        raise ShadowAuditError("preregistration_rules_not_frozen")
    if not _valid_sha256(preregistration_file_sha256):
        raise ShadowAuditError("preregistration_file_sha_invalid")
    return {
        "source_commit": str(required["source_commit"]),
        **code,
        "cutoff_file_sha256": cutoff_file_sha256,
        "cutoff_identity_sha256": str(cutoff["cutoff_identity_sha256"]),
        "preregistration_file_sha256": preregistration_file_sha256,
        "holdout_key_file_sha256": holdout_key_file_sha256,
        "holdout_exact_count": DEFAULT_HOLDOUT_COUNT,
        "selection_algorithm": SELECTION_ALGORITHM,
        "selection_seed_sha256": hashlib.sha256(seed.encode("ascii")).hexdigest(),
        "privacy_k": DEFAULT_PRIVACY_K,
        "max_jsonl_line_bytes": MAX_JSONL_LINE_BYTES,
        "rules_frozen": True,
    }


def run_audit(
    runtime_root: Path,
    cutoff: Dict[str, Any],
    *,
    holdout_key: bytes,
    selection_seed: str,
    holdout_count: int,
    provenance: Dict[str, Any],
    privacy_k: int = DEFAULT_PRIVACY_K,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    validate_cutoff(cutoff)
    if len(holdout_key) < 32:
        raise ShadowAuditError("holdout_key_too_short")
    if holdout_count < 1:
        raise ShadowAuditError("holdout_count_invalid")
    if privacy_k < 1:
        raise ShadowAuditError("privacy_k_invalid")

    kinds: Dict[str, Counter] = {kind: Counter() for kind in RECORD_PATHS}
    skip_reasons = Counter()
    error_reasons = Counter()
    candidate_counts = Counter()
    semantic_counts = Counter()
    state_counts = Counter()
    shelf_counts = Counter()
    taint_counts = Counter()
    trace_counts = Counter()
    literal_counts = Counter()
    source_system_counts = Counter()
    language_counts = Counter()
    length_counts = Counter()
    holdout_descriptors: List[Dict[str, str]] = []

    records_processed = 0
    records_engine_ambiguity_flagged = 0
    records_conservative_review_required = 0
    records_with_literal_hit = 0
    records_overlap = 0
    records_observed_at_fallback = 0
    records_legacy_naive_utc = 0
    records_preference_source_triggered = 0
    records_zero_candidates = 0
    candidates_preference_source_triggered = 0
    candidates_ambiguous = 0
    candidates_conservative_review_required = 0
    candidates_with_literal_hit = 0
    default_claim_active_trusted = 0
    projection_span_failures = 0
    source_ref_echo_failures = 0
    activation_violations = 0
    raw_sentence_count = 0
    deduplicated_sentence_count = 0

    for kind, line_number, record, line_error in _iter_cutoff_lines(runtime_root, cutoff):
        kinds[kind]["seen"] += 1
        if line_error:
            if line_error not in ERROR_REASONS:
                raise ShadowAuditError("unexpected_line_error")
            kinds[kind]["error"] += 1
            kinds[kind]["review_or_unprocessable"] += 1
            error_reasons[line_error] += 1
            continue
        assert record is not None
        refs = _parse_source_refs(record.get("source_refs"))
        if not refs:
            kinds[kind]["skipped"] += 1
            kinds[kind]["review_or_unprocessable"] += 1
            skip_reasons["source_refs_invalid"] += 1
            continue
        projection = _text_projection(record)
        text = str(projection["text"])
        if not text:
            kinds[kind]["skipped"] += 1
            kinds[kind]["review_or_unprocessable"] += 1
            skip_reasons["source_text_empty"] += 1
            continue
        recorded_at, recorded_at_mode = _normalized_recorded_at(record.get("extracted_at"))
        if not recorded_at:
            kinds[kind]["skipped"] += 1
            kinds[kind]["review_or_unprocessable"] += 1
            skip_reasons["recorded_at_invalid"] += 1
            continue
        observed_at, used_fallback = _observed_at(refs, recorded_at)
        if not _valid_datetime(observed_at):
            kinds[kind]["skipped"] += 1
            kinds[kind]["review_or_unprocessable"] += 1
            skip_reasons["observed_at_invalid"] += 1
            continue

        native_id = str(record.get("exp_id") or "")
        record_token = _hmac_hex(
            holdout_key,
            "record",
            cutoff["cutoff_identity_sha256"],
            kind,
            line_number,
            native_id,
            text,
        )
        opaque_record_id = "record-" + record_token[:32]
        opaque_source_ref = "source-" + _hmac_hex(
            holdout_key, "source-ref", canonical_json(refs)
        )[:32]
        source_system = _source_system_bucket(refs)
        language = _language_bucket(text)
        length = _length_band(text)
        preference_source_triggered = candidate_rules._preference_source(
            candidate_rules._normalized_text(text)
        )
        try:
            plan = candidate_rules.build_hybrid_plan({
                "recorded_at": recorded_at,
                "sources": [{
                    "source_ref_id": opaque_source_ref,
                    "observed_at": observed_at,
                    "text": text,
                }],
            })
        except Exception:
            kinds[kind]["error"] += 1
            kinds[kind]["review_or_unprocessable"] += 1
            error_reasons["extractor_error"] += 1
            continue

        candidates = [item for item in plan.get("candidates") or [] if isinstance(item, dict)]
        records_processed += 1
        kinds[kind]["processed"] += 1
        source_system_counts[source_system] += 1
        language_counts[language] += 1
        length_counts[length] += 1
        overlap = projection["overlap_mode"] != "no_overlap"
        records_overlap += int(overlap)
        raw_sentence_count += int(projection["raw_sentence_count"])
        deduplicated_sentence_count += int(projection["deduplicated_sentence_count"])
        records_observed_at_fallback += int(used_fallback)
        records_legacy_naive_utc += int(recorded_at_mode == "legacy_naive_utc")
        records_preference_source_triggered += int(preference_source_triggered)
        candidates_preference_source_triggered += (
            len(candidates) if preference_source_triggered else 0
        )

        record_ambiguous = False
        record_conservative = preference_source_triggered or not candidates
        record_literal = False
        if not candidates:
            records_zero_candidates += 1
            kinds[kind]["zero_candidate"] += 1
        for candidate in candidates:
            candidate_counts["total"] += 1
            semantic_type = str(candidate.get("semantic_type") or "missing")
            semantic_counts[semantic_type] += 1
            state_counts[str(candidate.get("state_role") or "missing")] += 1
            shelf_counts[str(candidate.get("shelf") or "missing")] += 1
            taint_counts[str(candidate.get("taint") or "missing")] += 1
            traces = {str(value) for value in candidate.get("rule_trace") or []}
            trace_counts.update(traces)
            ambiguity = bool(candidate.get("ambiguities"))
            conservative = (
                ambiguity
                or "default_claim_rule" in traces
                or preference_source_triggered
            )
            literal_hits = _literal_family_hits(str(candidate.get("content") or ""))
            literal_counts.update(literal_hits)
            candidates_ambiguous += int(ambiguity)
            candidates_conservative_review_required += int(conservative)
            candidates_with_literal_hit += int(bool(literal_hits))
            record_ambiguous = record_ambiguous or ambiguity
            record_conservative = record_conservative or conservative
            record_literal = record_literal or bool(literal_hits)

            if traces == {"default_claim_rule"}:
                candidate_counts["default_claim_only"] += 1
            elif (
                "default_claim_rule" in traces
                and traces <= ({"default_claim_rule"} | RELATIONSHIP_TRACES)
            ):
                candidate_counts["default_claim_plus_intra_record_relationship"] += 1
            else:
                candidate_counts["lexical_semantic_or_safety"] += 1
            default_claim_active_trusted += int(
                "default_claim_rule" in traces
                and candidate.get("state_role") == "active"
                and candidate.get("taint") == "trusted"
            )
            projection_span_failures += int(
                not _projection_span_exact(str(plan.get("source_text") or ""), candidate)
            )
            candidate_refs = candidate.get("source_refs")
            source_ref_echo_failures += int(
                not isinstance(candidate_refs, list)
                or len(candidate_refs) != 1
                or not isinstance(candidate_refs[0], dict)
                or candidate_refs[0].get("source_system") != "synthetic_public_pilot"
                or candidate_refs[0].get("evidence_ref") != opaque_source_ref
            )
            activation_violations += int(candidate.get("activation_allowed") is not False)

        records_engine_ambiguity_flagged += int(record_ambiguous)
        records_conservative_review_required += int(record_conservative)
        records_with_literal_hit += int(record_literal)
        if record_conservative:
            kinds[kind]["review_or_unprocessable"] += 1
        holdout_descriptors.append({
            "opaque_record_id": opaque_record_id,
            "kind": kind,
            "source_system_bucket": source_system,
            "language_bucket": language,
            "length_band": length,
        })

    records_seen = sum(values["seen"] for values in kinds.values())
    records_skipped = sum(values["skipped"] for values in kinds.values())
    records_error = sum(values["error"] for values in kinds.values())
    candidates_total = int(candidate_counts["total"])
    conservation_by_kind = {
        kind: (
            values["seen"]
            == values["processed"] + values["skipped"] + values["error"]
        )
        for kind, values in kinds.items()
    }
    partial_tail_files = sum(
        int(item.get("trailing_partial_bytes") or 0) > 0 for item in cutoff["files"]
    )
    partial_tail_bytes = sum(
        int(item.get("trailing_partial_bytes") or 0) for item in cutoff["files"]
    )
    holdout = _holdout_manifest(
        str(cutoff["cutoff_identity_sha256"]),
        holdout_descriptors,
        key=holdout_key,
        seed=selection_seed,
        exact_count=holdout_count,
    )
    validate_holdout_manifest(holdout)
    mechanical_ok = projection_span_failures == 0 and source_ref_echo_failures == 0
    safety_ok = activation_violations == 0
    measurement_complete = (
        records_seen > 0
        and records_processed == records_seen
        and records_skipped == 0
        and records_error == 0
        and all(conservation_by_kind.values())
        and partial_tail_files == 0
        and holdout["selection_complete"] is True
    )

    by_kind_counts = Counter({
        kind: int(values["seen"]) for kind, values in kinds.items()
    })
    metrics = {
        "records": {
            "seen": records_seen,
            "processing_outcome": _safe_distribution(
                Counter({
                    "processed": records_processed,
                    "skipped": records_skipped,
                    "error": records_error,
                }),
                name="processing_outcome",
                privacy_k=privacy_k,
            ),
            "by_kind": {
                kind: _safe_kind_metrics(values, privacy_k=privacy_k)
                for kind, values in sorted(kinds.items())
            },
            "skip_reasons": _safe_distribution(
                skip_reasons, name="skip_reason", privacy_k=privacy_k
            ),
            "error_reasons": _safe_distribution(
                error_reasons, name="error_reason", privacy_k=privacy_k
            ),
            "engine_ambiguity_flagged": _safe_subset_metric(
                records_engine_ambiguity_flagged,
                records_processed,
                privacy_k=privacy_k,
            ),
            "actual_model_calls": _safe_subset_metric(
                0, records_processed, privacy_k=privacy_k
            ),
            "conservative_review_required": _safe_subset_metric(
                records_conservative_review_required,
                records_processed,
                privacy_k=privacy_k,
            ),
            "review_or_unprocessable": _safe_subset_metric(
                sum(values["review_or_unprocessable"] for values in kinds.values()),
                records_seen,
                privacy_k=privacy_k,
            ),
            "with_literal_family_hit": _safe_subset_metric(
                records_with_literal_hit,
                records_processed,
                privacy_k=privacy_k,
            ),
            "summary_detail_overlap": _safe_subset_metric(
                records_overlap, records_processed, privacy_k=privacy_k
            ),
            "zero_candidate": _safe_subset_metric(
                records_zero_candidates, records_processed, privacy_k=privacy_k
            ),
            "observed_at_fallback": _safe_subset_metric(
                records_observed_at_fallback,
                records_processed,
                privacy_k=privacy_k,
            ),
            "recorded_at_legacy_naive_utc": _safe_subset_metric(
                records_legacy_naive_utc,
                records_processed,
                privacy_k=privacy_k,
            ),
            "recorded_at_legacy_naive_utc_policy": LEGACY_NAIVE_UTC_POLICY,
            "preference_source_triggered": _safe_subset_metric(
                records_preference_source_triggered,
                records_processed,
                privacy_k=privacy_k,
            ),
        },
        "sentences": {
            "raw_summary_plus_detail_count": raw_sentence_count,
            "deduplicated_projection_count": (
                deduplicated_sentence_count
                if _safe_subset_metric(
                    max(0, raw_sentence_count - deduplicated_sentence_count),
                    raw_sentence_count,
                    privacy_k=privacy_k,
                )["status"]
                == "published"
                else None
            ),
            "duplicate_projection_sentences_avoided": _safe_subset_metric(
                max(0, raw_sentence_count - deduplicated_sentence_count),
                raw_sentence_count,
                privacy_k=privacy_k,
            ),
            "projection_policy": PROJECTION_POLICY,
        },
        "candidates": {
            "total": candidates_total,
            "engine_ambiguity_flagged": _safe_subset_metric(
                candidates_ambiguous, candidates_total, privacy_k=privacy_k
            ),
            "actual_model_calls": _safe_subset_metric(
                0, candidates_total, privacy_k=privacy_k
            ),
            "conservative_review_required": _safe_subset_metric(
                candidates_conservative_review_required,
                candidates_total,
                privacy_k=privacy_k,
            ),
            "with_literal_family_hit": _safe_subset_metric(
                candidates_with_literal_hit,
                candidates_total,
                privacy_k=privacy_k,
            ),
            "default_claim_only": _safe_subset_metric(
                int(candidate_counts["default_claim_only"]),
                candidates_total,
                privacy_k=privacy_k,
            ),
            "default_claim_plus_intra_record_relationship": _safe_subset_metric(
                int(candidate_counts["default_claim_plus_intra_record_relationship"]),
                candidates_total,
                privacy_k=privacy_k,
            ),
            "lexical_semantic_or_safety": _safe_subset_metric(
                int(candidate_counts["lexical_semantic_or_safety"]),
                candidates_total,
                privacy_k=privacy_k,
            ),
            "default_claim_active_trusted": _safe_subset_metric(
                default_claim_active_trusted,
                candidates_total,
                privacy_k=privacy_k,
            ),
            "preference_source_triggered": _safe_subset_metric(
                candidates_preference_source_triggered,
                candidates_total,
                privacy_k=privacy_k,
            ),
        },
        "distributions": {
            "record_kind": _safe_distribution(
                by_kind_counts, name="record_kind", privacy_k=privacy_k
            ),
            "literal_family": _safe_distribution(
                literal_counts, name="literal_family", privacy_k=privacy_k
            ),
            "rule_trace": _safe_distribution(
                trace_counts, name="rule_trace", privacy_k=privacy_k
            ),
            "semantic_type": _safe_distribution(
                semantic_counts, name="semantic_type", privacy_k=privacy_k
            ),
            "state_role": _safe_distribution(
                state_counts, name="state_role", privacy_k=privacy_k
            ),
            "shelf": _safe_distribution(
                shelf_counts, name="shelf", privacy_k=privacy_k
            ),
            "taint": _safe_distribution(
                taint_counts, name="taint", privacy_k=privacy_k
            ),
            "source_system_bucket": _safe_distribution(
                source_system_counts,
                name="source_system_bucket",
                privacy_k=privacy_k,
            ),
            "language_bucket": _safe_distribution(
                language_counts, name="language_bucket", privacy_k=privacy_k
            ),
            "length_band": _safe_distribution(
                length_counts, name="length_band", privacy_k=privacy_k
            ),
            "cross_tabulations": CROSS_TABULATION_POLICY,
        },
        "cutoff": {
            "files_with_partial_tail_count": partial_tail_files,
            "trailing_partial_bytes_total": partial_tail_bytes,
            "complete_record_prefix_only": True,
        },
        "mechanical_projection_checks": {
            "projection_span_exactness_failures": _safe_subset_metric(
                projection_span_failures,
                candidates_total,
                privacy_k=privacy_k,
            ),
            "source_ref_digest_echo_failures": _safe_subset_metric(
                source_ref_echo_failures,
                candidates_total,
                privacy_k=privacy_k,
            ),
            "all_pass": mechanical_ok,
            "semantic_authority": False,
        },
        "safety_invariants": {
            "activation_denial_violations": _safe_subset_metric(
                activation_violations,
                candidates_total,
                privacy_k=privacy_k,
            ),
            "all_pass": safety_ok,
        },
    }
    shelf_cross_marginal_differences = (
        int(trace_counts["action_procedure_rule"])
        - int(shelf_counts["xingce"]),
        int(semantic_counts["preference"])
        - int(shelf_counts["zhiyi"]),
        int(shelf_counts["errata"])
        - int(state_counts["rejected"]),
    )
    if any(value < 0 for value in shelf_cross_marginal_differences):
        raise ShadowAuditError("cross_marginal_subset_invariant_failed")
    if any(0 < value < privacy_k for value in shelf_cross_marginal_differences):
        metrics["distributions"]["shelf"] = _withheld_distribution(privacy_k)
    duplicate_projection_count = max(
        0, raw_sentence_count - deduplicated_sentence_count
    )
    overlap_sentence_difference = abs(records_overlap - duplicate_projection_count)
    if 0 < overlap_sentence_difference < privacy_k:
        metrics["records"]["summary_detail_overlap"] = _withheld_subset_metric(
            records_processed
        )

    if candidates_total != deduplicated_sentence_count:
        raise ShadowAuditError("candidate_sentence_count_invariant_failed")
    if sum(int(value) for value in skip_reasons.values()) != records_skipped:
        raise ShadowAuditError("skip_reason_conservation_invariant_failed")
    if sum(int(value) for value in error_reasons.values()) != records_error:
        raise ShadowAuditError("error_reason_conservation_invariant_failed")
    if candidates_conservative_review_required != (
        candidates_ambiguous
        + int(trace_counts["default_claim_rule"])
        + candidates_preference_source_triggered
    ):
        raise ShadowAuditError("candidate_conservative_decomposition_invariant_failed")
    if (
        sum(int(values["review_or_unprocessable"]) for values in kinds.values())
        != records_conservative_review_required + records_skipped + records_error
    ):
        raise ShadowAuditError("record_review_conservation_invariant_failed")
    if int(literal_counts["instruction"]) != int(
        trace_counts["instruction_like_claim"]
    ):
        raise ShadowAuditError("instruction_literal_trace_invariant_failed")
    if candidates_ambiguous != int(trace_counts["event_claim_ambiguity"]):
        raise ShadowAuditError("candidate_ambiguity_trace_invariant_failed")
    _apply_known_cross_marginal_privacy(
        metrics,
        privacy_k=privacy_k,
        relation_values={
            "candidate_conservative_overlap_memberships": (
                candidates_ambiguous
                + int(trace_counts["default_claim_rule"])
                + candidates_preference_source_triggered
                - candidates_conservative_review_required
            ),
            "candidate_conservative_minus_ambiguity": (
                candidates_conservative_review_required - candidates_ambiguous
            ),
            "candidate_conservative_minus_default_claim": (
                candidates_conservative_review_required
                - int(trace_counts["default_claim_rule"])
            ),
            "candidate_conservative_minus_preference_source": (
                candidates_conservative_review_required
                - candidates_preference_source_triggered
            ),
            "default_trace_lexical_memberships": (
                int(trace_counts["default_claim_rule"])
                - int(candidate_counts["default_claim_only"])
                - int(
                    candidate_counts[
                        "default_claim_plus_intra_record_relationship"
                    ]
                )
            ),
            "default_trace_not_active_trusted": (
                int(trace_counts["default_claim_rule"])
                - default_claim_active_trusted
            ),
            "default_trace_extra_over_record_default_only": (
                int(trace_counts["default_claim_rule"])
                - (
                    records_conservative_review_required
                    - records_zero_candidates
                    - records_engine_ambiguity_flagged
                    - records_preference_source_triggered
                )
            ),
            "default_active_trusted_frechet_lower_slack": (
                2 * candidates_total
                + default_claim_active_trusted
                - int(trace_counts["default_claim_rule"])
                - int(state_counts["active"])
                - int(taint_counts["trusted"])
            ),
            "candidate_ambiguity_extra_memberships": (
                candidates_ambiguous - records_engine_ambiguity_flagged
            ),
            "candidate_conservative_extra_memberships": (
                candidates_conservative_review_required
                + records_zero_candidates
                - records_conservative_review_required
            ),
            "candidate_literal_extra_memberships": (
                candidates_with_literal_hit - records_with_literal_hit
            ),
            "candidate_preference_source_extra_memberships": (
                candidates_preference_source_triggered
                - records_preference_source_triggered
            ),
            "candidate_record_extra_memberships": (
                candidates_total + records_zero_candidates - records_processed
            ),
            "conservative_extra_minus_ambiguity_extra_memberships": (
                candidates_conservative_review_required
                + records_zero_candidates
                - records_conservative_review_required
                - candidates_ambiguous
                + records_engine_ambiguity_flagged
            ),
            "conservative_extra_minus_preference_source_extra_memberships": (
                candidates_conservative_review_required
                + records_zero_candidates
                - records_conservative_review_required
                - candidates_preference_source_triggered
                + records_preference_source_triggered
            ),
            "extra_non_conservative_candidate_memberships": (
                (candidates_total - candidates_conservative_review_required)
                - (records_processed - records_conservative_review_required)
            ),
            "extra_non_literal_candidate_memberships": (
                candidates_total
                + records_zero_candidates
                - records_processed
                - candidates_with_literal_hit
                + records_with_literal_hit
            ),
            "lexical_partition_minus_candidate_ambiguity": (
                int(candidate_counts["lexical_semantic_or_safety"])
                - candidates_ambiguous
            ),
            "literal_family_extra_memberships": (
                sum(int(value) for value in literal_counts.values())
                - candidates_with_literal_hit
            ),
            "literal_union_minus_explicit_end": (
                candidates_with_literal_hit - int(literal_counts["explicit_end"])
            ),
            "literal_union_minus_explicit_event": (
                candidates_with_literal_hit - int(literal_counts["explicit_event"])
            ),
            "literal_union_minus_instruction": (
                candidates_with_literal_hit - int(literal_counts["instruction"])
            ),
            "literal_union_minus_preference_domain": (
                candidates_with_literal_hit
                - int(literal_counts["preference_domain"])
            ),
            "literal_union_minus_procedure_action": (
                candidates_with_literal_hit
                - int(literal_counts["procedure_action"])
            ),
            "literal_union_minus_unknown": (
                candidates_with_literal_hit - int(literal_counts["unknown"])
            ),
            "literal_union_minus_update": (
                candidates_with_literal_hit - int(literal_counts["update"])
            ),
            "newer_update_supersedes_minus_active": (
                int(trace_counts["newer_update_supersedes"])
                - int(trace_counts["newer_update_active"])
            ),
            "preference_source_domain_or_instruction_overlap": (
                candidates_preference_source_triggered
                + int(literal_counts["preference_domain"])
                - int(semantic_counts["preference"])
            ),
            "record_conservative_minus_ambiguity": (
                records_conservative_review_required
                - records_engine_ambiguity_flagged
            ),
            "record_conservative_minus_preference_source": (
                records_conservative_review_required
                - records_preference_source_triggered
            ),
            "record_conservative_minus_zero_candidate": (
                records_conservative_review_required - records_zero_candidates
            ),
            "record_default_only_conservative": (
                records_conservative_review_required
                - records_zero_candidates
                - records_engine_ambiguity_flagged
                - records_preference_source_triggered
            ),
            "record_nonzero_conservative_minus_ambiguity": (
                records_conservative_review_required
                - records_zero_candidates
                - records_engine_ambiguity_flagged
            ),
            "record_nonzero_conservative_minus_preference_source": (
                records_conservative_review_required
                - records_zero_candidates
                - records_preference_source_triggered
            ),
            "record_with_candidates_minus_literal": (
                records_processed
                - records_zero_candidates
                - records_with_literal_hit
            ),
            "relationship_trace_extra_memberships": (
                sum(int(trace_counts[name]) for name in RELATIONSHIP_TRACES)
                - int(
                    candidate_counts[
                        "default_claim_plus_intra_record_relationship"
                    ]
                )
            ),
            "semantic_claim_minus_instruction_literal": (
                int(semantic_counts["claim"])
                - int(literal_counts["instruction"])
            ),
            "semantic_event_minus_candidate_ambiguity": (
                int(semantic_counts["event"]) - candidates_ambiguous
            ),
            "literal_explicit_end_extra_memberships": (
                int(literal_counts["explicit_end"])
                - int(trace_counts["explicit_end_superseded"])
            ),
            "state_active_minus_default_claim_active_trusted": (
                int(state_counts["active"]) - default_claim_active_trusted
            ),
            "taint_trusted_minus_default_claim_active_trusted": (
                int(taint_counts["trusted"]) - default_claim_active_trusted
            ),
        },
    )
    _apply_dependency_privacy_closure(metrics, privacy_k=privacy_k)
    mechanical_result_visible = all(
        metrics["mechanical_projection_checks"][name]["status"] == "published"
        for name in (
            "projection_span_exactness_failures",
            "source_ref_digest_echo_failures",
        )
    )
    safety_result_visible = (
        metrics["safety_invariants"]["activation_denial_violations"]["status"]
        == "published"
    )
    shareable_integrity_visible = (
        metrics["records"]["processing_outcome"]["status"] == "published"
        and all(
            value["status"] == "published"
            for value in metrics["records"]["by_kind"].values()
        )
        and metrics["mechanical_projection_checks"][
            "projection_span_exactness_failures"
        ]["status"]
        == "published"
        and metrics["mechanical_projection_checks"][
            "source_ref_digest_echo_failures"
        ]["status"]
        == "published"
        and metrics["safety_invariants"]["activation_denial_violations"][
            "status"
        ]
        == "published"
        and metrics["records"]["actual_model_calls"]["status"] == "published"
        and metrics["candidates"]["actual_model_calls"]["status"] == "published"
    )
    report_ok = (
        measurement_complete
        and mechanical_ok
        and safety_ok
        and shareable_integrity_visible
    )
    measurement_identity = _measurement_identity_payload(
        provenance,
        metrics,
        holdout["holdout_manifest_sha256"],
    )
    report = {
        "ok": report_ok,
        "ok_scope": "measurement_integrity_only_not_production_or_quality",
        "contract": CONTRACT,
        "status": (
            "measurement_integrity_complete_product_gate_red"
            if report_ok
            else "rejected_incomplete_or_mechanical_safety_failure"
        ),
        "decision": "NO_GO_PRODUCTION_SHADOW",
        "decision_reasons": BASE_DECISION_REASONS
        + (
            []
            if measurement_complete and shareable_integrity_visible
            else ["record_measurement_incomplete"]
        )
        + (
            []
            if not mechanical_result_visible or mechanical_ok
            else ["mechanical_projection_check_failed"]
        )
        + (
            []
            if not safety_result_visible or safety_ok
            else ["activation_denial_invariant_failed"]
        ),
        "provenance": provenance,
        "metrics": metrics,
        "measurement_identity_sha256": sha256_json(measurement_identity),
        "holdout_manifest_sha256": holdout["holdout_manifest_sha256"],
        "quality": {
            "coverage": "not_measured",
            "preservation": "not_measured",
            "semantic_accuracy": "not_measured",
            "state_role_accuracy": "not_measured",
            "canonical_source_ref_retention": "not_measured",
            "source_ref_resolvability": "not_measured",
            "source_ref_semantic_correctness": "not_measured",
            "raw_source_span_exactness": "not_measured",
            "cross_record_conflict_and_supersession": "not_measured",
            "rule_hit_is_not_accuracy": True,
            "same_author_held_out_is_not_independent_blind_evidence": True,
        },
        "privacy": {
            "k_anonymity_threshold": privacy_k,
            "only_preregistered_marginal_distributions": True,
            "small_cell_policy": SMALL_CELL_POLICY,
            "cross_tabulations_emitted": False,
            "source_text_emitted": False,
            "text_hashes_emitted": False,
            "source_paths_emitted": False,
            "machine_or_session_ids_emitted": False,
            "native_record_ids_emitted": False,
            "holdout_records_emitted_in_shareable_report": False,
        },
        "write_boundary": {
            "read_only": True,
            "model_call_performed": False,
            "network_call_performed": False,
            "production_shadow_write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "activation_performed": False,
        },
        "no_overall_score": True,
        "non_claims": NON_CLAIMS,
        "time_rule_decision": {
            "decision": "attached",
            "rule_ids": TIME_RULE_IDS,
        },
    }
    validate_shareable_report(
        report,
        expected_privacy_k=privacy_k,
        expected_holdout_count=holdout_count,
    )
    return report, holdout


def validate_shareable_report(
    report: Dict[str, Any],
    *,
    expected_privacy_k: int = DEFAULT_PRIVACY_K,
    expected_holdout_count: int = DEFAULT_HOLDOUT_COUNT,
) -> None:
    top_level = {
        "ok",
        "ok_scope",
        "contract",
        "status",
        "decision",
        "decision_reasons",
        "provenance",
        "metrics",
        "measurement_identity_sha256",
        "holdout_manifest_sha256",
        "quality",
        "privacy",
        "write_boundary",
        "no_overall_score",
        "non_claims",
        "time_rule_decision",
    }
    if not isinstance(report, dict) or set(report) != top_level:
        raise ShadowAuditError("shareable_report_top_level_allowlist_failed")
    if report.get("contract") != CONTRACT:
        raise ShadowAuditError("shareable_report_contract_invalid")
    if report.get("decision") != "NO_GO_PRODUCTION_SHADOW":
        raise ShadowAuditError("shareable_report_production_decision_invalid")
    if report.get("ok_scope") != (
        "measurement_integrity_only_not_production_or_quality"
    ):
        raise ShadowAuditError("shareable_report_ok_scope_invalid")
    if report.get("no_overall_score") is not True:
        raise ShadowAuditError("shareable_report_overall_score_policy_invalid")
    if not isinstance(report.get("ok"), bool):
        raise ShadowAuditError("shareable_report_ok_invalid")
    expected_status = (
        "measurement_integrity_complete_product_gate_red"
        if report["ok"]
        else "rejected_incomplete_or_mechanical_safety_failure"
    )
    if report.get("status") != expected_status:
        raise ShadowAuditError("shareable_report_status_invalid")
    required_red_reasons = set(BASE_DECISION_REASONS)
    reasons = report.get("decision_reasons")
    if not isinstance(reasons, list) or not required_red_reasons.issubset(reasons):
        raise ShadowAuditError("shareable_report_red_reasons_invalid")

    def exact_keys(value: object, expected: set, label: str) -> Dict[str, Any]:
        if not isinstance(value, dict) or set(value) != expected:
            raise ShadowAuditError("shareable_report_" + label + "_allowlist_failed")
        return value

    metrics = exact_keys(
        report.get("metrics"),
        {
            "records",
            "sentences",
            "candidates",
            "distributions",
            "cutoff",
            "mechanical_projection_checks",
            "safety_invariants",
        },
        "metrics",
    )
    records = exact_keys(
        metrics.get("records"),
        {
            "seen",
            "processing_outcome",
            "by_kind",
            "skip_reasons",
            "error_reasons",
            "engine_ambiguity_flagged",
            "actual_model_calls",
            "conservative_review_required",
            "review_or_unprocessable",
            "with_literal_family_hit",
            "summary_detail_overlap",
            "zero_candidate",
            "observed_at_fallback",
            "recorded_at_legacy_naive_utc",
            "recorded_at_legacy_naive_utc_policy",
            "preference_source_triggered",
        },
        "records",
    )
    by_kind = exact_keys(records.get("by_kind"), set(RECORD_PATHS), "record_kind")
    for kind, value in by_kind.items():
        exact_keys(
            value,
            {
                "status",
                "seen",
                "processed",
                "skipped",
                "error",
                "conservation_pass",
            },
            "record_kind_" + kind,
        )
    exact_keys(
        metrics.get("sentences"),
        {
            "raw_summary_plus_detail_count",
            "deduplicated_projection_count",
            "duplicate_projection_sentences_avoided",
            "projection_policy",
        },
        "sentences",
    )
    exact_keys(
        metrics.get("candidates"),
        {
            "total",
            "engine_ambiguity_flagged",
            "actual_model_calls",
            "conservative_review_required",
            "with_literal_family_hit",
            "default_claim_only",
            "default_claim_plus_intra_record_relationship",
            "lexical_semantic_or_safety",
            "default_claim_active_trusted",
            "preference_source_triggered",
        },
        "candidates",
    )
    exact_keys(
        metrics.get("cutoff"),
        {
            "files_with_partial_tail_count",
            "trailing_partial_bytes_total",
            "complete_record_prefix_only",
        },
        "cutoff",
    )
    exact_keys(
        metrics.get("mechanical_projection_checks"),
        {
            "projection_span_exactness_failures",
            "source_ref_digest_echo_failures",
            "all_pass",
            "semantic_authority",
        },
        "mechanical_projection_checks",
    )
    exact_keys(
        metrics.get("safety_invariants"),
        {"activation_denial_violations", "all_pass"},
        "safety_invariants",
    )
    quality = exact_keys(
        report.get("quality"),
        {
            "coverage",
            "preservation",
            "semantic_accuracy",
            "state_role_accuracy",
            "canonical_source_ref_retention",
            "source_ref_resolvability",
            "source_ref_semantic_correctness",
            "raw_source_span_exactness",
            "cross_record_conflict_and_supersession",
            "rule_hit_is_not_accuracy",
            "same_author_held_out_is_not_independent_blind_evidence",
        },
        "quality",
    )
    if any(
        quality[name] != "not_measured"
        for name in (
            "coverage",
            "preservation",
            "semantic_accuracy",
            "state_role_accuracy",
            "canonical_source_ref_retention",
            "source_ref_resolvability",
            "source_ref_semantic_correctness",
            "raw_source_span_exactness",
            "cross_record_conflict_and_supersession",
        )
    ):
        raise ShadowAuditError("shareable_report_quality_redline_invalid")
    if (
        quality["rule_hit_is_not_accuracy"] is not True
        or quality["same_author_held_out_is_not_independent_blind_evidence"]
        is not True
    ):
        raise ShadowAuditError("shareable_report_quality_policy_invalid")
    privacy = exact_keys(
        report.get("privacy"),
        {
            "k_anonymity_threshold",
            "only_preregistered_marginal_distributions",
            "small_cell_policy",
            "cross_tabulations_emitted",
            "source_text_emitted",
            "text_hashes_emitted",
            "source_paths_emitted",
            "machine_or_session_ids_emitted",
            "native_record_ids_emitted",
            "holdout_records_emitted_in_shareable_report",
        },
        "privacy",
    )
    if (
        privacy["k_anonymity_threshold"] != expected_privacy_k
        or privacy["only_preregistered_marginal_distributions"] is not True
        or privacy["small_cell_policy"] != SMALL_CELL_POLICY
        or privacy["cross_tabulations_emitted"] is not False
        or privacy["source_text_emitted"] is not False
        or privacy["text_hashes_emitted"] is not False
        or privacy["source_paths_emitted"] is not False
        or privacy["machine_or_session_ids_emitted"] is not False
        or privacy["native_record_ids_emitted"] is not False
        or privacy["holdout_records_emitted_in_shareable_report"] is not False
    ):
        raise ShadowAuditError("shareable_report_privacy_redline_invalid")
    write_boundary = exact_keys(
        report.get("write_boundary"),
        {
            "read_only",
            "model_call_performed",
            "network_call_performed",
            "production_shadow_write_performed",
            "raw_write_performed",
            "memory_write_performed",
            "platform_write_performed",
            "activation_performed",
        },
        "write_boundary",
    )
    if write_boundary["read_only"] is not True or any(
        write_boundary[name] is not False
        for name in (
            "model_call_performed",
            "network_call_performed",
            "production_shadow_write_performed",
            "raw_write_performed",
            "memory_write_performed",
            "platform_write_performed",
            "activation_performed",
        )
    ):
        raise ShadowAuditError("shareable_report_write_boundary_invalid")
    time_rule = exact_keys(
        report.get("time_rule_decision"),
        {"decision", "rule_ids"},
        "time_rule_decision",
    )
    if time_rule.get("decision") != "attached":
        raise ShadowAuditError("shareable_report_time_rule_decision_invalid")
    if time_rule.get("rule_ids") != TIME_RULE_IDS:
        raise ShadowAuditError("shareable_report_time_rule_ids_invalid")
    if report.get("non_claims") != NON_CLAIMS:
        raise ShadowAuditError("shareable_report_non_claims_invalid")
    forbidden_names = {
        "detail",
        "exp_id",
        "message_id",
        "msg_id",
        "native_id",
        "relative_path",
        "session_id",
        "source_path",
        "summary",
        "text",
        "text_sha256",
        "window_id",
    }

    def walk(value: object, path: Tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in forbidden_names:
                    raise ShadowAuditError(
                        "shareable_report_forbidden_field:" + ".".join(path + (key,))
                    )
                walk(child, path + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, path + (str(index),))
        elif isinstance(value, str):
            if any(marker in value for marker in PRIVATE_PATH_MARKERS):
                raise ShadowAuditError("shareable_report_private_path_value")
            if "@" in value:
                raise ShadowAuditError("shareable_report_email_like_value")

    walk(report)
    privacy_k = expected_privacy_k

    def is_count(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    def validate_distribution(value: object, name: str) -> None:
        allowed = ALLOWED_DISTRIBUTION_LABELS[name]
        if not isinstance(value, dict) or set(value) != {"status", "k", "counts"}:
            raise ShadowAuditError("shareable_report_distribution_shape_invalid")
        if value["k"] != privacy_k:
            raise ShadowAuditError("shareable_report_distribution_k_mismatch")
        if value["status"] not in {"published", "withheld_due_to_small_cells"}:
            raise ShadowAuditError("shareable_report_distribution_status_invalid")
        if not isinstance(value["counts"], dict):
            raise ShadowAuditError("shareable_report_distribution_counts_invalid")
        if value["status"] == "withheld_due_to_small_cells" and value["counts"]:
            raise ShadowAuditError("shareable_report_withheld_distribution_leaked")
        if not set(value["counts"]).issubset(allowed):
            raise ShadowAuditError("shareable_report_distribution_label_invalid")
        for count in value["counts"].values():
            if not is_count(count) or count < privacy_k:
                raise ShadowAuditError("shareable_report_small_cell_emitted")

    def validate_subset(value: object) -> None:
        if not isinstance(value, dict) or set(value) != {
            "status",
            "count",
            "rate",
            "denominator",
        }:
            raise ShadowAuditError("shareable_report_subset_shape_invalid")
        if value["status"] == "withheld_due_to_dependency_closure":
            if any(value[name] is not None for name in ("count", "rate", "denominator")):
                raise ShadowAuditError(
                    "shareable_report_dependency_withheld_subset_leaked"
                )
            return
        denominator = value["denominator"]
        if not is_count(denominator):
            raise ShadowAuditError("shareable_report_subset_denominator_invalid")
        if value["status"] == "withheld_due_to_small_subset_or_complement":
            if value["count"] is not None or value["rate"] is not None:
                raise ShadowAuditError("shareable_report_withheld_subset_leaked")
            return
        if value["status"] != "published":
            raise ShadowAuditError("shareable_report_subset_status_invalid")
        count = value["count"]
        if not is_count(count) or count > denominator:
            raise ShadowAuditError("shareable_report_subset_count_invalid")
        if any(0 < part < privacy_k for part in (count, denominator - count)):
            raise ShadowAuditError("shareable_report_small_subset_or_complement")
        if value["rate"] != _rate(count, denominator):
            raise ShadowAuditError("shareable_report_subset_rate_invalid")

    validate_distribution(records["processing_outcome"], "processing_outcome")
    validate_distribution(records["skip_reasons"], "skip_reason")
    validate_distribution(records["error_reasons"], "error_reason")
    if not is_count(records["seen"]):
        raise ShadowAuditError("shareable_report_records_seen_invalid")

    outcome = records["processing_outcome"]
    outcome_visible = outcome["status"] == "published"
    outcome_counts = {
        name: int(outcome["counts"].get(name, 0))
        for name in ("processed", "skipped", "error")
    }
    if outcome_visible and sum(outcome_counts.values()) != records["seen"]:
        raise ShadowAuditError("shareable_report_processing_outcome_conservation_failed")
    if outcome_visible:
        for metric_name, outcome_name in (
            ("skip_reasons", "skipped"),
            ("error_reasons", "error"),
        ):
            reason_metric = records[metric_name]
            if reason_metric["status"] == "published" and (
                sum(int(value) for value in reason_metric["counts"].values())
                != outcome_counts[outcome_name]
            ):
                raise ShadowAuditError(
                    "shareable_report_" + metric_name + "_total_mismatch"
                )

    kinds_visible = True
    kind_totals = Counter()
    kind_seen_counts: Dict[str, int] = {}
    for kind, value in by_kind.items():
        status = value["status"]
        conservation = value["conservation_pass"]
        if not isinstance(conservation, bool):
            raise ShadowAuditError("shareable_report_kind_conservation_flag_invalid")
        if status == "published":
            counts = {}
            for name in ("seen", "processed", "skipped", "error"):
                count = value[name]
                if not is_count(count) or 0 < count < privacy_k:
                    raise ShadowAuditError("shareable_report_small_kind_cell")
                counts[name] = count
                kind_totals[name] += count
            expected_conservation = counts["seen"] == (
                counts["processed"] + counts["skipped"] + counts["error"]
            )
            if conservation is not expected_conservation:
                raise ShadowAuditError("shareable_report_kind_conservation_flag_mismatch")
            kind_seen_counts[kind] = counts["seen"]
        elif status == "withheld_due_to_small_cells":
            kinds_visible = False
            if any(
                value[name] is not None
                for name in ("seen", "processed", "skipped", "error")
            ):
                raise ShadowAuditError("shareable_report_withheld_kind_leaked")
        else:
            raise ShadowAuditError("shareable_report_kind_status_invalid")

    kind_publication = [
        value["status"] == "published" for value in by_kind.values()
    ]
    if any(kind_publication) and not all(kind_publication):
        raise ShadowAuditError("shareable_report_mixed_kind_visibility")

    if kinds_visible:
        if kind_totals["seen"] != records["seen"]:
            raise ShadowAuditError("shareable_report_kind_seen_total_mismatch")
        if outcome_visible and any(
            kind_totals[name] != outcome_counts[name]
            for name in ("processed", "skipped", "error")
        ):
            raise ShadowAuditError("shareable_report_kind_outcome_total_mismatch")

    for name in RECORD_SUBSET_NAMES:
        validate_subset(records[name])
    if outcome_visible:
        for name in RECORD_SUBSET_NAMES:
            expected_denominator = (
                records["seen"]
                if name == "review_or_unprocessable"
                else outcome_counts["processed"]
            )
            if records[name]["denominator"] != expected_denominator:
                raise ShadowAuditError(
                    "shareable_report_record_subset_denominator_mismatch"
                )
        if (
            records["review_or_unprocessable"]["status"] == "published"
            and records["conservative_review_required"]["status"] == "published"
            and int(records["review_or_unprocessable"]["count"])
            != int(records["conservative_review_required"]["count"])
            + int(outcome_counts["skipped"])
            + int(outcome_counts["error"])
        ):
            raise ShadowAuditError(
                "shareable_report_record_review_conservation_mismatch"
            )
    else:
        if any(kind_publication):
            raise ShadowAuditError(
                "shareable_report_hidden_outcome_kind_dependency_leak"
            )
        if any(
            records[name]["status"] != "withheld_due_to_dependency_closure"
            for name in RECORD_SUBSET_NAMES
        ):
            raise ShadowAuditError(
                "shareable_report_hidden_outcome_subset_dependency_leak"
            )
        if any(
            records[name]["status"] != "withheld_due_to_small_cells"
            for name in ("skip_reasons", "error_reasons")
        ):
            raise ShadowAuditError(
                "shareable_report_hidden_outcome_reason_dependency_leak"
            )

    sentences = metrics["sentences"]
    if records["recorded_at_legacy_naive_utc_policy"] != LEGACY_NAIVE_UTC_POLICY:
        raise ShadowAuditError("shareable_report_legacy_utc_policy_invalid")
    if sentences["projection_policy"] != PROJECTION_POLICY:
        raise ShadowAuditError("shareable_report_projection_policy_invalid")
    raw_sentence_count = sentences["raw_summary_plus_detail_count"]
    deduplicated_count = sentences["deduplicated_projection_count"]
    duplicate_metric = sentences["duplicate_projection_sentences_avoided"]
    validate_subset(duplicate_metric)
    if duplicate_metric["status"] == "withheld_due_to_dependency_closure":
        if raw_sentence_count is not None or deduplicated_count is not None:
            raise ShadowAuditError(
                "shareable_report_hidden_sentence_dependency_leak"
            )
    elif duplicate_metric["status"] == "published":
        if not is_count(raw_sentence_count):
            raise ShadowAuditError("shareable_report_sentence_count_invalid")
        if duplicate_metric["denominator"] != raw_sentence_count:
            raise ShadowAuditError("shareable_report_sentence_denominator_mismatch")
        if not is_count(deduplicated_count):
            raise ShadowAuditError("shareable_report_deduplicated_count_invalid")
        if raw_sentence_count - deduplicated_count != duplicate_metric["count"]:
            raise ShadowAuditError("shareable_report_sentence_conservation_failed")
    else:
        raise ShadowAuditError("shareable_report_hidden_sentence_dependency_leak")
    overlap_metric = records["summary_detail_overlap"]
    if (
        overlap_metric["status"] == "published"
        and duplicate_metric["status"] == "published"
        and 0
        < abs(overlap_metric["count"] - duplicate_metric["count"])
        < privacy_k
    ):
        raise ShadowAuditError("shareable_report_overlap_sentence_small_cell")

    candidates = metrics["candidates"]
    candidate_total = candidates["total"]
    if not is_count(candidate_total):
        raise ShadowAuditError("shareable_report_candidate_total_invalid")
    if deduplicated_count is not None and candidate_total != deduplicated_count:
        raise ShadowAuditError("shareable_report_candidate_sentence_count_mismatch")
    candidate_subset_names = (
        "engine_ambiguity_flagged",
        "actual_model_calls",
        "conservative_review_required",
        "with_literal_family_hit",
        "default_claim_only",
        "default_claim_plus_intra_record_relationship",
        "lexical_semantic_or_safety",
        "default_claim_active_trusted",
        "preference_source_triggered",
    )
    for name in candidate_subset_names:
        validate_subset(candidates[name])
        if candidates[name]["denominator"] != candidate_total:
            raise ShadowAuditError(
                "shareable_report_candidate_subset_denominator_mismatch"
            )
    for name in CANDIDATE_RECORD_ALIAS_NAMES:
        if (
            candidates[name]["status"] == "published"
        ) != (records[name]["status"] == "published"):
            raise ShadowAuditError(
                "shareable_report_candidate_record_alias_visibility_leak"
            )
    partition_publication = [
        candidates[name]["status"] == "published"
        for name in CANDIDATE_PARTITION_NAMES
    ]
    if any(partition_publication) and not all(partition_publication):
        raise ShadowAuditError("shareable_report_mixed_candidate_partition_visibility")
    if all(partition_publication):
        if (
            sum(candidates[name]["count"] for name in CANDIDATE_PARTITION_NAMES)
            != candidate_total
        ):
            raise ShadowAuditError("shareable_report_candidate_partition_mismatch")

    mechanical = metrics["mechanical_projection_checks"]
    mechanical_metrics = (
        mechanical["projection_span_exactness_failures"],
        mechanical["source_ref_digest_echo_failures"],
    )
    for value in mechanical_metrics:
        validate_subset(value)
        if value["denominator"] != candidate_total:
            raise ShadowAuditError("shareable_report_mechanical_denominator_mismatch")
    if mechanical["semantic_authority"] is not False:
        raise ShadowAuditError("shareable_report_mechanical_authority_invalid")
    mechanical_visible = all(
        value["status"] == "published" for value in mechanical_metrics
    )
    if mechanical_visible:
        if not isinstance(mechanical["all_pass"], bool):
            raise ShadowAuditError("shareable_report_mechanical_all_pass_invalid")
        mechanical_expected = all(value["count"] == 0 for value in mechanical_metrics)
        if mechanical["all_pass"] is not mechanical_expected:
            raise ShadowAuditError("shareable_report_mechanical_all_pass_mismatch")
    elif mechanical["all_pass"] is not None:
        raise ShadowAuditError("shareable_report_hidden_mechanical_result_leaked")

    safety = metrics["safety_invariants"]
    activation_metric = safety["activation_denial_violations"]
    validate_subset(activation_metric)
    if activation_metric["denominator"] != candidate_total:
        raise ShadowAuditError("shareable_report_safety_denominator_mismatch")
    safety_visible = activation_metric["status"] == "published"
    if safety_visible:
        if not isinstance(safety["all_pass"], bool):
            raise ShadowAuditError("shareable_report_safety_all_pass_invalid")
        if safety["all_pass"] is not (activation_metric["count"] == 0):
            raise ShadowAuditError("shareable_report_safety_all_pass_mismatch")
    elif safety["all_pass"] is not None:
        raise ShadowAuditError("shareable_report_hidden_safety_result_leaked")

    distributions = metrics.get("distributions", {})
    main_distribution_names = set(ALLOWED_DISTRIBUTION_LABELS) - {
        "processing_outcome",
        "skip_reason",
        "error_reason",
    }
    if set(distributions) != main_distribution_names | {"cross_tabulations"}:
        raise ShadowAuditError("shareable_report_distribution_allowlist_failed")
    if distributions["cross_tabulations"] != CROSS_TABULATION_POLICY:
        raise ShadowAuditError("shareable_report_cross_tabulation_policy_invalid")
    for name in main_distribution_names:
        validate_distribution(distributions[name], name)
    candidate_distribution_publication = [
        distributions[name]["status"] == "published"
        for name in CANDIDATE_DISTRIBUTION_NAMES
    ]
    if any(candidate_distribution_publication) and not all(
        candidate_distribution_publication
    ):
        raise ShadowAuditError(
            "shareable_report_mixed_candidate_distribution_visibility"
        )
    if any(candidate_distribution_publication) and any(
        candidates[name]["status"] != "published"
        for name in CANDIDATE_DISTRIBUTION_ALIAS_NAMES
    ):
        raise ShadowAuditError(
            "shareable_report_candidate_alias_distribution_dependency_leak"
        )
    if not outcome_visible and any(
        distributions[name]["status"] != "withheld_due_to_small_cells"
        for name in ("source_system_bucket", "language_bucket", "length_band")
    ):
        raise ShadowAuditError(
            "shareable_report_hidden_outcome_distribution_dependency_leak"
        )
    if kinds_visible and distributions["record_kind"]["status"] == "published":
        expected_kind_counts = {
            kind: count for kind, count in sorted(kind_seen_counts.items()) if count > 0
        }
        if distributions["record_kind"]["counts"] != expected_kind_counts:
            raise ShadowAuditError("shareable_report_record_kind_distribution_mismatch")
    if outcome_visible:
        for name in ("source_system_bucket", "language_bucket", "length_band"):
            value = distributions[name]
            if value["status"] == "published" and (
                sum(value["counts"].values()) != outcome_counts["processed"]
            ):
                raise ShadowAuditError("shareable_report_record_distribution_total_mismatch")
    for name in ("semantic_type", "state_role", "shelf", "taint"):
        value = distributions[name]
        if value["status"] == "published" and (
            sum(value["counts"].values()) != candidate_total
        ):
            raise ShadowAuditError("shareable_report_candidate_distribution_total_mismatch")

    def distribution_count(name: str, label: str) -> int:
        return int(distributions[name]["counts"].get(label, 0))

    def published_subset_count(container: Dict[str, Any], name: str) -> Optional[int]:
        value = container[name]
        return int(value["count"]) if value["status"] == "published" else None

    def validate_cross_marginal_residual(value: int, name: str) -> None:
        if value < 0:
            raise ShadowAuditError(
                "shareable_report_" + name + "_relation_invalid"
            )
        if 0 < value < privacy_k:
            raise ShadowAuditError(
                "shareable_report_" + name + "_small_cell"
            )

    rule_trace_published = distributions["rule_trace"]["status"] == "published"
    candidate_ambiguity = published_subset_count(
        candidates, "engine_ambiguity_flagged"
    )
    record_ambiguity = published_subset_count(
        records, "engine_ambiguity_flagged"
    )
    candidate_conservative = published_subset_count(
        candidates, "conservative_review_required"
    )
    record_conservative = published_subset_count(
        records, "conservative_review_required"
    )
    record_zero_candidate = published_subset_count(records, "zero_candidate")
    candidate_literal = published_subset_count(
        candidates, "with_literal_family_hit"
    )
    record_literal = published_subset_count(records, "with_literal_family_hit")
    candidate_preference_source = published_subset_count(
        candidates, "preference_source_triggered"
    )
    record_preference_source = published_subset_count(
        records, "preference_source_triggered"
    )
    conservative_publication = (
        candidate_conservative is not None,
        record_conservative is not None,
        records["review_or_unprocessable"]["status"] == "published",
        record_zero_candidate is not None,
    )
    if any(conservative_publication) and not all(conservative_publication):
        raise ShadowAuditError(
            "shareable_report_mixed_conservative_dependency_visibility"
        )
    candidate_conservative_components_visible = (
        candidate_ambiguity is not None,
        candidate_preference_source is not None,
        *(
            candidates[name]["status"] == "published"
            for name in CANDIDATE_PARTITION_NAMES
        ),
    )
    if candidate_conservative is None and candidate_ambiguity is not None:
        raise ShadowAuditError(
            "shareable_report_hidden_conservative_ambiguity_dependency_leak"
        )
    if candidate_conservative is not None and not all(
        candidate_conservative_components_visible
    ):
        raise ShadowAuditError(
            "shareable_report_conservative_component_dependency_leak"
        )
    candidate_conservative_algebra_publication = (
        candidate_conservative is not None,
        *candidate_conservative_components_visible,
        rule_trace_published,
    )
    if any(candidate_conservative_algebra_publication) and not all(
        candidate_conservative_algebra_publication
    ):
        raise ShadowAuditError(
            "shareable_report_mixed_candidate_conservative_algebra_visibility"
        )
    if candidate_conservative is not None:
        expected_candidate_conservative = (
            int(candidates["default_claim_only"]["count"])
            + int(
                candidates["default_claim_plus_intra_record_relationship"][
                    "count"
                ]
            )
            + int(candidate_preference_source)
            + int(candidate_ambiguity)
        )
        if candidate_conservative != expected_candidate_conservative:
            raise ShadowAuditError(
                "shareable_report_candidate_conservative_decomposition_mismatch"
            )

    if rule_trace_published and candidate_ambiguity is not None:
        if candidate_ambiguity != distribution_count(
            "rule_trace", "event_claim_ambiguity"
        ):
            raise ShadowAuditError(
                "shareable_report_candidate_ambiguity_trace_relation_mismatch"
            )
    if (
        rule_trace_published
        and candidate_ambiguity is not None
        and candidates["conservative_review_required"]["status"] == "published"
        and candidates["preference_source_triggered"]["status"] == "published"
    ):
        validate_cross_marginal_residual(
            candidate_ambiguity
            + distribution_count("rule_trace", "default_claim_rule")
            + int(candidates["preference_source_triggered"]["count"])
            - int(candidates["conservative_review_required"]["count"]),
            "candidate_conservative_overlap",
        )
    if candidate_conservative is not None:
        candidate_conservative_components = {
            "candidate_conservative_minus_ambiguity": candidate_ambiguity,
            "candidate_conservative_minus_default_claim": (
                distribution_count("rule_trace", "default_claim_rule")
                if rule_trace_published
                else None
            ),
            "candidate_conservative_minus_preference_source": (
                candidate_preference_source
            ),
        }
        for name, component in candidate_conservative_components.items():
            if component is not None:
                validate_cross_marginal_residual(
                    candidate_conservative - component,
                    name,
                )
    if (
        rule_trace_published
        and candidates["default_claim_only"]["status"] == "published"
        and candidates["default_claim_plus_intra_record_relationship"]["status"]
        == "published"
    ):
        validate_cross_marginal_residual(
            distribution_count("rule_trace", "default_claim_rule")
            - int(candidates["default_claim_only"]["count"])
            - int(
                candidates["default_claim_plus_intra_record_relationship"][
                    "count"
                ]
            ),
            "default_trace_lexical_membership",
        )
    if (
        rule_trace_published
        and candidates["default_claim_active_trusted"]["status"] == "published"
    ):
        validate_cross_marginal_residual(
            distribution_count("rule_trace", "default_claim_rule")
            - int(candidates["default_claim_active_trusted"]["count"]),
            "default_trace_not_active_trusted",
        )
    if candidate_ambiguity is not None and record_ambiguity is not None:
        validate_cross_marginal_residual(
            candidate_ambiguity - record_ambiguity,
            "candidate_ambiguity_extra_membership",
        )
    if (
        candidate_ambiguity is not None
        and candidates["lexical_semantic_or_safety"]["status"] == "published"
    ):
        validate_cross_marginal_residual(
            int(candidates["lexical_semantic_or_safety"]["count"])
            - candidate_ambiguity,
            "lexical_partition_minus_candidate_ambiguity",
        )
    if (
        candidate_conservative is not None
        and record_conservative is not None
        and record_zero_candidate is not None
    ):
        validate_cross_marginal_residual(
            candidate_conservative
            + record_zero_candidate
            - record_conservative,
            "candidate_conservative_extra_membership",
        )
    if candidate_literal is not None and record_literal is not None:
        validate_cross_marginal_residual(
            candidate_literal - record_literal,
            "candidate_literal_extra_membership",
        )
    if outcome_visible and record_zero_candidate is not None:
        validate_cross_marginal_residual(
            candidate_total
            + record_zero_candidate
            - int(outcome_counts["processed"]),
            "candidate_record_extra_membership",
        )
    if (
        candidate_preference_source is not None
        and record_preference_source is not None
    ):
        validate_cross_marginal_residual(
            candidate_preference_source - record_preference_source,
            "candidate_preference_source_extra_membership",
        )
    if record_conservative is not None:
        record_conservative_components = {
            "record_conservative_minus_ambiguity": record_ambiguity,
            "record_conservative_minus_preference_source": (
                record_preference_source
            ),
            "record_conservative_minus_zero_candidate": record_zero_candidate,
        }
        for name, component in record_conservative_components.items():
            if component is not None:
                validate_cross_marginal_residual(
                    record_conservative - component,
                    name,
                )
    if (
        outcome_visible
        and candidate_conservative is not None
        and record_conservative is not None
    ):
        validate_cross_marginal_residual(
            (candidate_total - candidate_conservative)
            - (int(outcome_counts["processed"]) - record_conservative),
            "extra_non_conservative_candidate_membership",
        )
    if (
        candidate_conservative is not None
        and record_conservative is not None
        and record_zero_candidate is not None
    ):
        for name, candidate_component, record_component in (
            (
                "conservative_extra_minus_ambiguity_extra_membership",
                candidate_ambiguity,
                record_ambiguity,
            ),
            (
                "conservative_extra_minus_preference_source_extra_membership",
                candidate_preference_source,
                record_preference_source,
            ),
        ):
            if candidate_component is not None and record_component is not None:
                validate_cross_marginal_residual(
                    candidate_conservative
                    + record_zero_candidate
                    - record_conservative
                    - candidate_component
                    + record_component,
                    name,
                )
    if (
        outcome_visible
        and record_zero_candidate is not None
        and candidate_literal is not None
        and record_literal is not None
    ):
        validate_cross_marginal_residual(
            candidate_total
            + record_zero_candidate
            - int(outcome_counts["processed"])
            - candidate_literal
            + record_literal,
            "extra_non_literal_candidate_membership",
        )
        validate_cross_marginal_residual(
            int(outcome_counts["processed"])
            - record_zero_candidate
            - record_literal,
            "record_with_candidates_minus_literal",
        )
    if record_conservative is not None and record_zero_candidate is not None:
        for name, component in (
            ("record_nonzero_conservative_minus_ambiguity", record_ambiguity),
            (
                "record_nonzero_conservative_minus_preference_source",
                record_preference_source,
            ),
        ):
            if component is not None:
                validate_cross_marginal_residual(
                    record_conservative - record_zero_candidate - component,
                    name,
                )
    if (
        record_conservative is not None
        and record_zero_candidate is not None
        and record_ambiguity is not None
        and record_preference_source is not None
    ):
        record_default_only = (
            record_conservative
            - record_zero_candidate
            - record_ambiguity
            - record_preference_source
        )
        validate_cross_marginal_residual(
            record_default_only,
            "record_default_only_conservative",
        )
        if rule_trace_published:
            validate_cross_marginal_residual(
                distribution_count("rule_trace", "default_claim_rule")
                - record_default_only,
                "default_trace_extra_over_record_default_only",
            )
    if (
        distributions["literal_family"]["status"] == "published"
        and candidate_literal is not None
    ):
        validate_cross_marginal_residual(
            sum(distributions["literal_family"]["counts"].values())
            - candidate_literal,
            "literal_family_extra_membership",
        )
        for label in (
            "explicit_end",
            "explicit_event",
            "instruction",
            "preference_domain",
            "procedure_action",
            "unknown",
            "update",
        ):
            validate_cross_marginal_residual(
                candidate_literal
                - distribution_count("literal_family", label),
                "literal_union_minus_" + label,
            )
    if (
        distributions["literal_family"]["status"] == "published"
        and distributions["semantic_type"]["status"] == "published"
        and candidate_preference_source is not None
    ):
        validate_cross_marginal_residual(
            candidate_preference_source
            + distribution_count("literal_family", "preference_domain")
            - distribution_count("semantic_type", "preference"),
            "preference_source_domain_or_instruction_overlap",
        )
    if rule_trace_published:
        validate_cross_marginal_residual(
            sum(
                distribution_count("rule_trace", name)
                for name in RELATIONSHIP_TRACES
            )
            - int(
                candidates["default_claim_plus_intra_record_relationship"][
                    "count"
                ]
            ),
            "relationship_trace_extra_membership",
        )
        validate_cross_marginal_residual(
            distribution_count("rule_trace", "newer_update_supersedes")
            - distribution_count("rule_trace", "newer_update_active"),
            "newer_update_supersedes_minus_active",
        )
    if (
        distributions["literal_family"]["status"] == "published"
        and rule_trace_published
        and distribution_count("literal_family", "instruction")
        != distribution_count("rule_trace", "instruction_like_claim")
    ):
        raise ShadowAuditError(
            "shareable_report_instruction_literal_trace_relation_mismatch"
        )
    if (
        distributions["semantic_type"]["status"] == "published"
        and distributions["literal_family"]["status"] == "published"
    ):
        validate_cross_marginal_residual(
            distribution_count("semantic_type", "claim")
            - distribution_count("literal_family", "instruction"),
            "semantic_claim_minus_instruction_literal",
        )
    if (
        distributions["semantic_type"]["status"] == "published"
        and candidate_ambiguity is not None
    ):
        validate_cross_marginal_residual(
            distribution_count("semantic_type", "event") - candidate_ambiguity,
            "semantic_event_minus_candidate_ambiguity",
        )
    if distributions["literal_family"]["status"] == "published" and rule_trace_published:
        validate_cross_marginal_residual(
            distribution_count("literal_family", "explicit_end")
            - distribution_count("rule_trace", "explicit_end_superseded"),
            "literal_explicit_end_extra_membership",
        )
    if candidates["default_claim_active_trusted"]["status"] == "published":
        default_active_trusted = int(
            candidates["default_claim_active_trusted"]["count"]
        )
        if distributions["state_role"]["status"] == "published":
            validate_cross_marginal_residual(
                distribution_count("state_role", "active")
                - default_active_trusted,
                "state_active_minus_default_claim_active_trusted",
            )
        if distributions["taint"]["status"] == "published":
            validate_cross_marginal_residual(
                distribution_count("taint", "trusted")
                - default_active_trusted,
                "taint_trusted_minus_default_claim_active_trusted",
            )
        if (
            rule_trace_published
            and distributions["state_role"]["status"] == "published"
            and distributions["taint"]["status"] == "published"
        ):
            validate_cross_marginal_residual(
                2 * candidate_total
                + default_active_trusted
                - distribution_count("rule_trace", "default_claim_rule")
                - distribution_count("state_role", "active")
                - distribution_count("taint", "trusted"),
                "default_active_trusted_frechet_lower_slack",
            )

    if (
        distributions["semantic_type"]["status"] == "published"
        and distributions["rule_trace"]["status"] == "published"
    ):
        semantic_trace_relations = {
            "claim": (
                distribution_count("rule_trace", "default_claim_rule")
                + distribution_count("rule_trace", "instruction_like_claim")
            ),
            "event": (
                distribution_count("rule_trace", "explicit_event_rule")
                + distribution_count("rule_trace", "event_claim_ambiguity")
            ),
            "procedure": (
                distribution_count("rule_trace", "action_procedure_rule")
                + distribution_count("rule_trace", "descriptive_schedule_rule")
            ),
            "preference": distribution_count("rule_trace", "preference_rule"),
        }
        if any(
            distribution_count("semantic_type", label) != expected
            for label, expected in semantic_trace_relations.items()
        ):
            raise ShadowAuditError("shareable_report_semantic_trace_relation_mismatch")
    if (
        distributions["state_role"]["status"] == "published"
        and distributions["rule_trace"]["status"] == "published"
    ):
        if distribution_count("state_role", "rejected") != distribution_count(
            "rule_trace", "instruction_like_claim"
        ):
            raise ShadowAuditError("shareable_report_rejected_trace_relation_mismatch")
        if distribution_count("state_role", "conflicting") != distribution_count(
            "rule_trace", "cross_source_conflict"
        ):
            raise ShadowAuditError("shareable_report_conflict_trace_relation_mismatch")
        expected_superseded = (
            distribution_count("rule_trace", "explicit_end_superseded")
            + distribution_count("rule_trace", "newer_update_supersedes")
        )
        if distribution_count("state_role", "superseded") != expected_superseded:
            raise ShadowAuditError("shareable_report_superseded_trace_relation_mismatch")
    if (
        distributions["taint"]["status"] == "published"
        and distributions["rule_trace"]["status"] == "published"
        and distribution_count("taint", "instruction_like")
        != distribution_count("rule_trace", "instruction_like_claim")
    ):
        raise ShadowAuditError("shareable_report_taint_trace_relation_mismatch")

    shelf = distributions["shelf"]
    if shelf["status"] == "published":
        shelf_subset_differences = []
        if distributions["rule_trace"]["status"] == "published":
            shelf_subset_differences.append(
                distribution_count("rule_trace", "action_procedure_rule")
                - distribution_count("shelf", "xingce")
            )
        if distributions["semantic_type"]["status"] == "published":
            shelf_subset_differences.append(
                distribution_count("semantic_type", "preference")
                - distribution_count("shelf", "zhiyi")
            )
        if distributions["state_role"]["status"] == "published":
            shelf_subset_differences.append(
                distribution_count("shelf", "errata")
                - distribution_count("state_role", "rejected")
            )
        if any(value < 0 for value in shelf_subset_differences):
            raise ShadowAuditError("shareable_report_cross_marginal_subset_invalid")
        if any(0 < value < privacy_k for value in shelf_subset_differences):
            raise ShadowAuditError("shareable_report_cross_marginal_small_cell")

    cutoff_metrics = metrics["cutoff"]
    if (
        not is_count(cutoff_metrics["files_with_partial_tail_count"])
        or not is_count(cutoff_metrics["trailing_partial_bytes_total"])
        or cutoff_metrics["complete_record_prefix_only"] is not True
    ):
        raise ShadowAuditError("shareable_report_cutoff_metrics_invalid")
    cutoff_complete = (
        cutoff_metrics["files_with_partial_tail_count"] == 0
        and cutoff_metrics["trailing_partial_bytes_total"] == 0
    )

    provenance = report.get("provenance", {})
    expected_provenance = {
        "source_commit",
        "tool_sha256",
        "extractor_sha256",
        "extractor_contract",
        "cutoff_file_sha256",
        "cutoff_identity_sha256",
        "preregistration_file_sha256",
        "holdout_key_file_sha256",
        "holdout_exact_count",
        "selection_algorithm",
        "selection_seed_sha256",
        "privacy_k",
        "max_jsonl_line_bytes",
        "rules_frozen",
    }
    if set(provenance) != expected_provenance:
        raise ShadowAuditError("shareable_report_provenance_allowlist_failed")
    if provenance["privacy_k"] != expected_privacy_k:
        raise ShadowAuditError("shareable_report_provenance_privacy_k_invalid")
    if provenance["holdout_exact_count"] != expected_holdout_count:
        raise ShadowAuditError("shareable_report_provenance_holdout_count_invalid")
    if not _valid_commit(provenance["source_commit"]):
        raise ShadowAuditError("shareable_report_provenance_commit_invalid")
    for name in (
        "tool_sha256",
        "extractor_sha256",
        "cutoff_file_sha256",
        "cutoff_identity_sha256",
        "preregistration_file_sha256",
        "holdout_key_file_sha256",
        "selection_seed_sha256",
    ):
        if not _valid_sha256(provenance[name]):
            raise ShadowAuditError("shareable_report_provenance_sha256_invalid")
    if (
        provenance["extractor_contract"]
        != candidate_rules.HYBRID_EXTRACTION_CONTRACT
        or provenance["selection_algorithm"] != SELECTION_ALGORITHM
        or provenance["max_jsonl_line_bytes"] != MAX_JSONL_LINE_BYTES
        or provenance["rules_frozen"] is not True
    ):
        raise ShadowAuditError("shareable_report_provenance_policy_invalid")

    holdout_digest = report["holdout_manifest_sha256"]
    measurement_digest = report["measurement_identity_sha256"]
    if not _valid_sha256(holdout_digest):
        raise ShadowAuditError("shareable_report_holdout_digest_invalid")
    if not _valid_sha256(measurement_digest):
        raise ShadowAuditError("shareable_report_measurement_identity_invalid")
    expected_measurement_digest = sha256_json(
        _measurement_identity_payload(provenance, metrics, holdout_digest)
    )
    if measurement_digest != expected_measurement_digest:
        raise ShadowAuditError("shareable_report_measurement_identity_mismatch")

    actual_model_visible = (
        records["actual_model_calls"]["status"] == "published"
        and candidates["actual_model_calls"]["status"] == "published"
    )
    if actual_model_visible and (
        records["actual_model_calls"]["count"] != 0
        or candidates["actual_model_calls"]["count"] != 0
    ):
        raise ShadowAuditError("shareable_report_actual_model_calls_nonzero")
    shareable_integrity_visible = (
        outcome_visible
        and kinds_visible
        and mechanical_visible
        and safety_visible
        and actual_model_visible
    )
    measurement_complete = (
        shareable_integrity_visible
        and records["seen"] > 0
        and outcome_counts["processed"] == records["seen"]
        and outcome_counts["skipped"] == 0
        and outcome_counts["error"] == 0
        and all(value["conservation_pass"] is True for value in by_kind.values())
        and cutoff_complete
    )
    expected_ok = (
        measurement_complete
        and mechanical["all_pass"] is True
        and safety["all_pass"] is True
    )
    if report["ok"] is not expected_ok:
        raise ShadowAuditError("shareable_report_ok_not_recomputed")
    expected_status = (
        "measurement_integrity_complete_product_gate_red"
        if expected_ok
        else "rejected_incomplete_or_mechanical_safety_failure"
    )
    if report["status"] != expected_status:
        raise ShadowAuditError("shareable_report_status_not_recomputed")
    expected_reasons = BASE_DECISION_REASONS + (
        [] if measurement_complete else ["record_measurement_incomplete"]
    )
    if mechanical_visible and mechanical["all_pass"] is not True:
        expected_reasons.append("mechanical_projection_check_failed")
    if safety_visible and safety["all_pass"] is not True:
        expected_reasons.append("activation_denial_invariant_failed")
    if reasons != expected_reasons:
        raise ShadowAuditError("shareable_report_decision_reasons_not_recomputed")


def validate_holdout_manifest(holdout: Dict[str, Any]) -> None:
    expected = {
        "contract",
        "source_cutoff_identity_sha256",
        "selection_algorithm",
        "selection_seed_sha256",
        "exact_count",
        "holdout_count",
        "selection_complete",
        "records",
        "contains_source_text",
        "contains_text_hashes",
        "contains_answer_labels",
        "contains_private_paths_or_native_ids",
        "opaque_id_scheme",
        "independent_labels_status",
        "local_only_not_shared_with_rule_author_or_antagonist",
        "read_only",
        "write_performed",
        "holdout_manifest_sha256",
    }
    if not isinstance(holdout, dict) or set(holdout) != expected:
        raise ShadowAuditError("holdout_manifest_allowlist_failed")
    if holdout.get("contract") != HOLDOUT_CONTRACT:
        raise ShadowAuditError("holdout_manifest_contract_invalid")
    records = holdout.get("records")
    if not isinstance(records, list):
        raise ShadowAuditError("holdout_manifest_records_invalid")
    for item in records:
        if not isinstance(item, dict) or set(item) != {"opaque_record_id"}:
            raise ShadowAuditError("holdout_manifest_record_allowlist_failed")
        value = str(item["opaque_record_id"])
        if not value.startswith("record-") or len(value) != 39:
            raise ShadowAuditError("holdout_manifest_opaque_id_invalid")
    clean = dict(holdout)
    claimed = clean.pop("holdout_manifest_sha256", None)
    if claimed != sha256_json(clean):
        raise ShadowAuditError("holdout_manifest_digest_invalid")


def write_private_bytes(path: Path, payload: bytes, *, runtime_root: Path) -> None:
    path = Path(path)
    if _path_is_within(path, Path(runtime_root)):
        raise ShadowAuditError("output_must_not_be_inside_runtime_root")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ShadowAuditError("output_already_exists")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="." + path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(str(temporary), str(path))
        except FileExistsError as exc:
            raise ShadowAuditError("output_already_exists") from exc
        os.unlink(temporary)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        if temporary.exists():
            temporary.unlink()


def write_private_json(path: Path, value: object, *, runtime_root: Path) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    write_private_bytes(path, payload, runtime_root=runtime_root)


def create_holdout_key(path: Path, *, runtime_root: Path) -> None:
    value = {
        "contract": HOLDOUT_KEY_CONTRACT,
        "key_hex": secrets.token_hex(32),
    }
    write_private_json(path, value, runtime_root=runtime_root)


def load_holdout_key(path: Path) -> bytes:
    path = Path(path)
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ShadowAuditError("holdout_key_permissions_too_broad")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("contract") != HOLDOUT_KEY_CONTRACT:
        raise ShadowAuditError("holdout_key_contract_invalid")
    try:
        key = bytes.fromhex(str(value.get("key_hex") or ""))
    except ValueError as exc:
        raise ShadowAuditError("holdout_key_invalid") from exc
    if len(key) != 32:
        raise ShadowAuditError("holdout_key_invalid")
    return key


def _default_runtime_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "time-library"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "time-library"
    return Path.home() / ".local" / "share" / "time-library"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only R2 real-distribution workload audit"
    )
    parser.add_argument("--runtime-root", type=Path, default=_default_runtime_root())
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture-cutoff")
    capture_parser.add_argument("--cutoff-output", type=Path, required=True)

    key_parser = subparsers.add_parser("create-holdout-key")
    key_parser.add_argument("--holdout-key-output", type=Path, required=True)

    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--cutoff-input", type=Path, required=True)
    audit_parser.add_argument("--preregistration-input", type=Path, required=True)
    audit_parser.add_argument("--holdout-key-input", type=Path, required=True)
    audit_parser.add_argument("--report-output", type=Path, required=True)
    audit_parser.add_argument("--holdout-output", type=Path, required=True)
    audit_parser.add_argument("--run-receipt-output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "capture-cutoff":
        cutoff = capture_cutoff(args.runtime_root)
        validate_cutoff(cutoff)
        write_private_json(args.cutoff_output, cutoff, runtime_root=args.runtime_root)
        print(json.dumps({
            "ok": True,
            "cutoff_identity_sha256": cutoff["cutoff_identity_sha256"],
            "cutoff_file_sha256": file_sha256(args.cutoff_output),
        }, sort_keys=True))
        return 0

    if args.command == "create-holdout-key":
        create_holdout_key(args.holdout_key_output, runtime_root=args.runtime_root)
        print(json.dumps({
            "ok": True,
            "holdout_key_file_sha256": file_sha256(args.holdout_key_output),
        }, sort_keys=True))
        return 0

    cutoff_file_sha = file_sha256(args.cutoff_input)
    preregistration_file_sha = file_sha256(args.preregistration_input)
    key_file_sha = file_sha256(args.holdout_key_input)
    cutoff = json.loads(args.cutoff_input.read_text(encoding="utf-8"))
    preregistration = json.loads(
        args.preregistration_input.read_text(encoding="utf-8")
    )
    validate_cutoff(cutoff)
    provenance = validate_preregistration(
        preregistration,
        preregistration_file_sha256=preregistration_file_sha,
        cutoff=cutoff,
        cutoff_file_sha256=cutoff_file_sha,
        holdout_key_file_sha256=key_file_sha,
        actual_source_commit=_repository_head(Path(__file__).resolve().parents[1]),
    )
    key = load_holdout_key(args.holdout_key_input)
    started = time.perf_counter()
    report, holdout = run_audit(
        args.runtime_root,
        cutoff,
        holdout_key=key,
        selection_seed=str(preregistration["independent_seed"]),
        holdout_count=DEFAULT_HOLDOUT_COUNT,
        provenance=provenance,
        privacy_k=DEFAULT_PRIVACY_K,
    )
    elapsed = round(time.perf_counter() - started, 6)
    run_receipt = {
        "contract": RUN_RECEIPT_CONTRACT,
        "report_measurement_identity_sha256": report["measurement_identity_sha256"],
        "report_sha256": sha256_json(report),
        "holdout_manifest_sha256": holdout["holdout_manifest_sha256"],
        "elapsed_seconds": elapsed,
        "peak_rss": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "peak_rss_unit": "bytes" if sys.platform == "darwin" else "kibibytes",
        "read_only": True,
        "write_performed": False,
    }
    write_private_json(args.report_output, report, runtime_root=args.runtime_root)
    write_private_json(args.holdout_output, holdout, runtime_root=args.runtime_root)
    write_private_json(
        args.run_receipt_output, run_receipt, runtime_root=args.runtime_root
    )
    print(json.dumps({
        "ok": report["ok"],
        "ok_scope": report["ok_scope"],
        "decision": report["decision"],
        "records_processed": report["metrics"]["records"]["processing_outcome"][
            "counts"
        ].get("processed"),
        "candidates": report["metrics"]["candidates"]["total"],
        "engine_ambiguity_flagged": report["metrics"]["records"][
            "engine_ambiguity_flagged"
        ],
        "conservative_review_required": report["metrics"]["records"][
            "conservative_review_required"
        ],
        "measurement_identity_sha256": report["measurement_identity_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
