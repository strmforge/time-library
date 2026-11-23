"""Updating the server from the admin page, without pulling a new Docker image.

Nearly all of the image is Python and libraries that rarely change; the server's own code is its last
layer, well under a megabyte. So an update fetches just that layer of the newer published image from the
registry, checks it (every step is named by the sha256 of what it must be), puts it in the data folder,
and asks the launcher (deploy/nas/launcher.py) to start from it. The launcher runs it on trial and goes
back by itself when it does not work. A version that needs newer libraries than this image carries says
so, and then the image has to be pulled once.

What went wrong in the earlier version is the bar here: a check that fails says that it failed, never
"up to date"; an update counts only once the new version itself answered as that version; and only the
program is replaced, the library is left alone (schema changes only ever add).

It asks api.github.com which release is newest (no identifiers, only when the owner looks or clicks) and
ghcr.io for the layer. Both are fixed; there is nothing to configure.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from . import SERVER_VERSION
from .errors import ApiError

log = logging.getLogger("tl_server.update")

# Only tests and the repository's own smoke checks point these elsewhere.
RELEASES_URL = os.environ.get("TL_UPDATE_API") or "https://api.github.com/repos/strmforge/time-library/releases/latest"
REGISTRY = os.environ.get("TL_UPDATE_REGISTRY") or "https://ghcr.io"
IMAGE = "strmforge/time-library-server"
RUNTIME_LABEL = "org.time-library.runtime"

CHECK_EVERY = 6 * 3600  # looking at the page checks again after this long
REQUEST_TIMEOUT = 30
TRIES = 3
LAYER_MAX = 20 * 1024 * 1024
UNPACKED_MAX = 60 * 1024 * 1024
FILES_MAX = 2000
ALLOWED = ("app/tl_server/", "app/tl_client/", "app/system/skills/time-library/")
PARENTS = {"app", "app/tl_server", "app/tl_client", "app/system", "app/system/skills", "app/system/skills/time-library"}
IMPORT_SECONDS = 120
INDEX = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"


class UpdateError(Exception):
    """What went wrong, in words the owner reads."""


class _Redirects(urllib.request.HTTPRedirectHandler):
    """The registry sends downloads on to another host: the pull permission is not passed along."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        onward = super().redirect_request(request, fp, code, msg, headers, newurl)
        if onward is not None and urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(request.full_url).hostname:
            onward.remove_header("Authorization")
        return onward


def version_of(text: Any) -> tuple[int, ...] | None:
    if not isinstance(text, str) or not re.fullmatch(r"\d{1,6}(\.\d{1,6}){1,5}", text):
        return None
    return tuple(int(part) for part in text.split("."))


def newer(a: str, b: str) -> bool:
    x, y = version_of(a), version_of(b)
    return x is not None and y is not None and x > y


