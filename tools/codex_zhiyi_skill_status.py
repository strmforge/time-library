#!/usr/bin/env python3
"""Read-only Codex Zhiyi skill/MCP activation diagnostic."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


SENSITIVE_KEY_RE = re.compile(r"(key|token|secret|password|auth|credential|cookie)", re.I)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except Exception:
        return ""


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): ("[redacted]" if SENSITIVE_KEY_RE.search(str(key)) else _redact(child))
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    result: dict[str, str] = {}
    for raw_line in text[3:end].splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _skill_dir_status(skill_dir: Path) -> dict[str, Any]:
    skill_file = skill_dir / "SKILL.md"
    text = _read_text(skill_file)
    meta = _frontmatter(text)
    description = meta.get("description", "")
    return {
        "path": str(skill_dir),
        "dirname": skill_dir.name,
        "has_skill_md": skill_file.is_file(),
        "name": meta.get("name", ""),
        "version": meta.get("version", ""),
        "prompt_version": meta.get("prompt_version", ""),
        "is_backup_dir": ".backup" in skill_dir.name or skill_dir.name.endswith(".bak"),
        "description_starts_use_when": description.lower().startswith("use when"),
        "description_mentions_zhiyi_recall": "zhiyi_recall" in description,
        "description_mentions_already_built": "already-built" in description or "already built" in description,
    }


def _parse_toml(path: Path) -> dict[str, Any] | None:
    try:
        import tomllib
    except Exception:
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _codex_mcp_status(codex_home: Path) -> dict[str, Any]:
    config_path = codex_home / "config.toml"
    text = _read_text(config_path)
    data = _parse_toml(config_path)
    server: dict[str, Any] = {}
    if isinstance(data, dict):
        mcp_servers = data.get("mcp_servers") if isinstance(data.get("mcp_servers"), dict) else {}
        raw_server = mcp_servers.get("yifanchen-zhiyi") if isinstance(mcp_servers, dict) else None
        if isinstance(raw_server, dict):
            server = raw_server
    present = bool(server) or "[mcp_servers.yifanchen-zhiyi]" in text
    return {
        "config_path": str(config_path),
        "config_exists": config_path.is_file(),
        "mcp_present": present,
        "uses_codex_mcp_bridge": "codex_mcp_bridge.py" in text,
        "endpoint_9851_present": "127.0.0.1:9851" in text,
        "server_redacted": _redact(server),
    }


def build_status(*, codex_home: Path, repo_root: Path | None = None) -> dict[str, Any]:
    skills_root = codex_home / "skills"
    skill_dirs = []
    if skills_root.is_dir():
        try:
            candidates = sorted(path for path in skills_root.iterdir() if path.is_dir() and path.name.startswith("yifanchen-zhiyi"))
        except OSError:
            candidates = []
        skill_dirs = [_skill_dir_status(path) for path in candidates]

    matching = [item for item in skill_dirs if item.get("name") == "yifanchen-zhiyi"]
    backups = [item for item in matching if item.get("is_backup_dir")]
    main = [item for item in matching if not item.get("is_backup_dir") and item.get("dirname") == "yifanchen-zhiyi"]

    repo_skill: dict[str, Any] | None = None
    if repo_root:
        repo_path = repo_root / "system" / "skills" / "yifanchen-zhiyi"
        if repo_path.exists():
            repo_skill = _skill_dir_status(repo_path)

    active_main_version = main[0].get("version", "") if main else ""
    repo_version = repo_skill.get("version", "") if repo_skill else ""
    issues: list[str] = []
    if not main:
        issues.append("main_skill_missing")
    if backups:
        issues.append("backup_skill_dirs_in_active_root")
    if len(matching) > 1:
        issues.append("duplicate_same_name_skills")
    if main and not main[0].get("description_starts_use_when"):
        issues.append("main_description_not_use_when")
    if repo_version and active_main_version and repo_version != active_main_version:
        issues.append("active_skill_version_drift")

    mcp = _codex_mcp_status(codex_home)
    if not mcp.get("mcp_present"):
        issues.append("codex_mcp_missing")

    return {
        "tool": "codex_zhiyi_skill_status",
        "read_only": True,
        "codex_home": str(codex_home),
        "skills_root": str(skills_root),
        "skill_dirs": skill_dirs,
        "matching_skill_count": len(matching),
        "backup_skill_count": len(backups),
        "main_skill": main[0] if main else None,
        "repo_skill": repo_skill,
        "mcp": mcp,
        "issues": issues,
        "ok": not issues,
        "recommendation": _recommendation(issues),
    }


def _recommendation(issues: list[str]) -> str:
    if not issues:
        return "Codex has one active Zhiyi skill and the yifanchen-zhiyi MCP entry is present."
    if "backup_skill_dirs_in_active_root" in issues or "duplicate_same_name_skills" in issues:
        return "Move yifanchen-zhiyi.backup* directories out of the active Codex skills root, then reinstall the main skill."
    if "active_skill_version_drift" in issues:
        return "Reinstall the Codex skill from system/skills/yifanchen-zhiyi."
    if "codex_mcp_missing" in issues:
        return "Register the yifanchen-zhiyi MCP server in Codex config."
    return "Reinstall the Codex skill and run this diagnostic again."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME") or str(Path.home() / ".codex"))
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args(argv)
    payload = build_status(codex_home=Path(args.codex_home).expanduser(), repo_root=Path(args.repo_root).expanduser())
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
