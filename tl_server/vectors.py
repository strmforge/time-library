"""Recall by meaning: a small embedding model on the server itself.

Words find a memory only when the question uses its words. A small embedding
model, run on the server's CPU, turns each memory and each question into a
vector; questions then find memories that say the same thing in other words.
Recall merges both (see recall.py).

Nothing here needs a GPU or an online model: the model is a few hundred MB,
downloaded once (from Hugging Face, or a mirror), checked against its hash, and
run with ONNX Runtime. Vectors are kept in SQLite next to the memories and held
in memory for search: at tens of thousands of memories a plain matrix product
takes milliseconds, so no vector database is needed.

The model that made the vectors is recorded. Vectors from another model live in
another space and are never mixed: switching models rebuilds the index.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .errors import ApiError

log = logging.getLogger("tl_server.vectors")

HOSTS = tuple(
    host.strip().rstrip("/")
    for host in os.environ.get("TL_MODEL_HOSTS", "https://huggingface.co,https://hf-mirror.com").split(",")
    if host.strip()
)
BATCH = 64
IDLE_SECONDS = 20  # how often new memories are looked for
THREADS = int(os.environ.get("TL_VECTOR_THREADS", "2"))  # leave the rest of the CPU to everything else

# Chosen by testing on the owner's own memories (2026-11-22, 47,822 memories, 300
# questions in other words; share answered in the first 1 / 5 / 10 results):
#   recall by words (BM25, before)        28% / 51% / 61%
#   hs-embed-1 alone                      54% / 77% / 83%   (int8: the same)
#   hs-embed-1 + hs-rerank-1 (top 30)     57% / 82% / 90%
#   BGE-M3 alone (568M, 14x slower)       62% / 84% / 89%
#   Granite 97M r2                        50% / 74% / 82%   (int8: 45 / 66 / 75)
# On the NAS CPU: 56 memories a second to embed, 9 ms a question, about 0.6-0.9 s
# to rerank. Both models are MIT licensed and read Chinese.
CATALOG: list[dict[str, Any]] = [
    {
        "id": "hs-embed-1",
        "label": "hs-embed-1 + hs-rerank-1",
        "note": "小模型,本机 CPU 就能跑;中文可用;约 380 MB",
        "revision": "3164caa4db95a03faac8a327f914f7c8f42d2f98",
        "pooling": "mean",
        "embed": {"repo": "hindsight-ai/hs-embed-1", "revision": "3164caa4db95a03faac8a327f914f7c8f42d2f98",
                  "onnx": "onnx/model.onnx", "tokenizer": "tokenizer.json"},
        "rerank": {"repo": "hindsight-ai/hs-rerank-1", "revision": "927f5be31280298a51cf29af8a29cb111ed812c5",
                   "onnx": "onnx/model.onnx", "tokenizer": "tokenizer.json"},
        "files": [
            {"part": "embed", "path": "onnx/model.onnx", "bytes": 152245964,
             "sha256": "ad880bb19889113774d139ca02c20d4eeda936ebefb3e0d647492b20968ce432"},
            {"part": "embed", "path": "tokenizer.json", "bytes": 34363286,
             "sha256": "f34b44a6dc8a0eef651bfa10e8325057530152606a69d9c3b6ae02efb1558f0a"},
            {"part": "rerank", "path": "onnx/model.onnx", "bytes": 160582339,
             "sha256": "c866580692c6bf274b11ca622db4329f4cbfd6f08f96af964badc31d748ef243"},
            {"part": "rerank", "path": "tokenizer.json", "bytes": 34363188,
             "sha256": "609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f"},
        ],
    },
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_vectors (
  memory_id INTEGER PRIMARY KEY,
  vector BLOB NOT NULL
);
"""

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def runtime_available() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError:
        return False
    return True


def _session(path: Path):
    import onnxruntime as ort

    # The owner's memories stay on the owner's server: no usage reporting.
    if hasattr(ort, "disable_telemetry_events"):
        ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = THREADS
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def _tokenizer(path: Path, max_tokens: int):
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(path))
    tokenizer.enable_truncation(max_tokens)
    tokenizer.enable_padding()
    return tokenizer


