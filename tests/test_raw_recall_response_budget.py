from src.raw_recall_response_budget import compact_recall_payload


def test_compact_payload_preserves_source_coordinates_without_raw_excerpt():
    payload = {
        "ok": True,
        "matched_count": 1,
        "items": [
            {
                "library_id": "ZX-RAW-EXAMPLE",
                "summary": "source-backed item",
                "native_artifact_format": "jsonl",
                "raw_archive_layout": "computer_first",
                "source_path": "/tmp/source.jsonl",
                "msg_ids": ["turn-1"],
                "byte_offsets": [12, 48],
                "line_offsets": [3, 4],
                "artifact_type": "codex_jsonl",
                "raw_mapping_mode": "source_ref_byte_offsets",
                "primary_recall_backend": "vector",
                "primary_recall_mode": "semantic_locator",
                "raw_excerpt": "original text should stay out of compact mode",
            }
        ],
    }

    compact = compact_recall_payload(payload)
    item = compact["items"][0]

    assert item["native_artifact_format"] == "jsonl"
    assert item["raw_archive_layout"] == "computer_first"
    assert item["byte_offsets"] == [12, 48]
    assert item["line_offsets"] == [3, 4]
    assert item["artifact_type"] == "codex_jsonl"
    assert item["raw_mapping_mode"] == "source_ref_byte_offsets"
    assert item["primary_recall_backend"] == "vector"
    assert item["primary_recall_mode"] == "semantic_locator"
    assert "raw_excerpt" not in item
    assert compact["response_budget"]["raw_excerpt_available"] is True
    assert compact["response_budget"]["raw_excerpt_returned"] is False


def test_compact_payload_preserves_recall_and_freshness_telemetry_only_when_present():
    payload = {
        "ok": True,
        "matched_count": 1,
        "bm25_applied": True,
        "bm25_index_status": {"status": "ready", "doc_count": 7},
        "fts5_applied": True,
        "fts5_status": {"enabled": True},
        "fts5_rank_reason": "fts5_bm25",
        "memory_cache_status": "refresh_pending",
        "refresh_status": "pending",
        "refresh_pending": True,
        "freshness_boundary": "bounded_recent_delta",
        "last_refresh_started_at": "2026-07-01T12:00:00Z",
        "last_refresh_completed_at": "2026-07-01T12:00:01Z",
        "last_refresh_duration_seconds": 1.25,
        "refresh_trigger_count": 2,
        "recent_delta_applied": True,
        "recent_delta_status": {"applied": True},
        "recent_delta_doc_count": 3,
        "recent_delta_bounded": True,
        "recent_delta_full_refresh_waited": False,
        "freshness_fast_path": "recent_delta",
        "default_vector_freshness_covered": False,
        "rrf_applied": True,
        "recall_methods_used": ["keyword", "bm25", "fts5", "rrf"],
        "primary_recall_backend": "hybrid",
        "primary_recall_modes": ["keyword", "vector"],
        "primary_recall_elapsed_seconds": 0.03,
        "primary_recall_items_count": 4,
        "vector_runtime_status": {"ok": False, "status": "degraded"},
        "vector_degraded": True,
        "vector_degradation_issues": ["missing_index"],
        "recall_transport": "inline_fallback_p3_service_unavailable",
        "vector_fallback_applied": True,
        "vector_fallback_backend": "FTS5+BM25",
        "raw_gateway_timing": {"elapsed_seconds": 0.04},
        "items": [{"library_id": "ZX-RAW-TELEMETRY"}],
    }

    compact = compact_recall_payload(payload)

    for key in (
        "bm25_applied",
        "bm25_index_status",
        "fts5_applied",
        "fts5_status",
        "fts5_rank_reason",
        "memory_cache_status",
        "refresh_status",
        "refresh_pending",
        "freshness_boundary",
        "last_refresh_started_at",
        "last_refresh_completed_at",
        "last_refresh_duration_seconds",
        "refresh_trigger_count",
        "recent_delta_applied",
        "recent_delta_status",
        "recent_delta_doc_count",
        "recent_delta_bounded",
        "recent_delta_full_refresh_waited",
        "freshness_fast_path",
        "default_vector_freshness_covered",
        "rrf_applied",
        "recall_methods_used",
        "primary_recall_backend",
        "primary_recall_modes",
        "primary_recall_elapsed_seconds",
        "primary_recall_items_count",
        "vector_runtime_status",
        "vector_degraded",
        "vector_degradation_issues",
        "recall_transport",
        "vector_fallback_applied",
        "vector_fallback_backend",
        "raw_gateway_timing",
    ):
        assert compact[key] == payload[key]


def test_compact_payload_omits_empty_telemetry_values():
    compact = compact_recall_payload({
        "ok": True,
        "fts5_status": {},
        "refresh_status": "",
        "vector_degradation_issues": [],
        "raw_gateway_timing": None,
        "items": [],
    })

    assert "fts5_status" not in compact
    assert "refresh_status" not in compact
    assert "vector_degradation_issues" not in compact
    assert "raw_gateway_timing" not in compact


def test_raw_budget_still_returns_full_payload_and_marks_raw_excerpt_returned():
    payload = {
        "items": [
            {
                "library_id": "ZX-RAW-FULL",
                "raw_excerpt": "full raw excerpt",
                "byte_offsets": [0, 16],
            }
        ],
        "expensive_field": {"kept": True},
    }

    full = compact_recall_payload(payload, response_budget_mode="raw")

    assert full["expensive_field"] == {"kept": True}
    assert full["items"][0]["raw_excerpt"] == "full raw excerpt"
    assert full["response_budget"]["mode"] == "raw"
    assert full["response_budget"]["raw_excerpt_returned"] is True
