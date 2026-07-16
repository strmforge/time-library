#!/usr/bin/env python3
"""Prepare, freeze, and score a local-only R2 blind quality worksheet.

The prepare phase reconstructs the already selected opaque V15 holdout without
running the extractor. The freeze phase accepts independently authored labels
and binds them before prediction. The score phase reconstructs the worksheet
from the original cutoff and runs only the zero-model, fail-closed extractor.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from src import state_memory_extraction_candidate as candidate_rules
    from tools import r2_real_distribution_shadow_audit as shadow
    from tools import r2_state_extractor_eval as offline_eval
except Exception:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src import state_memory_extraction_candidate as candidate_rules
    from tools import r2_real_distribution_shadow_audit as shadow
    from tools import r2_state_extractor_eval as offline_eval


WORKSHEET_CONTRACT = "time_library.r2_blind_label_worksheet.v2026.7.15"
TOOL_CONTRACT = "time_library.r2_blind_quality_gate.v2026.7.15"
LABEL_DRAFT_CONTRACT = "time_library.r2_blind_label_draft.v2026.7.15"
FROZEN_LABELS_CONTRACT = "time_library.r2_blind_labels.v2026.7.15"
PRIVATE_REPORT_CONTRACT = "time_library.r2_blind_quality_private_report.v2026.7.15"
SHAREABLE_REPORT_CONTRACT = "time_library.r2_blind_quality_shareable_report.v2026.7.15"
LABEL_SIGNING_KEY_CONTRACT = "time_library.r2_blind_label_signing_key.v2026.7.15"
PIPELINE_SCOPE = "rule_first_zero_model_fail_closed"
V15_IDENTITY_PROFILE = "v15_20260715_fixed"
SYNTHETIC_TEST_IDENTITY_PROFILE = "synthetic_test_only"
V15_SOURCE_COMMIT = "7e64714bb74fcd225da3f3f6ff6ff214ea7ac27c"
V15_MEASUREMENT_IDENTITY_SHA256 = (
    "f4f9b6c6789ca140fb5198285345b5e9d4d7a54ca525761255c84b143ba7c325"
)
V15_HOLDOUT_FILE_SHA256 = (
    "b8964503ce1ff6207d656bd174a0a17ae64bd4b1c349a8c8f5480642c749a5c0"
)
V15_HOLDOUT_KEY_FILE_SHA256 = (
    "73f6a82bc2f33724316712a318a19f9ab57ecc599bd4396fcd9e4a7f62e927ad"
)
V15_HOLDOUT_KEY_ID_SHA256 = (
    "cc2be5b9631dea352dbb91b3c3e23e370ea4aca74b7e4f8ad2042ea5ed764916"
)
QUALITY_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "output" / "r2_blind_quality_gate_20260715"
QUALITY_PRIVATE_ROOT = QUALITY_OUTPUT_ROOT / "private"
WORKSHEET_PATH = QUALITY_PRIVATE_ROOT / "BLIND_WORKSHEET.json"
LABEL_DRAFT_PATH = QUALITY_PRIVATE_ROOT / "LABELS_DRAFT.json"
LABEL_SIGNING_KEY_PATH = QUALITY_PRIVATE_ROOT / "LABELER_SIGNING_KEY.json"
FROZEN_LABELS_PATH = QUALITY_PRIVATE_ROOT / "FROZEN_LABELS.json"
PRIVATE_REPORT_PATH = QUALITY_PRIVATE_ROOT / "PRIVATE_QUALITY_REPORT.json"
SHAREABLE_REPORT_PATH = QUALITY_OUTPUT_ROOT / "SHAREABLE_QUALITY_REPORT.json"
V15_HOLDOUT_KEY_PATH = (
    Path(__file__).resolve().parents[1]
    / "output"
    / "r2_real_distribution_shadow_20260715_v15"
    / "holdout_key_v15.json"
)

SEMANTIC_TYPES = {"claim", "event", "procedure", "preference"}
SHELVES = {"raw", "zhiyi", "xingce", "toolbook", "errata"}
STATE_ROLES = {
    "candidate",
    "active",
    "superseded",
    "transition",
    "conflicting",
    "unknown",
    "rejected",
}
TAINT_VALUES = {"trusted", "untrusted_content", "instruction_like", "unknown"}
LABEL_STATUSES = {"labeled", "unlabelable"}
UNLABELABLE_REASONS = {
    "insufficient_context",
    "source_unresolvable",
    "cross_record_context_required",
    "ambiguous_source",
    "other_with_note",
}
NO_ATOM_REASONS = {
    "no_durable_state",
    "boilerplate_only",
    "non_state_content",
    "other_with_note",
}
FORBIDDEN_LABEL_KEYS = {
    "prediction",
    "predictions",
    "predicted_atoms",
    "extractor_output",
    "rule_trace",
    "rule_traces",
    "ambiguities",
    "existing_record_kind",
    "record_kind",
    "benchmark_stratum",
}
TIME_RULE_IDS = [
    "raw_is_highest_authority",
    "source_refs_required_not_replacement",
    "events_remain_orderable",
    "unknown_must_remain_visible",
    "derived_sediment_must_reference_origin",
    "platforms_are_inlets_not_origin",
]
NON_CLAIMS = [
    "production State Memory shadow remains unauthorized",
    "canonical source-ref retention, resolvability, and semantic support are not measured",
    "projection spans are not raw-source byte spans",
    "single-record holdout does not measure cross-record conflict or supersession",
    "zero-model fail-closed scoring does not measure model-owned ambiguity resolution",
    "quality metrics do not authorize activation, installed sync, release, or LAN rollout",
]
WRITE_BOUNDARY = {
    "read_only": True,
    "model_call_performed": False,
    "network_call_performed": False,
    "production_shadow_write_performed": False,
    "memory_write_performed": False,
    "activation_performed": False,
}
UNSUPPORTED_QUALITY = {
    "canonical_source_ref_retention": "not_measured",
    "source_ref_resolvability": "not_measured",
    "source_ref_semantic_correctness": "not_measured",
    "raw_source_span_exactness": "not_measured",
    "cross_record_conflict_and_supersession": "not_measured",
    "model_owned_ambiguity_resolution": "not_measured",
}
TIME_RULE_DECISION = {"decision": "attached", "rule_ids": TIME_RULE_IDS}
BLINDNESS_POLICY = {
    "worksheet_contains_predictions": False,
    "worksheet_contains_rule_traces": False,
    "worksheet_contains_existing_record_kind": False,
    "labels_must_be_frozen_before_scoring": True,
    "labeler_must_be_independent_from_extractor_and_rule_author": True,
    "existing_record_kind_is_not_a_gold_label": True,
    "rules_and_same_author_fixtures_are_not_gold_labels": True,
}
QUALITY_STATUSES = {
    "blind_quality_metrics_computed_independence_and_chronology_attested_not_proven",
    "quality_not_measured_incomplete_independent_labels",
    "quality_not_measured_no_decidable_gold_atoms",
    "synthetic_fixture_not_quality_measurement",
}
QUALITY_GATE_CANDIDATE_STATUSES = {
    "ready_for_independent_verifier_and_owner_threshold_review",
    "not_ready_incomplete_independent_labels",
    "not_ready_no_decidable_gold_atoms",
    "not_ready_non_v15_identity",
}


class BlindQualityError(RuntimeError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_json(path: Path) -> Dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise BlindQualityError("json_non_finite_number_forbidden:" + value)

    def unique_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        value: Dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise BlindQualityError("json_duplicate_key_forbidden:" + key)
            value[key] = item
        return value

    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise BlindQualityError("json_input_invalid") from exc
    if not isinstance(value, dict):
        raise BlindQualityError("json_input_must_be_object")
    return value


def _valid_datetime(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _datetime_value(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _private_permissions(path: Path) -> None:
    try:
        mode = Path(path).stat().st_mode
    except FileNotFoundError as exc:
        raise BlindQualityError("private_input_missing") from exc
    except OSError as exc:
        raise BlindQualityError("private_input_unreadable") from exc
    if os.name != "nt" and mode & 0o077:
        raise BlindQualityError("private_input_permissions_too_broad")


def _self_digest(value: Dict[str, Any], field: str) -> str:
    clean = copy.deepcopy(value)
    clean.pop(field, None)
    return sha256_json(clean)


def _worksheet_evidence_payload(worksheet: Dict[str, Any]) -> Dict[str, Any]:
    clean = copy.deepcopy(worksheet)
    clean.pop("worksheet_evidence_sha256", None)
    clean.pop("worksheet_hmac_sha256", None)
    return clean


def _worksheet_hmac(worksheet: Dict[str, Any], key: bytes) -> str:
    clean = copy.deepcopy(worksheet)
    clean.pop("worksheet_hmac_sha256", None)
    return hmac.new(
        key,
        canonical_json(clean).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _has_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        if any(str(key) in FORBIDDEN_LABEL_KEYS for key in value):
            return True
        return any(_has_forbidden_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_forbidden_key(item) for item in value)
    return False


def _load_source_bundle(
    *,
    runtime_root: Path,
    cutoff_path: Path,
    holdout_key_path: Path,
    holdout_path: Path,
    measurement_report_path: Path,
    expected_measurement_identity_sha256: str,
    expected_holdout_file_sha256: str,
    expected_source_commit: Optional[str],
) -> Tuple[Dict[str, Any], Dict[str, Any], bytes, Dict[str, Any], Dict[str, Any]]:
    for path in (cutoff_path, holdout_key_path, holdout_path):
        _private_permissions(path)
    cutoff = _read_json(cutoff_path)
    holdout = _read_json(holdout_path)
    report = _read_json(measurement_report_path)
    shadow.validate_cutoff(cutoff)
    shadow.validate_holdout_manifest(holdout)
    provenance = report.get("provenance")
    privacy = report.get("privacy")
    if not isinstance(provenance, dict) or not isinstance(privacy, dict):
        raise BlindQualityError("measurement_report_shape_invalid")
    expected_count = provenance.get("holdout_exact_count")
    expected_k = privacy.get("k_anonymity_threshold")
    if not isinstance(expected_count, int) or not isinstance(expected_k, int):
        raise BlindQualityError("measurement_report_policy_invalid")
    shadow.validate_shareable_report(
        report,
        expected_privacy_k=expected_k,
        expected_holdout_count=expected_count,
    )
    if report.get("measurement_identity_sha256") != expected_measurement_identity_sha256:
        raise BlindQualityError("fixed_measurement_identity_mismatch")
    if file_sha256(holdout_path) != expected_holdout_file_sha256:
        raise BlindQualityError("fixed_holdout_file_digest_mismatch")
    if expected_source_commit is not None and provenance.get("source_commit") != expected_source_commit:
        raise BlindQualityError("fixed_source_commit_mismatch")
    if report.get("decision") != "NO_GO_PRODUCTION_SHADOW":
        raise BlindQualityError("measurement_report_product_gate_not_red")
    quality = report.get("quality")
    if not isinstance(quality, dict) or any(
        quality.get(name) != "not_measured"
        for name in (
            "coverage",
            "preservation",
            "semantic_accuracy",
            "state_role_accuracy",
        )
    ):
        raise BlindQualityError("measurement_report_quality_not_red")
    if report.get("holdout_manifest_sha256") != holdout.get("holdout_manifest_sha256"):
        raise BlindQualityError("holdout_report_binding_mismatch")
    records = holdout.get("records")
    if (
        not isinstance(records, list)
        or holdout.get("exact_count") != expected_count
        or holdout.get("holdout_count") != expected_count
        or len(records) != expected_count
        or holdout.get("selection_complete") is not True
        or holdout.get("contains_source_text") is not False
        or holdout.get("contains_text_hashes") is not False
        or holdout.get("contains_answer_labels") is not False
        or holdout.get("contains_private_paths_or_native_ids") is not False
        or holdout.get("independent_labels_status") != "not_measured"
        or holdout.get("local_only_not_shared_with_rule_author_or_antagonist") is not True
        or holdout.get("read_only") is not True
        or holdout.get("write_performed") is not False
    ):
        raise BlindQualityError("holdout_strict_policy_invalid")
    holdout_ids = [
        str(item.get("opaque_record_id") or "")
        for item in records
        if isinstance(item, dict)
    ]
    if len(holdout_ids) != expected_count or len(holdout_ids) != len(set(holdout_ids)):
        raise BlindQualityError("holdout_record_identity_invalid")
    if cutoff.get("cutoff_identity_sha256") != provenance.get("cutoff_identity_sha256"):
        raise BlindQualityError("cutoff_report_identity_mismatch")
    if holdout.get("source_cutoff_identity_sha256") != cutoff.get("cutoff_identity_sha256"):
        raise BlindQualityError("holdout_cutoff_identity_mismatch")
    if file_sha256(cutoff_path) != provenance.get("cutoff_file_sha256"):
        raise BlindQualityError("cutoff_file_digest_mismatch")
    if file_sha256(holdout_key_path) != provenance.get("holdout_key_file_sha256"):
        raise BlindQualityError("holdout_key_file_digest_mismatch")
    if file_sha256(Path(shadow.__file__)) != provenance.get("tool_sha256"):
        raise BlindQualityError("audit_tool_digest_mismatch")
    if file_sha256(Path(candidate_rules.__file__)) != provenance.get("extractor_sha256"):
        raise BlindQualityError("extractor_digest_mismatch")
    key = shadow.load_holdout_key(holdout_key_path)
    return cutoff, holdout, key, report, provenance


def _source_ref_slots(
    key: bytes,
    opaque_record_id: str,
    refs: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    slots = []
    for index, ref in enumerate(refs):
        slot_id = "ref-" + shadow._hmac_hex(
            key,
            "blind-label-source-ref",
            opaque_record_id,
            index,
            canonical_json(ref),
        )[:32]
        slots.append({"source_ref_id": slot_id, "source_ref": copy.deepcopy(ref)})
    return slots


def _source_text_projection(record: Dict[str, Any]) -> str:
    """Rebuild only the V15 text projection, without candidate segmentation."""
    summary = str(record.get("summary") or "").strip()
    detail = str(record.get("detail") or "").strip()
    left = summary.casefold()
    right = detail.casefold()
    if left and right and left == right:
        return summary
    if left and right and left in right:
        return detail
    if left and right and right in left:
        return summary
    return "\n".join(value for value in (summary, detail) if value)


def prepare_worksheet(
    *,
    runtime_root: Path,
    cutoff_path: Path,
    holdout_key_path: Path,
    holdout_path: Path,
    measurement_report_path: Path,
    identity_profile: str = V15_IDENTITY_PROFILE,
    expected_measurement_identity_sha256: Optional[str] = None,
    expected_holdout_file_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    if identity_profile == V15_IDENTITY_PROFILE:
        expected_measurement_identity_sha256 = V15_MEASUREMENT_IDENTITY_SHA256
        expected_holdout_file_sha256 = V15_HOLDOUT_FILE_SHA256
        expected_source_commit: Optional[str] = V15_SOURCE_COMMIT
    elif identity_profile == SYNTHETIC_TEST_IDENTITY_PROFILE:
        if not expected_measurement_identity_sha256 or not expected_holdout_file_sha256:
            raise BlindQualityError("synthetic_test_identity_values_required")
        expected_source_commit = None
    else:
        raise BlindQualityError("identity_profile_invalid")
    cutoff, holdout, key, report, provenance = _load_source_bundle(
        runtime_root=runtime_root,
        cutoff_path=cutoff_path,
        holdout_key_path=holdout_key_path,
        holdout_path=holdout_path,
        measurement_report_path=measurement_report_path,
        expected_measurement_identity_sha256=expected_measurement_identity_sha256,
        expected_holdout_file_sha256=expected_holdout_file_sha256,
        expected_source_commit=expected_source_commit,
    )
    holdout_ids = [str(item.get("opaque_record_id") or "") for item in holdout["records"]]
    if len(holdout_ids) != len(set(holdout_ids)):
        raise BlindQualityError("holdout_duplicate_record_id")
    selected = set(holdout_ids)
    found: Dict[str, Dict[str, Any]] = {}
    for kind, line_number, record, line_error in shadow._iter_cutoff_lines(
        runtime_root, cutoff
    ):
        if line_error or not isinstance(record, dict):
            continue
        refs = shadow._parse_source_refs(record.get("source_refs"))
        if not refs:
            continue
        source_text = _source_text_projection(record)
        if not source_text:
            continue
        recorded_at, _mode = shadow._normalized_recorded_at(record.get("extracted_at"))
        if not recorded_at:
            continue
        observed_at, _fallback = shadow._observed_at(refs, recorded_at)
        if not shadow._valid_datetime(observed_at):
            continue
        record_token = shadow._hmac_hex(
            key,
            "record",
            cutoff["cutoff_identity_sha256"],
            kind,
            line_number,
            str(record.get("exp_id") or ""),
            source_text,
        )
        opaque_record_id = "record-" + record_token[:32]
        if opaque_record_id not in selected:
            continue
        if opaque_record_id in found:
            raise BlindQualityError("worksheet_opaque_record_collision")
        found[opaque_record_id] = {
            "opaque_record_id": opaque_record_id,
            "source_text": source_text,
            "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            "observed_at": observed_at,
            "recorded_at": recorded_at,
            "source_refs": _source_ref_slots(key, opaque_record_id, refs),
        }
    if set(found) != selected:
        raise BlindQualityError("worksheet_holdout_reconstruction_incomplete")
    records = [found[record_id] for record_id in holdout_ids]
    worksheet = {
        "contract": WORKSHEET_CONTRACT,
        "source_measurement": {
            "identity_profile": identity_profile,
            "source_commit": provenance["source_commit"],
            "measurement_identity_sha256": report["measurement_identity_sha256"],
            "expected_measurement_identity_sha256": expected_measurement_identity_sha256,
            "report_file_sha256": file_sha256(measurement_report_path),
            "holdout_file_sha256": file_sha256(holdout_path),
            "expected_holdout_file_sha256": expected_holdout_file_sha256,
            "holdout_key_file_sha256": file_sha256(holdout_key_path),
            "privacy_k": int(report["privacy"]["k_anonymity_threshold"]),
            "holdout_manifest_sha256": holdout["holdout_manifest_sha256"],
            "cutoff_file_sha256": file_sha256(cutoff_path),
            "cutoff_identity_sha256": cutoff["cutoff_identity_sha256"],
            "audit_contract": report["contract"],
            "audit_sha256": provenance["tool_sha256"],
            "extractor_contract": provenance["extractor_contract"],
            "extractor_sha256": provenance["extractor_sha256"],
            "quality_tool_contract": TOOL_CONTRACT,
            "quality_tool_sha256": file_sha256(Path(__file__)),
        },
        "blindness_policy": copy.deepcopy(BLINDNESS_POLICY),
        "record_count": len(records),
        "records": records,
        "contains_private_source_text": True,
        "contains_private_source_refs": True,
        "contains_predictions": False,
        "contains_rule_metadata": False,
        "existing_record_kind_emitted": False,
        "local_only": True,
        "read_only": True,
        "write_performed": False,
    }
    worksheet["worksheet_evidence_sha256"] = sha256_json(
        _worksheet_evidence_payload(worksheet)
    )
    worksheet["worksheet_hmac_sha256"] = _worksheet_hmac(worksheet, key)
    validate_worksheet(worksheet)
    verify_worksheet_authentication(worksheet, key)
    return worksheet


def _valid_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def validate_source_measurement(source_measurement: object) -> None:
    expected_keys = {
        "identity_profile",
        "source_commit",
        "measurement_identity_sha256",
        "expected_measurement_identity_sha256",
        "report_file_sha256",
        "holdout_file_sha256",
        "expected_holdout_file_sha256",
        "holdout_key_file_sha256",
        "privacy_k",
        "holdout_manifest_sha256",
        "cutoff_file_sha256",
        "cutoff_identity_sha256",
        "audit_contract",
        "audit_sha256",
        "extractor_contract",
        "extractor_sha256",
        "quality_tool_contract",
        "quality_tool_sha256",
    }
    if not isinstance(source_measurement, dict) or set(source_measurement) != expected_keys:
        raise BlindQualityError("source_measurement_allowlist_failed")
    if (
        source_measurement.get("measurement_identity_sha256")
        != source_measurement.get("expected_measurement_identity_sha256")
        or source_measurement.get("holdout_file_sha256")
        != source_measurement.get("expected_holdout_file_sha256")
    ):
        raise BlindQualityError("source_measurement_fixed_identity_mismatch")
    identity_profile = source_measurement.get("identity_profile")
    if identity_profile not in {V15_IDENTITY_PROFILE, SYNTHETIC_TEST_IDENTITY_PROFILE}:
        raise BlindQualityError("source_measurement_identity_profile_invalid")
    if identity_profile == V15_IDENTITY_PROFILE and (
        source_measurement.get("source_commit") != V15_SOURCE_COMMIT
        or source_measurement.get("measurement_identity_sha256")
        != V15_MEASUREMENT_IDENTITY_SHA256
        or source_measurement.get("holdout_file_sha256") != V15_HOLDOUT_FILE_SHA256
        or source_measurement.get("holdout_key_file_sha256")
        != V15_HOLDOUT_KEY_FILE_SHA256
        or source_measurement.get("privacy_k") != shadow.DEFAULT_PRIVACY_K
    ):
        raise BlindQualityError("source_measurement_v15_identity_invalid")
    privacy_k = source_measurement.get("privacy_k")
    if not isinstance(privacy_k, int) or isinstance(privacy_k, bool) or privacy_k < 1:
        raise BlindQualityError("source_measurement_privacy_k_invalid")
    source_commit = str(source_measurement.get("source_commit") or "")
    if len(source_commit) != 40 or any(
        char not in "0123456789abcdef" for char in source_commit
    ):
        raise BlindQualityError("source_measurement_commit_invalid")
    for name in (
        "measurement_identity_sha256",
        "expected_measurement_identity_sha256",
        "report_file_sha256",
        "holdout_file_sha256",
        "expected_holdout_file_sha256",
        "holdout_key_file_sha256",
        "holdout_manifest_sha256",
        "cutoff_file_sha256",
        "cutoff_identity_sha256",
        "audit_sha256",
        "extractor_sha256",
        "quality_tool_sha256",
    ):
        if not _valid_sha256(source_measurement.get(name)):
            raise BlindQualityError("source_measurement_digest_invalid:" + name)
    if (
        source_measurement.get("audit_contract") != shadow.CONTRACT
        or source_measurement.get("extractor_contract")
        != candidate_rules.HYBRID_EXTRACTION_CONTRACT
        or source_measurement.get("quality_tool_contract") != TOOL_CONTRACT
    ):
        raise BlindQualityError("source_measurement_contract_invalid")
    if source_measurement.get("audit_sha256") != file_sha256(Path(shadow.__file__)):
        raise BlindQualityError("source_measurement_audit_digest_mismatch")
    if source_measurement.get("extractor_sha256") != file_sha256(
        Path(candidate_rules.__file__)
    ):
        raise BlindQualityError("source_measurement_extractor_digest_mismatch")
    if source_measurement.get("quality_tool_sha256") != file_sha256(Path(__file__)):
        raise BlindQualityError("source_measurement_quality_tool_digest_mismatch")


def validate_worksheet(worksheet: Dict[str, Any]) -> None:
    expected_keys = {
        "contract",
        "source_measurement",
        "blindness_policy",
        "record_count",
        "records",
        "contains_private_source_text",
        "contains_private_source_refs",
        "contains_predictions",
        "contains_rule_metadata",
        "existing_record_kind_emitted",
        "local_only",
        "read_only",
        "write_performed",
        "worksheet_evidence_sha256",
        "worksheet_hmac_sha256",
    }
    if not isinstance(worksheet, dict) or set(worksheet) != expected_keys:
        raise BlindQualityError("worksheet_allowlist_failed")
    if worksheet.get("contract") != WORKSHEET_CONTRACT:
        raise BlindQualityError("worksheet_contract_invalid")
    if worksheet.get("worksheet_evidence_sha256") != sha256_json(
        _worksheet_evidence_payload(worksheet)
    ):
        raise BlindQualityError("worksheet_digest_invalid")
    if not _valid_sha256(worksheet.get("worksheet_hmac_sha256")):
        raise BlindQualityError("worksheet_hmac_shape_invalid")
    if any(
        worksheet.get(name) is not expected
        for name, expected in (
            ("contains_private_source_text", True),
            ("contains_private_source_refs", True),
            ("contains_predictions", False),
            ("contains_rule_metadata", False),
            ("existing_record_kind_emitted", False),
            ("local_only", True),
            ("read_only", True),
            ("write_performed", False),
        )
    ):
        raise BlindQualityError("worksheet_policy_invalid")
    if worksheet.get("blindness_policy") != BLINDNESS_POLICY:
        raise BlindQualityError("worksheet_blindness_policy_invalid")
    validate_source_measurement(worksheet.get("source_measurement"))
    records = worksheet.get("records")
    if not isinstance(records, list) or worksheet.get("record_count") != len(records):
        raise BlindQualityError("worksheet_record_count_invalid")
    seen = set()
    for record in records:
        expected_record_keys = {
            "opaque_record_id",
            "source_text",
            "source_text_sha256",
            "observed_at",
            "recorded_at",
            "source_refs",
        }
        if not isinstance(record, dict) or set(record) != expected_record_keys:
            raise BlindQualityError("worksheet_record_allowlist_failed")
        record_id = str(record.get("opaque_record_id") or "")
        if not record_id.startswith("record-") or len(record_id) != 39 or record_id in seen:
            raise BlindQualityError("worksheet_record_id_invalid")
        seen.add(record_id)
        source_text = record.get("source_text")
        if not isinstance(source_text, str) or not source_text.strip():
            raise BlindQualityError("worksheet_source_text_invalid")
        if record.get("source_text_sha256") != hashlib.sha256(
            source_text.encode("utf-8")
        ).hexdigest():
            raise BlindQualityError("worksheet_source_text_digest_invalid")
        if not _valid_datetime(record.get("observed_at")) or not _valid_datetime(
            record.get("recorded_at")
        ):
            raise BlindQualityError("worksheet_time_invalid")
        refs = record.get("source_refs")
        if not isinstance(refs, list) or not refs:
            raise BlindQualityError("worksheet_source_refs_missing")
        ref_ids = set()
        for item in refs:
            if not isinstance(item, dict) or set(item) != {"source_ref_id", "source_ref"}:
                raise BlindQualityError("worksheet_source_ref_allowlist_failed")
            ref_id = str(item.get("source_ref_id") or "")
            if not ref_id.startswith("ref-") or len(ref_id) != 36 or ref_id in ref_ids:
                raise BlindQualityError("worksheet_source_ref_id_invalid")
            ref_ids.add(ref_id)
            if not isinstance(item.get("source_ref"), dict):
                raise BlindQualityError("worksheet_source_ref_invalid")
    if _has_forbidden_key(worksheet.get("records")):
        raise BlindQualityError("worksheet_prediction_or_rule_leak")


def verify_worksheet_authentication(
    worksheet: Dict[str, Any],
    authentication_key: bytes,
) -> None:
    validate_worksheet(worksheet)
    if not isinstance(authentication_key, bytes) or len(authentication_key) != 32:
        raise BlindQualityError("worksheet_authentication_key_invalid")
    profile = worksheet["source_measurement"]["identity_profile"]
    if profile == V15_IDENTITY_PROFILE and hashlib.sha256(
        authentication_key
    ).hexdigest() != V15_HOLDOUT_KEY_ID_SHA256:
        raise BlindQualityError("worksheet_v15_authentication_key_mismatch")
    if worksheet.get("worksheet_hmac_sha256") != _worksheet_hmac(
        worksheet, authentication_key
    ):
        raise BlindQualityError("worksheet_hmac_invalid")


def make_label_draft(worksheet: Dict[str, Any]) -> Dict[str, Any]:
    validate_worksheet(worksheet)
    return {
        "contract": LABEL_DRAFT_CONTRACT,
        "worksheet_evidence_sha256": worksheet["worksheet_evidence_sha256"],
        "worksheet_hmac_sha256": worksheet["worksheet_hmac_sha256"],
        "labeler_attestation": {
            "labeler_id": "",
            "label_source": "human_independent_review",
            "completed_at": "",
            "independent_from_extractor_and_rule_author": False,
            "predictions_unseen_before_freeze": False,
            "existing_record_kind_not_used_as_gold": False,
            "rules_and_same_author_fixtures_not_used_as_gold": False,
        },
        "record_count": worksheet["record_count"],
        "records": [
            {
                "opaque_record_id": record["opaque_record_id"],
                "label_status": "pending",
                "unlabelable_reason": "",
                "unlabelable_note": "",
                "no_atom_reason": "",
                "closed_world_review_complete": False,
                "reviewed_source_text_sha256": record["source_text_sha256"],
                "expected_atoms": [],
            }
            for record in worksheet["records"]
        ],
        "instructions": {
            "atom_required_fields": [
                "label_id",
                "content",
                "source_span",
                "semantic_type",
                "state_role",
                "shelf",
                "taint",
                "valid_from",
                "valid_to",
                "supporting_source_ref_ids",
                "must_preserve",
            ],
            "source_span_rule": "null_allowed_only_when_content_is_unique_in_source_text",
            "zero_atom_rule": "labeled records with no atoms require no_atom_reason",
            "unknown_rule": "insufficient evidence must be unlabelable, never guessed",
        },
        "contains_predictions": False,
        "labels_frozen": False,
        "local_only": True,
    }


def _validate_attestation(value: object) -> Dict[str, Any]:
    expected = {
        "labeler_id",
        "label_source",
        "completed_at",
        "independent_from_extractor_and_rule_author",
        "predictions_unseen_before_freeze",
        "existing_record_kind_not_used_as_gold",
        "rules_and_same_author_fixtures_not_used_as_gold",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise BlindQualityError("labeler_attestation_allowlist_failed")
    labeler_id = str(value.get("labeler_id") or "").strip()
    if not labeler_id or labeler_id.casefold() in {
        "codex",
        "rule_author",
        "extractor_author",
        "same_author",
    }:
        raise BlindQualityError("independent_labeler_id_invalid")
    if value.get("label_source") != "human_independent_review":
        raise BlindQualityError("independent_label_source_invalid")
    if not _valid_datetime(value.get("completed_at")):
        raise BlindQualityError("label_completion_time_invalid")
    for name in (
        "independent_from_extractor_and_rule_author",
        "predictions_unseen_before_freeze",
        "existing_record_kind_not_used_as_gold",
        "rules_and_same_author_fixtures_not_used_as_gold",
    ):
        if value.get(name) is not True:
            raise BlindQualityError("labeler_attestation_incomplete:" + name)
    return copy.deepcopy(value)


def load_label_signing_key(path: Path) -> bytes:
    if not Path(path).exists():
        raise BlindQualityError(
            "label_signing_key_missing_independent_labeler_action_required"
        )
    _private_permissions(path)
    value = _read_json(path)
    if set(value) != {"contract", "key_hex"} or value.get("contract") != LABEL_SIGNING_KEY_CONTRACT:
        raise BlindQualityError("label_signing_key_contract_invalid")
    try:
        key = bytes.fromhex(str(value.get("key_hex") or ""))
    except ValueError as exc:
        raise BlindQualityError("label_signing_key_invalid") from exc
    if len(key) != 32:
        raise BlindQualityError("label_signing_key_invalid")
    return key


def _freeze_hmac(value: Dict[str, Any], signing_key: bytes) -> str:
    clean = copy.deepcopy(value)
    clean.pop("frozen_labels_sha256", None)
    clean.pop("freeze_hmac_sha256", None)
    return hmac.new(
        signing_key,
        canonical_json(clean).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _unique_quote_span(source_text: str, quote: str) -> Dict[str, Any]:
    first = source_text.find(quote)
    if first < 0:
        raise BlindQualityError("label_content_not_in_source")
    if source_text.find(quote, first + 1) >= 0:
        raise BlindQualityError("label_content_not_unique_span_required")
    byte_start = len(source_text[:first].encode("utf-8"))
    byte_end = byte_start + len(quote.encode("utf-8"))
    return {"byte_start": byte_start, "byte_end": byte_end, "text": quote}


def _normalize_span(source_text: str, content: str, value: object) -> Dict[str, Any]:
    if value is None:
        return _unique_quote_span(source_text, content)
    if not isinstance(value, dict) or set(value) != {"byte_start", "byte_end", "text"}:
        raise BlindQualityError("label_source_span_shape_invalid")
    start = value.get("byte_start")
    end = value.get("byte_end")
    text = value.get("text")
    if isinstance(start, bool) or isinstance(end, bool):
        raise BlindQualityError("label_source_span_bounds_invalid")
    if not isinstance(start, int) or not isinstance(end, int) or text != content:
        raise BlindQualityError("label_source_span_invalid")
    source_bytes = source_text.encode("utf-8")
    if not (0 <= start < end <= len(source_bytes)):
        raise BlindQualityError("label_source_span_bounds_invalid")
    if source_bytes[start:end] != content.encode("utf-8"):
        raise BlindQualityError("label_source_span_not_exact")
    return {"byte_start": start, "byte_end": end, "text": content}


def _normalize_atom(
    atom: object,
    *,
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    expected = {
        "label_id",
        "content",
        "source_span",
        "semantic_type",
        "state_role",
        "shelf",
        "taint",
        "valid_from",
        "valid_to",
        "supporting_source_ref_ids",
        "must_preserve",
    }
    if not isinstance(atom, dict) or set(atom) != expected:
        raise BlindQualityError("label_atom_allowlist_failed")
    label_id = str(atom.get("label_id") or "").strip()
    content = str(atom.get("content") or "")
    if not label_id or not content:
        raise BlindQualityError("label_atom_identity_or_content_missing")
    if atom.get("semantic_type") not in SEMANTIC_TYPES:
        raise BlindQualityError("label_semantic_type_invalid")
    if atom.get("state_role") not in STATE_ROLES:
        raise BlindQualityError("label_state_role_invalid")
    if atom.get("shelf") not in SHELVES:
        raise BlindQualityError("label_shelf_invalid")
    if atom.get("taint") not in TAINT_VALUES:
        raise BlindQualityError("label_taint_invalid")
    valid_from = atom.get("valid_from")
    valid_to = atom.get("valid_to")
    if not _valid_datetime(valid_from):
        raise BlindQualityError("label_valid_from_invalid")
    if valid_to is not None and not _valid_datetime(valid_to):
        raise BlindQualityError("label_valid_to_invalid")
    if valid_to is not None and _datetime_value(valid_to) < _datetime_value(valid_from):
        raise BlindQualityError("label_valid_interval_invalid")
    available_refs = {
        str(item["source_ref_id"])
        for item in evidence["source_refs"]
        if isinstance(item, dict)
    }
    source_ref_ids = atom.get("supporting_source_ref_ids")
    if (
        not isinstance(source_ref_ids, list)
        or not source_ref_ids
        or len(source_ref_ids) != len(set(source_ref_ids))
        or any(str(ref_id) not in available_refs for ref_id in source_ref_ids)
    ):
        raise BlindQualityError("label_supporting_source_refs_invalid")
    if not isinstance(atom.get("must_preserve"), bool):
        raise BlindQualityError("label_must_preserve_invalid")
    span = _normalize_span(evidence["source_text"], content, atom.get("source_span"))
    return {
        "label_id": label_id,
        "content": content,
        "source_span": span,
        "semantic_type": atom["semantic_type"],
        "state_role": atom["state_role"],
        "shelf": atom["shelf"],
        "taint": atom["taint"],
        "observed_at": evidence["observed_at"],
        "recorded_at": evidence["recorded_at"],
        "valid_from": valid_from,
        "valid_to": valid_to,
        "supporting_source_ref_ids": [str(value) for value in source_ref_ids],
        "must_preserve": atom["must_preserve"],
    }


def freeze_labels(
    worksheet: Dict[str, Any],
    draft: Dict[str, Any],
    *,
    signing_key: bytes,
    worksheet_authentication_key: bytes,
    _validate_output: bool = True,
) -> Dict[str, Any]:
    verify_worksheet_authentication(worksheet, worksheet_authentication_key)
    if not isinstance(signing_key, bytes) or len(signing_key) != 32:
        raise BlindQualityError("label_signing_key_invalid")
    if hmac.compare_digest(signing_key, worksheet_authentication_key):
        raise BlindQualityError("label_signing_key_must_differ_from_holdout_key")
    expected_draft_keys = {
        "contract",
        "worksheet_evidence_sha256",
        "worksheet_hmac_sha256",
        "labeler_attestation",
        "record_count",
        "records",
        "instructions",
        "contains_predictions",
        "labels_frozen",
        "local_only",
    }
    if not isinstance(draft, dict) or set(draft) != expected_draft_keys:
        raise BlindQualityError("label_draft_allowlist_failed")
    if draft.get("contract") != LABEL_DRAFT_CONTRACT:
        raise BlindQualityError("label_draft_contract_invalid")
    if draft.get("worksheet_evidence_sha256") != worksheet["worksheet_evidence_sha256"]:
        raise BlindQualityError("label_draft_worksheet_mismatch")
    if draft.get("worksheet_hmac_sha256") != worksheet["worksheet_hmac_sha256"]:
        raise BlindQualityError("label_draft_worksheet_authentication_mismatch")
    if (
        draft.get("contains_predictions") is not False
        or draft.get("labels_frozen") is not False
        or draft.get("local_only") is not True
        or _has_forbidden_key(draft)
    ):
        raise BlindQualityError("label_draft_blindness_policy_invalid")
    if draft.get("instructions") != make_label_draft(worksheet)["instructions"]:
        raise BlindQualityError("label_draft_instructions_changed")
    attestation = _validate_attestation(draft.get("labeler_attestation"))
    evidence_by_id = {
        str(record["opaque_record_id"]): record for record in worksheet["records"]
    }
    draft_records = draft.get("records")
    if not isinstance(draft_records, list) or draft.get("record_count") != len(draft_records):
        raise BlindQualityError("label_draft_record_count_invalid")
    by_id: Dict[str, Dict[str, Any]] = {}
    expected_record_keys = {
        "opaque_record_id",
        "label_status",
        "unlabelable_reason",
        "unlabelable_note",
        "no_atom_reason",
        "closed_world_review_complete",
        "reviewed_source_text_sha256",
        "expected_atoms",
    }
    for item in draft_records:
        if not isinstance(item, dict) or set(item) != expected_record_keys:
            raise BlindQualityError("label_record_allowlist_failed")
        record_id = str(item.get("opaque_record_id") or "")
        if record_id in by_id:
            raise BlindQualityError("duplicate_label_record_id")
        by_id[record_id] = item
    if set(by_id) != set(evidence_by_id):
        raise BlindQualityError("label_record_set_mismatch")
    frozen_records = []
    unlabelable_count = 0
    for evidence in worksheet["records"]:
        record_id = str(evidence["opaque_record_id"])
        item = by_id[record_id]
        status = item.get("label_status")
        if status not in LABEL_STATUSES:
            raise BlindQualityError("label_status_incomplete_or_invalid")
        if item.get("closed_world_review_complete") is not True:
            raise BlindQualityError("closed_world_review_incomplete")
        if item.get("reviewed_source_text_sha256") != evidence["source_text_sha256"]:
            raise BlindQualityError("reviewed_source_identity_mismatch")
        atoms_value = item.get("expected_atoms")
        if not isinstance(atoms_value, list):
            raise BlindQualityError("expected_atoms_invalid")
        if status == "unlabelable":
            reason = str(item.get("unlabelable_reason") or "")
            note = str(item.get("unlabelable_note") or "").strip()
            if reason not in UNLABELABLE_REASONS or atoms_value:
                raise BlindQualityError("unlabelable_record_invalid")
            if reason == "other_with_note" and not note:
                raise BlindQualityError("unlabelable_note_required")
            if item.get("no_atom_reason"):
                raise BlindQualityError("unlabelable_no_atom_reason_forbidden")
            unlabelable_count += 1
            frozen_records.append({
                "opaque_record_id": record_id,
                "label_status": status,
                "unlabelable_reason": reason,
                "unlabelable_note": note,
                "no_atom_reason": "",
                "closed_world_review_complete": True,
                "reviewed_source_text_sha256": evidence["source_text_sha256"],
                "expected_atoms": [],
            })
            continue
        if item.get("unlabelable_reason") or item.get("unlabelable_note"):
            raise BlindQualityError("labeled_record_has_unlabelable_fields")
        no_atom_reason = str(item.get("no_atom_reason") or "")
        if atoms_value and no_atom_reason:
            raise BlindQualityError("labeled_atoms_conflict_with_no_atom_reason")
        if not atoms_value and no_atom_reason not in NO_ATOM_REASONS:
            raise BlindQualityError("zero_atom_reason_required")
        atoms = [
            _normalize_atom(atom, evidence=evidence) for atom in atoms_value
        ]
        label_ids = [str(atom["label_id"]) for atom in atoms]
        if len(label_ids) != len(set(label_ids)):
            raise BlindQualityError("duplicate_label_atom_id")
        atoms.sort(
            key=lambda atom: (
                int(atom["source_span"]["byte_start"]),
                int(atom["source_span"]["byte_end"]),
                str(atom["label_id"]),
            )
        )
        frozen_records.append({
            "opaque_record_id": record_id,
            "label_status": status,
            "unlabelable_reason": "",
            "unlabelable_note": "",
            "no_atom_reason": no_atom_reason,
            "closed_world_review_complete": True,
            "reviewed_source_text_sha256": evidence["source_text_sha256"],
            "expected_atoms": atoms,
        })
    frozen = {
        "contract": FROZEN_LABELS_CONTRACT,
        "worksheet_evidence_sha256": worksheet["worksheet_evidence_sha256"],
        "worksheet_hmac_sha256": worksheet["worksheet_hmac_sha256"],
        "labeler_attestation": attestation,
        "record_count": len(frozen_records),
        "records": frozen_records,
        "labels_complete": unlabelable_count == 0,
        "unlabelable_count": unlabelable_count,
        "contains_predictions": False,
        "labels_frozen": True,
        "local_only": True,
        "read_only": True,
        "write_performed": False,
        "independence_proof_status": "attested_not_source_proven",
        "labeler_signing_key_sha256": hashlib.sha256(signing_key).hexdigest(),
    }
    frozen["freeze_hmac_sha256"] = _freeze_hmac(frozen, signing_key)
    frozen["frozen_labels_sha256"] = sha256_json(frozen)
    if _validate_output:
        validate_frozen_labels(
            worksheet,
            frozen,
            signing_key=signing_key,
            worksheet_authentication_key=worksheet_authentication_key,
        )
    return frozen


def validate_frozen_labels(
    worksheet: Dict[str, Any],
    frozen: Dict[str, Any],
    *,
    signing_key: bytes,
    worksheet_authentication_key: bytes,
) -> None:
    verify_worksheet_authentication(worksheet, worksheet_authentication_key)
    expected = {
        "contract",
        "worksheet_evidence_sha256",
        "worksheet_hmac_sha256",
        "labeler_attestation",
        "record_count",
        "records",
        "labels_complete",
        "unlabelable_count",
        "contains_predictions",
        "labels_frozen",
        "local_only",
        "read_only",
        "write_performed",
        "independence_proof_status",
        "labeler_signing_key_sha256",
        "freeze_hmac_sha256",
        "frozen_labels_sha256",
    }
    if not isinstance(frozen, dict) or set(frozen) != expected:
        raise BlindQualityError("frozen_labels_allowlist_failed")
    if frozen.get("contract") != FROZEN_LABELS_CONTRACT:
        raise BlindQualityError("frozen_labels_contract_invalid")
    if frozen.get("frozen_labels_sha256") != _self_digest(
        frozen, "frozen_labels_sha256"
    ):
        raise BlindQualityError("frozen_labels_digest_invalid")
    if not isinstance(signing_key, bytes) or len(signing_key) != 32:
        raise BlindQualityError("label_signing_key_invalid")
    if frozen.get("labeler_signing_key_sha256") != hashlib.sha256(signing_key).hexdigest():
        raise BlindQualityError("label_signing_key_identity_mismatch")
    if frozen.get("freeze_hmac_sha256") != _freeze_hmac(frozen, signing_key):
        raise BlindQualityError("frozen_labels_hmac_invalid")
    if frozen.get("independence_proof_status") != "attested_not_source_proven":
        raise BlindQualityError("label_independence_boundary_invalid")
    if frozen.get("worksheet_evidence_sha256") != worksheet["worksheet_evidence_sha256"]:
        raise BlindQualityError("frozen_labels_worksheet_mismatch")
    if frozen.get("worksheet_hmac_sha256") != worksheet["worksheet_hmac_sha256"]:
        raise BlindQualityError("frozen_labels_worksheet_authentication_mismatch")
    if any(
        frozen.get(name) is not expected_value
        for name, expected_value in (
            ("contains_predictions", False),
            ("labels_frozen", True),
            ("local_only", True),
            ("read_only", True),
            ("write_performed", False),
        )
    ) or _has_forbidden_key(frozen):
        raise BlindQualityError("frozen_labels_policy_invalid")
    _validate_attestation(frozen.get("labeler_attestation"))
    records = frozen.get("records")
    if not isinstance(records, list) or frozen.get("record_count") != len(records):
        raise BlindQualityError("frozen_labels_record_count_invalid")
    expected_ids = [str(item["opaque_record_id"]) for item in worksheet["records"]]
    actual_ids = [
        str(item.get("opaque_record_id") or "")
        for item in records
        if isinstance(item, dict)
    ]
    if actual_ids != expected_ids:
        raise BlindQualityError("frozen_labels_record_order_or_set_invalid")
    unlabelable_count = sum(
        1 for item in records if isinstance(item, dict) and item.get("label_status") == "unlabelable"
    )
    if frozen.get("unlabelable_count") != unlabelable_count:
        raise BlindQualityError("frozen_labels_unlabelable_count_invalid")
    if frozen.get("labels_complete") is not (unlabelable_count == 0):
        raise BlindQualityError("frozen_labels_completion_invalid")
    draft = {
        "contract": LABEL_DRAFT_CONTRACT,
        "worksheet_evidence_sha256": frozen["worksheet_evidence_sha256"],
        "worksheet_hmac_sha256": frozen["worksheet_hmac_sha256"],
        "labeler_attestation": copy.deepcopy(frozen["labeler_attestation"]),
        "record_count": frozen["record_count"],
        "records": [],
        "instructions": copy.deepcopy(make_label_draft(worksheet)["instructions"]),
        "contains_predictions": False,
        "labels_frozen": False,
        "local_only": True,
    }
    for item in records:
        if not isinstance(item, dict):
            raise BlindQualityError("frozen_label_record_invalid")
        restored = copy.deepcopy(item)
        for atom in restored.get("expected_atoms") or []:
            if not isinstance(atom, dict):
                raise BlindQualityError("frozen_label_atom_invalid")
            atom.pop("observed_at", None)
            atom.pop("recorded_at", None)
        draft["records"].append(restored)
    regenerated = freeze_labels(
        worksheet,
        draft,
        signing_key=signing_key,
        worksheet_authentication_key=worksheet_authentication_key,
        _validate_output=False,
    )
    if regenerated != frozen:
        raise BlindQualityError("frozen_labels_not_canonical")


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 6) if denominator else None


def _span_key(atom: Dict[str, Any]) -> Tuple[int, int, str]:
    span = atom.get("source_span") if isinstance(atom, dict) else None
    if not isinstance(span, dict):
        return (-1, -1, "")
    try:
        return (int(span.get("byte_start")), int(span.get("byte_end")), str(span.get("text") or ""))
    except (TypeError, ValueError):
        return (-1, -1, "")


def _score_record(
    evidence: Dict[str, Any],
    label: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    source_input = {
        "recorded_at": evidence["recorded_at"],
        "sources": [{
            "source_ref_id": evidence["opaque_record_id"],
            "observed_at": evidence["observed_at"],
            "text": evidence["source_text"],
        }],
    }
    plan = candidate_rules.build_hybrid_plan(source_input)
    resolved = candidate_rules.apply_ambiguity_response(plan, {"decisions": []})
    actual = [item for item in resolved.get("atoms") or [] if isinstance(item, dict)]
    actual.sort(key=lambda atom: (_span_key(atom), str(atom.get("atom_id") or "")))
    prediction = {
        "opaque_record_id": evidence["opaque_record_id"],
        "candidate_count": int(plan.get("candidate_count") or 0),
        "ambiguity_count": int(plan.get("ambiguity_count") or 0),
        "unresolved_errors": list(resolved.get("errors") or []),
        "atoms": copy.deepcopy(actual),
    }
    if label.get("label_status") != "labeled":
        return prediction, {
            "opaque_record_id": evidence["opaque_record_id"],
            "label_status": "unlabelable",
            "expected_atom_count": 0,
            "actual_atom_count": len(actual),
            "excluded_from_quality_denominator": True,
            "unresolved_ambiguity_count": len(prediction["unresolved_errors"]),
        }

    expected = [item for item in label.get("expected_atoms") or [] if isinstance(item, dict)]
    expected_groups: Dict[Tuple[int, int, str], List[Dict[str, Any]]] = defaultdict(list)
    actual_groups: Dict[Tuple[int, int, str], List[Dict[str, Any]]] = defaultdict(list)
    for item in expected:
        expected_groups[_span_key(item)].append(item)
    for item in actual:
        actual_groups[_span_key(item)].append(item)
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    missing_expected: List[Dict[str, Any]] = []
    unexpected_actual: List[Dict[str, Any]] = []
    for key in sorted(set(expected_groups) | set(actual_groups)):
        expected_items = sorted(expected_groups.get(key, []), key=lambda item: str(item["label_id"]))
        actual_items = sorted(actual_groups.get(key, []), key=lambda item: str(item.get("atom_id") or ""))
        pair_count = min(len(expected_items), len(actual_items))
        pairs.extend(zip(expected_items[:pair_count], actual_items[:pair_count]))
        missing_expected.extend(expected_items[pair_count:])
        unexpected_actual.extend(actual_items[pair_count:])
    expected_count = len(expected)
    matched_count = len(pairs)
    indeterminate_expected = [
        item
        for item in expected
        if item.get("state_role") in {"unknown", "conflicting"}
        or item.get("taint") == "unknown"
    ]
    indeterminate_label_ids = {
        str(item["label_id"]) for item in indeterminate_expected
    }
    decisive_expected = [
        item for item in expected if str(item["label_id"]) not in indeterminate_label_ids
    ]
    decisive_pairs = [
        (left, right)
        for left, right in pairs
        if str(left["label_id"]) not in indeterminate_label_ids
    ]
    indeterminate_pairs = [
        (left, right)
        for left, right in pairs
        if str(left["label_id"]) in indeterminate_label_ids
    ]
    must_preserve = [item for item in expected if item.get("must_preserve") is True]
    paired_label_ids = {str(left["label_id"]) for left, _right in pairs}
    preserved_count = sum(
        1 for item in must_preserve if str(item["label_id"]) in paired_label_ids
    )

    def correct(field: str) -> int:
        return sum(
            1 for left, right in decisive_pairs if right.get(field) == left.get(field)
        )

    time_correct = sum(
        1
        for left, right in decisive_pairs
        if all(
            right.get(field) == left.get(field)
            for field in ("observed_at", "recorded_at", "valid_from", "valid_to")
        )
    )
    faithful_count = sum(
        1 for item in actual if offline_eval._faithful_span(evidence["source_text"], item)
    )
    temporal_count = sum(1 for item in actual if offline_eval._temporal_consistent(item))
    schema_count = sum(1 for item in actual if offline_eval._valid_atom_shape(item))
    expected_opaque_ref = canonical_json({
        "source_system": "synthetic_public_pilot",
        "evidence_ref": evidence["opaque_record_id"],
    })
    ref_retained_count = sum(
        1
        for item in actual
        if {canonical_json(ref) for ref in item.get("source_refs") or []}
        == {expected_opaque_ref}
    )
    decisive_matched_count = len(decisive_pairs)
    coverage_ok = (
        decisive_matched_count == len(decisive_expected)
        and not indeterminate_expected
    )
    preservation_ok = (
        preserved_count == len(must_preserve)
        and not unexpected_actual
        and not indeterminate_expected
    )
    activation_violations = sum(
        1 for item in actual if item.get("activation_allowed") is not False
    )
    verifier_false_passes = 0
    for item in actual:
        verifier = item.get("verifier") if isinstance(item.get("verifier"), dict) else {}
        verifier_false_passes += int(verifier.get("coverage") == "pass" and not coverage_ok)
        verifier_false_passes += int(
            verifier.get("preservation") == "pass" and not preservation_ok
        )
        verifier_false_passes += int(
            verifier.get("faithfulness") == "pass"
            and not offline_eval._faithful_span(evidence["source_text"], item)
        )
    return prediction, {
        "opaque_record_id": evidence["opaque_record_id"],
        "label_status": "labeled",
        "expected_atom_count": expected_count,
        "actual_atom_count": len(actual),
        "matched_atom_count": matched_count,
        "decidable_expected_atom_count": len(decisive_expected),
        "decidable_matched_atom_count": decisive_matched_count,
        "indeterminate_expected_atom_count": len(indeterminate_expected),
        "indeterminate_matched_atom_count": len(indeterminate_pairs),
        "missing_expected_atom_count": len(missing_expected),
        "unexpected_atom_count": len(unexpected_actual),
        "must_preserve_atom_count": len(must_preserve),
        "preserved_atom_count": preserved_count,
        "coverage_ok": coverage_ok,
        "preservation_ok": preservation_ok,
        "faithful_actual_atom_count": faithful_count,
        "schema_valid_actual_atom_count": schema_count,
        "opaque_source_ref_retained_atom_count": ref_retained_count,
        "semantic_type_correct_count": correct("semantic_type"),
        "state_role_correct_count": correct("state_role"),
        "shelf_correct_count": correct("shelf"),
        "taint_correct_count": correct("taint"),
        "dual_time_correct_count": time_correct,
        "temporal_consistent_actual_atom_count": temporal_count,
        "activation_violation_count": activation_violations,
        "verifier_false_pass_count": verifier_false_passes,
        "unresolved_ambiguity_count": len(prediction["unresolved_errors"]),
        "excluded_from_quality_denominator": False,
    }


def _sum(records: Iterable[Dict[str, Any]], field: str) -> int:
    return sum(int(item.get(field) or 0) for item in records)


def _aggregate_quality(record_scores: List[Dict[str, Any]]) -> Dict[str, Any]:
    labeled = [item for item in record_scores if item.get("label_status") == "labeled"]
    expected = _sum(labeled, "expected_atom_count")
    decidable_expected = _sum(labeled, "decidable_expected_atom_count")
    decidable_matched = _sum(labeled, "decidable_matched_atom_count")
    actual = _sum(labeled, "actual_atom_count")
    must_preserve = _sum(labeled, "must_preserve_atom_count")
    return {
        "holdout_record_count": len(record_scores),
        "labeled_record_count": len(labeled),
        "unlabelable_record_count": len(record_scores) - len(labeled),
        "expected_atom_count": expected,
        "actual_atom_count": actual,
        "matched_atom_count": _sum(labeled, "matched_atom_count"),
        "decidable_expected_atom_count": decidable_expected,
        "decidable_matched_atom_count": decidable_matched,
        "indeterminate_expected_atom_count": _sum(
            labeled, "indeterminate_expected_atom_count"
        ),
        "indeterminate_matched_atom_count": _sum(
            labeled, "indeterminate_matched_atom_count"
        ),
        "missing_expected_atom_count": _sum(labeled, "missing_expected_atom_count"),
        "unexpected_atom_count": _sum(labeled, "unexpected_atom_count"),
        "coverage_rate": _rate(decidable_matched, decidable_expected),
        "all_atom_recall_diagnostic": _rate(
            _sum(labeled, "matched_atom_count"), expected
        ),
        "indeterminate_handling_rate": _rate(
            _sum(labeled, "indeterminate_matched_atom_count"),
            _sum(labeled, "indeterminate_expected_atom_count"),
        ),
        "record_coverage_rate": _rate(
            sum(1 for item in labeled if item.get("coverage_ok") is True), len(labeled)
        ),
        "preservation_rate": _rate(
            sum(1 for item in labeled if item.get("preservation_ok") is True), len(labeled)
        ),
        "must_preserve_atom_recall": _rate(
            _sum(labeled, "preserved_atom_count"), must_preserve
        ),
        "faithfulness_rate": _rate(decidable_matched, actual),
        "projection_span_exactness_rate": _rate(
            _sum(labeled, "faithful_actual_atom_count"), actual
        ),
        "schema_valid_rate": _rate(
            _sum(labeled, "schema_valid_actual_atom_count"), actual
        ),
        "opaque_source_ref_retention_rate": _rate(
            _sum(labeled, "opaque_source_ref_retained_atom_count"), actual
        ),
        "semantic_type_accuracy": _rate(
            _sum(labeled, "semantic_type_correct_count"), decidable_expected
        ),
        "state_role_accuracy": _rate(
            _sum(labeled, "state_role_correct_count"), decidable_expected
        ),
        "shelf_accuracy": _rate(
            _sum(labeled, "shelf_correct_count"), decidable_expected
        ),
        "taint_accuracy": _rate(
            _sum(labeled, "taint_correct_count"), decidable_expected
        ),
        "dual_time_accuracy": _rate(
            _sum(labeled, "dual_time_correct_count"), decidable_expected
        ),
        "temporal_consistency_rate": _rate(
            _sum(labeled, "temporal_consistent_actual_atom_count"), actual
        ),
        "activation_violation_count": _sum(labeled, "activation_violation_count"),
        "verifier_false_pass_count": _sum(labeled, "verifier_false_pass_count"),
        "unresolved_ambiguity_count": _sum(record_scores, "unresolved_ambiguity_count"),
    }


def _withheld_metric() -> Dict[str, Any]:
    return {
        "status": "withheld_due_to_small_subset_or_complement",
        "count": None,
        "rate": None,
        "denominator": None,
    }


def _safe_metric(numerator: int, denominator: int, privacy_k: int) -> Dict[str, Any]:
    complement = denominator - numerator
    if denominator < 0 or numerator < 0 or complement < 0:
        raise BlindQualityError("quality_subset_metric_denominator_invalid")
    if any(0 < value < privacy_k for value in (numerator, complement)):
        return _withheld_metric()
    return {
        "status": "published",
        "count": numerator,
        "rate": _rate(numerator, denominator),
        "denominator": denominator,
    }


def _suppress_metric_group(
    metrics: Dict[str, Dict[str, Any]], names: Iterable[str]
) -> None:
    for name in names:
        metrics[name] = _withheld_metric()


def _build_shareable_metrics(
    metrics: Dict[str, Any],
    record_scores: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    *,
    privacy_k: int,
) -> Dict[str, Any]:
    labeled = int(metrics["labeled_record_count"])
    expected = int(metrics["decidable_expected_atom_count"])
    actual = int(metrics["actual_atom_count"])
    candidate_total = sum(int(item.get("candidate_count") or 0) for item in predictions)
    shareable = {
        "records_labeled": _safe_metric(
            labeled, int(metrics["holdout_record_count"]), privacy_k
        ),
        "atom_coverage": _safe_metric(
            int(metrics["decidable_matched_atom_count"]), expected, privacy_k
        ),
        "indeterminate_handling": _safe_metric(
            int(metrics["indeterminate_matched_atom_count"]),
            int(metrics["indeterminate_expected_atom_count"]),
            privacy_k,
        ),
        "record_coverage": _safe_metric(
            sum(1 for item in record_scores if item.get("coverage_ok") is True),
            labeled,
            privacy_k,
        ),
        "record_preservation": _safe_metric(
            sum(1 for item in record_scores if item.get("preservation_ok") is True),
            labeled,
            privacy_k,
        ),
        "blind_label_faithfulness": _safe_metric(
            int(metrics["decidable_matched_atom_count"]), actual, privacy_k
        ),
        "projection_span_exactness": _safe_metric(
            _sum(record_scores, "faithful_actual_atom_count"), actual, privacy_k
        ),
        "semantic_type_accuracy": _safe_metric(
            _sum(record_scores, "semantic_type_correct_count"), expected, privacy_k
        ),
        "state_role_accuracy": _safe_metric(
            _sum(record_scores, "state_role_correct_count"), expected, privacy_k
        ),
        "taint_accuracy": _safe_metric(
            _sum(record_scores, "taint_correct_count"), expected, privacy_k
        ),
        "dual_time_accuracy": _safe_metric(
            _sum(record_scores, "dual_time_correct_count"), expected, privacy_k
        ),
        "activation_denial_violations": _safe_metric(
            int(metrics["activation_violation_count"]), actual, privacy_k
        ),
        "verifier_false_passes": _safe_metric(
            int(metrics["verifier_false_pass_count"]), actual * 3, privacy_k
        ),
        "unresolved_ambiguities": _safe_metric(
            int(metrics["unresolved_ambiguity_count"]), candidate_total, privacy_k
        ),
    }
    if shareable["records_labeled"]["status"] != "published":
        _suppress_metric_group(
            shareable, ("record_coverage", "record_preservation")
        )

    expected_family = (
        "atom_coverage",
        "semantic_type_accuracy",
        "state_role_accuracy",
        "taint_accuracy",
        "dual_time_accuracy",
    )
    coverage_count = int(metrics["decidable_matched_atom_count"])
    expected_children = (
        int(_sum(record_scores, "semantic_type_correct_count")),
        int(_sum(record_scores, "state_role_correct_count")),
        int(_sum(record_scores, "taint_correct_count")),
        int(_sum(record_scores, "dual_time_correct_count")),
    )
    residuals = [coverage_count - child for child in expected_children]
    if any(residual < 0 for residual in residuals):
        raise BlindQualityError("quality_expected_metric_relation_invalid")
    if any(0 < residual < privacy_k for residual in residuals):
        _suppress_metric_group(shareable, expected_family)

    actual_family = (
        "blind_label_faithfulness",
        "projection_span_exactness",
        "activation_denial_violations",
        "verifier_false_passes",
    )
    missed_expected = expected - coverage_count
    if missed_expected < 0:
        raise BlindQualityError("quality_coverage_relation_invalid")
    if 0 < missed_expected < privacy_k:
        _suppress_metric_group(
            shareable, expected_family + ("blind_label_faithfulness",)
        )

    indeterminate_matched = int(metrics["indeterminate_matched_atom_count"])
    total_matched = coverage_count + indeterminate_matched
    if total_matched != int(metrics["matched_atom_count"]):
        raise BlindQualityError("quality_total_match_relation_invalid")

    decisive_unmatched_actual = actual - coverage_count
    if decisive_unmatched_actual < 0:
        raise BlindQualityError("quality_actual_decisive_match_relation_invalid")
    if 0 < decisive_unmatched_actual < privacy_k:
        _suppress_metric_group(shareable, expected_family + actual_family)

    unmatched_actual = actual - total_matched
    if unmatched_actual < 0:
        raise BlindQualityError("quality_actual_match_relation_invalid")
    if 0 < unmatched_actual < privacy_k:
        _suppress_metric_group(
            shareable,
            expected_family + ("indeterminate_handling",) + actual_family,
        )

    faithful_actual = int(_sum(record_scores, "faithful_actual_atom_count"))
    faithful_decisive_residual = faithful_actual - coverage_count
    if faithful_decisive_residual < 0:
        raise BlindQualityError("quality_faithfulness_decisive_relation_invalid")
    if 0 < faithful_decisive_residual < privacy_k:
        _suppress_metric_group(
            shareable,
            expected_family
            + ("blind_label_faithfulness", "projection_span_exactness"),
        )

    faithful_residual = faithful_actual - total_matched
    if faithful_residual < 0:
        raise BlindQualityError("quality_faithfulness_relation_invalid")
    if 0 < faithful_residual < privacy_k:
        _suppress_metric_group(
            shareable,
            expected_family
            + (
                "indeterminate_handling",
                "blind_label_faithfulness",
                "projection_span_exactness",
            ),
        )

    if 0 < actual < privacy_k:
        _suppress_metric_group(shareable, actual_family)
    return shareable


def _replay_quality_evidence(
    worksheet: Dict[str, Any],
    frozen: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    labels_by_id = {
        str(item["opaque_record_id"]): item for item in frozen["records"]
    }
    predictions = []
    record_scores = []
    for evidence in worksheet["records"]:
        prediction, record_score = _score_record(
            evidence, labels_by_id[str(evidence["opaque_record_id"])]
        )
        predictions.append(prediction)
        record_scores.append(record_score)
    return predictions, record_scores


def validate_private_report(
    report: Dict[str, Any],
    *,
    expected_worksheet: Dict[str, Any],
    worksheet_authentication_key: bytes,
    frozen_labels: Dict[str, Any],
    label_signing_key: bytes,
) -> None:
    expected_keys = {
        "contract",
        "source_measurement",
        "worksheet_evidence_sha256",
        "worksheet_hmac_sha256",
        "frozen_labels_sha256",
        "labeler_signing_key_sha256",
        "label_independence_proof_status",
        "prediction_sha256",
        "pipeline_scope",
        "quality_status",
        "quality_gate_candidate_status",
        "decision",
        "metrics",
        "records",
        "predictions",
        "write_boundary",
        "unsupported_quality",
        "owner_threshold_decision",
        "no_overall_score",
        "non_claims",
        "time_rule_decision",
        "private_report_sha256",
    }
    if not isinstance(report, dict) or set(report) != expected_keys:
        raise BlindQualityError("private_report_allowlist_failed")
    if report.get("contract") != PRIVATE_REPORT_CONTRACT:
        raise BlindQualityError("private_report_contract_invalid")
    if report.get("private_report_sha256") != _self_digest(
        report, "private_report_sha256"
    ):
        raise BlindQualityError("private_report_digest_invalid")
    if report.get("pipeline_scope") != PIPELINE_SCOPE:
        raise BlindQualityError("private_report_pipeline_scope_invalid")
    validate_source_measurement(report.get("source_measurement"))
    validate_frozen_labels(
        expected_worksheet,
        frozen_labels,
        signing_key=label_signing_key,
        worksheet_authentication_key=worksheet_authentication_key,
    )
    if hmac.compare_digest(label_signing_key, worksheet_authentication_key):
        raise BlindQualityError("label_signing_key_must_differ_from_holdout_key")
    expected_source_measurement = expected_worksheet["source_measurement"]
    expected_predictions, expected_record_scores = _replay_quality_evidence(
        expected_worksheet, frozen_labels
    )
    if (
        report.get("worksheet_evidence_sha256")
        != expected_worksheet.get("worksheet_evidence_sha256")
        or report.get("worksheet_hmac_sha256")
        != expected_worksheet.get("worksheet_hmac_sha256")
    ):
        raise BlindQualityError("private_report_worksheet_binding_invalid")
    if report.get("source_measurement") != expected_source_measurement:
        raise BlindQualityError("private_report_source_measurement_not_expected")
    if (
        report.get("frozen_labels_sha256")
        != frozen_labels.get("frozen_labels_sha256")
        or report.get("labeler_signing_key_sha256")
        != frozen_labels.get("labeler_signing_key_sha256")
    ):
        raise BlindQualityError("private_report_frozen_labels_binding_invalid")
    for name in (
        "worksheet_evidence_sha256",
        "worksheet_hmac_sha256",
        "frozen_labels_sha256",
        "labeler_signing_key_sha256",
        "prediction_sha256",
    ):
        if not _valid_sha256(report.get(name)):
            raise BlindQualityError("private_report_digest_field_invalid:" + name)
    if report.get("label_independence_proof_status") != "attested_not_source_proven":
        raise BlindQualityError("private_report_independence_boundary_invalid")
    if report.get("quality_status") not in QUALITY_STATUSES:
        raise BlindQualityError("private_report_quality_status_invalid")
    if report.get("quality_gate_candidate_status") not in QUALITY_GATE_CANDIDATE_STATUSES:
        raise BlindQualityError("private_report_candidate_status_invalid")
    if report.get("decision") != "NO_GO_PRODUCTION_SHADOW":
        raise BlindQualityError("private_report_product_gate_not_red")
    if report.get("write_boundary") != WRITE_BOUNDARY:
        raise BlindQualityError("private_report_write_boundary_invalid")
    if report.get("unsupported_quality") != UNSUPPORTED_QUALITY:
        raise BlindQualityError("private_report_unsupported_quality_invalid")
    if report.get("owner_threshold_decision") != "not_applied_to_real_distribution_in_this_cut":
        raise BlindQualityError("private_report_owner_threshold_invalid")
    if report.get("no_overall_score") is not True or report.get("non_claims") != NON_CLAIMS:
        raise BlindQualityError("private_report_non_claims_invalid")
    if report.get("time_rule_decision") != TIME_RULE_DECISION:
        raise BlindQualityError("private_report_time_rule_invalid")
    predictions = report.get("predictions")
    record_scores = report.get("records")
    if not isinstance(predictions, list) or not isinstance(record_scores, list):
        raise BlindQualityError("private_report_detail_shape_invalid")
    if len(predictions) != len(record_scores):
        raise BlindQualityError("private_report_detail_count_mismatch")
    if report.get("prediction_sha256") != sha256_json(predictions):
        raise BlindQualityError("private_report_prediction_digest_invalid")
    if report.get("metrics") != _aggregate_quality(record_scores):
        raise BlindQualityError("private_report_metrics_not_recomputed")
    metrics = report["metrics"]
    incomplete = int(metrics.get("unlabelable_record_count") or 0) > 0
    no_decidable = int(metrics.get("decidable_expected_atom_count") or 0) == 0
    source_measurement = report["source_measurement"]
    identity_profile = source_measurement.get("identity_profile")
    if incomplete:
        expected_quality_status = "quality_not_measured_incomplete_independent_labels"
        expected_candidate_status = "not_ready_incomplete_independent_labels"
    elif no_decidable:
        expected_quality_status = "quality_not_measured_no_decidable_gold_atoms"
        expected_candidate_status = "not_ready_no_decidable_gold_atoms"
    elif identity_profile != V15_IDENTITY_PROFILE:
        expected_quality_status = "synthetic_fixture_not_quality_measurement"
        expected_candidate_status = "not_ready_non_v15_identity"
    else:
        expected_quality_status = (
            "blind_quality_metrics_computed_independence_and_chronology_"
            "attested_not_proven"
        )
        expected_candidate_status = (
            "ready_for_independent_verifier_and_owner_threshold_review"
        )
    if report.get("quality_status") != expected_quality_status:
        raise BlindQualityError("private_report_quality_status_not_recomputed")
    if report.get("quality_gate_candidate_status") != expected_candidate_status:
        raise BlindQualityError("private_report_candidate_status_not_recomputed")
    if predictions != expected_predictions:
        raise BlindQualityError("private_report_predictions_not_expected")
    if record_scores != expected_record_scores:
        raise BlindQualityError("private_report_record_scores_not_expected")


def score_frozen_labels(
    worksheet: Dict[str, Any],
    frozen: Dict[str, Any],
    *,
    signing_key: bytes,
    worksheet_authentication_key: bytes,
    privacy_k: int = shadow.DEFAULT_PRIVACY_K,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    validate_frozen_labels(
        worksheet,
        frozen,
        signing_key=signing_key,
        worksheet_authentication_key=worksheet_authentication_key,
    )
    if hmac.compare_digest(signing_key, worksheet_authentication_key):
        raise BlindQualityError("label_signing_key_must_differ_from_holdout_key")
    if not isinstance(privacy_k, int) or isinstance(privacy_k, bool) or privacy_k < 1:
        raise BlindQualityError("quality_privacy_k_invalid")
    minimum_privacy_k = int(worksheet["source_measurement"]["privacy_k"])
    if privacy_k < minimum_privacy_k:
        raise BlindQualityError("quality_privacy_k_below_authenticated_source_policy")
    predictions, record_scores = _replay_quality_evidence(worksheet, frozen)
    metrics = _aggregate_quality(record_scores)
    labels_complete = frozen.get("labels_complete") is True
    identity_profile = worksheet["source_measurement"]["identity_profile"]
    if not labels_complete:
        quality_status = "quality_not_measured_incomplete_independent_labels"
        quality_gate_candidate_status = "not_ready_incomplete_independent_labels"
    elif int(metrics["decidable_expected_atom_count"]) == 0:
        quality_status = "quality_not_measured_no_decidable_gold_atoms"
        quality_gate_candidate_status = "not_ready_no_decidable_gold_atoms"
    elif identity_profile != V15_IDENTITY_PROFILE:
        quality_status = "synthetic_fixture_not_quality_measurement"
        quality_gate_candidate_status = "not_ready_non_v15_identity"
    else:
        quality_status = (
            "blind_quality_metrics_computed_independence_and_chronology_"
            "attested_not_proven"
        )
        quality_gate_candidate_status = (
            "ready_for_independent_verifier_and_owner_threshold_review"
        )
    private = {
        "contract": PRIVATE_REPORT_CONTRACT,
        "source_measurement": copy.deepcopy(worksheet["source_measurement"]),
        "worksheet_evidence_sha256": worksheet["worksheet_evidence_sha256"],
        "worksheet_hmac_sha256": worksheet["worksheet_hmac_sha256"],
        "frozen_labels_sha256": frozen["frozen_labels_sha256"],
        "labeler_signing_key_sha256": frozen["labeler_signing_key_sha256"],
        "label_independence_proof_status": "attested_not_source_proven",
        "prediction_sha256": sha256_json(predictions),
        "pipeline_scope": PIPELINE_SCOPE,
        "quality_status": quality_status,
        "quality_gate_candidate_status": quality_gate_candidate_status,
        "decision": "NO_GO_PRODUCTION_SHADOW",
        "metrics": metrics,
        "records": record_scores,
        "predictions": predictions,
        "write_boundary": copy.deepcopy(WRITE_BOUNDARY),
        "unsupported_quality": copy.deepcopy(UNSUPPORTED_QUALITY),
        "owner_threshold_decision": "not_applied_to_real_distribution_in_this_cut",
        "no_overall_score": True,
        "non_claims": NON_CLAIMS,
        "time_rule_decision": copy.deepcopy(TIME_RULE_DECISION),
    }
    private["private_report_sha256"] = sha256_json(private)
    validate_private_report(
        private,
        expected_worksheet=worksheet,
        worksheet_authentication_key=worksheet_authentication_key,
        frozen_labels=frozen,
        label_signing_key=signing_key,
    )
    shareable_metrics = _build_shareable_metrics(
        metrics,
        record_scores,
        predictions,
        privacy_k=privacy_k,
    )
    shareable = {
        "contract": SHAREABLE_REPORT_CONTRACT,
        "identity_profile": identity_profile,
        "source_measurement_identity_sha256": worksheet["source_measurement"][
            "measurement_identity_sha256"
        ],
        "pipeline_scope": PIPELINE_SCOPE,
        "quality_status": quality_status,
        "quality_gate_candidate_status": private["quality_gate_candidate_status"],
        "decision": "NO_GO_PRODUCTION_SHADOW",
        "privacy_k": privacy_k,
        "metrics": shareable_metrics,
        "privacy": {
            "source_text_emitted": False,
            "source_refs_emitted": False,
            "opaque_record_ids_emitted": False,
            "label_text_or_hashes_emitted": False,
            "per_record_results_emitted": False,
            "small_cell_policy": shadow.SMALL_CELL_POLICY,
        },
        "write_boundary": copy.deepcopy(private["write_boundary"]),
        "unsupported_quality": copy.deepcopy(private["unsupported_quality"]),
        "owner_threshold_decision": private["owner_threshold_decision"],
        "no_overall_score": True,
        "non_claims": NON_CLAIMS,
        "time_rule_decision": copy.deepcopy(private["time_rule_decision"]),
    }
    shareable["shareable_report_sha256"] = sha256_json(shareable)
    validate_shareable_report(
        shareable,
        private_report=private,
        expected_worksheet=worksheet,
        worksheet_authentication_key=worksheet_authentication_key,
        frozen_labels=frozen,
        label_signing_key=signing_key,
    )
    return private, shareable


def _validate_safe_metric(value: object, privacy_k: int) -> None:
    if not isinstance(value, dict):
        raise BlindQualityError("shareable_metric_shape_invalid")
    status = value.get("status")
    if status == "published":
        if set(value) != {"status", "count", "rate", "denominator"}:
            raise BlindQualityError("shareable_metric_allowlist_failed")
        count = value.get("count")
        denominator = value.get("denominator")
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or not isinstance(denominator, int)
            or isinstance(denominator, bool)
            or not 0 <= count <= denominator
            or value.get("rate") != shadow._rate(count, denominator)
        ):
            raise BlindQualityError("shareable_metric_published_value_invalid")
        if any(0 < item < privacy_k for item in (count, denominator - count)):
            raise BlindQualityError("shareable_metric_small_cell_published")
        return
    if status == "withheld_due_to_small_subset_or_complement":
        if set(value) != {"status", "count", "rate", "denominator"}:
            raise BlindQualityError("shareable_metric_allowlist_failed")
        if (
            value.get("count") is not None
            or value.get("rate") is not None
            or value.get("denominator") is not None
        ):
            raise BlindQualityError("shareable_metric_withheld_value_invalid")
        return
    raise BlindQualityError("shareable_metric_status_invalid")


def validate_shareable_report(
    report: Dict[str, Any],
    *,
    private_report: Optional[Dict[str, Any]] = None,
    expected_worksheet: Optional[Dict[str, Any]] = None,
    worksheet_authentication_key: Optional[bytes] = None,
    frozen_labels: Optional[Dict[str, Any]] = None,
    label_signing_key: Optional[bytes] = None,
) -> None:
    expected = {
        "contract",
        "identity_profile",
        "source_measurement_identity_sha256",
        "pipeline_scope",
        "quality_status",
        "quality_gate_candidate_status",
        "decision",
        "privacy_k",
        "metrics",
        "privacy",
        "write_boundary",
        "unsupported_quality",
        "owner_threshold_decision",
        "no_overall_score",
        "non_claims",
        "time_rule_decision",
        "shareable_report_sha256",
    }
    if not isinstance(report, dict) or set(report) != expected:
        raise BlindQualityError("shareable_report_allowlist_failed")
    if report.get("contract") != SHAREABLE_REPORT_CONTRACT:
        raise BlindQualityError("shareable_report_contract_invalid")
    if report.get("shareable_report_sha256") != _self_digest(
        report, "shareable_report_sha256"
    ):
        raise BlindQualityError("shareable_report_digest_invalid")
    if report.get("decision") != "NO_GO_PRODUCTION_SHADOW":
        raise BlindQualityError("shareable_report_product_gate_not_red")
    identity_profile = report.get("identity_profile")
    if identity_profile not in {V15_IDENTITY_PROFILE, SYNTHETIC_TEST_IDENTITY_PROFILE}:
        raise BlindQualityError("shareable_report_identity_profile_invalid")
    if not _valid_sha256(report.get("source_measurement_identity_sha256")):
        raise BlindQualityError("shareable_report_measurement_identity_invalid")
    if identity_profile == V15_IDENTITY_PROFILE and report.get(
        "source_measurement_identity_sha256"
    ) != V15_MEASUREMENT_IDENTITY_SHA256:
        raise BlindQualityError("shareable_report_v15_identity_invalid")
    if report.get("pipeline_scope") != PIPELINE_SCOPE:
        raise BlindQualityError("shareable_report_pipeline_scope_invalid")
    if report.get("quality_status") not in QUALITY_STATUSES:
        raise BlindQualityError("shareable_report_quality_status_invalid")
    if report.get("quality_gate_candidate_status") not in QUALITY_GATE_CANDIDATE_STATUSES:
        raise BlindQualityError("shareable_report_candidate_status_invalid")
    privacy_k = report.get("privacy_k")
    if not isinstance(privacy_k, int) or isinstance(privacy_k, bool) or privacy_k < 1:
        raise BlindQualityError("shareable_report_privacy_k_invalid")
    metrics = report.get("metrics")
    expected_metric_names = {
        "records_labeled",
        "atom_coverage",
        "indeterminate_handling",
        "record_coverage",
        "record_preservation",
        "blind_label_faithfulness",
        "projection_span_exactness",
        "semantic_type_accuracy",
        "state_role_accuracy",
        "taint_accuracy",
        "dual_time_accuracy",
        "activation_denial_violations",
        "verifier_false_passes",
        "unresolved_ambiguities",
    }
    if not isinstance(metrics, dict) or set(metrics) != expected_metric_names:
        raise BlindQualityError("shareable_report_metrics_allowlist_failed")
    for metric in metrics.values():
        _validate_safe_metric(metric, privacy_k)
    privacy = report.get("privacy")
    expected_privacy = {
        "source_text_emitted": False,
        "source_refs_emitted": False,
        "opaque_record_ids_emitted": False,
        "label_text_or_hashes_emitted": False,
        "per_record_results_emitted": False,
        "small_cell_policy": shadow.SMALL_CELL_POLICY,
    }
    if privacy != expected_privacy:
        raise BlindQualityError("shareable_report_privacy_invalid")
    if report.get("write_boundary") != WRITE_BOUNDARY:
        raise BlindQualityError("shareable_report_write_boundary_invalid")
    if report.get("unsupported_quality") != UNSUPPORTED_QUALITY:
        raise BlindQualityError("shareable_report_unsupported_quality_invalid")
    if report.get("owner_threshold_decision") != "not_applied_to_real_distribution_in_this_cut":
        raise BlindQualityError("shareable_report_owner_threshold_invalid")
    if report.get("no_overall_score") is not True or report.get("non_claims") != NON_CLAIMS:
        raise BlindQualityError("shareable_report_non_claims_invalid")
    if report.get("time_rule_decision") != TIME_RULE_DECISION:
        raise BlindQualityError("shareable_report_time_rule_invalid")
    if (
        private_report is None
        or expected_worksheet is None
        or worksheet_authentication_key is None
        or frozen_labels is None
        or label_signing_key is None
    ):
        raise BlindQualityError("shareable_report_private_binding_required")
    minimum_privacy_k = int(expected_worksheet["source_measurement"]["privacy_k"])
    if privacy_k < minimum_privacy_k:
        raise BlindQualityError("shareable_report_privacy_k_below_source_policy")
    validate_private_report(
        private_report,
        expected_worksheet=expected_worksheet,
        worksheet_authentication_key=worksheet_authentication_key,
        frozen_labels=frozen_labels,
        label_signing_key=label_signing_key,
    )
    if (
        report.get("identity_profile")
        != private_report.get("source_measurement", {}).get("identity_profile")
        or report.get("source_measurement_identity_sha256")
        != private_report.get("source_measurement", {}).get(
            "measurement_identity_sha256"
        )
        or report.get("quality_status") != private_report.get("quality_status")
        or report.get("quality_gate_candidate_status")
        != private_report.get("quality_gate_candidate_status")
        or report.get("metrics")
        != _build_shareable_metrics(
            private_report["metrics"],
            private_report["records"],
            private_report["predictions"],
            privacy_k=privacy_k,
        )
    ):
        raise BlindQualityError("shareable_report_private_binding_invalid")
    serialized = canonical_json(report)
    if (
        "record-" in serialized
        or '"source_path":' in serialized
        or '"source_text":' in serialized
        or '"source_refs":' in serialized
    ):
        raise BlindQualityError("shareable_report_private_shape_leak")


def validate_exact_reconstruction(
    provided: Dict[str, Any], reconstructed: Dict[str, Any]
) -> None:
    validate_worksheet(provided)
    validate_worksheet(reconstructed)
    if provided != reconstructed:
        raise BlindQualityError("worksheet_not_exact_reconstruction")


def validate_designed_freeze_identity(worksheet: Dict[str, Any]) -> None:
    validate_worksheet(worksheet)
    if worksheet["source_measurement"]["identity_profile"] != V15_IDENTITY_PROFILE:
        raise BlindQualityError("designed_freeze_requires_fixed_v15_identity")
    authentication_key = shadow.load_holdout_key(V15_HOLDOUT_KEY_PATH)
    if file_sha256(V15_HOLDOUT_KEY_PATH) != V15_HOLDOUT_KEY_FILE_SHA256:
        raise BlindQualityError("designed_freeze_v15_key_file_mismatch")
    verify_worksheet_authentication(worksheet, authentication_key)


def _write_private(
    path: Path,
    value: object,
    runtime_root: Path,
    *,
    allowed_output_root: Path = QUALITY_OUTPUT_ROOT,
) -> None:
    if not shadow._path_is_within(Path(path), Path(allowed_output_root)):
        raise BlindQualityError("output_outside_declared_quality_root")
    try:
        shadow.write_private_json(path, value, runtime_root=runtime_root)
    except shadow.ShadowAuditError as exc:
        raise BlindQualityError(str(exc)) from exc
    except OSError as exc:
        raise BlindQualityError(
            "private_output_write_failed:" + exc.__class__.__name__
        ) from exc


def _source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runtime-root", type=Path, default=shadow._default_runtime_root())
    parser.add_argument("--cutoff-input", type=Path, required=True)
    parser.add_argument("--holdout-key-input", type=Path, required=True)
    parser.add_argument("--holdout-input", type=Path, required=True)
    parser.add_argument("--measurement-report-input", type=Path, required=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local-only R2 blind quality gate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    _source_args(prepare_parser)

    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--runtime-root", type=Path, default=shadow._default_runtime_root())

    score_parser = subparsers.add_parser("score")
    _source_args(score_parser)
    score_parser.add_argument("--privacy-k", type=int, default=shadow.DEFAULT_PRIVACY_K)
    return parser.parse_args()


def _score_command_outcome(private_report: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    ready = (
        private_report.get("quality_gate_candidate_status")
        == "ready_for_independent_verifier_and_owner_threshold_review"
    )
    payload = {
        "ok": ready,
        "quality_status": private_report["quality_status"],
        "quality_gate_candidate_status": private_report[
            "quality_gate_candidate_status"
        ],
        "decision": private_report["decision"],
        "prediction_sha256": private_report["prediction_sha256"],
    }
    if not ready:
        payload["error"] = "quality_gate_candidate_not_ready"
    return payload, 0 if ready else 3


def main() -> int:
    args = _parse_args()
    try:
        if args.command == "prepare":
            worksheet = prepare_worksheet(
                runtime_root=args.runtime_root,
                cutoff_path=args.cutoff_input,
                holdout_key_path=args.holdout_key_input,
                holdout_path=args.holdout_input,
                measurement_report_path=args.measurement_report_input,
            )
            draft = make_label_draft(worksheet)
            _write_private(WORKSHEET_PATH, worksheet, args.runtime_root)
            _write_private(LABEL_DRAFT_PATH, draft, args.runtime_root)
            print(json.dumps({
                "ok": True,
                "status": "worksheet_ready_labels_not_measured",
                "record_count": worksheet["record_count"],
                "worksheet_evidence_sha256": worksheet["worksheet_evidence_sha256"],
                "quality_status": "quality_not_measured",
            }, sort_keys=True))
            return 0
        if args.command == "freeze":
            _private_permissions(WORKSHEET_PATH)
            _private_permissions(LABEL_DRAFT_PATH)
            worksheet = _read_json(WORKSHEET_PATH)
            validate_designed_freeze_identity(worksheet)
            draft = _read_json(LABEL_DRAFT_PATH)
            signing_key = load_label_signing_key(LABEL_SIGNING_KEY_PATH)
            worksheet_authentication_key = shadow.load_holdout_key(
                V15_HOLDOUT_KEY_PATH
            )
            frozen = freeze_labels(
                worksheet,
                draft,
                signing_key=signing_key,
                worksheet_authentication_key=worksheet_authentication_key,
            )
            _write_private(FROZEN_LABELS_PATH, frozen, args.runtime_root)
            print(json.dumps({
                "ok": True,
                "labels_complete": frozen["labels_complete"],
                "unlabelable_count": frozen["unlabelable_count"],
                "frozen_labels_sha256": frozen["frozen_labels_sha256"],
                "freeze_status": "labels_frozen_before_scoring",
                "quality_status": "quality_not_measured_freeze_only",
                "independence_proof_status": "attested_not_source_proven",
            }, sort_keys=True))
            return 0

        reconstructed = prepare_worksheet(
            runtime_root=args.runtime_root,
            cutoff_path=args.cutoff_input,
            holdout_key_path=args.holdout_key_input,
            holdout_path=args.holdout_input,
            measurement_report_path=args.measurement_report_input,
        )
        _private_permissions(WORKSHEET_PATH)
        _private_permissions(FROZEN_LABELS_PATH)
        worksheet = _read_json(WORKSHEET_PATH)
        validate_exact_reconstruction(worksheet, reconstructed)
        frozen = _read_json(FROZEN_LABELS_PATH)
        signing_key = load_label_signing_key(LABEL_SIGNING_KEY_PATH)
        holdout_key = shadow.load_holdout_key(args.holdout_key_input)
        if hmac.compare_digest(signing_key, holdout_key):
            raise BlindQualityError("label_signing_key_must_differ_from_holdout_key")
        private, shareable = score_frozen_labels(
            worksheet,
            frozen,
            signing_key=signing_key,
            worksheet_authentication_key=holdout_key,
            privacy_k=args.privacy_k,
        )
        _write_private(PRIVATE_REPORT_PATH, private, args.runtime_root)
        _write_private(SHAREABLE_REPORT_PATH, shareable, args.runtime_root)
        payload, exit_code = _score_command_outcome(private)
        print(json.dumps(payload, sort_keys=True))
        return exit_code
    except (BlindQualityError, shadow.ShadowAuditError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
