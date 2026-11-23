"""Proof: whether the library is sound, and whether memory helps at all.

The owner is not an operator. Once a night (and on request) a checkup reads the
library and says, in a few lines marked ✅ ⚠️ 🔴, what is sound and what needs a
look: can every memory still be traced to its words, is anything stuck, is any
computer silent, does recall find what it should. It costs no model calls,
except once to write the test questions recall is measured with.

On request it also tests the whole point of the library: the same questions are
answered twice by the model, once with no memory and once with what recall
hands it, and a model judges each answer against the memory it was written
from. The questions come from the memories themselves, so this measures how
much a window gains when the answer is in the library, not every kind of task.
"""

from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from typing import Any

from .voiceprint import USER_VOICE_SQL
from .errors import ApiError
from .model_client import ModelError
from .recall import speaks_for_user

log = logging.getLogger("tl_server.doctor")

PROBES_WANTED = 50
PROBES_MIN = 30
COMPARE_DEFAULT = 40
BATCH = 10
OFFLINE_HOURS = 24
CHECK_SECONDS = 600
NIGHT_WINDOW_HOURS = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS doctor_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,
  started_at REAL NOT NULL,
  finished_at REAL,
  report TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS probe_questions (
  memory_id INTEGER PRIMARY KEY,
  question TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS compare_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at REAL NOT NULL,
  finished_at REAL,
  status TEXT NOT NULL,
  questions INTEGER NOT NULL DEFAULT 0,
  off_right INTEGER NOT NULL DEFAULT 0,
  on_right INTEGER NOT NULL DEFAULT 0,
  found INTEGER NOT NULL DEFAULT 0,
  details TEXT NOT NULL DEFAULT '[]',
  model TEXT NOT NULL DEFAULT '',
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT ''
);
"""

PROBE_SYSTEM = """下面是一个 AI 助手长期记忆库里的若干条记忆。为每条写一个问题:设想另一个 AI 助手正在干活,需要这条记忆里的信息时会怎么问。
要求:像真实提问一样自然,一句话;不要照抄记忆里的句子和关键词,换一种说法,项目名、工具名这类专有名词可以保留;只问这条记忆能回答的事。
只输出 JSON,不要别的文字:{"questions":[{"n":1,"q":"…"}]}"""

ANSWER_OFF_SYSTEM = """回答下面每个问题,每个一两句。你手上没有关于这位用户和他的项目的任何背景资料;不知道就答"不知道",不要猜。
只输出 JSON,不要别的文字:{"answers":[{"n":1,"a":"…"}]}"""

ANSWER_ON_SYSTEM = """回答下面每个问题,每个一两句。每个问题后面附了从用户长期记忆里找到的几条可能相关的记忆,可以依据它们回答;记忆里没有答案就答"不知道",不要猜。
只输出 JSON,不要别的文字:{"answers":[{"n":1,"a":"…"}]}"""

JUDGE_SYSTEM = """判断每个回答是否答对了问题。每组给了问题、参考事实(正确答案所依据的记忆)和回答。
- right:回答与参考事实一致,答到了要点
- wrong:回答与参考事实不符,或答非所问
- unknown:回答说不知道、没有答案
只输出 JSON,不要别的文字:{"verdicts":[{"n":1,"v":"right"}]}"""


def _json_list(text: str, key: str) -> dict[int, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        items = json.loads(cleaned[start : end + 1]).get(key)
    except (ValueError, AttributeError):
        return {}
    found = {}
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("n"), int):
            found[item["n"]] = item
    return found


class Doctor:
    def __init__(self, store, distiller, recall, vectors=None, whiteboard=None) -> None:
        self._store = store
        self._distiller = distiller
        self._recall = recall
        self._vectors = vectors
        self._whiteboard = whiteboard
        self._guard = threading.Lock()
        self._busy: dict[str, threading.Thread] = {}
        self._live: dict[str, Any] = {}
        self._stop = threading.Event()
        with store._lock:
            store._db.executescript(SCHEMA)
            store._db.execute("UPDATE compare_runs SET status='interrupted', finished_at=? WHERE status='running'", (store._clock(),))

    # ---- running in the background ------------------------------------------------

    def _launch(self, name: str, work) -> dict[str, Any]:
        with self._guard:
            thread = self._busy.get(name)
            if thread is not None and thread.is_alive():
                raise ApiError(409, "already_running")
            thread = threading.Thread(target=work, daemon=True, name=f"doctor-{name}")
            self._busy[name] = thread
            thread.start()
        return {"ok": True}

    def running(self, name: str) -> bool:
        thread = self._busy.get(name)
        return thread is not None and thread.is_alive()

    def wait(self, timeout: float = 120) -> None:
        for thread in list(self._busy.values()):
            thread.join(timeout)

    def start_checkup(self, trigger: str = "manual") -> dict[str, Any]:
        return self._launch("checkup", lambda: self._safe(self.checkup, trigger))

    def start_compare(self, questions: int = COMPARE_DEFAULT) -> dict[str, Any]:
        if not self._distiller._models.resolve("daily"):
            raise ApiError(409, "no_model", "assign a model to daily distillation first")
        if isinstance(questions, bool) or not isinstance(questions, int) or not 5 <= questions <= 200:
            raise ApiError(400, "invalid_field", "questions must be a whole number from 5 to 200")
        return self._launch("compare", lambda: self._safe(self.compare, questions))

    @staticmethod
    def _safe(work, *args) -> None:
        try:
            work(*args)
        except Exception:
            log.exception("doctor work failed")

    def shutdown(self) -> None:
        self._stop.set()

    def tick(self) -> str:
        """Once a night: a checkup (no model calls unless test questions are missing)."""
        from . import distill

        now = time.localtime(self._store._clock())
        if not distill.NIGHTLY_HOUR <= now.tm_hour < distill.NIGHTLY_HOUR + NIGHT_WINDOW_HOURS or self.running("checkup"):
            return ""
        tonight = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, distill.NIGHTLY_HOUR, 0, 0, 0, 0, -1))
        with self._store.reading() as db:
            if db.execute("SELECT 1 FROM doctor_runs WHERE trigger = 'nightly' AND started_at >= ?", (tonight,)).fetchone():
                return ""
        self.start_checkup("nightly")
        return "nightly"

    def run_scheduler(self) -> None:
        def loop() -> None:
            while not self._stop.wait(CHECK_SECONDS):
                try:
                    self.tick()
                except Exception:
                    log.exception("doctor scheduler failed")

        threading.Thread(target=loop, daemon=True, name="doctor-scheduler").start()

    # ---- the test questions --------------------------------------------------------

    def _ask(self, prompt: str, system: str, job: str = "daily", usage: dict[str, Any] | None = None) -> str:
        reply = self._distiller._complete(prompt, job, None, system=system, max_tokens=6000, task="check")
        if usage is not None:
            usage["input_tokens"] += int(reply.get("input_tokens") or 0)
            usage["output_tokens"] += int(reply.get("output_tokens") or 0)
            usage["model"] = reply.get("model", "")
        return reply["text"]

    def _probe_targets(self) -> list[tuple[int, str, int]]:
        """(memory asked about, question, memory that now holds it): a folded memory counts as found through the one it was folded into."""
        with self._store.reading() as db:
            rows = db.execute(
                """
                SELECT p.memory_id, p.question, m.status, m.folded_into FROM probe_questions p
                JOIN memories m ON m.id = p.memory_id WHERE m.status IN ('active', 'folded') ORDER BY p.memory_id
                """
            ).fetchall()
        return [(row[0], row[1], row[3] if row[2] == "folded" and row[3] else row[0]) for row in rows]

    def make_probes(self, wanted: int = PROBES_WANTED) -> int:
        """Write test questions for randomly chosen memories, until there are enough."""
        have = len(self._probe_targets())
        if have >= PROBES_MIN or not self._distiller._models.resolve("daily"):
            return 0
        with self._store.reading() as db:
            pool = [tuple(row) for row in db.execute(
                """
                SELECT id, statement FROM memories WHERE status = 'active' AND kind != 'experience' AND LENGTH(statement) >= 25
                AND id NOT IN (SELECT memory_id FROM probe_questions)
                """
            )]
        chosen = sorted(random.Random(self._store._clock()).sample(pool, min(len(pool), wanted - have)))  # which: random; asked in order
        made = 0
        for start in range(0, len(chosen), 20):
            batch = chosen[start : start + 20]
            text = self._ask("\n".join(f"{n}. {statement}" for n, (_, statement) in enumerate(batch, start=1)), PROBE_SYSTEM)
            questions = _json_list(text, "questions")
            rows = [(memory_id, questions[n]["q"].strip()[:300], self._store._clock())
                    for n, (memory_id, _) in enumerate(batch, start=1)
                    if isinstance(questions.get(n, {}).get("q"), str) and questions[n]["q"].strip()]
            with self._store._tx() as db:
                db.executemany("INSERT OR IGNORE INTO probe_questions(memory_id, question, created_at) VALUES(?,?,?)", rows)
            made += len(rows)
        return made

    def _probe_recall(self) -> dict[str, Any] | None:
        targets = self._probe_targets()
        if not targets:
            return None
        hits = {"words": 0, "both": 0}
        started = time.monotonic()
        for _, question, holder in targets:
            for name, by_meaning in (("words", False), ("both", True)):
                found = self._recall.recall(question, limit=10, lend=False, by_meaning=by_meaning)["memories"]
                if any(memory["id"] == holder for memory in found):
                    hits[name] += 1
        return {
            "questions": len(targets),
            "words": round(100 * hits["words"] / len(targets)),
            "both": round(100 * hits["both"] / len(targets)),
            "meaning_on": bool(self._vectors is not None and self._vectors.ready()),
            "ms_per_question": round(1000 * (time.monotonic() - started) / (2 * len(targets))),
        }

    # ---- the checkup --------------------------------------------------------------------

    def checkup(self, trigger: str = "manual") -> dict[str, Any]:
        with self._store._tx() as db:
            run_id = db.execute("INSERT INTO doctor_runs(trigger, started_at) VALUES(?,?)", (trigger, self._store._clock())).lastrowid
        checks: list[dict[str, Any]] = []

        def add(key: str, status: str, label: str, detail: str = "", examples: list[int] | None = None) -> None:
            checks.append({"key": key, "status": status, "label": label, "detail": detail, "examples": examples or []})

        try:
            self.make_probes()
        except ModelError as error:
            add("probes", "warn", "没能写出召回抽测题", f"模型出错:{error.reason}")
        now = self._store._clock()
        with self._store.reading() as db:
            active = db.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()[0]
            broken = [row[0] for row in db.execute(
                """
                SELECT DISTINCT e.memory_id FROM memory_evidence e JOIN memories m ON m.id = e.memory_id
                LEFT JOIN segments s ON s.id = e.segment_id
                WHERE m.status = 'active' AND (s.id IS NULL OR instr(s.text, e.quote) = 0)
                """
            )]
            bare = [row[0] for row in db.execute(
                "SELECT m.id FROM memories m WHERE m.status = 'active' AND NOT EXISTS (SELECT 1 FROM memory_evidence e WHERE e.memory_id = m.id)"
            )]
            statements = db.execute("SELECT id, kind, statement FROM memories WHERE status = 'active'").fetchall()
            quoted = {row[0] for row in db.execute(
                f"SELECT DISTINCT e.memory_id FROM memory_evidence e JOIN segments s ON s.id = e.segment_id WHERE {USER_VOICE_SQL}"
            )}
            pending = db.execute(
                """
                SELECT COUNT(*), MIN(s.received_at) FROM segments s
                LEFT JOIN distill_progress p ON p.agent_id = s.agent_id AND p.session_id = s.session_id
                WHERE s.imported = 0 AND s.id > COALESCE(p.last_segment_id, 0)
                """
            ).fetchone()
            last_daily = db.execute("SELECT status, error_reason, started_at FROM distill_runs WHERE kind = 'daily' ORDER BY id DESC LIMIT 1").fetchone()
            devices = db.execute("SELECT name, last_seen_at, client_version FROM devices WHERE revoked_at IS NULL").fetchall()
            waiting_pairs = db.execute("SELECT COUNT(*) FROM review_pairs WHERE verdict = ''").fetchone()[0]
            upgradable = db.execute(
                """
                SELECT COUNT(*) FROM memories m WHERE m.status = 'active' AND m.kind != 'experience'
                AND (SELECT COUNT(*) FROM memory_loans l WHERE l.memory_id = m.id AND l.outcome = 'useful') >= 2
                AND NOT EXISTS (SELECT 1 FROM memory_links k WHERE k.relation = 'derived_from' AND k.to_id = m.id)
                """
            ).fetchone()[0]
            borrowed = db.execute("SELECT COUNT(DISTINCT memory_id) FROM memory_loans").fetchone()[0]
            boards = [row[0] for row in db.execute("SELECT DISTINCT project FROM whiteboard_records")] if self._whiteboard is not None else []
        # Every memory can be traced to its words.
        if broken:
            add("evidence", "bad", f"{len(broken)} 条记忆的原话对不上存着的对话了", "原话是入库时逐字核对过的,对不上说明对话被改动或删掉了", broken[:5])
        else:
            add("evidence", "ok", f"{active} 条有效记忆的原话都能逐字找回")
        if bare:
            add("bare", "warn", f"{len(bare)} 条记忆没有任何原话", "", bare[:5])
        relayed = sum(1 for row in statements if speaks_for_user(row["kind"], row["statement"]) and row["id"] not in quoted)
        share = round(100 * relayed / active) if active else 0
        add("relayed", "warn" if share > 25 else "ok", f"{share}% 是助手转述你的意思(已标注,召回时会提醒)" if relayed else "说你意思的记忆都有你的原话")
        # Recall by meaning.
        vectors = self._vectors.status() if self._vectors is not None else None
        if vectors is None or not vectors["enabled"]:
            add("vectors", "warn", "按意思召回没有打开", "在「模型」页打开后,换个说法也能找到记忆")
        elif vectors["phase"] == "error":
            add("vectors", "bad", "按意思召回出错了", vectors["error"])
        elif vectors["active"] and vectors["indexed"] < 0.95 * vectors["active"] and vectors["phase"] != "indexing":
            add("vectors", "warn", f"按意思召回只覆盖了 {vectors['indexed']}/{vectors['active']} 条")
        else:
            add("vectors", "ok", f"按意思召回覆盖 {vectors['indexed']}/{vectors['active']} 条")
        # Recall measured.
        probe = self._probe_recall()
        if probe:
            status = "ok" if probe["both"] >= 75 else ("warn" if probe["both"] >= 50 else "bad")
            add("recall", status, f"召回抽测 {probe['questions']} 题:前 10 条里找到 {probe['both']}%" + ("" if probe["meaning_on"] else "(只按字面)"),
                f"只按字面 {probe['words']}% · 每题约 {probe['ms_per_question']} 毫秒")
        # Distilling.
        if not self._distiller._models.resolve("daily"):
            add("distill", "bad", "日常提炼没有模型,新的对话不会变成记忆", "在「模型」页给「日常提炼」选一个")
        elif last_daily is not None and last_daily["status"] == "stopped":
            add("distill", "bad", f"上一次日常提炼停下了({last_daily['error_reason'] or '出错'})", "进度没丢,每 30 分钟自动再试")
        elif pending[0] and pending[1] and now - pending[1] > 2 * 86400:
            add("distill", "warn", f"有 {pending[0]} 段对话等了两天以上还没提炼")
        else:
            add("distill", "ok", "日常提炼正常" + (f",待提炼 {pending[0]} 段" if pending[0] else ""))
        # Computers.
        silent = [row["name"] for row in devices if not row["last_seen_at"] or now - row["last_seen_at"] > OFFLINE_HOURS * 3600]
        from . import client_package

        current = client_package.client_version()
        behind = [row["name"] for row in devices if current and row["client_version"] and row["client_version"] != current and row["name"] not in silent]
        if silent:
            add("clients", "warn", f"{len(silent)} 台电脑超过一天没联系:{'、'.join(silent[:3])}", "那边的对话会攒着,联上后补传")
        elif behind:
            add("clients", "warn", f"{'、'.join(behind[:3])} 的客户端还没更新到 {current}", "通常一小时内会自己更新")
        else:
            add("clients", "ok", f"{len(devices)} 台电脑最近一天都联系过,客户端是最新的")
        # Whether anything was missed: each computer compares its agents' own files with what is stored here.
        looked = [(row["name"], agent["name"], agent["verified"]) for row in self._store.list_devices() if not row["revoked"]
                  for agent in row["agents"] if agent["verified"] and not agent["disconnected"]]
        short = [f"{device}·{name}" for device, name, seen in looked if seen.get("missing")]
        if short:
            add("missed", "warn", f"{len(short)} 个 agent 的会话文件里有没收到的话:{'、'.join(short[:3])}", "数目不寻常,没有自动补收;在那台电脑上运行 tl.py verify --repair")
        elif looked:
            turns = sum(seen.get("segments", 0) for _, _, seen in looked)
            mended = sum(seen.get("repaired_ever", 0) for _, _, seen in looked)
            add("missed", "ok", f"和源文件核对过 {turns} 句,没有漏收的" + (f"(补收过 {mended} 句)" if mended else ""))
        # Prompt hooks: an agent saying it has one is its word; whether it asks is seen here.
        quiet = [f"{row['name']}·{agent['name']}" for row in self._store.list_devices() if not row["revoked"]
                 for agent in row["agents"] if agent["preflight"]["quiet"]]
        if quiet:
            add("preflight", "warn", f"{len(quiet)} 个 agent 自报支持提问前预检,最近的提问却没触发:{'、'.join(quiet[:3])}",
                "让它照 install.md 第 6 步查自己的钩子")
        # Work in flight and things waiting.
        if self._whiteboard is not None:
            stale = sum(1 for project in boards for task in self._whiteboard.tasks(project, include_done=False) if task["stale"])
            if stale:
                add("whiteboard", "warn", f"白板上 {stale} 件事两周没动静了", "可能做完了没写「完成」,也可能搁下了")
        add("evolution", "ok", f"还有 {waiting_pairs} 对相近说法等每晚比对" if waiting_pairs else "相近说法都比对过了")
        add("lifecycle", "ok", f"{borrowed} 条记忆被 agent 借过;{upgradable} 条被评有用两次以上、还没归纳进经验")
        order = {"bad": 0, "warn": 1, "ok": 2}
        checks.sort(key=lambda item: order[item["status"]])
        report = {"at": now, "checks": checks, "worst": checks[0]["status"] if checks else "ok", "probe": probe}
        with self._store._tx() as db:
            db.execute("UPDATE doctor_runs SET finished_at = ?, report = ? WHERE id = ?", (self._store._clock(), json.dumps(report, ensure_ascii=False), run_id))
        return report

    # ---- memory on and off ------------------------------------------------------------------

    def compare(self, questions: int = COMPARE_DEFAULT) -> dict[str, Any]:
        usage = {"input_tokens": 0, "output_tokens": 0, "model": ""}
        with self._store._tx() as db:
            run_id = db.execute("INSERT INTO compare_runs(started_at, status) VALUES(?, 'running')", (self._store._clock(),)).lastrowid
        self._live["compare"] = {"run": run_id, "step": "questions", "done": 0, "total": questions}
        status, error, rows = "done", "", []
        try:
            self.make_probes(max(PROBES_WANTED, questions))
            targets = self._probe_targets()
            random.Random(run_id).shuffle(targets)
            targets = targets[:questions]
            with self._store.reading() as db:
                facts = {row[0]: row[1] for row in db.execute(
                    f"SELECT id, statement FROM memories WHERE id IN ({','.join('?' * len(targets))})", [t[2] for t in targets]
                )} if targets else {}
            rows = [{"memory_id": holder, "question": question, "fact": facts.get(holder, "")} for _, question, holder in targets]
            self._live["compare"]["total"] = len(rows)
            for start in range(0, len(rows), BATCH):
                batch = rows[start : start + BATCH]
                self._live["compare"].update(step="answering", done=start)
                off = _json_list(self._ask("\n".join(f"{n}. {row['question']}" for n, row in enumerate(batch, 1)), ANSWER_OFF_SYSTEM, usage=usage), "answers")
                blocks = []
                for n, row in enumerate(batch, 1):
                    found = self._recall.recall(row["question"], limit=5, lend=False)["memories"]
                    row["found"] = any(memory["id"] == row["memory_id"] for memory in found)
                    blocks.append(f"{n}. {row['question']}\n" + "\n".join(f"   记忆:{memory['statement']}" for memory in found))
                on = _json_list(self._ask("\n\n".join(blocks), ANSWER_ON_SYSTEM, usage=usage), "answers")
                for n, row in enumerate(batch, 1):
                    row["off"] = str(off.get(n, {}).get("a", ""))[:300]
                    row["on"] = str(on.get(n, {}).get("a", ""))[:300]
                judge_job = "reflect" if self._distiller._models.resolve("reflect") else "daily"
                for side in ("off", "on"):
                    verdicts = _json_list(self._ask("\n\n".join(
                        f"{n}. 问题:{row['question']}\n   参考事实:{row['fact']}\n   回答:{row[side] or '(没有回答)'}" for n, row in enumerate(batch, 1)
                    ), JUDGE_SYSTEM, judge_job, usage), "verdicts")
                    for n, row in enumerate(batch, 1):
                        verdict = verdicts.get(n, {}).get("v")
                        row[f"{side}_verdict"] = verdict if verdict in ("right", "wrong", "unknown") else "unclear"
            self._live["compare"].update(step="done", done=len(rows))
        except ModelError as failure:
            status, error = "stopped", f"{failure.reason}: {str(failure)[:200]}"
        judged = [row for row in rows if "on_verdict" in row]
        result = {
            "questions": len(judged),
            "off_right": sum(1 for row in judged if row["off_verdict"] == "right"),
            "on_right": sum(1 for row in judged if row["on_verdict"] == "right"),
            "found": sum(1 for row in judged if row.get("found")),
        }
        with self._store._tx() as db:
            db.execute(
                """
                UPDATE compare_runs SET finished_at=?, status=?, questions=?, off_right=?, on_right=?, found=?, details=?,
                       model=?, input_tokens=?, output_tokens=?, error=? WHERE id=?
                """,
                (self._store._clock(), status, result["questions"], result["off_right"], result["on_right"], result["found"],
                 json.dumps(judged, ensure_ascii=False), usage["model"], usage["input_tokens"], usage["output_tokens"], error, run_id),
            )
        self._live.pop("compare", None)
        return result

    # ---- what the admin page shows ------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._store.reading() as db:
            last = db.execute("SELECT * FROM doctor_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
            compare = db.execute("SELECT * FROM compare_runs ORDER BY id DESC LIMIT 1").fetchone()
            probes = db.execute("SELECT COUNT(*) FROM probe_questions").fetchone()[0]
        out: dict[str, Any] = {
            "checkup": json.loads(last["report"]) | {"trigger": last["trigger"]} if last else None,
            "checkup_running": self.running("checkup"),
            "compare": None,
            "compare_running": self.running("compare"),
            "compare_live": self._live.get("compare"),
            "probes": probes,
            "has_model": bool(self._distiller._models.resolve("daily")),
        }
        if compare is not None:
            out["compare"] = {key: compare[key] for key in compare.keys() if key != "details"} | {"details": json.loads(compare["details"] or "[]")}
        return out
