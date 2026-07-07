"""SQLite FTS5 recall index for the P3 substring leg.

The index is a rebuildable projection over zhiyi memories. It is not the
source of truth and it is never allowed to mutate raw/archive records.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable


CONTRACT = "fts5_recall_index.v2026.7.3"


def default_index_path(memcore_root: str | os.PathLike[str]) -> str:
    return str(Path(memcore_root) / "runtime" / "fts5_recall" / "p3_memories.sqlite3")


def capability_probe() -> dict[str, Any]:
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE probe USING fts5(text, tokenize='trigram')")
        con.execute("INSERT INTO probe(text) VALUES (?)", ("Time Library freshness probe",))
        rows = con.execute("SELECT rowid FROM probe WHERE probe MATCH ?", ("freshness",)).fetchall()
        con.close()
        return {
            "ok": bool(rows),
            "sqlite_version": sqlite3.sqlite_version,
            "fts5": True,
            "trigram": True,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "sqlite_version": sqlite3.sqlite_version,
            "fts5": False,
            "trigram": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _source_refs(memory: dict[str, Any]) -> dict[str, Any]:
    refs = memory.get("source_refs") or memory.get("_source_refs") or {}
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:
            refs = {}
    return refs if isinstance(refs, dict) else {}


def memory_doc_id(memory: dict[str, Any]) -> str:
    exp_id = str(memory.get("exp_id") or "").strip()
    if exp_id:
        return exp_id
    refs = _source_refs(memory)
    payload = {
        "type": memory.get("_type") or memory.get("type") or "",
        "scope": memory.get("scope") or "",
        "source_path": refs.get("source_path") or "",
        "msg_ids": refs.get("msg_ids") or [],
        "summary": memory.get("summary") or "",
        "detail": memory.get("detail") or "",
    }
    digest = hashlib.sha256(json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return f"doc-{digest[:24]}"


def _memory_projection(memory: dict[str, Any]) -> dict[str, Any]:
    refs = _source_refs(memory)
    return {
        "doc_id": memory_doc_id(memory),
        "exp_id": str(memory.get("exp_id") or ""),
        "memory_type": str(memory.get("_type") or memory.get("type") or ""),
        "scope": str(memory.get("scope") or ""),
        "summary": str(memory.get("summary") or ""),
        "detail": str(memory.get("detail") or ""),
        "source_refs": _jsonable(refs),
    }


def corpus_signature(memories: Iterable[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for memory in sorted((_memory_projection(m) for m in memories if isinstance(m, dict)), key=lambda item: item["doc_id"]):
        h.update(json.dumps(memory, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS docs("
        "doc_id TEXT PRIMARY KEY, "
        "exp_id TEXT, "
        "memory_type TEXT, "
        "scope TEXT, "
        "summary TEXT, "
        "detail TEXT, "
        "source_refs TEXT, "
        "content_sha256 TEXT NOT NULL)"
    )
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts "
        "USING fts5(doc_id UNINDEXED, summary, detail, tokenize='trigram')"
    )


def build_index(memories: Iterable[dict[str, Any]], index_path: str, *, replace: bool = True) -> dict[str, Any]:
    capability = capability_probe()
    started = time.time()
    if not capability.get("ok"):
        return {
            "ok": False,
            "contract": CONTRACT,
            "index_path": index_path,
            "error": capability.get("error") or "fts5_trigram_unavailable",
            "capability": capability,
            "write_performed": False,
        }
    docs = [_memory_projection(m) for m in memories if isinstance(m, dict)]
    signature = corpus_signature(memories)
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = _connect(str(path))
    try:
        _ensure_schema(con)
        if replace:
            con.execute("DELETE FROM docs_fts")
            con.execute("DELETE FROM docs")
        for doc in docs:
            content_for_hash = json.dumps(doc, ensure_ascii=False, sort_keys=True)
            content_sha = hashlib.sha256(content_for_hash.encode("utf-8")).hexdigest()
            con.execute(
                "INSERT OR REPLACE INTO docs(doc_id, exp_id, memory_type, scope, summary, detail, source_refs, content_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc["doc_id"],
                    doc["exp_id"],
                    doc["memory_type"],
                    doc["scope"],
                    doc["summary"],
                    doc["detail"],
                    json.dumps(doc["source_refs"], ensure_ascii=False, sort_keys=True),
                    content_sha,
                ),
            )
            con.execute(
                "INSERT INTO docs_fts(rowid, doc_id, summary, detail) "
                "VALUES ((SELECT rowid FROM docs WHERE doc_id = ?), ?, ?, ?)",
                (doc["doc_id"], doc["doc_id"], doc["summary"], doc["detail"]),
            )
        meta = {
            "contract": CONTRACT,
            "corpus_signature": signature,
            "doc_count": str(len(docs)),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sqlite_version": sqlite3.sqlite_version,
        }
        for key, value in meta.items():
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, str(value)))
        con.commit()
        return {
            "ok": True,
            "contract": CONTRACT,
            "index_path": str(path),
            "doc_count": len(docs),
            "corpus_signature": signature,
            "elapsed_seconds": round(time.time() - started, 4),
            "write_performed": True,
            "error": None,
            "capability": capability,
        }
    finally:
        con.close()


def _meta(con: sqlite3.Connection) -> dict[str, str]:
    try:
        return {str(k): str(v) for k, v in con.execute("SELECT key, value FROM meta").fetchall()}
    except Exception:
        return {}


def _query_terms(query: str) -> list[str]:
    q = str(query or "").strip()
    if not q:
        return []
    candidates = [q]
    candidates.extend(re.split(r"[\s,，。；;：:、/]+", q))
    terms: list[str] = []
    for term in candidates:
        term = str(term or "").strip()
        if len(term) < 3:
            continue
        if term not in terms:
            terms.append(term)
    return terms


def _match_query(query: str) -> tuple[str, list[str]]:
    terms = _query_terms(query)
    if not terms:
        return "", []
    quoted = ['"' + term.replace('"', '""') + '"' for term in terms[:8]]
    return " OR ".join(quoted), terms


def search_index(
    *,
    query: str,
    index_path: str,
    limit: int = 20,
    expected_signature: str = "",
) -> dict[str, Any]:
    started = time.time()
    match_query, terms = _match_query(query)
    status: dict[str, Any] = {
        "contract": CONTRACT,
        "enabled": True,
        "index_path": index_path,
        "query_terms": terms,
        "error": None,
        "applied": False,
        "matched_count": 0,
        "raw_matched_count": 0,
        "post_filter_matched_count": 0,
        "discarded_by_filter_count": 0,
        "stale": False,
    }
    if not match_query:
        status.update({"error": "query_too_short_for_trigram"})
        return {"ok": False, "rows": [], "status": status}
    if not os.path.exists(index_path):
        status.update({"error": "index_missing"})
        return {"ok": False, "rows": [], "status": status}
    try:
        con = sqlite3.connect(index_path)
        meta = _meta(con)
        actual_signature = meta.get("corpus_signature", "")
        stale = bool(expected_signature and actual_signature and actual_signature != expected_signature)
        rows = [
            {
                "doc_id": str(row[0]),
                "exp_id": str(row[1] or ""),
                "rank": float(row[2]),
                "memory_type": str(row[3] or ""),
            }
            for row in con.execute(
                "SELECT docs.doc_id, docs.exp_id, bm25(docs_fts) AS rank, docs.memory_type "
                "FROM docs_fts JOIN docs ON docs.rowid = docs_fts.rowid "
                "WHERE docs_fts MATCH ? "
                "ORDER BY rank ASC LIMIT ?",
                (match_query, int(limit)),
            ).fetchall()
        ]
        con.close()
        status.update({
            "applied": bool(rows),
            "matched_count": len(rows),
            "raw_matched_count": len(rows),
            "doc_count": int(meta.get("doc_count") or 0),
            "corpus_signature": actual_signature,
            "expected_signature": expected_signature,
            "stale": stale,
            "elapsed_seconds": round(time.time() - started, 4),
            "rank_reason": "sqlite_fts5_trigram_bm25",
        })
        return {"ok": True, "rows": rows, "status": status}
    except Exception as exc:
        status.update({
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": round(time.time() - started, 4),
        })
        return {"ok": False, "rows": [], "status": status}


def _memory_to_legacy_doc(memory: dict[str, Any]) -> dict[str, Any]:
    refs = _source_refs(memory)
    source_path = str(refs.get("source_path") or "")
    raw_offset = refs.get("raw_offset") or refs.get("byte_offsets") or ""
    if isinstance(raw_offset, dict):
        raw_offset = json.dumps(raw_offset, ensure_ascii=False, sort_keys=True)
    return {
        "exp_id": str(memory_doc_id(memory)),
        "summary": str(memory.get("summary") or ""),
        "detail": str(memory.get("detail") or ""),
        "source_ref": str(refs.get("source_ref") or refs.get("source") or ""),
        "source_path": source_path,
        "raw_offset": str(raw_offset or ""),
        "evidence_hash": str(memory.get("evidence_hash") or memory.get("verbatim_sha256") or ""),
    }


def fts5_search(query: str, docs: list[dict[str, Any]], top_k: int = 50):
    """Compatibility wrapper for older p3 runtime branches.

    The new block9 contract should prefer ``search_index`` plus explicit p3
    gating. This wrapper intentionally reports flag_off unless the environment
    explicitly enables FTS5; it does not read feature_flags.
    """
    if str(os.environ.get("MEMCORE_FTS5_RECALL") or "").strip().lower() not in {"1", "true", "yes", "on", "enabled"}:
        return [], {"enabled": False, "fts5_enabled": False, "reason": "flag_off"}
    expected_signature = corpus_signature(docs)
    result = search_index(
        query=query,
        index_path=default_index_path(os.environ.get("MEMCORE_ROOT") or Path(__file__).resolve().parents[1]),
        limit=top_k,
        expected_signature=expected_signature,
    )
    rows = result.get("rows") or []
    by_id = {}
    for doc in docs:
        try:
            by_id[memory_doc_id(doc)] = doc
        except Exception:
            continue
    scored = []
    for row in rows:
        memory = by_id.get(str(row.get("doc_id") or ""))
        if not memory:
            continue
        score = 1.0 / (1.0 + len(scored))
        scored.append((score, memory))
    return scored, result.get("status") or {}


def fts5_build_or_catchup(docs: list[dict[str, Any]]):
    if str(os.environ.get("MEMCORE_FTS5_RECALL") or "").strip().lower() not in {"1", "true", "yes", "on", "enabled"}:
        return {"ok": True, "skipped": True, "reason": "flag_off"}
    return build_index(docs, default_index_path(os.environ.get("MEMCORE_ROOT") or Path(__file__).resolve().parents[1]))


def fts5_build_background(docs: list[dict[str, Any]]):
    # Keep compatibility non-blocking semantics conservative for local runtime:
    # build only when explicitly enabled, and do it synchronously in this small
    # wrapper so callers can still observe errors through status/build receipts.
    return fts5_build_or_catchup(docs)


def fts5_status():
    index_path = default_index_path(os.environ.get("MEMCORE_ROOT") or Path(__file__).resolve().parents[1])
    status = {
        "fts5_enabled": str(os.environ.get("MEMCORE_FTS5_RECALL") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"},
        "index_path": index_path,
        "exists": os.path.exists(index_path),
    }
    if not os.path.exists(index_path):
        status.update({"built": False, "doc_count": 0})
        return status
    try:
        con = sqlite3.connect(index_path)
        meta = _meta(con)
        con.close()
        status.update({
            "built": True,
            "doc_count": int(meta.get("doc_count") or 0),
            "corpus_signature": meta.get("corpus_signature", ""),
            "contract": meta.get("contract", CONTRACT),
        })
    except Exception as exc:
        status.update({"built": False, "error": f"{type(exc).__name__}: {exc}"})
    return status


def probe_fts5_capability() -> dict[str, Any]:
    cap = capability_probe()
    return {
        "provider": "sqlite3",
        "version": cap.get("sqlite_version", ""),
        "sqlite_version": cap.get("sqlite_version", ""),
        "fts5": bool(cap.get("fts5")),
        "trigram": bool(cap.get("trigram")),
        "fallback_required": not bool(cap.get("ok")),
        "error": cap.get("error"),
        "ok": bool(cap.get("ok")),
    }
