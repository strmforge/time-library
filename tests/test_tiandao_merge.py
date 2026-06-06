import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_tiandao_folder_contains_merged_python_and_nantianmen_sources():
    tiandao = ROOT / "src" / "tiandao"

    # Existing Yifanchen Python mirror remains in place.
    assert (tiandao / "boundary.py").is_file()
    assert (tiandao / "context_service.py").is_file()

    # Nantianmen Tiandao source files are copied into the same Tiandao folder,
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


def test_tiandao_python_exports_nantianmen_promoted_contracts():
    from tiandao import (
        AuditAction,
        AuditResult,
        TiandaoEvidenceLevel,
        active_memory_default_recall_order,
        conversation_capture_verdict,
        api_mode_for_endpoint,
        build_tiandao_model_assets,
        create_audit_event,
        is_evidence_level_at_least,
        memory_context_mode_for_routing,
        runtime_model_id_for,
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
