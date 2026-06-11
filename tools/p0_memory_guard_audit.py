#!/usr/bin/env python3
"""Read-only P0 memory guard audit for local AI client records.

This script prints a compact JSON report. It does not modify files, start
services, or require the memcore runtime to be active.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from pathlib import Path
from typing import Any


LEGACY_LOCAL_RELAY_TOKEN = "cc" + "switch"
LEGACY_LOCAL_RELAY_BUNDLE = "com." + LEGACY_LOCAL_RELAY_TOKEN + ".desktop"


def _home() -> Path:
    return Path.home()


def _win_env(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else fallback


def roots() -> dict[str, Path]:
    home = _home()
    system = platform.system().lower()
    if system == "windows":
        appdata = _win_env("APPDATA", home / "AppData" / "Roaming")
        localappdata = _win_env("LOCALAPPDATA", home / "AppData" / "Local")
        return {
            "codex_sessions": home / ".codex" / "sessions",
            "codex_home": home / ".codex",
            "claude_code_projects": home / ".claude" / "projects",
            "claude_desktop": appdata / "Claude",
            "claude_code_sessions": appdata / "Claude" / "claude-code-sessions",
            "local_relay": appdata / LEGACY_LOCAL_RELAY_BUNDLE,
            "memcore": localappdata / "memcore-cloud",
            "memcore_memory": localappdata / "memcore-cloud" / "memory",
            "kiro_roaming": appdata / "Kiro",
            "kiro_local": localappdata / "Kiro",
        }
    if system == "darwin":
        app_support = home / "Library" / "Application Support"
        return {
            "codex_sessions": home / ".codex" / "sessions",
            "codex_home": home / ".codex",
            "claude_code_projects": home / ".claude" / "projects",
            "claude_desktop": app_support / "Claude",
            "claude_code_sessions": app_support / "Claude" / "claude-code-sessions",
            "local_relay": app_support / LEGACY_LOCAL_RELAY_BUNDLE,
            "memcore": app_support / "memcore-cloud",
            "memcore_memory": app_support / "memcore-cloud" / "memory",
            "kiro_roaming": app_support / "Kiro",
            "kiro_local": app_support / "Kiro",
        }
    return {
        "codex_sessions": home / ".codex" / "sessions",
        "codex_home": home / ".codex",
        "claude_code_projects": home / ".claude" / "projects",
        "claude_desktop": home / ".config" / "Claude",
        "claude_code_sessions": home / ".config" / "Claude" / "claude-code-sessions",
        "local_relay": home / ".config" / LEGACY_LOCAL_RELAY_BUNDLE,
        "memcore": home / ".local" / "share" / "memcore-cloud",
        "memcore_memory": home / ".local" / "share" / "memcore-cloud" / "memory",
        "kiro_roaming": home / ".config" / "Kiro",
        "kiro_local": home / ".config" / "Kiro",
    }


def stat_path(path: Path) -> dict[str, Any]:
    exists = path.exists()
    result: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
    }
    if exists:
        try:
            st = path.stat()
            result.update(
                {
                    "is_dir": path.is_dir(),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "mtime_iso_local": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                }
            )
        except OSError as exc:
            result["stat_error"] = str(exc)
    return result


def iter_files(root: Path, suffixes: tuple[str, ...] | None = None, max_depth: int = 8) -> list[Path]:
    if not root.exists():
        return []
    found: list[Path] = []
    base_parts = len(root.parts)
    try:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if len(path.parts) - base_parts > max_depth:
                continue
            if suffixes and not path.name.lower().endswith(suffixes):
                continue
            found.append(path)
    except OSError:
        return found
    return found


def file_summary(paths: list[Path], limit: int = 12) -> dict[str, Any]:
    rows = []
    for path in paths:
        try:
            st = path.stat()
        except OSError:
            continue
        rows.append((st.st_mtime, st.st_size, path))
    rows.sort(reverse=True)
    return {
        "count": len(rows),
        "latest": [
            {
                "path": str(path),
                "size": size,
                "mtime": mtime,
                "mtime_iso_local": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
            }
            for mtime, size, path in rows[:limit]
        ],
    }


def text_role_probe(path: Path) -> dict[str, Any]:
    """Best-effort role probe for JSONL/text files without exposing contents."""
    probe = {
        "user_markers": 0,
        "assistant_markers": 0,
        "tool_markers": 0,
        "lines_sampled": 0,
    }
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for idx, line in enumerate(handle):
                if idx >= 500:
                    break
                lower = line.lower()
                if '"role":"user"' in lower or '"role": "user"' in lower or '"type":"user' in lower:
                    probe["user_markers"] += 1
                if (
                    '"role":"assistant"' in lower
                    or '"role": "assistant"' in lower
                    or '"type":"assistant' in lower
                    or '"type":"response_item"' in lower
                ):
                    probe["assistant_markers"] += 1
                if '"tool' in lower or "mcp__" in lower:
                    probe["tool_markers"] += 1
                probe["lines_sampled"] += 1
    except OSError as exc:
        probe["error"] = str(exc)
    return probe


def latest_role_probe(paths: list[Path]) -> dict[str, Any]:
    rows = []
    for path in paths:
        try:
            rows.append((path.stat().st_mtime, path))
        except OSError:
            continue
    rows.sort(reverse=True)
    if not rows:
        return {"available": False}
    latest = rows[0][1]
    return {"available": True, "path": str(latest), **text_role_probe(latest)}


def memcore_source_files(root: Path, source_system: str, suffixes: tuple[str, ...] = (".jsonl", ".json")) -> list[Path]:
    source = source_system.lower()
    files = []
    for path in iter_files(root, suffixes, max_depth=10):
        parts = {part.lower() for part in path.parts}
        if source in parts:
            files.append(path)
    return files


def build_report() -> dict[str, Any]:
    r = roots()
    codex_source = iter_files(r["codex_sessions"], (".jsonl",), max_depth=8)
    memcore_codex = memcore_source_files(r["memcore_memory"], "codex", (".jsonl",))
    claude_code_source = iter_files(r["claude_code_projects"], (".jsonl",), max_depth=8)
    claude_code_metadata = iter_files(r["claude_code_sessions"], (".json", ".jsonl"), max_depth=8)
    memcore_claude_cli = memcore_source_files(r["memcore_memory"], "claude_code_cli", (".jsonl",))
    claude_desktop_files = iter_files(
        r["claude_desktop"],
        (".log", ".ldb", ".json", ".sqlite", ".db"),
        max_depth=5,
    )
    memcore_claude_desktop = memcore_source_files(r["memcore_memory"], "claude_desktop")
    local_relay_files = iter_files(r["local_relay"], (".json", ".sqlite", ".db", ".log"), max_depth=8)
    kiro_files = iter_files(r["kiro_roaming"], (".json", ".jsonl", ".sqlite", ".db", ".log"), max_depth=8)
    kiro_files += iter_files(r["kiro_local"], (".json", ".jsonl", ".sqlite", ".db", ".log"), max_depth=8)
    memcore_kiro = memcore_source_files(r["memcore_memory"], "kiro")

    return {
        "audited_at_local": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "host": platform.node(),
        "system": platform.system(),
        "release": platform.release(),
        "roots": {name: stat_path(path) for name, path in r.items()},
        "sources": {
            "codex": {
                "source_jsonl": file_summary(codex_source),
                "memcore_jsonl": file_summary(memcore_codex),
                "source_role_probe": latest_role_probe(codex_source),
                "memcore_role_probe": latest_role_probe(memcore_codex),
            },
            "claude_code_cli": {
                "source_records": file_summary(claude_code_source),
                "desktop_metadata_records": file_summary(claude_code_metadata),
                "memcore_jsonl": file_summary(memcore_claude_cli),
                "source_role_probe": latest_role_probe(claude_code_source),
                "memcore_role_probe": latest_role_probe(memcore_claude_cli),
            },
            "claude_desktop": {
                "source_storage_candidates": file_summary(claude_desktop_files),
                "memcore_records": file_summary(memcore_claude_desktop),
                "coverage_note": "desktop_storage_candidates_only; raw body support requires connector-specific parser verification",
            },
            "local_relay": {
                "source_storage_candidates": file_summary(local_relay_files),
                "coverage_note": "candidate storage only; verify database schema before claiming capture",
            },
            "kiro": {
                "source_storage_candidates": file_summary(kiro_files),
                "memcore_records": file_summary(memcore_kiro),
                "coverage_note": "candidate storage only; verify whether assistant replies persist after window close",
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
