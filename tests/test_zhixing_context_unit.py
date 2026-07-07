import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_context_budget_unit_candidate_is_source_backed_and_review_only():
    context_unit = importlib.import_module("zhixing_context_unit")

    result = context_unit.build_context_budget_unit_candidate({
        "unit_text": "这条记录不对：腾讯那个我会称呼 ExampleTool，不是 Windows 原生 OpenClaw。",
        "source_refs": {
            "source_system": "codex",
            "source_path": "raw/codex/exampletool-correction.jsonl",
            "msg_ids": ["m-123"],
        },
        "verbatim_excerpt": "腾讯那个我会称呼 ExampleTool，不会和 openclaw 混说",
        "objective_link": "prevent future ExampleTool naming drift",
        "retrieval_trigger": ["ExampleTool", "Windows OpenClaw", "腾讯 OpenClaw"],
        "verification": ["route to errata warning before answering"],
        "max_tokens": 80,
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    candidate = result["candidate"]
    assert candidate["candidate_type"] == "context_budget_unit_candidate"
    assert candidate["unit_kind"] == "correction"
    assert candidate["context_slot"] == "errata_warning"
    assert candidate["source_refs"]["source_path"] == "raw/codex/exampletool-correction.jsonl"
    assert candidate["verbatim_excerpt"] == "腾讯那个我会称呼 ExampleTool，不会和 openclaw 混说"
    assert candidate["objective_link"] == "prevent future ExampleTool naming drift"
    assert candidate["budget"]["over_budget"] is False
    assert candidate["representation"]["summary_allowed"] is False
    for key in [
        "raw_write_performed",
        "zhiyi_write_performed",
        "xingce_write_performed",
        "toolbook_write_performed",
        "errata_write_performed",
        "skill_write_performed",
        "platform_write_performed",
    ]:
        assert candidate[key] is False


def test_context_budget_unit_requires_source_refs_excerpt_and_objective():
    context_unit = importlib.import_module("zhixing_context_unit")

    result = context_unit.build_context_budget_unit_candidate({
        "unit_text": "粒子方向：把上下文拆成可组合最小单元。",
    })

    assert result["ok"] is False
    assert result["candidate_created"] is False
    assert result["candidate"] is None
    assert result["write_performed"] is False
    assert "source_refs" in result["missing"]
    assert "objective_link" in result["missing"]
    assert result["error"] == "invalid_context_budget_unit_candidate"


def test_context_budget_unit_contract_marks_particle_wording_as_unconfirmed_alias():
    context_unit = importlib.import_module("zhixing_context_unit")

    contract = context_unit.get_context_budget_unit_contract()

    assert contract["ok"] is True
    assert contract["read_only"] is True
    assert contract["write_performed"] is False
    assert contract["candidate_type"] == "context_budget_unit_candidate"
    assert contract["endpoint"] == "/api/v1/zhixing/context-units/dry-run"
    assert "粒子/离子方向待核验" in contract["aka"]
    assert "write_platform_prompt_or_skill" in contract["forbidden_by_default"]
