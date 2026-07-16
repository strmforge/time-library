import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest

from src import raw_gateway_mcp, raw_gateway_mcp_runtime
from src import time_library_delivery_runtime as runtime
from tools import codex_mcp_bridge


def _result(*, status="active"):
    return {
        "ok": True,
        "mode": "library_card_borrow",
        "query": "ZX-TEST-CURRENT",
        "matched_count": 1,
        "items": [
            {
                "library_id": "ZX-TEST-CURRENT",
                "source_system": "codex",
                "summary": "source-backed test card",
            }
        ],
        "catalog_card": {
            "library_id": "ZX-TEST-CURRENT",
            "card": {
                "library_id": "ZX-TEST-CURRENT",
                "status": status,
                "source_refs": {
                    "source_system": "codex",
                    "source_path": "raw/codex/test.jsonl",
                },
            },
        },
        "consumer_receipt": {
            "used_source_refs": [
                {
                    "library_id": "ZX-TEST-CURRENT",
                    "source_system": "codex",
                    "source_path": "raw/codex/test.jsonl",
                }
            ]
        },
    }


def _ack_args(challenge_payload, **overrides):
    values = {
        "challenge_id": challenge_payload["challenge_id"],
        "challenge": challenge_payload["challenge"],
        "retrieval_id": challenge_payload["retrieval_id"],
        "platform": "codex",
        "request_id": "codex-model-tool-call-1",
        "used_source_refs": challenge_payload["selected_source_refs"],
        "response_evidence_ref": "codex-composed-response-1",
    }
    values.update(overrides)
    return values


def _verified_context(tmp_path, platform="codex"):
    normalized = str(platform).strip().lower().replace("-", "_").replace(" ", "_")
    context = {
        "transport_session_id": f"test-session:{tmp_path}:{normalized}",
        "initialized": True,
        "client_info_present": True,
        "client_name": f"{normalized} test host",
        "client_version": "1",
        "inferred_platform_hint": "unknown_mcp_client",
    }
    receipt = runtime.record_verified_host_connection(
        context,
        {
            "ok": True,
            "self_report_verified": True,
            "client_info": {"self_reported_platform": normalized},
            "real_recall_proof": {
                "library_id": "ZX-TEST-CURRENT",
                "source_refs_count": 1,
            },
            "borrowing_card_receipt": {"card_id": f"card-{normalized}"},
        },
        memcore_root=tmp_path,
    )
    assert receipt["ok"] is True
    return context


def _tracked(tmp_path, result=None, **arguments):
    args = {"consumer": "codex", "query": "source-backed test"}
    args.update(arguments)
    return runtime.instrument_recall_result(
        result or _result(),
        args,
        memcore_root=tmp_path,
        connection_context=_verified_context(tmp_path, args["consumer"]),
    )


def _acknowledge(tmp_path, args):
    return runtime.acknowledge_delivery(
        args,
        memcore_root=tmp_path,
        connection_context=_verified_context(tmp_path, args.get("platform") or "codex"),
    )


def test_verified_host_resume_is_single_use_under_concurrency(tmp_path):
    previous = _verified_context(tmp_path, "future_xyz")

    def rotate(index):
        return runtime.rotate_verified_host_connection_resume(
            previous,
            {"transport_session_id": f"rotated-session-{index}"},
            initialized_client_name="future_xyz test host",
            initialized_client_version="1",
            memcore_root=tmp_path,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rotate, range(2)))

    assert sum(result["ok"] is True for result in results) == 1
    rejected = next(result for result in results if result["ok"] is False)
    assert rejected["error"] == "verified_host_resume_already_consumed"


def test_any_verified_self_reported_consumer_is_trackable_and_explicit_opt_out_stays_zero_write(tmp_path):
    original = _result()

    tracked = runtime.instrument_recall_result(
        original,
        {"consumer": "generic-mcp", "query": "x"},
        memcore_root=tmp_path,
        connection_context=_verified_context(tmp_path, "generic-mcp"),
    )
    opted_out = runtime.instrument_recall_result(
        original,
        {"consumer": "codex", "query": "x", "delivery_tracking": False},
        memcore_root=tmp_path / "opt-out",
    )

    assert tracked["delivery_runtime"]["platform"] == "generic_mcp"
    assert tracked["delivery_runtime"]["challenge"]["platform"] == "generic_mcp"
    assert opted_out == original
    assert runtime.delivery_store_path(tmp_path).exists() is True
    assert runtime.delivery_store_path(tmp_path / "opt-out").exists() is False


