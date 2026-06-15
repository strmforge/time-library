# Local AI Tool Entry Points

Many AI tools can follow a small local project rule. Memcore Cloud can prepare
that rule for you, so each tool knows the same simple behavior: when the question depends on old work, ask Zhiyi first.

This covers common local AI tool entry points without asking you to learn each
tool's private file format.

Memcore Cloud shows the right place and the text to use, then the agent can
remember to call `zhiyi_recall` before answering follow-up questions, old
project decisions, corrections, or release status.

The rule is easy:

- start with the current window or session
- then use the same project or workspace
- then use the same task
- then use stable preferences and tool facts
- only search wider memory when the user asks for that wider view

Memcore Cloud previews this first. It does not silently change your project
files or read chat bodies just to show the instructions.

## Work Preflight

For coding, install, sync, release-prep, or operational work, the safer entry is
Agent Work Preflight:

```text
zhiyi_recall(mode="work_preflight", query="<the work to do>")
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

很多 AI 工具都可以遵守一条本机项目规则。Memcore Cloud 可以先帮你准备好这条规则，让每个工具都知道同一条简单行为：问题依赖旧上下文时，先问忆凡尘。

它会覆盖常见的本机 AI 工具入口。你不需要研究每个工具的文件格式，也不需要知道各工具的私有文件格式。

忆凡尘会告诉你该放在哪里、内容怎么写，让 agent 在回答旧决定、旧进度、纠错、安装/测试/发布状态这类问题前，先调用 `zhiyi_recall`。

规则很简单：先当前窗口或会话，再同项目或工作区，再同一条任务线，再稳定偏好和工具事实；只有你明确要求更宽视图时，才搜索更大的记忆范围。

Memcore Cloud 会先给出预览，不会为了展示这些指令就偷偷改项目文件或读取聊天正文。

## 开工前自检

写代码、安装、同步、发版准备、远端排障这类工作，应该先走 Agent Work Preflight：

```text
zhiyi_recall(mode="work_preflight", query="<准备做的事>")
```

这条路径只读，不写记忆、不调用模型、不返回 raw 原文摘录。它只负责先分清楚：

- 已经做了但 agent 忘了；
- 已经做了但接线错了；
- 诊断入口不够；
- 真的缺功能。

这个判断只是起点，不能代替查代码、查测试、查工具和查 wiki。
