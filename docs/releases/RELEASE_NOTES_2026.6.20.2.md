# Memcore Cloud 2026.6.20.2

2026.6.20.2 is a small safety-followup patch. It keeps the passive-first
OpenClaw/Zhiyi behavior and fixes two release hygiene problems:
runtime surfaces now report the real package version from `VERSION`, and
Windows scripts no longer collide with PowerShell's read-only `$PID` variable.

## What Changed

- Runtime version reporting now uses a single source:
  - `VERSION`
  - `src/memcore_version.py`
- Raw gateway health, MCP/server metadata, preflight surfaces, console APIs, and
  the local console UI no longer report stale `2026.6.20` strings after a patch
  install.
- Windows guardian and uninstall scripts avoid assigning to PowerShell's
  read-only `$PID` automatic variable.
- Release gate now blocks runtime version literals in user-visible/reporting
  surfaces and blocks future PowerShell `$PID` assignment regressions.
- One-command installers now default to `2026.6.20.2`.

## Boundaries

- This release keeps the 2026.6.20 passive-first delivery behavior:
  - `zhiyi_direct=false`
  - `zhiyi_inject=false`
  - `openclaw_rpc=false`
  - `passthrough=true`
- This release does not publish benchmark scores or leaderboard claims.
- Contract identifiers such as `agent_work_preflight.v2026.6.20` remain protocol
  ids and are not runtime package-version strings.

## 中文

2026.6.20.2 是一个小型安全跟进补丁。它保留 OpenClaw / 知意 passive-first
的止血结果，同时修掉两个发布卫生问题：运行态版本面统一从
`VERSION` 读取真实包版本，Windows 脚本不再撞 PowerShell 只读 `$PID` 变量。

### 本版本包含

- 运行态版本上报改成单一来源:
  - `VERSION`
  - `src/memcore_version.py`
- raw gateway health、MCP/server metadata、preflight、console API 和本地控制台
  UI 不再在补丁安装后继续显示旧的 `2026.6.20`。
- Windows guardian 和卸载脚本不再给 PowerShell 只读 `$PID` 自动变量赋值。
- release gate 增加机械门，阻止运行态版本字面量回到用户可见/健康上报面，也阻止
  PowerShell `$PID` 赋值类回归。
- 一键安装脚本默认版本更新到 `2026.6.20.2`。

### 边界

- 本版本保留 2026.6.20 的 passive-first 默认:
  - `zhiyi_direct=false`
  - `zhiyi_inject=false`
  - `openclaw_rpc=false`
  - `passthrough=true`
- 本公开版本不发布 benchmark 分数，也不声明任何公开榜单成绩。
- `agent_work_preflight.v2026.6.20` 这类 contract id 是协议版本，不是运行包版本。
