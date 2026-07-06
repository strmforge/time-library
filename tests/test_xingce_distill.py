import json
import hashlib
import os
import sqlite3
import sys
import subprocess

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools.xingce_distill import (
    s0_select_worthy_spans, s1_split_exchanges, s2_distill_from_exchange,
    s3_validate, s4_dedupe, s5_build_candidate, run_pipeline,
    write_candidate, write_auto_action, _is_agent_narration,
    _candidate_id, _verify_verbatim_in_raw, _resolve_source_path,
    _extract_resolved_references, _extract_normalized_time,
    _extract_participant_attribution, _extract_explicit_reasoning,
    _extract_fact_type, _extract_entities, _extract_situation,
    _is_reject, load_raw_records, _find_raw_excerpt_for_record,
    AUTO_ACTION_STATUS, _apply_model_distill_to_card,
    _REJECT_CONSTRUCTION_STATUS,
    _build_xingce_distill_prompt, _extract_json_from_response,
    _source_origin_guard, _owner_sample_prefilter,
    load_canonical_work_records,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────

def _make_record(exp_id="exp-case-t001", record_type="case_memory",
                 summary="", detail="", source_path="/tmp/nonexistent.jsonl"):
    return {
        "exp_id": exp_id, "type": record_type,
        "canonical_window_id": "test-window", "session_id": "test-session",
        "computer_id": "local", "source_system": "codex",
        "summary": summary, "detail": detail,
        "source_refs": json.dumps({
            "source_system": "codex", "computer_name": "local",
            "canonical_window_id": "test-window", "session_id": "test-session",
            "source_path": source_path, "msg_ids": ["msg-1"],
            "artifact_type": "codex_session_jsonl", "captured_at": "2026-06-30T00:00:00Z",
        }),
        "score": 0.7, "evidence_level": "medium", "extracted_at": "2026-06-30 00:00:00",
    }


def _write_raw(tmp_path, content, name="raw.jsonl"):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


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
            source_path = row["source_path"]
            raw_path = row.get("raw_path", "")
            source_start = row.get("source_start", 0)
            source_end = row.get("source_end", len(text.encode("utf-8")))
            raw_start = row.get("raw_start", source_start)
            raw_end = row.get("raw_end", source_end)
            payload = {
                "source_line": {
                    "role": row.get("role", "assistant"),
                    "content": text,
                    "offset_start": source_start,
                    "offset_end": source_end,
                    "line_no": idx,
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
                    row.get("message_id", f"m{idx}"),
                    row.get("record_id", "r1"),
                    row.get("source_system", "claude_code_cli"),
                    row.get("session_id", "f2-test"),
                    row.get("canonical_window_id", "w1"),
                    row.get("project_id", "technical-window-id"),
                    str(root),
                    str(source_path),
                    str(raw_path),
                    row.get("role", "assistant"),
                    "message",
                    row.get("native_id", f"n{idx}"),
                    row.get("timestamp", "2026-07-02T00:00:00Z"),
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
                    "2026-07-02T00:00:00Z",
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        con.commit()
    finally:
        con.close()
    return db


def _exchange_record(tmp_path, verbatim, context="上下文：评估 GSDesk 新兴远程桌面项目"):
    raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
    return _make_record(
        detail=f"{context}。assistant 原话：{verbatim}",
        source_path=raw_path,
    )


def _card_with_offsets(tmp_path, verbatim, card=None):
    """Build a card with real _resolution_report.computed_byte_offsets backed by a temp file."""
    from tools.xingce_distill import _compute_verbatim_byte_offsets
    raw_path = _write_raw(tmp_path, f'{verbatim}\n')
    offsets = _compute_verbatim_byte_offsets(verbatim, raw_path)
    if card is None:
        card = {}
    card.setdefault("title", "测试经验")
    card.setdefault("one_sentence", "一句话")
    card.setdefault("verbatim_excerpt", verbatim)
    card.setdefault("situation", "场景")
    card.setdefault("action_or_lesson", "行动")
    card.setdefault("when_to_use", "时机")
    card.setdefault("distill_meta", {})
    rec = card.get("source_record") or _make_record(source_path=raw_path)
    refs = json.loads(rec["source_refs"])
    refs["source_path"] = raw_path
    rec["source_refs"] = json.dumps(refs)
    card["source_record"] = rec
    card["_resolution_report"] = {
        "original_source_path": raw_path,
        "resolved_source_path": raw_path,
        "resolution_method": "exact_match",
        "computed_byte_offsets": offsets,
    }
    return card


# ─── Gate 1: 产出可见可用 ─────────────────────────────────────────────────

class TestGate1OutputVisibleUsable:
    def test_pipeline_produces_n_greater_than_0(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=False)
        n = report["steps"]["S5_write"].get("written_candidate_files", 0)
        assert n > 0, f"Expected N>0, got {n}"

    def test_canonical_messages_input_uses_source_offsets_without_raw_offsets(self, tmp_path):
        source_path = tmp_path / "claude" / "f2.jsonl"
        text = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        line = json.dumps({"role": "assistant", "content": text}, ensure_ascii=False) + "\n"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(line, encoding="utf-8")
        db = _write_records_db(
            tmp_path,
            [
                {
                    "message_id": "m-source-only",
                    "content": text,
                    "source_path": source_path,
                    "raw_path": tmp_path / "missing" / "archive.jsonl",
                    "source_start": 0,
                    "source_end": len(line.encode("utf-8")),
                    "raw_start": None,
                    "raw_end": None,
                }
            ],
        )

        records = load_canonical_work_records(tmp_path, records_db=db, session_id="f2-test", scan_limit=10)
        report = run_pipeline(
            str(tmp_path),
            input_source="canonical_messages",
            records_db=db,
            raw_session_id="f2-test",
            dry_run=True,
        )

        assert len(records) == 1
        assert json.loads(records[0]["source_refs"])["source_path"] == str(source_path)
        assert report["input_source"] == "canonical_messages"
        assert report["steps"]["S3_validate"]["passed"] >= 1
        assert report["steps"]["S5_write"]["unique_candidates"] >= 1

    def test_p3_loader_reads_candidates(self, tmp_path):
        """p3_recall._load_xingce_work_experience_candidate_memories can read the written candidates."""
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-gate1-test", "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate", "title": "不建议直接上生产",
            "summary": "不建议直接上生产", "verbatim_excerpt": "不建议直接上生产",
            "evidence_refs": [{"source_path": "/tmp/t.jsonl"}], "source_refs": ["/tmp/t.jsonl"],
            "observed_facts": ["评估"], "recommended_procedure": ["隔离"], "confidence": 0.7,
        }
        with open(cand_dir / "xingce-distill-gate1-test-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-distill-gate1-test", "action_status": AUTO_ACTION_STATUS}) + "\n")
        from src.p3_recall import _load_xingce_work_experience_candidate_memories
        mems = _load_xingce_work_experience_candidate_memories()
        assert len(mems) >= 1
        assert mems[0]["_type"] == "xingce_work_experience_candidate"
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]


# ─── Gate 2: 送达闭环·隔天真召回 ──────────────────────────────────────────

