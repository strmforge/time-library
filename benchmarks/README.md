# Official Benchmark Diagnostics

This directory documents benchmark work that uses public benchmark data. The
first implementation is an internal evidence-retrieval diagnostic, not a public
leaderboard claim.

Why start here:

- If the gold evidence cannot be retrieved, a later answer-generation score will
  not be trustworthy.
- LoCoMo and LongMemEval have official data and evaluation conventions; we
  should use those before presenting any public score.
- LongMemEval-V2 has the most relevant shape for Xingce because it tests
  workflow knowledge, environment gotchas, dynamic state tracking, and premise
  awareness.

## No-Key Benchmark Suite

The easiest trust check is the free retrieval suite. It runs LoCoMo and
LongMemEval evidence-retrieval diagnostics in one command, without an OpenAI
API key, without a judge model, and without writing memory:

```bash
python3 tools/free_memory_benchmark.py --download
```

If the public data is already cached, run:

```bash
python3 tools/free_memory_benchmark.py --summary-json
```

Boundary:

- `no_api_key_required=true`
- `no_model_call=true`
- `no_memory_write=true`
- `official_leaderboard_score=false`
- score type: `evidence_retrieval_diagnostic`

Latest full-data no-key suite result on 2026-06-17, shown on a 100-point scale
so it can be compared with public memory benchmark writeups:

| dataset | mode | top5 exact | top5 bundled | top5 session / gold anchor |
|---|---|---:|---:|---:|
| LoCoMo locomo10 | fused_library_index_bm25 | 66.5/100 | 82.3/100 | 88.3/100 |
| LongMemEval oracle | fused_library_index_bm25 | 82.6/100 | 91.2/100 | 100.0/100 |

These are reproducible retrieval diagnostics, not final QA accuracy and not
LoCoMo / LongMemEval official leaderboard scores.

Run a small LoCoMo diagnostic:

```bash
python3 tools/official_memory_benchmark.py \
  --dataset locomo \
  --download \
  --retrieval-mode bm25 \
  --max-conversations 1 \
  --max-questions 50
```

Run LongMemEval oracle diagnostic:

```bash
python3 tools/official_memory_benchmark.py \
  --dataset longmemeval \
  --split oracle \
  --download \
  --retrieval-mode bm25 \
  --max-questions 50
```

The output reports `exact_source_recall`, `near_source_recall`,
`bundled_source_recall`, `session_recall`, and `gold_anchor_recall` at `top_k`.
`near_source_recall` counts adjacent turns separately and must not be reported
as exact evidence. `bundled_source_recall` checks whether the gold source is in
the adjacent raw-turn evidence bundle for the selected anchors; it is also not
an exact-source leaderboard score. The diagnostic does not call a model, write
memory, or claim a LoCoMo / LongMemEval leaderboard score.

## Official QA Trial Artifacts

The benchmark CLI can now also generate answer artifacts in the shape expected
by the official evaluators. This is the next step after evidence retrieval, but
it is still not a public leaderboard score until the official evaluator or judge
has been run.

Generate a LoCoMo-compatible QA output file:

```bash
python3 tools/official_memory_benchmark.py \
  --dataset locomo \
  --download \
  --retrieval-mode fused_library_index_bm25 \
  --qa-trial \
  --qa-output /tmp/memcore-locomo-qa-trial.json
```

The LoCoMo trial writes a JSON file with each QA item carrying:

- `<model_key>_prediction`
- `<model_key>_context`
- `<model_key>_f1`
- `<model_key>_recall`

The local `official_like_local_f1` is a small compatibility check based on the
released LoCoMo scoring logic. Public numbers should still be reported only
after running the LoCoMo official script or an equivalent pinned evaluator
environment.

Generate a LongMemEval v1 hypothesis file:

```bash
python3 tools/official_memory_benchmark.py \
  --dataset longmemeval \
  --split oracle \
  --download \
  --retrieval-mode fused_library_index_bm25 \
  --qa-trial \
  --qa-output /tmp/memcore-longmemeval-hyp.jsonl
```

The LongMemEval trial writes JSONL rows with `question_id` and `hypothesis`,
plus a `memcore_context` debug field. The official score then requires the
LongMemEval evaluator and an evaluator model, for example:

