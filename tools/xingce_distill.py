#!/usr/bin/env python3
"""S0→S5 raw→Xingce candidate distillation pipeline.

Reads seed records from time_library JSONL (case_memory, error_memory, preference_memory),
traces back to raw source files via source_refs.source_path for verbatim verification,
applies pollution/reject guard, extracts evidence-bound work-experience cards,
and writes to output/xingce_work_experience/candidates/.

Usage:
  python tools/xingce_distill.py [--dry-run] [--sample N] [--root PATH]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from src.p2_extract import tool_result_pollution_guard
except ImportError:
    tool_result_pollution_guard = None

try:
    from src.evidence_bound_model import (
        run_evidence_bound_experience_refinement,
        default_model_config,
        EvidenceBoundModelConfig,
    )
except ImportError:
    run_evidence_bound_experience_refinement = None
    default_model_config = None
    EvidenceBoundModelConfig = None


# --- Constants ---

AUTO_ACTION_STATUS = "auto_adopted_evidence_bound"
INPUT_SOURCE_MEMORY_RECORDS = "memory_records"
INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

_SEARCH_ROOTS = [
    str(Path(__file__).resolve().parents[1]),
    "/Volumes/京造/忆凡尘施工区/",
    os.path.expanduser("~/Library/Application Support/memcore-cloud"),
    os.path.expanduser("~/memcore-cloud-x4"),
]


# --- Reject list patterns ---

_REJECT_VIDEO_SUBTITLE = re.compile(r"(字幕|subtitle|srt|vtt|\.srt|\.vtt)", re.IGNORECASE)
_REJECT_REPOST_ARTICLE = re.compile(r"(转载|repost|转发|原文出处|原文链接)", re.IGNORECASE)
_REJECT_SKILL_DUMP = re.compile(r"(skill_dump|技能转储|skill\.json|plugin\.json)", re.IGNORECASE)
_REJECT_SELF_TEST = re.compile(r"(self.?test|自测|冒烟测|smoke.?test)", re.IGNORECASE)
_REJECT_TEMPLATE_STUB = re.compile(
    r"(案例\.\.\.核心词\.\.\.上下文空|summary\s*=\s*head-?\d+\s*truncat|detail\s*=\s*whole\s*blob)",
    re.IGNORECASE,
)
_REJECT_AI_CONSTRUCTION = re.compile(
    r"(施工报告|施工前基线|施工后基线|本轮施工|本轮改动|本轮验证|"
    r"已(完成|修改|添加|删除|更新|创建|写入)了?\s*(施工|源码|代码|文件|测试)|"
    r"I('ve| have| just)?\s*(implemented|fixed|added|modified|updated|created|written)\s+(the|a|an|this)\s+\w+|"
    r"(This|The)\s+(change|commit|update|fix|patch)\s+(implements|adds|fixes|modifies))",
    re.IGNORECASE | re.MULTILINE,
)
_REJECT_TOOL_EXEC = re.compile(
    r"(exit[_\s]?code[:\s=]\s*\d+|stdout[:\s]|stderr[:\s]|Process exited with code|"
    r"Command exited with|Exec completed|Exec failed|tool_call_id|"
    r"pytest\s+\d+\s*(passed|failed)|py_compile)",
    re.IGNORECASE,
)
_REJECT_BASE64 = re.compile(r"[A-Za-z0-9+/=]{60,}")

_REJECT_CONSTRUCTION_STATUS = re.compile(
    r"(我会让测试|这轮我把|我先把它改|然后跑测试|现在残留的|本轮改动|"
    r"我会更严|我先改完|这轮改完|本轮把|我把这轮|"
    r"我已经把.*改成|我刚把.*改成|我已经修改了.*测试|我刚修改了.*测试|"
    r"下一步我修|再一起跑测试|脏改|"
    r"放进去了.*先接上|已经放进去了|路径解析模块已经放|"
    r"同步到运行版.*重启|再同步.*重启 9851|"
    r"现在进入验证|跑完我会停|我看到一个实现和文档|现在我集中看|"
    r"我接着这份审计往下收|动之前我会先确认|"
    r"兜底已经补上了.*我会全量跑|我会全量跑一遍|"
    r"代码已加[。,.].*补测试|"
    r"补齐了.*跑验证|统一跑验证|编译.*模块.*跑.*测试|"
    r"跑全量测试|"
    r"跑.{0,10}相关测试.*打包同步|"
    r"过了之后再重新打包同步|"
    r"现在跑.{0,15}(测试|验证).{0,30}(打包|同步|部署)|"
    r"修补已经落进源码|"
    r"(安装器|探测层|候选路径).{0,40}(复用|优先找))",
    re.IGNORECASE,
)

_AGENT_NARRATION_STARTS = [
    "我先确认", "我先查看", "我先看", "我先读", "我先跑", "我先测试", "我先验证",
    "我先分析", "我先检查", "我先打开", "我先执行", "我先运行", "我先开始",
    "我现在确认", "我现在查看", "我现在看", "我现在读", "我现在跑",
    "我确认", "我查看", "我分析", "我检查", "我验证",
    "我转去", "我去看", "我去确认", "我去查看",
    "现在我转去", "现在我去看", "现在我去确认", "现在我去查看",
    "现在我确认", "现在我查看", "现在我看", "现在我读", "现在我跑",
    "接下来我确认", "接下来我查看", "接下来我看",
    "然后我确认", "然后我查看", "然后我看",
    "验证通过：", "验证通过:",
    "那我刚才应该",
    "我接着这份",
    "我接着这个",
    "我看到一个",
    "现在进入验证",
    "现在我集中",
    "现在我接着",
    "我接着往下",
    "我接着这份审计",
    "兜底已经补上",
    "动之前我会",
]

_AGENT_PLAN_STATUS_PREFIXES = [
    "我会", "我先", "我再", "我现在", "现在我", "接下来我", "我已经",
    "我来", "我去", "我把这轮写进", "我去跑", "我还需要",
    "那我刚才", "我刚才", "我接着",
]



_SOURCE_ORIGIN_GUARD_PATTERNS = [
    re.compile(r"现在进入验证", re.IGNORECASE),
    re.compile(r"跑完我会停[在到]", re.IGNORECASE),
    re.compile(r"我看到一个实现和文档的", re.IGNORECASE),
    re.compile(r"现在我集中看", re.IGNORECASE),
    re.compile(r"我接着这份审计", re.IGNORECASE),
    re.compile(r"动之前我会先确认", re.IGNORECASE),
    re.compile(r"兜底已经补上了", re.IGNORECASE),
    re.compile(r"我会全量跑一遍", re.IGNORECASE),
    re.compile(r"我先(跑|测|试|验|改|修|看|确认|检查|验证).{0,15}(测试|验证|检查|跑完|通过)", re.IGNORECASE),
    re.compile(r"(已经|刚刚|刚).{0,10}(改|修|加|删|更新|写).{0,10}(好了|完了|上了|进去)", re.IGNORECASE),
    re.compile(r"我先用.{0,20}(验|测试|试跑|smoke)", re.IGNORECASE),
    re.compile(r"(smoke\s*message|能力检查模式).{0,40}(代码|测试|补上)", re.IGNORECASE),
    re.compile(r"只发一条\s*smoke\s*message", re.IGNORECASE),
    re.compile(r"冒烟测", re.IGNORECASE),
    re.compile(r"代码已加[。,.].*补测试", re.IGNORECASE),
    re.compile(r"命令用错了\s*import\s*路径", re.IGNORECASE),
    re.compile(r"我已经过了", re.IGNORECASE),
    re.compile(r"补齐了.*跑验证", re.IGNORECASE),
    re.compile(r"统一跑验证", re.IGNORECASE),
    re.compile(r"编译.*模块.*跑.*测试", re.IGNORECASE),
    re.compile(r"跑全量测试", re.IGNORECASE),
    re.compile(r"diff\s*check.*敏感词扫描", re.IGNORECASE),
]

# Generalized assistant/source_testing first-person operational/status patterns.
# These match anywhere in the text (not just prefix), but only when participant
# roles include 'assistant' or 'source_testing'.
_ASSISTANT_OP_ANYWHERE = [
    re.compile(r"我.{0,80}(代码|测试|实现|验证|验收|编译|打包|传到|覆盖|备份|施工|补|写进|记录|同步|重启|部署|摸清|跑|读样本|管线)"),
    re.compile(r"我把.{0,20}(写进|放进|改成|写入|同步到|记录到)"),
    re.compile(r"我看完.{0,240}现在我开始.{0,30}(代码|测试|实现|补|写)"),
    re.compile(r"我现在.{0,20}(打包|开始|加|补|写|传|覆盖|同步|部署|重启|跑|验)"),
    re.compile(r"我只做.{0,20}(复盘|只读|审查|检查|确认)"),
    re.compile(r"现在我(补看|补查|补审|接着看|接着查|继续看|往下看)"),
    re.compile(r"我(补看|补查|补审)"),
    re.compile(r"我会(明确写|写明|注明|记录)"),
    re.compile(r"下一刀我会"),
    re.compile(r"先读样本字段"),
    re.compile(r"刚才.{0,30}(已经确认|已经验证|已经过了).{0,40}(现在我|我)"),
    re.compile(r"(验收|验证).{0,10}(写进|记录到|放进)"),
]


def _source_origin_guard(text: str, participant_attr: dict = None) -> Tuple[bool, str]:
    """Block assistant construction/verification/status sources from entering owner samples.

    Returns (blocked, reason).
    """
    t = text.strip()
    if not t:
        return False, ""

    roles = (participant_attr or {}).get("roles", [])
    trusted_user = "user" in roles
    is_assistant_or_testing = "assistant" in roles or ("source_testing" in roles and not trusted_user)

    if not trusted_user:
        for pat in _SOURCE_ORIGIN_GUARD_PATTERNS:
            if pat.search(t):
                return True, "source_origin_guard"

    if is_assistant_or_testing:
        if _is_agent_narration(t) or _is_agent_plan_status(t):
            return True, "source_origin_assistant_in_roles"
        for pat in _ASSISTANT_OP_ANYWHERE:
            if pat.search(t):
                return True, "source_origin_assistant_op"
        if _REJECT_CONSTRUCTION_STATUS.search(t):
            return True, "source_origin_construction_status"

    return False, ""


_WE_STRONG = re.compile(
    r"(不建议|不推荐|不应该|必须|一定要|千万别|核心是|关键在于|本质是|"
    r"先.*再|先.*然后|隔离.*试跑|试跑.*隔离|"
    r"should not|must|never|critical|essential|key\s+(insight|lesson|takeaway))",
    re.IGNORECASE,
)

_WE_ACTIONABLE = re.compile(
    r"(建议|应该|需要|做法|策略|步骤|方法|修|改|升级|评估|确认|验证|检查|"
    r"recommend|should|approach|strategy|step|fix|upgrade|assess|verify|check)",
    re.IGNORECASE,
)


_BLOB_INDICATOR = re.compile(r'^[\s]*[-•*]\s+\*\*')

_OWNER_SAMPLE_PREFILTER_REJECT = re.compile(
    r"(施工报告|施工前基线|施工后基线|本轮施工|本轮改动|本轮验证|"
    r"修补已经落进源码|跑相关测试.*打包同步|"
    r"同步到运行版|再同步.*重启|"
    r"接入验证|解析闸门|联调|干跑|未命中|"
    r"写入线|改完|接下来先跑|先跑编译|fallback|"
    r"代码修改验证阶段|最贴近的测试|测试用例|"
    r"本机真实发现结果|工具发现结果|验证工具发现|"
    r"应该已经\s*ready|保持无写入目标|预期路径被发现|发现机制|"
    r"焦点测试全过|重新打包|覆盖到\s*Windows|"
    r"显式全扫|全量扫描|默认接口秒回|接口秒回|"
    r"轻量版部署|部署到目标环境|部署验证|"
    r"exit[_\s]?code|stdout[:\s]|stderr[:\s]|"
    r"pytest\s+\d+\s*(passed|failed)|py_compile|"
    r"source_testing)",
    re.IGNORECASE,
)


def _owner_sample_prefilter(card: dict) -> Tuple[bool, str]:
    """Pre-filter cards for owner sample shortlist.

    Returns (suitable, reason). Cards must be:
    - Non-construction status
    - Non source_testing operational report
    - Non blob
    - Non public naming leak
    - Human-readable in ~2 seconds (title + one_sentence concise)
    """
    title = card.get("title", "")
    one_sentence = card.get("one_sentence", "")
    verbatim = card.get("verbatim_excerpt", "")
    action = card.get("action_or_lesson", "")
    combined = f"{title} {one_sentence} {verbatim} {action}"

    dm = card.get("distill_meta", {})
    pa = dm.get("participant_attribution", {})
    roles = pa.get("roles", [])

    if "source_testing" in roles and "user" not in roles:
        if _OWNER_SAMPLE_PREFILTER_REJECT.search(combined):
            return False, "prefilter_source_testing_ops"

    if _OWNER_SAMPLE_PREFILTER_REJECT.search(combined):
        return False, "prefilter_owner_sample_ops"

    if _REJECT_CONSTRUCTION_STATUS.search(combined):
        return False, "prefilter_construction_status"

    if _BLOB_INDICATOR.match(one_sentence):
        return False, "prefilter_blob"

    if "知意" in combined or re.search(r"\b(zhiyi_recall|yifanchen-zhiyi)\b", combined):
        return False, "prefilter_naming_leak"

    if len(title) > 80:
        return False, "prefilter_title_too_long"
    if len(one_sentence) > 250:
        return False, "prefilter_one_sentence_too_long"

    if not _WE_STRONG.search(combined) and not _WE_ACTIONABLE.search(combined):
        return False, "prefilter_no_actionable_content"

    return True, ""


def _owner_sample_card_ok(card: dict) -> Tuple[bool, str]:
    """Final owner-sample gate after model rewriting.

    The model can make operational status sound like a lesson, so the final
    card face must still be checked together with the original verbatim and
    participant attribution.
    """
    dm = card.get("distill_meta", {})
    if dm.get("source_mode") != "evidence_bound_model_distill":
        return False, "not_model_distilled"
    return _owner_sample_prefilter(card)


# --- Helpers ---

def _ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _span_hash(span: str) -> str:
    return hashlib.sha256(span.encode("utf-8")).hexdigest()[:12]


def _record_hash(record: dict) -> str:
    key = json.dumps(
        {k: record.get(k) for k in ("exp_id", "type", "summary", "detail")},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _parse_source_refs(record: dict) -> dict:
    raw = record.get("source_refs", {})
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


def _is_agent_narration(text: str) -> bool:
    t = text.strip()
    for prefix in _AGENT_NARRATION_STARTS:
        if t.startswith(prefix):
            return True
    return False


def _is_agent_plan_status(text: str) -> bool:
    t = text.strip()
    for prefix in _AGENT_PLAN_STATUS_PREFIXES:
        if t.startswith(prefix):
            return True
    return False


# --- Source path relocation ---

def _path_tail(path: str, depth: int = 4) -> str:
    """Extract the last `depth` components of a path for matching."""
    parts = Path(path).parts
    return str(Path(*parts[-depth:])) if len(parts) >= depth else path


def _resolve_source_path(original_path: str) -> Tuple[str, str, List[str]]:
    """Resolve a stale source_path to a real file by searching multiple roots.

    Returns (resolved_path, resolution_method, roots_tried).
    """
    if not original_path:
        return "", "empty_original", []

    if os.path.isfile(original_path):
        return original_path, "exact_match", []

    roots_tried: List[str] = []

    # Try progressively shorter tails (from 8 down to 2)
    parts = Path(original_path).parts
    for depth in range(min(8, len(parts)), 1, -1):
        tail = str(Path(*parts[-depth:]))
        for root in _SEARCH_ROOTS:
            if not os.path.isdir(root):
                if root not in roots_tried:
                    roots_tried.append(f"{root} (not_dir)")
                continue
            if root not in roots_tried:
                roots_tried.append(root)
            candidate = os.path.join(root, tail)
            if os.path.isfile(candidate):
                return candidate, f"tail_match_d{depth}:{tail}", roots_tried

    return "", "unresolved", roots_tried


def _verify_verbatim_in_raw(verbatim: str, record: dict) -> Tuple[bool, str, dict]:
    """Verify verbatim exists in the actual raw source file.

    Returns (passed, raw_info_str, resolution_report).
    """
    source_refs = _parse_source_refs(record)
    original_path = source_refs.get("source_path", "")
    resolution_report = {
        "original_source_path": original_path,
        "resolved_source_path": "",
        "resolution_method": "",
        "byte_offset_used": "",
        "search_used": "",
    }

    resolved_path, method, roots_tried = _resolve_source_path(original_path)
    resolution_report["resolved_source_path"] = resolved_path
    resolution_report["resolution_method"] = method

    if not resolved_path:
        return False, "source_path_unresolved", resolution_report

    byte_offsets = source_refs.get("byte_offsets", {})

    # Normalize verbatim for matching (collapse whitespace)
    verbatim_norm = re.sub(r"\s+", " ", verbatim.strip())
    match_key = verbatim_norm

    # Try byte offset verification first
    if byte_offsets and isinstance(byte_offsets, dict):
        for msg_id, offset_info in byte_offsets.items():
            if not isinstance(offset_info, dict):
                continue
            start = offset_info.get("start")
            end = offset_info.get("end")
            if start is None or end is None:
                continue
            try:
                with open(resolved_path, "rb") as f:
                    f.seek(int(start))
                    chunk = f.read(int(end) - int(start))
                    raw_text = chunk.decode("utf-8", errors="ignore")
                if match_key in re.sub(r"\s+", " ", raw_text):
                    resolution_report["byte_offset_used"] = f"{start}-{end}"
                    return True, f"byte_offset:{start}-{end}", resolution_report
            except Exception:
                continue

    # Fallback: bounded search in the raw file (strict small window)
    try:
        file_size = os.path.getsize(resolved_path)
        max_read = min(file_size, 2 * 1024 * 1024)
        with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(max_read)
        content_norm = re.sub(r"\s+", " ", content)
        if match_key in content_norm:
            resolution_report["search_used"] = "bounded_search_ok"
            return True, "bounded_search_ok", resolution_report
    except Exception:
        pass

    # JSONL-aware search: check each text field individually (not concatenated)
    # Strict bounds: 500 lines / 2MB max per card to avoid full rescan
    try:
        max_lines = 500
        max_bytes = 2 * 1024 * 1024  # 2MB
        bytes_read = 0
        with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f):
                if line_no > max_lines:
                    break
                bytes_read += len(line.encode("utf-8", errors="ignore"))
                if bytes_read > max_bytes:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    for field_text in _extract_individual_text_fields(obj):
                        field_norm = re.sub(r"\s+", " ", field_text)
                        if match_key in field_norm:
                            resolution_report["search_used"] = f"jsonl_field_line_{line_no}"
                            return True, f"jsonl_field_line_{line_no}", resolution_report
                except (json.JSONDecodeError, Exception):
                    line_norm = re.sub(r"\s+", " ", line)
                    if match_key in line_norm:
                        resolution_report["search_used"] = f"jsonl_plain_line_{line_no}"
                        return True, f"jsonl_plain_line_{line_no}", resolution_report
    except Exception:
        pass

    return False, "verbatim_not_in_raw", resolution_report


def _compute_verbatim_byte_offsets(verbatim: str, resolved_path: str) -> Optional[dict]:
    """Compute the actual byte range of verbatim in the resolved raw file.

    Returns {"start": int, "end": int} or None if not found.
    Uses streaming chunked search to handle large files (hundreds of MB).
    """
    if not verbatim or not resolved_path or not os.path.isfile(resolved_path):
        return None

    verbatim_bytes = verbatim.encode("utf-8")
    file_size = os.path.getsize(resolved_path)

    # Pass 1: streaming chunked direct byte search
    CHUNK_SIZE = 4 * 1024 * 1024
    OVERLAP = len(verbatim_bytes) + 256
    try:
        with open(resolved_path, "rb") as f:
            chunk_start = 0
            prev_tail = b""
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                search_buf = prev_tail + chunk
                idx = search_buf.find(verbatim_bytes)
                if idx >= 0:
                    start = chunk_start - len(prev_tail) + idx
                    return {"start": start, "end": start + len(verbatim_bytes)}
                chunk_start += len(chunk)
                if len(search_buf) > OVERLAP:
                    prev_tail = search_buf[-OVERLAP:]
                else:
                    prev_tail = search_buf
    except Exception:
        pass

    # Pass 2: JSONL-aware — search within individual text fields (line by line)
    verbatim_norm = re.sub(r"\s+", " ", verbatim.strip())
    try:
        offset = 0
        with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f):
                line_stripped = line.strip()
                if not line_stripped:
                    offset += len(line.encode("utf-8"))
                    continue
                try:
                    obj = json.loads(line_stripped)
                    for field_text in _extract_individual_text_fields(obj):
                        field_norm = re.sub(r"\s+", " ", field_text.strip())
                        sub_idx = field_norm.find(verbatim_norm)
                        if sub_idx >= 0:
                            raw_line = line.encode("utf-8")
                            field_in_raw = field_text.strip().encode("utf-8")
                            fidx = raw_line.find(field_in_raw)
                            if fidx >= 0:
                                prefix = field_norm[:sub_idx]
                                pre_bytes = prefix.encode("utf-8")
                                return {
                                    "start": offset + fidx + len(pre_bytes),
                                    "end": offset + fidx + len(pre_bytes) + len(verbatim_bytes),
                                }
                except (json.JSONDecodeError, Exception):
                    pass
                offset += len(line.encode("utf-8"))
    except Exception:
        pass

    return None


def _read_verbatim_slice(resolved_path: str, offsets: dict) -> tuple[str, str] | tuple[None, None]:
    """Return the exact UTF-8 source slice text plus raw-byte sha256."""
    try:
        start = int(offsets.get("start"))
        end = int(offsets.get("end"))
    except Exception:
        return None, None
    if start < 0 or end <= start:
        return None, None
    try:
        with open(resolved_path, "rb") as f:
            f.seek(start)
            raw = f.read(end - start)
    except OSError:
        return None, None
    return raw.decode("utf-8", errors="ignore"), hashlib.sha256(raw).hexdigest()


def _find_raw_excerpt_for_record(record: dict, hint_text: str) -> Tuple[Optional[str], str]:
    """Find a real verbatim excerpt from raw JSONL source for a record.

    Priority:
    1. source_refs byte_offsets → read exact bytes from raw file
    2. session_id/turn_id/line hints in source_refs
    3. Small-window field-level exact search in raw JSONL

    Returns (excerpt, method) or (None, failure_reason).
    The excerpt is always a continuous substring of a real raw text field.
    """
    if not hint_text or len(hint_text.strip()) < 10:
        return None, "hint_too_short"

    source_refs = _parse_source_refs(record)
    original_path = source_refs.get("source_path", "")
    resolved_path, method, _ = _resolve_source_path(original_path)
    if not resolved_path:
        return None, "source_path_unresolved"

    hint_norm = re.sub(r"\s+", " ", hint_text.strip())

    # Priority 1: byte_offsets (only if they actually contain the hint)
    byte_offsets = source_refs.get("byte_offsets", {})
    if byte_offsets and isinstance(byte_offsets, dict):
        for msg_id, offset_info in byte_offsets.items():
            if not isinstance(offset_info, dict):
                continue
            start = offset_info.get("start")
            end = offset_info.get("end")
            if start is None or end is None:
                continue
            try:
                with open(resolved_path, "rb") as f:
                    f.seek(int(start))
                    chunk = f.read(int(end) - int(start))
                    raw_text = chunk.decode("utf-8", errors="ignore")
                text_from_json = _extract_text_from_json_chunk(raw_text)
                search_text = text_from_json if text_from_json != raw_text else raw_text
                search_norm = re.sub(r"\s+", " ", search_text.strip())
                if hint_norm[:40] in search_norm:
                    excerpt = _select_raw_backed_excerpt(search_text, raw_text, hint_norm)
                    if not excerpt:
                        idx = search_norm.index(hint_norm[:40])
                        excerpt = search_text.strip()[idx:idx + 500]
                    if len(excerpt) >= 10:
                        return excerpt, "byte_offset"
                # byte_offsets exist but don't contain hint — skip, don't use stale data
            except Exception:
                continue
            start = offset_info.get("start")
            end = offset_info.get("end")
            if start is None or end is None:
                continue
            try:
                with open(resolved_path, "rb") as f:
                    f.seek(int(start))
                    chunk = f.read(int(end) - int(start))
                    raw_text = chunk.decode("utf-8", errors="ignore")
                text_from_json = _extract_text_from_json_chunk(raw_text)
                search_text = text_from_json if text_from_json != raw_text else raw_text
                search_norm = re.sub(r"\s+", " ", search_text.strip())
                if hint_norm[:40] in search_norm:
                    excerpt = _select_raw_backed_excerpt(search_text, raw_text, hint_norm)
                    if not excerpt:
                        idx = search_norm.index(hint_norm[:40])
                        excerpt = search_text.strip()[idx:idx + 500]
                    if len(excerpt) >= 10:
                        return excerpt, "byte_offset"
            except Exception:
                continue

    # Priority 2: session_id/line hints — scan targeted JSONL lines
    session_id = source_refs.get("session_id", "")
    msg_ids = source_refs.get("msg_ids", [])
    if resolved_path.endswith(".jsonl") and (session_id or msg_ids):
        try:
            with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f):
                    if line_no > 500:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        obj_session = obj.get("session_id", "")
                        obj_msg_id = obj.get("msg_id", "") or obj.get("id", "")
                        if (session_id and obj_session == session_id) or (obj_msg_id in msg_ids):
                            # Found matching line, extract text fields
                            for field_text in _extract_individual_text_fields(obj):
                                field_norm = re.sub(r"\s+", " ", field_text.strip())
                                if hint_norm[:40] in field_norm:
                                    idx = field_norm.index(hint_norm[:40])
                                    excerpt = field_text.strip()[idx:idx + 500]
                                    if len(excerpt) >= 10:
                                        return excerpt, f"session_line_{line_no}"
                    except (json.JSONDecodeError, Exception):
                        continue
        except Exception:
            pass

    # Priority 3: small-window field-level exact search
    try:
        bytes_read = 0
        with open(resolved_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f):
                if line_no > 500:
                    break
                bytes_read += len(line.encode("utf-8", errors="ignore"))
                if bytes_read > 2 * 1024 * 1024:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    for field_text in _extract_individual_text_fields(obj):
                        field_norm = re.sub(r"\s+", " ", field_text.strip())
                        if hint_norm[:40] in field_norm:
                            idx = field_norm.index(hint_norm[:40])
                            excerpt = field_text.strip()[idx:idx + 500]
                            if len(excerpt) >= 10:
                                return excerpt, f"bounded_exact_line_{line_no}"
                except (json.JSONDecodeError, Exception):
                    text_from_json = _extract_text_from_json_chunk(line)
                    search_text = text_from_json if text_from_json != line else line
                    line_norm = re.sub(r"\s+", " ", search_text.strip())
                    if hint_norm[:40] in line_norm:
                        excerpt = _select_raw_backed_excerpt(search_text, line, hint_norm)
                        if not excerpt:
                            idx = line_norm.index(hint_norm[:40])
                            excerpt = search_text.strip()[idx:idx + 500]
                        if len(excerpt) >= 10:
                            return excerpt, f"bounded_exact_line_{line_no}"
    except Exception:
        pass

    return None, "verbatim_not_in_raw"


def _extract_text_from_json(obj, max_depth: int = 5) -> str:
    """Recursively extract all string values from a JSON object."""
    if max_depth <= 0:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return " ".join(_extract_text_from_json(v, max_depth - 1) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(_extract_text_from_json(v, max_depth - 1) for v in obj)
    return str(obj)


def _preferred_message_text(obj) -> str:
    if not isinstance(obj, dict):
        return ""
    message = obj.get("message") if isinstance(obj.get("message"), dict) else obj
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(part for part in parts if part)
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    if payload:
        text = _preferred_message_text(payload)
        if text:
            return text
    return ""


def _extract_individual_text_fields(obj, max_depth: int = 5) -> List[str]:
    """Extract individual text field values (not concatenated) from a JSON object."""
    if max_depth <= 0:
        return []
    if isinstance(obj, str) and len(obj) > 5:
        return [obj]
    if isinstance(obj, dict):
        results = []
        for v in obj.values():
            results.extend(_extract_individual_text_fields(v, max_depth - 1))
        return results
    if isinstance(obj, list):
        results = []
        for item in obj:
            results.extend(_extract_individual_text_fields(item, max_depth - 1))
        return results
    return []


_TEXT_FIELD_PRIORITY = ["payload.message", "message", "content", "text"]


def _extract_text_from_json_chunk(chunk: str) -> str:
    """Parse a JSON chunk and return concatenated human-readable text fields.

    Tries priority fields (payload.message, message, content, text) first,
    then falls back to all extracted text fields. Returns raw chunk if not JSON.
    """
    try:
        obj = json.loads(chunk)
    except (json.JSONDecodeError, ValueError):
        return chunk
    if isinstance(obj, dict):
        preferred = _preferred_message_text(obj)
        if preferred:
            return preferred
        for field in _TEXT_FIELD_PRIORITY:
            parts = field.split(".")
            val = obj
            for p in parts:
                if isinstance(val, dict):
                    val = val.get(p)
                else:
                    val = None
                    break
            if isinstance(val, str) and len(val) > 3:
                return val
    fields = _extract_individual_text_fields(obj)
    if fields:
        return " ".join(fields)
    return chunk


def _select_raw_backed_excerpt(decoded_text: str, raw_text: str, hint_norm: str = "") -> str:
    """Pick a short decoded text span that also appears byte-contiguously in raw JSONL.

    Claude JSONL stores long message text inside JSON strings. Multi-paragraph
    decoded excerpts contain real newlines, while the raw file contains escaped
    ``\\n`` bytes. Use the decoded field for semantics, but choose a compact
    sentence/line that can still be verified with ordinary byte offsets.
    """
    decoded = str(decoded_text or "")
    raw = str(raw_text or "")
    if not decoded or not raw:
        return ""
    pieces: list[str] = []
    for line in decoded.splitlines():
        line = line.strip()
        if not line:
            continue
        pieces.append(line)
        pieces.extend(part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*", line) if part.strip())
    seen = set()
    candidates = []
    hint_head = re.sub(r"\s+", " ", str(hint_norm or "").strip())[:80]
    for piece in pieces:
        clean = re.sub(r"\s+", " ", piece).strip()
        clean = clean.strip("` ")
        if len(clean) < 12 or len(clean) > 260:
            continue
        if clean in seen:
            continue
        seen.add(clean)
        if clean in raw:
            score = 0
            if hint_head and clean[:20] in hint_head:
                score += 4
            if _WE_STRONG.search(clean):
                score += 3
            if _WE_ACTIONABLE.search(clean):
                score += 2
            candidates.append((score, len(clean), clean))
    if not candidates:
        compact = re.sub(r"\s+", " ", decoded).strip()
        if 12 <= len(compact) <= 260 and compact in raw:
            return compact
        return ""
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


# --- S0: Choose real raw spans worth cards ---

def _is_reject(record: dict) -> Tuple[bool, str]:
    text = " ".join(str(record.get(k, "") or "") for k in ("summary", "detail"))
    if not text.strip():
        return True, "empty"

    if tool_result_pollution_guard:
        guard = tool_result_pollution_guard(text, role="user")
        if guard.get("blocked"):
            return True, f"pollution:{guard.get('category', '')}"

    for label, pat in [
        ("video_subtitle", _REJECT_VIDEO_SUBTITLE),
        ("repost_article", _REJECT_REPOST_ARTICLE),
        ("skill_dump", _REJECT_SKILL_DUMP),
        ("self_test", _REJECT_SELF_TEST),
        ("template_stub", _REJECT_TEMPLATE_STUB),
        ("ai_construction", _REJECT_AI_CONSTRUCTION),
        ("construction_status", _REJECT_CONSTRUCTION_STATUS),
        ("tool_exec", _REJECT_TOOL_EXEC),
    ]:
        if pat.search(text):
            return True, label

    if _REJECT_BASE64.search(text):
        return True, "base64"

    summary_text = str(record.get("summary") or "")
    detail_text = str(record.get("detail") or "")
    assistant_text = ""
    am = re.search(r"assistant\s*原话[：:]\s*(.+)", detail_text, re.DOTALL)
    if am:
        assistant_text = am.group(1).strip()
    check_text = assistant_text or summary_text
    if _is_agent_narration(check_text) and not _WE_STRONG.search(check_text):
        return True, "agent_narration"

    if _is_agent_plan_status(check_text):
        return True, "agent_plan_status"

    participant_attr = _extract_participant_attribution(check_text)
    blocked, reason = _source_origin_guard(check_text, participant_attr=participant_attr)
    if blocked:
        return True, reason

    return False, ""


def s0_select_worthy_spans(records: List[dict]) -> Tuple[List[dict], List[dict]]:
    worthy = []
    rejected = []
    for rec in records:
        is_rej, reason = _is_reject(rec)
        if is_rej:
            rejected.append({"record": rec, "reason": reason})
        else:
            worthy.append(rec)
    return worthy, rejected


# --- S1: Split into exchanges ---

def _extract_exchange_text(record: dict) -> List[str]:
    """Extract exchange-level text blocks from a record.

    An exchange = full assistant/user turn + context. Not split by sentence.
    Returns 1-3 exchange blocks covering the record.
    """
    summary = str(record.get("summary") or "")
    detail = str(record.get("detail") or "")
    exchanges = []

    # Strip "案例：" prefix from summary for installed runtime records
    clean_summary = re.sub(r"^案例[：:]\s*", "", summary).strip()

    # Primary exchange: assistant 原话 block (full, not split)
    assistant_match = re.search(r"assistant\s*原话[：:]\s*(.+)", detail, re.DOTALL)
    if assistant_match:
        raw_text = assistant_match.group(1).strip()
        if len(raw_text) > 10:
            exchanges.append(raw_text)

    # Secondary: summary if it has strong signal (full text, not split)
    if _WE_STRONG.search(clean_summary) and len(clean_summary) > 10:
        exchanges.append(clean_summary)
    elif len(clean_summary) > 20 and not exchanges:
        # Installed runtime records: summary is the primary content
        # Accept if it has actionable or strong signal, or is substantive
        if _WE_ACTIONABLE.search(clean_summary) or _WE_STRONG.search(clean_summary):
            exchanges.append(clean_summary)

    # Tertiary: detail block with context (first 500 chars, not split)
    if not exchanges and detail and _WE_STRONG.search(detail):
        exchanges.append(detail[:500])

    return exchanges


def s1_split_exchanges(record: dict) -> List[dict]:
    """S1: Split a record into exchange-level blocks.

    Each exchange = full assistant/user turn + context (not split by sentence).
    Returns list of {"exchange_text": str, "source_record": dict}.
    """
    exchanges = _extract_exchange_text(record)

    seen = set()
    unique = []
    for text in exchanges:
        key = text[:80]
        if key in seen:
            continue
        seen.add(key)
        if _is_agent_narration(text) and not _WE_STRONG.search(text):
            continue
        if _is_agent_plan_status(text):
            continue
        unique.append(text)

    return [{"exchange_text": t, "source_record": record} for t in unique]


# --- S2: Distill narrative cards from exchange ---

def _extract_title(text: str) -> str:
    clean = re.sub(r"^[\s]*[-•*]\s*", "", text.strip())
    clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean)
    title = clean[:60]
    if len(clean) > 60:
        title = title.rstrip("，。、；：,.:;") + "..."
    return title


def _extract_situation(text: str, record: dict) -> str:
    # Try topic from text with better quality
    topic_match = re.search(r"(评估|审查|分析|部署|试跑|验证|决定|选择)\s*(\S{2,30}?)(?:[，。；,;]|$)", text)
    if topic_match:
        action = topic_match.group(1)
        obj = topic_match.group(2).rstrip("的")
        if len(obj) > 2:
            return f"{action} {obj} 时的经验"
    context = str(record.get("detail") or "")
    ctx_match = re.search(r"上下文[：:]\s*(.+?)(?:assistant|$)", context, re.DOTALL)
    if ctx_match:
        ctx = ctx_match.group(1).strip()[:150]
        if ctx and len(ctx) > 5:
            return ctx
    summary = str(record.get("summary") or "")
    topic_match2 = re.search(r"(评估|审查|分析|关于|针对)\s*(\S{2,30})", summary)
    if topic_match2:
        return f"{topic_match2.group(0)}的经验"
    # Use first meaningful clause
    first_clause = text[:80].split("。")[0].split("，")[0]
    if len(first_clause) > 5:
        return first_clause
    return ""


def _extract_action_lesson(text: str) -> str:
    sentences = re.split(r"(?<=[。！？\.\!\?\n])\s*", text)
    action_sentences = [s for s in sentences if _WE_ACTIONABLE.search(s) or _WE_STRONG.search(s)]
    if action_sentences:
        return " ".join(action_sentences[:3])
    return text[:300]


def _extract_when_to_use(text: str) -> str:
    if re.search(r"(风险|注意|不要|不应该|risk|caution|warning|不建议|不推荐)", text, re.IGNORECASE):
        return "评估项目风险/成熟度时"
    if re.search(r"(部署|上线|生产|deploy|production|公网)", text, re.IGNORECASE):
        return "决定是否部署/上线时"
    if re.search(r"(建议|应该|推荐|should|recommend|先.*再|隔离)", text, re.IGNORECASE):
        return "做技术选型/实施方案决策时"
    if re.search(r"(安全|漏洞|license|授权|签名)", text, re.IGNORECASE):
        return "安全审计/合规检查时"
    return ""


def _extract_resolved_references(text: str) -> dict:
    """Lightweight pronoun/reference resolution."""
    refs = {"resolved": [], "unresolved": []}
    # Simple pattern: pronouns near nouns
    pronoun_patterns = [
        (r"(它|这个|该项目|这个项目|该方案|这个方案)", "project_reference"),
        (r"(他|她)", "person_reference"),
        (r"(这|那)(个|些|种|类)?(做法|方法|策略|方案|工具|库|框架)", "approach_reference"),
    ]
    for pat, label in pronoun_patterns:
        matches = re.findall(pat, text)
        if matches:
            # Try to find the antecedent in context
            noun_match = re.search(r"([\u4e00-\u9fff]{2,10}(项目|方案|工具|库|框架|系统|平台))", text)
            if noun_match:
                refs["resolved"].append({
                    "pronoun": matches[0] if isinstance(matches[0], str) else matches[0][0],
                    "resolved_to": noun_match.group(1),
                    "type": label,
                })
            else:
                refs["unresolved"].append({
                    "pronoun": matches[0] if isinstance(matches[0], str) else matches[0][0],
                    "type": label,
                })
    return refs


def _extract_normalized_time(text: str) -> dict:
    """Normalize relative time expressions to absolute timestamps (UTC+8)."""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    result = {"normalized": [], "unresolved": []}

    time_patterns = [
        (r"刚才", lambda: now.strftime("%Y-%m-%dT%H:%M"), "minutes_ago"),
        (r"今天", lambda: now.strftime("%Y-%m-%d"), "today"),
        (r"昨天", lambda: (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d"), "yesterday"),
        (r"上周", lambda: (now - datetime.timedelta(weeks=1)).strftime("%Y-%m-%d"), "last_week"),
        (r"本月", lambda: now.strftime("%Y-%m"), "this_month"),
        (r"今年", lambda: now.strftime("%Y"), "this_year"),
        (r"去年", lambda: str(now.year - 1), "last_year"),
        (r"(\d{4})年(\d{1,2})月", None, "absolute_date"),
    ]

    for pat, calc, label in time_patterns:
        match = re.search(pat, text)
        if match:
            if calc:
                result["normalized"].append({
                    "expression": match.group(0),
                    "absolute": calc(),
                    "type": label,
                })
            else:
                year = match.group(1)
                month = match.group(2)
                result["normalized"].append({
                    "expression": match.group(0),
                    "absolute": f"{year}-{int(month):02d}",
                    "type": label,
                })

    # Check for relative time expressions that couldn't be resolved
    if re.search(r"(最近|近期|之前|之前几天|前段时间)", text):
        result["unresolved"].append({
            "expression": re.search(r"(最近|近期|之前|之前几天|前段时间)", text).group(0),
            "reason": "unresolved_relative_time",
        })

    if not result["normalized"] and not result["unresolved"]:
        result["status"] = "none"
    elif result["unresolved"] and not result["normalized"]:
        result["status"] = "unresolved_relative_time"

    return result


def _extract_participant_attribution(text: str) -> dict:
    """Identify who said/did/requested."""
    attrs = {"roles": []}
    if re.search(r"(用户|你|主人|老板|PM|产品经理)", text):
        attrs["roles"].append("user")
    if re.search(r"(我|assistant|AI|模型|agent)", text, re.IGNORECASE):
        attrs["roles"].append("assistant")
    if re.search(r"(文档|手册|官方|README|文档说)", text):
        attrs["roles"].append("source_documentation")
    if re.search(r"(测试|pytest|benchmark|监控)", text):
        attrs["roles"].append("source_testing")
    if not attrs["roles"]:
        attrs["roles"].append("unknown")
    return attrs


def _extract_explicit_reasoning(text: str) -> List[str]:
    """Extract explicit reasoning chains (because/so/if/but)."""
    patterns = [
        r"因为[^，。,.\n]{5,50}",
        r"所以[^，。,.\n]{5,50}",
        r"如果[^，。,.\n]{5,50}",
        r"但[^，。,.\n]{5,50}",
        r"先[^，。,.\n]{5,30}再[^，。,.\n]{5,30}",
        r"since[^,.\n]{5,50}",
        r"because[^,.\n]{5,50}",
        r"so[^,.\n]{5,50}",
        r"if[^,.\n]{5,50}",
        r"but[^,.\n]{5,50}",
    ]
    reasoning = []
    for pat in patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        reasoning.extend(matches[:2])
    return reasoning[:5]


def _extract_fact_type(text: str) -> str:
    """Classify the card's fact type."""
    if re.search(r"(风险|注意|不要|不应该|risk|caution)", text, re.IGNORECASE):
        return "risk"
    if re.search(r"(决定|选择|采用|放弃|决策|decision)", text, re.IGNORECASE):
        return "decision"
    if re.search(r"(纠偏|纠正|修正|原来.*错|之前.*不对)", text, re.IGNORECASE):
        return "correction"
    if re.search(r"(经验|教训|做法|策略|方法|步骤)", text, re.IGNORECASE):
        return "xingce_work_experience"
    if _WE_STRONG.search(text) or _WE_ACTIONABLE.search(text):
        return "xingce_work_experience"
    return "observation"


