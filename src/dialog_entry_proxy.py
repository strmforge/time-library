"""
dialog_entry_proxy.py
P9-System-F F3/F4/F5: 对话入口代理（http.server版）
P9-System-G G5: Feature Flag 体系

架构：
用户 → entry_proxy(:9860) → 意图判断 → 知意直答/知意注入/直接放行

Feature Flag 控制：
- zhiyi_direct: F3 知意直答开关
- zhiyi_inject: F4 知意注入开关
- openclaw_rpc: OpenClaw WS RPC 转发开关
- passthrough: F5 放行开关
- audit_log: 审计日志开关
"""

import json
import uuid
import time
import os
import datetime
import hashlib
import re
import shutil
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
import urllib.request

from dialog_intent_router import classify_intent, level_to_label, level_to_action
from openclaw_ws_rpc_client import OpenClawWsRpcClient, ADMIN_OPERATOR_SCOPES
from openclaw_routing_resolver import resolve as routing_resolve, ACTION_REJECT
from config_loader import get as config_get, get_memcore_root, memory_root, node_id

ZHIYI_GATEWAY_URL = "http://127.0.0.1:9840/inject"
ZHIYI_GATEWAY_TIMEOUT = 10
FLAG_CONFIG_PATH = os.path.join(get_memcore_root(), "config", "feature_flags.json")
AUDIT_LOG_PATH = os.path.join(get_memcore_root(), "logs", "audit.jsonl")
ZHIYI_USAGE_LOG_PATH = os.path.join(get_memcore_root(), "logs", "zhiyi_usage.jsonl")
OPENCLAW_BEFORE_DISPATCH_HANDLED_LOG_PATH = os.path.join(get_memcore_root(), "logs", "openclaw_before_dispatch_handled.jsonl")
OPENCLAW_BEFORE_DISPATCH_DEDUPE_TTL_SECONDS = 300
ZHIYI_MODEL_CALL_DEFAULT_TIMEOUT = 90
HERMES_CLI_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), ".local", "bin", "hermes"),
    os.path.join(os.path.expanduser("~"), ".hermes", "hermes-agent", "venv", "bin", "hermes"),
]

_flags = None


def load_flags() -> dict:
    global _flags
    if _flags is not None:
        return _flags
    if os.path.exists(FLAG_CONFIG_PATH):
        try:
            with open(FLAG_CONFIG_PATH, encoding="utf-8-sig") as f:
                _flags = json.load(f)
                return _flags
        except Exception:
            pass
    _flags = {"zhiyi_direct": True, "zhiyi_inject": True, "openclaw_rpc": True, "passthrough": True, "audit_log": True}
    return _flags


