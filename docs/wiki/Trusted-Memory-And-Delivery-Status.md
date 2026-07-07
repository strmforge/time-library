# Trusted Memory And Delivery Status

Time Library uses "trusted memory" in a specific way: original records stay
above summaries, recall should carry source refs, and evidence-bound answers
should expose what was used, what is missing, and when the honest boundary is
`UNKNOWN`.

It is an enhancer for the user's existing memory safety net, not a replacement
for it. Keep notes, knowledge bases, documents, and local archives. Time Library's job is to preserve, reconnect, and verify them with source refs, not to
promise that the user can stop keeping records.

This page keeps the public wording aligned with the current product boundary.

For the maintainer execution plan, see
[Trusted Memory Next Plan](../decisions/2026-06-21-trusted-memory-next-plan.md).

## What Is Available Now

- Original local records, raw mirrors, canonical indexes, and source refs can be
  guarded and inspected.
- Recall can return compact source refs, library ids, hit reasons, and bounded
  raw excerpts when requested.
- Capability check verifies the read-only connection without recalling real
  memory or returning raw excerpts.
- Record Doctor and the local console show record health before the user trusts
  recall.
- Work preflight can run a read-only check before coding, install, sync,
  release-prep, or troubleshooting work.
- The console can show an evidence receipt projection for the work-preflight
  search/think probe: what was recalled, what was used, what gaps remain, and
  whether raw expansion is available.
- Platform entry points stay passive by default. Ordinary chat must pass
  through unless the user explicitly enters a memory/direct-answer path or grants
  stronger authority.
- A repeatable fixture-backed live answer probe now satisfies the five-cell
  Definition of Proven on one real platform entry path for two cases: enough
  evidence returns `used_source_refs`, and insufficient evidence returns
  `UNKNOWN`. In both cases ordinary chat passed through, explicit memory entry
  called the evidence-bound model with source refs, the receipt was visible on
  the same path, and passive/security tests were green.
- A controlled-temp-memory live answer probe now writes non-sensitive
  `case_memory` records into a temporary `MEMCORE_ROOT`, serves the normal
  `/inject` gateway against that temporary root, and can exercise source-backed
  and `UNKNOWN` behavior without touching the installed preference/work-experience store.
  It calls a live evidence-bound model, so it remains a live diagnostic and may
  expose model variance.
- The default trust metrics runner now summarizes deterministic contract
  fixtures on hijack rate, unsupported-answer rate, UNKNOWN discipline, source
  reachability, and receipt visibility. Live model probes are opt-in with
  `--live-probes`.
- The trust metrics runner also has an explicit scoped installed user/work mode:
  `--user-work-probe` requires a scope filter, source-backed query, and UNKNOWN
  query before it reads installed preference/work-experience records. It is scoped proof, not
  broad/global recall.
- A scoped user/work-record trace probe exists for the next closure step. By
  default, with no scope/query, it performs only a no-record smoke check. When a
  scope filter, source-backed query, and UNKNOWN query are supplied, it reads
  scoped installed preference/work-experience user/work records as normal installed recall.
  Installing and connecting Time Library is the local trust boundary for normal
  recall; the no-record default prevents broad diagnostic sweeps.
- A recall-before-judgment liveness probe now exists to check whether
  work-preflight surfaces authoritative source anchors before an agent makes a
  product or engineering judgment. This is passive and findings-only; it is not
  automatic answer injection.
- Current working-tree recall-before-judgment observation on 2026-06-21:
  a real HTTP gateway on a temporary port surfaces the Trusted Memory
  scoped-recall-boundary anchors before judgment.
- Current installed 9851 observation on 2026-06-21 now returns
  `authoritative_anchor_surfaced` after refreshing only
  `com.memcorecloud.raw-gateway` and its local source files. The probe also
  checked `/health` source identity and reported
  `service_source_status=matches_working_tree` /
  `service_refresh_required=false`, so recall-before-judgment liveness is
  proven for this installed raw-gateway path.
- A read-only code-change source audit now exists for maintainer work.
  It reports repository git working-tree changes as source refs and
  reproducible commands, with status `source_refs_only_until_raw_origin`.
  Saved verification or test output artifacts can be attached as
  `verification_source_refs`; without an explicit artifact the report keeps
  `test_output_evidence_status=not_supplied`.
  It does not turn code changes into preference/work-experience/toolbook records, user memory,
  release claims, or platform actions.

