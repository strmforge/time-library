import importlib
import importlib.util
import hashlib
import json
import os
import sqlite3
import sys
import threading
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reload_modules(tmp_path):
    os.environ["MEMCORE_ROOT"] = str(tmp_path / "memcore")
    os.environ["MEMCORE_CONFIG"] = str(ROOT / "config" / "memcore.json")
    os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "memcore" / "zhiyi")
    os.environ["MEMCORE_PROJECT_STATUS_ROOT_OVERRIDE"] = str(tmp_path / "memcore")
    os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path / "memcore")
    for name in ["config_loader", "src.config_loader", "src.p3_recall", "src.raw_consumption_gateway"]:
        sys.modules.pop(name, None)
    p3 = importlib.import_module("src.p3_recall")
    raw_gateway = importlib.import_module("src.raw_consumption_gateway")
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    return p3, raw_gateway


def _clear_raw_gateway_env():
    for key in [
        "MEMCORE_RAW_GATEWAY_STATE_DIR",
        "MEMCORE_RAW_SEGMENT_BYTES",
        "MEMCORE_RAW_SEGMENT_MAX_SEGMENTS",
    ]:
        os.environ.pop(key, None)


def _write_memory(
    tmp_path,
    source_system,
    session_id,
    msg_id,
    summary,
    content,
    window_id="project-a",
    project_id="",
    project_root="",
    workstream_id="",
    task_id="",
    memory_type="case_memory",
):
    root = tmp_path / "memcore"
    raw_path = root / "memory" / source_system / "local" / window_id / f"{session_id}.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps({
            "timestamp": msg_id,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    refs = {
        "source_system": source_system,
        "computer_name": "local",
        "canonical_window_id": window_id,
        "session_id": session_id,
        "project_id": project_id,
        "project_root": project_root,
        "workstream_id": workstream_id,
        "task_id": task_id,
        "source_path": str(raw_path),
        "msg_ids": [msg_id],
        "artifact_type": f"{source_system}_session_jsonl",
    }
    record = {
        "exp_id": f"exp-{source_system}-{session_id}",
        "type": memory_type,
        "canonical_window_id": window_id,
        "session_id": session_id,
        "project_id": project_id,
        "project_root": project_root,
        "workstream_id": workstream_id,
        "task_id": task_id,
        "computer_id": "local",
        "source_system": source_system,
        "scope": f"window/{window_id}",
        "summary": summary,
        "detail": "shared-base smoke marker 忆凡尘 Codex OpenClaw Hermes",
        "source_refs": json.dumps(refs, ensure_ascii=False),
        "score": 0.8,
    }
    zhiyi_path = root / "zhiyi" / memory_type / f"{memory_type}.jsonl"
    zhiyi_path.parent.mkdir(parents=True, exist_ok=True)
    with zhiyi_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_hermes_skill_artifact_status(tmp_path):
    root = tmp_path / "memcore"
    status_dir = root / "output" / "hermes_native_learning" / "skill_artifact_status"
    status_dir.mkdir(parents=True, exist_ok=True)
    status = {
        "artifact_type": "hermes_skill_artifact_status",
        "schema_version": "2026.6.1",
        "status_id": "hermes-skill-artifact-status-test",
        "status": "current",
        "project": "memcore-cloud / 忆凡尘",
        "skill_artifact_status": "probe_only_not_adopted",
        "probe_id": "hermes-skill-generation-probe-2fec7027343c3a92",
        "probe_receipt_path": str(root / "output" / "hermes_native_learning" / "skill_generation_probes" / "latest.json"),
        "skill_relative_path": "yifanchen/zhiyi-recall-check/SKILL.md",
        "skill_path": r"C:\Users\Example\AppData\Local\hermes\skills\yifanchen\zhiyi-recall-check\SKILL.md",
        "skill_sha256": "1c2fb11afc3148e5c21686c6401c576b73d483c85753be5803ebc63eec1f1e34",
        "summary": "Hermes skill generation probe verdict: zhiyi-recall-check is probe-only and not adopted.",
        "current_state": "Fresh Hermes did not naturally use MCP recall for the probe verdict.",
        "next_step": "Make this status recallable before any skill adoption.",
        "completed": ["Hermes generated a native skill artifact."],
        "remaining": ["Skill adoption is still blocked by quality review."],
        "limitations": ["This is not production experience adoption."],
        "write_boundary": {
            "write_performed": True,
            "status_receipt_write_performed": True,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_skill_write_performed_by_yifanchen": False,
            "production_experience_write_performed": False,
            "openclaw_write_performed": False,
        },
    }
    (status_dir / "latest.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def test_hermes_normal_raw_pool_requires_explicit_workflow_or_cross_window_flag(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex 共享底座经验",
        "Codex 这条经验来自 Codex 窗口，但只能作为 Hermes 背景记忆。",
    )
    _write_memory(
        tmp_path,
        "openclaw",
        "openclaw-session",
        "msg_001",
        "OpenClaw 共享底座经验",
        "OpenClaw 这条经验来自 OpenClaw 窗口，也只能带来源使用。",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "共享底座经验",
        source_system="",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=200,
        consumer="hermes",
        request_id="test-shared",
        memory_scope="raw_pool",
    )

    assert result["ok"] is True
    assert result["memory_scope"] == "raw_pool"
    assert result["memory_base_scope"] == "shared"
    assert result["scope_missing"] is True
    assert result["recall_status"] == "cross_window_permission_required"
    assert result["cross_window_read"] is True
    assert result["cross_window_read_allowed"] is False
    assert result["hermes_global_exception"] is False
    assert result["hermes_plain_recall_is_global_exception"] is False
    assert result["hermes_broad_context_workflow"] is False
    assert result["missing_scope_fields"] == ["allow_cross_window_recall"]
    assert "Hermes normal recall is also window-scoped" in result["window_binding_hint"]
    assert result["matched_count"] == 0
    assert result["items"] == []


def test_hermes_skill_generation_workflow_can_read_shared_base_with_receipt(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex 共享底座经验",
        "Codex 这条经验来自 Codex 窗口，但只能作为 Hermes 背景记忆。",
    )
    _write_memory(
        tmp_path,
        "openclaw",
        "openclaw-session",
        "msg_001",
        "OpenClaw 共享底座经验",
        "OpenClaw 这条经验来自 OpenClaw 窗口，也只能带来源使用。",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "共享底座经验",
        source_system="",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=200,
        consumer="hermes",
        request_id="test-hermes-skill-generation",
        memory_scope="raw_pool",
        cross_window_reason="skill_generation",
    )

    assert result["ok"] is True
    assert result["scope_missing"] is False
    assert result["memory_scope"] == "raw_pool"
    assert result["memory_base_scope"] == "shared"
    assert result["cross_window_read"] is True
    assert result["cross_window_read_allowed"] is True
    assert result["hermes_global_exception"] is True
    assert result["hermes_broad_context_workflow"] is True
    assert result["cross_window_reason"] == "skill_generation"
    assert result["agent_boundary"] == "active_window_first_explicit_broad_scope"
    assert result["injection_boundary"] == "source_refs_only_no_cross_agent_window_write"
    sources = {item["source_system"] for item in result["items"]}
    assert {"codex", "openclaw"}.issubset(sources)


def test_active_default_can_continue_same_project_without_current_window_identity(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-a",
        "2026-05-27T10:00:00Z",
        "Codex active project continuation marker ACTIVE_PROJECT_MARKER",
        "ACTIVE_PROJECT_MARKER should continue across windows in the same project.",
        window_id="window-a",
        project_id="memcore-cloud-rebuilt-20260527",
        project_root="/workspace/memcore-cloud-rebuilt-20260527",
    )
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-b",
        "2026-05-27T10:01:00Z",
        "Codex active project continuation marker ACTIVE_PROJECT_MARKER",
        "ACTIVE_PROJECT_MARKER from another project must not leak.",
        window_id="window-b",
        project_id="other-project",
        project_root="/workspace/other-project",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "ACTIVE_PROJECT_MARKER",
        consumer="codex",
        request_id="test-active-project",
        project_id="memcore-cloud-rebuilt-20260527",
    )

    assert result["ok"] is True
    assert result["memory_scope"] == "active"
    assert result["memory_base_scope"] == "active_layered"
    assert result["scope_missing"] is False
    assert result["cross_window_read"] is False
    assert result["project_id_filter"] == "memcore-cloud-rebuilt-20260527"
    assert result["active_layers_used"] == ["same_project_workspace"]
    assert result["injection_boundary"] == "active_layered_source_refs_only"
    assert result["items"]
    assert {item["project_id"] for item in result["items"]} == {"memcore-cloud-rebuilt-20260527"}
    assert {item["active_memory_layer"] for item in result["items"]} == {"same_project_workspace"}
    assert "another project must not leak" not in json.dumps(result["items"], ensure_ascii=False)


