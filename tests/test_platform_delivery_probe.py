import importlib
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_platform_delivery_probe_runs_work_preflight_findings_only(tmp_path):
    probe = importlib.import_module("src.platform_delivery_probe")
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            captured["request"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "classification": "already_built_but_forgotten",
                "decision": "surface",
                "recall_status": "preflight_surface_required",
                "memory_scope": "window",
                "scope_missing": False,
                "cross_window_read": False,
                "cross_window_read_allowed": False,
                "active_layers_used": ["current_window"],
                "source_refs_count": 2,
                "raw_items_count": 1,
                "fast_window_preflight": True,
                "fast_recall_path": "canonical_window_index",
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = probe.build_platform_delivery_liveness_probe(
            {
                "endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "query": "送达审计",
                "platforms": ["openclaw", "codex"],
                "canonical_window_id": "codex-current",
                "autodiscovery_payload": {
                    "systems": [
                        {
                            "system": "openclaw",
                            "status": "active",
                            "connectable_now": True,
                            "intent_signal_detected": True,
                            "content_gate": "verified_format_collector_required",
                            "actions": [{"action": "capability_check", "status": "ready"}],
                        },
                        {
                            "system": "codex",
                            "status": "active",
                            "connectable_now": True,
                            "intent_signal_detected": True,
                            "content_gate": "verified_format_collector_required",
                            "actions": [{"action": "capability_check", "status": "ready"}],
                        },
                    ],
                },
            }
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert captured["request"]["mode"] == "work_preflight"
    assert captured["request"]["query"] == "送达审计"
    assert captured["request"]["canonical_window_id"] == "codex-current"
    assert payload["contract"] == "platform_delivery_liveness_probe.v2026.6.21"
    assert payload["read_only"] is True
    assert payload["findings_only"] is True
    assert payload["write_performed"] is False
    assert payload["platform_write_performed"] is False
    assert payload["model_call_performed"] is False
    assert payload["platform_chat_delivery_attempted"] is False
    assert payload["work_preflight_probe"]["not_platform_delivery_proof"] is True
    assert payload["work_preflight_probe"]["response"]["source_refs_count"] == 2
    audit = payload["platform_delivery_liveness"]
    assert audit["findings_only"] is True
    assert audit["counts"]["platforms_total"] == 2
    for finding in audit["platforms"]:
        assert finding["source_refs_visible"] is True
        assert finding["delivered_to_model"] == "not_measured"
        assert "connection_signal_only_not_delivery_proof" in finding["risk"]


def test_platform_delivery_probe_can_skip_work_preflight():
    probe = importlib.import_module("src.platform_delivery_probe")

    payload = probe.build_platform_delivery_liveness_probe(
        {
            "run_work_preflight": False,
            "platforms": "hermes",
            "autodiscovery_payload": {
                "systems": [
                    {
                        "system": "hermes",
                        "status": "detected",
                        "connectable_now": False,
                        "intent_signal_detected": False,
                        "content_gate": "raw_pointer_consumption_only_no_platform_write",
                        "actions": [{"action": "auto_connect", "status": "auto_connect_ready"}],
                    }
                ]
            },
        }
    )

    assert payload["work_preflight_probe_performed"] is False
    assert payload["work_preflight_probe"]["skipped"] is True
    assert payload["work_preflight_probe"]["model_call_performed"] is False
    finding = payload["platform_delivery_liveness"]["platforms"][0]
    assert finding["platform"] == "hermes"
    assert finding["source_refs_visible"] is False
    assert "source_refs_not_visible" in finding["risk"]


def test_platform_delivery_probe_defaults_to_all_discovered_platforms():
    probe = importlib.import_module("src.platform_delivery_probe")

    payload = probe.build_platform_delivery_liveness_probe(
        {
            "run_work_preflight": False,
            "autodiscovery_payload": {
                "systems": [
                    {
                        "system": "openclaw",
                        "status": "active",
                        "connectable_now": True,
                        "intent_signal_detected": True,
                        "actions": [{"action": "capability_check", "status": "ready"}],
                    },
                    {
                        "system": "cursor",
                        "status": "active",
                        "connectable_now": True,
                        "intent_signal_detected": True,
                        "actions": [{"action": "capability_check", "status": "ready"}],
                    },
                    {
                        "system": "pi",
                        "status": "detected",
                        "connectable_now": False,
                        "intent_signal_detected": False,
                        "actions": [{"action": "auto_connect", "status": "auto_connect_ready"}],
                    },
                    {
                        "system": "not_installed",
                        "status": "not_found",
                        "connectable_now": False,
                        "intent_signal_detected": False,
                        "actions": [{"action": "observe_only", "status": "blocked"}],
                    },
                ]
            },
        }
    )

    platforms = {item["platform"] for item in payload["platform_delivery_liveness"]["platforms"]}
    assert platforms == {"openclaw", "cursor", "pi"}


def test_platform_delivery_probe_cli_outputs_json(tmp_path):
    script = ROOT / "tools" / "platform_delivery_liveness_probe.py"
    run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--no-work-preflight",
            "--platforms",
            "codex",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(run.stdout)
    assert payload["contract"] == "platform_delivery_liveness_probe.v2026.6.21"
    assert payload["read_only"] is True
    assert payload["work_preflight_probe_performed"] is False
    assert payload["platform_delivery_liveness"]["platforms"][0]["platform"] == "codex"
