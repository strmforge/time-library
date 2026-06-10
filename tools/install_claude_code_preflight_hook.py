#!/usr/bin/env python3
"""Install the Yifanchen preflight hook into Claude Code settings."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


HOOK_NAME = "yifanchen-zhiyi-preflight"
EVENT_NAME = "UserPromptSubmit"
DEFAULT_ENDPOINT = "http://127.0.0.1:9851/api/v1/raw/query"
DEFAULT_PREFLIGHT_TIMEOUT_SECONDS = 0.75


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _settings_path(scope: str, project_root: str = "") -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    root = Path(project_root or os.getcwd()).expanduser().resolve(strict=False)
    if scope == "project":
        return root / ".claude" / "settings.json"
    if scope == "project-local":
        return root / ".claude" / "settings.local.json"
    raise ValueError(f"unsupported scope: {scope}")


def _hook_handler(
    *,
    python_executable: str,
    hook_script: Path,
    endpoint: str,
    timeout: float,
    max_context_chars: int,
) -> dict[str, Any]:
    return {
        "type": "command",
        "command": python_executable,
        "args": [
            str(hook_script),
            "--endpoint",
            endpoint,
            "--timeout",
            str(timeout),
            "--max-context-chars",
            str(max_context_chars),
        ],
        "timeout": max(1, int(timeout + 1)),
        "statusMessage": "Checking Yifanchen context",
    }


def _is_yifanchen_handler(handler: Any, hook_script: Path) -> bool:
    if not isinstance(handler, dict):
        return False
    args = handler.get("args")
    if isinstance(args, list):
        for arg in args:
            text = str(arg)
            if text == str(hook_script):
                return True
            if Path(text).name == hook_script.name == "claude_code_preflight_hook.py":
                return True
    command = str(handler.get("command") or "")
    return hook_script.name in command and "claude_code_preflight_hook" in command


def _hook_group(handler: dict[str, Any]) -> dict[str, Any]:
    return {
        "hooks": [handler],
        "description": "Yifanchen Zhiyi/Xingce preflight before Claude answers memory-dependent prompts.",
    }


def install_hook(
    settings_path: Path,
    hook_script: Path,
    *,
    python_executable: str = sys.executable,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_PREFLIGHT_TIMEOUT_SECONDS,
    max_context_chars: int = 5000,
) -> dict[str, Any]:
    settings_path = settings_path.expanduser()
    hook_script = hook_script.expanduser().resolve(strict=False)
    if not hook_script.exists():
        return {
            "ok": False,
            "reason": "hook_script_not_found",
            "settings_path": str(settings_path),
            "hook_script": str(hook_script),
            "installed": False,
        }

    cfg = _load_json(settings_path)
    hooks = cfg.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        cfg["hooks"] = hooks
    event_groups = hooks.get(EVENT_NAME)
    if not isinstance(event_groups, list):
        event_groups = []
    handler = _hook_handler(
        python_executable=python_executable,
        hook_script=hook_script,
        endpoint=endpoint,
        timeout=timeout,
        max_context_chars=max_context_chars,
    )

    new_groups: list[Any] = []
    replaced = False
    for group in event_groups:
        if not isinstance(group, dict):
            new_groups.append(group)
            continue
        group_hooks = group.get("hooks")
        if not isinstance(group_hooks, list):
            new_groups.append(group)
            continue
        kept = [item for item in group_hooks if not _is_yifanchen_handler(item, hook_script)]
        if len(kept) != len(group_hooks):
            if kept:
                new_group = dict(group)
                new_group["hooks"] = kept
                new_groups.append(new_group)
            if not replaced:
                new_groups.append(_hook_group(handler))
                replaced = True
        else:
            new_groups.append(group)
    if not replaced:
        new_groups.append(_hook_group(handler))

    hooks[EVENT_NAME] = new_groups
    cfg.setdefault("memcoreCloud", {})
    if isinstance(cfg.get("memcoreCloud"), dict):
        cfg["memcoreCloud"]["yifanchenPreflightHook"] = {
            "name": HOOK_NAME,
            "event": EVENT_NAME,
            "hookScript": str(hook_script),
            "endpoint": endpoint,
            "updatedAt": int(time.time()),
        }

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        backup = settings_path.with_suffix(settings_path.suffix + ".bak-yifanchen-preflight")
        if not backup.exists():
            backup.write_text(
                settings_path.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
    tmp = settings_path.with_suffix(settings_path.suffix + ".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(settings_path)
    return {
        "ok": True,
        "reason": "installed" if not replaced else "updated",
        "settings_path": str(settings_path),
        "hook_script": str(hook_script),
        "event": EVENT_NAME,
        "hook_name": HOOK_NAME,
        "installed": True,
        "python_executable": python_executable,
        "endpoint": endpoint,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Yifanchen preflight hook for Claude Code.")
    parser.add_argument("--scope", choices=("user", "project", "project-local"), default="user")
    parser.add_argument("--project-root", default="")
    parser.add_argument("--settings-path", default="")
    parser.add_argument("--hook-script", default=str(Path(__file__).with_name("claude_code_preflight_hook.py")))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_PREFLIGHT_TIMEOUT_SECONDS)
    parser.add_argument("--max-context-chars", type=int, default=5000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    settings_path = Path(args.settings_path).expanduser() if args.settings_path else _settings_path(args.scope, args.project_root)
    result = install_hook(
        settings_path,
        Path(args.hook_script),
        python_executable=args.python,
        endpoint=args.endpoint,
        timeout=args.timeout,
        max_context_chars=args.max_context_chars,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result.get('reason')} {result.get('settings_path')}")
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