```bash
python3 tools/official_memory_benchmark.py \
  --dataset longmemeval \
  --official-eval-preflight \
  --official-repo /tmp/memcore-official-benchmarks/LongMemEval \
  --hypothesis /tmp/memcore-longmemeval-hyp.jsonl \
  --reference ~/.cache/memcore-cloud/benchmarks/longmemeval/longmemeval_oracle.json \
  --metric-model gpt-4o \
  --summary-json
```

When the official repo, hypothesis file, reference file, and evaluator model
environment are all present, add `--run-official-eval` to execute the official
judge command. Without an evaluator key, this command must report
`blocked_reasons=["metric_model_environment"]` rather than inventing a score.

The underlying official command shape is:

```bash
python3 src/evaluation/evaluate_qa.py \
  gpt-4o \
  /tmp/memcore-longmemeval-hyp.jsonl \
  ~/.cache/memcore-cloud/benchmarks/longmemeval/longmemeval_oracle.json
```

## Codex CLI Internal Judge

If you do not have OpenAI Platform credit, you can still use the local Codex
subscription/account as an internal judge for LongMemEval samples. This uses
`codex exec` and the Codex CLI authentication already present on the machine;
it does not require `OPENAI_API_KEY`.

This is useful for development: you can inspect answer quality, review misses,
and compare retrieval changes before paying for or wiring the official evaluator
path. It is still not an official leaderboard score, because official scores
must use the accepted benchmark evaluator path.

Preflight only:

```bash
python3 tools/codex_memory_judge.py \
  --hypothesis /tmp/memcore-longmemeval-hyp.jsonl \
  --reference ~/.cache/memcore-cloud/benchmarks/longmemeval/longmemeval_oracle.json \
  --max-questions 5 \
  --summary-json
```

Actually call Codex on the sample:

```bash
python3 tools/codex_memory_judge.py \
  --hypothesis /tmp/memcore-longmemeval-hyp.jsonl \
  --reference ~/.cache/memcore-cloud/benchmarks/longmemeval/longmemeval_oracle.json \
  --max-questions 5 \
  --run-codex \
  --summary-json
```

Run a specific Codex judge profile available on this machine:

```bash
python3 tools/codex_memory_judge.py \
  --hypothesis /tmp/memcore-longmemeval-hyp.jsonl \
  --reference ~/.cache/memcore-cloud/benchmarks/longmemeval/longmemeval_oracle.json \
  --max-questions 5 \
  --model <codex-model> \
  --reasoning-effort xhigh \
  --run-codex \
  --summary-json
```

For fixed LongMemEval samples, prefer `--sample-tier` over ad hoc
`--max-questions`. The tiers use `fixed_difficulty_ramp_v1`, which samples
across LongMemEval question types instead of taking only the first rows.

| tier | questions | use |
|---|---:|---|
| `smoke` | 3 | installation and schema check |
| `pilot` | 20 | quick answer-quality read |
| `standard` | 50 | normal local regression |
| `deep` | 100 | stronger diagnostic before public claims |
| `full` | all available | expensive full local judge run |

Example fixed-tier run:

```bash
python3 tools/codex_memory_judge.py \
  --hypothesis /tmp/memcore-longmemeval-hyp.jsonl \
  --reference ~/.cache/memcore-cloud/benchmarks/longmemeval/longmemeval_oracle.json \
  --sample-tier deep \
  --model <codex-model> \
  --reasoning-effort xhigh \
  --run-codex \
  --output-json /tmp/memcore-codex-judge-runs/deep100-codex-internal.json \
  --missed-cases-jsonl /tmp/memcore-codex-judge-runs/deep100-codex-internal-missed.jsonl \
  --summary-json
```

For full 500-question LongMemEval runs, prefer batched judging. A single giant
structured-output call can return an empty item list even when the process exits
successfully; that is a coverage failure, not a meaningful low score.

```bash
python3 tools/codex_memory_judge.py \
  --hypothesis /tmp/memcore-longmemeval-hyp.jsonl \
  --reference ~/.cache/memcore-cloud/benchmarks/longmemeval/longmemeval_oracle.json \
  --sample-tier full \
  --batch-size 50 \
  --model <codex-model> \
  --reasoning-effort xhigh \
  --run-codex \
  --output-json /tmp/memcore-codex-judge-runs/full500-codex-internal.json \
  --missed-cases-jsonl /tmp/memcore-codex-judge-runs/full500-codex-internal-missed.jsonl \
  --summary-json
```

