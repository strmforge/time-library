import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = ROOT / "tools" / "claude_code_preflight_hook.py"
INSTALLER_PATH = ROOT / "tools" / "install_claude_code_preflight_hook.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_claude_code_preflight_hook_self_registers_user_prompt_event(tmp_path):
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_under_test")
    registry_path = tmp_path / "window_binding_registry.json"

    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "claude-session-1",
        "transcript_path": "/tmp/claude/projects/session.jsonl",
        "cwd": "/work/project",
        "prompt": "继续发布前检查",
    }

    payload = hook.build_preflight_request(
        event,
        consumer="claude_code_hook",
        limit=2,
        excerpt_chars=120,
        registry_path=str(registry_path),
    )

    assert payload["mode"] == "preflight"
    assert payload["consumer"] == "claude_code_hook"
    assert payload["source_system"] == "claude_code_cli"
    assert payload["query"] == "继续发布前检查"
    assert payload["request_id"] == "claude-code-hook-claude-session-1"
    assert payload["session_id"] == "claude-session-1"
    assert payload["canonical_window_id"] == "claude-session-1"
    assert payload["project_id"] == "project"
    assert payload["project_root"] == "/work/project"
    assert payload["workstream_id"] == ""
    assert payload["task_id"] == ""
    assert payload["memory_scope"] == "active"
    assert payload["limit"] == 2
    assert payload["excerpt_chars"] == 120
    assert payload["window_binding_key"] == "claude_code_cli"
    assert payload["window_binding_source"] == "claude_code_user_prompt_submit_hook"
    assert payload["window_binding_registered"] is True

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    current = registry["current_windows"]["claude_code_cli"]
    assert current["session_id"] == "claude-session-1"
    assert current["canonical_window_id"] == "claude-session-1"
    assert current["source_path"] == "/tmp/claude/projects/session.jsonl"
    assert current["binding_source"] == "claude_code_user_prompt_submit_hook"
    assert current["metadata"]["native_artifact_format"] == "claude_code_user_prompt_submit_event"
    assert current["metadata"]["project_root"] == "/work/project"


def test_claude_code_preflight_hook_adds_matching_registry_binding(tmp_path):
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_registry_match_test")
    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_code_cli": {
                        "source_system": "claude_code_cli",
                        "canonical_window_id": "claude-session-1",
                        "session_id": "claude-session-1",
                        "metadata": {
                            "project_id": "memcore-cloud",
                            "project_root": "/work/memcore-cloud",
                            "workstream_id": "preflight",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "claude-session-1",
        "cwd": "/work/ignored",
        "prompt": "继续发布前检查",
    }

    payload = hook.build_preflight_request(
        event,
        consumer="claude_code_hook",
        limit=2,
        excerpt_chars=120,
        registry_path=str(registry_path),
    )

    assert payload["source_system"] == "claude_code_cli"
    assert payload["session_id"] == "claude-session-1"
    assert payload["canonical_window_id"] == "claude-session-1"
    assert payload["project_id"] == "memcore-cloud"
    assert payload["project_root"] == "/work/memcore-cloud"
    assert payload["workstream_id"] == "preflight"
    assert payload["memory_scope"] == "active"
    assert payload["window_binding_key"] == "claude_code_cli"
    assert payload["window_binding_registered"] is False


def test_claude_code_preflight_hook_replaces_stale_registry_binding_from_live_event(tmp_path):
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_registry_stale_test")
    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_code_cli": {
                        "source_system": "claude_code_cli",
                        "canonical_window_id": "old-session",
                        "session_id": "old-session",
                        "metadata": {"project_id": "old-project"},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "new-session",
        "transcript_path": "/tmp/claude/projects/new-session.jsonl",
        "cwd": "/work/ignored",
        "prompt": "继续发布前检查",
    }

    payload = hook.build_preflight_request(
        event,
        consumer="claude_code_hook",
        limit=2,
        excerpt_chars=120,
        registry_path=str(registry_path),
    )

    assert payload["session_id"] == "new-session"
    assert payload["canonical_window_id"] == "new-session"
    assert payload["project_id"] == "ignored"
    assert payload["project_root"] == "/work/ignored"
    assert payload["memory_scope"] == "active"
    assert payload["window_binding_key"] == "claude_code_cli"
    assert payload["window_binding_source"] == "claude_code_user_prompt_submit_hook"
    assert payload["window_binding_registered"] is True

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    current = registry["current_windows"]["claude_code_cli"]
    assert current["session_id"] == "new-session"
    assert current["metadata"]["project_id"] == "ignored"


