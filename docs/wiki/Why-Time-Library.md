# Why Time Library

Most "AI memory" tools store a summary and hand it back later. Time Library is built on a stricter idea: memory is only trustworthy if it can point back to the original words, know when it was true, and prove it was used.

## Three things most memory tools don't do

1. **Source-provenance, not paraphrase.** Every remembered card traces back to the byte offset of the original record. Summaries are treated as navigation; the raw record stays the authority. Recall answers with source refs first and expands to raw excerpts only when you ask. It is not "I think I remember" — it is "here is the original, at this line."
2. **It is time.** As-of queries, time travel, and a raw → daily → digest sediment are its nature, not a bolted-on feature. You can ask what the system believed on a given day. That is why it is a *library of time*.
3. **Many agents, one low-noise pool — no human relay.** On one machine, several agents (Codex, Claude, OpenClaw, Hermes) read a shared, read-only, traceable project memory. Startup hands out a *catalog* — a booklist / map — not a dump of content into your window, so recall stays low-contamination. You stop being the middleman who repeats context between tools.

## Why not just use Cognee (or Mem0)?

Cognee is the most serious incumbent. The difference is not feature count:

- Cognee / Mem0 store and inject **summaries / content**. Time Library stores the **original source + the time + proof of delivery and use**.
- Mem0 / Cognee push content into the window at startup. Time Library pushes a **catalog** (a map, not the territory) — lower contamination.
- MemGPT / Letta keep a small core memory **per agent**. Time Library is a **shared** pool across agents on the machine.
- Trellis keeps repo-level project **plans**. Time Library keeps the machine's **experience**, with provenance, cross-project reach, and automatic capture.

Provenance is not decoration. In ablation, removing the two-layer / source path costs 13.31 points.

## Who it is for

Time Library is for **AI agents**, not for humans (your own memory is more reliable than any tool). An agent's work is its experience: preferences and corrections settle into the preference shelf; repair paths and acceptance checks settle into the work-experience shelf. Experience is a shared local reference, not one agent's private skill.

## Honest status (what we do and don't claim)

Proven today: source-exact recall, hybrid search, the multi-agent reading room, borrow records, catalog-on-startup, and a model switch that changes default recall routing.

We do **not** claim:

- that cross-machine sync is finished — it is at design-audit / partial-remote-source;
- that Hermes auto-adopts production experience — the autonomous loop runs as a registered, value-gated background agent (wakes hourly, at least 24h between real triggers, one run per day), bounded and never burning idle cycles, but adoption into production experience is a separate, closed gate;
- that the vector (bge-m3) switch improves recall quality — only that it changes default recall routing;
- fully autonomous self-training — experience evolution is curated, with review and receipts.

Every change ships in separate proof layers — source/test, local preview, installed runtime, cross-machine, release — signed separately, so "it clicks" is never mistaken for "it works."

## 中文

大多数“AI 记忆”工具存一段摘要、之后再还给你。时间图书馆的底线更严：记忆只有能回到原话、知道是什么时候的、并证明被用上了，才值得信。

**三件别人不做的事：**

1. **回源，不是转述。** 每张记忆卡都能回到原始记录的 byte 级出处；摘要当导航，原始记录当权威。召回默认先给 source refs，需要原文时才展开。不是“我好像记得”，而是“原话在这，第几行”。
2. **它本身就是“时间”。** as-of 查询、时间旅行、raw → 日 → 摘要的时间沉积是本分不是外挂。你能问“某一天系统当时信的是什么”。所以它叫**时间**图书馆。
3. **多 agent 共读一块低污染池，免人肉转达。** 一台机器上多个 agent 共读只读、可回源的项目记忆；开局推**书单**（地图）不灌正文，你不用再当工具之间重复上下文的中间人。

**为什么不直接用 Cognee（或 Mem0）？** 它们存/灌摘要与内容；时间图书馆存原话出处 + 时间 + 送达/使用证据，且多 agent 共读一块。MemGPT/Letta 各管各的 core memory，它是共享池；Trellis 记项目计划，它记机器经验（带回源、跨项目、自动捕获）。回源不是装饰——消融里去掉双层/回源掉 13.31 分。

**给谁用：** 给 **AI agent**，不是给人（人的记忆比它靠谱）。agent 的工作就是它的经验：偏好纠错沉淀进偏好层，排障路径与验收沉淀进经验层；经验是本机共享参考，不是某个 agent 的私有 skill。

**诚实边界：** 已证——可回源逐字召回、混合检索、多 agent 阅读室、借阅记录、开局注书单、能切默认召回路由的模型开关。**不声称**：跨机同步已完成（现为设计审计/部分远端源）；Hermes 会自动把经验采纳进生产（自主环以受价值门控的后台常驻运行：每小时醒、真触发至少隔 24h、每日 1 次，有界不空烧，但采纳进生产经验是另一道默认关闭的硬门）；bge 开关提升召回质量（只说能改路由）；全自动自训（经验进化是可审计采编，有评审有回执）。每次改动分层签署，不把“能点”当“已生效”。
