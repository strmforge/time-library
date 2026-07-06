# Concepts And Five Shelves

This page explains the product model behind Time Library. The README should stay feature-first; this wiki page is where the deeper continuity model belongs.

## Continuity Model

Time Library separates two kinds of long-lived context:

- **Memory**: what the AI should remember about the user, project, preferences,
  decisions, corrections, and context.
- **Experience**: what the AI should reuse about how work gets done, including
  repeatable fixes, review steps, project rules, gotchas, validation paths, and
  rollback notes.

Memory helps an agent understand the user. Experience helps an agent do the next task better.

The two should connect, but they should not collapse into one bucket. A user
preference may influence work experience, but a preference is not a procedure.
A validated procedure may cite user preferences, but it remains work
experience.

## Raw Records First

Original records are the source of truth.

Summaries, indexes, knowledge cards, and compact recall help navigation, but
they must not replace source records. When the system answers from memory or
experience, it should be able to point back to source refs, raw excerpts,
record ids, collection ids, receipts, or rank reasons.

That is why the first trust demo is Record Doctor: before asking users to trust
recall, show that the record chain is guarded.

## The Five Shelves

Time Library keeps AI-readable knowledge sediment inside five existing
shelves. It should not add a sixth Obsidian-like layer just because markdown
knowledge bases are useful.

| Shelf | Role | Examples |
| --- | --- | --- |
| `raw` | Original records and source material | Conversation records, local tool traces, imported source text, raw excerpts |
| `zhiyi` | Preference, intent, corrections, and stable understanding | User likes concise answers; project A must not change LAN access; a prior interpretation was wrong |
| `xingce` | Work experience, methods, validation paths, and adoption state | How to validate a Windows install; how to split a module under Tiandao boundaries; known repair sequence |
| `toolbook` | Tool-facing usage knowledge and operational notes | How a local tool stores data; how to run a safe capability check; known platform facts |
| `errata` | Corrections, conflicts, and trust repair | Wrong memory corrections; source conflicts; rejected or superseded experience |

The shelves are not marketing names for different databases. They are reading
and trust boundaries.

## AI-Readable Knowledge Sediment

Markdown-style knowledge works well for AI because it is plain text, easy to
diff, easy to link, and easy to inspect. Time Library borrows that shape
without requiring a note app integration.

The useful pattern is:

- index first, detail second;
- source refs before summary claims;
- links between concepts, records, and experience;
- receipts for validation and adoption;
- progressive disclosure instead of dumping every raw record into context.

In practice, this means a page, card, or index should let an agent answer:

- What is this about?
- Which shelf owns it?
- What source record supports it?
- Is it a candidate, accepted, rejected, superseded, or needs review?
- What should the agent read next if more evidence is needed?

## Library Projections

The note-like view is a projection of the five shelves, not a separate
Obsidian-style knowledge layer.

Two names are used for this direction:

- **Library Note Projection / 馆藏注记**: an AI-readable note view of one
  record, concept, preference, experience, tool fact, or erratum.
- **Library Index Projection / 馆藏目录投影**: an index-first view that helps
  agents see what exists before opening details.

These projections may look like Markdown knowledge pages because Markdown is
easy for both humans and agents to read. Authority still comes from the owning
shelf and its source refs. If a projection disagrees with raw records or a
receipt, the projection is the thing to repair.

## Reading Area And Whiteboard Preview

The local runtime also has a preview of project-scoped projections:

- Reading Area: a read-only project page that shows scoped lanes across local
  agent windows without exposing raw bodies by default.
- Whiteboard: a project handoff/claim registry projection, not a sixth shelf.
- Project History: project-level progress records that appear in project pages,
  not in the five shelves.

These are projections over the existing source records and registries. They do
not change the five shelf model. Current proof and boundaries are tracked in
[Local Runtime Preview](Local-Runtime-Preview.md).

## Recall Volume

Recall should be quiet by default.

The first response should usually include compact source refs, counts, receipts,
and rank reasons. Raw excerpts are useful, but they should be explicit and
bounded. A wall of memory can hide the signal and make the agent worse at the
task.

## Experience Evolution

Experience should move through a lifecycle rather than becoming permanent
because one model wrote it once.

A healthy experience flow is:

1. Candidate: an execution or review suggests a reusable lesson.
2. Evidence: the candidate carries source refs and receipts.
3. Review: a user or validator checks whether it is useful and safe.
4. Adoption: accepted experience enters the correct shelf with a receipt.
5. Reuse: future agents can recall it with rank reasons.
6. Repair: errata, rollback, supersede, or rejection stays visible.

This is why Xingce is not a skill marketplace. It is the work-experience shelf
and its governance path.

## Public Copy Boundary

The GitHub README should lead with concrete user-visible features:

- shared local context;
- automatic local records;
- source-backed recall;
- reusable work paths;
- Record Doctor;
- local console;
- no cloud account required;
- simple install.

The deeper explanation on this page should stay in the wiki unless a user is
already evaluating how the system works.

## 中文

README 负责讲清楚用户能直接得到什么：有什么功能、怎么安装、怎么安全验证。理念和体系解释放在 Wiki。

忆凡尘的核心能力可以分成两类：**记忆** 和 **经验**。

- **记忆**：用户偏好、项目背景、纠偏、旧决定、上下文。
- **经验**：做事方法、排障顺序、复核步骤、项目规矩、踩坑记录、验收办法。

记忆让 AI 更懂你；经验让 AI 下次更会做事。

底线是：原始记录是最高事实。摘要、索引、卡片和紧凑召回只能帮助浏览，不能替代原文。召回最好默认给来源线索、计数、回执和命中理由；只有明确需要原文时，才展开有界摘录。

## 五层书架

| 书架 | 作用 | 例子 |
| --- | --- | --- |
| `raw` | 原始记录和来源材料 | 对话记录、工具痕迹、导入文本、原文摘录 |
| `zhiyi` | 偏好、意图、纠偏、稳定理解 | 喜欢简短回答；某项目不能改 LAN；某条记忆理解错了 |
| `xingce` | 工作经验、方法、验证路径、采纳状态 | Windows 安装怎么验；模块怎么按天道边界拆；已知修复顺序 |
| `toolbook` | 工具使用知识和平台事实 | 某工具如何存数据；安全能力检查怎么跑 |
| `errata` | 纠错、冲突、信任修复 | 错误记忆、来源冲突、被拒绝或废弃的经验 |

这五层就是 AI 可读知识沉积的位置，不需要再造一个类似 Obsidian 的第六层。Obsidian/Markdown 的启发在于：纯文本、可链接、可 diff、AI 好读；不是说忆凡尘要变成 Obsidian 集成。

馆藏注记 / Library Note Projection 和馆藏目录投影 / Library Index Projection
就是这个方向的名字：它们是五层书架的 AI 可读投影，不是新书架。看起来可以像 Markdown
笔记，但可信度来自对应书架的 source refs、raw 记录、回执和采纳状态。投影和原始记录冲突时，
修投影，不改事实来源。

阅读区、白板和项目史也是投影：阅读区是项目范围的只读多窗口车道视图；白板是交接/认领登记；
项目史是项目页里的进展记录。它们都不是第六个书架。当前本机运行态证明和边界见
[Local Runtime Preview](Local-Runtime-Preview.md)。

行策不是技能市场。它更像经验的生命周期：候选、证据、复核、采纳、复用、纠错或回滚。每一步都应该带来源和回执。