## What Is A Controlled Or Preflight Path

The search/think boundary is implemented as a contract and preflight probe:

- local Time Library owns search and evidence packaging;
- the final think answer is owned by the evidence-bound model;
- local code may validate source refs and `UNKNOWN` boundaries after think;
- local code must not synthesize, rewrite, or fill an answer after think.

The evidence receipt shown from this path is a local projection. It is useful
for trust and debugging, but it is not proof that a host platform model received
the evidence.

## What Is Not Claimed Yet

Do not read the current public wording as claiming these are already proven for
every platform:

- platform answer paths always use search/think;
- every platform answer path has demonstrably delivered evidence to its
  evidence-bound model;
- every platform answer automatically shows an evidence receipt;
- delivery receipt projection is itself platform delivery proof;
- controlled-temp-memory proof is the same as a scoped installed preference/work-experience
  user/work-record trace;
- controlled trust metrics are the same as broad install or platform-wide trust
  metrics;
- benchmark recall is final QA accuracy.
- Time Library can replace the user's own note-taking or knowledge-base
  practice.
- "Never forgets everything" or "you can stop keeping notes" is not a product
  claim.
- Code-change source refs are not automatic memory sediment or release proof.

Those claims require platform-specific live verification.

## Current Closure Target

The first closure target has moved from "no observed model delivery" to
fixture-backed observed traces plus controlled-temp-memory live diagnostics.
The next target is to keep this behavior on scoped installed preference/work-experience
user/work records, then expand platform by platform:

1. Pick the first real platform answer path and make that path the demo. Do not
   build a separate showcase path that bypasses production authority checks.
2. Connect search/think to that live platform answer path.
3. Keep the explicit memory-entry gate in front of that path.
4. Keep `validate_think_result()` in the path so the model owns the final
   evidence-bound answer.
5. Verify platform by platform that evidence was actually delivered to the
   model, not merely displayed in a local console projection.

For this status page, `proven` means an observed end-to-end trace, not merely
that the path is wired and tests run. A proven trace must show ordinary chat
passing through, explicit memory entry delivering source refs to the
evidence-bound model, the answer carrying `used_source_refs` or `UNKNOWN`, the
receipt visible on the same answer path, and passive/security tests still green.
If the trace says `model=not_measured`, delivery remains `unproven`.

The demo should be load-bearing: ordinary chat passes through, explicit memory
entry uses source refs, missing evidence returns `UNKNOWN`, and the evidence
receipt is produced from the same path being verified.

Current repeatable fixture-backed observed probe:

- command: `python3 tools/trusted_memory_live_trace_probe.py --json`;
- `fixture_backed=true`;
- `user_work_records_read=false`;
- `platform_action_performed=false`.

Source-backed case:

- `ordinary_handled=false`;
- `answer_source=evidence_bound_model_call`;
- `model_called=true` and `request_sent=true`;
- `evidence_packet_refs=["exp-live-trace-next"]`;
- `used_source_refs=["exp-live-trace-next"]`;
- `receipt_status=source_backed`;
- `trace_status=proven`;
- `model_delivery_state=observed`;
- all five Definition-of-Proven cells were true.

UNKNOWN case:

- `ordinary_handled=false`;
- `answer=UNKNOWN`;
- `answer_source=evidence_bound_model_call`;
- `model_called=true` and `request_sent=true`;
- `evidence_packet_refs=["exp-live-trace-gap"]`;
- `used_source_refs=[]`;
- `receipt_status=unknown`;
- `unknown_boundary=true`;
- `trace_status=proven`;
- `model_delivery_state=observed`;
- all five Definition-of-Proven cells were true.

Boundary: this was a fixture-backed probe with real evidence-bound model calls.
It proves the first load-bearing path can repeatedly produce the required
observations, including the `UNKNOWN` boundary. It does not claim every
platform, every real preference/work-experience answer, or every install is already proven.

Current controlled-temp-memory live diagnostic:

- command: `python3 tools/trusted_memory_real_memory_trace_probe.py --json`;
- `fixture_backed=false`;
- `controlled_temp_memory=true`;
- `user_work_records_read=false`;
- `platform_action_performed=false`;
- `temporary_gateway=true`;
- inserts two non-sensitive `case_memory` records into a temporary
  `MEMCORE_ROOT`;
