import importlib


def test_agent_work_preflight_classifies_existing_miswired_and_scope_gap():
    mod = importlib.import_module("src.agent_work_preflight")

    existing = mod.build_agent_work_preflight(
        "不要新造 Obsidian 那种旁路知识层",
        consumer="codex",
        request_id="work-preflight-existing",
        preflight_payload={
            "contract": "zhixing_preflight.v2026.6.20",
            "decision": "surface",
            "should_surface": True,
            "memory_scope": "active",
            "active_layers_used": ["same_project_workspace"],
            "must_surface": [
                {
                    "library_id": "ZX-XINGCE-LIBRARY-PROJECTION",
                    "library_shelf": "xingce",
                    "title": "Library Note Projection",
                    "summary": "已有馆藏注记投影机制，不要新造旁路知识层。",
                    "source_system": "codex",
                    "source_path": "raw/probe_logs/library-projection.jsonl",
                    "raw_evidence_status": "raw_offset",
                    "project_id": "memcore-cloud",
                }
            ],
            "do_not_repeat": ["不要新造 Obsidian 那种旁路知识层"],
            "acceptance_checks": ["先查 Library Note Projection 入口"],
            "source_refs_count": 1,
            "raw_items_count": 1,
        },
    )

    assert existing["mode"] == "work_preflight"
    assert existing["contract"] == "agent_work_preflight.v2026.6.20"
    assert existing["classification"] == "already_built_but_forgotten"
    assert existing["should_intervene"] is True
    assert existing["read_only"] is True
    assert existing["write_performed"] is False
    assert existing["evidence"][0]["library_id"] == "ZX-XINGCE-LIBRARY-PROJECTION"
    assert "raw_excerpt" not in existing["evidence"][0]
    assert existing["consumer_receipt"]["receipt_scope"] == "agent_work_preflight_read_only"
    assert existing["consumer_receipt"]["write_performed"] is False
    assert existing["consumer_receipt"]["used_library_ids"] == ["ZX-XINGCE-LIBRARY-PROJECTION"]

    miswired = mod.build_agent_work_preflight(
        "windows123 上 Claude 召回抽屉错了",
        preflight_payload={
            "decision": "surface",
            "should_surface": True,
            "must_surface": [
                {
                    "library_id": "ZX-XINGCE-WINDOWS-CLAUDE",
                    "library_shelf": "xingce",
                    "summary": "source_system 错配导致 claude_desktop 去了 claude_code_cli 之外的抽屉。",
                }
            ],
        },
    )
    assert miswired["classification"] == "built_but_miswired"
    assert "connection path" in miswired["agent_instruction"]

    scope_gap = mod.build_agent_work_preflight(
        "继续",
        preflight_payload={
            "decision": "scope_required",
            "scope_missing": True,
            "recall_status": "active_preflight_anchor_required",
            "must_surface": [],
        },
    )
    assert scope_gap["classification"] == "diagnostic_gap"
    assert scope_gap["next_action"] == "report_binding_gap_without_claiming_memory_empty"

    missing = mod.build_agent_work_preflight(
        "普通问题",
        preflight_payload={"decision": "silent", "must_surface": []},
    )
    assert missing["classification"] == "actually_missing"
    assert missing["should_intervene"] is False


def test_gateway_agent_work_preflight_forces_fast_window_preflight_without_project_scan():
    mod = importlib.import_module("src.agent_work_preflight")
    captured = {}

    def fake_preflight_builder(**kwargs):
        captured.update(kwargs)
        return {
            "contract": "zhixing_preflight.v2026.6.20",
            "decision": "scope_required",
            "scope_missing": True,
            "recall_status": "active_preflight_anchor_required",
            "memory_scope": kwargs.get("memory_scope", ""),
            "must_surface": [],
            "consumer": kwargs.get("consumer", ""),
        }

    result = mod.build_gateway_agent_work_preflight(
        query="开始同步 2026.6.20 到 windows123 和 windows191",
        preflight_builder=fake_preflight_builder,
        preflight_kwargs={
            "consumer": "codex",
            "source_system": "codex",
            "project_id": "memcore-cloud",
            "project_root": "/work/memcore-cloud",
        },
        consumer="codex",
    )

    assert captured["memory_scope"] == "window"
    assert captured["query"] == "开始同步 2026.6.20 到 windows123 和 windows191"
    assert captured["force_task_preflight"] is True
    assert captured["fast_window_preflight"] is True
    assert captured["project_id"] == ""
    assert captured["project_root"] == ""
    assert result["mode"] == "work_preflight"
    assert result["classification"] == "diagnostic_gap"
    assert result["next_action"] == "report_binding_gap_without_claiming_memory_empty"


