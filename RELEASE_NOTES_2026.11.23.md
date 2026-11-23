# Time Library 2026.11.23 — a rebuild

<p align="center">
  <img src="https://raw.githubusercontent.com/strmforge/time-library/main/assets/brand/time-library-logo-en.png" alt="Time Library" width="200"/>
</p>

Time Library has been rebuilt from the ground up. The aim is the same — one
memory for all your agents, every memory resting on the original words — but
the architecture, the code, the install and the admin are new. It now runs as
**one server on your NAS** (Docker) and **a small client on each computer**,
instead of a full set of services on every computer, and every agent on every
computer shares that one memory. Why it was rebuilt, and what changed, is in
[A rebuild](https://github.com/strmforge/time-library#a-rebuild).

## Read this first if you use 2026.9.11 or earlier

This is a different architecture. Earlier versions cannot install it with their
own update button, on purpose: applied over an earlier install it would break
it. Those from 2026.7.11 on may show that a new version exists, but the update
installs nothing. Move each computer over instead — see
[Moving from an earlier version](https://github.com/strmforge/time-library#moving-from-an-earlier-version).
The client's `old-install` commands bring the history the earlier version kept,
stop its services, keep a checked copy, and only then remove it. Earlier
releases stay on this page if you need to go back.

## What's in it

- **Server** (`ghcr.io/strmforge/time-library-server:2026.11.23`): stores the
  dialogue, distills it every night into memories that quote their original
  words (each quote checked character for character), organises them (the same
  thing said twice folded together, newer statements superseding older ones,
  experience cards per project, every step undoable), answers recall by words
  and by meaning, and has a web admin on port 9850.
- **Client, with its own Python**: one `curl | tar` (Windows: its own
  `curl.exe` and `tar.exe`) installs the client together with Python 3.14 in
  its own folder. It reads each agent's session files, keeps only the
  dialogue, masks credentials, uploads, and keeps itself at the server's
  version. If the NAS gets a new address, it finds it again on your network.
- **Agents describe themselves.** No per-product code: an agent describes its
  own session files in a small JSON description, tries it on its own files
  with `tl.py check`, and reports it. Prompt hooks of any shape are described
  the same way (`--hook-json`), so no agent needs a script of its own.
  Formats covered by the description: JSON lines, zstd-compressed files, one
  JSON document per session, SQLite databases.
- **For agents** (MCP): `time_library_recall`, `time_library_source`,
  `time_library_answer` (one answer from memory with what it rests on, or
  UNKNOWN), `time_library_catalog` and `time_library_declare` (a project's
  catalog, shown when a window opens), `time_library_whiteboard` (work in
  flight, handed from agent to agent), `time_library_return` (judge a memory:
  useful, useless, misleading). A prompt hook hands memories over only when
  they are clearly about the prompt.
- **Telling voices apart**: what the user said, what an assistant relayed, and
  what the user pasted in (another AI's report, an article) are kept apart; a
  preference resting only on someone else's words is marked as such.
- **Proof**: a nightly checkup and a memory on/off comparison; each memory's
  history.
- **Models per task** with backups (history import, nightly distillation, deep
  summary); OpenAI Responses, Anthropic Messages and chat/completions; a
  built-in local model (Qwen3-4B on llama.cpp); meaning-based recall with small
  local models (hs-embed-1, hs-rerank-1) when switched on.
- **History import**: held until you choose a range and start it, with the
  expected token use shown first.

## Not in this version

The server image is for x86-64 (Intel/AMD) machines; there is no ARM image yet.
The Hermes skill-and-experience loop is not planned. The server is meant for
your home network; do not expose it to the internet as it is.

## 中文

时间图书馆（忆凡尘）这一版是**重构**：目标没变——所有 agent 共用一份记忆，每条记忆都以原话为凭——
架构、代码、安装方式、后台全部重做。现在是 **NAS 上一个服务端**（Docker）加**每台电脑一个轻客户端**，
所有电脑上的所有 agent 共用同一份记忆。为什么重做、改了什么，见 README 的
[这是一次重构](https://github.com/strmforge/time-library/blob/main/README.zh-CN.md#这是一次重构)。

- **服务端**（`ghcr.io/strmforge/time-library-server:2026.11.23`）：保存对话，每晚提炼成带原话的记忆（引文逐字核对），
  整理（重复的并起来、新说法取代旧的、每个项目归纳成经验卡，每步可撤销），按字词也按意思召回，9850 端口有中英双语网页后台。
- **客户端，自带 Python**：一条 `curl | tar`（Windows 用自带的 `curl.exe`、`tar.exe`）连同 Python 3.14 装进客户端自己的文件夹；
  只留对话、密钥打码后上传，自己跟着服务端升级；NAS 换了地址会在家里局域网里自己找回来。
- **agent 自己描述自己**：没有为任何产品写的代码。agent 用一份小 JSON 描述自己的会话文件，用 `tl.py check` 在自己的文件上试对了再报上来；
  提问前钩子也同样描述（`--hook-json`）。支持 JSON lines、zstd 压缩、每个会话一个 JSON 文件、SQLite。
- **给 agent 的工具**（MCP）：召回、看原话前后文、只凭记忆作答（不知道就答 UNKNOWN）、项目书单、白板、借还评价。
- **分得清是谁说的**：用户原话、助手转述、用户贴进来的别人的话（别的 AI 的报告、文章）分开记。
- **模型按任务选**，可加备用；原生 Responses、Messages，chat/completions 兜底；自带本机模型。
- **历史导入**：先扣着，选好范围、看过预计用量再开始。

**从 2026.9.11 或更早升级**：旧版自己的"一键更新"装不上本版，这是有意的（直接覆盖会弄坏旧安装）；2026.7.11 起的旧版可能会提示有新版本，但更新什么都不会装。请按
[从旧版迁移](https://github.com/strmforge/time-library/blob/main/README.zh-CN.md#从旧版迁移)
一台一台迁过来；旧版本一直留在发布页，需要时可以回退。

**这一版没有的**：服务端镜像只有 x86-64（Intel / AMD），还没有 ARM 版。Hermes 的 skill 与经验升级环不再做（Hermes 的对话照常收）。服务端为家里局域网设计，不要原样暴露到公网。
