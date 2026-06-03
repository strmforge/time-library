# Changelog

## [2026.6.4] - 2026-06-04

- Released Memcore Cloud 2026.6.4 with native Windows as the default Windows install path and WSL documented as development / advanced testing only.
- Verified a clean official Windows Codex install where `codex.exe` is not on `PATH`: Memcore Cloud locates the bundled official CLI through Codex native-host metadata and registers `yifanchen-zhiyi` with official `codex mcp add`.
- Added and validated the Codex stdio MCP bridge for current-window recall, including `MEMCORE_WINDOW_BINDING_REGISTRY`, `MEMCORE_ROOT`, UTF-8 env setup, and standard JSON-RPC capability-check responses.
- Hardened Windows Python discovery so Microsoft Store `python` / `python3` aliases are not treated as usable runtimes unless they can execute `import sys`.
- Exposed continuous-sync status so the local service can report whether watchers are running as a continuous loop and which collectors are ready or pending.
- Added verified local assistant session collection with assistant-reply persistence checks; user-only local records stay evidence and do not count as complete conversation memory.
- Added model-assisted local tool identification as a second recognition layer: deterministic metadata and known storage patterns remain the fallback when no model provider is configured.
- Added `docs/construction/2026-06-04-windows-codex-native.md` and `docs/wiki/Native-Windows-Codex.md` to preserve the Windows official Codex validation and troubleshooting path.

## [2026.6.3] - 2026-06-03

- Prepared Memcore Cloud Zhiyi prompt v4 as a standing memory rule instead of a one-time setup note, so agents are explicitly told to call `zhiyi_recall` before answering memory-dependent questions such as prior decisions, corrections, install/test/release status, and short "next step / what else / then what" follow-ups.
- Updated the public install prompts, local console copy prompt, Codex skill metadata, and Claude Desktop skill manifest wording to teach the same standing rule while keeping capability check read-only and no-recall.
- Verified the macOS and native Windows install roots can be upgraded in place with user data preserved, bringing both local runtimes back in line with `2026.6.3` while installing prompt v4 into Codex and Claude Desktop skill locations.
- Added `docs/construction/2026-06-02-03.md` so active construction decisions from 2026-06-02/03 are preserved outside transient agent windows.
- Connected local AI tool adapter drafts into authorized auto-connect dry-run, apply-gate previews, and apply receipts, including MCP, collector, and raw-archive plan fields.
- Added regression checks that adapter-draft-driven plans keep discovery/dry-run chat-body reads disabled and preserve the 2026.6.1 computer-first raw archive layout.
- Documented and enforced the current memory-scope correction: default recall is current-window first, ordinary Hermes recall is window-scoped too, and broader project/global or Hermes skill-generation/self-review scopes must be routed explicitly.
- Documented native Windows install as the normal Windows path and WSL as development / advanced testing only.
- Added assistant-reply persistence as a verification item before claiming complete conversation memory.

## [2026.6.2] - 2026-06-02

- Released Memcore Cloud 2026.6.2 as today's published version.
- Fixed Claude Desktop recall over the local `yifanchen-zhiyi` MCP bridge so capability checks and real recall can both complete cleanly.
- Added tolerant raw-text decoding for recalled excerpts and direct raw lookup, including BOM-aware UTF-8 plus Windows Chinese encodings, so Chinese `raw_excerpt` text stays readable.
- Changed the Claude Desktop stdio bridge to emit UTF-8 JSON lines and updated Claude installers to read existing config with BOM tolerance while writing config without BOM trouble.
- Covered both regular Claude Desktop config paths and Microsoft Store Claude config paths on Windows.
- Bumped the raw consumption gateway, skill metadata, installers, local console version markers, and public docs to `2026.6.2`.
- Strengthened the `yifanchen-zhiyi` skill prompt so agents are told to call memory first for previous decisions, corrections, project boundaries, install/test/release status, and next-step questions.
- Improved recall ranking for decision-focused queries so project decisions and release/status notes are easier to surface.
- Added product-facing Wiki source pages for getting started, safe capability checks, AI tool boundaries, memory layout, and release-history routing.

