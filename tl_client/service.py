"""Keep the client running in the background: one service per operating system.

The same few lines for every agent; what differs is only the operating system's
own way to start a program at login and keep it running.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

LABEL = "com.timelibrary.client"
TASK_NAME = "TimeLibraryClient"
UNIT_NAME = "time-library-client.service"


def app_dir() -> Path:
    """The folder that holds the tl_client package."""
    return Path(__file__).resolve().parent.parent


def background_python() -> str:
    """On Windows, pythonw.exe runs without a console window."""
    if platform.system() == "Windows":
        candidate = Path(sys.executable).with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return sys.executable


def run_arguments(log: Path) -> list[str]:
    return [background_python(), "-m", "tl_client", "run", "--interval", "15", "--log", str(log)]


def macos_plist(log: Path) -> str:
    args = "\n".join(f"    <string>{_xml(arg)}</string>" for arg in run_arguments(log))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>WorkingDirectory</key>
  <string>{_xml(str(app_dir()))}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
"""


def systemd_unit(log: Path) -> str:
    command = " ".join(_systemd_quote(arg) for arg in run_arguments(log))
    return f"""[Unit]
Description=Time Library client (uploads agent dialogue to the Time Library server)

[Service]
WorkingDirectory={app_dir()}
ExecStart={command}
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
"""


def windows_script(log: Path) -> str:
    python, *rest = run_arguments(log)
    arguments = " ".join(f'"{arg}"' if " " in arg else arg for arg in rest)
    return (
        # Installing again (another Python, say): the running instance stops first, with the worker it started,
        # or the task would ignore the new start and keep the old one running.
        f"Stop-ScheduledTask -TaskName {_ps(TASK_NAME)} -ErrorAction SilentlyContinue\n"
        "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Where-Object { $_.CommandLine -like '*tl_client*run*--worker*' } "
        "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }\n"
        f"$action = New-ScheduledTaskAction -Execute {_ps(python)} -Argument {_ps(arguments)} -WorkingDirectory {_ps(str(app_dir()))}\n"
        "$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME\n"
        "$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) "
        "-MultipleInstances IgnoreNew -StartWhenAvailable\n"
        # The bare user name: "DOMAIN\\user" can fail to map over remote sessions.
        "$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited\n"
        f"Register-ScheduledTask -TaskName {_ps(TASK_NAME)} -Action $action -Trigger $trigger -Settings $settings "
        "-Principal $principal -Description 'Time Library client: uploads agent dialogue to the server' -Force -ErrorAction Stop | Out-Null\n"
        f"Start-ScheduledTask -TaskName {_ps(TASK_NAME)}\n"
    )


def install(home: Path) -> str:
    log = home / "client.log"
    home.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True, check=False)
        path.write_text(macos_plist(log), encoding="utf-8")
        subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True, capture_output=True)
        return f"started at login by launchd ({path})"
    if system == "Windows":
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", windows_script(log)],
            check=True, capture_output=True,
        )
        return f"started at login by Task Scheduler (task {TASK_NAME})"
    path = Path.home() / ".config" / "systemd" / "user" / UNIT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(systemd_unit(log), encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", UNIT_NAME], check=True, capture_output=True)
    return f"started at login by systemd --user ({path})"


def uninstall() -> str:
    system = platform.system()
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, check=False)
        path.unlink(missing_ok=True)
        return "background client removed"
    if system == "Windows":
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"Stop-ScheduledTask -TaskName {_ps(TASK_NAME)} -ErrorAction SilentlyContinue; "
             f"Unregister-ScheduledTask -TaskName {_ps(TASK_NAME)} -Confirm:$false -ErrorAction SilentlyContinue"],
            capture_output=True, check=False,
        )
        return "background client removed"
    subprocess.run(["systemctl", "--user", "disable", "--now", UNIT_NAME], capture_output=True, check=False)
    (Path.home() / ".config" / "systemd" / "user" / UNIT_NAME).unlink(missing_ok=True)
    return "background client removed"


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ps(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _systemd_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"' if any(c in text for c in ' "\\') else text
