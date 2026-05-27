#!/usr/bin/env python3
"""
memcore-cloud P0: 系统级原始记忆抓取 Scanner
- 遍历 OpenClaw transcript 文件
- 通过 alias_map.json 将 observed_name → canonical_window_id
- 按 source_system/computer/canonical_window/session 归档
- 默认使用 copy（独立原始记忆保全），禁止 hardlink
"""
import os, sys, json, glob, argparse, shutil, hashlib
from datetime import datetime, UTC
from pathlib import Path

from config_loader import openclaw_agents, memory_root, alias_map

OPENCLAW_ROOT = openclaw_agents()
MEMCORE_ROOT = memory_root()
ALIAS_MAP_FILE = alias_map()

HOSTNAME = "local"  # 从 config_loader.nodes.current 读取
SOURCE_SYSTEM = "openclaw"


def _node_id():
    from config_loader import node_id as _nid
    return _nid()


def load_alias_map():
    """加载 alias_map.json，返回 {observed_name: canonical_window_id}"""
    if not os.path.exists(ALIAS_MAP_FILE):
        return {}
    with open(ALIAS_MAP_FILE) as f:
        data = json.load(f)
    mapping = {}
    for canonical, info in data.get("canonical_windows", {}).items():
        for obs in info.get("observed_names", []):
            mapping[obs] = canonical
    return mapping


def get_canonical_window(observed_name):
    """将 observed_name（agent_dir）映射为 canonical_window_id"""
    static_map = load_alias_map()
    if observed_name in static_map:
        return static_map[observed_name]
    if observed_name.startswith("group-"):
        parts = observed_name.split("--")
        if len(parts) >= 2:
            return parts[-1]
    return observed_name


def scan_openclaw_transcripts():
    """扫描所有 OpenClaw transcript JSONL 文件"""
    records = []
    for agent_dir in sorted(os.listdir(OPENCLAW_ROOT)):
        sessions_dir = os.path.join(OPENCLAW_ROOT, agent_dir, "sessions")
        if not os.path.isdir(sessions_dir):
            continue
        canonical_window = get_canonical_window(agent_dir)
        for sf in sorted(glob.glob(os.path.join(sessions_dir, "*.jsonl"))):
            session_id = os.path.basename(sf).replace(".jsonl", "")
            if ".checkpoint." in session_id:
                continue
            records.append({
                "source_system": SOURCE_SYSTEM,
                "computer": _node_id(),
                "window": canonical_window,
                "observed_name": agent_dir,
                "session": session_id,
                "source_path": sf
            })
    return records