## [2026.6.1] - 2026-06-01

- Released Memcore Cloud as the English-first product name while keeping 忆凡尘 / Yifanchen as the Chinese name and codename.
- Added a read-only local AI tool discovery view so Memcore Cloud can show present tools, safe-check readiness, and access boundaries without silently parsing chat bodies.
- Added connection previews for local AI tools, including would-change paths, backup and rollback notes, restart needs, receipts, and capability-check payloads.
- Added bounded local settings discovery so newer AI tools can be noticed through common MCP/config patterns before deeper access is granted.
- Updated the local Platforms page to show tool presence, safe next steps, usage freshness, and whether new records are following the computer-first layout.
- Implemented the 2026.6.1 raw archive layout contract for all new installs and new raw writes: new records are grouped by computer first, then by source tool and app format. Older layouts remain readable for compatibility.
- Promoted Claude Code CLI from a boundary-only object to a connectable candidate while keeping it separate from Claude Desktop and still requiring a parser gate before reading conversation bodies.
- Added a read-only authorization gate for future platform-config changes, with required confirmations, backup and rollback readiness, receipt preview, and capability-check follow-up.

## [2026.5.31] - 2026-05-31

- Added natural-language correction routing so "this memory is wrong", "you misunderstood", and similar user feedback can become review-only Zhiyi errata candidates.
- Added external method-signal candidate dry-runs for turning news, repositories, audits, and practice feedback into review-only method candidates without installing or activating anything.
- Added public README prompts that users can send directly to an AI agent to install Yifanchen and finish with capability check mode.
- Updated the Yifanchen skill with a clear "local memory library" identity signal and ambient recall-before-judgment triggers for forgotten/corrected/ongoing project context.
- Clarified the Hermes raw-pointer-to-native-skill-learning chain: Yifanchen emits a self-review signal, provides raw/source-ref pointers, and observes Hermes native feedback, but does not directly write Hermes skills.
- Added a read-only Hermes native learning liveness check for recent `background_review`, `skill_manage`, and skill-file changes so cold learning chains are visible.
- Added Hermes self-review wake dry-run and signal receipt gating so Yifanchen can record that a wake signal was produced without triggering Hermes or writing Hermes skills.
- Added Hermes MemoryProvider consumption parity: `sync_turn` posts Yifanchen-side consumption receipts on a background thread and `queue_prefetch` warms recall without copying OpenClaw's before-dispatch interception model.
- Added a read-only Hermes skill vs experience diff dry-run that compares Hermes skill files with Yifanchen experience records and produces review-only adoption / upgrade candidates.
- Added Claude Desktop as a first-class source system distinct from Claude Code CLI, with local app-data sync manifest and sync-state receipt endpoints for config, IndexedDB, Local Storage, Session Storage, skill manifests, and logs. Consumer diagnostics distinguish a generic skill signal from a working Yifanchen MCP/Desktop Extension recall connection. Readers can aggregate all Claude surfaces under `claude_all`, while Windows relay / Claude Code related records keep dual attribution fields (`storage_owner`, `conversation_origin`, `runtime_consumer`) and isolation boundaries in manifest, sync-state, and source refs instead of being flattened into one source. Official Claude exports are treated as cold-start/backfill fallback only.
- Added read-only State Ledger / Temporal Index dry-runs for latest trusted judgment review while preserving superseded, deprecated, conflicting, and needs-review records.
- Added `context_budget_unit_candidate` dry-runs for source-backed, composable context units with explicit budget, trigger, verification, expiry/review, and no-write flags.
- Updated macOS, Linux, and Windows full installers to automatically install the Codex skill and register the `yifanchen-zhiyi` Codex MCP server at `http://127.0.0.1:9851/mcp` when Codex CLI is available.
- Added a Claude Desktop stdio MCP bridge and installer registration so Claude Desktop can call the existing read-only `zhiyi_recall` MCP instead of only seeing generic skill instructions.
- Bumped public README version markers, installers, raw MCP server info, and skill metadata to 2026.5.31.

## [2026.5.30] - 2026-05-30

