"""Local mirror of the neutral Tiandao boundary contract.

The boundary is about platform shape: adapters stay thin, source systems keep
their own capabilities, and raw projections may carry original local memory
data when the product path needs it.
"""

from __future__ import annotations

from typing import Any


class SourceRef:
    """Reference to an external artifact or memory source."""

    def __init__(
        self,
        ref_id: str,
        source_system: str,
        artifact_type: str,
        ref_path: str = "",
        artifact_id: str = "",
        captured_at: str = "",
        auth_required: bool = False,
        auth_granted: bool = False,
        content: Any = None,
    ):
        self.ref_id = ref_id
        self.source_system = source_system
        self.artifact_type = artifact_type
        self.ref_path = ref_path
        self.artifact_id = artifact_id
        self.captured_at = captured_at
        self.auth_required = auth_required
        self.auth_granted = auth_granted
        self.content = content

    @property
    def can_read_content(self) -> bool:
        return True

    def to_dict(self) -> dict:
        d = {
            "ref_id": self.ref_id,
            "source_system": self.source_system,
            "artifact_type": self.artifact_type,
            "ref_path": self.ref_path,
            "artifact_id": self.artifact_id,
            "captured_at": self.captured_at,
            "auth_required": self.auth_required,
            "auth_granted": self.auth_granted,
        }
        if self.content is not None:
            d["content"] = self.content
        return d

    def __repr__(self) -> str:
        return f"SourceRef({self.source_system}/{self.artifact_type}@{self.ref_id[:8]})"


class BoundaryChecker:
    """Checks local mirror rules without claiming Tiandao authority."""

    def __init__(self, package: "ContextPackage"):
        self.package = package

    def check(self) -> tuple[bool, list[str]]:
        violations: list[str] = []
        if getattr(self.package, "memory_write", False):
            violations.append("local context-package mirrors do not perform direct memory writes")
        return len(violations) == 0, violations

    def _check_forbidden_fields(self, d: dict, path: str = "") -> list[str]:
        return []

    def _check_mode_c_auth(self) -> bool:
        return True

    def _ref_has_raw_content(self, ref: dict) -> bool:
        return False
