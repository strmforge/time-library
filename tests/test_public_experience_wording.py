from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_docs_keep_experience_distinct_from_skill():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")

    assert "Experience is not a skill library" in default
    assert "Experience is not a skill library" in default
    assert "行策不是技能库" in short_zh
    assert "Zhiyi keeps preference and intent experience" in default
    assert "Experience is not a skill library" in en
    assert "Zhiyi keeps preference and intent experience" in en
    assert "Xingce keeps work experience" in en
    assert "Experience is not a skill library" in history
    assert "work-experience layer" in history
    assert "contextual judgment" not in history


def test_public_docs_describe_zhixing_library_in_both_languages():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    intro = (ROOT / "INTRODUCTION.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")

    assert "Zhiyi and Xingce" in default
    assert "source records, source refs, corrections, and work experience" in default
    assert "知意和行策" in short_zh
    assert "原始记录仍然是最高事实" in short_zh
    assert "Zhiyi and Xingce" in en
    assert "source records, source refs, corrections, and work experience" in en
    assert "知行图书馆" in intro
    assert "Zhixing Library" in history
    assert "知行图书馆" in history


def test_public_docs_explain_agent_install_without_mcp_knowledge():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    assert default.index("## Paste This To Your Local Agent") < default.index("## Quick Install")
    assert "You are installing Memcore Cloud for me on this machine." in default
    assert "Repository: https://github.com/strmforge/memcore-cloud" in default
    assert "standing memory rule" in default
    assert "not just a one-time setup note" in default
    assert "Memcore Cloud Zhiyi skill/instruction" in default
    assert "register the MCP tool named yifanchen-zhiyi" in default
    assert "call zhiyi_recall before answering" in default
    assert "install/test/release status" in default
    assert "MCP/tool connection is missing" in default
    assert "你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）" in default
    assert "请安装并启动 Memcore Cloud" in default
    assert "长期记忆规则" in default
    assert "添加 Memcore Cloud Zhiyi skill/指令" in default
    assert "请先调用 zhiyi_recall" in default
    assert "下一步/接下来呢/还有吗/然后呢" in default
    assert "不要凭印象猜" in default
    assert "Install once, then it finds your tools" in default
    assert "connects supported Skill/MCP surfaces automatically" in default
    assert "Paste This To Your Local Agent" in en
    assert "You are installing Memcore Cloud for me on this machine." in en
    assert "Repository: https://github.com/strmforge/memcore-cloud" in en
    assert "standing memory rule" in en
    assert "Memcore Cloud Zhiyi skill/instruction" in en
    assert "call zhiyi_recall before answering" in en
    assert "next step" in en
    assert "what else" in en
    assert "then what" in en
    assert "MCP/tool connection is missing" in en
    assert "Install once, then it finds your tools" in en
    assert "connects supported Skill/MCP surfaces automatically" in en
    assert "do not recall my real memory" in en
    assert "你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）" in short_zh
    assert "请先调用 zhiyi_recall" in short_zh
    assert "不要凭印象猜" in short_zh
    for text in (default, en, short_zh):
        assert "yifanchen-zhiyi" in text
        assert "http://127.0.0.1:9851/mcp" in text
        assert "capability check" in text


def test_windows_public_install_is_not_presented_as_wsl():
    public_docs = [
        ROOT / "README.md",
        ROOT / "README.en.md",
        ROOT / "README.zh-CN.md",
        ROOT / "docs" / "wiki" / "Getting-Started.md",
    ]

    for path in public_docs:
        text = path.read_text(encoding="utf-8")
        assert "macOS / Linux / WSL" not in text
        assert "Windows PowerShell" in text
        assert "install.ps1" in text
        assert "memcore-cloud-wsl-test" not in text

    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    wiki = (ROOT / "docs" / "wiki" / "Getting-Started.md").read_text(encoding="utf-8")

    for text in (default, en, wiki):
        assert "WSL is only for development or advanced testing" in text
        assert "Normal Windows installs should" in text

    assert "WSL 只适合开发或高级测试" in zh
    assert "普通 Windows 用户" in zh


def test_public_entry_points_use_memcore_cloud_first():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")
    intro = (ROOT / "INTRODUCTION.md").read_text(encoding="utf-8")
    install_sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    install_ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
    console = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")

    assert default.startswith("# Memcore Cloud")
    assert en.startswith("# Memcore Cloud")
    assert history.startswith("# Memcore Cloud Update History")
    assert intro.startswith("# Memcore Cloud")
    assert "Memcore Cloud is a local personal AI memory center." in intro
    assert "Yifanchen is a local personal AI memory center." not in intro
    assert "connects supported Skill/MCP surfaces automatically" in intro
    assert "connected tools" not in intro
    assert "What Memcore Cloud Means" in default
    assert "What Memcore Cloud Means" in en
    assert "Downloading Memcore Cloud" in install_sh
    assert "Downloading Memcore Cloud" in install_ps1
    assert "[memcore-cloud]" in install_sh
    assert "[memcore-cloud]" in install_ps1
    assert "<title>Memcore Cloud · Local Memory Center</title>" in console
    assert "agentInstall.prompt" in console
    assert "copy-agent-prompt-btn" in console
    assert "standing memory rule" in console
    assert "call zhiyi_recall before answering" in console
    assert "请先调用 zhiyi_recall" in console
    assert "Yifanchen keeps only connection status" not in console
    assert "Yifanchen provides memory in the background" not in console


