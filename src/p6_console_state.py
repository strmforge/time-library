#!/usr/bin/env python3
"""Local persisted state for the Time Library console.

This module stores only product-console UI state: local tasks, note handles,
and Reading Room project entries. It is intentionally separate from raw
records, preference memory, work experience, and platform configuration.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

try:
    from src.config_loader import base_path
except Exception:
    from config_loader import base_path


CONSOLE_STATE_SCHEMA_VERSION = "console-state.v1"
MEMCORE_ROOT = Path(base_path())
STATE_PATH = MEMCORE_ROOT / "runtime" / "console_state.user.json"


def configure_console_state(memcore_root: str | os.PathLike[str]) -> None:
    global MEMCORE_ROOT, STATE_PATH
    MEMCORE_ROOT = Path(str(memcore_root))
    STATE_PATH = MEMCORE_ROOT / "runtime" / "console_state.user.json"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _default_state() -> dict[str, Any]:
    return {
        "schema_version": CONSOLE_STATE_SCHEMA_VERSION,
        "tasks": [],
        "notes": [],
        "projects": [],
    }


def _clean_text(value: Any, *, max_chars: int) -> str:
    text = " ".join(str(value or "").replace("\r", " ").split())
    return text[:max_chars]


def _clean_priority(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"high", "mid", "low"} else "mid"


def _clean_bool(value: Any, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return default


def _make_id(prefix: str, seed: str) -> str:
    digest = hashlib.sha256(f"{prefix}\x1f{seed}\x1f{_now()}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _read_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default_state()
    except FileNotFoundError:
        return _default_state()
    except Exception:
        return _default_state()
    state = _default_state()
    for key in ("tasks", "notes", "projects"):
        value = data.get(key)
        if isinstance(value, list):
            state[key] = [item for item in value if isinstance(item, dict)]
    state["schema_version"] = str(data.get("schema_version") or CONSOLE_STATE_SCHEMA_VERSION)
    return state


def _write_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".console_state.", suffix=".tmp", dir=str(STATE_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, STATE_PATH)
        try:
            os.chmod(STATE_PATH, 0o600)
        except Exception:
            pass
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except Exception:
                pass


def _public_state(state: dict[str, Any] | None = None) -> dict[str, Any]:
    data = _read_state() if state is None else state
    return {
        "ok": True,
        "schema_version": CONSOLE_STATE_SCHEMA_VERSION,
        "state_storage": "runtime/console_state.user.json",
        "tasks": data.get("tasks", []),
        "notes": data.get("notes", []),
        "projects": data.get("projects", []),
        "write_boundary": {
            "console_state_write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
        },
    }


def get_console_state() -> dict[str, Any]:
    return _public_state()


def add_console_task(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    title = _clean_text(body.get("title"), max_chars=180)
    if not title:
        return {"ok": False, "error": "title_required"}
    state = _read_state()
    item = {
        "id": _make_id("task", title),
        "title": title,
        "priority": _clean_priority(body.get("priority")),
        "created_at": _now(),
    }
    state["tasks"] = [item] + list(state.get("tasks", []))[:49]
    _write_state(state)
    result = _public_state(state)
    result.update({"console_state_write_performed": True, "item": item})
    result["write_boundary"]["console_state_write_performed"] = True
    return result


def delete_console_task(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    item_id = _clean_text(body.get("id"), max_chars=120)
    state = _read_state()
    before = len(state.get("tasks", []))
    state["tasks"] = [item for item in state.get("tasks", []) if str(item.get("id") or "") != item_id]
    changed = len(state["tasks"]) != before
    if changed:
        _write_state(state)
    result = _public_state(state)
    result.update({"console_state_write_performed": changed, "deleted": changed})
    result["write_boundary"]["console_state_write_performed"] = changed
    return result


def add_console_note(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    title = _clean_text(body.get("title"), max_chars=180)
    text = _clean_text(body.get("body") or body.get("text"), max_chars=3000)
    if not title and not text:
        return {"ok": False, "error": "note_required"}
    if not title:
        title = text[:60] or "Note"
    state = _read_state()
    item = {
        "id": _make_id("note", f"{title}\x1f{text}"),
        "title": title,
        "body": text,
        "created_at": _now(),
    }
    state["notes"] = [item] + list(state.get("notes", []))[:49]
    _write_state(state)
    result = _public_state(state)
    result.update({"console_state_write_performed": True, "item": item})
    result["write_boundary"]["console_state_write_performed"] = True
    return result


def delete_console_note(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    item_id = _clean_text(body.get("id"), max_chars=120)
    state = _read_state()
    before = len(state.get("notes", []))
    state["notes"] = [item for item in state.get("notes", []) if str(item.get("id") or "") != item_id]
    changed = len(state["notes"]) != before
    if changed:
        _write_state(state)
    result = _public_state(state)
    result.update({"console_state_write_performed": changed, "deleted": changed})
    result["write_boundary"]["console_state_write_performed"] = changed
    return result


def add_console_project(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    name = _clean_text(body.get("name"), max_chars=180)
    if not name:
        return {"ok": False, "error": "name_required"}
    source = _clean_text(body.get("source"), max_chars=500)
    note = _clean_text(body.get("note"), max_chars=1000)
    state = _read_state()
    item = {
        "id": _make_id("project", f"{name}\x1f{source}"),
        "name": name,
        "source": source,
        "note": note,
        "shared": _clean_bool(body.get("shared"), default=True),
        "created_at": _now(),
    }
    state["projects"] = [item] + list(state.get("projects", []))[:49]
    _write_state(state)
    result = _public_state(state)
    result.update({"console_state_write_performed": True, "item": item})
    result["write_boundary"]["console_state_write_performed"] = True
    return result


def delete_console_project(body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    item_id = _clean_text(body.get("id"), max_chars=120)
    state = _read_state()
    before = len(state.get("projects", []))
    state["projects"] = [item for item in state.get("projects", []) if str(item.get("id") or "") != item_id]
    changed = len(state["projects"]) != before
    if changed:
        _write_state(state)
    result = _public_state(state)
    result.update({"console_state_write_performed": changed, "deleted": changed})
    result["write_boundary"]["console_state_write_performed"] = changed
    return result


__all__ = [
    "CONSOLE_STATE_SCHEMA_VERSION",
    "STATE_PATH",
    "add_console_note",
    "add_console_project",
    "add_console_task",
    "configure_console_state",
    "delete_console_note",
    "delete_console_project",
    "delete_console_task",
    "get_console_state",
]
