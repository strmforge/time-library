import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_external_method_signal_builds_review_only_candidate():
    method_signal = importlib.import_module("zhixing_method_signal")

    result = method_signal.build_method_signal_candidate({
        "title": "Tianlu feed-to-method",
        "signal": "这个 GitHub repo 可能对忆凡尘有用，是个新方向：把外部资讯变成方法候选。",
        "source_url": "https://github.com/strmforge/tianlu-skills",
        "source_refs": {
            "source_system": "github",
            "source_url": "https://github.com/strmforge/tianlu-skills",
            "commit": "f5ac7db",
        },
        "verbatim_excerpt": "The incubator is the entrance for new methods.",
        "proposed_trigger": "用户说新方向、外部仓库、可能对忆凡尘有用",
        "proposed_mechanism": "先生成 method_card_candidate，再由 Replay/Benchmark 决定是否升格。",
        "initial_scope": "Yifanchen method governance",
        "known_failure_modes": ["把外部 repo 当 authority", "直接安装 skill"],
        "verification_needed": ["dry-run candidate", "negative replay cases"],
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    candidate = result["candidate"]
    assert candidate["candidate_type"] == "external_method_signal_candidate"
    assert candidate["library_shelf"] == "incubator"
    assert candidate["source_refs"]["commit"] == "f5ac7db"
    assert candidate["verbatim_excerpt"] == "The incubator is the entrance for new methods."
    assert candidate["activation_allowed"] is False
    assert candidate["install_allowed"] is False
    assert candidate["matched_intent"]["route"] == "method_signal"
    assert "toolbook" in candidate["placement_candidates"]
    assert "xingce" in candidate["placement_candidates"]
    for key in [
        "write_performed",
        "raw_write_performed",
        "zhiyi_write_performed",
        "xingce_write_performed",
        "toolbook_write_performed",
        "errata_write_performed",
        "skill_write_performed",
        "platform_write_performed",
    ]:
        assert candidate[key] is False


def test_method_signal_requires_source_refs_and_verbatim_excerpt():
    method_signal = importlib.import_module("zhixing_method_signal")

    result = method_signal.build_method_signal_candidate({
        "signal": "新方向：外部资讯可以变成方法候选。",
    })

    assert result["ok"] is False
    assert result["candidate_created"] is False
    assert result["candidate"] is None
    assert result["write_performed"] is False
    assert "source_refs" in result["missing"]
    assert result["error"] == "invalid_method_signal_candidate"


def test_method_signal_contract_is_read_only_and_forbids_activation():
    method_signal = importlib.import_module("zhixing_method_signal")

    contract = method_signal.get_method_signal_contract()

    assert contract["ok"] is True
    assert contract["read_only"] is True
    assert contract["write_performed"] is False
    assert contract["endpoint"] == "/api/v1/zhixing/method-signals/dry-run"
    assert "signal" in contract["required_fields"]
    assert "source_refs" in contract["required_fields"]
    assert "verbatim_excerpt" in contract["required_fields"]
    assert "install_or_activate_skill" in contract["forbidden_by_default"]