def _extract_entities(text: str) -> List[dict]:
    """Lightweight entity extraction."""
    entities = []
    # Project names
    for m in re.finditer(r"([\u4e00-\u9fffA-Z][\w\-]{2,20}(项目|系统|平台|工具|库|框架))", text):
        entities.append({"text": m.group(1), "type": "project"})
    # Software/tools
    for m in re.finditer(r"\b(python|node|npm|docker|k8s|kubernetes|redis|postgres|sqlite|nginx|webpack|vite|bun|deno|pytest|mypy|ruff|uv|pip)\b", text, re.IGNORECASE):
        entities.append({"text": m.group(1), "type": "software"})
    # Files/functions
    for m in re.finditer(r"([\w/]+\.(?:py|ts|js|json|yaml|yml|toml|md|sql))", text):
        entities.append({"text": m.group(1), "type": "file"})
    # Machines/hosts
    for m in re.finditer(r"(windows\d+|mac|linux|服务器|NAS|VPS)", text, re.IGNORECASE):
        entities.append({"text": m.group(1), "type": "machine"})
    return entities


def _extract_narrative_cards(exchange_text: str, record: dict) -> List[dict]:
    """Extract 2-5 narrative cards from an exchange block.

    Each card covers a different aspect of the exchange.
    verbatim_excerpt must come from real raw source, not from summary/detail.
    """
    cards = []
    sentences = re.split(r"(?<=[。！？\.\!\?\n])\s*", exchange_text)

    # Group sentences into thematic clusters
    clusters = []
    current_cluster = []
    for sent in sentences:
        if not sent.strip() or len(sent.strip()) < 10:
            continue
        current_cluster.append(sent)
        # Break cluster at topic shift or when it gets too long
        if len(current_cluster) >= 3 or (len(current_cluster) >= 2 and
            (_WE_STRONG.search(sent) or _WE_ACTIONABLE.search(sent))):
            clusters.append(" ".join(current_cluster))
            current_cluster = []
    if current_cluster:
        clusters.append(" ".join(current_cluster))

    # If no clusters, use the whole exchange as one cluster
    if not clusters and len(exchange_text) > 10:
        clusters = [exchange_text[:500]]

    for cluster_text in clusters[:5]:
        has_strong = bool(_WE_STRONG.search(cluster_text))
        has_actionable = bool(_WE_ACTIONABLE.search(cluster_text))
        if not has_strong and not has_actionable:
            continue
        if _is_agent_narration(cluster_text) and not has_strong:
            continue
        if _is_agent_plan_status(cluster_text):
            continue

        title = _extract_title(cluster_text)
        situation = _extract_situation(cluster_text, record)
        action_lesson = _extract_action_lesson(cluster_text)
        when_to_use = _extract_when_to_use(cluster_text)

        if not action_lesson:
            if not has_strong:
                continue
        if not when_to_use:
            continue
        if not situation:
            continue

        # verbatim_excerpt must be from real raw source
        raw_excerpt, raw_method = _find_raw_excerpt_for_record(record, cluster_text)
        if not raw_excerpt:
            continue

        # Six sub-step fields
        resolved_refs = _extract_resolved_references(cluster_text)
        normalized_time = _extract_normalized_time(cluster_text)
        participant_attr = _extract_participant_attribution(cluster_text)
        explicit_reasoning = _extract_explicit_reasoning(cluster_text)
        fact_type = _extract_fact_type(cluster_text)
        entities = _extract_entities(cluster_text)

        cards.append({
            "title": title,
            "one_sentence": cluster_text[:200],
            "verbatim_excerpt": raw_excerpt,
            "raw_excerpt_method": raw_method,
            "situation": situation,
            "action_or_lesson": action_lesson,
            "when_to_use": when_to_use,
            "source_record": record,
            "distill_meta": {
                "resolved_references": resolved_refs,
                "normalized_time": normalized_time,
                "participant_attribution": participant_attr,
                "explicit_reasoning": explicit_reasoning,
                "fact_type": fact_type,
                "entities": entities,
            },
        })

    return cards