def test_local_wiki_draft_is_product_facing_and_keeps_internal_strategy_hidden():
    wiki_dir = ROOT / "docs" / "wiki"
    pages = {
        path.name: path.read_text(encoding="utf-8")
        for path in wiki_dir.glob("*.md")
    }

    assert {
        "Home.md",
        "Getting-Started.md",
        "Safe-Capability-Check.md",
        "AI-Tool-Boundaries.md",
        "Memory-Layout.md",
        "Release-History.md",
    }.issubset(set(pages))
    assert pages["Home.md"].startswith("# Memcore Cloud Wiki")
    assert "local-first, source-backed memory" in pages["Home.md"]
    assert "Claude Desktop and Claude Code CLI are first-class surfaces" in pages["AI-Tool-Boundaries.md"]
    assert "memory/<computer-name>/<source-tool>/<app-format>/<window-or-project>/<session>.jsonl" in pages["Memory-Layout.md"]
    assert "最新版保留独立发布说明" in pages["Release-History.md"]

    all_wiki = "\n".join(pages.values())
    assert "Please install Memcore Cloud from https://github.com/strmforge/memcore-cloud" in all_wiki or "You are installing Memcore Cloud for me on this machine." in all_wiki
    assert "请帮我在本机安装 Memcore Cloud" in all_wiki or "你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）" in all_wiki
    assert "read_only: true" in all_wiki
    assert "recall_performed: false" in all_wiki
    assert "finds local AI tools and connects supported Skill/MCP surfaces automatically" in all_wiki

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
        "Nantianmen",
        "南天门",
        "central-node",
        "中央节点",
        "native_artifact_format",
        "source-system-first",
    ]
    for term in hidden_public_terms:
        assert term not in all_wiki


def test_only_current_release_notes_stays_as_root_file():
    release_notes = sorted(path.name for path in ROOT.glob("RELEASE_NOTES_*.md"))
    assert release_notes == ["RELEASE_NOTES_2026.6.4.md"]


def test_2026_6_4_release_note_is_current_public_release():
    release = ROOT / "RELEASE_NOTES_2026.6.4.md"
    text = release.read_text(encoding="utf-8")

    assert release.exists()
    assert "Memcore Cloud 2026.6.4" in text
    assert "Native Windows is now the normal path" in text
    assert "Official Codex on Windows is verified" in text
    assert "Codex MCP uses a current-window bridge" in text
    assert "Active recall is window-first, not window-only" in text
    assert "持续同步状态可见" in text
    assert "active 召回是窗口优先，不是窗口锁死" in text
    assert "Windows 默认走原生安装" in text
    assert "Status: local draft, not published" not in text
    assert "GitHub Wiki has not been synced yet" not in text
    assert not (ROOT / "docs" / "releases" / "drafts" / "2026.6.4.md").exists()


