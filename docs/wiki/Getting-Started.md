# Getting Started

## Install

macOS / Linux / WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

Then open:

```text
http://127.0.0.1:9850
```

## Paste This To Your Local Agent

If you use a local AI agent that can run terminal commands, paste this:

```text
You are installing Memcore Cloud for me on this machine.
Repository: https://github.com/strmforge/memcore-cloud

Install and start Memcore Cloud. Then install the Memcore Cloud Zhiyi skill or custom instruction in this agent if the platform supports skills, and register the MCP tool named yifanchen-zhiyi at http://127.0.0.1:9851/mcp if the platform supports MCP.

After setup, run only a safe capability check with zhiyi_recall:
{"query":"capability check","mode":"capability_check"}
Do not recall my real memory yet; do not recall my real memory until I ask.

From then on, treat Memcore Cloud as my local memory. Before answering anything about previous decisions, corrections, project boundaries, forgotten context, install/test/release status, or "what next" in an ongoing project, call zhiyi_recall first and use source refs or raw excerpts when available. If the skill is installed but zhiyi_recall is not available, tell me the MCP/tool connection is missing instead of guessing from memory.
```

Chinese prompt:

```text
你正在帮我在这台机器安装 Memcore Cloud（忆凡尘）。
仓库：https://github.com/strmforge/memcore-cloud

请安装并启动 Memcore Cloud。然后，如果这个平台支持 skill 或自定义指令，请安装 Memcore Cloud Zhiyi skill；如果这个平台支持 MCP，请注册名为 yifanchen-zhiyi 的 MCP 工具，地址是 http://127.0.0.1:9851/mcp。

安装完成后，只做一次安全能力检查：
{"query":"capability check","mode":"capability_check"}
先不要召回我的真实记忆。

以后请把 Memcore Cloud 当成我的本机记忆。凡是我问到之前的决定、纠错、项目边界、你忘了什么、安装/测试/发布状态，或者在持续项目里问“下一步/接下来呢/还有吗”，请先调用 zhiyi_recall，再结合 source_refs / raw_excerpt 回答。如果 skill 已安装但 zhiyi_recall 不可用，请告诉我 MCP/工具连接还没接上，不要凭印象猜。
```

## First Run

1. Start the local service.
2. Open `http://127.0.0.1:9850`.
3. Run capability check before real recall.
4. Only run real recall after you choose to test memory retrieval.

Installing a skill is a connection signal. It is not permission to read chat bodies.