def test_consumer_label_cannot_override_verified_host_identity_or_tracking(tmp_path):
    context = _verified_context(tmp_path, "future_xyz")

    results = [
        runtime.instrument_recall_result(
            _result(),
            {
                "consumer": consumer,
                "platform": "future_xyz",
                "query": "same verified connection",
            },
            memcore_root=tmp_path,
            connection_context=context,
        )
        for consumer in ("future_xyz", "codex", "arbitrary display label")
    ]
    consumer_only = runtime.instrument_recall_result(
        _result(),
        {"consumer": "codex", "query": "receipt remains authoritative"},
        memcore_root=tmp_path,
        connection_context=context,
    )

    assert {item["delivery_runtime"]["platform"] for item in results} == {"future_xyz"}
    assert {item["delivery_runtime"]["challenge"]["platform"] for item in results} == {"future_xyz"}
    assert all(item["delivery_runtime"]["write_boundary"]["write_performed"] for item in results)
    assert consumer_only["delivery_runtime"]["platform"] == "future_xyz"
    assert consumer_only["delivery_runtime"]["challenge"]["platform"] == "future_xyz"


def test_unverified_consumer_cannot_create_delivery_store_or_events(tmp_path):
    result = runtime.instrument_recall_result(
        _result(),
        {"consumer": "never_self_reported_xyz", "query": "x"},
        memcore_root=tmp_path,
    )

    assert result["delivery_runtime"]["error"] == "verified_host_connection_required"
    assert result["delivery_runtime"]["write_boundary"]["write_performed"] is False
    assert runtime.delivery_store_path(tmp_path).exists() is False


def test_delivery_status_accepts_an_unlisted_self_reported_client(tmp_path):
    tracked = _tracked(tmp_path, consumer="unlisted_host")
    challenge = tracked["delivery_runtime"]["challenge"]
    acknowledged = _acknowledge(tmp_path, _ack_args(challenge, platform="unlisted_host"))

    status = runtime.query_delivery_status(memcore_root=tmp_path, platform="unlisted_host")

    assert acknowledged["ok"] is True
    assert status["ok"] is True
    assert status["platform"] == "unlisted_host"
    assert status["stages"]["used"]["state"] == "observed"