def _compute_checksum(filepath):
    """计算 SHA256 checksum"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_record(record, dry_run=True):
    """归档到 memcore-cloud 目录

    独立保全原则：只使用 copy，禁止 hardlink。
    每次归档生成同目录 .meta.json 元数据文件。
    """
    src = record["source_path"]

    # 计算 source 元数据（用于校验）
    src_stat = os.stat(src)
    raw_meta = {
        "source_path": src,
        "source_inode": src_stat.st_ino,
        "source_mtime": src_stat.st_mtime,
        "source_checksum": _compute_checksum(src),
        "archived_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_computer": record["computer"],
        "source_window": record["window"],
        "source_session": record["session"],
    }

    rel_path = (
        f"{record['source_system']}/"
        f"{record['computer']}/"
        f"{record['window']}/"
        f"{record['session']}.jsonl"
    )
    dest = os.path.join(MEMCORE_ROOT, rel_path)
    meta_dest = dest + ".meta.json"

    if dry_run:
        return dest, "dry_run", record["observed_name"], raw_meta

    os.makedirs(os.path.dirname(dest), exist_ok=True)

    if os.path.exists(dest):
        dest_stat = os.stat(dest)
        same_inode = (src_stat.st_ino == dest_stat.st_ino)
        if same_inode:
            # 历史 hardlink：删除旧硬链接，写独立副本
            os.unlink(dest)
            shutil.copy2(src, dest)
        # 写/更新 metadata
        with open(meta_dest, "w") as f:
            json.dump(raw_meta, f, indent=2)
        return dest, "copied", record["observed_name"], raw_meta, same_inode

    # 只用 copy，禁止 hardlink（独立保全原则）
    shutil.copy2(src, dest)
    with open(meta_dest, "w") as f:
        json.dump(raw_meta, f, indent=2)
    return dest, "copied", record["observed_name"], raw_meta


def migrate_old_structure(execute=False):
    """检测并报告旧结构（openclaw/local/<old_agent_dir>/）的残留"""
    old_base = MEMCORE_ROOT
    if not os.path.exists(old_base):
        return []
    residuals = []
    for source_system in os.listdir(old_base):
        st_path = os.path.join(old_base, source_system)
        if not os.path.isdir(st_path):
            continue
        for computer in os.listdir(st_path):
            cp_path = os.path.join(st_path, computer)
            if not os.path.isdir(cp_path):
                continue
            for window_dir in os.listdir(cp_path):
                wp_path = os.path.join(cp_path, window_dir)
                if not os.path.isdir(wp_path):
                    continue
                canonical = get_canonical_window(window_dir)
                if canonical != window_dir:
                    for sf in glob.glob(os.path.join(wp_path, "*.jsonl")):
                        session_id = os.path.basename(sf)
                        new_dir = os.path.join(old_base, source_system, computer, canonical)
                        new_path = os.path.join(new_dir, session_id)
                        if execute:
                            os.makedirs(new_dir, exist_ok=True)
                            if os.path.exists(new_path):
                                print(f"  [skip_exists] {sf} → {new_path}")
                            else:
                                os.rename(sf, new_path)
                                print(f"  [moved] {sf} → {new_path}")
                        else:
                            residuals.append({
                                "old_path": sf,
                                "new_path": new_path,
                                "observed": window_dir,
                                "canonical": canonical
                            })
    return residuals


def main():
    p = argparse.ArgumentParser(description="memcore-cloud P0 Scanner")
    p.add_argument("--dry-run", action="store_true", help="只打印不写入")
    p.add_argument("--limit", type=int, default=0, help="限制处理条数，0=不限")
    p.add_argument("--migrate", action="store_true", help="检测并报告旧结构残留")
    p.add_argument("--migrate-execute", action="store_true", help="执行旧结构迁移（observed → canonical）")
    args = p.parse_args()

    print(f"[memcore-cloud P0 Scanner]")
    print(f"  source:       {OPENCLAW_ROOT}")
    print(f"  dest:         {MEMCORE_ROOT}")
    print(f"  alias_map:    {ALIAS_MAP_FILE}")
    print(f"  dry_run:      {args.dry_run}")

    if args.migrate:
        print("\n=== 旧结构迁移检测 ===")
        residuals = migrate_old_structure(execute=args.migrate_execute)
        if not residuals:
            print("无旧结构残留，当前目录结构已符合 canonical_window 规范")
        else:
            print(f"发现 {len(residuals)} 个文件待迁移（observed_name → canonical）:")
            for r in residuals:
                print(f"  {r['observed']:40} → {r['canonical']}  ({os.path.basename(r['old_path'])})"+("  ← 待移动" if not args.migrate_execute else ""))
        return

    records = scan_openclaw_transcripts()
    print(f"\n发现 {len(records)} 个 session 文件")

    if args.limit > 0:
        records = records[:args.limit]

    exists = dry_run_count = copied = failed = 0

    for rec in records:
        dest, status, obs, *extra = archive_record(rec, dry_run=args.dry_run)
        if status == "dry_run":
            dry_run_count += 1
            print(f"  [{status}] {obs:40} → {rec['window']}/ {rec['session'][:8]}")
        elif status == "copied":
            copied += 1
            print(f"  [copied]  {obs:40} → {rec['window']}/ {rec['session'][:8]}")

        elif status == "exists":
            if extra and extra[0]:  # same_inode
                print(f"  [exists:hardlink] {obs:40} → {rec['window']}/ {rec['session'][:8]}")
            else:
                print(f"  [exists:copied] {obs:40} → {rec['window']}/ {rec['session'][:8]}")
            exists += 1
        else:
            failed += 1
            print(f"  [FAILED]  {obs:40} → {dest}")

    print(f"\n汇总: 发现={len(records)} copied={copied} exists={exists} failed={failed}")


if __name__ == "__main__":
    main()
