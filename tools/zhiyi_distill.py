#!/usr/bin/env python3
"""Evidence-bound Zhiyi preference distillation pipeline.

Reads old preference_memory records, resolves their raw source, asks a model to
distill owner-readable preference cards, validates evidence support, and writes
only clean candidates to output/zhiyi_preference_cards/candidates when not in
dry-run mode. The default is dry-run.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from src.evidence_bound_model import EvidenceBoundModelConfig, default_model_config
except Exception:  # pragma: no cover
    EvidenceBoundModelConfig = None
    default_model_config = None

try:
    from src.p2_extract import classify_preference_intent, tool_result_pollution_guard
except Exception:  # pragma: no cover
    classify_preference_intent = None
    tool_result_pollution_guard = None


ZHIYI_DISTILL_CONTRACT = "time_library_zhiyi_preference_distill.v1"
ZHIYI_MODEL_SOURCE_MODE = "evidence_bound_model_distill"
DEFAULT_OUTPUT_REL = "output/zhiyi_preference_cards"
PREFERENCE_TYPES = {"preference_memory", "raw_user_message"}
INPUT_SOURCE_PREFERENCE_MEMORY = "preference_memory"
INPUT_SOURCE_RAW_USER = "raw_user"
_DISALLOWED_SOURCE_RE = re.compile(
    r"(字幕|subtitle|skill dump|skill\.md|plugin\.json|自测|smoke test|"
    r"施工报告|本轮施工|本轮改动|工具输出|stdout|stderr|Process exited with code)",
    re.IGNORECASE,
)
_RAW_USER_SKIP_RE = re.compile(
    r"(<environment_context>|# AGENTS\.md instructions|Applications mentioned by the user|"
    r"Selected text:|Files mentioned by the user|The attached pasted text file|"
    r"capability check|不要召回真实记忆|只做.*能力检查|Say OK only)",
    re.IGNORECASE | re.DOTALL,
)
_RAW_USER_RELAY_RE = re.compile(
    r"(claude的(反馈|复核|建议|看法)|让mimo|给 Codex|致 Codex|Opus 上机二签|"
    r"二签结果|派单来了|可直接转给 Codex|【派单|【合并派单|【接续·先读再动手】|"
    r"Codex 报|MiMo 施工|流水落好|落二签|转给 Codex|"
    r"原创\s+|在小说阅读器|GitHubDaily|小 G|Hyman的杂货铺|V1ki|"
    r"Opus/Codex整理|回执|流水|施工稿|施工报告|验收门|"
    r"Another language model started|Handoff Summary)",
    re.IGNORECASE,
)
_RAW_USER_PREFERENCE_SIGNALS = (
    "我喜欢",
    "我不喜欢",
    "我更喜欢",
    "我希望",
    "我习惯",
    "以后按",
    "以后用",
    "以后不要",
    "你以后",
    "不要再",
    "别再",
    "用 Time Library",
    "不用拼音",
    "time_library",
    "实地核源",
    "别信二手",
    "一致≠印证",
    "一致不等于印证",
    "独立第二源",
    "先给结论",
    "再给证据",
    "最小化想象者负荷",
    "只在决策点出现",
    "不在旧码上签运行态",
    "别信公众号",
)
_RAW_USER_DIRECTIVE_RE = re.compile(
    r"(我(喜欢|不喜欢|更喜欢|希望|习惯|要求|建议)|"
    r"你以后|以后(按|用|不要)|不要再|别再|"
    r"取名为|命名|英文名不是|"
    r"回答先给结论|先给结论再给证据|"
    r"一致≠印证|一致不等于印证|独立第二源|"
    r"实地核源|别信二手|别信公众号|"
    r"最小化想象者负荷|只在决策点出现|"
    r"不在旧码上签运行态|不用拼音|用\s*Time Library|"
    r"(不是|不要用|不用)\s*time_library)",
    re.IGNORECASE,
)
_RAW_USER_SPAN_REJECT_RE = re.compile(
    r"(^[#>`|*-]+|https?://|/" + "(?:Volumes|Users)" + r"/|"
    r"原创|在小说阅读器|GitHub|ICML|论文|文章|开源|"
    r"await |session\.|add_message|token=|probe-|hash=|"
    r"回执|流水|施工|验收|二签|复核|报告|派单|"
    r"pytest|passed|failed|source_code|targeted_test|connected_runtime|"
    r"我可以告诉你|我去读|我刚|我核|我跑|我签|"
    r"新存|MEMORY\.md|已挂进|索引|下次新会话不用重捋)",
    re.IGNORECASE,
)
_RAW_USER_AGENT_WORK_RE = re.compile(
    r"(回答|证据|核源|二手|印证|第二源|想象者负荷|决策点|"
    r"旧码|运行态|Time Library|Time Library|time_library|"
    r"agent|Agent|模型|召回|记忆|书单|阅读区|借阅证|过滤轴|窗口|平台|skill|MCP)",
    re.IGNORECASE,
)
_RAW_USER_ONE_OFF_RE = re.compile(
    r"(现在|这轮|这一刀|下一刀|先|然后|跑完|同步|重启|部署|验证|"
    r"授权|执行|读\s+活仓|按\s+NAS|单焦点|别从聊天拼|固定格式报|"
    r"write-real|pytest|py_compile|curl|git\s+diff|git\s+status)",
    re.IGNORECASE,
)
_RAW_USER_LONG_RELAY_MARKERS = (
    "## ",
    "```",
    "|---|",
    "核点",
    "签字",
    "验收",
    "回执",
    "报告",
    "流水",
    "施工",
    "派单",
    "Handoff Summary",
    "Another language model",
    "Files mentioned by the user",
)
_PUBLIC_NAME_NORMALIZE = {
    "zhiyi_recall": "time_library_recall",
    "time-library": "time-library",
}
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_ACCEPTED_OWNER_SAMPLE_DECISION = "accepted_by_owner_2026_07_01"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value: Any, *, limit: int = 1000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def _parse_source_refs(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        for item in value:
            parsed = _parse_source_refs(item)
            if parsed:
                return parsed
        return {}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"source_path": value} if "/" in value or value.endswith(".jsonl") else {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _extract_text_fields(obj: Any, max_depth: int = 5) -> list[str]:
    if max_depth <= 0:
        return []
    if isinstance(obj, str) and obj.strip():
        return [obj]
    if isinstance(obj, dict):
        out: list[str] = []
        for value in obj.values():
            out.extend(_extract_text_fields(value, max_depth - 1))
        return out
    if isinstance(obj, list):
        out: list[str] = []
        for value in obj:
            out.extend(_extract_text_fields(value, max_depth - 1))
        return out
    return []


def _message_text_from_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        parts: list[str] = []
        for item in payload:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(part for part in parts if part)
    if isinstance(payload, dict):
        for key in ("content", "text", "message"):
            if key in payload:
                text = _message_text_from_payload(payload.get(key))
                if text:
                    return text
    return ""


def _content_byte_span(content: str, selected: str, base_start: int = 0) -> dict[str, int] | None:
    if not content or not selected:
        return None
    char_start = content.find(selected)
    if char_start < 0:
        compact_selected = re.sub(r"\s+", " ", selected).strip()
        compact_content = re.sub(r"\s+", " ", content).strip()
        if not compact_selected or compact_selected not in compact_content:
            return None
        return None
    byte_start = int(base_start) + len(content[:char_start].encode("utf-8"))
    return {"start": byte_start, "end": byte_start + len(selected.encode("utf-8"))}


def _source_text_offsets(
    source_path: str,
    selected: str,
    *,
    range_start: int = 0,
    range_end: int = 0,
) -> dict[str, int] | None:
    if not source_path or not selected:
        return None
    path = Path(source_path).expanduser()
    if not path.exists():
        return None
    needle = selected.encode("utf-8")
    try:
        data = path.read_bytes()
    except OSError:
        return None
    start_hint = max(0, int(range_start or 0))
    end_hint = min(len(data), int(range_end or 0)) if int(range_end or 0) > 0 else len(data)
    if start_hint < end_hint:
        local = data[start_hint:end_hint].find(needle)
        if local >= 0:
            start = start_hint + local
            return {"start": start, "end": start + len(needle)}
    start = data.find(needle)
    if start >= 0:
        return {"start": start, "end": start + len(needle)}
    return None


def _split_user_preference_spans(text: str) -> list[str]:
    content = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    compact_content = _clean(content, limit=6000)
    if _RAW_USER_SKIP_RE.search(compact_content):
        return []
    if len(compact_content) > 700 and (
        _RAW_USER_RELAY_RE.search(compact_content)
        or sum(1 for marker in _RAW_USER_LONG_RELAY_MARKERS if marker in compact_content) >= 2
    ):
        return []
    spans: list[str] = []
    chunks: list[str] = []
    for piece in re.split(r"[\n。！？!?；;]+", content):
        chunks.extend(
            part
            for part in re.split(r"(?=还有一点|另外|其实我现在最大的困扰|我建议|我提个方向|我把这个新的模式取名为)", piece)
            if part
        )
    for block in chunks:
        block = _clean(block, limit=900)
        if not block:
            continue
        if _RAW_USER_SKIP_RE.search(block):
            continue
        block = re.sub(r"^[\s:：,，、\-*•]+", "", block).strip()
        block = re.sub(r"[\s,，、:：]+$", "", block).strip()
        if len(block) > 360:
            continue
        if _RAW_USER_RELAY_RE.search(block):
            continue
        if _RAW_USER_SPAN_REJECT_RE.search(block):
            continue
        if len(block) < 12 or len(block) > 260:
            continue
        if not _RAW_USER_AGENT_WORK_RE.search(block):
            continue
        if not _RAW_USER_DIRECTIVE_RE.search(block):
            continue
        if _RAW_USER_ONE_OFF_RE.search(block) and not any(
            marker in block
            for marker in (
                "不在旧码上签运行态",
                "一致≠印证",
                "一致不等于印证",
                "先给结论",
                "最小化想象者负荷",
                "Time Library",
                "time_library",
                "实地核源",
                "别信二手",
            )
        ):
            continue
        spans.append(block)
    return list(dict.fromkeys(spans))


def _raw_user_signal(text: str) -> bool:
    compact = _clean(text, limit=5000)
    if not compact:
        return False
    if _RAW_USER_SKIP_RE.search(compact):
        return False
    if len(compact) > 700 and (
        _RAW_USER_RELAY_RE.search(compact)
        or sum(1 for marker in _RAW_USER_LONG_RELAY_MARKERS if marker in compact) >= 2
    ):
        return bool(_split_user_preference_spans(compact))
    if len(compact) > 900:
        return bool(_split_user_preference_spans(compact))
    return bool(_split_user_preference_spans(compact) or any(signal.lower() in compact.lower() for signal in _RAW_USER_PREFERENCE_SIGNALS))


def _json_line_role_and_content(obj: dict[str, Any]) -> tuple[str, str]:
    role = str(obj.get("role") or "").strip().lower()
    content: Any = obj.get("content")
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
    if not role and isinstance(message, dict):
        role = str(message.get("role") or "").strip().lower()
        content = message.get("content")
    if not role and isinstance(payload, dict):
        role = str(payload.get("role") or "").strip().lower()
        content = payload.get("content")
        if not role and isinstance(payload.get("message"), dict):
            role = str(payload["message"].get("role") or "").strip().lower()
            content = payload["message"].get("content")
        if not role and payload.get("type") == "user_message":
            role = "user"
            content = payload.get("message")
    if not role and obj.get("type") == "user":
        role = "user"
    return role, _message_text_from_payload(content)


def _record_from_raw_user_message(
    *,
    message_id: str,
    source_system: str,
    session_id: str,
    canonical_window_id: str = "",
    project_id: str = "",
    source_path: str,
    raw_path: str,
    timestamp: str,
    content: str,
    evidence_text: str | None = None,
    source_offset_start: int | None = None,
    source_offset_end: int | None = None,
    raw_offset_start: int | None = None,
    raw_offset_end: int | None = None,
    line_no: int | None = None,
) -> dict[str, Any]:
    content_clean = _clean(content, limit=5000)
    evidence_clean = _clean(evidence_text if evidence_text is not None else content, limit=900)
    source_file = str(raw_path or "")
    if source_file and not Path(source_file).expanduser().exists():
        source_file = ""
    if not source_file:
        source_file = str(source_path or "")
    byte_offsets = {
        "start": int(raw_offset_start if raw_offset_start is not None else source_offset_start or 0),
        "end": int(raw_offset_end if raw_offset_end is not None else source_offset_end or 0),
    }
    evidence_offsets = _source_text_offsets(
        source_file,
        evidence_clean,
        range_start=byte_offsets["start"],
        range_end=byte_offsets["end"],
    )
    if not evidence_offsets:
        evidence_offsets = _content_byte_span(content, evidence_clean, byte_offsets["start"]) if evidence_clean else None
    if evidence_offsets:
        byte_offsets = evidence_offsets
    source_refs = {
        "source_system": source_system,
        "source_path": source_file,
        "source_role": "user",
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
        "raw_user_input": True,
        "source_text_span": evidence_clean,
    }
    return {
        "exp_id": "raw-user-" + hashlib.sha256(
            "|".join([source_system, session_id, str(message_id), evidence_clean[:120]]).encode("utf-8")
        ).hexdigest()[:16],
        "type": "raw_user_message",
        "summary": evidence_clean[:160],
        "detail": evidence_clean,
        "source_message_text": content_clean,
        "source_author": "user",
        "source_role": "user",
        "source_message_id": message_id,
        "source_refs": source_refs,
        "created_at": timestamp,
    }


def _resolve_source_path(source_path: str, root: str | Path = "") -> str:
    text = _clean(source_path, limit=1000)
    if not text:
        return ""
    candidates = [Path(text).expanduser()]
    root_path = Path(root).expanduser() if root else None
    if root_path and not Path(text).is_absolute():
        candidates.append(root_path / text)
    candidates.append(_REPO_ROOT / text)
    for candidate in candidates:
        try:
            if candidate.exists():
                return str(candidate)
        except OSError:
            continue
    return text


def _read_raw_text_for_record(record: dict[str, Any], root: str | Path = "") -> tuple[str, dict[str, Any]]:
    refs = _parse_source_refs(record.get("source_refs"))
    source_path = _resolve_source_path(str(refs.get("source_path") or ""), root)
    if not source_path or not Path(source_path).exists():
        fallback = "\n".join(_clean(record.get(key)) for key in ("summary", "detail") if _clean(record.get(key)))
        return fallback, {**refs, "source_path": source_path, "raw_read_status": "source_missing_record_text_fallback"}
    fields: list[str] = []
    roles_seen: set[str] = set()
    try:
        with open(source_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f):
                if line_no > 2000:
                    break
                text = line.strip()
                if not text:
                    continue
                try:
                    obj = json.loads(text)
                    if isinstance(obj, dict):
                        role, content = _json_line_role_and_content(obj)
                        if role:
                            roles_seen.add(role)
                        if role == "user" and content:
                            fields.append(content)
                        elif not role:
                            fields.extend(_extract_text_fields(obj))
                    else:
                        fields.extend(_extract_text_fields(obj))
                except Exception:
                    fields.append(text)
    except OSError:
        fallback = "\n".join(_clean(record.get(key)) for key in ("summary", "detail") if _clean(record.get(key)))
        return fallback, {**refs, "source_path": source_path, "raw_read_status": "read_error_record_text_fallback"}
    raw_text = "\n".join(_clean(field, limit=1200) for field in fields if _clean(field))
    source_role = "user" if "user" in roles_seen else sorted(roles_seen)[0] if roles_seen else ""
    return raw_text, {**refs, "source_path": source_path, "raw_read_status": "ok", "source_role": source_role}


def _verbatim_offsets(
    verbatim: str,
    source_path: str,
    *,
    range_start: int = 0,
    range_end: int = 0,
) -> dict[str, int] | None:
    if not verbatim or not source_path or not Path(source_path).exists():
        return None
    needle = verbatim.encode("utf-8")
    try:
        data = Path(source_path).read_bytes()
    except OSError:
        return None
    if range_start or range_end:
        start_hint = max(0, int(range_start or 0))
        end_hint = min(len(data), int(range_end or 0)) if int(range_end or 0) > 0 else len(data)
        if start_hint < end_hint:
            local = data[start_hint:end_hint].find(needle)
            if local >= 0:
                start = start_hint + local
                return {"start": start, "end": start + len(needle)}
    start = data.find(needle)
    if start < 0:
        normalized = re.sub(r"\s+", " ", verbatim).strip()
        if not normalized:
            return None
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            return None
        match = re.search(re.escape(normalized[:80]), re.sub(r"\s+", " ", text))
        if not match:
            return None
        prefix = text[: match.start()]
        start = len(prefix.encode("utf-8", errors="ignore"))
        return {"start": start, "end": start + len(normalized.encode("utf-8"))}
    return {"start": start, "end": start + len(needle)}


def _extract_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _http_chat_completion_with_config(messages: list[dict[str, Any]], config_dict: dict[str, Any]) -> dict[str, Any]:
    if EvidenceBoundModelConfig is None:
        return {"ok": False, "error": "model_config_missing"}
    try:
        from src.evidence_bound_model import _http_chat_completion

        cfg = EvidenceBoundModelConfig(
            provider=str(config_dict.get("provider", "")),
            model=str(config_dict.get("model", "")),
            base_url=str(config_dict.get("base_url", "")),
            api_key_env=str(config_dict.get("api_key_env", "")),
            credential_ref=str(config_dict.get("credential_ref", "")),
            timeout_seconds=int(config_dict.get("timeout_seconds", 60)),
            max_tokens=int(config_dict.get("max_tokens", 0)),
            transparency_ledger_path=str(config_dict.get("transparency_ledger_path") or _transparency_ledger_path()),
            transparency_call_kind=str(config_dict.get("transparency_call_kind") or "distillation"),
        )
        return _http_chat_completion(messages, cfg)
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__}


def _transparency_ledger_path() -> str:
    try:
        from src.distill_transparency import default_ledger_path
    except Exception:
        from distill_transparency import default_ledger_path
    return str(default_ledger_path())


def _model_config_dict() -> dict[str, Any]:
    if default_model_config is None:
        return {}
    cfg = default_model_config()
    if int(getattr(cfg, "max_tokens", 0) or 0) <= 0 and EvidenceBoundModelConfig is not None:
        cfg = EvidenceBoundModelConfig(
            provider=cfg.provider,
            model=cfg.model,
            base_url=cfg.base_url,
            api_key_env=cfg.api_key_env,
            credential_ref=cfg.credential_ref,
            timeout_seconds=cfg.timeout_seconds,
            max_tokens=700,
        )
    result = {
        "provider": getattr(cfg, "provider", ""),
        "model": getattr(cfg, "model", ""),
        "base_url": getattr(cfg, "base_url", ""),
        "api_key_env": getattr(cfg, "api_key_env", ""),
        "credential_ref": getattr(cfg, "credential_ref", ""),
        "timeout_seconds": getattr(cfg, "timeout_seconds", 60),
        "max_tokens": getattr(cfg, "max_tokens", 700),
    }
    if _api_key_ready(result):
        return result
    fallback_key = next(
        (
            name
            for name in ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "MEMCORE_ZHIYI_API_KEY")
            if os.environ.get(name)
        ),
        "",
    )
    if not fallback_key:
        return result
    if "MINIMAX" in fallback_key:
        return {
            "provider": "minimax",
            "model": os.environ.get("MINIMAX_MODEL") or os.environ.get("MINIMAX_CN_MODEL") or "MiniMax-M2.7-highspeed",
            "base_url": os.environ.get("MINIMAX_BASE_URL") or os.environ.get("MINIMAX_CN_BASE_URL") or "https://api.minimaxi.com/v1",
            "api_key_env": fallback_key,
            "credential_ref": "",
            "timeout_seconds": 60,
            # MiniMax M3 may spend a long preamble inside <think> unless the
            # budget is large enough to reach the required JSON object.
            "max_tokens": int(os.environ.get("MINIMAX_MAX_TOKENS") or 1800),
        }
    if "DEEPSEEK" in fallback_key:
        return {
            "provider": "deepseek",
            "model": os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash",
            "base_url": os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1",
            "api_key_env": fallback_key,
            "credential_ref": "",
            "timeout_seconds": 60,
            "max_tokens": 700,
        }
    try:
        cfg = default_model_config(api_key_env=fallback_key)
    except Exception:
        return result
    return {
        "provider": getattr(cfg, "provider", ""),
        "model": getattr(cfg, "model", ""),
        "base_url": getattr(cfg, "base_url", ""),
        "api_key_env": getattr(cfg, "api_key_env", ""),
        "credential_ref": getattr(cfg, "credential_ref", ""),
        "timeout_seconds": getattr(cfg, "timeout_seconds", 60),
        "max_tokens": getattr(cfg, "max_tokens", 700) or 700,
    }


def _api_key_ready(config: dict[str, Any]) -> bool:
    key_env = str(config.get("api_key_env") or "").strip()
    if key_env and os.environ.get(key_env):
        return True
    credential_ref = str(config.get("credential_ref") or "").strip()
    if not credential_ref:
        return False
    try:
        from src.model_api_key_store import resolve_model_api_key
    except Exception:
        from model_api_key_store import resolve_model_api_key
    key, _source = resolve_model_api_key(api_key_env=key_env, credential_ref=credential_ref)
    return bool(key)


def load_preference_records(root: str | Path, *, limit: int = 0) -> list[dict[str, Any]]:
    root_path = Path(root).expanduser()
    paths = [
        root_path / "zhiyi" / "preference_memory" / "preference_memory.jsonl",
        root_path / "preference_memory" / "preference_memory.jsonl",
    ]
    records: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig") as f:
            for line in f:
                text = line.strip()
                if not text:
                    continue
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    records.append(obj)
                if limit and len(records) >= limit:
                    return records
    return records


def _records_db_path(root: str | Path) -> Path:
    override = os.environ.get("MEMCORE_RECORDS_DB", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(root).expanduser() / "output" / "records" / "records.db"


def load_raw_user_records(
    root: str | Path,
    *,
    limit: int = 0,
    scan_limit: int = 5000,
    records_db: str | Path = "",
    source_system: str = "",
    session_id: str = "",
    raw_query: str = "",
) -> list[dict[str, Any]]:
    root_path = Path(root).expanduser()
    db_path = Path(records_db).expanduser() if records_db else _records_db_path(root_path)
    if db_path.exists():
        return _dedupe_raw_user_records(_load_raw_user_records_from_db(
            db_path,
            limit=limit,
            scan_limit=scan_limit,
            source_system=source_system,
            session_id=session_id,
            raw_query=raw_query,
        ), limit=limit)
    return _dedupe_raw_user_records(
        _load_raw_user_records_from_files(root_path, limit=limit, scan_limit=scan_limit, raw_query=raw_query),
        limit=limit,
    )


def _dedupe_raw_user_records(records: list[dict[str, Any]], *, limit: int = 0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        refs = _parse_source_refs(record.get("source_refs"))
        key = (
            str(refs.get("source_system") or ""),
            str(refs.get("session_id") or ""),
            _clean(record.get("detail") or record.get("summary"), limit=500),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
        if limit and len(out) >= limit:
            break
    return out


def _load_raw_user_records_from_db(
    db_path: Path,
    *,
    limit: int = 0,
    scan_limit: int = 5000,
    source_system: str = "",
    session_id: str = "",
    raw_query: str = "",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    max_scan = max(1, int(scan_limit or 5000))
    query_limit = max_scan
    where = [
        "role='user'",
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
            (*params, query_limit),
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
            spans = _split_user_preference_spans(content)
            if not spans:
                continue
            for span in spans:
                record = _record_from_raw_user_message(
                    message_id=str(row[0] or ""),
                    source_system=str(row[1] or ""),
                    session_id=str(row[2] or ""),
                    canonical_window_id=str(row[3] or ""),
                    project_id=str(row[4] or ""),
                    source_path=str(row[5] or ""),
                    raw_path=str(row[6] or ""),
                    timestamp=str(row[8] or ""),
                    content=content,
                    evidence_text=span,
                    source_offset_start=int(row[9] or 0),
                    source_offset_end=int(row[10] or 0),
                    raw_offset_start=int(row[11] or 0),
                    raw_offset_end=int(row[12] or 0),
                    line_no=int(row[13] or 0),
                )
                records.append(record)
                if limit and len(records) >= limit:
                    break
            if limit and len(records) >= limit:
                break
    return records


def _load_raw_user_records_from_files(
    root_path: Path,
    *,
    limit: int = 0,
    scan_limit: int = 5000,
    raw_query: str = "",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    scanned = 0
    memory_root = root_path / "memory"
    paths = sorted(memory_root.glob("**/*.jsonl"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True) if memory_root.exists() else []
    for path in paths:
        try:
            offset = 0
            with path.open("rb") as f:
                for line_no, raw_line in enumerate(f, start=1):
                    if scanned >= scan_limit:
                        return records
                    start = offset
                    offset += len(raw_line)
                    scanned += 1
                    try:
                        obj = json.loads(raw_line.decode("utf-8", errors="ignore"))
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    role, content = _json_line_role_and_content(obj)
                    if role != "user":
                        continue
                    if raw_query and raw_query not in content:
                        continue
                    spans = _split_user_preference_spans(content)
                    for span in spans:
                        records.append(
                            _record_from_raw_user_message(
                                message_id=str(obj.get("uuid") or obj.get("id") or f"{path}:{line_no}"),
                                source_system=str(obj.get("source_system") or "raw_jsonl"),
                                session_id=str(obj.get("sessionId") or obj.get("session_id") or ""),
                                source_path=str(path),
                                raw_path=str(path),
                                timestamp=str(obj.get("timestamp") or ""),
                                content=content,
                                evidence_text=span,
                                source_offset_start=start,
                                source_offset_end=offset,
                                raw_offset_start=start,
                                raw_offset_end=offset,
                                line_no=line_no,
                            )
                        )
                        if limit and len(records) >= limit:
                            return records
        except OSError:
            continue
    return records


def s0_select_preference_candidates(records: list[dict[str, Any]], *, root: str | Path = "") -> tuple[list[dict[str, Any]], dict[str, int]]:
    selected: list[dict[str, Any]] = []
    reject_reasons: dict[str, int] = {}

    def reject(reason: str) -> None:
        reject_reasons[reason] = reject_reasons.get(reason, 0) + 1

    for record in records:
        if not isinstance(record, dict):
            reject("not_object")
            continue
        record_type = _clean(record.get("type") or record.get("_type"))
        if record_type not in PREFERENCE_TYPES:
            reject("not_preference_memory")
            continue
        if record_type == "raw_user_message":
            refs = _parse_source_refs(record.get("source_refs"))
            evidence_text = _clean(record.get("detail") or record.get("summary"), limit=5000)
            if str(record.get("source_role") or record.get("source_author") or "").lower() != "user":
                reject("raw_user_source_role_not_user")
                continue
            if not _split_user_preference_spans(evidence_text):
                reject("raw_user_not_direct_preference_span")
                continue
        else:
            raw_text, refs = _read_raw_text_for_record(record, root)
            combined = "\n".join(
                _clean(record.get(key), limit=1400)
                for key in ("summary", "detail")
                if _clean(record.get(key))
            )
            evidence_text = raw_text or combined
        source_role = str(record.get("source_role") or refs.get("source_role") or "").strip().lower()
        if record_type == "raw_user_message" and source_role != "user":
            reject("source_role_not_user")
            continue
        if not evidence_text:
            reject("empty")
            continue
        if _DISALLOWED_SOURCE_RE.search(evidence_text):
            reject("disallowed_source_material")
            continue
        if tool_result_pollution_guard:
            guard = tool_result_pollution_guard(evidence_text, role="user")
            if guard.get("blocked"):
                reject(str(guard.get("category") or "pollution_guard"))
                continue
        intent = classify_preference_intent(evidence_text) if classify_preference_intent else {"write_preference": True}
        if record_type == "raw_user_message" and _raw_user_signal(evidence_text):
            intent = {**intent, "write_preference": True, "intent_type": intent.get("intent_type") or "raw_user_preference_signal"}
        if not intent.get("write_preference"):
            reject(str(intent.get("intent_type") or "not_preference"))
            continue
        candidate_source_role = source_role
        if record_type == "raw_user_message" and not candidate_source_role:
            candidate_source_role = "user"
        selected.append({
            "record": record,
            "evidence_text": evidence_text,
            "source_refs": refs,
            "intent": intent,
            "input_source": record_type,
            "source_role": candidate_source_role,
        })
    return selected, reject_reasons


def _build_prompt(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    record = candidate["record"]
    payload = {
        "task_kind": "zhiyi_preference_card_distill",
        "candidate": {
            "exp_id": record.get("exp_id", ""),
            "summary": record.get("summary", ""),
            "detail": record.get("detail", ""),
            "source_refs": candidate.get("source_refs", {}),
        },
        "evidence": [
            {
                "source_id": "verbatim",
                "evidence_ref": "verbatim",
                "role": candidate.get("source_role") or "user",
                "authority": "user_fact",
                "text": candidate.get("evidence_text", ""),
                "source_refs": candidate.get("source_refs", {}),
            }
        ],
        "rules": [
            "Use only supplied evidence.",
            "Return one JSON object only; no markdown, no prose.",
            "Distill exactly one stable user preference, wording preference, correction, or durable preference boundary.",
            "Reject pasted articles, subtitles, skill dumps, tests, tool output, and one-off operational status.",
            "The source must be user-authored. If it is not user-authored, reject.",
            "The evidence is already a short user-authored span; do not import context from outside it.",
            "Preserve uncertainty. If the user is exploring feasibility or saying '会不会不太好', phrase the card as a preference to evaluate cautiously, not a hard command.",
            "title must be one short sentence the user can understand in 2 seconds.",
            "If the user evidence is Chinese, the title must be Chinese or bilingual with Chinese; do not return an English-only title.",
            "preference_statement must be supported by verbatim_excerpt.",
            "verbatim_excerpt must be a direct substring of evidence and should carry the preference itself.",
            "when_to_use describes the trigger signal for future agents.",
            "Do not use public names zhiyi_recall, time-library, or 知意 as product/MCP entry names; use Time Library when needed.",
        ],
        "response_schema": {
            "schema": "zhiyi_preference_card_distill.v1",
            "verdict": "refined|insufficient_evidence|reject",
            "title": "short sentence",
            "preference_statement": "one sentence",
            "when_to_use": "trigger signal",
            "object": "what this preference applies to",
            "collapse_condition": "when this preference should be downgraded",
            "verbatim_excerpt": "direct evidence substring",
            "confidence": "0..1",
            "supporting_refs": ["verbatim"],
        },
    }
    return [
        {"role": "system", "content": "Return a compact JSON object only. Do not include <think>, markdown, analysis, or prose. Distill Time Library preference cards strictly from the supplied user evidence."},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _normalize_public_names(text: str) -> str:
    value = text
    for old, new in _PUBLIC_NAME_NORMALIZE.items():
        value = re.sub(re.escape(old), new, value, flags=re.IGNORECASE)
    return value.replace("知意", "Time Library")


def _has_direct_user_preference_signal(text: str) -> bool:
    compact = _clean(text, limit=1200)
    return bool(compact and _RAW_USER_DIRECTIVE_RE.search(compact))


def _candidate_id(record: dict[str, Any], verbatim: str) -> str:
    seed = "|".join([str(record.get("exp_id") or ""), verbatim])
    return "zhiyi-distill-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _validate_card(parsed: dict[str, Any], candidate: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    if not parsed:
        return False, "non_json_model_response", {}
    verdict = _clean(parsed.get("verdict"), limit=80).lower()
    source_refs = dict(candidate.get("source_refs") or {})
    source_role = str(candidate.get("source_role") or source_refs.get("source_role") or "").strip().lower()
    relaxed_user_evidence = (
        verdict == "insufficient_evidence"
        and candidate.get("input_source") == "raw_user_message"
        and source_role == "user"
        and _has_direct_user_preference_signal(candidate.get("evidence_text", ""))
    )
    if verdict not in {"refined", "keep_original"} and not relaxed_user_evidence:
        return False, verdict or "not_refined", {}
    refs = [str(ref).strip() for ref in parsed.get("supporting_refs") or [] if str(ref).strip()]
    if "verbatim" not in refs:
        return False, "supporting_refs_missing_verbatim", {}
    if source_role != "user":
        return False, "source_role_not_user", {}
    title = _normalize_public_names(_clean(parsed.get("title"), limit=80))
    statement = _normalize_public_names(_clean(parsed.get("preference_statement") or parsed.get("summary"), limit=240))
    when_to_use = _normalize_public_names(_clean(parsed.get("when_to_use"), limit=160))
    obj = _normalize_public_names(_clean(parsed.get("object"), limit=120))
    collapse = _normalize_public_names(_clean(parsed.get("collapse_condition"), limit=180))
    verbatim = _clean(parsed.get("verbatim_excerpt"), limit=700)
    evidence_text = candidate.get("evidence_text", "")
    if not title or not statement or not when_to_use:
        return False, "missing_required_fields", {}
    if _has_cjk(evidence_text) and not _has_cjk(title):
        return False, "title_language_mismatch", {}
    if not verbatim or verbatim not in evidence_text:
        return False, "verbatim_not_in_evidence", {}
    if statement and verbatim[:8] not in evidence_text:
        return False, "statement_not_evidence_bound", {}
    source_path = source_refs.get("source_path", "")
    source_offsets = source_refs.get("byte_offsets") if isinstance(source_refs.get("byte_offsets"), dict) else {}
    offsets = _verbatim_offsets(
        verbatim,
        source_path,
        range_start=int(source_offsets.get("start") or 0),
        range_end=int(source_offsets.get("end") or 0),
    )
    if source_path and not offsets:
        return False, "verbatim_byte_offset_not_found", {}
    evidence_refs = []
    if source_path:
        ref = dict(source_refs)
        if offsets:
            ref["byte_offsets"] = offsets
        evidence_refs.append(ref)
    card = {
        "candidate_id": _candidate_id(candidate["record"], verbatim),
        "candidate_type": "zhiyi_preference_card",
        "schema_version": "2026.7.1",
        "created_at": _now(),
        "library_shelf": "zhiyi",
        "type": "preference_memory",
        "source_mode": ZHIYI_MODEL_SOURCE_MODE,
        "lifecycle_status": "active",
        "title": title,
        "summary": statement,
        "preference_statement": statement,
        "when_to_use": when_to_use,
        "object": obj,
        "collapse_condition": collapse or "用户后续明确改口或纠正时降级",
        "verbatim_excerpt": verbatim,
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "source_author": "user",
        "source_role": "user",
        "input_source": candidate.get("input_source", ""),
        "source_exp_id": candidate["record"].get("exp_id", ""),
        "confidence": max(0.0, min(float(parsed.get("confidence") or 0.0), 1.0)),
        "distill_meta": {
            "source_mode": ZHIYI_MODEL_SOURCE_MODE,
            "model_distill_status": "relaxed_insufficient_evidence" if relaxed_user_evidence else "refined",
            "acceptance_policy": "coverage_first_relaxed_threshold" if relaxed_user_evidence else "strict_refined",
            "supporting_refs": refs,
            "intent": candidate.get("intent", {}),
            "read_only_raw": True,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
        },
    }
    return True, "ok", card


def _write_candidate(card: dict[str, Any], output_root: str | Path) -> Path:
    out_dir = Path(output_root).expanduser() / "candidates"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{card['candidate_id']}.json"
    path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _owner_sample_cards_from_artifact(path: str | Path) -> list[dict[str, Any]]:
    artifact_path = Path(path).expanduser()
    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    samples = data.get("owner_sample") or data.get("owner_samples") or []
    if not isinstance(samples, list):
        return []
    return [dict(item) for item in samples if isinstance(item, dict)]


def _refine_card_offsets(card: dict[str, Any]) -> dict[str, Any]:
    """Use the exact verbatim evidence ref for the card-level source handle.

    Older dry-run artifacts may keep a wider user-message span in source_refs
    while evidence_refs[0] points at the exact verbatim sentence. Catalog source
    handles should use the exact span without touching raw.
    """
    result = dict(card)
    evidence_refs = result.get("evidence_refs") if isinstance(result.get("evidence_refs"), list) else []
    exact_ref = next(
        (
            dict(item)
            for item in evidence_refs
            if isinstance(item, dict)
            and item.get("source_path")
            and isinstance(item.get("byte_offsets"), dict)
        ),
        {},
    )
    if exact_ref:
        refs = dict(result.get("source_refs") or {})
        if refs.get("source_path") == exact_ref.get("source_path"):
            refs["byte_offsets"] = exact_ref["byte_offsets"]
            result["source_refs"] = refs
    return result


def validate_accepted_owner_sample_card(card: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    if not isinstance(card, dict):
        return False, "not_object", {}
    if card.get("candidate_type") != "zhiyi_preference_card":
        return False, "not_zhiyi_preference_card", {}
    if card.get("library_shelf") != "zhiyi" or card.get("type") != "preference_memory":
        return False, "not_zhiyi_preference", {}
    if card.get("source_mode") != ZHIYI_MODEL_SOURCE_MODE:
        return False, "not_model_distill", {}
    if str(card.get("source_author") or "").lower() != "user" or str(card.get("source_role") or "").lower() != "user":
        return False, "source_role_not_user", {}
    for key in ("candidate_id", "title", "preference_statement", "when_to_use", "verbatim_excerpt"):
        if not _clean(card.get(key), limit=1000):
            return False, f"missing_{key}", {}
    refined = _refine_card_offsets(card)
    refs = refined.get("source_refs") if isinstance(refined.get("source_refs"), dict) else {}
    source_path = str(refs.get("source_path") or "").strip()
    offsets = refs.get("byte_offsets") if isinstance(refs.get("byte_offsets"), dict) else {}
    if not source_path:
        return False, "missing_source_path", {}
    if offsets.get("start") is None or offsets.get("end") is None:
        return False, "missing_byte_offsets", {}
    raw_offsets = _verbatim_offsets(
        str(refined.get("verbatim_excerpt") or ""),
        source_path,
        range_start=int(offsets.get("start") or 0),
        range_end=int(offsets.get("end") or 0),
    )
    if not raw_offsets:
        return False, "verbatim_byte_offset_not_found", {}
    refs["byte_offsets"] = raw_offsets
    refined["source_refs"] = refs
    evidence_refs = refined.get("evidence_refs") if isinstance(refined.get("evidence_refs"), list) else []
    if evidence_refs and isinstance(evidence_refs[0], dict) and evidence_refs[0].get("source_path") == source_path:
        evidence_refs = [dict(evidence_refs[0], byte_offsets=raw_offsets), *evidence_refs[1:]]
        refined["evidence_refs"] = evidence_refs
    meta = dict(refined.get("distill_meta") or {})
    meta["owner_decision"] = _ACCEPTED_OWNER_SAMPLE_DECISION
    meta["owner_decision_at"] = "2026-07-01"
    meta["read_only_raw"] = True
    meta["raw_write_performed"] = False
    meta["zhiyi_candidate_write_performed"] = True
    refined["distill_meta"] = meta
    refined["lifecycle_status"] = refined.get("lifecycle_status") or "active"
    return True, "ok", refined


def write_accepted_owner_samples(
    artifact_paths: list[str | Path],
    output_root: str | Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": True,
        "contract": ZHIYI_DISTILL_CONTRACT,
        "created_at": _now(),
        "operation": "write_accepted_owner_samples",
        "dry_run": dry_run,
        "read_only_raw": True,
        "raw_write_performed": False,
        "zhiyi_runtime_write_performed": False,
        "output_root": str(Path(output_root).expanduser()),
        "artifact_paths": [str(Path(path).expanduser()) for path in artifact_paths],
        "input_cards": 0,
        "written_candidate_files": 0,
        "rejected": 0,
        "reject_reasons": {},
        "written_files": [],
        "cards": [],
        "nonclaims": [
            "writes_candidate_files_only_not_raw",
            "does_not_write_legacy_zhiyi_runtime_jsonl",
            "owner_acceptance_does_not_replace_byte_offset_validation",
        ],
    }
    seen: set[str] = set()
    for artifact in artifact_paths:
        for card in _owner_sample_cards_from_artifact(artifact):
            report["input_cards"] += 1
            cid = str(card.get("candidate_id") or "").strip()
            if cid in seen:
                continue
            seen.add(cid)
            valid, reason, refined = validate_accepted_owner_sample_card(card)
            if not valid:
                report["rejected"] += 1
                report["reject_reasons"][reason] = report["reject_reasons"].get(reason, 0) + 1
                continue
            report["cards"].append(refined)
            if not dry_run:
                path = _write_candidate(refined, output_root)
                report["written_candidate_files"] += 1
                report["written_files"].append(str(path))
    return report


def _write_quarantine(record: dict[str, Any], reason: str, output_root: str | Path) -> Path:
    out_dir = Path(output_root).expanduser() / "quarantined"
    out_dir.mkdir(parents=True, exist_ok=True)
    exp_id = _clean(record.get("exp_id"), limit=80) or hashlib.sha256(json.dumps(record, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    path = out_dir / f"{exp_id}.json"
    payload = {
        "quarantined_at": _now(),
        "reason": reason,
        "source_exp_id": record.get("exp_id", ""),
        "source_record": record,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def quarantine_preference_dump(
    root: str | Path,
    *,
    execute: bool = False,
    reason: str = "mislabeled_preference_dump_ai_or_relay_voice",
) -> dict[str, Any]:
    """Move legacy active preference dump records into a quarantine archive.

    The legacy JSONL path is an active runtime input for older recall paths.
    Quarantine preserves every source byte in `quarantined/` and leaves an empty
    active JSONL so future valid appends can continue without resurrecting the
    bad dump.
    """

    root_path = Path(root).expanduser()
    active_path = root_path / "zhiyi" / "preference_memory" / "preference_memory.jsonl"
    report: dict[str, Any] = {
        "ok": True,
        "contract": ZHIYI_DISTILL_CONTRACT,
        "created_at": _now(),
        "operation": "quarantine_preference_dump",
        "execute": execute,
        "reason": reason,
        "active_path": str(active_path),
        "active_exists": active_path.exists(),
        "records_seen": 0,
        "records_quarantined": 0,
        "active_file_emptied": False,
        "raw_write_performed": False,
        "zhiyi_candidate_write_performed": False,
        "zhiyi_runtime_write_performed": False,
        "quarantine_path": "",
        "manifest_path": "",
        "source_sha256": "",
        "nonclaims": [
            "quarantines_legacy_dump_only",
            "does_not_delete_records",
            "does_not_write_raw_or_candidate_cards",
            "does_not_validate_future_preference_extracts",
        ],
    }
    if not active_path.exists():
        report["ok"] = False
        report["error"] = "active_preference_dump_missing"
        return report
    data = active_path.read_bytes()
    records: list[dict[str, Any]] = []
    for line in data.decode("utf-8", errors="ignore").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    digest = hashlib.sha256(data).hexdigest()
    report["records_seen"] = len(records)
    report["source_sha256"] = digest
    if not execute:
        return report

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    q_dir = active_path.parent / "quarantined"
    q_dir.mkdir(parents=True, exist_ok=True)
    quarantine_path = q_dir / f"preference_memory_quarantined_{stamp}_{digest[:12]}.jsonl"
    manifest_path = q_dir / f"preference_memory_quarantine_manifest_{stamp}_{digest[:12]}.json"
    shutil.copy2(active_path, quarantine_path)
    manifest = {
        "contract": ZHIYI_DISTILL_CONTRACT,
        "created_at": _now(),
        "reason": reason,
        "source_path": str(active_path),
        "quarantine_path": str(quarantine_path),
        "source_sha256": digest,
        "records_quarantined": len(records),
        "exp_ids": [_clean(record.get("exp_id"), limit=120) for record in records],
        "preserve_source_bytes": True,
        "active_file_emptied": True,
        "raw_write_performed": False,
        "zhiyi_candidate_write_performed": False,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    active_path.write_text("", encoding="utf-8")
    report.update(
        {
            "records_quarantined": len(records),
            "active_file_emptied": True,
            "zhiyi_runtime_write_performed": True,
            "quarantine_path": str(quarantine_path),
            "manifest_path": str(manifest_path),
        }
    )
    return report


def run_pipeline(
    root: str | Path,
    *,
    input_source: str = INPUT_SOURCE_PREFERENCE_MEMORY,
    dry_run: bool = True,
    sample: int = 0,
    raw_scan_limit: int = 5000,
    records_db: str | Path = "",
    raw_source_system: str = "",
    raw_session_id: str = "",
    raw_query: str = "",
    model_distill: bool = False,
    model_distill_limit: int = 0,
    model_retry_non_json: int = 0,
    quarantine_bad: bool = False,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root).expanduser()
    output_path = Path(output_root).expanduser() if output_root else root_path / DEFAULT_OUTPUT_REL
    if input_source == INPUT_SOURCE_RAW_USER:
        records = load_raw_user_records(
            root_path,
            limit=sample,
            scan_limit=raw_scan_limit,
            records_db=records_db,
            source_system=raw_source_system,
            session_id=raw_session_id,
            raw_query=raw_query,
        )
    else:
        records = load_preference_records(root_path, limit=sample)
    selected, reject_reasons = s0_select_preference_candidates(records, root=root_path)
    config = _model_config_dict()
    report: dict[str, Any] = {
        "ok": True,
        "contract": ZHIYI_DISTILL_CONTRACT,
        "created_at": _now(),
        "dry_run": dry_run,
        "read_only_raw": True,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "input_source": input_source,
        "records_db": str(Path(records_db).expanduser()) if records_db else str(_records_db_path(root_path)),
        "raw_scan_limit": raw_scan_limit if input_source == INPUT_SOURCE_RAW_USER else 0,
        "raw_source_system": raw_source_system,
        "raw_session_id": raw_session_id,
        "raw_query": raw_query,
        "model_distill_enabled": model_distill,
        "model_retry_non_json": model_retry_non_json,
        "input_records": len(records),
        "output_root": str(output_path),
        "steps": {
            "S0_select": {
                "selected": len(selected),
                "rejected": sum(reject_reasons.values()),
                "reject_reasons": reject_reasons,
            },
            "S2_model_distill": {
                "attempted": 0,
                "refined": 0,
                "failed": 0,
                "skipped": 0,
                "api_key_ready": _api_key_ready(config),
                "transparency_failures": 0,
                "transparency_errors": [],
                "transparency_warnings": [],
            },
            "S3_validate": {"passed": 0, "failed": 0, "fail_reasons": {}},
            "S5_write": {"written_candidate_files": 0, "quarantined_files": 0},
        },
        "owner_sample": [],
        "nonclaims": [
            "default_dry_run_does_not_write_zhiyi_runtime",
            "tests_must_mock_model_calls",
            "installed_runtime_not_signed",
            "owner_quality_not_signed_until_human_spot_check",
        ],
    }
    if not model_distill:
        report["steps"]["S2_model_distill"]["skipped"] = len(selected)
        return report
    if not _api_key_ready(config):
        report["steps"]["S2_model_distill"]["skipped"] = len(selected)
        report["steps"]["S2_model_distill"]["skip_reason"] = "no_api_key"
        return report

    limit = model_distill_limit if model_distill_limit > 0 else len(selected)
    for candidate in selected[:limit]:
        report["steps"]["S2_model_distill"]["attempted"] += 1
        valid = False
        reason = "non_json_model_response"
        card: dict[str, Any] = {}
        attempts = 1 + max(0, int(model_retry_non_json or 0))
        for attempt_index in range(attempts):
            response = _http_chat_completion_with_config(_build_prompt(candidate), config)
            if isinstance(response, dict) and response.get("transparency_recorded") is False:
                transparency_step = report["steps"]["S2_model_distill"]
                transparency_step["transparency_failures"] += 1
                transparency_step["transparency_errors"].append(
                    str(response.get("transparency_error") or "transparency_ledger_write_failed")[:300]
                )
                transparency_step["transparency_warnings"].append(
                    "model_call_succeeded_but_transparency_ledger_write_failed"
                    if response.get("ok") is not False
                    else "model_call_failed_and_transparency_ledger_write_failed"
                )
            if isinstance(response, dict) and response.get("ok") is False and "content" not in response:
                reason = str(response.get("error") or "model_error")
                break
            parsed = _extract_json(response.get("content") if isinstance(response, dict) else response)
            valid, reason, card = _validate_card(parsed, candidate)
            if valid or reason != "non_json_model_response" or attempt_index >= attempts - 1:
                break
        if reason != "non_json_model_response" and not valid and isinstance(locals().get("response"), dict) and response.get("ok") is False and "content" not in response:
            report["steps"]["S2_model_distill"]["failed"] += 1
        if not valid:
            report["steps"]["S3_validate"]["failed"] += 1
            report["steps"]["S3_validate"]["fail_reasons"][reason] = report["steps"]["S3_validate"]["fail_reasons"].get(reason, 0) + 1
            if quarantine_bad and not dry_run:
                _write_quarantine(candidate["record"], reason, output_path)
                report["steps"]["S5_write"]["quarantined_files"] += 1
            continue
        report["steps"]["S2_model_distill"]["refined"] += 1
        report["steps"]["S3_validate"]["passed"] += 1
        report["owner_sample"].append(card)
        if not dry_run:
            _write_candidate(card, output_path)
            report["steps"]["S5_write"]["written_candidate_files"] += 1
    if len(selected) > limit:
        report["steps"]["S2_model_distill"]["skipped"] += len(selected) - limit
    if report["steps"]["S2_model_distill"]["transparency_failures"]:
        warnings = list(dict.fromkeys(report["steps"]["S2_model_distill"]["transparency_warnings"]))
        report["transparency_warnings"] = warnings
        report["transparency_warning"] = warnings[0]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S0→S5 Zhiyi preference distillation")
    parser.add_argument("--root", default=os.environ.get("MEMCORE_ROOT", "."))
    parser.add_argument("--output-root", default="")
    parser.add_argument(
        "--accepted-owner-sample-artifact",
        action="append",
        default=[],
        help="Import owner-accepted dry-run owner_sample cards and write them as candidates when --write is set",
    )
    parser.add_argument(
        "--input-source",
        choices=[INPUT_SOURCE_PREFERENCE_MEMORY, INPUT_SOURCE_RAW_USER],
        default=INPUT_SOURCE_PREFERENCE_MEMORY,
        help="preference_memory screens old dump records; raw_user extracts user-authored raw turns",
    )
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--raw-scan-limit", type=int, default=5000)
    parser.add_argument("--records-db", default="")
    parser.add_argument("--raw-source-system", default="")
    parser.add_argument("--raw-session-id", default="")
    parser.add_argument("--raw-query", default="", help="Only consider raw user turns containing this exact text")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--write", action="store_true", help="Write candidates under output root")
    parser.add_argument("--model-distill", action="store_true")
    parser.add_argument("--model-distill-limit", type=int, default=0)
    parser.add_argument("--model-retry-non-json", type=int, default=0)
    parser.add_argument("--quarantine-bad", action="store_true")
    parser.add_argument(
        "--quarantine-preference-dump",
        action="store_true",
        help="Quarantine legacy zhiyi/preference_memory/preference_memory.jsonl records without deleting them",
    )
    parser.add_argument("--quarantine-execute", action="store_true", help="Execute quarantine; default is dry-run")
    args = parser.parse_args(argv)
    dry_run = True
    if args.write:
        dry_run = False
    if args.dry_run:
        dry_run = True
    if args.accepted_owner_sample_artifact:
        report = write_accepted_owner_samples(
            args.accepted_owner_sample_artifact,
            args.output_root or (Path(args.root).expanduser() / DEFAULT_OUTPUT_REL),
            dry_run=dry_run,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ok") else 1
    if args.quarantine_preference_dump:
        report = quarantine_preference_dump(args.root, execute=args.quarantine_execute)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report.get("ok") else 1
    report = run_pipeline(
        args.root,
        input_source=args.input_source,
        dry_run=dry_run,
        sample=args.sample,
        raw_scan_limit=args.raw_scan_limit,
        records_db=args.records_db,
        raw_source_system=args.raw_source_system,
        raw_session_id=args.raw_session_id,
        raw_query=args.raw_query,
        model_distill=args.model_distill,
        model_distill_limit=args.model_distill_limit,
        model_retry_non_json=args.model_retry_non_json,
        quarantine_bad=args.quarantine_bad,
        output_root=args.output_root or None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
