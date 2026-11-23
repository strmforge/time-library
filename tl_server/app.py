"""HTTP front of the Time Library server.

Standard library only, like the rest of Time Library. Clients always call the
server; the server never calls a client. Every API route except /health and the
sign-in routes needs a credential: a device token for client routes; the admin
token or a signed-in browser session for admin routes.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from . import API_VERSION, SERVER_VERSION
from . import client_package
from .distill import Distiller
from .evolution import Evolution
from .vectors import Vectors
from .whiteboard import Whiteboard
from .answer import Answerer
from .continuity import Continuity
from .runtimes import RUNTIMES, Runtimes
from .doctor import Doctor
from .projects import Projects
from .ledger import Ledger
from .errors import ApiError
from .local_model import LocalModel
from .model_registry import ModelRegistry
from .recall import Recall
from .store import SESSION_TTL_SECONDS, Store
from .update import Updater
from .words import WordIndex

MAX_BODY_BYTES = 8 * 1024 * 1024
SESSION_COOKIE = "tl_session"
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_FAILURES = 5
WEB_DIR = Path(__file__).parent / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
    # The official Time Library marks (assets/brand, sized for the page): the logo in each language, and the emblem.
    "/assets/logo-zh.png": ("brand/logo-zh.png", "image/png"),
    "/assets/logo-en.png": ("brand/logo-en.png", "image/png"),
    "/favicon.png": ("brand/favicon.png", "image/png"),
    "/apple-touch-icon.png": ("brand/icon-180.png", "image/png"),
}
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
log = logging.getLogger("tl_server")



BUNDLE_PATH = re.compile(r"/client/bundle/([a-z0-9_-]{3,30})\.tar\.gz")
GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)  # the caller went away

def _health(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return {"ok": True, "server_id": handler.store.server_id, "api": API_VERSION, "version": SERVER_VERSION}


def _update_status(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    updater = handler.server.updater  # type: ignore[attr-defined]
    return updater.check(force=False) if handler.query.get("look", [""])[0] == "1" else updater.status()


def _update_check(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.updater.check()  # type: ignore[attr-defined]


def _update_start(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.updater.start()  # type: ignore[attr-defined]


def _update_back(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.updater.go_back()  # type: ignore[attr-defined]


def _pair(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.store.pair(body.get("pairing_token"), body.get("device"))


def _agents_report(handler: "Handler", _match, body, who) -> dict[str, Any]:
    return handler.store.report_agent(who["device_id"], body.get("agent"))


def _heartbeat(handler: "Handler", _match, body, who) -> dict[str, Any]:
    handler.store.heartbeat(who["device_id"], body.get("client_version"), body.get("backlog"))
    reply: dict[str, Any] = {"ok": True}
    if client_package.available():
        # Clients installed from this server's package follow the version it hands out.
        reply["client"] = {"version": client_package.client_version(), "package": f"/client/{client_package.PACKAGE_NAME}"}
    return reply


def _ingest(handler: "Handler", _match, body, who) -> dict[str, Any]:
    return handler.store.ingest(who["device_id"], body.get("agent_id"), body.get("segments"), body.get("origin"))


def _cursor(handler: "Handler", _match, _body, who) -> dict[str, Any]:
    raw = handler.query.get("agent_id", [""])[0]
    if not raw.isdigit():
        raise ApiError(400, "invalid_field", "agent_id query parameter is required")
    return {"cursor": handler.store.cursor(who["device_id"], int(raw))}


def _session_state(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return {
        "setup_needed": not handler.store.admin_password_is_set(),
        "signed_in": handler.store.verify_admin_session(handler.session_token()),
    }


def _session_setup(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    handler.store.set_admin_password(body.get("password"))
    handler.start_session()
    return {"ok": True}


def _session_login(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    limiter = handler.server.login_limiter  # type: ignore[attr-defined]
    address = handler.client_address[0]
    if limiter.blocked(address):
        raise ApiError(429, "too_many_attempts", "wait a few minutes and try again")
    if not handler.store.check_admin_password(body.get("password")):
        limiter.failed(address)
        raise ApiError(401, "wrong_password")
    limiter.cleared(address)
    handler.start_session()
    return {"ok": True}


def _session_password(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    """Change the password, signed in, with the old one."""
    limiter = handler.server.login_limiter  # type: ignore[attr-defined]
    address = handler.client_address[0]
    if limiter.blocked(address):
        raise ApiError(429, "too_many_attempts", "wait a few minutes and try again")
    if not handler.store.check_admin_password(body.get("old")):
        limiter.failed(address)
        raise ApiError(401, "wrong_password")
    handler.store.replace_admin_password(body.get("password"))
    limiter.cleared(address)
    handler.start_session()  # this browser stays in; every other one signs in again
    return {"ok": True}


def _session_reset(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    """Forgot the password: whoever can read the server key in the server's data folder sets a new one."""
    limiter = handler.server.login_limiter  # type: ignore[attr-defined]
    address = handler.client_address[0]
    if limiter.blocked(address):
        raise ApiError(429, "too_many_attempts", "wait a few minutes and try again")
    token = body.get("token")
    if not isinstance(token, str) or not handler.store.verify_admin(token.strip()):
        limiter.failed(address)
        raise ApiError(401, "wrong_server_key")
    handler.store.replace_admin_password(body.get("password"))
    limiter.cleared(address)
    handler.start_session()
    return {"ok": True}


