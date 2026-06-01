# Memcore Cloud

<p align="center">
  <img src="assets/brand/yifanchen-logo.jpg" alt="Memcore Cloud" width="220"/>
</p>

<p align="center">
  <strong>Local-first, source-backed memory for AI agents.</strong>
</p>

<p align="center">
  Give Claude Desktop, Codex, OpenClaw, Hermes, and other local AI tools a shared memory layer without replacing original records with summaries.
</p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.6.1">2026.6.1</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.6.1-2f5f9b">
  <img alt="Platforms" src="https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-ready-247447">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-memory-b07d35">
</p>

Memcore Cloud is the English product name. **忆凡尘 / Yifanchen** remains the Chinese name and codename.

## What You Get

- Your AI tools can stop starting from zero every time you open a new window.
- Original conversations stay on your machine, with source trails you can check later.
- Preferences, corrections, project habits, and repeated work paths can become reusable memory.
- Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and newer local agents can be discovered from the machine they already run on.
- A local agent can install the skill and wire the MCP connection for you; the first check can prove the connection works without recalling real memory.

## Copy This To Your Local Agent

If you use Codex, Claude Code CLI, OpenClaw, Hermes, or another local agent that can run terminal commands, copy either prompt below to it. The agent can install the workflow skill, and the installer will register the `yifanchen-zhiyi` MCP connection where the platform supports MCP.

```text
Please install Memcore Cloud (Yifanchen) from https://github.com/strmforge/memcore-cloud on this machine.
After installation, start the local services. Automatically install the Codex skill. If Codex CLI is available, automatically register the Codex MCP server named yifanchen-zhiyi at http://127.0.0.1:9851/mcp.
If OpenClaw, Hermes, or Claude Desktop is available, use the installer defaults to connect them too; Claude Desktop needs the local MCP bridge registration before it can actually query Memcore Cloud.
Finish with capability check mode only; do not recall my real memory.
```

中文可复制版本：

```text
请帮我在本机安装 Memcore Cloud（忆凡尘 / Yifanchen），仓库是 https://github.com/strmforge/memcore-cloud 。
安装完成后请启动本机服务；请自动安装 Codex skill；如果检测到 Codex CLI，请自动把 Codex MCP 接到 http://127.0.0.1:9851/mcp，MCP 名称用 yifanchen-zhiyi。
如果检测到 OpenClaw、Hermes 或 Claude Desktop，也请按安装器默认方式接入；Claude Desktop 需要注册本机 MCP bridge 才能真正查询忆凡尘。
最后只做 capability check，不要召回我的真实记忆。
```

The installer tries to install the workflow skill where the client supports skills, then registers the `yifanchen-zhiyi` MCP connection where the platform can use MCP. Skill installation is an intent signal; real recall still goes through the local MCP tool, and chat-body parsing stays behind a separate authorization gate.

## Why It Exists

AI coding and agent tools still forget too easily. You explain a preference in Claude Desktop, debug a project in Codex, test a workflow in OpenClaw, and the next window starts from zero.

Memcore Cloud keeps the useful trail on your own machine: original conversations, source refs, corrections, work experience, and platform facts. It helps the tools you already use pick up the thread, while keeping platform boundaries visible instead of flattening every agent into one blob.

## Quick Install

macOS / Linux / WSL:

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

After install, use `mode=capability_check` to verify the skill/MCP/read-only path without recalling real memory.

## Safe Test Checklist

Start with capability check mode. A successful first test should report `read_only: true`, `recall_performed: false`, `raw_excerpt_returned: false`, and `mcp_tools: ["zhiyi_recall"]`.

Then open `http://127.0.0.1:9850` and check whether your local tools are detected. Memcore Cloud can show what it sees locally, which tools already have a usable connection, and which ones need one more authorization step. This check does not write platform config, parse chat bodies, or recall real memory.

## 查看它发现了什么

本地页面会告诉你：这台机器上有哪些 AI 工具，哪些已经可以做安全能力检查，哪些还差一次授权接入。

Claude Desktop 和 Claude Code CLI 会分开看待，不会混读。Codex、OpenClaw、Hermes、Cursor 类工具，以及更新的本机 agent，也可以从它们原本保存本机设置的位置被识别出来。发现某个工具，只代表“看见了入口”，不代表读取聊天正文。

