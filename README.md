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
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.6.2">2026.6.2</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.6.2-2f5f9b">
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
- **Local discovery that stays quiet**: the local page can show which AI tools are present, which ones are ready for a safe capability check, and which ones need permission first.

## Paste This To Your Local Agent

If you use Codex, Claude Code CLI, OpenClaw, Hermes, or another local agent that can run terminal commands, paste this prompt into it:

```text
You are installing Memcore Cloud for me on this machine.
Repository: https://github.com/strmforge/memcore-cloud

Install and start Memcore Cloud. Then install the Memcore Cloud Zhiyi skill or custom instruction in this agent if the platform supports skills, and register the MCP tool named yifanchen-zhiyi at http://127.0.0.1:9851/mcp if the platform supports MCP.

After setup, run only a safe capability check with zhiyi_recall:
{"query":"capability check","mode":"capability_check"}
Do not recall my real memory yet; do not recall my real memory until I ask.

From then on, treat Memcore Cloud as my local memory. Before answering anything about previous decisions, corrections, project boundaries, forgotten context, install/test/release status, or "what next" in an ongoing project, call zhiyi_recall first and use source refs or raw excerpts when available. If the skill is installed but zhiyi_recall is not available, tell me the MCP/tool connection is missing instead of guessing from memory.
```

Chinese prompt:

```text
你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）。
仓库：https://github.com/strmforge/memcore-cloud

请安装并启动 Memcore Cloud。然后，如果这个平台支持 skill 或自定义指令，请安装 Memcore Cloud Zhiyi skill；如果这个平台支持 MCP，请注册名为 yifanchen-zhiyi 的 MCP 工具，地址是 http://127.0.0.1:9851/mcp。

安装完成后，只做一次安全能力检查：
{"query":"capability check","mode":"capability_check"}
先不要召回我的真实记忆。

以后请把 Memcore Cloud 当成我的本机记忆。凡是我问到之前的决定、纠错、项目边界、你忘了什么、安装/测试/发布状态，或者在持续项目里问“下一步/接下来呢/还有吗”，请先调用 zhiyi_recall，再结合 source_refs / raw_excerpt 回答。如果 skill 已安装但 zhiyi_recall 不可用，请告诉我 MCP/工具连接还没接上，不要凭印象猜。
```

The installer tries to add the workflow skill where skills are supported, then registers `yifanchen-zhiyi` MCP where the platform supports MCP. Installing a skill is a connection signal, not permission to read chat bodies.

## Quick Install

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

WSL is only for development or advanced testing. Normal Windows installs should
use the Windows PowerShell command above.

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
- which ones can run a safe capability check;
- which ones need permission before deeper access;
- whether a tool looks recently used or has been quiet for a while;
- where new raw records are being stored.

This page is read-only for platform data by default. It does not write app config, parse chat bodies, or recall real memory just because a tool was found.
Finding a tool means Memcore Cloud saw an entry point. It does not mean the tool is connected, readable, or ready for memory import.

## What Makes It Different

- **Source-backed memory**: recall can carry `source_refs`, raw excerpts, library ids, and rank reasons.
- **Zhiyi and Xingce**: Zhiyi keeps preference and intent experience; Xingce keeps work experience and validation paths. Experience is not a skill library.
- **Organized local records**: new records are grouped by computer first, then by the AI tool that produced them, so a multi-device setup can stay understandable.
- **Claude is handled carefully**: Claude Desktop and Claude Code CLI can both connect, but they remain separate surfaces. Official, relay, and CLI-related records keep attribution boundaries.
- **Hermes can inspect sources itself**: Memcore Cloud can provide raw/source-ref pointers and observe native feedback, while Hermes-owned skill changes remain Hermes-owned.

## Current Release: 2026.6.2

2026.6.2 is the current published release of Memcore Cloud.

- Claude can call the local `yifanchen-zhiyi` memory gateway through MCP and run real recall.
- Chinese `raw_excerpt` text is readable again in Claude recall.
- Windows Claude setup is steadier: no BOM config breakage, JSON-line bridge output, and regular / Store config paths are both covered.
- OpenClaw and Hermes records can show up together with source refs and attribution.
- Computer-first storage is visible in practice, so records are easier to browse by machine and source tool.
- The install prompt and skill now tell agents to call memory first for old decisions, corrections, project boundaries, install/test/release status, and next-step questions.
- Product-facing Wiki source pages are ready under `docs/wiki/`.

See [RELEASE_NOTES_2026.6.2.md](RELEASE_NOTES_2026.6.2.md) for the current release, [UPDATE_HISTORY.md](UPDATE_HISTORY.md) for older highlights, and [CHANGELOG.md](CHANGELOG.md) for lower-level changes.

## AI Tool Surfaces

- **Claude Desktop**: can use Memcore Cloud through local MCP / Desktop Extensions; source records stay behind explicit parsing authorization.
- **Claude Code CLI**: can use MCP while staying separate from Claude Desktop.
- **Codex**: can use the shared skill and MCP entry, and local sessions can become source-backed records.
- **OpenClaw**: can receive memory support through its normal local entry points.
- **Hermes**: can consume raw/source-ref pointers and produce native feedback without Memcore Cloud writing Hermes skills.
- **Other local AI tools**: can be recognized from local settings; safe checks come first, deeper access needs explicit permission.

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
