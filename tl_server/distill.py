"""Distillation: turning stored dialogue into memories that carry their evidence.

A model reads a stretch of dialogue and proposes memories. Each memory must
point at the exact words that support it. The server then checks every quote
against the stored text, character for character: a quote that is not really
there is thrown away, and a memory left without any real quote is not kept.
The model proposes; a deterministic check decides.

Progress is kept per conversation, so a run that is interrupted (balance ran
out, endpoint unreachable, server restarted) picks up where it stopped and
never distills the same dialogue twice.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from typing import Any

from . import model_client
from .errors import ApiError
from .folding import StatementIndex
from .evolution import shelf_of
from .model_client import ModelError
from .model_registry import ModelRegistry
from .projects import _epoch, _owner
from .recall import LOANS_SCHEMA, OUTCOMES, loan_verdicts, tokens, user_quoted_ids, voice_note
from .voiceprint import RULES_VERSION as VOICE_RULES
from .voiceprint import add_evidence, is_user_voice, own_part, relayed, voice_of
from .store import Store, surface_label

log = logging.getLogger("tl_server.distill")

WINDOW_CHARS = 12_000
SEGMENT_PROMPT_CHARS = 3_000
MAX_QUOTE_CHARS = 300
MAX_STATEMENT_CHARS = 500
MAX_MEMORIES_PER_WINDOW = 8
MAX_OUTPUT_TOKENS = 4_000
CALL_TIMEOUT = 240
KINDS = ("decision", "preference", "correction", "fact", "lesson")
DEFAULT_RETENTION_DAYS = 30
NIGHTLY_HOUR = 2
# A call that fails for a passing reason (timed out, endpoint busy) is tried
# again after these pauses before the model counts as unavailable.
RETRY_DELAYS = (15, 60)
TRANSIENT_REASONS = ("unreachable",)
# After a round stops because no model answered (out of balance, key revoked,
# unreachable), the server tries again on its own this often, so topping up
# is all the owner has to do.
RESUME_AFTER_SECONDS = 30 * 60
RESUMABLE_REASONS = ("unreachable", "quota", "auth", "http", "not_found")

# Two jobs share one worker. "daily" organises what arrives live, every night.
# "import" organises history brought in after the fact: it is held until the
# owner starts it (it can be large), uses its own model slot, can be paused,
# and steps aside for the nightly round, then carries on by itself.
JOBS = ("daily", "import")
# Each job keeps its own position in a conversation.
PROGRESS_PREFIX = {"daily": "", "import": "import:"}
# How a round ended. "yielded": an import round that stepped aside for the
# nightly one; "interrupted": cut off by a restart. Both carry on by themselves.
CARRY_ON_STATUSES = ("yielded", "interrupted")
# Rough tokens per stored character, for estimates before real runs are measured.
DEFAULT_INPUT_TOKENS_PER_CHAR = 0.67
DEFAULT_OUTPUT_TOKENS_PER_CHAR = 0.11
MIN_MEASURED_CHARS = 20_000
# Conversations distilled at once in one round (online models; the machine's own model takes one at a time).
PARALLEL = {"daily": 1, "import": 4}
# Which part of the imported history to organise: recent months, some agents,
# some projects or folders. What lies outside waits, untouched.
SCOPE_MONTHS = (0, 1, 3, 6, 12)
MONTH_SECONDS = 30 * 86400
FOLDER_CHOICES = 15
ALL_HISTORY = {"months": 0, "agents": None, "groups": None, "rest": False, "listed": []}

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fingerprint TEXT NOT NULL UNIQUE,
  statement TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  agent_id INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  expired_at REAL,
  expire_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status, created_at);
CREATE TABLE IF NOT EXISTS memory_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  memory_id INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  segment_id INTEGER NOT NULL,
  quote TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_memory ON memory_evidence(memory_id);
CREATE TABLE IF NOT EXISTS distill_progress (
  agent_id INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  last_segment_id INTEGER NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY (agent_id, session_id)
);
CREATE TABLE IF NOT EXISTS memory_folds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kept_id INTEGER NOT NULL,
  folded_statement TEXT NOT NULL,
  folded_at REAL NOT NULL
);
-- How memories change: one replaces another, an experience card rests on
-- memories, an owner keeps one the evidence would have dropped. Each row is a
-- receipt: who decided, why. Undone links stay, marked undone.
CREATE TABLE IF NOT EXISTS memory_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  relation TEXT NOT NULL,
  from_id INTEGER NOT NULL,
  to_id INTEGER NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  decided_by TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  undone_at REAL
);
CREATE INDEX IF NOT EXISTS idx_links_from ON memory_links(from_id, relation);
CREATE INDEX IF NOT EXISTS idx_links_to ON memory_links(to_id, relation);
-- Pairs of memories close in wording but different in a detail: waiting for a
-- model to say whether the later one replaces the earlier.
CREATE TABLE IF NOT EXISTS review_pairs (
  later_id INTEGER NOT NULL,
  earlier_id INTEGER NOT NULL,
  similarity REAL NOT NULL,
  queued_at REAL NOT NULL,
  verdict TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  decided_at REAL,
  PRIMARY KEY (later_id, earlier_id)
);
CREATE TABLE IF NOT EXISTS distill_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,
  started_at REAL NOT NULL,
  finished_at REAL,
  status TEXT NOT NULL,
  windows INTEGER NOT NULL DEFAULT 0,
  segments INTEGER NOT NULL DEFAULT 0,
  memories INTEGER NOT NULL DEFAULT 0,
  rejected INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  model TEXT NOT NULL DEFAULT '',
  error_reason TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT ''
);
"""

SYSTEM_PROMPT = """你在为一个 AI 助手的长期记忆库做提炼。下面是一段用户与 AI 助手的对话(工具调用等运行过程已经去掉)。请找出其中"以后还用得上"的内容,写成一条条记忆。

值得记的:
- decision 决定:定下来的方案、取舍、范围
- preference 偏好:用户希望事情怎样做、自己怎样被对待
- correction 纠正:用户指出助手做错或想错的地方,以及正确的做法
- fact 事实:关于用户、项目、设备、环境的稳定信息
- lesson 教训:踩过的坑,和由此得到的做法

不要记的:
- 一次性的进度播报、当下任务的中间步骤、寒暄
- 只在当时有用的运行状态(某条命令的输出、某次测试的具体数字)
- 很快就会过时的状态:当前版本号或构建号、测试通过了几项、某个功能"还没做""做到哪一步"、这一次的排查或测试计划
- 助手的客套话

替用户说话要有用户的原话:
- preference 和 correction 的 evidence 里至少要有一句标着"用户"的段落里的原话
- statement 写成"用户要求/希望/纠正/认为……"时也一样
- 只有助手的说法、没有用户原话时,不要写成用户的意思;确实值得记,就写成助手提出或定下的(例如"助手建议……""定下……")
- 标着"用户(转贴)"的段落是用户贴进来的别人的内容(别的 AI 的报告、文章),里面的话不是用户本人说的;用户段落里"## My request"之前是软件自动附上的上下文(网页、文件、之前的回答),不算用户的原话,只有其中 Comment: 下面和 "annotation" 里写的批注是用户本人写的

每条记忆的要求:
- statement:一句完整的话,脱离这段对话也能看懂(写清是谁、哪个项目、什么东西),用对话本身的语言
- kind:decision / preference / correction / fact / lesson 之一
- evidence:1 到 3 条原话。每条给出所在段落的编号 n,以及从该段落里逐字复制的一小段 quote(不超过 120 字;不许改写,不许用省略号拼接)

宁缺毋滥,最多 8 条。没有值得记的就返回空列表。

只输出 JSON,不要任何别的文字。格式:
{"memories":[{"statement":"…","kind":"decision","evidence":[{"n":1,"quote":"…"}]}]}"""

ROLE_LABELS = {"user": "用户", "assistant": "助手"}


def build_prompt(window: list[dict[str, Any]]) -> str:
    lines = ["对话:"]
    for number, segment in enumerate(window, start=1):
        text = segment["text"]
        if len(text) > SEGMENT_PROMPT_CHARS:
            text = text[:SEGMENT_PROMPT_CHARS] + "\n(这一段后面还有内容,已省略)"
        label = ROLE_LABELS.get(segment["role"], segment["role"])
        if segment["role"] == "user" and relayed(own_part(segment["text"])):
            label = "用户(转贴)"
        lines.append(f"[{number}] {label}: {text}")
    return "\n\n".join(lines)


def parse_reply(text: str) -> list[dict[str, Any]]:
    """Pull the proposed memories out of a model reply. Raises ValueError if the
    reply is not the JSON that was asked for."""
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the reply")
    payload = json.loads(cleaned[start : end + 1])
    memories = payload.get("memories") if isinstance(payload, dict) else None
    if not isinstance(memories, list):
        raise ValueError("reply has no memories list")
    return [item for item in memories if isinstance(item, dict)]


