#!/usr/bin/env python3
"""Well-known local endpoint discovery for Time Library clients."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_FRONT_DOOR_PORT = 9850
PORT_FILE_NAME = "front_door_port"
LEGACY_PUBLIC_PORTS = frozenset({9830, 9840, 9851, 9860})
LEGACY_HEALTH_SERVICES = frozenset({
    "p3_recall",
    "p4_provider",
    "p6_console",
    "raw_consumption_gateway",
    "dialog_entry_proxy",
})


def installation_root(root: str | os.PathLike[str] | None = None) -> Path:
    explicit = str(root or os.environ.get("TIME_LIBRARY_ROOT") or os.environ.get("MEMCORE_ROOT") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve(strict=False)
    return Path(__file__).resolve().parents[1]


def port_file_path(root: str | os.PathLike[str] | None = None) -> Path:
    return installation_root(root) / "runtime" / PORT_FILE_NAME


def validate_port(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("port must be an integer")
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    return port


def write_port_atomic(port: int, root: str | os.PathLike[str] | None = None) -> Path:
    validated = validate_port(port)
    path = port_file_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as handle:
            handle.write(f"{validated}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return path


def read_port(
    root: str | os.PathLike[str] | None = None,
    *,
    fallback: int | None = None,
) -> int:
    path = port_file_path(root)
    try:
        return validate_port(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, ValueError):
        if fallback is None:
            raise RuntimeError(f"Time Library front-door port is unavailable: {path}")
        return validate_port(fallback)


def front_door_url(
    path: str = "",
    root: str | os.PathLike[str] | None = None,
    *,
    fallback: int | None = None,
) -> str:
    suffix = str(path or "").strip()
    if suffix and not suffix.startswith("/"):
        suffix = "/" + suffix
    return f"http://127.0.0.1:{read_port(root, fallback=fallback)}{suffix}"


def is_legacy_loopback_endpoint(endpoint: str) -> bool:
    text = str(endpoint or "").strip()
    if not text:
        return False
    try:
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"} and port in LEGACY_PUBLIC_PORTS


def _health_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    return urlunparse((parsed.scheme or "http", parsed.netloc, "/health", "", "", ""))


def verify_time_library_endpoint(endpoint: str, *, front_door: bool, timeout: float = 0.75) -> bool:
    try:
        request = Request(_health_url(endpoint), headers={"Accept": "application/json"}, method="GET")
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return False
    service = str(payload.get("service") or "").strip()
    if front_door:
        return service == "time-library-front-door" and payload.get("user_visible_address_count") == 1
    return service in LEGACY_HEALTH_SERVICES


def resolve_client_url(
    path: str,
    *,
    endpoint: str = "",
    root: str | os.PathLike[str] | None = None,
    fallback: int | None = None,
    verify: bool = True,
    wait_timeout: float = 0.0,
    retry_interval: float = 0.05,
) -> str:
    deadline = time.monotonic() + max(0.0, float(wait_timeout))
    while True:
        try:
            return _resolve_client_url_once(
                path,
                endpoint=endpoint,
                root=root,
                fallback=fallback,
                verify=verify,
            )
        except RuntimeError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(max(0.01, float(retry_interval)), remaining))


def _resolve_client_url_once(
    path: str,
    *,
    endpoint: str = "",
    root: str | os.PathLike[str] | None = None,
    fallback: int | None = None,
    verify: bool = True,
) -> str:
    explicit = str(endpoint or "").strip()
    if explicit and not is_legacy_loopback_endpoint(explicit):
        return explicit
    discovery_present = port_file_path(root).exists()
    try:
        discovery_path = path
        if explicit:
            parsed = urlparse(explicit)
            legacy_path = parsed.path or ""
            if parsed.query:
                legacy_path = f"{legacy_path}?{parsed.query}"
            if legacy_path:
                discovery_path = legacy_path
        resolved = front_door_url(discovery_path, root, fallback=fallback)
        if verify and not verify_time_library_endpoint(resolved, front_door=True):
            raise RuntimeError(f"Time Library front-door identity check failed: {_health_url(resolved)}")
        return resolved
    except RuntimeError:
        # Keep a pre-discovery client usable during migration; an installed
        # service with a valid discovery file always takes the new route.
        if explicit and (
            not verify
            or not discovery_present
            or verify_time_library_endpoint(explicit, front_door=False)
        ):
            return explicit
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve the Time Library local front-door endpoint")
    parser.add_argument("--root", default="")
    parser.add_argument("--path", default="")
    parser.add_argument("--fallback", type=int, default=None)
    parser.add_argument("--port-only", action="store_true")
    args = parser.parse_args()
    if args.port_only:
        print(read_port(args.root or None, fallback=args.fallback))
    else:
        print(front_door_url(args.path, args.root or None, fallback=args.fallback))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
