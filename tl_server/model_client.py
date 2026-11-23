"""Talking to model endpoints in their native protocol.

Three wire protocols, spoken natively (no translation layer between them):

  responses  POST {base}/responses         OpenAI Responses
  messages   POST {base}/messages          Anthropic Messages
  chat       POST {base}/chat/completions  fallback for endpoints with neither

A local model server and a relay differ only in address: both are just a base
URL that speaks one of these.
"""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any

PROTOCOLS = ("responses", "messages", "chat")
ANTHROPIC_VERSION = "2023-06-01"
LIST_TIMEOUT = 20
MAX_MODEL_PAGES = 20

# Why a call failed, in terms the owner can act on.
REASON_UNREACHABLE = "unreachable"  # cannot connect at all
REASON_AUTH = "auth"  # key missing, wrong or revoked
REASON_QUOTA = "quota"  # out of balance / quota
REASON_NOT_FOUND = "not_found"  # wrong address, protocol or model name
REASON_BAD_RESPONSE = "bad_response"  # answered, but not in the chosen protocol
REASON_HTTP = "http"  # any other refusal


class ModelError(Exception):
    def __init__(self, reason: str, message: str = "", status: int | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.message = message or reason
        self.status = status


def _headers(protocol: str, api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "time-library-server"}
    if protocol == "messages":
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if api_key:
            headers["x-api-key"] = api_key
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _classify(status: int, body: str) -> str:
    lowered = body.lower()
    if status == 402 or any(mark in lowered for mark in ("insufficient_quota", "insufficient balance", "余额不足", "quota exceeded", "billing")):
        return REASON_QUOTA
    if status in (401, 403):
        return REASON_AUTH
    if status == 404:
        return REASON_NOT_FOUND
    return REASON_HTTP


# Told the very bytes of a request that carries words to a model, right before they are sent; what it returns is
# told how that ended (ledger.py). None: nothing is written down (a model list, a test of this module).
OnSend = Any


def _told(on_send: OnSend, url: str, data: bytes | None):
    return on_send(url, data) if on_send is not None and data is not None else (lambda *_, **__: None)


def _request(method: str, url: str, headers: dict[str, str], body: Any, timeout: float, on_send: OnSend = None) -> Any:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    ended = _told(on_send, url, data)
    try:
        payload = _answer_of(method, url, headers, data, timeout)
    except ModelError as error:
        ended(f"error:{error.reason}", error.message)
        raise
    ended("ok", json.dumps(payload, ensure_ascii=False), payload.get("usage") if isinstance(payload, dict) and isinstance(payload.get("usage"), dict) else {})
    return payload


def _answer_of(method: str, url: str, headers: dict[str, str], data: bytes | None, timeout: float) -> Any:
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        text = error.read(4096).decode("utf-8", errors="replace")
        raise ModelError(_classify(error.code, text), text[:300], error.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as error:
        raise ModelError(REASON_UNREACHABLE, str(getattr(error, "reason", error))[:300]) from None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ModelError(REASON_BAD_RESPONSE, "the endpoint did not answer with JSON") from None


def list_models(base_url: str, protocol: str, api_key: str) -> list[str]:
    """Ask the endpoint which models it offers (GET {base}/models)."""
    return [entry["id"] for entry in list_models_detailed(base_url, protocol, api_key)]


def _levels_of(item: Any) -> tuple[list[str], str]:
    """The thinking levels a model entry reports, and its default; ([], '') when it says nothing.

    Two published shapes are read: a list of levels with a default (the shape of
    OpenAI's Codex model catalog: supported_reasoning_levels / default_reasoning_level)
    and Anthropic's capability tree (capabilities.effort.<level>.supported).
    """
    if not isinstance(item, dict):
        return [], ""
    levels: list[str] = []
    for name in ("supported_reasoning_levels", "supported_reasoning_efforts", "reasoning_efforts"):
        for level in item.get(name) or []:
            word = level if isinstance(level, str) else (level.get("effort") or level.get("reasoning_effort") or level.get("name")) if isinstance(level, dict) else None
            if isinstance(word, str) and EFFORT_PATTERN.match(word) and word not in levels:
                levels.append(word)
    capabilities = item.get("capabilities")
    effort = capabilities.get("effort") if isinstance(capabilities, dict) else None
    if isinstance(effort, dict) and effort.get("supported"):
        for word, leaf in effort.items():
            if word != "supported" and isinstance(leaf, dict) and leaf.get("supported") and EFFORT_PATTERN.match(word) and word not in levels:
                levels.append(word)
    default = ""
    for name in ("default_reasoning_level", "default_reasoning_effort"):
        if isinstance(item.get(name), str) and EFFORT_PATTERN.match(item[name]):
            default = item[name]
            break
    return levels, default


def list_models_detailed(base_url: str, protocol: str, api_key: str) -> list[dict[str, Any]]:
    """The endpoint's models, each with the thinking levels it reports (if any)."""
    base = base_url.rstrip("/")
    headers = _headers(protocol, api_key)
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    after = ""
    for _page in range(MAX_MODEL_PAGES):
        url = f"{base}/models" + (f"?after_id={after}&limit=1000" if after else ("?limit=1000" if protocol == "messages" else ""))
        payload = _request("GET", url, headers, None, LIST_TIMEOUT)
        items = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ModelError(REASON_BAD_RESPONSE, "the endpoint did not return a model list")
        for item in items:
            model_id = item.get("id") if isinstance(item, dict) else item
            if isinstance(model_id, str) and model_id and model_id not in seen:
                seen.add(model_id)
                levels, default = _levels_of(item)
                found.append({"id": model_id, "levels": levels, "default_level": default})
        # Only the Messages listing is paged.
        if not (isinstance(payload, dict) and payload.get("has_more") and payload.get("last_id")):
            break
        after = str(payload["last_id"])
    return found


def _text_from_reply(protocol: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ModelError(REASON_BAD_RESPONSE, "unexpected reply shape")
    parts: list[str] = []
    if protocol == "responses":
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        output = payload.get("output")
        if not isinstance(output, list):
            raise ModelError(REASON_BAD_RESPONSE, "reply has no output: is this endpoint really Responses?")
        for item in output:
            for block in (item.get("content") or []) if isinstance(item, dict) else []:
                if isinstance(block, dict) and block.get("type") in ("output_text", "text") and isinstance(block.get("text"), str):
                    parts.append(block["text"])
    elif protocol == "messages":
        content = payload.get("content")
        if not isinstance(content, list):
            raise ModelError(REASON_BAD_RESPONSE, "reply has no content: is this endpoint really Messages?")
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
    else:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelError(REASON_BAD_RESPONSE, "reply has no choices: is this endpoint really chat/completions?")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            parts.append(content)
    return "".join(parts)


# A thinking level is the model's own word (for example low / medium / high /
# xhigh / max / ultra, which differ per model): never a fixed list here. Where the
# endpoint reports the levels a model takes, they are read from its model list.
EFFORT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
# Thinking counts against the output cap in every protocol: room for it when a
# level is chosen, so the answer itself is never cut short.
THINKING_ROOM = 32000


def complete(
    base_url: str,
    protocol: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    system: str = "",
    max_tokens: int = 1024,
    timeout: float = 120,
    effort: str = "",
    stream: bool = True,
    on_send: OnSend = None,
) -> dict[str, Any]:
    """One request, one answer, in the endpoint's own protocol.

    Streamed by default: the answer arrives as it is written, so a long answer
    never sits behind one silent connection that a relay or gateway may cut.
    `effort` is the model's own word for a thinking level, sent as is in the
    protocol's own field; empty leaves the model's default.
    """
    if protocol not in PROTOCOLS:
        raise ModelError(REASON_NOT_FOUND, f"unknown protocol: {protocol}")
    base = base_url.rstrip("/")
    if protocol == "responses":
        url = f"{base}/responses"
        body: dict[str, Any] = {"model": model, "input": prompt, "max_output_tokens": max_tokens, "store": False}
        if system:
            body["instructions"] = system
    elif protocol == "messages":
        url = f"{base}/messages"
        body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
    else:
        url = f"{base}/chat/completions"
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if effort:
        if not EFFORT_PATTERN.match(effort):
            raise ModelError(REASON_HTTP, f"not a thinking level: {effort[:40]}")
        if protocol == "responses":
            body["reasoning"] = {"effort": effort}
            body["max_output_tokens"] = max_tokens + THINKING_ROOM
        elif protocol == "messages":
            body["thinking"] = {"type": "adaptive"}
            body["output_config"] = {"effort": effort}
            body["max_tokens"] = max_tokens + THINKING_ROOM
        else:
            body["reasoning_effort"] = effort
            body["max_tokens"] = max_tokens + THINKING_ROOM
    headers = _headers(protocol, api_key)
    started = time.monotonic()
    if stream:
        try:
            text, usage = _stream(protocol, url, headers, {**body, **_stream_fields(protocol)}, timeout, on_send)
        except ModelError as error:
            if error.status != 400:
                raise
            # An endpoint that refuses the streaming fields: one ordinary request instead.
            text, usage = _whole(protocol, url, headers, body, timeout, on_send)
    else:
        text, usage = _whole(protocol, url, headers, body, timeout, on_send)
    return {
        "text": text,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
        "output_tokens": usage.get("output_tokens", usage.get("completion_tokens")),
    }


def _stream_fields(protocol: str) -> dict[str, Any]:
    if protocol == "chat":
        return {"stream": True, "stream_options": {"include_usage": True}}
    return {"stream": True}


def _whole(protocol: str, url: str, headers: dict[str, str], body: Any, timeout: float, on_send: OnSend = None) -> tuple[str, dict[str, Any]]:
    payload = _request("POST", url, headers, body, timeout, on_send)
    usage = payload.get("usage") if isinstance(payload, dict) and isinstance(payload.get("usage"), dict) else {}
    return _text_from_reply(protocol, payload), usage


def _stream(protocol: str, url: str, headers: dict[str, str], body: Any, timeout: float, on_send: OnSend = None) -> tuple[str, dict[str, Any]]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    ended = _told(on_send, url, data)
    try:
        text, usage = _streamed(protocol, url, headers, data, timeout)
    except ModelError as error:
        ended(f"error:{error.reason}", error.message)
        raise
    ended("ok", text, usage)
    return text, usage


def _streamed(protocol: str, url: str, headers: dict[str, str], data: bytes, timeout: float) -> tuple[str, dict[str, Any]]:
    """Read a server-sent-events answer: text deltas and the usage figures."""
    request = urllib.request.Request(url, data=data, method="POST", headers={**headers, "Accept": "text/event-stream"})
    try:
        response = urllib.request.urlopen(request, timeout=timeout)  # the timeout is per read: it never trips while text flows
    except urllib.error.HTTPError as error:
        text = error.read(4096).decode("utf-8", errors="replace")
        raise ModelError(_classify(error.code, text), text[:300], error.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as error:
        raise ModelError(REASON_UNREACHABLE, str(getattr(error, "reason", error))[:300]) from None
    parts: list[str] = []
    usage: dict[str, Any] = {}
    understood = False
    try:
        with response:
            if "text/event-stream" not in (response.headers.get("Content-Type") or ""):
                # The endpoint ignored the request to stream: an ordinary answer.
                try:
                    payload = json.loads(response.read().decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise ModelError(REASON_BAD_RESPONSE, "the endpoint did not answer with JSON") from None
                usage = payload.get("usage") if isinstance(payload, dict) and isinstance(payload.get("usage"), dict) else {}
                return _text_from_reply(protocol, payload), usage
            name = ""
            for raw in response:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    name = ""
                    continue
                if line.startswith("event:"):
                    name = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    event = json.loads(chunk)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get("type") or name
                if kind == "error" or kind == "response.failed" or (protocol == "chat" and event.get("error")):
                    detail = json.dumps(event, ensure_ascii=False)
                    reason = _classify(0, detail)
                    # Broken off mid-answer ("Upstream HTTP/2 stream failed"): the relay's
                    # upstream failed, like a 502. Worth another try, not a stopped round;
                    # quota and key problems keep their own reasons.
                    raise ModelError(reason, detail[:300], 502 if reason == REASON_HTTP else None)
                if protocol == "responses":
                    if kind == "response.output_text.delta" and isinstance(event.get("delta"), str):
                        parts.append(event["delta"])
                        understood = True
                    elif kind in ("response.completed", "response.incomplete"):
                        finished = event.get("response") if isinstance(event.get("response"), dict) else {}
                        usage = finished.get("usage") or usage
                        if not parts and finished.get("output"):
                            parts.append(_text_from_reply(protocol, finished))
                        understood = True
                elif protocol == "messages":
                    if kind == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                            parts.append(delta["text"])  # thinking deltas are not the answer
                        understood = True
                    elif kind == "message_start":
                        usage.update((event.get("message") or {}).get("usage") or {})
                        understood = True
                    elif kind == "message_delta":
                        usage.update(event.get("usage") or {})
                else:
                    for choice in event.get("choices") or []:
                        content = (choice.get("delta") or {}).get("content") if isinstance(choice, dict) else None
                        if isinstance(content, str):
                            parts.append(content)
                        understood = True
                    if isinstance(event.get("usage"), dict):
                        usage = event["usage"]
                        understood = True
    except (socket.timeout, TimeoutError, OSError) as error:
        if isinstance(error, ModelError):
            raise
        raise ModelError(REASON_UNREACHABLE, f"the answer stopped arriving: {error}"[:300]) from None
    if not understood:
        raise ModelError(REASON_BAD_RESPONSE, "the stream was not in the chosen protocol")
    return "".join(parts), usage


def probe(base_url: str, protocol: str, api_key: str, model: str, timeout: float = 60, effort: str = "", on_send: OnSend = None) -> dict[str, Any]:
    """The smallest real call: proves address, protocol, key and model (and a thinking level) together."""
    reply = complete(base_url, protocol, api_key, model, "Reply with the single word: OK", max_tokens=16, timeout=timeout, effort=effort, on_send=on_send)
    return {"latency_ms": reply["latency_ms"]}
