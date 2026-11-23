"""A new window, and the user only says "continue".

The words themselves say nothing to look up, so what helps is where it was left: the last conversations in this
project (with any agent, on any computer), how the last one ended, the work in flight on the whiteboard, and what
was decided lately, each with the number of the turn or memory it comes from. That is the hand-over. It is built
from what is stored, so it costs no model call and is there at once.

When a conversation has gone quiet, the daily model also writes a short note of it: the goal, what is done, what is
left, what it waits on, the next step. Each line must quote the turn it rests on, checked word for word like a
memory; a line without its quote is dropped. The owner can see the notes, delete them, and switch this off.

A hand-over is given once, in a new window, and never mid-conversation: there the agent already knows.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any

from .errors import ApiError
from .model_client import ModelError
from .recall import _clip
from .store import Store, normalize_folder, surface_label
from .voiceprint import own_part, relayed

log = logging.getLogger("tl_server.continuity")

ASK_CHARS = 30  # longer prompts say what they are about, and are looked up as such
ASKS = re.compile(
    r"继续|接着|接上|往下做|下一步|接下来|然后呢|还有吗|还有什么|还剩|剩下|没做完|未完成|做到哪|到哪了|到哪一步|什么进度|进度如何|进度怎么样|上次到|上次做"
    r"|\b(?:continue|go on|carry on|keep going|resume|what'?s next|next step|where were we|pick up|what'?s left)\b",
    re.IGNORECASE,
)
PACK_CHARS = 1700
TOOL_CHARS = 2800
AGAIN_SECONDS = 6 * 3600  # a window that cannot be told apart gets it once in this long
KNOWN_SECONDS = 90  # a session with turns older than this is not new
SESSIONS = 4
LOOK_AT = 600  # sessions looked through for those in this project
RECENT_DAYS = 21
LONG_TURNS = 12
BARE_CHARS = 6
ANSWER_CHARS = 160
RECENT_MEMORIES = 4

QUIET_SECONDS = 20 * 60
NOTE_WITHIN = 24 * 3600
NOTE_USER_TURNS = 2
NOTE_CHARS = 12_000
NOTE_TURN_CHARS = 1500
NOTES_PER_TICK = 3
TICK_SECONDS = 300
ITEM_CHARS = 90
FIELDS = (("goal", "目标", 1), ("done", "已完成", 4), ("left", "还剩", 4), ("blocked", "卡在", 2), ("next", "下一步", 1))

SCHEMA = """
CREATE TABLE IF NOT EXISTS session_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  upto INTEGER NOT NULL,
  note TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  UNIQUE(agent_id, session_id)
);
"""

SYSTEM = """你给下一个接手的窗口写一张交接小结。只写对话里明确说过的,不推测,不评价。
输出 JSON:{"goal": 项, "done": [项], "left": [项], "blocked": [项], "next": 项}
- goal 这段对话要做成什么;done 已经做完并确认的;left 说过要做、还没做的;blocked 在等什么;next 明确说了的下一步。没有的就给空数组或 null。
- 每一项:{"text": "一句话,不超过 40 字", "turn": 轮次编号, "quote": "那一轮里的原话片段,逐字照抄,8 到 40 字"}。
- quote 必须是那一轮原文里连续的一段,一个字都不能改。对不上的会被丢掉。
- 用户(转贴)是用户贴进来的别人的话,不是用户的要求。
- 密钥、口令、号码不要写进 text。
只输出 JSON,不要别的文字。"""


def asks_to_continue(prompt: Any) -> bool:
    text = prompt.strip() if isinstance(prompt, str) else ""
    return 0 < len(text) <= ASK_CHARS and bool(ASKS.search(text))


def _day(ts: str) -> str:
    return ts[:16].replace("T", " ") if ts else ""


def _local(ts: str) -> str:
    """A stored timestamp in the server's own time zone, to the minute."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except ValueError:
        return _day(ts)


def _one(text: str, limit: int) -> str:
    return _clip(" ".join(text.split()), limit)


