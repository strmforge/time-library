# Time Library

<p align="center">
  <img src="assets/brand/time-library-logo-en.png" alt="Time Library" width="220"/>
</p>

<p align="center">
  <strong>One memory for all your AI agents, on your own server — with the receipts.</strong>
</p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/strmforge/time-library/releases">Releases</a> ·
  <a href="https://github.com/strmforge/time-library/wiki">Wiki</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.11-2f5f9b">
  <img alt="Server" src="https://img.shields.io/badge/server-NAS%20%2F%20Docker-247447">
  <img alt="Client" src="https://img.shields.io/badge/client-macOS%20%7C%20Windows%20%7C%20Linux-b07d35">
</p>

**Time Library / 时间图书馆** remembers what you and your AI agents decided,
corrected and learned — across every agent on every computer — and shows the
original words each memory came from.

It runs as **one server on your NAS** (a Docker container) and **a small client
on each computer**. Agents connect themselves: you give an agent one sentence,
it installs the client, says what it is and where it keeps its sessions, and
connects. There is no per-tool adapter to wait for.

## A rebuild

2026.11.23 does not add to the earlier version: Time Library was rebuilt from
the ground up. The aim is unchanged: one memory for all your agents, every
memory resting on the original words. The architecture, the code, the install
and the admin are all new.

| | 2026.9.11 and earlier | 2026.11.23 on |
|---|---|---|
| Where it runs | A full set of services on every computer | One server on your NAS (Docker), a small client on each computer |
| Who shares memory | The agents on one computer | Every agent on every computer |
| What is kept | Whole session files, runtime (tool output and the like) included | Dialogue only; runtime is dropped on the computer, credentials masked before they leave it |
| A new agent | Needed an adapter written for it | Describes its own session format, checks it, and reports it; no code for any particular product |
| Memories | Raw records with two layers of notes on top | Distilled every night with quotes, each checked character for character; the user's own words told apart from an assistant's and from pasted text |
| Models | chat/completions | A model per task with backups; OpenAI Responses and Anthropic Messages natively; a built-in local model |
| Install | Install scripts and installers | `docker compose up` for the server; the server hands out the client, with its own Python |
| Admin | A local page on each computer | One web admin on the server, in English and Chinese |

Why rebuild:

- **A full stack on every computer meant every computer had its own
  problems**, and most of what it kept was runtime rather than dialogue, so
  local disks kept filling. Now a computer keeps only its read position; the
  dialogue goes to the NAS.
- **Memory should cross computers.** One memory per computer meant starting
  over on the next one.
- **Adapters per product cannot keep up.** New agents appear faster than
  adapters get written. Now an agent says what it is and how its sessions
  look; Time Library only has to read that description.
- **A memory should hold up as evidence**: it points back to the original
  words, and says whose words they were.

