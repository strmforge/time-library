"""Time Library in its container: starts the server, and lets it be updated without a new image.

This is the container's first process. It runs the server from one of two places:

- the code in the image (/app), or
- a newer version the server fetched into the data folder (/data/app/versions/<version>/), which the
  owner asked for on the admin's "update" button.

A fetched version first runs on trial: it must answer its health check as the version it is meant to be,
and keep answering. If it does not, the launcher goes back to the version before by itself, and says so
in the state file, which the admin page shows. The newest of image and fetched version runs, so pulling
a newer image later simply takes over. Nothing here reads or changes the owner's data.

It uses only the Python standard library and lives outside the code it starts, so that an update can
never break what brings it back. Its contract with the server is the state file and exit code RESTART.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RESTART = 75  # the server's exit code for "start me again" (an update or going back was asked for)
TRIAL_SECONDS = 300  # how long a new version may take to answer (a large library starts slowly)
STABLE_SECONDS = 20  # and then keep answering
GRACE_SECONDS = 90  # a server that was asked to restart but does not stop is ended
STOP_SECONDS = 30
CRASHES_ALLOWED = 5  # of a fetched version within CRASH_WINDOW before going back
CRASH_WINDOW = 600
KEEP_HISTORY = 20
POLL = 0.5


def version_of(text: str) -> tuple[int, ...] | None:
    """'2026.11.24' -> (2026, 11, 24); None for anything else."""
    if not isinstance(text, str) or not re.fullmatch(r"\d{1,6}(\.\d{1,6}){1,5}", text):
        return None
    return tuple(int(part) for part in text.split("."))


def version_in(code: Path) -> str:
    """The SERVER_VERSION written in a code folder, without running any of it."""
    try:
        text = (code / "tl_server" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    found = re.search(r'^SERVER_VERSION = "([^"]+)"', text, re.MULTILINE)
    return found.group(1) if found else ""


def intact(code: Path) -> bool:
    """Whether a fetched version is exactly what was fetched and checked (see tl_server/update.py)."""
    try:
        listed = json.loads((code / "manifest.json").read_text(encoding="utf-8"))["files"]
        present = {path.relative_to(code).as_posix() for path in code.rglob("*")
                   if path.is_file() and "__pycache__" not in path.parts} - {"manifest.json"}
        if set(listed) != present:
            return False
        return all(hashlib.sha256((code / name).read_bytes()).hexdigest() == digest for name, digest in listed.items())
    except (OSError, ValueError, KeyError, TypeError):
        return False


class State:
    """/data/app/state.json, shared with the server; always replaced whole."""

    def __init__(self, data_dir: Path) -> None:
        self.folder = Path(data_dir) / "app"
        self.path = self.folder / "state.json"

    def read(self) -> dict:
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        for key in ("current", "previous", "trial"):
            if not isinstance(state.get(key), str):
                state[key] = ""
        for key in ("bad", "history"):
            if not isinstance(state.get(key), list):
                state[key] = []
        return state

    def write(self, state: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        partial = self.path.with_suffix(".json.part")
        partial.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(partial, self.path)

    def code(self, version: str) -> Path:
        return self.folder / "versions" / version


class Launcher:
    def __init__(self, image: Path, data_dir: Path, port: int, command: list[str] | None = None, args: list[str] | None = None) -> None:
        self.image = Path(image)
        self.state = State(data_dir)
        self.port = port
        self.command = [*(command or [sys.executable, "-m", "tl_server"]), *(args or [])]
        self.child: subprocess.Popen | None = None
        self.stopping = False
        self._crashes: list[float] = []
        # A proxy set for the container must not be asked for the server on this machine.
        self._direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # ---- which code runs -----------------------------------------------------

    def choose(self) -> tuple[Path, str]:
        """(folder, version) to run: a fetched version if it is newer than the image and intact, else the image."""
        image_version = version_in(self.image)
        if os.environ.get("TL_USE_IMAGE") == "1":  # the owner asked for the image's own version (say, to go back to it)
            return self.image, image_version
        state = self.state.read()
        current = state["current"]
        wanted = version_of(current)
        if wanted is None or current in state["bad"]:
            return self.image, image_version
        have = version_of(image_version)
        if have is not None and wanted <= have:
            return self.image, image_version  # a newer (or the same) image was pulled since
        code = self.state.code(current)
        if version_in(code) != current or not intact(code):
            self._settle(current, False, "这一版的文件不完整,没有用它")
            return self.choose()
        return code, current

    def _settle(self, version: str, ok: bool, note: str = "") -> None:
        """Record how a fetched version turned out; when it did not work, go back to the one before."""
        state = self.state.read()
        state["history"] = (state["history"] + [{"at": time.time(), "version": version, "ok": ok, "note": note}])[-KEEP_HISTORY:]
        if not ok:
            if version not in state["bad"]:
                state["bad"].append(version)
            state["current"] = state["previous"] if state["previous"] != version else ""
            state["previous"] = ""
        state["trial"] = ""
        state.pop("restart_at", None)
        self.state.write(state)

    # ---- running it ----------------------------------------------------------

    def _spawn(self, code: Path) -> None:
        env = dict(os.environ, PYTHONPATH=str(code), TL_LAUNCHER="1", TL_APP_DIR=str(code), TL_IMAGE_DIR=str(self.image))
        self.child = subprocess.Popen(self.command, cwd=str(code), env=env)

    def _reap(self) -> int | None:
        """The server's exit code once it has ended; also collects anything it left behind (we are process 1)."""
        assert self.child is not None
        if os.getpid() != 1:
            return self.child.poll()
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return self.child.returncode if self.child.returncode is not None else 0
            if pid == 0:
                return None
            if pid == self.child.pid:
                self.child.returncode = os.waitstatus_to_exitcode(status)
                return self.child.returncode

    def _end_child(self, seconds: float = STOP_SECONDS) -> int:
        """Ask the server to stop, then make it stop; its exit code."""
        assert self.child is not None
        code = self._reap()
        if code is not None:
            return code
        for sign, wait in ((signal.SIGTERM, seconds), (signal.SIGKILL, 10.0)):
            try:
                self.child.send_signal(sign)
            except OSError:
                pass
            until = time.monotonic() + wait
            while time.monotonic() < until:
                code = self._reap()
                if code is not None:
                    return code
                time.sleep(POLL)
        return -9

    def _health(self) -> dict:
        try:
            with self._direct.open(f"http://127.0.0.1:{self.port}/api/v1/health", timeout=5) as response:
                body = json.loads(response.read(4096))
            return body if isinstance(body, dict) else {}
        except (OSError, ValueError):
            return {}

    def run(self) -> int:
        """Until the container is stopped. Returns the exit code for the container."""
        while not self.stopping:
            code, version = self.choose()
            fetched = code != self.image
            trial = fetched and self.state.read()["trial"] == version
            state = self.state.read()
            if "restart_at" in state:
                state.pop("restart_at")
                self.state.write(state)
            self._say(f"starting {version or '(unknown version)'} from {'the data folder' if fetched else 'the image'}"
                      + (" on trial" if trial else ""))
            self._spawn(code)
            result = self._watch(version, trial)
            if self.stopping:
                return 0 if result is None else result
            if result == RESTART:
                self._crashes.clear()
                continue
            if fetched:
                if trial:
                    continue  # _watch went back already
                now = time.monotonic()
                self._crashes = [at for at in self._crashes if now - at < CRASH_WINDOW] + [now]
                if len(self._crashes) >= CRASHES_ALLOWED:
                    self._say(f"{version} keeps ending: going back")
                    self._settle(version, False, "连着退出好几次,已退回上一版")
                    self._crashes.clear()
                time.sleep(2)
                continue
            return result  # the image's own code ended: Docker's restart policy starts us again
        return 0

    def _watch(self, version: str, trial: bool) -> int | None:
        """Wait for the server to end (its exit code). While on trial, judge it."""
        started = time.monotonic()
        good_since: float | None = None
        looked = 0.0
        while True:
            code = self._reap()
            if code is not None:
                if trial and code != RESTART and not self.stopping:
                    self._say(f"{version} ended while on trial (exit code {code}): going back")
                    self._settle(version, False, f"启动后自己退出了(退出码 {code}),已退回上一版")
                return code
            if self.stopping:
                return self._end_child()
            now = time.monotonic()
            if trial and now - looked >= 2:
                looked = now
                body = self._health()
                if body.get("ok") is True and body.get("version") == version:
                    good_since = good_since or now
                    if now - good_since >= STABLE_SECONDS:
                        self._say(f"{version} works")
                        self._settle(version, True)
                        trial = False
                else:
                    good_since = None
                if trial and now - started > TRIAL_SECONDS:
                    self._say(f"{version} did not answer in {TRIAL_SECONDS} s: going back")
                    self._settle(version, False, f"{TRIAL_SECONDS} 秒内没有正常答复,已退回上一版")
                    self._end_child()
                    return RESTART
            elif now - looked >= 5:
                looked = now
                asked = self.state.read().get("restart_at")
                if isinstance(asked, (int, float)) and time.time() - asked > GRACE_SECONDS:
                    self._say("asked to restart but still running: ending it")
                    self._end_child()
                    return RESTART
            time.sleep(POLL)

    def stop(self, *_args) -> None:
        self.stopping = True

    @staticmethod
    def _say(text: str) -> None:
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} launcher {text}", flush=True)


def main() -> int:
    launcher = Launcher(
        Path(os.environ.get("TL_IMAGE_DIR", "/app")),
        Path(os.environ.get("TL_DATA_DIR", "/data")),
        int(os.environ.get("TL_PORT", "9850")),
        args=sys.argv[1:],
    )
    signal.signal(signal.SIGTERM, launcher.stop)
    signal.signal(signal.SIGINT, launcher.stop)
    return launcher.run()


if __name__ == "__main__":
    sys.exit(main())
