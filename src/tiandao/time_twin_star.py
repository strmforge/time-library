"""Read-only Time Twin Star projection for Yifanchen.

This module projects the existing time policies in ``memory_routing.py`` into
the Tiandao v1 TwinStar shape. It is deliberately read-only: it does not write
memory, change runtime routing, call models, or read NAS files.
"""

from __future__ import annotations

import json
import hashlib
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .memory_routing import (
    time_origin_contract_descriptor,
    time_river_contract_descriptor,
    time_river_sediment_contract_descriptor,
)


TIME_TWIN_STAR_SURFACE_CONTRACT = "time_tiandao_surface.v1"
TIME_RULES_CONTRACT = "time_rules.v1"
TIME_TWIN_STAR_PROJECTION_CONTRACT = "time_twin_star_read_only_projection.v1"
TIME_TWIN_STAR_RUNTIME_STATUS_CONTRACT = "time_twin_star_runtime_status.v1"
TIME_TWIN_STAR_INSTALLED_RUNTIME_PROBE_CONTRACT = "time_twin_star_installed_runtime_probe.v1"
TIME_TWIN_STAR_TURN_LOOP_PROBE_CONTRACT = "time_twin_star_turn_loop_probe.v1"
TIME_TWIN_STAR_TURN_LOOP_TRACE_GATE_CONTRACT = "time_twin_star_turn_loop_trace_gate.v1"
TIME_TWIN_STAR_PASSIVE_PUSH_TRACE_GATE_CONTRACT = "time_twin_star_passive_push_trace_gate.v1"
TIME_TWIN_STAR_SOURCE_FILE = "src/tiandao/memory_routing.py"
TIME_TWIN_STAR_RUNTIME_STATUS = "not_connected"
TIME_TWIN_STAR_IMPLEMENTATION_STATUS = "read_only_projection_present"
TIME_TWIN_STAR_SOURCE_RUNTIME_ROUTE_STATUS = "source_runtime_route_present"
TIME_TWIN_STAR_TURN_LOOP_PROBE_STATUS = "turn_loop_probe_present"
TIME_TWIN_STAR_TURN_LOOP_TRACE_GATE_STATUS = "turn_loop_trace_gate_present"
TIME_TWIN_STAR_PASSIVE_PUSH_TRACE_GATE_STATUS = "passive_push_trace_gate_present"
TIME_TWIN_STAR_AGENT_TURN_LOOP_STATUS = "agent_turn_loop_not_proven"
TIME_TWIN_STAR_TURN_LOOP_BEHAVIOR_STATUS = "turn_loop_behavior_not_proven"
TIME_TWIN_STAR_PASSIVE_PUSH_BEHAVIOR_STATUS = "passive_push_behavior_not_proven"
TIME_TWIN_STAR_STATUS_ENDPOINT = "/api/v1/tiandao/time-twin-star/status"
TIME_TWIN_STAR_DEFAULT_CONSOLE_URL = "http://127.0.0.1:9850"
TIME_TWIN_STAR_BEHAVIOR_PROOF_CONTRACT = "time_twin_star_behavior_proof_manifest.v1"
TIME_TWIN_STAR_BEHAVIOR_PROOF_MANIFEST = "src/tiandao/time_twin_star_behavior_proof.json"
_REPOSITORY_WORKING_DIRECTORY = str(Path(__file__).resolve().parents[2])

TIME_TWIN_STAR_SURFACES = ("time_origin", "time_river", "time_sediment")
TIME_TWIN_STAR_PRINCIPLES = (
    "时间起源于被见证的原始记录（raw）",
    "忆凡尘是河床，不是时间本身",
    "时间长河有起点，没有终点",
    "多机源流合并，不互相覆盖",
    "平台是入口，不是起源",
)

TIME_POLICY_FIELDS = (
    "raw_authority_policy",
    "origin_event_policy",
    "derived_sediment_policy",
    "local_runtime_policy",
    "multi_machine_policy",
    "platform_policy",
    "river_endpoint_policy",
    "origin_policy",
    "source_ref_policy",
    "origin_link_policy",
    "summary_policy",
    "time_order_policy",
    "write_policy",
)

_RULE_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "raw_is_highest_authority",
        "surface": "time_origin",
        "statement": "raw 原文是最高事实；派生层不得替代它。",
        "sourcePolicyFields": ["raw_authority_policy"],
    },
    {
        "id": "time_origin_is_witnessed_raw",
        "surface": "time_origin",
        "statement": "时间起源于 raw 被见证的那一刻。",
        "sourcePolicyFields": ["origin_event_policy"],
    },
    {
        "id": "derived_sediment_must_reference_origin",
        "surface": "time_sediment",
        "statement": "派生沉积必须能回指起源；断链则不得升为事实。",
        "sourcePolicyFields": ["derived_sediment_policy", "origin_link_policy"],
        "dedupNote": "同一规则在 origin 与 sediment 两个 descriptor 各有一处，去重为一条。",
    },
    {
        "id": "each_runtime_first_witnessed_raw",
        "surface": "time_origin",
        "statement": "每个运行时的时间起源 = 它第一条被见证的 raw 事件。",
        "sourcePolicyFields": ["local_runtime_policy"],
    },
    {
        "id": "source_streams_merge_not_overwrite",
        "surface": "time_origin",
        "statement": "多机源流合并，不互相覆盖。",
        "sourcePolicyFields": ["multi_machine_policy"],
    },
    {
        "id": "platforms_are_inlets_not_origin",
        "surface": "time_origin",
        "statement": "平台是入口，不是起源/不是河法。",
        "sourcePolicyFields": ["platform_policy"],
    },
    {
        "id": "river_begins_at_origin_event",
        "surface": "time_river",
        "statement": "时间长河始于 raw 起源事件。",
        "sourcePolicyFields": ["origin_policy"],
    },
    {
        "id": "time_river_has_no_endpoint",
        "surface": "time_river",
        "statement": "时间长河有起点，没有终点。",
        "sourcePolicyFields": ["river_endpoint_policy"],
    },
    {
        "id": "events_remain_orderable",
        "surface": "time_river",
        "statement": "时间事件必须能按 event_time 与 audit_time 保持可排序。",
        "sourcePolicyFields": ["time_order_policy"],
        "classificationRuling": "time_order_policy belongs to the time river surface, not unclassified.",
    },
    {
        "id": "source_refs_required_not_replacement",
        "surface": "time_sediment",
        "statement": "source_refs 必须有，但不能替代原文；回不到源就声明 unavailable。",
        "sourcePolicyFields": ["source_ref_policy"],
    },
    {
        "id": "summaries_are_navigation_not_source",
        "surface": "time_sediment",
        "statement": "摘要是导航，不是原文替代品。",
        "sourcePolicyFields": ["summary_policy"],
    },
    {
        "id": "unknown_when_no_origin_link",
        "surface": "time_sediment",
        "statement": "无 origin link 时必须 UNKNOWN，不得以'记得像'冒充'有证据'。",
        "sourcePolicyFields": ["derived_sediment_policy"],
        "alsoFrom": "sediment candidate_statuses (untrusted)",
    },
    {
        "id": "read_only_descriptor_no_write",
        "surface": "time_sediment",
        "statement": "沉积链是只读描述符，不写记忆。",
        "sourcePolicyFields": ["write_policy"],
    },
)

