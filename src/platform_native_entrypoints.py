"""Dry-run previews for native agent instruction entry points.

The preview shows where Time Library instructions would fit in popular
agent surfaces without writing project files, reading chat bodies, or calling a
model.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from src.memcore_version import SERVICE_VERSION
except Exception:  # pragma: no cover - direct script import fallback
    from memcore_version import SERVICE_VERSION
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


NATIVE_ENTRYPOINT_PREVIEW_CONTRACT = "agent_native_entrypoints_preview.v1"
ACTIVE_RECALL_ORDER = [
    "current_window_session",
    "same_project_workspace",
    "same_workstream_task",
    "stable_user_preferences_tool_facts",
    "explicit_raw_pool_global_only_when_requested",
]

SOURCE_BASIS = [
    {
        "name": "Codex AGENTS.md",
        "url": "https://github.com/openai/codex/blob/main/docs/agents_md.md",
    },
    {
        "name": "Claude Code CLAUDE.md and rules",
        "url": "https://code.claude.com/docs/en/memory",
    },
    {
        "name": "Gemini CLI extensions",
        "url": "https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md",
    },
    {
        "name": "Gemini CLI MCP settings",
        "url": "https://google-gemini.github.io/gemini-cli/docs/tools/mcp-server.html",
    },
    {
        "name": "GitHub Copilot custom agents",
        "url": "https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-custom-agents",
    },
    {
        "name": "GitHub Copilot custom instructions",
        "url": "https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions",
    },
    {
        "name": "Cursor rules",
        "url": "https://docs.cursor.com/context/rules",
    },
    {
        "name": "Windsurf memories and rules",
        "url": "https://docs.windsurf.com/windsurf/cascade/memories",
    },
]


def ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _project_path(project_root: Path | None, relative_path: str) -> str:
    if project_root is None:
        return relative_path
    return str(project_root / relative_path)


def _normal_project_root(project_root: str | Path | None) -> Path | None:
    if not project_root:
        return None
    return Path(project_root).expanduser().resolve(strict=False)


def _json_block(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _standing_memory_rule(agent_name: str) -> str:
    capability = json.dumps(CAPABILITY_CHECK_PAYLOAD, ensure_ascii=False, separators=(",", ":"))
    return f"""# Time Library

Use Time Library as the standing memory rule for {agent_name}.

Before answering questions that depend on prior work, previous decisions, corrections, project status, install/test/release state, or short follow-ups such as "next step", "what else", or "then what", call `{MEMCORE_MCP_TOOL_NAME}`.

When checking the connection, run capability check first and do not recall real memory:

```json
{capability}
```

Normal recall order:

1. current window/session
2. same project/workspace
3. same workstream/task
4. stable user preferences and tool facts
5. raw-pool/global only when the user explicitly requests it