class TestGate2RecallClosure:
    def test_candidate_recalled_via_p3_loader(self, tmp_path):
        """Distilled candidate is loadable via p3 loader and has correct structure for recall."""
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-gate2-test", "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate", "title": "评估新兴项目时应先隔离试跑",
            "summary": "评估新兴项目时应先隔离试跑，因为太新风险高",
            "verbatim_excerpt": "评估新兴项目时应先隔离试跑，因为太新风险高",
            "evidence_refs": [{"source_path": "/tmp/t.jsonl"}], "source_refs": ["/tmp/t.jsonl"],
            "observed_facts": ["评估新兴项目"], "recommended_procedure": ["隔离试跑"],
            "work_scenario": "评估新兴项目", "action_strategy": "隔离试跑",
            "confidence": 0.7, "applicable_scope": "test-window",
        }
        with open(cand_dir / "xingce-distill-gate2-test-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-distill-gate2-test", "action_status": AUTO_ACTION_STATUS}) + "\n")
        from src.p3_recall import _load_xingce_work_experience_candidate_memories
        mems = _load_xingce_work_experience_candidate_memories()
        assert len(mems) >= 1
        first = mems[0]
        # Verify it has the structure needed for recall/scoring
        assert first.get("_type") == "xingce_work_experience_candidate"
        assert first.get("exp_id")
        assert first.get("summary")
        assert first.get("source_refs", {}).get("source_path") or first.get("source_refs", {}).get("candidate_path")
        assert first.get("_xingce", {}).get("action_status") == AUTO_ACTION_STATUS
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]

    def test_candidate_has_source_ref_traceable(self, tmp_path):
        """Recalled candidate has source_ref that is traceable."""
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "zhiyi_empty")
        (tmp_path / "zhiyi_empty").mkdir(parents=True, exist_ok=True)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-gate2b", "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate", "title": "先修掉 typecheck 再部署",
            "summary": "先修掉 typecheck 再部署", "verbatim_excerpt": "先修掉 typecheck 再部署",
            "evidence_refs": [{"source_path": "/tmp/traceable.jsonl", "session_id": "sess-1"}],
            "source_refs": ["/tmp/traceable.jsonl"],
            "observed_facts": ["验证"], "recommended_procedure": ["修 typecheck"],
            "confidence": 0.7,
        }
        with open(cand_dir / "xingce-distill-gate2b-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-distill-gate2b", "action_status": AUTO_ACTION_STATUS}) + "\n")
        from src.p3_recall import handle_recall
        import src.p3_recall as _p3mod
        _p3mod.MEMORIES_CACHE = None
        _p3mod.MEMORIES_CACHE_SIGNATURE = None
        _p3mod._MEMORY_RELOAD_THREAD = None
        result = handle_recall({"query": "修 typecheck 部署", "recall_mode": "substring", "top_k": 10})
        matched = result.get("matched_memories", [])
        xingce_matches = [m for m in matched if m.get("type") == "xingce_work_experience_candidate"]
        assert len(xingce_matches) >= 1, (
            f"handle_recall must return xingce_candidates, got 0 xingce out of {len(matched)} matched. "
            f"Types: {[m.get('type') for m in matched]}"
        )
        sr = xingce_matches[0].get("source_refs", {})
        assert sr.get("source_path") or sr.get("candidate_path")
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]
        del os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"]

    def test_handle_recall_returns_xingce_candidate_via_real_path(self, tmp_path):
        """handle_recall substring returns _type=xingce_work_experience_candidate through real recall path."""
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "zhiyi_empty")
        (tmp_path / "zhiyi_empty").mkdir(parents=True, exist_ok=True)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-gate2-real",
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "远程桌面软件不能直接公网裸上",
            "summary": "远程桌面软件不能直接公网裸上，应该先在测试机试跑验证",
            "verbatim_excerpt": "远程桌面软件不能直接公网裸上，应该先在测试机试跑验证",
            "evidence_refs": [{"source_path": "/tmp/real.jsonl", "session_id": "sess-real"}],
            "source_refs": ["/tmp/real.jsonl"],
            "observed_facts": ["远程桌面软件部署评估"],
            "recommended_procedure": ["先测试机试跑"],
            "work_scenario": "评估远程桌面项目风险",
            "action_strategy": "隔离试跑验证",
            "confidence": 0.7,
        }
        with open(cand_dir / "xingce-distill-gate2-real-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-real-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-distill-gate2-real", "action_status": AUTO_ACTION_STATUS}) + "\n")
        from src.p3_recall import handle_recall
        import src.p3_recall as _p3mod
        _p3mod.MEMORIES_CACHE = None
        _p3mod.MEMORIES_CACHE_SIGNATURE = None
        _p3mod._MEMORY_RELOAD_THREAD = None
        queries = [
            "远程桌面软件 不能直接公网裸上 先测试机试跑",
            "远程桌面 公网 试跑验证",
        ]
        for q in queries:
            _p3mod.MEMORIES_CACHE = None
            _p3mod.MEMORIES_CACHE_SIGNATURE = None
            result = handle_recall({"query": q, "recall_mode": "substring", "top_k": 10})
            matched = result.get("matched_memories", [])
            xingce_matches = [m for m in matched if m.get("type") == "xingce_work_experience_candidate"]
            assert len(xingce_matches) >= 1, (
                f"Query '{q}' must recall xingce_candidate, got 0 xingce out of {len(matched)}. "
                f"Types: {[m.get('type') for m in matched]}"
            )
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]
        del os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"]

    def test_gateway_compact_returns_xingce_candidate(self, tmp_path):
        """Gateway query_raw_source_refs + compact_recall_payload returns xingce_candidate item, not just p3 direct."""
        from tests.test_shared_memory_consumption import _reload_modules
        p3, gw = _reload_modules(tmp_path)
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "zhiyi_empty")
        (tmp_path / "zhiyi_empty").mkdir(parents=True, exist_ok=True)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-gate2-gw",
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "安全审计 LICENSE 商用集成需要合规检查",
            "summary": "安全审计 合规检查 LICENSE 二次分发 商用集成时应先验证授权边界",
            "verbatim_excerpt": "安全审计 合规检查 LICENSE 二次分发 商用集成时应先验证授权边界",
            "evidence_refs": [{"source_path": "/tmp/gw.jsonl", "session_id": "sess-gw"}],
            "source_refs": ["/tmp/gw.jsonl"],
            "observed_facts": ["安全审计"], "recommended_procedure": ["合规检查"],
            "work_scenario": "安全审计/合规检查时", "action_strategy": "验证授权边界",
            "confidence": 0.7,
        }
        with open(cand_dir / "xingce-distill-gate2-gw-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-gw-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-distill-gate2-gw", "action_status": AUTO_ACTION_STATUS}) + "\n")
        p3.MEMORIES_CACHE = None
        p3.MEMORIES_CACHE_SIGNATURE = None
        result = gw.query_raw_source_refs(
            "安全审计 合规检查 LICENSE 二次分发 商用集成",
            consumer="test",
            request_id="test-gate2-gateway-xingce",
            recall_mode="substring",
            memory_scope="raw_pool",
            allow_cross_window_recall=True,
            limit=10,
            excerpt_chars=300,
        )
        compact = gw.compact_recall_payload(result)
        items = compact.get("items", [])
        xingce_items = [it for it in items if it.get("xingce_candidate") or it.get("type") == "xingce_work_experience_candidate"]
        assert len(xingce_items) >= 1, (
            f"Gateway compact must return xingce_candidate items. "
            f"Got {len(items)} items, xingce_items={len(xingce_items)}. "
            f"Types: {[it.get('type') for it in items]}"
        )
        assert xingce_items[0].get("xingce_candidate", {}).get("action_status") == AUTO_ACTION_STATUS
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]
        del os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"]

    def test_gateway_xingce_survives_source_system_filter(self, tmp_path):
        """Xingce candidates must pass through gateway even when source_system filter is set to non-openclaw."""
        from tests.test_shared_memory_consumption import _reload_modules, _write_memory
        p3, gw = _reload_modules(tmp_path)
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        _write_memory(tmp_path, "codex", "sess-codex", "msg-codex", "安全审计 LICENSE", "安全审计 LICENSE 商用集成合规检查")
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-gate2-filter",
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "LICENSE 商用集成前必须先做安全审计",
            "summary": "LICENSE 商用集成前必须先做安全审计和合规检查",
            "verbatim_excerpt": "LICENSE 商用集成前必须先做安全审计和合规检查",
            "evidence_refs": [{"source_path": "/tmp/filter.jsonl", "session_id": "sess-filter"}],
            "source_refs": ["/tmp/filter.jsonl"],
            "observed_facts": ["安全审计"], "recommended_procedure": ["合规检查"],
            "confidence": 0.7,
        }
        with open(cand_dir / "xingce-distill-gate2-filter-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-filter-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-distill-gate2-filter", "action_status": AUTO_ACTION_STATUS}) + "\n")
        p3.MEMORIES_CACHE = None
        p3.MEMORIES_CACHE_SIGNATURE = None
        result = gw.query_raw_source_refs(
            "安全审计 LICENSE 商用集成",
            source_system="codex",
            consumer="test",
            request_id="test-gate2-source-filter",
            recall_mode="substring",
            memory_scope="raw_pool",
            allow_cross_window_recall=True,
            limit=10,
            excerpt_chars=300,
        )
        compact = gw.compact_recall_payload(result)
        items = compact.get("items", [])
        xingce_items = [it for it in items if it.get("xingce_candidate") or it.get("type") == "xingce_work_experience_candidate"]
        assert len(xingce_items) >= 1, (
            f"Xingce must survive source_system=codex filter. "
            f"Got {len(items)} items, xingce_items={len(xingce_items)}. "
            f"Types: {[it.get('type') for it in items]}"
        )
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]

    def test_handle_recall_default_mode_returns_xingce_candidate(self, tmp_path):
        """handle_recall with NO explicit recall_mode (default vector→substring fallback)
        still returns xingce_candidate items through the supplement bridge."""
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "zhiyi_empty")
        (tmp_path / "zhiyi_empty").mkdir(parents=True, exist_ok=True)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-default-mode",
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "默认模型路径配置规范",
            "summary": "按官方文档规范配置默认模型路径，避免路径拼接错误导致加载失败",
            "verbatim_excerpt": "按官方文档规范配置默认模型路径，避免路径拼接错误导致加载失败",
            "evidence_refs": [{"source_path": "/tmp/default-mode.jsonl", "session_id": "sess-dm"}],
            "source_refs": ["/tmp/default-mode.jsonl"],
            "observed_facts": ["模型路径配置"],
            "recommended_procedure": ["按官方文档配置"],
            "work_scenario": "配置模型路径时",
            "action_strategy": "按官方文档规范配置",
            "confidence": 0.7,
        }
        with open(cand_dir / "xingce-distill-default-mode-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-default-mode-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-distill-default-mode", "action_status": AUTO_ACTION_STATUS}) + "\n")
        from src.p3_recall import handle_recall
        import src.p3_recall as _p3mod
        _p3mod.MEMORIES_CACHE = None
        _p3mod.MEMORIES_CACHE_SIGNATURE = None
        _p3mod._MEMORY_RELOAD_THREAD = None
        result = handle_recall({"query": "配置 模型 路径 规范", "top_k": 10})
        matched = result.get("matched_memories", [])
        xingce_matches = [m for m in matched if m.get("type") == "xingce_work_experience_candidate"]
        assert len(xingce_matches) >= 1, (
            f"Default recall_mode must return xingce_candidates via supplement bridge. "
            f"Got 0 xingce out of {len(matched)} matched. "
            f"mode={result.get('mode')}, types: {[m.get('type') for m in matched]}"
        )
        assert xingce_matches[0].get("matched_by") in ("xingce_candidate_bridge", "rrf(keyword+bm25)", "bm25", "fts5_bm25", "substring")
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]
        del os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"]

    def test_gateway_default_mode_returns_xingce_candidate(self, tmp_path):
        """Gateway query_raw_source_refs without explicit recall_mode returns xingce_candidate."""
        from tests.test_shared_memory_consumption import _reload_modules
        p3, gw = _reload_modules(tmp_path)
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "zhiyi_empty")
        (tmp_path / "zhiyi_empty").mkdir(parents=True, exist_ok=True)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-gw-default",
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "多设备开发推荐软KM",
            "summary": "多设备开发场景推荐软KM替代KVM，减少硬件切换成本",
            "verbatim_excerpt": "多设备开发场景推荐软KM替代KVM，减少硬件切换成本",
            "evidence_refs": [{"source_path": "/tmp/gw-default.jsonl", "session_id": "sess-gw-dm"}],
            "source_refs": ["/tmp/gw-default.jsonl"],
            "observed_facts": ["多设备开发"],
            "recommended_procedure": ["使用软KM"],
            "work_scenario": "多设备开发时",
            "action_strategy": "软KM替代KVM",
            "confidence": 0.7,
        }
        with open(cand_dir / "xingce-distill-gw-default-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-gw-default-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-distill-gw-default", "action_status": AUTO_ACTION_STATUS}) + "\n")
        p3.MEMORIES_CACHE = None
        p3.MEMORIES_CACHE_SIGNATURE = None
        result = gw.query_raw_source_refs(
            "多设备 开发 软KM KVM",
            consumer="test",
            request_id="test-gw-default-xingce",
            memory_scope="raw_pool",
            allow_cross_window_recall=True,
            limit=10,
            excerpt_chars=300,
        )
        compact = gw.compact_recall_payload(result)
        items = compact.get("items", [])
        xingce_items = [it for it in items if it.get("xingce_candidate") or it.get("type") == "xingce_work_experience_candidate"]
        assert len(xingce_items) >= 1, (
            f"Gateway default recall_mode must return xingce_candidate items. "
            f"Got {len(items)} items, xingce_items={len(xingce_items)}. "
            f"Types: {[it.get('type') for it in items]}"
        )
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]
        del os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"]

    def test_supplement_bridge_adds_xingce_when_absent(self, tmp_path):
        """_supplement_xingce_candidates adds relevant xingce items when they are missing from matched."""
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "zhiyi_empty")
        (tmp_path / "zhiyi_empty").mkdir(parents=True, exist_ok=True)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-bridge-test",
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "bridge测试标题",
            "summary": "bridge测试摘要",
            "verbatim_excerpt": "bridge测试摘要",
            "evidence_refs": [{"source_path": "/tmp/bridge.jsonl"}],
            "source_refs": ["/tmp/bridge.jsonl"],
            "confidence": 0.7,
        }
        with open(cand_dir / "xingce-bridge-test-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-bridge-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-bridge-test", "action_status": AUTO_ACTION_STATUS}) + "\n")
        from src.p3_recall import _supplement_xingce_candidates, handle_recall
        import src.p3_recall as _p3mod
        _p3mod.MEMORIES_CACHE = None
        _p3mod.MEMORIES_CACHE_SIGNATURE = None
        _p3mod._MEMORY_RELOAD_THREAD = None
        fake_matched = [{"type": "case_memory", "exp_id": "other-exp", "summary": "not xingce", "source_refs": {"source_path": "/tmp/other.jsonl"}}]
        result = _supplement_xingce_candidates(fake_matched, "bridge 测试", 10)
        xingce_in_result = [m for m in result if m.get("type") == "xingce_work_experience_candidate"]
        assert len(xingce_in_result) >= 1, (
            f"_supplement_xingce_candidates must add xingce items. "
            f"Got {len(result)} total, 0 xingce."
        )
        assert xingce_in_result[0].get("matched_by") == "xingce_candidate_bridge"
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]
        del os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"]

    def test_supplement_bridge_does_not_add_unrelated_xingce(self, tmp_path):
        """The bridge must not pollute unrelated queries with every xingce candidate."""
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"] = str(tmp_path / "zhiyi_empty")
        (tmp_path / "zhiyi_empty").mkdir(parents=True, exist_ok=True)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-bridge-unrelated-test",
            "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate",
            "title": "发布前执行完整测试",
            "summary": "发布前执行完整测试，避免未验证变更进入运行态",
            "verbatim_excerpt": "发布前执行完整测试，避免未验证变更进入运行态",
            "evidence_refs": [{"source_path": "/tmp/unrelated-bridge.jsonl"}],
            "source_refs": ["/tmp/unrelated-bridge.jsonl"],
            "confidence": 0.7,
        }
        with open(cand_dir / "xingce-bridge-unrelated-test-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-unrelated-bridge-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-bridge-unrelated-test", "action_status": AUTO_ACTION_STATUS}) + "\n")
        from src.p3_recall import _supplement_xingce_candidates
        fake_matched = [{"type": "case_memory", "exp_id": "other-exp", "summary": "not xingce", "source_refs": {"source_path": "/tmp/other.jsonl"}}]
        result = _supplement_xingce_candidates(fake_matched, "天气 股票 旅游", 10)
        xingce_in_result = [m for m in result if m.get("type") == "xingce_work_experience_candidate"]
        assert not xingce_in_result, (
            f"_supplement_xingce_candidates must not add unrelated xingce items. "
            f"Got {len(xingce_in_result)} xingce items in {len(result)} total."
        )
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]
        del os.environ["MEMCORE_ZHIYI_ROOT_OVERRIDE"]

class TestGate3BidirectionalSampling:
    def test_false_positive_ai_construction_blocked(self, tmp_path):
        """AI construction narration should be blocked (false positive guard)."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        # AI construction narration
        rec = _make_record(
            summary="I've implemented the recall pipeline",
            detail="This change implements a new extraction module in the recall pipeline."
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        # Should be rejected at S0
        assert report["steps"]["S0_select"]["worthy"] == 0

    def test_false_positive_self_test_blocked(self, tmp_path):
        """Self-test content should be blocked."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(summary="self test 结果通过", detail="自测完成，冒烟测试通过")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0

    def test_false_positive_skill_dump_blocked(self, tmp_path):
        """Skill dump content should be blocked."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(summary="skill_dump 导出", detail="技能转储完成")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0

    def test_false_negative_real_experience_passes(self, tmp_path):
        """Real work experience should pass through."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高，所以先在测试环境验证"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估新兴项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=False)
        assert report["steps"]["S5_write"].get("written_candidate_files", 0) >= 1

    def test_sampling_metadata_present(self, tmp_path):
        """Report should have sampling metadata."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(summary="test", detail="test")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert "sampling" in report
        assert "approach" in report["sampling"]


# ─── Gate 4: evidence-bound 抽查 ──────────────────────────────────────────

class TestGate4EvidenceBound:
    def test_verbatim_in_raw_with_byte_offset(self, tmp_path):
        content = 'prefix ' + 'X' * 100 + ' suffix'
        raw_path = _write_raw(tmp_path, content)
        rec = _make_record(source_path=raw_path)
        refs = json.loads(rec["source_refs"])
        refs["byte_offsets"] = {"msg-1": {"start": 7, "end": 107}}
        rec["source_refs"] = json.dumps(refs)
        ok, info, report = _verify_verbatim_in_raw("X" * 40, rec)
        assert ok
        assert report.get("byte_offset_used") == "7-107"

    def test_verbatim_in_raw_with_bounded_search(self, tmp_path):
        verbatim = "不建议现在把它当成熟可放心生产部署的项目"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(source_path=raw_path)
        ok, info, report = _verify_verbatim_in_raw(verbatim, rec)
        assert ok
        assert report.get("resolution_method") in ("exact_match", "tail_match", "short_tail_match") or "tail_match" in report.get("resolution_method", "")

    def test_resolution_report_fields(self, tmp_path):
        verbatim = "测试验证内容"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(source_path=raw_path)
        ok, info, report = _verify_verbatim_in_raw(verbatim, rec)
        assert ok
        assert "original_source_path" in report
        assert "resolved_source_path" in report
        assert "resolution_method" in report

    def test_participant_attribution_correct(self):
        attrs = _extract_participant_attribution("用户要求先评估风险，我建议隔离试跑")
        assert "user" in attrs["roles"]
        assert "assistant" in attrs["roles"]

    def test_candidate_has_resolved_source_path_in_evidence_ref(self, tmp_path):
        """Pipeline-written candidate must have resolved_source_path and resolution_report in evidence_refs[0]."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=False)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        import glob as globmod
        cand_files = globmod.glob(str(cand_dir / "xingce-*-candidate.json"))
        assert cand_files, "Expected at least one candidate file"
        with open(cand_files[0]) as f:
            cand = json.load(f)
        er = cand["evidence_refs"][0]
        assert er.get("resolved_source_path"), (
            f"evidence_refs[0] must have resolved_source_path, got: {er.keys()}"
        )
        assert os.path.isfile(er["resolved_source_path"]), (
            f"resolved_source_path must be an existing file: {er['resolved_source_path']}"
        )
        rr = er.get("resolution_report", {})
        assert rr.get("original_source_path"), "resolution_report must have original_source_path"
        assert rr.get("resolved_source_path"), "resolution_report must have resolved_source_path"
        assert rr.get("resolution_method"), "resolution_report must have resolution_method"


