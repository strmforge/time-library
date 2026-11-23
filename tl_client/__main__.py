"""Time Library client command line.

  python -m tl_client pair --server http://<nas-address>:9850 --token tlp_...
  python -m tl_client report-agent --name "Claude Code" --sessions ~/.claude/projects \
      --format message_envelope_content_blocks --capability mcp=true
  python -m tl_client sync          # read and upload once
  python -m tl_client run           # keep doing so
  python -m tl_client status

The agent itself runs report-agent: what it is, where its sessions are and what
it supports are its own report, not something this client looks up by product.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any
from pathlib import Path

from . import CLIENT_VERSION
from .api import Api, ServerRefused, ServerUnreachable
from .formats import BUILTIN_FORMATS, spec_from_report
from .state import State, default_device_name, machine_uid, os_label
from .sync import DEFAULT_GLOB, sync_all


def _api(state: State) -> Api:
    if not state.paired:
        raise SystemExit("not paired yet: run `pair --server URL --token TOKEN` first")
    return Api(state.config["server_url"], state.config["device_token"])


def cmd_pair(state: State, args: argparse.Namespace) -> int:
    if not args.server:
        from .discover import find_servers, home_networks

        found = find_servers(home_networks())
        if len(found) != 1:
            listing = "".join(f"\n  {item['url']}  (server {item['server_id'][:8]})" for item in found)
            raise SystemExit(
                ("no Time Library server found on this network; give its address with --server" if not found
                 else "more than one Time Library server on this network; choose one with --server:" + listing)
            )
        args.server = found[0]["url"]
        print(f"found the server at {args.server}")
    api = Api(args.server)
    device_uid = state.config.get("device_uid") or machine_uid()
    name = args.name or state.config.get("device_name") or default_device_name()
    paired = api.pair(
        args.token,
        {"device_uid": device_uid, "name": name, "os": os_label(), "client_version": CLIENT_VERSION},
    )
    if state.config.get("server_id") not in (None, paired["server_id"]):
        # A different server: agent ids and read positions belong to the old one.
        state.config["agents"] = {}
        state.progress.clear()
        state.save_progress()
    state.config.update(
        server_url=args.server.rstrip("/"),
        server_id=paired["server_id"],
        device_id=paired["device_id"],
        device_uid=device_uid,
        device_name=name,
        device_token=paired["device_token"],
    )
    state.save_config()
    print(f"paired: this computer is '{name}' on server {paired['server_id'][:8]}")
    return 0


def _json_arg(value: str, option: str) -> Any:
    """A JSON option's value: the JSON itself, or @<file> holding it (easier than quoting on Windows)."""
    text = value
    if value.startswith("@"):
        try:
            text = Path(value[1:]).expanduser().read_text(encoding="utf-8-sig")
        except OSError as error:
            raise SystemExit(f"{option}: could not read {value[1:]}: {error}") from None
    try:
        return json.loads(text)
    except ValueError as error:
        raise SystemExit(f"{option} is not valid JSON: {error}") from None


def _capabilities(pairs: list[str]) -> dict[str, bool]:
    capabilities = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator or value.lower() not in ("true", "false"):
            raise SystemExit(f"--capability expects name=true or name=false, got: {pair}")
        capabilities[key.strip()] = value.lower() == "true"
    return capabilities


