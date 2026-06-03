import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "system" / "skills" / "yifanchen-zhiyi"
CLAUDE_SKILL_HELPER = ROOT / "tools" / "install_claude_desktop_skill.py"


def _load_claude_skill_helper():
    sys.modules.pop("install_claude_desktop_skill_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "install_claude_desktop_skill_under_test",
        CLAUDE_SKILL_HELPER,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_zhiyi_skill_package_is_platform_neutral():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    lowered = skill.lower()

    assert "version: 2026.6.4" in skill
    assert "prompt_version: 4" in skill
    assert "local memory library" in skill
    assert "active memory routing" in skill
    assert "standing active memory rule" in skill
    assert "one-time setup note" in skill
    assert "Identity Signal" in skill
    assert "Default Invocation Contract" in skill
    assert "Call `zhiyi_recall` first" in skill
    assert "If `zhiyi_recall` is not available" in skill
    assert "MCP/tool connection is missing" in skill
    assert "active layered" in skill
    assert "current window/session first" in skill
    assert "same project/workspace" in skill
    assert "same workstream/task" in skill
    assert "stable user preferences/tool facts" in skill
    assert "raw-pool/global only" in skill
    assert "when explicitly requested" in skill
    assert "scope_missing=true" in skill
    assert "recall_status=window_identity_required" in skill
    assert "explicit `memory_scope=window`" in skill
    assert "Do not say there is no memory" in skill
    assert "install, upgrade, or test status questions" in skill
    assert "定论" in skill
    assert "下一步" in skill
    assert "接下来呢" in skill
    assert "还有吗" in skill
    assert "然后呢" in skill
    assert "next step" in skill
    assert "what else" in skill
    assert "then what" in skill
    assert "Short follow-up phrases" in skill
    assert "raw records, Zhiyi, Xingce, toolbooks, and errata" in skill
    assert "Ambient Recall Discipline" in skill
    assert "Before making a product or engineering judgment" in skill
    assert "不是第一次" in skill
    assert "你忘了" in skill
    assert "之前纠正过" in skill
    assert "another idea" in skill
    assert "written to the knowledge base" in skill
    assert "Correction Entry" in skill
    assert "zhiyi_errata_candidate" in skill
    assert "Platform Capability Notes" in skill
    assert "When Hermes native review is triggered" in skill
    assert "Hermes can consume raw/source-ref pointers" in skill
    assert "Hermes normal recall remains a strict current-window/current-session surface" in skill
    assert "Hermes raw-pool recall is only for explicit skill/toolbook generation or self-review workflows" in skill
    assert "project-level review workflows" not in skill
    assert "Memcore Cloud emits the self-review signal" in skill
    assert "Claude can use this skill as an instruction signal" in skill
    assert "source_collection=claude_all" in skill
    assert "reader/UI aggregation group" in skill
    assert "official Claude login chats and relay/Claude Code chats are isolated surfaces" in skill
    assert "attribution_mode=dual" in skill
    assert "lineage evidence, not as platform interoperability" in skill
    assert "capability_check" in skill
    assert "Zhixing Library" in skill
    assert "library_id" in skill
    assert "rank_reason" in skill
    assert "codex only" not in lowered
    assert "only supports codex" not in lowered
    assert "openclaw" in lowered
    assert "hermes" in lowered
    assert "codex" in lowered
    assert "claude" in lowered
    assert "mcp" in lowered


def test_zhiyi_skill_declares_mcp_as_connection_layer():
    metadata = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    metadata_lowered = metadata.lower()

    assert "yifanchen-zhiyi" in metadata
    assert "Memcore Cloud Zhiyi" in metadata
    assert "local memory library" in metadata
    assert "before answering about previous decisions" in metadata_lowered
    assert "call zhiyi_recall first" in metadata_lowered
    assert "standing active memory routing rule" in metadata
    assert "one-time setup note" in metadata
    assert "capability check" in metadata
    assert "capability_check" in metadata
    assert "MCP/tool connection is missing" in metadata
    assert "active layered" in metadata
    assert "same project/workspace" in metadata
    assert "same workstream/task" in metadata
    assert "stable user preferences/tool facts" in metadata
    assert "raw-pool/global only when explicitly requested" in metadata
    assert "explicit memory_scope=window" in metadata
    assert "install/test/release status" in metadata
    assert "type: \"mcp\"" in metadata
    assert "http://127.0.0.1:9851/mcp" in metadata


def test_readme_install_prompts_teach_agents_to_install_and_call_recall():
    for relative in ["README.md", "README.en.md"]:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "You are installing Memcore Cloud for me on this machine." in text
        assert "Repository: https://github.com/strmforge/memcore-cloud" in text
        assert "standing memory rule" in text
        assert "not just a one-time setup note" in text
        assert "register the MCP tool named yifanchen-zhiyi" in text
        assert '{"query":"capability check","mode":"capability_check"}' in text
        assert "Keep this rule active from now on" in text
        assert "call zhiyi_recall before answering" in text
        assert "next step" in text
        assert "what else" in text
        assert "then what" in text
        assert "MCP/tool connection is missing" in text
        assert "guessing from memory" in text
        assert "current window/session first" in text
        assert "same project/workspace" in text
        assert "same workstream/task" in text
        assert "stable preferences/tool facts" in text
        assert "raw-pool/global" in text
        assert "do not claim there is no memory" in text

    zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    root = (ROOT / "README.md").read_text(encoding="utf-8")
    for text in (zh, root):
        assert "你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）" in text
        assert "仓库：https://github.com/strmforge/memcore-cloud" in text
        assert "长期记忆规则" in text
        assert "注册名为 yifanchen-zhiyi 的 MCP 工具" in text
        assert '{"query":"capability check","mode":"capability_check"}' in text
        assert "请持续遵守这条规则" in text
        assert "请先调用 zhiyi_recall" in text
        assert "下一步/接下来呢/还有吗/然后呢" in text
        assert "当前窗口/session 优先" in text
        assert "同项目/同工作区" in text
        assert "同工作流/同任务" in text
        assert "稳定偏好/工具事实" in text
        assert "raw-pool/global" in text
        assert "不要说没有记忆" in text
        assert "不要凭印象猜" in text


def test_full_installers_install_codex_skill_and_register_mcp_when_available():
    for relative in [
        "tools/macos_full_install.sh",
        "tools/linux_full_install.sh",
        "tools/windows_full_install.ps1",
    ]:
        text = (ROOT / relative).read_text(encoding="utf-8")
        normalized = text.replace("\\", "/")
        assert "yifanchen-zhiyi" in text
        assert "system/skills/yifanchen-zhiyi" in normalized
        assert "Codex skill installed" in text
        assert "Codex skill:" in text
        assert "http://127.0.0.1:9851/mcp" in text
        assert "codex mcp add yifanchen-zhiyi" in text
        assert "Codex MCP registered" in text
        assert "codex_mcp_bridge.py" in text
        assert "receipt_url" in text
        assert "enable_receipts" in text
        assert "enable_queue_prefetch" in text
        assert "Claude Desktop MCP" in text
        assert "claude_desktop_mcp_bridge.py" in text
        assert "install_claude_desktop_skill.py" in text
        assert "claude_desktop_config.json" in text
        assert '"type": "stdio"' in text
        assert '"PYTHONIOENCODING": "utf-8"' in text
        assert '"PYTHONUTF8": "1"' in text
        assert "MEMCORE_ROOT" in text
        assert "MEMCORE_WINDOW_BINDING_REGISTRY" in text
        assert "MEMCORE_CLAUDE_DESKTOP_CANONICAL_WINDOW_ID" in text
        assert "MEMCORE_CLAUDE_DESKTOP_SESSION_ID" in text
        assert "--window-binding-registry" in text
        assert "--binding-key" in text
        assert "chrome-native-hosts-v2.json" in text
        assert "chrome-native-hosts.json" in text
        assert "claude_desktop" in text
        assert "--create" not in text
        if relative.endswith(".ps1"):
            assert "Find-CodexCli" in text
            assert "$codexExe" in text
            assert "interval_seconds = 5" in text
        else:
            assert "find_codex_cli" in text
            assert "codex_exe" in text
            assert '"interval_seconds": int(raw_ingest.get("interval_seconds") or 5)' in text


def test_codex_mcp_bridge_is_installed_for_current_window_routing():
    bridge = (ROOT / "tools" / "codex_mcp_bridge.py").read_text(encoding="utf-8")
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert "stdio bridge for Codex" in bridge
    assert "CODEX_THREAD_ID" in bridge
    assert "MEMCORE_CODEX_SESSION_ID" in bridge
    assert "MEMCORE_CODEX_CANONICAL_WINDOW_ID" in bridge
    assert "consumer\", \"codex\"" in bridge
    assert "memory_scope\", \"active\"" in bridge
    assert "codex_compact" in bridge
    for text in (mac, linux, windows):
        assert "codex_mcp_bridge.py" in text
        assert "codex mcp add yifanchen-zhiyi" in text
        assert "--endpoint" in text
        assert "http://127.0.0.1:9851/mcp" in text
        assert "--window-binding-registry" in text
        assert "--binding-key" in text
        assert "codex" in text
        assert "MEMCORE_WINDOW_BINDING_REGISTRY" in text
        assert "chrome-native-hosts-v2.json" in text
        assert "chrome-native-hosts.json" in text
        assert "--url http://127.0.0.1:9851/mcp" not in text
        assert '--url "http://127.0.0.1:9851/mcp"' not in text


def test_codex_mcp_bridge_adds_thread_id_as_session_without_guessing():
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 27,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "Codex 当前窗口"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 27,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {
                "ok": True,
                "consumer": "codex",
                "memory_scope": "active",
                "matched_count": 0,
                "items": [],
            },
            "isError": False,
        },
    }

    with patch.dict(os.environ, {"CODEX_THREAD_ID": "codex-thread-27"}, clear=False):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "codex"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["session_id"] == "codex-thread-27"
    assert "canonical_window_id" not in forwarded_args
    assert forwarded_args["limit"] == 3
    assert forwarded_args["excerpt_chars"] == 240
    structured = result["result"]["structuredContent"]
    assert structured["response_budget"]["mode"] == "codex_compact"


