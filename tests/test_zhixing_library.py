import importlib
import json
from pathlib import Path


def test_zhixing_library_shelves_keep_zhiyi_and_xingce_distinct():
    lib = importlib.import_module("src.zhixing_library")

    preference = {
        "type": "preference_memory",
        "exp_id": "pref-001",
        "summary": "用户偏好：回答先给结论。",
        "detail": "以后同类问题先给结论。",
    }
    xingce = {
        "_type": "xingce_work_experience_candidate",
        "exp_id": "xingce-001",
        "summary": "排障工作经验",
        "detail": "先查网关，再查配置。",
        "_xingce": {"candidate_id": "xingce-001", "lifecycle_status": "candidate"},
    }

    pref_card = lib.library_card_for(preference)
    xingce_card = lib.library_card_for(xingce)

    assert pref_card["library_id"].startswith("ZX-ZHIYI-")
    assert pref_card["shelf"] == "zhiyi"
    assert xingce_card["library_id"].startswith("ZX-XINGCE-")
    assert xingce_card["shelf"] == "xingce"
    assert xingce_card["work_experience"]["not_a_user_preference"] is True


def test_zhixing_library_preserves_verbatim_excerpt_without_redaction():
    lib = importlib.import_module("src.zhixing_library")
    marker = "用户原话 token=USER_OWN_TEXT_1234567890 password=只是聊天内容，不能脱敏。"

    card = lib.library_card_for({
        "type": "case_memory",
        "exp_id": "case-verbatim",
        "summary": "原样保存",
        "raw_excerpt": marker,
        "source_refs": {"source_system": "codex", "source_path": "/tmp/session.jsonl"},
    })

    assert marker in card["verbatim_excerpt"]
    assert "REDACTED" not in card["verbatim_excerpt"]
    assert "****" not in card["verbatim_excerpt"]
    assert card["evidence_contract"]["valid_experience_record"] is True
    assert card["evidence_contract"]["verbatim_excerpt_required"] is True


def test_zhixing_library_platform_source_path_does_not_turn_zhiyi_into_toolbook():
    lib = importlib.import_module("src.zhixing_library")

    card = lib.library_card_for({
        "type": "case_memory",
        "exp_id": "case-codex-path",
        "summary": "用户希望回答自然接上前文。",
        "source_refs": {
            "source_system": "codex",
            "source_path": "/tmp/memory/codex/local/project-a/session.jsonl",
        },
    })

    assert card["shelf"] == "zhiyi"


def test_zhixing_library_xingce_card_has_lifecycle_and_graph_edges():
    lib = importlib.import_module("src.zhixing_library")
    record = {
        "_type": "xingce_work_experience_candidate",
        "exp_id": "xingce-graph",
        "summary": "某类修复必须先验收服务状态。",
        "work_scenario": "服务修复",
        "action_strategy": ["先查状态", "再改配置"],
        "avoid_conditions": ["没有来源时不要采用"],
        "acceptance_checks": ["重启后健康检查通过"],
        "source_refs": {
            "source_system": "openclaw",
            "canonical_window_id": "project-a",
            "source_path": "/tmp/openclaw.jsonl",
        },
        "verbatim_excerpt": "原话片段：先查状态，再改配置。",
        "origin_event": {
            "origin_id": "origin_xingce_graph",
            "origin_status": "origin_witnessed",
            "origin_label": "起源已见证",
            "source_refs": {
                "source_system": "openclaw",
                "source_path": "/tmp/openclaw.jsonl",
            },
        },
        "supersedes": ["ZX-XINGCE-OLD"],
        "conflicts_with": [],
        "_xingce": {"candidate_id": "xingce-graph", "lifecycle_status": "candidate"},
    }

    card = lib.library_card_for(record, query="服务修复", raw_status="raw")
    edge_types = {edge["type"] for edge in card["typed_graph"]["edges"]}

    assert card["shelf"] == "xingce"
    assert card["xingce_lifecycle"]["allowed_statuses"] == [
        "candidate",
        "pending_review",
        "adopted",
        "deprecated",
        "superseded",
    ]
    assert card["work_experience"]["work_scenario"] == "服务修复"
    assert "uses_preference" in edge_types
    assert "belongs_to" in edge_types
    assert "source_refs" in card["matched_by"]
    assert "shelf=xingce" in card["rank_reason"]
    assert card["supersedes"] == ["ZX-XINGCE-OLD"]
    assert card["evidence_contract"]["valid_experience_record"] is True
    assert card["time_river_sediment"]["contract"] == "tiandao_time_river_sediment.v1"
    assert card["time_river_sediment"]["origin_id"] == "origin_xingce_graph"
    assert card["time_river_sediment"]["sediment_status"] == "origin_linked"
    assert card["time_river_sediment"]["trusted_sediment"] is True


def test_zhixing_library_missing_verbatim_excerpt_is_contract_failure():
    lib = importlib.import_module("src.zhixing_library")

    card = lib.library_card_for({
        "type": "case_memory",
        "exp_id": "case-missing-verbatim",
        "summary": "只有总结没有原话片段。",
        "source_refs": {"source_system": "codex", "source_path": "/tmp/session.jsonl"},
    })

    assert card["verbatim_excerpt"] == ""
    assert card["evidence_contract"]["valid_experience_record"] is False
    assert "verbatim_excerpt" in card["evidence_contract"]["missing_fields"]


def test_toolbook_requires_raw_external_doc_or_probe_log_and_has_tool_node():
    lib = importlib.import_module("src.zhixing_library")

    good = lib.library_card_for({
        "type": "yifanchen_project_status",
        "exp_id": "toolbook-good",
        "summary": "Hermes config.yaml 位置说明。",
        "verbatim_excerpt": "测试日志原文：config.yaml 位于 profiles/default/config.yaml。",
        "source_refs": {
            "source_system": "probe",
            "source_path": "raw/probe_logs/hermes-config-location.jsonl",
        },
    })
    bad = lib.library_card_for({
        "type": "yifanchen_project_status",
        "exp_id": "toolbook-bad",
        "summary": "Hermes config.yaml 位置说明。",
        "verbatim_excerpt": "测试日志原文。",
        "source_refs": {
            "source_system": "probe",
            "source_path": "notes/hermes-config-location.md",
        },
    })

    assert good["shelf"] == "toolbook"
    assert good["evidence_contract"]["toolbook_raw_source_ok"] is True
    assert any(node["type"] == "tool" for node in good["typed_graph"]["nodes"])
    assert bad["evidence_contract"]["valid_experience_record"] is False
    assert "toolbook_raw_source" in bad["evidence_contract"]["missing_fields"]


def test_library_manifest_declares_tool_node_and_source_first_pipeline():
    lib = importlib.import_module("src.zhixing_library")

    manifest = lib.library_manifest()
    hybrid = lib.hybrid_recall_manifest()

    assert "tool" in manifest["node_types"]
    assert manifest["toolbook_raw_sources"]["external_docs"] == "raw/external_docs/"
    assert manifest["time_river_sediment"]["contract"] == "tiandao_time_river_sediment.v1"
    assert manifest["time_river_sediment"]["trusted_status"] == "origin_linked"
    assert manifest["ai_readable_projection"]["contract"] == "zhixing_ai_readable_library_projection.v1"
    assert manifest["ai_readable_projection"]["profile"] == "five_shelf_ai_readable_projection.v2026.6.17"
    assert manifest["ai_readable_projection"]["l0_layer"] == "L0_library_index_projection"
    assert manifest["ai_readable_projection"]["l1_layer"] == "L1_library_note_projection"
    assert manifest["ai_readable_projection"]["source_authority_layer"] == "L2_raw_source_record"
    assert "bind_projection_to_one_note_app" in manifest["ai_readable_projection"]["forbidden_by_default"]
    assert manifest["library_note_projection"]["not_a_new_memory_layer"] is True
    assert manifest["library_note_projection"]["requires_obsidian"] is False
    assert manifest["library_note_projection"]["projection_layer"] == "L1_library_note_projection"
    assert manifest["admission_candidate"]["not_durable_memory"] is True
    assert manifest["experience_apply_package"]["contract"] == "zhixing_library_experience_apply_package.v1"
    assert manifest["experience_apply_package"]["not_a_new_memory_layer"] is True
    assert manifest["experience_flow_overview"]["contract"] == "zhixing_library_experience_flow_overview.v1"
    assert manifest["experience_flow_overview"]["stage_count"] == 8
    assert hybrid["pipeline_order"][0] == "source_refs_exact"
    assert hybrid["vector_is_not_authority"] is True


