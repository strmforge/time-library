"""HTTP calls from the client to the server.

The client always initiates. Requests go straight to the server's address and
deliberately ignore any system or environment proxy: a proxy on the computer
must never get to carry (or swallow) traffic meant for the local network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import CLIENT_VERSION

TIMEOUT_SECONDS = 20
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ServerUnreachable(Exception):
    """The server could not be reached; try again later, nothing was lost."""


class ServerRefused(Exception):
    """The server answered and said no."""

    def __init__(self, status: int, code: str, message: str = "") -> None:
        super().__init__(f"{status} {code}: {message}" if message else f"{status} {code}")
        self.status = status
        self.code = code
        self.message = message


class Api:
    def __init__(self, server_url: str, token: str | None = None, timeout: float = TIMEOUT_SECONDS) -> None:
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.last_heartbeat: dict[str, Any] = {}

    def _call(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"User-Agent": f"time-library-client/{CLIENT_VERSION}"}
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.server_url + path, data=data, method=method, headers=headers)
        try:
            with _DIRECT.open(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8"))
            except Exception:
                detail = {}
            raise ServerRefused(error.code, str(detail.get("error") or "http_error"), str(detail.get("message") or "")) from None
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise ServerUnreachable(str(error)) from None
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except ValueError:
            raise ServerUnreachable("server returned something that is not JSON") from None
        if not isinstance(parsed, dict):
            raise ServerUnreachable("server returned an unexpected response")
        return parsed

    def health(self) -> dict[str, Any]:
        return self._call("GET", "/api/v1/health")

    def pair(self, pairing_token: str, device: dict[str, str]) -> dict[str, Any]:
        return self._call("POST", "/api/v1/pair", {"pairing_token": pairing_token, "device": device})

    def report_agent(self, agent: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/api/v1/agents/report", {"agent": agent})

    def heartbeat(self, backlog: dict[str, int]) -> dict[str, Any]:
        reply = self._call("POST", "/api/v1/heartbeat", {"client_version": CLIENT_VERSION, "backlog": backlog})
        self.last_heartbeat = reply
        return reply

    def download(self, path: str) -> bytes:
        """Raw bytes of a file the server serves (the client package)."""
        request = urllib.request.Request(self.server_url + path, headers={"User-Agent": f"time-library-client/{CLIENT_VERSION}"})
        try:
            with _DIRECT.open(request, timeout=max(self.timeout, 60)) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise ServerRefused(error.code, "http_error") from None
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise ServerUnreachable(str(error)) from None

    def ingest(self, agent_id: int, segments: list[dict[str, Any]], origin: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"agent_id": agent_id, "segments": segments}
        if origin:
            body["origin"] = origin
        return self._call("POST", "/api/v1/ingest", body)

    def cursor(self, agent_id: int) -> dict[str, int]:
        return self._call("GET", f"/api/v1/ingest/cursor?agent_id={agent_id}")["cursor"]

    def recall(self, query: str, *, limit: int = 5, mode: str = "search", agent: str = "", folder: str = "") -> list[dict[str, Any]]:
        return self.recall_result(query, limit=limit, mode=mode, agent=agent, folder=folder)["memories"]

    def continue_here(self, agent: str = "", folder: str = "") -> dict[str, Any] | None:
        return self._call("POST", "/api/v1/continue", {"agent": agent, "folder": folder})["continue"]

    def recall_result(self, query: str, *, limit: int = 5, mode: str = "search", agent: str = "", folder: str = "",
                      only: dict[str, str] | None = None, session: str = "") -> dict[str, Any]:
        body = {"query": query, "limit": limit, "mode": mode, "agent": agent, "folder": folder, "only": only or {}, "session": session}
        return self._call("POST", "/api/v1/recall", body)

    def answer(self, question: str, agent: str = "", folder: str = "") -> dict[str, Any]:
        return self._call("POST", "/api/v1/answer", {"question": question, "agent": agent, "folder": folder})

    def search(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/api/v1/search", body)

    def around(self, segment: int) -> dict[str, Any]:
        return self._call("GET", f"/api/v1/segments/{int(segment)}/around")

    def missing(self, agent_id: int, asked: list[dict[str, str]]) -> list[str]:
        return self._call("POST", "/api/v1/ingest/check", {"agent_id": agent_id, "segments": asked})["missing"]

    def verified(self, agent_id: int, found: dict[str, int]) -> dict[str, Any]:
        return self._call("POST", "/api/v1/ingest/verified", {"agent_id": agent_id, "found": found})

    def declare(self, folder: str, project: str, series: str = "", agent: str = "") -> dict[str, Any]:
        return self._call("POST", "/api/v1/projects/declare", {"folder": folder, "project": project, "series": series, "agent": agent})

    def whiteboard_write(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/api/v1/whiteboard", body)

    def whiteboard_list(self, folder: str, task_id: str = "") -> dict[str, Any]:
        query = urllib.parse.urlencode({"folder": folder, "task_id": task_id})
        return self._call("GET", f"/api/v1/whiteboard?{query}")

    def catalog(self, folder: str, full: bool = False) -> dict[str, Any]:
        query = urllib.parse.urlencode({"folder": folder, "full": "1" if full else "0"})
        return self._call("GET", f"/api/v1/catalog?{query}")

    def report_sessions(self, agent_id: int, sessions: list[dict[str, str]]) -> dict[str, Any]:
        return self._call("POST", "/api/v1/sessions/report", {"agent_id": agent_id, "sessions": sessions})

    def report_levels(self, models: list[dict[str, Any]], agent: str = "") -> dict[str, Any]:
        return self._call("POST", "/api/v1/model-levels", {"models": models, "agent": agent})

    def give_back(self, returns: list[dict[str, Any]], agent: str = "") -> dict[str, Any]:
        return self._call("POST", "/api/v1/returns", {"returns": returns, "agent": agent})

    def memory_source(self, memory_id: int) -> dict[str, Any]:
        return self._call("GET", f"/api/v1/memories/{int(memory_id)}/source")