def test_claude_code_preflight_hook_does_not_register_without_transcript_anchor(tmp_path):
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_no_transcript_test")
    registry_path = tmp_path / "window_binding_registry.json"
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "new-session",
        "cwd": "/work/project",
        "prompt": "继续发布前检查",
    }

    payload = hook.build_preflight_request(
        event,
        consumer="claude_code_hook",
        limit=2,
        excerpt_chars=120,
        registry_path=str(registry_path),
    )

    assert payload["session_id"] == ""
    assert payload["canonical_window_id"] == ""
    assert payload["project_id"] == "project"
    assert payload["project_root"] == "/work/project"
    assert payload["memory_scope"] == "active"
    assert payload["window_binding_key"] == ""
    assert payload["window_binding_registered"] is False
    assert not registry_path.exists()


def test_claude_code_preflight_hook_preserves_explicit_window_binding():
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_window_binding_test")

    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "new-claude-session",
        "canonical_window_id": "stable-project-window",
        "cwd": "/work/project",
        "prompt": "继续",
    }

    payload = hook.build_preflight_request(event, consumer="claude_code_hook", limit=3, excerpt_chars=160)

    assert payload["session_id"] == "new-claude-session"
    assert payload["canonical_window_id"] == "stable-project-window"
    assert payload["project_id"] == "project"
    assert payload["project_root"] == "/work/project"
    assert payload["memory_scope"] == "active"


def test_claude_code_preflight_hook_preserves_explicit_project_id():
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_project_id_test")

    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "new-claude-session",
        "project_id": "memcore-cloud",
        "cwd": "/work/project",
        "prompt": "继续",
    }

    payload = hook.build_preflight_request(event, consumer="claude_code_hook", limit=3, excerpt_chars=160)

    assert payload["session_id"] == "new-claude-session"
    assert payload["project_id"] == "memcore-cloud"
    assert payload["memory_scope"] == "active"


def test_claude_code_preflight_hook_preserves_only_explicit_project_anchors():
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_explicit_project_anchor_test")

    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "new-claude-session",
        "project_id": "memcore-cloud",
        "project_root": "/work/project",
        "workstream_id": "release-check",
        "task_id": "preflight-hook",
        "cwd": "/work/ignored",
        "prompt": "继续",
    }

    payload = hook.build_preflight_request(event, consumer="claude_code_hook", limit=3, excerpt_chars=160)

    assert payload["project_id"] == "memcore-cloud"
    assert payload["project_root"] == "/work/project"
    assert payload["workstream_id"] == "release-check"
    assert payload["task_id"] == "preflight-hook"
    assert payload["memory_scope"] == "active"


def test_claude_code_preflight_hook_outputs_additional_context_only_on_surface():
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_surface_test")

    context = hook.build_additional_context({
        "decision": "surface",
        "auto_entry_state": "enter",
        "next_action": "apply_must_surface_before_answer",
        "prompt_class": "continuation",
        "confidence": 0.86,
        "must_surface": [
            {
                "library_id": "ZX-XINGCE-1",
                "library_shelf": "xingce",
                "title": "发布前检查",
                "summary": "先跑 release gate，再同步版本。",
                "source_path": "raw/probe_logs/release.jsonl",
                "why_surface": "continuation_state",
                "raw_excerpt": "must not appear",
            }
        ],
        "do_not_repeat": ["不要把内部工具写入公开文案"],
        "acceptance_checks": ["python3 -m pytest -q"],
    })

    assert "Time Library / 忆凡尘 preflight" in context
    assert "auto_entry=enter" in context
    assert "next_action=apply_must_surface_before_answer" in context
    assert "ZX-XINGCE-1" in context
    assert "不要把内部工具写入公开文案" in context
    assert "python3 -m pytest -q" in context
    assert "must not appear" not in context


def test_claude_code_preflight_hook_silent_decision_outputs_nothing():
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_silent_test")

    assert hook.build_additional_context({"decision": "silent", "must_surface": []}) == ""
    assert hook.build_additional_context({"decision": "skip", "must_surface": []}) == ""
    assert hook.build_additional_context({"decision": "scope_required", "must_surface": []}) == ""


def test_claude_code_preflight_hook_default_timeout_covers_indexed_project_fallback():
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_timeout_default_test")

    assert hook.DEFAULT_TIMEOUT_SECONDS >= 1.5