_CANDIDATE_EVIDENCE_COMMAND = (
    "python3 tools/trusted_memory_trust_metrics.py --json "
    "--user-work-casefile <case> --user-work-casefile-repeat 2"
)
_RAW_IS_HIGHEST_AUTHORITY_EVIDENCE_COMMAND = (
    "python3 -m pytest -q "
    "tests/test_raw_archive_verbatim.py::test_openclaw_raw_archive_preserves_platform_record_verbatim "
    "tests/test_saved_content_verbatim_pipeline.py::test_p3_recall_keeps_saved_detail_verbatim_in_injection "
    "tests/test_saved_content_verbatim_pipeline.py::test_p3_recall_does_not_block_saved_user_secret_like_words "
    "tests/test_zhixing_library.py::test_zhixing_library_preserves_verbatim_excerpt_without_redaction "
    "tests/test_zhixing_library.py::test_library_admission_candidate_requires_source_refs_and_verbatim_excerpt "
    "tests/test_context_delivery_compaction.py::test_context_delivery_compaction_contract_is_delivery_only "
    "tests/test_context_delivery_compaction.py::test_context_delivery_compaction_recommends_log_compaction_with_source_refs "
    "tests/test_memory_authority_policy.py::test_memory_authority_defaults_to_passive "
    "tests/test_memory_authority_policy.py::test_memory_authority_policy_documents_installed_scoped_recall_boundary"
)
_SOURCE_REFS_NOT_REPLACEMENT_EVIDENCE_COMMAND = (
    "python3 -m pytest -q tests/test_delivery_receipt.py "
    "tests/test_search_think_dry_run.py "
    "tests/test_evidence_atom_vocabulary.py "
    "tests/test_time_river_sediment.py"
)
_DERIVED_SEDIMENT_REFERENCE_ORIGIN_EVIDENCE_COMMAND = (
    "python3 -m pytest -q "
    "tests/test_time_river_sediment.py "
    "tests/test_code_change_tiandao_source.py::test_code_change_tiandao_source_reports_dirty_worktree_without_writing "
    "tests/test_code_change_tiandao_source.py::test_code_change_tiandao_source_can_include_verification_output_refs "
    "tests/test_code_change_tiandao_source.py::test_code_change_tiandao_source_clean_repo_is_still_read_only "
    "tests/test_code_change_tiandao_source.py::test_code_change_tiandao_source_non_git_archive_is_non_blocking_read_only"
)
_UNKNOWN_WHEN_NO_ORIGIN_LINK_EVIDENCE_COMMAND = (
    "python3 -m pytest -q "
    "tests/test_evidence_bound_model.py::test_no_evidence_returns_unknown_without_model_call "
    "tests/test_evidence_bound_model.py::test_fake_client_hallucinated_ref_is_rejected_to_unknown "
    "tests/test_evidence_bound_model.py::test_answer_without_supporting_refs_is_rejected "
    "tests/test_search_think_dry_run.py::test_search_think_no_evidence_returns_unknown_without_model_call "
    "tests/test_search_think_dry_run.py::test_search_think_default_dry_run_does_not_call_model_and_preserves_gap "
    "tests/test_search_think_dry_run.py::test_search_think_hallucinated_model_ref_is_rejected_to_unknown "
    "tests/test_search_think_dry_run.py::test_local_fallback_answer_cannot_become_think_answer "
    "tests/test_time_river_sediment.py::test_time_river_sediment_keeps_source_refs_only_as_candidate "
    "tests/test_time_river_sediment.py::test_time_river_sediment_marks_lost_raw_untrusted "
    "tests/test_time_river_sediment.py::test_time_river_sediment_without_origin_or_source_refs_is_untrusted_candidate"
)
_SUMMARIES_ARE_NAVIGATION_EVIDENCE_COMMAND = (
    "python3 -m pytest -q "
    "tests/test_time_river_sediment.py::test_time_river_sediment_links_derived_memory_to_raw_origin "
    "tests/test_source_ref_compact_evidence.py::test_source_ref_compact_evidence_reads_bounded_raw_for_model_only "
    "tests/test_source_ref_compact_evidence.py::test_source_ref_compact_evidence_missing_file_remains_candidate_only "
    "tests/test_work_preflight_search_think_probe.py::test_evidence_items_from_work_preflight_response_uses_compact_surfaces_only "
    "tests/test_work_preflight_search_think_probe.py::test_evidence_items_from_work_preflight_response_backtraces_source_ref "
    "tests/test_context_delivery_compaction.py::test_context_delivery_compaction_recommends_log_compaction_with_source_refs "
    "tests/test_context_delivery_compaction.py::test_context_delivery_compaction_requires_source_refs_for_reversible_drop "
    "tests/test_zhixing_context_unit.py::test_context_budget_unit_candidate_is_source_backed_and_review_only "
    "tests/test_zhixing_library.py::test_library_admission_candidate_requires_source_refs_and_verbatim_excerpt"
)
_READ_ONLY_DESCRIPTOR_NO_WRITE_EVIDENCE_COMMAND = (
    "python3 -m pytest -q "
    "tests/test_time_twin_star.py::test_time_twin_star_projection_matches_tiandao_v1_shape "
    "tests/test_time_twin_star.py::test_time_twin_star_consistency_preserves_proof_discipline "
    "tests/test_time_twin_star.py::test_time_twin_star_import_does_not_touch_nas_paths "
    "tests/test_time_river_sediment.py::test_time_river_sediment_dry_run_is_read_only "
    "tests/test_tiandao_source_canon.py::test_tiandao_source_canon_registry_keeps_nas_as_audit_refs_only "
    "tests/test_tiandao_source_canon.py::test_source_canon_import_does_not_touch_nas_paths"
)
_TIME_ORIGIN_IS_WITNESSED_RAW_EVIDENCE_COMMAND = (
    "python3 -m pytest -q "
    "tests/test_raw_origin_event.py::test_raw_origin_event_is_stable_and_raw_is_time_origin "
    "tests/test_raw_record_guardian.py::test_raw_record_guardian_reports_record_guarded_after_raw_mirror "
    "tests/test_raw_record_guardian.py::test_canonical_record_index_stores_codex_offsets_and_chunks "
    "tests/test_tiandao_merge.py::test_tiandao_python_exports_nantianmen_promoted_contracts"
)
_EACH_RUNTIME_FIRST_WITNESSED_RAW_EVIDENCE_COMMAND = (
    "python3 -m pytest -q "
    "tests/test_raw_origin_event.py::test_origin_summary_reports_first_witnessed_raw_per_local_runtime "
    "tests/test_raw_origin_event.py::test_raw_origin_event_is_stable_and_raw_is_time_origin "
    "tests/test_tiandao_merge.py::test_tiandao_python_exports_nantianmen_promoted_contracts"
)
_RIVER_BEGINS_AT_ORIGIN_EVENT_EVIDENCE_COMMAND = (
    "python3 -m pytest -q "
    "tests/test_raw_origin_event.py::test_raw_origin_event_is_stable_and_raw_is_time_origin "
    "tests/test_tiandao_merge.py::test_tiandao_python_exports_nantianmen_promoted_contracts "
    "tests/test_tiandao_merge.py::test_tiandao_schema_and_ts_sources_preserve_neutral_contract_names "
    "tests/test_time_river_sediment.py::test_time_river_sediment_links_derived_memory_to_raw_origin"
)
_PLATFORMS_ARE_INLETS_NOT_ORIGIN_EVIDENCE_COMMAND = (
    "python3 -m pytest -q "
    "tests/test_raw_origin_event.py::test_platform_source_system_is_inlet_not_time_origin "
    "tests/test_tiandao_merge.py::test_tiandao_python_exports_nantianmen_promoted_contracts "
    "tests/test_tiandao_merge.py::test_tiandao_schema_and_ts_sources_preserve_neutral_contract_names"
)
_EVENTS_REMAIN_ORDERABLE_EVIDENCE_COMMAND = (
    "python3 -m pytest -q "
    "tests/test_raw_record_guardian.py::test_origin_events_remain_orderable_by_event_time_and_audit_time "
    "tests/test_raw_origin_event.py::test_raw_origin_event_is_stable_and_raw_is_time_origin "
    "tests/test_tiandao_merge.py::test_tiandao_python_exports_nantianmen_promoted_contracts"
)