def s2_distill_from_exchange(exchange_item: dict) -> List[dict]:
    """S2: Distill an exchange into 2-5 narrative cards."""
    exchange_text = exchange_item["exchange_text"]
    record = exchange_item["source_record"]
    return _extract_narrative_cards(exchange_text, record)


# --- S3: Validation ---

def s3_validate(card: dict) -> Tuple[bool, str, dict]:
    meta: Dict[str, Any] = {}
    verbatim = card.get("verbatim_excerpt", "")
    if not verbatim or len(verbatim) < 10:
        return False, "verbatim_too_short", meta

    title = card.get("title", "")
    if not title or len(title) < 3:
        return False, "title_too_short", meta

    situation = card.get("situation", "")
    if not situation or len(situation) < 5:
        return False, "missing_or_weak_situation", meta

    action = card.get("action_or_lesson", "")
    if not action:
        return False, "missing_action", meta

    when_to_use = card.get("when_to_use", "")
    if not when_to_use:
        return False, "missing_when_to_use", meta

    if _REJECT_AI_CONSTRUCTION.search(title + " " + card.get("one_sentence", "")):
        return False, "construction_narrative", meta

    _card_text_for_status = " ".join(
        card.get(f, "") for f in ("title", "one_sentence", "verbatim_excerpt", "action_or_lesson")
    )
    if _REJECT_CONSTRUCTION_STATUS.search(_card_text_for_status):
        return False, "construction_status_card", meta

    _card_participant_attr = card.get("distill_meta", {}).get("participant_attribution")
    for check_field in ("title", "one_sentence", "verbatim_excerpt", "action_or_lesson"):
        field_val = card.get(check_field, "")
        if field_val:
            blocked, reason = _source_origin_guard(field_val, participant_attr=_card_participant_attr)
            if blocked:
                return False, f"source_origin_guard_{check_field}", meta

    if _is_agent_narration(verbatim):
        if _is_agent_narration(title) or _is_agent_narration(card.get("one_sentence", "")):
            return False, "agent_narration", meta

    verbatim_first_clause = verbatim.strip().split("。")[0].split("，")[0]
    if _is_agent_plan_status(verbatim_first_clause):
        return False, "agent_plan_status", meta

    if verbatim.lstrip().startswith("{") and re.search(r'"(timestamp|payload)"', verbatim[:200]):
        return False, "json_wrapper_excerpt", meta

    # S3 owner_sample_quality: reject first-person plan/status in card-facing fields
    _PLAN_NARRATION_FIELD = re.compile(
        r"^(我先|我会|我还需要|现在我|接下来|之后给结论|我把这轮写进|我来跑|我去跑|我去|我再)"
    )
    for field_name in ("title", "one_sentence", "action_or_lesson"):
        field_val = card.get(field_name, "")
        if not field_val:
            continue
        first_clause = field_val.strip().split("。")[0].split("，")[0]
        if _PLAN_NARRATION_FIELD.match(first_clause):
            return False, "owner_sample_quality_plan", meta
    for field_name in ("title", "one_sentence", "action_or_lesson", "verbatim_excerpt"):
        field_val = card.get(field_name, "")
        if not field_val:
            continue
        if re.search(r"(之后给结论|我把这轮写进|我来跑|我去跑|我先不动生产数据)", field_val):
            return False, "owner_sample_quality_construction", meta

    # Public naming: zhiyi/知意/yifanchen-zhiyi must not appear in card-facing fields
    _NORM_TO_TIME_LIBRARY = {"zhiyi_recall": "time_library_recall", "知意": "Time Library", "yifanchen-zhiyi": "time_library_recall"}
    combined_public = title + " " + card.get("one_sentence", "") + " " + card.get("action_or_lesson", "") + " " + card.get("when_to_use", "")
    if "知意" in combined_public:
        return False, "naming_leak_zhiyi", meta
    if re.search(r"\b(zhiyi_recall|yifanchen-zhiyi)\b", combined_public):
        return False, "naming_leak_zhiyi_recall", meta

    # Gate5 quality: reject path fragments, timestamps, low-quality situation
    if re.search(r'(ts:\d+|session\.\s*ts|\.jsonl|\.py:\d+|\.ts:\d+)', title):
        return False, "path_fragment_title", meta
    if re.search(r'[""\u201c].*[""\u201d]\s*(项目|方案|工具)', situation):
        return False, "quoted_path_situation", meta
    if situation and len(situation) < 8 and "的经验" in situation:
        return False, "weak_situation_suffix", meta
    if re.search(r'^[\w\-\.:/\s]+$', title.strip()) and len(title.strip()) < 20:
        return False, "path_only_title", meta

    _BULLET_PREFIX = re.compile(r'^[\s]*[-•*]\s+\*\*')
    for check_field in ("title", "one_sentence", "action_or_lesson"):
        field_val = card.get(check_field, "")
        if field_val and _BULLET_PREFIX.match(field_val):
            return False, "multi_bullet_blob", meta

    # Raw verification with relocation — strict only, no fuzzy
    record = card.get("source_record", {})
    raw_ok, raw_info, resolution_report = _verify_verbatim_in_raw(verbatim, record)
    meta["raw_verification"] = "passed" if raw_ok else "failed"
    meta["raw_info"] = raw_info
    meta["resolution_report"] = resolution_report
    meta["raw_excerpt_method"] = card.get("raw_excerpt_method", "")
    if not raw_ok:
        return False, f"raw_verification_failed:{raw_info}", meta

    return True, "", meta


