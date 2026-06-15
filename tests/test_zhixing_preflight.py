import importlib


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
    assert result["decision"] == "surface"
    assert result["auto_entry_contract"] == "zhixing_auto_entry.v2026.6.15"
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
