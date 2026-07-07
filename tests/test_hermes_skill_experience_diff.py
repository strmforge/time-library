import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_hermes_skill_experience_diff_builds_upgrade_candidate_without_writing():
    diff = importlib.import_module("hermes_skill_experience_diff")

    result = diff.build_hermes_skill_experience_diff_dry_run({
        "skills": [
            {
                "skill_id": "software-development/hermes-profile-config",
                "title": "Hermes profile config",
                "text": "# Hermes profile config\nProfile config.yaml is read from the profile directory. No root fallback. Validate with hermes profile show.",
                "source_refs": {
                    "source_system": "hermes",
                    "artifact_type": "hermes_skill_file",
                    "source_path": "/tmp/hermes/skills/hermes-profile-config/SKILL.md",
                },
            },
        ],
        "experiences": [
            {
                "library_id": "ZX-XINGCE-HERMES-PROFILE",
                "summary": "Hermes profile config is read from the profile directory.",
                "detail": "Validate with hermes profile show.",
                "source_refs": {
                    "source_system": "probe",
                    "source_path": "raw/probe_logs/hermes-profile.jsonl",
                },
                "verbatim_excerpt": "profile config.yaml was read from profiles/default/config.yaml",
            },
        ],
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["hermes_write_performed"] is False
    assert result["production_experience_write_performed"] is False
    assert result["summary"]["matched_skill_count"] == 1
    assert result["summary"]["upgrade_candidate_count"] == 1
    candidate = result["upgrade_candidates"]["candidates"][0]
    assert candidate["candidate_type"] == "hermes_skill_experience_upgrade_candidate"
    assert candidate["experience_upgrade_ready"] is True
    assert candidate["matched_experience"]["experience_id"] == "ZX-XINGCE-HERMES-PROFILE"
    assert candidate["skill"]["source_refs"]["artifact_type"] == "hermes_skill_file"
    assert candidate["write_boundary"]["hermes_skill_write_performed"] is False
    assert candidate["write_boundary"]["production_experience_write_performed"] is False


def test_hermes_skill_experience_diff_builds_adoption_candidate_for_unmatched_skill():
    diff = importlib.import_module("hermes_skill_experience_diff")

    result = diff.build_hermes_skill_experience_diff_dry_run({
        "skills": [
            {
                "skill_id": "workflow/new-review-loop",
                "title": "New review loop",
                "text": "# New review loop\nWhen background review creates a skill, compare it with experience before adoption.",
            },
        ],
        "experiences": [],
    })

    assert result["ok"] is True
    assert result["summary"]["new_skill_candidate_count"] == 1
    candidate = result["upgrade_candidates"]["candidates"][0]
    assert candidate["candidate_type"] == "hermes_skill_experience_adoption_candidate"
    assert candidate["matched_experience"] == {}
    assert candidate["write_boundary"]["raw_write_performed"] is False


def test_hermes_skill_experience_diff_can_scan_skill_files_read_only(tmp_path):
    diff = importlib.import_module("hermes_skill_experience_diff")
    home = tmp_path / "hermes"
    skill = home / "skills" / "workflow" / "review-loop" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Review loop\nCompare Hermes skill with Time Library experience before upgrade.\n", encoding="utf-8")

    result = diff.build_hermes_skill_experience_diff_dry_run({
        "hermes_home": str(home),
        "experiences": [],
    })

    assert result["skills_count"] == 1
    assert result["skill_experience_comparisons"][0]["skill_id"] == "workflow/review-loop"
    assert result["write_performed"] is False


def test_hermes_skill_experience_diff_plan_is_read_only():
    diff = importlib.import_module("hermes_skill_experience_diff")

    plan = diff.get_hermes_skill_experience_diff_plan()

    assert plan["ok"] is True
    assert plan["read_only"] is True
    assert plan["write_performed"] is False
    assert plan["endpoint"] == "/api/v1/hermes/skill-experience-diff/dry-run"
    assert "write_hermes_skill" in plan["forbidden_by_default"]
    assert "write_production_experience" in plan["forbidden_by_default"]
