#!/usr/bin/env python3
"""Claude Desktop authorized raw-ingest connector under the Time River contract.

This module owns explicit parser-gated local-store ingestion for Claude Desktop.
It can mirror authorized local conversation evidence into Yifanchen raw archives,
but it does not own Time Origin and never writes Claude Desktop platform data.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
CLAUDE_DESKTOP_RAW_INGEST_CONTRACT = "tiandao_claude_desktop_raw_ingest_connector.v1"


def configure_claude_desktop_raw_ingest(**bindings):
    globals().update(bindings)


def get_claude_desktop_raw_ingest_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": CLAUDE_DESKTOP_RAW_INGEST_CONTRACT,
        "zh_name": "Claude Desktop 授权原始记录摄入口",
        "en_name": "Claude Desktop Authorized Raw Ingest Connector",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "source_system": globals().get("SOURCE_SYSTEM", "claude_desktop"),
        "connector_layer": "platform_raw_ingest_inlet",
        "read_only_by_default": True,
        "write_capable": True,
        "authorization_required_for_write": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "authorized_platform_ingest_mirrors_evidence_into_time_origin_without_replacing_it",
        "platform_boundary": "never_write_claude_desktop_config_cookies_tokens_or_native_stores",
        "authorized_write_scopes": [
            "yifanchen_raw_jsonl_mirror",
            "window_binding_receipt",
            "raw_ingest_metadata_receipt",
        ],
    }

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


__all__ = [
    "CLAUDE_DESKTOP_RAW_INGEST_CONTRACT",
    "configure_claude_desktop_raw_ingest",
    "get_claude_desktop_raw_ingest_contract",
    "parser_gate_policy",
    "_is_authorized_parser",
    "_apply_authorized",
    "_parser_files_from_artifact",
    "_decode_file_fragments",
    "_balanced_json_objects",
    "_normalize_role",
    "_text_from_content",
    "_message_dict_from_obj",
    "_collect_messages",
    "_conversation_id_from_obj",
    "_conversation_title_from_obj",
    "_candidate_from_obj",
    "_scan_authorized_candidates",
    "_safe_session_id",
    "_raw_archive_dir",
    "_raw_session_path",
    "_claude_projects_jsonl_raw_session_path",
    "_short_path_digest",
    "_claude_projects_jsonl_raw_artifact_id",
    "_claude_projects_jsonl_raw_artifact_path",
    "_native_jsonl_raw_artifact_path",
    "_legacy_fixed_scope_raw_session_path",
    "_message_content_hash",
    "_claude_desktop_linked_project_candidates",
    "_cowork_jsonl_raw_artifact_id",
    "_cowork_jsonl_candidates",
    "_local_relay_desktop_linked_project_candidates",
    "_stable_message_dedupe_key",
    "_message_dedupe_key",
    "_record_text_from_payload",
    "_record_dedupe_key",
    "_record_from_candidate",
    "_retarget_record_to_candidate_window",
    "_migrate_legacy_fixed_scope_records",
    "_register_current_window_for_candidate",
    "_append_raw_candidates",
    "_sha256_file",
    "_write_claude_projects_jsonl_meta",
    "_write_native_jsonl_mirror_meta",
    "_append_native_jsonl_mirror_candidates",
    "_append_claude_projects_jsonl_candidates",
    "_append_local_relay_projects_jsonl_candidates",
    "_public_candidate",
    "_candidate_has_complete_conversation",
    "_candidate_capture_diagnostic",
    "conversation_body_probe",
    "surface_summary",
    "raw_ingest_dry_run",
    "ingest_authorized_raw",
]
