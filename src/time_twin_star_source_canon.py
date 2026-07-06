"""Read-only Time Twin Star source-canon snapshot.

This module carries data only. It lets lightweight status surfaces read the
accepted Time Twin Star source-canon projection without importing the broader
``tiandao`` package or any runtime module.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


TIME_TWIN_STAR_SOURCE_CANON_STATUS_CONTRACT = "time_twin_star_source_canon_status.v1"

_TIME_TWIN_STAR_STATUS = {
    "surface_contract": "time_tiandao_surface.v1",
    "rules_contract": "time_rules.v1",
    "current_repo_source": "src/tiandao/memory_routing.py",
    "current_status": "read_only_projection_present",
    "runtime_status": "not_connected",
    "implementation_status": "first_cut_read_only_projection",
    "projection_source": "src/tiandao/time_twin_star.py",
    "first_cut_policy": "read_only_projection_no_runtime_behavior_change",
    "rule_status_counts_from_tiandao_v1": {
        "candidate_source_proven": 0,
        "contract_only": 1,
        "planned": 1,
        "source_proven": 11,
    },
    "source_proven_rules": [
        "derived_sediment_must_reference_origin",
        "each_runtime_first_witnessed_raw",
        "events_remain_orderable",
        "platforms_are_inlets_not_origin",
        "raw_is_highest_authority",
        "read_only_descriptor_no_write",
        "river_begins_at_origin_event",
        "source_refs_required_not_replacement",
        "summaries_are_navigation_not_source",
        "time_origin_is_witnessed_raw",
        "unknown_when_no_origin_link",
    ],
    "source_proven_scope": "repository_behavior_only",
}


def time_twin_star_source_canon_entry() -> dict[str, Any]:
    return deepcopy(_TIME_TWIN_STAR_STATUS)