def test_library_note_projection_renders_markdown_without_creating_sixth_layer():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.build_library_note_projection_dry_run({
        "record": {
            "_type": "xingce_work_experience_candidate",
            "library_id": "ZX-XINGCE-NOTE",
            "exp_id": "xingce-note",
            "summary": "发布前先跑记录医生，确认 raw 和 source 都在。",
            "work_scenario": "发布前检查",
            "action_strategy": ["跑记录医生", "确认遗失源/遗失 raw 为 0"],
            "avoid_conditions": ["没有 source_refs 不要采纳"],
            "acceptance_checks": ["record doctor passed"],
            "source_refs": {
                "source_system": "codex",
                "source_path": "raw/codex/release-check.jsonl",
            },
            "verbatim_excerpt": "发布前先跑记录医生，确认 raw 和 source 都在。",
            "supersedes": ["ZX-XINGCE-OLD"],
            "conflicts_with": [],
            "depends_on": ["ZX-TOOL-DOCTOR"],
            "_xingce": {"candidate_id": "xingce-note", "lifecycle_status": "candidate"},
        }
    })

    markdown = result["markdown"]
    projection = result["projection"]

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert projection["not_a_new_memory_layer"] is True
    assert projection["requires_obsidian"] is False
    assert projection["ai_readable_projection_profile"] == "five_shelf_ai_readable_projection.v2026.6.17"
    assert projection["projection_layer"] == "L1_library_note_projection"
    assert projection["source_authority_layer"] == "L2_raw_source_record"
    assert projection["shelf"] == "xingce"
    assert "type: \"Library Note Projection\"" in markdown
    assert "ai_readable_projection_profile: \"five_shelf_ai_readable_projection.v2026.6.17\"" in markdown
    assert "source_authority_layer: \"L2_raw_source_record\"" in markdown
    assert "library_id: \"ZX-XINGCE-NOTE\"" in markdown
    assert "not_a_new_memory_layer: true" in markdown
    assert "requires_obsidian: false" not in markdown
    assert "## Procedure Or Judgment" in markdown
    assert "- 跑记录医生" in markdown
    assert "- source_path: `raw/codex/release-check.jsonl`" in markdown


def test_library_relation_graph_keeps_relations_inside_library_ids():
    lib = importlib.import_module("src.zhixing_library")

    card = lib.library_card_for({
        "_type": "xingce_work_experience_candidate",
        "library_id": "ZX-XINGCE-REL",
        "summary": "行策依赖工具事实和勘误。",
        "source_refs": {"source_system": "codex", "source_path": "raw/codex/rel.jsonl"},
        "verbatim_excerpt": "行策依赖工具事实和勘误。",
        "supersedes": ["ZX-XINGCE-OLD"],
        "depends_on": ["ZX-TOOL-FACT"],
        "proven_by": ["ZX-RAW-PROOF"],
        "contradicts": ["ZX-ERRATA-RISK"],
        "conflicts_with": [],
        "_xingce": {"candidate_id": "xingce-rel", "lifecycle_status": "candidate"},
    })

    edge_types = {edge["type"] for edge in card["typed_graph"]["edges"]}
    node_ids = {node["id"] for node in card["typed_graph"]["nodes"]}

    assert {"supersedes", "depends_on", "proven_by", "contradicts"}.issubset(edge_types)
    assert "library:ZX-TOOL-FACT" in node_ids
    assert "library:ZX-ERRATA-RISK" in node_ids
    assert card["library_note_projection"]["relations"]["depends_on"] == ["ZX-TOOL-FACT"]


