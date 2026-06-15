# Memcore Cloud

<p align="center">
  <img src="assets/brand/yifanchen-logo.jpg" alt="Memcore Cloud" width="220"/>
</p>

<p align="center">
  <strong>Keep local AI agents from starting over.</strong>
</p>

<p align="center">
  Memcore Cloud helps Claude, Codex, OpenClaw, Hermes, and other local agents keep useful records on your machine, recall prior context, reuse proven fixes, and verify answers from original source records.
</p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.6.15">2026.6.15</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.6.15-2f5f9b">
  <img alt="Platforms" src="https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-ready-247447">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-memory-b07d35">
</p>

**Memcore Cloud** is the English product name. **忆凡尘 / Yifanchen** remains the Chinese name and codename.

## Features

- **Shared local context**: use one local record base across Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and popular open-source agents.
- **Automatic local records**: keep useful local AI conversations and tool traces on your own computer, organized by device and source tool.
- **Source-backed recall**: ask an agent about old decisions, preferences, fixes, or project boundaries and get compact source refs, hit reasons, and optional bounded excerpts.
- **Reusable work paths**: save repeatable fixes, review steps, project rules, gotchas, and validation paths so the next AI window can continue with what already worked.
- **Record Doctor**: run a safe one-command check before recall to see whether source records, raw mirrors, the canonical index, and memory/experience links are guarded.
- **Local console**: open a browser page to see connected tools, recent record health, safe capability checks, and where new raw records are stored.
- **No cloud account required**: local data stays on your machine by default. Summaries help navigation, but original records remain the source of truth.
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

## What It Remembers

AI tools forget the small things that make work smooth: your preferred wording, project boundaries, old mistakes, useful fixes, and where a task left off. Memcore Cloud keeps that trail on your own machine so a new agent window does not have to start from zero.

It is not a hosted chat app and not a summary vault. It keeps source records, source refs, corrections, and work experience together so memory can point back to the original words.

## What You Get In Practice

- **Shared local context for your AI tools**: Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and fast-moving open-source agents can connect to the same local record base.
- **Working methods that survive the next window**: preferences stay available, while proven ways of working become reusable guidance.
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
```

The installer adds the workflow skill where skills are supported, registers `yifanchen-zhiyi` MCP where the platform supports MCP, and keeps backup/receipt records for local config writes.

## Quick Install

macOS / Linux:

```bash
curl -fL -o memcore-cloud-install.sh https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.15/install.sh
bash memcore-cloud-install.sh
```

Windows PowerShell:

```powershell
iwr https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.15/install.ps1 -OutFile .\install.ps1
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
iwr https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.15/install.ps1 -OutFile .\install.ps1
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
- **Record doctor**: a one-click self-check shows whether source records, raw mirrors, the canonical index, and memory/experience links are guarded.
- **A timeline you can trace back**: different tools leave different clues, but Memcore Cloud keeps them in one source-backed timeline. Raw records stay first; useful experience can settle into Zhiyi, Xingce, toolbook, or errata with source refs, collection ids, lifecycle state, and receipts.
- **Organized local records**: new records are grouped by computer first, then by the AI tool that produced them, so a multi-device setup can stay understandable.
- **Claude is handled carefully**: Claude Desktop and Claude Code CLI can both connect, but they remain separate surfaces. Official, relay, and CLI-related records keep attribution boundaries.
- **Hermes can inspect sources itself**: Memcore Cloud can provide raw/source-ref pointers and observe native feedback, while Hermes-owned skill changes remain Hermes-owned.

## Current Release: 2026.6.15

2026.6.15 is the current Memcore Cloud release.

- Public docs, catalogs, watchlists, diagnostics, and tests no longer expose a specific local relay product as a public dependency or platform entry.
- Existing personal relay traces remain compatible through neutral `local_relay` handling, without promoting that relay as required infrastructure.
- Record diagnostics keep lost source / lost raw wording instead of legacy stray-record wording.
- The release gate now scans public and repository text surfaces for removed relay names and legacy stray-record diagnostics.
- Installers, gateway health, active-memory routing, preflight metadata, local console version text, and the packaged Zhiyi skill report 2026.6.15 consistently.
- Experience validation receipts, receipt-backed apply gates, apply package previews, and the experience flow overview are included as source-backed dry-run governance.
- Current-run local maintainer validation for 2026.6.15 passed on macOS and two Windows hosts: full local tests passed, the working-tree release gate passed, Windows native smoke passed, and the record-chain audit found no lost source or lost raw.

See [RELEASE_NOTES_2026.6.15.md](RELEASE_NOTES_2026.6.15.md) for this release, [UPDATE_HISTORY.md](UPDATE_HISTORY.md) for older highlights, and [CHANGELOG.md](CHANGELOG.md) for lower-level changes.

## AI Tool Surfaces

- **Claude Desktop**: can use Memcore Cloud through local MCP / Desktop Extensions; source records use verified local format collectors.
- **Claude Code CLI**: can use MCP while staying separate from Claude Desktop.
- **Codex**: can use the shared skill and MCP entry, and local sessions can become source-backed records.
- **OpenClaw**: can receive memory support through its normal local entry points.
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
