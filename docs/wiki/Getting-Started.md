# Getting Started

## Install

macOS / Linux:

```bash
curl -fL -o memcore-cloud-install.sh https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.14/install.sh
bash memcore-cloud-install.sh
```

Windows PowerShell:

```powershell
iwr https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.14/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

If you downloaded the release zip, Windows can also use the double-click
`Memcore Cloud Installer.cmd`; it opens a folder picker and then runs the same
installer with the selected path. On macOS, double-click
`Memcore Cloud Installer.command` from the extracted release folder.

Windows installs default to `%LOCALAPPDATA%\memcore-cloud`. To choose a path
before the install:

```powershell
$env:MEMCORE_INSTALL_DIR = "D:\Apps\memcore-cloud"
iwr https://github.com/strmforge/memcore-cloud/releases/download/v2026.6.14/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

If you already downloaded the repo, you can also run:

```powershell
.\install.ps1 -Dir "D:\Apps\memcore-cloud"
```

WSL is only for development or advanced testing. Normal Windows installs should
use the Windows PowerShell command above.

On Windows, use the Memcore Cloud tray icon after install. On macOS, use the
Memcore Cloud menu bar icon. Both can open the local console, show health, and
catch up missed records.

You can also open the local console directly:

```text
http://127.0.0.1:9850
```

## Paste This To Your Local Agent

If you use a local AI agent that can run terminal commands, paste this:

```text
You are installing Memcore Cloud for me on this machine.
Repository: https://github.com/strmforge/memcore-cloud

Install and start Memcore Cloud. Then install Memcore Cloud Zhiyi as a standing memory rule for this agent, not just a one-time setup note. If this platform supports skills or custom instructions, add the Memcore Cloud Zhiyi skill/instruction. If this platform supports MCP, register the MCP tool named yifanchen-zhiyi at http://127.0.0.1:9851/mcp.

After setup, run only a safe capability check with zhiyi_recall:
{"query":"capability check","mode":"capability_check"}
Do not recall my real memory yet; do not recall my real memory until I ask.

Keep this rule active from now on. When my question depends on prior context, call zhiyi_recall before answering and use source refs by default; ask for raw excerpts only when I explicitly need original evidence text. Triggers include previous decisions, corrections, project boundaries, forgotten context, install/test/release status, and short follow-ups in ongoing work such as "next step", "what else", or "then what". Use active recall by default: current window/session first, then same project/workspace, same workstream/task, then stable preferences/tool facts. Use wider shared or global memory only when I explicitly ask for that wider view. If the skill is installed but zhiyi_recall is not available, tell me the MCP/tool connection is missing instead of guessing from memory.
```

Chinese prompt:

```text
你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）。
仓库：https://github.com/strmforge/memcore-cloud

请安装并启动 Memcore Cloud。然后把 Memcore Cloud Zhiyi 安装成这个 agent 的长期记忆规则，不只是一次性安装说明。如果这个平台支持 skill 或自定义指令，请添加 Memcore Cloud Zhiyi skill/指令；如果这个平台支持 MCP，请注册名为 yifanchen-zhiyi 的 MCP 工具，地址是 http://127.0.0.1:9851/mcp。

安装完成后，只做一次安全能力检查：
{"query":"capability check","mode":"capability_check"}
先不要召回我的真实记忆。

以后请持续遵守这条规则。凡是我的问题依赖旧上下文，请先调用 zhiyi_recall，默认结合 source_refs 回答；只有我明确需要原文证据时，才请求 raw_excerpt。触发词包括：之前、定论、纠错、边界、忘了、安装/测试/发布状态，以及持续项目里的“下一步/接下来呢/还有吗/然后呢”。默认使用 active 召回：当前窗口/session 优先，然后同项目/同工作区、同工作流/同任务、稳定偏好/工具事实。只有我明确要求更宽视图时，才使用共享或全局记忆。如果 skill 已安装但 zhiyi_recall 不可用，请告诉我 MCP/工具连接还没接上，不要凭印象猜。
```

## First Run

1. Start the local service.
2. Open `http://127.0.0.1:9850`.
3. Let Memcore Cloud find local AI tools and connect usable local entries.
4. Run capability check before real recall.
5. Use real recall when the current question depends on prior context.

Install once, then it keeps looking for usable local AI tools. Conversation import uses verified local formats, so memory can stay tied to source records.

## What To Check Next

- [Desktop Companion And Live Sync](Desktop-Companion-And-Live-Sync.md): make sure the watcher keeps running and missed records can be caught up.
- [Local Tool Recognition](Local-Tool-Recognition.md): see how Memcore Cloud identifies local AI tools and when the Zhiyi model can help.
- [AI Tool Boundaries](AI-Tool-Boundaries.md): understand why different tools and windows keep their source trails.