# --- S4: Dedupe/conflict ---

def s4_dedupe(cards: List[dict]) -> List[dict]:
    seen = {}
    unique = []
    for card in cards:
        verbatim = card.get("verbatim_excerpt", "")
        key = verbatim[:80]
        if key in seen:
            continue
        record = card.get("source_record", {})
        exp_id = record.get("exp_id", "")
        is_dup = False
        for existing in unique:
            if existing.get("source_record", {}).get("exp_id") != exp_id:
                continue
            existing_verbatim = existing.get("verbatim_excerpt", "")
            overlap = len(set(verbatim[:100]) & set(existing_verbatim[:100]))
            if overlap > 60:
                is_dup = True
                break
        if not is_dup:
            seen[key] = True
            unique.append(card)
    return unique


# --- S5: Write to candidate layer ---

def _candidate_id(exp_id: str, span: str) -> str:
    safe_exp = "".join(ch for ch in str(exp_id) if ch.isalnum() or ch in ("-", "_"))[:24]
    return f"xingce-distill-{safe_exp}-{_span_hash(span)}"


def s5_build_candidate(card: dict) -> dict:
    record = card.get("source_record", {})
    source_refs = _parse_source_refs(record)
    exp_id = record.get("exp_id", "")
    resolution_report = card.get("_resolution_report", {})
    computed_offsets = resolution_report.get("computed_byte_offsets")
    if not computed_offsets:
        return None
    resolved_source_path = resolution_report.get("resolved_source_path", "")
    verbatim, verbatim_sha256 = _read_verbatim_slice(resolved_source_path, computed_offsets)
    if not verbatim:
        return None
    cand_id = _candidate_id(exp_id, verbatim)
    now = _ts()

    evidence_ref = {
        "source_path": source_refs.get("source_path", ""),
        "resolved_source_path": resolved_source_path,
        "resolution_method": resolution_report.get("resolution_method", ""),
        "resolution_report": {
            "original_source_path": resolution_report.get("original_source_path", source_refs.get("source_path", "")),
            "resolved_source_path": resolved_source_path,
            "resolution_method": resolution_report.get("resolution_method", ""),
            "computed_byte_offsets": computed_offsets,
        },
        "source_system": source_refs.get("source_system", record.get("source_system", "")),
        "source_author": record.get("source_author", record.get("source_role", "")),
        "source_role": record.get("source_role", record.get("source_author", "")),
        "computer_name": source_refs.get("computer_name", record.get("computer_id", "local")),
        "canonical_window_id": source_refs.get("canonical_window_id", record.get("canonical_window_id", "")),
        "session_id": source_refs.get("session_id", record.get("session_id", "")),
        "msg_ids": source_refs.get("msg_ids", []),
        "byte_offsets": dict(computed_offsets),
        "artifact_type": source_refs.get("artifact_type", ""),
        "captured_at": source_refs.get("captured_at", now),
    }

    distill_meta = card.get("distill_meta", {})
    source_mode = distill_meta.get("source_mode", "heuristic_draft")
    model_distill_ok = source_mode == "evidence_bound_model_distill"
    pipeline_name = "S0_S5_model_distill" if model_distill_ok else "S0_S5_heuristic"
    lifecycle = "candidate" if model_distill_ok else "candidate_not_signed"

    return {
        "candidate_id": cand_id,
        "candidate_type": "xingce_work_experience",
        "library_shelf": "xingce",
        "lifecycle_status": lifecycle,
        "created_at": now,
        "title": card["title"],
        "summary": card["one_sentence"],
        "verbatim_excerpt": verbatim,
        "verbatim_sha256": verbatim_sha256,
        "source_mode": source_mode,
        "source_author": record.get("source_author", record.get("source_role", "")),
        "source_role": record.get("source_role", record.get("source_author", "")),
        "confidence": card.get("_model_distill_confidence", 0.7) if model_distill_ok else 0.7,
        "evidence_refs": [evidence_ref],
        "source_refs": [
            resolution_report.get("resolved_source_path") or source_refs.get("source_path", "")
        ] if resolution_report.get("resolved_source_path") or source_refs.get("source_path") else [],
        "observed_facts": [card["situation"]],
        "recommended_procedure": [card["action_or_lesson"]],
        "verification_steps": [],
        "avoid_conditions": [],
        "work_scenario": card["situation"],
        "action_strategy": card["action_or_lesson"],
        "applicable_scope": evidence_ref.get("canonical_window_id", ""),
        "frontstage_surface": "work_experience",
        "supersedes": [],
        "conflicts_with": [],
        "write_boundary": {
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "distill_meta": {
            "pipeline": pipeline_name,
            "when_to_use": card.get("when_to_use", ""),
            "one_sentence": card["one_sentence"],
            "situation": card["situation"],
            "action_or_lesson": card["action_or_lesson"],
            "source_exp_id": exp_id,
            "source_type": record.get("type", ""),
            "distilled_at": now,
            "resolved_references": distill_meta.get("resolved_references", {}),
            "normalized_time": distill_meta.get("normalized_time", {}),
            "participant_attribution": distill_meta.get("participant_attribution", {}),
            "explicit_reasoning": distill_meta.get("explicit_reasoning", []),
            "fact_type": distill_meta.get("fact_type", ""),
            "entities": distill_meta.get("entities", []),
        },
    }


def write_candidate(candidate: dict, candidates_dir: str) -> str:
    os.makedirs(candidates_dir, exist_ok=True)
    cand_id = candidate["candidate_id"]
    safe_id = "".join(ch for ch in cand_id if ch.isalnum() or ch in ("-", "_"))
    path = os.path.join(candidates_dir, f"{safe_id}-candidate.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(candidate, f, ensure_ascii=False, indent=2)
    return path


def write_auto_action(candidate: dict, actions_dir: str) -> str:
    import uuid
    os.makedirs(actions_dir, exist_ok=True)
    cand_id = candidate["candidate_id"]
    safe_id = "".join(ch for ch in cand_id if ch.isalnum() or ch in ("-", "_"))
    now = _ts()
    action_id = "xingce-action-" + uuid.uuid4().hex[:16]
    receipt = {
        "schema_version": "1.0",
        "action_id": action_id,
        "created_at": now,
        "candidate_id": safe_id,
        "candidate_type": candidate.get("candidate_type", ""),
        "action": "auto_adopt",
        "action_status": AUTO_ACTION_STATUS,
        "operator": "xingce_distill_auto",
        "reason": "auto-adopted by S0-S5 distillation pipeline, evidence-bound",
        "source_candidate_path": "",
        "source_mode": candidate.get("source_mode", ""),
        "write_boundary": {
            "action_receipt_write_performed": True,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
        "notes": [
            "auto_distill_action_receipt",
            "evidence_bound_auto_adopted",
            "no_human_review_gate",
            "candidate_artifact_not_modified",
        ],
    }
    ts_name = now.replace(":", "").replace("-", "")
    action_path = os.path.join(actions_dir, f"{ts_name}-{safe_id}-auto_adopt.jsonl")
    with open(action_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) + "\n")
    return action_path


# --- Model distill integration ---

def _build_xingce_distill_prompt(card: dict, evidence_items: list) -> list:
    """Build a dedicated S2/S4.5 prompt for owner-readable work-experience distillation."""
    candidate_stub = {
        "title": card.get("title", ""),
        "one_sentence": card.get("one_sentence", ""),
        "verbatim_excerpt": card.get("verbatim_excerpt", ""),
        "situation": card.get("situation", ""),
        "action_or_lesson": card.get("action_or_lesson", ""),
        "when_to_use": card.get("when_to_use", ""),
    }
    payload = {
        "task_kind": "xingce_card_distill",
        "candidate": candidate_stub,
        "rules": [
            "Use only the supplied evidence (verbatim_excerpt).",
            "Return JSON only. Do not include markdown or prose outside JSON.",
            "Produce owner-readable work-experience card fields.",
            "title: a concise third-person or imperative Chinese phrase (6-30 chars), NOT first-person narration (no 我先/我会/现在进入验证/这轮我/我先). NOT a bullet blob. A human must understand it in 2 seconds.",
            "one_sentence: one owner-readable sentence (20-120 chars) summarizing the lesson. NOT first-person agent narration. NOT a bullet list.",
            "action_or_lesson: the concrete action or lesson (20-200 chars), owner-readable, imperative or third-person. NOT agent construction status.",
            "when_to_use: when to apply this lesson (5-60 chars), e.g. '评估新兴项目时' or '部署上线前'.",
            "situation: the context/situation where this lesson applies (5-100 chars).",
            "verdict must be 'refined' if you produced valid card fields, or 'insufficient_evidence' if the verbatim lacks actionable content.",
            "confidence: 0.0-1.0.",
            "Every field must be supported by the verbatim evidence. Do not invent facts.",
        ],
        "evidence": evidence_items,
        "response_schema": {
            "schema": "xingce_card_distill.v1",
            "verdict": "refined|insufficient_evidence",
            "title": "string",
            "one_sentence": "string",
            "action_or_lesson": "string",
            "when_to_use": "string",
            "situation": "string",
            "confidence": "number between 0 and 1",
            "supporting_refs": ["source_id or evidence_ref"],
        },
    }
    return [
        {"role": "system", "content": "You distill work-experience cards from evidence. Return compact JSON only."},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _apply_model_distill_to_card(
    card: dict,
    *,
    client=None,
    execute: bool = True,
    model_config=None,
) -> dict:
    """Attempt model distill on a validated card. Mutates card in-place.

    When execute=True (default), uses client if provided, otherwise falls back
    to _http_chat_completion with default_model_config. If config/API key is
    missing, reports model_config_missing instead of silently skipping.
    """
    dm = card.setdefault("distill_meta", {})

    if run_evidence_bound_experience_refinement is None and not execute:
        dm["source_mode"] = "heuristic_draft"
        dm["model_distill_status"] = "import_failed"
        return card

    record = card.get("source_record", {})
    evidence_items = [{
        "text": card.get("verbatim_excerpt", ""),
        "source_id": "verbatim",
        "session_id": _parse_source_refs(record).get("session_id", ""),
    }]

    if not execute:
        dm["source_mode"] = "heuristic_draft"
        dm["model_distill_status"] = "not_executed"
        return card

    config = None
    if model_config is not None:
        if EvidenceBoundModelConfig is not None and isinstance(model_config, EvidenceBoundModelConfig):
            config = model_config
        elif isinstance(model_config, dict):
            config = model_config
    elif default_model_config is not None:
        try:
            config = default_model_config()
        except Exception:
            config = None

    def _has_valid_api(cfg) -> bool:
        if cfg is None:
            return False
        if isinstance(cfg, EvidenceBoundModelConfig):
            return cfg.api_key_present
        if isinstance(cfg, dict):
            return bool(cfg.get("api_key_env") and os.environ.get(cfg["api_key_env"]))
        return False

    if not _has_valid_api(config):
        fallback_keys = ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "DEEPSEEK_API_KEY",
                         "OPENAI_API_KEY", "MEMCORE_ZHIYI_API_KEY")
        found_key = next((k for k in fallback_keys if os.environ.get(k)), "")
        if found_key:
            if "MINIMAX" in found_key:
                config = {
                    "provider": "minimax",
                    "model": os.environ.get("MINIMAX_MODEL") or os.environ.get("MINIMAX_CN_MODEL") or "MiniMax-M2.7-highspeed",
                    "base_url": os.environ.get("MINIMAX_BASE_URL") or os.environ.get("MINIMAX_CN_BASE_URL") or "https://api.minimaxi.com/v1",
                    "api_key_env": found_key,
                    "timeout_seconds": 60,
                    "max_tokens": 0,
                }
            elif "DEEPSEEK" in found_key:
                config = {
                    "provider": "deepseek",
                    "model": os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash",
                    "base_url": os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1",
                    "api_key_env": found_key,
                    "timeout_seconds": 60,
                    "max_tokens": 0,
                }
            elif default_model_config is not None:
                try:
                    config = default_model_config(api_key_env=found_key)
                except Exception:
                    config = None

    use_client = client
    if use_client is None and config is not None:
        if not _has_valid_api(config):
            dm["source_mode"] = "heuristic_draft"
            dm["model_distill_status"] = "model_config_missing"
            dm["model_distill_error"] = "no_api_key"
            return card

        config_dict = config if isinstance(config, dict) else {
            "provider": config.provider, "model": config.model,
            "base_url": config.base_url, "api_key_env": config.api_key_env,
            "timeout_seconds": config.timeout_seconds, "max_tokens": config.max_tokens,
        }
        use_client = lambda msgs, cfg: _http_chat_completion_with_config(msgs, config_dict)

    try:
        messages = _build_xingce_distill_prompt(card, evidence_items)
        if use_client is not None:
            raw_result = use_client(messages, config)
        else:
            raw_result = {"ok": False, "error": "model_config_missing"}

        if isinstance(raw_result, dict) and raw_result.get("ok") is False:
            err = raw_result.get("error", "model_error")
            dm["source_mode"] = "heuristic_draft"
            dm["model_distill_status"] = "model_error" if err != "model_config_missing" else "model_config_missing"
            dm["model_distill_error"] = str(err)[:200]
            return card

        content = raw_result.get("content", "") if isinstance(raw_result, dict) else str(raw_result)
        parsed = _extract_json_from_response(content)
    except Exception as exc:
        dm["source_mode"] = "heuristic_draft"
        dm["model_distill_status"] = "error"
        dm["model_distill_error"] = str(exc)[:200]
        return card

    verdict = str(parsed.get("verdict") or "").strip() if parsed else ""
    confidence = _safe_float(parsed.get("confidence"), 0.0) if parsed else 0.0

    dm["model_distill_verdict"] = verdict
    dm["model_distill_confidence"] = confidence
    dm["model_distill_result_keys"] = list(parsed.keys()) if isinstance(parsed, dict) else []

    if verdict == "refined" and confidence > 0 and parsed:
        new_title = str(parsed.get("title") or "").strip()
        new_one_sentence = str(parsed.get("one_sentence") or "").strip()
        new_action = str(parsed.get("action_or_lesson") or "").strip()
        new_when = str(parsed.get("when_to_use") or "").strip()
        new_situation = str(parsed.get("situation") or "").strip()

        if new_title and len(new_title) >= 3:
            card["title"] = new_title
        if new_one_sentence and len(new_one_sentence) >= 10:
            card["one_sentence"] = new_one_sentence
        if new_action and len(new_action) >= 10:
            card["action_or_lesson"] = new_action
        if new_when and len(new_when) >= 3:
            card["when_to_use"] = new_when
        if new_situation and len(new_situation) >= 3:
            card["situation"] = new_situation

        dm["source_mode"] = "evidence_bound_model_distill"
        dm["model_distill_status"] = "refined"
        card["_model_distill_confidence"] = confidence
    elif verdict == "refined":
        dm["source_mode"] = "model_distill_contract"
        dm["model_distill_status"] = "refined_low_confidence"
    else:
        dm["source_mode"] = "model_distill_contract"
        dm["model_distill_status"] = "insufficient_evidence"

    return card


def _http_chat_completion_with_config(messages: list, config_dict: dict) -> dict:
    """Thin wrapper around _http_chat_completion using a plain dict config."""
    if EvidenceBoundModelConfig is not None:
        cfg = EvidenceBoundModelConfig(
            provider=str(config_dict.get("provider", "")),
            model=str(config_dict.get("model", "")),
            base_url=str(config_dict.get("base_url", "")),
            api_key_env=str(config_dict.get("api_key_env", "")),
            timeout_seconds=int(config_dict.get("timeout_seconds", 60)),
            max_tokens=int(config_dict.get("max_tokens", 0)),
        )
    else:
        cfg = config_dict
    try:
        return _http_chat_completion_raw(messages, cfg)
    except Exception:
        return {"ok": False, "error": "http_call_failed"}


def _http_chat_completion_raw(messages: list, config) -> dict:
    """Raw HTTP chat completion (reuses evidence_bound_model._http_chat_completion pattern)."""
    try:
        from src.evidence_bound_model import _http_chat_completion
        return _http_chat_completion(messages, config)
    except ImportError:
        pass

    import urllib.request
    import urllib.error

    if isinstance(config, dict):
        base_url = config.get("base_url", "")
        model = config.get("model", "")
        api_key_env = config.get("api_key_env", "")
        timeout = config.get("timeout_seconds", 60)
    else:
        base_url = getattr(config, "base_url", "")
        model = getattr(config, "model", "")
        api_key_env = getattr(config, "api_key_env", "")
        timeout = getattr(config, "timeout_seconds", 60)

    url = str(base_url or "").strip().rstrip("/")
    if url and not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    key = os.environ.get(api_key_env or "", "")
    if not url or not model or not key:
        return {"ok": False, "error": "model_config_missing"}

    body = {"model": model, "messages": messages, "temperature": 0, "response_format": {"type": "json_object"}}
    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=max(int(timeout), 1)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"ok": True, "content": content}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"http_{exc.code}"}
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__}


