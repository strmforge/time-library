# Memcore Cloud 2026.6.11

Memcore Cloud 2026.6.11 is a reliability release for the local record base and
the active Zhiyi/Xingce path. It keeps the record-first boundary from 2026.6.9,
then makes recovery, preflight recall, and runtime health checks less passive.

## English

### Highlights

- **Checkpoint recovery**: corrupt P0 and P2 checkpoint files are preserved as
  `.corrupt-backup-*` files and the next save uses atomic replacement, so a bad
  local state file does not stall record capture.
- **Canonical session identity**: Codex and Claude Code records now normalize
  canonical window identity to the native session id while keeping older
  workspace/window hints as source refs and project clues.
- **Zhiyi/Xingce preflight**: the read-only preflight planner can decide when
  source-backed Zhiyi or Xingce anchors should surface before an agent answers,
  and when it should retreat silently.
- **Fast current-window recall**: the raw gateway can answer short continuation
  preflight requests from the canonical record index without cold-loading broad
  recall or returning raw excerpts.
- **Claude Code hook**: installers can add a quiet `UserPromptSubmit` hook for
  Claude Code. It only emits additional context when preflight returns a
  source-backed `surface` decision.
- **Runtime guard tightening**: raw gateway health reports its source identity
  and hash; Windows guardian checks that identity and reports foreign port
  owners. Dialog-entry tokens are scoped to dialog-entry service commands
  instead of being injected into unrelated local services.

### Boundaries

- Preflight is a behind-the-scenes agent aid, not a new user-facing feature.
- Capability check remains read-only and no-recall.
- Raw excerpts are not exposed by preflight bridge compaction or the Claude Code
  hook.
- LAN reachability for OpenClaw and Hermes remains supported when explicitly
  configured.

## 中文

### 主要更新

- **checkpoint 坏账本恢复**：P0 / P2 checkpoint 损坏时会先备份为
  `.corrupt-backup-*`，后续保存改为原子替换，避免一个坏状态文件卡住记录采集。
- **canonical session 身份修正**：Codex 和 Claude Code 记录把 canonical window
  统一到原生 session id，同时把旧 workspace/window 线索保留为 source refs 和项目线索。
- **知意 / 行策 preflight**：新增只读裁判层，能判断什么时候应该在回答前主动浮现有来源的知意
  或行策锚点，什么时候应该静默退回。
- **当前窗口快速召回**：raw gateway 可以从 canonical record index 回答短续问 preflight，
  不冷启动宽范围召回，也不返回 raw 原文。
- **Claude Code hook**：安装器可以写入安静的 `UserPromptSubmit` hook；只有 preflight
  返回有来源的 `surface` 决策时才给 Claude Code 增加上下文。
- **运行守护收紧**：raw gateway health 带 source 身份和哈希；Windows guardian 校验该身份并报告
  端口归属。dialog-entry token 只进入 dialog-entry 服务命令，不再扩散到无关本地服务。

### 边界

- preflight 是 agent 背后的辅助机制，不是新的用户功能入口。
- capability check 仍然只读、无真实召回。
- preflight bridge 和 Claude Code hook 不暴露 raw excerpt。
- 明确配置时仍然保留 OpenClaw / Hermes 的局域网访问能力。