真正接入前，忆凡尘会先告诉你准备改哪里、是否需要重启、怎么撤回、接好后怎样做只读能力检查。只有你明确决定测试记忆召回之后，才进入真实 recall。安装 Skill、发现某个平台、看到 Claude Desktop 本地存储，都不等于授权读取聊天正文。

## 安全测试清单

先跑 capability check。第一步成功时，应该看到 `read_only: true`、`recall_performed: false`、`raw_excerpt_returned: false`，以及 `mcp_tools: ["zhiyi_recall"]`。

然后打开 `http://127.0.0.1:9850` 看本机工具是否被发现。忆凡尘会告诉你本机有哪些 AI 工具、哪些已经可以安全检查、哪些还差一次授权接入。这个过程不会写平台配置、不会解析聊天正文、不会召回真实记忆。

Claude Desktop 和 Claude Code CLI 会分开看待，不会混读。Codex、OpenClaw、Hermes、Cursor 类工具，以及更新的本机 agent，也可以从它们原本保存本机设置的位置被识别出来。发现某个工具，只代表“看见了入口”，不代表读取聊天正文。

真正接入前，忆凡尘会先告诉你准备改哪里、是否需要重启、怎么撤回、接好后怎样做只读能力检查。只有你明确决定测试记忆召回之后，才进入真实 recall。安装 Skill、发现某个平台、看到 Claude Desktop 本地存储，都不等于授权读取聊天正文。

## What Makes It Different

- **It keeps the receipts**: original saved records stay as the highest fact; summaries do not replace source text.
- **It can explain why it remembered something**: recall keeps the reason trail visible.
- **It meets tools where they are**: Claude Desktop, Claude Code CLI, Codex, OpenClaw, Hermes, Cursor-style tools, and newer local agents can sit around the same memory core without getting mixed together.
- **It asks before crossing lines**: discovery is read-only by default. Installing a skill can signal intent, but writing platform config or reading chat bodies needs explicit authorization.
- **It separates knowing from doing**: Zhiyi captures preference and intent; Xingce captures work experience and validation paths. Experience is not a skill library.

## Chinese Introduction

## 人间会忘，忆凡尘会记得

人和 AI 的对话，常常像一天里擦肩而过的话。

今天说清楚了一个想法，明天又要重新解释；这台电脑懂了，换一个入口又像从头认识。真正有用的，不只是那一轮回答，而是你一路说过的话、做过的选择、留下的偏好、踩过的坑。

忆凡尘做的事很朴素：把这些人间的细节留在本机。你继续在 OpenClaw、Hermes、Codex、Claude Desktop 等工具里正常聊天，它在旁边安静记下原始对话，整理成可回看的经验。你感觉到的，不应该是多了一个复杂东西，而是原来的工具更顺手了，更像认识你了。

## 它能做什么

- **原样保存**：各平台原始记录、知意经验、召回上下文和使用记录按已保存内容保留；不脱敏、不改写、不替换成摘要或哈希。

  > 忆凡尘的判断很简单：你说过的话本身就是最高事实。整理可以发生，召回可以发生，知意和行策也可以从中长出经验；但任何替代原文的压缩，都是污染。半年后回头看，原话还应该在那里。
- **知意整理**：从记录里提炼用户喜好、表达习惯、纠偏和常见问题，形成可以反复使用的偏好与意图经验。
- **行策沉淀**：从做事、失败、纠偏和验收里长出下一次可参考的做法。
  行策主要保存工作经验，不是技能库。比如某个项目历史上为什么不能动某个改法、排障先查哪条链路、一次失败后下次怎么验收，这些没有标准输入输出，但会影响下一次怎么做。
- **自然接入**：OpenClaw、Hermes、Codex、Claude Desktop 继续用原来的入口，忆凡尘在后台提供记忆。
- **Hermes 原始记忆供给**：Hermes native review 被触发时，可以读取忆凡尘开放的 raw/source_refs 路径指针，必要时再由 Hermes 自己去看原始资料；忆凡尘负责发出 self-review signal、观察 native feedback，不直接替 Hermes 写 skill。
  2026.5.31 起，self-review signal 有 wake dry-run 和授权 receipt gate，可记录“已产生信号”，但这仍不等于 Hermes 已执行 `background_review` 或生成 skill。