Use source refs and raw excerpts as evidence. Summaries are hints, not replacements for original records. If `{MEMCORE_MCP_SERVER_NAME}` or `{MEMCORE_MCP_TOOL_NAME}` is unavailable, try legacy `zhiyi_recall` during migration; if neither works, say the memory connection is unavailable instead of guessing from stale context.
"""


def _file(
    project_root: Path | None,
    relative_path: str,
    content: str,
    *,
    file_format: str,
    purpose: str,
    include_content: bool,
) -> dict[str, Any]:
    result = {
        "target_path": _project_path(project_root, relative_path),
        "relative_path": relative_path,
        "format": file_format,
        "purpose": purpose,
        "would_write": False,
        "content_reads_performed": False,
        "chat_body_included": False,
        "raw_excerpt_included": False,
    }
    if include_content:
        result["preview_content"] = content
    return result


def _entry(
    *,
    system: str,
    display_name: str,
    entrypoint_kind: str,
    files: list[dict[str, Any]],
    supports_mcp_reference: bool,
    mcp_connection_mode: str,
    status: str = "preview_ready",
    safe_next_step: str = "Review the preview and apply it from the target agent's own instruction UI or project files.",
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "system": system,
        "display_name": display_name,
        "entrypoint_kind": entrypoint_kind,
        "status": status,
        "supports_mcp_reference": supports_mcp_reference,
        "mcp_connection_mode": mcp_connection_mode,
        "mcp_server_name": MEMCORE_MCP_SERVER_NAME,
        "mcp_url": MEMCORE_MCP_HTTP_URL,
        "tool_name": MEMCORE_MCP_TOOL_NAME,
        "target_paths": [file["target_path"] for file in files],
        "files": files,
        "writes_by_default": False,
        "would_write": False,
        "content_reads_performed": False,
        "chat_body_included": False,
        "raw_excerpt_included": False,
        "model_call_performed": False,
        "api_key_included": False,
        "safe_next_step": safe_next_step,
        "notes": notes or [],
    }


def _codex_entry(project_root: Path | None, include_content: bool) -> dict[str, Any]:
    content = _standing_memory_rule("Codex")
    files = [
        _file(
            project_root,
            "AGENTS.md",
            content,
            file_format="markdown",
            purpose="Project instruction file read by Codex and other agents that honor AGENTS.md.",
            include_content=include_content,
        )
    ]
    return _entry(
        system="codex",
        display_name="Codex",
        entrypoint_kind="project_instruction",
        files=files,
        supports_mcp_reference=True,
        mcp_connection_mode="use_existing_codex_mcp_config",
        safe_next_step="Put this in AGENTS.md when you want Codex to remember to call Time Library for prior-context questions.",
    )


def _claude_code_entry(project_root: Path | None, include_content: bool) -> dict[str, Any]:
    content = _standing_memory_rule("Claude Code")
    files = [
        _file(
            project_root,
            "CLAUDE.md",
            content,
            file_format="markdown",
            purpose="Project instruction file loaded by Claude Code at session start.",
            include_content=include_content,
        ),
        _file(
            project_root,
            ".claude/rules/time-library.md",
            content,
            file_format="markdown",
            purpose="Optional Claude Code rule for larger projects that keep instructions under .claude/rules.",
            include_content=include_content,
        ),
    ]
    return _entry(
        system="claude_code",
        display_name="Claude Code",
        entrypoint_kind="project_memory_or_rule",
        files=files,
        supports_mcp_reference=True,
        mcp_connection_mode="use_existing_claude_mcp_config_and_user_prompt_submit_hook",
        safe_next_step="First check whether Time Library is already installed and reachable on this machine; if it is, skip reinstall and only connect the Claude Code MCP plus UserPromptSubmit hook.",
        notes=[
            "Install once awareness: if 9851 is already healthy, skip reinstall and connect only Claude Code surfaces.",
            "Claude Code native delivery shape is UserPromptSubmit hook plus MCP.",
        ],
    )


def _gemini_cli_entry(project_root: Path | None, include_content: bool) -> dict[str, Any]:
    manifest = {
        "name": "time-library",
        "version": SERVICE_VERSION,
        "description": "Use Time Library as source-backed local memory.",
        "contextFileName": "GEMINI.md",
        "mcpServers": {
            MEMCORE_MCP_SERVER_NAME: {
                "httpUrl": MEMCORE_MCP_HTTP_URL,
                "timeout": 5000,
            }
        },
    }
    files = [
        _file(
            project_root,
            ".gemini/extensions/time-library/gemini-extension.json",
            _json_block(manifest),
            file_format="json",
            purpose="Gemini CLI extension manifest with context and local HTTP MCP settings.",
            include_content=include_content,
        ),
        _file(
            project_root,
            ".gemini/extensions/time-library/GEMINI.md",
            _standing_memory_rule("Gemini CLI"),
            file_format="markdown",
            purpose="Gemini CLI extension context file.",
            include_content=include_content,
        ),
    ]
    return _entry(
        system="gemini_cli",
        display_name="Gemini CLI",
        entrypoint_kind="extension_manifest_and_context",
        files=files,
        supports_mcp_reference=True,
        mcp_connection_mode="extension_mcp_http_preview",
        safe_next_step="First check whether Time Library is already installed and reachable on this machine; if it is, skip reinstall and only link this Gemini extension plus MCP.",
    )


def _github_copilot_entry(project_root: Path | None, include_content: bool) -> dict[str, Any]:
    agent_profile = f"""---
name: time-library
description: Use source-backed local memory before answering questions that depend on previous work.
---

{_standing_memory_rule("GitHub Copilot").strip()}

If Copilot is running in a cloud environment that cannot reach localhost, report that the local Time Library service is not reachable from that environment.
"""
    repo_instruction = _standing_memory_rule("GitHub Copilot")
    files = [
        _file(
            project_root,
            ".github/agents/time-library.md",
            agent_profile,
            file_format="markdown_with_yaml_frontmatter",
            purpose="Copilot custom agent profile.",
            include_content=include_content,
        ),
        _file(
            project_root,
            ".github/copilot-instructions.md",
            repo_instruction,
            file_format="markdown",
            purpose="Repository-wide Copilot instruction fallback.",
            include_content=include_content,
        ),
    ]
    return _entry(
        system="github_copilot",
        display_name="GitHub Copilot",
        entrypoint_kind="custom_agent_or_repository_instruction",
        files=files,
        supports_mcp_reference=True,
        mcp_connection_mode="external_mcp_config_required",
        safe_next_step="Use the agent profile for Copilot agent workflows and keep local MCP reachability explicit.",
        notes=["Cloud-hosted agents may not be able to reach a local 127.0.0.1 service."],
    )


def _cursor_entry(project_root: Path | None, include_content: bool) -> dict[str, Any]:
    content = f"""---
