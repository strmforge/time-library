# Automatic Reminders

Time Library should not wait for you to remember the memory command every time.
When an AI tool supports automatic moments, Time Library can prepare simple
reminders for that tool.

Useful moments include:

- when a new AI session starts
- before the agent answers a follow-up question
- before a command or file-changing action
- after tool work finishes
- before the conversation gets compressed
- when a session ends and missed records need to catch up

Claude Code and Gemini CLI expose stronger event support today. Codex, Cursor,
and Windsurf can still use project instructions, rules, workflows, and the local
watcher so the memory habit stays alive even without a native event file.

The user-facing goal is simple: if the next answer depends on old work, the
agent should ask Time Library first.

Time Library shows these reminders before applying anything. It does not
silently change project files or read chat bodies just to show what would happen.

## 中文

Time Library 不应该每次都等你手动想起记忆命令。只要某个 AI 工具支持自动时刻，Time Library就可以帮它准备简单提醒。

常见时刻包括：

- 新 AI 会话开始时
- agent 回答追问之前
- 执行命令或改文件之前
- 工具执行完成之后
- 对话被压缩之前
- 会话结束、需要补上漏掉记录时

Claude Code 和 Gemini CLI 现在有更强的事件支持。Codex、Cursor 和 Windsurf 即使没有同样的原生事件文件，也可以通过项目指令、规则、工作流和本机 watcher 维持这条记忆习惯。

用户看到的目标很简单：如果下一个回答依赖旧上下文，agent 应该先问Time Library。

Time Library 会先展示这些提醒，不会为了展示效果就偷偷改项目文件或读取聊天正文。
