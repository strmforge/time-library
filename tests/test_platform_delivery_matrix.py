import json
import subprocess
import sys
from pathlib import Path

from src.platform_delivery_liveness import DEFAULT_PLATFORMS, build_platform_delivery_liveness_audit
from src.platform_delivery_matrix import (
    PLATFORM_DELIVERY_7OF7_GATE_CONTRACT,
    PLATFORM_DELIVERY_MATRIX_CONTRACT,
    build_platform_delivery_matrix,
)


ROOT = Path(__file__).resolve().parents[1]


def _audit_payload():
    return build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "openclaw",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                },
                {
                    "system": "hermes",
                    "status": "detected",
                    "connectable_now": False,
                    "intent_signal_detected": False,
                    "content_gate": "raw_pointer_consumption_only_no_platform_write",
                    "actions": [{"action": "auto_connect", "status": "auto_connect_ready"}],
                },
                {
                    "system": "codex",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                },
                {
                    "system": "claude_desktop",
                    "status": "detected",
                    "connectable_now": False,
                    "intent_signal_detected": True,
                    "actions": [{"action": "auto_connect_missing_thin_adapter", "status": "auto_connect_ready"}],
                },
            ],
        },
        preflight_payload={
            "recall_status": "preflight_surface_required",
            "memory_scope": "window",
            "source_refs_count": 3,
            "raw_items_count": 3,
            "cross_window_read": False,
        },
        platforms=("openclaw", "hermes", "codex", "claude"),
    )


def test_platform_delivery_matrix_projects_four_platform_findings_without_delivery_claim():
    matrix = build_platform_delivery_matrix(_audit_payload())

    assert matrix["contract"] == PLATFORM_DELIVERY_MATRIX_CONTRACT
    assert matrix["read_only"] is True
    assert matrix["findings_only"] is True
    assert matrix["write_performed"] is False
    assert matrix["platform_write_performed"] is False
    assert matrix["model_call_performed"] is False
    assert matrix["not_a_delivery_mechanism"] is True
    assert matrix["not_a_model_answerer"] is True
    assert matrix["counts"]["platforms_total"] == 4
    assert matrix["counts"]["source_refs_visible"] == 4
    assert matrix["counts"]["model_delivery_observed"] == 0
    assert matrix["counts"]["platform_delivery_proven"] == 0
    assert set(matrix["unproven_delivery_platforms"]) == {"openclaw", "hermes", "codex", "claude"}
    assert set(matrix["platform_proof"]["platforms_unproven"]) == {"openclaw", "hermes", "codex", "claude"}
    assert matrix["platform_proof"]["model_not_measured_means_unproven"] is True
    assert matrix["platform_proof"]["scope_or_casefile_proof_is_not_platform_wide_proof"] is True
    gate = matrix["platform_proof"]["seven_of_seven_gate"]
    assert gate["contract"] == PLATFORM_DELIVERY_7OF7_GATE_CONTRACT
    assert gate["platform_delivery_7_of_7_proven"] is False
    assert gate["proof_state"] == "7_of_7_not_proven"
    assert set(gate["missing_platforms"]) == {"claude_code_cli", "cursor", "pi"}
    assert "unproven_required_platforms" in gate["fail_reasons"]
    assert matrix["counts"]["platform_delivery_7_of_7_proven"] == 0
    assert "run_platform_specific_passive_delivery_probe_before_claiming_model_delivery" in matrix["next_actions"]
    assert "complete_7of7_platform_delivery_gate_before_release_claim" in matrix["next_actions"]
    rows = {row["platform"]: row for row in matrix["matrix"]}
    assert rows["openclaw"]["risk_level"] == "unproven"
    assert rows["openclaw"]["delivered_to_model"] == "not_measured"
    assert rows["openclaw"]["platform_proof_state"] == "platform_delivery_unproven_model_not_measured"
    assert rows["hermes"]["passive_state"] == "detected_without_connection"
    assert rows["claude"]["recall_trigger"] == "auto_connect_missing_thin_adapter"
    assert matrix["limitations"][0] == "matrix_is_projection_of_findings_not_new_probe"


def test_platform_delivery_matrix_accepts_probe_payload():
    audit = _audit_payload()
    probe_payload = {
        "contract": "platform_delivery_liveness_probe.v2026.6.21",
        "platform_delivery_liveness": audit,
    }

    matrix = build_platform_delivery_matrix(probe_payload)

    assert matrix["source_contract"] == "platform_delivery_liveness_audit.v2026.6.21"
    assert len(matrix["matrix"]) == 4
    assert matrix["matrix"][0]["source_refs_visible"] is True


