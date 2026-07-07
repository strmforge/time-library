import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_state_ledger_returns_latest_trusted_judgment_and_keeps_old_states_visible():
    ledger = importlib.import_module("zhixing_state_ledger")

    result = ledger.build_state_ledger_snapshot({
        "topic": "ExampleTool naming",
        "records": [
            {
                "library_id": "ZX-ZHIYI-OLD",
                "title": "Windows native OpenClaw is called ExampleTool",
                "status": "superseded",
                "updated_at": "2026-05-29T10:00:00Z",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/old.jsonl"},
                "verbatim_excerpt": "Windows 原生 OpenClaw 你称为 ExampleTool",
            },
            {
                "library_id": "ZX-ZHIYI-CURRENT",
                "title": "Tencent OpenClaw is called ExampleTool",
                "status": "adopted",
                "updated_at": "2026-05-30T10:00:00Z",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/current.jsonl"},
                "verbatim_excerpt": "腾讯那个我会称呼 ExampleTool，不会和 openclaw 混说",
                "supersedes": ["ZX-ZHIYI-OLD"],
            },
            {
                "library_id": "ZX-ZHIYI-CONFLICT",
                "title": "Conflicting note",
                "status": "candidate",
                "updated_at": "2026-05-30T11:00:00Z",
                "source_refs": {"source_system": "codex", "source_path": "raw/codex/conflict.jsonl"},
                "verbatim_excerpt": "这条记录就不对了",
                "conflicts_with": ["ZX-ZHIYI-OLD"],
            },
        ],
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["latest_trusted_judgment"]["record_id"] == "ZX-ZHIYI-CURRENT"
    assert result["latest_trusted_judgment"]["status_category"] == "current"
    assert result["state_ledger"]["superseded"][0]["record_id"] == "ZX-ZHIYI-OLD"
    assert result["state_ledger"]["conflicting"][0]["record_id"] == "ZX-ZHIYI-CONFLICT"
    assert result["status_counts"]["current"] == 1
    assert result["status_counts"]["superseded"] == 1
    assert result["status_counts"]["conflicting"] == 1
    assert result["raw_authority"] is True
    assert result["write_flags"]["raw_write_performed"] is False
    assert "conflicting_records_visible_for_errata_review" in result["warnings"]


def test_state_ledger_plan_declares_temporal_index_navigation_only():
    ledger = importlib.import_module("zhixing_state_ledger")

    plan = ledger.get_state_ledger_plan()

    assert plan["ok"] is True
    assert plan["read_only"] is True
    assert plan["write_performed"] is False
    assert plan["endpoint"] == "/api/v1/zhixing/state-ledger/dry-run"
    assert plan["temporal_index_role"] == "navigation_only_not_authority"
    assert "source_refs" in plan["required_for_promotion_later"]
    assert "treat_temporal_index_as_truth" in plan["forbidden_by_default"]


def test_state_ledger_no_records_is_explicit_not_error():
    ledger = importlib.import_module("zhixing_state_ledger")

    result = ledger.build_state_ledger_snapshot({"topic": "empty"})

    assert result["ok"] is True
    assert result["latest_trusted_judgment"] is None
    assert result["latest_trusted_judgment_found"] is False
    assert "no_records_supplied" in result["warnings"]
