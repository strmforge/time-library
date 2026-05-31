# 忆凡尘

中文主页已放在 [README.md](README.md)。

忆凡尘是本地个人 AI 记忆中心。它原样保存对话，安静整理经验，让 OpenClaw、Hermes、Codex 等常用 AI 工具慢慢更懂你。

当前版本：**2026.5.31**

## 最新亮点

- **自然语言纠错入口**：用户说“这条记错了”“你理解偏了”时，优先进入勘误候选，不当作长期偏好硬写。
- **Agent 安装闭环**：可以把下面的安装提示直接发给 Codex、OpenClaw、Hermes、Claude Code 等本机 agent；用户不需要先理解 Skill 或 MCP。
- **Hermes 不是只有普通 prefetch**：Hermes native review 被触发时，可以读取忆凡尘开放的 raw/source_refs 路径指针，再由 Hermes 自己看原始资料；忆凡尘负责 self-review signal、native learning liveness、消费回执和 skill-experience diff，不直接替 Hermes 写 skill。
- **知行图书馆证据闭环**：原始记忆是底本，知意是理解类馆藏，行策是工作经验和工具书；召回、回放、候选升级都要尽量保留来源。
- **模型事实只读**：忆凡尘读取 OpenClaw / Hermes / Codex 已有模型配置供自己判断和测试，不写回平台，不做模型中心。

完整历史更新见 [UPDATE_HISTORY.md](UPDATE_HISTORY.md)，工程级变更见 [CHANGELOG.md](CHANGELOG.md)，本版完整说明见 [RELEASE_NOTES_2026.5.31.md](RELEASE_NOTES_2026.5.31.md)。

## 让 AI agent 帮你安装

如果你正在使用 Codex、OpenClaw、Hermes、Claude Code 或其他能操作本机终端的 AI agent，可以直接把下面这段话发给它：

```text
请帮我在本机安装忆凡尘（Yifanchen），仓库是 https://github.com/strmforge/memcore-cloud 。
安装完成后请启动本机服务；请自动安装 Codex skill；如果检测到 Codex CLI，请自动把 Codex MCP 接到 http://127.0.0.1:9851/mcp，MCP 名称用 yifanchen-zhiyi。
如果检测到 OpenClaw 或 Hermes，也请按安装器默认方式接入。
最后只做 capability check，不要召回我的真实记忆。
```

安装器会尽量自动完成本机接入。Codex skill 会给新开的 Codex 会话一个明确锚点：忆凡尘是一座本机记忆图书馆；Codex MCP 注册成功后，新会话可以看到 `yifanchen-zhiyi` / `zhiyi_recall`；已经打开的会话可能需要重开后才会加载新连接。

安装或冒烟测试时用 `mode=capability_check` 做能力检查：它只验证 Skill / MCP / 只读状态，不触发召回、不返回 source refs 或原文摘录。

## 更新

打开 `http://127.0.0.1:9850`，进入“设置与更新”，点击“检查更新”和“一键更新”。如果本地页面打不开，可以重新运行安装命令做修复安装。

知意主要沉淀用户喜好、表达习惯和意图经验；行策主要沉淀工作经验。经验不是可调用函数；行策不是技能库。偏好由知意记住，做事路径由行策沉淀。

忆凡尘的底线是：你说过的话本身就是最高事实。任何替代原文的压缩，都是污染。
