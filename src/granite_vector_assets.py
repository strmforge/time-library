#!/usr/bin/env python3
"""Install-relative Granite assets and active LanceDB index preparation."""

from __future__ import annotations

import hashlib
import gc
import json
import os
import shutil
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from src.vector_recall_runtime import (
        canonical_source_refs,
        corpus_signatures,
        memory_text,
        model_contract,
        pool_hidden_state,
        validate_table_identity,
        write_table_identity,
    )
except Exception:
    from vector_recall_runtime import (
        canonical_source_refs,
        corpus_signatures,
        memory_text,
        model_contract,
        pool_hidden_state,
        validate_table_identity,
        write_table_identity,
    )


GRANITE_MODEL_ID = "ibm-granite/granite-embedding-97m-multilingual-r2"
GRANITE_REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
GRANITE_TABLE = "experiences_v2_granite_97m"
GRANITE_MODEL_DIR = "granite-embedding-97m-multilingual-r2"
GRANITE_LICENSE = "Apache-2.0"
GRANITE_FILES = {
    "config.json": {
        "sha256": "de948b0bdc6f356afad7a84b276d8dd7e7fe10fb9add1bb5e610621c28e41ebc",
        "size": 1216,
    },
    "model.safetensors": {
        "sha256": "f3ea88b230492811046145513710e76b4cc8c2ad49e8708da0e7247e548903be",
        "size": 194889568,
    },
    "special_tokens_map.json": {
        "sha256": "013787ee251ff611722479197c00853b62113ad303cb0a36524231783c676c69",
        "size": 871,
    },
    "tokenizer.json": {
        "sha256": "4f2842d568e2724370aec203652a42ac783c7937f8347a1a2cc7506d71f1582f",
        "size": 25301672,
    },
    "tokenizer_config.json": {
        "sha256": "6ed69389e30a8ecabfce2f9ebcdf0c908b34056f24d994340f2f216521c057d5",
        "size": 12860,
    },
}
GRANITE_TOTAL_BYTES = sum(item["size"] for item in GRANITE_FILES.values())
_PREPARE_LOCK = threading.Lock()
_PREPARE_THREAD: threading.Thread | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _root(memcore_root: str | os.PathLike[str]) -> Path:
    return Path(memcore_root).expanduser().resolve()


def model_path(memcore_root: str | os.PathLike[str]) -> Path:
    return _root(memcore_root) / "runtime" / "model_cache" / GRANITE_MODEL_DIR


def status_path(memcore_root: str | os.PathLike[str]) -> Path:
    return _root(memcore_root) / "runtime" / "granite_vector_asset_status.json"


