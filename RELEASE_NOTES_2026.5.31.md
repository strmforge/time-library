# Yifanchen 2026.5.31

忆凡尘 2026.5.31 继续把“本机记忆图书馆”往真实 agent 消费里推进。这一版重点不是宣称 Hermes 已经自动生成 skill，而是让安装、能力检查、自然语言纠错、Hermes 消费状态和 skill/experience 对照都变得可见、可验、可回源。

## 中文

### 主要更新

- **自然语言纠错入口**：用户在原来的 AI 工具里说“这条记错了”“你理解偏了”“不是我的意思”时，忆凡尘会把它识别为勘误候选，而不是继续误写成长期偏好。
- **Agent 安装闭环**：README 增加可直接发给 Codex / OpenClaw / Hermes / Claude Code 等 agent 的安装提示。安装器会尽量自动安装 Codex skill，并在 Codex CLI 可用时注册 `yifanchen-zhiyi` MCP。
- **能力检查模式收口**：安装和冒烟测试继续使用 `mode=capability_check`，只验证 Skill / MCP / 只读状态，不触发真实召回，不返回 raw excerpts。
- **Hermes 学习心跳**：新增只读 native learning liveness 检查，观察最近是否有 Hermes `background_review`、`skill_manage` 和 skill 文件变化，帮助判断自然学习链路是否冷掉。
- **Hermes 消费回执**：按 Hermes 官方 MemoryProvider 生命周期补齐 `queue_prefetch` 和 `sync_turn`，记录 Hermes 是否召回、命中多少、source refs 多少，同时保持 hook 非阻塞。
- **Hermes 技能与经验对比升级**：新增只读 `skill-experience-diff` dry-run，把 Hermes skill 文件与忆凡尘经验对照，产出待审 adoption / upgrade 候选。
- **状态账本与上下文最小单元**：新增只读 State Ledger / Temporal Index 与 `context_budget_unit_candidate` dry-run，用来复核最新可信判断和可组合上下文，不替代 raw。
- **模型事实只读方向**：忆凡尘读取 OpenClaw / Hermes / Codex 已有模型配置供自己判断和测试，不写回平台，不把自己做成模型中心。

### 明确边界

- 忆凡尘不直接替 Hermes 写 skill。
- self-review signal receipt 只表示忆凡尘产生了唤醒信号，不等于 Hermes 已执行 `background_review`。
- Windows 大样本实测显示当前能看到 Hermes 原生环境，但 `skill_artifacts=0` 时不能宣称这几天 Hermes 已自然生成新 skill。
- 所有 dry-run / contract / candidate 入口默认不写 raw、知意、行策、工具书、勘误或平台配置。

## English

Yifanchen 2026.5.31 improves the local memory-library path for real agent use. This release does not claim that Hermes has automatically generated skills. It makes install checks, natural-language corrections, Hermes consumption state, native-learning liveness, and skill-vs-experience comparison visible and reviewable.

### Highlights

- **Natural-language correction entry**: user corrections such as "this memory is wrong" can become review-only errata candidates instead of durable preference memories.
- **Agent install loop**: README now includes a prompt users can send directly to a local AI agent. Installers try to install the Codex skill and register the `yifanchen-zhiyi` MCP server when Codex CLI is available.
- **Capability check mode**: smoke tests use `mode=capability_check` to verify service/tool/read-only availability without real recall or raw excerpts.
- **Hermes learning heartbeat**: read-only native liveness reports recent `background_review`, `skill_manage`, and skill-file changes.
- **Hermes consumption receipts**: follows the Hermes MemoryProvider lifecycle with `queue_prefetch` and non-blocking `sync_turn` receipts.
- **Hermes skill vs experience diff**: read-only dry-run compares Hermes skill files with Yifanchen experience and creates review-only adoption / upgrade candidates.
- **State Ledger and Context Budget Units**: contract-first dry-runs for latest trusted judgments and source-backed context units.
- **Read-only model facts**: Yifanchen reads existing OpenClaw / Hermes / Codex model facts for its own checks and does not write them back.

### Boundaries

- Yifanchen does not directly write Hermes skills.
- A self-review signal receipt is not proof that Hermes ran `background_review`.
- If `skill_artifacts=0`, the correct claim is that Hermes native status is observable, not that new Hermes skills were generated.
- Candidate and dry-run endpoints are non-writing unless a separate authorized apply path exists.
