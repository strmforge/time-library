"""Projects and the startup catalog.

Which project a conversation belongs to is said by an agent, never guessed: an
agent declares "the folder I work in is project P (part of series S)", once,
and every session that worked in that folder or below it belongs to P from
then on. A folder nobody declared belongs to no project.

Projects decide order and labels, not who may see what: agents are good at
telling what matters. The catalog an agent gets when a window opens lists the
current project first, then preferences that hold everywhere, then the other
projects. It is a list of headlines and memory numbers, never the memories'
text; the original words are one call away.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from typing import Any

from .errors import ApiError
from .recall import OUTCOMES, loan_verdicts, voice_note
from .store import Store, normalize_folder

SCHEMA = """
CREATE TABLE IF NOT EXISTS project_folders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id INTEGER NOT NULL,
  folder TEXT NOT NULL,
  project TEXT NOT NULL,
  series TEXT NOT NULL DEFAULT '',
  declared_by TEXT NOT NULL DEFAULT '',
  declared_at REAL NOT NULL,
  UNIQUE(device_id, folder)
);
"""

KIND_LABELS = {"decision": "决定", "preference": "偏好", "correction": "纠正", "fact": "事实", "lesson": "教训", "experience": "经验"}
KIND_ORDER = ("experience", "decision", "lesson", "correction", "fact", "preference")
# MCP clients cut long server instructions (7/2026: cut at about 3,300 characters).
STARTUP_CHARS = 2000
CACHE_SECONDS = 60
OWNER = "用户(后台)"  # declared by the owner on the admin page
FULL_CHARS = 12000
HEADLINE_CHARS = 46


def headline(statement: str) -> str:
    text = " ".join(statement.split())
    if len(text) <= HEADLINE_CHARS:
        return text
    cut = text[:HEADLINE_CHARS]
    for mark in ("。", "；", "，", ",", ";", " "):
        at = cut.rfind(mark)
        if at >= HEADLINE_CHARS // 2:
            return cut[:at] + "…"
    return cut + "…"


def _epoch(stamp: Any) -> float:
    """Seconds since the epoch for an ISO 8601 timestamp, or 0."""
    if not isinstance(stamp, str) or len(stamp) < 19:
        return 0.0
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _gathered(folders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Folders inside another listed folder are counted with it: saying where that one belongs says it for them too."""
    tops: list[dict[str, Any]] = []
    for item in sorted(folders, key=lambda entry: len(entry["folder"])):
        outer = next((top for top in tops if top["device_id"] == item["device_id"] and nested(top["folder"], item["folder"])), None)
        if outer is None:
            tops.append({**item, "inside": 0})
        else:
            outer["memories"] += item["memories"]
            outer["inside"] += 1
    return sorted(tops, key=lambda entry: -entry["memories"])


def _owner(folders: list[tuple[str, str, str]], cwd: str) -> tuple[str, str] | None:
    """The declared project whose folder is cwd or the closest folder above it."""
    best = None
    for folder, project, series in folders:
        if cwd == folder or cwd.startswith(folder.rstrip("/") + "/"):
            if best is None or len(folder) > len(best[0]):
                best = (folder, project, series)
    return (best[1], best[2]) if best else None


# Folders too general to say anything about what is worked on there: a drive, a home folder.
GENERAL = re.compile(r"^(?:/|[A-Za-z]:/?|(?:[A-Za-z]:)?/(?:Users|home)(?:/[^/]+)?(?:/(?:Desktop|Documents|Downloads|桌面|文档|下载))?|/root)$", re.IGNORECASE)


def nested(a: str, b: str) -> bool:
    """The same folder, or one inside the other (not counting drives and home folders, which hold everything)."""
    if not a or not b:
        return False
    if a == b:
        return not GENERAL.match(a)
    outer, inner = (a, b) if len(a) < len(b) else (b, a)
    return not GENERAL.match(outer) and inner.startswith(outer.rstrip("/") + "/")