def test_library_admission_candidate_shapes_markdown_as_review_only_material():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.build_library_admission_candidate({
        "source_type": "markdown_note",
        "target_shelf": "xingce",
        "title": "发布前检查经验",
        "text": "发布前先跑记录医生，确认遗失源和遗失 raw 都为 0。",
        "source_refs": {
            "source_system": "local_note",
            "source_path": "raw/external_docs/release-note.md.jsonl",
        },
        "verbatim_excerpt": "发布前先跑记录医生，确认遗失源和遗失 raw 都为 0。",
        "action_strategy": ["跑 doctor", "看 raw_attention/backfill/遗失源/遗失 raw"],
        "acceptance_checks": ["lost_source_count == 0", "lost_raw_count == 0"],
        "depends_on": ["ZX-TOOL-RECORD-DOCTOR"],
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["target_shelf"] == "xingce"
    assert result["candidate"]["library_shelf"] == "xingce"
    assert result["candidate"]["library_card"]["library_note_projection"]["not_a_new_memory_layer"] is True
    assert result["library_note_projection"]["requires_obsidian"] is False
    assert "admission_candidate_is_not_durable_memory" in result["notes"]
    assert "## Sources" in result["markdown"]
    assert "raw/external_docs/release-note.md.jsonl" in result["markdown"]


def test_library_admission_candidate_requires_source_refs_and_verbatim_excerpt():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.build_library_admission_candidate({
        "source_type": "article",
        "title": "只有标题的文章",
    })

    assert result["ok"] is False
    assert "source_refs" in result["missing"]
    assert "verbatim_excerpt" in result["missing"]
    assert result["candidate"] is None


def test_active_bookmarks_keep_current_task_compact_and_errata_first():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.build_active_bookmarks_dry_run({
        "task_id": "release-risk",
        "query": "发布前检查这条记录是不是不对",
        "limit": 2,
        "records": [
            {
                "type": "preference_memory",
                "library_id": "ZX-ZHIYI-STYLE",
                "summary": "用户偏好：先给结论。",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/style.jsonl"},
                "verbatim_excerpt": "先给结论。",
                "supersedes": [],
                "conflicts_with": [],
            },
            {
                "_type": "xingce_work_experience_candidate",
                "library_id": "ZX-XINGCE-RELEASE",
                "summary": "发布前先跑记录医生。",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/release.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
                "acceptance_checks": ["record doctor passed"],
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "release", "lifecycle_status": "candidate"},
            },
            {
                "type": "case_memory",
                "library_shelf": "errata",
                "library_id": "ZX-ERRATA-RELEASE",
                "summary": "旧发布记录已废弃。",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/errata.jsonl"},
                "verbatim_excerpt": "旧发布记录已废弃。",
                "status": "superseded",
                "supersedes": ["ZX-XINGCE-OLD"],
                "conflicts_with": ["ZX-XINGCE-OLD"],
            },
        ],
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["not_a_new_memory_layer"] is True
    assert result["global_memory_scan_performed"] is False
    assert result["recall_volume_control"]["input_count"] == 3
    assert result["recall_volume_control"]["output_count"] == 2
    assert result["recall_volume_control"]["limit_applied"] is True
    assert result["errata_first_applied"] is True
    assert result["bookmarks"][0]["library_id"] == "ZX-ERRATA-RELEASE"
    assert result["bookmarks"][0]["shelf"] == "errata"
    assert "errata_first_for_risky_query" in result["bookmarks"][0]["reason"]
    assert result["compact_context"][0]["library_id"] == "ZX-ERRATA-RELEASE"


def test_experience_history_tracks_xingce_without_changing_lifecycle():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.build_experience_history_dry_run({
        "records": [
            {
                "_type": "xingce_work_experience_candidate",
                "library_id": "ZX-XINGCE-HISTORY",
                "summary": "先验收再发布。",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/history.jsonl"},
                "verbatim_excerpt": "先验收再发布。",
                "acceptance_checks": ["tests passed"],
                "usage_count": "2",
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "history", "lifecycle_status": "candidate"},
            },
            {
                "type": "preference_memory",
                "library_id": "ZX-ZHIYI-SKIP",
                "summary": "先给结论。",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/pref.jsonl"},
                "verbatim_excerpt": "先给结论。",
                "supersedes": [],
                "conflicts_with": [],
            },
        ],
        "events": [
            {"library_id": "ZX-XINGCE-HISTORY", "event_type": "replay_passed", "at": "2026-06-14T10:00:00Z"},
            {"library_id": "ZX-XINGCE-HISTORY", "event_type": "accepted", "at": "2026-06-14T10:05:00Z"},
        ],
    })

    history = result["histories"][0]

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["not_a_new_memory_layer"] is True
    assert result["history_count"] == 1
    assert result["skipped_count"] == 1
    assert history["library_id"] == "ZX-XINGCE-HISTORY"
    assert history["usage_count"] == 4
    assert history["accepted_count"] == 1
    assert history["replay_count"] == 1
    assert history["validation_status"] == "validated"
    assert history["status"] == "candidate"
    assert result["summary"]["validated_count"] == 1


def test_library_trust_doctor_combines_projection_bookmarks_and_history():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.build_library_trust_doctor_dry_run({
        "query": "发布前检查",
        "records": [
            {
                "_type": "xingce_work_experience_candidate",
                "library_id": "ZX-XINGCE-DOCTOR",
                "summary": "发布前先跑记录医生。",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/doctor.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
                "acceptance_checks": ["record doctor passed"],
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "doctor", "lifecycle_status": "candidate"},
            }
        ],
        "events": [
            {"library_id": "ZX-XINGCE-DOCTOR", "event_type": "replay_passed", "at": "2026-06-14T10:00:00Z"}
        ],
    })

    checks = {check["id"]: check for check in result["checks"]}

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["doctor_status"] == "records_guarded"
    assert result["not_a_new_memory_layer"] is True
    assert checks["source_refs_available"]["ok"] is True
    assert checks["verbatim_excerpt_available"]["ok"] is True
    assert checks["library_note_projection_ready"]["ok"] is True
    assert checks["xingce_has_validation"]["ok"] is True
    assert result["active_bookmarks"]["bookmarks"][0]["library_id"] == "ZX-XINGCE-DOCTOR"
    assert result["experience_history"]["histories"][0]["validation_status"] == "validated"


def test_experience_evolution_candidates_turn_attention_into_review_queue():
    lib = importlib.import_module("src.zhixing_library")
    records = [
        {
            "_type": "xingce_work_experience_candidate",
            "library_id": "ZX-XINGCE-NEEDS-VALIDATION",
            "summary": "发布前先跑记录医生。",
            "source_refs": {"source_system": "codex", "source_path": "raw/codex/evolution.jsonl"},
            "verbatim_excerpt": "发布前先跑记录医生。",
            "supersedes": [],
            "conflicts_with": [],
            "_xingce": {"candidate_id": "needs-validation", "lifecycle_status": "candidate"},
        },
        {
            "type": "case_memory",
            "library_id": "ZX-ZHIYI-MISSING-EVIDENCE",
            "summary": "只有总结没有来源。",
            "supersedes": [],
            "conflicts_with": [],
        },
    ]
    trust = lib.build_library_trust_doctor_dry_run({
        "query": "发布前检查",
        "records": records,
    })
    replay = lib.run_replay_dry_run({
        "case": {
            "case_id": "evolution-case",
            "query": "继续发布",
            "expected_behavior_markers": ["记录医生"],
            "expected_source_refs": ["raw/codex/evolution.jsonl"],
            "forbidden_repeated_mistakes": ["跳过验收"],
            "required_acceptance_checks": ["record doctor passed"],
            "expected_proactive_resurfacing": ["发布前先跑记录医生"],
        },
        "records": records,
    })

    result = lib.build_experience_evolution_candidates_dry_run({
        "records": records,
        "trust_doctor": trust,
        "replay": replay,
    })
    candidate_types = set(result["candidate_types"])

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["raw_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["markdown_write_performed"] is False
    assert result["contract"] == "zhixing_library_experience_evolution_candidates.v1"
    assert result["not_a_new_memory_layer"] is True
    assert result["authorization_required_for_apply"] is True
    assert "experience_xingce_validation_candidate" in candidate_types
    assert "experience_errata_candidate" in candidate_types
    assert result["target_shelf_counts"]["xingce"] >= 1
    assert result["target_shelf_counts"]["errata"] >= 1
    assert all(candidate["requires_authorization"] is True for candidate in result["candidates"])
    assert all(candidate["write_performed"] is False for candidate in result["candidates"])
    assert {
        candidate["target_shelf"]
        for candidate in result["candidates"]
    }.issubset({"xingce", "toolbook", "errata"})


def test_experience_review_actions_are_receipt_previews_not_adoption():
    lib = importlib.import_module("src.zhixing_library")
    evolution = lib.build_experience_evolution_candidates_dry_run({
        "records": [
            {
                "_type": "xingce_work_experience_candidate",
                "library_id": "ZX-XINGCE-REVIEW",
                "summary": "发布前先跑记录医生。",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "raw/codex/review-action.jsonl",
                },
                "verbatim_excerpt": "发布前先跑记录医生。",
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "review-action", "lifecycle_status": "candidate"},
            }
        ],
        "trust_doctor": {
            "xingce_needs_validation": ["ZX-XINGCE-REVIEW"],
            "attention": ["ZX-XINGCE-REVIEW"],
        },
    })
    candidate_id = evolution["candidates"][0]["candidate_id"]

    result = lib.build_experience_review_actions_dry_run({
        "experience_evolution": evolution,
        "actions": [
            {
                "candidate_id": candidate_id,
                "action": "approve",
                "reason": "reviewed source refs and replay evidence",
                "reviewer": "local-test",
            },
            {
                "candidate_id": candidate_id,
                "action": "request_evidence",
                "reason": "需要补验收截图。",
            },
        ],
    })

    assert result["ok"] is True
    assert result["contract"] == "zhixing_library_experience_review_action.v1"
    assert result["source_contract"] == "zhixing_library_experience_evolution_candidates.v1"
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["raw_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["markdown_write_performed"] is False
    assert result["not_a_new_memory_layer"] is True
    assert result["authorization_required_for_apply"] is True
    assert result["all_writes_blocked"] is True
    assert result["action_count"] == 2
    assert result["target_shelf_counts"]["xingce"] == 2
    approve = result["review_actions"][0]
    assert approve["requested_action"] == "approve"
    assert approve["planned_lifecycle_status"] == "pending_authorized_adoption"
    assert approve["adoption_status"] == "not_adopted_in_dry_run"
    assert approve["receipt_preview"]["would_write"] is False
    assert approve["receipt_preview"]["requires_authorized_apply_gate"] is True
    assert all(action["requires_authorization"] is True for action in result["review_actions"])


def test_experience_review_apply_gate_blocks_then_readies_without_writes():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidate": {
            "candidate_id": "review-gate-candidate",
            "candidate_type": "experience_xingce_validation_candidate",
            "target_shelf": "xingce",
            "reason": "needs validation",
        },
        "action": "approve",
        "candidate_id": "review-gate-candidate",
        "reason": "ready for gate",
    })

    blocked = lib.build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
    })
    assert blocked["contract"] == "zhixing_library_experience_review_apply_gate.v1"
    assert blocked["status"] == "blocked"
    assert "missing_authorization_confirmations" in blocked["blocked_reasons"]
    assert blocked["write_performed"] is False
    assert blocked["receipt_preview"]["would_write"] is False

    ready = lib.build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
        "authorization": {
            "confirm_review_action_intent": True,
            "confirm_source_refs_checked": True,
            "confirm_replay_or_validation_checked": True,
            "confirm_no_raw_or_markdown_write": True,
            "operator": "local-test",
            "reason": "dry-run gate only",
        },
    })
    assert ready["status"] == "ready"
    assert ready["authorization_complete"] is True
    assert ready["missing_confirmations"] == []
    assert ready["review_action_count"] == 1
    assert ready["target_shelf_counts"]["xingce"] == 1
    assert ready["write_performed"] is False
    assert ready["raw_write_performed"] is False
    assert ready["xingce_write_performed"] is False
    assert ready["markdown_write_performed"] is False
    assert ready["receipt_preview"]["future_apply_required"] is True
    assert ready["receipt_preview"]["would_write"] is False


