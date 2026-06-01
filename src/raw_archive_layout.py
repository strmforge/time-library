"""Raw archive folder layout contract.

Preferred raw storage order is:

    memory/<computer_name>/<source_system>/<native_artifact_format>/...

Starting with 2026.6.1, every new install and every new raw archive write uses
this computer-first contract. Existing older source-system-first archives are
read-compatible only; no new connector should create legacy layout paths.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

RAW_ARCHIVE_LAYOUT_CONTRACT = "raw_archive_layout.v1"
RAW_ARCHIVE_LAYOUT_EFFECTIVE_VERSION = "2026.6.1"
RAW_ARCHIVE_LAYOUT_ORDER = ("computer_name", "source_system", "native_artifact_format")
LEGACY_RAW_ARCHIVE_LAYOUT_ORDER = ("source_system", "computer_name", "native_scope")
RAW_ARCHIVE_LAYOUT_AUDIT_CONTRACT = "raw_archive_layout_audit.v1"


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_segment(value: str, fallback: str = "unknown") -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-_")
    return text[:96] or fallback


def native_artifact_format(artifact: dict[str, Any] | None = None, fallback: str = "native") -> str:
    data = artifact or {}
    return safe_segment(
        data.get("native_artifact_format")
        or data.get("artifact_type")
        or data.get("platform_native_format")
        or fallback,
        fallback,
    )


def preferred_raw_archive_dir(
    memory_root: str | Path,
    *,
    computer_name: str,
    source_system: str,
    native_format: str,
) -> Path:
    return (
        Path(memory_root)
        / safe_segment(computer_name, "local")
        / safe_segment(source_system, "unknown_source")
        / safe_segment(native_format, "native")
    )


def preferred_raw_archive_path(
    memory_root: str | Path,
    *,
    computer_name: str,
    source_system: str,
    native_format: str,
    native_scope: str = "",
    session_id: str = "",
    extension: str = "jsonl",
) -> Path:
    root = preferred_raw_archive_dir(
        memory_root,
        computer_name=computer_name,
        source_system=source_system,
        native_format=native_format,
    )
    scope = safe_segment(native_scope, "default")
    stem = safe_segment(session_id, "session")
    ext = safe_segment(extension.lstrip("."), "jsonl")
    return root / scope / f"{stem}.{ext}"


def classify_raw_archive_path(path: str | Path, memory_root: str | Path) -> dict[str, Any]:
    root = Path(memory_root)
    raw_path = Path(path)
    try:
        parts = raw_path.relative_to(root).parts
    except ValueError:
        parts = raw_path.parts
    if len(parts) >= 5:
        return {
            "layout": "computer_first",
            "computer_name": parts[0],
            "source_system": parts[1],
            "native_artifact_format": parts[2],
            "native_scope": parts[3],
            "session_id": raw_path.stem,
            "legacy": False,
            "path": str(raw_path),
        }
    if len(parts) >= 4:
        return {
            "layout": "legacy_source_first",
            "computer_name": parts[1],
            "source_system": parts[0],
            "native_artifact_format": "",
            "native_scope": parts[2],
            "session_id": raw_path.stem,
            "legacy": True,
            "path": str(raw_path),
        }
    return {
        "layout": "unknown",
        "computer_name": "",
        "source_system": "",
        "native_artifact_format": "",
        "native_scope": "",
        "session_id": raw_path.stem,
        "legacy": False,
        "path": str(raw_path),
    }


def audit_raw_archive_layout(
    memory_root: str | Path,
    *,
    max_files: int = 5000,
    sample_limit: int = 80,
) -> dict[str, Any]:
    root = Path(memory_root)
    current_files = 0
    legacy_files = 0
    unknown_files = 0
    truncated = False
    by_computer: dict[str, int] = {}
    by_source_system: dict[str, int] = {}
    by_native_artifact_format: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    raw_files: list[Path] = []
    if root.exists():
        for index, path in enumerate(root.rglob("*.jsonl")):
            if index >= max_files:
                truncated = True
                break
            if not path.is_file():
                continue
            raw_files.append(path)

    for path in raw_files:
        item = classify_raw_archive_path(path, root)
        layout = item.get("layout")
        if layout == "computer_first":
            current_files += 1
        elif layout == "legacy_source_first":
            legacy_files += 1
        else:
            unknown_files += 1
        computer = item.get("computer_name") or "unknown"
        source_system = item.get("source_system") or "unknown"
        native_format = item.get("native_artifact_format") or "legacy_or_unknown"
        by_computer[computer] = by_computer.get(computer, 0) + 1
        by_source_system[source_system] = by_source_system.get(source_system, 0) + 1
        by_native_artifact_format[native_format] = by_native_artifact_format.get(native_format, 0) + 1
        if len(samples) < sample_limit:
            samples.append(item)

    return {
        "ok": True,
        "contract": RAW_ARCHIVE_LAYOUT_AUDIT_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "memory_root": str(root),
        "effective_from_version": RAW_ARCHIVE_LAYOUT_EFFECTIVE_VERSION,
        "new_raw_writes_must_use_preferred_layout": True,
        "legacy_layout_allowed_for_new_writes": False,
        "legacy_layout_status": "read_compatibility_only",
        "totals": {
            "raw_jsonl_files": current_files + legacy_files + unknown_files,
            "computer_first_files": current_files,
            "legacy_source_first_files": legacy_files,
            "unknown_layout_files": unknown_files,
        },
        "legacy_present": legacy_files > 0,
        "unknown_present": unknown_files > 0,
        "truncated": truncated,
        "max_files": max_files,
        "by_computer": dict(sorted(by_computer.items())),
        "by_source_system": dict(sorted(by_source_system.items())),
        "by_native_artifact_format": dict(sorted(by_native_artifact_format.items())),
        "samples": samples,
    }


def layout_descriptor(
    *,
    computer_name: str = "local",
    source_system: str = "codex",
    native_format: str = "codex_session_jsonl",
    native_scope: str = "project",
    session_id: str = "session",
) -> dict[str, Any]:
    example = preferred_raw_archive_path(
        "memory",
        computer_name=computer_name,
        source_system=source_system,
        native_format=native_format,
        native_scope=native_scope,
        session_id=session_id,
    )
    return {
        "ok": True,
        "contract": RAW_ARCHIVE_LAYOUT_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "effective_from_version": RAW_ARCHIVE_LAYOUT_EFFECTIVE_VERSION,
        "new_install_default_layout": "computer_first",
        "new_raw_writes_must_use_preferred_layout": True,
        "preferred_segment_order": list(RAW_ARCHIVE_LAYOUT_ORDER),
        "preferred_template": "memory/{computer_name}/{source_system}/{native_artifact_format}/{native_scope}/{session_id}.{extension}",
        "legacy_segment_order_supported_for_existing_archives": list(LEGACY_RAW_ARCHIVE_LAYOUT_ORDER),
        "legacy_layout_status": "read_compatibility_only",
        "legacy_layout_allowed_for_new_writes": False,
        "legacy_migration_required_before_read": False,
        "policy_summary": (
            "From version 2026.6.1 onward, new installs and new raw archive writes use the "
            "computer-first layout. Legacy source-system-first paths remain readable but are not "
            "created by new connectors."
        ),
        "central_node_mode_rationale": (
            "When multiple machines sync into one central node, raw archives are grouped by computer first. "
            "Each computer then contains the software surfaces and their native save formats."
        ),
        "primary_partition_key": "computer_name",
        "secondary_partition_key": "source_system",
        "native_format_policy": "preserve_each_platform_native_save_format_under_its_own_bucket",
        "discovery_policy": "platform_discovery_may_be_broad_but_raw_archives_remain_computer_and_source_partitioned",
        "example_path": str(example),
    }
