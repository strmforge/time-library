import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TOOL = ROOT / "tools" / "code_change_tiandao_audit.py"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, text=True, capture_output=True)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_code_change_tiandao_source_reports_dirty_worktree_without_writing(tmp_path):
    from code_change_tiandao_source import build_code_change_tiandao_source_report

    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    (repo / "new_file.py").write_text("print('hi')\n", encoding="utf-8")

    report = build_code_change_tiandao_source_report(repo_root=repo)

    assert report["ok"] is True
    assert report["contract"] == "tiandao_code_change_source_inlet.v1"
    assert report["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert report["time_origin_contract"] == "tiandao_time_origin.v1"
    assert report["time_river_contract"] == "tiandao_time_river.v1"
    assert report["source_kind"] == "repository_code_change"
    assert report["dirty"] is True
    assert report["changed_file_count"] == 2
    assert report["source_evidence_kinds"] == ["git_status", "git_diff", "file_hash"]
    assert report["test_output_evidence_status"] == "not_supplied"
    assert report["verification_source_refs"] == []
    assert report["verification_source_ref_count"] == 0
    assert report["tiandao_ingest_status"] == "source_refs_only_until_raw_origin"
    assert report["origin_event_available"] is False
    assert report["candidate_until_raw_origin_linked"] is True
    assert report["code_change_policy"] == "code_changes_are_source_evidence_not_memory_sediment"
    assert report["adoption_policy"] == "do_not_auto_adopt_code_changes_into_zhiyi_xingce_or_toolbook"
    assert report["read_only"] is True
    assert report["write_performed"] is False
    assert report["raw_write_performed"] is False
    assert report["memory_write_performed"] is False
    assert report["platform_write_performed"] is False
    paths = {item["source_path"]: item for item in report["source_refs"]}
    assert paths["README.md"]["diff_sha256"]
    assert paths["README.md"]["content_sha256"]
    assert paths["new_file.py"]["tracked_state"] == "untracked"
    assert paths["new_file.py"]["diff_sha256"] == ""
    assert paths["new_file.py"]["content_sha256"]


def test_code_change_tiandao_source_can_include_verification_output_refs(tmp_path):
    from code_change_tiandao_source import build_code_change_tiandao_source_report

    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    output = repo / "tmp" / "pytest-output.txt"
    output.parent.mkdir()
    output.write_text("1 passed\n", encoding="utf-8")

    report = build_code_change_tiandao_source_report(
        repo_root=repo,
        verification_outputs=["tmp/pytest-output.txt"],
        verification_commands=["python3 -m pytest -q tests/test_code_change_tiandao_source.py"],
    )

    assert report["ok"] is True
    assert report["read_only"] is True
    assert report["memory_write_performed"] is False
    assert report["raw_write_performed"] is False
    assert "verification_output" in report["source_evidence_kinds"]
    assert report["test_output_evidence_status"] == "source_refs_only"
    assert report["verification_source_ref_count"] == 1
    assert report["verification_output_ref_count"] == 1
    verification_ref = report["verification_source_refs"][0]
    assert verification_ref["source_system"] == "maintainer_command"
    assert verification_ref["artifact_type"] == "code_change_verification_output"
    assert verification_ref["source_path"] == "tmp/pytest-output.txt"
    assert verification_ref["verification_command"] == "python3 -m pytest -q tests/test_code_change_tiandao_source.py"
    assert verification_ref["content_sha256"]
    assert verification_ref["evidence_status"] == "output_artifact_available"


def test_code_change_tiandao_source_package_id_includes_verification_refs(tmp_path):
    from code_change_tiandao_source import build_code_change_tiandao_source_report

    repo = _make_repo(tmp_path)
    output = repo / "verification.txt"
    output.write_text("first run\n", encoding="utf-8")

    without_verification = build_code_change_tiandao_source_report(repo_root=repo)
    with_verification = build_code_change_tiandao_source_report(
        repo_root=repo,
        verification_outputs=["verification.txt"],
        verification_commands=["python3 -m pytest -q tests/test_code_change_tiandao_source.py"],
    )

    assert without_verification["source_package_id"] != with_verification["source_package_id"]


def test_code_change_tiandao_source_clean_repo_is_still_read_only(tmp_path):
    from code_change_tiandao_source import build_code_change_tiandao_source_report

    repo = _make_repo(tmp_path)

    report = build_code_change_tiandao_source_report(repo_root=repo)

    assert report["ok"] is True
    assert report["dirty"] is False
    assert report["changed_file_count"] == 0
    assert report["source_refs"] == []
    assert report["test_output_evidence_status"] == "not_supplied"
    assert report["source_refs_available"] is False
    assert report["tiandao_ingest_status"] == "source_refs_only_until_raw_origin"
    assert report["memory_write_performed"] is False


def test_code_change_tiandao_source_can_require_complete_refs(tmp_path):
    from code_change_tiandao_source import build_code_change_tiandao_source_report

    repo = _make_repo(tmp_path)
    for index in range(3):
        (repo / f"changed_{index}.txt").write_text(f"changed {index}\n", encoding="utf-8")

    report = build_code_change_tiandao_source_report(
        repo_root=repo,
        max_refs=2,
        require_complete=True,
    )

    assert report["ok"] is False
    assert report["changed_file_count"] == 3
    assert report["source_ref_count"] == 2
    assert report["source_refs_truncated"] is True
    assert report["complete_source_refs"] is False
    assert report["complete_source_refs_required"] is True
    assert report["tiandao_ingest_status"] == "complete_source_refs_required"
    assert "source_refs_truncated_but_complete_source_refs_required" in report["limitations"]
    assert report["memory_write_performed"] is False
    assert report["raw_write_performed"] is False


def test_code_change_tiandao_source_non_git_archive_is_non_blocking_read_only(tmp_path):
    from code_change_tiandao_source import build_code_change_tiandao_source_report

    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("release archive\n", encoding="utf-8")

    report = build_code_change_tiandao_source_report(repo_root=source)

    assert report["ok"] is True
    assert report["repo_context_available"] is False
    assert report["status"] == "not_a_git_worktree"
    assert report["tiandao_ingest_status"] == "repo_context_unavailable"
    assert report["changed_file_count"] == 0
    assert report["source_refs"] == []
    assert report["read_only"] is True
    assert report["write_performed"] is False
    assert report["memory_write_performed"] is False
    assert report["platform_write_performed"] is False


def test_code_change_tiandao_audit_cli_outputs_json(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(TOOL), "--repo-root", str(repo), "--json"],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["contract"] == "tiandao_code_change_source_inlet.v1"
    assert payload["changed_file_count"] == 1


def test_code_change_tiandao_audit_cli_accepts_verification_output(tmp_path):
    repo = _make_repo(tmp_path)
    output = repo / "verification.txt"
    output.write_text("release gate PASS\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--repo-root",
            str(repo),
            "--verification-output",
            "verification.txt",
            "--verification-command",
            "python3 tools/release_gate.py --source working-tree --no-venv --skip-pytest",
            "--json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["verification_source_ref_count"] == 1
    assert payload["verification_output_ref_count"] == 1
    assert payload["verification_source_refs"][0]["source_path"] == "verification.txt"


def test_code_change_tiandao_audit_cli_can_require_complete_refs(tmp_path):
    repo = _make_repo(tmp_path)
    for index in range(2):
        (repo / f"changed_{index}.txt").write_text(f"changed {index}\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--repo-root",
            str(repo),
            "--max-refs",
            "1",
            "--require-complete",
            "--json",
        ],
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["source_refs_truncated"] is True
    assert payload["complete_source_refs_required"] is True


def test_code_change_tiandao_audit_cli_is_importable():
    spec = importlib.util.spec_from_file_location("code_change_tiandao_audit_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert callable(module.main)
