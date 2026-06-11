#!/usr/bin/env python3
"""Claude Desktop source-system connector.

This connector is intentionally read-only. It recognizes Claude Desktop as a
first-class local source system, reports supported evidence locations, and
builds a local sync manifest for user-owned Claude Desktop app data.

Export archives are only a cold-start/backfill fallback. The main source-system
line is local user-space sync from the Claude Desktop support directory and
related logs, with parser gates for content-bearing stores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
try:
    from src.raw_archive_layout import preferred_raw_archive_dir, preferred_raw_archive_path
except ImportError:
    from raw_archive_layout import preferred_raw_archive_dir, preferred_raw_archive_path
try:
    from src.window_binding_registry import register_current_window
except ImportError:
    from window_binding_registry import register_current_window
try:
    from src.tiandao.memory_routing import (
        TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
        conversation_capture_verdict,
        is_complete_conversation_roles,
    )
except ImportError:
    from tiandao.memory_routing import (
        TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
        conversation_capture_verdict,
        is_complete_conversation_roles,
    )

UTC = timezone.utc
SOURCE_SYSTEM = "claude_desktop"
SYNC_STATE_VERSION = 1
RAW_INGEST_SCHEMA_VERSION = 1
NATIVE_RAW_ARTIFACT_FORMAT = "claude_desktop_authorized_local_store_jsonl"
LOCAL_RELAY_PROXY_DB_ARTIFACT = "local_relay_proxy_request_logs_db"
SURFACE_CHAT = "claude_ai_web_chat"
SURFACE_COWORK = "claude_desktop_cowork"
SURFACE_CODE_OR_AGENT = "claude_desktop_code_or_agent"
CHAT_BROWSER_STORE_BODY_OWNER = "claude_ai_web_chat_browser_cache_not_canonical"
COWORK_LOCAL_AGENT_BODY_OWNER = "claude_desktop_cowork_local_agent_store"
COWORK_RUNTIME_CONSUMER = "claude_desktop_cowork_local_agent"
COWORK_SESSION_METADATA_ARTIFACT = "claude_desktop_cowork_session_metadata_json"
COWORK_SESSIONS_DIR_ARTIFACT = "claude_desktop_cowork_sessions_dir"
COWORK_AUDIT_JSONL_RAW_FORMAT = "claude_desktop_cowork_audit_jsonl"
COWORK_PROJECTS_JSONL_RAW_FORMAT = "claude_desktop_cowork_projects_jsonl"
COWORK_JSONL_RAW_ARTIFACT_ID_SCHEMA = "claude_desktop_cowork_jsonl_raw_artifact_id.v1"
CLAUDE_PROJECTS_JSONL_REFERENCE_CONTRACT = "claude_projects_jsonl_reference.v1"
CLAUDE_PROJECTS_JSONL_RAW_FORMAT = "claude_projects_jsonl_desktop_entrypoint"
CLAUDE_PROJECTS_JSONL_RAW_ARTIFACT_ID_SCHEMA = "claude_projects_jsonl_raw_artifact_id.v1"
LEGACY_LOCAL_RELAY_TOKEN = "cc" + "switch"
LEGACY_LOCAL_RELAY_DASHED = "cc" + "-switch"
LEGACY_LOCAL_RELAY_DISPLAY = "CC" + " Switch"
LEGACY_LOCAL_RELAY_BUNDLE = "com." + LEGACY_LOCAL_RELAY_TOKEN + ".desktop"
LEGACY_LOCAL_RELAY_RAW_FORMAT = f"{LEGACY_LOCAL_RELAY_TOKEN}_claude_provider_projects_jsonl"
CLAUDE_PROJECTS_JSONL_LEGACY_RAW_FORMATS = (
    "local_relay_claude_provider_projects_jsonl",
    LEGACY_LOCAL_RELAY_RAW_FORMAT,
)
CLAUDE_PROJECTS_JSONL_BOUNDARY = "claude_projects_jsonl_reads_claude_projects_jsonl_not_relay_or_proxy_db_chat_body"
RAW_ARCHIVE_SEGMENT_MAX_CHARS = 96
CLAUDE_DESKTOP_INSTALLER_INCLUDES_CLI = False
CLAUDE_CLI_INSTALLATION_BOUNDARY = "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
CLAUDE_DESKTOP_CLI_RELATIONSHIP = "user_installed_cli_independent_but_desktop_may_manage_local_agent_runtime"
CLAUDE_DESKTOP_MANAGED_RUNTIME_CONSUMER = "claude_desktop_managed_claude_code_runtime"
CLAUDE_DESKTOP_MANAGED_RUNTIME_OWNER = "claude_desktop"
CLAUDE_DESKTOP_MANAGED_RUNTIME_POLICY = "desktop_managed_runtime_is_distinct_from_user_installed_path_cli"
CLAUDE_CODE_BODY_STORAGE_OWNER = "claude_code_session_store"
CLAUDE_DESKTOP_CODE_SESSION_POLICY = "metadata_only_links_desktop_session_to_claude_code_jsonl_body"
SENSITIVE_KEY_RE = re.compile(r"(key|token|secret|password|auth|credential|cookie)", re.I)
TEXT_FRAGMENT_RE = re.compile(rb"[\x09\x0a\x0d\x20-\x7e]{8,}")
ROLE_VALUES = {"user", "human", "assistant", "ai", "model", "tool", "system"}
MAX_PARSER_FILE_BYTES = 64 * 1024 * 1024
LIVE_SYNC_ARTIFACT_TYPES = {
    "claude_desktop_app_support_dir",
    "claude_desktop_config_json",
    "claude_desktop_config_json_parse_error",
    COWORK_SESSIONS_DIR_ARTIFACT,
    COWORK_SESSION_METADATA_ARTIFACT,
    COWORK_AUDIT_JSONL_RAW_FORMAT,
    COWORK_PROJECTS_JSONL_RAW_FORMAT,
    "claude_desktop_indexeddb_dir",
    "claude_desktop_indexeddb_leveldb_dir",
    "claude_desktop_indexeddb_blob_dir",
    "claude_desktop_local_storage_leveldb_dir",
    "claude_desktop_session_storage_dir",
    "claude_desktop_logs_dir",
    "claude_desktop_log_file",
    "claude_desktop_preferences_json",
    "claude_desktop_skills_plugin_dir",
    "claude_desktop_skills_manifest_json",
    LOCAL_RELAY_PROXY_DB_ARTIFACT,
}
COWORK_ARTIFACT_TYPES = {
    COWORK_SESSIONS_DIR_ARTIFACT,
    COWORK_SESSION_METADATA_ARTIFACT,
    COWORK_AUDIT_JSONL_RAW_FORMAT,
    COWORK_PROJECTS_JSONL_RAW_FORMAT,
}
COWORK_BODY_ARTIFACT_TYPES = {
    COWORK_AUDIT_JSONL_RAW_FORMAT,
    COWORK_PROJECTS_JSONL_RAW_FORMAT,
}
CHAT_BROWSER_STORE_ARTIFACT_TYPES = {
    "claude_desktop_indexeddb_dir",
    "claude_desktop_indexeddb_leveldb_dir",
    "claude_desktop_indexeddb_blob_dir",
    "claude_desktop_local_storage_leveldb_dir",
    "claude_desktop_session_storage_dir",
}
EXPORT_ARTIFACT_TYPES = {"claude_data_export_candidate"}
RELATED_CLAUDE_CODE_ARTIFACT_TYPES = {
    "claude_code_sessions_dir",
    "claude_code_runtime_bundle",
    "claude_code_vm_bundle",
}
PARSER_ARTIFACT_TYPES = {
    "claude_desktop_indexeddb_leveldb_dir",
    "claude_desktop_indexeddb_blob_dir",
    "claude_desktop_local_storage_leveldb_dir",
    "claude_desktop_session_storage_dir",
}
PARSER_FILE_SUFFIXES = {
    ".log",
    ".ldb",
    ".sst",
    ".json",
    ".jsonl",
    ".txt",
}
RELATED_CLAUDE_CODE_ATTRIBUTION = {
    "claude_code_sessions_dir": {
        "conversation_origin": "claude_desktop_managed_claude_code_session",
        "runtime_consumer": CLAUDE_DESKTOP_MANAGED_RUNTIME_CONSUMER,
        "artifact_role": "desktop_managed_code_session_metadata_store",
        "body_storage_owner": CLAUDE_CODE_BODY_STORAGE_OWNER,
        "desktop_managed_runtime_detected": True,
    },
    "claude_code_runtime_bundle": {
        "conversation_origin": "not_conversation_memory",
        "runtime_consumer": CLAUDE_DESKTOP_MANAGED_RUNTIME_CONSUMER,
        "artifact_role": "desktop_managed_runtime_bundle",
        "body_storage_owner": "not_conversation_memory",
        "desktop_managed_runtime_detected": True,
    },
    "claude_code_vm_bundle": {
        "conversation_origin": "not_conversation_memory",
        "runtime_consumer": "claude_code_vm",
        "artifact_role": "runtime_vm_bundle",
        "body_storage_owner": "not_conversation_memory",
        "desktop_managed_runtime_detected": True,
    },
}
LOCAL_RELAY_CLAUDE_DESKTOP_APP_TYPES = ("claude-desktop", "claude_desktop", "claudedesktop")
SKIP_DIR_NAMES = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "blob_storage",
    "vm_bundles",
    "claude-code",
    "claude-code-vm",
    "Partitions",
}
CONFIG_KEYS_TO_REPORT = (
    "mcpServers",
    "preferences",
    "coworkUserFilesPath",
    "desktopExtensions",
    "extensions",
)


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _platform_key() -> str:
    override = os.environ.get("MEMCORE_PLATFORM", "").strip().lower()
    if override in {"windows", "win32"}:
        return "win32"
    if override in {"darwin", "mac", "macos"}:
        return "darwin"
    if override == "linux":
        return "linux"
    if os.name == "nt" or sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _path_from_env(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def default_claude_home_candidates() -> list[Path]:
    override = _path_from_env("CLAUDE_DESKTOP_HOME")
    if override:
        return [override]

    platform = _platform_key()
    home = Path.home()
    candidates: list[Path] = []
    if platform == "darwin":
        candidates.append(home / "Library" / "Application Support" / "Claude")
    elif platform == "win32":
        for env_name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE"):
            root = os.environ.get(env_name, "").strip()
            if not root:
                continue
            base = Path(root)
            if env_name == "USERPROFILE":
                candidates.extend([
                    base / "AppData" / "Roaming" / "Claude",
                    base / "AppData" / "Local" / "Claude",
                ])
            else:
                candidates.append(base / "Claude")
                if env_name == "LOCALAPPDATA":
                    try:
                        for local_dir in base.glob("Claude-*"):
                            candidates.append(local_dir)
                    except OSError:
                        pass
                    packages = base / "Packages"
                    candidates.append(packages / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude")
                    try:
                        for package_dir in packages.glob("Claude_*"):
                            candidates.append(package_dir / "LocalCache" / "Roaming" / "Claude")
                    except OSError:
                        pass
    else:
        candidates.extend([
            home / ".config" / "Claude",
            home / ".config" / "claude",
        ])

    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def resolve_claude_home() -> Path:
    candidates = default_claude_home_candidates()
    evidence_rels = (
        Path("IndexedDB"),
        Path("Local Storage") / "leveldb",
        Path("Session Storage"),
        Path("local-agent-mode-sessions") / "skills-plugin",
        Path("logs"),
        Path("Preferences"),
    )

    def score(path: Path) -> int:
        if not path.exists():
            return 0
        value = 1
        if (path / "claude_desktop_config.json").exists():
            value += 4
        for rel in evidence_rels:
            if (path / rel).exists():
                value += 12
        return value

    scored = [(score(path), index, path) for index, path in enumerate(candidates)]
    best_score, _, best_path = max(scored, key=lambda item: (item[0], -item[1]))
    if best_score:
        return best_path
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def claude_config_path(home: Path | None = None) -> Path:
    root = home or resolve_claude_home()
    return root / "claude_desktop_config.json"


def _public_path_label(path: str | Path) -> str:
    text = str(path or "")
    if not text:
        return ""
    try:
        p = Path(text).expanduser()
        resolved = p.resolve()
        home = Path.home().resolve()
        try:
            rel = resolved.relative_to(home)
            return "~/" + str(rel)
        except ValueError:
            return str(p)
    except Exception:
        return text


def _public_relay_proxy_summary(summary: dict[str, Any]) -> dict[str, Any]:
    result = dict(summary or {})
    if "db_path" in result:
        result["db_path"] = "local_relay_proxy_request_logs_db"
    if "db_path_public" in result:
        result["db_path_public"] = "local_relay_proxy_request_logs_db"
    return result


def _computer_name() -> str:
    if os.environ.get("COMPUTERNAME"):
        return os.environ["COMPUTERNAME"]
    if hasattr(os, "uname"):
        try:
            return os.uname().nodename
        except Exception:
            return ""
    return ""


def _memcore_root() -> Path:
    return Path(os.environ.get("MEMCORE_ROOT") or Path(__file__).resolve().parents[1])


def local_relay_home_candidates() -> list[Path]:
    """Return likely local relay app-config homes without writing anything."""
    explicit = None
    for env_name in (
        "LOCAL_RELAY_HOME",
        "LOCAL_RELAY_ROOT",
        "CC" + "_SWITCH_HOME",
        "CC" + "SWITCH_HOME",
    ):
        explicit = _path_from_env(env_name)
        if explicit:
            break
    if explicit:
        return [explicit]
    platform = _platform_key()
    home = Path.home()
    candidates = [home / ".local-relay"]
    if platform == "win32":
        for env_name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE"):
            root = os.environ.get(env_name, "").strip()
            if not root:
                continue
            base = Path(root)
            if env_name == "USERPROFILE":
                candidates.append(base / ".local-relay")
                candidates.append(base / f".{LEGACY_LOCAL_RELAY_DASHED}")
            else:
                candidates.extend([
                    base / "local-relay",
                    base / "Local Relay",
                    base / "com.localrelay.desktop",
                    base / LEGACY_LOCAL_RELAY_DASHED,
                    base / LEGACY_LOCAL_RELAY_DISPLAY,
                    base / LEGACY_LOCAL_RELAY_BUNDLE,
                ])
    elif platform == "darwin":
        candidates.extend([
            home / "Library" / "Application Support" / "local-relay",
            home / "Library" / "Application Support" / "Local Relay",
            home / "Library" / "Application Support" / "com.localrelay.desktop",
            home / "Library" / "Application Support" / LEGACY_LOCAL_RELAY_DASHED,
            home / "Library" / "Application Support" / LEGACY_LOCAL_RELAY_DISPLAY,
            home / "Library" / "Application Support" / LEGACY_LOCAL_RELAY_BUNDLE,
        ])
    else:
        candidates.extend([
            home / ".config" / "local-relay",
            home / ".local" / "share" / "local-relay",
            home / ".config" / LEGACY_LOCAL_RELAY_DASHED,
            home / ".local" / "share" / LEGACY_LOCAL_RELAY_DASHED,
        ])
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def local_relay_db_candidates() -> list[Path]:
    explicit = None
    for env_name in (
        "LOCAL_RELAY_DB",
        "LOCAL_RELAY_DATABASE",
        "CC" + "_SWITCH_DB",
        "CC" + "SWITCH_DB",
    ):
        explicit = _path_from_env(env_name)
        if explicit:
            break
    if explicit:
        return [explicit]
    candidates: list[Path] = []
    for root in local_relay_home_candidates():
        candidates.append(root / "local-relay.db")
        candidates.append(root / f"{LEGACY_LOCAL_RELAY_DASHED}.db")
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def resolve_local_relay_db_path() -> Path | None:
    for candidate in local_relay_db_candidates():
        if candidate.exists():
            return candidate
    return None


def _local_relay_proxy_request_logs_summary(db_path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "db_path": str(db_path),
        "db_path_public": _public_path_label(db_path),
        "table_exists": False,
        "app_type_filter": list(LOCAL_RELAY_CLAUDE_DESKTOP_APP_TYPES),
        "request_count": 0,
        "success_count": 0,
        "error_count": 0,
        "latest_created_at_epoch": 0,
        "latest_created_at": "",
        "latest_model": "",
        "latest_request_model": "",
        "latest_status_code": None,
        "latest_session_id": "",
        "latest_data_source": "",
        "message_text_returned": False,
        "raw_excerpt_returned": False,
        "read_only_probe": True,
        "write_performed": False,
    }
    if not db_path.exists():
        return summary
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}:{str(exc)[:160]}"
        return summary
    try:
        exists = conn.execute(
            "select count(*) from sqlite_master where type='table' and name='proxy_request_logs'"
        ).fetchone()[0]
        summary["table_exists"] = bool(exists)
        if not exists:
            return summary
        placeholders = ",".join("?" for _ in LOCAL_RELAY_CLAUDE_DESKTOP_APP_TYPES)
        total = conn.execute(
            f"select count(*) from proxy_request_logs where app_type in ({placeholders})",
            LOCAL_RELAY_CLAUDE_DESKTOP_APP_TYPES,
        ).fetchone()[0]
        success = conn.execute(
            f"select count(*) from proxy_request_logs where app_type in ({placeholders}) and status_code between 200 and 299",
            LOCAL_RELAY_CLAUDE_DESKTOP_APP_TYPES,
        ).fetchone()[0]
        latest = conn.execute(
            f"""
            select created_at, model, request_model, status_code, session_id, data_source
            from proxy_request_logs
            where app_type in ({placeholders})
            order by created_at desc
            limit 1
            """,
            LOCAL_RELAY_CLAUDE_DESKTOP_APP_TYPES,
        ).fetchone()
        summary["request_count"] = int(total or 0)
        summary["success_count"] = int(success or 0)
        summary["error_count"] = max(0, int(total or 0) - int(success or 0))
        if latest:
            created_at, model, request_model, status_code, session_id, data_source = latest
            try:
                epoch = int(created_at or 0)
            except Exception:
                epoch = 0
            summary["latest_created_at_epoch"] = epoch
            summary["latest_created_at"] = (
                datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                if epoch > 0
                else ""
            )
            summary["latest_model"] = str(model or "")
            summary["latest_request_model"] = str(request_model or "")
            summary["latest_status_code"] = int(status_code) if status_code is not None else None
            summary["latest_session_id"] = str(session_id or "")
            summary["latest_data_source"] = str(data_source or "")
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}:{str(exc)[:160]}"
    finally:
        conn.close()
    return summary


def claude_projects_jsonl_reference(limit: int = 20, public: bool = True) -> dict[str, Any]:
    """Expose Claude's own projects JSONL source as Desktop-entrypoint evidence.

    A local relay tool helped confirm the path in development, but it is not a
    required user dependency and relay metadata is not the transcript store.
    """
    try:
        import claude_code_local_connector as claude_code
    except Exception as exc:
        return {
            "ok": False,
            "contract": CLAUDE_PROJECTS_JSONL_REFERENCE_CONTRACT,
            "source_system": SOURCE_SYSTEM,
            "reference": CLAUDE_PROJECTS_JSONL_RAW_FORMAT,
            "error": f"{type(exc).__name__}:{str(exc)[:160]}",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }

    try:
        artifacts = claude_code.discover_sessions(limit=max(1, min(int(limit or 20), 200)))
    except Exception as exc:
        artifacts = []
        error = f"{type(exc).__name__}:{str(exc)[:160]}"
    else:
        error = ""

    desktop_linked = [
        item for item in artifacts
        if item.get("desktop_entrypoint_detected")
        or item.get("desktop_session_metadata_detected")
        or "claude_desktop" in (item.get("co_source_systems") or [])
        or str(item.get("conversation_origin") or "").startswith("claude_desktop")
    ]
    complete = [
        item for item in desktop_linked
        if item.get("complete_conversation_candidate")
    ]
    latest = [
        {
            "session_id": item.get("session_id", ""),
            "source_path": _public_path_label(item.get("source_path", "")) if public else item.get("source_path", ""),
            "project_id": item.get("project_id", ""),
            "project_root": _public_path_label(item.get("project_root", "")) if public else item.get("project_root", ""),
            "thread_name": item.get("thread_name", ""),
            "mtime": item.get("mtime", ""),
            "complete_conversation_candidate": bool(item.get("complete_conversation_candidate")),
            "user_message_count": int(item.get("user_message_count", 0) or 0),
            "assistant_message_count": int(item.get("assistant_message_count", 0) or 0),
            "conversation_origin": item.get("conversation_origin", ""),
            "runtime_consumer": item.get("runtime_consumer", ""),
            "desktop_entrypoint_detected": bool(item.get("desktop_entrypoint_detected")),
            "desktop_session_metadata_detected": bool(item.get("desktop_session_metadata_detected")),
            "body_storage_owner": item.get("body_storage_owner", ""),
        }
        for item in desktop_linked[: min(5, len(desktop_linked))]
    ]
    local_relay_db = resolve_local_relay_db_path()
    return {
        "ok": not error,
        "contract": CLAUDE_PROJECTS_JSONL_REFERENCE_CONTRACT,
        "source_system": SOURCE_SYSTEM,
        "reference": CLAUDE_PROJECTS_JSONL_RAW_FORMAT,
        "development_reference": "none",
        "development_reference_only": True,
        "development_reference_is_required_dependency": False,
        "implementation_observed": "claude_projects_jsonl_parser_shape",
        "provider_id": "claude",
        "provider_source_root": _public_path_label(claude_code.claude_code_projects_root()) if public else str(claude_code.claude_code_projects_root()),
        "provider_source_glob": "projects/**/*.jsonl",
        "message_parser": "line_json.message.role_and_message.content",
        "body_storage_owner": "claude_code_session_store",
        "conversation_origin_filter": "claude_desktop_entrypoint_or_desktop_managed_claude_code_session",
        "boundary": CLAUDE_PROJECTS_JSONL_BOUNDARY,
        "relay_db_detected": bool(local_relay_db),
        "relay_db_path": "" if public else (str(local_relay_db) if local_relay_db else ""),
        "relay_db_is_transcript_store": False,
        "desktop_linked_session_count": len(desktop_linked),
        "desktop_linked_complete_conversation_count": len(complete),
        "desktop_linked_assistant_reply_persistence": "verified" if complete else "unverified",
        "ordinary_desktop_browser_store_claimed_complete": False,
        "latest_desktop_linked": latest,
        "error": error,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "notes": [
            "This follows Claude's own projects JSONL as the source path.",
            "It proves Desktop-entrypoint or Desktop-managed Claude Code JSONL body capture when those artifacts exist.",
            "It does not prove ordinary claude.ai web Chat browser-cache transcript capture.",
            "In Claude Desktop Code mode, the desktop session metadata maps the current window to the projects JSONL body file.",
        ],
    }


def local_relay_session_manager_reference(limit: int = 20, public: bool = True) -> dict[str, Any]:
    """Backward-compatible alias; public callers should use Claude projects naming."""
    return claude_projects_jsonl_reference(limit=limit, public=public)


def _memory_root() -> Path:
    env_root = os.environ.get("MEMCORE_ROOT")
    if env_root:
        return Path(env_root).expanduser() / "memory"
    try:
        from src.config_loader import memory_root
    except ImportError:
        try:
            from config_loader import memory_root
        except ImportError:
            memory_root = None
    if memory_root:
        try:
            return Path(memory_root()).expanduser()
        except Exception:
            pass
    return _memcore_root() / "memory"


def _sync_state_path() -> Path:
    override = _path_from_env("CLAUDE_DESKTOP_SYNC_STATE")
    if override:
        return override
    return _memcore_root() / "output" / "source_systems" / SOURCE_SYSTEM / "sync_state.json"


def _load_sync_state() -> dict[str, Any]:
    path = _sync_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_sync_state(state: dict[str, Any]) -> Path:
    path = _sync_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _sha256_small(path: Path, max_bytes: int = 20 * 1024 * 1024) -> str:
    try:
        if path.stat().st_size > max_bytes:
            return f"sha256_skipped_large_file:{path.stat().st_size}"
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                result[key] = "<redacted>"
            else:
                result[key] = _redact(child)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def load_config(home: Path | None = None) -> dict[str, Any]:
    path = claude_config_path(home)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_config_result(home: Path | None = None) -> tuple[dict[str, Any], str]:
    path = claude_config_path(home)
    if not path.exists():
        return {}, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}, "ok"
    except Exception as exc:
        return {}, f"parse_error:{type(exc).__name__}"


def config_summary(config: dict[str, Any]) -> dict[str, Any]:
    mcp_servers = config.get("mcpServers") if isinstance(config.get("mcpServers"), dict) else {}
    server_names = sorted(str(name) for name in mcp_servers.keys())
    server_text = json.dumps(_redact(mcp_servers), ensure_ascii=False)
    yifanchen_names = [
        name for name in server_names
        if "yifanchen" in name.lower()
        or "zhiyi" in name.lower()
        or "9851" in server_text
    ]
    prefs = config.get("preferences") if isinstance(config.get("preferences"), dict) else {}
    return {
        "has_config": bool(config),
        "has_mcp_servers": bool(server_names),
        "mcp_server_names": server_names,
        "yifanchen_mcp_detected": bool(yifanchen_names),
        "yifanchen_mcp_server_names": yifanchen_names,
        "cowork_user_files_path": prefs.get("coworkUserFilesPath") or config.get("coworkUserFilesPath") or "",
        "desktop_extensions_possible": True,
        "redacted_config": _redact(config),
        "reported_keys": [key for key in CONFIG_KEYS_TO_REPORT if key in config],
    }


def _manifest_skill_matches(item: dict[str, Any]) -> bool:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("skillId", "id", "name", "description")
    ).lower()
    return any(needle in haystack for needle in ("yifanchen", "zhiyi", "memcore", "忆凡尘", "知意"))


def _skills_plugin_roots(home: Path | None = None) -> list[Path]:
    root = home or resolve_claude_home()
    base = root / "local-agent-mode-sessions" / "skills-plugin"
    if not base.exists():
        return []
    roots: list[Path] = []
    try:
        for manifest in base.glob("*/*/manifest.json"):
            plugin_root = manifest.parent
            if plugin_root not in roots:
                roots.append(plugin_root)
    except OSError:
        pass
    return roots


def discover_skills(home: Path | None = None, limit: int = 50) -> dict[str, Any]:
    roots = _skills_plugin_roots(home)
    plugin_items: list[dict[str, Any]] = []
    skills: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    for plugin_root in roots[:limit]:
        manifest_path = plugin_root / "manifest.json"
        manifest: dict[str, Any] = {}
        parse_ok = False
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            parse_ok = isinstance(manifest, dict)
        except Exception as exc:
            parse_errors.append({
                "path": str(manifest_path),
                "error": f"{type(exc).__name__}:{str(exc)[:120]}",
            })
        raw_skills = manifest.get("skills") if isinstance(manifest.get("skills"), list) else []
        plugin_items.append({
            "plugin_root": str(plugin_root),
            "manifest_path": str(manifest_path),
            "parse_ok": parse_ok,
            "skill_count": len(raw_skills),
            "skill_ids": [
                str(item.get("skillId") or item.get("id") or item.get("name") or "")
                for item in raw_skills
                if isinstance(item, dict)
            ][:limit],
        })
        for item in raw_skills:
            if not isinstance(item, dict):
                continue
            skill_id = str(item.get("skillId") or item.get("id") or item.get("name") or "")
            skill_path = plugin_root / "skills" / skill_id
            skills.append({
                "skill_id": skill_id,
                "name": str(item.get("name") or skill_id),
                "description": str(item.get("description") or "")[:500],
                "enabled": bool(item.get("enabled", True)),
                "creator_type": str(item.get("creatorType") or ""),
                "updated_at": item.get("updatedAt"),
                "skill_path": str(skill_path),
                "skill_path_exists": skill_path.exists(),
                "looks_like_yifanchen": _manifest_skill_matches(item),
            })
    yifanchen_skills = [item for item in skills if item.get("looks_like_yifanchen")]
    return {
        "plugins_detected": len(plugin_items),
        "skills_detected": len(skills),
        "skill_ids": [item.get("skill_id", "") for item in skills][:limit],
        "yifanchen_skill_detected": bool(yifanchen_skills),
        "yifanchen_skill_ids": [item.get("skill_id", "") for item in yifanchen_skills],
        "plugins": plugin_items,
        "skills": skills[:limit],
        "parse_errors": parse_errors,
        "read_only_probe": True,
        "write_performed": False,
    }


def _public_skills_summary(summary: dict[str, Any]) -> dict[str, Any]:
    result = dict(summary)
    result["plugins"] = [
        {
            **item,
            "plugin_root": _public_path_label(item.get("plugin_root", "")),
            "manifest_path": _public_path_label(item.get("manifest_path", "")),
        }
        for item in result.get("plugins", [])
        if isinstance(item, dict)
    ]
    result["skills"] = [
        {
            **item,
            "skill_path": _public_path_label(item.get("skill_path", "")),
        }
        for item in result.get("skills", [])
        if isinstance(item, dict)
    ]
    return result


def consumer_status(config: dict[str, Any] | None = None, home: Path | None = None) -> dict[str, Any]:
    root = home or resolve_claude_home()
    config = config if isinstance(config, dict) else load_config(root)
    cfg = config_summary(config)
    skills = discover_skills(root)
    mcp_detected = bool(cfg.get("yifanchen_mcp_detected"))
    skill_detected = bool(skills.get("yifanchen_skill_detected"))
    if mcp_detected:
        readiness = "ready_with_mcp"
        likely_rejection_reason = ""
    elif skill_detected:
        readiness = "skill_signal_without_tool_connection"
        likely_rejection_reason = "Claude can see Yifanchen instructions, but no Yifanchen MCP/Desktop Extension tool is detected for actual recall."
    else:
        readiness = "not_connected"
        likely_rejection_reason = "No Yifanchen MCP/Desktop Extension or Yifanchen skill signal detected in Claude Desktop local data."
    return {
        "consumer": SOURCE_SYSTEM,
        "mcp_detected": mcp_detected,
        "mcp_server_names": cfg.get("yifanchen_mcp_server_names", []),
        "skill_detected": skill_detected,
        "skill_ids": skills.get("yifanchen_skill_ids", []),
        "skills_summary": _public_skills_summary(skills),
        "recall_connection_ready": mcp_detected,
        "readiness": readiness,
        "likely_rejection_reason": likely_rejection_reason,
        "read_only_probe": True,
        "write_performed": False,
        "platform_write_performed": False,
    }


def _file_artifact(path: Path, artifact_type: str, classification: str = "EXTERNAL", **extra: Any) -> dict[str, Any]:
    stat = path.stat()
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": artifact_type,
        "source_path": str(path),
        "filename": path.name,
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 3),
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": _sha256_small(path),
        "capture_classification": classification,
        "read_only_probe": True,
        "write_performed": False,
        "sync_strategy": "metadata_probe",
        **extra,
    }


def _dir_artifact(path: Path, artifact_type: str, classification: str = "EXTERNAL", **extra: Any) -> dict[str, Any]:
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": artifact_type,
        "source_path": str(path),
        "filename": path.name,
        "exists": path.exists(),
        "capture_classification": classification,
        "read_only_probe": True,
        "content_read_supported_now": False,
        "write_performed": False,
        "sync_strategy": "metadata_probe",
        **extra,
    }


def _millis_to_iso(value: Any) -> str:
    try:
        millis = float(value)
    except Exception:
        return ""
    if millis <= 0:
        return ""
    return datetime.fromtimestamp(millis / 1000.0, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cowork_sessions_root(home: Path | None = None) -> Path:
    root = home or resolve_claude_home()
    override = _path_from_env("CLAUDE_DESKTOP_COWORK_SESSIONS_DIR")
    return override if override else root / "local-agent-mode-sessions"


def _safe_json_load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _cowork_metadata_for_json(meta_path: Path) -> dict[str, Any]:
    data = _safe_json_load(meta_path)
    session_id = str(data.get("sessionId") or meta_path.stem)
    cli_session_id = str(data.get("cliSessionId") or "")
    session_dir = meta_path.with_suffix("")
    return {
        "source_system": SOURCE_SYSTEM,
        "source_surface": SURFACE_COWORK,
        "artifact_type": COWORK_SESSION_METADATA_ARTIFACT,
        "source_path": str(meta_path),
        "filename": meta_path.name,
        "desktop_session_id": session_id,
        "session_id": _safe_session_id(session_id),
        "cli_session_id": cli_session_id,
        "session_dir": str(session_dir),
        "title": str(data.get("title") or ""),
        "initial_message_present": bool(str(data.get("initialMessage") or "").strip()),
        "model": str(data.get("model") or ""),
        "process_name": str(data.get("processName") or ""),
        "cwd": str(data.get("cwd") or ""),
        "created_at": _millis_to_iso(data.get("createdAt")),
        "last_activity_at": _millis_to_iso(data.get("lastActivityAt")),
        "metadata_only": True,
        "message_text_returned": False,
        "raw_excerpt_returned": False,
        "complete_conversation_candidate": False,
        "read_only_probe": True,
    }


def discover_cowork_sessions(home: Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    root = _cowork_sessions_root(home)
    if not root.exists():
        return []
    try:
        files = [p for p in root.glob("*/*/local_*.json") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    sessions: list[dict[str, Any]] = []
    for path in files[: max(1, min(int(limit or 50), 500))]:
        sessions.append(_cowork_metadata_for_json(path))
    return sessions


def _cowork_jsonl_message_counts(path: Path, line_limit: int = 2000) -> dict[str, Any]:
    counts = {
        "user_message_count": 0,
        "assistant_message_count": 0,
        "tool_result_message_count": 0,
        "content_message_count": 0,
        "line_count_sample": 0,
        "parse_errors": 0,
        "roles": set(),
        "session_id": "",
        "entrypoint_counts": {},
        "first_user_message": "",
    }
    def norm_role(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text == "human":
            return "user"
        if text in {"ai", "model"}:
            return "assistant"
        return text if text in ROLE_VALUES else "unknown"

    def text_from(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return "\n".join(part for part in (text_from(item) for item in value) if part).strip()
        if isinstance(value, dict):
            for key in ("text", "content", "message", "value"):
                if key in value:
                    text = text_from(value.get(key))
                    if text:
                        return text
        return str(value).strip()

    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for index, line in enumerate(handle):
                if index >= line_limit:
                    break
                line = line.strip()
                if not line:
                    continue
                counts["line_count_sample"] += 1
                try:
                    record = json.loads(line)
                except Exception:
                    counts["parse_errors"] += 1
                    continue
                if not counts["session_id"]:
                    counts["session_id"] = str(record.get("sessionId") or record.get("session_id") or "")
                entrypoint = str(record.get("entrypoint") or "").strip().lower()
                if entrypoint:
                    entry_counts = counts["entrypoint_counts"]
                    entry_counts[entrypoint] = int(entry_counts.get(entrypoint, 0) or 0) + 1
                message = record.get("message")
                if not isinstance(message, dict):
                    continue
                role = norm_role(message.get("role") or record.get("type"))
                text = text_from(message.get("content"))
                if role == "user" and not counts["first_user_message"] and text:
                    counts["first_user_message"] = text
                if role == "user":
                    counts["user_message_count"] += 1
                elif role == "assistant":
                    counts["assistant_message_count"] += 1
                elif role == "tool":
                    counts["tool_result_message_count"] += 1
                else:
                    continue
                counts["roles"].add(role)
                if text.strip():
                    counts["content_message_count"] += 1
    except OSError:
        pass
    return {
        **counts,
        "roles": sorted(counts["roles"]),
    }


def _cowork_body_artifact(
    path: Path,
    artifact_type: str,
    session_meta: dict[str, Any],
    *,
    discovered_at: str,
) -> dict[str, Any]:
    counts = _cowork_jsonl_message_counts(path)
    native_session_id = str(counts.get("session_id") or session_meta.get("cli_session_id") or path.stem)
    desktop_session_id = str(session_meta.get("desktop_session_id") or "")
    complete = bool(counts.get("user_message_count") and counts.get("assistant_message_count"))
    return _file_artifact(
        path,
        artifact_type,
        "SHADOW",
        discovered_at=discovered_at,
        content_read_supported_now="native_jsonl_mirror",
        sync_strategy="cowork_local_agent_jsonl_mirror",
        sync_role="primary",
        source_surface=SURFACE_COWORK,
        desktop_session_id=desktop_session_id,
        session_id=_safe_session_id(native_session_id),
        canonical_window_id=_safe_session_id(desktop_session_id or native_session_id),
        title=str(session_meta.get("title") or ""),
        model=str(session_meta.get("model") or ""),
        session_metadata_path=session_meta.get("source_path", ""),
        session_dir=session_meta.get("session_dir", ""),
        user_message_count=int(counts.get("user_message_count") or 0),
        assistant_message_count=int(counts.get("assistant_message_count") or 0),
        tool_result_message_count=int(counts.get("tool_result_message_count") or 0),
        content_message_count=int(counts.get("content_message_count") or 0),
        roles=counts.get("roles", []),
        complete_conversation_candidate=complete,
        assistant_reply_persistence="verified" if complete else "unverified",
        entrypoint_counts=counts.get("entrypoint_counts", {}),
        first_user_message_preview=_truncate_public(counts.get("first_user_message", ""), 80),
        note="Claude Desktop Cowork local-agent JSONL body evidence. Mirrored only after explicit raw-ingest authorization.",
    )


def _truncate_public(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _cowork_body_artifacts(home: Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    discovered_at = ts()
    artifacts: list[dict[str, Any]] = []
    for session_meta in discover_cowork_sessions(home, limit=limit):
        session_dir_text = str(session_meta.get("session_dir") or "")
        session_dir = Path(session_dir_text)
        if not session_dir.exists():
            continue
        audit_path = session_dir / "audit.jsonl"
        if audit_path.exists():
            artifacts.append(_cowork_body_artifact(
                audit_path,
                COWORK_AUDIT_JSONL_RAW_FORMAT,
                session_meta,
                discovered_at=discovered_at,
            ))
        try:
            project_jsonls = [p for p in (session_dir / ".claude" / "projects").rglob("*.jsonl") if p.is_file()]
            project_jsonls.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            project_jsonls = []
        for path in project_jsonls[: max(1, min(int(limit or 50), 500))]:
            artifacts.append(_cowork_body_artifact(
                path,
                COWORK_PROJECTS_JSONL_RAW_FORMAT,
                session_meta,
                discovered_at=discovered_at,
            ))
    return artifacts


def attribution_from_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    artifact_type = str(artifact.get("artifact_type") or "")
    sync_role = str(artifact.get("sync_role") or "")
    collection = {
        "source_family": "claude",
        "source_collection": "claude_all",
        "collection_label": "Claude",
        "collection_mode": "aggregate_all_claude_surfaces_preserve_attribution",
        "collection_does_not_imply_shared_platform_memory": True,
    }
    if artifact_type in COWORK_ARTIFACT_TYPES:
        is_body = artifact_type in COWORK_BODY_ARTIFACT_TYPES
        return {
            **collection,
            "attribution_mode": "single",
            "source_surface": SURFACE_COWORK,
            "source_systems": [SOURCE_SYSTEM],
            "co_source_systems": [],
            "storage_owner": SOURCE_SYSTEM,
            "body_storage_owner": COWORK_LOCAL_AGENT_BODY_OWNER if is_body else "not_conversation_memory",
            "conversation_origin": SURFACE_COWORK if is_body else "not_conversation_memory",
            "runtime_consumer": COWORK_RUNTIME_CONSUMER,
            "relay_owner": "",
            "artifact_role": "cowork_local_agent_body" if is_body else "cowork_session_metadata",
            "visibility_boundary": "cowork_local_agent_surface",
            "cross_surface_memory_shared": False,
            "official_relay_interop": False,
            "surface_readability": {
                "complete_conversation_body": bool(artifact.get("complete_conversation_candidate")) if is_body else False,
                "metadata_only": not is_body,
                "message_text_returned": False,
                "raw_excerpt_returned": False,
            },
            "attribution_chain": [
                {
                    "role": "storage_owner",
                    "source_system": SOURCE_SYSTEM,
                    "evidence": "local-agent-mode-sessions",
                },
                {
                    "role": "source_surface",
                    "source_system": SURFACE_COWORK,
                    "evidence": artifact_type,
                },
            ],
            "boundary_note": (
                "Cowork local-agent records live under Claude Desktop app data, but are not ordinary Chat IndexedDB records and are not user PATH Claude Code CLI records."
            ),
        }
    if artifact_type in CHAT_BROWSER_STORE_ARTIFACT_TYPES:
        return {
            **collection,
            "attribution_mode": "single",
            "source_surface": SURFACE_CHAT,
            "source_systems": [SOURCE_SYSTEM],
            "co_source_systems": [],
            "storage_owner": SOURCE_SYSTEM,
            "body_storage_owner": CHAT_BROWSER_STORE_BODY_OWNER,
            "conversation_origin": SURFACE_CHAT,
            "runtime_consumer": SOURCE_SYSTEM,
            "relay_owner": "",
            "artifact_role": "chat_browser_store",
            "visibility_boundary": "ordinary_chat_browser_store_parser_gated",
            "cross_surface_memory_shared": False,
            "official_relay_interop": False,
            "surface_readability": {
                "complete_conversation_body": False,
                "parser_gate_required": True,
                "canonical_store_is_cloud": True,
                "desktop_store_is_cache": True,
                "message_text_returned": False,
                "raw_excerpt_returned": False,
            },
            "attribution_chain": [
                {
                    "role": "source_surface",
                    "source_system": SURFACE_CHAT,
                    "evidence": artifact_type,
                }
            ],
            "boundary_note": (
                "Chat mode is a claude.ai web-chat surface inside the desktop shell. Local IndexedDB/blob files are cache/evidence, not the canonical save path; do not treat Code/Cowork JSONL success as Chat transcript capture."
            ),
        }
    if artifact_type in RELATED_CLAUDE_CODE_ARTIFACT_TYPES:
        related = RELATED_CLAUDE_CODE_ATTRIBUTION.get(artifact_type, {})
        conversation_origin = str(related.get("conversation_origin") or "claude_code_cli")
        runtime_consumer = str(related.get("runtime_consumer") or "claude_code_cli")
        body_storage_owner = str(related.get("body_storage_owner") or CLAUDE_CODE_BODY_STORAGE_OWNER)
        desktop_managed_runtime_detected = bool(related.get("desktop_managed_runtime_detected"))
        return {
            **collection,
            "attribution_mode": "dual",
            "source_surface": SURFACE_CODE_OR_AGENT,
            "source_systems": [SOURCE_SYSTEM, "claude_code_cli"],
            "co_source_systems": ["claude_code_cli", "claude_desktop_managed_local_agent"],
            "storage_owner": SOURCE_SYSTEM,
            "body_storage_owner": body_storage_owner,
            "conversation_origin": conversation_origin,
            "runtime_consumer": runtime_consumer,
            "desktop_installer_includes_cli": CLAUDE_DESKTOP_INSTALLER_INCLUDES_CLI,
            "cli_installation_boundary": CLAUDE_CLI_INSTALLATION_BOUNDARY,
            "desktop_cli_relationship": CLAUDE_DESKTOP_CLI_RELATIONSHIP,
            "user_installed_cli_independent": True,
            "user_installed_path_cli_required": False,
            "desktop_managed_runtime_detected": desktop_managed_runtime_detected,
            "desktop_managed_runtime_owner": CLAUDE_DESKTOP_MANAGED_RUNTIME_OWNER if desktop_managed_runtime_detected else "",
            "desktop_managed_runtime_policy": CLAUDE_DESKTOP_MANAGED_RUNTIME_POLICY if desktop_managed_runtime_detected else "",
            "desktop_managed_runtime_is_user_installed_cli": False if desktop_managed_runtime_detected else None,
            "desktop_metadata_is_conversation_body": False,
            "desktop_code_session_policy": CLAUDE_DESKTOP_CODE_SESSION_POLICY,
            "relay_owner": "claude_desktop_managed_local_agent",
            "artifact_role": related.get("artifact_role") or sync_role or "related_artifact",
            "visibility_boundary": "isolated_surfaces",
            "cross_surface_memory_shared": False,
            "official_relay_interop": False,
            "surface_readability": {
                "desktop_metadata_is_conversation_body": False,
                "desktop_managed_runtime_is_user_installed_cli": False if desktop_managed_runtime_detected else None,
                "ordinary_claude_desktop_chat_store_is_separate": True,
            },
            "attribution_chain": [
                {
                    "role": "storage_owner",
                    "source_system": SOURCE_SYSTEM,
                    "evidence": "artifact_discovered_under_claude_desktop_home",
                },
                {
                    "role": "conversation_origin",
                    "source_system": conversation_origin,
                    "evidence": artifact_type,
                },
                {
                    "role": "desktop_managed_local_agent",
                    "source_system": "claude_desktop_managed_local_agent",
                    "evidence": "claude_desktop_related_claude_code_artifact",
                },
            ],
            "attribution_note": (
                "Claude Desktop can manage a local Claude Code runtime and session metadata under its app data. "
                "Yifanchen keeps storage ownership and conversation/runtime ownership separate."
            ),
            "boundary_note": (
                "Dual attribution is lineage evidence only. Claude Desktop metadata is not the chat body, and a Desktop-managed runtime is not a user-installed PATH CLI."
            ),
        }
    if sync_role == "consumer_capability":
        return {
            **collection,
            "attribution_mode": "single",
            "source_surface": "claude_desktop_consumer_capability",
            "source_systems": [SOURCE_SYSTEM],
            "co_source_systems": [],
            "storage_owner": SOURCE_SYSTEM,
            "body_storage_owner": "not_conversation_memory",
            "conversation_origin": "not_conversation_memory",
            "runtime_consumer": SOURCE_SYSTEM,
            "relay_owner": "",
            "artifact_role": "consumer_capability",
            "visibility_boundary": "not_conversation_memory",
            "cross_surface_memory_shared": False,
            "official_relay_interop": False,
            "surface_readability": {},
            "attribution_chain": [
                {
                    "role": "consumer_capability",
                    "source_system": SOURCE_SYSTEM,
                    "evidence": artifact_type,
                }
            ],
        }
    if artifact_type == LOCAL_RELAY_PROXY_DB_ARTIFACT:
        return {
            **collection,
            "attribution_mode": "single",
            "source_surface": "claude_desktop_local_relay_request_log",
            "source_systems": [SOURCE_SYSTEM],
            "co_source_systems": ["local_relay"],
            "storage_owner": "local_relay",
            "body_storage_owner": "not_complete_conversation_body",
            "conversation_origin": "claude_desktop_local_relay_request",
            "runtime_consumer": SOURCE_SYSTEM,
            "relay_owner": "local_relay_gateway",
            "artifact_role": "local_gateway_request_log",
            "visibility_boundary": "request_metadata_not_chat_body",
            "cross_surface_memory_shared": False,
            "official_relay_interop": False,
            "surface_readability": {
                "request_metadata_available": True,
                "message_text_returned": False,
                "raw_excerpt_returned": False,
                "complete_conversation_body": False,
            },
            "attribution_chain": [
                {
                    "role": "local_gateway",
                    "source_system": "local_relay",
                    "evidence": "proxy_request_logs",
                },
                {
                    "role": "runtime_consumer",
                    "source_system": SOURCE_SYSTEM,
                    "evidence": "app_type=claude-desktop",
                },
            ],
            "attribution_note": (
                "A local relay provider/gateway path can expose routed Desktop request metadata. "
                "The proxy_request_logs table is request metadata, not a complete chat transcript."
            ),
            "boundary_note": (
                "Keep this evidence separate from Claude Code projects JSONL and from authorized Claude Desktop local-store raw ingestion."
            ),
        }
    return {
        **collection,
        "attribution_mode": "single",
        "source_surface": SOURCE_SYSTEM,
        "source_systems": [SOURCE_SYSTEM],
        "co_source_systems": [],
        "storage_owner": SOURCE_SYSTEM,
        "body_storage_owner": SOURCE_SYSTEM,
        "conversation_origin": SOURCE_SYSTEM,
        "runtime_consumer": SOURCE_SYSTEM,
        "relay_owner": "",
        "artifact_role": sync_role or "primary",
        "visibility_boundary": "single_surface",
        "cross_surface_memory_shared": False,
        "official_relay_interop": False,
        "surface_readability": {},
        "attribution_chain": [
            {
                "role": "source_system",
                "source_system": SOURCE_SYSTEM,
                "evidence": artifact_type,
            }
        ],
    }


def claude_log_home_candidates() -> list[Path]:
    override = _path_from_env("CLAUDE_DESKTOP_LOG_HOME")
    if override:
        return [override]
    home_override = _path_from_env("CLAUDE_DESKTOP_HOME")
    if home_override:
        return [home_override / "logs"]
    platform = _platform_key()
    home = Path.home()
    if platform == "darwin":
        return [home / "Library" / "Logs" / "Claude"]
    if platform == "win32":
        candidates: list[Path] = []
        for env_name in ("APPDATA", "LOCALAPPDATA", "USERPROFILE"):
            root = os.environ.get(env_name, "").strip()
            if not root:
                continue
            base = Path(root)
            if env_name == "USERPROFILE":
                candidates.extend([
                    base / "AppData" / "Roaming" / "Claude" / "logs",
                    base / "AppData" / "Local" / "Claude" / "logs",
                ])
            else:
                candidates.append(base / "Claude" / "logs")
        return candidates
    return [home / ".config" / "Claude" / "logs", home / ".config" / "claude" / "logs"]


def resolve_claude_log_home() -> Path | None:
    for path in claude_log_home_candidates():
        if path.exists():
            return path
    candidates = claude_log_home_candidates()
    return candidates[0] if candidates else None


def _export_search_dirs(config: dict[str, Any]) -> list[Path]:
    dirs: list[Path] = []
    explicit = _path_from_env("CLAUDE_EXPORT_DIR")
    if explicit:
        dirs.append(explicit)
    prefs = config.get("preferences") if isinstance(config.get("preferences"), dict) else {}
    for value in (
        config.get("coworkUserFilesPath"),
        prefs.get("coworkUserFilesPath"),
        str(Path.home() / "Downloads"),
        str(Path.home() / "Claude"),
    ):
        text = str(value or "").strip()
        if text:
            path = Path(text).expanduser()
            if path not in dirs:
                dirs.append(path)
    return dirs


def _looks_like_claude_export(path: Path) -> bool:
    name = path.name.lower()
    if path.suffix.lower() not in {".zip", ".json", ".jsonl"}:
        return False
    return (
        "claude" in name
        or "anthropic" in name
        or "conversation" in name
        or "export" in name
    )


def discover_artifacts(limit: int = 50) -> list[dict[str, Any]]:
    root = resolve_claude_home()
    config, config_status = _load_config_result(root)
    artifacts: list[dict[str, Any]] = []
    discovered_at = ts()

    if root.exists():
        artifacts.append(_dir_artifact(
            root,
            "claude_desktop_app_support_dir",
            "SHADOW",
            discovered_at=discovered_at,
            content_read_supported_now="metadata_only",
            sync_strategy="live_local_metadata_sync",
            sync_role="primary",
        ))

    cowork_root = _cowork_sessions_root(root)
    if cowork_root.exists():
        artifacts.append(_dir_artifact(
            cowork_root,
            COWORK_SESSIONS_DIR_ARTIFACT,
            "SHADOW",
            discovered_at=discovered_at,
            content_read_supported_now="metadata_and_jsonl_body_candidates",
            sync_strategy="cowork_local_agent_store_monitor",
            sync_role="primary",
            source_surface=SURFACE_COWORK,
            note="Claude Desktop Cowork local-agent session root detected. This is separate from Chat web cache and Code projects JSONL.",
        ))
        for session_meta in discover_cowork_sessions(root, limit=min(limit, 20)):
            meta_path = Path(str(session_meta.get("source_path") or ""))
            if not meta_path.exists():
                continue
            artifacts.append(_file_artifact(
                meta_path,
                COWORK_SESSION_METADATA_ARTIFACT,
                "SHADOW",
                discovered_at=discovered_at,
                content_read_supported_now="redacted_metadata_only",
                sync_strategy="cowork_local_agent_metadata_sync",
                sync_role="primary",
                source_surface=SURFACE_COWORK,
                cowork_session_metadata={
                    **session_meta,
                    "source_path": _public_path_label(session_meta.get("source_path", "")),
                    "session_dir": _public_path_label(session_meta.get("session_dir", "")),
                },
                note="Cowork metadata links the desktop Cowork session to local-agent JSONL body artifacts; metadata itself is not the chat body.",
            ))
        artifacts.extend(_cowork_body_artifacts(root, limit=min(limit, 50)))

    skills_plugin_dir = root / "local-agent-mode-sessions" / "skills-plugin"
    if skills_plugin_dir.exists():
        artifacts.append(_dir_artifact(
            skills_plugin_dir,
            "claude_desktop_skills_plugin_dir",
            "SHADOW",
            discovered_at=discovered_at,
            content_read_supported_now="manifest_summary_only",
            sync_strategy="live_local_consumer_capability_probe",
            sync_role="consumer_capability",
            note="Claude Desktop local skills plugin directory detected. Used to diagnose whether a Yifanchen skill signal exists; not conversation memory.",
        ))
        skills_summary = _public_skills_summary(discover_skills(root))
        for plugin_root in _skills_plugin_roots(root)[: min(limit, 20)]:
            manifest_path = plugin_root / "manifest.json"
            if manifest_path.exists():
                artifacts.append(_file_artifact(
                    manifest_path,
                    "claude_desktop_skills_manifest_json",
                    "SHADOW",
                    discovered_at=discovered_at,
                    content_read_supported_now="redacted_manifest_summary_only",
                    sync_strategy="live_local_consumer_capability_probe",
                    sync_role="consumer_capability",
                    skills_summary=skills_summary,
                    note="Claude Desktop skills manifest detected. Used to distinguish skill signal from actual MCP recall connection.",
                ))

    config_path = claude_config_path(root)
    if config_path.exists():
        artifacts.append(_file_artifact(
            config_path,
            "claude_desktop_config_json",
            "SHADOW" if config_status == "ok" else "EXTERNAL",
            discovered_at=discovered_at,
            config_summary=config_summary(config),
            config_parse_status=config_status,
            content_read_supported_now="redacted_config_summary_only",
            sync_strategy="live_local_config_sync",
            sync_role="primary",
        ))

    indexeddb = root / "IndexedDB"
    if indexeddb.exists():
        artifacts.append(_dir_artifact(
            indexeddb,
            "claude_desktop_indexeddb_dir",
            "SHADOW",
            discovered_at=discovered_at,
            content_read_supported_now="parser_gate_required",
            sync_strategy="live_local_store_monitor",
            sync_role="primary",
            note="Detected Claude Desktop local IndexedDB. Yifanchen monitors it as a first-class source-system artifact; content parsing is gated by an explicit authorized parser.",
        ))
        try:
            for child in indexeddb.iterdir():
                lower_name = child.name.lower()
                if child.is_dir() and "claude.ai" in lower_name and lower_name.endswith(".leveldb"):
                    artifacts.append(_dir_artifact(
                        child,
                        "claude_desktop_indexeddb_leveldb_dir",
                        "SHADOW",
                        discovered_at=discovered_at,
                        content_read_supported_now="parser_gate_required",
                        sync_strategy="live_local_store_monitor",
                        sync_role="primary",
                        note="Local Claude Desktop IndexedDB LevelDB store. First-class sync target; parser gate required before raw ingestion.",
                    ))
                elif child.is_dir() and "claude.ai" in lower_name and lower_name.endswith(".blob"):
                    artifacts.append(_dir_artifact(
                        child,
                        "claude_desktop_indexeddb_blob_dir",
                        "SHADOW",
                        discovered_at=discovered_at,
                        content_read_supported_now="parser_gate_required",
                        sync_strategy="live_local_store_monitor",
                        sync_role="primary",
                        note="Local Claude Desktop IndexedDB blob store. First-class sync target; parser gate required before raw ingestion.",
                    ))
        except OSError:
            pass

    for rel, artifact_type in (
        (Path("Local Storage") / "leveldb", "claude_desktop_local_storage_leveldb_dir"),
        (Path("Session Storage"), "claude_desktop_session_storage_dir"),
    ):
        path = root / rel
        if path.exists():
            artifacts.append(_dir_artifact(
                path,
                artifact_type,
                "SHADOW",
                discovered_at=discovered_at,
                content_read_supported_now="parser_gate_required",
                sync_strategy="live_local_store_monitor",
                sync_role="primary",
                note="Local Claude Desktop browser-store artifact. It is monitored for incremental sync evidence; parser gate required before reading content.",
            ))

    prefs_path = root / "Preferences"
    if prefs_path.exists():
        artifacts.append(_file_artifact(
            prefs_path,
            "claude_desktop_preferences_json",
            "SHADOW",
            discovered_at=discovered_at,
            content_read_supported_now="redacted_config_summary_only",
            sync_strategy="live_local_config_sync",
            sync_role="primary",
            note="Claude Desktop preferences detected. Sensitive fields are not exposed.",
        ))

    log_home = resolve_claude_log_home()
    if log_home and log_home.exists():
        artifacts.append(_dir_artifact(
            log_home,
            "claude_desktop_logs_dir",
            "SHADOW",
            discovered_at=discovered_at,
            content_read_supported_now="metadata_only",
            sync_strategy="live_local_log_sync",
            sync_role="primary",
        ))
        try:
            log_files = [p for p in log_home.iterdir() if p.is_file() and p.suffix.lower() in {".log", ".json", ".jsonl"}]
            log_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for path in log_files[: min(limit, 20)]:
                artifacts.append(_file_artifact(
                    path,
                    "claude_desktop_log_file",
                    "SHADOW",
                    discovered_at=discovered_at,
                    content_read_supported_now="metadata_only",
                    sync_strategy="live_local_log_sync",
                    sync_role="primary",
                    note="Log file metadata only. Content reading requires a separate parser allowlist.",
                ))
        except OSError:
            pass

    for subdir, artifact_type in (
        ("claude-code-sessions", "claude_code_sessions_dir"),
        ("claude-code", "claude_code_runtime_bundle"),
        ("claude-code-vm", "claude_code_vm_bundle"),
    ):
        path = root / subdir
        if path.exists():
            artifacts.append(_dir_artifact(
                path,
                artifact_type,
                "EXTERNAL",
                discovered_at=discovered_at,
                sync_role="related_not_primary",
                note="Claude Code related artifact under Claude Desktop app data; keep distinct from Claude Desktop chat memory.",
            ))

    local_relay_db = resolve_local_relay_db_path()
    if local_relay_db:
        proxy_summary = _local_relay_proxy_request_logs_summary(local_relay_db)
        if proxy_summary.get("table_exists") and proxy_summary.get("request_count"):
            artifacts.append(_file_artifact(
                local_relay_db,
                LOCAL_RELAY_PROXY_DB_ARTIFACT,
                "SHADOW",
                discovered_at=discovered_at,
                content_read_supported_now="redacted_request_metadata_only",
                sync_strategy="local_relay_gateway_request_log_sync",
                sync_role="primary",
                relay_proxy_request_summary=proxy_summary,
                note=(
                    "A local relay provider/gateway request log was detected. "
                    "This is relay request metadata, not a required dependency and not complete conversation body."
                ),
            ))

    export_candidates: list[Path] = []
    for directory in _export_search_dirs(config):
        if not directory.exists() or not directory.is_dir():
            continue
        try:
            for path in directory.iterdir():
                if path.is_file() and _looks_like_claude_export(path):
                    export_candidates.append(path)
        except OSError:
            continue
    export_candidates = sorted(set(export_candidates), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in export_candidates[:limit]:
        artifacts.append(_file_artifact(
            path,
            "claude_data_export_candidate",
            "SHADOW",
            discovered_at=discovered_at,
            content_read_supported_now=False,
            sync_strategy="export_backfill_fallback",
            sync_role="fallback",
            note="User-initiated Claude data export candidate. This is a cold-start/backfill fallback, not the normal live sync path.",
        ))

    return artifacts


def public_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    result = dict(artifact)
    result.update(attribution_from_artifact(artifact))
    result["source_path"] = _public_path_label(result.get("source_path", ""))
    if "config_summary" in result:
        summary = dict(result["config_summary"])
        if summary.get("redacted_config"):
            summary["redacted_config"] = summary["redacted_config"]
        result["config_summary"] = summary
    return result


def _artifact_type_rank(artifact_type: str) -> int:
    priority = {
        "claude_desktop_config_json": 0,
        "claude_desktop_indexeddb_leveldb_dir": 1,
        "claude_desktop_indexeddb_blob_dir": 2,
        "claude_desktop_indexeddb_dir": 3,
        "claude_desktop_local_storage_leveldb_dir": 4,
        "claude_desktop_session_storage_dir": 5,
        "claude_desktop_logs_dir": 6,
        "claude_desktop_log_file": 7,
        "claude_desktop_skills_plugin_dir": 8,
        "claude_desktop_skills_manifest_json": 9,
        LOCAL_RELAY_PROXY_DB_ARTIFACT: 10,
        "claude_code_sessions_dir": 20,
        "claude_code_runtime_bundle": 21,
        "claude_code_vm_bundle": 22,
        "claude_data_export_candidate": 30,
    }
    return priority.get(str(artifact_type or ""), 20)


def source_refs_from_artifact(
    artifact: dict[str, Any],
    *,
    canonical_window_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    effective_session_id = _safe_session_id(session_id or artifact.get("filename", ""))
    effective_window_id = _safe_session_id(canonical_window_id or effective_session_id)
    refs = {
        "source_system": SOURCE_SYSTEM,
        "computer_name": _computer_name(),
        "canonical_window_id": effective_window_id,
        "session_id": effective_session_id,
        "source_path": artifact.get("source_path", ""),
        "msg_ids": [],
        "artifact_type": artifact.get("artifact_type", "unknown"),
        "captured_at": ts(),
        "capture_classification": artifact.get("capture_classification", "EXTERNAL"),
        "sync_strategy": artifact.get("sync_strategy", "metadata_probe"),
        "sync_role": artifact.get("sync_role", "unknown"),
        "read_only_probe": True,
    }
    refs.update(attribution_from_artifact(artifact))
    return refs


def parser_gate_policy() -> dict[str, Any]:
    artifacts = discover_artifacts(limit=80)
    parser_items = [
        _artifact_sync_item(item)
        for item in artifacts
        if item.get("artifact_type") in PARSER_ARTIFACT_TYPES
    ]
    writable_root = _raw_archive_dir()
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "gate": "explicit_authorized_parser_required",
        "parser_status": "available_but_locked",
        "parser_kind": "authorized_local_store_text_fragment_parser",
        "primary_sync_mode": "live_local_user_space_sync",
        "export_role": "cold_start_or_backfill_fallback_only",
        "default_behavior": {
            "content_read_by_default": False,
            "dry_run_default": True,
            "raw_excerpt_by_default": False,
            "memory_write_by_default": False,
            "platform_write_allowed": False,
        },
        "authorization_required": [
            "confirm_authorized_parser",
            "confirm_user_owns_claude_desktop_data",
        ],
        "apply_authorization_required": [
            "apply",
            "confirm_write_yifanchen_raw",
            "confirm_no_claude_platform_write",
        ],
        "artifact_types": sorted(PARSER_ARTIFACT_TYPES),
        "candidate_store_count": len(parser_items),
        "candidate_stores": [
            {
                "artifact_type": item.get("artifact_type", ""),
                "source_path": _public_path_label(item.get("source_path", "")),
                "exists": item.get("exists", False),
                "parser_required": True,
                "source_refs": {
                    **item.get("source_refs", {}),
                    "source_path": _public_path_label(item.get("source_refs", {}).get("source_path", "")),
                },
            }
            for item in parser_items
        ],
        "raw_write_root": _public_path_label(writable_root),
        "attribution_policy": {
            "source_collection": "claude_all",
            "storage_owner": SOURCE_SYSTEM,
            "conversation_origin": SOURCE_SYSTEM,
            "runtime_consumer": SOURCE_SYSTEM,
            "official_relay_interop": False,
            "claude_code_excluded_from_this_parser": True,
        },
        "notes": [
            "This parser reads local Claude Desktop user-space stores only after explicit authorization.",
            "It writes only Yifanchen raw JSONL when apply is explicitly authorized.",
            "It never writes Claude Desktop config, cookies, tokens, native memory, or chat stores.",
            ".claude / Claude Code data is not part of this parser.",
        ],
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
    }


def _is_authorized_parser(body: dict[str, Any] | None) -> bool:
    body = body or {}
    if body.get("authorized") is True:
        return True
    return bool(body.get("confirm_authorized_parser") and body.get("confirm_user_owns_claude_desktop_data"))


def _apply_authorized(body: dict[str, Any] | None) -> bool:
    body = body or {}
    return bool(
        body.get("apply")
        and body.get("confirm_authorized_parser")
        and body.get("confirm_user_owns_claude_desktop_data")
        and body.get("confirm_write_yifanchen_raw")
        and body.get("confirm_no_claude_platform_write")
    )


def _parser_files_from_artifact(artifact: dict[str, Any], limit: int) -> list[Path]:
    path = Path(str(artifact.get("source_path") or "")).expanduser()
    artifact_type = str(artifact.get("artifact_type") or "")
    if not path.exists():
        return []
    files: list[Path] = []
    if path.is_file():
        if path.suffix.lower() in PARSER_FILE_SUFFIXES:
            files.append(path)
        return files[:limit]
    try:
        for child in path.rglob("*"):
            if len(files) >= limit:
                break
            if not child.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in child.parts):
                continue
            if (
                child.suffix.lower() not in PARSER_FILE_SUFFIXES
                and "leveldb" not in str(child.parent).lower()
                and artifact_type != "claude_desktop_indexeddb_blob_dir"
            ):
                continue
            try:
                if child.stat().st_size <= 0:
                    continue
            except OSError:
                continue
            files.append(child)
    except OSError:
        return files[:limit]
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return files[:limit]


def _decode_file_fragments(path: Path) -> list[str]:
    try:
        size = path.stat().st_size
        if size > MAX_PARSER_FILE_BYTES:
            return []
        data = path.read_bytes()
    except OSError:
        return []

    fragments: list[str] = []
    for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
        try:
            text = data.decode(encoding, errors="ignore")
        except Exception:
            continue
        if text and ("role" in text or "message" in text or "conversation" in text or "content" in text):
            fragments.append(text)

    for match in TEXT_FRAGMENT_RE.finditer(data):
        try:
            text = match.group(0).decode("utf-8", errors="ignore")
        except Exception:
            continue
        if "role" in text or "message" in text or "conversation" in text or "content" in text:
            fragments.append(text)
    return fragments


def _balanced_json_objects(text: str, limit: int = 200) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    starts: list[int] = []
    for idx, char in enumerate(text):
        if char in "{[":
            starts.append(idx)
            if len(starts) >= limit * 12:
                break
    for start in starts:
        if len(objects) >= limit:
            break
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except Exception:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    objects.append(item)
                    if len(objects) >= limit:
                        break
    return objects


def _normalize_role(role: Any) -> str:
    text = str(role or "").strip().lower()
    if text == "human":
        return "user"
    if text in {"ai", "model"}:
        return "assistant"
    return text if text in ROLE_VALUES else "unknown"


def _text_from_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_text_from_content(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "value", "thinking"):
            if key in value:
                text = _text_from_content(value.get(key))
                if text:
                    return text
        if value.get("type") in {"text", "input_text", "output_text"}:
            return _text_from_content(value.get("text"))
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _message_dict_from_obj(obj: dict[str, Any]) -> dict[str, Any] | None:
    role = _normalize_role(obj.get("role") or obj.get("sender") or obj.get("author_role") or obj.get("type"))
    content = obj.get("content")
    if content is None:
        content = obj.get("text")
    if content is None:
        content = obj.get("message")
    if isinstance(content, dict) and "content" in content and role == "unknown":
        role = _normalize_role(content.get("role"))
    text = _text_from_content(content)
    if role == "unknown" or not text:
        return None
    return {
        "role": role,
        "content": text,
        "native_id": str(obj.get("id") or obj.get("uuid") or obj.get("message_id") or obj.get("created_at") or ""),
        "created_at": str(obj.get("created_at") or obj.get("timestamp") or obj.get("updated_at") or ""),
    }


def _collect_messages(obj: Any, limit: int = 200) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    def walk(value: Any, depth: int = 0) -> None:
        if len(messages) >= limit or depth > 8:
            return
        if isinstance(value, dict):
            direct = _message_dict_from_obj(value)
            if direct:
                messages.append(direct)
            for key in ("messages", "chat_messages", "items", "nodes", "children", "turns"):
                child = value.get(key)
                if isinstance(child, list):
                    for item in child:
                        walk(item, depth + 1)
            mapping = value.get("mapping")
            if isinstance(mapping, dict):
                for item in mapping.values():
                    walk(item, depth + 1)
            message = value.get("message")
            if isinstance(message, dict):
                walk(message, depth + 1)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)

    walk(obj)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in messages:
        key = json.dumps(
            {
                "role": message.get("role", ""),
                "content": message.get("content", ""),
                "native_id": message.get("native_id", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(message)
    return deduped


def _conversation_id_from_obj(obj: dict[str, Any], fallback: str) -> str:
    for key in (
        "conversation_id",
        "conversationId",
        "chat_id",
        "chatId",
        "thread_id",
        "threadId",
        "session_id",
        "uuid",
        "id",
    ):
        value = obj.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return fallback


def _conversation_title_from_obj(obj: dict[str, Any]) -> str:
    for key in ("title", "name", "summary", "conversation_title"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return ""


def _candidate_from_obj(obj: dict[str, Any], artifact: dict[str, Any], path: Path, index: int) -> dict[str, Any] | None:
    messages = _collect_messages(obj)
    useful_messages = [m for m in messages if m.get("role") in {"user", "assistant", "tool", "system"} and m.get("content")]
    if not useful_messages:
        return None
    looks_like_conversation = any(
        key in obj
        for key in (
            "conversation_id",
            "conversationId",
            "chat_id",
            "chatId",
            "thread_id",
            "threadId",
            "session_id",
            "messages",
            "chat_messages",
            "turns",
            "mapping",
        )
    )
    if len(useful_messages) < 2 and not looks_like_conversation:
        return None
    fallback_seed = f"{path}:{index}:{json.dumps(useful_messages[:3], ensure_ascii=False, sort_keys=True)[:500]}"
    fallback_id = hashlib.sha256(fallback_seed.encode("utf-8", errors="ignore")).hexdigest()[:16]
    conversation_id = _conversation_id_from_obj(obj, f"fragment-{fallback_id}")
    candidate_hash = hashlib.sha256(
        json.dumps(
            {
                "conversation_id": conversation_id,
                "messages": useful_messages,
                "source_path": str(path),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8", errors="ignore")
    ).hexdigest()
    session_id = _safe_session_id(conversation_id)
    refs = source_refs_from_artifact(
        artifact,
        canonical_window_id=session_id,
        session_id=session_id,
    )
    refs.update({
        "source_path": str(path),
        "artifact_type": artifact.get("artifact_type", "unknown"),
        "parser_kind": "authorized_local_store_text_fragment_parser",
        "parser_schema_version": RAW_INGEST_SCHEMA_VERSION,
        "msg_ids": [
            m.get("native_id") or f"msg_{idx + 1:03d}"
            for idx, m in enumerate(useful_messages)
        ],
        "candidate_hash": candidate_hash,
    })
    return {
        "candidate_id": candidate_hash[:24],
        "conversation_id": conversation_id,
        "session_id": session_id,
        "canonical_window_id": session_id,
        "title": _conversation_title_from_obj(obj),
        "message_count": len(useful_messages),
        "roles": sorted({m.get("role", "") for m in useful_messages if m.get("role")}),
        "source_path": str(path),
        "source_path_public": _public_path_label(path),
        "artifact_type": artifact.get("artifact_type", "unknown"),
        "store_path": artifact.get("source_path", ""),
        "store_path_public": _public_path_label(artifact.get("source_path", "")),
        "candidate_hash": candidate_hash,
        "messages": useful_messages,
        "source_refs": refs,
    }


def _scan_authorized_candidates(limit: int = 20, file_limit: int = 80) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    artifacts = [
        item for item in discover_artifacts(limit=80)
        if item.get("artifact_type") in PARSER_ARTIFACT_TYPES
    ]
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    scanned_files = 0
    scanned_objects = 0
    skipped_large_files = 0
    parse_errors = 0
    for artifact in artifacts:
        for path in _parser_files_from_artifact(artifact, file_limit):
            scanned_files += 1
            try:
                if path.stat().st_size > MAX_PARSER_FILE_BYTES:
                    skipped_large_files += 1
                    continue
            except OSError:
                continue
            fragments = _decode_file_fragments(path)
            for fragment in fragments:
                for index, obj in enumerate(_balanced_json_objects(fragment, limit=200)):
                    scanned_objects += 1
                    try:
                        candidate = _candidate_from_obj(obj, artifact, path, index)
                    except Exception:
                        parse_errors += 1
                        continue
                    if not candidate or candidate["candidate_hash"] in seen:
                        continue
                    seen.add(candidate["candidate_hash"])
                    candidates.append(candidate)
                    if len(candidates) >= limit:
                        return candidates, {
                            "artifacts_scanned": len(artifacts),
                            "files_scanned": scanned_files,
                            "json_objects_scanned": scanned_objects,
                            "skipped_large_files": skipped_large_files,
                            "parse_errors": parse_errors,
                            "limit_reached": True,
                        }
    return candidates, {
        "artifacts_scanned": len(artifacts),
        "files_scanned": scanned_files,
        "json_objects_scanned": scanned_objects,
        "skipped_large_files": skipped_large_files,
        "parse_errors": parse_errors,
        "limit_reached": False,
    }


def _safe_session_id(value: str) -> str:
    text = str(value or "").strip() or "claude-desktop-session"
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", text)
    text = text.strip(".-") or "claude-desktop-session"
    return text[:120]


def _raw_archive_dir() -> Path:
    return preferred_raw_archive_dir(
        _memory_root(),
        computer_name=_computer_name(),
        source_system=SOURCE_SYSTEM,
        native_format=NATIVE_RAW_ARTIFACT_FORMAT,
    )


def _raw_session_path(session_id: str, canonical_window_id: str = "") -> Path:
    safe_session_id = _safe_session_id(session_id)
    return preferred_raw_archive_path(
        _memory_root(),
        computer_name=_computer_name(),
        source_system=SOURCE_SYSTEM,
        native_format=NATIVE_RAW_ARTIFACT_FORMAT,
        native_scope=_safe_session_id(canonical_window_id or safe_session_id),
        session_id=safe_session_id,
    )


def _claude_projects_jsonl_raw_session_path(session_id: str, canonical_window_id: str = "") -> Path:
    safe_session_id = _safe_session_id(session_id)
    return preferred_raw_archive_path(
        _memory_root(),
        computer_name=_computer_name(),
        source_system=SOURCE_SYSTEM,
        native_format=CLAUDE_PROJECTS_JSONL_RAW_FORMAT,
        native_scope=_safe_session_id(canonical_window_id or safe_session_id),
        session_id=safe_session_id,
    )


def _short_path_digest(path: Path) -> str:
    text = str(path).replace("\\", "/")
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:8]


def _claude_projects_jsonl_raw_artifact_id(source_path: str | Path, session_id: str) -> str:
    """Return a stable raw id for one Claude projects JSONL file.

    Claude Desktop project JSONL can use the same native sessionId across more
    than one source file. Keep session_id as the native conversation grouping
    key, but make the raw archive filename source-file-specific.
    """
    path = Path(str(source_path or "")).expanduser()
    sid = _safe_session_id(session_id or path.stem)
    stem = _safe_session_id(path.stem or sid)
    if stem and stem != sid:
        digest = _short_path_digest(path)
        raw_id = _safe_session_id(f"{sid}__{stem}__{digest}")
        if len(raw_id) <= RAW_ARCHIVE_SEGMENT_MAX_CHARS and raw_id.endswith(digest):
            return raw_id
        sid_part = sid[:54].strip(".-") or "session"
        stem_part = stem[:28].strip(".-") or "source"
        return _safe_session_id(f"{sid_part}__{stem_part}__{digest}")
    return sid


def _claude_projects_jsonl_raw_artifact_path(
    session_id: str,
    canonical_window_id: str = "",
    raw_artifact_id: str = "",
) -> Path:
    return _claude_projects_jsonl_raw_session_path(
        raw_artifact_id or session_id,
        canonical_window_id,
    )


def _native_jsonl_raw_artifact_path(
    *,
    native_format: str,
    session_id: str,
    canonical_window_id: str = "",
    raw_artifact_id: str = "",
) -> Path:
    safe_session_id = _safe_session_id(raw_artifact_id or session_id)
    return preferred_raw_archive_path(
        _memory_root(),
        computer_name=_computer_name(),
        source_system=SOURCE_SYSTEM,
        native_format=native_format,
        native_scope=_safe_session_id(canonical_window_id or session_id),
        session_id=safe_session_id,
    )


def _legacy_fixed_scope_raw_session_path(session_id: str) -> Path:
    return preferred_raw_archive_path(
        _memory_root(),
        computer_name=_computer_name(),
        source_system=SOURCE_SYSTEM,
        native_format=NATIVE_RAW_ARTIFACT_FORMAT,
        native_scope=SOURCE_SYSTEM,
        session_id=_safe_session_id(session_id),
    )


def _message_content_hash(content: Any) -> str:
    text = _text_from_content(content)
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _claude_desktop_linked_project_candidates(limit: int = 20) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return Claude Desktop-linked `projects/**/*.jsonl` candidates.

    The raw writer mirrors Claude's native JSONL bytes instead of normalizing
    them, so the original record line is preserved. A local relay implementation
    was only a development reference for this path, not a required dependency or
    source.
    """
    try:
        import claude_code_local_connector as claude_code
    except Exception as exc:
        return [], {
            "claude_projects_jsonl_import_available": False,
            "claude_projects_jsonl_error": f"{type(exc).__name__}:{str(exc)[:160]}",
        }

    safe_limit = max(1, min(int(limit or 20), 200))
    try:
        artifacts = claude_code.discover_sessions(limit=max(safe_limit * 4, 20))
    except Exception as exc:
        return [], {
            "claude_projects_jsonl_import_available": False,
            "claude_projects_jsonl_error": f"{type(exc).__name__}:{str(exc)[:160]}",
        }

    candidates: list[dict[str, Any]] = []
    scanned = 0
    for artifact in artifacts:
        scanned += 1
        desktop_linked = (
            artifact.get("desktop_entrypoint_detected")
            or artifact.get("desktop_session_metadata_detected")
            or "claude_desktop" in (artifact.get("co_source_systems") or [])
            or str(artifact.get("conversation_origin") or "").startswith("claude_desktop")
        )
        if not desktop_linked:
            continue
        session_id = _safe_session_id(str(artifact.get("session_id") or Path(str(artifact.get("source_path") or "")).stem))
        window_id = _safe_session_id(str(artifact.get("canonical_window_id") or session_id))
        roles: list[str] = []
        if int(artifact.get("user_message_count", 0) or 0):
            roles.append("user")
        if int(artifact.get("assistant_message_count", 0) or 0):
            roles.append("assistant")
        if int(artifact.get("tool_result_message_count", 0) or 0):
            roles.append("tool")
        source_path = str(artifact.get("source_path") or "")
        raw_artifact_id = _safe_session_id(
            _claude_projects_jsonl_raw_artifact_id(source_path, session_id)
        )
        raw_path = _claude_projects_jsonl_raw_artifact_path(session_id, window_id, raw_artifact_id)
        refs = {
            "source_system": SOURCE_SYSTEM,
            "source_collection": "claude_all",
            "computer_name": _computer_name(),
            "canonical_window_id": window_id,
            "session_id": session_id,
            "raw_artifact_id": raw_artifact_id,
            "raw_artifact_id_schema": CLAUDE_PROJECTS_JSONL_RAW_ARTIFACT_ID_SCHEMA,
            "source_path": source_path,
            "raw_session_path": str(raw_path),
            "native_artifact_format": CLAUDE_PROJECTS_JSONL_RAW_FORMAT,
            "raw_archive_layout": "computer_first",
            "artifact_type": CLAUDE_PROJECTS_JSONL_RAW_FORMAT,
            "parser_kind": "claude_projects_jsonl_mirror",
            "provider_source_glob": "projects/**/*.jsonl",
            "storage_owner": SOURCE_SYSTEM,
            "body_storage_owner": artifact.get("body_storage_owner", CLAUDE_CODE_BODY_STORAGE_OWNER),
            "conversation_origin": artifact.get("conversation_origin", ""),
            "runtime_consumer": artifact.get("runtime_consumer", CLAUDE_DESKTOP_MANAGED_RUNTIME_CONSUMER),
            "source_surface": SURFACE_CODE_OR_AGENT,
            "visibility_boundary": "desktop_entrypoint_or_desktop_managed_code_jsonl",
            "official_relay_interop": False,
            "desktop_entrypoint_detected": bool(artifact.get("desktop_entrypoint_detected")),
            "desktop_session_metadata_detected": bool(artifact.get("desktop_session_metadata_detected")),
            "desktop_metadata_is_conversation_body": False,
            "relay_db_is_transcript_store": False,
            "development_reference": "none",
            "development_reference_only": False,
            "message_text_returned": False,
            "raw_excerpt_returned": False,
        }
        candidates.append({
            "candidate_id": hashlib.sha256(
                f"{source_path}|{session_id}|{artifact.get('mtime', '')}".encode("utf-8", errors="ignore")
            ).hexdigest()[:24],
            "candidate_kind": "claude_projects_jsonl_desktop_entrypoint",
            "raw_ingest_strategy": "native_jsonl_mirror",
            "conversation_id": session_id,
            "session_id": session_id,
            "raw_artifact_id": raw_artifact_id,
            "raw_artifact_id_schema": CLAUDE_PROJECTS_JSONL_RAW_ARTIFACT_ID_SCHEMA,
            "canonical_window_id": window_id,
            "title": str(artifact.get("thread_name") or ""),
            "message_count": int(artifact.get("content_message_count", 0) or 0),
            "roles": sorted(set(roles)),
            "source_path": source_path,
            "source_path_public": _public_path_label(source_path),
            "artifact_type": CLAUDE_PROJECTS_JSONL_RAW_FORMAT,
            "store_path": source_path,
            "store_path_public": _public_path_label(source_path),
            "candidate_hash": hashlib.sha256(
                json.dumps(
                    {
                        "source_path": source_path,
                        "session_id": session_id,
                        "mtime": artifact.get("mtime", ""),
                        "size_bytes": artifact.get("size_bytes", 0),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8", errors="ignore")
            ).hexdigest(),
            "source_refs": refs,
            "project_id": artifact.get("project_id", ""),
            "project_root": artifact.get("project_root", ""),
            "conversation_origin": artifact.get("conversation_origin", ""),
            "runtime_consumer": artifact.get("runtime_consumer", ""),
            "body_storage_owner": artifact.get("body_storage_owner", CLAUDE_CODE_BODY_STORAGE_OWNER),
            "desktop_entrypoint_detected": bool(artifact.get("desktop_entrypoint_detected")),
            "desktop_session_metadata_detected": bool(artifact.get("desktop_session_metadata_detected")),
            "complete_conversation_candidate": bool(artifact.get("complete_conversation_candidate")),
        })
        if len(candidates) >= safe_limit:
            break
    return candidates, {
        "claude_projects_jsonl_import_available": True,
        "claude_projects_jsonl_artifacts_scanned": scanned,
        "claude_projects_jsonl_candidate_count": len(candidates),
        "claude_projects_jsonl_complete_candidate_count": len([
            item for item in candidates if _candidate_has_complete_conversation(item)
        ]),
        "claude_projects_jsonl_boundary": CLAUDE_PROJECTS_JSONL_BOUNDARY,
        "development_reference": "none",
    }


def _cowork_jsonl_raw_artifact_id(source_path: str | Path, session_id: str, native_format: str) -> str:
    path = Path(str(source_path or "")).expanduser()
    sid = _safe_session_id(session_id or path.stem)
    stem = _safe_session_id(path.stem or sid)
    digest = _short_path_digest(path)
    format_tag = _safe_session_id(native_format.replace("claude_desktop_", "").replace("_jsonl", ""))
    if stem and stem != sid:
        raw_id = _safe_session_id(f"{sid}__{format_tag}__{stem}__{digest}")
    else:
        raw_id = _safe_session_id(f"{sid}__{format_tag}__{digest}")
    if len(raw_id) <= RAW_ARCHIVE_SEGMENT_MAX_CHARS and raw_id.endswith(digest):
        return raw_id
    sid_part = sid[:52].strip(".-") or "session"
    tag_part = format_tag[:16].strip(".-") or "cowork"
    stem_part = stem[:20].strip(".-") or "source"
    return _safe_session_id(f"{sid_part}__{tag_part}__{stem_part}__{digest}")


def _cowork_jsonl_candidates(limit: int = 20) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 20), 200))
    artifacts = [
        artifact for artifact in discover_artifacts(limit=max(safe_limit * 4, 20))
        if artifact.get("artifact_type") in COWORK_BODY_ARTIFACT_TYPES
    ]
    candidates: list[dict[str, Any]] = []
    for artifact in artifacts:
        source_path = str(artifact.get("source_path") or "")
        if not source_path:
            continue
        session_id = _safe_session_id(str(artifact.get("session_id") or Path(source_path).stem))
        window_id = _safe_session_id(str(artifact.get("canonical_window_id") or artifact.get("desktop_session_id") or session_id))
        native_format = str(artifact.get("artifact_type") or COWORK_PROJECTS_JSONL_RAW_FORMAT)
        raw_artifact_id = _cowork_jsonl_raw_artifact_id(source_path, session_id, native_format)
        raw_path = _native_jsonl_raw_artifact_path(
            native_format=native_format,
            session_id=session_id,
            canonical_window_id=window_id,
            raw_artifact_id=raw_artifact_id,
        )
        roles = sorted(set(artifact.get("roles") or []))
        refs = {
            "source_system": SOURCE_SYSTEM,
            "source_collection": "claude_all",
            "computer_name": _computer_name(),
            "canonical_window_id": window_id,
            "session_id": session_id,
            "raw_artifact_id": raw_artifact_id,
            "raw_artifact_id_schema": COWORK_JSONL_RAW_ARTIFACT_ID_SCHEMA,
            "source_path": source_path,
            "raw_session_path": str(raw_path),
            "native_artifact_format": native_format,
            "raw_archive_layout": "computer_first",
            "artifact_type": native_format,
            "parser_kind": "cowork_local_agent_jsonl_mirror",
            "storage_owner": SOURCE_SYSTEM,
            "body_storage_owner": COWORK_LOCAL_AGENT_BODY_OWNER,
            "conversation_origin": SURFACE_COWORK,
            "runtime_consumer": COWORK_RUNTIME_CONSUMER,
            "source_surface": SURFACE_COWORK,
            "visibility_boundary": "cowork_local_agent_surface",
            "official_relay_interop": False,
            "desktop_session_id": artifact.get("desktop_session_id", ""),
            "session_metadata_path": artifact.get("session_metadata_path", ""),
            "message_text_returned": False,
            "raw_excerpt_returned": False,
        }
        candidates.append({
            "candidate_id": hashlib.sha256(
                f"{source_path}|{session_id}|{artifact.get('mtime', '')}|{native_format}".encode("utf-8", errors="ignore")
            ).hexdigest()[:24],
            "candidate_kind": "claude_desktop_cowork_jsonl",
            "raw_ingest_strategy": "native_jsonl_mirror",
            "conversation_id": session_id,
            "session_id": session_id,
            "raw_artifact_id": raw_artifact_id,
            "raw_artifact_id_schema": COWORK_JSONL_RAW_ARTIFACT_ID_SCHEMA,
            "canonical_window_id": window_id,
            "title": str(artifact.get("title") or ""),
            "message_count": int(artifact.get("content_message_count", 0) or 0),
            "roles": roles,
            "source_path": source_path,
            "source_path_public": _public_path_label(source_path),
            "artifact_type": native_format,
            "store_path": source_path,
            "store_path_public": _public_path_label(source_path),
            "candidate_hash": hashlib.sha256(
                json.dumps(
                    {
                        "source_path": source_path,
                        "session_id": session_id,
                        "mtime": artifact.get("mtime", ""),
                        "size_bytes": artifact.get("size_bytes", 0),
                        "native_format": native_format,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8", errors="ignore")
            ).hexdigest(),
            "source_refs": refs,
            "conversation_origin": SURFACE_COWORK,
            "runtime_consumer": COWORK_RUNTIME_CONSUMER,
            "body_storage_owner": COWORK_LOCAL_AGENT_BODY_OWNER,
            "complete_conversation_candidate": bool(artifact.get("complete_conversation_candidate")),
            "desktop_session_id": artifact.get("desktop_session_id", ""),
        })
        if len(candidates) >= safe_limit:
            break
    return candidates, {
        "cowork_jsonl_import_available": True,
        "cowork_jsonl_artifacts_scanned": len(artifacts),
        "cowork_jsonl_candidate_count": len(candidates),
        "cowork_jsonl_complete_candidate_count": len([
            item for item in candidates if _candidate_has_complete_conversation(item)
        ]),
        "cowork_source_surface": SURFACE_COWORK,
    }


def _local_relay_desktop_linked_project_candidates(limit: int = 20) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Backward-compatible alias for older internal callers."""
    return _claude_desktop_linked_project_candidates(limit=limit)


def _stable_message_dedupe_key(session_id: str, msg_id: str, role: str, content_hash: str) -> str:
    seed = {
        "source_system": SOURCE_SYSTEM,
        "session_id": _safe_session_id(session_id),
        "message_id": str(msg_id or ""),
        "role": _normalize_role(role),
        "content_hash": str(content_hash or ""),
    }
    return hashlib.sha256(
        json.dumps(seed, ensure_ascii=False, sort_keys=True).encode("utf-8", errors="ignore")
    ).hexdigest()


def _message_dedupe_key(candidate: dict[str, Any], message: dict[str, Any], index: int) -> str:
    msg_id = message.get("native_id") or f"msg_{index + 1:03d}"
    return _stable_message_dedupe_key(
        str(candidate.get("session_id") or candidate.get("conversation_id") or ""),
        str(msg_id),
        str(message.get("role") or "unknown"),
        _message_content_hash(message.get("content", "")),
    )


def _record_text_from_payload(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    if "content" in payload:
        return _text_from_content(payload.get("content"))
    if "text" in payload:
        return _text_from_content(payload.get("text"))
    return _text_from_content(payload)


def _record_dedupe_key(record: dict[str, Any]) -> str:
    if not isinstance(record, dict):
        return ""
    raw_ingest = record.get("raw_ingest", {}) if isinstance(record.get("raw_ingest"), dict) else {}
    existing = str(raw_ingest.get("message_dedupe_key") or "").strip()
    if existing:
        return existing

    refs = record.get("source_refs", {}) if isinstance(record.get("source_refs"), dict) else {}
    msg_ids = refs.get("msg_ids", []) if isinstance(refs.get("msg_ids", []), list) else []
    msg_id = str(record.get("id") or (msg_ids[0] if msg_ids else "") or "")
    if not msg_id:
        try:
            msg_id = f"msg_{int(raw_ingest.get('message_index')) + 1:03d}"
        except Exception:
            msg_id = ""

    payload = record.get("payload", {}) if isinstance(record.get("payload"), dict) else {}
    content_hash = str(raw_ingest.get("message_content_hash") or "").strip()
    if not content_hash:
        content_hash = _message_content_hash(_record_text_from_payload(payload))

    return _stable_message_dedupe_key(
        str(refs.get("session_id") or raw_ingest.get("conversation_id") or ""),
        msg_id,
        str(payload.get("role") or "unknown"),
        content_hash,
    )


def _record_from_candidate(candidate: dict[str, Any], message: dict[str, Any], index: int) -> dict[str, Any]:
    msg_id = message.get("native_id") or f"msg_{index + 1:03d}"
    content_hash = _message_content_hash(message.get("content", ""))
    dedupe_key = _message_dedupe_key(candidate, message, index)
    refs = dict(candidate.get("source_refs", {}))
    refs["msg_ids"] = [msg_id]
    refs["canonical_window_id"] = _safe_session_id(
        candidate.get("canonical_window_id") or candidate.get("session_id", "")
    )
    refs["session_id"] = _safe_session_id(candidate.get("session_id", ""))
    refs["raw_session_path"] = str(_raw_session_path(
        candidate.get("session_id", ""),
        candidate.get("canonical_window_id", ""),
    ))
    refs["native_artifact_format"] = NATIVE_RAW_ARTIFACT_FORMAT
    refs["raw_archive_layout"] = "computer_first"
    return {
        "timestamp": message.get("created_at") or ts(),
        "id": msg_id,
        "type": "response_item",
        "source_system": SOURCE_SYSTEM,
        "payload": {
            "type": "message",
            "role": message.get("role", "unknown"),
            "content": [
                {
                    "type": "output_text" if message.get("role") == "assistant" else "input_text",
                    "text": message.get("content", ""),
                }
            ],
        },
        "source_refs": refs,
        "_source_refs": refs,
        "raw_ingest": {
            "schema_version": RAW_INGEST_SCHEMA_VERSION,
            "parser_kind": "authorized_local_store_text_fragment_parser",
            "candidate_id": candidate.get("candidate_id", ""),
            "candidate_hash": candidate.get("candidate_hash", ""),
            "conversation_id": candidate.get("conversation_id", ""),
            "message_index": index,
            "message_content_hash": content_hash,
            "message_dedupe_key": dedupe_key,
            "saved_content_preserved_verbatim": True,
            "redaction_performed": False,
            "hash_only_replacement_allowed": False,
        },
    }


def _retarget_record_to_candidate_window(record: dict[str, Any], candidate: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    retargeted = dict(record)
    session_id = _safe_session_id(candidate.get("session_id", ""))
    window_id = _safe_session_id(candidate.get("canonical_window_id") or session_id)
    for key in ("source_refs", "_source_refs"):
        refs = retargeted.get(key)
        if not isinstance(refs, dict):
            refs = {}
        refs = dict(refs)
        refs.update({
            "source_system": SOURCE_SYSTEM,
            "computer_name": _computer_name(),
            "canonical_window_id": window_id,
            "session_id": session_id,
            "raw_session_path": str(raw_path),
            "native_artifact_format": NATIVE_RAW_ARTIFACT_FORMAT,
            "raw_archive_layout": "computer_first",
        })
        retargeted[key] = refs
    return retargeted


def _migrate_legacy_fixed_scope_records(
    candidate: dict[str, Any],
    raw_path: Path,
    existing_dedupe_keys: set[str],
) -> dict[str, Any]:
    legacy_path = _legacy_fixed_scope_raw_session_path(candidate.get("session_id", ""))
    if legacy_path == raw_path or not legacy_path.exists():
        return {"records_migrated": 0, "legacy_path": ""}

    records_migrated = 0
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with legacy_path.open("r", encoding="utf-8", errors="ignore") as src, raw_path.open("a", encoding="utf-8") as dst:
            for line in src:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if not isinstance(record, dict):
                    continue
                dedupe_key = _record_dedupe_key(record)
                if not dedupe_key:
                    dedupe_key = hashlib.sha256(line.encode("utf-8", errors="ignore")).hexdigest()
                if dedupe_key in existing_dedupe_keys:
                    continue
                retargeted = _retarget_record_to_candidate_window(record, candidate, raw_path)
                dst.write(json.dumps(retargeted, ensure_ascii=False, sort_keys=True) + "\n")
                existing_dedupe_keys.add(dedupe_key)
                records_migrated += 1
    except OSError:
        return {"records_migrated": 0, "legacy_path": str(legacy_path), "error": "legacy_read_or_write_failed"}

    return {"records_migrated": records_migrated, "legacy_path": str(legacy_path)}


def _register_current_window_for_candidate(candidate: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    source_refs = candidate.get("source_refs", {}) if isinstance(candidate.get("source_refs"), dict) else {}
    native_format = (
        source_refs.get("native_artifact_format")
        or candidate.get("artifact_type")
        or NATIVE_RAW_ARTIFACT_FORMAT
    )
    return register_current_window(
        source_system=SOURCE_SYSTEM,
        consumer=SOURCE_SYSTEM,
        canonical_window_id=candidate.get("canonical_window_id", ""),
        session_id=candidate.get("session_id", ""),
        native_window_id=candidate.get("conversation_id", ""),
        title=candidate.get("title", ""),
        source_path=str(raw_path),
        binding_source="claude_desktop_authorized_raw_ingest",
        confidence="authorized_local_store_capture",
        metadata={
            "candidate_id": candidate.get("candidate_id", ""),
            "candidate_hash": candidate.get("candidate_hash", ""),
            "message_count": candidate.get("message_count", 0),
            "roles": candidate.get("roles", []),
            "raw_archive_layout": "computer_first",
            "native_artifact_format": native_format,
            "body_storage_owner": candidate.get("body_storage_owner") or source_refs.get("body_storage_owner", ""),
            "conversation_origin": candidate.get("conversation_origin") or source_refs.get("conversation_origin", ""),
            "runtime_consumer": candidate.get("runtime_consumer") or source_refs.get("runtime_consumer", ""),
            "desktop_entrypoint_detected": bool(candidate.get("desktop_entrypoint_detected") or source_refs.get("desktop_entrypoint_detected")),
            "desktop_metadata_is_conversation_body": bool(source_refs.get("desktop_metadata_is_conversation_body")),
        },
    )


def _append_raw_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    written_paths: list[str] = []
    legacy_paths: list[str] = []
    window_bindings: list[dict[str, Any]] = []
    window_binding_skipped_candidate_ids: list[str] = []
    records_written = 0
    legacy_records_migrated = 0
    sessions_written = 0
    existing_dedupe_keys: dict[Path, set[str]] = {}
    current_window_registered = False
    for candidate in candidates:
        raw_path = _raw_session_path(
            candidate.get("session_id", ""),
            candidate.get("canonical_window_id", ""),
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_path not in existing_dedupe_keys:
            keys: set[str] = set()
            if raw_path.exists():
                try:
                    with raw_path.open("r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except Exception:
                                obj = {}
                            key = _record_dedupe_key(obj) if isinstance(obj, dict) else ""
                            if not key:
                                key = hashlib.sha256(line.encode("utf-8", errors="ignore")).hexdigest()
                            keys.add(key)
                except OSError:
                    pass
            existing_dedupe_keys[raw_path] = keys
        before = records_written
        migration = _migrate_legacy_fixed_scope_records(candidate, raw_path, existing_dedupe_keys[raw_path])
        migrated_count = int(migration.get("records_migrated") or 0)
        if migrated_count:
            legacy_records_migrated += migrated_count
            records_written += migrated_count
            legacy_path = str(migration.get("legacy_path") or "")
            if legacy_path and legacy_path not in legacy_paths:
                legacy_paths.append(legacy_path)
        with raw_path.open("a", encoding="utf-8") as f:
            for index, message in enumerate(candidate.get("messages", [])):
                record = _record_from_candidate(candidate, message, index)
                line = json.dumps(record, ensure_ascii=False, sort_keys=True)
                dedupe_key = _record_dedupe_key(record)
                if not dedupe_key:
                    dedupe_key = hashlib.sha256(line.encode("utf-8", errors="ignore")).hexdigest()
                if dedupe_key in existing_dedupe_keys[raw_path]:
                    continue
                existing_dedupe_keys[raw_path].add(dedupe_key)
                f.write(line + "\n")
                records_written += 1
        if records_written > before:
            sessions_written += 1
            written_paths.append(str(raw_path))
        if raw_path.exists() and not current_window_registered:
            if _candidate_has_complete_conversation(candidate):
                binding = _register_current_window_for_candidate(candidate, raw_path)
                if binding.get("ok"):
                    window_bindings.append(binding)
                    current_window_registered = True
            else:
                candidate_id = str(candidate.get("candidate_id") or "")
                if candidate_id:
                    window_binding_skipped_candidate_ids.append(candidate_id)
    return {
        "sessions_written": sessions_written,
        "records_written": records_written,
        "legacy_records_migrated": legacy_records_migrated,
        "window_bindings_registered": len(window_bindings),
        "window_bindings": window_bindings,
        "window_bindings_skipped_incomplete": len(window_binding_skipped_candidate_ids),
        "window_binding_skipped_candidate_ids": window_binding_skipped_candidate_ids,
        "legacy_raw_paths": legacy_paths,
        "legacy_raw_paths_public": [_public_path_label(path) for path in legacy_paths],
        "raw_paths": written_paths,
        "raw_paths_public": [_public_path_label(path) for path in written_paths],
    }


def _sha256_file(path: Path, max_bytes: int = 256 * 1024 * 1024) -> str:
    try:
        if path.stat().st_size > max_bytes:
            return f"sha256_skipped_large_file:{path.stat().st_size}"
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _write_claude_projects_jsonl_meta(candidate: dict[str, Any], raw_path: Path, source_path: Path, offset: int) -> None:
    meta = {
        "source_system": SOURCE_SYSTEM,
        "source_path": str(source_path),
        "source_checksum": _sha256_file(source_path),
        "archived_to": str(raw_path),
        "native_artifact_format": CLAUDE_PROJECTS_JSONL_RAW_FORMAT,
        "raw_archive_layout": "computer_first",
        "session_id": candidate.get("session_id", ""),
        "raw_artifact_id": candidate.get("raw_artifact_id", candidate.get("session_id", "")),
        "raw_artifact_id_schema": candidate.get(
            "raw_artifact_id_schema",
            CLAUDE_PROJECTS_JSONL_RAW_ARTIFACT_ID_SCHEMA,
        ),
        "canonical_window_id": candidate.get("canonical_window_id", ""),
        "project_id": candidate.get("project_id", ""),
        "project_root": candidate.get("project_root", ""),
        "thread_name": candidate.get("title", ""),
        "file_offset": offset,
        "storage_owner": SOURCE_SYSTEM,
        "body_storage_owner": candidate.get("body_storage_owner", CLAUDE_CODE_BODY_STORAGE_OWNER),
        "conversation_origin": candidate.get("conversation_origin", ""),
        "runtime_consumer": candidate.get("runtime_consumer", ""),
        "desktop_entrypoint_detected": bool(candidate.get("desktop_entrypoint_detected")),
        "desktop_session_metadata_detected": bool(candidate.get("desktop_session_metadata_detected")),
        "desktop_metadata_is_conversation_body": False,
        "claude_projects_jsonl_reference": CLAUDE_PROJECTS_JSONL_REFERENCE_CONTRACT,
        "claude_projects_jsonl_boundary": CLAUDE_PROJECTS_JSONL_BOUNDARY,
        "legacy_native_artifact_formats": list(CLAUDE_PROJECTS_JSONL_LEGACY_RAW_FORMATS),
        "development_reference": "A local relay was used as a development reference only; Claude projects JSONL is the source.",
        "development_reference_only": True,
        "source_refs": candidate.get("source_refs", {}),
        "last_update": ts(),
        "platform_write_performed": False,
    }
    with Path(str(raw_path) + ".meta.json").open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)


def _write_native_jsonl_mirror_meta(candidate: dict[str, Any], raw_path: Path, source_path: Path, offset: int) -> None:
    source_refs = candidate.get("source_refs", {}) if isinstance(candidate.get("source_refs"), dict) else {}
    native_format = (
        source_refs.get("native_artifact_format")
        or candidate.get("artifact_type")
        or "native_jsonl"
    )
    meta = {
        "source_system": SOURCE_SYSTEM,
        "source_path": str(source_path),
        "source_checksum": _sha256_file(source_path),
        "archived_to": str(raw_path),
        "native_artifact_format": native_format,
        "raw_archive_layout": "computer_first",
        "session_id": candidate.get("session_id", ""),
        "raw_artifact_id": candidate.get("raw_artifact_id", candidate.get("session_id", "")),
        "raw_artifact_id_schema": candidate.get("raw_artifact_id_schema", ""),
        "canonical_window_id": candidate.get("canonical_window_id", ""),
        "thread_name": candidate.get("title", ""),
        "file_offset": offset,
        "storage_owner": SOURCE_SYSTEM,
        "body_storage_owner": candidate.get("body_storage_owner", source_refs.get("body_storage_owner", "")),
        "conversation_origin": candidate.get("conversation_origin", source_refs.get("conversation_origin", "")),
        "runtime_consumer": candidate.get("runtime_consumer", source_refs.get("runtime_consumer", "")),
        "source_surface": source_refs.get("source_surface", ""),
        "desktop_session_id": candidate.get("desktop_session_id", source_refs.get("desktop_session_id", "")),
        "source_refs": source_refs,
        "last_update": ts(),
        "platform_write_performed": False,
    }
    with Path(str(raw_path) + ".meta.json").open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=2)


def _append_native_jsonl_mirror_candidates(
    candidates: list[dict[str, Any]],
    *,
    default_native_format: str,
) -> dict[str, Any]:
    written_paths: list[str] = []
    window_bindings: list[dict[str, Any]] = []
    window_binding_skipped_candidate_ids: list[str] = []
    records_written = 0
    sessions_written = 0
    items: list[dict[str, Any]] = []
    current_window_registered = False
    for candidate in candidates:
        source_path = Path(str(candidate.get("source_path") or "")).expanduser()
        source_refs = candidate.get("source_refs", {}) if isinstance(candidate.get("source_refs"), dict) else {}
        native_format = str(source_refs.get("native_artifact_format") or candidate.get("artifact_type") or default_native_format)
        raw_artifact_id = _safe_session_id(
            str(candidate.get("raw_artifact_id") or _cowork_jsonl_raw_artifact_id(source_path, str(candidate.get("session_id") or ""), native_format))
        )
        raw_path = _native_jsonl_raw_artifact_path(
            native_format=native_format,
            session_id=str(candidate.get("session_id") or ""),
            canonical_window_id=str(candidate.get("canonical_window_id") or ""),
            raw_artifact_id=raw_artifact_id,
        )
        candidate = {
            **candidate,
            "raw_artifact_id": raw_artifact_id,
            "source_refs": {
                **source_refs,
                "raw_artifact_id": raw_artifact_id,
                "raw_session_path": str(raw_path),
                "native_artifact_format": native_format,
            },
        }
        if not source_path.exists():
            items.append({
                "session_id": candidate.get("session_id", ""),
                "raw_artifact_id": raw_artifact_id,
                "raw_path": str(raw_path),
                "status": "source_missing",
                "records_written": 0,
            })
            continue
        try:
            source_size = source_path.stat().st_size
            raw_size = raw_path.stat().st_size if raw_path.exists() else 0
        except OSError:
            items.append({
                "session_id": candidate.get("session_id", ""),
                "raw_artifact_id": raw_artifact_id,
                "raw_path": str(raw_path),
                "status": "stat_error",
                "records_written": 0,
            })
            continue
        overwrite = raw_size > source_size
        offset = 0 if overwrite else raw_size
        if raw_size == source_size and raw_path.exists():
            _write_native_jsonl_mirror_meta(candidate, raw_path, source_path, source_size)
            if _candidate_has_complete_conversation(candidate) and not current_window_registered:
                binding = _register_current_window_for_candidate(candidate, raw_path)
                if binding.get("ok"):
                    window_bindings.append(binding)
                    current_window_registered = True
            elif not _candidate_has_complete_conversation(candidate):
                candidate_id = str(candidate.get("candidate_id") or "")
                if candidate_id:
                    window_binding_skipped_candidate_ids.append(candidate_id)
            items.append({
                "session_id": candidate.get("session_id", ""),
                "raw_artifact_id": raw_artifact_id,
                "raw_path": str(raw_path),
                "status": "up_to_date",
                "records_written": 0,
            })
            continue
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        line_count = 0
        mode = "wb" if overwrite else "ab"
        try:
            with source_path.open("rb") as src, raw_path.open(mode) as dst:
                src.seek(offset)
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    bytes_written += len(chunk)
                    line_count += chunk.count(b"\n")
        except OSError:
            items.append({
                "session_id": candidate.get("session_id", ""),
                "raw_artifact_id": raw_artifact_id,
                "raw_path": str(raw_path),
                "status": "copy_error",
                "records_written": 0,
            })
            continue
        if bytes_written:
            records_written += max(1, line_count)
            sessions_written += 1
            written_paths.append(str(raw_path))
        _write_native_jsonl_mirror_meta(candidate, raw_path, source_path, source_size)
        if raw_path.exists() and not current_window_registered:
            if _candidate_has_complete_conversation(candidate):
                binding = _register_current_window_for_candidate(candidate, raw_path)
                if binding.get("ok"):
                    window_bindings.append(binding)
                    current_window_registered = True
            else:
                candidate_id = str(candidate.get("candidate_id") or "")
                if candidate_id:
                    window_binding_skipped_candidate_ids.append(candidate_id)
        items.append({
            "session_id": candidate.get("session_id", ""),
            "raw_artifact_id": raw_artifact_id,
            "raw_path": str(raw_path),
            "status": "rewritten" if overwrite else "appended",
            "bytes_written": bytes_written,
            "records_written": max(1, line_count) if bytes_written else 0,
            "offset": source_size,
        })
    return {
        "sessions_written": sessions_written,
        "records_written": records_written,
        "window_bindings_registered": len(window_bindings),
        "window_bindings": window_bindings,
        "window_bindings_skipped_incomplete": len(window_binding_skipped_candidate_ids),
        "window_binding_skipped_candidate_ids": window_binding_skipped_candidate_ids,
        "raw_paths": written_paths,
        "raw_paths_public": [_public_path_label(path) for path in written_paths],
        "items": items,
        "native_artifact_format": default_native_format,
    }


def _append_claude_projects_jsonl_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    written_paths: list[str] = []
    window_bindings: list[dict[str, Any]] = []
    window_binding_skipped_candidate_ids: list[str] = []
    records_written = 0
    sessions_written = 0
    items: list[dict[str, Any]] = []
    current_window_registered = False
    for candidate in candidates:
        source_path = Path(str(candidate.get("source_path") or "")).expanduser()
        raw_artifact_id = _safe_session_id(
            str(
                candidate.get("raw_artifact_id")
                or _claude_projects_jsonl_raw_artifact_id(
                    source_path,
                    str(candidate.get("session_id") or ""),
                )
            )
        )
        candidate = {
            **candidate,
            "raw_artifact_id": raw_artifact_id,
            "raw_artifact_id_schema": candidate.get(
                "raw_artifact_id_schema",
                CLAUDE_PROJECTS_JSONL_RAW_ARTIFACT_ID_SCHEMA,
            ),
            "source_refs": {
                **(candidate.get("source_refs", {}) if isinstance(candidate.get("source_refs"), dict) else {}),
                "raw_artifact_id": raw_artifact_id,
                "raw_artifact_id_schema": candidate.get(
                    "raw_artifact_id_schema",
                    CLAUDE_PROJECTS_JSONL_RAW_ARTIFACT_ID_SCHEMA,
                ),
            },
        }
        raw_path = _claude_projects_jsonl_raw_artifact_path(
            str(candidate.get("session_id") or ""),
            str(candidate.get("canonical_window_id") or ""),
            raw_artifact_id,
        )
        candidate["source_refs"] = {
            **(candidate.get("source_refs", {}) if isinstance(candidate.get("source_refs"), dict) else {}),
            "raw_artifact_id": raw_artifact_id,
            "raw_artifact_id_schema": candidate.get(
                "raw_artifact_id_schema",
                CLAUDE_PROJECTS_JSONL_RAW_ARTIFACT_ID_SCHEMA,
            ),
            "raw_session_path": str(raw_path),
        }
        if not source_path.exists():
            items.append({
                "session_id": candidate.get("session_id", ""),
                "raw_artifact_id": candidate.get("raw_artifact_id", ""),
                "raw_path": str(raw_path),
                "status": "source_missing",
                "records_written": 0,
            })
            continue
        try:
            source_size = source_path.stat().st_size
            raw_size = raw_path.stat().st_size if raw_path.exists() else 0
        except OSError:
            items.append({
                "session_id": candidate.get("session_id", ""),
                "raw_artifact_id": candidate.get("raw_artifact_id", ""),
                "raw_path": str(raw_path),
                "status": "stat_error",
                "records_written": 0,
            })
            continue
        overwrite = raw_size > source_size
        offset = 0 if overwrite else raw_size
        if raw_size == source_size and raw_path.exists():
            _write_claude_projects_jsonl_meta(candidate, raw_path, source_path, source_size)
            if _candidate_has_complete_conversation(candidate) and not current_window_registered:
                binding = _register_current_window_for_candidate(candidate, raw_path)
                if binding.get("ok"):
                    window_bindings.append(binding)
                    current_window_registered = True
            elif not _candidate_has_complete_conversation(candidate):
                candidate_id = str(candidate.get("candidate_id") or "")
                if candidate_id:
                    window_binding_skipped_candidate_ids.append(candidate_id)
            items.append({
                "session_id": candidate.get("session_id", ""),
                "raw_artifact_id": candidate.get("raw_artifact_id", ""),
                "raw_path": str(raw_path),
                "status": "up_to_date",
                "records_written": 0,
            })
            continue
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        line_count = 0
        mode = "wb" if overwrite else "ab"
        try:
            with source_path.open("rb") as src, raw_path.open(mode) as dst:
                src.seek(offset)
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    bytes_written += len(chunk)
                    line_count += chunk.count(b"\n")
        except OSError:
            items.append({
                "session_id": candidate.get("session_id", ""),
                "raw_artifact_id": candidate.get("raw_artifact_id", ""),
                "raw_path": str(raw_path),
                "status": "copy_error",
                "records_written": 0,
            })
            continue
        if bytes_written:
            records_written += max(1, line_count)
            sessions_written += 1
            written_paths.append(str(raw_path))
        _write_claude_projects_jsonl_meta(candidate, raw_path, source_path, source_size)
        if raw_path.exists() and not current_window_registered:
            if _candidate_has_complete_conversation(candidate):
                binding = _register_current_window_for_candidate(candidate, raw_path)
                if binding.get("ok"):
                    window_bindings.append(binding)
                    current_window_registered = True
            else:
                candidate_id = str(candidate.get("candidate_id") or "")
                if candidate_id:
                    window_binding_skipped_candidate_ids.append(candidate_id)
        items.append({
            "session_id": candidate.get("session_id", ""),
            "raw_artifact_id": candidate.get("raw_artifact_id", ""),
            "raw_path": str(raw_path),
            "status": "rewritten" if overwrite else "appended",
            "bytes_written": bytes_written,
            "records_written": max(1, line_count) if bytes_written else 0,
            "offset": source_size,
        })
    return {
        "sessions_written": sessions_written,
        "records_written": records_written,
        "window_bindings_registered": len(window_bindings),
        "window_bindings": window_bindings,
        "window_bindings_skipped_incomplete": len(window_binding_skipped_candidate_ids),
        "window_binding_skipped_candidate_ids": window_binding_skipped_candidate_ids,
        "raw_paths": written_paths,
        "raw_paths_public": [_public_path_label(path) for path in written_paths],
        "items": items,
        "native_artifact_format": CLAUDE_PROJECTS_JSONL_RAW_FORMAT,
    }


def _append_local_relay_projects_jsonl_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Backward-compatible alias for older internal callers."""
    return _append_claude_projects_jsonl_candidates(candidates)


def _public_candidate(candidate: dict[str, Any], include_excerpt: bool = False, include_messages: bool = False) -> dict[str, Any]:
    result = {
        "candidate_id": candidate.get("candidate_id", ""),
        "candidate_kind": candidate.get("candidate_kind", ""),
        "raw_ingest_strategy": candidate.get("raw_ingest_strategy", ""),
        "conversation_id": candidate.get("conversation_id", ""),
        "session_id": candidate.get("session_id", ""),
        "raw_artifact_id": candidate.get("raw_artifact_id", ""),
        "raw_artifact_id_schema": candidate.get("raw_artifact_id_schema", ""),
        "title": candidate.get("title", ""),
        "message_count": candidate.get("message_count", 0),
        "roles": candidate.get("roles", []),
        "source_path": candidate.get("source_path_public", _public_path_label(candidate.get("source_path", ""))),
        "artifact_type": candidate.get("artifact_type", ""),
        "store_path": candidate.get("store_path_public", _public_path_label(candidate.get("store_path", ""))),
        "candidate_hash": candidate.get("candidate_hash", ""),
        "source_surface": candidate.get("source_refs", {}).get("source_surface", ""),
        "conversation_origin": candidate.get("conversation_origin") or candidate.get("source_refs", {}).get("conversation_origin", ""),
        "runtime_consumer": candidate.get("runtime_consumer") or candidate.get("source_refs", {}).get("runtime_consumer", ""),
        "body_storage_owner": candidate.get("body_storage_owner") or candidate.get("source_refs", {}).get("body_storage_owner", ""),
        "source_refs": {
            **candidate.get("source_refs", {}),
            "source_path": _public_path_label(candidate.get("source_refs", {}).get("source_path", "")),
            "raw_session_path": _public_path_label(candidate.get("source_refs", {}).get("raw_session_path", "")),
        },
    }
    if include_excerpt:
        excerpts = []
        for message in candidate.get("messages", [])[:3]:
            text = str(message.get("content", ""))
            excerpts.append({
                "role": message.get("role", "unknown"),
                "text": text[:300],
                "truncated": len(text) > 300,
            })
        result["message_excerpts"] = excerpts
    if include_messages:
        result["messages"] = candidate.get("messages", [])
    return result


def _candidate_has_complete_conversation(candidate: dict[str, Any]) -> bool:
    return is_complete_conversation_roles(candidate.get("roles") or [])


def _candidate_capture_diagnostic(candidates: list[dict[str, Any]], stats: dict[str, Any]) -> dict[str, Any]:
    complete_candidates = [
        candidate for candidate in candidates
        if _candidate_has_complete_conversation(candidate)
    ]
    user_only_candidates = [
        candidate for candidate in candidates
        if "user" in set(candidate.get("roles") or [])
        and "assistant" not in set(candidate.get("roles") or [])
    ]
    assistant_only_candidates = [
        candidate for candidate in candidates
        if "assistant" in set(candidate.get("roles") or [])
        and "user" not in set(candidate.get("roles") or [])
    ]
    if complete_candidates:
        status = "complete_conversation_candidates_verified"
        reason = "at_least_one_candidate_contains_user_and_assistant_turns"
        assistant_reply_persistence = "verified"
        current_window_binding_status = "registerable_after_apply"
    else:
        status = "complete_conversation_source_not_verified"
        reason = "no_complete_user_assistant_conversation_candidate_found"
        assistant_reply_persistence = "unverified"
        current_window_binding_status = "not_registerable_without_complete_candidate"
    return {
        "status": status,
        "reason": reason,
        "tiandao_conversation_evidence_contract": TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
        "conversation_capture_verdict": conversation_capture_verdict(
            sorted({role for candidate in candidates for role in (candidate.get("roles") or [])}),
            candidate_count=len(candidates),
        ),
        "candidate_count": len(candidates),
        "complete_candidate_count": len(complete_candidates),
        "incomplete_candidate_count": max(0, len(candidates) - len(complete_candidates)),
        "user_only_candidate_count": len(user_only_candidates),
        "assistant_only_candidate_count": len(assistant_only_candidates),
        "assistant_reply_persistence": assistant_reply_persistence,
        "current_window_binding_status": current_window_binding_status,
        "current_window_binding_registered": False,
        "not_no_memory": len(complete_candidates) == 0,
        "stores_scanned": {
            "artifacts_scanned": int(stats.get("artifacts_scanned") or 0),
            "files_scanned": int(stats.get("files_scanned") or 0),
            "json_objects_scanned": int(stats.get("json_objects_scanned") or 0),
            "parse_errors": int(stats.get("parse_errors") or 0),
            "skipped_large_files": int(stats.get("skipped_large_files") or 0),
        },
        "notes": [
            "This diagnostic is about verified local Claude Desktop conversation-body persistence, not MCP recall availability.",
            "No complete user+assistant candidate means the parser did not verify local assistant-reply persistence; keep it as a partial source instead of promoting it to complete conversation memory.",
        ],
    }


def conversation_body_probe(limit: int = 20, file_limit: int = 80) -> dict[str, Any]:
    """Return a redacted local-body readiness probe for status surfaces.

    This intentionally exposes only counts and verification state. It does not
    return message text, raw excerpts, or candidate source paths.
    """
    try:
        safe_limit = max(1, min(int(limit or 20), 100))
        safe_file_limit = max(1, min(int(file_limit or 80), 500))
        candidates, stats = _scan_authorized_candidates(limit=safe_limit, file_limit=safe_file_limit)
        diagnostic = _candidate_capture_diagnostic(candidates, stats)
    except Exception as exc:
        return {
            "ok": False,
            "source_system": SOURCE_SYSTEM,
            "probe_status": "error",
            "error": f"{type(exc).__name__}:{str(exc)[:160]}",
            "raw_excerpt_returned": False,
            "message_text_returned": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }

    complete = int(diagnostic.get("complete_candidate_count") or 0)
    user_only = int(diagnostic.get("user_only_candidate_count") or 0)
    assistant_only = int(diagnostic.get("assistant_only_candidate_count") or 0)
    candidate_count = int(diagnostic.get("candidate_count") or 0)
    if complete:
        raw_body_readiness = "complete_conversation_verified"
    elif candidate_count:
        raw_body_readiness = "partial_fragments_only"
    else:
        raw_body_readiness = "no_conversation_body_candidate_found"

    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "probe_status": diagnostic.get("status"),
        "raw_body_readiness": raw_body_readiness,
        "candidate_count": candidate_count,
        "complete_conversation_candidate_count": complete,
        "user_only_candidate_count": user_only,
        "assistant_only_candidate_count": assistant_only,
        "assistant_reply_persistence": diagnostic.get("assistant_reply_persistence"),
        "current_window_memory_registerable": bool(complete),
        "current_window_binding_status": diagnostic.get("current_window_binding_status"),
        "conversation_capture_verdict": diagnostic.get("conversation_capture_verdict", {}),
        "stores_scanned": diagnostic.get("stores_scanned", {}),
        "raw_excerpt_returned": False,
        "message_text_returned": False,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "notes": [
            "This probe verifies whether local Claude Desktop stores expose complete user+assistant conversation bodies.",
            "MCP/skill readiness is separate; a ready consumer connection does not prove Claude Desktop raw-body capture.",
            "User-only or assistant-only fragments are kept as evidence candidates and must not register current-window memory.",
        ],
    }


def surface_summary(limit: int = 20) -> dict[str, Any]:
    root = resolve_claude_home()
    artifacts = discover_artifacts(limit=limit)
    body_probe = conversation_body_probe(limit=limit, file_limit=80)
    cowork_candidates, cowork_stats = _cowork_jsonl_candidates(limit=limit)
    code_reference = claude_projects_jsonl_reference(limit=limit, public=True)
    chat_store_artifacts = [
        item for item in artifacts
        if item.get("artifact_type") in CHAT_BROWSER_STORE_ARTIFACT_TYPES
    ]
    cowork_sessions = discover_cowork_sessions(root, limit=limit)
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "surface_contract": "claude_desktop_three_surfaces.v1",
        "source_collection": "claude_all",
        "collection_does_not_imply_shared_platform_memory": True,
        "surfaces": {
            "chat": {
                "source_surface": SURFACE_CHAT,
                "label": "Claude.ai Chat",
                "native_url_prefix": "claude.ai/chat/",
                "canonical_store": "anthropic_cloud",
                "desktop_local_role": "browser_cache_and_local_state",
                "local_artifact_count": len(chat_store_artifacts),
                "complete_conversation_candidate_count": int(body_probe.get("complete_conversation_candidate_count") or 0),
                "raw_body_readiness": body_probe.get("raw_body_readiness", ""),
                "current_window_memory_registerable": bool(body_probe.get("current_window_memory_registerable")),
                "notes": [
                    "Chat mode is the claude.ai web-chat surface inside Claude Desktop.",
                    "Local IndexedDB/blob evidence can be monitored, but it is not the canonical save path.",
                ],
            },
            "cowork": {
                "source_surface": SURFACE_COWORK,
                "label": "Claude Desktop Cowork",
                "native_root": _public_path_label(_cowork_sessions_root(root)),
                "session_metadata_count": len(cowork_sessions),
                "jsonl_candidate_count": int(cowork_stats.get("cowork_jsonl_candidate_count") or 0),
                "complete_conversation_candidate_count": int(cowork_stats.get("cowork_jsonl_complete_candidate_count") or 0),
                "raw_body_readiness": (
                    "complete_conversation_verified"
                    if int(cowork_stats.get("cowork_jsonl_complete_candidate_count") or 0)
                    else "no_conversation_body_candidate_found"
                ),
                "latest": [
                    {
                        "session_id": item.get("session_id", ""),
                        "desktop_session_id": item.get("desktop_session_id", ""),
                        "title": item.get("title", ""),
                        "source_path": item.get("source_path_public", _public_path_label(item.get("source_path", ""))),
                        "artifact_type": item.get("artifact_type", ""),
                        "roles": item.get("roles", []),
                    }
                    for item in cowork_candidates[: min(5, len(cowork_candidates))]
                ],
            },
            "code": {
                "source_surface": SURFACE_CODE_OR_AGENT,
                "label": "Claude Desktop Code",
                "native_root": code_reference.get("provider_source_root", ""),
                "provider_source_glob": code_reference.get("provider_source_glob", "projects/**/*.jsonl"),
                "desktop_linked_session_count": int(code_reference.get("desktop_linked_session_count") or 0),
                "complete_conversation_candidate_count": int(code_reference.get("desktop_linked_complete_conversation_count") or 0),
                "raw_body_readiness": (
                    "complete_conversation_verified"
                    if int(code_reference.get("desktop_linked_complete_conversation_count") or 0)
                    else "no_conversation_body_candidate_found"
                ),
                "latest": code_reference.get("latest_desktop_linked", []),
                "notes": [
                    "Code mode maps the desktop local session to a .claude/projects JSONL body file.",
                    "The desktop claude-code-sessions JSON is metadata only.",
                ],
            },
        },
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
    }


