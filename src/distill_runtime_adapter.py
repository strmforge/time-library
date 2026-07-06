#!/usr/bin/env python3
"""Runtime distiller adapter for one automatic coverage-ledger session.

The coverage runner owns ledger state, candidate writing, de-duplication, and
self-check transitions. This adapter only calls the existing shelf pipelines in
read-only/dry-run mode and returns evidence-bound candidate objects.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from src.source_system_runtime_declarations import (
        source_system_for_distill_checkpoint_adapter,
        source_system_uses_distill_checkpoint_adapter,
    )
except ImportError:  # pragma: no cover
    from source_system_runtime_declarations import (
        source_system_for_distill_checkpoint_adapter,
        source_system_uses_distill_checkpoint_adapter,
    )

DISTILL_RUNTIME_ADAPTER_CONTRACT = "time_library_distill_runtime_adapter.v1"
MIMOCODE_CHECKPOINT_ADAPTER_CONTRACT = "time_library_distill_mimocode_checkpoint_adapter.v1"
DEEP_DISTILL_TARGET_SHAPE = "deep_distill"
MIMOCODE_DEEP_DISTILL_TARGET_SHAPE = "mimocode_deep_distill"
MIMOCODE_SOURCE_SYSTEM = source_system_for_distill_checkpoint_adapter("checkpoint_markdown_sections") or "mimocode"


def _root() -> Path:
    return Path(
        os.environ.get("TIME_LIBRARY_DISTILL_ROOT")
        or os.environ.get("MEMCORE_ROOT")
        or os.environ.get("MEMCORE_INSTALL_ROOT")
        or Path(__file__).resolve().parents[1]
    ).expanduser()


def _records_db(root: Path) -> Path:
    return Path(os.environ.get("TIME_LIBRARY_DISTILL_RECORDS_DB") or root / "output" / "records" / "records.db").expanduser()


def _load_tool_module(name: str):
    root = _root()
    path = root / "tools" / f"{name}.py"
    if not path.is_file():
        path = Path(__file__).resolve().parents[1] / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"time_library_runtime_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load tool module: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def _set_model_env(model: dict[str, Any]) -> None:
    provider = str(model.get("provider") or os.environ.get("TIME_LIBRARY_DISTILL_PROVIDER") or "").strip()
    model_name = str(model.get("model") or os.environ.get("TIME_LIBRARY_DISTILL_MODEL") or "").strip()
    if provider:
        os.environ.setdefault("MEMCORE_ZHIYI_PROVIDER", provider)
    if model_name:
        os.environ.setdefault("MEMCORE_ZHIYI_MODEL", model_name)
    if provider.lower() == "minimax" and model_name:
        os.environ.setdefault("MINIMAX_MODEL", model_name)
        os.environ.setdefault("MINIMAX_CN_MODEL", model_name)
    api_key_env = str(model.get("api_key_env") or os.environ.get("TIME_LIBRARY_DISTILL_API_KEY_ENV") or "").strip()
    if api_key_env:
        os.environ.setdefault("MEMCORE_ZHIYI_API_KEY_ENV", api_key_env)


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name) or default))
    except ValueError:
        return default


def _checkpoint_section_spans(text: str) -> list[dict[str, Any]]:
    sections = [
        ("## §1 Active intent", "user", "mimocode_checkpoint_active_intent"),
        ("## §5 Current work", "assistant", "mimocode_checkpoint_current_work"),
        ("## §7 Discovered knowledge", "assistant", "mimocode_checkpoint_discovered_knowledge"),
        ("## §10 Design decisions", "assistant", "mimocode_checkpoint_design_decisions"),
    ]
    spans: list[dict[str, Any]] = []
    for marker, role, basis in sections:
        idx = text.find(marker)
        if idx < 0:
            continue
        next_idx = text.find("\n## ", idx + len(marker))
        end_idx = next_idx if next_idx > idx else len(text)
        content = text[idx:end_idx]
        if len(content.strip()) < 20:
            continue
        start = len(text[:idx].encode("utf-8"))
        end = len(text[:end_idx].encode("utf-8"))
        spans.append({"role": role, "basis": basis, "content": content, "start": start, "end": end})
    if spans:
        return spans
    compact = text.strip()
    if not compact:
        return []
    return [{"role": "assistant", "basis": "mimocode_checkpoint_full_text", "content": compact, "start": 0, "end": len(text.encode("utf-8"))}]


def mimocode_checkpoint_messages_for_session(session: dict[str, Any]) -> list[dict[str, Any]]:
    """Project a MiMo checkpoint.md into canonical-message-shaped rows."""

    source_path = Path(str(session.get("source_path") or "")).expanduser()
    if not source_path.is_file():
        return []
    text = source_path.read_text(encoding="utf-8", errors="ignore")
    messages: list[dict[str, Any]] = []
    for index, span in enumerate(_checkpoint_section_spans(text), start=1):
        messages.append(
            {
                "message_id": f"{session.get('session_id') or source_path.stem}:checkpoint:{index}",
                "source_system": str(session.get("source_system") or MIMOCODE_SOURCE_SYSTEM),
                "session_id": str(session.get("session_id") or ""),
                "canonical_window_id": str(session.get("canonical_window_id") or session.get("session_id") or ""),
                "project_id": "",
                "source_path": str(source_path),
                "raw_path": "",
                "role": span["role"],
                "timestamp": str(session.get("source_updated_at") or session.get("updated_at") or ""),
                "source_offset_start": int(span["start"]),
                "source_offset_end": int(span["end"]),
                "raw_offset_start": None,
                "raw_offset_end": None,
                "line_no": index,
                "content_preview": str(span["content"])[:240],
                "payload_json": json.dumps(
                    {
                        "source_line": {"content": span["content"]},
                        "checkpoint_span_basis": span["basis"],
                        "checkpoint_adapter_contract": MIMOCODE_CHECKPOINT_ADAPTER_CONTRACT,
                    },
                    ensure_ascii=False,
                ),
            }
        )
    return messages


def _write_temp_records_db_for_messages(messages: list[dict[str, Any]]) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    # The existing distillers already accept canonical_messages. For MiMo
    # checkpoint.md, project a read-only in-process sqlite fixture with exact
    # source offsets instead of mutating the installed canonical store.
    tempdir = tempfile.TemporaryDirectory(prefix="time-library-mimocode-distill-")
    db_path = Path(tempdir.name) / "records.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                source_path text,
                raw_path text,
                role text,
                timestamp text,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                line_no integer,
                content_preview text,
                payload_json text
            )
            """
        )
        for item in messages:
            conn.execute(
                """
                insert into canonical_messages values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["message_id"],
                    item["source_system"],
                    item["session_id"],
                    item["canonical_window_id"],
                    item["project_id"],
                    item["source_path"],
                    item["raw_path"],
                    item["role"],
                    item["timestamp"],
                    item["source_offset_start"],
                    item["source_offset_end"],
                    item["raw_offset_start"],
                    item["raw_offset_end"],
                    item["line_no"],
                    item["content_preview"],
                    item["payload_json"],
                ),
            )
        conn.commit()
    return tempdir, db_path


def _compact_report(report: dict[str, Any], *, shelf: str) -> dict[str, Any]:
    steps = report.get("steps") if isinstance(report.get("steps"), dict) else {}
    return {
        "shelf": shelf,
        "input_records": report.get("input_records", report.get("total_raw", 0)),
        "owner_sample_count": len(report.get("owner_sample") or []),
        "candidate_object_count": len(report.get("candidate_objects") or []),
        "steps": steps,
    }


def distill_session(session: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """Return evidence-bound candidates for one canonical session.

    Intended import path for the coverage runner:
    ``src.distill_runtime_adapter:distill_session``.
    """

    _set_model_env(model)
    root = _root()
    records_db = _records_db(root)
    source_system = str(session.get("source_system") or "").strip()
    session_id = str(session.get("session_id") or "").strip()
    if not session_id:
        return {"candidates": [], "skip_reason": "session_id_missing"}
    temp_records: tempfile.TemporaryDirectory[str] | None = None
    if source_system_uses_distill_checkpoint_adapter(
        source_system,
        index_status=str(session.get("index_status") or ""),
        kind="checkpoint_markdown_sections",
    ):
        messages = mimocode_checkpoint_messages_for_session(session)
        if not messages:
            return {"candidates": [], "skip_reason": "mimocode_checkpoint_missing_or_empty"}
        temp_records, records_db = _write_temp_records_db_for_messages(messages)
    if not records_db.is_file():
        return {"candidates": [], "skip_reason": "records_db_missing"}

    target_shapes = {
        str(item or "").strip()
        for item in ([model.get("target_shape")] + list(model.get("target_shapes") or []))
        if str(item or "").strip()
    }
    deep_distill = bool(target_shapes & {DEEP_DISTILL_TARGET_SHAPE, MIMOCODE_DEEP_DISTILL_TARGET_SHAPE})
    only_targeted = bool(target_shapes)
    if deep_distill:
        zhiyi_limit = _int_env("TIME_LIBRARY_DEEP_DISTILL_ZHIYI_PER_SESSION", 3)
        xingce_limit = _int_env("TIME_LIBRARY_DEEP_DISTILL_XINGCE_PER_ROLE", 3)
        raw_scan_limit = _int_env("TIME_LIBRARY_DEEP_DISTILL_RAW_SCAN_LIMIT", 5000)
        xingce_roles = [
            role.strip()
            for role in str(os.environ.get("TIME_LIBRARY_DEEP_DISTILL_XINGCE_ROLES") or "assistant,user").split(",")
            if role.strip()
        ]
    else:
        zhiyi_limit = 0 if only_targeted and "zhiyi" not in target_shapes else _int_env("TIME_LIBRARY_DISTILL_ZHIYI_PER_SESSION", 1)
        xingce_limit = 0 if only_targeted and "xingce" not in target_shapes else _int_env("TIME_LIBRARY_DISTILL_XINGCE_PER_SESSION", 1)
        raw_scan_limit = _int_env("TIME_LIBRARY_DISTILL_RAW_SCAN_LIMIT", 600)
        xingce_roles = [os.environ.get("TIME_LIBRARY_DISTILL_XINGCE_ROLE", "assistant")]
    toolbook_limit = _int_env("TIME_LIBRARY_DISTILL_TOOLBOOK_PER_SESSION", 1) if "toolbook" in target_shapes else 0
    project_history_limit = _int_env("TIME_LIBRARY_DISTILL_PROJECT_HISTORY_PER_SESSION", 1) if "project_history_digest" in target_shapes else 0
    candidates: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    reject_reasons: list[str] = []

    try:
        if zhiyi_limit:
            zhiyi = _load_tool_module("zhiyi_distill")
            zhiyi_report = zhiyi.run_pipeline(
                root,
                input_source=zhiyi.INPUT_SOURCE_RAW_USER,
                dry_run=True,
                sample=zhiyi_limit,
                raw_scan_limit=raw_scan_limit,
                records_db=records_db,
                raw_source_system=source_system,
                raw_session_id=session_id,
                model_distill=True,
                model_distill_limit=zhiyi_limit,
                model_retry_non_json=1,
            )
            candidates.extend([dict(item) for item in zhiyi_report.get("owner_sample") or [] if isinstance(item, dict)])
            reports.append(_compact_report(zhiyi_report, shelf="zhiyi"))
            s3 = (zhiyi_report.get("steps") or {}).get("S3_validate") or {}
            reject_reasons.extend(str(k) for k in (s3.get("fail_reasons") or {}).keys())

        if xingce_limit:
            xingce = _load_tool_module("xingce_distill")
            for role in xingce_roles:
                xingce_report = xingce.run_pipeline(
                    str(root),
                    input_source=xingce.INPUT_SOURCE_CANONICAL_MESSAGES,
                    dry_run=True,
                    sample=xingce_limit,
                    raw_scan_limit=raw_scan_limit,
                    records_db=records_db,
                    raw_source_system=source_system,
                    raw_session_id=session_id,
                    raw_role=role,
                    model_distill=True,
                    model_distill_limit=xingce_limit,
                )
                candidates.extend([dict(item) for item in xingce_report.get("candidate_objects") or [] if isinstance(item, dict)])
                reports.append(_compact_report(xingce_report, shelf=f"xingce:{role}"))
                s3 = (xingce_report.get("steps") or {}).get("S3_validate") or {}
                reject_reasons.extend(str(k) for k in (s3.get("failure_reasons") or {}).keys())

        if toolbook_limit:
            toolbook = _load_tool_module("toolbook_distill")
            toolbook_report = toolbook.run_pipeline(
                str(root),
                input_source=toolbook.INPUT_SOURCE_CANONICAL_MESSAGES,
                dry_run=True,
                sample=toolbook_limit,
                raw_scan_limit=raw_scan_limit,
                records_db=records_db,
                raw_source_system=source_system,
                raw_session_id=session_id,
                model_distill=False,
                model_distill_limit=toolbook_limit,
            )
            candidates.extend([dict(item) for item in toolbook_report.get("candidate_objects") or [] if isinstance(item, dict)])
            reports.append(_compact_report(toolbook_report, shelf="toolbook"))
            s3 = (toolbook_report.get("steps") or {}).get("S3_validate") or {}
            reject_reasons.extend(str(k) for k in (s3.get("fail_reasons") or {}).keys())

        if project_history_limit:
            project_history = _load_tool_module("project_history_distill")
            history_report = project_history.run_pipeline(
                str(root),
                input_source=getattr(project_history, "INPUT_SOURCE_CANONICAL_MESSAGES", "canonical_messages"),
                dry_run=True,
                sample=project_history_limit,
                raw_scan_limit=raw_scan_limit,
                records_db=records_db,
                raw_source_system=source_system,
                raw_session_id=session_id,
                model_distill=True,
                model_distill_limit=project_history_limit,
            )
            candidates.extend([dict(item) for item in history_report.get("candidate_objects") or [] if isinstance(item, dict)])
            reports.append(_compact_report(history_report, shelf="project_history"))
            s3 = (history_report.get("steps") or {}).get("S3_validate") or {}
            reject_reasons.extend(str(k) for k in (s3.get("fail_reasons") or {}).keys())
    finally:
        if temp_records is not None:
            temp_records.cleanup()

    return {
        "contract": DISTILL_RUNTIME_ADAPTER_CONTRACT,
        "candidates": candidates,
        "reports": reports,
        "reject_reasons": sorted(set(reason for reason in reject_reasons if reason)),
        "skip_reason": "" if candidates else "no_evidence_bound_candidates",
    }


__all__ = [
    "DISTILL_RUNTIME_ADAPTER_CONTRACT",
    "MIMOCODE_CHECKPOINT_ADAPTER_CONTRACT",
    "distill_session",
    "mimocode_checkpoint_messages_for_session",
]
