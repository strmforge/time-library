import json
import subprocess
import sys
from pathlib import Path

from src import time_library_delivery_runtime as delivery_runtime
from src.platform_delivery_liveness import build_platform_delivery_liveness_audit
from src.platform_delivery_matrix import (
    PLATFORM_DELIVERY_7OF7_GATE_CONTRACT,
    PLATFORM_DELIVERY_MATRIX_CONTRACT,
    RELEASE_COMPATIBILITY_PLATFORMS,
    build_platform_delivery_matrix,
)


ROOT = Path(__file__).resolve().parents[1]


def _context(memcore_root, platform):
    context = {
        "transport_session_id": f"matrix:{memcore_root}:{platform}",
        "initialized": True,
        "client_info_present": True,
        "client_name": f"{platform} host",
        "client_version": "1",
        "inferred_platform_hint": "unknown_mcp_client",
    }
    receipt = delivery_runtime.record_verified_host_connection(
        context,
        {
            "ok": True,
            "self_report_verified": True,
            "client_info": {"self_reported_platform": platform},
            "real_recall_proof": {"library_id": "ZX-MATRIX", "source_refs_count": 1},
            "borrowing_card_receipt": {"card_id": f"card-{platform}"},
        },
        memcore_root=memcore_root,
    )
    assert receipt["ok"] is True
    return context


def _recall_result():
    return {
        "ok": True,
        "matched_count": 1,
        "items": [
            {
                "library_id": "ZX-MATRIX",
                "source_system": "local_files",
                "source_path": "raw/public-safe-proof.jsonl",
            }
        ],
    }


def _track(memcore_root, platform, context, *, delivery_form="context"):
    return delivery_runtime.instrument_recall_result(
        _recall_result(),
        {"consumer": platform, "query": "proof", "delivery_form": delivery_form},
        memcore_root=memcore_root,
        connection_context=context,
    )


def _ack(memcore_root, context, challenge, *, wrong=False):
    return delivery_runtime.acknowledge_delivery(
        {
            "challenge_id": challenge["challenge_id"],
            "challenge": "wrong" if wrong else challenge["challenge"],
            "retrieval_id": challenge["retrieval_id"],
            "platform": challenge["platform"],
            "request_id": f"matrix-model-request-{challenge['challenge_id']}",
            "used_source_refs": challenge["selected_source_refs"],
            "response_evidence_ref": f"matrix-model-response-{challenge['challenge_id']}",
        },
        memcore_root=memcore_root,
        connection_context=context,
    )


def _record_full_delivery(memcore_root, platform):
    context = _context(memcore_root, platform)
    tracked = _track(memcore_root, platform, context)
    assert _ack(memcore_root, context, tracked["delivery_runtime"]["challenge"])["ok"] is True
    _track(memcore_root, platform, context, delivery_form="silent")
    attacked = _track(memcore_root, platform, context)
    rejected = _ack(
        memcore_root,
        context,
        attacked["delivery_runtime"]["challenge"],
        wrong=True,
    )
    assert rejected["ok"] is False


def _audit_payload(memcore_root):
    platforms = ("openclaw", "hermes", "codex", "claude_desktop")
    for platform in platforms:
        _context(memcore_root, platform)
    return build_platform_delivery_liveness_audit(
        preflight_payload={"source_refs_count": 99, "raw_items_count": 99},
        platforms=platforms,
        memcore_root=memcore_root,
    )


def test_platform_delivery_matrix_projects_persisted_connections_without_delivery_claim(tmp_path):
    matrix = build_platform_delivery_matrix(_audit_payload(tmp_path))

    assert matrix["contract"] == PLATFORM_DELIVERY_MATRIX_CONTRACT
    assert matrix["read_only"] is True
    assert matrix["findings_only"] is True
    assert matrix["write_performed"] is False
    assert matrix["platform_write_performed"] is False
    assert matrix["model_call_performed"] is False
    assert matrix["not_a_delivery_mechanism"] is True
    assert matrix["counts"]["platforms_total"] == 4
    assert matrix["counts"]["source_refs_visible"] == 0
    assert matrix["counts"]["model_delivery_observed"] == 0
    assert matrix["counts"]["platform_delivery_proven"] == 0
    assert set(matrix["unproven_delivery_platforms"]) == {
        "openclaw",
        "hermes",
        "codex",
        "claude_desktop",
    }
    gate = matrix["platform_proof"]["seven_of_seven_gate"]
    assert gate["contract"] == PLATFORM_DELIVERY_7OF7_GATE_CONTRACT
    assert gate["scope"] == "release_compatibility_evidence_only"
    assert gate["does_not_control_liveness"] is True
    assert gate["does_not_limit_unknown_hosts"] is True
    assert gate["platform_delivery_7_of_7_proven"] is False
    assert set(gate["missing_platforms"]) == {"claude_code_cli", "cursor", "pi"}
    assert "unproven_required_platforms" in gate["fail_reasons"]
    assert "run_verified_host_delivery_probe_before_claiming_model_delivery" in matrix["next_actions"]
    rows = {row["platform"]: row for row in matrix["matrix"]}
    assert rows["openclaw"]["self_report_verified"] is True
    assert rows["openclaw"]["connection_receipt_id"].startswith("host-connection-")
    assert rows["openclaw"]["platform_proof_state"] == "platform_delivery_unproven_model_not_measured"
    assert matrix["limitations"][0] == "matrix_is_projection_of_findings_not_new_probe"


