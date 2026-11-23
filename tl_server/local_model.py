"""The built-in local model: nothing for the owner to install or run.

The server image carries a model runtime (llama.cpp's llama-server). When the
owner switches the local model on, the server downloads the model file itself
(resumable, checked against a known hash), runs the runtime as its own child
process, and registers it as a model source like any other. The runtime loads
the model into memory when it is needed and releases it after a while idle.

Nothing here is specific to one NAS: the catalog is data, and the download
tries the usual host first and a mirror second.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .errors import ApiError
from .model_registry import ModelRegistry
from .store import Store

log = logging.getLogger("tl_server.local_model")

LLAMA_DIR = os.environ.get("TL_LLAMA_DIR", "/opt/llama")
PORT = int(os.environ.get("TL_LLAMA_PORT", "18080"))
HOSTS = tuple(
    host.strip().rstrip("/")
    for host in os.environ.get("TL_MODEL_HOSTS", "https://huggingface.co,https://hf-mirror.com").split(",")
    if host.strip()
)
CONTEXT_TOKENS = 16384
IDLE_SECONDS = 600
START_TIMEOUT = 180
SOURCE_NAME = "本机模型"

CATALOG: list[dict[str, Any]] = [
    {
        "id": "qwen3-4b",
        "label": "Qwen3 4B",
        "repo": "unsloth/Qwen3-4B-GGUF",
        "file": "Qwen3-4B-Q4_K_M.gguf",
        "bytes": 2497281312,
        "sha256": "f6f851777709861056efcdad3af01da38b31223a3ba26e61a4f8bf3a2195813a",
        "ram_bytes": 5 * 1024**3,
    },
]

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _available_memory() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


class LocalModel:
    def __init__(self, store: Store, models: ModelRegistry) -> None:
        self._store = store
        self._models = models
        self._dir = store.data_dir / "models"
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._phase = "off"  # off | downloading | verifying | starting | ready | error
        self._error = ""
        self._downloaded = 0
        self._speed = 0.0
        saved = store._meta("local_model")
        self._model_id = json.loads(saved)["model_id"] if saved else ""
        models.local = self

    # ---- facts -------------------------------------------------------------

    @property
    def _binary(self) -> Path:
        return Path(LLAMA_DIR) / "llama-server"

    @property
    def available(self) -> bool:
        return self._binary.is_file() and os.access(self._binary, os.X_OK)

    def _entry(self, model_id: str) -> dict[str, Any]:
        for entry in CATALOG:
            if entry["id"] == model_id:
                return entry
        raise ApiError(400, "invalid_field", "unknown local model")

    def _file(self, entry: dict[str, Any]) -> Path:
        return self._dir / entry["file"]

    def _save(self, model_id: str) -> None:
        self._model_id = model_id
        with self._store._tx() as db:
            if model_id:
                db.execute(
                    "INSERT INTO meta(key, value) VALUES('local_model', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (json.dumps({"model_id": model_id}),),
                )
            else:
                db.execute("DELETE FROM meta WHERE key='local_model'")

    def _source_id(self) -> int | None:
        with self._store._lock:
            row = self._store._db.execute("SELECT id FROM model_sources WHERE builtin=1").fetchone()
        return row["id"] if row else None

    def status(self) -> dict[str, Any]:
        with self._lock:
            entry = self._entry(self._model_id) if self._model_id else None
            part = self._file(entry).with_name(self._file(entry).name + ".part") if entry else None
            downloaded = self._downloaded
            if entry and self._phase in ("off", "error") and part and part.exists():
                downloaded = part.stat().st_size
            usage = None
            try:
                import shutil

                usage = shutil.disk_usage(self._store.data_dir).free
            except OSError:
                pass
            return {
                "available": self.available,
                "phase": self._phase,
                "error": self._error,
                "model_id": self._model_id,
                "downloaded_bytes": downloaded,
                "total_bytes": entry["bytes"] if entry else 0,
                "bytes_per_second": int(self._speed),
                "source_id": self._source_id(),
                "idle_seconds": IDLE_SECONDS,
                "memory_available_bytes": _available_memory(),
                "disk_free_bytes": usage,
                "catalog": [
                    {"id": item["id"], "label": item["label"], "bytes": item["bytes"], "ram_bytes": item["ram_bytes"]}
                    for item in CATALOG
                ],
            }

    # ---- switching on and off ------------------------------------------------

    def enable(self, model_id: Any) -> dict[str, Any]:
        if not self.available:
            raise ApiError(409, "local_model_unavailable", "this build does not include the model runtime")
        entry = self._entry(model_id if isinstance(model_id, str) else "")
        with self._lock:
            if self._worker and self._worker.is_alive():
                raise ApiError(409, "already_running")
            self._save(entry["id"])
            self._cancel.clear()
            self._error = ""
            self._phase = "starting" if self._file(entry).exists() else "downloading"
            self._worker = threading.Thread(target=self._bring_up, args=(entry,), daemon=True, name="local-model")
            self._worker.start()
        return self.status()

    def resume_on_boot(self) -> None:
        """After a restart: if the local model was on and its file is here, run it again."""
        if not (self.available and self._model_id):
            return
        try:
            entry = self._entry(self._model_id)
        except ApiError:
            return
        if self._file(entry).exists():
            self.enable(entry["id"])

    def cancel(self) -> dict[str, Any]:
        """Pause a download. What has arrived is kept, so switching on again resumes."""
        self._cancel.set()
        self.wait(30)
        with self._lock:
            if self._phase in ("downloading", "verifying"):
                self._phase = "off"
        return self.status()

    def remove(self) -> dict[str, Any]:
        self._cancel.set()
        self.wait(30)
        self._stop_process()
        with self._lock:
            source_id = self._source_id()
            if source_id is not None:
                self._models.delete_source(source_id, builtin_ok=True)
            if self._model_id:
                target = self._file(self._entry(self._model_id))
                for path in (target, target.with_name(target.name + ".part")):
                    try:
                        path.unlink()
                    except OSError:
                        pass
            self._save("")
            self._phase, self._error, self._downloaded = "off", "", 0
        return self.status()

    def wait(self, timeout: float = 120) -> None:
        worker = self._worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout)

    def shutdown(self) -> None:
        self._cancel.set()
        self._stop_process()

    # ---- the work ----------------------------------------------------------

    def _bring_up(self, entry: dict[str, Any]) -> None:
        try:
            target = self._file(entry)
            if not target.exists():
                self._download(entry, target)
                if self._cancel.is_set():
                    with self._lock:
                        self._phase = "off"
                    return
            with self._lock:
                self._phase = "starting"
            self._start_process(entry, target)
            source_id = self._register(entry)
            outcome = self._models.test_source(source_id)
            if not outcome["ok"]:
                raise RuntimeError(f"the model runtime started but did not answer ({outcome.get('reason')})")
            with self._lock:
                self._phase = "ready"
        except Exception as error:
            if not self._cancel.is_set():
                log.exception("local model could not be brought up")
            with self._lock:
                self._phase = "off" if self._cancel.is_set() else "error"
                self._error = "" if self._cancel.is_set() else str(error)[:300]

    def _open(self, entry: dict[str, Any], offset: int):
        last: Exception | None = None
        for host in HOSTS:
            request = urllib.request.Request(
                f"{host}/{entry['repo']}/resolve/main/{entry['file']}",
                headers=({"Range": f"bytes={offset}-"} if offset else {}) | {"User-Agent": "time-library-server"},
            )
            try:
                return _DIRECT.open(request, timeout=20)
            except (urllib.error.URLError, OSError, TimeoutError) as error:
                last = error
        raise RuntimeError(f"could not reach any model download host ({last})")

    def _download(self, entry: dict[str, Any], target: Path) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        failures = 0
        while not self._cancel.is_set():
            have = part.stat().st_size if part.exists() else 0
            if have > entry["bytes"]:
                part.unlink()
                have = 0
            if have == entry["bytes"]:
                break
            with self._lock:
                self._phase, self._downloaded = "downloading", have
            try:
                with self._open(entry, have) as response:
                    if have and response.status != 206:
                        have = 0  # the host ignored the range: start over
                    received = 0
                    mark_time, mark_bytes = time.monotonic(), 0
                    with part.open("ab" if have else "wb") as out:
                        while not self._cancel.is_set():
                            # read1 returns what has arrived, so progress and
                            # pausing respond at once even on a slow link.
                            chunk = response.read1(256 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                            received += len(chunk)
                            now = time.monotonic()
                            with self._lock:
                                self._downloaded = have + received
                                if now - mark_time >= 3:  # speed over the last few seconds, not since the start
                                    self._speed = (received - mark_bytes) / (now - mark_time)
                                    mark_time, mark_bytes = now, received
                failures = 0
            except (urllib.error.URLError, OSError, TimeoutError, RuntimeError) as error:
                failures += 1
                if failures >= 5:
                    raise RuntimeError(f"the download kept failing ({error})") from None
                self._cancel.wait(3)
        if self._cancel.is_set():
            return
        with self._lock:
            self._phase = "verifying"
        digest = hashlib.sha256()
        with part.open("rb") as handle:
            for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != entry["sha256"]:
            part.unlink()
            raise RuntimeError("the downloaded model file is not the expected one (hash mismatch); it was discarded")
        os.replace(part, target)

    def _healthy(self) -> bool:
        try:
            with _DIRECT.open(f"http://127.0.0.1:{PORT}/health", timeout=3) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def _start_process(self, entry: dict[str, Any], target: Path) -> None:
        with self._lock:
            if self._process and self._process.poll() is None and self._healthy():
                return
            self._stop_process()
            threads = max(1, (os.cpu_count() or 2) - 1)
            command = [
                str(self._binary), "-m", str(target), "--host", "127.0.0.1", "--port", str(PORT),
                "--alias", entry["id"], "-c", str(CONTEXT_TOKENS), "-t", str(threads), "-np", "1",
                "--reasoning-budget", "0", "--sleep-idle-seconds", str(IDLE_SECONDS), "--no-webui",
            ]
            environment = dict(os.environ)
            environment["LD_LIBRARY_PATH"] = f"{LLAMA_DIR}:{environment.get('LD_LIBRARY_PATH', '')}".rstrip(":")
            log_file = (self._store.data_dir / "local_model.log").open("ab")
            self._process = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT, env=environment)
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if self._cancel.is_set():
                return
            if self._process.poll() is not None:
                raise RuntimeError("the model runtime exited while starting (see local_model.log in the data folder)")
            if self._healthy():
                return
            time.sleep(0.5)
        raise RuntimeError("the model runtime did not become ready in time")

    def _stop_process(self) -> None:
        with self._lock:
            process, self._process = self._process, None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)

    def _register(self, entry: dict[str, Any]) -> int:
        return self._models.upsert_builtin(SOURCE_NAME, f"http://127.0.0.1:{PORT}/v1", "responses", entry["id"])

    def ensure_running(self) -> None:
        """Called before every call to the built-in source: restart the runtime if it died."""
        if not self._model_id:
            return
        entry = self._entry(self._model_id)
        target = self._file(entry)
        if target.exists() and not (self._process and self._process.poll() is None and self._healthy()):
            self._start_process(entry, target)