def part_folder(root: Path, part: dict[str, Any]) -> Path:
    return root / part["repo"].replace("/", "--") / part["revision"]


class Reranker:
    """A cross-encoder: reads the question and each memory together and scores the pair."""

    def __init__(self, part: dict[str, Any], folder: Path) -> None:
        import numpy as np

        self._np = np
        self.tokenizer = _tokenizer(folder / part["tokenizer"], 512)
        self.session = _session(folder / part["onnx"])
        self._inputs = {item.name for item in self.session.get_inputs()}

    def scores(self, question: str, texts: list[str]):
        np = self._np
        encoded = self.tokenizer.encode_batch([(question, text) for text in texts])
        feed = {
            "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
        }
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.array([e.type_ids for e in encoded], dtype=np.int64)
        logits = self.session.run(None, {key: value for key, value in feed.items() if key in self._inputs})[0]
        return np.asarray(logits, dtype=np.float32).reshape(len(texts), -1)[:, 0]


class Embedder:
    """One loaded model: text in, unit-length vectors out."""

    def __init__(self, entry: dict[str, Any], folder: Path) -> None:
        import numpy as np

        self._np = np
        self.entry = entry
        part = entry["embed"]
        here = part_folder(folder, part)
        self.tokenizer = _tokenizer(here / part["tokenizer"], entry.get("max_tokens", 512))
        self.session = _session(here / part["onnx"])
        self._inputs = {item.name for item in self.session.get_inputs()}
        self._outputs = [item.name for item in self.session.get_outputs()]
        self.reranker = Reranker(entry["rerank"], part_folder(folder, entry["rerank"])) if entry.get("rerank") else None

    def embed(self, texts: list[str], query: bool = False):
        np = self._np
        prefix = self.entry.get("query_prefix" if query else "document_prefix", "")
        encoded = self.tokenizer.encode_batch([prefix + text for text in texts])
        feed = {
            "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
            "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
        }
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(feed["input_ids"])
        outputs = self.session.run(None, {key: value for key, value in feed.items() if key in self._inputs})
        if "sentence_embedding" in self._outputs:
            vectors = outputs[self._outputs.index("sentence_embedding")]
        else:
            hidden = outputs[0]
            if self.entry.get("pooling") == "cls":
                vectors = hidden[:, 0]
            else:
                mask = feed["attention_mask"][..., None].astype(np.float32)
                vectors = (hidden * mask).sum(1) / np.clip(mask.sum(1), 1e-9, None)
        vectors = vectors.astype(np.float32)
        return vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9, None)


def identity(entry: dict[str, Any]) -> str:
    return f"{entry['id']}@{entry['revision']}"


