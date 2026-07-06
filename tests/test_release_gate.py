import importlib.util
import sys
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
    assert "--exclude-standard" in text
    assert "shutil.copy2" in text
    assert "PRIVATE_RELEASE_PREFIXES" in text
    assert "PRIVATE_TOP_LEVEL_FILES" in text
    assert "assert_no_private_top_level_files" in text
    assert "PRIVATE_RELEASE_PREFIXES" in text
    assert "assert_no_private_release_prefixes" in text
    assert "FORBIDDEN_PUBLIC_EVAL_PATHS" in text
    assert "assert_no_public_eval_payload" in text
    assert "assert_product_src_does_not_import_eval" in text
    assert "assert_runtime_version_uses_version_file" in text
    assert "PERSONAL_IDENTITY_TERMS" in text
    assert "assert_no_personal_identity_terms" in text
    assert tuple(gate.PRIVATE_TOP_LEVEL_FILES) == (
        "AGENTS.md",
        "CODEX_CONTINUITY_LEDGER.md",
        "design-qa.md",
        "known-issues.md",
    )
    assert tuple(gate.PRIVATE_RELEASE_PREFIXES) == (
        "docs/construction/",
        "docs/decisions/",
    )
    assert "yang" + "haibin" in tuple(gate.PERSONAL_IDENTITY_TERMS)
    assert "src/official_memory_benchmarks.py" in tuple(gate.FORBIDDEN_PUBLIC_EVAL_PATHS)
    assert "tools/model_memory_judge.py" in tuple(gate.FORBIDDEN_PUBLIC_EVAL_PATHS)
    assert "benchmarks/README.md" in tuple(gate.FORBIDDEN_PUBLIC_EVAL_PATHS)
    assert "official_memory_benchmarks" in tuple(gate.FORBIDDEN_PRODUCT_IMPORT_MODULES)
    assert "benchmarks" in tuple(gate.FORBIDDEN_PRODUCT_IMPORT_MODULES)
    assert "web/console_product.html" in tuple(gate.RUNTIME_VERSION_SURFACE_PATHS)
    assert "src/raw_consumption_gateway.py" in tuple(gate.RUNTIME_VERSION_SURFACE_PATHS)
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
    assert "Time Library Installer.command" in surface_paths
    assert "Time Library Installer.cmd" in surface_paths
    assert "uninstall.sh" in surface_paths
    assert "uninstall.ps1" in surface_paths


def test_release_gate_guards_public_install_and_authorization_terms():
    gate = _load_release_gate()
    terms = tuple(gate.PUBLIC_FORBIDDEN_TERMS)
    repo_terms = tuple(gate.REPOSITORY_FORBIDDEN_TERMS)

    assert gate._term("CC", " Switch") in terms
    assert gate._term("cc", "switch") in terms
    assert gate._term("cc", "-switch") in terms
    assert gate._term("or", "phan") in repo_terms
    assert gate._term("or", "phan raw") in repo_terms
    assert "raw.githubusercontent.com/strmforge/time-library/main/install" in terms
    assert "archive/refs/heads/main.zip" in terms
    assert "time-library-main.zip" in terms
    assert "| bash" in terms
    assert "| iex" in terms
    assert "can_auto_connect_without_authorization" in terms
    assert "can_write_platform_config_without_authorization" in terms
    assert "can_parse_chat_bodies_without_authorization" in terms
    assert gate._term("capability", " matrix") in terms
    assert gate._term("能力", "矩阵") in terms
    assert gate._term("hooks", " / MCP / REST") in terms
    assert gate._term("AGENTS", ".md") in terms
    assert gate._term("旧的", "游离记录") in terms


def test_release_gate_scans_uninstall_public_surface():
    gate = _load_release_gate()
    repo_paths = tuple(gate.REPOSITORY_WORDING_PATHS)

    assert "uninstall.sh" in repo_paths
    assert "uninstall.ps1" in repo_paths


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
    assert "DEFAULT_RELEASE_PYTEST_ARGS" in text
    assert "tests/test_release_artifact.py" in text
    assert "tests/test_security_boundaries.py" in text
    assert "test_mcp_default_recall_surfaces_recent_delta_freshness_telemetry" in text
    assert "test_raw_gateway_recent_delta_new_session_platform_needs_only_declaration" in text
    assert '["bash", "-n", "install.sh"]' in text
    assert '["bash", "-n", "Time Library Installer.command"]' in text
    assert '["bash", "-n", "tools/macos_full_install.sh"]' in text
    assert '["bash", "-n", "tools/linux_full_install.sh"]' in text
    assert "git diff" in text


