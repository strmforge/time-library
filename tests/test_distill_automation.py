from __future__ import annotations

import json
import hashlib
import importlib
import importlib.util
import subprocess
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

from src import distill_automation as da
from src import distill_runtime_adapter as adapter
from src import reading_area_registry as registry
from src.zhixing_library import library_id_for

ROOT = Path(__file__).resolve().parents[1]


def _create_records_db(tmp_path: Path) -> Path:
    db = tmp_path / "records.db"
    con = sqlite3.connect(db)
    con.execute(
        """
        create table canonical_sessions (
            record_id text primary key,
            source_system text not null,
            session_id text,
            canonical_window_id text,
            raw_artifact_id text,
            project_id text,
            project_root text,
            thread_name text,
            source_path text,
            raw_path text,
            source_size_bytes integer,
            raw_size_bytes integer,
            indexed_message_count integer,
            raw_offset_coverage_count integer,
            index_status text,
            updated_at text
        )
        """
    )
    con.commit()
    con.close()
    return db


def _insert_session(db: Path, tmp_path: Path, *, idx: int, source_system: str = "claude_code_cli", text: str | None = None) -> Path:
    text = text or f"用户偏好样本 {idx}：回答先给结论再给证据"
    source_path = tmp_path / "raw" / f"s{idx}.jsonl"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(text, encoding="utf-8")
    con = sqlite3.connect(db)
    con.execute(
        """
        insert into canonical_sessions (
            record_id, source_system, session_id, canonical_window_id,
            raw_artifact_id, project_id, project_root, thread_name,
            source_path, raw_path, source_size_bytes, raw_size_bytes,
            indexed_message_count, raw_offset_coverage_count, index_status, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"rec-{idx}",
            source_system,
            f"sess-{idx}",
            f"win-{idx}",
            f"raw-{idx}",
            "technical-window-id",
            str(tmp_path),
            f"session {idx}",
            str(source_path),
            "",
            len(text.encode("utf-8")),
            0,
            1,
            1,
            "indexed",
            f"2026-07-02T00:0{idx}:00Z",
        ),
    )
    con.commit()
    con.close()
    return source_path


def _insert_pathless_session(db: Path, tmp_path: Path, *, idx: int) -> None:
    con = sqlite3.connect(db)
    con.execute(
        """
        insert into canonical_sessions (
            record_id, source_system, session_id, canonical_window_id,
            raw_artifact_id, project_id, project_root, thread_name,
            source_path, raw_path, source_size_bytes, raw_size_bytes,
            indexed_message_count, raw_offset_coverage_count, index_status, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"rec-pathless-{idx}",
            "claude_code_cli",
            f"sess-pathless-{idx}",
            f"win-pathless-{idx}",
            f"raw-pathless-{idx}",
            "technical-window-id",
            str(tmp_path),
            f"pathless {idx}",
            "",
            "",
            0,
            0,
            0,
            0,
            "indexed_without_source",
            f"2026-07-02T00:1{idx}:00Z",
        ),
    )
    con.commit()
    con.close()


def _read_ledger(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _model():
    return {"provider": "local", "model": "test-distiller"}


def _candidate_for(session: dict, *, dedupe_key: str | None = None, title: str | None = None) -> dict:
    source_path = Path(session["source_path"])
    text = source_path.read_text(encoding="utf-8")
    return {
        "candidate_id": f"zhiyi-auto-{session['session_id']}",
        "candidate_type": "zhiyi_preference_card",
        "library_shelf": "zhiyi",
        "lifecycle_status": "active",
        "title": title or f"偏好 {session['session_id']}",
        "summary": "用户偏好",
        "preference_statement": title or f"偏好 {session['session_id']}",
        "verbatim_excerpt": text,
        "source_author": "user",
        "source_role": "user",
        "source_mode": "evidence_bound_model_distill",
        "dedupe_key": dedupe_key or f"pref:{session['session_id']}",
        "source_refs": {
            "source_system": session["source_system"],
            "source_path": str(source_path),
            "source_role": "user",
            "byte_offsets": {"start": 0, "end": len(text.encode("utf-8"))},
        },
    }


def _xingce_candidate_for(session: dict) -> dict:
    source_path = Path(session["source_path"])
    text = source_path.read_text(encoding="utf-8")
    raw = text.encode("utf-8")
    return {
        "candidate_id": f"xingce-auto-{session['session_id']}",
        "candidate_type": "xingce_work_experience",
        "library_shelf": "xingce",
        "lifecycle_status": "candidate",
        "title": f"行策 {session['session_id']}",
        "summary": "工作经验",
        "work_scenario": "验证运行态时",
        "action_strategy": "先核源再签字",
        "verbatim_excerpt": text,
        "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
        "source_author": "assistant",
        "source_role": "assistant",
        "source_mode": "evidence_bound_model_distill",
        "dedupe_key": f"xingce:{session['session_id']}",
        "evidence_refs": [
            {
                "source_system": session["source_system"],
                "source_path": str(source_path),
                "source_role": "assistant",
                "byte_offsets": {"start": 0, "end": len(raw)},
            }
        ],
    }


def _toolbook_candidate_for(session: dict, *, dedupe_key: str | None = None) -> dict:
    source_path = Path(session["source_path"])
    text = source_path.read_text(encoding="utf-8")
    raw = text.encode("utf-8")
    return {
        "candidate_id": f"toolbook-auto-{session['session_id']}",
        "candidate_type": "toolbook_candidate",
        "_type": "toolbook_candidate",
        "type": "toolbook_candidate",
        "library_shelf": "toolbook",
        "lifecycle_status": "candidate",
        "title": f"工具事实 {session['session_id']}",
        "summary": "9840 是 catalog HTTP 端口",
        "detail": "9840 是 catalog HTTP 端口",
        "platform": session["source_system"],
        "observed_behavior": "9840 是 catalog HTTP 端口",
        "environment": session["canonical_window_id"],
        "fact_type": "port_or_endpoint",
        "verbatim_excerpt": text,
        "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
        "source_author": "assistant",
        "source_role": "assistant",
        "source_mode": "evidence_bound_p2_extract",
        "dedupe_key": dedupe_key or f"toolbook:{session['session_id']}",
        "source_refs": {
            "source_system": session["source_system"],
            "source_path": str(source_path),
            "source_role": "assistant",
            "source_author": "assistant",
            "byte_offsets": {"start": 0, "end": len(raw)},
            "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
        },
    }


def _project_history_candidate_for(session: dict) -> dict:
    source_path = Path(session["source_path"])
    text = source_path.read_text(encoding="utf-8")
    raw = text.encode("utf-8")
    return {
        "candidate_id": f"project-history-auto-{session['session_id']}",
        "candidate_type": "project_history_digest",
        "history_type": "decision",
        "project_id": session.get("declared_project_ids", ["project:time-library"])[0],
        "title": "白板历史从蒸馏补",
        "summary": "老项目进入白板后从现在记录，历史由蒸馏补到项目页。",
        "verbatim_excerpt": text,
        "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
        "source_author": "user",
        "source_role": "user",
        "source_mode": "evidence_bound_project_history_digest",
        "source_refs": {
            "source_system": session["source_system"],
            "source_path": str(source_path),
            "source_author": "user",
            "source_role": "user",
            "byte_offsets": {"start": 0, "end": len(raw)},
            "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
        },
    }


def _self_check_for(library_ids):
    ids = list(library_ids)
    return {
        "catalog_library_ids": ids,
        "borrow_results": {library_id: {"ok": True, "verbatim_excerpt": "source"} for library_id in ids},
        "instructions_char_count": 766,
        "contains_body_markers": False,
    }


def _project_history_self_check_for(record_ids):
    ids = list(record_ids)
    return {
        "project_history_record_ids": ids,
        "project_page_history_ids": ids,
        "borrow_results": {record_id: {"ok": True, "raw_source_excerpt": "source"} for record_id in ids},
        "instructions_char_count": 900,
        "contains_body_markers": False,
    }


def test_coverage_ledger_is_idempotent_and_tracks_incremental_sessions(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    _insert_session(db, tmp_path, idx=2, source_system="codex")
    ledger = tmp_path / "coverage.jsonl"

    first = da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)
    second = da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)
    _insert_session(db, tmp_path, idx=3, source_system="mimocode")
    third = da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    assert first["added"] == 2
    assert second["added"] == 0
    assert third["added"] == 1
    rows = _read_ledger(ledger)
    assert len(rows) == 3
    assert {row["status"] for row in rows} == {"queued"}
    assert {row["canonical_lane"] for row in rows} == {"opus", "codex", "mimo"}


def test_coverage_ledger_prioritizes_large_queued_sessions(tmp_path):
    db = _create_records_db(tmp_path)
    small = _insert_session(db, tmp_path, idx=1, text="小会话")
    large = _insert_session(db, tmp_path, idx=2, text="大" * 200)
    con = sqlite3.connect(db)
    con.execute("update canonical_sessions set source_size_bytes=? where session_id=?", (small.stat().st_size, "sess-1"))
    con.execute("update canonical_sessions set source_size_bytes=? where session_id=?", (large.stat().st_size, "sess-2"))
    con.commit()
    con.close()
    ledger = tmp_path / "coverage.jsonl"

    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    rows = _read_ledger(ledger)
    assert rows[0]["session_id"] == "sess-2"
    assert rows[0]["source_size_bytes"] > rows[1]["source_size_bytes"]


def test_deep_distill_side_status_queues_only_large_covered_sessions(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="小会话")
    _insert_session(db, tmp_path, idx=2, text="大窗会话")
    con = sqlite3.connect(db)
    con.execute("update canonical_sessions set source_size_bytes=?, indexed_message_count=? where session_id=?", (400, 20, "sess-1"))
    con.execute("update canonical_sessions set source_size_bytes=?, indexed_message_count=? where session_id=?", (2_000_000, 2_000, "sess-2"))
    con.commit()
    con.close()
    ledger = tmp_path / "coverage.jsonl"

    da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=lambda session, model: {"candidates": [_candidate_for(session)]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "deep_distill"},
        target_shape="deep_distill",
        max_sessions=1,
        distill_session=lambda session, model: {"candidates": [_candidate_for(session, title=f"deep {session['session_id']}")]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    rows = {row["session_id"]: row for row in _read_ledger(ledger)}
    assert result["ok"] is True
    assert result["ledger_status_key"] == "deep_distill_status"
    assert rows["sess-1"]["status"] == "covered"
    assert rows["sess-1"]["deep_distill_status"] == "skipped"
    assert rows["sess-1"]["deep_distill_skip_reason"] == "deep_distill_not_large_session"
    assert rows["sess-2"]["status"] == "covered"
    assert rows["sess-2"]["deep_distill_status"] == "covered"
    assert rows["sess-2"]["deep_distill_library_ids"]


def test_deep_distill_side_status_uses_default_candidate_write_path_and_voiceprint(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = _insert_session(
        db,
        tmp_path,
        idx=1,
        text="一致≠印证，我上机独立量。Opus 二签 opus_confirmed，BYTE-EXACT + SHA-MATCH。",
    )
    con = sqlite3.connect(db)
    con.execute("update canonical_sessions set source_size_bytes=?, indexed_message_count=? where session_id=?", (2_000_000, 2_000, "sess-1"))
    con.commit()
    con.close()
    ledger = tmp_path / "coverage.jsonl"

    da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=lambda session, model: {"candidates": [_xingce_candidate_for(session)]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    def deep_distiller(session, model):
        text = Path(session["source_path"]).read_text(encoding="utf-8")
        raw = text.encode("utf-8")
        return {
            "candidates": [{
                "candidate_id": "deep-zhiyi-relayed-auto",
                "candidate_type": "zhiyi_preference_card",
                "library_shelf": "zhiyi",
                "lifecycle_status": "active",
                "title": "一致不等于印证",
                "summary": "一致不等于印证",
                "preference_statement": "一致不等于印证",
                "when_to_use": "报告一致但未独立验牌时",
                "verbatim_excerpt": text,
                "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
                "source_author": "user",
                "source_role": "user",
                "source_mode": "evidence_bound_model_distill",
                "source_refs": {
                    "source_system": session["source_system"],
                    "source_path": str(source_path),
                    "source_author": "user",
                    "source_role": "user",
                    "byte_offsets": {"start": 0, "end": len(raw)},
                    "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
                },
            }]
        }

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "deep_distill"},
        target_shape="deep_distill",
        max_sessions=1,
        distill_session=deep_distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    stored = json.loads((tmp_path / "output" / "zhiyi_preference_cards" / "candidates" / "deep-zhiyi-relayed-auto.json").read_text(encoding="utf-8"))
    row = _read_ledger(ledger)[0]

    assert result["ok"] is True
    assert result["ledger_status_key"] == "deep_distill_status"
    assert row["status"] == "covered"
    assert row["deep_distill_status"] == "covered"
    assert stored["evidence_attribution"] == "user_relayed"
    assert stored["relay_voiceprint"]["user_relayed"] is True
    assert stored["verbatim_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()


def test_mimocode_deep_distill_queues_declared_checkpoint_even_when_base_skipped(tmp_path):
    db = _create_records_db(tmp_path)
    mimocode_root = tmp_path / "mimocode"
    session_id = "ses_0e69f6457ffevUIqYd3yLfN8BL"
    checkpoint = mimocode_root / "memory" / "sessions" / session_id / "checkpoint.md"
    checkpoint.parent.mkdir(parents=True)
    checkpoint_text = (
        "# Session checkpoint\n\n"
        "## §1 Active intent\n"
        "> catalog push runtime wiring\n\n"
        "## §10 Design decisions\n"
        "阅读区只读，raw 不修改。\n"
    )
    checkpoint.write_text(checkpoint_text, encoding="utf-8")
    registry_path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="mimocode",
        consumer="mimo",
        canonical_window_id=session_id,
        session_id=session_id,
        title="MiMo declared checkpoint",
        path=registry_path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="忆凡尘阅读区",
        projects=["time-library"],
        series=["honghuang"],
        path=registry_path,
    )
    ledger = tmp_path / "coverage.jsonl"

    base = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=lambda session, model: {"candidates": [], "skip_reason": "no_evidence_bound_candidates"},
        source_systems=["mimocode"],
        reading_area_registry_path=registry_path,
        mimocode_root=mimocode_root,
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
        max_sessions=1,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "mimocode_deep_distill"},
        target_shape="mimocode_deep_distill",
        distill_session=lambda session, model: {"candidates": [_xingce_candidate_for(session)]},
        source_systems=["mimocode"],
        reading_area_registry_path=registry_path,
        mimocode_root=mimocode_root,
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
        max_sessions=1,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    [row] = _read_ledger(ledger)

    assert base["ok"] is False
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "no_evidence_bound_candidates"
    assert result["ok"] is True
    assert result["ledger_status_key"] == "mimocode_deep_distill_status"
    assert row["mimocode_deep_distill_status"] == "covered"
    assert row["mimocode_deep_distill_library_ids"]


def test_mimocode_deep_distill_does_not_queue_undeclared_mimocode_rows(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, source_system="mimocode")
    ledger = tmp_path / "coverage.jsonl"

    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger, source_systems=["mimocode"])
    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "mimocode_deep_distill"},
        target_shape="mimocode_deep_distill",
        distill_session=lambda session, model: {"candidates": [_candidate_for(session)]},
        source_systems=["mimocode"],
        max_sessions=1,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    [row] = _read_ledger(ledger)

    assert result["processed_session_count"] == 0
    assert result["post_window_self_check"]["terminal_no_queue_window"] is True
    assert row["mimocode_deep_distill_status"] == "excluded"
    assert row["mimocode_deep_distill_exclude_reason"] == "mimocode_deep_distill_requires_declared_checkpoint"


