from src.raw_recall_explainability import build_query_payload_from_items


def _scope():
    return {
        "memory_scope": "window",
        "memory_base_scope": "window",
        "requested_source_system": "codex",
        "inferred_source_system": "",
        "cross_window_read": False,
        "cross_window_read_allowed": False,
        "cross_window_permission_explicit": False,
        "cross_window_reason_is_authorization": False,
    }


def _tiandao_context_builder(**kwargs):
    return {
        "validation": {"valid": True},
        "items_count": len(kwargs.get("items") or []),
    }


def test_query_payload_preserves_primary_recall_miss_when_fallback_returns_items():
    payload = build_query_payload_from_items(
        query="fallback only",
        consumer="codex",
        request_id="req-primary-miss",
        effective_source_system="codex",
        scope=_scope(),
        effective_window_id="window-a",
        effective_session_id="session-a",
        project_id="",
        project_root="",
        workstream_id="",
        task_id="",
        binding={},
        binding_applied_fields=[],
        active_layers_used=["current_window"],
        items=[
            {
                "library_id": "ZX-RAW-FALLBACK",
                "source_path": "/tmp/raw.jsonl",
                "raw_evidence_status": "raw_direct",
            }
        ],
        injection_boundary="explicit_window_scope",
        tiandao_context_builder=_tiandao_context_builder,
        library_manifest_payload={},
        hybrid_recall_manifest_payload={},
        raw_status_fn=lambda status: str(status or "").startswith("raw"),
        extra={
            "raw_recall_primary_items_count": 0,
            "raw_recall_primary_backend": "vector_timeout_degraded",
            "raw_fallback_stats": {
                "raw_fallback_used": True,
                "raw_fallback_status": "hit",
                "raw_fallback_scanned_files": 1,
                "raw_fallback_scanned_lines": 2,
                "raw_fallback_truncated": False,
                "raw_fallback_timed_out": False,
            },
            "raw_fallback_eligible": True,
        },
    )

    trajectory = {step["step"]: step for step in payload["raw_recall_trajectory"]}
    assert payload["matched_count"] == 1
    assert payload["raw_recall_primary_items_count"] == 0
    assert trajectory["primary_recall"]["status"] == "miss"
    assert trajectory["primary_recall"]["items_count"] == 0
    assert trajectory["primary_recall"]["backend"] == "vector_timeout_degraded"
    assert trajectory["raw_fallback"]["status"] == "hit"


def test_query_payload_defaults_primary_count_to_final_items_when_not_supplied():
    payload = build_query_payload_from_items(
        query="primary hit",
        consumer="codex",
        request_id="req-primary-hit",
        effective_source_system="codex",
        scope=_scope(),
        effective_window_id="window-a",
        effective_session_id="session-a",
        project_id="",
        project_root="",
        workstream_id="",
        task_id="",
        binding={},
        binding_applied_fields=[],
        active_layers_used=["current_window"],
        items=[
            {
                "library_id": "ZX-RAW-PRIMARY",
                "source_path": "/tmp/raw.jsonl",
                "raw_evidence_status": "raw_index",
            }
        ],
        injection_boundary="explicit_window_scope",
        tiandao_context_builder=_tiandao_context_builder,
        library_manifest_payload={},
        hybrid_recall_manifest_payload={},
        raw_status_fn=lambda status: str(status or "").startswith("raw"),
        extra={"primary_recall_backend": "hybrid"},
    )

    trajectory = {step["step"]: step for step in payload["raw_recall_trajectory"]}
    assert payload["raw_recall_primary_items_count"] == 1
    assert trajectory["primary_recall"]["status"] == "hit"
    assert trajectory["primary_recall"]["items_count"] == 1
    assert trajectory["primary_recall"]["backend"] == "hybrid"
