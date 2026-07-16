#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook for Time Library preflight.

The hook is intentionally quiet: failures, skip, silent, and scope-required
decisions produce no stdout so Claude Code can continue normally. Only a
source-backed `decision=surface` response is converted into additionalContext.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

HOOK_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(HOOK_ROOT), str(HOOK_ROOT / "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    from src.port_discovery import resolve_client_url
except Exception:
    from port_discovery import resolve_client_url


DEFAULT_ENDPOINT = ""
DEFAULT_TIMEOUT_SECONDS = 1.5
DEFAULT_MAX_CONTEXT_CHARS = 5000
SOURCE_SYSTEM = "claude_code_cli"
DEFAULT_BINDING_KEYS = ("claude_code_cli", "claude_code", "claude")
LIVE_BINDING_SOURCE = "claude_code_user_prompt_submit_hook"
LIVE_NATIVE_ARTIFACT_FORMAT = "claude_code_user_prompt_submit_event"


def _number_from_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
        return value if value > 0 else default
    except Exception:
        return default


def _int_from_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
        return value if value > 0 else default
    except Exception:
        return default


def _load_event(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _compact(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _explicit_text(event: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(event.get(key) or "").strip()
        if value:
            return value
    return ""


def _window_binding_registry_path(explicit: str = "") -> Path:
    value = str(explicit or os.environ.get("MEMCORE_WINDOW_BINDING_REGISTRY") or "").strip()
    if value:
        return Path(value).expanduser()
    root = str(os.environ.get("MEMCORE_ROOT") or "").strip()
    if root:
        return Path(root).expanduser() / "config" / "window_binding_registry.json"
    try:
        return Path(__file__).resolve().parents[1] / "config" / "window_binding_registry.json"
    except Exception:
        return Path("config") / "window_binding_registry.json"


def _binding_keys(binding_key: str = "") -> list[str]:
    keys: list[str] = []
    for key in (
        binding_key,
        os.environ.get("MEMCORE_CLAUDE_CODE_BINDING_KEY"),
        *DEFAULT_BINDING_KEYS,
    ):
        text = str(key or "").strip().lower().replace("-", "_")
        if text and text not in keys:
            keys.append(text)
    return keys


def _binding_matches_event(entry: dict[str, Any], event_session_id: str) -> bool:
    if not event_session_id:
        return False
    session_id = str(entry.get("session_id") or "").strip()
    canonical_window_id = str(entry.get("canonical_window_id") or "").strip()
    return event_session_id in {session_id, canonical_window_id}


def _current_window_binding_from_registry(
    *,
    event_session_id: str,
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, Any]:
    path = _window_binding_registry_path(registry_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    current_windows = data.get("current_windows") if isinstance(data, dict) else {}
    if not isinstance(current_windows, dict):
        return {}
    for key in _binding_keys(binding_key):
        entry = current_windows.get(key)
        if not isinstance(entry, dict):
            continue
        if not _binding_matches_event(entry, event_session_id):
            continue
        canonical_window_id = str(entry.get("canonical_window_id") or entry.get("session_id") or "").strip()
        session_id = str(entry.get("session_id") or "").strip()
        if canonical_window_id or session_id:
            result = dict(entry)
            result["binding_key"] = key
            result["canonical_window_id"] = canonical_window_id
            result["session_id"] = session_id
            return result
    return {}


def _binding_metadata(binding: dict[str, Any]) -> dict[str, Any]:
    metadata = binding.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _binding_text(binding: dict[str, Any], *keys: str) -> str:
    metadata = _binding_metadata(binding)
    for key in keys:
        value = str(binding.get(key) or metadata.get(key) or "").strip()
        if value:
            return value
    return ""


def _explicit_project_anchor(event: dict[str, Any]) -> str:
    return _explicit_text(
        event,
        "project_id",
        "project_root",
        "workspace_root",
        "workstream_id",
        "workstream",
        "task_id",
        "task",
    )


def _has_strong_anchor(event: dict[str, Any]) -> bool:
    return bool(str(event.get("canonical_window_id") or "").strip() or _explicit_project_anchor(event))


def _project_id_from_path(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    try:
        name = Path(text).expanduser().name
    except Exception:
        name = ""
    return name or text.rstrip("/").rsplit("/", 1)[-1]


def _hook_repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except Exception:
        return Path.cwd()


def _register_current_window_import() -> Any:
    root = _hook_repo_root()
    src_dir = root / "src"
    for candidate in (str(root), str(src_dir)):
        if candidate and candidate not in sys.path:
            sys.path.insert(0, candidate)
    try:
        from src.window_binding_registry import register_current_window

        return register_current_window
    except Exception:
        try:
            from window_binding_registry import register_current_window

            return register_current_window
        except Exception:
            return None


def _live_project_root(event: dict[str, Any]) -> str:
    return _explicit_text(event, "project_root", "workspace_root", "cwd")


def _live_project_id(event: dict[str, Any], project_root: str) -> str:
    return _explicit_text(event, "project_id") or _project_id_from_path(project_root)


def _self_register_live_window_binding(
    event: dict[str, Any],
    *,
    registry_path: str = "",
) -> dict[str, Any]:
    event_session_id = str(event.get("session_id") or "").strip()
    if not event_session_id:
        return {}
    transcript_path = str(event.get("transcript_path") or "").strip()
    project_root = _live_project_root(event)
    if not transcript_path:
        return {}
    register_current_window = _register_current_window_import()
    if register_current_window is None:
        return {}
    project_id = _live_project_id(event, project_root)
    metadata = {
        "project_id": project_id,
        "project_root": project_root,
        "workspace_root": _explicit_text(event, "workspace_root") or project_root,
        "cwd": _explicit_text(event, "cwd") or project_root,
        "transcript_path": transcript_path,
        "native_artifact_format": LIVE_NATIVE_ARTIFACT_FORMAT,
        "binding_source": LIVE_BINDING_SOURCE,
        "runtime_consumer": SOURCE_SYSTEM,
        "conversation_origin": SOURCE_SYSTEM,
        "hook_event_name": str(event.get("hook_event_name") or "UserPromptSubmit"),
        "workstream_id": _explicit_text(event, "workstream_id", "workstream"),
        "task_id": _explicit_text(event, "task_id", "task"),
    }
    try:
        result = register_current_window(
            source_system=SOURCE_SYSTEM,
            consumer=SOURCE_SYSTEM,
            canonical_window_id=str(event.get("canonical_window_id") or event_session_id).strip(),
            session_id=event_session_id,
            native_window_id=event_session_id,
            title=_compact(event.get("prompt"), 120),
            source_path=transcript_path,
            binding_source=LIVE_BINDING_SOURCE,
            confidence="observed",
            metadata=metadata,
            path=registry_path or None,
        )
    except Exception:
        return {}
    return result if isinstance(result, dict) and result.get("ok") else {}


def _memory_scope_for_request(event: dict[str, Any]) -> str:
    if _explicit_project_anchor(event):
        return "active"
    if str(event.get("canonical_window_id") or "").strip():
        return "window"
    return "active"


def build_preflight_request(
    event: dict[str, Any],
    *,
    consumer: str,
    limit: int,
    excerpt_chars: int,
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, Any]:
    event_session_id = str(event.get("session_id") or "").strip()
    registry_binding = _current_window_binding_from_registry(
        event_session_id=event_session_id,
        registry_path=registry_path,
        binding_key=binding_key,
    )
    live_registration = {}
    if not registry_binding:
        live_registration = _self_register_live_window_binding(
            event,
            registry_path=registry_path,
        )
        if live_registration:
            registry_binding = _current_window_binding_from_registry(
                event_session_id=event_session_id,
                registry_path=registry_path,
                binding_key=binding_key,
            )
    has_registry_binding = bool(registry_binding)
    registry_project_root = _binding_text(registry_binding, "project_root", "workspace_root", "cwd")
    registry_project_id = _binding_text(registry_binding, "project_id")
    session_id = (
        event_session_id
        if _has_strong_anchor(event)
        else str(registry_binding.get("session_id") or "").strip()
        if has_registry_binding
        else ""
    )
    transcript_path = str(event.get("transcript_path") or "").strip()
    canonical_window_id = str(
        event.get("canonical_window_id")
        or registry_binding.get("canonical_window_id")
        or ""
    ).strip()
    explicit_event_project_root = _explicit_text(event, "project_root", "workspace_root")
    event_cwd = _explicit_text(event, "cwd")
    if explicit_event_project_root:
        project_root = explicit_event_project_root
    elif live_registration:
        project_root = event_cwd or registry_project_root
    elif registry_project_root:
        project_root = registry_project_root
    else:
        project_root = event_cwd
    project_id = (
        _explicit_text(event, "project_id")
        or registry_project_id
        or _project_id_from_path(project_root)
    )
    workstream_id = _explicit_text(event, "workstream_id", "workstream") or _binding_text(registry_binding, "workstream_id", "workstream")
    task_id = _explicit_text(event, "task_id", "task") or _binding_text(registry_binding, "task_id", "task")
    event_for_scope = {
        **event,
        "canonical_window_id": canonical_window_id,
        "project_id": project_id,
        "project_root": project_root,
    }
    return {
        "query": str(event.get("prompt") or ""),
        "mode": "preflight",
        "consumer": consumer,
        "request_id": f"claude-code-hook-{event_session_id}" if event_session_id else "claude-code-hook",
        "source_system": SOURCE_SYSTEM,
        "session_id": session_id,
        "canonical_window_id": canonical_window_id,
        "project_id": project_id,
        "project_root": project_root,
        "workstream_id": workstream_id,
        "task_id": task_id,
        "memory_scope": _memory_scope_for_request(event_for_scope),
        "fast_preflight_miss_policy": "return_without_cold_recall",
        "limit": limit,
        "excerpt_chars": excerpt_chars,
        "hook_event_name": str(event.get("hook_event_name") or "UserPromptSubmit"),
        "transcript_path": transcript_path,
        "window_binding_key": str(registry_binding.get("binding_key") or ""),
        "window_binding_source": str(registry_binding.get("binding_source") or ""),
        "window_binding_registered": bool(live_registration),
    }


def call_preflight(endpoint: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    return data if isinstance(data, dict) else {}


def _surface_line(item: dict[str, Any]) -> str:
    parts = []
    library_id = _compact(item.get("library_id"), 80)
    shelf = _compact(item.get("library_shelf"), 40)
    title = _compact(item.get("title") or item.get("summary"), 140)
    summary = _compact(item.get("summary"), 240)
    if library_id:
        parts.append(library_id)
    if shelf:
        parts.append(shelf)
    label = " / ".join(parts) if parts else "source-backed memory"
    line = f"- {label}: {title}"
    if summary and summary != title:
        line += f" | {summary}"
    why = _compact(item.get("why_surface"), 160)
    if why:
        line += f" | why: {why}"
    source = _compact(item.get("source_path") or item.get("source_system"), 180)
    if source:
        line += f" | source: {source}"
    return line


def build_additional_context(payload: dict[str, Any], *, max_chars: int = DEFAULT_MAX_CONTEXT_CHARS) -> str:
    if not isinstance(payload, dict):
        return ""
    if payload.get("decision") != "surface" and not payload.get("should_surface"):
        return ""
    surfaces = payload.get("must_surface") if isinstance(payload.get("must_surface"), list) else []
    if not surfaces:
        return ""

    lines = [
        "Time Library preflight is source-backed and read-only.",
        (
            "Use this before answering; do not quote or expose raw excerpts. "
            f"decision={payload.get('decision')}; "
            f"auto_entry={payload.get('auto_entry_state') or 'enter'}; "
            f"next_action={payload.get('next_action') or 'apply_must_surface_before_answer'}; "
            f"prompt_class={payload.get('prompt_class')}; "
            f"confidence={payload.get('confidence')}"
        ),
        "Surface anchors:",
    ]
    for item in surfaces[:3]:
        if isinstance(item, dict):
            lines.append(_surface_line(item))
    do_not_repeat = [
        _compact(item, 180)
        for item in (payload.get("do_not_repeat") or [])
        if str(item or "").strip()
    ][:6]
    if do_not_repeat:
        lines.append("Do not repeat:")
        lines.extend(f"- {item}" for item in do_not_repeat)
    checks = [
        _compact(item, 180)
        for item in (payload.get("acceptance_checks") or [])
        if str(item or "").strip()
    ][:6]
    if checks:
        lines.append("Acceptance checks:")
        lines.extend(f"- {item}" for item in checks)

    text = "\n".join(lines).strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "..."


def hook_output(additional_context: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional_context,
        }
    }


def run(event_text: str, args: argparse.Namespace) -> int:
    event = _load_event(event_text)
    if str(event.get("hook_event_name") or "UserPromptSubmit") != "UserPromptSubmit":
        return 0
    payload = build_preflight_request(
        event,
        consumer=args.consumer,
        limit=args.limit,
        excerpt_chars=args.excerpt_chars,
        registry_path=getattr(args, "window_binding_registry", ""),
        binding_key=getattr(args, "binding_key", ""),
    )
    if not payload.get("query"):
        return 0
    try:
        try:
            endpoint = resolve_client_url(
                "/api/v1/raw/query",
                endpoint=args.endpoint,
                root=os.environ.get("MEMCORE_ROOT"),
            )
        except RuntimeError:
            return 0
        result = call_preflight(endpoint, payload, timeout=args.timeout)
        context = build_additional_context(result, max_chars=args.max_context_chars)
    except Exception as exc:
        if args.debug:
            print(f"time-library preflight hook skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    if not context:
        return 0
    print(json.dumps(hook_output(context), ensure_ascii=False, separators=(",", ":")))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code UserPromptSubmit preflight hook.")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("MEMCORE_PREFLIGHT_ENDPOINT", DEFAULT_ENDPOINT),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_number_from_env("MEMCORE_PREFLIGHT_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
    )
    parser.add_argument("--consumer", default=os.environ.get("MEMCORE_PREFLIGHT_CONSUMER", "claude_code_hook"))
    parser.add_argument("--limit", type=int, default=_int_from_env("MEMCORE_PREFLIGHT_LIMIT", 3))
    parser.add_argument("--excerpt-chars", type=int, default=_int_from_env("MEMCORE_PREFLIGHT_EXCERPT_CHARS", 160))
    parser.add_argument(
        "--max-context-chars",
        type=int,
        default=_int_from_env("MEMCORE_PREFLIGHT_MAX_CONTEXT_CHARS", DEFAULT_MAX_CONTEXT_CHARS),
    )
    parser.add_argument(
        "--window-binding-registry",
        default=os.environ.get("MEMCORE_WINDOW_BINDING_REGISTRY", ""),
    )
    parser.add_argument(
        "--binding-key",
        default=os.environ.get("MEMCORE_CLAUDE_CODE_BINDING_KEY", ""),
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(sys.stdin.read(), args))


if __name__ == "__main__":
    main()
