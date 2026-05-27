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
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.5.27">2026.5.27</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.5.27-2f5f9b">
  <img alt="Platforms" src="https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-ready-247447">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-memory-b07d35">
</p>

## The Idea

Conversations with AI are easy to lose.

You explain a preference today, repeat it tomorrow, and start over again when you switch tools. The useful part is not only one answer. It is the trail of decisions, habits, context, examples, and corrections that gradually describe how you work.

Yifanchen keeps that trail on your own machine. You keep chatting in OpenClaw, Hermes, Codex, and other tools as usual. Yifanchen stays in the background, preserves the original conversation records, and turns them into experience you can revisit.

## What It Does

- **Preserves saved content** across source records, Zhiyi experience, recalled context, and usage records, without redaction, rewriting, or hash-only replacement.
- **Organizes experience** such as examples, preferences, and recurring issues.
- **Works quietly** with OpenClaw, Hermes, and Codex through their normal surfaces.
- **Captures incrementally** from growing local session files, continuing from saved offsets instead of starting over every time.
- **Provides a local page** at `http://127.0.0.1:9850` for status, model settings, and generated experience.
- **Runs across platforms** on macOS, Linux, Windows, and WSL.

## What Is Zhiyi

Zhiyi is the part of Yifanchen that tries to understand intent, not just store text.

It is not a search box and not a plain summary. It looks at repeated conversations and turns them into reusable experience: preferences, project context, examples, corrections, and habits that should not need to be explained again.

In daily use, you still chat in OpenClaw, Hermes, or Codex. Yifanchen works quietly in the background. When you open the local page, the interesting part should be the new experience it found, whether it feels right, and whether you want to keep or delete it.

Zhiyi is about understanding you. Xingce is about knowing how to act. The first public version focuses on making experience visible, traceable, and able to grow over time.

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
- **Local files**: keeps the basic local-record path available.

## Version

Current version: **2026.5.27**

See [CHANGELOG.md](CHANGELOG.md) for changes.

## License

[MIT](LICENSE)
