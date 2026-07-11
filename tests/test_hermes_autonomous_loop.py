import json
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from src.hermes_autonomous_loop import (  # noqa: E402
    build_hermes_background_launchd_plist,
    build_hermes_autonomous_loop_plan,
    build_hermes_raw_watermark,
    load_hermes_background_config,
    load_hermes_background_state,
    load_hermes_autonomous_loop_state,
    query_hermes_autonomous_loop_runs,
    run_hermes_autonomous_loop_background_tick,
    run_hermes_autonomous_loop_once,
    write_hermes_background_config,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _hermes_cli(tmp_path: Path) -> Path:
    cli = tmp_path / "bin" / "hermes"
    return _write(cli, "#!/bin/sh\nexit 0\n")


def _hermes_home(tmp_path: Path) -> Path:
    home = tmp_path / "hermes"
    _write(home / "logs" / "agent.log", "ordinary chat\n")
    _write(home / "skills" / "time_library" / "time-library" / "SKILL.md", "# Time Library\n")
    return home


def _raw_file(root: Path, name: str = "session.jsonl", text: str = "{\"role\":\"user\",\"content\":\"new raw\"}\n") -> Path:
    return _write(
        root / "memory" / "local" / "hermes" / "hermes_state_db_messages_jsonl" / "session-a" / name,
        text,
    )


def _records_db(root: Path) -> Path:
    db = root / "output" / "records" / "records.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(
        """
        create table records(
          record_id text primary key,
          source_system text not null,
          session_id text,
          raw_artifact_id text,
          canonical_window_id text,
          project_id text,
          source_path text,
          raw_path text,
          source_mtime text,
          raw_mtime text,
          source_size_bytes integer,
          raw_size_bytes integer,
          user_turn_count integer,
          assistant_turn_count integer,
          bad_json_line_count integer,
          oversize_record_count integer,
          metadata_ok integer,
          has_user_and_assistant integer,
          raw_current integer,
          recoverable_from_raw integer,
          guard_status text,
          updated_at text,
          payload_json text
        );
        create table canonical_sessions(
          record_id text primary key,
          source_system text not null,
          session_id text,
          raw_artifact_id text,
          canonical_window_id text,
          project_id text,
          project_root text,
          thread_name text,
          source_path text,
          raw_path text,
          source_mtime text,
          raw_mtime text,
          source_size_bytes integer,
          raw_size_bytes integer,
          source_line_count integer,
          raw_line_count integer,
          indexed_message_count integer,
          indexed_chunk_count integer,
          raw_indexed_message_count integer,
          raw_offset_coverage_count integer,
          bad_json_line_count integer,
          oversized_line_count integer,
          index_status text,
          updated_at text,
          payload_json text
        );
        create table canonical_messages(
          message_id text primary key,
          record_id text not null,
          source_system text not null,
          session_id text,
          canonical_window_id text,
          project_id text,
          project_root text,
          source_path text,
          raw_path text,
          role text,
          native_type text,
          native_id text,
          timestamp text,
          line_no integer,
          raw_line_no integer,
          source_offset_start integer,
          source_offset_end integer,
          raw_offset_start integer,
          raw_offset_end integer,
          content_chars integer,
          content_hash text,
          line_hash text,
          content_preview text,
          raw_available integer,
          updated_at text,
          payload_json text
        );
        """
    )
    con.execute(
        """
        insert into records(record_id, source_system, session_id, raw_path, raw_mtime,
          raw_size_bytes, updated_at)
        values('r1','hermes','s1','/tmp/hermes.jsonl','2026-07-06T00:00:00Z',
          12,'2026-07-06T00:00:01Z')
        """
    )
    con.execute(
        """
        insert into canonical_sessions(record_id, source_system, session_id,
          raw_path, raw_mtime, indexed_message_count, updated_at)
        values('r1','hermes','s1','/tmp/hermes.jsonl','2026-07-06T00:00:00Z',
          1,'2026-07-06T00:00:01Z')
        """
    )
    con.execute(
        """
        insert into canonical_messages(message_id, record_id, source_system,
          session_id, raw_path, timestamp, content_preview, updated_at)
        values('m1','r1','hermes','s1','/tmp/hermes.jsonl',
          '2026-07-06T00:00:00Z','Hermes raw message','2026-07-06T00:00:01Z')
        """
    )
    con.commit()
    con.close()
    return db


