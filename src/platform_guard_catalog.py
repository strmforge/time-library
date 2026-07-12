#!/usr/bin/env python3
"""Platform Guard catalog, storage patterns, and local metadata probes under Tiandao."""

from __future__ import annotations

import os
import glob
import json
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

UTC = timezone.utc

PLATFORM_GUARD_CATALOG_CONTRACT = "tiandao_platform_guard_catalog.v1"


def get_platform_guard_catalog_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": PLATFORM_GUARD_CATALOG_CONTRACT,
        "zh_name": "平台守护目录与存储规则",
        "en_name": "Platform Guard Catalog",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "workbench_id": "platform_guard",
        "console_layer": "platform_guard_catalog",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "catalog_and_storage_patterns_identify_inlets_but_do_not_replace_time_origin",
    }


REGISTRY_CONTRACT = "thin_adapter_registry.v1"
AUTOCONNECT_DRY_RUN_CONTRACT = "authorized_auto_connect_dry_run.v1"
AUTOCONNECT_APPLY_GATE_CONTRACT = "authorized_auto_connect_apply_gate.v1"
AUTOCONNECT_APPLY_CONTRACT = "authorized_auto_connect_apply.v1"
DISCOVERY_DASHBOARD_CONTRACT = "platform_discovery_dashboard.v1"
PLATFORM_CATALOG_CONTRACT = "platform_catalog.v1"
PLATFORM_STORAGE_PATTERNS_CONTRACT = "platform_storage_patterns.v2026.6.20"
PACKAGE_MANAGER_INVENTORY_CONTRACT = "package_manager_agent_inventory.v1"
MODEL_IDENTIFICATION_CONTRACT = "local_ai_tool_model_identification.v1"
PROVISIONAL_ADAPTER_CANDIDATE_CONTRACT = "provisional_adapter_candidates.v1"
ADAPTER_DRAFT_CONTRACT = "local_ai_tool_adapter_draft.v1"

try:
    from src.platform_guard_package_inventory import *
except ImportError:  # pragma: no cover
    from platform_guard_package_inventory import *

INTENT_SIGNAL_RE = re.compile(r"(memcore|time[-_ ]?library|time_library|时间图书馆|zhiyi|知意)", re.I)
SENSITIVE_KEY_RE = re.compile(r"(key|token|secret|password|auth|credential|cookie)", re.I)
MCP_SECTION_RE = re.compile(r"\[\s*(?:mcpServers|mcp_servers)\.([^\]]+)\]", re.I)
SAFE_CONFIG_FILENAMES = {
    "mcp.json",
    "mcp_settings.json",
    "settings.json",
    "config.json",
    "config.yaml",
    "config.yml",
    "config.toml",
    "claude_desktop_config.json",
}
GENERIC_DISCOVERY_CONTRACT = "generic_local_ai_surface_discovery.v1"
GENERIC_CONFIG_FILENAMES = SAFE_CONFIG_FILENAMES | {"mcp.json"}
GENERIC_CONFIG_SUFFIXES = {".json", ".toml", ".yaml", ".yml"}
GENERIC_WORKSPACE_MARKER_DIRS = {
    "agent",
    "agents",
    "chat",
    "chats",
    "conversations",
    "history",
    "memory",
    "memories",
    "sessions",
    "specs",
    "workspace-sessions",
}
GENERIC_CONTEXT_DIR_NAMES = {
    "appdata",
    "application data",
    "desktop",
    "documents",
    "local",
    "local settings",
    "localcache",
    "packages",
    "projects",
    "roaming",
    "user",
    "users",
    "workspace",
}
GENERIC_DISCOVERY_BRANCH_NAMES = GENERIC_CONTEXT_DIR_NAMES | {
    ".codeium",
    ".config",
    ".local",
    "app support",
    "application support",
    "cascadeprojects",
    "downloads",
    "globalstorage",
    "localappdata",
    "programs",
    "roaming",
    "settings",
    "workspaceStorage".lower(),
}
LOCAL_AI_NOISE_DIR_TOKENS = {
    ".bak",
    ".backup",
    "backup",
    "backups",
    "bak",
    "cache",
    "disabled-test",
    "installer",
    "old",
    "periodic-maintenance-backup-disabled-test",
    "sync-enabled-disabled-test",
    "sync-enabled-ok-test",
    "sync-error-status-test",
    "test",
    "tmp",
    "updater",
}
LOCAL_INFRASTRUCTURE_SURFACE_IDS = {
    "docker",
    "git",
    "github",
    "ssh",
}
LOCAL_AI_SURFACE_TOKEN_RE = re.compile(
    r"(^|[._@+\-\s])("
    r"cc[-_\s]?switch|claude|clawui|claw|codebuddy|codex|copilot|cursor|"
    r"deepseek|gemini|hermes|kiro|mcp|mcporter|minimax|ollama|openclaw|"
    r"opencode|exampletool|reasonix|roo|windsurf|workbuddy"
    r")([._+\-\s]|$)",
    re.I,
)
LOCAL_AI_PROJECT_ARTIFACT_RE = re.compile(
    r"("
    r"aether[-_\s]?codex[-_\s]?review|"
    r"enquire[-_\s]?mcp|"
    r"memcore[-_\s].*(claude[-_\s]?src|verify)|"
    r"ntm[-_\s]?codex[-_\s]?(crew[-_\s]?run[-_\s]?smoke|runtime[-_\s]?jobs)"
    r")",
    re.I,
)
APP_BUNDLE_NAMES = {
    "claude_desktop": ("Claude.app",),
    "codex": ("Codex.app",),
    "cursor": ("Cursor.app",),
    "kiro": ("Kiro.app",),
    "continue": ("Continue.app",),
    "windsurf": ("Windsurf.app",),
}
CLI_VERSION_COMMANDS = {
    "claude_code_cli": ("claude", "--version"),
}
GENERIC_SKIP_DIRS = {
    ".cache",
    ".git",
    ".npm",
    ".venv",
    "__pycache__",
    "node_modules",
    "Library",
    "Pictures",
    "Movies",
    "Music",
}
COMPOSE_FILENAMES = {
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
}
AUTOCONNECT_TARGET_PATTERNS = {
    "codex": ("$CODEX_HOME/config.toml", "~/.codex/config.toml"),
    "claude_desktop": (
        "$CLAUDE_DESKTOP_HOME/claude_desktop_config.json",
        "~/Library/Application Support/Claude/claude_desktop_config.json",
        "$APPDATA/Claude/claude_desktop_config.json",
        "$LOCALAPPDATA/Claude/claude_desktop_config.json",
    ),
    "claude_code_cli": ("~/.claude.json", "$CLAUDE_PROJECT_DIR/.mcp.json", ".mcp.json"),
    "cursor": ("~/.cursor/mcp.json",),
    "continue": ("~/.continue/config.json",),
    "roo_code": (
        "~/Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline/mcp_settings.json",
        "$APPDATA/Code/User/globalStorage/rooveterinaryinc.roo-cline/mcp_settings.json",
        "$XDG_CONFIG_HOME/Code/User/globalStorage/rooveterinaryinc.roo-cline/mcp_settings.json",
    ),
    "cline": (
        "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/mcp_settings.json",
        "~/Library/Application Support/Code/User/globalStorage/cline.bot/mcp_settings.json",
        "$APPDATA/Code/User/globalStorage/saoudrizwan.claude-dev/mcp_settings.json",
        "$APPDATA/Code/User/globalStorage/cline.bot/mcp_settings.json",
        "$XDG_CONFIG_HOME/Code/User/globalStorage/saoudrizwan.claude-dev/mcp_settings.json",
        "$XDG_CONFIG_HOME/Code/User/globalStorage/cline.bot/mcp_settings.json",
    ),
}
CAPABILITY_CHECK_PAYLOAD = {"query": "capability check", "mode": "capability_check"}
MEMCORE_MCP_SERVER_NAME = "time-library"
MEMCORE_LEGACY_MCP_SERVER_NAMES = ("time-library",)
MEMCORE_MCP_TOOL_NAME = "time_library_recall"
MEMCORE_LEGACY_MCP_TOOL_NAMES = ("zhiyi_recall",)
MEMCORE_MCP_HTTP_URL = "http://127.0.0.1:9851/mcp"
DEFAULT_MODEL_IDENTIFICATION_EXECUTE_LIMIT = 3
IMPLEMENTED_APPLY_SYSTEMS = ("codex", "claude_code_cli", "cursor", "continue", "roo_code", "cline", "kiro")
JSON_MCP_APPLY_SYSTEMS = frozenset(system for system in IMPLEMENTED_APPLY_SYSTEMS if system != "codex")
CATALOG_JSON_APPLY_DENYLIST = frozenset({"claude_desktop", "codex", "zed"})
STALE_OR_DORMANT_FRESHNESS = {"stale", "dormant"}
STALE_PLATFORM_CONFIRMATION = "confirm_connect_stale_or_dormant_platform"
AUTO_CONNECT_READY_STATUS = "auto_connect_ready"
APPLY_GATE_CONFIRMATIONS = (
    "confirm_user_requested_auto_connect",
    "confirm_backup_before_platform_config_write",
    "confirm_receipt_after_each_platform_write",
    "confirm_capability_check_only_after_connect",
    "confirm_no_chat_body_parser_without_separate_authorization",
)


