# Memcore Cloud 2026.6.3

Memcore Cloud 2026.6.3 focuses on making the installed skill behave like a real memory habit, not a one-time setup note.

The main change is simple: when an agent sees an ongoing-project question like "what next", "what else", "then what", "之前", "定论", or "还有吗", it should know to call `zhiyi_recall` before answering.

## English

### Highlights

- **The skill is now a standing memory rule**: Memcore Cloud Zhiyi prompt v4 tells Codex, Claude Desktop, and other local agents to keep the rule active after installation.
- **Natural follow-ups trigger memory first**: prior decisions, corrections, project boundaries, install/test/release status, and short next-step questions now get clearer recall-before-answer wording.
- **Install prompts are clearer**: README, Wiki, and the local console copy prompt now tell users to paste one prompt into a local agent so it can install the skill, connect MCP, and run a safe check.
- **Safe checks stay safe**: capability check still verifies the Skill/MCP path without recalling real memory or returning raw excerpts.
- **Local install alignment is verified**: macOS and native Windows install roots can be upgraded in place while preserving user data, then installing prompt v4 into Codex and Claude Desktop skill locations.

### Boundaries

- Claude Desktop UI testing still depends on Claude quota being available.
- Skill installation is a connection signal, not permission to read chat bodies.
- Deeper platform access still needs explicit authorization.

## 中文

### 主要更新

- **Skill 变成长期记忆规则**：Memcore Cloud Zhiyi prompt v4 会告诉 Codex、Claude Desktop 和其他本机 agent，安装后要持续遵守，而不是只看一次安装说明。
- **自然追问会先想起记忆**：旧决定、纠错、项目边界、安装/测试/发布状态，以及“下一步 / 接下来呢 / 还有吗 / 然后呢”这类短追问，会更明确触发先调 `zhiyi_recall`。
- **安装提示更像产品入口**：README、Wiki 和本地 console 的复制提示都改成“把这段发给本机 agent，它会安装 skill、接 MCP、做安全检查”。
- **安全检查仍然安全**：capability check 仍然只验证 Skill/MCP/只读状态，不召回真实记忆、不返回原文。
- **本机安装目录已校准**：macOS 和 Windows 原生安装目录都可以原地升级并保留用户数据，同时把 prompt v4 安装到 Codex 和 Claude Desktop 的 skill 位置。

### 边界

- Claude Desktop UI 真实窗口测试仍受 Claude 额度影响。
- 安装 Skill 只是接入信号，不等于授权读取聊天正文。
- 更深的平台访问仍需要明确授权。