def _extract_json_from_response(value) -> dict:
    """Extract a JSON object from model response content."""
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start():])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return {}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --- Full pipeline ---

def _load_jsonl_dir(records: List[dict], root: str) -> None:
    for name in ("case_memory", "error_memory", "preference_memory"):
        path = os.path.join(root, name, f"{name}.jsonl")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        records.append(rec)
                except json.JSONDecodeError:
                    continue


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
                text = item.get("text") if isinstance(item.get("text"), str) else item.get("content")
                if isinstance(text, str):
                    parts.append(text)
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
        if text and Path(text).expanduser().exists():
            return text
    return str(raw_path or source_path or "").strip()


def _canonical_work_record_from_message(
    *,
    message_id: str,
    source_system: str,
    session_id: str,
    canonical_window_id: str,
    project_id: str,
    source_path: str,
    raw_path: str,
    role: str,
    timestamp: str,
    content: str,
    source_offset_start: int | None,
    source_offset_end: int | None,
    raw_offset_start: int | None,
    raw_offset_end: int | None,
    line_no: int | None,
) -> dict:
    content_clean = re.sub(r"\s+", " ", str(content or "")).strip()
    source_file = _existing_source_file(source_path, raw_path)
    start = raw_offset_start if raw_offset_start is not None else source_offset_start
    end = raw_offset_end if raw_offset_end is not None else source_offset_end
    byte_offsets = {}
    if start is not None and end is not None:
        byte_offsets["_canonical_message"] = {"start": int(start), "end": int(end)}
    source_refs = {
        "source_system": source_system,
        "source_path": source_file,
        "source_role": role,
        "session_id": session_id,
        "canonical_window_id": canonical_window_id,
        "project_id": project_id,
        "byte_offsets": byte_offsets,
        "source_byte_offsets": {
            "start": int(source_offset_start or 0),
            "end": int(source_offset_end or 0),
        },
        "raw_path": raw_path,
        "original_source_path": source_path,
        "line_no": line_no,
        "artifact_type": "canonical_message",
    }
    role_label = "assistant" if role == "assistant" else "user"
    return {
        "exp_id": "canonical-" + hashlib.sha256(
            "|".join([source_system, session_id, str(message_id), content_clean[:160]]).encode("utf-8")
        ).hexdigest()[:16],
        "type": "case_memory",
        "source_system": source_system,
        "session_id": session_id,
        "canonical_window_id": canonical_window_id,
        "project_id": project_id,
        "summary": content_clean[:220],
        "detail": f"上下文：Claude/Opus canonical raw。\n{role_label} 原话：{content_clean}",
        "source_refs": json.dumps(source_refs, ensure_ascii=False),
        "source_author": role,
        "source_role": role,
        "source_message_id": message_id,
        "created_at": timestamp,
    }


