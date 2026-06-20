# Memcore Cloud

<p align="center">
  <img src="assets/brand/yifanchen-logo.jpg" alt="Memcore Cloud" width="220"/>
</p>

<p align="center">
  <strong>Keep local AI agents from starting over.</strong>
</p>

<p align="center">
  Memcore Cloud is a local AI memory layer for agents: capture source records, recall them with source refs, answer from evidence, install a standing agent rule, and check health before real recall.
</p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.6.20">2026.6.20</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.6.20-2f5f9b">
  <img alt="Platforms" src="https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-ready-247447">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-memory-b07d35">
</p>

**Memcore Cloud** is the English product name. **忆凡尘 / Yifanchen** remains the Chinese name and codename.

Memcore Cloud is easiest to understand as a five-step local workflow:

```text
capture -> recall -> answer from evidence -> install agent rule -> health
```

It is not a hosted chat app and not a summary-to-vector API. It keeps original
records on your machine, returns source refs before raw excerpts, and gives
local agents a standing rule for when to check memory before they answer or act.

## Core Workflow

- **Capture source records**: keep original conversations, tool output, source tool, device, and timeline before any summary. Summaries help navigation, but original records remain the source of truth.
- **Recall with source refs**: ask about old decisions, preferences, fixes, project boundaries, or next steps and get compact source refs, library ids, hit reasons, and optional bounded excerpts.
- **Answer from evidence**: when a model is configured, Memcore Cloud can ask it to answer only from supplied evidence, cite supporting refs, or return `UNKNOWN` when evidence is insufficient.
- **Install an agent rule**: add the Memcore Cloud Zhiyi skill/instruction or `yifanchen-zhiyi` MCP tool so Codex, Claude, OpenClaw, Hermes, Cursor-style tools, and other local agents know when to call recall.
- **Check health before trust**: use capability check, Record Doctor, preflight doctor, and separated evaluation lanes so install checks, daily recall, regression tests, and offline benchmarks do not blur together.

## Advanced Capabilities

- **Shared local context**: use one local record base across Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and popular open-source agents.
- **Zhiyi and Xingce**: Zhiyi keeps preference and intent experience; Xingce keeps work experience, validation paths, gotchas, and repair order. Experience is not a skill library.
- **Experience for every local agent**: deliver source-backed work experience through skills, custom instructions, MCP, and `work_preflight` so agents can check work history before acting.
- **Hermes skill evolution**: compare Hermes skills with Xingce experience in a read-only diff, then turn new skills or changed skills into reviewable adoption or upgrade candidates.
- **Safe agent authority**: memory is passive by default. Recall context cannot silently become a direct answer, and a direct answer cannot silently become a platform action.
- **Local console**: open a browser page to see tools detected on this machine, recent record health, safe capability checks, and where new raw records are stored.
- **Evaluation lanes**: daily recall checks, targeted regression, and offline benchmark runs are separated, with resource ledgers so scoring work does not become the daily path.
- **Simple install options**: use one shell command, PowerShell, or the double-click installers included in the release zip.

## Quick Demo

After install, open the local console:

```text
http://127.0.0.1:9850
```

Then run the safe first check:

```json
{"query":"capability check","mode":"capability_check"}
```

A healthy first result says the connection is read-only, no real memory was recalled, and no raw excerpt was returned. After that, try a real question such as:

```text
What did we decide last time about this project?
```

Memcore Cloud is designed to answer with source refs first, then expand to original evidence only when you ask.

Before asking an agent to change code, install, sync, or troubleshoot, ask it to
check local context first. The expected behavior is simple: tell you whether the
work looks already built, miswired, missing a diagnostic, or truly missing, then
inspect the repo and tools before editing.

## What It Remembers

AI tools forget the small things that make work smooth: your preferred wording, project boundaries, old mistakes, useful fixes, and where a task left off. Memcore Cloud keeps that trail on your own machine so a new agent window does not have to start from zero.