def verify(proposed: list[dict[str, Any]], window: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep only memories whose quotes really occur in the stored dialogue.

    Returns (accepted, rejected_count). Nothing here trusts the model: a quote
    must be an exact substring of the segment it names.
    """
    accepted: list[dict[str, Any]] = []
    rejected = 0
    for item in proposed[:MAX_MEMORIES_PER_WINDOW]:
        statement = item.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            rejected += 1
            continue
        statement = statement.strip()[:MAX_STATEMENT_CHARS]
        kind = item.get("kind") if item.get("kind") in KINDS else "fact"
        evidence = []
        seen: set[tuple[int, str]] = set()
        for entry in item.get("evidence") or []:
            if not isinstance(entry, dict):
                continue
            number, quote = entry.get("n"), entry.get("quote")
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= len(window):
                continue
            if not isinstance(quote, str):
                continue
            segment = window[number - 1]
            candidate = quote.strip()
            if candidate not in segment["text"]:
                # Models like to wrap what they copied in quotation marks.
                candidate = candidate.strip("\"'“”‘’「」『』 ")
            if not candidate or len(candidate) > MAX_QUOTE_CHARS or candidate not in segment["text"]:
                continue
            if (segment["id"], candidate) not in seen:
                seen.add((segment["id"], candidate))
                evidence.append({"segment_id": segment["id"], "quote": candidate})
        if not evidence:
            rejected += 1
            continue
        accepted.append({"statement": statement, "kind": kind, "evidence": evidence[:3]})
    return accepted, rejected


def fingerprint(statement: str) -> str:
    normalized = re.sub(r"\s+", "", statement).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# Two memories are the same memory when they rest on the same words (a shared
# piece of evidence: same message, overlapping quote) and say much the same
# thing. Both bars are needed: one long message can support several different
# memories, and two memories can say similar things about different moments.
SAME_QUOTE_OVERLAP = 0.5
SAME_STATEMENT_OVERLAP = 0.3
MAX_EVIDENCE = 5
FOLD_BATCH = 500
# The shelves the kinds stand on (see evolution.py); 勘误 is made of what was replaced or judged wrong.
SHELF_KINDS = {"zhiyi": ["preference", "correction"], "xingce": ["decision", "lesson"], "toolbook": ["fact"], "experience": ["experience"]}
# Which folding rules the stored memories have been through. When the rules
# change, the next start folds the active memories again under the new ones.
FOLD_RULES = "2"


def _overlap(left: str, right: str) -> float:
    a, b = set(tokens(left)), set(tokens(right))
    return len(a & b) / len(a | b) if a and b else 0.0


def same_memory(statement_a: str, evidence_a, statement_b: str, evidence_b) -> bool:
    """evidence_*: iterables of (segment_id, quote)."""
    shared = any(
        seg_a == seg_b and (q_a in q_b or q_b in q_a or _overlap(q_a, q_b) >= SAME_QUOTE_OVERLAP)
        for seg_a, q_a in evidence_a
        for seg_b, q_b in evidence_b
    )
    return shared and _overlap(statement_a, statement_b) >= SAME_STATEMENT_OVERLAP


class _Round:
    """One running round of one job: its own thread, pause switch and live counts."""

    def __init__(self, job: str, trigger: str, started_at: float) -> None:
        self.job = job
        self.halt = threading.Event()  # stop after the stretches in hand
        self.halt_status = "paused"
        self.live: dict[str, Any] = {
            "job": job, "trigger": trigger, "started_at": started_at,
            "windows": 0, "segments": 0, "chars": 0, "memories": 0, "rejected": 0, "pausing": False, "parallel": 1,
        }
        self.thread: threading.Thread | None = None

    def alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


class Distiller:
    def __init__(self, store: Store, models: ModelRegistry) -> None:
        self._store = store
        self._models = models
        self._guard = threading.Lock()
        self._stop = threading.Event()
        # Daily dialogue and imported history run side by side, each in its own
        # round; they take turns only when both use the model on this machine.
        self._rounds: dict[str, _Round] = {}
        self._last_nightly = ""
        # Statements of the active memories, for folding restatements. Built on
        # first use (the first time, it also folds the restatements already stored).
        self._restated = StatementIndex()
        self._restated_ready = False
        self._restated_lock = threading.Lock()
        with store._lock:
            store._db.executescript(SCHEMA)
            store._db.executescript(LOANS_SCHEMA)
            evidence_columns = {row["name"] for row in store._db.execute("PRAGMA table_info(memory_evidence)")}
            if "voice" not in evidence_columns:
                # Whose words each quote is: the user's own, pasted in ("relayed"), or the assistant's.
                store._db.execute("ALTER TABLE memory_evidence ADD COLUMN voice TEXT NOT NULL DEFAULT ''")
            memory_columns = {row["name"] for row in store._db.execute("PRAGMA table_info(memories)")}
            if "folded_into" not in memory_columns:
                store._db.execute("ALTER TABLE memories ADD COLUMN folded_into INTEGER")
            # Experience cards (drawn up from many memories) carry a headline, when
            # they apply, and the project or folder they were drawn up for.
            for name in ("title", "when_to_use", "digest_group"):
                if name not in memory_columns:
                    store._db.execute(f"ALTER TABLE memories ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            # When a memory's words were last said, and whether any of them are the user's: kept on
            # the memory, so lists and the catalog never go back to the stored dialogue for them.
            if "said_at" not in memory_columns:
                store._db.execute("ALTER TABLE memories ADD COLUMN said_at TEXT NOT NULL DEFAULT ''")
                store._db.execute("ALTER TABLE memories ADD COLUMN user_quoted INTEGER NOT NULL DEFAULT 0")
                store._db.execute(
                    """
                    UPDATE memories SET
                      said_at = COALESCE((SELECT MAX(s.ts) FROM memory_evidence e JOIN segments s ON s.id = e.segment_id
                                          WHERE e.memory_id = memories.id), ''),
                      user_quoted = EXISTS (SELECT 1 FROM memory_evidence e JOIN segments s ON s.id = e.segment_id
                                            WHERE e.memory_id = memories.id AND s.role = 'user')
                    """
                )
            store._db.execute("CREATE INDEX IF NOT EXISTS idx_memories_folded_into ON memories(folded_into)")
            fold_columns = {row["name"] for row in store._db.execute("PRAGMA table_info(memory_folds)")}
            for name, definition in (
                ("folded_id", "INTEGER"),
                ("similarity", "REAL"),
                ("reason", "TEXT NOT NULL DEFAULT 'same_evidence'"),
                ("absorbed", "TEXT NOT NULL DEFAULT '[]'"),
                ("undone_at", "REAL"),
            ):
                if name not in fold_columns:
                    store._db.execute(f"ALTER TABLE memory_folds ADD COLUMN {name} {definition}")
            store._db.execute("CREATE INDEX IF NOT EXISTS idx_memory_folds_kept ON memory_folds(kept_id)")
            self._settle_folds(store._db)
            columns = {row["name"] for row in store._db.execute("PRAGMA table_info(distill_runs)")}
            for name, definition in (
                ("skipped", "INTEGER NOT NULL DEFAULT 0"),
                ("merged", "INTEGER NOT NULL DEFAULT 0"),
                ("kind", "TEXT NOT NULL DEFAULT 'daily'"),
                ("chars", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    store._db.execute(f"ALTER TABLE distill_runs ADD COLUMN {name} {definition}")
            # A run that was cut off by a restart did not finish.
            store._db.execute(
                "UPDATE distill_runs SET status='interrupted', finished_at=? WHERE status='running'",
                (store._clock(),),
            )
        self.merge_duplicates()

    # ---- one memory, stated once -------------------------------------------

    def _evidence(self, memory_ids: list[int]) -> dict[int, list[tuple[int, str]]]:
        found: dict[int, list[tuple[int, str]]] = {memory_id: [] for memory_id in memory_ids}
        if not memory_ids:
            return found
        marks = ",".join("?" * len(memory_ids))
        for row in self._store._db.execute(
            f"SELECT memory_id, segment_id, quote FROM memory_evidence WHERE memory_id IN ({marks}) ORDER BY id",
            memory_ids,
        ):
            found[row["memory_id"]].append((row["segment_id"], row["quote"]))
        return found

    def _absorb(self, db, keep_id: int, evidence: list[tuple[int, str]], existing: list[tuple[int, str]]) -> None:
        """Add the evidence a duplicate brought to the memory that stays."""
        room = MAX_EVIDENCE - len(existing)
        for segment_id, quote in evidence:
            if room <= 0:
                break
            if any(segment_id == seg and (quote in q or q in quote) for seg, q in existing):
                continue
            add_evidence(db, keep_id, segment_id, quote)
            existing.append((segment_id, quote))
            room -= 1

    def merge_duplicates(self) -> list[tuple[int, int]]:
        """Fold memories that are the same memory into the oldest of them. Returns (kept, folded) pairs."""
        merged: list[tuple[int, int]] = []
        with self._store._tx() as db:
            # Restatements already folded stay as they are: they are on file, not in play.
            # Experience cards quote the memories they were drawn from: they are not duplicates of them.
            rows = db.execute(
                "SELECT id, statement, recall_count, last_recalled_at FROM memories WHERE status != 'folded' AND kind != 'experience' ORDER BY id"
            ).fetchall() if self._has_recall_columns(db) else db.execute(
                "SELECT id, statement, 0 AS recall_count, NULL AS last_recalled_at FROM memories WHERE status != 'folded' AND kind != 'experience' ORDER BY id"
            ).fetchall()
            evidence = self._evidence([row["id"] for row in rows])
            by_segment: dict[int, list[int]] = {}
            alive: dict[int, Any] = {}
            for row in rows:
                memory_id = row["id"]
                candidates = {other for segment_id, _ in evidence[memory_id] for other in by_segment.get(segment_id, [])}
                target = next(
                    (
                        other
                        for other in sorted(candidates)
                        if other in alive and same_memory(alive[other]["statement"], evidence[other], row["statement"], evidence[memory_id])
                    ),
                    None,
                )
                if target is None:
                    alive[memory_id] = row
                    for segment_id, _ in evidence[memory_id]:
                        by_segment.setdefault(segment_id, []).append(memory_id)
                    continue
                self._absorb(db, target, evidence[memory_id], evidence[target])
                if self._has_recall_columns(db) and row["recall_count"]:
                    db.execute(
                        "UPDATE memories SET recall_count = recall_count + ?, last_recalled_at = MAX(COALESCE(last_recalled_at, 0), ?) WHERE id = ?",
                        (row["recall_count"], row["last_recalled_at"] or 0, target),
                    )
                # Keep what the folded memory said, so a fold can be looked at later.
                db.execute(
                    "INSERT INTO memory_folds(kept_id, folded_statement, folded_at) VALUES(?,?,?)",
                    (target, row["statement"], self._store._clock()),
                )
                # Restatements folded into the removed memory now belong to the one that stays.
                db.execute("UPDATE memories SET folded_into = ? WHERE folded_into = ?", (target, memory_id))
                db.execute("UPDATE memory_folds SET kept_id = ? WHERE kept_id = ?", (target, memory_id))
                db.execute("DELETE FROM memory_evidence WHERE memory_id = ?", (memory_id,))
                db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                merged.append((target, memory_id))
        if merged:
            log.info("folded %d duplicate memories into the ones they repeat", len(merged))
        return merged

    # ---- the same thing said again in another conversation -----------------

    def _restatements(self) -> StatementIndex:
        """The index of active statements, built on first use.

        The first build on a database that has never been through it also folds
        the restatements already stored, oldest memory kept, in batches so the
        rest of the server keeps writing meanwhile.
        """
        with self._restated_lock:
            if self._restated_ready:
                return self._restated
            with self._store.reading() as db:
                rows = db.execute(
                    "SELECT id, statement FROM memories WHERE status = 'active' AND kind != 'experience' ORDER BY id"
                ).fetchall()
                quotes: dict[int, list[str]] = {}
                for row in db.execute(
                    """
                    SELECT e.memory_id, e.quote FROM memory_evidence e JOIN memories m ON m.id = e.memory_id
                    WHERE m.status = 'active' AND m.kind != 'experience'
                    """
                ):
                    quotes.setdefault(row["memory_id"], []).append(row["quote"])
                undone = {
                    (row["kept_id"], row["folded_id"])
                    for row in db.execute("SELECT kept_id, folded_id FROM memory_folds WHERE undone_at IS NOT NULL")
                }
            folded_before = self._store._meta("restatements_folded") == FOLD_RULES
            pending: list[tuple[int, int, float]] = []
            total = 0
            for row in rows:
                if not folded_before:
                    hit = self._restated.find(
                        row["statement"], quotes.get(row["id"], ()), exclude=[kept for kept, folded in undone if folded == row["id"]]
                    )
                    if hit is not None:
                        pending.append((hit[0], row["id"], hit[1]))
                        if len(pending) >= FOLD_BATCH:
                            total += self._fold_batch(pending)
                            pending = []
                        continue
                self._restated.add(row["id"], row["statement"], quotes.get(row["id"], ()))
            if not folded_before:
                total += self._fold_batch(pending)
                with self._store._tx() as db:
                    db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('restatements_folded', ?)", (FOLD_RULES,))
                log.info("folded %d stored restatements into the memories they repeat", total)
            self._restated_ready = True
            return self._restated

    @staticmethod
    def _settle_folds(db) -> int:
        """Point every folded memory at the memory that finally stays (A into B, B into C: A into C)."""
        settled = 0
        for _ in range(20):
            changed = db.execute(
                """
                UPDATE memories SET folded_into = (SELECT k.folded_into FROM memories k WHERE k.id = memories.folded_into)
                WHERE status = 'folded' AND folded_into IN (SELECT id FROM memories WHERE status = 'folded')
                """
            ).rowcount
            db.execute(
                """
                UPDATE memory_folds SET kept_id = (SELECT k.folded_into FROM memories k WHERE k.id = memory_folds.kept_id)
                WHERE kept_id IN (SELECT id FROM memories WHERE status = 'folded')
                """
            )
            settled += changed
            if not changed:
                break
        return settled

    def _fold_batch(self, folds: list[tuple[int, int, float]]) -> int:
        done = 0
        if not folds:
            return done
        with self._store._tx() as db:
            for kept_id, memory_id, similarity in folds:
                state = {
                    row["id"]: row["status"]
                    for row in db.execute("SELECT id, status FROM memories WHERE id IN (?, ?)", (kept_id, memory_id))
                }
                if state.get(kept_id) != "active" or state.get(memory_id) != "active":
                    continue  # changed meanwhile (expired, cleared): leave both as they are
                self._fold(db, kept_id, memory_id, similarity)
                done += 1
        return done

    def _fold(self, db, kept_id: int, memory_id: int, similarity: float) -> None:
        """Fold a restatement into the memory it repeats. The restatement stays on file."""
        def evidence_of(mid: int) -> list[tuple[int, str, bool]]:
            """(segment, quote, is it the user's own words)"""
            return [
                (row["segment_id"], row["quote"], is_user_voice(row["voice"], row["role"] or ""))
                for row in db.execute(
                    """
                    SELECT e.segment_id, e.quote, e.voice, s.role FROM memory_evidence e LEFT JOIN segments s ON s.id = e.segment_id
                    WHERE e.memory_id = ? ORDER BY e.id
                    """,
                    (mid,),
                )
            ]

        existing = evidence_of(kept_id)
        incoming = evidence_of(memory_id)
        # The user's own words first: they are what a memory about the user needs.
        incoming.sort(key=lambda item: not item[2])
        has_user = any(own for _, _, own in existing)
        absorbed: list[int] = []
        for segment_id, quote, own in incoming:
            # The same words said in another conversation add nothing to read.
            if any(quote == q or (segment_id == seg and (quote in q or q in quote)) for seg, q, _ in existing):
                continue
            room = len(existing) < MAX_EVIDENCE
            if not room and not (own and not has_user):
                continue
            absorbed.append(add_evidence(db, kept_id, segment_id, quote)[0])
            existing.append((segment_id, quote, own))
            has_user = has_user or own
        statement = db.execute("SELECT statement FROM memories WHERE id = ?", (memory_id,)).fetchone()["statement"]
        self._restated.add_quotes(kept_id, [quote for _, quote, _ in incoming])
        db.execute("UPDATE memories SET status = 'folded', folded_into = ? WHERE id = ?", (kept_id, memory_id))
        db.execute(
            """
            UPDATE memories SET said_at = MAX(said_at, (SELECT said_at FROM memories WHERE id = ?)),
                                user_quoted = MAX(user_quoted, ?) WHERE id = ?
            """,
            (memory_id, int(has_user), kept_id),
        )
        # What was folded into this memory now belongs to the one that stays.
        db.execute("UPDATE memories SET folded_into = ? WHERE folded_into = ? AND status = 'folded'", (kept_id, memory_id))
        db.execute("UPDATE memory_folds SET kept_id = ? WHERE kept_id = ?", (kept_id, memory_id))
        db.execute(
            """
            INSERT INTO memory_folds(kept_id, folded_statement, folded_at, folded_id, similarity, reason, absorbed)
            VALUES(?,?,?,?,?, 'restated', ?)
            """,
            (kept_id, statement, self._store._clock(), memory_id, round(similarity, 3), json.dumps(absorbed)),
        )
        self._restated.remove(memory_id)

    def unfold(self, memory_id: int) -> None:
        """Take a folded restatement out again: it becomes its own memory, as before the fold."""
        with self._store._tx() as db:
            row = db.execute("SELECT status, statement, folded_into FROM memories WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                raise ApiError(404, "memory_not_found")
            if row["status"] != "folded":
                raise ApiError(409, "not_folded", "this memory is not folded into another")
            fold = db.execute(
                "SELECT id, absorbed FROM memory_folds WHERE folded_id = ? AND undone_at IS NULL ORDER BY id DESC LIMIT 1",
                (memory_id,),
            ).fetchone()
            if fold is not None:
                absorbed = json.loads(fold["absorbed"] or "[]")
                if absorbed:
                    db.execute(
                        f"DELETE FROM memory_evidence WHERE id IN ({','.join('?' * len(absorbed))})", absorbed
                    )
                db.execute("UPDATE memory_folds SET undone_at = ? WHERE id = ?", (self._store._clock(), fold["id"]))
            db.execute("UPDATE memories SET status = 'active', folded_into = NULL WHERE id = ?", (memory_id,))
            if self._restated_ready:
                own = [item["quote"] for item in db.execute("SELECT quote FROM memory_evidence WHERE memory_id = ?", (memory_id,))]
                self._restated.add(memory_id, row["statement"], own)

    @staticmethod
    def _has_recall_columns(db) -> bool:
        return "recall_count" in {row["name"] for row in db.execute("PRAGMA table_info(memories)")}

    # ---- what is waiting ---------------------------------------------------

    def _pending_sessions(self, job: str = "daily") -> list[dict[str, Any]]:
        """What the job will work through: for imported history, only what lies in the chosen range."""
        pending = self._pending_all(job)
        if job != "import":
            return pending
        scope = self.import_scope()
        if scope == ALL_HISTORY:
            return pending
        self._annotate(pending)
        return [item for item in pending if self._in_scope(item, scope)]

    def _pending_all(self, job: str = "daily") -> list[dict[str, Any]]:
        with self._store.reading() as db:
            # Conversations first (from the index), then only what lies past each
            # one's position: never a lookup per stored message.
            imported = 1 if job == "import" else 0
            rows = db.execute(
                """
                WITH conversations AS (
                  SELECT c.agent_id, c.session_id, COALESCE(p.last_segment_id, 0) AS done
                  FROM (SELECT DISTINCT agent_id, session_id FROM segments WHERE imported = ?) c
                  LEFT JOIN distill_progress p ON p.agent_id = c.agent_id AND p.session_id = ? || c.session_id
                )
                SELECT s.agent_id AS agent_id, s.session_id AS session_id, COUNT(*) AS segments,
                       COALESCE(SUM(s.chars), 0) AS chars, MIN(s.id) AS first_id
                FROM conversations k
                JOIN segments s INDEXED BY idx_segments_pending
                  ON s.imported = ? AND s.agent_id = k.agent_id AND s.session_id = k.session_id AND s.id > k.done
                GROUP BY s.agent_id, s.session_id
                ORDER BY first_id
                """,
                (imported, PROGRESS_PREFIX[job], imported),
            ).fetchall()
        return [dict(row) for row in rows]

    def _rates(self, job: str) -> dict[str, Any]:
        """Tokens and seconds per stored character, from rounds already run."""
        with self._store.reading() as db:
            measured = [
                db.execute(
                    f"""
                    SELECT COALESCE(SUM(input_tokens), 0) AS input, COALESCE(SUM(output_tokens), 0) AS output,
                           COALESCE(SUM(chars), 0) AS chars, COALESCE(SUM(finished_at - started_at), 0) AS seconds
                    FROM distill_runs WHERE chars > 0 AND finished_at IS NOT NULL {where}
                    """,
                    params,
                ).fetchone()
                for where, params in (("AND kind = ?", (job,)), ("", ()))
            ]
        for row in measured:
            if row["chars"] >= MIN_MEASURED_CHARS:
                return {
                    "input": row["input"] / row["chars"],
                    "output": row["output"] / row["chars"],
                    "seconds": row["seconds"] / row["chars"],
                    "measured": True,
                }
        return {"input": DEFAULT_INPUT_TOKENS_PER_CHAR, "output": DEFAULT_OUTPUT_TOKENS_PER_CHAR, "seconds": None, "measured": False}

    def _model_label(self, job: str) -> str:
        chain = self._models.resolve(job)
        return f"{chain[0]['name']} · {chain[0]['model']}" if chain else ""

    # ---- the range of imported history to organise --------------------------

    def import_scope(self) -> dict[str, Any]:
        try:
            return _clean_scope(json.loads(self._store._meta("import_scope") or "null"))
        except (ValueError, ApiError):
            return dict(ALL_HISTORY)

    def set_import_scope(self, raw: Any) -> dict[str, Any]:
        scope = _clean_scope(raw)
        with self._guard:
            current = self._rounds.get("import")
            if current is not None and current.alive():
                raise ApiError(409, "import_running", "pause the import before changing its range")
            with self._store._tx() as db:
                db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('import_scope', ?)", (json.dumps(scope),))
        return scope

    def preview_import_scope(self, raw: Any) -> dict[str, Any]:
        """How much a range would hold, before choosing it."""
        scope = _clean_scope(raw)
        pending = self._pending_all("import")
        self._annotate(pending)
        return self._volume([item for item in pending if self._in_scope(item, scope)])

    def _annotate(self, sessions: list[dict[str, Any]]) -> None:
        """When each conversation took place, and the project or folder it belongs to."""
        with self._store.reading() as db:
            spans = {(row[0], row[1]): row[2] for row in db.execute("SELECT agent_id, session_id, last_ts FROM session_spans")}
            folders_of = {(row[0], row[1]): row[2] for row in db.execute("SELECT agent_id, session_id, cwd FROM sessions")}
            device_of = {row[0]: row[1] for row in db.execute("SELECT id, device_id FROM agents")}
            declared: dict[int, list[tuple[str, str, str]]] = {}
            try:
                for row in db.execute("SELECT device_id, folder, project, series FROM project_folders"):
                    declared.setdefault(row[0], []).append((row[1], row[2], row[3]))
            except Exception:
                pass  # no project has been declared on this server yet
        for item in sessions:
            key = (item["agent_id"], item["session_id"])
            item["last"] = _epoch(spans.get(key, ""))
            folder = folders_of.get(key, "")
            owner = _owner(declared.get(device_of.get(item["agent_id"]), []), folder) if folder else None
            if owner:
                item["group"], item["label"] = f"project:{owner[0]}", owner[0]
            else:
                item["group"], item["label"] = f"folder:{folder}", folder

    def _in_scope(self, item: dict[str, Any], scope: dict[str, Any]) -> bool:
        if scope["agents"] is not None and item["agent_id"] not in scope["agents"]:
            return False
        if scope["months"] and item.get("last", 0) < self._store._clock() - scope["months"] * MONTH_SECONDS:
            return False
        if scope["groups"] is not None:
            group = item.get("group", "")
            if group not in scope["groups"] and not (scope["rest"] and group not in scope["listed"]):
                return False
        return True

    def _volume(self, sessions: list[dict[str, Any]]) -> dict[str, Any]:
        chars = sum(item["chars"] for item in sessions)
        rates = self._rates("import")
        return {
            "sessions": len(sessions),
            "segments": sum(item["segments"] for item in sessions),
            "chars": chars,
            "estimate": {
                "input_tokens": round(chars * rates["input"]),
                "output_tokens": round(chars * rates["output"]),
                "seconds": round(chars * rates["seconds"]) if rates["seconds"] else None,
                "measured": rates["measured"],
            },
        }

    def _choices(self, pending: list[dict[str, Any]], names: dict[int, tuple[str, str]]) -> dict[str, Any]:
        """What a range can be made of, with how much each part holds."""
        now = self._store._clock()
        agents: dict[int, dict[str, Any]] = {}
        groups: dict[str, dict[str, Any]] = {}
        for item in pending:
            device, agent = names.get(item["agent_id"], ("", ""))
            entry = agents.setdefault(item["agent_id"], {"agent_id": item["agent_id"], "device": device, "agent": agent, "sessions": 0, "chars": 0})
            entry["sessions"] += 1
            entry["chars"] += item["chars"]
            group = groups.setdefault(item["group"], {"key": item["group"], "label": item["label"], "project": item["group"].startswith("project:"), "sessions": 0, "chars": 0})
            group["sessions"] += 1
            group["chars"] += item["chars"]
        ranked = sorted(groups.values(), key=lambda entry: -entry["chars"])
        rest = ranked[FOLDER_CHOICES:]
        return {
            "months": [
                {"months": months, "sessions": len(recent), "chars": sum(item["chars"] for item in recent)}
                for months in SCOPE_MONTHS[1:]
                for recent in [[item for item in pending if item.get("last", 0) >= now - months * MONTH_SECONDS]]
            ],
            "agents": sorted(agents.values(), key=lambda entry: -entry["chars"]),
            "groups": ranked[:FOLDER_CHOICES],
            "rest": {"groups": len(rest), "sessions": sum(g["sessions"] for g in rest), "chars": sum(g["chars"] for g in rest)},
        }

    def _held(self) -> dict[str, Any]:
        pending = self._pending_all("import")
        self._annotate(pending)
        scope = self.import_scope()
        with self._store.reading() as db:
            total = db.execute(
                "SELECT COUNT(*) AS segments, COALESCE(SUM(chars), 0) AS chars FROM segments WHERE imported = 1"
            ).fetchone()
            names = {
                row["id"]: (row["device"], row["agent"])
                for row in db.execute(
                    "SELECT a.id AS id, a.name AS agent, d.name AS device FROM agents a JOIN devices d ON d.id = a.device_id"
                )
            }
            runs = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM distill_runs WHERE kind = 'import' ORDER BY id DESC LIMIT 5"
                ).fetchall()
            ]
        by_agent: dict[int, dict[str, Any]] = {}
        for item in pending:
            device, agent = names.get(item["agent_id"], ("", ""))
            entry = by_agent.setdefault(item["agent_id"], {"device": device, "agent": agent, "sessions": 0, "segments": 0, "chars": 0})
            entry["sessions"] += 1
            entry["segments"] += item["segments"]
            entry["chars"] += item["chars"]
        scoped = self._volume([item for item in pending if self._in_scope(item, scope)])
        return {
            "sessions": len(pending),
            "segments": sum(item["segments"] for item in pending),
            "chars": sum(item["chars"] for item in pending),
            "total_segments": total["segments"],
            "total_chars": total["chars"],
            "agents": sorted(by_agent.values(), key=lambda entry: -entry["chars"]),
            # What the next round will work through: the chosen range.
            "scope": scope,
            "scoped": {key: scoped[key] for key in ("sessions", "segments", "chars")},
            "estimate": scoped["estimate"],
            "choices": self._choices(pending, names),
            "model": self._model_label("import"),
            "runs": runs,
        }

    def status(self) -> dict[str, Any]:
        pending = self._pending_sessions("daily")
        with self._store.reading() as db:
            runs = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM distill_runs WHERE kind = 'daily' ORDER BY id DESC LIMIT 5"
                ).fetchall()
            ]
            counts = dict(
                db.execute("SELECT status, COUNT(*) FROM memories GROUP BY status").fetchall()
            )
        with self._guard:
            lives = {job: dict(round_.live) for job, round_ in self._rounds.items() if round_.alive()}
        live = lives.get("daily") or lives.get("import")
        return {
            "running": bool(lives),
            "live": live,
            "lives": lives,
            "pending": {
                "sessions": len(pending),
                "segments": sum(item["segments"] for item in pending),
                "chars": sum(item["chars"] for item in pending),
            },
            "held": self._held(),
            "memories": {"active": counts.get("active", 0), "expired": counts.get("expired", 0), "folded": counts.get("folded", 0)},
            "runs": runs,
            "has_model": bool(self._models.resolve("daily")),
            "has_import_model": bool(self._models.resolve("import")),
            "nightly_hour": NIGHTLY_HOUR,
        }

    # ---- running -----------------------------------------------------------

    def _uses_local(self, job: str) -> bool:
        return any(step.get("builtin") for step in self._models.resolve(job))

    def _parallel(self, job: str, max_windows: int | None) -> int:
        if max_windows is not None or self._uses_local(job):
            return 1  # the machine's own model answers one at a time; a capped round stays exact
        return max(1, PARALLEL.get(job, 1))

    def start(self, trigger: str = "manual", max_windows: int | None = None, job: str = "daily") -> dict[str, Any]:
        if job not in JOBS:
            raise ApiError(400, "invalid_field", "job must be daily or import")
        with self._guard:
            current = self._rounds.get(job)
            if current is not None and current.alive():
                raise ApiError(409, "already_running")
            if not self._models.resolve(job):
                if job == "import":
                    raise ApiError(409, "no_import_model", "assign a model to history import first")
                raise ApiError(409, "no_model", "assign a model to daily distillation first")
            other = next((r for j, r in self._rounds.items() if j != job and r.alive()), None)
            if other is not None and self._uses_local(job) and self._uses_local(other.job):
                raise ApiError(409, "local_model_busy", "the model on this machine is busy with the other job")
            round_ = _Round(job, trigger, self._store._clock())
            round_.live["parallel"] = self._parallel(job, max_windows)
            round_.thread = threading.Thread(target=self._run, args=(round_, trigger, max_windows), daemon=True, name=f"distill-{job}")
            self._rounds[job] = round_
            round_.thread.start()
        return {"ok": True}

    def pause(self, status: str = "paused", job: str | None = None) -> dict[str, Any]:
        """Stop a round after the stretches in hand; nothing done so far is lost."""
        with self._guard:
            running = {j: r for j, r in self._rounds.items() if r.alive()}
            if job is None:
                job = "import" if "import" in running else next(iter(running), None)
            round_ = running.get(job) if job else None
            if round_ is None:
                raise ApiError(409, "not_running")
            round_.halt_status = status
            round_.halt.set()
            round_.live["pausing"] = True
        return {"ok": True}

    def _running_jobs(self) -> set[str]:
        with self._guard:
            return {job for job, round_ in self._rounds.items() if round_.alive()}

    def wait(self, timeout: float = 120) -> None:
        with self._guard:
            threads = [round_.thread for round_ in self._rounds.values() if round_.thread]
        for thread in threads:
            thread.join(timeout)

    def _run(self, round_: _Round, trigger: str, max_windows: int | None) -> None:
        job = round_.job
        now = self._store._clock()
        with self._store._tx() as db:
            run_id = db.execute(
                "INSERT INTO distill_runs(trigger, started_at, status, kind) VALUES(?,?, 'running', ?)", (trigger, now, job)
            ).lastrowid
        totals = {
            "windows": 0, "segments": 0, "chars": 0, "memories": 0, "rejected": 0,
            "input_tokens": 0, "output_tokens": 0, "skipped": 0, "merged": 0,
        }
        counted = threading.Lock()
        used: list[str] = []
        fatal: list[BaseException] = []
        queue = list(self._pending_sessions(job))

        def stopping() -> bool:
            return self._stop.is_set() or round_.halt.is_set() or bool(fatal)

        def worker() -> None:
            # Several workers share the conversations; each conversation is read by
            # one worker at a time, in order, so its position only moves forward.
            while not stopping():
                with counted:
                    if not queue:
                        return
                    session = queue.pop(0)
                while not stopping():
                    with counted:
                        if max_windows is not None and totals["windows"] >= max_windows:
                            return
                    window = self._next_window(session["agent_id"], session["session_id"], job)
                    if not window:
                        break
                    try:
                        outcome = self._distill_window(window, job, round_)
                    except ModelError as error:
                        if error.reason != "bad_output":
                            if not (self._stop.is_set() or round_.halt.is_set()):
                                fatal.append(error)  # out of balance, unreachable...: every later call would fail too
                            return
                        # The model would not answer this stretch in the agreed form. Leave
                        # this conversation where it is (it is tried again next run) and
                        # carry on with the others instead of stopping the whole round.
                        with counted:
                            totals["skipped"] += 1
                        log.warning("skipping a conversation this run: %s", error.message)
                        break
                    except Exception as error:  # keep the server alive; record what happened
                        log.exception("distillation failed")
                        fatal.append(error)
                        return
                    self._save_window(session, window, outcome, job)
                    with counted:
                        used.append(outcome["model"])
                        totals["windows"] += 1
                        totals["segments"] += len(window)
                        totals["chars"] += sum(len(item["text"]) for item in window)
                        totals["memories"] += outcome["saved"]
                        for key in ("merged", "rejected", "input_tokens", "output_tokens"):
                            totals[key] += outcome[key]
                        snapshot = {key: totals[key] for key in ("windows", "segments", "chars", "memories", "rejected")}
                    with self._guard:
                        round_.live.update(snapshot)

        status, reason, message = "done", "", ""
        try:
            workers = [
                threading.Thread(target=worker, daemon=True, name=f"distill-{job}-{index}")
                for index in range(round_.live.get("parallel", 1))
            ]
            for thread in workers:
                thread.start()
            for thread in workers:
                thread.join()
            if fatal:
                error = fatal[0]
                if isinstance(error, ModelError):
                    status, reason, message = "stopped", error.reason, error.message
                else:
                    status, reason, message = "stopped", "internal", str(error)[:300]
        finally:
            if self._stop.is_set():
                status, reason, message = "interrupted", "", ""
            elif round_.halt.is_set():
                status, reason, message = round_.halt_status, "", ""
            with self._store._tx() as db:
                db.execute(
                    """
                    UPDATE distill_runs SET finished_at=?, status=?, windows=?, segments=?, memories=?, rejected=?,
                           input_tokens=?, output_tokens=?, model=?, error_reason=?, error=?, skipped=?, merged=?, chars=?
                    WHERE id=?
                    """,
                    (
                        self._store._clock(), status, totals["windows"], totals["segments"], totals["memories"],
                        totals["rejected"], totals["input_tokens"], totals["output_tokens"], used[-1] if used else "",
                        reason, message, totals["skipped"], totals["merged"], totals["chars"], run_id,
                    ),
                )

    def _next_window(self, agent_id: int, session_id: str, job: str = "daily") -> list[dict[str, Any]]:
        with self._store.reading() as db:
            rows = db.execute(
                """
                SELECT s.id, s.role, s.text, s.ts FROM segments s
                LEFT JOIN distill_progress p ON p.agent_id = s.agent_id AND p.session_id = ? || s.session_id
                WHERE s.agent_id = ? AND s.session_id = ? AND s.imported = ? AND s.id > COALESCE(p.last_segment_id, 0)
                ORDER BY s.id LIMIT 400
                """,
                (PROGRESS_PREFIX[job], agent_id, session_id, 1 if job == "import" else 0),
            ).fetchall()
        window: list[dict[str, Any]] = []
        chars = 0
        for row in rows:
            size = min(len(row["text"]), SEGMENT_PROMPT_CHARS)
            if window and chars + size > WINDOW_CHARS:
                break
            window.append({"id": row["id"], "role": row["role"], "text": row["text"], "ts": row["ts"] or ""})
            chars += size
        return window

    def _complete(self, prompt: str, job: str = "daily", round_: _Round | None = None, *,
                  system: str = SYSTEM_PROMPT, max_tokens: int = MAX_OUTPUT_TOKENS, task: str = "") -> dict[str, Any]:
        """Call the job's main model; on failure, its backup. task: what it is for, as the ledger of what was sent says it."""
        ledger = self._models.ledger
        chain = self._models.resolve(job)
        if not chain:
            raise ModelError("not_configured", f"no model is assigned to {job}")
        last: ModelError | None = None
        for step in chain:
            for attempt in range(len(RETRY_DELAYS) + 1):
                try:
                    timeout = self._models.prepare(step["source_id"])
                    reply = model_client.complete(
                        step["base_url"], step["protocol"], step["api_key"], step["model"], prompt,
                        system=system, max_tokens=max_tokens, timeout=timeout,
                        effort=step.get("effort", ""),
                        on_send=ledger.recorder(task=task or job, source=step["name"], protocol=step["protocol"], model=step["model"]) if ledger else None,
                    )
                    reply["model"] = f"{step['name']} · {step['model']}"
                    self._models.note_success(step["source_id"])
                    return reply
                except ModelError as error:
                    last = error
                    transient = error.reason in TRANSIENT_REASONS or (
                        error.reason == "http" and (error.status == 429 or (error.status or 0) >= 500)
                    )
                    if transient and attempt < len(RETRY_DELAYS):
                        log.warning("distillation model %s: %s, trying again", step["name"], error.reason)
                        halt = round_.halt if round_ is not None else self._stop
                        if halt.wait(RETRY_DELAYS[attempt]) or self._stop.is_set():
                            raise  # asked to stop while waiting: not the model's fault
                        continue
                    self._models.note_failure(step["source_id"], error)
                    log.warning("distillation model %s failed: %s", step["name"], error.reason)
                    break
        assert last is not None
        raise last

    def _distill_window(self, window: list[dict[str, Any]], job: str = "daily", round_: _Round | None = None) -> dict[str, Any]:
        prompt = build_prompt(window)
        usage = {"input_tokens": 0, "output_tokens": 0}
        problem = ""
        for attempt in range(2):
            reply = self._complete(prompt if attempt == 0 else prompt + "\n\n(上一次的回答不是合法 JSON。这一次只输出 JSON。)", job, round_)
            usage["input_tokens"] += int(reply.get("input_tokens") or 0)
            usage["output_tokens"] += int(reply.get("output_tokens") or 0)
            try:
                proposed = parse_reply(reply["text"])
            except ValueError as error:
                problem = str(error)
                continue
            accepted, rejected = verify(proposed, window)
            return {"memories": accepted, "rejected": rejected, "model": reply["model"], **usage}
        raise ModelError("bad_output", f"the model did not return the requested JSON ({problem})")

    def _save_window(self, session: dict[str, Any], window: list[dict[str, Any]], outcome: dict[str, Any], job: str = "daily") -> None:
        now = self._store._clock()
        saved = merged = 0
        restated = self._restatements() if outcome["memories"] else None  # before the write lock: it may build first
        with self._store._tx() as db:
            for memory in outcome["memories"]:
                new_evidence = [(item["segment_id"], item["quote"]) for item in memory["evidence"]]
                marks = ",".join("?" * len(new_evidence))
                nearby = [
                    row["memory_id"]
                    for row in db.execute(
                        f"SELECT DISTINCT memory_id FROM memory_evidence WHERE segment_id IN ({marks})",
                        [segment_id for segment_id, _ in new_evidence],
                    )
                ]
                statements = {
                    row["id"]: row["statement"]
                    for row in db.execute(
                        f"SELECT id, statement FROM memories WHERE status != 'folded' AND id IN ({','.join('?' * len(nearby))})", nearby
                    )
                } if nearby else {}
                known = self._evidence(sorted(statements))
                twin = next(
                    (mid for mid in sorted(statements) if same_memory(statements[mid], known[mid], memory["statement"], new_evidence)),
                    None,
                )
                if twin is not None:
                    # Already remembered: keep one memory and let it gain the new evidence.
                    self._absorb(db, twin, new_evidence, known[twin])
                    db.execute(
                        "INSERT INTO memory_folds(kept_id, folded_statement, folded_at) VALUES(?,?,?)",
                        (twin, memory["statement"], now),
                    )
                    merged += 1
                    continue
                cursor = db.execute(
                    """
                    INSERT OR IGNORE INTO memories(fingerprint, statement, kind, agent_id, session_id, model, created_at)
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        fingerprint(memory["statement"]), memory["statement"], memory["kind"],
                        session["agent_id"], session["session_id"], outcome["model"], now,
                    ),
                )
                if not cursor.rowcount:
                    continue  # the same memory was already recorded
                new_id = cursor.lastrowid
                voices = [add_evidence(db, new_id, item["segment_id"], item["quote"])[1] for item in memory["evidence"]]
                turns = {segment["id"]: segment for segment in window}
                cited = [turns[item["segment_id"]] for item in memory["evidence"] if item["segment_id"] in turns]
                db.execute(
                    "UPDATE memories SET said_at = ?, user_quoted = ? WHERE id = ?",
                    (max((turn.get("ts") or "" for turn in cited), default=""), int("user" in voices), new_id),
                )
                quotes = [item["quote"] for item in memory["evidence"]]
                if restated is not None and self._fold_restatement(db, restated, new_id, memory["statement"], quotes):
                    merged += 1
                    continue
                saved += 1
            # Only now does the conversation's position move: memories and
            # position are written together or not at all.
            db.execute(
                """
                INSERT INTO distill_progress(agent_id, session_id, last_segment_id, updated_at) VALUES(?,?,?,?)
                ON CONFLICT(agent_id, session_id) DO UPDATE SET last_segment_id=excluded.last_segment_id, updated_at=excluded.updated_at
                """,
                (session["agent_id"], PROGRESS_PREFIX[job] + session["session_id"], window[-1]["id"], now),
            )
        outcome["saved"] = saved
        outcome["merged"] = merged

    def _fold_restatement(self, db, restated: StatementIndex, memory_id: int, statement: str, quotes: list[str]) -> bool:
        """Fold a newly saved memory into the earlier one it restates, if any; else index it."""
        passed: list[int] = []
        for _ in range(3):
            hit = restated.find(statement, quotes, exclude=passed)
            if hit is None:
                break
            row = db.execute("SELECT status FROM memories WHERE id = ?", (hit[0],)).fetchone()
            if row is None or row["status"] != "active":
                restated.remove(hit[0])  # the index is behind (cleared, or a write that rolled back)
                passed.append(hit[0])
                continue
            self._fold(db, hit[0], memory_id, hit[1])
            return True
        # Close to an earlier memory but saying something else: one may replace the other.
        for earlier, similarity in restated.near_but_different(statement, quotes):
            db.execute(
                "INSERT OR IGNORE INTO review_pairs(later_id, earlier_id, similarity, queued_at) VALUES(?,?,?,?)",
                (memory_id, earlier, round(similarity, 3), self._store._clock()),
            )
        restated.add(memory_id, statement, quotes)
        return False

    # ---- memories ----------------------------------------------------------

    def list_memories(self, query: str = "", status: str = "", limit: int = 100, shelf: str = "", project: str = "") -> dict[str, Any]:
        clauses, params = [], []
        if shelf == "errata":
            # 勘误: what was replaced by something newer, or judged wrong by the agents that used it.
            clauses.append("(m.status = 'superseded' OR (m.status = 'expired' AND m.expire_reason = 'returns'))")
        else:
            if shelf in SHELF_KINDS:
                clauses.append(f"m.kind IN ({','.join('?' * len(SHELF_KINDS[shelf]))})")
                params += SHELF_KINDS[shelf]
            if status in ("active", "expired", "folded", "superseded"):
                clauses.append("m.status = ?")
                params.append(status)
            else:
                clauses.append("m.status NOT IN ('folded', 'superseded')")  # each listed under its own filter
        if query.strip():
            like = f"%{query.strip()}%"
            clauses.append(
                "(m.statement LIKE ? OR EXISTS (SELECT 1 FROM memory_evidence e WHERE e.memory_id = m.id AND e.quote LIKE ?))"
            )
            params += [like, like]
        limit = max(1, min(int(limit), 500))
        if project:
            # A project is a declaration on folders, not a column: find its memories through their sessions.
            with self._store.reading() as db:
                candidates = [dict(row) for row in db.execute(
                    f"SELECT m.id, m.agent_id, m.session_id FROM memories m {('WHERE ' + ' AND '.join(clauses)) if clauses else ''} ORDER BY m.id DESC",
                    params,
                )]
            self._annotate(candidates)
            chosen = [row["id"] for row in candidates if row["group"] == f"project:{project}"][:limit]
            clauses = [f"m.id IN ({','.join('?' * len(chosen))})"] if chosen else ["0"]
            params = list(chosen)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._store.reading() as db:
            rows = db.execute(
                f"""
                SELECT m.*, a.name AS agent, d.name AS device,
                       COALESCE((SELECT ss.surface FROM sessions ss WHERE ss.agent_id = m.agent_id AND ss.session_id = m.session_id), '') AS surface,
                       (SELECT COUNT(*) FROM memory_evidence e WHERE e.memory_id = m.id) AS quotes,
                       (SELECT e.quote FROM memory_evidence e WHERE e.memory_id = m.id ORDER BY e.id LIMIT 1) AS first_quote,
                       (SELECT COUNT(*) FROM memories f WHERE f.folded_into = m.id AND f.status = 'folded') AS restated
                FROM memories m JOIN agents a ON a.id = m.agent_id JOIN devices d ON d.id = a.device_id
                {where} ORDER BY m.id DESC LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
            counts = dict(db.execute("SELECT status, COUNT(*) FROM memories GROUP BY status").fetchall())
            kinds = dict(db.execute("SELECT kind, COUNT(*) FROM memories WHERE status = 'active' GROUP BY kind").fetchall())
            judged = db.execute(
                "SELECT COUNT(*) FROM memories WHERE status = 'expired' AND expire_reason = 'returns'"
            ).fetchone()[0]
            verdicts = loan_verdicts(db, [row["id"] for row in rows])
            quoted = user_quoted_ids(db, [row["id"] for row in rows])
        places = [{"id": row["id"], "agent_id": row["agent_id"], "session_id": row["session_id"]} for row in rows]
        self._annotate(places)
        project_of = {place["id"]: place["label"] for place in places if place["group"].startswith("project:")}
        listed = []
        for row in rows:
            item = self._public(row)
            item["project"] = project_of.get(row["id"], "")
            item["returns"] = verdicts.get(row["id"], {outcome: 0 for outcome in OUTCOMES})
            item["note"] = voice_note(row["kind"], row["statement"], row["id"] in quoted)
            listed.append(item)
        return {
            "memories": listed,
            "counts": {"active": counts.get("active", 0), "expired": counts.get("expired", 0), "folded": counts.get("folded", 0),
                       "superseded": counts.get("superseded", 0)},
            "shelves": {
                **{name: sum(kinds.get(kind, 0) for kind in members) for name, members in SHELF_KINDS.items()},
                "errata": counts.get("superseded", 0) + judged,
            },
            "retention_days": DEFAULT_RETENTION_DAYS,
            "now": self._store._clock(),
        }

    @staticmethod
    def _public(row) -> dict[str, Any]:
        keys = row.keys()
        return {
            "id": row["id"],
            "statement": row["statement"],
            "kind": row["kind"],
            "status": row["status"],
            "device": row["device"],
            "agent": row["agent"],
            "surface": surface_label(row["surface"]) if "surface" in row.keys() else "",
            "created_at": row["created_at"],
            "expired_at": row["expired_at"],
            "expire_reason": row["expire_reason"],
            "quotes": row["quotes"],
            "first_quote": row["first_quote"],
            "recall_count": row["recall_count"] if "recall_count" in keys else 0,
            "last_recalled_at": row["last_recalled_at"] if "last_recalled_at" in keys else None,
            "folded_into": row["folded_into"] if "folded_into" in keys else None,
            "restated": row["restated"] if "restated" in keys else 0,
            "shelf": shelf_of(row["kind"]),
            "title": row["title"] if "title" in keys else "",
            "when_to_use": row["when_to_use"] if "when_to_use" in keys else "",
        }

    def memory(self, memory_id: int) -> dict[str, Any]:
        with self._store.reading() as db:
            row = db.execute(
                """
                SELECT m.*, a.name AS agent, d.name AS device, 0 AS quotes, '' AS first_quote,
                       COALESCE((SELECT ss.surface FROM sessions ss WHERE ss.agent_id = m.agent_id AND ss.session_id = m.session_id), '') AS surface
                FROM memories m JOIN agents a ON a.id = m.agent_id JOIN devices d ON d.id = a.device_id WHERE m.id = ?
                """,
                (memory_id,),
            ).fetchone()
            if row is None:
                raise ApiError(404, "memory_not_found")
            evidence = db.execute(
                """
                SELECT e.quote, s.role, s.ts, s.received_at, e.voice FROM memory_evidence e
                LEFT JOIN segments s ON s.id = e.segment_id WHERE e.memory_id = ? ORDER BY e.id
                """,
                (memory_id,),
            ).fetchall()
            loans = db.execute(
                """
                SELECT l.agent, l.mode, l.lent_at, l.outcome, l.note, l.returned_at, d.name AS device
                FROM memory_loans l LEFT JOIN devices d ON d.id = l.device_id
                WHERE l.memory_id = ? ORDER BY COALESCE(l.returned_at, l.lent_at) DESC, l.id DESC LIMIT 20
                """,
                (memory_id,),
            ).fetchall()
            lent = db.execute(
                "SELECT COUNT(*) FROM memory_loans WHERE memory_id = ? AND mode != 'direct'", (memory_id,)
            ).fetchone()[0]
            verdicts = loan_verdicts(db, [memory_id])
            restatements = db.execute(
                """
                SELECT f.id, f.statement, f.created_at, a.name AS agent, d.name AS device, k.similarity
                FROM memories f JOIN agents a ON a.id = f.agent_id JOIN devices d ON d.id = a.device_id
                LEFT JOIN memory_folds k ON k.folded_id = f.id AND k.undone_at IS NULL
                WHERE f.folded_into = ? AND f.status = 'folded' ORDER BY f.id
                """,
                (memory_id,),
            ).fetchall()
            links = self._links(db, memory_id)
            history = self._history(db, memory_id)
        detail = self._public(row)
        detail["history"] = history
        place = [{"id": memory_id, "agent_id": row["agent_id"], "session_id": row["session_id"]}]
        self._annotate(place)
        detail["project"] = place[0]["label"] if place[0]["group"].startswith("project:") else ""
        detail["folder"] = place[0]["label"] if place[0]["group"].startswith("folder:") else ""
        detail["links"] = links
        detail["restatements"] = [dict(item) for item in restatements]
        detail["restated"] = len(restatements)
        evidence = [dict(item, voice=item["voice"] or ("user" if item["role"] == "user" else "assistant")) for item in evidence]
        detail["note"] = voice_note(row["kind"], row["statement"], any(item["voice"] == "user" for item in evidence),
                                    pasted=any(item["voice"] == "relayed" for item in evidence))
        detail["model"] = row["model"]
        detail["returns"] = verdicts.get(memory_id, {outcome: 0 for outcome in OUTCOMES})
        detail["lent"] = lent
        detail["loans"] = [dict(item) for item in loans]
        detail["evidence"] = evidence
        detail.pop("quotes"), detail.pop("first_quote")
        return detail

    @staticmethod
    def _history(db, memory_id: int) -> dict[str, Any]:
        """A memory's record: when it was said (first and last, its restatements included), in how many
        conversations, and who borrowed it."""
        members = [memory_id] + [row[0] for row in db.execute("SELECT id FROM memories WHERE folded_into = ?", (memory_id,))]
        marks = ",".join("?" * len(members))
        said = db.execute(
            f"""
            SELECT MIN(s.ts), MAX(s.ts) FROM memory_evidence e JOIN segments s ON s.id = e.segment_id
            WHERE e.memory_id IN ({marks}) AND s.ts != ''
            """,
            members,
        ).fetchone()
        conversations = db.execute(
            f"SELECT COUNT(DISTINCT agent_id || ':' || session_id) FROM memories WHERE id IN ({marks})", members
        ).fetchone()[0]
        borrowers = {row[0] or "未知": row[1] for row in db.execute(
            "SELECT agent, COUNT(*) FROM memory_loans WHERE memory_id = ? AND mode != 'direct' GROUP BY agent ORDER BY 2 DESC", (memory_id,)
        )}
        return {"first_said": said[0] or "", "last_said": said[1] or "", "conversations": conversations, "borrowers": borrowers}

    @staticmethod
    def _links(db, memory_id: int) -> dict[str, list[dict[str, Any]]]:
        """Where a memory stands in the chain: what replaced it, what it replaced, what it was drawn from or into."""
        def rows(sql: str) -> list[dict[str, Any]]:
            return [dict(item) for item in db.execute(sql, (memory_id,))]

        base = "SELECT k.id AS link_id, k.reason, k.decided_by, k.created_at, k.undone_at, m.id, m.statement, m.status, m.kind"
        return {
            "replaced_by": rows(f"{base} FROM memory_links k JOIN memories m ON m.id = k.from_id WHERE k.relation = 'replaces' AND k.to_id = ? ORDER BY k.id"),
            "replaces": rows(f"{base} FROM memory_links k JOIN memories m ON m.id = k.to_id WHERE k.relation = 'replaces' AND k.from_id = ? AND k.to_id != k.from_id ORDER BY k.id"),
            "derived_from": rows(f"{base} FROM memory_links k JOIN memories m ON m.id = k.to_id WHERE k.relation = 'derived_from' AND k.from_id = ? ORDER BY k.to_id"),
            "drawn_into": rows(f"{base} FROM memory_links k JOIN memories m ON m.id = k.from_id WHERE k.relation = 'derived_from' AND k.to_id = ? ORDER BY k.from_id"),
            "judged": rows(f"{base} FROM memory_links k JOIN memories m ON m.id = k.to_id WHERE k.relation IN ('judged', 'kept') AND k.to_id = ? ORDER BY k.id"),
        }

    def set_status(self, memory_id: int, status: str, reason: str = "") -> None:
        now = self._store._clock()
        with self._store._tx() as db:
            row = db.execute("SELECT status, statement, kind, expire_reason FROM memories WHERE id=?", (memory_id,)).fetchone()
            if row is None:
                raise ApiError(404, "memory_not_found")
            if row["status"] == "folded":
                raise ApiError(409, "folded", "this memory is folded into another; take it out first")
            if row["status"] == "superseded":
                raise ApiError(409, "superseded", "this memory was replaced; take the replacement back instead")
            if status == "active" and row["expire_reason"] == "returns":
                # Brought back by its owner after the agents judged it wrong: it stays.
                db.execute("UPDATE memory_links SET undone_at=? WHERE relation='judged' AND to_id=? AND undone_at IS NULL", (now, memory_id))
                db.execute(
                    "INSERT INTO memory_links(relation, from_id, to_id, reason, decided_by, created_at) VALUES('kept',?,?, '主人拿回来了', 'owner', ?)",
                    (memory_id, memory_id, now),
                )
            db.execute(
                "UPDATE memories SET status=?, expired_at=?, expire_reason=? WHERE id=?",
                (status, now if status == "expired" else None, reason if status == "expired" else "", memory_id),
            )
            if status == "active" and self._restated_ready and row["kind"] != "experience":
                self._restated.add(memory_id, row["statement"])
            elif status != "active":
                self._restated.remove(memory_id)

    @staticmethod
    def _delete(db, memory_ids: list[int]) -> None:
        """Remove memories for good, together with the restatements folded into them."""
        for memory_id in memory_ids:
            members = [row["id"] for row in db.execute("SELECT id FROM memories WHERE folded_into = ?", (memory_id,))]
            for mid in [memory_id, *members]:
                db.execute("DELETE FROM memory_evidence WHERE memory_id=?", (mid,))
                db.execute("DELETE FROM memories WHERE id=?", (mid,))
            db.execute("DELETE FROM memory_folds WHERE kept_id=?", (memory_id,))

    def purge(self, memory_id: int) -> None:
        with self._store._tx() as db:
            if db.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone() is None:
                raise ApiError(404, "memory_not_found")
            self._delete(db, [memory_id])
        self._restated.remove(memory_id)

    def purge_expired(self, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
        """Expired memories are kept for a while, then removed for good."""
        cutoff = self._store._clock() - retention_days * 86400
        with self._store._tx() as db:
            ids = [row["id"] for row in db.execute(
                "SELECT id FROM memories WHERE status='expired' AND expired_at IS NOT NULL AND expired_at < ?", (cutoff,)
            )]
            self._delete(db, ids)
        return len(ids)

    # ---- the nightly round -------------------------------------------------

    def tick(self) -> str:
        """One look at the clock. Returns what was started: 'nightly', 'resume' or ''.

        Once a night: clear out memories past their keep-by date, then distill
        whatever dialogue arrived since last time. Between nights: if the last
        round stopped because no model answered, try again every so often, so
        the owner only has to top up or fix the key.
        """
        now = self._store._clock()
        local = time.localtime(now)
        today = time.strftime("%Y-%m-%d", local)
        running = self._running_jobs()

        def clashes(job: str) -> bool:
            """Another round is using the model on this machine that this job would use too."""
            return any(other != job and self._uses_local(job) and self._uses_local(other) for other in running)

        if local.tm_hour == NIGHTLY_HOUR and self._last_nightly != today:
            daily_waiting = bool(self._models.resolve("daily") and self._pending_sessions("daily"))
            if "daily" in running:
                return ""  # a round started by hand is still going; tonight's waits for it
            if daily_waiting and clashes("daily"):
                # Only when both share this machine's model: history steps aside for
                # tonight's dialogue and carries on by itself afterwards.
                self.pause("yielded", job="import")
                return ""
            self._last_nightly = today
            self.purge_expired()
            if daily_waiting:
                self.start("nightly")
                return "nightly"
        for job in JOBS:  # tonight's dialogue before old history
            if job in running or clashes(job):
                continue
            with self._store.reading() as db:
                last = db.execute(
                    "SELECT * FROM distill_runs WHERE kind = ? ORDER BY id DESC LIMIT 1", (job,)
                ).fetchone()
            if last is None:
                continue
            stopped = (
                last["status"] == "stopped"
                and last["error_reason"] in RESUMABLE_REASONS
                and now - (last["finished_at"] or now) >= RESUME_AFTER_SECONDS
            )
            if (stopped or last["status"] in CARRY_ON_STATUSES) and self._models.resolve(job) and self._pending_sessions(job):
                self.start("resume", job=job)
                return "resume"
        return ""

    def stamp_voices(self) -> int:
        """Judge whose words each stored quote is (once per version of the rules). Returns quotes judged."""
        if self._store._meta("evidence_voices") == VOICE_RULES:
            return 0
        with self._store._tx() as db:
            db.execute(
                """
                UPDATE memory_evidence SET voice = 'assistant'
                WHERE voice != 'assistant' AND segment_id IN (SELECT id FROM segments WHERE role != 'user')
                """
            )
        last, judged = 0, 0
        while not self._stop.is_set():
            with self._store.reading() as db:
                rows = db.execute(
                    """
                    SELECT e.id, e.quote, s.text FROM memory_evidence e JOIN segments s ON s.id = e.segment_id
                    WHERE s.role = 'user' AND e.id > ? ORDER BY e.id LIMIT 1000
                    """,
                    (last,),
                ).fetchall()
            if not rows:
                break
            with self._store._tx() as db:
                db.executemany("UPDATE memory_evidence SET voice = ? WHERE id = ?",
                               [(voice_of("user", row["text"], row["quote"]), row["id"]) for row in rows])
            last, judged = rows[-1]["id"], judged + len(rows)
        if self._stop.is_set():
            return judged
        with self._store._tx() as db:
            db.execute(
                "UPDATE memories SET user_quoted = EXISTS (SELECT 1 FROM memory_evidence e WHERE e.memory_id = memories.id AND e.voice = 'user')"
            )
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('evidence_voices', ?)", (VOICE_RULES,))
        log.info("judged whose words %d quoted user turns are", judged)
        return judged

    def run_scheduler(self) -> None:
        def prepare() -> None:
            try:
                self.stamp_voices()
            except Exception:
                log.exception("could not judge whose words the stored quotes are")
            try:
                self._restatements()  # the first time on a database, this folds what is stored
            except Exception:
                log.exception("could not prepare restatement folding")

        threading.Thread(target=prepare, daemon=True, name="restatements").start()

        def loop() -> None:
            while not self._stop.wait(60):
                try:
                    self.tick()
                except ApiError:
                    pass  # already running, or no model: look again next minute
                except Exception:
                    log.exception("distillation scheduler failed")

        threading.Thread(target=loop, daemon=True, name="distill-scheduler").start()

    def shutdown(self) -> None:
        self._stop.set()
        with self._guard:
            for round_ in self._rounds.values():
                round_.halt.set()


def _clean_scope(raw: Any) -> dict[str, Any]:
    """A range of imported history, checked. None means all of it."""
    if raw is None:
        return dict(ALL_HISTORY)
    if not isinstance(raw, dict):
        raise ApiError(400, "invalid_field", "scope must be an object")
    months = raw.get("months", 0)
    if months not in SCOPE_MONTHS or isinstance(months, bool):
        raise ApiError(400, "invalid_field", f"scope.months must be one of {', '.join(map(str, SCOPE_MONTHS))}")
    agents = raw.get("agents")
    if agents is not None and (
        not isinstance(agents, list) or len(agents) > 500
        or any(isinstance(item, bool) or not isinstance(item, int) for item in agents)
    ):
        raise ApiError(400, "invalid_field", "scope.agents must be a list of agent numbers, or null for all")

    def keys(name: str) -> list[str] | None:
        value = raw.get(name)
        if value is None:
            return None
        if not isinstance(value, list) or len(value) > 500 or any(not isinstance(item, str) or len(item) > 600 for item in value):
            raise ApiError(400, "invalid_field", f"scope.{name} must be a list of project or folder keys")
        return value

    groups = keys("groups")
    return {
        "months": months,
        "agents": sorted(set(agents)) if agents is not None else None,
        "groups": groups,
        "rest": bool(raw.get("rest")) if groups is not None else False,
        "listed": (keys("listed") or []) if groups is not None else [],
    }
