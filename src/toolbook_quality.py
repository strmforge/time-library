#!/usr/bin/env python3
"""Quality helpers for Time Library toolbook candidates."""

from __future__ import annotations

import re
from typing import Any


def _clean(value: Any, *, limit: int = 1200) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def toolbook_text_from_record(record: dict[str, Any]) -> str:
    return "\n".join(
        str(record.get(key) or "")
        for key in ("title", "summary", "detail", "observed_behavior", "verbatim_excerpt")
    )


def is_one_time_status_report(text_or_record: Any) -> bool:
    if isinstance(text_or_record, dict):
        text = toolbook_text_from_record(text_or_record)
    else:
        text = str(text_or_record or "")
    compact = _clean(text, limit=1200)
    lower = compact.lower()
    if not compact:
        return False
    report_re = re.compile(
        r"(这轮|本轮|今早|今天|昨晚|已按|我在|codex|opus).{0,80}"
        r"(签|验|回执|报告|施工|收口|放行|写了|跑完|核)",
        re.IGNORECASE,
    )
    if report_re.search(compact):
        return True
    if "回执" in compact and any(marker in lower or marker in compact for marker in ("nonclaims", "byte-exact", "sha-match", "裸窗", "裸验", "裸签", "二签", "签字")):
        return True
    if any(phrase in compact for phrase in ("接手笔记", "施工稿", "签字层级", "命令证据", "回报格式")):
        return True
    return False


def is_low_quality_toolbook_record(text_or_record: Any) -> bool:
    if isinstance(text_or_record, dict):
        text = toolbook_text_from_record(text_or_record)
    else:
        text = str(text_or_record or "")
    compact = _clean(text, limit=1600)
    if not compact:
        return False
    lower = compact.lower()
    if is_one_time_status_report(compact):
        return True
    if re.search(r"^={2,}\s*top-level keys\s*={2,}", compact, re.IGNORECASE):
        return True
    if "tool_use_id" in lower and "type\":\"tool_result" in lower:
        return True
    if "tool_use_id" in lower and "tool_result" in lower:
        return True
    if "has been updated successfully" in lower and "file state is current" in lower:
        return True
    if "sourceToolAssistantUUID" in compact or "toolUseResult" in compact:
        return True
    if re.search(r"\bbox-shadow\s*:\s*[^;]+;", compact, re.IGNORECASE):
        return True
    if re.search(r"^\s*(stdout|stderr|interrupted|isimage|nooutputexpected)\s*[:=]", lower):
        return True
    if "=== size of each top key" in lower:
        return True
    if "Time Library能力检查结果" in compact and "capability" in lower:
        return True
    return False


def clean_toolbook_fact_title(title: str, *, summary: str = "", fact_type: str = "") -> str:
    text = _clean(title, limit=180).strip("。.!！ ")
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"^工具事实[：:]\s*", "", text)
    text = re.sub(r"^(端口/端点|路径/文件|配置|运行手册|平台事实)\s+", "", text)
    text = re.sub(r"^(最简单官方方案|官方方案|建议|事实)[：:]\s*", "", text)
    combined = f"{text} {summary}".lower()
    if (
        "macos" in combined
        and "microsoft" in combined
        and "windows app" in combined
        and ("rdp" in combined or "远程桌面" in text or "远程桌面" in summary)
        and re.search(r"(连|连接)\s*windows", f"{text} {summary}", re.IGNORECASE)
    ):
        return "macOS 用 Microsoft Windows App 连远程桌面"
    return text or _clean(fact_type, limit=80) or "工具事实"


def is_windows_app_rdp_fact(text: str) -> bool:
    lower = str(text or "").lower()
    return (
        "macos" in lower
        and "microsoft" in lower
        and "windows app" in lower
        and ("rdp" in lower or "远程桌面" in str(text or ""))
        and re.search(r"(连|连接)\s*windows", str(text or ""), re.IGNORECASE) is not None
    )
