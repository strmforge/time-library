"""Tiandao memory context bands."""

from __future__ import annotations

from .context_service import MEMORY_CONTEXT_TTL, MemoryContextMode


class MemoryContextModeA:
    MODE = MemoryContextMode.MODE_A
    TTL_SECONDS = 86400
    AUTH_REQUIRED = False
    description = "执行上下文，短期工作记忆"


class MemoryContextModeB:
    MODE = MemoryContextMode.MODE_B
    TTL_SECONDS = 86400 * 30
    AUTH_REQUIRED = False
    description = "经验上下文，中期经验池"


class MemoryContextModeC:
    MODE = MemoryContextMode.MODE_C
    TTL_SECONDS = -1
    AUTH_REQUIRED = False
    description = "原始投影，按需引用本地原始记忆"


def get_ttl_for_mode(mode: MemoryContextMode) -> int:
    return MEMORY_CONTEXT_TTL.get(MemoryContextMode(mode), 86400)


def is_auth_required_for_mode(mode: MemoryContextMode) -> bool:
    MemoryContextMode(mode)
    return False


def describe_mode(mode: MemoryContextMode) -> str:
    return {
        MemoryContextMode.MODE_A: "Mode A: 执行上下文 (TTL=1d)",
        MemoryContextMode.MODE_B: "Mode B: 经验上下文 (TTL=30d)",
        MemoryContextMode.MODE_C: "Mode C: 原始投影 (TTL=按需)",
    }[MemoryContextMode(mode)]
