# Yifanchen

<p align="center">
  <img src="assets/brand/yifanchen-logo.jpg" alt="Yifanchen" width="220"/>
</p>

<p align="center">
  <strong>Keep the conversations that matter close to you.</strong>
</p>

<p align="center">
  A local personal AI memory center. It preserves conversations as they are, quietly organizes useful experience, and helps your everyday AI tools feel more familiar over time.
</p>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.5.31">2026.5.31</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.5.31-2f5f9b">
  <img alt="Platforms" src="https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-ready-247447">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-memory-b07d35">
</p>

## The Idea

Conversations with AI are easy to lose.

You explain a preference today, repeat it tomorrow, and start over again when you switch tools. The useful part is not only one answer. It is the trail of decisions, habits, context, examples, and corrections that gradually describe how you work.

Yifanchen keeps that trail on your own machine. You keep chatting in OpenClaw, Hermes, Codex, and other tools as usual. Yifanchen stays in the background, preserves the original conversation records, and turns them into experience you can revisit.

## What It Does

- **Preserves saved content** across source records, Zhiyi experience, recalled context, and usage records, without redaction, rewriting, or hash-only replacement.

  > Yifanchen's rule is simple: the words you said are the highest fact. Organizing can happen, recall can happen, and Zhiyi and Xingce can grow experience from it; but any compression that replaces the original words is pollution. Six months later, the original sentence should still be there.
- **Organizes preference and intent experience** such as user habits, recurring preferences, corrections, and what a request usually means.
- **Builds work experience** from previous work, mistakes, corrections, and checks, so future agents have a better path to follow.
  Experience is not the same as a callable function or a skill library. Zhiyi keeps preference and intent experience; Xingce keeps work experience such as what to check first, which project boundary not to cross, and how to validate a fix next time.
- **Works quietly** with OpenClaw, Hermes, and Codex through their normal surfaces.
- **Feeds raw pointers to Hermes**: when Hermes native review is triggered, Hermes can read Yifanchen raw/source-ref pointers and inspect the original material itself. Yifanchen emits the self-review signal and observes native feedback; it does not write Hermes skills directly.
  Starting in 2026.5.31, that self-review signal has a wake dry-run and authorized receipt gate, so Yifanchen can record that a signal was produced without claiming Hermes has run `background_review` or generated a skill.
- **Captures incrementally** from growing local session files, continuing from saved offsets instead of starting over every time.
- **Provides a local page** at `http://127.0.0.1:9850` for status, model settings, and generated experience.
- **Runs across platforms** on macOS, Linux, Windows, and WSL.

## Latest Release: 2026.5.31

- **Natural-language correction entry**: user corrections such as "this memory is wrong" become review-only errata candidates instead of durable preference memories.
- **Agent install loop**: README now includes a prompt users can send directly to a local AI agent; installers try to connect Codex skill, Codex MCP, OpenClaw, and Hermes automatically.
- **Hermes status visibility**: adds learning liveness, consumption receipts, and skill-experience diff. Yifanchen provides raw/source-ref pointers and observes native feedback; it does not write Hermes skills directly.
- **State Ledger and Context Budget Units**: read-only dry-runs inspect the latest trusted judgment and shape source-backed, composable `context_budget_unit_candidate` records.
- **Read-only model facts**: Yifanchen reads existing OpenClaw, Hermes, and Codex model configuration for its own checks. It does not write back to platforms or become a model center.

See [UPDATE_HISTORY.md](UPDATE_HISTORY.md) for historical highlights, [CHANGELOG.md](CHANGELOG.md) for engineering changes, and [RELEASE_NOTES_2026.5.31.md](RELEASE_NOTES_2026.5.31.md) for the full current release notes.

## What Is Zhiyi

Zhiyi is the part of Yifanchen that tries to understand intent, not just store text.

It is not a search box and not a plain summary. It looks at repeated conversations and turns them into reusable preference and intent experience: user preferences, wording habits, corrections, recurring boundaries, and context that should not need to be explained again.

In daily use, you still chat in OpenClaw, Hermes, or Codex. Yifanchen works quietly in the background. When you open the local page, the interesting part should be the new experience it found, whether it feels right, and whether you want to keep or delete it.

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

The first toolbook entry path is intentionally non-writing. `/api/v1/zhixing/toolbook-candidates/dry-run` builds a candidate from platform, environment, observed behavior, source excerpt, and raw source path. `/api/v1/zhixing/toolbook-candidates/validate` checks the same evidence contract. Neither endpoint writes raw records, Zhiyi, Xingce, toolbooks, or platform config.

Starting in 2026.5.31, State Ledger and Context Budget Unit entries are also contract-first and non-writing. `/api/v1/zhixing/state-ledger/plan` and `/api/v1/zhixing/state-ledger/dry-run` inspect latest trusted judgment and timeline state. `/api/v1/zhixing/context-units/contract` and `/api/v1/zhixing/context-units/dry-run` shape review-only `context_budget_unit_candidate` records. These endpoints do not write raw records, Zhiyi, Xingce, toolbooks, errata, or platform config.

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

If you use Codex, OpenClaw, Hermes, Claude Code, or another AI agent that can operate your local terminal, you can send it this prompt:

```text
Please install Yifanchen from https://github.com/strmforge/memcore-cloud on this machine.
After installation, start the local services. Automatically install the Codex skill. If Codex CLI is available, automatically register the Codex MCP server named yifanchen-zhiyi at http://127.0.0.1:9851/mcp.
If OpenClaw or Hermes is available, use the installer defaults to connect them too.
Finish with capability check mode only; do not recall my real memory.
```

The installer tries to connect the local tools for you: OpenClaw plugin, Hermes provider, Codex skill, and Codex MCP are installed according to platform capability, so users do not need to understand Skill or MCP first. The Codex skill gives new Codex sessions a clear anchor: Yifanchen is the local memory library. After Codex MCP registration succeeds, a new Codex session can see `yifanchen-zhiyi` / `zhiyi_recall`; an already-open session may need to be reopened before the new connection is loaded.

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
- **Skill / MCP clients**: can use the generic Zhiyi rules and read-only recall entry.
- **Local files**: keeps the basic local-record path available.

## Version

Current version: **2026.5.31**

See [RELEASE_NOTES_2026.5.31.md](RELEASE_NOTES_2026.5.31.md) for the current release, [UPDATE_HISTORY.md](UPDATE_HISTORY.md) for historical highlights, and [CHANGELOG.md](CHANGELOG.md) for engineering changes.

## License

[MIT](LICENSE)
