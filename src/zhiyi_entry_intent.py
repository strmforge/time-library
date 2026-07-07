#!/usr/bin/env python3
"""Language-neutral Zhiyi entry intent helpers."""

from __future__ import annotations

import re
from typing import Any, Dict


ZHIYI_ENTRY_COMMANDS = (
    "/zhiyi",
    "/memory",
    "/recall",
    "/continue",
    "/catchup",
    "/catch-up",
    "/memcore",
    "/time_library",
    "/gets-you",
    "/getsyou",
)

ZHIYI_ENTRY_PHRASES = (
    "接一下前文",
    "接上前文",
    "接上上次",
    "接上项目",
    "按项目继续",
    "查一下本机记忆",
    "查一下之前的记录",
    "从本机记忆",
    "用本机记忆",
    "续上前文",
    "catch me up",
    "continue from memory",
    "continue from local memory",
    "check local memory",
    "check my memory",
    "look up my memory",
    "look up previous context",
    "pick up where we left off",
    "resume from memory",
    "what did we decide",
    "what did we say before",
)


def _clean_command_remainder(text: str) -> str:
    return re.sub(r"^[\s:：,，;；-]+", "", text or "").strip()


def normalize_zhiyi_entry_query(query: Any) -> Dict[str, Any]:
    """Detect slash/natural Zhiyi entry requests without rewriting saved content.

    The returned ``query`` is only a recall search string. The caller can keep the
    original user message separately for logs or source records.
    """
    original = str(query or "").strip()
    lowered = original.lower()
    for command in ZHIYI_ENTRY_COMMANDS:
        if lowered == command or lowered.startswith(command + " "):
            remainder = _clean_command_remainder(original[len(command):])
            return {
                "is_zhiyi_entry": True,
                "entry_command": command,
                "entry_language": "neutral",
                "query": remainder or "前文 项目 进度 上下文 memory context",
                "original_query": original,
            }

    for phrase in ZHIYI_ENTRY_PHRASES:
        if phrase in lowered:
            return {
                "is_zhiyi_entry": True,
                "entry_command": "",
                "entry_language": "zh-CN" if re.search(r"[\u4e00-\u9fff]", phrase) else "en-US",
                "query": original,
                "original_query": original,
            }

    return {
        "is_zhiyi_entry": False,
        "entry_command": "",
        "entry_language": "",
        "query": original,
        "original_query": original,
    }


def is_zhiyi_entry_request(query: Any) -> bool:
    return bool(normalize_zhiyi_entry_query(query).get("is_zhiyi_entry"))
