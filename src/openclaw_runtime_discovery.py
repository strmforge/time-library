#!/usr/bin/env python3
"""
OpenClaw Runtime Discovery
OpenClaw runtime discovery.

功能：探测本机 OpenClaw runtime 状态
约束：只读探测，不修改任何配置
输出：runtime/openclaw_runtime_snapshot.json + logs/openclaw_discovery.jsonl
"""

import json
import os
import subprocess
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from config_loader import get_memcore_root
from service_manager import get_service_manager

UTC = timezone.utc
OPENCLAW_ROOT = Path.home() / ".openclaw"
MEMCORE_ROOT = Path(get_memcore_root())
OUTPUT_DIR = MEMCORE_ROOT / "runtime"
LOG_DIR = MEMCORE_ROOT / "logs"
OUTPUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


def ts():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_cmd(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode, None
    except subprocess.TimeoutExpired:
        return "", 1, "timeout"
    except Exception as e:
        return "", 1, str(e)


def file_checksum(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return None


def discover_processes():
    stdout, code, _ = run_cmd("ps aux | grep -i openclaw | grep -v grep")
    processes = []
    if code == 0 and stdout:
        for line in stdout.splitlines():
            parts = line.split(None, 10)
            if len(parts) >= 11:
                processes.append({
                    "pid": parts[1],
                    "user": parts[0],
                    "cpu": parts[2],
                    "mem": parts[3],
                    "command": parts[10]
                })
    return processes


def discover_services():
    sm = get_service_manager()
    units = sm.list_units("service")
    services = [u for u in units if "openclaw" in u.get("name", "")]
    return services


def discover_ports():
    stdout, code, _ = run_cmd("ss -lntp | grep -E '19830|19840|19850|8090|8091' || true")
    ports = []
    if code == 0 and stdout:
        for line in stdout.splitlines():
            ports.append(line.strip())
    return ports


def discover_gateway_config():
    config = {}
    gateway_dir = OPENCLAW_ROOT / "gateway"
    if gateway_dir.exists():
        config_dir = gateway_dir / "config"
        if config_dir.exists():
            for f in config_dir.glob("*.json"):
                rel = f.relative_to(OPENCLAW_ROOT)
                config[str(rel)] = {
                    "exists": True,
                    "size": f.stat().st_size,
                    "checksum": file_checksum(f)
                }
    return config


def discover_agents():
    agents_dir = OPENCLAW_ROOT / "agents"
    agents = []
    if agents_dir.exists():
        for d in agents_dir.iterdir():
            if d.is_dir():
                sessions_dir = d / "sessions"
                sessions = len(list(sessions_dir.glob("*.jsonl"))) if sessions_dir.exists() else 0
                agents.append({
                    "agent_id": d.name,
                    "path": str(d),
                    "sessions_count": sessions
                })
    return agents


def discover_sessions():
    agents_dir = OPENCLAW_ROOT / "agents"
    sessions = []
    if agents_dir.exists():
        for d in agents_dir.iterdir():
            if d.is_dir():
                sessions_dir = d / "sessions"
                if sessions_dir.exists():
                    for f in sessions_dir.glob("*.jsonl"):
                        stat = f.stat()
                        sessions.append({
                            "session_id": f.stem,
                            "agent": d.name,
                            "size_bytes": stat.st_size,
                            "modified": stat.st_mtime
                        })
    return sessions


def main():
    snapshot = {
        "generated_at": ts(),
        "openclaw_root": str(OPENCLAW_ROOT),
        "memcore_root": str(MEMCORE_ROOT),
        "node_id": "local",
        "processes": discover_processes(),
        "services": discover_services(),
        "ports": discover_ports(),
        "gateway_config": discover_gateway_config(),
        "agents": discover_agents(),
        "sessions_count": len(discover_sessions()),
        "top_sessions": sorted(discover_sessions(), key=lambda x: x["size_bytes"], reverse=True)[:5]
    }

    # Write snapshot
    snapshot_path = OUTPUT_DIR / "openclaw_runtime_snapshot.json"
    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    print(f"Snapshot written: {snapshot_path}")

    # Write log
    log_entry = {
        "ts": ts(),
        "action": "runtime_discovery",
        "risk_level": "low",
        "result": "ok",
        "snapshot_path": str(snapshot_path),
        "processes_found": len(snapshot["processes"]),
        "sessions_found": snapshot["sessions_count"]
    }
    log_path = LOG_DIR / "openclaw_discovery.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    print(f"Log written: {log_path}")

    print(f"\nDiscovery summary:")
    print(f"  Processes: {len(snapshot['processes'])}")
    print(f"  Services: {len(snapshot['services'])}")
    print(f"  Ports: {len(snapshot['ports'])}")
    print(f"  Agents: {len(snapshot['agents'])}")
    print(f"  Sessions: {snapshot['sessions_count']}")


if __name__ == "__main__":
    main()