- serves the normal `/inject` gateway against that temporary root.

Source-backed case can pass with:

- `ordinary_handled=false`;
- `answer_source=evidence_bound_model_call`;
- `model_called=true` and `request_sent=true`;
- `recall_count=1`;
- `evidence_packet_refs=["exp-real-trace-next"]`;
- `used_source_refs=["exp-real-trace-next"]`;
- `receipt_status=source_backed`;
- `trace_status=proven`;
- `model_delivery_state=observed`;
- all five Definition-of-Proven cells were true.

UNKNOWN case can pass with:

- `ordinary_handled=false`;
- `answer=UNKNOWN`;
- `answer_source=evidence_bound_model_call`;
- `model_called=true` and `request_sent=true`;
- `recall_count=1`;
- `evidence_packet_refs=["exp-real-trace-gap"]`;
- `used_source_refs=[]`;
- `receipt_status=unknown`;
- `unknown_boundary=true`;
- `trace_status=proven`;
- `model_delivery_state=observed`;
- all five Definition-of-Proven cells were true.

Boundary: this controlled-temp-memory probe exercises real preference records and
the normal `/inject` recall gateway, but only inside a temporary root populated
with non-sensitive fixture records. It calls a live evidence-bound model, so a
single run can expose model variance. It does not touch the installed
preference/work-experience store and does not prove every installed user/work-record trace.

Current trust metrics report:

- command: `python3 tools/trusted_memory_trust_metrics.py --json`;
- scope: deterministic contract fixtures for fixture-backed and
  controlled-temp-memory trusted-memory behavior;
- proves the trust-axis contract fixture, not all installed preference/work-experience
  user/work-record traces, not all platforms, and not live model stability.
- live model diagnostic command:
  `python3 tools/trusted_memory_trust_metrics.py --json --live-probes`.
- scoped installed user/work diagnostic command:
  `python3 tools/trusted_memory_trust_metrics.py --json --user-work-probe --scope-filter <scope> --source-query <query-with-evidence> --unknown-query <query-that-should-be-UNKNOWN>`.
- scoped installed user/work casefile command:
  `python3 tools/trusted_memory_trust_metrics.py --json --user-work-casefile docs/fixtures/trusted-memory-user-work-cases.example.json`.
- the user/work mode reads installed preference/work-experience records only inside the supplied scope
  and queries, and now propagates `user_work_caller_scope` from the probe. It is
  not a broad record sweep or platform-wide proof.
- the casefile mode is a reproducibility wrapper around the same scoped proof
  contract. The checked-in example currently contains three observed
  scope/query pairs across two window scopes: a sample preference case, a
  legacy positioning/preference case, and a Codex history/provider-filter
  work case. Its checked `record_kind` coverage includes `user_preference` and
  `work_record`. The casefile accepts only those two `record_kind` values,
  matching the preference/work-experience boundary rather than an extra generic memory layer.
  Each checked case keeps `observed_at` and `evidence_command`, plus
  `expected_metrics` for the two-answer trace: ordinary pass-through count,
  source-backed claim count, UNKNOWN count, hijack rate, unsupported-answer
  rate, UNKNOWN discipline, source reachability, and receipt visibility. The
  status consistency gate checks each case's expected metrics and verifies that
  the command matches that case's scope/query pair. This is still scoped
  installed proof, not all-record or platform-wide coverage.
- the trust metrics runner emits a `proof_scope_matrix` with
  `fixture_backed_answer_path`, `controlled_temp_memory_answer_path`,
  `scoped_installed_zhiyi_xingce_user_work_records`, `platform_wide_delivery`,
  `all_records_all_scopes`, and `public_claim_rule`. The matrix keeps the
  public claim boundary next to the numbers: fixture-backed proof,
  controlled-temp proof, and scoped installed user/work proof cannot be
  described as platform-wide or all-record coverage.

Current code-change source audit:

- command: run the maintainer-only code-change source audit tool with `--json`;
- complete ledger command:
  use the same tool with `--max-refs 0 --require-complete --json`;
- optional verification-output ledger command:
  use the same tool with `--json --verification-output <saved-output> --verification-command <command-that-produced-it>`;
