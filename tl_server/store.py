"""SQLite store: computers, their agents, and the dialogue they upload.

Identity is always "which computer + which agent"; both are self-reported by the
client side. The server never keeps tokens in the clear, only their hashes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from . import tokens
from .errors import ApiError

SCHEMA_VERSION = 1
PAIRING_TTL_SECONDS = 24 * 3600
MAX_BATCH_SEGMENTS = 500
MAX_TEXT_CHARS = 200_000
CHECKPOINT_SECONDS = 10
WAL_SHRINK_BYTES = 64 * 1024 * 1024
MAX_POSITION = 2**62
ROLES = ("user", "assistant")
LAST_SEEN_WRITE_INTERVAL = 30.0
ONLINE_WINDOW_SECONDS = 90.0
SESSION_TTL_SECONDS = 30 * 24 * 3600
MIN_PASSWORD_LENGTH = 8
PBKDF2_ITERATIONS = 200_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pairing_tokens (
  token_hash TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  used_at REAL,
  used_by_device INTEGER
);
CREATE TABLE IF NOT EXISTS devices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_uid TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  os TEXT NOT NULL DEFAULT '',
  client_version TEXT NOT NULL DEFAULT '',
  token_hash TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_seen_at REAL,
  revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_devices_token ON devices(token_hash);
CREATE TABLE IF NOT EXISTS agents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id INTEGER NOT NULL REFERENCES devices(id),
  name TEXT NOT NULL,
  capabilities TEXT NOT NULL DEFAULT '{}',
  sessions_location TEXT NOT NULL DEFAULT '',
  session_format TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  last_report_at REAL NOT NULL,
  last_ingest_at REAL,
  backlog INTEGER,
  disconnected_at REAL,
  UNIQUE(device_id, name)
);
-- What an agent has really asked the server for, found something or not: what it says
-- it supports is its own word, this is what was seen. recent = the latest times (JSON).
CREATE TABLE IF NOT EXISTS agent_use (
  device_id INTEGER NOT NULL,
  agent TEXT NOT NULL,
  mode TEXT NOT NULL,
  calls INTEGER NOT NULL DEFAULT 0,
  handed INTEGER NOT NULL DEFAULT 0,
  last_at REAL NOT NULL,
  recent TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (device_id, agent, mode)
);
CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id INTEGER NOT NULL REFERENCES agents(id),
  segment_uid TEXT NOT NULL,
  session_id TEXT NOT NULL,
  source_file TEXT NOT NULL,
  position INTEGER NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  ts TEXT NOT NULL DEFAULT '',
  received_at REAL NOT NULL,
  UNIQUE(agent_id, segment_uid)
);
CREATE INDEX IF NOT EXISTS idx_segments_cursor ON segments(agent_id, source_file, position);
CREATE INDEX IF NOT EXISTS idx_segments_received ON segments(received_at);
CREATE TABLE IF NOT EXISTS sessions (
  agent_id INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  cwd TEXT NOT NULL DEFAULT '',
  updated_at REAL NOT NULL,
  PRIMARY KEY (agent_id, session_id)
);
-- When each conversation took place: its first and last message's timestamp.
CREATE TABLE IF NOT EXISTS session_spans (
  agent_id INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  first_ts TEXT NOT NULL,
  last_ts TEXT NOT NULL,
  PRIMARY KEY (agent_id, session_id)
);
CREATE TABLE IF NOT EXISTS admin_sessions (
  token_hash TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL
);
"""


def normalize_folder(path: str) -> str:
    """One spelling per folder: forward slashes, no trailing slash."""
    folder = path.strip().replace("\\", "/")
    while len(folder) > 1 and folder.endswith("/"):
        folder = folder[:-1]
    return folder


def content_key(role: str, ts: str, text: str, part: int = 0) -> str:
    """Identity of a message (or of one part of a long one) by what it is, not
    where it was read from. '' without a timestamp: then it cannot be told apart."""
    if not ts:
        return ""
    return hashlib.sha256(f"{role}\x00{ts}\x00{part}\x00{text}".encode("utf-8")).hexdigest()[:40]


def _text(value: Any, field: str, *, min_len: int = 0, max_len: int) -> str:
    if not isinstance(value, str):
        raise ApiError(400, "invalid_field", f"{field} must be a string")
    cleaned = value.strip() if max_len <= 1024 else value
    if len(cleaned) < min_len or len(cleaned) > max_len:
        raise ApiError(400, "invalid_field", f"{field} length must be {min_len}..{max_len}")
    return cleaned


def _optional_text(value: Any, field: str, *, max_len: int) -> str:
    return "" if value is None else _text(value, field, max_len=max_len)


PROMPT_MIN_CHARS = 6  # shorter prompts are not looked up before they are answered
PROMPT_LIVE_SECONDS = 900
PROMPT_SKEW_SECONDS = 120  # the computer's clock against the server's
PROMPTS_KEPT = 10
PREFLIGHT_QUIET_AFTER = 3  # this many prompts in a row without a request


def _epoch(stamp: Any) -> float | None:
    try:
        at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).timestamp()