_RULE_BINDINGS: tuple[dict[str, Any], ...] = (
    {
        "ruleId": "raw_is_highest_authority",
        "surfaces": ["time_origin"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _RAW_IS_HIGHEST_AUTHORITY_EVIDENCE_COMMAND,
        "evidenceMetric": "raw_is_highest_authority=9/9 tests passed",
        "evidenceRefs": [
            "tests/test_raw_archive_verbatim.py",
            "tests/test_saved_content_verbatim_pipeline.py",
            "tests/test_zhixing_library.py",
            "tests/test_context_delivery_compaction.py",
            "tests/test_memory_authority_policy.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第五条source_proven_raw_authority回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称 installed_runtime 信任指标已由本条证明",
            "不宣称全平台或全记录已覆盖",
            "不宣称所有 raw 入口或所有保存路径已穷尽",
        ],
    },
    {
        "ruleId": "derived_sediment_must_reference_origin",
        "surfaces": ["time_sediment"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _DERIVED_SEDIMENT_REFERENCE_ORIGIN_EVIDENCE_COMMAND,
        "evidenceMetric": "derived_sediment_must_reference_origin=9/9 tests passed",
        "evidenceRefs": [
            "tests/test_time_river_sediment.py",
            "tests/test_code_change_tiandao_source.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第四条source_proven_derived_origin回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称 installed_runtime 信任指标已由本条证明",
            "不宣称全平台或全记录已覆盖",
            "不宣称所有派生沉积路径已穷尽",
        ],
    },
    {
        "ruleId": "source_refs_required_not_replacement",
        "surfaces": ["time_sediment"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _SOURCE_REFS_NOT_REPLACEMENT_EVIDENCE_COMMAND,
        "evidenceMetric": "source_refs_required_not_replacement=15/15 tests passed",
        "evidenceRefs": [
            "tests/test_delivery_receipt.py",
            "tests/test_search_think_dry_run.py",
            "tests/test_evidence_atom_vocabulary.py",
            "tests/test_time_river_sediment.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第一条source_proven_source_refs回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称全平台或全记录已覆盖",
            "不宣称 installed_runtime 信任指标已由本条证明",
        ],
    },
    {
        "ruleId": "summaries_are_navigation_not_source",
        "surfaces": ["time_sediment"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _SUMMARIES_ARE_NAVIGATION_EVIDENCE_COMMAND,
        "evidenceMetric": "summaries_are_navigation_not_source=9/9 tests passed",
        "evidenceRefs": [
            "tests/test_time_river_sediment.py",
            "tests/test_source_ref_compact_evidence.py",
            "tests/test_work_preflight_search_think_probe.py",
            "tests/test_context_delivery_compaction.py",
            "tests/test_zhixing_context_unit.py",
            "tests/test_zhixing_library.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第三条source_proven_summary回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称 installed_runtime 信任指标已由本条证明",
            "不宣称全平台或全记录已覆盖",
            "不宣称所有摘要/压缩路径已穷尽",
        ],
    },
    {
        "ruleId": "unknown_when_no_origin_link",
        "surfaces": ["time_sediment"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _UNKNOWN_WHEN_NO_ORIGIN_LINK_EVIDENCE_COMMAND,
        "evidenceMetric": "unknown_when_no_origin_link=10/10 tests passed",
        "evidenceRefs": [
            "tests/test_evidence_bound_model.py",
            "tests/test_search_think_dry_run.py",
            "tests/test_time_river_sediment.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第二条source_proven_unknown回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称 installed_runtime 信任指标已由本条证明",
            "不宣称全平台或全记录已覆盖",
            "不宣称所有 UNKNOWN 场景已穷尽",
        ],
    },
    {
        "ruleId": "time_origin_is_witnessed_raw",
        "surfaces": ["time_origin"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _TIME_ORIGIN_IS_WITNESSED_RAW_EVIDENCE_COMMAND,
        "evidenceMetric": "time_origin_is_witnessed_raw=4/4 tests passed",
        "evidenceRefs": [
            "tests/test_raw_origin_event.py",
            "tests/test_raw_record_guardian.py",
            "tests/test_tiandao_merge.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第七条source_proven_time_origin_witnessed_raw回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称 installed_runtime 信任指标已由本条证明",
            "不宣称全平台或全记录已覆盖",
            "不宣称所有 raw 入口或所有 guardian/index 路径已穷尽",
        ],
    },
    {
        "ruleId": "river_begins_at_origin_event",
        "surfaces": ["time_river"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _RIVER_BEGINS_AT_ORIGIN_EVENT_EVIDENCE_COMMAND,
        "evidenceMetric": "river_begins_at_origin_event=4/4 tests passed",
        "evidenceRefs": [
            "tests/test_raw_origin_event.py",
            "tests/test_tiandao_merge.py",
            "tests/test_time_river_sediment.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第八条source_proven_river_begins_at_origin_event回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称 installed_runtime 信任指标已由本条证明",
            "不宣称全平台或全记录已覆盖",
            "不宣称 time_river_has_no_endpoint 公理已由本条测试证明",
            "不宣称所有时间长河入口或所有沉积链路径已穷尽",
        ],
    },
    {
        "ruleId": "each_runtime_first_witnessed_raw",
        "surfaces": ["time_origin"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _EACH_RUNTIME_FIRST_WITNESSED_RAW_EVIDENCE_COMMAND,
        "evidenceMetric": "each_runtime_first_witnessed_raw=3/3 tests passed",
        "evidenceRefs": [
            "src/raw_origin_event.py",
            "tests/test_raw_origin_event.py",
            "tests/test_tiandao_merge.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第十一条source_proven_each_runtime_first_raw回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称 installed_runtime 信任指标已由本条证明",
            "不宣称全平台或全记录已覆盖",
            "不宣称所有 runtime/source_system 分组或所有机器已穷尽",
            "不宣称多机源流合并已由本条证明",
            "不宣称 source_streams_merge_not_overwrite 已由本条证明",
        ],
    },
    {
        "ruleId": "platforms_are_inlets_not_origin",
        "surfaces": ["time_origin"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _PLATFORMS_ARE_INLETS_NOT_ORIGIN_EVIDENCE_COMMAND,
        "evidenceMetric": "platforms_are_inlets_not_origin=3/3 tests passed",
        "evidenceRefs": [
            "tests/test_raw_origin_event.py",
            "tests/test_tiandao_merge.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第九条source_proven_platform_inlet回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称 installed_runtime 信任指标已由本条证明",
            "不宣称全平台或全记录已覆盖",
            "不宣称所有平台、入口或适配器路径已穷尽",
            "不宣称平台动作权限或平台送达由本条证明",
        ],
    },
    {
        "ruleId": "read_only_descriptor_no_write",
        "surfaces": ["time_sediment"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _READ_ONLY_DESCRIPTOR_NO_WRITE_EVIDENCE_COMMAND,
        "evidenceMetric": "read_only_descriptor_no_write=6/6 tests passed",
        "evidenceRefs": [
            "tests/test_time_twin_star.py",
            "tests/test_time_river_sediment.py",
            "tests/test_tiandao_source_canon.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第六条source_proven_read_only_descriptor回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称 installed_runtime 信任指标已由本条证明",
            "不宣称全平台或全记录已覆盖",
            "不宣称所有只读路径或所有导入路径已穷尽",
        ],
    },
    {
        "ruleId": "time_river_has_no_endpoint",
        "surfaces": ["time_river"],
        "currentStatus": "contract_only",
        "note": "公理 axiom",
    },
    {
        "ruleId": "events_remain_orderable",
        "surfaces": ["time_river"],
        "currentStatus": "source_proven",
        "proofScope": "repository_behavior",
        "workingDirectory": _REPOSITORY_WORKING_DIRECTORY,
        "runtimeTarget": "repository-tests",
        "evidenceCommand": _EVENTS_REMAIN_ORDERABLE_EVIDENCE_COMMAND,
        "evidenceMetric": "events_remain_orderable=3/3 tests passed",
        "evidenceRefs": [
            "src/raw_record_canonical_index.py",
            "tests/test_raw_record_guardian.py",
            "tests/test_raw_origin_event.py",
            "tests/test_tiandao_merge.py",
            "/Volumes/洪荒体系笔记/天道/时间双子星第十条source_proven_events_orderable回执_2026-06-22.md",
        ],
        "nonClaims": [
            "不宣称忆凡尘运行态已接入时间双子星",
            "不宣称平台送达已 proven",
            "不宣称 installed_runtime 信任指标已由本条证明",
            "不宣称全平台或全记录已覆盖",
            "不宣称所有 origin_events 查询路径或排序场景已穷尽",
            "不宣称事件时间本身的真实性已由本条证明",
        ],
    },
    {
        "ruleId": "source_streams_merge_not_overwrite",
        "surfaces": ["time_origin"],
        "currentStatus": "planned",
        "note": "多机合并未单证",
    },
)

_SOURCE_POLICY_CLASSIFICATIONS: tuple[dict[str, Any], ...] = (
    {
        "policyField": "adapter_boundary_policy",
        "classification": "cross_surface_adapter_boundary",
        "ownerSurface": "adapter_boundary",
        "ruling": "not_time_rule",
        "reason": "平台私有协议边界归薄适配层，不作为时间双子星规则新增。",
    },
    {
        "policyField": "audit_policy",
        "classification": "audit_receipt_surface",
        "ownerSurface": "audit_event",
        "ruling": "not_time_rule",
        "reason": "读写、送达、scope 决策回执归审计面，不作为时间双子星规则新增。",
    },
    {
        "policyField": "context_delivery_policy",
        "classification": "context_delivery_surface",
        "ownerSurface": "context_package",
        "ruling": "not_time_rule",
        "reason": "上下文包的 scope、ttl、purpose、source_refs 归送达合同，不作为时间双子星规则新增。",
    },
    {
        "policyField": "endpoint_policy",
        "classification": "covered_time_endpoint_alias",
        "ownerSurface": "time_river",
        "ruling": "covered_by_existing_time_rule",
        "coveredByRule": "time_river_has_no_endpoint",
        "coveredBySourcePolicyField": "river_endpoint_policy",
        "reason": "该字段与 river_endpoint_policy 同值，已由 time_river_has_no_endpoint 覆盖，不新增第 14 条规则。",
    },
    {
        "policyField": "global_recall_policy",
        "classification": "recall_authority_surface",
        "ownerSurface": "memory_authority",
        "ruling": "not_time_rule",
        "reason": "全局召回 explicit_only 属召回权限边界，不作为时间双子星规则新增。",
    },
    {
        "policyField": "library_identity_policy",
        "classification": "library_identity_surface",
        "ownerSurface": "library_identity",
        "ruling": "not_time_rule",
        "reason": "稳定馆藏身份归图书馆/馆藏身份治理，不作为时间双子星规则新增。",
    },
    {
        "policyField": "lifecycle_policy",
        "classification": "sediment_lifecycle_surface",
        "ownerSurface": "sediment_lifecycle",
        "ruling": "not_time_rule",
        "boundaryConfirmation": "沉积生命周期挨着时间沉积面，但它描述 candidate/review/adopt/deprecate/supersede 的治理状态，不是时间律不变量。",
        "reason": "candidate/review/adopted/deprecated/superseded 是沉积生命周期治理状态，不作为时间双子星规则新增。",
    },
    {
        "policyField": "platform_capability_policy",
        "classification": "platform_capability_surface",
        "ownerSurface": "capability_exchange",
        "ruling": "not_time_rule",
        "reason": "平台可使用中性能力子集归能力交换面，不作为时间双子星规则新增。",
    },
)


def _is_pending_ref(refs: Any) -> bool:
    if not refs:
        return True
    return any("pending" in str(ref).lower() or "待补" in str(ref) for ref in refs)


def _join_url(base_url: str, path: str) -> str:
    base = str(base_url or TIME_TWIN_STAR_DEFAULT_CONSOLE_URL).rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


def _http_get_json(
    url: str,
    *,
    timeout_seconds: float,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    open_fn = opener or urllib.request.urlopen
    request = urllib.request.Request(url, method="GET")
    try:
        with open_fn(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
            body = response.read()
            text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
        try:
            payload = json.loads(text) if text else {}
        except json.JSONDecodeError:
            payload = {}
        return {
            "ok": 200 <= status_code < 300,
            "reachable": True,
            "status_code": status_code,
            "json_ok": isinstance(payload, dict),
            "payload": payload if isinstance(payload, dict) else {},
            "body_preview": " ".join(text.split())[:500],
            "error": "",
        }
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        return {
            "ok": False,
            "reachable": True,
            "status_code": int(exc.code),
            "json_ok": False,
            "payload": {},
            "body_preview": " ".join(text.split())[:500],
            "error": f"HTTPError: {exc.code}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "reachable": False,
            "status_code": 0,
            "json_ok": False,
            "payload": {},
            "body_preview": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _repo_path(relative_path: str) -> Path:
    return Path(__file__).resolve().parents[2] / relative_path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _time_policy_values_from_descriptors() -> dict[str, list[str]]:
    values: dict[str, set[str]] = {}
    for descriptor in (
        time_origin_contract_descriptor(),
        time_river_contract_descriptor(),
        time_river_sediment_contract_descriptor(),
    ):
        for key, value in descriptor.items():
            if key.endswith("_policy"):
                values.setdefault(key, set()).add(str(value))
    return {key: sorted(found_values) for key, found_values in sorted(values.items())}


def time_twin_star_rule_definitions() -> list[dict[str, Any]]:
    return deepcopy(list(_RULE_DEFINITIONS))


def time_twin_star_rule_bindings() -> list[dict[str, Any]]:
    return deepcopy(list(_RULE_BINDINGS))


def time_twin_star_policy_classifications() -> list[dict[str, Any]]:
    return deepcopy(list(_SOURCE_POLICY_CLASSIFICATIONS))


def time_twin_star_status_counts() -> dict[str, int]:
    counts = {
        "candidate_source_proven": 0,
        "contract_only": 0,
        "planned": 0,
        "source_proven": 0,
    }
    for binding in _RULE_BINDINGS:
        status = str(binding.get("currentStatus", ""))
        counts[status] = counts.get(status, 0) + 1
    return counts


def time_twin_star_consistency_report() -> dict[str, Any]:
    source_policy_values = _time_policy_values_from_descriptors()
    declared_fields = set(TIME_POLICY_FIELDS)
    source_fields = set(source_policy_values)
    source_policy_classifications = {
        classification["policyField"]: classification for classification in _SOURCE_POLICY_CLASSIFICATIONS
    }
    outside_time_rule_fields = source_fields - declared_fields
    definitions = {definition["id"]: definition for definition in _RULE_DEFINITIONS}
    bindings = {binding["ruleId"]: binding for binding in _RULE_BINDINGS}
    referenced_fields = {
        field
        for definition in _RULE_DEFINITIONS
        for field in definition.get("sourcePolicyFields", [])
    }
    errors: list[str] = []
    warnings: list[str] = []

    for field in sorted(declared_fields - source_fields):
        errors.append(f"invented_field:{field}")
    for field in sorted(declared_fields - referenced_fields):
        errors.append(f"unreferenced_declared_field:{field}")
    for field in sorted(outside_time_rule_fields - set(source_policy_classifications)):
        errors.append(f"source_policy_without_classification:{field}")
    for field in sorted(set(source_policy_classifications) - outside_time_rule_fields):
        errors.append(f"stale_source_policy_classification:{field}")
    for definition in _RULE_DEFINITIONS:
        for field in definition.get("sourcePolicyFields", []):
            if field not in source_fields:
                errors.append(f"invented_rule_field:{definition['id']}:{field}")
    for rule_id in sorted(set(definitions) - set(bindings)):
        errors.append(f"missing_binding:{rule_id}")
    for rule_id in sorted(set(bindings) - set(definitions)):
        errors.append(f"binding_without_definition:{rule_id}")

    for field, classification in source_policy_classifications.items():
        covered_rule = classification.get("coveredByRule")
        covered_field = classification.get("coveredBySourcePolicyField")
        if covered_rule and covered_rule not in definitions:
            errors.append(f"classification_unknown_rule:{field}:{covered_rule}")
        if covered_field:
            if covered_field not in source_policy_values:
                errors.append(f"classification_unknown_source_field:{field}:{covered_field}")
            elif source_policy_values.get(field) != source_policy_values.get(covered_field):
                errors.append(f"classification_alias_value_mismatch:{field}:{covered_field}")

    for rule_id, binding in bindings.items():
        status = str(binding.get("currentStatus", ""))
        if status == "source_proven":
            for required in ("proofScope", "workingDirectory", "runtimeTarget", "evidenceCommand", "nonClaims"):
                if not binding.get(required):
                    errors.append(f"source_proven_missing:{rule_id}:{required}")
            if _is_pending_ref(binding.get("evidenceRefs")):
                errors.append(f"source_proven_pending_refs:{rule_id}")
        elif status == "candidate_source_proven":
            if not binding.get("evidenceCommand"):
                warnings.append(f"candidate_missing_evidence_command:{rule_id}")
            if not _is_pending_ref(binding.get("evidenceRefs")):
                warnings.append(f"candidate_refs_present_consider_source_proven:{rule_id}")

    return {
        "ok": not errors,
        "contract": TIME_TWIN_STAR_PROJECTION_CONTRACT,
        "source_file": TIME_TWIN_STAR_SOURCE_FILE,
        "declared_time_policy_count": len(declared_fields),
        "source_policy_count": len(source_fields),
        "rule_definition_count": len(definitions),
        "rule_binding_count": len(bindings),
        "status_counts": time_twin_star_status_counts(),
        "missing_declared_policy_fields": sorted(declared_fields - source_fields),
        "unreferenced_declared_policy_fields": sorted(declared_fields - referenced_fields),
        "source_policies_not_declared_as_time_rules": sorted(outside_time_rule_fields),
        "source_policies_outside_time_rules": sorted(outside_time_rule_fields),
        "unclassified_source_policies": sorted(outside_time_rule_fields),
        "unclassified_source_policies_legacy_alias": True,
        "unclassified_source_policies_replaced_by": "source_policies_not_declared_as_time_rules",
        "source_policy_classifications": time_twin_star_policy_classifications(),
        "source_policies_without_classification": sorted(outside_time_rule_fields - set(source_policy_classifications)),
        "stale_source_policy_classifications": sorted(set(source_policy_classifications) - outside_time_rule_fields),
        "source_policy_classification_status": "all_source_policies_classified_or_covered",
        "source_policy_values": source_policy_values,
        "errors": errors,
        "warnings": warnings,
        "read_only": True,
        "runtime_behavior_changed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "nas_runtime_dependency": False,
        "source_proven_requires_complete_evidence_refs": True,
    }


def time_twin_star_projection() -> dict[str, Any]:
    report = time_twin_star_consistency_report()
    return {
        "lawId": "time",
        "owner": "yifanchen",
        "twinStar": {
            "surfaceContract": TIME_TWIN_STAR_SURFACE_CONTRACT,
            "rulesContract": TIME_RULES_CONTRACT,
        },
        "status": "READ_ONLY_PROJECTION",
        "implementation_status": TIME_TWIN_STAR_IMPLEMENTATION_STATUS,
        "runtime_status": TIME_TWIN_STAR_RUNTIME_STATUS,
        "statusNote": (
            "时间双子星第一刀只读投影已在忆凡尘本体落地；"
            "不改运行行为，不视为运行态接入。"
        ),
        "surfaces": list(TIME_TWIN_STAR_SURFACES),
        "principles": list(TIME_TWIN_STAR_PRINCIPLES),
        "sourceFile": TIME_TWIN_STAR_SOURCE_FILE,
        "timePolicyFields": list(TIME_POLICY_FIELDS),
        "sourcePolicyClassifications": time_twin_star_policy_classifications(),
        "ruleDefinitions": time_twin_star_rule_definitions(),
        "ruleBindings": time_twin_star_rule_bindings(),
        "consistency": report,
        "read_only": True,
        "runtime_behavior_changed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "nas_runtime_dependency": False,
        "non_claims": [
            "does_not_change_runtime_behavior",
            "does_not_write_memory",
            "does_not_read_nas",
            "does_not_claim_any_installed_runtime_time_rule_source_proven",
            "does_not_claim_platform_delivery_proven",
            "does_not_claim_packaged_proof",
        ],
    }


def _behavior_proof_trace(payload: dict[str, Any]) -> dict[str, Any]:
    trace = payload.get("trace")
    return trace if isinstance(trace, dict) else payload


def _load_time_twin_star_behavior_proof(
    proof_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(proof_manifest_path) if proof_manifest_path else _repo_path(TIME_TWIN_STAR_BEHAVIOR_PROOF_MANIFEST)
    base: dict[str, Any] = {
        "contract": TIME_TWIN_STAR_BEHAVIOR_PROOF_CONTRACT,
        "manifest_path": str(path),
        "manifest_present": False,
        "manifest_sha256": "",
        "proof_status": "not_proven",
        "trace_sufficient_for_behavior_proven": False,
        "turn_loop_behavior_status": TIME_TWIN_STAR_TURN_LOOP_BEHAVIOR_STATUS,
        "agent_turn_loop_status": TIME_TWIN_STAR_AGENT_TURN_LOOP_STATUS,
        "proof_scope": "",
        "source_proven_scope": "repository_behavior_only",
        "gate": {},
        "non_claims": [
            "does_not_claim_behavior_proven_without_external_real_trace",
            "does_not_read_nas_at_runtime",
        ],
    }
    if not path.exists():
        return {**base, "manifest_status": "missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {**base, "manifest_present": True, "manifest_status": "invalid_json", "error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(payload, dict):
        return {**base, "manifest_present": True, "manifest_status": "invalid_shape"}

    gate = time_twin_star_turn_loop_trace_gate_from_observation(payload)
    trace = _behavior_proof_trace(payload)
    sufficient = bool(gate.get("trace_sufficient_for_behavior_proven")) and payload.get("proof_status") == "behavior_proven"
    return {
        **base,
        "manifest_present": True,
        "manifest_status": "ok" if sufficient else "gate_rejected",
        "manifest_sha256": _file_sha256(path),
        "proof_status": "behavior_proven" if sufficient else "not_proven",
        "trace_sufficient_for_behavior_proven": sufficient,
        "turn_loop_behavior_status": str(gate.get("turn_loop_behavior_status") or TIME_TWIN_STAR_TURN_LOOP_BEHAVIOR_STATUS),
        "agent_turn_loop_status": str(gate.get("agent_turn_loop_status") or TIME_TWIN_STAR_AGENT_TURN_LOOP_STATUS),
        "proof_scope": str(payload.get("proof_scope") or trace.get("proof_scope") or ""),
        "source_proven_scope": str(payload.get("source_proven_scope") or "repository_behavior_plus_controlled_openclaw_smoke")
        if sufficient
        else "repository_behavior_only",
        "trace_id": str(trace.get("trace_id") or ""),
        "trace_kind": str(trace.get("trace_kind") or ""),
        "trace_source": str(trace.get("source") or ""),
        "gate": {
            "contract": gate.get("contract"),
            "gate_status": gate.get("gate_status"),
            "missing_observations": gate.get("missing_observations") or [],
            "forbidden_substitutes_present": gate.get("forbidden_substitutes_present") or [],
        },
        "evidence": payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {},
        "non_claims": payload.get("non_claims") if isinstance(payload.get("non_claims"), list) else base["non_claims"],
    }


def time_twin_star_runtime_status(
    *,
    proof_manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    projection = time_twin_star_projection()
    consistency = projection["consistency"]
    behavior_proof = _load_time_twin_star_behavior_proof(proof_manifest_path)
    behavior_proven = bool(behavior_proof.get("trace_sufficient_for_behavior_proven"))
    non_claims = [
        "does_not_read_nas_at_runtime",
        "does_not_write_raw_memory_or_platform_state",
    ]
    if behavior_proven:
        non_claims.extend(
            [
                "does_not_claim_platform_wide_delivery",
                "does_not_claim_hermes_delivery",
                "does_not_claim_all_time_rules_behavior",
                "does_not_claim_cross_machine_or_release_behavior",
            ]
        )
    else:
        non_claims.extend(
            [
                "does_not_claim_installed_runtime_updated",
                "does_not_claim_platform_delivery_proven",
                "does_not_claim_time_twin_star_active_in_agent_loop",
            ]
        )
    return {
        "ok": bool(consistency.get("ok")),
        "contract": TIME_TWIN_STAR_RUNTIME_STATUS_CONTRACT,
        "projection_contract": TIME_TWIN_STAR_PROJECTION_CONTRACT,
        "source_runtime_route_status": TIME_TWIN_STAR_SOURCE_RUNTIME_ROUTE_STATUS,
        "runtime_status": TIME_TWIN_STAR_SOURCE_RUNTIME_ROUTE_STATUS,
        "installed_runtime_status": "proven" if behavior_proven else "not_proven",
        "platform_delivery_status": "proven" if behavior_proven else "not_proven",
        "platform_delivery_scope": behavior_proof.get("proof_scope") if behavior_proven else "",
        "agent_turn_loop_status": behavior_proof.get("agent_turn_loop_status"),
        "turn_loop_behavior_status": behavior_proof.get("turn_loop_behavior_status"),
        "source_proven_scope": behavior_proof.get("source_proven_scope"),
        "runtimeTarget": "p6-console-source-route",
        "endpoint": "/api/v1/tiandao/time-twin-star/status",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "network_call_performed": False,
        "runtime_behavior_changed": behavior_proven,
        "nas_runtime_dependency": False,
        "behavior_proof": behavior_proof,
        "rule_status_counts": consistency["status_counts"],
        "source_proven_rules": [
            binding["ruleId"]
            for binding in projection["ruleBindings"]
            if binding.get("currentStatus") == "source_proven"
        ],
        "contract_only_rules": [
            binding["ruleId"]
            for binding in projection["ruleBindings"]
            if binding.get("currentStatus") == "contract_only"
        ],
        "planned_rules": [
            binding["ruleId"]
            for binding in projection["ruleBindings"]
            if binding.get("currentStatus") == "planned"
        ],
        "consistency": {
            "ok": consistency["ok"],
            "errors": list(consistency["errors"]),
            "warnings": list(consistency["warnings"]),
            "source_policies_without_classification": list(consistency["source_policies_without_classification"]),
        },
        "non_claims": non_claims
        + [
            "does_not_claim_time_river_has_no_endpoint_source_proven",
            "does_not_claim_source_streams_merge_not_overwrite_source_proven",
        ],
    }


def time_twin_star_turn_loop_definition_of_proven() -> dict[str, Any]:
    """Return the two-step proof boundary for Time Twin Star turn-loop work."""

    return {
        "ok": True,
        "contract": TIME_TWIN_STAR_TURN_LOOP_PROBE_CONTRACT,
        "current_target": TIME_TWIN_STAR_TURN_LOOP_PROBE_STATUS,
        "trace_gate_contract": TIME_TWIN_STAR_TURN_LOOP_TRACE_GATE_CONTRACT,
        "trace_gate_status": TIME_TWIN_STAR_TURN_LOOP_TRACE_GATE_STATUS,
        "source_runtime_route_status": TIME_TWIN_STAR_SOURCE_RUNTIME_ROUTE_STATUS,
        "platform_delivery_status": "platform_delivery_not_proven",
        "agent_turn_loop_status": TIME_TWIN_STAR_AGENT_TURN_LOOP_STATUS,
        "turn_loop_behavior_status": TIME_TWIN_STAR_TURN_LOOP_BEHAVIOR_STATUS,
        "levels": [
            {
                "id": TIME_TWIN_STAR_TURN_LOOP_PROBE_STATUS,
                "proof_level": "repository_or_in_process_probe",
                "required_observations": [
                    "ordinary_chat_handled_false",
                    "ordinary_chat_reason_requires_explicit_zhiyi_entry",
                    "explicit_zhiyi_entry_reaches_before_dispatch_hook",
                    "no_platform_action_performed",
                    "no_raw_or_memory_write_performed",
                    "no_model_call_required",
                    "existing_recall_or_answer_behavior_not_changed",
                ],
                "does_not_prove": [
                    "installed_runtime_route_present",
                    "platform_delivery_proven",
                    "agent_turn_loop_behavior_proven",
                    "time_rules_changed_real_user_answer_behavior",
                ],
            },
            {
                "id": "turn_loop_behavior_proven",
                "proof_level": "observed_real_turn_trace",
                "required_observations": [
                    "actual_agent_turn_loop_invoked",
                    "evidence_packet_observed_before_judgment",
                    "passive_first_default_still_handled_false",
                    "receipt_gap_unknown_visible_when_relevant",
                    "rollback_boundary_documented",
                    "no_platform_action_without_separate_authorization",
                ],
                "not_allowed_as_substitute": [
                    "repository_tests_only",
                    "fixture_backed_model_trace_only",
                    "source_route_or_installed_endpoint_only",
                ],
            },
        ],
        "read_only": True,
        "write_performed": False,
        "runtime_behavior_changed": False,
        "nas_runtime_dependency": False,
    }


def _truthy_observation(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _nested_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def time_twin_star_turn_loop_probe_from_observations(
    *,
    ordinary_result: dict[str, Any],
    explicit_result: dict[str, Any],
    write_observations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify an in-process turn-loop probe without claiming behavior proof."""

    ordinary = _nested_dict(ordinary_result)
    explicit = _nested_dict(explicit_result)
    writes = _nested_dict(write_observations)
    before_dispatch_raw = _nested_dict(explicit.get("before_dispatch_raw_capture"))
    before_dispatch_dedupe = _nested_dict(explicit.get("before_dispatch_dedupe"))
    usage_log = _nested_dict(explicit.get("usage_log"))
    platform_delivery = _nested_dict(explicit.get("platform_delivery"))
    model_call = _nested_dict(explicit.get("model_call"))

    ordinary_passive_first = (
        ordinary.get("handled") is False
        and ordinary.get("reason") == "openclaw_before_dispatch_requires_explicit_zhiyi_entry"
    )
    explicit_hook_observed = (
        explicit.get("handled") is True
        and explicit.get("chain") == "F3_zhiyi_direct"
        and str(explicit.get("text") or explicit.get("answer") or "").strip() != ""
    )
    no_write_observed = not any(
        _truthy_observation(value)
        for value in [
            explicit.get("openclaw_write_performed"),
            explicit.get("raw_write_performed"),
            explicit.get("memory_write_performed"),
            explicit.get("platform_write_performed"),
            platform_delivery.get("write_performed"),
            before_dispatch_raw.get("write_performed"),
            before_dispatch_dedupe.get("write_performed"),
            usage_log.get("usage_log_write_performed"),
            writes.get("raw_write_performed"),
            writes.get("memory_write_performed"),
            writes.get("platform_write_performed"),
            writes.get("usage_log_write_performed"),
        ]
    )
    no_model_call = not any(
        _truthy_observation(value)
        for value in [
            model_call.get("called"),
            model_call.get("request_sent"),
            explicit.get("model_call_performed"),
            writes.get("model_call_performed"),
        ]
    )
    no_platform_action = not any(
        _truthy_observation(value)
        for value in [
            writes.get("platform_action_performed"),
            writes.get("openclaw_rpc_performed"),
            explicit.get("platform_action_performed"),
        ]
    )
    ok = bool(ordinary_passive_first and explicit_hook_observed and no_write_observed and no_model_call and no_platform_action)

    return {
        "ok": ok,
        "contract": TIME_TWIN_STAR_TURN_LOOP_PROBE_CONTRACT,
        "turn_loop_probe_status": TIME_TWIN_STAR_TURN_LOOP_PROBE_STATUS if ok else "turn_loop_probe_unproven",
        "source_runtime_route_status": TIME_TWIN_STAR_SOURCE_RUNTIME_ROUTE_STATUS,
        "platform_delivery_status": "platform_delivery_not_proven",
        "agent_turn_loop_status": TIME_TWIN_STAR_AGENT_TURN_LOOP_STATUS,
        "turn_loop_behavior_status": TIME_TWIN_STAR_TURN_LOOP_BEHAVIOR_STATUS,
        "proof_scope": "repository_or_in_process_probe_only",
        "observations": {
            "ordinary_chat_handled_false": ordinary.get("handled") is False,
            "ordinary_chat_reason": ordinary.get("reason", ""),
            "ordinary_passive_first": ordinary_passive_first,
            "explicit_zhiyi_entry_handled": explicit.get("handled") is True,
            "explicit_hook_observed": explicit_hook_observed,
            "no_write_observed": no_write_observed,
            "no_model_call": no_model_call,
            "no_platform_action": no_platform_action,
        },
        "ordinary_result_summary": {
            "handled": ordinary.get("handled"),
            "reason": ordinary.get("reason", ""),
            "action": ordinary.get("action", ""),
        },
        "explicit_result_summary": {
            "handled": explicit.get("handled"),
            "chain": explicit.get("chain", ""),
            "answer_source": explicit.get("answer_source", ""),
            "platform_reply_returned": bool(explicit.get("platform_reply_returned")),
            "openclaw_before_dispatch_returned": bool(explicit.get("openclaw_before_dispatch_returned")),
        },
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "runtime_behavior_changed": False,
        "nas_runtime_dependency": False,
        "non_claims": [
            "does_not_claim_installed_runtime_route_present",
            "does_not_claim_platform_delivery_proven",
            "does_not_claim_agent_turn_loop_behavior_proven",
            "does_not_claim_time_rules_changed_real_user_answer_behavior",
            "does_not_restart_or_sync_installed_runtime",
            "does_not_write_raw_memory_or_platform_state",
        ],
    }


_REAL_TURN_TRACE_REQUIRED_OBSERVATIONS: tuple[str, ...] = (
    "actual_agent_turn_loop_invoked",
    "evidence_packet_observed_before_judgment",
    "passive_first_default_still_handled_false",
    "receipt_visible",
    "gap_visible_when_relevant",
    "unknown_visible_when_no_evidence",
    "time_rules_changed_real_user_answer_behavior",
    "changed_behavior_was_correct",
    "rollback_boundary_documented",
    "no_platform_action_without_separate_authorization",
)

_REAL_TURN_TRACE_FORBIDDEN_SUBSTITUTES: tuple[str, ...] = (
    "repository_tests_only",
    "fixture_backed_model_trace_only",
    "source_route_only",
    "installed_endpoint_only",
)


def time_twin_star_turn_loop_trace_gate_definition() -> dict[str, Any]:
    """Return the read-only gate for future real turn-loop behavior proof."""

    return {
        "ok": True,
        "contract": TIME_TWIN_STAR_TURN_LOOP_TRACE_GATE_CONTRACT,
        "gate_status": TIME_TWIN_STAR_TURN_LOOP_TRACE_GATE_STATUS,
        "target_status": "turn_loop_behavior_proven",
        "current_behavior_status": TIME_TWIN_STAR_TURN_LOOP_BEHAVIOR_STATUS,
        "required_observations": list(_REAL_TURN_TRACE_REQUIRED_OBSERVATIONS),
        "forbidden_substitutes": list(_REAL_TURN_TRACE_FORBIDDEN_SUBSTITUTES),
        "minimum_trace_kind": "observed_real_agent_turn",
        "read_only": True,
        "write_performed": False,
        "runtime_behavior_changed": False,
        "nas_runtime_dependency": False,
        "non_claims": [
            "does_not_collect_a_real_turn_trace_by_itself",
            "does_not_claim_agent_turn_loop_behavior_proven",
            "does_not_restart_or_sync_installed_runtime",
            "does_not_write_raw_memory_or_platform_state",
        ],
    }


def _trace_bool(trace: dict[str, Any], key: str) -> bool:
    observations = _nested_dict(trace.get("observations"))
    if key in observations:
        return _truthy_observation(observations.get(key))
    return _truthy_observation(trace.get(key))


def _trace_text(trace: dict[str, Any], key: str) -> str:
    value = trace.get(key)
    if value is None:
        value = _nested_dict(trace.get("observations")).get(key)
    return str(value or "").strip()


def time_twin_star_turn_loop_trace_gate_from_observation(trace: dict[str, Any]) -> dict[str, Any]:
    """Classify an externally supplied real turn trace without collecting one.

    The gate is intentionally conservative: it can say that a supplied trace is
    sufficient for the next proof step, but this function itself never claims
    that such a trace has been captured from a live agent.
    """

    observed = _behavior_proof_trace(_nested_dict(trace))
    trace_kind = _trace_text(observed, "trace_kind")
    if not trace_kind:
        trace_kind = _trace_text(observed, "source")
    missing = [key for key in _REAL_TURN_TRACE_REQUIRED_OBSERVATIONS if not _trace_bool(observed, key)]
    forbidden_present = [key for key in _REAL_TURN_TRACE_FORBIDDEN_SUBSTITUTES if _trace_bool(observed, key)]
    trace_source = _trace_text(observed, "source")
    if trace_source.startswith("fixture://"):
        forbidden_present.append("fixture_source_uri")
    real_trace_observed = trace_kind == "observed_real_agent_turn"
    if not real_trace_observed:
        missing.insert(0, "trace_kind_observed_real_agent_turn")

    sufficient = not missing and not forbidden_present
    return {
        "ok": True,
        "contract": TIME_TWIN_STAR_TURN_LOOP_TRACE_GATE_CONTRACT,
        "gate_status": TIME_TWIN_STAR_TURN_LOOP_TRACE_GATE_STATUS,
        "trace_sufficient_for_behavior_proven": sufficient,
        "turn_loop_behavior_status": "turn_loop_behavior_proven" if sufficient else TIME_TWIN_STAR_TURN_LOOP_BEHAVIOR_STATUS,
        "agent_turn_loop_status": "agent_turn_loop_behavior_observed" if sufficient else TIME_TWIN_STAR_AGENT_TURN_LOOP_STATUS,
        "proof_scope": "external_observed_real_turn_trace_required",
        "trace_kind": trace_kind,
        "trace_source": trace_source,
        "missing_observations": missing,
        "forbidden_substitutes_present": forbidden_present,
        "observations": {
            key: _trace_bool(observed, key) for key in _REAL_TURN_TRACE_REQUIRED_OBSERVATIONS
        },
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "runtime_behavior_changed": False,
        "nas_runtime_dependency": False,
        "non_claims": [
            "does_not_collect_a_real_turn_trace_by_itself",
            "does_not_claim_behavior_proven_without_external_real_trace",
            "does_not_accept_repository_tests_fixture_source_route_or_endpoint_as_substitute",
            "does_not_restart_or_sync_installed_runtime",
            "does_not_write_raw_memory_or_platform_state",
        ],
    }


_PASSIVE_PUSH_REQUIRED_OBSERVATIONS: tuple[str, ...] = (
    "actual_agent_turn_loop_invoked",
    "no_explicit_recall_call",
    "before_dispatch_auto_injection",
    "positive_memory_matched",
    "primary_recall_backend_vector",
    "matched_by_contains_vector",
    "evidence_packet_observed_before_judgment",
    "answer_uses_recalled_memory",
    "model_call_performed",
    "passive_first_default_still_handled_false",
    "negative_arm_no_injection",
    "receipt_visible",
    "source_ref_visible",
    "smoke_session_only",
    "no_real_person_touched",
    "flags_restored",
    "no_unauthorized_platform_write",
    "rollback_boundary_documented",
    "fallback_explicit_when_vector_miss",
)

_PASSIVE_PUSH_FORBIDDEN_SUBSTITUTES: tuple[str, ...] = (
    "explicit_zhiyi_recall_call",
    "repository_tests_only",
    "fixture_backed_model_trace_only",
    "source_route_only",
    "installed_endpoint_only",
    "direct_endpoint_controlled_smoke_only",
    "positive_arm_only",
    "negative_arm_only",
    "substring_success_masquerading_as_vector",
    "fixture_evidence_bound_model",
    "gateway_injected_model_only",
)


def time_twin_star_passive_push_trace_gate_definition() -> dict[str, Any]:
    """Return the read-only gate for the first passive auto-injection proof."""

    return {
        "ok": True,
        "contract": TIME_TWIN_STAR_PASSIVE_PUSH_TRACE_GATE_CONTRACT,
        "gate_status": TIME_TWIN_STAR_PASSIVE_PUSH_TRACE_GATE_STATUS,
        "target_status": "passive_push_behavior_proven",
        "current_behavior_status": TIME_TWIN_STAR_PASSIVE_PUSH_BEHAVIOR_STATUS,
        "scope": "controlled_openclaw_model_in_loop_smoke_only",
        "push_coverage_delta_when_sufficient": "0/7_to_1/7_when_model_in_loop",
        "required_observations": list(_PASSIVE_PUSH_REQUIRED_OBSERVATIONS),
        "forbidden_substitutes": list(_PASSIVE_PUSH_FORBIDDEN_SUBSTITUTES),
        "minimum_trace_kind": "observed_real_agent_turn",
        "read_only": True,
        "write_performed": False,
        "runtime_behavior_changed": False,
        "nas_runtime_dependency": False,
        "non_claims": [
            "does_not_collect_a_real_platform_trace_by_itself",
            "does_not_claim_all_platforms_passive_push_proven",
            "does_not_accept_explicit_pull_as_passive_push",
            "does_not_accept_substring_as_vector_proof",
            "does_not_restart_or_sync_installed_runtime",
            "does_not_write_raw_memory_or_platform_state",
        ],
    }


def time_twin_star_passive_push_trace_gate_from_observation(trace: dict[str, Any]) -> dict[str, Any]:
    """Classify an externally supplied OpenClaw passive push smoke trace."""

    observed = _nested_dict(trace)
    trace_kind = _trace_text(observed, "trace_kind")
    if not trace_kind:
        trace_kind = _trace_text(observed, "source")
    missing = [key for key in _PASSIVE_PUSH_REQUIRED_OBSERVATIONS if not _trace_bool(observed, key)]
    forbidden_present = [key for key in _PASSIVE_PUSH_FORBIDDEN_SUBSTITUTES if _trace_bool(observed, key)]
    answer_source = _trace_text(observed, "answer_source")
    model_name = _trace_text(observed, "model_name")
    provenance = _trace_text(observed, "provenance")
    real_trace_observed = trace_kind == "observed_real_agent_turn"
    if not real_trace_observed:
        missing.insert(0, "trace_kind_observed_real_agent_turn")
    if "fixture" in answer_source.lower() or "fixture" in model_name.lower():
        forbidden_present.append("fixture_evidence_bound_model")
    if model_name == "gateway-injected":
        forbidden_present.append("gateway_injected_model_only")
    if provenance == "direct_installed_runtime_openclaw_before_dispatch_endpoint_controlled_smoke":
        forbidden_present.append("direct_endpoint_controlled_smoke_only")

    sufficient = not missing and not forbidden_present
    return {
        "ok": True,
        "contract": TIME_TWIN_STAR_PASSIVE_PUSH_TRACE_GATE_CONTRACT,
        "gate_status": TIME_TWIN_STAR_PASSIVE_PUSH_TRACE_GATE_STATUS,
        "trace_sufficient_for_passive_push_proven": sufficient,
        "push_behavior_status": "passive_push_behavior_proven" if sufficient else TIME_TWIN_STAR_PASSIVE_PUSH_BEHAVIOR_STATUS,
        "push_platform_scope": "controlled_openclaw_model_in_loop_smoke_only",
        "push_coverage_delta": "0/7_to_1/7" if sufficient else "0/7_still_unproven",
        "proof_scope": "external_observed_real_openclaw_model_in_loop_trace_required",
        "trace_kind": trace_kind,
        "missing_observations": missing,
        "forbidden_substitutes_present": forbidden_present,
        "observations": {
            key: _trace_bool(observed, key) for key in _PASSIVE_PUSH_REQUIRED_OBSERVATIONS
        },
        "answer_source": answer_source,
        "model_name": model_name,
        "provenance": provenance,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "runtime_behavior_changed": False,
        "nas_runtime_dependency": False,
        "non_claims": [
            "does_not_collect_a_real_platform_trace_by_itself",
            "does_not_claim_passive_push_without_positive_and_negative_arms",
            "does_not_accept_explicit_pull_as_passive_push",
            "does_not_accept_substring_as_vector_proof",
            "does_not_claim_all_platforms_passive_push_proven",
            "does_not_restart_or_sync_installed_runtime",
            "does_not_write_raw_memory_or_platform_state",
        ],
    }


def probe_time_twin_star_installed_runtime(
    *,
    console_url: str = TIME_TWIN_STAR_DEFAULT_CONSOLE_URL,
    timeout_seconds: float = 3.0,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Probe the installed p6 console for the Time Twin Star status route.

    This is a read-only installed-runtime probe. It performs GET requests only
    and treats a reachable p6 console with a missing Time Twin Star endpoint as
    useful evidence: the installed runtime is live, but not updated to the new
    source route.
    """

    health_url = _join_url(console_url, "/api/health")
    endpoint_url = _join_url(console_url, TIME_TWIN_STAR_STATUS_ENDPOINT)
    health = _http_get_json(health_url, timeout_seconds=timeout_seconds, opener=opener)
    endpoint = _http_get_json(endpoint_url, timeout_seconds=timeout_seconds, opener=opener)
    endpoint_payload = endpoint.get("payload") if isinstance(endpoint.get("payload"), dict) else {}

    endpoint_contract_ok = (
        endpoint.get("ok") is True
        and endpoint_payload.get("contract") == TIME_TWIN_STAR_RUNTIME_STATUS_CONTRACT
        and endpoint_payload.get("runtime_status") == TIME_TWIN_STAR_SOURCE_RUNTIME_ROUTE_STATUS
    )

    if endpoint_contract_ok:
        installed_status = "installed_runtime_route_present"
    elif health.get("ok") is True and endpoint.get("status_code") == 404:
        installed_status = "installed_runtime_not_updated"
    elif health.get("ok") is True:
        installed_status = "installed_runtime_route_unproven"
    elif health.get("reachable") is False:
        installed_status = "installed_runtime_not_reachable"
    else:
        installed_status = "installed_runtime_unhealthy"

    return {
        "ok": installed_status in {"installed_runtime_route_present", "installed_runtime_not_updated"},
        "contract": TIME_TWIN_STAR_INSTALLED_RUNTIME_PROBE_CONTRACT,
        "source_runtime_route_status": TIME_TWIN_STAR_SOURCE_RUNTIME_ROUTE_STATUS,
        "installed_runtime_status": installed_status,
        "platform_delivery_status": str(endpoint_payload.get("platform_delivery_status") or "not_proven")
        if endpoint_contract_ok
        else "not_proven",
        "agent_turn_loop_status": str(endpoint_payload.get("agent_turn_loop_status") or "not_proven")
        if endpoint_contract_ok
        else "not_proven",
        "console_url": str(console_url or TIME_TWIN_STAR_DEFAULT_CONSOLE_URL).rstrip("/"),
        "health_url": health_url,
        "endpoint": TIME_TWIN_STAR_STATUS_ENDPOINT,
        "endpoint_url": endpoint_url,
        "timeout_seconds": timeout_seconds,
        "read_only": True,
        "http_methods_used": ["GET"],
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "runtime_behavior_changed": bool(endpoint_payload.get("runtime_behavior_changed")) if endpoint_contract_ok else False,
        "restart_performed": False,
        "sync_performed": False,
        "nas_runtime_dependency": False,
        "health_check": {
            "reachable": bool(health.get("reachable")),
            "ok": bool(health.get("ok")),
            "status_code": int(health.get("status_code") or 0),
            "json_ok": bool(health.get("json_ok")),
            "error": str(health.get("error") or ""),
        },
        "endpoint_check": {
            "reachable": bool(endpoint.get("reachable")),
            "ok": bool(endpoint.get("ok")),
            "status_code": int(endpoint.get("status_code") or 0),
            "json_ok": bool(endpoint.get("json_ok")),
            "contract": str(endpoint_payload.get("contract") or ""),
            "runtime_status": str(endpoint_payload.get("runtime_status") or ""),
            "installed_runtime_status": str(endpoint_payload.get("installed_runtime_status") or ""),
            "platform_delivery_status": str(endpoint_payload.get("platform_delivery_status") or ""),
            "agent_turn_loop_status": str(endpoint_payload.get("agent_turn_loop_status") or ""),
            "runtime_behavior_changed": bool(endpoint_payload.get("runtime_behavior_changed")),
            "source_proven_count": (
                endpoint_payload.get("rule_status_counts", {}).get("source_proven")
                if isinstance(endpoint_payload.get("rule_status_counts"), dict)
                else None
            ),
            "error": str(endpoint.get("error") or ""),
        },
        "observed_contract_payload": endpoint_payload if endpoint_contract_ok else {},
        "interpretation": {
            "installed_runtime_route_present": endpoint_contract_ok,
            "installed_runtime_not_updated": installed_status == "installed_runtime_not_updated",
            "installed_runtime_reachable": bool(health.get("ok")),
            "route_missing_while_console_healthy": health.get("ok") is True and endpoint.get("status_code") == 404,
        },
        "non_claims": [
            "does_not_sync_installed_runtime",
            "does_not_restart_p6_console",
            "does_not_claim_platform_delivery_proven",
            "does_not_claim_agent_turn_loop_connected",
            "does_not_change_runtime_behavior",
            "does_not_write_raw_memory_or_platform_state",
            "does_not_read_nas_at_runtime",
        ],
    }
