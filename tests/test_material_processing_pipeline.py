import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_material_processing_contract_is_read_only_and_neutral():
    from material_processing_pipeline import get_material_processing_pipeline_contract

    contract = get_material_processing_pipeline_contract()

    assert contract["ok"] is True
    assert contract["contract"] == "zhixing_material_processing_pipeline.v1"
    assert contract["zh_name"] == "资料处理流水线"
    assert contract["read_only"] is True
    assert contract["write_performed"] is False
    assert contract["third_party_tool_dependency"] is False
    assert contract["raw_authority_preserved"] is True
    assert "full_text_read_before_metadata_screening" in contract["forbidden_by_default"]
    assert "unbounded_parallel_review" in contract["forbidden_by_default"]


def test_material_processing_pipeline_screens_metadata_before_full_text():
    from material_processing_pipeline import build_material_processing_pipeline_dry_run

    result = build_material_processing_pipeline_dry_run({
        "need": "整理 Codex 大会话记录守护和 raw 起源证据",
        "batch_size": 2,
        "wip_limit": 1,
        "sample_rate": 0.25,
        "sources": [
            {
                "title": "Codex raw origin guardian report",
                "path": "/notes/codex-raw-origin.md",
                "summary": "记录守护、raw 起源、Codex 大会话滞后。",
                "keywords": ["Codex", "raw", "guardian"],
                "source_refs": {"source_path": "/notes/codex-raw-origin.md"},
                "priority": "high",
            },
            {
                "title": "Unrelated UI color draft",
                "path": "/notes/colors.md",
                "summary": "按钮颜色和间距。",
            },
            {
                "title": "时间长河沉积链",
                "path": "/notes/time-river-sediment.md",
                "summary": "raw 起源与知意行策沉积链。",
                "keywords": ["raw", "时间长河"],
            },
        ],
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["contract"] == "zhixing_material_processing_pipeline.v1"
    assert result["summary"]["source_count"] == 3
    assert result["summary"]["batch_count"] == 2
    assert result["summary"]["high_signal_count"] >= 1
    assert result["summary"]["main_library_candidate_count"] == result["summary"]["high_signal_count"]
    assert result["controls"]["wip_limit"] == 1
    assert result["worker_queue"][0]["active_batch_allowed"] is True
    assert all("source_id" in item for item in result["registered_sources"])
    assert all(candidate["status"] == "candidate" for candidate in result["main_library_candidates"])
    assert result["policies"]["screening_policy"] == "metadata_before_full_text"
    assert result["policies"]["review_policy"] == "small_batches_with_wip_limit"


def test_material_processing_pipeline_requires_need_and_sources():
    from material_processing_pipeline import build_material_processing_pipeline_dry_run

    result = build_material_processing_pipeline_dry_run({})

    assert result["ok"] is False
    assert result["candidate_id"] == ""
    assert "need_or_question" in result["missing"]
    assert "sources" in result["missing"]
    assert result["write_performed"] is False


def test_material_processing_pipeline_keeps_excluded_items_for_sample_check():
    from material_processing_pipeline import build_material_processing_pipeline_dry_run

    result = build_material_processing_pipeline_dry_run({
        "need": "Claude Desktop raw 采集正文路径",
        "sources": [
            {"title": "Claude Desktop projects JSONL", "path": "/raw/claude/projects.jsonl"},
            {"title": "Garden shopping list", "path": "/notes/garden.txt"},
        ],
        "sample_rate": 0.5,
    })

    assert result["ok"] is True
    assert result["sample_check"]["controller_must_record_decisions"] is True
    assert result["sample_check"]["sample_source_ids"]
    assert result["summary"]["excluded_count"] >= 1
