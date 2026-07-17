#!/usr/bin/env python3
"""Fail closed unless installer-owned runtime roots have no process or writer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.install_runtime_identity import (  # noqa: E402
    argv_targets_install_roots,
    macos_ps_command_targets_install_roots,
)


def _under_roots(path: str, roots: list[str]) -> bool:
    cleaned = path.removesuffix(" (deleted)")
    if not cleaned.startswith("/"):
        return False
    for root in roots:
        try:
            if os.path.commonpath((cleaned, root)) == root:
                return True
        except ValueError:
            continue
    return False


def _linux_processes(roots: list[str]) -> list[dict[str, Any]]:
    matches = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        if pid in {os.getpid(), os.getppid()}:
            continue
        try:
            args = [
                item.decode("utf-8", errors="replace")
                for item in (proc / "cmdline").read_bytes().split(b"\0")
                if item
            ]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if argv_targets_install_roots(args, roots):
            matches.append({"pid": pid})
    return matches


def _linux_writers(roots: list[str]) -> list[dict[str, Any]]:
    matches = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        if pid in {os.getpid(), os.getppid()}:
            continue
        fd_root = proc / "fd"
        try:
            descriptors = list(fd_root.iterdir())
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
                info = (proc / "fdinfo" / descriptor.name).read_text(encoding="ascii", errors="replace")
            except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
                continue
            flags_line = next((line for line in info.splitlines() if line.startswith("flags:")), "")
            try:
                flags = int(flags_line.split()[1], 8)
            except (IndexError, ValueError):
                continue
            if (flags & os.O_ACCMODE) not in {os.O_WRONLY, os.O_RDWR}:
                continue
            if _under_roots(target, roots):
                matches.append({"pid": pid, "fd": descriptor.name})
    return matches


def _macos_processes(roots: list[str]) -> list[dict[str, Any]]:
    rows = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines()
    matches = []
    for row in rows:
        raw_pid, _, command = row.strip().partition(" ")
        try:
            pid = int(raw_pid)
        except ValueError:
            continue
        if pid in {os.getpid(), os.getppid()}:
            continue
        if macos_ps_command_targets_install_roots(command, roots):
            matches.append({"pid": pid})
    return matches


def _macos_writers(roots: list[str]) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["lsof", "-n", "-P", "-F", "pfan", "-u", str(os.getuid())],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        raise RuntimeError(f"lsof failed with exit {completed.returncode}")
    matches = []
    pid = None
    fd = ""
    access = ""
    for line in completed.stdout.splitlines():
        prefix, value = line[:1], line[1:]
        if prefix == "p":
            pid = int(value)
            fd = ""
            access = ""
        elif prefix == "f":
            fd = value
            access = ""
        elif prefix == "a":
            access = value
        elif prefix == "n" and pid not in {None, os.getpid(), os.getppid()}:
            if access in {"w", "u"} and _under_roots(value, roots):
                matches.append({"pid": pid, "fd": fd})
    return matches


def check(roots: list[Path]) -> dict[str, Any]:
    normalized = [str(path.expanduser().resolve()) for path in roots]
    if sys.platform == "linux":
        processes = _linux_processes(normalized)
        writers = _linux_writers(normalized)
    elif sys.platform == "darwin":
        processes = _macos_processes(normalized)
        writers = _macos_writers(normalized)
    else:
        raise RuntimeError(f"unsupported platform: {sys.platform}")
    return {
        "contract": "time_library_install_runtime_quiescence.v1",
        "roots": normalized,
        "process_count": len(processes),
        "writer_count": len(writers),
        "processes": processes,
        "writers": writers,
        "ok": not processes and not writers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, action="append", required=True)
    args = parser.parse_args()
    result = check(args.root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
