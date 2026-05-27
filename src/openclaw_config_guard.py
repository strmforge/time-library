#!/usr/bin/env python3
"""
OpenClaw Config Guard
P9-System-A: P9-3

功能：备份 OpenClaw 配置、生成 diff、准备 rollback
约束：--dry-run（默认），不真实 apply 修改
输出：backups/openclaw/ + patches/openclaw/ + logs/runtime_changes.jsonl
"""

import json
import os
import sys
import hashlib
import argparse
import difflib
from datetime import datetime, timezone
from pathlib import Path
from config_loader import get_memcore_root

UTC = timezone.utc
OPENCLAW_ROOT = Path.home() / ".openclaw"
MEMCORE_ROOT = Path(get_memcore_root())
BACKUP_DIR = MEMCORE_ROOT / "backups" / "openclaw"
PATCH_DIR = MEMCORE_ROOT / "patches" / "openclaw"
LOG_DIR = MEMCORE_ROOT / "logs"

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
PATCH_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def ts():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_checksum(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return None


def scan_openclaw_configs():
    """扫描 OpenClaw 配置目录，返回需要备份的文件列表"""
    targets = []
    if not OPENCLAW_ROOT.exists():
        return targets

    # Gateway config
    gateway_config = OPENCLAW_ROOT / "gateway" / "config"
    if gateway_config.exists():
        for f in gateway_config.glob("*.json"):
            targets.append(f)

    # Service files
    service_dir = Path("/etc/systemd/system")
    if service_dir.exists():
        for f in service_dir.glob("openclaw*.service"):
            targets.append(f)
        for f in service_dir.glob("openclaw*.socket"):
            targets.append(f)

    # Environment/config files
    for pattern in ["*.json", "*.conf", "*.yaml", "*.yml"]:
        for f in gateway_config.glob(pattern):
            targets.append(f)
        env_dir = OPENCLAW_ROOT
        for f in env_dir.glob(pattern):
            if f.is_file() and not any(ex in f.name for ex in ["package", "node_modules"]):
                targets.append(f)

    return list(set(targets))


def backup_file(src_path):
    """备份单个文件，返回 backup 记录"""
    try:
        rel_path = src_path.relative_to("/") if src_path.is_absolute() else src_path
        checksum = file_checksum(src_path)
        backup_name = f"{ts().replace(':', '-')}_{rel_path.name}"
        backup_path = BACKUP_DIR / backup_name

        with open(src_path, "rb") as sf:
            content = sf.read()
        with open(backup_path, "wb") as bf:
            bf.write(content)

        return {
            "backup_at": ts(),
            "original_path": str(src_path),
            "backup_path": str(backup_path),
            "size": len(content),
            "checksum": checksum,
            "status": "ok"
        }
    except Exception as e:
        return {
            "original_path": str(src_path),
            "status": "error",
            "error": str(e)
        }


def generate_diff(original_content, new_content, filename):
    """生成 unified diff"""
    original_lines = original_content.decode("utf-8", errors="replace").splitlines(keepends=True)
    new_lines = new_content.decode("utf-8", errors="replace").splitlines(keepends=True)
    diff = difflib.unified_diff(
        original_lines, new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm=""
    )
    return "".join(diff)


def prepare_rollback(backup_record, current_content):
    """生成 rollback 文件"""
    rollback = {
        "generated_at": ts(),
        "mode": "dry_run" if DRY_RUN else "live",
        "original_path": backup_record["original_path"],
        "backup_path": backup_record["backup_path"],
        "rollback_content": current_content.decode("utf-8", errors="replace"),
        "checksum": file_checksum(Path(backup_record["backup_path"]))
    }
    rollback_name = f"{ts().replace(':', '-')}_{Path(backup_record['original_path']).name}.rollback.json"
    rollback_path = PATCH_DIR / rollback_name
    with open(rollback_path, "w") as f:
        json.dump(rollback, f, indent=2, ensure_ascii=False)
    return rollback_path


def log_change(entry):
    log_path = LOG_DIR / "runtime_changes.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="OpenClaw Config Guard (P9-System-A P9-3)")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Dry-run mode (default: on)")
    parser.add_argument("--apply", action="store_true",
                        help="Apply changes (requires --dry-run to be explicitly disabled)")
    parser.add_argument("--detect", action="store_true",
                        help="Only detect and list config files")
    args = parser.parse_args()

    global DRY_RUN
    DRY_RUN = args.dry_run and not args.apply

    print(f"Mode: {'DRY-RUN' if DRY_RUN else 'LIVE'}")
    print()

    targets = scan_openclaw_configs()
    print(f"Found {len(targets)} config files to protect\n")

    if args.detect:
        for t in targets:
            print(f"  {t}")
        return

    backups = []
    for src_path in targets:
        if not src_path.exists():
            continue
        print(f"Backing up: {src_path}")
        record = backup_file(src_path)
        backups.append(record)
        if record["status"] != "ok":
            print(f"  ERROR: {record.get('error')}")
        else:
            print(f"  -> {record['backup_path']} ({record['size']} bytes, checksum={record['checksum']})")

        # Check for changes: compare current file against the FIRST backup ever created for this file
        # The first backup has the original unmodified content
        all_backups = sorted(BACKUP_DIR.glob(f"*_{src_path.name}"), key=lambda p: p.stat().st_mtime)
        # Exclude backups created in this script run (same minute as now)
        current_minute = ts()[:16]  # e.g. "2026-04-26T19-08"
        prior_backups = [p for p in all_backups if p.name[:16] < current_minute]

        if prior_backups:
            old_backup = prior_backups[0]  # oldest prior = first backup ever created
            with open(src_path, "rb") as cf:
                current_content = cf.read()
            with open(old_backup, "rb") as bf:
                old_content = bf.read()

            if current_content != old_content:
                filename = src_path.name
                diff_text = generate_diff(old_content, current_content, filename)
                diff_name = f"{ts().replace(':', '-')}_{filename}.diff"
                diff_path = PATCH_DIR / diff_name
                with open(diff_path, "w") as f:
                    f.write(diff_text)
                print(f"  CHANGE DETECTED -> diff: {diff_path}")

                old_record = dict(record)
                old_record["backup_path"] = str(old_backup)
                rollback_path = prepare_rollback(old_record, current_content)
                print(f"  CHANGE DETECTED -> rollback: {rollback_path}")

                log_change({
                    "ts": ts(),
                    "action": "change_detected",
                    "risk_level": "medium",
                    "dry_run": DRY_RUN,
                    "file": str(src_path),
                    "old_backup": str(old_backup),
                    "diff_path": str(diff_path),
                    "rollback_path": str(rollback_path)
                })
            else:
                print(f"  (no change detected)")
        else:
            print(f"  (no prior backup, first time)")

        # Log backup
        log_change({
            "ts": ts(),
            "action": "backup",
            "risk_level": "low",
            "dry_run": DRY_RUN,
            "result": record
        })

    print(f"\nBackup complete: {len([b for b in backups if b['status']=='ok'])}/{len(backups)} files")
    print(f"Backup dir: {BACKUP_DIR}")
    print(f"Patch dir: {PATCH_DIR}")
    print(f"Log: {LOG_DIR / 'runtime_changes.jsonl'}")

    if DRY_RUN:
        print("\n[DRY-RUN] No changes applied. To apply:")
        print("  python openclaw_config_guard.py --apply")
    else:
        print("\n[LIVE] Changes would be applied here.")
        print("  Rollback files prepared in patches/openclaw/")


if __name__ == "__main__":
    main()
