import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_raw_origin_event_is_stable_and_raw_is_time_origin():
    from raw_origin_event import build_raw_origin_event

    first = build_raw_origin_event(
        source_system="codex",
        computer_id="machine-a",
        native_session_key="session-a",
        source_path="/tmp/source.jsonl",
        raw_path="/tmp/raw.jsonl",
        source_exists=True,
        raw_exists=True,
        event_time="2026-06-08T00:00:00Z",
        captured_at="2026-06-08T00:00:01Z",
        audit_time="2026-06-08T00:00:02Z",
        content_hash="hash-a",
        byte_offset=0,
        line_no=1,
    )
    second = build_raw_origin_event(
        source_system="codex",
        computer_id="machine-a",
        native_session_key="session-a",
        source_path="/tmp/source.jsonl",
        raw_path="/tmp/raw.jsonl",
        source_exists=True,
        raw_exists=True,
        event_time="2026-06-08T00:00:00Z",
        captured_at="2026-06-08T00:00:01Z",
        audit_time="2026-06-08T00:00:02Z",
        content_hash="hash-a",
        byte_offset=0,
        line_no=1,
    )

    assert first["origin_id"] == second["origin_id"]
    assert first["origin_contract"] == "tiandao_time_origin.v1"
    assert first["time_river_contract"] == "tiandao_time_river.v1"
    assert first["origin_layer"] == "raw"
    assert first["origin_status"] == "origin_witnessed"
    assert first["origin_seen"] is True
    assert first["no_raw_no_river"] is True
    assert first["platform_policy"] == "platforms_are_inlets_not_origin"
    assert first["river_endpoint_policy"] == "time_river_has_no_endpoint"


def test_raw_origin_event_uses_lost_source_and_lost_raw_labels():
    from raw_origin_event import (
        build_raw_origin_event,
        classify_origin_status,
        origin_status_label,
    )

    assert classify_origin_status(source_exists=True, raw_exists=False) == "lost_raw"
    assert classify_origin_status(source_exists=False, raw_exists=True) == "lost_source"
    assert origin_status_label("lost_raw") == "遗失 raw"
    assert origin_status_label("lost_source") == "遗失源"

    lost_raw = build_raw_origin_event(
        source_system="openclaw",
        source_path="/tmp/source.jsonl",
        source_exists=True,
        raw_exists=False,
    )
    lost_source = build_raw_origin_event(
        source_system="claude_desktop",
        raw_path="/tmp/raw.jsonl",
        source_exists=False,
        raw_exists=True,
    )

    assert lost_raw["origin_status"] == "lost_raw"
    assert lost_raw["origin_label"] == "遗失 raw"
    assert lost_raw["origin_seen"] is False
    assert lost_source["origin_status"] == "lost_source"
    assert lost_source["origin_label"] == "遗失源"