def test_active_default_uses_registry_current_window_when_request_has_no_identity(tmp_path):
    marker = "REGISTRY_CURRENT_WINDOW_MARKER"
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-a",
        "2026-05-27T10:00:00Z",
        "Codex registry current window marker",
        marker,
        window_id="window-a",
    )
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-b",
        "2026-05-27T10:01:00Z",
        "Codex registry current window marker",
        "REGISTRY_OTHER_WINDOW_SHOULD_NOT_LEAK",
        window_id="window-b",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "codex": {
                        "source_system": "codex",
                        "canonical_window_id": "window-a",
                        "session_id": "codex-session-a",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex registry current window marker",
        consumer="codex",
        request_id="test-registry-current-window",
    )

    assert result["memory_scope"] == "active"
    assert result["current_window_binding_applied"] is True
    assert result["current_window_binding_key"] == "codex"
    assert set(result["current_window_binding_fields"]) == {"source_system", "canonical_window_id", "session_id"}
    assert result["canonical_window_id_filter"] == "window-a"
    assert result["active_layers_used"] == ["current_window"]
    assert result["tiandao_context_package_valid"] is True
    tiandao_pkg = result["tiandao_context_package"]
    assert tiandao_pkg["schema"] == "tiandao_context_package.v1"
    assert tiandao_pkg["contract_role"] == "memory_context_candidate"
    assert tiandao_pkg["source_system"] == "codex"
    assert tiandao_pkg["canonical_window_id"] == "window-a"
    assert tiandao_pkg["session_id"] == "codex-session-a"
    assert tiandao_pkg["memory_context_mode"] == "mode_a"
    assert tiandao_pkg["active_memory_routing_contract"] == "tiandao_active_memory_routing.v1"
    assert tiandao_pkg["tiandao_routing_contract"]["contract"] == "tiandao_active_memory_routing.v1"
    assert tiandao_pkg["active_layers_used"] == ["current_window"]
    assert tiandao_pkg["current_window_binding_applied"] is True
    assert tiandao_pkg["cross_window_read"] is False
    assert tiandao_pkg["cross_window_read_allowed"] is True
    assert tiandao_pkg["scope_enforced"] is True
    assert tiandao_pkg["memory_write"] is False
    assert tiandao_pkg["permission_boundary"]["memory_write_enabled"] is False
    assert tiandao_pkg["permission_boundary"]["apply_to_platform_blocked"] is True
    assert tiandao_pkg["adapter_verdict"]["adapter_verdict"] == "READY_FOR_MEMORY_CONTEXT_CANDIDATE"
    assert tiandao_pkg["validation"]["valid"] is True
    assert tiandao_pkg["source_refs"]
    assert tiandao_pkg["matched_memories"][0]["active_memory_layer"] == "current_window"
    assert result["items"]
    assert {item["session_id"] for item in result["items"]} == {"codex-session-a"}
    assert {item["canonical_window_id"] for item in result["items"]} == {"codex-session-a"}
    assert {item["project_id"] for item in result["items"]} == {"window-a"}
    assert {item["source_refs_canonical_window_id"] for item in result["items"]} == {"window-a"}
    assert marker in result["items"][0]["raw_excerpt"]
    assert "REGISTRY_OTHER_WINDOW_SHOULD_NOT_LEAK" not in json.dumps(result["items"], ensure_ascii=False)


def test_active_default_uses_registry_project_anchor_for_new_window_continuation(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-old-session",
        "2026-05-27T10:00:00Z",
        "Codex registry same project marker REGISTRY_PROJECT_MARKER",
        "REGISTRY_PROJECT_MARKER can continue in a new window for the same project.",
        window_id="old-window",
        project_id="memcore-cloud-rebuilt-20260527",
        project_root="/workspace/memcore-cloud-rebuilt-20260527",
    )
    _write_memory(
        tmp_path,
        "codex",
        "codex-other-session",
        "2026-05-27T10:01:00Z",
        "Codex registry same project marker REGISTRY_PROJECT_MARKER",
        "REGISTRY_OTHER_PROJECT_SHOULD_NOT_LEAK",
        window_id="other-window",
        project_id="other-project",
        project_root="/workspace/other-project",
    )
    registry_path = tmp_path / "memcore" / "config" / "window_binding_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "codex": {
                        "source_system": "codex",
                        "canonical_window_id": "new-window",
                        "session_id": "new-session",
                        "metadata": {
                            "project_id": "memcore-cloud-rebuilt-20260527",
                            "project_root": "/workspace/memcore-cloud-rebuilt-20260527",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "REGISTRY_PROJECT_MARKER",
        consumer="codex",
        request_id="test-registry-project-anchor",
    )

    assert result["memory_scope"] == "active"
    assert result["current_window_binding_applied"] is True
    assert result["canonical_window_id_filter"] == "new-window"
    assert result["project_id_filter"] == "memcore-cloud-rebuilt-20260527"
    assert result["active_layers_used"] == ["same_project_workspace"]
    assert result["tiandao_context_package_valid"] is True
    assert result["tiandao_context_package"]["schema"] == "tiandao_context_package.v1"
    assert result["tiandao_context_package"]["memory_context_mode"] == "mode_b"
    assert result["tiandao_context_package"]["active_layers_used"] == ["same_project_workspace"]
    assert result["tiandao_context_package"]["current_window_binding_applied"] is True
    assert result["items"]
    assert {item["project_id"] for item in result["items"]} == {"memcore-cloud-rebuilt-20260527"}
    assert {item["active_memory_layer"] for item in result["items"]} == {"same_project_workspace"}
    assert "REGISTRY_OTHER_PROJECT_SHOULD_NOT_LEAK" not in json.dumps(result["items"], ensure_ascii=False)


def test_active_default_without_anchor_only_returns_stable_facts(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-case",
        "2026-05-27T10:00:00Z",
        "Codex active no anchor marker ACTIVE_STABLE_MARKER",
        "ACTIVE_STABLE_MARKER ordinary case memory must not appear without an anchor.",
        window_id="case-window",
    )
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-pref",
        "2026-05-27T10:01:00Z",
        "Codex active no anchor marker ACTIVE_STABLE_MARKER",
        "ACTIVE_STABLE_MARKER stable preference can appear without a project anchor.",
        window_id="pref-window",
        memory_type="preference_memory",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "ACTIVE_STABLE_MARKER",
        consumer="codex",
        request_id="test-active-stable-only",
    )

    assert result["memory_scope"] == "active"
    assert result["scope_missing"] is False
    assert result["active_layers_used"] == ["stable_user_preferences_tool_facts"]
    assert result["items"]
    assert {item["memory_type"] for item in result["items"]} == {"preference_memory"}
    assert "ordinary case memory must not appear" not in json.dumps(result["items"], ensure_ascii=False)


def test_explicit_window_recall_requires_current_window_identity(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex 显式窗口必须绑定",
        "Explicit window scope still needs current window identity.",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex 显式窗口必须绑定",
        consumer="codex",
        request_id="test-explicit-window-required",
        memory_scope="window",
    )

    assert result["ok"] is True
    assert result["memory_scope"] == "window"
    assert result["memory_base_scope"] == "window"
    assert result["scope_missing"] is True
    assert result["recall_status"] == "window_identity_required"
    assert "not proof that memory is empty" in result["window_binding_hint"]
    assert set(result["missing_scope_fields"]) == {"canonical_window_id", "session_id"}
    assert result["recall_performed"] is False
    assert result["raw_excerpt_returned"] is False
    assert result["matched_count"] == 0
    assert result["source_refs_count"] == 0
    assert result["raw_items_count"] == 0
    assert result["items"] == []
    assert result["tiandao_context_package_valid"] is True
    tiandao_pkg = result["tiandao_context_package"]
    assert tiandao_pkg["schema"] == "tiandao_context_package.v1"
    assert tiandao_pkg["source_system"] == "codex"
    assert tiandao_pkg["scope_enforced"] is True
    assert tiandao_pkg["injection_blocked"] is True
    assert tiandao_pkg["block_reason"] == "window_identity_required"
    assert tiandao_pkg["memory_write"] is False
    assert tiandao_pkg["permission_boundary"]["read_only"] is True
    assert tiandao_pkg["validation"]["valid"] is True


def test_non_hermes_raw_pool_requires_explicit_cross_window_flag(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex raw pool 越界防线",
        "Codex cannot read the raw pool unless the caller marks the cross-window intent.",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex raw pool 越界防线",
        consumer="codex",
        request_id="test-raw-pool-blocked",
        memory_scope="raw_pool",
    )

    assert result["memory_scope"] == "raw_pool"
    assert result["scope_missing"] is True
    assert result["recall_status"] == "cross_window_permission_required"
    assert "Hermes normal recall is also window-scoped" in result["window_binding_hint"]
    assert result["missing_scope_fields"] == ["allow_cross_window_recall"]
    assert result["cross_window_read"] is True
    assert result["cross_window_read_allowed"] is False
    assert result["matched_count"] == 0
    assert result["items"] == []


def test_non_hermes_platform_scope_also_requires_explicit_cross_window_flag(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex platform scope 越界防线",
        "Platform scope is still cross-window for ordinary clients.",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex platform scope 越界防线",
        consumer="codex",
        request_id="test-platform-scope-blocked",
        memory_scope="platform",
    )

    assert result["memory_scope"] == "platform"
    assert result["source_system_filter"] == "codex"
    assert result["scope_missing"] is True
    assert result["recall_status"] == "cross_window_permission_required"
    assert result["missing_scope_fields"] == ["allow_cross_window_recall"]
    assert result["cross_window_read"] is True
    assert result["cross_window_read_allowed"] is False
    assert result["matched_count"] == 0
    assert result["items"] == []


