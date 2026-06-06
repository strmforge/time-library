"""Neutral Tiandao AuditEvent contract merged into the Python mirror."""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

UTC = timezone.utc


class AuditAction(str, Enum):
    TASK_CREATE = "task.create"
    TASK_EXECUTE = "task.execute"
    TASK_COMPLETE = "task.complete"
    TASK_FAIL = "task.fail"
    VERDICT_CREATE = "verdict.create"
    VERDICT_APPROVE = "verdict.approve"
    VERDICT_REJECT = "verdict.reject"
    ROLE_CREATE = "role.create"
    ROLE_ASSIGN = "role.assign"
    ROLE_REVOKE = "role.revoke"
    CONTEXT_ASSEMBLE = "context.assemble"
    CONTEXT_INJECT = "context.inject"
    EVIDENCE_COLLECT = "evidence.collect"
    SOURCE_REF_TRACK = "source_ref.track"
    CONNECTION_OPEN = "connection.open"
    CONNECTION_CLOSE = "connection.close"
    REGISTRY_REGISTER = "registry.register"
    REGISTRY_UNREGISTER = "registry.unregister"


class AuditResult(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    PARTIAL = "partial"


def _audit_ts() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _audit_event_id() -> str:
    suffix = "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(8))
    return f"audit_{int(time.time() * 1000)}_{suffix}"


class TiandaoAuditEvent:
    """Common audit envelope shared by Honghuang systems."""

    def __init__(
        self,
        actor: str,
        action: AuditAction | str,
        target: str,
        result: AuditResult | str,
        event_id: str = "",
        timestamp: str = "",
        details: dict[str, Any] | None = None,
        source_ip: str = "",
        user_agent: str = "",
    ):
        self.event_id = event_id or _audit_event_id()
        self.timestamp = timestamp or _audit_ts()
        self.actor = actor
        self.action = AuditAction(action)
        self.target = target
        self.result = AuditResult(result)
        self.details = details or {}
        self.source_ip = source_ip
        self.user_agent = user_agent

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "action": self.action.value,
            "target": self.target,
            "result": self.result.value,
        }
        if self.details:
            data["details"] = self.details
        if self.source_ip:
            data["source_ip"] = self.source_ip
        if self.user_agent:
            data["user_agent"] = self.user_agent
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TiandaoAuditEvent":
        return cls(
            event_id=str(data.get("event_id", "")),
            timestamp=str(data.get("timestamp", "")),
            actor=str(data.get("actor", "")),
            action=str(data.get("action", AuditAction.TASK_CREATE.value)),
            target=str(data.get("target", "")),
            result=str(data.get("result", AuditResult.PENDING.value)),
            details=data.get("details") if isinstance(data.get("details"), dict) else {},
            source_ip=str(data.get("source_ip", "")),
            user_agent=str(data.get("user_agent", "")),
        )


def create_audit_event(
    *,
    actor: str,
    action: AuditAction | str,
    target: str,
    result: AuditResult | str,
    event_id: str = "",
    details: dict[str, Any] | None = None,
    source_ip: str = "",
    user_agent: str = "",
) -> dict[str, Any]:
    return TiandaoAuditEvent(
        event_id=event_id,
        actor=actor,
        action=action,
        target=target,
        result=result,
        details=details,
        source_ip=source_ip,
        user_agent=user_agent,
    ).to_dict()