def raw_ingest_dry_run(body: dict[str, Any] | None = None, public: bool = True) -> dict[str, Any]:
    body = body or {}
    limit = max(1, min(int(body.get("limit") or 20), 100))
    include_excerpt = bool(body.get("include_excerpt"))
    if not _is_authorized_parser(body):
        policy = parser_gate_policy()
        return {
            "ok": False,
            "source_system": SOURCE_SYSTEM,
            "dry_run": True,
            "blocked": True,
            "error": "authorized_parser_required",
            "missing_authorization": policy["authorization_required"],
            "parser_gate": policy,
            "candidate_count": 0,
            "candidates": [],
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }
    candidates, stats = _scan_authorized_candidates(limit=limit)
    cowork_candidates, cowork_stats = _cowork_jsonl_candidates(limit=limit)
    claude_projects_candidates, claude_projects_stats = _claude_desktop_linked_project_candidates(limit=limit)
    candidates = candidates + cowork_candidates + claude_projects_candidates
    stats = {**stats, **cowork_stats, **claude_projects_stats}
    capture_diagnostic = _candidate_capture_diagnostic(candidates, stats)
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "dry_run": True,
        "blocked": False,
        "parser_kind": "authorized_local_store_text_fragment_parser_plus_cowork_jsonl_plus_code_projects_jsonl",
        "parser_schema_version": RAW_INGEST_SCHEMA_VERSION,
        "candidate_count": len(candidates),
        "current_window_capture_status": capture_diagnostic["status"],
        "assistant_reply_persistence": capture_diagnostic["assistant_reply_persistence"],
        "current_window_binding_status": capture_diagnostic["current_window_binding_status"],
        "capture_diagnostic": capture_diagnostic,
        "stats": stats,
        "candidates": [
            _public_candidate(candidate, include_excerpt=include_excerpt, include_messages=not public)
            for candidate in candidates
        ],
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "notes": [
            "Dry-run parsed Claude Desktop local stores after explicit parser authorization.",
            "Cowork local-agent JSONL candidates are included as a separate source surface when present.",
            "Desktop-linked Claude projects JSONL candidates are included when present; standalone Claude Code CLI sessions are not imported here.",
            "No raw records were written. Use the apply endpoint with write authorization to ingest into Yifanchen raw.",
        ],
    }


