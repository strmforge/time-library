#!/usr/bin/env python3
"""Read-only Tiandao source inlet for repository code changes.

Code changes are source evidence for maintainer work. This module describes
their source refs and reproducible git commands, but it does not write raw
records, Zhiyi, Xingce, Toolbook entries, platform config, or release state.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tiandao.memory_routing import (
        TIANDAO_TIME_ORIGIN_CONTRACT,
        TIANDAO_TIME_RIVER_CONTRACT,
    )
except ImportError:  # pragma: no cover
    from src.tiandao.memory_routing import (
        TIANDAO_TIME_ORIGIN_CONTRACT,
        TIANDAO_TIME_RIVER_CONTRACT,
    )


CODE_CHANGE_TIANDAO_SOURCE_CONTRACT = "tiandao_code_change_source_inlet.v1"
SOURCE_REFS_ONLY_UNTIL_RAW_ORIGIN = "source_refs_only_until_raw_origin"
COMPLETE_SOURCE_REFS_REQUIRED = "complete_source_refs_required"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )


def _git_text(repo_root: Path, args: list[str]) -> str:
    proc = _run_git(repo_root, args)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _repo_head(repo_root: Path) -> dict[str, Any]:
    return {
        "branch": _git_text(repo_root, ["branch", "--show-current"]),
        "head": _git_text(repo_root, ["rev-parse", "--verify", "HEAD"]),
        "top_level": _git_text(repo_root, ["rev-parse", "--show-toplevel"]),
    }


def _parse_porcelain_z(output: str) -> list[dict[str, str]]:
    parts = output.split("\0")
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(parts):
        item = parts[index]
        index += 1
        if not item:
            continue
        status = item[:2]
        path = item[2:].lstrip(" ")
        old_path = ""
        if status.startswith("R") or status.startswith("C"):
            if index < len(parts):
                old_path = parts[index]
                index += 1
        entries.append({
            "status": status,
            "path": path,
            "old_path": old_path,
        })
    return entries


def _file_hash(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return ""


def _diff_hash(repo_root: Path, rel_path: str) -> str:
    proc = _run_git(repo_root, ["diff", "--", rel_path])
    if proc.returncode != 0 or not proc.stdout:
        proc = _run_git(repo_root, ["diff", "--cached", "--", rel_path])
    if proc.returncode != 0 or not proc.stdout:
        return ""
    return hashlib.sha256(proc.stdout.encode("utf-8", errors="replace")).hexdigest()


def _as_path_list(values: list[str | Path] | None) -> list[Path]:
    return [Path(value).expanduser() for value in (values or [])]


def _source_ref_for_entry(repo_root: Path, entry: dict[str, str]) -> dict[str, Any]:
    rel_path = _safe_str(entry.get("path"))
    abs_path = repo_root / rel_path if rel_path else repo_root
    exists = abs_path.exists()
    try:
        stat = abs_path.stat() if exists and abs_path.is_file() else None
    except OSError:
        stat = None
    status = _safe_str(entry.get("status"))
    untracked = "?" in status
    return {
        "source_system": "git_worktree",
        "artifact_type": "code_change",
        "repo_root": str(repo_root),
        "source_path": rel_path,
        "old_source_path": _safe_str(entry.get("old_path")),
        "git_status": status,
        "source_exists": exists,
        "tracked_state": "untracked" if untracked else "tracked_or_indexed",
        "size_bytes": int(stat.st_size) if stat else None,
        "content_sha256": _file_hash(abs_path) if stat else "",
        "diff_sha256": "" if untracked else _diff_hash(repo_root, rel_path),
        "reproduce_status_command": f"git status --short -- {json.dumps(rel_path, ensure_ascii=False)}",
        "reproduce_diff_command": f"git diff -- {json.dumps(rel_path, ensure_ascii=False)}",
    }


def _verification_source_ref(
    *,
    repo_root: Path,
    index: int,
    output_path: Path | None,
    command: str,
) -> dict[str, Any]:
    abs_path = None
    rel_path = ""
    if output_path is not None:
        abs_path = output_path if output_path.is_absolute() else repo_root / output_path
        try:
            rel_path = str(abs_path.resolve().relative_to(repo_root))
        except ValueError:
            rel_path = str(abs_path)
    exists = bool(abs_path and abs_path.exists())
    try:
        stat = abs_path.stat() if abs_path and exists and abs_path.is_file() else None
    except OSError:
        stat = None
    return {
        "source_system": "maintainer_command",
        "artifact_type": "code_change_verification_output",
        "repo_root": str(repo_root),
        "source_path": rel_path,
        "verification_index": index,
        "verification_command": command.strip(),
        "source_exists": exists,
        "size_bytes": int(stat.st_size) if stat else None,
        "content_sha256": _file_hash(abs_path) if stat and abs_path else "",
        "reproduce_command": command.strip(),
        "evidence_status": "output_artifact_available" if stat else "declared_without_output_artifact",
    }


def _stable_source_package_id(repo_root: Path, head: str, refs: list[dict[str, Any]]) -> str:
    basis = _stable_json({
        "repo_root": str(repo_root),
        "head": head,
        "refs": [
            {
                "source_path": item.get("source_path"),
                "git_status": item.get("git_status"),
                "content_sha256": item.get("content_sha256"),
                "diff_sha256": item.get("diff_sha256"),
            }
            for item in refs
        ],
    })
    return "code_change_source_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def build_code_change_tiandao_source_report(
    *,
    repo_root: str | Path,
    max_refs: int = 200,
    require_complete: bool = False,
    verification_outputs: list[str | Path] | None = None,
    verification_commands: list[str] | None = None,
) -> dict[str, Any]:
    """Build a read-only source package for current git worktree changes."""

    root = Path(repo_root).expanduser().resolve()
    output_paths = _as_path_list(verification_outputs)
    commands = [str(command or "").strip() for command in (verification_commands or [])]
    verification_count = max(len(output_paths), len(commands))
    verification_source_refs = [
        _verification_source_ref(
            repo_root=root,
            index=index,
            output_path=output_paths[index] if index < len(output_paths) else None,
            command=commands[index] if index < len(commands) else "",
        )
        for index in range(verification_count)
    ]
    git_check = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if git_check.returncode != 0:
        return {
            "ok": True,
            "contract": CODE_CHANGE_TIANDAO_SOURCE_CONTRACT,
            "repo_context_available": False,
            "status": "not_a_git_worktree",
            "repo_root": str(root),
            "source_system": "git_worktree",
            "source_kind": "repository_code_change",
            "dirty": False,
            "changed_file_count": 0,
            "source_ref_count": 0,
            "source_refs": [],
            "verification_source_refs": verification_source_refs,
            "verification_source_ref_count": len(verification_source_refs),
            "verification_output_ref_count": sum(1 for item in verification_source_refs if item.get("source_exists")),
            "source_refs_available": False,
            "source_evidence_kinds": ["verification_output"] if verification_source_refs else [],
            "test_output_evidence_status": "source_refs_only" if verification_source_refs else "not_supplied",
            "tiandao_ingest_status": "repo_context_unavailable",
            "origin_event_available": False,
            "origin_seen": False,
            "candidate_until_raw_origin_linked": True,
            "code_change_policy": "code_changes_are_source_evidence_not_memory_sediment",
            "adoption_policy": "do_not_auto_adopt_code_changes_into_zhiyi_xingce_or_toolbook",
            "raw_authority_policy": "git_diff_commit_test_output_are_source_evidence",
            "read_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "limitations": [
                "repo_context_unavailable_without_git_metadata",
                "release_archives_may_not_include_dot_git",
                "not_a_zhiyi_xingce_or_toolbook_adoption",
                "not_a_release_claim",
            ],
        }

    head = _repo_head(root)
    status_output = _git_text(root, ["status", "--porcelain=v1", "-z"])
    entries = _parse_porcelain_z(status_output)
    effective_max_refs = len(entries) if max_refs <= 0 else max_refs
    source_refs = [_source_ref_for_entry(root, entry) for entry in entries[:effective_max_refs]]
    truncated = len(entries) > len(source_refs)
    package_id = _stable_source_package_id(root, _safe_str(head.get("head")), [*source_refs, *verification_source_refs])
    dirty = bool(entries)
    complete_source_refs = not truncated
    return {
        "ok": not (require_complete and truncated),
        "contract": CODE_CHANGE_TIANDAO_SOURCE_CONTRACT,
        "parent_tiandao_contract": TIANDAO_TIME_RIVER_CONTRACT,
        "time_origin_contract": TIANDAO_TIME_ORIGIN_CONTRACT,
        "time_river_contract": TIANDAO_TIME_RIVER_CONTRACT,
        "source_package_id": package_id,
        "source_system": "git_worktree",
        "source_kind": "repository_code_change",
        "repo_context_available": True,
        "repo_root": str(root),
        "git": head,
        "dirty": dirty,
        "changed_file_count": len(entries),
        "source_ref_count": len(source_refs),
        "total_source_ref_count": len(source_refs) + len(verification_source_refs),
        "source_refs": source_refs,
        "verification_source_refs": verification_source_refs,
        "verification_source_ref_count": len(verification_source_refs),
        "verification_output_ref_count": sum(1 for item in verification_source_refs if item.get("source_exists")),
        "source_refs_truncated": truncated,
        "complete_source_refs": complete_source_refs,
        "complete_source_refs_required": require_complete,
        "source_refs_available": bool(source_refs),
        "source_evidence_kinds": [
            "git_status",
            "git_diff",
            "file_hash",
            *(["verification_output"] if verification_source_refs else []),
        ],
        "test_output_evidence_status": "source_refs_only" if verification_source_refs else "not_supplied",
        "tiandao_ingest_status": COMPLETE_SOURCE_REFS_REQUIRED if require_complete and truncated else SOURCE_REFS_ONLY_UNTIL_RAW_ORIGIN,
        "origin_event_available": False,
        "origin_seen": False,
        "candidate_until_raw_origin_linked": True,
        "code_change_policy": "code_changes_are_source_evidence_not_memory_sediment",
        "adoption_policy": "do_not_auto_adopt_code_changes_into_zhiyi_xingce_or_toolbook",
        "raw_authority_policy": "git_diff_commit_test_output_are_source_evidence",
        "reproduce_status_command": "git status --short",
        "reproduce_diff_command": "git diff",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "generated_at": ts(),
        "limitations": [
            "this_report_does_not_persist_a_raw_artifact",
            "source_refs_only_until_raw_origin",
            *(
                []
                if verification_source_refs
                else ["verification_or_test_output_artifacts_not_supplied"]
            ),
            "not_a_zhiyi_xingce_or_toolbook_adoption",
            "not_a_release_claim",
            *(
                ["source_refs_truncated_but_complete_source_refs_required"]
                if require_complete and truncated
                else []
            ),
        ],
    }


def render_code_change_tiandao_source_markdown(report: dict[str, Any]) -> str:
    status = "PASS" if report.get("ok") else "ATTENTION"
    lines = [
        "# Code Change Tiandao Source Inlet",
        "",
        f"- Contract: `{report.get('contract')}`",
        f"- Status: `{status}`",
        f"- Repository: `{report.get('repo_root', '')}`",
        f"- Read-only: `{report.get('read_only')}`",
        f"- Changed files: `{report.get('changed_file_count', 0)}`",
        f"- Verification refs: `{report.get('verification_source_ref_count', 0)}`",
        f"- Tiandao ingest status: `{report.get('tiandao_ingest_status', '')}`",
        f"- Policy: `{report.get('code_change_policy', '')}`",
        f"- Adoption: `{report.get('adoption_policy', '')}`",
        "",
        "## Source Refs",
        "",
    ]
    for item in report.get("source_refs") or []:
        if not isinstance(item, dict):
            continue
        lines.extend([
            f"- `{item.get('git_status', '')}` `{item.get('source_path', '')}`",
            f"  - content_sha256: `{item.get('content_sha256', '')}`",
            f"  - diff_sha256: `{item.get('diff_sha256', '')}`",
        ])
    if not report.get("source_refs"):
        lines.append("- No current working-tree code changes.")
    if report.get("verification_source_refs"):
        lines.extend(["", "## Verification Source Refs", ""])
    for item in report.get("verification_source_refs") or []:
        if not isinstance(item, dict):
            continue
        lines.extend([
            f"- `{item.get('source_path', '')}`",
            f"  - command: `{item.get('verification_command', '')}`",
            f"  - content_sha256: `{item.get('content_sha256', '')}`",
            f"  - evidence_status: `{item.get('evidence_status', '')}`",
        ])
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "CODE_CHANGE_TIANDAO_SOURCE_CONTRACT",
    "COMPLETE_SOURCE_REFS_REQUIRED",
    "SOURCE_REFS_ONLY_UNTIL_RAW_ORIGIN",
    "build_code_change_tiandao_source_report",
    "render_code_change_tiandao_source_markdown",
]