def preflight_seen(agent, use) -> dict[str, Any]:
    """Whether the prompt hook an agent says it has was really seen at work: when it last asked,
    and quiet = how many of the user's latest prompts came without it asking (0 = none, or too few to tell)."""
    calls = json.loads(use["recent"]) if use else []
    seen = {"calls": use["calls"] if use else 0, "handed": use["handed"] if use else 0,
            "last_at": use["last_at"] if use else None, "quiet": 0}
    if agent["disconnected_at"] is not None or not json.loads(agent["capabilities"]).get("preflight"):
        return seen
    quiet = 0
    for at in reversed(json.loads(agent["recent_prompts"])):
        if any(abs(call - at) <= PROMPT_SKEW_SECONDS for call in calls):
            break
        quiet += 1
    if quiet >= PREFLIGHT_QUIET_AFTER:
        seen["quiet"] = quiet
    return seen


class Store:
    def __init__(self, data_dir: str | os.PathLike[str], *, clock: Callable[[], float] = time.time) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        # A write may have to wait for the disk on a slow NAS volume: give it time
        # rather than failing the request.
        self._db = sqlite3.connect(
            self.data_dir / "server.db", check_same_thread=False, isolation_level=None, timeout=30
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        # A receipt means "it is on disk": clients only move their read position
        # forward after one, so never acknowledge before the write is durable.
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        # Folding the write-ahead log back into the database syncs the disk, which
        # can take seconds on a NAS volume. Do it from a separate connection in the
        # background, so no request ever waits behind it.
        self._db.execute("PRAGMA wal_autocheckpoint=0")
        # When the log starts over after a checkpoint, cut its file back to this
        # size. (A TRUNCATE checkpoint would do it too, but it holds every write
        # back while it runs, which on slow disks means failed requests.)
        self._db.execute(f"PRAGMA journal_size_limit={WAL_SHRINK_BYTES}")
        # Reads that agents wait on (recall, the original words) use their own
        # connection: in WAL mode they never wait behind a write and its disk sync.
        self._read_db = sqlite3.connect(self.data_dir / "server.db", check_same_thread=False, isolation_level=None)
        self._read_db.row_factory = sqlite3.Row
        self._read_db.execute("PRAGMA query_only=ON")
        self._read_lock = threading.RLock()  # re-entrant: a reader may call another reader
        self._seen: dict[int, float] = {}
        self._seen_lock = threading.Lock()
        self._closing = threading.Event()
        self._checkpointer = threading.Thread(target=self._checkpoint_loop, daemon=True, name="wal-checkpoint")
        self._db.executescript(SCHEMA)
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(segments)")}
        if "imported" not in columns:
            # 1 = history brought in after the fact; held for the owner to have organised.
            self._db.execute("ALTER TABLE segments ADD COLUMN imported INTEGER NOT NULL DEFAULT 0")
        if "chars" not in columns:
            # Kept beside the text so totals never have to read the text itself.
            self._db.execute("ALTER TABLE segments ADD COLUMN chars INTEGER NOT NULL DEFAULT -1")
        self._db.execute("UPDATE segments SET chars = LENGTH(text) WHERE chars < 0")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_segments_session ON segments(agent_id, session_id, id)")
        # Answers "what is still waiting, and how much" from the index alone.
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_segments_pending ON segments(imported, agent_id, session_id, id, chars)")
        self._dedupe_segments()
        self._fill_session_spans()
        self._count_segments()
        if "verified" not in {row["name"] for row in self._db.execute("PRAGMA table_info(agents)")}:
            # What the last look at this agent's own files found (JSON): whether anything was missed.
            self._db.execute("ALTER TABLE agents ADD COLUMN verified TEXT NOT NULL DEFAULT ''")
        if "recent_prompts" not in {row["name"] for row in self._db.execute("PRAGMA table_info(agents)")}:
            # When the user last asked this agent something (JSON, live prompts only).
            self._db.execute("ALTER TABLE agents ADD COLUMN recent_prompts TEXT NOT NULL DEFAULT '[]'")
        if "surface" not in {row["name"] for row in self._db.execute("PRAGMA table_info(sessions)")}:
            # Where a session was started (an agent's desktop app or its command line), as its records say.
            self._db.execute("ALTER TABLE sessions ADD COLUMN surface TEXT NOT NULL DEFAULT ''")
        self.admin_token_path = self.data_dir / "admin_token.txt"
        self._init_meta()
        self._server_id = self._meta("server_id") or ""
        self._checkpointer.start()

    def _checkpoint_loop(self) -> None:
        try:
            db = sqlite3.connect(self.data_dir / "server.db", check_same_thread=False, isolation_level=None)
        except sqlite3.Error:
            return
        try:
            db.execute("PRAGMA busy_timeout=5000")
            while not self._closing.wait(CHECKPOINT_SECONDS):
                try:
                    self._flush_seen()
                except sqlite3.Error:
                    pass
                try:
                    # PASSIVE never holds writes back.
                    db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                except sqlite3.Error:
                    pass  # busy now: next time
        finally:
            db.close()

    def _dedupe_segments(self) -> None:
        """One message, stored once.

        Some agents copy a conversation's history into a new session file (when
        a session is resumed or forked). Those copies carry the same role,
        timestamp and text, so they are recognised by that and kept once; a
        message only counts as a copy when it has a timestamp.
        """
        db = self._db
        with self._lock:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(segments)")}
            if "content_key" not in columns:
                db.execute("ALTER TABLE segments ADD COLUMN content_key TEXT NOT NULL DEFAULT ''")
            elif db.execute("SELECT 1 FROM meta WHERE key='segments_content_keyed'").fetchone():
                # Done once; every segment since carries its key. Skips a full scan per start.
                db.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_segments_content ON segments(agent_id, content_key) WHERE content_key != ''"
                )
                return
            pending = db.execute(
                """
                SELECT id, role, ts, text,
                       (SELECT COUNT(*) FROM segments o WHERE o.agent_id = s.agent_id AND o.source_file = s.source_file
                          AND o.position = s.position AND o.id < s.id) AS part
                FROM segments s WHERE content_key = '' AND ts != ''
                """
            ).fetchall()
            if pending:
                db.execute("BEGIN IMMEDIATE")
                # Rebuilt below, once the copies are gone.
                db.execute("DROP INDEX IF EXISTS idx_segments_content")
                # Parts of one long message share a file and position; their order is their part number.
                db.executemany(
                    "UPDATE segments SET content_key = ? WHERE id = ?",
                    [(content_key(row["role"], row["ts"], row["text"], row["part"]), row["id"]) for row in pending],
                )
                groups = db.execute(
                    """
                    SELECT MIN(id) AS keep, GROUP_CONCAT(id) AS ids FROM segments
                    WHERE content_key != '' GROUP BY agent_id, content_key HAVING COUNT(*) > 1
                    """
                ).fetchall()
                has_evidence = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_evidence'"
                ).fetchone()
                for group in groups:
                    copies = [int(value) for value in group["ids"].split(",") if int(value) != group["keep"]]
                    marks = ",".join("?" * len(copies))
                    if has_evidence:
                        # Memories that cite a copy now cite the message it copies.
                        db.execute(f"UPDATE memory_evidence SET segment_id = ? WHERE segment_id IN ({marks})", (group["keep"], *copies))
                    db.execute(f"DELETE FROM segments WHERE id IN ({marks})", copies)
                db.execute("COMMIT")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_segments_content ON segments(agent_id, content_key) WHERE content_key != ''"
            )
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('segments_content_keyed', '1')")

    def _count_segments(self) -> None:
        """Each agent's stored segments, counted as they arrive (counting the table on
        every page view meant a full scan of a million rows behind the writers)."""
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(agents)")}
        if "segments_total" in columns:
            return
        with self._tx() as db:
            db.execute("ALTER TABLE agents ADD COLUMN segments_total INTEGER NOT NULL DEFAULT 0")
            db.execute("UPDATE agents SET segments_total = (SELECT COUNT(*) FROM segments s WHERE s.agent_id = agents.id)")

    def _fill_session_spans(self) -> None:
        """Once: when each stored conversation took place. Every upload since keeps it current."""
        with self._tx() as db:
            if db.execute("SELECT 1 FROM meta WHERE key='session_spans_filled'").fetchone():
                return
            db.execute(
                """
                INSERT OR REPLACE INTO session_spans(agent_id, session_id, first_ts, last_ts)
                SELECT agent_id, session_id, MIN(ts), MAX(ts) FROM segments WHERE ts != '' GROUP BY agent_id, session_id
                """
            )
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('session_spans_filled', '1')")

    @contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        """A read-only connection that never waits behind writes."""
        with self._read_lock:
            yield self._read_db

    def close(self) -> None:
        self._closing.set()
        self._checkpointer.join(10)
        try:
            self._flush_seen()
        except sqlite3.Error:
            pass
        with self._read_lock:
            self._read_db.close()
        with self._lock:
            self._db.close()  # the last connection to close folds the log in

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            else:
                self._db.execute("COMMIT")

    def _meta(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _init_meta(self) -> None:
        new_admin_token = None
        with self._tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            db.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('server_id', ?)",
                (uuid.uuid4().hex,),
            )
            if not db.execute("SELECT 1 FROM meta WHERE key='admin_token_hash'").fetchone():
                new_admin_token = tokens.mint(tokens.ADMIN_PREFIX)
                db.execute(
                    "INSERT INTO meta(key, value) VALUES('admin_token_hash', ?)",
                    (tokens.digest(new_admin_token),),
                )
        if new_admin_token:
            fd = os.open(self.admin_token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(new_admin_token + "\n")

    @property
    def server_id(self) -> str:
        return self._server_id  # fixed for the life of the database; no lock needed

    # ---- admin -----------------------------------------------------------

    def verify_admin(self, token: str | None) -> bool:
        token_hash = self._meta("admin_token_hash")
        return bool(token and token_hash and tokens.matches(token, token_hash))

    # ---- signing in from a browser ----------------------------------------

    @staticmethod
    def _password_digest(password: str, salt: bytes, iterations: int) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

    def admin_password_is_set(self) -> bool:
        return self._meta("admin_password") is not None

    def _password_record(self, password: Any) -> str:
        if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
            raise ApiError(400, "password_too_short", f"at least {MIN_PASSWORD_LENGTH} characters")
        salt = secrets.token_bytes(16)
        return json.dumps(
            {
                "salt": salt.hex(),
                "iterations": PBKDF2_ITERATIONS,
                "hash": self._password_digest(password, salt, PBKDF2_ITERATIONS).hex(),
            }
        )

    def set_admin_password(self, password: Any) -> None:
        """First-visit setup: whoever opens the page first chooses the password."""
        record = self._password_record(password)
        with self._tx() as db:
            if db.execute("SELECT 1 FROM meta WHERE key='admin_password'").fetchone():
                raise ApiError(409, "already_set_up")
            db.execute("INSERT INTO meta(key, value) VALUES('admin_password', ?)", (record,))

    def replace_admin_password(self, password: Any) -> None:
        """A new password (changed, or set again by whoever holds the server key): every browser signs in again."""
        record = self._password_record(password)
        with self._tx() as db:
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('admin_password', ?)", (record,))
            db.execute("DELETE FROM admin_sessions")

    def check_admin_password(self, password: Any) -> bool:
        stored = self._meta("admin_password")
        if not stored or not isinstance(password, str):
            return False
        record = json.loads(stored)
        candidate = self._password_digest(password, bytes.fromhex(record["salt"]), int(record["iterations"]))
        return hmac.compare_digest(candidate, bytes.fromhex(record["hash"]))

    def create_admin_session(self) -> str:
        token = tokens.mint(tokens.SESSION_PREFIX)
        now = self._clock()
        with self._tx() as db:
            db.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (now,))
            db.execute(
                "INSERT INTO admin_sessions(token_hash, created_at, expires_at) VALUES(?,?,?)",
                (tokens.digest(token), now, now + SESSION_TTL_SECONDS),
            )
        return token

    def verify_admin_session(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            row = self._db.execute(
                "SELECT expires_at FROM admin_sessions WHERE token_hash=?", (tokens.digest(token),)
            ).fetchone()
        return bool(row and row["expires_at"] >= self._clock())

    def delete_admin_session(self, token: str | None) -> None:
        if token:
            with self._tx() as db:
                db.execute("DELETE FROM admin_sessions WHERE token_hash=?", (tokens.digest(token),))

    def overview(self, since: float) -> dict[str, Any]:
        """What the overview page shows. `since` is the viewer's start of today."""
        now = self._clock()
        with self._seen_lock:
            pending = dict(self._seen)  # sightings not yet written: shown without waiting for a write
        with self.reading() as db:
            today = db.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(chars), 0) AS chars FROM segments WHERE received_at >= ? AND imported = 0",
                (since,),
            ).fetchone()
            total = db.execute("SELECT COALESCE(SUM(segments_total), 0) AS n FROM agents").fetchone()["n"]
            seen = db.execute("SELECT id, last_seen_at FROM devices WHERE revoked_at IS NULL").fetchall()
            devices = {
                "n": len(seen),
                "online": sum(1 for row in seen if max(row["last_seen_at"] or 0, pending.get(row["id"], 0)) >= now - ONLINE_WINDOW_SECONDS),
            }
            agents = db.execute(
                """
                SELECT COUNT(*) AS n FROM agents a JOIN devices d ON d.id = a.device_id
                WHERE d.revoked_at IS NULL AND a.disconnected_at IS NULL
                """
            ).fetchone()["n"]
            recent = db.execute(
                """
                SELECT d.name AS device, a.name AS agent, a.last_ingest_at AS at,
                       (SELECT COUNT(*) FROM segments s WHERE s.agent_id = a.id AND s.received_at >= ? AND s.imported = 0) AS today
                FROM agents a JOIN devices d ON d.id = a.device_id
                WHERE a.last_ingest_at IS NOT NULL
                ORDER BY a.last_ingest_at DESC LIMIT 8
                """,
                (since,),
            ).fetchall()
        usage = shutil.disk_usage(self.data_dir)
        return {
            "server_id": self.server_id,
            "now": now,
            "segments_today": today["n"],
            "chars_today": today["chars"],
            "segments_total": total,
            "devices_total": devices["n"],
            "devices_online": devices["online"],
            "agents_total": agents,
            "storage": {"free_bytes": usage.free, "total_bytes": usage.total},
            "recent": [dict(row) for row in recent],
        }

    def create_pairing_token(self) -> dict[str, Any]:
        token = tokens.mint(tokens.PAIRING_PREFIX)
        now = self._clock()
        expires_at = now + PAIRING_TTL_SECONDS
        with self._tx() as db:
            db.execute(
                "INSERT INTO pairing_tokens(token_hash, created_at, expires_at) VALUES(?,?,?)",
                (tokens.digest(token), now, expires_at),
            )
        return {"pairing_token": token, "expires_at": expires_at}

    @staticmethod
    def _note_prompts(db, agent_id: int, stamps: list[str], now: float) -> None:
        """Remember when the user asked this agent something, as it happens (an upload catching up does not count)."""
        fresh = {at for at in map(_epoch, stamps) if at is not None and now - PROMPT_LIVE_SECONDS <= at <= now + PROMPT_SKEW_SECONDS}
        if not fresh:
            return
        kept = json.loads(db.execute("SELECT recent_prompts FROM agents WHERE id=?", (agent_id,)).fetchone()[0])
        merged = sorted(fresh.union(kept))[-PROMPTS_KEPT:]
        if merged != kept:
            db.execute("UPDATE agents SET recent_prompts=? WHERE id=?", (json.dumps(merged), agent_id))

    def list_devices(self) -> list[dict[str, Any]]:
        online_after = self._clock() - ONLINE_WINDOW_SECONDS
        with self._seen_lock:
            pending = dict(self._seen)
        with self.reading() as db:
            devices = db.execute("SELECT * FROM devices ORDER BY id").fetchall()
            agents = db.execute("SELECT * FROM agents ORDER BY id").fetchall()
            asked = {(row["device_id"], row["agent"]): row for row in
                     db.execute("SELECT * FROM agent_use WHERE mode = 'preflight'")}
        counts = {agent["id"]: agent["segments_total"] for agent in agents}
        by_device: dict[int, list[dict[str, Any]]] = {}
        for agent in agents:
            by_device.setdefault(agent["device_id"], []).append(
                {
                    "agent_id": agent["id"],
                    "name": agent["name"],
                    "capabilities": json.loads(agent["capabilities"]),
                    "sessions_location": agent["sessions_location"],
                    "session_format": agent["session_format"],
                    "last_report_at": agent["last_report_at"],
                    "last_ingest_at": agent["last_ingest_at"],
                    "backlog": agent["backlog"],
                    "disconnected": agent["disconnected_at"] is not None,
                    "segments_total": counts.get(agent["id"], 0),
                    "verified": json.loads(agent["verified"]) if agent["verified"] else None,
                    "preflight": preflight_seen(agent, asked.get((agent["device_id"], agent["name"]))),
                }
            )
        return [
            {
                "device_id": device["id"],
                "name": device["name"],
                "os": device["os"],
                "client_version": device["client_version"],
                "created_at": device["created_at"],
                "last_seen_at": max(device["last_seen_at"] or 0, pending.get(device["id"], 0)) or None,
                "online": device["revoked_at"] is None
                and max(device["last_seen_at"] or 0, pending.get(device["id"], 0)) >= online_after,
                "revoked": device["revoked_at"] is not None,
                "revoked_at": device["revoked_at"],
                "agents": by_device.get(device["id"], []),
            }
            for device in devices
        ]

    def revoke_device(self, device_id: int) -> None:
        with self._tx() as db:
            changed = db.execute(
                "UPDATE devices SET revoked_at=COALESCE(revoked_at, ?) WHERE id=?",
                (self._clock(), device_id),
            ).rowcount
        if not changed:
            raise ApiError(404, "device_not_found")

    def disconnect_agent(self, agent_id: int) -> None:
        with self._tx() as db:
            changed = db.execute(
                "UPDATE agents SET disconnected_at=COALESCE(disconnected_at, ?) WHERE id=?",
                (self._clock(), agent_id),
            ).rowcount
        if not changed:
            raise ApiError(404, "agent_not_found")

    # ---- pairing ---------------------------------------------------------

    def pair(self, pairing_token: Any, device: Any) -> dict[str, Any]:
        if not isinstance(pairing_token, str) or not pairing_token:
            raise ApiError(401, "pairing_token_invalid")
        if not isinstance(device, Mapping):
            raise ApiError(400, "invalid_field", "device must be an object")
        device_uid = _text(device.get("device_uid"), "device.device_uid", min_len=8, max_len=128)
        name = _text(device.get("name"), "device.name", min_len=1, max_len=128)
        os_name = _optional_text(device.get("os"), "device.os", max_len=64)
        client_version = _optional_text(
            device.get("client_version"), "device.client_version", max_len=64
        )
        device_token = tokens.mint(tokens.DEVICE_PREFIX)
        now = self._clock()
        with self._tx() as db:
            row = db.execute(
                "SELECT * FROM pairing_tokens WHERE token_hash=?", (tokens.digest(pairing_token),)
            ).fetchone()
            if row is None:
                raise ApiError(401, "pairing_token_invalid")
            if row["used_at"] is not None:
                raise ApiError(401, "pairing_token_used")
            if row["expires_at"] < now:
                raise ApiError(401, "pairing_token_expired")
            db.execute(
                """
                INSERT INTO devices(device_uid, name, os, client_version, token_hash, created_at, last_seen_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(device_uid) DO UPDATE SET
                  name=excluded.name, os=excluded.os, client_version=excluded.client_version,
                  token_hash=excluded.token_hash, last_seen_at=excluded.last_seen_at, revoked_at=NULL
                """,
                (device_uid, name, os_name, client_version, tokens.digest(device_token), now, now),
            )
            device_id = db.execute(
                "SELECT id FROM devices WHERE device_uid=?", (device_uid,)
            ).fetchone()["id"]
            db.execute(
                "UPDATE pairing_tokens SET used_at=?, used_by_device=? WHERE token_hash=?",
                (now, device_id, row["token_hash"]),
            )
        return {"device_id": device_id, "device_token": device_token, "server_id": self.server_id}

    def device_for_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        now = self._clock()
        with self.reading() as db:
            row = db.execute(
                "SELECT * FROM devices WHERE token_hash=? AND revoked_at IS NULL",
                (tokens.digest(token),),
            ).fetchone()
        if row is None:
            return None
        if row["last_seen_at"] is None or now - row["last_seen_at"] >= LAST_SEEN_WRITE_INTERVAL:
            # Noted now, written in the background: a request never waits on the disk for it.
            with self._seen_lock:
                self._seen[row["id"]] = now
        return {"device_id": row["id"], "name": row["name"]}

    def _flush_seen(self) -> None:
        with self._seen_lock:
            seen, self._seen = self._seen, {}
        if seen:
            with self._lock:
                self._db.executemany("UPDATE devices SET last_seen_at = MAX(COALESCE(last_seen_at, 0), ?) WHERE id = ?",
                                     [(at, device_id) for device_id, at in seen.items()])

    # ---- agents ----------------------------------------------------------

    def report_agent(self, device_id: int, agent: Any) -> dict[str, Any]:
        if not isinstance(agent, Mapping):
            raise ApiError(400, "invalid_field", "agent must be an object")
        name = _text(agent.get("name"), "agent.name", min_len=1, max_len=64)
        raw_caps = agent.get("capabilities") or {}
        if not isinstance(raw_caps, Mapping) or len(raw_caps) > 16:
            raise ApiError(400, "invalid_field", "agent.capabilities must be a small object")
        # Self-report is the authority: record exactly what the agent says it
        # supports, including an explicit "not supported".
        capabilities = {
            _text(key, "agent.capabilities key", min_len=1, max_len=32): value
            for key, value in raw_caps.items()
            if isinstance(value, bool)
        }
        sessions_location = _optional_text(
            agent.get("sessions_location"), "agent.sessions_location", max_len=1024
        )
        session_format = _optional_text(agent.get("session_format"), "agent.session_format", max_len=64)
        now = self._clock()
        with self._tx() as db:
            db.execute(
                """
                INSERT INTO agents(device_id, name, capabilities, sessions_location, session_format,
                                   created_at, last_report_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(device_id, name) DO UPDATE SET
                  capabilities=CASE WHEN ? THEN excluded.capabilities ELSE agents.capabilities END,
                  sessions_location=excluded.sessions_location,
                  session_format=excluded.session_format, last_report_at=excluded.last_report_at,
                  disconnected_at=NULL
                """,
                (
                    device_id,
                    name,
                    json.dumps(capabilities, ensure_ascii=False, sort_keys=True),
                    sessions_location,
                    session_format,
                    now,
                    now,
                    "capabilities" in agent,  # a report that says nothing about them keeps what was said before
                ),
            )
            agent_id = db.execute(
                "SELECT id FROM agents WHERE device_id=? AND name=?", (device_id, name)
            ).fetchone()["id"]
        return {"agent_id": agent_id, "name": name}

    def _require_agent(self, device_id: int, agent_id: Any) -> int:
        if isinstance(agent_id, bool) or not isinstance(agent_id, int):
            raise ApiError(400, "invalid_field", "agent_id must be an integer")
        with self._lock:
            row = self._db.execute(
                "SELECT id, disconnected_at FROM agents WHERE id=? AND device_id=?",
                (agent_id, device_id),
            ).fetchone()
        if row is None:
            raise ApiError(404, "agent_not_found")
        if row["disconnected_at"] is not None:
            raise ApiError(403, "agent_disconnected")
        return agent_id

    def heartbeat(self, device_id: int, client_version: Any, backlog: Any) -> None:
        version = _optional_text(client_version, "client_version", max_len=64)
        if backlog is None:
            backlog = {}
        if not isinstance(backlog, Mapping) or len(backlog) > 256:
            raise ApiError(400, "invalid_field", "backlog must be an object")
        updates = []
        for key, value in backlog.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ApiError(400, "invalid_field", "backlog values must be non-negative integers")
            try:
                updates.append((value, int(key), device_id))
            except (TypeError, ValueError):
                raise ApiError(400, "invalid_field", "backlog keys must be agent ids") from None
        with self._tx() as db:
            db.execute(
                "UPDATE devices SET last_seen_at=?, client_version=CASE WHEN ?='' THEN client_version ELSE ? END WHERE id=?",
                (self._clock(), version, version, device_id),
            )
            db.executemany("UPDATE agents SET backlog=? WHERE id=? AND device_id=?", updates)

    # ---- dialogue --------------------------------------------------------

    def ingest(self, device_id: int, agent_id: Any, segments: Any, origin: Any = None) -> dict[str, int]:
        """Store dialogue. origin "import" marks history brought in after the fact.

        Imported history is held: the nightly round leaves it alone until the
        owner starts organising it, since it can be large.
        """
        agent_id = self._require_agent(device_id, agent_id)
        if origin not in (None, "live", "import"):
            raise ApiError(400, "invalid_field", "origin must be live or import")
        imported = 1 if origin == "import" else 0
        if not isinstance(segments, list) or not segments:
            raise ApiError(400, "invalid_field", "segments must be a non-empty list")
        if len(segments) > MAX_BATCH_SEGMENTS:
            raise ApiError(413, "batch_too_large", f"at most {MAX_BATCH_SEGMENTS} segments per request")
        now = self._clock()
        rows = []
        folders: dict[str, str] = {}
        surfaces: dict[str, str] = {}
        for index, segment in enumerate(segments):
            if not isinstance(segment, Mapping):
                raise ApiError(400, "invalid_field", f"segments[{index}] must be an object")
            position = segment.get("position")
            if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position < MAX_POSITION:
                raise ApiError(400, "invalid_field", f"segments[{index}].position must be a non-negative integer")
            role = segment.get("role")
            if role not in ROLES:
                raise ApiError(400, "invalid_field", f"segments[{index}].role must be user or assistant")
            text = _text(segment.get("text"), f"segments[{index}].text", min_len=1, max_len=MAX_TEXT_CHARS)
            ts = _optional_text(segment.get("ts"), f"segments[{index}].ts", max_len=64)
            part = segment.get("part", 0)
            if isinstance(part, bool) or not isinstance(part, int) or not 0 <= part < 10_000:
                raise ApiError(400, "invalid_field", f"segments[{index}].part must be a small non-negative integer")
            cwd = _optional_text(segment.get("cwd"), f"segments[{index}].cwd", max_len=512)
            if cwd:
                folders[str(segment.get("session_id"))[:256]] = normalize_folder(cwd)
            surface = _optional_text(segment.get("surface"), f"segments[{index}].surface", max_len=40)
            if surface:
                surfaces[str(segment.get("session_id"))[:256]] = surface
            rows.append(
                (
                    agent_id,
                    _text(segment.get("segment_uid"), f"segments[{index}].segment_uid", min_len=8, max_len=128),
                    _text(segment.get("session_id"), f"segments[{index}].session_id", min_len=1, max_len=256),
                    _text(segment.get("source_file"), f"segments[{index}].source_file", min_len=1, max_len=512),
                    position,
                    role,
                    text,
                    ts,
                    now,
                    content_key(role, ts, text, part),
                    imported,
                    len(text),
                )
            )
        with self._tx() as db:
            before = db.total_changes
            # The segment_uid is derived from "which file, which position", so a
            # retry after a dropped connection or a reinstalled client is a no-op;
            # the content_key makes a copy of the same message in another file one too.
            db.executemany(
                """
                INSERT OR IGNORE INTO segments(agent_id, segment_uid, session_id, source_file,
                                               position, role, text, ts, received_at, content_key, imported, chars)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
            accepted = db.total_changes - before
            if accepted:
                # Only when something new arrived: a batch of messages already
                # stored then changes nothing, so it costs no disk sync at all.
                db.execute("UPDATE agents SET last_ingest_at=?, segments_total=segments_total+? WHERE id=?", (now, accepted, agent_id))
                spans: dict[str, list[str]] = {}
                for row in rows:
                    if row[7]:
                        span = spans.setdefault(row[2], [row[7], row[7]])
                        span[0], span[1] = min(span[0], row[7]), max(span[1], row[7])
                db.executemany(
                    """
                    INSERT INTO session_spans(agent_id, session_id, first_ts, last_ts) VALUES(?,?,?,?)
                    ON CONFLICT(agent_id, session_id) DO UPDATE SET
                      first_ts = MIN(session_spans.first_ts, excluded.first_ts), last_ts = MAX(session_spans.last_ts, excluded.last_ts)
                    WHERE excluded.first_ts < session_spans.first_ts OR excluded.last_ts > session_spans.last_ts
                    """,
                    [(agent_id, session_id, first, last) for session_id, (first, last) in spans.items()],
                )
                if not imported:
                    self._note_prompts(db, agent_id, [row[7] for row in rows if row[5] == "user" and len(row[6].strip()) >= PROMPT_MIN_CHARS], now)
            self._note_folders(db, agent_id, folders, now)
            self._note_surfaces(db, agent_id, surfaces, now)
            if not imported and accepted < len(rows):
                # A live session that was also imported earlier is not old history:
                # let the nightly round have it.
                keys = [row[9] for row in rows if row[9]]
                for index in range(0, len(keys), 500):
                    chunk = keys[index : index + 500]
                    db.execute(
                        f"UPDATE segments SET imported = 0 WHERE agent_id = ? AND imported = 1 AND content_key IN ({','.join('?' * len(chunk))})",
                        (agent_id, *chunk),
                    )
        return {"accepted": accepted, "duplicates": len(rows) - accepted}

    @staticmethod
    def _note_folders(db, agent_id: int, folders: dict[str, str], now: float) -> None:
        """Which folder each session was working in (written only when it changes)."""
        for session_id, folder in folders.items():
            db.execute(
                """
                INSERT INTO sessions(agent_id, session_id, cwd, updated_at) VALUES(?,?,?,?)
                ON CONFLICT(agent_id, session_id) DO UPDATE SET cwd=excluded.cwd, updated_at=excluded.updated_at
                WHERE sessions.cwd != excluded.cwd
                """,
                (agent_id, session_id, folder, now),
            )

    @staticmethod
    def _note_surfaces(db, agent_id: int, surfaces: dict[str, str], now: float) -> None:
        """Where each session was started (written only when it changes)."""
        for session_id, surface in surfaces.items():
            db.execute(
                """
                INSERT INTO sessions(agent_id, session_id, surface, updated_at) VALUES(?,?,?,?)
                ON CONFLICT(agent_id, session_id) DO UPDATE SET surface=excluded.surface, updated_at=excluded.updated_at
                WHERE sessions.surface != excluded.surface
                """,
                (agent_id, session_id, surface, now),
            )

    def report_sessions(self, device_id: int, agent_id: Any, sessions: Any) -> dict[str, int]:
        """Working folders (and where they were started) of sessions already uploaded."""
        agent_id = self._require_agent(device_id, agent_id)
        if not isinstance(sessions, list) or len(sessions) > 2000:
            raise ApiError(400, "invalid_field", "sessions must be a list of at most 2000 items")
        folders: dict[str, str] = {}
        surfaces: dict[str, str] = {}
        for index, item in enumerate(sessions):
            if not isinstance(item, Mapping):
                raise ApiError(400, "invalid_field", f"sessions[{index}] must be an object")
            session_id = _text(item.get("session_id"), f"sessions[{index}].session_id", min_len=1, max_len=256)
            cwd = _optional_text(item.get("cwd"), f"sessions[{index}].cwd", max_len=512)
            if cwd:
                folders[session_id] = normalize_folder(cwd)
            surface = _optional_text(item.get("surface"), f"sessions[{index}].surface", max_len=40)
            if surface:
                surfaces[session_id] = surface
        with self._tx() as db:
            self._note_folders(db, agent_id, folders, self._clock())
            self._note_surfaces(db, agent_id, surfaces, self._clock())
        return {"recorded": len(set(folders) | set(surfaces))}

    def missing(self, device_id: int, agent_id: Any, asked: Any) -> list[str]:
        """Which of these turns are not stored (by where they were read, or by what they are): their uids."""
        agent_id = self._require_agent(device_id, agent_id)
        if not isinstance(asked, list) or not asked or len(asked) > MAX_BATCH_SEGMENTS:
            raise ApiError(400, "invalid_field", f"segments must be a list of 1 to {MAX_BATCH_SEGMENTS}")
        uids, keys = [], []
        for item in asked:
            if not isinstance(item, Mapping) or not isinstance(item.get("uid"), str) or not isinstance(item.get("key", ""), str):
                raise ApiError(400, "invalid_field", "each segment needs a uid and a key")
            uids.append(item["uid"])
            keys.append(item.get("key") or "")
        known: set[str] = set()
        with self.reading() as db:
            for start in range(0, len(uids), 400):
                part = uids[start : start + 400]
                known.update(row[0] for row in db.execute(
                    f"SELECT segment_uid FROM segments WHERE agent_id = ? AND segment_uid IN ({','.join('?' * len(part))})", (agent_id, *part)))
            same: set[str] = set()
            left = [key for uid, key in zip(uids, keys) if uid not in known and key]
            for start in range(0, len(left), 400):
                part = left[start : start + 400]
                same.update(row[0] for row in db.execute(
                    f"SELECT content_key FROM segments WHERE agent_id = ? AND content_key != '' AND content_key IN ({','.join('?' * len(part))})",
                    (agent_id, *part)))
        return [uid for uid, key in zip(uids, keys) if uid not in known and key not in same]

    def note_verified(self, device_id: int, agent_id: Any, found: Any) -> dict[str, Any]:
        """What a computer found when it compared an agent's files with what is stored."""
        agent_id = self._require_agent(device_id, agent_id)
        if not isinstance(found, Mapping):
            raise ApiError(400, "invalid_field", "found must be an object")
        noted = {key: int(found[key]) for key in ("files", "looked", "segments", "missing", "repaired", "gone", "base")
                 if isinstance(found.get(key), int) and not isinstance(found.get(key), bool) and found[key] >= 0}
        with self._tx() as db:
            before = json.loads(db.execute("SELECT verified FROM agents WHERE id = ?", (agent_id,)).fetchone()[0] or "{}")
            noted["repaired_ever"] = int(before.get("repaired_ever", 0)) + noted.get("repaired", 0)
            noted["at"] = self._clock()
            db.execute("UPDATE agents SET verified = ? WHERE id = ?", (json.dumps(noted), agent_id))
        return noted

    def cursor(self, device_id: int, agent_id: Any) -> dict[str, int]:
        agent_id = self._require_agent(device_id, agent_id)
        with self._lock:
            rows = self._db.execute(
                "SELECT source_file, MAX(position) AS position FROM segments WHERE agent_id=? GROUP BY source_file",
                (agent_id,),
            ).fetchall()
        return {row["source_file"]: row["position"] for row in rows}


def surface_label(value: str) -> str:
    """Where a session was started, as a short label: an agent's own word for it, read generically."""
    word = (value or "").strip().lower()
    if not word:
        return ""
    if "desktop" in word:
        return "桌面"
    if word in ("cli", "terminal", "tui", "shell"):
        return "命令行"
    if any(part in word for part in ("vscode", "jetbrains", "ide", "cursor")):
        return "编辑器"
    if word.startswith("sdk"):
        return "SDK"
    if "web" in word:
        return "网页"
    return value.strip()[:20]
