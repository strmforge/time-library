#!/usr/bin/env python3
"""HTTP route helpers for Zhixing library dry-run endpoints."""

from __future__ import annotations

import json
import urllib.parse

try:
    from src.zhixing_library import (
        build_active_bookmarks_dry_run,
        build_experience_apply_package_dry_run,
        build_experience_apply_receipt_schema_dry_run,
        build_experience_evolution_candidates_dry_run,
        build_experience_flow_overview_dry_run,
        build_experience_review_apply_gate_dry_run,
        build_experience_review_actions_dry_run,
        build_experience_review_queue_dry_run,
        build_experience_validation_receipt_schema_dry_run,
        build_experience_validation_report_dry_run,
        build_experience_history_dry_run,
        build_library_admission_candidate,
        build_library_index_projection_dry_run,
        build_library_note_projection_dry_run,
        build_library_trust_doctor_dry_run,
        library_experience_apply_package_contract,
        library_experience_apply_receipt_schema_contract,
        library_active_bookmarks_contract,
        library_admission_candidate_contract,
        library_experience_evolution_contract,
        library_experience_flow_overview_contract,
        library_experience_review_queue_contract,
        library_experience_validation_receipt_schema_contract,
        library_experience_validation_report_contract,
        library_experience_review_apply_gate_contract,
        library_experience_review_action_contract,
        library_experience_history_contract,
        library_index_projection_contract,
        library_note_projection_contract,
        library_trust_doctor_contract,
        zhixing_loop_manifest,
    )
except Exception:  # pragma: no cover
    from zhixing_library import (
        build_active_bookmarks_dry_run,
        build_experience_apply_package_dry_run,
        build_experience_apply_receipt_schema_dry_run,
        build_experience_evolution_candidates_dry_run,
        build_experience_flow_overview_dry_run,
        build_experience_review_apply_gate_dry_run,
        build_experience_review_actions_dry_run,
        build_experience_review_queue_dry_run,
        build_experience_validation_receipt_schema_dry_run,
        build_experience_validation_report_dry_run,
        build_experience_history_dry_run,
        build_library_admission_candidate,
        build_library_index_projection_dry_run,
        build_library_note_projection_dry_run,
        build_library_trust_doctor_dry_run,
        library_experience_apply_package_contract,
        library_experience_apply_receipt_schema_contract,
        library_active_bookmarks_contract,
        library_admission_candidate_contract,
        library_experience_evolution_contract,
        library_experience_flow_overview_contract,
        library_experience_review_queue_contract,
        library_experience_validation_receipt_schema_contract,
        library_experience_validation_report_contract,
        library_experience_review_apply_gate_contract,
        library_experience_review_action_contract,
        library_experience_history_contract,
        library_index_projection_contract,
        library_note_projection_contract,
        library_trust_doctor_contract,
        zhixing_loop_manifest,
    )


ZHIXING_CONTRACT_ROUTES = {
    "/api/v1/zhixing/loop": zhixing_loop_manifest,
    "/api/v1/zhixing/library-note-projection/contract": library_note_projection_contract,
    "/api/v1/zhixing/admission-candidates/contract": library_admission_candidate_contract,
    "/api/v1/zhixing/active-bookmarks/contract": library_active_bookmarks_contract,
    "/api/v1/zhixing/experience-history/contract": library_experience_history_contract,
    "/api/v1/zhixing/library-trust-doctor/contract": library_trust_doctor_contract,
    "/api/v1/zhixing/library-index-projection/contract": library_index_projection_contract,
    "/api/v1/zhixing/experience-evolution/contract": library_experience_evolution_contract,
    "/api/v1/zhixing/experience-review-actions/contract": library_experience_review_action_contract,
    "/api/v1/zhixing/experience-review-queue/contract": library_experience_review_queue_contract,
    "/api/v1/zhixing/experience-review-actions/apply-gate/contract": library_experience_review_apply_gate_contract,
    "/api/v1/zhixing/experience-validation-report/contract": library_experience_validation_report_contract,
    "/api/v1/zhixing/experience-validation-receipts/contract": library_experience_validation_receipt_schema_contract,
    "/api/v1/zhixing/experience-apply-receipts/contract": library_experience_apply_receipt_schema_contract,
    "/api/v1/zhixing/experience-apply-package/contract": library_experience_apply_package_contract,
    "/api/v1/zhixing/experience-flow-overview/contract": library_experience_flow_overview_contract,
}

ZHIXING_DRY_RUN_ROUTES = {
    "/api/v1/zhixing/library-note-projection/dry-run": build_library_note_projection_dry_run,
    "/api/v1/zhixing/admission-candidates/dry-run": build_library_admission_candidate,
    "/api/v1/zhixing/active-bookmarks/dry-run": build_active_bookmarks_dry_run,
    "/api/v1/zhixing/experience-history/dry-run": build_experience_history_dry_run,
    "/api/v1/zhixing/library-trust-doctor/dry-run": build_library_trust_doctor_dry_run,
    "/api/v1/zhixing/library-index-projection/dry-run": build_library_index_projection_dry_run,
    "/api/v1/zhixing/experience-evolution/dry-run": build_experience_evolution_candidates_dry_run,
    "/api/v1/zhixing/experience-review-actions/dry-run": build_experience_review_actions_dry_run,
    "/api/v1/zhixing/experience-review-actions/apply-gate/dry-run": build_experience_review_apply_gate_dry_run,
    "/api/v1/zhixing/experience-validation-report/dry-run": build_experience_validation_report_dry_run,
    "/api/v1/zhixing/experience-validation-receipts/dry-run": build_experience_validation_receipt_schema_dry_run,
    "/api/v1/zhixing/experience-review-queue/dry-run": build_experience_review_queue_dry_run,
    "/api/v1/zhixing/experience-apply-receipts/dry-run": build_experience_apply_receipt_schema_dry_run,
    "/api/v1/zhixing/experience-apply-package/dry-run": build_experience_apply_package_dry_run,
    "/api/v1/zhixing/experience-flow-overview/dry-run": build_experience_flow_overview_dry_run,
}


def query_params(raw_path: str) -> dict:
    parsed = urllib.parse.urlparse(raw_path)
    query = urllib.parse.parse_qs(parsed.query)
    return {key: value[0] if len(value) == 1 else value for key, value in query.items()}


def read_json_body(handler) -> dict:
    length = int(handler.headers.get("Content-Length", 0))
    return json.loads(handler.rfile.read(length).decode()) if length > 0 else {}


def send_contract_if_matched(handler, path: str) -> bool:
    builder = ZHIXING_CONTRACT_ROUTES.get(path)
    if builder is None:
        return False
    handler.send_json(builder())
    return True


def send_dry_run_if_matched(handler, path: str) -> bool:
    builder = ZHIXING_DRY_RUN_ROUTES.get(path)
    if builder is None:
        return False
    result = builder(read_json_body(handler))
    handler.send_json(result, 200 if result.get("ok") else 400)
    return True


__all__ = [
    "build_library_admission_candidate",
    "query_params",
    "send_contract_if_matched",
    "send_dry_run_if_matched",
]