def ingest_authorized_raw(body: dict[str, Any] | None = None, public: bool = True) -> dict[str, Any]:
    body = body or {}
    if not _apply_authorized(body):
        dry = raw_ingest_dry_run(body, public=public)
        dry.update({
            "ok": False,
            "blocked": True,
            "error": "raw_ingest_apply_authorization_required",
            "missing_authorization": [
                "apply",
                "confirm_authorized_parser",
                "confirm_user_owns_claude_desktop_data",
                "confirm_write_yifanchen_raw",
                "confirm_no_claude_platform_write",
            ],
            "memory_write_performed": False,
            "platform_write_performed": False,
        })
        return dry
    limit = max(1, min(int(body.get("limit") or 20), 100))
    candidates, stats = _scan_authorized_candidates(limit=limit)
    cowork_candidates, cowork_stats = _cowork_jsonl_candidates(limit=limit)
    claude_projects_candidates, claude_projects_stats = _claude_desktop_linked_project_candidates(limit=limit)
    stats = {**stats, **cowork_stats, **claude_projects_stats}
    write_result = _append_raw_candidates(candidates)
    cowork_write_result = _append_native_jsonl_mirror_candidates(
        cowork_candidates,
        default_native_format=COWORK_PROJECTS_JSONL_RAW_FORMAT,
    )
    claude_projects_write_result = _append_claude_projects_jsonl_candidates(claude_projects_candidates)
    all_candidates = candidates + cowork_candidates + claude_projects_candidates
    combined_write_result = {
        **write_result,
        "sessions_written": (
            int(write_result.get("sessions_written", 0) or 0)
            + int(cowork_write_result.get("sessions_written", 0) or 0)
            + int(claude_projects_write_result.get("sessions_written", 0) or 0)
        ),
        "records_written": (
            int(write_result.get("records_written", 0) or 0)
            + int(cowork_write_result.get("records_written", 0) or 0)
            + int(claude_projects_write_result.get("records_written", 0) or 0)
        ),
        "window_bindings_registered": (
            int(write_result.get("window_bindings_registered", 0) or 0)
            + int(cowork_write_result.get("window_bindings_registered", 0) or 0)
            + int(claude_projects_write_result.get("window_bindings_registered", 0) or 0)
        ),
        "window_bindings": (
            (write_result.get("window_bindings", []) or [])
            + (cowork_write_result.get("window_bindings", []) or [])
            + (claude_projects_write_result.get("window_bindings", []) or [])
        ),
        "window_bindings_skipped_incomplete": (
            int(write_result.get("window_bindings_skipped_incomplete", 0) or 0)
            + int(cowork_write_result.get("window_bindings_skipped_incomplete", 0) or 0)
            + int(claude_projects_write_result.get("window_bindings_skipped_incomplete", 0) or 0)
        ),
        "window_binding_skipped_candidate_ids": (
            (write_result.get("window_binding_skipped_candidate_ids", []) or [])
            + (cowork_write_result.get("window_binding_skipped_candidate_ids", []) or [])
            + (claude_projects_write_result.get("window_binding_skipped_candidate_ids", []) or [])
        ),
        "raw_paths": (
            (write_result.get("raw_paths", []) or [])
            + (cowork_write_result.get("raw_paths", []) or [])
            + (claude_projects_write_result.get("raw_paths", []) or [])
        ),
        "raw_paths_public": (
            (write_result.get("raw_paths_public", []) or [])
            + (cowork_write_result.get("raw_paths_public", []) or [])
            + (claude_projects_write_result.get("raw_paths_public", []) or [])
        ),
        "cowork_jsonl_write": cowork_write_result,
        "claude_projects_jsonl_write": claude_projects_write_result,
    }
    capture_diagnostic = _candidate_capture_diagnostic(all_candidates, stats)
    capture_diagnostic["current_window_binding_registered"] = bool(
        combined_write_result.get("window_bindings_registered")
    )
    if combined_write_result.get("window_bindings_registered"):
        capture_diagnostic["current_window_binding_status"] = "registered"
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "dry_run": False,
        "blocked": False,
        "parser_kind": "authorized_local_store_text_fragment_parser_plus_cowork_jsonl_plus_code_projects_jsonl",
        "parser_schema_version": RAW_INGEST_SCHEMA_VERSION,
        "candidate_count": len(all_candidates),
        "current_window_capture_status": capture_diagnostic["status"],
        "assistant_reply_persistence": capture_diagnostic["assistant_reply_persistence"],
        "current_window_binding_status": capture_diagnostic["current_window_binding_status"],
        "capture_diagnostic": capture_diagnostic,
        "stats": stats,
        "write_performed": bool(combined_write_result.get("records_written")),
        "platform_write_performed": False,
        "memory_write_performed": bool(combined_write_result.get("records_written")),
        "raw_write": {
            **combined_write_result,
            "raw_paths": [
                _public_path_label(path) if public else path
                for path in combined_write_result.get("raw_paths", [])
            ],
        },
        "candidates": [
            _public_candidate(candidate, include_excerpt=bool(body.get("include_excerpt")), include_messages=not public)
            for candidate in all_candidates
        ],
        "notes": [
            "Wrote only Yifanchen raw JSONL records.",
            "No Claude Desktop config, native chat store, cookie, token, MCP config, or skill manifest was written.",
            "Cowork local-agent JSONL records are mirrored as a distinct source surface.",
            "Desktop-linked Claude projects JSONL records are mirrored only when they carry Claude Desktop entrypoint or metadata linkage.",
            "Standalone Claude Code CLI data remains outside this parser.",
        ],
    }


