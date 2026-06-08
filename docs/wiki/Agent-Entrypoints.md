# Agent Entrypoints

Many AI tools now read a small instruction file from your project. Memcore Cloud
can prepare those instructions for you, so each tool knows the same simple rule:
when the question depends on old work, ask Zhiyi first.

This covers common local entry points:

- Codex: `AGENTS.md`
- Claude Code: `CLAUDE.md`
- Gemini CLI: `.gemini/extensions/memcore-cloud-zhiyi/`
- GitHub Copilot: `.github/agents/memcore-cloud-zhiyi.md`
- Cursor: `.cursor/rules/memcore-cloud-zhiyi.mdc`
- Windsurf: `.devin/rules/memcore-cloud-zhiyi.md`

You do not need to know each tool's file format. Memcore Cloud shows the right
place and the text to use, then the agent can remember to call `zhiyi_recall`
before answering follow-up questions, old project decisions, corrections, or
release status.

The rule is easy:

- start with the current window or session
- then use the same project or workspace
- then use the same task
- then use stable preferences and tool facts
- only search wider memory when the user asks for that wider view

Memcore Cloud previews this first. It does not silently change your project
files or read chat bodies just to show the instructions.

## 中文

很多 AI 工具现在都会读取项目里的小型指令文件。Memcore Cloud 可以先帮你准备好这些指令，让每个工具都知道同一条简单规则：问题依赖旧上下文时，先问忆凡尘。

它会覆盖这些常见入口：

- Codex：`AGENTS.md`
- Claude Code：`CLAUDE.md`
- Gemini CLI：`.gemini/extensions/memcore-cloud-zhiyi/`
- GitHub Copilot：`.github/agents/memcore-cloud-zhiyi.md`
- Cursor：`.cursor/rules/memcore-cloud-zhiyi.mdc`
- Windsurf：`.devin/rules/memcore-cloud-zhiyi.md`

你不需要研究每个工具的文件格式。忆凡尘会告诉你该放在哪里、内容怎么写，让 agent 在回答旧决定、旧进度、纠错、安装/测试/发布状态这类问题前，先调用 `zhiyi_recall`。

规则很简单：先当前窗口或会话，再同项目或工作区，再同一条任务线，再稳定偏好和工具事实；只有你明确要求更宽视图时，才搜索更大的记忆范围。

Memcore Cloud 会先给出预览，不会为了展示这些指令就偷偷改项目文件或读取聊天正文。
