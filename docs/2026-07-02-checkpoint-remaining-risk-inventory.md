# Checkpoint Remaining-Risk Inventory

Recorded: 2026-07-02 CST

Checkpoint: `checkpoint/time-library-20260701-entangled`

Current branch/head: `cleanup/time-library-reading-area` at `e8cdc7e`

Checkpoint head inspected: `cf9b759`

Proof layer: source/test inventory only.

## Scope

This inventory classifies the remaining checkpoint diff after the clean splits
already extracted from `checkpoint/time-library-20260701-entangled`.

Commands used:

```text
git status --short --branch
git rev-parse --short HEAD
git rev-parse --short checkpoint/time-library-20260701-entangled
git diff --name-status HEAD..checkpoint/time-library-20260701-entangled
git diff --numstat HEAD..checkpoint/time-library-20260701-entangled
git diff HEAD..checkpoint/time-library-20260701-entangled -- <selected high-risk paths>
```

Snapshot result:

```text
remaining_changed_paths = 124
approx_insertions       = 28000+
approx_deletions        = 6500+
worktree_before         = clean
```

NonClaims:

- This is not a source-code implementation, installed runtime sync, service
  restart, live gateway/MCP proof, platform write, raw/source/card/memory write,
  remote push, tag, or release.
- No model call was made for implementation or runtime proof. The only model
  call in this pass was the user-authorized MiniMax-M3 read-only audit of this
  inventory.
- This does not prove any checkpoint feature works.
- This does not authorize applying release, installer, platform auto-connect,
  runtime endpoint, live probe, FTS5, raw gateway, or trusted-memory chunks.
- This does not update installed runtime or public documentation surfaces.

## Governing Boundaries

- Public name remains `Time Library / 忆凡尘`, MCP server `time-library`, tool
  `time_library_recall`. `yifanchen-zhiyi` and `zhiyi_recall` are legacy aliases
  only.
- Do not reuse inferred/window `project_id` as declared reading-area identity.
- Do not change raw/card/memory sources, installed runtime, or platform config in
  this inventory pass.
- Do not swallow broad checkpoint chunks. Large blocks need separate design,
  proof layer, and authorization.

## Already Extracted From This Checkpoint Line

These are no longer candidates for extraction from the remaining diff unless a
new bug is found:

- `42a270c` evidence-bound answer receipt refs.
- `8513e37` FTS5 recall default-off flag boundary.
- `979a752` scheduled restart runtime Python selection.
- `190e093` raw offset index scan limit.
- `a0e0066` preflight doctor memory absorption contracts.
- Time Twin Star source-canon workbench status split.
- Console smoke public naming assertion.
- P6 platform discovery bounded default scan.
- `64eae5c` work-preflight search-think probe helper reuse.
- `7f488f5` raw excerpt scan deadline.
- `8e9c3b3` zhixing preflight query-term overlap and raw-like coordinate gate.

## Bucket A: Safe Source/Test-Only Small Slices

Current decision: no remaining checkpoint slice is green-lit for immediate
source/test extraction.

Reasoning:

- The tempting small diffs are either no-value formatting, public naming
  regressions, release/public-docs work, or runtime/platform blocks.
- Remaining useful work is real, but it needs a separate cut brief rather than a
  blind cherry-pick from this checkpoint.

No-value rejects:

- `src/agent_work_preflight.py` only rewrites an existing append/update shape
  for the same evidence object. No behavior worth extracting.
- `src/evidence_bound_model.py` is formatting-only.
- `tests/test_xingce_distill.py` adds a trailing blank line only.
- `tools/platform_delivery_liveness_probe.py` removes a blank line only.

Possible future source/test cuts, but not safe without a new brief:

- Public docs wording such as `docs/wiki/Home.md`,
  `docs/wiki/AI-Tool-Boundaries.md`, `docs/wiki/Memory-Layout.md`, and
  `docs/Benchmark-And-Product-Differentiation.md`. These are public positioning
  surfaces, not internal tests; accept only after a wording/release decision.
- Small preflight or console-related remnants may exist, but each must be
  reviewed against the clean splits already landed before extraction.

## Bucket B: Authorization-Required Runtime / Platform / Release Work

These paths must not be applied under source/test-only authority.

### Release And Public Packaging

Classification: authorization required.

Paths:

- `VERSION`
- `CHANGELOG.md`
- `UPDATE_HISTORY.md`
- `RELEASE_NOTES_2026.6.20.2.md`
- `RELEASE_NOTES_2026.6.23.md`
- `docs/wiki/Release-History.md`
- `docs/wiki/Getting-Started.md`
- `docs/fixtures/installed-platform-coverage-release-candidate-2026.6.23.json`
- `tools/build_release_artifact.py`
- `tools/release_gate.py`
- `tests/test_release_artifact.py`
- `tests/test_release_gate.py`

Reason:

- These touch versioning, local release-candidate claims, release artifact gates,
  or install instructions.
- They require explicit release/public-doc authorization and cannot be smuggled
  through as cleanup.

### Installers, Platform Config Writes, And Auto-Connect

Classification: authorization required, with public-name regression risk in some
paths.

