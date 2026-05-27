from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_docs_keep_experience_distinct_from_skill():
    zh = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    short_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    release_notes = (ROOT / "RELEASE_NOTES_2026.5.28.md").read_text(encoding="utf-8")

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
