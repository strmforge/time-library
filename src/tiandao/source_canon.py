"""Local source-canon registry for accepted Tiandao texts.

This module carries NAS source-canon metadata into the Yifanchen repository as
local read-only data. The NAS paths below are audit source refs only: importing
this module must not read NAS files, require a mounted volume, or imply runtime
integration.
"""

from __future__ import annotations

from typing import Any

try:
    from src.time_twin_star_source_canon import time_twin_star_source_canon_entry
except Exception:  # pragma: no cover - direct script import fallback
    from time_twin_star_source_canon import time_twin_star_source_canon_entry


TIANDAO_SOURCE_CANON_REGISTRY_CONTRACT = "tiandao_source_canon_registry.v1"
TIANDAO_CORE_CANON_REF = "tiandao-core-yizhong-tongyuan-source-canon-discipline@2026-06-22"
TIANDAO_TOTAL_RULES_CANON_REF = "tiandao-total-rules-v1@2026-06-22"

CANON_STATUS_ACCEPTED = "canon_accepted"
PROOF_STATUS_NOT_APPLICABLE = "not_applicable"
RUNTIME_STATUS_NOT_CONNECTED = "not_connected"

_TIANDAO_TOTAL_RULES_SOURCE_REFS = (
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道正典索引_2026-06-22.md",
)

_TIANDAO_TOTAL_RULES_RECEIPT_REFS = (
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_合并回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_Opus工程边界审回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_南天门命运面复核回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第一条时间规则source_proven修订回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第二条时间规则source_proven修订回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第三条时间规则source_proven修订回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第四条时间规则source_proven修订回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第五条时间规则source_proven修订回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第六条时间规则source_proven修订回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第七条时间规则source_proven修订回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第八条时间规则source_proven修订回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第九条时间规则source_proven修订回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第十条时间规则source_proven修订回执_2026-06-22.md",
    "/Volumes/洪荒体系笔记/天道/天道总规则_v1_第十一条时间规则source_proven修订回执_2026-06-22.md",
)

_TIANDAO_CORE_SOURCE_REFS = (
    "/Volumes/洪荒体系笔记/天道核心_异种同源与源正典纪律_canon_draft_2026-06-22/01_天道核心_异种同源与源正典纪律_canon_draft.md",
    "/Volumes/洪荒体系笔记/天道核心_异种同源与源正典纪律_canon_draft_2026-06-22/08_canon_accepted_终裁回执.md",
)

_SOURCE_CANON_NON_CLAIMS = (
    "does_not_modify_runtime_behavior",
    "does_not_read_nas_at_import_or_runtime",
    "does_not_make_nas_a_build_or_run_dependency",
    "does_not_claim_source_code_integration",
    "does_not_claim_gate_passed",
    "does_not_claim_packaged_proof",
    "does_not_claim_time_twin_star_runtime_integrated",
    "does_not_claim_installed_runtime_time_rule_source_proven",
    "does_not_claim_platform_wide_runtime_delivery",
)

def tiandao_core_source_canon_contract() -> dict[str, Any]:
    return {
        "canon_ref": TIANDAO_CORE_CANON_REF,
        "title": "天道核心：异种同源与源正典纪律",
        "canon_status": CANON_STATUS_ACCEPTED,
        "proof_status": PROOF_STATUS_NOT_APPLICABLE,
        "runtime_status": RUNTIME_STATUS_NOT_CONNECTED,
        "owner": "想象者 / 天道正典",
        "maintainer": "忆凡尘代表",
        "source_refs": list(_TIANDAO_CORE_SOURCE_REFS),
        "receipt_refs": [
            "/Volumes/洪荒体系笔记/天道核心_异种同源与源正典纪律_canon_draft_2026-06-22/05_canon_candidate_状态回执.md",
            "/Volumes/洪荒体系笔记/天道核心_异种同源与源正典纪律_canon_draft_2026-06-22/06_Opus工程边界审_回执.md",
            "/Volumes/洪荒体系笔记/天道核心_异种同源与源正典纪律_canon_draft_2026-06-22/07_南天门命运动作边界审_回执.md",
            "/Volumes/洪荒体系笔记/天道核心_异种同源与源正典纪律_canon_draft_2026-06-22/08_canon_accepted_终裁回执.md",
        ],
        "source_layer_only": True,
        "runtime_connected": False,
        "nas_paths_are_audit_refs_only": True,
        "non_claims": list(_SOURCE_CANON_NON_CLAIMS),
    }


def tiandao_total_rules_v1_contract() -> dict[str, Any]:
    return {
        "canon_ref": TIANDAO_TOTAL_RULES_CANON_REF,
        "title": "天道总规则 v1",
        "canon_status": CANON_STATUS_ACCEPTED,
        "proof_status": PROOF_STATUS_NOT_APPLICABLE,
        "runtime_status": RUNTIME_STATUS_NOT_CONNECTED,
        "owner": "想象者 / 天道正典",
        "maintainer": "忆凡尘代表",
        "source_refs": list(_TIANDAO_TOTAL_RULES_SOURCE_REFS),
        "receipt_refs": list(_TIANDAO_TOTAL_RULES_RECEIPT_REFS),
        "source_layer_only": True,
        "runtime_connected": False,
        "source_code_connected": False,
        "gate_proven": False,
        "packaged_proven": False,
        "runtime_behavior_changed": False,
        "nas_paths_are_audit_refs_only": True,
        "nas_runtime_dependency": False,
        "build_run_dependency": False,
        "time_twin_star": time_twin_star_source_canon_entry(),
        "next_local_action": "time_twin_star_first_cut_after_local_source_canon_registry",
        "non_claims": list(_SOURCE_CANON_NON_CLAIMS),
    }


def tiandao_source_canon_registry() -> dict[str, Any]:
    return {
        "contract": TIANDAO_SOURCE_CANON_REGISTRY_CONTRACT,
        "registry_scope": "yifanchen_local_source_canon_mirror",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "nas_runtime_dependency": False,
        "build_run_dependency": False,
        "runtime_connected": False,
        "source_ref_policy": "nas_paths_are_audit_refs_only_not_import_or_runtime_dependencies",
        "entries": [
            tiandao_core_source_canon_contract(),
            tiandao_total_rules_v1_contract(),
        ],
        "non_claims": list(_SOURCE_CANON_NON_CLAIMS),
    }
