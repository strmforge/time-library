"""Searching the original words: everything that was said, not only what became a memory.

Distilling keeps what is worth keeping; most of a conversation never becomes a memory, and sometimes the
thing needed is in there: a path, a number, a name, what exactly was said that day. This finds it in the
dialogue itself, and answers with the words around it, who said them, when and where.

Agents ask for it explicitly (it is never handed over unasked), and get short excerpts; the conversation
around one is a second, separate call.

The index is a file of its own (search.db) and can always be rebuilt from the dialogue: SQLite's FTS5
without positions or a copy of the text, over the same words recall uses. It is built in the background,
newest first, a little at a time, so recall and uploads never wait for it.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .errors import ApiError
from .recall import B, K1, _clip, tokens
from .store import Store, surface_label
from .voiceprint import voice_of

log = logging.getLogger("tl_server.words")

INDEX_VERSION = "2"  # change it when the words change: the index is built again
BATCH = 300
PAUSE = 0.25  # seconds between batches while catching up
IDLE = 3.0  # seconds between looks for new dialogue
MAX_QUERY_WORDS = 24
COMMON = 30_000  # a word in more turns than this is not listed, only counted when the turns are read
EXAMINE = 6_000  # candidates whose particulars are looked at (filters may drop most)
READ = 120  # candidates whose words are read
SAME_CHARS = 300  # turns that begin alike this far are the same words in another window
PER_SESSION = 3
MAX_LIMIT = 20
WINDOW = 220  # how close together words must be to count as together
EXCERPT = 320
OWN_WORDS = 1.2
SAME_PLACE = 1.15
TURN_CHARS = 1500
AROUND_CHARS = 700
OWN_CONVERSATION = 600  # seconds: what an agent is being told right now is not an answer to its search

# What the user said and what assistants said are indexed apart: "what did I say" is asked often, and is a
# fraction of it all. turns keeps what conditions are checked against, so that the dialogue itself (large rows
# on slow disks) is only read for what is shown.
ROLES = ("user", "assistant")
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY, agent INTEGER NOT NULL, session TEXT NOT NULL, day TEXT NOT NULL, got REAL NOT NULL);
""" + "".join(f"""
CREATE VIRTUAL TABLE IF NOT EXISTS said_{role} USING fts5(words, content='', detail=none, tokenize="unicode61 remove_diacritics 0");
CREATE VIRTUAL TABLE IF NOT EXISTS vocab_{role} USING fts5vocab(said_{role}, 'row');
""" for role in ROLES)


