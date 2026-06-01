# Memcore Cloud

<p align="center">
  <img src="assets/brand/yifanchen-logo.jpg" alt="Memcore Cloud" width="220"/>
</p>

<p align="center">
  <strong>Local-first, source-backed memory for AI agents.</strong>
</p>

<p align="center">
  Memcore Cloud helps Claude Desktop, Codex, OpenClaw, Hermes, and other local AI tools remember what matters without replacing your original records with summaries.
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

**Memcore Cloud** is the English product name. **忆凡尘 / Yifanchen** remains the Chinese name and codename.

## Why People Use It

AI tools forget the small things that make work smooth: your preferred wording, project boundaries, old mistakes, useful fixes, and where a task left off. Memcore Cloud keeps that trail on your own machine so a new agent window does not have to start from zero.

It is not a hosted chat app and not a summary vault. It keeps source records, source refs, corrections, and work experience together so memory can point back to the original words.

## What You Get

- **Shared local memory for your AI tools**: Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and newer local agents can connect to the same memory base.
- **Receipts, not vibes**: remembered items keep source trails so you can check why something came back.
- **Original records stay original**: summaries can help navigation, but they do not replace saved source text.
- **Tool boundaries stay visible**: Claude Desktop and Claude Code CLI are treated separately; relay or official-login records are not silently mixed.
- **A safer first test**: capability check proves the local Skill/MCP path works without recalling real memory or returning raw excerpts.
- **Local discovery that stays quiet**: the local page can show which AI tools are present and which ones are ready to connect, without reading chat bodies by default.

## Copy This To Your Local Agent

If you use Codex, Claude Code CLI, OpenClaw, Hermes, or another local agent that can run terminal commands, paste this prompt into it:

```text
Please install Memcore Cloud (Yifanchen) from https://github.com/strmforge/memcore-cloud on this machine.
After installation, start the local services. Automatically install the Codex skill. If Codex CLI is available, automatically register the Codex MCP server named yifanchen-zhiyi at http://127.0.0.1:9851/mcp.
If OpenClaw, Hermes, or Claude Desktop is available, use the installer defaults to connect them too; Claude Desktop needs the local MCP bridge registration before it can actually query Memcore Cloud.
Finish with capability check mode only; do not recall my real memory.
```

Chinese prompt:

```text
请帮我在本机安装 Memcore Cloud（忆凡尘 / Yifanchen），仓库是 https://github.com/strmforge/memcore-cloud 。
安装完成后请启动本机服务；请自动安装 Codex skill；如果检测到 Codex CLI，请自动把 Codex MCP 接到 http://127.0.0.1:9851/mcp，MCP 名称用 yifanchen-zhiyi。
如果检测到 OpenClaw、Hermes 或 Claude Desktop，也请按安装器默认方式接入；Claude Desktop 需要注册本机 MCP bridge 才能真正查询 Memcore Cloud。
最后只做 capability check，不要召回我的真实记忆。
```

The installer tries to add the workflow skill where skills are supported, then registers `yifanchen-zhiyi` MCP where the platform supports MCP. Installing a skill is a connection signal, not permission to read chat bodies.

## Quick Install

macOS / Linux / WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

Then open:

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

## What The Local Page Shows

Open `http://127.0.0.1:9850` to see:

- which AI tools are present on this machine;
- which ones already have a usable connection;
- which ones need one more permission step;
- whether a tool looks recently used or has been quiet for a while;
- where new raw records are being stored.

This page is read-only for platform data by default. It does not write app config, parse chat bodies, or recall real memory just because a tool was found.

## What Makes It Different

- **Source-backed memory**: recall can carry `source_refs`, raw excerpts, library ids, and rank reasons.
- **Zhiyi and Xingce**: Zhiyi keeps preference and intent experience; Xingce keeps work experience and validation paths. Experience is not a skill library.
- **Organized local records**: new records are grouped by computer first, then by the AI tool that produced them, so a multi-device setup can stay understandable.
- **Claude is handled carefully**: Claude Desktop and Claude Code CLI can both connect, but they remain separate surfaces. Official, relay, and CLI-related records keep attribution boundaries.
- **Hermes can inspect sources itself**: Memcore Cloud can provide raw/source-ref pointers and observe native feedback, while Hermes-owned skill changes remain Hermes-owned.

## Current Release: 2026.6.1

2026.6.1 is the current published release of Memcore Cloud.

- English-first public name: **Memcore Cloud**.
- Local-agent install prompt is now near the top of the README.
- The local page can show detected AI tools and safe next steps.
- Claude Desktop and Claude Code CLI are treated as first-class, separate surfaces.
- New local records are grouped by computer first, then by source tool.
- The public page now focuses on what people can try today, while deeper sync work stays out of the first-screen story.

See [RELEASE_NOTES_2026.6.1.md](RELEASE_NOTES_2026.6.1.md) for the current release, [UPDATE_HISTORY.md](UPDATE_HISTORY.md) for older highlights, and [CHANGELOG.md](CHANGELOG.md) for lower-level changes.

## Supported Sources

- **Claude Desktop**: can use Memcore Cloud through local MCP / Desktop Extensions; source records stay behind explicit parsing authorization.
- **Claude Code CLI**: can connect through MCP while staying separate from Claude Desktop.
- **Codex**: can use the shared skill and MCP entry, and local sessions can become source-backed records.
- **OpenClaw**: can receive memory support through its normal local entry points.
- **Hermes**: can consume raw/source-ref pointers and produce native feedback without Memcore Cloud writing Hermes skills.
- **Other local AI tools**: can be detected from local settings and connected when the user authorizes the next step.

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