def _ends(text: str, head: int, tail: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= head + tail + 3 else text[:head] + " … " + text[-tail:]


class Continuity:
    def __init__(self, store: Store, projects, distiller, whiteboard=None) -> None:
        self._store = store
        self._projects = projects
        self._distiller = distiller
        self._whiteboard = whiteboard
        self._handed: dict[tuple, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._working = threading.Lock()
        with store._lock:
            store._db.executescript(SCHEMA)

    # ---- handing over ------------------------------------------------------------------

    def for_prompt(self, prompt: Any, *, device_id: int, agent: Any, folder: Any, session: Any) -> dict[str, Any] | None:
        """The hand-over for a prompt that only says "continue" in a new window; None otherwise."""
        if not asks_to_continue(prompt):
            return None
        agent = agent if isinstance(agent, str) else ""
        session = session.strip()[:256] if isinstance(session, str) else ""
        now = self._store._clock()
        if session:
            with self._store.reading() as db:
                known = db.execute(
                    """
                    SELECT 1 FROM segments s JOIN agents a ON a.id = s.agent_id
                    WHERE a.device_id = ? AND a.name = ? AND s.session_id = ? AND s.role = 'user' AND s.received_at < ? LIMIT 1
                    """, (device_id, agent, session, now - KNOWN_SECONDS)).fetchone()
            if known:
                return None  # mid-conversation: the agent knows
        key = (device_id, agent, session or normalize_folder(folder if isinstance(folder, str) else ""))
        with self._lock:
            if now - self._handed.get(key, 0.0) < AGAIN_SECONDS:
                return None
        pack = self.pack(device_id=device_id, agent=agent, folder=folder, session=session, limit=PACK_CHARS)
        if pack is None:
            return None
        with self._lock:
            self._handed[key] = now
            if len(self._handed) > 500:
                self._handed = dict(sorted(self._handed.items(), key=lambda item: -item[1])[:300])
        return pack

    def pack(self, *, device_id: int, agent: str, folder: Any, session: str = "", limit: int = TOOL_CHARS) -> dict[str, Any] | None:
        here = self._projects.same_place(device_id, folder)
        cwd = normalize_folder(folder) if isinstance(folder, str) and folder.strip() else ""
        project = self._projects.owner_of()(device_id, cwd) if cwd else ""
        found = self._sessions(here, device_id, agent, session)
        if not found:
            return None
        where = f"项目「{project}」" if project else (f"文件夹 {cwd}" if here is not None else "")
        head = (f"用户要接着做。{where}上次做到这里" if where else "用户要接着做。认不出是哪个项目,下面是这台电脑上这个 agent 最近的一次")
        lines = [head + "(出自存下的原话;和现在不符以现在为准,拿不准就问用户):"]
        last = found[0]
        lines += self._last(last)
        for item in found[1:]:
            lines.append(f"更早:{self._who(item)}:{_one(item['topic'], 60)}")
        if project and self._whiteboard is not None:
            lines += self._whiteboard.startup_lines(project)
        lines += self._decided(here)
        lines.append("要看前后文用 time_library_source 加 turn_id;要查细节用 time_library_search。")
        text = ""
        for line in lines:  # what comes first matters most
            if len(text) + len(line) + 1 > limit:
                break
            text += ("\n" if text else "") + line
        return {"text": text, "project": project, "session": last["session"], "agent": last["agent"], "device": last["device"]}

    @staticmethod
    def _who(item: dict[str, Any]) -> str:
        return f"{_local(item['last'])} {item['device']} · {item['agent']}" + (f"({item['surface']})" if item["surface"] else "")

    def _sessions(self, here, device_id: int, agent: str, session: str) -> list[dict[str, Any]]:
        with self._store.reading() as db:
            rows = db.execute(
                """
                SELECT p.agent_id, p.session_id, p.last_ts, a.name AS agent, a.device_id, d.name AS device,
                       COALESCE(s.cwd, '') AS cwd, COALESCE(s.surface, '') AS surface
                FROM session_spans p JOIN agents a ON a.id = p.agent_id JOIN devices d ON d.id = a.device_id
                LEFT JOIN sessions s ON s.agent_id = p.agent_id AND s.session_id = p.session_id
                ORDER BY p.last_ts DESC LIMIT ?
                """, (LOOK_AT,)).fetchall()
            chosen = []
            for row in rows:
                if session and row["session_id"] == session:
                    continue
                fits = here(row["device_id"], row["cwd"]) if here is not None else (row["device_id"] == device_id and row["agent"] == agent)
                if not fits:
                    continue
                first = db.execute(
                    "SELECT text FROM segments WHERE agent_id = ? AND session_id = ? AND role = 'user' ORDER BY COALESCE(ts, ''), id LIMIT 1",
                    (row["agent_id"], row["session_id"])).fetchone()
                if first is None:
                    continue
                if asks_to_continue(own_part(first["text"])) and db.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM segments WHERE agent_id = ? AND session_id = ? AND role = 'user' LIMIT 2)",
                    (row["agent_id"], row["session_id"])).fetchone()[0] < 2:
                    continue  # this very window: it opened with nothing but "continue"
                said = db.execute(
                    "SELECT COUNT(*) FROM segments WHERE agent_id = ? AND session_id = ? AND role = 'user'", (row["agent_id"], row["session_id"])).fetchone()[0]
                topic, label = own_part(first["text"]), "开头"
                if said > LONG_TURNS:  # what a long conversation began with says little about where it is now
                    later = self._meant(db, row["agent_id"], row["session_id"], 1)
                    if later:
                        topic, label = later[0][1], "最近在说"
                chosen.append({"agent_id": row["agent_id"], "session": row["session_id"], "last": row["last_ts"], "agent": row["agent"],
                               "device": row["device"], "surface": surface_label(row["surface"]), "topic": topic, "label": label, "said": said})
                if len(chosen) == SESSIONS:
                    break
        return chosen

    @staticmethod
    def _meant(db, agent_id: int, session: str, count: int) -> list[tuple[int, str, bool]]:
        """The user's latest turns that say something (not a bare "yes" or "go on"): (turn, words, pasted in)."""
        found: list[tuple[int, str, bool]] = []
        for row in db.execute(
            "SELECT id, text FROM segments WHERE agent_id = ? AND session_id = ? AND role = 'user' ORDER BY COALESCE(ts, '') DESC, id DESC LIMIT 12",
            (agent_id, session)):
            text = own_part(row["text"]).strip()
            if len(text) > BARE_CHARS and not asks_to_continue(text):
                found.append((row["id"], text, relayed(text)))
                if len(found) == count:
                    break
        return found

    def _last(self, item: dict[str, Any]) -> list[str]:
        with self._store.reading() as db:
            meant = self._meant(db, item["agent_id"], item["session"], 2)
            latest = db.execute(
                "SELECT id, text FROM segments WHERE agent_id = ? AND session_id = ? AND role = 'user' ORDER BY COALESCE(ts, '') DESC, id DESC LIMIT 1",
                (item["agent_id"], item["session"])).fetchone()
            answers = db.execute(
                "SELECT id, text FROM segments WHERE agent_id = ? AND session_id = ? AND role = 'assistant' ORDER BY COALESCE(ts, '') DESC, id DESC LIMIT 12",
                (item["agent_id"], item["session"])).fetchall()
            note = db.execute("SELECT note, upto FROM session_notes WHERE agent_id = ? AND session_id = ?", (item["agent_id"], item["session"])).fetchone()
        lines = [f"上次:{self._who(item)} · 用户说了 {item['said']} 句 · {item['label']}:{_one(item['topic'], 60)}"]
        if note is not None:
            noted = json.loads(note["note"])
            for field, label, _ in FIELDS:
                for entry in noted.get(field) or []:
                    lines.append(f"  {label}:{entry['text']}(turn_id={entry['turn']})")
        # A bare "go on" or "yes" as the last word says little: what was said before it, and then that word.
        for turn, text, pasted in reversed(meant):
            lines.append(f"  用户{'(转贴)' if pasted else ''}说:「{_one(text, 160)}」(turn_id={turn})")
        if latest is not None and all(turn < latest["id"] for turn, _, _ in meant):
            lines.append(f"  用户最后说:「{_one(own_part(latest['text']), 40)}」(turn_id={latest['id']})")
        if answers:
            # The last full answer: a line said on the way ("now the tests:") says nothing about where it stands.
            full = next((row for row in answers if len(row["text"]) >= ANSWER_CHARS), answers[0])
            lines.append(f"  助手{'最后' if full is answers[0] else '最近一次完整'}说:「{_ends(full['text'], 180, 380)}」(turn_id={full['id']})")
        return lines

    def _decided(self, here) -> list[str]:
        if here is None:
            return []
        since = datetime.fromtimestamp(self._store._clock() - RECENT_DAYS * 86400, timezone.utc).strftime("%Y-%m-%d")
        with self._store.reading() as db:
            rows = db.execute(
                """
                SELECT m.id, m.kind, m.statement, m.said_at, a.device_id, s.cwd FROM memories m JOIN agents a ON a.id = m.agent_id
                JOIN sessions s ON s.agent_id = m.agent_id AND s.session_id = m.session_id
                WHERE m.status = 'active' AND m.kind IN ('decision', 'correction') AND m.said_at >= ? ORDER BY m.said_at DESC LIMIT 400
                """, (since,)).fetchall()
        chosen = [row for row in rows if here(row["device_id"], row["cwd"])][:RECENT_MEMORIES]
        return ["最近定下的:"] + [f"  #{row['id']} {(row['said_at'] or '')[5:10]} {_one(row['statement'], 80)}" for row in chosen] if chosen else []

    def startup_line(self, device_id: int, folder: Any) -> str:
        """One line for a window's catalog: when and with whom this was last worked on."""
        here = self._projects.same_place(device_id, folder)
        if here is None:
            return ""
        found = self._sessions(here, device_id, "", "")
        return f"上次在这里:{self._who(found[0])}:{_one(found[0]['topic'], 40)}(用户说「继续」就用 time_library_continue)" if found else ""

    # ---- notes of conversations that went quiet ------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._store._meta("session_notes") != "off"

    def switch(self, on: Any) -> dict[str, Any]:
        with self._store._tx() as db:
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('session_notes', ?)", ("on" if on else "off",))
        return self.listing()

    def listing(self) -> dict[str, Any]:
        with self._store.reading() as db:
            rows = db.execute(
                """
                SELECT n.id, n.session_id, n.note, n.model, n.created_at, a.name AS agent, a.device_id, d.name AS device,
                       COALESCE(s.cwd, '') AS cwd, COALESCE(s.surface, '') AS surface
                FROM session_notes n JOIN agents a ON a.id = n.agent_id JOIN devices d ON d.id = a.device_id
                LEFT JOIN sessions s ON s.agent_id = n.agent_id AND s.session_id = n.session_id ORDER BY n.created_at DESC LIMIT 12
                """).fetchall()
            total = db.execute("SELECT COUNT(*) FROM session_notes").fetchone()[0]
        owner = self._projects.owner_of()
        return {"enabled": self.enabled, "model": bool(self._distiller._models.resolve("daily")), "total": total, "notes": [
            {"id": row["id"], "session": row["session_id"], "device": row["device"], "agent": row["agent"], "surface": surface_label(row["surface"]),
             "folder": row["cwd"], "project": owner(row["device_id"], row["cwd"]), "at": row["created_at"], "model": row["model"],
             "lines": [{"label": label, **entry} for field, label, _ in FIELDS for entry in json.loads(row["note"]).get(field) or []]}
            for row in rows]}

    def delete(self, note_id: int) -> dict[str, Any]:
        with self._store._tx() as db:
            db.execute("DELETE FROM session_notes WHERE id = ?", (note_id,))
        return self.listing()

    def run_scheduler(self) -> None:
        def loop() -> None:
            while not self._stop.wait(TICK_SECONDS):
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 - a note is a help: never take anything down
                    log.exception("session notes")

        threading.Thread(target=loop, daemon=True, name="session-notes").start()

    def shutdown(self) -> None:
        self._stop.set()

    def tick(self) -> int:
        """Write notes of conversations that went quiet. How many were written."""
        if not self.enabled or not self._distiller._models.resolve("daily") or not self._working.acquire(blocking=False):
            return 0
        try:
            written = 0
            for agent_id, session_id, upto in self._due():
                if self._stop.is_set() or written >= NOTES_PER_TICK:
                    break
                try:
                    written += int(self._note(agent_id, session_id, upto))
                except ModelError as error:
                    log.info("session note not written: %s", error.reason)
                    break  # the model is away: later
            return written
        finally:
            self._working.release()

    def _due(self) -> list[tuple[int, str, int]]:
        now = self._store._clock()
        stamp = lambda at: datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")  # noqa: E731
        with self._store.reading() as db:
            rows = db.execute(
                """
                SELECT p.agent_id, p.session_id, COALESCE(n.upto, 0) AS upto FROM session_spans p
                LEFT JOIN session_notes n ON n.agent_id = p.agent_id AND n.session_id = p.session_id
                WHERE p.last_ts > ? AND p.last_ts < ? ORDER BY p.last_ts DESC
                """, (stamp(now - NOTE_WITHIN), stamp(now - QUIET_SECONDS))).fetchall()
            due = []
            for row in rows:
                said = db.execute(
                    "SELECT COUNT(*) FROM segments WHERE agent_id = ? AND session_id = ? AND id > ? AND role = 'user' AND imported = 0",
                    (row["agent_id"], row["session_id"], row["upto"])).fetchone()[0]
                if said >= NOTE_USER_TURNS:
                    due.append((row["agent_id"], row["session_id"], row["upto"]))
        return due

    def _note(self, agent_id: int, session_id: str, upto: int) -> bool:
        with self._store.reading() as db:
            rows = db.execute(
                "SELECT id, role, text FROM segments WHERE agent_id = ? AND session_id = ? ORDER BY COALESCE(ts, ''), id", (agent_id, session_id)).fetchall()
        if not rows:
            return False
        first = next((row for row in rows if row["role"] == "user"), None)
        turns, used = [], 0
        for row in reversed(rows):
            text = own_part(row["text"]) if row["role"] == "user" else row["text"]
            used += min(len(text), NOTE_TURN_CHARS)
            if turns and used > NOTE_CHARS:
                break
            turns.append((row["id"], row["role"], text))
        turns.reverse()
        if first is not None and all(turn[0] != first["id"] for turn in turns):
            turns.insert(0, (first["id"], "user", own_part(first["text"])))
        shown = []
        for turn, role, text in turns:
            who = "助手" if role == "assistant" else ("用户(转贴)" if relayed(text) else "用户")
            # Long answers keep their beginning and their end: that is where conclusions and next steps are.
            shown.append(f"[轮次 {turn} {who}] " + (text if len(text) <= NOTE_TURN_CHARS else text[:600] + "\n……\n" + text[-(NOTE_TURN_CHARS - 600):]))
        reply = self._distiller._complete("\n\n".join(shown), "daily", None, system=SYSTEM, max_tokens=2000)
        note = _checked(reply.get("text") or "", {turn: text for turn, _, text in turns})
        newest = max(row["id"] for row in rows)
        with self._store._tx() as db:
            db.execute(
                """
                INSERT INTO session_notes(agent_id, session_id, upto, note, model, created_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(agent_id, session_id) DO UPDATE SET upto=excluded.upto, note=excluded.note, model=excluded.model, created_at=excluded.created_at
                """, (agent_id, session_id, newest, json.dumps(note, ensure_ascii=False), reply.get("model", ""), self._store._clock()))
        return True


def _checked(text: str, turns: dict[int, str]) -> dict[str, list[dict[str, Any]]]:
    """Only lines whose quoted words are really in the turn they name."""
    start, end = text.find("{"), text.rfind("}")
    try:
        said = json.loads(text[start : end + 1]) if 0 <= start < end else {}
    except ValueError:
        said = {}
    note: dict[str, list[dict[str, Any]]] = {}
    for field, _, most in FIELDS:
        value = said.get(field) if isinstance(said, dict) else None
        kept = []
        for item in value if isinstance(value, list) else [value]:
            if not isinstance(item, dict):
                continue
            words, quote = item.get("text"), item.get("quote")
            turn = int(item["turn"]) if str(item.get("turn", "")).strip().isdigit() else None
            if not isinstance(words, str) or not words.strip() or not isinstance(quote, str) or len(quote.strip()) < 4:
                continue
            if turn not in turns or quote.strip() not in turns[turn]:
                continue
            kept.append({"text": _one(words, ITEM_CHARS), "turn": turn, "quote": quote.strip()[:120]})
            if len(kept) == most:
                break
        if kept:
            note[field] = kept
    return note
