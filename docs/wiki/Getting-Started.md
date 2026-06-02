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
Please install Memcore Cloud from https://github.com/strmforge/memcore-cloud on this machine.
After installation, start the local service. Install the Memcore Cloud Zhiyi skill wherever this agent supports skills or custom instructions, and register the yifanchen-zhiyi MCP endpoint at http://127.0.0.1:9851/mcp wherever MCP is supported.
After setup, run capability check only with zhiyi_recall using {"query":"capability check","mode":"capability_check"}; do not recall my real memory yet.
From then on, before answering anything about previous decisions, corrections, project boundaries, forgotten context, install/test/release status, or "what next" in an ongoing project, call zhiyi_recall first and use source refs or raw excerpts when available.
```

Chinese prompt:

```text
请帮我在本机安装 Memcore Cloud（忆凡尘），仓库是 https://github.com/strmforge/memcore-cloud 。
安装后启动本机服务；在支持 skill 或自定义指令的平台安装 Memcore Cloud Zhiyi skill；在支持 MCP 的平台注册 yifanchen-zhiyi，地址 http://127.0.0.1:9851/mcp。
安装完成后只用 zhiyi_recall 做 capability check：{"query":"capability check","mode":"capability_check"}，先不要召回我的真实记忆。
以后我问到之前的决定、纠错、项目边界、你忘了什么、安装/测试/发布状态，或者在持续项目里问“下一步”，请先调用 zhiyi_recall，再结合 source_refs / raw_excerpt 回答。
```

## First Run

1. Start the local service.
2. Open `http://127.0.0.1:9850`.
3. Run capability check before real recall.
4. Only run real recall after you choose to test memory retrieval.

Installing a skill is a connection signal. It is not permission to read chat bodies.
