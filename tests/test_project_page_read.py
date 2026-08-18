import importlib
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


def _runtime(tmp_path: Path, monkeypatch):
    registry_path = tmp_path / "reading_area_registry.json"
    records_db = tmp_path / "records.db"
    monkeypatch.setenv("MEMCORE_READING_AREA_REGISTRY", str(registry_path))
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    runtime = importlib.import_module("src.raw_gateway_mcp_runtime")
    provider = importlib.import_module("src.p4_provider")
    return runtime, provider, registry_path


def _card(registry_path: Path, *, source_system: str, project: str, series: str):
    registry = importlib.import_module("src.reading_area_registry")
    card = registry.ensure_borrowing_card(
        source_system=source_system,
        consumer=source_system,
        canonical_window_id=f"{source_system}-window",
        session_id=f"{source_system}-session",
        path=registry_path,
    )["card"]
    registry.declare_membership(
        card_id=card["card_id"],
        reading_area="Time Library阅读区",
        projects=[project],
        series=[series],
        path=registry_path,
    )
    return card


def _projection_page(project_id: str = "project-a"):
    return {
        "contract": "time_library_reading_area_project_page.v1",
        "project_id": project_id,
        "project_name": "Project A",
        "read_only": True,
        "write_performed": False,
        "lane_count": 1,
        "visible_lane_count": 1,
        "truncated": False,
        "omitted_lane_count": 0,
        "digest_token_count": 12,
        "digest": "目录摘要，不是正文。",
        "library_id_pull_handles": ["ZX-XINGCE-1"],
        "visible_library_id_pull_handles": ["ZX-XINGCE-1"],
        "omitted_library_id_pull_handles_count": 0,
        "visible_lane_summaries": [
            {
                "agent": "future_xyz",
                "item_count": 1,
                "shelf_counts": {"xingce": 1},
                "library_ids": ["ZX-XINGCE-1"],
                "nested_secret": "BODY-SENTINEL-LANE",
            }
        ],
        "whiteboard": {
            "record_count": 1,
            "visible_record_count": 1,
            "visible_record_ids": ["WB-1"],
            "lines": ["在飞：施工 -> 进行中；[WB-1]"],
            "records": [
                {
                    "record_id": "WB-1",
                    "summary": "BODY-SENTINEL-WHITEBOARD",
                    "verbatim_excerpt": "BODY-SENTINEL-WHITEBOARD",
                    "source_refs": {"source_path": "/private/raw.jsonl"},
                }
            ],
        },
        "history": {
            "record_count": 1,
            "visible_record_count": 1,
            "visible_record_ids": ["PH-1"],
            "lines": ["历史：milestone 已记录；[PH-1]"],
            "records": [
                {
                    "record_id": "PH-1",
                    "display_line": "历史：milestone 已记录；[PH-1]",
                    "verbatim_excerpt": "BODY-SENTINEL-HISTORY",
                    "source_refs": {"source_path": "/private/raw.jsonl"},
                }
            ],
        },
    }


def test_project_page_read_requires_explicit_scope_and_card(tmp_path, monkeypatch):
    runtime, _provider, _registry_path = _runtime(tmp_path, monkeypatch)

    missing_card = runtime._project_page_read_payload({"project_id": "Project A"})
    assert missing_card["ok"] is False
    assert missing_card["error"] == "borrowing_card_identity_required"

    card = _card(
        _registry_path,
        source_system="future_xyz",
        project="Project A",
        series="Series A",
    )
    missing_scope = runtime._project_page_read_payload(
        {"borrowing_card_id": card["card_id"]}
    )
    assert missing_scope["ok"] is False
    assert missing_scope["error"] == "explicit_project_or_series_required"


