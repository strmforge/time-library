"""What the client remembers on disk: who it is paired with, and how far it has read.

It never stores dialogue. If this state is lost, the client asks the server
how far it got and carries on from there.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any


def client_home() -> Path:
    override = os.environ.get("TL_CLIENT_HOME")
    return Path(override).expanduser() if override else Path.home() / ".time-library-client"


def _atomic_write_json(path: Path, payload: dict[str, Any], *, private: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # Windows: a virus scanner or indexer can hold the file for a moment.
                if attempt == 19:
                    raise
                time.sleep(0.25)
    finally:
        if tmp.exists():
            tmp.unlink()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class State:
    def __init__(self, home: str | os.PathLike[str] | None = None) -> None:
        self.home = Path(home) if home else client_home()
        self.config_path = self.home / "client.json"
        self.progress_path = self.home / "progress.json"
        self.config: dict[str, Any] = _load_json(self.config_path)
        self.progress: dict[str, dict[str, int]] = _load_json(self.progress_path)
        self.config.setdefault("agents", {})

    @property
    def paired(self) -> bool:
        return bool(self.config.get("server_url") and self.config.get("device_token"))

    def save_config(self) -> None:
        # Holds the device token, so readable by this user only.
        _atomic_write_json(self.config_path, self.config, private=True)

    def save_progress(self) -> None:
        _atomic_write_json(self.progress_path, self.progress, private=False)


def _run(command: list[str]) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _raw_machine_id() -> str:
    system = platform.system()
    if system == "Darwin":
        match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', _run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]))
        return match.group(1) if match else ""
    if system == "Windows":
        output = _run(["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"])
        match = re.search(r"MachineGuid\s+REG_SZ\s+(\S+)", output)
        return match.group(1) if match else ""
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            value = Path(candidate).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def machine_uid() -> str:
    """A stable id for this computer, so a reinstalled client is the same device.

    Derived from the operating system's machine id and hashed, so the id itself
    never leaves the computer. Falls back to a random id if none is available.
    """
    raw = _raw_machine_id()
    if not raw:
        return uuid.uuid4().hex
    return hashlib.sha256(f"time-library-client:{raw}".encode("utf-8")).hexdigest()[:32]


def default_device_name() -> str:
    if platform.system() == "Darwin":
        name = _run(["scutil", "--get", "ComputerName"]).strip()
        if name:
            return name
    return platform.node() or "unnamed-computer"


def os_label() -> str:
    return {"Darwin": "macOS"}.get(platform.system(), platform.system() or "unknown")
