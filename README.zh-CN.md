# 忆凡尘

默认主页现在使用英文首屏：[README.md](README.md)。忆凡尘是中文名，英文产品名是 **Memcore Cloud**。

忆凡尘是本地个人 AI 记忆中心。它原样保存对话，安静整理经验，让 OpenClaw、Hermes、Codex、Claude Desktop 等常用 AI 工具慢慢更懂你。

当前发布版本：**2026.6.1**

2026.6.1 是当前已发布版本，英文对外名统一为 **Memcore Cloud**。

## 你会得到什么

- 新开一个 AI 窗口时，不用每次都从头解释自己。
- 原始对话留在本机，之后可以回到来源看证据。
- 偏好、纠偏、项目习惯、踩坑经验，都可以慢慢变成可复用记忆。
- Claude Desktop、Claude Code CLI、Codex、OpenClaw、Hermes、Cursor 类工具和更新的本机 agent，都可以从本机被发现。
- 你可以直接把安装提示发给本机 agent，让它帮你装 Skill、接 MCP；第一步只做能力检查，不召回真实记忆。

## 把这段发给本机 AI agent

如果你正在使用 Codex、OpenClaw、Hermes、Claude Code CLI 或其他能操作本机终端的 AI agent，直接把下面这段话发给它。它会帮你安装 skill；如果平台支持 MCP，安装器会顺势注册 `yifanchen-zhiyi` MCP。

```text
请帮我在本机安装 Memcore Cloud（忆凡尘 / Yifanchen），仓库是 https://github.com/strmforge/memcore-cloud 。
安装完成后请启动本机服务；请自动安装 Codex skill；如果检测到 Codex CLI，请自动把 Codex MCP 接到 http://127.0.0.1:9851/mcp，MCP 名称用 yifanchen-zhiyi。
如果检测到 OpenClaw、Hermes 或 Claude Desktop，也请按安装器默认方式接入；Claude Desktop 需要注册本机 MCP bridge 才能真正查询忆凡尘。
最后只做 capability check，不要召回我的真实记忆。
```

Skill 安装只是接入意图信号，不等于授权读取聊天正文；真正召回仍走本机 MCP，正文解析另有授权 gate。

## 最新亮点

- **自然语言纠错入口**：用户说“这条记错了”“你理解偏了”时，优先进入勘误候选，不当作长期偏好硬写。
- **Agent 安装闭环**：可以把下面的安装提示直接发给 Codex、OpenClaw、Hermes、Claude Code CLI 等本机 agent；安装器会尽量接好 Claude Desktop MCP bridge，用户不需要先理解 Skill 或 MCP。
- **本机平台发现**：能看到本机有哪些 AI 工具、哪些已经能能力检查、哪些还差一次授权接入。
- **计算机优先的 raw 归档契约**：2026.6.1 起，新装和新增 raw 写入全面使用 `memory/{computer_name}/{source_system}/{native_artifact_format}/...`。历史 source-system-first 目录只保留读取兼容，不再作为新增记录形状。
- **Hermes 不是只有普通 prefetch**：Hermes native review 被触发时，可以读取忆凡尘开放的 raw/source_refs 路径指针，再由 Hermes 自己看原始资料；忆凡尘负责 self-review signal、native learning liveness、消费回执和 skill-experience diff，不直接替 Hermes 写 skill。
- **Claude Desktop 一等公民**：Claude Desktop 和 Claude Code CLI 分开识别。Claude Desktop 可以通过本机 MCP / Desktop Extension 消费忆凡尘；只装通用 Skill 只是信号，不等于能调用本机记忆。来源侧先做本机用户态同步清单和 sync-state receipt；读取和页面展示可以按 `claude_all` 聚合全部 Claude 入口，但 Windows 上通过中转服务或 Claude Code 运行时产生的记录仍会保留双归属字段和隔离边界，不压成单一来源，也不表示官方登录聊天和中转聊天互通。官方导出包只作冷启动或补档 fallback。
- **知行图书馆证据闭环**：原始记忆是底本，知意是理解类馆藏，行策是工作经验和工具书；召回、回放、候选升级都要尽量保留来源。
- **模型事实只读**：忆凡尘读取 OpenClaw / Hermes / Codex 已有模型配置供自己判断和测试，不写回平台，不做模型中心。

当前发布说明见 [RELEASE_NOTES_2026.6.1.md](RELEASE_NOTES_2026.6.1.md)，完整历史更新见 [UPDATE_HISTORY.md](UPDATE_HISTORY.md)，工程级变更见 [CHANGELOG.md](CHANGELOG.md)。

## 直接安装

macOS / Linux / WSL：

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

安装或冒烟测试时用 `mode=capability_check` 做能力检查：它只验证 Skill / MCP / 只读状态，不触发召回、不返回 source refs 或原文摘录。

## 安全测试清单

第一步只做 capability check。成功结果应该包含 `read_only: true`、`recall_performed: false`、`raw_excerpt_returned: false`，以及 `mcp_tools: ["zhiyi_recall"]`。

第二步打开 `http://127.0.0.1:9850` 看本机工具是否被发现。忆凡尘会告诉你它在本机看到了哪些工具、哪些已经能用、哪些还差一步授权接入。这个检查不会写平台配置、不会解析聊天正文、不会召回真实记忆。

## 查看它发现了什么

本地页面会告诉你：这台机器上有哪些 AI 工具，哪些已经可以做安全能力检查，哪些还差一次授权接入。

Claude Desktop 和 Claude Code CLI 会分开看待，不会混读。Codex、OpenClaw、Hermes、Cursor 类工具，以及更新的本机 agent，也可以从它们原本保存本机设置的位置被识别出来。发现某个工具，只代表“看见了入口”，不代表读取聊天正文。

真正接入前，忆凡尘会先告诉你准备改哪里、是否需要重启、怎么撤回、接好后怎样做只读能力检查。只有你明确决定测试记忆召回之后，才进入真实 recall。安装 Skill、发现某个平台、看到 Claude Desktop 本地存储，都不等于授权读取聊天正文。

## 更新

打开 `http://127.0.0.1:9850`，进入“设置与更新”，点击“检查更新”和“一键更新”。如果本地页面打不开，可以重新运行安装命令做修复安装。

知意主要沉淀用户喜好、表达习惯和意图经验；行策主要沉淀工作经验。经验不是可调用函数；行策不是技能库。偏好由知意记住，做事路径由行策沉淀。

忆凡尘的底线是：你说过的话本身就是最高事实。任何替代原文的压缩，都是污染。
