import json
import hashlib
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.recall_before_judgment_liveness import (
    DEFAULT_QUERY,
    DEFAULT_REQUIRED_TERMS,
    RECALL_BEFORE_JUDGMENT_LIVENESS_CONTRACT,
    build_recall_before_judgment_liveness,
)


def test_recall_before_judgment_liveness_default_query_uses_scoped_recall_boundary_not_read_authorization():
    assert DEFAULT_QUERY == "Trusted Memory 安装后的 scoped recall 权限边界是什么，哪些动作需要升级授权？"
    assert "读前授权" not in DEFAULT_QUERY
    assert "读取用户工作记录" not in DEFAULT_QUERY
    assert "installed local trust boundary" in DEFAULT_REQUIRED_TERMS
    assert "context_inject" in DEFAULT_REQUIRED_TERMS
    assert "direct_answer" in DEFAULT_REQUIRED_TERMS
    assert "platform_act" in DEFAULT_REQUIRED_TERMS


def test_recall_before_judgment_liveness_accepts_authoritative_anchor():
    payload = build_recall_before_judgment_liveness(
        {"required_terms": ["memory_authority_policy", "recall_only", "投影不脱敏"]},
        work_preflight_response={
            "ok": True,
            "mode": "work_preflight",
            "contract": "agent_work_preflight.v2026.6.20",
            "decision": "surface",
            "classification": "diagnostic_gap",
            "source_refs_count": 2,
            "raw_items_count": 2,
            "evidence": [
                {
                    "library_id": "ZX-AUTHORITY",
                    "library_shelf": "xingce",
                    "summary": "src/memory_authority_policy.py says recall_only can read memory; 05 says 投影不脱敏.",
                    "source_system": "codex",
                    "source_path": "src/memory_authority_policy.py",
                    "raw_evidence_status": "raw_index",
                }
            ],
        },
    )

    assert payload["ok"] is True
    assert payload["contract"] == RECALL_BEFORE_JUDGMENT_LIVENESS_CONTRACT
    assert payload["status"] == "authoritative_anchor_surfaced"
    assert payload["read_only"] is True
    assert payload["model_call_performed"] is False
    assert payload["platform_write_performed"] is False
    assert payload["matched_required_terms"] == ["memory_authority_policy", "recall_only", "投影不脱敏"]
    assert payload["missing_required_terms"] == []
    assert payload["boundary"]["automatic_answer_injection"] is False


def test_recall_before_judgment_liveness_accepts_required_terms_field_when_summary_is_compacted():
    payload = build_recall_before_judgment_liveness(
        {"required_terms": ["installed local trust boundary", "投影不脱敏"]},
        work_preflight_response={
            "ok": True,
            "mode": "work_preflight",
            "contract": "agent_work_preflight.v2026.6.20",
            "decision": "surface",
            "classification": "diagnostic_gap",
            "source_refs_count": 2,
            "raw_items_count": 2,
            "evidence": [
                {
                    "library_id": "ZX-AUTH-LOCAL-TRUST-BOUNDARY",
                    "library_shelf": "errata",
                    "summary": "Compacted summary omitted the exact boundary term.",
                    "required_terms": ["installed local trust boundary"],
                    "source_system": "codex",
                    "source_path": "src/memory_authority_policy.py",
                    "raw_evidence_status": "raw_authority_file",
                },
                {
                    "library_id": "ZX-AUTH-ORIGINAL-WORDING",
                    "library_shelf": "errata",
                    "summary": "",
                    "required_terms": ["投影不脱敏"],
                    "source_system": "codex",
                    "source_path": "src/memory_authority_policy.py",
                    "raw_evidence_status": "raw_authority_file",
                },
            ],
        },
    )

    assert payload["ok"] is True
    assert payload["status"] == "authoritative_anchor_surfaced"
    assert payload["matched_required_terms"] == ["installed local trust boundary", "投影不脱敏"]
    assert payload["missing_required_terms"] == []


