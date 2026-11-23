"""Recall: finding the memories that bear on what an agent is doing now.

There is no vector index yet. Memories are short and number in the hundreds
to low thousands, so the server scores them in memory with BM25 over
character bigrams (for Chinese and Japanese, which have no spaces) and words
(for everything else). The index is rebuilt only when the memories change.

Two ways in:
  search    an agent asks on purpose (MCP tool): return the best matches.
  preflight a hook asks with the user's whole prompt before the agent sees
            it: return only clear matches, or nothing, so the agent is not
            handed noise on every turn.
"""

from __future__ import annotations

import math
import re
import secrets
import threading
import time
from collections import Counter
from typing import Any

from .errors import ApiError
from .store import Store, surface_label
from .voiceprint import USER_VOICE_SQL

K1 = 1.2
B = 0.75
MAX_LIMIT = 20
MAX_QUERY_CHARS = 20_000
PREFLIGHT_MIN_QUERY_CHARS = 6
# A preflight match must share at least two distinct words with the prompt and
# score at least as much as about two rare words would (a "rare" word is one
# found in a single memory). Measured in rare words rather than raw points, the
# bar keeps its meaning as the number of memories grows.
# Calibrated 2026-11-17 on 466 real memories. Newly worded questions about past
# topics: the right memory ranked first in 9 of 10, scoring 2.1-7.9 rare words;
# long prompts about something else drew incidental matches of 3.0-4.5. Word
# matching cannot separate those ranges completely (meaning-based search will),
# and a wrong memory pushed into every prompt costs more than a missed one the
# agent can still look up: so the bar favours being right over saying something.
# At 3.5: 6 of 10 answered, none wrong; 1 of 12 real prompts drew noise.
PREFLIGHT_MIN_RARE_WORDS = 3.5
PREFLIGHT_MIN_SHARED = 2
PREFLIGHT_LIMIT = 3
# With recall by meaning, preflight hands over only memories the reranker scores
# at least this high. Measured on the server's 50 test questions and 20 everyday
# prompts: 90% of right answers scored 4.5 or more, no everyday prompt above 4.05.
PREFLIGHT_RERANK_MIN = 5.0
# From this many memories on, rebuilding the word index takes seconds: recall
# answers from the index in hand while a fresh one is built in the background.
BACKGROUND_REBUILD_FROM = 5000
REBUILD_AT_MOST_EVERY = 60.0  # seconds; an import adds memories every few seconds
# Search merges the two lists (by words, by meaning) by rank: reciprocal rank fusion.
# Words count for less: on 300 real questions in other words they found the right
# memory in the first ten 61% of the time, meaning 83%, and an equal share pulled
# the merged list down. They still decide when a question names an exact thing
# (a path, a version, an id). The first RERANK_DEPTH are then read again, question
# and memory together, by the reranker. Measured end to end (first 1 / 5 / 10):
# words alone 28 / 51 / 61%; this 57 / 83 / 90% (reranking 10: 56 / 83 / 86%, 30: 57 / 82 / 89%).
FUSE_DEPTH = 100
RRF_K = 60
WORDS_WEIGHT = 0.25
RERANK_DEPTH = 20
CONTEXT_TURNS = 2
CONTEXT_CHARS = 600
EVIDENCE_WINDOW = 800

_CJK = r"぀-ヿ㐀-䶿一-鿿豈-﫿"
_RUNS = re.compile(rf"[{_CJK}]+|[A-Za-z0-9]+")
_IS_CJK = re.compile(rf"[{_CJK}]")

STOP = set(
    """
    这个 那个 一个 我们 你们 他们 可以 什么 现在 就是 还是 但是 因为 所以 如果 没有 不是 已经 这样 那样
    然后 一下 的话 时候 东西 怎么 这些 那些 自己 需要 应该 可能 知道 觉得 这次 一些 以后 之后 之前 里面
    还有 一样 不要 不会 是不 我的 你的 在这 这里 那里 也是 都是 有没 是的 的是 了一 在的 有的 这是 那是
    我在 你在 一直 其实 还要 而且 或者 比如 然后 直接 一起 只是 为了 关于 对于 进行 通过 以及 他的 它的
    the and for to of a an is in it this that be with on as are not or if we you i do does at by from
    """.split()
)