def _auth():
    return {
        "operator": "codex-test",
        "reason": "verify value gated autonomous loop",
        "confirm_run_hermes_autonomous_loop": True,
        "confirm_hermes_may_read_raw_source_refs": True,
        "confirm_hermes_native_skill_artifacts_allowed": True,
        "confirm_no_time_library_raw_zhiyi_xingce_write": True,
        "confirm_no_unbounded_cron": True,
    }


def test_raw_watermark_reads_records_db_and_raw_files_without_writing(tmp_path):
    root = tmp_path / "memcore"
    _records_db(root)
    _raw_file(root)

    result = build_hermes_raw_watermark(memcore_root=root)

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["records_db"]["records_count"] == 1
    assert result["records_db"]["canonical_message_count"] == 1
    assert result["raw_files"]["file_count"] == 1
    assert result["source_event_count"] == 2


def test_no_new_raw_skips_hermes_and_spends_zero(tmp_path):
    root = tmp_path / "memcore"
    cli = _hermes_cli(tmp_path)
    _raw_file(root)
    initial = build_hermes_autonomous_loop_plan(
        {"hermes_cli": str(cli), "allow_first_run_bootstrap": True},
        memcore_root=root,
    )
    state = {
        "last_raw_watermark_token": initial["raw_watermark"]["watermark_token"],
        "consecutive_empty_outputs": 0,
        "backoff_multiplier": 1,
        "cadence_state": "normal",
    }
    state_path = root / "output" / "hermes_native_learning" / "autonomous_loop" / "state.json"
    _write(state_path, json.dumps(state))
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    result = run_hermes_autonomous_loop_once(
        {
            "hermes_cli": str(cli),
            "authorization": _auth(),
            "allow_first_run_bootstrap": True,
        },
        memcore_root=root,
        hermes_home=_hermes_home(tmp_path),
        runner=runner,
    )

    assert result["ok"] is True
    assert result["hermes_trigger_called"] is False
    assert calls == []
    receipt = result["receipt"]
    assert receipt["change_gate"]["decision"] == "skip_no_new_raw"
    assert receipt["change_gate"]["estimated_hermes_spend_units"] == 0
    assert receipt["write_boundary"]["hermes_skill_write_performed_by_time_library"] is False
    assert receipt["write_boundary"]["unbounded_cron_registered"] is False


