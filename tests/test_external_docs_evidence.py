import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_external_docs_contract_is_neutral_and_read_only():
    docs_evidence = importlib.import_module("external_docs_evidence")

    contract = docs_evidence.get_external_docs_evidence_contract()

    assert contract["ok"] is True
    assert contract["contract"] == "zhixing_external_docs_evidence.v1"
    assert contract["read_only"] is True
    assert contract["write_performed"] is False
    assert contract["candidate_type"] == "external_docs_evidence_plan"
    assert contract["raw_source_root"] == "raw/external_docs/"
    assert contract["not_a_memory_source"] is True
    assert contract["third_party_tool_dependency"] is False
    assert contract["network_call_performed"] is False
    assert "brand_named_provider_dependency" in contract["forbidden_by_default"]
    assert "store_summary_as_raw" in contract["forbidden_by_default"]


def test_external_docs_dry_run_recommends_docs_for_versioned_dependency_question():
    docs_evidence = importlib.import_module("external_docs_evidence")

    result = docs_evidence.build_external_docs_evidence_dry_run({
        "question": "After upgrading fastapi 0.115, the SDK import fails. Which official docs should be checked first?",
        "project": "api-service",
        "version": "0.115",
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["network_call_performed"] is False
    assert result["raw_write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["contract"] == "zhixing_external_docs_evidence.v1"
    assert result["external_docs_recommended"] is True

    candidate = result["candidate"]
    assert candidate["candidate_type"] == "external_docs_evidence_plan"
    assert candidate["external_docs_recommended"] is True
    assert candidate["evidence_scope"] == "toolbook"
    assert candidate["library_shelf"] == "toolbook"
    assert candidate["not_a_memory_source"] is True
    assert candidate["raw_target"].startswith("raw/external_docs/")
    assert candidate["raw_target"].endswith(".jsonl")
    assert candidate["source_ref_template"]["source_system"] == "external_docs"
    assert candidate["ttl_policy"]["default_hours"] == 168
    assert candidate["recommended_action"] == "collect_external_docs_evidence_before_answer"
    assert {item["source_type"] for item in candidate["query_plan"]} == {
        "official_docs",
        "release_notes",
        "migration_guides",
        "local_docs_cache",
        "user_configured_docs_provider",
    }
    for item in candidate["query_plan"]:
        assert item["must_capture_source_text"] is True
        assert item["must_record_source_ref"] is True
        assert item["network_call_allowed_in_dry_run"] is False


def test_external_docs_dry_run_can_decline_when_no_doc_drift_signal():
    docs_evidence = importlib.import_module("external_docs_evidence")

    result = docs_evidence.build_external_docs_evidence_dry_run({
        "query": "Summarize the local meeting notes for me.",
    })

    assert result["ok"] is True
    assert result["candidate_created"] is True
    assert result["external_docs_recommended"] is False
    assert result["candidate"]["review_required"] is False
    assert result["candidate"]["recommended_action"] == "answer_without_external_docs_evidence_unless_user_requests"
    assert result["candidate"]["network_call_performed"] is False
    assert result["candidate"]["toolbook_write_performed"] is False


def test_external_docs_dry_run_does_not_infer_stopword_as_dependency():
    docs_evidence = importlib.import_module("external_docs_evidence")

    result = docs_evidence.build_external_docs_evidence_dry_run({
        "query": "SDK upgrade error after version 2.4, check official docs first.",
        "version": "2.4",
    })

    assert result["ok"] is True
    assert result["external_docs_recommended"] is True
    assert result["candidate"]["dependency"] == ""
    assert "dependency=after" not in result["candidate"]["reason"]
    assert "after 2.4 official docs" not in json.dumps(result["candidate"]["query_plan"], ensure_ascii=False)


def test_external_docs_dry_run_requires_a_question():
    docs_evidence = importlib.import_module("external_docs_evidence")

    result = docs_evidence.build_external_docs_evidence_dry_run({})

    assert result["ok"] is False
    assert result["candidate_created"] is False
    assert result["candidate"] is None
    assert result["write_performed"] is False
    assert result["network_call_performed"] is False
    assert "query_or_question" in result["missing"]
    assert result["error"] == "invalid_external_docs_evidence_plan"