def test_release_gate_default_pytest_suite_covers_release_risks():
    gate = _load_release_gate()
    args = tuple(gate.DEFAULT_RELEASE_PYTEST_ARGS)

    assert "tests/test_release_artifact.py" in args
    assert "tests/test_release_gate.py" in args
    assert "tests/test_public_experience_wording.py" in args
    assert "tests/test_console_product_boundary.py" in args
    assert "tests/test_zhiyi_skill_package.py" in args
    assert "tests/test_security_boundaries.py" in args
    assert "tests/test_hermes_autonomous_loop.py" in args
    assert any("test_raw_gateway_default_recall_uses_saved_bge_preference" in item for item in args)
    assert any("test_mcp_default_recall_surfaces_recent_delta_freshness_telemetry" in item for item in args)
    assert any("test_raw_gateway_recent_delta_new_session_platform_needs_only_declaration" in item for item in args)
    assert args[-1] == "-q"


def test_release_gate_rejects_private_top_level_agent_rules(tmp_path):
    gate = _load_release_gate()
    (tmp_path / "AGENTS.md").write_text("private local agent rules", encoding="utf-8")

    try:
        gate.assert_no_private_top_level_files(tmp_path)
    except SystemExit as exc:
        assert "AGENTS.md" in str(exc)
    else:
        raise AssertionError("release gate allowed private AGENTS.md in public source")


def test_release_gate_rejects_private_construction_docs(tmp_path):
    gate = _load_release_gate()
    path = tmp_path / "docs" / "decisions"
    path.mkdir(parents=True)
    (path / "local-plan.md").write_text("private local decision", encoding="utf-8")

    try:
        gate.assert_no_private_release_prefixes(tmp_path)
    except SystemExit as exc:
        assert "docs/decisions/" in str(exc)
    else:
        raise AssertionError("release gate allowed private construction docs in public source")


def test_release_gate_rejects_personal_identity_terms(tmp_path):
    gate = _load_release_gate()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "public.md").write_text("path=/Users/" + "yang" + "haibin" + "/Downloads", encoding="utf-8")

    try:
        gate.assert_no_personal_identity_terms(tmp_path)
    except SystemExit as exc:
        assert "personal identity" in str(exc)
    else:
        raise AssertionError("release gate allowed a personal identity term in public source")


def test_release_gate_rejects_public_eval_payload(tmp_path):
    gate = _load_release_gate()
    path = tmp_path / "src" / "official_memory_benchmarks.py"
    path.parent.mkdir()
    path.write_text("# internal eval", encoding="utf-8")

    try:
        gate.assert_no_public_eval_payload(tmp_path)
    except SystemExit as exc:
        assert "official_memory_benchmarks" in str(exc)
    else:
        raise AssertionError("release gate allowed eval source in public payload")


def test_release_gate_rejects_product_src_importing_eval(tmp_path):
    gate = _load_release_gate()
    path = tmp_path / "src" / "preflight_doctor.py"
    path.parent.mkdir()
    path.write_text("from src.official_memory_benchmarks import official_sources\n", encoding="utf-8")

    try:
        gate.assert_product_src_does_not_import_eval(tmp_path)
    except SystemExit as exc:
        assert "official_memory_benchmarks" in str(exc)
    else:
        raise AssertionError("release gate allowed product src to import eval modules")


def test_release_gate_rejects_runtime_version_hardcoding(tmp_path):
    gate = _load_release_gate()
    root = tmp_path
    (root / "VERSION").write_text("2099.7.8\n", encoding="utf-8")
    src_dir = root / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "memcore_version.py").write_text(
        "\n".join([
            "from pathlib import Path",
            "def read_memcore_version(root=None, default='unknown'):",
            "    return (Path(root) / 'VERSION').read_text(encoding='utf-8').strip()",
            "SERVICE_VERSION = read_memcore_version(Path(__file__).resolve().parents[1])",
            "",
        ]),
        encoding="utf-8",
    )
    (root / "web").mkdir()
    (root / "web" / "console_product.html").write_text(
        '<span id="sidebar-version">2026.6.20</span>',
        encoding="utf-8",
    )

    try:
        gate.assert_runtime_version_uses_version_file(root, Path(sys.executable))
    except SystemExit as exc:
        assert "web/console_product.html" in str(exc)
    else:
        raise AssertionError("release gate allowed runtime version hardcoding")


def test_release_gate_includes_dialog_entry_install_safety_checks():
    text = RELEASE_GATE.read_text(encoding="utf-8")

    assert "tools/macos_full_install.sh" in text
    assert "tools/linux_full_install.sh" in text
