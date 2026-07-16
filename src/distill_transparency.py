#!/usr/bin/env python3
"""Local, source-backed ledger for distillation model requests."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl as _fcntl
except ImportError:  # Windows
    _fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:  # POSIX
    _msvcrt = None


DISTILL_TRANSPARENCY_CONTRACT = "time_library_distill_transparency_ledger.v1"
DEFAULT_LEDGER_RELATIVE_PATH = "runtime/distill_transparency_ledger.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def default_ledger_path(root: str | os.PathLike[str] | None = None) -> Path:
    override = str(os.environ.get("TIME_LIBRARY_DISTILL_TRANSPARENCY_LEDGER") or "").strip()
    if override:
        return Path(override).expanduser()
    base = Path(
        root
        or os.environ.get("TIME_LIBRARY_DISTILL_ROOT")
        or os.environ.get("MEMCORE_ROOT")
        or os.environ.get("MEMCORE_INSTALL_ROOT")
        or "."
    ).expanduser()
    return base / DEFAULT_LEDGER_RELATIVE_PATH


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _destination_scope(url: str) -> str:
    host = str(urllib.parse.urlparse(url).hostname or "").lower()
    return "local_loopback" if host in {"127.0.0.1", "localhost", "::1"} else "cloud"


def _artifact_id_from_messages(messages: Any) -> str:
    def walk(value: Any) -> str:
        if isinstance(value, dict):
            for key in ("candidate_id", "exp_id", "record_id", "session_id"):
                candidate = str(value.get(key) or "").strip()
                if candidate:
                    return candidate
            for child in value.values():
                found = walk(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found:
                    return found
        elif isinstance(value, str):
            try:
                return walk(json.loads(value))
            except (TypeError, ValueError, json.JSONDecodeError):
                return ""
        return ""

    return walk(messages)


def _response_summary(response_json: Any) -> str:
    content = ""
    if isinstance(response_json, dict):
        choices = response_json.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = str(message.get("content") or "")
        if not content:
            content = str(response_json.get("error") or "")
    return " ".join(content.split())[:1200]


def _lock_append_stream(stream: Any) -> None:
    if _fcntl is not None:
        _fcntl.flock(stream.fileno(), _fcntl.LOCK_EX)
        return
    if _msvcrt is not None:
        stream.seek(0)
        _msvcrt.locking(stream.fileno(), _msvcrt.LK_LOCK, 1)
        return
    raise RuntimeError("no supported file-lock implementation")


def _unlock_append_stream(stream: Any) -> None:
    if _fcntl is not None:
        _fcntl.flock(stream.fileno(), _fcntl.LOCK_UN)
        return
    if _msvcrt is not None:
        stream.seek(0)
        _msvcrt.locking(stream.fileno(), _msvcrt.LK_UNLCK, 1)
        return
    raise RuntimeError("no supported file-lock implementation")


def append_entry(entry: dict[str, Any], path: str | os.PathLike[str] | None = None) -> Path:
    target = Path(path).expanduser() if path else default_ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(fd, "ab", closefd=True) as stream:
            _lock_append_stream(stream)
            try:
                stream.seek(0, os.SEEK_END)
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
            finally:
                _unlock_append_stream(stream)
        os.chmod(target, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    return target


def record_http_call(
    *,
    config: Any,
    url: str,
    request_body: bytes,
    messages: Any,
    started_at: str,
    response_body: bytes = b"",
    response_json: Any = None,
    http_status: int | None = None,
    error: str = "",
    elapsed_seconds: float = 0.0,
) -> dict[str, Any]:
    call_id = "distill-call-" + uuid.uuid4().hex[:20]
    status = "completed" if not error else "failed"
    entry = {
        "contract": DISTILL_TRANSPARENCY_CONTRACT,
        "call_id": call_id,
        "call_kind": str(getattr(config, "transparency_call_kind", "distillation") or "distillation"),
        "started_at": started_at,
        "completed_at": _now(),
        "elapsed_seconds": round(float(elapsed_seconds or 0.0), 3),
        "status": status,
        "provider": str(getattr(config, "provider", "") or ""),
        "endpoint": url,
        "destination_scope": _destination_scope(url),
        "model": str(getattr(config, "model", "") or ""),
        "http_status": http_status,
        "associated_artifact_id": _artifact_id_from_messages(messages),
        "payload_encoding": "utf-8",
        "payload_byte_count": len(request_body),
        "payload_sha256": _sha256(request_body),
        "payload_text": request_body.decode("utf-8"),
        "response_byte_count": len(response_body),
        "response_sha256": _sha256(response_body) if response_body else "",
        "response_summary": _response_summary(response_json),
        "error": str(error or ""),
        "payload_source": "actual_http_request_data",
        "local_only_ledger": True,
        "ledger_append_only": True,
    }
    ledger_path = str(getattr(config, "transparency_ledger_path", "") or "").strip()
    append_entry(entry, ledger_path or None)
    return entry


def read_entries(path: str | os.PathLike[str] | None = None, *, limit: int = 50, call_id: str = "") -> list[dict[str, Any]]:
    target = Path(path).expanduser() if path else default_ledger_path()
    if not target.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            if call_id and str(item.get("call_id") or "") != call_id:
                continue
            rows.append(item)
    if call_id:
        return rows
    return rows[-max(1, int(limit or 50)) :][::-1]


def get_entry(call_id: str, path: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    rows = read_entries(path, call_id=str(call_id or "").strip())
    return rows[0] if rows else None


def ledger_status(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    target = Path(path).expanduser() if path else default_ledger_path()
    rows = read_entries(target, limit=1_000_000)
    return {
        "ok": True,
        "contract": DISTILL_TRANSPARENCY_CONTRACT,
        "ledger_path": str(target),
        "exists": target.is_file(),
        "mode": oct(target.stat().st_mode & 0o777) if target.exists() else "0600",
        "append_only": True,
        "local_only": True,
        "entry_count": len(rows),
        "latest_call_id": str(rows[-1].get("call_id") or "") if rows else "",
    }
