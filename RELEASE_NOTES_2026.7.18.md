# Time Library 2026.7.18

2026.7.18 improves local setup and connection reliability, simplifies the
local service entry point, strengthens source-backed archive preservation, and
adds clearer local visibility into model-assisted processing.

Windows repair installs now pass the declared mirror-copy arguments to
`robocopy`, so an existing installation can be upgraded without the installer
failing before file synchronization. The local transparency ledger and
front-door singleton also use native Windows-compatible locking and process
identity checks instead of the POSIX-only `os.kill(pid, 0)` pattern.
Existing Windows installs now require a complete program backup before
mirroring, prepare dependency wheels before stopping active services, create
the replacement Python environment at its final path, and restore program,
configuration, migration state, Python environment, and runtime availability
when an upgrade transaction fails. `-NoStart` now rejects a running install
root instead of mixing new files with old processes.

## 中文

2026.7.18 改进本机安装与连接可靠性，简化本机服务入口，加强可回源归档保全，
并让模型辅助处理的本机过程更清楚可查。

Windows 修复安装现会把已声明的镜像复制参数正确传给 `robocopy`，避免既有安装在
文件同步前因空参数调用而失败。本地透明账本与单前门锁也改用 Windows 原生兼容的
文件锁和进程身份检查。