- **Claude Desktop 一等公民**：Claude Desktop 和 Claude Code CLI 分开识别。Claude Desktop 可以通过本机 MCP / Desktop Extension 消费忆凡尘；只装通用 Skill 只是信号，不等于能调用本机记忆。作为来源侧，忆凡尘先做本机用户态同步清单和 sync-state receipt，持续跟踪配置、IndexedDB、Local Storage、Session Storage、Skill manifest 和日志等对象的变化。读取和页面展示可以按 `claude_all` 聚合全部 Claude 入口；但 Windows 上如果 Claude 通过中转服务或 Claude Code 运行时产生记录，source_refs 会保留双归属和隔离边界：`storage_owner`、`conversation_origin`、`runtime_consumer` 分开写，且不表示官方登录聊天和中转聊天互通。官方导出包只作为冷启动或补档 fallback，不是日常同步主链路；内容解析需要单独授权的 parser gate。
- **增量读取**：对还在增长的本机会话文件，从上次位置继续读取，减少重复扫描。
- **本地页面**：打开 `http://127.0.0.1:9850`，查看接入状态、模型选择和新生成的经验。
- **三端可用**：支持 macOS、Linux、Windows，也支持 WSL 环境。

## Current Release: 2026.6.1

2026.6.1 is the current published release of Memcore Cloud.

- **Natural-language correction entry**: user corrections such as "this memory is wrong" become review-only errata candidates instead of durable preference memories.
- **Agent install loop**: the README now exposes the local-agent install prompt near the top; installers try to connect Codex skill, Codex MCP, OpenClaw, Hermes, and the Claude Desktop MCP bridge automatically.
- **Local tool discovery**: Memcore Cloud can show the AI tools already present on the machine, which ones are ready to check, and which ones need one more authorization step.
- **Computer-first raw archive contract**: starting with 2026.6.1, new installs and new raw writes use `memory/{computer_name}/{source_system}/{native_artifact_format}/...`. Older source-system-first archives stay readable, but the legacy layout is no longer created for new records.
- **Hermes status visibility**: adds learning liveness, consumption receipts, and skill-experience diff. Memcore Cloud provides raw/source-ref pointers and observes native feedback; it does not write Hermes skills directly.
- **Claude Desktop source registration**: adds Claude Desktop source-system detection, consumer-side readiness diagnostics, a local sync manifest, and sync-state receipts. Readers can aggregate under `claude_all`, while source refs keep Windows relay / Claude Code dual attribution and isolation boundaries.
- **State Ledger and Context Budget Units**: review-only checks help later sessions find the latest trusted judgment and carry compact, source-backed context forward.
- **Read-only model facts**: Memcore Cloud reads existing OpenClaw, Hermes, and Codex model configuration for its own checks. It does not write back to platforms or become a model center.

See [RELEASE_NOTES_2026.6.1.md](RELEASE_NOTES_2026.6.1.md) for the current release, [UPDATE_HISTORY.md](UPDATE_HISTORY.md) for historical highlights, and [CHANGELOG.md](CHANGELOG.md) for engineering changes.

## 知意是什么

知意是忆凡尘里最靠近人的一层。

它不是搜索框，也不是把聊天压成几句摘要。它更像一个安静的整理者：从你反复说过的话里看见真正的意思，记住偏好、背景、案例和纠偏，让这些经验在下次需要时还能回来。

比如你多次强调“不要让我去另一个页面查，我希望原来的 AI 工具自然变聪明”，知意应该记住的不是这句话本身，而是背后的使用偏好：服务要安静、顺手、少打扰。

所以忆凡尘的页面不应该成为新的工作负担。日常你仍然在 OpenClaw、Hermes、Codex、Claude Desktop 里聊天；偶尔打开本地页面时，重点看的是有没有新的经验、这些经验是否准确、是否需要删除或保留。

需要在新窗口接上前文时，可以用 `/zhiyi` 开头；英文环境也可以用 `/memory`、`/recall`、`/continue`，或直接说 `catch me up`。这些只是入口意图，不会改变原始记录的保存方式。

## 行策是什么

