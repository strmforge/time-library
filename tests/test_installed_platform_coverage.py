import json
import subprocess
import sys
from pathlib import Path

from src.installed_platform_coverage import (
    INSTALLED_PLATFORM_COVERAGE_CONTRACT,
    build_installed_platform_coverage,
)


ROOT = Path(__file__).resolve().parents[1]


def _autodiscovery_payload():
    return {
        "systems": [
            {
                "system": "memcore_cloud",
                "status": "active",
                "connectable_now": True,
                "intent_signal_detected": True,
            },
            {
                "system": "openclaw",
                "status": "active",
                "connectable_now": True,
                "intent_signal_detected": True,
                "content_gate": "verified_format_collector_required",
            },
            {
                "system": "hermes",
                "status": "detected",
                "connectable_now": True,
                "intent_signal_detected": True,
                "content_gate": "raw_pointer_consumption_only_no_platform_write",
            },
            {
                "system": "codex",
                "status": "active",
                "connectable_now": True,
                "intent_signal_detected": True,
                "content_gate": "verified_format_collector_required",
            },
        ]
    }


def _delivery_matrix_payload():
    return {
        "contract": "platform_delivery_liveness_matrix.v2026.6.21",
        "matrix": [
            {
                "platform": "openclaw",
                "platform_proof_state": "platform_delivery_proven",
                "platform_delivery_proven": True,
            },
            {
                "platform": "hermes",
                "platform_proof_state": "platform_delivery_unproven_model_not_measured",
                "platform_delivery_proven": False,
            },
            {
                "platform": "codex",
                "platform_proof_state": "platform_delivery_unproven_model_not_measured",
                "platform_delivery_proven": False,
            },
        ],
    }


def test_installed_platform_coverage_separates_detection_delivery_and_runtime():
    payload = build_installed_platform_coverage(
        autodiscovery_payload=_autodiscovery_payload(),
        delivery_matrix_payload=_delivery_matrix_payload(),
        remote_probes=[
            {
                "system": "pi",
                "host": "DESKTOP-EXAMPLE",
                "read_only": True,
                "body_read": False,
                "secret_read": False,
                "detected": False,
                "processes": [],
                "app_paths": [],
                "config_dirs": [],
                "shortcuts": [],
                "uninstall_entries": [],
            }
        ],
        runtime_status={"openclaw": "controlled_smoke_path_proven"},
        required_targets=["openclaw", "hermes", "codex", "pi"],
    )

    rows = {row["system"]: row for row in payload["matrix"]}

    assert payload["contract"] == INSTALLED_PLATFORM_COVERAGE_CONTRACT
    assert payload["read_only"] is True
    assert payload["platform_write_performed"] is False
    assert payload["model_call_performed"] is False
    assert payload["chat_body_read"] is False
    assert payload["secret_read"] is False
    assert payload["ok"] is False
    assert payload["release_candidate_gate"]["required_detection_gaps"] == ["pi"]
    assert rows["openclaw"]["coverage_state"] == "covered_by_controlled_runtime_scope_only"
    assert rows["openclaw"]["runtime_turn_loop_state"] == "controlled_smoke_path_proven"
    assert rows["hermes"]["installed_state"] == "detected"
    assert rows["hermes"]["delivery_proof_state"] == "platform_delivery_unproven_model_not_measured"
    assert rows["hermes"]["runtime_turn_loop_state"] == "not_proven"
    assert "runtime_turn_loop_not_proven" in rows["hermes"]["gap"]
    assert rows["pi"]["installed_state"] == "not_detected_explicit_probe"
    assert "pi_requested_target_not_installed_on_checked_hosts" in rows["pi"]["gap"]
    assert rows["pi"]["pre_tiandao_restored"] is False
    assert payload["remote_probe_summaries"][0] == {
        "host": "DESKTOP-EXAMPLE",
        "platform": "pi",
        "detected": False,
        "signal_count": 0,
        "read_only": True,
        "body_read": False,
        "secret_read": False,
        "agent_site_metadata_read": False,
        "browser_profile_content_read": False,
    }
    assert "controlled_openclaw_scope_does_not_cover_all_platforms" in rows["openclaw"]["non_claims"]
    assert "nas_model_config_is_not_installation_proof" in payload["non_claims"]


def _pi_autodiscovery_payload():
    return {
        "systems": [
            {
                "system": "pi",
                "status": "detected",
                "connectable_now": False,
                "intent_signal_detected": False,
                "content_gate": "verified_format_collector_required",
            }
        ]
    }