- scope: current repository working-tree source refs for maintainer audit;
- status: `source_refs_only_until_raw_origin`;
- complete-ledger expectation: `complete_source_refs=true` and
  `source_refs_truncated=false`;
- verification-output expectation: without a saved artifact,
  `test_output_evidence_status=not_supplied`; with one, the report emits
  `verification_source_refs` and
  `test_output_evidence_status=source_refs_only`;
- proves source-reference packaging, not persisted raw origin, memory adoption,
  release publication, or user-facing platform delivery.

Current scoped user/work-record probe:

- default no-read smoke: `python3 tools/trusted_memory_user_work_trace_probe.py --json`;
- install-specific form:
  `python3 tools/trusted_memory_user_work_trace_probe.py --json --scope-filter <scope> --source-query <query-with-evidence> --unknown-query <query-that-should-be-UNKNOWN>`;
- casefile form:
  `python3 tools/trusted_memory_user_work_trace_probe.py --json --casefile docs/fixtures/trusted-memory-user-work-cases.example.json`;
- default output keeps `user_work_records_read=false` because scope/query are
  missing. This is a broad-sweep guard for the diagnostic, not an extra approval
  layer for normal installed recall;
- install-specific output includes both `authorized_scope_filter` and
  `authorized_caller_scope`, and the dialog entry path forwards
  `caller_scope.canonical_window_id` to the memory gateway;
- install-specific output is still scoped to the supplied scope filter and is not
  platform-wide proof.

Current installed scoped observation on 2026-06-21:

- command:
  run the scoped user/work trace probe with `--scope-filter <window-scope> --source-query <source-backed query> --unknown-query <query-without-evidence> --timeout-seconds 120`;
- status: `proven`;
- scope: one authorized caller window scope;
- source-backed case: ordinary chat `handled=false`; explicit memory entry
  answered through `evidence_bound_model_call`, used installed record
  `exp-pref-a1fe8885`, and showed a source-backed receipt;
- UNKNOWN case: same scoped evidence packet reached the model, but no evidence
  covered the remote release receipt, so the answer stayed `UNKNOWN`;
- boundary: this proves one scoped installed user/work-record trace. It is not
  all records, all scopes, all models, or platform-wide proof. The probe now
  aligns the F3 gateway timeout with `--timeout-seconds` so install-sized scoped
  recall is measured instead of being cut off by the old 10-second gateway
  timeout.

Current scoped user/work trust-metrics observation on 2026-06-21:

- command:
  run the trust metrics tool with `--user-work-probe --scope-filter <window-scope> --source-query <source-backed query> --unknown-query <query-without-evidence> --timeout-seconds 120`;
- status: `ok=true`, `installed_user_work_probe_performed=true`,
  `user_work_records_read=true`;
- counts: `ordinary_chats_checked=2`, `source_claims_checked=1`,
  `unknown_cases_checked=1`, `model_delivery_observed_cases=2`,
  `receipt_visible_cases=2`;
- metrics: `hijack_rate=0/2`, `unsupported_answer_rate=0/1`,
  `unknown_discipline=1/1`, `source_reachability=1/1`,
  `receipt_visibility=2/2`;
- boundary: this is still scoped installed proof for the supplied scope and
  queries only. It is not all installed records or platform-wide proof.
- the same observed scope/query pairs can now be rerun through
  `docs/fixtures/trusted-memory-user-work-cases.example.json`. This improves
  reproducibility and gives future scoped installed proofs a fixed list format;
  it does not add broader proof until additional cases are actually observed.
