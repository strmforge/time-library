"""Thin-adapter registry for local AI tools.

Memcore Cloud discovers local AI tools, recognizes their native storage shapes,
and prepares Skill/MCP connection paths automatically where the platform allows
it. Backups and receipts remain part of the write path, but the product promise
is straightforward: install once, then let the local memory layer find and wire
up the tools already on this machine.
"""

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

REGISTRY_CONTRACT = "thin_adapter_registry.v1"
AUTOCONNECT_DRY_RUN_CONTRACT = "authorized_auto_connect_dry_run.v1"
AUTOCONNECT_APPLY_GATE_CONTRACT = "authorized_auto_connect_apply_gate.v1"
AUTOCONNECT_APPLY_CONTRACT = "authorized_auto_connect_apply.v1"
DISCOVERY_DASHBOARD_CONTRACT = "platform_discovery_dashboard.v1"
PLATFORM_CATALOG_CONTRACT = "platform_catalog.v1"
PLATFORM_STORAGE_PATTERNS_CONTRACT = "platform_storage_patterns.v2026.6.9"
PACKAGE_MANAGER_INVENTORY_CONTRACT = "package_manager_agent_inventory.v1"
MODEL_IDENTIFICATION_CONTRACT = "local_ai_tool_model_identification.v1"
PROVISIONAL_ADAPTER_CANDIDATE_CONTRACT = "provisional_adapter_candidates.v1"
ADAPTER_DRAFT_CONTRACT = "local_ai_tool_adapter_draft.v1"
INTENT_SIGNAL_RE = re.compile(r"(memcore|yifanchen|zhiyi|忆凡尘|知意)", re.I)
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
    r"opencode|qclaw|reasonix|roo|windsurf|workbuddy"
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
MEMCORE_MCP_SERVER_NAME = "yifanchen-zhiyi"
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
            "$CODEX_HOME/skills/yifanchen-zhiyi/SKILL.md",
            "$CODEX_HOME/skills/yifanchen/SKILL.md",
            "~/.codex/skills/yifanchen-zhiyi/SKILL.md",
            "~/.codex/skills/yifanchen/SKILL.md",
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
        skill_paths=("$HERMES_HOME/plugins/memcore_yifanchen", "~/.hermes/plugins/memcore_yifanchen"),
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


def _env_paths(env: dict[str, str], key: str) -> list[Path]:
    value = env.get(key, "")
    return [Path(item).expanduser() for item in value.split(os.pathsep) if item.strip()]


