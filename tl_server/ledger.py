"""What was sent to a model, byte for byte.

Dialogue leaves this server only towards the models the owner chose. Every such request is written down here
as it goes out: the very bytes of it (not put together again afterwards), where it went, for which task, and
what came back. The owner can open any of them and read exactly what was sent.

The key travels in a header and is never written. The texts are kept for a while (RETAIN_DAYS, at most
RETAIN_BYTES); the line saying that it happened, when, where to, how much and its sha256 stays for a year.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .errors import ApiError

log = logging.getLogger("tl_server.ledger")

RETAIN_DAYS = 30
RETAIN_BYTES = 500 * 1024 * 1024
KEEP_LINES_DAYS = 365
TIDY_EVERY = 200  # calls
PAGE = 50

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at REAL NOT NULL,
  task TEXT NOT NULL,
  source TEXT NOT NULL,
  host TEXT NOT NULL,
  scope TEXT NOT NULL,
  protocol TEXT NOT NULL,
  model TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  body BLOB,
  status TEXT NOT NULL DEFAULT 'sent',
  answer_bytes INTEGER,
  answer_sha256 TEXT,
  answer BLOB,
  tokens_in INTEGER,
  tokens_out INTEGER,
  ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_calls_at ON calls(at);
"""


def scope_of(host: str) -> str:
    """nas (this machine), lan (the home network) or outside."""
    if host in ("localhost", "host.docker.internal") or host.endswith(".localhost"):
        return "nas"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "outside"
    return "nas" if ip.is_loopback else ("lan" if ip.is_private else "outside")


class Ledger:
    def __init__(self, data_dir: Path | str, clock: Callable[[], float] = time.time) -> None:
        self._path = Path(data_dir) / "sent.db"
        self._clock = clock
        self._lock = threading.Lock()
        self.missed = 0  # requests that could not be written down (and were sent all the same)
        self._since_tidy = 0
        self._db = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        os.chmod(self._path, 0o600)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self._db.executescript(SCHEMA)
        # Under way when the server was last stopped: how they ended is not known.
        self._db.execute("UPDATE calls SET status = 'error:interrupted' WHERE status = 'sent'")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def recorder(self, *, task: str, source: str, protocol: str, model: str) -> Callable[[str, bytes], Callable[..., None]]:
        """For one call to a model: told the bytes as they go out, and how it ended."""

        def sent(url: str, body: bytes) -> Callable[..., None]:
            host = urlsplit(url).hostname or ""
            started = time.monotonic()
            try:
                with self._lock:
                    row = self._db.execute(
                        "INSERT INTO calls(at, task, source, host, scope, protocol, model, bytes, sha256, body) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (self._clock(), task, source, host, scope_of(host), protocol, model, len(body), hashlib.sha256(body).hexdigest(), zlib.compress(body, 6)),
                    ).lastrowid
            except sqlite3.Error as error:
                self.missed += 1
                log.warning("a request to a model could not be written down: %s", error)
                return lambda *_, **__: None

            def ended(status: str, answer: str = "", usage: dict[str, Any] | None = None) -> None:
                data = answer.encode("utf-8")
                usage = usage or {}
                try:
                    with self._lock:
                        self._db.execute(
                            "UPDATE calls SET status=?, answer_bytes=?, answer_sha256=?, answer=?, tokens_in=?, tokens_out=?, ms=? WHERE id=?",
                            (status, len(data), hashlib.sha256(data).hexdigest() if data else None, zlib.compress(data, 6) if data else None,
                             usage.get("input_tokens", usage.get("prompt_tokens")), usage.get("output_tokens", usage.get("completion_tokens")),
                             int((time.monotonic() - started) * 1000), row))
                    self._since_tidy += 1
                    if self._since_tidy >= TIDY_EVERY:
                        self._since_tidy = 0
                        self.tidy()
                except sqlite3.Error as error:
                    log.warning("how a request to a model ended could not be written down: %s", error)

            return ended

        return sent

    def tidy(self) -> None:
        """Old texts go; the lines about them stay (for a year)."""
        now = self._clock()
        with self._lock:
            self._db.execute("UPDATE calls SET body=NULL, answer=NULL WHERE at < ? AND (body IS NOT NULL OR answer IS NOT NULL)", (now - RETAIN_DAYS * 86400,))
            self._db.execute("DELETE FROM calls WHERE at < ?", (now - KEEP_LINES_DAYS * 86400,))
            held = self._db.execute("SELECT COALESCE(SUM(LENGTH(body)), 0) + COALESCE(SUM(LENGTH(answer)), 0) FROM calls").fetchone()[0]
            while held > RETAIN_BYTES:
                rows = self._db.execute(
                    "SELECT id, COALESCE(LENGTH(body), 0) + COALESCE(LENGTH(answer), 0) AS size FROM calls WHERE body IS NOT NULL OR answer IS NOT NULL ORDER BY id LIMIT 200").fetchall()
                if not rows:
                    break
                self._db.execute(f"UPDATE calls SET body=NULL, answer=NULL WHERE id IN ({','.join('?' * len(rows))})", [row["id"] for row in rows])
                held -= sum(row["size"] for row in rows)
            self._db.execute("PRAGMA incremental_vacuum")

    # ---- reading ---------------------------------------------------------------------

    def listing(self, *, before: int = 0, task: str = "", scope: str = "", today: float = 0.0) -> dict[str, Any]:
        """What was sent, newest first: where, how much, for what. Not the texts."""
        clauses, params = [], []
        for column, value in (("task", task), ("scope", scope)):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        if before:
            clauses.append("id < ?")
            params.append(before)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._db.execute(
                f"""SELECT id, at, task, source, host, scope, protocol, model, bytes, sha256, status, answer_bytes, tokens_in, tokens_out, ms,
                           body IS NOT NULL AS kept FROM calls {where} ORDER BY id DESC LIMIT ?""", (*params, PAGE)).fetchall()
            totals = [dict(row) for row in self._db.execute(
                "SELECT scope, COUNT(*) AS calls, SUM(bytes) AS bytes FROM calls WHERE at >= ? GROUP BY scope", (today,))]
            tasks = [row[0] for row in self._db.execute("SELECT DISTINCT task FROM calls ORDER BY task")]
            total = self._db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        return {"calls": [dict(row) for row in rows], "today": totals, "tasks": tasks, "total": total, "missed": self.missed,
                "retain_days": RETAIN_DAYS}

    def one(self, call_id: int) -> dict[str, Any]:
        """One request exactly as it was sent, and the answer."""
        with self._lock:
            row = self._db.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        if row is None:
            raise ApiError(404, "call_not_found")
        found = {key: row[key] for key in row.keys() if key not in ("body", "answer")}
        body = zlib.decompress(row["body"]) if row["body"] is not None else None
        answer = zlib.decompress(row["answer"]) if row["answer"] is not None else None
        found["body"] = body.decode("utf-8", errors="replace") if body is not None else None
        found["answer"] = answer.decode("utf-8", errors="replace") if answer is not None else None
        found["intact"] = body is not None and len(body) == row["bytes"] and hashlib.sha256(body).hexdigest() == row["sha256"]
        return found