def test_project_page_read_whitelist_hides_nested_records_and_preserves_unknowns(
    tmp_path, monkeypatch
):
    runtime, provider, registry_path = _runtime(tmp_path, monkeypatch)
    card = _card(
        registry_path,
        source_system="future_xyz",
        project="Project A",
        series="Series A",
    )
    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "project_pages": [_projection_page()],
        }

    monkeypatch.setattr(provider, "build_reading_area_catalog_from_candidates", fake_builder)
    result = runtime._project_page_read_payload(
        {
            "borrowing_card_id": card["card_id"],
            "source_system": "future_xyz",
            "project_id": "Project A",
            "target_tokens": 1200,
        }
    )

    assert result["ok"] is True
    assert captured["borrowing_card_id"] == card["card_id"]
    assert captured["project_ids"] == result["scope"]["effective_project_ids"]
    wire = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert "BODY-SENTINEL" not in wire
    assert '"records"' not in wire
    assert "source_refs" not in wire
    page = result["project_pages"][0]
    assert page["history"]["lines"] == ["历史：milestone 已记录；[PH-1]"]
    assert page["history"]["record_ids"] == ["PH-1"]
    assert page["project_state"] == {
        "goal": "unknown",
        "completed": "unknown",
        "remaining": "unknown",
        "next_step": "unknown",
        "evidence_status": "not_measured",
    }
    assert result["goal"] == "unknown"
    assert result["completed"] == "unknown"
    assert result["remaining"] == "unknown"
    assert result["next_step"] == "unknown"
    assert result["state_evidence_status"] == "not_measured"
    assert set(result["nonClaims"])
    assert "NonClaims" not in result
    for key in (
        "write_performed",
        "registry_write_performed",
        "platform_write_performed",
        "memory_write_performed",
        "raw_write_performed",
        "reading_area_content_write_performed",
    ):
        assert result[key] is False

    public_call = runtime.mcp_call_tool(
        "time_library_reading_area",
        {
            "action": "project_page_read",
            "borrowing_card_id": card["card_id"],
            "project_id": "Project A",
        },
    )
    assert public_call["isError"] is False
    assert public_call["structuredContent"]["mode"] == "project_page_read"


def test_project_page_read_enforces_card_scope_and_closes_page_budget(tmp_path, monkeypatch):
    runtime, provider, registry_path = _runtime(tmp_path, monkeypatch)
    card = _card(
        registry_path,
        source_system="future_xyz",
        project="Project A",
        series="Series A",
    )
    calls = []

    def fake_builder(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "project_pages": [
                _projection_page("project-a"),
                _projection_page("project-b"),
                _projection_page("project-c"),
            ],
        }

    monkeypatch.setattr(provider, "build_reading_area_catalog_from_candidates", fake_builder)
    denied = runtime._project_page_read_payload(
        {"borrowing_card_id": card["card_id"], "project_id": "Project B"}
    )
    assert denied["ok"] is False
    assert denied["error"] == "project_page_scope_not_declared"
    assert calls == []

    result = runtime._project_page_read_payload(
        {
            "borrowing_card_id": card["card_id"],
            "project_id": "Project A",
            "limit": 1,
            "target_tokens": 1200,
        }
    )
    assert result["ok"] is True
    assert result["project_page_count"] == 3
    assert result["visible_project_page_count"] == 1
    assert result["omitted_project_page_count"] == 2
    assert result["budget"]["available_page_count"] == 3
    assert result["budget"]["visible_page_count"] == 1
    assert result["budget"]["omitted_page_count"] == 2
    assert result["budget"]["closure"] is True
    assert result["budget"]["used_tokens"] <= result["budget"]["target_tokens"]


def test_project_page_read_passes_only_card_scope_intersection_to_builder(tmp_path, monkeypatch):
    runtime, provider, registry_path = _runtime(tmp_path, monkeypatch)
    card = _card(
        registry_path,
        source_system="future_xyz",
        project="Project A",
        series="Series A",
    )
    captured = {}

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "project_pages": [_projection_page("project-a")]}

    monkeypatch.setattr(provider, "build_reading_area_catalog_from_candidates", fake_builder)
    result = runtime._project_page_read_payload(
        {
            "borrowing_card_id": card["card_id"],
            "declared_project_ids": ["Project A", "Project B"],
            "declared_series_ids": ["Series A", "Series B"],
        }
    )

    assert result["ok"] is True
    assert captured["project_ids"] == result["scope"]["effective_project_ids"]
    assert captured["series_ids"] == result["scope"]["effective_series_ids"]
    assert "Project B" not in captured["project_ids"]
    assert "Series B" not in captured["series_ids"]