def _existing_unique_dirs(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen = set()
    for path in paths:
        try:
            resolved = path.expanduser()
        except Exception:
            resolved = path
        text = str(resolved)
        if text in seen or not _safe_is_dir(resolved):
            continue
        unique.append(resolved)
        seen.add(text)
    return unique


def _npm_global_roots(home: Path, env: dict[str, str]) -> list[Path]:
    roots = _env_paths(env, "MEMCORE_NPM_GLOBAL_ROOT")
    if env.get("MEMCORE_PACKAGE_SCAN_STRICT_ROOTS") == "1":
        return _existing_unique_dirs(roots)
    roots.extend([
        home / ".npm-global" / "lib" / "node_modules",
        home / ".volta" / "tools" / "image" / "packages",
        Path("/opt/homebrew/lib/node_modules"),
        Path("/usr/local/lib/node_modules"),
    ])
    roots.extend(Path(item) for item in glob.glob(str(home / ".nvm" / "versions" / "node" / "*" / "lib" / "node_modules")))
    roots.extend(Path(item) for item in glob.glob(str(home / ".local" / "share" / "mise" / "installs" / "node" / "*" / "lib" / "node_modules")))
    return _existing_unique_dirs(roots)


def _package_json_metadata(path: Path) -> dict[str, str]:
    data = _load_json_object(path / "package.json")
    return {
        "version": str(data.get("version") or ""),
        "description": str(data.get("description") or "")[:240],
    }


def _scan_npm_global(home: Path, env: dict[str, str]) -> dict[str, Any]:
    roots = _npm_global_roots(home, env)
    items: list[dict[str, Any]] = []
    for root in roots:
        try:
            children = _safe_iterdir(root, limit=500)
        except Exception:
            continue
        for child in children:
            if not _safe_is_dir(child):
                continue
            if child.name.startswith("@"):
                scoped_children = _safe_iterdir(child, limit=200)
                for scoped in scoped_children:
                    if _safe_is_dir(scoped):
                        meta = _package_json_metadata(scoped)
                        items.append({
                            "manager": "npm_global",
                            "name": f"{child.name}/{scoped.name}",
                            "path": str(scoped),
                            **meta,
                        })
            else:
                meta = _package_json_metadata(child)
                items.append({
                    "manager": "npm_global",
                    "name": child.name,
                    "path": str(child),
                    **meta,
                })
    return {"roots": [str(root) for root in roots], "items": items}


def _pipx_roots(home: Path, env: dict[str, str]) -> list[Path]:
    roots = _env_paths(env, "MEMCORE_PIPX_HOME")
    if env.get("MEMCORE_PACKAGE_SCAN_STRICT_ROOTS") == "1":
        return _existing_unique_dirs(roots)
    roots.extend([
        home / ".local" / "pipx",
        home / ".local" / "share" / "pipx",
        home / ".pipx",
    ])
    return _existing_unique_dirs(roots)


def _scan_pipx(home: Path, env: dict[str, str]) -> dict[str, Any]:
    roots = _pipx_roots(home, env)
    items: list[dict[str, Any]] = []
    for root in roots:
        venvs = root / "venvs"
        if not _safe_is_dir(venvs):
            continue
        children = _safe_iterdir(venvs, limit=500)
        for child in children:
            if _safe_is_dir(child):
                items.append({
                    "manager": "pipx",
                    "name": child.name,
                    "path": str(child),
                    "version": "",
                    "description": "",
                })
    return {"roots": [str(root) for root in roots], "items": items}


def _brew_prefixes(home: Path, env: dict[str, str]) -> list[Path]:
    roots = _env_paths(env, "MEMCORE_BREW_PREFIX")
    if env.get("MEMCORE_PACKAGE_SCAN_STRICT_ROOTS") == "1":
        return _existing_unique_dirs(roots)
    if env.get("HOMEBREW_PREFIX"):
        roots.append(Path(env["HOMEBREW_PREFIX"]))
    roots.extend([Path("/opt/homebrew"), Path("/usr/local")])
    return _existing_unique_dirs(roots)


def _scan_homebrew(home: Path, env: dict[str, str]) -> dict[str, Any]:
    prefixes = _brew_prefixes(home, env)
    items: list[dict[str, Any]] = []
    for prefix in prefixes:
        cellar = prefix / "Cellar"
        if not _safe_is_dir(cellar):
            continue
        formulae = _safe_iterdir(cellar, limit=800)
        for formula in formulae:
            if not _safe_is_dir(formula):
                continue
            version = ""
            versions = sorted([child.name for child in _safe_iterdir(formula) if _safe_is_dir(child)])
            version = versions[-1] if versions else ""
            items.append({
                "manager": "homebrew",
                "name": formula.name,
                "path": str(formula),
                "version": version,
                "description": "",
            })
    return {"roots": [str(root) for root in prefixes], "items": items}


def _docker_image_lines(env: dict[str, str]) -> list[str]:
    override = env.get("MEMCORE_DOCKER_IMAGE_LIST", "")
    if override:
        path = Path(override).expanduser()
        if _safe_is_file(path):
            return _read_small_text(path, limit=1_000_000).splitlines()
        return override.splitlines()
    docker = shutil.which("docker")
    if env.get("MEMCORE_PACKAGE_SCAN_STRICT_ROOTS") == "1":
        return []
    if not docker:
        return []
    try:
        result = subprocess.run(
            [docker, "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def _scan_docker_images(env: dict[str, str]) -> dict[str, Any]:
    items = []
    for line in _docker_image_lines(env):
        name = line.strip()
        if not name or name.startswith("<none>"):
            continue
        items.append({
            "manager": "docker_image",
            "name": name,
            "path": "",
            "version": name.rsplit(":", 1)[-1] if ":" in name else "",
            "description": "",
        })
    return {"roots": [], "items": items}


def _iter_compose_files(
    roots: list[Path],
    *,
    max_depth: int = 4,
    max_dirs: int = 1200,
) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    dirs_seen = 0
    queue: list[tuple[Path, int]] = [(root, 0) for root in roots]
    while queue and dirs_seen < max_dirs:
        current, depth = queue.pop(0)
        if depth > max_depth or current.name in GENERIC_SKIP_DIRS:
            continue
        dirs_seen += 1
        children = _safe_iterdir(current)
        for child in children:
            if _safe_is_file(child) and child.name in COMPOSE_FILENAMES:
                text = str(child)
                if text not in seen:
                    found.append(child)
                    seen.add(text)
            elif _safe_is_dir(child) and depth < max_depth and child.name not in GENERIC_SKIP_DIRS:
                queue.append((child, depth + 1))
    return found


def _scan_compose_files(roots: list[Path]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for path in _iter_compose_files(roots):
        text = _read_small_text(path, limit=300_000)
        for match in re.finditer(r"(?im)^\s*image:\s*[\"']?([^\"'\s#]+)", text):
            name = match.group(1).strip()
            if name:
                items.append({
                    "manager": "docker_compose",
                    "name": name,
                    "path": str(path),
                    "version": name.rsplit(":", 1)[-1] if ":" in name else "",
                    "description": "",
                })
    return {"roots": [str(root) for root in roots], "items": items}


def _package_manager_matches(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source_name, source in sources.items():
        for item in source.get("items", []):
            name = str(item.get("name") or "")
            system = _catalog_system_for_install_name(name)
            if not system:
                continue
            key = (system, source_name, name)
            if key in seen:
                continue
            seen.add(key)
            matches.append({
                "system": system,
                "display_name": (_catalog_entry(system) or {}).get("display_name") or system,
                "catalog_entry": _catalog_entry_summary(system),
                "manager": source_name,
                "name": name,
                "path": item.get("path", ""),
                "version": item.get("version", ""),
                "description": item.get("description", ""),
                "read_only": True,
                "source_read": False,
            })
    return matches


def build_package_manager_agent_inventory(
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    roots = _generic_scan_roots(resolved_home, resolved_env)
    sources = {
        "npm_global": _scan_npm_global(resolved_home, resolved_env),
        "pipx": _scan_pipx(resolved_home, resolved_env),
        "homebrew": _scan_homebrew(resolved_home, resolved_env),
        "docker_image": _scan_docker_images(resolved_env),
        "docker_compose": _scan_compose_files(roots),
    }
    matches = _package_manager_matches(sources)
    return {
        "ok": True,
        "contract": PACKAGE_MANAGER_INVENTORY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "source_read": False,
        "source_count": len(sources),
        "item_count": sum(len(source.get("items", [])) for source in sources.values()),
        "match_count": len(matches),
        "sources": sources,
        "matches": matches,
        "global_guarantees": {
            "does_not_install_packages": True,
            "does_not_write_platform_config": True,
            "does_not_parse_chat_bodies": True,
            "does_not_read_source_files": True,
        },
    }


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
    if name in SAFE_CONFIG_FILENAMES and re.search(r"\bmcpServers\b|\bmcp_servers\b|9851|zhiyi_recall", text):
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
    endpoint_signal = bool(re.search(r"127\.0\.0\.1:9851|localhost:9851|zhiyi_recall", text, re.I))
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
    queue: list[tuple[Path, int]] = [(root, 0) for root in roots]
    while queue and dirs_seen < max_dirs and files_seen < max_files:
        current, depth = queue.pop(0)
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


def _model_identity_hints_for_surface(surface: dict[str, Any]) -> dict[str, Any]:
    system = str(surface.get("system") or "").strip()
    display_name = str(surface.get("display_name") or "").strip()
    path_tokens: list[str] = []
    for key in ("config_paths", "workspace_paths", "content_store_paths", "installation_paths"):
        for path in surface.get(key, []) if isinstance(surface.get(key), list) else []:
            for part in Path(str(path)).parts[-6:]:
                cleaned = part.strip()
                if cleaned:
                    path_tokens.append(cleaned)
    variants = sorted(_identifier_variants(system) | _identifier_variants(display_name))
    for token in path_tokens[:24]:
        variants.extend(sorted(_identifier_variants(token)))
    variants = _compact_unique(variants, limit=32)
    known_alias = _catalog_system_for_install_name(system) or _catalog_system_for_install_name(display_name)
    catalog_entry = _catalog_entry(system) or (_catalog_entry(known_alias) if known_alias else {})
    aliases = _catalog_list(catalog_entry, "aliases") if catalog_entry else ()
    return {
        "surface_id": system,
        "display_name_hint": display_name,
        "visible_identifier_variants": variants,
        "path_name_tokens": _compact_unique(path_tokens, limit=24),
        "known_catalog_match": known_alias or (system if catalog_entry else ""),
        "known_display_name": catalog_entry.get("display_name", "") if catalog_entry else "",
        "known_aliases": list(aliases)[:20],
        "identity_hint_policy": (
            "Prefer a clear product/app name from surface_id, display_name_hint, "
            "path tokens, or known_catalog_match over Unknown."
        ),
    }


def _model_runtime_chain_item(
    *,
    source: str,
    configured: bool,
    role: str,
    independent: bool,
    provider: str = "",
    provider_id: str = "",
    model_name: str = "",
    transport: str = "",
) -> dict[str, Any]:
    return {
        "source": source,
        "configured": bool(configured),
        "role": role,
        "independent": bool(independent),
        "provider": provider,
        "provider_id": provider_id,
        "model_name": model_name,
        "transport": transport,
    }


def _model_runtime_from_block(
    block: dict[str, Any],
    *,
    source: str,
    independent: bool,
    default_provider: str = "",
    default_transport: str = "openai_compatible_http",
) -> dict[str, Any] | None:
    if not isinstance(block, dict) or _truthy(block.get("enabled")) is False and "enabled" in block:
        return None
    model_name = str(
        block.get("model_name")
        or block.get("model")
        or block.get("selected_model")
        or block.get("selected_option_id")
        or ""
    ).strip()
    option_id = str(block.get("selected_option_id") or model_name).strip()
    provider = str(block.get("provider") or default_provider or "").strip()
    provider_id = str(block.get("provider_id") or block.get("selected_provider") or "").strip()
    if not model_name and not option_id:
        return None
    return {
        "configured": True,
        "source": source,
        "selected_option_id": option_id,
        "provider": provider or "configured_model",
        "provider_id": provider_id,
        "model_name": model_name or option_id,
        "transport": str(block.get("transport") or default_transport or "openai_compatible_http"),
        "base_url": str(block.get("base_url") or block.get("endpoint") or "").strip(),
        "api_key_env": str(block.get("api_key_env") or "").strip(),
        "independent": bool(independent),
    }


def _transport_for_tiandao_api_mode(api_mode: str) -> str:
    normalized = str(api_mode or "").strip().lower()
    if normalized in {"openai-completions", "openai", "openai-compatible", "openai_compatible_http"}:
        return "openai_compatible_http"
    if normalized in {"anthropic-messages", "anthropic"}:
        return "anthropic_messages_http"
    if normalized == "gemini":
        return "gemini_http"
    if normalized == "ollama":
        return "ollama_http"
    return normalized or "openai_compatible_http"


def _model_runtime_from_tiandao_block(
    block: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any] | None:
    if not isinstance(block, dict) or _truthy(block.get("enabled")) is False and "enabled" in block:
        return None

    endpoints = block.get("endpoints") or block.get("model_endpoints") or block.get("connections")
    models = block.get("models") or block.get("model_assets") or block.get("assets")
    if not isinstance(endpoints, list) or not isinstance(models, list):
        return None

    try:
        from tiandao.model_identity import (
            api_mode_for_endpoint,
            build_tiandao_model_assets,
            provider_name_for_endpoint,
        )
    except Exception:
        return None

    endpoint_by_id = {
        str(endpoint.get("id") or ""): endpoint
        for endpoint in endpoints
        if isinstance(endpoint, dict)
    }
    model_items = [model for model in models if isinstance(model, dict)]
    assets = build_tiandao_model_assets(
        [endpoint for endpoint in endpoints if isinstance(endpoint, dict)],
        model_items,
    )
    selected = str(
        block.get("selected_model_asset_id")
        or block.get("selected_asset_id")
        or block.get("selected_option_id")
        or block.get("selected_model_id")
        or block.get("selected_model")
        or block.get("model_name")
        or ""
    ).strip()
    if selected:
        selected_asset = next(
            (
                asset
                for asset in assets
                if selected in {
                    str(asset.get("assetId") or ""),
                    str(asset.get("runtimeModelId") or ""),
                    str(asset.get("id") or ""),
                    str(asset.get("modelName") or ""),
                    str(asset.get("modelKey") or ""),
                }
            ),
            None,
        )
    else:
        selected_asset = assets[0] if len(assets) == 1 else None
    if not selected_asset:
        return None

    endpoint = endpoint_by_id.get(str(selected_asset.get("endpointId") or "")) or {}
    api_mode = str(selected_asset.get("apiMode") or api_mode_for_endpoint(endpoint)).strip()
    provider_name = str(selected_asset.get("providerName") or provider_name_for_endpoint(endpoint)).strip()
    runtime_model_id = str(
        selected_asset.get("runtimeModelId")
        or selected_asset.get("modelName")
        or selected_asset.get("id")
        or ""
    ).strip()
    if not runtime_model_id:
        return None

    base_url = str(
        block.get("base_url")
        or block.get("endpoint")
        or selected_asset.get("endpointBaseUrl")
        or endpoint.get("baseUrl")
        or ""
    ).strip()
    api_key_env = str(
        block.get("api_key_env")
        or selected_asset.get("apiKeyEnv")
        or selected_asset.get("api_key_env")
        or endpoint.get("apiKeyEnv")
        or endpoint.get("api_key_env")
        or ""
    ).strip()
    return {
        "configured": True,
        "source": source,
        "selected_option_id": str(selected_asset.get("assetId") or selected or runtime_model_id),
        "provider": provider_name or "tiandao_model_identity",
        "provider_id": str(endpoint.get("id") or selected_asset.get("endpointId") or provider_name),
        "model_name": runtime_model_id,
        "transport": _transport_for_tiandao_api_mode(api_mode),
        "base_url": base_url,
        "api_key_env": api_key_env,
        "independent": True,
        "tiandao_model_identity": {
            "asset_id": str(selected_asset.get("assetId") or ""),
            "connection_key": str(selected_asset.get("connectionKey") or ""),
            "endpoint_id": str(endpoint.get("id") or selected_asset.get("endpointId") or ""),
            "endpoint_name": str(selected_asset.get("endpointName") or endpoint.get("name") or ""),
            "endpoint_base_url": base_url,
            "api_mode": api_mode,
            "platform": str(selected_asset.get("platform") or endpoint.get("platform") or ""),
            "source_contract": "tiandao_model_identity",
        },
    }


def _tiandao_model_center_blocks(model_config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key in ("tiandao_model_center", "model_center", "tiandao_model_identity"):
        value = model_config.get(key)
        if isinstance(value, dict):
            candidates.append((f"model_config.{key}", value))
    tiandao_cfg = model_config.get("tiandao")
    if isinstance(tiandao_cfg, dict):
        for key in ("model_center", "model_identity"):
            value = tiandao_cfg.get(key)
            if isinstance(value, dict):
                candidates.append((f"model_config.tiandao.{key}", value))
    return candidates


def _inherited_platform_model_runtime(
    block: dict[str, Any],
    *,
    source: str,
    provider: str,
    transport: str,
) -> dict[str, Any] | None:
    if not isinstance(block, dict):
        return None
    selected_model = str(block.get("selected_model") or block.get("model_name") or block.get("model") or "").strip()
    selected_provider = str(block.get("selected_provider") or block.get("provider_id") or "").strip()
    if not selected_model:
        return None
    return {
        "configured": True,
        "source": source,
        "selected_option_id": f"configured-{provider.lower()}:{selected_provider or 'default'}:{selected_model}",
        "provider": provider,
        "provider_id": selected_provider,
        "model_name": selected_model,
        "transport": transport,
        "base_url": str(block.get("base_url") or block.get("endpoint") or "").strip(),
        "api_key_env": str(block.get("api_key_env") or "").strip(),
        "independent": False,
    }


def _model_identification_runtime(env: dict[str, str]) -> dict[str, Any]:
    memcore_root = _memcore_root_from_env(env)
    explicit_provider = str(env.get("MEMCORE_ZHIYI_PROVIDER") or env.get("MEMCORE_MODEL_IDENTIFICATION_PROVIDER") or "").strip()
    explicit_model = str(env.get("MEMCORE_ZHIYI_MODEL") or env.get("MEMCORE_MODEL_IDENTIFICATION_MODEL") or "").strip()
    explicit_transport = str(env.get("MEMCORE_ZHIYI_TRANSPORT") or env.get("MEMCORE_MODEL_IDENTIFICATION_TRANSPORT") or "openai_compatible_http")
    explicit_base_url = str(env.get("MEMCORE_ZHIYI_BASE_URL") or env.get("MEMCORE_MODEL_IDENTIFICATION_BASE_URL") or "").strip()
    explicit_zhiyi_configured = any(
        str(env.get(name) or "").strip()
        for name in ("MEMCORE_ZHIYI_PROVIDER", "MEMCORE_ZHIYI_MODEL", "MEMCORE_ZHIYI_TRANSPORT", "MEMCORE_ZHIYI_BASE_URL")
    )
    explicit_api_key_env = (
        "MEMCORE_ZHIYI_API_KEY"
        if explicit_zhiyi_configured or env.get("MEMCORE_ZHIYI_API_KEY")
        else "MEMCORE_MODEL_IDENTIFICATION_API_KEY"
    )
    chain: list[dict[str, Any]] = []
    if explicit_model:
        runtime = {
            "configured": True,
            "source": "env",
            "selected_option_id": explicit_model,
            "provider": explicit_provider or "configured_model",
            "provider_id": explicit_provider,
            "model_name": explicit_model,
            "transport": explicit_transport,
            "base_url": explicit_base_url,
            "api_key_env": explicit_api_key_env,
            "independent": True,
        }
        runtime["provider_chain"] = [
            _model_runtime_chain_item(
                source="env",
                configured=True,
                role="primary",
                independent=True,
                provider=runtime["provider"],
                provider_id=runtime["provider_id"],
                model_name=runtime["model_name"],
                transport=runtime["transport"],
            ),
        ]
        return runtime
    chain.append(_model_runtime_chain_item(
        source="env",
        configured=False,
        role="primary",
        independent=True,
        transport="openai_compatible_http",
    ))

    user_default = _load_json_object(memcore_root / "config" / "zhiyi_model_binding.user.json")
    user_runtime = _model_runtime_from_block(
        user_default,
        source="zhiyi_model_binding.user.json",
        independent=True,
    )
    if user_runtime:
        user_runtime["provider_chain"] = [
            *chain,
            _model_runtime_chain_item(
                source=user_runtime["source"],
                configured=True,
                role="primary",
                independent=True,
                provider=user_runtime["provider"],
                provider_id=user_runtime["provider_id"],
                model_name=user_runtime["model_name"],
                transport=user_runtime["transport"],
            ),
        ]
        return user_runtime
    chain.append(_model_runtime_chain_item(
        source="zhiyi_model_binding.user.json",
        configured=False,
        role="primary",
        independent=True,
        transport="openai_compatible_http",
    ))

    model_config = _load_json_object(memcore_root / "config" / "model_config.json")
    for key in ("zhiyi_model", "local_tool_identification", "model_identification", "ai_discovery"):
        config_runtime = _model_runtime_from_block(
            model_config.get(key) if isinstance(model_config.get(key), dict) else {},
            source=f"model_config.{key}",
            independent=True,
        )
        if config_runtime:
            config_runtime["provider_chain"] = [
                *chain,
                _model_runtime_chain_item(
                    source=config_runtime["source"],
                    configured=True,
                    role="primary",
                    independent=True,
                    provider=config_runtime["provider"],
                    provider_id=config_runtime["provider_id"],
                    model_name=config_runtime["model_name"],
                    transport=config_runtime["transport"],
                ),
            ]
            return config_runtime

    recall_cfg = model_config.get("recall") if isinstance(model_config.get("recall"), dict) else {}
    recall_identification = _model_runtime_from_block(
        recall_cfg.get("model_identification") if isinstance(recall_cfg.get("model_identification"), dict) else {},
        source="model_config.recall.model_identification",
        independent=True,
    )
    if recall_identification:
        recall_identification["provider_chain"] = [
            *chain,
            _model_runtime_chain_item(
                source=recall_identification["source"],
                configured=True,
                role="primary",
                independent=True,
                provider=recall_identification["provider"],
                provider_id=recall_identification["provider_id"],
                model_name=recall_identification["model_name"],
                transport=recall_identification["transport"],
            ),
        ]
        return recall_identification

    chain.append(_model_runtime_chain_item(
        source="model_config.zhiyi_model",
        configured=False,
        role="primary",
        independent=True,
        transport="openai_compatible_http",
    ))

    for source, block in _tiandao_model_center_blocks(model_config):
        tiandao_runtime = _model_runtime_from_tiandao_block(block, source=source)
        if tiandao_runtime:
            tiandao_runtime["provider_chain"] = [
                *chain,
                _model_runtime_chain_item(
                    source=tiandao_runtime["source"],
                    configured=True,
                    role="shared_tiandao_identity",
                    independent=True,
                    provider=tiandao_runtime["provider"],
                    provider_id=tiandao_runtime["provider_id"],
                    model_name=tiandao_runtime["model_name"],
                    transport=tiandao_runtime["transport"],
                ),
            ]
            return tiandao_runtime

    chain.append(_model_runtime_chain_item(
        source="model_config.tiandao_model_center",
        configured=False,
        role="shared_tiandao_identity",
        independent=True,
        transport="openai_compatible_http",
    ))

    inherited_sources = (
        (
            "model_config.openclaw_model",
            recall_cfg.get("openclaw_model") if isinstance(recall_cfg.get("openclaw_model"), dict) else {},
            "OpenClaw",
            "inherited_openclaw_model",
        ),
        (
            "model_config.hermes_model",
            recall_cfg.get("hermes_model") if isinstance(recall_cfg.get("hermes_model"), dict) else {},
            "Hermes",
            "inherited_hermes_model",
        ),
    )
    for source, block, provider, transport in inherited_sources:
        runtime = _inherited_platform_model_runtime(
            block,
            source=source,
            provider=provider,
            transport=transport,
        )
        if runtime:
            role = "optional_inherited"
            runtime["provider_chain"] = [
                *chain,
                _model_runtime_chain_item(
                    source=source,
                    configured=True,
                    role=role,
                    independent=False,
                    provider=provider,
                    provider_id=runtime["provider_id"],
                    model_name=runtime["model_name"],
                    transport=transport,
                ),
            ]
            return runtime

    optional_chain = []
    for source, _block, provider, transport in inherited_sources:
        optional_chain.append(_model_runtime_chain_item(
            source=source,
            configured=False,
            role="optional_inherited",
            independent=False,
            provider=provider,
            transport=transport,
        ))

    return {
        "configured": False,
        "source": "not_configured",
        "selected_option_id": "",
        "provider": "",
        "provider_id": "",
        "model_name": "",
        "transport": "",
        "base_url": "",
        "api_key_env": "",
        "independent": True,
        "provider_chain": [
            *chain,
            *optional_chain,
        ],
    }
def _signal_metadata_for_model(signal: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = (
        "kind",
        "role",
        "artifact_format",
        "path_pattern",
        "reported_keys",
        "mcp_detected",
        "mcp_server_names",
        "memcore_mcp_detected",
        "memcore_mcp_server_names",
        "intent_signal_detected",
        "manager",
        "name",
        "version",
        "app_installed",
        "cli_installed",
        "complete_conversation_candidate",
        "assistant_replies_may_persist",
    )
    metadata = {key: signal.get(key) for key in allowed_keys if key in signal}
    if signal.get("path"):
        metadata["path_tail"] = _path_tail(str(signal.get("path")))
    return metadata


def _surface_metadata_for_model(surface: dict[str, Any]) -> dict[str, Any]:
    signals = [
        _signal_metadata_for_model(signal)
        for signal in surface.get("signals", [])[:12]
        if isinstance(signal, dict)
    ]
    software = surface.get("software") if isinstance(surface.get("software"), dict) else {}
    app = software.get("app") if isinstance(software.get("app"), dict) else {}
    cli = software.get("cli") if isinstance(software.get("cli"), dict) else {}
    return {
        "surface_id": surface.get("system", ""),
        "display_name_hint": surface.get("display_name", ""),
        "identity_hints": _model_identity_hints_for_surface(surface),
        "source": surface.get("source", ""),
        "platform_family_hint": surface.get("platform_family", ""),
        "catalog_driven": bool(surface.get("catalog_driven")),
        "mcp_config_detected": bool(surface.get("mcp_config_detected")),
        "memcore_mcp_detected": bool(surface.get("memcore_mcp_detected")),
        "intent_signal_detected": bool(surface.get("intent_signal_detected")),
        "config_file_names": _compact_unique(Path(path).name for path in surface.get("config_paths", [])),
        "config_path_tails": _compact_unique(_path_tail(path) for path in surface.get("config_paths", [])),
        "workspace_path_tails": _compact_unique(_path_tail(path) for path in surface.get("workspace_paths", [])),
        "content_store_path_tails": _compact_unique(_path_tail(path) for path in surface.get("content_store_paths", [])),
        "installation_path_tails": _compact_unique(_path_tail(path) for path in surface.get("installation_paths", [])),
        "app_bundle": {
            "installed": bool(app.get("installed")),
            "name": Path(str(app.get("bundle_path") or "")).name if app.get("bundle_path") else "",
            "version": str(app.get("version") or ""),
        },
        "cli_binary": {
            "installed": bool(cli.get("installed")),
            "name": Path(str(cli.get("path") or "")).name if cli.get("path") else "",
            "version": str(cli.get("version") or ""),
        },
        "signals": signals,
        "chat_body_included": False,
        "raw_excerpt_included": False,
    }


def _category_from_family(family: Any) -> str:
    family_text = str(family or "").lower()
    if "cli" in family_text:
        return "agent_cli"
    if "ide" in family_text or "editor" in family_text:
        return "editor_agent"
    if "desktop" in family_text or "app" in family_text:
        return "agent_app"
    if "panel" in family_text:
        return "agent_panel"
    if "mcp" in family_text or "config" in family_text:
        return "agent_config_surface"
    return "unknown"


def _storage_candidate_for_surface(surface: dict[str, Any]) -> str:
    for key in ("content_store_paths", "workspace_paths", "config_paths", "installation_paths"):
        values = surface.get(key)
        if isinstance(values, list) and values:
            return _path_tail(str(values[0]))
    return ""


def _rule_identification_result(surface: dict[str, Any]) -> dict[str, Any]:
    catalog_driven = bool(surface.get("catalog_driven"))
    mcp_detected = bool(surface.get("mcp_config_detected"))
    intent_detected = bool(surface.get("intent_signal_detected"))
    confidence = 0.9 if catalog_driven else 0.62 if (mcp_detected or intent_detected) else 0.45
    if str(surface.get("source") or "").startswith("verified_storage"):
        confidence = max(confidence, 0.86)
    return {
        "likely_name": surface.get("display_name") or surface.get("system") or "Unknown local AI tool",
        "category": _category_from_family(surface.get("platform_family")),
        "supports_mcp_likely": mcp_detected or "mcp" in str(surface.get("platform_family") or "").lower(),
        "skill_surface_likely": any(
            isinstance(signal, dict) and "skill" in str(signal.get("kind") or "").lower()
            for signal in surface.get("signals", [])
        ),
        "storage_candidate": _storage_candidate_for_surface(surface),
        "confidence": round(confidence, 2),
        "reason": (
            "matched verified local catalog or storage pattern"
            if confidence >= 0.86
            else "matched local config or MCP-shaped metadata"
            if confidence >= 0.6
            else "only weak local metadata was available"
        ),
    }


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _normalize_model_confidence(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(float(value), 1.0))
    text = str(value or "").strip().lower()
    if not text:
        return 0.0
    word_values = {
        "very high": 0.95,
        "high": 0.85,
        "medium": 0.6,
        "moderate": 0.6,
        "low": 0.3,
        "very low": 0.15,
        "unknown": 0.0,
    }
    if text in word_values:
        return word_values[text]
    try:
        numeric = float(text.rstrip("%"))
    except Exception:
        return 0.0
    if numeric > 1.0:
        numeric = numeric / 100.0
    return max(0.0, min(numeric, 1.0))


def _is_unknown_model_name(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {
        "",
        "unknown",
        "unknown local ai tool",
        "unknown local tool",
        "unknown tool",
        "local ai tool",
    }


def _visible_identity_name(metadata: dict[str, Any]) -> str:
    hints = metadata.get("identity_hints") if isinstance(metadata.get("identity_hints"), dict) else {}
    for key in ("known_display_name", "display_name_hint", "surface_id"):
        value = str(hints.get(key) or metadata.get(key) or "").strip()
        if value and not _is_unknown_model_name(value):
            return value.replace("_", " ").replace("-", " ").title()
    return ""


def _repair_model_identification_result(
    result: dict[str, Any],
    *,
    rule_result: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    repaired = dict(result)
    if _is_unknown_model_name(repaired.get("likely_name")):
        visible_name = _visible_identity_name(metadata)
        if visible_name:
            repaired["likely_name"] = visible_name
            repaired["visible_identity_fallback_applied"] = True
            repaired["reason"] = (
                f"{repaired.get('reason') or 'model returned unknown'}; "
                "used visible local identifier"
            )
            repaired["confidence"] = max(
                _normalize_model_confidence(rule_result.get("confidence")),
                min(_normalize_model_confidence(repaired.get("confidence")), 0.78),
            )
    if str(repaired.get("category") or "").strip().lower() == "unknown" and rule_result.get("category"):
        repaired["category"] = rule_result.get("category")
    repaired["confidence"] = _normalize_model_confidence(repaired.get("confidence", 0.0))
    return repaired


def _parse_model_identification_response(text: str) -> dict[str, Any]:
    data = None
    parse_error = ""
    for candidate in _json_object_candidates(text):
        try:
            data = json.loads(candidate)
            break
        except Exception as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
    if data is None:
        return {
            "ok": False,
            "error": "model_response_not_json",
            "parse_error": parse_error,
            "raw_preview": text[:500],
        }
    if not isinstance(data, dict):
        return {
            "ok": False,
            "error": "model_response_not_object",
            "raw_type": type(data).__name__,
        }
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    allowed = {
        "likely_name",
        "category",
        "supports_mcp_likely",
        "skill_surface_likely",
        "storage_candidate",
        "confidence",
        "reason",
    }
    normalized = {key: result.get(key) for key in allowed if key in result}
    if not normalized.get("likely_name"):
        normalized["likely_name"] = "Unknown local AI tool"
    if not normalized.get("category"):
        normalized["category"] = "unknown"
    normalized["confidence"] = _normalize_model_confidence(normalized.get("confidence", 0.0))
    return {
        "ok": True,
        "result": normalized,
        "raw_keys": sorted(str(key) for key in data.keys()),
    }


def _json_object_candidates(text: str) -> list[str]:
    stripped = str(text or "").strip()
    if not stripped:
        return []
    candidates = [stripped]
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", stripped, re.I | re.S):
        fenced = match.group(1).strip()
        if fenced and fenced not in candidates:
            candidates.append(fenced)
    for candidate in _balanced_json_objects(stripped):
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _balanced_json_objects(text: str) -> list[str]:
    results: list[str] = []
    for start, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            current = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    results.append(text[start : index + 1])
                    break
    return results[:5]


def _run_model_identification_command(
    request_envelope: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any] | None:
    command = str(
        env.get("MEMCORE_ZHIYI_MODEL_COMMAND")
        or env.get("MEMCORE_MODEL_IDENTIFICATION_COMMAND")
        or ""
    ).strip()
    if not command:
        return None
    try:
        timeout = int(str(
            env.get("MEMCORE_ZHIYI_MODEL_TIMEOUT_SECONDS")
            or env.get("MEMCORE_MODEL_IDENTIFICATION_TIMEOUT_SECONDS")
            or "45"
        ))
    except Exception:
        timeout = 45
    payload = json.dumps(
        {"request_envelope": request_envelope},
        ensure_ascii=False,
        sort_keys=True,
    )
    try:
        completed = subprocess.run(
            shlex.split(command),
            input=payload,
            text=True,
            capture_output=True,
            timeout=max(1, min(timeout, 120)),
            check=False,
        )
    except Exception as exc:
        return {
            "ok": False,
            "executor": "local_command",
            "model_call_performed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    parsed = _parse_model_identification_response(completed.stdout.strip())
    return {
        "ok": completed.returncode == 0 and bool(parsed.get("ok")),
        "executor": "local_command",
        "model_call_performed": completed.returncode == 0,
        "returncode": completed.returncode,
        "stderr_preview": completed.stderr[:500],
        **parsed,
    }


def _provider_env_candidates(provider: str, provider_id: str) -> tuple[list[str], list[str], str]:
    marker = f"{provider} {provider_id}".lower()
    if "deepseek" in marker:
        return (
            ["MEMCORE_ZHIYI_API_KEY", "MEMCORE_MODEL_IDENTIFICATION_API_KEY", "DEEPSEEK_API_KEY"],
            ["MEMCORE_ZHIYI_BASE_URL", "MEMCORE_MODEL_IDENTIFICATION_BASE_URL", "DEEPSEEK_BASE_URL"],
            "https://api.deepseek.com/v1",
        )
    if "minimax" in marker or "mimo" in marker:
        return (
            ["MEMCORE_ZHIYI_API_KEY", "MEMCORE_MODEL_IDENTIFICATION_API_KEY", "MINIMAX_API_KEY", "MINIMAX_CN_API_KEY"],
            ["MEMCORE_ZHIYI_BASE_URL", "MEMCORE_MODEL_IDENTIFICATION_BASE_URL", "MINIMAX_BASE_URL", "MINIMAX_CN_BASE_URL"],
            "https://api.minimaxi.com/v1",
        )
    if "openai" in marker:
        return (
            ["MEMCORE_ZHIYI_API_KEY", "MEMCORE_MODEL_IDENTIFICATION_API_KEY", "OPENAI_API_KEY"],
            ["MEMCORE_ZHIYI_BASE_URL", "MEMCORE_MODEL_IDENTIFICATION_BASE_URL", "OPENAI_BASE_URL"],
            "https://api.openai.com/v1",
        )
    return (
        ["MEMCORE_ZHIYI_API_KEY", "MEMCORE_MODEL_IDENTIFICATION_API_KEY"],
        ["MEMCORE_ZHIYI_BASE_URL", "MEMCORE_MODEL_IDENTIFICATION_BASE_URL"],
        "",
    )


def _first_env_value(env: dict[str, str], names: list[str]) -> str:
    for name in names:
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return ""


def _run_openai_compatible_model_identification(
    request_envelope: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any] | None:
    transport = str(request_envelope.get("transport") or "openai_compatible_http").strip().lower()
    if transport and transport not in {"openai_compatible_http", "openai-compatible", "openai"}:
        return None
    provider = str(request_envelope.get("provider") or "")
    provider_id = str(request_envelope.get("provider_id") or "")
    model_name = str(request_envelope.get("model_name") or "").strip()
    key_names, base_names, default_base_url = _provider_env_candidates(provider, provider_id)
    explicit_key_env = str(request_envelope.get("api_key_env") or "").strip()
    api_key = str(env.get(explicit_key_env) or "").strip() if explicit_key_env else ""
    if not api_key:
        api_key = _first_env_value(env, key_names)
    base_url = str(request_envelope.get("base_url") or "").strip()
    if not base_url:
        base_url = _first_env_value(env, base_names) or default_base_url
    if not api_key or not base_url or not model_name:
        return None
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    payload = {
        "model": model_name,
        "messages": request_envelope.get("messages", []),
        "temperature": 0,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        timeout = int(str(
            env.get("MEMCORE_ZHIYI_MODEL_TIMEOUT_SECONDS")
            or env.get("MEMCORE_MODEL_IDENTIFICATION_TIMEOUT_SECONDS")
            or "45"
        ))
    except Exception:
        timeout = 45
    try:
        with urllib.request.urlopen(req, timeout=max(1, min(timeout, 120))) as response:
            body = response.read(2_000_000).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "executor": "openai_compatible_http",
            "model_call_performed": True,
            "status_code": exc.code,
            "error": exc.read(2000).decode("utf-8", errors="ignore"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "executor": "openai_compatible_http",
            "model_call_performed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        payload_obj = json.loads(body)
        content = payload_obj["choices"][0]["message"]["content"]
    except Exception:
        return {
            "ok": False,
            "executor": "openai_compatible_http",
            "model_call_performed": True,
            "error": "chat_completion_response_missing_message_content",
            "raw_preview": body[:500],
        }
    parsed = _parse_model_identification_response(str(content).strip())
    return {
        "ok": bool(parsed.get("ok")),
        "executor": "openai_compatible_http",
        "model_call_performed": True,
        **parsed,
    }


def _execute_model_identification_request(
    request_envelope: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    command_result = _run_model_identification_command(request_envelope, env)
    if command_result is not None:
        return command_result
    http_result = _run_openai_compatible_model_identification(request_envelope, env)
    if http_result is not None:
        return http_result
    transport = str(request_envelope.get("transport") or "").strip()
    if transport and transport not in {"openai_compatible_http", "openai-compatible", "openai"}:
        return {
            "ok": False,
            "executor": "unsupported_transport",
            "model_call_performed": False,
            "error": f"unsupported_model_identification_transport:{transport}",
        }
    return {
        "ok": False,
        "executor": "not_configured",
        "model_call_performed": False,
        "error": "model_identification_executor_not_configured",
    }


def _build_model_identification(
    surface: dict[str, Any],
    env: dict[str, str],
    *,
    execute_model: bool = False,
) -> dict[str, Any]:
    rule_result = _rule_identification_result(surface)
    metadata = _surface_metadata_for_model(surface)
    runtime = _model_identification_runtime(env)
    needs_model = not bool(surface.get("catalog_driven")) or float(rule_result.get("confidence") or 0.0) < 0.75
    base = {
        "contract": MODEL_IDENTIFICATION_CONTRACT,
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "input_kind": "local_metadata_only",
        "local_scanner_role": "collect_paths_configs_package_and_marker_metadata",
        "model_role": "identify_unknown_or_low_confidence_local_ai_tool",
        "chat_body_included": False,
        "raw_excerpt_included": False,
        "rule_result": rule_result,
        "local_metadata": metadata,
    }
    if not needs_model:
        return {
            **base,
            "enabled": False,
            "mode": "rules_confident",
            "reason": "local_rules_already_identified_surface",
            "configured_model": {
                "configured": bool(runtime.get("configured")),
                "source": runtime.get("source", ""),
                "provider": runtime.get("provider", ""),
                "provider_id": runtime.get("provider_id", ""),
                "model_name": runtime.get("model_name", ""),
                "transport": runtime.get("transport", ""),
                "independent": bool(runtime.get("independent", True)),
                "provider_chain": runtime.get("provider_chain", []),
            },
            "result": rule_result,
        }
    if not runtime.get("configured"):
        return {
            **base,
            "enabled": False,
            "mode": "fallback_rules",
            "reason": "model_not_configured",
            "configured_model": {
                "configured": False,
                "source": runtime.get("source", "not_configured"),
                "provider": "",
                "provider_id": "",
                "model_name": "",
                "transport": "",
                "independent": True,
                "provider_chain": runtime.get("provider_chain", []),
            },
            "result": rule_result,
        }
    request_envelope = {
        "schema_version": "1.0",
        "request_kind": "local_ai_tool_identification",
        "task_kind": "identify_local_ai_tool_from_metadata",
        "selected_option_id": runtime.get("selected_option_id", ""),
        "provider": runtime.get("provider", ""),
        "provider_id": runtime.get("provider_id", ""),
        "model_name": runtime.get("model_name", ""),
        "transport": runtime.get("transport", ""),
        "base_url": runtime.get("base_url", ""),
        "api_key_env": runtime.get("api_key_env", ""),
        "independent_provider": bool(runtime.get("independent", True)),
        "provider_chain": runtime.get("provider_chain", []),
        "messages": [
            {
                "role": "system",
                "content": (
                    "Identify the local AI coding tool or agent surface from local metadata only. "
                    "Return only a JSON object. Do not infer from chat bodies. "
                    "Use visible identifiers such as surface_id, display_name_hint, path_name_tokens, "
                    "config_file_names, known_catalog_match, and app or CLI names. "
                    "If the visible identifier is a product-like name, return that name instead of "
                    "Unknown local AI tool, even when the exact platform is not in your prior knowledge. "
                    "Set confidence as a number from 0 to 1."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            },
        ],
        "expected_response_schema": {
            "likely_name": "string",
            "category": "agent_ide|agent_cli|editor_agent|agent_panel|agent_app|agent_config_surface|unknown",
            "supports_mcp_likely": "boolean",
            "skill_surface_likely": "boolean",
            "storage_candidate": "string",
            "confidence": "number",
            "reason": "string",
        },
        "request_sent": False,
        "response_received": False,
        "model_call_performed": False,
    }
    response = {
        **base,
        "enabled": True,
        "mode": "configured_model",
        "reason": "model_configured_for_unknown_or_low_confidence_surface",
        "configured_model": {
            "configured": True,
            "source": runtime.get("source", ""),
            "provider": runtime.get("provider", ""),
            "provider_id": runtime.get("provider_id", ""),
            "model_name": runtime.get("model_name", ""),
            "transport": runtime.get("transport", ""),
            "independent": bool(runtime.get("independent", True)),
            "provider_chain": runtime.get("provider_chain", []),
        },
        "request_envelope": request_envelope,
        "result": {
            **rule_result,
            "status": "pending_model_identification",
            "provisional": True,
        },
    }
    if not execute_model:
        return response
    execution = _execute_model_identification_request(request_envelope, env)
    response["executor"] = execution.get("executor", "")
    response["model_call_performed"] = bool(execution.get("model_call_performed"))
    response["request_envelope"] = {
        **request_envelope,
        "request_sent": bool(execution.get("model_call_performed")),
        "response_received": bool(execution.get("ok")),
        "model_call_performed": bool(execution.get("model_call_performed")),
    }
    if execution.get("ok") and isinstance(execution.get("result"), dict):
        model_result = _repair_model_identification_result(
            execution["result"],
            rule_result=rule_result,
            metadata=metadata,
        )
        response["result"] = {
            **rule_result,
            **model_result,
            "status": "identified_by_model",
            "provisional": False,
        }
        response["execution"] = {
            "ok": True,
            "executor": execution.get("executor", ""),
            "model_call_performed": bool(execution.get("model_call_performed")),
        }
        return response
    response["result"] = {
        **rule_result,
        "status": "model_identification_failed_fallback_rules",
        "provisional": True,
    }
    response["execution"] = {
        "ok": False,
        "executor": execution.get("executor", ""),
        "model_call_performed": bool(execution.get("model_call_performed")),
        "error": execution.get("error", "model_identification_failed"),
    }
    return response


def _candidate_connection_status(system: str, surface: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    config_paths = list(surface.get("config_paths") or [])
    supports_mcp = bool(result.get("supports_mcp_likely")) or bool(surface.get("mcp_config_detected"))
    apply_ready = system in _implemented_apply_systems()
    if supports_mcp and config_paths and apply_ready:
        next_step = "auto_connect"
    elif supports_mcp and config_paths:
        next_step = "create_thin_adapter_from_candidate"
    elif supports_mcp:
        next_step = "locate_mcp_config_surface"
    else:
        next_step = "observe_storage_shape"
    return {
        "supports_mcp_likely": supports_mcp,
        "skill_surface_likely": bool(result.get("skill_surface_likely")),
        "config_paths": config_paths,
        "auto_connect_supported_now": bool(supports_mcp and config_paths and apply_ready),
        "apply_endpoint_status": _apply_endpoint_status_for_system(system),
        "next_step": next_step,
    }


def _candidate_native_artifact_format(system: str, surface: dict[str, Any]) -> str:
    preferred_roles = {"content_store", "app_data", "project_artifacts", "workspace"}
    signals = [signal for signal in surface.get("signals", []) if isinstance(signal, dict)]
    for signal in signals:
        artifact_format = str(signal.get("artifact_format") or "").strip()
        if artifact_format and signal.get("complete_conversation_candidate") is True:
            return artifact_format
    for signal in signals:
        artifact_format = str(signal.get("artifact_format") or "").strip()
        role = str(signal.get("role") or "").strip()
        if artifact_format and role in preferred_roles:
            return artifact_format
    for storage_item in _verified_storage_patterns(system):
        role = str(storage_item.get("role") or "").strip()
        artifact_format = str(storage_item.get("artifact_format") or "").strip()
        if artifact_format and role in preferred_roles:
            return artifact_format
    return f"{_slug(system)}_native_store"


def _candidate_next_actions(connection: dict[str, Any], collector_status: str, boundary: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    next_step = str(connection.get("next_step") or "")
    if next_step:
        actions.append(next_step)
    if collector_status == "verified_collector_required":
        actions.append("create_verified_format_collector")
    if boundary.get("complete_conversation_candidate"):
        actions.append("verify_assistant_reply_roundtrip")
    actions.append("write_computer_first_raw_archive_after_verified_collection")
    return list(dict.fromkeys(actions))


def _build_adapter_draft(
    *,
    system: str,
    display_name: str,
    surface: dict[str, Any],
    result: dict[str, Any],
    connection: dict[str, Any],
    recognized_by: str,
    recognition_mode: str,
    confidence: float,
) -> dict[str, Any]:
    content_store_paths = list(surface.get("content_store_paths") or [])
    workspace_paths = list(surface.get("workspace_paths") or [])
    boundary = surface.get("conversation_memory_boundary") or _conversation_memory_boundary(
        system,
        [*content_store_paths, *workspace_paths],
    )
    collector_required = bool(content_store_paths or workspace_paths or boundary.get("complete_conversation_candidate"))
    collector_status = "verified_collector_required" if collector_required else "no_content_store_detected"
    native_artifact_format = _candidate_native_artifact_format(system, surface)
    return {
        "contract": ADAPTER_DRAFT_CONTRACT,
        "draft_type": "local_ai_tool_adapter_draft",
        "draft_id": _slug(f"{system}-{display_name}-draft"),
        "status": "draft_ready",
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "recognition": {
            "recognized_by": recognized_by,
            "recognition_mode": recognition_mode,
            "confidence": round(confidence, 2),
            "model_status": result.get("status", ""),
            "reason": result.get("reason", ""),
        },
        "mcp": {
            "supports_mcp_likely": bool(connection.get("supports_mcp_likely")),
            "skill_surface_likely": bool(connection.get("skill_surface_likely")),
            "config_paths": list(surface.get("config_paths") or []),
            "candidate_config_patterns": list(_catalog_mcp_config_patterns(system))[:12],
            "auto_connect_supported_now": bool(connection.get("auto_connect_supported_now")),
            "apply_endpoint_status": connection.get("apply_endpoint_status", ""),
            "next_step": connection.get("next_step", ""),
        },
        "collector": {
            "collector_status": collector_status,
            "collector_kind": "verified_format_collector",
            "parser_gate": boundary.get("parser_gate", "verified_format_collector_required"),
            "native_artifact_format": native_artifact_format,
            "storage_candidate": result.get("storage_candidate") or _storage_candidate_for_surface(surface),
            "content_store_paths": content_store_paths,
            "workspace_paths": workspace_paths,
            "complete_conversation_candidate": bool(boundary.get("complete_conversation_candidate")),
            "assistant_replies_may_persist": boundary.get("assistant_replies_may_persist", False),
            "assistant_reply_persistence": boundary.get("assistant_reply_persistence", "unverified"),
            "content_read": False,
            "chat_body_included": False,
            "raw_excerpt_included": False,
        },
        "raw_archive": {
            "layout": "computer_first",
            "effective_from_version": "2026.6.1",
            "segment_order": ["computer_name", "source_system", "native_artifact_format"],
            "source_system": system,
            "native_artifact_format": native_artifact_format,
            "preferred_template": "memory/{computer_name}/{source_system}/{native_artifact_format}/{native_scope}/{session_id}.jsonl",
            "legacy_layout_allowed_for_new_writes": False,
        },
        "conversation_memory_boundary": boundary,
        "next_actions": _candidate_next_actions(connection, collector_status, boundary),
    }


def _build_provisional_adapter_candidate(surface: dict[str, Any]) -> dict[str, Any]:
    system = str(surface.get("system") or "unknown_surface")
    identification = surface.get("model_identification") if isinstance(surface.get("model_identification"), dict) else {}
    result = identification.get("result") if isinstance(identification.get("result"), dict) else _rule_identification_result(surface)
    mode = str(identification.get("mode") or "fallback_rules")
    recognized_by = "model" if mode == "configured_model" and result.get("status") == "identified_by_model" else "local_rules"
    display_name = str(result.get("likely_name") or surface.get("display_name") or system)
    category = str(result.get("category") or surface.get("platform_family") or "unknown")
    confidence = result.get("confidence", 0.0)
    try:
        confidence_value = float(confidence)
    except Exception:
        confidence_value = 0.0
    connection = _candidate_connection_status(system, surface, result)
    content_store_paths = list(surface.get("content_store_paths") or [])
    workspace_paths = list(surface.get("workspace_paths") or [])
    adapter_draft = _build_adapter_draft(
        system=system,
        display_name=display_name,
        surface=surface,
        result=result,
        connection=connection,
        recognized_by=recognized_by,
        recognition_mode=mode,
        confidence=confidence_value,
    )
    candidate = {
        "contract": PROVISIONAL_ADAPTER_CANDIDATE_CONTRACT,
        "candidate_type": "provisional_adapter_candidate",
        "candidate_id": _slug(f"{system}-{display_name}"),
        "system": system,
        "display_name": display_name,
        "source_surface": surface.get("source", ""),
        "recognized_by": recognized_by,
        "recognition_mode": mode,
        "confidence": round(confidence_value, 2),
        "category": category,
        "reason": result.get("reason", ""),
        "status": "candidate_ready",
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "connection": connection,
        "adapter_draft": adapter_draft,
        "storage": {
            "storage_candidate": result.get("storage_candidate") or _storage_candidate_for_surface(surface),
            "content_store_paths": content_store_paths,
            "workspace_paths": workspace_paths,
            "conversation_memory_boundary": surface.get("conversation_memory_boundary") or _conversation_memory_boundary(
                system,
                [*content_store_paths, *workspace_paths],
            ),
            "parser_gate": "verified_format_collector_required",
            "content_read": False,
            "chat_body_included": False,
            "raw_excerpt_included": False,
        },
        "next_step": connection["next_step"],
    }
    return candidate


def _refresh_catalog_surface_metadata(surface: dict[str, Any], system: str) -> None:
    entry = _catalog_entry(system)
    if not entry:
        return
    surface["display_name"] = entry.get("display_name") or surface.get("display_name") or system
    surface["catalog_driven"] = True
    surface["catalog_entry"] = _catalog_entry_summary(system)
    surface["platform_family"] = entry.get("family", surface.get("platform_family"))


def build_generic_local_ai_surfaces(
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    execute_model_identification: bool = False,
    scan_mode: str = "deep",
    model_execute_limit: int | None = None,
) -> dict[str, Any]:
    resolved_scan_mode = _normalize_generic_scan_mode(scan_mode)
    execute_limit = _normalize_execute_limit(
        model_execute_limit,
        default=DEFAULT_MODEL_IDENTIFICATION_EXECUTE_LIMIT,
    )
    remaining_model_calls = execute_limit
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    roots = _generic_scan_roots(resolved_home, resolved_env)
    package_inventory = build_package_manager_agent_inventory(home=resolved_home, env=resolved_env)
    surfaces: dict[str, dict[str, Any]] = {}
    seen_config_paths: set[str] = set()
    for system in _verified_storage_systems():
        for storage_item in _verified_storage_patterns(system):
            paths = storage_item.get("paths") if isinstance(storage_item.get("paths"), list) else []
            for pattern in [str(path) for path in paths if _looks_like_path_pattern(str(path))]:
                for path in _expanded_catalog_pattern_paths(pattern, home=resolved_home, env=resolved_env, roots=roots):
                    if not _safe_exists(path):
                        continue
                    surface = surfaces.setdefault(system, _generic_surface_record(system, source="verified_storage_patterns"))
                    _refresh_catalog_surface_metadata(surface, system)
                    _record_verified_storage_path(
                        surface,
                        system=system,
                        path=path,
                        storage_item=storage_item,
                        path_pattern=pattern,
                    )
                    if str(path) in surface.get("config_paths", []):
                        seen_config_paths.add(str(path))
    for system, path in _iter_catalog_config_candidates(roots, resolved_home, resolved_env):
        probe = _config_probe(path)
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="catalog_mcp_config_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        path_text = str(path)
        seen_config_paths.add(path_text)
        if path_text not in surface["config_paths"]:
            surface["config_paths"].append(path_text)
        surface["signals"].append({**probe, "catalog_driven": True})
        surface["mcp_config_detected"] = surface["mcp_config_detected"] or bool(probe.get("mcp_detected"))
        surface["memcore_mcp_detected"] = surface["memcore_mcp_detected"] or bool(probe.get("memcore_mcp_detected"))
        surface["intent_signal_detected"] = surface["intent_signal_detected"] or bool(probe.get("intent_signal_detected"))
        surface["connectable_now"] = surface["connectable_now"] or bool(probe.get("memcore_mcp_detected"))
    if resolved_scan_mode == "deep":
        generic_config_candidates = _iter_generic_config_candidates(roots)
        generic_workspace_candidates = _iter_generic_workspace_candidates(roots)
        git_repo_candidates = _iter_git_repo_candidates(roots)
        limits = {
            "max_depth": 5,
            "max_dirs": 500,
            "max_workspace_dirs": 3000,
            "max_files": 800,
        }
    elif resolved_scan_mode == "smart":
        generic_config_candidates = _iter_generic_config_candidates(
            roots,
            max_depth=2,
            max_dirs=160,
            max_files=300,
        )
        generic_workspace_candidates = _iter_generic_workspace_candidates(
            roots,
            max_depth=2,
            max_dirs=260,
        )
        git_repo_candidates = _iter_git_repo_candidates(
            roots,
            max_depth=2,
            max_dirs=260,
        )
        limits = {
            "max_depth": 2,
            "max_dirs": 160,
            "max_workspace_dirs": 260,
            "max_files": 300,
        }
    else:
        generic_config_candidates = []
        generic_workspace_candidates = []
        git_repo_candidates = []
        limits = {
            "full_scan_endpoint": "/api/v1/platforms/generic-local-ai-surfaces?scan=full",
        }
    for path in generic_config_candidates:
        if str(path) in seen_config_paths:
            continue
        probe = _config_probe(path)
        if not probe.get("mcp_detected") and not probe.get("intent_signal_detected"):
            continue
        system = _infer_surface_id(path, resolved_home)
        if _is_infrastructure_surface_id(system):
            continue
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="generic_mcp_config_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        path_text = str(path)
        if path_text not in surface["config_paths"]:
            surface["config_paths"].append(path_text)
        surface["signals"].append(probe)
        surface["mcp_config_detected"] = surface["mcp_config_detected"] or bool(probe.get("mcp_detected"))
        surface["memcore_mcp_detected"] = surface["memcore_mcp_detected"] or bool(probe.get("memcore_mcp_detected"))
        surface["intent_signal_detected"] = surface["intent_signal_detected"] or bool(probe.get("intent_signal_detected"))
        surface["connectable_now"] = surface["connectable_now"] or bool(probe.get("memcore_mcp_detected"))
    for path in generic_workspace_candidates:
        system = _infer_surface_id(path, resolved_home)
        if _is_infrastructure_surface_id(system):
            continue
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="generic_workspace_surface_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        _record_workspace_surface_path(surface, path)
        if system == "kiro":
            for candidate in _kiro_workspace_session_candidates(path):
                if _safe_is_dir(candidate):
                    _record_kiro_native_workspace_sessions(surface, candidate)
    for repo_path in git_repo_candidates:
        system = _catalog_system_for_repo(repo_path)
        if not system:
            continue
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="github_watchlist_repo_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        path_text = str(repo_path)
        if path_text not in surface["workspace_paths"]:
            surface["workspace_paths"].append(path_text)
        surface["signals"].append({
            "kind": "github_watchlist_repo",
            "path": path_text,
            "repo_config_read": True,
            "source_read": False,
            "parser_gate": "not_applicable_repo_metadata_only",
        })
    for match in package_inventory.get("matches", []):
        system = str(match.get("system") or "")
        if not system:
            continue
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="package_manager_inventory"))
        _refresh_catalog_surface_metadata(surface, system)
        install_path = str(match.get("path") or "")
        if install_path and install_path not in surface["installation_paths"]:
            surface["installation_paths"].append(install_path)
        surface["signals"].append({
            "kind": "package_manager_install",
            "manager": match.get("manager", ""),
            "name": match.get("name", ""),
            "path": install_path,
            "version": match.get("version", ""),
            "source_read": False,
            "content_read": False,
        })
    for system in _platform_catalog_entries():
        if system in surfaces:
            continue
        app = _app_bundle_metadata(system, resolved_home, resolved_env)
        cli = _cli_version_metadata(system, resolved_home, resolved_env)
        if not app.get("installed") and not cli.get("installed"):
            continue
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="catalog_installed_software_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        surface["signals"].append({
            "kind": "catalog_installed_software",
            "app_installed": bool(app.get("installed")),
            "cli_installed": bool(cli.get("installed")),
            "content_read": False,
        })
    for system, surface in surfaces.items():
        activity_records = [
            ("config", Path(path))
            for path in surface.get("config_paths", [])
        ] + [
            ("content_store", Path(path))
            for path in surface.get("content_store_paths", [])
        ] + [
            ("workspace", Path(path))
            for path in surface.get("workspace_paths", [])
        ] + [
            ("installation", Path(path))
            for path in surface.get("installation_paths", [])
            if path
        ]
        app = _app_bundle_metadata(system, resolved_home, resolved_env)
        cli = _cli_version_metadata(system, resolved_home, resolved_env)
        if app.get("installed") and app.get("bundle_path"):
            activity_records.append(("app_bundle", Path(str(app["bundle_path"]))))
        if cli.get("installed") and cli.get("path"):
            activity_records.append(("cli_binary", Path(str(cli["path"]))))
        surface["software"] = {
            "app": app,
            "cli": cli,
        }
        surface["activity"] = _activity_snapshot(activity_records)
        _refresh_conversation_memory_boundary(surface)
        execute_this_surface = bool(execute_model_identification and remaining_model_calls > 0)
        surface["model_identification"] = _build_model_identification(
            surface,
            resolved_env,
            execute_model=execute_this_surface,
        )
        attempted_model_execution = (
            execute_this_surface
            and surface["model_identification"].get("mode") == "configured_model"
            and bool(surface["model_identification"].get("enabled"))
        )
        if execute_model_identification and _surface_needs_model_identification(surface):
            surface["model_identification"]["execution_deferred"] = True
            surface["model_identification"]["deferred_reason"] = "model_execute_limit_reached"
        if attempted_model_execution:
            remaining_model_calls -= 1
        surface["provisional_adapter_candidate"] = _build_provisional_adapter_candidate(surface)
    model_identifications = [
        surface.get("model_identification")
        for surface in surfaces.values()
        if isinstance(surface.get("model_identification"), dict)
    ]
    return {
        "ok": True,
        "contract": GENERIC_DISCOVERY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "scan_mode": resolved_scan_mode,
        "scan_roots": [str(root) for root in roots],
        "surface_count": len(surfaces),
        "surfaces": list(surfaces.values()),
        "model_identification": {
            "contract": MODEL_IDENTIFICATION_CONTRACT,
            "read_only": True,
            "dry_run": True,
            "input_kind": "local_metadata_only",
            "model_call_performed": False,
            "execution_requested": bool(execute_model_identification),
            "execute_limit": execute_limit,
            "deferred_model_surface_count": sum(
                1 for item in model_identifications
                if bool(item.get("execution_deferred"))
            ),
            "executed_model_surface_count": sum(
                1 for item in model_identifications
                if bool(item.get("model_call_performed"))
            ),
            "configured_model_available": any(
                bool(item.get("configured_model", {}).get("configured"))
                for item in model_identifications
            ),
            "configured_model_surface_count": sum(
                1 for item in model_identifications
                if item.get("mode") == "configured_model"
            ),
            "fallback_rules_surface_count": sum(
                1 for item in model_identifications
                if item.get("mode") == "fallback_rules"
            ),
            "rules_confident_surface_count": sum(
                1 for item in model_identifications
                if item.get("mode") == "rules_confident"
            ),
        },
        "catalog": {
            "contract": PLATFORM_CATALOG_CONTRACT,
            "entry_count": load_platform_catalog().get("entry_count", 0),
            "github_watchlist_entry_count": load_platform_catalog().get("github_watchlist_entry_count", 0),
        },
        "package_manager_inventory": {
            "contract": package_inventory.get("contract"),
            "item_count": package_inventory.get("item_count", 0),
            "match_count": package_inventory.get("match_count", 0),
        },
        "limits": limits,
    }


def build_generic_local_ai_surfaces_snapshot() -> dict[str, Any]:
    catalog = load_platform_catalog()
    return {
        "ok": True,
        "contract": GENERIC_DISCOVERY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "scan_mode": "fast_snapshot",
        "surface_count": 0,
        "surfaces": [],
        "catalog": {
            "contract": PLATFORM_CATALOG_CONTRACT,
            "entry_count": catalog.get("entry_count", 0),
            "github_watchlist_entry_count": catalog.get("github_watchlist_entry_count", 0),
        },
        "limits": {
            "full_scan_endpoint": "/api/v1/platforms/generic-local-ai-surfaces?scan=full",
        },
    }


def _dir_signal_text(path: Path, limit: int = 60) -> str:
    names = [child.name for child in _safe_iterdir(path, limit=limit)]
    return " ".join(names)


def _path_descriptor(path: Path, path_role: str) -> dict[str, Any] | None:
    is_dir = _safe_is_dir(path)
    is_file = _safe_is_file(path)
    if not is_dir and not is_file:
        return None
    descriptor: dict[str, Any] = {
        "type": path_role,
        "path": str(path),
        "is_dir": is_dir,
        "is_file": is_file,
    }
    stat = _stat_snapshot(path)
    if stat:
        descriptor["modified_at"] = stat["modified_at"]
        descriptor["age_days"] = stat["age_days"]
        descriptor["freshness"] = stat["freshness"]
    if is_file:
        file_stat = _safe_stat(path)
        descriptor["size"] = file_stat.st_size if file_stat else None
    return descriptor


def _signal_detected(path: Path) -> bool:
    if INTENT_SIGNAL_RE.search(str(path)):
        return True
    if _safe_is_file(path):
        return bool(INTENT_SIGNAL_RE.search(_read_small_text(path)))
    if _safe_is_dir(path):
        return bool(INTENT_SIGNAL_RE.search(_dir_signal_text(path)))
    return False


def _activity_snapshot(records: list[tuple[str, Path]]) -> dict[str, Any]:
    by_role: dict[str, list[dict[str, Any]]] = {}
    for role, path in records:
        stat = _stat_snapshot(path)
        if not stat:
            continue
        by_role.setdefault(role, []).append({**stat, "role": role})
    latest_by_role: dict[str, dict[str, Any]] = {}
    for role, items in by_role.items():
        latest_by_role[role] = min(items, key=lambda item: int(item.get("age_days") or 0))
    primary_role = ""
    for candidate in ("content_store", "workspace", "config", "installation", "skill", "app_bundle", "cli_binary"):
        if candidate in latest_by_role:
            primary_role = candidate
            break
    primary = latest_by_role.get(primary_role, {})
    age = primary.get("age_days") if primary else None
    return {
        "primary_source": primary_role,
        "primary_path": primary.get("path", ""),
        "primary_last_seen_at": primary.get("modified_at", ""),
        "primary_age_days": age,
        "freshness": _freshness_from_age(age if isinstance(age, int) else None),
        "latest_by_role": latest_by_role,
    }


def _status_from_profile(profile: dict[str, Any]) -> str:
    status = str(profile.get("status") or "not_found")
    if status in {"active", "detected", "not_found"}:
        return status
    return "detected" if profile.get("instances") else "not_found"


def _profile_instances(profile: dict[str, Any]) -> list[dict[str, Any]]:
    instances = profile.get("instances")
    return list(instances) if isinstance(instances, list) else []


def _adapter_actions(
    *,
    detected: bool,
    intent_signal: bool,
    connectable_now: bool,
    content_bearing_store_detected: bool,
    current_focus: bool,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if not current_focus:
        actions.append({
            "action": "document_boundary_only",
            "status": "parked",
            "reason": "known_platform_but_not_current_product_focus",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
        return actions
    if not detected:
        actions.append({
            "action": "observe_only",
            "status": "waiting",
            "reason": "known_adapter_target_not_detected",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    elif connectable_now:
        actions.append({
            "action": "capability_check",
            "status": "ready",
            "reason": "memcore_mcp_or_tool_connection_detected",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    elif intent_signal:
        actions.append({
            "action": "auto_connect_missing_thin_adapter",
            "status": AUTO_CONNECT_READY_STATUS,
            "reason": "memcore_skill_or_mcp_signal_detected",
            "requires_user_authorization": False,
            "writes_platform_config": True,
        })
    else:
        actions.append({
            "action": "auto_connect",
            "status": AUTO_CONNECT_READY_STATUS,
            "reason": "platform_detected_without_memcore_signal",
            "requires_user_authorization": False,
            "writes_platform_config": True,
        })
    if content_bearing_store_detected:
        actions.append({
            "action": "verified_format_collector",
            "status": "collector_required",
            "reason": "content_bearing_store_detected_and_waiting_for_verified_collector",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        })
    return actions


def _probe_spec(
    spec: AdapterSpec,
    *,
    runtime_profile: dict[str, Any],
    home: Path,
    env: dict[str, str],
    include_software_probe: bool = True,
) -> dict[str, Any]:
    profile = runtime_profile.get(spec.system) if isinstance(runtime_profile.get(spec.system), dict) else {}
    profile_status = _status_from_profile(profile)
    profile_instances = _profile_instances(profile)
    instances: list[dict[str, Any]] = list(profile_instances)
    seen_paths = {str(item.get("path")) for item in instances if item.get("path")}
    intent_signal = False
    connectable_now = False
    mcp_config_detected = False
    memcore_mcp_detected = False
    skill_signal_detected = False
    content_bearing_store_detected = False
    signals: list[dict[str, Any]] = []
    activity_records: list[tuple[str, Path]] = []
    config_patterns = tuple(dict.fromkeys((*spec.config_paths, *_catalog_mcp_config_patterns(spec.system))))

    for role, patterns in (
        ("config", config_patterns),
        ("skill", spec.skill_paths),
        ("content_store", spec.content_paths),
    ):
        for pattern in patterns:
            path = _expand_path(pattern, home, env)
            if path is None:
                continue
            descriptor = _path_descriptor(path, role)
            if descriptor is None:
                continue
            activity_records.append((role, path))
            if descriptor.get("path") not in seen_paths:
                instances.append(descriptor)
                seen_paths.add(str(descriptor.get("path")))
            if role == "content_store":
                content_bearing_store_detected = True
                signals.append({
                    "kind": "content_store",
                    "path": str(path),
                    "content_read": False,
                    "parser_gate": spec.content_gate,
                })
            config_probes: list[dict[str, Any]] = []
            descriptor_is_file = bool(descriptor.get("is_file"))
            descriptor_is_dir = bool(descriptor.get("is_dir"))
            if role in {"config", "skill"} and descriptor_is_file:
                config_probes.append(_config_probe(path))
            elif role in {"config", "skill"} and descriptor_is_dir:
                config_probes.extend(_dir_config_probe(path))
            for probe in config_probes:
                signals.append(probe)
                mcp_config_detected = mcp_config_detected or bool(probe.get("mcp_detected"))
                memcore_mcp_detected = memcore_mcp_detected or bool(probe.get("memcore_mcp_detected"))
                intent_signal = intent_signal or bool(probe.get("intent_signal_detected"))
            signal_detected = _signal_detected(path)
            if role == "skill" and signal_detected:
                skill_signal_detected = True
                intent_signal = True
            elif signal_detected:
                intent_signal = True

    profile_consumer = profile.get("consumer_connection") if isinstance(profile.get("consumer_connection"), dict) else {}
    if profile_consumer.get("skill_detected") or profile_consumer.get("mcp_detected"):
        intent_signal = True
        skill_signal_detected = skill_signal_detected or bool(profile_consumer.get("skill_detected"))
        mcp_config_detected = mcp_config_detected or bool(profile_consumer.get("mcp_detected"))
    if profile_consumer.get("recall_connection_ready") or memcore_mcp_detected:
        connectable_now = True
    app = _app_bundle_metadata(spec.system, home, env) if include_software_probe else {
        "installed": False,
        "bundle_path": "",
        "version": "",
        "build": "",
        "modified_at": "",
        "age_days": None,
        "freshness": "unknown",
        "probe_skipped": True,
    }
    cli = _cli_version_metadata(spec.system, home, env) if include_software_probe else {
        "installed": False,
        "path": "",
        "version": "",
        "raw": "",
        "probe_skipped": True,
    }
    if app.get("installed") and app.get("bundle_path"):
        activity_records.append(("app_bundle", Path(str(app["bundle_path"]))))
    if cli.get("installed") and cli.get("path"):
        activity_records.append(("cli_binary", Path(str(cli["path"]))))
    conversation_boundary = _conversation_memory_boundary(
        spec.system,
        [str(path) for _role, path in activity_records],
    )
    detected = profile_status != "not_found" or bool(instances)
    status = profile_status if profile_status != "not_found" else ("detected" if instances else "not_found")
    actions = _adapter_actions(
        detected=detected,
        intent_signal=intent_signal,
        connectable_now=connectable_now,
        content_bearing_store_detected=content_bearing_store_detected,
        current_focus=spec.current_focus,
    )
    return {
        "system": spec.system,
        "display_name": spec.display_name,
        "support_level": spec.support_level,
        "platform_family": spec.platform_family,
        "status": status,
        "detected": detected,
        "thin_adapter": True,
        "current_focus": spec.current_focus,
        "read_only": True,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "connection_surfaces": list(spec.connection_surfaces),
        "instance_count": len(instances),
        "instances": instances,
        "signals": signals,
        "mcp_config_detected": mcp_config_detected,
        "memcore_mcp_detected": memcore_mcp_detected,
        "skill_signal_detected": skill_signal_detected,
        "intent_signal_detected": intent_signal,
        "connectable_now": connectable_now,
        "content_bearing_store_detected": content_bearing_store_detected,
        "content_gate": spec.content_gate,
        "software": {
            "app": app,
            "cli": cli,
        },
        "activity": _activity_snapshot(activity_records),
        "catalog_driven": bool(_catalog_entry(spec.system)),
        "catalog_entry": _catalog_entry_summary(spec.system),
        "skill_installation_is_intent_signal_only": True,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": conversation_boundary,
        "actions": actions,
        "notes": list(spec.notes),
    }


def build_thin_adapter_registry(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    include_generic: bool = True,
    include_software_probe: bool | None = None,
    execute_model_identification: bool = False,
    generic_scan_mode: str = "deep",
    model_execute_limit: int | None = None,
) -> dict[str, Any]:
    profile = runtime_profile or {}
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    catalog = load_platform_catalog()
    software_probe = include_generic if include_software_probe is None else include_software_probe
    adapters = [
        _probe_spec(
            spec,
            runtime_profile=profile,
            home=resolved_home,
            env=resolved_env,
            include_software_probe=software_probe,
        )
        for spec in ADAPTER_SPECS
    ]
    generic = build_generic_local_ai_surfaces(
        home=resolved_home,
        env=resolved_env,
        execute_model_identification=execute_model_identification,
        scan_mode=generic_scan_mode,
        model_execute_limit=model_execute_limit,
    ) if include_generic else {
        "ok": True,
        "contract": GENERIC_DISCOVERY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "scan_mode": "skipped_for_fast_snapshot",
        "surface_count": 0,
        "surfaces": [],
        "limits": {},
    }
    known_systems = {adapter["system"] for adapter in adapters}
    generic_surfaces = [
        surface for surface in generic.get("surfaces", [])
        if surface.get("system") not in known_systems
    ]
    detected = [item for item in adapters if item["detected"]]
    auto_connect_ready = [
        item for item in adapters
        if any(action.get("status") == AUTO_CONNECT_READY_STATUS for action in item.get("actions", []))
    ]
    return {
        "ok": True,
        "contract": REGISTRY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "default_policy": "auto_discover_and_auto_connect_supported_surfaces",
        "scan_mode": "full" if include_generic else "fast_known_adapters_only",
        "software_probe_mode": "enabled" if software_probe else "skipped_for_fast_snapshot",
        "adapter_count": len(adapters),
        "catalog_entry_count": catalog.get("entry_count", 0),
        "github_watchlist_entry_count": catalog.get("github_watchlist_entry_count", 0),
        "detected_adapter_count": len(detected),
        "generic_surface_count": len(generic_surfaces),
        "generic_surface_memcore_ready_count": sum(1 for item in generic_surfaces if item.get("connectable_now")),
        "auto_connect_ready_count": len(auto_connect_ready),
        "authorization_needed_count": 0,
        "registry_scope": [
            "supported first-class adapters",
            "planned adapter candidates",
            "editor and MCP surfaces",
            "content-bearing stores as locked parser gates",
        ],
        "adapters": adapters,
        "platform_catalog": {
            "contract": catalog.get("contract"),
            "catalog_version": catalog.get("catalog_version"),
            "watchlist_version": catalog.get("watchlist_version"),
            "entry_count": catalog.get("entry_count"),
            "curated_entry_count": catalog.get("curated_entry_count"),
            "github_watchlist_entry_count": catalog.get("github_watchlist_entry_count"),
        },
        "generic_surface_discovery": {
            **generic,
            "surfaces": generic_surfaces,
            "surface_count": len(generic_surfaces),
        },
        "model_identification": {
            "contract": MODEL_IDENTIFICATION_CONTRACT,
            "read_only": True,
            "dry_run": True,
            "input_kind": "local_metadata_only",
            "model_call_performed": False,
            "execution_requested": bool(execute_model_identification),
            "execute_limit": _normalize_execute_limit(model_execute_limit),
            "deferred_model_surface_count": int(
                sum(
                    1 for item in generic_surfaces
                    if ((item.get("model_identification") or {}).get("execution_deferred"))
                )
            ),
            "executed_model_surface_count": int(
                sum(
                    1 for item in generic_surfaces
                    if ((item.get("model_identification") or {}).get("model_call_performed"))
                )
            ),
            "configured_model_available": bool(
                any(
                    bool(((item.get("model_identification") or {}).get("configured_model") or {}).get("configured"))
                    for item in generic_surfaces
                )
            ),
            "configured_model_surface_count": int(
                sum(
                    1 for item in generic_surfaces
                    if (item.get("model_identification") or {}).get("mode") == "configured_model"
                )
            ),
            "fallback_rules_surface_count": int(
                sum(
                    1 for item in generic_surfaces
                    if (item.get("model_identification") or {}).get("mode") == "fallback_rules"
                )
            ),
            "rules_confident_surface_count": int(
                sum(
                    1 for item in generic_surfaces
                    if (item.get("model_identification") or {}).get("mode") == "rules_confident"
                )
            ),
        },
        "authorization_contract": {
            "can_auto_discover": True,
            "default_connection_mode": "auto_discover_and_auto_connect",
            "can_auto_connect_supported_configs": True,
            "conversation_import_mode": "verified_format_collectors",
            "window_memory_scope_default": "current_window_first",
            "skill_installation_is_connection_signal": True,
            "receipts_required_for_writes": True,
            "backup_required_before_platform_config_write": True,
        },
    }


def build_model_identification_report(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    include_generic: bool = True,
    execute: bool = False,
    scan_mode: str = "smart",
    model_execute_limit: int | None = None,
) -> dict[str, Any]:
    resolved_scan_mode = "fast_snapshot" if not include_generic else _normalize_generic_scan_mode(scan_mode)
    registry = build_thin_adapter_registry(
        runtime_profile,
        home=home,
        env=env,
        include_generic=include_generic,
        include_software_probe=include_generic,
        execute_model_identification=execute and include_generic,
        generic_scan_mode=resolved_scan_mode,
        model_execute_limit=model_execute_limit,
    )
    surfaces = registry.get("generic_surface_discovery", {}).get("surfaces", [])
    items: list[dict[str, Any]] = []
    for surface in surfaces:
        if not isinstance(surface, dict):
            continue
        identification = surface.get("model_identification") if isinstance(surface.get("model_identification"), dict) else {}
        result = identification.get("result") if isinstance(identification.get("result"), dict) else {}
        envelope = identification.get("request_envelope") if isinstance(identification.get("request_envelope"), dict) else {}
        metadata = identification.get("local_metadata") if isinstance(identification.get("local_metadata"), dict) else {}
        candidate = surface.get("provisional_adapter_candidate") if isinstance(surface.get("provisional_adapter_candidate"), dict) else {}
        items.append({
            "system": surface.get("system", ""),
            "display_name": surface.get("display_name", ""),
            "source": surface.get("source", ""),
            "mode": identification.get("mode", "unknown"),
            "enabled": bool(identification.get("enabled")),
            "reason": identification.get("reason", ""),
            "configured_model": identification.get("configured_model", {}),
            "executor": identification.get("executor", ""),
            "model_call_performed": bool(identification.get("model_call_performed")),
            "result": result,
            "execution": identification.get("execution", {}),
            "request_envelope": envelope,
            "local_metadata": metadata,
            "provisional_adapter_candidate": candidate,
            "chat_body_included": bool(identification.get("chat_body_included", False)),
            "raw_excerpt_included": bool(identification.get("raw_excerpt_included", False)),
        })
    summary = registry.get("model_identification", {}) if isinstance(registry.get("model_identification"), dict) else {}
    return {
        "ok": True,
        "contract": MODEL_IDENTIFICATION_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": not execute,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "input_kind": "local_metadata_only",
        "scan_mode": resolved_scan_mode,
        "execute_requested": bool(execute),
        "execute_limit": _normalize_execute_limit(model_execute_limit),
        "model_call_performed": any(item["model_call_performed"] for item in items),
        "summary": {
            "surface_count": len(items),
            "configured_model_available": bool(summary.get("configured_model_available")),
            "configured_model_surface_count": int(summary.get("configured_model_surface_count") or 0),
            "fallback_rules_surface_count": int(summary.get("fallback_rules_surface_count") or 0),
            "rules_confident_surface_count": int(summary.get("rules_confident_surface_count") or 0),
            "executed_model_surface_count": int(summary.get("executed_model_surface_count") or 0),
            "deferred_model_surface_count": int(summary.get("deferred_model_surface_count") or 0),
            "provisional_adapter_candidate_count": sum(
                1 for item in items
                if item.get("provisional_adapter_candidate")
            ),
        },
        "items": items,
        "public_summary": {
            "local_tools_checked": len(items),
            "ready_for_model_identification": sum(1 for item in items if item.get("mode") == "configured_model"),
            "using_rule_fallback": sum(1 for item in items if item.get("mode") == "fallback_rules"),
            "recognized_from_local_signals": sum(1 for item in items if item.get("mode") == "rules_confident"),
        },
    }


_PUBLIC_STRATEGY_TOKEN_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("github_watchlist", "known_repo_reference"),
    ("GitHub Watchlist", "Known Repo Reference"),
    ("github_top100", "known_repo_reference"),
    ("GitHub100", "known repo reference"),
    ("catalog_watchlist", "catalog_reference"),
    ("watchlist", "reference_list"),
    ("platform_catalog", "tool_reference"),
    ("thin_adapter", "tool_adapter"),
    ("泛发现", "本地发现"),
    ("平台字典", "工具识别"),
    ("Nantianmen", "orchestration system"),
    ("南天门", "调度系统"),
    ("Tiandao", "public rules"),
    ("天道", "公共规则"),
)


def _public_text_without_strategy_terms(value: str) -> str:
    result = value
    for old, new in _PUBLIC_STRATEGY_TOKEN_REPLACEMENTS:
        result = result.replace(old, new)
    return result


def _public_payload_without_strategy_terms(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            _public_text_without_strategy_terms(str(key)): _public_payload_without_strategy_terms(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_public_payload_without_strategy_terms(item) for item in value]
    if isinstance(value, tuple):
        return [_public_payload_without_strategy_terms(item) for item in value]
    if isinstance(value, str):
        return _public_text_without_strategy_terms(value)
    return value


def public_tool_discovery_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a product-facing copy without internal discovery strategy names."""
    sanitized = _public_payload_without_strategy_terms(payload)
    return sanitized if isinstance(sanitized, dict) else {}


def build_provisional_adapter_candidates_report(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    include_generic: bool = True,
    execute: bool = False,
    scan_mode: str = "smart",
    model_execute_limit: int | None = None,
) -> dict[str, Any]:
    identification = build_model_identification_report(
        runtime_profile,
        home=home,
        env=env,
        include_generic=include_generic,
        execute=execute,
        scan_mode=scan_mode,
        model_execute_limit=model_execute_limit,
    )
    candidates = [
        item.get("provisional_adapter_candidate")
        for item in identification.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("provisional_adapter_candidate"), dict)
    ]
    return {
        "ok": True,
        "contract": PROVISIONAL_ADAPTER_CANDIDATE_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": not execute,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "scan_mode": identification.get("scan_mode", "fast_snapshot"),
        "execute_requested": bool(execute),
        "execute_limit": identification.get("execute_limit", DEFAULT_MODEL_IDENTIFICATION_EXECUTE_LIMIT),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "summary": {
            "auto_connect_supported_now": sum(
                1 for candidate in candidates
                if (candidate.get("connection") or {}).get("auto_connect_supported_now")
            ),
            "adapter_draft_count": sum(
                1 for candidate in candidates
                if isinstance(candidate.get("adapter_draft"), dict)
            ),
            "verified_collectors_needed": sum(
                1 for candidate in candidates
                if ((candidate.get("adapter_draft") or {}).get("collector") or {}).get("collector_status")
                == "verified_collector_required"
            ),
            "complete_conversation_candidates": sum(
                1 for candidate in candidates
                if ((candidate.get("adapter_draft") or {}).get("collector") or {}).get("complete_conversation_candidate")
            ),
            "computer_first_archive_ready": sum(
                1 for candidate in candidates
                if ((candidate.get("adapter_draft") or {}).get("raw_archive") or {}).get("layout") == "computer_first"
            ),
            "needs_thin_adapter": sum(
                1 for candidate in candidates
                if candidate.get("next_step") == "create_thin_adapter_from_candidate"
            ),
            "needs_mcp_config_location": sum(
                1 for candidate in candidates
                if candidate.get("next_step") == "locate_mcp_config_surface"
            ),
        },
    }


def _existing_paths(adapter: dict[str, Any], role: str | None = None) -> list[str]:
    paths: list[str] = []
    for item in adapter.get("instances", []):
        if role is not None and item.get("type") != role:
            continue
        path = item.get("path")
        if path:
            paths.append(str(path))
    return paths


def _expanded_autoconnect_targets(
    system: str,
    *,
    adapter: dict[str, Any],
    home: Path,
    env: dict[str, str],
) -> list[str]:
    existing_config_paths = _existing_paths(adapter, "config")
    if system == "codex":
        targets = [
            path for path in existing_config_paths
            if Path(path).name.lower() == "config.toml"
        ]
        for pattern in AUTOCONNECT_TARGET_PATTERNS.get(system, ()):
            path = _expand_path(pattern, home, env)
            if path is not None and path.name.lower() == "config.toml":
                text = str(path)
                if text not in targets:
                    targets.append(text)
        return targets[:1]
    targets = [path for path in existing_config_paths if _safe_is_file(Path(path))]
    patterns = tuple(dict.fromkeys((
        *AUTOCONNECT_TARGET_PATTERNS.get(system, ()),
        *_catalog_mcp_config_patterns(system),
    )))
    for pattern in patterns:
        roots = _generic_scan_roots(home, env)
        paths = _expanded_catalog_pattern_paths(pattern, home=home, env=env, roots=roots)
        if not paths:
            path = _expand_path(pattern, home, env)
            paths = [path] if path is not None else []
        for path in paths:
            if "*" in str(path):
                continue
            if Path(path).suffix.lower() != ".json" and "mcp" not in Path(path).name.lower():
                continue
            text = str(path)
            if text not in targets:
                targets.append(text)
    return targets[:3]


def _missing_for_adapter(adapter: dict[str, Any]) -> list[str]:
    if adapter.get("connectable_now"):
        return []
    missing: list[str] = []
    if not adapter.get("detected"):
        missing.append("platform_detection")
    if adapter.get("detected") and not adapter.get("memcore_mcp_detected"):
        missing.append("memcore_mcp_registration")
    if adapter.get("detected") and not adapter.get("connectable_now"):
        missing.append("capability_check_connection")
    return missing


def _plan_status(adapter: dict[str, Any]) -> str:
    if not adapter.get("current_focus", True):
        return "parked_not_current_focus"
    if not adapter.get("detected"):
        return "not_detected"
    if adapter.get("connectable_now"):
        return "ready_for_capability_check"
    return AUTO_CONNECT_READY_STATUS


def _safe_next_step(status: str, item: dict[str, Any]) -> str:
    if status == "ready_for_capability_check":
        return "run_capability_check"
    if status == AUTO_CONNECT_READY_STATUS:
        return "auto_connect"
    if status == "parked_not_current_focus":
        return "document_boundary_only"
    if status == "not_detected":
        return "observe_only"
    if item.get("content_bearing_store_detected"):
        return "parser_gate_locked"
    return "observe_only"


def _dashboard_item_from_adapter(adapter: dict[str, Any]) -> dict[str, Any]:
    status = _plan_status(adapter)
    safe_next_step = _safe_next_step(status, adapter)
    system = str(adapter.get("system") or "")
    return {
        "system": system,
        "display_name": adapter.get("display_name") or system,
        "surface_type": "known_thin_adapter",
        "support_level": adapter.get("support_level"),
        "platform_family": adapter.get("platform_family"),
        "status": status,
        "detected": bool(adapter.get("detected")),
        "connectable_now": bool(adapter.get("connectable_now")),
        "current_focus": bool(adapter.get("current_focus", True)),
        "intent_signal_detected": bool(adapter.get("intent_signal_detected")),
        "mcp_config_detected": bool(adapter.get("mcp_config_detected")),
        "memcore_mcp_detected": bool(adapter.get("memcore_mcp_detected")),
        "skill_signal_detected": bool(adapter.get("skill_signal_detected")),
        "content_bearing_store_detected": bool(adapter.get("content_bearing_store_detected")),
        "parser_gate": adapter.get("content_gate"),
        "software": adapter.get("software", {}),
        "activity": adapter.get("activity", {}),
        "freshness": (adapter.get("activity") or {}).get("freshness", "unknown"),
        "catalog_driven": bool(adapter.get("catalog_driven")),
        "catalog_entry": adapter.get("catalog_entry", {}),
        "safe_next_step": safe_next_step,
        "authorized_connect_plan_endpoint": f"/api/v1/platforms/{system}/authorized-connect-plan",
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD if status == "ready_for_capability_check" else {},
        "writes_now": False,
        "reads_chat_bodies": False,
        "real_recall_now": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": adapter.get("conversation_memory_boundary") or _conversation_memory_boundary(system),
        "instance_count": int(adapter.get("instance_count") or 0),
        "config_paths": _existing_paths(adapter, "config"),
    }


def _dashboard_item_from_generic_surface(surface: dict[str, Any]) -> dict[str, Any]:
    system = str(surface.get("system") or "")
    config_paths = list(surface.get("config_paths") or [])
    content_store_paths = list(surface.get("content_store_paths") or [])
    workspace_paths = list(surface.get("workspace_paths") or [])
    installation_paths = list(surface.get("installation_paths") or [])
    adapter_like = {
        "system": system,
        "detected": surface.get("detected"),
        "connectable_now": surface.get("connectable_now"),
        "current_focus": True,
    }
    status = _plan_status(adapter_like)
    safe_next_step = _safe_next_step(status, adapter_like)
    return {
        "system": system,
        "display_name": surface.get("display_name") or system,
        "surface_type": "generic_local_ai_surface",
        "support_level": "generic_surface_candidate",
        "platform_family": surface.get("platform_family") or "generic_mcp_or_config_surface",
        "status": status,
        "detected": bool(surface.get("detected")),
        "connectable_now": bool(surface.get("connectable_now")),
        "current_focus": True,
        "intent_signal_detected": bool(surface.get("intent_signal_detected")),
        "mcp_config_detected": bool(surface.get("mcp_config_detected")),
        "memcore_mcp_detected": bool(surface.get("memcore_mcp_detected")),
        "skill_signal_detected": False,
        "content_bearing_store_detected": bool(content_store_paths),
        "parser_gate": "verified_format_collector_required",
        "software": surface.get("software", {}),
        "activity": surface.get("activity", {}),
        "freshness": (surface.get("activity") or {}).get("freshness", "unknown"),
        "catalog_driven": bool(surface.get("catalog_driven")),
        "catalog_entry": surface.get("catalog_entry", {}),
        "safe_next_step": safe_next_step,
        "authorized_connect_plan_endpoint": f"/api/v1/platforms/{system}/authorized-connect-plan",
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD if status == "ready_for_capability_check" else {},
        "writes_now": False,
        "reads_chat_bodies": False,
        "real_recall_now": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": surface.get("conversation_memory_boundary") or _conversation_memory_boundary(
            system,
            [*content_store_paths, *workspace_paths],
        ),
        "model_identification": surface.get("model_identification", {}),
        "provisional_adapter_candidate": surface.get("provisional_adapter_candidate", {}),
        "instance_count": len(config_paths) + len(content_store_paths) + len(workspace_paths) + len(installation_paths),
        "config_paths": config_paths,
        "content_store_paths": content_store_paths,
        "workspace_paths": workspace_paths,
        "installation_paths": installation_paths,
    }


def _public_tool_type(item: dict[str, Any]) -> str:
    if item.get("surface_type") == "generic_local_ai_surface":
        return "local_tool"
    return "recognized_tool"


def _public_safe_next_step(value: str) -> str:
    mapping = {
        "auto_connect": "auto_connect",
        "document_boundary_only": "review_boundary",
        "observe_only": "keep_observing",
        "parser_gate_locked": "verified_collector",
    }
    return mapping.get(value, value)


def _public_recognition_status(item: dict[str, Any]) -> dict[str, Any]:
    identification = item.get("model_identification") if isinstance(item.get("model_identification"), dict) else {}
    mode = str(identification.get("mode") or "")
    if mode == "configured_model":
        return {
            "recognized_by": "model",
            "recognition_status": "ready_for_model_identification",
            "model_call_performed": False,
        }
    if mode == "fallback_rules":
        return {
            "recognized_by": "local_rules",
            "recognition_status": "fallback_rules",
            "model_call_performed": False,
        }
    return {
        "recognized_by": "local_rules",
        "recognition_status": "recognized_from_local_signals",
        "model_call_performed": False,
    }


def _public_dashboard_item(item: dict[str, Any]) -> dict[str, Any]:
    activity = item.get("activity") if isinstance(item.get("activity"), dict) else {}
    software = item.get("software") if isinstance(item.get("software"), dict) else {}
    app = software.get("app") if isinstance(software.get("app"), dict) else {}
    cli = software.get("cli") if isinstance(software.get("cli"), dict) else {}
    version = str(app.get("version") or cli.get("version") or "")
    recognition = _public_recognition_status(item)
    return {
        "system": item.get("system", ""),
        "display_name": item.get("display_name", ""),
        "tool_type": _public_tool_type(item),
        "status": item.get("status", "unknown"),
        "detected": bool(item.get("detected")),
        "ready_for_safe_check": item.get("status") == "ready_for_capability_check",
        "auto_connect_ready": item.get("status") == AUTO_CONNECT_READY_STATUS,
        "connectable_now": bool(item.get("connectable_now")),
        "memcore_connected": bool(item.get("memcore_mcp_detected")),
        "connection_signal_detected": bool(item.get("intent_signal_detected")),
        "version": version,
        "freshness": item.get("freshness") or activity.get("freshness") or "unknown",
        "last_seen_at": activity.get("primary_last_seen_at", ""),
        "recognized_by": recognition["recognized_by"],
        "recognition_status": recognition["recognition_status"],
        "model_call_performed": recognition["model_call_performed"],
        "safe_next_step": _public_safe_next_step(str(item.get("safe_next_step", "observe_only"))),
        "capability_check_payload": item.get("capability_check_payload", {}),
        "writes_now": False,
        "reads_chat_bodies": False,
        "real_recall_now": False,
        "chat_body_parser_requires_verified_collector": bool(
            item.get("chat_body_parser_requires_verified_collector")
        ),
    }


def _public_discovery_dashboard(full: dict[str, Any]) -> dict[str, Any]:
    counts = full.get("counts") if isinstance(full.get("counts"), dict) else {}
    public_summary = full.get("public_summary") if isinstance(full.get("public_summary"), dict) else {}
    public_counts = {
        "total": int(counts.get("total") or 0),
        "detected": int(counts.get("detected") or 0),
        "ready_for_capability_check": int(counts.get("ready_for_capability_check") or 0),
        "auto_connect_ready": int(counts.get("auto_connect_ready") or counts.get("needs_authorization") or 0),
        "other_local_tools": int(public_summary.get("other_local_tools") or 0),
        "recently_quiet_tools": int(public_summary.get("recently_quiet_tools") or 0),
    }
    return {
        "ok": bool(full.get("ok", True)),
        "contract": full.get("contract", DISCOVERY_DASHBOARD_CONTRACT),
        "view": "public",
        "generated_at": full.get("generated_at", ts()),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "name": "Memcore Cloud",
        "default_policy": "auto_discover_and_auto_connect_supported_surfaces",
        "dashboard_goal": "show_local_ai_tools_with_auto_connect_status",
        "counts": public_counts,
        "public_summary": {
            "local_ai_tools": public_counts["total"],
            "detected_tools": public_counts["detected"],
            "ready_for_safe_check": public_counts["ready_for_capability_check"],
            "auto_connect_ready": public_counts["auto_connect_ready"],
            "other_local_tools": public_counts["other_local_tools"],
            "recently_quiet_tools": public_counts["recently_quiet_tools"],
        },
        "items": [
            _public_dashboard_item(item)
            for item in full.get("items", [])
            if isinstance(item, dict)
        ],
        "global_guarantees": {
            "auto_connect_supported_skill_mcp_surfaces": True,
            "backup_and_receipt_on_config_write": True,
            "conversation_import_mode": "verified_format_collectors",
            "capability_check_after_connect": True,
            "new_memory_layout": "computer_first",
            "legacy_memory_layout": "read_compatibility_only",
        },
    }


def build_platform_discovery_dashboard(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    include_generic: bool = True,
    public: bool = True,
) -> dict[str, Any]:
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    catalog = load_platform_catalog()
    package_inventory = build_package_manager_agent_inventory(home=resolved_home, env=resolved_env) if include_generic else {
        "contract": PACKAGE_MANAGER_INVENTORY_CONTRACT,
        "item_count": 0,
        "match_count": 0,
        "scan_mode": "skipped_for_fast_snapshot",
    }
    registry = build_thin_adapter_registry(
        runtime_profile,
        home=resolved_home,
        env=resolved_env,
        include_generic=include_generic,
    )
    known_items = [
        _dashboard_item_from_adapter(adapter)
        for adapter in registry.get("adapters", [])
    ]
    generic_items = [
        _dashboard_item_from_generic_surface(surface)
        for surface in registry.get("generic_surface_discovery", {}).get("surfaces", [])
    ]
    order = {
        "ready_for_capability_check": 0,
        AUTO_CONNECT_READY_STATUS: 1,
        "parked_not_current_focus": 2,
        "not_detected": 3,
    }
    freshness_order = {
        "active_recent": 0,
        "warm": 1,
        "unknown": 2,
        "stale": 3,
        "dormant": 4,
    }
    items = sorted(
        known_items + generic_items,
        key=lambda item: (
            freshness_order.get(str(item.get("freshness") or "unknown"), 9),
            order.get(str(item.get("status")), 9),
            str(item.get("surface_type")),
            str(item.get("display_name")),
        ),
    )
    counts = {
        "total": len(items),
        "detected": sum(1 for item in items if item.get("detected")),
        "ready_for_capability_check": sum(1 for item in items if item.get("status") == "ready_for_capability_check"),
        "auto_connect_ready": sum(1 for item in items if item.get("status") == AUTO_CONNECT_READY_STATUS),
        "needs_authorization": sum(1 for item in items if item.get("status") == AUTO_CONNECT_READY_STATUS),
        "generic_surfaces": sum(1 for item in items if item.get("surface_type") == "generic_local_ai_surface"),
        "catalog_entries": int(catalog.get("entry_count") or 0),
        "catalog_watchlist": int(catalog.get("github_watchlist_entry_count") or 0),
        "catalog_detected": sum(1 for item in items if item.get("catalog_driven") and item.get("detected")),
        "package_manager_matches": int(package_inventory.get("match_count") or 0),
        "parked_not_current_focus": sum(1 for item in items if item.get("status") == "parked_not_current_focus"),
        "verified_collectors_needed": sum(1 for item in items if item.get("chat_body_parser_requires_verified_collector")),
        "parser_gates_locked": sum(1 for item in items if item.get("chat_body_parser_requires_verified_collector")),
        "stale": sum(1 for item in items if item.get("freshness") == "stale"),
        "dormant": sum(1 for item in items if item.get("freshness") == "dormant"),
    }
    public_summary = {
        "local_ai_tools": counts["total"],
        "detected_tools": counts["detected"],
        "ready_for_safe_check": counts["ready_for_capability_check"],
        "auto_connect_ready": counts["auto_connect_ready"],
        "other_local_tools": counts["generic_surfaces"],
        "recently_quiet_tools": counts["stale"] + counts["dormant"],
        "install_record_matches": counts["package_manager_matches"],
    }
    full_payload = {
        "ok": True,
        "contract": DISCOVERY_DASHBOARD_CONTRACT,
        "view": "internal",
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "name": "Memcore Cloud",
        "codename": "Yifanchen",
        "default_policy": "auto_discover_and_auto_connect_supported_surfaces",
        "dashboard_goal": "show_local_ai_tools_with_auto_connect_status",
        "counts": counts,
        "public_summary": public_summary,
        "platform_catalog": {
            "contract": catalog.get("contract"),
            "catalog_version": catalog.get("catalog_version"),
            "watchlist_version": catalog.get("watchlist_version"),
            "entry_count": catalog.get("entry_count"),
            "curated_entry_count": catalog.get("curated_entry_count"),
            "github_watchlist_entry_count": catalog.get("github_watchlist_entry_count"),
        },
        "package_manager_inventory": {
            "contract": package_inventory.get("contract"),
            "item_count": package_inventory.get("item_count"),
            "match_count": package_inventory.get("match_count"),
        },
        "items": items,
        "global_guarantees": {
            "auto_connect_supported_skill_mcp_surfaces": True,
            "backup_and_receipt_on_config_write": True,
            "conversation_import_mode": "verified_format_collectors",
            "does_not_recall_real_memory": True,
            "skill_installation_is_not_body_read_consent": True,
            "capability_check_only_when_connectable": True,
            "raw_archive_layout_order": ["computer_name", "source_system", "native_artifact_format"],
            "raw_archive_primary_partition_key": "computer_name",
            "raw_archive_secondary_partition_key": "source_system",
            "raw_archive_effective_from_version": "2026.6.1",
            "raw_archive_new_install_default_layout": "computer_first",
            "raw_archive_legacy_layout_status": "read_compatibility_only",
            "raw_archive_legacy_layout_allowed_for_new_writes": False,
        },
        "links": {
            "thin_adapter_registry": "/api/v1/platforms/thin-adapter-registry",
            "platform_catalog": "/api/v1/platforms/catalog",
            "package_manager_inventory": "/api/v1/platforms/package-manager-inventory",
            "generic_local_ai_surfaces": "/api/v1/platforms/generic-local-ai-surfaces",
            "authorized_auto_connect_dry_run": "/api/v1/platforms/authorized-auto-connect/dry-run",
        },
    }
    if public:
        return _public_discovery_dashboard(full_payload)
    return full_payload


def _write_strategy_for_system(system: str) -> str:
    if system == "claude_desktop":
        return "register_local_stdio_mcp_bridge"
    if system == "codex":
        return "use_codex_mcp_add_stdio_bridge"
    if system == "claude_code_cli":
        return "use_claude_mcp_add_or_update_mcp_json"
    if system == "kiro":
        return "register_generic_json_mcp_server"
    if system in {"codex", "cursor", "continue", "roo_code", "cline"}:
        return "register_loopback_mcp_server"
    if _catalog_json_mcp_apply_supported(system):
        return "register_catalog_json_mcp_server"
    if system in {"openclaw", "hermes"}:
        return "use_installer_default_connector"
    return "manual_review_required"


def _apply_endpoint_status_for_system(system: str) -> str:
    if system == "codex":
        return "implemented_for_codex_cli_mcp_bridge"
    return "implemented_for_json_mcp_surfaces" if system in _implemented_apply_systems() else "not_implemented"


def _adapter_draft_for_plan(adapter: dict[str, Any]) -> dict[str, Any]:
    candidate = adapter.get("provisional_adapter_candidate")
    if isinstance(candidate, dict) and isinstance(candidate.get("adapter_draft"), dict):
        return candidate["adapter_draft"]
    system = str(adapter.get("system") or "")
    display_name = str(adapter.get("display_name") or system)
    config_paths = _existing_paths(adapter, "config")
    content_store_paths = _existing_paths(adapter, "content_store")
    workspace_paths = _existing_paths(adapter, "workspace")
    surface = {
        "system": system,
        "display_name": display_name,
        "source": "known_thin_adapter",
        "platform_family": adapter.get("platform_family", ""),
        "catalog_driven": bool(adapter.get("catalog_driven")),
        "config_paths": config_paths,
        "content_store_paths": content_store_paths,
        "workspace_paths": workspace_paths,
        "signals": adapter.get("signals", []),
        "mcp_config_detected": bool(adapter.get("mcp_config_detected")),
        "memcore_mcp_detected": bool(adapter.get("memcore_mcp_detected")),
        "intent_signal_detected": bool(adapter.get("intent_signal_detected")),
        "conversation_memory_boundary": adapter.get("conversation_memory_boundary") or _conversation_memory_boundary(
            system,
            [*content_store_paths, *workspace_paths],
        ),
    }
    result = {
        "likely_name": display_name,
        "category": _category_from_family(adapter.get("platform_family")),
        "supports_mcp_likely": bool(config_paths or _catalog_mcp_config_patterns(system) or system in _implemented_apply_systems()),
        "skill_surface_likely": bool(adapter.get("skill_signal_detected")),
        "storage_candidate": _storage_candidate_for_surface(surface),
        "confidence": 0.9 if adapter.get("detected") else 0.5,
        "reason": "known thin adapter plan",
    }
    connection = _candidate_connection_status(system, surface, result)
    return _build_adapter_draft(
        system=system,
        display_name=display_name,
        surface=surface,
        result=result,
        connection=connection,
        recognized_by="known_thin_adapter",
        recognition_mode="known_adapter",
        confidence=float(result["confidence"]),
    )


def _mcp_plan_from_adapter_draft(
    adapter_draft: dict[str, Any],
    *,
    write_strategy: str,
    would_write: list[str],
) -> dict[str, Any]:
    mcp = adapter_draft.get("mcp") if isinstance(adapter_draft.get("mcp"), dict) else {}
    return {
        "plan_source": "adapter_draft" if adapter_draft else "legacy_plan",
        "supports_mcp_likely": bool(mcp.get("supports_mcp_likely")),
        "skill_surface_likely": bool(mcp.get("skill_surface_likely")),
        "auto_connect_supported_now": bool(mcp.get("auto_connect_supported_now")),
        "apply_endpoint_status": mcp.get("apply_endpoint_status", ""),
        "next_step": mcp.get("next_step", ""),
        "write_strategy": write_strategy,
        "detected_config_paths": list(mcp.get("config_paths") or []),
        "candidate_config_patterns": list(mcp.get("candidate_config_patterns") or []),
        "would_write": would_write,
        "capability_check_after_connect": True,
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
    }


def _collector_plan_from_adapter_draft(adapter_draft: dict[str, Any]) -> dict[str, Any]:
    collector = adapter_draft.get("collector") if isinstance(adapter_draft.get("collector"), dict) else {}
    collector_status = str(collector.get("collector_status") or "no_content_store_detected")
    return {
        "plan_source": "adapter_draft" if adapter_draft else "legacy_plan",
        "collector_status": collector_status,
        "collector_kind": collector.get("collector_kind", "verified_format_collector"),
        "required_before_real_recall": collector_status == "verified_collector_required",
        "parser_gate": collector.get("parser_gate", "verified_format_collector_required"),
        "native_artifact_format": collector.get("native_artifact_format", ""),
        "storage_candidate": collector.get("storage_candidate", ""),
        "content_store_paths": list(collector.get("content_store_paths") or []),
        "workspace_paths": list(collector.get("workspace_paths") or []),
        "complete_conversation_candidate": bool(collector.get("complete_conversation_candidate")),
        "assistant_replies_may_persist": collector.get("assistant_replies_may_persist", False),
        "assistant_reply_persistence": collector.get("assistant_reply_persistence", "unverified"),
        "content_read": False,
        "chat_body_included": False,
        "raw_excerpt_included": False,
    }


def _raw_archive_plan_from_adapter_draft(adapter_draft: dict[str, Any], system: str) -> dict[str, Any]:
    raw_archive = adapter_draft.get("raw_archive") if isinstance(adapter_draft.get("raw_archive"), dict) else {}
    return {
        "plan_source": "adapter_draft" if adapter_draft else "legacy_plan",
        "layout": raw_archive.get("layout", "computer_first"),
        "effective_from_version": raw_archive.get("effective_from_version", "2026.6.1"),
        "segment_order": list(raw_archive.get("segment_order") or ["computer_name", "source_system", "native_artifact_format"]),
        "source_system": raw_archive.get("source_system", system),
        "native_artifact_format": raw_archive.get("native_artifact_format", f"{_slug(system)}_native_store"),
        "preferred_template": raw_archive.get(
            "preferred_template",
            "memory/{computer_name}/{source_system}/{native_artifact_format}/{native_scope}/{session_id}.jsonl",
        ),
        "legacy_layout_allowed_for_new_writes": bool(raw_archive.get("legacy_layout_allowed_for_new_writes", False)),
    }


def _build_adapter_autoconnect_plan(
    adapter: dict[str, Any],
    *,
    home: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    system = str(adapter.get("system") or "")
    status = _plan_status(adapter)
    would_write: list[str] = []
    if status == AUTO_CONNECT_READY_STATUS:
        would_write = _expanded_autoconnect_targets(system, adapter=adapter, home=home, env=env)
    restart_required = system in {"codex", "claude_desktop", "cursor", "continue", "roo_code", "cline"} or _catalog_json_mcp_apply_supported(system)
    adapter_draft = _adapter_draft_for_plan(adapter)
    write_strategy = _write_strategy_for_system(system)
    mcp_plan = _mcp_plan_from_adapter_draft(
        adapter_draft,
        write_strategy=write_strategy,
        would_write=would_write,
    )
    collector_plan = _collector_plan_from_adapter_draft(adapter_draft)
    raw_archive_plan = _raw_archive_plan_from_adapter_draft(adapter_draft, system)
    conversation_boundary = adapter_draft.get("conversation_memory_boundary") or adapter.get("conversation_memory_boundary") or _conversation_memory_boundary(system)
    return {
        "system": system,
        "display_name": adapter.get("display_name"),
        "support_level": adapter.get("support_level"),
        "plan_source": "adapter_draft",
        "adapter_draft_consumed": True,
        "status": status,
        "detected": bool(adapter.get("detected")),
        "connectable_now": bool(adapter.get("connectable_now")),
        "intent_signal_detected": bool(adapter.get("intent_signal_detected")),
        "software": adapter.get("software", {}),
        "activity": adapter.get("activity", {}),
        "freshness": (adapter.get("activity") or {}).get("freshness", "unknown"),
        "missing": _missing_for_adapter(adapter),
        "write_strategy": write_strategy,
        "would_write": would_write,
        "would_create_parent_dirs": [
            str(Path(path).parent)
            for path in would_write
            if not _safe_is_dir(Path(path).parent)
        ],
        "backup_required": bool(would_write),
        "backup_plan": "copy_each_existing_config_before_write" if would_write else "not_applicable",
        "receipt_required": bool(would_write),
        "restart_required": restart_required if would_write else False,
        "capability_check_after_connect": True,
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        "real_recall_after_connect": False,
        "mcp_plan": mcp_plan,
        "collector_plan": collector_plan,
        "raw_archive_plan": raw_archive_plan,
        "next_actions": list(adapter_draft.get("next_actions") or []),
        "parser_gate": collector_plan.get("parser_gate") or adapter.get("content_gate"),
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": conversation_boundary,
        "provisional_adapter_candidate": adapter.get("provisional_adapter_candidate", {}),
        "adapter_draft": adapter_draft,
        "rollback_plan": "restore_backup_file_and_remove_added_mcp_server" if would_write else "not_applicable",
        "apply_endpoint_status": _apply_endpoint_status_for_system(system),
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
    }


def build_authorized_auto_connect_dry_run(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    system: str | None = None,
    include_generic: bool = True,
) -> dict[str, Any]:
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    registry = build_thin_adapter_registry(
        runtime_profile,
        home=resolved_home,
        env=resolved_env,
        include_generic=include_generic,
    )
    adapters = registry.get("adapters", [])
    generic_surfaces = registry.get("generic_surface_discovery", {}).get("surfaces", [])
    if system:
        adapters = [item for item in adapters if item.get("system") == system]
        generic_surfaces = [item for item in generic_surfaces if item.get("system") == system]
        if not include_generic and not adapters and system not in _known_adapter_systems():
            generic = build_generic_local_ai_surfaces(home=resolved_home, env=resolved_env)
            generic_surfaces = [
                item for item in generic.get("surfaces", [])
                if item.get("system") == system
            ]
    plans = [
        _build_adapter_autoconnect_plan(adapter, home=resolved_home, env=resolved_env)
        for adapter in adapters
    ]
    for surface in generic_surfaces:
        adapter_like = {
            "system": surface.get("system"),
            "display_name": surface.get("display_name"),
            "support_level": "generic_surface_candidate",
            "detected": surface.get("detected"),
            "connectable_now": surface.get("connectable_now"),
            "intent_signal_detected": surface.get("intent_signal_detected"),
            "content_gate": "verified_format_collector_required",
            "conversation_memory_boundary": surface.get("conversation_memory_boundary") or _conversation_memory_boundary(
                str(surface.get("system") or ""),
                [
                    *list(surface.get("content_store_paths") or []),
                    *list(surface.get("workspace_paths") or []),
                ],
            ),
            "current_focus": True,
            "instances": [{"type": "config", "path": path} for path in surface.get("config_paths", [])],
            "software": surface.get("software", {}),
            "activity": surface.get("activity", {}),
            "provisional_adapter_candidate": surface.get("provisional_adapter_candidate", {}),
        }
        plans.append(_build_adapter_autoconnect_plan(adapter_like, home=resolved_home, env=resolved_env))
    return {
        "ok": bool(plans) or system is None,
        "contract": AUTOCONNECT_DRY_RUN_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "system_filter": system or "",
        "scan_mode": "full" if include_generic else "fast_known_adapters_only",
        "plan_count": len(plans),
        "plans": plans,
        "apply_endpoint_status": "implemented_for_json_mcp_surfaces",
        "implemented_apply_systems": _implemented_apply_systems(),
        "authorization_required_before_apply": list(APPLY_GATE_CONFIRMATIONS),
        "conditional_authorization_required_before_apply": {
            "confirm_connect_stale_or_dormant_platform": "required when a target platform is stale or dormant and a config write would occur",
        },
        "global_guarantees": {
            "dry_run_only": True,
            "backup_and_receipt_on_apply": True,
            "conversation_import_mode": "verified_format_collectors",
            "real_recall_after_connect": False,
            "user_or_installer_approval_required_before_apply": True,
        },
    }


def _confirmation_enabled(body: dict[str, Any], name: str) -> bool:
    value = body.get(name)
    if value is True:
        return True
    confirmations = body.get("confirmations")
    if isinstance(confirmations, dict) and confirmations.get(name) is True:
        return True
    if isinstance(confirmations, list) and name in confirmations:
        return True
    return False


def build_authorized_auto_connect_apply_gate_dry_run(
    body: dict[str, Any] | None = None,
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    include_generic: bool = False,
) -> dict[str, Any]:
    payload = body or {}
    system = str(payload.get("system") or payload.get("target_system") or "").strip() or None
    plan = build_authorized_auto_connect_dry_run(
        runtime_profile,
        home=home,
        env=env,
        system=system,
        include_generic=include_generic,
    )
    plans = plan.get("plans", [])
    installer_approved = bool(
        payload.get("installer_approved")
        or payload.get("user_approved")
        or payload.get("user_requested_auto_connect")
    )
    missing_confirmations = [
        name for name in APPLY_GATE_CONFIRMATIONS
        if not installer_approved and not _confirmation_enabled(payload, name)
    ]
    blocked_reasons: list[str] = []
    if not system:
        blocked_reasons.append("system_required")
    if not plans:
        blocked_reasons.append("no_connect_plan_found")
    planned = plans[0] if plans else {}
    stale_write_notice = (
        planned.get("freshness") in STALE_OR_DORMANT_FRESHNESS
        and bool(planned.get("would_write"))
        and planned.get("status") == AUTO_CONNECT_READY_STATUS
    )
    stale_confirmation_required = bool(
        stale_write_notice
        and not installer_approved
        and not _confirmation_enabled(payload, STALE_PLATFORM_CONFIRMATION)
    )
    if stale_confirmation_required:
        missing_confirmations.append(STALE_PLATFORM_CONFIRMATION)
    if planned.get("status") == "not_detected":
        blocked_reasons.append("platform_not_detected")
    if planned.get("status") == "parked_not_current_focus":
        blocked_reasons.append("platform_not_current_focus")
    if planned.get("status") == "ready_for_capability_check":
        blocked_reasons.append("already_connectable")
    if planned and not planned.get("would_write"):
        blocked_reasons.append("no_platform_config_target")
    if missing_confirmations:
        blocked_reasons.append("missing_authorization_confirmations")
    ready = not blocked_reasons
    receipt = {
        "receipt_type": "authorized_auto_connect_apply_gate",
        "system": system or "",
        "plan_source": planned.get("plan_source", "adapter_draft" if planned.get("adapter_draft") else "legacy_plan"),
        "adapter_draft_consumed": bool(planned.get("adapter_draft_consumed")),
        "write_strategy": planned.get("write_strategy"),
        "would_write": planned.get("would_write", []),
        "mcp_plan": planned.get("mcp_plan", {}),
        "collector_plan": planned.get("collector_plan", {}),
        "raw_archive_plan": planned.get("raw_archive_plan", {}),
        "next_actions": planned.get("next_actions", []),
        "adapter_draft_id": (planned.get("adapter_draft") or {}).get("draft_id", ""),
        "backup_plan": planned.get("backup_plan"),
        "rollback_plan": planned.get("rollback_plan"),
        "capability_check_payload": planned.get("capability_check_payload") or CAPABILITY_CHECK_PAYLOAD,
        "freshness": planned.get("freshness", "unknown"),
        "stale_or_dormant_confirmation_required": bool(stale_confirmation_required),
        "stale_or_dormant_notice": bool(stale_write_notice),
        "real_recall_after_connect": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": planned.get("conversation_memory_boundary") or _conversation_memory_boundary(system or ""),
    }
    return {
        "ok": True,
        "contract": AUTOCONNECT_APPLY_GATE_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "system": system or "",
        "status": "ready_for_auto_connect" if ready else "blocked",
        "ready_for_auto_connect": ready,
        "ready_after_authorization": ready,
        "missing_confirmations": missing_confirmations,
        "blocked_reasons": blocked_reasons,
        "plan": planned,
        "receipt_preview": receipt,
        "apply_endpoint_status": _apply_endpoint_status_for_system(system or ""),
        "global_guarantees": {
            "backup_before_write": True,
            "receipt_after_write": True,
            "conversation_import_mode": "verified_format_collectors",
            "real_recall_after_connect": False,
            "adapter_draft_consumed": True,
        },
    }


def _platform_apply_receipts_dir(memcore_root: Path | None) -> Path:
    root = memcore_root or Path.cwd()
    return root / "output" / "platform_auto_connect" / "receipts"


def _backup_platform_config(path: Path, *, memcore_root: Path | None, system: str) -> str:
    backup_dir = (memcore_root or Path.cwd()) / "backups" / "platform_auto_connect" / system
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.name}.{_stamp()}.bak"
    if _safe_is_file(path):
        shutil.copy2(path, backup_path)
    else:
        backup_path.write_text("", encoding="utf-8")
    return str(backup_path)


def _write_json_object(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _mcp_server_section_key(config: dict[str, Any], system: str = "") -> str:
    for key in ("mcpServers", "mcp_servers", "servers"):
        if isinstance(config.get(key), dict):
            return key
    for key in _catalog_config_keys(system):
        return key
    return "mcpServers"


def _apply_json_mcp_server(target_path: Path, *, system: str = "") -> dict[str, Any]:
    config = _load_json_object(target_path)
    section_key = _mcp_server_section_key(config, system)
    servers = config.get(section_key)
    if not isinstance(servers, dict):
        servers = {}
        config[section_key] = servers
    before = servers.get(MEMCORE_MCP_SERVER_NAME)
    desired = {"type": "http", "url": MEMCORE_MCP_HTTP_URL}
    already_configured = before == desired
    servers[MEMCORE_MCP_SERVER_NAME] = desired
    _write_json_object(target_path, config)
    return {
        "target_path": str(target_path),
        "section_key": section_key,
        "server_name": MEMCORE_MCP_SERVER_NAME,
        "server_url": MEMCORE_MCP_HTTP_URL,
        "already_configured": already_configured,
    }


def _resolve_codex_cli(
    *,
    home: Path,
    env: dict[str, str],
    software: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    cli = software.get("cli") if isinstance(software, dict) and isinstance(software.get("cli"), dict) else {}
    configured = str(cli.get("path") or "").strip()
    if configured:
        return configured, str(cli.get("source") or "detected_cli"), {}
    executable = shutil.which("codex", path=env.get("PATH"))
    if executable:
        return executable, "path", {}
    executable, native_host = _codex_cli_from_native_hosts(home, env)
    if executable:
        return executable, "codex_chrome_native_host", native_host
    return "", "", {}


def _resolve_codex_bridge_path(memcore_root: Path | None) -> Path:
    candidates: list[Path] = []
    if memcore_root is not None:
        candidates.append(memcore_root / "tools" / "codex_mcp_bridge.py")
    candidates.append(_repo_root() / "tools" / "codex_mcp_bridge.py")
    for candidate in candidates:
        if _safe_is_file(candidate):
            return candidate
    return candidates[0]


def _codex_python_executable(payload: dict[str, Any], env: dict[str, str]) -> str:
    for key in ("python_executable", "python", "MEMCORE_PYTHON", "PYTHON"):
        value = payload.get(key) if key in payload else env.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return sys.executable


def _apply_codex_mcp_server(
    target_path: Path,
    *,
    home: Path,
    env: dict[str, str],
    memcore_root: Path | None,
    planned: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    software = planned.get("software") if isinstance(planned.get("software"), dict) else {}
    codex_cli, codex_cli_source, native_host = _resolve_codex_cli(
        home=home,
        env=env,
        software=software,
    )
    if not codex_cli:
        raise RuntimeError("codex_cli_not_found")
    bridge = _resolve_codex_bridge_path(memcore_root)
    if not _safe_is_file(bridge):
        raise RuntimeError(f"codex_mcp_bridge_not_found:{bridge}")
    root = memcore_root or _repo_root()
    registry_path = Path(
        str(
            payload.get("window_binding_registry")
            or env.get("MEMCORE_WINDOW_BINDING_REGISTRY")
            or (root / "config" / "window_binding_registry.json")
        )
    ).expanduser()
    python_executable = _codex_python_executable(payload, env)
    already_configured = _config_probe(target_path).get("memcore_mcp_detected") if _safe_is_file(target_path) else False
    bridge_env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "MEMCORE_ROOT": str(root),
        "MEMCORE_WINDOW_BINDING_REGISTRY": str(registry_path),
    }
    run_env = dict(os.environ)
    run_env.update(env)
    run_env.update(bridge_env)
    remove_cmd = [codex_cli, "mcp", "remove", MEMCORE_MCP_SERVER_NAME]
    add_args = [
        "mcp",
        "add",
        MEMCORE_MCP_SERVER_NAME,
        "--env",
        "PYTHONIOENCODING=utf-8",
        "--env",
        "PYTHONUTF8=1",
        "--env",
        f"MEMCORE_ROOT={root}",
        "--env",
        f"MEMCORE_WINDOW_BINDING_REGISTRY={registry_path}",
        "--",
        python_executable,
        str(bridge),
        "--endpoint",
        MEMCORE_MCP_HTTP_URL,
        "--timeout",
        "30",
        "--window-binding-registry",
        str(registry_path),
        "--binding-key",
        "codex",
    ]
    add_cmd = [codex_cli, *add_args]
    remove_result = subprocess.run(
        remove_cmd,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env=run_env,
    )
    add_result = subprocess.run(
        add_cmd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=run_env,
    )
    if add_result.returncode != 0:
        detail = (add_result.stderr or add_result.stdout or "").strip()
        raise RuntimeError(f"codex_mcp_add_failed:{add_result.returncode}:{detail[:500]}")
    return {
        "target_path": str(target_path),
        "server_name": MEMCORE_MCP_SERVER_NAME,
        "type": "stdio_bridge",
        "command": codex_cli,
        "args": add_args,
        "env": bridge_env,
        "python": python_executable,
        "bridge_path": str(bridge),
        "endpoint": MEMCORE_MCP_HTTP_URL,
        "window_binding_registry": str(registry_path),
        "binding_key": "codex",
        "codex_cli_source": codex_cli_source,
        "native_host": native_host,
        "already_configured": bool(already_configured),
        "remove_returncode": remove_result.returncode,
        "add_returncode": add_result.returncode,
        "config_write_mode": "codex_cli_mcp_add",
    }


def _persist_platform_apply_receipt(receipt: dict[str, Any], *, memcore_root: Path | None) -> str:
    receipts_dir = _platform_apply_receipts_dir(memcore_root)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    safe_system = _slug(str(receipt.get("system") or "unknown"))
    receipt_id = str(receipt.get("receipt_id") or f"{_stamp()}-{safe_system}")
    receipt_path = receipts_dir / f"{receipt_id}.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest_path = receipts_dir / "latest.json"
    latest_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(receipt_path)


def _mcp_target_paths_for_system(system: str, home: Path | None, env: dict[str, str] | None) -> list[Path]:
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    targets: list[Path] = []
    roots = _generic_scan_roots(resolved_home, resolved_env)
    patterns = tuple(dict.fromkeys((
        *AUTOCONNECT_TARGET_PATTERNS.get(system, ()),
        *_catalog_mcp_config_patterns(system),
    )))
    for pattern in patterns:
        path = _expand_path(pattern, resolved_home, resolved_env)
        expanded_paths = _expanded_catalog_pattern_paths(pattern, home=resolved_home, env=resolved_env, roots=roots)
        for candidate in ([path] if path is not None else []) + expanded_paths:
            if "*" not in str(candidate):
                targets.append(candidate)
    if system not in AUTOCONNECT_TARGET_PATTERNS:
        generic = build_generic_local_ai_surfaces(home=resolved_home, env=resolved_env)
        for surface in generic.get("surfaces", []):
            if surface.get("system") != system:
                continue
            for path in surface.get("config_paths", []):
                targets.append(Path(str(path)))
    unique: list[Path] = []
    seen = set()
    for path in targets:
        text = str(path)
        if text not in seen:
            unique.append(path)
            seen.add(text)
    return unique


def _connected_mcp_target(system: str, home: Path | None, env: dict[str, str] | None) -> Path | None:
    for path in _mcp_target_paths_for_system(system, home, env):
        if not _safe_is_file(path):
            continue
        probe = _config_probe(path)
        if probe.get("memcore_mcp_detected"):
            return path
    return None


def apply_authorized_auto_connect(
    body: dict[str, Any] | None = None,
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    memcore_root: Path | None = None,
) -> dict[str, Any]:
    payload = body or {}
    system = str(payload.get("system") or payload.get("target_system") or "").strip()
    gate = build_authorized_auto_connect_apply_gate_dry_run(
        payload,
        runtime_profile,
        home=home,
        env=env,
        include_generic=bool(payload.get("include_generic") or payload.get("scan") in {"full", "deep"}),
    )
    if not system:
        return {
            **gate,
            "ok": False,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "read_only": False,
            "dry_run": False,
            "status": "blocked",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "error": "system_required",
        }
    if system not in _implemented_apply_systems():
        return {
            **gate,
            "ok": False,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "read_only": False,
            "dry_run": False,
            "status": "blocked",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "error": "apply_not_implemented_for_system",
            "implemented_apply_systems": _implemented_apply_systems(),
        }
    planned = gate.get("plan") if isinstance(gate.get("plan"), dict) else {}
    if "already_connectable" in gate.get("blocked_reasons", []):
        target_path = _connected_mcp_target(system, home, env)
        receipt = {
            "receipt_id": f"{_stamp()}-{system}-already-connected",
            "receipt_type": "authorized_auto_connect_apply",
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "recorded_at": ts(),
            "system": system,
            "display_name": (gate.get("plan") or {}).get("display_name") or system,
            "status": "already_connected",
            "plan_source": planned.get("plan_source", "adapter_draft" if planned.get("adapter_draft") else "legacy_plan"),
            "adapter_draft_consumed": bool(planned.get("adapter_draft_consumed")),
            "adapter_draft_id": (planned.get("adapter_draft") or {}).get("draft_id", ""),
            "mcp_plan": planned.get("mcp_plan", {}),
            "collector_plan": planned.get("collector_plan", {}),
            "raw_archive_plan": planned.get("raw_archive_plan", {}),
            "next_actions": planned.get("next_actions", []),
            "target_path": str(target_path) if target_path else "",
            "backup_path": "",
            "rollback_plan": "not_applicable_existing_connection_preserved",
            "applied_mcp_server": {
                "name": MEMCORE_MCP_SERVER_NAME,
                "type": "stdio_bridge" if system == "codex" else "http",
                "url": "" if system == "codex" else MEMCORE_MCP_HTTP_URL,
                "endpoint": MEMCORE_MCP_HTTP_URL if system == "codex" else "",
                "already_configured": True,
            },
            "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
            "capability_check_after_connect": True,
            "real_recall_after_connect": False,
            "chat_body_parser_requires_verified_collector": True,
            "chat_body_parser_requires_separate_authorization": True,
            "conversation_memory_boundary": (gate.get("plan") or {}).get("conversation_memory_boundary") or _conversation_memory_boundary(system),
            "read_chat_bodies": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
        }
        receipt_path = _persist_platform_apply_receipt(receipt, memcore_root=memcore_root)
        return {
            "ok": True,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "generated_at": ts(),
            "read_only": False,
            "dry_run": False,
            "system": system,
            "status": "already_connected",
            "write_performed": True,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "chat_body_parser_requires_verified_collector": True,
            "chat_body_parser_requires_separate_authorization": True,
            "real_recall_after_connect": False,
            "target_path": str(target_path) if target_path else "",
            "backup_path": "",
            "receipt_path": receipt_path,
            "receipt": receipt,
            "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
            "mcp_plan": receipt["mcp_plan"],
            "collector_plan": receipt["collector_plan"],
            "raw_archive_plan": receipt["raw_archive_plan"],
        }
    if not gate.get("ready_for_auto_connect"):
        return {
            **gate,
            "ok": False,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "read_only": False,
            "dry_run": False,
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "error": "apply_gate_blocked",
        }

    targets = [Path(path) for path in planned.get("would_write", [])]
    if system == "codex":
        target_path = next((path for path in targets if path.name.lower() == "config.toml"), None)
    elif system == "claude_code_cli":
        target_path = next((path for path in targets if path.name == ".claude.json"), None)
    else:
        target_path = next(
            (path for path in targets if path.suffix.lower() == ".json" or "mcp" in path.name.lower()),
            None,
        )
    if target_path is None and targets:
        target_path = targets[0]
    if target_path is None:
        return {
            **gate,
            "ok": False,
            "contract": AUTOCONNECT_APPLY_CONTRACT,
            "read_only": False,
            "dry_run": False,
            "status": "blocked",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "error": "codex_mcp_config_not_planned" if system == "codex" else "json_mcp_config_not_planned",
        }

    backup_path = _backup_platform_config(target_path, memcore_root=memcore_root, system=system)
    if system == "codex":
        applied = _apply_codex_mcp_server(
            target_path,
            home=home or Path.home(),
            env=_effective_env(home or Path.home(), env),
            memcore_root=memcore_root,
            planned=planned,
            payload=payload,
        )
    else:
        applied = _apply_json_mcp_server(target_path, system=system)
    receipt = {
        "receipt_id": f"{_stamp()}-{system}",
        "receipt_type": "authorized_auto_connect_apply",
        "contract": AUTOCONNECT_APPLY_CONTRACT,
        "recorded_at": ts(),
        "system": system,
        "display_name": planned.get("display_name") or system,
        "plan_source": planned.get("plan_source", "adapter_draft" if planned.get("adapter_draft") else "legacy_plan"),
        "adapter_draft_consumed": bool(planned.get("adapter_draft_consumed")),
        "adapter_draft_id": (planned.get("adapter_draft") or {}).get("draft_id", ""),
        "write_strategy": planned.get("write_strategy"),
        "mcp_plan": planned.get("mcp_plan", {}),
        "collector_plan": planned.get("collector_plan", {}),
        "raw_archive_plan": planned.get("raw_archive_plan", {}),
        "next_actions": planned.get("next_actions", []),
        "target_path": str(target_path),
        "backup_path": backup_path,
        "rollback_plan": "restore_backup_file_and_remove_added_mcp_server",
        "applied_mcp_server": {
            "name": applied["server_name"],
            "type": applied.get("type", "http"),
            "url": applied.get("server_url", ""),
            "endpoint": applied.get("endpoint", applied.get("server_url", "")),
            "command": applied.get("command", ""),
            "args": applied.get("args", []),
            "env": applied.get("env", {}),
            "already_configured": applied["already_configured"],
        },
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        "capability_check_after_connect": True,
        "real_recall_after_connect": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "conversation_memory_boundary": planned.get("conversation_memory_boundary") or _conversation_memory_boundary(system),
        "read_chat_bodies": False,
        "memory_write_performed": False,
        "platform_write_performed": True,
    }
    receipt_path = _persist_platform_apply_receipt(receipt, memcore_root=memcore_root)
    return {
        "ok": True,
        "contract": AUTOCONNECT_APPLY_CONTRACT,
        "generated_at": ts(),
        "read_only": False,
        "dry_run": False,
        "system": system,
        "status": "applied",
        "write_performed": True,
        "platform_write_performed": True,
        "memory_write_performed": False,
        "chat_body_parser_requires_verified_collector": True,
        "chat_body_parser_requires_separate_authorization": True,
        "real_recall_after_connect": False,
        "target_path": str(target_path),
        "backup_path": backup_path,
        "receipt_path": receipt_path,
        "receipt": receipt,
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        "mcp_plan": receipt["mcp_plan"],
        "collector_plan": receipt["collector_plan"],
        "raw_archive_plan": receipt["raw_archive_plan"],
    }
