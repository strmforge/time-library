# Yifanchen Update History

This page keeps the longer release highlights out of the README homepage. For the current release, see [RELEASE_NOTES_2026.5.31.md](RELEASE_NOTES_2026.5.31.md). For engineering-level changes, see [CHANGELOG.md](CHANGELOG.md).

## 中文

### 2026.5.31

- **自然语言纠错入口**：当用户在原来的 AI 工具里说“这条记错了”“你理解偏了”“不是我的意思”时，忆凡尘会把它识别为勘误候选，而不是继续当作普通偏好写入。
- **方法信号候选**：外部资讯、工具仓库和实践反馈可以先进入 `external_method_signal_candidate` dry-run，作为“新方法是否值得沉淀”的候选，不直接安装或激活。
- **Agent 安装闭环**：README 提供可直接发给 AI agent 的安装提示；安装器会自动安装 Codex skill，并在检测到 Codex CLI 时注册 `yifanchen-zhiyi` MCP，用户不需要先理解 Skill 或 MCP。
- **Hermes 学习心跳**：新增只读 native learning liveness 检查，报告最近是否有 Hermes `background_review`、`skill_manage` 和 skill 文件变化，帮助区分“会被触发时能学”和“这几天自然链路冷掉了”。
- **Hermes 消费回执**：按 Hermes 官方 MemoryProvider 生命周期补齐 `sync_turn` 回执和 `queue_prefetch` 预热；`sync_turn` 回执走后台线程，避免阻塞 Hermes hook。Hermes 不复制 OpenClaw 的 before-dispatch 拦截形态，但每轮可以记录“是否召回、命中多少、是否进入 turn 后回执”。
- **Hermes 技能与经验对比升级**：新增只读 `skill-experience-diff` dry-run，把 Hermes 生成或修改的 skill 与忆凡尘现有经验对照，产出待审 adoption / upgrade 候选；不直接写 Hermes skill，也不直接写正式经验。
- **状态账本 / 时间索引**：新增只读 dry-run，回答“当前最新可信判断是什么”，同时把已采用、待复核、已废弃、被替代和冲突记录放在同一条时间线上；时间索引只是导航，不替代 raw。
- **上下文预算最小单元**：新增 `context_budget_unit_candidate` dry-run，把纠错、工具事实、方法信号、工作经验等整理成可回源、可组合、可过期复核的上下文最小单元；“粒子/离子”命名仍按待核验方向处理，不写成已确认原话。
- **模型事实只读方向**：忆凡尘读取 OpenClaw / Hermes / Codex 已有模型配置供自己判断和测试，不写回平台，不把自己做成模型中心。

### 2026.5.30

- **真实任务集 benchmark**：新增多案例 dry-run，用同一批真实任务形状对比无记忆、只有知意、知意加行策，先看信号质量，再决定是否建设 Replay 反哺队列。
- **偏好提取更谨慎**：新增偏好意图 gate。用户纠错、指代澄清、转述审计材料和创作提示不会因为出现“称呼”“偏好”等词就被写成长期知意偏好。
- **Windows 大样本实测**：施工版已在 Windows 本地服务上做运行测试，验证 Web、Replay/benchmark、MCP、OpenClaw raw 查询、source_refs 和错误日志状态。

### 2026.5.29

- **知行图书馆**：原始记忆是底本，知意是理解类馆藏，行策是工作经验和工具书。图书馆里不只放“懂你”的书，也放能指导做事的工具书。
- **召回可解释**：召回结果会带 `library_id`、书架、来源、命中方式和排序理由，方便知道这条经验为什么被带出来。
- **行策对象生产化**：行策候选开始按工作场景、行动策略、禁用条件、验收方式和生命周期整理。
- **轻量图谱与混合召回契约**：先提供用户、项目、平台、任务、偏好、工作经验这些节点和强关系，配合 source_refs、关键词、向量可用状态和项目过滤。
- **效果回放计划**：新增只读回放计划，用同一批任务对比无记忆、只有知意、知意加行策的差异。
- **知行闭环 dry-run**：7 步流程穿过五书架，并用确定性规则检查 4 个防御指标和 1 个进攻指标；回放后生成待审反哺候选，不自动写入正式经验。
- **使用回执**：每次召回都会说明用了哪些馆藏号、哪些来源、为什么命中，以及本轮没有写入平台。
- **工具书候选入口**：平台事实、环境差异和命令实测可以先生成工具书候选；当前是 dry-run / validate，不直接写入馆藏。
- **Codex 本地接入**：读取本机 Codex 会话记录，进入同一个本地记忆底座。
- **通用知意入口**：新窗口可以用 `/zhiyi` 接上前情；英文环境可用 `/memory`、`/recall`、`/continue` 或 `catch me up`。
- **Skill / MCP 接入**：提供平台中立的 `yifanchen-zhiyi` Skill，以及只读的 `zhiyi_recall` 召回入口。
- **能力检查模式**：安装和冒烟测试可以用 `mode=capability_check` 验证 Skill / MCP / 只读状态，不触发召回、不返回原文。
- **共享记忆底座**：OpenClaw、Hermes、Codex 可以使用同一套本地原始记忆，但各自窗口和 agent 仍分开管理。
- **增量与续读**：正在增长的会话文件从上次位置继续读取，旧记录回源时支持分段补查。
- **来源可回看**：知意经验带馆藏号、状态和来源线索，尽量回到原话出处。
- **行策说明补齐**：行策作为工作经验层，负责把做事过程里的经验沉淀成下一次可参考的路径。
- **本地网关加固**：只读召回网关显式限制本机回环访问，并防止续读状态误写入平台配置目录。

