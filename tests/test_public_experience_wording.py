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