The tool first checks that the hypothesis `question_id` values align with the
reference file. Mismatched artifacts are blocked with
`blocked_reasons=["reference_alignment"]` so a file mix-up does not become a
fake bad score.

The Codex run is controlled for automation with:

```text
codex exec --ignore-user-config --ignore-rules --ephemeral --sandbox read-only
```

Use `--model <codex-model>` when comparing repeated runs. Because this tool uses
`--ignore-user-config`, pass `--reasoning-effort xhigh` explicitly when you want
the high-effort Codex judge profile; do not rely on local defaults.

Boundary:

- `uses_openai_platform_api_key=false`
- `uses_codex_cli_auth=true`
- `score_type=codex_assisted_local_judge_diagnostic`
- `judge_profile` should record the concrete Codex model and reasoning effort
  used for that run.
- `official_leaderboard_score=false`
- `official_evaluator_replacement=false`
- `reference_alignment.ok=true` before model calls

Public wording: it is fair to say Memcore Cloud can run no-key retrieval checks
and can use Codex CLI authentication for internal answer judging when available.
Do not say the result is a LoCoMo / LongMemEval official leaderboard score. The
public evaluator path must still be pinned to the benchmark's accepted
evaluator, model, prompt, data split, and artifact format.

Latest LongMemEval oracle local-judge results on 2026-06-17. LongMemEval's
official evaluator is a yes/no judge and its summary reports both task-averaged
and overall accuracy. The closest internal comparison is therefore
`official-like overall binary`: only `correct` counts. `task-avg binary` is the
mean of per-question-type binary accuracies. `internal half-credit` is kept for
miss analysis because it gives `partial` cases half credit.

| run | tier | questions | task-avg binary | overall binary | internal half-credit | correct | partial | incorrect | coverage |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| context-only baseline | `full` | 500 | 29.6/100 | 26.2/100 | 40.8/100 (0.408) | 131 | 146 | 223 | 500/500 |
| answer synthesis, fixed sample | `standard` | 50 | 85.7/100 | 86.0/100 | 88.0/100 (0.880) | 43 | 2 | 5 | 50/50 |
| answer synthesis, one-shot | `full` | 500 | unusable | unusable | unusable | 0 | 0 | 0 | 0/500 |
| answer synthesis, batched 10x50 | `full` | 500 | 32.5/100 | 28.8/100 | 34.3/100 (0.343) | 144 | 55 | 301 | 500/500 |
| answer synthesis synth6, fixed sample | `standard` | 50 | 97.9/100 | 98.0/100 | 99.0/100 (0.990) | 49 | 1 | 0 | 50/50 |
| answer synthesis synth6, batched 10x50 | `full` | 500 | 37.0/100 | 33.6/100 | 37.5/100 (0.375) | 168 | 39 | 293 | 500/500 |
| answer synthesis synth7, fixed sample | `standard` | 50 | 100.0/100 | 100.0/100 | 100.0/100 (1.000) | 50 | 0 | 0 | 50/50 |
| answer synthesis synth7, batched 10x50 | `full` | 500 | 38.5/100 | 35.6/100 | 39.8/100 (0.398) | 178 | 42 | 280 | 500/500 |
| answer synthesis synth8, fixed sample | `standard` | 50 | 93.8/100 | 94.0/100 | 95.0/100 (0.950) | 47 | 1 | 2 | 50/50 |
| answer synthesis synth8, batched 10x50 | `full` | 500 | 40.9/100 | 37.6/100 | 42.0/100 (0.420) | 188 | 44 | 268 | 500/500 |
| answer synthesis synth9, fixed sample | `standard` | 50 | 97.9/100 | 98.0/100 | 98.0/100 (0.980) | 49 | 0 | 1 | 50/50 |
| answer synthesis synth9, batched 10x50 | `full` | 500 | 41.5/100 | 38.2/100 | 41.8/100 (0.418) | 191 | 36 | 272 | 500/500 |
| answer synthesis synth10, fixed sample | `standard` | 50 | 100.0/100 | 100.0/100 | 100.0/100 (1.000) | 50 | 0 | 0 | 50/50 |
| answer synthesis synth10, batched 10x50 | `full` | 500 | 41.2/100 | 38.4/100 | 42.8/100 (0.428) | 192 | 44 | 264 | 500/500 |
| answer synthesis synth11, batched 10x50 | `full` | 500 | 42.1/100 | 39.2/100 | 42.7/100 (0.427) | 196 | 35 | 268 | 500/500 |
| answer synthesis synth13, fixed sample | `standard` | 50 | 100.0/100 | 100.0/100 | 100.0/100 (1.000) | 50 | 0 | 0 | 50/50 |
| answer synthesis synth13, batched 10x50 | `full` | 500 | 42.2/100 | 39.4/100 | 43.7/100 (0.437) | 197 | 43 | 259 | 500/500 |
| answer synthesis synth14, batched 10x50 | `full` | 500 | 44.6/100 | 42.6/100 | 46.5/100 (0.465) | 213 | 39 | 248 | 500/500 |
| answer synthesis synth15, batched 10x50 | `full` | 500 | 46.3/100 | 45.8/100 | 49.1/100 (0.491) | 229 | 33 | 238 | 500/500 |

