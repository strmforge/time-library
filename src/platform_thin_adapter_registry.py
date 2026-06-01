"""Read-only thin-adapter registry for local AI tools.

The registry is the product-facing shape of "Tiandao + thin adapters":
Memcore Cloud can recognize many local AI surfaces, but detection is metadata
only. Connecting, writing platform config, or parsing chat bodies remains behind
explicit authorization and receipts.
"""

from __future__ import annotations

import os
import glob
import json
import plistlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

REGISTRY_CONTRACT = "thin_adapter_registry.v1"
AUTOCONNECT_DRY_RUN_CONTRACT = "authorized_auto_connect_dry_run.v1"
AUTOCONNECT_APPLY_GATE_CONTRACT = "authorized_auto_connect_apply_gate.v1"
AUTOCONNECT_APPLY_CONTRACT = "authorized_auto_connect_apply.v1"
DISCOVERY_DASHBOARD_CONTRACT = "platform_discovery_dashboard.v1"
PLATFORM_CATALOG_CONTRACT = "platform_catalog.v1"
PACKAGE_MANAGER_INVENTORY_CONTRACT = "package_manager_agent_inventory.v1"
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
IMPLEMENTED_APPLY_SYSTEMS = ("claude_code_cli", "cursor", "continue", "roo_code", "cline", "kiro")
JSON_MCP_APPLY_SYSTEMS = frozenset(IMPLEMENTED_APPLY_SYSTEMS)
CATALOG_JSON_APPLY_DENYLIST = frozenset({"claude_desktop", "codex", "zed"})
STALE_OR_DORMANT_FRESHNESS = {"stale", "dormant"}
STALE_PLATFORM_CONFIRMATION = "confirm_connect_stale_or_dormant_platform"
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
    content_gate: str = "explicit_authorized_parser_required"
    current_focus: bool = True
    notes: tuple[str, ...] = ()