知意是机器先知你意：知道你是谁、怎么想、以前怎么纠偏、这件事做到哪里。

行策是机器开始会行事：从一次次做事、失败、纠偏和验收里沉淀经验，知道下次怎么推进、怎么避坑、怎么接手。

知意现在更接近一个本地档案员：它主要沉淀用户喜好、表达习惯、关系偏好、纠偏和意图线索。每条经验会带馆藏号、状态和来源线索，方便回到原话出处，而不是只给一段没有来路的摘要。

行策则是工作经验层。它不替用户做最后决定，也不把经验写成空话；它把已经做过的事、踩过的坑、验证过的步骤、项目里的历史边界，整理成下一步能执行、能回看、能对照原话的路径。

这里要和 Skill 分开。Skill 是给 AI 工具的入口规矩和工作流，告诉它什么时候调取知意、怎样带来源回答；经验不是可调用函数，经验本身不是 `f(input) -> output`。知意保存“用户怎么想、偏好什么、以前怎么纠偏”，行策保存“这类工作下次怎么做、先查什么、哪些坑别再踩”。如果某个人的偏好会影响工作推进，偏好本身仍归知意；行策只在具体工作路径里引用它，不把偏好改名成行策。

知意负责看见，行策负责落地，合起来就是知行合一。第一版先把能看见、能回源、能继续积累的经验做好，再让这些经验进入各个平台的做事过程。

更口语的一句：**知行合一，机器飞升。**

## 知行图书馆

知行图书馆是知意和行策的共同馆藏层。

原始记忆是底本，永远不被知意或行策替代。知意更像理解类馆藏，保存用户喜好、表达习惯、纠偏、意图和背景；行策是工作经验和工具书，保存做事路径、项目边界、排障顺序、踩坑记录和验收方法。

每条馆藏都应该能回答几个问题：它的馆藏号是什么，来自哪段原话，属于哪个书架，现在是候选还是已采用，有没有冲突或被替代，什么时候最后验证过，适用范围和禁用条件是什么。工具书也一样不能凭空出现：外部文档和平台探测日志要先进入 `raw/external_docs/` 或 `raw/probe_logs/`，再长成工具书馆藏。

例如一条平台探测事实：“某工具的 profile 配置会被立即读取，而大小写敏感系统只识别官方大写文件名”，应该先保存对应命令输出或官方文档片段，再生成工具书候选。这样它是可回看的平台事实，不是模型凭印象写出的结论。

所以忆凡尘接下来不是只追求“召回一段看似聪明的总结”，而是追求：知意可回源，行策可验收，召回可解释，效果可回放。知行闭环按 7 步流转：原样保存、知意回源、行策沉淀、工具书补事实、勘误处理冲突、Replay 验证、反哺召回或行动。回放评分优先走确定性规则：预期来源、预期行为、禁踩旧坑、必要验收项，以及能否主动浮现用户忘了但过去做对过的东西，而不是让模型自己夸自己。当前反哺先生成 adoption / errata / proactive resurfacing 候选；授权 apply 只写审阅收据，不自动写正式经验。

工具书候选入口先只做审阅候选：平台事实、环境差异、命令实测、原话片段可以先变成候选，但不会悄悄写进正式馆藏。

2026.5.31 起，状态账本和上下文最小单元也遵守同一条规则：帮助后续会话找到“最新可信判断”，把必要上下文压成可回源的小块，但是否采用仍然要经过审阅。

## 给 AI 工具使用知意

支持 Skill、MCP 或自定义系统提示的 AI 工具，可以使用仓库里的通用知意技能：

```text
system/skills/yifanchen-zhiyi
```

Skill 负责告诉 AI 什么时候调取知意、怎样按来源回答；MCP 或平台插件负责连接本机忆凡尘服务。它不是 Codex 专属，也不是把忆凡尘降级成技能库；真正沉淀用户喜好和工作经验的是知意与行策背后的经验层。

安装或冒烟测试时，不要用 `/zhiyi` 当能力检查命令；它可能会真的召回本机记忆。请让客户端调用 `zhiyi_recall` 时带上：

```json
{"query":"capability check","mode":"capability_check"}
```

这个模式只报告服务、工具、版本和只读状态，不查询记忆、不返回 source refs 或原文摘录。

