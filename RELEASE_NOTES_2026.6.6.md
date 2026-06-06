# Memcore Cloud 2026.6.6

Memcore Cloud 2026.6.6 focuses on making local memory feel present in daily use:
it stays running, keeps up with local chat records, and gives agents a safer way
to pick up context without mixing every window together.

## English

### Highlights

- **Background companion on desktop**: Windows gets a tray entry and macOS gets a
  menu bar entry, so the local console, health view, and catch-up tools are one
  click away.
- **Closer to live local sync**: watchers stay active after install instead of
  acting like a one-time scan. Missed records can be caught up after restart or
  repair.
- **One Zhiyi model setting**: the same visible model setting powers Zhiyi and
  optional AI-assisted local-tool recognition. Default scans still use local
  metadata and do not read chat bodies.
- **Better recognition for unfamiliar tools**: Memcore Cloud can combine local
  app names, paths, config traces, workspace markers, and an optional model call
  to identify new local AI tools sooner.
- **Cleaner source boundaries**: Codex, Claude Desktop, Claude Code CLI,
  OpenClaw, Hermes, and open-source agents stay separate at the source layer, with
  recall widening only through the active routing ladder.
- **Native Windows stays the default**: Windows users install with PowerShell on
  Windows itself. WSL remains for development and special troubleshooting.

### Boundaries

- Capability check is still read-only and no-recall.
- Default discovery and dry-run scans do not send chat bodies or raw excerpts to
  a model.
- A discovered tool is not automatically a complete memory source. It becomes
  one only after its local format is verified.
- Ordinary recall is window-first. raw-pool/global recall remains explicit.

## 中文

### 主要更新

- **桌面常驻入口**：Windows 有托盘入口，macOS 有菜单栏入口，可以直接打开本地
  页面、查看健康状态、补扫漏掉的记录。
- **更接近日常使用的同步**：watcher 会持续运行，不是安装时扫一次。重启或修复
  安装后，也能继续追上漏掉的本机记录。
- **知意只保留一个模型设置**：同一个“知意模型”既给知意使用，也可以在你明确配置
  后帮助识别陌生本机 AI 工具。默认扫描仍然只看本机元数据，不读聊天正文。
- **陌生工具更容易认出来**：忆凡尘会结合应用名、路径、配置痕迹、工作区标记，以及
  可选模型识别，更快判断这台机器上出现了什么 AI 工具。
- **来源边界更清楚**：Codex、Claude Desktop、Claude Code CLI、OpenClaw、
  Hermes 和开源 agent 会按各自来源分开保留；普通召回按 active 分层逐步放宽。
- **Windows 继续默认原生安装**：普通 Windows 用户走 PowerShell 原生安装；WSL
  只用于开发和特殊排障。

### 边界

- capability check 仍然只读、无真实召回、不返回原文。
- 默认发现和 dry-run 不会把聊天正文或原始摘录发给模型。
- 发现某个工具不等于它已经是完整记忆源；只有本地格式验证后，才会升级为可回源记忆。
- 普通召回仍然窗口优先；raw-pool/global 只在明确要求时使用。
