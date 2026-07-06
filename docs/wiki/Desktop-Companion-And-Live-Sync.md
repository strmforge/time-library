# Desktop Companion And Live Sync

Time Library is meant to stay available while you work, not only when a browser
tab is open.

On Windows, Time Library installs a tray entry. On macOS, it installs a menu bar
entry. Both give you a simple desktop entry point for:

- opening the local console;
- checking whether the local watcher is running;
- catching up missed local records after a restart or repair;
- opening logs when something needs attention.

The local console is still available at:

```text
http://127.0.0.1:9850
```

The desktop entry just means you do not have to remember that port.

## What Live Sync Means

Time Library keeps a local watcher running after install. The watcher prefers
file events when the operating system supports them, and falls back to a low
latency loop when needed.

The status page separates:

- tools that are only discovered;
- tools that are connected through Skill or MCP;
- tools whose local records are being continuously captured;
- tools still waiting for a verified local record format.

This matters because "I can see the app" is not the same as "its conversations
are safely preserved." Time Library should say which stage a tool is in.

## What It Does Not Mean

Live sync does not mean every local app is automatically read as conversation
memory.

Default discovery looks at local metadata and app traces. Conversation import
requires a verified local format collector. If a tool only exposes user turns
but not assistant replies, Time Library can keep that as evidence, but it should
not pretend it has a complete conversation.

## 中文

忆凡尘应该常驻，而不是每次都让你打开浏览器、记端口。

Windows 安装后有托盘入口，macOS 安装后有菜单栏入口。它们可以：

- 打开本地控制台；
- 查看本机 watcher 是否在运行；
- 重启或修复后补扫漏掉的记录；
- 打开日志查看问题。

本地页面仍然是：

```text
http://127.0.0.1:9850
```

托盘 / 菜单栏只是让入口更顺手。

接近实时同步的意思是：安装后 watcher 会持续运行，能用系统文件事件就用文件事件，
需要兜底时再用低延迟循环。状态页会区分“只是发现了工具”“Skill / MCP 已接上”
“本地记录正在持续采集”“还在等本地格式验证”。

这点很重要：看见一个软件，不等于已经安全保存了它的对话。忆凡尘应该把阶段说清楚。