def tokens(text: str) -> list[str]:
    out: list[str] = []
    for run in _RUNS.findall(text):
        if _IS_CJK.match(run):
            if len(run) == 1:
                out.append(run)
            else:
                out.extend(run[index : index + 2] for index in range(len(run) - 1))
        else:
            word = run.lower()
            if len(word) >= 2 or word.isdigit():
                out.append(word)
    return [token for token in out if token not in STOP]


class _Index:
    def __init__(self, docs: list[tuple[int, list[str] | Counter]]) -> None:
        self.ids = [doc_id for doc_id, _ in docs]
        self.members = set(self.ids)
        self.tf = [words if isinstance(words, Counter) else Counter(words) for _, words in docs]
        self.length = [sum(counts.values()) for counts in self.tf]
        self.avg = (sum(self.length) / len(self.length)) if self.length else 0.0
        df: Counter[str] = Counter()
        for counts in self.tf:
            df.update(counts.keys())
        total = len(docs)
        self.idf = {token: math.log(1 + (total - count + 0.5) / (count + 0.5)) for token, count in df.items()}
        # What one word found in a single memory is worth.
        self.rare = math.log(1 + (total - 0.5) / 1.5) if total else 1.0

    def score(self, query: list[str]) -> list[tuple[int, float, int]]:
        """(memory id, bm25 score, number of distinct words shared with the query)."""
        wanted = set(query)
        results = []
        for position, counts in enumerate(self.tf):
            shared = wanted.intersection(counts)
            if not shared:
                continue
            norm = K1 * (1 - B + B * self.length[position] / (self.avg or 1))
            score = sum(self.idf[t] * counts[t] * (K1 + 1) / (counts[t] + norm) for t in shared)
            results.append((self.ids[position], score, len(shared)))
        results.sort(key=lambda item: item[1], reverse=True)
        return results


