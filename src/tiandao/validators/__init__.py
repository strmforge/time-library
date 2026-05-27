"""Validators for Tiandao packages."""

from __future__ import annotations

from tiandao.context_service import IntentMode, MemoryContextMode


def scan_forbidden_fields(data: dict) -> list[str]:
    """Compatibility scanner. Tiandao no longer redacts raw local memory data."""
    return []


def validate_context_package(pkg: dict) -> tuple[bool, list[str]]:
    violations: list[str] = []
    if pkg.get("schema") != "tiandao_context_package.v1":
        violations.append("schema must be tiandao_context_package.v1")
    if not pkg.get("query") and not pkg.get("query_hash"):
        violations.append("query or query_hash is required")
    try:
        IntentMode(pkg.get("intent_mode", "summary"))
    except ValueError:
        violations.append("invalid intent_mode")
    try:
        MemoryContextMode(pkg.get("memory_context_mode", "mode_a"))
    except ValueError:
        violations.append("invalid memory_context_mode")
    if pkg.get("memory_write") is True:
        violations.append("memory_write=True is not owned by Tiandao context packages")
    return len(violations) == 0, violations


def validate_with_schema(pkg: dict, schema_name: str | None = None) -> tuple[bool, list[str]]:
    return validate_context_package(pkg)


def validate_projection_package(pkg: dict) -> tuple[bool, list[str]]:
    return validate_context_package(pkg)
