#!/usr/bin/env python3
"""Source-system display taxonomy for reading-area lanes.

This is a projection layer only. It keeps stored source_system values intact
while giving reading-area pages a stable lane vocabulary.
"""

from __future__ import annotations

import re
from typing import Any


SOURCE_SYSTEM_TAXONOMY_CONTRACT = "time_library_source_system_taxonomy.v1"

_LANE_ALIASES = {
    "claude_code_cli": "opus",
    "claude_code": "opus",
    "opus": "opus",
    "mimocode": "mimo",
    "mimo_code": "mimo",
    "mimo": "mimo",
    "codex": "codex",
}


def _clean(value: Any, *, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def normalize_source_system(value: Any) -> str:
    """Return a normalized source-system token for comparisons."""

    token = _clean(value).lower().replace("-", "_")
    return token


def canonical_reading_area_lane(value: Any, *, consumer: Any = "") -> str:
    """Return the canonical lane label for reading-area projection.

    Only the explicit source identity may choose a lane. ``consumer`` is kept
    for API compatibility and telemetry, but it must not relabel source-backed
    records or change startup Delivery content.
    """

    source_token = normalize_source_system(value)
    if source_token in _LANE_ALIASES:
        return _LANE_ALIASES[source_token]
    return _clean(value or "unknown", limit=80) or "unknown"


def source_system_aliases(value: Any, *, consumer: Any = "") -> list[str]:
    """Return visible aliases that were folded into the canonical lane."""

    canonical = canonical_reading_area_lane(value)
    aliases: list[str] = []
    token = normalize_source_system(value)
    if token and token != canonical:
        aliases.append(token)
    return aliases


__all__ = [
    "SOURCE_SYSTEM_TAXONOMY_CONTRACT",
    "canonical_reading_area_lane",
    "normalize_source_system",
    "source_system_aliases",
]