# ─── Gate 4b: Strict-only evidence (no fuzzy) ─────────────────────────────

class TestGate4bStrictOnlyEvidence:
    def test_fuzzy_fragment_match_cannot_pass_s3(self, tmp_path):
        """Fuzzy/fragment match must NOT let S3 pass — verbatim must exist as-is in raw."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        # Record says verbatim has these chunks, but raw only has partial overlap
        verbatim_in_record = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        # Raw has only some fragments, not the full continuous text
        raw_content = '{"text": "不建议把新兴项目直接上生产"}\n{"text": "项目太新风险高"}\n'
        raw_path = _write_raw(tmp_path, raw_content)
        rec = _make_record(
            detail=f"上下文：评估项目。assistant 原话：{verbatim_in_record}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        # Must NOT produce any candidates because verbatim is not continuous in raw
        s5_n = report["steps"]["S5_write"].get("attempted_cards", 0)
        assert s5_n == 0, (
            f"Fuzzy fragment match must not pass S3, but got {s5_n} candidates"
        )

    def test_installed_summary_produces_card_with_raw_verbatim(self, tmp_path):
        """Installed-style summary can produce card, but verbatim_excerpt must come from raw field."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(
            summary=f"案例：{verbatim}",
            detail="",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        cards = report.get("sample_cards", [])
        if cards:
            card = cards[0]
            excerpt = card.get("verbatim_excerpt", "")
            # Excerpt must be a continuous substring from raw, not the summary text
            assert verbatim in excerpt or excerpt in verbatim, (
                f"verbatim_excerpt must be from raw field, got: {excerpt[:80]}"
            )
            method = card.get("raw_excerpt_method", "")
            assert method and method != "", (
                f"raw_excerpt_method must be set, got: {method}"
            )

    def test_no_unbounded_scan_on_large_file(self, tmp_path):
        """Large source file must NOT cause unbounded 50MB per-card scan."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定"
        # Create a large-ish raw file (not actually 50MB, but structured to test bounds)
        lines = ['{"text": "无关内容 ' + str(i) + '"}\n' for i in range(600)]
        lines[300] = f'{{"text": "{verbatim}"}}\n'
        raw_path = _write_raw(tmp_path, "".join(lines))
        rec = _make_record(
            detail=f"上下文：评估项目。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        # Should still find the card (line 300 is within 500-line bound)
        s5_n = report["steps"]["S5_write"].get("attempted_cards", 0)
        assert s5_n >= 1, f"Should find card within bounded search, got {s5_n}"

    def test_s3_pass_reason_is_strict(self, tmp_path):
        """S3 pass reasons must be byte_offset/jsonl_field_line/bounded_exact, not fuzzy."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(
            detail=f"上下文：评估项目。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        cards = report.get("sample_cards", [])
        for card in cards:
            method = card.get("raw_excerpt_method", "")
            assert "fuzzy" not in method.lower(), (
                f"S3 pass reason must not be fuzzy, got: {method}"
            )

    def test_find_raw_excerpt_returns_none_for_missing(self, tmp_path):
        """_find_raw_excerpt_for_record returns None when text not in raw."""
        raw_path = _write_raw(tmp_path, '{"text": "完全无关的内容"}\n')
        rec = _make_record(source_path=raw_path)
        excerpt, method = _find_raw_excerpt_for_record(rec, "这段话完全不在raw文件里面所以找不到")
        assert excerpt is None
        assert method == "verbatim_not_in_raw"

    def test_find_raw_excerpt_returns_continuous_substring(self, tmp_path):
        """_find_raw_excerpt_for_record returns a continuous substring from raw field."""
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(source_path=raw_path)
        excerpt, method = _find_raw_excerpt_for_record(rec, verbatim)
        assert excerpt is not None
        assert verbatim in excerpt or excerpt in verbatim
        assert "bounded_exact" in method or "byte_offset" in method or "session_line" in method

    def test_jsonl_payload_message_excerpt_not_json_wrapper(self, tmp_path):
        """verbatim_excerpt from JSONL with payload.message must be human-readable text, not JSON wrapper."""
        msg = "不建议把新兴项目直接上生产，应该先隔离试跑再决定"
        raw_line = json.dumps({
            "timestamp": "2026-06-30T12:00:00Z",
            "level": "info",
            "payload": {"message": msg},
            "session_id": "test-session",
            "msg_id": "msg-1",
        }, ensure_ascii=False)
        raw_path = _write_raw(tmp_path, raw_line + "\n")
        rec = _make_record(
            detail=f"上下文：评估项目。assistant 原话：{msg}",
            source_path=raw_path,
        )
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        cards = report.get("sample_cards", [])
        if cards:
            excerpt = cards[0].get("verbatim_excerpt", "")
            assert not excerpt.startswith("{"), (
                f"verbatim_excerpt must not start with '{{', got: {excerpt[:80]}"
            )
            assert '"timestamp"' not in excerpt, (
                f"verbatim_excerpt must not contain JSON wrapper, got: {excerpt[:80]}"
            )
            assert '"payload"' not in excerpt, (
                f"verbatim_excerpt must not contain JSON wrapper, got: {excerpt[:80]}"
            )
            assert msg[:20] in excerpt, (
                f"verbatim_excerpt must contain actual message text, got: {excerpt[:80]}"
            )


# ─── Gate 5: 主人抽检包 ───────────────────────────────────────────────────

class TestGate5OwnerSamplePack:
    def test_assistant_plan_status_rejected(self, tmp_path):
        """Assistant plan/status cards (我会按只读来做) must be rejected, not enter owner sample."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "我会按只读来做这次的审查，先确认源码结构再决定下一步"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(
            detail=f"上下文：审查代码。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"Assistant plan/status must be rejected at S0, "
            f"worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_assistant_plan_status_rejected_even_with_lesson_signal(self, tmp_path):
        """Plan/status starting with person prefix is rejected at S0 even with lesson signal.
        The lesson part can be preserved if abstracted separately (not starting with plan/status prefix)."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "我会先确认授权边界，但不建议直接公网裸上，必须先隔离试跑验证"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(
            detail=f"上下文：部署评估。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"Plan/status starting with person prefix must be rejected at S0, "
            f"worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_plan_need_more_source_rejected(self, tmp_path):
        """'我还需要最后几段源码来支撑...之后给结论' must be rejected as agent plan/status."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "我还需要最后几段源码来支撑分析，之后给结论"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(
            detail=f"上下文：分析代码。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"'我还需要...之后给结论' must be rejected at S0, "
            f"worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_plan_local_zhiyi_recall_rejected(self, tmp_path):
        """'我先不动生产数据，先做一个本地 zhiyi_recall...' must be rejected at S0."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "我先不动生产数据，先做一个本地 zhiyi_recall 验证闭环"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(
            detail=f"上下文：验证功能。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"'我先不动生产数据' must be rejected at S0, "
            f"worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_objective_lesson_passes(self, tmp_path):
        """An objective lesson like '涉及生产数据前，先用本地最小闭环验证' can pass."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "涉及生产数据前，先用本地最小闭环验证功能，确认无误后再碰真实环境"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(
            detail=f"上下文：数据验证。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=False)
        assert report["steps"]["S5_write"].get("written_candidate_files", 0) >= 1, (
            f"Objective lesson should pass, S5={report['steps']['S5_write']}"
        )

    def test_zhiyi_recall_in_title_blocked(self, tmp_path):
        """Card title/one_sentence/action/when must not contain zhiyi_recall."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(
            detail=f"上下文：评估项目。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        cards = report.get("sample_cards", [])
        for card in cards:
            for field in ("title", "one_sentence", "action_or_lesson", "when_to_use"):
                val = card.get(field, "")
                assert "zhiyi_recall" not in val, (
                    f"Card {field} must not contain zhiyi_recall, got: {val[:80]}"
                )
                assert "知意" not in val, (
                    f"Card {field} must not contain 知意, got: {val[:80]}"
                )

    def test_owner_sample_quality_plan_fields_rejected(self, tmp_path):
        """Card fields starting with 我先/我还需要/之后给结论 must fail S3."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        # This text has objective lesson but also plan language
        verbatim = "我先不动生产数据，先做一个本地 zhiyi_recall 验证闭环，确认通过再部署"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(
            detail=f"上下文：验证功能。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        # Should be rejected at S0 or not produce usable cards
        s5 = report["steps"]["S5_write"].get("attempted_cards", 0)
        assert s5 == 0, f"Plan narration must not produce candidates, got {s5}"

    def test_naming_leak_zhiyi_blocked_in_s3(self, tmp_path):
        """Card with 知意 in title/one_sentence must be blocked at S3, not enter owner sample."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(
            detail=f"上下文：评估项目。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        cards = report.get("sample_cards", [])
        for card in cards:
            title = card.get("title", "")
            one_sentence = card.get("one_sentence", "")
            assert "知意" not in title, (
                f"Card title must not expose 知意, got: {title}"
            )
            assert "知意" not in one_sentence, (
                f"Card one_sentence must not expose 知意, got: {one_sentence[:80]}"
            )

    def test_sample_cards_quality(self, tmp_path):
        """Sample cards must have useful situation, not weak patterns."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = ("不建议把 GSDesk 直接上公网生产环境，因为项目太新只有 v0.1.9。"
                    "应该先在局域网测试 VPS 试跑，修掉 server typecheck 失败问题，"
                    "明确 LICENSE 授权，升级 drizzle-orm 漏洞，理清签名校验边界。")
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估 GSDesk 远程桌面项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        cards = report.get("sample_cards", [])
        if cards:
            card = cards[0]
            # Situation must not be weak
            situation = card.get("situation", "")
            assert "的场景" not in situation or len(situation) > 15
            assert len(situation) >= 5
            # Must have all required fields
            assert card.get("title")
            assert card.get("one_sentence")
            assert card.get("when_to_use")
            assert card.get("action_or_lesson")
            assert card.get("verbatim_excerpt")

    def test_situation_extraction_quality(self):
        """_extract_situation should not produce weak 'X的场景' patterns."""
        sit = _extract_situation("不建议把 GSDesk 直接上生产", {})
        assert sit  # not empty
        assert sit != "的场景"  # not weak


# ─── Gate 6: §4 真挡 ─────────────────────────────────────────────────────

class TestGate6RealBlocking:
    def test_ai_narration_blocked_through_pipeline(self, tmp_path):
        """AI construction narration blocked through full pipeline, not just _is_reject."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(
            summary="I've implemented the recall pipeline in src/p3_recall.py",
            detail="This change implements a new extraction module. Updated the tests accordingly."
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0
        assert report["steps"]["S0_select"]["rejected"] >= 1

    def test_self_test_blocked_through_pipeline(self, tmp_path):
        """Self-test content blocked through full pipeline."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(summary="自测通过", detail="冒烟测试完成，self test passed")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0

    def test_skill_dump_blocked_through_pipeline(self, tmp_path):
        """Skill dump blocked through full pipeline."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(summary="skill_dump 导出完成", detail="技能转储数据如下")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0


# ─── MCP naming tests ────────────────────────────────────────────────────

