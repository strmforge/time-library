#!/usr/bin/env python3
"""Extract evidence-bound toolbook facts from canonical raw messages.

Toolbook is the objective-fact shelf: paths, ports, configuration, platform
properties, and runbook snippets.  This extractor deliberately stays small and
source-bound; the automation runner owns durable candidate writes, de-dupe, and
post-window delivery self-checks.
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

try:
    from src.toolbook_quality import (
        clean_toolbook_fact_title,
        is_low_quality_toolbook_record,
        is_one_time_status_report,
        is_windows_app_rdp_fact,
    )
except Exception:  # pragma: no cover
    from toolbook_quality import (
        clean_toolbook_fact_title,
        is_low_quality_toolbook_record,
        is_one_time_status_report,
        is_windows_app_rdp_fact,
    )


TOOLBOOK_DISTILL_CONTRACT = "time_library_toolbook_distill.v1"
INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"
DEFAULT_OUTPUT_REL = "output/toolbook_platform_facts"

_TOOL_FACT_KEYWORDS = (
    "路径",
    "端口",
    "配置",
    "环境变量",
    "启动",
    "重启",
    "命令",
    "脚本",
    "回执",
    "sha",
    "pid",
    "mcp",
    "http://",
    "https://",
    "launchd",
    "launchctl",
    "plist",
    "config",
    "runtime",
    "gateway",
    "catalog-card",
    "catalog-inject",
    "records.db",
    "远程桌面",
    "rdp",
    "windows app",
    "microsoft",
    ".jsonl",
    ".md",
    ".py",
    "/volumes/",
    "/users/",
    "src/",
    "tools/",
    "output/",
)
_PATH_RE = re.compile(r"(/Volumes/[^\s`'\"，。；;]+|/Users/[^\s`'\"，。；;]+|(?:src|tools|output|config)/[^\s`'\"，。；;]+)")
_PORT_RE = re.compile(r"\b(?:[1-9][0-9]{2,4})\b")
_ENV_RE = re.compile(r"\b[A-Z][A-Z0-9_]{4,}\b")
_NOISY_ATTACHMENT_MARKERS = (
    "# files mentioned by the user:",
    "files mentioned by the user",
    "<image name=",
    "data:image/",
    "input_image",
    "base64,",
    "<environment_context>",
    "<filesystem>",
    "<current_date>",
)
_LOW_QUALITY_SUMMARY_TEXT = {"记好了", "收到", "成了", "好的", "明白"}


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


def _fact_type(text: str) -> str:
    lower = text.lower()
    if is_windows_app_rdp_fact(text):
        return "platform_fact"
    if "端口" in text or "port" in lower or "http://" in lower or "https://" in lower:
        if _PORT_RE.search(text):
            return "port_or_endpoint"
    if _PATH_RE.search(text) or ".jsonl" in lower or ".md" in lower or ".py" in lower:
        return "path_or_file"
    if "配置" in text or "环境变量" in text or "config" in lower or _ENV_RE.search(text):
        return "configuration"
    if any(token in lower for token in ("launchctl", "curl", "python", "pytest", "重启", "启动", "命令", "脚本")):
        return "runbook"
    return "platform_fact"


def _fact_type_label(fact_type: str) -> str:
    return {
        "port_or_endpoint": "端口/端点",
        "path_or_file": "路径/文件",
        "configuration": "配置",
        "runbook": "运行手册",
        "platform_fact": "平台事实",
    }.get(fact_type, "平台事实")


def _looks_like_tool_fact(text: str) -> bool:
    compact = _clean(text, limit=1200)
    if len(compact) < 12:
        return False
    if _looks_like_noisy_attachment_payload(compact):
        return False
    if is_low_quality_toolbook_record(compact):
        return False
    if is_one_time_status_report(compact):
        return False
    lower = compact.lower()
    if any(keyword in lower or keyword in compact for keyword in _TOOL_FACT_KEYWORDS):
        return True
    return bool(_PATH_RE.search(compact) or _ENV_RE.search(compact))


def _looks_like_noisy_attachment_payload(text: str) -> bool:
    lower = str(text or "").lower()
    return any(marker in lower for marker in _NOISY_ATTACHMENT_MARKERS)


def _clean_toolbook_title(summary: str, fact_type: str) -> str:
    return clean_toolbook_fact_title(summary, summary=summary, fact_type=_fact_type_label(fact_type))[:80]


def _objective_fact_summary(text: str, fact_type: str) -> str:
    compact = _clean(text, limit=1000)
    segments = [item.strip(" *`:-：") for item in re.split(r"[。；;\n]+", compact) if item.strip()]

    def score(segment: str) -> int:
        lower = segment.lower()
        if _low_quality_summary(segment):
            return -10
        if is_one_time_status_report(segment):
            return -10
        value = 0
        if _PATH_RE.search(segment):
            value += 4
        if _PORT_RE.search(segment):
            value += 3
        if _ENV_RE.search(segment):
            value += 2
        if any(keyword in lower or keyword in segment for keyword in _TOOL_FACT_KEYWORDS):
            value += 2
        if any(keyword in segment for keyword in ("验收", "步骤", "命令", "端口", "路径", "配置", "回源", "借书")):
            value += 2
        return value

    ranked = sorted(((score(segment), index, segment) for index, segment in enumerate(segments)), key=lambda item: (-item[0], item[1]))
    for value, _index, segment in ranked:
        if value > 0 and not _low_quality_summary(segment) and not is_one_time_status_report(segment):
            return _clean(segment, limit=220)
    fallback = segments[0] if segments else compact
    return "" if _low_quality_summary(fallback) else (_clean(fallback, limit=220) or _fact_type_label(fact_type))


def _low_quality_summary(text: str) -> bool:
    if _clean(text, limit=80).strip("。.!！ ") in _LOW_QUALITY_SUMMARY_TEXT:
        return True
    return is_low_quality_toolbook_record(text)


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


def _candidate_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    content = str(row.get("content") or "")
    if not _looks_like_tool_fact(content):
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
    if _looks_like_noisy_attachment_payload(content) or _looks_like_noisy_attachment_payload(verbatim):
        return None
    if is_one_time_status_report(content) or is_one_time_status_report(verbatim):
        return None
    fact_type = _fact_type(content or verbatim)
    summary = _objective_fact_summary(content or verbatim, fact_type)
    if not summary:
        return None
    title = _clean_toolbook_title(summary, fact_type)
    seed = json.dumps(
        {
            "fact_type": fact_type,
            "summary": summary.lower(),
            "source_system": row.get("source_system"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    role = _clean(row.get("role"), limit=80).lower() or "assistant"
    sha = hashlib.sha256(raw).hexdigest()
    source_mode = "evidence_bound_p2_extract"
    source_refs = {
        "source_system": row.get("source_system") or "",
        "source_path": str(source_file),
        "source_role": role,
        "source_author": role,
        "session_id": row.get("session_id") or "",
        "canonical_window_id": row.get("canonical_window_id") or "",
        "project_id": row.get("project_id") or "",
        "message_id": row.get("message_id") or "",
        "line_no": row.get("line_no"),
        "artifact_type": "canonical_message",
        "byte_offsets": {"start": start_i, "end": end_i},
        "source_mode": source_mode,
        "verbatim_sha256": sha,
    }
    return {
        "candidate_id": f"toolbook-p2-{digest}",
        "candidate_type": "toolbook_candidate",
        "_type": "toolbook_candidate",
        "type": "toolbook_candidate",
        "library_shelf": "toolbook",
        "lifecycle_status": "candidate",
        "title": title,
        "summary": summary,
        "detail": summary,
        "platform": row.get("source_system") or "local",
        "environment": row.get("canonical_window_id") or row.get("session_id") or "",
        "fact_type": fact_type,
        "observed_behavior": summary,
        "applicable_scope": row.get("source_system") or "",
        "verbatim_excerpt": verbatim,
        "verbatim_sha256": sha,
        "source_path": source_file,
        "source_ref": f"{source_file}:{start_i}-{end_i}",
        "byte_offsets": {"start": start_i, "end": end_i},
        "source_author": role,
        "source_role": role,
        "source_mode": source_mode,
        "source_refs": source_refs,
        "dedupe_key": "toolbook:" + hashlib.sha256(f"{fact_type}|{summary.lower()}".encode("utf-8")).hexdigest()[:20],
        "supersedes": [],
        "conflicts_with": [],
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
    model_distill: bool = False,
    model_distill_limit: int = 0,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root).expanduser()
    output_path = Path(output_root).expanduser() if output_root else root_path / DEFAULT_OUTPUT_REL
    records = _canonical_rows(
        records_db or _records_db_path(root_path),
        source_system=raw_source_system,
        session_id=raw_session_id,
        scan_limit=raw_scan_limit,
    )
    selected = [row for row in records if _looks_like_tool_fact(str(row.get("content") or ""))]
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
        if not dry_run:
            out = output_path / "candidates"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{candidate['candidate_id']}.json").write_text(
                json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    return {
        "ok": True,
        "contract": TOOLBOOK_DISTILL_CONTRACT,
        "created_at": _now(),
        "input_source": input_source,
        "dry_run": dry_run,
        "read_only_raw": True,
        "raw_write_performed": False,
        "toolbook_write_performed": False,
        "records_db": str(Path(records_db).expanduser()) if records_db else str(_records_db_path(root_path)),
        "raw_scan_limit": raw_scan_limit,
        "raw_source_system": raw_source_system,
        "raw_session_id": raw_session_id,
        "model_distill_enabled": bool(model_distill),
        "input_records": len(records),
        "output_root": str(output_path),
        "candidate_objects": candidates,
        "steps": {
            "S0_select": {
                "selected": len(selected),
                "rejected": max(0, len(records) - len(selected)),
            },
            "S2_p2_extract": {
                "attempted": len(selected),
                "facts": len(candidates),
            },
            "S3_validate": {
                "passed": len(candidates),
                "failed": sum(fail_reasons.values()),
                "fail_reasons": fail_reasons,
            },
            "S5_write": {"written_candidate_files": 0 if dry_run else len(candidates)},
        },
        "nonclaims": [
            "objective_fact_extraction_only_not_preference_or_work_experience",
            "automation_runner_must_validate_byte_exact_before_durable_candidate_write",
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
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    report = run_pipeline(
        args.root,
        dry_run=not args.write,
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