def _read_status_file(memcore_root: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        data = json.loads(status_path(memcore_root).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_status(memcore_root: str | os.PathLike[str], payload: dict[str, Any]) -> None:
    path = status_path(memcore_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _read_status_file(memcore_root)
    current.update(payload)
    current.update({
        "schema": "time_library.granite_vector_asset_status.v1",
        "model_id": GRANITE_MODEL_ID,
        "revision": GRANITE_REVISION,
        "updated_at": _now(),
    })
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _model_files_status(root: Path, *, verify: bool) -> dict[str, Any]:
    target = model_path(root)
    missing: list[str] = []
    mismatched: list[str] = []
    for name, expected in GRANITE_FILES.items():
        path = target / name
        if not path.is_file():
            missing.append(name)
            continue
        if path.stat().st_size != expected["size"]:
            mismatched.append(name)
            continue
        if verify and _sha256(path) != expected["sha256"]:
            mismatched.append(name)
    return {
        "model_path": str(target),
        "model_ready": not missing and not mismatched,
        "checksum_verified": bool(verify and not missing and not mismatched),
        "missing_files": missing,
        "mismatched_files": mismatched,
        "expected_bytes": GRANITE_TOTAL_BYTES,
    }


def _vector_config(root: Path) -> dict[str, Any]:
    path = root / "config" / "model_config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        data = {}
    recall = data.get("recall") if isinstance(data, dict) else {}
    configured = recall.get("local_vector") if isinstance(recall, dict) else {}
    if not isinstance(configured, dict):
        configured = {}
    result = dict(configured)
    result.update({
        "model_name": GRANITE_MODEL_ID,
        "model_id": GRANITE_MODEL_ID,
        "embedding_model": GRANITE_MODEL_ID,
        "model_path": str(model_path(root)),
        "embedding_dim": 384,
        "pooling": "cls",
        "normalize": True,
        "distance_type": "cosine",
        "max_seq_length": 256,
        "table": GRANITE_TABLE,
    })
    return result


def granite_asset_status(memcore_root: str | os.PathLike[str], *, verify: bool = False) -> dict[str, Any]:
    root = _root(memcore_root)
    files = _model_files_status(root, verify=verify)
    lancedb_root = root / "experience_lancedb"
    identity_path = lancedb_root / f"{GRANITE_TABLE}.identity.json"
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        identity = None
    identity_issues = validate_table_identity(model_contract(_vector_config(root)), identity)
    table_path = lancedb_root / f"{GRANITE_TABLE}.lance"
    table_ready = table_path.is_dir() and not identity_issues and int((identity or {}).get("row_count") or 0) > 0
    persisted = _read_status_file(root)
    state = str(persisted.get("state") or "")
    if files["model_ready"] and table_ready:
        state = "ready"
    elif state not in {"downloading", "building_index", "failed"}:
        state = "not_ready"
    return {
        "ok": True,
        "state": state,
        "ready": bool(files["model_ready"] and table_ready),
        "mechanism": "download_on_enable",
        "model_id": GRANITE_MODEL_ID,
        "revision": GRANITE_REVISION,
        "license": GRANITE_LICENSE,
        **files,
        "checksum_verified": bool(files["checksum_verified"] or persisted.get("checksum_verified")),
        "table": GRANITE_TABLE,
        "table_path": str(table_path),
        "table_ready": table_ready,
        "table_row_count": int((identity or {}).get("row_count") or 0),
        "table_identity_issues": identity_issues,
        "progress": persisted.get("progress") if isinstance(persisted.get("progress"), dict) else {},
        "error": str(persisted.get("error") or "") if state == "failed" else "",
        "fallback": "FTS5+BM25",
        "download_started_at": persisted.get("download_started_at"),
        "completed_at": persisted.get("completed_at"),
        "raw_write_performed": False,
        "memory_write_performed": False,
    }


def _download_assets(root: Path, *, opener: Callable[..., Any] = urllib.request.urlopen) -> None:
    final_dir = model_path(root)
    staging = final_dir.with_name(final_dir.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    try:
        for name, expected in GRANITE_FILES.items():
            url = (
                "https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2/"
                f"resolve/{GRANITE_REVISION}/{name}"
            )
            path = staging / name
            request = urllib.request.Request(url, headers={"User-Agent": "Time-Library/Granite-assets"})
            with opener(request, timeout=60) as response, path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    _write_status(root, {
                        "state": "downloading",
                        "progress": {
                            "file": name,
                            "downloaded_bytes": downloaded,
                            "total_bytes": GRANITE_TOTAL_BYTES,
                            "percent": round(downloaded * 100.0 / GRANITE_TOTAL_BYTES, 1),
                        },
                    })
            if path.stat().st_size != expected["size"] or _sha256(path) != expected["sha256"]:
                raise ValueError(f"checksum mismatch: {name}")
        if final_dir.exists():
            shutil.rmtree(final_dir)
        os.replace(staging, final_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


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


def _build_active_index(
    root: Path, memories: list[dict[str, Any]], *, batch_size: int = 16,
    write_batch_size: int = 512,
) -> None:
    if not memories:
        raise ValueError("no memories available for Granite index preparation")
    import lancedb
    import numpy as np
    import pyarrow as pa
    import torch
    from transformers import AutoModel, AutoTokenizer

    contract = model_contract(_vector_config(root))
    tokenizer = AutoTokenizer.from_pretrained(contract["model_path"], local_files_only=True)
    model = AutoModel.from_pretrained(contract["model_path"], local_files_only=True, torch_dtype=torch.float32).eval()
    device = "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu"
    if device != "cpu":
        model.to(device)
    lancedb_root = root / "experience_lancedb"
    lancedb_root.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(lancedb_root))
    temp_table = f"{GRANITE_TABLE}_preparing"
    if temp_table in set(db.table_names()):
        db.drop_table(temp_table)
    schema = pa.schema([
        pa.field("exp_id", pa.string()), pa.field("type", pa.string()),
        pa.field("scope", pa.string()), pa.field("summary", pa.string()),
        pa.field("detail", pa.string()), pa.field("source_refs", pa.string()),
        pa.field("evidence_level", pa.string()), pa.field("score", pa.float64()),
        pa.field("extracted_at", pa.string()), pa.field("status", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), 384)),
    ])
    table = db.create_table(temp_table, schema=schema)
    try:
        pending_rows: list[dict[str, Any]] = []
        for start in range(0, len(memories), batch_size):
            batch = memories[start:start + batch_size]
            inputs = tokenizer(
                [memory_text(item) for item in batch], padding=True, truncation=True,
                max_length=contract["max_seq_length"], return_tensors="pt",
            )
            if device != "cpu":
                inputs = {key: value.to(device) for key, value in inputs.items()}
            with torch.inference_mode():
                hidden = model(**inputs).last_hidden_state
            pooled = pool_hidden_state(hidden, inputs["attention_mask"], "cls")
            if device != "cpu":
                pooled = pooled.cpu()
            values = pooled.float().numpy()
            values = values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-12)
            pending_rows.extend(
                _row(item, vector) for item, vector in zip(batch, values.tolist())
            )
            if len(pending_rows) >= write_batch_size or start + len(batch) >= len(memories):
                table.add(pending_rows)
                pending_rows = []
            _write_status(root, {
                "state": "building_index",
                "progress": {
                    "encoded": min(start + len(batch), len(memories)),
                    "total_records": len(memories),
                    "percent": round(min(start + len(batch), len(memories)) * 100.0 / len(memories), 1),
                },
            })
        corpus_signature, refs_signature = corpus_signatures(memories)
        temp_contract = dict(contract, table=temp_table)
        temp_identity = write_table_identity(
            lancedb_root, temp_table, contract=temp_contract,
            row_count=int(table.count_rows()), corpus_signature=corpus_signature,
            source_refs_signature=refs_signature, build_role="download_on_enable_preparing",
        )
        if GRANITE_TABLE in set(db.table_names()):
            raise RuntimeError(f"active Granite table already exists: {GRANITE_TABLE}")
        temp_table_path = lancedb_root / f"{temp_table}.lance"
        final_table_path = lancedb_root / f"{GRANITE_TABLE}.lance"
        del table
        del db
        gc.collect()
        if final_table_path.exists():
            raise RuntimeError(f"active Granite table path already exists: {final_table_path}")
        os.replace(temp_table_path, final_table_path)
        identity = json.loads(temp_identity.read_text(encoding="utf-8"))
        identity["table"] = GRANITE_TABLE
        identity["model"]["table"] = GRANITE_TABLE
        identity["build_role"] = "download_on_enable_active"
        final_identity = lancedb_root / f"{GRANITE_TABLE}.identity.json"
        final_identity.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_identity.unlink(missing_ok=True)
    except Exception:
        try:
            cleanup_db = lancedb.connect(str(lancedb_root))
            if temp_table in set(cleanup_db.table_names()):
                cleanup_db.drop_table(temp_table)
        except Exception:
            shutil.rmtree(lancedb_root / f"{temp_table}.lance", ignore_errors=True)
        (lancedb_root / f"{temp_table}.identity.json").unlink(missing_ok=True)
        raise
    finally:
        try:
            model.to("cpu")
        except Exception:
            pass


def prepare_granite_assets(
    memcore_root: str | os.PathLike[str], *, memories: list[dict[str, Any]] | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    root = _root(memcore_root)
    with _PREPARE_LOCK:
        _write_status(root, {
            "state": "downloading", "error": "", "download_started_at": _now(),
            "progress": {"downloaded_bytes": 0, "total_bytes": GRANITE_TOTAL_BYTES, "percent": 0},
        })
        try:
            model_files = _model_files_status(root, verify=True)
            if not model_files["model_ready"]:
                _download_assets(root, opener=opener)
            verified = _model_files_status(root, verify=True)
            if not verified["model_ready"]:
                raise ValueError("Granite model files failed checksum verification")
            current = granite_asset_status(root, verify=True)
            if not current["table_ready"]:
                if memories is None:
                    os.environ["MEMCORE_ROOT"] = str(root)
                    try:
                        from src import p3_recall
                    except Exception:
                        import p3_recall
                    memories = p3_recall.load_memories()
                _write_status(root, {"state": "building_index", "progress": {"encoded": 0, "total_records": len(memories)}})
                _build_active_index(root, list(memories))
            _write_status(root, {
                "state": "ready", "completed_at": _now(), "error": "",
                "checksum_verified": True, "progress": {"percent": 100},
            })
            return granite_asset_status(root, verify=True)
        except Exception as exc:
            _write_status(root, {"state": "failed", "error": f"{type(exc).__name__}: {exc}"})
            return granite_asset_status(root, verify=False)


def start_granite_asset_prepare(
    memcore_root: str | os.PathLike[str], *,
    on_complete: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    global _PREPARE_THREAD
    root = _root(memcore_root)
    if _PREPARE_THREAD is not None and _PREPARE_THREAD.is_alive():
        return granite_asset_status(root)
    verified_status = granite_asset_status(root, verify=True)
    if verified_status["ready"]:
        return verified_status

    def worker() -> None:
        result = prepare_granite_assets(root)
        if on_complete is not None:
            try:
                on_complete(result)
            except Exception as exc:
                _write_status(root, {"state": "failed", "error": f"enable_finalize_failed:{type(exc).__name__}: {exc}"})

    _PREPARE_THREAD = threading.Thread(target=worker, daemon=True, name="granite-asset-prepare")
    _PREPARE_THREAD.start()
    result = granite_asset_status(root)
    result["started"] = True
    return result
