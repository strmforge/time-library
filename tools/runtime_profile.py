#!/usr/bin/env python3
"""Read-only runtime profile for Yifanchen local integrations.

This module is intentionally small: it gives the local UI enough evidence to
show whether Yifanchen, OpenClaw, and Hermes are reachable or installed without
reading conversation content or changing any platform state.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_FOR_IMPORT = Path(__file__).resolve().parent.parent
if str(ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(ROOT_FOR_IMPORT))

from src.hermes_paths import hermes_config_paths, resolve_hermes_home


UTC = timezone.utc
MEMCORE_ROOT = Path(os.environ.get("MEMCORE_ROOT") or Path(__file__).resolve().parent.parent)
OPENCLAW_HOME = Path(os.environ.get("OPENCLAW_HOME") or Path.home() / ".openclaw")
HERMES_HOME = resolve_hermes_home()
DISCOVERY_PROCESS_MARKERS = [
    "runtime_profile.py",
    "/api/v1/runtime/profile",
    "/api/v1/raw/query",
    "python3 -m json.tool",
    "curl -sS",
    "curl --",
    "python -c",
    "python3 -c",
    "/bin/zsh -lc",
    "/bin/bash -lc",
]


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(argv: list[str], timeout: int = 3) -> tuple[str, int]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return (proc.stdout or proc.stderr or "").strip(), proc.returncode
    except Exception:
        return "", 1


def _ps_lines() -> list[str]:
    out, code = _run(["ps", "axo", "pid=,command="], timeout=5)
    return out.splitlines() if code == 0 else []


def _trim(value: str | None, limit: int = 220) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _processes_containing(*needles: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    lowered_needles = [needle.lower() for needle in needles]
    for line in _ps_lines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(marker.lower() in lowered for marker in DISCOVERY_PROCESS_MARKERS):
            continue
        if all(needle in lowered for needle in lowered_needles):
            pid_text, _, command = stripped.partition(" ")
            try:
                pid = int(pid_text)
            except ValueError:
                continue
            matches.append({
                "type": "running",
                "pid": pid,
                "command": _trim(command.strip()),
            })
    return matches


def http_health_check(url: str, timeout: int = 2) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(400).decode("utf-8", errors="replace")
            return {
                "reachable": True,
                "status_code": resp.status,
                "body": body,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(200).decode("utf-8", errors="replace")
        return {
            "reachable": True,
            "status_code": exc.code,
            "body": body,
            "error": None,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "status_code": None,
            "body": None,
            "error": str(exc),
        }


def _first_reachable(urls: list[str]) -> dict[str, Any]:
    last_error: str | None = None
    for url in urls:
        result = http_health_check(url)
        if result.get("reachable"):
            return {
                "reachable": True,
                "health_url": url,
                "status_code": result.get("status_code"),
                "details": _trim(result.get("body"), 200),
            }
        last_error = result.get("error")
    return {
        "reachable": False,
        "health_url": None,
        "status_code": None,
        "details": None,
        "error": last_error,
    }


def probe_memcore_health() -> dict[str, Any]:
    return _first_reachable([
        "http://127.0.0.1:9850/api/v1/update/status",
        "http://127.0.0.1:9830/health",
    ])


def probe_openclaw_health() -> dict[str, Any]:
    return _first_reachable([
        "http://127.0.0.1:18789/health",
        "http://localhost:18789/health",
    ])


def probe_hermes_health() -> dict[str, Any]:
    return _first_reachable([
        "http://127.0.0.1:8642/health",
        "http://localhost:8642/health",
    ])


def _version_from_file(root: Path) -> str | None:
    version_file = root / "VERSION"
    if not version_file.exists():
        return None
    try:
        return version_file.read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def find_memcore_instances() -> list[dict[str, Any]]:
    instances = _processes_containing("memcore-cloud")
    if MEMCORE_ROOT.exists():
        instances.append({
            "type": "installed",
            "path": str(MEMCORE_ROOT),
            "version": _version_from_file(MEMCORE_ROOT),
            "has_console": (MEMCORE_ROOT / "src" / "p6_console.py").exists(),
        })
    return instances


def get_memcore_running_instance() -> dict[str, Any] | None:
    for item in _processes_containing("p6_console.py"):
        return item
    for item in _processes_containing("memcore-cloud.py"):
        return item
    return None


def get_openclaw_version() -> str | None:
    for candidate in ["openclaw", "/opt/homebrew/bin/openclaw", "/usr/local/bin/openclaw"]:
        if "/" in candidate and not Path(candidate).exists():
            continue
        out, code = _run([candidate, "--version"])
        if code == 0 and out:
            return out
    return None


def find_openclaw_instances() -> list[dict[str, Any]]:
    instances = _processes_containing("openclaw")
    if OPENCLAW_HOME.exists():
        instances.append({"type": "openclaw_home", "path": str(OPENCLAW_HOME)})
    plugin_index = OPENCLAW_HOME / "plugins" / "installs.json"
    if plugin_index.exists():
        instances.append({
            "type": "openclaw_plugin_index",
            "path": str(plugin_index),
            "size": plugin_index.stat().st_size,
        })
    return instances


def get_openclaw_running_instance() -> dict[str, Any] | None:
    for item in _processes_containing("openclaw", "gateway"):
        return item
    return None


def get_hermes_version() -> str | None:
    candidates = [
        os.environ.get("HERMES_BIN"),
        str(HERMES_HOME / "bin" / "hermes"),
        str(HERMES_HOME / "bin" / "tirith"),
        "hermes",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if "/" in candidate and not Path(candidate).exists():
            continue
        out, code = _run([candidate, "--version"])
        if code == 0 and out:
            return out
    return None


def find_hermes_instances() -> list[dict[str, Any]]:
    instances = _processes_containing("hermes")
    if HERMES_HOME.exists():
        instances.append({"type": "hermes_home", "path": str(HERMES_HOME)})
    plugin_dir = HERMES_HOME / "plugins" / "memcore_yifanchen"
    if plugin_dir.exists():
        instances.append({"type": "memcore_yifanchen_plugin", "path": str(plugin_dir)})
    for config_path in hermes_config_paths(HERMES_HOME, existing_only=True):
        instances.append({
            "type": "hermes_config",
            "path": str(config_path),
            "size": config_path.stat().st_size,
        })
    agent_dir = HERMES_HOME / "hermes-agent"
    if agent_dir.exists():
        instances.append({"type": "hermes_agent", "path": str(agent_dir)})
    return instances


def get_hermes_running_instance() -> dict[str, Any] | None:
    for item in find_hermes_instances():
        if item.get("type") == "running":
            return item
    return None


def detect_source_system_status(source_key: str) -> str:
    if source_key == "openclaw":
        if probe_openclaw_health().get("reachable"):
            return "active"
        if find_openclaw_instances():
            return "detected"
        return "not_found"
    if source_key == "hermes":
        if probe_hermes_health().get("reachable"):
            return "active"
        if find_hermes_instances():
            return "detected"
        return "not_found"
    if source_key in {"memcore-cloud", "memcore_cloud", "yifanchen"}:
        if probe_memcore_health().get("reachable"):
            return "active"
        if find_memcore_instances():
            return "detected"
        return "not_found"
    return "unknown"


def _profile_status(health: dict[str, Any], running: dict[str, Any] | None, detected: bool) -> str:
    if health.get("reachable"):
        return "active"
    if running or detected:
        return "detected"
    return "not_found"


def build_memcore_profile() -> dict[str, Any]:
    instances = find_memcore_instances()
    running = get_memcore_running_instance()
    health = probe_memcore_health()
    selected = None
    if running:
        selected = {"source": "running_process", "detail": running}
    elif health.get("reachable"):
        selected = {"source": "health_endpoint", "detail": health.get("health_url")}
    elif instances:
        selected = {"source": "installed", "detail": instances[0]}
    return {
        "system": "memcore-cloud",
        "status": _profile_status(health, running, bool(instances)),
        "version": _version_from_file(MEMCORE_ROOT),
        "instances": instances,
        "running_instance": running,
        "selected_runtime": selected,
        "health": {
            "reachable": health.get("reachable", False),
            "health_url": health.get("health_url"),
            "status_code": health.get("status_code"),
        },
        "stale_instances": [],
        "version_mismatches": [],
    }


def build_openclaw_profile() -> dict[str, Any]:
    instances = find_openclaw_instances()
    running = get_openclaw_running_instance()
    health = probe_openclaw_health()
    selected = None
    if running:
        selected = {"source": "running_process", "detail": running}
    elif health.get("reachable"):
        selected = {"source": "health_endpoint", "detail": health.get("health_url")}
    elif instances:
        selected = {"source": "installed", "detail": instances[0]}
    return {
        "system": "openclaw",
        "status": _profile_status(health, running, bool(instances)),
        "version": get_openclaw_version(),
        "instances": instances,
        "running_instance": running,
        "selected_runtime": selected,
        "health": {
            "reachable": health.get("reachable", False),
            "health_url": health.get("health_url"),
            "status_code": health.get("status_code"),
        },
        "stale_instances": [],
        "version_mismatches": [],
    }


def build_hermes_profile() -> dict[str, Any]:
    instances = find_hermes_instances()
    running = get_hermes_running_instance()
    health = probe_hermes_health()
    selected = None
    if running:
        selected = {"source": "running_process", "detail": running}
    elif health.get("reachable"):
        selected = {"source": "health_endpoint", "detail": health.get("health_url")}
    elif instances:
        selected = {"source": "installed", "detail": instances[0]}
    config_paths = hermes_config_paths(HERMES_HOME, existing_only=True)
    config_path = config_paths[0] if config_paths else (HERMES_HOME / "profiles" / "default" / "config.yaml")
    return {
        "system": "hermes",
        "status": _profile_status(health, running, bool(instances)),
        "version": get_hermes_version(),
        "instances": instances,
        "running_instance": running,
        "selected_runtime": selected,
        "install_root": str(HERMES_HOME) if HERMES_HOME.exists() else None,
        "home_resolution": "HERMES_HOME" if os.environ.get("HERMES_HOME") else "platform_default",
        "config": {
            "path": str(config_path),
            "profiles_supported": True,
            "size": config_path.stat().st_size if config_path.exists() else None,
        } if config_path.exists() else None,
        "health": {
            "reachable": health.get("reachable", False),
            "health_url": health.get("health_url"),
            "status_code": health.get("status_code"),
        },
    }


def build_instances_summary() -> dict[str, Any]:
    openclaw = find_openclaw_instances()
    hermes = find_hermes_instances()
    memcore = find_memcore_instances()
    return {
        "memcore_cloud": memcore,
        "openclaw": openclaw,
        "hermes": hermes,
        "detected_count": sum(1 for items in [openclaw, hermes] if items),
        "openclaw_detected": bool(openclaw),
        "hermes_detected": bool(hermes),
        "stale_instances": [],
        "version_mismatches": [],
    }


def build_all_profile() -> dict[str, Any]:
    return {
        "generated_at": ts(),
        "memcore_cloud": build_memcore_profile(),
        "openclaw": build_openclaw_profile(),
        "hermes": build_hermes_profile(),
        "instances_summary": build_instances_summary(),
    }


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "all"
    if command in {"all", "profile"}:
        payload = build_all_profile() if command == "all" else build_memcore_profile()
    elif command == "openclaw":
        payload = build_openclaw_profile()
    elif command == "hermes":
        payload = build_hermes_profile()
    elif command == "instances":
        payload = build_instances_summary()
    elif command == "compatibility":
        payload = {
            "memcore_cloud": build_memcore_profile(),
            "openclaw": build_openclaw_profile(),
            "hermes": build_hermes_profile(),
        }
    else:
        print("Usage: runtime_profile.py [all|profile|openclaw|hermes|instances|compatibility]", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