def cmd_report_agent(state: State, args: argparse.Namespace) -> int:
    api = _api(state)
    known = state.config["agents"].get(args.name, {})
    if not args.sessions and not known:
        raise SystemExit("--sessions is needed the first time an agent reports itself")
    # Reporting again: whatever is left out stays as it was (say only what changed).
    if args.format_json:
        reported_format = _json_arg(args.format_json, "--format-json")
    else:
        reported_format = args.format or known.get("format") or "flat_role_content"
    try:
        spec = spec_from_report(reported_format)
    except ValueError as error:
        raise SystemExit(f"session format not usable: {error}") from None
    sessions_root = str(Path(args.sessions).expanduser()) if args.sessions else known["sessions_root"]
    glob = args.glob or known.get("glob") or DEFAULT_GLOB
    since = None
    if args.since:
        from datetime import datetime, timezone

        from .formats import parse_time

        moment = datetime.now(timezone.utc) if args.since == "now" else parse_time(args.since)
        if moment is None:
            raise SystemExit("--since takes a time like 2026-11-23T10:00:00+08:00, or now")
        since = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hook = None
    if args.hook_json:
        from .recall import check_hook

        try:
            hook = check_hook(_json_arg(args.hook_json, "--hook-json"))
        except ValueError as error:
            raise SystemExit(f"hook description not usable: {error}") from None
    report = {"name": args.name, "sessions_location": sessions_root, "session_format": spec.name}
    if args.capability or not known:
        report["capabilities"] = _capabilities(args.capability)
    reply = api.report_agent(report)
    existing = state.config["agents"].get(reply["name"], {})
    state.config["agents"][reply["name"]] = {
        **existing,
        "agent_id": reply["agent_id"],
        "sessions_root": sessions_root,
        "glob": glob,
        "format": reported_format,
        "paused": False,
    }
    if since:
        state.config["agents"][reply["name"]]["since"] = since
    if hook is not None:
        state.config["agents"][reply["name"]]["hook"] = hook
    if args.model_catalog:
        state.config["agents"][reply["name"]]["model_catalog"] = str(Path(args.model_catalog).expanduser())
        state.config["agents"][reply["name"]].pop("model_catalog_mtime", None)
    state.save_config()
    started = f", from {since}" if since else ""
    print(f"agent '{reply['name']}' is connected (sessions: {sessions_root}, format: {spec.name}{started})")
    return 0


def _print_results(results) -> None:
    for result in results:
        line = f"{result.agent}: {result.accepted} new, {result.duplicates} already stored, {result.files_read} files read"
        if result.paused:
            line += " [paused]"
        print(line)
        for note in result.notes:
            print(f"  - {note}")


def cmd_sync(state: State, _args: argparse.Namespace) -> int:
    _print_results(sync_all(_api(state), state))
    return 0


UPDATED_EXIT = 75  # a worker that installed a newer client exits with this to be started again


def _supervise(args: argparse.Namespace) -> int:
    """The process a service manager keeps running. It does no work itself: it runs
    the worker and starts it again (with the code now on disk) when the worker
    updated the client, or after a pause when it stopped for any other reason.
    Restarting in place instead would end the whole service on Windows, where
    Task Scheduler stops a task whose first process exits."""
    import subprocess

    command = [sys.executable, "-m", "tl_client"]
    if args.home:
        command += ["--home", args.home]
    command += ["run", "--worker", "--interval", str(args.interval)]
    if args.log:
        command += ["--log", args.log]
    while True:
        try:
            code = subprocess.run(command, check=False).returncode
        except KeyboardInterrupt:
            return 0
        except OSError:
            code = 1
        if code != UPDATED_EXIT:
            time.sleep(30)