description: Use Time Library for source-backed local memory before prior-context answers.
globs:
alwaysApply: true
---

{_standing_memory_rule("Cursor").strip()}
"""
    files = [
        _file(
            project_root,
            ".cursor/rules/time-library.mdc",
            content,
            file_format="mdc",
            purpose="Cursor project rule.",
            include_content=include_content,
        )
    ]
    return _entry(
        system="cursor",
        display_name="Cursor",
        entrypoint_kind="project_rule",
        files=files,
        supports_mcp_reference=True,
        mcp_connection_mode="use_existing_cursor_mcp_config",
        safe_next_step="First check whether Time Library is already installed and reachable on this machine; if it is, skip reinstall and only add the Cursor rule plus MCP connection.",
    )


def _windsurf_entry(project_root: Path | None, include_content: bool) -> dict[str, Any]:
    rule_content = _standing_memory_rule("Windsurf Cascade")
    workflow_content = f"""# Time Library Recall

Use this workflow when the user asks to continue from prior work.

1. Check whether `{MEMCORE_MCP_SERVER_NAME}` and `{MEMCORE_MCP_TOOL_NAME}` are available.
2. If this is only a connection check, call capability check with:

```json
{json.dumps(CAPABILITY_CHECK_PAYLOAD, ensure_ascii=False)}
```

3. For real prior-context questions, call `{MEMCORE_MCP_TOOL_NAME}` and answer from source refs or raw excerpts.
4. Keep raw-pool/global recall behind explicit user permission.
"""
    files = [
        _file(
            project_root,
            ".devin/rules/time-library.md",
            rule_content,
            file_format="markdown",
            purpose="Windsurf/Devin workspace rule preview.",
            include_content=include_content,
        ),
        _file(
            project_root,
            ".windsurf/rules/time-library.md",
            rule_content,
            file_format="markdown",
            purpose="Legacy Windsurf workspace rule fallback.",
            include_content=include_content,
        ),
        _file(
            project_root,
            ".windsurf/workflows/time-library-recall.md",
            workflow_content,
            file_format="markdown",
            purpose="Optional Windsurf workflow preview for manual recall checks.",
            include_content=include_content,
        ),
    ]
    return _entry(
        system="windsurf",
        display_name="Windsurf",
        entrypoint_kind="rule_and_workflow",
        files=files,
        supports_mcp_reference=True,
        mcp_connection_mode="use_existing_windsurf_mcp_config",
        safe_next_step="First check whether Time Library is already installed and reachable on this machine; if it is, skip reinstall and only connect Windsurf/Devin rule surfaces plus MCP.",
    )


def build_agent_native_entrypoints_preview(
    project_root: str | Path | None = None,
    *,
    include_content: bool = True,
) -> dict[str, Any]:
    root = _normal_project_root(project_root)
    entrypoints = [
        _codex_entry(root, include_content),
        _claude_code_entry(root, include_content),
        _gemini_cli_entry(root, include_content),
        _github_copilot_entry(root, include_content),
        _cursor_entry(root, include_content),
        _windsurf_entry(root, include_content),
    ]
    return {
        "ok": True,
        "contract": NATIVE_ENTRYPOINT_PREVIEW_CONTRACT,
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
        "active_recall_order": ACTIVE_RECALL_ORDER,
        "global_guarantees": {
            "does_not_write_project_files": True,
            "does_not_read_project_files": True,
            "does_not_read_chat_bodies": True,
            "does_not_call_model": True,
            "does_not_store_api_keys": True,
            "capability_check_is_no_recall": True,
            "raw_source_text_remains_source_of_truth": True,
        },
        "summary": {
            "entrypoint_count": len(entrypoints),
            "file_preview_count": sum(len(item["files"]) for item in entrypoints),
            "ready_count": sum(1 for item in entrypoints if item["status"] == "preview_ready"),
            "writes_planned": 0,
            "model_calls_planned": 0,
        },
        "entrypoints": entrypoints,
        "source_basis": SOURCE_BASIS,
    }