def test_platform_delivery_matrix_flags_local_draft_as_blocker():
    audit = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "openclaw",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                }
            ]
        },
        preflight_payload={"source_refs_count": 0, "raw_items_count": 0},
        observed_platforms={
            "openclaw": {
                "answer_owner": "zhiyi_direct_natural_fallback_after_model_no_answer",
                "delivered_to_model": "not_measured",
                "delivered_to_user": "observed",
            }
        },
        platforms=("openclaw",),
    )

    matrix = build_platform_delivery_matrix(audit)
    row = matrix["matrix"][0]

    assert row["risk_level"] == "blocker"
    assert row["local_draft_detected"] is True
    assert row["platform_proof_state"] == "blocked_by_local_draft"
    assert "block_local_draft_or_fallback_as_think_answer" in matrix["next_actions"]


def test_platform_delivery_matrix_does_not_promote_partial_trace_to_platform_proof():
    audit = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "codex",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                }
            ]
        },
        preflight_payload={"source_refs_count": 1, "raw_items_count": 1},
        dialog_result={
            "answer_source": "evidence_bound_model_call",
            "trusted_memory_delivery_trace": {
                "status": "unproven",
                "model_delivery_state": "observed",
                "cells": {
                    "passive_gate_observed": True,
                    "model_evidence_receipt_observed": True,
                    "answer_evidence_observed": True,
                    "receipt_visibility_observed": True,
                    "security_gate_observed": False,
                },
                "missing_cells": ["security_gate_observed"],
                "used_source_refs": ["E1"],
            },
            "answer_debug": {
                "model_call": {"called": True, "request_sent": True, "supporting_refs": ["E1"]},
                "evidence": [{"source_refs_present": True}],
            },
            "platform_delivery": {"visible_reply_ok": True},
        },
        platforms=("codex",),
    )

    matrix = build_platform_delivery_matrix(audit)
    row = matrix["matrix"][0]

    assert row["delivered_to_model"] == "observed"
    assert row["platform_delivery_proven"] is False
    assert row["platform_proof_state"] == "platform_delivery_unproven_missing_definition_cells"
    assert row["definition_of_proven_missing_cells"] == ["security_gate_observed"]
    assert matrix["counts"]["model_delivery_observed"] == 1
    assert matrix["counts"]["platform_delivery_proven"] == 0
    assert matrix["platform_proof"]["platforms_proven"] == []
    assert matrix["platform_proof"]["proof_states"]["codex"] == "platform_delivery_unproven_missing_definition_cells"
    assert "complete_all_definition_of_proven_cells_before_claiming_platform_proof" in matrix["next_actions"]


def test_platform_delivery_matrix_marks_full_definition_trace_as_platform_proven():
    audit = build_platform_delivery_liveness_audit(
        autodiscovery_payload={
            "systems": [
                {
                    "system": "codex",
                    "status": "active",
                    "connectable_now": True,
                    "intent_signal_detected": True,
                    "actions": [{"action": "capability_check", "status": "ready"}],
                }
            ]
        },
        preflight_payload={"source_refs_count": 1, "raw_items_count": 1},
        dialog_result={
            "answer_source": "evidence_bound_model_call",
            "trusted_memory_delivery_trace": {
                "status": "proven",
                "model_delivery_state": "observed",
                "cells": {
                    "passive_gate_observed": True,
                    "model_evidence_receipt_observed": True,
                    "answer_evidence_observed": True,
                    "receipt_visibility_observed": True,
                    "security_gate_observed": True,
                },
                "missing_cells": [],
                "used_source_refs": ["E1"],
            },
            "answer_debug": {
                "model_call": {"called": True, "request_sent": True, "supporting_refs": ["E1"]},
                "evidence": [{"source_refs_present": True}],
            },
            "platform_delivery": {"visible_reply_ok": True},
        },
        platforms=("codex",),
    )

    matrix = build_platform_delivery_matrix(audit)
    row = matrix["matrix"][0]

    assert row["platform_delivery_proven"] is True
    assert row["platform_proof_state"] == "platform_delivery_proven"
    assert row["definition_of_proven_observed"] is True
    assert matrix["counts"]["platform_delivery_proven"] == 1
    assert matrix["platform_proof"]["platforms_proven"] == ["codex"]
    assert matrix["platform_proof"]["platforms_unproven"] == []
    assert matrix["platform_proof"]["seven_of_seven_gate"]["platform_delivery_7_of_7_proven"] is False


