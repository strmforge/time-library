"""Evolution: how memories change over time.

Three movements, all automatic, all undoable, each leaving a receipt (who
decided, why, on what):

  replaced (取代)     A later memory shows that something has changed: v17
                      became v18, "use the local model" became "use an online
                      one". Pairs close in wording but different in such a
                      detail are queued when they are distilled; a model reads
                      both with their words and dates and says whether the newer
                      replaces the older. A replaced memory leaves recall
                      (status 'superseded') but stays on file, linked to what
                      replaced it.
  judged wrong (判误)  Agents that borrowed a memory returned it as misleading
                      more often than useful: it leaves recall (expired, reason
                      'returns'). If the owner brings it back, it stays.
  drawn up (归纳)      The memories of one project or folder are read together
                      and drawn up into experience: a few cards on how work goes
                      there, each naming when it applies and the memories it
                      rests on. As the project grows the cards are drawn up
                      again; the old ones are replaced, not piled up.

Nothing waits for a person. The owner corrects what is wrong (undo), never
approves what is right. The model used is the "deep" slot (深度归纳).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

from .errors import ApiError
from .folding import StatementIndex
from .model_client import ModelError
from .voiceprint import USER_VOICE_SQL, add_evidence

log = logging.getLogger("tl_server.evolution")

# Which shelf a memory stands on: what the user likes and corrected, how work is done (decisions and lessons),
# the facts, and the experience drawn up from them. A fifth, "corrected", holds what was replaced or judged wrong,
# with the reason (distill.list_memories).
SHELVES = {
    "preference": "preferences",
    "correction": "preferences",
    "decision": "decisions",
    "lesson": "decisions",
    "fact": "facts",
    "experience": "experience",
}

SLOT = "reflect"
REVIEW_BATCH = 10
REVIEW_PER_RUN = 600
MISLEADING_MIN = 2
DIGEST_MIN = 8  # memories a project needs before it is drawn up
DIGEST_GROWTH = 10  # new memories before it is drawn up again
DIGEST_PER_RUN = 40
DIGEST_INPUT = 60  # memories read per drawing-up
DIGEST_MAX_CARDS = 6
EXPERIENCE_EVIDENCE = 3
OUTPUT_TOKENS = 6000
CHECK_SECONDS = 300
NIGHT_WINDOW_HOURS = 6  # a nightly run starts between the nightly hour and six hours later
FATAL_REASONS = ("auth", "quota", "not_configured", "not_found")

SCHEMA = """
CREATE TABLE IF NOT EXISTS digests (
  group_key TEXT PRIMARY KEY,
  label TEXT NOT NULL DEFAULT '',
  memories INTEGER NOT NULL,
  digested_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS evolution_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,
  started_at REAL NOT NULL,
  finished_at REAL,
  status TEXT NOT NULL,
  reviewed INTEGER NOT NULL DEFAULT 0,
  replaced INTEGER NOT NULL DEFAULT 0,
  folded INTEGER NOT NULL DEFAULT 0,
  judged INTEGER NOT NULL DEFAULT 0,
  groups INTEGER NOT NULL DEFAULT 0,
  experiences INTEGER NOT NULL DEFAULT 0,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  model TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT ''
);
"""

REVIEW_SYSTEM = """你在维护一个 AI 助手的长期记忆库。下面每一组是两条说法相近、但某个细节不同的记忆:较早的 A 和较晚的 B,各带日期和原话。判断 B 和 A 的关系:
- replaces:情况变了,B 取代了 A,A 已经过时(例如版本从 v17 换成 v18、做法从 X 改成 Y、先前的决定被推翻)
- same:说的是同一件事,只是措辞不同
- both:两条都仍然成立(说的是不同对象、不同场景或不同方面)
- unrelated:其实不相关
拿不准时选 both。reason 用一句话写清依据,用记忆本身的语言。

只输出 JSON,不要任何别的文字。格式:
{"pairs":[{"n":1,"verdict":"replaces","reason":"…"}]}"""

DIGEST_SYSTEM = """你在为一个 AI 助手把同一个项目里积累的记忆归纳成"经验":下一次在这个项目里干活时,先读这几条就能少走弯路。