- current checked-in casefile run on 2026-06-21:
  `python3 tools/trusted_memory_trust_metrics.py --json --user-work-casefile docs/fixtures/trusted-memory-user-work-cases.example.json`
  returned `ok=true`, `evaluation_scope=scoped_installed_zhiyi_xingce_user_work_record_probe`,
  `user_work_case_count=3`, `user_work_scope_count=2`,
  `ordinary_chats_checked=6`, `source_claims_checked=3`, `unknown_cases_checked=3`,
  `hijack_rate=0/6`, `unsupported_answer_rate=0/3`,
  `unknown_discipline=3/3`, `source_reachability=3/3`, and
  `receipt_visibility=6/6`, with `user_work_record_kinds=["user_preference","work_record"]`
  and no `failed_source_backed_cases`.
  Boundary: these are three scoped installed cases across two window scopes
  rerun through a reproducible casefile, with `user_preference` and
  `work_record` coverage, not all-record or platform-wide proof. Because this
  command calls a live evidence-bound model, a single run can still expose model
  variance and remains a scoped diagnostic rather than a broad product claim.
  The trust metrics runner now also emits top-level `user_work_case_evidence`
  with each `casefile_case`, `casefile_observed_at`,
  `casefile_evidence_command`, and `authorized_scope_filter`, so the current
  metric report carries the observed case trail with the numbers. It also emits
  `user_work_case_metric_evidence` with per-case `observed_metrics`,
  `expected_metrics_match`, and metric mismatches, so the runner itself compares
  casefile expectations with the observed trace metrics. It can also repeat the
  same casefile and report `user_work_casefile_repeat_requested`,
  `user_work_casefile_repeat_completed`, `user_work_casefile_stable`, and
  `user_work_case_metric_evidence_runs`; this exposes live model or installed
  service variance without turning the casefile into all-record or
  platform-wide proof. A repeat diagnostic on 2026-06-21 with
  `python3 tools/trusted_memory_trust_metrics.py --json --user-work-casefile docs/fixtures/trusted-memory-user-work-cases.example.json --user-work-casefile-repeat 2`
  returned `user_work_casefile_repeat_requested=2`,
  `user_work_casefile_repeat_completed=2`, `user_work_casefile_stable=true`, and
  `user_work_case_expected_metrics_match=true`. The checked casefile also keeps
  `expected_metrics`, and
  the status consistency gate checks each case's expected metrics before
  accepting aggregate counts. The current
  checked-in source-backed cases are `exampletool-preference-scope-proof`,
  `legacy-positioning-preference-proof`, and
  `codex-history-provider-filter-work-proof`.
  The same report carries `proof_scope_matrix` rows for
  `fixture_backed_answer_path`, `controlled_temp_memory_answer_path`,
  `scoped_installed_zhiyi_xingce_user_work_records`, `platform_wide_delivery`,
  and `all_records_all_scopes`, plus `public_claim_rule`; the platform-wide and
  all-record rows remain unproven until their own evidence exists.
  The platform delivery matrix now emits `platform_proof` with
  `platform_proof_state`, `platform_delivery_proven`, and
  `proof_scope_projection`; the projection includes
  `scoped_installed_user_work_records`. A platform row is proven only when all five Definition-of-Proven cells are true, and scope or casefile proof is not
  platform-wide proof.
  Latest live rerun of the old combined positioning case showed model/evidence
  drift instead of confirming the earlier green observation: it returned
  `ok=false` with
  `source_backed_expectation_failed`, `source_backed_cases_expected=3`,
  `source_backed_cases_proven=2`, and
  `failed_source_backed_cases=["trusted_memory_user_work_trace_probe.v2026.6.21:source_backed"]`
  for the old `casefile_case=legacy-positioning-scoped-preference-proof`.
  This preserved the failure as evidence for the next diagnosis and led to the
  current narrower checked-in source query. A focused
  single-case rerun of the old combined query reports
  `ok=false`, `status=unproven`, and `model_verdict=insufficient_evidence` for
  the same case because the evidence packet partially supports Time Library positioning
  but does not fully support 偏好层/经验层 positioning. That verdict is now treated as
  source-backed failure even when `used_source_refs` are present. The failure
  diagnostics now also keep the concrete `authorized_scope_filter`, so the
  failing case points back to the authorized window scope instead of
  losing its scope in the aggregate report. The checked-in casefile now replaces
  that old combined source query with the narrower, observed source-backed query
  `Time Library的定位是什么？`; a separate live probe for `偏好层和经验层的定位是什么？`
  still returns `status=unproven` / `model_verdict=unknown`, so preference/work-experience
  positioning remains a documented evidence gap. It is not a passing claim.
  preference/work-experience positioning remains a documented evidence gap.
  If a source-backed case drifts to `UNKNOWN`, the trust metrics runner now
  reports `source_backed_expectation_failed` and lists
  `failed_source_backed_cases` instead of silently reducing the source-backed
  denominator. Failed cases now also include bounded `failure_diagnostics` with
  `casefile_case`, `casefile_record_kind`, `authorized_scope_filter`,
  `model_verdict`, `unknown_reason`, `used_source_refs`,
  `evidence_packet_refs`, and `missing_cells`, so a maintainer can separate
  recall drift, model verdict drift, and missing-evidence failures.

