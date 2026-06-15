"""
C2: GitHub / source update source module.
Provides version checking, archive download, staging, and flat-install apply.

Design:
- Default source: the current GitHub release (VERSION + source archive)
- Overridable via env vars MEMCORE_UPDATE_VERSION_URL, MEMCORE_UPDATE_ARCHIVE_URL
- Staging: <MEMCORE_ROOT>/update_staging/ or system temp dir
- Version comparison: date-based (2026.5.25 < 2026.5.26)
- Flat apply: replace program files in the current install root while preserving
  user data, local configuration, logs, backups, and virtualenv state.
"""

import os, re, hashlib, json, zipfile, shutil, tempfile, sys, subprocess, time
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.request import urlopen, Request
from urllib.error import URLError

# Default URLs
DEFAULT_UPDATE_VERSION = os.environ.get("MEMCORE_UPDATE_VERSION") or "2026.6.16"
DEFAULT_RELEASE_TAG = os.environ.get("MEMCORE_UPDATE_RELEASE_TAG") or f"v{DEFAULT_UPDATE_VERSION}"
DEFAULT_VERSION_URL = f"https://github.com/strmforge/memcore-cloud/releases/download/{DEFAULT_RELEASE_TAG}/VERSION"
DEFAULT_ARCHIVE_URL = f"https://github.com/strmforge/memcore-cloud/releases/download/{DEFAULT_RELEASE_TAG}/memcore-cloud-{DEFAULT_UPDATE_VERSION}.zip"

# Forbidden paths in update packages
FORBIDDEN_ROOTS = [
    "memory/", "zhiyi/", "experience_lancedb/", "raw/", ".git/",
    "logs/", "backups/", "update_staging/", ".venv/"
]
FORBIDDEN_EXTS = [".bak", ".v4bak", ".pyc"]
FORBIDDEN_NAMES = {"__pycache__"}

PERSISTENT_TOP_LEVELS = {
    ".git", ".venv", "memory", "zhiyi", "experience_lancedb",
    "raw", "logs", "backups", "data", "state", "input", "output",
    "update_staging",
}

REPLACEABLE_TOP_LEVELS = {
    "src", "tools", "web", "system", "assets",
    "CHANGELOG.md", "LICENSE", "README.md", "README.en.md",
    "README.zh-CN.md", "UPDATE_HISTORY.md", "VERSION", "install.sh", "install.ps1",
    "Memcore Cloud Installer.command", "Memcore Cloud Installer.cmd",
    "uninstall.sh", "uninstall.ps1", "requirements.txt",
    "requirements-core.txt", "requirements-dev.txt", "requirements-vector.txt",
}

CONFIG_COPY_IF_MISSING = {
    "alias_map.json", "feature_flags.json", "intent_router_rules.json",
    "lancedb_v2_metadata.json", "model_config.json", "source_system_registry.json",
    "zhiyi_freshness_policy.json", "zhiyi_injection_policy.json",
    "zhiyi_ranking_policy.json", "zhiyi_relevance_policy.json",
    "zhiyi_scope_metadata.json", "default_alias_map.json",
    "default_feature_flags.json", "default_init_state.json",
    "default_model_config.json", "default_window_binding_registry.json",
}


def _get_version_url() -> str:
    return os.environ.get("MEMCORE_UPDATE_VERSION_URL") or DEFAULT_VERSION_URL


def _get_archive_url() -> str:
    return os.environ.get("MEMCORE_UPDATE_ARCHIVE_URL") or DEFAULT_ARCHIVE_URL


def _get_staging_dir(memcore_root: str) -> str:
    """Return a safe staging directory for downloaded update packages."""
    # Prefer MEMCORE_ROOT/update_staging/ if writable
    root_staging = os.path.join(memcore_root, "update_staging")
    try:
        Path(root_staging).mkdir(parents=True, exist_ok=True)
        test_file = os.path.join(root_staging, ".write_test")
        Path(test_file).write_text("")
        os.remove(test_file)
        return root_staging
    except (OSError, PermissionError):
        pass
    # Fallback to system temp
    tmp = os.path.join(tempfile.gettempdir(), "memcore-update-staging")
    Path(tmp).mkdir(parents=True, exist_ok=True)
    return tmp