def _artifact_sync_item(artifact: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(artifact.get("source_path") or "")).expanduser()
    exists = path.exists()
    size = None
    mtime = ""
    inode = None
    if exists:
        try:
            st = path.stat()
            size = st.st_size
            mtime = datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            inode = getattr(st, "st_ino", None)
        except OSError:
            pass
    attribution = attribution_from_artifact(artifact)
    item = {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": artifact.get("artifact_type", ""),
        "sync_role": artifact.get("sync_role", "primary" if artifact.get("artifact_type") in LIVE_SYNC_ARTIFACT_TYPES else "unknown"),
        "sync_strategy": artifact.get("sync_strategy", "metadata_probe"),
        "source_path": artifact.get("source_path", ""),
        "source_path_public": _public_path_label(artifact.get("source_path", "")),
        "exists": exists,
        "size_bytes": size,
        "mtime": mtime,
        "inode": inode,
        "parser_required": artifact.get("content_read_supported_now") == "parser_gate_required",
        "content_read_supported_now": artifact.get("content_read_supported_now", False),
        "capture_classification": artifact.get("capture_classification", "EXTERNAL"),
        "write_performed": False,
        "platform_write_performed": False,
        **attribution,
        "source_refs": source_refs_from_artifact(artifact),
    }
    for key in (
        "relay_proxy_request_summary",
        "note",
    ):
        if key in artifact:
            item[key] = artifact[key]
    return item


