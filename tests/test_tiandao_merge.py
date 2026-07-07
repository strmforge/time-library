import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_tiandao_folder_contains_merged_python_and_orchestration_system_sources():
    tiandao = ROOT / "src" / "tiandao"

    # Existing Time Library Python mirror remains in place.
    assert (tiandao / "boundary.py").is_file()
    assert (tiandao / "context_service.py").is_file()

    # orchestration system Tiandao source files are copied into the same Tiandao folder,
    # not used as a separate subsystem-specific Tiandao tree.
    for name in [
        "source-ref.ts",
        "context-package.ts",
        "audit-event.ts",
        "evidence-level.ts",
        "memory-routing.ts",
        "model.ts",
        "index.ts",
    ]:
        assert (tiandao / "contracts" / name).is_file()

    for name in [
        "source-ref.schema.json",
        "context-package.schema.json",
        "audit-event.schema.json",
        "evidence-level.schema.json",
        "source-system.schema.json",
        "evidence-ref.schema.json",
        "memory-routing.schema.json",
    ]:
        assert (tiandao / "schemas" / name).is_file()

    assert not (ROOT / "TIANDAO.md").exists()


def test_tiandao_python_exports_orchestration_system_promoted_contracts():
    from tiandao import (
        AuditAction,
        AuditResult,
        TiandaoEvidenceLevel,
        active_memory_default_recall_order,
        classify_memory_signal_layer,
        conversation_capture_verdict,
        api_mode_for_endpoint,
        build_tiandao_model_assets,
        create_audit_event,
        is_evidence_level_at_least,
        memory_experience_layering_contract_descriptor,
        memory_context_mode_for_routing,
        runtime_model_id_for,
        time_origin_contract_descriptor,
        time_river_contract_descriptor,
        time_river_sediment_contract_descriptor,
    )

    event = create_audit_event(
        actor="codex",
        action=AuditAction.CONTEXT_ASSEMBLE,
        target="ctx-1",
        result=AuditResult.SUCCESS,
    )
    assert event["action"] == "context.assemble"
    assert event["result"] == "success"
    assert event["event_id"].startswith("audit_")

    assert is_evidence_level_at_least(
        TiandaoEvidenceLevel.CODEX_REVIEWED,
        TiandaoEvidenceLevel.AUTO_EVIDENCED,
    )
    assert active_memory_default_recall_order() == [
        "current_window",
        "current_session",
        "same_project_workspace",
        "same_workstream_task",
        "stable_user_preferences_tool_facts",
        "explicit_raw_pool_global_only_when_requested",
    ]
    assert memory_context_mode_for_routing("raw_pool", [], True) == "mode_c"
    verdict = conversation_capture_verdict(["user"])
    assert verdict["contract"] == "tiandao_conversation_evidence.v1"
    assert verdict["complete_conversation_candidate"] is False
    assert verdict["partial_source_policy"] == "evidence_only_not_current_window_memory"
    layering = memory_experience_layering_contract_descriptor()
    assert layering["contract"] == "tiandao_memory_experience_layering.v1"
    assert layering["all_queryable_layers"] == ["raw", "zhiyi", "xingce", "toolbook"]
    assert layering["platform_is_not_memory_layer"] is True
    assert layering["platform_capability_policy"] == "platforms_may_use_any_subset_of_neutral_capabilities"
    assert "platform_method_biases" not in layering
    assert classify_memory_signal_layer("correction") == "zhiyi"
    assert classify_memory_signal_layer("workflow") == "xingce"
    assert classify_memory_signal_layer("tool_fact") == "toolbook"
    time_origin = time_origin_contract_descriptor()
    assert time_origin["contract"] == "tiandao_time_origin.v1"
    assert time_origin["zh_name"] == "时间起源"
    assert time_origin["origin_layer"] == "raw"
    assert time_origin["origin_event_required"] is True
    assert time_origin["no_raw_no_river"] is True
    assert time_origin["raw_authority_policy"] == "raw_source_text_is_highest_authority"
    assert time_origin["derived_sediment_policy"] == "derived_sediment_must_reference_origin"
    assert time_origin["multi_machine_policy"] == "source_streams_merge_not_overwrite"
    assert time_origin["platform_policy"] == "platforms_are_inlets_not_origin"
    assert time_origin["river_endpoint_policy"] == "time_river_has_no_endpoint"
    assert time_origin["lost_source_label"] == "遗失源"
    assert time_origin["lost_raw_label"] == "遗失 raw"
    time_river = time_river_contract_descriptor()
    assert time_river["contract"] == "tiandao_time_river.v1"
    assert time_river["zh_name"] == "时间长河"
    assert time_river["role"] == "neutral_temporal_memory_continuity_contract"
    assert time_river["time_origin_contract"] == "tiandao_time_origin.v1"
    assert time_river["sediment_contract"] == "tiandao_time_river_sediment.v1"
    assert time_river["origin_policy"] == "time_river_begins_at_raw_origin_event"
    assert time_river["platform_policy"] == "platforms_are_inlets_not_river_laws"
    assert time_river["raw_authority_policy"] == "raw_source_text_is_highest_authority"
    assert time_river["summary_policy"] == "summaries_are_navigation_not_source_replacement"
    assert time_river["endpoint_policy"] == "time_river_has_no_endpoint"
    assert "source_event" in time_river["stages"]
    assert "raw_preservation" in time_river["stages"]
    assert "experience_sedimentation" in time_river["stages"]
    assert "replay_validation" in time_river["stages"]
    assert set(["event_time", "source_refs", "library_id", "lifecycle_status", "audit_event"]).issubset(
        set(time_river["required_anchors"])
    )
    assert "proactive_resurfacing" in time_river["replay_validation_metrics"]
    sediment = time_river_sediment_contract_descriptor()
    assert sediment["contract"] == "tiandao_time_river_sediment.v1"
    assert sediment["zh_name"] == "时间长河沉积链"
    assert sediment["time_origin_contract"] == "tiandao_time_origin.v1"
    assert sediment["time_river_contract"] == "tiandao_time_river.v1"
    assert sediment["trusted_status"] == "origin_linked"
    assert "source_refs_only" in sediment["candidate_statuses"]
    assert sediment["origin_link_policy"] == "derived_sediment_must_reference_origin"
    assert sediment["write_policy"] == "read_only_descriptor_no_memory_write"

    endpoint = {
        "id": "ep-openclaw",
        "name": "OpenClaw",
        "providerName": "deepseek",
        "providerType": "openai",
        "baseUrl": "https://api.example.test/",
        "platform": "openclaw",
    }
    model = {
        "id": "ep-openclaw/deepseek-chat",
        "endpointId": "ep-openclaw",
        "modelName": "deepseek-chat",
        "capabilities": ["chat"],
    }
    assert api_mode_for_endpoint(endpoint) == "openai-completions"
    assert runtime_model_id_for(endpoint, model) == "deepseek/deepseek-chat"
    assets = build_tiandao_model_assets([endpoint], [model])
    assert assets[0]["runtimeModelId"] == "deepseek/deepseek-chat"
    assert assets[0]["connectionKey"] == "deepseek@https://api.example.test@openai-completions"