It is not a hosted chat app and not a summary vault. It keeps source records, source refs, corrections, and work experience together so memory can point back to the original words.

## How Experience Evolves

Experience evolves, but it is not a black box. Memcore Cloud supports
evidence-backed curation with validation and receipts. Experience moves like a
library curation workflow:

```text
raw record
-> experience candidate
-> review queue
-> source and acceptance-check validation
-> authorized adoption or rejection
-> rollback, supersede, or upgrade receipt
```

That means a useful repair path can become reusable Xingce experience, while a
bad or unsupported lesson can stay in review, move to errata, or be rolled back.
The current system supports curated evolution; it does not claim fully
autonomous self-training.

## What You Get In Practice

- **Shared local context for your AI tools**: Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and fast-moving open-source agents can connect to the same local record base.
- **Working methods that survive the next window**: preferences stay available, while proven ways of working become reusable guidance.
- **Preferences and experience stay distinct**: Zhiyi keeps preferences, corrections, and boundaries; Xingce keeps repair paths, validation steps, and work methods.
- **Experience can intervene across platforms**: Xingce is not private to one tool. Any local agent with a skill, custom instruction, or MCP entry can read the same experience candidates, gotchas, and acceptance checks before work.
- **Fewer repeated fixes**: before starting work, an agent can check whether you already built the feature, tested the path, or found the same wiring problem earlier.
- **Receipts, not vibes**: remembered items keep source trails so you can check why something came back.
- **Original records stay original**: summaries can help navigation, but they do not replace saved source text.
- **Tool boundaries stay visible**: Claude Desktop and Claude Code CLI are treated separately; relay or official-login records are not silently mixed.
- **A safer first test**: capability check proves the local read-only path works without recalling real memory or returning raw excerpts.
- **Install once, then it finds your tools**: Memcore Cloud discovers local AI tools, including popular open-source agents such as OpenCode, Goose, Aider, and OpenHands, connects usable local AI tool entries, and keeps new memory sources in a computer-first archive.
- **Smarter recognition for new tools**: if you have a model configured, or already have a local AI model setting Memcore Cloud can reuse, it can identify unfamiliar tools from metadata only; if not, local rules still work.

## Paste This To Your Local Agent

If you use Codex, Claude Code CLI, OpenClaw, Hermes, or another local agent that can run terminal commands, paste this prompt into it:

```text
You are installing Memcore Cloud for me on this machine.
Repository: https://github.com/strmforge/memcore-cloud

Install and start Memcore Cloud. Then install Memcore Cloud Zhiyi as a standing memory rule for this agent, not just a one-time setup note. If this platform supports skills or custom instructions, add the Memcore Cloud Zhiyi skill/instruction. If this platform supports MCP, register the MCP tool named yifanchen-zhiyi at http://127.0.0.1:9851/mcp.

After setup, run only a safe capability check with zhiyi_recall:
{"query":"capability check","mode":"capability_check"}
Do not recall my real memory yet; do not recall my real memory until I ask.

Keep this rule active from now on. When my question depends on prior context, call zhiyi_recall before answering and use source refs by default; ask for raw excerpts only when I explicitly need original evidence text. Triggers include previous decisions, corrections, project boundaries, forgotten context, install/test/release status, and short follow-ups in ongoing work such as "next step", "what else", or "then what". Use active recall by default: current window/session first, then same project/workspace, same workstream/task, then stable preferences/tool facts. Use raw-pool/global only when I explicitly ask for that wider view. If explicit window-only recall says the current window/session is not bound yet, say that plainly; do not claim there is no memory. If the skill is installed but zhiyi_recall is not available, tell me the MCP/tool connection is missing instead of guessing from memory.

Before coding, installing, syncing, release-prep, or remote troubleshooting, run a read-only pre-work check:
{"query":"<the work to do>","mode":"work_preflight"}
Use it to decide whether the work looks already built but forgotten, already built but miswired, missing diagnostics, or actually missing. Treat that result as a starting point; still inspect the repo, tests, tools, and docs before editing.
```

