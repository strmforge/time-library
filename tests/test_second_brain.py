import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_second_brain_contract_is_time_river_major_module():
    from second_brain import get_second_brain_contract

    contract = get_second_brain_contract()

    assert contract["ok"] is True
    assert contract["contract"] == "tiandao_second_brain.v1"
    assert contract["zh_name"] == "第二大脑"
    assert contract["en_name"] == "Second Brain"
    assert contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert contract["first_major_module_under_time_river"] is True
    assert contract["not_raw_origin"] is True
    assert contract["write_performed"] is False
    assert "material_processing_pipeline" in contract["orchestrated_modules"]
    assert "time_river_sediment" in contract["orchestrated_modules"]


def test_second_brain_dry_run_orchestrates_existing_candidates():
    from second_brain import build_second_brain_dry_run

    result = build_second_brain_dry_run({
        "need": "整理 Codex raw 起源和记录守护资料",
        "batch_size": 2,
        "wip_limit": 1,
        "sources": [
            {
                "title": "Codex raw origin report",
                "path": "/notes/codex-raw-origin.md",
                "summary": "Codex raw 起源、记录守护、回源证据。",
                "content": "Codex raw 起源需要记录守护，source_refs 与 verbatim excerpt 必须保留。",
                "source_refs": {"source_path": "/notes/codex-raw-origin.md"},
                "priority": "high",
            },
            {
                "title": "Unrelated color draft",
                "path": "/notes/colors.md",
                "summary": "颜色草稿。",
            },
        ],
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["contract"] == "tiandao_second_brain.v1"
    assert result["zh_name"] == "第二大脑"
    assert result["en_name"] == "Second Brain"
    assert result["write_performed"] is False
    assert result["raw_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["material_pipeline"]["ok"] is True
    assert result["summary"]["source_count"] == 2
    assert result["summary"]["high_signal_count"] == 1
    assert result["summary"]["evidence_plan_count"] == 1
    assert result["summary"]["context_unit_count"] == 1
    assert result["summary"]["method_signal_count"] == 1
    assert result["summary"]["compaction_plan_count"] == 1
    assert result["summary"]["sediment_link_count"] == 1
    assert result["receipt"]["contract"] == "second_brain_receipt.v1"
    assert result["receipt"]["promotion_gate"] == "sample_check_and_replay_before_adoption"
    assert result["policies"]["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert result["policies"]["raw_origin_policy"] == "second_brain_does_not_replace_time_origin"


def test_second_brain_requires_need_and_sources():
    from second_brain import build_second_brain_dry_run

    result = build_second_brain_dry_run({})

    assert result["ok"] is False
    assert result["candidate_id"] == ""
    assert "need_or_question" in result["missing"]
    assert "sources" in result["missing"]
    assert result["write_performed"] is False
