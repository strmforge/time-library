from __future__ import annotations

from src import raw_consumption_gateway as raw_gateway
from src.trusted_memory_authority_anchor import TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT


def test_raw_gateway_fast_preflight_surfaces_trusted_memory_authority_anchor(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(tmp_path / "missing-records.db"))

    result = raw_gateway.query_raw_source_refs(
        query="Trusted Memory recall_only 投影不脱敏 scope_and_queries_required",
        source_system="codex",
        canonical_window_id="window-a",
        memory_scope="window",
        fast_window_preflight=True,
        limit=5,
        excerpt_chars=420,
        consumer="codex",
    )

    assert result["ok"] is True
    assert result["fast_window_preflight"] is True
    assert result["authority_anchor_fallback_used"] is True
    assert result["authority_anchor_contract"] == TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT
    assert result["authority_anchor_scope"] == "project_boundary_files_only"
    assert result["fast_recall_path"] == "canonical_window_index+trusted_memory_authority_anchor"
    assert result["fast_window_index_status"] == "authority_anchor_fallback_hit"
    assert result["raw_fallback_status"] == "skipped_authority_anchor_fallback_hit"
    assert result["recall_performed"] is True
    assert result["source_refs_count"] >= 3
    assert result["raw_items_count"] >= 3
    assert result["library_index_projection_used"] is True
    assert result["library_index_projection_refs_count"] >= 3
    assert any(item.get("trusted_memory_authority_anchor") for item in result["items"])
    assert any("投影不脱敏" in item.get("summary", "") for item in result["items"])
    assert "ZX-AUTH-MEMORY-AUTHORITY-POLICY" in result["consumer_receipt"]["used_library_ids"]


def test_agent_work_preflight_passthrough_includes_authority_anchor_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(tmp_path / "missing-records.db"))

    result = raw_gateway._work_preflight_from_kwargs(
        {
            "query": "Trusted Memory recall_only 投影不脱敏 scope_and_queries_required",
            "source_system": "codex",
            "canonical_window_id": "window-a",
            "memory_scope": "window",
            "limit": 5,
            "excerpt_chars": 420,
            "consumer": "codex",
        }
    )

    assert result["ok"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["model_call_performed"] is False
    assert result["authority_anchor_fallback_used"] is True
    assert result["authority_anchor_contract"] == TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT
    assert result["matched_count"] >= 3
    assert result["source_refs_count"] >= 3
    assert result["raw_items_count"] >= 3
    assert result["fast_recall_path"] == "canonical_window_index+trusted_memory_authority_anchor"
    assert result["library_index_projection_refs_count"] >= 3
    assert result["evidence"]
    evidence_blob = " ".join(
        " ".join(str(term) for term in evidence.get("required_terms", []))
        + " "
        + str(evidence.get("summary", ""))
        for evidence in result["evidence"]
    )
    assert "memory_authority_policy" in evidence_blob
    assert "recall_only" in evidence_blob
    assert "投影不脱敏" in evidence_blob
    assert "scope_and_queries_required" in evidence_blob
    assert result["consumer_receipt"]["used_library_ids"]
