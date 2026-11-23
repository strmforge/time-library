"""A stand-in model endpoint that speaks Responses, Messages and chat/completions.

Good key: test-key-123. "broke-key" is out of balance. "missing-model" does not exist.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GOOD_KEY = "test-key-123"
MODELS = ["alpha-large", "alpha-mini", "embed-small"]


class FakeModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:
        pass

    def _send(self, status: int, payload) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _key(self) -> str:
        if self.headers.get("x-api-key"):
            return self.headers["x-api-key"]
        return self.headers.get("Authorization", "").removeprefix("Bearer ").strip()

    def _guard(self) -> bool:
        key = self._key()
        if key == "broke-key":
            self._send(402, {"error": {"code": "insufficient_quota", "message": "余额不足"}})
            return False
        if key != GOOD_KEY:
            self._send(401, {"error": {"message": "invalid api key"}})
            return False
        return True

    def do_GET(self) -> None:
        self.server.seen.append(("GET", self.path, dict(self.headers)))
        if not self._guard():
            return
        path, _, query = self.path.partition("?")
        if path != "/v1/models":
            self._send(404, {"error": {"message": "not found"}})
            return
        if self.headers.get("x-api-key"):  # Messages-style listing is paged; Anthropic reports capabilities
            if "after_id=alpha-mini" in query:
                self._send(200, {"data": [{"id": "embed-small"}], "has_more": False, "last_id": "embed-small"})
            else:
                effort = {"supported": True, "low": {"supported": True}, "medium": {"supported": False}, "max": {"supported": True}}
                self._send(200, {"data": [{"id": "alpha-large"}, {"id": "alpha-mini", "capabilities": {"effort": effort}}],
                                 "has_more": True, "last_id": "alpha-mini"})
            return
        listed = [{"id": name} for name in MODELS]
        # The shape of a Codex-style model catalog: levels plus a default.
        listed[0].update({"supported_reasoning_levels": [{"effort": "low", "description": "fast"}, {"effort": "xhigh"}],
                          "default_reasoning_level": "low"})
        self._send(200, {"object": "list", "data": listed})

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.raw.append(raw)  # exactly what arrived
        body = json.loads(raw or b"{}")
        self.server.seen.append(("POST", self.path, dict(self.headers), body))
        if self.server.gate is not None:
            self.server.gate.wait(10)  # a test holds the call in flight until it opens the gate
        if self.path == "/weird/v1/responses":
            self._send(200, {"hello": 1})
            return
        if self.server.fail_next > 0:
            self.server.fail_next -= 1
            self._send(503, {"error": {"message": "upstream busy"}})
            return
        if not self._guard():
            return
        if body.get("model") == "missing-model":
            self._send(404, {"error": {"message": "model not found"}})
            return
        # Scripted replies are used first, in order; then the default reply.
        reply = self.server.replies.pop(0) if self.server.replies else self.server.reply_text
        chosen = (body.get("reasoning") or {}).get("effort") or (body.get("output_config") or {}).get("effort") or body.get("reasoning_effort")
        if chosen in self.server.bad_efforts:
            self._send(400, {"error": {"message": f"Unsupported value: {chosen}"}})
            return
        if body.get("stream") and self.server.refuse_stream:
            self._send(400, {"error": {"message": "stream is not supported"}})
            return
        if body.get("stream") and not self.server.ignore_stream and self.path in ("/v1/responses", "/v1/messages", "/v1/chat/completions"):
            self._send_stream(reply, body)
            return
        if self.path == "/v1/responses":
            self._send(200, {"output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": reply}]}],
                             "usage": {"input_tokens": 7, "output_tokens": 2}})
        elif self.path == "/v1/messages":
            if not self.headers.get("anthropic-version"):
                self._send(400, {"error": {"message": "anthropic-version header required"}})
                return
            self._send(200, {"content": [{"type": "text", "text": reply}], "usage": {"input_tokens": 7, "output_tokens": 2}})
        elif self.path == "/v1/chat/completions":
            self._send(200, {"choices": [{"message": {"role": "assistant", "content": reply}}],
                             "usage": {"prompt_tokens": 7, "completion_tokens": 2}})
        else:
            self._send(404, {"error": {"message": "not found"}})


    def _send_stream(self, reply: str, body) -> None:
        pieces = [reply[i : i + 5] for i in range(0, len(reply), 5)] or [""]
        events = []
        if reply == "STREAM_ERROR" and self.path == "/v1/responses":
            # The relay's upstream breaks off in the middle of an answer.
            events = [("response.created", {"type": "response.created"}),
                      ("response.output_text.delta", {"type": "response.output_text.delta", "delta": "{\"mem"}),
                      ("error", {"type": "error", "code": "upstream_http2_stream_error", "message": "Upstream HTTP/2 stream failed"})]
            lines = [f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n" for name, data in events]
        elif self.path == "/v1/responses":
            events += [("response.created", {"type": "response.created"})]
            events += [("response.output_text.delta", {"type": "response.output_text.delta", "delta": piece}) for piece in pieces]
            events += [("response.completed", {"type": "response.completed", "response": {"usage": {"input_tokens": 7, "output_tokens": 2}}})]
            lines = [f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n" for name, data in events]
        elif self.path == "/v1/messages":
            events.append({"type": "message_start", "message": {"usage": {"input_tokens": 7, "output_tokens": 1}}})
            if body.get("thinking"):
                events.append({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "THOUGHTS"}})
            events += [{"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": piece}} for piece in pieces]
            events += [{"type": "message_delta", "usage": {"output_tokens": 2}}, {"type": "message_stop"}]
            lines = [f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n" for event in events]
        else:
            lines = [f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]}, ensure_ascii=False)}\n" for piece in pieces]
            lines.append(f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 7, 'completion_tokens': 2}})}\n")
            lines.append("data: [DONE]\n")
        data = "\n".join(lines).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start_fake_model_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
    httpd.daemon_threads = True
    httpd.seen = []
    httpd.raw = []
    httpd.reply_text = "OK"
    httpd.replies = []
    httpd.fail_next = 0
    httpd.gate = None
    httpd.ignore_stream = False  # answer a stream request with one JSON reply
    httpd.bad_efforts = {"bogus"}  # thinking levels this endpoint refuses
    httpd.refuse_stream = False  # refuse a stream request with 400
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    httpd.base_url = f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    return httpd