每条经验:
- title:10 到 20 个字的标题
- statement:一两句话,说清该怎么做、为什么(判断和分寸,不是操作步骤清单)
- when:什么情况下该想起它
- derived_from:支撑它的记忆编号,至少 2 个,只能用下面列出的编号

只归纳几条记忆共同支撑的东西,不要只是换个说法复述单条记忆;不要写会很快过时的状态(版本号、进度)。
如果列出了已有的经验:仍然成立又没有新内容的,把编号放进 keep;需要更新的就写一条新的(会取代旧的);不再成立的不列。
最多 6 条。没有值得归纳的就返回空列表。

只输出 JSON,不要任何别的文字。格式:
{"experiences":[{"title":"…","statement":"…","when":"…","derived_from":[1,2]}],"keep":[]}"""


def shelf_of(kind: str) -> str:
    return SHELVES.get(kind, "decisions")


def _json_reply(text: str, key: str) -> Any:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the reply")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise ValueError(f"reply has no {key} list")
    return payload


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


class Evolution:
    def __init__(self, store, distiller) -> None:
        self._store = store
        self._distiller = distiller
        self._guard = threading.Lock()
        self._halt = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._live: dict[str, Any] | None = None
        self._last_day = ""
        self._limits = {"pairs": REVIEW_PER_RUN, "groups": DIGEST_PER_RUN}
        with store._lock:
            store._db.executescript(SCHEMA)
            # A run cut off by a restart did not finish.
            store._db.execute(
                "UPDATE evolution_runs SET status='interrupted', finished_at=? WHERE status='running'", (store._clock(),)
            )

    # ---- running -------------------------------------------------------------

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, trigger: str = "manual", pairs: int | None = None, groups: int | None = None) -> dict[str, Any]:
        """pairs / groups cap a run (a trial on a small batch); the nightly run uses the defaults."""
        with self._guard:
            if self.running():
                raise ApiError(409, "already_running")
            if not self._distiller._models.resolve(SLOT):
                raise ApiError(409, "no_reflect_model", "assign a model to deep organising first")
            self._halt.clear()
            self._limits = {"pairs": REVIEW_PER_RUN if pairs is None else pairs, "groups": DIGEST_PER_RUN if groups is None else groups}
            self._live = {"trigger": trigger, "started_at": self._store._clock(), "step": "", "reviewed": 0, "replaced": 0,
                          "folded": 0, "judged": 0, "groups": 0, "experiences": 0, "input_tokens": 0, "output_tokens": 0, "model": ""}
            self._thread = threading.Thread(target=self._run, args=(trigger,), daemon=True, name="evolution")
            self._thread.start()
        return {"ok": True}

    def pause(self) -> dict[str, Any]:
        if not self.running():
            raise ApiError(409, "not_running")
        self._halt.set()
        return {"ok": True}

    def wait(self, timeout: float = 120) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def shutdown(self) -> None:
        self._stop.set()
        self._halt.set()

    def tick(self) -> str:
        """Once a night, after the nightly distilling has had its turn.

        Only in the night's window, and only if no nightly run started since this
        night's hour: a restart during the day must not start one (the record of
        what ran is in the database, not in memory).
        """
        from . import distill  # the nightly hour lives there

        clock = self._store._clock()
        now = time.localtime(clock)
        if not distill.NIGHTLY_HOUR <= now.tm_hour < distill.NIGHTLY_HOUR + NIGHT_WINDOW_HOURS or self.running():
            return ""
        if "daily" in self._distiller._running_jobs():
            return ""  # let tonight's distilling finish first
        tonight = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, distill.NIGHTLY_HOUR, 0, 0, 0, 0, -1))
        with self._store.reading() as db:
            if db.execute("SELECT 1 FROM evolution_runs WHERE trigger = 'nightly' AND started_at >= ?", (tonight,)).fetchone():
                return ""
        if not self._distiller._models.resolve(SLOT):
            return ""
        self.start("nightly")
        return "nightly"

    def run_scheduler(self) -> None:
        def loop() -> None:
            while not self._stop.wait(CHECK_SECONDS):
                try:
                    self.tick()
                except ApiError:
                    pass
                except Exception:
                    log.exception("evolution scheduler failed")

        threading.Thread(target=loop, daemon=True, name="evolution-scheduler").start()

    def _run(self, trigger: str) -> None:
        live = self._live
        assert live is not None
        with self._store._tx() as db:
            run_id = db.execute(
                "INSERT INTO evolution_runs(trigger, started_at, status) VALUES(?,?, 'running')", (trigger, live["started_at"])
            ).lastrowid
        status, error = "done", ""
        try:
            live["step"] = "review"
            self._queue_stored_pairs()
            self._review(live)
            live["step"] = "judge"
            self._judge(live)
            live["step"] = "digest"
            self._digest(live)
            if self._halt.is_set():
                status = "paused"
        except ModelError as failure:
            status, error = "stopped", f"{failure.reason}: {str(failure)[:300]}"
            log.warning("evolution stopped: %s", failure.reason)
        except Exception as failure:  # never leave a run marked running
            status, error = "stopped", f"error: {failure}"[:300]
            log.exception("evolution failed")
        with self._store._tx() as db:
            db.execute(
                """
                UPDATE evolution_runs SET finished_at=?, status=?, reviewed=?, replaced=?, folded=?, judged=?, groups=?,
                       experiences=?, input_tokens=?, output_tokens=?, model=?, error=? WHERE id=?
                """,
                (self._store._clock(), status, live["reviewed"], live["replaced"], live["folded"], live["judged"], live["groups"],
                 live["experiences"], live["input_tokens"], live["output_tokens"], live["model"], error, run_id),
            )

    def _ask(self, prompt: str, system: str, live: dict[str, Any]) -> str:
        reply = self._distiller._complete(prompt, SLOT, None, system=system, max_tokens=OUTPUT_TOKENS, task="organise")
        live["input_tokens"] += int(reply.get("input_tokens") or 0)
        live["output_tokens"] += int(reply.get("output_tokens") or 0)
        live["model"] = reply.get("model", "")
        return reply["text"]

    # ---- replaced -----------------------------------------------------------

    def _queue_stored_pairs(self) -> None:
        """Once: the near-but-different pairs among memories stored before this existed."""
        if self._store._meta("review_pairs_queued") == "1":
            return
        with self._store.reading() as db:
            rows = db.execute(
                "SELECT id, statement FROM memories WHERE status = 'active' AND kind != 'experience' ORDER BY id"
            ).fetchall()
            quotes: dict[int, list[str]] = {}
            for row in db.execute(
                "SELECT e.memory_id, e.quote FROM memory_evidence e JOIN memories m ON m.id = e.memory_id "
                "WHERE m.status = 'active' AND m.kind != 'experience'"
            ):
                quotes.setdefault(row[0], []).append(row[1])
        index = StatementIndex()
        pairs = []
        for row in rows:
            for earlier, similarity in index.near_but_different(row["statement"], quotes.get(row["id"], ())):
                pairs.append((row["id"], earlier, round(similarity, 3), self._store._clock()))
            index.add(row["id"], row["statement"], quotes.get(row["id"], ()))
        with self._store._tx() as db:
            db.executemany(
                "INSERT OR IGNORE INTO review_pairs(later_id, earlier_id, similarity, queued_at) VALUES(?,?,?,?)", pairs
            )
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('review_pairs_queued', '1')")
        log.info("queued %d stored pairs for review", len(pairs))

    def _said(self, db, ids: list[int]) -> dict[int, dict[str, Any]]:
        """Each memory's statement, when its words were said, and a couple of its quotes."""
        found: dict[int, dict[str, Any]] = {}
        if not ids:
            return found
        marks = ",".join("?" * len(ids))
        for row in db.execute(f"SELECT id, statement, kind, status, created_at FROM memories WHERE id IN ({marks})", ids):
            found[row["id"]] = {"statement": row["statement"], "kind": row["kind"], "status": row["status"],
                                "when": "", "created_at": row["created_at"], "quotes": []}
        for row in db.execute(
            f"""
            SELECT e.memory_id, e.quote, e.voice, s.role, s.ts FROM memory_evidence e LEFT JOIN segments s ON s.id = e.segment_id
            WHERE e.memory_id IN ({marks}) ORDER BY e.id
            """,
            ids,
        ):
            item = found.get(row["memory_id"])
            if item is None:
                continue
            if row["ts"] and row["ts"] > item["when"]:
                item["when"] = row["ts"]
            if len(item["quotes"]) < 2 and all(row["quote"] != quote for _, quote in item["quotes"]):
                voice = row["voice"] or ("user" if row["role"] == "user" else "assistant")
                item["quotes"].append(({"user": "用户", "relayed": "用户转贴"}.get(voice, "助手"), row["quote"]))
        return found

    def _review(self, live: dict[str, Any]) -> None:
        reviewed = 0
        while reviewed < self._limits["pairs"] and not self._halt.is_set() and not self._stop.is_set():
            with self._store.reading() as db:
                pairs = db.execute(
                    "SELECT later_id, earlier_id, similarity FROM review_pairs WHERE verdict = '' ORDER BY queued_at, later_id LIMIT ?",
                    (min(REVIEW_BATCH, self._limits["pairs"] - reviewed),),
                ).fetchall()
                if not pairs:
                    return
                said = self._said(db, sorted({pid for pair in pairs for pid in (pair[0], pair[1])}))
            batch, gone = [], []
            for later, earlier, similarity in pairs:
                a, b = said.get(earlier), said.get(later)
                if not a or not b or a["status"] != "active" or b["status"] != "active":
                    gone.append((later, earlier))
                    continue
                # Older and newer by when the words were said, not by when they were stored.
                if (a["when"] or "") > (b["when"] or "") or (not a["when"] and not b["when"] and earlier > later):
                    a, b, older, newer = b, a, later, earlier
                else:
                    older, newer = earlier, later
                batch.append({"pair": (later, earlier), "older": older, "newer": newer, "a": a, "b": b, "similarity": similarity})
            verdicts: dict[int, dict[str, str]] = {}
            if batch:
                lines = []
                for number, item in enumerate(batch, start=1):
                    lines.append(f"第 {number} 组")
                    for name, memory in (("A", item["a"]), ("B", item["b"])):
                        lines.append(f"{name}({memory['when'][:10] or '日期不详'}):{memory['statement']}")
                        for who, quote in memory["quotes"]:
                            lines.append(f"   {who}原话:「{_clip(quote, 160)}」")
                    lines.append("")
                text = self._ask("\n".join(lines), REVIEW_SYSTEM, live)
                try:
                    for entry in _json_reply(text, "pairs")["pairs"]:
                        if isinstance(entry, dict) and isinstance(entry.get("n"), int) and not isinstance(entry.get("n"), bool):
                            verdicts[entry["n"]] = entry
                except ValueError:
                    pass  # an unreadable answer: these pairs are marked unclear and not asked again
            now = self._store._clock()
            restated = self._distiller._restated
            with self._store._tx() as db:
                for later, earlier in gone:
                    db.execute("UPDATE review_pairs SET verdict='gone', decided_at=? WHERE later_id=? AND earlier_id=?", (now, later, earlier))
                for number, item in enumerate(batch, start=1):
                    entry = verdicts.get(number, {})
                    verdict = entry.get("verdict") if entry.get("verdict") in ("replaces", "same", "both", "unrelated") else "unclear"
                    reason = _clip(entry.get("reason") if isinstance(entry.get("reason"), str) else "", 300)
                    states = dict(db.execute(
                        "SELECT id, status FROM memories WHERE id IN (?, ?)", (item["older"], item["newer"])
                    ).fetchall())
                    if states.get(item["older"]) != "active" or states.get(item["newer"]) != "active":
                        verdict = "gone"
                    elif verdict == "replaces":
                        db.execute("UPDATE memories SET status='superseded' WHERE id=?", (item["older"],))
                        db.execute(
                            "INSERT INTO memory_links(relation, from_id, to_id, reason, decided_by, created_at) VALUES('replaces',?,?,?,?,?)",
                            (item["newer"], item["older"], reason, live["model"], now),
                        )
                        restated.remove(item["older"])
                        live["replaced"] += 1
                    elif verdict == "same":
                        self._distiller._fold(db, item["older"], item["newer"], item["similarity"])
                        live["folded"] += 1
                    later, earlier = item["pair"]
                    db.execute(
                        "UPDATE review_pairs SET verdict=?, reason=?, decided_at=? WHERE later_id=? AND earlier_id=?",
                        (verdict, reason, now, later, earlier),
                    )
            reviewed += len(batch)
            live["reviewed"] += len(batch)

    # ---- judged wrong --------------------------------------------------------

    def _judge(self, live: dict[str, Any]) -> None:
        """Memories that agents found misleading more often than useful leave recall."""
        with self._store.reading() as db:
            rows = db.execute(
                """
                SELECT l.memory_id AS id, SUM(l.outcome = 'misleading') AS misleading, SUM(l.outcome = 'useful') AS useful
                FROM memory_loans l JOIN memories m ON m.id = l.memory_id
                WHERE l.outcome IS NOT NULL AND m.status = 'active'
                  AND NOT EXISTS (SELECT 1 FROM memory_links k WHERE k.relation = 'kept' AND k.to_id = l.memory_id AND k.undone_at IS NULL)
                GROUP BY l.memory_id HAVING misleading >= ? AND misleading > useful
                """,
                (MISLEADING_MIN,),
            ).fetchall()
        if not rows:
            return
        now = self._store._clock()
        with self._store._tx() as db:
            for row in rows:
                db.execute(
                    "UPDATE memories SET status='expired', expired_at=?, expire_reason='returns' WHERE id=? AND status='active'", (now, row["id"])
                )
                db.execute(
                    "INSERT INTO memory_links(relation, from_id, to_id, reason, decided_by, created_at) VALUES('judged',?,?,?, 'returns', ?)",
                    (row["id"], row["id"], f"借用后 {row['misleading']} 次被判误导、{row['useful']} 次被判有用", now),
                )
                self._distiller._restated.remove(row["id"])
                live["judged"] += 1

    # ---- drawn up into experience -----------------------------------------------

    def groups(self) -> dict[str, dict[str, Any]]:
        """The active memories of each project or folder (experience cards apart)."""
        with self._store.reading() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT id, agent_id, session_id FROM memories WHERE status = 'active' AND kind != 'experience'"
            )]
        self._distiller._annotate(rows)
        found: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row["group"] == "folder:":
                continue  # no folder known: nothing ties these memories together
            entry = found.setdefault(row["group"], {"label": row["label"], "ids": []})
            entry["ids"].append(row["id"])
        return found

    def _digest(self, live: dict[str, Any]) -> None:
        groups = self.groups()
        with self._store.reading() as db:
            state = {row["group_key"]: row["memories"] for row in db.execute("SELECT group_key, memories FROM digests")}
        due = [
            (key, entry) for key, entry in groups.items()
            if len(entry["ids"]) >= DIGEST_MIN and (key not in state or len(entry["ids"]) - state[key] >= DIGEST_GROWTH)
        ]
        due.sort(key=lambda item: -len(item[1]["ids"]))
        for key, entry in due[: self._limits["groups"]]:
            if self._halt.is_set() or self._stop.is_set():
                return
            self._draw_up(key, entry, live)
            live["groups"] += 1

    def _pick(self, db, ids: list[int]) -> list[int]:
        """The memories that matter most in a project: said again and again, found useful, recent."""
        marks = ",".join("?" * len(ids))
        restated = dict(db.execute(
            f"SELECT folded_into, COUNT(*) FROM memories WHERE status = 'folded' AND folded_into IN ({marks}) GROUP BY folded_into", ids
        ).fetchall())
        returns: dict[int, int] = {}
        for row in db.execute(
            f"""SELECT memory_id, SUM(CASE outcome WHEN 'useful' THEN 3 WHEN 'misleading' THEN -4 ELSE 0 END)
                FROM memory_loans WHERE memory_id IN ({marks}) AND outcome IS NOT NULL GROUP BY memory_id""",
            ids,
        ):
            returns[row[0]] = row[1] or 0
        ranked = sorted(ids, key=lambda mid: (-(returns.get(mid, 0) + 0.5 * min(restated.get(mid, 0), 10)), -mid))
        return ranked[:DIGEST_INPUT]

    def _draw_up(self, key: str, entry: dict[str, Any], live: dict[str, Any]) -> None:
        from .distill import fingerprint  # the same fingerprint every memory gets

        with self._store.reading() as db:
            chosen = self._pick(db, entry["ids"])
            said = self._said(db, chosen)
            existing = [dict(row) for row in db.execute(
                "SELECT id, title, statement, when_to_use FROM memories WHERE kind = 'experience' AND status = 'active' AND digest_group = ? ORDER BY id",
                (key,),
            )]
        listed = [mid for mid in chosen if mid in said]
        lines = [f"项目:{entry['label']}", "", "记忆:"]
        for mid in listed:
            memory = said[mid]
            lines.append(f"#{mid} ({memory['when'][:10] or '日期不详'}) {memory['statement']}")
        if existing:
            lines += ["", "已有的经验:"]
            lines += [f"#{card['id']} {card['title']}:{card['statement']}(什么时候用:{card['when_to_use']})" for card in existing]
        text = self._ask("\n".join(lines), DIGEST_SYSTEM, live)
        try:
            payload = _json_reply(text, "experiences")
        except ValueError:
            return  # an unreadable answer: try again when this project has grown
        allowed = set(listed)
        cards = []
        for item in payload["experiences"][:DIGEST_MAX_CARDS]:
            if not isinstance(item, dict):
                continue
            title, statement, when = (item.get(name) for name in ("title", "statement", "when"))
            sources = item.get("derived_from")
            if not all(isinstance(value, str) and value.strip() for value in (title, statement)) or not isinstance(sources, list):
                continue
            sources = sorted({mid for mid in sources if isinstance(mid, int) and not isinstance(mid, bool) and mid in allowed})
            if len(sources) < 2:
                continue  # an experience rests on more than one memory, or it is just that memory again
            cards.append({"title": _clip(title, 60), "statement": _clip(statement, 500),
                          "when": _clip(when if isinstance(when, str) else "", 200), "sources": sources})
        keep = {mid for mid in payload.get("keep") or [] if isinstance(mid, int)}
        now = self._store._clock()
        with self._store._tx() as db:
            made = []
            for card in cards:
                newest = max(card["sources"])
                origin = db.execute("SELECT agent_id, session_id FROM memories WHERE id = ?", (newest,)).fetchone()
                if origin is None:
                    continue
                cursor = db.execute(
                    """
                    INSERT OR IGNORE INTO memories(fingerprint, statement, kind, agent_id, session_id, model, created_at,
                                                   title, when_to_use, digest_group)
                    VALUES(?,?, 'experience', ?,?,?,?,?,?,?)
                    """,
                    (fingerprint(card["statement"]), card["statement"], origin["agent_id"], origin["session_id"],
                     live["model"], now, card["title"], card["when"], key),
                )
                if not cursor.rowcount:
                    continue
                experience = cursor.lastrowid
                made.append(experience)
                db.execute(
                    f"UPDATE memories SET said_at = (SELECT COALESCE(MAX(said_at), '') FROM memories WHERE id IN ({','.join('?' * len(card['sources']))})) WHERE id = ?",
                    (*card["sources"], experience),
                )
                # Its evidence: the words behind the memories it rests on, the user's first.
                marks = ",".join("?" * len(card["sources"]))
                quotes = db.execute(
                    f"""
                    SELECT e.segment_id, e.quote FROM memory_evidence e LEFT JOIN segments s ON s.id = e.segment_id
                    WHERE e.memory_id IN ({marks}) ORDER BY {USER_VOICE_SQL} DESC, e.id
                    """,
                    card["sources"],
                ).fetchall()
                seen: set[str] = set()
                for segment_id, quote in quotes:
                    if quote in seen:
                        continue
                    seen.add(quote)
                    add_evidence(db, experience, segment_id, quote)
                    if len(seen) >= EXPERIENCE_EVIDENCE:
                        break
                db.executemany(
                    "INSERT INTO memory_links(relation, from_id, to_id, reason, decided_by, created_at) VALUES('derived_from',?,?, '', ?, ?)",
                    [(experience, source, live["model"], now) for source in card["sources"]],
                )
                live["experiences"] += 1
            if made or not cards:
                for card in existing:
                    if card["id"] in keep:
                        continue
                    db.execute("UPDATE memories SET status='superseded' WHERE id=? AND status='active'", (card["id"],))
                    db.execute(
                        "INSERT INTO memory_links(relation, from_id, to_id, reason, decided_by, created_at) VALUES('replaces',?,?,?,?,?)",
                        (made[0] if made else card["id"], card["id"], f"重新归纳「{entry['label']}」后没有再保留", live["model"], now),
                    )
            db.execute(
                "INSERT OR REPLACE INTO digests(group_key, label, memories, digested_at) VALUES(?,?,?,?)",
                (key, entry["label"], len(entry["ids"]), now),
            )

    # ---- undoing -------------------------------------------------------------

    def undo(self, link_id: int) -> None:
        """Take back a replacement or a judgement: the memory returns to recall."""
        now = self._store._clock()
        with self._store._tx() as db:
            link = db.execute("SELECT * FROM memory_links WHERE id = ?", (link_id,)).fetchone()
            if link is None:
                raise ApiError(404, "link_not_found")
            if link["undone_at"] is not None:
                raise ApiError(409, "already_undone")
            if link["relation"] == "replaces":
                db.execute("UPDATE memories SET status='active' WHERE id=? AND status='superseded'", (link["to_id"],))
            elif link["relation"] == "judged":
                db.execute(
                    "UPDATE memories SET status='active', expired_at=NULL, expire_reason='' WHERE id=? AND status='expired'", (link["to_id"],)
                )
                db.execute(
                    "INSERT INTO memory_links(relation, from_id, to_id, reason, decided_by, created_at) VALUES('kept',?,?, '主人拿回来了', 'owner', ?)",
                    (link["to_id"], link["to_id"], now),
                )
            else:
                raise ApiError(409, "cannot_undo", "only a replacement or a judgement can be taken back")
            db.execute("UPDATE memory_links SET undone_at = ? WHERE id = ?", (now, link_id))
            row = db.execute("SELECT statement, kind, status FROM memories WHERE id = ?", (link["to_id"],)).fetchone()
        if row is not None and row["status"] == "active" and row["kind"] != "experience" and self._distiller._restated_ready:
            self._distiller._restated.add(link["to_id"], row["statement"])

    # ---- what the admin page shows ------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._store.reading() as db:
            runs = [dict(row) for row in db.execute("SELECT * FROM evolution_runs ORDER BY id DESC LIMIT 5")]
            waiting = db.execute("SELECT COUNT(*) FROM review_pairs WHERE verdict = ''").fetchone()[0]
            experiences = db.execute("SELECT COUNT(*) FROM memories WHERE kind = 'experience' AND status = 'active'").fetchone()[0]
            replaced = db.execute("SELECT COUNT(*) FROM memories WHERE status = 'superseded'").fetchone()[0]
            judged = db.execute("SELECT COUNT(*) FROM memories WHERE status = 'expired' AND expire_reason = 'returns'").fetchone()[0]
            projects = db.execute("SELECT COUNT(*) FROM digests").fetchone()[0]
        live = dict(self._live) if self.running() and self._live else None
        if live is not None:
            live["pausing"] = self._halt.is_set()
        return {
            "running": live is not None,
            "live": live,
            "waiting_pairs": waiting if self._store._meta("review_pairs_queued") == "1" else None,
            "experiences": experiences,
            "replaced": replaced,
            "judged": judged,
            "projects": projects,
            "runs": runs,
            "has_model": bool(self._distiller._models.resolve(SLOT)),
        }