def _safe_extract_zip(zip_path: str, target_dir: str) -> list:
    """Extract zip safely, preventing path traversal. Returns list of extracted file paths."""
    target = Path(target_dir).resolve()
    extracted = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            # Path traversal check
            clean_name = name.replace('\\', '/')
            if '..' in clean_name.split('/') or clean_name.startswith('/'):
                raise ValueError(f"Path traversal detected in zip: {name}")
            dest = (target / clean_name).resolve()
            if not str(dest).startswith(str(target)):
                raise ValueError(f"Zip slip: {name}")
            if name.endswith('/'):
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(dest, 'wb') as dst:
                    dst.write(src.read())
            extracted.append(str(dest))
    return extracted


def _strip_archive_root(name: str) -> str:
    """Strip GitHub archive root directory, e.g. memcore-cloud-main/src/a.py."""
    clean = name.replace('\\', '/').lstrip('/')
    parts = clean.split('/')
    if len(parts) > 1 and parts[0].startswith("memcore-cloud"):
        return "/".join(parts[1:])
    return clean


def _forbidden_archive_path(name: str) -> Optional[str]:
    """Return a reason if a package entry targets user data/state."""
    rel = _strip_archive_root(name).lower()
    if not rel:
        return None
    for forbidden in FORBIDDEN_ROOTS:
        if rel.startswith(forbidden):
            return forbidden
    parts = rel.split('/')
    if any(part in FORBIDDEN_NAMES for part in parts):
        return "__pycache__"
    if any(rel.endswith(ext) for ext in FORBIDDEN_EXTS):
        return "forbidden extension"
    return None


def _find_project_root(extract_dir: str) -> Path:
    root = Path(extract_dir)
    if (root / "VERSION").exists() and (root / "src").exists():
        return root
    for child in root.iterdir():
        if child.is_dir() and (child / "VERSION").exists() and (child / "src").exists():
            return child
    raise ValueError("Extracted package does not contain VERSION + src")


def _read_package_text(package_path: str, wanted_basename: str) -> Optional[str]:
    with zipfile.ZipFile(package_path) as zf:
        for name in zf.namelist():
            if _strip_archive_root(name) == wanted_basename or name.endswith("/" + wanted_basename):
                return zf.read(name).decode("utf-8", errors="replace").strip()
    return None


