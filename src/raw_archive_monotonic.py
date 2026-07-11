"""Append-only helpers for source-backed raw archives.

Raw archives may advance when the source grows. A shorter or rewritten source
is diagnostic evidence, never permission to shrink or replace the archive.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


CONTRACT = "time_library_raw_archive_monotonic.v1"
CHUNK_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prefix_matches(source: Path, archive: Path, length: int) -> bool:
    remaining = max(0, int(length))
    with source.open("rb") as src, archive.open("rb") as raw:
        while remaining:
            size = min(CHUNK_SIZE, remaining)
            if src.read(size) != raw.read(size):
                return False
            remaining -= size
    return True


def append_source_file(
    source_path: str | Path,
    archive_path: str | Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    source = Path(source_path).expanduser()
    archive = Path(archive_path).expanduser()
    source_size = source.stat().st_size
    archive_size = archive.stat().st_size if archive.exists() else 0
    base = {
        "ok": True,
        "contract": CONTRACT,
        "source_path": str(source),
        "archive_path": str(archive),
        "source_size": source_size,
        "archive_size_before": archive_size,
        "archive_size_after": archive_size,
        "write_performed": False,
        "dry_run": bool(dry_run),
        "raw_shrink_performed": False,
        "source_regression": False,
        "source_divergence": False,
    }
    if archive_size > source_size:
        return {
            **base,
            "status": "source_regression_raw_retained",
            "source_regression": True,
            "retained_bytes": archive_size,
        }
    if archive_size and not _prefix_matches(source, archive, archive_size):
        return {
            **base,
            "status": "source_divergence_raw_retained",
            "source_divergence": True,
            "retained_bytes": archive_size,
        }
    if archive.exists() and archive_size == source_size:
        return {
            **base,
            "status": "up_to_date",
            "source_sha256": _sha256(source),
            "archive_sha256": _sha256(archive),
        }

    if dry_run:
        return {
            **base,
            "status": "would_create" if not archive.exists() else "would_append",
            "bytes_appended": source_size - archive_size,
            "archive_size_after": source_size,
        }

    archive.parent.mkdir(parents=True, exist_ok=True)
    mode = "ab" if archive.exists() else "xb"
    with source.open("rb") as src, archive.open(mode) as raw:
        src.seek(archive_size)
        appended = 0
        lines_appended = 0
        for chunk in iter(lambda: src.read(CHUNK_SIZE), b""):
            raw.write(chunk)
            appended += len(chunk)
            lines_appended += chunk.count(b"\n")
        raw.flush()
        os.fsync(raw.fileno())
    final_size = archive.stat().st_size
    return {
        **base,
        "status": "created" if archive_size == 0 else "appended",
        "archive_size_after": final_size,
        "bytes_appended": appended,
        "lines_appended": lines_appended,
        "write_performed": appended > 0,
        "source_sha256": _sha256(source),
        "archive_sha256": _sha256(archive),
    }


def append_jsonl_records(
    archive_path: str | Path,
    records: Iterable[dict[str, Any]],
    *,
    id_key: str = "id",
) -> dict[str, Any]:
    archive = Path(archive_path).expanduser()
    incoming = [item for item in records if isinstance(item, dict)]
    existing: list[dict[str, Any]] = []
    if archive.exists():
        for line in archive.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                existing.append(value)

    def record_identity(item: dict[str, Any]) -> str:
        explicit = str(item.get(id_key) or "").strip()
        if explicit:
            return "id:" + explicit
        payload = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    existing_by_id = {record_identity(item): item for item in existing}
    incoming_by_id = {record_identity(item): item for item in incoming}
    mutations = [
        record_id
        for record_id in sorted(existing_by_id.keys() & incoming_by_id.keys())
        if existing_by_id[record_id] != incoming_by_id[record_id]
    ]
    missing_from_source = sorted(existing_by_id.keys() - incoming_by_id.keys())
    additions = [
        item for item in incoming
        if record_identity(item) not in existing_by_id
    ]
    if additions:
        archive.parent.mkdir(parents=True, exist_ok=True)
        with archive.open("a", encoding="utf-8") as handle:
            for item in additions:
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return {
        "ok": True,
        "contract": CONTRACT,
        "archive_path": str(archive),
        "status": (
            "appended_with_source_regression_raw_retained"
            if additions and missing_from_source
            else "appended_with_source_divergence_raw_retained"
            if additions and mutations
            else "appended"
            if additions
            else "source_regression_raw_retained"
            if missing_from_source
            else "source_divergence_raw_retained"
            if mutations
            else "up_to_date"
        ),
        "existing_record_count": len(existing),
        "source_record_count": len(incoming),
        "appended_record_count": len(additions),
        "source_missing_record_count": len(missing_from_source),
        "source_mutation_count": len(mutations),
        "source_regression": bool(missing_from_source),
        "source_divergence": bool(mutations),
        "write_performed": bool(additions),
        "raw_shrink_performed": False,
    }


__all__ = ["CONTRACT", "append_source_file", "append_jsonl_records"]
