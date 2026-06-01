# Memcore Cloud

<p align="center">
  <img src="assets/brand/yifanchen-logo.jpg" alt="Memcore Cloud" width="220"/>
</p>

<p align="center">
  <strong>Local-first, source-backed memory for AI agents.</strong>
</p>

<p align="center">
  Give Claude Desktop, Codex, OpenClaw, Hermes, and other local AI tools a shared memory layer without replacing original records with summaries.
</p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.6.1">2026.6.1</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.6.1-2f5f9b">
  <img alt="Platforms" src="https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-ready-247447">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-memory-b07d35">
</p>

Memcore Cloud is the English product name. **忆凡尘 / Yifanchen** remains the Chinese name and codename.

## What You Get

- Your AI tools can stop starting from zero every time you open a new window.
- Original conversations stay on your machine, with source trails you can check later.
- Preferences, corrections, project habits, and repeated work paths can become reusable memory.
- Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and newer local agents can be discovered from the machine they already run on.
- A local agent can install the skill and wire the MCP connection for you; the first check can prove the connection works without recalling real memory.

## Copy This To Your Local Agent

If you use Codex, Claude Code CLI, OpenClaw, Hermes, or another local agent that can run terminal commands, copy this prompt to it:

```text
Please install Memcore Cloud (Yifanchen) from https://github.com/strmforge/memcore-cloud on this machine.
After installation, start the local services. Automatically install the Codex skill. If Codex CLI is available, automatically register the Codex MCP server named yifanchen-zhiyi at http://127.0.0.1:9851/mcp.
If OpenClaw, Hermes, or Claude Desktop is available, use the installer defaults to connect them too; Claude Desktop needs the local MCP bridge registration before it can actually query Memcore Cloud.
Finish with capability check mode only; do not recall my real memory.
```

The installer tries to install the workflow skill where the client supports skills, then registers the `yifanchen-zhiyi` MCP connection where the platform can use MCP. Skill installation is an intent signal; real recall still goes through the local MCP tool, and chat-body parsing stays behind a separate authorization gate.

## Why It Exists

AI coding and agent tools still forget too easily. You explain a preference in Claude Desktop, debug a project in Codex, test a workflow in OpenClaw, and the next window starts from zero.

Memcore Cloud keeps the useful trail on your own machine: original conversations, source refs, corrections, work experience, and platform facts. It helps the tools you already use pick up the thread, while keeping platform boundaries visible instead of flattening every agent into one blob.

## Quick Install

macOS / Linux / WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

After install, use `mode=capability_check` to verify the skill/MCP/read-only path without recalling real memory.

## Safe Test Checklist

Start with capability check mode. A successful first test should report `read_only: true`, `recall_performed: false`, `raw_excerpt_returned: false`, and `mcp_tools: ["zhiyi_recall"]`.

Then open `http://127.0.0.1:9850` and check whether your local tools are detected. Memcore Cloud can show what it sees locally, which tools already have a usable connection, and which ones need one more authorization step. This check does not write platform config, parse chat bodies, or recall real memory.

## Check What It Found

The local page can show which AI tools are already on this machine, which ones are ready for a safe capability check, and which ones need one more permission step before they connect.

Memcore Cloud keeps Claude Desktop and Claude Code CLI separate. It can also recognize Codex, OpenClaw, Hermes, Cursor-style tools, and newer local agents from the settings they already keep on the machine. Seeing a tool is not the same as reading its chats.

When a tool can be connected, Memcore Cloud shows the next step before anything changes: where it would connect, whether a restart is needed, how to roll back, and what safe check should run afterward.

Only run real recall after you explicitly choose to test memory retrieval. Installing a skill, seeing a detected platform, or finding a Claude Desktop store is not treated as permission to read conversation bodies.

## What Makes It Different

- **It keeps the receipts**: original saved records stay as the highest fact; summaries do not replace source text.
- **It can explain why it remembered something**: recall keeps the reason trail visible.
- **It meets tools where they are**: Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and newer local agents can sit around the same memory core without getting mixed together.
- **It asks before crossing lines**: discovery is read-only by default. Installing a skill can signal intent, but writing platform config or reading chat bodies needs explicit authorization.
- **It separates knowing from doing**: Zhiyi captures preference and intent; Xingce captures work experience and validation paths. Experience is not a skill library.