def test_codex_mcp_bridge_adds_registry_current_window_binding(tmp_path):
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "codex": {
                        "canonical_window_id": "codex-project-1",
                        "session_id": "codex-session-1",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 28,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "Codex registry"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 28,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            bridge._forward(
                "http://127.0.0.1:9851/mcp",
                request,
                30,
                True,
                registry_path=str(registry_path),
            )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "codex"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["canonical_window_id"] == "codex-project-1"
    assert forwarded_args["session_id"] == "codex-session-1"


def test_installers_allow_skipping_codex_mcp_without_user_learning_mcp():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    wrapper = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "--skip-codex" in mac
    assert "--skip-codex" in linux
    assert "[switch]$SkipCodex" in windows
    assert "[switch]$SkipCodex" in wrapper
    assert "$installerArgs = @{}" in wrapper
    assert '$installerArgs["InstallRoot"] = $Dir' in wrapper
    assert '$installerArgs["SkipCodex"] = $true' in wrapper
    assert "$args +=" not in wrapper


def test_claude_desktop_bridge_and_skip_option_are_installed():
    bridge = (ROOT / "tools" / "claude_desktop_mcp_bridge.py").read_text(encoding="utf-8")
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    wrapper = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "stdio bridge for Claude Desktop" in bridge
    assert "http://127.0.0.1:9851/mcp" in bridge
    assert "Content-Length:" in bridge
    assert 'encode("utf-8")' in bridge
    assert "sys.stdout.buffer" in bridge or 'getattr(sys.stdout, "buffer", None)' in bridge
    assert "DEFAULT_TIMEOUT_SECONDS = 30.0" in bridge
    assert "--full-recall-response" in bridge
    assert "--window-binding-registry" in bridge
    assert "MEMCORE_WINDOW_BINDING_REGISTRY" in bridge
    assert "current_windows" in bridge
    assert "--skip-claude-desktop" in mac
    assert "--skip-claude-desktop" in linux
    assert "[switch]$SkipClaudeDesktop" in windows
    assert "[switch]$SkipClaudeDesktop" in wrapper
    assert '$installerArgs["SkipClaudeDesktop"] = $true' in wrapper
    assert '& $installer @installerArgs' in wrapper
    assert 'Where-Object { $_.Name -like "Claude-*" }' in windows
    for text in (mac, linux, windows):
        assert '"--timeout", "30"' in text
        assert '"--window-binding-registry"' in text
        assert '"--binding-key", "claude_desktop"' in text
        assert '"PYTHONIOENCODING": "utf-8"' in text
        assert '"PYTHONUTF8": "1"' in text
        assert '"MEMCORE_ROOT": str(install_root)' in text
        assert '"MEMCORE_WINDOW_BINDING_REGISTRY": str(registry_path)' in text


def test_claude_desktop_bridge_writes_utf8_json_lines():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    class FakeStdout:
        def __init__(self):
            self.buffer = io.BytesIO()

        def flush(self):
            pass

    fake_stdout = FakeStdout()
    with patch.object(bridge.sys, "stdout", fake_stdout):
        bridge._write_message({"jsonrpc": "2.0", "id": 1, "result": {"text": "中文召回正常"}})

    payload = fake_stdout.buffer.getvalue()
    assert payload.endswith(b"\n")
    assert not payload.startswith(b"Content-Length:")
    decoded = json.loads(payload.decode("utf-8"))
    assert decoded["result"]["text"] == "中文召回正常"
    assert b"\\u4e2d\\u6587" not in payload


def test_claude_desktop_bridge_compacts_recall_payload_for_stdio():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "忆凡尘"}},
    }
    payload = {
        "ok": True,
        "consumer": "claude_desktop_windows",
        "query": "忆凡尘",
        "zhixing_library": {"large": "x" * 5000},
        "hybrid_recall": {"large": "y" * 5000},
        "matched_count": 1,
        "source_refs_count": 1,
        "raw_items_count": 1,
        "items": [
            {
                "library_id": "ZX-1",
                "library_shelf": "raw",
                "memory_type": "case_memory",
                "source_system": "claude_desktop",
                "source_path": "memory/claude_desktop/local/claude_desktop/s1.jsonl",
                "msg_ids": ["m1"],
                "summary": "s" * 2000,
                "raw_excerpt": "r" * 2000,
                "library_card": {"large": "z" * 5000},
                "typed_graph": {"large": "g" * 5000},
            }
        ],
        "consumer_receipt": {
            "consumer": "claude_desktop_windows",
            "request_id": "r1",
            "read_only": True,
            "write_performed": False,
            "used_source_refs": [{"source_path": "too-large-for-stdio"}],
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert "canonical_window_id" not in forwarded_args
    assert "session_id" not in forwarded_args
    assert forwarded_args["limit"] == 3
    assert forwarded_args["excerpt_chars"] == 240
    structured = result["result"]["structuredContent"]
    text_payload = json.loads(result["result"]["content"][0]["text"])
    assert structured == text_payload
    assert "zhixing_library" not in structured
    assert "hybrid_recall" not in structured
    assert "library_card" not in structured["items"][0]
    assert "typed_graph" not in structured["items"][0]
    assert structured["items"][0]["raw_excerpt"].endswith("[truncated]")
    assert structured["response_budget"]["mode"] == "claude_desktop_compact"
    assert "used_source_refs" not in structured["consumer_receipt"]


def test_claude_desktop_bridge_preserves_window_identity_hint():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 17,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "Claude 新窗口"}},
    }
    payload = {
        "ok": True,
        "consumer": "claude_desktop_windows",
        "query": "Claude 新窗口",
        "memory_scope": "window",
        "memory_base_scope": "window",
        "scope_missing": True,
        "recall_status": "window_identity_required",
        "window_binding_hint": (
            "Current-window recall is the default, but this client did not provide "
            "a canonical_window_id or session_id. This is not proof that memory is empty."
        ),
        "missing_scope_fields": ["canonical_window_id", "session_id"],
        "agent_boundary": "isolated_per_window",
        "injection_boundary": "window_scope_required_for_default_recall",
        "recall_performed": False,
        "raw_excerpt_returned": False,
        "matched_count": 0,
        "source_refs_count": 0,
        "raw_items_count": 0,
        "items": [],
        "zhixing_library": {"large": "x" * 5000},
        "hybrid_recall": {"large": "y" * 5000},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 17,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    structured = result["result"]["structuredContent"]
    text_payload = json.loads(result["result"]["content"][0]["text"])
    assert structured == text_payload
    assert structured["scope_missing"] is True
    assert structured["recall_status"] == "window_identity_required"
    assert "not proof that memory is empty" in structured["window_binding_hint"]
    assert structured["missing_scope_fields"] == ["canonical_window_id", "session_id"]
    assert structured["recall_performed"] is False
    assert structured["raw_excerpt_returned"] is False
    assert "zhixing_library" not in structured
    assert "hybrid_recall" not in structured


def test_claude_desktop_bridge_preserves_explicit_recall_budget():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "test",
                "limit": 1,
                "excerpt_chars": 40,
            },
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 8,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["limit"] == 1
    assert forwarded_args["excerpt_chars"] == 40