def test_positive_recall_keeps_item_order_and_persists_selected_unknown_prefix(tmp_path):
    original = _result()
    result = _tracked(tmp_path, original)
    trace = result["delivery_runtime"]

    assert result["items"] == original["items"]
    assert result["read_only"] is False
    assert result["source_memory_read_only"] is True
    assert result["raw_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert trace["latest_proven_stage"] == "selected"
    assert trace["unknown_for_stage"] == ["delivered"]
    assert trace["challenge"]["ack_tool"] == "time_library_delivery_ack"

    status = runtime.query_delivery_status(memcore_root=tmp_path, platform="codex")
    assert status["stages"]["selected"]["state"] == "observed"
    assert status["stages"]["delivered"]["state"] == "unknown"
    assert status["stages"]["used"]["state"] == "not_measured"


def test_valid_host_model_ack_advances_used_and_keeps_helped_unknown(tmp_path):
    tracked = _tracked(tmp_path)
    challenge = tracked["delivery_runtime"]["challenge"]

    result = _acknowledge(tmp_path, _ack_args(challenge))

    assert result["ok"] is True
    assert result["latest_proven_stage"] == "used"
    assert result["unknown_for_stage"] == ["helped"]
    assert result["helped_observed"] is False
    assert result["request_body_byte_capture"] is False
    assert result["response_body_byte_capture"] is False
    assert result["evidence_authority"] == "host_self_report"
    assert result["independent_model_delivery_proven"] is False
    assert result["platform_delivery_proof_kind"] == "host_attested_append_only_chain"
    assert result["host_attested_append_only_chain_proven"] is True
    status = runtime.query_delivery_status(memcore_root=tmp_path, platform="codex")
    assert status["stages"]["delivered"]["state"] == "observed"
    assert status["stages"]["used"]["state"] == "observed"
    assert status["stages"]["helped"]["state"] == "unknown"


def test_ack_is_idempotent_after_used_is_observed(tmp_path):
    tracked = _tracked(tmp_path)
    challenge = tracked["delivery_runtime"]["challenge"]
    args = _ack_args(challenge)

    first = _acknowledge(tmp_path, args)
    second = _acknowledge(tmp_path, args)

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["idempotent"] is True
    assert second["write_boundary"]["write_performed"] is False
    status = runtime.query_delivery_status(memcore_root=tmp_path, platform="codex")
    assert status["stages"]["used"]["count"] == 1


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"challenge": "wrong-token"}, "delivery_challenge_mismatch"),
        ({"platform": "hermes"}, "verified_host_identity_mismatch"),
        (
            {"used_source_refs": [{"source_system": "codex", "library_id": "ZX-NOT-SELECTED"}]},
            "used_source_refs_not_selected_for_delivery",
        ),
    ],
)
def test_invalid_ack_is_blocked_and_recorded_only_as_security_audit(tmp_path, override, error):
    tracked = _tracked(tmp_path)
    challenge = tracked["delivery_runtime"]["challenge"]

    args = _ack_args(challenge, **override)
    connection_platform = "codex" if override.get("platform") == "hermes" else args["platform"]
    result = runtime.acknowledge_delivery(
        args,
        memcore_root=tmp_path,
        connection_context=_verified_context(tmp_path, connection_platform),
    )

    assert result["ok"] is False
    assert result["error"] == error
    assert result["delivery_performed"] is False
    status = runtime.query_delivery_status(memcore_root=tmp_path)
    expected_security_events = 0 if error == "verified_host_identity_mismatch" else 1
    assert status["totals"]["security_events"] == expected_security_events
    assert status["stages"]["delivered"]["state"] == "unknown"


def test_expired_challenge_cannot_advance_the_chain(tmp_path, monkeypatch):
    initial_now = runtime._now()
    monkeypatch.setattr(runtime, "_now", lambda: initial_now)
    tracked = _tracked(tmp_path)
    challenge = tracked["delivery_runtime"]["challenge"]
    monkeypatch.setattr(
        runtime,
        "_now",
        lambda: initial_now + timedelta(seconds=runtime.CHALLENGE_TTL_SECONDS + 1),
    )

    result = _acknowledge(tmp_path, _ack_args(challenge))

    assert result["ok"] is False
    assert result["error"] == "delivery_challenge_expired"


def test_silent_policy_persists_terminal_selection_but_returns_no_memory_content(tmp_path):
    result = _tracked(tmp_path, delivery_form="silent")

    assert result["mode"] == "delivery_silent"
    assert result["items"] == []
    assert "catalog_card" not in result
    assert result["raw_excerpt_returned"] is False
    assert result["delivery_runtime"]["decision"] == "silent"
    assert result["delivery_runtime"]["challenge"] == {}
    status = runtime.query_delivery_status(memcore_root=tmp_path, platform="codex")
    assert status["stages"]["selected"]["state"] == "observed"
    assert status["stages"]["delivered"]["state"] == "not_measured"


def test_superseded_exact_borrow_is_a_real_conflict_lifecycle_negative_arm(tmp_path):
    result = _tracked(tmp_path, _result(status="superseded"))

    assert result["mode"] == "delivery_silent"
    assert result["items"] == []
    assert "lifecycle_superseded" in result["delivery_runtime"]["silent_reasons"]