Current recall-before-judgment liveness probe:

- command:
  `python3 tools/recall_before_judgment_liveness_probe.py --json --canonical-window-id codex-current --project-root <repo-root>`;
- status values distinguish `authoritative_anchor_surfaced`,
  `weak_anchor_surfaced`, `not_surfaced_before_judgment`, and unavailable
  work-preflight;
- a weak anchor is not enough to claim that the agent will reliably remember
  the right boundary before judging;
- the probe is read-only and does not call a model, write memory, or attempt
  platform delivery.
- working-tree HTTP gateway result on 2026-06-21:
  `status=authoritative_anchor_surfaced`, with required terms
  `memory_authority_policy`, `recall_only`, `投影不脱敏`,
  `installed local trust boundary`, `context_inject`, `direct_answer`,
  `platform_act`, `299_2026-06-21_TrustedMemory授权模型纠偏`, and
  `scope_and_queries_required`;
- installed 9851 result on 2026-06-21:
  `status=authoritative_anchor_surfaced`, with `decision=surface`,
  `recall_status=preflight_surface_required` (`preflight_surface_required`),
  `fast_recall_path=canonical_window_index+trusted_memory_authority_anchor`,
  `source_refs_count=5`, `raw_items_count=5`, and all required terms:
  `memory_authority_policy`, `recall_only`, `投影不脱敏`,
  `installed local trust boundary`, `context_inject`, `direct_answer`,
  `platform_act`, `299_2026-06-21_TrustedMemory授权模型纠偏`, and
  `scope_and_queries_required`. The same run queried
  `http://127.0.0.1:9851/health` and found `service_version=2026.6.20.2`,
  `service_source_status=matches_working_tree`,
  `service_source_matches_working_tree=true`, and
  `service_refresh_required=false`: the running source was
  `<install-root>/src/raw_consumption_gateway.py`
  with hash `d363977e738464f7476a93f05436de7fe5bc3e026319f368182149ad1b26e3b2`,
  matching the working-tree `src/raw_consumption_gateway.py`. This proves the
  installed service can surface the Trusted Memory scoped-recall-boundary
  anchors before judgment. It remains findings-only: it does not prove model
  answer delivery. It also does not prove platform action, automatic context
  injection, or platform-wide coverage.
  Machine-readable boundary: does not prove model answer delivery.

## Trust Metrics

Retrieval recall can still be useful for engineering, but it is not the main
public proof for this product. The public proof should measure trust behavior:

- **Hijack rate**: ordinary platform chat that gets taken over by memory. Target:
  `0`.
- **Unsupported-answer rate**: answers produced without supporting local
  evidence. Target: `0`.
- **UNKNOWN discipline**: cases with insufficient evidence that correctly return
  `UNKNOWN`.
- **Source reachability**: claims whose refs can be expanded back to original
  evidence. Target: `100%` for evidence-bound claims.
- **Receipt visibility**: evidence-bound answers whose used refs, gaps, and
  unknown boundary are visible to the user.

Current deterministic contract fixture on 2026-06-21 passes with hijack rate
`0`, unsupported-answer rate `0`, UNKNOWN discipline `100%`, source
reachability `100%`, and receipt visibility `100%`. It is not a live model
probe. The opt-in `--live-probes` diagnostic also passed in the latest run, but
a prior same-session live run showed controlled-temp-memory variance, so live
probe results remain diagnostics, not broad platform-wide or single-run
absolute claims.

Until platform-by-platform closure lands, the honest user-facing promise is:

> Time Library preserves original evidence, can recall with source refs, keeps
> ordinary platform chat from being hijacked, can show evidence receipt
> projections in controlled/preflight paths, and has repeatable fixture-backed
> and controlled-temp-memory live diagnostics for source-backed and `UNKNOWN`
> answers, plus a deterministic trust metrics runner for the trust-axis
> contract. Full installed preference/work-experience user/work-record and platform coverage
> is proven only after install-specific and platform-specific verification. It
> strengthens existing notes and knowledge bases; it does not ask the user to
> abandon them.

## 中文

