# Getting Started

## Install

2026.7.7.1 is the current published release. Download the release zip or use
the versioned install scripts from GitHub Releases.

macOS / Linux:

```bash
curl -fL -o time-library-install.sh https://github.com/strmforge/time-library/releases/download/v2026.7.7.1/install.sh
bash time-library-install.sh
```

Windows PowerShell:

```powershell
iwr https://github.com/strmforge/time-library/releases/download/v2026.7.7.1/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

If you downloaded the release zip, you can also use the Windows installer entry
or the macOS installer entry from the extracted release folder.

Windows installs default to `%LOCALAPPDATA%\time-library`. To choose a path
before the install:

```powershell
$env:TIME_LIBRARY_INSTALL_DIR = "D:\Apps\time-library"
iwr https://github.com/strmforge/time-library/releases/download/v2026.7.7.1/install.ps1 -OutFile .\install.ps1
.\install.ps1
```

If you already downloaded the repo, you can also run:

```powershell
.\install.ps1 -Dir "D:\Apps\time-library"
```

WSL is only for development or advanced testing. Normal Windows installs should
use the Windows PowerShell command above.

On Windows, use the Time Library tray icon after install. On macOS, use the
Time Library menu bar icon. Both can open the local console, show health, and
catch up missed records.

You can also open the local console directly:

```text
http://127.0.0.1:9850
```

## Paste This To Your Local Agent

If you use a local AI agent that can run terminal commands, paste this:

```text
You are installing Time Library for me on this machine.
Repository: https://github.com/strmforge/time-library

First check whether Time Library is already installed and running on this machine. Probe `http://127.0.0.1:9851` and any local install marker you know how to inspect. If it is already installed and reachable, do not reinstall it. In that case, only connect this platform's native delivery surface and MCP. If it is not installed, install and start Time Library.

Then install Time Library as a standing memory rule for this agent, not just a one-time setup note. If this platform supports skills or custom instructions, add the Time Library skill/instruction. If this platform supports MCP, register the MCP tool named time-library at http://127.0.0.1:9851/mcp. If this platform is Claude Code, also install the UserPromptSubmit hook that calls the local Time Library preflight path; that hook must stay quiet and never block prompts when 9851 is unavailable.

After setup, run only a safe capability check with time_library_recall:
{"query":"capability check","mode":"capability_check"}
Do not recall my real memory yet; do not recall my real memory until I ask.

Keep this rule active from now on. When my question depends on prior context, call time_library_recall before answering and use source refs by default; ask for raw excerpts only when I explicitly need original evidence text. Triggers include previous decisions, corrections, project boundaries, forgotten context, install/test/release status, and short follow-ups in ongoing work such as "next step", "what else", or "then what". Use active recall by default: current window/session first, then same project/workspace, same workstream/task, then stable preferences/tool facts. Use wider shared or global memory only when I explicitly ask for that wider view. If explicit window-only recall says the current window/session is not bound yet, say that plainly; do not claim there is no memory. If the skill is installed but time_library_recall is not available, tell me the MCP/tool connection is missing instead of guessing from memory. You may mention legacy zhiyi_recall only as a migration fallback, not as the primary instruction.
```

Chinese prompt:

```text
你正在帮我在这台机器安装 Time Library。
仓库：https://github.com/strmforge/time-library

请先检查这台机器上的 Time Library 是否已经安装并在运行。探测 `http://127.0.0.1:9851`，也检查你已知的本地安装标记。如果已经安装且可达，就不要重装，只接这一个平台的原生投递面和 MCP；如果没装，再安装并启动 Time Library。

然后把 Time Library 安装成这个 agent 的长期记忆规则，不只是一次性安装说明。如果这个平台支持 skill 或自定义指令，请添加 Time Library skill/指令；如果这个平台支持 MCP，请注册名为 time-library 的 MCP 工具，地址是 http://127.0.0.1:9851/mcp。如果这个平台是 Claude Code，再安装 `UserPromptSubmit` hook，把 prompt preflight 接到本机 Time Library；这个 hook 在 9851 不可达时必须静默软失败，不能刷屏、不能卡 prompt。

安装完成后，只做一次安全能力检查：
{"query":"capability check","mode":"capability_check"}
先不要召回我的真实记忆。

以后请持续遵守这条规则。凡是我的问题依赖旧上下文，请先调用 time_library_recall，默认结合 source_refs 回答；只有我明确需要原文证据时，才请求 raw_excerpt。触发词包括：之前、定论、纠错、边界、忘了、安装/测试/发布状态，以及持续项目里的“下一步/接下来呢/还有吗/然后呢”。默认使用 active 召回：当前窗口/session 优先，然后同项目/同工作区、同工作流/同任务、稳定偏好/工具事实。只有我明确要求更宽视图时，才使用共享或全局记忆。如果显式 window-only 召回提示当前窗口/session 还没绑定，请直接说明这个绑定缺口；不要说没有记忆。如果 skill 已安装但 time_library_recall 不可用，请告诉我 MCP/工具连接还没接上，不要凭印象猜。`zhiyi_recall` 只能作为迁移期兼容别名，不要当主指令。
```

## First Run

1. Start the local service.
2. Open `http://127.0.0.1:9850`.
3. Let Time Library find local AI tools and connect usable local entries.
4. Run capability check before real recall.
5. Use real recall when the current question depends on prior context.

Install once, then it keeps looking for usable local AI tools. Conversation import uses verified local formats, so memory can stay tied to source records.

## What To Check Next

- [Desktop Companion And Live Sync](Desktop-Companion-And-Live-Sync.md): make sure the watcher keeps running and missed records can be caught up.
- [Local Tool Recognition](Local-Tool-Recognition.md): see how Time Library identifies local AI tools and when the main model can help.
- [AI Tool Boundaries](AI-Tool-Boundaries.md): understand why different tools and windows keep their source trails.
