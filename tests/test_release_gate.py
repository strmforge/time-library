import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_GATE = ROOT / "tools" / "release_gate.py"


def _load_release_gate():
    spec = importlib.util.spec_from_file_location("release_gate_under_test", RELEASE_GATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_release_gate_uses_clean_head_archive_by_default():
    gate = _load_release_gate()
    text = RELEASE_GATE.read_text(encoding="utf-8")

    assert 'default="head"' in text
    assert '"git", "archive"' in text
    assert "HEAD" in text
    assert "working-tree" in text
    assert "copy_working_tree" in text
    assert ".git" in text
    assert ".venv" in text
    assert "memory" in text
    assert "logs" in text
    assert "backups" in text
    assert tuple(gate.PUBLIC_DOCS) == (
        "README.md",
        "README.en.md",
        "README.zh-CN.md",
        "docs/wiki/Getting-Started.md",
    )
    surface_paths = tuple(gate.PUBLIC_SURFACE_PATHS)
    assert "tools/windows_native_smoke.ps1" in surface_paths
    assert "tools/windows_full_install.ps1" in surface_paths
    assert "docs" in surface_paths


def test_release_gate_guards_public_install_and_authorization_terms():
    gate = _load_release_gate()
    terms = tuple(gate.PUBLIC_FORBIDDEN_TERMS)
    repo_terms = tuple(gate.REPOSITORY_FORBIDDEN_TERMS)

    assert gate._term("CC", " Switch") in terms
    assert gate._term("cc", "switch") in terms
    assert gate._term("cc", "-switch") in terms
    assert gate._term("or", "phan") in repo_terms
    assert gate._term("or", "phan raw") in repo_terms
    assert "raw.githubusercontent.com/strmforge/memcore-cloud/main/install" in terms
    assert "archive/refs/heads/main.zip" in terms
    assert "memcore-cloud-main.zip" in terms
    assert "| bash" in terms
    assert "| iex" in terms
    assert "can_auto_connect_without_authorization" in terms
    assert "can_write_platform_config_without_authorization" in terms
    assert "can_parse_chat_bodies_without_authorization" in terms


def test_release_gate_runs_core_release_checks():
    text = RELEASE_GATE.read_text(encoding="utf-8")

    assert "requirements-core.txt" in text
    assert "requirements-dev.txt" in text
    assert "py_compile" in text
    assert "run_internal_direction_audit" in text
    assert "tools\" / \"internal_direction_audit.py" in text
    assert "run_core_record_reliability_contract" in text
    assert "tools\" / \"core_record_reliability_audit.py" in text
    assert "--contract-only" in text
    assert '"--format", "json"' in text
    assert "pytest" in text
    assert '["bash", "-n", "install.sh"]' in text
    assert '["bash", "-n", "tools/macos_full_install.sh"]' in text
    assert '["bash", "-n", "tools/linux_full_install.sh"]' in text
    assert "git diff" in text


def test_release_gate_includes_dialog_entry_install_safety_checks():
    text = RELEASE_GATE.read_text(encoding="utf-8")

    assert "tools/macos_full_install.sh" in text
    assert "tools/linux_full_install.sh" in text
