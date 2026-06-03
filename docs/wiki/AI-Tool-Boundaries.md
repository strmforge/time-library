# AI Tool Boundaries

Memcore Cloud can help multiple AI tools use the same local memory base, but it keeps their surfaces separate.

## Default Scope

The original anti-pollution rule is window-first.

By default, a conversation window should prefer its own records and its own
source refs before using broader project or cross-platform memory. Shared memory
is useful, but it should not silently flatten every local AI tool window into
one scope.

Memcore Cloud can expose broader project memory when the workflow asks for it.
The routing layer must make that scope choice explicit:

- current window / current session;
- current platform;
- current project;
- same computer;
- all local tools;
- explicit review or skill-generation workflow scope.

Hermes normal recall follows the same window-first rule. Only explicit Hermes
review and skill-generation workflows may use broader source-backed context.
That is a special review mode, not the default recall rule for Hermes or any
other agent window.

## Claude

Claude Desktop and Claude Code CLI are first-class surfaces, but they are not the same source.

- Claude Desktop can use Memcore Cloud through local MCP / Desktop Extensions.
- Claude Code CLI can use MCP while staying separate from Claude Desktop.
- Official-login, relay, and CLI-related records keep attribution boundaries.
- Conversation import uses verified local collectors and keeps Claude attribution fields separate.

## Codex

Codex can use the shared skill and MCP entry. Local Codex sessions can also become source-backed records when local capture is enabled.

## OpenClaw

OpenClaw can receive memory support through local entry points and can contribute raw records with source refs.

## Hermes

Hermes can consume raw/source-ref pointers and inspect sources itself. Memcore Cloud observes native feedback without taking ownership of Hermes skill changes.

## Other Local AI Tools

The local page shows AI tools found on the machine, connects supported Skill/MCP surfaces automatically, and promotes a tool to a memory source when its local format is verified.

Some local AI tools may show full conversation history in the app but persist
only part of the conversation on disk. A tool must not be treated as complete
conversation memory until a verified collector proves that assistant replies as
well as user turns are saved locally.

Discovery and auto-connect can inspect metadata, config paths, MCP surfaces, and
storage shapes. They do not read chat bodies during discovery or dry-run.

## 中文

忆凡尘可以让多个本机 AI 工具使用同一个记忆底座，但不会把平台边界抹平。

Claude Desktop、Claude Code CLI、官方登录、中转服务和 CLI 运行时产生的记录要保留归属。安装后会自动发现本机 AI 工具，支持 Skill / MCP 的入口会自动接入；对话进入记忆时走已验证的本地格式采集器。

默认防污染规则仍然是“窗口优先”：一个窗口先读自己的记录，再按需要扩到平台、项目、同电脑或全局。Hermes 的普通召回同样按窗口隔离；只有明确的 skill 生成和审查流程可以读更宽的上下文，这是特例，不是 Hermes 或任何窗口的默认规则。

部分本机 AI 工具要先验证本地文件是否同时保存用户发言和 AI 回复。没验证前，只能说看到了入口或本地记录候选，不能说已经完整接入对话记忆。