def test_gateway_agent_work_preflight_uses_fast_path_for_project_window_anchor_by_default():
    mod = importlib.import_module("src.agent_work_preflight")
    captured = {}

    def fake_preflight_builder(**kwargs):
        captured.update(kwargs)
        return {
            "contract": "zhixing_preflight.v2026.6.20",
            "decision": "surface",
            "should_surface": True,
            "recall_status": "preflight_surface_required",
            "memory_scope": kwargs.get("memory_scope", ""),
            "fast_window_preflight": kwargs.get("fast_window_preflight", False),
            "must_surface": [
                {
                    "library_id": "ZX-XINGCE-PROJECT-WINDOW",
                    "library_shelf": "xingce",
                    "summary": "已有项目窗口锚点下的工作经验。",
                    "source_path": "raw/probe_logs/project-window.jsonl",
                }
            ],
        }

    result = mod.build_gateway_agent_work_preflight(
        query="继续 Hermes 平台配置问题，动手前先查已有机制",
        preflight_builder=fake_preflight_builder,
        preflight_kwargs={
            "consumer": "codex",
            "source_system": "codex",
            "canonical_window_id": "project-a",
            "project_id": "memcore-cloud",
        },
        consumer="codex",
    )

    assert captured["fast_window_preflight"] is True
    assert captured["canonical_window_id"] == "project-a"
    assert captured["project_id"] == "memcore-cloud"
    assert result["classification"] == "already_built_but_forgotten"
    assert result["should_intervene"] is True
    assert result["fast_window_preflight"] is True


def test_gateway_agent_work_preflight_full_path_requires_explicit_deep_opt_in():
    mod = importlib.import_module("src.agent_work_preflight")
    captured = {}

    def fake_preflight_builder(**kwargs):
        captured.update(kwargs)
        return {
            "contract": "zhixing_preflight.v2026.6.20",
            "decision": "surface",
            "should_surface": True,
            "recall_status": "preflight_surface_required",
            "memory_scope": kwargs.get("memory_scope", ""),
            "fast_window_preflight": kwargs.get("fast_window_preflight", False),
            "must_surface": [
                {
                    "library_id": "ZX-XINGCE-DEEP",
                    "library_shelf": "xingce",
                    "summary": "显式 deep_work_preflight 才允许项目窗口深扫。",
                    "source_path": "raw/probe_logs/deep-work-preflight.jsonl",
                }
            ],
        }

    result = mod.build_gateway_agent_work_preflight(
        query="继续 Hermes 平台配置问题，明确要求深度扫描已有机制",
        preflight_builder=fake_preflight_builder,
        preflight_kwargs={
            "consumer": "codex",
            "source_system": "codex",
            "canonical_window_id": "project-a",
            "project_id": "memcore-cloud",
            "deep_work_preflight": True,
        },
        consumer="codex",
    )

    assert captured["fast_window_preflight"] is False
    assert "deep_work_preflight" not in captured
    assert captured["canonical_window_id"] == "project-a"
    assert captured["project_id"] == "memcore-cloud"
    assert result["classification"] == "already_built_but_forgotten"
    assert result["should_intervene"] is True
    assert result["fast_window_preflight"] is False


