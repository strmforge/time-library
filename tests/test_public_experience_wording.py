from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_docs_keep_experience_distinct_from_skill():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_2026.5.29.md").read_text(encoding="utf-8")

    assert "Experience is not a skill library" in default
    assert "经验本身不是 `f(input) -> output`" in default
    assert "行策不是技能库" in short_zh
    assert "偏好本身仍归知意" in default
    assert "Experience is not the same as a callable function" in en
    assert "Experience is often not `f(input) -> output`" in en
    assert "the preference still belongs to Zhiyi" in en
    assert "Experience is explicitly kept separate from skills" in release_notes
    assert "work-experience layer" in release_notes
    assert "contextual judgment" not in release_notes


def test_public_docs_describe_zhixing_library_in_both_languages():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    intro = (ROOT / "INTRODUCTION.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_2026.5.29.md").read_text(encoding="utf-8")

    assert "知行图书馆" in default
    assert "原始记忆是底本" in default
    assert "行策是工作经验和工具书" in default
    assert "召回可解释" in default
    assert "效果可回放" in default
    assert "知行图书馆证据闭环" in short_zh
    assert "Zhixing Library" in en
    assert "work-experience and toolbook shelf" in en
    assert "recall can explain itself" in en
    assert "知行图书馆" in intro
    assert "Added the Zhixing Library contract" in release_notes


def test_public_docs_explain_agent_install_without_mcp_knowledge():
    default = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    assert default.index("## Copy This To Your Local Agent") < default.index("## Why It Exists")
    assert "Please install Memcore Cloud (Yifanchen)" in default
    assert "Automatically install the Codex skill" in default
    assert "请帮我在本机安装 Memcore Cloud" in default
    assert "请自动安装 Codex skill" in default
    assert "Skill installation is an intent signal" in default
    assert "chat-body parsing stays behind a separate authorization gate" in default
    assert "Copy This To Your Local Agent" in en
    assert "Please install Memcore Cloud (Yifanchen)" in en
    assert "Automatically install the Codex skill" in en
    assert "Skill installation is an intent signal" in en
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
    assert "## Safe Test Checklist" in default
    assert default.index("## Safe Test Checklist") < default.index("## What Makes It Different")
    assert "read_only: true" in default
    assert "recall_performed: false" in default
    assert "raw_excerpt_returned: false" in default
    assert 'mcp_tools: ["zhiyi_recall"]' in default
    assert "## 查看它发现了什么" in default
    assert "本机有哪些 AI 工具" in default
    assert "Claude Desktop 和 Claude Code CLI 会分开看待" in default
    assert "发现某个工具，只代表“看见了入口”" in default
    assert "准备改哪里、是否需要重启、怎么撤回" in default
    assert "不会写平台配置、不会解析聊天正文、不会召回真实记忆" in default
    assert "都不等于授权读取聊天正文" in default
    assert "## Safe Test Checklist" in en
    assert "## Check What It Found" in en
    assert "which AI tools are already on this machine" in en
    assert "Memcore Cloud keeps Claude Desktop and Claude Code CLI separate" in en
    assert "Seeing a tool is not the same as reading its chats" in en
    assert "where it would connect, whether a restart is needed, how to roll back" in en
    assert "This check does not write platform config, parse chat bodies, or recall real memory" in en
    assert "## 安全测试清单" in short_zh
    assert "## 查看它发现了什么" in short_zh
    assert "本机有哪些 AI 工具" in short_zh
    assert "Claude Desktop 和 Claude Code CLI 会分开看待" in short_zh
    assert "准备改哪里、是否需要重启、怎么撤回" in short_zh
    assert "不会写平台配置、不会解析聊天正文、不会召回真实记忆" in short_zh
    assert "都不等于授权读取聊天正文" in short_zh

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

    assert "Hermes 原始记忆供给" in default
    assert "Hermes native review 被触发时" in default
    assert "raw/source_refs 路径指针" in default
    assert "self-review signal" in default
    assert "不直接替 Hermes 写 skill" in default
    assert "Feeds raw pointers to Hermes" in en
    assert "when Hermes native review is triggered" in en
    assert "inspect the original material itself" in en
    assert "self-review signal" in en
    assert "does not write Hermes skills directly" in en
    assert "Hermes 不是只有普通 prefetch" in short_zh
    assert "Hermes native review 被触发时" in short_zh
    assert "raw/source_refs 路径指针" in short_zh
    assert "Hermes status visibility" in default
    assert "Hermes status visibility" in en
    assert "learning liveness" in en
    assert "native learning liveness" in short_zh
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
    assert "Computer-first raw archive contract" in default
    assert "Computer-first raw archive contract" in en
    assert "计算机优先的 raw 归档契约" in short_zh
    assert "legacy layout is no longer created for new records" in default
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

    assert "Claude Desktop 一等公民" in default
    assert "Claude Desktop 和 Claude Code CLI 分开识别" in default
    assert "只装通用 Skill 只是信号" in default
    assert "官方导出包只作为冷启动或补档 fallback" in default
    assert "本机用户态同步清单和 sync-state receipt" in default
    assert "读取和页面展示可以按 `claude_all` 聚合全部 Claude 入口" in default
    assert "Windows 上如果 Claude 通过中转服务或 Claude Code 运行时产生记录" in default
    assert "`storage_owner`、`conversation_origin`、`runtime_consumer`" in default
    assert "不表示官方登录聊天和中转聊天互通" in default
    assert "Treats Claude Desktop as first-class" in en
    assert "Claude Desktop is detected separately from Claude Code CLI" in en
    assert "installing the generic skill is a signal" in en
    assert "Official export archives are cold-start/backfill fallback only" in en
    assert "sync-state receipt" in en
    assert "aggregate all Claude surfaces under `claude_all`" in en
    assert "relay service or Claude Code runtime still keep dual attribution" in en
    assert "Claude Desktop 一等公民" in short_zh
    assert "按 `claude_all` 聚合全部 Claude 入口" in short_zh
    assert "保留双归属字段" in short_zh
    assert "Claude Desktop 一等公民接入" in history
    assert "只装通用 Skill 有信号" in history
    assert "按 `claude_all` 聚合全部 Claude 入口" in history
    assert "Windows 上通过中转服务或 Claude Code 运行时产生的记录" in history
    assert "Claude Desktop as a first-class source system" in changelog
    assert "aggregate all Claude surfaces under `claude_all`" in changelog
    assert "dual attribution fields" in changelog
    assert "sync-state receipt endpoints" in changelog