def test_non_hermes_raw_pool_can_read_only_when_explicitly_allowed(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex raw pool 显式越界",
        "Explicitly allowed raw pool read returns source-backed records.",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex raw pool 显式越界",
        consumer="codex",
        request_id="test-raw-pool-allowed",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert result["scope_missing"] is False
    assert result["cross_window_read"] is True
    assert result["cross_window_read_allowed"] is True
    assert result["items"]
    assert result["items"][0]["source_system"] == "codex"


def test_window_scope_filters_same_platform_to_one_window(tmp_path):
    marker = "CURRENT_WINDOW_ONLY_MARKER"
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-a",
        "2026-05-27T10:00:00Z",
        "同平台窗口隔离 marker",
        marker,
        window_id="window-a",
    )
    _write_memory(
        tmp_path,
        "codex",
        "codex-session-b",
        "2026-05-27T10:01:00Z",
        "同平台窗口隔离 marker",
        "OTHER_WINDOW_SHOULD_NOT_LEAK",
        window_id="window-b",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "同平台窗口隔离 marker",
        consumer="codex",
        request_id="test-window-filter",
        memory_scope="window",
        canonical_window_id="window-a",
    )

    assert result["scope_missing"] is False
    assert result["memory_scope"] == "window"
    assert result["memory_base_scope"] == "window"
    assert result["canonical_window_id_filter"] == "window-a"
    assert result["items"]
    assert {item["session_id"] for item in result["items"]} == {"codex-session-a"}
    assert {item["canonical_window_id"] for item in result["items"]} == {"codex-session-a"}
    assert {item["project_id"] for item in result["items"]} == {"window-a"}
    assert {item["source_refs_canonical_window_id"] for item in result["items"]} == {"window-a"}
    assert marker in result["items"][0]["raw_excerpt"]
    assert "OTHER_WINDOW_SHOULD_NOT_LEAK" not in json.dumps(result["items"], ensure_ascii=False)


def test_window_scope_prefers_matching_session_when_codex_window_id_is_legacy_project(tmp_path):
    marker = "SESSION_FIRST_ZHIYI_WINDOW_DRIFT_MARKER"
    _write_memory(
        tmp_path,
        "codex",
        "session-a",
        "2026-06-10T01:20:00Z",
        "Codex session-first window drift marker",
        marker,
        window_id="legacy-project-window",
    )
    _write_memory(
        tmp_path,
        "codex",
        "session-b",
        "2026-06-10T01:21:00Z",
        "Codex session-first window drift marker",
        "SESSION_FIRST_ZHIYI_OTHER_SESSION_SHOULD_NOT_LEAK",
        window_id="session-b",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Codex session-first window drift marker",
        consumer="codex",
        request_id="test-session-first-zhiyi-window-drift",
        source_system="codex",
        memory_scope="window",
        session_id="session-a",
        canonical_window_id="session-a",
    )

    assert result["scope_missing"] is False
    assert result["memory_scope"] == "window"
    assert result["canonical_window_id_filter"] == "session-a"
    assert result["items"]
    assert {item["session_id"] for item in result["items"]} == {"session-a"}
    assert {item["canonical_window_id"] for item in result["items"]} == {"session-a"}
    assert {item["project_id"] for item in result["items"]} == {"legacy-project-window"}
    assert marker in result["items"][0]["raw_excerpt"]
    assert "OTHER_SESSION_SHOULD_NOT_LEAK" not in json.dumps(result["items"], ensure_ascii=False)


def test_p3_filter_prefers_matching_session_when_codex_window_id_is_legacy_project(tmp_path):
    p3, _ = _reload_modules(tmp_path)
    memory = {
        "_type": "case_memory",
        "type": "case_memory",
        "scope": "window/legacy-project-window",
        "canonical_window_id": "legacy-project-window",
        "summary": "P3_SESSION_FIRST_MARKER",
        "detail": "session match should override legacy project window identity",
        "source_refs": json.dumps(
            {
                "source_system": "codex",
                "computer_name": "local",
                "session_id": "session-a",
                "canonical_window_id": "legacy-project-window",
            },
            ensure_ascii=False,
        ),
    }

    matched = p3.filter_memories(
        [memory],
        query="P3_SESSION_FIRST_MARKER",
        source_system_filter="codex",
        session_id_filter="session-a",
        canonical_window_id_filter="session-a",
    )

    assert matched == [memory]


def test_raw_gateway_source_filter_is_explicit_not_default(tmp_path):
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex 共享底座经验",
        "Codex filtered raw excerpt.",
    )
    _write_memory(
        tmp_path,
        "openclaw",
        "openclaw-session",
        "msg_001",
        "OpenClaw 共享底座经验",
        "OpenClaw should not appear in a Codex-filtered result.",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "共享底座经验",
        source_system="codex",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=200,
        consumer="hermes",
        request_id="test-filtered",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert result["memory_base_scope"] == "filtered"
    assert result["source_system_filter"] == "codex"
    assert result["items"]
    assert {item["source_system"] for item in result["items"]} == {"codex"}


def test_raw_gateway_returns_platform_record_text_verbatim(tmp_path):
    marker = "用户原话 token=USER_OWN_TEXT_1234567890 password=不是凭据只是聊天内容。"
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "Codex 原样保存经验",
        marker,
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "原样保存经验",
        source_system="codex",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=300,
        consumer="hermes",
        request_id="test-verbatim",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert result["items"]
    raw_excerpt = result["items"][0]["raw_excerpt"]
    assert marker in raw_excerpt
    assert "REDACTED" not in raw_excerpt


def test_raw_gateway_exposes_readonly_zhiyi_mcp_tool(tmp_path):
    marker = "MCP 只读工具返回原始摘录 token=USER_OWN_TEXT_MCP。"
    _write_memory(
        tmp_path,
        "codex",
        "codex-session",
        "2026-05-27T10:00:00Z",
        "MCP 知意召回经验",
        marker,
    )
    _, raw_gateway = _reload_modules(tmp_path)

    listed = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    })
    tools = listed["result"]["tools"]
    assert tools[0]["name"] == "zhiyi_recall"

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "MCP 知意召回经验",
                "consumer": "codex",
                "canonical_window_id": "project-a",
                "limit": 3,
                "excerpt_chars": 300,
            },
        },
    })
    content = called["result"]["structuredContent"]
    assert content["ok"] is True
    assert content["consumer_receipt"]["write_performed"] is False
    assert content["zhixing_library"]["name"] == "Zhixing Library"
    assert content["hybrid_recall"]["enabled"] is True
    assert content["items"][0]["library_id"].startswith("ZX-")
    assert content["items"][0]["library_card"]["library_id"] == content["items"][0]["library_id"]
    assert content["items"][0]["matched_by"]
    assert content["items"][0]["rank_reason"]
    assert content["items"][0]["library_card"]["evidence_contract"]["verbatim_excerpt_required"] is True
    assert content["hybrid_recall"]["pipeline_order"][0] == "source_refs_exact"
    assert content["hybrid_recall"]["vector_is_not_authority"] is True
    assert content["items"][0]["library_id"] in content["consumer_receipt"]["used_library_ids"]
    assert content["consumer_receipt"]["used_source_refs"]
    assert marker in content["items"][0]["raw_excerpt"]
    assert "REDACTED" not in content["items"][0]["raw_excerpt"]


