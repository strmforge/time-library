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
try:
    from src import claude_desktop_raw_ingest as _raw_ingest
    from src.claude_desktop_raw_ingest import *
except ImportError:
    import claude_desktop_raw_ingest as _raw_ingest
    from claude_desktop_raw_ingest import *

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


def get_claude_desktop_connector_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": "tiandao_claude_desktop_source_connector.v1",
        "zh_name": "Claude Desktop 源系统连接器",
        "en_name": "Claude Desktop Source Connector",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "source_system": SOURCE_SYSTEM,
        "connector_layer": "platform_source_inlet",
        "read_only_by_default": True,
        "write_capable": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "claude_desktop_is_source_inlet_not_time_origin",
        "subcontracts": [
            "tiandao_claude_desktop_raw_ingest_connector.v1",
        ],
    }


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
    time_library_names = [
        name for name in server_names
        if "time_library" in name.lower()
        or "zhiyi" in name.lower()
        or "9851" in server_text
    ]
    prefs = config.get("preferences") if isinstance(config.get("preferences"), dict) else {}
    return {
        "has_config": bool(config),
        "has_mcp_servers": bool(server_names),
        "mcp_server_names": server_names,
        "time_library_mcp_detected": bool(time_library_names),
        "time_library_mcp_server_names": time_library_names,
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
    return any(
        needle in haystack
        for needle in (
            "time library",
            "time-library",
            "time_library",
            "时间图书馆",
            "zhiyi",
            "memcore",
            "知意",
        )
    )


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
                "looks_like_time_library": _manifest_skill_matches(item),
            })
    time_library_skills = [item for item in skills if item.get("looks_like_time_library")]
    return {
        "plugins_detected": len(plugin_items),
        "skills_detected": len(skills),
        "skill_ids": [item.get("skill_id", "") for item in skills][:limit],
        "time_library_skill_detected": bool(time_library_skills),
        "time_library_skill_ids": [item.get("skill_id", "") for item in time_library_skills],
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
    mcp_detected = bool(cfg.get("time_library_mcp_detected"))
    skill_detected = bool(skills.get("time_library_skill_detected"))
    if mcp_detected:
        readiness = "ready_with_mcp"
        likely_rejection_reason = ""
    elif skill_detected:
        readiness = "skill_signal_without_tool_connection"
        likely_rejection_reason = "Claude can see Time Library instructions, but no Time Library MCP/Desktop Extension tool is detected for actual recall."
    else:
        readiness = "not_connected"
        likely_rejection_reason = "No Time Library MCP/Desktop Extension or Time Library skill signal detected in Claude Desktop local data."
    return {
        "consumer": SOURCE_SYSTEM,
        "mcp_detected": mcp_detected,
        "mcp_server_names": cfg.get("time_library_mcp_server_names", []),
        "skill_detected": skill_detected,
        "skill_ids": skills.get("time_library_skill_ids", []),
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
                "Time Library keeps storage ownership and conversation/runtime ownership separate."
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
            note="Claude Desktop local skills plugin directory detected. Used to diagnose whether a Time Library skill signal exists; not conversation memory.",
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
            note="Detected Claude Desktop local IndexedDB. Time Library monitors it as a first-class source-system artifact; content parsing is gated by an explicit authorized parser.",
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


# Authorized raw-ingest helpers live under claude_desktop_raw_ingest.py.


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


_raw_ingest.configure_claude_desktop_raw_ingest(**{
    name: globals()[name]
    for name in (
        "SOURCE_SYSTEM",
        "SYNC_STATE_VERSION",
        "RAW_INGEST_SCHEMA_VERSION",
        "NATIVE_RAW_ARTIFACT_FORMAT",
        "SURFACE_CHAT",
        "SURFACE_COWORK",
        "SURFACE_CODE_OR_AGENT",
        "COWORK_LOCAL_AGENT_BODY_OWNER",
        "COWORK_RUNTIME_CONSUMER",
        "COWORK_PROJECTS_JSONL_RAW_FORMAT",
        "COWORK_JSONL_RAW_ARTIFACT_ID_SCHEMA",
        "CLAUDE_PROJECTS_JSONL_REFERENCE_CONTRACT",
        "CLAUDE_PROJECTS_JSONL_RAW_FORMAT",
        "CLAUDE_PROJECTS_JSONL_RAW_ARTIFACT_ID_SCHEMA",
        "CLAUDE_PROJECTS_JSONL_LEGACY_RAW_FORMATS",
        "CLAUDE_PROJECTS_JSONL_BOUNDARY",
        "RAW_ARCHIVE_SEGMENT_MAX_CHARS",
        "CLAUDE_DESKTOP_INSTALLER_INCLUDES_CLI",
        "CLAUDE_CLI_INSTALLATION_BOUNDARY",
        "CLAUDE_DESKTOP_CLI_RELATIONSHIP",
        "CLAUDE_DESKTOP_MANAGED_RUNTIME_CONSUMER",
        "CLAUDE_DESKTOP_MANAGED_RUNTIME_POLICY",
        "CLAUDE_CODE_BODY_STORAGE_OWNER",
        "CLAUDE_DESKTOP_CODE_SESSION_POLICY",
        "TEXT_FRAGMENT_RE",
        "ROLE_VALUES",
        "MAX_PARSER_FILE_BYTES",
        "LIVE_SYNC_ARTIFACT_TYPES",
        "CHAT_BROWSER_STORE_ARTIFACT_TYPES",
        "COWORK_BODY_ARTIFACT_TYPES",
        "PARSER_ARTIFACT_TYPES",
        "PARSER_FILE_SUFFIXES",
        "SKIP_DIR_NAMES",
        "TIANDAO_CONVERSATION_EVIDENCE_CONTRACT",
        "ts",
        "_public_path_label",
        "_public_relay_proxy_summary",
        "_computer_name",
        "_memcore_root",
        "_memory_root",
        "_sha256_small",
        "_cowork_sessions_root",
        "attribution_from_artifact",
        "discover_artifacts",
        "discover_cowork_sessions",
        "claude_projects_jsonl_reference",
        "source_refs_from_artifact",
        "conversation_capture_verdict",
        "is_complete_conversation_roles",
        "preferred_raw_archive_dir",
        "preferred_raw_archive_path",
        "register_current_window",
        "resolve_claude_home",
        "_artifact_sync_item",
    )
})


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
            "Skill detection is diagnostic only; actual recall requires a Time Library MCP/Desktop Extension tool connection.",
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
            "time_library_mcp_detected": summary["time_library_mcp_detected"],
            "time_library_mcp_server_names": summary["time_library_mcp_server_names"],
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
            "Skill detection is diagnostic only; actual recall requires a Time Library MCP/Desktop Extension tool connection.",
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
    parser.add_argument("--confirm-write-time_library-raw", action="store_true")
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
        "confirm_write_time_library_raw": args.confirm_write_time_library_raw,
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
