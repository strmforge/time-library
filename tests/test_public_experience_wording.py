from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_docs_keep_experience_distinct_from_skill():
    zh = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_2026.5.29.md").read_text(encoding="utf-8")

    assert "经验不是可调用函数" in zh
    assert "经验本身不是 `f(input) -> output`" in zh
    assert "行策不是技能库" in short_zh
    assert "偏好本身仍归知意" in zh
    assert "Experience is not the same as a callable function" in en
    assert "Experience is often not `f(input) -> output`" in en
    assert "the preference still belongs to Zhiyi" in en
    assert "Experience is explicitly kept separate from skills" in release_notes
    assert "work-experience layer" in release_notes
    assert "contextual judgment" not in release_notes


def test_public_docs_describe_zhixing_library_in_both_languages():
    zh = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    intro = (ROOT / "INTRODUCTION.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_2026.5.29.md").read_text(encoding="utf-8")

    assert "知行图书馆" in zh
    assert "原始记忆是底本" in zh
    assert "行策是工作经验和工具书" in zh
    assert "召回可解释" in zh
    assert "效果可回放" in zh
    assert "知行图书馆证据闭环" in short_zh
    assert "Zhixing Library" in en
    assert "work-experience and toolbook shelf" in en
    assert "recall can explain itself" in en
    assert "知行图书馆" in intro
    assert "Added the Zhixing Library contract" in release_notes


def test_public_docs_explain_agent_install_without_mcp_knowledge():
    zh = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    assert "让你的 AI agent 帮你安装" in zh
    assert "请帮我在本机安装忆凡尘" in zh
    assert "不需要先理解 Skill 或 MCP" in zh
    assert "Codex skill" in zh
    assert "忆凡尘是一座本机记忆图书馆" in zh
    assert "不要召回我的真实记忆" in zh
    assert "Ask Your AI Agent To Install It" in en
    assert "Please install Yifanchen" in en
    assert "Automatically install the Codex skill" in en
    assert "users do not need to understand Skill or MCP first" in en
    assert "Yifanchen is the local memory library" in en
    assert "do not recall my real memory" in en
    assert "请帮我在本机安装忆凡尘" in short_zh
    for text in (zh, en, short_zh):
        assert "yifanchen-zhiyi" in text
        assert "http://127.0.0.1:9851/mcp" in text
        assert "capability check" in text


def test_public_docs_explain_hermes_native_skill_learning_boundary():
    zh = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "Hermes 原始记忆供给" in zh
    assert "Hermes native review 被触发时" in zh
    assert "raw/source_refs 路径指针" in zh
    assert "self-review signal" in zh
    assert "不直接替 Hermes 写 skill" in zh
    assert "Feeds raw pointers to Hermes" in en
    assert "when Hermes native review is triggered" in en
    assert "inspect the original material itself" in en
    assert "self-review signal" in en
    assert "does not write Hermes skills directly" in en
    assert "Hermes 不是只有普通 prefetch" in short_zh
    assert "Hermes native review 被触发时" in short_zh
    assert "raw/source_refs 路径指针" in short_zh
    assert "Hermes 学习心跳" in zh
    assert "natural learning chain has gone cold" in en
    assert "native learning liveness" in short_zh
    assert "raw-pointer-to-native-skill-learning chain" in changelog


def test_public_docs_show_current_2026_5_31_version():
    zh = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    assert "version-2026.5.31" in zh
    assert "当前版本：**2026.5.31**" in zh
    assert "version-2026.5.31" in en
    assert "Current version: **2026.5.31**" in en
    assert "当前版本：**2026.5.31**" in short_zh
