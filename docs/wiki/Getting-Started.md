# Getting Started

## Install

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

WSL is only for development or advanced testing. Normal Windows installs should
use the Windows PowerShell command above.

Then open:

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

Keep this rule active from now on. When my question depends on prior context, call zhiyi_recall before answering and use source refs or raw excerpts when available. Triggers include previous decisions, corrections, project boundaries, forgotten context, install/test/release status, and short follow-ups in ongoing work such as "next step", "what else", or "then what". If the skill is installed but zhiyi_recall is not available, tell me the MCP/tool connection is missing instead of guessing from memory.
```

Chinese prompt:

```text
你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）。
仓库：https://github.com/strmforge/memcore-cloud

请安装并启动 Memcore Cloud。然后把 Memcore Cloud Zhiyi 安装成这个 agent 的长期记忆规则，不只是一次性安装说明。如果这个平台支持 skill 或自定义指令，请添加 Memcore Cloud Zhiyi skill/指令；如果这个平台支持 MCP，请注册名为 yifanchen-zhiyi 的 MCP 工具，地址是 http://127.0.0.1:9851/mcp。

安装完成后，只做一次安全能力检查：
{"query":"capability check","mode":"capability_check"}
先不要召回我的真实记忆。

以后请持续遵守这条规则。凡是我的问题依赖旧上下文，请先调用 zhiyi_recall，再结合 source_refs / raw_excerpt 回答。触发词包括：之前、定论、纠错、边界、忘了、安装/测试/发布状态，以及持续项目里的“下一步/接下来呢/还有吗/然后呢”。如果 skill 已安装但 zhiyi_recall 不可用，请告诉我 MCP/工具连接还没接上，不要凭印象猜。
```

## First Run

1. Start the local service.
2. Open `http://127.0.0.1:9850`.
3. Let Memcore Cloud find local AI tools and connect supported Skill/MCP surfaces.
4. Run capability check before real recall.
5. Use real recall when the current question depends on prior context.

Install once, then it keeps looking for usable local AI tools. Conversation import uses verified local formats, so memory can stay tied to source records.