def test_no_source_refs_records_insufficient_evidence_without_creating_delivery_events(tmp_path):
    result = runtime.instrument_recall_result(
        {"ok": True, "matched_count": 0, "items": []},
        {"consumer": "codex", "query": "no evidence"},
        memcore_root=tmp_path,
        connection_context=_verified_context(tmp_path),
    )

    assert result["mode"] == "delivery_silent"
    assert result["delivery_runtime"]["event_ids"] == []
    assert "source_refs_unavailable" in result["delivery_runtime"]["silent_reasons"]
    status = runtime.query_delivery_status(memcore_root=tmp_path, platform="codex")
    assert status["totals"]["events"] == 0
    assert status["totals"]["decisions"] == 1


def test_all_append_only_tables_reject_update_and_delete(tmp_path):
    tracked = _tracked(tmp_path)
    challenge = tracked["delivery_runtime"]["challenge"]
    _acknowledge(tmp_path, _ack_args(challenge, challenge="wrong"))
    previous = _verified_context(tmp_path)
    rotated = runtime.rotate_verified_host_connection_resume(
        previous,
        {"transport_session_id": "append-only-rotated-session"},
        initialized_client_name="codex test host",
        initialized_client_version="1",
        memcore_root=tmp_path,
    )
    assert rotated["ok"] is True
    path = runtime.delivery_store_path(tmp_path)
    connection = sqlite3.connect(str(path))
    try:
        for table in (
            "delivery_events",
            "delivery_challenges",
            "delivery_decisions",
            "delivery_security_events",
            "host_connection_receipts",
            "host_connection_resume_events",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append_only"):
                connection.execute("UPDATE %s SET rowid = rowid" % table)
            with pytest.raises(sqlite3.IntegrityError, match="append_only"):
                connection.execute("DELETE FROM %s" % table)
    finally:
        connection.close()


def test_delivery_store_and_sqlite_sidecars_are_owner_only(tmp_path):
    path = runtime.delivery_store_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    path.chmod(0o644)

    _tracked(tmp_path)

    candidates = [path, Path(str(path) + "-wal"), Path(str(path) + "-shm")]
    assert path.stat().st_mode & 0o777 == 0o600
    assert all(candidate.stat().st_mode & 0o777 == 0o600 for candidate in candidates if candidate.exists())


def test_five_cell_status_requires_real_silent_ack_visibility_and_security_evidence(tmp_path):
    tracked = _tracked(tmp_path)
    challenge = tracked["delivery_runtime"]["challenge"]
    assert _acknowledge(tmp_path, _ack_args(challenge))["ok"] is True
    _tracked(tmp_path, delivery_form="silent")
    second = _tracked(tmp_path)
    second_challenge = second["delivery_runtime"]["challenge"]
    assert _acknowledge(tmp_path, _ack_args(second_challenge, challenge="wrong"))["ok"] is False

    status = runtime.query_delivery_status(memcore_root=tmp_path, platform="codex")

    assert status["definition_of_proven"]["status"] == "proven"
    assert set(status["definition_of_proven"]["cells"].values()) == {True}
    assert status["platform_delivery_proven"] is True
    assert status["evidence_authority"] == "host_self_report"
    assert status["independent_model_delivery_proven"] is False
    assert status["platform_delivery_proof_kind"] == "host_attested_append_only_chain"
    assert status["host_attested_append_only_chain_proven"] is True
    assert status["definition_of_proven"]["proof_scope"] == "host_attested_append_only_events_plus_local_receipt_projection"
    assert status["stages"]["helped"]["state"] == "unknown"
    assert status["helped_not_implied_by_used"] is True


def test_status_projection_opens_the_store_read_only(tmp_path):
    _tracked(tmp_path)
    path = runtime.delivery_store_path(tmp_path)
    before = path.stat().st_mtime_ns

    status = runtime.query_delivery_status(memcore_root=tmp_path, platform="codex")

    assert status["ok"] is True
    assert status["read_only"] is True
    assert status["write_performed"] is False
    assert path.stat().st_mtime_ns == before


def test_mcp_schema_exposes_a_separate_write_explicit_ack_tool():
    tools = raw_gateway_mcp.mcp_tools_payload(
        max_limit=20,
        max_excerpt=1000,
    )["tools"]
    by_name = {tool["name"]: tool for tool in tools}

    assert "delivery_tracking" in by_name["time_library_recall"]["inputSchema"]["properties"]
    assert "time_library_delivery_ack" in by_name
    ack = by_name["time_library_delivery_ack"]
    assert set(ack["inputSchema"]["required"]) >= {
        "challenge_id",
        "challenge",
        "used_source_refs",
        "response_evidence_ref",
    }


def test_mcp_ack_dispatch_uses_runtime_result_and_preserves_error_state(monkeypatch):
    class FakeRuntime:
        @staticmethod
        def acknowledge_delivery(arguments, **_kwargs):
            return {"ok": False, "error": "blocked", "arguments": arguments}

    monkeypatch.setattr(raw_gateway_mcp_runtime, "_delivery_runtime", lambda: FakeRuntime)

    result = raw_gateway_mcp_runtime.mcp_call_tool(
        "time_library_delivery_ack",
        {"challenge_id": "c"},
    )

    assert result["isError"] is True
    assert result["structuredContent"]["error"] == "blocked"


def test_codex_bridge_preserves_delivery_challenge_while_compacting_recall():
    payload = _result()
    payload.update(
        {
            "read_only": False,
            "source_memory_read_only": True,
            "write_performed": True,
            "derived_delivery_audit_write_performed": True,
            "delivery_runtime": {
                "ok": True,
                "platform": "codex",
                "retrieval_id": "retrieval-1",
                "latest_proven_stage": "selected",
                "unknown_for_stage": ["delivered"],
                "source_refs": [{"source_system": "codex", "library_id": "ZX-TEST-CURRENT"}],
                "challenge": {
                    "ack_required": True,
                    "ack_tool": "time_library_delivery_ack",
                    "challenge_id": "challenge-1",
                    "challenge": "one-time-token",
                    "retrieval_id": "retrieval-1",
                    "platform": "codex",
                    "selected_source_refs": [
                        {"source_system": "codex", "library_id": "ZX-TEST-CURRENT"}
                    ],
                    "expires_at": "2026-07-13T00:15:00Z",
                },
                "write_boundary": {
                    "write_performed": True,
                    "source_memory_read_only": True,
                    "raw_write_performed": False,
                    "memory_write_performed": False,
                    "platform_write_performed": False,
                    "append_only": True,
                },
            },
        }
    )

    compact = codex_mcp_bridge._compact_recall_payload(payload)

    challenge = compact["delivery_runtime"]["challenge"]
    assert challenge["challenge"] == "one-time-token"
    assert challenge["selected_source_refs"] == [
        {"source_system": "codex", "library_id": "ZX-TEST-CURRENT"}
    ]
    assert compact["source_memory_read_only"] is True
    assert compact["derived_delivery_audit_write_performed"] is True
    assert "catalog_card" not in compact


@pytest.mark.parametrize("tool_name", ["time_library_recall", "zhiyi_recall"])
def test_codex_bridge_injects_host_identity_for_current_and_legacy_recall(tool_name):
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": {"query": "current tool identity"},
        },
    }

    forwarded = codex_mcp_bridge._budget_zhiyi_request(request)

    assert forwarded["params"]["arguments"]["consumer"] == "codex"
    assert forwarded["params"]["arguments"]["memory_scope"] == "active"


def test_console_has_six_stage_runtime_projection_not_a_static_used_claim():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "web" / "console_product.html").read_text(encoding="utf-8")
    server = (root / "src" / "p6_console.py").read_text(encoding="utf-8")

    assert 'id="delivery-stage-grid"' in ui
    assert "['stored', 'retrieved', 'selected', 'delivered', 'used', 'helped']" in ui
    assert "item.state || 'not_measured'" in ui
    assert "/api/v1/delivery/status?platform=codex" in ui
    assert 'path == "/api/v1/delivery/status"' in server
    final_visual_pass = ui.split("/* Canvas visual pass 5.1:", 1)[1]
    assert """@media (max-width: 1180px) {
  .app {
    grid-template-columns: 1fr;
  }""" in final_visual_pass