def test_claude_code_preflight_hook_run_prints_json_for_surface(capsys):
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_run_test")

    class Args:
        endpoint = "http://127.0.0.1:9851/api/v1/raw/query"
        timeout = 0.5
        consumer = "claude_code_hook"
        limit = 3
        excerpt_chars = 120
        max_context_chars = 5000
        debug = False

    event_text = json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s1",
        "cwd": "/work/project",
        "prompt": "继续",
    }, ensure_ascii=False)
    with patch.object(hook, "call_preflight") as call:
        call.return_value = {
            "decision": "surface",
            "prompt_class": "continuation",
            "confidence": 0.9,
            "must_surface": [{"library_id": "ZX-1", "library_shelf": "xingce", "summary": "继续事项"}],
        }
        assert hook.run(event_text, Args()) == 0

    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "ZX-1" in data["hookSpecificOutput"]["additionalContext"]


def test_claude_code_preflight_hook_run_forwards_matching_registry_anchor(tmp_path, capsys):
    hook = _load(HOOK_PATH, "claude_code_preflight_hook_run_registry_test")
    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_code_cli": {
                        "canonical_window_id": "s1",
                        "session_id": "s1",
                        "metadata": {
                            "project_id": "memcore-cloud",
                            "project_root": "/work/memcore-cloud",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class Args:
        endpoint = "http://127.0.0.1:9851/api/v1/raw/query"
        timeout = 0.5
        consumer = "claude_code_hook"
        limit = 3
        excerpt_chars = 120
        max_context_chars = 5000
        window_binding_registry = str(registry_path)
        binding_key = ""
        debug = False

    event_text = json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s1",
        "cwd": "/work/ignored",
        "prompt": "继续",
    }, ensure_ascii=False)
    with patch.object(hook, "call_preflight") as call:
        call.return_value = {"decision": "scope_required", "must_surface": []}
        assert hook.run(event_text, Args()) == 0

    payload = call.call_args.args[1]
    assert payload["source_system"] == "claude_code_cli"
    assert payload["session_id"] == "s1"
    assert payload["canonical_window_id"] == "s1"
    assert payload["project_id"] == "memcore-cloud"
    assert payload["project_root"] == "/work/memcore-cloud"
    assert payload["window_binding_key"] == "claude_code_cli"
    assert capsys.readouterr().out == ""


def test_install_claude_code_preflight_hook_merges_settings_without_dropping_existing_hooks(tmp_path):
    installer = _load(INSTALLER_PATH, "install_claude_code_preflight_hook_under_test")
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3",
                                "args": ["existing.py"],
                            }
                        ]
                    }
                ]
            }
        }),
        encoding="utf-8",
    )
    hook_script = tmp_path / "claude_code_preflight_hook.py"
    hook_script.write_text("# hook\n", encoding="utf-8")

    result = installer.install_hook(
        settings,
        hook_script,
        python_executable="/usr/bin/python3",
        endpoint="http://127.0.0.1:9851/api/v1/raw/query",
        timeout=2.5,
        max_context_chars=4000,
    )

    assert result["ok"] is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    groups = data["hooks"]["UserPromptSubmit"]
    serialized = json.dumps(groups)
    assert "existing.py" in serialized
    assert str(hook_script) in serialized
    assert data["timeLibrary"]["preflightHook"]["name"] == "time-library-preflight"
    assert data["memcoreCloud"]["yifanchenPreflightHook"]["name"] == "time-library-preflight"
    assert data["memcoreCloud"]["yifanchenPreflightHook"]["legacyAlias"] is True


def test_install_claude_code_preflight_hook_is_idempotent(tmp_path):
    installer = _load(INSTALLER_PATH, "install_claude_code_preflight_hook_idempotent_test")
    assert installer.DEFAULT_PREFLIGHT_TIMEOUT_SECONDS >= 2.5
    settings = tmp_path / ".claude" / "settings.json"
    hook_script = tmp_path / "claude_code_preflight_hook.py"
    hook_script.write_text("# hook\n", encoding="utf-8")

    for _ in range(2):
        result = installer.install_hook(settings, hook_script, python_executable="/usr/bin/python3")
        assert result["ok"] is True

    data = json.loads(settings.read_text(encoding="utf-8"))
    serialized = json.dumps(data["hooks"]["UserPromptSubmit"])
    assert serialized.count(str(hook_script)) == 1
