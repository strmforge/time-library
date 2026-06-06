"""Neutral Tiandao EvidenceLevel contract merged into the Python mirror."""

from __future__ import annotations

from enum import Enum


class TiandaoEvidenceLevel(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    AUTO_EVIDENCED = "AUTO_EVIDENCED"
    LOCAL_REVIEWED = "LOCAL_REVIEWED"
    CODEX_REVIEWED = "CODEX_REVIEWED"
    OWNER_ACCEPTED = "OWNER_ACCEPTED"


EVIDENCE_LEVEL_RANK: dict[TiandaoEvidenceLevel, int] = {
    TiandaoEvidenceLevel.SELF_REPORTED: 0,
    TiandaoEvidenceLevel.AUTO_EVIDENCED: 1,
    TiandaoEvidenceLevel.LOCAL_REVIEWED: 2,
    TiandaoEvidenceLevel.CODEX_REVIEWED: 3,
    TiandaoEvidenceLevel.OWNER_ACCEPTED: 4,
}


def is_evidence_level_at_least(
    level: TiandaoEvidenceLevel | str,
    minimum: TiandaoEvidenceLevel | str,
) -> bool:
    return EVIDENCE_LEVEL_RANK[TiandaoEvidenceLevel(level)] >= EVIDENCE_LEVEL_RANK[
        TiandaoEvidenceLevel(minimum)
    ]