## 安装

### 让你的 AI agent 帮你安装

如果你正在使用 Codex、OpenClaw、Hermes、Claude Code CLI 或其他能操作本机终端的 AI agent，可以直接把下面这段话发给它：

```text
请帮我在本机安装 Memcore Cloud（忆凡尘 / Yifanchen），仓库是 https://github.com/strmforge/memcore-cloud 。
安装完成后请启动本机服务；请自动安装 Codex skill；如果检测到 Codex CLI，请自动把 Codex MCP 接到 http://127.0.0.1:9851/mcp，MCP 名称用 yifanchen-zhiyi。
如果检测到 OpenClaw、Hermes 或 Claude Desktop，也请按安装器默认方式接入；Claude Desktop 需要注册本机 MCP bridge 才能真正查询 Memcore Cloud。
最后只做 capability check，不要召回我的真实记忆。
```

安装器会尽量自动完成本机接入：OpenClaw 插件、Hermes provider、Codex skill、Codex MCP、Claude Desktop MCP bridge 都会按平台能力接好，用户不需要先理解 Skill 或 MCP。Codex skill 会给新开的 Codex 会话一个明确锚点：忆凡尘是一座本机记忆图书馆；Codex/Claude Desktop MCP 注册成功后，新会话可以看到 `yifanchen-zhiyi` / `zhiyi_recall`；已经打开的会话可能需要重开后才会加载新连接。

### macOS / Linux / WSL

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

安装后打开：

```text
http://127.0.0.1:9850
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

首次运行会询问安装位置。直接回车即可使用推荐位置。

## 更新

已经安装过的用户，优先用本地页面更新：

1. 打开 `http://127.0.0.1:9850`。
2. 进入“设置与更新”。
3. 点击“检查更新”。
4. 如果发现新版本，点击“一键更新”。

一键更新会先备份程序文件，再替换新版本；`memory/`、`raw/`、`zhiyi/`、`config/`、`logs/`、`backups/` 等本地数据会保留。

如果本地页面打不开，可以重新运行安装命令做修复安装：

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows：

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

## 卸载

### macOS / Linux

```bash
~/.memcore-cloud/uninstall.sh
```

### Windows

```powershell
.\uninstall.ps1
```

卸载只移除软件本体，`memory/`、`raw/`、`zhiyi/`、`config/` 等本地数据会保留。

## Supported Sources

- **OpenClaw**：从常用聊天入口获得记忆辅助。
- **Hermes**：在本机可用时读取忆凡尘提供的本地记忆；Hermes native review 触发并产生 skill/learning 变化时，忆凡尘可以观察变化并生成待审升级输入。
- **Codex**：读取本机 Codex 会话记录，整理成可回源经验。
- **Claude Desktop**：作为消费端可通过本机 MCP / Desktop Extension 使用知意；作为来源端会列入同步清单和 sync-state receipt，优先做本机用户态同步。读取层可按 `claude_all` 聚合，Windows 中转/Claude Code 相关记录保留双归属字段和隔离边界；官方导出包只作冷启动或补档 fallback。
- **Skill / MCP 客户端**：通过通用知意规则和只读召回入口接入。
- **本地文件**：保留基础的本地记录读取能力。

## Documentation

- [为什么叫忆凡尘](INTRODUCTION.md)
- [Wiki](https://github.com/strmforge/memcore-cloud/wiki)
- [第一次使用](https://github.com/strmforge/memcore-cloud/wiki/%E7%AC%AC%E4%B8%80%E6%AC%A1%E4%BD%BF%E7%94%A8)
- [知意](https://github.com/strmforge/memcore-cloud/wiki/%E7%9F%A5%E6%84%8F)
- [行策](https://github.com/strmforge/memcore-cloud/wiki/%E8%A1%8C%E7%AD%96)
- [历史更新](UPDATE_HISTORY.md)

## Version

Current release: **2026.6.1**

See [RELEASE_NOTES_2026.6.1.md](RELEASE_NOTES_2026.6.1.md) for the latest published release, [UPDATE_HISTORY.md](UPDATE_HISTORY.md) for historical highlights, and [CHANGELOG.md](CHANGELOG.md) for engineering changes.

## License

[MIT](LICENSE)