Earlier versions cannot install this one with their own update button, on
purpose: applied over an earlier install it would break it. Those from 2026.7.11
on may show that a new version exists, but the update installs nothing. See
[Moving from an earlier version](#moving-from-an-earlier-version).

## How it works

```text
 computer A                       computer B                  your NAS (Docker)
 ┌──────────────────────┐        ┌──────────────────────┐     ┌────────────────────────────┐
 │ Claude Code, Codex,  │        │ OpenClaw, Codex, ... │     │ Time Library server        │
 │ any agent            │        │                      │     │  stores the dialogue       │
 │   │ session files    │        │   │                  │     │  distills it every night   │
 │   ▼                  │        │   ▼                  │     │  into memories with quotes │
 │ client: keeps only   │──LAN──▶│ client               │────▶│  answers recall            │
 │ dialogue, masks keys │◀─recall│                      │◀────│  web admin :9850           │
 └──────────────────────┘        └──────────────────────┘     └────────────────────────────┘
```

- **Capture.** The client reads each agent's own session files. Tool calls,
  tool output, reasoning and injected context are runtime: they are dropped on
  the computer and never leave it. Credentials are always masked; email,
  phone and ID numbers are masked by default. Each agent describes its own
  session files (a small JSON description) and tries it with `tl.py check`
  before reporting it: Time Library has no code for any particular product.
- **Distill.** Every night the server has a model read the new dialogue and
  propose memories — decisions, preferences, corrections, facts, lessons. Each
  must quote the exact words it rests on; the server checks every quote
  against the stored dialogue, character for character. No real quote, no
  memory. The same thing said again in another conversation is folded into
  the memory it repeats (and can be taken out again). What the user said is
  told apart from what the assistant relayed and from what the user pasted in
  (another AI's report, an article).
- **Organise.** After distilling, a second pass: close statements are compared
  and the newer one supersedes the older (both stay when unsure); memories
  returned as misleading again and again are retired; each project's memories
  are drawn up into a few experience cards. Every step leaves a receipt and
  can be undone.
- **Recall.** By words and by meaning (an optional embedding model that runs on
  the NAS). Agents ask through MCP (`time_library_recall`; `time_library_source`
  for the surrounding conversation; `time_library_answer` for one fact that
  must not be guessed: answered only from memory, naming the memories it rests
  on, or UNKNOWN). A window opens with the current project's catalog; where the
  agent has a prompt hook, memories show up before a prompt only when they are
  clearly about it.
- **Borrow and return.** Every recall is a loan. After its work an agent can
  return a memory as useful, useless or misleading (`time_library_return`).
  The next agent sees how a memory was judged.
- **Whiteboard.** The agents in a project write down what they took on, how
  far it got and whom it was handed to; the next window picks it up without
  you relaying anything.

## What you get

- One memory pool across agents and computers, each memory labelled with the
  computer and agent it came from (an agent's desktop app and command line
  told apart).
- Evidence first: every memory carries the original words, and the full
  conversation around them is one call away; each memory has its history
  (first and last said, in how many conversations, who borrowed it, how it
  was judged).
- Proof that it helps: a nightly checkup (are the quoted words still there,
  recall spot checks), and a memory on/off comparison (the same questions
  answered without and with memory, on a button).
- Models your way: a model per task (history import, nightly distillation,
  deep summary), each with an optional backup; OpenAI Responses, Anthropic
  Messages and chat/completions spoken natively; keys stay on the server. A
  built-in local model (Qwen3-4B on llama.cpp) runs on the NAS itself.
- Survives outages: the client keeps its read position, the server keeps its
  place in every conversation. A model that runs out of balance or goes
  offline is retried by itself; nothing is distilled twice. If the NAS gets a
  new address, the clients find it again on your home network.
- History import: sessions from before you installed come in held; choose a
  range on **Import** (recent months, which agents, which projects) and start
  it, with the expected token use shown first.
- A web admin on the server: overview, devices and agents, models, import,
  projects (catalog, agents, whiteboard), and memories (evidence, evolution,
  loans, lifecycle, ask-from-memory). The admin password can be changed, and
  set again with the server key in the NAS's data folder if forgotten.

## Install

### 1. The server, on your NAS

An x86-64 (Intel/AMD) NAS or Linux box with Docker; there is no ARM image yet. In a folder on the NAS's own disk (not a
network share — it holds a SQLite database):

```bash
mkdir -p time-library && cd time-library
curl -fLO https://raw.githubusercontent.com/strmforge/time-library/main/deploy/nas/docker-compose.yml
docker compose up -d
```

Open `http://<nas-address>:9850`, set the admin password, and add a model on
the **Models** page (or switch on the built-in local model). Optional `.env`
next to the compose file: `TL_UID` / `TL_GID` (the NAS user that owns `data/`),
`TL_PORT`, `TL_VERSION`.

No access to the image registry? Clone the repository on the NAS and run
`docker compose -f deploy/nas/docker-compose.yml up -d --build`; fetch the
model runtime first with `python3 deploy/nas/llama_runtime.py --dest
deploy/nas/vendor/llama` if the NAS cannot reach GitHub.

### 2. Each computer: one sentence to an agent

On the **Devices** page, click **生成接入口令** and give the sentence to an
agent on that computer (Claude Code, Codex, OpenClaw, WorkBuddy — any agent
that can run commands). It reads like this:

```text
Connect yourself to the Time Library server http://<nas-address>:9850 with
pairing token tlp_…. First check whether this computer already has the Time
Library client: if it does, do not reinstall; if not, open
http://<nas-address>:9850/client/install.md and follow its steps. Then
describe yourself as its step 4 says: look at your own session files, write
the description, try it with tl.py check on your own files until it says it
looks right, and report it with report-agent; connect MCP, skill and prompt
hook as step 6 says. Write no scripts and do not guess from product names; if
something cannot be described, say exactly what is missing.
```

The server hands out the client itself, **together with its own Python
(3.14)**, installed inside the client's folder: nothing system-wide, no PATH
change, no administrator, whether or not the computer already has Python. On
macOS and Linux it is one `curl | tar`; Windows 10 and later use their own
`curl.exe` and `tar.exe`. The client always matches the server, and installed
clients follow the server's version by themselves. The token is valid for 24
hours and binds to the first computer that uses it. A second agent on the same
computer gets a shorter sentence without a token.

### 3. Updating

The admin's **Overview** shows the version at the top: when there is a newer one, click
**Update to …**; no image is pulled. The server downloads only its own program (under
1 MB, from the image registry, checked by sha256), restarts, and runs it on trial: it
counts as updated only once the new version answers as itself. If it does not work, the
server goes back by itself; you can also go back by hand. Your data is not touched. A
rare version that needs a newer Python or libraries says so, and then its image is
pulled once: `docker compose pull && docker compose up -d`.

Checking asks `api.github.com` which release is newest (only when you open Overview or
click, with no identifiers). The clients follow the server's version by themselves.

## Moving from an earlier version

Versions up to 2026.9.11 ran a full set of services on every computer. To
move a computer over:

1. Set up the server (above).
2. Give an agent on that computer the sentence. After installing the client,
   the guide's last section has it run `tl.py old-install scan`: it finds the
   earlier install, its services, and the history it kept, with an import
   command for each collection. Imported history waits on the server, costing
   nothing until you start organising it on the **Import** page.
3. The agent stops the earlier services, removes its own settings that point
   into the earlier folder, keeps a checked copy where you tell it
   (`old-install archive --to …`), and only then removes the earlier install
   (`old-install remove`).

Earlier releases stay available on the
[releases page](https://github.com/strmforge/time-library/releases) if you
need to go back.

## Not in this version

- The Hermes skill-and-experience loop: not planned (Hermes's conversations are
  collected as usual).
- The server is meant for your home network: plain HTTP with per-computer
  tokens. Do not expose it to the internet as it is.

## Data and privacy

- Stored on your NAS: the dialogue (without runtime), the memories, and the
  loans. Original session files stay where each agent keeps them.
- Sent to a model: the dialogue being distilled, organised or answered from,
  to the endpoint you chose for that task. A relay is a third party; the built-in local model keeps
  everything on the NAS.
- Masked before upload, always: API keys, tokens, private keys, passwords in
  URLs and assignments. Masked by default: email, phone numbers, ID numbers.

## Remove

- A computer: `PY ~/.time-library-client/tl.py service uninstall`, remove the
  agents' `time-library` MCP entries / hooks / skills, then delete
  `~/.time-library-client`. Revoke it on the **Devices** page.
- The server: `docker compose down`. Everything it kept is in `data/`.

## Development

```bash
pip install -r requirements-dev.txt                    # pytest, zstandard, meaning-based recall
python -m pytest tests/server_client -q
python -m tl_server --data-dir ./data --port 9850      # server
python -m tl_client --help                             # client
```

`tl_client/` uses only the Python standard library (it runs on 3.9 and later;
installs bring 3.14). So does `tl_server/`; meaning-based recall also needs
`requirements-vectors.txt` (the image has it). `system/skills/time-library/` is
the skill the client package carries.

## License

[MIT](LICENSE)