更多早期版本见 [RELEASE_NOTES_2026.5.28.md](RELEASE_NOTES_2026.5.28.md) 与 [RELEASE_NOTES_2026.5.27.md](RELEASE_NOTES_2026.5.27.md)。

## English

### 2026.5.31

- **Natural-language correction entry**: when the user says a memory is wrong, misunderstood, or not their meaning inside the AI tool they already use, Yifanchen can shape that into an errata candidate instead of treating it as another preference.
- **Method-signal candidates**: external news, tool repositories, and practice feedback can enter an `external_method_signal_candidate` dry-run before anything is installed or activated.
- **Agent install loop**: README now includes a prompt users can send directly to an AI agent; installers automatically install the Codex skill and register the `yifanchen-zhiyi` Codex MCP when Codex CLI is available, so users do not need to understand Skill or MCP first.
- **Hermes learning heartbeat**: adds a read-only native learning liveness check for recent Hermes `background_review`, `skill_manage`, and skill-file changes, making it visible when the natural learning chain has gone cold.
- **Hermes consumption receipts**: follows the official Hermes MemoryProvider lifecycle. `prefetch` recalls and injects context, `queue_prefetch` warms the next turn, and `sync_turn` records a Yifanchen-side consumption receipt on a background thread without writing Hermes skills or memory.
- **Hermes skill vs experience diff**: adds a read-only `skill-experience-diff` dry-run that compares Hermes-created or updated skills with existing Yifanchen experience and produces review-only adoption / upgrade candidates. It does not write Hermes skills or production experience.
- **State Ledger / Temporal Index**: adds a read-only dry-run for answering the latest trusted judgment while keeping adopted, pending, deprecated, superseded, and conflicting records visible on the same timeline. The temporal index is navigation only, not a replacement for raw records.
- **Context Budget Units**: adds a `context_budget_unit_candidate` dry-run for source-backed, composable, reviewable context units such as corrections, tool facts, method signals, and work experience. The particle/ion wording remains an unconfirmed direction, not claimed source wording.
- **Read-only model facts**: Yifanchen reads existing OpenClaw / Hermes / Codex model facts for its own checks and does not write them back.

### 2026.5.30

- **Real-task benchmark dry-run**: adds a multi-case benchmark so the same task set can compare no memory, Zhiyi only, and Zhiyi plus Xingce before any Replay feedback queue is built.
- **More precise preference extraction**: adds an intent gate so corrections, deictic disambiguation, relayed audit/task text, and creative prompts do not become durable Zhiyi preferences just because they contain preference-like words.
- **Windows large-sample smoke test**: the construction build was verified against a Windows local service with Web, Replay/benchmark, MCP, OpenClaw raw query, source refs, and error-log checks.

### 2026.5.29

- **Zhixing Library**: raw records are the source texts, Zhiyi is the understanding shelf, and Xingce is the work-experience and toolbook shelf.
- **Explainable recall**: recall results can include `library_id`, shelf, source refs, match method, and rank reason.
- **Production-shaped Xingce objects**: work-experience candidates now carry scenario, action strategy, avoid conditions, acceptance checks, scope, and lifecycle status.
- **Light typed graph and hybrid recall contract**: starts with user, project, platform, task, preference, and work-experience nodes, then combines source refs, keyword matching, vector readiness, and project/time filters.
- **Replay plan**: adds a read-only plan for comparing no memory, Zhiyi only, and Zhiyi plus Xingce on the same task set.
- **Zhixing loop dry-run**: a seven-step flow crosses the five shelves, checks four defensive metrics plus one offensive metric, and produces review-only feedback candidates instead of writing adopted experience automatically.
- **Explainable usage receipts**: each recall can report which library ids and source refs were used, why they matched, and that no platform write happened.
- **Toolbook candidate entry**: platform facts, environment differences, and command probes can be shaped into toolbook candidates; this first entry is dry-run / validate only.
- **Codex local support**: reads local Codex session records into the same local memory base.
- **Universal Zhiyi entry**: use `/zhiyi` to pick up a thread in a new window; English users can also use `/memory`, `/recall`, `/continue`, or `catch me up`.
- **Skill / MCP access**: includes the platform-neutral `yifanchen-zhiyi` skill and a read-only `zhiyi_recall` recall entry.
- **Capability check mode**: install and smoke tests can use `mode=capability_check` to verify Skill / MCP / read-only status without running recall or returning source text.
- **Shared local memory base**: OpenClaw, Hermes, and Codex can benefit from the same original records while their agents and windows remain scoped.
- **Incremental and resumable reading**: growing session files continue from saved offsets, and older source lookup can resume in segments.
- **Traceable experience**: Zhiyi experiences can carry catalog ids, lifecycle status, and source anchors.
- **Clearer Xingce wording**: Xingce is documented as the work-experience layer that turns prior work into reviewable next steps.
- **Local gateway hardening**: the read-only recall gateway explicitly accepts loopback clients only and guards cursor-state writes from platform config folders.

Older release notes: [2026.5.28](RELEASE_NOTES_2026.5.28.md), [2026.5.27](RELEASE_NOTES_2026.5.27.md).
