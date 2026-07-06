import json
import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import zhiyi_distill


def _write_records_db(root, rows):
    db = root / "output" / "records" / "records.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    try:
        con.execute(
            """
            create table canonical_messages (
                message_id text primary key,
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
        for idx, row in enumerate(rows, start=1):
            text = row["content"]
            raw_path = row.get("raw_path", "")
            source_path = row.get("source_path", raw_path)
            source_start = row.get("source_start", row.get("start", 0))
            source_end = row.get("source_end", row.get("end", len(text.encode("utf-8"))))
            raw_start = row.get("raw_start", row.get("start", 0))
            raw_end = row.get("raw_end", row.get("end", len(text.encode("utf-8"))))
            payload = {
                "source_line": {
                    "role": row.get("role", "user"),
                    "content": text,
                    "offset_start": source_start,
                    "offset_end": source_end,
                    "line_no": idx,
                },
                "raw_line": {
                    "role": row.get("role", "user"),
                    "content": text,
                    "offset_start": raw_start,
                    "offset_end": raw_end,
                    "line_no": idx,
                },
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
                    row.get("message_id", f"m{idx}"),
                    row.get("record_id", "r1"),
                    row.get("source_system", "codex"),
                    row.get("session_id", "s1"),
                    row.get("canonical_window_id", "w1"),
                    row.get("project_id", "technical-window-id"),
                    str(root),
                    str(source_path),
                    str(raw_path),
                    row.get("role", "user"),
                    "message",
                    row.get("native_id", f"n{idx}"),
                    row.get("timestamp", "2026-07-01T00:00:00Z"),
                    idx,
                    idx,
                    source_start,
                    source_end,
                    raw_start,
                    raw_end,
                    len(text),
                    "hash",
                    "linehash",
                    text[:240],
                    1,
                    "2026-07-01T00:00:00Z",
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        con.commit()
    finally:
        con.close()
    return db


def _write_raw_line(path, obj):
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(line, encoding="utf-8")
    return len(line.encode("utf-8"))


def _write_pref(root, exp_id, text, *, source_name="raw.jsonl", record_text=None):
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / source_name
    raw_path.write_text(json.dumps({"role": "user", "content": text}, ensure_ascii=False) + "\n", encoding="utf-8")
    zhiyi_dir = root / "zhiyi" / "preference_memory"
    zhiyi_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "exp_id": exp_id,
        "type": "preference_memory",
        "summary": record_text or text[:80],
        "detail": f"用户表达了偏好：{record_text or text}",
        "source_refs": json.dumps({"source_system": "codex", "source_path": str(raw_path)}, ensure_ascii=False),
    }
    path = zhiyi_dir / "preference_memory.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record, raw_path


def test_load_raw_user_records_from_records_db_selects_user_preference(tmp_path):
    raw_path = tmp_path / "memory" / "codex" / "session.jsonl"
    text = "以后回答先给结论再给证据，别一上来铺太长背景。"
    end = _write_raw_line(raw_path, {"role": "user", "content": text})
    _write_records_db(
        tmp_path,
        [
            {"message_id": "m-user", "role": "user", "content": text, "raw_path": raw_path, "start": 0, "end": end},
            {"message_id": "m-noise", "role": "user", "content": "Say OK only.", "raw_path": raw_path, "start": 0, "end": end},
        ],
    )

    records = zhiyi_distill.load_raw_user_records(tmp_path, limit=5, scan_limit=20)
    selected, rejects = zhiyi_distill.s0_select_preference_candidates(records, root=tmp_path)

    assert len(records) == 1
    assert len(selected) == 1
    assert selected[0]["input_source"] == "raw_user_message"
    assert selected[0]["source_role"] == "user"
    assert selected[0]["source_refs"]["source_role"] == "user"
    offsets = selected[0]["source_refs"]["byte_offsets"]
    assert raw_path.read_bytes()[offsets["start"]:offsets["end"]].decode("utf-8") == "以后回答先给结论再给证据，别一上来铺太长背景"
    assert rejects == {}


def test_raw_user_loader_extracts_direct_preference_span_from_long_turn(tmp_path):
    raw_path = tmp_path / "memory" / "codex" / "session.jsonl"
    text = (
        "claude的复核\n"
        "这里是一大段二签报告和施工说明，不应该整段进入知意。\n"
        "我的偏好是以后回答先给结论再给证据，别一上来铺太长背景。\n"
        "后面继续贴一堆流水和回执。"
    )
    end = _write_raw_line(raw_path, {"role": "user", "content": text})
    _write_records_db(tmp_path, [{"message_id": "m-long", "role": "user", "content": text, "raw_path": raw_path, "start": 0, "end": end}])

    records = zhiyi_distill.load_raw_user_records(tmp_path, limit=5, scan_limit=20)
    selected, rejects = zhiyi_distill.s0_select_preference_candidates(records, root=tmp_path)

    assert len(records) == 1
    assert len(selected) == 1
    assert selected[0]["evidence_text"] == "我的偏好是以后回答先给结论再给证据，别一上来铺太长背景"
    assert "claude的复核" not in selected[0]["evidence_text"]
    offsets = selected[0]["source_refs"]["byte_offsets"]
    raw = raw_path.read_bytes()
    assert raw[offsets["start"]:offsets["end"]].decode("utf-8") == selected[0]["evidence_text"]
    assert rejects == {}


def test_raw_user_loader_rejects_relay_and_article_noise(tmp_path):
    raw_path = tmp_path / "memory" / "codex" / "session.jsonl"
    article = "看看 让 Agent 拥有超强记忆，TencentDB Agent Memory 开源了！原创 小 G 在小说阅读器读本章。"
    dispatch = "按 NAS 监工验收口径继续。单焦点,不发散。跑完用固定格式报,不要 Handoff 作文。"
    end = _write_raw_line(raw_path, {"role": "user", "content": article})
    _write_records_db(
        tmp_path,
        [
            {"message_id": "m-article", "role": "user", "content": article, "raw_path": raw_path, "start": 0, "end": end},
            {"message_id": "m-dispatch", "role": "user", "content": dispatch, "raw_path": raw_path, "start": 0, "end": end},
        ],
    )

    records = zhiyi_distill.load_raw_user_records(tmp_path, limit=5, scan_limit=20)
    selected, rejects = zhiyi_distill.s0_select_preference_candidates(records, root=tmp_path)

    assert records == []
    assert selected == []
    assert rejects == {}


def test_load_raw_user_records_can_scope_to_session(tmp_path):
    raw_path = tmp_path / "memory" / "codex" / "session.jsonl"
    wanted = "以后回答先给结论再给证据，别一上来铺太长背景。"
    other = "以后用 Time Library / 忆凡尘，不用拼音 yifanchen。"
    end = _write_raw_line(raw_path, {"role": "user", "content": wanted})
    _write_records_db(
        tmp_path,
        [
            {"message_id": "m-wanted", "session_id": "s-wanted", "role": "user", "content": wanted, "raw_path": raw_path, "start": 0, "end": end},
            {"message_id": "m-other", "session_id": "s-other", "role": "user", "content": other, "raw_path": raw_path, "start": 0, "end": end},
        ],
    )

    records = zhiyi_distill.load_raw_user_records(tmp_path, limit=5, scan_limit=20, source_system="codex", session_id="s-wanted")

    assert len(records) == 1
    assert records[0]["detail"] == "以后回答先给结论再给证据，别一上来铺太长背景"
    assert records[0]["source_refs"]["session_id"] == "s-wanted"


def test_load_raw_user_records_uses_source_offsets_when_raw_offsets_are_missing(tmp_path):
    source_path = tmp_path / "claude" / "f2.jsonl"
    prefix = "metadata:"
    wanted = "他现在有新名字了不要用yifanchen这样的称呼他"
    suffix = ":tail"
    payload_text = prefix + wanted + suffix
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(payload_text, encoding="utf-8")
    start = len(prefix.encode("utf-8"))
    end = start + len(wanted.encode("utf-8"))
    missing_raw_path = tmp_path / "missing" / "archive.jsonl"
    _write_records_db(
        tmp_path,
        [
            {
                "message_id": "m-source-offset-only",
                "session_id": "f2c08dd8-test",
                "role": "user",
                "content": wanted,
                "source_path": source_path,
                "raw_path": missing_raw_path,
                "source_start": start,
                "source_end": end,
                "raw_start": None,
                "raw_end": None,
            }
        ],
    )

    records = zhiyi_distill.load_raw_user_records(tmp_path, limit=5, scan_limit=20, session_id="f2c08dd8-test")
    selected, rejects = zhiyi_distill.s0_select_preference_candidates(records, root=tmp_path)

    assert len(records) == 1
    assert len(selected) == 1
    refs = selected[0]["source_refs"]
    assert refs["source_path"] == str(source_path)
    assert refs["raw_path"] == str(missing_raw_path)
    assert refs["byte_offsets"] == {"start": start, "end": end}
    assert source_path.read_bytes()[start:end].decode("utf-8") == selected[0]["evidence_text"]
    assert rejects == {}


def test_load_raw_user_records_can_filter_by_raw_query(tmp_path):
    raw_path = tmp_path / "memory" / "codex" / "session.jsonl"
    wanted = "他的英文名不是yifanchen，我们的仓库名不是写在哪里了吗。"
    other = "以后回答先给结论再给证据，别一上来铺太长背景。"
    end = _write_raw_line(raw_path, {"role": "user", "content": wanted})
    _write_records_db(
        tmp_path,
        [
            {"message_id": "m-wanted", "role": "user", "content": wanted, "raw_path": raw_path, "start": 0, "end": end},
            {"message_id": "m-other", "role": "user", "content": other, "raw_path": raw_path, "start": 0, "end": end},
        ],
    )

    records = zhiyi_distill.load_raw_user_records(tmp_path, limit=5, scan_limit=20, raw_query="英文名不是yifanchen")

    assert len(records) == 1
    assert records[0]["detail"] == "他的英文名不是yifanchen，我们的仓库名不是写在哪里了吗"
    assert "yifanchen" in records[0]["detail"]


def test_raw_user_loader_splits_yifanchen_preference_from_status_visibility_complaint(tmp_path):
    raw_path = tmp_path / "memory" / "claude" / "session.jsonl"
    text = "他现在有新名字了不要用yifanchen这样的称呼他，这种老外看不懂老中看不习惯，其实我现在最大的困扰不是没有功能而是我提的什么功能实现了接没接上，我眼前就是一片雾。"
    end = _write_raw_line(raw_path, {"role": "user", "content": text})
    _write_records_db(
        tmp_path,
        [{"message_id": "m-yifanchen-long", "role": "user", "content": text, "raw_path": raw_path, "start": 0, "end": end}],
    )

    records = zhiyi_distill.load_raw_user_records(tmp_path, limit=5, scan_limit=20, raw_query="yifanchen")

    assert [record["detail"] for record in records] == [
        "他现在有新名字了不要用yifanchen这样的称呼他，这种老外看不懂老中看不习惯"
    ]


def test_raw_user_model_card_requires_user_author_and_offsets(tmp_path, monkeypatch):
    raw_path = tmp_path / "memory" / "codex" / "session.jsonl"
    text = "以后回答先给结论再给证据，别一上来铺太长背景。"
    evidence = "以后回答先给结论再给证据，别一上来铺太长背景"
    end = _write_raw_line(raw_path, {"role": "user", "content": text})
    _write_records_db(tmp_path, [{"message_id": "m-user", "role": "user", "content": text, "raw_path": raw_path, "start": 0, "end": end}])
    monkeypatch.setenv("MEMCORE_ZHIYI_API_KEY", "fake-key")
    monkeypatch.setenv("MEMCORE_ZHIYI_MODEL", "fake-model")
    monkeypatch.setenv("MEMCORE_ZHIYI_BASE_URL", "https://example.invalid/v1")

    def fake_http(messages, config):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "verdict": "refined",
                    "title": "回答先给结论再给证据",
                    "preference_statement": "用户希望回答先给结论再给证据，避免开头铺太长背景。",
                    "when_to_use": "组织复杂回答或解释证据时",
                    "object": "回答结构",
                    "collapse_condition": "用户明确要求先展开背景时降级",
                    "verbatim_excerpt": evidence,
                    "confidence": 0.91,
                    "supporting_refs": ["verbatim"],
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(zhiyi_distill, "_http_chat_completion_with_config", fake_http)
    report = zhiyi_distill.run_pipeline(
        tmp_path,
        input_source="raw_user",
        dry_run=True,
        model_distill=True,
        model_distill_limit=3,
    )

    assert report["input_source"] == "raw_user"
    assert report["input_records"] == 1
    assert report["steps"]["S3_validate"]["passed"] == 1
    card = report["owner_sample"][0]
    assert card["input_source"] == "raw_user_message"
    assert card["source_author"] == "user"
    assert card["source_refs"]["source_role"] == "user"
    start = raw_path.read_bytes().find(evidence.encode("utf-8"))
    assert card["evidence_refs"][0]["byte_offsets"] == {"start": start, "end": start + len(evidence.encode("utf-8"))}


def test_raw_user_insufficient_evidence_relaxed_when_direct_preference_is_bound(tmp_path, monkeypatch):
    raw_path = tmp_path / "memory" / "codex" / "session.jsonl"
    text = "以后用 Time Library / 忆凡尘，不用拼音 yifanchen。"
    evidence = "以后用 Time Library / 忆凡尘，不用拼音 yifanchen"
    end = _write_raw_line(raw_path, {"role": "user", "content": text})
    _write_records_db(tmp_path, [{"message_id": "m-name", "role": "user", "content": text, "raw_path": raw_path, "start": 0, "end": end}])
    monkeypatch.setenv("MEMCORE_ZHIYI_API_KEY", "fake-key")
    monkeypatch.setenv("MEMCORE_ZHIYI_MODEL", "fake-model")
    monkeypatch.setenv("MEMCORE_ZHIYI_BASE_URL", "https://example.invalid/v1")

    def fake_http(messages, config):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "verdict": "insufficient_evidence",
                    "title": "公开名称使用 Time Library / 忆凡尘",
                    "preference_statement": "用户希望公开名称使用 Time Library / 忆凡尘，不用拼音 yifanchen。",
                    "when_to_use": "命名 MCP、skill、公开入口或文档时",
                    "object": "Time Library public naming",
                    "collapse_condition": "用户明确恢复拼音名时降级",
                    "verbatim_excerpt": evidence,
                    "confidence": 0.66,
                    "supporting_refs": ["verbatim"],
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(zhiyi_distill, "_http_chat_completion_with_config", fake_http)
    report = zhiyi_distill.run_pipeline(
        tmp_path,
        input_source="raw_user",
        dry_run=True,
        model_distill=True,
        model_distill_limit=1,
    )

    assert report["steps"]["S3_validate"]["passed"] == 1
    card = report["owner_sample"][0]
    assert card["distill_meta"]["model_distill_status"] == "relaxed_insufficient_evidence"
    assert card["distill_meta"]["acceptance_policy"] == "coverage_first_relaxed_threshold"
    assert card["source_role"] == "user"
    assert card["verbatim_excerpt"] == evidence


def test_raw_user_chinese_evidence_rejects_english_only_title(tmp_path, monkeypatch):
    raw_path = tmp_path / "memory" / "codex" / "session.jsonl"
    text = "以后用 Time Library / 忆凡尘，不用拼音 yifanchen。"
    evidence = "以后用 Time Library / 忆凡尘，不用拼音 yifanchen"
    end = _write_raw_line(raw_path, {"role": "user", "content": text})
    _write_records_db(tmp_path, [{"message_id": "m-title-language", "role": "user", "content": text, "raw_path": raw_path, "start": 0, "end": end}])
    monkeypatch.setenv("MEMCORE_ZHIYI_API_KEY", "fake-key")
    monkeypatch.setenv("MEMCORE_ZHIYI_MODEL", "fake-model")
    monkeypatch.setenv("MEMCORE_ZHIYI_BASE_URL", "https://example.invalid/v1")

    def fake_http(messages, config):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "verdict": "refined",
                    "title": "Use Time Library public naming",
                    "preference_statement": "用户希望公开名称使用 Time Library / 忆凡尘，不用拼音 yifanchen。",
                    "when_to_use": "命名 MCP、skill、公开入口或文档时",
                    "object": "Time Library public naming",
                    "collapse_condition": "用户明确恢复拼音名时降级",
                    "verbatim_excerpt": evidence,
                    "confidence": 0.86,
                    "supporting_refs": ["verbatim"],
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(zhiyi_distill, "_http_chat_completion_with_config", fake_http)
    report = zhiyi_distill.run_pipeline(
        tmp_path,
        input_source="raw_user",
        dry_run=True,
        model_distill=True,
        model_distill_limit=1,
    )

    assert report["steps"]["S3_validate"]["failed"] == 1
    assert report["steps"]["S3_validate"]["fail_reasons"]["title_language_mismatch"] == 1
    assert report["owner_sample"] == []


def test_model_config_falls_back_to_minimax_m3_when_memcore_key_missing(monkeypatch):
    monkeypatch.delenv("MEMCORE_ZHIYI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_MAX_TOKENS", raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "fake-minimax-key")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M3")

    config = zhiyi_distill._model_config_dict()

    assert config["provider"] == "minimax"
    assert config["model"] == "MiniMax-M3"
    assert config["api_key_env"] == "MINIMAX_API_KEY"
    assert config["max_tokens"] == 1800
    assert zhiyi_distill._api_key_ready(config) is True


def test_model_config_allows_minimax_token_override(monkeypatch):
    monkeypatch.delenv("MEMCORE_ZHIYI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "fake-minimax-key")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M3")
    monkeypatch.setenv("MINIMAX_MAX_TOKENS", "2400")

    config = zhiyi_distill._model_config_dict()

    assert config["provider"] == "minimax"
    assert config["max_tokens"] == 2400


def test_raw_user_prompt_forbids_think_preamble(tmp_path):
    raw_path = tmp_path / "memory" / "codex" / "session.jsonl"
    text = "他现在有新名字了不要用yifanchen这样的称呼他，这种老外看不懂老中看不习惯。"
    end = _write_raw_line(raw_path, {"role": "user", "content": text})
    _write_records_db(tmp_path, [{"message_id": "m-name", "role": "user", "content": text, "raw_path": raw_path, "start": 0, "end": end}])
    records = zhiyi_distill.load_raw_user_records(tmp_path, limit=1, scan_limit=20, raw_query="yifanchen")
    selected, _rejects = zhiyi_distill.s0_select_preference_candidates(records, root=tmp_path)

    messages = zhiyi_distill._build_prompt(selected[0])

    assert "Do not include <think>" in messages[0]["content"]
    assert "JSON object only" in messages[0]["content"]


def test_write_accepted_owner_sample_artifact_writes_validated_candidate(tmp_path):
    raw_path = tmp_path / "raw.jsonl"
    prefix = "prefix:"
    evidence = "我把这个新的模式取名为阅读区和raw一样不能修改只读，多窗口进入为多人阅读区"
    suffix = ":suffix"
    raw_path.write_text(prefix + evidence + suffix, encoding="utf-8")
    start = len(prefix.encode("utf-8"))
    end = start + len(evidence.encode("utf-8"))
    artifact = tmp_path / "artifact.json"
    card = {
        "candidate_id": "zhiyi-distill-owner-accepted-001",
        "candidate_type": "zhiyi_preference_card",
        "schema_version": "2026.7.1",
        "library_shelf": "zhiyi",
        "type": "preference_memory",
        "source_mode": "evidence_bound_model_distill",
        "lifecycle_status": "active",
        "title": "阅读区模式保持只读",
        "summary": "新的阅读区模式应与raw模式相同，保持只读不可修改，多窗口进入时为多人阅读区",
        "preference_statement": "新的阅读区模式应与raw模式相同，保持只读不可修改，多窗口进入时为多人阅读区",
        "when_to_use": "设计阅读区或多人共读区时",
        "object": "阅读区模式",
        "collapse_condition": "用户明确要求改成可写模式时降级",
        "verbatim_excerpt": evidence,
        "source_author": "user",
        "source_role": "user",
        "input_source": "raw_user_message",
        "source_refs": {
            "source_path": str(raw_path),
            "source_role": "user",
            "byte_offsets": {"start": 0, "end": len((prefix + evidence + suffix).encode("utf-8"))},
        },
        "evidence_refs": [
            {
                "source_path": str(raw_path),
                "source_role": "user",
                "byte_offsets": {"start": start, "end": end},
            }
        ],
        "confidence": 0.95,
    }
    artifact.write_text(json.dumps({"owner_sample": [card]}, ensure_ascii=False), encoding="utf-8")

    out = tmp_path / "out"
    report = zhiyi_distill.write_accepted_owner_samples([artifact], out, dry_run=False)

    assert report["written_candidate_files"] == 1
    written = json.loads(Path(report["written_files"][0]).read_text(encoding="utf-8"))
    assert written["candidate_id"] == "zhiyi-distill-owner-accepted-001"
    assert written["source_refs"]["byte_offsets"] == {"start": start, "end": end}
    assert written["distill_meta"]["owner_decision"] == "accepted_by_owner_2026_07_01"
    assert written["distill_meta"]["raw_write_performed"] is False
    assert written["distill_meta"]["zhiyi_candidate_write_performed"] is True


def test_raw_user_pipeline_rejects_non_user_source_role(tmp_path, monkeypatch):
    text = "以后回答先给结论再给证据。"
    raw_path = tmp_path / "raw.jsonl"
    raw_path.write_text(text, encoding="utf-8")
    record = {
        "exp_id": "raw-user-bad",
        "type": "raw_user_message",
        "summary": text,
        "detail": text,
        "source_role": "assistant",
        "source_refs": {"source_path": str(raw_path), "source_role": "assistant", "byte_offsets": {"start": 0, "end": len(text.encode("utf-8"))}},
    }

    selected, rejects = zhiyi_distill.s0_select_preference_candidates([record], root=tmp_path)

    assert selected == []
    assert rejects["raw_user_source_role_not_user"] == 1


def test_s0_selects_user_preference_and_rejects_skill_dump(tmp_path):
    good_text = "我喜欢你回答时先给结论，再给关键证据，别一上来铺太长背景。"
    bad_text = "skill.md dump: name: tool-test 这是一大段 skill dump，不是我的偏好。"
    _write_pref(tmp_path, "exp-good", good_text, source_name="good.jsonl")
    _write_pref(tmp_path, "exp-bad", bad_text, source_name="bad.jsonl")

    records = zhiyi_distill.load_preference_records(tmp_path)
    selected, rejects = zhiyi_distill.s0_select_preference_candidates(records, root=tmp_path)

    assert len(selected) == 1
    assert selected[0]["record"]["exp_id"] == "exp-good"
    assert rejects["disallowed_source_material"] == 1


def test_model_distill_requires_fake_key_and_mock_http(tmp_path, monkeypatch):
    text = "我喜欢你回答时先给结论，再给关键证据，别一上来铺太长背景。"
    _write_pref(tmp_path, "exp-pref", text)
    for name in ("MEMCORE_ZHIYI_API_KEY", "OPENAI_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MEMCORE_ZHIYI_API_KEY", "fake-key")
    monkeypatch.setenv("MEMCORE_ZHIYI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("MEMCORE_ZHIYI_MODEL", "fake-model")
    monkeypatch.setenv("MEMCORE_ZHIYI_BASE_URL", "https://example.invalid/v1")

    calls = []

    def fake_http(messages, config):
        calls.append((messages, config))
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "verdict": "refined",
                    "title": "回答先给结论再给证据",
                    "preference_statement": "用户喜欢回答先给结论，再给关键证据，避免一上来铺太长背景。",
                    "when_to_use": "回答需要组织结构或解释复杂问题时",
                    "object": "回答结构",
                    "collapse_condition": "用户要求先展开背景时降级",
                    "verbatim_excerpt": text,
                    "confidence": 0.9,
                    "supporting_refs": ["verbatim"],
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(zhiyi_distill, "_http_chat_completion_with_config", fake_http)
    report = zhiyi_distill.run_pipeline(
        tmp_path,
        dry_run=True,
        model_distill=True,
        model_distill_limit=5,
    )

    assert calls, "model path should use the mocked HTTP client"
    assert report["steps"]["S2_model_distill"]["attempted"] == 1
    assert report["steps"]["S2_model_distill"]["refined"] == 1
    assert report["steps"]["S3_validate"]["passed"] == 1
    assert report["steps"]["S5_write"]["written_candidate_files"] == 0
    card = report["owner_sample"][0]
    assert card["source_mode"] == "evidence_bound_model_distill"
    assert card["library_shelf"] == "zhiyi"
    assert card["title"] == "回答先给结论再给证据"
    assert card["verbatim_excerpt"] == text
    assert card["evidence_refs"][0]["byte_offsets"]["start"] >= 0


def test_no_key_skips_model_without_http_call(tmp_path, monkeypatch):
    text = "我喜欢你回答时先给结论，再给关键证据。"
    _write_pref(tmp_path, "exp-pref", text)
    for name in ("MEMCORE_ZHIYI_API_KEY", "OPENAI_API_KEY", "MINIMAX_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    def fail_http(*_args, **_kwargs):
        raise AssertionError("HTTP must not be called without API key")

    monkeypatch.setattr(zhiyi_distill, "_http_chat_completion_with_config", fail_http)
    report = zhiyi_distill.run_pipeline(tmp_path, dry_run=True, model_distill=True)

    assert report["steps"]["S2_model_distill"]["attempted"] == 0
    assert report["steps"]["S2_model_distill"]["skip_reason"] == "no_api_key"
    assert report["owner_sample"] == []


def test_rejects_model_card_when_verbatim_not_supported(tmp_path, monkeypatch):
    text = "我喜欢你回答时先给结论，再给关键证据。"
    _write_pref(tmp_path, "exp-pref", text)
    monkeypatch.setenv("MEMCORE_ZHIYI_API_KEY", "fake-key")
    monkeypatch.setenv("MEMCORE_ZHIYI_MODEL", "fake-model")
    monkeypatch.setenv("MEMCORE_ZHIYI_BASE_URL", "https://example.invalid/v1")

    def fake_http(messages, config):
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "verdict": "refined",
                    "title": "模型编造了不在证据里的偏好",
                    "preference_statement": "用户喜欢先看数学证明。",
                    "when_to_use": "数学题",
                    "object": "回答结构",
                    "verbatim_excerpt": "用户喜欢先看数学证明。",
                    "confidence": 0.9,
                    "supporting_refs": ["verbatim"],
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(zhiyi_distill, "_http_chat_completion_with_config", fake_http)
    report = zhiyi_distill.run_pipeline(tmp_path, dry_run=True, model_distill=True)

    assert report["steps"]["S3_validate"]["failed"] == 1
    assert report["steps"]["S3_validate"]["fail_reasons"]["verbatim_not_in_evidence"] == 1
    assert report["owner_sample"] == []


def test_write_mode_writes_candidates_and_quarantines_bad_model_output(tmp_path, monkeypatch):
    good_text = "我喜欢你回答时先给结论，再给关键证据。"
    bad_text = "我喜欢你解释代码时先说风险，再说改动。"
    _write_pref(tmp_path, "exp-good", good_text, source_name="good.jsonl")
    _write_pref(tmp_path, "exp-bad", bad_text, source_name="bad.jsonl")
    monkeypatch.setenv("MEMCORE_ZHIYI_API_KEY", "fake-key")
    monkeypatch.setenv("MEMCORE_ZHIYI_MODEL", "fake-model")
    monkeypatch.setenv("MEMCORE_ZHIYI_BASE_URL", "https://example.invalid/v1")
    calls = {"n": 0}

    def fake_http(messages, config):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "ok": True,
                "content": json.dumps(
                    {
                        "verdict": "refined",
                        "title": "回答先给结论再给证据",
                        "preference_statement": "用户喜欢回答先给结论，再给关键证据。",
                        "when_to_use": "回答复杂问题时",
                        "object": "回答结构",
                        "verbatim_excerpt": good_text,
                        "confidence": 0.88,
                        "supporting_refs": ["verbatim"],
                    },
                    ensure_ascii=False,
                ),
            }
        return {
            "ok": True,
            "content": json.dumps(
                {
                    "verdict": "refined",
                    "title": "坏卡",
                    "preference_statement": "坏卡",
                    "when_to_use": "坏卡",
                    "verbatim_excerpt": "不在原文",
                    "supporting_refs": ["verbatim"],
                },
                ensure_ascii=False,
            ),
        }

    monkeypatch.setattr(zhiyi_distill, "_http_chat_completion_with_config", fake_http)
    out = tmp_path / "out"
    report = zhiyi_distill.run_pipeline(
        tmp_path,
        dry_run=False,
        model_distill=True,
        quarantine_bad=True,
        output_root=out,
    )

    assert report["steps"]["S5_write"]["written_candidate_files"] == 1
    assert report["steps"]["S5_write"]["quarantined_files"] == 1
    assert len(list((out / "candidates").glob("*.json"))) == 1
    assert len(list((out / "quarantined").glob("*.json"))) == 1


def test_quarantine_preference_dump_dry_run_does_not_modify_active_file(tmp_path):
    text = "skill.md dump: name: yifanchen-zhiyi 这不是用户偏好。"
    _write_pref(tmp_path, "exp-bad", text)
    active = tmp_path / "zhiyi" / "preference_memory" / "preference_memory.jsonl"
    before = active.read_text(encoding="utf-8")

    report = zhiyi_distill.quarantine_preference_dump(tmp_path, execute=False)

    assert report["records_seen"] == 1
    assert report["records_quarantined"] == 0
    assert report["active_file_emptied"] is False
    assert active.read_text(encoding="utf-8") == before


def test_quarantine_preference_dump_execute_preserves_bytes_and_empties_active_file(tmp_path):
    text = "skill.md dump: name: yifanchen-zhiyi 这不是用户偏好。"
    _write_pref(tmp_path, "exp-bad", text)
    active = tmp_path / "zhiyi" / "preference_memory" / "preference_memory.jsonl"
    before = active.read_bytes()

    report = zhiyi_distill.quarantine_preference_dump(tmp_path, execute=True)

    assert report["records_seen"] == 1
    assert report["records_quarantined"] == 1
    assert report["active_file_emptied"] is True
    assert report["raw_write_performed"] is False
    assert report["zhiyi_candidate_write_performed"] is False
    assert report["zhiyi_runtime_write_performed"] is True
    assert active.read_text(encoding="utf-8") == ""
    quarantine_path = Path(report["quarantine_path"])
    manifest_path = Path(report["manifest_path"])
    assert quarantine_path.read_bytes() == before
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["records_quarantined"] == 1
    assert manifest["exp_ids"] == ["exp-bad"]
