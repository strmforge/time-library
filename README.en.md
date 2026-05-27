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
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.5.28">2026.5.28</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.5.28-2f5f9b">
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
- **Organizes experience** such as examples, preferences, and recurring issues.
- **Builds action experience** from previous work, mistakes, corrections, and checks, so future agents have a better path to follow.
- **Works quietly** with OpenClaw, Hermes, and Codex through their normal surfaces.
- **Captures incrementally** from growing local session files, continuing from saved offsets instead of starting over every time.
- **Provides a local page** at `http://127.0.0.1:9850` for status, model settings, and generated experience.
- **Runs across platforms** on macOS, Linux, Windows, and WSL.

## New In 2026.5.28

- **Codex local support**: reads local Codex session records into the same local memory base.
- **Universal Zhiyi entry**: use `/zhiyi` to pick up a thread in a new window; English users can also use `/memory`, `/recall`, `/continue`, or `catch me up`.
- **Skill / MCP access**: includes the platform-neutral `yifanchen-zhiyi` skill and a read-only `zhiyi_recall` recall entry.
- **Shared local memory base**: OpenClaw, Hermes, and Codex can benefit from the same original records while their agents and windows remain scoped.
- **Incremental and resumable reading**: growing session files continue from saved offsets, and older source lookup can resume in segments.
- **Traceable experience**: Zhiyi experiences can carry catalog ids, lifecycle status, and source anchors.
- **Clearer Xingce wording**: Xingce is documented as the action-experience layer that turns prior work into reviewable next steps.

## What Is Zhiyi

Zhiyi is the part of Yifanchen that tries to understand intent, not just store text.

It is not a search box and not a plain summary. It looks at repeated conversations and turns them into reusable experience: preferences, project context, examples, corrections, and habits that should not need to be explained again.

In daily use, you still chat in OpenClaw, Hermes, or Codex. Yifanchen works quietly in the background. When you open the local page, the interesting part should be the new experience it found, whether it feels right, and whether you want to keep or delete it.

When you want a new window to pick up the thread, start with `/zhiyi`. English aliases such as `/memory`, `/recall`, and `/continue` also work, as do natural phrases like `catch me up`. These are entry intents only; they do not change how original records are preserved.

## What Is Xingce

Zhiyi means "understanding the intent." It helps the machine know who you are, what you meant before, what you corrected, and where the current work left off.

Xingce means "knowing how to act." It is the action-experience layer. It does not replace the user's final decision and does not turn memory into vague advice. It learns from previous work, failures, corrections, and checks, then turns that evidence into reviewable next steps an agent can use.

Zhiyi now behaves more like a local archivist: each experience can carry a catalog id, status, and source anchors, so it can return to the original words instead of relying on an unattributed summary. Xingce is closer to a workbench: it turns source-backed understanding into paths for what to check, what to avoid, and how to continue.

Together, Zhiyi sees clearly and Xingce follows through. That is the product meaning of "knowing and doing as one": memory is not only kept; it becomes useful inside the work.

## Using Zhiyi From AI Tools

AI tools that support skills, MCP, or custom system instructions can use the generic Zhiyi skill in this repository:

```text
system/skills/yifanchen-zhiyi
```

The skill defines when to call Zhiyi and how to answer with sources. MCP or a native platform plugin is the connection layer to the local Yifanchen service. It is not Codex-only; the same behavior can be used by Hermes, OpenClaw, Claude, or another local agent entry point.

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

Current version: **2026.5.28**

See [CHANGELOG.md](CHANGELOG.md) for changes.

## License

[MIT](LICENSE)