def test_claude_desktop_bridge_adds_explicit_window_binding_without_guessing():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 18,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 18,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            canonical_window_id="claude-official-1",
            session_id="claude-official-1",
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["canonical_window_id"] == "claude-official-1"
    assert forwarded_args["session_id"] == "claude-official-1"


def test_claude_desktop_bridge_adds_registry_current_window_binding(tmp_path):
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_desktop": {
                        "canonical_window_id": "claude-official-2",
                        "session_id": "claude-session-2",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 19,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 19,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            registry_path=str(registry_path),
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["canonical_window_id"] == "claude-official-2"
    assert forwarded_args["session_id"] == "claude-session-2"


def test_claude_desktop_bridge_normalizes_bare_gateway_error_to_jsonrpc():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    bare_gateway_error = {"ok": False, "error": "simulated gateway failure"}

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            bare_gateway_error,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    assert result == {
        "jsonrpc": "2.0",
        "id": 9,
        "error": {"code": -32603, "message": "simulated gateway failure"},
    }
    assert "ok" not in result


def test_claude_desktop_bridge_normalizes_invalid_jsonrpc_error_id():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    invalid_gateway_error = {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32603, "message": "bad upstream id"},
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            invalid_gateway_error,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    assert result == {
        "jsonrpc": "2.0",
        "id": 10,
        "error": {"code": -32603, "message": "bad upstream id"},
    }


