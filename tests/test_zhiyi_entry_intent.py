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
