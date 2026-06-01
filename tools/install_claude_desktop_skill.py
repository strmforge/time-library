#!/usr/bin/env python3
"""Install or update the Yifanchen skill inside Claude Desktop skill manifests.

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


SKILL_ID = "yifanchen-zhiyi"


def _skill_entry() -> dict[str, Any]:
    return {
        "skillId": SKILL_ID,
        "name": "Yifanchen Zhiyi",
        "description": (
            "Use Yifanchen as the local source-backed memory library through MCP. "
            "Aggregate Claude records under claude_all for reading, while preserving "
            "source refs, dual attribution, and official/relay isolation boundaries."
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

    installed: list[str] = []
    errors: list[dict[str, str]] = []
    for manifest_path in sorted(base.glob("*/*/manifest.json")):
        plugin_root = manifest_path.parent
        try:
            manifest = _load_manifest(manifest_path)
            skills = manifest.get("skills")
            if not isinstance(skills, list):
                skills = []
            entry = _skill_entry()
            replaced = False
            new_skills: list[Any] = []
            for item in skills:
                if isinstance(item, dict) and str(item.get("skillId") or item.get("id") or "") == SKILL_ID:
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

            dst = plugin_root / "skills" / SKILL_ID
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
        "skill_id": SKILL_ID,
        "created_if_missing": create,
        "installed_count": len(installed),
        "manifest_paths": installed,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Yifanchen skill into existing Claude Desktop skill manifests.")
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
