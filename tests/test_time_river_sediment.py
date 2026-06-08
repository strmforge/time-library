import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_time_river_sediment_links_derived_memory_to_raw_origin():
    from time_river_sediment import build_sediment_link

    record = {
        "library_id": "ZX-XINGCE-RAWLINK",
        "library_shelf": "xingce",
        "summary": "先查源记录再沉淀经验。",
        "source_refs": {
            "source_system": "codex",
            "session_id": "session-1",
            "source_path": "/tmp/source.jsonl",
            "raw_session_path": "/tmp/raw.jsonl",
        },
        "origin_event": {
            "origin_id": "origin_abc",
            "origin_status": "origin_witnessed",
            "origin_label": "起源已见证",
            "source_refs": {
                "source_system": "codex",
                "session_id": "session-1",
                "raw_session_path": "/tmp/raw.jsonl",
            },
        },
    }

    link = build_sediment_link(record)

    assert link["contract"] == "tiandao_time_river_sediment.v1"
    assert link["time_origin_contract"] == "tiandao_time_origin.v1"
    assert link["time_river_contract"] == "tiandao_time_river.v1"
    assert link["sediment_id"].startswith("sediment_")
    assert link["sediment_layer"] == "xingce"
    assert link["library_id"] == "ZX-XINGCE-RAWLINK"
    assert link["origin_id"] == "origin_abc"
    assert link["origin_status"] == "origin_witnessed"
    assert link["sediment_status"] == "origin_linked"
    assert link["trusted_sediment"] is True
    assert link["raw_authority_policy"] == "raw_source_text_is_highest_authority"
    assert link["summary_policy"] == "summaries_are_navigation_not_source_replacement"
    assert link["write_performed"] is False


def test_time_river_sediment_keeps_source_refs_only_as_candidate():
    from time_river_sediment import build_sediment_link

    link = build_sediment_link({
        "library_id": "ZX-ZHIYI-SOURCEONLY",
        "library_shelf": "zhiyi",
        "source_refs": {
            "source_system": "claude_desktop",
            "source_path": "/tmp/claude-source.jsonl",
        },
        "verbatim_excerpt": "用户原话。",
    })

    assert link["source_refs_available"] is True
    assert link["origin_event_available"] is False
    assert link["sediment_status"] == "source_refs_only"
    assert link["candidate_until_origin_linked"] is True
    assert link["trusted_sediment"] is False
    assert link["raw_available"] is True


def test_time_river_sediment_marks_lost_raw_untrusted():
    from time_river_sediment import build_sediment_link

    link = build_sediment_link({
        "library_id": "ZX-TOOL-LOSTRAW",
        "library_shelf": "toolbook",
        "source_refs": {"source_system": "probe", "source_path": "raw/probe_logs/tool.jsonl"},
        "origin_event": {
            "origin_id": "origin_lost_raw",
            "origin_status": "lost_raw",
            "origin_label": "遗失 raw",
        },
    })

    assert link["sediment_status"] == "raw_unavailable_untrusted"
    assert link["trusted_sediment"] is False
    assert link["origin_status_label"] == "遗失 raw"


def test_time_river_sediment_dry_run_is_read_only():
    from time_river_sediment import build_time_river_sediment_dry_run

    result = build_time_river_sediment_dry_run({
        "record": {
            "library_id": "ZX-XINGCE-DRYRUN",
            "library_shelf": "xingce",
            "source_refs": {"source_system": "codex", "source_path": "/tmp/session.jsonl"},
        },
    })

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert result["raw_write_performed"] is False
    assert result["sediment"]["contract"] == "tiandao_time_river_sediment.v1"
