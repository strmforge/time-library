"""Read new dialogue from an agent's session files and upload it.

Only complete lines are read. Each uploaded piece carries an id derived from
"which file, which line, which part", so sending it twice is harmless. The read
position moves forward only after the server has acknowledged a batch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .api import Api, ServerRefused, ServerUnreachable
from .formats import (FormatSpec, _dig, extract_cwd, extract_message, extract_session_id, extract_surface, parse_time,
                      path_session_id, record_from_row, session_left_out, spec_from_report)
from .redact import redact
from .state import State

MAX_LINE_BYTES = 32 * 1024 * 1024
BATCH_SEGMENTS = 200
BATCH_CHARS = 1_000_000
CHUNK_CHARS = 100_000
DEFAULT_GLOB = "**/*.jsonl"


@dataclass
class SyncResult:
    agent: str
    files_read: int = 0
    accepted: int = 0
    duplicates: int = 0
    pending: int = 0
    paused: bool = False
    notes: list[str] = field(default_factory=list)


def segment_uid(source_file: str, line_start: int, part: int) -> str:
    return hashlib.sha256(f"{source_file}\n{line_start}\n{part}".encode("utf-8")).hexdigest()[:40]


ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
READ_CHUNK = 1 << 20


def is_compressed(path: Path) -> bool:
    """Some agents keep each session file compressed (zstd). Told by the file's first bytes, not its name."""
    try:
        with path.open("rb") as handle:
            return handle.read(4) == ZSTD_MAGIC
    except OSError:
        return False


def iter_complete_lines(
    path: Path, offset: int, *, resume: tuple[int, int] = (0, 0), marks: list[tuple[int, int]] | None = None
) -> Iterator[tuple[int, int, bytes | None]]:
    """Yield (start, end, line) for each complete line from offset.

    A line still being written (no trailing newline yet) is left for next time.
    An oversized line is reported with line=None so the caller can step over it.
    In a compressed file, positions count bytes of its text, not of the file;
    `resume` is (file position, text position) of a frame at or before offset to
    start decoding from, and `marks` collects (text position, file position) of
    each frame read, so the next round can start from one.
    """
    if is_compressed(path):
        yield from _compressed_lines(path, offset, resume, marks)
        return
    with path.open("rb") as handle:
        handle.seek(offset)
        while True:
            start = handle.tell()
            chunk = handle.readline(MAX_LINE_BYTES + 1)
            if not chunk:
                return
            if chunk.endswith(b"\n"):
                yield start, handle.tell(), chunk
                continue
            if len(chunk) <= MAX_LINE_BYTES:
                return  # incomplete tail
            while True:  # oversized: skip to the end of this line without holding it
                more = handle.readline(MAX_LINE_BYTES)
                if not more:
                    return  # oversized and still being written
                if more.endswith(b"\n"):
                    break
            yield start, handle.tell(), None


def _frames(path: Path, file_at: int, text_at: int) -> Iterator[tuple[int, int, bytes]]:
    """(file position, text position, text) of each whole frame from file_at; stops at one still being written."""
    from .zstd import ZstdError, decompress_frame, frame_end

    with path.open("rb") as handle:
        handle.seek(file_at)
        buffer, buffer_at, ended = b"", file_at, False
        while True:
            local = file_at - buffer_at
            try:
                end = frame_end(buffer, local)
            except ZstdError:
                return  # damaged from here on: nothing more can be read from it
            if end is None:
                if ended:
                    return
                more = handle.read(READ_CHUNK)
                if not more:
                    ended = True
                    continue
                buffer, buffer_at = buffer[local:] + more, file_at
                continue
            try:
                text = decompress_frame(buffer[local:end])
            except ZstdError:
                return
            yield file_at, text_at, text
            file_at, text_at = buffer_at + end, text_at + len(text)


def _compressed_lines(path: Path, offset: int, resume: tuple[int, int],
                      marks: list[tuple[int, int]] | None) -> Iterator[tuple[int, int, bytes | None]]:
    file_at, text_at = resume
    if text_at > offset or not _frame_at(path, file_at):
        file_at, text_at = 0, 0  # not a frame there any more (the file was replaced): decode from the top
    pending, line_start, dropped = b"", text_at, False
    reached = text_at
    for frame_file, frame_text, text in _frames(path, file_at, text_at):
        if marks is not None:
            marks.append((frame_text, frame_file))
        reached = frame_text + len(text)
        cursor = 0
        while True:
            newline = text.find(b"\n", cursor)
            if newline < 0:
                if not dropped:
                    pending += text[cursor:]
                    if len(pending) > MAX_LINE_BYTES:  # oversized: remember where it began, not what it says
                        pending, dropped = b"", True
                break
            end = frame_text + newline + 1
            if end > offset:
                line = None if dropped else pending + text[cursor : newline + 1]
                yield line_start, end, line if line is not None and len(line) <= MAX_LINE_BYTES else None
            pending, line_start, dropped = b"", end, False
            cursor = newline + 1
    if offset and (file_at, text_at) == (0, 0) and reached < offset:
        # Its text is shorter than where we got to: the file was replaced. Read it all.
        yield from _compressed_lines(path, 0, (0, 0), marks)


