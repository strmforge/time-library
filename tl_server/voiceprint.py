"""Telling the user's own words from what the user pasted in.

People often paste another agent's report into a conversation ("here's what the
other window found"). In the transcript that is a user turn, but the words are
the other agent's: a preference or decision resting on them is not the user's.

A user turn is marked relayed when it reads like a pasted work report: an agent
narrating its own work in the first person ("我已核实", "I verified"), with the
marks of generated text (bold, code spans, headings, status marks, tables),
technical traces (process ids, hashes, paths, ports), or the way people
introduce a paste ("这是 claude 做的", "那边的看法"). A pasted article (its
"原创 作者 日期" line) is relayed too. The rule is deliberately cautious: a
long message the user wrote themselves, even a structured one, is not enough on
its own; an agent's first-person work voice is what tips it.

Nothing is removed or changed: the turn stays, its quotes stay, and they are
shown as "用户转贴". Only whether they count as the user's own words changes.
"""

from __future__ import annotations

import json
import re

RULES_VERSION = "2"  # change it when the rules change: stored quotes are judged again
MIN_CHARS = 200
THRESHOLD = 5
LEAD_CHARS = 300  # a line of the user's own on top of a paste

PASTE_WRAPPER = re.compile(r"<pasted_content\b|\[Pasted text #\d+", re.IGNORECASE)
AGENT_WORK = re.compile(
    r"我(?:已经|已|刚刚|刚|先|这边|独立|亲自|上机|复核|核实|核对|检查了|验证了|跑了|测了|实测|改了|修了|查了|确认了|发现|排查|定位到|看了一下)"
    r"|(?:I|We)(?: have|'ve)? (?:checked|verified|ran|tested|fixed|found|confirmed|reviewed|implemented|updated|inspected|investigated)\b"
    r"|\bI (?:will|'ll) (?:now )?(?:check|run|fix|update)\b",
    re.IGNORECASE,
)
HEADING = re.compile(r"^\s*(?:#{1,4} \S|\*\*[^*\n]{2,40}\*\*\s*$|[一二三四五六七八九十]+、)", re.MULTILINE)
STATUS = re.compile(r"[✅❌⚠🔴🟡🟢✔☑]")
TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)
TECH = re.compile(
    r"\b(?:PID|SHA-?256|sha256|commit|exit code|stdout|stderr|Traceback|HTTP/1\.[01]|localhost|127\.0\.0\.1)\b"
    r"|[A-Za-z]:\\[^\s]+|(?<![\w.])/(?:Users|home|var|etc|opt|vol\d)/\S+|:\d{4,5}\b",
    re.IGNORECASE,
)
REPORT_WORD = re.compile(r"自查|结论|总结|汇报|回执|验收|下一步|待确认|Summary|Conclusion|Findings|Next steps|Status:", re.IGNORECASE)
BOLD = re.compile(r"\*\*[^*\n]{1,80}\*\*")
CODE_SPAN = re.compile(r"`[^`\n]{1,120}`")
# How people introduce a paste: "这是 claude 做的", "那边的看法", "codex 的反馈", "这里有一份审计".
PREFACE = re.compile(
    r"^.{0,24}?(?:这是|那边|这里有|下面是|以下是|转给你|转发|贴一下|"
    r"(?:claude|codex|gpt|gemini|deepseek|dsh|hermes|workbuddy|openclaw|opus|sonnet|mimo|minimax|ai)\s*(?:的|说|回复|反馈|报告|结论|看法|复核)"
    r"|(?:的|份)(?:反馈|报告|审计|复核|看法|回复|结论|自查))",
    re.IGNORECASE | re.DOTALL,
)
# A pasted article: "原创 <作者> <公众号> 2026年5月20日 07:12".
ARTICLE = re.compile(r"原创\s+(?:\S{1,20}\s+){1,3}\d{4}年\d{1,2}月\d{1,2}日")


# Some harnesses put context above what the user typed (files mentioned, the page
# open in a browser, earlier answers the user selected) and then the request
# under a heading. Only what follows the last such heading is the user's.
REQUEST_HEADING = re.compile(r"^#{1,3} My request(?: for [^:\n]{1,40})?:[ \t]*$", re.MULTILINE)


def own_part(text: str) -> str:
    """The part of a user turn the user typed (all of it, unless a harness put context above it)."""
    found = None
    for found in REQUEST_HEADING.finditer(text):
        pass
    return text[found.end():] if found else text


