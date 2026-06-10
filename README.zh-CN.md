# 忆凡尘

英文产品名是 **Memcore Cloud**。**忆凡尘 / Yifanchen** 保留为中文名和 codename。

忆凡尘是一个本机 AI 记忆中心。它把 Claude Desktop、Codex、OpenClaw、Hermes 和其他本机 AI 工具用过的有用线索留在你的电脑上，让下一次对话不用从零开始。

当前发布版本：**2026.6.11**

2026.6.11 是当前已发布版本。

## 它解决什么

AI 工具很聪明，但经常忘掉你已经说过的细节：你喜欢怎样表达、项目哪里不能动、上次怎么修好的、哪个坑不要再踩、某件事做到哪里了。

忆凡尘做的事很朴素：把这些线索留在本机，并且尽量带着来源。它不是云聊天，也不是把原话压成几句摘要的仓库。原始记录仍然是最高事实，整理出来的知意和行策都应该能回到来源。

## 你会得到什么

- **多个 AI 工具共享本机记忆**：Claude Desktop、Claude Code CLI、Codex、OpenClaw、Hermes、Cursor 类工具和正在流行的开源 agent 可以接到同一个记忆底座。
- **记忆有来源**：召回不是凭感觉说“我记得”，而是尽量带来源线索、原始摘录、命中理由。
- **原话不被摘要替代**：摘要可以帮助浏览，但不能替代已保存的原始内容。
- **工具边界不混读**：Claude Desktop 和 Claude Code CLI 分开看待；官方登录、中转服务、CLI 运行时产生的记录会保留归属边界。
- **第一步可以安全测试**：capability check 只验证 Skill / MCP / 只读路径，不召回真实记忆、不返回原文。
- **安装一次，自动找到本机工具**：OpenCode、Goose、Aider、OpenHands 这类开源 agent 也会进入识别范围；支持 Skill / MCP 的会自动接入，新的记忆源按设备优先归档。
- **新工具也能更快认出来**：如果你配置了模型，或本机已有可复用的 AI 模型设置，忆凡尘会根据本机元数据识别陌生 AI 工具；如果没配置，本地规则也能继续工作。

## 把这段发给本机 AI agent

如果你正在使用 Codex、OpenClaw、Hermes、Claude Code CLI 或其他能操作本机终端的 AI agent，可以直接把下面这段话发给它：

```text
你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）。
仓库：https://github.com/strmforge/memcore-cloud

请安装并启动 Memcore Cloud。然后把 Memcore Cloud Zhiyi 安装成这个 agent 的长期记忆规则，不只是一次性安装说明。如果这个平台支持 skill 或自定义指令，请添加 Memcore Cloud Zhiyi skill/指令；如果这个平台支持 MCP，请注册名为 yifanchen-zhiyi 的 MCP 工具，地址是 http://127.0.0.1:9851/mcp。

安装完成后，只做一次安全能力检查：
{"query":"capability check","mode":"capability_check"}
先不要召回我的真实记忆。

以后请持续遵守这条规则。凡是我的问题依赖旧上下文，请先调用 zhiyi_recall，再结合 source_refs / raw_excerpt 回答。触发词包括：之前、定论、纠错、边界、忘了、安装/测试/发布状态，以及持续项目里的“下一步/接下来呢/还有吗/然后呢”。默认使用 active 召回：当前窗口/session 优先，然后同项目/同工作区、同工作流/同任务、稳定偏好/工具事实。只有我明确要求更宽视图时，才使用 raw-pool/global。如果显式 window-only 召回提示当前窗口/session 还没绑定，请直接说明这个绑定缺口；不要说没有记忆。如果 skill 已安装但 zhiyi_recall 不可用，请告诉我 MCP/工具连接还没接上，不要凭印象猜。
```

安装器会在支持 skill 或自定义指令的平台加入 Memcore Cloud Zhiyi，并在支持 MCP 的平台注册 `yifanchen-zhiyi`；改动本机配置时会留下备份和回执。

## 直接安装

macOS / Linux：

```bash
curl -fL -o memcore-cloud-install.sh https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.11/install.sh
bash memcore-cloud-install.sh
```

Windows PowerShell：