def _frame_at(path: Path, file_at: int) -> bool:
    if file_at == 0:
        return True
    try:
        with path.open("rb") as handle:
            handle.seek(file_at)
            head = handle.read(4)
    except OSError:
        return False
    magic = int.from_bytes(head, "little") if len(head) == 4 else -1
    return head == ZSTD_MAGIC or 0x184D2A50 <= magic <= 0x184D2A5F


MAX_JSON_DOCUMENT_BYTES = 256 * 1024 * 1024


def iter_records(path: Path, spec: FormatSpec, offset: int = 0, *, resume: tuple[int, int] = (0, 0),
                 marks: list[tuple[int, int]] | None = None) -> Iterator[tuple[int, int, Any]]:
    """Yield (start, end, record) from a session file: a line of JSONL (positions are bytes), or one
    entry of a JSON document's list of records (store "json": positions are the entry's index).
    A record that can't be read is yielded as None so it can be stepped over."""
    if spec.store == "json":
        try:
            if path.stat().st_size > MAX_JSON_DOCUMENT_BYTES:
                return
            document = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return  # being written, or not JSON: try again when it changes
        entries = _dig(document, spec.records) if spec.records else document
        if not isinstance(entries, list):
            return
        for index in range(offset, len(entries)):
            yield index, index + 1, entries[index]
        return
    for start, end, raw in iter_complete_lines(path, offset, resume=resume, marks=marks):
        if raw is None:
            yield start, end, None
            continue
        try:
            yield start, end, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            yield start, end, None


def file_stamp(info) -> list[int]:
    return [int(info.st_size), int(info.st_mtime_ns)]


def resume_point(resume: tuple[int, int], marks: list[tuple[int, int]], position: int) -> tuple[int, int]:
    """(file position, text position) of the last frame read that starts at or before position."""
    best = resume
    for text_at, file_at in marks:
        if text_at > position:
            break
        best = (file_at, text_at)
    return best


def read_start(path: Path, stored: Any, size: int) -> tuple[int, bool] | None:
    """(where to start reading, is it compressed), or None when nothing new is in the file.

    `stored` is what was kept last time: for a plain file the position reached;
    for a compressed file {"at": position reached in its text, "size": the file's
    size then}, since a position in the text says nothing about the file's size.
    """
    if isinstance(stored, dict):
        if stored.get("size") == size:
            return None
        return int(stored.get("at") or 0), True
    offset = int(stored or 0)
    if size == offset:
        return None
    if is_compressed(path):
        return offset, True
    return (0 if size < offset else offset), False  # smaller: replaced or truncated, start over


def stored_resume(stored: Any) -> tuple[int, int]:
    """The frame a compressed file's reading can start from: (file position, text position)."""
    frame = stored.get("frame") if isinstance(stored, dict) else None
    if isinstance(frame, list) and len(frame) == 2 and all(isinstance(n, int) and n >= 0 for n in frame):
        return frame[0], frame[1]
    return 0, 0


def compressed_progress(position: int, size: int, resume: tuple[int, int], marks: list[tuple[int, int]]) -> dict:
    """What to keep for a compressed file read up to position; size -1 until it was read to the end."""
    frame = resume_point(resume, marks, position)
    return {"at": position, "size": size, "frame": [frame[0], frame[1]]}