Paths:

- `install.sh`
- `install.ps1`
- `tools/linux_full_install.sh`
- `tools/macos_full_install.sh`
- `tools/windows_full_install.ps1`
- `tools/windows_guardian.ps1`
- `tools/windows_native_smoke.ps1`
- `tools/install_claude_desktop_skill.py`
- `config/platform_storage_patterns.verified.json`
- `src/platform_autodiscovery.py`
- `src/platform_guard_catalog.py`
- `src/platform_guard_surface_scan.py`
- `src/platform_thin_adapter_registry.py`
- `tests/test_platform_autodiscovery.py`
- `tests/test_installed_platform_coverage.py`

Reason:

- These change platform discovery, auto-apply expectations, supported surfaces,
  or installed config write behavior.
- Several checkpoint lines turn human confirmation into default auto-connect and
  add Pi/apply paths. That is platform mutation policy, not a source/test-only
  cleanup.

### Live Runtime Probes And Endpoints

Classification: authorization required.

Paths:

- `src/p6_console.py`
- `src/tiandao/time_twin_star.py`
- `src/tiandao/__init__.py`
- `src/tiandao/source_canon.py`
- `src/tiandao_workbenches.py`
- `src/time_twin_star_source_canon.py`
- `tests/test_time_twin_star.py`
- `tests/test_tiandao_workbenches.py`
- `tools/time_twin_star_installed_runtime_probe.py`
- `tools/time_twin_star_passive_push_trace_gate.py`
- `tools/time_twin_star_turn_loop_probe.py`
- `tools/time_twin_star_turn_loop_trace_gate.py`
- `tools/runtime_freshness_full_chain_probe.py`
- `tools/openclaw_passive_push_smoke_probe.py`

Reason:

- These are runtime endpoint/probe/trace surfaces. They may be useful later, but
  connected runtime proof and platform action require explicit authorization.

### Trusted-Memory Live Status / Metrics / Probes

Classification: authorization required or separate design block.

Paths:

- `docs/wiki/Trusted-Memory-And-Delivery-Status.md`
- `docs/decisions/2026-06-21-trusted-memory-next-plan.md`
- `docs/fixtures/trusted-memory-user-work-cases.2026.6.23.json`
- `docs/fixtures/trusted-memory-user-work-cases.example.json`
- `src/trusted_memory_status_consistency.py`
- `src/trusted_memory_trust_metrics.py`
- `tests/test_trusted_memory_live_trace_probe.py`
- `tests/test_trusted_memory_real_memory_trace_probe.py`
- `tests/test_trusted_memory_status_consistency.py`
- `tests/test_trusted_memory_trust_metrics.py`
- `tests/test_trusted_memory_user_work_trace_probe.py`
- `tools/trusted_memory_live_trace_probe.py`
- `tools/trusted_memory_real_memory_trace_probe.py`
- `tools/trusted_memory_status_consistency.py`
- `tools/trusted_memory_trust_metrics.py`
- `tools/trusted_memory_user_work_trace_probe.py`

Reason:

- These mix public trusted-memory wording, status claims, metrics, and live probe
  harnesses. They need a separate proof plan and cannot be accepted as a single
  cleanup diff.

## Bucket C: Reject / Defer

### Public-Name Regression: Reject Checkpoint Version

Classification: reject as-is.

Paths:

- `config/platform_catalog.json`
- `config/platform_storage_patterns.verified.json`
- `src/platform_event_triggers.py`
- `src/platform_native_entrypoints.py`
- `tests/test_installed_platform_coverage.py`
- installer diffs in `install.sh`, `install.ps1`,
  `tools/linux_full_install.sh`, `tools/macos_full_install.sh`, and
  `tools/windows_full_install.ps1`

Evidence:

```text
checkpoint reintroduces primary yifanchen-zhiyi / zhiyi_recall /
Memcore Cloud Zhiyi wording in platform policy, entrypoint fallbacks, install
targets, and tests.
```

Decision:

- Do not apply these checkpoint lines.
- Future installer/platform work must keep `time-library` and
  `time_library_recall` primary, with legacy alias only as compatibility.

### FTS5 / BM25 / RRF / P3 Recall Block: Defer As Large Design Work

Classification: defer.

Paths:

- `src/fts5_recall_index.py`
- `src/p3_recall.py`
- `runtime/bm25_index/bm25_corpus.json`
- `requirements-vector.txt`
- `tests/test_fts5_recall.py`
- `tests/test_bm25_segment_index.py`
- `tests/test_write_pollution_guard_and_bm25_rrf.py`
- `tools/rebuild_lancedb_v2_from_zhiyi.py`
- `tests/test_rebuild_lancedb_gpu_device.py`

Reason:

- This is a broad indexing/retrieval implementation, not a small split.
- It includes new index backends, corpus artifacts, rebuild tools, GPU/device
  tests, and P3 behavior changes.
- Before another implementation attempt, obey the three-failure external-search
  gate for indexing work and record sources/options in the receipt.

### Raw Gateway / Raw JSONL Fallback / MCP Schema: Defer As Design Work