@dataclass(frozen=True)
class AdapterSpec:
    system: str
    display_name: str
    support_level: str
    platform_family: str
    connection_surfaces: tuple[str, ...]
    config_paths: tuple[str, ...] = ()
    skill_paths: tuple[str, ...] = ()
    content_paths: tuple[str, ...] = ()
    content_gate: str = "verified_format_collector_required"
    current_focus: bool = True
    notes: tuple[str, ...] = ()


ADAPTER_SPECS: tuple[AdapterSpec, ...] = (
    AdapterSpec(
        system="codex",
        display_name="Codex",
        support_level="supported_source_and_consumer",
        platform_family="agent_app_and_cli",
        connection_surfaces=("official_desktop_app", "skill", "mcp", "session_jsonl", "state_sqlite", "chrome_native_host"),
        config_paths=(
            "$CODEX_HOME/config.toml",
            "~/.codex/config.toml",
            "$CODEX_HOME/chrome-native-hosts-v2.json",
            "$CODEX_HOME/chrome-native-hosts.json",
            "~/.codex/chrome-native-hosts-v2.json",
            "~/.codex/chrome-native-hosts.json",
            "~/Library/Application Support/OpenAI/Codex/chrome-native-hosts-v2.json",
            "~/Library/Application Support/OpenAI/Codex/chrome-native-hosts.json",
            "$LOCALAPPDATA/OpenAI/Codex/chrome-native-hosts-v2.json",
            "$LOCALAPPDATA/OpenAI/Codex/chrome-native-hosts.json",
            "$APPDATA/OpenAI/Codex/chrome-native-hosts-v2.json",
            "$APPDATA/OpenAI/Codex/chrome-native-hosts.json",
        ),
        skill_paths=(
            "$CODEX_HOME/skills/time-library/SKILL.md",
            "$CODEX_HOME/skills/time-library/SKILL.md",
            "$CODEX_HOME/skills/time_library/SKILL.md",
            "~/.codex/skills/time-library/SKILL.md",
            "~/.codex/skills/time-library/SKILL.md",
            "~/.codex/skills/time_library/SKILL.md",
        ),
        content_paths=("$CODEX_HOME/sessions", "$CODEX_HOME/state_5.sqlite", "~/.codex/sessions", "~/.codex/state_5.sqlite"),
        content_gate="source_connector_authorization_required_for_raw_ingest",
    ),
    AdapterSpec(
        system="openclaw",
        display_name="OpenClaw",
        support_level="supported_source_and_consumer",
        platform_family="agent_app",
        connection_surfaces=("plugin", "local_gateway", "session_jsonl"),
        config_paths=("$OPENCLAW_HOME/plugins/installs.json", "~/.openclaw/plugins/installs.json"),
        content_paths=("$OPENCLAW_HOME/agents", "~/.openclaw/agents"),
        content_gate="source_connector_authorization_required_for_raw_ingest",
    ),
    AdapterSpec(
        system="hermes",
        display_name="Hermes",
        support_level="supported_consumer_observer",
        platform_family="agent_app",
        connection_surfaces=("provider", "raw_pointer", "native_review_observer"),
        config_paths=("$HERMES_HOME/config.yaml", "$HERMES_HOME/profiles/default/config.yaml", "~/.hermes/config.yaml"),
        skill_paths=("$HERMES_HOME/plugins/time_library", "~/.hermes/plugins/time_library"),
        content_paths=("$HERMES_HOME", "~/.hermes"),
        content_gate="raw_pointer_consumption_only_no_platform_write",
    ),
    AdapterSpec(
        system="claude_desktop",
        display_name="Claude Desktop",
        support_level="first_class_desktop_source_and_consumer",
        platform_family="desktop_ai_app",
        connection_surfaces=("mcp_bridge", "desktop_extension", "local_browser_store_manifest"),
        config_paths=(
            "$CLAUDE_DESKTOP_HOME/claude_desktop_config.json",
            "~/Library/Application Support/Claude/claude_desktop_config.json",
            "$APPDATA/Claude/claude_desktop_config.json",
            "$LOCALAPPDATA/Claude/claude_desktop_config.json",
        ),
        skill_paths=("$CLAUDE_DESKTOP_HOME/local-agent-mode-sessions/skills-plugin",),
        content_paths=(
            "$CLAUDE_DESKTOP_HOME/IndexedDB",
            "$CLAUDE_DESKTOP_HOME/Local Storage",
            "$CLAUDE_DESKTOP_HOME/Session Storage",
        ),
        content_gate="verified_format_collector_required",
    ),
    AdapterSpec(
        system="claude_code_cli",
        display_name="Claude Code CLI",
        support_level="adapter_candidate_separate_claude_surface",
        platform_family="agent_cli",
        connection_surfaces=("settings", "mcp", "project_sessions"),
        config_paths=("~/.claude.json", "~/.claude/settings.json", "~/.claude/mcp.json", "$CLAUDE_PROJECT_DIR/.mcp.json", ".mcp.json"),
        content_paths=("~/.claude/projects", "~/.claude"),
        content_gate="source_connector_authorization_required_for_raw_ingest",
        notes=(
            "Connectable as a CLI adapter candidate through Claude Code MCP config.",
            "Keep separate from Claude Desktop official and relay-owned conversations.",
        ),
    ),
    AdapterSpec(
        system="cursor",
        display_name="Cursor",
        support_level="adapter_candidate",
        platform_family="editor_agent",
        connection_surfaces=("mcp", "extension_storage", "workspace_storage"),
        config_paths=(
            "~/.cursor/mcp.json",
            "~/Library/Application Support/Cursor/User/globalStorage",
            "$APPDATA/Cursor/User/globalStorage",
            "$XDG_CONFIG_HOME/Cursor/User/globalStorage",
        ),
        content_paths=(
            "~/Library/Application Support/Cursor/User/workspaceStorage",
            "$APPDATA/Cursor/User/workspaceStorage",
            "$XDG_CONFIG_HOME/Cursor/User/workspaceStorage",
        ),
    ),
    AdapterSpec(
        system="continue",
        display_name="Continue",
        support_level="adapter_candidate",
        platform_family="editor_agent",
        connection_surfaces=("config", "mcp", "extension_storage"),
        config_paths=("~/.continue/config.json", "~/.continue/config.yaml", "~/.continue/config.ts"),
        content_paths=("~/.continue/dev_data", "~/.continue/sessions"),
    ),
    AdapterSpec(
        system="roo_code",
        display_name="Roo Code",
        support_level="adapter_candidate",
        platform_family="editor_agent",
        connection_surfaces=("vscode_extension_storage", "mcp"),
        config_paths=(
            "~/Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline",
            "$APPDATA/Code/User/globalStorage/rooveterinaryinc.roo-cline",
            "$XDG_CONFIG_HOME/Code/User/globalStorage/rooveterinaryinc.roo-cline",
        ),
        content_paths=(
            "~/Library/Application Support/Code/User/globalStorage/rooveterinaryinc.roo-cline",
            "$APPDATA/Code/User/globalStorage/rooveterinaryinc.roo-cline",
            "$XDG_CONFIG_HOME/Code/User/globalStorage/rooveterinaryinc.roo-cline",
        ),
    ),
    AdapterSpec(
        system="cline",
        display_name="Cline",
        support_level="adapter_candidate",
        platform_family="editor_agent",
        connection_surfaces=("vscode_extension_storage", "mcp"),
        config_paths=(
            "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev",
            "~/Library/Application Support/Code/User/globalStorage/cline.bot",
            "$APPDATA/Code/User/globalStorage/saoudrizwan.claude-dev",
            "$APPDATA/Code/User/globalStorage/cline.bot",
            "$XDG_CONFIG_HOME/Code/User/globalStorage/saoudrizwan.claude-dev",
            "$XDG_CONFIG_HOME/Code/User/globalStorage/cline.bot",
        ),
        content_paths=(
            "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev",
            "~/Library/Application Support/Code/User/globalStorage/cline.bot",
            "$APPDATA/Code/User/globalStorage/saoudrizwan.claude-dev",
            "$APPDATA/Code/User/globalStorage/cline.bot",
            "$XDG_CONFIG_HOME/Code/User/globalStorage/saoudrizwan.claude-dev",
            "$XDG_CONFIG_HOME/Code/User/globalStorage/cline.bot",
        ),
    ),
)


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_days(value: float) -> int:
    now = datetime.now(UTC).timestamp()
    return max(0, int((now - value) // 86400))


def _freshness_from_age(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= 14:
        return "active_recent"
    if age_days <= 45:
        return "warm"
    if age_days <= 180:
        return "stale"
    return "dormant"


def _expand_path(pattern: str, home: Path, env: dict[str, str]) -> Path | None:
    if pattern.startswith("~/"):
        return home / pattern[2:]
    expanded = pattern
    for key, value in env.items():
        expanded = expanded.replace(f"${key}", value)
        expanded = expanded.replace(f"%{key}%", value)
    if "$" in expanded or re.search(r"%[A-Za-z_][A-Za-z0-9_]*%", expanded):
        return None
    return Path(expanded).expanduser()


def _effective_env(home: Path, env: dict[str, str] | None) -> dict[str, str]:
    resolved = dict(os.environ if env is None else env)
    home_text = str(home)
    resolved.setdefault("HOME", home_text)
    resolved.setdefault("USERPROFILE", home_text)
    resolved.setdefault("CODEX_HOME", str(home / ".codex"))
    if "APPDATA" not in resolved:
        resolved["APPDATA"] = str(home / "AppData" / "Roaming")
    if "LOCALAPPDATA" not in resolved:
        resolved["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    if "XDG_CONFIG_HOME" not in resolved:
        resolved["XDG_CONFIG_HOME"] = str(home / ".config")
    return resolved


def _read_small_text(path: Path, limit: int = 65536) -> str:
    try:
        with path.open("rb") as fh:
            return fh.read(limit).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _safe_iterdir(path: Path, limit: int | None = None) -> list[Path]:
    try:
        children = list(path.iterdir())
    except OSError:
        return []
    return children if limit is None else children[:limit]


def _safe_stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def _stat_snapshot(path: Path) -> dict[str, Any] | None:
    stat = _safe_stat(path)
    if stat is None:
        return None
    mtime = float(stat.st_mtime)
    age = _age_days(mtime)
    return {
        "path": str(path),
        "modified_at": _iso_from_timestamp(mtime),
        "age_days": age,
        "freshness": _freshness_from_age(age),
    }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            result[str(key)] = "<redacted>" if SENSITIVE_KEY_RE.search(str(key)) else _redact(child)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _safe_json_loads(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _load_json_object(path: Path) -> dict[str, Any]:
    if not _safe_is_file(path):
        return {}
    data = _safe_json_loads(_read_small_text(path, limit=2_000_000))
    return data if isinstance(data, dict) else {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _memcore_root_from_env(env: dict[str, str] | None = None) -> Path:
    source = env or os.environ
    value = str(source.get("MEMCORE_ROOT") or "").strip()
    return Path(value).expanduser() if value else _repo_root()


def _platform_catalog_path() -> Path:
    return _repo_root() / "config" / "platform_catalog.json"


def _platform_watchlist_path() -> Path:
    return _repo_root() / "config" / "platform_watchlist.github_top100.json"


def _platform_storage_patterns_path() -> Path:
    return _repo_root() / "config" / "platform_storage_patterns.verified.json"


def _json_file_cache_key(path: Path) -> tuple[str, int, int]:
    resolved = path.expanduser()
    try:
        stat = resolved.stat()
    except OSError:
        return (str(resolved), -1, -1)
    return (str(resolved), int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))), int(stat.st_size))


def _platform_storage_patterns_cache_key(storage_path: Path | None = None) -> tuple[str, int, int]:
    return _json_file_cache_key(storage_path or _platform_storage_patterns_path())


def _platform_catalog_cache_key(
    catalog_path: Path | None = None,
    watchlist_path: Path | None = None,
) -> tuple[str, int, int, str, int, int, str, int, int]:
    return (
        *_json_file_cache_key(catalog_path or _platform_catalog_path()),
        *_json_file_cache_key(watchlist_path or _platform_watchlist_path()),
        *_platform_storage_patterns_cache_key(),
    )


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


@lru_cache(maxsize=16)
def _load_platform_storage_patterns_cached(path_text: str, mtime_ns: int, size: int) -> dict[str, Any]:
    resolved_path = Path(path_text)
    data = _load_json_object(resolved_path)
    entries = data.get("entries") if isinstance(data.get("entries"), dict) else {}
    observed = data.get("observed_machines") if isinstance(data.get("observed_machines"), list) else []
    native_path_evidence = (
        data.get("native_path_evidence")
        if isinstance(data.get("native_path_evidence"), dict)
        else {}
    )
    return {
        "ok": bool(data),
        "contract": PLATFORM_STORAGE_PATTERNS_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "storage_path": str(resolved_path),
        "schema_version": PLATFORM_STORAGE_PATTERNS_CONTRACT,
        "source_schema_version": data.get("schema_version", ""),
        "product_policy": data.get("product_policy", {}),
        "observed_machines": observed,
        "native_path_evidence": native_path_evidence,
        "entry_count": len(entries),
        "entries": entries,
    }


def load_platform_storage_patterns(
    storage_path: Path | None = None,
) -> dict[str, Any]:
    """Load verified local storage patterns observed on native Mac/Windows."""
    result = dict(_load_platform_storage_patterns_cached(*_platform_storage_patterns_cache_key(storage_path)))
    result["generated_at"] = ts()
    return result


@lru_cache(maxsize=16)
def _load_platform_catalog_cached(
    catalog_path_text: str,
    catalog_mtime_ns: int,
    catalog_size: int,
    watchlist_path_text: str,
    watchlist_mtime_ns: int,
    watchlist_size: int,
    storage_path_text: str,
    storage_mtime_ns: int,
    storage_size: int,
) -> dict[str, Any]:
    resolved_catalog_path = Path(catalog_path_text)
    resolved_watchlist_path = Path(watchlist_path_text)
    catalog = _load_json_object(resolved_catalog_path)
    watchlist = _load_json_object(resolved_watchlist_path)
    storage = load_platform_storage_patterns(Path(storage_path_text))
    curated_entries = _list_of_dicts(catalog.get("entries"))
    watchlist_entries = _list_of_dicts(watchlist.get("entries"))
    storage_entries = storage.get("entries") if isinstance(storage.get("entries"), dict) else {}
    curated_ids = {item.get("id") for item in curated_entries}
    watchlist_ids = {item.get("id") for item in watchlist_entries}
    storage_only_entries = [
        {
            "id": system,
            "display_name": system.replace("_", " ").title(),
            "family": "local_ai_tool",
            "catalog_level": "verified_local_storage",
            "confidence": "verified_local_observation",
            "source_urls": [],
            "workspace_markers": [system, system.replace("_", "-"), f".{system}"],
        }
        for system in sorted(storage_entries)
        if system not in curated_ids and system not in watchlist_ids
    ]
    entries = curated_entries + [
        entry for entry in watchlist_entries
        if entry.get("id") not in curated_ids
    ] + storage_only_entries
    source_urls = sorted({
        str(url)
        for entry in entries
        for url in (entry.get("source_urls") if isinstance(entry.get("source_urls"), list) else [])
        if url
    })
    return {
        "ok": bool(catalog),
        "contract": PLATFORM_CATALOG_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "catalog_path": str(resolved_catalog_path),
        "watchlist_path": str(resolved_watchlist_path),
        "catalog_version": catalog.get("catalog_version", ""),
        "watchlist_version": watchlist.get("watchlist_version", ""),
        "generated_from_public_sources_at": catalog.get("generated_from_public_sources_at", ""),
        "purpose": catalog.get("purpose", ""),
        "scan_policy": catalog.get("scan_policy", {}),
        "storage_patterns": {
            "contract": storage.get("contract"),
            "schema_version": storage.get("schema_version"),
            "entry_count": storage.get("entry_count"),
            "product_policy": storage.get("product_policy", {}),
            "observed_machines": storage.get("observed_machines", []),
            "native_path_evidence": storage.get("native_path_evidence", {}),
        },
        "entry_count": len(entries),
        "curated_entry_count": len(curated_entries),
        "github_watchlist_entry_count": len(watchlist_entries),
        "source_url_count": len(source_urls),
        "source_urls": source_urls,
        "entries": entries,
    }


def load_platform_catalog(
    catalog_path: Path | None = None,
    watchlist_path: Path | None = None,
) -> dict[str, Any]:
    """Load the curated platform catalog plus the generated GitHub watchlist."""
    result = dict(_load_platform_catalog_cached(*_platform_catalog_cache_key(catalog_path, watchlist_path)))
    result["generated_at"] = ts()
    return result


@lru_cache(maxsize=16)
def _platform_catalog_entries_cached(
    catalog_path_text: str,
    catalog_mtime_ns: int,
    catalog_size: int,
    watchlist_path_text: str,
    watchlist_mtime_ns: int,
    watchlist_size: int,
    storage_path_text: str,
    storage_mtime_ns: int,
    storage_size: int,
) -> dict[str, dict[str, Any]]:
    return {
        str(entry.get("id")): entry
        for entry in load_platform_catalog(Path(catalog_path_text), Path(watchlist_path_text)).get("entries", [])
        if entry.get("id")
    }


def _platform_catalog_entries() -> dict[str, dict[str, Any]]:
    return _platform_catalog_entries_cached(*_platform_catalog_cache_key())


def _catalog_entry(system: str) -> dict[str, Any]:
    return _platform_catalog_entries().get(system, {})


def _catalog_list(entry: dict[str, Any], key: str) -> tuple[str, ...]:
    value = entry.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _catalog_mcp(system: str) -> dict[str, Any]:
    mcp = _catalog_entry(system).get("mcp")
    return mcp if isinstance(mcp, dict) else {}


def _catalog_config_keys(system: str) -> tuple[str, ...]:
    keys = _catalog_mcp(system).get("config_keys")
    if not isinstance(keys, list):
        return ()
    return tuple(str(key) for key in keys if key in {"mcpServers", "mcp_servers", "servers"})


def _looks_like_path_pattern(pattern: str) -> bool:
    text = pattern.strip()
    if not text or " " in text and "/" not in text:
        return False
    return bool(
        text.startswith(("~/", "./", "../", "/", "$", "%", "."))
        or "/" in text
        or "\\" in text
        or Path(text).suffix
    )


def _catalog_mcp_config_patterns(system: str) -> tuple[str, ...]:
    patterns = _catalog_mcp(system).get("candidate_config_paths")
    if not isinstance(patterns, list):
        return ()
    return tuple(dict.fromkeys((
        *[str(pattern) for pattern in patterns if _looks_like_path_pattern(str(pattern))],
        *_verified_storage_path_patterns(system, roles={"config"}),
    )))


def _storage_entry(system: str) -> dict[str, Any]:
    entries = load_platform_storage_patterns().get("entries", {})
    if isinstance(entries, dict):
        value = entries.get(system)
        return value if isinstance(value, dict) else {}
    return {}


def _verified_storage_patterns(system: str) -> tuple[dict[str, Any], ...]:
    value = _storage_entry(system).get("verified_storage_patterns")
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _verified_storage_path_patterns(system: str, *, roles: set[str] | None = None) -> tuple[str, ...]:
    patterns: list[str] = []
    for item in _verified_storage_patterns(system):
        role = str(item.get("role") or "")
        if roles is not None and role not in roles:
            continue
        for path in item.get("paths") if isinstance(item.get("paths"), list) else []:
            if _looks_like_path_pattern(str(path)):
                patterns.append(str(path))
    return tuple(dict.fromkeys(patterns))


def _verified_storage_systems() -> tuple[str, ...]:
    entries = load_platform_storage_patterns().get("entries", {})
    if not isinstance(entries, dict):
        return ()
    return tuple(sorted(str(system) for system in entries if str(system).strip()))


def _verified_storage_item_for_path(system: str, path_pattern: str) -> dict[str, Any]:
    for item in _verified_storage_patterns(system):
        paths = item.get("paths") if isinstance(item.get("paths"), list) else []
        if path_pattern in {str(path) for path in paths}:
            return item
    return {}


def _catalog_app_bundle_names(system: str) -> tuple[str, ...]:
    names = _catalog_list(_catalog_entry(system), "app_bundle_names")
    if names:
        return names
    return APP_BUNDLE_NAMES.get(system, (f"{system.replace('_', ' ').title().replace(' ', '')}.app",))


def _catalog_cli_version_command(system: str) -> tuple[str, ...] | None:
    command = _catalog_entry(system).get("cli_version_command")
    if isinstance(command, list) and command:
        return tuple(str(part) for part in command if str(part).strip())
    return CLI_VERSION_COMMANDS.get(system)


def _catalog_entry_summary(system: str) -> dict[str, Any]:
    entry = _catalog_entry(system)
    storage_entry = _storage_entry(system)
    if not entry:
        if not storage_entry:
            return {}
        return {
            "id": system,
            "display_name": system.replace("_", " ").title(),
            "family": "local_ai_tool",
            "catalog_level": "verified_local_storage",
            "confidence": "verified_local_observation",
            "source_urls": [],
            "repo": {},
            "storage_patterns": {
                "verified": True,
                "pattern_count": len(_verified_storage_patterns(system)),
                "auto_connect": storage_entry.get("auto_connect", {}),
            },
        }
    repo = entry.get("repo") if isinstance(entry.get("repo"), dict) else {}
    return {
        "id": entry.get("id", system),
        "display_name": entry.get("display_name", system),
        "family": entry.get("family", ""),
        "catalog_level": entry.get("catalog_level", "curated"),
        "confidence": entry.get("confidence", ""),
        "rank": entry.get("rank"),
        "source_urls": entry.get("source_urls", []),
        "repo": {
            "full_name": repo.get("full_name", ""),
            "url": repo.get("url", ""),
            "stars": repo.get("stars"),
            "language": repo.get("language", ""),
        } if repo else {},
        "storage_patterns": {
            "verified": bool(storage_entry),
            "pattern_count": len(_verified_storage_patterns(system)),
            "auto_connect": storage_entry.get("auto_connect", {}) if storage_entry else {},
        },
    }


def _catalog_json_mcp_apply_supported(system: str) -> bool:
    if system in CATALOG_JSON_APPLY_DENYLIST:
        return False
    mcp = _catalog_mcp(system)
    if not mcp.get("supported"):
        return False
    if not _catalog_config_keys(system):
        return False
    return any(Path(pattern).suffix.lower() == ".json" for pattern in _catalog_mcp_config_patterns(system))


@lru_cache(maxsize=16)
def _implemented_apply_systems_cached(
    catalog_path_text: str,
    catalog_mtime_ns: int,
    catalog_size: int,
    watchlist_path_text: str,
    watchlist_mtime_ns: int,
    watchlist_size: int,
    storage_path_text: str,
    storage_mtime_ns: int,
    storage_size: int,
) -> tuple[str, ...]:
    systems = set(IMPLEMENTED_APPLY_SYSTEMS)
    for system in _platform_catalog_entries():
        if _catalog_json_mcp_apply_supported(system):
            systems.add(system)
    return tuple(sorted(systems))


def _implemented_apply_systems() -> list[str]:
    return list(_implemented_apply_systems_cached(*_platform_catalog_cache_key()))


def _known_adapter_systems() -> set[str]:
    return {spec.system for spec in ADAPTER_SPECS}


def _identifier_variants(text: str) -> set[str]:
    raw = text.strip().lower()
    if not raw:
        return set()
    raw = raw.removesuffix(".app")
    values = {raw}
    if ":" in raw:
        values.add(raw.rsplit(":", 1)[0])
    if "/" in raw:
        values.add(raw.rsplit("/", 1)[-1])
        values.add(raw.lstrip("@").replace("/", "-"))
    if raw.startswith("@") and "/" in raw:
        values.add(raw.rsplit("/", 1)[-1])
    for value in list(values):
        normalized = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
        underscored = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
        compact = re.sub(r"[^a-z0-9]+", "", value)
        values.update(item for item in (normalized, underscored, compact) if item)
    return values


def _catalog_detection_terms(system: str, entry: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for value in (
        system,
        str(entry.get("display_name") or ""),
        *_catalog_list(entry, "aliases"),
        *_catalog_list(entry, "app_bundle_names"),
    ):
        terms.update(_identifier_variants(value))
    repo = entry.get("repo") if isinstance(entry.get("repo"), dict) else {}
    for value in (repo.get("name"), repo.get("full_name")):
        if value:
            terms.update(_identifier_variants(str(value)))
    command = entry.get("cli_version_command")
    if isinstance(command, list) and command:
        terms.update(_identifier_variants(str(command[0])))
    return {term for term in terms if len(term) >= 2}


@lru_cache(maxsize=16)
def _catalog_detection_term_index_cached(
    catalog_path_text: str,
    catalog_mtime_ns: int,
    catalog_size: int,
    watchlist_path_text: str,
    watchlist_mtime_ns: int,
    watchlist_size: int,
    storage_path_text: str,
    storage_mtime_ns: int,
    storage_size: int,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (system, tuple(sorted(_catalog_detection_terms(system, entry))))
        for system, entry in _platform_catalog_entries().items()
    )


def _catalog_detection_term_index() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return _catalog_detection_term_index_cached(*_platform_catalog_cache_key())


def _catalog_system_for_install_name(name: str) -> str | None:
    variants = _identifier_variants(name)
    if not variants:
        return None
    best: tuple[int, str] | None = None
    for system, terms_tuple in _catalog_detection_term_index():
        terms = set(terms_tuple)
        if not terms:
            continue
        overlap = variants & terms
        fuzzy_overlap = {
            term
            for variant in variants
            for term in terms
            if len(term) >= 4
            and (
                variant.startswith(f"{term}-")
                or variant.startswith(f"{term}_")
                or variant.endswith(f"-{term}")
                or variant.endswith(f"_{term}")
            )
        }
        combined = overlap | fuzzy_overlap
        if not combined:
            continue
        score = max(len(term) for term in combined)
        if best is None or score > best[0]:
            best = (score, system)
    return best[1] if best else None



# Package-manager inventory lives in platform_guard_package_inventory.py under
# tiandao_platform_guard_package_inventory.v1. Names are re-exported here for
# compatibility with existing registry and surface-scan callers.

def _app_roots(home: Path, env: dict[str, str]) -> list[Path]:
    roots: list[Path] = []
    explicit = env.get("MEMCORE_APP_ROOTS", "")
    for item in explicit.split(os.pathsep):
        if item.strip():
            roots.append(Path(item).expanduser())
    roots.extend([Path("/Applications"), home / "Applications"])
    unique: list[Path] = []
    seen = set()
    for root in roots:
        text = str(root)
        if text not in seen:
            unique.append(root)
            seen.add(text)
    return unique


def _app_bundle_metadata(system: str, home: Path, env: dict[str, str]) -> dict[str, Any]:
    names = _catalog_app_bundle_names(system)
    for root in _app_roots(home, env):
        for name in names:
            bundle = root / name
            info_path = bundle / "Contents" / "Info.plist"
            if not _safe_is_file(info_path):
                continue
            version = ""
            build = ""
            try:
                with info_path.open("rb") as fh:
                    info = plistlib.load(fh)
                version = str(info.get("CFBundleShortVersionString") or "")
                build = str(info.get("CFBundleVersion") or "")
            except Exception:
                pass
            stat = _stat_snapshot(bundle) or {}
            return {
                "installed": True,
                "bundle_path": str(bundle),
                "version": version,
                "build": build,
                "modified_at": stat.get("modified_at", ""),
                "age_days": stat.get("age_days"),
                "freshness": stat.get("freshness", "unknown"),
            }
    return {
        "installed": False,
        "bundle_path": "",
        "version": "",
        "build": "",
        "modified_at": "",
        "age_days": None,
        "freshness": "unknown",
    }


def _is_codex_native_host_path(path: Path) -> bool:
    name = path.name.lower()
    return name in {
        "chrome-native-hosts-v2.json",
        "chrome-native-hosts.json",
        "com.openai.codexextension.json",
    }


def _codex_native_host_candidate_paths(home: Path, env: dict[str, str]) -> list[Path]:
    patterns = (
        "$CODEX_HOME/chrome-native-hosts-v2.json",
        "$CODEX_HOME/chrome-native-hosts.json",
        "~/.codex/chrome-native-hosts-v2.json",
        "~/.codex/chrome-native-hosts.json",
        "~/Library/Application Support/OpenAI/Codex/chrome-native-hosts-v2.json",
        "~/Library/Application Support/OpenAI/Codex/chrome-native-hosts.json",
        "~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.openai.codexextension.json",
        "$LOCALAPPDATA/OpenAI/Codex/chrome-native-hosts-v2.json",
        "$LOCALAPPDATA/OpenAI/Codex/chrome-native-hosts.json",
        "$APPDATA/OpenAI/Codex/chrome-native-hosts-v2.json",
        "$APPDATA/OpenAI/Codex/chrome-native-hosts.json",
    )
    paths: list[Path] = []
    seen: set[str] = set()
    for pattern in patterns:
        path = _expand_path(pattern, home, env)
        if path is None:
            continue
        text = str(path)
        if text not in seen:
            paths.append(path)
            seen.add(text)
    return paths


def _codex_native_host_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(data.get("entries"), list):
        return [item for item in data["entries"] if isinstance(item, dict)]
    if isinstance(data.get("chromeNativeHosts"), list):
        return [item for item in data["chromeNativeHosts"] if isinstance(item, dict)]
    if isinstance(data.get("paths"), dict):
        return [data]
    if isinstance(data.get("path"), str) or isinstance(data.get("allowed_origins"), list):
        return [data]
    return []


def _codex_native_host_probe(path: Path) -> dict[str, Any]:
    data = _load_json_object(path)
    entries = _codex_native_host_entries(data)
    entry = entries[0] if entries else {}
    paths = entry.get("paths") if isinstance(entry.get("paths"), dict) else {}
    codex_cli_path = str(paths.get("codexCliPath") or entry.get("codexCliPath") or entry.get("path") or "")
    codex_home = str(paths.get("codexHome") or entry.get("codexHome") or "")
    extension_ids = entry.get("extensionIds") if isinstance(entry.get("extensionIds"), list) else []
    native_host_names = entry.get("nativeHostNames") if isinstance(entry.get("nativeHostNames"), list) else []
    return {
        "kind": "codex_chrome_native_host",
        "path": str(path),
        "parse_ok": bool(data),
        "schema_version": data.get("schemaVersion", ""),
        "entry_count": len(entries),
        "app_version": str(entry.get("appVersion") or ""),
        "cli_version": str(entry.get("cliVersion") or ""),
        "native_host_version": str(entry.get("nativeHostVersion") or ""),
        "extension_ids": [str(item) for item in extension_ids],
        "native_host_names": [str(item) for item in native_host_names],
        "codex_home": codex_home,
        "codex_cli_path": codex_cli_path,
        "node_repl_path": str(paths.get("nodeReplPath") or entry.get("nodeReplPath") or ""),
        "resources_path": str(paths.get("resourcesPath") or entry.get("resourcesPath") or ""),
        "official_bridge_detected": bool(entries),
        "mcp_detected": False,
        "memcore_mcp_detected": False,
        "intent_signal_detected": bool(entries),
        "content_read": False,
        "chat_body_included": False,
        "raw_excerpt_included": False,
    }


def _codex_cli_from_native_hosts(home: Path, env: dict[str, str]) -> tuple[str, dict[str, Any]]:
    for path in _codex_native_host_candidate_paths(home, env):
        if not _safe_is_file(path):
            continue
        probe = _codex_native_host_probe(path)
        candidate = str(probe.get("codex_cli_path") or "")
        if candidate:
            return candidate, probe
    return "", {}


def _cli_version_metadata(system: str, home: Path | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    command = _catalog_cli_version_command(system)
    if not command:
        return {"installed": False, "path": "", "version": "", "raw": ""}
    resolved_env = _effective_env(home or Path.home(), env)
    executable = shutil.which(command[0], path=resolved_env.get("PATH"))
    native_host_probe: dict[str, Any] = {}
    if not executable and system == "codex" and home is not None:
        executable, native_host_probe = _codex_cli_from_native_hosts(home, resolved_env)
    if not executable:
        return {"installed": False, "path": "", "version": "", "raw": ""}
    try:
        result = subprocess.run(
            [executable, *command[1:]],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        raw = (result.stdout or result.stderr or "").strip().splitlines()[0:1]
        version = raw[0] if raw else ""
    except Exception:
        version = ""
        raw = []
    return {
        "installed": True,
        "path": executable,
        "version": version,
        "raw": raw[0] if raw else "",
        "source": "codex_chrome_native_host" if native_host_probe else "path",
        "native_host": native_host_probe,
    }


def _mcp_server_map_from_json(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("mcpServers", "mcp_servers", "mcpServer", "servers"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _mcp_server_names_from_text(text: str) -> list[str]:
    names = set()
    data = _safe_json_loads(text)
    if data:
        names.update(str(name) for name in _mcp_server_map_from_json(data).keys())
    for match in MCP_SECTION_RE.finditer(text):
        name = match.group(1).strip().strip('"').strip("'")
        if name:
            names.add(name)
    return sorted(names)


def _looks_like_mcp_config(path: Path, text: str) -> bool:
    name = path.name.lower()
    if "mcp" in name:
        return True
    tool_pattern = "|".join(re.escape(name) for name in (MEMCORE_MCP_TOOL_NAME, *MEMCORE_LEGACY_MCP_TOOL_NAMES))
    if name in SAFE_CONFIG_FILENAMES and re.search(rf"\bmcpServers\b|\bmcp_servers\b|9851|{tool_pattern}", text):
        return True
    return False


def _config_probe(path: Path) -> dict[str, Any]:
    if _is_codex_native_host_path(path):
        return _codex_native_host_probe(path)
    text = _read_small_text(path)
    data = _safe_json_loads(text)
    server_map = _mcp_server_map_from_json(data) if data else {}
    server_names = sorted(str(name) for name in server_map.keys()) if server_map else _mcp_server_names_from_text(text)
    redacted_server_map = _redact(server_map) if server_map else {}
    memcore_server_names = [
        name for name in server_names
        if INTENT_SIGNAL_RE.search(name)
    ]
    tool_pattern = "|".join(re.escape(name) for name in (MEMCORE_MCP_TOOL_NAME, *MEMCORE_LEGACY_MCP_TOOL_NAMES))
    endpoint_signal = bool(re.search(rf"127\.0\.0\.1:9851|localhost:9851|{tool_pattern}", text, re.I))
    memcore_signal = bool(memcore_server_names or endpoint_signal or INTENT_SIGNAL_RE.search(text))
    return {
        "kind": "mcp_config" if _looks_like_mcp_config(path, text) else "config",
        "path": str(path),
        "parse_ok": bool(data),
        "reported_keys": sorted(str(key) for key in data.keys()) if data else [],
        "mcp_detected": bool(server_names or _looks_like_mcp_config(path, text)),
        "mcp_server_names": server_names,
        "memcore_mcp_detected": bool(memcore_server_names or endpoint_signal),
        "memcore_mcp_server_names": memcore_server_names,
        "intent_signal_detected": memcore_signal,
        "redacted_mcp_servers": redacted_server_map,
    }


def _dir_config_probe(path: Path, limit: int = 24) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    children = _safe_iterdir(path, limit=limit)
    for child in children:
        if not _safe_is_file(child):
            continue
        lower = child.name.lower()
        if lower in SAFE_CONFIG_FILENAMES or "mcp" in lower:
            probes.append(_config_probe(child))
    return probes


def _slug(text: str) -> str:
    cleaned = re.sub(r"^\.+", "", text.strip())
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", cleaned).strip("_").lower()
    return cleaned or "unknown_surface"


def _is_infrastructure_surface_id(system: str) -> bool:
    return _slug(system) in LOCAL_INFRASTRUCTURE_SURFACE_IDS


def _normalized_path_text(path: Path | str) -> str:
    return str(path).replace("\\", "/").lower()


def _kiro_artifact_kind(path: Path | str) -> str:
    normalized = _normalized_path_text(path)
    if "/kiro/user/globalstorage/kiro.kiroagent/workspace-sessions" in normalized:
        return "native_workspace_sessions"
    if normalized.endswith("/workspace-sessions") and "/kiro.kiroagent/" in normalized:
        return "native_workspace_sessions"
    if normalized.endswith("/.kiro") or "/.kiro/" in normalized:
        return "project_artifacts"
    if normalized.endswith("/kiro") or "/kiro/" in normalized:
        return "native_app_storage"
    return ""


def _kiro_workspace_session_candidates(path: Path) -> list[Path]:
    name = path.name.lower()
    candidates: list[Path] = []
    if name == "workspace-sessions":
        candidates.append(path)
    if name == "kiro.kiroagent":
        candidates.append(path / "workspace-sessions")
    if name == "globalstorage":
        candidates.append(path / "kiro.kiroagent" / "workspace-sessions")
    if name == "user":
        candidates.append(path / "globalStorage" / "kiro.kiroagent" / "workspace-sessions")
    if name == "kiro":
        candidates.append(path / "User" / "globalStorage" / "kiro.kiroagent" / "workspace-sessions")
    return candidates


def _append_unique_path(paths: list[str], path: Path | str) -> bool:
    text = str(path)
    if text in paths:
        return False
    paths.append(text)
    return True


def _conversation_memory_boundary(system: str, paths: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    if system == "codex":
        normalized = {_normalized_path_text(path) for path in paths}
        has_sessions = any(path.endswith("/.codex/sessions") or "/.codex/sessions/" in path for path in normalized)
        if has_sessions:
            return {
                "conversation_capture_mode": "codex_official_session_jsonl_observed",
                "complete_conversation_candidate": True,
                "assistant_replies_may_persist": True,
                "assistant_reply_persistence": "observed_in_official_session_jsonl_format",
                "assistant_replies_observed_by_current_scan": False,
                "can_recall_assistant_replies_now": False,
                "content_read": False,
                "parser_gate": "verified_format_collector_required",
            }
        return {
            "conversation_capture_mode": "codex_official_metadata_only",
            "complete_conversation_candidate": False,
            "assistant_replies_may_persist": False,
            "assistant_reply_persistence": "not_claimed_from_state_or_native_host_metadata",
            "assistant_replies_observed_by_current_scan": False,
            "can_recall_assistant_replies_now": False,
            "content_read": False,
            "parser_gate": "verified_format_collector_required",
        }
    if system == "kiro":
        kinds = {_kiro_artifact_kind(path) for path in paths}
        if "native_workspace_sessions" in kinds:
            return {
                "conversation_capture_mode": "native_workspace_sessions_observed",
                "complete_conversation_candidate": True,
                "assistant_replies_may_persist": True,
                "assistant_reply_persistence": "observed_in_windows_native_workspace_sessions_format",
                "assistant_replies_observed_by_current_scan": False,
                "can_recall_assistant_replies_now": False,
                "content_read": False,
                "parser_gate": "verified_format_collector_required",
            }
        if "project_artifacts" in kinds:
            return {
                "conversation_capture_mode": "project_artifacts_only_observed",
                "complete_conversation_candidate": False,
                "assistant_replies_may_persist": False,
                "assistant_reply_persistence": "not_claimed_from_project_specs",
                "assistant_replies_observed_by_current_scan": False,
                "can_recall_assistant_replies_now": False,
                "content_read": False,
                "parser_gate": "verified_format_collector_required",
            }
        return {
            "conversation_capture_mode": "kiro_surface_only",
            "complete_conversation_candidate": False,
            "assistant_replies_may_persist": False,
            "assistant_reply_persistence": "unverified_until_native_workspace_sessions_detected",
            "assistant_replies_observed_by_current_scan": False,
            "can_recall_assistant_replies_now": False,
            "content_read": False,
            "parser_gate": "verified_format_collector_required",
        }
    return {
        "conversation_capture_mode": "not_claimed_until_source_parser_verified",
        "complete_conversation_candidate": False,
        "assistant_replies_may_persist": False,
        "assistant_reply_persistence": "unverified",
        "assistant_replies_observed_by_current_scan": False,
        "can_recall_assistant_replies_now": False,
        "content_read": False,
        "parser_gate": "verified_format_collector_required",
    }


def _refresh_conversation_memory_boundary(surface: dict[str, Any]) -> None:
    system = str(surface.get("system") or "")
    boundary_paths = [
        *list(surface.get("content_store_paths") or []),
        *list(surface.get("workspace_paths") or []),
    ]
    surface["conversation_memory_boundary"] = _conversation_memory_boundary(system, boundary_paths)


def _record_workspace_surface_path(surface: dict[str, Any], path: Path) -> None:
    path_text = str(path)
    _append_unique_path(surface["content_store_paths"], path_text)
    _append_unique_path(surface["workspace_paths"], path_text)
    surface["signals"].append({
        "kind": "workspace_surface",
        "path": path_text,
        "content_read": False,
        "parser_gate": "verified_format_collector_required",
    })


def _record_kiro_native_workspace_sessions(surface: dict[str, Any], path: Path) -> None:
    path_text = str(path)
    _append_unique_path(surface["content_store_paths"], path_text)
    _append_unique_path(surface["workspace_paths"], path_text)
    signal_exists = any(
        signal.get("kind") == "kiro_native_workspace_sessions" and signal.get("path") == path_text
        for signal in surface.get("signals", [])
        if isinstance(signal, dict)
    )
    if not signal_exists:
        surface["signals"].append({
            "kind": "kiro_native_workspace_sessions",
            "path": path_text,
            "content_read": False,
            "assistant_roles_read": False,
            "parser_gate": "verified_format_collector_required",
        })


def _record_verified_storage_path(
    surface: dict[str, Any],
    *,
    system: str,
    path: Path,
    storage_item: dict[str, Any],
    path_pattern: str,
) -> None:
    role = str(storage_item.get("role") or "app_data")
    artifact_format = str(storage_item.get("artifact_format") or "")
    path_text = str(path)
    if role == "config":
        _append_unique_path(surface["config_paths"], path_text)
        if _safe_is_file(path):
            probe = _config_probe(path)
            surface["signals"].append({
                **probe,
                "kind": probe.get("kind", "config"),
                "catalog_driven": True,
                "verified_storage": True,
                "artifact_format": artifact_format,
                "path_pattern": path_pattern,
            })
            surface["mcp_config_detected"] = surface["mcp_config_detected"] or bool(probe.get("mcp_detected"))
            surface["memcore_mcp_detected"] = surface["memcore_mcp_detected"] or bool(probe.get("memcore_mcp_detected"))
            surface["intent_signal_detected"] = surface["intent_signal_detected"] or bool(probe.get("intent_signal_detected"))
            surface["connectable_now"] = surface["connectable_now"] or bool(probe.get("memcore_mcp_detected"))
        else:
            surface["signals"].append({
                "kind": "verified_config_surface",
                "path": path_text,
                "content_read": False,
                "verified_storage": True,
                "artifact_format": artifact_format,
                "path_pattern": path_pattern,
            })
        return

    if role in {"content_store", "app_data", "project_artifacts"}:
        _append_unique_path(surface["content_store_paths"], path_text)
    if role in {"project_artifacts", "workspace", "content_store"}:
        _append_unique_path(surface["workspace_paths"], path_text)
    surface["signals"].append({
        "kind": "verified_storage_path",
        "role": role,
        "path": path_text,
        "path_pattern": path_pattern,
        "artifact_format": artifact_format,
        "verified_storage": True,
        "complete_conversation_candidate": storage_item.get("complete_conversation_candidate", False),
        "assistant_replies_may_persist": storage_item.get("assistant_replies_may_persist", "unknown"),
        "assistant_reply_persistence": storage_item.get("assistant_reply_persistence", ""),
        "content_read": False,
        "parser_gate": "verified_format_collector_required",
    })
    if system == "kiro":
        for candidate in _kiro_workspace_session_candidates(path):
            if _safe_is_dir(candidate):
                _record_kiro_native_workspace_sessions(surface, candidate)


def _catalog_system_for_workspace_path(path: Path) -> str | None:
    if _is_noisy_local_ai_candidate(path):
        return None
    name = path.name.lower()
    for system, entry in _platform_catalog_entries().items():
        markers = {marker.lower() for marker in _catalog_list(entry, "workspace_markers")}
        aliases = {alias.lower() for alias in _catalog_list(entry, "aliases")}
        repo = entry.get("repo") if isinstance(entry.get("repo"), dict) else {}
        repo_name = str(repo.get("name") or "").lower()
        full_name = str(repo.get("full_name") or "").lower()
        marker_match = name in markers and path.name.startswith(".")
        if marker_match or name in aliases or (repo_name and name == repo_name):
            return system
        if full_name and str(path).lower().endswith(full_name.replace("/", os.sep)):
            return system
    return _catalog_system_for_install_name(path.name)


def _is_context_path_part(part: str) -> bool:
    lowered = part.lower()
    return lowered in GENERIC_CONTEXT_DIR_NAMES or len(lowered) == 1 and lowered.isalpha()


def _is_noisy_local_ai_candidate(path: Path) -> bool:
    variants = _identifier_variants(path.name)
    if variants & LOCAL_AI_NOISE_DIR_TOKENS:
        return True
    lowered = path.name.lower()
    if LOCAL_AI_PROJECT_ARTIFACT_RE.search(lowered):
        return True
    if re.search(r"(^|[-_.\s])(bak|backup|backups|cache|disabled[-_.\s]?test|old|test|tmp|updater)([-_.\s]|$)", lowered):
        return True
    parent_names = [parent.name.lower() for parent in path.parents]
    windows_temp_parent = "temp" in parent_names and any(name in parent_names for name in ("appdata", "local settings"))
    backup_parent = any(name in {"backup", "backups", "cache", "caches"} for name in parent_names)
    return windows_temp_parent or backup_parent


def _is_high_value_generic_branch(path: Path, depth: int) -> bool:
    lowered = path.name.lower()
    if _is_noisy_local_ai_candidate(path) or lowered in GENERIC_SKIP_DIRS:
        return False
    if depth <= 2:
        return True
    if lowered in GENERIC_DISCOVERY_BRANCH_NAMES:
        return True
    if lowered.startswith(".") and len(lowered) > 1:
        return True
    if _catalog_system_for_workspace_path(path):
        return True
    if LOCAL_AI_SURFACE_TOKEN_RE.search(path.name):
        return True
    return False


def _infer_surface_id(path: Path, home: Path) -> str:
    cursor = path if _safe_is_dir(path) else path.parent
    if _kiro_artifact_kind(cursor):
        return "kiro"
    for current in (cursor, *cursor.parents):
        system = _catalog_system_for_workspace_path(current)
        if system:
            return system
        if current == home:
            break
    try:
        rel = path.relative_to(home)
        parts = rel.parts
    except ValueError:
        parts = path.parts
    if ".cursor" in parts:
        return "cursor"
    if ".continue" in parts:
        return "continue"
    for part in reversed(parts):
        lowered = part.lower()
        if _is_context_path_part(part):
            continue
        catalog_system = _catalog_system_for_install_name(part)
        if catalog_system:
            return catalog_system
        if lowered.startswith(".") and lowered not in GENERIC_SKIP_DIRS and len(lowered) > 1:
            return _slug(lowered)
    if ".vscode" in parts:
        return "vscode"
    for part in reversed(parts):
        lowered = part.lower()
        if lowered in {"settings", "user", "globalstorage", "workspaceStorage".lower()} or _is_context_path_part(part):
            continue
        if lowered.endswith(".json") or lowered.endswith(".toml") or lowered.endswith(".yaml") or lowered.endswith(".yml"):
            continue
        slug = _slug(part)
        if slug:
            return slug
    return _slug(path.parent.name)


def _is_generic_config_candidate(path: Path) -> bool:
    lower = path.name.lower()
    if lower in GENERIC_CONFIG_FILENAMES:
        return True
    return "mcp" in lower and path.suffix.lower() in GENERIC_CONFIG_SUFFIXES


def _is_generic_workspace_candidate(path: Path) -> bool:
    if not _safe_is_dir(path) or path.name in GENERIC_SKIP_DIRS:
        return False
    if _is_noisy_local_ai_candidate(path):
        return False
    if _kiro_artifact_kind(path) == "native_workspace_sessions":
        return True
    if not path.name.startswith("."):
        return bool(_catalog_system_for_workspace_path(path) or LOCAL_AI_SURFACE_TOKEN_RE.search(path.name))
    if _catalog_system_for_workspace_path(path):
        return True
    if LOCAL_AI_SURFACE_TOKEN_RE.search(path.name):
        return True
    child_names = {child.name.lower() for child in _safe_iterdir(path, limit=80)}
    return bool(child_names & GENERIC_WORKSPACE_MARKER_DIRS)


def _generic_scan_roots(home: Path, env: dict[str, str]) -> list[Path]:
    roots = [home]
    for child in ("Desktop", "workspace", "Projects"):
        roots.append(home / child)
    for key in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "MEMCORE_DISCOVERY_ROOT"):
        value = env.get(key)
        if value:
            roots.append(Path(value).expanduser())
    roots.append(Path.cwd())
    unique: list[Path] = []
    seen = set()
    for root in roots:
        text = str(root)
        if text not in seen and _safe_is_dir(root):
            unique.append(root)
            seen.add(text)
    return unique


def _glob_static_base(path: Path) -> Path:
    parts = path.parts
    base_parts: list[str] = []
    for part in parts:
        if any(char in part for char in "*?["):
            break
        base_parts.append(part)
    if not base_parts:
        return Path(".")
    return Path(*base_parts)


def _expanded_catalog_pattern_paths(
    pattern: str,
    *,
    home: Path,
    env: dict[str, str],
    roots: list[Path],
) -> list[Path]:
    if not _looks_like_path_pattern(pattern):
        return []
    pattern = pattern.replace("\\", "/")
    seed_paths: list[Path] = []
    if pattern.startswith("."):
        seed_paths = [root / pattern for root in roots]
    else:
        expanded = _expand_path(pattern, home, env)
        if expanded is not None:
            seed_paths = [expanded]
    results: list[Path] = []
    for seed in seed_paths:
        text = str(seed)
        if any(char in text for char in "*?["):
            base = _glob_static_base(seed)
            if _safe_is_dir(base):
                results.extend(Path(item) for item in glob.glob(text, recursive=True))
        else:
            results.append(seed)
    unique: list[Path] = []
    seen = set()
    for path in results:
        text = str(path)
        if text not in seen:
            unique.append(path)
            seen.add(text)
    return unique


def _iter_catalog_config_candidates(roots: list[Path], home: Path, env: dict[str, str]) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for system in _platform_catalog_entries():
        for pattern in _catalog_mcp_config_patterns(system):
            for path in _expanded_catalog_pattern_paths(pattern, home=home, env=env, roots=roots):
                if not _safe_is_file(path):
                    continue
                text = str(path)
                if text in seen:
                    continue
                found.append((system, path))
                seen.add(text)
    return found


def _iter_generic_config_candidates(
    roots: list[Path],
    *,
    max_depth: int = 5,
    max_dirs: int = 500,
    max_files: int = 800,
) -> list[Path]:
    found: list[Path] = []
    seen_files: set[str] = set()
    dirs_seen = 0
    files_seen = 0
    queues: list[list[tuple[Path, int]]] = [[(root, 0)] for root in roots]
    seen_dirs: set[str] = set()
    while any(queues) and dirs_seen < max_dirs and files_seen < max_files:
        for queue in queues:
            if not queue or dirs_seen >= max_dirs or files_seen >= max_files:
                continue
            current, depth = queue.pop(0)
            current_text = str(current)
            if current_text in seen_dirs:
                continue
            seen_dirs.add(current_text)
            if depth > max_depth or current.name in GENERIC_SKIP_DIRS or _is_noisy_local_ai_candidate(current):
                continue
            dirs_seen += 1
            children = _safe_iterdir(current)
            for child in children:
                if files_seen >= max_files:
                    break
                if _safe_is_file(child):
                    files_seen += 1
                    if _is_generic_config_candidate(child):
                        text = str(child)
                        if text not in seen_files:
                            found.append(child)
                            seen_files.add(text)
                elif (
                    _safe_is_dir(child)
                    and depth < max_depth
                    and child.name not in GENERIC_SKIP_DIRS
                    and not _is_noisy_local_ai_candidate(child)
                    and _is_high_value_generic_branch(child, depth + 1)
                ):
                    queue.append((child, depth + 1))
    return found


def _iter_git_repo_candidates(
    roots: list[Path],
    *,
    max_depth: int = 4,
    max_dirs: int = 1200,
) -> list[Path]:
    found: list[Path] = []
    seen_dirs: set[str] = set()
    dirs_seen = 0
    queue: list[tuple[Path, int]] = [(root, 0) for root in roots]
    while queue and dirs_seen < max_dirs:
        current, depth = queue.pop(0)
        if depth > max_depth or current.name in GENERIC_SKIP_DIRS or _is_noisy_local_ai_candidate(current):
            continue
        dirs_seen += 1
        if _safe_is_file(current / ".git" / "config"):
            text = str(current)
            if text not in seen_dirs:
                found.append(current)
                seen_dirs.add(text)
            continue
        children = _safe_iterdir(current)
        for child in children:
            if (
                _safe_is_dir(child)
                and depth < max_depth
                and child.name not in GENERIC_SKIP_DIRS
                and not _is_noisy_local_ai_candidate(child)
                and _is_high_value_generic_branch(child, depth + 1)
            ):
                queue.append((child, depth + 1))
    return found


def _catalog_system_for_repo(repo_root: Path) -> str | None:
    config_text = _read_small_text(repo_root / ".git" / "config", limit=200_000).lower()
    name = repo_root.name.lower()
    for system, entry in _platform_catalog_entries().items():
        repo = entry.get("repo") if isinstance(entry.get("repo"), dict) else {}
        full_name = str(repo.get("full_name") or "").lower()
        repo_name = str(repo.get("name") or "").lower()
        aliases = {alias.lower() for alias in _catalog_list(entry, "aliases")}
        if full_name and full_name in config_text:
            return system
        if repo_name and name == repo_name:
            return system
        if name in aliases:
            return system
    return None


def _iter_generic_workspace_candidates(
    roots: list[Path],
    *,
    max_depth: int = 5,
    max_dirs: int = 3000,
) -> list[Path]:
    found: list[Path] = []
    seen_dirs: set[str] = set()
    dirs_seen = 0
    queue: list[tuple[Path, int]] = [(root, 0) for root in roots]
    while queue and dirs_seen < max_dirs:
        current, depth = queue.pop(0)
        if depth > max_depth or current.name in GENERIC_SKIP_DIRS or _is_noisy_local_ai_candidate(current):
            continue
        dirs_seen += 1
        if _is_generic_workspace_candidate(current):
            text = str(current)
            if text not in seen_dirs:
                found.append(current)
                seen_dirs.add(text)
        children = _safe_iterdir(current)
        for child in children:
            if (
                _safe_is_dir(child)
                and depth < max_depth
                and child.name not in GENERIC_SKIP_DIRS
                and not _is_noisy_local_ai_candidate(child)
                and _is_high_value_generic_branch(child, depth + 1)
            ):
                queue.append((child, depth + 1))
    return found


def _normalize_generic_scan_mode(scan_mode: str | None) -> str:
    normalized = str(scan_mode or "").strip().lower()
    if normalized in {"fast", "quick", "snapshot"}:
        return "fast_snapshot"
    if normalized in {"deep", "full"}:
        return "deep"
    return "smart"


def _normalize_execute_limit(value: Any, *, default: int = DEFAULT_MODEL_IDENTIFICATION_EXECUTE_LIMIT) -> int:
    try:
        limit = int(str(value).strip())
    except Exception:
        limit = default
    return max(0, min(limit, 50))


def _surface_needs_model_identification(surface: dict[str, Any]) -> bool:
    identification = surface.get("model_identification")
    if not isinstance(identification, dict):
        return False
    return (
        identification.get("mode") == "configured_model"
        and bool(identification.get("enabled"))
        and not bool(identification.get("model_call_performed"))
    )


def _generic_surface_record(system: str, *, source: str) -> dict[str, Any]:
    catalog_entry = _catalog_entry(system)
    summary = _catalog_entry_summary(system)
    return {
        "system": system,
        "display_name": catalog_entry.get("display_name") or system.replace("_", " ").title(),
        "status": "detected",
        "detected": True,
        "generic_surface": True,
        "catalog_driven": bool(catalog_entry),
        "catalog_entry": summary,
        "read_only": True,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "source": source,
        "platform_family": catalog_entry.get("family", "generic_mcp_or_config_surface"),
        "config_paths": [],
        "content_store_paths": [],
        "workspace_paths": [],
        "installation_paths": [],
        "signals": [],
        "mcp_config_detected": False,
        "memcore_mcp_detected": False,
        "intent_signal_detected": False,
        "connectable_now": False,
        "content_read": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": _conversation_memory_boundary(system),
    }


def _path_tail(path: Path | str, limit: int = 5) -> str:
    parts = Path(str(path)).parts
    if not parts:
        return ""
    return "/".join(parts[-limit:])


def _compact_unique(values: Iterable[Any], *, limit: int = 20) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
        if len(result) >= limit:
            break
    return result




__all__ = [name for name in globals() if not name.startswith("__")]
