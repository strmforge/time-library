#!/usr/bin/env python3
"""Package-manager inventory observation under Platform Guard.

Tiandao contract: this module observes package-manager install surfaces that may
indicate local AI tools. It is read-only inventory evidence, not the platform
catalog itself and not raw origin.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

UTC = timezone.utc
PACKAGE_MANAGER_INVENTORY_CONTRACT = "package_manager_agent_inventory.v1"
PACKAGE_MANAGER_INVENTORY_TIANDAO_CONTRACT = "tiandao_platform_guard_package_inventory.v1"
COMPOSE_FILENAMES = {
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
}
GENERIC_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".cache",
    "cache",
    "Caches",
    "node_modules",
    "Library",
    "System Volume Information",
    "$Recycle.Bin",
    "AppData",
    "Applications",
    "Program Files",
    "Program Files (x86)",
    "Windows",
    "Volumes",
    "dev",
    "proc",
    "run",
    "sys",
    "tmp",
    "var",
}


def _catalog_module():
    candidates = (
        ("src.platform_guard_catalog", "platform_guard_catalog")
        if __name__.startswith("src.")
        else ("platform_guard_catalog", "src.platform_guard_catalog")
    )
    last_error: Exception | None = None
    for name in candidates:
        try:
            import importlib
            return importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - fallback path
            last_error = exc
    if last_error:
        raise last_error
    raise ImportError("platform_guard_catalog")


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _effective_env(home: Path, env: dict[str, str] | None) -> dict[str, str]:
    resolved = dict(os.environ if env is None else env)
    home_text = str(home)
    resolved.setdefault("HOME", home_text)
    resolved.setdefault("USERPROFILE", home_text)
    resolved.setdefault("CODEX_HOME", str(home / ".codex"))
    if "APPDATA" not in resolved:
        resolved["APPDATA"] = str(home / "AppData" / "Roaming")
    if "LOCALAPPDATA" not in resolved:
        resolved["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    if "XDG_CONFIG_HOME" not in resolved:
        resolved["XDG_CONFIG_HOME"] = str(home / ".config")
    return resolved


def get_platform_guard_package_inventory_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": PACKAGE_MANAGER_INVENTORY_TIANDAO_CONTRACT,
        "inventory_contract": PACKAGE_MANAGER_INVENTORY_CONTRACT,
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "workbench_id": "platform_guard",
        "console_layer": "platform_guard_package_inventory",
        "source_authority": "platform_guard_catalog",
        "not_raw_origin": True,
        "read_only_by_default": True,
        "write_capable": False,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "raw_origin_policy": "package-manager inventory observes install surfaces but does not replace Time Origin",
    }


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _safe_iterdir(path: Path, limit: int | None = None) -> list[Path]:
    try:
        children = list(path.iterdir())
    except OSError:
        return []
    if limit is not None:
        return children[:limit]
    return children


def _read_small_text(path: Path, limit: int = 65536) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _catalog_system_for_install_name(name: str) -> str | None:
    return _catalog_module()._catalog_system_for_install_name(name)


def _catalog_entry(system: str) -> dict[str, Any]:
    return _catalog_module()._catalog_entry(system)


def _catalog_entry_summary(system: str) -> dict[str, Any]:
    return _catalog_module()._catalog_entry_summary(system)


def _generic_scan_roots(home: Path, env: dict[str, str]) -> list[Path]:
    return _catalog_module()._generic_scan_roots(home, env)

def _env_paths(env: dict[str, str], key: str) -> list[Path]:
    value = env.get(key, "")
    return [Path(item).expanduser() for item in value.split(os.pathsep) if item.strip()]


def _existing_unique_dirs(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen = set()
    for path in paths:
        try:
            resolved = path.expanduser()
        except Exception:
            resolved = path
        text = str(resolved)
        if text in seen or not _safe_is_dir(resolved):
            continue
        unique.append(resolved)
        seen.add(text)
    return unique


def _npm_global_roots(home: Path, env: dict[str, str]) -> list[Path]:
    roots = _env_paths(env, "MEMCORE_NPM_GLOBAL_ROOT")
    if env.get("MEMCORE_PACKAGE_SCAN_STRICT_ROOTS") == "1":
        return _existing_unique_dirs(roots)
    roots.extend([
        home / ".npm-global" / "lib" / "node_modules",
        home / ".volta" / "tools" / "image" / "packages",
        Path("/opt/homebrew/lib/node_modules"),
        Path("/usr/local/lib/node_modules"),
    ])
    roots.extend(Path(item) for item in glob.glob(str(home / ".nvm" / "versions" / "node" / "*" / "lib" / "node_modules")))
    roots.extend(Path(item) for item in glob.glob(str(home / ".local" / "share" / "mise" / "installs" / "node" / "*" / "lib" / "node_modules")))
    return _existing_unique_dirs(roots)


def _package_json_metadata(path: Path) -> dict[str, str]:
    data = _load_json_object(path / "package.json")
    return {
        "version": str(data.get("version") or ""),
        "description": str(data.get("description") or "")[:240],
    }


def _scan_npm_global(home: Path, env: dict[str, str]) -> dict[str, Any]:
    roots = _npm_global_roots(home, env)
    items: list[dict[str, Any]] = []
    for root in roots:
        try:
            children = _safe_iterdir(root, limit=500)
        except Exception:
            continue
        for child in children:
            if not _safe_is_dir(child):
                continue
            if child.name.startswith("@"):
                scoped_children = _safe_iterdir(child, limit=200)
                for scoped in scoped_children:
                    if _safe_is_dir(scoped):
                        meta = _package_json_metadata(scoped)
                        items.append({
                            "manager": "npm_global",
                            "name": f"{child.name}/{scoped.name}",
                            "path": str(scoped),
                            **meta,
                        })
            else:
                meta = _package_json_metadata(child)
                items.append({
                    "manager": "npm_global",
                    "name": child.name,
                    "path": str(child),
                    **meta,
                })
    return {"roots": [str(root) for root in roots], "items": items}


def _pipx_roots(home: Path, env: dict[str, str]) -> list[Path]:
    roots = _env_paths(env, "MEMCORE_PIPX_HOME")
    if env.get("MEMCORE_PACKAGE_SCAN_STRICT_ROOTS") == "1":
        return _existing_unique_dirs(roots)
    roots.extend([
        home / ".local" / "pipx",
        home / ".local" / "share" / "pipx",
        home / ".pipx",
    ])
    return _existing_unique_dirs(roots)


def _scan_pipx(home: Path, env: dict[str, str]) -> dict[str, Any]:
    roots = _pipx_roots(home, env)
    items: list[dict[str, Any]] = []
    for root in roots:
        venvs = root / "venvs"
        if not _safe_is_dir(venvs):
            continue
        children = _safe_iterdir(venvs, limit=500)
        for child in children:
            if _safe_is_dir(child):
                items.append({
                    "manager": "pipx",
                    "name": child.name,
                    "path": str(child),
                    "version": "",
                    "description": "",
                })
    return {"roots": [str(root) for root in roots], "items": items}


def _brew_prefixes(home: Path, env: dict[str, str]) -> list[Path]:
    roots = _env_paths(env, "MEMCORE_BREW_PREFIX")
    if env.get("MEMCORE_PACKAGE_SCAN_STRICT_ROOTS") == "1":
        return _existing_unique_dirs(roots)
    if env.get("HOMEBREW_PREFIX"):
        roots.append(Path(env["HOMEBREW_PREFIX"]))
    roots.extend([Path("/opt/homebrew"), Path("/usr/local")])
    return _existing_unique_dirs(roots)


def _scan_homebrew(home: Path, env: dict[str, str]) -> dict[str, Any]:
    prefixes = _brew_prefixes(home, env)
    items: list[dict[str, Any]] = []
    for prefix in prefixes:
        cellar = prefix / "Cellar"
        if not _safe_is_dir(cellar):
            continue
        formulae = _safe_iterdir(cellar, limit=800)
        for formula in formulae:
            if not _safe_is_dir(formula):
                continue
            version = ""
            versions = sorted([child.name for child in _safe_iterdir(formula) if _safe_is_dir(child)])
            version = versions[-1] if versions else ""
            items.append({
                "manager": "homebrew",
                "name": formula.name,
                "path": str(formula),
                "version": version,
                "description": "",
            })
    return {"roots": [str(root) for root in prefixes], "items": items}


def _docker_image_lines(env: dict[str, str]) -> list[str]:
    override = env.get("MEMCORE_DOCKER_IMAGE_LIST", "")
    if override:
        path = Path(override).expanduser()
        if _safe_is_file(path):
            return _read_small_text(path, limit=1_000_000).splitlines()
        return override.splitlines()
    docker = shutil.which("docker")
    if env.get("MEMCORE_PACKAGE_SCAN_STRICT_ROOTS") == "1":
        return []
    if not docker:
        return []
    try:
        result = subprocess.run(
            [docker, "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def _scan_docker_images(env: dict[str, str]) -> dict[str, Any]:
    items = []
    for line in _docker_image_lines(env):
        name = line.strip()
        if not name or name.startswith("<none>"):
            continue
        items.append({
            "manager": "docker_image",
            "name": name,
            "path": "",
            "version": name.rsplit(":", 1)[-1] if ":" in name else "",
            "description": "",
        })
    return {"roots": [], "items": items}


def _iter_compose_files(
    roots: list[Path],
    *,
    max_depth: int = 4,
    max_dirs: int = 1200,
) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    dirs_seen = 0
    queue: list[tuple[Path, int]] = [(root, 0) for root in roots]
    while queue and dirs_seen < max_dirs:
        current, depth = queue.pop(0)
        if depth > max_depth or current.name in GENERIC_SKIP_DIRS:
            continue
        dirs_seen += 1
        children = _safe_iterdir(current)
        for child in children:
            if _safe_is_file(child) and child.name in COMPOSE_FILENAMES:
                text = str(child)
                if text not in seen:
                    found.append(child)
                    seen.add(text)
            elif _safe_is_dir(child) and depth < max_depth and child.name not in GENERIC_SKIP_DIRS:
                queue.append((child, depth + 1))
    return found


def _scan_compose_files(roots: list[Path]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for path in _iter_compose_files(roots):
        text = _read_small_text(path, limit=300_000)
        for match in re.finditer(r"(?im)^\s*image:\s*[\"']?([^\"'\s#]+)", text):
            name = match.group(1).strip()
            if name:
                items.append({
                    "manager": "docker_compose",
                    "name": name,
                    "path": str(path),
                    "version": name.rsplit(":", 1)[-1] if ":" in name else "",
                    "description": "",
                })
    return {"roots": [str(root) for root in roots], "items": items}


def _package_manager_matches(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source_name, source in sources.items():
        for item in source.get("items", []):
            name = str(item.get("name") or "")
            system = _catalog_system_for_install_name(name)
            if not system:
                continue
            key = (system, source_name, name)
            if key in seen:
                continue
            seen.add(key)
            matches.append({
                "system": system,
                "display_name": (_catalog_entry(system) or {}).get("display_name") or system,
                "catalog_entry": _catalog_entry_summary(system),
                "manager": source_name,
                "name": name,
                "path": item.get("path", ""),
                "version": item.get("version", ""),
                "description": item.get("description", ""),
                "read_only": True,
                "source_read": False,
            })
    return matches


def build_package_manager_agent_inventory(
    *,
    home: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    resolved_home = home or Path.home()
    resolved_env = _effective_env(resolved_home, env)
    roots = _generic_scan_roots(resolved_home, resolved_env)
    sources = {
        "npm_global": _scan_npm_global(resolved_home, resolved_env),
        "pipx": _scan_pipx(resolved_home, resolved_env),
        "homebrew": _scan_homebrew(resolved_home, resolved_env),
        "docker_image": _scan_docker_images(resolved_env),
        "docker_compose": _scan_compose_files(roots),
    }
    matches = _package_manager_matches(sources)
    return {
        "ok": True,
        "contract": PACKAGE_MANAGER_INVENTORY_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "source_read": False,
        "source_count": len(sources),
        "item_count": sum(len(source.get("items", [])) for source in sources.values()),
        "match_count": len(matches),
        "sources": sources,
        "matches": matches,
        "global_guarantees": {
            "does_not_install_packages": True,
            "does_not_write_platform_config": True,
            "does_not_parse_chat_bodies": True,
            "does_not_read_source_files": True,
        },
    }



__all__ = [
    "PACKAGE_MANAGER_INVENTORY_CONTRACT",
    "PACKAGE_MANAGER_INVENTORY_TIANDAO_CONTRACT",
    "get_platform_guard_package_inventory_contract",
    "_effective_env",
    "_env_paths",
    "_existing_unique_dirs",
    "_npm_global_roots",
    "_package_json_metadata",
    "_scan_npm_global",
    "_pipx_roots",
    "_scan_pipx",
    "_brew_prefixes",
    "_scan_homebrew",
    "_docker_image_lines",
    "_scan_docker_images",
    "_iter_compose_files",
    "_scan_compose_files",
    "_package_manager_matches",
    "build_package_manager_agent_inventory",
]