def cmd_run(state: State, args: argparse.Namespace) -> int:
    _api(state)  # refuse to start unpaired
    if not args.worker:
        return _supervise(args)
    if args.log:
        # Background starters without a console (pythonw on Windows) have no
        # stdout at all: write what the loop reports to a file instead.
        log = open(Path(args.log).expanduser(), "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = _Stamped(log)
    refresh_skills(state)  # a worker starts after every update: skills follow the client
    was_down = False
    down_since: float | None = None
    last_search: float | None = None
    revoked_notice = False
    while True:
        # Read the state afresh every round: an agent reporting itself, or a new
        # pairing, happens in another process and must not be overwritten here.
        state = State(state.home)
        api = Api(state.config["server_url"], state.config["device_token"])
        try:
            results = sync_all(api, state)
            revoked_notice = False
            down_since = None
            if was_down:
                print("server is reachable again; resumed from the last read position")
                was_down = False
            if any(result.accepted or result.notes for result in results):
                _print_results(results)
            _maybe_update(api)
            _maybe_verify(api, state)
        except ServerUnreachable as error:
            if not was_down:
                print(f"server not reachable ({error}); will keep trying, nothing is lost")
            was_down = True
            now = time.monotonic()
            down_since = down_since or now
            if now - down_since >= REDISCOVER_AFTER and (last_search is None or now - last_search >= REDISCOVER_EVERY):
                last_search = now
                moved = _find_server_again(state)
                if moved:
                    print(f"the server moved to {moved}; carrying on there")
                    down_since = None
        except ServerRefused as refusal:
            if refusal.status == 401:
                # Revoked. Stay quiet and keep waiting: pairing again brings it back.
                if not revoked_notice:
                    print("the server no longer accepts this computer's token (revoked); waiting to be paired again")
                revoked_notice = True
            else:
                print(f"server refused: {refusal}")
        if sys.stdout is not None:
            sys.stdout.flush()
        time.sleep(args.interval)


VERIFY_EVERY = 3600.0
_last_verify: float | None = None


def _maybe_verify(api: Api, state: State) -> None:
    """Now and then, a little: whether anything in the session files never reached the server."""
    global _last_verify
    now = time.monotonic()
    if _last_verify is None:
        _last_verify = now - VERIFY_EVERY + 300  # not while a computer is still starting up
    if now - _last_verify < VERIFY_EVERY:
        return
    _last_verify = now
    from .verify import verify_round

    for name, found in verify_round(api, state).items():
        if found["missing"]:
            print(f"verify {name}: {found['missing']} turns were not on the server; {found['repaired']} sent now"
                  + (f", {found['held_back']} held back (tl.py verify --repair sends them)" if found["held_back"] else ""))


def cmd_verify(state: State, args: argparse.Namespace) -> int:
    from .verify import verify_round

    api = _api(state)
    results = verify_round(api, state, only=args.agent or "", everything=True, repair=args.repair)
    if not results:
        print("no agent to look at" + (f" named {args.agent}" if args.agent else ""))
        return 1
    short = 0
    for name, found in results.items():
        print(f"{name}: {found['read']} of {found['files']} files read, {found['segments']} turns compared, "
              f"{found['missing']} were not on the server, {found['repaired']} sent now"
              + (f", {found['held_back']} held back (--repair sends them)" if found["held_back"] else "")
              + (f", {found['gone']} files are gone here (what they held is kept on the server)" if found["gone"] else ""))
        for note in found.get("notes", []):
            print("  " + note)
        short += found["held_back"]
    return 1 if short else 0


REDISCOVER_AFTER = 300.0  # unreachable this long (longer than a restart): look for the server on the home network
REDISCOVER_EVERY = 600.0  # and at most this often


def _find_server_again(state: State) -> str:
    """The server got a new address: find it (same server id, token accepted there) and remember it."""
    from .discover import find_again

    old_url = state.config.get("server_url", "")
    try:
        new_url = find_again(old_url, state.config.get("server_id", ""))
    except Exception:  # noqa: BLE001 - looking is best effort; the loop carries on regardless
        return ""
    if not new_url:
        return ""
    try:
        Api(new_url, state.config["device_token"]).heartbeat({})
    except (ServerUnreachable, ServerRefused):
        return ""  # the same server id but it won't take this computer's token: leave it
    fresh = State(state.home)  # another process may have changed the config meanwhile
    if fresh.config.get("server_url") != old_url:
        return ""
    fresh.config["server_url"] = new_url
    fresh.save_config()
    return new_url


def cmd_check(state: State, args: argparse.Namespace) -> int:
    """Try a session format (and a hook description) on this computer's own files; nothing is sent."""
    from .check import check, check_hook, describe
    from .recall import check_hook as valid_hook

    known = (state.config.get("agents") or {}).get(args.agent or "", {}) if args.agent else {}
    if args.agent and not known:
        raise SystemExit(f"no agent called {args.agent!r} has reported itself on this computer")
    sessions = args.sessions or known.get("sessions_root")
    if not sessions:
        raise SystemExit("give --sessions (and --format or --format-json), or --agent for one already reported")
    if args.format_json:
        reported_format = _json_arg(args.format_json, "--format-json")
    else:
        reported_format = args.format or known.get("format") or "flat_role_content"
    try:
        spec = spec_from_report(reported_format)
    except ValueError as error:
        raise SystemExit(f"session format not usable: {error}") from None
    found = check(Path(sessions).expanduser(), args.glob or known.get("glob") or DEFAULT_GLOB, spec)
    report: dict[str, Any] = {"sessions": found, "hook": None}
    hook = known.get("hook")
    if args.hook_json:
        try:
            hook = valid_hook(_json_arg(args.hook_json, "--hook-json"))
        except ValueError as error:
            raise SystemExit(f"hook description not usable: {error}") from None
    if args.hook_sample:
        sample = args.hook_sample
        if sample.startswith("@"):
            sample = Path(sample[1:]).expanduser().read_text(encoding="utf-8-sig")
        report["hook"] = check_hook(hook or {}, spec, sample)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1, default=lambda value: dict(value)))
    else:
        print(describe(found))
        if report["hook"]:
            print("")
            print(f"hook: would look up: {report['hook']['prompt'] or '(nothing: the prompt was not found)'}")
            print(f"hook: would print: {report['hook']['prints']}")
            print(f"hook: when nothing is found: {report['hook']['prints_when_none']}")
    return 1 if found["warnings"] or (report["hook"] is not None and not report["hook"]["prompt"]) else 0