def test_cost_cap_zero_blocks_trigger_even_with_new_raw(tmp_path):
    root = tmp_path / "memcore"
    cli = _hermes_cli(tmp_path)
    _raw_file(root)

    result = run_hermes_autonomous_loop_once(
        {
            "hermes_cli": str(cli),
            "authorization": _auth(),
            "allow_first_run_bootstrap": True,
            "max_triggers_per_cycle": 0,
        },
        memcore_root=root,
        hermes_home=_hermes_home(tmp_path),
        runner=lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    assert result["ok"] is True
    assert result["hermes_trigger_called"] is False
    assert result["receipt"]["change_gate"]["decision"] == "skip_cost_cap_reached"
    assert result["receipt"]["cost_cap"]["trigger_count_planned"] == 0


def test_empty_output_increments_streak_and_backoff(tmp_path):
    root = tmp_path / "memcore"
    cli = _hermes_cli(tmp_path)
    _raw_file(root)
    state_path = root / "output" / "hermes_native_learning" / "autonomous_loop" / "state.json"
    _write(state_path, json.dumps({
        "last_raw_watermark_token": "older-token",
        "consecutive_empty_outputs": 1,
        "backoff_multiplier": 1,
        "cadence_state": "normal",
    }))
    home = _hermes_home(tmp_path)

    class Completed:
        returncode = 0
        stdout = "{\"probe_status\":\"ok\"}"
        stderr = ""

    def runner(command, **kwargs):
        return Completed()

    result = run_hermes_autonomous_loop_once(
        {
            "hermes_cli": str(cli),
            "authorization": _auth(),
            "allow_first_run_bootstrap": True,
            "empty_backoff_threshold": 2,
            "base_interval_seconds": 100,
        },
        memcore_root=root,
        hermes_home=home,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["hermes_trigger_called"] is True
    receipt = result["receipt"]
    assert receipt["value_adaptation"]["outcome"] == "empty_output"
    assert receipt["value_adaptation"]["next_consecutive_empty_outputs"] == 2
    assert receipt["value_adaptation"]["next_backoff_multiplier"] == 2
    assert receipt["value_adaptation"]["next_cadence_state"] == "backoff"
    assert receipt["value_adaptation"]["recommended_next_interval_seconds"] == 200


def test_useful_skill_output_builds_source_backed_candidate_and_resets_backoff(tmp_path):
    root = tmp_path / "memcore"
    cli = _hermes_cli(tmp_path)
    _raw_file(root)
    state_path = root / "output" / "hermes_native_learning" / "autonomous_loop" / "state.json"
    _write(state_path, json.dumps({
        "last_raw_watermark_token": "older-token",
        "consecutive_empty_outputs": 3,
        "backoff_multiplier": 8,
        "cadence_state": "backoff",
    }))
    home = _hermes_home(tmp_path)

    class Completed:
        returncode = 0
        stdout = "{\"probe_status\":\"created\"}"
        stderr = ""

    def runner(command, **kwargs):
        _write(home / "logs" / "agent.log", "background_review review_skills=true\nskill_manage create skill\n")
        _write(home / "skills" / "workflow" / "valuable-review" / "SKILL.md", "# Valuable review\nUse raw source refs before adopting experience.\n")
        return Completed()

    def diff_builder(body, **kwargs):
        return {
            "ok": True,
            "read_only": True,
            "write_performed": False,
            "upgrade_candidates": {
                "candidate_count": 1,
                "candidates": [
                    {
                        "candidate_id": "hermes-skill-exp-adoption-test",
                        "candidate_type": "hermes_skill_experience_adoption_candidate",
                        "recommended_action": "review_skill_as_new_experience_candidate",
                        "activation_allowed": False,
                        "skill": {
                            "skill_id": "workflow/valuable-review",
                            "source_refs": {
                                "source_system": "hermes",
                                "artifact_type": "hermes_skill_file",
                                "source_path": str(home / "skills" / "workflow" / "valuable-review" / "SKILL.md"),
                            },
                        },
                    }
                ],
            },
            "summary": {"new_skill_candidate_count": 1},
        }

    result = run_hermes_autonomous_loop_once(
        {
            "hermes_cli": str(cli),
            "authorization": _auth(),
            "allow_first_run_bootstrap": True,
            "base_interval_seconds": 100,
        },
        memcore_root=root,
        hermes_home=home,
        runner=runner,
        diff_builder=diff_builder,
    )

    assert result["ok"] is True
    receipt = result["receipt"]
    assert receipt["trigger"]["skill_generation_success"] is True
    assert receipt["experience_candidate_delivery"]["delivery_status"] == "candidate_dry_run_built"
    assert receipt["experience_candidate_delivery"]["diff_summary"]["candidate_count"] == 1
    assert receipt["experience_candidate_delivery"]["activation_allowed"] is False
    assert receipt["value_adaptation"]["outcome"] == "useful_output"
    assert receipt["value_adaptation"]["next_consecutive_empty_outputs"] == 0
    assert receipt["value_adaptation"]["next_backoff_multiplier"] == 1
    assert receipt["value_adaptation"]["next_cadence_state"] == "fast"
    assert receipt["write_boundary"]["production_experience_write_performed"] is False
    state = load_hermes_autonomous_loop_state(memcore_root=root)["state"]
    assert state["consecutive_empty_outputs"] == 0
    queried = query_hermes_autonomous_loop_runs(memcore_root=root)
    assert queried["count"] == 1
    assert queried["items"][0]["candidate_count"] == 1


def test_background_first_tick_records_baseline_without_hermes_spend(tmp_path):
    root = tmp_path / "memcore"
    cli = _hermes_cli(tmp_path)
    _raw_file(root)
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    result = run_hermes_autonomous_loop_background_tick(
        {"hermes_cli": str(cli), "minimum_interval_seconds": 60},
        memcore_root=root,
        install_root=tmp_path,
        python_bin=cli,
        hermes_home=_hermes_home(tmp_path),
        runner=runner,
        now_epoch=1000,
    )

    assert result["ok"] is True
    assert result["decision"] == "baseline_without_spend"
    assert result["hermes_trigger_called"] is False
    assert calls == []
    receipt = result["receipt"]
    assert receipt["run"]["called"] is True
    assert receipt["run"]["hermes_trigger_called"] is False
    assert receipt["write_boundary"]["production_experience_write_performed"] is False
    loop_state = load_hermes_autonomous_loop_state(memcore_root=root)["state"]
    assert loop_state["total_hermes_spend_units"] == 0
    background_state = load_hermes_background_state(memcore_root=root)["state"]
    assert background_state["last_tick_decision"] == "baseline_without_spend"
    assert background_state["last_interval_anchor_epoch"] == 1000
    assert background_state["last_baseline_epoch"] == 1000
    assert background_state["last_trigger_epoch"] == 0


def test_background_tick_respects_minimum_interval_without_spend(tmp_path):
    root = tmp_path / "memcore"
    cli = _hermes_cli(tmp_path)
    _raw_file(root)
    first = run_hermes_autonomous_loop_background_tick(
        {"hermes_cli": str(cli), "minimum_interval_seconds": 3600},
        memcore_root=root,
        install_root=tmp_path,
        python_bin=cli,
        hermes_home=_hermes_home(tmp_path),
        now_epoch=1000,
    )
    assert first["decision"] == "baseline_without_spend"

    result = run_hermes_autonomous_loop_background_tick(
        {"hermes_cli": str(cli), "minimum_interval_seconds": 3600},
        memcore_root=root,
        install_root=tmp_path,
        python_bin=cli,
        hermes_home=_hermes_home(tmp_path),
        now_epoch=1200,
    )

    assert result["ok"] is True
    assert result["decision"] == "skip_interval_not_due"
    assert result["hermes_trigger_called"] is False
    assert result["receipt"]["reason"] == "minimum_interval_not_elapsed"
    assert result["receipt"]["interval_gate"]["anchor_epoch"] == 1000
    state = load_hermes_background_state(memcore_root=root)["state"]
    assert state["last_tick_epoch"] == 1200
    assert state["last_interval_anchor_epoch"] == 1000


def test_background_heartbeat_does_not_push_due_time_forever(tmp_path):
    root = tmp_path / "memcore"
    cli = _hermes_cli(tmp_path)
    raw = _raw_file(root, text="{\"role\":\"user\",\"content\":\"baseline\"}\n")
    home = _hermes_home(tmp_path)

    first = run_hermes_autonomous_loop_background_tick(
        {"hermes_cli": str(cli), "minimum_interval_seconds": 3600},
        memcore_root=root,
        install_root=tmp_path,
        python_bin=cli,
        hermes_home=home,
        now_epoch=1000,
    )
    assert first["decision"] == "baseline_without_spend"

    skipped = run_hermes_autonomous_loop_background_tick(
        {"hermes_cli": str(cli), "minimum_interval_seconds": 3600},
        memcore_root=root,
        install_root=tmp_path,
        python_bin=cli,
        hermes_home=home,
        now_epoch=1200,
    )
    assert skipped["decision"] == "skip_interval_not_due"

    raw.write_text(
        raw.read_text(encoding="utf-8")
        + "{\"role\":\"user\",\"content\":\"new material after baseline\"}\n",
        encoding="utf-8",
    )
    calls = []

    class Completed:
        returncode = 0
        stdout = "{\"probe_status\":\"created\"}"
        stderr = ""

    def runner(command, **kwargs):
        calls.append(command)
        _write(home / "logs" / "agent.log", "background_review review_skills=true\nskill_manage create skill\n")
        _write(home / "skills" / "workflow" / "due-review" / "SKILL.md", "# Due review\n")
        return Completed()

    due = run_hermes_autonomous_loop_background_tick(
        {
            "hermes_cli": str(cli),
            "minimum_interval_seconds": 3600,
            "daily_trigger_budget": 1,
            "daily_spend_budget": 1,
        },
        memcore_root=root,
        install_root=tmp_path,
        python_bin=cli,
        hermes_home=home,
        runner=runner,
        now_epoch=5000,
    )

    assert due["decision"] == "trigger_background_once"
    assert due["hermes_trigger_called"] is True
    assert calls
    assert due["receipt"]["interval_gate"]["anchor_epoch"] == 1000
    state = load_hermes_background_state(memcore_root=root)["state"]
    assert state["last_tick_epoch"] == 5000
    assert state["last_interval_anchor_epoch"] == 5000
    assert state["last_trigger_epoch"] == 5000


def test_background_tick_daily_budget_blocks_trigger(tmp_path):
    root = tmp_path / "memcore"
    cli = _hermes_cli(tmp_path)
    _raw_file(root)
    state_path = root / "output" / "hermes_native_learning" / "autonomous_loop" / "state.json"
    _write(state_path, json.dumps({
        "last_raw_watermark_token": "older-token",
        "consecutive_empty_outputs": 0,
        "backoff_multiplier": 1,
        "cadence_state": "normal",
    }))
    bg_state_path = root / "output" / "hermes_native_learning" / "autonomous_loop" / "background_state.json"
    _write(bg_state_path, json.dumps({
        "last_tick_epoch": 0,
        "daily_budget": {"day": "1970-01-01", "trigger_count": 1, "spend_units": 1},
    }))

    result = run_hermes_autonomous_loop_background_tick(
        {
            "hermes_cli": str(cli),
            "minimum_interval_seconds": 60,
            "daily_trigger_budget": 1,
            "daily_spend_budget": 1,
        },
        memcore_root=root,
        install_root=tmp_path,
        python_bin=cli,
        hermes_home=_hermes_home(tmp_path),
        now_epoch=1000,
    )

    assert result["ok"] is True
    assert result["decision"] == "skip_daily_trigger_budget_reached"
    assert result["hermes_trigger_called"] is False


def test_background_tick_due_with_new_raw_triggers_once_and_counts_budget(tmp_path):
    root = tmp_path / "memcore"
    cli = _hermes_cli(tmp_path)
    _raw_file(root, text="{\"role\":\"user\",\"content\":\"old raw\"}\n")
    state_path = root / "output" / "hermes_native_learning" / "autonomous_loop" / "state.json"
    _write(state_path, json.dumps({
        "last_raw_watermark_token": "older-token",
        "consecutive_empty_outputs": 0,
        "backoff_multiplier": 1,
        "cadence_state": "normal",
        "updated_at": "1970-01-01T00:00:00Z",
    }))
    bg_state_path = root / "output" / "hermes_native_learning" / "autonomous_loop" / "background_state.json"
    _write(bg_state_path, json.dumps({
        "last_tick_epoch": 0,
        "daily_budget": {"day": "1970-01-01", "trigger_count": 0, "spend_units": 0},
    }))
    home = _hermes_home(tmp_path)
    calls = []

    class Completed:
        returncode = 0
        stdout = "{\"probe_status\":\"created\"}"
        stderr = ""

    def runner(command, **kwargs):
        calls.append(command)
        _write(home / "logs" / "agent.log", "background_review review_skills=true\nskill_manage create skill\n")
        _write(home / "skills" / "workflow" / "valuable-review" / "SKILL.md", "# Valuable review\n")
        return Completed()

    def diff_builder(body, **kwargs):
        return {
            "ok": True,
            "read_only": True,
            "write_performed": False,
            "upgrade_candidates": {
                "candidate_count": 1,
                "candidates": [
                    {
                        "candidate_id": "hermes-skill-exp-adoption-test",
                        "candidate_type": "hermes_skill_experience_adoption_candidate",
                        "recommended_action": "review_skill_as_new_experience_candidate",
                        "activation_allowed": False,
                        "skill": {"skill_id": "workflow/valuable-review", "source_refs": {"source_system": "hermes"}},
                    }
                ],
            },
        }

    result = run_hermes_autonomous_loop_background_tick(
        {
            "hermes_cli": str(cli),
            "minimum_interval_seconds": 60,
            "daily_trigger_budget": 1,
            "daily_spend_budget": 1,
        },
        memcore_root=root,
        install_root=tmp_path,
        python_bin=cli,
        hermes_home=home,
        runner=runner,
        diff_builder=diff_builder,
        now_epoch=1000,
    )

    assert result["ok"] is True
    assert result["decision"] == "trigger_background_once"
    assert result["hermes_trigger_called"] is True
    assert calls
    assert result["receipt"]["run"]["candidate_count"] == 1
    assert result["receipt"]["state_after"]["daily_budget"]["trigger_count"] == 1
    assert result["receipt"]["state_after"]["daily_budget"]["spend_units"] == 1
    assert result["receipt"]["write_boundary"]["production_experience_write_performed"] is False


def test_background_trigger_failure_does_not_spend_advance_watermark_or_delay_retry(tmp_path):
    root = tmp_path / "memcore"
    cli = _hermes_cli(tmp_path)
    _raw_file(root, text="{\"role\":\"user\",\"content\":\"new material\"}\n")
    state_path = root / "output" / "hermes_native_learning" / "autonomous_loop" / "state.json"
    _write(state_path, json.dumps({
        "last_raw_watermark_token": "older-token",
        "last_raw_watermark": {"watermark_token": "older-token"},
        "consecutive_empty_outputs": 0,
        "backoff_multiplier": 1,
        "cadence_state": "normal",
    }))

    class Failed:
        returncode = 1
        stdout = "Error: Unknown skill"
        stderr = ""

    result = run_hermes_autonomous_loop_background_tick(
        {
            "hermes_cli": str(cli),
            "minimum_interval_seconds": 60,
            "daily_trigger_budget": 1,
            "daily_spend_budget": 1,
        },
        memcore_root=root,
        install_root=tmp_path,
        python_bin=cli,
        hermes_home=_hermes_home(tmp_path),
        runner=lambda command, **kwargs: Failed(),
        now_epoch=1000,
    )

    assert result["ok"] is False
    assert result["decision"] == "trigger_background_failed"
    assert result["hermes_trigger_called"] is True
    assert result["hermes_trigger_succeeded"] is False
    assert result["receipt"]["state_after"]["daily_budget"]["trigger_count"] == 0
    assert result["receipt"]["state_after"]["daily_budget"]["spend_units"] == 0
    background = load_hermes_background_state(memcore_root=root)["state"]
    assert not background.get("last_interval_anchor_epoch")
    assert not background.get("last_trigger_epoch")
    loop = load_hermes_autonomous_loop_state(memcore_root=root)["state"]
    assert loop["last_raw_watermark_token"] == "older-token"
    assert loop["total_trigger_count"] == 0
    assert loop["total_hermes_spend_units"] == 0


def test_background_launchd_plist_is_bounded_wakeup_not_keepalive(tmp_path):
    root = tmp_path / "memcore"
    python_bin = tmp_path / ".venv" / "bin" / "python"
    write_hermes_background_config(
        {"start_interval_seconds": 3600},
        memcore_root=root,
        install_root=tmp_path,
        python_bin=python_bin,
    )

    result = build_hermes_background_launchd_plist(
        memcore_root=root,
        install_root=tmp_path,
        python_bin=python_bin,
    )

    assert result["ok"] is True
    plist = result["plist"]
    assert plist["RunAtLoad"] is False
    assert plist["KeepAlive"] is False
    assert plist["StartInterval"] == 3600
    assert "tick" in plist["ProgramArguments"]
    assert str(root) in plist["ProgramArguments"]
    assert result["launchd_boundary"]["value_gate_controls_spend"] is True
    loaded = load_hermes_background_config(memcore_root=root, install_root=tmp_path, python_bin=python_bin)
    assert loaded["config"]["auto_production_adoption_allowed"] is False
