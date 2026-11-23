"""Bringing in history that an agent's own session folder no longer holds.

For example the copies an earlier Time Library install kept, after the agent
itself cleaned up old sessions. The files are read the same way as live ones
(same format description, same runtime filtering, same redaction), but they go
up marked as imported history: the server keeps them apart from the nightly
round until the owner decides to have them organised, since that can be large.

Resumable: progress is kept per folder, and anything already on the server
(including the same messages arriving from a live session file) is stored once.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from time import sleep

from .api import Api, ServerUnreachable
from .formats import spec_from_report
from .state import State, _atomic_write_json, _load_json
from .formats import path_session_id
from .sync import (BATCH_CHARS, BATCH_SEGMENTS, compressed_progress, file_context, file_stamp, iter_records, left_out,
                   read_start, report_folders, segments_for_record, stored_resume)

# Separate from the live read positions: the background client keeps writing
# those while an import runs in another process.
PROGRESS_FILE = "import-progress.json"
# Waits before sending a batch again; then the import stops (and resumes next run).
RETRY_PAUSES = (10, 30, 60, 120, 300, 600)
IMPORT_TIMEOUT_SECONDS = 120


@dataclass
class ImportResult:
    agent: str
    files: int = 0
    files_read: int = 0
    segments: int = 0
    chars: int = 0
    accepted: int = 0
    duplicates: int = 0
    folders: int = 0
    notes: list[str] = field(default_factory=list)


def import_history(
    api: Api | None, state: State, agent_name: str, folder: str, glob: str | list[str], reported_format: Any, *,
    dry_run: bool = False, folders_only: bool = False,
) -> ImportResult:
    agents = state.config.get("agents", {})
    if agent_name not in agents:
        raise SystemExit(f"agent '{agent_name}' has not reported itself on this computer yet")
    agent_id = int(agents[agent_name]["agent_id"])
    spec = spec_from_report(reported_format)
    root = Path(folder).expanduser()
    result = ImportResult(agent=agent_name)
    if not root.is_dir():
        result.notes.append(f"folder not found: {root}")
        return result
    categories = state.config.get("redact")
    progress_path = state.home / PROGRESS_FILE
    every = _load_json(progress_path)
    progress = {} if dry_run else every.setdefault(f"{agent_name}:{root}", {})

    def save() -> None:
        _atomic_write_json(progress_path, every, private=False)

    def flush(batch: list[dict[str, Any]]) -> None:
        for index in range(0, len(batch), BATCH_SEGMENTS):
            part = batch[index : index + BATCH_SEGMENTS]
            for attempt, pause in enumerate((*RETRY_PAUSES, None)):
                try:
                    reply = api.ingest(agent_id, part, origin="import")
                    break
                except ServerUnreachable as error:
                    # A bulk import can outrun a busy server. Sending the same
                    # batch again is harmless: the server stores each message once.
                    if pause is None:
                        raise
                    result.notes.append(f"server slow or unreachable ({error}); sending again in {pause}s")
                    sleep(pause)
            result.accepted += int(reply.get("accepted", 0))
            result.duplicates += int(reply.get("duplicates", 0))

    patterns = [glob] if isinstance(glob, str) else list(glob)
    # Several patterns may be needed to pick the session files out from a
    # folder that also holds other files; a file matched twice is read once.
    files = sorted({candidate for pattern in patterns for candidate in root.glob(pattern) if candidate.is_file()})
    for path in [] if folders_only else files:
        result.files += 1
        relative = path.relative_to(root).as_posix()
        source_file = ("history/" + relative)[-512:]
        try:
            info = path.stat()
        except OSError:
            continue
        size = info.st_size
        stored = progress.get(source_file, 0)
        whole = spec.store == "json"
        if whole:
            stamp = file_stamp(info)
            if isinstance(stored, dict) and stored.get("stamp") == stamp:
                continue
            offset, compressed = (int(stored.get("at") or 0) if isinstance(stored, dict) else 0), False
        else:
            start_at = read_start(path, stored, size)
            if start_at is None:
                continue
            offset, compressed = start_at
            if not compressed and isinstance(stored, int) and size < stored:
                continue  # read before, and the file got smaller since: leave it
        if left_out(path, spec):
            continue
        resume, marks = stored_resume(stored), []
        result.files_read += 1
        batch: list[dict[str, Any]] = []
        batch_chars = 0
        read_to = offset
        named = path_session_id(spec, relative)
        folder: dict[str, str] = (
            file_context(path, spec, source_file=relative) if offset else ({"session_id": named} if named else {})
        )
        for start, end, record in iter_records(path, spec, offset, resume=resume, marks=marks):
            segments = [] if record is None else segments_for_record(
                record, spec=spec, source_file=source_file, line_start=start, redact_categories=categories, folder=folder
            )
            chars = sum(len(segment["text"]) for segment in segments)
            result.segments += len(segments)
            result.chars += chars
            if not dry_run and batch and (len(batch) + len(segments) > BATCH_SEGMENTS or batch_chars + chars > BATCH_CHARS):
                flush(batch)
                progress[source_file] = ({"at": read_to, "stamp": None} if whole
                                         else compressed_progress(read_to, -1, resume, marks) if compressed else read_to)
                save()
                batch, batch_chars = [], 0
            if not dry_run:
                batch.extend(segments)
                batch_chars += chars
            read_to = end
        if not dry_run:
            if batch:
                flush(batch)
            progress[source_file] = ({"at": read_to, "stamp": stamp} if whole
                                     else compressed_progress(read_to, size, resume, marks) if compressed else read_to)
            save()
    if not dry_run and (spec.cwd or spec.surface):
        # Which folder each of these sessions worked in (also for files read on an earlier run).
        result.folders = report_folders(api, agent_id, spec, [(path, ("history/" + path.relative_to(root).as_posix())[-512:]) for path in files])
    return result