def load_canonical_work_records(
    root: str | Path,
    *,
    limit: int = 0,
    scan_limit: int = 5000,
    records_db: str | Path = "",
    source_system: str = "",
    session_id: str = "",
    role: str = "assistant",
    raw_query: str = "",
) -> List[dict]:
    db_path = Path(records_db).expanduser() if records_db else _records_db_path(root)
    if not db_path.exists():
        return []
    max_scan = max(1, int(scan_limit or 5000))
    where = [
        "((raw_offset_start is not null and raw_offset_end is not null) "
        "or (source_offset_start is not null and source_offset_end is not null))",
    ]
    params: list[Any] = []
    if role:
        where.append("role=?")
        params.append(role)
    if source_system:
        where.append("source_system=?")
        params.append(source_system)
    if session_id:
        where.append("session_id=?")
        params.append(session_id)
    records: List[dict] = []
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"""
            select message_id, source_system, session_id, canonical_window_id,
                   project_id, source_path, raw_path, role, timestamp,
                   source_offset_start, source_offset_end,
                   raw_offset_start, raw_offset_end, line_no,
                   content_preview, payload_json
            from canonical_messages
            where {" and ".join(where)}
            order by rowid desc
            limit ?
            """,
            (*params, max_scan),
        )
        for row in rows:
            payload = {}
            try:
                payload = json.loads(row[15] or "{}")
            except Exception:
                payload = {}
            source_line = payload.get("source_line") if isinstance(payload.get("source_line"), dict) else {}
            content = _message_text_from_payload(source_line.get("content")) or str(row[14] or "")
            if raw_query and raw_query not in content:
                continue
            if len(re.sub(r"\s+", " ", content).strip()) < 20:
                continue
            records.append(
                _canonical_work_record_from_message(
                    message_id=str(row[0] or ""),
                    source_system=str(row[1] or ""),
                    session_id=str(row[2] or ""),
                    canonical_window_id=str(row[3] or ""),
                    project_id=str(row[4] or ""),
                    source_path=str(row[5] or ""),
                    raw_path=str(row[6] or ""),
                    role=str(row[7] or ""),
                    timestamp=str(row[8] or ""),
                    content=content,
                    source_offset_start=row[9],
                    source_offset_end=row[10],
                    raw_offset_start=row[11],
                    raw_offset_end=row[12],
                    line_no=row[13],
                )
            )
            if limit and len(records) >= limit:
                break
    return records


