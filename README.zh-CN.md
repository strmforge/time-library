# 忆凡尘

英文产品名是 **Memcore Cloud**。**忆凡尘 / Yifanchen** 保留为中文名和 codename。

忆凡尘是一个本机 AI 记忆中心。它把 Claude Desktop、Codex、OpenClaw、Hermes 和其他本机 AI 工具用过的有用线索留在你的电脑上，让下一次对话不用从零开始。

当前发布版本：**2026.6.3**

2026.6.3 是当前已发布版本。

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
你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）。
仓库：https://github.com/strmforge/memcore-cloud

请安装并启动 Memcore Cloud。然后把 Memcore Cloud Zhiyi 安装成这个 agent 的长期记忆规则，不只是一次性安装说明。如果这个平台支持 skill 或自定义指令，请添加 Memcore Cloud Zhiyi skill/指令；如果这个平台支持 MCP，请注册名为 yifanchen-zhiyi 的 MCP 工具，地址是 http://127.0.0.1:9851/mcp。

安装完成后，只做一次安全能力检查：
{"query":"capability check","mode":"capability_check"}
先不要召回我的真实记忆。

以后请持续遵守这条规则。凡是我的问题依赖旧上下文，请先调用 zhiyi_recall，再结合 source_refs / raw_excerpt 回答。触发词包括：之前、定论、纠错、边界、忘了、安装/测试/发布状态，以及持续项目里的“下一步/接下来呢/还有吗/然后呢”。如果 skill 已安装但 zhiyi_recall 不可用，请告诉我 MCP/工具连接还没接上，不要凭印象猜。
```

安装 Skill 只是接入信号，不等于授权读取聊天正文。真正召回仍走本机 MCP；读取聊天正文需要单独授权。

## 直接安装

macOS / Linux：

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

WSL 只适合开发或高级测试。普通 Windows 用户请使用上面的 Windows
PowerShell 安装命令。

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
- 哪些可以先做安全能力检查；
- 哪些还需要授权后才能更深接入；
- 某个工具最近是否还在用；
- 新的 raw 记忆按什么目录保存。

这个页面默认只展示状态。发现某个工具，只代表“看见了入口”，不代表已经接通、可读正文、可导入记忆，也不代表会写平台配置、解析聊天正文或召回真实记忆。

## 知意和行策

知意更靠近“理解你”：偏好、表达习惯、纠偏、背景和意图。

行策更靠近“下次怎么做”：排障顺序、项目边界、踩坑记录、验收方法和工作经验。

经验不是可调用函数，行策不是技能库。偏好由知意记住，做事路径由行策沉淀；如果某个偏好会影响工作，行策可以引用它，但不会把偏好改名成行策。

忆凡尘的底线是：你说过的话本身就是最高事实。任何替代原文的压缩，都是污染。

## 2026.6.3 亮点

- Memcore Cloud Zhiyi prompt v4 已经改成长期记忆规则，不再只是一次性安装说明。
- 旧决定、纠错、项目边界、安装/测试/发布状态，以及“下一步 / 接下来呢 / 还有吗 / 然后呢”这类追问，会更明确要求 agent 先调 `zhiyi_recall`。
- README、Wiki 和本地 console 的复制提示统一为“安装 -> 安全检查 -> 需要旧上下文时先调记忆”。
- capability check 仍然只读、无召回、不返回原文。
- macOS 和 Windows 原生安装目录都已按 2026.6.3 验证，可以保留用户数据并把 prompt v4 安装到 Codex 和 Claude Desktop skill 位置。

当前发布说明见 [RELEASE_NOTES_2026.6.3.md](RELEASE_NOTES_2026.6.3.md)，完整历史更新见 [UPDATE_HISTORY.md](UPDATE_HISTORY.md)，更底层变更见 [CHANGELOG.md](CHANGELOG.md)。

## AI 工具入口

- **Claude Desktop**：可通过本机 MCP / Desktop Extension 使用忆凡尘；读取正文需要单独授权。
- **Claude Code CLI**：可通过 MCP 使用忆凡尘，并与 Claude Desktop 分开管理。
- **Codex**：可使用通用 skill 和 MCP，本机会话也可以成为可回源记录。
- **OpenClaw**：可在常用聊天入口获得记忆辅助。
- **Hermes**：可读取 raw/source refs 路径指针并保留 Hermes 自己的反馈边界。
- **其他本机 AI 工具**：可以先从本机设置里识别；先做安全检查，更深访问需要明确授权。

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
