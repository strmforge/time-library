"""Trying a session format on an agent's own files before (or after) reporting it.

An agent describes its sessions itself. This reads its files with that
description, sends nothing anywhere, and says what would be collected and what
looks wrong, so the agent can correct its own description until it reads right.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .formats import (FormatSpec, examine, extract_cwd, extract_session_id, extract_surface, path_session_id,
                      record_from_row, session_left_out)
from .sync import is_compressed, iter_records

MAX_FILES = 400
MAX_RECORDS = 200_000
SAMPLES = 3
TAG_START = re.compile(r"^\s*<([A-Za-z_][\w:-]{0,40})[\s>/]")


def _short(text: str, limit: int = 100) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"


def check(root: Path, glob: str, spec: FormatSpec) -> dict[str, Any]:
    """What reading these sessions with this description gives, and what looks wrong."""
    found: dict[str, Any] = {
        "files": 0, "files_read": 0, "left_out": 0, "compressed": 0, "records": 0,
        "turns": Counter(), "reasons": Counter(), "no_match": Counter(), "roles_unknown": Counter(),
        "sessions": Counter(), "cwd": 0, "surfaces": Counter(), "no_time": 0, "tags": Counter(),
        "samples": {"user": [], "assistant": []}, "truncated": False,
    }

    def take(record: Any, source: str, folder: dict[str, str]) -> None:
        found["records"] += 1
        if isinstance(record, dict):
            cwd = extract_cwd(record, spec)
            if cwd:
                folder["cwd"] = cwd
            if not folder.get("session_id"):
                named = extract_session_id(record, spec)
                if named:
                    folder["session_id"] = named
            surface = extract_surface(record, spec)
            if surface:
                folder["surface"] = surface
        reason, message, detail = examine(record, spec)
        found["reasons"][reason] += 1
        if reason == "no_match":
            found["no_match"][detail] += 1
        elif reason == "role":
            found["roles_unknown"][detail] += 1
        if message is None:
            return
        found["turns"][message.role] += 1
        found["sessions"][message.session_id or folder.get("session_id") or Path(source).stem] += 1
        found["no_time"] += 0 if message.timestamp else 1
        if message.role == "user":
            tag = TAG_START.match(message.text)
            if tag:
                found["tags"][tag.group(1)] += 1
        samples = found["samples"][message.role]
        if len(samples) < SAMPLES:
            samples.append(_short(message.text))

    if spec.store == "sqlite":
        _check_sqlite(root, spec, found, take)
    else:
        files = sorted((candidate for candidate in root.glob(glob) if candidate.is_file()),
                       key=lambda candidate: candidate.stat().st_mtime, reverse=True) if root.is_dir() else []
        found["files"] = len(files)
        if len(files) > MAX_FILES:
            files, found["truncated"] = files[:MAX_FILES], True
        for path in files:
            relative = path.relative_to(root).as_posix()
            found["compressed"] += int(is_compressed(path))
            first = next((record for _, _, record in iter_records(path, spec)), None)
            if spec.session_skip_if_equals and session_left_out(first, spec):
                found["left_out"] += 1
                continue
            found["files_read"] += 1
            named = path_session_id(spec, relative)
            folder: dict[str, str] = {"session_id": named} if named else {}
            for _, _, record in iter_records(path, spec):
                if found["records"] >= MAX_RECORDS:
                    found["truncated"] = True
                    break
                take(record, relative, folder)
            found["cwd"] += int(bool(folder.get("cwd")))
            if folder.get("surface"):
                found["surfaces"][folder["surface"]] += 1
    found["warnings"] = _warnings(found, spec)
    return found


def _check_sqlite(db_path: Path, spec: FormatSpec, found: dict[str, Any], take) -> None:
    if not db_path.is_file():
        found["warnings_extra"] = [f"no database at {db_path}"]
        return
    found["files"] = found["files_read"] = 1
    try:
        db = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        rows = db.execute(f'SELECT * FROM "{spec.table}" ORDER BY "{spec.order}" LIMIT ?', (MAX_RECORDS,))
        folder: dict[str, str] = {}
        for row in rows:
            take(record_from_row(row, spec), f"{db_path.name}#{spec.table}", folder)
        db.close()
    except sqlite3.Error as error:
        found["warnings_extra"] = [f"could not read the database: {error}"]


def _warnings(found: dict[str, Any], spec: FormatSpec) -> list[str]:
    said: list[str] = list(found.pop("warnings_extra", []))
    turns, sessions = found["turns"], found["sessions"]
    ok = turns["user"] + turns["assistant"]
    if not found["files"]:
        said.append("no session files matched: check the sessions folder and --glob")
        return said
    if not found["records"]:
        said.append("files matched, but no records could be read from them: are they JSON lines (or set store)?")
        return said
    if found["no_match"] and found["reasons"]["no_match"] > found["records"] / 2:
        top = ", ".join(f"{value} ×{count}" for value, count in found["no_match"].most_common(6))
        said.append(f"most records do not pass `match`; the values seen there: {top}")
    if found["roles_unknown"]:
        top = ", ".join(f"{value} ×{count}" for value, count in found["roles_unknown"].most_common(6))
        said.append(f"speaker values that are neither user nor assistant: {top}. If some of them are the user or "
                    'the assistant, say so with role_map (for example {"USER_EXPLICIT": "user", "MODEL": "assistant"})')
    if not turns["user"]:
        said.append("no user turns at all: check role (and role_map), match and user_match")
    if not turns["assistant"]:
        said.append("no assistant turns at all: check role (and role_map), content and match")
    if found["files_read"] > 1 and len(sessions) == 1:
        (only,) = sessions
        said.append(f"all {found['files_read']} files give the same session id {only!r}: point session_id at a field "
                    "that names the session, or use session_id_from_path when the folder names it")
    elif found["files_read"] > 3 and len(sessions) < found["files_read"] / 2:
        said.append(f"{found['files_read']} files but only {len(sessions)} session ids: several files share one")
    if turns["user"] and sum(found["tags"].values()) > turns["user"] * 0.3:
        top = ", ".join(f"<{tag}> ×{count}" for tag, count in found["tags"].most_common(5))
        said.append(f"many user turns start with a tag ({top}): if that is context your harness adds rather than "
                    "words the user typed, list it in runtime_elements (dropped) or unwrap_elements (tags dropped, "
                    "words kept), or use user_match")
    if ok and found["no_time"] > ok / 2:
        said.append("most turns have no time: point timestamp at the field that holds it")
    if found["reasons"]["empty"] > max(10, ok):
        said.append(f"{found['reasons']['empty']} records had nothing left after removing wrappers: if they held "
                    "the user's words, a wrapper is listed in runtime_elements that should be in unwrap_elements")
    return said


def check_hook(hook: dict[str, Any], spec: FormatSpec | None, sample: str) -> dict[str, str]:
    """What the prompt hook would look up for this sample input, and what it would print."""
    from .recall import _fill, prompt_from

    raw = sample.encode("utf-8")
    prompt = ""
    if hook.get("prompt"):
        try:
            data = json.loads(sample)
        except ValueError:
            data = None
        if isinstance(data, dict):
            from .formats import _first

            value = _first(data, hook["prompt"])
            prompt = value.strip() if isinstance(value, str) else ""
    else:
        prompt = prompt_from(raw)
    if spec is not None and prompt:
        from .formats import strip_runtime

        prompt = strip_runtime(prompt, spec)
    text = "<time-library-memory>\n(the memories found go here)\n</time-library-memory>"
    output = _fill(hook["output"], text) if "output" in hook else text
    return {
        "prompt": prompt,
        "prints": output if isinstance(output, str) else json.dumps(output, ensure_ascii=False),
        "prints_when_none": hook.get("empty", "") or "(nothing)",
    }


def describe(found: dict[str, Any]) -> str:
    lines = [
        f"files matched: {found['files']}" + (" (the first 400 newest were read)" if found["truncated"] else ""),
        f"left out as whole sessions (session_skip_if_equals): {found['left_out']}",
        f"read: {found['files_read']} files, {found['records']} records"
        + (f", {found['compressed']} of the files zstd-compressed" if found["compressed"] else ""),
        f"would collect: {found['turns']['user']} user turns, {found['turns']['assistant']} assistant turns, "
        f"in {len(found['sessions'])} sessions",
    ]
    if found["sessions"]:
        lines.append("session ids, for example: " + ", ".join(list(found["sessions"])[:3]))
    lines.append(f"working folder found for {found['cwd']} of {found['files_read']} files"
                 + (", started from: " + ", ".join(found["surfaces"]) if found["surfaces"] else ""))
    skipped = {reason: count for reason, count in found["reasons"].items() if reason != "ok"}
    if skipped:
        lines.append("not dialogue (left out): " + ", ".join(f"{reason} ×{count}" for reason, count in skipped.items()))
    for role in ("user", "assistant"):
        for sample in found["samples"][role]:
            lines.append(f"  {role}: {sample}")
    if found["warnings"]:
        lines.append("")
        lines.append("to look at:")
        lines.extend(f"- {warning}" for warning in found["warnings"])
    else:
        lines.append("")
        lines.append("looks right: report it with report-agent (the same --sessions, --glob and format).")
    return "\n".join(lines)
