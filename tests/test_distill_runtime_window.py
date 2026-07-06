from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "distill_runtime_window.py"
SPEC = importlib.util.spec_from_file_location("distill_runtime_window_test_module", TOOL)
assert SPEC and SPEC.loader
runtime_window = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_window)


def test_hydrates_minimax_key_from_mmx_config_without_returning_secret(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".mmx").mkdir(parents=True)
    (home / ".mmx" / "config.json").write_text(
        json.dumps({"api_key": "sk-test-secret", "region": "global"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    result = runtime_window._hydrate_minimax_api_key("MINIMAX_API_KEY")

    assert result["api_key_present"] is True
    assert result["loaded_from_mmx"] is True
    assert result["source"] == "mmx_config"
    assert "secret" not in json.dumps(result)


def test_hydrates_minimax_key_when_existing_env_is_blank(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".mmx").mkdir(parents=True)
    (home / ".mmx" / "config.json").write_text(
        json.dumps({"api_key": "sk-from-config"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MINIMAX_API_KEY", "   ")

    result = runtime_window._hydrate_minimax_api_key("MINIMAX_API_KEY")

    assert result["api_key_present"] is True
    assert result["source"] == "mmx_config"
    assert "from-config" not in json.dumps(result)


def test_live_self_check_collects_catalog_and_reading_area_ids(monkeypatch):
    def fake_http_json(url, *, timeout=20):
        if "catalog-inject" in url:
            return {
                "ok": True,
                "instructions_char_count": 766,
                "contains_body_markers": False,
                "reading_area_contains_body_markers": False,
                "catalog_entry_count": 1,
                "startup_instruction_mode": "reading_area_lanes_only",
                "catalog": [{"library_id": "ZX-ZHIYI-1"}],
                "reading_area_projection": {
                    "project_pages": [
                        {
                            "library_id_pull_handles": ["ZX-XINGCE-2"],
                            "lanes": [{"library_ids": ["ZX-RAW-3"]}],
                            "history": {"visible_record_ids": ["PH-HISTORY-1"]},
                        }
                    ]
                },
            }
        if "catalog-card" in url:
            if "PH-HISTORY-1" in url:
                return {"ok": True, "raw_source_excerpt": "source"}
            return {"ok": True, "verbatim_excerpt": "source"}
        return {"ok": False}

    monkeypatch.setattr(runtime_window, "_http_json", fake_http_json)

    payload = runtime_window.collect_live_self_check(
        {"produced_library_ids": ["ZX-XINGCE-2", "ZX-RAW-3"], "produced_project_history_ids": ["PH-HISTORY-1"]},
        port=9840,
    )

    assert payload["instructions_char_count"] == 766
    assert set(payload["catalog_library_ids"]) == {"ZX-ZHIYI-1", "ZX-XINGCE-2", "ZX-RAW-3", "PH-HISTORY-1"}
    assert payload["project_page_history_ids"] == ["PH-HISTORY-1"]
    assert payload["borrow_results"]["ZX-XINGCE-2"]["ok"] is True
    assert payload["borrow_results"]["PH-HISTORY-1"]["raw_source_excerpt"] == "source"