def _copytree_replace(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    shutil.copytree(src, dst, symlinks=False, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _copy_config_preserving_user_values(new_config_dir: Path, install_config_dir: Path, steps: list) -> None:
    install_config_dir.mkdir(parents=True, exist_ok=True)
    if not new_config_dir.exists():
        steps.append({"action": "merge_config", "status": "skip", "reason": "no config dir in package"})
        return
    copied = []
    skipped = []
    for item in new_config_dir.iterdir():
        if not item.is_file():
            continue
        dst = install_config_dir / item.name
        should_copy = (item.name.startswith("default_") or item.name in CONFIG_COPY_IF_MISSING) and not dst.exists()
        if should_copy:
            shutil.copy2(item, dst)
            copied.append(item.name)
        else:
            skipped.append(item.name)
    steps.append({
        "action": "merge_config",
        "status": "pass",
        "copied": copied,
        "preserved_existing": skipped,
    })


def _snapshot_current_install(memcore_root: Path, backup_dir: Path, steps: list) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    errors = []
    for name in sorted(REPLACEABLE_TOP_LEVELS | {"config", ".checkpoint", ".checkpoint_p2.json"}):
        src = memcore_root / name
        if not src.exists():
            continue
        dst = backup_dir / name
        try:
            if src.is_dir():
                shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_symlink():
                    os.symlink(os.readlink(src), dst)
                else:
                    shutil.copy2(src, dst)
            copied.append(name)
        except Exception as exc:
            errors.append({"item": name, "error": str(exc)[:300]})
    (backup_dir / "rollback.json").write_text(json.dumps({
        "backup_dir": str(backup_dir),
        "restore_hint": "Stop Yifanchen, copy these files back to install root, then start it again.",
        "snapshotted": copied,
        "snapshot_errors": errors,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    steps.append({
        "action": "snapshot",
        "status": "pass_with_warnings" if errors else "pass",
        "backup_dir": str(backup_dir),
        "items": copied,
        "errors": errors,
    })


def _write_update_history(memcore_root: Path, entry: dict) -> None:
    hist = memcore_root / "update_history.jsonl"
    with open(hist, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _write_restart_script(memcore_root: Path, python_exe: str, delay_seconds: float = 1.2) -> Path:
    staging = Path(_get_staging_dir(str(memcore_root)))
    script = staging / "restart_yifanchen_after_update.py"
    src_dir = str((memcore_root / "src").resolve())
    root_dir = str(memcore_root.resolve())
    log_path = str((memcore_root / "logs" / "update_restart.log").resolve())
    payload = f'''#!/usr/bin/env python3
import json, os, signal, subprocess, time
from pathlib import Path

MEMCORE_ROOT = {str(memcore_root)!r}
SRC_DIR = {src_dir!r}
ROOT_DIR = {root_dir!r}
PYTHON = {python_exe!r}
LOG_PATH = {log_path!r}

def read_dialog_entry_host():
    default = os.environ.get("MEMCORE_DIALOG_ENTRY_HOST") or "127.0.0.1"
    cfg_path = Path(ROOT_DIR) / "config" / "memcore.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        services = cfg.get("services") if isinstance(cfg, dict) else {{}}
        host = str((services or {{}}).get("dialog_entry_host") or "").strip()
        return host or default
    except Exception:
        return default

DIALOG_ENTRY_HOST = read_dialog_entry_host()
SCRIPTS = [
    ("memcore-cloud.py", [PYTHON, str(Path(SRC_DIR) / "memcore-cloud.py"), "--watch"]),
    ("p3_recall.py", [PYTHON, str(Path(SRC_DIR) / "p3_recall.py"), "serve", "--port", "9830"]),
    ("p4_provider.py", [PYTHON, str(Path(SRC_DIR) / "p4_provider.py"), "--port", "9840"]),
    ("raw_consumption_gateway.py", [PYTHON, str(Path(SRC_DIR) / "raw_consumption_gateway.py")]),
    ("dialog_entry_proxy.py", [PYTHON, str(Path(SRC_DIR) / "dialog_entry_proxy.py"), "--host", DIALOG_ENTRY_HOST, "--port", "9860"]),
    ("p6_console.py", [PYTHON, str(Path(SRC_DIR) / "p6_console.py"), "--host", "127.0.0.1", "--port", "9850"]),
]

def log(msg):
    Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%S") + " " + msg + "\\n")

def process_rows():
    if os.name == "nt":
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
            if not out:
                return []
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            rows = []
            for item in data:
                rows.append((int(item.get("ProcessId")), item.get("CommandLine") or ""))
            return rows
        except Exception as exc:
            log(f"process listing failed: {{exc}}")
            return []
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        try:
            rows.append((int(parts[0]), parts[1]))
        except ValueError:
            continue
    return rows

def matching_pids_for(name=None):
    current = os.getpid()
    pids = []
    src_key = SRC_DIR.lower() if os.name == "nt" else SRC_DIR
    for pid, cmd in process_rows():
        if pid == current:
            continue
        haystack = cmd.lower() if os.name == "nt" else cmd
        if src_key in haystack and any(script_name in haystack for script_name, _ in SCRIPTS):
            if name is None or name.lower() in haystack:
                pids.append(pid)
    return pids

def stop_pid(pid, force=False):
    if os.name == "nt":
        cmd = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            cmd.append("/F")
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)

def popen_kwargs():
    if os.name == "nt":
        flags = 0
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        return {{"creationflags": flags}}
    return {{"start_new_session": True}}

def main():
    time.sleep({delay_seconds!r})
    pids = matching_pids_for()
    log("stopping " + ",".join(map(str, pids)))
    for pid in pids:
        try:
            stop_pid(pid, force=False)
        except Exception as exc:
            log(f"stop {{pid}} failed: {{exc}}")
    deadline = time.time() + 5.0
    while time.time() < deadline and matching_pids_for():
        time.sleep(0.2)
    for pid in matching_pids_for():
        try:
            stop_pid(pid, force=True)
        except Exception:
            pass
    time.sleep(0.5)
    env = os.environ.copy()
    env["MEMCORE_ROOT"] = MEMCORE_ROOT
    env["MEMCORE_INSTALL_ROOT"] = MEMCORE_ROOT
    env["PYTHONPATH"] = ROOT_DIR + os.pathsep + SRC_DIR + os.pathsep + env.get("PYTHONPATH", "")
    log_file = open(LOG_PATH, "ab", buffering=0)
    for name, cmd in SCRIPTS:
        if not (Path(SRC_DIR) / name).exists():
            continue
        if matching_pids_for(name):
            continue
        try:
            subprocess.Popen(cmd, cwd=MEMCORE_ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT, **popen_kwargs())
            log("started " + name)
        except Exception as exc:
            log(f"start {{name}} failed: {{exc}}")

if __name__ == "__main__":
    main()
'''
    script.write_text(payload, encoding="utf-8")
    script.chmod(0o755)
    return script


def schedule_restart(memcore_root: str) -> Dict[str, Any]:
    """Schedule a detached restart of local Yifanchen processes after the HTTP response is sent."""
    root = Path(memcore_root).resolve()
    script = _write_restart_script(root, sys.executable)
    log_path = root / "logs" / "update_restart.log"
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(root),
        env={**os.environ, "MEMCORE_ROOT": str(root), "MEMCORE_INSTALL_ROOT": str(root)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )
    return {"scheduled": True, "script": str(script), "log": str(log_path)}


def _parse_version(version_str: str) -> Optional[tuple]:
    """Parse '2026.5.25' into (2026, 5, 25) for comparison."""
    m = re.match(r'^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:[-.].*)?$', version_str.strip())
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two version strings.
    Returns -1 if v1 < v2, 0 if equal, 1 if v1 > v2.
    """
    p1 = _parse_version(v1)
    p2 = _parse_version(v2)
    if p1 is None or p2 is None:
        # Fallback to string comparison for non-standard versions
        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        return 0
    if p1 < p2:
        return -1
    elif p1 > p2:
        return 1
    return 0


def check_remote_version() -> Dict[str, Any]:
    """
    Fetch the latest version from the remote source.
    Returns dict with: ok, latest_version, metadata_source, error (if any)
    """
    url = _get_version_url()
    try:
        req = Request(url, headers={"User-Agent": "memcore-cloud-updater/1.0"})
        with urlopen(req, timeout=10) as resp:
            # file:// URLs have status=None; accept any non-error response
            if resp.status is not None and resp.status != 200:
                return {"ok": False, "error": f"HTTP {resp.status}", "metadata_source": "http_error"}
            body = resp.read().decode("utf-8", errors="replace").strip()
            parsed = _parse_version(body)
            if not parsed:
                return {"ok": False, "error": f"Unparseable version: {body[:50]}", "metadata_source": "parse_error"}
            source = "file" if url.startswith("file://") else "github_raw"
            return {
                "ok": True,
                "latest_version": body,
                "metadata_source": source,
            }
    except URLError as e:
        return {"ok": False, "error": str(e.reason)[:100], "metadata_source": "network_error"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100], "metadata_source": "error"}


def download_update_archive(memcore_root: str) -> Dict[str, Any]:
    """
    Download update archive from source, verify, store in staging.
    Returns dict with: ok, downloaded, package_path, package_sha256, target_version, staging_dir, error
    """
    staging = _get_staging_dir(memcore_root)
    archive_url = _get_archive_url()

    # Step 1: Check version first
    version_info = check_remote_version()
    if not version_info.get("ok"):
        return {
            "ok": False, "downloaded": False,
            "error": f"Version check failed: {version_info.get('error', 'unknown')}",
            "user_upload_required": False,
        }

    target_version = version_info["latest_version"]

    # Step 2: Download archive
    archive_name = f"memcore-cloud-{target_version}.zip"
    archive_path = os.path.join(staging, archive_name)

    try:
        req = Request(archive_url, headers={"User-Agent": "memcore-cloud-updater/1.0"})
        with urlopen(req, timeout=60) as resp:
            if resp.status is not None and resp.status != 200:
                return {
                    "ok": False, "downloaded": False,
                    "error": f"Download failed: HTTP {resp.status}",
                    "user_upload_required": False,
                }
            data = resp.read()
            if len(data) == 0:
                return {
                    "ok": False, "downloaded": False,
                    "error": "Downloaded empty archive",
                    "user_upload_required": False,
                }

            Path(archive_path).write_bytes(data)
    except URLError as e:
        return {
            "ok": False, "downloaded": False,
            "error": f"Download failed: {str(e.reason)[:100]}",
            "user_upload_required": False,
        }
    except Exception as e:
        return {
            "ok": False, "downloaded": False,
            "error": f"Download error: {str(e)[:100]}",
            "user_upload_required": False,
        }

    # Step 3: Verify archive
    try:
        sha256 = hashlib.sha256(Path(archive_path).read_bytes()).hexdigest()

        # Check it's a valid zip
        with zipfile.ZipFile(archive_path) as zf:
            names = zf.namelist()
            if len(names) == 0:
                raise ValueError("Empty zip archive")

            # Check for VERSION
            version_found = None
            for name in names:
                if name.endswith("/VERSION") or name == "VERSION":
                    v = zf.read(name).decode("utf-8", errors="replace").strip()
                    version_found = v
                    break

            if not version_found:
                raise ValueError("VERSION file not found in archive")

            # Check package version matches
            if version_found != target_version:
                raise ValueError(f"Package version {version_found} != expected {target_version}")

            # Check forbidden paths after stripping GitHub's top-level archive dir.
            for name in names:
                reason = _forbidden_archive_path(name)
                if reason:
                    raise ValueError(f"Forbidden path in archive: {name} ({reason})")

        return {
            "ok": True,
            "downloaded": True,
            "package_path": archive_path,
            "package_sha256": sha256,
            "target_version": target_version,
            "staging_dir": staging,
            "user_upload_required": False,
        }
    except ValueError as e:
        # Clean up invalid archive
        Path(archive_path).unlink(missing_ok=True)
        return {
            "ok": False, "downloaded": False,
            "error": f"Archive validation failed: {e}",
            "user_upload_required": False,
        }
    except Exception as e:
        Path(archive_path).unlink(missing_ok=True)
        return {
            "ok": False, "downloaded": False,
            "error": f"Archive verification error: {str(e)[:100]}",
            "user_upload_required": False,
        }


def validate_staged_package(package_path: str, memcore_root: str) -> Dict[str, Any]:
    """
    Validate a staged package: dry-run extraction, forbidden path scan, version check.
    Returns dict compatible with the dry-run API response.
    """
    result = {
        "ok": True,
        "dry_run": True,
        "forbidden_paths_found": False,
        "target_version": None,
        "entries": 0,
        "errors": [],
    }

    pkg = Path(package_path)
    if not pkg.exists():
        result["ok"] = False
        result["errors"].append("Package not found")
        return result

    staging = _get_staging_dir(memcore_root)
    extract_dir = os.path.join(staging, "__verify_" + pkg.stem)
    if Path(extract_dir).exists():
        shutil.rmtree(extract_dir)

    try:
        with zipfile.ZipFile(package_path) as zf:
            names = zf.namelist()
            result["entries"] = len(names)

            # Find version
            for name in names:
                if name.endswith("/VERSION") or name == "VERSION":
                    v = zf.read(name).decode("utf-8", errors="replace").strip()
                    result["target_version"] = v
                    break

            # Forbidden path check
            forbidden_found = []
            for name in names:
                if _forbidden_archive_path(name):
                    forbidden_found.append(name)

            if forbidden_found:
                result["forbidden_paths_found"] = True
                result["errors"].extend([f"Forbidden: {f}" for f in forbidden_found])

            # Safe extract to verify layout
            _safe_extract_zip(package_path, extract_dir)

            # Check layout
            extracted_items = list(Path(extract_dir).iterdir())
            result["extracted_count"] = len(extracted_items)
            result["top_items"] = [e.name for e in extracted_items]

    except Exception as e:
        result["ok"] = False
        result["errors"].append(str(e)[:200])
    finally:
        if Path(extract_dir).exists():
            shutil.rmtree(extract_dir)

    if result.get("errors"):
        result["ok"] = False

    result["user_upload_required"] = False
    return result


def apply_flat_update(memcore_root: str, package_path: str, target_version: Optional[str] = None) -> Dict[str, Any]:
    """Apply a source archive directly into the current install root."""
    root = Path(memcore_root).resolve()
    pkg = Path(package_path).resolve()
    steps = []
    if not root.exists():
        return {"ok": False, "stage": "apply_blocked", "error": f"install root not found: {root}", "steps": steps}
    if not pkg.exists():
        return {"ok": False, "stage": "apply_blocked", "error": f"package not found: {pkg}", "steps": steps}

    try:
        with zipfile.ZipFile(str(pkg)) as zf:
            names = zf.namelist()
        forbidden = [name for name in names if _forbidden_archive_path(name)]
        if forbidden:
            return {
                "ok": False,
                "stage": "package_forbidden_paths",
                "error": "package contains user data/state paths",
                "forbidden_paths": forbidden[:20],
                "steps": steps,
            }
        steps.append({"action": "package_scan", "status": "pass", "entries": len(names)})

        version = target_version or _read_package_text(str(pkg), "VERSION")
        if not version:
            return {"ok": False, "stage": "version_missing", "error": "VERSION not found in package", "steps": steps}
        from_version = (root / "VERSION").read_text(encoding="utf-8").strip() if (root / "VERSION").exists() else ""
        steps.append({"action": "detect_version", "status": "pass", "version": version})

        ts = time.strftime("%Y%m%d%H%M%S")
        backup_dir = root / "backups" / f"update-{ts}-{version}"
        _snapshot_current_install(root, backup_dir, steps)

        staging = Path(_get_staging_dir(str(root)))
        extract_dir = staging / f"apply-{ts}-{version}"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        _safe_extract_zip(str(pkg), str(extract_dir))
        project_root = _find_project_root(str(extract_dir))
        steps.append({"action": "safe_extract", "status": "pass", "project_root": str(project_root)})

        replaced = []
        skipped = []
        for item in project_root.iterdir():
            name = item.name
            if name in PERSISTENT_TOP_LEVELS:
                skipped.append(name)
                continue
            if name == "config":
                _copy_config_preserving_user_values(item, root / "config", steps)
                continue
            if name not in REPLACEABLE_TOP_LEVELS and not name.startswith("requirements"):
                skipped.append(name)
                continue
            dst = root / name
            if item.is_dir():
                _copytree_replace(item, dst)
            else:
                if dst.exists() or dst.is_symlink():
                    dst.unlink()
                shutil.copy2(item, dst)
            replaced.append(name)
        steps.append({"action": "replace_program_files", "status": "pass", "replaced": sorted(replaced), "skipped": sorted(skipped)})

        shutil.rmtree(extract_dir, ignore_errors=True)
        history = {
            "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "version": version,
            "from_version": from_version,
            "package": str(pkg),
            "package_sha256": hashlib.sha256(pkg.read_bytes()).hexdigest(),
            "backup_dir": str(backup_dir),
            "mode": "flat_install_apply",
            "dry_run": False,
            "steps": steps,
        }
        _write_update_history(root, history)
        steps.append({"action": "write_history", "status": "pass", "history": str(root / "update_history.jsonl")})
        return {
            "ok": True,
            "stage": "applied",
            "target_version": version,
            "from_version": from_version,
            "backup_dir": str(backup_dir),
            "package_path": str(pkg),
            "restart_required": True,
            "dry_run": False,
            "install_enabled": True,
            "production_apply": True,
            "steps": steps,
        }
    except Exception as e:
        return {"ok": False, "stage": "apply_failed", "error": str(e)[:300], "steps": steps}


def one_click_update(memcore_root: str, current_version: str, apply: bool = False, restart: bool = False) -> Dict[str, Any]:
    """
    One-click update flow: check version → download → validate → optional apply.
    """
    # Step 1: Check version
    version_info = check_remote_version()
    if not version_info.get("ok"):
        return {
            "ok": False,
            "stage": "version_check_failed",
            "error": version_info.get("error", "Version check failed"),
            "update_available": False,
            "user_upload_required": False,
        }

    latest = version_info["latest_version"]

    # Check if newer
    if compare_versions(current_version, latest) >= 0:
        return {
            "ok": True,
            "stage": "up_to_date",
            "update_available": False,
            "current_version": current_version,
            "latest_version": latest,
            "message": "当前已是最新版本",
            "user_upload_required": False,
        }

    # Step 2: Download
    download_info = download_update_archive(memcore_root)
    if not download_info.get("ok"):
        return {
            "ok": False,
            "stage": "download_failed",
            "error": download_info.get("error", "Download failed"),
            "update_available": True,
            "target_version": latest,
            "user_upload_required": False,
        }

    # Step 3: Validate
    validate_info = validate_staged_package(download_info["package_path"], memcore_root)

    result = {
        "ok": validate_info.get("ok", False),
        "stage": "downloaded_and_validated" if validate_info.get("ok") else "validation_failed",
        "update_available": True,
        "target_version": download_info["target_version"],
        "current_version": current_version,
        "latest_version": latest,
        "downloaded": True,
        "package_path": download_info["package_path"],
        "package_sha256": download_info["package_sha256"],
        "dry_run": not apply,
        "install_enabled": True,
        "production_apply": bool(apply),
        "forbidden_paths_found": validate_info.get("forbidden_paths_found", False),
        "entry_count": validate_info.get("entries", 0),
        "user_upload_required": False,
        "message": "更新包已下载并验证",
    }
    if not validate_info.get("ok"):
        return result
    if not apply:
        return result

    apply_result = apply_flat_update(memcore_root, download_info["package_path"], target_version=download_info["target_version"])
    result.update({
        "ok": apply_result.get("ok", False),
        "stage": apply_result.get("stage", "apply_failed"),
        "applied": apply_result.get("ok", False),
        "backup_dir": apply_result.get("backup_dir"),
        "restart_required": apply_result.get("restart_required", False),
        "apply_steps": apply_result.get("steps", []),
        "error": apply_result.get("error"),
        "message": "更新已应用，正在重启本机服务" if apply_result.get("ok") else apply_result.get("error", "更新应用失败"),
    })
    if apply_result.get("ok") and restart:
        result["restart"] = schedule_restart(memcore_root)
    return result