- Added a multi-case Zhixing benchmark dry-run so real task sets can compare no memory, Zhiyi only, and Zhiyi plus Xingce before any Replay feedback queue or adoption flow is built.
- Added a precision-first P2 preference intent gate so repairs, deictic disambiguation, creative prompts, and long relayed audit text do not become durable Zhiyi preferences.
- Added public-safe benchmark fixture cases for checking source-backed behavior, proactive resurfacing, toolbook facts, connector boundaries, and public-documentation boundaries.
- Bumped runtime-visible versions for the Web console, Zhixing Library, raw MCP gateway, installers, and skill metadata to 2026.5.30.
- Verified the construction build on a Windows local service with health, Replay/benchmark plans, MCP initialize, OpenClaw raw query, source-ref sampling, and error-log checks.

## [2026.5.29] - 2026-05-29

- Added the Zhixing Library evidence loop: raw records remain source texts, Zhiyi keeps preference and intent experience, and Xingce keeps work experience and toolbooks.
- Added `library_id`, `library_shelf`, `library_card`, `matched_by`, `rank_reason`, and typed-graph metadata to recall and MCP gateway results.
- Expanded Xingce work-experience candidates with lifecycle status, work scenario, action strategy, avoid conditions, acceptance checks, and applicable scope.
- Added read-only Zhixing Library and replay-plan endpoints for library inspection and future no-memory / Zhiyi-only / Zhiyi-plus-Xingce evaluation.
- Extended usage receipts and Hermes context formatting so clients can explain what was recalled, why it matched, and which source refs were used.
- Added `mode=capability_check` for Skill/MCP install smoke tests, verifying availability without recall or raw excerpts.

## [2026.5.28] - 2026-05-28

- Added the first Zhiyi archive-catalog layer: stable catalog ids, archive cards, source-aware evidence output, and an archivist-style injection prompt.
- Added language-neutral Zhiyi entry aliases: `/zhiyi` as the main command, with `/memory`, `/recall`, `/continue`, and natural English recall phrases as aliases.
- Added a platform-neutral `yifanchen-zhiyi` skill package and a read-only MCP-compatible `zhiyi_recall` tool endpoint for AI clients that support skills, MCP, plugins, or custom system instructions.
- Expanded the public Zhiyi/Xingce wording in Chinese and English: Zhiyi keeps preference and intent experience, Xingce keeps work experience, and both stay source-backed.
- Clarified that experience is not a callable skill: Zhiyi keeps preference and intent experience, while Xingce keeps source-backed work experience.
- Hardened the local raw gateway with an explicit loopback-only request guard and safer cursor-state directory checks.

## [2026.5.27] - 2026-05-27

- Added Codex local record support. Yifanchen can discover local Codex sessions, preserve them as raw memory, and organize useful experience from them.
- Clarified and tested the saved-content rule: platform records, Zhiyi experience, recalled context, and usage records keep saved content without redaction, rewriting, or hash-only replacement.
- Extended the shared local memory base for OpenClaw, Hermes, and Codex while keeping each platform and conversation window separate.
- Added incremental capture for growing session files, so new conversation records are processed from saved offsets instead of rereading from the beginning.
- Added direct raw evidence lookup by byte offset, with a resumable segmented fallback for older records.
- Updated Hermes memory provider defaults to read the shared local memory base in read-only mode.
- Added tests for Codex capture, Zhiyi extraction, shared raw access, segmented resume, and offset lookup.

## [2026.5.26] - 2026-05-26

- Enabled the local one-click update flow: check, download, validate, back up app files, apply the new version, and restart local services.
- Preserved local memory, raw records, Zhiyi experience, configuration, logs, backups, and virtualenv state during update.
- Fixed the update history API so the local page can read past update records.
- Updated README and wiki guidance for install, repair install, and one-click update.

## [2026.5.25] - 2026-05-25

- First public release of Yifanchen.
- Added one-command installers for macOS, Linux, and Windows; WSL remains an advanced development/testing path.
- Added the local memory center page for platform status, model settings, and generated experience.
- Kept the public repository focused on the installable product.
