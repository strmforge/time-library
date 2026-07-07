# AI Tool Boundaries

Time Library can help multiple AI tools use the same local memory base, but it keeps their surfaces separate.

## Default Scope

The original anti-pollution rule is window-first.

By default, a conversation window should prefer its own records and its own
source refs before using broader project or cross-platform memory. Shared memory
is useful, but it should not silently flatten every local AI tool window into
one scope.

Time Library uses active recall by default. It starts close to the current
conversation, then widens only as much as the question needs:

- current window / current session;
- same project / workspace;
- same workstream / task;
- stable user preferences and tool facts;
- wider shared or global memory only when explicitly requested.

Hermes normal recall follows the same window-first rule. Only explicit Hermes
review and skill-generation workflows may use broader source-backed context.
That is a special review mode, not the default recall rule for Hermes or any
other agent window.

## Claude

Claude Desktop and Claude Code CLI are first-class surfaces, but they are not the same source.

- Claude Desktop can use Time Library through local MCP / Desktop Extensions.
- Claude Code CLI can use MCP while staying separate from Claude Desktop; it is an independent install/runtime surface.
- Claude Desktop may also manage a local Claude Code runtime. Its code-session metadata can point to Claude Code JSONL body records, but metadata is not the conversation body and the managed runtime is not a user-installed PATH CLI.
- Official-login, Desktop-managed runtime, and CLI-related records keep attribution boundaries.
- Conversation import uses verified local collectors and keeps Claude attribution fields separate.

## Codex

Codex can use the shared skill and MCP entry. Local Codex sessions can also become source-backed records when local capture is enabled.

## OpenClaw

OpenClaw can receive memory support through local entry points and can contribute raw records with source refs.

## Hermes

Hermes can consume raw/source-ref pointers and inspect sources itself. Time Library observes native feedback without taking ownership of Hermes skill changes.

## Other Local AI Tools

The local page shows AI tools found on the machine, connects usable local entries automatically, and promotes a tool to a memory source when its local format is verified.

Some local AI tools may show full conversation history in the app but persist
only part of the conversation on disk. A tool must not be treated as complete
conversation memory until a verified collector proves that assistant replies as
well as user turns are saved locally.

Discovery and auto-connect can inspect metadata, config paths, local entry signals, and
storage shapes. They do not read chat bodies during discovery or dry-run.

## 中文

Time Library可以让多个本机 AI 工具使用同一个记忆底座，但不会把平台边界抹平。

Claude Desktop、Claude Code CLI、官方登录、Desktop 托管本地 runtime 和 CLI 运行时产生的记录要保留归属。Claude Code CLI 是独立安装 / 运行入口；Desktop 目录下的 code-session 元数据可以指向 Claude Code JSONL 正文，但元数据不是正文，Desktop 托管 runtime 也不是用户安装到 PATH 的 CLI。安装后会自动发现本机 AI 工具，并把可用入口接入同一套本机记录底座；对话进入记忆时走已验证的本地格式采集器。

默认防污染规则仍然是“窗口优先”：当前窗口/session 先读，然后才是同项目/同工作区、同工作流/同任务、稳定偏好/工具事实。只有用户明确要求更宽视图时，才读共享或全局记忆。Hermes 的普通召回同样按窗口优先；只有明确的 skill 生成和审查流程可以读更宽的上下文，这是特例，不是 Hermes 或任何窗口的默认规则。

部分本机 AI 工具要先验证本地文件是否同时保存用户发言和 AI 回复。没验证前，只能说看到了入口或本地记录候选，不能说已经完整接入对话记忆。