class TestMCPTimingLibraryNaming:
    def test_tools_list_has_time_library_recall_primary(self, tmp_path):
        from tests.test_shared_memory_consumption import _reload_modules
        _, gw = _reload_modules(tmp_path)
        listed = gw.handle_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tools = listed["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "time_library_recall" in names
        assert "zhiyi_recall" in names
        assert names[0] == "time_library_recall"

    def test_time_library_recall_works_as_primary(self, tmp_path):
        from tests.test_shared_memory_consumption import _reload_modules, _write_memory
        _write_memory(tmp_path, "codex", "sess-tl", "msg-tl", "Time Library 命名测试", "测试内容")
        _, gw = _reload_modules(tmp_path)
        called = gw.handle_mcp_request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "time_library_recall", "arguments": {"query": "Time Library 命名测试", "consumer": "test", "recall_mode": "substring"}},
        })
        assert called["result"]["structuredContent"]["ok"] is True

    def test_zhiyi_recall_legacy_alias_works(self, tmp_path):
        from tests.test_shared_memory_consumption import _reload_modules, _write_memory
        _write_memory(tmp_path, "codex", "sess-legacy", "msg-legacy", "legacy alias 测试", "测试内容")
        _, gw = _reload_modules(tmp_path)
        called = gw.handle_mcp_request({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "zhiyi_recall", "arguments": {"query": "legacy alias 测试", "consumer": "test", "recall_mode": "substring"}},
        })
        assert called["result"]["structuredContent"]["ok"] is True

    def test_mcp_schema_no_zhiyi_in_primary_description(self, tmp_path):
        from tests.test_shared_memory_consumption import _reload_modules
        _, gw = _reload_modules(tmp_path)
        listed = gw.handle_mcp_request({"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}})
        tools = listed["result"]["tools"]
        primary = tools[0]
        assert primary["name"] == "time_library_recall"
        assert "Time Library" in primary["description"]
        legacy = tools[1]
        assert "Legacy" in legacy["description"]


# ─── Source path relocation ───────────────────────────────────────────────

class TestSourcePathRelocation:
    def test_original_exists(self, tmp_path):
        f = _write_raw(tmp_path, "test\n")
        path, method, tried = _resolve_source_path(f)
        assert path == f
        assert method == "exact_match"

    def test_empty_path(self):
        path, method, tried = _resolve_source_path("")
        assert path == ""

    def test_byte_offset_verification(self, tmp_path):
        content = 'prefix ' + 'X' * 100 + ' suffix'
        raw_path = _write_raw(tmp_path, content)
        rec = _make_record(source_path=raw_path)
        refs = json.loads(rec["source_refs"])
        refs["byte_offsets"] = {"msg-1": {"start": 7, "end": 107}}
        rec["source_refs"] = json.dumps(refs)
        ok, info, report = _verify_verbatim_in_raw("X" * 40, rec)
        assert ok
        assert report.get("byte_offset_used") == "7-107"


# ─── Six sub-step tests ──────────────────────────────────────────────────

class TestS2SixSubSteps:
    def test_resolved_references(self):
        refs = _extract_resolved_references("它是一个新项目，这个项目需要先评估")
        assert refs.get("resolved")

    def test_normalized_time(self):
        result = _extract_normalized_time("今天我们决定先不部署")
        assert result.get("normalized") or result.get("status") != "none"

    def test_participant_attribution(self):
        p = _extract_participant_attribution("用户要求先评估风险，我建议隔离试跑")
        assert "user" in p["roles"]
        assert "assistant" in p["roles"]

    def test_explicit_reasoning(self):
        r = _extract_explicit_reasoning("因为项目太新，所以不建议直接上生产")
        assert len(r) >= 1

    def test_fact_type(self):
        ft = _extract_fact_type("不建议现在把它当成熟可放心生产部署的项目")
        assert ft in ("xingce_work_experience", "risk", "decision")

    def test_entities(self):
        entities = _extract_entities("GSDesk 是一个 Cloudflare Worker 项目，检查 app.ts 的路由")
        assert len(entities) >= 1


# ─── Exchange granularity ────────────────────────────────────────────────

class TestExchangeGranularity:
    def test_s1_extracts_whole_exchange(self, tmp_path):
        verbatim = "不建议现在把它当成熟可放心生产部署的项目，需要先隔离试跑验证。先修掉typecheck明确LICENSE再部署上线。"
        rec = _exchange_record(tmp_path, verbatim)
        exchanges = s1_split_exchanges(rec)
        assert len(exchanges) >= 1

    def test_fragment_card_rejected(self, tmp_path):
        rec = _make_record(detail="assistant 原话：7 的若干字段；服务端代码里 VPS 的签名校验默认值。")
        exchanges = s1_split_exchanges(rec)
        cards = []
        for ex in exchanges:
            cards.extend(s2_distill_from_exchange(ex))
        assert len(cards) == 0

    def test_pure_description_rejected(self, tmp_path):
        rec = _make_record(detail="assistant 原话：GSDesk 是一个很新的远程桌面项目，定位是 Cloudflare Worker。")
        exchanges = s1_split_exchanges(rec)
        cards = []
        for ex in exchanges:
            cards.extend(s2_distill_from_exchange(ex))
        assert len(cards) == 0


# ─── No human review gate ────────────────────────────────────────────────

class TestNoHumanReviewGate:
    def test_action_status_is_auto_adopted(self, tmp_path):
        card = _card_with_offsets(tmp_path, "摘录内容足够长通过验证")
        cand = s5_build_candidate(card)
        actions_dir = str(tmp_path / "actions")
        write_auto_action(cand, actions_dir)
        import glob
        action_files = glob.glob(os.path.join(actions_dir, "*.jsonl"))
        with open(action_files[0]) as f:
            action = json.loads(f.readline())
        assert action["action_status"] == AUTO_ACTION_STATUS
        assert "review" not in action["action_status"]

    def test_p3_loads_auto_adopted(self, tmp_path):
        os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = str(tmp_path)
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        act_dir = tmp_path / "output" / "xingce_work_experience" / "actions"
        cand_dir.mkdir(parents=True)
        act_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-test-abc", "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate", "title": "不建议直接上生产",
            "summary": "不建议直接上生产", "verbatim_excerpt": "不建议直接上生产",
            "evidence_refs": [{"source_path": "/tmp/t.jsonl"}], "source_refs": ["/tmp/t.jsonl"],
            "observed_facts": ["评估"], "recommended_procedure": ["隔离"], "confidence": 0.7,
        }
        with open(cand_dir / "xingce-distill-test-abc-candidate.json", "w") as f:
            json.dump(cand, f)
        with open(act_dir / "20260630-action.jsonl", "w") as f:
            f.write(json.dumps({"candidate_id": "xingce-distill-test-abc", "action_status": AUTO_ACTION_STATUS}) + "\n")
        from src.p3_recall import _load_xingce_work_experience_candidate_memories
        mems = _load_xingce_work_experience_candidate_memories()
        assert len(mems) == 1
        s = mems[0]["summary"]
        assert "待审" not in s
        assert "review" not in s.lower()
        assert "active usable" in s
        del os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"]


# ─── Agent narration ─────────────────────────────────────────────────────

class TestAgentNarration:
    def test_catches_我先确认(self):
        assert _is_agent_narration("我先确认这个文件到底是什么壳子")
    def test_catches_现在我转去(self):
        assert _is_agent_narration("现在我转去代码层确认它的真实边界")
    def test_catches_验证通过(self):
        assert _is_agent_narration("验证通过：Claude Code CLI 的关键路径是...")
    def test_allows_conclusion(self):
        assert not _is_agent_narration("**结论**：GSDesk 是一个很新的远程桌面项目")
    def test_allows_recommendation(self):
        assert not _is_agent_narration("但我不建议现在把它当成熟可放心生产部署的项目")


# ─── Candidate ID uniqueness ─────────────────────────────────────────────

class TestCandidateIDUniqueness:
    def test_different_spans_different_ids(self):
        assert _candidate_id("exp-001", "span A 完全不同内容") != _candidate_id("exp-001", "span B 完全不同内容")
    def test_same_span_same_id(self):
        assert _candidate_id("exp-001", "same") == _candidate_id("exp-001", "same")
    def test_different_exp_different_ids(self):
        assert _candidate_id("exp-001", "same") != _candidate_id("exp-002", "same")


# ─── Source mode tests ───────────────────────────────────────────────────

class TestSourceModeDistinction:
    def test_s5_candidate_never_distill_heuristic(self, tmp_path):
        """s5_build_candidate must NEVER produce source_mode=distill_heuristic."""
        card = _card_with_offsets(tmp_path, "摘录内容足够长通过验证")
        cand = s5_build_candidate(card)
        assert cand["source_mode"] != "distill_heuristic", (
            f"source_mode must never be distill_heuristic, got: {cand['source_mode']}"
        )

    def test_heuristic_only_source_mode(self, tmp_path):
        """Without model distill, source_mode=heuristic_draft, lifecycle=not_signed."""
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定"
        card = _card_with_offsets(tmp_path, verbatim, {
            "title": "测试经验", "one_sentence": "应该先隔离试跑再决定",
            "verbatim_excerpt": verbatim,
            "situation": "评估新兴项目", "action_or_lesson": "隔离试跑",
            "when_to_use": "做技术选型时",
        })
        cand = s5_build_candidate(card)
        assert cand["source_mode"] == "heuristic_draft"
        assert cand["lifecycle_status"] == "candidate_not_signed"
        assert cand["distill_meta"]["pipeline"] == "S0_S5_heuristic"

    def test_model_distill_success_source_mode(self, tmp_path):
        """When model distill succeeds, source_mode=evidence_bound_model_distill and card fields are rewritten."""
        def fake_client(messages, config):
            return {"ok": True, "content": json.dumps({
                "verdict": "refined", "title": "新兴项目应先隔离试跑再上线",
                "one_sentence": "评估新兴项目风险时，不建议直接上生产，应先隔离试跑验证",
                "action_or_lesson": "先在测试环境隔离试跑，确认稳定后再部署到生产环境",
                "when_to_use": "评估新兴或不成熟项目时",
                "situation": "评估新兴远程桌面项目部署风险",
                "confidence": 0.85, "supporting_refs": ["verbatim"],
            })}
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定"
        card = _card_with_offsets(tmp_path, verbatim, {
            "title": "测试经验", "one_sentence": "应该先隔离试跑再决定",
            "verbatim_excerpt": verbatim,
            "situation": "评估新兴项目", "action_or_lesson": "隔离试跑",
            "when_to_use": "做技术选型时",
        })
        _apply_model_distill_to_card(card, client=fake_client)
        assert card["title"] == "新兴项目应先隔离试跑再上线"
        assert "评估新兴项目风险时" in card["one_sentence"]
        assert "测试环境隔离试跑" in card["action_or_lesson"]
        cand = s5_build_candidate(card)
        assert cand["source_mode"] == "evidence_bound_model_distill", (
            f"Expected evidence_bound_model_distill, got: {cand['source_mode']}"
        )
        assert cand["lifecycle_status"] == "candidate"
        assert cand["distill_meta"]["pipeline"] == "S0_S5_model_distill"
        assert cand["confidence"] > 0.7

    def test_model_distill_failure_source_mode(self, tmp_path):
        """When model distill executes but returns insufficient evidence, source_mode=model_distill_contract."""
        def fake_client(messages, config):
            return {"ok": True, "content": json.dumps({
                "verdict": "insufficient_evidence", "summary": "", "detail": "",
                "confidence": 0.0, "supporting_refs": [],
                "review_notes": "no_evidence",
            })}
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定"
        card = _card_with_offsets(tmp_path, verbatim, {
            "title": "测试经验", "one_sentence": "应该先隔离试跑再决定",
            "verbatim_excerpt": verbatim,
            "situation": "评估新兴项目", "action_or_lesson": "隔离试跑",
            "when_to_use": "做技术选型时",
        })
        _apply_model_distill_to_card(card, client=fake_client)
        cand = s5_build_candidate(card)
        assert cand["source_mode"] == "model_distill_contract", (
            f"Expected model_distill_contract, got: {cand['source_mode']}"
        )
        assert cand["lifecycle_status"] == "candidate_not_signed"

    def test_model_not_available_not_accepted(self, tmp_path):
        """When execute=False (model not available), source_mode=heuristic_draft."""
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定"
        card = _card_with_offsets(tmp_path, verbatim, {
            "title": "测试经验", "one_sentence": "应该先隔离试跑再决定",
            "verbatim_excerpt": verbatim,
            "situation": "评估新兴项目", "action_or_lesson": "隔离试跑",
            "when_to_use": "做技术选型时",
        })
        _apply_model_distill_to_card(card, execute=False)
        cand = s5_build_candidate(card)
        assert cand["source_mode"] == "heuristic_draft"
        assert cand["lifecycle_status"] == "candidate_not_signed"

    def test_model_distill_no_client_uses_http_fallback(self, tmp_path, monkeypatch):
        """CLI --model-distill path without fake client should use HTTP fallback, not skip."""
        calls = []

        def mock_http(messages, config):
            calls.append(messages)
            return {"ok": True, "content": json.dumps({
                "verdict": "refined", "title": "HTTP回落蒸馏成功",
                "one_sentence": "通过HTTP回落路径完成模型蒸馏，不依赖fake client",
                "action_or_lesson": "当无fake client时，应使用default_model_config走HTTP回落",
                "when_to_use": "CLI --model-distill 运行时",
                "situation": "CLI无client但有API key的场景",
                "confidence": 0.9, "supporting_refs": ["verbatim"],
            })}

        for _k in ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "MEMCORE_ZHIYI_API_KEY",
                    "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(_k, raising=False)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake-test-key-for-hermetic")

        import tools.xingce_distill as distill_mod
        orig_http = distill_mod._http_chat_completion_with_config
        distill_mod._http_chat_completion_with_config = mock_http
        try:
            card = {
                "title": "测试经验", "one_sentence": "应该先隔离试跑再决定",
                "verbatim_excerpt": "不建议把新兴项目直接上生产，应该先隔离试跑再决定",
                "situation": "评估新兴项目", "action_or_lesson": "隔离试跑",
                "when_to_use": "做技术选型时",
                "source_record": _make_record(), "distill_meta": {},
            }
            _apply_model_distill_to_card(card, execute=True)
            assert len(calls) >= 1, "HTTP fallback must be called when no client provided"
            assert card["title"] == "HTTP回落蒸馏成功"
            assert card["distill_meta"]["source_mode"] == "evidence_bound_model_distill"
        finally:
            distill_mod._http_chat_completion_with_config = orig_http

    def test_pipeline_model_distill_flag_sets_source_mode(self, tmp_path):
        """run_pipeline with model_distill=True + fake client produces evidence_bound_model_distill."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")

        def fake_client(messages, config):
            return {"ok": True, "content": json.dumps({
                "verdict": "refined", "title": "新兴项目应先隔离试跑再上线",
                "one_sentence": "评估新兴项目风险时，不建议直接上生产，应先隔离试跑验证",
                "action_or_lesson": "先在测试环境隔离试跑，确认稳定后再部署到生产环境",
                "when_to_use": "评估新兴或不成熟项目时",
                "situation": "评估新兴远程桌面项目部署风险",
                "confidence": 0.85, "supporting_refs": ["verbatim"],
            })}

        import tools.xingce_distill as distill_mod
        orig_fn = distill_mod._apply_model_distill_to_card

        def patched_distill(card, *, client=None, execute=True, model_config=None):
            return orig_fn(card, client=fake_client, execute=True, model_config=model_config)

        distill_mod._apply_model_distill_to_card = patched_distill
        try:
            report = run_pipeline(str(tmp_path), dry_run=True, model_distill=True)
            cards = report.get("sample_cards", [])
            assert len(cards) >= 1, "Expected at least 1 sample card"
            for card in cards:
                assert card.get("source_mode") == "evidence_bound_model_distill", (
                    f"With model_distill=True + successful client, source_mode must be "
                    f"evidence_bound_model_distill, got: {card.get('source_mode')}"
                )
            stats = report["steps"]["S4_5_model_distill"]
            assert stats["enabled"] is True
            assert stats["refined"] >= 1
        finally:
            distill_mod._apply_model_distill_to_card = orig_fn


# ─── Construction status blocking ──────────────────────────────────────

class TestConstructionStatusBlocking:
    def test_construction_status_pattern_catches_我会让测试(self):
        assert _REJECT_CONSTRUCTION_STATUS.search("我会让测试更严一点")

    def test_construction_status_pattern_catches_这轮我把(self):
        assert _REJECT_CONSTRUCTION_STATUS.search("这轮我把很多文件里的施工阶段头衔改成中性说明了")

    def test_construction_status_pattern_catches_我先把它改(self):
        assert _REJECT_CONSTRUCTION_STATUS.search("我先把它改成中性的然后跑测试")

    def test_construction_status_pattern_catches_然后跑测试(self):
        assert _REJECT_CONSTRUCTION_STATUS.search("我先把它改成中性说明，然后跑测试")

    def test_construction_status_pattern_catches_现在残留(self):
        assert _REJECT_CONSTRUCTION_STATUS.search("现在残留的 P9-System-* 应该只剩历史目录名了")

    def test_construction_status_pattern_catches_本轮改动(self):
        assert _REJECT_CONSTRUCTION_STATUS.search("本轮改动涉及 12 个文件")

    def test_construction_status_blocked_at_s0(self, tmp_path):
        """Construction status records must be rejected at S0."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(
            summary="现在残留的 P9-System-* 应该只剩历史目录名了，我会让测试更严一点",
            detail="assistant 原话：现在残留的 P9-System-* 应该只剩历史目录名了，我会让测试更严一点"
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"Construction status must be rejected at S0, "
            f"worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_construction_status_blocked_at_s0_这轮我把(self, tmp_path):
        """'这轮我把很多文件里的施工阶段头衔改成中性说明了' must be rejected at S0."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(
            summary="这轮我把很多文件里的施工阶段头衔改成中性说明了",
            detail="assistant 原话：这轮我把很多文件里的施工阶段头衔改成中性说明了，我先把它改成中性说明然后跑测试"
        )
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0

    def test_construction_status_blocked_at_s3_card_fields(self, tmp_path):
        """Card with construction status in title/one_sentence must fail S3."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        cards = report.get("sample_cards", [])
        for card in cards:
            title = card.get("title", "")
            one_sentence = card.get("one_sentence", "")
            verbatim_out = card.get("verbatim_excerpt", "")
            combined = title + " " + one_sentence + " " + verbatim_out
            assert not _REJECT_CONSTRUCTION_STATUS.search(combined), (
                f"Card must not contain construction status, got: {combined[:120]}"
            )

    def test_objective_lesson_not_killed_by_construction_filter(self, tmp_path):
        """Objective lesson without construction status keywords must pass."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "涉及生产数据前，先用本地最小闭环验证功能，确认无误后再碰真实环境"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：数据验证。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=False)
        assert report["steps"]["S5_write"].get("written_candidate_files", 0) >= 1, (
            f"Objective lesson should pass, S5={report['steps']['S5_write']}"
        )
        # Verify no construction status in output
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        import glob as globmod
        for f in globmod.glob(str(cand_dir / "*.json")):
            with open(f) as fh:
                cand = json.load(fh)
            combined = cand.get("title", "") + " " + cand.get("summary", "") + " " + cand.get("verbatim_excerpt", "")
            assert not _REJECT_CONSTRUCTION_STATUS.search(combined), (
                f"Objective lesson card must not be caught by construction filter: {combined[:120]}"
            )

    def test_no_blob_bullet_dump_in_sample(self, tmp_path):
        """Sample cards must not contain blob/bullet dump patterns."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        cards = report.get("sample_cards", [])
        for card in cards:
            for field in ("title", "one_sentence", "verbatim_excerpt"):
                val = card.get(field, "")
                assert not val.startswith("•"), f"Card {field} must not be bullet dump: {val[:60]}"
                assert not val.startswith("- "), f"Card {field} must not be bullet dump: {val[:60]}"
                assert len(val) < 1000, f"Card {field} must not be blob dump: len={len(val)}"


