import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_zhiyi_slash_command_is_language_neutral_entry():
    intent = importlib.import_module("zhiyi_entry_intent")

    result = intent.normalize_zhiyi_entry_query("/zhiyi 这个项目现在做到哪里了")

    assert result["is_zhiyi_entry"] is True
    assert result["entry_command"] == "/zhiyi"
    assert result["query"] == "这个项目现在做到哪里了"
    assert result["original_query"] == "/zhiyi 这个项目现在做到哪里了"


def test_english_memory_phrases_are_entry_requests():
    intent = importlib.import_module("zhiyi_entry_intent")

    result = intent.normalize_zhiyi_entry_query("catch me up on the release state")

    assert result["is_zhiyi_entry"] is True
    assert result["entry_language"] == "en-US"
    assert result["query"] == "catch me up on the release state"


def test_dialog_router_accepts_commands_and_english_memory_intent():
    router = importlib.import_module("dialog_intent_router")

    assert router.classify_intent("/zhiyi 继续这个项目") == router.LEVEL_MEMORY_QUERY
    assert router.classify_intent("/memory continue this project") == router.LEVEL_MEMORY_QUERY
    assert router.classify_intent("pick up where we left off") == router.LEVEL_MEMORY_QUERY
    assert router.classify_intent("do not use memory for this new topic") == router.LEVEL_NORMAL_QA


def test_fine_dialog_router_routes_natural_language_correction_to_errata_candidate():
    router = importlib.import_module("dialog_intent_router")

    result = router.classify_fine_intent("这条记录不对，不是我的原话")

    assert result["route"] == "correction_errata"
    assert result["level"] == router.LEVEL_MEMORY_QUERY
    assert result["action"] == "zhiyi_errata_candidate"
    assert result["target_shelf"] == "errata"
    assert result["correction_candidate_suggested"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False


def test_fine_dialog_router_separates_lookup_shelves_and_no_memory():
    router = importlib.import_module("dialog_intent_router")

    cases = [
        ("查一下这句话的原话出处", "source_lookup", "raw"),
        ("查知意里我对复杂设置的偏好", "zhiyi_lookup", "zhiyi"),
        ("查行策里下一刀怎么做", "xingce_lookup", "xingce"),
        ("查工具书里 9860 端口的平台事实", "toolbook_lookup", "toolbook"),
        ("benchmark 三组对比现在怎么跑", "benchmark_replay", "evaluation"),
        ("这个 GitHub repo 可能对Time Library有用，是个新方向", "method_signal", "incubator"),
        ("查一下 ExampleTool 这件事的最新可信判断", "state_ledger", "evaluation"),
        ("把这条纠错做成一个上下文预算最小单元", "context_unit", "incubator"),
        ("/zhiyi 继续这个项目", "memory_recall", "zhiyi"),
    ]

    for message, route, shelf in cases:
        result = router.classify_fine_intent(message)
        assert result["route"] == route
        assert result["target_shelf"] == shelf
        assert result["read_only"] is True
        assert result["write_performed"] is False

    no_memory = router.classify_fine_intent("do not use memory for this new topic")
    assert no_memory["route"] == "no_memory"
    assert no_memory["level"] == router.LEVEL_NORMAL_QA
    assert no_memory["action"] == "pass_through"
