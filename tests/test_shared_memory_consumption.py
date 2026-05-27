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

    shared_payload = provider._build_payload("召唤知意", session_id="hermes-session")
    assert shared_payload["consumer"] == "hermes"
    assert shared_payload["memory_scope"] == "raw_pool"
    assert shared_payload["source_system"] == ""

    platform_payload = provider._build_payload(
        "召唤知意",
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