Time Library说“可信记忆”，不是说所有平台答题现在都已经自动带证据回执。

当前已经能稳定表达的是：

- 原始记录、raw 镜像、canonical index 和 source refs 可以被守住和检查；
- 召回可以返回来源线索、馆藏身份、命中理由，并在需要时展开有界原文；
- capability check 不召回真实记忆，只验证只读连接；
- 记录医生和本地控制台可以先看记录健康；
- work preflight 可以在写代码、安装、同步、发版准备或排障前做只读检查；
- 控制台可以展示 work-preflight search/think 探针的证据回执投影；
- 平台入口默认被动，普通聊天不应该被Time Library接管；只有显式进入偏好层 / 直接回答路径或授权更高权限时才升级。
- Time Library是增强和保全用户已有笔记、知识库、文档、归档的系统，不是让用户停止记录、把全部记忆交出去的替代品。
- 现在已经有一个可重复的 fixture-backed 真实答题路径 probe 满足五格 Definition
  of Proven，覆盖两个场景：证据充分时返回 `used_source_refs`，证据不足时返回
  `UNKNOWN`。两个场景里普通聊天都放行，显式记忆入口都调用 evidence-bound
  model 并携带 source refs，同一路径展示证据回执，passive / security 测试通过。
- 现在也有一个 controlled-temp-memory 真实答题路径诊断：它向临时
  `MEMCORE_ROOT` 写入非敏感 `case_memory`，通过正常 `/inject` 网关召回，可覆盖
  source-backed 和 `UNKNOWN` 两个场景；它不触碰安装中的偏好层 / 经验层存储。但它调用活的
  evidence-bound model，所以属于 live 诊断，会暴露模型波动。
- 现在还有一个默认确定性的 trust metrics runner，会汇总合同 fixture 的抢答率、无证据作答率、
  UNKNOWN 纪律、回源可达率和回执可见率；活模型诊断需显式 `--live-probes`。它也有显式的
  scoped installed user/work 模式: `--user-work-probe`；提供 scope、source-backed 查询和 UNKNOWN 查询后，它按正常安装召回读取对应范围内的偏好层 / 经验层记录。
- 现在也有一个 scoped 的真实偏好层 / 经验层记录探针入口：无 scope/query 时只做 no-record smoke；安装 / 连接本身就是本地正常召回的信任边界。提供 scope、source-backed 查询和 UNKNOWN 查询后，才会尝试安装级证明。
- scoped installed user/work 现在也支持 casefile 形式，可以把多条 scope/query
  证明固定成可复现列表；当前示例包含两个 window scope 下已经观测过的三条
  case，但仍不代表全记录或全平台覆盖。

当前还不能夸口的是：

- 每个平台答题路径都已经接入 search/think；
- 每个平台模型都已实证收到证据包；
- 每次平台回答都会自动展示证据回执；
- 控制台回执投影就是平台送达证明；
- controlled-temp-memory proof 等于 scoped 的真实偏好层 / 经验层用户工作记录已经证明；
- 受控 probe 的 trust metrics 等于所有安装或所有平台的 trust metrics；
- 检索 recall 等于端到端 QA 准确率。
- Time Library可以替代用户自己的笔记和知识库习惯；
- “永远不会忘 / 你不用再记”不是当前产品承诺。

第一条闭环已经从“没有观测到模型送达”推进到“有 fixture-backed observed trace 和
controlled-temp-memory live diagnostic”。下一步不是做旁路 demo，而是把这条路径推进到 scoped
真实偏好层 / 经验层用户工作记录，再逐平台扩展：

- 普通聊天放行；
- 显式记忆入口使用 source refs；
- 证据不足返回 `UNKNOWN`；
- 证据回执来自同一条真实路径。

然后把 search/think 接入这条真实平台答题路径，同时保留两道门：

- 显式偏好层入口门：普通聊天仍然放行；
- `validate_think_result()`：最终答案归 evidence-bound model，本机不合成答案。

这里的 `proven` 必须是一条被观测到的端到端 trace，不是“接好了、测试绿”。五格缺一格仍然是 `unproven`：

- 普通聊天仍然放行；
- 显式记忆入口能观测到模型实际收到 source refs；
- 答案带 `used_source_refs`，证据不足时返回 `UNKNOWN`；
- 同一条答题路径前台显示证据回执；
- passive / security 测试仍然通过。

