"""Read-only previews for automatic agent event reminders.
This module does not install hooks or write project files. It describes useful
moments where an AI tool can remind itself to ask Time Library before
losing work context.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from platform_thin_adapter_registry import (
        CAPABILITY_CHECK_PAYLOAD,
        MEMCORE_MCP_HTTP_URL,
        MEMCORE_MCP_SERVER_NAME,
        MEMCORE_MCP_TOOL_NAME,
    )
except Exception:  # pragma: no cover - keeps this module importable in isolation.
    CAPABILITY_CHECK_PAYLOAD = {"query": "capability check", "mode": "capability_check"}
    MEMCORE_MCP_HTTP_URL = "http://127.0.0.1:9851/mcp"
    MEMCORE_MCP_SERVER_NAME = "time-library"
    MEMCORE_MCP_TOOL_NAME = "time_library_recall"


AGENT_EVENT_TRIGGER_PREVIEW_CONTRACT = "agent_event_trigger_preview.v1"
COMMON_MOMENTS = [
    "new_session",
    "before_agent_answers",
    "before_tool_use",
    "after_tool_use",
    "before_context_compact",
    "session_end",
]

SOURCE_BASIS = [
    {
        "name": "Claude Code hooks",
        "url": "https://code.claude.com/docs/en/hooks",
    },
    {
        "name": "Gemini CLI hooks",
        "url": "https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/writing-hooks.md",
    },
    {
        "name": "Gemini CLI hook settings",
        "url": "https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md",
    },
    {
        "name": "Cursor rules",
        "url": "https://docs.cursor.com/context/rules",
    },
]


def ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normal_project_root(project_root: str | Path | None) -> Path | None:
    if not project_root:
        return None
    return Path(project_root).expanduser().resolve(strict=False)


def _project_path(project_root: Path | None, relative_path: str) -> str:
    if project_root is None:
        return relative_path
    return str(project_root / relative_path)


def _moment(
    *,
    moment: str,
    platform_event: str,
    user_value: str,
    memcore_action: str,
    recommended: bool = True,
) -> dict[str, Any]:
    return {
        "moment": moment,
        "platform_event": platform_event,
        "user_value": user_value,
        "memcore_action": memcore_action,
        "recommended": recommended,
        "would_write": False,
        "real_recall_by_default": False,
        "content_reads_performed": False,
        "chat_body_included": False,
        "raw_excerpt_included": False,
        "model_call_performed": False,
    }


def _platform(
    *,
    system: str,
    display_name: str,
    target_paths: list[str],
    native_event_support: bool,
    moments: list[dict[str, Any]],
    setup_hint: str,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "system": system,
        "display_name": display_name,
        "native_event_support": native_event_support,
        "target_paths": target_paths,
        "moment_count": len(moments),
        "moments": moments,
        "setup_hint": setup_hint,
        "mcp_server_name": MEMCORE_MCP_SERVER_NAME,
        "mcp_url": MEMCORE_MCP_HTTP_URL,
        "tool_name": MEMCORE_MCP_TOOL_NAME,
        "writes_by_default": False,
        "would_write": False,
        "content_reads_performed": False,
        "chat_body_included": False,
        "raw_excerpt_included": False,
        "model_call_performed": False,
        "api_key_included": False,
        "notes": notes or [],
    }


def _claude_code(project_root: Path | None) -> dict[str, Any]:
    return _platform(
        system="claude_code",
        display_name="Claude Code",
        native_event_support=True,
        target_paths=[
            _project_path(project_root, ".claude/settings.json"),
            _project_path(project_root, ".claude/settings.local.json"),
            "~/.claude/settings.json",
        ],
        moments=[
            _moment(
                moment="new_session",
                platform_event="SessionStart",
                user_value="A new Claude Code window starts with the memory rule already fresh.",
                memcore_action="Check the local Time Library connection and remind the agent when old work may matter.",
            ),
            _moment(
                moment="before_agent_answers",
                platform_event="UserPromptSubmit",
                user_value="Short follow-ups like 'next step' or 'what else' can trigger a memory check before the answer.",
                memcore_action="Classify the prompt as memory-dependent or ordinary.",
            ),
            _moment(
                moment="before_tool_use",
                platform_event="PreToolUse",
                user_value="Before a risky or project-changing action, the agent can ask whether there is old context to respect.",
                memcore_action="Remind the agent to check project boundaries and prior corrections.",
            ),
            _moment(
                moment="after_tool_use",
                platform_event="PostToolUse",
                user_value="After edits or commands, the local watcher can catch up instead of waiting for a manual scan.",
                memcore_action="Signal local capture and health status.",
            ),
            _moment(
                moment="before_context_compact",
                platform_event="PreCompact",
                user_value="Before context is compressed, important source-backed pointers can be kept visible.",
                memcore_action="Prepare a compact memory reminder without replacing original records.",
            ),
            _moment(
                moment="session_end",
                platform_event="SessionEnd",
                user_value="When the session ends, missed records can be caught up.",
                memcore_action="Nudge the local watcher to run a catch-up check.",
            ),
        ],
        setup_hint="Claude Code can define lifecycle events in user or project settings.",
    )


def _gemini_cli(project_root: Path | None) -> dict[str, Any]:
    return _platform(
        system="gemini_cli",
        display_name="Gemini CLI",
        native_event_support=True,
        target_paths=[
            _project_path(project_root, ".gemini/settings.json"),
            _project_path(project_root, ".gemini/hooks/"),
            _project_path(project_root, ".gemini/extensions/time-library/hooks/hooks.json"),
        ],
        moments=[
            _moment(
                moment="new_session",
                platform_event="SessionStart",
                user_value="A Gemini CLI session can start with the same memory habit as other tools.",
                memcore_action="Check that Time Library is reachable and ready.",
            ),
            _moment(
                moment="before_agent_answers",
                platform_event="BeforeAgent",
                user_value="Before the agent loop starts, it can be reminded to ask Time Library for old work when needed.",
                memcore_action="Add a small context reminder rather than a full recall.",
            ),
            _moment(
                moment="before_tool_use",
                platform_event="BeforeTool",
                user_value="Before a write or shell command, old project boundaries can be checked.",
                memcore_action="Route the moment to project-boundary recall when the user has asked for memory help.",
            ),
            _moment(
                moment="after_tool_use",
                platform_event="AfterTool",
                user_value="After tool work, Time Library can keep the local timeline warm.",
                memcore_action="Trigger local capture catch-up.",
            ),
            _moment(
                moment="before_context_compact",
                platform_event="PreCompress",
                user_value="Before conversation compression, the agent can keep the important memory route visible.",
                memcore_action="Prepare source-backed pointers for the next turn.",
            ),
            _moment(
                moment="session_end",
                platform_event="SessionEnd",
                user_value="When the session ends, the local record can be consolidated.",
                memcore_action="Run catch-up without replacing source records.",
            ),
        ],
        setup_hint="Gemini CLI supports project settings and extension-packaged hooks.",
    )


def _codex(project_root: Path | None) -> dict[str, Any]:
    return _platform(
        system="codex",
        display_name="Codex",
        native_event_support=False,
        target_paths=[
            _project_path(project_root, "AGENTS.md"),
            "~/.codex/config.toml",
        ],
        moments=[
            _moment(
                moment="new_session",
                platform_event="AGENTS.md loaded",
                user_value="Codex can start with the memory rule in its project instructions.",
                memcore_action="Use the standing Time Library rule and the existing MCP connection.",
            ),
            _moment(
                moment="before_agent_answers",
                platform_event="prompt instruction",
                user_value="When the user asks a follow-up, Codex can call Time Library before answering.",
                memcore_action="Use current-window recall first.",
            ),
            _moment(
                moment="after_tool_use",
                platform_event="local watcher",
                user_value="After commands or edits, Time Library can still capture local session records through its watcher.",
                memcore_action="Let the local watcher catch up independently of Codex MCP.",
            ),
        ],
        setup_hint="Codex is handled through AGENTS.md, MCP, and the local Time Library watcher rather than a native hook file.",
        notes=["Native hook support is not assumed for Codex in this preview."],
    )


def _cursor(project_root: Path | None) -> dict[str, Any]:
    return _platform(
        system="cursor",
        display_name="Cursor",
        native_event_support=False,
        target_paths=[
            _project_path(project_root, ".cursor/rules/time-library.mdc"),
            _project_path(project_root, "AGENTS.md"),
        ],
        moments=[
            _moment(
                moment="new_session",
                platform_event="project rule loaded",
                user_value="Cursor can keep the memory habit in project rules.",
                memcore_action="Tell the agent when to ask Time Library.",
            ),
            _moment(
                moment="before_agent_answers",
                platform_event="rule instruction",
                user_value="Old decisions and short follow-ups can be routed to Time Library first.",
                memcore_action="Use the active recall order before answering.",
            ),
            _moment(
                moment="after_tool_use",
                platform_event="local watcher",
                user_value="Time Library can still follow local records even when Cursor only provides rules.",
                memcore_action="Use continuous local capture.",
            ),
        ],
        setup_hint="Cursor uses project rules and can also read AGENTS.md.",
    )


def _windsurf(project_root: Path | None) -> dict[str, Any]:
    return _platform(
        system="windsurf",
        display_name="Windsurf",
        native_event_support=False,
        target_paths=[
            _project_path(project_root, ".devin/rules/time-library.md"),
            _project_path(project_root, ".windsurf/rules/time-library.md"),
            _project_path(project_root, ".windsurf/workflows/time-library-recall.md"),
        ],
        moments=[
            _moment(
                moment="new_session",
                platform_event="workspace rule loaded",
                user_value="Windsurf can start with a simple memory rule for this workspace.",
                memcore_action="Keep the standing Time Library rule visible.",
            ),
            _moment(
                moment="before_agent_answers",
                platform_event="workflow or rule instruction",
                user_value="The agent can ask Time Library before answering old-context questions.",
                memcore_action="Use source-backed recall when the user asks to continue.",
            ),
            _moment(
                moment="session_end",
                platform_event="local watcher",
                user_value="The local service can catch up after the work pauses.",
                memcore_action="Use watcher catch-up rather than a one-time scan.",
            ),
        ],
        setup_hint="Windsurf is represented as rules and workflows until a verified native event surface is available.",
    )


def build_agent_event_triggers_preview(project_root: str | Path | None = None) -> dict[str, Any]:
    root = _normal_project_root(project_root)
    platforms = [
        _claude_code(root),
        _gemini_cli(root),
        _codex(root),
        _cursor(root),
        _windsurf(root),
    ]
    moment_count = sum(item["moment_count"] for item in platforms)
    native_count = sum(1 for item in platforms if item["native_event_support"])
    return {
        "ok": True,
        "contract": AGENT_EVENT_TRIGGER_PREVIEW_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "content_reads_performed": False,
        "chat_body_included": False,
        "raw_excerpt_included": False,
        "model_call_performed": False,
        "api_key_included": False,
        "project_root": str(root) if root else "",
        "mcp_server_name": MEMCORE_MCP_SERVER_NAME,
        "mcp_url": MEMCORE_MCP_HTTP_URL,
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        "common_moments": COMMON_MOMENTS,
        "summary": {
            "platform_count": len(platforms),
            "native_event_platform_count": native_count,
            "moment_count": moment_count,
            "writes_planned": 0,
            "model_calls_planned": 0,
        },
        "global_guarantees": {
            "does_not_write_project_files": True,
            "does_not_read_chat_bodies": True,
            "does_not_call_model": True,
            "does_not_store_api_keys": True,
            "real_recall_requires_agent_or_user_intent": True,
            "watcher_remains_continuous_not_install_scan_only": True,
        },
        "platforms": platforms,
        "source_basis": SOURCE_BASIS,
    }