def cmd_runtime(state: State, args: argparse.Namespace) -> int:
    """Move this computer onto the client's own Python (see runtime.py)."""
    from . import runtime

    if args.action == "where":
        print(runtime.bundled_python() if runtime.bundled_python().exists() else "not installed: the client runs on " + sys.executable)
        return 0
    if runtime.running_bundled():
        print(f"already running on the client's own Python ({sys.executable})")
        return 0
    if not state.paired:
        raise SystemExit("pair this computer first: the Python comes from the server")
    try:
        interpreter = runtime.install(state.config["server_url"])
    except (OSError, RuntimeError) as error:
        raise SystemExit(f"the client's own Python was not installed: {error}") from None
    print(f"installed: {interpreter}")
    launcher = runtime.client_root() / "tl.py"
    args_home = ["--home", str(state.home)]
    done = subprocess.run([str(interpreter), str(launcher), *args_home, "service", "install"], capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"installed, but the background service was not moved onto it: {done.stderr.strip()[-300:]}")
    print(done.stdout.strip())
    print(f"the background service now runs on it. Agents' commands may name it too: {interpreter} {launcher} ...")
    return 0


def cmd_discover(state: State, _args: argparse.Namespace) -> int:
    from .discover import find_servers, home_networks

    url = state.config.get("server_url", "")
    networks = home_networks(url)
    print("looking in " + ", ".join(str(network) for network in networks) + " …")
    found = find_servers(networks, server_id=state.config.get("server_id", ""))
    if not found:
        print("no Time Library server answered on this network")
        return 1
    for item in found:
        mine = " (this computer's server)" if item["server_id"] == state.config.get("server_id") else ""
        here = " - current address" if item["url"] == url.rstrip("/") else ""
        print(f"{item['url']}  server {item['server_id'][:8]}{mine}{here}")
    return 0


# When this process last tried to update. None until the first try: monotonic
# time starts near zero on some systems (macOS), so "an hour since 0" would hold
# back the first update for the first hour of every worker.
_last_update_try: float | None = None


def _maybe_update(api: Api) -> None:
    """Follow the client version the server hands out; on success start again with it."""
    global _last_update_try
    from .update import update_if_needed

    advertised = (api.last_heartbeat.get("client") or {}).get("version")
    if not advertised or advertised == CLIENT_VERSION:
        return
    if _last_update_try is not None and time.monotonic() - _last_update_try < 3600:
        return
    _last_update_try = time.monotonic()
    try:
        if not update_if_needed(api, advertised):
            return
    except Exception as error:  # noqa: BLE001 - keep uploading with this version; try again later
        print(f"could not update the client to {advertised}: {error}")
        return
    print(f"client updated {CLIENT_VERSION} -> {advertised}; starting again")
    if sys.stdout is not None:
        sys.stdout.flush()
    raise SystemExit(UPDATED_EXIT)  # the supervising process starts the new code