def test_raw_gateway_mcp_preflight_surfaces_xingce_without_raw_excerpt(tmp_path):
    marker = "Hermes 平台配置经验：先查 profile config；不要改 root config 当默认继承；验收用 hermes profile show。"
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "codex" / "local" / "project-a" / "codex-session.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-06-09T10:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": marker}],
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    candidates_dir = root / "output" / "xingce_work_experience" / "candidates"
    actions_dir = root / "output" / "xingce_work_experience" / "actions"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    actions_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = "xingce-hermes-profile-preflight"
    (candidates_dir / "xingce-hermes-profile-candidate.json").write_text(
        json.dumps({
            "candidate_id": candidate_id,
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "Hermes profile config preflight",
            "summary": "Hermes 平台配置经验 profile config",
            "work_scenario": "Hermes profile config",
            "recommended_procedure": ["先查 profile config"],
            "avoid_conditions": ["不要改 root config 当默认继承"],
            "verification_steps": ["hermes profile show"],
            "evidence_refs": [
                {
                    "source_system": "codex",
                    "computer_name": "local",
                    "canonical_window_id": "project-a",
                    "session_id": "codex-session",
                    "project_id": "memcore-cloud",
                    "project_root": "/work/memcore-cloud",
                    "workstream_id": "release-check",
                    "source_path": str(raw_path),
                    "msg_ids": ["2026-06-09T10:00:00Z"],
                }
            ],
            "source_refs": [str(raw_path)],
            "confidence": 0.8,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    (actions_dir / "2026-06-09-actions.jsonl").write_text(
        json.dumps({
            "action_id": "action-hermes-profile-preflight",
            "candidate_id": candidate_id,
            "action": "queue_for_experience_service_review",
            "action_status": "queued_for_experience_service_review",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    listed = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    })
    mode_schema = listed["result"]["tools"][0]["inputSchema"]["properties"]["mode"]
    assert "preflight" in mode_schema["enum"]

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续 Hermes 平台配置问题，接下来怎么做",
                "mode": "preflight",
                "consumer": "codex",
                "source_system": "codex",
                "canonical_window_id": "project-a",
                "project_id": "memcore-cloud",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]
    encoded = json.dumps(content, ensure_ascii=False)

    assert content["ok"] is True
    assert content["mode"] == "preflight"
    assert content["read_only"] is True
    assert content["write_performed"] is False
    assert content["raw_write_performed"] is False
    assert content["zhiyi_write_performed"] is False
    assert content["xingce_write_performed"] is False
    assert content["platform_write_performed"] is False
    assert content["model_call_performed"] is False
    assert content["should_recall"] is True
    assert content["should_surface"] is True
    assert content["decision"] == "surface"
    assert content["proactive_resurfacing_required"] is True
    assert "action_strategy" in content["xingce_focus"]
    assert "continuation_state" in content["xingce_focus"]
    assert content["must_surface"]
    assert content["must_surface"][0]["library_shelf"] == "xingce"
    assert content["must_surface"][0]["project_id"] == "memcore-cloud"
    assert any("不要改 root config" in item for item in content["do_not_repeat"])
    assert any("hermes profile show" in item for item in content["acceptance_checks"])
    assert content["raw_excerpt_returned"] is False
    assert content["consumer_receipt"]["receipt_scope"] == "zhixing_preflight_read_only"
    assert '"raw_excerpt":' not in encoded
    assert marker not in encoded

    project_called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续 Hermes 平台配置问题，接下来怎么做",
                "mode": "preflight",
                "consumer": "codex",
                "source_system": "codex",
                "project_id": "memcore-cloud",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    project_content = project_called["result"]["structuredContent"]
    assert project_content["decision"] == "surface"
    assert project_content["should_surface"] is True
    assert project_content["active_layers_used"] == ["same_project_workspace"]


def test_raw_gateway_mcp_window_preflight_uses_canonical_index_without_cold_recall(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    marker = "FAST_WINDOW_INDEX_PREFLIGHT_MARKER"
    raw_path = root / "memory" / "local" / "claude_code_cli" / "claude_code_session_jsonl" / "window-a" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("", encoding="utf-8")
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-fast-window",
                "record-fast-window",
                "claude_code_cli",
                "session-a",
                "window-a",
                "memcore-cloud",
                "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                "assistant",
                "claude_code_session_jsonl",
                "native-fast-window",
                "2026-06-10T01:00:00Z",
                1,
                1,
                0,
                160,
                0,
                160,
                f"继续 {marker}：当前窗口已经有 canonical index，可用于自动 preflight。",
                "2026-06-10T01:00:01Z",
            ),
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_cold_recall():
        raise AssertionError("window preflight should not cold-load zhiyi recall")

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_cold_recall)
    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": f"继续 {marker}",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "window",
                "canonical_window_id": "window-a",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["ok"] is True
    assert content["mode"] == "preflight"
    assert content["decision"] == "surface"
    assert content["should_surface"] is True
    assert content["fast_window_preflight"] is True
    assert content["fast_recall_path"] == "canonical_window_index"
    assert content["fast_window_index_status"] == "hit"
    assert content["zhiyi_layer_skipped_for_fast_preflight"] is True
    assert content["recall_performed"] is True
    assert content["active_layers_used"] == ["current_window"]
    assert content["raw_items_count"] == 1
    assert content["must_surface"]
    assert content["must_surface"][0]["source_system"] == "claude_code_cli"
    assert content["must_surface"][0]["session_id"] == "session-a"
    assert content["must_surface"][0]["canonical_window_id"] == "session-a"
    assert content["must_surface"][0]["source_refs_canonical_window_id"] == "window-a"
    assert content["must_surface"][0]["raw_evidence_status"] == "raw_index"
    assert content["raw_excerpt_returned"] is False
    assert content["consumer_receipt"]["receipt_scope"] == "zhixing_preflight_read_only"


def test_raw_gateway_mcp_window_preflight_uses_recent_context_for_short_continuation(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    raw_path = root / "memory" / "local" / "claude_code_cli" / "claude_code_session_jsonl" / "window-a" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("", encoding="utf-8")
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-recent-context",
                "record-recent-context",
                "claude_code_cli",
                "session-a",
                "window-a",
                "memcore-cloud",
                "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                "assistant",
                "claude_code_session_jsonl",
                "native-recent-context",
                "2026-06-10T01:20:00Z",
                1,
                1,
                0,
                180,
                0,
                180,
                "上一轮已经完成 9851 fast index 和 cold import 修复，下一刀是 release gate smoke。",
                "2026-06-10T01:20:01Z",
            ),
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(
        raw_gateway,
        "_load_handle_recall",
        lambda: (_ for _ in ()).throw(AssertionError("short preflight must stay on canonical index fast path")),
    )

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 25,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续发布前检查",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "window",
                "canonical_window_id": "window-a",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["decision"] == "surface"
    assert content["should_surface"] is True
    assert content["fast_window_preflight"] is True
    assert content["fast_window_index_status"] == "hit_recent_context"
    assert content["recall_performed"] is True
    assert content["active_layers_used"] == ["current_window"]
    assert content["raw_items_count"] == 1
    assert content["must_surface"][0]["source_system"] == "claude_code_cli"
    assert content["must_surface"][0]["session_id"] == "session-a"
    assert content["must_surface"][0]["canonical_window_id"] == "session-a"
    assert content["must_surface"][0]["source_refs_canonical_window_id"] == "window-a"
    assert content["must_surface"][0]["raw_evidence_status"] == "raw_index"
    assert content["raw_excerpt_returned"] is False


def test_raw_gateway_mcp_window_preflight_does_not_use_recent_context_for_long_unrelated_task(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    raw_path = root / "memory" / "local" / "claude_code_cli" / "claude_code_session_jsonl" / "window-a" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("", encoding="utf-8")
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-long-unrelated",
                "record-long-unrelated",
                "claude_code_cli",
                "session-a",
                "window-a",
                "memcore-cloud",
                "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                "assistant",
                "claude_code_session_jsonl",
                "native-long-unrelated",
                "2026-06-10T01:30:00Z",
                1,
                1,
                0,
                180,
                0,
                180,
                "上一轮是 9851 preflight 快索引验证，不涉及新网站设计任务。",
                "2026-06-10T01:30:01Z",
            ),
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(
        raw_gateway,
        "_load_handle_recall",
        lambda: (_ for _ in ()).throw(AssertionError("long unmatched window preflight must not cold-load recall")),
    )

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 26,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "修复一个完全不同的问题并重新设计公开网站的按钮样式和配色以及新增营销落地页文案，同时检查另一个全新项目的数据库迁移流程和移动端布局",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "window",
                "canonical_window_id": "window-a",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["decision"] == "silent"
    assert content["silence_reason"] == "no_relevant_evidence"
    assert content["fast_window_preflight"] is True
    assert content["fast_window_index_status"] == "miss_content_filter"
    assert content["recall_performed"] is False
    assert content["matched_count"] == 0
    assert content["must_surface"] == []


def test_raw_gateway_mcp_window_preflight_missing_index_silently_skips_cold_recall(tmp_path, monkeypatch):
    records_db = tmp_path / "memcore" / "output" / "records" / "missing-records.db"
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_cold_recall():
        raise AssertionError("missing index must not fall back to cold zhiyi recall for window preflight")

    monkeypatch.setattr(raw_gateway, "_load_handle_recall", fail_cold_recall)
    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 23,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续发布前检查",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "window",
                "canonical_window_id": "window-a",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["ok"] is True
    assert content["decision"] == "silent"
    assert content["silence_reason"] == "no_relevant_evidence"
    assert content["fast_window_preflight"] is True
    assert content["fast_recall_path"] == "canonical_window_index"
    assert content["fast_window_index_status"] == "records_db_missing"
    assert content["zhiyi_layer_skipped_for_fast_preflight"] is True
    assert content["recall_performed"] is False
    assert content["matched_count"] == 0
    assert content["must_surface"] == []


def test_raw_gateway_mcp_window_preflight_prefers_session_when_registry_window_drifts(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    records_db = root / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    marker = "SESSION_FIRST_WINDOW_DRIFT_MARKER"
    raw_path = root / "memory" / "local" / "claude_code_cli" / "claude_code_session_jsonl" / "db-window" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text("", encoding="utf-8")
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, project_root, source_path,
                raw_path, role, native_type, native_id, timestamp, line_no,
                raw_line_no, source_offset_start, source_offset_end,
                raw_offset_start, raw_offset_end, content_preview, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-window-drift",
                "record-window-drift",
                "claude_code_cli",
                "session-a",
                "db-window",
                "memcore-cloud",
                "/work/memcore-cloud",
                str(raw_path),
                str(raw_path),
                "assistant",
                "claude_code_session_jsonl",
                "native-window-drift",
                "2026-06-10T01:10:00Z",
                1,
                1,
                0,
                160,
                0,
                160,
                f"继续 {marker}：session 精确匹配时，不应被 registry window 漂移挡掉。",
                "2026-06-10T01:10:01Z",
            ),
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    _, raw_gateway = _reload_modules(tmp_path)
    monkeypatch.setattr(
        raw_gateway,
        "_load_handle_recall",
        lambda: (_ for _ in ()).throw(AssertionError("must stay on canonical index fast path")),
    )

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 24,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": f"继续 {marker}",
                "mode": "preflight",
                "consumer": "claude_code_hook",
                "source_system": "claude_code_cli",
                "memory_scope": "window",
                "canonical_window_id": "registry-window",
                "session_id": "session-a",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["decision"] == "surface"
    assert content["fast_window_index_status"] == "hit"
    assert content["must_surface"][0]["session_id"] == "session-a"
    assert content["must_surface"][0]["canonical_window_id"] == "session-a"
    assert content["must_surface"][0]["project_id"] == "memcore-cloud"
    assert content["canonical_window_id_filter"] == "registry-window"


def test_raw_gateway_records_db_path_avoids_guardian_import_on_preflight_path(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    sys.modules.pop("raw_record_guardian", None)
    sys.modules.pop("src.raw_record_guardian", None)

    path = raw_gateway._records_db_path_for_gateway()

    assert path == tmp_path / "memcore" / "output" / "records" / "records.db"
    assert "raw_record_guardian" not in sys.modules
    assert "src.raw_record_guardian" not in sys.modules


def test_raw_gateway_mcp_preflight_skips_trivial_prompt_without_recall(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_query(*args, **kwargs):
        raise AssertionError("trivial preflight must not query raw/source refs")

    monkeypatch.setattr(raw_gateway, "query_raw_source_refs", fail_query)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "好的",
                "mode": "preflight",
                "consumer": "codex",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["ok"] is True
    assert content["mode"] == "preflight"
    assert content["decision"] == "skip"
    assert content["prompt_class"] == "trivial"
    assert content["should_recall"] is False
    assert content["should_surface"] is False
    assert content["recall_performed"] is False
    assert content["silence_reason"] == "trivial_prompt"
    assert content["must_surface"] == []
    assert content["consumer_receipt"]["items_count"] == 0
    assert content["write_performed"] is False


def test_raw_gateway_mcp_preflight_requires_active_anchor_before_recall(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)

    def fail_query(*args, **kwargs):
        raise AssertionError("unanchored preflight must not query raw/source refs")

    monkeypatch.setattr(raw_gateway, "query_raw_source_refs", fail_query)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "继续 Hermes 平台配置问题，接下来怎么做",
                "mode": "preflight",
                "consumer": "codex",
                "limit": 3,
                "excerpt_chars": 220,
            },
        },
    })
    content = called["result"]["structuredContent"]

    assert content["ok"] is True
    assert content["mode"] == "preflight"
    assert content["decision"] == "scope_required"
    assert content["prompt_class"] == "continuation"
    assert content["should_recall"] is True
    assert content["should_surface"] is False
    assert content["recall_performed"] is False
    assert content["scope_missing"] is True
    assert content["recall_status"] == "active_preflight_anchor_required"
    assert content["silence_reason"] == "scope_missing"
    assert "project_id" in content["missing_scope_fields"]
    assert content["must_surface"] == []


