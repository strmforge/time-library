#!/usr/bin/env python3
"""Single user-facing HTTP front door for existing Time Library services."""

from __future__ import annotations

import argparse
import errno
import http.client
import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping
from urllib.parse import urlparse

try:
    from src.port_discovery import (
        DEFAULT_FRONT_DOOR_PORT,
        installation_root,
        port_file_path,
        write_port_atomic,
    )
except Exception:
    from port_discovery import DEFAULT_FRONT_DOOR_PORT, installation_root, port_file_path, write_port_atomic


DEFAULT_HOST = "127.0.0.1"
DEFAULT_INTERNAL_PORTS = {
    "p3": 19300,
    "p4": 19400,
    "p6": 19500,
    "raw": 19510,
    "dialog": 19600,
}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
LOCK_FILE_NAME = "front_door.lock"
WINDOWS_FILETIME_TO_DATETIME_TICKS = 504_911_232_000_000_000
WINDOWS_PROCESS_FINGERPRINT_SCHEME = "windows_filetime_100ns_since_1601"
INTERNAL_SERVICE_CONNECT_GRACE_SECONDS = 3.0
INTERNAL_SERVICE_CONNECT_ATTEMPT_TIMEOUT_SECONDS = 0.25
INTERNAL_SERVICE_RETRY_INTERVAL_SECONDS = 0.05
INTERNAL_SERVICE_RESPONSE_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class Target:
    host: str
    port: int


class FrontDoorLock:
    def __init__(self, path: str, fd: int):
        self.path = path
        self.fd = fd
        self.inode = os.fstat(fd).st_ino

    def release(self) -> None:
        try:
            os.close(self.fd)
        finally:
            try:
                if os.stat(self.path).st_ino == self.inode:
                    os.unlink(self.path)
            except FileNotFoundError:
                pass


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            return bool(_windows_process_fingerprint(pid))
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_fingerprint(pid: int) -> str:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        error_code = ctypes.get_last_error()
        if error_code == 87:  # ERROR_INVALID_PARAMETER: PID does not exist.
            return ""
        if error_code == 5:  # ERROR_ACCESS_DENIED: process may still be alive.
            raise PermissionError(error_code, f"OpenProcess denied for PID {pid}")
        raise OSError(error_code, f"OpenProcess failed for PID {pid}")
    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel_time = wintypes.FILETIME()
    user_time = wintypes.FILETIME()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, f"GetProcessTimes failed for PID {pid}")
        return str((creation.dwHighDateTime << 32) | creation.dwLowDateTime)
    finally:
        kernel32.CloseHandle(handle)