def test_installed_platform_coverage_requires_auto_connect_and_structure_analysis_for_pi_candidate():
    payload = build_installed_platform_coverage(
        {"auto_connect_dry_run": {"plans": []}},
        autodiscovery_payload=_pi_autodiscovery_payload(),
        delivery_matrix_payload={"contract": "platform_delivery_liveness_matrix.v2026.6.21", "matrix": []},
        required_targets=["pi"],
    )

    row = payload["matrix"][0]
    assert payload["ok"] is False
    assert payload["release_candidate_gate"]["required_detection_gaps"] == []
    assert payload["release_candidate_gate"]["required_auto_connect_gaps"] == ["pi"]
    assert payload["release_candidate_gate"]["structure_analysis_gate"]["ok"] is False
    assert row["system"] == "pi"
    assert row["installed_state"] == "detected"
    assert row["installed_evidence"] == ["local_autodiscovery"]
    assert row["coverage_state"] == "covered_by_detection_only"
    assert row["source_capture_state"] == "verified_collector_required_for_pi_coding_agent"
    assert row["consumer_connection_state"] == "detected_without_memcore_connection"
    assert "delivery_matrix_missing" in row["gap"]


def test_installed_platform_coverage_accepts_pi_when_detection_auto_connect_and_structure_analysis_are_present():
    payload = build_installed_platform_coverage(
        {
            "auto_connect_dry_run": {
                "plans": [
                    {
                        "system": "pi",
                        "status": "auto_connect_ready",
                        "plan_source": "adapter_draft",
                        "would_write": ["/home/user/.pi/agent/skills/time-library"],
                        "apply_endpoint_status": "implemented_for_pi_skill_surface",
                    }
                ]
            },
            "model_structure_analysis": {
                "summary": {
                    "executed_model_surface_count": 1,
                    "adapter_draft_count": 1,
                },
                "chat_body_read": False,
                "secret_read": False,
                "input_kind": "local_metadata_only",
            },
        },
        autodiscovery_payload=_pi_autodiscovery_payload(),
        delivery_matrix_payload={"contract": "platform_delivery_liveness_matrix.v2026.6.21", "matrix": []},
        required_targets=["pi"],
    )

    row = payload["matrix"][0]
    assert payload["ok"] is True
    assert payload["release_candidate_gate"]["required_detection_gaps"] == []
    assert payload["release_candidate_gate"]["required_auto_connect_gaps"] == []
    assert payload["release_candidate_gate"]["structure_analysis_gate"]["ok"] is True
    assert row["auto_connect_state"] == "auto_connect_ready_with_apply_endpoint"
    assert row["auto_connect_plan_source"] == "adapter_draft"


def test_installed_platform_coverage_derives_structure_analysis_from_auto_connect_adapter_drafts():
    payload = build_installed_platform_coverage(
        {
            "auto_connect_dry_run": {
                "plans": [
                    {
                        "system": "pi",
                        "status": "auto_connect_ready",
                        "plan_source": "adapter_draft",
                        "would_write": ["/home/user/.pi/agent/skills/time-library"],
                        "apply_endpoint_status": "implemented_for_pi_skill_surface",
                        "adapter_draft": {
                            "contract": "local_ai_tool_adapter_draft.v1",
                            "recognition": {"recognized_by": "known_thin_adapter"},
                        },
                    }
                ]
            },
        },
        autodiscovery_payload=_pi_autodiscovery_payload(),
        delivery_matrix_payload={"contract": "platform_delivery_liveness_matrix.v2026.6.21", "matrix": []},
        required_targets=["pi"],
    )

    gate = payload["release_candidate_gate"]["structure_analysis_gate"]
    assert payload["ok"] is True
    assert gate["ok"] is True
    assert gate["model_structure_analysis_present"] is True
    assert gate["adapter_draft_count"] == 1
    assert gate["local_rule_structure_analysis_count"] == 1
    assert gate["model_identification_executed_count"] == 0
    assert gate["chat_body_read"] is False
    assert gate["secret_read"] is False


def test_installed_platform_coverage_cli_outputs_json_and_nonzero_for_required_gap(tmp_path):
    remote_probe = tmp_path / "pi.json"
    remote_probe.write_text(
        json.dumps(
            {
                "system": "pi",
                "host": "win-node-a",
                "read_only": True,
                "body_read": False,
                "secret_read": False,
                "detected": False,
            }
        ),
        encoding="utf-8",
    )
    autodiscovery = tmp_path / "autodiscovery.json"
    autodiscovery.write_text(json.dumps({"systems": []}), encoding="utf-8")
    delivery = tmp_path / "delivery.json"
    delivery.write_text(
        json.dumps({"contract": "platform_delivery_liveness_matrix.v2026.6.21", "matrix": []}),
        encoding="utf-8",
    )

    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "installed_platform_coverage.py"),
            "--autodiscovery",
            str(autodiscovery),
            "--delivery-matrix",
            str(delivery),
            "--remote-probe",
            str(remote_probe),
            "--required-targets",
            "pi",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(run.stdout)
    assert run.returncode == 2
    assert payload["release_candidate_gate"]["required_detection_gaps"] == ["pi"]
