"""The whiteboard: the work in flight in a project, written by the agents doing it.

The library shelves hold the past (what was decided, learned, preferred). The
whiteboard holds the present: who took on what, how far it got, who it was handed
to. A new window opens with the work in flight in its project and can pick up a
handoff without the owner relaying a word.

Its rules, as the owner set them:
  - Only conclusions are written: taking on a task, a milestone reached, a
    handoff, a blocker, done. Discussion stays in the conversation.
  - Each agent only adds records; nobody edits or removes another's. The records
    of one task form a thread; the task stands where its latest record says.
  - A record carries the writer's role (施工, 二签, …). The same task claimed twice
    by the same role is marked as a collision, first come first served, shown.
  - The owner never writes the whiteboard.

A task lives in the project its folder was declared for (projects.py): the
whiteboard follows the declaration, never a guess.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .errors import ApiError
from .projects import _owner
from .store import Store, normalize_folder

ACTIONS = {
    "claim": "进行中",
    "progress": "进行中",
    "handoff": "待接棒",
    "blocked": "受阻",
    "done": "完成",
}
OPEN_KINDS = ("claim", "progress", "handoff", "blocked")
STALE_DAYS = 14  # in flight but silent this long: kept, not shown at startup
RECENT_DONE_DAYS = 7
STARTUP_LINES = 3
STARTUP_CHARS = 450
TASK_ID = re.compile(r"^(?:WB-?)?(\d{1,9})$", re.IGNORECASE)

SCHEMA = """
CREATE TABLE IF NOT EXISTS whiteboard_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  project TEXT NOT NULL,
  series TEXT NOT NULL DEFAULT '',
  device_id INTEGER NOT NULL,
  agent TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  next_owner TEXT NOT NULL DEFAULT '',
  memory_ids TEXT NOT NULL DEFAULT '[]',
  collision_with INTEGER,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_whiteboard_task ON whiteboard_records(project, task_id, id);
