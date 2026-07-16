#!/usr/bin/env python3
"""Local encrypted credential storage for Time Library analysis models."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


MODEL_CREDENTIAL_STORE_CONTRACT = "time_library.model_credential_store.v1"
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_REF_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


def default_api_key_env(provider: str = "", provider_id: str = "") -> str:
    marker = " ".join((str(provider or ""), str(provider_id or ""))).lower()
    if "deepseek" in marker:
        return "DEEPSEEK_API_KEY"
    if "minimax" in marker:
        return "MINIMAX_API_KEY"
    return "MEMCORE_ZHIYI_API_KEY"


def is_valid_env_name(value: str) -> bool:
    return bool(_ENV_NAME_RE.fullmatch(str(value or "").strip()))


def looks_like_secret(value: str) -> bool:
    text = str(value or "").strip()
    if not text or is_valid_env_name(text):
        return False
    return len(text) >= 12 or text.lower().startswith(("sk-", "key-", "token-"))


def credential_ref_for(provider: str = "", provider_id: str = "") -> str:
    marker = str(provider_id or provider or "custom").strip().lower()
    marker = re.sub(r"[^a-z0-9._-]+", "-", marker).strip("-._") or "custom"
    return f"analysis-model:{marker}"[:128]


def _normalized_ref(value: str) -> str:
    ref = str(value or "").strip().lower()
    if not _REF_RE.fullmatch(ref):
        raise ValueError("invalid_credential_ref")
    return ref


def _root_path(root=None) -> Path:
    if root:
        return Path(root).expanduser()
    configured = os.environ.get("MEMCORE_ROOT") or os.environ.get("MEMCORE_INSTALL_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1]


def _paths(root=None) -> tuple[Path, Path]:
    config_dir = _root_path(root) / "config"
    return config_dir / ".model_credentials.key", config_dir / "model_credentials.enc.json"


def _write_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _load_or_create_key(root=None) -> bytes:
    key_path, _ = _paths(root)
    if key_path.is_file():
        key = key_path.read_bytes().strip()
        Fernet(key)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        return key
    key = Fernet.generate_key()
    _write_private(key_path, key + b"\n")
    return key


def _read_store(root=None) -> dict:
    _, store_path = _paths(root)
    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"schema_version": "1.0", "entries": {}}
    entries = payload.get("entries") if isinstance(payload, dict) else None
    return {
        "schema_version": "1.0",
        "entries": entries if isinstance(entries, dict) else {},
    }


def store_model_api_key(root, credential_ref: str, secret_value: str) -> dict:
    ref = _normalized_ref(credential_ref)
    secret = str(secret_value or "").strip()
    if not secret or len(secret) > 16_384 or any(ch.isspace() for ch in secret):
        raise ValueError("invalid_api_key_value")
    key = _load_or_create_key(root)
    payload = _read_store(root)
    payload["entries"][ref] = Fernet(key).encrypt(secret.encode("utf-8")).decode("ascii")
    _, store_path = _paths(root)
    _write_private(
        store_path,
        (json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8"),
    )
    return credential_status(root, ref)


def load_model_api_key(root, credential_ref: str) -> str:
    try:
        ref = _normalized_ref(credential_ref)
        key_path, _ = _paths(root)
        token = _read_store(root)["entries"].get(ref)
        if not token or not key_path.is_file():
            return ""
        return Fernet(key_path.read_bytes().strip()).decrypt(
            str(token).encode("ascii")
        ).decode("utf-8")
    except (OSError, ValueError, InvalidToken, UnicodeError):
        return ""


def credential_status(root, credential_ref: str) -> dict:
    try:
        ref = _normalized_ref(credential_ref)
    except ValueError:
        return {
            "configured": False,
            "credential_ref": "",
            "storage": "encrypted_local_file",
            "secret_value_returned": False,
        }
    configured = bool(load_model_api_key(root, ref))
    return {
        "configured": configured,
        "credential_ref": ref,
        "storage": "encrypted_local_file",
        "secret_value_returned": False,
    }


def resolve_model_api_key(
    root=None,
    *,
    api_key_env: str = "",
    credential_ref: str = "",
    transient_value: str = "",
    env=None,
) -> tuple[str, str]:
    transient = str(transient_value or "").strip()
    if transient:
        return transient, "request"
    environment = os.environ if env is None else env
    env_name = str(api_key_env or "").strip()
    if is_valid_env_name(env_name) and environment.get(env_name):
        return str(environment.get(env_name)), "environment"
    saved = load_model_api_key(root, credential_ref) if credential_ref else ""
    if saved:
        return saved, "encrypted_local_file"
    return "", "missing"


def migrate_legacy_binding_secret(root=None) -> dict:
    """Move a secret mistakenly saved as api_key_env into the encrypted store."""
    root_path = _root_path(root)
    binding_path = root_path / "config" / "zhiyi_model_binding.user.json"
    try:
        payload = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"migrated": False, "reason": "binding_unavailable"}
    if not isinstance(payload, dict):
        return {"migrated": False, "reason": "binding_invalid"}
    candidate = str(payload.get("api_key_env") or "").strip()
    if not looks_like_secret(candidate):
        return {"migrated": False, "reason": "no_legacy_secret"}
    ref = credential_ref_for(payload.get("provider"), payload.get("provider_id"))
    status = store_model_api_key(root_path, ref, candidate)
    payload["api_key_env"] = default_api_key_env(
        payload.get("provider"), payload.get("provider_id")
    )
    payload["credential_ref"] = ref
    payload["secrets_stored"] = True
    payload["secret_storage"] = "encrypted_local_file"
    payload["secret_values_returned"] = False
    _write_private(
        binding_path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return {
        "migrated": True,
        "credential_ref": ref,
        "credential_configured": bool(status.get("configured")),
        "plaintext_binding_scrubbed": True,
        "secret_value_returned": False,
    }


__all__ = [
    "MODEL_CREDENTIAL_STORE_CONTRACT",
    "credential_ref_for",
    "credential_status",
    "default_api_key_env",
    "is_valid_env_name",
    "load_model_api_key",
    "looks_like_secret",
    "migrate_legacy_binding_secret",
    "resolve_model_api_key",
    "store_model_api_key",
]
