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
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.5.29">2026.5.29</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.5.29-2f5f9b">
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
- **Captures incrementally** from growing local session files, continuing from saved offsets instead of starting over every time.
- **Provides a local page** at `http://127.0.0.1:9850` for status, model settings, and generated experience.
- **Runs across platforms** on macOS, Linux, Windows, and WSL.

## New In 2026.5.29

- **Zhixing Library**: raw records are the source texts, Zhiyi is the understanding shelf, and Xingce is the work-experience and toolbook shelf.
- **Explainable recall**: recall results can include `library_id`, shelf, source refs, match method, and rank reason.
- **Production-shaped Xingce objects**: work-experience candidates now carry scenario, action strategy, avoid conditions, acceptance checks, scope, and lifecycle status.
- **Light typed graph and hybrid recall contract**: starts with user, project, platform, task, preference, and work-experience nodes, then combines source refs, keyword matching, vector readiness, and project/time filters.
- **Replay plan**: adds a read-only plan for comparing no memory, Zhiyi only, and Zhiyi plus Xingce on the same task set.
- **Zhixing loop dry-run**: a seven-step flow crosses the five shelves, checks four defensive metrics plus one offensive metric, and produces review-only feedback candidates instead of writing adopted experience automatically.
- **Explainable usage receipts**: each recall can report which library ids and source refs were used, why they matched, and that no platform write happened.
- **Toolbook candidate entry**: platform facts, environment differences, and command probes can be shaped into toolbook candidates; this first entry is dry-run / validate only.
- **Codex local support**: reads local Codex session records into the same local memory base.
- **Universal Zhiyi entry**: use `/zhiyi` to pick up a thread in a new window; English users can also use `/memory`, `/recall`, `/continue`, or `catch me up`.
- **Skill / MCP access**: includes the platform-neutral `yifanchen-zhiyi` skill and a read-only `zhiyi_recall` recall entry.
- **Capability check mode**: install and smoke tests can use `mode=capability_check` to verify Skill / MCP / read-only status without running recall or returning source text.
- **Shared local memory base**: OpenClaw, Hermes, and Codex can benefit from the same original records while their agents and windows remain scoped.
- **Incremental and resumable reading**: growing session files continue from saved offsets, and older source lookup can resume in segments.
- **Traceable experience**: Zhiyi experiences can carry catalog ids, lifecycle status, and source anchors.
- **Clearer Xingce wording**: Xingce is documented as the work-experience layer that turns prior work into reviewable next steps.
- **Local gateway hardening**: the read-only recall gateway explicitly accepts loopback clients only and guards cursor-state writes from platform config folders.

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

Raw memory is the source text and is never replaced by Zhiyi or Xingce. Zhiyi is the understanding shelf: user preferences, wording habits, corrections, intent, and background. Xingce is the toolbook shelf: work paths, project boundaries, troubleshooting order, gotchas, and validation methods.

Each library record should be able to answer: what is its library id, which original source backs it, which shelf it belongs to, whether it is a candidate or adopted, whether it conflicts with another record, when it was last verified, and where it applies or should not be used. Toolbooks follow the same rule: external docs and platform probe logs should first land under `raw/external_docs/` or `raw/probe_logs/`, then become toolbook records.

For example, a platform probe such as "this tool reads profile config immediately, and case-sensitive systems only recognize the official uppercase filename" should first preserve the relevant command output or official documentation excerpt, then become a toolbook candidate. That keeps it as a source-backed platform fact instead of a model-written impression.

The next product line is therefore: Zhiyi can return to sources, Xingce can be validated, recall can explain itself, and results can be replayed. The Zhixing loop moves through seven steps: preserve raw, return to Zhiyi sources, shape Xingce work experience, add toolbook facts, handle errata, replay, then feed validated experience into later recall or action. Replay scoring should prefer deterministic checks such as expected sources, behavior markers, repeated-mistake blockers, required acceptance checks, and proactive resurfacing, not AI self-judging. The current feedback step creates adoption, errata, and proactive-resurfacing candidates for review; authorized apply writes a review receipt only, not adopted experience.

The first toolbook entry path is intentionally non-writing. `/api/v1/zhixing/toolbook-candidates/dry-run` builds a candidate from platform, environment, observed behavior, source excerpt, and raw source path. `/api/v1/zhixing/toolbook-candidates/validate` checks the same evidence contract. Neither endpoint writes raw records, Zhiyi, Xingce, toolbooks, or platform config.

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

## Supported Sources

- **OpenClaw**: memory support for the usual chat entry.
- **Hermes**: read-only access to the local memory base when available.
- **Codex**: reads local Codex session records and turns them into traceable experience.
- **Skill / MCP clients**: can use the generic Zhiyi rules and read-only recall entry.
- **Local files**: keeps the basic local-record path available.

## Version

Current version: **2026.5.29**

See [CHANGELOG.md](CHANGELOG.md) for changes.

## License

[MIT](LICENSE)
