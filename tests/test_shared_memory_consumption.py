import importlib
import importlib.util
import json
import os
import sys
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


def test_raw_gateway_mcp_initialize_reports_2026_5_29(tmp_path):
    _, raw_gateway = _reload_modules(tmp_path)

    initialized = raw_gateway.handle_mcp_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    })

    assert initialized["result"]["serverInfo"]["version"] == "2026.5.30"


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


def test_raw_gateway_falls_back_to_raw_jsonl_when_zhiyi_has_not_indexed_yet(tmp_path):
    marker = "yfc-codex-live-fallback token=USER_OWN_TEXT_RAW_DIRECT"
    root = tmp_path / "memcore"
    raw_path = root / "memory" / "codex" / "local" / "project-a" / "codex-live.jsonl"
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
    assert marker in item["raw_excerpt"]
    assert item["raw_excerpt"].startswith("[tool]")
    assert item["byte_offsets"]["start"] == 0
    assert item["source_path"] == str(raw_path)