# Borrowing and returning. Every memory handed to an agent is a loan; when the
# agent has done its work it can return the memory with a verdict: it helped,
# it did not matter, or it misled. Usefulness then comes from this ledger, not
# from a model's guess, and later steps (memories that sink from disuse, upgrade
# candidates, errata) read it.
LOANS_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_loans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  delivery_id TEXT NOT NULL,
  memory_id INTEGER NOT NULL,
  device_id INTEGER,
  agent TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL,
  query TEXT NOT NULL DEFAULT '',
  lent_at REAL NOT NULL,
  outcome TEXT,
  note TEXT NOT NULL DEFAULT '',
  returned_at REAL
);
CREATE INDEX IF NOT EXISTS idx_loans_memory ON memory_loans(memory_id, lent_at);
CREATE INDEX IF NOT EXISTS idx_loans_open ON memory_loans(device_id, memory_id, returned_at);
"""
OUTCOMES = ("useful", "useless", "misleading")
MAX_NOTE_CHARS = 300
MAX_RETURNS = 20
LEDGER_SECONDS = 2


class Recall:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._lock = threading.Lock()
        self._index: _Index | None = None
        self._signature: tuple | None = None
        self._rebuilding = False
        self._build_lock = threading.Lock()
        self._built_at = 0.0
        # Each memory's words, kept between builds: a rebuild only reads and splits
        # the memories that are new or whose evidence changed.
        self._words: dict[int, tuple[int, Counter]] = {}
        self.vectors = None  # recall by meaning, when the server has it switched on (vectors.py)
        # Who borrowed what is written in the background, a batch at a time: an
        # agent waiting for memories must never wait for the disk.
        self._pending: list[tuple] = []
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._ledger_loop, daemon=True, name="recall-ledger").start()
        with store._lock:
            columns = {row["name"] for row in store._db.execute("PRAGMA table_info(memories)")}
            if "recall_count" not in columns:
                store._db.execute("ALTER TABLE memories ADD COLUMN recall_count INTEGER NOT NULL DEFAULT 0")
            if "last_recalled_at" not in columns:
                store._db.execute("ALTER TABLE memories ADD COLUMN last_recalled_at REAL")
            store._db.executescript(LOANS_SCHEMA)

    def _ledger_loop(self) -> None:
        while not self._stop.wait(LEDGER_SECONDS):
            try:
                self.flush()
            except Exception:  # noqa: BLE001 - try again next time; never take recall down
                pass

    def flush(self) -> None:
        """Write the loans recorded so far."""
        with self._pending_lock:
            pending, self._pending = self._pending, []
        if not pending:
            return
        try:
            with self._store._tx() as db:
                db.executemany(
                    "UPDATE memories SET recall_count = recall_count + 1, last_recalled_at = MAX(COALESCE(last_recalled_at, 0), ?) WHERE id = ?",
                    [(lent_at, memory_id) for (_d, memory_id, _dev, _a, _m, _q, lent_at) in pending],
                )
                db.executemany(
                    "INSERT INTO memory_loans(delivery_id, memory_id, device_id, agent, mode, query, lent_at) VALUES(?,?,?,?,?,?,?)",
                    pending,
                )
        except Exception:
            with self._pending_lock:
                self._pending = pending + self._pending
            raise

    def shutdown(self) -> None:
        self._stop.set()
        self.flush()

    def _signature_now(self) -> tuple:
        with self._store.reading() as db:
            return tuple(
                db.execute(
                    "SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(SUM(CASE WHEN status='active' THEN id END), 0), "
                    "(SELECT COALESCE(MAX(id), 0) FROM memory_evidence) FROM memories"
                ).fetchone()
            )

    def _build(self, signature: tuple) -> _Index:
        with self._build_lock:
            if self._index is not None and self._signature == signature:
                return self._index  # built meanwhile by another caller
            with self._store.reading() as db:
                active = db.execute(
                    """
                    SELECT m.id, COALESCE((SELECT MAX(e.id) FROM memory_evidence e WHERE e.memory_id = m.id), 0) AS mark
                    FROM memories m WHERE m.status = 'active'
                    """
                ).fetchall()
                stale = [row["id"] for row in active if self._words.get(row["id"], (None,))[0] != row["mark"]]
                fresh: dict[int, str] = {}
                for start in range(0, len(stale), 500):
                    chunk = stale[start : start + 500]
                    for row in db.execute(
                        f"""
                        SELECT m.id, m.statement,
                               (SELECT GROUP_CONCAT(e.quote, ' ') FROM memory_evidence e WHERE e.memory_id = m.id) AS quotes
                        FROM memories m WHERE m.id IN ({','.join('?' * len(chunk))})
                        """,
                        chunk,
                    ):
                        fresh[row["id"]] = f"{row['statement']} {row['quotes'] or ''}"
            marks = {row["id"]: row["mark"] for row in active}
            for memory_id, text in fresh.items():
                self._words[memory_id] = (marks[memory_id], Counter(tokens(text)))
            for memory_id in [memory_id for memory_id in self._words if memory_id not in marks]:
                del self._words[memory_id]  # no longer in play
            index = _Index([(row["id"], self._words[row["id"]][1]) for row in active if row["id"] in self._words])
            with self._lock:
                self._index, self._signature = index, signature
                self._built_at = time.monotonic()
            return index

    def _current_index(self) -> _Index:
        """The word index. A large library is never waited on: while memories are being added (an import
        adds them every few seconds), recall answers from the index in hand and a fresh one is built beside it."""
        signature = self._signature_now()
        with self._lock:
            index, current = self._index, self._signature
            if index is not None and signature == current:
                return index
            stale_ok = (index is not None and len(index.ids) >= BACKGROUND_REBUILD_FROM and not self._rebuilding
                        and time.monotonic() - self._built_at >= REBUILD_AT_MOST_EVERY)
            if stale_ok:
                self._rebuilding = True
        if index is not None and len(index.ids) >= BACKGROUND_REBUILD_FROM:
            if stale_ok:
                threading.Thread(target=self._rebuild_beside, args=(signature,), daemon=True, name="recall-index").start()
            return index
        return self._build(signature)

    def _rebuild_beside(self, signature: tuple) -> None:
        try:
            self._build(signature)
        except Exception:  # noqa: BLE001 - the next recall tries again
            pass
        finally:
            with self._lock:
                self._rebuilding = False

    def warm(self) -> None:
        """Build the index once at startup, so the first recall does not wait for it."""
        threading.Thread(target=lambda: self._build(self._signature_now()), daemon=True, name="recall-warm").start()

    def recall(self, query: Any, *, limit: Any = 5, mode: str = "search", device_id: int | None = None, agent: Any = None,
               lend: bool = True, by_meaning: bool = True) -> dict[str, Any]:
        """lend=False: a look for the server's own checks, not a loan to an agent (nothing is recorded).
        by_meaning=False: by words alone, as recall was before (for comparison)."""
        if not isinstance(query, str) or not query.strip():
            raise ApiError(400, "invalid_field", "query must be a non-empty string")
        query = query[:MAX_QUERY_CHARS]
        if isinstance(limit, bool) or not isinstance(limit, int):
            limit = 5
        limit = max(1, min(limit, MAX_LIMIT))
        if mode == "preflight":
            limit = min(limit, PREFLIGHT_LIMIT)
            if len(query.strip()) < PREFLIGHT_MIN_QUERY_CHARS:
                return {"memories": [], "mode": mode}
        index = self._current_index()
        ranked = index.score(tokens(query))
        by_meaning = by_meaning and self.vectors is not None and self.vectors.ready()
        if mode == "preflight" and not by_meaning:
            # Words alone: only a match on several rare words is close enough to hand over unasked.
            bar = PREFLIGHT_MIN_RARE_WORDS * index.rare
            ranked = [item for item in ranked if item[1] >= bar and item[2] >= PREFLIGHT_MIN_SHARED]
        words = {memory_id: (score, shared) for memory_id, score, shared in ranked[:FUSE_DEPTH]}
        meaning: dict[int, float] = {}
        if by_meaning:
            # By meaning too: only memories that are in play (the word index holds exactly those).
            meaning = {memory_id: similarity for memory_id, similarity in self.vectors.search(query, FUSE_DEPTH)
                       if memory_id in index.members}
        if meaning:
            fused: dict[int, float] = {}
            for weight, order in ((WORDS_WEIGHT, [memory_id for memory_id, _, _ in ranked[:FUSE_DEPTH]]), (1.0, list(meaning))):
                for rank, memory_id in enumerate(order, start=1):
                    fused[memory_id] = fused.get(memory_id, 0.0) + weight / (RRF_K + rank)
            merged = [memory_id for memory_id, _ in sorted(fused.items(), key=lambda item: -item[1])]
            head = merged[:RERANK_DEPTH]
            with self._store.reading() as db:
                texts = {
                    row[0]: (row[2] + ":" if row[2] else "") + row[1]
                    for row in db.execute(
                        f"SELECT id, statement, title FROM memories WHERE id IN ({','.join('?' * len(head))})", head
                    )
                }
            scored = self.vectors.rerank_scores(query, [(memory_id, texts[memory_id]) for memory_id in head if memory_id in texts])
            if mode == "preflight":
                # Handed over unasked: only what the reranker finds clearly about this prompt.
                if scored is None:
                    bar = PREFLIGHT_MIN_RARE_WORDS * index.rare
                    chosen_ids = [memory_id for memory_id, score, shared in ranked
                                  if score >= bar and shared >= PREFLIGHT_MIN_SHARED][:limit]
                else:
                    chosen_ids = [memory_id for memory_id, score in scored if score >= PREFLIGHT_RERANK_MIN][:limit]
            else:
                if scored:
                    reranked = [memory_id for memory_id, _ in scored]
                    merged = reranked + [memory_id for memory_id in merged if memory_id not in set(reranked)]
                chosen_ids = merged[:limit]
        else:
            chosen_ids = [memory_id for memory_id, _, _ in ranked[:limit]]
        memories = self._load(chosen_ids)
        for memory in memories:
            score, shared = words.get(memory["id"], (0.0, 0))
            # Relevance in "rare words' worth": comparable however many memories there are.
            memory["relevance"] = round(score / index.rare, 2)
            memory["shared_words"] = shared
            if memory["id"] in meaning:
                memory["similarity"] = round(meaning[memory["id"]], 3)
            memory["matched_by"] = "both" if shared and memory["id"] in meaning else ("meaning" if memory["id"] in meaning else "words")
        delivery_id = self.lend([memory["id"] for memory in memories], device_id=device_id, agent=agent, mode=mode,
                                query=query) if lend else ""
        return {"memories": memories, "mode": mode, "delivery_id": delivery_id}

    def lend(self, memory_ids: list[int], *, device_id: int | None, agent: Any, mode: str, query: str) -> str:
        """Record memories as lent to an agent (written in the background); the delivery's id."""
        if not memory_ids:
            return ""
        delivery_id = secrets.token_hex(6)
        now = self._store._clock()
        agent_name = agent[:120] if isinstance(agent, str) else ""
        with self._pending_lock:
            self._pending.extend(
                (delivery_id, memory_id, device_id, agent_name, mode, query[:200], now) for memory_id in memory_ids
            )
        return delivery_id

    def give_back(self, returns: Any, *, device_id: int | None, agent: Any = None) -> dict[str, Any]:
        """Return borrowed memories with a verdict. Closes the latest open loan, or records one."""
        if not isinstance(returns, list) or not returns or len(returns) > MAX_RETURNS:
            raise ApiError(400, "invalid_field", f"returns must be a list of 1 to {MAX_RETURNS} items")
        agent_name = agent[:120] if isinstance(agent, str) else ""
        self.flush()  # the loans being returned must be on record first
        cleaned = []
        for index, item in enumerate(returns):
            if not isinstance(item, dict):
                raise ApiError(400, "invalid_field", f"returns[{index}] must be an object")
            memory_id, outcome, note = item.get("memory_id"), item.get("outcome"), item.get("note", "")
            if isinstance(memory_id, bool) or not isinstance(memory_id, int):
                raise ApiError(400, "invalid_field", f"returns[{index}].memory_id must be a memory number")
            if outcome not in OUTCOMES:
                raise ApiError(400, "invalid_field", f"returns[{index}].outcome must be one of {', '.join(OUTCOMES)}")
            if not isinstance(note, str):
                raise ApiError(400, "invalid_field", f"returns[{index}].note must be text")
            cleaned.append((memory_id, outcome, note.strip()[:MAX_NOTE_CHARS]))
        now = self._store._clock()
        recorded = []
        with self._store._tx() as db:
            for memory_id, outcome, note in cleaned:
                if db.execute("SELECT 1 FROM memories WHERE id = ?", (memory_id,)).fetchone() is None:
                    raise ApiError(404, "memory_not_found", f"no memory {memory_id}")
                loan = db.execute(
                    """
                    SELECT id FROM memory_loans WHERE memory_id = ? AND device_id IS ? AND returned_at IS NULL
                    ORDER BY lent_at DESC, id DESC LIMIT 1
                    """,
                    (memory_id, device_id),
                ).fetchone()
                if loan is None:
                    # Returned without a loan we know of (for example read some other way): still a verdict.
                    loan_id = db.execute(
                        "INSERT INTO memory_loans(delivery_id, memory_id, device_id, agent, mode, lent_at) VALUES('', ?, ?, ?, 'direct', ?)",
                        (memory_id, device_id, agent_name, now),
                    ).lastrowid
                else:
                    loan_id = loan["id"]
                db.execute(
                    "UPDATE memory_loans SET outcome = ?, note = ?, returned_at = ?, agent = CASE WHEN agent = '' THEN ? ELSE agent END WHERE id = ?",
                    (outcome, note, now, agent_name, loan_id),
                )
                recorded.append({"memory_id": memory_id, "outcome": outcome})
        return {"recorded": recorded}

    def _load(self, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        with self._store.reading() as db:
            rows = {
                row["id"]: row
                for row in db.execute(
                    f"""
                    SELECT m.*, a.name AS agent, d.name AS device,
                           COALESCE((SELECT ss.surface FROM sessions ss WHERE ss.agent_id = m.agent_id AND ss.session_id = m.session_id), '') AS surface,
                           (SELECT COUNT(*) FROM memory_links k WHERE k.relation = 'derived_from' AND k.from_id = m.id) AS sources
                    FROM memories m JOIN agents a ON a.id = m.agent_id JOIN devices d ON d.id = a.device_id
                    WHERE m.id IN ({marks})
                    """,
                    ids,
                )
            }
            evidence: dict[int, list[dict[str, Any]]] = {}
            for row in db.execute(
                f"""
                SELECT e.memory_id, e.quote, e.voice, s.role, s.ts FROM memory_evidence e
                LEFT JOIN segments s ON s.id = e.segment_id WHERE e.memory_id IN ({marks}) ORDER BY e.id
                """,
                ids,
            ):
                said = evidence.setdefault(row["memory_id"], [])
                if any(item["quote"] == row["quote"] for item in said):
                    continue  # the same words from another conversation: once is enough to read
                voice = row["voice"] or ("user" if row["role"] == "user" else "assistant")
                said.append({"quote": row["quote"], "role": row["role"], "voice": voice, "ts": row["ts"] or ""})
            verdicts = loan_verdicts(db, ids)
        return [
            {
                "id": memory_id,
                "statement": rows[memory_id]["statement"],
                "kind": rows[memory_id]["kind"],
                "created_at": rows[memory_id]["created_at"],
                "device": rows[memory_id]["device"],
                "agent": rows[memory_id]["agent"],
                "surface": surface_label(rows[memory_id]["surface"]),
                "evidence": evidence.get(memory_id, []),
                "returns": verdicts.get(memory_id, {outcome: 0 for outcome in OUTCOMES}),
                "note": voice_note(
                    rows[memory_id]["kind"], rows[memory_id]["statement"],
                    any(item["voice"] == "user" for item in evidence.get(memory_id, [])),
                    pasted=any(item["voice"] == "relayed" for item in evidence.get(memory_id, [])),
                ) if rows[memory_id]["kind"] != "experience" else "",
                # An experience card: drawn up from several memories, with when it applies.
                **({"title": rows[memory_id]["title"], "when": rows[memory_id]["when_to_use"], "sources": rows[memory_id]["sources"]}
                   if rows[memory_id]["kind"] == "experience" else {}),
            }
            for memory_id in ids
            if memory_id in rows
        ]

    def source(self, memory_id: int) -> dict[str, Any]:
        """The conversation around each piece of evidence: the original words, on demand."""
        with self._store.reading() as db:
            memory = db.execute(
                "SELECT m.* FROM memories m WHERE m.id = ?", (memory_id,)
            ).fetchone()
            if memory is None:
                raise ApiError(404, "memory_not_found")
            items = []
            for row in db.execute(
                """
                SELECT e.quote, s.id AS segment_id, s.agent_id, s.session_id, s.role, s.text, s.ts
                FROM memory_evidence e JOIN segments s ON s.id = e.segment_id WHERE e.memory_id = ? ORDER BY e.id
                """,
                (memory_id,),
            ).fetchall():
                def around(order: str, compare: str) -> list[dict[str, str]]:
                    found = db.execute(
                        f"""
                        SELECT role, text FROM segments
                        WHERE agent_id = ? AND session_id = ? AND id {compare} ? ORDER BY id {order} LIMIT ?
                        """,
                        (row["agent_id"], row["session_id"], row["segment_id"], CONTEXT_TURNS),
                    ).fetchall()
                    turns = [{"role": item["role"], "text": _clip(item["text"], CONTEXT_CHARS)} for item in found]
                    return list(reversed(turns)) if order == "DESC" else turns

                text = row["text"]
                at = text.find(row["quote"])
                start = max(0, at - EVIDENCE_WINDOW) if at >= 0 else 0
                end = min(len(text), (at + len(row["quote"]) + EVIDENCE_WINDOW) if at >= 0 else 2 * EVIDENCE_WINDOW)
                items.append(
                    {
                        "quote": row["quote"],
                        "before": around("DESC", "<"),
                        "turn": {
                            "role": row["role"],
                            "ts": row["ts"] or "",
                            "text": ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else ""),
                        },
                        "after": around("ASC", ">"),
                    }
                )
        found = {"id": memory["id"], "statement": memory["statement"], "status": memory["status"], "evidence": items}
        if "folded_into" in memory.keys() and memory["folded_into"]:
            found["folded_into"] = memory["folded_into"]  # a restatement: the memory it repeats
        with self._store.reading() as db:
            replaced = db.execute(
                "SELECT from_id, reason FROM memory_links WHERE relation = 'replaces' AND to_id = ? AND undone_at IS NULL ORDER BY id DESC LIMIT 1",
                (memory_id,),
            ).fetchone()
            sources = [row[0] for row in db.execute(
                "SELECT to_id FROM memory_links WHERE relation = 'derived_from' AND from_id = ? ORDER BY to_id", (memory_id,)
            )]
        if replaced is not None and memory["status"] == "superseded":
            found["replaced_by"] = {"id": replaced[0], "reason": replaced[1]}
        if sources:
            found["derived_from"] = sources  # an experience card: the memories it was drawn up from
        return found


