"""
src/update_safety.py
Update Safety Guards
"""
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


KNOWN_CHECKSUMS = {
    "2026.5.25": {}
}

PLATFORM_ARCH_MATRIX = {
    "linux": {"arch": ["x86_64", "aarch64"], "os": ["linux"]},
    "windows": {"arch": ["x86_64", "i386"], "os": ["windows", "win32"]},
    "darwin": {"arch": ["arm64", "x86_64"], "os": ["darwin", "macos"]},
}

PROTECTED_UPDATE_PATHS = (
    "~/.ssh",
    "~/.openclaw/gateway/device_identity",
    "~/.openclaw/gateway/private_key",
    "memory",
    "raw",
    "zhiyi",
    "config",
    "logs",
    "backups",
)


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 of a file."""
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def verify_checksum(package_path: Path, expected_sha: str) -> Tuple[bool, str]:
    """Verify package SHA256 matches expected."""
    if not package_path.exists():
        return False, f"package not found: {package_path}"
    actual = compute_sha256(package_path)
    if actual != expected_sha:
        return False, f"checksum mismatch: expected {expected_sha[:16]}..., got {actual[:16]}..."
    return True, "checksum verified"


def verify_checksum_platform(package_path: Path, platform: str, version: str) -> Tuple[bool, str]:
    """Verify package checksum for a specific platform/version."""
    checksums = KNOWN_CHECKSUMS.get(version, {})
    expected = checksums.get(platform, "")
    if not expected:
        return False, f"no known checksum for {platform}/{version}"
    return verify_checksum(package_path, expected)


def verify_platform_arch(
    package_platform: str, package_arch: str, target_platform: str, target_arch: str
) -> Tuple[bool, str]:
    """Block platform/arch mismatch."""
    if package_platform != target_platform:
        return False, f"platform mismatch: package={package_platform}, target={target_platform}"
    if package_arch != target_arch:
        return False, f"arch mismatch: package={package_arch}, target={target_arch}"
    return True, "platform/arch verified"


def verify_package_metadata(
    package_path: Path, platform: str, version: str
) -> Tuple[bool, str, dict]:
    """
    Verify package metadata matches expected.
    Returns (ok, message, metadata_dict).
    """
    metadata_files = [
        package_path.parent / f"{package_path.stem}.metadata.json",
        package_path.parent / "metadata.json",
    ]
    for mf in metadata_files:
        if mf.exists():
            try:
                meta = json.loads(mf.read_text())
                meta_platform = meta.get("platform", "")
                meta_version = meta.get("version", "")
                # Normalize platform aliases (win32 == windows, darwin == darwin)
                platform_aliases = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
                norm_meta = platform_aliases.get(meta_platform, meta_platform)
                norm_target = platform_aliases.get(platform, platform)
                if meta_platform and norm_meta != norm_target:
                    return False, f"metadata platform mismatch: {meta_platform} != {platform}", meta
                if meta_version and meta_version != version:
                    return False, f"metadata version mismatch: {meta_version} != {version}", meta
                return True, "metadata verified", meta
            except Exception as e:
                return False, f"metadata parse error: {e}", {}
    return True, "no metadata file found (OK)", {}


def audit_log_sanitize(audit_entry: dict) -> dict:
    """
    Sanitize audit log: remove sensitive fields.
    Only query_hash, timestamp, action, result, platform, version are kept.
    """
    sensitive_fields = {"query", "token", "private_key", "secret", "password", "api_key", "raw_content"}
    sanitized = {}
    for k, v in audit_entry.items():
        if k.lower() in sensitive_fields or any(s in k.lower() for s in sensitive_fields):
            sanitized[k] = f"[REDACTED:{k}]"
        else:
            sanitized[k] = v
    # Always include hash of query if query present
    if "query" in audit_entry:
        q = audit_entry["query"]
        sanitized["query_hash"] = hashlib.sha256(str(q).encode()).hexdigest()[:16]
        if "query" in sanitized: del sanitized["query"]
    return sanitized


def generate_update_audit_log(
    action: str,
    result: str,
    platform: str,
    version: str,
    sandbox: bool = True,
    extra: Optional[dict] = None,
) -> dict:
    """Generate a sanitized audit log entry."""
    from datetime import datetime
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "action": action,
        "result": result,
        "platform": platform,
        "version": version,
        "sandbox": sandbox,
        "audit_version": "1.0",
    }
    if extra:
        entry.update(audit_log_sanitize(extra))
    return audit_log_sanitize(entry)


def detect_partial_apply_state(install_root: Path) -> str:
    """Detect current state of a partial apply."""
    marker = install_root / ".update_in_progress"
    if marker.exists():
        try:
            data = json.loads(marker.read_text())
            return data.get("state", "unknown")
        except Exception:
            return "unknown"
    completed = install_root / ".current_version"
    if completed.exists():
        return "complete"
    return "unknown"


def block_on_partial_apply(install_root: Path) -> Tuple[bool, str]:
    """Block apply if a previous partial apply is detected."""
    state = detect_partial_apply_state(install_root)
    if state == "in_progress":
        return False, f"BLOCKED: previous partial apply in progress at {install_root}"
    if state == "unknown":  # clean state: no previous apply
        return True, "no previous partial apply (clean state)"
    return True, "no partial apply detected"


def write_partial_apply_marker(install_root: Path, state: str, version: str) -> bool:
    """Write partial apply marker."""
    try:
        marker = install_root / ".update_in_progress"
        marker.write_text(json.dumps({"state": state, "version": version}, indent=2))
        return True
    except Exception:
        return False


def clear_partial_apply_marker(install_root: Path) -> bool:
    """Clear partial apply marker."""
    try:
        marker = install_root / ".update_in_progress"
        if marker.exists():
            marker.unlink()
        return True
    except Exception:
        return False