def test_tiandao_schema_and_ts_sources_preserve_neutral_contract_names():
    tiandao = ROOT / "src" / "tiandao"
    source_ref = (tiandao / "contracts" / "source-ref.ts").read_text(encoding="utf-8")
    context_package = (tiandao / "contracts" / "context-package.ts").read_text(encoding="utf-8")
    memory_routing = (tiandao / "contracts" / "memory-routing.ts").read_text(encoding="utf-8")
    audit_event = (tiandao / "contracts" / "audit-event.ts").read_text(encoding="utf-8")
    evidence_level = (tiandao / "contracts" / "evidence-level.ts").read_text(encoding="utf-8")
    model_core = (tiandao / "model" / "core.ts").read_text(encoding="utf-8")

    assert "TiandaoSourceRef" in source_ref
    assert "TiandaoContextPackage" in context_package
    assert "TiandaoActiveMemoryRoutingContract" in memory_routing
    assert "tiandao_active_memory_routing.v1" in memory_routing
    assert "tiandao_conversation_evidence.v1" in memory_routing
    assert "tiandao_continuous_local_sync.v1" in memory_routing
    assert "tiandao_memory_experience_layering.v1" in memory_routing
    assert "tiandao_time_origin.v1" in memory_routing
    assert "tiandao_time_river.v1" in memory_routing
    assert "tiandao_time_river_sediment.v1" in memory_routing
    assert "platforms_are_inlets_not_origin" in memory_routing
    assert "time_river_has_no_endpoint" in memory_routing
    assert "platforms_are_inlets_not_river_laws" in memory_routing
    assert "raw_source_text_is_highest_authority" in memory_routing
    assert "content_signal_not_platform_identity" in memory_routing
    assert "openclaw:" not in memory_routing
    assert "codex:" not in memory_routing
    assert "claude:" not in memory_routing
    assert "hermes:" not in memory_routing
    assert "TiandaoAuditEvent" in audit_event
    assert "TiandaoEvidenceLevel" in evidence_level
    assert "../contracts/model.js" in model_core
    assert "src/contracts/tiandao" not in model_core

    schema = json.loads((tiandao / "schemas" / "context-package.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema"]["const"] == "tiandao_context_package.v1"
    assert schema["properties"]["memory_write"]["const"] is False
    assert "active_memory_routing_contract" in schema["properties"]
    routing_schema = json.loads((tiandao / "schemas" / "memory-routing.schema.json").read_text(encoding="utf-8"))
    assert routing_schema["properties"]["active_memory_routing_contract"]["const"] == "tiandao_active_memory_routing.v1"
    assert routing_schema["properties"]["memory_experience_layering_contract"]["const"] == "tiandao_memory_experience_layering.v1"
    assert routing_schema["properties"]["time_origin_contract"]["const"] == "tiandao_time_origin.v1"
    assert routing_schema["properties"]["time_origin_layer"]["const"] == "raw"
    assert routing_schema["properties"]["time_origin_event_required"]["const"] is True
    assert routing_schema["properties"]["no_raw_no_river"]["const"] is True
    assert routing_schema["properties"]["time_origin_platform_policy"]["const"] == "platforms_are_inlets_not_origin"
    assert routing_schema["properties"]["time_river_contract"]["const"] == "tiandao_time_river.v1"
    assert routing_schema["properties"]["time_river_sediment_contract"]["const"] == "tiandao_time_river_sediment.v1"
    assert routing_schema["properties"]["time_river_platform_policy"]["const"] == "platforms_are_inlets_not_river_laws"
    assert routing_schema["properties"]["time_river_raw_authority_policy"]["const"] == "raw_source_text_is_highest_authority"
    assert (
        routing_schema["properties"]["time_river_summary_policy"]["const"]
        == "summaries_are_navigation_not_source_replacement"
    )
    assert routing_schema["properties"]["time_river_origin_policy"]["const"] == "time_river_begins_at_raw_origin_event"
    assert routing_schema["properties"]["time_river_endpoint_policy"]["const"] == "time_river_has_no_endpoint"
    assert "origin_linked" in routing_schema["properties"]["time_river_sediment_statuses"]["items"]["enum"]
    assert routing_schema["properties"]["classification_rule"]["const"] == "content_signal_not_platform_identity"
    assert "platform_method_biases" not in routing_schema["properties"]
    assert "platform_direction_defaults" not in routing_schema["properties"]
