#!/usr/bin/env python3
"""Shared current-window binding registry.

The registry is intentionally small and file-based so source collectors,
bridges, and the console can agree on the current window/session identity
without giving ordinary recall a cross-window fallback.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
REGISTRY_VERSION = "2.0"
DEFAULT_REGISTRY_RELATIVE_PATH = "config/window_binding_registry.json"
HISTORY_LIMIT = 80


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _memcore_root() -> Path:
    env_root = os.environ.get("MEMCORE_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser()
    try:
        from config_loader import get_memcore_root

        return Path(get_memcore_root()).expanduser()
    except Exception:
        return Path(__file__).resolve().parents[1]


def registry_path(path: str | Path | None = None) -> Path:
    explicit = str(path or os.environ.get("MEMCORE_WINDOW_BINDING_REGISTRY") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return _memcore_root() / DEFAULT_REGISTRY_RELATIVE_PATH


def _empty_registry() -> dict[str, Any]:
    return {
        "_meta": {
            "version": REGISTRY_VERSION,
            "updated_at": ts(),
            "note": "Current-window binding registry. Ordinary recall still requires a current window/session identity.",
            "rules": [
                "default recall is current-window only",
                "unbound window no recall",
                "no default main",
                "Hermes broad raw-pool reads are limited to explicit skill-generation/self-review workflows",
            ],
        },
        "bindings": {},
        "inferred_from_catalog": {},
        "current_windows": {},
        "current_window_history": [],
    }


def _normalize_registry(value: Any) -> dict[str, Any]:
    registry = value if isinstance(value, dict) else {}
    base = _empty_registry()
    merged = {**base, **registry}
    meta = merged.get("_meta") if isinstance(merged.get("_meta"), dict) else {}
    merged["_meta"] = {**base["_meta"], **meta, "version": str(meta.get("version") or REGISTRY_VERSION)}
    for key, default in (
        ("bindings", {}),
        ("inferred_from_catalog", {}),
        ("current_windows", {}),
    ):
        if not isinstance(merged.get(key), dict):
            merged[key] = default
    if not isinstance(merged.get("current_window_history"), list):
        merged["current_window_history"] = []
    return merged


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    resolved = registry_path(path)
    if not resolved.exists():
        return _empty_registry()
    try:
        data = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except Exception:
        return _empty_registry()
    return _normalize_registry(data)


def save_registry(registry: dict[str, Any], path: str | Path | None = None) -> Path:
    resolved = registry_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_registry(registry)
    normalized["_meta"]["updated_at"] = ts()
    tmp = resolved.with_suffix(resolved.suffix + ".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, resolved)
    return resolved


def _clean(value: Any) -> str:
    return str(value or "").strip()


def current_window_keys(source_system: str, consumer: str = "") -> list[str]:
    keys: list[str] = []
    for value in (consumer, source_system):
        text = _clean(value).lower().replace("-", "_")
        if text and text not in keys:
            keys.append(text)
    if "claude_desktop" in keys and "claude" not in keys:
        keys.append("claude")
    if "codex" in keys and "codex_cli" not in keys:
        keys.append("codex_cli")
    return keys


def get_current_window_binding(
    source_system: str,
    *,
    consumer: str = "",
    path: str | Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(path)
    current_windows = registry.get("current_windows", {})
    if not isinstance(current_windows, dict):
        return {}
    for key in current_window_keys(source_system, consumer):
        entry = current_windows.get(key)
        if not isinstance(entry, dict):
            continue
        canonical_window_id = _clean(entry.get("canonical_window_id"))
        session_id = _clean(entry.get("session_id"))
        if canonical_window_id or session_id:
            result = dict(entry)
            result["binding_key"] = key
            result["canonical_window_id"] = canonical_window_id or session_id
            result["session_id"] = session_id
            return result
    return {}


def register_current_window(
    *,
    source_system: str,
    canonical_window_id: str,
    session_id: str = "",
    consumer: str = "",
    native_window_id: str = "",
    title: str = "",
    source_path: str = "",
    binding_source: str = "",
    confidence: str = "observed",
    metadata: dict[str, Any] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    source = _clean(source_system).lower().replace("-", "_")
    canonical = _clean(canonical_window_id)
    session = _clean(session_id)
    if not source or not (canonical or session):
        return {
            "ok": False,
            "error": "source_system_and_window_identity_required",
            "registry_path": str(registry_path(path)),
        }

    now = ts()
    entry = {
        "source_system": source,
        "consumer": _clean(consumer) or source,
        "canonical_window_id": canonical or session,
        "session_id": session,
        "native_window_id": _clean(native_window_id),
        "title": _clean(title)[:200],
        "source_path": _clean(source_path),
        "binding_source": _clean(binding_source) or "local_source_capture",
        "confidence": _clean(confidence) or "observed",
        "current_window_only": True,
        "cross_window_read_allowed": False,
        "updated_at": now,
    }
    if metadata:
        entry["metadata"] = {
            str(key): value
            for key, value in metadata.items()
            if value not in ("", None, [], {})
        }

    registry = load_registry(path)
    keys = current_window_keys(source, consumer)
    for key in keys:
        registry["current_windows"][key] = dict(entry, binding_key=key)

    registry["bindings"][f"{source}:current"] = {
        "session_key": session or canonical,
        "canonical_window_id": canonical or session,
        "source_system": source,
        "binding_source": entry["binding_source"],
        "bound_at": now,
    }

    history = registry.get("current_window_history", [])
    history.append(dict(entry, binding_keys=keys))
    registry["current_window_history"] = history[-HISTORY_LIMIT:]
    saved_path = save_registry(registry, path)
    return {
        "ok": True,
        "registry_path": str(saved_path),
        "binding_keys": keys,
        "canonical_window_id": entry["canonical_window_id"],
        "session_id": entry["session_id"],
        "source_system": source,
        "current_window_only": True,
    }
