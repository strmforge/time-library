# Memcore Cloud 2026.6.4

Memcore Cloud 2026.6.4 turns the last two days of construction into a release:
native Windows installs, official Codex MCP connection, active memory routing,
and clearer local-tool discovery.

The product promise is simple: install once, let Memcore Cloud find local AI
tools, connect supported Skill/MCP surfaces, and keep recall tied to source
records without making every new window start from zero.

## English

### Highlights

- **Native Windows is now the normal path**: Windows users should install
  Memcore Cloud directly with PowerShell. WSL remains for development or
  advanced testing.
- **Official Codex on Windows is verified**: Memcore Cloud can find the bundled
  official `codex.exe` even when it is not on `PATH`, then register
  `yifanchen-zhiyi` through official `codex mcp add`.
- **Codex MCP uses a current-window bridge**: the installed Codex MCP entry uses
  a local stdio bridge so recall can carry window/session identity instead of
  guessing from another Codex session.
- **Active recall is window-first, not window-only**: ordinary clients try the
  current window/session first, then same project/workspace, same
  workstream/task, and stable preferences/tool facts. raw-pool/global remains
  explicit; Hermes broad context stays limited to explicit skill-generation or
  review workflows.
- **Continuous sync is visible**: the local service now reports whether
  watchers are running as a continuous loop instead of a one-time install scan.
  Claude Desktop local capture joins that loop by default, writing only Memcore
  Cloud raw records, while pending collectors stay clearly marked.
- **Conversation collectors are stricter**: a local tool is not promoted to
  complete conversation memory unless the verified local format preserves both
  user turns and assistant replies.
- **New-tool recognition has two layers**: deterministic local rules run first;
  when a model provider is configured, model-assisted identification can classify
  unfamiliar local AI tools from metadata only.
- **Knowledge base pages were updated**: the Windows official Codex validation
  is now documented in the wiki for future troubleshooting.

### Boundaries

- A Skill/MCP connection proves the tool can call Memcore Cloud; it does not
  mean real memory was recalled.
- Capability check remains read-only and no-recall.
- Claude Desktop local capture can enter Memcore Cloud raw by default. Ordinary
  recall is active and source-backed: current window/session first, then same
  project/workspace, same workstream/task, and stable preferences/tool facts.
- Not every discovered local AI tool has a verified collector yet. Unknown or
  partial formats stay as candidates until source-backed collection is proven.

## 中文

### 主要更新

- **Windows 默认走原生安装**：普通 Windows 用户不该装到 WSL。WSL 只保留给
  开发、高级测试或特殊排障。
- **官方 Windows Codex 已验证**：即使 `codex.exe` 不在 PATH，忆凡尘也能从
  Codex native-host 元数据找到官方 bundled CLI，然后用官方 `codex mcp add`
  注册 `yifanchen-zhiyi`。
- **Codex MCP 走当前窗口 bridge**：安装后的 Codex MCP 入口使用本地 stdio
  bridge，召回时带上窗口/session 线索，不再靠猜另一个 Codex 会话。
- **active 召回是窗口优先，不是窗口锁死**：普通客户端先读当前窗口/session，
  然后同项目/同工作区、同工作流/同任务、稳定偏好/工具事实。raw-pool/global
  仍然只在明确要求更宽视图时使用；Hermes 的宽上下文只保留给明确的 skill
  生成或审查流程。
- **持续同步状态可见**：本地服务会报告 watcher 是持续循环，不是安装时扫一次。
  Claude Desktop 本机采集默认加入这个循环，只写忆凡尘 raw；仍待验证的采集器会
  继续标成候选。
- **对话采集更严格**：只有已验证的本地格式同时保留用户发言和 AI 回复，才会被
  当作完整对话记忆来源。
- **新工具识别变成两层**：先用本机规则识别；如果配置了模型，再让模型只根据
  元数据识别陌生本机 AI 工具。没有模型时继续走本地规则兜底。
- **知识库补齐**：Windows 官方 Codex 原生验证已经写入 wiki，方便后续排障。

### 边界

- Skill / MCP 接上，只证明这个工具能调用忆凡尘，不代表已经召回真实记忆。
- capability check 仍然只读、无真实召回、不返回原文。
- Claude Desktop 本机记录默认可以进入忆凡尘 raw。普通召回走 source-backed
  active 分层：当前窗口/session 优先，然后同项目/同工作区、同工作流/同任务、
  稳定偏好/工具事实。
- 不是每个发现到的本机 AI 工具都有完整采集器。未知格式或只保存部分对话的工具，
  仍然只能标为候选，不能宣传成完整记忆来源。