The installer adds the workflow skill where skills are supported, registers `yifanchen-zhiyi` MCP where the platform supports MCP, and keeps backup/receipt records for local config writes.

## Quick Install

2026.6.20 is the current published release. Download the release zip or use
the versioned install scripts from GitHub Releases.

macOS / Linux:

```bash
curl -fL -o memcore-cloud-install.sh https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.20/install.sh
bash memcore-cloud-install.sh
```

Windows PowerShell:

```powershell
iwr https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.20/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

If you downloaded the release zip, Windows can also use the double-click
`Memcore Cloud Installer.cmd`; it opens a folder picker and then runs the same
installer with the selected path. On macOS, double-click
`Memcore Cloud Installer.command` from the extracted release folder.

Windows installs default to `%LOCALAPPDATA%\memcore-cloud`. To choose a path
before the install:

```powershell
$env:MEMCORE_INSTALL_DIR = "D:\Apps\memcore-cloud"
iwr https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.20/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

If you already downloaded the repo, you can also run:

```powershell
.\install.ps1 -Dir "D:\Apps\memcore-cloud"
```

WSL is only for development or advanced testing. Normal Windows installs should
use the Windows PowerShell command above.

On Windows, use the Memcore Cloud tray icon after install. On macOS, use the
Memcore Cloud menu bar icon. Both can open the local console, show health, and
catch up missed records.

You can also open the local console directly:

```text
http://127.0.0.1:9850
```

## Safe First Check

For install checks, do not use `/zhiyi` first. It may run real recall. Ask the client to call `zhiyi_recall` with:

```json
{"query":"capability check","mode":"capability_check"}
```

A good first result should include:

```text
read_only: true
recall_performed: false
raw_excerpt_returned: false
mcp_tools: ["zhiyi_recall"]
```

Only run real recall after you explicitly choose to test memory retrieval.

## Record Doctor

To check whether records are guarded before testing recall, run:

```bash
python3 tools/record_doctor.py
```

It prints a short read-only report for source records, raw mirrors, the canonical index, and memory/experience links. It does not run recall, backfill, model calls, or platform writes.

## Benchmark Diagnostics

Benchmarks are useful, but they are not the same thing as daily product
behavior. Memcore Cloud separates daily recall checks, targeted regression, and
offline benchmark runs so a scoring job does not overload the workstation that
is also running your local agents.

The first public diagnostic is no-key evidence retrieval over public memory
benchmark data. It checks whether Memcore Cloud can find the original evidence:

```bash
python3 tools/free_memory_benchmark.py --download
```

Current no-key retrieval diagnostic, on a 100-point scale:

| dataset | exact source recall | bundled source recall |
|---|---:|---:|
| LoCoMo locomo10 | 66.5/100 | 82.3/100 |
| LongMemEval oracle | 82.6/100 | 91.2/100 |

This suite does not call a judge model, does not write memory, and does not
claim a LoCoMo or LongMemEval official leaderboard score.

Answer-level diagnostics are a separate lane. Current internal LongMemEval
oracle judging shows the main gap clearly: evidence retrieval is stronger than
answer synthesis. The latest full 500-question internal run reached **39.4/100**
official-like binary accuracy, or **43.7/100** internal half-credit answer
acceptance. Treat those as internal diagnostics for miss-case review, not a
leaderboard claim. Official LongMemEval scoring still requires the accepted
official evaluator path and evaluator model environment.

For commands, sample tiers, Codex-based internal judging, resource ledgers, and
offline/R730XD pressure-test notes, see [benchmarks/README.md](benchmarks/README.md).

## What The Local Page Shows

Open `http://127.0.0.1:9850` to see:

- which AI tools are present on this machine;
- which ones can run a safe capability check;
- which ones are already connected or ready for local AI tool integration;
- whether source records, raw mirrors, the canonical index, and memory/experience links are guarded;
- whether a tool looks recently used or has been quiet for a while;
- where new raw records are being stored.