Artifacts are local diagnostics. Keep them with the run ledger and concrete
model profile that produced them; do not treat local artifact paths as public
benchmark evidence.

Scores are computed from per-item verdicts (`score_source=item_verdicts`)
because the model-written summary can be inconsistent with the item list,
especially on large runs. Coverage is part of the score contract: a run with
`item_count=0` and `expected_item_count=500` must be treated as unusable even if
the process returned successfully.

Every Codex judge result now also carries `layered_score_report`. This is a
diagnostic map, not a new official score. It says which layer the current run
actually measured and which layer still needs a separate harness. In the Codex
judge path, `answer_synthesis_score`, `gap_score`, and the missed-case
self-improvement loop can be measured from item verdicts and failure buckets.
`retrieval_score`, `projection_score`, `preflight_score`,
`progressive_retrieval_score`, and `ingestion_quality_score` stay explicitly
`not_measured` unless a run includes the right traces. This keeps us from
pretending that one LongMemEval answer number explains the whole memory system.

Current interpretation: retrieval is already strong in the no-key suite, but
answer quality is the bottleneck. The first answer-synthesis pass can look very
good on a fixed 50-question sample, but the full 500-question run exposes long
tail failures. Synth6 adds insufficient-information gates and a named-book
remaining-pages extractor; it fixes cases like `The Nightingale` remaining
pages while refusing to guess missing `Sapiens` remaining pages. Synth7 adds a
source-date-aware temporal extractor that uses explicit dates, relative dates
such as `three weeks ago`, and session timestamps only as fallback evidence.
Synth8 adds targeted short-answer, duration, money, latest-state, and small
numeric extraction. Synth9 adds regression guards for aggregate and
missing-object cases, but overconstrains some after-start day differences.
Synth10 repairs only the narrow `after starting / after I bought / after I
ordered` day-difference patterns, recovering cases such as house search,
laptop backpack arrival, and remote shutter release delivery while keeping the
camping and bike aggregate guards. Synth11 added missed-case bucketing and a
first object-bound aggregation pass; it fixed some hard count cases but exposed
over-counting when assistant summaries were treated like raw user facts.
Synth13 tightens that path by inferring `user:` / `assistant:` text prefixes,
trusting user facts first, and only applying narrow object-bound aggregation
when all named objects are present. Synth14 adds temporal long-tail operators
for relative dates, compound durations, and first/which-happened-first event
questions. Synth15 adds another object-bound aggregation pass for concrete
counts and money sums, with missing-information gates for several `_abs`
counterfactual questions. Synth15 is the current best complete full=500 local
Codex diagnostic.

The latest complete full run still misses 271 cases: 88 temporal-long-tail, 68
multi-session-object-aggregation, 43 latest-state, 26
assistant-context-extraction, 20 preference-direct-answer, 20
single-fact-extraction, and 6 other cases. Compared with synth14, synth15 cut
multi-session-object-aggregation misses from 87 to 68 and lifted multi-session
binary accuracy from 21.1/100 to 35.3/100, while temporal and latest-state
remain the largest next targets. Next work should focus on source-date aware
temporal long tails such as `days ago`, `months ago`, and `how long had I
been...`, stronger latest-fact selection, remaining object-bound count/sum
operators, and turning relevant copied context into direct preference or
assistant answers. Do not advertise the standard=50 score as the full-system
level.

