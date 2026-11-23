"""Answering a question only from the user's memory, or saying it doesn't know.

An agent can read recalled memories and answer for itself. This is for when it
wants one short answer it can rely on: the server's model is handed the memories
recall found, with their original words, and may answer only from them. Every
answer must name the memories it rests on, and the server checks that those are
memories it was actually given; an answer that names none, or names others, is
replaced by UNKNOWN. A question about several things gets the parts memory does
say, with the rest named as missing. When memory says none of it, the honest
answer is UNKNOWN, with what was missing.

Only the memories an answer rests on count as borrowed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .errors import ApiError
from .model_client import ModelError

UNKNOWN = "UNKNOWN"
EVIDENCE_MEMORIES = 8
QUOTES_PER_MEMORY = 3
MAX_ANSWER_CHARS = 1200
MAX_MISSING_CHARS = 300
ROLES = {"user": "用户", "assistant": "助手"}

SYSTEM = """你只依据给你的记忆作答。记忆是从用户过去和各个 AI 工具的对话里提炼的,每条附有当时的原话。
规则:
- 只用下面给出的记忆和原话,不用常识或外部知识补充。
- 问题问了好几件事时,记忆里有依据的那几件照答,没有依据的不要编,在 missing 里一句话说记忆没说到的是哪几件。缺一件不等于整个答不了。
- 一件都没有依据,answer 才写 UNKNOWN,并在 unknown_reason 里说缺的是什么。
- 问的事没有被明确说过,就答 UNKNOWN;不要拿相关但不同的事实顶替(别的端口、别的版本、别的人、别的建议)。
- 没有证据不等于没发生:问某件事有没有做、有没有发生,而记忆只说还没确认或没有回执,答 UNKNOWN,不要答"没有"。
- 关于用户本人的偏好、决定、事实,以用户原话为准。只有助手说法、没有用户原话的,可以用,但要在回答里说明"这是助手的说法"。
- 同一件事前后说法不同,用日期最新的,并提一句以前的说法。
- 每个不是 UNKNOWN 的回答,都要在 used 里列出它依据的记忆编号,只能是下面出现过的编号。
- 回答简短,用提问的语言。
只输出 JSON,不要别的文字:{"answer": "...", "used": [记忆编号], "missing": "", "unknown_reason": ""}"""


def _date(ts: Any) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return str(ts or "")[:10]


def evidence_text(memories: list[dict[str, Any]]) -> str:
    blocks = []
    for memory in memories:
        head = f"记忆 {memory['id']} [{memory['kind']}]"
        if memory.get("title"):
            head += f" {memory['title']}:"
        lines = [f"{head} {memory['statement']}"]
        if memory.get("note"):
            lines.append(f"  (注意:{memory['note']})")
        for item in (memory.get("evidence") or [])[:QUOTES_PER_MEMORY]:
            who = ROLES.get(item.get("role"), item.get("role") or "")
            lines.append(f"  原话({who}、{_date(item.get('ts'))}):「{item.get('quote', '')}」")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _parse(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _unknown(reason: str, memories: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    return {"answer": UNKNOWN, "verdict": "unknown", "unknown_reason": reason, "missing": "", "used": [], "memories": [],
            "considered": len(memories or []), **extra}


class Answerer:
    def __init__(self, recall, distiller) -> None:
        self._recall = recall
        self._distiller = distiller

    def job(self) -> str:
        """The model that answers: the deep-summary one if set, else the daily one."""
        models = self._distiller._models
        return "reflect" if models.resolve("reflect") else "daily"

    def answer(self, question: Any, *, device_id: int | None = None, agent: Any = None, lend: bool = True) -> dict[str, Any]:
        result = self._answer(question, device_id=device_id, agent=agent, lend=lend)
        if lend:
            self._recall.note_use(device_id, agent, "answer", result["verdict"] == "answered")
        return result

    def _answer(self, question: Any, *, device_id: int | None, agent: Any, lend: bool) -> dict[str, Any]:
        if not isinstance(question, str) or not question.strip():
            raise ApiError(400, "invalid_field", "question must be a non-empty string")
        question = question.strip()[:1000]
        job = self.job()
        if not self._distiller._models.resolve(job):
            raise ApiError(409, "model_not_configured",
                           "服务端还没配模型:在后台「模型」页给「深度归纳」或「日常提炼」选一个模型,才能按证据作答。")
        found = self._recall.recall(question, limit=EVIDENCE_MEMORIES, device_id=device_id, agent=agent, lend=False)["memories"]
        if not found:
            return _unknown("记忆里没有和这个问题相关的内容。")
        prompt = f"问题:{question}\n\n记忆:\n\n{evidence_text(found)}"
        try:
            reply = self._distiller._complete(prompt, job, None, system=SYSTEM, max_tokens=4000)
        except ModelError as error:
            raise ApiError(502, "model_failed", f"作答的模型这次没回上来({error.reason}),稍后再试。") from None
        parsed = _parse(reply.get("text") or "")
        model = reply.get("model", "")
        if not parsed:
            return _unknown("模型没有按要求给出回答。", found, model=model)
        answer = " ".join(str(parsed.get("answer") or "").split())[:MAX_ANSWER_CHARS]
        used = parsed.get("used") if isinstance(parsed.get("used"), list) else []
        used = [int(item) for item in used
                if (isinstance(item, int) and not isinstance(item, bool)) or (isinstance(item, str) and item.strip().isdigit())]
        given = {memory["id"]: memory for memory in found}
        if not answer or answer.upper() == UNKNOWN:
            reason = " ".join(str(parsed.get("unknown_reason") or "").split())[:300] or "记忆里没有说到这件事。"
            return _unknown(reason, found, model=model)
        if any(memory_id not in given for memory_id in used):
            return _unknown("回答引用了没交给它的记忆,作废。", found, model=model)
        if not used:
            return _unknown("回答没有说依据哪条记忆,作废。", found, model=model)
        used = list(dict.fromkeys(used))
        delivery_id = ""
        if lend:
            delivery_id = self._recall.lend(used, device_id=device_id, agent=agent, mode="answer", query=question)
        return {
            "answer": answer,
            "verdict": "answered",
            "unknown_reason": "",
            "missing": " ".join(str(parsed.get("missing") or "").split())[:MAX_MISSING_CHARS],
            "used": used,
            "memories": [given[memory_id] for memory_id in used],
            "considered": len(found),
            "model": model,
            "delivery_id": delivery_id,
        }