def _dir_metadata_snapshot(path: Path, max_files: int = 2000, max_depth: int = 4) -> dict[str, Any]:
    file_count = 0
    dir_count = 0
    total_bytes = 0
    latest_mtime = 0.0
    sampled_files: list[dict[str, Any]] = []
    stack: list[tuple[Path, int]] = [(path, 0)]
    truncated = False
    while stack:
        current, depth = stack.pop()
        if current.name in SKIP_DIR_NAMES and current != path:
            continue
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name in SKIP_DIR_NAMES:
                continue
            try:
                st = child.stat()
            except OSError:
                continue
            latest_mtime = max(latest_mtime, st.st_mtime)
            if child.is_dir():
                dir_count += 1
                if depth + 1 <= max_depth:
                    stack.append((child, depth + 1))
                continue
            file_count += 1
            total_bytes += st.st_size
            if len(sampled_files) < 80:
                try:
                    rel = str(child.relative_to(path))
                except ValueError:
                    rel = child.name
                sampled_files.append({
                    "relative_path": rel,
                    "size_bytes": st.st_size,
                    "mtime": datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "suffix": child.suffix.lower(),
                })
            if file_count >= max_files:
                truncated = True
                stack.clear()
                break
    sampled_files.sort(key=lambda item: (item.get("relative_path", ""), item.get("mtime", "")))
    fingerprint_basis = {
        "file_count": file_count,
        "dir_count": dir_count,
        "total_bytes": total_bytes,
        "latest_mtime": latest_mtime,
        "sampled_files": sampled_files,
        "truncated": truncated,
    }
    digest = hashlib.sha256(json.dumps(fingerprint_basis, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {
        "file_count": file_count,
        "dir_count": dir_count,
        "total_bytes": total_bytes,
        "latest_mtime": datetime.fromtimestamp(latest_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if latest_mtime else "",
        "sampled_files": sampled_files,
        "truncated": truncated,
        "metadata_fingerprint": digest,
    }


def _sync_state_item(sync_item: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(sync_item.get("source_path") or "")).expanduser()
    exists = path.exists()
    item: dict[str, Any] = {
        "key": f"{sync_item.get('artifact_type', '')}:{str(path)}",
        "source_system": SOURCE_SYSTEM,
        "artifact_type": sync_item.get("artifact_type", ""),
        "sync_role": sync_item.get("sync_role", ""),
        "sync_strategy": sync_item.get("sync_strategy", ""),
        "source_path": str(path),
        "source_path_public": _public_path_label(path),
        "exists": exists,
        "parser_required": bool(sync_item.get("parser_required")),
        "content_read_supported_now": sync_item.get("content_read_supported_now", False),
        "capture_classification": sync_item.get("capture_classification", "EXTERNAL"),
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "source_refs": sync_item.get("source_refs", {}),
    }
    for key in (
        "source_family",
        "source_collection",
        "collection_label",
        "collection_mode",
        "collection_does_not_imply_shared_platform_memory",
        "attribution_mode",
        "source_surface",
        "source_systems",
        "co_source_systems",
        "storage_owner",
        "body_storage_owner",
        "conversation_origin",
        "runtime_consumer",
        "desktop_installer_includes_cli",
        "cli_installation_boundary",
        "desktop_cli_relationship",
        "user_installed_cli_independent",
        "user_installed_path_cli_required",
        "desktop_managed_runtime_detected",
        "desktop_managed_runtime_owner",
        "desktop_managed_runtime_policy",
        "desktop_managed_runtime_is_user_installed_cli",
        "desktop_metadata_is_conversation_body",
        "desktop_code_session_policy",
        "relay_owner",
        "artifact_role",
        "visibility_boundary",
        "cross_surface_memory_shared",
        "official_relay_interop",
        "surface_readability",
        "attribution_chain",
        "attribution_note",
        "boundary_note",
    ):
        if key in sync_item:
            item[key] = sync_item[key]
    if not exists:
        item["fingerprint"] = "missing"
        return item
    try:
        st = path.stat()
        item["size_bytes"] = st.st_size
        item["mtime"] = datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        item["inode"] = getattr(st, "st_ino", None)
    except OSError:
        item["fingerprint"] = "stat_error"
        return item
    if path.is_dir():
        item["metadata_snapshot"] = _dir_metadata_snapshot(path)
        item["fingerprint"] = item["metadata_snapshot"]["metadata_fingerprint"]
    else:
        basis = {
            "size_bytes": item.get("size_bytes"),
            "mtime": item.get("mtime"),
            "inode": item.get("inode"),
            "sha256": _sha256_small(path),
        }
        item["fingerprint"] = hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()
    return item


def build_sync_state(public: bool = False, apply: bool = False, limit: int = 80) -> dict[str, Any]:
    manifest = build_sync_manifest(public=False, limit=limit)
    primary_items = [_sync_state_item(item) for item in manifest.get("items", [])]
    consumer_items = [_sync_state_item(item) for item in manifest.get("consumer_capability_items", [])]
    related_items = [_sync_state_item(item) for item in manifest.get("related_items", [])]
    previous = _load_sync_state()
    previous_items = previous.get("items_by_key") if isinstance(previous.get("items_by_key"), dict) else {}

    def attach_status(item: dict[str, Any]) -> dict[str, Any]:
        prior = previous_items.get(item["key"]) if isinstance(previous_items, dict) else None
        if not prior:
            status_value = "new"
        elif prior.get("fingerprint") != item.get("fingerprint"):
            status_value = "changed"
        else:
            status_value = "unchanged"
        return {
            **item,
            "sync_status": status_value,
            "previous_fingerprint": prior.get("fingerprint") if isinstance(prior, dict) else "",
        }

    primary_items = [attach_status(item) for item in primary_items]
    consumer_items = [attach_status(item) for item in consumer_items]
    related_items = [attach_status(item) for item in related_items]
    current_keys = {item["key"] for item in primary_items + consumer_items + related_items}
    removed_items = [
        {
            **prior,
            "sync_status": "missing",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }
        for key, prior in previous_items.items()
        if key not in current_keys
    ] if isinstance(previous_items, dict) else []

    status_counts: dict[str, int] = {}
    for item in primary_items + consumer_items + related_items + removed_items:
        status_counts[item.get("sync_status", "unknown")] = status_counts.get(item.get("sync_status", "unknown"), 0) + 1

    state_to_save = {
        "version": SYNC_STATE_VERSION,
        "source_system": SOURCE_SYSTEM,
        "generated_at": ts(),
        "sync_scope": "system_level_local_user_space_memory_sync",
        "primary_sync_mode": "live_local_user_space_sync",
        "export_role": "cold_start_or_backfill_fallback_only",
        "items_by_key": {
            item["key"]: {
                **item,
                "source_path_public": _public_path_label(item.get("source_path", "")),
            }
            for item in primary_items + consumer_items + related_items
        },
        "parser_gates": manifest.get("parser_gates", []),
    }

    wrote_state = False
    if apply:
        _save_sync_state(state_to_save)
        wrote_state = True

    def scrub(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result["source_path"] = result.pop("source_path_public", _public_path_label(result.get("source_path", "")))
        result["key"] = hashlib.sha256(str(result.get("key", "")).encode("utf-8")).hexdigest()[:16]
        if result.get("artifact_type") == LOCAL_RELAY_PROXY_DB_ARTIFACT:
            result["source_path"] = "local_relay_proxy_request_logs_db"
            if isinstance(result.get("relay_proxy_request_summary"), dict):
                result["relay_proxy_request_summary"] = _public_relay_proxy_summary(result["relay_proxy_request_summary"])
        if isinstance(result.get("metadata_snapshot"), dict):
            snapshot = dict(result["metadata_snapshot"])
            sampled = snapshot.pop("sampled_files", [])
            snapshot["sampled_file_count"] = len(sampled) if isinstance(sampled, list) else 0
            result["metadata_snapshot"] = snapshot
        refs = dict(result.get("source_refs", {}))
        refs["source_path"] = _public_path_label(refs.get("source_path", ""))
        if result.get("artifact_type") == LOCAL_RELAY_PROXY_DB_ARTIFACT:
            refs["source_path"] = "local_relay_proxy_request_logs_db"
            refs["canonical_window_id"] = "local_relay_proxy_request_logs_db"
            refs["session_id"] = "local_relay_proxy_request_logs_db"
        result["source_refs"] = refs
        return result

    if public:
        primary_out = [scrub(item) for item in primary_items]
        consumer_out = [scrub(item) for item in consumer_items]
        related_out = [scrub(item) for item in related_items]
        removed_out = [scrub(item) for item in removed_items]
        state_path = _public_path_label(_sync_state_path())
    else:
        primary_out = primary_items
        consumer_out = consumer_items
        related_out = related_items
        removed_out = removed_items
        state_path = str(_sync_state_path())

    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "generated_at": ts(),
        "dry_run": not apply,
        "read_only_source": True,
        "write_performed": wrote_state,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "state_receipt_write_performed": wrote_state,
        "sync_scope": "system_level_local_user_space_memory_sync",
        "primary_sync_mode": "live_local_user_space_sync",
        "export_role": "cold_start_or_backfill_fallback_only",
        "state_path": state_path,
        "previous_state_loaded": bool(previous),
        "primary_item_count": len(primary_items),
        "consumer_capability_item_count": len(consumer_items),
        "related_item_count": len(related_items),
        "removed_item_count": len(removed_items),
        "status_counts": status_counts,
        "items": primary_out,
        "consumer_capability_items": consumer_out,
        "related_items": related_out,
        "removed_items": removed_out,
        "parser_gates": manifest.get("parser_gates", []),
        "attribution_policy": {
            "dual_attribution_supported": True,
            "dual_attribution_does_not_mean_interop": True,
            "source_collection": "claude_all",
            "source_collection_mode": "aggregate_all_claude_surfaces_preserve_attribution",
            "collection_does_not_imply_shared_platform_memory": True,
            "storage_owner_field": "storage_owner",
            "conversation_origin_field": "conversation_origin",
            "runtime_consumer_field": "runtime_consumer",
            "relay_owner_field": "relay_owner",
            "body_storage_owner_field": "body_storage_owner",
            "desktop_managed_runtime_field": "desktop_managed_runtime_detected",
            "visibility_boundary_field": "visibility_boundary",
            "windows_claude_runtime_note": (
                "Claude Desktop can store code-session metadata and manage a local Claude Code runtime under its app data. "
                "That metadata is not the conversation body, and the Desktop-managed runtime is not a user-installed PATH CLI."
            ),
            "desktop_installer_includes_cli": CLAUDE_DESKTOP_INSTALLER_INCLUDES_CLI,
            "cli_installation_boundary": CLAUDE_CLI_INSTALLATION_BOUNDARY,
            "desktop_cli_relationship": CLAUDE_DESKTOP_CLI_RELATIONSHIP,
            "desktop_managed_runtime_policy": CLAUDE_DESKTOP_MANAGED_RUNTIME_POLICY,
            "desktop_code_session_policy": CLAUDE_DESKTOP_CODE_SESSION_POLICY,
        },
        "notes": [
            "This is the system-level local sync state for Claude Desktop user-space data.",
            "Export archives are not part of the primary sync state; they remain cold-start/backfill fallback evidence.",
            "Content-bearing stores are tracked by fingerprint and metadata until an explicit parser gate is authorized.",
            "Related Claude Code artifacts keep dual attribution instead of being flattened into Claude Desktop.",
            "A Desktop-managed Claude Code runtime is distinct from a user-installed PATH CLI.",
            "No Claude config, Claude memory, cookies, tokens, or sessions are written.",
        ],
    }


def build_sync_manifest(public: bool = False, limit: int = 80) -> dict[str, Any]:
    artifacts = discover_artifacts(limit=limit)
    live_items = [
        _artifact_sync_item(item)
        for item in artifacts
        if item.get("artifact_type") in LIVE_SYNC_ARTIFACT_TYPES
        and item.get("sync_role") != "consumer_capability"
    ]
    consumer_items = [
        _artifact_sync_item(item)
        for item in artifacts
        if item.get("sync_role") == "consumer_capability"
    ]
    export_items = [
        _artifact_sync_item(item)
        for item in artifacts
        if item.get("artifact_type") in EXPORT_ARTIFACT_TYPES
    ]
    related_items = [
        _artifact_sync_item(item)
        for item in artifacts
        if item.get("artifact_type") not in LIVE_SYNC_ARTIFACT_TYPES | EXPORT_ARTIFACT_TYPES
    ]
    if public:
        def scrub(item: dict[str, Any]) -> dict[str, Any]:
            result = dict(item)
            result["source_path"] = result.pop("source_path_public", "")
            if result.get("artifact_type") == LOCAL_RELAY_PROXY_DB_ARTIFACT:
                result["source_path"] = "local_relay_proxy_request_logs_db"
                if isinstance(result.get("relay_proxy_request_summary"), dict):
                    result["relay_proxy_request_summary"] = _public_relay_proxy_summary(result["relay_proxy_request_summary"])
            refs = dict(result.get("source_refs", {}))
            refs["source_path"] = _public_path_label(refs.get("source_path", ""))
            if result.get("artifact_type") == LOCAL_RELAY_PROXY_DB_ARTIFACT:
                refs["source_path"] = "local_relay_proxy_request_logs_db"
                refs["canonical_window_id"] = "local_relay_proxy_request_logs_db"
                refs["session_id"] = "local_relay_proxy_request_logs_db"
            result["source_refs"] = refs
            return result
        live_items = [scrub(item) for item in live_items]
        consumer_items = [scrub(item) for item in consumer_items]
        export_items = [scrub(item) for item in export_items]
        related_items = [scrub(item) for item in related_items]
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "generated_at": ts(),
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "primary_sync_mode": "live_local_user_space_sync",
        "export_role": "cold_start_or_backfill_fallback_only",
        "manifest_kind": "claude_desktop_sync_manifest",
        "live_item_count": len(live_items),
        "consumer_capability_item_count": len(consumer_items),
        "export_fallback_count": len(export_items),
        "related_item_count": len(related_items),
        "items": live_items,
        "consumer_capability_items": consumer_items,
        "export_fallback_items": export_items,
        "related_items": related_items,
        "parser_gates": [
            {
                "artifact_types": [
                    "claude_desktop_indexeddb_leveldb_dir",
                    "claude_desktop_indexeddb_blob_dir",
                    "claude_desktop_local_storage_leveldb_dir",
                    "claude_desktop_session_storage_dir",
                ],
                "status": "not_enabled",
                "reason": "content-bearing browser stores need an explicit authorized parser before raw ingestion",
            }
        ],
        "attribution_policy": {
            "dual_attribution_supported": True,
            "dual_attribution_does_not_mean_interop": True,
            "source_collection": "claude_all",
            "source_collection_mode": "aggregate_all_claude_surfaces_preserve_attribution",
            "collection_does_not_imply_shared_platform_memory": True,
            "storage_owner_field": "storage_owner",
            "conversation_origin_field": "conversation_origin",
            "runtime_consumer_field": "runtime_consumer",
            "relay_owner_field": "relay_owner",
            "body_storage_owner_field": "body_storage_owner",
            "desktop_managed_runtime_field": "desktop_managed_runtime_detected",
            "visibility_boundary_field": "visibility_boundary",
            "windows_claude_runtime_note": (
                "Claude Desktop can store code-session metadata and manage a local Claude Code runtime under its app data. "
                "That metadata is not the conversation body, and the Desktop-managed runtime is not a user-installed PATH CLI."
            ),
            "desktop_installer_includes_cli": CLAUDE_DESKTOP_INSTALLER_INCLUDES_CLI,
            "cli_installation_boundary": CLAUDE_CLI_INSTALLATION_BOUNDARY,
            "desktop_cli_relationship": CLAUDE_DESKTOP_CLI_RELATIONSHIP,
            "desktop_managed_runtime_policy": CLAUDE_DESKTOP_MANAGED_RUNTIME_POLICY,
            "desktop_code_session_policy": CLAUDE_DESKTOP_CODE_SESSION_POLICY,
        },
        "notes": [
            "Claude Desktop is a first-class source system distinct from Claude Code CLI.",
            "Claude Desktop may manage a local Claude Code runtime, while a user-installed PATH CLI remains independent.",
            "Claude projects JSONL can contain Desktop-entrypoint/managed Claude Code body evidence; local relay metadata is only a non-body reference when present.",
            "Related Claude Code artifacts keep both Claude Desktop storage ownership and Claude Code runtime/body attribution.",
            "The normal path is local sync from Claude Desktop app data, not repeated manual exports.",
            "Skill detection is diagnostic only; actual recall requires a Yifanchen MCP/Desktop Extension tool connection.",
            "Export archives are only fallback/backfill evidence.",
            "No Claude config, platform memory, cookies, tokens, or sessions are written.",
        ],
    }


def status() -> dict[str, Any]:
    root = resolve_claude_home()
    config, config_parse_status = _load_config_result(root)
    artifacts = discover_artifacts(limit=20)
    summary = config_summary(config)
    consumer = consumer_status(config, root)
    body_probe = conversation_body_probe(limit=20, file_limit=80)
    claude_projects_reference = claude_projects_jsonl_reference(limit=20, public=True)
    surfaces = surface_summary(limit=20)
    indexeddb_exists = (root / "IndexedDB").exists()
    export_count = sum(1 for item in artifacts if item.get("artifact_type") == "claude_data_export_candidate")
    live_count = sum(1 for item in artifacts if item.get("artifact_type") in LIVE_SYNC_ARTIFACT_TYPES)
    local_relay_proxy_artifacts = [
        item for item in artifacts
        if item.get("artifact_type") == LOCAL_RELAY_PROXY_DB_ARTIFACT
    ]
    local_relay_gateway_summary = (
        local_relay_proxy_artifacts[0].get("relay_proxy_request_summary", {})
        if local_relay_proxy_artifacts
        else {}
    )
    relay_gateway_summary_public = _public_relay_proxy_summary(local_relay_gateway_summary)
    latest = sorted(artifacts[:], key=lambda item: (_artifact_type_rank(item.get("artifact_type", "")), item.get("filename", "")))
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "status": "detected" if root.exists() else "not_found",
        "desktop_home": _public_path_label(root),
        "config_path": _public_path_label(claude_config_path(root)),
        "reachable": root.exists(),
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_authorized": False,
        "official_capabilities": {
            "chat_search_memory": True,
            "data_export": True,
            "local_mcp_servers": True,
            "desktop_extensions": True,
        },
        "surface_summary": surfaces,
        "primary_sync_mode": "live_local_user_space_sync",
        "export_role": "cold_start_or_backfill_fallback_only",
        "config": {
            "exists": claude_config_path(root).exists(),
            "parse_status": config_parse_status,
            "has_mcp_servers": summary["has_mcp_servers"],
            "mcp_server_names": summary["mcp_server_names"],
            "yifanchen_mcp_detected": summary["yifanchen_mcp_detected"],
            "yifanchen_mcp_server_names": summary["yifanchen_mcp_server_names"],
            "cowork_user_files_path": _public_path_label(summary.get("cowork_user_files_path", "")),
        },
        "consumer_connection": consumer,
        "local_storage": {
            "source_surface": SURFACE_CHAT,
            "surface_label": "Claude.ai Chat browser cache/local state",
            "canonical_store": "anthropic_cloud",
            "desktop_local_role": "browser_cache_and_local_state",
            "indexeddb_detected": indexeddb_exists,
            "indexeddb_content_read_by_default": False,
            "content_parser_gate": "explicit_authorized_parser_required",
            "preferred_raw_source": "live_local_sync_manifest_then_authorized_parser",
            "conversation_body_parser_status": body_probe.get("probe_status"),
            "raw_body_readiness": body_probe.get("raw_body_readiness"),
            "complete_conversation_candidate_count": body_probe.get("complete_conversation_candidate_count", 0),
            "user_only_candidate_count": body_probe.get("user_only_candidate_count", 0),
            "assistant_only_candidate_count": body_probe.get("assistant_only_candidate_count", 0),
            "assistant_reply_persistence": body_probe.get("assistant_reply_persistence"),
            "current_window_memory_registerable": bool(body_probe.get("current_window_memory_registerable")),
            "current_window_binding_status": body_probe.get("current_window_binding_status"),
            "raw_body_probe": body_probe,
        },
        "claude_projects_jsonl_reference": claude_projects_reference,
        "claude_projects_jsonl_desktop_linked_session_count": claude_projects_reference.get("desktop_linked_session_count", 0),
        "claude_projects_jsonl_desktop_linked_complete_conversation_count": claude_projects_reference.get("desktop_linked_complete_conversation_count", 0),
        "claude_projects_jsonl_boundary": claude_projects_reference.get("boundary", ""),
        "conversation_body_probe_endpoint": "/api/v1/source-systems/claude_desktop/conversation-body-probe",
        "raw_body_readiness": body_probe.get("raw_body_readiness"),
        "current_window_memory_registerable": bool(body_probe.get("current_window_memory_registerable")),
        "sync_manifest_endpoint": "/api/v1/source-systems/claude_desktop/sync-manifest",
        "sync_state_endpoint": "/api/v1/source-systems/claude_desktop/sync-state",
        "parser_gate_endpoint": "/api/v1/source-systems/claude_desktop/parser-gate",
        "raw_ingest_dry_run_endpoint": "/api/v1/source-systems/claude_desktop/raw-ingest/dry-run",
        "raw_ingest_endpoint": "/api/v1/source-systems/claude_desktop/raw-ingest",
        "sync_manifest_live_item_count": live_count,
        "export_candidates_count": export_count,
        "relay_gateway_request_log_detected": bool(local_relay_proxy_artifacts),
        "relay_gateway_request_count": int(relay_gateway_summary_public.get("request_count") or 0),
        "relay_gateway_latest_status_code": relay_gateway_summary_public.get("latest_status_code"),
        "relay_gateway_request_summary": relay_gateway_summary_public,
        "relay_gateway_visibility_boundary": (
            "request_metadata_not_chat_body" if local_relay_proxy_artifacts else ""
        ),
        "sync_state": {
            "state_path": _public_path_label(_sync_state_path()),
            "exists": _sync_state_path().exists(),
            "sync_scope": "system_level_local_user_space_memory_sync",
        },
        "attribution_policy": {
            "dual_attribution_supported": True,
            "dual_attribution_does_not_mean_interop": True,
            "source_collection": "claude_all",
            "source_collection_mode": "aggregate_all_claude_surfaces_preserve_attribution",
            "collection_does_not_imply_shared_platform_memory": True,
            "windows_claude_runtime_note": "Related Claude Code artifacts are tracked with storage_owner, body_storage_owner, conversation_origin, runtime_consumer, and desktop_managed_runtime fields.",
            "desktop_installer_includes_cli": CLAUDE_DESKTOP_INSTALLER_INCLUDES_CLI,
            "cli_installation_boundary": CLAUDE_CLI_INSTALLATION_BOUNDARY,
            "desktop_cli_relationship": CLAUDE_DESKTOP_CLI_RELATIONSHIP,
            "desktop_managed_runtime_policy": CLAUDE_DESKTOP_MANAGED_RUNTIME_POLICY,
            "desktop_code_session_policy": CLAUDE_DESKTOP_CODE_SESSION_POLICY,
        },
        "artifact_count_sample": len(artifacts),
        "latest": [public_artifact(item) for item in latest[:5]],
    }


def scan(dry_run: bool = True, public: bool = False, limit: int = 50) -> dict[str, Any]:
    artifacts = discover_artifacts(limit=limit)
    items = [public_artifact(item) if public else item for item in artifacts]
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "dry_run": dry_run,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "discovered": len(items),
        "items": items,
        "notes": [
            "Claude Desktop is listed as a first-class source system.",
            "The default path is live local metadata/store monitoring; content parsers remain gated.",
            "Official export archives are fallback/backfill candidates, not the normal sync path.",
            "Skill detection is diagnostic only; actual recall requires a Yifanchen MCP/Desktop Extension tool connection.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Desktop source-system connector")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--sync-manifest", action="store_true")
    parser.add_argument("--sync-state", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--consumer-status", action="store_true")
    parser.add_argument("--parser-gate", action="store_true")
    parser.add_argument("--conversation-body-probe", action="store_true")
    parser.add_argument("--raw-ingest-dry-run", action="store_true")
    parser.add_argument("--raw-ingest", action="store_true")
    parser.add_argument("--confirm-authorized-parser", action="store_true")
    parser.add_argument("--confirm-user-owns-claude-desktop-data", action="store_true")
    parser.add_argument("--confirm-write-yifanchen-raw", action="store_true")
    parser.add_argument("--confirm-no-claude-platform-write", action="store_true")
    parser.add_argument("--include-excerpt", action="store_true")
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    parser_body = {
        "limit": args.limit,
        "include_excerpt": args.include_excerpt,
        "confirm_authorized_parser": args.confirm_authorized_parser,
        "confirm_user_owns_claude_desktop_data": args.confirm_user_owns_claude_desktop_data,
        "confirm_write_yifanchen_raw": args.confirm_write_yifanchen_raw,
        "confirm_no_claude_platform_write": args.confirm_no_claude_platform_write,
        "apply": args.apply,
    }
    if args.parser_gate:
        payload = parser_gate_policy()
    elif args.conversation_body_probe:
        payload = conversation_body_probe(limit=args.limit)
    elif args.raw_ingest_dry_run:
        payload = raw_ingest_dry_run(parser_body, public=args.public)
    elif args.raw_ingest:
        parser_body["apply"] = True
        payload = ingest_authorized_raw(parser_body, public=args.public)
    elif args.sync_manifest:
        payload = build_sync_manifest(public=args.public, limit=args.limit)
    elif args.sync_state:
        payload = build_sync_state(public=args.public, apply=args.apply, limit=args.limit)
    elif args.consumer_status:
        payload = consumer_status()
    elif args.discover:
        payload: Any = discover_artifacts(limit=args.limit)
        if args.public:
            payload = [public_artifact(item) for item in payload]
    elif args.scan:
        payload = scan(dry_run=True, public=args.public, limit=args.limit)
    else:
        payload = status()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