def cmd_status(state: State, _args: argparse.Namespace) -> int:
    if not state.paired:
        print("not paired")
        return 0
    print(f"computer: {state.config.get('device_name')}  server: {state.config.get('server_url')}")
    print(f"log: {state.home / 'client.log'}  python: {sys.executable}")
    for name, agent in sorted(state.config.get("agents", {}).items()):
        files = len(state.progress.get(name, {}))
        paused = " [paused]" if agent.get("paused") else ""
        print(f"agent: {name}{paused}  sessions: {agent.get('sessions_root')}  files tracked: {files}")
    return 0


def cmd_import(state: State, args: argparse.Namespace) -> int:
    from .history import import_history

    from .history import IMPORT_TIMEOUT_SECONDS

    reported_format = json.loads(args.format_json) if args.format_json else args.format
    api = None
    if not args.dry_run:
        _api(state)  # refuse to start unpaired
        api = Api(state.config["server_url"], state.config["device_token"], timeout=IMPORT_TIMEOUT_SECONDS)
    result = import_history(api, state, args.agent, args.folder, args.glob or DEFAULT_GLOB, reported_format, dry_run=args.dry_run,
                            folders_only=args.folders_only)
    verb = "would send" if args.dry_run else "sent"
    print(
        f"{result.agent}: {result.files} files ({result.files_read} with something new), "
        f"{verb} {result.segments} dialogue pieces, {result.chars} characters"
        + ("" if args.dry_run else f"; {result.accepted} new on the server, {result.duplicates} already there"
           f"; working folders known for {result.folders} sessions")
    )
    for note in result.notes:
        print(f"  - {note}")
    return 0