# In that context the user may also have written comments of their own: on a part
# of a web page ("Comment:" and the words under it) or on an earlier answer
# ("annotation": "..."). Those are the user's words.
PAGE_COMMENT = re.compile(r"^Comment:[ \t]*\n(.+?)(?=\n[ \t]*\n|\n#{1,3} |\Z)", re.MULTILINE | re.DOTALL)
ANNOTATION = re.compile(r'"annotation"\s*:\s*"((?:[^"\\]|\\.)*)"')


def user_comments(context: str) -> list[str]:
    found = [match.group(1).strip() for match in PAGE_COMMENT.finditer(context)]
    for match in ANNOTATION.finditer(context):
        try:
            found.append(json.loads(f'"{match.group(1)}"'))
        except ValueError:
            found.append(match.group(1))
    return [comment for comment in found if comment]


def voice_of(role: str, text: str, quote: str) -> str:
    """Whose words a quote is: 'user' (the user's own), 'relayed' (pasted in, or the harness's context), 'assistant'."""
    if role != "user":
        return "assistant"
    text = text or ""
    own = own_part(text)
    if own is not text and quote and quote not in own and quote in text:
        # Quoted from the context the harness put above the request: the user's only where they commented.
        context = text[: len(text) - len(own)]
        return "user" if any(quote in comment for comment in user_comments(context)) else "relayed"
    if not relayed(own):
        return "user"
    # A paste often comes with a line of the user's own on top ("这何止是人好读啊……").
    lead = own.strip().split("\n\n", 1)[0]
    if quote and quote in lead and len(lead) <= LEAD_CHARS and lead != own.strip() and not _generated(lead):
        return "user"
    return "relayed"


def _generated(text: str) -> bool:
    """Marks a person rarely types but generated text is full of."""
    return bool(BOLD.search(text) or CODE_SPAN.search(text) or HEADING.search(text) or STATUS.search(text)
                or AGENT_WORK.search(text))


def signals(text: str) -> dict[str, int]:
    return {
        "agent_work": len(AGENT_WORK.findall(text)),
        "headings": len(HEADING.findall(text)),
        "status": len(STATUS.findall(text)),
        "table": len(TABLE_ROW.findall(text)),
        "tech": len(TECH.findall(text)),
        "report_words": len(REPORT_WORD.findall(text)),
        "bold": len(BOLD.findall(text)),
        "code": len(CODE_SPAN.findall(text)),
        "preface": int(bool(PREFACE.match(text))),
    }


def relayed(text: str) -> bool:
    """Whether a user turn reads like something the user pasted in rather than wrote."""
    if not isinstance(text, str) or len(text) < MIN_CHARS:
        return False
    if PASTE_WRAPPER.search(text) or ARTICLE.search(text[:400]):
        return True
    found = signals(text)
    if not found["agent_work"]:
        return False  # without an agent's own work voice, a structured message is still the user's
    score = min(found["agent_work"], 3) * 2
    score += 2 if found["preface"] else 0
    score += 2 if found["bold"] >= 2 else 0
    score += 2 if found["code"] >= 2 else 0
    score += 2 if found["headings"] >= 2 else 0
    score += 2 if found["status"] >= 2 else 0
    score += 2 if found["table"] >= 2 else 0
    score += 1 if found["tech"] >= 2 else 0
    score += 1 if found["report_words"] >= 2 else 0
    score += 1 if len(text) >= 800 else 0
    return score >= THRESHOLD


# ---- whose words a stored quote is -------------------------------------------------

# Quotes stored before voices were judged have voice '' until the background pass
# reaches them; meanwhile they count by the turn's role, as before.
USER_VOICE_SQL = "(e.voice = 'user' OR (e.voice = '' AND s.role = 'user'))"


def is_user_voice(voice: str, role: str) -> bool:
    return voice == "user" or (not voice and role == "user")


def add_evidence(db, memory_id: int, segment_id: int, quote: str) -> tuple[int, str]:
    """Store a quote as a memory's evidence, with whose words it is. Returns (row id, voice)."""
    row = db.execute("SELECT role, text FROM segments WHERE id = ?", (segment_id,)).fetchone()
    voice = voice_of(row[0], row[1], quote) if row else ""
    rowid = db.execute(
        "INSERT INTO memory_evidence(memory_id, segment_id, quote, voice) VALUES(?,?,?,?)", (memory_id, segment_id, quote, voice)
    ).lastrowid
    return rowid, voice
