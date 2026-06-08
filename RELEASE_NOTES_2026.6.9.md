# Memcore Cloud 2026.6.9

Memcore Cloud 2026.6.9 is a record-first release candidate: it tightens the
local record base, keeps source boundaries clearer, and adds release gates for
the larger pre-release change set.

## English

### Highlights

- **Record Origin Guard**: raw source records are treated as the origin of the
  local memory timeline. The guardian checks source/raw freshness, corruption,
  recoverability, and lost source / lost raw states.
- **All-session canonical index**: Codex, Claude Code CLI, Claude Desktop,
  OpenClaw, Hermes, and other verified local records can be indexed across
  sessions without turning summaries into authority.
- **Claude Desktop three-surface model**: Chat is handled as the `claude.ai`
  web-chat surface with local cache evidence only; Cowork and Code/agent records
  use verified local JSONL body candidates when available.
- **Safer LAN entry points**: local action routes are token-gated while keeping
  LAN access available for setups that intentionally use OpenClaw or Hermes from
  another machine on the same network.
- **Second Brain and Time River contracts**: material processing, external docs
  evidence, context delivery compaction, and Time River sediment now have
  bounded dry-run contracts. They strengthen source-backed recall without
  replacing raw records.
- **Release gate coverage**: the pre-release gate compiles Python, checks
  installer syntax, scans public wording, runs internal direction and core record
  reliability audits, and executes the test suite.

### Boundaries

- Chat cache evidence is not claimed as a complete local Claude.ai transcript.
- Capability check remains read-only and no-recall.
- Public docs avoid development-only relay/tool names as dependencies.
- User-facing status should show record health, recovery, and lost source / lost
  raw states rather than internal construction progress.

## 中文

### 主要更新

- **记录底座与时间起源**：原始 source / raw 记录被放回记忆系统的起点。记录守护会检查
  source/raw 新鲜度、损坏、可恢复状态，以及遗失源 / 遗失 raw。
- **所有会话 canonical index**：Codex、Claude Code CLI、Claude Desktop、
  OpenClaw、Hermes 和其他已验证本机记录可以进入跨会话索引，但摘要仍然只是导航，不替代原始记录。
- **Claude Desktop 三模式分型**：Chat 按 `claude.ai` 网页聊天表面处理，本地只算缓存证据；
  Cowork 和 Code/agent 在可验证时使用本地 JSONL 正文候选。
- **LAN 入口安全分档**：动作路由加 token gate，同时保留有意使用局域网连接 OpenClaw /
  Hermes 的能力。
- **第二大脑与时间长河契约**：资料处理流水线、外部文档证据、上下文投递压缩、时间长河沉积
  都进入有边界的 dry-run 合同，用来增强可回源召回，不替代 raw。
- **发布前检查增强**：release gate 会编译 Python、检查安装脚本语法、扫描公开文案、运行
  内部方向审计、核心记录可靠性审计和测试套件。

### 边界

- Chat 缓存证据不声明为完整本地 Claude.ai transcript。
- capability check 仍然只读、无真实召回、不返回原文。
- 公开文档不把开发环境里的中转工具名写成用户依赖。
- 普通用户界面应该展示记录健康、恢复和遗失源 / 遗失 raw，而不是内部施工完成度。