ADAPTER_SPECS: tuple[AdapterSpec, ...] = (
    AdapterSpec(
        system="codex",
        display_name="Codex",
        support_level="supported_source_and_consumer",
        platform_family="agent_cli",
        connection_surfaces=("skill", "mcp", "session_jsonl"),
        config_paths=("$CODEX_HOME/config.toml", "~/.codex/config.toml"),
        skill_paths=(
            "$CODEX_HOME/skills/yifanchen-zhiyi/SKILL.md",
            "$CODEX_HOME/skills/yifanchen/SKILL.md",
            "~/.codex/skills/yifanchen-zhiyi/SKILL.md",
            "~/.codex/skills/yifanchen/SKILL.md",
        ),
        content_paths=("$CODEX_HOME/sessions", "~/.codex/sessions"),
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
        content_gate="explicit_authorized_parser_required",
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


def _platform_catalog_path() -> Path:
    return _repo_root() / "config" / "platform_catalog.json"


def _platform_watchlist_path() -> Path:
    return _repo_root() / "config" / "platform_watchlist.github_top100.json"


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def load_platform_catalog(
    catalog_path: Path | None = None,
    watchlist_path: Path | None = None,
) -> dict[str, Any]:
    """Load the curated platform catalog plus the generated GitHub watchlist."""
    resolved_catalog_path = catalog_path or _platform_catalog_path()
    resolved_watchlist_path = watchlist_path or _platform_watchlist_path()
    catalog = _load_json_object(resolved_catalog_path)
    watchlist = _load_json_object(resolved_watchlist_path)
    curated_entries = _list_of_dicts(catalog.get("entries"))
    watchlist_entries = _list_of_dicts(watchlist.get("entries"))
    entries = curated_entries + [
        entry for entry in watchlist_entries
        if entry.get("id") not in {item.get("id") for item in curated_entries}
    ]
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
        "entry_count": len(entries),
        "curated_entry_count": len(curated_entries),
        "github_watchlist_entry_count": len(watchlist_entries),
        "source_url_count": len(source_urls),
        "source_urls": source_urls,
        "entries": entries,
    }


def _platform_catalog_entries() -> dict[str, dict[str, Any]]:
    return {
        str(entry.get("id")): entry
        for entry in load_platform_catalog().get("entries", [])
        if entry.get("id")
    }


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
    return tuple(str(pattern) for pattern in patterns if _looks_like_path_pattern(str(pattern)))


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
    if not entry:
        return {}
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


def _implemented_apply_systems() -> list[str]:
    systems = set(IMPLEMENTED_APPLY_SYSTEMS)
    for system in _platform_catalog_entries():
        if _catalog_json_mcp_apply_supported(system):
            systems.add(system)
    return sorted(systems)


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


def _catalog_system_for_install_name(name: str) -> str | None:
    variants = _identifier_variants(name)
    if not variants:
        return None
    best: tuple[int, str] | None = None
    for system, entry in _platform_catalog_entries().items():
        terms = _catalog_detection_terms(system, entry)
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
    resolved_env = dict(os.environ if env is None else env)
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


def _cli_version_metadata(system: str) -> dict[str, Any]:
    command = _catalog_cli_version_command(system)
    if not command:
        return {"installed": False, "path": "", "version": "", "raw": ""}
    executable = shutil.which(command[0])
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
        "chat_body_parser_requires_separate_authorization": True,
    }


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
) -> dict[str, Any]:
    resolved_home = home or Path.home()
    resolved_env = dict(os.environ if env is None else env)
    roots = _generic_scan_roots(resolved_home, resolved_env)
    package_inventory = build_package_manager_agent_inventory(home=resolved_home, env=resolved_env)
    surfaces: dict[str, dict[str, Any]] = {}
    seen_config_paths: set[str] = set()
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
    for path in _iter_generic_config_candidates(roots):
        if str(path) in seen_config_paths:
            continue
        probe = _config_probe(path)
        if not probe.get("mcp_detected") and not probe.get("intent_signal_detected"):
            continue
        system = _infer_surface_id(path, resolved_home)
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
    for path in _iter_generic_workspace_candidates(roots):
        system = _infer_surface_id(path, resolved_home)
        surface = surfaces.setdefault(system, _generic_surface_record(system, source="generic_workspace_surface_scan"))
        _refresh_catalog_surface_metadata(surface, system)
        path_text = str(path)
        if path_text not in surface["content_store_paths"]:
            surface["content_store_paths"].append(path_text)
        if path_text not in surface["workspace_paths"]:
            surface["workspace_paths"].append(path_text)
        surface["signals"].append({
            "kind": "workspace_surface",
            "path": path_text,
            "content_read": False,
            "parser_gate": "explicit_authorized_parser_required",
        })
    for repo_path in _iter_git_repo_candidates(roots):
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
        cli = _cli_version_metadata(system)
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
        cli = _cli_version_metadata(system)
        if app.get("installed") and app.get("bundle_path"):
            activity_records.append(("app_bundle", Path(str(app["bundle_path"]))))
        if cli.get("installed") and cli.get("path"):
            activity_records.append(("cli_binary", Path(str(cli["path"]))))
        surface["software"] = {
            "app": app,
            "cli": cli,
        }
        surface["activity"] = _activity_snapshot(activity_records)
    return {
        "ok": True,
        "contract": GENERIC_DISCOVERY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "scan_roots": [str(root) for root in roots],
        "surface_count": len(surfaces),
        "surfaces": list(surfaces.values()),
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
        "limits": {
            "max_depth": 5,
            "max_dirs": 500,
            "max_workspace_dirs": 3000,
            "max_files": 800,
        },
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
            "action": "register_missing_thin_adapter",
            "status": "needs_authorization",
            "reason": "memcore_skill_or_mcp_signal_detected",
            "requires_user_authorization": True,
            "writes_platform_config": True,
        })
    else:
        actions.append({
            "action": "offer_connect_prompt",
            "status": "needs_authorization",
            "reason": "platform_detected_without_memcore_signal",
            "requires_user_authorization": True,
            "writes_platform_config": False,
        })
    if content_bearing_store_detected:
        actions.append({
            "action": "raw_parser_gate",
            "status": "locked",
            "reason": "content_bearing_store_detected_but_not_read_by_default",
            "requires_user_authorization": True,
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
    cli = _cli_version_metadata(spec.system) if include_software_probe else {
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
        "chat_body_parser_requires_separate_authorization": True,
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
) -> dict[str, Any]:
    profile = runtime_profile or {}
    resolved_home = home or Path.home()
    resolved_env = dict(os.environ if env is None else env)
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
    generic = build_generic_local_ai_surfaces(home=resolved_home, env=resolved_env) if include_generic else {
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
    needs_authorization = [
        item for item in adapters
        if any(action.get("requires_user_authorization") for action in item.get("actions", []))
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
        "default_policy": "observe_known_surfaces_only_until_authorized",
        "scan_mode": "full" if include_generic else "fast_known_adapters_only",
        "software_probe_mode": "enabled" if software_probe else "skipped_for_fast_snapshot",
        "adapter_count": len(adapters),
        "catalog_entry_count": catalog.get("entry_count", 0),
        "github_watchlist_entry_count": catalog.get("github_watchlist_entry_count", 0),
        "detected_adapter_count": len(detected),
        "generic_surface_count": len(generic_surfaces),
        "generic_surface_memcore_ready_count": sum(1 for item in generic_surfaces if item.get("connectable_now")),
        "authorization_needed_count": len(needs_authorization),
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
        "authorization_contract": {
            "can_auto_discover": True,
            "can_auto_connect_without_authorization": False,
            "can_parse_chat_bodies_without_authorization": False,
            "can_write_platform_config_without_authorization": False,
            "skill_installation_is_consent_signal": True,
            "skill_installation_is_not_body_read_consent": True,
            "receipts_required_for_writes": True,
            "backup_required_before_platform_config_write": True,
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
    return "needs_authorization"


def _safe_next_step(status: str, item: dict[str, Any]) -> str:
    if status == "ready_for_capability_check":
        return "run_capability_check"
    if status == "needs_authorization":
        return "inspect_authorized_connect_plan"
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
        "chat_body_parser_requires_separate_authorization": True,
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
        "parser_gate": "explicit_authorized_parser_required",
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
        "chat_body_parser_requires_separate_authorization": True,
        "instance_count": len(config_paths) + len(content_store_paths) + len(workspace_paths) + len(installation_paths),
        "config_paths": config_paths,
        "content_store_paths": content_store_paths,
        "workspace_paths": workspace_paths,
        "installation_paths": installation_paths,
    }


def build_platform_discovery_dashboard(
    runtime_profile: dict[str, Any] | None = None,
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
    include_generic: bool = True,
) -> dict[str, Any]:
    resolved_home = home or Path.home()
    resolved_env = dict(os.environ if env is None else env)
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
        "needs_authorization": 1,
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
        "needs_authorization": sum(1 for item in items if item.get("status") == "needs_authorization"),
        "generic_surfaces": sum(1 for item in items if item.get("surface_type") == "generic_local_ai_surface"),
        "catalog_entries": int(catalog.get("entry_count") or 0),
        "catalog_watchlist": int(catalog.get("github_watchlist_entry_count") or 0),
        "catalog_detected": sum(1 for item in items if item.get("catalog_driven") and item.get("detected")),
        "package_manager_matches": int(package_inventory.get("match_count") or 0),
        "parked_not_current_focus": sum(1 for item in items if item.get("status") == "parked_not_current_focus"),
        "parser_gates_locked": sum(1 for item in items if item.get("chat_body_parser_requires_separate_authorization")),
        "stale": sum(1 for item in items if item.get("freshness") == "stale"),
        "dormant": sum(1 for item in items if item.get("freshness") == "dormant"),
    }
    public_summary = {
        "local_ai_tools": counts["total"],
        "detected_tools": counts["detected"],
        "ready_for_safe_check": counts["ready_for_capability_check"],
        "needs_permission_step": counts["needs_authorization"],
        "other_local_tools": counts["generic_surfaces"],
        "recently_quiet_tools": counts["stale"] + counts["dormant"],
        "install_record_matches": counts["package_manager_matches"],
    }
    return {
        "ok": True,
        "contract": DISCOVERY_DASHBOARD_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "name": "Memcore Cloud",
        "codename": "Yifanchen",
        "default_policy": "discover_only_until_authorized",
        "dashboard_goal": "show_local_ai_tools_with_safe_next_steps",
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
            "does_not_write_platform_config": True,
            "does_not_parse_chat_bodies": True,
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


def _write_strategy_for_system(system: str) -> str:
    if system == "claude_desktop":
        return "register_local_stdio_mcp_bridge"
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
    return "implemented_for_json_mcp_surfaces" if system in _implemented_apply_systems() else "not_implemented"


def _build_adapter_autoconnect_plan(
    adapter: dict[str, Any],
    *,
    home: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    system = str(adapter.get("system") or "")
    status = _plan_status(adapter)
    would_write: list[str] = []
    if status == "needs_authorization":
        would_write = _expanded_autoconnect_targets(system, adapter=adapter, home=home, env=env)
    restart_required = system in {"codex", "claude_desktop", "cursor", "continue", "roo_code", "cline"} or _catalog_json_mcp_apply_supported(system)
    return {
        "system": system,
        "display_name": adapter.get("display_name"),
        "support_level": adapter.get("support_level"),
        "status": status,
        "detected": bool(adapter.get("detected")),
        "connectable_now": bool(adapter.get("connectable_now")),
        "intent_signal_detected": bool(adapter.get("intent_signal_detected")),
        "software": adapter.get("software", {}),
        "activity": adapter.get("activity", {}),
        "freshness": (adapter.get("activity") or {}).get("freshness", "unknown"),
        "missing": _missing_for_adapter(adapter),
        "write_strategy": _write_strategy_for_system(system),
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
        "parser_gate": adapter.get("content_gate"),
        "chat_body_parser_requires_separate_authorization": True,
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
    resolved_env = dict(os.environ if env is None else env)
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
            "content_gate": "explicit_authorized_parser_required",
            "current_focus": True,
            "instances": [{"type": "config", "path": path} for path in surface.get("config_paths", [])],
            "software": surface.get("software", {}),
            "activity": surface.get("activity", {}),
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
            "stale_or_dormant_platform_with_config_write": STALE_PLATFORM_CONFIRMATION,
        },
        "global_guarantees": {
            "does_not_write_platform_config": True,
            "does_not_parse_chat_bodies": True,
            "does_not_recall_real_memory": True,
            "skill_installation_is_not_body_read_consent": True,
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
    missing_confirmations = [
        name for name in APPLY_GATE_CONFIRMATIONS
        if not _confirmation_enabled(payload, name)
    ]
    blocked_reasons: list[str] = []
    if not system:
        blocked_reasons.append("system_required")
    if not plans:
        blocked_reasons.append("no_connect_plan_found")
    planned = plans[0] if plans else {}
    stale_write_requires_confirmation = (
        planned.get("freshness") in STALE_OR_DORMANT_FRESHNESS
        and planned.get("would_write")
        and planned.get("status") == "needs_authorization"
    )
    if stale_write_requires_confirmation and not _confirmation_enabled(payload, STALE_PLATFORM_CONFIRMATION):
        missing_confirmations.append(STALE_PLATFORM_CONFIRMATION)
    if planned.get("status") == "not_detected":
        blocked_reasons.append("platform_not_detected")
    if planned.get("status") == "parked_not_current_focus":
        blocked_reasons.append("platform_not_current_focus")
    if planned.get("status") == "ready_for_capability_check":
        blocked_reasons.append("already_connectable")
    if planned and not planned.get("would_write"):
        blocked_reasons.append("no_platform_config_target")
    if stale_write_requires_confirmation and STALE_PLATFORM_CONFIRMATION in missing_confirmations:
        blocked_reasons.append("stale_or_dormant_platform_requires_intentional_connect")
    if missing_confirmations:
        blocked_reasons.append("missing_authorization_confirmations")
    ready = not blocked_reasons
    receipt = {
        "receipt_type": "authorized_auto_connect_apply_gate",
        "system": system or "",
        "write_strategy": planned.get("write_strategy"),
        "would_write": planned.get("would_write", []),
        "backup_plan": planned.get("backup_plan"),
        "rollback_plan": planned.get("rollback_plan"),
        "capability_check_payload": planned.get("capability_check_payload") or CAPABILITY_CHECK_PAYLOAD,
        "freshness": planned.get("freshness", "unknown"),
        "stale_or_dormant_confirmation_required": bool(stale_write_requires_confirmation),
        "real_recall_after_connect": False,
        "chat_body_parser_requires_separate_authorization": True,
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
        "status": "ready_after_authorization" if ready else "blocked",
        "ready_after_authorization": ready,
        "missing_confirmations": missing_confirmations,
        "blocked_reasons": blocked_reasons,
        "plan": planned,
        "receipt_preview": receipt,
        "apply_endpoint_status": _apply_endpoint_status_for_system(system or ""),
        "global_guarantees": {
            "does_not_write_platform_config": True,
            "does_not_parse_chat_bodies": True,
            "does_not_recall_real_memory": True,
            "requires_backup_before_write": True,
            "requires_receipt_after_write": True,
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
    resolved_env = dict(os.environ if env is None else env)
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
            "target_path": str(target_path) if target_path else "",
            "backup_path": "",
            "rollback_plan": "not_applicable_existing_connection_preserved",
            "applied_mcp_server": {
                "name": MEMCORE_MCP_SERVER_NAME,
                "type": "http",
                "url": MEMCORE_MCP_HTTP_URL,
                "already_configured": True,
            },
            "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
            "capability_check_after_connect": True,
            "real_recall_after_connect": False,
            "chat_body_parser_requires_separate_authorization": True,
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
            "chat_body_parser_requires_separate_authorization": True,
            "real_recall_after_connect": False,
            "target_path": str(target_path) if target_path else "",
            "backup_path": "",
            "receipt_path": receipt_path,
            "receipt": receipt,
            "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        }
    if not gate.get("ready_after_authorization"):
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

    planned = gate.get("plan") if isinstance(gate.get("plan"), dict) else {}
    targets = [Path(path) for path in planned.get("would_write", [])]
    if system == "claude_code_cli":
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
            "error": "json_mcp_config_not_planned",
        }

    backup_path = _backup_platform_config(target_path, memcore_root=memcore_root, system=system)
    applied = _apply_json_mcp_server(target_path, system=system)
    receipt = {
        "receipt_id": f"{_stamp()}-{system}",
        "receipt_type": "authorized_auto_connect_apply",
        "contract": AUTOCONNECT_APPLY_CONTRACT,
        "recorded_at": ts(),
        "system": system,
        "display_name": planned.get("display_name") or "Claude Code CLI",
        "write_strategy": planned.get("write_strategy"),
        "target_path": str(target_path),
        "backup_path": backup_path,
        "rollback_plan": "restore_backup_file_and_remove_added_mcp_server",
        "applied_mcp_server": {
            "name": applied["server_name"],
            "type": "http",
            "url": applied["server_url"],
            "already_configured": applied["already_configured"],
        },
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
        "capability_check_after_connect": True,
        "real_recall_after_connect": False,
        "chat_body_parser_requires_separate_authorization": True,
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
        "chat_body_parser_requires_separate_authorization": True,
        "real_recall_after_connect": False,
        "target_path": str(target_path),
        "backup_path": backup_path,
        "receipt_path": receipt_path,
        "receipt": receipt,
        "capability_check_payload": CAPABILITY_CHECK_PAYLOAD,
    }
