"""How agents reach their memories through the client on their own computer.

Two doors, both thin: everything is asked of the server; nothing is kept here.

  mcp        a stdio MCP server an agent registers like any other tool. It adds
             the device token and forwards. If the server cannot be reached,
             the tool says so at once instead of hanging the agent.
  preflight  a command a host can run before each prompt (for example a
             "user prompt submit" hook). It prints related memories, or
             nothing. Any failure prints nothing and exits 0: it must never
             block or clutter a prompt.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, BinaryIO

from . import CLIENT_VERSION
from .api import Api, ServerRefused, ServerUnreachable
from .state import State

MCP_TIMEOUT = 8.0
ANSWER_TIMEOUT = 120.0  # an answer waits for the server's model
CATALOG_TIMEOUT = 3.0
PREFLIGHT_TIMEOUT = 4.0  # hooks allow more (WorkBuddy 8s, Claude Code 60s); a busy server can need 2-3s
MAX_STDIN_BYTES = 2 * 1024 * 1024
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
KIND_LABELS = {"decision": "决定", "preference": "偏好", "correction": "纠正", "fact": "事实", "lesson": "教训", "experience": "经验"}
ROLE_LABELS = {"user": "用户", "assistant": "助手"}

TOOLS = [
    {
        "name": "time_library_recall",
        "description": (
            "Search the user's long-term memory (Time Library, in Chinese 时间图书馆 or 忆凡尘). It holds decisions, preferences, corrections, "
            "facts and lessons distilled from the user's past conversations with all of their AI tools on all "
            "of their computers, each with the user's or assistant's original words as evidence. Use it when "
            "the task may depend on earlier context: why something was decided, how the user wants things done, "
            "what went wrong before. Ask with the user's own question, as they put it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": (
                    "The question as the user put it: one sentence, in the language of the conversation. Do not string "
                    "keywords together or add words of your own: every extra word pulls in other subjects and pushes "
                    "the answer out. To ask about something else, call again."
                )},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "description": "How many memories to return (default 5)."},
                "project": {"type": "string", "description": "Only this project's memories (its declared name). Leave out normally: the project you work in already counts for more, and others are not shut out."},
                "agent": {"type": "string", "description": "Only memories from this agent's conversations."},
                "computer": {"type": "string", "description": "Only memories from this computer."},
                "kind": {"type": "string", "enum": ["decision", "preference", "correction", "fact", "lesson", "experience"]},
                "since": {"type": "string", "description": "Only what was said from this day on, like 2026-11-01."},
                "until": {"type": "string", "description": "Only what was said up to this day."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "time_library_answer",
        "description": (
            "Ask the user's memory a question and get one short answer that rests only on what was said, "
            "with the memories it rests on and the parts memory doesn't say, or UNKNOWN when it says none of it. Use it "
            "when you need a fact you must not guess, such as what was decided, which version or address, "
            "what the user asked for; use time_library_recall instead to browse what is there. It costs one "
            "model call on the user's server and can take half a minute."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": (
                "One question about one thing, as the user put it, in the language of the conversation. "
                "Several things asked in one go are looked up together and crowd each other out: ask them one by one."
            )}},
            "required": ["question"],
        },
    },
    {
        "name": "time_library_continue",
        "description": (
            "Where the work in this folder's project was left: the last conversations (with any agent, on any "
            "computer), how the last one ended, the work in flight, what was decided lately. Use it first when the "
            "user opens a new window with little more than 继续 / 接着做 / 下一步 / 做到哪了 (continue, what's next), "
            "before asking them to explain again. Not needed when the conversation already says where it stands."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "time_library_search",
        "description": (
            "Search the original words of all past conversations (every agent, every computer), not the memories "
            "drawn from them. Most of what was said never became a memory. Use it when time_library_recall has "
            "nothing, or when you need the exact words: a path, a number, a name, an error message, what was said "
            "on a certain day. Give the words themselves. Returns short excerpts, each with its turn number; "
            "time_library_source with that turn_id shows the conversation around it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The words to look for, as they were probably said."},
                "who": {"type": "string", "enum": ["user", "assistant"], "description": "Only what the user said, or only what assistants said."},
                "since": {"type": "string", "description": "From this day on, like 2026-11-01."},
                "until": {"type": "string", "description": "Up to this day."},
                "agent": {"type": "string", "description": "Only this agent's conversations, such as Codex."},
                "computer": {"type": "string", "description": "Only this computer's conversations."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "description": "How many excerpts (default 8)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "time_library_source",
        "description": (
            "Show the original conversation around a memory's evidence, or around a turn found by "
            "time_library_search: that turn and the ones just before and after it. Use it when a recalled memory "
            "or an excerpt matters and you need its full context. Give one of the two numbers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "integer", "description": "The memory number from time_library_recall."},
                "turn_id": {"type": "integer", "description": "The turn number from time_library_search."},
            },
        },
    },
    {
        "name": "time_library_declare",
        "description": (
            "Say which project the folder you are working in belongs to (once per folder; later windows in this "
            "folder or below it count as the same project). Time Library then lists this project first when a "
            "window opens here. Use the project's own name; ask the user if it is not clear. Never guess."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "The project's name."},
                "series": {"type": "string", "description": "Optional: the larger body of work it is part of."},
            },
            "required": ["project"],
        },
    },
    {
        "name": "time_library_catalog",
        "description": (
            "The full catalog of the user's memories: headlines and memory numbers, the current project first, "
            "then preferences and the other projects. A list, not the memories' text."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "time_library_whiteboard",
        "description": (
            "The project's whiteboard: the work in flight, written by the agents doing it, so the next window "
            "can pick up without the user relaying anything. Write conclusions only, never discussion: "
            "claim when you take on a task (new: give task; taking over a handoff: give its task_id), "
            "progress at a milestone, handoff when you stop and someone else should continue (say next_owner), "
            "blocked when it waits on something, done when finished. One sentence each. list shows the board "
            "(or one task's thread with task_id). Needs a declared project for this folder (time_library_declare). "
            'Examples: {"action":"claim","task":"白板功能施工","role":"施工"} · '
            '{"action":"handoff","task_id":"WB-12","summary":"施工完成,请二签复核","next_owner":"二签"} · '
            '{"action":"list"}'
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["claim", "progress", "handoff", "blocked", "done", "list"]},
                "task": {"type": "string", "description": "claim of a new task only: its short name (up to 60 characters)."},
                "task_id": {"type": "string", "description": "An existing task, as the board shows it, e.g. WB-12. Required for progress, handoff, blocked, done."},
                "summary": {"type": "string", "description": "One sentence: the conclusion reached (up to 200 characters). Required except for claim."},
                "role": {"type": "string", "description": "Your part in this work, e.g. 施工, 一签, 二签, 出稿 (up to 20 characters)."},
                "next_owner": {"type": "string", "description": "handoff only (required there): the role or agent that should continue."},
                "memory_ids": {"type": "array", "items": {"type": "integer"}, "description": "Optional: memory numbers this rests on, as recall shows them."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "time_library_return",
        "description": (
            "After you have finished the work, return a recalled memory with a verdict, so Time Library learns "
            "which memories help. useful = it changed what you did, for the better; useless = it did not matter "
            "here; misleading = it was wrong or out of date for this situation. Judge only from what actually "
            "happened in this conversation; if you cannot tell, do not return it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "integer", "description": "The memory number."},
                "outcome": {"type": "string", "enum": ["useful", "useless", "misleading"]},
                "note": {"type": "string", "description": "One short sentence: how it helped, or what was wrong."},
            },
            "required": ["memory_id", "outcome"],
        },
    },
]
OUTCOME_LABELS = {"useful": "有用", "useless": "没用上", "misleading": "误导"}

INSTRUCTIONS = (
    "Time Library is the user's long-term memory across their AI tools and computers. Its Chinese names are "
    "时间图书馆 and 忆凡尘: all three are this one system, so when the user says any of them they mean these tools. "
    "Call time_library_recall when earlier context could change what you do, asking with the user's own question "
    "rather than keywords of your own; treat what it returns as background that the current conversation can override. "
    "When a new window opens with little more than 继续 / 下一步 / continue, call time_library_continue first."
)


def _date(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return ""


def format_memories(memories: list[dict[str, Any]], *, with_hint: bool = True) -> str:
    lines = []
    for number, memory in enumerate(memories, start=1):
        label = KIND_LABELS.get(memory["kind"], memory["kind"])
        if memory["kind"] == "experience":
            lines.append(f"{number}. [{label}] {memory.get('title') or ''}:{memory['statement']}")
            if memory.get("when"):
                lines.append(f"   什么时候想起它:{memory['when']}")
            lines.append(f"   归纳自 {memory.get('sources') or 0} 条记忆(用 time_library_source 看它们的原话)")
        else:
            lines.append(f"{number}. [{label}] {memory['statement']}")
        if memory.get("note"):
            lines.append(f"   注意:{memory['note']},别当成用户亲口说的。")
        for item in memory.get("evidence", [])[:2]:
            who = "用户转贴" if item.get("voice") == "relayed" else ROLE_LABELS.get(item.get("role"), "")
            when = _date(item.get("ts"))
            meta = "、".join(part for part in (who, when) if part)
            lines.append(f"   原话({meta}):「{item['quote']}」" if meta else f"   原话:「{item['quote']}」")
        verdicts = memory.get("returns") or {}
        judged = [f"{OUTCOME_LABELS[key]} {verdicts[key]}" for key in ("useful", "useless", "misleading") if verdicts.get(key)]
        if judged:
            lines.append(f"   以前借用后的评价:{' · '.join(judged)}")
        surface = f"({memory['surface']})" if memory.get("surface") else ""
        project = f" · 项目「{memory['project']}」" if memory.get("project") else ""
        lines.append(f"   来源:{memory['device']} · {memory['agent']}{surface}{project} · 记忆编号 {memory['id']}")
    if with_hint:
        lines.append("")
        lines.append("要看某条记忆前后的完整对话,用 time_library_source 并给出记忆编号。")
    return "\n".join(lines)


def format_answer(result: dict[str, Any]) -> str:
    if result.get("verdict") != "answered":
        considered = result.get("considered") or 0
        tail = f"(看过 {considered} 条相关记忆)" if considered else ""
        return f"UNKNOWN:{result.get('unknown_reason') or '记忆里没有说到这件事。'}{tail}\n记忆没说的,别猜;需要的话直接问用户。"
    lines = [f"回答:{result['answer']}"]
    if result.get("missing"):
        lines.append(f"记忆没说到的(别猜,需要就问用户):{result['missing']}")
    lines += ["", "依据(只凭这些记忆作答):"]
    lines.append(format_memories(result.get("memories") or [], with_hint=False))
    lines.append("")
    lines.append("这是按记忆整理的回答,不是原话;要核对就用 time_library_source 看依据的原话。")
    return "\n".join(lines)


def format_task(task: dict[str, Any], thread: bool = False) -> str:
    latest = task["latest"]
    who = "/".join(part for part in (latest.get("role"), latest.get("agent")) if part)
    line = f"{task['id']} {task['title']} · {who} → {task['state']}"
    if task.get("kind") == "handoff" and latest.get("next_owner"):
        line += f",交接给 {latest['next_owner']}"
    if latest.get("summary"):
        line += f":{latest['summary']}"
    if task.get("stale"):
        line += "(两周没动静了)"
    if not thread:
        return line
    lines = [line, "记录:"]
    for record in task.get("records", []):
        who = "/".join(part for part in (record.get("role"), record.get("agent")) if part)
        lines.append(f"  {_date(record['created_at'])} {who} {record['state']}" + (f":{record['summary']}" if record.get("summary") else "")
                     + (f"(交接给 {record['next_owner']})" if record.get("next_owner") else "")
                     + (f" 依据记忆 {', '.join(map(str, record['memory_ids']))}" if record.get("memory_ids") else ""))
    return "\n".join(lines)


def format_source(source: dict[str, Any]) -> str:
    lines = [f"记忆编号 {source['id']}:{source['statement']}" + {"expired": "(已失效)", "superseded": "(已被取代)"}.get(source.get("status"), "")]
    if source.get("folded_into"):
        lines.append(f"这条是记忆 {source['folded_into']} 的重复说法,已合并进去;以那一条为准。")
    if source.get("replaced_by"):
        replaced = source["replaced_by"]
        lines.append(f"这条已被记忆 {replaced['id']} 取代" + (f"({replaced['reason']})" if replaced.get("reason") else "") + ";以那一条为准。")
    if source.get("derived_from"):
        lines.append("这是一条经验,归纳自记忆 " + "、".join(f"#{mid}" for mid in source["derived_from"]) + ";下面是它们的原话。")
    for number, item in enumerate(source.get("evidence", []), start=1):
        lines.append("")
        lines.append(f"—— 证据 {number}:「{item['quote']}」")
        for turn in item.get("before", []):
            lines.append(f"{ROLE_LABELS.get(turn['role'], turn['role'])}:{turn['text']}")
        turn = item["turn"]
        when = _date(turn.get("ts"))
        lines.append(f"▶ {ROLE_LABELS.get(turn['role'], turn['role'])}{'(' + when + ')' if when else ''}:{turn['text']}")
        for turn in item.get("after", []):
            lines.append(f"{ROLE_LABELS.get(turn['role'], turn['role'])}:{turn['text']}")
    if not source.get("evidence"):
        lines.append("这条记忆的原话已经不在服务端了。")
    return "\n".join(lines)


VOICE_LABELS = {"user": "用户", "relayed": "用户转贴", "assistant": "助手"}


def format_search(found: dict[str, Any]) -> str:
    hits = found.get("hits") or []
    index = found.get("index") or {}
    building = "" if index.get("ready", True) else (
        f"(原话索引还在建,已建 {index.get('indexed', 0)}/{index.get('total', 0)} 句,从最近的开始;没找到不代表没说过。)")
    if not hits:
        return "原话里没有找到。" + building
    lines = [f"原话里找到 {len(hits)} 处(摘录;要看前后文用 time_library_source 加 turn_id):"]
    for number, hit in enumerate(hits, start=1):
        agent = hit["agent"] + (f"({hit['surface']})" if hit.get("surface") else "")
        where = " · ".join(part for part in (hit["device"], agent, hit.get("project") or "") if part)
        lines.append("")
        lines.append(f"{number}. {VOICE_LABELS.get(hit['voice'], hit['voice'])}、{_date(hit['ts']) or '日期不详'}:「{hit['text']}」")
        same = f" · 另有 {hit['same']} 处相同" if hit.get("same") else ""
        lines.append(f"   来源:{where}{same} · 编号 turn_id={hit['segment']}")
    if building:
        lines += ["", building]
    return "\n".join(lines)


def format_around(found: dict[str, Any]) -> str:
    agent = found["agent"] + (f"({found['surface']})" if found.get("surface") else "")
    lines = [f"原话 turn_id={found['segment']} 的前后文 · {found['device']} · {agent}" + (f" · {found['folder']}" if found.get("folder") else "")]
    for turn in found.get("before", []):
        lines.append(f"{ROLE_LABELS.get(turn['role'], turn['role'])}:{turn['text']}")
    turn = found["turn"]
    when = _date(turn.get("ts"))
    lines.append(f"▶ {ROLE_LABELS.get(turn['role'], turn['role'])}{'(' + when + ')' if when else ''}:{turn['text']}")
    for turn in found.get("after", []):
        lines.append(f"{ROLE_LABELS.get(turn['role'], turn['role'])}:{turn['text']}")
    return "\n".join(lines)


def _number(value: Any) -> int | None:
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _api(state: State, timeout: float) -> Api | None:
    if not state.paired:
        return None
    return Api(state.config["server_url"], state.config["device_token"], timeout=timeout)


# ---- MCP over stdio -----------------------------------------------------------


class McpServer:
    def __init__(self, state: State, agent: str = "") -> None:
        self.state = state
        self.agent = agent

    def _text(self, text: str, error: bool = False) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": text}], "isError": error}

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        api = _api(State(self.state.home), ANSWER_TIMEOUT if name == "time_library_answer" else MCP_TIMEOUT)
        if api is None:
            return self._text("这台电脑还没接入忆凡尘服务端,所以查不到记忆。", error=True)
        try:
            if name == "time_library_recall":
                query = arguments.get("query")
                if not isinstance(query, str) or not query.strip():
                    return self._text("query 不能为空。", error=True)
                limit = arguments.get("limit", 5)
                only = {key: arguments[key] for key in ("project", "agent", "computer", "kind", "since", "until")
                        if isinstance(arguments.get(key), str) and arguments[key].strip()}
                found = api.recall_result(query, limit=limit if isinstance(limit, int) else 5, agent=self.agent, folder=os.getcwd(), only=only)
                memories = found["memories"]
                if not memories:
                    without = found.get("without_conditions")
                    return self._text("没有找到相关的记忆。" if without is None else
                                      f"按这些条件没有找到({'、'.join(f'{key}={value}' for key, value in only.items())});去掉条件能找到 {without} 条相关的。")
                return self._text(f"找到 {len(memories)} 条相关记忆(按相关度排序):\n\n" + format_memories(memories))
            if name == "time_library_answer":
                question = arguments.get("question")
                if not isinstance(question, str) or not question.strip():
                    return self._text("question 不能为空。", error=True)
                return self._text(format_answer(api.answer(question, agent=self.agent, folder=os.getcwd())))
            if name == "time_library_declare":
                project = arguments.get("project")
                if not isinstance(project, str) or not project.strip():
                    return self._text("project 不能为空。", error=True)
                series = arguments.get("series") if isinstance(arguments.get("series"), str) else ""
                done = api.declare(os.getcwd(), project.strip(), series.strip(), agent=self.agent)
                return self._text(
                    f"已声明:文件夹 {done['folder']} 属于项目「{done['project']}」"
                    + (f"(属于 {done['series']})" if done.get("series") else "")
                    + f"。这台电脑上已有 {done['sessions']} 个会话在这个文件夹里。"
                )
            if name == "time_library_catalog":
                return self._text(api.catalog(os.getcwd(), full=True)["text"])
            if name == "time_library_whiteboard":
                return self._text(self._whiteboard(api, arguments))
            if name == "time_library_return":
                memory_id = arguments.get("memory_id")
                if isinstance(memory_id, str) and memory_id.strip().isdigit():
                    memory_id = int(memory_id.strip())
                if isinstance(memory_id, bool) or not isinstance(memory_id, int):
                    return self._text("memory_id 必须是记忆编号(整数)。", error=True)
                outcome = arguments.get("outcome")
                if outcome not in OUTCOME_LABELS:
                    return self._text("outcome 只能是 useful、useless 或 misleading。", error=True)
                note = arguments.get("note") if isinstance(arguments.get("note"), str) else ""
                api.give_back([{"memory_id": memory_id, "outcome": outcome, "note": note}], agent=self.agent)
                return self._text(f"已记下:记忆 {memory_id} {OUTCOME_LABELS[outcome]}。")
            if name == "time_library_continue":
                pack = api.continue_here(agent=self.agent, folder=os.getcwd())
                return self._text(pack["text"] if pack else "这里还没有可以接着做的对话记录。")
            if name == "time_library_search":
                query = arguments.get("query")
                if not isinstance(query, str) or not query.strip():
                    return self._text("query 不能为空。", error=True)
                body = {key: arguments[key] for key in ("query", "who", "since", "until", "agent", "computer", "limit") if arguments.get(key)}
                return self._text(format_search(api.search({**body, "asking": self.agent, "folder": os.getcwd()})))
            if name == "time_library_source":
                turn_id, memory_id = _number(arguments.get("turn_id")), _number(arguments.get("memory_id"))
                if turn_id is not None:
                    return self._text(format_around(api.around(turn_id)))
                if memory_id is None:
                    return self._text("memory_id 必须是记忆编号(整数),或者给 turn_id(time_library_search 结果里的编号)。", error=True)
                return self._text(format_source(api.memory_source(memory_id)))
            return self._text(f"没有这个工具:{name}", error=True)
        except ServerUnreachable:
            return self._text("忆凡尘服务端现在连不上,这次没有查到记忆。可以先不依赖记忆继续。", error=True)
        except ServerRefused as refusal:
            if name == "time_library_whiteboard" and refusal.message:
                return self._text(refusal.message, error=True)  # it says what was wrong and shows a call that works
            if refusal.code in ("model_not_configured", "model_failed") and refusal.message:
                return self._text(refusal.message, error=True)
            if refusal.code == "memory_not_found":
                return self._text("没有这个编号的记忆(可能已经被清除)。", error=True)
            if refusal.status == 401:
                return self._text("服务端不再接受这台电脑的令牌(已被吊销),需要重新接入。", error=True)
            return self._text(f"服务端拒绝了这次查询:{refusal.code}", error=True)

    def _whiteboard(self, api: Any, arguments: dict[str, Any]) -> str:
        action = arguments.get("action")
        if action == "list":
            task_id = arguments.get("task_id") if isinstance(arguments.get("task_id"), str) else ""
            found = api.whiteboard_list(os.getcwd(), task_id)
            if found.get("task"):
                return format_task(found["task"], thread=True)
            if not found.get("project"):
                return found.get("hint") or "这个文件夹还没声明项目。"
            tasks = found.get("tasks") or []
            if not tasks:
                return f"项目「{found['project']['name']}」的白板上还没有任务。开工时用 claim 领一件。"
            return f"项目「{found['project']['name']}」的白板:\n" + "\n".join(format_task(task) for task in tasks)
        body = {key: arguments[key] for key in ("action", "task", "task_id", "summary", "role", "next_owner", "memory_ids") if key in arguments}
        body.update({"folder": os.getcwd(), "agent": self.agent})
        done = api.whiteboard_write(body)
        text = "已写上白板:" + format_task(done["task"])
        if done.get("warning"):
            text += "\n注意:" + done["warning"]
        return text

    def _startup_instructions(self) -> str:
        """The instructions plus the catalog for the folder this window works in (never fails)."""
        try:
            api = _api(State(self.state.home), CATALOG_TIMEOUT)
            if api is None:
                return INSTRUCTIONS
            text = api.catalog(os.getcwd())["text"]
        except Exception:  # noqa: BLE001 - the window opens without a catalog rather than not at all
            return INSTRUCTIONS
        return f"{INSTRUCTIONS}\n\n{text}"

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        method = message.get("method")
        has_id = "id" in message
        if not has_id:
            return None  # a notification: nothing to answer
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "initialize":
            asked = params.get("protocolVersion")
            reply["result"] = {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "time-library", "version": CLIENT_VERSION},
                "instructions": self._startup_instructions(),
            }
        elif method == "ping":
            reply["result"] = {}
        elif method == "tools/list":
            reply["result"] = {"tools": TOOLS}
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            reply["result"] = self._call_tool(name if isinstance(name, str) else "", arguments)
        else:
            reply["error"] = {"code": -32601, "message": f"method not found: {method}"}
        return reply

    def serve(self, reader: BinaryIO, writer: BinaryIO) -> None:
        for raw in reader:
            if not raw.strip():
                continue
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                replies = [{"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}]
            else:
                batch = message if isinstance(message, list) else [message]
                replies = [reply for reply in (self.handle(item) for item in batch) if reply is not None]
            for reply in replies:
                writer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
                writer.flush()


# ---- preflight -------------------------------------------------------------------


def prompt_from(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
    except ValueError:
        return text.strip()
    if isinstance(data, dict):
        for key in ("prompt", "user_prompt", "message", "input"):
            if isinstance(data.get(key), str):
                return data[key].strip()
        return ""
    return data.strip() if isinstance(data, str) else ""


HOOK_FIELDS = ("prompt", "output", "empty", "once_per", "cwd", "session")
SEEN_FILE = "preflight-seen.json"
SEEN_KEEP = 300


def check_hook(hook: Any) -> dict[str, Any]:
    """An agent's description of its prompt hook, checked. Raises ValueError saying what is wrong."""
    if not isinstance(hook, dict) or set(hook) - set(HOOK_FIELDS):
        raise ValueError(f"the hook description is an object with any of: {', '.join(HOOK_FIELDS)}")
    for field in ("prompt", "once_per", "cwd", "session"):
        value = hook.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise ValueError(f"hook.{field} must be a list of dotted paths into what the hook is given")
    if "output" in hook and not isinstance(hook["output"], (str, dict, list)):
        raise ValueError('hook.output is a template (text, or JSON) with "{text}" where the memories go')
    if "output" in hook and "{text}" not in json.dumps(hook["output"], ensure_ascii=False):
        raise ValueError('hook.output must contain "{text}" where the memories go')
    if "empty" in hook and not isinstance(hook["empty"], str):
        raise ValueError("hook.empty is the text to print when there is nothing to hand over (for example {})")
    return hook