def test_project_page_read_over_real_mcp_http_dispatch(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime-root"
    runtime_root.mkdir()
    monkeypatch.setenv("MEMCORE_ROOT", str(runtime_root))
    runtime, provider, _registry_path = _runtime(tmp_path, monkeypatch)
    raw_gateway = importlib.import_module("src.raw_consumption_gateway")

    def fake_builder(**_kwargs):
        return {"ok": True, "project_pages": [_projection_page()]}

    monkeypatch.setattr(provider, "build_reading_area_catalog_from_candidates", fake_builder)
    source_ref = {
        "source_path": str(tmp_path / "source.jsonl"),
        "byte_offsets": {"start": 0, "end": 32},
    }

    def fake_query(**kwargs):
        return {
            "ok": True,
            "mode": "raw_recall",
            "query": str(kwargs.get("query") or ""),
            "consumer": str(kwargs.get("consumer") or ""),
            "read_only": True,
            "write_performed": False,
            "platform_write_performed": False,
            "recall_performed": True,
            "matched_count": 1,
            "source_refs_count": 1,
            "items": [
                {
                    "library_id": "ZX-HTTP-PAGE-1",
                    "summary": "HTTP project-page proof reference",
                    "source_refs": [source_ref],
                }
            ],
            "consumer_receipt": {"used_source_refs": [source_ref]},
        }

    monkeypatch.setattr(raw_gateway, "query_raw_source_refs", fake_query)

    server = ThreadingHTTPServer(("127.0.0.1", 0), raw_gateway.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/mcp?startup_catalog=deferred"

    def post(payload, session_id=""):
        headers = {"Content-Type": "application/json"}
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return (
                json.loads(response.read().decode("utf-8")),
                response.headers.get("Mcp-Session-Id", ""),
            )

    try:
        initialized, session_id = post(
            {
                "jsonrpc": "2.0",
                "id": "project-page-http-initialize",
                "method": "initialize",
                "params": {"clientInfo": {"name": "future xyz", "version": "1"}},
            }
        )
        assert initialized["result"]["serverInfo"]["name"] == "time-library"
        assert session_id

        capability, _ = post(
            {
                "jsonrpc": "2.0",
                "id": "project-page-http-capability",
                "method": "tools/call",
                "params": {
                    "name": "time_library_recall",
                    "arguments": {
                        "mode": "capability_check",
                        "consumer": "future_xyz",
                    },
                },
            },
            session_id,
        )
        assert capability["result"]["structuredContent"]["recall_performed"] is False

        proof, _ = post(
            {
                "jsonrpc": "2.0",
                "id": "project-page-http-proof",
                "method": "tools/call",
                "params": {
                    "name": "time_library_recall",
                    "arguments": {
                        "query": "HTTP project-page proof",
                        "consumer": "future_xyz",
                        "source_system": "future_xyz",
                        "memory_scope": "raw_pool",
                        "allow_cross_window_recall": True,
                        "response_budget": "compact",
                        "delivery_tracking": False,
                    },
                },
            },
            session_id,
        )
        proof_result = proof["result"]["structuredContent"]
        assert proof_result["matched_count"] == 1
        proof_library_id = proof_result["items"][0]["library_id"]

        connected, _ = post(
            {
                "jsonrpc": "2.0",
                "id": "project-page-http-connect",
                "method": "tools/call",
                "params": {
                    "name": "time_library_reading_area",
                    "arguments": {
                        "action": "self_report_connect",
                        "source_system": "future_xyz",
                        "consumer": "future_xyz",
                        "session_id": "future-http-project-page",
                        "declared_project_ids": ["Project A"],
                        "skill_surface_status": "mcp_only",
                        "config_write_authority": False,
                        "proof_library_id": proof_library_id,
                    },
                },
            },
            session_id,
        )
        connected_result = connected["result"]["structuredContent"]
        assert connected_result["self_report_verified"] is True
        verified_card_id = connected_result["borrowing_card_receipt"]["card_id"]

        response, response_session_id = post(
            {
                "jsonrpc": "2.0",
                "id": "project-page-http-call",
                "method": "tools/call",
                "params": {
                    "name": "time_library_reading_area",
                    "arguments": {
                        "action": "project_page_read",
                        "borrowing_card_id": verified_card_id,
                        "project_id": "Project A",
                    },
                },
            },
            session_id,
        )
        assert response_session_id == ""
        tool_result = response["result"]
        assert tool_result["isError"] is False
        structured = tool_result["structuredContent"]
        assert structured["mode"] == "project_page_read"
        assert structured["project_pages"][0]["history"]["lines"] == [
            "历史：milestone 已记录；[PH-1]"
        ]
        wire = json.dumps(structured, ensure_ascii=False)
        assert "BODY-SENTINEL" not in wire
        assert '"records"' not in wire
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        with runtime._MCP_SESSION_LOCK:
            runtime._MCP_SESSIONS.clear()
            runtime._MCP_SESSION_REQUEST_LOCKS.clear()
