# Local AI Tool Entry Points

Many AI tools can follow a small local project rule. Time Library can prepare
that rule for you, so each tool knows the same simple behavior: when the question depends on old work, ask Time Library first.

This covers common local AI tool entry points without asking you to learn each
tool's private file format.

Time Library shows the right place and the text to use, then the agent can
remember to call `time_library_recall` before answering follow-up questions, old
project decisions, corrections, or release status.

The rule is easy:

- start with the current window or session
- then use the same project or workspace
- then use the same task
- then use stable preferences and tool facts
- only search wider memory when the user asks for that wider view

Time Library previews this first. It does not silently change your project
files or read chat bodies just to show the instructions.

## Connection Preview

The local runtime can preview how some tools would be connected without changing
their files. The preview shows the planned change, the safety copy, and the way
back if you later approve a real connection.

A preview is not the same as a real connection. A real connection still needs
your explicit approval for that tool, a safety copy, a way back, a health check,
and a real memory lookup after the tool is connected.

Current preview status is tracked in
[Local Runtime Preview](Local-Runtime-Preview.md).

## Work Preflight

For coding, install, sync, release-prep, or operational work, the safer entry is
Agent Work Preflight:

```text
time_library_recall(mode="work_preflight", query="<the work to do>")
```

This path is read-only. It should not write memory, call a model, or return raw
conversation excerpts. Its job is to help the agent decide what kind of work it
is about to do:

- `already_built_but_forgotten`
- `miswired`
- `diagnostic_gap`
- `actually_missing`

The result is only a starting hypothesis. The agent still needs to inspect the
repo, tests, tools, and wiki before editing.

## 中文

很多 AI 工具都可以遵守一条本机项目规则。Time Library 可以先帮你准备好这条规则，让每个工具都知道同一条简单行为：问题依赖旧上下文时，先问忆凡尘。

它会覆盖常见的本机 AI 工具入口。你不需要研究每个工具的文件格式，也不需要知道各工具的私有文件格式。

忆凡尘会告诉你该放在哪里、内容怎么写，让 agent 在回答旧决定、旧进度、纠错、安装/测试/发布状态这类问题前，先调用 `time_library_recall`。

规则很简单：先当前窗口或会话，再同项目或工作区，再同一条任务线，再稳定偏好和工具事实；只有你明确要求更宽视图时，才搜索更大的记忆范围。

Time Library 会先给出预览，不会为了展示这些指令就偷偷改项目文件或读取聊天正文。

## 自动接入预览

本机运行态可以先预览部分工具怎么接入，但预览不会写入外部平台配置。它只说明准备改哪里、
会如何留安全副本、以及之后怎么退回去。

预览不等于真正接入。真实接入仍需要你对具体平台单独授权，并且要有安全副本、退回路径、
健康检查和接入后的真实召回验证。当前预览状态见
[Local Runtime Preview](Local-Runtime-Preview.md)。

## 开工前自检

写代码、安装、同步、发版准备、远端排障这类工作，应该先走 Agent Work Preflight：

```text
time_library_recall(mode="work_preflight", query="<准备做的事>")
```

这条路径只读，不写记忆、不调用模型、不返回 raw 原文摘录。它只负责先分清楚：

- 已经做了但 agent 忘了；
- 已经做了但接线错了；
- 诊断入口不够；
- 真的缺功能。

这个判断只是起点，不能代替查代码、查测试、查工具和查 wiki。
