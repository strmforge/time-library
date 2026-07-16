import ast
import importlib
import json
import os
import sqlite3
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _write_public_safe_catalog_candidate(memcore_root):
    source_path = memcore_root / "raw" / "public-safe" / "connection-proof.txt"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("platform-neutral public-safe connection proof\n", encoding="utf-8")
    candidate_dir = memcore_root / "output" / "xingce_work_experience" / "candidates"
    action_dir = memcore_root / "output" / "xingce_work_experience" / "actions"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    action_dir.mkdir(parents=True, exist_ok=True)
    candidate = {
        "candidate_id": "platform-neutral-public-safe-proof",
        "candidate_type": "xingce_work_experience",
        "lifecycle_status": "candidate",
        "title": "Platform-neutral public-safe connection proof",
        "work_scenario": "MCP connection verification",
        "summary": "Public-safe evidence used only by the external HTTP contract test.",
        "detail": "The host must complete initialize-bound self-report before Delivery writes.",
        "recommended_procedure": ["initialize", "self-report", "recall", "ack"],
        "verification_steps": ["inspect append-only receipt"],
        "evidence_refs": [
            {
                "source_system": "local_files",
                "source_path": str(source_path),
                "byte_offsets": {"start": 0, "end": source_path.stat().st_size},
            }
        ],
        "source_refs": [str(source_path)],
    }
    (candidate_dir / "xingce-platform-neutral-public-safe-proof-candidate.json").write_text(
        json.dumps(candidate, ensure_ascii=False),
        encoding="utf-8",
    )
    (action_dir / "platform-neutral-public-safe-proof.jsonl").write_text(
        json.dumps(
            {
                "candidate_id": candidate["candidate_id"],
                "action_status": "auto_adopted_evidence_bound",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_window_binding_identity_fixture(memcore_root, host_id):
    marker = f"WINDOW_BINDING_IDENTITY_MARKER_{host_id}"
    current_windows = {}
    for source_system, suffix in ((host_id, "verified"), ("codex", "display-label")):
        session_id = f"{source_system}-binding-session"
        window_id = f"{source_system}-binding-window"
        raw_path = (
            memcore_root
            / "memory"
            / source_system
            / "local"
            / window_id
            / f"{session_id}.jsonl"
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-07-15T00:00:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": f"{marker} {suffix}",
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        refs = {
            "source_system": source_system,
            "computer_name": "local",
            "canonical_window_id": window_id,
            "session_id": session_id,
            "source_path": str(raw_path),
            "msg_ids": [f"msg-{source_system}"],
            "artifact_type": f"{source_system}_session_jsonl",
        }
        case_path = memcore_root / "zhiyi" / "case_memory" / "case_memory.jsonl"
        case_path.parent.mkdir(parents=True, exist_ok=True)
        with case_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "exp_id": f"exp-{source_system}-binding",
                        "type": "case_memory",
                        "canonical_window_id": window_id,
                        "session_id": session_id,
                        "computer_id": "local",
                        "source_system": source_system,
                        "scope": f"window/{window_id}",
                        "summary": marker,
                        "detail": f"{marker} {suffix}",
                        "source_refs": json.dumps(refs, ensure_ascii=False),
                        "score": 0.8,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        current_windows[source_system] = {
            "source_system": source_system,
            "canonical_window_id": window_id,
            "session_id": session_id,
        }

    binding_path = memcore_root / "config" / "window_binding_registry.json"
    binding_path.write_text(
        json.dumps({"current_windows": current_windows}, ensure_ascii=False),
        encoding="utf-8",
    )
    return marker


def _post_json(url, payload, *, transport_session_id=""):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if transport_session_id:
        headers["Mcp-Session-Id"] = transport_session_id
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8")), dict(response.headers.items())


def _run_external_host_flow(
    tmp_path,
    monkeypatch,
    *,
    host_id,
    capability_arguments=None,
):
    memcore_root = tmp_path / "memcore"
    memcore_root.mkdir(parents=True, exist_ok=True)
    (memcore_root / "VERSION").write_text("2099.1.2\n", encoding="utf-8")
    config_dir = memcore_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "memcore.json").write_text(
        json.dumps({"paths": {"base": "."}}, sort_keys=True),
        encoding="utf-8",
    )
    _write_public_safe_catalog_candidate(memcore_root)
    binding_marker = _write_window_binding_identity_fixture(memcore_root, host_id)
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv("MEMCORE_ZHIYI_ROOT_OVERRIDE", str(memcore_root / "zhiyi"))
    monkeypatch.setenv("MEMCORE_XINGCE_ROOT_OVERRIDE", str(memcore_root))
    monkeypatch.setenv("MEMCORE_P3_RECALL_TRANSPORT", "inline")
    for module_name in (
        "config_loader",
        "src.config_loader",
        "src.raw_gateway_mcp_runtime",
        "src.raw_consumption_gateway",
    ):
        sys.modules.pop(module_name, None)
    gateway = importlib.import_module("src.raw_consumption_gateway")
    host_home = tmp_path / "host-home"
    host_home.mkdir(parents=True, exist_ok=True)
    host_config = host_home / "mcp.json"
    host_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "time-library": {
                        "url": "http://127.0.0.1:0/mcp?startup_catalog=deferred"
                    }
                }
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    host_config_before = host_config.read_bytes()

    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    plain_endpoint = f"http://127.0.0.1:{server.server_port}/mcp"
    endpoint = f"http://127.0.0.1:{server.server_port}/mcp?startup_catalog=deferred"
    try:
        plain_initialized, plain_headers = _post_json(
            plain_endpoint,
            {
                "jsonrpc": "2.0",
                "id": "plain-initialize",
                "method": "initialize",
                "params": {"clientInfo": {"name": f"{host_id}-plain", "version": "1"}},
            },
        )
        assert plain_headers.get("Mcp-Session-Id")
        assert plain_initialized["result"]["startupCatalog"]["catalog"] == []
        assert plain_initialized["result"]["startupCatalog"]["catalog_entry_count"] == 0
        assert plain_initialized["result"]["startupCatalog"]["private_catalog_text_delivered"] is False
        assert plain_initialized["result"]["startupCatalogDeliveryReceipt"]["passive_delivery"] is False

        initialized, response_headers = _post_json(
            endpoint,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": host_id, "version": "1"}},
            },
        )
        transport_session_id = response_headers.get("Mcp-Session-Id")
        assert transport_session_id
        assert initialized["result"]["startupCatalog"]["catalog"] == []

        listed, _ = _post_json(
            endpoint,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            transport_session_id=transport_session_id,
        )
        ack_tool = next(
            tool
            for tool in listed["result"]["tools"]
            if tool["name"] == "time_library_delivery_ack"
        )
        reading_area_tool = next(
            tool
            for tool in listed["result"]["tools"]
            if tool["name"] == "time_library_reading_area"
        )
        assert "enum" not in ack_tool["inputSchema"]["properties"]["platform"]
        proof_description = reading_area_tool["inputSchema"]["properties"][
            "proof_library_id"
        ]["description"]
        assert "prior user-authorized real recall" in proof_description
        assert "Direct catalog-card/library_id borrowing cannot establish" in proof_description
        assert "Legacy catalog-card proof remains compatible" not in proof_description
        assert (
            "Direct catalog-card/library_id borrowing is not connection proof"
            in reading_area_tool["description"]
        )

        capability_request_arguments = {
            "query": "capability check",
            "consumer": host_id,
            **(capability_arguments or {"mode": "capability_check"}),
        }
        capability, _ = _post_json(
            endpoint,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "time_library_recall",
                    "arguments": capability_request_arguments,
                },
            },
            transport_session_id=transport_session_id,
        )
        assert capability["result"]["structuredContent"]["recall_performed"] is False
        capability_state = gateway._mcp_transport_session(transport_session_id)
        assert capability_state["capability_check_observed_at_epoch"] > 0
        assert "real_recall_proofs" not in capability_state

        first_authorized_recall, _ = _post_json(
            endpoint,
            {
                "jsonrpc": "2.0",
                "id": "first-authorized-recall",
                "method": "tools/call",
                "params": {
                    "name": "time_library_recall",
                    "arguments": {
                        "query": binding_marker,
                        "consumer": host_id,
                        "source_system": "codex",
                        "canonical_window_id": "codex-binding-window",
                        "session_id": "codex-binding-session",
                        "memory_scope": "window",
                        "limit": 3,
                    },
                },
            },
            transport_session_id=transport_session_id,
        )
        first_recall = first_authorized_recall["result"]["structuredContent"]
        assert first_recall["matched_count"] >= 1, first_recall
        assert first_recall["raw_excerpt_returned"] is False
        assert first_recall["delivery_runtime"]["error"] == "verified_host_connection_required"
        assert not (memcore_root / "runtime" / "delivery-events.sqlite3").exists()
        proof_item = first_recall["items"][0]
        proof_library_id = proof_item["library_id"]
        session_state = gateway._mcp_transport_session(transport_session_id)
        session_proof = session_state["real_recall_proofs"][proof_library_id]
        assert session_proof["source_refs_count"] >= 1
        assert session_proof["recall_source_system_filter"] == "codex"
        assert binding_marker not in json.dumps(
            session_state["real_recall_proofs"],
            ensure_ascii=False,
        )

        connected, _ = _post_json(
            endpoint,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "time_library_reading_area",
                    "arguments": {
                        "action": "self_report_connect",
                        "source_system": host_id,
                        "consumer": host_id,
                        "session_id": f"{host_id}-binding-session",
                        "declared_project_ids": ["Time Library"],
                        "skill_surface_status": "custom_instruction_installed",
                        "config_write_authority": False,
                        "proof_library_id": proof_library_id,
                    },
                },
            },
            transport_session_id=transport_session_id,
        )
        connection = connected["result"]["structuredContent"]
        assert connection["self_report_verified"] is True, json.dumps(
            {
                "registration_blockers": connection.get("registration_blockers"),
                "real_recall_proof": connection.get("real_recall_proof"),
            },
            ensure_ascii=False,
        )
        assert connection["connection_proof_method"] == (
            "capability_check_then_same_transport_session_real_recall"
        )
        assert connection["real_recall_proof"]["raw_excerpt_returned"] is False
        assert connection["consumer_connection_requires_native_parser"] is False
        delivery_runtime = importlib.import_module("src.time_library_delivery_runtime")
        connection_receipts = delivery_runtime.query_verified_host_connections(
            memcore_root=memcore_root,
        )
        assert connection["connection_receipt"]["platform"] == host_id
        assert connection_receipts == [
            {
                key: value
                for key, value in connection["connection_receipt"].items()
                if key != "write_performed"
            }
        ], (connection["connection_receipt"], connection_receipts)

        verified_card_id = connection["connection_receipt"]["borrowing_card_id"]
        for consumer_label in (host_id, "codex", "arbitrary display label"):
            reissued, _ = _post_json(
                endpoint,
                {
                    "jsonrpc": "2.0",
                    "id": f"card-{consumer_label}",
                    "method": "tools/call",
                    "params": {
                        "name": "time_library_reading_area",
                        "arguments": {
                            "action": "issue_borrowing_card",
                            "source_system": "spoofed_source",
                            "consumer": consumer_label,
                            "session_id": f"spoofed-{consumer_label}",
                        },
                    },
                },
                transport_session_id=transport_session_id,
            )
            reissued_content = reissued["result"]["structuredContent"]
            assert reissued_content["ok"] is True
            assert reissued_content["card_id"] == verified_card_id
            assert reissued_content["card"]["source_system"] == host_id
            assert reissued_content["identity_authority"] == "verified_host_connection_receipt"

        wrong_card, _ = _post_json(
            endpoint,
            {
                "jsonrpc": "2.0",
                "id": "wrong-card",
                "method": "tools/call",
                "params": {
                    "name": "time_library_reading_area",
                    "arguments": {
                        "action": "declare_membership",
                        "borrowing_card_id": "card:caller-controlled",
                        "declared_project_ids": ["Other Project"],
                    },
                },
            },
            transport_session_id=transport_session_id,
        )
        wrong_card_content = wrong_card["result"]["structuredContent"]
        assert wrong_card_content["ok"] is False
        assert wrong_card_content["error"] == "borrowing_card_identity_mismatch"
        reading_registry = importlib.import_module("src.reading_area_registry").load_registry()
        assert list(reading_registry["borrowing_cards"]) == [verified_card_id]

        for consumer_label in (host_id, "codex", "arbitrary display label"):
            bound_recall, _ = _post_json(
                endpoint,
                {
                    "jsonrpc": "2.0",
                    "id": f"binding-{consumer_label}",
                    "method": "tools/call",
                    "params": {
                        "name": "time_library_recall",
                        "arguments": {
                            "query": binding_marker,
                            "consumer": consumer_label,
                            "delivery_tracking": False,
                            "limit": 3,
                        },
                    },
                },
                transport_session_id=transport_session_id,
            )
            bound_content = bound_recall["result"]["structuredContent"]
            assert bound_content["consumer"] == consumer_label
            assert bound_content["current_window_binding_key"] == host_id
            assert bound_content["canonical_window_id_filter"] == f"{host_id}-binding-window"
            assert bound_content["source_system_filter"] == host_id
            assert {item["source_system"] for item in bound_content["items"]} == {host_id}

        registry = importlib.import_module("src.platform_thin_adapter_registry")
        recorded_install = registry.apply_authorized_auto_connect(
            {
                "system": host_id,
                "host_capabilities": {
                    "mcp_capability": True,
                    "skill_surface": "custom_instruction",
                    "config_write_owner": "host",
                    "startup_catalog_policy": "deferred",
                },
                "host_install_performed": True,
                "host_install_receipt": "host-configured-its-own-mcp",
                "connection_receipt_id": connection["connection_receipt"]["receipt_id"],
            },
            home=host_home,
            memcore_root=memcore_root,
        )
        assert recorded_install["ok"] is True, recorded_install
        assert recorded_install["platform_write_performed"] is False
        assert host_config.read_bytes() == host_config_before

        recalled, _ = _post_json(
            endpoint,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "time_library_recall",
                    "arguments": {
                        "query": binding_marker,
                        "consumer": host_id,
                        "source_system": "codex",
                        "canonical_window_id": "codex-binding-window",
                        "session_id": "codex-binding-session",
                        "memory_scope": "window",
                        "limit": 3,
                    },
                },
            },
            transport_session_id=transport_session_id,
        )
        recall = recalled["result"]["structuredContent"]
        assert recall["matched_count"] == 1
        challenge = recall["delivery_runtime"]["challenge"]

        def ack_payload(challenge_text, request_id):
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": "time_library_delivery_ack",
                    "arguments": {
                        "challenge_id": challenge["challenge_id"],
                        "challenge": challenge_text,
                        "retrieval_id": challenge["retrieval_id"],
                        "platform": host_id,
                        "request_id": f"{host_id}-model-request-{request_id}",
                        "used_source_refs": challenge["selected_source_refs"],
                        "response_evidence_ref": f"{host_id}-response-{request_id}",
                    },
                },
            }

        rejected, _ = _post_json(
            endpoint,
            ack_payload("wrong-challenge", 6),
            transport_session_id=transport_session_id,
        )
        assert rejected["result"]["structuredContent"]["error"] == "delivery_challenge_mismatch"
        accepted, _ = _post_json(
            endpoint,
            ack_payload(challenge["challenge"], 7),
            transport_session_id=transport_session_id,
        )
        accepted_content = accepted["result"]["structuredContent"]
        assert accepted_content["latest_proven_stage"] == "used"
        assert accepted_content["evidence_authority"] == "host_self_report"
        assert accepted_content["independent_model_delivery_proven"] is False
        assert accepted_content["platform_delivery_proof_kind"] == "host_attested_append_only_chain"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    delivery_runtime = importlib.import_module("src.time_library_delivery_runtime")
    status = delivery_runtime.query_delivery_status(
        memcore_root=memcore_root,
        platform=host_id,
    )
    assert status["stages"]["used"]["state"] == "observed"
    assert status["evidence_authority"] == "host_self_report"
    assert status["independent_model_delivery_proven"] is False
    assert status["platform_delivery_proof_kind"] == "host_attested_append_only_chain"
    assert status["totals"]["security_events"] == 1
    return status


