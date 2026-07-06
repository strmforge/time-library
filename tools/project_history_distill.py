#!/usr/bin/env python3
"""Extract evidence-bound project history records from canonical messages.

Project history is not a sixth shelf. This tool emits candidate objects for the
automation runner, and the runner writes accepted records into the reading-area
registry/project page history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_HISTORY_DISTILL_CONTRACT = "time_library_project_history_distill.v1"
PROJECT_HISTORY_SOURCE_MODE = "evidence_bound_project_history_digest"
INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

_HISTORY_SIGNAL_RE = re.compile(
    r"(想象者拍板|裁定|定盘|决定|结论|方向纠正|里程碑|收口|交接|handoff|"
    r"北极星|验收|签字|opus_confirmed|runtime|全量收官|开题|授权)",
    re.IGNORECASE,
)
_ONE_OFF_NOISE_RE = re.compile(
    r"(pytest|py_compile|git diff|curl |lsof |launchctl|SHA×|PID=|source==installed|"
    r"回报格式|禁止跑偏|命令证据|max_tokens|token|stdout|stderr)",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value: Any, *, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _records_db_path(root: str | Path) -> Path:
    override = os.environ.get("MEMCORE_RECORDS_DB", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(root).expanduser() / "output" / "records" / "records.db"


def _message_text_from_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        parts: list[str] = []
        for item in payload:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("text", "content"):
                    if isinstance(item.get(key), str):
                        parts.append(item[key])
                        break
        return "\n".join(part for part in parts if part)
    if isinstance(payload, dict):
        for key in ("content", "text", "message"):
            text = _message_text_from_payload(payload.get(key))
            if text:
                return text
    return ""


def _canonical_rows(
    records_db: str | Path,
    *,
    source_system: str = "",
    session_id: str = "",
    scan_limit: int = 5000,
) -> list[dict[str, Any]]:
    db_path = Path(records_db).expanduser()
    if not db_path.is_file():
        return []
    where = [
        "((raw_offset_start is not null and raw_offset_end is not null) "
        "or (source_offset_start is not null and source_offset_end is not null))",
    ]
    params: list[Any] = []
    if source_system:
        where.append("source_system=?")
        params.append(source_system)
    if session_id:
        where.append("session_id=?")
        params.append(session_id)
    sql = f"""
        select message_id, source_system, session_id, canonical_window_id, project_id,
               source_path, raw_path, role, timestamp,
               source_offset_start, source_offset_end,
               raw_offset_start, raw_offset_end,
               line_no, content_preview, payload_json
        from canonical_messages
        where {' and '.join(where)}
        order by timestamp desc, line_no desc
        limit ?
    """
    params.append(max(1, int(scan_limit or 5000)))
    rows: list[dict[str, Any]] = []
    with sqlite3.connect(db_path) as conn:
        for row in conn.execute(sql, params).fetchall():
            payload: dict[str, Any] = {}
            try:
                payload = json.loads(row[15] or "{}")
            except json.JSONDecodeError:
                payload = {}
            source_line = payload.get("source_line") if isinstance(payload.get("source_line"), dict) else {}
            content = _message_text_from_payload(source_line.get("content")) or str(row[14] or "")
            rows.append(
                {
                    "message_id": row[0],
                    "source_system": row[1],
                    "session_id": row[2],
                    "canonical_window_id": row[3],
                    "project_id": row[4],
                    "source_path": row[5],
                    "raw_path": row[6],
                    "role": row[7],
                    "timestamp": row[8],
                    "source_offset_start": row[9],
                    "source_offset_end": row[10],
                    "raw_offset_start": row[11],
                    "raw_offset_end": row[12],
                    "line_no": row[13],
                    "content": content,
                }
            )
    return rows


def _existing_source_file(source_path: str, raw_path: str) -> str:
    for value in (raw_path, source_path):
        text = str(value or "").strip()
        if text and Path(text).expanduser().is_file():
            return text
    return str(raw_path or source_path or "").strip()


def _source_slice(source_path: str, start: int, end: int) -> tuple[bytes, str]:
    if not source_path or start < 0 or end <= start:
        return b"", ""
    path = Path(source_path).expanduser()
    if not path.is_file() or path.stat().st_size < end:
        return b"", ""
    with path.open("rb") as f:
        f.seek(start)
        raw = f.read(end - start)
    return raw, raw.decode("utf-8", errors="ignore")


def _history_type(text: str) -> str:
    lower = text.lower()
    if "交接" in text or "handoff" in lower or "接棒" in text:
        return "handoff"
    if "裁定" in text or "拍板" in text or "决定" in text or "定盘" in text:
        return "decision"
    if "checkpoint" in lower or "节点" in text:
        return "checkpoint"
    return "milestone"


def _looks_like_project_history(text: str) -> bool:
    compact = _clean(text, limit=1600)
    if len(compact) < 12:
        return False
    if not _HISTORY_SIGNAL_RE.search(compact):
        return False
    if _ONE_OFF_NOISE_RE.search(compact) and not any(token in compact for token in ("想象者拍板", "裁定", "定盘", "收口")):
        return False
    return True


def _title_from_text(text: str, history_type: str) -> str:
    compact = _clean(text, limit=220)
    if compact.startswith("【") and "】" in compact[:80]:
        compact = compact[1:compact.index("】")]
    fragments = [item.strip(" 。，；:：[]【】") for item in re.split(r"[。；;\n]+", compact) if item.strip()]
    title = fragments[0] if fragments else compact
    title = re.sub(r"^(想象者拍板|Opus 裸签|Opus 二签|Codex|MiniMax-M3)[·：:\s-]*", "", title)
    if not title:
        title = {"decision": "项目决策", "handoff": "项目交接", "checkpoint": "项目节点"}.get(history_type, "项目里程碑")
    return _clean(title, limit=80)


def _summary_from_text(text: str) -> str:
    fragments = [item.strip(" 。，；:：[]【】") for item in re.split(r"[。；;\n]+", _clean(text, limit=800)) if item.strip()]
    if not fragments:
        return _clean(text, limit=220)
    return _clean("；".join(fragments[:2]), limit=220)


def _candidate_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    content = str(row.get("content") or "")
    if not _looks_like_project_history(content):
        return None
    source_file = _existing_source_file(str(row.get("source_path") or ""), str(row.get("raw_path") or ""))
    start = row.get("raw_offset_start") if row.get("raw_offset_start") is not None else row.get("source_offset_start")
    end = row.get("raw_offset_end") if row.get("raw_offset_end") is not None else row.get("source_offset_end")
    try:
        start_i = int(start)
        end_i = int(end)
    except (TypeError, ValueError):
        return None
    raw, verbatim = _source_slice(source_file, start_i, end_i)
    if not raw or not verbatim:
        return None
    history_type = _history_type(content)
    title = _title_from_text(content, history_type)
    summary = _summary_from_text(content)
    role = _clean(row.get("role"), limit=80).lower() or "assistant"
    sha = hashlib.sha256(raw).hexdigest()
    seed = json.dumps(
        {
            "title": title,
            "summary": summary,
            "source_system": row.get("source_system"),
            "session_id": row.get("session_id"),
            "start": start_i,
            "end": end_i,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    source_refs = {
        "source_system": row.get("source_system") or "",
        "source_path": str(source_file),
        "source_role": role,
        "source_author": role,
        "session_id": row.get("session_id") or "",
        "canonical_window_id": row.get("canonical_window_id") or "",
        "message_id": row.get("message_id") or "",
        "line_no": row.get("line_no"),
        "artifact_type": "canonical_message",
        "byte_offsets": {"start": start_i, "end": end_i},
        "source_mode": PROJECT_HISTORY_SOURCE_MODE,
        "verbatim_sha256": sha,
        "verbatim_excerpt": verbatim,
    }
    return {
        "candidate_id": f"project-history-{digest}",
        "candidate_type": "project_history_digest",
        "history_type": history_type,
        "title": title,
        "summary": summary,
        "verbatim_excerpt": verbatim,
        "verbatim_sha256": sha,
        "source_author": role,
        "source_role": role,
        "source_mode": PROJECT_HISTORY_SOURCE_MODE,
        "source_refs": source_refs,
        "created_at": _now(),
    }


def run_pipeline(
    root: str | Path,
    *,
    input_source: str = INPUT_SOURCE_CANONICAL_MESSAGES,
    dry_run: bool = True,
    sample: int = 0,
    raw_scan_limit: int = 5000,
    records_db: str | Path = "",
    raw_source_system: str = "",
    raw_session_id: str = "",
    model_distill: bool = True,
    model_distill_limit: int = 0,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root).expanduser()
    records = _canonical_rows(
        records_db or _records_db_path(root_path),
        source_system=raw_source_system,
        session_id=raw_session_id,
        scan_limit=raw_scan_limit,
    )
    selected = [row for row in records if _looks_like_project_history(str(row.get("content") or ""))]
    limit = int(model_distill_limit or sample or len(selected) or 0)
    if limit > 0:
        selected = selected[:limit]
    candidates: list[dict[str, Any]] = []
    fail_reasons: dict[str, int] = {}
    for row in selected:
        candidate = _candidate_from_row(row)
        if candidate is None:
            fail_reasons["source_slice_unavailable"] = fail_reasons.get("source_slice_unavailable", 0) + 1
            continue
        candidates.append(candidate)
    return {
        "ok": True,
        "contract": PROJECT_HISTORY_DISTILL_CONTRACT,
        "created_at": _now(),
        "input_source": input_source,
        "dry_run": dry_run,
        "read_only_raw": True,
        "raw_write_performed": False,
        "project_history_write_performed": False,
        "project_history_not_a_sixth_shelf": True,
        "records_db": str(Path(records_db).expanduser()) if records_db else str(_records_db_path(root_path)),
        "raw_scan_limit": raw_scan_limit,
        "raw_source_system": raw_source_system,
        "raw_session_id": raw_session_id,
        "model_distill_enabled": bool(model_distill),
        "input_records": len(records),
        "candidate_objects": candidates,
        "steps": {
            "S0_select": {
                "selected": len(selected),
                "rejected": max(0, len(records) - len(selected)),
            },
            "S2_project_history_digest": {
                "attempted": len(selected),
                "digests": len(candidates),
            },
            "S3_validate": {
                "passed": len(candidates),
                "failed": sum(fail_reasons.values()),
                "fail_reasons": fail_reasons,
            },
            "S5_write": {"written_candidate_files": 0},
        },
        "nonclaims": [
            "project_history_candidates_only_runner_writes_registry_records",
            "not_a_sixth_shelf",
            "installed_runtime_not_signed_by_this_module",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("MEMCORE_ROOT", "."))
    parser.add_argument("--records-db", default="")
    parser.add_argument("--raw-source-system", default="")
    parser.add_argument("--raw-session-id", default="")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--raw-scan-limit", type=int, default=5000)
    args = parser.parse_args(argv)
    report = run_pipeline(
        args.root,
        sample=args.sample,
        raw_scan_limit=args.raw_scan_limit,
        records_db=args.records_db,
        raw_source_system=args.raw_source_system,
        raw_session_id=args.raw_session_id,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
