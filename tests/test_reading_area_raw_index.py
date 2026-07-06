import json
import sqlite3
from pathlib import Path

from src import reading_area_raw_index
from src import reading_area_registry as registry


def _create_records_db(path: Path) -> Path:
    db = path / "records.db"
    con = sqlite3.connect(db)
    con.execute(
        """
        create table canonical_sessions (
            record_id text primary key,
            source_system text not null,
            session_id text,
            raw_artifact_id text,
            canonical_window_id text,
            project_id text,
            project_root text,
            thread_name text,
            source_path text,
            raw_path text,
            source_mtime text,
            raw_mtime text,
            source_size_bytes integer,
            raw_size_bytes integer,
            source_line_count integer,
            raw_line_count integer,
            indexed_message_count integer,
            indexed_chunk_count integer,
            raw_indexed_message_count integer,
            raw_offset_coverage_count integer,
            bad_json_line_count integer,
            oversized_line_count integer,
            index_status text,
            updated_at text,
            payload_json text
        )
        """
    )
    con.execute(
        """
        create table canonical_messages (
            message_id text primary key,
            record_id text not null,
            source_system text not null,
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
            content_chars integer,
            content_hash text,
            line_hash text,
            content_preview text,
            raw_available integer,
            updated_at text,
            payload_json text
        )
        """
    )
    con.commit()
    con.close()
    return db


def _write_source_line(path: Path, text: str, *, prefix: str = "prefix:") -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = prefix + text + ":suffix\n"
    path.write_text(content, encoding="utf-8")
    start = len(prefix.encode("utf-8"))
    end = start + len(text.encode("utf-8"))
    return start, end


def _insert_session(con, *, session_id: str, source_path: Path, thread_name: str = ""):
    con.execute(
        """
        insert into canonical_sessions (
            record_id, source_system, session_id, raw_artifact_id,
            canonical_window_id, project_id, project_root, thread_name,
            source_path, raw_path, source_mtime, raw_mtime, source_size_bytes,
            raw_size_bytes, source_line_count, raw_line_count,
            indexed_message_count, indexed_chunk_count, raw_indexed_message_count,
            raw_offset_coverage_count, bad_json_line_count, oversized_line_count,
            index_status, updated_at, payload_json
        ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            f"record-{session_id}",
            "claude_code_cli",
            session_id,
            session_id,
            session_id,
            "technical-window-id",
            "/tmp/project",
            thread_name,
            str(source_path),
            str(source_path.parent / "missing-raw.jsonl"),
            "2026-07-01T00:00:00Z",
            "",
            source_path.stat().st_size,
            0,
            1,
            0,
            1,
            1,
            0,
            0,
            0,
            0,
            "raw_missing",
            "2026-07-01T00:00:00Z",
            "{}",
        ),
    )


def _insert_user_message(con, *, session_id: str, source_path: Path, text: str, start: int, end: int, message_id: str = "m1"):
    payload = {
        "source_line": {
            "role": "user",
            "content": text,
            "offset_start": start,
            "offset_end": end,
            "line_no": 1,
        }
    }
    con.execute(
        """
        insert into canonical_messages (
            message_id, record_id, source_system, session_id,
            canonical_window_id, project_id, project_root, source_path,
            raw_path, role, native_type, native_id, timestamp, line_no,
            raw_line_no, source_offset_start, source_offset_end,
            raw_offset_start, raw_offset_end, content_chars, content_hash,
            line_hash, content_preview, raw_available, updated_at, payload_json
        ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            message_id,
            f"record-{session_id}",
            "claude_code_cli",
            session_id,
            session_id,
            "technical-window-id",
            "/tmp/project",
            str(source_path),
            str(source_path.parent / "missing-raw.jsonl"),
            "user",
            "user",
            message_id,
            "2026-07-01T00:00:00Z",
            1,
            0,
            start,
            end,
            None,
            None,
            len(text),
            "hash",
            "linehash",
            text[:240],
            0,
            "2026-07-01T00:00:00Z",
            json.dumps(payload, ensure_ascii=False),
        ),
    )


