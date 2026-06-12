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
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.6.12">2026.6.12</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.6.12-2f5f9b">
  <img alt="Platforms" src="https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-ready-247447">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-memory-b07d35">
</p>

**Memcore Cloud** is the English product name. **忆凡尘 / Yifanchen** remains the Chinese name and codename.

## Why People Use It

AI tools forget the small things that make work smooth: your preferred wording, project boundaries, old mistakes, useful fixes, and where a task left off. Memcore Cloud keeps that trail on your own machine so a new agent window does not have to start from zero.

It is not a hosted chat app and not a summary vault. It keeps source records, source refs, corrections, and work experience together so memory can point back to the original words.

## What You Get

- **Shared local memory for your AI tools**: Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and fast-moving open-source agents can connect to the same memory base.
- **Receipts, not vibes**: remembered items keep source trails so you can check why something came back.
- **Original records stay original**: summaries can help navigation, but they do not replace saved source text.
- **Tool boundaries stay visible**: Claude Desktop and Claude Code CLI are treated separately; relay or official-login records are not silently mixed.
- **A safer first test**: capability check proves the local Skill/MCP path works without recalling real memory or returning raw excerpts.
- **Install once, then it finds your tools**: Memcore Cloud discovers local AI tools, including popular open-source agents such as OpenCode, Goose, Aider, and OpenHands, connects supported Skill/MCP surfaces automatically, and keeps new memory sources in a computer-first archive.
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

Keep this rule active from now on. When my question depends on prior context, call zhiyi_recall before answering and use source refs or raw excerpts when available. Triggers include previous decisions, corrections, project boundaries, forgotten context, install/test/release status, and short follow-ups in ongoing work such as "next step", "what else", or "then what". Use active recall by default: current window/session first, then same project/workspace, same workstream/task, then stable preferences/tool facts. Use raw-pool/global only when I explicitly ask for that wider view. If explicit window-only recall says the current window/session is not bound yet, say that plainly; do not claim there is no memory. If the skill is installed but zhiyi_recall is not available, tell me the MCP/tool connection is missing instead of guessing from memory.
```

Chinese prompt:

```text
你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）。
仓库：https://github.com/strmforge/memcore-cloud

请安装并启动 Memcore Cloud。然后把 Memcore Cloud Zhiyi 安装成这个 agent 的长期记忆规则，不只是一次性安装说明。如果这个平台支持 skill 或自定义指令，请添加 Memcore Cloud Zhiyi skill/指令；如果这个平台支持 MCP，请注册名为 yifanchen-zhiyi 的 MCP 工具，地址是 http://127.0.0.1:9851/mcp。

安装完成后，只做一次安全能力检查：
{"query":"capability check","mode":"capability_check"}
先不要召回我的真实记忆。

以后请持续遵守这条规则。凡是我的问题依赖旧上下文，请先调用 zhiyi_recall，再结合 source_refs / raw_excerpt 回答。触发词包括：之前、定论、纠错、边界、忘了、安装/测试/发布状态，以及持续项目里的“下一步/接下来呢/还有吗/然后呢”。默认使用 active 召回：当前窗口/session 优先，然后同项目/同工作区、同工作流/同任务、稳定偏好/工具事实。只有我明确要求更宽视图时，才使用 raw-pool/global。如果显式 window-only 召回提示当前窗口/session 还没绑定，请直接说明这个绑定缺口；不要说没有记忆。如果 skill 已安装但 zhiyi_recall 不可用，请告诉我 MCP/工具连接还没接上，不要凭印象猜。
```

The installer adds the workflow skill where skills are supported, registers `yifanchen-zhiyi` MCP where the platform supports MCP, and keeps backup/receipt records for local config writes.

## Quick Install

macOS / Linux:

```bash
curl -fL -o memcore-cloud-install.sh https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.12/install.sh
bash memcore-cloud-install.sh
```

Windows PowerShell:

```powershell
iwr https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.12/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

Windows installs default to `%LOCALAPPDATA%\memcore-cloud`. To choose a path
before the install:

```powershell
$env:MEMCORE_INSTALL_DIR = "D:\Apps\memcore-cloud"
iwr https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.12/install.ps1 -OutFile .\install.ps1
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

## What The Local Page Shows

Open `http://127.0.0.1:9850` to see:

- which AI tools are present on this machine;
- which ones can run a safe capability check;
- which ones are already connected or ready for automatic Skill/MCP connection;
- whether a tool looks recently used or has been quiet for a while;
- where new raw records are being stored.

On Windows and macOS, the tray/menu bar icon gives you the same entry point
without remembering the port. The local watcher keeps running and can backfill
missed records after restart or repair.

Supported Skill/MCP surfaces can be connected automatically. Conversation import uses verified local formats, and capability check remains no-recall until an agent calls real recall.

## What Makes It Different

- **Source-backed memory**: recall can carry `source_refs`, raw excerpts, library ids, and rank reasons.
- **Zhiyi and Xingce**: Zhiyi keeps preference and intent experience; Xingce keeps work experience and validation paths. Experience is not a skill library.
- **A timeline you can trace back**: different tools leave different clues, but Memcore Cloud keeps them in one source-backed timeline. Raw records stay first; useful experience can settle into Zhiyi, Xingce, toolbook, or errata with source refs, collection ids, lifecycle state, and receipts.
- **Organized local records**: new records are grouped by computer first, then by the AI tool that produced them, so a multi-device setup can stay understandable.
- **Claude is handled carefully**: Claude Desktop and Claude Code CLI can both connect, but they remain separate surfaces. Official, relay, and CLI-related records keep attribution boundaries.
- **Hermes can inspect sources itself**: Memcore Cloud can provide raw/source-ref pointers and observe native feedback, while Hermes-owned skill changes remain Hermes-owned.

## Current Release: 2026.6.12

2026.6.12 is the current published release of Memcore Cloud.

- Public docs, catalogs, watchlists, diagnostics, and tests no longer expose a specific local relay product as a public dependency or platform entry.
- Existing personal relay traces remain compatible through neutral `local_relay` handling, without promoting that relay as required infrastructure.
- Record diagnostics keep lost source / lost raw wording instead of legacy stray-record wording.
- The release gate now scans public and repository text surfaces for removed relay names and legacy stray-record diagnostics.
- Installers, gateway health, active-memory routing, preflight metadata, local console version text, and the packaged Zhiyi skill report 2026.6.12 consistently.
- Windows install validation was rechecked on two Windows hosts; native smoke confirms the watcher, guardian, local services, no-recall capability check, and `codex_capture_status raw_sync=raw_current`.

See [RELEASE_NOTES_2026.6.12.md](RELEASE_NOTES_2026.6.12.md) for the current release, [UPDATE_HISTORY.md](UPDATE_HISTORY.md) for older highlights, and [CHANGELOG.md](CHANGELOG.md) for lower-level changes.

## AI Tool Surfaces

- **Claude Desktop**: can use Memcore Cloud through local MCP / Desktop Extensions; source records use verified local format collectors.
- **Claude Code CLI**: can use MCP while staying separate from Claude Desktop.
- **Codex**: can use the shared skill and MCP entry, and local sessions can become source-backed records.
- **OpenClaw**: can receive memory support through its normal local entry points.
- **Hermes**: can consume raw/source-ref pointers and produce native feedback without Memcore Cloud writing Hermes skills.
- **Other local AI tools**: can be recognized from local settings, app folders, package managers, and workspace markers; supported Skill/MCP surfaces can be connected automatically, and tools are promoted to memory sources once their local formats are verified.

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