# A memory that speaks for the user (a preference, a correction, "用户要求…")
# should rest on something the user said. When its evidence holds only the
# assistant's words, it is the assistant's reading of the user, and it says so
# wherever it is shown, so no agent takes it for the user's own voice.
USER_CLAIM = re.compile(r"用户|\buser\b", re.IGNORECASE)
RELAYED_NOTE = "没有用户原话,是助手的转述"
PASTED_NOTE = "引的是用户贴进来的别人的话(别的 AI 的报告、文章),不是用户本人的说法"


def speaks_for_user(kind: str, statement: str) -> bool:
    return kind in ("preference", "correction") or bool(USER_CLAIM.search(statement or ""))


def voice_note(kind: str, statement: str, user_quoted: bool, pasted: bool = False) -> str:
    if not speaks_for_user(kind, statement) or user_quoted:
        return ""
    return PASTED_NOTE if pasted else RELAYED_NOTE


def user_quoted_ids(db, ids: list[int]) -> set[int]:
    """Which of these memories quote something the user said (their own words, not a paste)."""
    found: set[int] = set()
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        marks = ",".join("?" * len(chunk))
        found.update(
            row[0]
            for row in db.execute(
                f"""
                SELECT DISTINCT e.memory_id FROM memory_evidence e JOIN segments s ON s.id = e.segment_id
                WHERE e.memory_id IN ({marks}) AND {USER_VOICE_SQL}
                """,
                chunk,
            )
        )
    return found


def loan_verdicts(db, ids: list[int]) -> dict[int, dict[str, int]]:
    """How each memory was judged when agents returned it."""
    found: dict[int, dict[str, int]] = {}
    if not ids:
        return found
    marks = ",".join("?" * len(ids))
    for row in db.execute(
        f"SELECT memory_id, outcome, COUNT(*) AS n FROM memory_loans WHERE memory_id IN ({marks}) AND outcome IS NOT NULL GROUP BY memory_id, outcome",
        ids,
    ):
        found.setdefault(row["memory_id"], {outcome: 0 for outcome in OUTCOMES})[row["outcome"]] = row["n"]
    return found


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"