## The Idea

Conversations with AI are easy to lose.

You explain a preference today, repeat it tomorrow, and start over again when you switch tools. The useful part is not only one answer. It is the trail of decisions, habits, context, examples, and corrections that gradually describe how you work.

Memcore Cloud keeps that trail on your own machine. You keep chatting in OpenClaw, Hermes, Codex, Claude Desktop, and other tools as usual. Yifanchen stays in the background as the Chinese codename, preserves the original conversation records, and turns them into experience you can revisit.

## What It Does

- **Preserves saved content** across source records, Zhiyi experience, recalled context, and usage records, without redaction, rewriting, or hash-only replacement.

  > Yifanchen's rule is simple: the words you said are the highest fact. Organizing can happen, recall can happen, and Zhiyi and Xingce can grow experience from it; but any compression that replaces the original words is pollution. Six months later, the original sentence should still be there.
- **Organizes preference and intent experience** such as user habits, recurring preferences, corrections, and what a request usually means.
- **Builds work experience** from previous work, mistakes, corrections, and checks, so future agents have a better path to follow.
  Experience is not the same as a callable function or a skill library. Zhiyi keeps preference and intent experience; Xingce keeps work experience such as what to check first, which project boundary not to cross, and how to validate a fix next time.
- **Works quietly** with OpenClaw, Hermes, Codex, and Claude Desktop through their normal surfaces.
- **Feeds raw pointers to Hermes**: when Hermes native review is triggered, Hermes can read Yifanchen raw/source-ref pointers and inspect the original material itself. Yifanchen emits the self-review signal and observes native feedback; it does not write Hermes skills directly.
  Starting in 2026.5.31, that self-review signal has a wake dry-run and authorized receipt gate, so Yifanchen can record that a signal was produced without claiming Hermes has run `background_review` or generated a skill.
- **Treats Claude Desktop as first-class**: Claude Desktop is detected separately from Claude Code CLI. It can consume Yifanchen through local MCP / Desktop Extensions; installing the generic skill is a signal, not a working local-memory tool by itself. As a source system, Yifanchen builds a local sync manifest and sync-state receipt for config, IndexedDB, Local Storage, Session Storage, skill manifests, and logs. Readers and UI panels can aggregate all Claude surfaces under `claude_all`; on Windows, records created through a relay service or Claude Code runtime still keep dual attribution and isolation boundaries in source_refs: `storage_owner`, `conversation_origin`, and `runtime_consumer` are separate, and this does not mean official login chats and relay chats can read each other. Official export archives are cold-start/backfill fallback only, not the normal sync path; content parsing needs a separate authorized parser gate.
- **Captures incrementally** from growing local session files, continuing from saved offsets instead of starting over every time.
- **Provides a local page** at `http://127.0.0.1:9850` for status, model settings, and generated experience.
- **Runs across platforms** on macOS, Linux, Windows, and WSL.

## Current Release: 2026.6.1

2026.6.1 is the current published release of Memcore Cloud.

- **Natural-language correction entry**: user corrections such as "this memory is wrong" become review-only errata candidates instead of durable preference memories.
- **Agent install loop**: README now includes a prompt users can send directly to a local AI agent; installers try to connect Codex skill, Codex MCP, OpenClaw, Hermes, and the Claude Desktop MCP bridge automatically.
- **Computer-first raw archive contract**: starting with 2026.6.1, new installs and new raw writes use `memory/{computer_name}/{source_system}/{native_artifact_format}/...`. Older source-system-first archives stay readable, but the legacy layout is no longer created for new records.
- **Hermes status visibility**: adds learning liveness, consumption receipts, and skill-experience diff. Yifanchen provides raw/source-ref pointers and observes native feedback; it does not write Hermes skills directly.
- **Claude Desktop source registration**: adds Claude Desktop source-system detection, consumer-side readiness diagnostics, a local sync manifest, and sync-state receipts. Readers can aggregate under `claude_all`, while source refs keep Windows relay / Claude Code dual attribution and isolation boundaries; repeated manual export is not treated as the daily sync design.
- **State Ledger and Context Budget Units**: review-only checks help later sessions find the latest trusted judgment and carry compact, source-backed context forward.
- **Read-only model facts**: Yifanchen reads existing OpenClaw, Hermes, and Codex model configuration for its own checks. It does not write back to platforms or become a model center.