def test_experience_validation_report_gates_apply_with_replay_or_history_evidence():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidates": [
            {
                "candidate_id": "candidate-validated",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_library_id": "ZX-XINGCE-VALIDATED",
                "target_shelf": "xingce",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/validated.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
                "acceptance_checks": ["record doctor passed"],
            }
        ],
        "actions": [
            {"candidate_id": "candidate-validated", "action": "approve", "reason": "validation evidence checked"},
        ],
    })
    report = lib.build_experience_validation_report_dry_run({
        "experience_review_actions": review,
        "experience_history": {
            "histories": [
                {"library_id": "ZX-XINGCE-VALIDATED", "validation_status": "validated", "replay_count": 1}
            ]
        },
    })

    assert report["contract"] == "zhixing_library_experience_validation_report.v1"
    assert report["source_contract"] == "zhixing_library_experience_review_action.v1"
    assert report["dry_run"] is True
    assert report["read_only"] is True
    assert report["write_performed"] is False
    assert report["raw_write_performed"] is False
    assert report["xingce_write_performed"] is False
    assert report["markdown_write_performed"] is False
    assert report["not_a_new_memory_layer"] is True
    assert report["report_passed"] is True
    assert report["validation_issue_count"] == 0
    assert report["validation_reports"][0]["checks"]["history_validated"] is True
    assert report["validation_reports"][0]["validation_passed"] is True

    gate = lib.build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": report,
        "authorization": {
            "confirm_review_action_intent": True,
            "confirm_source_refs_checked": True,
            "confirm_replay_or_validation_checked": True,
            "confirm_no_raw_or_markdown_write": True,
            "operator": "local-test",
            "reason": "validation report attached",
        },
    })
    assert gate["status"] == "ready"
    assert gate["validation_report_attached"] is True
    assert gate["validation_report_passed"] is True


def test_experience_validation_report_blocks_missing_replay_or_acceptance_evidence():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidates": [
            {
                "candidate_id": "candidate-unvalidated",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_library_id": "ZX-XINGCE-UNVALIDATED",
                "target_shelf": "xingce",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/unvalidated.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
            }
        ],
        "actions": [
            {"candidate_id": "candidate-unvalidated", "action": "approve", "reason": "missing validation"},
        ],
    })
    report = lib.build_experience_validation_report_dry_run({
        "experience_review_actions": review,
    })
    gate = lib.build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": report,
        "authorization": {
            "confirm_review_action_intent": True,
            "confirm_source_refs_checked": True,
            "confirm_replay_or_validation_checked": True,
            "confirm_no_raw_or_markdown_write": True,
            "operator": "local-test",
            "reason": "validation report attached",
        },
    })

    assert report["report_passed"] is False
    assert report["validation_issue_count"] == 1
    assert "acceptance_checks" in report["validation_issues"][0]["missing"]
    assert "history_validated" in report["validation_issues"][0]["missing"]
    assert "replay_passed" in report["validation_issues"][0]["missing"]
    assert report["validation_reports"][0]["write_performed"] is False
    assert gate["status"] == "blocked"
    assert "validation_report_not_passed" in gate["blocked_reasons"]
    assert gate["write_performed"] is False


def test_experience_validation_receipts_preview_passed_and_failed_without_writes():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidates": [
            {
                "candidate_id": "candidate-validation-receipt-ready",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_library_id": "ZX-VALIDATION-RECEIPT-READY",
                "target_shelf": "xingce",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/validation-ready.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
                "acceptance_checks": ["record doctor passed"],
            },
            {
                "candidate_id": "candidate-validation-receipt-blocked",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_library_id": "ZX-VALIDATION-RECEIPT-BLOCKED",
                "target_shelf": "xingce",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/validation-blocked.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
            },
        ],
        "actions": [
            {"candidate_id": "candidate-validation-receipt-ready", "action": "approve", "reason": "ready"},
            {"candidate_id": "candidate-validation-receipt-blocked", "action": "approve", "reason": "missing checks"},
        ],
    })
    validation_report = lib.build_experience_validation_report_dry_run({
        "experience_review_actions": review,
        "experience_history": {
            "histories": [
                {"library_id": "ZX-VALIDATION-RECEIPT-READY", "validation_status": "validated", "replay_count": 1},
                {"library_id": "ZX-VALIDATION-RECEIPT-BLOCKED", "validation_status": "validated", "replay_count": 1},
            ]
        },
    })
    review_queue = lib.build_experience_review_queue_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": validation_report,
    })
    receipts = lib.build_experience_validation_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": validation_report,
        "experience_review_queue": review_queue,
    })

    assert receipts["contract"] == "zhixing_library_experience_validation_receipt_schema.v1"
    assert receipts["source_contract"] == "zhixing_library_experience_validation_report.v1"
    assert receipts["dry_run"] is True
    assert receipts["read_only"] is True
    assert receipts["write_performed"] is False
    assert receipts["raw_write_performed"] is False
    assert receipts["xingce_write_performed"] is False
    assert receipts["markdown_write_performed"] is False
    assert receipts["validation_result_write_performed"] is False
    assert receipts["candidate_status_change_performed"] is False
    assert receipts["not_a_new_memory_layer"] is True
    assert receipts["under_tiandao_five_shelves"] is True
    assert receipts["receipt_count"] == 2
    assert receipts["would_allow_apply_gate_count"] == 1
    assert receipts["validation_issue_count"] == 1

    by_candidate = {item["candidate_id"]: item for item in receipts["validation_receipts"]}
    ready = by_candidate["candidate-validation-receipt-ready"]
    blocked = by_candidate["candidate-validation-receipt-blocked"]
    assert ready["receipt_type"] == "experience_validation_receipt"
    assert ready["source_refs_checked"] is True
    assert ready["verbatim_excerpt_checked"] is True
    assert ready["acceptance_checks_checked"] is True
    assert ready["history_or_replay_evidence"] is True
    assert ready["would_allow_apply_gate"] is True
    assert ready["write_performed"] is False
    assert ready["recommended_next_step"] == "attach_validation_receipt_to_apply_gate_after_human_authorization"
    assert blocked["would_allow_apply_gate"] is False
    assert "acceptance_checks" in blocked["validation_issues"]
    assert blocked["recommended_next_step"] == "add_acceptance_checks_before_validation_receipt"
    assert blocked["write_performed"] is False


def test_experience_apply_gate_prefers_validation_receipts_over_report():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidates": [
            {
                "candidate_id": "candidate-gate-validation-receipt",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_library_id": "ZX-GATE-VALIDATION-RECEIPT",
                "target_shelf": "xingce",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/gate-validation-receipt.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
                "acceptance_checks": ["record doctor passed"],
            }
        ],
        "actions": [
            {"candidate_id": "candidate-gate-validation-receipt", "action": "approve", "reason": "receipt gate"},
        ],
    })
    report = lib.build_experience_validation_report_dry_run({
        "experience_review_actions": review,
        "experience_history": {
            "histories": [
                {"library_id": "ZX-GATE-VALIDATION-RECEIPT", "validation_status": "validated", "replay_count": 1}
            ]
        },
    })
    receipts = lib.build_experience_validation_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": report,
    })
    gate = lib.build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": report,
        "experience_validation_receipt_schema": receipts,
        "authorization": {
            "confirm_review_action_intent": True,
            "confirm_source_refs_checked": True,
            "confirm_replay_or_validation_checked": True,
            "confirm_no_raw_or_markdown_write": True,
            "operator": "local-test",
            "reason": "validation receipt attached",
        },
    })

    assert gate["status"] == "ready"
    assert gate["validation_receipt_preferred_for_future_apply"] is True
    assert gate["validation_receipt_attached"] is True
    assert gate["validation_receipt_count"] == 1
    assert gate["validation_receipts_allow_gate"] is True
    assert gate["validation_receipt_blocked"] == []
    assert gate["receipt_preview"]["validation_receipt_attached"] is True
    assert gate["receipt_preview"]["validation_receipt_count"] == 1
    assert gate["write_performed"] is False
    assert gate["markdown_write_performed"] is False