def test_raw_gateway_run_uses_threading_http_server(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)
    created = []

    class FakeServer:
        def __init__(self, address, handler):
            self.address = address
            self.handler = handler
            self.served = False
            created.append(self)

        def serve_forever(self):
            self.served = True

    monkeypatch.setattr(raw_gateway, "ThreadingHTTPServer", FakeServer)

    raw_gateway.run(port=9917)

    assert len(created) == 1
    assert created[0].address == ("127.0.0.1", 9917)
    assert created[0].handler is raw_gateway.Handler
    assert created[0].served is True


def test_raw_gateway_exposes_active_memory_routing_status_without_recall(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    status = raw_gateway.active_memory_routing_status()

    assert status["ok"] is True
    assert status["contract"] == "active_memory_routing.v2026.6.14"
    assert status["tiandao_contract"] == "tiandao_active_memory_routing.v1"
    assert status["tiandao_routing_contract"]["contract"] == "tiandao_active_memory_routing.v1"
    assert (
        status["tiandao_memory_experience_layering_contract"]["contract"]
        == "tiandao_memory_experience_layering.v1"
    )
    assert status["tiandao_time_river_contract"]["contract"] == "tiandao_time_river.v1"
    assert status["tiandao_time_river_contract"]["zh_name"] == "时间长河"
    assert status["tiandao_time_river_contract"]["platform_policy"] == "platforms_are_inlets_not_river_laws"
    assert status["tiandao_time_river_contract"]["raw_authority_policy"] == "raw_source_text_is_highest_authority"
    assert (
        status["tiandao_time_river_contract"]["summary_policy"]
        == "summaries_are_navigation_not_source_replacement"
    )
    assert status["all_queryable_memory_layers"] == ["raw", "zhiyi", "xingce", "toolbook"]
    assert status["platform_is_not_memory_layer"] is True
    assert "platform_memory_method_biases" not in status
    assert status["example_signal_layering"]["workflow"] == "xingce"
    assert status["example_signal_layering"]["correction"] == "zhiyi"
    assert status["example_signal_layering"]["skill"] == "xingce"
    assert status["example_signal_layering"]["tool_fact"] == "toolbook"
    assert status["read_only"] is True
    assert status["write_performed"] is False
    assert status["platform_write_performed"] is False
    assert status["memory_write_performed"] is False
    assert status["recall_performed"] is False
    assert status["raw_excerpt_returned"] is False
    assert status["default_memory_scope"] == "active"
    assert status["default_recall_order"] == [
        "current_window",
        "current_session",
        "same_project_workspace",
        "same_workstream_task",
        "stable_user_preferences_tool_facts",
        "explicit_raw_pool_global_only_when_requested",
    ]
    assert status["ordinary_client_contract"]["default_scope"] == "active"
    assert status["ordinary_client_contract"]["requires_current_window_identity"] is False
    assert status["ordinary_client_contract"]["missing_identity_status"] == "active_layered"
    assert status["ordinary_client_contract"]["missing_identity_is_not_no_memory"] is True
    assert status["ordinary_client_contract"]["window_scope_is_strict_when_explicit"] is True
    assert status["ordinary_client_contract"]["active_recall_is_window_first_not_window_only"] is True
    assert status["ordinary_client_contract"]["cross_window_requires_explicit_flag"] is True
    assert status["ordinary_client_contract"]["cross_window_flag"] == "allow_cross_window_recall"
    assert status["scope_modes"]["active"]["memory_base_scope"] == "active_layered"
    assert status["scope_modes"]["active"]["cross_window_read"] is False
    assert status["scope_modes"]["active"]["raw_pool_or_global"] == "explicit_only"
    assert status["scope_modes"]["window"]["cross_window_read"] is False
    assert status["scope_modes"]["platform"]["cross_window_read"] is True
    assert status["scope_modes"]["raw_pool"]["ordinary_clients_require_explicit_flag"] is True
    assert status["special_exceptions"]["hermes_skill_generation_review"]["allowed_without_cross_window_flag"] is True
    assert status["special_exceptions"]["hermes_skill_generation_review"]["requires_explicit_workflow_reason"] is True
    assert status["special_exceptions"]["hermes_skill_generation_review"]["ordinary_hermes_recall_uses_window_scope"] is True
    assert status["example_resolutions"]["ordinary_active_without_identity"]["scope_missing"] is False
    assert status["example_resolutions"]["ordinary_active_without_identity"]["recall_status"] == "active_layered"
    assert status["example_resolutions"]["ordinary_active_without_identity"]["active_layered_continuation"] is True
    assert status["example_resolutions"]["ordinary_window_without_identity"]["scope_missing"] is True
    assert status["example_resolutions"]["ordinary_window_without_identity"]["recall_status"] == "window_identity_required"
    assert status["example_resolutions"]["ordinary_raw_pool_without_flag"]["recall_status"] == "cross_window_permission_required"
    assert status["example_resolutions"]["ordinary_raw_pool_without_flag"]["cross_window_read_allowed"] is False
    assert status["example_resolutions"]["hermes_raw_pool"]["scope_missing"] is True
    assert status["example_resolutions"]["hermes_raw_pool"]["recall_status"] == "cross_window_permission_required"
    assert status["example_resolutions"]["hermes_raw_pool"]["cross_window_read_allowed"] is False
    assert status["example_resolutions"]["hermes_raw_pool"]["hermes_global_exception"] is False
    assert status["example_resolutions"]["hermes_raw_pool"]["hermes_plain_recall_is_global_exception"] is False
    assert status["example_resolutions"]["hermes_skill_generation_raw_pool"]["scope_missing"] is False
    assert status["example_resolutions"]["hermes_skill_generation_raw_pool"]["cross_window_read_allowed"] is True
    assert status["example_resolutions"]["hermes_skill_generation_raw_pool"]["hermes_global_exception"] is True
    assert status["example_resolutions"]["hermes_skill_generation_raw_pool"]["cross_window_reason"] == "skill_generation"
    assert "items" not in status
    assert '"raw_excerpt":' not in json.dumps(status, ensure_ascii=False)


def test_raw_gateway_mcp_initialize_reports_service_version(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    })

    assert initialized["result"]["serverInfo"]["version"] == "2026.6.14"