def save_flags(flags: dict):
    global _flags
    with open(FLAG_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(flags, f, indent=2)
    _flags = flags


def get_flags() -> dict:
    return load_flags()


def is_enabled(key: str) -> bool:
    return load_flags().get(key, True)


def _zhiyi_memory_summary(memory: dict) -> str:
    mtype = memory.get("type") or memory.get("_type") or ""
    if mtype == "yifanchen_project_status":
        injectable = str(memory.get("injectable_context") or "").strip()
        if injectable:
            return injectable
    return str(memory.get("summary") or memory.get("content") or "")


def _build_zhiyi_context(recall: dict, summary_chars: int, empty_summary: str = "") -> dict:
    """Preserve the p3/p4 memory contract while keeping legacy raw_refs usable."""
    matched = recall.get("matched_memories", [])[:3]
    summaries = []
    source_refs = []
    raw_refs = []
    for memory in matched:
        summary = _zhiyi_memory_summary(memory)
        if summary:
            summaries.append(summary[:summary_chars])

        refs = memory.get("source_refs")
        if refs:
            refs = refs if isinstance(refs, list) else [refs]
            source_refs.extend(refs)
            for ref in refs:
                if isinstance(ref, dict) and ref.get("source_path"):
                    raw_refs.append(ref["source_path"])

        legacy_raw_ref = memory.get("raw_ref")
        if legacy_raw_ref and legacy_raw_ref not in raw_refs:
            raw_refs.append(legacy_raw_ref)

    return {
        "summary": "\n".join(summaries) if summaries else empty_summary,
        "source_refs": source_refs,
        "raw_refs": raw_refs,
        "matched_count": recall.get("total_matched", 0),
        "matched_memories": matched,
    }


def audit_log(entry: dict):
    if not is_enabled("audit_log"):
        return
    record = dict(entry)
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _usage_ref_count(value) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return 1 if value else 0
    if isinstance(value, str) and value.strip():
        return 1
    return 0


def _usage_evidence_items(zhiyi_context: dict) -> list:
    items = []
    memories = zhiyi_context.get("matched_memories", []) if isinstance(zhiyi_context, dict) else []
    if not isinstance(memories, list):
        return items
    for memory in memories[:5]:
        if not isinstance(memory, dict):
            continue
        refs = memory.get("source_refs", {})
        raw_ref = memory.get("raw_ref", "")
        if not raw_ref and isinstance(refs, dict):
            raw_ref = refs.get("source_path", "")
        items.append({
            "exp_id": memory.get("exp_id", "") or memory.get("id", ""),
            "type": memory.get("type", "") or memory.get("_type", ""),
            "confidence": memory.get("confidence", 0),
            "should_inject": bool(memory.get("should_inject", False)),
            "source_refs": refs,
            "source_refs_count": _usage_ref_count(refs),
            "raw_ref": raw_ref,
        })
    return items


def _truthy(value) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on", "confirmed", "confirm")
    return False


def _safe_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def _first_text(*values) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _resolve_hermes_cli(explicit_path: str = "") -> str:
    candidates = []
    if explicit_path:
        candidates.append(explicit_path)
    env_path = os.environ.get("MEMCORE_HERMES_CLI") or os.environ.get("HERMES_CLI")
    if env_path:
        candidates.append(env_path)
    which = shutil.which("hermes")
    if which:
        candidates.append(which)
    candidates.extend(HERMES_CLI_CANDIDATES)
    for candidate in candidates:
        if candidate and os.path.exists(os.path.expanduser(candidate)):
            return os.path.expanduser(candidate)
    return ""


def _model_call_request(body: dict) -> dict:
    body = body or {}
    cfg = body.get("model_call", {})
    if not isinstance(cfg, dict):
        cfg = {}
    configured = config_get("integrations.hermes.model_call", {})
    if not isinstance(configured, dict):
        configured = {}
    enabled = _truthy(cfg.get("enabled")) or _truthy(body.get("enable_model_call"))
    provider = str(cfg.get("provider") or body.get("model_provider") or "hermes_cli").strip().lower()
    return {
        "enabled": enabled,
        "provider": provider,
        "confirm_live_model_call": _truthy(cfg.get("confirm_live_model_call") or body.get("confirm_live_model_call")),
        "timeout_seconds": _safe_int(cfg.get("timeout_seconds", body.get("model_call_timeout", ZHIYI_MODEL_CALL_DEFAULT_TIMEOUT)), ZHIYI_MODEL_CALL_DEFAULT_TIMEOUT, 5, 180),
        "hermes_cli": str(cfg.get("hermes_cli") or body.get("hermes_cli") or ""),
        "hermes_provider": _first_text(
            cfg.get("hermes_provider"),
            cfg.get("hermesProvider"),
            body.get("hermes_provider"),
            body.get("hermesProvider"),
            os.environ.get("MEMCORE_HERMES_PROVIDER"),
            configured.get("hermes_provider"),
            configured.get("provider"),
        ),
        "hermes_model": _first_text(
            cfg.get("hermes_model"),
            cfg.get("hermesModel"),
            body.get("hermes_model"),
            body.get("hermesModel"),
            os.environ.get("MEMCORE_HERMES_MODEL"),
            configured.get("hermes_model"),
            configured.get("model"),
        ),
        "hermes_source": _first_text(
            cfg.get("hermes_source"),
            body.get("hermes_source"),
            os.environ.get("MEMCORE_HERMES_SOURCE"),
            configured.get("source"),
            "memcore-yifanchen",
        ),
        "max_context_chars": _safe_int(cfg.get("max_context_chars", 1800), 1800, 200, 6000),
    }


def _build_zhiyi_model_prompt(message: str, result: dict, max_context_chars: int = 1800) -> str:
    zhiyi_context = result.get("zhiyi_context", {}) if isinstance(result, dict) else {}
    summary = ""
    if isinstance(zhiyi_context, dict):
        summary = str(zhiyi_context.get("summary") or "")
    summary = summary[:max_context_chars]
    direct_answer = str(result.get("answer") or "").strip() if isinstance(result, dict) else ""
    direct_answer = direct_answer[:max_context_chars]
    source_refs = result.get("source_refs", []) if isinstance(result, dict) else []
    if not isinstance(source_refs, list):
        source_refs = [source_refs] if source_refs else []
    refs_preview = json.dumps(source_refs[:3], ensure_ascii=False)[:1200]
    runtime_context = result.get("runtime_delivery_context", {}) if isinstance(result, dict) else {}
    runtime_prompt = ""
    if isinstance(runtime_context, dict) and runtime_context:
        fields = []
        for key in ("source", "route", "delivery_method", "platform", "session_key", "channel"):
            value = runtime_context.get(key)
            if value not in (None, ""):
                fields.append(f"- {key}: {value}")
        note = str(runtime_context.get("note") or "").strip()
        if note:
            fields.append(f"- note: {note}")
        if fields:
            runtime_prompt = "\n[当前接入状态]\n" + "\n".join(fields) + "\n\n"
    return (
        "你是忆凡尘的知意回答层。请基于下面本地知意上下文回答用户，"
        "不要说自己没有上下文；如果上下文不足就直说不足并继续帮助。"
        "如果[当前接入状态]存在，它是本轮真实运行事实，优先于旧记忆和 source_refs；"
        "用户询问当前链路是否接上时，用自然话直接确认，不要反向索要日志，"
        "也不要原样复述 route/status 字段。"
        "如果上下文出现 write_boundary 或 *_write=false，这表示对应层本轮按设计保持只读或沉默，"
        "不要说成未接通、未落盘、待触发写入或下一步要补写入线；"
        "也不要说后台独立工作流后续补写入链。"
        "如果用户在补写入链和验自然对话质量之间二选一，应回答先验自然对话质量。"
        "回答当前 B131/B130 断点时不要引入 K/N/J、Linux、eval 等旧阶段标签。\n\n"
        f"[用户问题]\n{message}\n\n"
        f"{runtime_prompt}"
        f"[知意上下文]\n{summary or '（无相关记忆）'}\n\n"
        f"[知意直答草案]\n{direct_answer or '（无）'}\n\n"
        f"[source_refs]\n{refs_preview}\n\n"
        "请用中文给出一段自然、简洁、可继续工作的回答。"
    )


def _clean_zhiyi_model_answer(text: str) -> str:
    lines = []
    for line in str(text or "").splitlines():
        if "Reached maximum iterations" in line and "Requesting summary" in line:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _compact_zhiyi_fallback_context(text: str, max_chars: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return ""
    cut = len(text)
    for sep in ("。", "！", "？"):
        pos = text.find(sep)
        if 0 <= pos < cut:
            cut = pos + len(sep)
    text = text[:cut].strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip("，,；;：:。") + "。"


def _zhiyi_direct_fallback_after_model_no_answer(message: str, result: dict, model_call: dict) -> str:
    message_text = str(message or "")
    message_lower = message_text.lower()
    completion_question = any(k in message_text for k in ("完成", "学会", "整体", "最终", "pass")) or any(
        k in message_lower for k in ("done", "finish", "passed")
    )
    if completion_question:
        return (
            "不能。现在只能说忆凡尘能接住当前状态和已采用的经验，但还不能写完成；"
            "write=false 是边界，不是后面要补写入链。下一步继续压 OpenClaw/Hermes 的自然话术和真实消费闭环。"
        )

    next_step_question = any(k in message_text for k in ("下一步", "现在", "当前", "接着", "继续", "做什么", "该做"))
    if next_step_question:
        return (
            "现在要收的是更真实工作场景里的自然话术质量：看 OpenClaw/Hermes 在不提示工程关键词时，"
            "能不能接住当前忆凡尘状态、说清下一步，并继续避免把 write=false 说成待补写入链。"
        )

    zhiyi_context = result.get("zhiyi_context", {}) if isinstance(result, dict) else {}
    summary = ""
    if isinstance(zhiyi_context, dict):
        summary = str(zhiyi_context.get("summary") or "")
    draft = str((result or {}).get("answer") or "")
    context = _compact_zhiyi_fallback_context(summary or draft)
    if context:
        return f"我接到的当前状态是：{context} 这还不是完成结论；下一步继续按真实场景压自然话术和消费闭环。"
    return "我这边已经接上忆凡尘当前状态；现在先按当前状态继续推进，但还不能写完成。"


def _run_hermes_cli_for_zhiyi(message: str, result: dict, request: dict) -> dict:
    started = time.time()
    cli = _resolve_hermes_cli(request.get("hermes_cli", ""))
    base = {
        "requested": True,
        "called": False,
        "provider": "Hermes",
        "provider_id": request.get("hermes_provider") or "hermes_cli",
        "model_name": request.get("hermes_model") or "",
        "transport": "hermes_cli",
        "request_sent": False,
        "response_received": False,
        "runtime_binding_ready": True,
        "not_called_reason": "",
        "cli_path": cli,
        "exit_code": None,
        "elapsed_seconds": 0,
        "answer_chars": 0,
        "answer_excerpt": "",
        "usable_answer_received": False,
        "empty_answer": False,
        "session_id": "",
    }
    if not cli:
        base["not_called_reason"] = "hermes_cli_not_found"
        return base

    prompt = _build_zhiyi_model_prompt(
        message,
        result,
        max_context_chars=request.get("max_context_chars", 1800),
    )
    base["prompt_chars"] = len(prompt)
    cmd = [
        cli,
        "chat",
        "-q",
        prompt,
        "-Q",
        "--max-turns",
        "1",
        "--ignore-rules",
        "--source",
        request.get("hermes_source") or "memcore-yifanchen",
    ]
    if request.get("hermes_provider"):
        cmd.extend(["--provider", request["hermes_provider"]])
    if request.get("hermes_model"):
        cmd.extend(["--model", request["hermes_model"]])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=request.get("timeout_seconds", ZHIYI_MODEL_CALL_DEFAULT_TIMEOUT),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        stdout = (proc.stdout or "").strip()
        cleaned_stdout = _clean_zhiyi_model_answer(stdout)
        stderr = proc.stderr or ""
        base.update({
            "request_sent": True,
            "exit_code": proc.returncode,
            "elapsed_seconds": round(time.time() - started, 2),
            "answer_chars": len(cleaned_stdout),
            "answer_excerpt": cleaned_stdout[:800],
            "raw_answer_chars": len(stdout),
            "answer_cleaned": cleaned_stdout != stdout,
            "usable_answer_received": bool(cleaned_stdout),
            "empty_answer": proc.returncode == 0 and not bool(cleaned_stdout),
        })
        match = re.search(r"session_id:\s*([A-Za-z0-9_\-]+)", stderr)
        if match:
            base["session_id"] = match.group(1)
        if proc.returncode == 0:
            base["called"] = True
            if cleaned_stdout:
                base["response_received"] = True
                base["not_called_reason"] = ""
            else:
                base["response_received"] = False
                base["not_called_reason"] = "hermes_cli_empty_answer"
        else:
            base["not_called_reason"] = f"hermes_exit_code_{proc.returncode}"
            base["stderr_excerpt"] = stderr[:500]
    except subprocess.TimeoutExpired:
        base.update({
            "request_sent": True,
            "exit_code": -1,
            "elapsed_seconds": round(time.time() - started, 2),
            "not_called_reason": "hermes_cli_timeout",
        })
    except Exception as e:
        base.update({
            "exit_code": -2,
            "elapsed_seconds": round(time.time() - started, 2),
            "not_called_reason": f"hermes_cli_error:{e}",
        })
    return base


def maybe_run_zhiyi_live_model_call(body: dict, message: str, result: dict) -> dict:
    request = _model_call_request(body)
    if not request.get("enabled"):
        return result
    if result.get("chain") != "F3_zhiyi_direct" or result.get("status") != "ok":
        result["model_call"] = {
            "requested": True,
            "called": False,
            "runtime_binding_ready": False,
            "not_called_reason": "only_f3_zhiyi_direct_ok_can_call_model",
        }
        return result
    if request.get("provider") != "hermes_cli":
        result["model_call"] = {
            "requested": True,
            "called": False,
            "runtime_binding_ready": False,
            "not_called_reason": "unsupported_model_call_provider",
            "provider_id": request.get("provider"),
        }
        return result
    if not request.get("confirm_live_model_call"):
        result["model_call"] = {
            "requested": True,
            "called": False,
            "runtime_binding_ready": False,
            "not_called_reason": "confirm_live_model_call_required",
        }
        return result
    model_call = _run_hermes_cli_for_zhiyi(message, result, request)
    result["model_call"] = model_call
    if model_call.get("called") and model_call.get("answer_excerpt"):
        result["model_answer"] = model_call["answer_excerpt"]
        result["answer_before_model_call"] = result.get("answer", "")
        result["answer"] = model_call["answer_excerpt"]
        result["answer_source"] = "hermes_cli_model_call"
    elif model_call.get("request_sent"):
        fallback_answer = _zhiyi_direct_fallback_after_model_no_answer(message, result, model_call)
        if fallback_answer:
            result["answer_before_model_call"] = result.get("answer", "")
            result["answer"] = fallback_answer
            result["answer_source"] = "zhiyi_direct_natural_fallback_after_model_no_answer"
            result["model_fallback_applied"] = True
            model_call["fallback_applied"] = True
    return result


def _dict_value(value) -> dict:
    return value if isinstance(value, dict) else {}


def _openclaw_history_text(message: dict) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content", [])
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") in ("text", "input_text"):
            parts.append(str(item.get("text", "")))
    return "\n".join(parts).strip()


def _openclaw_visible_reply_status(history_result: dict, expected_text: str = "") -> dict:
    payload = history_result.get("payload", {}) if isinstance(history_result, dict) else {}
    messages = payload.get("messages", []) if isinstance(payload, dict) else []
    if not isinstance(messages, list) or not messages:
        return {"checked": True, "visible_reply_ok": False, "reason": "chat_history_empty"}
    latest_assistant = None
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            latest_assistant = message
            break
    if not latest_assistant:
        return {"checked": True, "visible_reply_ok": False, "reason": "assistant_reply_not_found"}
    assistant_seq = 0
    meta = latest_assistant.get("__openclaw", {})
    if isinstance(meta, dict):
        try:
            assistant_seq = int(meta.get("seq") or 0)
        except Exception:
            assistant_seq = 0
    text = _openclaw_history_text(latest_assistant)
    stop_reason = str(latest_assistant.get("stopReason") or "")
    error_message = str(latest_assistant.get("errorMessage") or "")
    if stop_reason == "error" or "failed before producing content" in text:
        return {
            "checked": True,
            "visible_reply_ok": False,
            "reason": "assistant_turn_failed",
            "stop_reason": stop_reason,
            "error_message": error_message[:160],
            "assistant_text_chars": len(text),
            "assistant_seq": assistant_seq,
        }
    if not text:
        return {
            "checked": True,
            "visible_reply_ok": False,
            "reason": "assistant_reply_empty",
            "stop_reason": stop_reason,
            "error_message": error_message[:160],
            "assistant_seq": assistant_seq,
        }
    expected_text = str(expected_text or "").strip()
    if expected_text and expected_text not in text:
        return {
            "checked": True,
            "visible_reply_ok": False,
            "reason": "assistant_reply_text_mismatch",
            "stop_reason": stop_reason,
            "error_message": error_message[:160],
            "assistant_text_chars": len(text),
            "assistant_seq": assistant_seq,
        }
    return {
        "checked": True,
        "visible_reply_ok": True,
        "reason": "",
        "stop_reason": stop_reason,
        "assistant_text_chars": len(text),
        "assistant_seq": assistant_seq,
    }


def _wait_for_openclaw_visible_reply(
    client,
    session_key: str,
    before_seq: int,
    expected_text: str = "",
    wait_seconds: float = 12,
    initial_reason: str = "assistant_reply_not_observed",
) -> dict:
    visible = {
        "checked": True,
        "visible_reply_ok": False,
        "reason": initial_reason,
    }
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        history = client.chat_history(session_key, limit=8, max_chars=1000, timeout=10)
        candidate = _openclaw_visible_reply_status(history, expected_text=expected_text)
        try:
            candidate_seq = int(candidate.get("assistant_seq") or 0)
        except Exception:
            candidate_seq = 0
        if candidate_seq > before_seq:
            return candidate
        time.sleep(0.5)
    return visible


def _platform_delivery_request(body: dict, session_id: str = "") -> dict:
    """Parse the platform-native delivery request carried by /entry callers."""
    body = body or {}
    cfg = _dict_value(body.get("platform_delivery") or body.get("delivery"))
    platform = str(
        cfg.get("platform")
        or cfg.get("target")
        or body.get("target_platform")
        or body.get("source_system")
        or ""
    ).strip().lower()
    enabled = (
        _truthy(cfg.get("enabled"))
        or _truthy(cfg.get("live"))
        or _truthy(body.get("deliver_to_platform"))
        or _truthy(body.get("deliver_to_openclaw"))
    )
    session_key = str(
        cfg.get("session_key")
        or cfg.get("target_session_key")
        or body.get("openclaw_session_key")
        or body.get("target_session_key")
        or body.get("session_key")
        or ""
    ).strip()
    if not session_key and str(session_id).startswith("agent:"):
        session_key = str(session_id)
    mode = str(cfg.get("mode") or body.get("delivery_mode") or "same_chat").strip().lower()
    idempotency_key = str(
        cfg.get("idempotency_key")
        or body.get("delivery_idempotency_key")
        or ""
    ).strip()
    requested = bool(cfg or enabled or platform or session_key)
    if platform in ("", "same_chat") and (session_key.startswith("agent:") or _truthy(body.get("deliver_to_openclaw"))):
        platform = "openclaw"
    return {
        "requested": requested,
        "enabled": enabled,
        "platform": platform,
        "mode": mode,
        "session_key": session_key,
        "idempotency_key": idempotency_key,
    }


def _openclaw_message_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") in ("text", "input_text") and item.get("text"):
            parts.append(str(item["text"]))
    return "\n".join(parts).strip()


def _openclaw_native_event_request(body: dict) -> dict:
    body = body or {}
    event = body.get("event", {})
    if not isinstance(event, dict):
        event = {}
    if not event and body.get("type") == "message":
        event = body
    message = event.get("message", {})
    if not isinstance(message, dict):
        message = {}
    text = (
        str(body.get("message_text") or "").strip()
        or _openclaw_message_text(message.get("content"))
    )
    return {
        "event_id": str(event.get("id") or body.get("event_id") or "").strip(),
        "role": str(message.get("role") or body.get("role") or "").strip().lower(),
        "message": text,
        "session_key": str(body.get("session_key") or body.get("openclaw_session_key") or "").strip(),
        "source_session_id": str(
            body.get("source_session_id") or body.get("openclaw_session_id") or ""
        ).strip(),
        "agent_id": str(body.get("agent_id") or body.get("openclaw_agent_id") or "").strip(),
        "scope_filter": body.get("scope_filter", {}),
    }


def _openclaw_before_dispatch_request(body: dict) -> dict:
    body = body or {}
    message = (
        str(body.get("message") or "").strip()
        or str(body.get("content") or "").strip()
        or str(body.get("body") or "").strip()
    )
    return {
        "message": message,
        "session_key": str(body.get("session_key") or body.get("sessionKey") or body.get("session_id") or "").strip(),
        "channel": str(body.get("channel") or "").strip().lower(),
        "sender_id": str(body.get("sender_id") or body.get("senderId") or "").strip(),
        "conversation_id": str(body.get("conversation_id") or body.get("conversationId") or "").strip(),
        "scope_filter": body.get("scope_filter", {}),
        "force_zhiyi_direct": _truthy(body.get("force_zhiyi_direct") or body.get("forceZhiyiDirect")),
    }


def _openclaw_before_dispatch_signature(session_key: str, message: str) -> str:
    normalized = json.dumps({
        "session_key": str(session_key or "").strip(),
        "message": str(message or "").strip(),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def remember_openclaw_before_dispatch_handled(session_key: str, message: str, result: dict) -> dict:
    if not session_key or not message:
        return {"ok": False, "write_performed": False, "reason": "session_key_or_message_required"}
    event = {
        "ts": time.time(),
        "signature": _openclaw_before_dispatch_signature(session_key, message),
        "session_key": session_key,
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "chain": (result or {}).get("chain", ""),
        "answer_chars": len(str((result or {}).get("answer") or "")),
    }
    created = not os.path.exists(OPENCLAW_BEFORE_DISPATCH_HANDLED_LOG_PATH)
    try:
        os.makedirs(os.path.dirname(OPENCLAW_BEFORE_DISPATCH_HANDLED_LOG_PATH), exist_ok=True)
        with open(OPENCLAW_BEFORE_DISPATCH_HANDLED_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        if created:
            os.chmod(OPENCLAW_BEFORE_DISPATCH_HANDLED_LOG_PATH, 0o600)
        return {"ok": True, "write_performed": True, "path": OPENCLAW_BEFORE_DISPATCH_HANDLED_LOG_PATH}
    except Exception as exc:
        return {"ok": False, "write_performed": False, "path": OPENCLAW_BEFORE_DISPATCH_HANDLED_LOG_PATH, "error": str(exc)}


def _safe_path_segment(value: str, fallback: str = "main") -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return text.strip("._-") or fallback


def remember_openclaw_before_dispatch_raw(event: dict, result: dict) -> dict:
    message = str((event or {}).get("message") or "").strip()
    answer = str((result or {}).get("answer") or "").strip()
    session_key = str((event or {}).get("session_key") or "main").strip()
    if not message:
        return {"ok": False, "write_performed": False, "reason": "message_required"}

    node = _safe_path_segment(node_id(), "local")
    session_slug = _safe_path_segment(session_key, "main")
    raw_dir = os.path.join(memory_root(), "openclaw", node, "before_dispatch")
    raw_path = os.path.join(raw_dir, f"{session_slug}.jsonl")
    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    now_ms = int(now.timestamp() * 1000)
    event_id = uuid.uuid4().hex
    signature = _openclaw_before_dispatch_signature(session_key, message)
    user_id = f"before-dispatch-user-{event_id}"
    base_meta = {
        "source_system": "openclaw",
        "source": "openclaw_before_dispatch",
        "session_key": session_key,
        "channel": str((event or {}).get("channel") or ""),
        "sender_id": str((event or {}).get("sender_id") or ""),
        "conversation_id": str((event or {}).get("conversation_id") or ""),
        "before_dispatch_signature": signature,
        "raw_capture": "native_hook_event",
    }
    records = [
        {
            "id": user_id,
            "type": "message",
            "timestamp": now_iso,
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": message}],
                "timestamp": now_ms,
                "metadata": base_meta,
            },
        }
    ]
    if answer:
        records.append({
            "id": f"before-dispatch-assistant-{event_id}",
            "type": "message",
            "parentId": user_id,
            "timestamp": now_iso,
            "message": {
                "role": "assistant",
                "parentId": user_id,
                "content": [{"type": "text", "text": answer}],
                "timestamp": now_ms,
                "metadata": {**base_meta, "answer_source": str((result or {}).get("answer_source") or "")},
            },
        })

    try:
        os.makedirs(raw_dir, exist_ok=True)
        created = not os.path.exists(raw_path)
        with open(raw_path, "a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        if created:
            os.chmod(raw_path, 0o600)
        extract_result = {}
        try:
            from p2_extract import incremental_extract_session
            pn, cn, en = incremental_extract_session(raw_path, session_id=session_slug, window="before_dispatch")
            extract_result = {"preference_new": pn, "case_new": cn, "error_new": en}
        except Exception as exc:
            extract_result = {"error": str(exc)}
        return {
            "ok": True,
            "write_performed": True,
            "path": raw_path,
            "records": len(records),
            "p2": extract_result,
        }
    except Exception as exc:
        return {"ok": False, "write_performed": False, "path": raw_path, "error": str(exc)}


def was_openclaw_before_dispatch_handled(session_key: str, message: str, now: float = None) -> bool:
    if not session_key or not message or not os.path.exists(OPENCLAW_BEFORE_DISPATCH_HANDLED_LOG_PATH):
        return False
    now = time.time() if now is None else now
    signature = _openclaw_before_dispatch_signature(session_key, message)
    try:
        with open(OPENCLAW_BEFORE_DISPATCH_HANDLED_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if event.get("signature") != signature:
                    continue
                try:
                    age = now - float(event.get("ts", 0))
                except Exception:
                    continue
                if 0 <= age <= OPENCLAW_BEFORE_DISPATCH_DEDUPE_TTL_SECONDS:
                    return True
    except Exception:
        return False
    return False


def resolve_openclaw_event_session_key(source_session_id: str, agent_id: str = "", client_factory=None) -> dict:
    """Resolve an archived OpenClaw JSONL session id to its live WS RPC key."""
    if not source_session_id:
        return {"ok": False, "resolved": False, "reason": "source_session_id_required", "read_only": True}
    if client_factory is None:
        client_factory = OpenClawWsRpcClient
    client = client_factory()
    try:
        if not client.connect(timeout=5):
            return {"ok": False, "resolved": False, "reason": "openclaw_connect_failed", "read_only": True}
        response = client.sessions_list(timeout=5)
    finally:
        try:
            client.close()
        except Exception:
            pass
    sessions = response.get("payload", {}).get("sessions", []) if response.get("ok") else []
    matches = [s for s in sessions if s.get("sessionId") == source_session_id]
    if agent_id:
        agent_prefix = f"agent:{agent_id}:"
        matches = [s for s in matches if str(s.get("key", "")).startswith(agent_prefix)]
    if len(matches) != 1:
        return {
            "ok": False,
            "resolved": False,
            "reason": "session_key_not_unique" if matches else "session_key_not_found",
            "match_count": len(matches),
            "source_session_id": source_session_id,
            "agent_id": agent_id,
            "read_only": True,
        }
    return {
        "ok": True,
        "resolved": True,
        "session_key": matches[0].get("key", ""),
        "source_session_id": source_session_id,
        "agent_id": agent_id,
        "method": "sessions.list_sessionId_match",
        "read_only": True,
    }


def build_zhiyi_usage_log_event(message: str, result: dict, audit: dict) -> dict:
    """Build the live usage event for a Zhiyi entry request without duplicating raw bodies."""
    result = result or {}
    audit = audit or {}
    zhiyi_context = result.get("zhiyi_context", {})
    source_refs = result.get("source_refs", [])
    raw_refs = result.get("raw_refs", [])
    result_status = result.get("status", "unknown")
    recall_count = int(result.get("recall_count", 0) or 0)
    if result_status == "error":
        outcome_status = "error"
    elif result_status == "disabled":
        outcome_status = "disabled"
    elif recall_count > 0:
        outcome_status = "matched_ready"
    else:
        outcome_status = "no_match"

    model_call = result.get("model_call", {}) if isinstance(result.get("model_call"), dict) else {}
    if model_call:
        model_call_event = {
            "called": bool(model_call.get("called", False)),
            "requested": bool(model_call.get("requested", False)),
            "provider": model_call.get("provider", ""),
            "provider_id": model_call.get("provider_id", ""),
            "model_name": model_call.get("model_name", ""),
            "transport": model_call.get("transport", ""),
            "request_sent": bool(model_call.get("request_sent", False)),
            "response_received": bool(model_call.get("response_received", False)),
            "runtime_binding_ready": bool(model_call.get("runtime_binding_ready", False)),
            "not_called_reason": model_call.get("not_called_reason", ""),
            "exit_code": model_call.get("exit_code"),
            "elapsed_seconds": model_call.get("elapsed_seconds", 0),
            "answer_chars": model_call.get("answer_chars", 0),
            "answer_excerpt": model_call.get("answer_excerpt", ""),
            "usable_answer_received": bool(model_call.get("usable_answer_received", False)),
            "empty_answer": bool(model_call.get("empty_answer", False)),
            "fallback_applied": bool(model_call.get("fallback_applied", False)),
            "session_id": model_call.get("session_id", ""),
        }
    else:
        model_call_event = {
            "called": False,
            "not_called_reason": "entry_recall_only_no_live_model_call",
            "runtime_binding_ready": False,
        }
    applied_to_platform = False
    if result.get("platform_reply_returned") or result.get("openclaw_before_dispatch_returned"):
        applied_to_platform = True
    elif isinstance(result.get("openclaw"), dict):
        applied_to_platform = bool(result.get("openclaw", {}).get("ok")) and not (
            isinstance(result.get("platform_delivery"), dict)
            and result.get("platform_delivery", {}).get("visible_reply_ok") is False
        )

    return {
        "schema_version": "1.0",
        "event_type": "zhiyi_usage_record",
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "trigger": {
            "type": "dialog_entry_live",
            "query": message,
            "session_id": audit.get("session_id", ""),
            "route": result.get("chain") or audit.get("chain", ""),
        },
        "outcome": {
            "status": outcome_status,
            "result_status": result_status,
            "chain": result.get("chain") or audit.get("chain", ""),
            "level": result.get("level", audit.get("level")),
            "label": result.get("label", audit.get("label", "")),
            "used_in_answer": result_status == "ok" and result.get("chain") == "F3_zhiyi_direct",
            "applied_to_platform": applied_to_platform,
            "dry_run_only": False,
        },
        "recall": {
            "executed": result.get("chain") in ("F3_zhiyi_direct", "F4_zhiyi_inject"),
            "total_matched": recall_count,
            "matched_memories_count": int(zhiyi_context.get("matched_count", recall_count) or 0) if isinstance(zhiyi_context, dict) else recall_count,
            "source_refs_count": _usage_ref_count(source_refs),
            "raw_refs_count": _usage_ref_count(raw_refs),
            "evidence_items": _usage_evidence_items(zhiyi_context if isinstance(zhiyi_context, dict) else {}),
        },
        "model_call": model_call_event,
        "source_refs_policy": {
            "usage_log_contains_source_refs": True,
            "raw_detail_endpoint_available": True,
            "saved_user_content_preserved": True,
            "hash_only_replacement_allowed": False,
            "redaction_performed": False,
        },
    }


def append_zhiyi_usage_log_event(event: dict) -> dict:
    parent = os.path.dirname(ZHIYI_USAGE_LOG_PATH)
    created = not os.path.exists(ZHIYI_USAGE_LOG_PATH)
    try:
        os.makedirs(parent, exist_ok=True)
        with open(ZHIYI_USAGE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        if created:
            os.chmod(ZHIYI_USAGE_LOG_PATH, 0o600)
        return {
            "ok": True,
            "write_performed": True,
            "usage_log_write_performed": True,
            "path": ZHIYI_USAGE_LOG_PATH,
            "created": created,
        }
    except Exception as e:
        return {
            "ok": False,
            "write_performed": False,
            "usage_log_write_performed": False,
            "path": ZHIYI_USAGE_LOG_PATH,
            "error": str(e),
        }


def record_zhiyi_usage_log(message: str, result: dict, audit: dict) -> dict:
    chain = (result or {}).get("chain") or (audit or {}).get("chain")
    if chain not in ("F3_zhiyi_direct", "F4_zhiyi_inject"):
        return {"ok": True, "skipped": True, "reason": "not_zhiyi_chain", "usage_log_write_performed": False}
    if (result or {}).get("status") == "disabled":
        return {"ok": True, "skipped": True, "reason": "zhiyi_disabled", "usage_log_write_performed": False}
    event = build_zhiyi_usage_log_event(message, result, audit)
    info = append_zhiyi_usage_log_event(event)
    info["event_type"] = event.get("event_type")
    info["chain"] = chain
    return info


class DialogEntryHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "service": "dialog_entry_proxy", "port": 9860}).encode())
            return
        if self.path == "/flags":
            flags = get_flags()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"flags": flags}, ensure_ascii=False).encode())
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/flags":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "invalid json"}).encode())
                return
            flags = get_flags()
            changed = []
            for key in ["zhiyi_direct", "zhiyi_inject", "openclaw_rpc", "passthrough", "audit_log"]:
                if key in data:
                    flags[key] = bool(data[key])
                    changed.append(key)
            save_flags(flags)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"flags": flags, "changed": changed}, ensure_ascii=False).encode())
            return

        if self.path == "/entry/openclaw-event":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "invalid json"}).encode())
                return
            result = self.handle_openclaw_native_event(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
            return

        if self.path == "/entry/openclaw-before-dispatch":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "invalid json"}).encode())
                return
            result = self.handle_openclaw_before_dispatch(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
            return

        if self.path != "/entry":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "invalid json"}).encode())
            return

        message = data.get("message", "")
        session_id = data.get("session_id", str(uuid.uuid4()))
        scope_filter = data.get("scope_filter", {})

        level = classify_intent(message)
        action = level_to_action(level)
        label = level_to_label(level)

        audit = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "message": message[:100],
            "level": level,
            "action": action,
            "label": label,
            "session_id": session_id,
            "flags": get_flags(),
        }

        if level == 1:
            result = self.handle_memory_direct(message, scope_filter, audit)
        elif level == 2:
            result = self.handle_zhiyi_inject(message, scope_filter, audit)
        else:
            result = self.handle_pass_through(message, session_id, audit)

        result = maybe_run_zhiyi_live_model_call(data, message, result)
        result = self.maybe_deliver_platform_answer(data, message, session_id, result)
        usage_log = record_zhiyi_usage_log(message, result, audit)
        result["usage_log"] = usage_log
        audit_log({"type": "entry_request", **audit, "result_status": result.get("status"), "usage_log_write_performed": usage_log.get("usage_log_write_performed", False)})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode())

    def maybe_deliver_platform_answer(self, body: dict, message: str, session_id: str, result: dict) -> dict:
        """Send an F3 Zhiyi answer back into the caller's native chat when requested."""
        delivery = _platform_delivery_request(body, session_id)
        if not delivery.get("requested"):
            return result

        status = {
            "requested": True,
            "enabled": bool(delivery.get("enabled")),
            "platform": delivery.get("platform", ""),
            "mode": delivery.get("mode", ""),
            "target_session_key": delivery.get("session_key", ""),
            "idempotency_key": delivery.get("idempotency_key", ""),
            "executed": False,
            "delivery_type": "f3_direct_answer_to_platform_chat",
            "reason": "",
        }
        result["platform_delivery"] = status

        if not status["enabled"]:
            status["reason"] = "platform_delivery_not_enabled"
            return result
        if status["platform"] != "openclaw":
            status["reason"] = "unsupported_platform_delivery_target"
            return result
        if result.get("chain") != "F3_zhiyi_direct" or result.get("status") != "ok":
            status["reason"] = "only_f3_zhiyi_direct_ok_can_deliver_answer"
            return result
        answer = str(result.get("answer") or "").strip()
        if not answer:
            status["reason"] = "empty_zhiyi_answer"
            return result
        if not status["target_session_key"]:
            status["reason"] = "openclaw_session_key_required"
            return result

        if status["idempotency_key"]:
            forward_result = self._forward_to_openclaw(
                answer,
                status["target_session_key"],
                idempotency_key=status["idempotency_key"],
            )
        else:
            forward_result = self._forward_to_openclaw(answer, status["target_session_key"])
        status.update({
            "executed": True,
            "answer_chars": len(answer),
            "openclaw_ok": bool(forward_result.get("ok")) if isinstance(forward_result, dict) else False,
            "visible_reply_checked": bool(forward_result.get("visible_reply_checked")) if isinstance(forward_result, dict) else False,
            "visible_reply_ok": forward_result.get("visible_reply_ok") if isinstance(forward_result, dict) else None,
            "visible_reply_reason": forward_result.get("visible_reply_reason", "") if isinstance(forward_result, dict) else "",
        })
        result["openclaw"] = forward_result
        return result

    def handle_openclaw_before_dispatch(self, body: dict) -> dict:
        """Native OpenClaw pre-model hook: answer F3 in-place without provider dispatch."""
        event = _openclaw_before_dispatch_request(body)
        base = {
            "status": "skipped",
            "chain": "openclaw_before_dispatch",
            "handled": False,
            "text": "",
            "openclaw_write_performed": False,
            "passthrough_forwarded": False,
            "native_event": {
                "source_system": "openclaw",
                "session_key": event.get("session_key", ""),
                "channel": event.get("channel", ""),
                "force_zhiyi_direct": bool(event.get("force_zhiyi_direct", False)),
            },
        }
        message = event.get("message", "")
        if not message:
            base["reason"] = "empty_openclaw_before_dispatch_message"
            return base

        force_zhiyi_direct = bool(event.get("force_zhiyi_direct", False))
        level = 1 if force_zhiyi_direct else classify_intent(message)
        action = level_to_action(level)
        label = level_to_label(level)
        if level != 1:
            base.update({
                "reason": "openclaw_before_dispatch_not_f3_zhiyi_direct",
                "level": level,
                "label": label,
                "action": action,
            })
            return base

        audit = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "message": message[:100],
            "level": level,
            "action": action,
            "label": label,
            "session_id": event.get("session_key", ""),
            "flags": get_flags(),
            "source": "openclaw_before_dispatch",
            "force_zhiyi_direct": force_zhiyi_direct,
        }
        result = self.handle_memory_direct(message, event.get("scope_filter", {}), audit)
        result["runtime_delivery_context"] = {
            "source": "openclaw_before_dispatch",
            "route": "F3_zhiyi_direct",
            "delivery_method": "before_dispatch_return",
            "platform": "openclaw",
            "session_key": event.get("session_key", ""),
            "channel": event.get("channel", ""),
            "status": "model_dispatch_preempted",
            "note": "本轮 OpenClaw webchat 消息已经在 provider 模型分发前进入忆凡尘知意；可自然表述为：已经在 OpenClaw 前台无声接上知意 before_dispatch，并直接作为 final reply 展示。",
        }
        dispatch_body = dict(body or {})
        if "model_call" not in dispatch_body and "enable_model_call" not in dispatch_body:
            dispatch_body["model_call"] = {
                "enabled": True,
                "provider": "hermes_cli",
                "confirm_live_model_call": True,
            }
        result = maybe_run_zhiyi_live_model_call(dispatch_body, message, result)
        answer = str(result.get("answer") or "").strip()
        handled = result.get("status") == "ok" and result.get("chain") == "F3_zhiyi_direct" and bool(answer)
        remember_status = {}
        raw_capture = {}
        if handled:
            remember_status = remember_openclaw_before_dispatch_handled(event.get("session_key", ""), message, result)
            raw_capture = remember_openclaw_before_dispatch_raw(event, result)
        result.update({
            "handled": handled,
            "text": answer if handled else "",
            "openclaw_write_performed": False,
            "passthrough_forwarded": False,
            "openclaw_before_dispatch_returned": handled,
            "platform_reply_returned": handled,
            "platform_delivery": {
                "enabled": handled,
                "platform": "openclaw",
                "delivery_method": "before_dispatch_return",
                "visible_reply_ok": handled,
                "write_performed": False,
            },
            "native_event": base["native_event"],
            "before_dispatch_dedupe": remember_status,
            "before_dispatch_raw_capture": raw_capture,
        })
        usage_log = record_zhiyi_usage_log(message, result, audit)
        result["usage_log"] = usage_log
        audit_log({"type": "openclaw_before_dispatch", **audit, "result_status": result.get("status"), "handled": handled, "usage_log_write_performed": usage_log.get("usage_log_write_performed", False)})
        return result

    def handle_openclaw_native_event(self, body: dict) -> dict:
        """Consume an already-written OpenClaw user event without duplicating passthrough."""
        event = _openclaw_native_event_request(body)
        base = {
            "status": "skipped",
            "chain": "openclaw_native_event",
            "native_event": {
                "source_system": "openclaw",
                "event_id": event.get("event_id", ""),
                "role": event.get("role", ""),
                "source_session_id": event.get("source_session_id", ""),
                "agent_id": event.get("agent_id", ""),
            },
            "openclaw_write_performed": False,
            "passthrough_forwarded": False,
        }
        message = event.get("message", "")
        if event.get("role") != "user":
            base["reason"] = "non_user_openclaw_event"
            return base
        if not message:
            base["reason"] = "empty_openclaw_user_message"
            return base

        level = classify_intent(message)
        action = level_to_action(level)
        label = level_to_label(level)
        if level != 1:
            base.update({
                "reason": "openclaw_event_not_f3_zhiyi_direct",
                "level": level,
                "label": label,
                "action": action,
            })
            return base

        session_key = event.get("session_key", "")
        resolution = {"ok": True, "resolved": bool(session_key), "session_key": session_key}
        if not session_key:
            resolution = resolve_openclaw_event_session_key(
                event.get("source_session_id", ""),
                event.get("agent_id", ""),
            )
            session_key = resolution.get("session_key", "") if resolution.get("ok") else ""
        if not session_key:
            base.update({
                "status": "blocked",
                "reason": "openclaw_session_key_not_resolved",
                "level": level,
                "label": label,
                "action": action,
                "session_key_resolution": resolution,
            })
            return base

        if was_openclaw_before_dispatch_handled(session_key, message):
            base.update({
                "status": "skipped",
                "reason": "openclaw_before_dispatch_already_handled",
                "level": level,
                "label": label,
                "action": action,
                "native_event": {
                    **base["native_event"],
                    "consumed": True,
                },
                "session_key_resolution": resolution,
                "before_dispatch_dedupe": True,
            })
            return base

        audit = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "message": message[:100],
            "level": level,
            "action": action,
            "label": label,
            "session_id": session_key,
            "flags": get_flags(),
            "source": "openclaw_native_event",
        }
        pre_delivery_abort = self._abort_openclaw_active_run(session_key)
        result = self.handle_memory_direct(message, event.get("scope_filter", {}), audit)
        result["openclaw_pre_delivery_abort"] = pre_delivery_abort
        event_id = event.get("event_id") or uuid.uuid4().hex[:12]
        delivery_body = dict(body or {})
        if "model_call" not in delivery_body and "enable_model_call" not in delivery_body:
            delivery_body["model_call"] = {
                "enabled": True,
                "provider": "hermes_cli",
                "confirm_live_model_call": True,
            }
        delivery_body["platform_delivery"] = {
            **_dict_value(delivery_body.get("platform_delivery")),
            "enabled": True,
            "platform": "openclaw",
            "mode": "same_chat",
            "session_key": session_key,
            "idempotency_key": f"memcore-openclaw-event-{event_id}",
        }
        result = maybe_run_zhiyi_live_model_call(delivery_body, message, result)
        result = self.maybe_deliver_platform_answer(delivery_body, message, session_key, result)
        usage_log = record_zhiyi_usage_log(message, result, audit)
        result["usage_log"] = usage_log
        result["native_event"] = base["native_event"]
        result["native_event"]["consumed"] = True
        result["session_key_resolution"] = resolution
        result["passthrough_forwarded"] = False
        audit_log({"type": "openclaw_native_event", **audit, "result_status": result.get("status"), "usage_log_write_performed": usage_log.get("usage_log_write_performed", False)})
        return result

    def _abort_openclaw_active_run(self, session_key: str) -> dict:
        """End the native OpenClaw run that the user just started before injecting Zhiyi."""
        status = {
            "attempted": False,
            "ok": False,
            "aborted": False,
            "run_ids": [],
            "method": "chat.abort",
            "reason": "",
        }
        if not session_key:
            status["reason"] = "openclaw_session_key_required"
            return status
        if not is_enabled("openclaw_rpc"):
            status["reason"] = "flag openclaw_rpc=false"
            return status

        client = None
        try:
            client = OpenClawWsRpcClient(scopes=ADMIN_OPERATOR_SCOPES)
            if not client.connect(timeout=5):
                status["attempted"] = True
                status["reason"] = client.last_error or "openclaw_connect_failed"
                return status
            result = client.chat_abort(session_key=session_key, timeout=5)
            payload = result.get("payload", {}) if isinstance(result, dict) else {}
            status.update({
                "attempted": True,
                "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
                "aborted": bool(payload.get("aborted")) if isinstance(payload, dict) else False,
                "run_ids": payload.get("runIds", []) if isinstance(payload, dict) and isinstance(payload.get("runIds", []), list) else [],
                "error": result.get("error") if isinstance(result, dict) and result.get("error") else None,
            })
            if not status["ok"]:
                status["reason"] = "chat_abort_failed"
            elif not status["aborted"]:
                status["reason"] = "no_active_openclaw_run"
            return status
        except Exception as exc:
            status.update({
                "attempted": True,
                "ok": False,
                "reason": f"chat_abort_exception:{str(exc)[:120]}",
            })
            return status
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

    def handle_memory_direct(self, message: str, scope_filter: dict, audit: dict):
        """F3: 记忆查询 → 知意直答"""
        if not is_enabled("zhiyi_direct"):
            return {"status": "disabled", "chain": "F3_zhiyi_direct", "reason": "flag zhiyi_direct=false", "audit": audit}
        audit["chain"] = "F3_zhiyi_direct"
        try:
            payload = json.dumps({
                "query": message,
                "message": message,
                "mode": "summary",
                "scope_filter": scope_filter,
                "recall_mode": "substring",
            }).encode("utf-8")
            req = urllib.request.Request(
                ZHIYI_GATEWAY_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=ZHIYI_GATEWAY_TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            recall = result.get("recall_result", {})
            zhiyi_context = _build_zhiyi_context(recall, 200, "（无相关记忆）")
            return {
                "status": "ok",
                "chain": "F3_zhiyi_direct",
                "level": audit["level"],
                "label": audit["label"],
                "zhiyi_context": zhiyi_context,
                "answer": zhiyi_context["summary"],
                "source_refs": zhiyi_context["source_refs"],
                "raw_refs": zhiyi_context["raw_refs"],
                "recall_count": recall.get("total_matched", 0),
                "audit": audit,
            }
        except Exception as e:
            audit["error"] = str(e)
            return {"status": "error", "chain": "F3_zhiyi_direct", "error": str(e), "audit": audit}

    def _get_default_session_key(self) -> str:
        if not is_enabled("openclaw_rpc"):
            return None
        try:
            client = OpenClawWsRpcClient()
            if not client.connect(timeout=5):
                return None
            result = client.sessions_list(timeout=5)
            client.close()
            if result.get("ok"):
                sessions = result.get("payload", {}).get("sessions", [])
                if sessions:
                    return sessions[0]["key"]
        except Exception:
            pass
        return None

    def _forward_to_openclaw(self, message: str, session_key: str = None, idempotency_key: str = None) -> dict:
        if not is_enabled("openclaw_rpc"):
            return {"ok": False, "error": "flag openclaw_rpc=false"}

        # H4: 所有转发必须先过 routing_resolver
        route = routing_resolve(session_key)
        if route.get("action") == ACTION_REJECT:
            return {
                "ok": False,
                "error": "routing_rejected",
                "reason": route.get("reason"),
                "canonical_window_id": route.get("canonical_window_id"),
                "route_source": route.get("source"),
            }

        target_key = route.get("session_key")
        if not target_key:
            return {"ok": False, "error": "routing resolved but no session_key"}

        # H5: scope校验 - 验证 session_key 真实存在于 Gateway
        valid_sessions = self._get_valid_session_keys()
        if target_key not in valid_sessions:
            return {
                "ok": False,
                "error": "scope_verification_failed",
                "reason": f"session_key {target_key} not found in Gateway session list",
                "canonical_window_id": route.get("canonical_window_id"),
            }

        client = None
        try:
            client = OpenClawWsRpcClient(scopes=ADMIN_OPERATOR_SCOPES)
            admin_connected = client.connect(timeout=5)
            inject_connect_error = None
            if not admin_connected:
                inject_connect_error = client.last_error or "Failed to connect to OpenClaw Gateway with admin scope"
                try:
                    client.close()
                except Exception:
                    pass
                client = OpenClawWsRpcClient()
                if not client.connect(timeout=5):
                    return {
                        "ok": False,
                        "error": "Failed to connect to OpenClaw Gateway",
                        "delivery_method": "chat.inject",
                        "chat_inject_attempted": False,
                        "chat_inject_connect_ok": False,
                        "chat_inject_connect_error": inject_connect_error,
                    }
            before_seq = 0
            try:
                before = client.chat_history(target_key, limit=8, max_chars=400, timeout=10)
                before_seq = int(_openclaw_visible_reply_status(before).get("assistant_seq") or 0)
            except Exception:
                before_seq = 0

            inject_result = None
            if admin_connected:
                inject_result = client.chat_inject(
                    session_key=target_key,
                    message=message,
                    label="忆凡尘知意",
                    timeout=10,
                )
                if isinstance(inject_result, dict):
                    inject_result["delivery_method"] = "chat.inject"
                    inject_result["chat_inject_attempted"] = True
                    inject_result["chat_inject_ok"] = bool(inject_result.get("ok"))
                    inject_result["chat_inject_connect_ok"] = True
                if isinstance(inject_result, dict) and inject_result.get("ok"):
                    try:
                        visible = _wait_for_openclaw_visible_reply(
                            client,
                            target_key,
                            before_seq,
                            expected_text=message,
                            wait_seconds=12,
                            initial_reason="assistant_reply_not_observed_after_inject",
                        )
                        inject_result["visible_reply_checked"] = True
                        inject_result["visible_reply_ok"] = visible.get("visible_reply_ok", False)
                        inject_result["visible_reply_reason"] = visible.get("reason", "")
                        inject_result["visible_reply"] = visible
                    except Exception as verify_exc:
                        inject_result["visible_reply_checked"] = True
                        inject_result["visible_reply_ok"] = False
                        inject_result["visible_reply_reason"] = f"chat_history_verify_failed:{str(verify_exc)[:120]}"
                    return inject_result

            result = client.chat_send(
                session_key=target_key,
                message=message,
                idempotency_key=idempotency_key or f"f4-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"
            )
            if isinstance(result, dict):
                result["delivery_method"] = "chat.send_fallback"
                result["chat_inject_attempted"] = bool(admin_connected)
                result["chat_inject_connect_ok"] = bool(admin_connected)
                result["chat_inject_ok"] = False
                if inject_connect_error:
                    result["chat_inject_connect_error"] = inject_connect_error
                if isinstance(inject_result, dict):
                    result["chat_inject_error"] = inject_result.get("error") or inject_result
            if result.get("ok"):
                try:
                    visible = _wait_for_openclaw_visible_reply(
                        client,
                        target_key,
                        before_seq,
                        wait_seconds=45,
                        initial_reason="assistant_reply_not_observed_after_send",
                    )
                    result["visible_reply_checked"] = True
                    result["visible_reply_ok"] = visible.get("visible_reply_ok", False)
                    result["visible_reply_reason"] = visible.get("reason", "")
                    result["visible_reply"] = visible
                except Exception as verify_exc:
                    result["visible_reply_checked"] = True
                    result["visible_reply_ok"] = False
                    result["visible_reply_reason"] = f"chat_history_verify_failed:{str(verify_exc)[:120]}"
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass

    def _get_valid_session_keys(self) -> set:
        """H5: 获取Gateway中真实存在的session key集合（用于scope校验）"""
        try:
            client = OpenClawWsRpcClient()
            if not client.connect(timeout=5):
                return set()
            result = client.sessions_list(timeout=5)
            client.close()
            if result.get("ok"):
                sessions = result.get("payload", {}).get("sessions", [])
                return {s.get("key") for s in sessions}
        except Exception:
            pass
        return set()

    def handle_zhiyi_inject(self, message: str, scope_filter: dict, audit: dict):
        """F4: 复杂任务 → 知意注入上下文 → OpenClaw转发"""
        if not is_enabled("zhiyi_inject"):
            return {"status": "disabled", "chain": "F4_zhiyi_inject", "reason": "flag zhiyi_inject=false", "audit": audit}
        audit["chain"] = "F4_zhiyi_inject"
        session_key = audit.get("session_id")
        try:
            payload = json.dumps({
                "query": message,
                "message": message,
                "mode": "summary",
                "scope_filter": scope_filter,
                "recall_mode": "substring",
            }).encode("utf-8")
            req = urllib.request.Request(
                ZHIYI_GATEWAY_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=ZHIYI_GATEWAY_TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            recall = result.get("recall_result", {})
            zhiyi_context = _build_zhiyi_context(recall, 300)
            injected = f"[知意上下文]\n{zhiyi_context['summary']}\n\n[用户问题]\n{message}"
            forward_result = self._forward_to_openclaw(injected, session_key)
            return {
                "status": "ok",
                "chain": "F4_zhiyi_inject",
                "level": audit["level"],
                "label": audit["label"],
                "zhiyi_context": zhiyi_context,
                "source_refs": zhiyi_context["source_refs"],
                "raw_refs": zhiyi_context["raw_refs"],
                "injected_message": injected,
                "openclaw": forward_result,
                "audit": audit,
            }
        except Exception as e:
            audit["error"] = str(e)
            return {"status": "error", "chain": "F4_zhiyi_inject", "error": str(e), "audit": audit}

    def handle_pass_through(self, message: str, session_id: str, audit: dict):
        """F5: 普通问题 → 直接放行 → OpenClaw转发"""
        if not is_enabled("passthrough"):
            return {"status": "disabled", "chain": "F5_pass_through", "reason": "flag passthrough=false", "audit": audit}
        audit["chain"] = "F5_pass_through"
        forward_result = self._forward_to_openclaw(message, session_id)
        return {
            "status": "ok",
            "chain": "F5_pass_through",
            "level": audit["level"],
            "label": audit["label"],
            "message": message,
            "session_id": session_id,
            "openclaw": forward_result,
            "audit": audit,
        }


def run(port=9860):
    server = HTTPServer(("0.0.0.0", port), DialogEntryHandler)
    print(f"dialog_entry_proxy running on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