def test_mimocode_deep_distill_uses_runtime_declaration_aliases(tmp_path):
    db = _create_records_db(tmp_path)
    source = _insert_session(db, tmp_path, idx=1, source_system="mimo")
    ledger = tmp_path / "coverage.jsonl"
    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger, source_systems=["mimocode"])
    rows = _read_ledger(ledger)
    assert len(rows) == 1
    row = rows[0]
    row["status"] = "skipped"
    row["coverage_source"] = "reading_area_declared_mimocode_checkpoint"
    row["source_path"] = str(source)
    row["mimocode_deep_distill_status"], status_key, reason = da._initial_target_shape_status(
        row,
        "mimocode_deep_distill",
    )
    row[status_key] = reason

    assert row["source_system"] == "mimo"
    assert row["mimocode_deep_distill_status"] == "queued"
    assert status_key == "queued_at"


def test_mimocode_deep_distill_terminal_single_empty_window_can_pass_when_queue_exhausted(tmp_path):
    result = da.run_window_self_check(
        {
            "target_shape": "mimocode_deep_distill",
            "status": "window_complete",
            "processed_session_count": 1,
            "produced_library_ids": [],
            "empty_window_skip_samples": [
                {
                    "session_key": "session:mimo",
                    "skip_reason": "no_evidence_bound_candidates",
                    "false_negative_found": False,
                }
            ],
            "skip_reason_counts": {"no_evidence_bound_candidates": 1},
            "terminal_target_queue_exhausted": True,
            "target_queue_remaining_count": 0,
        },
        catalog_library_ids=[],
        borrow_results={},
        instructions_char_count=1271,
        contains_body_markers=False,
    )

    assert result["ok"] is True
    assert result["empty_window_receipt_visible"] is True
    assert result["terminal_small_empty_window"] is True


def test_non_mimocode_single_empty_window_still_requires_three_samples():
    result = da.run_window_self_check(
        {
            "target_shape": "deep_distill",
            "status": "window_complete",
            "processed_session_count": 1,
            "produced_library_ids": [],
            "empty_window_skip_samples": [
                {
                    "session_key": "session:deep",
                    "skip_reason": "no_evidence_bound_candidates",
                    "false_negative_found": False,
                }
            ],
            "skip_reason_counts": {"no_evidence_bound_candidates": 1},
            "terminal_target_queue_exhausted": True,
            "target_queue_remaining_count": 0,
        },
        catalog_library_ids=[],
        borrow_results={},
        instructions_char_count=1271,
        contains_body_markers=False,
    )

    assert result["ok"] is False
    assert "empty_window_false_negative_samples_missing" in result["blockers"]
    assert result["terminal_small_empty_window"] is False


