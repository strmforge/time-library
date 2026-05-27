"""
openclaw_ws_rpc_client.py
P9-System-F R2+R3: OpenClaw WebSocket RPC Client
P9-System-G G1: timeout/retry/fallback/error classification hardening

Protocol:
- WebSocket URL: ws://127.0.0.1:18789/ws
- Auth: Bearer token (from openclaw.json) + Ed25519 device identity
- Methods:
  - sessions.list() -> list of sessions
  - sessions.send(key, message) -> runId
  - chat.send(sessionKey, message, idempotencyKey) -> runId
  - chat.inject(sessionKey, message, label) -> messageId
- Protocol: JSON-RPC over WebSocket
  - Send: {type:"req",id:"<uuid>",method:"<method>",params:{...}}
  - Receive: {type:"res",id:"<uuid>",ok:true/false,payload:{...}或error:{...}}
- Connection flow:
  1. HTTP Upgrade with Bearer token
  2. Receive connect.challenge (nonce)
  3. Send connect request with device identity + auth.token
  4. Receive hello-ok
"""

import json
import uuid
import socket
import base64
import os
import hashlib
import struct
import threading
import time
import select
from typing import Optional, Tuple
from config_loader import get_memcore_root

GATEWAY_HOST = "127.0.0.1"
GATEWAY_PORT = 18789
WS_PATH = "/ws"
GATEWAY_TOKEN = None

DEFAULT_CONNECT_TIMEOUT = 8.0
DEFAULT_REQUEST_TIMEOUT = 20.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.8
OPENCLAW_PROTOCOL_MIN = 4
OPENCLAW_PROTOCOL_MAX = 4
DEFAULT_OPERATOR_SCOPES = ["operator.read", "operator.write"]
ADMIN_OPERATOR_SCOPES = ["operator.admin", "operator.read", "operator.write"]

IDENTITY_PEM_PATH = os.path.join(get_memcore_root(), "config", "openclaw_device_identity.pem")
IDENTITY_JSON_PATH = os.path.join(get_memcore_root(), "config", "openclaw_device_identity.json")

ERROR_TIMEOUT = "TIMEOUT"
ERROR_NETWORK = "NETWORK_ERROR"
ERROR_HANDSHAKE = "HANDSHAKE_FAILED"
ERROR_AUTH = "AUTH_FAILED"
ERROR_PAIRING = "PAIRING_REQUIRED"
ERROR_PROTOCOL = "PROTOCOL_ERROR"
ERROR_NOT_CONNECTED = "NOT_CONNECTED"
ERROR_NO_RESPONSE = "NO_RESPONSE"
ERROR_UNKNOWN = "UNKNOWN_ERROR"

try:
    with open(os.path.expanduser("~/.openclaw/openclaw.json")) as f:
        GATEWAY_TOKEN = json.load(f).get("gateway", {}).get("auth", {}).get("token")
except Exception:
    pass