class WordIndex:
    def __init__(self, store: Store, data_dir: Path | str, projects=None) -> None:
        self._store = store
        self._projects = projects
        self._path = Path(data_dir) / "search.db"
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._db = self._open()

    # ---- building ------------------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=OFF")  # it can be built again
            db.executescript(SCHEMA)
            version = db.execute("SELECT value FROM meta WHERE key='version'").fetchone()
            fits = version is None or version[0] == INDEX_VERSION
        except sqlite3.DatabaseError:
            fits = False
        if not fits:
            db.close()
            for suffix in ("", "-wal", "-shm"):
                Path(str(self._path) + suffix).unlink(missing_ok=True)
            return self._open()
        db.execute("INSERT OR IGNORE INTO meta VALUES('version', ?)", (INDEX_VERSION,))
        return db

    def _meta(self, key: str) -> int | None:
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return int(row[0]) if row else None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="word-index")
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(10)
        with self._lock:
            self._db.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                pause = PAUSE if self.step() else IDLE
            except Exception:  # noqa: BLE001 - it is only an index: try again, never take anything down
                log.exception("word index")
                pause = 30.0
            self._stop.wait(pause)

    def catch_up(self) -> None:
        while self.step():
            pass

    def step(self) -> bool:
        """One batch: what is new first, then further back. False when there is nothing left to do."""
        with self._lock:
            top, bottom = self._meta("top"), self._meta("bottom")
        with self._store.reading() as db:
            if top is None:
                newest = db.execute("SELECT COALESCE(MAX(id), 0) FROM segments").fetchone()[0]
                if not newest:
                    return False
                top = bottom = newest + 1
                with self._lock:
                    self._db.executemany("INSERT OR REPLACE INTO meta VALUES(?,?)", [("top", newest), ("bottom", newest + 1)])
                top = newest
            columns = "id, agent_id, session_id, role, text, ts, received_at"
            rows = db.execute(f"SELECT {columns} FROM segments WHERE id > ? ORDER BY id LIMIT ?", (top, BATCH)).fetchall()
            fresh = bool(rows)
            if not rows and bottom > 1:
                rows = db.execute(f"SELECT {columns} FROM segments WHERE id < ? ORDER BY id DESC LIMIT ?", (bottom, BATCH)).fetchall()
        if not rows:
            if bottom > 1:
                with self._lock:
                    self._db.execute("INSERT OR REPLACE INTO meta VALUES('bottom', 1)")
            return False
        rows = sorted(rows, key=lambda row: row["id"])
        batch = [(row["id"], row["role"], " ".join(dict.fromkeys(tokens(row["text"])))) for row in rows]
        with self._lock:
            self._db.execute("BEGIN")
            try:
                for role in ROLES:
                    self._db.executemany(f"INSERT INTO said_{role}(rowid, words) VALUES(?,?)", [(at, words) for at, who, words in batch if who == role])
                self._db.executemany("INSERT OR REPLACE INTO turns VALUES(?,?,?,?,?)",
                                     [(row["id"], row["agent_id"], row["session_id"], (row["ts"] or "")[:10], row["received_at"]) for row in rows])
                if fresh:
                    self._db.execute("INSERT OR REPLACE INTO meta VALUES('top', ?)", (batch[-1][0],))
                else:
                    self._db.execute("INSERT OR REPLACE INTO meta VALUES('bottom', ?)", (batch[0][0],))
                self._db.execute("INSERT OR REPLACE INTO meta VALUES('count', ?)", ((self._meta("count") or 0) + len(batch),))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return True

    def status(self) -> dict[str, Any]:
        with self._lock:
            indexed, bottom = self._meta("count") or 0, self._meta("bottom")
        with self._store.reading() as db:
            total = db.execute("SELECT COALESCE(SUM(segments_total), 0) FROM agents").fetchone()[0]
        ready = bottom == 1 or not total
        return {"indexed": indexed, "total": max(total, indexed), "ready": ready}

    # ---- searching -----------------------------------------------------------------

    def search(self, query: Any, *, limit: Any = 8, who: Any = "", agent: Any = "", computer: Any = "", project: Any = "",
               since: Any = "", until: Any = "", asking: tuple[int, str] | None = None, folder: Any = "") -> dict[str, Any]:
        """Turns that hold these words, best first. asking = (device, agent) that asks: what it is being told
        right now is left out. folder: where it works; the same project's conversations are lifted a little."""
        if not isinstance(query, str) or not query.strip():
            raise ApiError(400, "invalid_field", "query must be a non-empty string")
        limit = 8 if isinstance(limit, bool) or not isinstance(limit, int) else max(1, min(limit, MAX_LIMIT))
        who = who if who in ("user", "assistant") else ""
        agent, computer, project = (value.strip() if isinstance(value, str) else "" for value in (agent, computer, project))
        since, until = (_day(value, name) for value, name in ((since, "since"), (until, "until")))
        wanted = list(dict.fromkeys(tokens(query)))[:MAX_QUERY_WORDS]
        result: dict[str, Any] = {"hits": [], "words": wanted, "index": self.status()}
        if not wanted:
            return result
        scores, idf = self._candidates(wanted, (who,) if who else ROLES)
        if not scores:
            return result
        ranked = [rowid for rowid, _ in sorted(scores.items(), key=lambda item: (-item[1], -item[0]))[:EXAMINE]]
        chosen = self._filtered(ranked, agent, computer, project, since, until, asking)
        here = self._projects.same_place(asking[0], folder) if asking and self._projects is not None else None
        result["hits"] = self._read(chosen, query, wanted, idf, limit, here)
        return result

    def _candidates(self, wanted: list[str], roles: tuple[str, ...]) -> tuple[dict[int, float], dict[str, float]]:
        with self._lock:
            total = max(1, self._meta("count") or 0)
            marks = ",".join("?" * len(wanted))
            seen: Counter[str] = Counter()
            for role in ROLES:  # how rare a word is, is judged over everything that was said
                for term, count in self._db.execute(f"SELECT term, doc FROM vocab_{role} WHERE term IN ({marks})", wanted):
                    seen[term] += count
            idf = {word: math.log(1 + (total - seen[word] + 0.5) / (seen[word] + 0.5)) for word in wanted if seen.get(word)}
            scores: dict[int, float] = {}
            listed = 0
            for word in sorted(idf, key=lambda item: -idf[item]):
                if listed and seen[word] > COMMON:
                    break  # the rest are commoner still
                for role in roles:
                    for (rowid,) in self._db.execute(f"SELECT rowid FROM said_{role} WHERE said_{role} MATCH ? ORDER BY rowid DESC LIMIT ?",
                                                     (f'"{word}"', COMMON)):
                        scores[rowid] = scores.get(rowid, 0.0) + idf[word]
                listed += 1
        return scores, idf

    def _filtered(self, ranked: list[int], agent: str, computer: str, project: str, since: str, until: str,
                  asking: tuple[int, str] | None) -> list[dict[str, Any]]:
        recent = self._store._clock() - OWN_CONVERSATION
        owner_of = self._projects.owner_of() if project and self._projects is not None else None
        with self._store.reading() as db:
            agents = {row["id"]: row for row in db.execute(
                "SELECT a.id, a.name, a.device_id, d.name AS device FROM agents a JOIN devices d ON d.id = a.device_id")}
        chosen: list[dict[str, Any]] = []
        for start in range(0, len(ranked), 400):
            chunk = ranked[start : start + 400]
            with self._lock:
                turns = {row[0]: row for row in self._db.execute(
                    f"SELECT id, agent, session, day, got FROM turns WHERE id IN ({','.join('?' * len(chunk))})", chunk)}
            for rowid in chunk:
                if rowid not in turns or turns[rowid][1] not in agents:
                    continue
                _, agent_id, session, day, got = turns[rowid]
                who = agents[agent_id]
                if agent and agent.lower() not in who["name"].lower():
                    continue
                if computer and computer.lower() not in who["device"].lower():
                    continue
                if (since and day < since) or (until and (not day or day > until)):
                    continue
                if asking and who["device_id"] == asking[0] and who["name"] == asking[1] and got > recent:
                    continue
                row = {"id": rowid, "agent_id": agent_id, "session_id": session, "agent": who["name"], "device_id": who["device_id"], "device": who["device"]}
                if owner_of is not None:
                    with self._store.reading() as db:
                        at = db.execute("SELECT cwd FROM sessions WHERE agent_id = ? AND session_id = ?", (agent_id, session)).fetchone()
                    if owner_of(who["device_id"], at["cwd"] if at else "") != project:
                        continue
                chosen.append(row)
                if len(chosen) >= READ:
                    return chosen
        return chosen

    def _read(self, rows: list[dict[str, Any]], query: str, wanted: list[str], idf: dict[str, float], limit: int,
              here=None) -> list[dict[str, Any]]:
        if not rows:
            return []
        with self._store.reading() as db:
            said = {row["id"]: row for row in db.execute(
                f"SELECT id, role, text, ts FROM segments WHERE id IN ({','.join('?' * len(rows))})", [row["id"] for row in rows])}
            places = {(row["agent_id"], row["session_id"]): db.execute(
                "SELECT cwd, surface FROM sessions WHERE agent_id = ? AND session_id = ?", (row["agent_id"], row["session_id"])).fetchone() for row in rows}
        for row in rows:
            at = places[(row["agent_id"], row["session_id"])]
            row["cwd"], row["surface"] = (at["cwd"], at["surface"]) if at else ("", "")
        rows = [{**row, "role": said[row["id"]]["role"], "ts": said[row["id"]]["ts"]} for row in rows if row["id"] in said]  # (one may be gone since)
        texts = {at: row["text"] for at, row in said.items()}
        whole = _plain(query)
        average = sum(len(text) for text in texts.values()) / max(1, len(texts))
        scored = []
        for row in rows:
            text = texts.get(row["id"], "")
            counts = Counter(tokens(text))
            norm = K1 * (1 - B + B * len(text) / (average or 1))
            score = sum(idf[word] * counts[word] * (K1 + 1) / (counts[word] + norm) for word in wanted if word in idf and counts[word])
            at, together = _closest(text, [word for word in wanted if counts[word]], idf)
            score += together
            if len(whole) >= 4 and whole in _plain(text):
                score += 3 * max(idf.values())  # said exactly so
            voice = voice_of(row["role"], text, text[max(0, at - 60) : max(0, at - 60) + EXCERPT])
            if voice == "user":
                score *= OWN_WORDS  # the user's own words before an assistant saying them again
            if here is not None and here(row["device_id"], row["cwd"]):
                score *= SAME_PLACE
            scored.append((score, row["id"], at, text, voice, row))
        scored.sort(key=lambda item: (-item[0], -item[1]))
        hits, per_session = [], Counter()
        shown: dict[tuple[str, str], dict[str, Any]] = {}
        owner_of = self._projects.owner_of() if self._projects is not None else None
        for score, _, at, text, voice, row in scored:
            alike = (row["role"], _plain(text[:SAME_CHARS * 2])[:SAME_CHARS])
            if alike in shown:  # the same words, kept again by a window that was resumed or copied
                shown[alike]["same"] += 1
                continue
            key = (row["agent_id"], row["session_id"])
            if per_session[key] >= PER_SESSION or len(hits) >= limit:
                continue
            per_session[key] += 1
            start = max(0, at - 60)
            core = text[start : start + EXCERPT]
            hits.append({
                "segment": row["id"], "session": row["session_id"], "role": row["role"],
                "voice": voice, "ts": row["ts"] or "", "device": row["device"], "agent": row["agent"],
                "surface": surface_label(row["surface"]), "folder": row["cwd"],
                "project": (owner_of(row["device_id"], row["cwd"]) if owner_of else "") or "",
                "text": ("…" if start else "") + core + ("…" if start + EXCERPT < len(text) else ""), "chars": len(text),
                "score": round(score, 2), "same": 0,
            })
            shown[alike] = hits[-1]
        return hits

    # ---- the conversation around a turn -----------------------------------------------

    def around(self, segment_id: int, before: int = 3, after: int = 3) -> dict[str, Any]:
        with self._store.reading() as db:
            row = db.execute(
                """
                SELECT s.*, a.name AS agent, d.name AS device, COALESCE(ss.cwd, '') AS cwd, COALESCE(ss.surface, '') AS surface
                FROM segments s JOIN agents a ON a.id = s.agent_id JOIN devices d ON d.id = a.device_id
                LEFT JOIN sessions ss ON ss.agent_id = s.agent_id AND ss.session_id = s.session_id WHERE s.id = ?
                """, (segment_id,)).fetchone()
            if row is None:
                raise ApiError(404, "segment_not_found", f"no turn {segment_id}")

            def side(order: str, compare: str, count: int) -> list[dict[str, Any]]:
                # By when it was said: a session imported later can hold its turns in another order of arrival.
                found = db.execute(
                    f"""
                    SELECT id, role, text, ts FROM segments WHERE agent_id = ? AND session_id = ?
                      AND (COALESCE(ts, ''), id) {compare} (?, ?) ORDER BY COALESCE(ts, '') {order}, id {order} LIMIT ?
                    """, (row["agent_id"], row["session_id"], row["ts"] or "", row["id"], count)).fetchall()
                turns = [{"segment": item["id"], "role": item["role"], "ts": item["ts"] or "", "text": _clip(item["text"], AROUND_CHARS)} for item in found]
                return list(reversed(turns)) if order == "DESC" else turns

            return {
                "segment": row["id"], "session": row["session_id"], "device": row["device"], "agent": row["agent"],
                "surface": surface_label(row["surface"]), "folder": row["cwd"],
                "before": side("DESC", "<", before),
                "turn": {"segment": row["id"], "role": row["role"], "ts": row["ts"] or "", "text": _clip(row["text"], TURN_CHARS), "chars": row["chars"]},
                "after": side("ASC", ">", after),
            }


def _day(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        raise ApiError(400, "invalid_field", f"{name} must be a day, like 2026-11-23")
    return value.strip()


def _plain(text: str) -> str:
    return "".join(re.findall(r"\w+", text.lower()))


def _closest(text: str, words: list[str], idf: dict[str, float]) -> tuple[int, float]:
    """Where most of the words stand together: (position, what the words found there are worth)."""
    lowered = text.lower()
    places: list[tuple[int, str]] = []
    for word in words:
        at, found = lowered.find(word), 0
        while at != -1 and found < 60:
            places.append((at, word))
            at, found = lowered.find(word, at + 1), found + 1
    if not places:
        return 0, 0.0
    places.sort()
    best_at, best, left, inside, worth = places[0][0], 0.0, 0, Counter(), 0.0
    for at, word in places:
        inside[word] += 1
        if inside[word] == 1:
            worth += idf.get(word, 0.0)
        while at - places[left][0] > WINDOW:
            gone = places[left][1]
            inside[gone] -= 1
            if not inside[gone]:
                worth -= idf.get(gone, 0.0)
            left += 1
        if worth > best + 1e-9:
            best_at, best = places[left][0], worth
    return best_at, best