def _declared_card(path: Path, *, session_id: str):
    card = registry.ensure_borrowing_card(
        source_system="claude_code_cli",
        consumer="opus",
        canonical_window_id=session_id,
        session_id=session_id,
        path=path,
    )["card"]
    return registry.declare_membership(
        card_id=card["card_id"],
        reading_area="忆凡尘阅读区",
        projects=["time-library"],
        series=["honghuang"],
        path=path,
    )


def test_raw_session_index_uses_declared_borrowing_card_and_source_offsets(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = tmp_path / "claude" / "declared.jsonl"
    text = "我把这个新的模式取名为阅读区和raw一样不能修改只读，多窗口进入为多人阅读区"
    start, end = _write_source_line(source_path, text)
    con = sqlite3.connect(db)
    _insert_session(con, session_id="declared-session", source_path=source_path, thread_name="")
    _insert_user_message(con, session_id="declared-session", source_path=source_path, text=text, start=start, end=end)
    con.commit()
    con.close()
    registry_path = tmp_path / "reading_area_registry.json"
    membership = _declared_card(registry_path, session_id="declared-session")

    result = reading_area_raw_index.build_raw_session_index_records(
        records_db_path=db,
        reading_area_registry_path=registry_path,
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
    )

    assert result["ok"] is True
    assert result["record_count"] == 1
    assert result["title_model_used"] is False
    record = result["records"][0]
    assert record["library_shelf"] == "raw"
    assert record["source_system"] == "opus"
    assert record["origin_source_system"] == "claude_code_cli"
    assert "claude_code_cli" in record["source_system_aliases"]
    assert record["source_refs"]["source_system_canonical_lane"] == "opus"
    assert record["declared_project_ids"] == membership["project_ids"]
    assert record["raw_index_meta"]["scope_source"] == "borrowing_card_declared_membership"
    assert record["raw_index_meta"]["source_system_taxonomy_applied"] is True
    assert record["raw_index_meta"]["technical_project_id_used_as_declared_identity"] is False
    excerpt = reading_area_raw_index.read_raw_index_source_excerpt(record, extra_allowed_roots=[tmp_path])
    assert excerpt["ok"] is True
    assert excerpt["text"] == text
    assert excerpt["byte_offsets"] == {"start": start, "end": end}


def test_raw_session_index_does_not_index_undeclared_sessions(tmp_path):
    db = _create_records_db(tmp_path)
    declared_source = tmp_path / "claude" / "declared.jsonl"
    undeclared_source = tmp_path / "claude" / "undeclared.jsonl"
    declared_text = "阅读区只给目录和编号，正文按需借阅"
    undeclared_text = "另一个项目的会话不能盲目塞进 time-library"
    d_start, d_end = _write_source_line(declared_source, declared_text)
    u_start, u_end = _write_source_line(undeclared_source, undeclared_text)
    con = sqlite3.connect(db)
    _insert_session(con, session_id="declared-session", source_path=declared_source, thread_name="Declared Lane")
    _insert_user_message(con, session_id="declared-session", source_path=declared_source, text=declared_text, start=d_start, end=d_end)
    _insert_session(con, session_id="undeclared-session", source_path=undeclared_source, thread_name="Undeclared Lane")
    _insert_user_message(con, session_id="undeclared-session", source_path=undeclared_source, text=undeclared_text, start=u_start, end=u_end, message_id="m2")
    con.commit()
    con.close()
    registry_path = tmp_path / "reading_area_registry.json"
    _declared_card(registry_path, session_id="declared-session")

    result = reading_area_raw_index.build_raw_session_index_records(
        records_db_path=db,
        reading_area_registry_path=registry_path,
        project_ids=["time-library"],
    )

    assert result["record_count"] == 1
    assert result["records"][0]["session_id"] == "declared-session"
    assert result["records"][0]["title"] == "Declared Lane"
    assert "undeclared-session" not in json.dumps(result, ensure_ascii=False)


def test_thread_name_title_still_uses_first_user_message_offsets(tmp_path):
    db = _create_records_db(tmp_path)
    source_path = tmp_path / "claude" / "thread-named.jsonl"
    text = "真正有料的用户消息应该成为 raw lane 借阅切片"
    start, end = _write_source_line(source_path, text, prefix="metadata header:")
    con = sqlite3.connect(db)
    _insert_session(con, session_id="thread-named-session", source_path=source_path, thread_name="Opus lane readable title")
    _insert_user_message(
        con,
        session_id="thread-named-session",
        source_path=source_path,
        text="<environment_context>\n  <cwd>/tmp/project</cwd>\n</environment_context>",
        start=0,
        end=start,
        message_id="m-env",
    )
    _insert_user_message(con, session_id="thread-named-session", source_path=source_path, text=text, start=start, end=end, message_id="m-real")
    con.commit()
    con.close()
    registry_path = tmp_path / "reading_area_registry.json"
    membership = _declared_card(registry_path, session_id="thread-named-session")

    result = reading_area_raw_index.build_raw_session_index_records(
        records_db_path=db,
        reading_area_registry_path=registry_path,
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
    )

    record = result["records"][0]
    assert record["title"] == "Opus lane readable title"
    assert record["source_refs"]["byte_offsets"] == {"start": start, "end": end}
    assert record["source_refs"]["source_span_selection_basis"] == "first_user_message_text"
    assert record["raw_index_meta"]["source_span_selection_basis"] == "first_user_message_text"
    excerpt = reading_area_raw_index.read_raw_index_source_excerpt(record, extra_allowed_roots=[tmp_path])
    assert excerpt["text"] == text


def test_first_user_message_offsets_do_not_read_entire_source_file(tmp_path, monkeypatch):
    db = _create_records_db(tmp_path)
    source_path = tmp_path / "claude" / "large-thread.jsonl"
    text = "大文件也只能按 records.db 给出的 offset 附近读取首条有料消息"
    start, end = _write_source_line(source_path, text, prefix="x" * 200000)
    con = sqlite3.connect(db)
    _insert_session(con, session_id="large-thread-session", source_path=source_path, thread_name="Large Raw Lane")
    _insert_user_message(con, session_id="large-thread-session", source_path=source_path, text=text, start=start, end=end)
    con.commit()
    con.close()
    registry_path = tmp_path / "reading_area_registry.json"
    membership = _declared_card(registry_path, session_id="large-thread-session")

    def fail_read_bytes(self):
        raise AssertionError("raw span selection must not read the whole source file")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    result = reading_area_raw_index.build_raw_session_index_records(
        records_db_path=db,
        reading_area_registry_path=registry_path,
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
    )

    record = result["records"][0]
    assert record["title"] == "Large Raw Lane"
    assert record["source_refs"]["byte_offsets"] == {"start": start, "end": end}
    assert record["source_refs"]["source_span_selection_basis"] == "first_user_message_text"
    excerpt = reading_area_raw_index.read_raw_index_source_excerpt(record, extra_allowed_roots=[tmp_path])
    assert excerpt["text"] == text


def test_raw_session_index_can_project_declared_mimocode_checkpoint(tmp_path):
    db = _create_records_db(tmp_path)
    mimocode_root = tmp_path / "mimocode"
    session_id = "ses_0e69f6457ffevUIqYd3yLfN8BL"
    checkpoint = mimocode_root / "memory" / "sessions" / session_id / "checkpoint.md"
    checkpoint.parent.mkdir(parents=True)
    checkpoint_text = (
        "# Session checkpoint\n"
        "_Generated by checkpoint writer; structure preserved across updates._\n\n"
        "Topic: catalog push runtime wiring — minimal consumer endpoint + targeted tests\n\n"
        "## §1 Active intent\n"
        "> \"任务：catalog 开局 push 运行态接线，单焦点。\"\n"
    )
    checkpoint.write_text(checkpoint_text, encoding="utf-8")
    undeclared = mimocode_root / "memory" / "sessions" / "ses_undeclared" / "checkpoint.md"
    undeclared.parent.mkdir(parents=True)
    undeclared.write_text("Topic: unrelated MiMo session\n", encoding="utf-8")
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

    result = reading_area_raw_index.build_raw_session_index_records(
        records_db_path=db,
        reading_area_registry_path=registry_path,
        project_ids=membership["project_ids"],
        series_ids=membership["series_ids"],
        mimocode_root=mimocode_root,
    )

    assert result["ok"] is True
    assert result["record_count"] == 1
    assert result["matched_session_count"] == 1
    assert result["title_model_used"] is False
    assert "ses_undeclared" not in json.dumps(result, ensure_ascii=False)
    record = result["records"][0]
    assert record["library_shelf"] == "raw"
    assert record["source_system"] == "mimo"
    assert record["origin_source_system"] == "mimocode"
    assert record["session_id"] == session_id
    assert record["title"] == "catalog push runtime wiring — minimal consumer endpoint + targeted tests"
    assert record["raw_index_meta"]["scope_source"] == "borrowing_card_declared_membership"
    assert record["raw_index_meta"]["title_model_used"] is False
    assert record["source_refs"]["source_ref_kind"] == "mimocode_checkpoint_source_path_fallback"
    assert record["source_refs"]["source_path"] == str(checkpoint)
    active_start = len(checkpoint_text.split("## §1 Active intent", 1)[0].encode("utf-8"))
    assert record["source_refs"]["byte_offsets"] == {"start": active_start, "end": len(checkpoint_text.encode("utf-8"))}
    assert record["source_refs"]["source_span_selection_basis"] == "checkpoint_active_intent"
    excerpt = reading_area_raw_index.read_raw_index_source_excerpt(record, extra_allowed_roots=[tmp_path])
    assert excerpt["ok"] is True
    assert excerpt["text"].startswith("## §1 Active intent")
    assert "任务：catalog 开局 push 运行态接线" in excerpt["text"]


def test_raw_session_index_uses_runtime_declaration_for_checkpoint_alias(tmp_path):
    db = _create_records_db(tmp_path)
    mimocode_root = tmp_path / "mimocode"
    session_id = "ses_alias"
    checkpoint = mimocode_root / "memory" / "sessions" / session_id / "checkpoint.md"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_text(
        "## §1 Active intent\n"
        "用 alias 声明进入 MiMo checkpoint raw index。\n",
        encoding="utf-8",
    )
    registry_path = tmp_path / "reading_area_registry.json"
    card = registry.ensure_borrowing_card(
        source_system="unknown",
        consumer="mimo",
        canonical_window_id=session_id,
        session_id=session_id,
        path=registry_path,
    )["card"]
    registry.declare_membership(
        card_id=card["card_id"],
        reading_area="忆凡尘阅读区",
        projects=["time-library"],
        series=["honghuang"],
        path=registry_path,
    )

    result = reading_area_raw_index.build_raw_session_index_records(
        records_db_path=db,
        reading_area_registry_path=registry_path,
        mimocode_root=mimocode_root,
    )

    assert result["ok"] is True
    assert result["record_count"] == 1
    record = result["records"][0]
    assert record["origin_source_system"] == "mimocode"
    assert record["source_refs"]["source_ref_kind"] == "mimocode_checkpoint_source_path_fallback"
    excerpt = reading_area_raw_index.read_raw_index_source_excerpt(record, extra_allowed_roots=[tmp_path])
    assert excerpt["ok"] is True
    assert "用 alias 声明进入 MiMo checkpoint raw index" in excerpt["text"]


def test_raw_session_index_source_excerpt_rejects_paths_outside_allowed_roots(tmp_path):
    allowed = tmp_path / "allowed"
    blocked = tmp_path / "blocked" / "secret.txt"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("do-not-leak", encoding="utf-8")
    record = {
        "source_refs": {
            "source_path": str(blocked),
            "byte_offsets": {"start": 0, "end": len("do-not-leak")},
        }
    }

    excerpt = reading_area_raw_index.read_raw_index_source_excerpt(record, extra_allowed_roots=[allowed])

    assert excerpt["ok"] is False
    assert excerpt["status"] == "source_path_not_allowed"
    assert excerpt["text"] == ""