# ─── py_compile check ────────────────────────────────────────────────────

class TestPyCompile:
    def test_distill_compiles(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", os.path.join(_REPO_ROOT, "tools", "xingce_distill.py")],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"py_compile failed: {result.stderr}"

    def test_p3_recall_compiles(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", os.path.join(_REPO_ROOT, "src", "p3_recall.py")],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"py_compile failed: {result.stderr}"

    def test_zhixing_preflight_compiles(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", os.path.join(_REPO_ROOT, "src", "zhixing_preflight.py")],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"py_compile failed: {result.stderr}"

    def test_raw_gateway_mcp_compiles(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", os.path.join(_REPO_ROOT, "src", "raw_gateway_mcp.py")],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"py_compile failed: {result.stderr}"


# ─── Source-origin guard broadening ──────────────────────────────────────

class TestSourceOriginGuardBroadening:
    def test_blocks_assistant_plus_source_testing_roles(self):
        """Roles ['assistant','source_testing'] must be blocked for agent narration."""
        text = "页面级工具这边没有直接暴露出来，我先用运行版 HTTP 继续验"
        blocked, reason = _source_origin_guard(
            text,
            participant_attr={"roles": ["assistant", "source_testing"]},
        )
        assert blocked, f"Expected blocked for roles=['assistant','source_testing'], got reason={reason}"

    def test_blocks_assistant_only_roles(self):
        """Roles ['assistant'] must still be blocked (backward compat)."""
        text = "我先用运行版 HTTP 继续验"
        blocked, reason = _source_origin_guard(
            text,
            participant_attr={"roles": ["assistant"]},
        )
        assert blocked

    def test_blocks_assistant_source_testing_smoke_message(self):
        """The exact leaked smoke message must be blocked."""
        text = "现在在 OpenClaw Control 的真实聊天窗口里了。这里的测试只发一条 smoke message"
        blocked, reason = _source_origin_guard(
            text,
            participant_attr={"roles": ["assistant", "source_testing"]},
        )
        assert blocked, f"smoke message leak not blocked, reason={reason}"

    def test_blocks_assistant_source_testing_capability_check(self):
        """The exact leaked capability check message must be blocked."""
        text = "刚刚这条能力检查模式...我先把代码和测试补上"
        blocked, reason = _source_origin_guard(
            text,
            participant_attr={"roles": ["assistant", "source_testing"]},
        )
        assert blocked, f"capability check leak not blocked, reason={reason}"

    def test_allows_user_role(self):
        """Roles ['user'] with construction phrase should NOT be blocked solely by pattern."""
        text = "我先用运行版 HTTP 继续验"
        blocked, reason = _source_origin_guard(
            text,
            participant_attr={"roles": ["user"]},
        )
        assert not blocked, f"User role must not be blocked by construction phrase, got reason={reason}"

    def test_allows_no_participant_attr(self):
        """No participant_attr should not block (falls through to pattern-only)."""
        text = "客观的技术建议内容"
        blocked, reason = _source_origin_guard(text)
        assert not blocked

    def test_s3_blocks_assistant_op_in_card_fields_with_participant_attr(self, tmp_path):
        """s3_validate must reject assistant/source_testing first-person operational text in card fields
        when distill_meta.participant_attribution roles include assistant/source_testing.
        Before the fix, _source_origin_guard was called without participant_attr for card fields,
        so _ASSISTANT_OP_ANYWHERE never triggered."""
        raw_path = _write_raw(tmp_path, '{"text": "客观的摘录内容足够长通过验证验证验证验证验证"}\n')
        for title_text in [
            "我看完现状了：已有 Replay dry-run 是单 case runner；现在我开始加代码和测试",
            "本地施工版最小测试通过。我现在打包并传到 Windows 临时目录",
        ]:
            card = {
                "title": title_text,
                "one_sentence": "客观的摘录内容足够长通过验证验证验证",
                "verbatim_excerpt": "客观的摘录内容足够长通过验证验证验证验证验证",
                "situation": "评估项目风险",
                "action_or_lesson": "先隔离试跑再决定",
                "when_to_use": "评估新兴项目时",
                "source_record": _make_record(source_path=raw_path),
                "distill_meta": {
                    "participant_attribution": {"roles": ["assistant", "source_testing"]},
                },
            }
            ok, reason, _ = s3_validate(card)
            assert not ok, (
                f"s3_validate must reject card with title='{title_text}' for assistant/source_testing roles, "
                f"got ok={ok}, reason={reason}"
            )
            assert "source_origin" in reason, (
                f"Reason must contain 'source_origin', got: {reason}"
            )

    def test_s3_allows_user_role_same_phrases(self, tmp_path):
        """s3_validate must NOT reject the same phrases when participant_attribution roles are ['user'].
        User-role exception must be preserved."""
        raw_path = _write_raw(tmp_path, '{"text": "客观的摘录内容足够长通过验证验证验证验证验证"}\n')
        for title_text in [
            "我看完现状了：已有 Replay dry-run 是单 case runner；现在我开始加代码和测试",
            "本地施工版最小测试通过。我现在打包并传到 Windows 临时目录",
        ]:
            card = {
                "title": title_text,
                "one_sentence": "客观的摘录内容足够长通过验证验证验证",
                "verbatim_excerpt": "客观的摘录内容足够长通过验证验证验证验证验证",
                "situation": "评估项目风险",
                "action_or_lesson": "先隔离试跑再决定",
                "when_to_use": "评估新兴项目时",
                "source_record": _make_record(source_path=raw_path),
                "distill_meta": {
                    "participant_attribution": {"roles": ["user"]},
                },
            }
            ok, reason, _ = s3_validate(card)
            assert ok, (
                f"s3_validate must allow card with title='{title_text}' for user role, "
                f"got ok={ok}, reason={reason}"
            )

    def test_no_model_sample_5000_leak_blocked_in_pipeline(self, tmp_path):
        """The three leaked card texts from no-model sample 5000 must be blocked at S0."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        leaked_texts = [
            "页面级工具这边没有直接暴露出来，我先用运行版 HTTP 继续验",
            "现在在 OpenClaw Control 的真实聊天窗口里了。这里的测试只发一条 smoke message",
            "刚刚这条能力检查模式...我先把代码和测试补上",
        ]
        for i, text in enumerate(leaked_texts):
            rec = _make_record(
                exp_id=f"leak-{i}",
                summary=text,
                detail=f"assistant 原话：{text}",
            )
            (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
            report = run_pipeline(str(tmp_path), dry_run=True)
            assert report["steps"]["S0_select"]["worthy"] == 0, (
                f"Leaked text {i} must be rejected at S0: {text[:60]}"
            )


# ─── No-model --sample 5000 leaked construction cards ────────────────────

class TestSample5000LeakedConstructionCards:
    LEAKED_PHRASE_1 = '刚刚这条"能力检查模式"是被 OpenClaw 真实冒烟测出来的新需求，我先把代码和测试补上，再把这次实测结论写进知识库和代码对照库，先不提交。'
    LEAKED_PHRASE_2 = 'apply-gate 代码已加。现在补测试：先验证缺授权不写，再验证授权后只写 receipt、不写 zhiyi/raw/xingce/hermes/openclaw。'
    LEAKED_PHRASE_3 = '刚才一个小 smoke 命令用错了 import 路径，单测是过的，命令行直 import p6 需要把 src 放进 PYTHONPATH。我先把这个 smoke 补跑干净，再决定要不要上外部测试机。'
    ALLOWED_PHRASE = '我先用运行版 HTTP 继续验'

    # New leaked phrases from no-model --sample 5000 first cards
    LEAKED_PHRASE_4 = '本地和 ubuntu181 的关键验证已经过了，我现在把这次验收写进两处：一份证据笔记，一份源码功能对照。这里会明确写"结构、dry-run、授权 receipt 已闭；正式采用/勘误/主动提示规则还没闭"，避免下次接手的人过度宣称。'
    LEAKED_PHRASE_5 = '先不改代码、不写知识库、不碰 git，我只做只读复盘：先看本机记忆索引，再对 SMB 资料库和源代码对照库，确认我到底做过什么、哪些结论已经落库、哪些还只是口头判断。'
    LEAKED_PHRASE_6 = '刚才那一轮已经确认 5.29 的公开版本、HTTP 验收和"结构闭了但正式反哺未闭"的边界。现在我补看容易误判的老施工线：9860 为什么是系统入口、B110/B111/B125 的生产经验链路到底做到哪里、以及天道样本的口径。'

    def test_phrase1_blocked_assistant_source_testing(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_1,
            participant_attr={"roles": ["assistant", "source_testing"]},
        )
        assert blocked, f"Phrase 1 must be blocked for assistant+source_testing, reason={reason}"

    def test_phrase1_blocked_source_testing_only(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_1,
            participant_attr={"roles": ["source_testing"]},
        )
        assert blocked, f"Phrase 1 must be blocked for source_testing, reason={reason}"

    def test_phrase1_rejected_at_s0_via_self_test(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(exp_id="leak-p1", summary=self.LEAKED_PHRASE_1, detail=f"assistant 原话：{self.LEAKED_PHRASE_1}")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"Phrase 1 must be rejected at S0, worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_phrase2_blocked_assistant_source_testing(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_2,
            participant_attr={"roles": ["assistant", "source_testing"]},
        )
        assert blocked, f"Phrase 2 must be blocked for assistant+source_testing, reason={reason}"

    def test_phrase2_blocked_source_testing_only(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_2,
            participant_attr={"roles": ["source_testing"]},
        )
        assert blocked, f"Phrase 2 must be blocked for source_testing, reason={reason}"

    def test_phrase2_rejected_at_s0_pipeline(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(exp_id="leak-p2", summary=self.LEAKED_PHRASE_2, detail=f"assistant 原话：{self.LEAKED_PHRASE_2}")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"Phrase 2 must be rejected at S0, worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_phrase3_blocked_assistant_source_testing(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_3,
            participant_attr={"roles": ["assistant", "source_testing"]},
        )
        assert blocked, f"Phrase 3 must be blocked for assistant+source_testing, reason={reason}"

    def test_phrase3_blocked_source_testing_only(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_3,
            participant_attr={"roles": ["source_testing"]},
        )
        assert blocked, f"Phrase 3 must be blocked for source_testing, reason={reason}"

    def test_phrase3_rejected_at_s0_pipeline(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(exp_id="leak-p3", summary=self.LEAKED_PHRASE_3, detail=f"assistant 原话：{self.LEAKED_PHRASE_3}")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"Phrase 3 must be rejected at S0, worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_user_role_allowed_through(self):
        blocked, reason = _source_origin_guard(
            self.ALLOWED_PHRASE,
            participant_attr={"roles": ["user"]},
        )
        assert not blocked, f"User role with '{self.ALLOWED_PHRASE}' must NOT be blocked, reason={reason}"

    def test_phrase4_blocked_assistant(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_4,
            participant_attr={"roles": ["assistant"]},
        )
        assert blocked, f"Phrase 4 must be blocked for assistant, reason={reason}"

    def test_phrase4_blocked_source_testing(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_4,
            participant_attr={"roles": ["source_testing"]},
        )
        assert blocked, f"Phrase 4 must be blocked for source_testing, reason={reason}"

    def test_phrase4_rejected_at_s0_pipeline(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(exp_id="leak-p4", summary=self.LEAKED_PHRASE_4, detail=f"assistant 原话：{self.LEAKED_PHRASE_4}")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"Phrase 4 must be rejected at S0, worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_phrase5_blocked_assistant(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_5,
            participant_attr={"roles": ["assistant"]},
        )
        assert blocked, f"Phrase 5 must be blocked for assistant, reason={reason}"

    def test_phrase5_blocked_source_testing(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_5,
            participant_attr={"roles": ["source_testing"]},
        )
        assert blocked, f"Phrase 5 must be blocked for source_testing, reason={reason}"

    def test_phrase5_rejected_at_s0_pipeline(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(exp_id="leak-p5", summary=self.LEAKED_PHRASE_5, detail=f"assistant 原话：{self.LEAKED_PHRASE_5}")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"Phrase 5 must be rejected at S0, worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_phrase6_blocked_assistant(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_6,
            participant_attr={"roles": ["assistant"]},
        )
        assert blocked, f"Phrase 6 must be blocked for assistant, reason={reason}"

    def test_phrase6_blocked_source_testing(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_6,
            participant_attr={"roles": ["source_testing"]},
        )
        assert blocked, f"Phrase 6 must be blocked for source_testing, reason={reason}"

    def test_phrase6_rejected_at_s0_pipeline(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(exp_id="leak-p6", summary=self.LEAKED_PHRASE_6, detail=f"assistant 原话：{self.LEAKED_PHRASE_6}")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"Phrase 6 must be rejected at S0, worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_phrase4_user_role_allowed(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_4,
            participant_attr={"roles": ["user"]},
        )
        assert not blocked, f"User role with phrase 4 must NOT be blocked, reason={reason}"

    def test_phrase5_user_role_allowed(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_5,
            participant_attr={"roles": ["user"]},
        )
        assert not blocked, f"User role with phrase 5 must NOT be blocked, reason={reason}"

    def test_phrase6_user_role_allowed(self):
        blocked, reason = _source_origin_guard(
            self.LEAKED_PHRASE_6,
            participant_attr={"roles": ["user"]},
        )
        assert not blocked, f"User role with phrase 6 must NOT be blocked, reason={reason}"

    def test_objective_lesson_still_passes(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "涉及生产数据前，先用本地最小闭环验证功能，确认无误后再碰真实环境"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：数据验证。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=False)
        assert report["steps"]["S5_write"].get("written_candidate_files", 0) >= 1, (
            f"Objective lesson must still pass, S5={report['steps']['S5_write']}"
        )


# ─── Quarantine blobs CLI wiring ─────────────────────────────────────────

class TestQuarantineBlobWiring:
    def test_quarantine_blobs_dry_run_prints_report(self, tmp_path):
        """--quarantine-blobs --dry-run must print report and exit without running pipeline."""
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        cand_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-qtest", "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate", "title": "- **不建议直接上生产**",
            "summary": "- **应该隔离试跑**", "verbatim_excerpt": "不建议直接上生产",
            "evidence_refs": [], "source_refs": [],
        }
        with open(cand_dir / "xingce-distill-qtest-candidate.json", "w") as f:
            json.dump(cand, f)
        result = subprocess.run(
            [sys.executable, os.path.join(_REPO_ROOT, "tools", "xingce_distill.py"),
             "--root", str(tmp_path), "--quarantine-blobs", "--dry-run"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["scanned"] >= 1
        assert report["blob_found"] >= 1
        assert report["quarantined"] == 0
        assert report["dry_run"] is True

    def test_quarantine_blobs_execute_moves_files(self, tmp_path):
        """--quarantine-blobs --quarantine-execute moves blob candidates to quarantined/."""
        cand_dir = tmp_path / "output" / "xingce_work_experience" / "candidates"
        cand_dir.mkdir(parents=True)
        cand = {
            "candidate_id": "xingce-distill-qexec", "candidate_type": "xingce_work_experience",
            "lifecycle_status": "candidate", "title": "- **应该隔离试跑**",
            "summary": "正常摘要", "verbatim_excerpt": "不建议直接上生产",
            "evidence_refs": [], "source_refs": [],
        }
        cand_path = cand_dir / "xingce-distill-qexec-candidate.json"
        with open(cand_path, "w") as f:
            json.dump(cand, f)
        result = subprocess.run(
            [sys.executable, os.path.join(_REPO_ROOT, "tools", "xingce_distill.py"),
             "--root", str(tmp_path), "--quarantine-blobs", "--quarantine-execute"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        report = json.loads(result.stdout)
        assert report["quarantined"] >= 1
        assert report["dry_run"] is False
        assert not cand_path.exists(), "Candidate should be moved from candidates/"
        q_dir = tmp_path / "output" / "xingce_work_experience" / "quarantined"
        assert q_dir.exists(), "quarantined/ dir should exist"
        q_files = list(q_dir.glob("*.json"))
        assert len(q_files) >= 1
        with open(q_files[0]) as f:
            q_cand = json.load(f)
        assert "_quarantined" in q_cand
        assert q_cand["_quarantined"]["reason"] == "multi_bullet_blob"


# ─── Gate5 owner_sample: construction status S0 guard ────────────────────

class TestGate5OwnerSampleConstructionStatusGuard:
    P1 = "实现、测试样本和知识库都补齐了，现在统一跑验证。先编译新增模块和 p6，再跑全量测试。"
    P2 = "现在进入验证：先跑针对文案边界的测试、diff check 和敏感词扫描...跑完我会停在本地，不提交。"

    def test_p1_reject_construction_status(self):
        assert _REJECT_CONSTRUCTION_STATUS.search(self.P1), "P1 must match _REJECT_CONSTRUCTION_STATUS"

    def test_p2_reject_construction_status(self):
        assert _REJECT_CONSTRUCTION_STATUS.search(self.P2), "P2 must match _REJECT_CONSTRUCTION_STATUS"

    def test_p1_source_origin_guard_no_roles(self):
        blocked, reason = _source_origin_guard(self.P1)
        assert blocked, f"P1 must be blocked without roles, reason={reason}"

    def test_p2_source_origin_guard_no_roles(self):
        blocked, reason = _source_origin_guard(self.P2)
        assert blocked, f"P2 must be blocked without roles, reason={reason}"

    def test_p1_rejected_at_s0_pipeline(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(exp_id="gate5-p1", summary=self.P1, detail=f"assistant 原话：{self.P1}")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"P1 must be rejected at S0, worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_p2_rejected_at_s0_pipeline(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(exp_id="gate5-p2", summary=self.P2, detail=f"assistant 原话：{self.P2}")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        assert report["steps"]["S0_select"]["worthy"] == 0, (
            f"P2 must be rejected at S0, worthy={report['steps']['S0_select']['worthy']}"
        )

    def test_p1_never_in_owner_sample(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(exp_id="gate5-p1b", summary=self.P1, detail=f"上下文：施工。assistant 原话：{self.P1}")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        for card in report.get("sample_cards", []):
            combined = card.get("title", "") + " " + card.get("one_sentence", "") + " " + card.get("verbatim_excerpt", "")
            assert "补齐了" not in combined, f"P1 must not appear in sample_cards: {combined[:80]}"

    def test_p2_never_in_owner_sample(self, tmp_path):
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        rec = _make_record(exp_id="gate5-p2b", summary=self.P2, detail=f"上下文：施工。assistant 原话：{self.P2}")
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True)
        for card in report.get("sample_cards", []):
            combined = card.get("title", "") + " " + card.get("one_sentence", "") + " " + card.get("verbatim_excerpt", "")
            assert "现在进入验证" not in combined, f"P2 must not appear in sample_cards: {combined[:80]}"


# ─── Owner sample: only evidence_bound_model_distill ────────────────────

class TestOwnerSampleOnlyModelDistill:
    def test_owner_sample_only_model_distill(self, tmp_path):
        """owner_sample must contain only source_mode=evidence_bound_model_distill cards."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")

        def fake_client(messages, config):
            return {"ok": True, "content": json.dumps({
                "verdict": "refined", "title": "新兴项目应先隔离试跑再上线",
                "one_sentence": "评估新兴项目风险时，不建议直接上生产，应先隔离试跑验证",
                "action_or_lesson": "先在测试环境隔离试跑，确认稳定后再部署到生产环境",
                "when_to_use": "评估新兴或不成熟项目时",
                "situation": "评估新兴远程桌面项目部署风险",
                "confidence": 0.85, "supporting_refs": ["verbatim"],
            })}

        import tools.xingce_distill as distill_mod
        orig_fn = distill_mod._apply_model_distill_to_card
        def patched_distill(card, *, client=None, execute=True, model_config=None):
            return orig_fn(card, client=fake_client, execute=True, model_config=model_config)
        distill_mod._apply_model_distill_to_card = patched_distill
        try:
            report = run_pipeline(str(tmp_path), dry_run=True, model_distill=True)
            owner = report.get("owner_sample", [])
            assert len(owner) >= 1, "owner_sample must have at least 1 card"
            for card in owner:
                assert card["source_mode"] == "evidence_bound_model_distill", (
                    f"owner_sample card must be model_distill, got: {card['source_mode']}"
                )
        finally:
            distill_mod._apply_model_distill_to_card = orig_fn

    def test_owner_sample_fields_complete(self, tmp_path):
        """Each owner_sample card must have all required fields."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")

        def fake_client(messages, config):
            return {"ok": True, "content": json.dumps({
                "verdict": "refined", "title": "新兴项目应先隔离试跑再上线",
                "one_sentence": "评估新兴项目风险时，不建议直接上生产，应先隔离试跑验证",
                "action_or_lesson": "先在测试环境隔离试跑，确认稳定后再部署到生产环境",
                "when_to_use": "评估新兴或不成熟项目时",
                "situation": "评估新兴远程桌面项目部署风险",
                "confidence": 0.85, "supporting_refs": ["verbatim"],
            })}

        import tools.xingce_distill as distill_mod
        orig_fn = distill_mod._apply_model_distill_to_card
        def patched_distill(card, *, client=None, execute=True, model_config=None):
            return orig_fn(card, client=fake_client, execute=True, model_config=model_config)
        distill_mod._apply_model_distill_to_card = patched_distill
        try:
            report = run_pipeline(str(tmp_path), dry_run=True, model_distill=True)
            owner = report.get("owner_sample", [])
            assert len(owner) >= 1
            required_fields = [
                "title", "one_sentence", "action_or_lesson", "when_to_use",
                "situation", "verbatim_excerpt", "source_ref", "raw_offset",
                "participant_attribution", "source_mode",
            ]
            for card in owner:
                for field in required_fields:
                    assert field in card, f"owner_sample card missing field: {field}"
        finally:
            distill_mod._apply_model_distill_to_card = orig_fn

    def test_owner_sample_empty_without_model_distill(self, tmp_path):
        """Without model_distill, owner_sample must be empty (heuristic cards excluded)."""
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True, model_distill=False)
        owner = report.get("owner_sample", [])
        assert len(owner) == 0, "owner_sample must be empty without model_distill"


# ─── Hermetic model distill tests ────────────────────────────────────────

class TestHermeticModelDistill:
    def test_model_distill_hermetic_no_real_api(self, tmp_path, monkeypatch):
        """Model distill must work with fake key + mocked HTTP, no real API call."""
        for k in ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "MEMCORE_ZHIYI_API_KEY",
                   "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake-hermetic-key-no-real-call")

        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")

        import tools.xingce_distill as distill_mod
        orig_http = distill_mod._http_chat_completion_with_config

        def mock_http(messages, config_dict):
            return {"ok": True, "content": json.dumps({
                "verdict": "refined",
                "title": "新兴项目应先隔离试跑再上线",
                "one_sentence": "评估新兴项目风险时，不建议直接上生产，应先隔离试跑验证",
                "action_or_lesson": "先在测试环境隔离试跑，确认稳定后再部署到生产环境",
                "when_to_use": "评估新兴或不成熟项目时",
                "situation": "评估新兴远程桌面项目部署风险",
                "confidence": 0.85, "supporting_refs": ["verbatim"],
            })}

        distill_mod._http_chat_completion_with_config = mock_http
        try:
            report = run_pipeline(str(tmp_path), dry_run=True, model_distill=True)
            owner = report.get("owner_sample", [])
            assert len(owner) >= 1, "Hermetic model distill must produce owner_sample"
            assert owner[0]["source_mode"] == "evidence_bound_model_distill"
            assert owner[0]["title"] == "新兴项目应先隔离试跑再上线"
        finally:
            distill_mod._http_chat_completion_with_config = orig_http

    def test_model_distill_hermetic_no_keys_still_passes_tests(self, tmp_path, monkeypatch):
        """With all API keys removed, pipeline still passes (heuristic fallback, no crash)."""
        for k in ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "MEMCORE_ZHIYI_API_KEY",
                   "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=True, model_distill=True)
        assert report["steps"]["S0_select"]["worthy"] >= 1
        assert report["steps"]["S4_5_model_distill"]["enabled"] is True

    def test_pipeline_model_distill_with_mock_produces_owner_sample(self, tmp_path, monkeypatch):
        """Full pipeline with model_distill=True + mocked HTTP produces owner_sample with 3-5 cards."""
        for k in ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "MEMCORE_ZHIYI_API_KEY",
                   "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake-hermetic-key")

        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        records = []
        for i in range(5):
            verbatim = f"关于项目{i}的风险评估：不建议直接上生产，应该先隔离试跑验证再决定部署策略，因为太新风险高"
            raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n', name=f"raw{i}.jsonl")
            rec = _make_record(
                exp_id=f"exp-hermetic-{i}",
                detail=f"上下文：评估项目{i}。assistant 原话：{verbatim}",
                source_path=raw_path,
            )
            records.append(json.dumps(rec))
        (zhiyi_dir / "case_memory.jsonl").write_text("\n".join(records) + "\n")

        import tools.xingce_distill as distill_mod
        orig_http = distill_mod._http_chat_completion_with_config
        call_count = [0]

        def mock_http(messages, config_dict):
            call_count[0] += 1
            return {"ok": True, "content": json.dumps({
                "verdict": "refined",
                "title": f"蒸馏卡片{call_count[0]}：先隔离试跑再上线",
                "one_sentence": f"针对项目风险，不建议直接上生产环境，应先隔离试跑验证稳定性",
                "action_or_lesson": "在测试环境隔离试跑，确认稳定后再部署到生产环境",
                "when_to_use": "评估新兴或不成熟项目时",
                "situation": f"评估项目{call_count[0]}的部署风险",
                "confidence": 0.85, "supporting_refs": ["verbatim"],
            })}

        distill_mod._http_chat_completion_with_config = mock_http
        try:
            report = run_pipeline(str(tmp_path), dry_run=True, model_distill=True, sample=5)
            owner = report.get("owner_sample", [])
            assert len(owner) >= 3, f"Expected >=3 owner_sample cards, got {len(owner)}"
            for card in owner:
                assert card["source_mode"] == "evidence_bound_model_distill"
                assert card["title"]
                assert card["one_sentence"]
                assert card["action_or_lesson"]
                assert card["when_to_use"]
                assert card["situation"]
                assert card["verbatim_excerpt"]
                assert "participant_attribution" in card
        finally:
            distill_mod._http_chat_completion_with_config = orig_http


# ─── Gate 5: owner_sample prefilter & bounded model distill ────────────────

class TestGate5OwnerSamplePrefilter:
    def test_construction_status_blocked_by_s3(self):
        """Construction status sentence must not pass S3."""
        card = {
            "title": "修补已落进源码",
            "one_sentence": "修补已经落进源码：Windows 安装器会优先找已有 Claude 配置，探测层也复用 Claude connector 的候选路径。现在跑相关测试，过了之后再重新打包同步到 Windows。",
            "verbatim_excerpt": "修补已经落进源码：Windows 安装器会优先找已有 Claude 配置，探测层也复用 Claude connector 的候选路径。现在跑相关测试，过了之后再重新打包同步到 Windows。",
            "action_or_lesson": "跑完测试后打包同步到目标机器",
            "when_to_use": "同步代码到 Windows 时",
            "situation": "Windows 安装器配置同步",
            "source_record": {},
            "distill_meta": {"participant_attribution": {"roles": ["source_testing"]}},
        }
        ok, reason, _ = s3_validate(card)
        assert not ok, f"Construction status must be blocked by S3, got ok={ok} reason={reason}"
        assert "construction" in reason or "source_origin" in reason

    def test_construction_status_blocked_by_origin_guard(self):
        """Construction status with source_testing role blocked by _source_origin_guard."""
        text = "修补已经落进源码：Windows 安装器会优先找已有 Claude 配置，探测层也复用 Claude connector 的候选路径。现在跑相关测试，过了之后再重新打包同步到 Windows。"
        pa = {"roles": ["source_testing"]}
        blocked, reason = _source_origin_guard(text, participant_attr=pa)
        assert blocked, f"Expected blocked, got {blocked}, reason={reason}"

    def test_construction_status_prefilter_rejected(self):
        """Construction status card rejected by prefilter."""
        card = {
            "title": "修补已落进源码",
            "one_sentence": "修补已经落进源码：Windows 安装器会优先找已有 Claude 配置，探测层也复用 Claude connector 的候选路径。现在跑相关测试，过了之后再重新打包同步到 Windows。",
            "verbatim_excerpt": "修补已经落进源码：Windows 安装器会优先找已有 Claude 配置",
            "action_or_lesson": "跑完测试后打包同步到目标机器",
            "distill_meta": {"participant_attribution": {"roles": ["source_testing"]}},
        }
        suitable, reason = _owner_sample_prefilter(card)
        assert not suitable, f"Expected not suitable, got {suitable}, reason={reason}"

    def test_objective_lesson_passes_s3(self, tmp_path):
        """Objective reusable lesson must pass S3."""
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        card = {
            "title": "新兴项目部署风险：应先隔离试跑再上线生产环境",
            "one_sentence": verbatim,
            "verbatim_excerpt": verbatim,
            "action_or_lesson": "先在隔离环境试跑，确认稳定后再决定是否上生产",
            "when_to_use": "评估新兴或不成熟的项目时",
            "situation": "评估新兴远程桌面项目 GSDesk 的部署风险",
            "source_record": _make_record(detail=f"上下文：评估。assistant 原话：{verbatim}", source_path=raw_path),
            "distill_meta": {"participant_attribution": {"roles": ["unknown"]}},
        }
        ok, reason, _ = s3_validate(card)
        assert ok, f"Objective lesson must pass S3, got ok={ok} reason={reason}"

    def test_objective_lesson_passes_prefilter(self):
        """Objective reusable lesson passes prefilter."""
        card = {
            "title": "新兴项目应先隔离试跑再上线",
            "one_sentence": "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高",
            "verbatim_excerpt": "不建议把新兴项目直接上生产",
            "action_or_lesson": "先在隔离环境试跑，确认稳定后再决定",
            "distill_meta": {"participant_attribution": {"roles": ["unknown"]}},
        }
        suitable, reason = _owner_sample_prefilter(card)
        assert suitable, f"Expected suitable, got reason={reason}"

    def test_blob_card_prefilter_rejected(self):
        """Multi-bullet blob card rejected by prefilter."""
        card = {
            "title": "技术栈总结",
            "one_sentence": "- **Python**: 主力语言\n- **Node**: 前端工具",
            "verbatim_excerpt": "- **Python**: 主力语言\n- **Node**: 前端工具",
            "action_or_lesson": "选择合适的技术栈",
            "distill_meta": {"participant_attribution": {"roles": ["unknown"]}},
        }
        suitable, reason = _owner_sample_prefilter(card)
        assert not suitable
        assert reason == "prefilter_blob"

    def test_naming_leak_prefilter_rejected(self):
        """Naming leak card rejected by prefilter."""
        card = {
            "title": "zhiyi_recall 配置",
            "one_sentence": "配置 zhiyi_recall 的参数",
            "verbatim_excerpt": "配置 zhiyi_recall 的参数",
            "action_or_lesson": "正确配置 zhiyi_recall",
            "distill_meta": {"participant_attribution": {"roles": ["unknown"]}},
        }
        suitable, reason = _owner_sample_prefilter(card)
        assert not suitable
        assert reason == "prefilter_naming_leak"


class TestGate5BoundedModelDistill:
    def test_bounded_model_distill_respects_limit(self, tmp_path, monkeypatch):
        """With model_distill_limit=3, only 3 attempts are made."""
        for k in ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "MEMCORE_ZHIYI_API_KEY",
                   "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake-hermetic-key")

        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        records = []
        for i in range(10):
            verbatim = f"关于项目{i}的风险评估：不建议直接上生产，应该先隔离试跑验证再决定部署策略，因为太新风险高"
            raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n', name=f"raw{i}.jsonl")
            rec = _make_record(
                exp_id=f"exp-bounded-{i}",
                detail=f"上下文：评估项目{i}。assistant 原话：{verbatim}",
                source_path=raw_path,
            )
            records.append(json.dumps(rec))
        (zhiyi_dir / "case_memory.jsonl").write_text("\n".join(records) + "\n")

        import tools.xingce_distill as distill_mod
        orig_http = distill_mod._http_chat_completion_with_config
        call_count = [0]

        def mock_http(messages, config_dict):
            call_count[0] += 1
            return {"ok": True, "content": json.dumps({
                "verdict": "refined",
                "title": f"蒸馏卡片{call_count[0]}：先隔离试跑再上线",
                "one_sentence": f"针对项目风险，不建议直接上生产环境，应先隔离试跑验证稳定性",
                "action_or_lesson": "在测试环境隔离试跑，确认稳定后再部署到生产环境",
                "when_to_use": "评估新兴或不成熟项目时",
                "situation": f"评估项目{call_count[0]}的部署风险",
                "confidence": 0.85, "supporting_refs": ["verbatim"],
            })}

        distill_mod._http_chat_completion_with_config = mock_http
        try:
            report = run_pipeline(
                str(tmp_path), dry_run=True, model_distill=True,
                model_distill_limit=3, sample=10,
            )
            md = report["steps"]["S4_5_model_distill"]
            assert md["limit"] == 3
            assert md["attempted"] <= 3, f"Expected <=3 attempts, got {md['attempted']}"
            owner = report.get("owner_sample", [])
            assert len(owner) <= 5
            for card in owner:
                assert card["source_mode"] == "evidence_bound_model_distill"
        finally:
            distill_mod._http_chat_completion_with_config = orig_http

    def test_bounded_model_distill_prefilter_stats(self, tmp_path, monkeypatch):
        """Prefilter stats are reported in model distill output."""
        for k in ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "MEMCORE_ZHIYI_API_KEY",
                   "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake-hermetic-key")

        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{verbatim}"}}\n')
        rec = _make_record(detail=f"上下文：评估项目。assistant 原话：{verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")

        import tools.xingce_distill as distill_mod
        orig_http = distill_mod._http_chat_completion_with_config

        def mock_http(messages, config_dict):
            return {"ok": True, "content": json.dumps({
                "verdict": "refined",
                "title": "新兴项目应先隔离试跑再上线",
                "one_sentence": "不建议把新兴项目直接上生产，应该先隔离试跑再决定",
                "action_or_lesson": "先在隔离环境试跑，确认稳定后再上生产",
                "when_to_use": "评估新兴项目时",
                "situation": "评估新兴项目的部署风险",
                "confidence": 0.85, "supporting_refs": ["verbatim"],
            })}

        distill_mod._http_chat_completion_with_config = mock_http
        try:
            report = run_pipeline(
                str(tmp_path), dry_run=True, model_distill=True,
                model_distill_limit=10,
            )
            md = report["steps"]["S4_5_model_distill"]
            assert "prefilter_total" in md
            assert "prefilter_passed" in md
            assert "prefilter_rejected" in md
            assert md["prefilter_total"] >= 1
        finally:
            distill_mod._http_chat_completion_with_config = orig_http

    def test_construction_status_never_in_owner_sample(self, tmp_path, monkeypatch):
        """Construction status card must never appear in owner_sample even with model distill."""
        for k in ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "MEMCORE_ZHIYI_API_KEY",
                   "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake-hermetic-key")

        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        bad_verbatim = "修补已经落进源码：Windows 安装器会优先找已有 Claude 配置，探测层也复用 Claude connector 的候选路径。现在跑相关测试，过了之后再重新打包同步到 Windows。"
        good_verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_path = _write_raw(tmp_path, f'{{"text": "{bad_verbatim}"}}\n{{"text": "{good_verbatim}"}}\n')
        rec1 = _make_record(exp_id="exp-bad", detail=f"上下文：同步。assistant 原话：{bad_verbatim}", source_path=raw_path)
        rec2 = _make_record(exp_id="exp-good", detail=f"上下文：评估。assistant 原话：{good_verbatim}", source_path=raw_path)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec1) + "\n" + json.dumps(rec2) + "\n")

        import tools.xingce_distill as distill_mod
        orig_http = distill_mod._http_chat_completion_with_config

        def mock_http(messages, config_dict):
            return {"ok": True, "content": json.dumps({
                "verdict": "refined",
                "title": "新兴项目应先隔离试跑再上线",
                "one_sentence": "不建议把新兴项目直接上生产，应该先隔离试跑再决定",
                "action_or_lesson": "先在隔离环境试跑，确认稳定后再上生产",
                "when_to_use": "评估新兴项目时",
                "situation": "评估新兴项目的部署风险",
                "confidence": 0.85, "supporting_refs": ["verbatim"],
            })}

        distill_mod._http_chat_completion_with_config = mock_http
        try:
            report = run_pipeline(str(tmp_path), dry_run=True, model_distill=True, model_distill_limit=10)
            owner = report.get("owner_sample", [])
            for card in owner:
                combined = card["title"] + " " + card["one_sentence"] + " " + card.get("action_or_lesson", "")
                assert "修补已经落进源码" not in combined, f"Construction status leaked into owner_sample: {card['title']}"
                assert "打包同步" not in combined, f"Construction status leaked into owner_sample: {card['title']}"
        finally:
            distill_mod._http_chat_completion_with_config = orig_http

    def test_post_refine_revokes_source_testing_status_and_continues(self, tmp_path, monkeypatch):
        """A polished model rewrite into operational status is revoked, then later good cards continue."""
        for k in ("MINIMAX_API_KEY", "MINIMAX_CN_API_KEY", "MEMCORE_ZHIYI_API_KEY",
                   "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake-hermetic-key")

        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        good_verbatims = [
            f"关于项目{i}的风险评估：不建议直接上生产，应该先隔离试跑验证再决定部署策略，因为太新风险高"
            for i in range(6)
        ]
        raw_path = _write_raw(
            tmp_path,
            "".join([f'{{"text": "{v}"}}\n' for v in good_verbatims]),
        )
        records = []
        for i, verbatim in enumerate(good_verbatims):
            records.append(json.dumps(_make_record(
                exp_id=f"exp-good-after-revoke-{i}",
                detail=f"上下文：评估项目{i}。assistant 原话：{verbatim}",
                source_path=raw_path,
            )))
        (zhiyi_dir / "case_memory.jsonl").write_text("\n".join(records) + "\n")

        import tools.xingce_distill as distill_mod
        orig_http = distill_mod._http_chat_completion_with_config
        call_count = [0]

        def mock_http(messages, config_dict):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"ok": True, "content": json.dumps({
                    "verdict": "refined",
                    "title": "写入线修改后优先运行最贴近的测试",
                    "one_sentence": "写入线修改完成后，应优先运行与改动最相关的测试用例。",
                    "action_or_lesson": "修改完成后先跑编译并执行最贴近的测试用例。",
                    "when_to_use": "代码修改验证阶段",
                    "situation": "多条写入线同时修改后进入测试验证",
                    "confidence": 0.85,
                    "supporting_refs": ["verbatim"],
                })}
            return {"ok": True, "content": json.dumps({
                "verdict": "refined",
                "title": f"项目{call_count[0]}应先隔离试跑再上线",
                "one_sentence": "不建议把新兴项目直接上生产，应该先隔离试跑再决定。",
                "action_or_lesson": "先在隔离环境试跑，确认稳定后再上生产。",
                "when_to_use": "评估新兴项目时",
                "situation": "评估新兴项目的部署风险",
                "confidence": 0.85,
                "supporting_refs": ["verbatim"],
            })}

        distill_mod._http_chat_completion_with_config = mock_http
        try:
            report = run_pipeline(str(tmp_path), dry_run=True, model_distill=True, model_distill_limit=6)
            md = report["steps"]["S4_5_model_distill"]
            assert md["revalidation_revoked"] >= 1
            assert md["clean_owner_sample"] >= 3
            assert md["attempted"] > md["clean_owner_sample"]
            owner = report.get("owner_sample", [])
            assert len(owner) >= 3
            for card in owner:
                combined = " ".join([
                    card.get("title", ""),
                    card.get("one_sentence", ""),
                    card.get("action_or_lesson", ""),
                    card.get("verbatim_excerpt", ""),
                ])
                assert "写入线" not in combined
                assert "接下来先跑" not in combined
                assert card["source_mode"] == "evidence_bound_model_distill"
        finally:
            distill_mod._http_chat_completion_with_config = orig_http


# ─── Gate 7: Byte offset回源真 ────────────────────────────────────────────

class TestGate7ByteOffsetProvenance:
    def test_jsonl_field_offset_updated_when_original_wrong(self, tmp_path):
        """When verbatim is in a JSONL field but original byte_offsets point elsewhere,
        candidate evidence_refs.byte_offsets must be updated to actual verbatim location."""
        import re
        from tools.xingce_distill import _compute_verbatim_byte_offsets

        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定"
        raw_line = json.dumps({
            "timestamp": "2026-06-30T12:00:00Z",
            "session_id": "test-session",
            "msg_id": "msg-1",
            "payload": {"message": verbatim},
        }, ensure_ascii=False)
        raw_path = _write_raw(tmp_path, raw_line + "\n")

        raw_bytes = raw_line.encode("utf-8")
        verbatim_bytes = verbatim.encode("utf-8")
        actual_start = raw_bytes.find(verbatim_bytes)
        assert actual_start >= 0, "verbatim must be findable in raw bytes"

        rec = _make_record(
            detail=f"上下文：评估项目。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        refs = json.loads(rec["source_refs"])
        refs["byte_offsets"] = {"msg-1": {"start": 0, "end": 10}}
        rec["source_refs"] = json.dumps(refs)

        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=False)
        n = report["steps"]["S5_write"].get("written_candidate_files", 0)
        assert n >= 1, f"Expected >=1 candidate, got {n}"

        import glob as globmod
        cand_files = globmod.glob(str(tmp_path / "output" / "xingce_work_experience" / "candidates" / "xingce-*-candidate.json"))
        assert cand_files, "Expected at least one candidate file"
        with open(cand_files[0]) as f:
            cand = json.load(f)

        er = cand["evidence_refs"][0]
        offsets = er.get("byte_offsets", {})
        assert "_computed_verbatim" not in offsets
        bo = offsets
        start = bo["start"]
        end = bo["end"]

        with open(raw_path, "rb") as f:
            f.seek(int(start))
            chunk = f.read(int(end) - int(start))
            extracted = chunk.decode("utf-8", errors="ignore")
        assert extracted == cand["verbatim_excerpt"] == verbatim, (
            f"byte_offsets [{start}:{end}] must contain verbatim. "
            f"Got: {extracted[:80]} vs verbatim: {verbatim[:80]}"
        )
        assert cand.get("verbatim_sha256") == hashlib.sha256(chunk).hexdigest()

    def test_compute_verbatim_byte_offsets_direct(self, tmp_path):
        """_compute_verbatim_byte_offsets finds verbatim in a simple text file."""
        from tools.xingce_distill import _compute_verbatim_byte_offsets
        verbatim = "不建议直接上生产应该先隔离试跑"
        content = f"prefix {verbatim} suffix"
        raw_path = _write_raw(tmp_path, content)
        offsets = _compute_verbatim_byte_offsets(verbatim, raw_path)
        assert offsets is not None
        with open(raw_path, "rb") as f:
            f.seek(offsets["start"])
            chunk = f.read(offsets["end"] - offsets["start"])
        assert chunk.decode("utf-8") == verbatim

    def test_compute_verbatim_byte_offsets_jsonl_field(self, tmp_path):
        """_compute_verbatim_byte_offsets finds verbatim in a JSONL payload.message field."""
        from tools.xingce_distill import _compute_verbatim_byte_offsets
        verbatim = "评估新兴项目风险时应先隔离试跑验证"
        raw_line = json.dumps({
            "timestamp": "2026-06-30T12:00:00Z",
            "payload": {"message": verbatim},
        }, ensure_ascii=False)
        raw_path = _write_raw(tmp_path, raw_line + "\n")
        offsets = _compute_verbatim_byte_offsets(verbatim, raw_path)
        assert offsets is not None
        with open(raw_path, "rb") as f:
            f.seek(offsets["start"])
            chunk = f.read(offsets["end"] - offsets["start"])
        assert chunk.decode("utf-8") == verbatim

    def test_compute_verbatim_byte_offsets_returns_none_for_missing(self, tmp_path):
        """_compute_verbatim_byte_offsets returns None when verbatim not in file."""
        from tools.xingce_distill import _compute_verbatim_byte_offsets
        raw_path = _write_raw(tmp_path, '{"text": "完全无关的内容"}\n')
        offsets = _compute_verbatim_byte_offsets("这段话不在文件里", raw_path)
        assert offsets is None

    def test_written_candidate_byte_offset_spot_check(self, tmp_path):
        """Every written candidate's evidence_refs.byte_offsets must point to actual verbatim in raw."""
        import re
        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)

        def fake_client(messages, config):
            return {"ok": True, "content": json.dumps({
                "verdict": "refined", "title": "新兴项目应先隔离试跑再上线",
                "one_sentence": "评估新兴项目风险时，不建议直接上生产，应先隔离试跑验证",
                "action_or_lesson": "先在测试环境隔离试跑，确认稳定后再部署到生产环境",
                "when_to_use": "评估新兴或不成熟项目时",
                "situation": "评估新兴远程桌面项目部署风险",
                "confidence": 0.85, "supporting_refs": ["verbatim"],
            })}

        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        raw_line = json.dumps({
            "timestamp": "2026-06-30T12:00:00Z",
            "session_id": "test-session",
            "msg_id": "msg-1",
            "payload": {"message": verbatim},
        }, ensure_ascii=False)
        raw_path = _write_raw(tmp_path, raw_line + "\n")
        rec = _make_record(
            detail=f"上下文：评估项目。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        refs = json.loads(rec["source_refs"])
        refs["byte_offsets"] = {"msg-1": {"start": 0, "end": 5}}
        rec["source_refs"] = json.dumps(refs)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")

        import tools.xingce_distill as distill_mod
        orig_http = distill_mod._http_chat_completion_with_config
        distill_mod._http_chat_completion_with_config = lambda msgs, cfg: fake_client(msgs, cfg)
        had_key = "MINIMAX_API_KEY" in os.environ
        orig_key_val = os.environ.get("MINIMAX_API_KEY")
        os.environ["MINIMAX_API_KEY"] = "fake-test-key-for-hermetic"
        try:
            report = run_pipeline(str(tmp_path), dry_run=False, model_distill=True)
            n = report["steps"]["S5_write"].get("written_candidate_files", 0)
            assert n >= 1, f"Expected >=1 written candidate, got {n}"

            import glob as globmod
            for cand_path in globmod.glob(str(tmp_path / "output" / "xingce_work_experience" / "candidates" / "*.json")):
                with open(cand_path) as f:
                    cand = json.load(f)
                er = cand["evidence_refs"][0]
                resolved_path = er.get("resolved_source_path", "")
                offsets = er.get("byte_offsets", {})
                verbatim_out = cand.get("verbatim_excerpt", "")

                assert resolved_path, "Candidate must have resolved_source_path"
                assert offsets, "Candidate must have byte_offsets"
                assert os.path.isfile(resolved_path), f"resolved_source_path must exist: {resolved_path}"

                assert "_computed_verbatim" not in offsets
                bo = offsets
                start = bo["start"]
                end = bo["end"]
                with open(resolved_path, "rb") as f:
                    f.seek(int(start))
                    chunk = f.read(int(end) - int(start))
                    extracted = chunk.decode("utf-8", errors="ignore")
                assert extracted == verbatim_out, (
                    f"Candidate {cand['candidate_id']}: byte_offsets [{start}:{end}] "
                    f"must contain verbatim_excerpt. Got: {extracted[:80]} vs {verbatim_out[:80]}"
                )
                assert cand.get("verbatim_sha256") == hashlib.sha256(chunk).hexdigest()
        finally:
            distill_mod._http_chat_completion_with_config = orig_http
            if had_key:
                os.environ["MINIMAX_API_KEY"] = orig_key_val
            else:
                os.environ.pop("MINIMAX_API_KEY", None)

    def test_original_byte_offsets_preserved_when_correct(self, tmp_path):
        """When original byte_offsets already point to verbatim, they should be preserved."""
        from tools.xingce_distill import _compute_verbatim_byte_offsets

        verbatim = "不建议把新兴项目直接上生产，应该先隔离试跑再决定，因为项目太新风险高"
        content = f"prefix {verbatim} suffix"
        raw_path = _write_raw(tmp_path, content)

        offsets = _compute_verbatim_byte_offsets(verbatim, raw_path)
        assert offsets is not None

        rec = _make_record(
            detail=f"上下文：评估项目。assistant 原话：{verbatim}",
            source_path=raw_path,
        )
        refs = json.loads(rec["source_refs"])
        refs["byte_offsets"] = {"msg-1": offsets}
        rec["source_refs"] = json.dumps(refs)

        zhiyi_dir = tmp_path / "zhiyi" / "case_memory"
        zhiyi_dir.mkdir(parents=True)
        (zhiyi_dir / "case_memory.jsonl").write_text(json.dumps(rec) + "\n")
        report = run_pipeline(str(tmp_path), dry_run=False)
        n = report["steps"]["S5_write"].get("written_candidate_files", 0)
        assert n >= 1

        import glob as globmod
        cand_files = globmod.glob(str(tmp_path / "output" / "xingce_work_experience" / "candidates" / "*.json"))
        with open(cand_files[0]) as f:
            cand = json.load(f)
        er = cand["evidence_refs"][0]
        # When original offsets are correct, the standard flat offsets are used.
        assert "_computed_verbatim" not in er["byte_offsets"]
        bo = er["byte_offsets"]
        assert bo["start"] == offsets["start"]
        assert bo["end"] == offsets["end"]
