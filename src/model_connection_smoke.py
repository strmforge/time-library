#!/usr/bin/env python3
"""Authorized live checks for the Time Library analysis-model preference."""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from src.model_api_key_store import (
        credential_ref_for,
        resolve_model_api_key,
    )
except Exception:
    from model_api_key_store import (
        credential_ref_for,
        resolve_model_api_key,
    )


MODEL_CONNECTION_SMOKE_CONTRACT = "time_library_model_connection_smoke.v1"
DEFAULT_PROMPT = "Reply with exactly TIME_LIBRARY_MODEL_OK."


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "confirmed"}
    return bool(value)


def _compact(value, limit=240):
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    return text if len(text) <= limit else text[:limit]


def _provider_kind(provider, provider_id, option_id):
    marker = " ".join(str(item or "") for item in (provider, provider_id, option_id)).lower()
    if "deepseek" in marker:
        return "deepseek"
    if "minimax" in marker:
        return "minimax"
    if "openai" in marker:
        return "openai_compatible"
    return str(provider_id or provider or "").strip().lower()


def _present_env(preferred, fallbacks, env):
    names = [str(preferred or "").strip()] + list(fallbacks)
    seen = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        if env.get(name):
            return name
    return str(preferred or "").strip() or (fallbacks[0] if fallbacks else "")