def skill_source() -> Path | None:
    """The skill that ships in the install package (one copy, in system/skills)."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "agent_skill", here.parent / "system" / "skills" / "time-library"):
        if (candidate / "SKILL.md").is_file():
            return candidate
    return None


def cmd_skill(state: State, args: argparse.Namespace) -> int:
    """Put the Time Library skill into a skills folder the agent says it reads."""
    source = skill_source()
    if source is None:
        raise SystemExit("the Time Library skill is not in this client package")
    target = Path(args.into).expanduser() / "time-library"
    _write_skill(state, source, target)
    # Remember where it went: when the client updates itself, the skill there is updated too.
    folders = state.config.setdefault("skills", [])
    if str(target) not in folders:
        folders.append(str(target))
        state.save_config()
    return 0


def _write_skill(state: State, source: Path, target: Path) -> None:
    import shutil

    if target.exists():
        backup = state.home / "skill-backups" / time.strftime("%Y%m%d-%H%M%S") / str(target).strip("/\\").replace(":", "").replace("\\", "_").replace("/", "_")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(backup))
        print(f"previous skill kept at {backup}")
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    print(f"skill written to {target}")


def refresh_skills(state: State) -> list[str]:
    """After an update: the skill copies this client put into agents' folders, brought up to date.
    A copy the agent has since removed stays removed."""
    source = skill_source()
    if source is None:
        return []
    fresh = (source / "SKILL.md").read_bytes()
    updated = []
    for folder in state.config.get("skills", []):
        target = Path(folder)
        try:
            if not (target / "SKILL.md").is_file() or (target / "SKILL.md").read_bytes() == fresh:
                continue
            _write_skill(state, source, target)
            updated.append(folder)
        except OSError as error:
            print(f"could not update the skill at {folder}: {error}")
    return updated


class _Stamped:
    """A log file whose every line starts with the time it was written."""

    def __init__(self, out) -> None:
        self.out = out
        self.fresh = True

    def write(self, text: str) -> int:
        for piece in text.splitlines(keepends=True):
            if self.fresh:
                self.out.write(time.strftime("%Y-%m-%d %H:%M:%S "))
            self.out.write(piece)
            self.fresh = piece.endswith("\n")
        return len(text)

    def flush(self) -> None:
        self.out.flush()


def cmd_service(state: State, args: argparse.Namespace) -> int:
    from . import service

    if args.action == "install":
        _api(state)  # only a paired client is worth keeping running
        print(service.install(state.home))
    else:
        print(service.uninstall())
    return 0


def cmd_old_install(state: State, args: argparse.Namespace) -> int:
    from . import old_install

    if args.action == "scan":
        launcher = f'"{sys.executable}" "{Path(sys.argv[0]).resolve()}"' if sys.argv and sys.argv[0].endswith("tl.py") else "PY TL/tl.py"
        report = old_install.scan(launcher)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if not report["installs"] and not report["services"]:
            print("no earlier Time Library install on this computer")
            return 0
        for install in report["installs"]:
            print(f"earlier install: {install['folder']}")
            for item in install["history"]:
                print(f"  history: {item['computer']} / {item['source']}: {item['files']} files, "
                      f"{item['bytes'] / 1e9:.1f} GB, shape {item['shape'] or 'unknown'}")
                print(f"    {item['import_command']}")
        for service in report["services"]:
            print(f"service: {service['name']} ({service['kind']})")
        return 0
    if args.action == "stop":
        for line in old_install.stop() or ["nothing was running"]:
            print(f"stopped: {line}")
        return 0
    if args.action == "archive":
        if not args.to:
            raise SystemExit("archive needs --to FOLDER (somewhere with room, for example an external disk)")
        for record in old_install.archive(Path(args.to).expanduser(), state.home):
            print(f"kept {record['folder']} in {record['archive']} ({record['files']} files, {record['bytes'] / 1e9:.1f} GB, checked)")
        return 0
    for line in old_install.remove(state.home, without_backup=args.without_backup) or ["nothing to remove"]:
        print(f"removed: {line}")
    return 0


def cmd_mcp(state: State, args: argparse.Namespace) -> int:
    from .recall import run_mcp

    return run_mcp(state, args.agent)


def cmd_preflight(state: State, args: argparse.Namespace) -> int:
    from .recall import run_preflight

    return run_preflight(state, args.agent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tl_client", description="Time Library client")
    parser.add_argument("--home", help="client state directory (default: ~/.time-library-client)")
    commands = parser.add_subparsers(dest="command", required=True)

    pair = commands.add_parser("pair", help="pair this computer with a server")
    pair.add_argument("--server", help="the server's address; left out, the client looks for it on this network")
    pair.add_argument("--token", required=True)
    pair.add_argument("--name", help="what this computer calls itself (default: its own name)")
    pair.set_defaults(func=cmd_pair)

    report = commands.add_parser("report-agent", help="an agent reports itself")
    report.add_argument("--name", required=True)
    report.add_argument("--sessions", help="directory holding this agent's session files (needed the first time)")
    report.add_argument("--glob", help=f"which files are sessions (default {DEFAULT_GLOB})")
    report.add_argument("--format", help="one of: " + ", ".join(sorted(BUILTIN_FORMATS)) + " (default flat_role_content)")
    report.add_argument("--format-json", help="a session format description, as JSON, instead of --format")
    report.add_argument("--capability", action="append", default=[], metavar="NAME=true|false")
    report.add_argument("--since", help="only collect what is said from this time on (an ISO time, or now): "
                        "for sessions whose past is not worth keeping")
    report.add_argument("--hook-json", help='how your prompt hook works, if it is not "prompt in, text out": '
                        '{"prompt": [paths to the user\'s words in what the hook is given], "output": a template with '
                        '"{text}" where the memories go, "empty": what to print when there are none, "once_per": '
                        '[paths that identify one turn, for a hook that runs on every model call]}')
    report.add_argument("--model-catalog", help="a file where you keep the official list of your models (with their thinking levels)")
    report.set_defaults(func=cmd_report_agent)

    commands.add_parser("sync", help="read and upload once").set_defaults(func=cmd_sync)
    run = commands.add_parser("run", help="keep reading and uploading")
    run.add_argument("--interval", type=float, default=15.0)
    run.add_argument("--log", help="append what the loop reports to this file instead of stdout")
    run.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    run.set_defaults(func=cmd_run)
    commands.add_parser("status", help="show pairing and agents").set_defaults(func=cmd_status)
    commands.add_parser("discover", help="list the Time Library servers on this network").set_defaults(func=cmd_discover)
    vf = commands.add_parser("verify", help="compare the session files with what the server has, and send what it is missing")
    vf.add_argument("--agent", help="only this agent (default: all on this computer)")
    vf.add_argument("--repair", action="store_true", help="also send when unusually much is missing")
    vf.set_defaults(func=cmd_verify)
    rt = commands.add_parser("runtime", help="the client's own Python: install it here (from the server) and run on it")
    rt.add_argument("action", choices=["install", "where"])
    rt.set_defaults(func=cmd_runtime)
    chk = commands.add_parser("check", help="try a session format on your own files: what would be collected and "
                                            "what looks wrong (nothing is sent)")
    chk.add_argument("--agent", help="check what an agent already reported")
    chk.add_argument("--sessions")
    chk.add_argument("--glob")
    chk.add_argument("--format")
    chk.add_argument("--format-json")
    chk.add_argument("--hook-json", help="a hook description to try (see report-agent --hook-json)")
    chk.add_argument("--hook-sample", help="what your prompt hook is given, as one sample (JSON or text)")
    chk.add_argument("--json", action="store_true", help="the result as JSON")
    chk.set_defaults(func=cmd_check)
    imp = commands.add_parser("import", help="bring in history the agent's own session folder no longer holds")
    imp.add_argument("--agent", required=True, help="the agent the history belongs to (already reported)")
    imp.add_argument("--from", dest="folder", required=True, help="folder holding the old session files")
    imp.add_argument("--glob", action="append", help="file pattern; repeat for several (default: all .jsonl)")
    imp.add_argument("--format", default="flat_role_content")
    imp.add_argument("--format-json")
    imp.add_argument("--dry-run", action="store_true", help="count only, send nothing")
    imp.add_argument("--folders-only", action="store_true", help="only tell the server which folder each session worked in")
    imp.set_defaults(func=cmd_import)
    skill = commands.add_parser("skill", help="write the Time Library skill into an agent's skills folder")
    skill.add_argument("--into", required=True, help="the skills folder the agent reads (it reports this itself)")
    skill.set_defaults(func=cmd_skill)
    svc = commands.add_parser("service", help="keep the client running in the background (starts at login)")
    svc.add_argument("action", choices=["install", "uninstall"])
    svc.set_defaults(func=cmd_service)
    old = commands.add_parser("old-install", help="move this computer off an earlier Time Library install")
    old.add_argument("action", choices=["scan", "stop", "archive", "remove"])
    old.add_argument("--json", action="store_true", help="scan: print the report as JSON")
    old.add_argument("--to", help="archive: the folder that keeps the copy")
    old.add_argument("--without-backup", action="store_true", help="remove: even if no archive was made")
    old.set_defaults(func=cmd_old_install)
    mcp = commands.add_parser("mcp", help="MCP server on stdio for an agent to recall memories")
    mcp.add_argument("--agent", default="", help="which agent this is (its own name)")
    mcp.set_defaults(func=cmd_mcp)
    pre = commands.add_parser("preflight", help="print memories related to the prompt on stdin, or nothing")
    pre.add_argument("--agent", default="")
    pre.set_defaults(func=cmd_preflight)

    args = parser.parse_args(argv)
    state = State(args.home)
    try:
        return args.func(state, args)
    except ServerUnreachable as error:
        print(f"server not reachable: {error}", file=sys.stderr)
        return 3
    except ServerRefused as refusal:
        print(f"server refused: {refusal}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
