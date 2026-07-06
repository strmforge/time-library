#!/usr/bin/env python3
"""Manage the bounded Hermes autonomous native-learning background loop."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.hermes_autonomous_loop import (  # noqa: E402
    DEFAULT_BACKGROUND_LABEL,
    build_hermes_background_launchd_plist,
    load_hermes_autonomous_loop_state,
    load_hermes_background_config,
    load_hermes_background_state,
    query_hermes_autonomous_loop_runs,
    run_hermes_autonomous_loop_background_tick,
    write_hermes_background_config,
    write_hermes_background_launchd_plist,
)


def _print_json(value: dict) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if value.get("ok") is not False else 1


def _load_json_arg(text: str) -> dict:
    if not text:
        return {}
    path = Path(text).expanduser()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("config JSON must be an object")
    return data


def _launchctl(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(["launchctl", *args], text=True, capture_output=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def _bootstrap_launchd(label: str, plist_path: Path) -> dict:
    uid = subprocess.run(["id", "-u"], text=True, capture_output=True, check=False).stdout.strip()
    target = f"gui/{uid}"
    service = f"{target}/{label}"
    actions = []
    for args in (("bootout", service), ("remove", label), ("bootstrap", target, str(plist_path)), ("enable", service)):
        code, stdout, stderr = _launchctl(*args)
        actions.append({
            "args": ["launchctl", *args],
            "returncode": code,
            "stdout": stdout.strip(),
            "stderr": stderr.strip(),
        })
    listed_code, listed_out, listed_err = _launchctl("list", label)
    return {
        "uid": uid,
        "target": target,
        "service": service,
        "actions": actions,
        "launchctl_list": {
            "returncode": listed_code,
            "stdout": listed_out.strip(),
            "stderr": listed_err.strip(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="", help="Installed Time Library root")
    parser.add_argument("--install-root", default="", help="Installed code root, defaults to --root")
    parser.add_argument("--python-bin", default="", help="Python executable for launchd plist")
    parser.add_argument("--config-json", default="", help="JSON object or path merged into background config")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show config, background state, loop state, and recent runs")
    sub.add_parser("write-config", help="Write bounded default background config")
    sub.add_parser("tick", help="Run one bounded background tick")
    sub.add_parser("launchd-plan", help="Print the LaunchAgent plist plan")
    sub.add_parser("write-launchd-plist", help="Write the LaunchAgent plist only")
    sub.add_parser("install-launchd", help="Write and bootstrap the LaunchAgent")

    args = parser.parse_args(argv)
    root = Path(args.root).expanduser() if args.root else ROOT
    install_root = Path(args.install_root).expanduser() if args.install_root else root
    python_bin = Path(args.python_bin).expanduser() if args.python_bin else install_root / ".venv" / "bin" / "python"
    try:
        config = _load_json_arg(args.config_json)
    except Exception as exc:
        return _print_json({"ok": False, "error": f"invalid_config_json:{type(exc).__name__}:{exc}"})

    if args.cmd == "status":
        return _print_json({
            "ok": True,
            "read_only": True,
            "write_performed": False,
            "config": load_hermes_background_config(
                memcore_root=root,
                install_root=install_root,
                python_bin=python_bin,
            ),
            "background_state": load_hermes_background_state(memcore_root=root),
            "loop_state": load_hermes_autonomous_loop_state(memcore_root=root),
            "runs": query_hermes_autonomous_loop_runs(memcore_root=root, limit=10),
        })

    if args.cmd == "write-config":
        return _print_json(write_hermes_background_config(
            config,
            memcore_root=root,
            install_root=install_root,
            python_bin=python_bin,
        ))

    if args.cmd == "tick":
        return _print_json(run_hermes_autonomous_loop_background_tick(
            config,
            memcore_root=root,
            install_root=install_root,
            python_bin=python_bin,
        ))

    if args.cmd == "launchd-plan":
        return _print_json(build_hermes_background_launchd_plist(
            config,
            memcore_root=root,
            install_root=install_root,
            python_bin=python_bin,
        ))

    if args.cmd == "write-launchd-plist":
        return _print_json(write_hermes_background_launchd_plist(
            config,
            memcore_root=root,
            install_root=install_root,
            python_bin=python_bin,
        ))

    if args.cmd == "install-launchd":
        written = write_hermes_background_config(
            config,
            memcore_root=root,
            install_root=install_root,
            python_bin=python_bin,
        )
        plist = write_hermes_background_launchd_plist(
            written.get("config", config),
            memcore_root=root,
            install_root=install_root,
            python_bin=python_bin,
        )
        label = plist.get("label", DEFAULT_BACKGROUND_LABEL)
        launchd = _bootstrap_launchd(label, Path(plist["plist_path"]))
        return _print_json({
            "ok": plist.get("ok") is True and launchd["actions"][-2]["returncode"] == 0,
            "write_performed": True,
            "config": written,
            "plist": plist,
            "launchd": launchd,
            "non_claims": [
                "installing_launchd_does_not_force_an_immediate_hermes_spend",
                "tick_value_gate_and_daily_budget_control_hermes_calls",
                "production_experience_auto_adoption_remains_disabled",
            ],
        })

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