def _all_required_autodiscovery():
    return {
        "systems": [
            {
                "system": platform,
                "status": "active",
                "connectable_now": True,
                "intent_signal_detected": True,
                "actions": [{"action": "capability_check", "status": "ready"}],
            }
            for platform in DEFAULT_PLATFORMS
        ]
    }


def _full_definition_dialog(*, forbidden=None):
    trace = {
        "status": "proven",
        "model_delivery_state": "observed",
        "cells": {
            "passive_gate_observed": True,
            "model_evidence_receipt_observed": True,
            "answer_evidence_observed": True,
            "receipt_visibility_observed": True,
            "security_gate_observed": True,
        },
        "missing_cells": [],
        "used_source_refs": ["E1"],
    }
    if forbidden:
        trace["forbidden_substitutes_present"] = list(forbidden)
    return {
        "answer_source": "evidence_bound_model_call",
        "trusted_memory_delivery_trace": trace,
        "answer_debug": {
            "model_call": {"called": True, "request_sent": True, "supporting_refs": ["E1"]},
            "evidence": [{"source_refs_present": True}],
        },
        "platform_delivery": {"visible_reply_ok": True},
    }


def test_platform_delivery_matrix_7of7_gate_passes_only_all_required_platforms_proven():
    audit = build_platform_delivery_liveness_audit(
        autodiscovery_payload=_all_required_autodiscovery(),
        preflight_payload={"source_refs_count": 1, "raw_items_count": 1},
        dialog_result=_full_definition_dialog(),
        platforms=DEFAULT_PLATFORMS,
    )

    matrix = build_platform_delivery_matrix(audit)
    gate = matrix["platform_proof"]["seven_of_seven_gate"]

    assert matrix["counts"]["platform_delivery_proven"] == 7
    assert gate["contract"] == PLATFORM_DELIVERY_7OF7_GATE_CONTRACT
    assert gate["platform_delivery_7_of_7_proven"] is True
    assert gate["proof_state"] == "platform_delivery_7_of_7_proven"
    assert gate["required_platforms"] == list(DEFAULT_PLATFORMS)
    assert gate["proven_platforms"] == list(DEFAULT_PLATFORMS)
    assert gate["fail_reasons"] == []
    assert matrix["platform_proof"]["platform_delivery_7_of_7_proven"] is True
    assert matrix["counts"]["platform_delivery_7_of_7_proven"] == 1


def test_platform_delivery_matrix_7of7_gate_rejects_forbidden_substitutes_even_with_green_cells():
    audit = build_platform_delivery_liveness_audit(
        autodiscovery_payload=_all_required_autodiscovery(),
        preflight_payload={"source_refs_count": 1, "raw_items_count": 1},
        dialog_result=_full_definition_dialog(forbidden=["direct_endpoint_controlled_smoke_only"]),
        platforms=DEFAULT_PLATFORMS,
    )

    matrix = build_platform_delivery_matrix(audit)
    gate = matrix["platform_proof"]["seven_of_seven_gate"]
    rows = {row["platform"]: row for row in matrix["matrix"]}

    assert gate["platform_delivery_7_of_7_proven"] is False
    assert gate["proof_state"] == "7_of_7_not_proven"
    assert "forbidden_substitute_present" in gate["fail_reasons"]
    assert set(gate["forbidden_substitutes_by_platform"]) == set(DEFAULT_PLATFORMS)
    assert rows["openclaw"]["platform_proof_state"] == "blocked_by_forbidden_substitute"
    assert rows["openclaw"]["risk_level"] == "blocker"
    assert rows["openclaw"]["forbidden_substitutes_present"] == ["direct_endpoint_controlled_smoke_only"]
    assert matrix["counts"]["platform_delivery_proven"] == 0
    assert "remove_fixture_endpoint_or_gateway_substitutes_from_delivery_proof" in matrix["next_actions"]


