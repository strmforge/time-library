#!/usr/bin/env python3
"""Stop stale Claude Desktop bridge children after an atomic config migration."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path


def _process_rows() -> list[tuple[int, str]]:
    if os.name == "nt":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
        ]
        output = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False).stdout.strip()
        if not output:
            return []
        data = json.loads(output)
        items = [data] if isinstance(data, dict) else data
        return [(int(item.get("ProcessId") or 0), str(item.get("CommandLine") or "")) for item in items]
    output = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    ).stdout
    rows = []
    for line in output.splitlines():
        raw_pid, separator, command = line.strip().partition(" ")
        if not separator:
            continue
        try:
            rows.append((int(raw_pid), command))
        except ValueError:
            continue
    return rows


def _stop(pid: int, *, force: bool) -> None:
    if os.name == "nt":
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


def refresh(roots: list[Path]) -> dict[str, object]:
    targets = {
        str(root.expanduser().resolve(strict=False) / "tools" / "claude_desktop_mcp_bridge.py")
        for root in roots
    }
    current = os.getpid()
    matched = sorted({
        pid
        for pid, command in _process_rows()
        if pid not in {current, os.getppid()} and any(target in command for target in targets)
    })
    for pid in matched:
        try:
            _stop(pid, force=False)
        except (OSError, subprocess.SubprocessError):
            pass
    deadline = time.monotonic() + 2.0
    remaining = set(matched)
    while remaining and time.monotonic() < deadline:
        live = {pid for pid, _command in _process_rows()}
        remaining.intersection_update(live)
        if remaining:
            time.sleep(0.1)
    for pid in sorted(remaining):
        try:
            _stop(pid, force=True)
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "ok": True,
        "matched_pids": matched,
        "stopped_count": len(matched),
        "host_process_stopped": False,
        "match_scope": sorted(targets),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-root", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(refresh([Path(value) for value in args.install_root]), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
