import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_natural_language_correction_builds_review_only_errata_candidate():
    errata = importlib.import_module("zhiyi_errata")

    result = errata.build_zhiyi_errata_candidate({
        "correction_text": "这条记录不对，不是我的原话",
        "target": {
            "library_id": "ZX-ZHIYI-QCLAW",
            "source_refs": {
                "source_system": "codex",
                "source_path": "raw/codex/session.jsonl",
            },
        },
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    candidate = result["candidate"]
    assert candidate["candidate_type"] == "zhiyi_errata_candidate"
    assert candidate["library_shelf"] == "errata"
    assert candidate["verbatim_feedback"] == "这条记录不对，不是我的原话"
    assert candidate["target_ref"] == "ZX-ZHIYI-QCLAW"
    assert candidate["requires_authorization"] is True
    assert candidate["matched_intent"]["route"] == "correction_errata"
    for key in [
        "write_performed",
        "raw_write_performed",
        "zhiyi_write_performed",
        "xingce_write_performed",
        "errata_write_performed",
        "platform_write_performed",
    ]:
        assert candidate[key] is False


def test_non_correction_does_not_create_errata_candidate():
    errata = importlib.import_module("zhiyi_errata")

    result = errata.build_zhiyi_errata_candidate({
        "message": "查一下我之前说过什么",
    })

    assert result["ok"] is False
    assert result["candidate_created"] is False
    assert result["candidate"] is None
    assert result["write_performed"] is False
    assert "correction_intent" in result["missing"]
    assert result["error"] == "not_a_memory_correction"