def test_platform_delivery_matrix_projects_proof_scope_without_promoting_platform_claims():
    audit = _audit_payload()
    payload = {
        "platform_delivery_liveness": audit,
        "proof_scope_matrix": {
            "contract": "trusted_memory_proof_scope_matrix.v2026.6.21",
            "scope_filters": ["window/a", "window/b"],
            "casefile_cases": ["pref", "work"],
            "public_claim_rule": "cite only rows whose proof_state is passed/proof",
            "rows": [
                {
                    "proof_scope": "scoped_installed_zhiyi_xingce_user_work_records",
                    "proof_state": "scoped_installed_user_work_proof",
                    "evidence_source": "installed_scoped_user_work_probe_or_casefile",
                    "cases_checked": 6,
                    "scope_count": 2,
                    "record_kinds": ["user_preference", "work_record"],
                    "reads_installed_user_work_records": True,
                    "model_delivery_observed_cases": 6,
                    "platform_wide": False,
                    "broad_all_records": False,
                    "claim_boundary": "only the supplied scope/query pairs and record kinds",
                    "non_claims": ["not platform-wide delivery proof"],
                },
                {
                    "proof_scope": "platform_wide_delivery",
                    "proof_state": "platform_wide_delivery_unproven",
                    "evidence_source": "platform_specific_live_probes_required",
                    "cases_checked": 0,
                    "scope_count": 0,
                    "record_kinds": [],
                    "reads_installed_user_work_records": False,
                    "model_delivery_observed_cases": 0,
                    "platform_wide": True,
                    "broad_all_records": False,
                    "claim_boundary": "requires per-platform observed delivery traces",
                    "non_claims": ["scoped user/work proof is not platform-wide proof"],
                },
                {
                    "proof_scope": "all_records_all_scopes",
                    "proof_state": "broad_all_records_unproven",
                    "evidence_source": "not_measured_by_this_runner",
                    "cases_checked": 0,
                    "scope_count": 0,
                    "record_kinds": [],
                    "reads_installed_user_work_records": False,
                    "model_delivery_observed_cases": 0,
                    "platform_wide": False,
                    "broad_all_records": True,
                    "claim_boundary": "requires separate broad coverage design and evidence",
                    "non_claims": ["scoped casefile is not all-record proof"],
                },
            ],
        },
    }

    matrix = build_platform_delivery_matrix(payload)
    projection = matrix["platform_proof"]["proof_scope_projection"]

    assert projection["available"] is True
    assert projection["scope_filters"] == ["window/a", "window/b"]
    assert projection["casefile_cases"] == ["pref", "work"]
    assert projection["scoped_installed_user_work_records"]["proof_state"] == "scoped_installed_user_work_proof"
    assert projection["scoped_installed_user_work_records"]["cases_checked"] == 6
    assert projection["scoped_installed_user_work_records"]["record_kinds"] == ["user_preference", "work_record"]
    assert projection["platform_wide_delivery"]["proof_state"] == "platform_wide_delivery_unproven"
    assert projection["platform_wide_claim_allowed"] is False
    assert matrix["counts"]["platform_delivery_proven"] == 0
    assert matrix["platform_proof"]["platforms_proven"] == []
    assert set(matrix["platform_proof"]["platforms_unproven"]) == {"openclaw", "hermes", "codex", "claude"}


def test_platform_delivery_matrix_accepts_nested_trust_metrics_proof_scope():
    payload = {
        "platform_delivery_liveness": _audit_payload(),
        "trusted_memory_trust_metrics": {
            "proof_scope_matrix": {
                "contract": "trusted_memory_proof_scope_matrix.v2026.6.21",
                "rows": [
                    {
                        "proof_scope": "platform_wide_delivery",
                        "proof_state": "platform_wide_delivery_unproven",
                    }
                ],
            }
        },
    }

    matrix = build_platform_delivery_matrix(payload)

    assert matrix["platform_proof"]["proof_scope_projection"]["available"] is True
    assert (
        matrix["platform_proof"]["proof_scope_projection"]["platform_wide_delivery"]["proof_state"]
        == "platform_wide_delivery_unproven"
    )


def test_platform_delivery_matrix_cli_outputs_json(tmp_path):
    payload_path = tmp_path / "audit.json"
    payload_path.write_text(json.dumps(_audit_payload(), ensure_ascii=False), encoding="utf-8")
    script = ROOT / "tools" / "platform_delivery_matrix.py"

    run = subprocess.run(
        [sys.executable, str(script), "--input", str(payload_path), "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(run.stdout)
    assert payload["contract"] == PLATFORM_DELIVERY_MATRIX_CONTRACT
    assert payload["counts"]["platforms_total"] == 4
    assert payload["platform_write_performed"] is False
