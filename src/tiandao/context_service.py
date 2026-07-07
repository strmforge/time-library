"""Local mirror of the neutral Tiandao context package contract.

Tiandao itself is the private architecture-wide public rule system. This module is only
this repository's reader/candidate surface for memory context delivery: it
keeps platform adapters thin, preserves source evidence, and avoids claiming
runtime, release, orchestration system, sync route, or central-node completion.
"""

from __future__ import annotations

import copy
import hashlib
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

UTC = timezone.utc


class IntentMode(str, Enum):
    """How much context a caller wants back."""

    SUMMARY = "summary"
    EVIDENCE = "evidence"
    VERBATIM = "verbatim"
    AUDIT = "audit"


class MemoryContextMode(str, Enum):
    """Tiandao memory context bands as used by this local mirror."""

    MODE_A = "mode_a"
    MODE_B = "mode_b"
    MODE_C = "mode_c"


MEMORY_CONTEXT_TTL = {
    MemoryContextMode.MODE_A: 86400,
    MemoryContextMode.MODE_B: 86400 * 30,
    MemoryContextMode.MODE_C: -1,
}

# Kept for old imports. Tiandao no longer redacts fields at this layer.
FORBIDDEN_FIELDS: set[str] = set()


def preserve_dict(data: Any, _depth: int = 0) -> Any:
    """Return a detached copy of data without redaction or masking."""
    if _depth > 20:
        return copy.deepcopy(data)
    if isinstance(data, dict):
        return {k: preserve_dict(v, _depth + 1) for k, v in data.items()}
    if isinstance(data, list):
        return [preserve_dict(item, _depth + 1) for item in data]
    return copy.deepcopy(data)


def sanitize_dict(data: Any, _depth: int = 0) -> Any:
    """Compatibility alias: preserve data as-is in this local mirror."""
    return preserve_dict(data, _depth)


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_query(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()


def generate_event_id() -> str:
    return str(uuid.uuid4())


class ValidationError(Exception):
    pass


class ContextPackage:
    """Strong context package shaped like the Tiandao candidate contract.

    Adapters may include raw_projection when the caller needs original local
    memory data. This local mirror still defaults to memory_write=False because
    the neutral Tiandao rules coordinate context rather than writing platform
    state.
    """

    schema_version = "tiandao_context_package.v1"

    def __init__(
        self,
        query: str = "",
        query_hash: Optional[str] = None,
        source_system: str = "",
        canonical_window_id: str = "",
        session_id: str = "",
        intent_mode: IntentMode | str = IntentMode.SUMMARY,
        memory_context_mode: MemoryContextMode | str = MemoryContextMode.MODE_A,
        matched_memories: Optional[list] = None,
        source_refs: Optional[list] = None,
        raw_projection: Optional[dict] = None,
        active_memory_routing_contract: str = "",
        active_layers_used: Optional[list] = None,
        current_window_binding_applied: bool = False,
        cross_window_read: bool = False,
        cross_window_read_allowed: bool = False,
        scope_enforced: bool = False,
        injection_blocked: bool = False,
        block_reason: Optional[str] = None,
        memory_write: bool = False,
        assembled_at: Optional[str] = None,
    ):
        try:
            intent_mode = IntentMode(intent_mode)
            memory_context_mode = MemoryContextMode(memory_context_mode)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if not query and not query_hash:
            raise ValidationError("Either query or query_hash must be provided")

        self.query = query
        self.query_hash = query_hash or hash_query(query)
        self.source_system = source_system
        self.canonical_window_id = canonical_window_id
        self.session_id = session_id
        self.intent_mode = intent_mode
        self.memory_context_mode = memory_context_mode
        self.matched_memories = preserve_dict(matched_memories or [])
        self.source_refs = preserve_dict(source_refs or [])
        self.raw_projection = preserve_dict(raw_projection or {})
        self.active_memory_routing_contract = active_memory_routing_contract
        self.active_layers_used = preserve_dict(active_layers_used or [])
        self.current_window_binding_applied = bool(current_window_binding_applied)
        self.cross_window_read = bool(cross_window_read)
        self.cross_window_read_allowed = bool(cross_window_read_allowed)
        self.scope_enforced = scope_enforced
        self.injection_blocked = injection_blocked
        self.block_reason = block_reason
        self.memory_write = memory_write
        self.assembled_at = assembled_at or ts()

    @property
    def ttl_seconds(self) -> int:
        return MEMORY_CONTEXT_TTL.get(self.memory_context_mode, 86400)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema_version,
            "query": self.query,
            "query_hash": self.query_hash,
            "source_system": self.source_system,
            "canonical_window_id": self.canonical_window_id,
            "session_id": self.session_id,
            "intent_mode": self.intent_mode.value,
            "memory_context_mode": self.memory_context_mode.value,
            "ttl_seconds": self.ttl_seconds,
            "matched_memories": preserve_dict(self.matched_memories),
            "source_refs": preserve_dict(self.source_refs),
            "raw_projection": preserve_dict(self.raw_projection),
            "active_memory_routing_contract": self.active_memory_routing_contract,
            "active_layers_used": preserve_dict(self.active_layers_used),
            "current_window_binding_applied": self.current_window_binding_applied,
            "cross_window_read": self.cross_window_read,
            "cross_window_read_allowed": self.cross_window_read_allowed,
            "scope_enforced": self.scope_enforced,
            "injection_blocked": self.injection_blocked,
            "block_reason": self.block_reason,
            "memory_write": self.memory_write,
            "assembled_at": self.assembled_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContextPackage":
        return cls(
            query=d.get("query", ""),
            query_hash=d.get("query_hash", ""),
            source_system=d.get("source_system", ""),
            canonical_window_id=d.get("canonical_window_id", ""),
            session_id=d.get("session_id", ""),
            intent_mode=d.get("intent_mode", "summary"),
            memory_context_mode=d.get("memory_context_mode", "mode_a"),
            matched_memories=d.get("matched_memories", []),
            source_refs=d.get("source_refs", []),
            raw_projection=d.get("raw_projection", {}),
            active_memory_routing_contract=d.get("active_memory_routing_contract", ""),
            active_layers_used=d.get("active_layers_used", []),
            current_window_binding_applied=d.get("current_window_binding_applied", False),
            cross_window_read=d.get("cross_window_read", False),
            cross_window_read_allowed=d.get("cross_window_read_allowed", False),
            scope_enforced=d.get("scope_enforced", False),
            injection_blocked=d.get("injection_blocked", False),
            block_reason=d.get("block_reason"),
            memory_write=d.get("memory_write", False),
            assembled_at=d.get("assembled_at"),
        )

    def __repr__(self) -> str:
        return (
            f"ContextPackage(hash={self.query_hash[:8]}..., "
            f"source={self.source_system}, intent={self.intent_mode.value}, "
            f"mode={self.memory_context_mode.value}, write={self.memory_write})"
        )


class ContextService(ABC):
    """Common interface implemented by source-system adapters."""

    @property
    @abstractmethod
    def source_system(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def build_context_package(
        self,
        query: str,
        intent_mode: IntentMode = IntentMode.SUMMARY,
        memory_context_mode: MemoryContextMode = MemoryContextMode.MODE_A,
        session_id: str = "",
        canonical_window_id: str = "",
    ) -> ContextPackage:
        raise NotImplementedError

    @abstractmethod
    def validate_context_package(self, package: ContextPackage) -> tuple[bool, Optional[str]]:
        raise NotImplementedError

    @abstractmethod
    def supports_intent_mode(self, mode: IntentMode) -> bool:
        raise NotImplementedError
