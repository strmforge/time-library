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

UTC = timezone.utc
SOURCE_SYSTEM = "claude_desktop"
SYNC_STATE_VERSION = 1
RAW_INGEST_SCHEMA_VERSION = 1
NATIVE_RAW_ARTIFACT_FORMAT = "claude_desktop_authorized_local_store_jsonl"
SENSITIVE_KEY_RE = re.compile(r"(key|token|secret|password|auth|credential|cookie)", re.I)
TEXT_FRAGMENT_RE = re.compile(rb"[\x09\x0a\x0d\x20-\x7e]{8,}")
ROLE_VALUES = {"user", "human", "assistant", "ai", "model", "tool", "system"}
MAX_PARSER_FILE_BYTES = 64 * 1024 * 1024
LIVE_SYNC_ARTIFACT_TYPES = {
    "claude_desktop_app_support_dir",
    "claude_desktop_config_json",
    "claude_desktop_config_json_parse_error",
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
        "conversation_origin": "claude_code_cli",
        "runtime_consumer": "claude_code_cli",
        "artifact_role": "conversation_session_store",
    },
    "claude_code_runtime_bundle": {
        "conversation_origin": "not_conversation_memory",
        "runtime_consumer": "claude_code_cli",
        "artifact_role": "runtime_bundle",
    },
    "claude_code_vm_bundle": {
        "conversation_origin": "not_conversation_memory",
        "runtime_consumer": "claude_code_vm",
        "artifact_role": "runtime_vm_bundle",
    },
}
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
    if artifact_type in RELATED_CLAUDE_CODE_ARTIFACT_TYPES:
        related = RELATED_CLAUDE_CODE_ATTRIBUTION.get(artifact_type, {})
        conversation_origin = str(related.get("conversation_origin") or "claude_code_cli")
        runtime_consumer = str(related.get("runtime_consumer") or "claude_code_cli")
        return {
            **collection,
            "attribution_mode": "dual",
            "source_surface": conversation_origin,
            "source_systems": [SOURCE_SYSTEM, "claude_code_cli"],
            "co_source_systems": ["claude_code_cli", "claude_desktop_relay"],
            "storage_owner": SOURCE_SYSTEM,
            "conversation_origin": conversation_origin,
            "runtime_consumer": runtime_consumer,
            "relay_owner": "claude_desktop_relay",
            "artifact_role": related.get("artifact_role") or sync_role or "related_artifact",
            "visibility_boundary": "isolated_surfaces",
            "cross_surface_memory_shared": False,
            "official_relay_interop": False,
            "surface_readability": {
                "official_claude_desktop_reads_relay_chats": False,
                "relay_runtime_reads_official_claude_chats": False,
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
                    "role": "relay_or_bridge_surface",
                    "source_system": "claude_desktop_relay",
                    "evidence": "claude_desktop_related_claude_code_artifact",
                },
            ],
            "attribution_note": (
                "Claude Code or relay artifacts can live under Claude Desktop app data. "
                "Yifanchen keeps storage ownership and conversation/runtime ownership separate."
            ),
            "boundary_note": (
                "Dual attribution is lineage evidence only. Official Claude login chats and relay/Claude Code chats are isolated surfaces."
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
    return {
        **collection,
        "attribution_mode": "single",
        "source_surface": SOURCE_SYSTEM,
        "source_systems": [SOURCE_SYSTEM],
        "co_source_systems": [],
        "storage_owner": SOURCE_SYSTEM,
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
            "native_artifact_format": NATIVE_RAW_ARTIFACT_FORMAT,
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


def _public_candidate(candidate: dict[str, Any], include_excerpt: bool = False, include_messages: bool = False) -> dict[str, Any]:
    result = {
        "candidate_id": candidate.get("candidate_id", ""),
        "conversation_id": candidate.get("conversation_id", ""),
        "session_id": candidate.get("session_id", ""),
        "title": candidate.get("title", ""),
        "message_count": candidate.get("message_count", 0),
        "roles": candidate.get("roles", []),
        "source_path": candidate.get("source_path_public", _public_path_label(candidate.get("source_path", ""))),
        "artifact_type": candidate.get("artifact_type", ""),
        "store_path": candidate.get("store_path_public", _public_path_label(candidate.get("store_path", ""))),
        "candidate_hash": candidate.get("candidate_hash", ""),
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
    return {"user", "assistant"}.issubset(set(candidate.get("roles") or []))


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
    capture_diagnostic = _candidate_capture_diagnostic(candidates, stats)
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "dry_run": True,
        "blocked": False,
        "parser_kind": "authorized_local_store_text_fragment_parser",
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
    write_result = _append_raw_candidates(candidates)
    capture_diagnostic = _candidate_capture_diagnostic(candidates, stats)
    capture_diagnostic["current_window_binding_registered"] = bool(
        write_result.get("window_bindings_registered")
    )
    if write_result.get("window_bindings_registered"):
        capture_diagnostic["current_window_binding_status"] = "registered"
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "dry_run": False,
        "blocked": False,
        "parser_kind": "authorized_local_store_text_fragment_parser",
        "parser_schema_version": RAW_INGEST_SCHEMA_VERSION,
        "candidate_count": len(candidates),
        "current_window_capture_status": capture_diagnostic["status"],
        "assistant_reply_persistence": capture_diagnostic["assistant_reply_persistence"],
        "current_window_binding_status": capture_diagnostic["current_window_binding_status"],
        "capture_diagnostic": capture_diagnostic,
        "stats": stats,
        "write_performed": bool(write_result.get("records_written")),
        "platform_write_performed": False,
        "memory_write_performed": bool(write_result.get("records_written")),
        "raw_write": {
            **write_result,
            "raw_paths": [
                _public_path_label(path) if public else path
                for path in write_result.get("raw_paths", [])
            ],
        },
        "candidates": [
            _public_candidate(candidate, include_excerpt=bool(body.get("include_excerpt")), include_messages=not public)
            for candidate in candidates
        ],
        "notes": [
            "Wrote only Yifanchen raw JSONL records.",
            "No Claude Desktop config, native chat store, cookie, token, MCP config, or skill manifest was written.",
            "Claude Code data remains outside this parser.",
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
    return {
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
        "conversation_origin",
        "runtime_consumer",
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
        if isinstance(result.get("metadata_snapshot"), dict):
            snapshot = dict(result["metadata_snapshot"])
            sampled = snapshot.pop("sampled_files", [])
            snapshot["sampled_file_count"] = len(sampled) if isinstance(sampled, list) else 0
            result["metadata_snapshot"] = snapshot
        refs = dict(result.get("source_refs", {}))
        refs["source_path"] = _public_path_label(refs.get("source_path", ""))
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
            "visibility_boundary_field": "visibility_boundary",
            "windows_claude_relay_note": (
                "A Claude artifact can be stored under Claude Desktop while the conversation/runtime belongs to Claude Code or a relay surface. "
                "Official Claude login chats and relay/Claude Code chats remain isolated and do not read each other."
            ),
        },
        "notes": [
            "This is the system-level local sync state for Claude Desktop user-space data.",
            "Export archives are not part of the primary sync state; they remain cold-start/backfill fallback evidence.",
            "Content-bearing stores are tracked by fingerprint and metadata until an explicit parser gate is authorized.",
            "Related Claude Code or relay artifacts keep dual attribution instead of being flattened into Claude Desktop.",
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
            refs = dict(result.get("source_refs", {}))
            refs["source_path"] = _public_path_label(refs.get("source_path", ""))
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
            "visibility_boundary_field": "visibility_boundary",
            "windows_claude_relay_note": (
                "A Claude artifact can be stored under Claude Desktop while the conversation/runtime belongs to Claude Code or a relay surface. "
                "Official Claude login chats and relay/Claude Code chats remain isolated and do not read each other."
            ),
        },
        "notes": [
            "Claude Desktop is a first-class source system distinct from Claude Code CLI.",
            "On Windows relay setups, related Claude Code artifacts keep both Claude Desktop storage ownership and Claude Code/relay runtime attribution.",
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
    indexeddb_exists = (root / "IndexedDB").exists()
    export_count = sum(1 for item in artifacts if item.get("artifact_type") == "claude_data_export_candidate")
    live_count = sum(1 for item in artifacts if item.get("artifact_type") in LIVE_SYNC_ARTIFACT_TYPES)
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
            "indexeddb_detected": indexeddb_exists,
            "indexeddb_content_read_by_default": False,
            "content_parser_gate": "explicit_authorized_parser_required",
            "preferred_raw_source": "live_local_sync_manifest_then_authorized_parser",
        },
        "sync_manifest_endpoint": "/api/v1/source-systems/claude_desktop/sync-manifest",
        "sync_state_endpoint": "/api/v1/source-systems/claude_desktop/sync-state",
        "parser_gate_endpoint": "/api/v1/source-systems/claude_desktop/parser-gate",
        "raw_ingest_dry_run_endpoint": "/api/v1/source-systems/claude_desktop/raw-ingest/dry-run",
        "raw_ingest_endpoint": "/api/v1/source-systems/claude_desktop/raw-ingest",
        "sync_manifest_live_item_count": live_count,
        "export_candidates_count": export_count,
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
            "windows_claude_relay_note": "Related Claude Code or relay artifacts are tracked with storage_owner, conversation_origin, and runtime_consumer fields; official Claude login chats and relay/Claude Code chats remain isolated.",
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
