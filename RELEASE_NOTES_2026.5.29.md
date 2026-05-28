# Yifanchen 2026.5.29

This release turns the first archive-catalog work into the Zhixing Library
Evidence Loop.

## What's New

- Added the Zhixing Library contract: raw records are source texts, Zhiyi is the preference and intent shelf, Xingce is the work-experience and toolbook shelf.
- Added stable `library_id`, `library_shelf`, `library_card`, `matched_by`, `rank_reason`, and typed-graph metadata to recall results.
- Expanded Xingce candidates into production-shaped work experience: scenario, action strategy, avoid conditions, acceptance checks, applicable scope, and lifecycle status.
- Added an evidence contract for experience records: source refs, verbatim excerpt, status, supersedes, and conflicts are explicit fields, and missing source text is reported instead of hidden.
- Added a Tool node type and a toolbook raw-source rule: toolbooks should come from `raw/external_docs/` or `raw/probe_logs/`.
- Added non-writing toolbook candidate dry-run and validation helpers for platform facts, environment differences, and command-probe findings.
- Added a read-only `/api/v1/zhixing/library` endpoint for the library manifest and current Xingce work-experience candidates.
- Added a read-only `/api/v1/zhixing/replay/plan` endpoint for future replay evaluation across no memory, Zhiyi only, and Zhiyi plus Xingce.
- Added a read-only `/api/v1/zhixing/loop` contract and `/api/v1/zhixing/replay/dry-run` deterministic runner.
- Replay scoring is defined as deterministic rule checks first, not AI self-judging.
- Replay now includes the offensive `proactive_resurfacing` metric: surfacing a past successful pattern the user did not explicitly ask for.
- Replay dry-run now emits review-only feedback candidates for adoption, errata, and proactive resurfacing; it still performs no production experience write.
- Added an authorized replay feedback apply gate that writes a review receipt only; it does not write raw, Zhiyi, Xingce, Hermes, OpenClaw, or adopted production experience.
- Extended MCP gateway receipts so clients can see which library ids and source refs were used, why they matched, and that no platform write occurred.
- Added capability check mode for install and smoke tests: clients can verify Skill/MCP/read-only availability without running recall or returning source text.
- Updated Hermes context formatting to include library ids, shelves, match methods, and rank reasons.
- Experience is explicitly kept separate from skills: Zhiyi remains the preference and intent layer, while Xingce remains the work-experience layer.

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