class Vectors:
    def __init__(self, store) -> None:
        self._store = store
        self._dir = store.data_dir / "models" / "embed"
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._embedder: Embedder | None = None
        self._phase = "off"  # off | downloading | verifying | loading | indexing | ready | error
        self._error = ""
        self._downloaded = 0
        self._ids = None  # memory ids, aligned with the rows of _matrix
        self._matrix = None
        with store._lock:
            store._db.executescript(SCHEMA)

    # ---- switching on and off ------------------------------------------------

    def entry(self) -> dict[str, Any] | None:
        chosen = self._store._meta("vector_model_choice") or ""
        return next((item for item in CATALOG if item["id"] == chosen), None)

    def enable(self, model_id: str | None = None) -> dict[str, Any]:
        if not runtime_available():
            raise ApiError(409, "vector_runtime_missing", "this server image has no ONNX Runtime; update it first")
        entry = next((item for item in CATALOG if item["id"] == (model_id or CATALOG[0]["id"])), None) if CATALOG else None
        if entry is None:
            raise ApiError(400, "invalid_field", "unknown embedding model")
        with self._store._tx() as db:
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('vector_model_choice', ?)", (entry["id"],))
        self.start()
        return self.status()

    def disable(self) -> dict[str, Any]:
        with self._store._tx() as db:
            db.execute("DELETE FROM meta WHERE key='vector_model_choice'")
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(30)
        with self._lock:
            self._phase, self._embedder, self._ids, self._matrix = "off", None, None, None
        return self.status()

    def start(self) -> None:
        """Bring the model up and keep the index current (on start-up, if switched on)."""
        if self.entry() is None or not runtime_available():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._wake.set()
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._work, daemon=True, name="vectors")
            self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()

    def notify(self) -> None:
        """New memories were saved: embed them soon."""
        self._wake.set()

    # ---- the worker ---------------------------------------------------------------

    def _work(self) -> None:
        entry = self.entry()
        if entry is None:
            return
        try:
            folder = self._dir / entry["id"]
            done = 0  # bytes of the files already in place, so progress counts across all of them
            for item in entry["files"]:
                target = part_folder(folder, entry[item["part"]]) / item["path"]
                if not target.exists():
                    self._download(entry, item, target, done)
                if self._stop.is_set():
                    return
                done += item["bytes"]
            with self._lock:
                self._phase = "loading"
            embedder = Embedder(entry, folder)
            self._adopt(entry)
            with self._lock:
                self._embedder = embedder
            self._load_matrix()
            while not self._stop.is_set():
                added = self._index_some(embedder)
                if added:
                    continue
                with self._lock:
                    self._phase = "ready"
                self._wake.wait(IDLE_SECONDS)
                self._wake.clear()
        except Exception as error:
            log.exception("recall by meaning is unavailable")
            with self._lock:
                self._phase, self._error = "error", str(error)[:300]

    def _adopt(self, entry: dict[str, Any]) -> None:
        """Vectors made by another model are another space: drop them and build anew."""
        current = identity(entry)
        if self._store._meta("vector_model") == current:
            return
        with self._store._tx() as db:
            db.execute("DELETE FROM memory_vectors")
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('vector_model', ?)", (current,))
        log.info("vector index (re)built for %s", current)

    def _load_matrix(self) -> None:
        import numpy as np

        with self._store.reading() as db:
            rows = db.execute("SELECT memory_id, vector FROM memory_vectors ORDER BY memory_id").fetchall()
        ids = np.array([row[0] for row in rows], dtype=np.int64)
        matrix = np.stack([np.frombuffer(row[1], dtype=np.float16) for row in rows]).astype(np.float32) if rows else None
        with self._lock:
            self._ids, self._matrix = ids, matrix

    def _index_some(self, embedder: Embedder) -> int:
        import numpy as np

        with self._store.reading() as db:
            todo = db.execute(
                """
                SELECT m.id, m.statement, m.title FROM memories m LEFT JOIN memory_vectors v ON v.memory_id = m.id
                WHERE m.status = 'active' AND v.memory_id IS NULL ORDER BY m.id LIMIT ?
                """,
                (BATCH,),
            ).fetchall()
            if todo:
                missing = db.execute(
                    "SELECT COUNT(*) FROM memories m LEFT JOIN memory_vectors v ON v.memory_id = m.id WHERE m.status = 'active' AND v.memory_id IS NULL"
                ).fetchone()[0]
        if not todo:
            return 0
        with self._lock:
            self._phase = "indexing" if missing > BATCH else self._phase
        texts = [(row["title"] + ":" if row["title"] else "") + row["statement"] for row in todo]
        vectors = embedder.embed(texts)
        with self._store._tx() as db:
            db.executemany(
                "INSERT OR REPLACE INTO memory_vectors(memory_id, vector) VALUES(?,?)",
                [(row["id"], vector.astype(np.float16).tobytes()) for row, vector in zip(todo, vectors)],
            )
        new_ids = np.array([row["id"] for row in todo], dtype=np.int64)
        with self._lock:
            if self._matrix is None:
                self._ids, self._matrix = new_ids, vectors
            else:
                self._ids = np.concatenate([self._ids, new_ids])
                self._matrix = np.concatenate([self._matrix, vectors])
        return len(todo)

    def _download(self, entry: dict[str, Any], item: dict[str, Any], target: Path, before: int = 0) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        failures = 0
        while not self._stop.is_set():
            have = part.stat().st_size if part.exists() else 0
            if have > item["bytes"]:
                part.unlink()
                have = 0
            if have == item["bytes"]:
                break
            with self._lock:
                self._phase, self._downloaded = "downloading", before + have
            try:
                with self._open(entry, item, have) as response:
                    if have and response.status != 206:
                        have = 0
                    with part.open("ab" if have else "wb") as out:
                        while not self._stop.is_set():
                            chunk = response.read1(256 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                            have += len(chunk)
                            with self._lock:
                                self._downloaded = before + have
                failures = 0
            except (urllib.error.URLError, OSError, TimeoutError, RuntimeError) as error:
                failures += 1
                if failures >= 5:
                    raise RuntimeError(f"the download kept failing ({error})") from None
                self._stop.wait(3)
        if self._stop.is_set():
            return
        with self._lock:
            self._phase = "verifying"
        digest = hashlib.sha256()
        with part.open("rb") as handle:
            for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != item["sha256"]:
            part.unlink()
            raise RuntimeError(f"{item['path']} is not the expected file (hash mismatch); it was discarded")
        os.replace(part, target)

    def _open(self, entry: dict[str, Any], item: dict[str, Any], offset: int):
        last: Exception | None = None
        for host in HOSTS:
            part = entry[item["part"]]
            request = urllib.request.Request(
                f"{host}/{part['repo']}/resolve/{part['revision']}/{item['path']}",
                headers=({"Range": f"bytes={offset}-"} if offset else {}) | {"User-Agent": "time-library-server"},
            )
            try:
                return _DIRECT.open(request, timeout=20)
            except (urllib.error.URLError, OSError, TimeoutError) as error:
                last = error
        raise RuntimeError(f"could not reach any model download host ({last})")

    # ---- searching ------------------------------------------------------------------

    def ready(self) -> bool:
        with self._lock:
            return self._embedder is not None and self._matrix is not None

    def rerank(self, question: str, candidates: list[tuple[int, str]]) -> list[int] | None:
        """Order candidate memories (id, text) by the reranker; None when there is none."""
        scored = self.rerank_scores(question, candidates)
        return None if scored is None else [memory_id for memory_id, _ in scored]

    def rerank_scores(self, question: str, candidates: list[tuple[int, str]]) -> list[tuple[int, float]] | None:
        """(memory id, reranker score), best first; None when there is no reranker."""
        with self._lock:
            embedder = self._embedder
        if embedder is None or embedder.reranker is None or not candidates:
            return None
        scores = embedder.reranker.scores(question, [text for _, text in candidates])
        order = sorted(range(len(candidates)), key=lambda i: -float(scores[i]))
        return [(candidates[i][0], float(scores[i])) for i in order]

    def search(self, query: str, limit: int = 100) -> list[tuple[int, float]]:
        """Memories closest in meaning to the query: (memory id, cosine similarity), best first."""
        import numpy as np

        with self._lock:
            embedder, ids, matrix = self._embedder, self._ids, self._matrix
        if embedder is None or matrix is None or not len(ids):
            return []
        vector = embedder.embed([query], query=True)[0]
        scores = matrix @ vector
        top = np.argpartition(-scores, min(limit, len(scores) - 1))[:limit]
        top = top[np.argsort(-scores[top])]
        return [(int(ids[i]), float(scores[i])) for i in top]

    # ---- what the admin page shows ------------------------------------------------------

    def status(self) -> dict[str, Any]:
        entry = self.entry()
        with self._store.reading() as db:
            indexed = db.execute(
                "SELECT COUNT(*) FROM memory_vectors v JOIN memories m ON m.id = v.memory_id WHERE m.status = 'active'"
            ).fetchone()[0]
            active = db.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()[0]
        with self._lock:
            phase, error, downloaded = self._phase, self._error, self._downloaded
        return {
            "available": runtime_available(),
            "enabled": entry is not None,
            "model": {key: entry[key] for key in ("id", "label", "note")} if entry else None,
            "catalog": [{key: item[key] for key in ("id", "label", "note")} | {"bytes": sum(f["bytes"] for f in item["files"])} for item in CATALOG],
            "phase": phase if entry else "off",
            "error": error,
            "downloaded": downloaded,
            "download_bytes": sum(f["bytes"] for f in entry["files"]) if entry else 0,
            "indexed": indexed,
            "active": active,
        }
