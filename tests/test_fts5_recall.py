import importlib
import json
import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _reload_p3(tmp_path, monkeypatch, *, fts5_enabled=False):
    memcore = tmp_path / "memcore"
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("MEMCORE_ZHIYI_ROOT_OVERRIDE", str(memcore / "zhiyi"))
    monkeypatch.setenv("MEMCORE_FTS5_RECALL_INDEX_PATH", str(memcore / "runtime" / "fts5" / "p3.sqlite3"))
    if fts5_enabled:
        monkeypatch.setenv("MEMCORE_FTS5_RECALL", "1")
    else:
        monkeypatch.delenv("MEMCORE_FTS5_RECALL", raising=False)
    for name in [
        "config_loader",
        "src.config_loader",
        "src.fts5_recall_index",
        "src.p3_recall",
    ]:
        sys.modules.pop(name, None)
    p3 = importlib.import_module("src.p3_recall")
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    return p3


def _write_memory(tmp_path, *, exp_id, summary, detail, source_system="codex"):
    memcore = tmp_path / "memcore"
    raw_path = memcore / "memory" / source_system / "local" / "project-a" / f"{exp_id}.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps({"text": detail}, ensure_ascii=False), encoding="utf-8")
    zhiyi_path = memcore / "zhiyi" / "case_memory" / "case_memory.jsonl"
    zhiyi_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "exp_id": exp_id,
        "type": "case_memory",
        "summary": summary,
        "detail": detail,
        "score": 0.8,
        "scope": "window/project-a",
        "source_refs": {
            "source_system": source_system,
            "source_path": str(raw_path),
            "msg_ids": [exp_id],
        },
    }
    with open(zhiyi_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def test_substring_mode_does_not_load_an_empty_vector_contract(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch)
    config_path = tmp_path / "model_config.json"
    config_path.write_text(json.dumps({"recall": {"mode": "substring"}}), encoding="utf-8")
    p3._CONFIG_PATH = str(config_path)
    p3._lancedb_v2_cache.update({
        "tok": None,
        "model": None,
        "tbl": None,
        "row_count": None,
        "status": {},
    })

    def fail_if_loaded():
        raise AssertionError("substring mode must not load a vector contract")

    monkeypatch.setattr(p3, "_v2_model_contract", fail_if_loaded)

    engine = p3._get_v2_engine()
    status = p3.vector_runtime_status(load_model=False)

    assert engine["model"] is None
    assert engine["tbl"] is None
    assert status["status"] == "off"
    assert status["expected"] is False
    assert status["issues"] == []


def test_fts5_index_builds_and_searches_trigram(tmp_path):
    from src.fts5_recall_index import build_index, capability_probe, search_index

    probe = capability_probe()
    assert probe["ok"] is True
    memories = [
        {
            "exp_id": "exp-remote-desktop",
            "_type": "case_memory",
            "scope": "window/project-a",
            "summary": "远程桌面不要直暴露3389",
            "detail": "先用跳板或 VPN，再开放远程桌面。",
            "source_refs": {"source_path": str(tmp_path / "source.jsonl")},
        }
    ]
    index_path = tmp_path / "fts5.sqlite3"
    built = build_index(memories, str(index_path))
    assert built["ok"] is True
    assert built["doc_count"] == 1

    found = search_index(query="远程桌面 3389", index_path=str(index_path), expected_signature=built["corpus_signature"])
    assert found["ok"] is True
    assert found["status"]["applied"] is True
    assert found["rows"][0]["exp_id"] == "exp-remote-desktop"


def test_fts5_search_reports_concurrent_build_as_not_ready(tmp_path):
    from src.fts5_recall_index import search_index

    index_path = tmp_path / "fts5-building.sqlite3"
    con = sqlite3.connect(index_path)
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute(
        "CREATE TABLE docs("
        "doc_id TEXT PRIMARY KEY, exp_id TEXT, memory_type TEXT, scope TEXT, "
        "summary TEXT, detail TEXT, source_refs TEXT, content_sha256 TEXT NOT NULL)"
    )
    con.execute(
        "CREATE VIRTUAL TABLE docs_fts "
        "USING fts5(doc_id UNINDEXED, summary, detail, tokenize='trigram')"
    )
    con.commit()
    con.close()

    result = search_index(
        query="开局注入防截断",
        index_path=str(index_path),
        expected_signature="pending-build-signature",
    )

    assert result["ok"] is False
    assert result["rows"] == []
    assert result["status"]["error"] == "index_not_ready"
    assert result["status"]["build_in_progress"] is True


def test_p3_substring_uses_fts5_only_when_explicitly_enabled(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    _write_memory(
        tmp_path,
        exp_id="exp-slow-meta",
        summary="普通状态流水",
        detail="这条只是普通流水，包含远程和桌面两个词，但没有 3389。",
    )
    _write_memory(
        tmp_path,
        exp_id="exp-3389",
        summary="远程桌面不要直暴露3389",
        detail="远程桌面端口 3389 不要直接暴露在公网。",
    )

    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    default_result = p3.handle_recall({"query": "远程桌面 3389", "recall_mode": "substring", "top_k": 2})
    assert "fts5_applied" not in default_result

    from src.fts5_recall_index import build_index

    index_path = tmp_path / "memcore" / "runtime" / "fts5" / "p3.sqlite3"
    built = build_index(p3.get_memories(), str(index_path))
    assert built["ok"] is True

    enabled_result = p3.handle_recall({
        "query": "远程桌面 3389",
        "recall_mode": "substring",
        "top_k": 2,
        "fts5_recall": True,
    })
    assert enabled_result["fts5_applied"] is True
    assert enabled_result["fts5_status"]["error"] is None
    assert enabled_result["fts5_status"]["stale"] is False
    assert enabled_result["default_vector_freshness_covered"] is False
    assert enabled_result["primary_recall_backend"] == "keyword+fts5"
    assert enabled_result["ranking_owner"] in ("keyword", "keyword+fts5")
    assert enabled_result["matched_memories"][0]["exp_id"] == "exp-3389"
    assert enabled_result["matched_memories"][0]["matched_by"] == "fts5_bm25"
    assert enabled_result["matched_memories"][0]["rank_reason"] == "sqlite_fts5_trigram_bm25"
    assert "_fts5" not in enabled_result["matched_memories"][0]["archive_card"]


def test_p3_default_recall_uses_bounded_recent_delta_without_fts5(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    _write_memory(
        tmp_path,
        exp_id="exp-old-vector-hit",
        summary="旧向量命中",
        detail="这条旧记忆会模拟 vector 先命中，但不包含新 token。",
    )
    p3.get_memories()

    def fake_vector_search(_query, top_k=5, scope_filter=None, type_filter=None):
        raise AssertionError("bounded recent_delta hit must return before vector search")

    monkeypatch.setattr(p3, "vector_search_v2", fake_vector_search)
    monkeypatch.setattr(p3, "vector_runtime_status", lambda load_model=False: {"ok": True, "expected": True})

    token = "fresh-default-recall-token-0704"
    _write_memory(
        tmp_path,
        exp_id="exp-fresh-default-recall",
        summary=f"刚写入的新记忆 {token}",
        detail=f"默认召回必须立刻看见这条新记忆，nonce={token}。",
    )

    result = p3.handle_recall({"query": token, "top_k": 3})
    ids = [item.get("exp_id") for item in result["matched_memories"]]

    assert result["mode"] == "vector_with_bounded_recent_delta"
    assert "fts5_applied" not in result
    assert result["recent_delta_applied"] is True
    assert result["freshness_fast_path"] == "bounded_recent_delta"
    assert result["freshness_boundary"] == "bounded_recent_delta"
    assert result["default_recall_freshness_covered"] is True
    assert result["default_vector_freshness_covered"] is False
    assert result["vector_search_deferred_for_recent_delta"] is True
    assert ids[0] == "exp-fresh-default-recall"
    assert result["matched_memories"][0]["matched_by"] == "recent_delta"


def test_p3_default_recall_uses_bounded_recent_tail_on_cold_cache(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    token = "fresh-default-cold-tail-token-0704"
    _write_memory(
        tmp_path,
        exp_id="exp-fresh-cold-tail",
        summary=f"冷启动刚写入的新记忆 {token}",
        detail=f"默认召回在无 cache baseline 时也必须先看 bounded recent tail，nonce={token}。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    p3._MEMORY_LAST_SERVED_SIGNATURE = None

    def fake_vector_search(_query, top_k=5, scope_filter=None, type_filter=None):
        raise AssertionError("cold bounded recent tail hit must return before vector search")

    monkeypatch.setattr(p3, "vector_search_v2", fake_vector_search)
    monkeypatch.setattr(p3, "vector_runtime_status", lambda load_model=False: {"ok": True, "expected": True})

    result = p3.handle_recall({"query": token, "top_k": 3})

    assert result["mode"] == "vector_with_bounded_recent_delta"
    assert result["recent_delta_applied"] is True
    assert result["recent_delta_status"]["reason"] == "bounded_recent_tail_default_recall_hit"
    assert result["recent_delta_status"]["cold_start_tail"] is True
    assert result["freshness_fast_path"] == "bounded_recent_delta"
    assert result["default_recall_freshness_covered"] is True
    assert result["default_vector_freshness_covered"] is False
    assert result["vector_search_deferred_for_recent_delta"] is True
    assert result["structure_analysis"]["reason"] == "skipped_recent_delta_fast_path"
    assert result["matched_memories"][0]["exp_id"] == "exp-fresh-cold-tail"
    assert result["matched_memories"][0]["matched_by"] == "recent_delta"


def test_p3_explicit_fts5_request_schedules_missing_index_refresh_off_request_path(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-no-index",
        summary="开局注入防截断",
        detail="开局注入只留阅读区 lanes，避免客户端截断。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    first = p3.handle_recall({"query": "开局注入防截断", "recall_mode": "substring", "top_k": 1})
    assert first["fts5_applied"] is False
    assert first["fts5_status"]["error"] in {"index_missing", "index_not_ready"}
    assert first["fts5_status"]["auto_refresh_attempted"] is True
    assert first["fts5_status"]["auto_refresh_pending"] is True
    assert first["fts5_status"]["auto_refresh_trigger"] == first["fts5_status"]["error"]
    assert first["default_recall_freshness_covered"] is False

    p3._FTS5_REFRESH_THREAD.join(timeout=5)
    second = p3.handle_recall({"query": "开局注入防截断", "recall_mode": "substring", "top_k": 1})
    assert second["fts5_applied"] is True
    assert second["fts5_status"]["error"] is None
    assert second["fts5_status"]["stale"] is False
    assert second["fts5_status"]["auto_refresh_completed"] is True
    assert second["default_recall_freshness_covered"] is True
    assert second["matched_memories"][0]["exp_id"] == "exp-no-index"


def test_p3_explicit_fts5_request_schedules_stale_index_refresh_off_request_path(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-before-refresh",
        summary="旧索引内容",
        detail="这条先进入 FTS5 索引。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None
    from src.fts5_recall_index import build_index

    index_path = tmp_path / "memcore" / "runtime" / "fts5" / "p3.sqlite3"
    assert build_index(p3.get_memories(), str(index_path))["ok"] is True
    _write_memory(
        tmp_path,
        exp_id="exp-after-refresh",
        summary="自动刷新唯一标记 durability-refresh-0710",
        detail="显式 FTS5 请求必须发现 corpus signature 变化并自动追平。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    first = p3.handle_recall({
        "query": "durability-refresh-0710",
        "recall_mode": "substring",
        "top_k": 2,
    })

    assert first["fts5_status"]["stale"] is True
    assert first["fts5_status"]["auto_refresh_attempted"] is True
    assert first["fts5_status"]["auto_refresh_pending"] is True
    assert first["fts5_status"]["auto_refresh_trigger"] == "corpus_signature_mismatch"
    assert first["default_recall_freshness_covered"] is False

    p3._FTS5_REFRESH_THREAD.join(timeout=5)
    second = p3.handle_recall({
        "query": "durability-refresh-0710",
        "recall_mode": "substring",
        "top_k": 2,
    })
    assert second["fts5_status"]["stale"] is False
    assert second["fts5_status"]["auto_refresh_completed"] is True
    assert second["default_recall_freshness_covered"] is True
    assert second["matched_memories"][0]["exp_id"] == "exp-after-refresh"


def test_fts5_existing_index_catches_up_without_process_env_flag(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    first = _write_memory(
        tmp_path,
        exp_id="exp-existing-index",
        summary="先建立索引",
        detail="existing index",
    )
    from src import fts5_recall_index

    index_path = tmp_path / "memcore" / "runtime" / "fts5" / "p3.sqlite3"
    assert fts5_recall_index.build_index([first], str(index_path))["ok"] is True
    second = _write_memory(
        tmp_path,
        exp_id="exp-catchup-without-env",
        summary="无进程 env 也要追平已存在索引",
        detail="existing index catchup",
    )

    report = fts5_recall_index.fts5_build_or_catchup([first, second])

    assert report["ok"] is True
    assert report["refresh_trigger"] == "existing_index_catchup"
    assert report["doc_count"] == 2


def test_p3_default_substring_does_not_read_feature_flags(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    _write_memory(
        tmp_path,
        exp_id="exp-default-no-flag-io",
        summary="默认路径不要读 FTS5 flag",
        detail="默认 substring recall 不应该为了 FTS5 去读 feature_flags.json。",
    )
    flag_path = tmp_path / "missing-feature-flags.json"
    monkeypatch.setenv("MEMCORE_FEATURE_FLAGS", str(flag_path))

    def explode(_name):
        raise AssertionError("feature flag path should not be read on default recall")

    monkeypatch.setattr(p3, "_feature_flag_enabled", explode)
    result = p3.handle_recall({"query": "默认路径 FTS5", "recall_mode": "substring", "top_k": 1})
    assert result["matched_memories"]
    assert "fts5_applied" not in result


def test_p3_feature_flag_config_is_not_a_default_enable_path(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    _write_memory(
        tmp_path,
        exp_id="exp-config-flag-disabled",
        summary="feature flag config 不能默认打开 FTS5",
        detail="块9要求 FTS5 只通过 body 或 MEMCORE_FTS5_RECALL 显式打开。",
    )
    flags = tmp_path / "feature_flags.json"
    flags.write_text(json.dumps({"fts5_recall": True}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("MEMCORE_FEATURE_FLAGS", str(flags))
    monkeypatch.setenv("MEMCORE_ENABLE_FEATURE_FLAG_FTS5_RECALL", "1")

    result = p3.handle_recall({"query": "feature flag config FTS5", "recall_mode": "substring", "top_k": 1})
    assert result["matched_memories"]
    assert "fts5_applied" not in result


def test_p3_vector_mode_falls_back_to_fts5_when_assets_are_unavailable(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-vector-no-fts5",
        summary="vector 模式不签 FTS5 freshness",
        detail="FTS5 只属于 substring leg。",
    )
    result = p3.handle_recall({"query": "vector 模式", "recall_mode": "vector", "top_k": 1})
    assert result["mode"] == "vector_assets_unavailable_fallback_fts5"
    assert result["vector_fallback_applied"] is True
    assert result["vector_fallback_backend"] == "FTS5+BM25"
    assert result["vector_degraded"] is True


def test_p3_open_file_limit_is_raised_for_fragmented_lancedb_tables(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=False)
    status = p3.OPEN_FILE_LIMIT_STATUS
    assert status["requested_soft_limit"] == 4096
    if status["supported"] and not status["error"]:
        assert status["soft_limit_after"] >= min(4096, status["hard_limit"])


def test_p3_fts5_fuses_with_keyword_results_instead_of_replacing_them(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    keyword_only = _write_memory(
        tmp_path,
        exp_id="exp-keyword-only",
        summary="远程桌面 3389 keyword baseline",
        detail="这条 keyword 命中，但稍后会被伪造的 FTS5 索引漏掉。",
    )
    _write_memory(
        tmp_path,
        exp_id="exp-fts5-ranked",
        summary="远程桌面 3389 fts5 ranked",
        detail="这条会从 FTS5 返回。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    original_doc_id = p3._fts5_memory_doc_id

    def fake_search_index(**_kwargs):
        return {
            "rows": [{
                "doc_id": original_doc_id({
                    "exp_id": "exp-fts5-ranked",
                    "_type": "case_memory",
                    "scope": "window/project-a",
                    "summary": "远程桌面 3389 fts5 ranked",
                    "detail": "这条会从 FTS5 返回。",
                    "source_refs": keyword_only["source_refs"],
                }),
                "exp_id": "exp-fts5-ranked",
                "rank": -1.0,
                "memory_type": "case_memory",
            }],
            "status": {
                "enabled": True,
                "applied": True,
                "error": None,
                "matched_count": 1,
                "raw_matched_count": 1,
                "stale": False,
            },
        }

    monkeypatch.setattr(p3, "_fts5_search_index", fake_search_index)
    result = p3.handle_recall({"query": "远程桌面 3389", "recall_mode": "substring", "top_k": 3})
    ids = [item["exp_id"] for item in result["matched_memories"]]
    assert "exp-keyword-only" in ids
    assert "exp-fts5-ranked" in ids
    assert result["fts5_applied"] is True
    assert result["fts5_status"]["post_lifecycle_matched_count"] == 1
    assert result["fts5_status"]["fts5_only_hits"] == 0
    assert result["fts5_status"]["fts5_keyword_overlap_hits"] == 1
    assert result["fts5_status"]["fusion_policy"] == "keyword_base_with_bounded_fts5_boost"


def test_p3_fts5_raw_match_filtered_out_is_not_reported_as_applied(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-visible-keyword",
        summary="可见 keyword 记录",
        detail="scope 过滤后仍然可见。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    def fake_search_index(**_kwargs):
        return {
            "rows": [{
                "doc_id": "missing-doc-id",
                "exp_id": "exp-filtered-out",
                "rank": -1.0,
                "memory_type": "case_memory",
            }],
            "status": {
                "enabled": True,
                "applied": True,
                "error": None,
                "matched_count": 1,
                "raw_matched_count": 1,
                "stale": False,
            },
        }

    monkeypatch.setattr(p3, "_fts5_search_index", fake_search_index)
    result = p3.handle_recall({"query": "可见 keyword", "recall_mode": "substring", "top_k": 1})
    assert result["fts5_applied"] is False
    assert result["fts5_status"]["raw_matched_count"] == 1
    assert result["fts5_status"]["post_filter_matched_count"] == 0
    assert result["fts5_status"]["discarded_by_filter_count"] == 1
    assert result["primary_recall_backend"] == "keyword"


def test_p3_fts5_only_hits_do_not_replace_keyword_base(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-visible-keyword",
        summary="可见 keyword 记录",
        detail="keyword 基线必须保留。",
    )
    _write_memory(
        tmp_path,
        exp_id="exp-fts5-only",
        summary="FTS5 only hit",
        detail="这条只从 FTS5 返回，不该替代基线。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    original_doc_id = p3._fts5_memory_doc_id

    def fake_search_index(**_kwargs):
        return {
            "rows": [{
                "doc_id": original_doc_id({
                    "exp_id": "exp-fts5-only",
                    "_type": "case_memory",
                    "scope": "window/project-a",
                    "summary": "FTS5 only hit",
                    "detail": "这条只从 FTS5 返回，不该替代基线。",
                }),
                "exp_id": "exp-fts5-only",
                "rank": -1.0,
                "memory_type": "case_memory",
            }],
            "status": {
                "enabled": True,
                "applied": True,
                "error": None,
                "matched_count": 1,
                "raw_matched_count": 1,
                "stale": False,
            },
        }

    monkeypatch.setattr(p3, "_fts5_search_index", fake_search_index)
    result = p3.handle_recall({"query": "可见 keyword", "recall_mode": "substring", "top_k": 2})
    ids = [item["exp_id"] for item in result["matched_memories"]]
    assert "exp-visible-keyword" in ids
    assert "exp-fts5-only" not in ids
    assert result["fts5_applied"] is False
    assert result["fts5_status"]["fts5_only_hits"] == 1
    assert result["primary_recall_backend"] == "keyword"


def test_p3_fts5_used_skips_xingce_supplement_to_preserve_matched_by(tmp_path, monkeypatch):
    p3 = _reload_p3(tmp_path, monkeypatch, fts5_enabled=True)
    _write_memory(
        tmp_path,
        exp_id="exp-fts5-no-supplement",
        summary="FTS5 matched_by 不应被 supplement 覆盖",
        detail="FTS5 used 时不跑 xingce supplement。",
    )
    p3.MEMORIES_CACHE = None
    p3.MEMORIES_CACHE_SIGNATURE = None

    from src.fts5_recall_index import build_index

    index_path = tmp_path / "memcore" / "runtime" / "fts5" / "p3.sqlite3"
    assert build_index(p3.get_memories(), str(index_path))["ok"] is True

    def explode(_matched, _query, _top_k):
        raise AssertionError("xingce supplement must not run when FTS5 was used")

    monkeypatch.setattr(p3, "_supplement_xingce_candidates", explode)
    result = p3.handle_recall({"query": "FTS5 matched_by supplement", "recall_mode": "substring", "top_k": 1})
    assert result["fts5_applied"] is True
    assert result["matched_memories"][0]["matched_by"] == "fts5_bm25"
