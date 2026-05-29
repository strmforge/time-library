# Yifanchen 2026.5.30

This release tightens the 2026.5.29 Zhixing Library work with a real-task
benchmark dry-run and a safer preference-extraction gate.

## What's New

- Added `/api/v1/zhixing/benchmark/plan` and `/api/v1/zhixing/benchmark/dry-run` for multi-case deterministic benchmark dry-runs.
- The benchmark compares `no_memory`, `zhiyi_only`, and `zhiyi_plus_xingce` before any Replay feedback queue or adoption flow is built.
- Added a public-safe real-task fixture covering source-backed handoff, proactive resurfacing, toolbook source rules, connector boundaries, and public documentation boundaries.
- Added a precision-first P2 preference intent gate: repairs, deictic disambiguation, relayed audit/task text, and creative prompts are routed away from durable `preference_memory` unless they carry a clear preference signal.
- Bumped runtime-visible versions for the Web console, Zhixing Library, raw MCP gateway, installers, and the `yifanchen-zhiyi` skill to `2026.5.30`.
- Verified the construction build on a Windows local service with health, Replay/benchmark plans, MCP initialize, OpenClaw raw query, source-ref sampling, and error-log checks.

## Notes

- The benchmark is a dry-run evaluation surface, not a claim that the feedback queue is ready.
- Replay feedback apply remains review-only and does not write adopted production experience.
- Local memory, Zhiyi records, raw records, logs, output, backups, and local configuration stay outside update payloads.

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
