#!/usr/bin/env python3
"""Check that a minimal hotfix bundle can still import live entrypoints.

This builds a temporary tree from a published base ref, overlays the planned
hotfix files from the current working tree, then imports the requested module.
It catches "bundle missed a new hard dependency" failures before packaging.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HOTFIX_BUNDLE_PATHS = (
    "config/feature_flags.json",
    "install.ps1",
    "install.sh",
    "src/dialog_entry_proxy.py",
    "src/evidence_bound_model.py",
    "src/memory_authority_policy.py",
    "src/update_source.py",
    "system/openclaw/plugins/time-library-native/index.js",
    "system/openclaw/plugins/time-library-native/openclaw.plugin.json",
    "tests/test_security_boundaries.py",
    "tools/hotfix_bundle_import_check.py",
    "tools/linux_full_install.sh",
    "tools/macos_full_install.sh",
    "tools/windows_full_install.ps1",
)

BASE_IMPORT_CLOSURE_PATHS = (
    "VERSION",
    "config/memcore.json",
    "config/default_feature_flags.json",
    "src/config_loader.py",
    "src/dialog_intent_router.py",
    "src/openclaw_routing_resolver.py",
    "src/openclaw_ws_rpc_client.py",
    "src/zhiyi_entry_intent.py",
)


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"[hotfix-import-check] $ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def capture(cmd: list[str], *, cwd: Path, timeout_seconds: int = 20) -> str:
    return subprocess.check_output(cmd, cwd=str(cwd), text=True, timeout=timeout_seconds)


def export_base_ref(base_ref: str, target: Path) -> Path:
    source = target / "source"
    source.mkdir()
    print(f"[hotfix-import-check] exporting base ref {base_ref}", flush=True)
    for rel in BASE_IMPORT_CLOSURE_PATHS:
        if not rel:
            continue
        dst = source / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        data = subprocess.check_output(["git", "show", f"{base_ref}:{rel}"], cwd=str(ROOT), timeout=20)
        dst.write_bytes(data)
    return source


def overlay_hotfix_files(source: Path, paths: tuple[str, ...]) -> list[str]:
    copied: list[str] = []
    missing: list[str] = []
    for rel in paths:
        src = ROOT / rel
        dst = source / rel
        if not src.exists():
            missing.append(rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    if missing:
        raise SystemExit("hotfix bundle source files are missing:\n" + "\n".join(missing))
    return copied


def import_module_in_tree(source: Path, module: str) -> None:
    memcore_root = source / ".hotfix-import-check-root"
    memcore_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    src_dir = source / "src"
    env["PYTHONPATH"] = str(src_dir) + os.pathsep + str(source) + os.pathsep + env.get("PYTHONPATH", "")
    env["MEMCORE_ROOT"] = str(memcore_root)
    env["MEMCORE_INSTALL_ROOT"] = str(memcore_root)
    env["MEMCORE_CONFIG"] = str(source / "config" / "memcore.json")
    code = f"import importlib; importlib.import_module({module!r}); print('import_ok:{module}')"
    run([sys.executable, "-c", code], cwd=source, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a minimal hotfix bundle import closure.")
    parser.add_argument("--base-ref", default="v2026.6.16")
    parser.add_argument("--module", default="dialog_entry_proxy")
    parser.add_argument("--keep", action="store_true", help="keep the temporary draft tree")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="memcore-hotfix-bundle-"))
    try:
        source = export_base_ref(args.base_ref, tmp)
        copied = overlay_hotfix_files(source, HOTFIX_BUNDLE_PATHS)
        import_module_in_tree(source, args.module)
        print(json.dumps({
            "ok": True,
            "base_ref": args.base_ref,
            "module": args.module,
            "draft_tree": str(source),
            "base_import_closure": list(BASE_IMPORT_CLOSURE_PATHS),
            "hotfix_file_count": len(copied),
            "hotfix_files": copied,
        }, ensure_ascii=False, indent=2), flush=True)
        return 0
    finally:
        if args.keep:
            print(f"[hotfix-import-check] kept temp dir: {tmp}", flush=True)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
