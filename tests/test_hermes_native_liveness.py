import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from src.hermes_native_liveness import (
    build_hermes_native_learning_liveness,
    build_hermes_self_review_wake_dry_run,
    persist_hermes_self_review_signal_receipt,
    build_hermes_self_review_trigger_plan,
    query_hermes_self_review_triggers,
    trigger_hermes_self_review,
    build_hermes_skill_generation_probe_plan,
    trigger_hermes_skill_generation_probe,
    query_hermes_skill_generation_probes,
    build_hermes_skill_artifact_status_dry_run,
    record_hermes_skill_artifact_status,
    query_hermes_skill_artifact_statuses,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_hermes_native_liveness_reports_cold_when_no_native_review(tmp_path):
    home = tmp_path / "hermes"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")

    result = build_hermes_native_learning_liveness(hermes_home=home)

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["liveness_status"] == "cold"
    assert result["native_skill_write_observed"] is False
    assert "no_background_review_seen" in result["cold_reasons"]
    assert "no_skill_manage_seen" in result["cold_reasons"]
    assert "latest_skill_write_looks_like_yifanchen_install" in result["cold_reasons"]
    assert result["skills"]["latest_relative_path"] == "yifanchen/yifanchen-zhiyi/SKILL.md"


def test_hermes_native_liveness_detects_review_and_skill_manage(tmp_path):
    home = tmp_path / "hermes"
    _write(
        home / "logs" / "agent.log",
        "\n".join([
            "session started",
            "background_review review_skills=true",
            "tool event: skill_manage update systematic-debugging",
        ]),
    )
    _write(home / "skills" / "software-development" / "systematic-debugging" / "SKILL.md", "# Debugging\n")

    result = build_hermes_native_learning_liveness(hermes_home=home)

    assert result["liveness_status"] == "native_skill_write_observed"
    assert result["cold"] is False
    assert result["native_skill_write_observed"] is True
    assert result["logs"]["native_review_event_count"] >= 2
    assert result["logs"]["skill_manage_event_count"] == 1
    assert result["skills"]["latest_relative_path"] == "software-development/systematic-debugging/SKILL.md"
    assert result["hermes_write_performed"] is False


def test_hermes_native_liveness_summarizes_feedback_artifacts(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    _write(home / "logs" / "agent.log", "background_review review_skills=true\nskill_manage\n")
    _write(home / "skills" / "devops" / "kanban-orchestrator" / "references" / "feedback.md", "feedback\n")
    upgrade = {
        "upgrade_input_id": "hermes-upgrade-input-test",
        "upgrade_input_status": "ready_for_experience_review_native_change_observed",
        "experience_upgrade_ready": True,
        "production_experience_write_performed": False,
    }
    _write(
        memcore / "output" / "hermes_experience_feedback" / "upgrade_inputs" / "hermes-upgrade-input-test.json",
        json.dumps(upgrade),
    )

    result = build_hermes_native_learning_liveness(hermes_home=home, memcore_root=memcore)

    artifacts = result["feedback_artifacts"]["upgrade_inputs"]
    assert artifacts["latest_id"] == "hermes-upgrade-input-test"
    assert artifacts["latest_status"] == "ready_for_experience_review_native_change_observed"
    assert artifacts["experience_upgrade_ready"] is True


def test_hermes_native_liveness_emits_self_review_signal_without_packaging(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    _write(home / "logs" / "agent.log", "background_review review_skills=true\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")

    result = build_hermes_native_learning_liveness(hermes_home=home, memcore_root=memcore)

    signal = result["self_review_signal"]
    assert signal["read_only"] is True
    assert signal["write_performed"] is False
    assert signal["signal_type"] == "hermes_self_review_signal"
    assert signal["signal_status"] == "wake_signal"
    assert signal["scope"]["read_scope"] == "all_raw_memory"
    assert signal["scope"]["read_hint"] == "这一片都是你该去读的原始记忆"
    assert "raw/" in signal["scope"]["logical_roots"]
    assert "signal_only" in signal["notes"]
    assert "no_summary_pack" in signal["notes"]
    assert signal["instructions"][0] == "Hermes should inspect the underlying raw/source_refs itself."
    assert signal["instructions"][1] == "This whole area is yours to read."


def test_hermes_self_review_wake_dry_run_is_signal_only(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")

    result = build_hermes_self_review_wake_dry_run(
        hermes_home=home,
        memcore_root=memcore,
        requested_by="codex-test",
        reason="verify signal flow",
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["signal_receipt_write_performed"] is False
    assert result["hermes_write_performed"] is False
    assert result["self_review_signal"]["scope"]["read_scope"] == "all_raw_memory"
    assert result["wake_plan"]["delivery_state"] == "not_delivered"
    assert result["wake_plan"]["requires_separate_runtime_integration_to_trigger_hermes"] is True
    assert result["wake_plan"]["does_not_package_zhiyi_summary"] is True
    assert result["receipt_draft"]["receipt_status"] == "draft_ready_for_authorized_record"
    assert not (memcore / "output" / "hermes_native_learning").exists()


def test_hermes_self_review_signal_receipt_requires_authorization(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")

    result = persist_hermes_self_review_signal_receipt(
        {"operator": "codex-test"},
        hermes_home=home,
        memcore_root=memcore,
    )

    assert result["ok"] is False
    assert result["write_performed"] is False
    assert "confirm_record_signal_receipt" in result["missing_authorization"]
    assert "confirm_no_hermes_write" in result["missing_authorization"]
    assert "confirm_no_raw_zhiyi_xingce_write" in result["missing_authorization"]
    assert "reason" in result["missing_authorization"]
    assert not (memcore / "output" / "hermes_native_learning").exists()


def test_hermes_self_review_signal_receipt_writes_memcore_receipt_only(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")

    result = persist_hermes_self_review_signal_receipt(
        {
            "authorization": {
                "operator": "codex-test",
                "reason": "record wake signal for Hermes review",
                "confirm_record_signal_receipt": True,
                "confirm_no_hermes_write": True,
                "confirm_no_raw_zhiyi_xingce_write": True,
            }
        },
        hermes_home=home,
        memcore_root=memcore,
    )

    assert result["ok"] is True
    assert result["write_performed"] is True
    assert result["signal_receipt_write_performed"] is True
    assert result["raw_write_performed"] is False
    assert result["zhiyi_write_performed"] is False
    assert result["xingce_write_performed"] is False
    assert result["hermes_write_performed"] is False
    assert result["openclaw_write_performed"] is False
    receipt_path = Path(result["receipt_path"])
    assert receipt_path.exists()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["receipt_status"] == "recorded_signal_only"
    assert receipt["read_scope"] == "all_raw_memory"
    assert receipt["read_hint"] == "这一片都是你该去读的原始记忆"
    assert receipt["write_boundary"]["signal_receipt_write_performed"] is True
    assert receipt["write_boundary"]["hermes_write_performed"] is False
    assert "does_not_package_zhiyi_summary" in receipt["notes"]


def test_hermes_self_review_trigger_requires_authorization(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    hermes_cli = tmp_path / "bin" / "hermes"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")
    _write(hermes_cli, "#!/bin/sh\nexit 0\n")

    result = trigger_hermes_self_review(
        {
            "hermes_cli": str(hermes_cli),
            "operator": "codex-test",
            "reason": "missing confirmations",
        },
        hermes_home=home,
        memcore_root=memcore,
    )

    assert result["ok"] is False
    assert result["hermes_trigger_called"] is False
    assert result["write_performed"] is False
    assert "confirm_live_hermes_trigger" in result["missing_authorization"]
    assert "confirm_hermes_may_read_raw_source_refs" in result["missing_authorization"]
    assert "confirm_hermes_native_artifacts_allowed" in result["missing_authorization"]
    assert "confirm_no_yifanchen_raw_zhiyi_xingce_write" in result["missing_authorization"]
    assert not (memcore / "output" / "hermes_native_learning" / "triggers").exists()


def test_hermes_self_review_trigger_plan_is_dry_run(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    hermes_cli = tmp_path / "bin" / "hermes"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")
    _write(hermes_cli, "#!/bin/sh\nexit 0\n")

    result = build_hermes_self_review_trigger_plan(
        {
            "hermes_cli": str(hermes_cli),
            "operator": "codex-test",
            "reason": "plan trigger",
        },
        hermes_home=home,
        memcore_root=memcore,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["hermes_cli_found"] is True
    assert result["wake"]["wake_plan"]["requires_separate_runtime_integration_to_trigger_hermes"] is True
    assert "confirm_live_hermes_trigger" in result["authorization_required"]
    assert result["write_boundary"]["hermes_native_artifacts_may_be_written_by_hermes"] is True
    assert result["write_boundary"]["hermes_skill_write_performed_by_yifanchen"] is False


def test_hermes_self_review_trigger_calls_runner_and_records_receipt_only(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    hermes_cli = tmp_path / "bin" / "hermes"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")
    _write(hermes_cli, "#!/bin/sh\nexit 0\n")
    captured = {}

    class Completed:
        returncode = 0
        stdout = "```json\n{\"review_status\":\"ok\",\"files_read_count\":3,\"candidate_count\":1}\n```"
        stderr = "session_id: hermes-test-session"

    def fake_runner(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        _write(home / "logs" / "agent.log", "background_review review_skills=true\nskill_manage\n")
        _write(home / "skills" / "software-development" / "new-native-review" / "SKILL.md", "# Native review\n")
        return Completed()

    result = trigger_hermes_self_review(
        {
            "hermes_cli": str(hermes_cli),
            "authorization": {
                "operator": "codex-test",
                "reason": "live trigger test",
                "confirm_live_hermes_trigger": True,
                "confirm_hermes_may_read_raw_source_refs": True,
                "confirm_hermes_native_artifacts_allowed": True,
                "confirm_no_yifanchen_raw_zhiyi_xingce_write": True,
            },
            "timeout_seconds": 30,
            "max_turns": 2,
        },
        hermes_home=home,
        memcore_root=memcore,
        runner=fake_runner,
    )

    assert result["ok"] is True
    assert result["hermes_trigger_called"] is True
    assert captured["command"][0] == str(hermes_cli)
    assert captured["command"][1:3] == ["chat", "-q"]
    assert "--skills" in captured["command"]
    assert "yifanchen-zhiyi" in captured["command"]
    assert result["trigger_receipt_write_performed"] is True
    assert result["raw_write_performed"] is False
    assert result["zhiyi_write_performed"] is False
    assert result["xingce_write_performed"] is False
    assert result["hermes_write_performed_by_yifanchen"] is False
    assert result["hermes_skill_write_performed_by_yifanchen"] is False
    assert result["liveness_after"]["native_skill_write_observed"] is True
    receipt_path = Path(result["receipt_path"])
    assert receipt_path.exists()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["receipt_status"] == "recorded_live_trigger"
    assert receipt["write_boundary"]["trigger_receipt_write_performed"] is True
    assert receipt["write_boundary"]["hermes_native_artifacts_may_be_written_by_hermes"] is True
    assert receipt["write_boundary"]["hermes_skill_write_performed_by_yifanchen"] is False
    assert receipt["native_observation"]["skill_write_observed_after_trigger"] is True

    queried = query_hermes_self_review_triggers(memcore_root=memcore)
    assert queried["ok"] is True
    assert queried["read_only"] is True
    assert queried["write_performed"] is False
    assert queried["count"] == 1
    assert queried["latest"]["latest_trigger_id"] == result["trigger_id"]
    assert queried["items"][0]["trigger_id"] == result["trigger_id"]
    assert queried["items"][0]["exit_code"] == 0
    assert queried["items"][0]["native_skill_write_observed_after_trigger"] is True
    assert queried["items"][0]["write_boundary"]["hermes_skill_write_performed_by_yifanchen"] is False


def test_hermes_skill_generation_probe_plan_is_stage_gated_dry_run(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    hermes_cli = tmp_path / "bin" / "hermes"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")
    _write(hermes_cli, "#!/bin/sh\nexit 0\n")

    result = build_hermes_skill_generation_probe_plan(
        {
            "hermes_cli": str(hermes_cli),
            "operator": "codex-test",
            "reason": "plan skill probe",
        },
        hermes_home=home,
        memcore_root=memcore,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["probe_id"].startswith("hermes-skill-generation-probe-")
    assert result["stage_gates"]["c_skill_artifact_change"] == "non-Yifanchen skill file is added or modified"
    assert "confirm_live_hermes_skill_generation_probe" in result["authorization_required"]
    assert result["write_boundary"]["hermes_native_artifacts_may_be_written_by_hermes"] is True
    assert result["write_boundary"]["hermes_skill_write_performed_by_yifanchen"] is False


def test_hermes_skill_generation_probe_requires_authorization(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    hermes_cli = tmp_path / "bin" / "hermes"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")
    _write(hermes_cli, "#!/bin/sh\nexit 0\n")

    result = trigger_hermes_skill_generation_probe(
        {
            "hermes_cli": str(hermes_cli),
            "operator": "codex-test",
            "reason": "missing confirmations",
        },
        hermes_home=home,
        memcore_root=memcore,
    )

    assert result["ok"] is False
    assert result["hermes_trigger_called"] is False
    assert result["write_performed"] is False
    assert "confirm_live_hermes_skill_generation_probe" in result["missing_authorization"]
    assert "confirm_hermes_may_read_raw_source_refs" in result["missing_authorization"]
    assert "confirm_hermes_native_skill_artifacts_allowed" in result["missing_authorization"]
    assert "confirm_no_yifanchen_raw_zhiyi_xingce_write" in result["missing_authorization"]
    assert not (memcore / "output" / "hermes_native_learning" / "skill_generation_probes").exists()


def test_hermes_skill_generation_probe_does_not_claim_success_without_skill_diff(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    hermes_cli = tmp_path / "bin" / "hermes"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")
    _write(hermes_cli, "#!/bin/sh\nexit 0\n")

    class Completed:
        returncode = 0
        stdout = "```json\n{\"probe_status\":\"ok\",\"skill_action_attempted\":false}\n```"
        stderr = "session_id: hermes-skill-probe"

    def fake_runner(command, **kwargs):
        _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
        return Completed()

    result = trigger_hermes_skill_generation_probe(
        {
            "hermes_cli": str(hermes_cli),
            "authorization": {
                "operator": "codex-test",
                "reason": "probe should not pass without skill diff",
                "confirm_live_hermes_skill_generation_probe": True,
                "confirm_hermes_may_read_raw_source_refs": True,
                "confirm_hermes_native_skill_artifacts_allowed": True,
                "confirm_no_yifanchen_raw_zhiyi_xingce_write": True,
            },
            "timeout_seconds": 30,
            "max_turns": 2,
        },
        hermes_home=home,
        memcore_root=memcore,
        runner=fake_runner,
    )

    assert result["ok"] is True
    assert result["skill_generation_success"] is False
    assert result["skill_generation_stage"] == "a_hermes_trigger_success_only"
    assert result["skill_generation_observation"]["trigger_success"] is True
    assert result["skill_generation_observation"]["skill_file_changed"] is False
    assert "no_non_yifanchen_skill_file_change" in result["skill_generation_observation"]["blockers"]
    assert result["probe_receipt_write_performed"] is True
    assert result["hermes_skill_write_performed_by_yifanchen"] is False


def test_hermes_skill_generation_probe_records_success_only_on_skill_file_diff(tmp_path):
    home = tmp_path / "hermes"
    memcore = tmp_path / "memcore"
    hermes_cli = tmp_path / "bin" / "hermes"
    _write(home / "logs" / "agent.log", "ordinary chat without native review\n")
    _write(home / "skills" / "yifanchen" / "yifanchen-zhiyi" / "SKILL.md", "# Yifanchen\n")
    _write(hermes_cli, "#!/bin/sh\nexit 0\n")
    captured = {}

    class Completed:
        returncode = 0
        stdout = "```json\n{\"probe_status\":\"created\",\"skill_action_attempted\":true,\"skill_action_result\":\"created\"}\n```"
        stderr = "session_id: hermes-skill-probe"

    def fake_runner(command, **kwargs):
        captured["command"] = command
        _write(home / "logs" / "agent.log", "background_review review_skills=true\nskill_manage create skill\n")
        _write(home / "skills" / "software-development" / "raw-evidence-discipline" / "SKILL.md", "# Raw evidence discipline\n")
        return Completed()

    result = trigger_hermes_skill_generation_probe(
        {
            "hermes_cli": str(hermes_cli),
            "authorization": {
                "operator": "codex-test",
                "reason": "probe should pass with skill diff",
                "confirm_live_hermes_skill_generation_probe": True,
                "confirm_hermes_may_read_raw_source_refs": True,
                "confirm_hermes_native_skill_artifacts_allowed": True,
                "confirm_no_yifanchen_raw_zhiyi_xingce_write": True,
            },
            "timeout_seconds": 30,
            "max_turns": 2,
        },
        hermes_home=home,
        memcore_root=memcore,
        runner=fake_runner,
    )

    assert result["ok"] is True
    assert result["skill_generation_success"] is True
    assert result["skill_generation_stage"] == "c_skill_artifact_changed"
    assert captured["command"][1:3] == ["chat", "-q"]
    assert "--skills" in captured["command"]
    assert "yifanchen-zhiyi" in captured["command"]
    assert result["skill_generation_observation"]["background_review_seen"] is True
    assert result["skill_generation_observation"]["skill_manage_seen"] is True
    assert result["skill_generation_observation"]["skill_file_changed"] is True
    assert result["skill_file_diff"]["non_yifanchen_changed_count"] == 1
    assert result["raw_write_performed"] is False
    assert result["zhiyi_write_performed"] is False
    assert result["xingce_write_performed"] is False
    assert result["hermes_skill_write_performed_by_yifanchen"] is False
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["skill_generation_observation"]["skill_generation_success"] is True
    assert receipt["write_boundary"]["probe_receipt_write_performed"] is True
    assert receipt["write_boundary"]["hermes_skill_write_performed_by_yifanchen"] is False

    queried = query_hermes_skill_generation_probes(memcore_root=memcore)
    assert queried["ok"] is True
    assert queried["read_only"] is True
    assert queried["count"] == 1
    assert queried["latest"]["latest_probe_id"] == result["probe_id"]
    assert queried["items"][0]["skill_generation_success"] is True
    assert queried["items"][0]["skill_file_changed"] is True


def _write_probe_receipt(memcore: Path, receipt: dict) -> Path:
    directory = memcore / "output" / "hermes_native_learning" / "skill_generation_probes"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "latest.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_hermes_skill_artifact_status_dry_run_builds_review_only_artifact(tmp_path):
    memcore = tmp_path / "memcore"
    receipt_path = _write_probe_receipt(memcore, {
        "probe_id": "hermes-skill-generation-probe-2fec7027343c3a92",
        "skill_generation_observation": {
            "skill_generation_success": True,
            "skill_generation_stage": "c_skill_artifact_changed",
        },
        "skill_file_diff": {
            "non_yifanchen_changed": [
                {
                    "relative_path": "yifanchen/zhiyi-recall-check/SKILL.md",
                    "path": r"C:\Users\56214\AppData\Local\hermes\skills\yifanchen\zhiyi-recall-check\SKILL.md",
                    "sha256": "1c2fb11afc3148e5c21686c6401c576b73d483c85753be5803ebc63eec1f1e34",
                }
            ]
        },
    })

    result = build_hermes_skill_artifact_status_dry_run(
        {
            "skill_artifact_status": "probe_only_not_adopted",
            "summary": "Hermes generated zhiyi-recall-check, but it is probe-only and not adopted.",
        },
        memcore_root=memcore,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["ready_for_record"] is True
    draft = result["status_draft"]
    assert draft["artifact_type"] == "hermes_skill_artifact_status"
    assert draft["status_id"].startswith("hermes-skill-artifact-status-")
    assert draft["probe_id"] == "hermes-skill-generation-probe-2fec7027343c3a92"
    assert draft["probe_receipt_path"] == str(receipt_path)
    assert draft["skill_artifact_status"] == "probe_only_not_adopted"
    assert draft["skill_relative_path"] == "yifanchen/zhiyi-recall-check/SKILL.md"
    assert draft["skill_sha256"] == "1c2fb11afc3148e5c21686c6401c576b73d483c85753be5803ebc63eec1f1e34"
    assert draft["write_boundary"]["status_receipt_write_performed"] is False
    assert draft["write_boundary"]["raw_write_performed"] is False
    assert draft["write_boundary"]["hermes_skill_write_performed_by_yifanchen"] is False
    assert "confirm_record_hermes_skill_artifact_status" in result["authorization_required"]


def test_hermes_skill_artifact_status_record_requires_authorization(tmp_path):
    memcore = tmp_path / "memcore"
    _write_probe_receipt(memcore, {
        "probe_id": "hermes-skill-generation-probe-auth",
        "skill_generation_observation": {"skill_generation_success": True},
        "skill_file_diff": {
            "non_yifanchen_changed": [
                {"relative_path": "yifanchen/zhiyi-recall-check/SKILL.md"}
            ]
        },
    })

    result = record_hermes_skill_artifact_status(
        {"operator": "codex-test", "reason": "missing confirmations"},
        memcore_root=memcore,
    )

    assert result["ok"] is False
    assert result["write_performed"] is False
    assert result["status_receipt_write_performed"] is False
    assert "confirm_record_hermes_skill_artifact_status" in result["missing_authorization"]
    assert "confirm_no_raw_zhiyi_xingce_write" in result["missing_authorization"]
    assert "confirm_no_hermes_skill_write_by_yifanchen" in result["missing_authorization"]
    assert "confirm_no_production_experience_adoption" in result["missing_authorization"]
    assert not (memcore / "output" / "hermes_native_learning" / "skill_artifact_status").exists()


def test_hermes_skill_artifact_status_records_status_only(tmp_path):
    memcore = tmp_path / "memcore"
    _write_probe_receipt(memcore, {
        "probe_id": "hermes-skill-generation-probe-2fec7027343c3a92",
        "skill_generation_observation": {
            "skill_generation_success": True,
            "skill_generation_stage": "c_skill_artifact_changed",
        },
        "skill_file_diff": {
            "non_yifanchen_changed": [
                {
                    "relative_path": "yifanchen/zhiyi-recall-check/SKILL.md",
                    "path": r"C:\Users\56214\AppData\Local\hermes\skills\yifanchen\zhiyi-recall-check\SKILL.md",
                    "sha256": "1c2fb11afc3148e5c21686c6401c576b73d483c85753be5803ebc63eec1f1e34",
                }
            ]
        },
    })

    result = record_hermes_skill_artifact_status(
        {
            "authorization": {
                "operator": "codex-test",
                "reason": "make Hermes skill probe verdict recallable",
                "confirm_record_hermes_skill_artifact_status": True,
                "confirm_no_raw_zhiyi_xingce_write": True,
                "confirm_no_hermes_skill_write_by_yifanchen": True,
                "confirm_no_production_experience_adoption": True,
            },
            "skill_artifact_status": "probe_only_not_adopted",
            "summary": "Hermes generated zhiyi-recall-check, but quality review says probe-only not adopted.",
            "current_state": "Fresh Hermes only used session_search; forced skill preload called MCP but did not hit the probe verdict.",
            "next_step": "Record status first, then verify recall before any adoption.",
        },
        memcore_root=memcore,
    )

    assert result["ok"] is True
    assert result["write_performed"] is True
    assert result["status_receipt_write_performed"] is True
    assert result["raw_write_performed"] is False
    assert result["zhiyi_write_performed"] is False
    assert result["xingce_write_performed"] is False
    assert result["hermes_skill_write_performed_by_yifanchen"] is False
    assert result["production_experience_write_performed"] is False

    latest = memcore / "output" / "hermes_native_learning" / "skill_artifact_status" / "latest.json"
    assert latest.exists()
    status = json.loads(latest.read_text(encoding="utf-8"))
    assert status["artifact_type"] == "hermes_skill_artifact_status"
    assert status["skill_artifact_status"] == "probe_only_not_adopted"
    assert status["probe_id"] == "hermes-skill-generation-probe-2fec7027343c3a92"
    assert status["write_boundary"]["status_receipt_write_performed"] is True
    assert status["write_boundary"]["production_experience_write_performed"] is False
    assert "not_a_skill_adoption" in status["notes"]

    queried = query_hermes_skill_artifact_statuses(memcore_root=memcore)
    assert queried["ok"] is True
    assert queried["read_only"] is True
    assert queried["count"] == 1
    assert queried["latest"]["latest_status_id"] == result["status_id"]
    assert queried["items"][0]["skill_artifact_status"] == "probe_only_not_adopted"
