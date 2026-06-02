# AI Tool Boundaries

Memcore Cloud can help multiple AI tools use the same local memory base, but it keeps their surfaces separate.

## Claude

Claude Desktop and Claude Code CLI are first-class surfaces, but they are not the same source.

- Claude Desktop can use Memcore Cloud through local MCP / Desktop Extensions.
- Claude Code CLI can use MCP while staying separate from Claude Desktop.
- Official-login, relay, and CLI-related records keep attribution boundaries.
- Reading local chat bodies requires explicit parser authorization.

## Codex

Codex can use the shared skill and MCP entry. Local Codex sessions can also become source-backed records when local capture is enabled.

## OpenClaw

OpenClaw can receive memory support through local entry points and can contribute raw records with source refs.

## Hermes

Hermes can consume raw/source-ref pointers and inspect sources itself. Memcore Cloud observes native feedback without taking ownership of Hermes skill changes.

## Other Local AI Tools

The local page may show other tools present on the machine. Discovery means Memcore Cloud saw an entry point. It does not mean the tool is connected, readable, or imported.

## 中文

忆凡尘可以让多个本机 AI 工具使用同一个记忆底座，但不会把平台边界抹平。

Claude Desktop、Claude Code CLI、官方登录、中转服务和 CLI 运行时产生的记录要保留归属。发现某个工具，只代表看见入口，不代表已经读取正文。
