"""Moving a computer off an earlier Time Library install (the one that ran a
full set of services on every computer).

    old-install scan                    what is there: folders, services, history
    old-install stop                    stop its services (they keep restarting otherwise)
    old-install archive --to FOLDER     keep a copy (a tar file per install folder), checked
    old-install remove                  remove its services and folders (after archive)

The history it kept is brought over with the ordinary `import` command; `scan`
prints those commands. The agents' own settings (MCP entries, hooks, skills
that point into the old folder) are changed by each agent itself, the same way
it connected: this client never edits another program's configuration.

The places below are where that earlier install itself lived, per operating
system; nothing here depends on which agents are installed.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .formats import BUILTIN_FORMATS, extract_message

OLD_NAMES = ("time-library", "memcore-cloud")
SIDE_FILES = re.compile(r"\.(canonical_dialogue\.jsonl|forensic_runtime\.json|meta\.json|prefix-proof\.json|generation\.lock)$")
TRANSCRIPT_GLOBS = (
    "**/*-????-????-????-????????????.jsonl",
    "**/*.seg[0-9].jsonl",
    "**/*.seg[0-9][0-9].jsonl",
    "**/*.seg[0-9][0-9][0-9].jsonl",
)
ARCHIVE_RECORD = "old-install-archives.json"


def candidate_roots() -> list[Path]:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        bases = [home / "Library" / "Application Support"]
    elif system == "Windows":
        bases = [Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))]
    else:
        bases = [home / ".local" / "share", home / ".local" / "state"]
    return [base / name for base in bases for name in OLD_NAMES if (base / name).is_dir()]


def _is_old_install(root: Path) -> bool:
    return any((root / marker).exists() for marker in ("src", "memory", "runtime", "config"))


def roots() -> list[Path]:
    return [root for root in candidate_roots() if _is_old_install(root)]


# ---- services ---------------------------------------------------------------


def _run(command: list[str]) -> str:
    """A command's output as text; '' on any failure. Output in another encoding
    (Windows consoles) is read as UTF-8 with stand-ins, never as nothing."""
    if command and command[0] == "powershell" and "-Command" in command:
        at = command.index("-Command") + 1
        command = [*command[:at], "[Console]::OutputEncoding = [Text.Encoding]::UTF8; " + command[at], *command[at + 1 :]]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (completed.stdout or b"").decode("utf-8", errors="replace")


def services() -> list[dict[str, str]]:
    system = platform.system()
    found: list[dict[str, str]] = []
    if system == "Darwin":
        folder = Path.home() / "Library" / "LaunchAgents"
        for plist in sorted(folder.glob("com.memcorecloud.*.plist")):
            found.append({"kind": "launchd", "name": plist.stem, "file": str(plist)})
    elif system == "Windows":
        out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "Get-ScheduledTask | Where-Object { $_.TaskName -match '^MemcoreCloud' } | ForEach-Object { $_.TaskName }"])
        found += [{"kind": "scheduled_task", "name": name.strip()} for name in out.splitlines() if name.strip()]
    else:
        folder = Path.home() / ".config" / "systemd" / "user"
        for unit in sorted(folder.glob("*.service")):
            if unit.name.startswith(("time-library-", "memcore")) and unit.name != "time-library-client.service":
                found.append({"kind": "systemd", "name": unit.name, "file": str(unit)})
    return found


def stop() -> list[str]:
    done = []
    for service in services():
        if service["kind"] == "launchd":
            _run(["launchctl", "bootout", f"gui/{os.getuid()}/{service['name']}"])
        elif service["kind"] == "scheduled_task":
            _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                  f"Stop-ScheduledTask -TaskName '{service['name']}' -ErrorAction SilentlyContinue; "
                  f"Disable-ScheduledTask -TaskName '{service['name']}' -ErrorAction SilentlyContinue | Out-Null"])
        else:
            _run(["systemctl", "--user", "disable", "--now", service["name"]])
        done.append(service["name"])
    # Whatever still runs from the old folders (helpers its services started).
    for root in roots():
        for pid in _processes_under(root):
            _kill(pid)
            done.append(f"process {pid}")
    return done


def _processes_under(root: Path) -> list[int]:
    needle = str(root)
    if platform.system() == "Windows":
        out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"])
    else:
        out = _run(["ps", "-axo", "pid=,command="])
    found = []
    for line in out.splitlines():
        pid_text, _, command = line.strip().partition("\t" if platform.system() == "Windows" else " ")
        if runs_from(command, needle) and pid_text.strip().isdigit() and int(pid_text) != os.getpid():
            found.append(int(pid_text))
    return found


def runs_from(command: str, folder: str) -> bool:
    """Whether a command line refers to something inside `folder` (as a whole folder:
    a sibling such as "time-library-client" next to "time-library" does not count)."""
    pattern = re.escape(folder.rstrip("/\\")) + r'(?=[/\\"\'\s]|$)'
    return re.search(pattern, command, re.IGNORECASE if platform.system() == "Windows" else 0) is not None


def _kill(pid: int) -> None:
    if platform.system() == "Windows":
        _run(["taskkill", "/PID", str(pid), "/F"])
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


# ---- what history is there ------------------------------------------------------


@dataclass
class Collection:
    path: str
    computer: str
    source: str
    files: int
    bytes: int
    shape: str
    globs: list[str] = field(default_factory=list)


def _transcripts(folder: Path) -> list[Path]:
    files = {path for pattern in TRANSCRIPT_GLOBS for path in folder.glob(pattern) if path.is_file()}
    if not files:  # a collection named some other way: every .jsonl that is not a side file
        files = {path for path in folder.rglob("*.jsonl") if path.is_file() and not SIDE_FILES.search(path.name)}
    return sorted(files)


def _shape(files: list[Path]) -> str:
    """The built-in shape that reads dialogue out of these files, if one does."""
    for path in files[:5]:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                lines = [handle.readline() for _ in range(200)]
        except OSError:
            continue
        for name, spec in BUILTIN_FORMATS.items():
            hits = 0
            for line in lines:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if extract_message(record, spec) is not None:
                    hits += 1
            if hits >= 2:
                return name
    return ""


def collections(root: Path) -> list[Collection]:
    memory = root / "memory"
    found: list[Collection] = []
    if not memory.is_dir():
        return found
    for computer in sorted(path for path in memory.iterdir() if path.is_dir()):
        for source in sorted(path for path in computer.iterdir() if path.is_dir()):
            for folder in sorted(path for path in source.iterdir() if path.is_dir()):
                files = _transcripts(folder)
                if not files:
                    continue
                uses_globs = any(True for pattern in TRANSCRIPT_GLOBS for _ in folder.glob(pattern))
                found.append(
                    Collection(
                        path=str(folder),
                        computer=computer.name,
                        source=source.name,
                        files=len(files),
                        bytes=sum(path.stat().st_size for path in files),
                        shape=_shape(files),
                        globs=list(TRANSCRIPT_GLOBS) if uses_globs else ["**/*.jsonl"],
                    )
                )
    return found


def import_command(collection: Collection, launcher: str) -> str:
    globs = " ".join(f'--glob "{pattern}"' for pattern in collection.globs)
    shape = f"--format {collection.shape}" if collection.shape else "--format-json '<your shape description>'"
    return f'{launcher} import --agent "<your name>" --from "{collection.path}" {shape} {globs}'


def scan(launcher: str = "PY TL/tl.py") -> dict[str, Any]:
    found = []
    for root in roots():
        found.append(
            {
                "folder": str(root),
                "history": [
                    {**collection.__dict__, "import_command": import_command(collection, launcher)}
                    for collection in collections(root)
                ],
            }
        )
    return {"installs": found, "services": services()}


# ---- keep a copy, then remove ------------------------------------------------------


def archive(target: Path, home: Path) -> list[dict[str, Any]]:
    target.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    records = _load_records(home)
    made = []
    for root in roots():
        destination = target / f"{root.name}-old-install-{platform.node() or 'computer'}-{stamp}.tar"
        files = size = 0
        with tarfile.open(destination, "w") as archive_file:
            archive_file.add(root, arcname=root.name)
            for service in services():
                if service.get("file"):
                    archive_file.add(service["file"], arcname=f"services/{Path(service['file']).name}")
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                files += 1
                size += path.stat().st_size
        # Read the archive back: every file of the folder must be in it, at its size.
        listed = listed_size = 0
        with tarfile.open(destination, "r") as archive_file:
            for member in archive_file:
                if member.isfile() and member.name.startswith(f"{root.name}/"):
                    listed += 1
                    listed_size += member.size
        if (listed, listed_size) != (files, size):
            raise RuntimeError(f"archive of {root} does not match the folder ({listed}/{files} files)")
        record = {"folder": str(root), "archive": str(destination), "files": files, "bytes": size, "at": time.time()}
        records[str(root)] = record
        made.append(record)
    _save_records(home, records)
    return made


def remove(home: Path, without_backup: bool = False) -> list[str]:
    records = _load_records(home)
    pending = [str(root) for root in roots() if str(root) not in records]
    if pending and not without_backup:
        raise SystemExit("not archived yet: " + ", ".join(pending) + " (run `old-install archive --to FOLDER` first)")
    removed = stop()
    for service in services():
        if service.get("file"):
            Path(service["file"]).unlink(missing_ok=True)
        elif service["kind"] == "scheduled_task":
            _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                  f"Unregister-ScheduledTask -TaskName '{service['name']}' -Confirm:$false -ErrorAction SilentlyContinue"])
        removed.append(f"service {service['name']}")
    for root in roots():
        shutil.rmtree(root, ignore_errors=True)
        removed.append(("still present (in use?): " if root.exists() else "folder ") + str(root))
    return removed


def _load_records(home: Path) -> dict[str, Any]:
    try:
        data = json.loads((home / ARCHIVE_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_records(home: Path, records: dict[str, Any]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / ARCHIVE_RECORD).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
