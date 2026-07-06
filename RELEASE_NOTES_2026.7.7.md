# Time Library 2026.7.7

2026.7.7 is the rename-and-release-prep cut for Time Library. It moves the
public repository, release package, installer defaults, and user-facing install
paths to `time-library` while preserving legacy `memcore-cloud` roots as
migration and uninstall fallbacks.

## What Changed

- One-command installers now download `strmforge/time-library` release assets
  named `time-library-<version>.zip`.
- Fresh installs default to Time Library paths:
  - macOS: `~/Library/Application Support/time-library`
  - Linux: `~/.local/share/time-library`
  - Windows: `%LOCALAPPDATA%\time-library`
- Existing `memcore-cloud` installs are copied forward by full installers when
  the new default path is empty, so user data is preserved.
- Windows, macOS, Linux, tray, and menu bar helpers now use the new public
  install path by default.
- Public docs and smoke commands now point at `time-library` paths and
  `TIME_LIBRARY_*` environment variables.
- Release packages are built as `time-library-<version>.zip`.
- The bge-m3 switch is wired through the saved recall preference path.
- Hermes autonomous learning is value-gated and budgeted: the background
  controller can wake on a schedule, but it only spends when new raw evidence
  makes a run due.

## Compatibility

- Legacy `MEMCORE_*` environment variables still work as fallback inputs.
- Legacy install roots such as `~/Library/Application Support/memcore-cloud`
  and `%LOCALAPPDATA%\memcore-cloud` remain migration sources and uninstall
  fallback targets.
- Internal service labels and watcher script names that still contain
  `memcore` are retained for compatibility in this cut.

## Boundaries

- This release changes source/package/install defaults. It does not forcibly
  move a currently running local macOS installation at runtime.
- Production experience auto-adoption remains disabled by default.
- The rename does not claim cross-machine synchronization is fully proven.

## 中文

2026.7.7 是 Time Library 的公开版本，也是正名与发布准备版本：公开仓库、发布包、安装器默认值
和用户可见安装路径都切到 `time-library`，同时保留旧 `memcore-cloud` 目录作为迁移
和卸载兜底，避免老用户数据丢失。

### 本版本包含

- 一键安装器默认下载 `strmforge/time-library` 的 release 资产，包名为
  `time-library-<version>.zip`。
- 新安装默认路径改为：
  - macOS: `~/Library/Application Support/time-library`
  - Linux: `~/.local/share/time-library`
  - Windows: `%LOCALAPPDATA%\time-library`
- 如果新默认路径为空但旧 `memcore-cloud` 安装存在，完整安装器会把用户数据复制到
  新路径。
- Windows、macOS、Linux、托盘和菜单栏工具默认都使用新的公开安装路径。
- 公开文档和 smoke 命令改用 `time-library` 路径与 `TIME_LIBRARY_*` 环境变量。
- 发布包改为 `time-library-<version>.zip`。
- bge-m3 开关已接入保存后的默认召回偏好。
- Hermes 自主学习改为价值门控和预算上限：后台可以按计划醒来，但只有新 raw 证据
  到期时才花费运行。

### 兼容边界

- 旧 `MEMCORE_*` 环境变量仍作为 fallback 可用。
- 旧安装目录仍作为迁移源和卸载 fallback 保留。
- 仍带 `memcore` 的内部服务 label 和 watcher 文件名本刀先保留，避免破坏现有运行态。
- 本版本不强搬当前正在运行的本机 macOS installed runtime。