```powershell
iwr https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.11/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

Windows 默认安装到 `%LOCALAPPDATA%\memcore-cloud`。如果要自己选安装路径，
先设置路径再执行安装：

```powershell
$env:MEMCORE_INSTALL_DIR = "D:\Apps\memcore-cloud"
iwr https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.11/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

如果已经下载了仓库，也可以直接运行：

```powershell
.\install.ps1 -Dir "D:\Apps\memcore-cloud"
```

WSL 只适合开发或高级测试。普通 Windows 用户请使用上面的 Windows
PowerShell 安装命令。

Windows 安装后会有 Memcore Cloud 托盘图标；macOS 安装后会有 Memcore Cloud 菜单栏图标。它们都可以直接打开本地控制台、查看健康状态，或者立刻补扫漏掉的记录。

也可以直接打开本地控制台：

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
- 哪些可以先做安全能力检查；
- 哪些已经接入或可以自动接入 Skill / MCP；
- 某个工具最近是否还在用；
- 新的 raw 记忆按什么目录保存。

Windows 和 macOS 上都不用记端口，托盘/菜单栏图标就是入口。本机 watcher 会保持运行，并在重启或修复安装后补扫漏掉的记录。

支持 Skill / MCP 的入口可以自动接入。对话进入记忆依赖已验证的本地格式采集器；能力检查仍然是无召回，只有 agent 明确调用 recall 才会读取真实记忆。

## 知意和行策

知意更靠近“理解你”：偏好、表达习惯、纠偏、背景和意图。

行策更靠近“下次怎么做”：排障顺序、项目边界、踩坑记录、验收方法和工作经验。

不同工具留下来的线索不一样。忆凡尘会把它们汇进同一条“时间长河”：先守住原始记录，再按来源、时间、馆藏身份、证据和生命周期沉淀成知意、行策、工具书或勘误。你以后问起旧事，它应该能沿着时间和来源找回去，而不是只给一段没出处的摘要。

经验不是可调用函数，行策不是技能库。偏好由知意记住，做事路径由行策沉淀；如果某个偏好会影响工作，行策可以引用它，但不会把偏好改名成行策。

忆凡尘的底线是：你说过的话本身就是最高事实。任何替代原文的压缩，都是污染。

## 2026.6.11 亮点

- checkpoint 损坏时会先备份成 `.corrupt-backup-*`，新的 checkpoint 保存改为原子替换。
- Codex 和 Claude Code 记录在 canonical index 里稳定使用 session 身份，同时保留旧 workspace/window 线索。
- 知意 / 行策 preflight 可以在 agent 回答前主动浮现有来源的锚点，也可以在证据不足时静默退回。
- raw gateway 可以直接从 canonical index 回答当前窗口短续问 preflight，不扩大召回范围，也不暴露 raw 原文。
- Claude Code 安装时可以写入安静的 `UserPromptSubmit` hook，让持续任务不必每次靠手动记忆命令续上下文。
- 运行守护更紧：raw gateway health 带 source 身份，Windows guardian 会报告端口归属，dialog-entry token 只进入 dialog-entry 服务命令。

当前发布说明见 [RELEASE_NOTES_2026.6.11.md](RELEASE_NOTES_2026.6.11.md)，完整历史更新见 [UPDATE_HISTORY.md](UPDATE_HISTORY.md)，更底层变更见 [CHANGELOG.md](CHANGELOG.md)。

## AI 工具入口

- **Claude Desktop**：可通过本机 MCP / Desktop Extension 使用忆凡尘；来源记录走已验证的本地格式采集器。
- **Claude Code CLI**：可通过 MCP 使用忆凡尘，并与 Claude Desktop 分开管理。
- **Codex**：可使用通用 skill 和 MCP，本机会话也可以成为可回源记录。
- **OpenClaw**：可在常用聊天入口获得记忆辅助。
- **Hermes**：可读取 raw/source refs 路径指针并保留 Hermes 自己的反馈边界。
- **其他本机 AI 工具**：可以从本机设置、应用目录、包管理器和工作区痕迹里识别；支持 Skill / MCP 的自动接入，本地格式验证后可成为记忆来源。

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
