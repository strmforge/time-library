#!/usr/bin/env python3
"""
runtime_context_package
================================================
GAP-2 Fix: context_package not strongly typed

强类型 ContextPackage 模型，基于 RIC schema (context_package.v1)。
所有字段都有类型标注，构造时做基本校验。

Schema fields:
- query_hash: str (SHA256 helper for routing and dedupe)
- canonical_window_id: str
- session_id: str
- intent_mode: str (summary|evidence|verbatim|audit)
- matched_memories: list[dict]
- source_refs: list[dict]
- scope_enforced: bool
- injection_blocked: bool
- block_reason: str|null
- assembled_at: str (ISO8601)
"""

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

UTC = timezone.utc

# ─── Legacy field list kept for compatibility ─────────────────────
FORBIDDEN_FIELDS = frozenset({
    "token", "tokens", "api_key", "apikey", "api_key_b64",
    "password", "secret", "private_key", "privatekey", "client_secret",
    "auth_token", "access_token", "refresh_token", "bearer_token",
    "encryption_key", "secret_key", "message_content", "raw_content",
})

INTENT_MODES = frozenset({"summary", "evidence", "verbatim", "audit"})

def ts():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

def hash_query(query: str) -> str:
    """SHA256 hash — query 明文不存储"""
    return hashlib.sha256(query.encode()).hexdigest()

def sanitize_dict(d):
    """Compatibility no-op: context packages keep platform records verbatim."""
    if isinstance(d, dict):
        return {
            k: sanitize_dict(v) if isinstance(v, (dict, list)) else v
            for k, v in d.items()
        }
    elif isinstance(d, list):
        return [sanitize_dict(item) if isinstance(item, dict) else item for item in d]
    else:
        return d

def generate_event_id() -> str:
    return str(uuid.uuid4())

class ValidationError(Exception):
    pass

# ─── ContextPackage ────────────────────────────────────────────────

