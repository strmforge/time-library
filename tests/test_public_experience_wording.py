from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_docs_keep_experience_distinct_from_skill():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_2026.5.29.md").read_text(encoding="utf-8")

    assert "Experience is not a skill library" in default
    assert "Experience is not a skill library" in default
    assert "行策不是技能库" in short_zh
    assert "Zhiyi keeps preference and intent experience" in default
    assert "Experience is not a skill library" in en
    assert "Zhiyi keeps preference and intent experience" in en
    assert "Xingce keeps work experience" in en
    assert "Experience is explicitly kept separate from skills" in release_notes
    assert "work-experience layer" in release_notes
    assert "contextual judgment" not in release_notes


def test_public_docs_describe_zhixing_library_in_both_languages():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    intro = (ROOT / "INTRODUCTION.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_2026.5.29.md").read_text(encoding="utf-8")

    assert "Zhiyi and Xingce" in default
    assert "source records, source refs, corrections, and work experience" in default
    assert "知意和行策" in short_zh
    assert "原始记录仍然是最高事实" in short_zh
    assert "Zhiyi and Xingce" in en
    assert "source records, source refs, corrections, and work experience" in en
    assert "知行图书馆" in intro
    assert "Added the Zhixing Library contract" in release_notes


def test_public_docs_explain_agent_install_without_mcp_knowledge():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    assert default.index("## Copy This To Your Local Agent") < default.index("## Quick Install")
    assert "Please install Memcore Cloud (Yifanchen)" in default
    assert "Automatically install the Codex skill" in default
    assert "请帮我在本机安装 Memcore Cloud" in default
    assert "请自动安装 Codex skill" in default
    assert "Installing a skill is a connection signal" in default
    assert "not permission to read chat bodies" in default
    assert "Copy This To Your Local Agent" in en
    assert "Please install Memcore Cloud (Yifanchen)" in en
    assert "Automatically install the Codex skill" in en
    assert "Installing a skill is a connection signal" in en
    assert "do not recall my real memory" in en
    assert "请帮我在本机安装 Memcore Cloud" in short_zh
    for text in (default, en, short_zh):
        assert "yifanchen-zhiyi" in text
        assert "http://127.0.0.1:9851/mcp" in text
        assert "capability check" in text


def test_public_docs_explain_safe_testing_and_autodiscovery_boundaries():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "README.zh-CN.md" in en
    assert "## Safe First Check" in default
    assert default.index("## Safe First Check") < default.index("## What Makes It Different")
    assert "read_only: true" in default
    assert "recall_performed: false" in default
    assert "raw_excerpt_returned: false" in default
    assert 'mcp_tools: ["zhiyi_recall"]' in default
    assert "## What The Local Page Shows" in default
    assert "which AI tools are present on this machine" in default
    assert "It does not write app config, parse chat bodies, or recall real memory" in default
    assert "## Safe First Check" in en
    assert "## What The Local Page Shows" in en
    assert "which AI tools are present on this machine" in en
    assert "It does not write app config, parse chat bodies, or recall real memory" in en
    assert "## 安全第一步" in short_zh
    assert "## 本地页面能看什么" in short_zh
    assert "这台机器上有哪些 AI 工具" in short_zh
    assert "发现某个工具，只代表“看见了入口”" in short_zh

    public_docs = "\n".join([default, en, short_zh])
    hidden_public_terms = [
        "/api/v1/platforms/thin-adapter-registry",
        "/api/v1/platforms/generic-local-ai-surfaces",
        "/api/v1/platforms/authorized-auto-connect/dry-run",
        "Tiandao thin-adapter",
        "Kiro",
        "github_watchlist",
        "platform dictionary",
        "平台字典",
        "泛发现",
    ]
    for term in hidden_public_terms:
        assert term not in public_docs

    assert "/api/v1/platforms/thin-adapter-registry" in changelog
    assert "/api/v1/platforms/generic-local-ai-surfaces" in changelog
    assert "/api/v1/platforms/authorized-auto-connect/dry-run" in changelog