"""

EXAMPLE = {
    "claim": '{"action": "claim", "task": "白板功能施工", "role": "施工"}',
    "progress": '{"action": "progress", "task_id": "WB-12", "summary": "服务端和测试已完成,还差后台页面"}',
    "handoff": '{"action": "handoff", "task_id": "WB-12", "summary": "施工完成,请二签复核", "next_owner": "二签"}',
    "blocked": '{"action": "blocked", "task_id": "WB-12", "summary": "等主人决定是否删除旧数据"}',
    "done": '{"action": "done", "task_id": "WB-12", "summary": "二签通过,已上线"}',
}


def task_label(task_id: int) -> str:
    return f"WB-{task_id}"


def _bad(field: str, problem: str, action: str = "claim") -> ApiError:
    """An error that says what was wrong and shows a call that works."""
    return ApiError(400, "invalid_field", f"{field}: {problem}. 例如: {EXAMPLE.get(action, EXAMPLE['claim'])}")


def _text(value: Any, field: str, limit: int, action: str, required: bool = False) -> str:
    if value is None or value == "":
        if required:
            raise _bad(field, "必填", action)
        return ""
    if not isinstance(value, str):
        raise _bad(field, "要一段文字", action)
    value = " ".join(value.split())
    if len(value) > limit:
        raise _bad(field, f"最多 {limit} 个字(白板只写一句结论)", action)
    return value


class Whiteboard:
    def __init__(self, store: Store) -> None:
        self._store = store
        with store._lock:
            store._db.executescript(SCHEMA)

    # ---- which project ------------------------------------------------------------

    def project_of(self, device_id: int, folder: Any) -> tuple[str, str] | None:
        if not isinstance(folder, str) or not folder.strip():
            return None
        with self._store.reading() as db:
            mine = [(row[0], row[1], row[2]) for row in db.execute(
                "SELECT folder, project, series FROM project_folders WHERE device_id = ?", (device_id,)
            )]
        return _owner(mine, normalize_folder(folder))

    # ---- writing --------------------------------------------------------------------

    def write(self, device_id: int, body: dict[str, Any]) -> dict[str, Any]:
        action = body.get("action")
        if action not in ACTIONS:
            raise ApiError(400, "invalid_field", "action 要是 claim / progress / handoff / blocked / done 之一。例如: " + EXAMPLE["claim"])
        owner = self.project_of(device_id, body.get("folder"))
        if owner is None:
            raise ApiError(409, "folder_not_declared",
                           "这个文件夹还没声明属于哪个项目,白板挂在项目上。先调用 time_library_declare "
                           '(例如 {"project": "time-library", "series": "tools"}),再写白板。')
        project, series = owner
        agent = _text(body.get("agent"), "agent", 120, action) or "unknown"
        role = _text(body.get("role"), "role", 20, action)
        summary = _text(body.get("summary"), "summary", 200, action, required=action != "claim")
        next_owner = _text(body.get("next_owner"), "next_owner", 40, action, required=action == "handoff")
        memory_ids = body.get("memory_ids") or []
        if not isinstance(memory_ids, list) or len(memory_ids) > 20 or any(
            isinstance(item, bool) or not isinstance(item, int) for item in memory_ids
        ):
            raise _bad("memory_ids", "要一组记忆编号(整数,最多 20 个),就是召回结果里的「记忆编号」", action)
        now = self._store._clock()
        with self._store._tx() as db:
            if memory_ids:
                found = {row[0] for row in db.execute(
                    f"SELECT id FROM memories WHERE id IN ({','.join('?' * len(memory_ids))})", memory_ids
                )}
                missing = [mid for mid in memory_ids if mid not in found]
                if missing:
                    raise _bad("memory_ids", f"没有这些记忆: {missing}", action)
            raw_task = body.get("task_id")
            latest = None
            if raw_task not in (None, ""):
                match = TASK_ID.match(str(raw_task).strip())
                if not match:
                    raise _bad("task_id", "写成白板上显示的编号,如 WB-12", action)
                task_id = int(match.group(1))
                latest = db.execute(
                    "SELECT * FROM whiteboard_records WHERE task_id = ? ORDER BY id DESC LIMIT 1", (task_id,)
                ).fetchone()
                if latest is None:
                    raise ApiError(404, "task_not_found", f"白板上没有 {task_label(task_id)}。新任务用 claim 并给 task(任务名)。例如: {EXAMPLE['claim']}")
                if latest["project"] != project:
                    raise ApiError(409, "other_project", f"{task_label(task_id)} 属于项目「{latest['project']}」,不是这个文件夹的「{project}」。")
                title = latest["title"]
            else:
                if action != "claim":
                    raise _bad("task_id", "进展、交接、受阻、完成都要指明是哪件事", action)
                title = _text(body.get("task"), "task", 60, action, required=True)
                task_id = None
            collision = None
            if action == "claim" and latest is not None and latest["kind"] in ("claim", "progress") \
                    and latest["role"] == role and latest["agent"] != agent:
                collision = latest["id"]  # the same role already on it: first come first served, both shown
            record_id = db.execute(
                """
                INSERT INTO whiteboard_records(task_id, project, series, device_id, agent, role, kind, title, summary,
                                               next_owner, memory_ids, collision_with, created_at)
                VALUES(COALESCE(?, 0), ?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (task_id, project, series, device_id, agent, role, action, title, summary, next_owner,
                 json.dumps(memory_ids), collision, now),
            ).lastrowid
            if task_id is None:
                task_id = record_id  # a new task is named after its first record
                db.execute("UPDATE whiteboard_records SET task_id = ? WHERE id = ?", (task_id, record_id))
        result: dict[str, Any] = {"task": self.task(task_id), "record_id": record_id}
        if collision:
            result["warning"] = f"同一角色({role or '未写角色'})已经有人接了这件事,两条都记下了,请和对方确认分工。"
        return result

    # ---- reading ------------------------------------------------------------------------

    @staticmethod
    def _public(row) -> dict[str, Any]:
        return {
            "record_id": row["id"],
            "kind": row["kind"],
            "state": ACTIONS[row["kind"]],
            "agent": row["agent"],
            "role": row["role"],
            "summary": row["summary"],
            "next_owner": row["next_owner"],
            "memory_ids": json.loads(row["memory_ids"] or "[]"),
            "collision_with": row["collision_with"],
            "created_at": row["created_at"],
        }

    def task(self, task_id: int) -> dict[str, Any]:
        with self._store.reading() as db:
            rows = db.execute("SELECT * FROM whiteboard_records WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
        if not rows:
            raise ApiError(404, "task_not_found", f"白板上没有 {task_label(task_id)}")
        latest = rows[-1]
        return {
            "id": task_label(task_id),
            "title": latest["title"],
            "project": latest["project"],
            "series": latest["series"],
            "state": ACTIONS[latest["kind"]],
            "kind": latest["kind"],
            "latest": self._public(latest),
            "records": [self._public(row) for row in rows],
            "updated_at": latest["created_at"],
            "started_at": rows[0]["created_at"],
        }

    def tasks(self, project: str, include_done: bool = True) -> list[dict[str, Any]]:
        """The project's tasks, newest activity first: in flight, then recently done."""
        with self._store.reading() as db:
            ids = [row[0] for row in db.execute(
                "SELECT task_id FROM whiteboard_records WHERE project = ? GROUP BY task_id ORDER BY MAX(id) DESC", (project,)
            )]
        now = self._store._clock()
        found = []
        for task_id in ids:
            item = self.task(task_id)
            item["stale"] = item["kind"] in OPEN_KINDS and now - item["updated_at"] > STALE_DAYS * 86400
            if item["kind"] == "done" and (not include_done or now - item["updated_at"] > RECENT_DONE_DAYS * 86400):
                continue
            found.append(item)
        return found

    def startup_lines(self, project: str) -> list[str]:
        """At most three lines for a new window: handoffs first, then blockers, then work under way."""
        order = {"handoff": 0, "blocked": 1, "claim": 2, "progress": 2}
        open_tasks = [task for task in self.tasks(project, include_done=False) if task["kind"] in OPEN_KINDS and not task["stale"]]
        open_tasks.sort(key=lambda task: (order[task["kind"]], -task["updated_at"]))
        lines, used = [], 0
        for task in open_tasks:
            latest = task["latest"]
            who = "/".join(part for part in (latest["role"], latest["agent"]) if part)
            line = f"进行中:{task['id']} {task['title']} · {who} → {task['state']}"
            if latest["next_owner"] and task["kind"] == "handoff":
                line += f",交接给 {latest['next_owner']}"
            if latest["summary"]:
                summary = latest["summary"]
                line += ":" + (summary if len(summary) <= 60 else summary[:60] + "…")
            if len(lines) == STARTUP_LINES or used + len(line) > STARTUP_CHARS:
                break
            lines.append(line)
            used += len(line)
        rest = len(open_tasks) - len(lines)
        if rest > 0:
            lines.append(f"(白板上还有 {rest} 件进行中,用 time_library_whiteboard 的 list 看全)")
        return lines
