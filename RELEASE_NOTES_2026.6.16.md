# Memcore Cloud 2026.6.16

Memcore Cloud 2026.6.16 focuses on making the local AI memory library easier to
connect, inspect, and trust. It fixes the local AI "finished the chat, lost the
context" problem by keeping original records, preferences, project boundaries,
proven work paths, and borrowing receipts on the user's own machine.

## Highlights

- **Local AI memory library**: original records remain the archive, library ids
  make memories findable, and usage receipts show what an agent borrowed before
  it answered.
- **Source-backed recall**: recall can return compact source refs, rank reasons,
  and bounded original excerpts when explicitly requested.
- **Pre-work context checks**: before coding, installing, syncing, or
  troubleshooting, an agent can check whether the work looks already built,
  miswired, missing diagnostics, or truly missing.
- **Zhiyi and Xingce stay distinct**: Zhiyi keeps preferences, corrections,
  habits, and boundaries; Xingce keeps repair paths, validation steps, and work
  methods.
- **Experience reaches local agents**: skill-, instruction-, and MCP-capable
  local agents can read the same Xingce guidance before work instead of keeping
  separate private experience stores.
- **Traceable experience evolution**: successful fixes, mistakes, and user
  corrections can become candidates. Source-backed candidates with original
  evidence and acceptance checks can be adopted, upgraded, rejected, or rolled
  back with receipts.
- **Record Doctor**: a safe read-only check shows whether source records, raw
  mirrors, the canonical index, and memory/experience links are guarded before
  real recall is tested.
- **Quieter first response**: capability check remains read-only and no-recall;
  real memory is only retrieved when an agent calls recall.
- **Installer entry points**: macOS, Linux, and Windows installers use the
  2026.6.16 release tag and keep local data such as `memory/`, `raw/`, `zhiyi/`,
  and `config/` separate from app files.

## 中文

Memcore Cloud 2026.6.16 的重点，是让“忆凡尘这座本机 AI 记忆图书馆”更容易接入、检查和信任。它解决本机 AI “聊完就散、换窗就忘、做过还重做”的硬伤：原始记录仍然是最高事实；召回要能回源；有用的工作经验必须经过证据和验收，才能变成下一次可复用的行策。

### 主要更新

- **本机 AI 记忆图书馆**：原始记录是馆藏原件，馆藏号负责定位，借阅记录说明 agent 回答前用了哪些记忆。
- **可回源召回**：召回可以返回精简来源线索、命中理由，并在明确需要时给出有界原文摘录。
- **开工前上下文检查**：写代码、安装、同步、排障前，agent 可以先判断这件事更像已经做过、接线错了、缺诊断，还是确实缺功能。
- **知意和行策分开**：知意保存偏好、纠正、习惯和边界；行策保存修复路径、验证步骤和工作方法。
- **经验可以接给本机 agent**：支持 skill、自定义指令或 MCP 的本机 agent，都可以在动手前读取同一套行策经验，而不是各自攒一套私有经验。
- **经验可追踪进化**：做成、踩坑、纠错都可以先成为候选；带得回来源、原文和验收条件的候选，才能被采纳、升级、拒绝或回滚，并留下回执。
- **记录医生**：真实召回前，可以先用只读自检确认源记录、raw 镜像、canonical index 和记忆/经验链路是否守住。
- **更安全的第一次测试**：capability check 仍然只读、无真实召回；只有 agent 明确调用 recall，才读取真实记忆。
- **安装入口对齐**：macOS、Linux、Windows 安装器使用 2026.6.16 release tag，并把 `memory/`、`raw/`、`zhiyi/`、`config/` 等本地数据和软件文件分开。

## Boundaries

- Summaries help navigation, but they do not replace original records.
- Experience is not a skill marketplace and Xingce is not a callable function
  library.
- Experience evolves, but it stays source-backed, reviewable, and reversible.
- Local data stays on the user's machine by default.
