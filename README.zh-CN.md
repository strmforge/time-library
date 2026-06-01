# 忆凡尘

英文产品名是 **Memcore Cloud**。**忆凡尘 / Yifanchen** 保留为中文名和 codename。

忆凡尘是一个本机 AI 记忆中心。它把 Claude Desktop、Codex、OpenClaw、Hermes 和其他本机 AI 工具用过的有用线索留在你的电脑上，让下一次对话不用从零开始。

当前发布版本：**2026.6.1**

2026.6.1 是当前已发布版本。

## 它解决什么

AI 工具很聪明，但经常忘掉你已经说过的细节：你喜欢怎样表达、项目哪里不能动、上次怎么修好的、哪个坑不要再踩、某件事做到哪里了。

忆凡尘做的事很朴素：把这些线索留在本机，并且尽量带着来源。它不是云聊天，也不是把原话压成几句摘要的仓库。原始记录仍然是最高事实，整理出来的知意和行策都应该能回到来源。

## 你会得到什么

- **多个 AI 工具共享本机记忆**：Claude Desktop、Claude Code CLI、Codex、OpenClaw、Hermes、Cursor 类工具和新的本机 agent 可以接到同一个记忆底座。
- **记忆有来源**：召回不是凭感觉说“我记得”，而是尽量带来源线索、原始摘录、命中理由。
- **原话不被摘要替代**：摘要可以帮助浏览，但不能替代已保存的原始内容。
- **工具边界不混读**：Claude Desktop 和 Claude Code CLI 分开看待；官方登录、中转服务、CLI 运行时产生的记录会保留归属边界。
- **第一步可以安全测试**：capability check 只验证 Skill / MCP / 只读路径，不召回真实记忆、不返回原文。
- **本机工具发现**：本地页面能告诉你这台电脑上有哪些 AI 工具、哪些已经可以检查、哪些还差一次授权接入。

## 把这段发给本机 AI agent

如果你正在使用 Codex、OpenClaw、Hermes、Claude Code CLI 或其他能操作本机终端的 AI agent，可以直接把下面这段话发给它：

```text
请帮我在本机安装 Memcore Cloud（忆凡尘 / Yifanchen），仓库是 https://github.com/strmforge/memcore-cloud 。
安装完成后请启动本机服务；请自动安装 Codex skill；如果检测到 Codex CLI，请自动把 Codex MCP 接到 http://127.0.0.1:9851/mcp，MCP 名称用 yifanchen-zhiyi。
如果检测到 OpenClaw、Hermes 或 Claude Desktop，也请按安装器默认方式接入；Claude Desktop 需要注册本机 MCP bridge 才能真正查询 Memcore Cloud。
最后只做 capability check，不要召回我的真实记忆。
```

安装 Skill 只是接入信号，不等于授权读取聊天正文。真正召回仍走本机 MCP；读取聊天正文需要单独授权。

## 直接安装

macOS / Linux / WSL：

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

安装后打开：

```text
http://127.0.0.1:9850
```

## 安全第一步

安装或冒烟测试时，不要先用 `/zhiyi`。它可能真的召回本机记忆。请让客户端调用 `zhiyi_recall` 并带上：

```json
{"query":"capability check","mode":"capability_check"}
```

成功结果应该包含：

```text
read_only: true
recall_performed: false
raw_excerpt_returned: false
mcp_tools: ["zhiyi_recall"]
```

只有你明确决定测试记忆召回之后，才进入真实 recall。

## 本地页面能看什么

打开 `http://127.0.0.1:9850` 可以看到：

- 这台机器上有哪些 AI 工具；
- 哪些已经有可用连接；
- 哪些还差一次授权；
- 某个工具最近是否还在用；
- 新的 raw 记忆按什么目录保存。

这个页面默认只展示状态。发现某个工具，只代表“看见了入口”，不代表写平台配置、解析聊天正文或召回真实记忆。

## 知意和行策

知意更靠近“理解你”：偏好、表达习惯、纠偏、背景和意图。

行策更靠近“下次怎么做”：排障顺序、项目边界、踩坑记录、验收方法和工作经验。

经验不是可调用函数，行策不是技能库。偏好由知意记住，做事路径由行策沉淀；如果某个偏好会影响工作，行策可以引用它，但不会把偏好改名成行策。

忆凡尘的底线是：你说过的话本身就是最高事实。任何替代原文的压缩，都是污染。

## 2026.6.1 亮点

- 英文首屏统一为 **Memcore Cloud**。
- README 顶部放了可直接发给本机 agent 的安装提示。
- 本地页面能展示已发现的 AI 工具和安全下一步。
- Claude Desktop 和 Claude Code CLI 作为一等对象，但仍分开管理。
- **按电脑整理本机记录**：新增记录先按电脑分组，再按产生记录的 AI 工具分组。以后多台机器汇集时，也能先看清“哪台机器上的哪个工具”。
- 公开入口聚焦今天能安装、能检查、能召回的功能，更深的跨设备能力留在后续版本继续推进。

当前发布说明见 [RELEASE_NOTES_2026.6.1.md](RELEASE_NOTES_2026.6.1.md)，完整历史更新见 [UPDATE_HISTORY.md](UPDATE_HISTORY.md)，更底层变更见 [CHANGELOG.md](CHANGELOG.md)。

## 支持的来源

- **Claude Desktop**：可通过本机 MCP / Desktop Extension 使用忆凡尘；读取正文需要单独授权。
- **Claude Code CLI**：可通过 MCP 接入，并与 Claude Desktop 分开管理。
- **Codex**：可使用通用 skill 和 MCP，本机会话也可以成为可回源记录。
- **OpenClaw**：可在常用聊天入口获得记忆辅助。
- **Hermes**：可读取 raw/source refs 路径指针并保留 Hermes 自己的反馈边界。
- **其他本机 AI 工具**：能从本机设置里被发现，授权后再接入。

## 更新

打开 `http://127.0.0.1:9850`，进入“设置与更新”，点击“检查更新”和“一键更新”。如果本地页面打不开，可以重新运行安装命令做修复安装。

## 卸载

macOS / Linux：

```bash
~/.memcore-cloud/uninstall.sh
```

Windows：

```powershell
.\uninstall.ps1
```

卸载只移除软件本体，`memory/`、`raw/`、`zhiyi/`、`config/` 等本地数据会保留。