See [RELEASE_NOTES_2026.6.1.md](RELEASE_NOTES_2026.6.1.md) for the current release, [UPDATE_HISTORY.md](UPDATE_HISTORY.md) for historical highlights, and [CHANGELOG.md](CHANGELOG.md) for engineering changes.

## What Is Zhiyi

Zhiyi is the part of Yifanchen that tries to understand intent, not just store text.

It is not a search box and not a plain summary. It looks at repeated conversations and turns them into reusable preference and intent experience: user preferences, wording habits, corrections, recurring boundaries, and context that should not need to be explained again.

In daily use, you still chat in OpenClaw, Hermes, Codex, or Claude Desktop. Yifanchen works quietly in the background. When you open the local page, the interesting part should be the new experience it found, whether it feels right, and whether you want to keep or delete it.

When you want a new window to pick up the thread, start with `/zhiyi`. English aliases such as `/memory`, `/recall`, and `/continue` also work, as do natural phrases like `catch me up`. These are entry intents only; they do not change how original records are preserved.

## What Is Xingce

Zhiyi means "understanding the intent." It helps the machine know who you are, what you meant before, what you corrected, and where the current work left off.

Xingce means "knowing how to act." It is the work-experience layer. It does not replace the user's final decision and does not turn memory into vague advice. It learns from previous work, failures, corrections, and checks, then turns that evidence into reviewable next steps an agent can use.

Zhiyi now behaves more like a local archivist: each experience can carry a catalog id, status, and source anchors, so it can return to the original words instead of relying on an unattributed summary. Xingce is closer to a workbench: it turns source-backed work history into paths for what to check, what to avoid, and how to continue.

This is why Xingce is not described as a skill system. A skill is an entry rule or workflow for an AI tool. Experience is often not `f(input) -> output`. Zhiyi keeps preference and intent experience; Xingce keeps work experience. If a preference affects a task, the preference still belongs to Zhiyi; Xingce may cite it inside a concrete work path, but it does not rename preference into work experience.

Together, Zhiyi sees clearly and Xingce follows through. That is the product meaning of "knowing and doing as one": memory is not only kept; it becomes useful inside the work.

## Zhixing Library

The Zhixing Library is the shared library layer for Zhiyi and Xingce.

Raw memory is the source text and is never replaced by Zhiyi or Xingce. Zhiyi is the understanding shelf: user preferences, wording habits, corrections, intent, and background. Xingce is the work-experience and toolbook shelf: work paths, project boundaries, troubleshooting order, gotchas, and validation methods.

Each library record should be able to answer: what is its library id, which original source backs it, which shelf it belongs to, whether it is a candidate or adopted, whether it conflicts with another record, when it was last verified, and where it applies or should not be used. Toolbooks follow the same rule: external docs and platform probe logs should first land under `raw/external_docs/` or `raw/probe_logs/`, then become toolbook records.

For example, a platform probe such as "this tool reads profile config immediately, and case-sensitive systems only recognize the official uppercase filename" should first preserve the relevant command output or official documentation excerpt, then become a toolbook candidate. That keeps it as a source-backed platform fact instead of a model-written impression.

The next product line is therefore: Zhiyi can return to sources, Xingce can be validated, recall can explain itself, and results can be replayed. The Zhixing loop moves through seven steps: preserve raw, return to Zhiyi sources, shape Xingce work experience, add toolbook facts, handle errata, replay, then feed validated experience into later recall or action. Replay scoring should prefer deterministic checks such as expected sources, behavior markers, repeated-mistake blockers, required acceptance checks, and proactive resurfacing, not AI self-judging. The current feedback step creates adoption, errata, and proactive-resurfacing candidates for review; authorized apply writes a review receipt only, not adopted experience.

The first toolbook path is intentionally review-only. It can turn a platform fact, environment difference, command result, or source excerpt into a candidate, but it does not quietly write that candidate into the library.

Starting in 2026.5.31, State Ledger and Context Budget Units follow the same rule: they help later sessions understand the latest trusted judgment and carry compact context forward, while keeping adoption as an explicit review step.

## Using Zhiyi From AI Tools

AI tools that support skills, MCP, or custom system instructions can use the generic Zhiyi skill in this repository:

```text
system/skills/yifanchen-zhiyi
```

