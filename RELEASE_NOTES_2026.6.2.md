# Memcore Cloud 2026.6.2

Memcore Cloud 2026.6.2 makes the memory path feel real from inside the tools people already use.

The headline is simple: Claude can call the local memory gateway, real recall returns readable Chinese, and source-backed memory from more local tools shows up with clearer ownership.

## English

### Highlights

- **Claude recall now works cleanly**: Claude can call `yifanchen-zhiyi` through the local MCP bridge, run safe capability checks, and perform real recall without the old timeout / JSON-RPC error path.
- **Chinese excerpts are readable again**: recalled `raw_excerpt` text stays readable in Claude instead of turning into garbled characters.
- **Windows setup is less fragile**: Claude config is written without UTF-8 BOM, the bridge speaks the JSON-line format Claude expects, and both regular and Store-style Claude config paths can be registered.
- **OpenClaw and Hermes records show up together**: recall can surface source-backed records from multiple local tools while keeping source refs and attribution visible.
- **Computer-first storage is visible in practice**: new records can be found under paths shaped by computer first, then by the AI tool that produced them.
- **The install prompt got stronger**: the skill now tells an agent when to call memory first, especially for previous decisions, corrections, project boundaries, install/test/release status, and "what next" questions.
- **Wiki source pages are ready**: product-facing wiki pages now cover getting started, safe checks, AI tool boundaries, memory layout, and release history routing.

### What This Means

Memcore Cloud is no longer only saying "shared local memory" in the README. In this release, the loop is easier to test:

1. install the skill / MCP connection;
2. run capability check without recalling real memory;
3. run real recall;
4. inspect source refs and raw excerpts;
5. keep platform boundaries visible.

### Boundaries

- Claude Desktop chat-body parsing remains a separate authorization step.
- Skill installation is still a connection signal, not permission to read every chat body.
- Capability check remains no-recall and read-only.

## 中文

### 主要更新

- **Claude 召回链路更稳了**：Claude 可以通过本机 MCP bridge 调 `yifanchen-zhiyi`，能力检查和真实 recall 都能跑通。
- **中文原文摘录不再乱码**：Claude 里召回到的 `raw_excerpt` 已经能正常显示中文。
- **Windows 配置更稳**：Claude 配置文件不再带 BOM，bridge 输出也改回 Claude 需要的 JSON-line 形式；普通路径和 Store 路径都能注册。
- **OpenClaw / Hermes 记录能一起召回**：多来源本机记忆可以一起出现，同时保留来源和归属。
- **按电脑优先的目录开始落地可见**：新增记录能按“计算机名 -> 软件名 -> 软件保存格式”这条结构进入本机记忆。
- **Skill 提示更会提醒 agent 调记忆**：遇到之前的决定、纠错、项目边界、安装/测试/发布状态、下一步这类问题，先调用 `zhiyi_recall`。
- **Wiki 源文件准备好了**：包含入门、安全检查、AI 工具边界、记忆目录和版本历史入口。

### 大白话

这一版重点不是堆新名词，而是让“AI 编程助手终于不失忆了”这件事更能被实际验证。

先安全检查，不碰真实记忆；确认通了，再做真实 recall；召回结果能读、能回源、能看出来自哪台机器和哪个工具。

### 边界

- Claude Desktop 聊天正文解析仍是单独授权步骤。
- 安装 Skill 只是接入信号，不等于授权读取所有聊天正文。
- capability check 仍然只读、无召回。
