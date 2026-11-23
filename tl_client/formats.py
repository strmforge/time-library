"""Session formats: how to find the dialogue inside an agent's session file.

There is no per-product parser here and there must never be one. An agent
self-reports its session format either as the name of one of a few generic
shapes below, or as a small description (plain data) that overrides them. A new
agent is supported by what it reports, not by new code.

"Dialogue" means what the user and the assistant said to each other. Tool
calls, tool output, reasoning traces, injected context and transcript
bookkeeping are runtime: they are dropped here and never leave the computer.
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

ROLE_ALIASES = {"human": "user", "ai": "assistant", "model": "assistant"}
DIALOGUE_ROLES = ("user", "assistant")

# Wrapper elements that harnesses inject into a "user" turn. Their whole content
# is runtime, so the element is removed; if nothing else is left the turn was
# not something the user said.
RUNTIME_ELEMENTS = (
    "system-reminder",
    "command-name",
    "command-message",
    "command-args",
    "local-command-stdout",
    "local-command-stderr",
    "local-command-caveat",
    "task-notification",
    "tools-used-before-summary",
    "artifact-view-context",
    "artifact-content-authored-by-others",
    "environment_context",
    "user_instructions",
    "external_codex_apps_open_page",
    "time-library-memory",  # our own recall, if a host writes it into the turn
    "subagent_notification",
    "codex_internal_context",
    "goal_context",
    "in-app-browser-context",
    "heartbeat",
    "turn_aborted",
    "recommended_plugins",
    "codex_delegation",
    "thinking",
)

# Whole-turn placeholders a harness writes in the user's name (regular
# expressions, matched against the entire cleaned turn).
RUNTIME_MESSAGES = (
    r"\[Request interrupted by user[^\]]*\]",
    r"# AGENTS\.md instructions\b.*",  # project instructions injected as a user turn
)

_INLINE_DATA = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=\s]{200,}")


@dataclass(frozen=True)
class FormatSpec:
    """A description of one session shape. All paths are dotted lookups.

    Most agents keep sessions as JSONL files. Some keep them in a SQLite
    database: then store is "sqlite", each row of `table` is one record (its
    columns are the paths), and `order` is a column that only grows (the row id),
    so reading can carry on where it stopped. The database is only ever read."""

    name: str
    store: str = "jsonl"
    table: str = ""
    order: str = ""
    # Every (path, allowed values) pair must hold for a record to be considered.
    match: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # ... and these too, for a record in the user's name. Harnesses write their
    # own context (the time, approvals, a subagent's report) as user turns; this
    # says which user records are the ones the user actually typed.
    user_match: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # A record is skipped when any of these paths holds a true value.
    skip_if_true: tuple[str, ...] = ()
    # ... or when one of these paths holds one of the listed values (for example
    # an assistant message marked as running commentary rather than an answer).
    skip_if_equals: tuple[tuple[str, tuple[str, ...]], ...] = ()
    role: tuple[str, ...] = ("role",)
    content: tuple[str, ...] = ("content",)
    timestamp: tuple[str, ...] = ("timestamp",)
    # Where a record says which session it belongs to. A file whose messages
    # don't say may name it once in an earlier record (a header line).
    session_id: tuple[str, ...] = ()
    # Where a record says which folder the agent was working in (any record, not
    # only messages). Used to place a session in a project the agent declared.
    cwd: tuple[str, ...] = ()
    # Where a record says the session was started, when one agent has several
    # (its desktop app, its command line): kept with the session, shown beside
    # the agent's name. The agent's own word for it, unchanged.
    surface: tuple[str, ...] = ()
    # Only blocks of these types are dialogue text. Everything else in a content
    # list (tool calls, tool results, reasoning, images) is runtime.
    text_block_types: tuple[str, ...] = ("text", "input_text", "output_text")
    runtime_elements: tuple[str, ...] = RUNTIME_ELEMENTS
    runtime_messages: tuple[str, ...] = RUNTIME_MESSAGES
    # Wrappers around what the user typed (<user_query>...</user_query>): the tags
    # go, the words inside stay.
    unwrap_elements: tuple[str, ...] = ()
    # When the speaker field uses words of its own ("USER_EXPLICIT", "MODEL"):
    # which of them mean the user and which the assistant.
    role_map: tuple[tuple[str, str], ...] = ()
    # When a session's id is only in its file's path (a folder per session): a
    # regular expression over the path relative to the sessions folder, whose
    # first group is the id.
    session_id_from_path: str = ""
    # The keys a content block keeps its text under.
    block_text: tuple[str, ...] = ("text",)
    # store "json": each file is one JSON document holding the session; this is
    # the dotted path to its list of records ("" when the document is the list).
    records: str = ""
    # store "sqlite": columns that hold JSON text, read as objects so paths can go into them.
    json_columns: tuple[str, ...] = ()
    # A whole session file is left out when its first record holds one of these
    # values: a subagent's own transcript, for example, where what the lead agent
    # sends it is written as the user's turn.
    session_skip_if_equals: tuple[tuple[str, tuple[str, ...]], ...] = ()


BUILTIN_FORMATS: dict[str, FormatSpec] = {
    spec.name: spec
    for spec in (
        # {"type": "user", "message": {"role": ..., "content": str | [blocks]}}
        FormatSpec(
            name="message_envelope_content_blocks",
            match=(("type", ("user", "assistant")),),
            skip_if_true=(
                "isMeta",
                "isSidechain",
                "isCompactSummary",
                "isVisibleInTranscriptOnly",
                "isApiErrorMessage",
            ),
            role=("message.role",),
            content=("message.content",),
            timestamp=("timestamp",),
            session_id=("sessionId",),
            cwd=("cwd",),
            surface=("entrypoint",),
        ),
        # {"type": "response_item", "payload": {"type": "message", "role": ..., "content": [blocks]}}
        FormatSpec(
            name="response_item_payload_message",
            match=(("type", ("response_item",)), ("payload.type", ("message",))),
            # Progress narration while working; the answer is marked final_answer.
            skip_if_equals=(("payload.phase", ("commentary",)),),
            role=("payload.role",),
            content=("payload.content",),
            timestamp=("timestamp",),
            cwd=("payload.cwd",),
        ),
        # {"role": ..., "content": ...}
        FormatSpec(
            name="flat_role_content",
            role=("role",),
            content=("content", "text"),
            timestamp=("timestamp", "created_at", "createdAt"),
            session_id=("session_id", "sessionId"),
            cwd=("cwd",),
        ),
    )
}

_LIST_FIELDS = ("skip_if_true", "role", "content", "timestamp", "session_id", "cwd", "surface", "text_block_types",
                "unwrap_elements", "block_text")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def spec_from_report(reported: Any) -> FormatSpec:
    """Turn what an agent reported into a FormatSpec.

    A string names a built-in shape. An object may name a "base" shape and
    override any field, which is how an agent with an unfamiliar format gets
    read without anyone writing a parser for it.
    """
    if isinstance(reported, str):
        if reported not in BUILTIN_FORMATS:
            raise ValueError(f"unknown session format: {reported}")
        return BUILTIN_FORMATS[reported]
    if not isinstance(reported, Mapping):
        raise ValueError("session format must be a name or an object")
    base_name = reported.get("base", "flat_role_content")
    if base_name not in BUILTIN_FORMATS:
        raise ValueError(f"unknown base session format: {base_name}")
    changes: dict[str, Any] = {"name": str(reported.get("name") or f"custom:{base_name}")}
    store = reported.get("store", "jsonl")
    if store not in ("jsonl", "json", "sqlite"):
        raise ValueError("store must be jsonl, json or sqlite")
    if store == "json":
        records = reported.get("records", "")
        if not isinstance(records, str):
            raise ValueError("records must be the dotted path to the list of records (or \"\")")
        changes["store"], changes["records"] = "json", records
    if store == "sqlite":
        for field in ("table", "order"):
            value = reported.get(field)
            if not isinstance(value, str) or not _IDENTIFIER.match(value):
                raise ValueError(f"a sqlite store needs {field}: a table or column name")
            changes[field] = value
        changes["store"] = "sqlite"
    for field in _LIST_FIELDS:
        if field in reported:
            changes[field] = _strings(reported[field], field)
    if "json_columns" in reported:
        columns = _strings(reported["json_columns"], "json_columns")
        if not all(_IDENTIFIER.match(column) for column in columns):
            raise ValueError("json_columns must be column names")
        changes["json_columns"] = columns
    if "role_map" in reported:
        given = reported["role_map"]
        if not isinstance(given, Mapping) or not all(
            isinstance(word, str) and word and meaning in DIALOGUE_ROLES + ("skip",) for word, meaning in given.items()
        ):
            raise ValueError('role_map must map your words to "user", "assistant" or "skip"')
        changes["role_map"] = tuple((word, meaning) for word, meaning in given.items())
    if "session_id_from_path" in reported:
        pattern = reported["session_id_from_path"]
        try:
            compiled = re.compile(pattern) if isinstance(pattern, str) else None
        except re.error as error:
            raise ValueError(f"session_id_from_path is not a valid pattern: {error}") from None
        if compiled is None or compiled.groups < 1:
            raise ValueError("session_id_from_path must be a pattern with one group, for example \"^([^/]+)/\"")
        changes["session_id_from_path"] = pattern
    for name in ("match", "user_match", "skip_if_equals", "session_skip_if_equals"):
        if name in reported:
            given = reported[name]
            if not isinstance(given, Mapping):
                raise ValueError(f"{name} must be an object of path -> values")
            changes[name] = tuple((str(path), _strings(values, f"{name}.{path}")) for path, values in given.items())
    if "runtime_elements" in reported:
        # Reported wrappers are added to the shared list, never substituted for it.
        extra = _strings(reported["runtime_elements"], "runtime_elements")
        changes["runtime_elements"] = tuple(dict.fromkeys(RUNTIME_ELEMENTS + extra))
    if "runtime_messages" in reported:
        extra = _strings(reported["runtime_messages"], "runtime_messages")
        for expression in extra:
            try:
                re.compile(expression)
            except re.error as error:
                raise ValueError(f"runtime_messages has an invalid pattern: {error}") from None
        changes["runtime_messages"] = tuple(dict.fromkeys(RUNTIME_MESSAGES + extra))
    return dataclasses.replace(BUILTIN_FORMATS[base_name], **changes)


def _dig(record: Any, path: str) -> Any:
    current = record
    for key in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _first(record: Mapping[str, Any], paths: Iterable[str]) -> Any:
    for path in paths:
        value = _dig(record, path)
        if value is not None:
            return value
    return None


def _dialogue_text(content: Any, text_block_types: tuple[str, ...], block_text: tuple[str, ...] = ("text",)) -> str:
    if isinstance(content, str):
        return content
    blocks = content if isinstance(content, list) else [content]
    parts = []
    for block in blocks:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, Mapping) and block.get("type") in text_block_types:
            for key in block_text:
                text = block.get(key)
                if isinstance(text, str):
                    parts.append(text)
                    break
    return "\n".join(part for part in parts if part)


_ELEMENT_CACHE: dict[tuple[str, ...], "re.Pattern[str]"] = {}


def _inner(match: "re.Match[str]") -> str:
    whole = match.group(0)
    if whole.endswith("/>") and not whole.endswith(f"</{match.group('tag')}>"):
        return ""
    return whole[whole.index(">") + 1 : whole.rindex("</")]


def _runtime_element_pattern(names: tuple[str, ...]) -> "re.Pattern[str]":
    pattern = _ELEMENT_CACHE.get(names)
    if pattern is None:
        alternation = "|".join(re.escape(name) for name in names)
        pattern = re.compile(
            rf"<(?P<tag>{alternation})(?:\s[^>]*)?(?:/>|>.*?</(?P=tag)\s*>)", re.DOTALL
        )
        _ELEMENT_CACHE[names] = pattern
    return pattern


def strip_runtime(text: str, spec: FormatSpec) -> str:
    if spec.runtime_elements:
        text = _runtime_element_pattern(spec.runtime_elements).sub("", text)
    if spec.unwrap_elements:
        text = _runtime_element_pattern(spec.unwrap_elements).sub(_inner, text)
    text = _INLINE_DATA.sub("[内嵌数据已省略]", text).strip()
    if any(re.fullmatch(expression, text, re.DOTALL) for expression in spec.runtime_messages):
        return ""
    return text


@dataclass(frozen=True)
class Message:
    role: str
    text: str
    timestamp: str
    session_id: str


def extract_cwd(record: Any, spec: FormatSpec) -> str:
    """The working folder a record names, or ''."""
    if not isinstance(record, Mapping) or not spec.cwd:
        return ""
    value = _first(record, spec.cwd)
    return value.strip()[:512] if isinstance(value, str) else ""


def session_left_out(first_record: Any, spec: FormatSpec) -> bool:
    """Whether a session file whose first record is this is left out altogether."""
    return isinstance(first_record, Mapping) and any(
        _dig(first_record, path) in values for path, values in spec.session_skip_if_equals
    )


def extract_surface(record: Any, spec: FormatSpec) -> str:
    """Where a record says its session was started, or ''."""
    if not isinstance(record, Mapping) or not spec.surface:
        return ""
    value = _first(record, spec.surface)
    return value.strip()[:40] if isinstance(value, str) else ""


def extract_session_id(record: Any, spec: FormatSpec) -> str:
    """The session a record names, or ''."""
    if not isinstance(record, Mapping) or not spec.session_id:
        return ""
    value = _first(record, spec.session_id)
    return value.strip()[:256] if isinstance(value, str) else ""


def iso_time(value: Any) -> str:
    """A timestamp as text. Numbers are epoch seconds, or milliseconds when that large."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return ""
    seconds = value / 1000 if value > 1e11 else value
    try:
        moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return ""
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_time(text: str) -> datetime | None:
    """An ISO time as an aware datetime (no zone given: UTC), or None."""
    if not isinstance(text, str) or not text.strip():
        return None
    value = text.strip()
    if value.endswith(("Z", "z")):
        value = value[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        try:
            moment = datetime.fromisoformat(value[:19])
        except ValueError:
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def examine(record: Any, spec: FormatSpec) -> tuple[str, Message | None, str]:
    """(what happened, the message, a detail) for one record. What happened is "ok", or why
    the record is not dialogue: "not_a_record", "no_match" (detail: path=value), "skipped",
    "role" (detail: the speaker value), "not_typed" (a user record the harness wrote), "no_words"
    (nothing said in it, such as a tool call), "empty" (all it said was dropped as wrappers)."""
    if not isinstance(record, Mapping):
        return "not_a_record", None, ""
    for path, allowed in spec.match:
        value = _dig(record, path)
        if value not in allowed:
            return "no_match", None, f"{path}={value if isinstance(value, (str, int, float, bool)) else type(value).__name__}"
    if any(_dig(record, path) for path in spec.skip_if_true):
        return "skipped", None, ""
    if any(_dig(record, path) in values for path, values in spec.skip_if_equals):
        return "skipped", None, ""
    raw_role = _first(record, spec.role)
    if not isinstance(raw_role, str):
        return "role", None, "(none)"
    role = dict(spec.role_map).get(raw_role, raw_role).strip()
    role = ROLE_ALIASES.get(role.lower(), role.lower())
    if role not in DIALOGUE_ROLES:
        return "role", None, raw_role[:40]
    if role == "user" and any(_dig(record, path) not in allowed for path, allowed in spec.user_match):
        return "not_typed", None, ""  # written in the user's name by the harness, not typed by the user
    words = _dialogue_text(_first(record, spec.content), spec.text_block_types, spec.block_text)
    if not words.strip():
        return "no_words", None, role  # nothing said (a tool call, say): not a turn
    text = strip_runtime(words, spec)
    if not text:
        return "empty", None, role  # everything said was in wrappers the description drops
    timestamp = _first(record, spec.timestamp)
    session_id = _first(record, spec.session_id)
    return "ok", Message(
        role=role,
        text=text,
        timestamp=iso_time(timestamp),
        session_id=session_id if isinstance(session_id, str) else "",
    ), ""


def extract_message(record: Any, spec: FormatSpec) -> Message | None:
    """Return the dialogue in one session record, or None if it is runtime."""
    return examine(record, spec)[1]


def path_session_id(spec: FormatSpec, relative_path: str) -> str:
    """The session id a file's path gives, when the agent said its sessions are named by their folders."""
    if not spec.session_id_from_path:
        return ""
    found = re.search(spec.session_id_from_path, relative_path)
    return found.group(1)[:256] if found and found.group(1) else ""


def record_from_row(row: Mapping[str, Any], spec: FormatSpec) -> dict[str, Any]:
    """A database row as a record, with the columns that hold JSON read as objects."""
    record = dict(row)
    for column in spec.json_columns:
        value = record.get(column)
        if isinstance(value, (str, bytes)):
            try:
                record[column] = json.loads(value)
            except ValueError:
                pass
    return record