def test_installers_report_claude_skill_update_only_when_installed_count_positive():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    for text in (mac, linux):
        assert "installed_count" in text
        assert "SKILL_RESULT=" in text
        assert "Claude Desktop skill not updated:" in text
        assert 'if [[ "$skill_status" == 0:* ]]' in text

    assert "ConvertFrom-Json" in windows
    assert "installed_count -gt 0" in windows
    assert "Claude Desktop skill not updated for" in windows


def test_windows_installer_preserves_runtime_state_files_on_mirror_update():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert '".checkpoint"' in windows
    assert '".checkpoint_p2.json"' in windows
    assert '"update_history.jsonl"' in windows


def test_claude_desktop_skill_helper_updates_existing_skill_only(tmp_path):
    helper = _load_claude_skill_helper()
    claude_home = tmp_path / "Claude"
    plugin_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text(
        json.dumps(
            {
                "skills": [
                    {"skillId": "other-skill", "name": "Other", "enabled": True},
                    {
                        "skillId": "yifanchen-zhiyi",
                        "name": "Old Yifanchen",
                        "description": "old",
                        "enabled": False,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    skill_src = tmp_path / "skill-src"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text("prompt_version: 2\n", encoding="utf-8")

    result = helper.install_skill(claude_home, skill_src)
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))
    skills = {item["skillId"]: item for item in manifest["skills"]}

    assert result["ok"] is True
    assert result["reason"] == "installed"
    assert result["created_if_missing"] is False
    assert result["installed_count"] == 1
    assert skills["other-skill"]["name"] == "Other"
    assert skills["yifanchen-zhiyi"]["name"] == "Memcore Cloud Zhiyi"
    assert skills["yifanchen-zhiyi"]["enabled"] is True
    assert "previous decisions" in skills["yifanchen-zhiyi"]["description"]
    assert "install/test/release status" in skills["yifanchen-zhiyi"]["description"]
    assert "Standing active memory rule" in skills["yifanchen-zhiyi"]["description"]
    assert "call the yifanchen-zhiyi MCP tool" in skills["yifanchen-zhiyi"]["description"]
    assert "skill is installed but recall cannot run yet" in skills["yifanchen-zhiyi"]["description"]
    assert "Preserve Claude Desktop" in skills["yifanchen-zhiyi"]["description"]
    assert (plugin_root / "skills" / "yifanchen-zhiyi" / "SKILL.md").exists()


def test_claude_desktop_skill_helper_does_not_create_missing_skill_by_default(tmp_path):
    helper = _load_claude_skill_helper()
    claude_home = tmp_path / "Claude"
    plugin_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text(
        '{"skills":[{"skillId":"other-skill","name":"Other","enabled":true}]}',
        encoding="utf-8",
    )
    skill_src = tmp_path / "skill-src"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text("prompt_version: 2\n", encoding="utf-8")

    result = helper.install_skill(claude_home, skill_src)
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["reason"] == "skill_not_found"
    assert result["installed_count"] == 0
    assert [item["skillId"] for item in manifest["skills"]] == ["other-skill"]
    assert not (plugin_root / "skills" / "yifanchen-zhiyi").exists()


def test_claude_desktop_skill_helper_create_flag_creates_missing_skill(tmp_path):
    helper = _load_claude_skill_helper()
    claude_home = tmp_path / "Claude"
    plugin_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text('{"skills":[]}', encoding="utf-8")
    skill_src = tmp_path / "skill-src"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text("prompt_version: 2\n", encoding="utf-8")

    result = helper.install_skill(claude_home, skill_src, create=True)
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["reason"] == "installed"
    assert result["created_if_missing"] is True
    assert result["installed_count"] == 1
    assert manifest["skills"][0]["skillId"] == "yifanchen-zhiyi"
    assert (plugin_root / "skills" / "yifanchen-zhiyi" / "SKILL.md").exists()
