import importlib
import importlib.util
import json
import os
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


def _write_memory(tmp_path, source_system, session_id, msg_id, summary, content):
    root = tmp_path / "memcore"
    raw_path = root / "memory" / source_system / "local" / "project-a" / f"{session_id}.jsonl"
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
        "canonical_window_id": "project-a",
        "session_id": session_id,
        "source_path": str(raw_path),
        "msg_ids": [msg_id],
        "artifact_type": f"{source_system}_session_jsonl",
    }
    record = {
        "exp_id": f"exp-{source_system}-{session_id}",
        "type": "case_memory",
        "canonical_window_id": "project-a",
        "session_id": session_id,
        "computer_id": "local",
        "source_system": source_system,
        "scope": "window/project-a",
        "summary": summary,
        "detail": "shared-base smoke marker 忆凡尘 Codex OpenClaw Hermes",
        "source_refs": json.dumps(refs, ensure_ascii=False),
        "score": 0.8,
    }
    zhiyi_path = root / "zhiyi" / "case_memory" / "case_memory.jsonl"
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
        "skill_path": r"C:\Users\56214\AppData\Local\hermes\skills\yifanchen\zhiyi-recall-check\SKILL.md",
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


def test_raw_gateway_shared_base_keeps_agent_boundary(tmp_path):
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
    )

    assert result["ok"] is True
    assert result["memory_base_scope"] == "shared"
    assert result["agent_boundary"] == "isolated_per_platform"
    assert result["injection_boundary"] == "source_refs_only_no_cross_agent_window_write"
    sources = {item["source_system"] for item in result["items"]}
    assert {"codex", "openclaw"}.issubset(sources)


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


def test_raw_gateway_mcp_initialize_reports_service_version(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    })

    assert initialized["result"]["serverInfo"]["version"] == "2026.6.3"


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


def test_hermes_provider_defaults_to_shared_base_without_agent_mix():
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
    assert provider._memory_scope() == "raw_pool"

    shared_payload = provider._build_payload("帮我接一下前文", session_id="hermes-session")
    assert shared_payload["consumer"] == "hermes"
    assert shared_payload["memory_scope"] == "raw_pool"
    assert shared_payload["source_system"] == ""
    assert shared_payload["computer_name"] == ""

    platform_payload = provider._build_payload(
        "帮我接一下前文",
        session_id="hermes-session",
        memory_scope="platform",
    )
    assert platform_payload["source_system"] == "hermes"

    context = provider._format_context({
        "items": [{
            "source_system": "codex",
            "session_id": "codex-session",
            "source_path": "/tmp/codex.jsonl",
            "raw_excerpt": "Codex 来源只能作为带来源的背景记忆。",
        }]
    }, shared_payload)
    assert "memory_base_scope: shared" in context
    assert "agent_boundary: Hermes/OpenClaw/Codex agents stay isolated" in context
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
