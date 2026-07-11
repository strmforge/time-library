#!/usr/bin/env python3
"""Build and compare model-aware shadow LanceDB indexes on current memories.

This is an internal migration tool. It never writes raw memory or replaces the
configured production vector table. The last current record is added as the
final shadow write so the report includes measured encode-to-visible freshness.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import random
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vector_recall_runtime import (  # noqa: E402
    canonical_source_refs,
    corpus_signatures,
    memory_text,
    model_contract,
    pool_hidden_state,
    write_table_identity,
)


BAD_PATTERNS = (
    "<appshot",
    "container (settable",
    "The focused UI element",
    "codex-clipboard",
    "Traceback",
)


def _now() -> float:
    return time.perf_counter()


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _language_bucket(text: str) -> str:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk and latin >= max(8, cjk // 3):
        return "mixed"
    if cjk:
        return "cjk"
    if latin:
        return "latin"
    return "other"


def _usable_query(memory: dict[str, Any]) -> bool:
    summary = _compact(memory.get("summary"))
    detail = _compact(memory.get("detail"))
    if len(summary) < 20 or len(detail) < 20:
        return False
    if len(summary) > 700 or any(pattern in summary or pattern in detail for pattern in BAD_PATTERNS):
        return False
    return bool(memory.get("exp_id"))


def _query_text(memory: dict[str, Any]) -> str:
    summary = _compact(memory.get("summary"))
    summary = re.sub(
        r"^(用户在 session [^ ]+ 中表达了偏好：|案例：|错误：)",
        "",
        summary,
    ).strip()
    if len(summary) >= 16:
        return summary[:180]
    return _compact(memory.get("detail"))[:180]


def _recent_sort_key(memory: dict[str, Any]) -> str:
    return str(
        memory.get("extracted_at")
        or memory.get("effective_from")
        or memory.get("updated_at")
        or ""
    )


def _select_freshness_memory(memories: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [memory for memory in memories if _usable_query(memory)]
    if not eligible:
        raise ValueError("no usable real memory is available for the freshness check")
    return max(eligible, key=_recent_sort_key)


def build_query_set(
    memories: list[dict[str, Any]], *, query_count: int, seed: int
) -> list[dict[str, Any]]:
    eligible = [memory for memory in memories if _usable_query(memory)]
    if len(eligible) < query_count:
        raise ValueError(f"only {len(eligible)} usable real memories for {query_count} queries")
    rng = random.Random(seed)
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for memory in eligible:
        key = (str(memory.get("type") or memory.get("_type") or "unknown"), _language_bucket(_query_text(memory)))
        buckets[key].append(memory)
    for bucket in buckets.values():
        rng.shuffle(bucket)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(memory: dict[str, Any]) -> None:
        exp_id = str(memory.get("exp_id") or "")
        if exp_id and exp_id not in seen and len(selected) < query_count:
            seen.add(exp_id)
            selected.append(memory)

    recent_target = min(24, max(8, query_count // 10))
    for memory in sorted(eligible, key=_recent_sort_key, reverse=True)[:recent_target]:
        add(memory)

    active_buckets = [bucket for bucket in buckets.values() if bucket]
    cursor = 0
    while len(selected) < query_count and active_buckets:
        bucket = active_buckets[cursor % len(active_buckets)]
        while bucket and str(bucket[-1].get("exp_id") or "") in seen:
            bucket.pop()
        if bucket:
            add(bucket.pop())
        active_buckets = [item for item in active_buckets if item]
        cursor += 1

    if len(selected) < query_count:
        remaining = [item for item in eligible if str(item.get("exp_id")) not in seen]
        rng.shuffle(remaining)
        for memory in remaining:
            add(memory)

    return [
        {
            "query": _query_text(memory),
            "expected_exp_id": str(memory.get("exp_id")),
            "expected_type": str(memory.get("type") or memory.get("_type") or ""),
            "language_bucket": _language_bucket(_query_text(memory)),
            "source_refs": canonical_source_refs(memory),
            "recent": memory in selected[:recent_target],
        }
        for memory in selected
    ]


def _row(memory: dict[str, Any], vector: list[float]) -> dict[str, Any]:
    return {
        "exp_id": str(memory.get("exp_id") or ""),
        "type": str(memory.get("type") or memory.get("_type") or ""),
        "scope": str(memory.get("scope") or ""),
        "summary": str(memory.get("summary") or ""),
        "detail": str(memory.get("detail") or ""),
        "source_refs": canonical_source_refs(memory),
        "evidence_level": str(memory.get("evidence_level") or ""),
        "score": float(memory.get("score") or 0.0),
        "extracted_at": str(memory.get("extracted_at") or ""),
        "status": str(memory.get("status") or "active"),
        "vector": vector,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 6)


class Encoder:
    def __init__(self, contract: dict[str, Any], device: str) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.contract = contract
        requested = device.lower()
        if requested == "auto":
            requested = "mps" if torch.backends.mps.is_available() else "cpu"
        if requested == "mps" and not torch.backends.mps.is_available():
            requested = "cpu"
        self.device = requested
        local_only = not bool(os.environ.get("MEMCORE_VECTOR_ALLOW_MODEL_DOWNLOAD") == "1")
        started = _now()
        self.tokenizer = AutoTokenizer.from_pretrained(
            contract["model_path"], local_files_only=local_only, trust_remote_code=True
        )
        self.model = AutoModel.from_pretrained(
            contract["model_path"],
            local_files_only=local_only,
            trust_remote_code=True,
            dtype=torch.float32,
        ).eval()
        if self.device != "cpu":
            self.model.to(self.device)
        self.load_seconds = _now() - started
        self.encode_calls = 0

    def encode(self, texts: list[str]) -> list[list[float]]:
        import numpy as np

        inputs = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=self.contract["max_seq_length"],
            return_tensors="pt",
        )
        if self.device != "cpu":
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            output = self.model(**inputs)
        hidden = pool_hidden_state(
            output.last_hidden_state,
            inputs["attention_mask"],
            self.contract["pooling"],
        )
        if self.device != "cpu":
            hidden = hidden.cpu()
        values = hidden.float().numpy()
        if self.contract["normalize"]:
            values = values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-12)
        if values.shape[1] != self.contract["embedding_dim"]:
            raise ValueError(
                f"{self.contract['model_id']} emitted {values.shape[1]} dimensions; "
                f"expected {self.contract['embedding_dim']}"
            )
        if not np.isfinite(values).all():
            raise ValueError(f"{self.contract['model_id']} emitted non-finite vectors")
        self.encode_calls += 1
        return values.astype("float32", copy=False).tolist()

    def close(self) -> None:
        try:
            self.model.to("cpu")
        except Exception:
            pass
        del self.model
        del self.tokenizer
        gc.collect()
        if getattr(self.torch.backends, "mps", None):
            try:
                self.torch.mps.empty_cache()
            except Exception:
                pass


def _selected_rows(table: Any, row_count: int) -> list[dict[str, Any]]:
    try:
        return table.search().select(["exp_id", "source_refs"]).limit(row_count + 10).to_list()
    except Exception:
        return [
            {"exp_id": row.get("exp_id"), "source_refs": row.get("source_refs")}
            for row in table.to_arrow().to_pylist()
        ]


def _search(table: Any, vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
    return table.search(vector, vector_column_name="vector").select(["exp_id", "source_refs"]).limit(limit).to_list()


def run_model(
    *,
    lancedb_root: Path,
    memories: list[dict[str, Any]],
    queries: list[dict[str, Any]],
    config: dict[str, Any],
    batch_size: int,
    device: str,
    replace_shadow: bool,
    corpus_signature: str,
    source_refs_signature: str,
) -> dict[str, Any]:
    import lancedb
    import pyarrow as pa

    contract = model_contract(config)
    db = lancedb.connect(str(lancedb_root))
    existing = set(db.table_names())
    if contract["table"] in existing:
        if not replace_shadow:
            raise RuntimeError(f"shadow table already exists: {contract['table']}")
        db.drop_table(contract["table"])
    identity_path = lancedb_root / f"{contract['table']}.identity.json"
    if identity_path.exists() and replace_shadow:
        identity_path.unlink()

    schema = pa.schema([
        pa.field("exp_id", pa.string()),
        pa.field("type", pa.string()),
        pa.field("scope", pa.string()),
        pa.field("summary", pa.string()),
        pa.field("detail", pa.string()),
        pa.field("source_refs", pa.string()),
        pa.field("evidence_level", pa.string()),
        pa.field("score", pa.float64()),
        pa.field("extracted_at", pa.string()),
        pa.field("status", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), contract["embedding_dim"])),
    ])
    table = db.create_table(contract["table"], schema=schema)
    encoder = Encoder(contract, device)
    build_started = _now()
    progress_started = build_started
    freshness_memory = _select_freshness_memory(memories)
    base_memories = [memory for memory in memories if memory is not freshness_memory]
    encoded = 0
    for start in range(0, len(base_memories), batch_size):
        batch = base_memories[start:start + batch_size]
        vectors = encoder.encode([memory_text(memory) for memory in batch])
        table.add([_row(memory, vector) for memory, vector in zip(batch, vectors)])
        encoded += len(batch)
        if encoded % max(batch_size, 256) == 0 or encoded == len(base_memories):
            elapsed = _now() - progress_started
            print(
                json.dumps({
                    "model": contract["model_id"],
                    "encoded": encoded,
                    "total_before_freshness": len(base_memories),
                    "elapsed_seconds": round(elapsed, 3),
                }, ensure_ascii=False),
                flush=True,
            )

    freshness_query = _query_text(freshness_memory)
    freshness_started = _now()
    fresh_vector = encoder.encode([memory_text(freshness_memory)])[0]
    freshness_document_encode_seconds = _now() - freshness_started
    add_started = _now()
    table.add([_row(freshness_memory, fresh_vector)])
    freshness_add_seconds = _now() - add_started
    query_started = _now()
    fresh_query_vector = encoder.encode([freshness_query])[0]
    freshness_query_encode_seconds = _now() - query_started
    visible_started = _now()
    freshness_hits = _search(table, fresh_query_vector, limit=5)
    freshness_search_seconds = _now() - visible_started
    freshness_rank = next(
        (index + 1 for index, item in enumerate(freshness_hits) if item.get("exp_id") == freshness_memory.get("exp_id")),
        None,
    )
    build_seconds = _now() - build_started
    row_count = int(table.count_rows())
    if row_count != len(memories):
        raise RuntimeError(f"shadow table row count {row_count} != corpus {len(memories)}")
    write_table_identity(
        lancedb_root,
        contract["table"],
        contract=contract,
        row_count=row_count,
        corpus_signature=corpus_signature,
        source_refs_signature=source_refs_signature,
        build_role="shadow_candidate" if "granite" in contract["model_id"].lower() else "shadow_baseline",
    )

    expected_refs = {
        str(memory.get("exp_id")): canonical_source_refs(memory)
        for memory in memories
    }
    stored_rows = _selected_rows(table, row_count)
    stored_refs = {str(row.get("exp_id")): str(row.get("source_refs") or "") for row in stored_rows}
    missing_ids = sorted(set(expected_refs) - set(stored_refs))
    mismatched_refs = sorted(
        exp_id for exp_id, refs in expected_refs.items()
        if exp_id in stored_refs and stored_refs[exp_id] != refs
    )

    query_vectors_started = _now()
    query_vectors: list[list[float]] = []
    query_texts = [item["query"] for item in queries]
    for start in range(0, len(query_texts), batch_size):
        query_vectors.extend(encoder.encode(query_texts[start:start + batch_size]))
    query_batch_encode_seconds = _now() - query_vectors_started

    metrics = {"top1": 0, "top3": 0, "top5": 0, "mrr": 0.0}
    language: dict[str, dict[str, int]] = defaultdict(lambda: {"queries": 0, "top1": 0, "top5": 0})
    failures: list[dict[str, Any]] = []
    search_times: list[float] = []
    recent_top1 = 0
    recent_count = 0
    for query, vector in zip(queries, query_vectors):
        started = _now()
        hits = _search(table, vector, limit=10)
        search_times.append(_now() - started)
        ranked = [str(hit.get("exp_id") or "") for hit in hits]
        expected = query["expected_exp_id"]
        rank = ranked.index(expected) + 1 if expected in ranked else None
        if rank == 1:
            metrics["top1"] += 1
        if rank is not None and rank <= 3:
            metrics["top3"] += 1
        if rank is not None and rank <= 5:
            metrics["top5"] += 1
        if rank:
            metrics["mrr"] += 1.0 / rank
        bucket = language[query["language_bucket"]]
        bucket["queries"] += 1
        bucket["top1"] += int(rank == 1)
        bucket["top5"] += int(rank is not None and rank <= 5)
        if query.get("recent"):
            recent_count += 1
            recent_top1 += int(rank == 1)
        if rank != 1 and len(failures) < 30:
            failures.append({
                "query": query["query"],
                "expected_exp_id": expected,
                "rank": rank,
                "top5": ranked[:5],
            })

    single_query_times: list[float] = []
    for query in queries[: min(24, len(queries))]:
        started = _now()
        encoder.encode([query["query"]])
        single_query_times.append(_now() - started)

    count = len(queries)
    report = {
        "model": contract,
        "python": sys.version.split()[0],
        "device": encoder.device,
        "model_load_seconds": round(encoder.load_seconds, 6),
        "table": contract["table"],
        "storage": "LanceDB",
        "row_count": row_count,
        "corpus_signature": corpus_signature,
        "source_refs_signature": source_refs_signature,
        "build": {
            "seconds": round(build_seconds, 6),
            "documents_per_second": round(row_count / max(build_seconds, 1e-9), 4),
            "batch_size": batch_size,
        },
        "retrieval": {
            "query_count": count,
            "top1": metrics["top1"],
            "top3": metrics["top3"],
            "top5": metrics["top5"],
            "top1_rate": round(metrics["top1"] / count, 6),
            "top3_rate": round(metrics["top3"] / count, 6),
            "top5_rate": round(metrics["top5"] / count, 6),
            "mrr": round(metrics["mrr"] / count, 6),
            "recent_query_count": recent_count,
            "recent_top1_rate": round(recent_top1 / max(recent_count, 1), 6),
            "by_language": dict(language),
            "failures_sample": failures,
        },
        "latency": {
            "query_batch_encode_seconds": round(query_batch_encode_seconds, 6),
            "query_batch_per_item_ms": round(query_batch_encode_seconds * 1000 / count, 6),
            "single_query_encode_p50_seconds": _percentile(single_query_times, 0.50),
            "single_query_encode_p95_seconds": _percentile(single_query_times, 0.95),
            "lancedb_search_p50_seconds": _percentile(search_times, 0.50),
            "lancedb_search_p95_seconds": _percentile(search_times, 0.95),
        },
        "freshness": {
            "real_exp_id": str(freshness_memory.get("exp_id") or ""),
            "query": freshness_query,
            "document_encode_seconds": round(freshness_document_encode_seconds, 6),
            "lancedb_add_seconds": round(freshness_add_seconds, 6),
            "query_encode_seconds": round(freshness_query_encode_seconds, 6),
            "first_search_seconds": round(freshness_search_seconds, 6),
            "encode_to_visible_seconds": round(
                freshness_document_encode_seconds
                + freshness_add_seconds
                + freshness_query_encode_seconds
                + freshness_search_seconds,
                6,
            ),
            "rank": freshness_rank,
            "visible_top5": bool(freshness_rank and freshness_rank <= 5),
        },
        "source_refs_parity": {
            "expected_count": len(expected_refs),
            "stored_count": len(stored_refs),
            "missing_count": len(missing_ids),
            "mismatch_count": len(mismatched_refs),
            "exact": not missing_ids and not mismatched_refs and len(stored_refs) == len(expected_refs),
            "missing_sample": missing_ids[:20],
            "mismatch_sample": mismatched_refs[:20],
        },
        "identity_path": str(identity_path),
    }
    encoder.close()
    return report


def gate_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    baseline_retrieval = baseline["retrieval"]
    candidate_retrieval = candidate["retrieval"]
    baseline_latency = baseline["latency"]
    candidate_latency = candidate["latency"]
    baseline_freshness = baseline["freshness"]
    candidate_freshness = candidate["freshness"]
    checks = {
        "accuracy_top1_not_worse": candidate_retrieval["top1_rate"] >= baseline_retrieval["top1_rate"],
        "accuracy_top5_not_worse": candidate_retrieval["top5_rate"] >= baseline_retrieval["top5_rate"],
        "accuracy_mrr_not_worse": candidate_retrieval["mrr"] >= baseline_retrieval["mrr"],
        "recent_top1_not_worse": candidate_retrieval["recent_top1_rate"] >= baseline_retrieval["recent_top1_rate"],
        "single_query_p50_not_slower": candidate_latency["single_query_encode_p50_seconds"] <= baseline_latency["single_query_encode_p50_seconds"],
        "single_query_p95_not_slower": candidate_latency["single_query_encode_p95_seconds"] <= baseline_latency["single_query_encode_p95_seconds"],
        "fresh_memory_visible": bool(candidate_freshness["visible_top5"]),
        "freshness_not_slower": candidate_freshness["encode_to_visible_seconds"] <= baseline_freshness["encode_to_visible_seconds"],
        "source_refs_exact": bool(candidate["source_refs_parity"]["exact"]),
        "same_corpus": candidate["corpus_signature"] == baseline["corpus_signature"],
        "same_source_refs": candidate["source_refs_signature"] == baseline["source_refs_signature"],
        "python_3_9": str(candidate.get("python") or "").startswith("3.9."),
        "storage_lancedb": candidate.get("storage") == "LanceDB",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "decision": "candidate_may_become_default" if all(checks.values()) else "keep_baseline_default",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--lancedb-root", required=True)
    parser.add_argument("--bge-model-path", required=True)
    parser.add_argument("--granite-model-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--query-count", type=int, default=240)
    parser.add_argument("--seed", type=int, default=20260710)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), default="auto")
    parser.add_argument("--replace-shadow", action="store_true")
    args = parser.parse_args()

    runtime_root = Path(args.runtime_root).expanduser().resolve()
    lancedb_root = Path(args.lancedb_root).expanduser().resolve()
    os.environ["MEMCORE_ROOT"] = str(runtime_root)
    os.environ["MEMCORE_INSTALL_ROOT"] = str(runtime_root)
    os.environ["PYTHONPATH"] = str(ROOT)
    from src import p3_recall

    memories = p3_recall.load_memories()
    corpus_signature, refs_signature = corpus_signatures(memories)
    queries = build_query_set(memories, query_count=args.query_count, seed=args.seed)
    bge_config = {
        "model_name": "BAAI/bge-m3",
        "model_path": str(Path(args.bge_model_path).expanduser().resolve()),
        "embedding_dim": 1024,
        "pooling": "mean_unmasked",
        "normalize": True,
        "distance_type": "cosine",
        "max_seq_length": 256,
        "table": "experiences_v2_bge_m3_baseline",
    }
    granite_config = {
        "model_name": "ibm-granite/granite-embedding-97m-multilingual-r2",
        "model_path": str(Path(args.granite_model_path).expanduser().resolve()),
        "embedding_dim": 384,
        "pooling": "cls",
        "normalize": True,
        "distance_type": "cosine",
        "max_seq_length": 256,
        "table": "experiences_v2_granite_97m_shadow",
    }
    common = {
        "lancedb_root": lancedb_root,
        "memories": memories,
        "queries": queries,
        "batch_size": max(1, args.batch_size),
        "device": args.device,
        "replace_shadow": args.replace_shadow,
        "corpus_signature": corpus_signature,
        "source_refs_signature": refs_signature,
    }
    baseline = run_model(config=bge_config, **common)
    candidate = run_model(config=granite_config, **common)
    gate = gate_reports(baseline, candidate)
    report = {
        "schema": "time_library.vector_model_shadow_eval.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime_root": str(runtime_root),
        "lancedb_root": str(lancedb_root),
        "corpus_count": len(memories),
        "query_count": len(queries),
        "query_language_counts": {
            bucket: sum(1 for item in queries if item["language_bucket"] == bucket)
            for bucket in sorted({item["language_bucket"] for item in queries})
        },
        "baseline": baseline,
        "candidate": candidate,
        "gate": gate,
        "production_default_changed": False,
        "raw_write_performed": False,
        "source_refs_write_performed": False,
        "zvec_touched": False,
        "nonClaims": [
            "self-retrieval accuracy is not a human-judged QA benchmark",
            "shadow tables do not change the production default",
            "no raw memory or source reference authority was migrated",
            "no cross-machine behavior is proven",
        ],
        "queries": queries,
    }
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "corpus_count": len(memories),
        "query_count": len(queries),
        "gate": gate,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