class Updater:
    def __init__(self, data_dir: Path | str, restart: Callable[[], None], clock: Callable[[], float] = time.time) -> None:
        self._folder = Path(data_dir) / "app"
        self._state_path = self._folder / "state.json"
        self._restart = restart
        self._clock = clock
        self._lock = threading.Lock()
        self._busy = False
        self._progress: dict[str, Any] = {}
        self._checked_at: float | None = None
        self._error = ""
        self._latest: dict[str, Any] | None = None
        self._failure: dict[str, Any] | None = None
        self._open = urllib.request.build_opener(_Redirects())  # a proxy set for the container is used

    # ---- what the page shows ---------------------------------------------------

    @property
    def supported(self) -> bool:
        """Only when the container's launcher started this server: it is what makes an update safe."""
        return os.environ.get("TL_LAUNCHER") == "1"

    def status(self) -> dict[str, Any]:
        state = self._state()
        with self._lock:
            latest = dict(self._latest) if self._latest else None
            status: dict[str, Any] = {
                "supported": self.supported,
                "version": SERVER_VERSION,
                "image_version": self._image_version(),
                "checked_at": self._checked_at,
                "error": self._error,
                "latest": latest,
                "available": bool(latest and newer(latest["version"], SERVER_VERSION)),
                "busy": self._busy,
                "progress": dict(self._progress),
                "failure": self._failure,
            }
        status["bad"] = state["bad"]
        status["previous"] = state["previous"] if state["previous"] else ("" if state["current"] else None)
        status["can_go_back"] = bool(self.supported and state["current"] == SERVER_VERSION and not state["trial"])
        status["last"] = state["history"][-1] if state["history"] else None
        status["on_trial"] = bool(state["trial"])
        return status

    def check(self, force: bool = True) -> dict[str, Any]:
        """Ask which release is newest. A failure is kept and shown as a failure."""
        if not force and self._checked_at and self._clock() - self._checked_at < CHECK_EVERY:
            return self.status()
        try:
            raw = self._get(RELEASES_URL, {"Accept": "application/vnd.github+json"}, limit=2 * 1024 * 1024)
            release = json.loads(raw)
            tag = str(release.get("tag_name") or "")
            version = tag[1:] if tag[:1] in "vV" else tag
            if version_of(version) is None:
                raise UpdateError(f"最新版的版本号认不出来:{tag[:40]}")
            latest = {
                "version": version,
                "notes": str(release.get("body") or "")[:20000],
                "published_at": str(release.get("published_at") or ""),
                "url": str(release.get("html_url") or ""),
            }
            if newer(version, SERVER_VERSION) and self.supported:
                # Whether this image can run it is known before the owner clicks.
                try:
                    self._look(version)
                except UpdateError as error:
                    latest["problem"] = str(error)
            with self._lock:
                self._latest, self._error, self._checked_at = latest, "", self._clock()
        except (UpdateError, ValueError, AttributeError) as error:
            reason = str(error) if isinstance(error, UpdateError) else "GitHub 的答复看不懂"
            with self._lock:
                self._error, self._checked_at = reason, self._clock()
        return self.status()

    # ---- updating --------------------------------------------------------------

    def start(self) -> dict[str, Any]:
        if not self.supported:
            raise ApiError(409, "update_not_supported", "这台服务端不是由容器的启动器启动的,不能在这里更新。")
        with self._lock:
            if self._busy:
                raise ApiError(409, "update_busy", "正在更新,等这次结束。")
            latest = self._latest
            if not latest or not newer(latest["version"], SERVER_VERSION):
                raise ApiError(409, "nothing_to_update", "没有比现在更新的版本。先点「检查更新」。")
            if latest.get("problem"):
                raise ApiError(409, "update_needs_image" if latest["problem"] == "needs_image" else "update_not_possible",
                               "这一版要用新镜像:在 NAS 上运行 docker compose pull && docker compose up -d。"
                               if latest["problem"] == "needs_image" else latest["problem"])
            if latest["version"] in self._state()["bad"]:
                raise ApiError(409, "update_failed_before", "这一版之前试过,没能正常运行,已经退回。等下一版。")
            self._busy, self._failure = True, None
            self._progress = {"step": "look", "done": 0, "total": 0}
        threading.Thread(target=self._run, args=(latest["version"],), daemon=True, name="update").start()
        return self.status()

    def _run(self, version: str) -> None:
        try:
            code = self._fetch(version)
            self._install(version, code)
        except UpdateError as error:
            log.warning("update to %s stopped: %s", version, error)
            self._failed(version, str(error))
        except Exception as error:  # noqa: BLE001 - anything else is also "not updated", never half-updated
            log.exception("update to %s stopped", version)
            self._failed(version, f"没想到的错误:{type(error).__name__}")

    def _failed(self, version: str, reason: str) -> None:
        shutil.rmtree(self._folder / "incoming", ignore_errors=True)
        with self._lock:
            self._busy, self._progress = False, {}
            self._failure = {"version": version, "reason": reason, "at": self._clock()}

    def go_back(self) -> dict[str, Any]:
        """Back to the version before this one (or the image's), at the owner's word."""
        if not self.supported:
            raise ApiError(409, "update_not_supported", "这台服务端不是由容器的启动器启动的,不能在这里更新。")
        state = self._state()
        if state["current"] != SERVER_VERSION or state["trial"]:
            raise ApiError(409, "nothing_to_go_back", "没有可以退回的上一版。")
        with self._lock:
            if self._busy:
                raise ApiError(409, "update_busy", "正在更新,等这次结束。")
            self._busy = True
            self._progress = {"step": "restart", "done": 0, "total": 0}
        state["current"], state["previous"] = state["previous"], ""
        state["trial"] = state["current"]
        state["restart_at"] = self._clock()
        state["history"] = (state["history"] + [{"at": self._clock(), "version": SERVER_VERSION, "ok": False,
                                                 "by": "owner", "note": ""}])[-20:]
        self._write(state)
        self._restart()
        return self.status()

    # ---- fetching and checking ----------------------------------------------------

    def _step(self, step: str, done: int = 0, total: int = 0) -> None:
        with self._lock:
            self._progress = {"step": step, "done": done, "total": total}

    def _look(self, version: str) -> tuple[str, dict]:
        """(pull permission, the layer that is the server's code) of a published version, if this image can run it."""
        token = self._token()
        machine = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower(), "")
        index = self._manifest(version, token, INDEX + ", " + MANIFEST)
        chosen = index
        if "manifests" in index:  # one image per kind of machine; without this list there is only the one
            fits = [entry for entry in index["manifests"]
                    if entry.get("platform", {}).get("os") == "linux" and entry.get("platform", {}).get("architecture") == machine]
            if not machine or not fits:
                raise UpdateError("这台机器的芯片没有对应的版本。")
            chosen = self._manifest(str(fits[0].get("digest") or ""), token, MANIFEST)
        layers = chosen.get("layers")
        config = chosen.get("config")
        if not isinstance(layers, list) or not layers or not isinstance(config, dict):
            raise UpdateError("这一版的镜像内容看不懂。")
        settings = json.loads(self._blob(config, token, 1024 * 1024))
        if isinstance(settings, dict) and settings.get("architecture") != machine:
            raise UpdateError("这台机器的芯片没有对应的版本。")
        self._check_runtime(settings)
        layer = layers[-1]
        kind = str(layer.get("mediaType") or "")
        if not kind.endswith(("tar+gzip", "tar.gzip")):
            raise UpdateError("这一版的打包方式不认识,请用新镜像更新。")
        size = layer.get("size")
        if not isinstance(size, int) or not 0 < size <= LAYER_MAX:
            raise UpdateError("这一版的程序大小不对,没有下载。")
        return token, layer

    def _fetch(self, version: str) -> Path:
        """The newer version's code, fetched, checked against the registry's digests and unpacked. Returns its folder."""
        self._step("look")
        token, layer = self._look(version)
        data = self._blob(layer, token, LAYER_MAX, say=True)
        self._step("check")
        incoming = self._folder / "incoming"
        shutil.rmtree(incoming, ignore_errors=True)
        code = incoming / version
        self._unpack(data, code)
        self._record(code, version)
        self._prove(code, version)
        return code

    @staticmethod
    def _check_runtime(settings: dict) -> None:
        labels = ((settings.get("config") or {}).get("Labels") or {}) if isinstance(settings, dict) else {}
        try:
            needs, have = int(labels.get(RUNTIME_LABEL) or ""), int(os.environ.get("TL_RUNTIME") or "")
        except ValueError:
            raise UpdateError("这一版没有标明需要的运行环境,请用新镜像更新。") from None
        if needs > have:
            raise UpdateError("needs_image")  # the page says how

    def _manifest(self, reference: str, token: str, accept: str) -> dict:
        url = f"{REGISTRY}/v2/{IMAGE}/manifests/{urllib.parse.quote(reference, safe=':')}"
        raw = self._get(url, {"Accept": accept, "Authorization": f"Bearer {token}"}, limit=1024 * 1024)
        if reference.startswith("sha256:") and hashlib.sha256(raw).hexdigest() != reference[7:]:
            raise UpdateError("镜像清单和登记的不一致,没有更新。")
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise UpdateError("镜像清单看不懂。")
        return body

    def _token(self) -> str:
        scope = urllib.parse.quote(f"repository:{IMAGE}:pull", safe="")
        raw = self._get(f"{REGISTRY}/token?service=ghcr.io&scope={scope}", {}, limit=64 * 1024)
        try:
            token = json.loads(raw)["token"]
        except (ValueError, KeyError, TypeError):
            raise UpdateError("登记处没有答复许可。") from None
        return str(token)

    def _blob(self, entry: dict, token: str, limit: int, say: bool = False) -> bytes:
        """One piece of the image, checked against the sha256 it is named by."""
        digest = str(entry.get("digest") or "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise UpdateError("镜像清单里的编号不对。")
        size = entry.get("size") if isinstance(entry.get("size"), int) else 0
        url = f"{REGISTRY}/v2/{IMAGE}/blobs/{digest}"
        progress = (lambda done: self._step("download", done, size)) if say else None
        raw = self._get(url, {"Authorization": f"Bearer {token}"}, limit=limit, progress=progress)
        if hashlib.sha256(raw).hexdigest() != digest[7:]:
            raise UpdateError("下载到的内容和登记的不一致,没有更新。")
        return raw

    def _get(self, url: str, headers: dict, limit: int, progress: Callable[[int], None] | None = None) -> bytes:
        for attempt in range(1, TRIES + 1):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "time-library-server", **headers})
                with self._open.open(request, timeout=REQUEST_TIMEOUT) as response:
                    parts, total = [], 0
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            return b"".join(parts)
                        total += len(chunk)
                        if total > limit:
                            raise UpdateError("收到的内容太大,没有更新。")
                        parts.append(chunk)
                        if progress:
                            progress(total)
            except UpdateError:
                raise
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    raise UpdateError("登记处里没有这一版。") from None
                reason = f"登记处答复 {error.code}"
            except (OSError, ValueError) as error:
                reason = "连不上(" + (str(getattr(error, "reason", "")) or type(error).__name__)[:80] + ")"
            if attempt < TRIES:
                time.sleep(attempt * 2)
        raise UpdateError(f"{urllib.parse.urlsplit(url).hostname} {reason}。现在的版本照常运行,稍后再试。")

    @staticmethod
    def _unpack(data: bytes, code: Path) -> None:
        """Only ordinary files under the three code folders; anything else refuses the whole package."""
        code.mkdir(parents=True)
        total = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data)), mode="r:") as archive:
                members = archive.getmembers()
                if len(members) > FILES_MAX:
                    raise UpdateError("更新包里的文件太多,没有更新。")
                for member in members:
                    name = member.name.rstrip("/")
                    path = PurePosixPath(name)
                    if path.is_absolute() or ".." in path.parts or "\\" in name or path.name.startswith(".wh."):
                        raise UpdateError("更新包里有不该有的路径,没有更新。")
                    if member.isdir():
                        if name not in PARENTS and not name.startswith(ALLOWED):
                            raise UpdateError("更新包里有不该有的文件夹,没有更新。")
                        continue
                    if not member.isreg() or not name.startswith(ALLOWED):
                        raise UpdateError("更新包里有不该有的文件,没有更新。")
                    total += member.size
                    if total > UNPACKED_MAX:
                        raise UpdateError("更新包解开后太大,没有更新。")
                    target = code / PurePosixPath(*path.parts[1:])  # without the leading app/
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    assert source is not None
                    target.write_bytes(source.read())
        except (tarfile.TarError, OSError, EOFError) as error:
            raise UpdateError(f"更新包解不开({type(error).__name__})。") from None

    @staticmethod
    def _record(code: Path, version: str) -> None:
        """What was fetched, so the launcher can tell that it is still exactly that."""
        files = {path.relative_to(code).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(code.rglob("*")) if path.is_file()}
        (code / "manifest.json").write_text(json.dumps({"version": version, "files": files}, indent=1), encoding="utf-8")

    @staticmethod
    def _prove(code: Path, version: str) -> None:
        """It must at least load here and be the version it says, before anything is switched."""
        probe = ("import sys; sys.path.insert(0, sys.argv[1]); import tl_server, tl_server.app, tl_client; "
                 "print(tl_server.SERVER_VERSION)")
        try:
            done = subprocess.run([sys.executable, "-I", "-B", "-c", probe, str(code)], capture_output=True, text=True,
                                  timeout=IMPORT_SECONDS, cwd=str(code))
        except subprocess.TimeoutExpired:
            raise UpdateError("新版本在这里载入得太久,没有更新。") from None
        if done.returncode != 0 or done.stdout.strip() != version:
            log.warning("update %s does not load here: %s", version, (done.stderr or done.stdout)[-500:])
            raise UpdateError("新版本在这台机器上载入不了,没有更新。")

    def _install(self, version: str, code: Path) -> None:
        """Put it beside the running one, and ask the launcher to start from it, on trial."""
        self._step("switch")
        target = self._folder / "versions" / version
        shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(code, target)
        shutil.rmtree(self._folder / "incoming", ignore_errors=True)
        state = self._state()
        running = state["current"] if state["current"] == SERVER_VERSION else ""
        for old in target.parent.iterdir():  # keep this one and the one to go back to
            if old.name not in (version, running):
                shutil.rmtree(old, ignore_errors=True)
        state.update({"current": version, "previous": running, "trial": version, "restart_at": self._clock()})
        self._write(state)
        log.info("updating from %s to %s", SERVER_VERSION, version)
        self._step("restart")
        self._restart()

    # ---- the state file, shared with the launcher ----------------------------------

    def _state(self) -> dict[str, Any]:
        try:
            state = json.loads(self._state_path.read_text(encoding="utf-8"))
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

    def _write(self, state: dict[str, Any]) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        partial = self._state_path.with_suffix(".json.part")
        partial.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(partial, self._state_path)

    @staticmethod
    def _image_version() -> str:
        try:
            text = (Path(os.environ.get("TL_IMAGE_DIR", "")) / "tl_server" / "__init__.py").read_text(encoding="utf-8")
        except OSError:
            return ""
        found = re.search(r'^SERVER_VERSION = "([^"]+)"', text, re.MULTILINE)
        return found.group(1) if found else ""
