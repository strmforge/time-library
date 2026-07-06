# Reading Room and Whiteboard

When several AI agents work on one machine, the hard part is not storing memory — it is letting them share the same project state without a human copying context between them. The reading room and the whiteboard are how Time Library does that.

## Reading room

The reading room is a shared, read-only workspace for the agents on one machine. It is a project memory pool that multiple agents (for example Codex, an Opus reviewer, and other local tools) can read.

- **Catalog, not content.** On entry an agent receives a *booklist* — collection ids, shelves, and lane counts — a map of what exists, not a dump of raw text into its window. This keeps recall low-contamination; the agent borrows a specific card by id when it actually needs the words.
- **Members self-report.** Borrow records show which agent read what, so the pool stays auditable and traceable back to source.
- **Arbitration stays with you.** The pool surfaces state and disagreements; it does not silently decide them. Rulings happen where you already are, not in a hidden backend.

The goal is to replace hand relay: instead of you repeating "here's where the project stands" to each new agent window, the agents read it from the same pool.

## Whiteboard

Inside the reading room, the whiteboard is the project progress board.

- A vertical route of the overall project (what is done, what is in flight, what is next), with the current stage highlighted.
- Click a stage to drill into its detail — the step flow (dispatch → build → review → installed → runtime → close), who owns it, and where "now" is.
- In-flight tasks and review boundaries live on the same picture, so a new agent can see where a project actually stands instead of asking you.

Reading room = the shared space. Whiteboard = the progress board inside it.

## 中文

一台机器上多个 AI agent 干活，难的不是存记忆，而是让它们共享同一份项目状态、不用人在中间搬上下文。阅读室和白板就是干这个的。

**阅读室**：一台机器上多个 agent（比如 Codex、Opus 二签、其他本机工具）共读的**只读**项目记忆池。

- **推书单，不灌正文。** 进来只给*书单*——馆藏号、书架、lane 计数——一张“有什么”的地图，不往窗口里倒原文；真要原话时按编号借具体那张卡。这样召回低污染。
- **成员自报。** 借阅记录显示哪个 agent 读了什么，池子可审、可回源。
- **仲裁归你。** 池子只呈现状态和分歧，不替你偷偷裁决；决定在你本来就在的地方定，不在隐藏后台。

目标是替代人肉转达：不用你对每个新窗口重复“项目到哪了”，agent 从同一个池子读。

**白板**：阅读室里那块项目进度板。

- 竖版项目总进度（做完了什么、在飞什么、下一步什么），当前阶段高亮。
- 点某阶段下钻看详情——步骤流（派单 → 施工 → 二签 → installed → runtime → 收口）、谁负责、“现在”在哪一步。
- 在飞任务和二签边界都在同一张图上，新来的 agent 一眼看到项目到哪了。

阅读室=共享空间；白板=里面那块进度板。
