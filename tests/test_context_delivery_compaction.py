import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_context_delivery_compaction_contract_is_delivery_only():
    compaction = importlib.import_module("context_delivery_compaction")

    contract = compaction.get_context_delivery_compaction_contract()

    assert contract["ok"] is True
    assert contract["contract"] == "zhixing_context_delivery_compaction.v1"
    assert contract["read_only"] is True
    assert contract["write_performed"] is False
    assert contract["candidate_type"] == "context_delivery_compaction_plan"
    assert contract["context_package_role"] == "delivery_optimization_only"
    assert contract["raw_authority_preserved"] is True
    assert contract["not_a_memory_source"] is True
    assert contract["third_party_tool_dependency"] is False
    assert contract["network_call_performed"] is False
    assert contract["cache_write_performed"] is False
    assert "compress_user_intent" in contract["forbidden_by_default"]
    assert "store_summary_as_raw" in contract["forbidden_by_default"]
    assert "install_platform_proxy" in contract["forbidden_by_default"]


def test_context_delivery_compaction_recommends_log_compaction_with_source_refs():
    compaction = importlib.import_module("context_delivery_compaction")
    log_lines = "\n".join(
        f"2026-06-08T00:00:{i:02d} INFO build step {i} completed"
        for i in range(80)
    )
    log_lines += "\n2026-06-08T00:02:00 FATAL linker failed: missing symbol yifanchen_raw_guard\n"
    log_lines += "\n".join(
        f"2026-06-08T00:02:{i:02d} ERROR traceback frame {i}"
        for i in range(80)
    )

    result = compaction.build_context_delivery_compaction_dry_run({
        "content": log_lines,
        "source_refs": {
            "source_system": "codex",
            "source_path": "raw/codex/build-log.jsonl",
        },
        "max_tokens": 300,
        "target_tokens": 160,
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert result["network_call_performed"] is False
    assert result["cache_write_performed"] is False
    assert result["raw_write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["contract"] == "zhixing_context_delivery_compaction.v1"
    assert result["compaction_recommended"] is True

    candidate = result["candidate"]
    assert candidate["candidate_type"] == "context_delivery_compaction_plan"
    assert candidate["content_profile"]["content_type"] == "log"
    assert candidate["content_profile"]["strategy"] == "pattern_cluster_keep_errors_tail_and_stack"
    assert candidate["recommended_action"] == "compact_for_delivery_with_deferred_retrieval"
    assert candidate["reversibility"]["ready"] is True
    assert candidate["reversibility"]["retrieval_anchor"] == "source_refs_or_raw_refs"
    assert candidate["source_refs_count"] == 1
    assert candidate["preservation_policy"]["raw_authority_preserved"] is True
    assert candidate["preservation_policy"]["summary_may_replace_raw"] is False
    assert candidate["preservation_policy"]["raw_record_mutation_allowed"] is False
    assert candidate["third_party_tool_dependency"] is False
    assert candidate["activation_allowed"] is False
    assert candidate["install_allowed"] is False


def test_context_delivery_compaction_requires_source_refs_for_reversible_drop():
    compaction = importlib.import_module("context_delivery_compaction")
    long_text = "\n".join(f"ERROR repeated failure line {i}" for i in range(240))

    result = compaction.build_context_delivery_compaction_dry_run({
        "content": long_text,
        "max_tokens": 200,
        "target_tokens": 100,
    })

    assert result["ok"] is True
    assert result["compaction_recommended"] is True
    candidate = result["candidate"]
    assert candidate["recommended_action"] == "capture_source_refs_before_compaction"
    assert candidate["reversibility"]["ready"] is False
    assert candidate["source_refs_count"] == 0
    assert candidate["raw_write_performed"] is False


def test_context_delivery_compaction_keeps_code_pass_through_by_default():
    compaction = importlib.import_module("context_delivery_compaction")
    code = "\n".join(
        [
            "def build_context_package(raw_refs):",
            "    if not raw_refs:",
            "        raise ValueError('source refs required')",
            "    return {'source_refs': raw_refs}",
        ]
        * 80
    )

    result = compaction.build_context_delivery_compaction_dry_run({
        "content": code,
        "source_refs": {"source_system": "repo", "source_path": "src/example.py"},
        "max_tokens": 200,
        "target_tokens": 100,
    })

    assert result["ok"] is True
    candidate = result["candidate"]
    assert candidate["content_profile"]["content_type"] == "code"
    assert candidate["compaction_recommended"] is False
    assert candidate["recommended_action"] == "pass_through_code_unless_explicit_compaction_enabled"
    assert candidate["preservation_policy"]["raw_record_mutation_allowed"] is False


def test_context_delivery_compaction_preserves_user_messages():
    compaction = importlib.import_module("context_delivery_compaction")
    result = compaction.build_context_delivery_compaction_dry_run({
        "messages": [
            {"role": "system", "content": "Use source refs."},
            {"role": "user", "content": "这是我的原话，不要压缩成别的意思。"},
            {"role": "tool", "content": "\n".join(f"INFO tool output {i}" for i in range(260))},
        ],
        "source_refs": {"source_system": "codex", "source_path": "raw/codex/session.jsonl"},
        "max_tokens": 200,
        "target_tokens": 100,
    })

    assert result["ok"] is True
    candidate = result["candidate"]
    assert candidate["preservation_policy"]["has_user_messages"] is True
    assert candidate["preservation_policy"]["preserve_user_messages"] is True
    assert candidate["preservation_policy"]["user_message_compaction_allowed"] is False
    assert candidate["preservation_policy"]["system_instruction_compaction_allowed"] is False


def test_context_delivery_compaction_requires_content_or_messages():
    compaction = importlib.import_module("context_delivery_compaction")

    result = compaction.build_context_delivery_compaction_dry_run({})

    assert result["ok"] is False
    assert result["candidate_created"] is False
    assert result["candidate"] is None
    assert result["write_performed"] is False
    assert "content_or_messages" in result["missing"]
    assert result["error"] == "invalid_context_delivery_compaction_plan"