def segments_for_line(
    raw: bytes,
    *,
    spec: FormatSpec,
    source_file: str,
    line_start: int,
    redact_categories: dict[str, bool] | None,
    folder: dict[str, str] | None = None,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """The dialogue in one line. `folder` carries the working folder seen so far in this file."""
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return []
    return segments_for_record(record, spec=spec, source_file=source_file, line_start=line_start,
                               redact_categories=redact_categories, folder=folder, since=since)


def segments_for_record(
    record: Any,
    *,
    spec: FormatSpec,
    source_file: str,
    line_start: int,
    redact_categories: dict[str, bool] | None,
    folder: dict[str, str] | None = None,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """The dialogue in one record: a line of a session file, or a row of a session database.

    With `since`, what was said before then is left out (an agent connected "from now on")."""
    if folder is not None:
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
    message = extract_message(record, spec)
    if message is None:
        return []
    if since is not None:
        said = parse_time(message.timestamp)
        if said is not None and said < since:
            return []
    text = redact(message.text, redact_categories)
    session_id = (message.session_id or (folder or {}).get("session_id") or Path(source_file).stem)[:256]
    cwd = (folder or {}).get("cwd", "")
    segments = [
        {
            "segment_uid": segment_uid(source_file, line_start, part),
            "session_id": session_id,
            "source_file": source_file,
            "position": line_start,
            "part": part,
            "role": message.role,
            "text": text[index : index + CHUNK_CHARS],
            "ts": message.timestamp[:64],
        }
        for part, index in enumerate(range(0, len(text), CHUNK_CHARS))
    ]
    surface = (folder or {}).get("surface", "")
    for segment in segments:
        if cwd:
            segment["cwd"] = cwd
        if surface:
            segment["surface"] = surface
    return segments


_CONTEXT_CACHE: dict[str, dict[str, str]] = {}


def file_context(path: Path, spec: FormatSpec, max_lines: int = 2000, source_file: str = "") -> dict[str, str]:
    """The session id and working folder a session file names (in its path, or its first records); only what was found."""
    key = f"{spec.name}\n{path}"
    if key in _CONTEXT_CACHE:
        return dict(_CONTEXT_CACHE[key])
    found: dict[str, str] = {}
    named = path_session_id(spec, source_file)
    if named:
        found["session_id"] = named
    try:
        for count, (_start, _end, record) in enumerate(iter_records(path, spec)):
            if count >= max_lines or (
                (found.get("cwd") or not spec.cwd) and (found.get("session_id") or not spec.session_id)
                and (found.get("surface") or not spec.surface)
            ):
                break
            if record is None:
                continue
            if not found.get("cwd"):
                found["cwd"] = extract_cwd(record, spec)
            if not found.get("session_id"):
                found["session_id"] = extract_session_id(record, spec)
            if not found.get("surface"):
                found["surface"] = extract_surface(record, spec)
    except OSError:
        return {}
    found = {name: value for name, value in found.items() if value}
    if len(_CONTEXT_CACHE) > 2000:
        _CONTEXT_CACHE.clear()
    if found.get("session_id") or not spec.session_id:
        _CONTEXT_CACHE[key] = dict(found)  # a file not yet naming its session may still do so
    return found


_LEFT_OUT_CACHE: dict[str, bool] = {}


def left_out(path: Path, spec: FormatSpec) -> bool:
    """Whether the agent said sessions like this one are not to be read (its first record tells)."""
    if not spec.session_skip_if_equals:
        return False
    key = f"{spec.name}\n{path}"
    if key not in _LEFT_OUT_CACHE:
        first = None
        try:
            for _start, _end, record in iter_records(path, spec):
                first = record
                break
        except OSError:
            return False
        if first is None:
            return False  # nothing written yet: ask again next time
        if len(_LEFT_OUT_CACHE) > 5000:
            _LEFT_OUT_CACHE.clear()
        _LEFT_OUT_CACHE[key] = session_left_out(first, spec)
    return _LEFT_OUT_CACHE[key]


def session_folder(path: Path, spec: FormatSpec, source_file: str, max_lines: int = 2000) -> tuple[str, str]:
    """(session_id, working folder) for a session file, from its first lines; '' when not found."""
    found = file_context(path, spec, max_lines, source_file=source_file)
    return (found.get("session_id") or Path(source_file).stem[:256]), found.get("cwd", "")


def session_facts(path: Path, spec: FormatSpec, source_file: str) -> dict[str, str]:
    """What the server keeps about a session file: its id, working folder and where it was started."""
    relative = source_file[len("history/"):] if source_file.startswith("history/") else source_file
    found = file_context(path, spec, source_file=relative)
    facts = {"session_id": found.get("session_id") or Path(source_file).stem[:256]}
    facts.update({name: found[name] for name in ("cwd", "surface") if found.get(name)})
    return facts


def report_folders(api: Api, agent_id: int, spec: FormatSpec, files: list[tuple[Path, str]]) -> int:
    """Tell the server which folder each session worked in and where it was started, for sessions sent before."""
    sessions = []
    for path, source_file in files:
        if left_out(path, spec):
            continue
        facts = session_facts(path, spec, source_file)
        if len(facts) > 1:
            sessions.append(facts)
    for index in range(0, len(sessions), 500):
        api.report_sessions(agent_id, sessions[index : index + 500])
    return len(sessions)


def _resume_offset(path: Path, last_position: int) -> int:
    """Server says the line starting at last_position is stored: resume after it."""
    try:
        if not is_compressed(path) and path.stat().st_size <= last_position:
            return 0
        for _start, end, _line in iter_complete_lines(path, last_position):
            return end
    except OSError:
        pass
    return 0


def sync_agent(api: Api, state: State, name: str) -> SyncResult:
    agent = state.config["agents"][name]
    result = SyncResult(agent=name)
    if agent.get("paused"):
        result.paused = True
        result.notes.append("paused: the server disconnected this agent; report it again to resume")
        return result

    spec = spec_from_report(agent["format"])
    since = parse_time(agent.get("since") or "")
    root = Path(agent["sessions_root"]).expanduser()
    agent_id = int(agent["agent_id"])
    categories = state.config.get("redact")
    progress = state.progress.setdefault(name, {})

    def pause() -> SyncResult:
        agent["paused"] = True
        state.save_config()
        state.save_progress()
        result.paused = True
        result.notes.append("the server disconnected this agent; nothing more was sent")
        return result

    # No local read positions (fresh install, or state was wiped): ask the server
    # how far it got instead of sending everything again.
    try:
        server_positions = api.cursor(agent_id) if not progress else {}
    except ServerRefused as refusal:
        if refusal.code == "agent_disconnected":
            return pause()
        raise

    def flush(batch: list[dict[str, Any]]) -> None:
        for index in range(0, len(batch), BATCH_SEGMENTS):
            reply = api.ingest(agent_id, batch[index : index + BATCH_SEGMENTS])
            result.accepted += int(reply.get("accepted", 0))
            result.duplicates += int(reply.get("duplicates", 0))

    if spec.store == "sqlite":
        return _sync_sqlite(api, state, name, root, spec, server_positions, flush, pause, result, since)
    if not root.is_dir():
        result.notes.append(f"sessions location not found: {root}")
        return result

    files = sorted(candidate for candidate in root.glob(agent.get("glob") or DEFAULT_GLOB) if candidate.is_file())
    if (spec.cwd and not agent.get("folders_reported")) or (spec.surface and not agent.get("surfaces_reported")):
        # Once: sessions uploaded before folders (or where they were started) were sent get them now.
        report_folders(api, agent_id, spec, [(path, path.relative_to(root).as_posix()[-512:]) for path in files])
        agent["folders_reported"] = True
        agent["surfaces_reported"] = True
        state.save_config()

    for path in files:
        source_file = path.relative_to(root).as_posix()[-512:]
        stored = progress.get(source_file)
        if stored is None and source_file in server_positions:
            stored = _resume_offset(path, server_positions[source_file])
        try:
            info = path.stat()
        except OSError:
            continue
        size = info.st_size
        if since is not None and stored is None and info.st_mtime < since.timestamp():
            continue  # last written before the agent was connected "from now on"
        whole = spec.store == "json"  # one JSON document per session: rewritten whole, read by entry
        if whole:
            stamp = file_stamp(info)
            if isinstance(stored, dict) and stored.get("stamp") == stamp:
                continue
            offset, compressed = (int(stored.get("at") or 0) if isinstance(stored, dict) else 0), False
        else:
            start_at = read_start(path, stored, size)
            if start_at is None:
                progress[source_file] = stored if stored is not None else 0
                continue
            offset, compressed = start_at
        if left_out(path, spec):
            progress[source_file] = (
                {"at": 0, "stamp": stamp, "left_out": True} if whole
                else {"at": 0, "size": size, "left_out": True} if compressed else size
            )
            continue
        resume, marks = stored_resume(stored), []

        def mark(position: int, done: bool = False) -> None:
            # A compressed file's size is kept only once it was read to the end,
            # so a round cut short carries on where it stopped.
            if whole:
                progress[source_file] = {"at": position, "stamp": stamp if done else None}
            else:
                progress[source_file] = (
                    compressed_progress(position, size if done else -1, resume, marks) if compressed else position
                )

        result.files_read += 1
        batch: list[dict[str, Any]] = []
        batch_chars = 0
        read_to = offset
        # Carrying on mid-file: the session and folder it named at the top (or its path names) still hold.
        named = path_session_id(spec, source_file)
        folder: dict[str, str] = (
            file_context(path, spec, source_file=source_file) if offset else ({"session_id": named} if named else {})
        )
        try:
            for start, end, record in iter_records(path, spec, offset, resume=resume, marks=marks):
                segments = (
                    []
                    if record is None
                    else segments_for_record(
                        record, spec=spec, source_file=source_file, line_start=start, redact_categories=categories,
                        folder=folder, since=since,
                    )
                )
                chars = sum(len(segment["text"]) for segment in segments)
                if batch and (len(batch) + len(segments) > BATCH_SEGMENTS or batch_chars + chars > BATCH_CHARS):
                    result.pending = len(batch)
                    flush(batch)
                    result.pending = 0
                    mark(read_to)
                    state.save_progress()
                    batch, batch_chars = [], 0
                batch.extend(segments)
                batch_chars += chars
                read_to = end
            if batch:
                result.pending = len(batch)
                flush(batch)
                result.pending = 0
        except ServerRefused as refusal:
            if refusal.code == "agent_disconnected":
                return pause()
            state.save_progress()
            raise
        except BaseException:
            state.save_progress()
            raise
        mark(read_to, done=True)
        state.save_progress()

    state.save_progress()
    return result


SQLITE_BATCH_ROWS = 500


def _sync_sqlite(api: Api, state: State, name: str, db_path: Path, spec: FormatSpec, server_positions: dict[str, int],
                 flush, pause, result: SyncResult, since: datetime | None = None) -> SyncResult:
    """An agent that keeps its sessions in a SQLite database: read new rows, in order, read-only."""
    import sqlite3

    if not db_path.is_file():
        result.notes.append(f"sessions database not found: {db_path}")
        return result
    progress = state.progress.setdefault(name, {})
    categories = state.config.get("redact")
    source_file = f"{db_path.name}#{spec.table}"[-512:]
    last = progress.get(source_file)
    if last is None:
        last = server_positions.get(source_file, -1)
    try:
        db = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as error:
        result.notes.append(f"could not open the sessions database: {error}")
        return result
    db.row_factory = sqlite3.Row
    try:
        while True:
            try:
                rows = db.execute(
                    f'SELECT * FROM "{spec.table}" WHERE "{spec.order}" > ? ORDER BY "{spec.order}" LIMIT ?',
                    (last, SQLITE_BATCH_ROWS),
                ).fetchall()
            except sqlite3.Error as error:  # busy, or the table changed shape: try next round
                result.notes.append(f"could not read the sessions database: {error}")
                break
            if not rows:
                break
            result.files_read = 1
            batch: list[dict[str, Any]] = []
            for row in rows:
                position = row[spec.order]
                if not isinstance(position, int) or isinstance(position, bool):
                    result.notes.append(f"{spec.order} is not a growing whole number; stopped reading")
                    return result
                batch.extend(segments_for_record(record_from_row(row, spec), spec=spec, source_file=source_file,
                                                 line_start=position, redact_categories=categories, since=since))
                last = position
            try:
                if batch:
                    result.pending = len(batch)
                    flush(batch)
                    result.pending = 0
            except ServerRefused as refusal:
                if refusal.code == "agent_disconnected":
                    return pause()
                raise
            progress[source_file] = last
            state.save_progress()
    finally:
        db.close()
    return result


def report_catalogs(api: Api, state: State) -> int:
    """Pass on the thinking levels from model catalogs agents reported, when a catalog changed."""
    from .catalogs import read_catalog

    sent = 0
    for name, agent in state.config.get("agents", {}).items():
        path = agent.get("model_catalog")
        if not path:
            continue
        try:
            mtime = Path(path).expanduser().stat().st_mtime
        except OSError:
            continue
        if agent.get("model_catalog_mtime") == mtime:
            continue
        models = read_catalog(path)
        if models:
            api.report_levels(models[:500], agent=name)
            sent += len(models)
        agent["model_catalog_mtime"] = mtime
        state.save_config()
    return sent


def sync_all(api: Api, state: State) -> list[SyncResult]:
    results = [sync_agent(api, state, name) for name in sorted(state.config.get("agents", {}))]
    try:
        report_catalogs(api, state)
    except (ServerRefused, ServerUnreachable):
        pass  # levels are a convenience: try again next round
    backlog = {
        str(state.config["agents"][result.agent]["agent_id"]): result.pending for result in results
    }
    if results:
        api.heartbeat(backlog)
    return results
