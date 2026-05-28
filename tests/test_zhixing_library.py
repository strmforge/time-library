import importlib


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
    assert hybrid["pipeline_order"][0] == "source_refs_exact"
    assert hybrid["vector_is_not_authority"] is True


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
