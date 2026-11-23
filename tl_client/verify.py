"""Making sure nothing was missed: what the sessions hold, against what the server has.

Uploading remembers how far each file was read; that is trust, not proof. This reads the files again from the
beginning, a little at a time, and asks the server which of those turns it has (by their identity: no text is
sent for that). A turn it does not have is sent then. The outcome is reported, so the owner sees on the Devices
page that it was looked at, and what was found.

Files are read again when they changed and were not looked at since, or after RECHECK_DAYS. A round reads about
ROUND_BYTES and takes at most ROUND_SECONDS, so a computer never notices; a file too large for one round (some
are many gigabytes) is carried on with in the next. When far more is missing than a
hiccup explains, nothing is sent by itself (a description that changed would look like that): it is reported, and
`tl.py verify --repair` sends it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator

from .api import Api
from .formats import FormatSpec, parse_time, path_session_id, record_from_row, spec_from_report
from .state import State
from .sync import BATCH_SEGMENTS, DEFAULT_GLOB, file_context, is_compressed, iter_records, left_out, segments_for_record

FILE = "verify.json"
RECHECK_DAYS = 30
ROUND_BYTES = 512 * 1024 * 1024
ROUND_SECONDS = 45.0
REPAIR_AT_ONCE = 500  # more than this missing in one round is not a hiccup
CHECK_SIZE = 400
SEND_SIZE = min(100, BATCH_SEGMENTS)


def content_key(role: str, ts: str, text: str, part: int = 0) -> str:
    """The same identity the server gives a turn (tl_server/store.py; a test holds them together)."""
    if not ts:
        return ""
    return hashlib.sha256(f"{role}\x00{ts}\x00{part}\x00{text}".encode("utf-8")).hexdigest()[:40]


def _read_to(stored: Any) -> int | None:
    """How far a file was read (None: not at all yet)."""
    if stored is None:
        return None
    if isinstance(stored, dict):
        return 0 if stored.get("left_out") else int(stored.get("at") or 0)
    return int(stored)


# Readers give (where to carry on, the turns of one record), in order.
def _file_segments(path: Path, spec: FormatSpec, source_file: str, at: int, upto: int, categories, since) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    named = path_session_id(spec, source_file)
    # Carrying on mid-file: the session and folder named at its top still hold.
    folder: dict[str, str] = file_context(path, spec, source_file=source_file) if at else ({"session_id": named} if named else {})
    for start, end, record in iter_records(path, spec, at):
        if start >= upto:
            return
        yield end, ([] if record is None else segments_for_record(
            record, spec=spec, source_file=source_file, line_start=start, redact_categories=categories, folder=folder, since=since))


def _table_segments(path: Path, spec: FormatSpec, source_file: str, upto: int, categories, since) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        for row in db.execute(f'SELECT * FROM "{spec.table}" WHERE "{spec.order}" <= ? ORDER BY "{spec.order}"', (upto,)):
            yield row[spec.order], segments_for_record(record_from_row(row, spec), spec=spec, source_file=source_file, line_start=row[spec.order],
                                                       redact_categories=categories, since=since)
    finally:
        db.close()


def load(home: Path) -> dict[str, dict[str, Any]]:
    try:
        seen = json.loads((home / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return seen if isinstance(seen, dict) else {}


def save(home: Path, seen: dict[str, dict[str, Any]]) -> None:
    partial = home / (FILE + ".part")
    partial.write_text(json.dumps(seen), encoding="utf-8")
    partial.replace(home / FILE)


def verify_agent(api: Api, state: State, name: str, seen: dict[str, dict[str, Any]], *, everything: bool = False,
                 repair: bool = False, bytes_left: int = ROUND_BYTES, until: float | None = None) -> dict[str, Any]:
    """One agent's files, as many as the round allows. Returns what was found (and how many bytes were read)."""
    agent = state.config["agents"][name]
    spec = spec_from_report(agent["format"])
    since = parse_time(agent.get("since") or "")
    root = Path(agent["sessions_root"]).expanduser()
    agent_id = int(agent["agent_id"])
    categories = state.config.get("redact")
    progress = state.progress.get(name) or {}
    looked = seen.setdefault(name, {})
    found: dict[str, Any] = {"files": 0, "read": 0, "segments": 0, "missing": 0, "repaired": 0, "gone": 0, "held_back": 0, "bytes": 0}

    if spec.store == "sqlite":
        files = [(root, f"{root.name}#{spec.table}"[-512:])] if root.is_file() else []
    else:
        files = [(path, path.relative_to(root).as_posix()[-512:]) for path in sorted(root.glob(agent.get("glob") or DEFAULT_GLOB))
                 if path.is_file()] if root.is_dir() else []
    present = {source for _, source in files}
    found["gone"] = sum(1 for source in looked if source not in present and not source.startswith("."))
    due = []
    for path, source in files:
        upto = _read_to(progress.get(source))
        if upto is None:
            continue  # not uploaded yet (or before "from now on"): the upload's own business
        try:
            info = path.stat()
        except OSError:
            continue
        found["files"] += 1
        was = looked.get(source) or {}
        fresh = "pos" not in was and was.get("upto") == upto and was.get("size") == info.st_size and time.time() - was.get("at", 0) < RECHECK_DAYS * 86400
        if fresh and not everything:
            continue
        due.append((was.get("at", 0), path, source, upto, info.st_size))
    out_of_time = lambda: until is not None and time.monotonic() >= until  # noqa: E731
    for _, path, source, upto, size in sorted(due, key=lambda item: item[0]):
        if not everything and (found["bytes"] >= bytes_left or out_of_time()):
            break
        was = looked.get(source) or {}
        # Only plain lines can be carried on with in the middle (a compressed file or a document is read whole).
        parts = spec.store == "jsonl" and not is_compressed(path)
        at = int(was.get("pos") or 0) if parts and not everything and int(was.get("pos") or 0) < upto else 0
        earlier = int(was.get("n") or 0) if at else 0
        begun, missing, count, stopped = at, [], earlier, False
        try:
            if spec.store == "sqlite":
                records = _table_segments(path, spec, source, upto, categories, since)
            elif upto <= 0 or left_out(path, spec):
                records = iter(())
            else:
                records = _file_segments(path, spec, source, at, upto, categories, since)
            batch: list[dict[str, Any]] = []
            for end, segments in records:
                batch.extend(segments)
                at = end
                if len(batch) >= CHECK_SIZE:
                    missing += _absent(api, agent_id, batch)
                    count += len(batch)
                    batch = []
                if parts and not everything and (found["bytes"] + at - begun >= bytes_left or out_of_time()):
                    stopped = at < upto
                    break
            for start in range(0, len(batch), CHECK_SIZE):
                missing += _absent(api, agent_id, batch[start : start + CHECK_SIZE])
            count += len(batch)
        except (OSError, sqlite3.Error) as error:
            found.setdefault("notes", []).append(f"{source}: {error}")
            continue
        found["bytes"] += (at - begun) if parts else size
        found["read"] += 1
        found["segments"] += count - earlier
        found["missing"] += len(missing)
        if missing:
            if repair or found["repaired"] + len(missing) <= REPAIR_AT_ONCE:
                for start in range(0, len(missing), SEND_SIZE):
                    reply = api.ingest(agent_id, missing[start : start + SEND_SIZE])
                    found["repaired"] += int(reply.get("accepted", 0)) + int(reply.get("duplicates", 0))
            else:
                found["held_back"] += len(missing)
                continue  # not settled: looked at again next round
        if stopped:
            looked[source] = {"pos": at, "at": was.get("at", 0), "n": count}  # carried on with next time
        else:
            looked[source] = {"upto": upto, "size": size, "at": time.time(), "n": count}
    return found