def test_raw_gateway_health_reports_install_source_identity(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    payload = raw_gateway.health_payload()
    source_path = Path(payload["source_path"])

    assert payload["ok"] is True
    assert payload["service"] == "raw_consumption_gateway"
    assert payload["version"] == "2026.6.14"
    assert payload["preflight"] is True
    assert payload["identity_contract"] == "raw_gateway_health_identity.v1"
    assert source_path == Path(raw_gateway.__file__).resolve()
    assert payload["source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()


def test_hermes_skill_artifact_status_is_recallable_by_probe_id(tmp_path):
    _write_hermes_skill_artifact_status(tmp_path)
    p3, raw_gateway = _reload_modules(tmp_path)

    result = p3.handle_recall({
        "query": "hermes-skill-generation-probe-2fec7027343c3a92 zhiyi-recall-check",
        "top_k": 3,
        "recall_mode": "substring",
    })

    assert result["matched_memories"]
    first = result["matched_memories"][0]
    assert first["type"] == "yifanchen_project_status"
    assert first["_project_status"]["artifact_type"] == "hermes_skill_artifact_status"
    assert first["_project_status"]["probe_id"] == "hermes-skill-generation-probe-2fec7027343c3a92"
    assert first["_project_status"]["skill_artifact_status"] == "probe_only_not_adopted"
    assert "not adopted" in first["detail"] or "not adopted" in first["summary"]

    raw_result = raw_gateway.query_raw_source_refs(
        "Hermes skill generation probe 结论是什么 zhiyi-recall-check",
        source_system="",
        computer_name="",
        session_id="",
        limit=3,
        excerpt_chars=600,
        consumer="codex",
        request_id="test-hermes-status",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert raw_result["items"]
    item = raw_result["items"][0]
    assert item["memory_type"] == "yifanchen_project_status"
    assert item["raw_evidence_status"] == "artifact"
    assert item["project_status"]["artifact_type"] == "hermes_skill_artifact_status"
    assert item["project_status"]["probe_id"] == "hermes-skill-generation-probe-2fec7027343c3a92"
    assert item["project_status"]["skill_artifact_status"] == "probe_only_not_adopted"
    assert item["project_status"]["hermes_skill_write_performed_by_yifanchen"] is False


def test_decision_focus_recall_prioritizes_boundary_memory_over_meta_lookup(tmp_path):
    p3, _ = _reload_modules(tmp_path)
    zhiyi_root = tmp_path / "memcore" / "zhiyi"
    case_path = zhiyi_root / "case_memory" / "case_memory.jsonl"
    error_path = zhiyi_root / "error_memory" / "error_memory.jsonl"
    case_path.parent.mkdir(parents=True, exist_ok=True)
    error_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = tmp_path / "memcore" / "memory" / "local" / "codex" / "codex_session_jsonl" / "project-a" / "decision.jsonl"
    source_ref = {"source_system": "codex", "source_path": str(raw_path)}

    meta_record = {
        "exp_id": "exp-meta-lookup",
        "type": "case_memory",
        "scope": "window/project-a",
        "summary": "案例：我正在查天道中性 / minimax-cn 网页认证不通 / 模型中心是天道 是否成为可召回经验。",
        "detail": "这只是二手排查记录，不是原始结论本身。",
        "source_refs": json.dumps(source_ref, ensure_ascii=False),
        "score": 0.9,
    }
    live_validation_record = {
        "exp_id": "exp-live-validation",
        "type": "error_memory",
        "scope": "window/project-a",
        "summary": "错误相关：现在 live 排序已经改善：第一条变成“忆凡尘读回来自己用，不写回平台，不是模型中心复刻”，这正是之前丢的定论。",
        "detail": "接下来跑全组测试，然后同步本机服务验证 9851。这是验证流水，不是原始定论本身。",
        "source_refs": json.dumps(source_ref, ensure_ascii=False),
        "score": 0.95,
    }
    boundary_record = {
        "exp_id": "exp-boundary-decision",
        "type": "error_memory",
        "scope": "window/project-a",
        "summary": "错误相关：对，这句话把性质拍死了：忆凡尘只读模型事实，不做模型中心。",
        "detail": "定论：天道中性；minimax-cn 网页认证不通；模型中心是天道。忆凡尘读取 OpenClaw/Hermes/Codex 的模型事实供自己用，不写回平台。",
        "source_refs": json.dumps(source_ref, ensure_ascii=False),
        "score": 0.7,
    }
    case_path.write_text(json.dumps(meta_record, ensure_ascii=False) + "\n", encoding="utf-8")
    error_path.write_text(
        json.dumps(live_validation_record, ensure_ascii=False) + "\n"
        + json.dumps(boundary_record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = p3.handle_recall({
        "query": "天道中性 minimax-cn 网页认证不通 模型中心是天道 定论",
        "top_k": 2,
        "recall_mode": "substring",
    })

    assert result["matched_memories"]
    assert result["matched_memories"][0]["exp_id"] == "exp-boundary-decision"
    assert "模型事实" in result["matched_memories"][0]["detail"]


def test_raw_gateway_capability_check_does_not_recall_or_return_excerpts(tmp_path):
    marker = "能力检查不能泄露这段真实记忆 token=USER_OWN_TEXT_CAPABILITY。"
    _write_memory(
        tmp_path,
        "openclaw",
        "openclaw-session",
        "2026-05-28T10:00:00Z",
        "MCP 知意召回经验",
        marker,
    )
    _, raw_gateway = _reload_modules(tmp_path)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "MCP 知意召回经验",
                "mode": "capability_check",
                "consumer": "openclaw-smoke",
                "request_id": "cap-smoke",
            },
        },
    })
    content = called["result"]["structuredContent"]
    encoded = json.dumps(content, ensure_ascii=False)

    assert content["ok"] is True
    assert content["mode"] == "capability_check"
    assert content["recall_performed"] is False
    assert content["raw_excerpt_returned"] is False
    assert content["read_only"] is True
    assert content["write_performed"] is False
    assert content["platform_write_performed"] is False
    assert content["mcp_tools"] == ["zhiyi_recall"]
    assert content["matched_count"] == 0
    assert content["source_refs_count"] == 0
    assert content["raw_items_count"] == 0
    assert content["items"] == []
    assert content["consumer_receipt"]["receipt_scope"] == "capability_check_no_recall"
    assert content["consumer_receipt"]["write_performed"] is False
    assert content["consumer_receipt"]["used_source_refs"] == []
    assert marker not in encoded
    assert '"raw_excerpt":' not in encoded


def test_raw_gateway_mcp_tool_exception_returns_jsonrpc_error(tmp_path, monkeypatch):
    _, raw_gateway = _reload_modules(tmp_path)

    def explode(*_args, **_kwargs):
        raise RuntimeError("simulated recall failure")

    monkeypatch.setattr(raw_gateway, "query_raw_source_refs", explode)

    called = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 44,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "trigger failure"},
        },
    })

    assert called == {
        "jsonrpc": "2.0",
        "id": 44,
        "error": {
            "code": -32603,
            "message": "Internal error while calling tool: RuntimeError: simulated recall failure",
        },
    }
    assert "ok" not in called


def test_raw_gateway_mcp_errors_use_valid_response_id(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    missing_id = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "method": "unknown/method",
        "params": {},
    })
    bool_id = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": True,
        "method": "unknown/method",
        "params": {},
    })

    assert missing_id == {
        "jsonrpc": "2.0",
        "id": "unknown",
        "error": {"code": -32601, "message": "Method not found: unknown/method"},
    }
    assert bool_id["id"] == "unknown"
    assert "ok" not in missing_id


