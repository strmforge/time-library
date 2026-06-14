#!/usr/bin/env python3
"""Run a clean local release gate for Memcore Cloud.

The default mode tests a clean archive of HEAD so local uncommitted files,
runtime state, and machine-specific memory do not affect the result. Use
`--source working-tree` only when intentionally checking pending local edits
before committing them.
"""

from __future__ import annotations

import argparse
import json
import os
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
    "raw.githubusercontent.com/strmforge/memcore-cloud/main/install",
    "archive/refs/heads/main.zip",
    "memcore-cloud-main.zip",
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
PUBLIC_SURFACE_PATHS = (
    "README.md",
    "README.en.md",
    "README.zh-CN.md",
    "RELEASE_NOTES_2026.6.14.md",
    "UPDATE_HISTORY.md",
    "CHANGELOG.md",
    "docs",
    "Memcore Cloud Installer.command",
    "Memcore Cloud Installer.cmd",
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
    "RELEASE_NOTES_2026.6.14.md",
    "config",
    "docs",
    "install.sh",
    "install.ps1",
    "Memcore Cloud Installer.command",
    "Memcore Cloud Installer.cmd",
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
    ignore = shutil.ignore_patterns(
        ".git",
        ".venv",
        ".pytest_cache",
        "__pycache__",
        "memory",
        "logs",
        "backups",
        "output",
        "update_staging",
        *PRIVATE_TOP_LEVEL_FILES,
    )
    shutil.copytree(ROOT, source, ignore=ignore)


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
    pytest_args = list(args) or ["-q"]
    run([str(python), "-m", "pytest", *pytest_args], cwd=source)


def run_shell_checks(source: Path) -> None:
    run(["bash", "-n", "install.sh"], cwd=source)
    run(["bash", "-n", "Memcore Cloud Installer.command"], cwd=source)
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
    parser = argparse.ArgumentParser(description="Run clean Memcore Cloud release checks.")
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
        assert_no_public_forbidden_terms(source)
        run_repository_wording_scan(source)
        run_shell_checks(source)
        run_git_checks(source)

        python = Path(sys.executable) if args.no_venv else make_venv(source)
        if not args.no_venv:
            install_requirements(python, source)
        run_py_compile(python, source)
        run_internal_direction_audit(python, source)
        run_core_record_reliability_contract(python, source)
        if not args.skip_pytest:
            run_pytest(python, source, args.pytest_args or ["-q"])

        print("[release-gate] PASS", flush=True)
        return 0
    finally:
        if args.keep:
            print(f"[release-gate] kept temp dir: {tmp}", flush=True)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