def load_raw_records(root: str, include_installed: bool = False) -> List[dict]:
    records: List[dict] = []
    _load_jsonl_dir(records, os.path.join(root, "zhiyi"))
    if include_installed:
        installed = os.path.expanduser(
            "~/Library/Application Support/memcore-cloud/zhiyi"
        )
        if os.path.isdir(installed):
            _load_jsonl_dir(records, installed)
    return records


def run_pipeline(
    root: str,
    *,
    input_source: str = INPUT_SOURCE_MEMORY_RECORDS,
    dry_run: bool = False,
    sample: int = 0,
    include_installed: bool = False,
    records_db: str | Path = "",
    raw_source_system: str = "",
    raw_session_id: str = "",
    raw_role: str = "assistant",
    raw_query: str = "",
    raw_scan_limit: int = 5000,
    model_distill: bool = False,
    model_distill_limit: int = 0,
) -> dict:
    if input_source == INPUT_SOURCE_CANONICAL_MESSAGES:
        records = load_canonical_work_records(
            root,
            limit=sample,
            scan_limit=raw_scan_limit,
            records_db=records_db,
            source_system=raw_source_system,
            session_id=raw_session_id,
            role=raw_role,
            raw_query=raw_query,
        )
    else:
        records = load_raw_records(root, include_installed=include_installed)
    if sample > 0:
        records = records[:sample]

    report: Dict[str, Any] = {
        "input_source": input_source,
        "records_db": str(Path(records_db).expanduser()) if records_db else str(_records_db_path(root)),
        "raw_source_system": raw_source_system,
        "raw_session_id": raw_session_id,
        "raw_role": raw_role if input_source == INPUT_SOURCE_CANONICAL_MESSAGES else "",
        "raw_query": raw_query,
        "raw_scan_limit": raw_scan_limit if input_source == INPUT_SOURCE_CANONICAL_MESSAGES else 0,
        "total_raw": len(records),
        "steps": {},
        "sampling": {
            "approach": "heuristic_offline",
            "note": "small sample, does not prove full-dataset distribution",
        },
    }

    # S0
    worthy, rejected = s0_select_worthy_spans(records)
    report["steps"]["S0_select"] = {
        "worthy": len(worthy),
        "rejected": len(rejected),
        "reject_reasons": {},
        "sampled_rejections": [
            {"exp_id": r["record"].get("exp_id", ""), "reason": r["reason"]}
            for r in rejected[:5]
        ],
    }
    for r in rejected:
        reason = r["reason"]
        report["steps"]["S0_select"]["reject_reasons"][reason] = (
            report["steps"]["S0_select"]["reject_reasons"].get(reason, 0) + 1
        )

    # S1: Exchange-level splits
    all_exchanges = []
    for rec in worthy:
        all_exchanges.extend(s1_split_exchanges(rec))
    report["steps"]["S1_split"] = {"exchange_spans": len(all_exchanges)}

    # S2: 2-5 narrative cards per exchange
    distilled = []
    six_step_coverage = {
        "resolved_refs": 0,
        "normalized_time": 0,
        "participant_attribution": 0,
        "explicit_reasoning": 0,
        "fact_type": 0,
        "entities": 0,
    }
    for exchange_item in all_exchanges:
        cards = s2_distill_from_exchange(exchange_item)
        for card in cards:
            distilled.append(card)
            meta = card.get("distill_meta", {})
            if meta.get("resolved_references", {}).get("resolved"):
                six_step_coverage["resolved_refs"] += 1
            if meta.get("normalized_time", {}).get("normalized"):
                six_step_coverage["normalized_time"] += 1
            if meta.get("participant_attribution", {}).get("roles"):
                six_step_coverage["participant_attribution"] += 1
            if meta.get("explicit_reasoning"):
                six_step_coverage["explicit_reasoning"] += 1
            if meta.get("fact_type") and meta["fact_type"] != "observation":
                six_step_coverage["fact_type"] += 1
            if meta.get("entities"):
                six_step_coverage["entities"] += 1
    report["steps"]["S2_distill"] = {
        "cards": len(distilled),
        "six_step_coverage": six_step_coverage,
    }

    # S3
    validated = []
    validation_failures = []
    raw_verified = 0
    resolution_stats = {"resolved": 0, "unresolved": 0}
    for card in distilled:
        ok, reason, meta = s3_validate(card)
        if ok:
            resolution_report = meta.get("resolution_report", {})
            resolved_path = resolution_report.get("resolved_source_path", "")
            if not resolved_path:
                source_refs = _parse_source_refs(card.get("source_record", {}))
                resolved_path, _, _ = _resolve_source_path(source_refs.get("source_path", ""))
                if resolved_path:
                    resolution_report["resolved_source_path"] = resolved_path
                    resolution_report["resolution_method"] = "pipeline_re_resolve"
            verbatim = card.get("verbatim_excerpt", "")
            if resolved_path and verbatim:
                computed_offsets = _compute_verbatim_byte_offsets(verbatim, resolved_path)
                if computed_offsets:
                    resolution_report["computed_byte_offsets"] = computed_offsets
            card["_resolution_report"] = resolution_report
            card["_s3_pass_reason"] = meta.get("raw_info", "")
            validated.append(card)
            raw_verified += 1
            if meta.get("resolution_report", {}).get("resolution_method", "").startswith(("tail_match", "short_tail_match")):
                resolution_stats["resolved"] += 1
        else:
            validation_failures.append({"reason": reason, "meta": meta})
            if "unresolved" in reason:
                resolution_stats["unresolved"] += 1
    report["steps"]["S3_validate"] = {
        "passed": len(validated),
        "failed": len(validation_failures),
        "raw_verified": raw_verified,
        "resolution_stats": resolution_stats,
        "failure_reasons": {},
        "sampled_failures": [
            {"reason": f["reason"]} for f in validation_failures[:5]
        ],
    }
    for f in validation_failures:
        reason = f["reason"]
        report["steps"]["S3_validate"]["failure_reasons"][reason] = (
            report["steps"]["S3_validate"]["failure_reasons"].get(reason, 0) + 1
        )

    # S4
    deduped = s4_dedupe(validated)
    report["steps"]["S4_dedupe"] = {
        "before": len(validated),
        "after": len(deduped),
        "removed": len(validated) - len(deduped),
    }

    # S4.5: Model distill (optional, bounded)
    model_distill_stats = {
        "prefilter_total": 0, "prefilter_passed": 0, "prefilter_rejected": 0,
        "attempted": 0, "executed": 0, "refined": 0, "failed": 0, "skipped": 0,
        "clean_owner_sample": 0, "revalidation_revoked": 0,
    }
    if model_distill:
        limit = model_distill_limit if model_distill_limit > 0 else len(deduped)
        shortlist = []
        for card in deduped:
            suitable, pfr = _owner_sample_prefilter(card)
            model_distill_stats["prefilter_total"] += 1
            if suitable:
                shortlist.append(card)
                model_distill_stats["prefilter_passed"] += 1
            else:
                model_distill_stats["prefilter_rejected"] += 1

        for card in shortlist:
            if model_distill_stats["attempted"] >= limit:
                break
            _apply_model_distill_to_card(card, execute=True)
            dm = card.get("distill_meta", {})
            md_status = dm.get("model_distill_status", "not_executed")
            model_distill_stats["attempted"] += 1
            if md_status == "refined":
                model_distill_stats["executed"] += 1
                model_distill_stats["refined"] += 1
                clean, reason = _owner_sample_card_ok(card)
                if clean:
                    model_distill_stats["clean_owner_sample"] += 1
                else:
                    dm["source_mode"] = "revoked_owner_sample_quality"
                    dm["model_distill_status"] = "revoked_post_refine"
                    dm["owner_sample_reject_reason"] = reason
                    model_distill_stats["revalidation_revoked"] += 1
            elif md_status in ("insufficient_evidence", "refined_low_confidence", "model_error", "model_config_missing"):
                model_distill_stats["executed"] += 1
                model_distill_stats["failed"] += 1
            else:
                model_distill_stats["skipped"] += 1

        for card in shortlist[model_distill_stats["attempted"]:]:
            card.setdefault("distill_meta", {})["source_mode"] = "heuristic_draft"
            card["distill_meta"]["model_distill_status"] = "skipped_limit"
            model_distill_stats["skipped"] += 1

        for card in deduped:
            dm = card.get("distill_meta", {})
            if dm.get("source_mode") != "evidence_bound_model_distill":
                continue
            clean, reason = _owner_sample_card_ok(card)
            if not clean:
                dm["source_mode"] = "revoked_owner_sample_quality"
                dm["model_distill_status"] = "revoked_post_refine"
                dm["owner_sample_reject_reason"] = reason
                model_distill_stats["revalidation_revoked"] += 1

    report["steps"]["S4_5_model_distill"] = {
        "enabled": model_distill,
        "limit": model_distill_limit,
        **model_distill_stats,
    }

    # S5
    if model_distill:
        write_eligible = [
            card for card in deduped
            if card.get("distill_meta", {}).get("source_mode") == "evidence_bound_model_distill"
        ]
    else:
        write_eligible = deduped
    attempted_cards = len(deduped)
    candidates = [c for c in (s5_build_candidate(card) for card in write_eligible) if c is not None]
    unique_candidates = len(set(c["candidate_id"] for c in candidates))
    report["steps"]["S5_write"] = {
        "attempted_cards": attempted_cards,
        "unique_candidates": unique_candidates,
    }
    report["candidate_objects"] = candidates

    if not dry_run:
        candidates_dir = os.path.join(root, "output", "xingce_work_experience", "candidates")
        actions_dir = os.path.join(root, "output", "xingce_work_experience", "actions")
        _clean_dir(candidates_dir, "xingce-*-candidate.json")
        _clean_dir(actions_dir, "*.jsonl")

        written_candidate_files = []
        written_action_files = []
        for cand in candidates:
            path = write_candidate(cand, candidates_dir)
            written_candidate_files.append(path)
            action_path = write_auto_action(cand, actions_dir)
            written_action_files.append(action_path)
        report["steps"]["S5_write"]["written_candidate_files"] = len(written_candidate_files)
        report["steps"]["S5_write"]["written_action_files"] = len(written_action_files)
        report["steps"]["S5_write"]["candidate_paths"] = written_candidate_files
        report["steps"]["S5_write"]["action_paths"] = written_action_files
    else:
        report["steps"]["S5_write"]["dry_run"] = True

    # Sample cards (all candidates, for debugging)
    report["sample_cards"] = []
    for card in deduped[:5]:
        source_refs = _parse_source_refs(card["source_record"])
        dm = card.get("distill_meta", {})
        report["sample_cards"].append({
            "title": card["title"],
            "one_sentence": card["one_sentence"][:200],
            "situation": card["situation"],
            "action_or_lesson": card["action_or_lesson"],
            "when_to_use": card["when_to_use"],
            "verbatim_excerpt": card["verbatim_excerpt"][:200],
            "raw_excerpt_method": card.get("raw_excerpt_method", ""),
            "s3_pass_reason": card.get("_s3_pass_reason", ""),
            "source_ref": source_refs.get("source_path", ""),
            "source_mode": dm.get("source_mode", "heuristic_draft"),
            "distill_meta": dm,
        })

    # Owner sample: only evidence_bound_model_distill cards for owner inspection
    report["owner_sample"] = []
    for card in deduped:
        clean, _reason = _owner_sample_card_ok(card)
        if not clean:
            continue
        source_refs = _parse_source_refs(card["source_record"])
        dm = card.get("distill_meta", {})
        resolution_report = card.get("_resolution_report", {})
        report["owner_sample"].append({
            "title": card["title"],
            "one_sentence": card["one_sentence"][:200],
            "situation": card["situation"],
            "action_or_lesson": card["action_or_lesson"],
            "when_to_use": card["when_to_use"],
            "verbatim_excerpt": card["verbatim_excerpt"][:200],
            "source_ref": source_refs.get("source_path", ""),
            "raw_offset": source_refs.get("byte_offsets", {}),
            "participant_attribution": dm.get("participant_attribution", {}),
            "source_mode": "evidence_bound_model_distill",
        })
        if len(report["owner_sample"]) >= 5:
            break

    return report