def _session_logout(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    handler.store.delete_admin_session(handler.session_token())
    handler.extra_headers.append(("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"))
    return {"ok": True}


def _admin_overview(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    raw = handler.query.get("since", ["0"])[0]
    try:
        since = float(raw)
    except ValueError:
        raise ApiError(400, "invalid_field", "since must be a timestamp") from None
    return handler.store.overview(since)


def _admin_pairing(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.store.create_pairing_token()


def _admin_devices(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return {"devices": handler.store.list_devices(), "now": time.time()}


def _admin_revoke(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    handler.store.revoke_device(int(match.group(1)))
    return {"ok": True}


def _admin_disconnect(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    handler.store.disconnect_agent(int(match.group(1)))
    return {"ok": True}


def _models_listing(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.models.listing()


def _models_create(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.models.create_source(body)


def _models_update(handler: "Handler", match, body, _who) -> dict[str, Any]:
    return handler.models.update_source(int(match.group(1)), body)


def _models_delete(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    handler.models.delete_source(int(match.group(1)))
    return {"ok": True}


def _models_fetch(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    return handler.models.fetch_models(int(match.group(1)))


def _models_test(handler: "Handler", match, body, _who) -> dict[str, Any]:
    return handler.models.test_source(int(match.group(1)), body.get("model"))


def _models_key(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    return {"api_key": handler.models.key(int(match.group(1)))}


def _models_slot(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.models.set_slot(body.get("slot"), body.get("role"), body.get("source_id"), body.get("model"))


def _recall(handler: "Handler", _match, body, who) -> dict[str, Any]:
    mode = body.get("mode") if body.get("mode") in ("search", "preflight") else "search"
    if mode == "preflight":
        pack = handler.server.continuity.for_prompt(  # type: ignore[attr-defined]
            body.get("query"), device_id=who["device_id"], agent=body.get("agent"), folder=body.get("folder"), session=body.get("session"))
        if pack is not None:
            handler.server.recall.note_use(who["device_id"], body.get("agent"), mode, True)  # type: ignore[attr-defined]
            return {"memories": [], "mode": mode, "delivery_id": "", "continue": pack}
    return handler.server.recall.recall(  # type: ignore[attr-defined]
        body.get("query"), limit=body.get("limit", 5), mode=mode, device_id=who["device_id"], agent=body.get("agent"),
        folder=body.get("folder"), only=body.get("only") if isinstance(body.get("only"), dict) else None,
    )


def _answer(handler: "Handler", _match, body, who) -> dict[str, Any]:
    return handler.server.answerer.answer(  # type: ignore[attr-defined]
        body.get("question"), device_id=who["device_id"], agent=body.get("agent"), folder=body.get("folder")
    )


def _admin_answer(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.server.answerer.answer(body.get("question"), lend=False)  # type: ignore[attr-defined]


def _search(handler: "Handler", _match, body, who) -> dict[str, Any]:
    agent = body.get("asking") if isinstance(body.get("asking"), str) else ""
    found = handler.server.words.search(  # type: ignore[attr-defined]
        body.get("query"), limit=body.get("limit", 8), who=body.get("who"), agent=body.get("agent"), computer=body.get("computer"),
        project=body.get("project"), since=body.get("since"), until=body.get("until"), asking=(who["device_id"], agent),
        folder=body.get("folder"),
    )
    handler.server.recall.note_use(who["device_id"], agent, "words", bool(found["hits"]))  # type: ignore[attr-defined]
    return found


def _admin_search(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    first = lambda name: handler.query.get(name, [""])[0]  # noqa: E731
    return handler.server.words.search(  # type: ignore[attr-defined]
        first("query"), limit=int(first("limit")) if first("limit").isdigit() else 20, who=first("who"), agent=first("agent"),
        computer=first("computer"), project=first("project"), since=first("since"), until=first("until"),
    )


def _continue(handler: "Handler", _match, body, who) -> dict[str, Any]:
    agent = body.get("agent") if isinstance(body.get("agent"), str) else ""
    pack = handler.server.continuity.pack(device_id=who["device_id"], agent=agent, folder=body.get("folder"))  # type: ignore[attr-defined]
    handler.server.recall.note_use(who["device_id"], agent, "continue", pack is not None)  # type: ignore[attr-defined]
    return {"continue": pack}


def _sent(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    first = lambda name: handler.query.get(name, [""])[0]  # noqa: E731
    number = lambda name: float(first(name)) if first(name).replace(".", "", 1).isdigit() else 0.0  # noqa: E731
    return handler.server.ledger.listing(  # type: ignore[attr-defined]
        before=int(number("before")), task=first("task"), scope=first("scope"), today=number("since"))


def _sent_one(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    return handler.server.ledger.one(int(match.group(1)))  # type: ignore[attr-defined]


def _notes(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.continuity.listing()  # type: ignore[attr-defined]


def _notes_switch(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.server.continuity.switch(bool(body.get("enabled")))  # type: ignore[attr-defined]


def _note_delete(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    return handler.server.continuity.delete(int(match.group(1)))  # type: ignore[attr-defined]


def _around(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    return handler.server.words.around(int(match.group(1)))  # type: ignore[attr-defined]


def _declare(handler: "Handler", _match, body, who) -> dict[str, Any]:
    return handler.server.projects.declare(  # type: ignore[attr-defined]
        who["device_id"], body.get("agent"), body.get("folder"), body.get("project"), body.get("series")
    )


def _catalog(handler: "Handler", _match, _body, who) -> dict[str, Any]:
    first = lambda name, default="": handler.query.get(name, [default])[0]  # noqa: E731
    handler.server.recall.flush()  # type: ignore[attr-defined]
    return handler.server.projects.catalog(  # type: ignore[attr-defined]
        who["device_id"], first("folder"), full=first("full") in ("1", "true")
    )


def _sessions_report(handler: "Handler", _match, body, who) -> dict[str, Any]:
    return handler.store.report_sessions(who["device_id"], body.get("agent_id"), body.get("sessions"))


def _admin_projects(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    projects = handler.server.projects  # type: ignore[attr-defined]
    return {"projects": projects.listing(), **projects.pages()}


def _project_assign(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.server.projects.assign(  # type: ignore[attr-defined]
        body.get("device_id"), body.get("folder"), body.get("project"), body.get("series"))


def _whiteboard_write(handler: "Handler", _match, body, who) -> dict[str, Any]:
    return handler.server.whiteboard.write(who["device_id"], body)  # type: ignore[attr-defined]


def _whiteboard_list(handler: "Handler", _match, _body, who) -> dict[str, Any]:
    board = handler.server.whiteboard  # type: ignore[attr-defined]
    first = lambda name, default="": handler.query.get(name, [default])[0]  # noqa: E731
    task = first("task_id")
    if task:
        match = board_task_id(task)
        return {"task": board.task(match)}
    owner = board.project_of(who["device_id"], first("folder"))
    if owner is None:
        return {"project": None, "tasks": [], "hint": "这个文件夹还没声明属于哪个项目;用 time_library_declare 声明后,白板挂在项目上。"}
    return {"project": {"name": owner[0], "series": owner[1]}, "tasks": board.tasks(owner[0])}


def board_task_id(text: str) -> int:
    from .whiteboard import TASK_ID

    match = TASK_ID.match(text.strip())
    if not match:
        raise ApiError(400, "invalid_field", "task_id 写成白板上显示的编号,如 WB-12")
    return int(match.group(1))


def _admin_whiteboard(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    first = lambda name, default="": handler.query.get(name, [default])[0]  # noqa: E731
    return {"tasks": handler.server.whiteboard.tasks(first("project"))}  # type: ignore[attr-defined]


def _model_levels(handler: "Handler", _match, body, who) -> dict[str, Any]:
    return handler.models.report_levels(body.get("models"), body.get("agent"), who["name"])


def _return(handler: "Handler", _match, body, who) -> dict[str, Any]:
    return handler.server.recall.give_back(  # type: ignore[attr-defined]
        body.get("returns"), device_id=who["device_id"], agent=body.get("agent")
    )


def _memory_source(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    return handler.server.recall.source(int(match.group(1)))  # type: ignore[attr-defined]


def _local_status(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.local_model.status()  # type: ignore[attr-defined]


def _local_enable(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.server.local_model.enable(body.get("model_id"))  # type: ignore[attr-defined]


def _local_cancel(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.local_model.cancel()  # type: ignore[attr-defined]


def _local_remove(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.local_model.remove()  # type: ignore[attr-defined]


def _slot_effort(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.models.set_effort(body.get("slot"), body.get("effort", ""))


def _distill_status(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.distiller.status()


def _distill_run(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    limit = body.get("max_windows")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000):
        raise ApiError(400, "invalid_field", "max_windows must be a positive integer")
    job = body.get("job") or "daily"
    if job == "import" and "scope" in body:
        handler.distiller.set_import_scope(body["scope"])  # the range this round works through
    return handler.distiller.start("manual", limit, job=job)


def _import_scope_set(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return {"scope": handler.distiller.set_import_scope(body.get("scope"))}


def _import_scope_preview(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.distiller.preview_import_scope(body.get("scope"))


def _distill_pause(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    job = body.get("job")
    if job not in (None, "daily", "import"):
        raise ApiError(400, "invalid_field", "job must be daily or import")
    return handler.distiller.pause(job=job)


def _memories_list(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    handler.server.recall.flush()  # type: ignore[attr-defined]  # show loans up to this moment
    first = lambda name, default="": handler.query.get(name, [default])[0]  # noqa: E731
    limit = first("limit", "100")
    return handler.distiller.list_memories(first("query"), first("status"), int(limit) if limit.isdigit() else 100, first("shelf"), first("project"))


def _memory_detail(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    handler.server.recall.flush()  # type: ignore[attr-defined]
    return handler.distiller.memory(int(match.group(1)))


def _memory_expire(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    handler.distiller.set_status(int(match.group(1)), "expired", "manual")
    return {"ok": True}


def _memory_restore(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    handler.distiller.set_status(int(match.group(1)), "active")
    return {"ok": True}


def _memory_purge(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    handler.distiller.purge(int(match.group(1)))
    return {"ok": True}


def _evolution_status(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.evolution.status()  # type: ignore[attr-defined]


def _evolution_run(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    limits = {}
    for name in ("pairs", "groups"):
        value = body.get(name)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
                raise ApiError(400, "invalid_field", f"{name} must be a whole number from 0 to 10000")
            limits[name] = value
    return handler.server.evolution.start("manual", **limits)  # type: ignore[attr-defined]


def _evolution_pause(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.evolution.pause()  # type: ignore[attr-defined]


def _vectors_status(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.vectors.status()  # type: ignore[attr-defined]


def _vectors_enable(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.server.vectors.enable(body.get("model"))  # type: ignore[attr-defined]


def _vectors_disable(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.vectors.disable()  # type: ignore[attr-defined]


def _doctor_status(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.doctor.status()  # type: ignore[attr-defined]


def _doctor_run(handler: "Handler", _match, _body, _who) -> dict[str, Any]:
    return handler.server.doctor.start_checkup("manual")  # type: ignore[attr-defined]


def _doctor_compare(handler: "Handler", _match, body, _who) -> dict[str, Any]:
    return handler.server.doctor.start_compare(body.get("questions", 40))  # type: ignore[attr-defined]


def _link_undo(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    handler.server.evolution.undo(int(match.group(1)))  # type: ignore[attr-defined]
    return {"ok": True}


def _memory_unfold(handler: "Handler", match, _body, _who) -> dict[str, Any]:
    handler.distiller.unfold(int(match.group(1)))
    return {"ok": True}


Route = tuple[str, "re.Pattern[str]", str | None, Callable[..., dict[str, Any]]]

ROUTES: list[Route] = [
    ("GET", re.compile(r"/api/v1/health"), None, _health),
    ("POST", re.compile(r"/api/v1/pair"), None, _pair),
    ("POST", re.compile(r"/api/v1/agents/report"), "device", _agents_report),
    ("POST", re.compile(r"/api/v1/heartbeat"), "device", _heartbeat),
    ("POST", re.compile(r"/api/v1/ingest"), "device", _ingest),
    ("GET", re.compile(r"/api/v1/ingest/cursor"), "device", _cursor),
    ("POST", re.compile(r"/api/v1/recall"), "device", _recall),
    ("POST", re.compile(r"/api/v1/answer"), "device", _answer),
    ("POST", re.compile(r"/api/v1/search"), "device", _search),
    ("POST", re.compile(r"/api/v1/continue"), "device", _continue),
    ("GET", re.compile(r"/api/v1/admin/sent"), "admin", _sent),
    ("GET", re.compile(r"/api/v1/admin/sent/(\d+)"), "admin", _sent_one),
    ("GET", re.compile(r"/api/v1/admin/notes"), "admin", _notes),
    ("POST", re.compile(r"/api/v1/admin/notes/switch"), "admin", _notes_switch),
    ("POST", re.compile(r"/api/v1/admin/notes/(\d+)/delete"), "admin", _note_delete),
    ("GET", re.compile(r"/api/v1/segments/(\d+)/around"), "device", _around),
    ("GET", re.compile(r"/api/v1/admin/search"), "admin", _admin_search),
    ("GET", re.compile(r"/api/v1/admin/segments/(\d+)/around"), "admin", _around),
    ("POST", re.compile(r"/api/v1/admin/answer"), "admin", _admin_answer),
    ("GET", re.compile(r"/api/v1/memories/(\d+)/source"), "device", _memory_source),
    ("POST", re.compile(r"/api/v1/returns"), "device", _return),
    ("POST", re.compile(r"/api/v1/projects/declare"), "device", _declare),
    ("POST", re.compile(r"/api/v1/model-levels"), "device", _model_levels),
    ("GET", re.compile(r"/api/v1/catalog"), "device", _catalog),
    ("POST", re.compile(r"/api/v1/whiteboard"), "device", _whiteboard_write),
    ("GET", re.compile(r"/api/v1/whiteboard"), "device", _whiteboard_list),
    ("GET", re.compile(r"/api/v1/admin/whiteboard"), "admin", _admin_whiteboard),
    ("POST", re.compile(r"/api/v1/sessions/report"), "device", _sessions_report),
    ("GET", re.compile(r"/api/v1/admin/projects"), "admin", _admin_projects),
    ("POST", re.compile(r"/api/v1/admin/projects/assign"), "admin", _project_assign),
    ("GET", re.compile(r"/api/v1/admin/session"), None, _session_state),
    ("POST", re.compile(r"/api/v1/admin/session/setup"), "browser", _session_setup),
    ("POST", re.compile(r"/api/v1/admin/session/login"), "browser", _session_login),
    ("POST", re.compile(r"/api/v1/admin/session/logout"), "browser", _session_logout),
    ("POST", re.compile(r"/api/v1/admin/session/password"), "admin", _session_password),
    ("POST", re.compile(r"/api/v1/admin/session/reset"), "browser", _session_reset),
    ("GET", re.compile(r"/api/v1/admin/overview"), "admin", _admin_overview),
    ("POST", re.compile(r"/api/v1/admin/pairing-tokens"), "admin", _admin_pairing),
    ("GET", re.compile(r"/api/v1/admin/devices"), "admin", _admin_devices),
    ("POST", re.compile(r"/api/v1/admin/devices/(\d+)/revoke"), "admin", _admin_revoke),
    ("POST", re.compile(r"/api/v1/admin/agents/(\d+)/disconnect"), "admin", _admin_disconnect),
    ("GET", re.compile(r"/api/v1/admin/models"), "admin", _models_listing),
    ("POST", re.compile(r"/api/v1/admin/models/sources"), "admin", _models_create),
    ("POST", re.compile(r"/api/v1/admin/models/sources/(\d+)"), "admin", _models_update),
    ("POST", re.compile(r"/api/v1/admin/models/sources/(\d+)/delete"), "admin", _models_delete),
    ("POST", re.compile(r"/api/v1/admin/models/sources/(\d+)/models"), "admin", _models_fetch),
    ("POST", re.compile(r"/api/v1/admin/models/sources/(\d+)/test"), "admin", _models_test),
    ("GET", re.compile(r"/api/v1/admin/models/sources/(\d+)/key"), "admin", _models_key),
    ("POST", re.compile(r"/api/v1/admin/models/slots"), "admin", _models_slot),
    ("GET", re.compile(r"/api/v1/admin/local-model"), "admin", _local_status),
    ("POST", re.compile(r"/api/v1/admin/local-model/enable"), "admin", _local_enable),
    ("POST", re.compile(r"/api/v1/admin/local-model/cancel"), "admin", _local_cancel),
    ("POST", re.compile(r"/api/v1/admin/local-model/remove"), "admin", _local_remove),
    ("GET", re.compile(r"/api/v1/admin/distill"), "admin", _distill_status),
    ("POST", re.compile(r"/api/v1/admin/models/slots/effort"), "admin", _slot_effort),
    ("POST", re.compile(r"/api/v1/admin/distill/run"), "admin", _distill_run),
    ("POST", re.compile(r"/api/v1/admin/distill/pause"), "admin", _distill_pause),
    ("POST", re.compile(r"/api/v1/admin/distill/import-scope"), "admin", _import_scope_set),
    ("POST", re.compile(r"/api/v1/admin/distill/import-scope/preview"), "admin", _import_scope_preview),
    ("GET", re.compile(r"/api/v1/admin/update"), "admin", _update_status),
    ("POST", re.compile(r"/api/v1/admin/update/check"), "admin", _update_check),
    ("POST", re.compile(r"/api/v1/admin/update/start"), "admin", _update_start),
    ("POST", re.compile(r"/api/v1/admin/update/back"), "admin", _update_back),
    ("GET", re.compile(r"/api/v1/admin/memories"), "admin", _memories_list),
    ("GET", re.compile(r"/api/v1/admin/memories/(\d+)"), "admin", _memory_detail),
    ("POST", re.compile(r"/api/v1/admin/memories/(\d+)/expire"), "admin", _memory_expire),
    ("POST", re.compile(r"/api/v1/admin/memories/(\d+)/restore"), "admin", _memory_restore),
    ("POST", re.compile(r"/api/v1/admin/memories/(\d+)/purge"), "admin", _memory_purge),
    ("POST", re.compile(r"/api/v1/admin/memories/(\d+)/unfold"), "admin", _memory_unfold),
    ("POST", re.compile(r"/api/v1/admin/links/(\d+)/undo"), "admin", _link_undo),
    ("GET", re.compile(r"/api/v1/admin/evolution"), "admin", _evolution_status),
    ("GET", re.compile(r"/api/v1/admin/vectors"), "admin", _vectors_status),
    ("GET", re.compile(r"/api/v1/admin/doctor"), "admin", _doctor_status),
    ("POST", re.compile(r"/api/v1/admin/doctor/run"), "admin", _doctor_run),
    ("POST", re.compile(r"/api/v1/admin/doctor/compare"), "admin", _doctor_compare),
    ("POST", re.compile(r"/api/v1/admin/vectors/enable"), "admin", _vectors_enable),
    ("POST", re.compile(r"/api/v1/admin/vectors/disable"), "admin", _vectors_disable),
    ("POST", re.compile(r"/api/v1/admin/evolution/run"), "admin", _evolution_run),
    ("POST", re.compile(r"/api/v1/admin/evolution/pause"), "admin", _evolution_pause),
]


class LoginLimiter:
    """Slow down password guessing: a few failures per address, then a pause."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def _recent(self, address: str) -> list[float]:
        cutoff = time.monotonic() - LOGIN_WINDOW_SECONDS
        recent = [stamp for stamp in self._failures.get(address, []) if stamp >= cutoff]
        if recent:
            self._failures[address] = recent
        else:
            self._failures.pop(address, None)
        return recent

    def blocked(self, address: str) -> bool:
        with self._lock:
            return len(self._recent(address)) >= LOGIN_MAX_FAILURES

    def failed(self, address: str) -> None:
        with self._lock:
            self._recent(address)
            self._failures.setdefault(address, []).append(time.monotonic())

    def cleared(self, address: str) -> None:
        with self._lock:
            self._failures.pop(address, None)


class Handler(BaseHTTPRequestHandler):
    server_version = "TimeLibraryServer"
    protocol_version = "HTTP/1.1"
    query: dict[str, list[str]] = {}
    extra_headers: list[tuple[str, str]] = []

    @property
    def store(self) -> Store:
        return self.server.store  # type: ignore[attr-defined]

    @property
    def models(self) -> ModelRegistry:
        return self.server.models  # type: ignore[attr-defined]

    @property
    def distiller(self) -> Distiller:
        return self.server.distiller  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        # Request line and status only: never bodies, never tokens.
        log.info("%s %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    # ---- credentials -----------------------------------------------------

    def _bearer(self) -> str | None:
        header = self.headers.get("Authorization", "")
        scheme, _, value = header.partition(" ")
        return value.strip() if scheme.lower() == "bearer" and value.strip() else None

    def session_token(self) -> str | None:
        header = self.headers.get("Cookie")
        if not header:
            return None
        try:
            morsel = SimpleCookie(header).get(SESSION_COOKIE)
        except Exception:
            return None
        return morsel.value if morsel else None

    def start_session(self) -> None:
        token = self.store.create_admin_session()
        self.extra_headers.append(
            (
                "Set-Cookie",
                f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL_SECONDS}",
            )
        )

    def _same_origin(self) -> bool:
        """A browser form or script on another site must not drive this server."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlsplit(origin).netloc == self.headers.get("Host", "")

    def _authenticate(self, kind: str | None, method: str) -> dict[str, Any] | None:
        if kind is None:
            return None
        if kind == "browser":
            if not self._same_origin():
                raise ApiError(403, "cross_site_request")
            return None
        if kind == "admin":
            if self.store.verify_admin(self._bearer()):
                return {"admin": True}
            if self.store.verify_admin_session(self.session_token()):
                if method != "GET" and not self._same_origin():
                    raise ApiError(403, "cross_site_request")
                return {"admin": True}
            raise ApiError(401, "admin_sign_in_required")
        device = self.store.device_for_token(self._bearer())
        if device is None:
            raise ApiError(401, "device_token_invalid")
        return device

    # ---- request / response ----------------------------------------------

    def _read_body(self) -> dict[str, Any]:
        length_header = self.headers.get("Content-Length")
        if length_header is None or not length_header.isdigit():
            self.close_connection = True
            raise ApiError(411, "length_required")
        length = int(length_header)
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            raise ApiError(413, "body_too_large", f"at most {MAX_BODY_BYTES} bytes")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "invalid_json") from None
        if not isinstance(body, dict):
            raise ApiError(400, "invalid_json", "body must be a JSON object")
        return body

    def _serve_bundle(self, path: str) -> bool:
        """The client with its own Python for one kind of computer: no sign-in, nothing secret in it."""
        match = BUNDLE_PATH.fullmatch(path)
        if not match:
            return False
        platform = match.group(1)
        if platform not in RUNTIMES or not client_package.available():
            self._send(404, {"error": "not_found", "message": "kinds of computer: " + ", ".join(RUNTIMES)})
            return True
        bundle = self.server.runtimes.bundle(platform)  # type: ignore[attr-defined]
        if bundle is None:
            self._send(503, {"error": "python_unavailable",
                             "message": "this server could not fetch Python for that computer; install with a Python already on it"})
            return True
        self.send_response(200)
        self.send_header("Content-Type", "application/gzip")
        self.send_header("Content-Length", str(bundle.stat().st_size))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Disposition", f'attachment; filename="{bundle.name}"')
        self.end_headers()
        with bundle.open("rb") as handle:
            while True:
                chunk = handle.read(1 << 20)
                if not chunk:
                    break
                self.wfile.write(chunk)
        return True

    def _serve_client(self, path: str) -> bool:
        """The client install package and its guide: no sign-in, nothing secret in them."""
        if self._serve_bundle(path):
            return True
        if path not in ("/client/install.md", f"/client/{client_package.PACKAGE_NAME}"):
            return False
        if not client_package.available():
            return False
        if path.endswith(".md"):
            host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_address[1]}"
            data = client_package.install_guide(f"http://{host}").encode("utf-8")
            content_type = "text/markdown; charset=utf-8"
        else:
            data = client_package.package()
            content_type = "application/zip"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if content_type == "application/zip":
            self.send_header("Content-Disposition", f'attachment; filename="{client_package.PACKAGE_NAME}"')
        self.end_headers()
        self.wfile.write(data)
        return True

    def _serve_static(self, path: str) -> bool:
        if self._serve_client(path):
            return True
        entry = STATIC_FILES.get(path)
        if entry is None:
            return False
        name, content_type = entry
        try:
            data = (WEB_DIR / name).read_bytes()
        except OSError:
            return False
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)
        return True

    def handle(self) -> None:
        try:
            super().handle()
        except GONE:
            self.close_connection = True  # hung up mid-answer (a timed-out health check, a closed tab): not an error

    def _dispatch(self, method: str) -> None:
        parts = urlsplit(self.path)
        self.query = parse_qs(parts.query)
        self.extra_headers = []
        if method == "GET" and self._serve_static(parts.path):
            return
        body_pending = method == "POST"
        try:
            path_known = False
            for route_method, pattern, auth, func in ROUTES:
                match = pattern.fullmatch(parts.path)
                if not match:
                    continue
                path_known = True
                if route_method != method:
                    continue
                # Authenticate before reading the body, so an unauthenticated
                # caller cannot make the server parse megabytes of JSON.
                who = self._authenticate(auth, method)
                body = self._read_body() if method == "POST" else {}
                body_pending = False
                self._send(200, func(self, match, body, who))
                return
            if path_known:
                raise ApiError(405, "method_not_allowed")
            raise ApiError(404, "not_found")
        except ApiError as error:
            if body_pending:
                # The request body was never read; do not reuse the connection.
                self.close_connection = True
            self._send(error.status, {"error": error.code, "message": error.message})
        except GONE:
            self.close_connection = True  # the caller hung up before the answer was sent: nothing went wrong here
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self.close_connection = True
            self._send(500, {"error": "internal_error", "message": "internal error"})

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in self.extra_headers:
            self.send_header(name, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)


def create_server(data_dir: str, host: str, port: int) -> ThreadingHTTPServer:
    store = Store(data_dir)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.store = store  # type: ignore[attr-defined]
    httpd.models = ModelRegistry(store)  # type: ignore[attr-defined]
    httpd.ledger = httpd.models.ledger = Ledger(data_dir)  # type: ignore[attr-defined]
    httpd.local_model = LocalModel(store, httpd.models)  # type: ignore[attr-defined]
    httpd.distiller = Distiller(store, httpd.models)  # type: ignore[attr-defined]
    httpd.projects = Projects(store)  # type: ignore[attr-defined]
    httpd.recall = Recall(store)  # type: ignore[attr-defined]  (after Distiller: it extends the memories table)
    httpd.recall.warm()  # type: ignore[attr-defined]
    httpd.evolution = Evolution(store, httpd.distiller)  # type: ignore[attr-defined]
    httpd.vectors = Vectors(store)  # type: ignore[attr-defined]
    httpd.whiteboard = Whiteboard(store)  # type: ignore[attr-defined]
    httpd.projects.whiteboard = httpd.whiteboard  # type: ignore[attr-defined]
    httpd.doctor = Doctor(store, httpd.distiller, httpd.recall, httpd.vectors, httpd.whiteboard)  # type: ignore[attr-defined]
    httpd.answerer = Answerer(httpd.recall, httpd.distiller)  # type: ignore[attr-defined]
    httpd.runtimes = Runtimes(Path(data_dir))  # type: ignore[attr-defined]
    httpd.recall.vectors = httpd.vectors  # type: ignore[attr-defined]
    httpd.recall.projects = httpd.projects  # type: ignore[attr-defined]
    httpd.continuity = Continuity(store, httpd.projects, httpd.distiller, httpd.whiteboard)  # type: ignore[attr-defined]
    httpd.projects.continuity = httpd.continuity  # type: ignore[attr-defined]
    httpd.words = WordIndex(store, data_dir, httpd.projects)  # type: ignore[attr-defined]
    httpd.login_limiter = LoginLimiter()  # type: ignore[attr-defined]
    httpd.restart_requested = threading.Event()  # type: ignore[attr-defined]
    httpd.updater = Updater(Path(data_dir), lambda: _restart_soon(httpd))  # type: ignore[attr-defined]
    return httpd


def _restart_soon(httpd: ThreadingHTTPServer) -> None:
    """Stop serving once the answer to this request is out; the process then ends with the launcher's restart code."""
    httpd.restart_requested.set()  # type: ignore[attr-defined]

    def stop() -> None:
        time.sleep(1)
        httpd.shutdown()

    threading.Thread(target=stop, daemon=True, name="restart").start()