def test_gateway_agent_work_preflight_passes_recall_trajectory_and_index_projection():
    mod = importlib.import_module("src.agent_work_preflight")

    def fake_preflight_builder(**kwargs):
        return {
            "contract": "zhixing_preflight.v2026.6.20",
            "decision": "surface",
            "should_surface": True,
            "recall_status": "preflight_surface_required",
            "memory_scope": kwargs.get("memory_scope", ""),
            "fast_window_preflight": True,
            "fast_recall_path": "canonical_window_index",
            "fast_window_index_status": "hit",
            "zhiyi_layer_skipped_for_fast_preflight": True,
            "raw_recall_trajectory_contract": "raw_recall_trajectory.v2026.6.17",
            "raw_recall_trajectory_policy": "retrieval_steps_are_diagnostics_not_evidence",
            "answer_debug_available": True,
            "answer_debug_capability_contract": "preflight_answer_debug_capability.v2026.6.18",
            "dialog_entry_answer_debug_contract": "dialog_entry_answer_debug.v2026.6.18",
            "evidence_bound_model_contract": "evidence_bound_model.v2026.6.18",
            "evidence_bound_model_gating_contract": "evidence_bound_model_gating.v2026.6.18",
            "answer_model_call_policy": "auto",
            "answer_debug_capability": {
                "contract": "preflight_answer_debug_capability.v2026.6.18",
                "available": True,
                "read_only": True,
                "model_call_performed": False,
                "request_sent": False,
                "dialog_entry_answer_debug_contract": "dialog_entry_answer_debug.v2026.6.18",
                "evidence_bound_model_gating_contract": "evidence_bound_model_gating.v2026.6.18",
                "default_model_call_policy": "auto",
                "final_evidence_authority": "raw_source_refs",
            },
            "raw_recall_trajectory": [
                {
                    "step": "catalog_index_projection",
                    "layer": "L1_library_index_projection",
                    "status": "hit",
                    "used": True,
                    "authority": "navigation_hint_only_raw_evidence_required",
                },
                {
                    "step": "raw_fallback",
                    "layer": "L2_raw_records",
                    "status": "skipped_fast_window_index_hit",
                    "used": False,
                    "authority": "raw_records_are_final_evidence",
                },
            ],
            "library_index_projection_contract": "library_index_projection_receipt.v2026.6.17",
            "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
            "library_index_projection_used": True,
            "library_index_projection_refs_count": 1,
            "library_index_projection_refs": [
                {
                    "projection_kind": "library_index_projection",
                    "authority": "navigation_hint_only_raw_evidence_required",
                    "source_path": "raw/probe_logs/fast-index.jsonl",
                }
            ],
            "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
            "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
            "library_index_projection_soft_weight": 6,
            "preflight_score_profile": [
                {
                    "library_id": "ZX-XINGCE-FAST-INDEX",
                    "library_shelf": "xingce",
                    "score": 79,
                    "base_score": 73,
                    "surface_eligible": True,
                    "library_index_projection_soft_weight_applied": True,
                    "library_index_projection_soft_weight": 6,
                }
            ],
            "must_surface": [
                {
                    "library_id": "ZX-XINGCE-FAST-INDEX",
                    "library_shelf": "xingce",
                    "summary": "已有 fast preflight 馆藏目录投影回执。",
                    "source_path": "raw/probe_logs/fast-index.jsonl",
                    "raw_evidence_status": "raw_index",
                }
            ],
            "source_refs_count": 1,
            "raw_items_count": 1,
        }

    result = mod.build_gateway_agent_work_preflight(
        query="继续，开工前先查已有机制",
        preflight_builder=fake_preflight_builder,
        preflight_kwargs={
            "consumer": "codex",
            "source_system": "codex",
            "canonical_window_id": "project-a",
        },
        consumer="codex",
    )

    assert result["mode"] == "work_preflight"
    assert result["classification"] == "already_built_but_forgotten"
    assert result["library_index_projection_used"] is True
    assert result["library_index_projection_refs_count"] == 1
    assert result["library_index_projection_refs"][0]["authority"] == "navigation_hint_only_raw_evidence_required"
    assert result["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    assert result["library_index_projection_soft_weight_policy"] == "soft_rank_signal_only_raw_evidence_required"
    assert result["library_index_projection_soft_weight"] == 6
    assert result["preflight_score_profile"][0]["library_id"] == "ZX-XINGCE-FAST-INDEX"
    trajectory = {step["step"]: step for step in result["raw_recall_trajectory"]}
    assert trajectory["catalog_index_projection"]["used"] is True
    assert trajectory["raw_fallback"]["status"] == "skipped_fast_window_index_hit"
    assert result["consumer_receipt"]["library_index_projection_used"] is True
    assert result["consumer_receipt"]["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    assert result["consumer_receipt"]["library_index_projection_soft_weight"] == 6
    assert result["consumer_receipt"]["raw_recall_trajectory_contract"] == "raw_recall_trajectory.v2026.6.17"
    assert result["answer_debug_available"] is True
    assert result["answer_debug_capability_contract"] == "preflight_answer_debug_capability.v2026.6.18"
    assert result["dialog_entry_answer_debug_contract"] == "dialog_entry_answer_debug.v2026.6.18"
    assert result["evidence_bound_model_gating_contract"] == "evidence_bound_model_gating.v2026.6.18"
    assert result["answer_debug_capability"]["read_only"] is True
    assert result["answer_debug_capability"]["model_call_performed"] is False
    assert result["consumer_receipt"]["answer_debug_available"] is True
    assert result["consumer_receipt"]["answer_debug_capability_contract"] == "preflight_answer_debug_capability.v2026.6.18"


def test_gateway_work_preflight_override_survives_bottom_preflight_classification():
    raw_gateway = importlib.import_module("src.raw_consumption_gateway")

    result = raw_gateway._work_preflight_from_kwargs({
        "query": "开始施工前先查已有机制",
        "consumer": "codex",
        "source_system": "codex",
        "limit": 1,
        "excerpt_chars": 80,
    })

    assert result["mode"] == "work_preflight"
    assert result["classification"] == "diagnostic_gap"
    assert result["decision"] == "scope_required"
    assert result["prompt_class"] == "task"
    assert result["recall_status"] == "active_preflight_anchor_required"
    assert result["scope_missing"] is True
    assert result["should_intervene"] is True
    assert result["next_action"] == "report_binding_gap_without_claiming_memory_empty"


def test_zhixing_preflight_surfaces_xingce_before_task_answer():
    mod = importlib.import_module("src.zhixing_preflight")

    result = mod.build_zhixing_preflight(
        "继续这个平台配置问题，接下来怎么做",
        consumer="codex",
        request_id="preflight-xingce",
        recall_payload={
            "ok": True,
            "consumer": "codex",
            "memory_scope": "active",
            "memory_base_scope": "active_layered",
            "active_layers_used": ["same_project_workspace"],
            "matched_count": 1,
            "source_refs_count": 1,
            "raw_items_count": 1,
            "items": [
                {
                    "library_id": "ZX-XINGCE-KNOWN",
                    "library_shelf": "xingce",
                    "memory_type": "xingce_work_experience_candidate",
                    "summary": "Hermes 平台配置经验：先查 profile config，profile 无 config 显示 auto。",
                    "raw_excerpt": "不要改 root config 当默认继承；验收用 hermes profile show。",
                    "source_system": "probe",
                    "source_path": "raw/probe_logs/hermes-profile-effective-config.jsonl",
                    "raw_evidence_status": "raw",
                    "active_memory_layer": "same_project_workspace",
                    "matched_by": ["source_refs", "typed_graph", "raw"],
                    "rank_reason": "source_refs available; shelf=xingce",
                    "work_experience": {
                        "work_scenario": "Hermes profile config",
                        "action_strategy": "先查 profile config，再改配置。",
                        "avoid_conditions": ["不要改 root config 当默认继承"],
                        "acceptance_checks": ["hermes profile show"],
                    },
                }
            ],
        },
    )

    assert result["ok"] is True
    assert result["mode"] == "preflight"
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["raw_write_performed"] is False
    assert result["zhiyi_write_performed"] is False
    assert result["xingce_write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["model_call_performed"] is False
    assert result["answer_debug_available"] is True
    assert result["answer_debug_capability_contract"] == "preflight_answer_debug_capability.v2026.6.18"
    assert result["dialog_entry_answer_debug_contract"] == "dialog_entry_answer_debug.v2026.6.18"
    assert result["evidence_bound_model_contract"] == "evidence_bound_model.v2026.6.18"
    assert result["evidence_bound_model_gating_contract"] == "evidence_bound_model_gating.v2026.6.18"
    assert result["answer_model_call_policy"] == "auto"
    assert result["answer_debug_capability"]["read_only"] is True
    assert result["answer_debug_capability"]["model_call_performed"] is False
    assert result["answer_debug_capability"]["request_sent"] is False
    assert result["answer_debug_capability"]["final_evidence_authority"] == "raw_source_refs"
    assert result["decision"] == "surface"
    assert result["auto_entry_contract"] == "zhixing_auto_entry.v2026.6.20"
    assert result["auto_entry_state"] == "enter"
    assert result["auto_entry_allowed"] is True
    assert result["auto_retreat_allowed"] is False
    assert result["auto_entry_reason"] == "proactive_resurfacing_required"
    assert "prompt:continuation" in result["auto_entry_triggered_by"]
    assert "shelf:xingce" in result["auto_entry_triggered_by"]
    assert "layer:same_project_workspace" in result["auto_entry_triggered_by"]
    assert result["context_delivery_mode"] == "compact_source_anchors"
    assert result["next_action"] == "apply_must_surface_before_answer"
    assert result["prompt_class"] == "continuation"
    assert result["silence_reason"] == ""
    assert result["confidence"] > 0
    assert result["should_recall"] is True
    assert result["should_surface"] is True
    assert result["proactive_resurfacing_required"] is True
    assert "action_strategy" in result["xingce_focus"]
    assert "continuation_state" in result["xingce_focus"]
    assert result["must_surface"][0]["library_id"] == "ZX-XINGCE-KNOWN"
    assert "不要改 root config 当默认继承" in result["do_not_repeat"]
    assert "hermes profile show" in result["acceptance_checks"]
    assert result["raw_excerpt_returned"] is False
    assert result["consumer_receipt"]["receipt_scope"] == "zhixing_preflight_read_only"
    assert result["consumer_receipt"]["answer_debug_available"] is True
    assert result["consumer_receipt"]["answer_debug_capability_contract"] == "preflight_answer_debug_capability.v2026.6.18"
    assert result["consumer_receipt"]["dialog_entry_answer_debug_contract"] == "dialog_entry_answer_debug.v2026.6.18"
    assert result["consumer_receipt"]["evidence_bound_model_gating_contract"] == "evidence_bound_model_gating.v2026.6.18"


def test_zhixing_preflight_marks_correction_and_preference_focus():
    mod = importlib.import_module("src.zhixing_preflight")

    result = mod.build_zhixing_preflight(
        "你之前误解了我的要求，不要把内部开发工具写进公开文案",
        recall_payload={
            "items": [
                {
                    "library_id": "ZX-ZHIYI-PREF",
                    "library_shelf": "zhiyi",
                    "memory_type": "preference_memory",
                    "summary": "公开文案不要出现内部中转工具依赖。",
                    "source_path": "raw/probe_logs/public-wording.jsonl",
                    "raw_evidence_status": "raw",
                }
            ],
            "matched_count": 1,
            "source_refs_count": 1,
            "raw_items_count": 1,
        },
    )

    assert result["should_surface"] is True
    assert result["decision"] == "surface"
    assert result["auto_entry_state"] == "enter"
    assert result["auto_entry_allowed"] is True
    assert "boundary_or_correction_signal" in result["auto_entry_triggered_by"]
    assert result["prompt_class"] == "correction"
    assert "correction_or_boundary" in result["zhiyi_focus"]
    assert "source_backed_intent" in result["zhiyi_focus"]
    assert result["must_surface"][0]["library_shelf"] == "zhiyi"
    assert result["source_refs_required"] is True


def test_zhixing_preflight_library_index_projection_soft_boosts_rank_only():
    mod = importlib.import_module("src.zhixing_preflight")

    result = mod.build_zhixing_preflight(
        "继续处理平台配置",
        recall_payload={
            "items": [
                {
                    "library_id": "ZX-XINGCE-RAW",
                    "library_shelf": "xingce",
                    "summary": "平台配置经验。",
                    "source_path": "raw/probe_logs/platform-raw.jsonl",
                    "raw_evidence_status": "raw",
                },
                {
                    "library_id": "ZX-XINGCE-INDEX",
                    "library_shelf": "xingce",
                    "summary": "平台配置经验。",
                    "source_path": "raw/probe_logs/platform-index.jsonl",
                    "raw_evidence_status": "raw_index",
                    "library_index_projection_used": True,
                    "matched_by": ["source_refs", "catalog_index", "raw_index"],
                },
            ],
            "matched_count": 2,
            "source_refs_count": 2,
            "raw_items_count": 2,
            "library_index_projection_used": True,
            "library_index_projection_refs_count": 1,
        },
    )

    assert result["decision"] == "surface"
    assert result["must_surface"][0]["library_id"] == "ZX-XINGCE-INDEX"
    assert result["must_surface"][0]["library_index_projection_soft_weight_applied"] is True
    assert result["must_surface"][0]["library_index_projection_soft_weight"] == 6
    assert result["must_surface"][0]["raw_evidence_status"] == "raw_index"
    assert result["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    profile_by_id = {
        profile["library_id"]: profile
        for profile in result["preflight_score_profile"]
    }
    assert profile_by_id["ZX-XINGCE-INDEX"]["score"] > profile_by_id["ZX-XINGCE-RAW"]["score"]
    assert profile_by_id["ZX-XINGCE-INDEX"]["base_score"] == profile_by_id["ZX-XINGCE-RAW"]["base_score"]
    assert profile_by_id["ZX-XINGCE-INDEX"]["surface_eligible"] is True
    assert any(
        component["name"] == "library_index_projection"
        for component in profile_by_id["ZX-XINGCE-INDEX"]["components"]
    )
    assert result["consumer_receipt"]["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"


def test_zhixing_preflight_preserves_projection_receipt_and_recall_trajectory():
    mod = importlib.import_module("src.zhixing_preflight")

    result = mod.build_zhixing_preflight(
        "继续，开工前先查已有机制",
        recall_payload={
            "items": [
                {
                    "library_id": "ZX-XINGCE-FAST-INDEX",
                    "library_shelf": "xingce",
                    "summary": "当前窗口 fast preflight 已命中馆藏目录投影。",
                    "source_path": "raw/probe_logs/fast-index.jsonl",
                    "raw_evidence_status": "raw_index",
                    "library_index_projection_used": True,
                    "matched_by": ["source_refs", "catalog_index", "raw_index"],
                }
            ],
            "matched_count": 1,
            "source_refs_count": 1,
            "raw_items_count": 1,
            "library_index_projection_contract": "library_index_projection_receipt.v2026.6.17",
            "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
            "library_index_projection_used": True,
            "library_index_projection_refs_count": 1,
            "library_index_projection_refs": [
                {
                    "projection_kind": "library_index_projection",
                    "authority": "navigation_hint_only_raw_evidence_required",
                    "source_path": "raw/probe_logs/fast-index.jsonl",
                }
            ],
            "raw_recall_trajectory_contract": "raw_recall_trajectory.v2026.6.17",
            "raw_recall_trajectory_policy": "retrieval_steps_are_diagnostics_not_evidence",
            "raw_recall_trajectory": [
                {
                    "step": "catalog_index_projection",
                    "layer": "L1_library_index_projection",
                    "status": "hit_recent_context",
                    "used": True,
                    "authority": "navigation_hint_only_raw_evidence_required",
                },
                {
                    "step": "raw_fallback",
                    "layer": "L2_raw_records",
                    "status": "skipped_fast_window_index_hit",
                    "used": False,
                    "authority": "raw_records_are_final_evidence",
                },
            ],
        },
    )

    assert result["decision"] == "surface"
    assert result["library_index_projection_used"] is True
    assert result["library_index_projection_refs_count"] == 1
    assert result["library_index_projection_refs"][0]["authority"] == "navigation_hint_only_raw_evidence_required"
    assert result["raw_recall_trajectory_contract"] == "raw_recall_trajectory.v2026.6.17"
    trajectory = {step["step"]: step for step in result["raw_recall_trajectory"]}
    assert trajectory["catalog_index_projection"]["used"] is True
    assert trajectory["raw_fallback"]["status"] == "skipped_fast_window_index_hit"
    assert result["consumer_receipt"]["library_index_projection_used"] is True
    assert result["consumer_receipt"]["library_index_projection_refs_count"] == 1
    assert result["consumer_receipt"]["raw_recall_trajectory_contract"] == "raw_recall_trajectory.v2026.6.17"


def test_zhixing_preflight_library_index_projection_cannot_surface_weak_evidence():
    mod = importlib.import_module("src.zhixing_preflight")

    result = mod.build_zhixing_preflight(
        "我的想法是先看这个方向",
        recall_payload={
            "items": [
                {
                    "library_id": "ZX-ZHIYI-WEAK-INDEX",
                    "library_shelf": "zhiyi",
                    "summary": "弱偏好，只是目录投影命中。",
                    "library_index_projection_used": True,
                    "matched_by": ["catalog_index"],
                }
            ],
            "matched_count": 1,
            "source_refs_count": 0,
            "raw_items_count": 0,
            "library_index_projection_used": True,
            "library_index_projection_refs_count": 1,
        },
    )

    assert result["decision"] == "silent"
    assert result["should_surface"] is False
    assert result["must_surface"] == []
    assert result["consumer_receipt"]["items_count"] == 0
    profile = result["preflight_score_profile"][0]
    assert profile["library_id"] == "ZX-ZHIYI-WEAK-INDEX"
    assert profile["library_index_projection_soft_weight_applied"] is True
    assert profile["base_score"] < result["min_surface_score"]
    assert profile["score"] == profile["base_score"] + 6
    assert profile["surface_eligible"] is False
    assert result["raw_evidence_status"] == "not_raw"


def test_zhixing_preflight_scope_missing_stays_read_only_without_surface():
    mod = importlib.import_module("src.zhixing_preflight")

    result = mod.build_zhixing_preflight(
        "继续",
        recall_payload={
            "scope_missing": True,
            "recall_status": "cross_window_permission_required",
            "missing_scope_fields": ["allow_cross_window_recall"],
            "cross_window_read": True,
            "cross_window_read_allowed": False,
            "items": [],
        },
    )

    assert result["should_surface"] is False
    assert result["decision"] == "scope_required"
    assert result["auto_entry_state"] == "bind_required"
    assert result["auto_entry_allowed"] is False
    assert result["auto_retreat_allowed"] is True
    assert result["auto_retreat_reason"] == "scope_missing"
    assert result["context_delivery_mode"] == "no_context_injection"
    assert result["next_action"] == "report_binding_gap_without_claiming_memory_empty"
    assert result["silence_reason"] == "scope_missing"
    assert result["scope_missing"] is True
    assert result["recall_status"] == "cross_window_permission_required"
    assert result["recall_performed"] is False
    assert result["must_surface"] == []
    assert result["write_performed"] is False


def test_zhixing_preflight_skips_trivial_prompt_without_recall():
    mod = importlib.import_module("src.zhixing_preflight")

    result = mod.build_zhixing_preflight(
        "好的",
        recall_payload={
            "items": [
                {
                    "library_id": "ZX-XINGCE-IRRELEVANT",
                    "library_shelf": "xingce",
                    "summary": "平台配置经验。",
                    "source_path": "raw/probe_logs/platform.jsonl",
                    "raw_evidence_status": "raw",
                }
            ],
            "matched_count": 1,
            "source_refs_count": 1,
            "raw_items_count": 1,
        },
    )

    assert result["decision"] == "skip"
    assert result["auto_entry_state"] == "skip"
    assert result["auto_entry_allowed"] is False
    assert result["auto_retreat_allowed"] is True
    assert result["auto_retreat_reason"] == "trivial_prompt"
    assert result["next_action"] == "answer_normally_without_memory_preamble"
    assert result["prompt_class"] == "trivial"
    assert result["should_recall"] is False
    assert result["should_surface"] is False
    assert result["must_surface"] == []
    assert result["silence_reason"] == "trivial_prompt"
    assert result["consumer_receipt"]["items_count"] == 0
    assert result["consumer_receipt"]["used_library_ids"] == []


def test_zhixing_preflight_keeps_ordinary_prompt_silent():
    mod = importlib.import_module("src.zhixing_preflight")

    result = mod.build_zhixing_preflight(
        "解释一下 Python list comprehension",
        recall_payload={
            "items": [],
            "matched_count": 0,
            "source_refs_count": 0,
            "raw_items_count": 0,
        },
    )

    assert result["decision"] == "skip"
    assert result["auto_entry_state"] == "skip"
    assert result["prompt_class"] == "ordinary"
    assert result["should_recall"] is False
    assert result["should_surface"] is False
    assert result["recall_status"] == "preflight_skipped_ordinary_prompt_without_memory_signal"


def test_zhixing_preflight_silences_below_threshold_evidence():
    mod = importlib.import_module("src.zhixing_preflight")

    result = mod.build_zhixing_preflight(
        "我的想法是先看这个方向",
        recall_payload={
            "items": [
                {
                    "library_id": "ZX-ZHIYI-WEAK",
                    "library_shelf": "zhiyi",
                    "summary": "一个没有 source path 和 raw 证据的弱偏好。",
                }
            ],
            "matched_count": 1,
            "source_refs_count": 0,
            "raw_items_count": 0,
        },
    )

    assert result["decision"] == "silent"
    assert result["auto_entry_state"] == "retreat"
    assert result["auto_entry_allowed"] is False
    assert result["auto_retreat_allowed"] is True
    assert result["auto_retreat_reason"] == "below_surface_threshold"
    assert result["next_action"] == "answer_normally_keep_uncertainty_if_prior_context_matters"
    assert result["prompt_class"] == "preference"
    assert result["should_recall"] is True
    assert result["should_surface"] is False
    assert result["silence_reason"] == "below_surface_threshold"
    assert result["must_surface"] == []