Classification: defer.

Paths:

- `src/raw_consumption_gateway.py`
- `src/raw_gateway_mcp.py`
- `src/raw_jsonl_fallback.py`
- `src/raw_evidence_excerpt.py` remaining checkpoint hunks not already extracted
- `tests/test_raw_recall_explainability.py`
- `tests/test_raw_recall_response_budget.py`

Reason:

- The checkpoint mixes P3 HTTP transport, degraded fallback semantics,
  raw-jsonl fallback extraction, MCP schema/tool text, and raw recall response
  budget changes.
- This touches public MCP behavior and runtime recall routing. It needs a
  separate raw-gateway design cut, not opportunistic extraction.

### Work-Preflight Probe Contract Removal: Reject As-Is

Classification: reject as-is.

Path:

- `src/work_preflight_search_think_probe.py`

Reason:

- The checkpoint version removes the explicit entry contract and local
  consumer-preserving wrapper that were intentionally kept in the clean split
  `64eae5c`.
- Do not re-apply the checkpoint hunk over that fix.

### Stale Ledger / Architecture / Broad Docs: Defer

Classification: defer or ignore.

Paths:

- `CODEX_CONTINUITY_LEDGER.md`
- `ARCHITECTURE_REVIEW.md`
- `INTRODUCTION.md`
- `README.md`
- `README.en.md`
- `README.zh-CN.md`
- `docs/github-positioning-2026.6.16.md`
- `docs/wiki/Home.md`
- `docs/wiki/AI-Tool-Boundaries.md`
- `docs/wiki/Memory-Layout.md`
- `docs/wiki/Getting-Started.md`
- `docs/wiki/Release-History.md`
- `docs/Benchmark-And-Product-Differentiation.md`

Reason:

- The checkpoint ledger is stale relative to the current clean-split ledger.
- The broad docs change public positioning and release wording. Accept only
  under a public-doc/release wording brief.

### Miscellaneous Defer

Classification: defer pending a narrow brief.

Paths:

- `.mimocode/command/test.md`
- `requirements-core.txt`
- `src/codex_local_connector.py`
- `src/dialog_entry_proxy.py` remaining hunks not already extracted
- `src/p2_extract.py`
- `src/p4_provider.py`
- `src/preflight_doctor.py` remaining hunks not already extracted
- `src/zhixing_library.py`
- `src/zhixing_preflight.py` remaining hunks not already extracted
- `system/openclaw/plugins/memcore-zhiyi-native/index.js`
- `system/openclaw/plugins/memcore-zhiyi-native/openclaw.plugin.json`
- `system/skills/time-library/SKILL.md`
- `system/skills/time-library/agents/openai.yaml`
- `system/skills/yifanchen-zhiyi/SKILL.md`
- `system/skills/yifanchen-zhiyi/agents/openai.yaml`
- `tests/test_codex_connector.py`
- `tests/test_console_product_boundary.py`
- `tests/test_internal_direction_audit.py`
- `tests/test_preflight_doctor.py`
- `tests/test_public_experience_wording.py`
- `tests/test_security_boundaries.py`
- `tests/test_shared_memory_consumption.py`
- `tests/test_time_river_sediment.py`
- `tests/test_trusted_memory_delivery_trace.py`
- `tests/test_work_preflight_search_think_probe.py`
- `tests/test_zhixing_preflight.py`
- `tests/test_zhiyi_archive_catalog.py`
- `tests/test_zhiyi_skill_package.py`
- `tools/codex_zhiyi_skill_status.py`
- `tools/preflight_doctor.py`
- `web/console_product.html`

Reason:

- These may contain useful fragments, but they overlap already-landed clean
  splits, public naming/skill packaging, console surfaces, security wording, or
  test reshapes. Each needs its own diff review before extraction.

## Next Queue

Recommended order:

1. Do not apply any remaining checkpoint chunk wholesale.
2. If the user wants more source/test cleanup, start with a fresh narrow brief
   from this inventory, not from the checkpoint title.
3. Treat public docs/release, installers/platform auto-connect, FTS5/P3 recall,
   raw gateway/MCP schema, Time Twin Star runtime, and trusted-memory live probes
   as separate projects with separate proof layers.
4. Keep `time-library` / `time_library_recall` as the primary public surface in
   every future cut.

Completion state for this inventory:

```text
source_diff_survey             pass
risk_bucket_inventory_written  pass
minimax_m3_read_only_audit      pass
source_code_changes            not_performed
installed_runtime_sync         not_performed
service_restart                not_performed
live_runtime_proof             not_performed
platform_write                 not_performed
raw_card_memory_write          not_performed
real_model_call                not_performed_except_read_only_m3_audit
push_tag_release               not_performed
```

MiniMax-M3 read-only audit:

```text
verdict=PASS
finding=Inventory keeps no-value diffs out of Bucket A, separates release /
        installer / runtime / live-probe work into authorization-required
        buckets, rejects public-name regression as-is, defers FTS5/P3 and raw
        gateway/MCP schema blocks, preserves time-library/time_library_recall as
        primary names, and does not overclaim runtime proof.
```
