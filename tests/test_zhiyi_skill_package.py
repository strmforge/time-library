from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "system" / "skills" / "yifanchen-zhiyi"


def test_zhiyi_skill_package_is_platform_neutral():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    lowered = skill.lower()

    assert "version: 2026.5.30" in skill
    assert "prompt_version: 1" in skill
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

    assert "yifanchen-zhiyi" in metadata
    assert "type: \"mcp\"" in metadata
    assert "http://127.0.0.1:9851/mcp" in metadata
