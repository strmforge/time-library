import importlib.util
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_release_gate():
    path = ROOT / "tools" / "release_gate.py"
    spec = importlib.util.spec_from_file_location("release_gate_truthfulness", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_release_gate_blocks_private_host_and_fake_runtime_markers():
    gate = _load_release_gate()
    blocked = set(gate.PUBLIC_SURFACE_SCAN_TERMS)

    expected = {
        "n" + "100",
        "ubuntu" + "181",
        "h" + "730xd",
        "u" + "green",
        "macbook" + "124",
        "FIXTURE" + "_MAP",
        "_sample_" + "hermes_items",
        "mock" + "_for_test",
    }
    assert expected <= blocked


def test_release_runtime_sources_do_not_embed_private_topology_or_fake_defaults():
    paths = (
        ROOT / "src" / "runtime_topology.py",
        ROOT / "src" / "raw_experience_endpoint.py",
        ROOT / "src" / "platform_adapters" / "runtime_profile_provider.py",
        ROOT / "src" / "platform_adapters" / "update_manager.py",
        ROOT / "src" / "zhiyi_interposition_mvp.py",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    blocked = (
        "n" + "100",
        "FIXTURE" + "_MAP",
        "_sample_" + "hermes_items",
        "mock" + "_for_test",
        "returns " + "fake but structurally valid profile",
        "extracted (" + "mock)",
    )
    assert not any(term in text for term in blocked)


def test_generic_mixed_runtime_topology_has_no_machine_identity(monkeypatch):
    from src import runtime_topology

    monkeypatch.delenv("MEMCORE_RUNTIME_MODE", raising=False)
    monkeypatch.setattr(runtime_topology.platform, "system", lambda: "Windows")
    monkeypatch.setattr(runtime_topology, "_cwd_is_y_drive", lambda: True)

    mode = runtime_topology.detect_runtime_mode()
    assert mode is runtime_topology.RuntimeMode.MIXED_LINUX_WINDOWS
    assert mode.value == "mixed_linux_windows"


def test_raw_experience_compat_endpoint_reads_real_raw_direct_path(monkeypatch):
    from src import raw_experience_endpoint

    observed = {}

    def query_raw_direct(**kwargs):
        observed.update(kwargs)
        return [{"raw_excerpt": "source-backed", "source_path": "memory/source.jsonl"}]

    monkeypatch.setattr(raw_experience_endpoint, "query_raw_direct", query_raw_direct)
    handler = raw_experience_endpoint.Handler.__new__(raw_experience_endpoint.Handler)
    replies = []
    handler._json = lambda status, payload: replies.append((status, payload))

    handler._handle_direct_query({
        "consumer": ["hermes"],
        "source_system": ["hermes"],
        "query_hint": ["source"],
        "include_raw_excerpt": ["false"],
    })

    assert observed["consumer"] == "hermes"
    assert observed["source_system"] == "hermes"
    status, payload = replies[-1]
    assert status == 200
    assert payload["source_mode"] == "raw_direct"
    assert payload["read_only"] is True
    assert payload["production_write"] is False
    assert "raw_excerpt" not in payload["items"][0]


def test_raw_experience_unknown_consumer_is_preserved_and_never_invents_a_source(monkeypatch):
    from src import raw_experience_endpoint

    observed = {}
    handler = raw_experience_endpoint.Handler.__new__(raw_experience_endpoint.Handler)
    replies = []
    handler._json = lambda status, payload: replies.append((status, payload))
    monkeypatch.setattr(
        raw_experience_endpoint,
        "query_raw_direct",
        lambda **kwargs: observed.update(kwargs) or [],
    )

    handler._handle_direct_query({
        "consumer": ["future_xyz"],
        "source_system": ["future_source"],
    })

    assert replies[-1][0] == 200
    assert observed["consumer"] == "future_xyz"
    assert observed["source_system"] == "future_source"

    observed.clear()
    handler._handle_direct_query({"consumer": ["future_xyz"]})

    assert replies[-1] == (
        400,
        {"ok": False, "error": "source_system_required_no_consumer_inference"},
    )
    assert observed == {}


def test_raw_experience_direct_query_requires_configured_token(monkeypatch):
    from src import raw_experience_endpoint

    monkeypatch.setenv(raw_experience_endpoint.TOKEN_ENV, "required-token")
    handler = raw_experience_endpoint.Handler.__new__(raw_experience_endpoint.Handler)
    handler.path = "/raw-experience/direct-query?consumer=hermes"
    handler.headers = {}
    replies = []
    handler._json = lambda status, payload: replies.append((status, payload))
    handler._handle_direct_query = lambda _query: replies.append((500, {"error": "auth_bypassed"}))

    handler.do_GET()

    assert replies == [(401, {"ok": False, "error": "missing_bearer_token"})]


def test_raw_experience_rejects_archive_path_traversal(monkeypatch):
    from src import raw_experience_endpoint

    handler = raw_experience_endpoint.Handler.__new__(raw_experience_endpoint.Handler)
    replies = []
    handler._json = lambda status, payload: replies.append((status, payload))
    monkeypatch.setattr(
        raw_experience_endpoint,
        "query_raw_direct",
        lambda **_kwargs: pytest.fail("path traversal reached raw archive query"),
    )

    handler._handle_direct_query({
        "consumer": ["hermes"],
        "source_system": ["hermes"],
        "computer_name": ["../private"],
    })

    assert replies == [(400, {"ok": False, "error": "invalid_path_segment:computer_name"})]


def test_raw_experience_response_is_not_cross_origin_readable():
    from src import raw_experience_endpoint

    handler = raw_experience_endpoint.Handler.__new__(raw_experience_endpoint.Handler)
    headers = {}
    handler.send_response = lambda _status: None
    handler.send_header = lambda name, value: headers.__setitem__(name, value)
    handler.end_headers = lambda: None
    handler.wfile = io.BytesIO()

    handler._json(200, {"ok": True})

    assert "Access-Control-Allow-Origin" not in headers
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_legacy_platform_adapters_fail_explicitly_instead_of_claiming_success():
    from src.platform_adapters.runtime_profile_provider import (
        MacOSRuntimeProfileProvider,
        WindowsRuntimeProfileProvider,
    )
    from src.platform_adapters.update_manager import MacOSUpdateManager, WindowsUpdateManager

    assert WindowsRuntimeProfileProvider().get_runtime_profile()["status"] == "unavailable"
    assert MacOSRuntimeProfileProvider().get_runtime_profile()["status"] == "unavailable"

    for manager in (WindowsUpdateManager(), MacOSUpdateManager()):
        result = manager.apply_update("candidate.zip", "install-root", "checksum", dry_run=False)
        assert result["ok"] is False
        assert result["error"] == "legacy_update_adapter_unavailable_use_native_installer"


def test_productized_doctor_does_not_invent_records_reviews_or_authorization(tmp_path):
    from src.productized_loops import build_productized_loops_doctor

    payload = build_productized_loops_doctor(
        {"skip_platform_scan": True},
        memcore_root=tmp_path,
        home=tmp_path,
    )

    assert payload["evidence_status"] == "no_records_not_measured"
    assert payload["summary"]["borrowing_demo_receipts"] == 0
    evolution = payload["loops"]["experience_evolution_demo"]
    assert evolution["records"] == []
    assert evolution["replay"]["status"] == "not_measured_no_records"
    assert evolution["replay"]["feedback_candidates"]["candidate_count"] == 0
    assert evolution["experience_evolution"]["candidate_count"] == 0
    assert evolution["review_actions"]["action_count"] == 0
    assert evolution["validation_report"]["validation_report_count"] == 0
    assert evolution["validation_receipts"]["receipt_count"] == 0
    assert evolution["review_queue"]["queue_count"] == 0
    assert evolution["apply_receipts"]["receipt_count"] == 0
    assert evolution["apply_gate"]["authorization_complete"] is False
    assert evolution["apply_gate"]["status"] != "ready"
    assert evolution["apply_package"]["ready_for_authorized_apply"] is False
    assert evolution["hermes_skill_experience_diff"]["skills_count"] == 0


def test_raw_experience_non_loopback_bind_requires_token(monkeypatch):
    from src import raw_experience_endpoint

    monkeypatch.delenv(raw_experience_endpoint.TOKEN_ENV, raising=False)
    raw_experience_endpoint._validate_bind_security("127.0.0.1")
    raw_experience_endpoint._validate_bind_security("::1")
    with pytest.raises(RuntimeError, match=raw_experience_endpoint.TOKEN_ENV):
        raw_experience_endpoint._validate_bind_security("0.0.0.0")

    monkeypatch.setenv(raw_experience_endpoint.TOKEN_ENV, "configured")
    raw_experience_endpoint._validate_bind_security("0.0.0.0")


def test_platform_package_adapters_build_the_same_privacy_gated_artifact(tmp_path):
    from src.platform_adapters import linux_adapter, macos_adapter, windows_adapter

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    packages = [
        adapter.build_package(version, tmp_path / platform_name)
        for platform_name, adapter in (
            ("linux", linux_adapter),
            ("macos", macos_adapter),
            ("windows", windows_adapter),
        )
    ]

    assert all(path.is_file() for path in packages)
    digests = {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in packages
    }
    assert len(digests) == 1

    with zipfile.ZipFile(packages[0]) as archive:
        names = archive.namelist()
    assert not any(name.endswith("/AGENTS.md") for name in names)
    assert not any("/runtime/" in name or "/input/" in name or "/zhiyi/" in name for name in names)


def test_shipped_storage_catalog_contains_patterns_not_preset_machines():
    payload = json.loads(
        (ROOT / "config" / "platform_storage_patterns.verified.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["observed_machines"] == []
    assert payload["native_path_evidence"] == {}
    assert payload["entries"]


def test_legacy_status_surfaces_do_not_ship_fixed_project_results():
    status_source = (ROOT / "src" / "p6_console_status.py").read_text(encoding="utf-8")
    html = (ROOT / "web" / "console_product.html").read_text(encoding="utf-8")
    blocked = (
        "J7-INJECT" + "-POLICY-NODATA",
        "LIFECYCLE-OVERLAY" + "-COVERAGE",
        "RAW-INTEGRITY" + "-REVIEW",
        "DECISION-M4" + "-NEXT",
        "76fe7e5b0b8d582f17f8b732c63a69c7" + "936573c9bd4474134e3a33922acbbfca",
        "19197c63c8ac770000ce2d338df234a47" + "002ca739124fb8065e0617676fc9691",
    )

    assert not any(term in status_source for term in blocked)
    assert "update.check_ok !== true" in html
    assert "data.check_ok === true && data.update_available && data.install_enabled" in html