LongMemEval-V2 is a different path: it needs a memory backend implementing the
official `Memory.insert()` / `Memory.query()` interface, complete `web` and
`enterprise` harness runs, then the official leaderboard packaging scripts.

Retrieval modes:

- `keyword`: the original lightweight TF-IDF-style scorer.
- `bm25`: a deterministic BM25 scorer; currently strongest on LongMemEval
  oracle exact-turn retrieval.
- `rrf`: reciprocal-rank fusion of keyword and BM25. It can improve broad
  anchor/session coverage, but should be checked against `exact_source_recall`
  before being treated as better.
- `context_bm25`: BM25 plus adjacent raw-turn expansion inside the same
  session. It tests whether preserved raw context can recover exact evidence
  that sits next to the lexical hit. `--context-decay` controls how much an
  adjacent raw turn is discounted; the default is the conservative `0.50`.
- `routed_context_bm25`: a first deterministic route. Cases with at least
  `--context-route-unit-threshold` source units use the aggressive decay
  (`--context-route-aggressive-decay`, default `0.84`); smaller cases use the
  conservative `--context-decay`. Route counts are printed in the result.
- `diverse_context_bm25`: a diagnostic mode that keeps one candidate per
  session before filling remaining slots. It measures anchor/session coverage
  risk when adjacent raw turns crowd out other sessions; it is not the current
  exact-source default.
- `anchored_context_bm25`: BM25 anchor ranking plus adjacent raw-turn evidence
  bundles. It keeps exact-source and gold-anchor metrics identical to BM25, and
  reports the extra coverage through `bundled_source_recall`.
- `hierarchical_bm25`: session/L1 candidate selection first, then turn/L2 BM25
  ranking inside the selected sessions.
- `typed_context_bm25`: transparent question-type routing. It keeps a
  conservative adjacent-context route for LongMemEval and LoCoMo type 1/2/3
  questions, while LoCoMo type 4/5 inferential questions use a stronger
  adjacent-context route. Route counts are printed so the score is auditable.
- `library_index_bm25`: diagnostic two-step retrieval using Library Index
  Projection / 馆藏目录投影 as navigation-only L1, then ranking raw L2 turns in
  selected sessions. It is useful as a failure probe, but not a default because
  hard session filtering can drop valid raw anchors.
- `fused_library_index_bm25`: typed context retrieval remains the raw-turn
  baseline, while Library Index Projection only supplies a small session-level
  rerank hint. Final evidence must still be raw turns.

Latest full-data diagnostic run on 2026-06-16:

| dataset | mode | top5 exact | top5 bundled | top5 near | top5 gold anchor |
|---|---|---:|---:|---:|---:|
| LoCoMo locomo10 | keyword | 0.6014 | 0.7381 | 0.1367 | 0.8708 |
| LoCoMo locomo10 | bm25 | 0.5848 | 0.7472 | 0.1625 | 0.8850 |
| LoCoMo locomo10 | anchored_context_bm25 | 0.5848 | 0.7472 | 0.1625 | 0.8850 |
| LoCoMo locomo10 | typed_context_bm25 | 0.6544 | 0.8184 | 0.1095 | 0.8819 |
| LoCoMo locomo10 | library_index_bm25 | 0.6458 | 0.7770 | 0.0888 | 0.8320 |
| LoCoMo locomo10 | fused_library_index_bm25 | 0.6650 | 0.8234 | 0.1085 | 0.8829 |
| LoCoMo locomo10 | rrf | 0.5969 | 0.7462 | 0.1493 | 0.8784 |
| LoCoMo locomo10 | context_bm25, window=1, decay=0.50 | 0.6246 | 0.7558 | 0.1312 | 0.8819 |
| LoCoMo locomo10 | context_bm25, window=1, decay=0.84 | 0.6524 | 0.7492 | 0.0969 | 0.8456 |
| LoCoMo locomo10 | routed_context_bm25, threshold=100 | 0.6524 | 0.7492 | 0.0969 | 0.8456 |
| LoCoMo locomo10 | diverse_context_bm25, decay=0.84 | 0.4546 | 0.6529 | 0.1983 | 0.9026 |
| LongMemEval oracle | keyword | 0.6500 | 0.8820 | 0.2320 | 1.0000 |
| LongMemEval oracle | bm25 | 0.8140 | 0.8960 | 0.0820 | 1.0000 |
| LongMemEval oracle | anchored_context_bm25 | 0.8140 | 0.8960 | 0.0820 | 1.0000 |
| LongMemEval oracle | typed_context_bm25 | 0.8260 | 0.9120 | 0.0640 | 1.0000 |
| LongMemEval oracle | fused_library_index_bm25 | 0.8260 | 0.9120 | 0.0640 | 1.0000 |
| LongMemEval oracle | rrf | 0.7540 | 0.9000 | 0.1460 | 1.0000 |
| LongMemEval oracle | context_bm25, window=1, decay=0.50 | 0.8280 | 0.8920 | 0.0640 | 1.0000 |
| LongMemEval oracle | routed_context_bm25, threshold=100 | 0.8280 | 0.8920 | 0.0640 | 1.0000 |
| LongMemEval oracle | diverse_context_bm25, decay=0.50 | 0.8180 | 0.9000 | 0.0820 | 1.0000 |