The skill defines when to call Zhiyi and how to answer with sources. MCP or a native platform plugin is the connection layer to the local Yifanchen service. It is not Codex-only, and it does not turn Yifanchen into a skill library; the deeper layer is source-backed preference experience from Zhiyi and work experience from Xingce.

For install or smoke tests, do not use `/zhiyi` as a capability check. It may run real recall against local memory. Ask the client to call `zhiyi_recall` with:

```json
{"query":"capability check","mode":"capability_check"}
```

This mode reports service, tool, version, and read-only availability only. It does not query memory, return source refs, or return raw excerpts.

## Install

### Ask Your AI Agent To Install It

If you use Codex, OpenClaw, Hermes, Claude Code CLI, or another AI agent that can operate your local terminal, you can send it this prompt:

```text
Please install Memcore Cloud (Yifanchen) from https://github.com/strmforge/memcore-cloud on this machine.
After installation, start the local services. Automatically install the Codex skill. If Codex CLI is available, automatically register the Codex MCP server named yifanchen-zhiyi at http://127.0.0.1:9851/mcp.
If OpenClaw, Hermes, or Claude Desktop is available, use the installer defaults to connect them too; Claude Desktop needs the local MCP bridge registration before it can actually query Memcore Cloud.
Finish with capability check mode only; do not recall my real memory.
```

The installer tries to connect the local tools for you: OpenClaw plugin, Hermes provider, Codex skill, Codex MCP, and Claude Desktop MCP bridge are installed according to platform capability, so users do not need to understand Skill or MCP first. The Codex skill gives new Codex sessions a clear anchor: Memcore Cloud is the local memory library. After Codex or Claude Desktop MCP registration succeeds, a new session can see `yifanchen-zhiyi` / `zhiyi_recall`; an already-open session may need to be reopened before the new connection is loaded.

### macOS / Linux / WSL

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Then open:

```text
http://127.0.0.1:9850
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

Press Enter on first run to use the recommended install location.

## Update

If Yifanchen is already installed, use the local page first:

1. Open `http://127.0.0.1:9850`.
2. Go to Settings & Update.
3. Click Check for updates.
4. If a new version is available, click One-click update.

One-click update backs up app files before replacing them. Local data such as `memory/`, `raw/`, `zhiyi/`, `config/`, `logs/`, and `backups/` is kept.

If the local page cannot open, rerun the installer as a repair install:

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows:

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

## Uninstall

### macOS / Linux

```bash
~/.memcore-cloud/uninstall.sh
```

### Windows

```powershell
.\uninstall.ps1
```

Uninstalling removes the app files only. Local data such as `memory/`, `raw/`, `zhiyi/`, and `config/` is kept.

## Documentation

- [Why Yifanchen](INTRODUCTION.md)
- [Wiki](https://github.com/strmforge/memcore-cloud/wiki)
- [First use](https://github.com/strmforge/memcore-cloud/wiki/%E7%AC%AC%E4%B8%80%E6%AC%A1%E4%BD%BF%E7%94%A8)
- [Zhiyi](https://github.com/strmforge/memcore-cloud/wiki/%E7%9F%A5%E6%84%8F)
- [Update history](UPDATE_HISTORY.md)

## Supported Sources

- **OpenClaw**: memory support for the usual chat entry.
- **Hermes**: read-only access to the local memory base when available; when Hermes native review is triggered and creates skill/learning changes, Yifanchen can observe them after the self-review signal and record the result.
- **Codex**: reads local Codex session records and turns them into traceable experience.
- **Claude Desktop**: can consume Zhiyi through local MCP / Desktop Extensions; as a source it is listed through a local sync manifest and sync-state receipt. Readers can aggregate under `claude_all`, while Windows relay / Claude Code related records keep attribution and isolation boundaries, with official exports kept as cold-start/backfill fallback only.
- **Skill / MCP clients**: can use the generic Zhiyi rules and read-only recall entry.
- **Local files**: keeps the basic local-record path available.

## Version

Current release: **2026.6.1**

See [RELEASE_NOTES_2026.6.1.md](RELEASE_NOTES_2026.6.1.md) for the latest published release, [UPDATE_HISTORY.md](UPDATE_HISTORY.md) for historical highlights, and [CHANGELOG.md](CHANGELOG.md) for engineering changes.

## License

[MIT](LICENSE)