class Projects:
    def __init__(self, store: Store) -> None:
        self._store = store
        self.whiteboard = None  # the work in flight per project (whiteboard.py), set by the server
        self._cache: tuple[float, list[dict[str, Any]]] | None = None
        self._cache_lock = threading.Lock()
        with store._lock:
            store._db.executescript(SCHEMA)

    # ---- declaring -----------------------------------------------------------

    def declare(self, device_id: int, agent: Any, folder: Any, project: Any, series: Any = "") -> dict[str, Any]:
        def text(value: Any, name: str, limit: int, required: bool) -> str:
            if value is None and not required:
                return ""
            if not isinstance(value, str) or (required and not value.strip()) or len(value.strip()) > limit:
                raise ApiError(400, "invalid_field", f"{name} must be text of at most {limit} characters")
            return value.strip()

        folder = normalize_folder(text(folder, "folder", 512, True))
        project = text(project, "project", 80, True)
        series = text(series, "series", 80, False)
        agent_name = agent.strip()[:120] if isinstance(agent, str) else ""
        with self._store._tx() as db:
            db.execute(
                """
                INSERT INTO project_folders(device_id, folder, project, series, declared_by, declared_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(device_id, folder) DO UPDATE SET project=excluded.project, series=excluded.series,
                    declared_by=excluded.declared_by, declared_at=excluded.declared_at
                """,
                (device_id, folder, project, series, agent_name, self._store._clock()),
            )
        with self._cache_lock:
            self._cache = None  # a declaration shows at once in the next window's catalog
        sessions = sum(1 for _ in self._sessions_in(device_id, folder))
        return {"folder": folder, "project": project, "series": series, "sessions": sessions}

    def owner_of(self):
        """A function (device, folder) -> the declared project it belongs to, or ''; as declared right now."""
        folders: dict[int, list[tuple[str, str, str]]] = {}
        with self._store.reading() as db:
            for row in db.execute("SELECT device_id, folder, project, series FROM project_folders"):
                folders.setdefault(row["device_id"], []).append((row["folder"], row["project"], row["series"]))
        known: dict[tuple[int, str], str] = {}

        def owner(device_id: int, cwd: str) -> str:
            if not cwd:
                return ""
            if (device_id, cwd) not in known:
                found = _owner(folders.get(device_id, []), cwd)
                known[(device_id, cwd)] = found[0] if found else ""
            return known[(device_id, cwd)]

        return owner

    def same_place(self, device_id: int | None, folder: Any):
        """A function (device, folder) -> whether that is where the asking window works: the same declared project
        on any computer, or (undeclared) the same folder or one inside the other on this computer. None when the
        window's folder says nothing."""
        cwd = normalize_folder(folder) if isinstance(folder, str) and folder.strip() else ""
        if device_id is None or not cwd:
            return None
        owner = self.owner_of()
        mine = owner(device_id, cwd)
        if not mine and GENERAL.match(cwd):
            return None

        def same(other_device: int, other: str) -> bool:
            theirs = owner(other_device, other)
            if mine or theirs:
                return bool(mine) and mine == theirs
            return other_device == device_id and nested(cwd, other)

        return same

    def assign(self, device_id: Any, folder: Any, project: Any, series: Any = "") -> dict[str, Any]:
        """The owner says on the admin page which project a folder belongs to ('' = none)."""
        with self._store.reading() as db:
            known = isinstance(device_id, int) and db.execute("SELECT 1 FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not known:
            raise ApiError(404, "device_not_found")
        if isinstance(project, str) and not project.strip():
            folder = normalize_folder(folder) if isinstance(folder, str) else ""
            with self._store._tx() as db:
                db.execute("DELETE FROM project_folders WHERE device_id = ? AND folder = ?", (device_id, folder))
            with self._cache_lock:
                self._cache = None
            return {"folder": folder, "project": "", "series": ""}
        return self.declare(device_id, OWNER, folder, project, series)

    def _sessions_in(self, device_id: int, folder: str):
        with self._store.reading() as db:
            rows = db.execute(
                "SELECT s.cwd FROM sessions s JOIN agents a ON a.id = s.agent_id WHERE a.device_id = ? AND s.cwd != ''",
                (device_id,),
            ).fetchall()
        prefix = folder.rstrip("/") + "/"
        return (row for row in rows if row["cwd"] == folder or row["cwd"].startswith(prefix))

    def pages(self) -> dict[str, Any]:
        """One page per declared project (memories by agent and shelf, experience, the whiteboard),
        and the folders with memories that no one has declared yet."""
        memories = self._memories()
        declared = self.listing()
        names: dict[str, dict[str, Any]] = {}
        for row in declared:
            page = names.setdefault(row["project"], {"project": row["project"], "series": row["series"], "folders": [],
                                                     "memories": 0, "lanes": {}, "kinds": {}, "experiences": []})
            page["folders"].append({key: row[key] for key in ("folder", "device_id", "device", "declared_by", "declared_at")})
        for memory in memories:
            page = names.get(memory["project"])
            if page is None:
                continue
            page["memories"] += 1
            page["lanes"][memory["agent"]] = page["lanes"].get(memory["agent"], 0) + 1
            page["kinds"][memory["kind"]] = page["kinds"].get(memory["kind"], 0) + 1
            if memory["kind"] == "experience" and len(page["experiences"]) < 6:
                page["experiences"].append({"id": memory["id"], "title": memory["title"]})
        for page in names.values():
            page["whiteboard"] = self.whiteboard.tasks(page["project"]) if self.whiteboard is not None else []
        with self._store.reading() as db:
            owned: dict[int, list[tuple[str, str, str]]] = {}
            for row in db.execute("SELECT device_id, folder, project, series FROM project_folders"):
                owned.setdefault(row[0], []).append((row[1], row[2], row[3]))
            loose = db.execute(
                """
                SELECT a.device_id, d.name AS device, s.cwd, COUNT(*) AS memories
                FROM memories m JOIN agents a ON a.id = m.agent_id JOIN devices d ON d.id = a.device_id
                JOIN sessions s ON s.agent_id = m.agent_id AND s.session_id = m.session_id
                WHERE m.status = 'active' AND s.cwd != '' GROUP BY a.device_id, s.cwd ORDER BY memories DESC
                """
            ).fetchall()
        undeclared = [
            {"device_id": row["device_id"], "device": row["device"], "folder": row["cwd"], "memories": row["memories"]}
            for row in loose if _owner(owned.get(row["device_id"], []), row["cwd"]) is None
        ]
        return {
            "pages": sorted(names.values(), key=lambda page: -page["memories"]),
            "undeclared": _gathered(undeclared)[:40],
            "undeclared_folders": len(undeclared),
            "undeclared_memories": sum(item["memories"] for item in undeclared),
        }

    def listing(self) -> list[dict[str, Any]]:
        with self._store.reading() as db:
            rows = db.execute(
                """
                SELECT p.folder, p.project, p.series, p.declared_by, p.declared_at, p.device_id, d.name AS device
                FROM project_folders p JOIN devices d ON d.id = p.device_id ORDER BY p.project, d.name, p.folder
                """
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- which project a memory belongs to --------------------------------------

    def _memories(self) -> list[dict[str, Any]]:
        """Every active memory with its project and score; kept for a minute (a new window's catalog
        must come back in time, even while history is being organised)."""
        with self._cache_lock:
            if self._cache is not None and time.monotonic() - self._cache[0] < CACHE_SECONDS:
                return self._cache[1]
        memories = self._compute_memories()
        with self._cache_lock:
            self._cache = (time.monotonic(), memories)
        return memories

    def _compute_memories(self) -> list[dict[str, Any]]:
        with self._store.reading() as db:
            folders: dict[int, list[tuple[str, str, str]]] = {}
            for row in db.execute("SELECT device_id, folder, project, series FROM project_folders"):
                folders.setdefault(row["device_id"], []).append((row["folder"], row["project"], row["series"]))
            rows = db.execute(
                """
                SELECT m.id, m.kind, m.statement, m.title, m.created_at, m.recall_count, a.device_id, a.name AS agent,
                       COALESCE(s.cwd, '') AS cwd, m.said_at, m.user_quoted,
                       (SELECT COUNT(*) FROM memories f WHERE f.folded_into = m.id AND f.status = 'folded') AS restated
                FROM memories m JOIN agents a ON a.id = m.agent_id
                LEFT JOIN sessions s ON s.agent_id = m.agent_id AND s.session_id = m.session_id
                WHERE m.status = 'active'
                """
            ).fetchall()
            verdicts = loan_verdicts(db, [row["id"] for row in rows])
        now = time.time()
        memories = []
        for row in rows:
            owner = _owner(folders.get(row["device_id"], []), row["cwd"]) if row["cwd"] else None
            judged = verdicts.get(row["id"], {outcome: 0 for outcome in OUTCOMES})
            # How recent: when the words were said, not when they were distilled.
            age_days = max(0.0, (now - (_epoch(row["said_at"]) or row["created_at"] or now)) / 86400)
            # Said again and again in other conversations: it matters to the user.
            score = (
                3 * judged["useful"] - 4 * judged["misleading"] + 0.5 * min(row["recall_count"] or 0, 10)
                + 2 * max(0.0, 30 - age_days) / 30 + 0.3 * min(row["restated"] or 0, 10)
                # Experience is drawn up from many memories: it is what a new window should read first.
                + (5 if row["kind"] == "experience" else 0)
            )
            memories.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "title": headline((row["title"] + ":" + row["statement"]) if row["kind"] == "experience" and row["title"] else row["statement"]),
                    "agent": row["agent"],
                    "project": owner[0] if owner else "",
                    "series": owner[1] if owner else "",
                    "relayed": bool(voice_note(row["kind"], row["statement"], bool(row["user_quoted"]))),
                    "score": score,
                }
            )
        memories.sort(key=lambda item: (-item["score"], -item["id"]))
        return memories

    # ---- the catalog ------------------------------------------------------------------

    def catalog(self, device_id: int, folder: Any, full: bool = False) -> dict[str, Any]:
        cwd = normalize_folder(folder) if isinstance(folder, str) and folder.strip() else ""
        with self._store.reading() as db:
            mine = [
                (row["folder"], row["project"], row["series"])
                for row in db.execute("SELECT folder, project, series FROM project_folders WHERE device_id = ?", (device_id,))
            ]
        current = _owner(mine, cwd) if cwd else None
        memories = self._memories()
        limit = FULL_CHARS if full else STARTUP_CHARS
        lines: list[str] = ["时间图书馆书单(只是目录:要看原话用 time_library_source 加记忆编号,按话题查用 time_library_recall)。"]
        listed: set[int] = set()

        def entry(memory: dict[str, Any], show_project: bool = False) -> str:
            where = f" · {memory['project']}" if show_project and memory["project"] else ""
            label = KIND_LABELS.get(memory["kind"], memory["kind"]) + ("·助手转述" if memory.get("relayed") else "")
            return f"#{memory['id']} [{label}] {memory['title']}{where}"

        def used() -> int:
            return sum(len(item) + 1 for item in lines)

        def add(line: str, memory: dict[str, Any] | None = None, cap: int | None = None) -> bool:
            if used() + len(line) > min(limit, cap or limit):
                return False
            lines.append(line)
            if memory is not None:
                listed.add(memory["id"])
            return True

        def section(heading: str, items: list[dict[str, Any]], cap: int | None = None, show_project: bool = False) -> None:
            """A heading and as many entries as fit; no heading when not even one fits."""
            if not items or used() + len(heading) + len(entry(items[0], show_project)) + 2 > min(limit, cap or limit):
                return
            add(heading)
            for memory in items:
                if not add(entry(memory, show_project), memory, cap):
                    break

        if current:
            project, series = current
            own = [memory for memory in memories if memory["project"] == project]
            kinds = " · ".join(
                f"{KIND_LABELS[kind]} {count}" for kind in KIND_ORDER if (count := sum(1 for m in own if m["kind"] == kind))
            )
            lanes = {}
            for memory in own:
                lanes[memory["agent"]] = lanes.get(memory["agent"], 0) + 1
            lane_text = " · ".join(f"{agent} {count}" for agent, count in sorted(lanes.items(), key=lambda item: -item[1]))
            add(f"当前项目:{project}" + (f"(属于 {series})" if series else "") + f",共 {len(own)} 条" + (f"({kinds})" if kinds else ""))
            if lane_text:
                add(f"各 agent:{lane_text}")
            # The present, before the past: the work in flight in this project.
            if self.whiteboard is not None:
                if full:
                    board = [
                        f"{task['id']} {task['title']} → {task['state']}" + (f":{task['latest']['summary']}" if task["latest"]["summary"] else "")
                        for task in self.whiteboard.tasks(project)
                    ]
                    if board:
                        add("白板(在飞与最近完成):")
                        for line in board:
                            add(line)
                else:
                    for line in self.whiteboard.startup_lines(project):
                        add(line)
            project_cap = None if full else int(limit * 0.65)
            for memory in own:
                if not add(entry(memory), memory, project_cap):
                    break
        else:
            add("这个文件夹还没声明属于哪个项目。确认项目名后用 time_library_declare 声明一次,以后在这个文件夹开的窗口都会先看到该项目的书单。")

        preferences = [m for m in memories if m["kind"] == "preference" and m["id"] not in listed]
        section("跨项目的偏好:", preferences[: 40 if full else 8], None if full else int(limit * 0.9), show_project=True)

        counts: dict[str, int] = {}
        for memory in memories:
            if memory["project"] and (not current or memory["project"] != current[0]):
                counts[memory["project"]] = counts.get(memory["project"], 0) + 1
        loose = sum(1 for memory in memories if not memory["project"])
        if counts:
            add("其他项目:" + "、".join(f"{name}({count})" for name, count in sorted(counts.items(), key=lambda item: -item[1])))
        if not current or full:
            others = [m for m in memories if m["id"] not in listed]
            section("常用的其他记忆:" if not full else "其余记忆:", others, show_project=True)
        if loose:
            add(f"另有 {loose} 条记忆不属于任何已声明的项目。")
        omitted = len(memories) - len(listed)
        if omitted > 0:
            lines.append(f"(书单列了 {len(listed)} 条,另有 {omitted} 条没列出;完整目录用 time_library_catalog。)")
        return {
            "project": {"name": current[0], "series": current[1]} if current else None,
            "text": "\n".join(lines),
            "listed": len(listed),
            "total": len(memories),
        }