def test_experience_apply_gate_blocks_failed_validation_receipts_without_writes():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidates": [
            {
                "candidate_id": "candidate-gate-validation-receipt-blocked",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_library_id": "ZX-GATE-VALIDATION-RECEIPT-BLOCKED",
                "target_shelf": "xingce",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/gate-validation-blocked.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
            }
        ],
        "actions": [
            {"candidate_id": "candidate-gate-validation-receipt-blocked", "action": "approve", "reason": "blocked receipt"},
        ],
    })
    report = lib.build_experience_validation_report_dry_run({"experience_review_actions": review})
    receipts = lib.build_experience_validation_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": report,
    })
    gate = lib.build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
        "experience_validation_receipt_schema": receipts,
        "authorization": {
            "confirm_review_action_intent": True,
            "confirm_source_refs_checked": True,
            "confirm_replay_or_validation_checked": True,
            "confirm_no_raw_or_markdown_write": True,
            "operator": "local-test",
            "reason": "validation receipt attached",
        },
    })

    assert gate["status"] == "blocked"
    assert "validation_receipt_not_passed" in gate["blocked_reasons"]
    assert "validation_report_not_passed" not in gate["blocked_reasons"]
    assert gate["validation_receipt_attached"] is True
    assert gate["validation_receipts_allow_gate"] is False
    assert gate["validation_receipt_issue_count"] == 1
    assert gate["validation_receipt_blocked"][0]["candidate_id"] == "candidate-gate-validation-receipt-blocked"
    assert "acceptance_checks" in gate["validation_receipt_blocked"][0]["validation_issues"]
    assert gate["write_performed"] is False
    assert gate["xingce_write_performed"] is False
    assert gate["markdown_write_performed"] is False


def test_experience_review_queue_triages_candidates_without_status_changes():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidates": [
            {
                "candidate_id": "candidate-ready",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_library_id": "ZX-READY",
                "target_shelf": "xingce",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/ready.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
                "acceptance_checks": ["record doctor passed"],
            },
            {
                "candidate_id": "candidate-missing-source",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_library_id": "ZX-MISSING-SOURCE",
                "target_shelf": "xingce",
                "acceptance_checks": ["record doctor passed"],
            },
            {
                "candidate_id": "candidate-errata",
                "candidate_type": "experience_errata_candidate",
                "target_library_id": "ZX-ERRATA",
                "target_shelf": "errata",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/errata.jsonl"},
                "verbatim_excerpt": "旧经验已经失效。",
            },
        ],
        "actions": [
            {"candidate_id": "candidate-ready", "action": "approve", "reason": "ready"},
            {"candidate_id": "candidate-missing-source", "action": "approve", "reason": "missing source"},
            {"candidate_id": "candidate-errata", "action": "reject", "reason": "invalidated"},
        ],
    })
    validation_report = lib.build_experience_validation_report_dry_run({
        "experience_review_actions": review,
        "experience_history": {
            "histories": [
                {"library_id": "ZX-READY", "validation_status": "validated", "replay_count": 1},
                {"library_id": "ZX-MISSING-SOURCE", "validation_status": "validated", "replay_count": 1},
                {"library_id": "ZX-ERRATA", "validation_status": "has_failed_replay", "replay_count": 1},
            ]
        },
    })
    queue = lib.build_experience_review_queue_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": validation_report,
    })

    assert queue["contract"] == "zhixing_library_experience_review_queue.v1"
    assert queue["dry_run"] is True
    assert queue["read_only"] is True
    assert queue["write_performed"] is False
    assert queue["raw_write_performed"] is False
    assert queue["xingce_write_performed"] is False
    assert queue["markdown_write_performed"] is False
    assert queue["not_a_new_memory_layer"] is True
    assert queue["queue_count"] == 3
    assert queue["bucket_counts"]["ready_for_review"] == 1
    assert queue["bucket_counts"]["needs_source_evidence"] == 1
    assert queue["bucket_counts"]["should_errata"] == 1
    assert queue["buckets"]["ready_for_review"][0]["recommended_next_step"] == "review_then_attach_authorized_apply_gate"
    assert queue["buckets"]["needs_source_evidence"][0]["recommended_next_step"] == "restore_source_refs_or_verbatim_excerpt"
    assert queue["buckets"]["should_errata"][0]["recommended_next_step"] == "prepare_errata_or_rejection_receipt"
    assert queue["all_writes_blocked"] is True


def test_experience_apply_receipt_schema_defines_rollback_supersede_errata_without_writes():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidates": [
            {
                "candidate_id": "candidate-apply",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_shelf": "xingce",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/apply-receipt.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
            },
            {
                "candidate_id": "candidate-errata",
                "candidate_type": "experience_errata_candidate",
                "target_shelf": "errata",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/errata-receipt.jsonl"},
                "verbatim_excerpt": "这条经验缺少验收。",
            },
        ],
        "actions": [
            {"candidate_id": "candidate-apply", "action": "approve", "reason": "apply shape"},
            {"candidate_id": "candidate-errata", "action": "reject", "reason": "errata shape"},
        ],
    })
    gate = lib.build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
        "authorization": {
            "confirm_review_action_intent": True,
            "confirm_source_refs_checked": True,
            "confirm_replay_or_validation_checked": True,
            "confirm_no_raw_or_markdown_write": True,
            "operator": "local-test",
            "reason": "schema only",
        },
    })
    schema = lib.build_experience_apply_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_review_apply_gate": gate,
    })

    assert schema["contract"] == "zhixing_library_experience_apply_receipt_schema.v1"
    assert schema["source_contract"] == "zhixing_library_experience_review_apply_gate.v1"
    assert schema["dry_run"] is True
    assert schema["read_only"] is True
    assert schema["durable_write_performed"] is False
    assert schema["write_performed"] is False
    assert schema["raw_write_performed"] is False
    assert schema["xingce_write_performed"] is False
    assert schema["errata_write_performed"] is False
    assert schema["markdown_write_performed"] is False
    assert schema["receipt_count"] == 2
    assert "experience_apply_receipt" in schema["receipt_types"]
    assert "experience_errata_receipt" in schema["receipt_types"]
    assert schema["source_evidence_complete"] is True
    assert schema["source_evidence_issue_count"] == 0
    assert len(schema["rollback_plans"]) == 2
    assert all(receipt["rollback_plan"]["receipt_type"] == "experience_rollback_receipt" for receipt in schema["receipts"])
    assert all(receipt["source_evidence_complete"] is True for receipt in schema["receipts"])
    assert all(receipt["future_apply_allowed_by_schema"] is True for receipt in schema["receipts"])
    assert all(receipt["durable_write_performed"] is False for receipt in schema["receipts"])
    assert all(plan["write_performed"] is False for plan in schema["rollback_plans"])


def test_experience_apply_receipt_schema_blocks_apply_when_source_evidence_missing():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidate": {
            "candidate_id": "candidate-missing-evidence",
            "candidate_type": "experience_xingce_validation_candidate",
            "target_shelf": "xingce",
        },
        "candidate_id": "candidate-missing-evidence",
        "action": "approve",
        "reason": "missing source proof",
    })
    gate = lib.build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
        "authorization": {
            "confirm_review_action_intent": True,
            "confirm_source_refs_checked": True,
            "confirm_replay_or_validation_checked": True,
            "confirm_no_raw_or_markdown_write": True,
            "operator": "local-test",
            "reason": "schema only",
        },
    })
    schema = lib.build_experience_apply_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_review_apply_gate": gate,
    })

    assert schema["source_evidence_complete"] is False
    assert schema["source_evidence_issue_count"] == 1
    assert schema["source_evidence_issues"][0]["candidate_id"] == "candidate-missing-evidence"
    assert "source_refs" in schema["source_evidence_issues"][0]["missing"]
    assert schema["receipts"][0]["future_apply_allowed_by_schema"] is False
    assert schema["receipts"][0]["durable_write_performed"] is False
    assert schema["receipts"][0]["write_performed"] is False


