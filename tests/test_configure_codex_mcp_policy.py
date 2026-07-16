from pathlib import Path

from tools.configure_codex_mcp_policy import configure_codex_mcp_policy


BASE_CONFIG = """\
[mcp_servers.time-library]
command = "python3"
args = ["codex_mcp_bridge.py"]

[mcp_servers.time-library.env]
PYTHONUTF8 = "1"
"""


def test_configure_codex_mcp_policy_adds_only_recall_and_ack(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(BASE_CONFIG, encoding="utf-8")

    result = configure_codex_mcp_policy(config)
    updated = config.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert result["changed"] is True
    assert result["other_tools_auto_approved"] is False
    assert "[mcp_servers.time-library.tools.time_library_recall]" in updated
    assert "[mcp_servers.time-library.tools.time_library_delivery_ack]" in updated
    assert updated.count('approval_mode = "approve"') == 2
    assert "time_library_reading_area" not in updated
    assert (tmp_path / "config.toml.time-library-policy.backup").read_text(
        encoding="utf-8"
    ) == BASE_CONFIG


def test_configure_codex_mcp_policy_is_idempotent(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(BASE_CONFIG, encoding="utf-8")

    first = configure_codex_mcp_policy(config)
    after_first = config.read_bytes()
    second = configure_codex_mcp_policy(config)

    assert first["changed"] is True
    assert second["ok"] is True
    assert second["changed"] is False
    assert config.read_bytes() == after_first


def test_configure_codex_mcp_policy_preserves_existing_tool_fields(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text(
        BASE_CONFIG
        + """

[mcp_servers."time-library".tools.time_library_recall]
enabled = true
approval_mode = "prompt"
""",
        encoding="utf-8",
    )

    result = configure_codex_mcp_policy(config)
    updated = config.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert "enabled = true" in updated
    assert 'approval_mode = "prompt"' not in updated
    assert updated.count('approval_mode = "approve"') == 2


def test_configure_codex_mcp_policy_refuses_missing_server(tmp_path: Path):
    config = tmp_path / "config.toml"
    original = '[mcp_servers.other]\ncommand = "other"\n'
    config.write_text(original, encoding="utf-8")

    result = configure_codex_mcp_policy(config)

    assert result["ok"] is False
    assert result["error"] == "codex_mcp_server_section_missing"
    assert result["write_performed"] is False
    assert config.read_text(encoding="utf-8") == original
