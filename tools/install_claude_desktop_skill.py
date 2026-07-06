#!/usr/bin/env python3
"""Install or update the Memcore Cloud skill inside Claude Desktop manifests.

Claude Desktop skills are managed under local-agent-mode-sessions/skills-plugin.
This helper only updates existing skill plugin manifests. It does not create a
new Claude skill plugin root when Claude has not initialized one yet.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SKILL_ID = "time-library"
DEFAULT_SKILL_NAME = "Time Library / 忆凡尘"


def _frontmatter(path: Path) -> dict[str, str]:
    skill_file = path / "SKILL.md"
    try:
        text = skill_file.read_text(encoding="utf-8-sig")
    except Exception:
        return {}
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


def _skill_identity(skill_src: Path) -> tuple[str, str, str, str]:
    meta = _frontmatter(skill_src)
    skill_id = meta.get("name") or DEFAULT_SKILL_ID
    if skill_id == "yifanchen-zhiyi":
        return skill_id, "Memcore Cloud Zhiyi", "zhiyi_recall", "legacy yifanchen-zhiyi MCP tool"
    return skill_id, DEFAULT_SKILL_NAME, "time_library_recall", "Time Library MCP tool"


def _skill_entry(skill_src: Path) -> dict[str, Any]:
    skill_id, skill_name, tool_name, tool_label = _skill_identity(skill_src)
    return {
        "skillId": skill_id,
        "name": skill_name,
        "description": (
            "Standing active memory rule, not a one-time setup note: call the "
            f"{tool_label} `{tool_name}` before answering "
            "about previous decisions, corrections, project boundaries, forgotten "
            "context, install/test/release status, or short follow-ups such as "
            "next step, what else, then what, 下一步, 接下来呢, 还有吗, or 然后呢. "
            "Use source refs and raw excerpts when available. If the MCP tool is missing, say the "
            "skill is installed but recall cannot run yet. Preserve Claude Desktop, "
            "Claude Code, official-login, and relay attribution boundaries."
        ),
        "creatorType": "local",
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "enabled": True,
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def install_skill(claude_home: Path, skill_src: Path, create: bool = False) -> dict[str, Any]:
    claude_home = claude_home.expanduser()
    skill_src = skill_src.expanduser()
    base = claude_home / "local-agent-mode-sessions" / "skills-plugin"
    if not skill_src.exists():
        return {
            "ok": False,
            "reason": "skill_source_not_found",
            "skill_source": str(skill_src),
            "installed_count": 0,
            "manifest_paths": [],
        }
    if not base.exists():
        return {
            "ok": True,
            "reason": "skills_plugin_not_found",
            "claude_home": str(claude_home),
            "installed_count": 0,
            "manifest_paths": [],
        }

    skill_id, _, _, _ = _skill_identity(skill_src)
    installed: list[str] = []
    errors: list[dict[str, str]] = []
    for manifest_path in sorted(base.glob("*/*/manifest.json")):
        plugin_root = manifest_path.parent
        try:
            manifest = _load_manifest(manifest_path)
            skills = manifest.get("skills")
            if not isinstance(skills, list):
                skills = []
            entry = _skill_entry(skill_src)
            replaced = False
            new_skills: list[Any] = []
            for item in skills:
                if isinstance(item, dict) and str(item.get("skillId") or item.get("id") or "") == skill_id:
                    new_skills.append({**item, **entry})
                    replaced = True
                else:
                    new_skills.append(item)
            if not replaced and create:
                new_skills.append(entry)
            if not replaced and not create:
                continue
            manifest["skills"] = new_skills
            manifest["lastUpdated"] = int(time.time() * 1000)

            dst = plugin_root / "skills" / skill_id
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(skill_src, dst)

            backup = manifest_path.with_suffix(manifest_path.suffix + ".bak-yifanchen-skill")
            if not backup.exists():
                backup.write_text(
                    manifest_path.read_text(encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                )
            tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
            tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(manifest_path)
            installed.append(str(manifest_path))
        except Exception as exc:  # pragma: no cover - surfaced in installer output
            errors.append({"manifest_path": str(manifest_path), "error": f"{type(exc).__name__}: {exc}"})

    return {
        "ok": not errors,
        "reason": "installed" if installed else "skill_not_found",
        "claude_home": str(claude_home),
        "skill_id": skill_id,
        "created_if_missing": create,
        "installed_count": len(installed),
        "manifest_paths": installed,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Memcore Cloud skill into existing Claude Desktop skill manifests.")
    parser.add_argument("claude_home")
    parser.add_argument("skill_source")
    parser.add_argument("--create", action="store_true", help="Create the skill entry when it is not already present.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = install_skill(Path(args.claude_home), Path(args.skill_source), create=args.create)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result.get('reason')} installed_count={result.get('installed_count', 0)}")
        for path in result.get("manifest_paths", []):
            print(path)
        for error in result.get("errors", []):
            print(f"ERROR {error.get('manifest_path')}: {error.get('error')}")
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
