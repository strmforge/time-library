# Yifanchen 2026.5.28

This release adds a lighter way for AI clients to call Zhiyi.

## What's New

- Zhiyi now has an initial archive-catalog layer with stable catalog ids, archive cards, source-aware evidence output, and an archivist-style prompt.
- Xingce is now described as the action-experience layer: it turns previous work, failures, corrections, and checks into reviewable next steps.
- Zhiyi can be requested with `/zhiyi`; English aliases such as `/memory`, `/recall`, `/continue`, and natural phrases like "catch me up" are supported as entry intents.
- A platform-neutral `yifanchen-zhiyi` skill package is included for AI clients that support skills, MCP, plugins, or custom system instructions.
- The local raw memory gateway exposes a read-only MCP-compatible `zhiyi_recall` tool for source-backed recall.
- Codex local session records can enter the same local memory base used by OpenClaw and Hermes.
- Growing session files are read incrementally from saved offsets, with segmented resume for older source lookup.
- Saved content remains unchanged across platform records, Zhiyi experience, recalled context, and usage records: no redaction, no rewriting, no hash-only replacement.
- The original words remain the highest fact. Summaries and experience can help, but any compression that replaces the original words is pollution.
- The raw gateway now rejects non-loopback clients explicitly and guards its cursor-state directory against accidental writes into platform config folders.

## Update

Open `http://127.0.0.1:9850`, go to Settings & Update, then use Check for updates and One-click update.

If the local page cannot open, rerun the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows:

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```