Reading:

- Conservative `context_bm25` improves LoCoMo and LongMemEval top5 exact-source
  recall in this diagnostic, which supports the raw-record premise: adjacent
  turns often carry the answer even when the lexical hit is one turn away.
- Aggressive context expansion can lift LoCoMo exact-source recall further, but
  may lower broader anchor coverage and hurt LongMemEval. Keep the decay
  visible in reports instead of treating context expansion as a free gain.
- The first routed mode uses source-unit count as a transparent proxy: in this
  run LongMemEval routed all 500 cases to `small_raw_context`, while LoCoMo
  routed all 1,986 cases to `large_raw_context`. This is a reproducible
  diagnostic route, not a learned router.
- `diverse_context_bm25` confirms the tradeoff: preserving session diversity can
  lift LoCoMo gold-anchor recall to 0.9026, but drops exact-source recall to
  0.4546. Keep it as a coverage-risk diagnostic until the router can decide
  when anchor coverage matters more than exact-turn ranking.
- `anchored_context_bm25` is the closest shape to a borrowing receipt: keep the
  ranked anchors stable, attach adjacent raw evidence bundles, and report
  `bundled_source_recall` separately. On LoCoMo it keeps BM25 exact/gold-anchor
  recall unchanged while lifting top5 bundled coverage from the exact 0.5848 to
  0.7472.
- `typed_context_bm25` is the first route that meaningfully improves LoCoMo
  exact-source recall without taking the full aggressive-context anchor hit:
  top5 exact rises from BM25's 0.5848 to 0.6544, while gold-anchor recall is
  0.8819. Its bundled-source recall uses each result's routed evidence window,
  so the top5 bundled coverage is 0.8184 on LoCoMo and 0.9120 on LongMemEval
  oracle. Treat it as a transparent diagnostic route, not a learned router.
- LoCoMo normalization now indexes turn-level media/query fields from the raw
  JSON (`query`, `blip_caption`, `img_url`) alongside text. This is not a new
  knowledge layer; it is raw-record preservation becoming searchable. It lifted
  LoCoMo typed top5 bundled coverage from 0.8047 to 0.8184 and gold-anchor
  recall from 0.8744 to 0.8819.
- `library_index_bm25` proves the boundary: Library Index Projection should not
  replace raw-turn retrieval. Hard filtering LoCoMo sessions lowers top5 exact
  to 0.6458 and gold anchor to 0.8320. The useful shape is fusion:
  `fused_library_index_bm25` keeps raw-turn typed retrieval and only applies a
  small session hint, lifting LoCoMo top5 exact to 0.6650 and bundled coverage
  to 0.8234 while LongMemEval remains unchanged.

Next steps:

- Generate official answer files for LoCoMo / LongMemEval v1.
- Run each benchmark's evaluator or judge path.
- Implement the LongMemEval-V2 memory backend interface and submit only after
  the official harness produces a complete submission package.
