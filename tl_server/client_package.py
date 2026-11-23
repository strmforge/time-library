"""The client install package, served by the server itself.

An agent told "connect to this server" fetches the client from the same
address: no internet needed, and the client always matches the server it talks
to. The package carries the Time Library skill (one copy, from system/skills).

Layout, unpacked into ~/.time-library-client/ (Windows: %USERPROFILE%):
  tl.py                      launcher: python tl.py <command> works from any folder
  app/tl_client/             the client (standard library only)
  app/tl_client/agent_skill/ the skill an agent installs into its skills folder
  INSTALL.md                 the steps, for the agent to follow
"""

from __future__ import annotations

import io
import os
import re
import threading
import zipfile
from pathlib import Path

from . import runtimes

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "time-library-client.zip"

LAUNCHER = """import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
from tl_client.__main__ import main
raise SystemExit(main())
"""

_cache: dict[str, bytes] = {}
_lock = threading.Lock()


def _sources() -> tuple[Path, Path]:
    client = Path(os.environ.get("TL_CLIENT_SOURCE", ROOT / "tl_client"))
    skill = Path(os.environ.get("TL_SKILL_SOURCE", ROOT / "system" / "skills" / "time-library"))
    return client, skill


def client_version() -> str:
    """The version of the client this server hands out."""
    client, _skill = _sources()
    try:
        text = (client / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'^CLIENT_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def available() -> bool:
    client, skill = _sources()
    return (client / "__main__.py").is_file() and (skill / "SKILL.md").is_file()


def package() -> bytes:
    """The zip, built once (the image does not change while it runs)."""
    with _lock:
        if "zip" not in _cache:
            _cache["zip"] = _build()
        return _cache["zip"]


def _build() -> bytes:
    client, skill = _sources()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("tl.py", LAUNCHER)
        archive.writestr("INSTALL.md", install_guide("<the server address you were given>"))
        for base, prefix in ((client, "app/tl_client"), (skill, "app/tl_client/agent_skill")):
            for path in sorted(base.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    archive.write(path, f"{prefix}/{path.relative_to(base).as_posix()}")
    return buffer.getvalue()


def install_guide(server: str) -> str:
    return f"""# Install the Time Library client

忆凡尘 / Time Library 客户端安装说明 —— 给 AI agent 照着做。

Server: {server}

The client is small (Python standard library only). It reads your own session
files, drops runtime (tool calls, tool output, reasoning), masks credentials,
and uploads the dialogue to the server. It also gives you recall over MCP.
Connect only through what you really support; leave the rest unsupported.

Below, `TL` means the folder `~/.time-library-client` (Windows:
`%USERPROFILE%\\.time-library-client`), and `PY` the client's own Python inside
it: `TL/python/bin/python3` (macOS, Linux) or `TL\\python\\python.exe` (Windows).
Write both as full absolute paths everywhere: services, MCP servers and hooks
do not see your shell's PATH.

## 1. Already installed?

If `TL/tl.py` exists and `PY TL/tl.py status` shows this server, skip to step 4.
(A computer set up earlier on a Python it already had keeps working; `<that python>
TL/tl.py runtime install` moves it onto the client's own Python.)

## 2. Download and unpack: the client with its own Python

The server hands out the client together with Python {runtimes.PYTHON_VERSION} for your kind of
computer. Nothing is installed system-wide, nothing changes on PATH, no
administrator is needed, and a Python already on the computer is left alone.
Your kind: `macos-arm64` (Apple silicon), `macos-x86_64`, `linux-x86_64`,
`linux-aarch64`, `windows-amd64` or `windows-arm64` (`uname -m` tells; on
Windows, the processor architecture).

macOS, Linux:

```
mkdir -p ~/.time-library-client && curl -fsSL --noproxy '*' {server}/client/bundle/<kind>.tar.gz | tar -xz -C ~/.time-library-client
```

Windows 10 or later (it has curl.exe and tar.exe), in PowerShell:

```
New-Item -ItemType Directory -Force "$env:USERPROFILE\\.time-library-client" | Out-Null
curl.exe -fsSL --noproxy "*" -o "$env:TEMP\\tl-bundle.tar.gz" {server}/client/bundle/<kind>.tar.gz
tar.exe -xzf "$env:TEMP\\tl-bundle.tar.gz" -C "$env:USERPROFILE\\.time-library-client"
```

The first time a kind of computer asks, the server fetches that Python (it can
take a minute). If it answers 503 (it could not fetch it), use a Python 3.9 or
later already on the computer as `PY` instead, and unpack the client alone:

```
PY -c "import io,os,urllib.request,zipfile; d=os.path.join(os.path.expanduser('~'),'.time-library-client'); os.makedirs(d,exist_ok=True); o=urllib.request.build_opener(urllib.request.ProxyHandler({{}})); zipfile.ZipFile(io.BytesIO(o.open('{server}/client/{PACKAGE_NAME}').read())).extractall(d)"
```

## 3. Pair this computer (once per computer)

Use the token from the sentence you were given (valid 24 hours, single use):

```
PY TL/tl.py pair --server {server} --token <TOKEN>
```

Add `--name "<name>"` only if the computer should be called something other
than its system name.

## 4. Describe yourself, check it, report it

You describe your own sessions; Time Library has no code for any particular
agent and never will. Write nothing of your own (no scripts, no copies of the
client): everything below is said with the client's options.

**a. Look at your own session files.** Find where they are and open a few lines
of a recent one. Note: where the speaker is said and in what words, where the
words are, where the time is, how a session is named (inside the records, in a
header line, or only by its folder), what your harness writes in the user's
name that the user did not type (context, approvals, reports from subagents),
and whether some files are subagents' own transcripts.

**b. Write the description** (JSON, for `--format-json`). Start from the shape
closest to yours as `base`:

- `message_envelope_content_blocks`: `{{"type": "user", "message": {{"role": ..., "content": ...}}}}`
- `response_item_payload_message`: `{{"type": "response_item", "payload": {{"type": "message", "role": ..., "content": ...}}}}`
- `flat_role_content`: `{{"role": ..., "content": ...}}`

and override what differs. Paths are dotted (`data.message.role`); fields that
take a list of paths use the first one present in a record.

- Which records: `match` (path -> allowed values, all must hold), `skip_if_true`
  (paths), `skip_if_equals` (path -> values).
- Who speaks: `role` (paths). If your speaker words are not user/assistant,
  `role_map` says what they mean: `{{"USER_EXPLICIT": "user", "MODEL": "assistant", "SYSTEM": "skip"}}`.
- What was said: `content` (paths; a string, or a list of blocks), `text_block_types`
  (which block types are words), `block_text` (the key a block keeps its words
  under, default `text`).
- When: `timestamp` (ISO text, or epoch seconds or milliseconds).
- Which session: `session_id` (paths; a header line's field works too: it
  carries to the records after it), or `session_id_from_path`, a regular
  expression over the file's path inside the sessions folder whose first group
  is the id (`"^([^/]+)/"` when each session has its own folder).
- Where it worked and was started: `cwd` (paths), `surface` (paths, when one
  agent has several places to start from, such as a desktop app and a command line).
- Only what the user typed: `user_match` (path -> values a user record must
  have to count as typed by the user), `unwrap_elements` (tags around the user's
  words: the tags go, the words stay), `runtime_elements` (tags around context
  you add: dropped with their content), `runtime_messages` (whole-turn notices,
  as regular expressions).
- Whole files that are not conversations with the user (a subagent's own
  transcript): `session_skip_if_equals`, path -> values, judged on the file's first record.
- How sessions are stored: JSON lines are the default (zstd-compressed files are
  read as they are). `"store": "json"` with `"records": "<path to the list>"`
  when each file is one JSON document. `"store": "sqlite"` with `"table"` and
  `"order"` (a column that only grows) when they are in a database (give the
  database file as `--sessions`); `json_columns` lists columns that hold JSON.
  The database is only read, never written.

**c. Check it on your own files.** Nothing is sent:

```
PY TL/tl.py check --sessions "<your sessions folder>" --glob "<which files>" --format-json '<your description>'
```

(On Windows, or whenever quoting JSON is awkward, put it in a file and pass
`--format-json @<file>`; the same works for `--hook-json` and `--hook-sample`.)

It says how many sessions and turns would be collected, shows a few, lists
what it left out and why, and warns about what looks wrong (all files giving
one session id, no user turns, speaker words it did not understand, context
written as user turns). Correct the description and check again until it says
it looks right. Use `--glob` when the folder holds other files too.

**d. Report it**, with the same options:

```
PY TL/tl.py report-agent --name "<your product name>" --sessions "<folder>" --glob "<files>" --format-json '<description>' --capability mcp=true|false --capability skill=true|false --capability preflight=true|false
```

If your past sessions are mostly tests or automated runs rather than the
user's own conversations, add `--since now`: only what is said from then on is
collected. Reporting again later, give only what changed; the rest stays:
`PY TL/tl.py report-agent --name "<your product name>" --capability preflight=true`.

If something about your sessions cannot be said with these fields, do not work
around it: tell the user exactly what is missing (the field, and a line of your
file that shows it), and report only what does read right.

If you keep the official list of your models on disk (with the thinking levels
each takes), add `--model-catalog "<that file>"`: the levels are then offered as
choices on the server's Models page instead of being typed in.

## 5. Keep it running (once per computer)

```
PY TL/tl.py service install
```

It starts at login (launchd on macOS, Task Scheduler on Windows, systemd --user
on Linux) and keeps uploading; when the server is away it waits and resumes.

## 6. Connect your surfaces (only the ones you have)

- MCP: register a stdio server named `time-library` with command `PY` and
  arguments `TL/tl.py mcp --agent "<your product name>"`. Tools:
  `time_library_recall`, `time_library_source`, `time_library_answer`,
  `time_library_catalog`, `time_library_declare`, `time_library_whiteboard`,
  `time_library_return`.
- Skill: `PY TL/tl.py skill --into "<your skills folder>"`.
- Prompt / preflight hook: command `PY TL/tl.py preflight --agent "<your product name>"`.
  It reads what the hook is given on stdin and prints a `<time-library-memory>`
  block (UTF-8), or nothing. It never fails loudly, and hands over memories only
  when they are clearly about the prompt. If your hook is not "the prompt in
  (JSON field `prompt`, or plain text), text out", describe it once with
  `report-agent --hook-json`: `{{"prompt": ["<path to the user's words>"],
  "output": <a text or JSON template with "{{text}}" where the memories go>,
  "empty": "<what to print when there are none, for example {{}}>",
  "once_per": ["<paths that identify one turn>"]}}` (`once_per` for a hook that
  runs on every model call: memories are handed over once a turn). Your own
  wrappers around the user's words are taken off as your description says. Try
  it with `PY TL/tl.py check --agent "<name>" --hook-sample '<what your hook is given>'`
  and point the hook at the same preflight command: no script in between.

## 7. Check

`PY TL/tl.py status` lists this computer and its agents. Do not recall the
user's memory just to prove the install; the first real recall happens when a
question actually needs earlier context.

## Another agent on the same computer

Steps 4 and 6 only: the client is already installed and paired.

## An earlier Time Library on this computer?

Earlier versions ran a full set of services on every computer. After steps 1-6:

1. `PY TL/tl.py old-install scan` lists the earlier install folders, their
   services, and the history they kept, with a ready `import` command for each
   collection. The source folder name tells which agent wrote it: import the
   ones that are yours (replace `<your name>`). Imported history waits on the
   server until the user decides to have it organised; it costs nothing now.
2. `PY TL/tl.py old-install stop` stops the earlier services.
3. Remove your own settings that point into the earlier folder (MCP entries,
   prompt hooks, skills such as `yifanchen-zhiyi`); you connected the new ones
   in step 6. Change only your own configuration.
4. Ask the user where to keep a copy (an external disk or a NAS folder with
   room), then `PY TL/tl.py old-install archive --to "<that folder>"`. The copy
   is read back and checked against the folder.
5. With the user's go-ahead: `PY TL/tl.py old-install remove`. It refuses to
   remove a folder that has no checked copy.
"""
