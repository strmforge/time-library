from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "system" / "skills" / "yifanchen-zhiyi"


def test_zhiyi_skill_package_is_platform_neutral():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    lowered = skill.lower()

    assert "version: 2026.5.31" in skill
    assert "prompt_version: 1" in skill
    assert "local memory library" in skill
    assert "Identity Signal" in skill
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
    assert "Yifanchen does not directly write Hermes skills" in skill
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

    assert "yifanchen-zhiyi" in metadata
    assert "local memory library" in metadata
    assert "before judging" in metadata
    assert "type: \"mcp\"" in metadata
    assert "http://127.0.0.1:9851/mcp" in metadata


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
        assert "receipt_url" in text
        assert "enable_receipts" in text
        assert "enable_queue_prefetch" in text


def test_installers_allow_skipping_codex_mcp_without_user_learning_mcp():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    wrapper = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "--skip-codex" in mac
    assert "--skip-codex" in linux
    assert "[switch]$SkipCodex" in windows
    assert "[switch]$SkipCodex" in wrapper
    assert '$args += "-SkipCodex"' in wrapper