def _clean_dir(directory: str, pattern: str):
    import glob as globmod
    if not os.path.isdir(directory):
        return
    for path in globmod.glob(os.path.join(directory, pattern)):
        try:
            os.remove(path)
        except OSError:
            pass


_BULLET_BLOB_RE = re.compile(r'^[\s]*[-•*]\s+\*\*')


def quarantine_blob_candidates(root: str, *, dry_run: bool = True) -> dict:
    """Scan existing candidates for multi-bullet blob patterns and quarantine them.

    Does NOT delete raw records. Only marks/quarantines candidate JSON files.
    Returns a report of what was found and processed.
    """
    import glob as globmod
    candidates_dir = os.path.join(root, "output", "xingce_work_experience", "candidates")
    quarantine_dir = os.path.join(root, "output", "xingce_work_experience", "quarantined")
    report = {"scanned": 0, "blob_found": 0, "quarantined": 0, "dry_run": dry_run, "blobs": []}

    if not os.path.isdir(candidates_dir):
        return report

    for cand_path in globmod.glob(os.path.join(candidates_dir, "xingce-*-candidate.json")):
        report["scanned"] += 1
        try:
            with open(cand_path, encoding="utf-8") as f:
                cand = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        is_blob = False
        blob_fields = []
        for field in ("title", "summary", "one_sentence", "action_or_lesson"):
            val = str(cand.get(field, "") or "")
            if _BULLET_BLOB_RE.match(val):
                is_blob = True
                blob_fields.append(field)

        if not is_blob:
            continue

        report["blob_found"] += 1
        blob_info = {
            "candidate_id": cand.get("candidate_id", ""),
            "path": cand_path,
            "blob_fields": blob_fields,
            "title_preview": str(cand.get("title", ""))[:80],
        }
        report["blobs"].append(blob_info)

        if not dry_run:
            os.makedirs(quarantine_dir, exist_ok=True)
            basename = os.path.basename(cand_path)
            quarantine_path = os.path.join(quarantine_dir, basename)
            cand["_quarantined"] = {
                "reason": "multi_bullet_blob",
                "quarantined_at": _ts(),
                "original_path": cand_path,
                "blob_fields": blob_fields,
            }
            with open(quarantine_path, "w", encoding="utf-8") as f:
                json.dump(cand, f, ensure_ascii=False, indent=2)
            os.remove(cand_path)
            report["quarantined"] += 1

    return report


def main():
    parser = argparse.ArgumentParser(description="S0→S5 Xingce distillation")
    parser.add_argument("--root", default=str(_REPO_ROOT), help="Project root")
    parser.add_argument(
        "--input-source",
        choices=[INPUT_SOURCE_MEMORY_RECORDS, INPUT_SOURCE_CANONICAL_MESSAGES],
        default=INPUT_SOURCE_MEMORY_RECORDS,
        help="memory_records reads legacy zhiyi records; canonical_messages reads records.db raw messages",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't write files")
    parser.add_argument("--sample", type=int, default=0, help="Limit raw records (0=all)")
    parser.add_argument("--installed-runtime", action="store_true",
                        help="Also load from installed runtime zhiyi")
    parser.add_argument("--records-db", default="", help="records.db path for canonical_messages input")
    parser.add_argument("--raw-source-system", default="", help="Filter canonical_messages by source_system")
    parser.add_argument("--raw-session-id", default="", help="Filter canonical_messages by session_id")
    parser.add_argument("--raw-role", default="assistant", help="Filter canonical_messages by role")
    parser.add_argument("--raw-query", default="", help="Only consider canonical messages containing this text")
    parser.add_argument("--raw-scan-limit", type=int, default=5000)
    parser.add_argument("--model-distill", action="store_true",
                        help="Run model distill on validated candidates")
    parser.add_argument("--model-distill-limit", type=int, default=0,
                        help="Max model distill attempts (0=all shortlisted)")
    parser.add_argument("--quarantine-blobs", action="store_true",
                        help="Scan and quarantine multi-bullet blob candidates")
    parser.add_argument("--quarantine-execute", action="store_true",
                        help="Actually move blobs to quarantined/ (default is dry-run)")
    args = parser.parse_args()

    if args.quarantine_blobs:
        report = quarantine_blob_candidates(args.root, dry_run=not args.quarantine_execute)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    report = run_pipeline(
        args.root,
        input_source=args.input_source,
        dry_run=args.dry_run,
        sample=args.sample,
        include_installed=args.installed_runtime,
        records_db=args.records_db,
        raw_source_system=args.raw_source_system,
        raw_session_id=args.raw_session_id,
        raw_role=args.raw_role,
        raw_query=args.raw_query,
        raw_scan_limit=args.raw_scan_limit,
        model_distill=args.model_distill,
        model_distill_limit=args.model_distill_limit,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