On Windows and macOS, the tray/menu bar icon gives you the same entry point
without remembering the port. The local watcher keeps running and can backfill
missed records after restart or repair.

Supported local AI tool entries can be connected automatically. Conversation import uses verified local formats, and capability check remains no-recall until an agent calls real recall.

## What Makes It Different

- **Source-backed memory**: recall can carry `source_refs`, raw excerpts, library ids, and rank reasons.
- **Zhiyi and Xingce**: Zhiyi keeps preference and intent experience; Xingce keeps work experience and validation paths. Experience is not a skill library.
- **Read-only pre-work checks**: agents can check existing context before they edit, so a finished feature does not get rebuilt just because the next window forgot it.
- **Explicit memory authority**: passive capture, recall, context injection, direct answers, and platform actions are separate levels. OpenClaw-style interception is passive by default.
- **Evidence-bound model use**: model calls are optional and must answer from supplied evidence with supporting refs or return `UNKNOWN`.
- **Traceable experience evolution**: candidates, review queues, validation receipts, apply gates, adoption receipts, and rollback overlays keep useful work paths improving while preserving raw records and receipts.
- **Record doctor**: a one-click self-check shows whether source records, raw mirrors, the canonical index, and memory/experience links are guarded.
- **A timeline you can trace back**: different tools leave different clues, but Memcore Cloud keeps them in one source-backed timeline. Raw records stay first; useful experience can settle into Zhiyi, Xingce, toolbook, or errata with source refs, collection ids, lifecycle state, and receipts.
- **Organized local records**: new records are grouped by computer first, then by the AI tool that produced them, so a multi-device setup can stay understandable.
- **Claude is handled carefully**: Claude Desktop and Claude Code CLI can both connect, but they remain separate surfaces. Official, relay, and CLI-related records keep attribution boundaries.
- **Hermes can inspect sources itself**: Memcore Cloud can provide raw/source-ref pointers and observe native feedback, while Hermes-owned skill changes remain Hermes-owned.

## Current Release: 2026.6.20

2026.6.20 is the current published release. It focuses on safer
local AI tool connection, low-resource defaults, pre-work context checks,
Record Doctor, source-backed recall, and evidence-bound model diagnostics.

See [RELEASE_NOTES_2026.6.20.md](RELEASE_NOTES_2026.6.20.md) for this release,
[UPDATE_HISTORY.md](UPDATE_HISTORY.md) for older highlights, and
[CHANGELOG.md](CHANGELOG.md) for lower-level changes.

## AI Tool Surfaces

- **Claude Desktop**: can use Memcore Cloud through local MCP / Desktop Extensions; source records use verified local format collectors.
- **Claude Code CLI**: can use MCP while staying separate from Claude Desktop.
- **Codex**: can use the shared skill and MCP entry, and local sessions can become source-backed records.
- **OpenClaw**: can receive memory support through local entry points, but normal chat is not taken over by Memcore Cloud by default.
- **Hermes**: can consume raw/source-ref pointers and produce native feedback without Memcore Cloud writing Hermes skills.
- **Other local AI tools**: can be recognized from local settings, app folders, package managers, and workspace markers; supported local entries can be connected automatically, and tools are promoted to memory sources once their local formats are verified.

## Documentation

- [中文 README](README.zh-CN.md)
- [What Memcore Cloud Means](INTRODUCTION.md)
- [Update history](UPDATE_HISTORY.md)
- [Wiki](https://github.com/strmforge/memcore-cloud/wiki)

## Uninstall

macOS / Linux:

```bash
~/.memcore-cloud/uninstall.sh
```

Windows:

```powershell
.\uninstall.ps1
```

Uninstalling removes the app files only. Local data such as `memory/`, `raw/`, `zhiyi/`, and `config/` is kept.

## License

[MIT](LICENSE)
