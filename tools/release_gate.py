#!/usr/bin/env python3
"""Run a clean local release gate for Time Library.

The default mode tests a clean archive of HEAD so local uncommitted files,
runtime state, and machine-specific memory do not affect the result. Use
`--source working-tree` only when intentionally checking pending local edits
before committing them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]


def _term(*parts: str) -> str:
    return "".join(parts)


PUBLIC_FORBIDDEN_TERMS = (
    _term("CC", " Switch"),
    _term("cc", "switch"),
    _term("cc", "-switch"),
    _term("CC", "_SWITCH"),
    _term("com.", "cc", "switch"),
    "raw.githubusercontent.com/strmforge/time-library/main/install",
    "archive/refs/heads/main.zip",
    "time-library-main.zip",
    "| bash",
    "| iex",
    "can_auto_connect_without_authorization",
    "can_write_platform_config_without_authorization",
    "can_parse_chat_bodies_without_authorization",
    _term("capability", " matrix"),
    _term("能力", "矩阵"),
    _term("hooks", " / MCP / REST"),
    _term("AGENTS", ".md"),
    _term("旧的", "游离记录"),
)
REPOSITORY_FORBIDDEN_TERMS = (
    *PUBLIC_FORBIDDEN_TERMS[:5],
    _term("Or", "phan:"),
    _term("or", "phan"),
    _term("or", "phan source"),
    _term("or", "phan raw"),
)
PUBLIC_DOCS = (
    "README.md",
    "README.en.md",
    "README.zh-CN.md",
    "docs/wiki/Getting-Started.md",
)
FORBIDDEN_PUBLIC_EVAL_PATHS = (
    "benchmarks/README.md",
    "src/codex_memory_judge.py",
    "src/eval_entrypoints.py",
    "src/eval_miss_report.py",
    "src/eval_resource_ledger.py",
    "src/free_memory_benchmark.py",
    "src/model_matrix_compare.py",
    "src/model_memory_judge.py",
    "src/official_memory_benchmarks.py",
    "tools/codex_memory_judge.py",
    "tools/eval_miss_report.py",
    "tools/eval_run_compare.py",
    "tools/free_memory_benchmark.py",
    "tools/memcore_eval_entry.py",
    "tools/model_heavy_qa_runner.py",
    "tools/model_matrix_compare.py",
    "tools/model_matrix_eval.py",
    "tools/model_memory_judge.py",
    "tools/official_memory_benchmark.py",
    "tools/r730_eval_stage_sync.sh",
)
FORBIDDEN_PRODUCT_IMPORT_MODULES = (
    "benchmarks",
    "codex_memory_judge",
    "eval_entrypoints",
    "eval_miss_report",
    "eval_resource_ledger",
    "free_memory_benchmark",
    "model_matrix_compare",
    "model_memory_judge",
    "official_memory_benchmarks",
)
RUNTIME_VERSION_SURFACE_PATHS = (
    "src/active_memory_routing.py",
    "src/agent_work_preflight.py",
    "src/p6_console.py",
    "src/p6_console_ui.py",
    "src/platform_native_entrypoints.py",
    "src/productized_loops.py",
    "src/raw_consumption_gateway.py",
    "src/update_source.py",
    "src/zhixing_library_dashboard.py",
    "src/zhixing_preflight.py",
    "web/console_product.html",
)
DEFAULT_RELEASE_PYTEST_ARGS = (
    "tests/test_release_artifact.py",
    "tests/test_release_gate.py",
    "tests/test_public_experience_wording.py",
    "tests/test_console_product_boundary.py",
    "tests/test_zhiyi_skill_package.py",
    "tests/test_security_boundaries.py",
    "tests/test_hermes_autonomous_loop.py",
    "tests/test_shared_memory_consumption.py::test_raw_gateway_default_recall_uses_saved_bge_preference",
    "tests/test_shared_memory_consumption.py::test_raw_gateway_explicit_recall_mode_overrides_saved_bge_preference",
    "tests/test_shared_memory_consumption.py::test_raw_gateway_unconfigured_bge_preference_uses_ui_default_fts5_recall",
    "tests/test_shared_memory_consumption.py::test_mcp_default_recall_surfaces_recent_delta_freshness_telemetry",
    "tests/test_shared_memory_consumption.py::test_raw_gateway_default_recall_hits_gateway_recent_delta_without_p3",
    "tests/test_shared_memory_consumption.py::test_raw_gateway_recent_delta_new_session_platform_needs_only_declaration",
    "-q",
)
PUBLIC_SURFACE_PATHS = (
    "README.md",
    "README.en.md",
    "README.zh-CN.md",
    "RELEASE_NOTES_2026.7.7.md",
    "UPDATE_HISTORY.md",
    "CHANGELOG.md",
    "docs",
    "Time Library Installer.command",
    "Time Library Installer.cmd",
    "install.sh",
    "install.ps1",
    "uninstall.sh",
    "uninstall.ps1",
    "tools/linux_full_install.sh",
    "tools/macos_full_install.sh",
    "tools/windows_full_install.ps1",
    "tools/windows_guardian.ps1",
    "tools/windows_native_smoke.ps1",
)
REPOSITORY_WORDING_PATHS = (
    "README.md",
    "README.en.md",
    "README.zh-CN.md",
    "INTRODUCTION.md",
    "CHANGELOG.md",
    "UPDATE_HISTORY.md",
    "RELEASE_NOTES_2026.7.7.md",
    "config",
    "docs",
    "install.sh",
    "install.ps1",
    "Time Library Installer.command",
    "Time Library Installer.cmd",
    "uninstall.sh",
    "uninstall.ps1",
    "src",
    "system",
    "tests",
    "tools",
    "web",
)
PRIVATE_TOP_LEVEL_FILES = (
    "AGENTS.md",
    "CODEX_CONTINUITY_LEDGER.md",
    "design-qa.md",
    "known-issues.md",
)
PRIVATE_RELEASE_PREFIXES = (
    "docs/construction/",
    "docs/decisions/",
)
PERSONAL_IDENTITY_TERMS = (
    _term("yang", "haibin"),
    _term("/Users/", "yang", "haibin"),
    _term("yang", "haibinde"),
)


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"[release-gate] $ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def capture(cmd: list[str], *, cwd: Path) -> str:
    return subprocess.check_output(cmd, cwd=str(cwd), text=True).strip()


def export_head(target: Path) -> None:
    archive = target / "source.tar"
    run(["git", "archive", "--format=tar", "-o", str(archive), "HEAD"], cwd=ROOT)
    source = target / "source"
    source.mkdir()
    run(["tar", "-xf", str(archive), "-C", str(source)], cwd=ROOT)


def copy_working_tree(target: Path) -> None:
    source = target / "source"
    source.mkdir()
    files = capture(["git", "ls-files", "--cached", "--modified", "--others", "--exclude-standard"], cwd=ROOT)
    for line in files.splitlines():
        rel = line.strip()
        if not rel:
            continue
        src = ROOT / rel
        if not src.is_file():
            continue
        if rel in PRIVATE_TOP_LEVEL_FILES:
            continue
        if any(rel.startswith(prefix) for prefix in PRIVATE_RELEASE_PREFIXES):
            continue
        dst = source / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def python_files(source: Path) -> list[str]:
    roots = ["src", "tools", "tests"]
    files: list[str] = []
    for root in roots:
        base = source / root
        if not base.exists():
            continue
        files.extend(str(path.relative_to(source)) for path in base.rglob("*.py"))
    return sorted(files)


def assert_no_public_forbidden_terms(source: Path) -> None:
    checked: list[Path] = []
    for rel in PUBLIC_SURFACE_PATHS:
        path = source / rel
        if path.is_file():
            checked.append(path)
        elif path.is_dir():
            checked.extend(child for child in path.rglob("*") if child.is_file())
    findings: list[dict[str, str]] = []
    for path in checked:
        text = path.read_text(encoding="utf-8", errors="replace")
        for term in PUBLIC_FORBIDDEN_TERMS:
            if term in text:
                findings.append({"path": str(path.relative_to(source)), "term": term})
    if findings:
        print(json.dumps({"forbidden_public_terms": findings}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)


def assert_no_private_top_level_files(source: Path) -> None:
    findings = [name for name in PRIVATE_TOP_LEVEL_FILES if (source / name).exists()]
    if findings:
        raise SystemExit("private top-level files are not allowed in public release source: " + ", ".join(findings))


def assert_no_private_release_prefixes(source: Path) -> None:
    findings: list[str] = []
    for prefix in PRIVATE_RELEASE_PREFIXES:
        path = source / prefix
        if path.exists():
            findings.append(prefix)
    if findings:
        raise SystemExit("private construction/decision docs are not allowed in public release source: " + ", ".join(findings))


def assert_no_public_eval_payload(source: Path) -> None:
    findings = [rel for rel in FORBIDDEN_PUBLIC_EVAL_PATHS if (source / rel).exists()]
    if findings:
        raise SystemExit("eval diagnostic files are not allowed in public product release source: " + ", ".join(findings))


def assert_product_src_does_not_import_eval(source: Path) -> None:
    tree = None
    import ast

    findings: list[str] = []
    src_dir = source / "src"
    if not src_dir.exists():
        return
    forbidden = set(FORBIDDEN_PRODUCT_IMPORT_MODULES)
    for path in sorted(src_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            raise SystemExit(f"failed to parse {path.relative_to(source)}: {exc}") from exc
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = str(alias.name or "").split(".", 1)[0]
                    if module in forbidden:
                        findings.append(f"{path.relative_to(source)} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module_name = str(node.module or "")
                parts = [part for part in module_name.split(".") if part]
                if parts[:1] == ["src"] and len(parts) > 1:
                    module = parts[1]
                elif parts:
                    module = parts[0]
                if module in forbidden:
                    findings.append(f"{path.relative_to(source)} imports {module_name}")
    if findings:
        raise SystemExit("product src must not import eval/benchmark modules:\n" + "\n".join(findings[:80]))


def assert_runtime_version_uses_version_file(source: Path, python: Path) -> None:
    expected = (source / "VERSION").read_text(encoding="utf-8-sig").strip()
    if not expected:
        raise SystemExit("VERSION file is empty")
    script = (
        "from src.memcore_version import read_memcore_version, SERVICE_VERSION; "
        "import pathlib; "
        f"root = pathlib.Path({str(source)!r}); "
        "assert read_memcore_version(root) == "
        f"{expected!r}, read_memcore_version(root); "
        "assert SERVICE_VERSION == "
        f"{expected!r}, SERVICE_VERSION"
    )
    run([str(python), "-c", script], cwd=source, env={**os.environ, "MEMCORE_ROOT": str(source)})
    version_pattern = re.compile(r"\b20\d{2}\.\d{1,2}\.\d{1,2}(?:\.\d+)?\b")
    runtime_version_literal_patterns = (
        re.compile(r"\b[A-Z_]*VERSION\b\s*=\s*.*['\"]20\d{2}\."),
        re.compile(r"['\"]version['\"]\s*:\s*['\"]20\d{2}\."),
        re.compile(r"body\.get\(\s*['\"]version['\"]\s*,\s*['\"]20\d{2}\."),
        re.compile(r"serverInfo.*['\"]version['\"].*20\d{2}\."),
        re.compile(r"(sidebar-version|about-version|settings\.version).*20\d{2}\."),
        re.compile(r"textContent\s*=.*20\d{2}\."),
        re.compile(r"<td>20\d{2}\."),
        re.compile(r"\|\|\s*['\"]20\d{2}\."),
    )
    violations: list[str] = []
    for rel in RUNTIME_VERSION_SURFACE_PATHS:
        path = source / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not version_pattern.search(line):
                continue
            if ".v2026.6.20" in line or "v2026.6.20" in line:
                continue
            if not any(pattern.search(line) for pattern in runtime_version_literal_patterns):
                continue
            violations.append(f"{rel}:{line_no}: {line.strip()}")
    if violations:
        raise SystemExit("runtime version surfaces must read VERSION instead of hard-coding old releases:\n" + "\n".join(violations[:80]))


def install_requirements(python: Path, source: Path) -> None:
    for req in ("requirements-core.txt", "requirements-dev.txt"):
        path = source / req
        if path.exists():
            run([str(python), "-m", "pip", "install", "-q", "-r", str(path)], cwd=source)


def make_venv(source: Path) -> Path:
    venv = source / ".release-gate-venv"
    run([sys.executable, "-m", "venv", str(venv)], cwd=source)
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def run_py_compile(python: Path, source: Path) -> None:
    files = python_files(source)
    if files:
        run([str(python), "-m", "py_compile", *files], cwd=source)


def run_pytest(python: Path, source: Path, args: Iterable[str]) -> None:
    pytest_args = list(args) or list(DEFAULT_RELEASE_PYTEST_ARGS)
    run([str(python), "-m", "pytest", *pytest_args], cwd=source)


def run_shell_checks(source: Path) -> None:
    run(["bash", "-n", "install.sh"], cwd=source)
    run(["bash", "-n", "Time Library Installer.command"], cwd=source)
    run(["bash", "-n", "tools/macos_full_install.sh"], cwd=source)
    run(["bash", "-n", "tools/linux_full_install.sh"], cwd=source)


def run_git_checks(source: Path) -> None:
    if (source / ".git").exists():
        run(["git", "diff", "--check"], cwd=source)
    else:
        print("[release-gate] skipping git diff --check for archive source", flush=True)


def iter_text_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            yield path
            continue
        for candidate in path.rglob("*"):
            if not candidate.is_file():
                continue
            if any(part in {".git", ".release-gate-venv", "__pycache__", ".pytest_cache"} for part in candidate.parts):
                continue
            if candidate.suffix.lower() in {
                ".bak",
                ".db",
                ".exe",
                ".jpg",
                ".jpeg",
                ".png",
                ".pyc",
                ".sqlite",
                ".zip",
            }:
                continue
            yield candidate


def run_repository_wording_scan(source: Path) -> None:
    violations: list[str] = []
    paths = [source / rel for rel in REPOSITORY_WORDING_PATHS]
    for path in iter_text_files(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            raise SystemExit(f"failed to scan wording in {path}: {exc}") from exc
        for term in REPOSITORY_FORBIDDEN_TERMS:
            if term in text:
                rel = path.relative_to(source)
                violations.append(f"{rel}: forbidden repository wording {term!r}")
    if violations:
        raise SystemExit("repository wording scan failed:\n" + "\n".join(violations[:80]))


def assert_no_personal_identity_terms(source: Path) -> None:
    scan_roots = [
        source / "README.md",
        source / "README.en.md",
        source / "README.zh-CN.md",
        source / "INTRODUCTION.md",
        source / "CHANGELOG.md",
        source / "UPDATE_HISTORY.md",
        source / "RELEASE_NOTES_2026.7.7.md",
        source / "config",
        source / "docs",
        source / "install.sh",
        source / "install.ps1",
        source / "Time Library Installer.command",
        source / "Time Library Installer.cmd",
        source / "uninstall.sh",
        source / "uninstall.ps1",
        source / "src",
        source / "system",
        source / "tests",
        source / "tools",
        source / "web",
    ]
    findings: list[str] = []
    for path in iter_text_files(scan_roots):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            raise SystemExit(f"failed to scan personal identity terms in {path}: {exc}") from exc
        for term in PERSONAL_IDENTITY_TERMS:
            if term in text:
                findings.append(f"{path.relative_to(source)}: personal identity term")
    if findings:
        raise SystemExit("personal identity terms are not allowed in public release source:\n" + "\n".join(findings[:80]))


def run_internal_direction_audit(python: Path, source: Path) -> None:
    audit = source / "tools" / "internal_direction_audit.py"
    if not audit.exists():
        raise SystemExit("internal direction audit script is missing")
    run([str(python), str(audit), "--format", "json"], cwd=source)


def run_core_record_reliability_contract(python: Path, source: Path) -> None:
    audit = source / "tools" / "core_record_reliability_audit.py"
    if not audit.exists():
        raise SystemExit("core record reliability audit script is missing")
    run([str(python), str(audit), "--format", "json", "--contract-only"], cwd=source)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run clean Time Library release checks.")
    parser.add_argument("--source", choices=("head", "working-tree"), default="head")
    parser.add_argument("--keep", action="store_true", help="keep the temporary source directory")
    parser.add_argument("--no-venv", action="store_true", help="use the current Python instead of creating a venv")
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--pytest-args", nargs=argparse.REMAINDER, default=None)
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="memcore-release-gate-"))
    try:
        if args.source == "head":
            export_head(tmp)
        else:
            copy_working_tree(tmp)
        source = tmp / "source"
        version = (source / "VERSION").read_text(encoding="utf-8").strip() if (source / "VERSION").exists() else ""
        print(f"[release-gate] source={args.source} version={version} root={source}", flush=True)

        assert_no_private_top_level_files(source)
        assert_no_private_release_prefixes(source)
        assert_no_public_eval_payload(source)
        assert_product_src_does_not_import_eval(source)
        assert_no_public_forbidden_terms(source)
        run_repository_wording_scan(source)
        assert_no_personal_identity_terms(source)
        run_shell_checks(source)
        run_git_checks(source)
        assert_runtime_version_uses_version_file(source, Path(sys.executable))

        python = Path(sys.executable) if args.no_venv else make_venv(source)
        if not args.no_venv:
            install_requirements(python, source)
        run_py_compile(python, source)
        run_internal_direction_audit(python, source)
        run_core_record_reliability_contract(python, source)
        if not args.skip_pytest:
            run_pytest(python, source, args.pytest_args or DEFAULT_RELEASE_PYTEST_ARGS)

        print("[release-gate] PASS", flush=True)
        return 0
    finally:
        if args.keep:
            print(f"[release-gate] kept temp dir: {tmp}", flush=True)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
