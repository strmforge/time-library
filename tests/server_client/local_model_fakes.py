"""Stand-ins for the model runtime binary and for the model download host."""

from __future__ import annotations

import os
import socket
import stat
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STUB_RUNTIME = '''#!{python}
"""A stand-in for llama-server: same flags, answers health, models and one protocol."""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

args = sys.argv[1:]
value = lambda flag: args[args.index(flag) + 1]
Path(__file__).with_name("argv.json").write_text(json.dumps(args))

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _send(self, payload):
        data = json.dumps(payload).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path == "/health": self._send({{"status": "ok"}})
        else: self._send({{"data": [{{"id": value("--alias")}}]}})
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self._send({{"output": [{{"type": "message", "content": [{{"type": "output_text", "text": "OK"}}]}}]}})

ThreadingHTTPServer((value("--host"), int(value("--port"))), Handler).serve_forever()
'''


def write_stub_runtime(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "llama-server"
    binary.write_text(STUB_RUNTIME.format(python=sys.executable), encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


class DownloadHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:
        payload = self.server.payload
        header = self.headers.get("Range")
        self.server.ranges.append(header)
        start = int(header.split("=")[1].rstrip("-")) if header else 0
        body = payload[start:]
        self.send_response(206 if header else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            for index in range(0, len(body), 20_000):
                self.wfile.write(body[index : index + 20_000])
                self.wfile.flush()
                if self.server.slow:
                    time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError):
            pass


def start_download_host(payload: bytes, slow: bool = False):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), DownloadHandler)
    httpd.daemon_threads = True
    httpd.payload, httpd.slow, httpd.ranges = payload, slow, []
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    return httpd


def wait_until(check, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


__all__ = ["write_stub_runtime", "free_port", "port_open", "start_download_host", "wait_until", "os"]