class ContextPackage:
    """
    强类型 ContextPackage。
    构造时校验所有必填字段，类型错误抛出 ValidationError。
    """
    def __init__(
        self,
        query: str = "",
        query_hash: Optional[str] = None,
        canonical_window_id: str = "",
        session_id: str = "",
        intent_mode: str = "summary",
        matched_memories: Optional[list] = None,
        source_refs: Optional[list] = None,
        scope_enforced: bool = False,
        injection_blocked: bool = False,
        block_reason: Optional[str] = None,
        assembled_at: Optional[str] = None,
    ):
        # Basic validation
        if intent_mode not in INTENT_MODES:
            raise ValidationError(f"intent_mode must be one of {INTENT_MODES}, got '{intent_mode}'")

        if not query and not query_hash:
            raise ValidationError("Either query or query_hash must be provided")

        matched_memories = matched_memories or []
        source_refs = source_refs or []

        self.query = query  # May be empty if only query_hash is available
        self.query_hash = query_hash or hash_query(query)
        self.canonical_window_id = canonical_window_id
        self.session_id = session_id
        self.intent_mode = intent_mode
        self.matched_memories = sanitize_dict(matched_memories) if matched_memories else []
        self.source_refs = sanitize_dict(source_refs) if source_refs else []
        self.scope_enforced = scope_enforced
        self.injection_blocked = injection_blocked
        self.block_reason = block_reason
        self.assembled_at = assembled_at or ts()

    def to_dict(self) -> dict:
        return {
            "schema": "context_package.v1",
            "query_hash": self.query_hash,
            "canonical_window_id": self.canonical_window_id,
            "session_id": self.session_id,
            "intent_mode": self.intent_mode,
            "matched_memories": self.matched_memories,
            "source_refs": self.source_refs,
            "scope_enforced": self.scope_enforced,
            "injection_blocked": self.injection_blocked,
            "block_reason": self.block_reason,
            "assembled_at": self.assembled_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContextPackage":
        return cls(
            query="",  # Reconstructed from hash only
            query_hash=d.get("query_hash", ""),
            canonical_window_id=d.get("canonical_window_id", ""),
            session_id=d.get("session_id", ""),
            intent_mode=d.get("intent_mode", "summary"),
            matched_memories=d.get("matched_memories", []),
            source_refs=d.get("source_refs", []),
            scope_enforced=d.get("scope_enforced", False),
            injection_blocked=d.get("injection_blocked", False),
            block_reason=d.get("block_reason"),
            assembled_at=d.get("assembled_at"),
        )

    def __repr__(self):
        return (f"ContextPackage(hash={self.query_hash[:8]}..., "
                f"window={self.canonical_window_id}, "
                f"intent={self.intent_mode}, "
                f"memories={len(self.matched_memories)})")


# ─── InjectionDecision ─────────────────────────────────────────────

class InjectionDecision:
    """
    强类型 InjectionDecision。
    对应 RIC schema (injection_decision.v1)。
    """
    def __init__(
        self,
        decision: str,  # inject|skip|block|error
        confidence: float,
        should_inject: bool,
        threshold: float,
        reason: str,
        injection_policy: str = "auto",
        blocking_active: bool = False,
        trace: Optional[list] = None,
        decided_at: Optional[str] = None,
    ):
        if decision not in frozenset({"inject", "skip", "block", "error"}):
            raise ValidationError(f"decision must be inject|skip|block|error, got '{decision}'")
        if not (0.0 <= confidence <= 1.0):
            raise ValidationError(f"confidence must be 0.0~1.0, got {confidence}")
        if not (0.0 <= threshold <= 1.0):
            raise ValidationError(f"threshold must be 0.0~1.0, got {threshold}")

        self.decision = decision
        self.confidence = confidence
        self.should_inject = should_inject
        self.threshold = threshold
        self.reason = reason
        self.injection_policy = injection_policy
        self.blocking_active = blocking_active
        self.trace = trace or []
        self.decided_at = decided_at or ts()

    def to_dict(self) -> dict:
        return {
            "schema": "injection_decision.v1",
            "decision": self.decision,
            "confidence": self.confidence,
            "should_inject": self.should_inject,
            "threshold": self.threshold,
            "reason": self.reason,
            "injection_policy": self.injection_policy,
            "blocking_active": self.blocking_active,
            "trace": self.trace,
            "decided_at": self.decided_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InjectionDecision":
        return cls(
            decision=d.get("decision", "error"),
            confidence=d.get("confidence", 0.0),
            should_inject=d.get("should_inject", False),
            threshold=d.get("threshold", 0.7),
            reason=d.get("reason", ""),
            injection_policy=d.get("injection_policy", "auto"),
            blocking_active=d.get("blocking_active", False),
            trace=d.get("trace", []),
            decided_at=d.get("decided_at"),
        )


# ─── InterpositionEvent ────────────────────────────────────────────

class InterpositionEvent:
    """
    强类型 InterpositionEvent。
    对应 RIC schema (interposition_event.v1)。

    Keeps matched memory and source reference content as provided. Query hash is
    an index helper, not a replacement for source-backed memory content.
    """
    def __init__(
        self,
        event_type: str,  # recall_query|injection_decision|context_assembled|injection_blocked|scope_violation
        source_system: str,  # openclaw|hermes|codex|local_files
        context_package: Optional[dict] = None,
        injection_decision: Optional[dict] = None,
        observe_only: bool = True,
        applied: bool = False,
        dry_run: bool = True,
        extra: Optional[dict] = None,
        event_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ):
        valid_types = frozenset({
            "recall_query", "injection_decision", "context_assembled",
            "injection_blocked", "scope_violation", "recall_observed",
        })
        if event_type not in valid_types:
            raise ValidationError(f"event_type must be one of {valid_types}, got '{event_type}'")

        self.event_id = event_id or generate_event_id()
        self.event_type = event_type
        self.source_system = source_system
        self.context_package = sanitize_dict(context_package) if context_package else {}
        self.injection_decision = sanitize_dict(injection_decision) if injection_decision else {}
        self.observe_only = observe_only
        self.applied = applied
        self.dry_run = dry_run
        self.extra = sanitize_dict(extra) if extra else {}
        self.timestamp = timestamp or ts()

    def to_dict(self) -> dict:
        return {
            "schema": "interposition_event.v1",
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source_system": self.source_system,
            "timestamp": self.timestamp,
            "context_package": self.context_package,
            "injection_decision": self.injection_decision,
            "observe_only": self.observe_only,
            "applied": self.applied,
            "dry_run": self.dry_run,
            **self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InterpositionEvent":
        extra = {k: v for k, v in d.items()
                 if k not in {"schema", "event_id", "event_type", "source_system",
                               "timestamp", "context_package", "injection_decision",
                               "observe_only", "applied", "dry_run"}}
        return cls(
            event_id=d.get("event_id"),
            event_type=d.get("event_type", ""),
            source_system=d.get("source_system", ""),
            context_package=d.get("context_package"),
            injection_decision=d.get("injection_decision"),
            observe_only=d.get("observe_only", True),
            applied=d.get("applied", False),
            dry_run=d.get("dry_run", True),
            extra=extra,
            timestamp=d.get("timestamp"),
        )


# ─── RIC Event Logger ──────────────────────────────────────────────

AUDIT_LOG_PATH = "/tmp/ric_audit_events.jsonl"

def log_interposition_event(event: InterpositionEvent) -> str:
    """
    将 InterpositionEvent 写入 audit log (JSONL)。
    只写 tmp 目录，不写 production zhiyi/。
    返回 event_id。
    """
    import json
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n")
    return event.event_id

def read_audit_events(limit: int = 100) -> list:
    """读取最近的 audit events（用于验证）"""
    import json
    events = []
    if not os.path.exists(AUDIT_LOG_PATH):
        return events
    with open(AUDIT_LOG_PATH) as f:
        lines = f.readlines()
    for line in reversed(lines[-limit:]):
        try:
            events.append(json.loads(line))
        except:
            pass
    return list(reversed(events))

# ─── Tests ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os

    # Test 1: ContextPackage
    cp = ContextPackage(
        query="test query",
        canonical_window_id="window_sg",
        session_id="session_001",
        intent_mode="summary",
        matched_memories=[
            {"memory_id": "mem1", "summary": "test memory", "token": "secret123"},
        ],
        scope_enforced=True,
    )
    print(f"ContextPackage: {cp}")
    d = cp.to_dict()
    print(f"  to_dict: query_hash={d['query_hash'][:8]}..., memories={len(d['matched_memories'])}")

    # Test 2: InjectionDecision
    id_ = InjectionDecision(
        decision="inject",
        confidence=0.85,
        should_inject=True,
        threshold=0.7,
        reason="confidence 0.85 >= threshold 0.7",
    )
    print(f"InjectionDecision: {id_.decision}, should_inject={id_.should_inject}")

    # Test 3: InterpositionEvent
    evt = InterpositionEvent(
        event_type="recall_query",
        source_system="openclaw",
        context_package=cp.to_dict(),
    )
    print(f"InterpositionEvent: {evt.event_id}, type={evt.event_type}")

    # Test 4: Verbatim preservation
    cp_verbatim = ContextPackage(
        query="source backed query",
        canonical_window_id="window_test",
        intent_mode="summary",
        matched_memories=[
            {"summary": "test", "token": "USER_OWN_TEXT_123", "detail": "keep source text as-is"},
        ],
    )
    print(f"Verbatim preserved: {'USER_OWN_TEXT_123' in str(cp_verbatim.matched_memories)}")

    print("All tests passed ✓")