def _absent(api: Api, agent_id: int, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Those of these turns the server does not have."""
    asked = [{"uid": segment["segment_uid"], "key": content_key(segment["role"], segment.get("ts") or "", segment["text"], segment.get("part", 0))}
             for segment in segments]
    absent = set(api.missing(agent_id, asked))
    return [segment for segment in segments if segment["segment_uid"] in absent]


def verify_round(api: Api, state: State, *, only: str = "", everything: bool = False, repair: bool = False) -> dict[str, dict[str, Any]]:
    """Every agent on this computer, within one round; what was found is reported to the server."""
    seen = load(state.home)
    left, until = ROUND_BYTES, time.monotonic() + ROUND_SECONDS
    results: dict[str, dict[str, Any]] = {}
    names = [name for name, agent in (state.config.get("agents") or {}).items() if not agent.get("paused") and (not only or name == only)]
    for number, name in enumerate(names):
        # A share each: one agent's tens of gigabytes must not keep the others waiting for days.
        waiting, agent, now = len(names) - number, state.config["agents"][name], time.monotonic()
        found = verify_agent(api, state, name, seen, everything=everything, repair=repair, bytes_left=max(left // waiting, 1),
                             until=now + max(until - now, 0.0) / waiting)
        left -= found["bytes"]
        results[name] = found
        looked = [entry for source, entry in seen[name].items() if isinstance(entry, dict)]
        if found["read"] or found["held_back"]:
            api.verified(int(agent["agent_id"]), {
                "files": found["files"], "looked": min(sum("pos" not in entry for entry in looked), found["files"]),
                "segments": sum(entry.get("n", 0) for entry in looked),
                "missing": found["held_back"], "repaired": found["repaired"], "gone": found["gone"],
            })
    save(state.home, seen)
    return results