def test_raw_gateway_accepts_loopback_clients_only(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    assert raw_gateway._is_loopback_client(("127.0.0.1", 12345)) is True
    assert raw_gateway._is_loopback_client(("::1", 12345, 0, 0)) is True
    assert raw_gateway._is_loopback_client(("::ffff:127.0.0.1", 12345, 0, 0)) is True
    assert raw_gateway._is_loopback_client(("localhost", 12345)) is True
    assert raw_gateway._is_loopback_client(("192.0.2.10", 12345)) is False
    assert raw_gateway._is_loopback_client(("10.0.0.8", 12345)) is False


def test_raw_gateway_state_dir_override_is_guarded(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    allowed_state = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(allowed_state)
    try:
        assert raw_gateway._raw_segment_state_dir() == allowed_state.resolve()
    finally:
        _clear_raw_gateway_env()

    project_state = ROOT / "output" / "raw_gateway_state_test"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(project_state)
    try:
        assert raw_gateway._raw_segment_state_dir() == project_state.resolve()
    finally:
        _clear_raw_gateway_env()

    for dirname in [".openclaw", ".codex", ".hermes", ".ssh"]:
        os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(tmp_path / dirname / "raw_gateway_state")
        try:
            try:
                raw_gateway._raw_segment_state_dir()
            except ValueError as exc:
                assert "unsafe MEMCORE_RAW_GATEWAY_STATE_DIR" in str(exc)
            else:
                raise AssertionError(f"{dirname} override should be rejected")
        finally:
            _clear_raw_gateway_env()


def test_hermes_provider_defaults_to_window_scope_without_cross_window_mix():
    agent_mod = types.ModuleType("agent")
    memory_provider_mod = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    memory_provider_mod.MemoryProvider = MemoryProvider
    sys.modules["agent"] = agent_mod
    sys.modules["agent.memory_provider"] = memory_provider_mod

    plugin_path = ROOT / "system" / "hermes" / "plugins" / "memcore_yifanchen" / "__init__.py"
    spec = importlib.util.spec_from_file_location("test_memcore_yifanchen_plugin", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    provider = module.MemcoreYifanchenMemoryProvider({})
    provider.initialize("hermes-session")
    assert provider._memory_scope() == "window"

    window_payload = provider._build_payload("帮我接一下前文", session_id="hermes-session")
    assert window_payload["consumer"] == "hermes"
    assert window_payload["memory_scope"] == "window"
    assert window_payload["source_system"] == ""
    assert window_payload["session_id"] == "hermes-session"
    assert "cross_window_reason" not in window_payload

    platform_payload = provider._build_payload(
        "帮我接一下前文",
        session_id="hermes-session",
        memory_scope="platform",
    )
    assert platform_payload["source_system"] == "hermes"

    accidental_raw_pool_provider = module.MemcoreYifanchenMemoryProvider({
        "memory_scope": "raw_pool",
    })
    accidental_raw_pool_provider.initialize("hermes-session")
    assert accidental_raw_pool_provider._memory_scope() == "window"
    accidental_payload = accidental_raw_pool_provider._build_payload("帮我接一下前文", session_id="hermes-session")
    assert accidental_payload["memory_scope"] == "window"
    assert accidental_payload["session_id"] == "hermes-session"
    assert "cross_window_reason" not in accidental_payload

    accidental_dual_provider = module.MemcoreYifanchenMemoryProvider({
        "memory_scope": "dual",
        "cross_window_reason": "ordinary_recall",
    })
    accidental_dual_provider.initialize("hermes-session")
    assert accidental_dual_provider._memory_scope() == "window"

    raw_pool_provider = module.MemcoreYifanchenMemoryProvider({
        "memory_scope": "raw_pool",
        "cross_window_reason": "skill_generation",
    })
    raw_pool_provider.initialize("hermes-session")
    shared_payload = raw_pool_provider._build_payload("帮我接一下前文", session_id="hermes-session")
    assert shared_payload["consumer"] == "hermes"
    assert shared_payload["memory_scope"] == "raw_pool"
    assert shared_payload["source_system"] == ""
    assert shared_payload["computer_name"] == ""
    assert shared_payload["session_id"] == ""
    assert shared_payload["cross_window_reason"] == "skill_generation"

    context = provider._format_context({
        "items": [{
            "source_system": "hermes",
            "session_id": "hermes-session",
            "source_path": "/tmp/hermes.jsonl",
            "raw_excerpt": "Hermes 当前窗口自己的记录。",
        }]
    }, window_payload)
    assert "memory_base_scope: window for normal Hermes recall" in context
    assert "ordinary Hermes recall stays isolated per window" in context
    assert "raw_pool requires an explicit skill-generation or self-review workflow" in context
    assert "injection_boundary: use source_refs as attributed background only" in context


def test_hermes_provider_accepts_multilingual_zhiyi_entry_commands():
    import importlib.util

    plugin_path = ROOT / "system" / "hermes" / "plugins" / "memcore_yifanchen" / "__init__.py"
    spec = importlib.util.spec_from_file_location("test_memcore_yifanchen_plugin_i18n", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    provider = module.MemcoreYifanchenMemoryProvider({})
    provider.initialize("hermes-session")

    zhiyi_payload = provider._build_payload("/zhiyi 这个项目现在做到哪里了", session_id="hermes-session")
    assert zhiyi_payload["query"] == "这个项目现在做到哪里了"
    assert zhiyi_payload["original_query"] == "/zhiyi 这个项目现在做到哪里了"
    assert zhiyi_payload["zhiyi_entry"]["requested"] is True
    assert zhiyi_payload["zhiyi_entry"]["command"] == "/zhiyi"

    english_payload = provider._build_payload("catch me up on this project", session_id="hermes-session")
    assert english_payload["query"] == "catch me up on this project"
    assert english_payload["zhiyi_entry"]["requested"] is True


def test_hermes_provider_sync_turn_posts_consumption_receipt(monkeypatch):
    import importlib.util

    agent_mod = types.ModuleType("agent")
    memory_provider_mod = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    memory_provider_mod.MemoryProvider = MemoryProvider
    sys.modules["agent"] = agent_mod
    sys.modules["agent.memory_provider"] = memory_provider_mod

    plugin_path = ROOT / "system" / "hermes" / "plugins" / "memcore_yifanchen" / "__init__.py"
    spec = importlib.util.spec_from_file_location("test_memcore_yifanchen_plugin_sync", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    captured = {}
    posted = threading.Event()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode("utf-8")

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        posted.set()
        return Response()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    provider = module.MemcoreYifanchenMemoryProvider({
        "receipt_url": "http://127.0.0.1:9850/api/v1/hermes/consumption-receipts",
        "enable_receipts": True,
    })
    provider.initialize("hermes-session")
    provider._last_prefetch = {
        "ok": True,
        "request_id": "hermes-memcore-prefetch-test",
        "matched_count": 2,
        "source_refs_count": 2,
    }

    provider.sync_turn("用户问题", "Hermes 回答", session_id="hermes-session", messages=[{"role": "user", "content": "用户问题"}])

    assert posted.wait(1.0)
    assert captured["url"] == "http://127.0.0.1:9850/api/v1/hermes/consumption-receipts"
    body = captured["body"]
    assert body["event_type"] == "hermes_turn_consumption_receipt"
    assert body["session_id"] == "hermes-session"
    assert body["user_content"] == "用户问题"
    assert body["assistant_content"] == "Hermes 回答"
    assert body["last_prefetch"]["matched_count"] == 2
    assert body["write_boundary"]["hermes_skill_write_performed"] is False
    assert body["write_boundary"]["raw_write_performed"] is False


def test_hermes_provider_reads_profile_config_before_root_config(tmp_path):
    agent_mod = types.ModuleType("agent")
    memory_provider_mod = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    memory_provider_mod.MemoryProvider = MemoryProvider
    sys.modules["agent"] = agent_mod
    sys.modules["agent.memory_provider"] = memory_provider_mod

    hermes_home = tmp_path / "hermes"
    profile_config = hermes_home / "profiles" / "default" / "config.yaml"
    root_config = hermes_home / "config.yaml"
    profile_config.parent.mkdir(parents=True)
    profile_config.write_text(
        "plugins:\n"
        "  memcore_yifanchen:\n"
        "    memory_scope: platform\n"
        "    cross_window_reason: self_review\n"
        "    limit: 2\n",
        encoding="utf-8",
    )
    root_config.write_text(
        "plugins:\n"
        "  memcore_yifanchen:\n"
        "    memory_scope: raw_pool\n"
        "    limit: 7\n",
        encoding="utf-8",
    )

    plugin_path = ROOT / "system" / "hermes" / "plugins" / "memcore_yifanchen" / "__init__.py"
    spec = importlib.util.spec_from_file_location("test_memcore_yifanchen_plugin_profiles", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    provider = module.MemcoreYifanchenMemoryProvider({})
    provider.initialize("hermes-session", hermes_home=str(hermes_home))

    assert provider._memory_scope() == "platform"
    assert provider._build_payload("继续", session_id="hermes-session")["limit"] == 2


def test_raw_experience_provider_legacy_redaction_policy_is_verbatim():
    from src.raw_experience_provider import REDACTION_LEGACY_SECRET_LIKE, build_item

    marker = "平台原文 token=USER_OWN_TEXT_1234567890 password=只是聊天内容"
    item = build_item(marker, source_system="codex", redaction_policy=REDACTION_LEGACY_SECRET_LIKE)

    assert item["raw_excerpt"] == marker
    assert item["_redaction_applied"] is False
    assert item["_redaction_policy"] == "none"
    assert "REDACTED" not in item["raw_excerpt"]


def test_raw_excerpt_segment_resume_reads_next_chunk(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    os.environ["MEMCORE_RAW_SEGMENT_BYTES"] = "4096"
    os.environ["MEMCORE_RAW_SEGMENT_MAX_SEGMENTS"] = "1"
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "big.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        filler = "x" * 5000
        raw_path.write_text(
            json.dumps({
                "timestamp": "filler-1",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": filler},
            }, ensure_ascii=False) + "\n" +
            json.dumps({
                "timestamp": target_id,
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "续读命中的目标内容"},
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        first = raw_gateway._extract_bounded_raw_excerpt_by_cursor_segments(raw_path.resolve(), [target_id], 100)
        assert first[0] == ""
        assert first[1] == "segment_pending"
        state = raw_gateway._load_raw_segment_state()
        assert state
        first_cursor = next(iter(state.values()))["next_offset"]
        assert first_cursor > 0

        second = raw_gateway._extract_bounded_raw_excerpt_by_cursor_segments(raw_path.resolve(), [target_id], 100)
        assert "续读命中的目标内容" in second[0]
        assert second[1] == "raw_segmented"
        state = raw_gateway._load_raw_segment_state()
        saved = next(iter(state.values()))
        assert saved["hit_offset"] >= first_cursor

        third = raw_gateway._extract_bounded_raw_excerpt_by_cursor_segments(raw_path.resolve(), [target_id], 100)
        assert "续读命中的目标内容" in third[0]
        assert third[1] == "raw_segmented"
        state = raw_gateway._load_raw_segment_state()
        assert next(iter(state.values()))["next_offset"] == saved["next_offset"]
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_uses_byte_offsets_without_segment_walk(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    os.environ["MEMCORE_RAW_SEGMENT_BYTES"] = "4096"
    os.environ["MEMCORE_RAW_SEGMENT_MAX_SEGMENTS"] = "1"
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "offset.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        first_line = json.dumps({
            "timestamp": "filler-1",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": "x" * 5000},
        }, ensure_ascii=False) + "\n"
        second_line = json.dumps({
            "timestamp": target_id,
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": "偏移直达命中的目标内容"},
        }, ensure_ascii=False) + "\n"
        raw_path.write_text(first_line + second_line, encoding="utf-8")
        start = len(first_line.encode("utf-8"))
        end = start + len(second_line.encode("utf-8"))

        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(
            str(raw_path),
            [target_id],
            100,
            {"byte_offsets": {target_id: {"start": start, "end": end}}},
        )

        assert "偏移直达命中的目标内容" in excerpt
        assert status == "raw_offset"
        assert evidence_hash
        assert raw_gateway._load_raw_segment_state() == {}
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_builds_offset_index_for_old_source_refs(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    os.environ["MEMCORE_RAW_SEGMENT_BYTES"] = "4096"
    os.environ["MEMCORE_RAW_SEGMENT_MAX_SEGMENTS"] = "1"
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "indexed.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        raw_path.write_text(
            json.dumps({
                "timestamp": "filler-1",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "x" * 5000},
            }, ensure_ascii=False) + "\n" +
            json.dumps({
                "timestamp": target_id,
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "旧经验索引命中的目标内容"},
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(str(raw_path), [target_id], 100)

        assert "旧经验索引命中的目标内容" in excerpt
        assert status == "raw_offset"
        assert evidence_hash
        assert raw_gateway._load_raw_segment_state() == {}
        index = raw_gateway._load_raw_offset_index()
        assert index
        entry = next(iter(index.values()))
        assert target_id in entry["offsets"]
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_decodes_utf16_byte_offsets_without_mojibake(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "utf16-offset.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        marker = "中文定论：天道中性，minimax-cn 网页认证不通，模型中心是天道。"
        first_line = json.dumps({
            "timestamp": "filler-1",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": "前置填充"},
        }, ensure_ascii=False) + "\n"
        second_line = json.dumps({
            "timestamp": target_id,
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": marker},
        }, ensure_ascii=False) + "\n"
        raw_path.write_bytes((first_line + second_line).encode("utf-16"))
        start = len(first_line.encode("utf-16"))
        end = len((first_line + second_line).encode("utf-16"))

        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(
            str(raw_path),
            [target_id],
            300,
            {"byte_offsets": {target_id: {"start": start, "end": end}}},
        )

        assert marker in excerpt
        assert "\ufffd" not in excerpt
        assert status == "raw_offset"
        assert evidence_hash
    finally:
        _clear_raw_gateway_env()


def test_raw_excerpt_builds_offset_index_for_utf16_source_refs_without_mojibake(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)
    state_dir = tmp_path / "state"
    os.environ["MEMCORE_RAW_GATEWAY_STATE_DIR"] = str(state_dir)
    os.environ["MEMCORE_RAW_SEGMENT_BYTES"] = "4096"
    os.environ["MEMCORE_RAW_SEGMENT_MAX_SEGMENTS"] = "1"
    try:
        raw_path = tmp_path / "memcore" / "memory" / "codex" / "local" / "project-a" / "utf16-indexed.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        target_id = "target-message-id"
        marker = "中文定论：天道中性，minimax-cn 网页认证不通，模型中心是天道。"
        payload = (
            json.dumps({
                "timestamp": "filler-1",
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "x" * 2000},
            }, ensure_ascii=False) + "\n" +
            json.dumps({
                "timestamp": target_id,
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": marker},
            }, ensure_ascii=False) + "\n"
        )
        raw_path.write_bytes(payload.encode("utf-16"))

        excerpt, status, evidence_hash = raw_gateway._extract_bounded_raw_excerpt(str(raw_path), [target_id], 300)

        assert marker in excerpt
        assert "\ufffd" not in excerpt
        assert status == "raw_offset"
        assert evidence_hash
        assert raw_gateway._load_raw_segment_state() == {}
    finally:
        _clear_raw_gateway_env()


def test_raw_gateway_falls_back_to_raw_jsonl_when_zhiyi_has_not_indexed_yet(tmp_path):
    marker = "yfc-codex-live-fallback token=USER_OWN_TEXT_RAW_DIRECT"
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "local" / "codex" / "codex_session_jsonl" / "project-a" / "codex-live.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-05-27T14:00:12Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "output": marker,
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        marker,
        source_system="codex",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=300,
        consumer="codex",
        request_id="test-raw-direct",
        canonical_window_id="project-a",
    )

    assert result["items"]
    item = result["items"][0]
    assert item["memory_type"] == "raw_jsonl"
    assert item["raw_evidence_status"] == "raw_direct"
    assert item["raw_mapping_mode"] == "raw_jsonl_fallback"
    assert item["source_system"] == "codex"
    assert item["computer_name"] == "local"
    assert item["native_artifact_format"] == "codex_session_jsonl"
    assert item["raw_archive_layout"] == "computer_first"
    assert marker in item["raw_excerpt"]
    assert item["raw_excerpt"].startswith("[tool]")
    assert item["byte_offsets"]["start"] == 0
    assert item["source_path"] == str(raw_path)


def test_raw_gateway_fallback_prefers_matching_session_when_codex_window_id_is_legacy_project(tmp_path):
    marker = "RAW_FALLBACK_SESSION_FIRST_WINDOW_DRIFT_MARKER"
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "local" / "codex" / "codex_session_jsonl" / "legacy-project-window" / "session-a.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-06-10T01:30:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": marker}],
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        marker,
        source_system="codex",
        computer_name="",
        session_id="session-a",
        limit=5,
        excerpt_chars=300,
        consumer="codex",
        request_id="test-raw-fallback-session-first-window-drift",
        memory_scope="window",
        canonical_window_id="session-a",
    )

    assert result["items"]
    item = result["items"][0]
    assert item["raw_evidence_status"] == "raw_direct"
    assert item["raw_mapping_mode"] == "raw_jsonl_fallback"
    assert item["session_id"] == "session-a"
    assert item["canonical_window_id"] == "session-a"
    assert item["project_id"] == "legacy-project-window"
    assert marker in item["raw_excerpt"]


def test_raw_gateway_fallback_matches_query_terms_across_meta_and_raw_text(tmp_path):
    root = tmp_path / "memcore"
    session_id = "claude-session-1"
    raw_path = (
        root
        / "memory"
        / "WINDOWS-FIXTURE"
        / "claude_code_cli"
        / "claude_code_session_jsonl"
        / "workspace-cb118856"
        / f"{session_id}.jsonl"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    marker = "用户要求检查 Windows 设置，助手给出优化建议。"
    raw_path.write_text(
        json.dumps({
            "timestamp": "2026-06-05T16:45:18.182Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": marker,
            },
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    Path(str(raw_path) + ".meta.json").write_text(
        json.dumps({
            "thread_name": "Windows optimization review",
            "conversation_origin": "claude_desktop_managed_claude_code_session",
            "runtime_consumer": "claude_desktop_managed_claude_code_runtime",
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        "Windows optimization review workspace Claude Desktop",
        source_system="claude_code_cli",
        computer_name="WINDOWS-FIXTURE",
        session_id="",
        limit=5,
        excerpt_chars=300,
        consumer="claude_desktop",
        request_id="test-meta-raw-direct",
        memory_scope="raw_pool",
        allow_cross_window_recall=True,
    )

    assert result["raw_items_count"] >= 1
    item = next(item for item in result["items"] if item["raw_evidence_status"] == "raw_direct")
    assert item["raw_mapping_mode"] == "raw_jsonl_fallback"
    assert item["source_system"] == "claude_code_cli"
    assert item["computer_name"] == "WINDOWS-FIXTURE"
    assert item["canonical_window_id"] == "claude-session-1"
    assert item["project_id"] == "workspace-cb118856"
    assert item["source_refs_canonical_window_id"] == "workspace-cb118856"
    assert marker in item["raw_excerpt"]


def test_raw_gateway_fallback_decodes_gb18030_jsonl_without_mojibake(tmp_path):
    marker = "中文定论：天道中性，minimax-cn 网页认证不通，模型中心是天道。"
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "local" / "codex" / "codex_session_jsonl" / "project-a" / "gb18030-live.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "timestamp": "2026-06-02T09:00:00Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": marker,
        },
    }, ensure_ascii=False) + "\n"
    raw_path.write_bytes(line.encode("gb18030"))
    _, raw_gateway = _reload_modules(tmp_path)

    result = raw_gateway.query_raw_source_refs(
        marker,
        source_system="codex",
        computer_name="",
        session_id="",
        limit=5,
        excerpt_chars=300,
        consumer="codex",
        request_id="test-gb18030-raw-direct",
        canonical_window_id="project-a",
    )

    assert result["items"]
    item = result["items"][0]
    assert item["raw_evidence_status"] == "raw_direct"
    assert item["raw_mapping_mode"] == "raw_jsonl_fallback"
    assert marker in item["raw_excerpt"]
    assert "\ufffd" not in item["raw_excerpt"]


def test_raw_direct_pool_decodes_gb18030_jsonl_without_mojibake(tmp_path):
    marker = "中文定论：天道中性，minimax-cn 网页认证不通，模型中心是天道。"
    root = tmp_path / "memcore"
    raw_path = root / "local" / "codex" / "codex_session_jsonl" / "project-a" / "raw-direct.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "timestamp": "2026-06-02T09:10:00Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": marker,
        },
    }, ensure_ascii=False) + "\n"
    raw_path.write_bytes(line.encode("gb18030"))

    from src.raw_direct_experience_pool import query_raw_direct

    items = query_raw_direct(
        query_hint=marker,
        source_system="codex",
        computer_name="local",
        raw_root=str(root),
        limit=3,
        excerpt_chars=300,
    )

    assert items
    assert marker in items[0]["raw_excerpt"]
    assert "\ufffd" not in items[0]["raw_excerpt"]