def test_deep_distill_does_not_merge_into_inactive_candidate(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = _insert_session(db, tmp_path, idx=1, text="一致≠印证，我上机独立量")
    _insert_session(db, tmp_path, idx=2, text="一致≠印证，我上机独立量")
    _insert_session(db, tmp_path, idx=3, text="一致≠印证，我上机独立量")
    con = sqlite3.connect(db)
    for idx in range(1, 4):
        con.execute("update canonical_sessions set source_size_bytes=?, indexed_message_count=? where session_id=?", (2_000_000, 2_000, f"sess-{idx}"))
    con.commit()
    con.close()
    ledger = tmp_path / "coverage.jsonl"

    inactive = _candidate_for({"source_path": str(source_path), "session_id": "old", "source_system": "claude_code_cli"}, dedupe_key="same-inactive", title="一致不等于印证")
    inactive["candidate_id"] = "inactive-zhiyi"
    inactive["exp_id"] = "inactive-zhiyi"
    inactive["lifecycle_status"] = "superseded"
    inactive_dir = tmp_path / "output" / "zhiyi_preference_cards" / "candidates"
    inactive_dir.mkdir(parents=True)
    (inactive_dir / "inactive-zhiyi.json").write_text(json.dumps(inactive, ensure_ascii=False), encoding="utf-8")

    da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=lambda session, model: {"candidates": [_xingce_candidate_for(session)]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "deep_distill"},
        target_shape="deep_distill",
        distill_session=lambda session, model: {"candidates": [_candidate_for(session, dedupe_key="same-inactive", title="一致不等于印证")]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    row = _read_ledger(ledger)[0]
    rows = _read_ledger(ledger)
    stored = json.loads((inactive_dir / "inactive-zhiyi.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["produced_library_ids"] == []
    assert result["empty_window_skip_sample_count"] == 3
    assert all(item["status"] == "covered" for item in rows)
    assert all(item["deep_distill_status"] == "skipped" for item in rows)
    assert all(item["deep_distill_skip_reason"] == "candidate_matches_inactive_record" for item in rows)
    assert all("deep_distill_library_ids" not in item for item in rows)
    assert stored.get("dedupe_merged") is None
    assert not stored.get("coverage_session_keys")


def test_deep_distill_does_not_recreate_inactive_topic_with_new_dedupe_key(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = _insert_session(db, tmp_path, idx=1, text="一致≠印证，我上机独立量")
    _insert_session(db, tmp_path, idx=2, text="一致≠印证，我上机独立量")
    _insert_session(db, tmp_path, idx=3, text="一致≠印证，我上机独立量")
    con = sqlite3.connect(db)
    for idx in range(1, 4):
        con.execute("update canonical_sessions set source_size_bytes=?, indexed_message_count=? where session_id=?", (2_000_000, 2_000, f"sess-{idx}"))
    con.commit()
    con.close()
    ledger = tmp_path / "coverage.jsonl"

    inactive = _candidate_for({"source_path": str(source_path), "session_id": "old", "source_system": "claude_code_cli"}, dedupe_key="old-inactive", title="一致不等于印证")
    inactive["candidate_id"] = "inactive-topic-zhiyi"
    inactive["exp_id"] = "inactive-topic-zhiyi"
    inactive["lifecycle_status"] = "superseded"
    inactive_dir = tmp_path / "output" / "zhiyi_preference_cards" / "candidates"
    inactive_dir.mkdir(parents=True)
    (inactive_dir / "inactive-topic-zhiyi.json").write_text(json.dumps(inactive, ensure_ascii=False), encoding="utf-8")

    da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=lambda session, model: {"candidates": [_xingce_candidate_for(session)]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "deep_distill"},
        target_shape="deep_distill",
        distill_session=lambda session, model: {"candidates": [_candidate_for(session, dedupe_key=f"new-{session['session_id']}", title="一致不等于印证")]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    rows = _read_ledger(ledger)
    assert result["ok"] is True
    assert result["produced_library_ids"] == []
    assert result["empty_window_skip_sample_count"] == 3
    assert all(item["deep_distill_status"] == "skipped" for item in rows)
    assert all(item["deep_distill_skip_reason"] == "candidate_matches_inactive_record" for item in rows)
    assert len(list(inactive_dir.glob("*.json"))) == 1


def test_deep_distill_empty_tail_window_can_use_recent_visible_samples(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = _insert_session(db, tmp_path, idx=1, text="一致≠印证，我上机独立量")
    _insert_session(db, tmp_path, idx=2, text="一致≠印证，我上机独立量")
    _insert_session(db, tmp_path, idx=3, text="一致≠印证，我上机独立量")
    con = sqlite3.connect(db)
    for idx in range(1, 4):
        con.execute("update canonical_sessions set source_size_bytes=?, indexed_message_count=? where session_id=?", (2_000_000, 2_000, f"sess-{idx}"))
    con.commit()
    con.close()
    ledger = tmp_path / "coverage.jsonl"

    inactive = _candidate_for({"source_path": str(source_path), "session_id": "old", "source_system": "claude_code_cli"}, dedupe_key="old-inactive", title="一致不等于印证")
    inactive["candidate_id"] = "inactive-tail-zhiyi"
    inactive["exp_id"] = "inactive-tail-zhiyi"
    inactive["lifecycle_status"] = "superseded"
    inactive_dir = tmp_path / "output" / "zhiyi_preference_cards" / "candidates"
    inactive_dir.mkdir(parents=True)
    (inactive_dir / "inactive-tail-zhiyi.json").write_text(json.dumps(inactive, ensure_ascii=False), encoding="utf-8")

    da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=lambda session, model: {"candidates": [_xingce_candidate_for(session)]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    first = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "deep_distill"},
        target_shape="deep_distill",
        max_sessions=1,
        distill_session=lambda session, model: {"candidates": [_candidate_for(session, dedupe_key=f"new-{session['session_id']}", title="一致不等于印证")]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    second = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "deep_distill"},
        target_shape="deep_distill",
        max_sessions=2,
        distill_session=lambda session, model: {"candidates": [_candidate_for(session, dedupe_key=f"new-{session['session_id']}", title="一致不等于印证")]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    rows = _read_ledger(ledger)

    assert first["ok"] is False
    assert first["empty_window_skip_sample_count"] == 1
    assert second["ok"] is True
    assert second["empty_window_skip_sample_count"] == 3
    assert len({item["session_key"] for item in second["empty_window_skip_samples"]}) == 3
    assert all(item["deep_distill_status"] == "skipped" for item in rows)


def test_coverage_ledger_keeps_pathless_sessions_visible_as_skipped(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_pathless_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"

    result = da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    assert result["ledger_row_count"] == 1
    row = _read_ledger(ledger)[0]
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "missing_source_path"


def test_coverage_ledger_marks_tiny_probe_sessions_excluded(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text='{"role":"user","content":"Say OK only."}\\n')
    _insert_session(db, tmp_path, idx=2, text="真实项目会话：这里有可以蒸馏的偏好。")
    ledger = tmp_path / "coverage.jsonl"

    result = da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    assert result["ledger_row_count"] == 2
    rows = _read_ledger(ledger)
    by_session = {row["session_id"]: row for row in rows}
    assert by_session["sess-1"]["status"] == "excluded"
    assert by_session["sess-1"]["exclude_reason"] == "tiny_probe_or_smoke_session"
    assert by_session["sess-2"]["status"] == "queued"


def test_coverage_ledger_marks_unknown_source_systems_excluded(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, source_system="codex")
    _insert_session(db, tmp_path, idx=2, source_system="unknown_agent")
    ledger = tmp_path / "coverage.jsonl"

    result = da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    assert result["ledger_row_count"] == 2
    rows = _read_ledger(ledger)
    by_source = {row["source_system"]: row for row in rows}
    assert by_source["codex"]["status"] == "queued"
    assert by_source["unknown_agent"]["status"] == "excluded"
    assert by_source["unknown_agent"]["exclude_reason"] == "source_system_not_in_current_distill_scope"


def test_coverage_ledger_allows_expanded_source_systems(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, source_system="hermes")
    _insert_session(db, tmp_path, idx=2, source_system="openclaw")
    _insert_session(db, tmp_path, idx=3, source_system="claude_desktop")
    ledger = tmp_path / "coverage.jsonl"

    result = da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    assert result["ledger_row_count"] == 3
    rows = _read_ledger(ledger)
    by_source = {row["source_system"]: row for row in rows}
    assert by_source["hermes"]["status"] == "queued"
    assert by_source["openclaw"]["status"] == "queued"
    assert by_source["claude_desktop"]["status"] == "queued"


def test_coverage_ledger_marks_exact_content_duplicates_excluded(tmp_path):
    db = _create_records_db(tmp_path)
    text = "同一段跨入口镜像内容：只应该蒸一次。"
    _insert_session(db, tmp_path, idx=1, source_system="claude_code_cli", text=text)
    _insert_session(db, tmp_path, idx=2, source_system="claude_desktop", text=text)
    _insert_session(db, tmp_path, idx=3, source_system="openclaw", text="另一段独立内容")
    ledger = tmp_path / "coverage.jsonl"

    result = da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    assert result["ledger_row_count"] == 3
    rows = _read_ledger(ledger)
    by_source = {row["source_system"]: row for row in rows}
    assert by_source["claude_code_cli"]["status"] == "queued"
    assert by_source["claude_desktop"]["status"] == "excluded"
    assert by_source["claude_desktop"]["exclude_reason"] == "duplicate_content_already_enrolled"
    assert by_source["claude_desktop"]["content_duplicate_of"] == by_source["claude_code_cli"]["session_key"]
    assert by_source["claude_desktop"]["source_content_sha256"] == by_source["claude_code_cli"]["source_content_sha256"]
    assert by_source["openclaw"]["status"] == "queued"


def test_coverage_ledger_keeps_same_platform_distinct_paths_with_same_content(tmp_path):
    db = _create_records_db(tmp_path)
    text = "同平台两个独立会话可以有相同短文本，但不能因此互相排除。"
    _insert_session(db, tmp_path, idx=1, source_system="hermes", text=text)
    _insert_session(db, tmp_path, idx=2, source_system="hermes", text=text)
    ledger = tmp_path / "coverage.jsonl"

    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    rows = _read_ledger(ledger)
    assert {row["status"] for row in rows} == {"queued"}
    assert all("content_duplicate_of" not in row or not row["content_duplicate_of"] for row in rows)


def test_coverage_ledger_marks_same_path_duplicate_excluded(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = _insert_session(db, tmp_path, idx=1, source_system="openclaw", text="同一源文件重复入账只能蒸一次。")
    con = sqlite3.connect(db)
    con.execute(
        """
        insert into canonical_sessions (
            record_id, source_system, session_id, canonical_window_id,
            raw_artifact_id, project_id, project_root, thread_name,
            source_path, raw_path, source_size_bytes, raw_size_bytes,
            indexed_message_count, raw_offset_coverage_count, index_status, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rec-dup",
            "openclaw",
            "sess-dup",
            "win-dup",
            "raw-dup",
            "technical-window-id",
            str(tmp_path),
            "duplicate same path",
            str(source_path),
            "",
            source_path.stat().st_size,
            0,
            1,
            1,
            "indexed",
            "2026-07-02T00:09:00Z",
        ),
    )
    con.commit()
    con.close()
    ledger = tmp_path / "coverage.jsonl"

    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    rows = _read_ledger(ledger)
    assert [row["status"] for row in rows].count("queued") == 1
    duplicate_rows = [row for row in rows if row["status"] == "excluded"]
    assert len(duplicate_rows) == 1
    assert duplicate_rows[0]["exclude_reason"] == "duplicate_content_already_enrolled"


def test_coverage_ledger_does_not_reopen_covered_expanded_scope_rows(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, source_system="hermes")
    session = da.load_canonical_sessions(db)[0]
    ledger = tmp_path / "coverage.jsonl"
    row = da._entry_from_session(session, distill_version=da.DEFAULT_DISTILL_VERSION)
    row["status"] = "covered"
    row["library_ids"] = ["ZX-ZHIYI-EXISTING"]
    ledger.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    [updated] = _read_ledger(ledger)
    assert updated["status"] == "covered"
    assert updated["library_ids"] == ["ZX-ZHIYI-EXISTING"]
    assert "exclude_reason" not in updated


def test_coverage_reopens_previously_excluded_expanded_scope_rows(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, source_system="hermes")
    ledger = tmp_path / "coverage.jsonl"
    session = da.load_canonical_sessions(db)[0]
    row = da._entry_from_session(
        session,
        distill_version=da.DEFAULT_DISTILL_VERSION,
    )
    row["status"] = "excluded"
    row["exclude_reason"] = "source_system_not_in_current_distill_scope"
    ledger.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)

    [updated] = _read_ledger(ledger)
    assert updated["source_system"] == "hermes"
    assert updated["status"] == "queued"
    assert updated["previous_status"] == "excluded"
    assert updated["previous_exclude_reason"] == "source_system_not_in_current_distill_scope"
    assert "exclude_reason" not in updated


def test_coverage_enrollment_adds_declared_mimocode_checkpoint(tmp_path):
    db = _create_records_db(tmp_path)
    mimocode_root = tmp_path / "mimocode"
    session_id = "ses_0e69f6457ffevUIqYd3yLfN8BL"
    checkpoint = mimocode_root / "memory" / "sessions" / session_id / "checkpoint.md"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(
        "# Session checkpoint\n\n"
        "Topic: catalog push runtime wiring\n\n"
        "## §1 Active intent\n"
        "> \"任务：catalog 开局 push 运行态接线，单焦点。\"\n\n"
        "## §5 Current work\n"
        "已定位 p4_inject catalog endpoint。\n",
        encoding="utf-8",
    )
    undeclared = mimocode_root / "memory" / "sessions" / "ses_undeclared" / "checkpoint.md"
    undeclared.parent.mkdir(parents=True)
    undeclared.write_text("## §1 Active intent\n> unrelated\n", encoding="utf-8")
    registry_path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="mimocode",
        consumer="mimo",
        canonical_window_id=session_id,
        session_id=session_id,
        title="MiMo catalog push runtime wiring",
        path=registry_path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="忆凡尘阅读区",
        projects=["time-library"],
        series=["honghuang"],
        path=registry_path,
    )
    ledger = tmp_path / "coverage.jsonl"

    declared_sessions = da.load_declared_mimocode_sessions(
        records_db_path=db,
        reading_area_registry_path=registry_path,
        mimocode_root=mimocode_root,
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
    )
    result = da.reconcile_coverage_ledger(
        records_db_path=db,
        ledger_path=ledger,
        source_systems=["mimocode"],
        reading_area_registry_path=registry_path,
        mimocode_root=mimocode_root,
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
    )

    assert [session["session_id"] for session in declared_sessions] == [session_id]
    assert "ses_undeclared" not in json.dumps(declared_sessions, ensure_ascii=False)
    assert result["canonical_session_count"] == 0
    assert result["declared_mimocode_session_count"] == 1
    assert result["ledger_row_count"] == 1
    row = _read_ledger(ledger)[0]
    assert row["status"] == "queued"
    assert row["source_system"] == "mimocode"
    assert row["canonical_lane"] == "mimo"
    assert row["coverage_source"] == "reading_area_declared_mimocode_checkpoint"
    assert row["source_path"] == str(checkpoint)
    assert row["raw_offset_coverage_count"] == 1
    assert "ses_undeclared" not in json.dumps(row, ensure_ascii=False)


def test_coverage_enrollment_source_filter_does_not_pull_declared_mimocode(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, source_system="codex")
    mimocode_root = tmp_path / "mimocode"
    session_id = "ses_declared_mimo"
    checkpoint = mimocode_root / "memory" / "sessions" / session_id / "checkpoint.md"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("## §1 Active intent\n> catalog push runtime wiring\n", encoding="utf-8")
    registry_path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="mimocode",
        consumer="mimo",
        canonical_window_id=session_id,
        session_id=session_id,
        title="MiMo declared checkpoint",
        path=registry_path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="忆凡尘阅读区",
        projects=["time-library"],
        series=["honghuang"],
        path=registry_path,
    )
    ledger = tmp_path / "coverage.jsonl"

    result = da.reconcile_coverage_ledger(
        records_db_path=db,
        ledger_path=ledger,
        source_systems=["codex"],
        reading_area_registry_path=registry_path,
        mimocode_root=mimocode_root,
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
    )

    assert result["canonical_session_count"] == 1
    assert result["declared_mimocode_session_count"] == 0
    rows = _read_ledger(ledger)
    assert len(rows) == 1
    assert rows[0]["source_system"] == "codex"
    assert rows[0]["coverage_source"] == "canonical_sessions"
    assert "mimocode" not in json.dumps(rows, ensure_ascii=False)


def test_filtered_mimocode_window_does_not_mark_codex_queue_missing(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, source_system="codex")
    ledger = tmp_path / "coverage.jsonl"
    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger, source_systems=["codex"])

    mimocode_root = tmp_path / "mimocode"
    session_id = "ses_declared_mimo"
    checkpoint = mimocode_root / "memory" / "sessions" / session_id / "checkpoint.md"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("## §1 Active intent\n> catalog push runtime wiring\n", encoding="utf-8")
    registry_path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="mimocode",
        consumer="mimo",
        canonical_window_id=session_id,
        session_id=session_id,
        title="MiMo declared checkpoint",
        path=registry_path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        reading_area="忆凡尘阅读区",
        projects=["time-library"],
        series=["honghuang"],
        path=registry_path,
    )

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=lambda session, model: {"candidates": [], "skip_reason": "no_evidence_bound_candidates"},
        source_systems=["mimocode"],
        reading_area_registry_path=registry_path,
        mimocode_root=mimocode_root,
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
        max_sessions=1,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    rows = _read_ledger(ledger)
    codex = [row for row in rows if row["source_system"] == "codex"][0]
    mimocode = [row for row in rows if row["source_system"] == "mimocode"][0]
    assert result["processed_session_count"] == 1
    assert result["ok"] is False
    assert codex["status"] == "queued"
    assert "skip_reason" not in codex
    assert mimocode["status"] == "skipped"
    assert mimocode["skip_reason"] == "no_evidence_bound_candidates"


def test_mimocode_checkpoint_adapter_projects_sections_with_byte_offsets(tmp_path):
    session_id = "ses_0e69f6457ffevUIqYd3yLfN8BL"
    checkpoint = tmp_path / "checkpoint.md"
    checkpoint_text = (
        "# Session checkpoint\n\n"
        "Topic: catalog push runtime wiring\n\n"
        "## §1 Active intent\n"
        "> \"任务：catalog 开局 push 运行态接线，单焦点。\"\n\n"
        "## §5 Current work\n"
        "已定位 p4_inject catalog endpoint。\n\n"
        "## §7 Discovered knowledge\n"
        "catalog 必须保持轻书单。\n"
    )
    checkpoint.write_text(checkpoint_text, encoding="utf-8")

    messages = adapter.mimocode_checkpoint_messages_for_session(
        {
            "source_system": "mimocode",
            "session_id": session_id,
            "canonical_window_id": session_id,
            "source_path": str(checkpoint),
        }
    )

    assert [item["role"] for item in messages] == ["user", "assistant", "assistant"]
    with checkpoint.open("rb") as f:
        for message in messages:
            f.seek(message["source_offset_start"])
            raw = f.read(message["source_offset_end"] - message["source_offset_start"])
            payload = json.loads(message["payload_json"])
            assert raw.decode("utf-8") == payload["source_line"]["content"]
            assert payload["checkpoint_adapter_contract"] == adapter.MIMOCODE_CHECKPOINT_ADAPTER_CONTRACT


def test_mimocode_checkpoint_adapter_feeds_downstream_distillers_byte_exact(tmp_path, monkeypatch):
    session_id = "ses_0e69f6457ffevUIqYd3yLfN8BL"
    checkpoint = tmp_path / "checkpoint.md"
    checkpoint_text = (
        "# Session checkpoint\n\n"
        "## §1 Active intent\n"
        "> \"任务：catalog 开局 push 运行态接线，单焦点。\"\n\n"
        "## §5 Current work\n"
        "已定位 p4_inject catalog endpoint。\n\n"
        "## §10 Design decisions\n"
        "阅读区只读，raw 不修改。\n"
    )
    checkpoint.write_text(checkpoint_text, encoding="utf-8")
    seen = {"zhiyi": 0, "xingce": 0, "toolbook": 0, "temp_records": []}

    def assert_temp_records_byte_exact(records_db: Path, *, source_system: str, session_id: str) -> None:
        assert source_system == "mimocode"
        assert session_id == "ses_0e69f6457ffevUIqYd3yLfN8BL"
        seen["temp_records"].append(str(records_db))
        con = sqlite3.connect(records_db)
        rows = con.execute(
            """
            select role, source_path, source_offset_start, source_offset_end, payload_json
            from canonical_messages
            order by line_no
            """
        ).fetchall()
        con.close()
        assert [row[0] for row in rows] == ["user", "assistant", "assistant"]
        for _, source_path, start, end, payload_json in rows:
            payload = json.loads(payload_json)
            with Path(source_path).open("rb") as f:
                f.seek(start)
                source_bytes = f.read(end - start)
            assert source_bytes.decode("utf-8") == payload["source_line"]["content"]
            assert payload["checkpoint_adapter_contract"] == adapter.MIMOCODE_CHECKPOINT_ADAPTER_CONTRACT

    class FakeZhiyi:
        INPUT_SOURCE_RAW_USER = "raw_user"

        @staticmethod
        def run_pipeline(root, **kwargs):
            seen["zhiyi"] += 1
            assert kwargs["input_source"] == FakeZhiyi.INPUT_SOURCE_RAW_USER
            assert kwargs["dry_run"] is True
            assert_temp_records_byte_exact(
                Path(kwargs["records_db"]),
                source_system=kwargs["raw_source_system"],
                session_id=kwargs["raw_session_id"],
            )
            return {"owner_sample": [], "steps": {"S3_validate": {"fail_reasons": {}}}}

    class FakeXingce:
        INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

        @staticmethod
        def run_pipeline(root, **kwargs):
            seen["xingce"] += 1
            assert kwargs["input_source"] == FakeXingce.INPUT_SOURCE_CANONICAL_MESSAGES
            assert kwargs["dry_run"] is True
            assert_temp_records_byte_exact(
                Path(kwargs["records_db"]),
                source_system=kwargs["raw_source_system"],
                session_id=kwargs["raw_session_id"],
            )
            return {"candidate_objects": [], "steps": {"S3_validate": {"failure_reasons": {}}}}

    class FakeToolbook:
        INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

        @staticmethod
        def run_pipeline(root, **kwargs):
            seen["toolbook"] += 1
            assert kwargs["input_source"] == FakeToolbook.INPUT_SOURCE_CANONICAL_MESSAGES
            assert kwargs["dry_run"] is True
            assert_temp_records_byte_exact(
                Path(kwargs["records_db"]),
                source_system=kwargs["raw_source_system"],
                session_id=kwargs["raw_session_id"],
            )
            return {"candidate_objects": [], "steps": {"S3_validate": {"fail_reasons": {}}}}

    def fake_loader(name: str):
        if name == "zhiyi_distill":
            return FakeZhiyi
        if name == "xingce_distill":
            return FakeXingce
        if name == "toolbook_distill":
            return FakeToolbook
        raise AssertionError(name)

    monkeypatch.setenv("TIME_LIBRARY_DISTILL_ROOT", str(tmp_path))
    monkeypatch.setattr(adapter, "_load_tool_module", fake_loader)

    result = adapter.distill_session(
        {
            "source_system": "mimocode",
            "session_id": session_id,
            "canonical_window_id": session_id,
            "source_path": str(checkpoint),
        },
        _model(),
    )

    assert result["candidates"] == []
    assert result["skip_reason"] == "no_evidence_bound_candidates"
    assert seen["zhiyi"] == 1
    assert seen["xingce"] == 1
    assert seen["toolbook"] == 0
    assert seen["temp_records"]
    assert all(not Path(path).exists() for path in seen["temp_records"])


def test_runtime_adapter_target_shape_toolbook_runs_only_toolbook(tmp_path, monkeypatch):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="catalog HTTP 端口是 9840。")
    seen = {"toolbook": 0}

    class FailIfCalled:
        INPUT_SOURCE_RAW_USER = "raw_user"
        INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

        @staticmethod
        def run_pipeline(root, **kwargs):
            raise AssertionError("non-toolbook distiller should not run")

    class FakeToolbook:
        INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

        @staticmethod
        def run_pipeline(root, **kwargs):
            seen["toolbook"] += 1
            return {"candidate_objects": [], "steps": {"S3_validate": {"fail_reasons": {}}}}

    def fake_loader(name: str):
        if name == "toolbook_distill":
            return FakeToolbook
        return FailIfCalled

    monkeypatch.setenv("TIME_LIBRARY_DISTILL_ROOT", str(tmp_path))
    monkeypatch.setenv("TIME_LIBRARY_DISTILL_RECORDS_DB", str(db))
    monkeypatch.setattr(adapter, "_load_tool_module", fake_loader)

    result = adapter.distill_session(
        {
            "source_system": "claude_code_cli",
            "session_id": "sess-1",
            "canonical_window_id": "win-1",
            "source_path": str(tmp_path / "raw" / "s1.jsonl"),
        },
        {**_model(), "target_shape": "toolbook"},
    )

    assert seen["toolbook"] == 1
    assert result["candidates"] == []


def test_runtime_adapter_deep_distill_raises_limits_and_runs_xingce_roles(tmp_path, monkeypatch):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="大会话里有监工教义：一致不等于印证。")
    calls: list[tuple[str, dict]] = []

    class FakeZhiyi:
        INPUT_SOURCE_RAW_USER = "raw_user"

        @staticmethod
        def run_pipeline(root, **kwargs):
            calls.append(("zhiyi", kwargs))
            return {"owner_sample": [], "steps": {"S3_validate": {"fail_reasons": {}}}}

    class FakeXingce:
        INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

        @staticmethod
        def run_pipeline(root, **kwargs):
            calls.append(("xingce", kwargs))
            return {"candidate_objects": [], "steps": {"S3_validate": {"failure_reasons": {}}}}

    def fake_loader(name: str):
        if name == "zhiyi_distill":
            return FakeZhiyi
        if name == "xingce_distill":
            return FakeXingce
        raise AssertionError(name)

    monkeypatch.setenv("TIME_LIBRARY_DISTILL_ROOT", str(tmp_path))
    monkeypatch.setenv("TIME_LIBRARY_DISTILL_RECORDS_DB", str(db))
    monkeypatch.delenv("TIME_LIBRARY_DEEP_DISTILL_ZHIYI_PER_SESSION", raising=False)
    monkeypatch.delenv("TIME_LIBRARY_DEEP_DISTILL_XINGCE_PER_ROLE", raising=False)
    monkeypatch.delenv("TIME_LIBRARY_DEEP_DISTILL_RAW_SCAN_LIMIT", raising=False)
    monkeypatch.delenv("TIME_LIBRARY_DEEP_DISTILL_XINGCE_ROLES", raising=False)
    monkeypatch.setattr(adapter, "_load_tool_module", fake_loader)

    result = adapter.distill_session(
        {
            "source_system": "claude_code_cli",
            "session_id": "sess-1",
            "canonical_window_id": "win-1",
            "source_path": str(tmp_path / "raw" / "s1.jsonl"),
        },
        {**_model(), "target_shape": "deep_distill"},
    )

    assert result["candidates"] == []
    assert [name for name, _kwargs in calls] == ["zhiyi", "xingce", "xingce"]
    zhiyi_call = calls[0][1]
    xingce_calls = [kwargs for name, kwargs in calls if name == "xingce"]
    assert zhiyi_call["sample"] == 3
    assert zhiyi_call["model_distill_limit"] == 3
    assert zhiyi_call["raw_scan_limit"] == 5000
    assert {call["raw_role"] for call in xingce_calls} == {"assistant", "user"}
    assert all(call["sample"] == 3 and call["model_distill_limit"] == 3 for call in xingce_calls)
    assert all(call["raw_scan_limit"] == 5000 for call in xingce_calls)


def test_runtime_adapter_mimocode_deep_distill_uses_deep_limits_without_toolbook(tmp_path, monkeypatch):
    session_id = "ses_declared_mimo"
    checkpoint = tmp_path / "checkpoint.md"
    checkpoint.write_text(
        "# Session checkpoint\n\n"
        "## §1 Active intent\n"
        "> 点亮 MiMo lane。\n\n"
        "## §5 Current work\n"
        "正在做阅读区 catalog push runtime wiring。\n\n"
        "## §10 Design decisions\n"
        "阅读区只读，raw 不修改。\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []

    class FakeZhiyi:
        INPUT_SOURCE_RAW_USER = "raw_user"

        @staticmethod
        def run_pipeline(root, **kwargs):
            calls.append(("zhiyi", kwargs))
            return {"owner_sample": [], "steps": {"S3_validate": {"fail_reasons": {}}}}

    class FakeXingce:
        INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

        @staticmethod
        def run_pipeline(root, **kwargs):
            calls.append(("xingce", kwargs))
            return {"candidate_objects": [], "steps": {"S3_validate": {"failure_reasons": {}}}}

    class FailToolbook:
        INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

        @staticmethod
        def run_pipeline(root, **kwargs):
            raise AssertionError("mimocode_deep_distill must not run toolbook")

    def fake_loader(name: str):
        if name == "zhiyi_distill":
            return FakeZhiyi
        if name == "xingce_distill":
            return FakeXingce
        if name == "toolbook_distill":
            return FailToolbook
        raise AssertionError(name)

    monkeypatch.setenv("TIME_LIBRARY_DISTILL_ROOT", str(tmp_path))
    monkeypatch.delenv("TIME_LIBRARY_DEEP_DISTILL_ZHIYI_PER_SESSION", raising=False)
    monkeypatch.delenv("TIME_LIBRARY_DEEP_DISTILL_XINGCE_PER_ROLE", raising=False)
    monkeypatch.delenv("TIME_LIBRARY_DEEP_DISTILL_RAW_SCAN_LIMIT", raising=False)
    monkeypatch.delenv("TIME_LIBRARY_DEEP_DISTILL_XINGCE_ROLES", raising=False)
    monkeypatch.setattr(adapter, "_load_tool_module", fake_loader)

    result = adapter.distill_session(
        {
            "source_system": "mimocode",
            "session_id": session_id,
            "canonical_window_id": session_id,
            "source_path": str(checkpoint),
        },
        {**_model(), "target_shape": "mimocode_deep_distill"},
    )

    assert result["candidates"] == []
    assert [name for name, _kwargs in calls] == ["zhiyi", "xingce", "xingce"]
    zhiyi_call = calls[0][1]
    xingce_calls = [kwargs for name, kwargs in calls if name == "xingce"]
    assert zhiyi_call["sample"] == 3
    assert zhiyi_call["model_distill_limit"] == 3
    assert zhiyi_call["raw_scan_limit"] == 5000
    assert {call["raw_role"] for call in xingce_calls} == {"assistant", "user"}
    assert all(call["raw_source_system"] == "mimocode" for call in xingce_calls)


def test_runner_marks_pending_when_model_config_is_missing(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"

    result = da.run_distill_window(records_db_path=db, ledger_path=ledger, candidate_root=tmp_path)

    assert result["ok"] is False
    assert result["status"] == "pending_model_config"
    rows = _read_ledger(ledger)
    assert rows[0]["status"] == "pending_model_config"
    assert "provider_missing" in rows[0]["model_blockers"]
    assert result["post_window_self_check"]["ok"] is False
    assert "model_config_pending_no_distillation_window" in result["post_window_self_check"]["blockers"]


def test_runner_reports_self_check_when_distiller_is_not_configured(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=None,
    )

    assert result["ok"] is False
    assert result["status"] == "distiller_not_configured"
    assert result["post_window_self_check"]["ok"] is False
    assert "distiller_not_configured_no_distillation_window" in result["post_window_self_check"]["blockers"]


def test_runner_resumes_from_ledger_budget_without_redistilling_covered_sessions(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    _insert_session(db, tmp_path, idx=2)
    ledger = tmp_path / "coverage.jsonl"
    calls: list[str] = []

    def distiller(session, model):
        calls.append(session["session_id"])
        return {"candidates": [_candidate_for(session)]}

    first = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        max_sessions=1,
        self_check_inputs=lambda result: _self_check_for(result["produced_library_ids"]),
    )
    second = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        max_sessions=5,
        self_check_inputs=lambda result: _self_check_for(result["produced_library_ids"]),
    )

    assert first["processed_session_count"] == 1
    assert first["status"] == "budget_exhausted"
    assert second["processed_session_count"] == 1
    assert set(calls) == {"sess-1", "sess-2"}
    assert len(calls) == 2
    rows = _read_ledger(ledger)
    assert {row["status"] for row in rows} == {"covered"}
    assert len(list((tmp_path / "output" / "zhiyi_preference_cards" / "candidates").glob("*.json"))) == 2
    assert second["post_window_self_check"]["ok"] is True


def test_runner_does_not_pass_when_self_check_inputs_are_missing(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        return {"candidates": [_candidate_for(session)]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        max_sessions=1,
    )

    assert result["ok"] is False
    assert result["status"] == "self_check_failed"
    assert result["self_check_inputs_missing"] is True
    assert "grave_one_candidates_not_visible_in_catalog" in result["self_check_blockers"]
    row = _read_ledger(ledger)[0]
    assert row["status"] == "self_check_failed"
    assert row["previous_status"] == "coverage_pending_self_check"
    assert row["library_ids"]

    retry = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        max_sessions=1,
        self_check_inputs=lambda result: _self_check_for(result["produced_library_ids"]),
    )

    assert retry["ok"] is True
    assert _read_ledger(ledger)[0]["status"] == "covered"


def test_pending_model_config_rows_resume_after_model_is_supplied(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"

    pending = da.run_distill_window(records_db_path=db, ledger_path=ledger, candidate_root=tmp_path)

    def distiller(session, model):
        return {"candidates": [_candidate_for(session)]}

    resumed = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda result: _self_check_for(result["produced_library_ids"]),
    )

    assert pending["status"] == "pending_model_config"
    assert resumed["ok"] is True
    assert _read_ledger(ledger)[0]["status"] == "covered"


def test_failed_rows_are_retryable_and_ledger_preserves_existing_outputs(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"
    attempts = {"count": 0}

    def flaky(session, model):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary model outage")
        return {"candidates": [_candidate_for(session)]}

    first = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=flaky,
        self_check_inputs=lambda result: _self_check_for(result["produced_library_ids"]),
    )
    second = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=flaky,
        self_check_inputs=lambda result: _self_check_for(result["produced_library_ids"]),
    )
    before = _read_ledger(ledger)[0]
    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger)
    after = _read_ledger(ledger)[0]

    assert first["failed_session_count"] == 1
    assert second["ok"] is True
    assert before["candidate_ids"] == after["candidate_ids"]
    assert before["library_ids"] == after["library_ids"]


def test_runner_merges_duplicate_experience_across_sessions(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="我喜欢先给结论再给证据")
    _insert_session(db, tmp_path, idx=2, text="以后回答先给结论再给证据")
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        return {"candidates": [_candidate_for(session, dedupe_key="pref:answer-conclusion-first", title="回答先给结论再给证据")]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        max_sessions=10,
        self_check_inputs=lambda result: _self_check_for(result["produced_library_ids"]),
    )

    assert result["produced_candidate_count"] == 1
    assert result["merged_candidate_count"] == 1
    candidates = list((tmp_path / "output" / "zhiyi_preference_cards" / "candidates").glob("*.json"))
    assert len(candidates) == 1
    merged = json.loads(candidates[0].read_text(encoding="utf-8"))
    assert merged["dedupe_merged"] is True
    assert len(merged["coverage_session_keys"]) == 2
    assert len(merged["merged_source_refs"]) == 1


def test_runner_merges_duplicate_evidence_even_when_model_dedupe_key_differs(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = _insert_session(db, tmp_path, idx=1, text="同一段证据：一致不等于印证")
    _insert_session(db, tmp_path, idx=2, text="另一条会话，但模型可能复述同一证据")
    ledger = tmp_path / "coverage.jsonl"
    source_text = source_path.read_text(encoding="utf-8")

    def distiller(session, model):
        candidate = _candidate_for(session, dedupe_key=f"model-key:{session['session_id']}", title=f"模型标题 {session['session_id']}")
        candidate["candidate_id"] = f"zhiyi-auto-evidence-{session['session_id']}"
        candidate["verbatim_excerpt"] = source_text
        candidate["source_refs"]["source_path"] = str(source_path)
        candidate["source_refs"]["byte_offsets"] = {"start": 0, "end": len(source_text.encode("utf-8"))}
        return {"candidates": [candidate]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        max_sessions=2,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    candidates = list((tmp_path / "output" / "zhiyi_preference_cards" / "candidates").glob("*.json"))
    merged = json.loads(candidates[0].read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["produced_candidate_count"] == 1
    assert result["merged_candidate_count"] == 1
    assert len(candidates) == 1
    assert merged["dedupe_merged"] is True
    assert len(merged["coverage_session_keys"]) == 2


def test_runner_avoids_overwriting_distinct_candidates_with_same_candidate_id(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="第一条偏好：一致不等于印证")
    _insert_session(db, tmp_path, idx=2, text="第二条偏好：运行态必须在新码上签")
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        candidate = _candidate_for(session, dedupe_key=f"pref:{session['session_id']}", title=f"偏好 {session['session_id']}")
        candidate["candidate_id"] = "zhiyi-distill-collision"
        return {"candidates": [candidate]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        max_sessions=2,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    rows = _read_ledger(ledger)
    candidates = sorted((tmp_path / "output" / "zhiyi_preference_cards" / "candidates").glob("*.json"))
    candidate_objects = [json.loads(path.read_text(encoding="utf-8")) for path in candidates]

    assert result["ok"] is True
    assert result["produced_candidate_count"] == 2
    assert result["merged_candidate_count"] == 0
    assert len(candidates) == 2
    assert len({item["candidate_id"] for item in candidate_objects}) == 2
    assert {row["status"] for row in rows} == {"covered"}
    assert len({library_id for row in rows for library_id in row["library_ids"]}) == 2


def test_runner_written_candidate_projects_source_metadata_through_catalog_card(tmp_path):
    from src import p4_provider

    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        return {"candidates": [_candidate_for(session)]}

    window = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda result: _self_check_for(result["produced_library_ids"]),
    )
    library_id = window["produced_library_ids"][0]
    card = p4_provider.fetch_catalog_card_by_library_id(library_id, xingce_root=str(tmp_path))

    assert card["ok"] is True
    assert card["source_author"] == "user"
    assert card["source_mode"] == "evidence_bound_model_distill"
    stored = json.loads(next((tmp_path / "output" / "zhiyi_preference_cards" / "candidates").glob("*.json")).read_text(encoding="utf-8"))
    expected_sha = hashlib.sha256(stored["verbatim_excerpt"].encode("utf-8")).hexdigest()
    assert stored["verbatim_sha256"] == expected_sha
    assert stored["source_refs"]["verbatim_sha256"] == expected_sha
    assert card["verbatim_sha256"] == expected_sha
    assert window["user_author_new_card_verbatim_count"] == 1
    assert window["user_author_new_card_verbatims"][0]["library_id"] == library_id
    assert window["user_author_new_card_verbatims"][0]["verbatim_excerpt"] == stored["verbatim_excerpt"]


def test_verbatim_sha256_backfill_fills_exact_candidate_only(tmp_path):
    backfill_mod = importlib.import_module("tools.verbatim_sha256_backfill")
    source_path = tmp_path / "raw" / "source.jsonl"
    source_text = "阅读区只读，raw 也只读。"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(source_text, encoding="utf-8")
    candidates_dir = tmp_path / "output" / "zhiyi_preference_cards" / "candidates"
    candidates_dir.mkdir(parents=True)
    candidate = {
        "candidate_id": "zhiyi-distill-sha-test",
        "candidate_type": "zhiyi_preference_card",
        "library_shelf": "zhiyi",
        "lifecycle_status": "active",
        "title": "阅读区只读",
        "verbatim_excerpt": source_text,
        "source_author": "user",
        "source_role": "user",
        "source_mode": "evidence_bound_model_distill",
        "source_refs": {
            "source_path": str(source_path),
            "source_role": "user",
            "byte_offsets": {"start": 0, "end": len(source_text.encode("utf-8"))},
        },
    }
    path = candidates_dir / "zhiyi-distill-sha-test.json"
    path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")

    report = backfill_mod.backfill(tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))

    expected_sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    assert report["ok"] is True
    assert report["backfilled"] == 1
    assert stored["verbatim_sha256"] == expected_sha
    assert stored["source_refs"]["verbatim_sha256"] == expected_sha


def test_runner_rejects_candidates_without_user_source_author(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        candidate = _candidate_for(session)
        candidate.pop("source_author")
        candidate.pop("source_role")
        candidate["source_refs"].pop("source_role")
        return {"candidates": [candidate]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    row = _read_ledger(ledger)[0]
    assert result["ok"] is False
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "source_author_missing"
    assert not list((tmp_path / "output").glob("**/*.json"))


def test_runner_accepts_assistant_source_author_for_xingce_candidates(tmp_path):
    from src import p4_provider

    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="先核源再签字，避免把转述当运行态证明。")
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        return {"candidates": [_xingce_candidate_for(session)]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    assert result["ok"] is True
    assert result["produced_candidate_count"] == 1
    row = _read_ledger(ledger)[0]
    assert row["status"] == "covered"
    assert list((tmp_path / "output" / "xingce_work_experience" / "candidates").glob("*.json"))
    assert list((tmp_path / "output" / "xingce_work_experience" / "actions").glob("*.jsonl"))
    card = p4_provider.fetch_catalog_card_by_library_id(result["produced_library_ids"][0], xingce_root=str(tmp_path))
    assert card["ok"] is True
    assert card["shelf"] == "xingce"
    assert card["source_author"] == "assistant"
    assert card["source_mode"] == "evidence_bound_model_distill"


def test_runner_accepts_toolbook_p2_extract_candidate_and_catalog_card(tmp_path):
    from src import p4_provider

    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="本机 catalog HTTP 端口是 9840，MCP gateway 端口是 9851。")
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        return {"candidates": [_toolbook_candidate_for(session)]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    assert result["ok"] is True
    assert result["produced_candidate_count"] == 1
    row = _read_ledger(ledger)[0]
    assert row["status"] == "covered"
    candidates = list((tmp_path / "output" / "toolbook_platform_facts" / "candidates").glob("*.json"))
    assert len(candidates) == 1
    stored = json.loads(candidates[0].read_text(encoding="utf-8"))
    assert stored["library_shelf"] == "toolbook"
    assert stored["source_mode"] == "evidence_bound_p2_extract"
    assert stored["byte_offsets"] == {"start": 0, "end": len(stored["verbatim_excerpt"].encode("utf-8"))}
    assert stored["source_ref"] == f"{stored['source_refs']['source_path']}:0-{len(stored['verbatim_excerpt'].encode('utf-8'))}"
    assert stored["source_refs"]["byte_offsets"] == {"start": 0, "end": len(stored["verbatim_excerpt"].encode("utf-8"))}
    assert stored["verbatim_sha256"] == hashlib.sha256(stored["verbatim_excerpt"].encode("utf-8")).hexdigest()

    card = p4_provider.fetch_catalog_card_by_library_id(result["produced_library_ids"][0], xingce_root=str(tmp_path))
    assert card["ok"] is True
    assert card["shelf"] == "toolbook"
    assert card["byte_offsets"] == stored["byte_offsets"]
    assert card["source_ref"] == stored["source_ref"]
    assert card["source_author"] == "assistant"
    assert card["source_mode"] == "evidence_bound_p2_extract"
    assert card["verbatim_excerpt"] == stored["verbatim_excerpt"]
    assert card["raw_source_excerpt"] == stored["verbatim_excerpt"]


def test_runner_rejects_toolbook_noisy_attachment_payload(tmp_path):
    db = _create_records_db(tmp_path)
    text = (
        "# Files mentioned by the user:\n\n"
        "## 4307.PNG: /Users/example/Downloads/4307.PNG\n\n"
        "<image name=[Image #1] path=\"/Users/example/Downloads/4307.PNG\">\n"
        "data:image/png;base64,AAAA\n"
        "</image>\n"
    )
    _insert_session(db, tmp_path, idx=1, text=text)
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        return {"candidates": [_toolbook_candidate_for(session)]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    row = _read_ledger(ledger)[0]
    assert result["rejected_candidate_count"] == 1
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "toolbook_noisy_attachment_payload"
    assert not list((tmp_path / "output" / "toolbook_platform_facts" / "candidates").glob("*.json"))


def test_runner_rejects_toolbook_environment_context_payload(tmp_path):
    db = _create_records_db(tmp_path)
    text = (
        "<environment_context>\n"
        "  <cwd>/Users/example/Documents/Codex/2026-06-18/files-mentioned-by-the-user-4307</cwd>\n"
        "  <shell>zsh</shell>\n"
        "  <current_date>2026-06-18</current_date>\n"
        "  <filesystem><workspace_roots><root>/Users/example/Documents/Codex</root></workspace_roots></filesystem>\n"
        "</environment_context>\n"
    )
    _insert_session(db, tmp_path, idx=1, text=text)
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        return {"candidates": [_toolbook_candidate_for(session)]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    row = _read_ledger(ledger)[0]
    assert result["rejected_candidate_count"] == 1
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "toolbook_noisy_attachment_payload"
    assert not list((tmp_path / "output" / "toolbook_platform_facts" / "candidates").glob("*.json"))


def test_runner_rejects_toolbook_boilerplate_summary(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="MCP 编号借书验收步已经通过，应固化为常设运行手册。")
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        candidate = _toolbook_candidate_for(session)
        candidate["summary"] = "记好了"
        candidate["observed_behavior"] = "记好了"
        candidate["title"] = "工具事实：平台事实 记好了"
        return {"candidates": [candidate]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    row = _read_ledger(ledger)[0]
    assert result["rejected_candidate_count"] == 1
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "toolbook_low_quality_summary"
    assert not list((tmp_path / "output" / "toolbook_platform_facts" / "candidates").glob("*.json"))


def test_runner_rejects_toolbook_one_time_status_report(tmp_path):
    db = _create_records_db(tmp_path)
    text = "这轮收在这:**白页 + MCP 编号借书两半都裸窗签过**；回执和 NonClaims 已落。"
    _insert_session(db, tmp_path, idx=1, text=text)
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        candidate = _toolbook_candidate_for(session)
        candidate["summary"] = text
        candidate["observed_behavior"] = text
        candidate["title"] = "工具事实：平台事实 " + text
        return {"candidates": [candidate]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    row = _read_ledger(ledger)[0]
    assert result["rejected_candidate_count"] == 1
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "toolbook_low_quality_summary"
    assert not list((tmp_path / "output" / "toolbook_platform_facts" / "candidates").glob("*.json"))


def test_runner_rejects_toolbook_tool_result_file_update_echo(tmp_path):
    db = _create_records_db(tmp_path)
    text = (
        '{"type":"user","message":{"content":[{"type":"tool_result",'
        '"content":"The file /Users/me/project/memory.md has been updated successfully. '
        '(file state is current in your context — no need to Read it back)"}]},'
        '"toolUseResult":{"filePath":"/Users/me/project/memory.md"}}'
    )
    _insert_session(db, tmp_path, idx=1, text=text)
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        candidate = _toolbook_candidate_for(session)
        candidate["summary"] = "The file /Users/me/project/memory.md has been updated successfully."
        candidate["observed_behavior"] = candidate["summary"]
        candidate["title"] = "The file /Users/me/project/memory.md has been updated successfully"
        candidate["verbatim_excerpt"] = text
        return {"candidates": [candidate]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    row = _read_ledger(ledger)[0]
    assert result["rejected_candidate_count"] == 1
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "toolbook_low_quality_summary"
    assert not list((tmp_path / "output" / "toolbook_platform_facts" / "candidates").glob("*.json"))


def test_toolbook_distill_rejects_status_report_and_cleans_fact_title(tmp_path):
    spec = importlib.util.spec_from_file_location("toolbook_distill_test_module", ROOT / "tools" / "toolbook_distill.py")
    assert spec and spec.loader
    toolbook_distill = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(toolbook_distill)

    def row_for(text: str, idx: int) -> dict:
        source = tmp_path / f"toolbook-{idx}.jsonl"
        source.write_text(text, encoding="utf-8")
        end = len(text.encode("utf-8"))
        return {
            "message_id": f"m-{idx}",
            "source_system": "codex",
            "session_id": f"s-{idx}",
            "canonical_window_id": f"w-{idx}",
            "project_id": "technical-window",
            "source_path": str(source),
            "raw_path": "",
            "role": "assistant",
            "timestamp": "2026-07-02T00:00:00Z",
            "source_offset_start": 0,
            "source_offset_end": end,
            "raw_offset_start": None,
            "raw_offset_end": None,
            "line_no": 1,
            "content": text,
        }

    status_text = "这轮收在这:**白页 + MCP 编号借书两半都裸窗签过**；回执、NonClaims、BYTE-EXACT 已落。"
    assert toolbook_distill._candidate_from_row(row_for(status_text, 1)) is None

    top_keys_dump = "=== top-level keys ===\nactive_layers_used\nagent_boundary\nconsumer_receipt\nitems"
    assert toolbook_distill._candidate_from_row(row_for(top_keys_dump, 11)) is None

    css_fragment = "box-shadow: 0 4px 24px rgba(59, 130, 246, 0.08);"
    assert toolbook_distill._candidate_from_row(row_for(css_fragment, 12)) is None

    tool_echo = (
        '{"type":"tool_result","content":"The file /Users/me/project.md has been updated successfully. '
        '(file state is current in your context — no need to Read it back)"}'
    )
    assert toolbook_distill._candidate_from_row(row_for(tool_echo, 13)) is None

    fact_text = "最简单官方方案：**macOS 装 Microsoft 的 Windows App，用 RDP 连 Windows**。"
    candidate = toolbook_distill._candidate_from_row(row_for(fact_text, 2))
    assert candidate is not None
    assert candidate["title"] == "macOS 用 Microsoft Windows App 连远程桌面"
    assert candidate["fact_type"] == "platform_fact"
    assert candidate["verbatim_excerpt"] == fact_text

    codex_fact = "Codex CLI 用 codex exec 运行，配置路径是 /Users/me/.codex/config.toml。"
    codex_candidate = toolbook_distill._candidate_from_row(row_for(codex_fact, 3))
    assert codex_candidate is not None
    assert "config.toml" in codex_candidate["title"]

    windows_app_path = "Microsoft Windows App 的日志路径是 /Users/me/Library/Logs/Windows App/app.log。"
    path_candidate = toolbook_distill._candidate_from_row(row_for(windows_app_path, 4))
    assert path_candidate is not None
    assert path_candidate["title"] != "macOS 用 Microsoft Windows App 连远程桌面"
    assert "日志路径" in path_candidate["title"]


def test_runner_merges_duplicate_toolbook_fact_across_sessions(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="catalog HTTP 端口是 9840。")
    _insert_session(db, tmp_path, idx=2, text="catalog HTTP 端口仍是 9840。")
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        return {"candidates": [_toolbook_candidate_for(session, dedupe_key="toolbook:catalog-http-port-9840")]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        max_sessions=2,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    candidates = list((tmp_path / "output" / "toolbook_platform_facts" / "candidates").glob("*.json"))
    stored = json.loads(candidates[0].read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["produced_candidate_count"] == 1
    assert result["merged_candidate_count"] == 1
    assert len(candidates) == 1
    assert stored["dedupe_merged"] is True
    assert len(stored["coverage_session_keys"]) == 2
    assert len(stored["merged_source_refs"]) == 1


def test_toolbook_target_shape_uses_side_status_without_rewriting_main_coverage(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="本机 catalog HTTP 端口是 9840。")
    ledger = tmp_path / "coverage.jsonl"

    da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=lambda session, model: {"candidates": [_candidate_for(session)]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )
    before = _read_ledger(ledger)[0]
    assert before["status"] == "covered"
    assert "toolbook_status" not in before

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "toolbook"},
        distill_session=lambda session, model: {"candidates": [_toolbook_candidate_for(session)]},
        target_shape="toolbook",
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    row = _read_ledger(ledger)[0]
    assert result["ok"] is True
    assert result["target_shape"] == "toolbook"
    assert result["ledger_status_key"] == "toolbook_status"
    assert row["status"] == "covered"
    assert row["toolbook_status"] == "covered"
    assert row["library_ids"]
    assert row["toolbook_library_ids"]
    assert row["library_ids"] != row["toolbook_library_ids"]


def test_project_history_target_shape_writes_registry_history_not_candidate_shelf(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = _insert_session(db, tmp_path, idx=1, text="用户裁定：白板历史从蒸馏补到项目页 history。")
    ledger = tmp_path / "coverage.jsonl"
    registry_path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="claude_code_cli",
        consumer="claude_code_cli",
        canonical_window_id="win-1",
        session_id="sess-1",
        path=registry_path,
    )["card"]
    membership = registry.declare_membership(
        card_id=card["card_id"],
        projects=["忆凡尘"],
        series=["洪荒世界"],
        path=registry_path,
    )

    da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=lambda session, model: {"candidates": [_candidate_for(session)]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
        reading_area_registry_path=registry_path,
    )
    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "project_history_digest"},
        distill_session=lambda session, model: {"candidates": [_project_history_candidate_for(session)]},
        target_shape="project_history_digest",
        self_check_inputs=lambda window: _project_history_self_check_for(window["produced_project_history_ids"]),
        reading_area_registry_path=registry_path,
    )

    assert source_path.exists()
    assert result["ok"] is True
    assert result["target_shape"] == "project_history_digest"
    assert result["ledger_status_key"] == "project_history_digest_status"
    assert result["produced_project_history_ids"][0].startswith("PH-")
    saved = registry.load_registry(registry_path)
    assert len(saved["project_history_records"]) == 1
    assert saved["project_history_records"][0]["declared_project_ids"] == membership["project_ids"]
    assert not (tmp_path / "output" / "project_history_digest").exists()
    row = _read_ledger(ledger)[0]
    assert row["status"] == "covered"
    assert row["project_history_digest_status"] == "covered"
    assert row["project_history_digest_library_ids"] == result["produced_project_history_ids"]


def test_project_history_target_shape_materializes_temp_source_ref(tmp_path):
    db = _create_records_db(tmp_path)
    temp_root = tmp_path / "var" / "folders" / "history-run"
    source_path = _insert_session(
        db,
        temp_root,
        idx=1,
        text="用户裁定：项目史不能把临时文件当长期证据源。",
    )
    ledger = tmp_path / "coverage.jsonl"
    registry_path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="claude_code_cli",
        consumer="claude_code_cli",
        canonical_window_id="win-1",
        session_id="sess-1",
        path=registry_path,
    )["card"]
    registry.declare_membership(
        card_id=card["card_id"],
        projects=["忆凡尘"],
        series=["洪荒世界"],
        path=registry_path,
    )
    da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=lambda session, model: {"candidates": [_candidate_for(session)]},
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
        reading_area_registry_path=registry_path,
    )

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config={**_model(), "target_shape": "project_history_digest"},
        distill_session=lambda session, model: {"candidates": [_project_history_candidate_for(session)]},
        target_shape="project_history_digest",
        self_check_inputs=lambda window: _project_history_self_check_for(window["produced_project_history_ids"]),
        reading_area_registry_path=registry_path,
    )

    assert result["ok"] is True
    saved = registry.load_registry(registry_path)
    record = saved["project_history_records"][0]
    archived_ref = record["source_ref"]
    assert archived_ref["source_path"] != str(source_path)
    assert str(temp_root) not in archived_ref["source_path"]
    assert "/output/project_history_evidence/slices/" in archived_ref["source_path"]
    assert archived_ref["source_persistence"] == "durable_project_history_evidence_archive"
    assert archived_ref["original_source_ref"]["source_path"] == str(source_path)
    assert Path(archived_ref["source_path"]).read_text(encoding="utf-8") == record["verbatim_excerpt"]


def test_project_history_self_check_requires_project_page_visible_and_borrowable():
    result = da.run_project_history_window_self_check(
        {"target_shape": "project_history_digest", "produced_project_history_ids": ["PH-1"]},
        project_history_record_ids=["PH-1"],
        project_page_history_ids=["PH-1"],
        borrow_results={"PH-1": {"ok": True, "raw_source_excerpt": "source"}},
        instructions_char_count=900,
        contains_body_markers=False,
    )

    assert result["ok"] is True
    assert result["grave_one_output_visible"] is True
    assert result["grave_two_delivery_borrowable"] is True

    missing = da.run_project_history_window_self_check(
        {"target_shape": "project_history_digest", "produced_project_history_ids": ["PH-2"]},
        project_history_record_ids=["PH-2"],
        project_page_history_ids=[],
        borrow_results={"PH-2": {"ok": True, "raw_source_excerpt": "source"}},
        instructions_char_count=900,
        contains_body_markers=False,
    )

    assert missing["ok"] is False
    assert "project_history_not_visible_in_project_page" in missing["blockers"]

    empty = da.run_project_history_window_self_check(
        {"target_shape": "project_history_digest", "processed_session_count": 1, "produced_project_history_ids": []},
        project_history_record_ids=[],
        project_page_history_ids=[],
        borrow_results={},
        instructions_char_count=900,
        contains_body_markers=False,
    )

    assert empty["ok"] is False
    assert "project_history_empty_window_no_digest" in empty["blockers"]


def test_runtime_adapter_target_shape_project_history_runs_only_history(tmp_path, monkeypatch):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1, text="用户裁定：历史从蒸馏补。")
    seen = {"history": 0}

    class FailIfCalled:
        INPUT_SOURCE_RAW_USER = "raw_user"
        INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

        @staticmethod
        def run_pipeline(root, **kwargs):
            raise AssertionError("non-history distiller should not run")

    class FakeHistory:
        INPUT_SOURCE_CANONICAL_MESSAGES = "canonical_messages"

        @staticmethod
        def run_pipeline(root, **kwargs):
            seen["history"] += 1
            return {"candidate_objects": [], "steps": {"S3_validate": {"fail_reasons": {}}}}

    def fake_loader(name: str):
        if name == "project_history_distill":
            return FakeHistory
        return FailIfCalled

    monkeypatch.setenv("TIME_LIBRARY_DISTILL_ROOT", str(tmp_path))
    monkeypatch.setenv("TIME_LIBRARY_DISTILL_RECORDS_DB", str(db))
    monkeypatch.setattr(adapter, "_load_tool_module", fake_loader)

    result = adapter.distill_session(
        {
            "source_system": "claude_code_cli",
            "session_id": "sess-1",
            "canonical_window_id": "win-1",
            "source_path": str(tmp_path / "raw" / "s1.jsonl"),
        },
        {**_model(), "target_shape": "project_history_digest"},
    )

    assert seen["history"] == 1
    assert result["candidates"] == []


def test_runtime_adapter_project_history_uses_real_tool_and_records_db_env(tmp_path, monkeypatch):
    db = tmp_path / "records.db"
    source = tmp_path / "raw" / "history.jsonl"
    text = "  【想象者拍板】白板历史从蒸馏补到项目页 history。\n"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                source_path text,
                raw_path text,
                role text,
                timestamp text,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                line_no integer,
                content_preview text,
                payload_json text
            )
            """
        )
        conn.execute(
            "insert into canonical_messages values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "msg-real-history-1",
                "codex",
                "sess-real-history",
                "win-real-history",
                "technical-window-id",
                str(source),
                "",
                "user",
                "2026-07-03T00:00:00Z",
                0,
                len(text.encode("utf-8")),
                None,
                None,
                1,
                text,
                json.dumps({"source_line": {"content": text}}, ensure_ascii=False),
            ),
        )
    monkeypatch.setenv("TIME_LIBRARY_DISTILL_ROOT", str(ROOT))
    monkeypatch.setenv("TIME_LIBRARY_DISTILL_RECORDS_DB", str(db))

    result = adapter.distill_session(
        {
            "source_system": "codex",
            "session_id": "sess-real-history",
            "canonical_window_id": "win-real-history",
            "source_path": str(source),
        },
        {**_model(), "target_shape": "project_history_digest"},
    )

    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["candidate_type"] == "project_history_digest"
    assert candidate["verbatim_excerpt"] == text
    assert candidate["verbatim_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_project_history_distill_tool_emits_byte_exact_candidate(tmp_path):
    tool_path = ROOT / "tools" / "project_history_distill.py"
    spec = importlib.util.spec_from_file_location("project_history_distill_test_module", tool_path)
    assert spec and spec.loader
    project_history = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project_history)

    db = tmp_path / "records.db"
    source = tmp_path / "raw" / "history.jsonl"
    text = "  【想象者拍板】白板历史从蒸馏补到项目页 history。\n"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            create table canonical_messages (
                message_id text,
                source_system text,
                session_id text,
                canonical_window_id text,
                project_id text,
                source_path text,
                raw_path text,
                role text,
                timestamp text,
                source_offset_start integer,
                source_offset_end integer,
                raw_offset_start integer,
                raw_offset_end integer,
                line_no integer,
                content_preview text,
                payload_json text
            )
            """
        )
        conn.execute(
            "insert into canonical_messages values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "msg-history-1",
                "codex",
                "sess-history",
                "win-history",
                "technical-window-id",
                str(source),
                "",
                "user",
                "2026-07-03T00:00:00Z",
                0,
                len(text.encode("utf-8")),
                None,
                None,
                1,
                text,
                json.dumps({"source_line": {"content": text}}, ensure_ascii=False),
            ),
        )

    report = project_history.run_pipeline(
        tmp_path,
        records_db=db,
        raw_source_system="codex",
        raw_session_id="sess-history",
        model_distill_limit=1,
    )

    assert report["ok"] is True
    candidate = report["candidate_objects"][0]
    assert candidate["candidate_type"] == "project_history_digest"
    assert candidate["history_type"] == "decision"
    assert candidate["verbatim_excerpt"] == text
    assert candidate["verbatim_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert candidate["source_refs"]["byte_offsets"] == {"start": 0, "end": len(text.encode("utf-8"))}
    assert candidate["source_refs"]["source_author"] == "user"


def test_runner_rejects_candidates_with_unreadable_source_ref(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"

    def distiller(session, model):
        candidate = _candidate_for(session)
        candidate["source_refs"]["source_path"] = str(tmp_path / "missing.jsonl")
        return {"candidates": [candidate]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    row = _read_ledger(ledger)[0]
    assert result["ok"] is False
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "source_path_unreadable"


def test_runner_keeps_ledger_pending_until_self_check_passes(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"
    observed_statuses: list[str] = []

    def distiller(session, model):
        return {"candidates": [_candidate_for(session)]}

    def self_check_payload(result):
        observed_statuses.append(_read_ledger(ledger)[0]["status"])
        return _self_check_for(result["produced_library_ids"])

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=self_check_payload,
    )

    assert result["ok"] is True
    assert observed_statuses == ["coverage_pending_self_check"]
    assert _read_ledger(ledger)[0]["status"] == "covered"


def test_empty_window_with_false_negative_samples_can_continue(tmp_path):
    db = _create_records_db(tmp_path)
    for idx in range(1, 4):
        _insert_session(db, tmp_path, idx=idx, text=f"探针残渣 {idx}，没有可复用经验")
    ledger = tmp_path / "coverage.jsonl"

    def no_candidate_distiller(session, model):
        return {
            "candidates": [],
            "reports": [
                {
                    "shelf": "xingce",
                    "input_records": 1,
                    "candidate_object_count": 0,
                    "owner_sample_count": 0,
                    "steps": {
                        "S0_select": {"worthy": 1, "rejected": 0},
                        "S2_distill": {"cards": 0},
                        "S3_validate": {"passed": 0, "fail_reasons": {}},
                    },
                }
            ],
        }

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=no_candidate_distiller,
        max_sessions=3,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    assert result["ok"] is True
    assert result["produced_candidate_count"] == 0
    assert result["post_window_self_check"]["empty_window"] is True
    assert result["post_window_self_check"]["empty_window_receipt_visible"] is True
    assert result["post_window_self_check"]["empty_window_skip_sample_count"] == 3
    assert {row["status"] for row in _read_ledger(ledger)} == {"skipped"}


def test_runner_does_not_merge_into_corrupted_existing_candidate(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"
    corrupt_dir = tmp_path / "output" / "zhiyi_preference_cards" / "candidates"
    corrupt_dir.mkdir(parents=True)
    corrupt_path = corrupt_dir / "corrupt.json"
    corrupt_path.write_text(
        json.dumps(
            {
                "candidate_id": "corrupt",
                "library_shelf": "zhiyi",
                "title": "回答先给结论再给证据",
                "preference_statement": "回答先给结论再给证据",
                "dedupe_key": "pref:answer-conclusion-first",
                "source_mode": "distill_heuristic",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def distiller(session, model):
        return {"candidates": [_candidate_for(session, dedupe_key="pref:answer-conclusion-first", title="回答先给结论再给证据")]}

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        self_check_inputs=lambda window: _self_check_for(window["produced_library_ids"]),
    )

    candidates = sorted(corrupt_dir.glob("*.json"))
    assert result["ok"] is True
    assert result["produced_candidate_count"] == 1
    assert result["merged_candidate_count"] == 0
    assert len(candidates) == 2
    assert "dedupe_merged" not in json.loads(corrupt_path.read_text(encoding="utf-8"))


def test_nightly_schedule_plan_supports_window_and_manual_override():
    outside = da.build_nightly_schedule_plan(now=datetime(2026, 7, 2, 12, 0))
    inside = da.build_nightly_schedule_plan(now=datetime(2026, 7, 2, 2, 0))
    manual = da.build_nightly_schedule_plan(now=datetime(2026, 7, 2, 12, 0), manual=True)
    overnight = da.build_nightly_schedule_plan({"start": "23:00", "end": "03:00"}, now=datetime(2026, 7, 2, 2, 0))

    assert outside["should_run"] is False
    assert inside["should_run"] is True
    assert manual["should_run"] is True
    assert manual["mode"] == "manual_now"
    assert overnight["should_run"] is True
    assert overnight["is_overnight_window"] is True
    assert overnight["window_semantics"] == "[start,end)"


def test_nightly_schedule_plan_rejects_invalid_or_zero_length_window():
    invalid = da.build_nightly_schedule_plan({"start": "24:00", "end": "03:00"}, now=datetime(2026, 7, 2, 2, 0))
    zero = da.build_nightly_schedule_plan({"start": "01:00", "end": "01:00"}, now=datetime(2026, 7, 2, 1, 0))

    assert invalid["ok"] is False
    assert "window_start_invalid_hhmm" in invalid["blockers"]
    assert zero["ok"] is False
    assert "window_start_equals_end" in zero["blockers"]


def test_scheduler_registration_plan_is_plan_only_and_requires_authorization():
    plan = da.build_scheduler_registration_plan({"repo_root": "/tmp/time-library", "source_systems": ["claude_code_cli"]})
    ready = da.build_scheduler_registration_plan(
        {
            "repo_root": "/tmp/time-library",
            "distiller_callable": "distillers.default:distill_session",
            "self_check_json": "/tmp/self-check.json",
        }
    )

    assert plan["ok"] is True
    assert plan["mode"] == "scheduler_registration_plan"
    assert plan["write_performed"] is False
    assert plan["requires_installed_authorization"] is True
    assert plan["ready_to_install"] is False
    assert "distiller_callable_required_before_install" in plan["blockers_before_install"]
    assert "not_installed" in plan["non_claims"]
    assert "run-window" in plan["command"]
    assert "--source-system" in plan["command"]
    assert ready["ready_to_install"] is True
    assert "--distiller-callable" in ready["command"]
    assert "--self-check-json" in ready["command"]


def test_distill_automation_cli_reconcile_and_schedule_plan(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"
    tool = Path(__file__).resolve().parents[1] / "tools" / "distill_automation.py"

    reconcile = subprocess.run(
        [sys.executable, str(tool), "--root", str(tmp_path), "--records-db", str(db), "--ledger", str(ledger), "reconcile"],
        text=True,
        capture_output=True,
        check=True,
    )
    schedule = subprocess.run(
        [sys.executable, str(tool), "schedule-plan", "--now", "2026-07-02T02:00:00"],
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(reconcile.stdout)["ledger_row_count"] == 1
    assert json.loads(schedule.stdout)["should_run"] is True


def test_distill_automation_cli_scheduler_registration_plan(tmp_path):
    tool = Path(__file__).resolve().parents[1] / "tools" / "distill_automation.py"

    result = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--root",
            str(tmp_path),
            "scheduler-registration-plan",
            "--source-system",
            "claude_code_cli",
            "--distiller-callable",
            "distillers.default:distill_session",
            "--self-check-json",
            str(tmp_path / "self-check.json"),
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["write_performed"] is False
    assert payload["requires_installed_authorization"] is True
    assert payload["ready_to_install"] is True
    assert "claude_code_cli" in payload["command"]


def test_distill_automation_cli_run_window_with_fixture_candidate_and_self_check(tmp_path):
    db = _create_records_db(tmp_path)
    raw_path = _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"
    session = da.load_canonical_sessions(db)[0]
    candidate = _candidate_for(session)
    candidate.setdefault("_type", "zhiyi_preference_card")
    candidate.setdefault("type", "preference_memory")
    candidate.setdefault("exp_id", candidate.get("candidate_id"))
    fixture = tmp_path / "candidate.json"
    fixture.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
    library_id = library_id_for(candidate)
    self_check = tmp_path / "self-check.json"
    self_check.write_text(
        json.dumps(
            {
                "catalog_library_ids": [library_id],
                "borrow_results": {library_id: {"ok": True, "verbatim_excerpt": raw_path.read_text(encoding="utf-8")}},
                "instructions_char_count": 766,
                "contains_body_markers": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tool = Path(__file__).resolve().parents[1] / "tools" / "distill_automation.py"

    result = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--root",
            str(tmp_path),
            "--records-db",
            str(db),
            "--ledger",
            str(ledger),
            "run-window",
            "--provider",
            "local",
            "--model",
            "fixture",
            "--fixture-candidate-json",
            str(fixture),
            "--self-check-json",
            str(self_check),
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["produced_library_ids"] == [library_id]
    assert _read_ledger(ledger)[0]["status"] == "covered"


def test_distill_automation_cli_run_window_without_model_is_pending(tmp_path):
    db = _create_records_db(tmp_path)
    _insert_session(db, tmp_path, idx=1)
    ledger = tmp_path / "coverage.jsonl"
    tool = Path(__file__).resolve().parents[1] / "tools" / "distill_automation.py"

    result = subprocess.run(
        [sys.executable, str(tool), "--root", str(tmp_path), "--records-db", str(db), "--ledger", str(ledger), "run-window"],
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["status"] == "pending_model_config"


def test_two_grave_self_check_blocks_empty_invisible_and_unborrowable_windows():
    empty = da.run_window_self_check(
        {"produced_library_ids": [], "processed_session_count": 1},
        catalog_library_ids=[],
        borrow_results={},
        instructions_char_count=700,
        contains_body_markers=False,
    )
    invisible = da.run_window_self_check(
        {"produced_library_ids": ["ZX-ZHIYI-1"]},
        catalog_library_ids=[],
        borrow_results={"ZX-ZHIYI-1": {"ok": True, "verbatim_excerpt": "source"}},
        instructions_char_count=700,
        contains_body_markers=False,
    )
    unborrowable = da.run_window_self_check(
        {"produced_library_ids": ["ZX-ZHIYI-1"]},
        catalog_library_ids=["ZX-ZHIYI-1"],
        borrow_results={"ZX-ZHIYI-1": {"ok": True, "verbatim_excerpt": ""}},
        instructions_char_count=700,
        contains_body_markers=False,
    )

    assert empty["ok"] is False
    assert "grave_one_empty_window_no_true_cards" in empty["blockers"]
    assert "empty_window_false_negative_samples_missing" in empty["blockers"]
    assert invisible["ok"] is False
    assert "grave_one_candidates_not_visible_in_catalog" in invisible["blockers"]
    assert unborrowable["ok"] is False
    assert "grave_two_new_cards_not_borrowable" in unborrowable["blockers"]


def test_two_grave_self_check_allows_sampled_empty_window():
    samples = [
        {"session_key": "s1", "skip_reason": "no_evidence_bound_candidates", "false_negative_found": False},
        {"session_key": "s2", "skip_reason": "no_evidence_bound_candidates", "false_negative_found": False},
        {"session_key": "s3", "skip_reason": "no_evidence_bound_candidates", "false_negative_found": False},
    ]

    result = da.run_window_self_check(
        {
            "produced_library_ids": [],
            "processed_session_count": 3,
            "skip_reason_counts": {"no_evidence_bound_candidates": 3},
            "empty_window_skip_samples": samples,
        },
        catalog_library_ids=[],
        borrow_results={},
        instructions_char_count=700,
        contains_body_markers=False,
    )

    assert result["ok"] is True
    assert result["empty_window_receipt_visible"] is True
    assert result["empty_window_auto_continue_allowed"] is True
    assert result["empty_window_skip_sample_count"] == 3


def test_two_grave_self_check_allows_terminal_no_queue_window():
    result = da.run_window_self_check(
        {
            "status": "window_complete",
            "produced_library_ids": [],
            "processed_session_count": 0,
        },
        catalog_library_ids=["ZX-TOOL-C05355162B"],
        borrow_results={},
        instructions_char_count=700,
        contains_body_markers=False,
    )

    assert result["ok"] is True
    assert result["terminal_no_queue_window"] is True
    assert result["empty_window"] is False
    assert result["blockers"] == []


def test_two_grave_self_check_blocks_consecutive_empty_window_with_true_leak():
    samples = [
        {"session_key": "s1", "skip_reason": "no_evidence_bound_candidates", "false_negative_found": True},
        {"session_key": "s2", "skip_reason": "no_evidence_bound_candidates", "false_negative_found": False},
        {"session_key": "s3", "skip_reason": "no_evidence_bound_candidates", "false_negative_found": False},
    ]

    result = da.run_window_self_check(
        {
            "produced_library_ids": [],
            "processed_session_count": 3,
            "skip_reason_counts": {"no_evidence_bound_candidates": 3},
            "empty_window_skip_samples": samples,
            "consecutive_empty_window_count": 2,
        },
        catalog_library_ids=[],
        borrow_results={},
        instructions_char_count=700,
        contains_body_markers=False,
    )

    assert result["ok"] is False
    assert "empty_window_false_negative_found_after_consecutive_empty_windows" in result["blockers"]


def test_two_grave_self_check_blocks_empty_window_with_error_skips():
    samples = [
        {"session_key": "s1", "skip_reason": "no_evidence_bound_candidates", "false_negative_found": False},
        {"session_key": "s2", "skip_reason": "no_evidence_bound_candidates", "false_negative_found": False},
        {"session_key": "s3", "skip_reason": "no_evidence_bound_candidates", "false_negative_found": False},
    ]

    result = da.run_window_self_check(
        {
            "produced_library_ids": [],
            "processed_session_count": 4,
            "skip_reason_counts": {"no_evidence_bound_candidates": 3, "model_json_parse_error": 1},
            "empty_window_skip_samples": samples,
        },
        catalog_library_ids=[],
        borrow_results={},
        instructions_char_count=700,
        contains_body_markers=False,
    )

    assert result["ok"] is False
    assert "empty_window_non_no_evidence_skip_reasons" in result["blockers"]


def test_two_grave_self_check_passes_when_new_cards_visible_and_borrowable():
    result = da.run_window_self_check(
        {"produced_library_ids": ["ZX-ZHIYI-1"]},
        catalog_library_ids=["ZX-ZHIYI-1", "ZX-RAW-1"],
        borrow_results={"ZX-ZHIYI-1": {"ok": True, "raw_source_excerpt": "source"}},
        instructions_char_count=766,
        contains_body_markers=False,
    )

    assert result["ok"] is True
    assert result["grave_one_output_visible"] is True
    assert result["grave_two_delivery_borrowable"] is True


def test_relay_voiceprint_classifier_keeps_short_user_preference_direct():
    voiceprint = importlib.import_module("src.relay_voiceprint")
    candidate = {
        "candidate_type": "zhiyi_preference_card",
        "library_shelf": "zhiyi",
        "source_author": "user",
        "source_role": "user",
        "verbatim_excerpt": "不要用 yifanchen 这类拼音拼接式称呼",
    }

    annotation = voiceprint.classify_candidate(candidate)

    assert annotation["evidence_attribution"] == "direct_user"
    assert annotation["user_relayed"] is False


def test_relay_voiceprint_merge_preserves_stored_annotation_without_reclassifying():
    voiceprint = importlib.import_module("src.relay_voiceprint")
    candidate = {
        "candidate_type": "zhiyi_preference_card",
        "library_shelf": "zhiyi",
        "source_author": "user",
        "source_role": "user",
        "verbatim_excerpt": "一致≠印证，我上机独立量。Opus 二签 opus_confirmed，BYTE-EXACT + SHA-MATCH。",
        "evidence_attribution": "direct_user",
        "relay_voiceprint": {
            "contract": "time_library_user_relayed_voiceprint.v1",
            "evidence_attribution": "direct_user",
            "user_relayed": False,
            "risk_level": "owner_adjudicated_direct",
            "reasons": ["owner_adjudication"],
            "score": 0,
        },
    }

    merged = voiceprint.merge_annotation(candidate)

    assert merged["evidence_attribution"] == "direct_user"
    assert merged["relay_voiceprint"]["risk_level"] == "owner_adjudicated_direct"
    assert merged["relay_voiceprint"]["reasons"] == ["owner_adjudication"]


def test_relay_voiceprint_marks_816_adjudication_anchor_as_relayed():
    voiceprint = importlib.import_module("src.relay_voiceprint")
    candidate = {
        "candidate_type": "zhiyi_preference_card",
        "library_shelf": "zhiyi",
        "source_author": "user",
        "source_role": "user",
        "verbatim_excerpt": "一致≠印证，我上机独立量",
    }

    annotation = voiceprint.classify_candidate(candidate)

    assert annotation["evidence_attribution"] == "user_relayed"
    assert "known_relayed_verification_voice" in annotation["reasons"]


def test_distill_window_marks_user_relayed_candidate_without_blocking(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = _insert_session(
        db,
        tmp_path,
        idx=1,
        text="一致≠印证，我上机独立量。Opus 二签 opus_confirmed，BYTE-EXACT + SHA-MATCH。",
    )
    ledger = tmp_path / "coverage.jsonl"
    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger, source_systems=["claude_code_cli"])

    def distiller(session, model):
        text = Path(session["source_path"]).read_text(encoding="utf-8")
        raw = text.encode("utf-8")
        return {
            "candidates": [{
                "candidate_id": "zhiyi-relayed-auto",
                "candidate_type": "zhiyi_preference_card",
                "library_shelf": "zhiyi",
                "lifecycle_status": "active",
                "title": "一致不等于印证",
                "summary": "一致不等于印证",
                "preference_statement": "一致不等于印证",
                "when_to_use": "报告一致但未独立验牌时",
                "verbatim_excerpt": text,
                "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
                "source_author": "user",
                "source_role": "user",
                "source_mode": "evidence_bound_model_distill",
                "source_refs": {
                    "source_system": session["source_system"],
                    "source_path": str(source_path),
                    "source_author": "user",
                    "source_role": "user",
                    "byte_offsets": {"start": 0, "end": len(raw)},
                    "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
                },
            }]
        }

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        source_systems=["claude_code_cli"],
        self_check_inputs=_self_check_for([]),
    )
    stored = json.loads(next((tmp_path / "output" / "zhiyi_preference_cards" / "candidates").glob("*.json")).read_text(encoding="utf-8"))

    assert result["produced_candidate_count"] == 1
    assert stored["evidence_attribution"] == "user_relayed"
    assert stored["relay_voiceprint"]["user_relayed"] is True
    assert "report_or_signoff_marker" in stored["relay_voiceprint"]["reasons"]


def test_distill_window_keeps_direct_user_candidate_direct(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = _insert_session(
        db,
        tmp_path,
        idx=1,
        text="不要用 yifanchen 这类拼音拼接式称呼",
    )
    ledger = tmp_path / "coverage.jsonl"
    da.reconcile_coverage_ledger(records_db_path=db, ledger_path=ledger, source_systems=["claude_code_cli"])

    def distiller(session, model):
        text = Path(session["source_path"]).read_text(encoding="utf-8")
        raw = text.encode("utf-8")
        return {
            "candidates": [{
                "candidate_id": "zhiyi-direct-auto",
                "candidate_type": "zhiyi_preference_card",
                "library_shelf": "zhiyi",
                "lifecycle_status": "active",
                "title": "不要用拼音拼接式称呼",
                "summary": "不要用拼音拼接式称呼",
                "preference_statement": "不要用拼音拼接式称呼",
                "when_to_use": "命名或引用产品名时",
                "verbatim_excerpt": text,
                "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
                "source_author": "user",
                "source_role": "user",
                "source_mode": "evidence_bound_model_distill",
                "source_refs": {
                    "source_system": session["source_system"],
                    "source_path": str(source_path),
                    "source_author": "user",
                    "source_role": "user",
                    "byte_offsets": {"start": 0, "end": len(raw)},
                    "verbatim_sha256": hashlib.sha256(raw).hexdigest(),
                },
            }]
        }

    result = da.run_distill_window(
        records_db_path=db,
        ledger_path=ledger,
        candidate_root=tmp_path,
        model_config=_model(),
        distill_session=distiller,
        source_systems=["claude_code_cli"],
        self_check_inputs=_self_check_for([]),
    )
    stored = json.loads(next((tmp_path / "output" / "zhiyi_preference_cards" / "candidates").glob("*.json")).read_text(encoding="utf-8"))

    assert result["produced_candidate_count"] == 1
    assert stored["evidence_attribution"] == "direct_user"
    assert stored["relay_voiceprint"]["user_relayed"] is False
