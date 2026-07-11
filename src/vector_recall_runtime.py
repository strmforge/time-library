#!/usr/bin/env python3
"""Model-aware vector encoding and LanceDB index identity checks."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VECTOR_INDEX_CONTRACT = "time_library.vector_index.v1"
SUPPORTED_POOLING = {"cls", "mean_masked", "mean_unmasked"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def model_contract(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize the model/index fields that must agree at query time."""
    pooling = _text(config.get("pooling") or "mean_unmasked").lower()
    if pooling not in SUPPORTED_POOLING:
        raise ValueError(f"unsupported vector pooling: {pooling}")
    dimension = int(config.get("embedding_dim") or 0)
    if dimension <= 0:
        raise ValueError("embedding_dim must be a positive integer")
    model_id = _text(
        config.get("model_id")
        or config.get("embedding_model")
        or config.get("model_name")
    )
    if not model_id:
        raise ValueError("vector model_id is required")
    table = _text(config.get("table"))
    if not table:
        raise ValueError("vector table is required")
    return {
        "contract": VECTOR_INDEX_CONTRACT,
        "model_id": model_id,
        "model_name": _text(config.get("model_name")) or model_id,
        "model_path": os.path.expanduser(os.path.expandvars(_text(config.get("model_path")))),
        "embedding_dim": dimension,
        "pooling": pooling,
        "normalize": bool(config.get("normalize", True)),
        "distance_type": _text(config.get("distance_type")) or "cosine",
        "max_seq_length": int(config.get("max_seq_length") or 256),
        "table": table,
    }


def table_identity_path(lancedb_root: str | os.PathLike[str], table: str) -> Path:
    return Path(lancedb_root).expanduser() / f"{table}.identity.json"


def load_table_identity(
    lancedb_root: str | os.PathLike[str], table: str
) -> dict[str, Any] | None:
    path = table_identity_path(lancedb_root, table)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def write_table_identity(
    lancedb_root: str | os.PathLike[str],
    table: str,
    *,
    contract: dict[str, Any],
    row_count: int,
    corpus_signature: str,
    source_refs_signature: str,
    build_role: str,
) -> Path:
    root = Path(lancedb_root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    path = table_identity_path(root, table)
    payload = {
        "contract": VECTOR_INDEX_CONTRACT,
        "table": table,
        "model": dict(contract),
        "row_count": int(row_count),
        "corpus_signature": _text(corpus_signature),
        "source_refs_signature": _text(source_refs_signature),
        "storage": "LanceDB",
        "build_role": _text(build_role),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def validate_table_identity(
    configured: dict[str, Any], identity: dict[str, Any] | None
) -> list[str]:
    if not identity:
        return ["missing_table_identity"]
    issues: list[str] = []
    if identity.get("contract") != VECTOR_INDEX_CONTRACT:
        issues.append("table_identity_contract_mismatch")
    if _text(identity.get("table")) != _text(configured.get("table")):
        issues.append("table_identity_table_mismatch")
    actual = identity.get("model") if isinstance(identity.get("model"), dict) else {}
    checks = (
        ("model_id", "table_identity_model_mismatch"),
        ("embedding_dim", "table_identity_dimension_mismatch"),
        ("pooling", "table_identity_pooling_mismatch"),
        ("normalize", "table_identity_normalize_mismatch"),
        ("distance_type", "table_identity_distance_mismatch"),
    )
    for field, issue in checks:
        if actual.get(field) != configured.get(field):
            issues.append(issue)
    return issues


def vector_dimension_from_schema(schema: Any) -> int | None:
    try:
        vector_type = schema.field("vector").type
    except Exception:
        return None
    for attr in ("list_size", "value_length"):
        value = getattr(vector_type, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def pool_hidden_state(hidden: Any, attention_mask: Any, pooling: str) -> Any:
    if pooling == "cls":
        return hidden[:, 0]
    if pooling == "mean_unmasked":
        return hidden.mean(dim=1)
    if pooling == "mean_masked":
        mask = attention_mask.unsqueeze(-1).expand(hidden.size()).to(hidden.dtype)
        return (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
    raise ValueError(f"unsupported vector pooling: {pooling}")


def memory_text(memory: dict[str, Any]) -> str:
    return " ".join(
        part for part in (
            _text(memory.get("summary")),
            _text(memory.get("detail")),
        ) if part
    )


def canonical_source_refs(memory: dict[str, Any]) -> str:
    refs = memory.get("source_refs") or memory.get("_source_refs") or {}
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except (TypeError, ValueError):
            return refs
    if isinstance(refs, dict):
        return json.dumps(refs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps({}, separators=(",", ":"))


def corpus_signatures(memories: Iterable[dict[str, Any]]) -> tuple[str, str]:
    corpus_digest = hashlib.sha256()
    refs_digest = hashlib.sha256()
    for memory in memories:
        exp_id = _text(memory.get("exp_id"))
        text = memory_text(memory)
        refs = canonical_source_refs(memory)
        corpus_digest.update(exp_id.encode("utf-8"))
        corpus_digest.update(b"\0")
        corpus_digest.update(text.encode("utf-8"))
        corpus_digest.update(b"\n")
        refs_digest.update(exp_id.encode("utf-8"))
        refs_digest.update(b"\0")
        refs_digest.update(refs.encode("utf-8"))
        refs_digest.update(b"\n")
    return corpus_digest.hexdigest(), refs_digest.hexdigest()