def test_platform_delivery_matrix_accepts_probe_payload(tmp_path):
    probe_payload = {
        "contract": "platform_delivery_liveness_probe.v2026.6.21",
        "platform_delivery_liveness": _audit_payload(tmp_path),
    }

    matrix = build_platform_delivery_matrix(probe_payload)

    assert matrix["source_contract"] == "platform_delivery_liveness_audit.v2026.6.21"
    assert len(matrix["matrix"]) == 4
    assert matrix["matrix"][0]["self_report_verified"] is True
    assert matrix["matrix"][0]["source_refs_visible"] is False


def test_platform_delivery_matrix_flags_local_draft_without_trusting_green_claims(tmp_path):
    audit = build_platform_delivery_liveness_audit(
        dialog_result={
            "answer": "local fallback",
            "answer_source": "zhiyi_direct_natural_fallback_after_model_no_answer",
        },
        observed_platforms={
            "future_host": {
                "self_report_verified": True,
                "source_refs_visible": True,
                "delivered_to_model": "observed",
            }
        },
        platforms=("future_host",),
        memcore_root=tmp_path,
    )

    row = build_platform_delivery_matrix(audit)["matrix"][0]

    assert row["risk_level"] == "blocker"
    assert row["local_draft_detected"] is True
    assert row["self_report_verified"] is False
    assert row["delivered_to_model"] == "not_measured"
    assert row["platform_proof_state"] == "blocked_by_local_draft"


def test_platform_delivery_matrix_recomputes_partial_definition_from_append_only_store(tmp_path):
    context = _context(tmp_path, "future_host")
    tracked = _track(tmp_path, "future_host", context)
    assert _ack(tmp_path, context, tracked["delivery_runtime"]["challenge"])["ok"] is True

    matrix = build_platform_delivery_matrix(
        platforms=("future_host",),
        memcore_root=tmp_path,
    )
    row = matrix["matrix"][0]

    assert row["delivered_to_model"] == "observed"
    assert row["platform_delivery_proven"] is False
    assert row["platform_proof_state"] == "platform_delivery_unproven_missing_definition_cells"
    assert set(row["definition_of_proven_missing_cells"]) == {
        "passive_gate_observed",
        "security_gate_observed",
    }


def test_unknown_host_can_be_proven_without_entering_release_compatibility_list(tmp_path):
    _record_full_delivery(tmp_path, "future_host")

    matrix = build_platform_delivery_matrix(memcore_root=tmp_path)
    row = matrix["matrix"][0]
    gate = matrix["platform_proof"]["seven_of_seven_gate"]

    assert row["platform"] == "future_host"
    assert row["platform_delivery_proven"] is True
    assert matrix["platform_proof"]["platforms_proven"] == ["future_host"]
    assert gate["platform_delivery_7_of_7_proven"] is False
    assert gate["extra_platforms"] == ["future_host"]
    assert gate["does_not_limit_unknown_hosts"] is True


def test_release_compatibility_gate_uses_persisted_connection_and_delivery_evidence(tmp_path):
    for platform in RELEASE_COMPATIBILITY_PLATFORMS:
        _record_full_delivery(tmp_path, platform)

    matrix = build_platform_delivery_matrix(memcore_root=tmp_path)
    gate = matrix["platform_proof"]["seven_of_seven_gate"]

    assert matrix["counts"]["platform_delivery_proven"] == 7
    assert gate["platform_delivery_7_of_7_proven"] is True
    assert gate["required_platforms"] == list(RELEASE_COMPATIBILITY_PLATFORMS)
    assert gate["proven_platforms"] == list(RELEASE_COMPATIBILITY_PLATFORMS)
    assert gate["verified_self_report_connection_missing"] == []
    assert gate["model_delivery_not_observed"] == []
    assert gate["user_delivery_not_observed"] == list(RELEASE_COMPATIBILITY_PLATFORMS)
    assert gate["fail_reasons"] == []
    assert "release_compatibility_samples_are_not_an_admission_allowlist" in gate["non_claims"]


def _proof_scope_payload(audit):
    return {
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
                },
                {
                    "proof_scope": "all_records_all_scopes",
                    "proof_state": "broad_all_records_unproven",
                },
            ],
        },
    }


def test_platform_delivery_matrix_projects_proof_scope_without_promoting_platform_claims(tmp_path):
    matrix = build_platform_delivery_matrix(_proof_scope_payload(_audit_payload(tmp_path)))
    projection = matrix["platform_proof"]["proof_scope_projection"]

    assert projection["available"] is True
    assert projection["scope_filters"] == ["window/a", "window/b"]
    assert projection["casefile_cases"] == ["pref", "work"]
    assert projection["scoped_installed_user_work_records"]["proof_state"] == "scoped_installed_user_work_proof"
    assert projection["scoped_installed_user_work_records"]["cases_checked"] == 6
    assert projection["platform_wide_claim_allowed"] is False
    assert matrix["counts"]["platform_delivery_proven"] == 0


def test_platform_delivery_matrix_accepts_nested_trust_metrics_proof_scope(tmp_path):
    payload = {
        "platform_delivery_liveness": _audit_payload(tmp_path),
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
    payload_path.write_text(json.dumps(_audit_payload(tmp_path), ensure_ascii=False), encoding="utf-8")
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