def test_recall_before_judgment_liveness_flags_weak_source_ref_without_authority():
    payload = build_recall_before_judgment_liveness(
        {"required_terms": ["memory_authority_policy"]},
        work_preflight_response={
            "ok": True,
            "mode": "work_preflight",
            "contract": "agent_work_preflight.v2026.6.20",
            "decision": "surface",
            "source_refs_count": 1,
            "raw_items_count": 1,
            "library_index_projection_refs": [
                {
                    "library_id": "ZX-RECENT",
                    "library_shelf": "zhiyi",
                    "summary": "NAS 回读正常。",
                    "source_system": "codex",
                    "source_path": "raw/session.jsonl",
                    "raw_evidence_status": "raw_index",
                }
            ],
        },
    )

    assert payload["ok"] is False
    assert payload["status"] == "weak_anchor_surfaced"
    assert payload["source_refs_count"] == 1
    assert payload["missing_required_terms"] == ["memory_authority_policy"]
    assert payload["diagnosis"] == "preflight_returned_source_refs_but_not_the_required_authoritative_boundary"


def test_recall_before_judgment_liveness_can_call_work_preflight_endpoint():
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            captured["request"] = json.loads(self.rfile.read(length).decode("utf-8"))
            response = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "decision": "surface",
                "source_refs_count": 1,
                "raw_items_count": 1,
                "evidence": [
                    {
                        "library_id": "ZX-299",
                        "summary": "299_2026-06-21_TrustedMemory授权模型纠偏: recall_only 允许读取。",
                        "source_path": "<private-time-rule-canon>/299_2026-06-21_TrustedMemory授权模型纠偏.md",
                    }
                ],
            }
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = build_recall_before_judgment_liveness(
            {
                "endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "query": "授权模型纠偏",
                "canonical_window_id": "codex-current",
                "project_root": "/work/memcore-cloud",
                "required_terms": ["299_2026-06-21_TrustedMemory授权模型纠偏", "recall_only"],
            }
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert captured["request"]["mode"] == "work_preflight"
    assert captured["request"]["query"] == "授权模型纠偏"
    assert captured["request"]["source_system"] == ""
    assert captured["request"]["canonical_window_id"] == "codex-current"
    assert captured["request"]["project_root"] == "/work/memcore-cloud"
    assert payload["ok"] is True
    assert payload["work_preflight_called"] is True
    assert payload["status"] == "authoritative_anchor_surfaced"
    assert payload["service_identity"]["service_health_checked"] is True


def test_recall_before_judgment_liveness_reports_matching_service_source_identity(tmp_path):
    project = tmp_path / "repo"
    gateway = project / "src" / "raw_consumption_gateway.py"
    gateway.parent.mkdir(parents=True)
    gateway.write_text("print('gateway')\n", encoding="utf-8")
    gateway_hash = hashlib.sha256(gateway.read_bytes()).hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            response = {
                "ok": True,
                "service": "raw_consumption_gateway",
                "version": "test",
                "identity_contract": "raw_gateway_health_identity.v1",
                "source_path": str(gateway),
                "source_sha256": gateway_hash,
            }
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            response = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "decision": "surface",
                "source_refs_count": 1,
                "raw_items_count": 1,
                "evidence": [
                    {
                        "library_id": "ZX-AUTH",
                        "summary": "memory_authority_policy recall_only 投影不脱敏",
                        "source_path": str(gateway),
                    }
                ],
            }
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = build_recall_before_judgment_liveness(
            {
                "endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "project_root": str(project),
                "required_terms": ["memory_authority_policy", "recall_only", "投影不脱敏"],
            }
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    identity = payload["service_identity"]
    assert identity["service_health_checked"] is True
    assert identity["service_health_ok"] is True
    assert identity["service_source_sha256"] == gateway_hash
    assert identity["working_tree_source_sha256"] == gateway_hash
    assert identity["service_source_matches_working_tree"] is True
    assert identity["service_source_status"] == "matches_working_tree"
    assert payload["service_refresh_required"] is False


def test_recall_before_judgment_liveness_flags_stale_installed_service_source(tmp_path):
    project = tmp_path / "repo"
    gateway = project / "src" / "raw_consumption_gateway.py"
    gateway.parent.mkdir(parents=True)
    gateway.write_text("print('working tree gateway')\n", encoding="utf-8")
    stale_hash = hashlib.sha256(b"stale installed gateway").hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            response = {
                "ok": True,
                "service": "raw_consumption_gateway",
                "version": "installed-test",
                "identity_contract": "raw_gateway_health_identity.v1",
                "source_path": "/installed/raw_consumption_gateway.py",
                "source_sha256": stale_hash,
            }
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            response = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "decision": "surface",
                "source_refs_count": 1,
                "raw_items_count": 1,
                "evidence": [
                    {
                        "library_id": "ZX-RECENT",
                        "summary": "recent context without the required policy anchor",
                        "source_path": "raw/session.jsonl",
                    }
                ],
            }
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = build_recall_before_judgment_liveness(
            {
                "endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "project_root": str(project),
                "required_terms": ["memory_authority_policy"],
            }
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert payload["status"] == "weak_anchor_surfaced"
    identity = payload["service_identity"]
    assert identity["service_source_sha256"] == stale_hash
    assert identity["working_tree_source_sha256"]
    assert identity["service_source_matches_working_tree"] is False
    assert identity["service_source_status"] == "differs_from_working_tree"
    assert identity["service_refresh_required"] is True
    assert payload["service_refresh_required"] is True


def test_recall_before_judgment_liveness_hits_real_gateway_authority_anchor_http(tmp_path, monkeypatch):
    from src import raw_consumption_gateway as raw_gateway

    records_db = tmp_path / "memcore" / "output" / "records" / "records.db"
    records_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(records_db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                record_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                project_root text,
                source_path text,
                raw_path text,
                role text,
                native_type text,
                native_id text,
                timestamp text,
                line_no integer,
                raw_line_no integer,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                content_preview text,
                updated_at text
            )
            """
        )
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(records_db))
    authority_dir = tmp_path / "authority"
    authority_dir.mkdir(parents=True)
    policy = authority_dir / "memory_authority_policy.py"
    policy.write_text("memory_authority_policy: recall_only can read scoped memory.", encoding="utf-8")
    no_boundary = authority_dir / "05_不要误改的边界.md"
    no_boundary.write_text("用户已经明确：Time Library投影不脱敏。", encoding="utf-8")
    correction = authority_dir / "299_2026-06-21_TrustedMemory授权模型纠偏.md"
    correction.write_text(
        "299_2026-06-21_TrustedMemory授权模型纠偏: installed local trust boundary; scope_and_queries_required.",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        raw_gateway,
        "TRUSTED_MEMORY_AUTHORITY_ANCHORS",
        (
            {
                "library_id": "ZX-AUTH-POLICY-HTTP",
                "library_shelf": "errata",
                "source_path": str(policy),
                "summary": "memory_authority_policy recall_only",
                "terms": ("memory_authority_policy", "recall_only"),
            },
            {
                "library_id": "ZX-AUTH-05-HTTP",
                "library_shelf": "errata",
                "source_path": str(no_boundary),
                "summary": "投影不脱敏",
                "terms": ("投影不脱敏",),
            },
            {
                "library_id": "ZX-AUTH-299-HTTP",
                "library_shelf": "errata",
                "source_path": str(correction),
                "summary": "299_2026-06-21_TrustedMemory授权模型纠偏 scope_and_queries_required",
                "terms": ("299_2026-06-21_TrustedMemory授权模型纠偏", "scope_and_queries_required"),
            },
        ),
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), raw_gateway.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = build_recall_before_judgment_liveness(
            {
                "endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "canonical_window_id": "codex-current",
                "project_root": "/work/memcore-cloud",
                "required_terms": [
                    "memory_authority_policy",
                    "recall_only",
                    "投影不脱敏",
                    "299_2026-06-21_TrustedMemory授权模型纠偏",
                    "scope_and_queries_required",
                ],
            }
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert payload["ok"] is True
    assert payload["status"] == "authoritative_anchor_surfaced"
    assert payload["work_preflight_called"] is True
    assert payload["decision"] == "surface"
    assert payload["source_refs_count"] >= 3
    assert payload["matched_required_terms"] == [
        "299_2026-06-21_TrustedMemory授权模型纠偏",
        "memory_authority_policy",
        "recall_only",
        "scope_and_queries_required",
        "投影不脱敏",
    ]
    assert payload["missing_required_terms"] == []
