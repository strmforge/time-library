# Why Time Library

Most "AI memory" tools store a summary and hand it back later. Time Library is built on a stricter idea: memory is only trustworthy if it can point back to the original words, know when it was true, and prove it was used.

## Three things most memory tools don't do

1. **Source-provenance, not paraphrase.** Every remembered card traces back to the byte offset of the original record. Summaries are treated as navigation; the raw record stays the authority. Recall answers with source refs first and expands to raw excerpts only when you ask. It is not "I think I remember" — it is "here is the original, at this line."
2. **It keeps time, not just text.** Ordered timestamps and the raw → daily → digest sediment preserve the foundation for historical views. A public as-of / time-travel query endpoint does not ship yet.
3. **Many agents, one low-noise pool — no human relay.** On one machine, several agents (Codex, Claude, OpenClaw, Hermes) read a shared, read-only, traceable project memory. Startup hands out a *catalog* — a booklist / map — not a dump of content into your window, so recall stays low-contamination. You stop being the middleman who repeats context between tools.

## Why not just use Cognee (or Mem0)?

Cognee is the most serious incumbent. The difference is not feature count:

- Time Library prioritizes the **original source + timestamp + delivery/use receipt fields** in one local pool. Those fields do not yet prove model-in-the-loop delivery on every platform.
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
- that Hermes auto-adopts production experience, or that unattended background fire-through has been observed — a controlled run-once is proven and the bounded scheduler is implemented;
- that one vector model is universally better — Granite has a local shadow evaluation, not a public benchmark;
- fully autonomous self-training — experience evolution is curated, with review and receipts.

Every change ships in separate proof layers — source/test, local preview, installed runtime, cross-machine, release — signed separately, so "it clicks" is never mistaken for "it works."

## 中文

大多数“AI 记忆”工具存一段摘要、之后再还给你。时间图书馆的底线更严：记忆只有能回到原话、知道是什么时候的、并证明被用上了，才值得信。

**三件别人不做的事：**

1. **回源，不是转述。** 每张记忆卡都能回到原始记录的 byte 级出处；摘要当导航，原始记录当权威。召回默认先给 source refs，需要原文时才展开。不是“我好像记得”，而是“原话在这，第几行”。
2. **它保存时间，不只保存文字。** 有序时间戳与 raw → 日 → 摘要沉积，为历史视图保留地基；当前还没有对外可用的 as-of / 时间旅行查询入口。
3. **多 agent 共读一块低污染池，免人肉转达。** 一台机器上多个 agent 共读只读、可回源的项目记忆；开局推**书单**（地图）不灌正文，你不用再当工具之间重复上下文的中间人。

**为什么不直接用 Cognee（或 Mem0）？** 设计重点不同：时间图书馆保留原话出处与时间，让多 agent 共读一块本机池，并携带送达/使用回执字段；这些字段目前还不能证明所有平台上的模型都已真正收到。MemGPT/Letta 各管各的 core memory，它是共享池；Trellis 记项目计划，它记机器经验（带回源、跨项目、自动捕获）。回源不是装饰——本项目消融里去掉双层/回源掉 13.31 分。

**给谁用：** 给 **AI agent**，不是给人（人的记忆比它靠谱）。agent 的工作就是它的经验：偏好纠错沉淀进偏好层，排障路径与验收沉淀进经验层；经验是本机共享参考，不是某个 agent 的私有 skill。

**诚实边界：** 已证——可回源逐字召回、混合检索、多 agent 阅读室、借阅记录、开局注书单、能切默认召回路由的模型开关。**不声称**：跨机同步已完成（现为设计审计/部分远端源）；Hermes 候选会自动采纳进生产或无人值守 fire-through 已被观察到（受控 run-once 已证、受限调度器已实现）；Granite 普遍优于其他模型（只有本机影子评测）；7 个平台的模型内送达已证明（当前 `0/7`）；全自动自训。每次改动分层签署，不把“能点”当“已生效”。
