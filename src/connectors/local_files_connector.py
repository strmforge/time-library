#!/usr/bin/env python3
"""
P9-System-L-lite: Local Files Source System Connector
Minimal connector: read-only scan of input/local_files/
Idempotent: source_path+checksum一致→不重复写；checksum变化→新版本；文件删除→不删raw
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc

# Dynamically resolve project root to support cross-platform
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent.parent))
from config_loader import base_path as _base_path

MEMCORE_ROOT = Path(_base_path())
INPUT_DIR = MEMCORE_ROOT / "input" / "local_files"
RAW_DIR = MEMCORE_ROOT / "memory" / "local_files"
INDEX_FILE = RAW_DIR / ".source_index.jsonl"
CHECKPOINT_FILE = RAW_DIR / ".checkpoint.json"
SUPPORTED_EXTS = {".txt", ".md", ".jsonl"}


def ts():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dirs():
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def compute_sha256(path):
    """计算文件 SHA256（部分读取用于大文件优化）"""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            data = f.read()
        h.update(data)
        return h.hexdigest()
    except Exception:
        return None


def read_content(path):
    """读取文本内容"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def compute_memory_id(content, source_path, checksum):
    """派生 memory_id = SHA256(content+source_path+checksum)"""
    h = hashlib.sha256()
    h.update((content + source_path + checksum).encode("utf-8"))
    return h.hexdigest()


# ── Index 管理 ────────────────────────────────────────────────────────

def load_index():
    """加载 source → checksum 映射"""
    if not INDEX_FILE.exists():
        return {}
    index = {}
    with open(INDEX_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                key = entry.get("source_path")
                if key:
                    index[key] = entry
            except Exception:
                pass
    return index


def save_index_entry(entry):
    """Append or update index entry (append-only for audit)"""
    with open(INDEX_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Checkpoint ────────────────────────────────────────────────────────

def load_checkpoint():
    if not CHECKPOINT_FILE.exists():
        return {}
    try:
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_checkpoint(data):
    CHECKPOINT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ── Connector API ──────────────────────────────────────────────────────

def status():
    """返回 connector 当前状态"""
    ensure_dirs()
    index = load_index()
    checkpoint = load_checkpoint()
    # 扫描 input 目录
    current_files = {}
    if INPUT_DIR.exists():
        for f in INPUT_DIR.iterdir():
            if f.is_file() and f.suffix in SUPPORTED_EXTS:
                checksum = compute_sha256(f)
                current_files[str(f)] = checksum

    active_sources = list(current_files.keys())
    ingested_sources = list(index.keys())

    return {
        "source_system": "local_files",
        "status": "active",
        "input_dir": str(INPUT_DIR),
        "raw_dir": str(RAW_DIR),
        "total_input_files": len(active_sources),
        "total_ingested_sources": len(ingested_sources),
        "active_sources": active_sources,
        "checkpoint": checkpoint,
    }


def discover():
    """发现 input/local_files/ 下所有支持的文件"""
    ensure_dirs()
    files = []
    if not INPUT_DIR.exists():
        return files
    for f in INPUT_DIR.iterdir():
        if f.is_file() and f.suffix in SUPPORTED_EXTS:
            checksum = compute_sha256(f)
            files.append({
                "source_path": str(f),
                "filename": f.name,
                "size": f.stat().st_size,
                "checksum": checksum,
                "modified_at": datetime.fromtimestamp(f.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "is_symlink": f.is_symlink(),
                "mode": oct(f.stat().st_mode)[-3:],
            })
    return files


def scan():
    """扫描并返回文件清单（不写入 raw）"""
    return discover()


def ingest(dry_run=True):
    """
    摄入文件到 raw 存储。

    幂等规则：
    - source_path + checksum 一致 → 跳过（幂等）
    - checksum 变化 → 新版本写入
    - 文件删除 → 不删 raw（保留历史）
    """
    ensure_dirs()
    index = load_index()
    checkpoint = load_checkpoint()
    discovered = discover()

    ingested = []
    skipped = []
    updated = []

    for item in discovered:
        source_path = item["source_path"]
        checksum = item["checksum"]
        content = read_content(Path(source_path))
        if content is None:
            skipped.append({**item, "reason": "read_failed"})
            continue

        prev = index.get(source_path)
        if prev and prev.get("checksum") == checksum:
            # 完全一致，幂等跳过
            skipped.append({**item, "reason": "idempotent_skip"})
            continue

        if prev:
            # checksum 变化，记录旧版本但不删除
            updated.append({**item, "previous_checksum": prev.get("checksum")})

        # 写入 raw
        if not dry_run:
            memory_id = compute_memory_id(content, source_path, checksum)
            raw_entry = {
                "memory_id": memory_id,
                "source_system": "local_files",
                "source_path": source_path,
                "source_checksum": checksum,
                "source_size": item["size"],
                "source_modified_at": item["modified_at"],
                "content": content,
                "extracted_at": ts(),
                "version": (prev.get("version", 0) + 1) if prev else 1,
                "source_refs": [],  # P2-1: relationship to other memory objects (placeholder)
            }
            raw_file = RAW_DIR / f"{hashlib.md5(source_path.encode()).hexdigest()}.jsonl"
            with open(raw_file, "a") as f:
                f.write(json.dumps(raw_entry, ensure_ascii=False) + "\n")

            # 更新 index
            index_entry = {
                "source_path": source_path,
                "checksum": checksum,
                "size": item["size"],
                "modified_at": item["modified_at"],
                "memory_id": memory_id,
                "raw_file": str(raw_file),
                "version": raw_entry["version"],
                "ingested_at": ts(),
            }
            save_index_entry(index_entry)
            index[source_path] = index_entry

            # 更新 checkpoint
            checkpoint[source_path] = checksum
            save_checkpoint(checkpoint)

        ingested.append({**item, "version": (prev.get("version", 0) + 1) if prev else 1})

    return {
        "dry_run": dry_run,
        "total_discovered": len(discovered),
        "ingested": ingested,
        "skipped": skipped,
        "updated": updated,
        "total_ingested": len(ingested),
        "total_skipped": len(skipped),
        "total_updated": len(updated),
    }


def checkpoint():
    """返回当前 checkpoint 状态"""
    return load_checkpoint()


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))
    elif cmd == "discover":
        print(json.dumps(discover(), indent=2, ensure_ascii=False))
    elif cmd == "scan":
        print(json.dumps(scan(), indent=2, ensure_ascii=False))
    elif cmd == "ingest":
        dry_run = "--dry-run" in sys.argv
        result = ingest(dry_run=dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif cmd == "checkpoint":
        print(json.dumps(checkpoint(), indent=2, ensure_ascii=False))
    else:
        print(f"Usage: {sys.argv[0]} [status|discover|scan|ingest|checkpoint]")
        sys.exit(1)


if __name__ == "__main__":
    main()
