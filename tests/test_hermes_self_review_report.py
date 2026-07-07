import importlib
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _sample_receipt() -> dict:
    return {
        "trigger_id": "hermes-self-review-trigger-test",
        "receipt_status": "recorded_live_trigger",
        "hermes_trigger": {
            "called": True,
            "exit_code": 0,
            "timed_out": False,
            "stdout_excerpt": """## Time Library原始记忆自审 — Review Report

#### 候选 #1: 「经验不是 skill」分野

- **来源路径**: `/memcore/zhiyi/preference_memory.jsonl`
- **原话片段**:
  > 知识不等于可执行函数
- **验收条件**: 回答 skill 边界时引用这条
""",
            "stderr_excerpt": "session_id: 20260531_test",
        },
        "native_observation": {
            "skill_write_observed_after_trigger": False,
        },
    }


def _failed_receipt() -> dict:
    return {
        "trigger_id": "hermes-self-review-trigger-failed",
        "receipt_status": "recorded_live_trigger",
        "hermes_trigger": {
            "called": True,
            "exit_code": 1,
            "timed_out": False,
            "stdout_excerpt": "Failed to initialize agent: The 'anthropic' package is required for the Anthropic provider.",
            "stderr_excerpt": "",
        },
        "native_observation": {
            "skill_write_observed_after_trigger": False,
        },
    }


def _state_db_receipt() -> dict:
    receipt = _sample_receipt()
    receipt["trigger_id"] = "hermes-self-review-trigger-state-db"
    receipt["hermes_trigger"]["stdout_excerpt"] = ""
    receipt["hermes_trigger"]["stderr_excerpt"] = "session_id: 20260531_state_db"
    return receipt