def test_public_docs_explain_safe_testing_and_autodiscovery_boundaries():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    history = (ROOT / "UPDATE_HISTORY.md").read_text(encoding="utf-8")
    release = (ROOT / "RELEASE_NOTES_2026.6.4.md").read_text(encoding="utf-8")

    assert "README.zh-CN.md" in en
    assert "## Safe First Check" in default
    assert default.index("## Safe First Check") < default.index("## What Makes It Different")
    assert "read_only: true" in default
    assert "recall_performed: false" in default
    assert "raw_excerpt_returned: false" in default
    assert 'mcp_tools: ["zhiyi_recall"]' in default
    assert "## What The Local Page Shows" in default
    assert "which AI tools are present on this machine" in default
    assert "which ones can run a safe capability check" in default
    assert "Supported Skill/MCP surfaces can be connected automatically" in default
    assert "Conversation import uses verified local formats" in default
    assert "## AI Tool Surfaces" in default
    assert "## Supported Sources" not in default
    assert "## Safe First Check" in en
    assert "## What The Local Page Shows" in en
    assert "which AI tools are present on this machine" in en
    assert "which ones can run a safe capability check" in en
    assert "Supported Skill/MCP surfaces can be connected automatically" in en
    assert "Conversation import uses verified local formats" in en
    assert "## AI Tool Surfaces" in en
    assert "## Supported Sources" not in en
    assert "## 安全第一步" in short_zh
    assert "## 本地页面能看什么" in short_zh
    assert "这台机器上有哪些 AI 工具" in short_zh
    assert "支持 Skill / MCP 的入口可以自动接入" in short_zh
    assert "对话进入记忆依赖已验证的本地格式采集器" in short_zh
    assert "## AI 工具入口" in short_zh
    assert "## 支持的来源" not in short_zh

    public_docs = "\n".join([default, en, short_zh, changelog, history, release])
    hidden_public_terms = [
        "/api/v1/platforms/thin-adapter-registry",
        "/api/v1/platforms/generic-local-ai-surfaces",
        "/api/v1/platforms/authorized-auto-connect/dry-run",
        "Tiandao thin-adapter",
        "construction build",
        "construction logs",
        "construction notes",
        "docs/construction",
        "Kiro",
        "github_watchlist",
        "platform dictionary",
        "平台字典",
        "泛发现",
        "Nantianmen",
        "南天门",
        "central-node",
        "中央节点",
        "native_artifact_format",
        "source-system-first",
    ]
    for term in hidden_public_terms:
        assert term not in public_docs

    assert "## [2026.6.4] - 2026-06-04" in changelog
    assert "native Windows as the default Windows install path" in changelog
    assert "Codex stdio MCP bridge for current-window recall" in changelog
    assert "model-assisted local tool identification" in changelog
    assert "## [2026.6.2] - 2026-06-02" in changelog
    assert "Claude Desktop recall" in changelog
    assert "local AI tool discovery view" in changelog


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

    assert "## Current Release: 2026.6.4" in default
    assert "## Current Release: 2026.6.4" in en
    assert "See [RELEASE_NOTES_2026.6.4.md](RELEASE_NOTES_2026.6.4.md)" in default
    assert "See [RELEASE_NOTES_2026.6.4.md](RELEASE_NOTES_2026.6.4.md)" in en
    assert "[UPDATE_HISTORY.md](UPDATE_HISTORY.md)" in default
    assert "[UPDATE_HISTORY.md](UPDATE_HISTORY.md)" in en
    assert "完整历史更新见 [UPDATE_HISTORY.md](UPDATE_HISTORY.md)" in short_zh
    assert "Organized local records" in history
    assert "按电脑整理本机记录" in history
    assert "new records are grouped by computer first" in history
    assert "先按电脑分组，再按产生记录的 AI 工具分组" in history

    assert "## 2026.5.29 新增" not in default
    assert "## 2026.5.30 新增" not in default
    assert "## 2026.5.31 新增" not in default
    assert "## New In 2026.5.29" not in en
    assert "## New In 2026.5.30" not in en
    assert "## New In 2026.5.31" not in en

    assert "### 2026.6.2" in history
    assert "### 2026.6.1" in history
    assert "### 2026.5.29" in history
    assert "### 2026.5.28" in history
    assert "### 2026.5.27" in history
    assert "### 2026.5.30" in history
    assert "### 2026.5.31" in history
    assert "Zhixing Library" in history
    assert "Hermes 学习心跳" in history
    assert "Codex 本地会话入记忆底座" in history
    assert "更轻的知意调用方式" in history
    assert "Codex local sessions enter memory" in history
    assert "Lighter Zhiyi entry" in history
    assert "RELEASE_NOTES_2026.6.1.md" not in history
    assert "RELEASE_NOTES_2026.5.28.md" not in history
    assert "RELEASE_NOTES_2026.5.27.md" not in history


def test_public_docs_show_current_2026_6_4_version():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_2026.6.4.md").read_text(encoding="utf-8")

    assert "version-2026.6.4" in default
    assert "2026.6.4 is the current published release of Memcore Cloud" in default
    assert "version-2026.6.4" in en
    assert "2026.6.4 is the current published release of Memcore Cloud" in en
    assert "当前发布版本：**2026.6.4**" in short_zh
    assert "2026.6.4 是当前已发布版本" in short_zh
    assert "Memcore Cloud 2026.6.4" in release_notes
    assert "Native Windows is the default Windows path" in default
    assert "Official Windows Codex can be connected even when `codex.exe` is not on `PATH`" in default
    assert "Windows 默认走原生安装" in short_zh
    assert "官方 Windows Codex" in short_zh
    assert "2026.6.2 is the current published release" not in default
    assert "2026.6.2 is the current published release" not in en
    assert "2026.6.2 是当前已发布版本" not in short_zh
    for text in (default, en, short_zh):
        assert "Current Development Version" not in text
        assert "latest published release is still [2026.5.31]" not in text
        assert "当前开发版本" not in text
        assert "最新已发布版本仍是 [2026.5.31]" not in text
        assert "2026.6.1 is the current published release" not in text
        assert "2026.6.1 是当前已发布版本" not in text


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
    assert "Claude Code CLI from a boundary-only object to a connectable candidate" in changelog
    assert "keeping it separate from Claude Desktop" in changelog