def test_experience_apply_package_collects_gate_receipts_and_rollback_without_writes():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidates": [
            {
                "candidate_id": "candidate-apply-package",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_library_id": "ZX-APPLY-PACKAGE",
                "target_shelf": "xingce",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/apply-package.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
                "acceptance_checks": ["record doctor passed"],
            }
        ],
        "actions": [
            {"candidate_id": "candidate-apply-package", "action": "approve", "reason": "package preview"},
        ],
    })
    validation_report = lib.build_experience_validation_report_dry_run({
        "experience_review_actions": review,
        "experience_history": {
            "histories": [
                {"library_id": "ZX-APPLY-PACKAGE", "validation_status": "validated", "replay_count": 1}
            ]
        },
    })
    validation_receipts = lib.build_experience_validation_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": validation_report,
    })
    gate = lib.build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
        "experience_validation_receipt_schema": validation_receipts,
        "authorization": {
            "confirm_review_action_intent": True,
            "confirm_source_refs_checked": True,
            "confirm_replay_or_validation_checked": True,
            "confirm_no_raw_or_markdown_write": True,
            "operator": "local-test",
            "reason": "package preview",
        },
    })
    apply_receipts = lib.build_experience_apply_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_review_apply_gate": gate,
    })
    package = lib.build_experience_apply_package_dry_run({
        "experience_review_actions": review,
        "experience_validation_receipt_schema": validation_receipts,
        "experience_review_apply_gate": gate,
        "experience_apply_receipt_schema": apply_receipts,
    })

    assert package["contract"] == "zhixing_library_experience_apply_package.v1"
    assert package["dry_run"] is True
    assert package["read_only"] is True
    assert package["write_performed"] is False
    assert package["raw_write_performed"] is False
    assert package["xingce_write_performed"] is False
    assert package["markdown_write_performed"] is False
    assert package["apply_receipt_write_performed"] is False
    assert package["candidate_status_change_performed"] is False
    assert package["not_a_new_memory_layer"] is True
    assert package["under_tiandao_five_shelves"] is True
    assert package["package_status"] == "ready"
    assert package["ready_for_authorized_apply"] is True
    assert package["authorized_apply_performed"] is False
    assert package["blocked_reasons"] == []
    assert package["review_action_count"] == 1
    assert package["validation_receipt_count"] == 1
    assert package["apply_receipt_count"] == 1
    assert package["rollback_plan_count"] == 1
    assert package["target_shelf_counts"]["xingce"] == 1
    assert package["package_items"][0]["candidate_id"] == "candidate-apply-package"
    assert package["package_items"][0]["future_apply_allowed_by_schema"] is True
    assert package["package_items"][0]["would_write"] is False
    assert package["rollback_plans"][0]["write_performed"] is False


def test_experience_apply_package_blocks_without_ready_gate_or_receipts():
    lib = importlib.import_module("src.zhixing_library")
    package = lib.build_experience_apply_package_dry_run({})

    assert package["package_status"] == "blocked"
    assert package["ready_for_authorized_apply"] is False
    assert "missing_review_actions" in package["blocked_reasons"]
    assert "missing_validation_receipts" in package["blocked_reasons"]
    assert "apply_gate_not_ready" in package["blocked_reasons"]
    assert package["write_performed"] is False
    assert package["durable_write_performed"] is False
    assert package["candidate_status_change_performed"] is False


def test_experience_flow_overview_orders_contracts_and_blocks_without_writes():
    lib = importlib.import_module("src.zhixing_library")

    overview = lib.build_experience_flow_overview_dry_run({})
    stages = overview["stage_statuses"]

    assert overview["contract"] == "zhixing_library_experience_flow_overview.v1"
    assert overview["dry_run"] is True
    assert overview["read_only"] is True
    assert overview["write_performed"] is False
    assert overview["raw_write_performed"] is False
    assert overview["xingce_write_performed"] is False
    assert overview["markdown_write_performed"] is False
    assert overview["candidate_status_change_performed"] is False
    assert overview["not_a_new_memory_layer"] is True
    assert overview["under_tiandao_five_shelves"] is True
    assert overview["stage_count"] == 8
    assert overview["ready_stage_count"] == 0
    assert overview["blocked_stage_count"] == 8
    assert overview["flow_status"] == "blocked_preview"
    assert [item["stage"] for item in stages] == [
        "experience_evolution",
        "review_action",
        "validation_report",
        "validation_receipt",
        "review_queue",
        "apply_gate",
        "apply_receipt_schema",
        "apply_package",
    ]
    assert all(item["writes_allowed"] is False for item in stages)
    assert all(item["write_performed"] is False for item in stages)
    assert "write_xingce" in overview["forbidden_everywhere"]
    assert "auto_adopt_experience" in overview["forbidden_everywhere"]


def test_experience_flow_overview_can_report_ready_preview_without_apply():
    lib = importlib.import_module("src.zhixing_library")
    review = lib.build_experience_review_actions_dry_run({
        "candidates": [
            {
                "candidate_id": "candidate-flow-overview",
                "candidate_type": "experience_xingce_validation_candidate",
                "target_library_id": "ZX-FLOW-OVERVIEW",
                "target_shelf": "xingce",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/flow-overview.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
                "acceptance_checks": ["record doctor passed"],
            }
        ],
        "actions": [
            {"candidate_id": "candidate-flow-overview", "action": "approve", "reason": "flow overview"},
        ],
    })
    validation_report = lib.build_experience_validation_report_dry_run({
        "experience_review_actions": review,
        "experience_history": {
            "histories": [
                {"library_id": "ZX-FLOW-OVERVIEW", "validation_status": "validated", "replay_count": 1}
            ]
        },
    })
    validation_receipts = lib.build_experience_validation_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": validation_report,
    })
    queue = lib.build_experience_review_queue_dry_run({
        "experience_review_actions": review,
        "experience_validation_report": validation_report,
    })
    gate = lib.build_experience_review_apply_gate_dry_run({
        "experience_review_actions": review,
        "experience_validation_receipt_schema": validation_receipts,
        "authorization": {
            "confirm_review_action_intent": True,
            "confirm_source_refs_checked": True,
            "confirm_replay_or_validation_checked": True,
            "confirm_no_raw_or_markdown_write": True,
            "operator": "local-test",
            "reason": "flow overview",
        },
    })
    apply_receipts = lib.build_experience_apply_receipt_schema_dry_run({
        "experience_review_actions": review,
        "experience_review_apply_gate": gate,
    })
    package = lib.build_experience_apply_package_dry_run({
        "experience_review_actions": review,
        "experience_validation_receipt_schema": validation_receipts,
        "experience_review_apply_gate": gate,
        "experience_apply_receipt_schema": apply_receipts,
    })
    overview = lib.build_experience_flow_overview_dry_run({
        "experience_evolution": {"candidate_count": 1},
        "experience_review_actions": review,
        "experience_validation_report": validation_report,
        "experience_validation_receipt_schema": validation_receipts,
        "experience_review_queue": queue,
        "experience_review_apply_gate": gate,
        "experience_apply_receipt_schema": apply_receipts,
        "experience_apply_package": package,
    })

    assert overview["flow_status"] == "ready_for_future_authorized_apply"
    assert overview["ready_stage_count"] == 8
    assert overview["blocked_stage_count"] == 0
    assert overview["write_performed"] is False
    assert overview["candidate_status_change_performed"] is False


