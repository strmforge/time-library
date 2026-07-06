import importlib
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_evidence_items_from_work_preflight_response_uses_compact_surfaces_only():
    mod = importlib.import_module("src.work_preflight_search_think_probe")

    evidence = mod.evidence_items_from_work_preflight_response(
        {
            "must_surface": [
                {
                    "library_id": "ZX-XINGCE-1",
                    "library_shelf": "xingce",
                    "title": "送达审计",
                    "summary": "先查已有 delivery liveness probe。",
                    "rank_reason": "source_refs available",
                    "source_system": "codex",
                    "source_path": "raw/probe_logs/delivery.jsonl",
                    "raw_excerpt": "this must not be copied",
                }
            ]
        },
        backtrace_source_refs=False,
    )

    assert len(evidence) == 1
    assert evidence[0]["library_id"] == "ZX-XINGCE-1"
    assert evidence[0]["source_refs"]["source_path"] == "raw/probe_logs/delivery.jsonl"
    assert evidence[0]["raw_expand_available"] is True
    assert "this must not be copied" not in evidence[0]["text"]
    assert evidence[0]["answer_bearing"] == "supporting_context"


def test_evidence_items_from_work_preflight_source_anchor_only_is_candidate_only():
    mod = importlib.import_module("src.work_preflight_search_think_probe")

    evidence = mod.evidence_items_from_work_preflight_response(
        {
            "library_index_projection_refs": [
                {
                    "library_id": "ZX-ANCHOR",
                    "library_shelf": "zhiyi",
                    "source_system": "codex",
                    "source_path": "raw/probe_logs/anchor.jsonl",
                }
            ]
        },
        backtrace_source_refs=False,
    )

    assert len(evidence) == 1
    assert evidence[0]["answer_bearing"] == "candidate_only"
    assert evidence[0]["raw_expand_available"] is True