class WsFrame:
    OPCODE_TEXT = 0x1
    OPCODE_CLOSE = 0x8

    @staticmethod
    def build_text_frame(payload: str) -> bytes:
        payload_bytes = payload.encode("utf-8")
        length = len(payload_bytes)
        frame = bytearray()
        frame.append(0x81)
        if length <= 125:
            frame.append(0x80 | length)
        elif length <= 65535:
            frame.append(0x80 | 126)
            frame.extend(struct.pack(">H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack(">Q", length))
        mask = os.urandom(4)
        frame.extend(mask)
        masked = bytearray(payload_bytes)
        for i in range(len(masked)):
            masked[i] ^= mask[i % 4]
        frame.extend(masked)
        return bytes(frame)

    @staticmethod
    def parse_frame(data: bytes):
        if len(data) < 2:
            return None, None, data
        first = data[0]
        second = data[1]
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        offset = 2
        if length == 126:
            if len(data) < 4:
                return None, None, data
            length = struct.unpack(">H", data[2:4])[0]
            offset = 4
        elif length == 127:
            if len(data) < 10:
                return None, None, data
            length = struct.unpack(">Q", data[2:10])[0]
            offset = 10
        mask_bytes = b''
        if masked:
            if len(data) < offset + 4:
                return None, None, data
            mask_bytes = data[offset:offset+4]
            offset += 4
        if len(data) < offset + length:
            return None, None, data
        payload = data[offset:offset+length]
        if masked and mask_bytes:
            payload = bytearray(payload)
            for i in range(len(payload)):
                payload[i] ^= mask_bytes[i % 4]
        rest = data[offset+length:]
        return opcode, payload.decode("utf-8", errors="replace"), rest


def build_error(code: str, message: str, retryable: bool = False, detail: dict = None) -> dict:
    payload = {"code": code, "message": message, "retryable": retryable}
    if detail:
        payload["detail"] = detail
    return payload


def classify_error(message: str) -> Tuple[str, bool]:
    text = (message or "").lower()
    if "timed out" in text or "timeout" in text:
        return ERROR_TIMEOUT, True
    if "not_paired" in text or "pair" in text and "device" in text:
        return ERROR_PAIRING, False
    if "unauthorized" in text or "auth" in text or "signature_invalid" in text:
        return ERROR_AUTH, False
    if "101" in text or "handshake" in text or "upgrade" in text:
        return ERROR_HANDSHAKE, True
    if "broken pipe" in text or "connection reset" in text or "refused" in text or "network" in text:
        return ERROR_NETWORK, True
    return ERROR_UNKNOWN, False


def ws_handshake(sock: socket.socket, host: str, path: str, token: str) -> Tuple[bool, Optional[str]]:
    key_raw = os.urandom(16)
    key = base64.b64encode(key_raw).decode()
    req = f"GET {path} HTTP/1.1\r\n"
    req += f"Host: {host}\r\n"
    req += "Upgrade: websocket\r\n"
    req += "Connection: Upgrade\r\n"
    req += f"Sec-WebSocket-Key: {key}\r\n"
    req += "Sec-WebSocket-Version: 13\r\n"
    req += f"Authorization: Bearer {token}\r\n"
    req += "\r\n"
    sock.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            return False, "empty handshake response"
        resp += chunk
    resp_str = resp.decode("utf-8", errors="replace")
    if "HTTP/1.1 101" not in resp_str:
        return False, resp_str[:300]
    return True, None


class OpenClawWsRpcClient:
    def __init__(
        self,
        host: str = GATEWAY_HOST,
        port: int = GATEWAY_PORT,
        path: str = WS_PATH,
        token: str = None,
        client_id: str = "gateway-client",
        client_mode: str = "cli",
        platform: str = "linux",
        user_agent: str = "memcore-cloud-rpc/1.1",
        min_protocol: int = OPENCLAW_PROTOCOL_MIN,
        max_protocol: int = OPENCLAW_PROTOCOL_MAX,
        scopes: list = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ):
        self.host = host
        self.port = port
        self.path = path
        self.token = token or GATEWAY_TOKEN
        self.client_id = client_id
        self.client_mode = client_mode
        self.platform = platform
        self.user_agent = user_agent
        self.min_protocol = min_protocol
        self.max_protocol = max_protocol
        self.scopes = list(scopes or DEFAULT_OPERATOR_SCOPES)
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.sock: Optional[socket.socket] = None
        self.connected = False
        self.authenticated = False
        self._lock = threading.Lock()
        self._pending = {}
        self._buf = b""
        self._receiver_running = False
        self._receiver_thread: Optional[threading.Thread] = None
        self.last_error = None

    def identity_status(self) -> dict:
        return {
            "pem_exists": os.path.exists(IDENTITY_PEM_PATH),
            "json_exists": os.path.exists(IDENTITY_JSON_PATH),
            "pem_path": IDENTITY_PEM_PATH,
            "json_path": IDENTITY_JSON_PATH,
        }

    def connect(self, timeout: float = None) -> bool:
        timeout = timeout or self.connect_timeout
        if self.connected:
            return True
        if not self.token:
            self.last_error = build_error(ERROR_AUTH, "Gateway token missing", retryable=False)
            return False

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect((self.host, self.port))
            ok, handshake_error = ws_handshake(self.sock, f"{self.host}:{self.port}", self.path, self.token)
            if not ok:
                self.last_error = build_error(ERROR_HANDSHAKE, "WebSocket handshake failed", retryable=True, detail={"raw": handshake_error})
                self.close()
                return False
            self.connected = True

            nonce = self._wait_for_challenge(timeout=5)
            if nonce is None:
                self.last_error = build_error(ERROR_PROTOCOL, "connect.challenge not received", retryable=True)
                self.close()
                return False

            connect_ok, connect_error = self._send_connect(nonce, timeout=8)
            if not connect_ok:
                code, retryable = classify_error(connect_error or "connect failed")
                self.last_error = build_error(code, connect_error or "connect failed", retryable=retryable)
                self.close()
                return False

            self.authenticated = True
            self._start_receiver()
            return True
        except socket.timeout:
            self.last_error = build_error(ERROR_TIMEOUT, f"Connect timed out after {timeout}s", retryable=True)
            self.close()
            return False
        except Exception as e:
            code, retryable = classify_error(str(e))
            self.last_error = build_error(code, str(e), retryable=retryable)
            self.close()
            return False

    def _start_receiver(self):
        self._receiver_running = True
        self._receiver_thread = threading.Thread(target=self._receiver_loop, daemon=True)
        self._receiver_thread.start()

    def _receiver_loop(self):
        while self._receiver_running and self.connected and self.sock:
            try:
                r, _, _ = select.select([self.sock], [], [], 0.5)
                if not r:
                    continue
                data = self.sock.recv(8192)
                if not data:
                    break
                self._buf += data
                while True:
                    opcode, payload, self._buf = WsFrame.parse_frame(self._buf)
                    if opcode is None:
                        break
                    if opcode == WsFrame.OPCODE_TEXT and payload:
                        try:
                            resp = json.loads(payload)
                            msg_id = resp.get("id")
                            if msg_id:
                                with self._lock:
                                    cb = self._pending.get(msg_id)
                                if cb:
                                    cb(resp)
                                    with self._lock:
                                        self._pending.pop(msg_id, None)
                        except Exception:
                            pass
                    elif opcode == WsFrame.OPCODE_CLOSE:
                        self._receiver_running = False
                        break
            except Exception:
                break
        self._receiver_running = False

    def _recv_frame(self, timeout: float = 5.0) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                remaining = max(0.1, deadline - time.time())
                readable, _, _ = select.select([self.sock], [], [], min(remaining, 0.5))
                if not readable:
                    continue
                data = self.sock.recv(8192)
                if not data:
                    return None
                self._buf += data
                while True:
                    opcode, payload, self._buf = WsFrame.parse_frame(self._buf)
                    if opcode is None:
                        break
                    if opcode == WsFrame.OPCODE_TEXT:
                        return payload
                    if opcode == WsFrame.OPCODE_CLOSE:
                        return None
            except Exception:
                return None
        return None

    def _wait_for_challenge(self, timeout: float = 5.0) -> Optional[str]:
        while True:
            msg = self._recv_frame(timeout=timeout)
            if msg is None:
                return None
            try:
                data = json.loads(msg)
                if data.get("type") == "event" and data.get("event") == "connect.challenge":
                    return data.get("payload", {}).get("nonce")
            except Exception:
                pass

    def _build_device_identity(self, nonce: str) -> tuple:
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            from cryptography.hazmat.primitives import serialization

            priv_key = ed25519.Ed25519PrivateKey.generate()
            device_id = None
            pub_b64 = None
            if os.path.exists(IDENTITY_PEM_PATH) and os.path.exists(IDENTITY_JSON_PATH):
                try:
                    with open(IDENTITY_PEM_PATH, "rb") as f:
                        priv_key = serialization.load_pem_private_key(f.read(), password=None)
                    with open(IDENTITY_JSON_PATH) as f:
                        info = json.load(f)
                    device_id = info.get("device_id")
                    pub_b64 = info.get("public_key_b64")
                except Exception:
                    pass

            pub_key = priv_key.public_key()
            pub_raw = pub_key.public_bytes_raw()
            if not device_id:
                device_id = hashlib.sha256(pub_raw).hexdigest()
            if not pub_b64:
                pub_b64 = base64.urlsafe_b64encode(pub_raw).decode().rstrip("=")

            signed_at_ms = int(time.time() * 1000)
            scopes_str = ",".join(self.scopes)
            auth_payload = (
                f"v3|{device_id}|{self.client_id}|{self.client_mode}|operator|"
                f"{scopes_str}|{signed_at_ms}|{self.token}|{nonce}|{self.platform}|"
            )
            sig = priv_key.sign(auth_payload.encode("utf-8"))
            sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
            return device_id, pub_b64, sig_b64, signed_at_ms
        except ImportError:
            return None, None, None, None

    def _send_connect(self, nonce: str, timeout: float = 5.0) -> Tuple[bool, Optional[str]]:
        device_id, pub_b64, sig_b64, signed_at_ms = self._build_device_identity(nonce)
        scopes = list(self.scopes)

        connect_params = {
            "minProtocol": self.min_protocol,
            "maxProtocol": self.max_protocol,
            "client": {
                "id": self.client_id,
                "version": "1.0",
                "platform": self.platform,
                "mode": self.client_mode,
            },
            "role": "operator",
            "scopes": scopes,
            "auth": {"token": self.token},
            "locale": "zh-CN",
            "caps": ["tool-events"],
            "userAgent": self.user_agent,
        }
        if device_id and pub_b64 and sig_b64:
            connect_params["device"] = {
                "id": device_id,
                "publicKey": pub_b64,
                "signature": sig_b64,
                "signedAt": signed_at_ms,
                "nonce": nonce,
            }

        msg_id = str(uuid.uuid4())
        request = {"type": "req", "id": msg_id, "method": "connect", "params": connect_params}
        self.sock.sendall(WsFrame.build_text_frame(json.dumps(request)))

        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self._recv_frame(timeout=1)
            if msg is None:
                return False, "no connect response"
            try:
                data = json.loads(msg)
                if data.get("type") == "event" and data.get("event") == "connect.hello":
                    return True, None
                if data.get("id") == msg_id:
                    if not data.get("ok"):
                        err = data.get("error") or {}
                        return False, err.get("message") or json.dumps(err, ensure_ascii=False)
                    return True, None
            except Exception:
                pass
        return False, "connect response timeout"

    def _send_raw(self, data: dict):
        self.sock.sendall(WsFrame.build_text_frame(json.dumps(data)))

    def _request_once(self, method: str, params: dict, timeout: float) -> dict:
        if not self.connected or not self.sock:
            return {"ok": False, "error": build_error(ERROR_NOT_CONNECTED, "WebSocket not connected", retryable=True)}

        msg_id = str(uuid.uuid4())
        request = {"type": "req", "id": msg_id, "method": method, "params": params}
        event = threading.Event()
        result_container = [None]

        def on_response(resp_data):
            result_container[0] = resp_data
            event.set()

        with self._lock:
            self._pending[msg_id] = on_response

        try:
            self._send_raw(request)
            if not event.wait(timeout=timeout):
                return {"ok": False, "error": build_error(ERROR_TIMEOUT, f"Request {method} timed out after {timeout}s", retryable=True)}
            return result_container[0] or {"ok": False, "error": build_error(ERROR_NO_RESPONSE, "No response received", retryable=True)}
        except socket.timeout:
            return {"ok": False, "error": build_error(ERROR_TIMEOUT, f"Socket timeout during {method}", retryable=True)}
        except Exception as e:
            code, retryable = classify_error(str(e))
            return {"ok": False, "error": build_error(code, str(e), retryable=retryable)}
        finally:
            with self._lock:
                self._pending.pop(msg_id, None)

    def request(self, method: str, params: dict, timeout: float = None, retryable: bool = True) -> dict:
        timeout = timeout or self.request_timeout
        attempts = max(1, self.max_retries + 1)
        last_result = None

        for attempt in range(1, attempts + 1):
            if not self.connected:
                if not self.connect(timeout=self.connect_timeout):
                    last_result = {"ok": False, "error": self.last_error or build_error(ERROR_NOT_CONNECTED, "connect failed", retryable=True), "attempt": attempt}
                else:
                    last_result = None

            if self.connected:
                last_result = self._request_once(method, params, timeout=timeout)
                if last_result.get("ok"):
                    last_result["attempt"] = attempt
                    return last_result

            error = (last_result or {}).get("error", {})
            can_retry = retryable and error.get("retryable", False) and attempt < attempts
            if not can_retry:
                if last_result is None:
                    return {"ok": False, "error": build_error(ERROR_UNKNOWN, f"Request {method} failed", retryable=False), "attempt": attempt}
                last_result["attempt"] = attempt
                return last_result

            self.close()
            time.sleep(self.retry_backoff_seconds * attempt)

        return last_result or {"ok": False, "error": build_error(ERROR_UNKNOWN, f"Request {method} failed", retryable=False), "attempt": attempts}

    def sessions_list(self, timeout: float = 10.0) -> dict:
        return self.request("sessions.list", {}, timeout=timeout)

    def chat_send(self, session_key: str, message: str, idempotency_key: str = None, timeout: float = 30.0) -> dict:
        params = {
            "sessionKey": session_key,
            "message": message,
            "idempotencyKey": idempotency_key or str(uuid.uuid4()),
        }
        return self.request("chat.send", params, timeout=timeout)

    def chat_inject(self, session_key: str, message: str, label: str = None, timeout: float = 10.0) -> dict:
        params = {
            "sessionKey": session_key,
            "message": message,
        }
        if label:
            params["label"] = label
        return self.request("chat.inject", params, timeout=timeout, retryable=False)

    def chat_abort(self, session_key: str, run_id: str = None, timeout: float = 5.0) -> dict:
        params = {
            "sessionKey": session_key,
        }
        if run_id:
            params["runId"] = run_id
        return self.request("chat.abort", params, timeout=timeout, retryable=False)

    def chat_history(self, session_key: str, limit: int = 20, max_chars: int = 1000, timeout: float = 10.0) -> dict:
        params = {
            "sessionKey": session_key,
            "limit": limit,
            "maxChars": max_chars,
        }
        return self.request("chat.history", params, timeout=timeout)

    def sessions_send(self, session_key: str, message: str, timeout: float = 30.0) -> dict:
        params = {"key": session_key, "message": message}
        return self.request("sessions.send", params, timeout=timeout)

    def close(self):
        self._receiver_running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.connected = False
        self.authenticated = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
