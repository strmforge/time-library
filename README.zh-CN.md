# 忆凡尘

中文主页已放在 [README.md](README.md)。

忆凡尘是本地个人 AI 记忆中心。它原样保存对话，安静整理经验，让 OpenClaw、Hermes、Codex 等常用 AI 工具慢慢更懂你。

当前版本：**2026.5.31**

更新方法：打开 `http://127.0.0.1:9850`，进入“设置与更新”，点击“检查更新”和“一键更新”。如果本地页面打不开，可以重新运行安装命令做修复安装。

如果你正在使用 Codex、OpenClaw、Hermes、Claude Code 或其他能操作本机终端的 AI agent，可以直接把下面这段话发给它：

```text
请帮我在本机安装忆凡尘（Yifanchen），仓库是 https://github.com/strmforge/memcore-cloud 。
安装完成后请启动本机服务；请自动安装 Codex skill；如果检测到 Codex CLI，请自动把 Codex MCP 接到 http://127.0.0.1:9851/mcp，MCP 名称用 yifanchen-zhiyi。
如果检测到 OpenClaw 或 Hermes，也请按安装器默认方式接入。
最后只做 capability check，不要召回我的真实记忆。
```

安装器会尽量自动完成本机接入：OpenClaw 插件、Hermes provider、Codex skill、Codex MCP 都会按平台能力接好，用户不需要先理解 Skill 或 MCP。Codex skill 会给新开的 Codex 会话一个明确锚点：忆凡尘是一座本机记忆图书馆；Codex MCP 注册成功后，新会话可以看到 `yifanchen-zhiyi` / `zhiyi_recall`；已经打开的会话可能需要重开后才会加载新连接。

Hermes 不是只有普通 prefetch：Hermes native review 被触发时，它可以读取忆凡尘开放的 raw/source_refs 路径指针，然后自己去看原始资料。忆凡尘的边界是发出 self-review signal、观察 Hermes native feedback；它不直接替 Hermes 写 skill。

2026.5.31 追加 Hermes 学习心跳：新增只读 native learning liveness 检查，报告最近是否有 Hermes `background_review`、`skill_manage` 和 skill 文件变化，帮助区分“会被触发时能学”和“这几天自然链路冷掉了”。self-review signal 也有 wake dry-run 和授权 receipt gate，可记录“已产生信号”，但这仍不等于 Hermes 已执行 native review 或生成 skill。

Hermes 同等消费不复制 OpenClaw 的 `before_dispatch` 拦截形态，而是按 Hermes 官方 MemoryProvider 生命周期补齐：`prefetch` 负责召回/注入，`queue_prefetch` 预热下一轮，`sync_turn` 用后台线程写入消费回执，避免阻塞 Hermes hook。这样能看到 Hermes 这一轮是否真的消费了忆凡尘、命中多少、source_refs 多少，同时仍不写 Hermes skill/memory。

2026.5.31 继续补 Hermes 技能与经验对比升级：新增只读 `skill-experience-diff` dry-run，把 Hermes 生成或修改的 skill 与忆凡尘现有经验对照，产出待审 adoption / upgrade 候选。它补的是“skill 和经验之间的 diff 层”，不直接写 Hermes skill，也不直接写正式经验。

2026.5.31 也追加状态账本、时间索引和上下文预算最小单元：状态账本回答“当前最新可信判断是什么”，旧判断保留为 superseded / deprecated / conflicting，不静默删除；时间索引只做导航，不替代 raw。`context_budget_unit_candidate` 用来把纠错、工具事实、方法信号和工作经验整理成可回源、可组合、可过期复核的上下文最小单元；“粒子/离子”仍按待核验方向处理，不写成已确认原话。相关接口均为 dry-run / contract，不写 raw、知意、行策、工具书、勘误或平台配置。

2026.5.29 增加知行图书馆证据闭环：原始记忆是底本，知意是理解类馆藏，行策是工作经验和工具书。召回结果开始带馆藏号、书架、来源、命中方式和排序理由；行策候选按工作场景、行动策略、禁用条件、验收方式和生命周期整理。工具书的底本来自 `raw/external_docs/` 或 `raw/probe_logs/`，例如平台配置是否立即生效、大小写敏感系统如何识别官方文件名这类命令实测事实，都要先保存输出或文档片段，再生成候选。工具书候选入口当前只做 dry-run / validate，不写入馆藏。Replay 评分优先用确定性规则，不靠 AI 自评；知行闭环 dry-run 已加入第 5 个进攻指标：主动浮现用户忘了但过去做对过的东西。当前反哺只生成待审候选，授权 apply 也只写审阅收据，不自动写入正式经验。

安装或冒烟测试时用 `mode=capability_check` 做能力检查：它只验证 Skill / MCP / 只读状态，不触发召回、不返回 source refs 或原文摘录。

知意主要沉淀用户喜好、表达习惯和意图经验；行策主要沉淀工作经验。经验不是可调用函数；行策不是技能库。偏好由知意记住，做事路径由行策沉淀。

忆凡尘的底线是：你说过的话本身就是最高事实。任何替代原文的压缩，都是污染。
