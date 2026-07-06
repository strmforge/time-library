from __future__ import annotations

import json
from pathlib import Path


def test_passive_probe_default_log_uses_launchd_log_dir():
    import runtime_passive_freshness_probe as probe

    assert probe.DEFAULT_WATCHER_LOG == Path.home() / "Library" / "Logs" / "memcore-cloud" / "p0-watcher.out.log"


def test_passive_probe_template_missing(monkeypatch, tmp_path):
    import runtime_passive_freshness_probe as probe

    payload = probe.build_probe_result(
        {
            "template_source_path": str(tmp_path / "missing.jsonl"),
            "endpoint": "http://127.0.0.1:9851/api/v1/raw/query",
        }
    )

    assert payload["ok"] is False
    assert payload["status"] == "template_source_missing"
    assert "template source missing" in payload["error"]
    assert payload["extraction_trigger"] == "watcher"


def test_passive_probe_success(monkeypatch, tmp_path):
    import runtime_passive_freshness_probe as probe

    template = tmp_path / "template.jsonl"
    template.write_text("{}\n", encoding="utf-8")
    generated = tmp_path / "probe-freshness-demo.jsonl"
    raw_dest = tmp_path / "raw.jsonl"

    state = {"gateway_calls": 0}

    monkeypatch.setattr(probe, "POLL_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(probe, "POLL_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(probe, "_watcher_log_size", lambda path: 0)
    monkeypatch.setattr(probe, "_tail_new_watcher_lines", lambda path, offset: ["[watch] probe-freshness-demo"]) 
    monkeypatch.setattr(
        probe.forced_probe,
        "_generate_probe_source_session",
        lambda src, token, token_hash: (
            True,
            {
                "generated_source_path": str(generated),
                "session_id": "probe-freshness-demo",
                "source_created": True,
                "bytes_written": 321,
                "error": "",
            },
        ),
    )
    monkeypatch.setattr(probe, "_compute_installed_raw_dest", lambda source_path: str(raw_dest))

    def fake_query(endpoint, query):
        state["gateway_calls"] += 1
        if state["gateway_calls"] == 1:
            return {}, "timeout: timed out"
        raw_dest.write_text("probe raw", encoding="utf-8")
        return (
            {
                "items": [
                    {
                        "library_id": "ZX-ZHIYI-DEMO",
                        "summary": f"token={query}",
                        "matched_by": ["keyword", "raw_offset"],
                    }
                ],
                "memory_cache_status": "recent_delta_fast_path",
                "freshness_boundary": "bounded_recent_delta",
                "recent_delta_applied": True,
            },
            "",
        )

    monkeypatch.setattr(probe, "_query_gateway", fake_query)
    monkeypatch.setattr(probe, "_perform_cleanup", lambda *args: {"all_layers_cleaned": True, "gateway_empty_after_cleanup": True})

    payload = probe.build_probe_result(
        {
            "template_source_path": str(template),
            "endpoint": "http://127.0.0.1:9851/api/v1/raw/query",
            "iterations": 1,
        }
    )

    assert payload["ok"] is True
    assert payload["status"] == "connected_runtime_passive_default_recall_proven"
    assert payload["default_recall_visible"] is True
    assert payload["passive_write_detected"] is True
    assert payload["all_layers_cleaned"] is True
    assert payload["gateway_empty_after_cleanup"] is True
    assert payload["runs"][0]["watcher_log_mentions_session"] is True
    assert payload["runs"][0]["gateway_hit"]["library_id"] == "ZX-ZHIYI-DEMO"
    assert payload["timing_summary"]["iterations"] == 1


def test_passive_probe_timeout_honest(monkeypatch, tmp_path):
    import runtime_passive_freshness_probe as probe

    template = tmp_path / "template.jsonl"
    template.write_text("{}\n", encoding="utf-8")
    generated = tmp_path / "probe-freshness-timeout.jsonl"
    raw_dest = tmp_path / "raw-timeout.jsonl"

    monkeypatch.setattr(probe, "POLL_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(probe, "_watcher_log_size", lambda path: 0)
    monkeypatch.setattr(probe, "_tail_new_watcher_lines", lambda path, offset: [])
    monkeypatch.setattr(
        probe.forced_probe,
        "_generate_probe_source_session",
        lambda src, token, token_hash: (
            True,
            {
                "generated_source_path": str(generated),
                "session_id": "probe-freshness-timeout",
                "source_created": True,
                "bytes_written": 222,
                "error": "",
            },
        ),
    )
    monkeypatch.setattr(probe, "_compute_installed_raw_dest", lambda source_path: str(raw_dest))
    raw_dest.write_text("exists", encoding="utf-8")
    monkeypatch.setattr(probe, "_query_gateway", lambda endpoint, query: ({}, "timeout: timed out"))
    monkeypatch.setattr(probe, "_perform_cleanup", lambda *args: {"all_layers_cleaned": True, "gateway_empty_after_cleanup": True})

    payload = probe.build_probe_result(
        {
            "template_source_path": str(template),
            "endpoint": "http://127.0.0.1:9851/api/v1/raw/query",
            "iterations": 1,
            "timeout_seconds": 0.01,
        }
    )

    assert payload["ok"] is False
    assert payload["status"] == "passive_timeout"
    assert "token not visible" in payload["error"]
    assert payload["passive_write_detected"] is False
    assert payload["default_recall_visible"] is False
