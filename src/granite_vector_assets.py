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
GRANITE_UPGRADE_STATUS = "granite_vector_upgrade_migration.json"
LEGACY_BGE_MODEL_ID = "BAAI/bge-m3"
LEGACY_BGE_TABLE = "experiences_v2"
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
    _atomic_write_json(path, current)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    )
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _upgrade_status_path(root: Path) -> Path:
    return root / "runtime" / GRANITE_UPGRADE_STATUS


def _write_upgrade_status(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    current = _read_json_object(_upgrade_status_path(root))
    current.update(payload)
    current.update({
        "schema": "time_library.granite_vector_upgrade_migration.v1",
        "updated_at": _now(),
    })
    _atomic_write_json(_upgrade_status_path(root), current)
    return current


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled", "vector"}
    return bool(value)


def _legacy_bge_default(recall: dict[str, Any]) -> dict[str, Any] | None:
    mode = str(recall.get("mode") or "").strip().lower()
    if mode == "local_bge_m3":
        configured = recall.get("local_bge_m3")
    elif mode in {"vector", "local_vector"}:
        configured = recall.get("local_vector") or recall.get("local_bge_m3")
    else:
        return None
    if not isinstance(configured, dict):
        return None
    model_id = str(
        configured.get("model_id")
        or configured.get("embedding_model")
        or configured.get("model_name")
        or ""
    ).strip().lower()
    table = str(configured.get("table") or "").strip()
    try:
        dimension = int(configured.get("embedding_dim") or 0)
    except (TypeError, ValueError):
        dimension = 0
    if model_id != LEGACY_BGE_MODEL_ID.lower():
        return None
    if table != LEGACY_BGE_TABLE or dimension != 1024:
        return None
    return dict(configured)


def _vector_preference(root: Path) -> tuple[dict[str, Any], bool]:
    payload = _read_json_object(root / "config" / "zhiyi_model_binding.user.json")
    preference = payload.get("vector_recall_preference") if isinstance(payload, dict) else {}
    preference = preference if isinstance(preference, dict) else {}
    return payload, _truthy(preference.get("enabled", False))


def _granite_target_configured(root: Path) -> bool:
    config = _read_json_object(root / "config" / "model_config.json")
    recall = config.get("recall") if isinstance(config, dict) else {}
    configured = recall.get("local_vector") if isinstance(recall, dict) else {}
    if not isinstance(configured, dict):
        return False
    model_id = str(
        configured.get("model_id")
        or configured.get("embedding_model")
        or configured.get("model_name")
        or ""
    ).strip()
    return model_id == GRANITE_MODEL_ID and str(configured.get("table") or "") == GRANITE_TABLE


def migrate_legacy_bge_upgrade(memcore_root: str | os.PathLike[str]) -> dict[str, Any]:
    """Move the shipped legacy BGE default to Granite-ready FTS5 fallback.

    Only the exact old default contract is migrated. Custom vector contracts are
    left untouched. An explicitly enabled vector preference is resumed by P6
    after Granite assets are ready; until then recall remains on FTS5+BM25.
    """
    root = _root(memcore_root)
    config_path = root / "config" / "model_config.json"
    config = _read_json_object(config_path)
    recall = config.get("recall") if isinstance(config, dict) else {}
    recall = recall if isinstance(recall, dict) else {}
    legacy = _legacy_bge_default(recall)
    if legacy is None:
        existing = _read_json_object(_upgrade_status_path(root))
        if existing:
            existing["write_performed"] = False
            return existing
        return {
            "ok": True,
            "applicable": False,
            "write_performed": False,
            "reason": "legacy_bge_default_not_detected",
        }

    _, vector_enabled = _vector_preference(root)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = config_path.with_name(f"model_config.json.pre-granite-{timestamp}.bak")
    shutil.copy2(config_path, backup_path)

    fallback = dict(legacy)
    fallback.setdefault("model_id", LEGACY_BGE_MODEL_ID)
    fallback.setdefault("model_name", LEGACY_BGE_MODEL_ID)
    fallback.setdefault("embedding_model", LEGACY_BGE_MODEL_ID)
    recall["local_vector"] = _vector_config(root)
    recall["vector_fallback"] = fallback
    recall["mode"] = "substring"
    config["recall"] = recall
    _atomic_write_json(config_path, config)

    return _write_upgrade_status(root, {
        "ok": True,
        "applicable": True,
        "write_performed": True,
        "state": "pending_assets" if vector_enabled else "awaiting_user_enable",
        "from_mode": "local_bge_m3",
        "from_model_id": LEGACY_BGE_MODEL_ID,
        "from_table": str(legacy.get("table") or ""),
        "target_mode": "local_vector",
        "target_model_id": GRANITE_MODEL_ID,
        "temporary_recall_mode": "substring",
        "fallback": "FTS5+BM25",
        "resume_vector_enable": vector_enabled,
        "backup_path": str(backup_path),
        "raw_write_performed": False,
        "memory_write_performed": False,
    })


def _granite_metadata(root: Path, config: dict[str, Any], row_count: int, *, enabled: bool) -> dict[str, Any]:
    recall = config.get("recall") if isinstance(config, dict) else {}
    recall = recall if isinstance(recall, dict) else {}
    fallback = recall.get("vector_fallback") if isinstance(recall.get("vector_fallback"), dict) else {}
    previous = _read_json_object(root / "config" / "lancedb_v2_metadata.json")
    history = previous.get("upgrade_history") if isinstance(previous.get("upgrade_history"), list) else []
    if not any(str(item.get("to") or "").startswith(GRANITE_MODEL_ID) for item in history if isinstance(item, dict)):
        history = list(history) + [{
            "date": datetime.now(timezone.utc).date().isoformat(),
            "from": f"{LEGACY_BGE_MODEL_ID}-1024d",
            "to": f"{GRANITE_MODEL_ID}-384d",
            "reason": "upgrade migration completed after checksum-verified asset preparation",
        }]
    return {
        "_comment": "Current vector index contract; runtime identity files remain authoritative per table.",
        "table": GRANITE_TABLE,
        "schema_version": "2.0",
        "embedding_metadata": {
            "embedding_model": GRANITE_MODEL_ID,
            "embedding_dim": 384,
            "embedding_version": "r2",
            "pooling": "cls",
            "distance_type": "cosine",
            "normalized": True,
            "max_seq_length": 256,
            "model_path": str(model_path(root)),
        },
        "last_rebuilt": datetime.now(timezone.utc).date().isoformat(),
        "record_count": int(row_count),
        "fallback": {
            "embedding_model": str(fallback.get("embedding_model") or fallback.get("model_name") or LEGACY_BGE_MODEL_ID),
            "embedding_dim": int(fallback.get("embedding_dim") or 1024),
            "pooling": str(fallback.get("pooling") or "mean_unmasked"),
            "table": str(fallback.get("table") or LEGACY_BGE_TABLE),
        },
        "upgrade_history": history,
        "recall_mode": "vector" if enabled else "substring",
    }


def finalize_legacy_vector_upgrade(
    memcore_root: str | os.PathLike[str], result: dict[str, Any],
) -> dict[str, Any]:
    root = _root(memcore_root)
    if not result.get("ready"):
        return _write_upgrade_status(root, {
            "state": "asset_prepare_failed",
            "resume_vector_enable": True,
            "temporary_recall_mode": "substring",
            "fallback": "FTS5+BM25",
            "error": str(result.get("error") or "Granite assets are not ready"),
            "write_performed": False,
        })

    config_path = root / "config" / "model_config.json"
    user_path = root / "config" / "zhiyi_model_binding.user.json"
    metadata_path = root / "config" / "lancedb_v2_metadata.json"
    config = _read_json_object(config_path)
    user_payload, vector_enabled = _vector_preference(root)
    recall = config.setdefault("recall", {})
    recall["local_vector"] = _vector_config(root)
    recall["mode"] = "local_vector" if vector_enabled else "substring"
    preference = user_payload.get("vector_recall_preference") if isinstance(user_payload, dict) else {}
    if isinstance(preference, dict) and preference:
        preference.update({
            "enabled": vector_enabled,
            "default_recall_mode": "vector" if vector_enabled else "substring",
            "fts5_recall": not vector_enabled,
            "hot_switch_status": "effective_for_new_gateway_requests",
            "requires_restart": False,
        })
        user_payload["vector_recall_preference"] = preference

    previous = {
        config_path: _read_json_object(config_path),
        metadata_path: _read_json_object(metadata_path),
        user_path: _read_json_object(user_path),
    }
    try:
        _atomic_write_json(config_path, config)
        _atomic_write_json(metadata_path, _granite_metadata(
            root, config, int(result.get("table_row_count") or 0), enabled=vector_enabled,
        ))
        if user_payload:
            _atomic_write_json(user_path, user_payload)
    except Exception:
        for path, payload in previous.items():
            if payload:
                _atomic_write_json(path, payload)
            else:
                path.unlink(missing_ok=True)
        raise

    return _write_upgrade_status(root, {
        "state": "completed_enabled" if vector_enabled else "completed_not_enabled",
        "resume_vector_enable": False,
        "target_model_id": GRANITE_MODEL_ID,
        "target_table": GRANITE_TABLE,
        "temporary_recall_mode": "",
        "active_recall_mode": "local_vector" if vector_enabled else "substring",
        "fallback": "FTS5+BM25" if not vector_enabled else LEGACY_BGE_MODEL_ID,
        "error": "",
        "write_performed": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
    })


def resume_legacy_vector_upgrade(memcore_root: str | os.PathLike[str]) -> dict[str, Any]:
    root = _root(memcore_root)
    migration = migrate_legacy_bge_upgrade(root)
    _, vector_enabled = _vector_preference(root)
    resume_enabled = bool(migration.get("resume_vector_enable")) or (
        vector_enabled and _granite_target_configured(root)
    )
    if not resume_enabled:
        return migration
    if not vector_enabled:
        return _write_upgrade_status(root, {
            "state": "awaiting_user_enable",
            "resume_vector_enable": False,
            "temporary_recall_mode": "substring",
            "write_performed": False,
        })
    assets = granite_asset_status(root, verify=True)
    if assets.get("ready"):
        return finalize_legacy_vector_upgrade(root, assets)
    started = start_granite_asset_prepare(
        root,
        on_complete=lambda result: finalize_legacy_vector_upgrade(root, result),
    )
    current = _read_json_object(_upgrade_status_path(root))
    if str(current.get("state") or "").startswith("completed_"):
        current["asset_prepare_started"] = bool(started.get("started", False))
        return current
    return _write_upgrade_status(root, {
        "state": str(started.get("state") or "downloading"),
        "resume_vector_enable": True,
        "temporary_recall_mode": "substring",
        "fallback": "FTS5+BM25",
        "asset_prepare_started": bool(started.get("started", False)),
        "write_performed": False,
    })


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
