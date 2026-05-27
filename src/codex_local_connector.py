#!/usr/bin/env python3
"""
Codex local source connector.

Read-only source side:
- discovers local Codex rollout JSONL files under ~/.codex/sessions
- reads session metadata and thread names without reading auth/token files

Write side:
- archives an independent raw copy into memory/codex/<node>/<project>/<session>.jsonl
- uses the shared memcore checkpoint for incremental appends
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config_loader import checkpoint_file, memory_root, node_id

UTC = timezone.utc
SOURCE_SYSTEM = "codex"
SESSION_GLOB = "*.jsonl"


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def codex_sessions_root() -> Path:
    override = os.environ.get("CODEX_SESSIONS_DIR", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex" / "sessions"


def codex_session_index_path() -> Path:
    override = os.environ.get("CODEX_SESSION_INDEX", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex" / "session_index.jsonl"


def _safe_segment(value: str, fallback: str = "unknown") -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-_")
    return text[:80] or fallback


def _public_path_label(path: str) -> str:
    path = str(path or "")
    if not path:
        return ""
    try:
        p = Path(path).expanduser()
        home = Path.home().resolve()
        resolved = p.resolve()
        try:
            rel = resolved.relative_to(home)
            return "~/" + str(rel)
        except ValueError:
            return p.name or path
    except Exception:
        return Path(path).name or path


def project_id_from_cwd(cwd: str) -> str:
    if not cwd:
        return "no-cwd"
    expanded = os.path.expanduser(cwd)
    name = Path(expanded).name or "project"
    digest = hashlib.sha1(expanded.encode("utf-8")).hexdigest()[:8]
    return _safe_segment(f"{name}-{digest}", "project")


def _file_hash(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size > 50 * 1024 * 1024:
        return f"sha256_skipped_large_file:{size}"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_session_index() -> Dict[str, dict]:
    index_path = codex_session_index_path()
    result: Dict[str, dict] = {}
    if not index_path.exists():
        return result
    try:
        with index_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                sid = str(item.get("id") or "")
                if sid:
                    result[sid] = item
    except OSError:
        return result
    return result


def _read_session_meta(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for _ in range(80):
                line = f.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "session_meta" and isinstance(obj.get("payload"), dict):
                    return obj["payload"]
    except OSError:
        return {}
    return {}


def _session_id_from_path(path: Path, meta: dict) -> str:
    sid = str(meta.get("id") or "").strip()
    if sid:
        return sid
    stem = path.stem
    if stem.startswith("rollout-"):
        parts = stem.split("-")
        if len(parts) >= 6:
            return "-".join(parts[-5:])
    return stem


def artifact_from_path(path: Path, index: Optional[Dict[str, dict]] = None) -> dict:
    path = path.expanduser()
    meta = _read_session_meta(path)
    session_id = _session_id_from_path(path, meta)
    index = index if index is not None else _load_session_index()
    indexed = index.get(session_id, {})
    cwd = str(meta.get("cwd") or "")
    project_id = project_id_from_cwd(cwd)
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": "codex_session_jsonl",
        "source_path": str(path),
        "filename": path.name,
        "session_id": session_id,
        "native_thread_id": session_id,
        "canonical_window_id": project_id,
        "project_id": project_id,
        "project_root": cwd,
        "thread_name": indexed.get("thread_name", ""),
        "thread_updated_at": indexed.get("updated_at", ""),
        "codex_source": meta.get("source", ""),
        "thread_source": meta.get("thread_source", ""),
        "model_provider": meta.get("model_provider", ""),
        "cli_version": meta.get("cli_version", ""),
        "computer_name": node_id(),
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 3),
        "mtime": mtime,
        "capture_classification": "SHADOW",
        "scope_level": "project",
        "read_only_probe": True,
    }


def discover_sessions(limit: int = 0) -> List[dict]:
    root = codex_sessions_root()
    if not root.exists():
        return []
    index = _load_session_index()
    files = [p for p in root.rglob(SESSION_GLOB) if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if limit and limit > 0:
        files = files[:limit]
    artifacts = []
    for path in files:
        try:
            artifacts.append(artifact_from_path(path, index=index))
        except OSError:
            continue
    return artifacts


def source_refs_from_artifact(artifact: dict) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        "computer_name": artifact.get("computer_name") or node_id(),
        "canonical_window_id": artifact.get("canonical_window_id", ""),
        "session_id": artifact.get("session_id", ""),
        "source_path": artifact.get("source_path", ""),
        "msg_ids": artifact.get("msg_ids", []) or [],
        "artifact_type": artifact.get("artifact_type", "codex_session_jsonl"),
        "captured_at": ts(),
        "project_root": artifact.get("project_root", ""),
        "project_id": artifact.get("project_id", artifact.get("canonical_window_id", "")),
        "thread_name": artifact.get("thread_name", ""),
        "native_thread_id": artifact.get("native_thread_id", artifact.get("session_id", "")),
    }


def public_artifact(artifact: dict) -> dict:
    """Return status-safe metadata without full local paths."""
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": artifact.get("artifact_type", "codex_session_jsonl"),
        "filename": artifact.get("filename", ""),
        "session_id": artifact.get("session_id", ""),
        "canonical_window_id": artifact.get("canonical_window_id", ""),
        "project_id": artifact.get("project_id", ""),
        "computer_name": artifact.get("computer_name", ""),
        "size_bytes": artifact.get("size_bytes", 0),
        "size_mb": artifact.get("size_mb", 0),
        "mtime": artifact.get("mtime", ""),
        "capture_classification": artifact.get("capture_classification", "SHADOW"),
        "scope_level": artifact.get("scope_level", "project"),
        "read_only_probe": True,
    }


def load_checkpoint() -> dict:
    path = checkpoint_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def save_checkpoint(data: dict) -> None:
    path = checkpoint_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _checkpoint_key(source_path: str) -> str:
    return f"{SOURCE_SYSTEM}:{os.path.abspath(os.path.expanduser(source_path))}"


def _raw_dest_for_artifact(artifact: dict) -> Path:
    project_id = _safe_segment(artifact.get("canonical_window_id") or artifact.get("project_id"), "project")
    session_id = _safe_segment(artifact.get("session_id"), "session")
    return Path(memory_root()) / SOURCE_SYSTEM / (artifact.get("computer_name") or node_id()) / project_id / f"{session_id}.jsonl"


def _write_meta(dest: Path, artifact: dict, src_stat: os.stat_result, offset: int, raw_order: int) -> None:
    meta = {
        "source_system": SOURCE_SYSTEM,
        "source_path": artifact.get("source_path", ""),
        "source_inode": src_stat.st_ino,
        "source_mtime": src_stat.st_mtime,
        "source_checksum": _file_hash(Path(artifact["source_path"])),
        "file_offset": offset,
        "raw_order": raw_order,
        "archived_to": str(dest),
        "session_id": artifact.get("session_id", ""),
        "project_id": artifact.get("project_id", ""),
        "project_root": artifact.get("project_root", ""),
        "thread_name": artifact.get("thread_name", ""),
        "last_update": ts(),
    }
    with open(str(dest) + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def archive_session_incremental(source_path: str, dry_run: bool = False, artifact: Optional[dict] = None) -> tuple[str, str]:
    src = Path(source_path).expanduser()
    if artifact is None:
        artifact = artifact_from_path(src)
    dest = _raw_dest_for_artifact(artifact)

    try:
        src_stat = src.stat()
    except OSError:
        return str(dest), "error: cannot stat source"

    checkpoint = load_checkpoint()
    key = _checkpoint_key(str(src))
    prior = checkpoint.get(key, {})
    last_offset = int(prior.get("offset", 0) or 0)
    is_rotation = bool(prior) and prior.get("source_inode") != src_stat.st_ino
    if is_rotation:
        last_offset = 0
    elif prior and not dest.exists():
        last_offset = 0

    if not prior and dest.exists():
        try:
            dest_size = dest.stat().st_size
        except OSError:
            dest_size = 0
        if 0 < dest_size < src_stat.st_size:
            last_offset = dest_size
        if dest_size == src_stat.st_size:
            checkpoint[key] = {
                "offset": src_stat.st_size,
                "archived_to": str(dest),
                "source_inode": src_stat.st_ino,
                "source_size": src_stat.st_size,
                "source_mtime": src_stat.st_mtime,
                "raw_order": 1,
                "source_system": SOURCE_SYSTEM,
                "last_update": ts(),
                "recovered_from_existing_dest": True,
            }
            save_checkpoint(checkpoint)
            _write_meta(dest, artifact, src_stat, src_stat.st_size, 1)
            return str(dest), f"up_to_date(offset={src_stat.st_size}, checkpoint_recovered)"

    if src_stat.st_size <= last_offset and not is_rotation:
        return str(dest), f"up_to_date(offset={last_offset})"

    raw_order = int(prior.get("raw_order", 0) or 0) + (1 if is_rotation or not prior else 0)
    raw_order = max(raw_order, 1)

    if dry_run:
        return str(dest), f"dry_run(offset={last_offset}/{src_stat.st_size})"

    dest.parent.mkdir(parents=True, exist_ok=True)

    bytes_written = 0
    lines_written = 0
    with src.open("rb") as inp, dest.open("ab") as out:
        inp.seek(last_offset)
        while True:
            chunk = inp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            bytes_written += len(chunk)
            lines_written += chunk.count(b"\n")
        new_offset = inp.tell()

    if bytes_written == 0:
        return str(dest), f"empty_append(offset={new_offset})"

    checkpoint[key] = {
        "offset": new_offset,
        "archived_to": str(dest),
        "source_inode": src_stat.st_ino,
        "source_size": src_stat.st_size,
        "source_mtime": src_stat.st_mtime,
        "raw_order": raw_order,
        "source_system": SOURCE_SYSTEM,
        "last_update": ts(),
    }
    save_checkpoint(checkpoint)
    _write_meta(dest, artifact, src_stat, new_offset, raw_order)

    if is_rotation:
        return str(dest), f"rotation_detected(appended {lines_written} lines, {bytes_written} bytes)"
    if last_offset == 0:
        return str(dest), f"archived({lines_written} lines, {bytes_written} bytes)"
    return str(dest), f"appended({lines_written} lines, {bytes_written} bytes, {last_offset}->{new_offset})"


def scan_sessions(dry_run: bool = False, limit: int = 0, public: bool = False) -> dict:
    artifacts = discover_sessions(limit=limit)
    items = []
    changed = 0
    would_change = 0
    for artifact in artifacts:
        dest, status = archive_session_incremental(artifact["source_path"], dry_run=dry_run, artifact=artifact)
        if dry_run and status.startswith("dry_run"):
            would_change += 1
        elif status.startswith(("archived", "appended", "rotation")):
            changed += 1
        items.append({
            "source_path": _public_path_label(artifact["source_path"]) if public else artifact["source_path"],
            "dest": _public_path_label(dest) if public else dest,
            "status": status,
            "session_id": artifact.get("session_id", ""),
            "canonical_window_id": artifact.get("canonical_window_id", ""),
            "project_root": _public_path_label(artifact.get("project_root", "")) if public else artifact.get("project_root", ""),
            "thread_name": artifact.get("thread_name", ""),
        })
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "sessions_root": str(codex_sessions_root()),
        "discovered": len(artifacts),
        "changed": changed,
        "would_change": would_change,
        "dry_run": dry_run,
        "items": items,
    }


def status() -> dict:
    artifacts = discover_sessions(limit=20)
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "sessions_root": _public_path_label(str(codex_sessions_root())),
        "session_index": _public_path_label(str(codex_session_index_path())),
        "reachable": codex_sessions_root().exists(),
        "artifact_count_sample": len(artifacts),
        "latest": [public_artifact(item) for item in artifacts[:5]],
        "read_only": True,
        "auth_files_read": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex local session connector")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.discover:
        print(json.dumps(discover_sessions(limit=args.limit), ensure_ascii=False, indent=2))
    elif args.scan:
        print(json.dumps(scan_sessions(dry_run=args.dry_run, limit=args.limit), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