def test_unknown_client_name_never_enters_product_source():
    forbidden = "future_xyz"
    matches = []
    for path in SRC.rglob("*.py"):
        if forbidden in path.read_text(encoding="utf-8", errors="ignore"):
            matches.append(str(path.relative_to(ROOT)))

    assert matches == []


def test_p4_borrowing_card_http_without_source_identity_fails_closed(tmp_path):
    p4_provider = importlib.import_module("src.p4_provider")
    bindings = importlib.import_module("src.window_binding_registry")
    reading_registry = importlib.import_module("src.reading_area_registry")
    window_path = tmp_path / "window_binding_registry.json"
    reading_path = tmp_path / "reading_area_registry.json"
    for source_system in ("codex", "future_host"):
        bindings.register_current_window(
            source_system=source_system,
            consumer=source_system,
            canonical_window_id=f"{source_system}-window",
            session_id=f"{source_system}-session",
            path=window_path,
        )

    server = ThreadingHTTPServer(("127.0.0.1", 0), p4_provider.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    query = urllib.parse.urlencode(
        {
            "consumer": "future display label",
            "window_registry_path": str(window_path),
            "reading_area_registry_path": str(reading_path),
        }
    )
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/reading-area/borrowing-card?{query}"
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("missing source identity must not issue a borrowing card")
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 404
            assert payload["ok"] is False
            assert payload["error"] == "source_system_required"
            assert payload["write_performed"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert reading_registry.load_registry(reading_path)["borrowing_cards"] == {}


def test_p4_membership_http_without_source_identity_fails_closed(tmp_path):
    p4_provider = importlib.import_module("src.p4_provider")
    bindings = importlib.import_module("src.window_binding_registry")
    reading_registry = importlib.import_module("src.reading_area_registry")
    window_path = tmp_path / "window_binding_registry.json"
    reading_path = tmp_path / "reading_area_registry.json"
    bindings.register_current_window(
        source_system="future_host",
        consumer="future_host",
        canonical_window_id="future-window",
        session_id="future-session",
        path=window_path,
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), p4_provider.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    body = json.dumps({
        "consumer": "future display label",
        "projects": ["Example Project A"],
        "window_registry_path": str(window_path),
        "reading_area_registry_path": str(reading_path),
    }).encode("utf-8")
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/reading-area/membership",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("missing source identity must not declare membership")
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 404
            assert payload["ok"] is False
            assert payload["error"] == "source_system_required"
            assert payload["write_performed"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert reading_registry.load_registry(reading_path)["borrowing_cards"] == {}


def test_product_source_has_no_named_platform_comparison_branches():
    platform_names = (
        "claude_code_cli",
        "openclaw",
        "hermes",
        "codex",
        "claude_desktop",
        "cursor",
        "pi",
        "kiro",
    )
    core_paths = (
        SRC / "active_memory_routing.py",
        SRC / "platform_thin_adapter_registry.py",
        SRC / "platform_delivery_liveness.py",
        SRC / "dialog_entry_proxy.py",
        SRC / "raw_consumption_gateway.py",
        SRC / "raw_gateway_mcp_runtime.py",
        SRC / "raw_recall_query.py",
        SRC / "reading_area_raw_index.py",
        SRC / "reading_area_projection.py",
        SRC / "source_system_taxonomy.py",
        SRC / "source_system_runtime_declarations.py",
        SRC / "p4_provider.py",
        SRC / "time_library_delivery_runtime.py",
        SRC / "time_library_delivery_spine.py",
        SRC / "window_binding_registry.py",
    )
    identity_names = {"system", "platform", "consumer", "source_system", "inferred_platform"}
    violations = []
    comparison_operators = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)
    for path in core_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            compared_identity_names = {
                child.id
                for child in ast.walk(node.left)
                if isinstance(child, ast.Name)
            }
            if not compared_identity_names.intersection(identity_names):
                continue
            if not any(isinstance(operator, comparison_operators) for operator in node.ops):
                continue
            compared_names = {
                child.value
                for comparator in node.comparators
                for child in ast.walk(comparator)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
            }
            forbidden_names = sorted(compared_names.intersection(platform_names))
            if forbidden_names:
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:{','.join(forbidden_names)}"
                )

    assert violations == []


def test_client_name_hint_cannot_substring_match_or_change_recall_identity():
    declarations = importlib.import_module("src.source_system_runtime_declarations")
    routing = importlib.import_module("src.active_memory_routing")
    bindings = importlib.import_module("src.window_binding_registry")

    for consumer in (
        "future_codex_xyz",
        "future-claude-wrapper",
        "my_openclaw_compatible_agent",
    ):
        assert declarations.source_system_from_consumer_name(consumer) == ""
        scope = routing.resolve_recall_scope(
            source_system="",
            consumer=consumer,
            memory_scope="active",
            canonical_window_id="shared-window",
            session_id="shared-session",
        )
        assert scope["inferred_source_system"] == ""
        assert scope["effective_source_system"] == ""
        assert scope["consumer_name_inference_used_for_routing"] is False

    assert declarations.source_system_from_consumer_name("claude code") == "claude_code_cli"
    filters, extra = declarations.recall_source_system_filters(
        effective_source_system="claude_desktop",
        session_id="session-1",
        canonical_window_id="window-1",
    )
    assert filters == ["claude_desktop"]
    assert extra == {}
    assert bindings.current_window_keys("", "future_codex_xyz") == []
    assert bindings.current_window_keys("codex", "") == ["codex"]


def test_consumer_display_label_cannot_relabel_reading_area_source_lane():
    taxonomy = importlib.import_module("src.source_system_taxonomy")

    assert taxonomy.canonical_reading_area_lane(
        "codex",
        consumer="claude_code_cli",
    ) == "codex"
    assert taxonomy.canonical_reading_area_lane(
        "",
        consumer="claude_code_cli",
    ) == "unknown"
    assert taxonomy.source_system_aliases(
        "codex",
        consumer="claude_code_cli",
    ) == []


def test_source_declarations_cannot_select_delivery_execution_or_window_identity():
    declarations = importlib.import_module("src.source_system_runtime_declarations")
    declaration_fields = set(declarations.SourceSystemRuntimeDeclaration.__dataclass_fields__)

    assert declaration_fields.isdisjoint(
        {
            "has_session_window_id",
            "delivery_flag_keys",
            "delivery_session_key_fields",
            "delivery_session_prefixes",
            "delivery_runtime_kind",
        }
    )
    source = (SRC / "dialog_entry_proxy.py").read_text(encoding="utf-8")
    for forbidden in (
        "source_system_delivery_enabled",
        "source_system_delivery_session_key",
        "source_system_delivery_runtime_kind",
        "infer_delivery_source_system",
    ):
        assert forbidden not in source


def test_delivery_dispatch_uses_explicit_runtime_capability_not_platform_name():
    proxy = importlib.import_module("src.dialog_entry_proxy")
    handler = object.__new__(proxy.DialogEntryHandler)
    calls = []

    def fake_forward(message, session_key, idempotency_key=None):
        calls.append((message, session_key, idempotency_key))
        return {
            "ok": True,
            "visible_reply_checked": True,
            "visible_reply_ok": True,
        }

    handler._forward_to_openclaw = fake_forward

    def deliver(platform, runtime_kind):
        return handler.maybe_deliver_platform_answer(
            {
                "platform_delivery": {
                    "enabled": True,
                    "authorized": True,
                    "platform": platform,
                    "delivery_runtime_kind": runtime_kind,
                    "session_key": "shared-session",
                    "idempotency_key": "shared-delivery",
                }
            },
            "/zhiyi continue",
            "ignored-transport-session",
            {
                "status": "ok",
                "chain": "F3_zhiyi_direct",
                "answer": "shared answer",
                "audit": {"zhiyi_entry": {"requested": True}},
            },
        )

    known = deliver("openclaw", "ws_rpc_forward")
    unknown = deliver("future_client", "ws_rpc_forward")
    name_only = deliver("openclaw", "")

    assert known["platform_delivery"]["executed"] is True
    assert unknown["platform_delivery"]["executed"] is True
    assert known["platform_delivery"]["delivery_ok"] is True
    assert unknown["platform_delivery"]["delivery_ok"] is True
    assert calls == [
        ("shared answer", "shared-session", "shared-delivery"),
        ("shared answer", "shared-session", "shared-delivery"),
    ]
    assert name_only["platform_delivery"]["executed"] is False
    assert name_only["platform_delivery"]["reason"] == "unsupported_delivery_runtime_kind"


def test_window_identity_normalization_is_identical_for_every_source_name():
    declarations = importlib.import_module("src.source_system_runtime_declarations")

    identities = [
        declarations.normalize_source_system_window_identity(
            source_system=source,
            session_id="shared-session",
            canonical_window_id="shared-window",
            project_id="",
        )
        for source in ("codex", "openclaw", "future_client", "")
    ]

    assert identities == [identities[0]] * len(identities)
    assert identities[0] == {
        "session_id": "shared-session",
        "canonical_window_id": "shared-session",
        "project_id": "shared-window",
        "source_refs_canonical_window_id": "shared-window",
    }
    gateway_source = (SRC / "raw_consumption_gateway.py").read_text(encoding="utf-8")
    assert "_source_system_has_session_window_id" not in gateway_source


def test_borrowing_card_without_source_identity_does_not_infer_from_consumer(tmp_path, monkeypatch):
    registry_path = tmp_path / "reading_area_registry.json"
    gateway = importlib.import_module("src.raw_consumption_gateway")
    monkeypatch.setattr(gateway, "_reading_area_registry_path_for_gateway", lambda: registry_path)
    db_path = tmp_path / "records.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "create table canonical_messages ("
            "source_system text, session_id text, canonical_window_id text, "
            "project_id text, project_root text, timestamp text, line_no integer)"
        )
        conn.executemany(
            "insert into canonical_messages values (?, ?, ?, ?, ?, ?, ?)",
            [
                ("codex", "session-1", "window-1", "project-from-codex", "/codex", "2", 2),
                ("claude_code_cli", "session-1", "window-1", "project-from-claude", "/claude", "1", 1),
            ],
        )
        for consumer in ("future_codex_xyz", "codex", "claude code"):
            registry_path.write_text(
                json.dumps(
                    {
                        "projects": {"project:one": {"id": "project:one"}},
                        "borrowing_cards": {
                            "card:unknown": {
                                "consumer": consumer,
                                "session_id": "session-1",
                                "canonical_window_id": "window-1",
                                "declared_project_ids": ["project:one"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            anchors = gateway._declared_project_session_anchors(["project:one"])
            technical, status = gateway._technical_project_anchors_from_declared_project(
                conn,
                project_id="project:one",
                project_root="",
                limit=5,
            )

            assert len(anchors) == 1
            assert anchors[0]["consumer"] == consumer
            assert anchors[0]["source_system"] == ""
            assert technical == []
            assert status == "declared_project_source_system_required"


def test_declared_cross_source_filters_require_the_same_bound_window(tmp_path, monkeypatch):
    memcore_root = tmp_path / "memcore"
    config_dir = memcore_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "window_binding_registry.json").write_text(
        json.dumps(
            {
                "current_windows": {
                    "future_source": {
                        "source_system": "future_source",
                        "canonical_window_id": "bound-window",
                        "session_id": "bound-session",
                        "metadata": {
                            "source_system_filters": ["future_source", "codex"],
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(memcore_root / "output" / "missing.db"))
    for module_name in ("src.raw_consumption_gateway", "src.raw_recall_query"):
        sys.modules.pop(module_name, None)
    gateway = importlib.import_module("src.raw_consumption_gateway")
    monkeypatch.setattr(
        gateway,
        "_load_handle_recall",
        lambda: (_ for _ in ()).throw(AssertionError("fast miss must not cold-load recall")),
    )

    result = gateway.query_raw_source_refs(
        "no indexed match",
        source_system="future_source",
        consumer="future_source",
        memory_scope="window",
        canonical_window_id="different-window",
        session_id="different-session",
        fast_window_preflight=True,
        fast_preflight_miss_policy="return_without_cold_recall",
    )

    assert result["source_system_filter"] == "future_source"
    assert "source_system_filter_aliases" not in result
    assert "source_collection_alias_applied" not in result


def test_raw_registry_never_offers_time_library_owned_platform_config_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = importlib.import_module("src.platform_thin_adapter_registry")
    runtime_profile = {
        "claude_desktop": {
            "status": "detected",
            "instances": [{"type": "config", "path": str(tmp_path / "host.json")}],
        }
    }

    result = registry.build_thin_adapter_registry(
        runtime_profile,
        home=tmp_path,
        env={},
        include_generic=False,
    )
    detected = next(item for item in result["adapters"] if item["system"] == "claude_desktop")

    assert result["default_policy"] == "observe_compatibility_then_verify_host_self_install"
    assert result["auto_connect_ready_count"] == 0
    assert result["host_self_install_required_count"] == 1
    assert result["global_guarantees"]["time_library_platform_write_supported"] is False
    assert result["global_guarantees"]["known_platform_catalog_is_not_an_admission_allowlist"] is True
    assert detected["actions"] == [
        {
            "action": "await_host_self_install_and_self_report",
            "status": "host_action_required",
            "reason": "platform_detected_without_memcore_signal",
            "requires_user_authorization": False,
            "writes_platform_config": False,
        }
    ]


def test_native_history_reader_is_not_in_generic_recall_core():
    recall_core = (SRC / "raw_recall_query.py").read_text(encoding="utf-8")
    gateway = (SRC / "raw_consumption_gateway.py").read_text(encoding="utf-8")

    assert "_query_hermes_state_db" not in recall_core
    assert "def _query_hermes_state_db" not in gateway


def test_cross_window_permission_is_explicit_and_identity_neutral():
    routing = importlib.import_module("src.active_memory_routing")

    def resolve(consumer, *, allowed):
        return routing.resolve_recall_scope(
            source_system="",
            consumer=consumer,
            memory_scope="raw_pool",
            canonical_window_id="",
            session_id="",
            allow_cross_window_recall=allowed,
            cross_window_reason="skill_generation",
        )

    hermes_without = resolve("hermes", allowed=False)
    unknown_without = resolve("future_xyz", allowed=False)
    hermes_with = resolve("hermes", allowed=True)
    unknown_with = resolve("future_xyz", allowed=True)

    assert hermes_without["cross_window_read_allowed"] is False
    assert unknown_without["cross_window_read_allowed"] is False
    assert hermes_without["missing_scope_fields"] == unknown_without["missing_scope_fields"]
    assert hermes_without["inferred_source_system"] == "hermes"
    assert unknown_without["inferred_source_system"] == ""
    assert hermes_without["effective_source_system"] == unknown_without["effective_source_system"] == ""
    assert hermes_without["consumer_name_inference_used_for_routing"] is False
    assert unknown_without["consumer_name_inference_used_for_routing"] is False
    assert hermes_with["cross_window_read_allowed"] is True
    assert unknown_with["cross_window_read_allowed"] is True
    assert hermes_with["cross_window_permission_explicit"] is True
    assert unknown_with["cross_window_permission_explicit"] is True
    assert hermes_with["cross_window_reason_is_authorization"] is False
    assert unknown_with["cross_window_reason_is_authorization"] is False


def test_fast_preflight_miss_policy_is_capability_driven_not_source_identity(tmp_path, monkeypatch):
    records_db = tmp_path / "memcore" / "output" / "records" / "missing.db"
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    for module_name in ("src.raw_consumption_gateway", "src.raw_recall_query"):
        sys.modules.pop(module_name, None)
    gateway = importlib.import_module("src.raw_consumption_gateway")
    monkeypatch.setattr(
        gateway,
        "_load_handle_recall",
        lambda: (_ for _ in ()).throw(AssertionError("fast preflight must not cold-load recall")),
    )

    results = []
    for source_system, consumer in (
        ("claude_code_cli", "claude_code_hook"),
        ("future_source", "future_xyz"),
    ):
        results.append(
            gateway.query_raw_source_refs(
                "no indexed match",
                source_system=source_system,
                consumer=consumer,
                memory_scope="active",
                canonical_window_id="shared-window",
                session_id="shared-session",
                fast_window_preflight=True,
                fast_preflight_miss_policy="return_without_cold_recall",
            )
        )

    assert {result["matched_count"] for result in results} == {0}
    assert {result["fast_preflight_miss_returned_without_cold_recall"] for result in results} == {True}
    assert {result["fast_preflight_miss_policy"] for result in results} == {"return_without_cold_recall"}
    assert {result["fast_preflight_miss_continued_to_cold_recall"] for result in results} == {False}
    assert {result["zhiyi_layer_skipped_for_fast_preflight"] for result in results} == {True}


def test_public_http_contract_accepts_unknown_client_without_product_source_change(tmp_path, monkeypatch):
    status = _run_external_host_flow(tmp_path, monkeypatch, host_id="future_xyz")
    assert status["platform"] == "future_xyz"


def test_hermes_consumer_http_flow_does_not_touch_native_history_parser(tmp_path, monkeypatch):
    hermes_paths = importlib.import_module("src.hermes_paths")
    monkeypatch.setattr(
        hermes_paths,
        "hermes_state_db_path",
        lambda: (_ for _ in ()).throw(AssertionError("native parser must not run")),
    )
    status = _run_external_host_flow(tmp_path, monkeypatch, host_id="hermes")
    assert status["platform"] == "hermes"


@pytest.mark.parametrize(
    ("capability_arguments", "host_id"),
    [
        ({"capability_check": True}, "capability_alias_host"),
        ({"no_recall": True}, "no_recall_alias_host"),
    ],
)
def test_public_http_connection_flow_accepts_capability_check_boolean_aliases(
    tmp_path,
    monkeypatch,
    capability_arguments,
    host_id,
):
    status = _run_external_host_flow(
        tmp_path,
        monkeypatch,
        host_id=host_id,
        capability_arguments=capability_arguments,
    )
    assert status["platform"] == host_id


def test_public_install_contract_is_platform_neutral_and_delays_private_recall():
    public_paths = [
        ROOT / "README.md",
        ROOT / "README.en.md",
        ROOT / "README.zh-CN.md",
        ROOT / "docs" / "wiki" / "Getting-Started.md",
        ROOT / "web" / "console_product.html",
        ROOT / "system" / "skills" / "time-library" / "SKILL.md",
    ]
    public_texts = {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in public_paths
    }

    for name, text in public_texts.items():
        assert "If this platform is Claude Code" not in text, name
        assert "如果这个平台是 Claude Code" not in text, name
        assert "only connect this platform's native delivery surface" not in text, name
        assert "只接这一个平台的原生投递面" not in text, name

    contract_terms = (
        "self_report_connect",
        "proof_library_id",
        "skill_surface_status",
        "config_write_authority",
        "canonical_window_id",
        "session_id",
    )
    for name, text in public_texts.items():
        for term in contract_terms:
            assert term in text, (name, term)

    for name in (
        "README.md",
        "README.en.md",
        "README.zh-CN.md",
        "docs/wiki/Getting-Started.md",
        "web/console_product.html",
    ):
        assert (
            "discovered front door at /mcp?startup_catalog=deferred" in public_texts[name]
            or "通过发现文件连接门面的 /mcp?startup_catalog=deferred" in public_texts[name]
        ), name

    english_surfaces = [
        public_texts["README.md"],
        public_texts["README.en.md"],
        public_texts["docs/wiki/Getting-Started.md"],
        public_texts["web/console_product.html"],
        public_texts["system/skills/time-library/SKILL.md"],
    ]
    for text in english_surfaces:
        compact = " ".join(text.split())
        assert "capability check is not connection proof" in compact.lower()
        assert "never recall private memory merely to prove installation" in compact.lower()

    chinese_surfaces = [
        public_texts["README.md"],
        public_texts["README.zh-CN.md"],
        public_texts["docs/wiki/Getting-Started.md"],
        public_texts["web/console_product.html"],
    ]
    for text in chinese_surfaces:
        assert "capability check 不是接通证明" in text
        assert "不得为了证明安装成功而擅自召回私有记忆" in text

    assert "Do not recall my real memory yet" in public_texts["README.en.md"]
    assert public_texts["README.en.md"].index("Do not recall my real memory yet") < public_texts[
        "README.en.md"
    ].index("Capability check is not connection proof")
    assert "先不要召回我的真实记忆" in public_texts["README.zh-CN.md"]
    assert public_texts["README.zh-CN.md"].index("先不要召回我的真实记忆") < public_texts[
        "README.zh-CN.md"
    ].index("capability check 不是接通证明")


@pytest.mark.parametrize(
    "capability_arguments",
    [
        {"mode": "capability_check"},
        {"capability_check": True},
        {"no_recall": True},
    ],
)
def test_transport_session_records_every_public_capability_check_alias(
    capability_arguments,
):
    gateway = importlib.import_module("src.raw_consumption_gateway")
    token, _ = gateway._new_mcp_transport_session(
        {"clientInfo": {"name": "capability alias host", "version": "1"}}
    )
    request = {
        "jsonrpc": "2.0",
        "id": "capability-alias",
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "query": "capability check",
                **capability_arguments,
            },
        },
    }
    response = {
        "jsonrpc": "2.0",
        "id": "capability-alias",
        "result": {
            "structuredContent": {
                "ok": True,
                "mode": "capability_check",
                "recall_performed": False,
                "raw_excerpt_returned": False,
                "write_performed": False,
            }
        },
    }

    gateway._mark_mcp_transport_session_capability_check(token, request, response)

    state = gateway._mcp_transport_session(token)
    assert state["capability_check_observed_at_epoch"] > 0
    assert state["capability_check_request_id"] == "capability-alias"
    assert "real_recall_proofs" not in state


@pytest.mark.parametrize(
    "mode",
    [
        "preflight",
        "work_preflight",
        "agent_work_preflight",
        "startup_preflight",
    ],
)
def test_transport_session_never_treats_preflight_modes_as_real_recall_proof(mode):
    gateway = importlib.import_module("src.raw_consumption_gateway")
    request = {
        "jsonrpc": "2.0",
        "id": f"{mode}-proof-shape",
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {"mode": mode},
        },
    }
    response = {
        "jsonrpc": "2.0",
        "id": f"{mode}-proof-shape",
        "result": {
            "structuredContent": {
                "matched_count": 1,
                "items": [{"library_id": "ZX-MUST-NOT-BECOME-PROOF"}],
                "consumer_receipt": {
                    "used_source_refs": [{"source_path": "raw/test.jsonl"}],
                },
            }
        },
    }

    assert gateway._mcp_real_recall_proofs(request, response) == []


def test_transport_session_recall_proofs_are_sanitized_and_bounded():
    gateway = importlib.import_module("src.raw_consumption_gateway")
    token, _ = gateway._new_mcp_transport_session(
        {"clientInfo": {"name": "future host", "version": "1"}}
    )
    private_marker = "PRIVATE_RECALL_BODY_MUST_NOT_ENTER_SESSION_STATE"
    items = [
        {
            "library_id": f"ZX-TEST-{index:03d}",
            "summary": private_marker,
            "raw_excerpt": private_marker,
        }
        for index in range(gateway.MCP_SESSION_MAX_RECALL_PROOFS + 5)
    ]
    request = {
        "method": "tools/call",
        "params": {
            "name": "time_library_recall",
            "arguments": {
                "query": private_marker,
                "source_system": "future_host",
                "session_id": "session-1",
            },
        },
    }
    response = {
        "result": {
            "structuredContent": {
                "matched_count": len(items),
                "raw_excerpt_returned": True,
                "items": items,
                "consumer_receipt": {
                    "used_source_refs": [{"source_path": "/private/source.jsonl"}],
                },
            }
        }
    }

    gateway._mark_mcp_transport_session_capability_check(
        token,
        {
            "id": "capability-before-recall",
            "method": "tools/call",
            "params": {
                "name": "time_library_recall",
                "arguments": {"mode": "capability_check"},
            },
        },
        {
            "result": {
                "structuredContent": {
                    "ok": True,
                    "mode": "capability_check",
                    "recall_performed": False,
                    "raw_excerpt_returned": False,
                    "write_performed": False,
                }
            }
        },
    )
    gateway._mark_mcp_transport_session_recall_proof(token, request, response)
    session = gateway._mcp_transport_session(token)
    proofs = session["real_recall_proofs"]

    assert len(proofs) == gateway.MCP_SESSION_MAX_RECALL_PROOFS
    serialized = json.dumps(proofs, ensure_ascii=False)
    assert private_marker not in serialized
    assert "/private/source.jsonl" not in serialized
    assert all(
        set(proof) == {
            "library_id",
            "matched_count",
            "source_refs_count",
            "raw_excerpt_returned",
            "recall_source_system_filter",
            "canonical_window_id",
            "session_id",
            "observed_at_epoch",
        }
        for proof in proofs.values()
    )


def test_same_session_recall_proof_can_reference_a_different_memory_source(tmp_path, monkeypatch):
    memcore_root = tmp_path / "memcore"
    (memcore_root / "config").mkdir(parents=True)
    (memcore_root / "VERSION").write_text("2099.1.2\n", encoding="utf-8")
    (memcore_root / "config" / "memcore.json").write_text(
        json.dumps({"paths": {"base": "."}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv(
        "MEMCORE_READING_AREA_REGISTRY",
        str(memcore_root / "config" / "reading_area_registry.json"),
    )
    for module_name in (
        "config_loader",
        "src.config_loader",
        "src.raw_gateway_mcp_runtime",
        "src.reading_area_registry",
    ):
        sys.modules.pop(module_name, None)
    runtime = importlib.import_module("src.raw_gateway_mcp_runtime")
    result = runtime._platform_self_report_connect_payload(
        {
            "action": "self_report_connect",
            "source_system": "host_beta",
            "consumer": "host_beta",
            "session_id": "session-beta",
            "declared_project_ids": ["Project Beta"],
            "skill_surface_status": "mcp_only",
            "config_write_authority": False,
            "proof_library_id": "ZX-PRIOR-001",
        },
        connection_context={
            "initialized": True,
            "client_info_present": True,
            "transport_session_id": "transport-1",
            "client_name": "future host",
            "client_version": "1",
            "inferred_platform_hint": "unknown_mcp_client",
            "capability_check_observed_at_epoch": 0.5,
            "real_recall_proofs": {
                "ZX-PRIOR-001": {
                    "library_id": "ZX-PRIOR-001",
                    "matched_count": 1,
                    "source_refs_count": 1,
                    "raw_excerpt_returned": False,
                    "recall_source_system_filter": "codex",
                    "session_id": "codex-session",
                    "observed_at_epoch": 1.0,
                }
            },
        },
    )

    assert result["ok"] is True
    assert result["self_report_verified"] is True
    assert result["client_info"]["self_reported_platform"] == "host_beta"
    assert result["real_recall_proof"]["recall_source_system_filter"] == "codex"
    assert result["registration_blockers"] == []


def test_self_report_connect_requires_capability_before_recall_and_same_session(tmp_path, monkeypatch):
    memcore_root = tmp_path / "memcore"
    (memcore_root / "config").mkdir(parents=True)
    (memcore_root / "VERSION").write_text("2099.1.2\n", encoding="utf-8")
    (memcore_root / "config" / "memcore.json").write_text(
        json.dumps({"paths": {"base": "."}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    for module_name in (
        "config_loader",
        "src.config_loader",
        "src.raw_gateway_mcp_runtime",
    ):
        sys.modules.pop(module_name, None)
    runtime = importlib.import_module("src.raw_gateway_mcp_runtime")
    args = {
        "action": "self_report_connect",
        "source_system": "unknown_host",
        "consumer": "unknown_host",
        "session_id": "unknown-session",
        "declared_project_ids": ["Project Unknown"],
        "skill_surface_status": "mcp_only",
        "config_write_authority": False,
        "proof_library_id": "ZX-PRIOR-001",
    }
    proof = {
        "ZX-PRIOR-001": {
            "library_id": "ZX-PRIOR-001",
            "matched_count": 1,
            "source_refs_count": 1,
            "raw_excerpt_returned": False,
            "observed_at_epoch": 1.0,
        }
    }
    base = {
        "initialized": True,
        "client_info_present": True,
        "client_name": "unknown host",
        "client_version": "1",
        "inferred_platform_hint": "unknown_mcp_client",
    }

    skipped_capability = runtime._platform_self_report_connect_payload(
        args,
        connection_context={
            **base,
            "transport_session_id": "transport-without-capability",
            "real_recall_proofs": proof,
        },
    )
    wrong_order = runtime._platform_self_report_connect_payload(
        args,
        connection_context={
            **base,
            "transport_session_id": "transport-wrong-order",
            "capability_check_observed_at_epoch": 2.0,
            "real_recall_proofs": proof,
        },
    )
    other_session = runtime._platform_self_report_connect_payload(
        args,
        connection_context={
            **base,
            "transport_session_id": "transport-without-proof",
            "capability_check_observed_at_epoch": 0.5,
            "real_recall_proofs": {},
        },
    )

    assert skipped_capability["error"] == "capability_check_not_observed_in_transport_session"
    assert skipped_capability["write_performed"] is False
    assert wrong_order["real_recall_proof"]["error"] == "capability_check_must_precede_real_recall"
    assert wrong_order["write_performed"] is False
    assert other_session["real_recall_proof"]["error"] == "prior_real_recall_proof_not_found_in_transport_session"
    assert other_session["write_performed"] is False
    assert not (memcore_root / "runtime" / "delivery-events.sqlite3").exists()