def _direct_config(body, env):
    provider = _provider_kind(
        body.get("provider"), body.get("provider_id"), body.get("model_id")
    )
    model = str(body.get("model_name") or "").strip()
    base_url = str(body.get("base_url") or "").strip().rstrip("/")
    explicit_key_env = "api_key_env" in body
    requested_key_env = str(
        body.get("api_key_env") if explicit_key_env else "MEMCORE_ZHIYI_API_KEY"
    ).strip()
    if provider == "deepseek":
        base_url = base_url or str(env.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").rstrip("/")
        key_env = _present_env(requested_key_env, ("DEEPSEEK_API_KEY",), env)
    elif provider == "minimax":
        base_url = base_url or str(
            env.get("MINIMAX_BASE_URL")
            or env.get("MINIMAX_CN_BASE_URL")
            or "https://api.minimaxi.com/v1"
        ).rstrip("/")
        key_env = _present_env(requested_key_env, ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY"), env)
    else:
        base_url = base_url or str(
            env.get("OPENAI_COMPATIBLE_BASE_URL") or env.get("OPENAI_BASE_URL") or ""
        ).rstrip("/")
        key_env = (
            requested_key_env
            if explicit_key_env
            else _present_env(requested_key_env, ("OPENAI_API_KEY",), env)
        )
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key_env": key_env,
        "credential_ref": str(body.get("credential_ref") or "").strip()
        or credential_ref_for(provider, body.get("provider_id")),
    }


def _chat_url(base_url):
    base = str(base_url or "").rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _is_loopback_model_url(url):
    host = (urllib.parse.urlparse(str(url or "")).hostname or "").rstrip(".").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _base_result(body):
    return {
        "ok": False,
        "contract": MODEL_CONNECTION_SMOKE_CONTRACT,
        "model_call_performed": False,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_config_write_performed": False,
        "secret_values_returned": False,
        "connection_scope": "explicit_test_only",
        "model_id": str(body.get("model_id") or ""),
        "model": str(body.get("model_name") or ""),
    }


def _authorization_missing(body):
    authorization = body.get("authorization")
    if not isinstance(authorization, dict):
        authorization = body
    checks = {
        "confirm_live_model_call": _truthy(authorization.get("confirm_live_model_call")),
        "confirm_no_platform_config_write": _truthy(authorization.get("confirm_no_platform_config_write")),
        "operator": bool(str(authorization.get("operator") or "").strip()),
        "reason": bool(str(authorization.get("reason") or "").strip()),
    }
    return [name for name, passed in checks.items() if not passed]


def _resolve_hermes_cli(body, env):
    candidates = (
        body.get("hermes_cli"),
        env.get("MEMCORE_HERMES_CLI"),
        env.get("HERMES_CLI_PATH"),
        env.get("HERMES_CLI"),
    )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return os.path.expanduser(value)

    discovered = shutil.which("hermes", path=str(env.get("PATH") or ""))
    if discovered:
        return discovered

    for candidate in (
        os.path.expanduser("~/.local/bin/hermes"),
        "/opt/homebrew/bin/hermes",
        "/usr/local/bin/hermes",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "hermes"


def _run_hermes(body, result, env, run_command):
    cli = _resolve_hermes_cli(body, env)
    model = str(body.get("model_name") or "").strip()
    provider_id = str(body.get("provider_id") or "").strip()
    command = [
        cli,
        "chat",
        "-q",
        str(body.get("prompt") or DEFAULT_PROMPT)[:500],
        "-Q",
        "--max-turns",
        "1",
        "--ignore-rules",
        "--source",
        "tool",
    ]
    if model:
        command.extend(["--model", model])
    if provider_id and provider_id.lower() not in {"hermes", "default"}:
        command.extend(["--provider", provider_id])
    started = time.time()
    try:
        completed = (run_command or subprocess.run)(
            command,
            capture_output=True,
            text=True,
            timeout=max(3, min(int(body.get("timeout_seconds") or 90), 180)),
            env=dict(env),
        )
        ok = int(getattr(completed, "returncode", 1)) == 0
        stdout = str(getattr(completed, "stdout", "") or "")
        stderr = str(getattr(completed, "stderr", "") or "")
        result.update({
            "ok": ok,
            "test_path": "hermes_cli",
            "platform": "hermes",
            "model_call_performed": True,
            "runnable_status": "runnable" if ok else "failed",
            "response_observed": bool(stdout.strip()),
            "elapsed_seconds": round(time.time() - started, 3),
            "error": "" if ok else "hermes_cli_failed",
            "stderr_excerpt": _compact(stderr),
        })
    except subprocess.TimeoutExpired:
        result.update({
            "test_path": "hermes_cli",
            "platform": "hermes",
            "model_call_performed": True,
            "runnable_status": "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "error": "timeout",
        })
    except Exception as exc:
        result.update({
            "test_path": "hermes_cli",
            "platform": "hermes",
            "model_call_performed": False,
            "runnable_status": "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "error": exc.__class__.__name__,
        })
    return result


def _run_direct_http(body, result, env, urlopen, credential_root=None):
    config = _direct_config(body, env)
    key, key_source = resolve_model_api_key(
        credential_root,
        api_key_env=config["api_key_env"],
        credential_ref=config["credential_ref"],
        transient_value=body.get("api_key_value"),
        env=env,
    )
    url = _chat_url(config["base_url"])
    local_endpoint = _is_loopback_model_url(url)
    authentication_mode = "bearer" if key else ("none_loopback" if local_endpoint else "missing")
    result.update({
        "test_path": "openai_compatible_http",
        "provider": config["provider"],
        "model": config["model"],
        "api_key_env": config["api_key_env"],
        "api_key_present": bool(key),
        "api_key_source": key_source,
        "credential_ref": config["credential_ref"],
        "base_url_host": urllib.parse.urlparse(url).hostname or "",
        "local_endpoint": local_endpoint,
        "authentication_mode": authentication_mode,
    })
    missing = []
    if not config["model"]:
        missing.append("model_name")
    if not url:
        missing.append("base_url")
    if not key and not local_endpoint:
        missing.append("api_key_env_value")
    if missing:
        result.update({"error": "model_config_missing", "missing": missing})
        return result

    payload = {
        "model": config["model"],
        "messages": [{"role": "user", "content": str(body.get("prompt") or DEFAULT_PROMPT)[:500]}],
        "temperature": 0,
        "max_tokens": 32,
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    default_timeout = 180 if local_endpoint else 60
    timeout_seconds = max(
        3, min(int(body.get("timeout_seconds") or default_timeout), 180)
    )
    result["timeout_seconds"] = timeout_seconds
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.time()
    try:
        opener = urlopen or urllib.request.urlopen
        with opener(request, timeout=timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        content = (
            response_payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        result.update({
            "ok": True,
            "model_call_performed": True,
            "runnable_status": "runnable",
            "response_observed": bool(str(content).strip()),
            "elapsed_seconds": round(time.time() - started, 3),
            "error": "",
        })
    except urllib.error.HTTPError as exc:
        result.update({
            "model_call_performed": True,
            "runnable_status": "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "error": "http_" + str(exc.code),
        })
    except Exception as exc:
        result.update({
            "model_call_performed": True,
            "runnable_status": "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "error": exc.__class__.__name__,
        })
    return result


def run_model_connection_smoke(
    body=None,
    *,
    env=None,
    run_command=None,
    urlopen=None,
    credential_root=None,
):
    """Run a minimal model call for the exact selection shown in settings."""
    body = body if isinstance(body, dict) else {}
    result = _base_result(body)
    missing = _authorization_missing(body)
    if missing:
        result.update({
            "requires_authorization": True,
            "missing_authorization": missing,
            "error": "missing_authorization",
        })
        return result
    if not str(body.get("model_id") or body.get("model_name") or "").strip():
        result.update({
            "requires_selection": True,
            "error": "specific_model_selection_required",
        })
        return result

    env_source = dict(os.environ if env is None else env)
    category = str(body.get("option_category") or "").strip().lower()
    provider = str(body.get("provider") or "").strip().lower()
    if category == "hermes" or provider == "hermes":
        return _run_hermes(body, result, env_source, run_command)
    return _run_direct_http(body, result, env_source, urlopen, credential_root)


__all__ = ["MODEL_CONNECTION_SMOKE_CONTRACT", "run_model_connection_smoke"]
