"""
dialog_entry_proxy.py
Dialog entry proxy.
Feature flag support.

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
import secrets
import subprocess
import ipaddress
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
import urllib.parse
import urllib.request

try:
    from src.source_system_runtime_declarations import (
        declared_delivery_runtime_kinds,
        infer_delivery_source_system,
        source_system_delivery_enabled,
        source_system_delivery_session_key,
        source_system_delivery_session_key_from_identity,
        source_system_delivery_runtime_kind,
    )
except ImportError:
    from source_system_runtime_declarations import (
        declared_delivery_runtime_kinds,
        infer_delivery_source_system,
        source_system_delivery_enabled,
        source_system_delivery_session_key,
        source_system_delivery_session_key_from_identity,
        source_system_delivery_runtime_kind,
    )

try:
    from src.evidence_bound_model import (
        EVIDENCE_BOUND_MODEL_CONTRACT,
        default_model_config,
        plan_evidence_bound_answer_model_use,
        run_evidence_bound_answer,
    )
    from src.memory_authority_policy import decide_memory_authority
except ImportError:
    from evidence_bound_model import (
        EVIDENCE_BOUND_MODEL_CONTRACT,
        default_model_config,
        plan_evidence_bound_answer_model_use,
        run_evidence_bound_answer,
    )
    from memory_authority_policy import decide_memory_authority
from dialog_intent_router import classify_intent, level_to_label, level_to_action
from zhiyi_entry_intent import normalize_zhiyi_entry_query
from openclaw_ws_rpc_client import OpenClawWsRpcClient, ADMIN_OPERATOR_SCOPES
from openclaw_routing_resolver import resolve as routing_resolve, ACTION_REJECT
from config_loader import get as config_get, get_memcore_root, memory_root, node_id

ZHIYI_GATEWAY_URL = "http://127.0.0.1:9840/inject"
ZHIYI_GATEWAY_TIMEOUT = 10
FLAG_CONFIG_PATH = os.path.join(get_memcore_root(), "config", "feature_flags.json")
DIALOG_ENTRY_TOKEN_PATH = os.path.join(get_memcore_root(), "runtime", "dialog_entry_token")
AUDIT_LOG_PATH = os.path.join(get_memcore_root(), "logs", "audit.jsonl")
ZHIYI_USAGE_LOG_PATH = os.path.join(get_memcore_root(), "logs", "zhiyi_usage.jsonl")
OPENCLAW_BEFORE_DISPATCH_HANDLED_LOG_PATH = os.path.join(get_memcore_root(), "logs", "openclaw_before_dispatch_handled.jsonl")
OPENCLAW_BEFORE_DISPATCH_DEDUPE_TTL_SECONDS = 300
ZHIYI_MODEL_CALL_DEFAULT_TIMEOUT = 90
DEFAULT_BIND_HOST = "127.0.0.1"
ENTRY_ACTION_PATHS = {"/entry", "/entry/openclaw-event", "/entry/openclaw-before-dispatch"}
ENTRY_ACTION_HANDLERS = {
    "/entry/openclaw-event": "handle_openclaw_native_event",
    "/entry/openclaw-before-dispatch": "handle_openclaw_before_dispatch",
}
PLATFORM_DELIVERY_FORWARDERS = {
    "ws_rpc_forward": "_forward_to_openclaw",
}
PLATFORM_DELIVERY_RESULT_KEYS = {
    "ws_rpc_forward": "openclaw",
}
MANAGEMENT_PATHS = {"/flags"}
HERMES_CLI_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), ".local", "bin", "hermes"),
    os.path.join(os.path.expanduser("~"), ".hermes", "hermes-agent", "venv", "bin", "hermes"),
]

DEFAULT_FEATURE_FLAGS = {
    "zhiyi_direct": False,
    "zhiyi_inject": False,
    "openclaw_passive_auto_inject": False,
    "openclaw_rpc": False,
    "passthrough": True,
    "audit_log": True,
    "fts5_recall": False,
}

_flags = None


def _is_loopback_host(host: str) -> bool:
    raw = str(host or "").strip()
    if not raw:
        return False
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if raw.lower() == "localhost":
        return True
    try:
        parsed = ipaddress.ip_address(raw)
    except ValueError:
        return False
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped:
        return bool(mapped.is_loopback)
    return bool(parsed.is_loopback)


def _is_private_or_loopback_host(host: str) -> bool:
    raw = str(host or "").strip()
    if not raw:
        return False
    if _is_loopback_host(raw):
        return True
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    try:
        parsed = ipaddress.ip_address(raw)
    except ValueError:
        return False
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped:
        return bool(mapped.is_private or mapped.is_link_local or mapped.is_loopback)
    return bool(parsed.is_private or parsed.is_link_local or parsed.is_loopback)


def _is_loopback_client(client_address) -> bool:
    if isinstance(client_address, (list, tuple)) and client_address:
        return _is_loopback_host(str(client_address[0]))
    return _is_loopback_host(str(client_address or ""))


def _request_host_name(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw if "://" in raw else f"http://{raw}")
    return parsed.hostname or ""


def _same_origin_or_local(origin: str, host_header: str) -> bool:
    if not origin:
        return True
    origin_host = _request_host_name(origin)
    request_host = _request_host_name(host_header)
    if not origin_host:
        return False
    if _is_loopback_host(origin_host):
        return True
    return bool(request_host and origin_host.lower() == request_host.lower())


def _dialog_request_surface_allowed(client_address, headers, token_authenticated: bool = False) -> bool:
    host = str(headers.get("Host", "") if headers else "").strip()
    host_name = _request_host_name(host)
    if _is_loopback_client(client_address) and host_name and not _is_loopback_host(host_name):
        return False
    origin = str(headers.get("Origin", "") if headers else "").strip()
    if origin and not _same_origin_or_local(origin, host):
        origin_host = _request_host_name(origin)
        if (
            token_authenticated
            and _is_private_or_loopback_host(origin_host)
            and (not host_name or _is_private_or_loopback_host(host_name))
        ):
            return True
        return False
    return True


def _token_matches(provided: str, expected: str) -> bool:
    return bool(expected) and hmac_compare(str(provided or ""), str(expected))


def hmac_compare(left: str, right: str) -> bool:
    try:
        import hmac
        return hmac.compare_digest(left, right)
    except Exception:
        return left == right


def _read_dialog_entry_token_file() -> str:
    try:
        if os.path.exists(DIALOG_ENTRY_TOKEN_PATH):
            with open(DIALOG_ENTRY_TOKEN_PATH, encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        return ""
    return ""


def _write_dialog_entry_token_file(token: str) -> None:
    if not token:
        return
    try:
        os.makedirs(os.path.dirname(DIALOG_ENTRY_TOKEN_PATH), exist_ok=True)
        with open(DIALOG_ENTRY_TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(token + "\n")
        try:
            os.chmod(DIALOG_ENTRY_TOKEN_PATH, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def _ensure_dialog_entry_token_file() -> str:
    existing = _read_dialog_entry_token_file()
    if existing:
        return existing
    token = secrets.token_urlsafe(32)
    _write_dialog_entry_token_file(token)
    return token


def _dialog_entry_token() -> str:
    env_token = os.environ.get("MEMCORE_DIALOG_ENTRY_TOKEN", "").strip()
    if env_token:
        if not _read_dialog_entry_token_file():
            _write_dialog_entry_token_file(env_token)
        return env_token
    return _ensure_dialog_entry_token_file()


def _provided_token(headers) -> str:
    auth = str(headers.get("Authorization", "") if headers else "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return str(headers.get("X-Memcore-Dialog-Token", "") if headers else "").strip()


def _entry_request_allowed(path: str, client_address, headers) -> bool:
    if path not in ENTRY_ACTION_PATHS:
        return False
    if _is_loopback_client(client_address):
        if not _dialog_request_surface_allowed(client_address, headers):
            return False
        return True
    token_ok = _token_matches(_provided_token(headers), _dialog_entry_token())
    if not token_ok:
        return False
    return _dialog_request_surface_allowed(client_address, headers, token_authenticated=True)


def _management_request_allowed(client_address, headers=None) -> bool:
    return _is_loopback_client(client_address) and _dialog_request_surface_allowed(client_address, headers)


def load_flags() -> dict:
    global _flags
    if _flags is not None:
        return _flags
    if os.path.exists(FLAG_CONFIG_PATH):
        try:
            with open(FLAG_CONFIG_PATH, encoding="utf-8-sig") as f:
                loaded = json.load(f)
                _flags = dict(DEFAULT_FEATURE_FLAGS)
                if isinstance(loaded, dict):
                    _flags.update(loaded)
                return _flags
        except Exception:
            pass
    _flags = dict(DEFAULT_FEATURE_FLAGS)
    return _flags


def save_flags(flags: dict):
    global _flags
    with open(FLAG_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(flags, f, indent=2)
    _flags = flags


def get_flags() -> dict:
    return load_flags()


def is_enabled(key: str) -> bool:
    return bool(load_flags().get(key, DEFAULT_FEATURE_FLAGS.get(key, False)))


def _zhiyi_memory_summary(memory: dict) -> str:
    mtype = memory.get("type") or memory.get("_type") or ""
    if mtype == "time_library_project_status":
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
            "memcore-time_library",
        ),
        "model": _first_text(
            cfg.get("model"),
            cfg.get("model_name"),
            body.get("model"),
            body.get("model_name"),
            os.environ.get("MEMCORE_ZHIYI_MODEL"),
        ),
        "base_url": _first_text(
            cfg.get("base_url"),
            cfg.get("baseUrl"),
            body.get("base_url"),
            body.get("baseUrl"),
            os.environ.get("MEMCORE_ZHIYI_BASE_URL"),
        ),
        "provider_hint": _first_text(
            cfg.get("provider_hint"),
            body.get("provider_hint"),
            provider,
        ),
        "call_policy": _first_text(
            cfg.get("call_policy"),
            cfg.get("model_call_policy"),
            body.get("answer_model_call_policy"),
            body.get("model_call_policy"),
            "always",
        ).strip().lower(),
        "debug": _truthy(
            cfg.get("debug")
            or cfg.get("answer_debug")
            or body.get("answer_debug")
            or body.get("debug_answer")
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
        "你是Time Library的知意回答层。请基于下面本地知意上下文回答用户，"
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
    return ""


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
        request.get("hermes_source") or "memcore-time_library",
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


def _zhiyi_context_to_model_evidence(result: dict, max_items: int = 5) -> list:
    zhiyi_context = result.get("zhiyi_context", {}) if isinstance(result, dict) else {}
    memories = zhiyi_context.get("matched_memories", []) if isinstance(zhiyi_context, dict) else []
    evidence = []
    for index, memory in enumerate(memories if isinstance(memories, list) else []):
        if not isinstance(memory, dict):
            continue
        text = _zhiyi_memory_summary(memory)
        if not text:
            text = str(memory.get("detail") or memory.get("content") or "")
        if not text.strip():
            continue
        refs = memory.get("source_refs", {})
        evidence_ref = str(memory.get("exp_id") or memory.get("id") or memory.get("raw_ref") or f"zhiyi_memory_{index + 1}")
        source_id = evidence_ref
        if isinstance(refs, dict):
            source_id = str(refs.get("library_id") or refs.get("catalog_id") or refs.get("source_id") or evidence_ref)
        evidence.append(
            {
                "source_id": source_id,
                "evidence_ref": evidence_ref,
                "role": str(memory.get("role") or ""),
                "timestamp": str(memory.get("created_at") or memory.get("extracted_at") or ""),
                "text": text,
                "source_refs": refs,
                "score": memory.get("score") or memory.get("confidence"),
            }
        )
        if len(evidence) >= max_items:
            break
    if evidence:
        return evidence
    summary = ""
    if isinstance(zhiyi_context, dict):
        summary = str(zhiyi_context.get("summary") or "")
    if summary.strip():
        return [
            {
                "source_id": "zhiyi_context_summary",
                "evidence_ref": "zhiyi_context_summary",
                "role": "summary",
                "text": summary,
                "source_refs": result.get("source_refs", []),
            }
        ]
    return []


def _debug_evidence_items(evidence: list) -> list:
    output = []
    for item in evidence[:5]:
        if not isinstance(item, dict):
            continue
        output.append(
            {
                "source_id": item.get("source_id", ""),
                "evidence_ref": item.get("evidence_ref", ""),
                "role": item.get("role", ""),
                "timestamp": item.get("timestamp", ""),
                "score": item.get("score"),
                "text_excerpt": str(item.get("text") or "")[:360],
                "source_refs": item.get("source_refs") if isinstance(item.get("source_refs"), (dict, list)) else {},
                "source_refs_present": bool(item.get("source_refs")),
            }
        )
    return output


def _evidence_packet_refs(evidence: list) -> list:
    refs = []
    seen = set()
    items = evidence if isinstance(evidence, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("evidence_ref") or item.get("source_id") or "").strip()
        if ref and ref not in seen:
            refs.append(ref)
            seen.add(ref)
    return refs


def _answer_debug_requested(body: dict) -> bool:
    body = body or {}
    cfg = body.get("model_call", {})
    if not isinstance(cfg, dict):
        cfg = {}
    return _truthy(
        body.get("answer_debug")
        or body.get("debug_answer")
        or cfg.get("debug")
        or cfg.get("answer_debug")
    )


def _attach_answer_debug_if_requested(body: dict, message: str, result: dict) -> dict:
    if not _answer_debug_requested(body):
        return result
    evidence = _zhiyi_context_to_model_evidence(result)
    model_call = result.get("model_call", {}) if isinstance(result.get("model_call"), dict) else {}
    result["answer_debug"] = {
        "contract": "dialog_entry_answer_debug.v2026.6.18",
        "read_only": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "question": str(message or ""),
        "draft_answer": str(result.get("answer_before_model_call") or result.get("answer") or ""),
        "final_answer": str(result.get("answer") or ""),
        "answer_source": result.get("answer_source", ""),
        "evidence_count": len(evidence),
        "evidence": _debug_evidence_items(evidence),
        "model_call": {
            "requested": bool(model_call.get("requested")),
            "called": bool(model_call.get("called")),
            "request_sent": bool(model_call.get("request_sent")),
            "provider": model_call.get("provider", ""),
            "provider_id": model_call.get("provider_id", ""),
            "model_name": model_call.get("model_name", ""),
            "transport": model_call.get("transport", ""),
            "verdict": model_call.get("model_verdict", ""),
            "confidence": model_call.get("model_confidence", 0),
            "supporting_refs": model_call.get("supporting_refs", []),
            "evidence_packet_refs": model_call.get("evidence_packet_refs", []),
            "validation_error": model_call.get("model_validation_error", ""),
            "not_called_reason": model_call.get("not_called_reason", ""),
            "fallback_applied": bool(model_call.get("fallback_applied")),
            "gating_policy": model_call.get("model_gating_policy", ""),
            "gating_reason": model_call.get("model_gating_reason", ""),
            "gating_signals": model_call.get("model_gating_signals", []),
            "api_key_env": model_call.get("api_key_env", ""),
            "api_key_present": bool(model_call.get("api_key_present")),
        },
    }
    return result


def _run_evidence_bound_model_for_zhiyi(message: str, result: dict, request: dict) -> dict:
    started = time.time()
    provider = str(request.get("provider") or request.get("provider_hint") or "").strip().lower()
    config = default_model_config(
        provider=provider,
        model=request.get("model") or "",
        base_url=request.get("base_url") or "",
    )
    evidence = _zhiyi_context_to_model_evidence(result)
    evidence_packet_refs = _evidence_packet_refs(evidence)
    draft_answer = str(result.get("answer") or "")
    gating = plan_evidence_bound_answer_model_use(
        message,
        evidence,
        draft_answer=draft_answer,
        policy=request.get("call_policy") or "always",
    )
    if not gating.get("should_call_model"):
        return {
            "requested": True,
            "called": False,
            "provider": config.provider or provider or "openai_compatible",
            "provider_id": provider or config.provider or "openai_compatible",
            "model_name": config.model,
            "transport": "openai_compatible_http",
            "request_sent": False,
            "response_received": False,
            "runtime_binding_ready": bool(config.api_key_present and config.base_url and config.model),
            "not_called_reason": str(gating.get("reason") or "model_call_gated"),
            "elapsed_seconds": round(time.time() - started, 2),
            "answer_chars": 0,
            "answer_excerpt": "",
            "usable_answer_received": False,
            "empty_answer": True,
            "session_id": "",
            "model_contract": EVIDENCE_BOUND_MODEL_CONTRACT,
            "model_verdict": "gated",
            "model_confidence": 0.0,
            "model_validation_error": "",
            "supporting_refs": [],
            "evidence_packet_refs": evidence_packet_refs,
            "evidence_count": len(evidence),
            "draft_answer_present": bool(draft_answer.strip()),
            "model_gating_policy": gating.get("policy", ""),
            "model_gating_reason": gating.get("reason", ""),
            "model_gating_signals": gating.get("signals", []),
            "api_key_env": config.api_key_env,
            "api_key_present": bool(config.api_key_present),
        }
    model_result = run_evidence_bound_answer(
        message,
        evidence,
        draft_answer=draft_answer,
        model_config=config,
        execute=True,
    )
    answer = str(model_result.get("answer") or "")
    unknown_answer = answer.strip().upper() == "UNKNOWN"
    used_refs = model_result.get("supporting_refs", [])
    usable = bool(answer and (unknown_answer or used_refs))
    return {
        "requested": True,
        "called": bool(model_result.get("model_call_performed")),
        "provider": config.provider or provider or "openai_compatible",
        "provider_id": provider or config.provider or "openai_compatible",
        "model_name": config.model,
        "transport": "openai_compatible_http",
        "request_sent": bool(model_result.get("model_call_performed")),
        "response_received": usable,
        "runtime_binding_ready": bool(config.api_key_present and config.base_url and config.model),
        "not_called_reason": "" if usable else str(model_result.get("validation_error") or model_result.get("unknown_reason") or model_result.get("verdict") or "no_usable_answer"),
        "exit_code": 0 if model_result.get("ok", True) else -1,
        "elapsed_seconds": round(time.time() - started, 2),
        "answer_chars": len(answer) if usable else 0,
        "answer_excerpt": answer[:800] if usable else "",
        "usable_answer_received": usable,
        "empty_answer": not usable,
        "session_id": "",
        "model_contract": model_result.get("contract", EVIDENCE_BOUND_MODEL_CONTRACT),
        "model_verdict": model_result.get("verdict", ""),
        "model_confidence": model_result.get("confidence", 0.0),
        "model_validation_error": model_result.get("validation_error", ""),
        "supporting_refs": used_refs,
        "used_source_refs": used_refs,
        "evidence_packet_refs": evidence_packet_refs,
        "evidence_count": model_result.get("evidence_count", len(evidence)),
        "unknown_answer": unknown_answer,
        "unknown_reason": model_result.get("unknown_reason", ""),
        "draft_answer_present": bool(draft_answer.strip()),
        "model_gating_policy": gating.get("policy", ""),
        "model_gating_reason": gating.get("reason", ""),
        "model_gating_signals": gating.get("signals", []),
        "api_key_env": model_result.get("api_key_env", ""),
        "api_key_present": bool(model_result.get("api_key_present")),
    }


def maybe_run_zhiyi_live_model_call(body: dict, message: str, result: dict) -> dict:
    request = _model_call_request(body)
    if not request.get("enabled"):
        return _attach_answer_debug_if_requested(body, message, result)
    if result.get("chain") != "F3_zhiyi_direct" or result.get("status") != "ok":
        result["model_call"] = {
            "requested": True,
            "called": False,
            "runtime_binding_ready": False,
            "not_called_reason": "only_f3_zhiyi_direct_ok_can_call_model",
        }
        return _attach_answer_debug_if_requested(body, message, result)
    provider = str(request.get("provider") or "").strip().lower()
    if provider not in ("hermes_cli", "openai_compatible", "evidence_bound_model", "deepseek", "minimax"):
        result["model_call"] = {
            "requested": True,
            "called": False,
            "runtime_binding_ready": False,
            "not_called_reason": "unsupported_model_call_provider",
            "provider_id": request.get("provider"),
        }
        return _attach_answer_debug_if_requested(body, message, result)
    if not request.get("confirm_live_model_call"):
        result["model_call"] = {
            "requested": True,
            "called": False,
            "runtime_binding_ready": False,
            "not_called_reason": "confirm_live_model_call_required",
        }
        return _attach_answer_debug_if_requested(body, message, result)
    if provider == "hermes_cli":
        model_call = _run_hermes_cli_for_zhiyi(message, result, request)
    else:
        model_call = _run_evidence_bound_model_for_zhiyi(message, result, request)
    result["model_call"] = model_call
    if model_call.get("called") and model_call.get("answer_excerpt"):
        result["model_answer"] = model_call["answer_excerpt"]
        result["answer_before_model_call"] = result.get("answer", "")
        result["answer"] = model_call["answer_excerpt"]
        result["answer_source"] = "hermes_cli_model_call" if provider == "hermes_cli" else "evidence_bound_model_call"
        result["used_source_refs"] = model_call.get("used_source_refs") or model_call.get("supporting_refs", [])
    elif model_call.get("request_sent"):
        fallback_answer = _zhiyi_direct_fallback_after_model_no_answer(message, result, model_call)
        if fallback_answer:
            result["answer_before_model_call"] = result.get("answer", "")
            result["answer"] = fallback_answer
            result["answer_source"] = "zhiyi_direct_natural_fallback_after_model_no_answer"
            result["model_fallback_applied"] = True
            model_call["fallback_applied"] = True
    return _attach_answer_debug_if_requested(body, message, result)


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
        or source_system_delivery_enabled(body=body, cfg=cfg)
    )
    session_key = str(
        cfg.get("session_key")
        or cfg.get("target_session_key")
        or source_system_delivery_session_key(body)
        or body.get("target_session_key")
        or body.get("session_key")
        or ""
    ).strip()
    if not session_key:
        session_key = source_system_delivery_session_key_from_identity(session_id=session_id, source_system=platform)
    mode = str(cfg.get("mode") or body.get("delivery_mode") or "same_chat").strip().lower()
    idempotency_key = str(
        cfg.get("idempotency_key")
        or body.get("delivery_idempotency_key")
        or ""
    ).strip()
    requested = bool(cfg or enabled or platform or session_key)
    platform = infer_delivery_source_system(platform=platform, session_key=session_key, body=body)
    authorized = _truthy(
        cfg.get("authorized")
        or cfg.get("confirm_platform_act")
        or cfg.get("platform_act_authorized")
        or body.get("confirm_platform_act")
        or body.get("platform_act_authorized")
        or body.get("authorize_platform_act")
    )
    return {
        "requested": requested,
        "enabled": enabled,
        "platform": platform,
        "mode": mode,
        "session_key": session_key,
        "idempotency_key": idempotency_key,
        "authorized": authorized,
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
            "model_contract": model_call.get("model_contract", ""),
            "model_verdict": model_call.get("model_verdict", ""),
            "model_confidence": model_call.get("model_confidence", 0),
            "model_validation_error": model_call.get("model_validation_error", ""),
            "supporting_refs": model_call.get("supporting_refs", []),
            "evidence_count": model_call.get("evidence_count", 0),
            "model_gating_policy": model_call.get("model_gating_policy", ""),
            "model_gating_reason": model_call.get("model_gating_reason", ""),
            "model_gating_signals": model_call.get("model_gating_signals", []),
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
    else:
        for runtime_kind in declared_delivery_runtime_kinds():
            result_key = PLATFORM_DELIVERY_RESULT_KEYS.get(runtime_kind)
            if not result_key:
                continue
            candidate = result.get(result_key)
            if not isinstance(candidate, dict):
                continue
            applied_to_platform = bool(candidate.get("ok")) and not (
                isinstance(result.get("platform_delivery"), dict)
                and result.get("platform_delivery", {}).get("visible_reply_ok") is False
            )
            if applied_to_platform:
                break

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

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def reject_management_if_forbidden(self) -> bool:
        if _management_request_allowed(getattr(self, "client_address", None), self.headers):
            return False
        self.send_json({"ok": False, "error": "loopback clients only"}, 403)
        return True

    def reject_entry_if_forbidden(self, path: str) -> bool:
        if _entry_request_allowed(path, getattr(self, "client_address", None), self.headers):
            return False
        self.send_json({"ok": False, "error": "dialog entry token required for non-loopback clients"}, 403)
        return True

    def do_GET(self):
        if self.path == "/health":
            self.send_json({
                "status": "ok",
                "service": "dialog_entry_proxy",
                "port": 9860,
                "default_bind_host": DEFAULT_BIND_HOST,
                "lan_requires_token": True,
            })
            return
        if self.path == "/flags":
            if self.reject_management_if_forbidden():
                return
            flags = get_flags()
            self.send_json({"flags": flags})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/flags":
            if self.reject_management_if_forbidden():
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_json({"error": "invalid json"}, 400)
                return
            flags = get_flags()
            changed = []
            for key in ["zhiyi_direct", "zhiyi_inject", "openclaw_passive_auto_inject", "openclaw_rpc", "passthrough", "audit_log", "fts5_recall"]:
                if key in data:
                    flags[key] = bool(data[key])
                    changed.append(key)
            save_flags(flags)
            self.send_json({"flags": flags, "changed": changed})
            return

        if self.path in ENTRY_ACTION_HANDLERS:
            if self.reject_entry_if_forbidden(self.path):
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.send_json({"error": "invalid json"}, 400)
                return
            handler_name = ENTRY_ACTION_HANDLERS[self.path]
            result = getattr(self, handler_name)(data)
            self.send_json(result)
            return

        if self.path != "/entry":
            self.send_response(404)
            self.end_headers()
            return

        if self.reject_entry_if_forbidden(self.path):
            return
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_json({"error": "invalid json"}, 400)
            return

        message = data.get("message", "")
        session_id = data.get("session_id", str(uuid.uuid4()))
        scope_filter = data.get("scope_filter", {})
        entry_intent = normalize_zhiyi_entry_query(message)

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
            "zhiyi_entry": {
                "requested": bool(entry_intent.get("is_zhiyi_entry")),
                "command": entry_intent.get("entry_command", ""),
                "language": entry_intent.get("entry_language", ""),
            },
        }

        if level == 1:
            result = self.handle_memory_direct(entry_intent.get("query") or message, scope_filter, audit)
        elif level == 2:
            result = self.handle_zhiyi_inject(message, scope_filter, audit)
        else:
            result = self.handle_pass_through(message, session_id, audit)

        result = maybe_run_zhiyi_live_model_call(data, message, result)
        result = self.maybe_deliver_platform_answer(data, message, session_id, result)
        result = _attach_answer_debug_if_requested(data, message, result)
        usage_log = record_zhiyi_usage_log(message, result, audit)
        result["usage_log"] = usage_log
        audit_log({"type": "entry_request", **audit, "result_status": result.get("status"), "usage_log_write_performed": usage_log.get("usage_log_write_performed", False)})
        self.send_json(result)

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
        authority = decide_memory_authority(
            source="dialog_entry_platform_delivery",
            requested_authority="platform_act",
            zhiyi_entry=bool((result.get("audit") or {}).get("zhiyi_entry", {}).get("requested")) if isinstance(result.get("audit"), dict) else False,
            explicit_direct_authorized=result.get("chain") == "F3_zhiyi_direct" and result.get("status") == "ok",
            platform_action_requested=True,
            platform_action_authorized=bool(delivery.get("authorized")),
        )
        status["memory_authority"] = authority
        result["memory_authority"] = authority
        result["platform_delivery"] = status

        if not status["enabled"]:
            status["reason"] = "platform_delivery_not_enabled"
            return result
        if not authority.get("can_platform_act"):
            status["reason"] = authority.get("reason") or "platform_act_requires_explicit_authorization"
            return result
        runtime_kind = source_system_delivery_runtime_kind(status["platform"])
        if runtime_kind not in PLATFORM_DELIVERY_FORWARDERS:
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

        forwarder_name = PLATFORM_DELIVERY_FORWARDERS[runtime_kind]
        forwarder = getattr(self, forwarder_name)
        if status["idempotency_key"]:
            forward_result = forwarder(
                answer,
                status["target_session_key"],
                idempotency_key=status["idempotency_key"],
            )
        else:
            forward_result = forwarder(answer, status["target_session_key"])
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
        """Native OpenClaw pre-model hook: only explicit Zhiyi entry may preempt provider dispatch."""
        event = _openclaw_before_dispatch_request(body)
        base = {
            "status": "skipped",
            "chain": "openclaw_before_dispatch",
            "handled": False,
            "text": "",
            "openclaw_write_performed": False,
            "passthrough_forwarded": False,
            "memory_authority": decide_memory_authority(
                source="openclaw_before_dispatch",
                requested_authority="passive",
            ),
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
        entry_intent = normalize_zhiyi_entry_query(message)
        direct_authorized = bool(entry_intent.get("is_zhiyi_entry")) or (
            force_zhiyi_direct
            and _truthy(
                (body or {}).get("confirm_direct_answer")
                or (body or {}).get("confirm_zhiyi_direct")
                or (body or {}).get("direct_answer_authorized")
            )
        )
        direct_authority = decide_memory_authority(
            source="openclaw_before_dispatch",
            requested_authority="direct_answer" if force_zhiyi_direct or entry_intent.get("is_zhiyi_entry") else "passive",
            zhiyi_entry=bool(entry_intent.get("is_zhiyi_entry")),
            explicit_direct_authorized=direct_authorized,
        )
        if not force_zhiyi_direct and not entry_intent.get("is_zhiyi_entry"):
            base.update({
                "reason": "openclaw_before_dispatch_requires_explicit_zhiyi_entry",
                "level": classify_intent(message),
                "label": level_to_label(classify_intent(message)),
                "action": "pass_through",
                "memory_authority": direct_authority,
            })
            return base
        if not direct_authority.get("can_direct_answer"):
            base.update({
                "reason": direct_authority.get("reason") or "direct_answer_requires_explicit_zhiyi_entry",
                "level": classify_intent(message),
                "label": level_to_label(classify_intent(message)),
                "action": "pass_through",
                "memory_authority": direct_authority,
            })
            return base
        level = 1
        action = level_to_action(level)
        label = level_to_label(level)

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
            "zhiyi_entry": {
                "requested": bool(entry_intent.get("is_zhiyi_entry")),
                "command": entry_intent.get("entry_command", ""),
                "language": entry_intent.get("entry_language", ""),
            },
        }
        result = self.handle_memory_direct(entry_intent.get("query") or message, event.get("scope_filter", {}), audit)
        result["memory_authority"] = direct_authority
        result["runtime_delivery_context"] = {
            "source": "openclaw_before_dispatch",
            "route": "F3_zhiyi_direct",
            "delivery_method": "before_dispatch_return",
            "platform": "openclaw",
            "session_key": event.get("session_key", ""),
            "channel": event.get("channel", ""),
            "status": "model_dispatch_preempted",
            "note": "本轮 OpenClaw webchat 消息已经在 provider 模型分发前进入Time Library知意；可自然表述为：已经在 OpenClaw 前台无声接上知意 before_dispatch，并直接作为 final reply 展示。",
        }
        dispatch_body = dict(body or {})
        result = maybe_run_zhiyi_live_model_call(dispatch_body, message, result)
        result = _attach_answer_debug_if_requested(dispatch_body, message, result)
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
            "memory_authority": decide_memory_authority(
                source="openclaw_native_event",
                requested_authority="passive",
            ),
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
        entry_intent = normalize_zhiyi_entry_query(message)
        if not entry_intent.get("is_zhiyi_entry"):
            base.update({
                "reason": "openclaw_native_event_requires_explicit_zhiyi_entry",
                "level": level,
                "label": label,
                "action": "pass_through",
            })
            return base
        level = 1
        action = level_to_action(level)
        label = level_to_label(level)

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
            "zhiyi_entry": {
                "requested": True,
                "command": entry_intent.get("entry_command", ""),
                "language": entry_intent.get("entry_language", ""),
            },
        }
        direct_authority = decide_memory_authority(
            source="openclaw_native_event",
            requested_authority="direct_answer",
            zhiyi_entry=True,
            explicit_direct_authorized=True,
        )
        platform_authority = decide_memory_authority(
            source="openclaw_native_event_platform_act",
            requested_authority="platform_act",
            zhiyi_entry=True,
            explicit_direct_authorized=True,
            platform_action_requested=True,
            platform_action_authorized=_truthy(
                (body or {}).get("confirm_platform_act")
                or (body or {}).get("platform_act_authorized")
                or (body or {}).get("authorize_platform_act")
            ),
        )
        if platform_authority.get("can_platform_act"):
            pre_delivery_abort = self._abort_openclaw_active_run(session_key)
        else:
            pre_delivery_abort = {
                "attempted": False,
                "ok": False,
                "aborted": False,
                "run_ids": [],
                "method": "chat.abort",
                "reason": platform_authority.get("reason") or "platform_act_requires_explicit_authorization",
                "memory_authority": platform_authority,
            }
        result = self.handle_memory_direct(entry_intent.get("query") or message, event.get("scope_filter", {}), audit)
        result["memory_authority"] = direct_authority
        result["openclaw_pre_delivery_abort"] = pre_delivery_abort
        event_id = event.get("event_id") or uuid.uuid4().hex[:12]
        delivery_body = dict(body or {})
        delivery_body["platform_delivery"] = {
            **_dict_value(delivery_body.get("platform_delivery")),
            "enabled": True,
            "platform": "openclaw",
            "mode": "same_chat",
            "session_key": session_key,
            "idempotency_key": f"memcore-openclaw-event-{event_id}",
            "authorized": platform_authority.get("can_platform_act"),
        }
        result = maybe_run_zhiyi_live_model_call(delivery_body, message, result)
        result = self.maybe_deliver_platform_answer(delivery_body, message, session_key, result)
        result = _attach_answer_debug_if_requested(delivery_body, message, result)
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
                    label="Time Library知意",
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


def run(port=9860, host=DEFAULT_BIND_HOST):
    bind_host = str(host or DEFAULT_BIND_HOST).strip() or DEFAULT_BIND_HOST
    _ensure_dialog_entry_token_file()
    server = HTTPServer((bind_host, port), DialogEntryHandler)
    print(f"dialog_entry_proxy running on http://{bind_host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="memcore-cloud dialog entry proxy")
    parser.add_argument("--host", default=os.environ.get("MEMCORE_DIALOG_ENTRY_HOST", DEFAULT_BIND_HOST))
    parser.add_argument("--port", type=int, default=9860)
    args = parser.parse_args()
    run(port=args.port, host=args.host)