def test_public_docs_explain_hermes_native_skill_learning_boundary():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "Hermes can inspect sources itself" in default
    assert "provide raw/source-ref pointers" in default
    assert "Hermes-owned skill changes remain Hermes-owned" in default
    assert "Hermes can inspect sources itself" in en
    assert "provide raw/source-ref pointers" in en
    assert "Hermes-owned skill changes remain Hermes-owned" in en
    assert "Hermes" in short_zh
    assert "raw/source refs 路径指针" in short_zh
    assert "raw-pointer-to-native-skill-learning chain" in changelog


def test_public_readme_keeps_old_release_highlights_in_history_page():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")

    assert "## Current Release: 2026.6.1" in default
    assert "## Current Release: 2026.6.1" in en
    assert "See [RELEASE_NOTES_2026.6.1.md](RELEASE_NOTES_2026.6.1.md)" in default
    assert "See [RELEASE_NOTES_2026.6.1.md](RELEASE_NOTES_2026.6.1.md)" in en
    assert "[UPDATE_HISTORY.md](UPDATE_HISTORY.md)" in default
    assert "[UPDATE_HISTORY.md](UPDATE_HISTORY.md)" in en
    assert "完整历史更新见 [UPDATE_HISTORY.md](UPDATE_HISTORY.md)" in short_zh
    assert "Computer-first archive layout" in default
    assert "Computer-first archive layout" in en
    assert "计算机优先的 raw 归档契约" in short_zh
    assert "new raw records use `memory/{computer_name}/{source_system}/{native_artifact_format}/...`" in default
    assert "历史 source-system-first 目录只保留读取兼容" in short_zh

    assert "## 2026.5.29 新增" not in default
    assert "## 2026.5.30 新增" not in default
    assert "## 2026.5.31 新增" not in default
    assert "## New In 2026.5.29" not in en
    assert "## New In 2026.5.30" not in en
    assert "## New In 2026.5.31" not in en

    assert "### 2026.5.29" in history
    assert "### 2026.5.30" in history
    assert "### 2026.5.31" in history
    assert "Zhixing Library" in history
    assert "Hermes 学习心跳" in history


def test_public_docs_show_current_2026_6_1_version():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_2026.6.1.md").read_text(encoding="utf-8")

    assert "version-2026.6.1" in default
    assert "2026.6.1 is the current published release of Memcore Cloud" in default
    assert "version-2026.6.1" in en
    assert "2026.6.1 is the current published release of Memcore Cloud" in en
    assert "当前发布版本：**2026.6.1**" in short_zh
    assert "2026.6.1 是当前已发布版本" in short_zh
    assert "Memcore Cloud 2026.6.1" in release_notes
    for text in (default, en, short_zh):
        assert "Current Development Version" not in text
        assert "latest published release is still [2026.5.31]" not in text
        assert "当前开发版本" not in text
        assert "最新已发布版本仍是 [2026.5.31]" not in text


def test_public_docs_treat_claude_desktop_as_first_class_not_export_only():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "Claude is handled carefully" in default
    assert "Claude Desktop and Claude Code CLI can both connect" in default
    assert "remain separate surfaces" in default
    assert "Official, relay, and CLI-related records keep attribution boundaries" in default
    assert "Claude is handled carefully" in en
    assert "Claude Desktop and Claude Code CLI can both connect" in en
    assert "remain separate surfaces" in en
    assert "Official, relay, and CLI-related records keep attribution boundaries" in en
    assert "工具边界不混读" in short_zh
    assert "Claude Desktop 和 Claude Code CLI 分开看待" in short_zh
    assert "官方登录、中转服务、CLI 运行时产生的记录会保留归属边界" in short_zh
    assert "Claude Desktop 一等公民接入" in history
    assert "只装通用 Skill 有信号" in history
    assert "按 `claude_all` 聚合全部 Claude 入口" in history
    assert "Windows 上通过中转服务或 Claude Code 运行时产生的记录" in history
    assert "Claude Desktop as a first-class source system" in changelog
    assert "aggregate all Claude surfaces under `claude_all`" in changelog
    assert "dual attribution fields" in changelog
    assert "sync-state receipt endpoints" in changelog
