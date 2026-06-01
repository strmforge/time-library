# Memcore Cloud 2026.6.1

Memcore Cloud 2026.6.1 is the first release that presents the project with its English product name by default. **忆凡尘 / Yifanchen** remains the Chinese name and codename.

This release focuses on making the local memory layer easy to try: users can paste an install prompt into a local agent, see which tools are detected, and verify the connection without recalling real memory.

## English

### Highlights

- **Memcore Cloud is now the English-first name**: Yifanchen stays as the Chinese/codename identity, but the repository is easier to search and explain in English.
- **You can hand installation to an agent**: paste the prompt into Codex, Claude Code CLI, OpenClaw, Hermes, or another local agent. It can install the skill, wire MCP where supported, and finish with a safe capability check.
- **It can look around your machine**: Memcore Cloud can show which local AI tools it sees, which ones are already connectable, and which ones need one more authorization step.
- **It keeps tools separate**: Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and newer agents can sit around the same memory core without their histories being flattened into one source.
- **It can notice newer tools**: newer local agent tools can be recognized from the local traces they already keep, before they need a named integration.
- **It plans before it writes**: before a one-click connection changes anything, Memcore Cloud can show what would change, how to back out, and what safe check will run afterward.
- **Claude Code CLI joins the connectable set**: Claude Code CLI can now be connected while staying separate from Claude Desktop, with separate permission required before chat text is read.
- **Raw memory is organized by computer first**: new raw records use `memory/{computer_name}/{source_system}/{native_artifact_format}/...`, which fits future multi-machine collection better.
- **Claude Desktop stays first-class**: official, relay, and Claude Code related records keep their attribution and isolation boundaries.
- **Central-node work is intentionally paused**: central sync waits for Nantianmen; this release is about strong local memory and local tool connection.

### Boundaries

- Discovery endpoints are read-only by default.
- Installing a skill is an intent signal, not permission to read chat bodies.
- Capability check does not recall real memory and does not return raw excerpts.
- Full local surface scanning can be heavier on Windows; the default dashboard path is fast and the deeper scan should be treated as explicit/background work.

## 中文

### 主要更新

- **英文首屏统一为 Memcore Cloud**：忆凡尘 / Yifanchen 保留为中文名和 codename，英文用户更容易搜到和理解。
- **可以把安装交给本机 agent**：把提示发给 Codex、Claude Code CLI、OpenClaw、Hermes 或其他本机 agent，它会帮你安装 Skill、接 MCP，并只做安全能力检查。
- **能看见本机有哪些 AI 工具**：面板会告诉你发现了哪些工具、哪些已经能用、哪些还差一次授权接入。
- **工具各归各的，不混成一团**：Claude Desktop、Claude Code CLI、Codex、OpenClaw、Hermes、Cursor 类工具和新 agent 可以围绕同一个记忆核心，但来源边界仍然保留。
- **能发现更多新工具**：更新的本机 agent 可以先从本地已有线索里被识别出来，不必先写成专门接入。
- **接入前先告诉你会改什么**：一键接入前会先展示准备改哪里、如何撤回、接完后怎么做安全能力检查。
- **Claude Code CLI 加入可接入范围**：它可以接入忆凡尘，但仍和 Claude Desktop 分开；读取聊天正文需要单独授权。
- **raw 记忆按电脑优先组织**：新记录使用 `memory/{computer_name}/{source_system}/{native_artifact_format}/...`，未来多机器汇集时先按机器分，再看每台机器上的软件。
- **Claude Desktop 继续作为一等公民**：官方、中转、Claude Code 相关记录保留归属和隔离边界。
- **中央节点暂停**：中央节点等南天门完成后再开，本版先把本机记忆和本机接入打实。

### 边界

- 发现接口默认只读。
- 安装 Skill 只是接入意图信号，不等于授权读取聊天正文。
- capability check 不召回真实记忆，不返回原文摘录。
- Windows 上全量本机表面扫描可能较重；默认面板路径已经保持快速，深扫应作为显式或后台任务处理。