def _fill(template: Any, text: str) -> Any:
    if isinstance(template, str):
        return text if template == "{text}" else template.replace("{text}", text)
    if isinstance(template, list):
        return [_fill(item, text) for item in template]
    if isinstance(template, dict):
        return {key: _fill(value, text) for key, value in template.items()}
    return template


def _hook_of(state: State, agent: str) -> tuple[dict[str, Any], Any]:
    """(the agent's hook description, its session format) as it reported them; empty when it did not."""
    entry = (state.config.get("agents") or {}).get(agent) or {} if state is not None else {}
    spec = None
    try:
        from .formats import spec_from_report

        spec = spec_from_report(entry["format"]) if entry.get("format") else None
    except (KeyError, ValueError):
        spec = None
    return (entry.get("hook") or {}), spec


def _seen_before(state: State, key: str) -> bool:
    """Whether this turn was already handed its memories (a hook that runs on every model call)."""
    path = state.home / SEEN_FILE
    try:
        seen = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(seen, list):
            seen = []
    except (OSError, ValueError):
        seen = []
    if key in seen:
        return True
    seen = (seen + [key])[-SEEN_KEEP:]
    try:
        path.write_text(json.dumps(seen), encoding="utf-8")
    except OSError:
        pass
    return False


def preflight(state: State, raw: bytes, agent: str = "") -> str:
    """Related memories for this prompt, in the form the agent's hook takes; its "nothing" when none or on any failure."""
    hook, spec = _hook_of(state, agent) if agent else ({}, None)
    empty = hook.get("empty", "")
    try:
        text = _preflight_text(state, raw, agent, hook, spec)
    except Exception:
        return empty
    if not text:
        return empty
    if "output" not in hook:
        return text
    filled = _fill(hook["output"], text)
    return filled if isinstance(filled, str) else json.dumps(filled, ensure_ascii=False)