def _process_fingerprint(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        if os.name == "nt":
            return _windows_process_fingerprint(pid)
        if not _process_exists(pid):
            return ""
        command = ["ps", "-p", str(pid), "-o", "lstart="]
        return subprocess.run(command, capture_output=True, text=True, timeout=2, check=False).stdout.strip()
    except Exception:
        return ""


def _process_fingerprints_match(
    expected: str,
    current: str,
    scheme: str,
    *,
    platform_name: str | None = None,
) -> bool:
    if expected == current:
        return True
    platform = platform_name or os.name
    if platform == "nt" and not scheme:
        try:
            return int(expected) == int(current) + WINDOWS_FILETIME_TO_DATETIME_TICKS
        except ValueError:
            return False
    return False


def acquire_front_door_lock(root: str | os.PathLike[str] | None = None) -> FrontDoorLock:
    runtime_root = installation_root(root) / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    path = runtime_root / LOCK_FILE_NAME
    for _attempt in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            payload = json.dumps({
                "pid": os.getpid(),
                "process_fingerprint": _process_fingerprint(os.getpid()),
                "process_fingerprint_scheme": (
                    WINDOWS_PROCESS_FINGERPRINT_SCHEME if os.name == "nt" else "posix_ps_lstart"
                ),
            }, separators=(",", ":"))
            os.write(fd, f"{payload}\n".encode("ascii"))
            os.fsync(fd)
            return FrontDoorLock(str(path), fd)
        except FileExistsError:
            try:
                existing_stat = path.stat()
                raw_lock = path.read_text(encoding="ascii").strip()
                try:
                    lock_data = json.loads(raw_lock)
                    pid = int(lock_data.get("pid") or 0)
                    expected_fingerprint = str(lock_data.get("process_fingerprint") or "")
                    expected_fingerprint_scheme = str(lock_data.get("process_fingerprint_scheme") or "")
                except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                    pid = int(raw_lock)
                    expected_fingerprint = ""
                    expected_fingerprint_scheme = ""
            except (OSError, UnicodeError, ValueError):
                pid = 0
                expected_fingerprint = ""
                expected_fingerprint_scheme = ""
                existing_stat = None
            current_fingerprint = _process_fingerprint(pid)
            if _process_exists(pid) and (
                not expected_fingerprint
                or not current_fingerprint
                or _process_fingerprints_match(
                    expected_fingerprint,
                    current_fingerprint,
                    expected_fingerprint_scheme,
                )
            ):
                raise RuntimeError(f"Time Library front door is already running (pid={pid})")
            try:
                if existing_stat is None or path.stat().st_ino == existing_stat.st_ino:
                    path.unlink()
            except FileNotFoundError:
                pass
    raise RuntimeError(f"Time Library front-door lock is unavailable: {path}")


def internal_targets_from_env() -> dict[str, Target]:
    return {
        name: Target(
            os.environ.get(f"TIME_LIBRARY_INTERNAL_{name.upper()}_HOST", DEFAULT_HOST),
            int(os.environ.get(f"TIME_LIBRARY_INTERNAL_{name.upper()}_PORT", default_port)),
        )
        for name, default_port in DEFAULT_INTERNAL_PORTS.items()
    }


def route_name(raw_path: str) -> str:
    path = urlparse(raw_path).path
    if path in {"/mcp", "/api/v1/raw/query", "/api/v1/memory-routing/status"}:
        return "raw"
    if path == "/recall":
        return "p3"
    if path in {"/inject", "/catalog", "/catalog-inject", "/catalog-card", "/ready"}:
        return "p4"
    if path.startswith("/reading-area/"):
        return "p4"
    if path in {"/entry", "/flags"} or path.startswith("/entry/"):
        return "dialog"
    return "p6"


def build_handler(targets: Mapping[str, Target], advertised_port: int):
    class SinglePortHandler(BaseHTTPRequestHandler):
        server_version = "TimeLibraryFrontDoor/1.0"

        def log_message(self, _format, *_args):
            return

        def _send_json(self, data: object, status: int = 200) -> None:
            payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def _health(self) -> None:
            self._send_json({
                "ok": True,
                "service": "time-library-front-door",
                "host": DEFAULT_HOST,
                "port": advertised_port,
                "discovery_file": str(port_file_path()),
                "user_visible_address_count": 1,
                "internal_services": sorted(targets),
            })

        def _proxy(self) -> None:
            target_name = route_name(self.path)
            target = targets[target_name]
            content_length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(content_length) if content_length else None
            headers = {
                name: value
                for name, value in self.headers.items()
                if name.lower() not in HOP_BY_HOP_HEADERS and name.lower() not in {"host", "content-length"}
            }
            headers["Host"] = f"{target.host}:{target.port}"
            headers["X-Time-Library-Front-Door"] = str(advertised_port)
            if body is not None:
                headers["Content-Length"] = str(len(body))
            connection = None
            try:
                deadline = time.monotonic() + INTERNAL_SERVICE_CONNECT_GRACE_SECONDS
                while True:
                    remaining = deadline - time.monotonic()
                    candidate = http.client.HTTPConnection(
                        target.host,
                        target.port,
                        timeout=min(
                            INTERNAL_SERVICE_CONNECT_ATTEMPT_TIMEOUT_SECONDS,
                            max(0.01, remaining),
                        ),
                    )
                    try:
                        candidate.connect()
                        if candidate.sock is not None:
                            candidate.sock.settimeout(INTERNAL_SERVICE_RESPONSE_TIMEOUT_SECONDS)
                        connection = candidate
                        break
                    except OSError:
                        candidate.close()
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise
                        time.sleep(min(INTERNAL_SERVICE_RETRY_INTERVAL_SECONDS, remaining))
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                payload = response.read()
                self.send_response(response.status, response.reason)
                for name, value in response.getheaders():
                    lowered = name.lower()
                    if lowered in HOP_BY_HOP_HEADERS or lowered == "content-length":
                        continue
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)
            except Exception as exc:
                self._send_json({
                    "ok": False,
                    "error": "internal_service_unavailable",
                    "service": target_name,
                    "detail": f"{type(exc).__name__}: {exc}",
                }, 502)
            finally:
                if connection is not None:
                    connection.close()

        def _dispatch(self) -> None:
            if urlparse(self.path).path == "/health":
                self._health()
                return
            self._proxy()

        do_GET = _dispatch
        do_POST = _dispatch
        do_PUT = _dispatch
        do_PATCH = _dispatch
        do_DELETE = _dispatch
        do_OPTIONS = _dispatch
        do_HEAD = _dispatch

    return SinglePortHandler


def create_server(
    *,
    host: str = DEFAULT_HOST,
    preferred_port: int = DEFAULT_FRONT_DOOR_PORT,
    max_attempts: int = 100,
    targets: Mapping[str, Target] | None = None,
) -> tuple[ThreadingHTTPServer, int]:
    selected_targets = dict(targets or internal_targets_from_env())
    for candidate in range(preferred_port, min(65535, preferred_port + max_attempts - 1) + 1):
        handler = build_handler(selected_targets, candidate)
        try:
            return ThreadingHTTPServer((host, candidate), handler), candidate
        except OSError as exc:
            if exc.errno not in {errno.EADDRINUSE, errno.EACCES}:
                raise
    raise RuntimeError(f"no available front-door port from {preferred_port} across {max_attempts} attempts")


def run(host: str = DEFAULT_HOST, preferred_port: int = DEFAULT_FRONT_DOOR_PORT, max_attempts: int = 100) -> None:
    lock = acquire_front_door_lock()
    server = None
    selected_port = None
    previous_handlers = {}

    def _stop(_signum, _frame):
        raise SystemExit(0)

    try:
        server, selected_port = create_server(host=host, preferred_port=preferred_port, max_attempts=max_attempts)
        discovery_path = write_port_atomic(selected_port)
        print(f"[time-library-front-door] running on http://{host}:{selected_port} discovery={discovery_path}", flush=True)
        if threading.current_thread() is threading.main_thread():
            for signal_name in ("SIGINT", "SIGTERM"):
                signal_number = getattr(signal, signal_name, None)
                if signal_number is not None:
                    previous_handlers[signal_number] = signal.getsignal(signal_number)
                    signal.signal(signal_number, _stop)
        server.serve_forever()
    finally:
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)
        if server is not None:
            server.server_close()
        if selected_port is not None:
            try:
                if port_file_path().read_text(encoding="ascii").strip() == str(selected_port):
                    port_file_path().unlink()
            except (FileNotFoundError, OSError, UnicodeError):
                pass
        lock.release()


def main() -> int:
    parser = argparse.ArgumentParser(description="Time Library single-port front door")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--preferred-port", type=int, default=DEFAULT_FRONT_DOOR_PORT)
    parser.add_argument("--max-attempts", type=int, default=100)
    args = parser.parse_args()
    run(args.host, args.preferred_port, args.max_attempts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
