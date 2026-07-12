import importlib
import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _fixture_records():
    return [
        {
            "_type": "xingce_work_experience_candidate",
            "library_id": "ZX-XINGCE-TEST-LOOPS",
            "summary": "Check existing source-backed behavior before changing recall.",
            "detail": "Use the provided source refs and acceptance checks without writing production data.",
            "work_scenario": "testing read-only proof loops",
            "action_strategy": ["inspect provided records", "preserve source refs"],
            "avoid_conditions": ["do not invent missing records"],
            "source_refs": {
                "source_system": "test-agent",
                "source_path": "raw/test-agent/source-a.jsonl",
                "session_id": "fixture-session-a",
            },
            "verbatim_excerpt": "Check existing behavior before changing recall.",
            "acceptance_checks": ["source refs remain available"],
            "_xingce": {"candidate_id": "fixture-candidate", "lifecycle_status": "candidate"},
        },
        {
            "type": "preference_memory",
            "library_id": "ZX-ZHIYI-TEST-LOOPS",
            "summary": "Prefer concrete evidence over slogans.",
            "detail": "Only provided records may contribute to this test result.",
            "source_refs": {
                "source_system": "test-agent",
                "source_path": "raw/test-agent/source-b.jsonl",
                "session_id": "fixture-session-b",
            },
            "verbatim_excerpt": "Prefer concrete evidence over slogans.",
        },
    ]


def test_productized_loops_doctor_aggregates_five_read_only_loops(tmp_path, monkeypatch):
    loops = importlib.import_module("src.productized_loops")

    payload = loops.build_productized_loops_doctor(
        {"skip_platform_scan": True, "records": _fixture_records()},
        memcore_root=tmp_path,
        home=tmp_path,
    )

    assert payload["ok"] is True
    assert payload["contract"] == "productized_loops_doctor.v2026.6.20"
    assert payload["read_only"] is True
    assert payload["write_performed"] is False
    assert payload["raw_write_performed"] is False
    assert payload["platform_write_performed"] is False
    assert payload["not_a_new_memory_layer"] is True
    assert payload["loop_ids"] == [
        "connect_doctor",
        "hot_path_preflight",
        "recall_experience_benchmark",
        "borrowing_receipts",
        "experience_evolution_demo",
    ]
    assert set(payload["loops"]) == set(payload["loop_ids"])
    assert all(item["read_only"] is True for item in payload["loop_statuses"].values())
    assert all(item["write_performed"] is False for item in payload["loop_statuses"].values())
    assert payload["summary"]["preflight_classification"] == "already_built_but_forgotten"
    assert payload["summary"]["benchmark_best_mode"] == "zhiyi_plus_xingce"
    assert payload["summary"]["benchmark_xingce_signal_detected"] is True
    assert payload["summary"]["borrowing_demo_receipts"] >= 2
    assert payload["summary"]["experience_candidate_count"] >= 1
    assert payload["summary"]["hermes_upgrade_candidate_count"] == 0
    assert (
        payload["loops"]["experience_evolution_demo"]["apply_package"][
            "ready_for_authorized_apply"
        ]
        is False
    )


def test_borrowing_receipts_view_exposes_library_ids_source_refs_and_receipts(tmp_path):
    loops = importlib.import_module("src.productized_loops")

    payload = loops.build_borrowing_receipts_view_dry_run(
        {"records": _fixture_records()},
        memcore_root=tmp_path,
    )

    assert payload["contract"] == "productized_borrowing_receipts_view.v2026.6.20"
    assert payload["read_only"] is True
    assert payload["write_performed"] is False
    assert payload["demo_receipt_count"] >= 2
    first = payload["demo_receipts"][0]
    assert first["library_id"].startswith("ZX-")
    assert first["library_shelf"] in {"zhiyi", "xingce", "toolbook", "errata"}
    assert first["source_refs"]["source_path"].startswith("raw/")
    assert first["raw_evidence_status"] == "raw_index"
    assert first["rank_reason"]
    receipt = payload["consumer_receipt"]
    assert receipt["receipt_scope"] == "productized_borrowing_receipts_read_only"
    assert receipt["read_only"] is True
    assert receipt["write_performed"] is False
    assert first["library_id"] in receipt["used_library_ids"]
    assert receipt["source_refs_count"] >= 1


def test_experience_evolution_preview_stays_blocked_without_review_or_authorization(tmp_path):
    loops = importlib.import_module("src.productized_loops")

    payload = loops.build_experience_evolution_demo_dry_run(
        {"records": _fixture_records()},
        memcore_root=tmp_path,
    )

    assert payload["contract"] == "productized_experience_evolution_demo.v2026.6.20"
    assert payload["read_only"] is True
    assert payload["write_performed"] is False
    assert payload["not_a_new_memory_layer"] is True
    assert payload["experience_evolution"]["candidate_count"] >= 1
    assert payload["review_actions"]["action_count"] == 0
    assert payload["apply_gate"]["status"] != "ready"
    assert payload["apply_package"]["package_status"] != "ready"
    assert payload["apply_package"]["write_performed"] is False
    assert payload["apply_package"]["authorized_apply_performed"] is False
    assert payload["hermes_skill_experience_diff"]["read_only"] is True
    assert payload["hermes_skill_experience_diff"]["write_performed"] is False
    assert payload["hermes_skill_experience_diff"]["summary"]["upgrade_candidate_count"] == 0


def test_productized_loops_cli_prints_json_without_platform_scan(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "productized_loops_doctor.py"),
            "--skip-platform-scan",
            "--memcore-root",
            str(tmp_path),
            "--home",
            str(tmp_path),
            "--json",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    payload = json.loads(result.stdout)

    assert payload["ok"] is True
    assert payload["evidence_status"] == "no_records_not_measured"
    assert payload["summary"]["borrowing_demo_receipts"] == 0
    assert payload["summary"]["experience_candidate_count"] == 0
    assert payload["read_only"] is True
    assert payload["write_performed"] is False


def test_productized_loops_console_routes_are_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in [
        "config_loader",
        "src.config_loader",
        "p6_console",
        "src.p6_console",
        "p6_experience_governance",
        "src.p6_experience_governance",
        "productized_loops",
        "src.productized_loops",
    ]:
        sys.modules.pop(name, None)
    p6 = importlib.import_module("p6_console")
    server = p6.ThreadingHTTPServer(("127.0.0.1", 0), p6.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/productized-loops/doctor?skip_platform_scan=1",
            timeout=10,
        ) as response:
            doctor = json.loads(response.read().decode("utf-8"))
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/productized-loops/borrowing-receipts",
            timeout=10,
        ) as response:
            receipts = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert doctor["contract"] == "productized_loops_doctor.v2026.6.20"
    assert doctor["read_only"] is True
    assert doctor["write_performed"] is False
    assert doctor["evidence_status"] == "no_records_not_measured"
    assert doctor["summary"]["borrowing_demo_receipts"] == 0
    assert receipts["contract"] == "productized_borrowing_receipts_view.v2026.6.20"
    assert receipts["read_only"] is True
    assert receipts["write_performed"] is False
    assert receipts["consumer_receipt"]["used_library_ids"] == []
    assert receipts["demo_receipt_count"] == 0