def _folder(hook: dict[str, Any], data: Any) -> str:
    """Where the window works: as the hook says (its own field, or `cwd` as most say it), else where the hook runs."""
    if isinstance(data, dict):
        from .formats import _first

        said = _first(data, hook.get("cwd") or ["cwd"])
        if isinstance(said, str) and said.strip():
            return said.strip()
    try:
        return os.getcwd()
    except OSError:
        return ""


def _session(hook: dict[str, Any], data: Any) -> str:
    """Which window asks, as the hook says (its own field, or one of the usual names); '' when it does not."""
    if not isinstance(data, dict):
        return ""
    from .formats import _first

    said = _first(data, hook.get("session") or ["session_id", "sessionId", "conversation_id", "conversationId", "thread_id"])
    return said.strip() if isinstance(said, str) else ""


def _preflight_text(state: State, raw: bytes, agent: str, hook: dict[str, Any], spec) -> str:
    started = time.monotonic()
    try:
        data: Any = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        data = None
    if hook.get("prompt") and isinstance(data, dict):
        from .formats import _first

        found = _first(data, hook["prompt"])
        prompt = found.strip() if isinstance(found, str) else ""
    else:
        prompt = prompt_from(raw)
    if spec is not None and prompt:
        from .formats import strip_runtime

        prompt = strip_runtime(prompt, spec)  # the agent's own wrappers around what the user typed
    api = _api(state, PREFLIGHT_TIMEOUT)
    if not prompt or api is None:
        return ""
    if hook.get("once_per") and isinstance(data, dict):
        from .formats import _dig

        parts = [str(_dig(data, path)) for path in hook["once_per"]]
        key = hashlib.sha256("\n".join([agent, *parts, prompt]).encode("utf-8")).hexdigest()[:24]
        if _seen_before(state, key):
            return ""
    found = api.recall_result(prompt, limit=3, mode="preflight", agent=agent, folder=_folder(hook, data), session=_session(hook, data))
    memories = found["memories"]
    if time.monotonic() - started > PREFLIGHT_TIMEOUT * 2:
        return ""
    if found.get("continue"):  # the user only says "go on", in a new window: where it was left
        return f"<time-library-memory>\n{found['continue']['text']}\n</time-library-memory>"
    if not memories:
        return ""
    return (
        "<time-library-memory>\n"
        "忆凡尘里可能和这个问题有关的记忆(从过往对话提炼,附原话)。仅供参考,和当前情况不符时以当前为准:\n"
        + format_memories(memories, with_hint=False)
        + "\n用完后可以用 time_library_return 告诉忆凡尘哪条有用、哪条误导。"
        + "\n</time-library-memory>"
    )


def run_mcp(state: State, agent: str) -> int:
    McpServer(state, agent).serve(sys.stdin.buffer, sys.stdout.buffer)
    return 0


def run_preflight(state: State, agent: str) -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_STDIN_BYTES)
    except Exception:
        return 0
    text = preflight(state, raw, agent)
    if text:
        # UTF-8 bytes whatever the console says: a hook started on Windows without
        # PYTHONUTF8 would otherwise write GBK, which the agent reads as garbage.
        out = getattr(sys.stdout, "buffer", None)
        if out is not None:
            out.write((text + "\n").encode("utf-8"))
            out.flush()
        else:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
    return 0