如果 trace 里仍是 `model=not_measured`，就不能宣称平台送达已经 proven。

当前可重复 fixture-backed probe：

- 命令：`python3 tools/trusted_memory_live_trace_probe.py --json`；
- `fixture_backed=true`；
- `user_work_records_read=false`；
- `platform_action_performed=false`。

source-backed 场景关键字段：

- `ordinary_handled=false`；
- `answer_source=evidence_bound_model_call`；
- `model_called=true` 且 `request_sent=true`；
- `evidence_packet_refs=["exp-live-trace-next"]`；
- `used_source_refs=["exp-live-trace-next"]`；
- `receipt_status=source_backed`；
- `trace_status=proven`；
- `model_delivery_state=observed`；
- 五格全部为 true。

UNKNOWN 场景关键字段：

- `ordinary_handled=false`；
- `answer=UNKNOWN`；
- `answer_source=evidence_bound_model_call`；
- `model_called=true` 且 `request_sent=true`；
- `evidence_packet_refs=["exp-live-trace-gap"]`；
- `used_source_refs=[]`；
- `receipt_status=unknown`；
- `unknown_boundary=true`；
- `trace_status=proven`；
- `model_delivery_state=observed`；
- 五格全部为 true。

边界也要说清：这是 fixture-backed 的真实 evidence-bound model 调用，证明第一条承重路径可以重复产出五格观测，包括 `UNKNOWN` 边界；它不等于所有平台、所有真实偏好层 / 经验层答题、所有安装环境都已经 proven。

当前 controlled-temp-memory live diagnostic：

- 命令：`python3 tools/trusted_memory_real_memory_trace_probe.py --json`；
- `fixture_backed=false`；
- `controlled_temp_memory=true`；
- `user_work_records_read=false`；
- `platform_action_performed=false`；
- `temporary_gateway=true`；
- 向临时 `MEMCORE_ROOT` 写入 2 条非敏感 `case_memory`；
- 通过正常 `/inject` 网关召回。

source-backed 场景关键字段：

- `ordinary_handled=false`；
- `answer_source=evidence_bound_model_call`；
- `model_called=true` 且 `request_sent=true`；
- `recall_count=1`；
- `evidence_packet_refs=["exp-real-trace-next"]`；
- `used_source_refs=["exp-real-trace-next"]`；
- `receipt_status=source_backed`；
- `trace_status=proven`；
- `model_delivery_state=observed`；
- 五格全部为 true。

UNKNOWN 场景关键字段：

- `ordinary_handled=false`；
- `answer=UNKNOWN`；
- `answer_source=evidence_bound_model_call`；
- `model_called=true` 且 `request_sent=true`；
- `recall_count=1`；
- `evidence_packet_refs=["exp-real-trace-gap"]`；
- `used_source_refs=[]`；
- `receipt_status=unknown`；
- `unknown_boundary=true`；
- `trace_status=proven`；
- `model_delivery_state=observed`；
- 五格全部为 true。

边界也要说清：controlled-temp-memory probe 走的是真实偏好层记录和正常 `/inject`
召回网关，但只在临时根目录里使用非敏感测试记录；它调用活模型，可能出现模型波动；它不触碰安装中的偏好层 / 经验层存储，也不等于所有安装级 scoped 记录路径都已经 proven。

在完成逐平台 live 验证之前，最诚实的说法是：Time Library已经能保存和召回可回源证据，默认不接管普通平台聊天，能在受控 / preflight 路径展示证据回执投影，并已经跑出 fixture-backed live answer probe 与 controlled-temp-memory live diagnostic；真实偏好层 / 经验层 scoped 用户工作记录和完整平台覆盖，需要安装级、逐平台证明。

公开证明也不应该只跟对手比 recall。更适合Time Library的是可信指标：

- 抢答率：普通平台聊天被记忆接管的比例，目标 `0`；
- 无证据作答率：没有本地证据却给答案的比例，目标 `0`；
- UNKNOWN 纪律：证据不足时正确返回 `UNKNOWN`；
- 回源可达率：证据绑定结论能展开回原始证据，证据绑定结论目标 `100%`；
- 回执可见率：用到的 refs、缺口和 UNKNOWN 边界对用户可见。