def test_library_index_projection_is_ai_readable_first_page_not_new_layer():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.build_library_index_projection_dry_run({
        "title": "本轮馆藏目录",
        "per_shelf_limit": 2,
        "records": [
            {
                "type": "preference_memory",
                "library_id": "ZX-ZHIYI-INDEX",
                "summary": "用户偏好：先给结论。",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/index-pref.jsonl"},
                "verbatim_excerpt": "先给结论。",
                "supersedes": [],
                "conflicts_with": [],
            },
            {
                "_type": "xingce_work_experience_candidate",
                "library_id": "ZX-XINGCE-INDEX",
                "summary": "发布前先跑记录医生。",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/index-xingce.jsonl"},
                "verbatim_excerpt": "发布前先跑记录医生。",
                "acceptance_checks": ["record doctor passed"],
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "index-xingce", "lifecycle_status": "candidate"},
            },
            {
                "type": "case_memory",
                "library_shelf": "errata",
                "library_id": "ZX-ERRATA-INDEX",
                "summary": "旧发布记录已废弃。",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/index-errata.jsonl"},
                "verbatim_excerpt": "旧发布记录已废弃。",
                "status": "superseded",
                "supersedes": ["ZX-XINGCE-OLD"],
                "conflicts_with": ["ZX-XINGCE-OLD"],
            },
        ],
    })

    index = result["index"]
    markdown = result["markdown"]

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["markdown_write_performed"] is False
    assert result["not_a_new_memory_layer"] is True
    assert result["requires_obsidian"] is False
    assert result["ai_readable_projection_profile"] == "five_shelf_ai_readable_projection.v2026.6.17"
    assert index["ai_readable_projection_profile"] == "five_shelf_ai_readable_projection.v2026.6.17"
    assert index["projection_layer"] == "L0_library_index_projection"
    assert index["source_authority_layer"] == "L2_raw_source_record"
    assert index["shelf_index"]["zhiyi"]["count"] == 1
    assert index["shelf_index"]["xingce"]["entries"][0]["library_id"] == "ZX-XINGCE-INDEX"
    assert index["shelf_index"]["errata"]["entries"][0]["attention"] == [
        "errata_record",
        "has_conflict",
        "supersedes_other_record",
    ]
    assert "contract: \"zhixing_library_index_projection.v1\"" in markdown
    assert "type: \"Library Index Projection\"" in markdown
    assert "projection_layer: \"L0_library_index_projection\"" in markdown
    assert "### zhiyi" in markdown
    assert "`ZX-XINGCE-INDEX`" in markdown


def test_zhixing_loop_manifest_defines_seven_steps_and_offense_metric():
    lib = importlib.import_module("src.zhixing_library")

    loop = lib.zhixing_loop_manifest()
    step_ids = [step["id"] for step in loop["steps"]]
    shelves = {step["shelf"] for step in loop["steps"]}
    metrics = {metric["id"]: metric for metric in loop["flight_metrics"]}

    assert len(loop["steps"]) == 7
    assert step_ids == [
        "preserve_raw",
        "zhiyi_source_backed_recall",
        "xingce_work_experience",
        "toolbook_platform_facts",
        "errata_conflict_handling",
        "replay_validation",
        "feed_next_recall_or_action",
    ]
    assert {"raw", "zhiyi", "xingce", "toolbook", "errata"}.issubset(shelves)
    assert loop["connector_persona"]["zh_name"] == "接引者"
    assert loop["connector_persona"]["zh_actions"] == ["召唤", "提示", "守门", "引路"]
    assert loop["connector_persona"]["zhiyi_remains_implicit"] is True
    assert loop["metric_shape"]["defense_count"] == 4
    assert loop["metric_shape"]["offense_count"] == 1
    assert loop["metric_shape"]["offense_metric"] == "proactive_resurfacing"
    assert loop["metric_shape"]["offense_metric_must_not_be_diluted"] is True
    assert metrics["proactive_resurfacing"]["kind"] == "offense"


def test_replay_dry_run_scores_zhiyi_plus_xingce_and_proactive_resurfacing():
    lib = importlib.import_module("src.zhixing_library")
    result = lib.run_replay_dry_run({
        "case": {
            "case_id": "case-proactive",
            "query": "继续这个平台配置问题",
            "expected_source_refs": ["raw/probe_logs/hermes-profile-effective-config.jsonl"],
            "expected_library_ids": ["ZX-XINGCE-KNOWN"],
            "expected_behavior_markers": ["先查 profile config"],
            "forbidden_repeated_mistakes": ["改 root config 当默认继承"],
            "required_acceptance_checks": ["hermes profile show"],
            "expected_proactive_resurfacing": ["profile 无 config 显示 auto"],
        },
        "records": [
            {
                "type": "preference_memory",
                "exp_id": "pref-answer-style",
                "summary": "用户偏好：先给结论。",
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "raw/probe_logs/preference.jsonl",
                },
                "verbatim_excerpt": "用户原话：先给结论。",
                "supersedes": [],
                "conflicts_with": [],
            },
            {
                "_type": "xingce_work_experience_candidate",
                "library_id": "ZX-XINGCE-KNOWN",
                "exp_id": "xingce-hermes-profile",
                "summary": "Hermes 平台配置经验：先查 profile config，profile 无 config 显示 auto。",
                "detail": "不要改 root config 当默认继承；验收用 hermes profile show。",
                "source_refs": {
                    "source_system": "probe",
                    "source_path": "raw/probe_logs/hermes-profile-effective-config.jsonl",
                },
                "verbatim_excerpt": "profile 无 config 显示 auto；hermes profile show 可验收。",
                "acceptance_checks": ["hermes profile show"],
                "supersedes": [],
                "conflicts_with": [],
                "_xingce": {"candidate_id": "xingce-hermes-profile", "lifecycle_status": "candidate"},
            },
        ],
    })

    by_mode = {item["memory_mode"]: item for item in result["results"]}

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["summary"]["best_mode"] == "zhiyi_plus_xingce"
    assert result["summary"]["improvement_over_no_memory"] > 0
    assert result["summary"]["proactive_resurfacing_passed"] is True
    assert result["summary"]["offense_metric_must_not_be_diluted"] is True
    assert by_mode["no_memory"]["offense_metric"]["passed"] is False
    assert by_mode["zhiyi_only"]["offense_metric"]["passed"] is False
    assert by_mode["zhiyi_plus_xingce"]["offense_metric"]["passed"] is True
    assert "ZX-XINGCE-KNOWN" in by_mode["zhiyi_plus_xingce"]["used_library_ids"]
    feedback = result["feedback_candidates"]
    candidate_types = set(feedback["candidate_types"])
    assert feedback["write_performed"] is False
    assert feedback["authorization_required_for_apply"] is True
    assert "replay_adoption_candidate" in candidate_types
    assert "proactive_resurfacing_candidate" in candidate_types
    assert any(
        candidate["target_library_id"] == "ZX-XINGCE-KNOWN"
        for candidate in feedback["candidates"]
        if candidate["candidate_type"] == "replay_adoption_candidate"
    )
    assert any(
        candidate["resurfacing_marker"] == "profile 无 config 显示 auto"
        for candidate in feedback["candidates"]
        if candidate["candidate_type"] == "proactive_resurfacing_candidate"
    )