def test_evidence_items_from_work_preflight_response_backtraces_source_ref(tmp_path, monkeypatch):
    mod = importlib.import_module("src.work_preflight_search_think_probe")
    raw_dir = tmp_path / "raw" / "probe_logs"
    raw_dir.mkdir(parents=True)
    (raw_dir / "anchor.jsonl").write_text(
        json.dumps(
            {
                "type": "human",
                "content": "送达审计下一步：先做 findings-only，再做 search/think 分层。",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    evidence = mod.evidence_items_from_work_preflight_response(
        {
            "library_index_projection_refs": [
                {
                    "library_id": "ZX-ANCHOR",
                    "library_shelf": "zhiyi",
                    "source_system": "codex",
                    "source_path": "raw/probe_logs/anchor.jsonl",
                }
            ]
        }
    )

    assert len(evidence) == 1
    assert evidence[0]["answer_bearing"] == "supporting_context"
    assert "findings-only" in evidence[0]["text"]
    assert evidence[0]["raw_excerpt_exposed_by_default"] is False
    assert "raw_excerpt" not in evidence[0]


def test_work_preflight_search_think_probe_runs_read_only_dry_run(tmp_path):
    mod = importlib.import_module("src.work_preflight_search_think_probe")
    captured = {}

    assert mod.DEFAULT_WORK_PREFLIGHT_ENDPOINT == "http://127.0.0.1:9851/api/v1/raw/query"

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
                "source_refs_count": 1,
                "raw_items_count": 1,
                "fast_window_preflight": True,
                "fast_recall_path": "canonical_window_index",
                "must_surface": [
                    {
                        "library_id": "ZX-XINGCE-DELIVERY",
                        "library_shelf": "xingce",
                        "title": "送达审计",
                        "summary": "已经有 findings-only live probe，不能把 source_refs 当模型送达证明。",
                        "rank_reason": "source_refs available; shelf=xingce",
                        "matched_by": ["current_window"],
                        "source_system": "codex",
                        "source_path": "raw/probe_logs/delivery.jsonl",
                        "session_id": "s1",
                        "raw_evidence_status": "raw_index",
                    }
                ],
                "consumer_receipt": {
                    "read_only": True,
                    "write_performed": False,
                    "receipt_scope": "agent_work_preflight_read_only",
                    "source_refs_count": 1,
                    "raw_items_count": 1,
                    "used_library_ids": ["ZX-XINGCE-DELIVERY"],
                },
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
        payload = mod.build_work_preflight_search_think_probe(
            {
                "endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "query": "送达审计下一步",
                "canonical_window_id": "codex-current",
            }
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert captured["request"]["mode"] == "work_preflight"
    assert captured["request"]["query"] == "送达审计下一步"
    assert captured["request"]["consumer"] == "work-preflight-search-think-probe"
    assert captured["request"]["canonical_window_id"] == "codex-current"
    assert payload["contract"] == "work_preflight_search_think_probe.v2026.6.21"
    assert payload["work_preflight_probe"]["contract"] == "work_preflight_search_think_entry_probe.v2026.6.21"
    assert payload["read_only"] is True
    assert payload["findings_only"] is True
    assert payload["write_performed"] is False
    assert payload["platform_write_performed"] is False
    assert payload["model_call_performed"] is False
    assert payload["not_platform_delivery_proof"] is True
    assert payload["evidence_items_count"] == 1
    assert payload["evidence_items"][0]["library_id"] == "ZX-XINGCE-DELIVERY"
    assert payload["search_think_dry_run"]["search_owner"] == "local_memcore"
    assert payload["search_think_dry_run"]["think_owner"] == "evidence_bound_model"
    assert payload["search_think_dry_run"]["model_call_performed"] is False
    assert payload["controlled_think_execution"]["allowed"] is False
    assert payload["controlled_think_execution"]["default_no_model_call"] is True
    assert "prompt_messages" not in payload["search_think_dry_run"]["evidence_bound_model_result"]
    assert payload["search_think_dry_run"]["evidence_bound_model_result"]["prompt_messages_omitted"] == "compact_probe_output"
    assert payload["delivery_receipt_view"]["status"] == "unknown"
    assert payload["delivery_receipt_view"]["actions"]["expand_raw"]["available"] is True
    assert payload["boundary"]["source_refs_are_local_entry_evidence_not_platform_model_receipt"] is True


def _serve_work_preflight_payload(payload):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_work_preflight_search_think_probe_execute_requested_requires_confirmation(tmp_path, monkeypatch):
    mod = importlib.import_module("src.work_preflight_search_think_probe")
    raw_dir = tmp_path / "raw" / "probe_logs"
    raw_dir.mkdir(parents=True)
    (raw_dir / "delivery.jsonl").write_text(
        json.dumps({"type": "human", "content": "发布门禁本地测试通过。"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    server, thread = _serve_work_preflight_payload(
        {
            "ok": True,
            "mode": "work_preflight",
            "contract": "agent_work_preflight.v2026.6.20",
            "decision": "surface",
            "library_index_projection_refs": [
                {
                    "library_id": "ZX-GATE",
                    "source_system": "codex",
                    "source_path": "raw/probe_logs/delivery.jsonl",
                }
            ],
        }
    )
    try:
        payload = mod.build_work_preflight_search_think_probe(
            {
                "endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "execute_think": True,
            },
            client=lambda *_: (_ for _ in ()).throw(AssertionError("confirmation gate should block client")),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert payload["controlled_think_execution"]["execute_requested"] is True
    assert payload["controlled_think_execution"]["allowed"] is False
    assert payload["controlled_think_execution"]["client_supplied"] is True
    assert payload["controlled_think_execution"]["blocked_reasons"] == ["confirm_model_call_required"]
    assert payload["model_call_performed"] is False


def test_work_preflight_search_think_probe_confirmed_model_owned_think(tmp_path, monkeypatch):
    mod = importlib.import_module("src.work_preflight_search_think_probe")
    raw_dir = tmp_path / "raw" / "probe_logs"
    raw_dir.mkdir(parents=True)
    (raw_dir / "delivery.jsonl").write_text(
        json.dumps({"type": "human", "content": "发布门禁本地测试通过，但没有远端 release 回执。"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    server, thread = _serve_work_preflight_payload(
        {
            "ok": True,
            "mode": "work_preflight",
            "contract": "agent_work_preflight.v2026.6.20",
            "decision": "surface",
            "library_index_projection_refs": [
                {
                    "library_id": "ZX-GATE",
                    "source_system": "codex",
                    "source_path": "raw/probe_logs/delivery.jsonl",
                }
            ],
        }
    )
    captured = {}

    def client(messages, config):
        prompt = json.loads(messages[1]["content"])
        captured["question"] = prompt["question"]
        captured["local_may_synthesize_answer"] = prompt["question_context"]["local_may_synthesize_answer"]
        captured["evidence_refs"] = [item["evidence_ref"] for item in prompt["evidence"]]
        return {
            "content": json.dumps(
                {
                    "answer": "只能确认本地测试通过；远端 release 回执 UNKNOWN。",
                    "verdict": "answered",
                    "confidence": 0.8,
                    "supporting_refs": ["ZX-GATE"],
                    "unknown_reason": "remote_release_receipt_missing",
                },
                ensure_ascii=False,
            )
        }

    try:
        payload = mod.build_work_preflight_search_think_probe(
            {
                "endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "query": "发布完成了吗",
                "execute_think": True,
                "confirm_model_call": True,
                "model_config": {"provider": "test", "model": "fake", "base_url": "", "api_key_env": ""},
            },
            client=client,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert captured["question"] == "发布完成了吗"
    assert captured["local_may_synthesize_answer"] is False
    assert captured["evidence_refs"] == ["ZX-GATE"]
    assert payload["controlled_think_execution"]["allowed"] is True
    assert payload["model_call_performed"] is True
    assert payload["search_think_dry_run"]["think_owner"] == "evidence_bound_model"
    assert payload["search_think_dry_run"]["think_result"]["answer_source"] == "evidence_bound_model_call"
    assert payload["search_think_dry_run"]["think_result"]["used_source_refs"] == ["ZX-GATE"]
    assert payload["search_think_dry_run"]["think_validation"]["ok"] is True
    assert payload["search_think_dry_run"]["delivery_receipt"]["used_records_count"] == 1
    assert payload["search_think_dry_run"]["delivery_receipt_view"]["status"] == "source_backed"
    assert payload["boundary"]["controlled_model_call_requires_explicit_gate"] is True


def test_work_preflight_search_think_probe_no_evidence_keeps_unknown_boundary():
    mod = importlib.import_module("src.work_preflight_search_think_probe")

    payload = mod.build_work_preflight_search_think_probe(
        {
            "query": "无证据测试",
            "endpoint": "http://127.0.0.1:1/api/v1/raw/query",
            "timeout_seconds": 0.01,
        }
    )

    assert payload["ok"] is False
    assert payload["model_call_performed"] is False
    assert "work_preflight_response_not_ok" in payload["missing_evidence"]
    assert "work_preflight_no_compact_evidence_items" in payload["missing_evidence"]
    assert payload["search_think_dry_run"]["think_result"]["answer"] == "UNKNOWN"
    assert payload["delivery_receipt_view"]["unknown_boundary"] is True


def test_work_preflight_search_think_probe_source_anchor_backtrace_removes_gap(tmp_path, monkeypatch):
    mod = importlib.import_module("src.work_preflight_search_think_probe")
    raw_dir = tmp_path / "raw" / "probe_logs"
    raw_dir.mkdir(parents=True)
    (raw_dir / "anchor.jsonl").write_text(
        json.dumps(
            {
                "type": "human",
                "content": "source_refs 可回源成 compact evidence，但前台默认不展示 raw excerpt。",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            payload = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "decision": "surface",
                "source_refs_count": 1,
                "raw_items_count": 1,
                "library_index_projection_refs": [
                    {
                        "library_id": "ZX-ANCHOR",
                        "library_shelf": "zhiyi",
                        "source_system": "codex",
                        "source_path": "raw/probe_logs/anchor.jsonl",
                    }
                ],
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
        payload = mod.build_work_preflight_search_think_probe(
            {"endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query"}
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert payload["evidence_items_count"] == 1
    assert payload["evidence_items"][0]["answer_bearing"] == "supporting_context"
    assert payload["source_ref_compact_evidence_probe"]["raw_backtrace_hits_count"] == 1
    assert payload["source_ref_compact_evidence_probe"]["raw_excerpt_exposed"] is False
    assert "work_preflight_source_anchors_only_no_answer_text" not in payload["missing_evidence"]
    assert "work_preflight_source_anchors_only_no_answer_text" not in payload["delivery_receipt_view"]["gaps"]
    assert payload["boundary"]["raw_excerpt_not_exposed_by_default"] is True


def test_work_preflight_search_think_probe_unresolved_source_anchors_adds_gap(tmp_path):
    mod = importlib.import_module("src.work_preflight_search_think_probe")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            payload = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "decision": "surface",
                "source_refs_count": 1,
                "raw_items_count": 1,
                "library_index_projection_refs": [
                    {
                        "library_id": "ZX-ANCHOR",
                        "library_shelf": "zhiyi",
                        "source_system": "codex",
                        "source_path": "raw/probe_logs/missing-anchor.jsonl",
                    }
                ],
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
        payload = mod.build_work_preflight_search_think_probe(
            {"endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query"}
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert payload["evidence_items_count"] == 1
    assert payload["evidence_items"][0]["answer_bearing"] == "candidate_only"
    assert payload["source_ref_compact_evidence_probe"]["raw_backtrace_hits_count"] == 0
    assert "work_preflight_source_anchors_only_no_answer_text" in payload["missing_evidence"]
    assert "work_preflight_source_anchors_only_no_answer_text" in payload["delivery_receipt_view"]["gaps"]


def test_work_preflight_search_think_probe_cli_outputs_json():
    script = ROOT / "tools" / "work_preflight_search_think_probe.py"
    run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--endpoint",
            "http://127.0.0.1:1/api/v1/raw/query",
            "--timeout-seconds",
            "0.01",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert run.returncode == 2
    payload = json.loads(run.stdout)
    assert payload["contract"] == "work_preflight_search_think_probe.v2026.6.21"
    assert payload["read_only"] is True
    assert payload["platform_write_performed"] is False
    assert payload["model_call_performed"] is False