def _write_hermes_state_db(path: Path, rows: list[tuple[str, str, str, str, int]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE messages (id TEXT, session_id TEXT, role TEXT, content TEXT, timestamp INTEGER)")
    con.executemany(
        "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()
    con.close()
    return path


def test_self_review_report_dry_run_builds_review_candidate(tmp_path):
    module = importlib.import_module("hermes_self_review_report")
    memcore = tmp_path / "memcore"
    _write_json(memcore / "output" / "hermes_native_learning" / "triggers" / "latest.json", _sample_receipt())

    result = module.build_hermes_self_review_report_dry_run(memcore_root=memcore)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["candidate"]["candidate_type"] == "hermes_self_review_report_candidate"
    assert result["upgrade_input"]["candidate_type"] == "hermes_self_review_report_upgrade_input"
    assert result["upgrade_input"]["experience_upgrade_ready"] is True
    assert result["review_text_source"] == "stdout_excerpt"
    assert result["candidate"]["report_items"][0]["title"] == "经验不是 skill」分野"
    assert result["candidate"]["write_boundary"]["hermes_skill_write_performed"] is False
    assert result["candidate"]["write_boundary"]["production_experience_write_performed"] is False


def test_self_review_report_dry_run_does_not_treat_failed_stdout_as_report(tmp_path):
    module = importlib.import_module("hermes_self_review_report")
    memcore = tmp_path / "memcore"
    _write_json(memcore / "output" / "hermes_native_learning" / "triggers" / "latest.json", _failed_receipt())

    result = module.build_hermes_self_review_report_dry_run(memcore_root=memcore)

    assert result["ok"] is False
    assert result["trigger_success"] is False
    assert result["report_available"] is False
    assert result["diagnostic_available"] is True
    assert "anthropic" in result["diagnostic_excerpt"]
    assert result["candidate"]["report_items"] == []
    assert result["upgrade_input"]["experience_upgrade_ready"] is False
    assert result["upgrade_input"]["upgrade_input_status"] == "blocked_no_successful_report"


def test_self_review_report_dry_run_reads_windows_native_state_db_when_stdout_empty(tmp_path):
    module = importlib.import_module("hermes_self_review_report")
    memcore = tmp_path / "memcore"
    state_db = tmp_path / "hermes" / "state.db"
    report_text = """## Time Library原始记忆自审 — Hermes 自审报告

#### 候选 #1: 「Hermes 原生报告落库」

- **来源路径**: `/memory/hermes/state.db`
- **原话片段**:
  > Windows native Hermes wrote the report to state.db
- **验收条件**: stdout 为空时从 state.db 只读提取报告
"""
    _write_json(memcore / "output" / "hermes_native_learning" / "triggers" / "latest.json", _state_db_receipt())
    _write_hermes_state_db(
        state_db,
        [
            ("m1", "20260531_state_db", "user", "trigger prompt", 1),
            ("m2", "20260531_state_db", "assistant", "普通回答", 2),
            ("m3", "20260531_state_db", "assistant", json.dumps([{"type": "text", "text": report_text}], ensure_ascii=False), 3),
        ],
    )

    result = module.build_hermes_self_review_report_dry_run(
        {"hermes_state_db_path": str(state_db)},
        memcore_root=memcore,
    )

    assert result["ok"] is True
    assert result["trigger_success"] is True
    assert result["report_available"] is True
    assert result["review_text_source"] == "hermes_state_db"
    assert result["review_session_id"] == "20260531_state_db"
    assert result["review_state_db_path"] == str(state_db)
    assert result["review_state_db_error"] == ""
    assert result["candidate"]["review_state_db_message_id"] == "m3"
    assert result["candidate"]["report_items"][0]["title"] == "Hermes 原生报告落库"
    assert result["upgrade_input"]["experience_upgrade_ready"] is True
    assert any(ref["artifact_type"] == "hermes_state_db_self_review_report" for ref in result["candidate"]["source_refs"])


def test_self_review_report_dry_run_keeps_report_unavailable_when_state_db_has_no_report(tmp_path):
    module = importlib.import_module("hermes_self_review_report")
    memcore = tmp_path / "memcore"
    state_db = tmp_path / "hermes" / "state.db"
    _write_json(memcore / "output" / "hermes_native_learning" / "triggers" / "latest.json", _state_db_receipt())
    _write_hermes_state_db(
        state_db,
        [
            ("m1", "20260531_state_db", "assistant", "普通回答，没有自审报告", 1),
        ],
    )

    result = module.build_hermes_self_review_report_dry_run(
        {"hermes_state_db_path": str(state_db)},
        memcore_root=memcore,
    )

    assert result["ok"] is False
    assert result["trigger_success"] is True
    assert result["report_available"] is False
    assert result["diagnostic_available"] is False
    assert result["review_text_source"] == "stdout_excerpt"
    assert result["review_state_db_error"] == "self_review_report_not_found"
    assert result["upgrade_input"]["experience_upgrade_ready"] is False


def test_self_review_report_record_blocks_failed_trigger_even_when_authorized(tmp_path):
    module = importlib.import_module("hermes_self_review_report")
    memcore = tmp_path / "memcore"
    _write_json(memcore / "output" / "hermes_native_learning" / "triggers" / "latest.json", _failed_receipt())

    result = module.record_hermes_self_review_report_candidate(
        {
            "confirm_record_self_review_report_candidate": True,
            "confirm_no_raw_zhiyi_xingce_write": True,
            "confirm_no_hermes_skill_write": True,
            "operator": "pytest",
            "reason": "should stay diagnostic",
        },
        memcore_root=memcore,
    )

    assert result["ok"] is False
    assert result["write_performed"] is False
    assert "self_review_report_required" in result["guard_failures"]
    assert "successful_trigger_required" in result["guard_failures"]
    assert not (memcore / "output" / "hermes_experience_feedback" / "candidates").exists()


def test_self_review_report_record_requires_authorization_without_writing(tmp_path):
    module = importlib.import_module("hermes_self_review_report")
    memcore = tmp_path / "memcore"
    _write_json(memcore / "output" / "hermes_native_learning" / "triggers" / "latest.json", _sample_receipt())

    result = module.record_hermes_self_review_report_candidate({"operator": "pytest"}, memcore_root=memcore)

    assert result["ok"] is False
    assert result["write_performed"] is False
    assert "confirm_record_self_review_report_candidate" in result["missing_authorization"]
    assert not (memcore / "output" / "hermes_experience_feedback" / "candidates").exists()


def test_self_review_report_record_writes_review_artifacts_only(tmp_path):
    module = importlib.import_module("hermes_self_review_report")
    memcore = tmp_path / "memcore"
    _write_json(memcore / "output" / "hermes_native_learning" / "triggers" / "latest.json", _sample_receipt())

    result = module.record_hermes_self_review_report_candidate(
        {
            "confirm_record_self_review_report_candidate": True,
            "confirm_no_raw_zhiyi_xingce_write": True,
            "confirm_no_hermes_skill_write": True,
            "operator": "pytest",
            "reason": "record report candidate",
        },
        memcore_root=memcore,
    )

    assert result["ok"] is True
    assert result["write_performed"] is True
    assert result["candidate_artifact_write_performed"] is True
    assert result["upgrade_input_artifact_write_performed"] is True
    assert result["raw_write_performed"] is False
    assert result["zhiyi_write_performed"] is False
    assert result["xingce_write_performed"] is False
    assert result["hermes_skill_write_performed"] is False
    assert result["production_experience_write_performed"] is False
    assert Path(result["candidate_path"]).exists()
    assert Path(result["upgrade_input_path"]).exists()
    assert (memcore / "output" / "hermes_experience_feedback" / "candidates" / "latest.json").exists()
    assert (memcore / "output" / "hermes_experience_feedback" / "upgrade_inputs" / "latest.json").exists()