def test_benchmark_dry_run_aggregates_real_task_set_before_queue():
    lib = importlib.import_module("src.zhixing_library")
    result = lib.run_benchmark_dry_run({
        "cases": [
            {
                "case_id": "hermes-profile-config",
                "query": "继续 Hermes 配置真实生效验证",
                "expected_source_refs": ["raw/probe_logs/hermes-profile-effective-config.jsonl"],
                "expected_library_ids": ["ZX-XINGCE-HERMES"],
                "expected_behavior_markers": ["先查 profile config"],
                "forbidden_repeated_mistakes": ["改 root config 当默认继承"],
                "required_acceptance_checks": ["hermes profile show"],
                "expected_proactive_resurfacing": ["profile 无 config 显示 auto"],
                "records": [
                    {
                        "type": "preference_memory",
                        "exp_id": "pref-concise",
                        "summary": "用户偏好：先给结论。",
                        "source_refs": {
                            "source_system": "codex",
                            "source_path": "raw/probe_logs/preference.jsonl",
                        },
                        "verbatim_excerpt": "用户原话：先给结论。",
                        "supersedes": [],
                        "conflicts_with": [],
                    },
                    {
                        "_type": "xingce_work_experience_candidate",
                        "library_id": "ZX-XINGCE-HERMES",
                        "exp_id": "xingce-hermes-profile",
                        "summary": "Hermes 平台配置经验：先查 profile config，profile 无 config 显示 auto。",
                        "detail": "不要改 root config 当默认继承；验收用 hermes profile show。",
                        "source_refs": {
                            "source_system": "probe",
                            "source_path": "raw/probe_logs/hermes-profile-effective-config.jsonl",
                        },
                        "verbatim_excerpt": "profile 无 config 显示 auto；hermes profile show 可验收。",
                        "acceptance_checks": ["hermes profile show"],
                        "supersedes": [],
                        "conflicts_with": [],
                        "_xingce": {"candidate_id": "xingce-hermes-profile", "lifecycle_status": "candidate"},
                    },
                ],
            },
            {
                "case_id": "openclaw-before-dispatch",
                "query": "接手 OpenClaw before_dispatch 入口",
                "expected_source_refs": ["raw/probe_logs/openclaw-before-dispatch.jsonl"],
                "expected_library_ids": ["ZX-XINGCE-OPENCLAW"],
                "expected_behavior_markers": ["先核对 18789 和 9860 的分工"],
                "forbidden_repeated_mistakes": ["把 9860 说成 OpenClaw WebUI 端口"],
                "required_acceptance_checks": ["检查插件 endpointUrl"],
                "expected_proactive_resurfacing": ["OpenClaw WebUI 默认端口是 18789"],
                "records": [
                    {
                        "_type": "xingce_work_experience_candidate",
                        "library_id": "ZX-XINGCE-OPENCLAW",
                        "exp_id": "xingce-openclaw-port",
                        "summary": "OpenClaw 接入经验：先核对 18789 和 9860 的分工；OpenClaw WebUI 默认端口是 18789。",
                        "detail": "不要把 9860 说成 OpenClaw WebUI 端口；检查插件 endpointUrl。",
                        "source_refs": {
                            "source_system": "probe",
                            "source_path": "raw/probe_logs/openclaw-before-dispatch.jsonl",
                        },
                        "verbatim_excerpt": "OpenClaw WebUI 默认端口是 18789；9860 是忆凡尘 dialog entry。",
                        "acceptance_checks": ["检查插件 endpointUrl"],
                        "supersedes": [],
                        "conflicts_with": [],
                        "_xingce": {"candidate_id": "xingce-openclaw-port", "lifecycle_status": "candidate"},
                    },
                ],
            },
        ],
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["model_call_performed"] is False
    assert result["case_count"] == 2
    assert result["summary"]["best_mode"] == "zhiyi_plus_xingce"
    assert result["summary"]["improvement_over_zhiyi_only"] > 0
    assert result["summary"]["xingce_signal_detected"] is True
    assert result["summary"]["recommendation"] == "proceed_to_replay_feedback_queue_design"
    assert result["summary"]["machine_ascension_not_claimed"] is True
    assert result["contract"]["ok"] is True
    assert result["totals"]["zhiyi_plus_xingce"]["proactive_resurfacing_passed"] == 2
    assert result["totals"]["zhiyi_only"]["proactive_resurfacing_passed"] == 0


def test_benchmark_dry_run_empty_cases_does_not_claim_signal():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.run_benchmark_dry_run({"cases": []})

    assert result["ok"] is True
    assert result["case_count"] == 0
    assert result["summary"]["best_mode"] == ""
    assert result["summary"]["xingce_signal_detected"] is False
    assert result["summary"]["recommendation"] == "provide_real_task_cases_before_benchmark"
    assert result["write_performed"] is False


def test_public_real_task_fixture_feeds_benchmark_runner():
    lib = importlib.import_module("src.zhixing_library")
    fixture_path = Path(__file__).parent / "fixtures" / "zhixing_real_task_benchmark_public.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    result = lib.run_benchmark_dry_run(fixture)

    assert result["ok"] is True
    assert result["case_count"] == 10
    assert result["contract"]["ok"] is True
    assert result["summary"]["best_mode"] == "zhiyi_plus_xingce"
    assert result["summary"]["xingce_signal_detected"] is True
    assert result["summary"]["improvement_over_zhiyi_only"] > 0
    assert result["summary"]["recommendation"] == "proceed_to_replay_feedback_queue_design"
    assert result["summary"]["machine_ascension_not_claimed"] is True
    assert result["totals"]["zhiyi_plus_xingce"]["proactive_resurfacing_passed"] == 10
    assert result["totals"]["zhiyi_only"]["proactive_resurfacing_passed"] == 0
    assert result["write_performed"] is False
    assert result["model_call_performed"] is False


def test_build_toolbook_candidate_accepts_probe_log_source_and_stays_dry_run():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.build_toolbook_candidate({
        "platform": "Hermes",
        "environment": "WSL isolated profile",
        "observed_behavior": "profile without config.yaml shows auto and does not inherit root config",
        "raw_source_path": "raw/probe_logs/hermes-profile-config-auto.jsonl",
        "verbatim_excerpt": "hermes profile show sample-a -> model: (auto)",
        "command_transcript_ref": "raw/probe_logs/hermes-profile-config-auto.jsonl",
    })

    candidate = result["candidate"]
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert candidate["candidate_type"] == "toolbook_candidate"
    assert candidate["library_shelf"] == "toolbook"
    assert candidate["library_card"]["evidence_contract"]["valid_experience_record"] is True
    assert candidate["toolbook_write_performed"] is False
    assert "tool" in candidate["typed_graph"]["node_types"]


def test_hermes_profile_probe_can_be_shaped_as_public_safe_toolbook_candidate():
    lib = importlib.import_module("src.zhixing_library")

    transcript = "\n".join([
        "hermes profile show sample-with-config -> Model: example-model-b",
        "hermes profile show sample-without-config -> Model: (auto)",
        "hermes profile show sample-lowercase-soul -> SOUL.md: not configured",
        "hermes profile show sample-uppercase-soul -> SOUL.md: exists",
    ])
    result = lib.build_toolbook_candidate({
        "platform": "Hermes",
        "environment": "Windows and WSL/Linux profile probe",
        "observed_behavior": (
            "Hermes profile config.yaml is read immediately; profiles without "
            "config.yaml stay auto instead of inheriting root config; lowercase "
            "soul files are not recognized on case-sensitive systems."
        ),
        "raw_source_path": "raw/probe_logs/hermes-profile-effective-config.jsonl",
        "verbatim_excerpt": transcript,
        "command_transcript_ref": "raw/probe_logs/hermes-profile-effective-config.jsonl",
        "applicable_scope": "Hermes profile materialization and model selection",
        "acceptance_checks": [
            "Hermes profile show reports the configured model for a profile with config.yaml.",
            "Hermes profile show reports Model: (auto) for a profile without config.yaml.",
            "Case-sensitive systems recognize SOUL.md and do not treat lowercase soul.md as equivalent.",
        ],
    })

    candidate = result["candidate"]
    card = candidate["library_card"]

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert candidate["library_shelf"] == "toolbook"
    assert "raw/probe_logs/hermes-profile-effective-config.jsonl" == candidate["source_refs"]["source_path"]
    assert "Model: (auto)" in card["verbatim_excerpt"]
    assert "SOUL.md: not configured" in card["verbatim_excerpt"]
    assert card["evidence_contract"]["toolbook_raw_source_ok"] is True
    assert any(node["type"] == "tool" for node in card["typed_graph"]["nodes"])
    assert "typed_graph" in card["matched_by"]
    assert candidate["raw_write_performed"] is False
    assert candidate["toolbook_write_performed"] is False


def test_build_toolbook_candidate_rejects_non_raw_toolbook_source():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.build_toolbook_candidate({
        "platform": "Hermes",
        "environment": "WSL isolated profile",
        "observed_behavior": "profile without config.yaml shows auto",
        "raw_source_path": "notes/hermes-profile-config-auto.md",
        "verbatim_excerpt": "profile show output",
    })

    assert result["ok"] is False
    assert "toolbook_raw_source" in result["validation"]["missing"]


def test_validate_toolbook_candidate_enforces_toolbook_raw_source_for_direct_payload():
    lib = importlib.import_module("src.zhixing_library")

    result = lib.validate_toolbook_candidate({
        "candidate_type": "toolbook_candidate",
        "type": "toolbook_candidate",
        "platform": "Hermes",
        "environment": "local validation probe",
        "observed_behavior": "platform probe facts need raw probe-log sources",
        "source_refs": {"source_system": "probe", "source_path": "notes/not-raw.md"},
        "verbatim_excerpt": "sample output",
        "status": "candidate",
        "supersedes": [],
        "conflicts_with": [],
        "write_performed": False,
    })

    assert result["ok"] is False
    assert result["library_card"]["shelf"] == "toolbook"
    assert result["library_card"]["evidence_contract"]["toolbook_raw_source_required"] is True
    assert "toolbook_raw_source" in result["missing"]
