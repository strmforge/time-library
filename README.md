# 忆凡尘

<p align="center">
  <img src="assets/brand/yifanchen-logo.jpg" alt="忆凡尘" width="220"/>
</p>

<p align="center">
  <strong>把人间说过的话，留在自己身边。</strong>
</p>

<p align="center">
  本地个人 AI 记忆中心。原样保存对话，安静整理经验，让你常用的 AI 工具慢慢更懂你。
</p>

<p align="center">
  <a href="README.en.md">English</a> ·
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.5.28">2026.5.28</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.5.28-2f5f9b">
  <img alt="Platforms" src="https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-ready-247447">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-memory-b07d35">
</p>

## 人间会忘，忆凡尘会记得

人和 AI 的对话，常常像一天里擦肩而过的话。

今天说清楚了一个想法，明天又要重新解释；这台电脑懂了，换一个入口又像从头认识。真正有用的，不只是那一轮回答，而是你一路说过的话、做过的选择、留下的偏好、踩过的坑。

忆凡尘做的事很朴素：把这些人间的细节留在本机。你继续在 OpenClaw、Hermes、Codex 等工具里正常聊天，它在旁边安静记下原始对话，整理成可回看的经验。你感觉到的，不应该是多了一个复杂东西，而是原来的工具更顺手了，更像认识你了。

## 它能做什么

- **原样保存**：各平台原始记录、知意经验、召回上下文和使用记录按已保存内容保留；不脱敏、不改写、不替换成摘要或哈希。

  > 忆凡尘的判断很简单：你说过的话本身就是最高事实。整理可以发生，召回可以发生，知意和行策也可以从中长出经验；但任何替代原文的压缩，都是污染。半年后回头看，原话还应该在那里。
- **知意整理**：从记录里提炼案例、偏好和常见问题，形成可以反复使用的经验。
- **行策沉淀**：从做事、失败、纠偏和验收里长出下一次可参考的做法。
- **自然接入**：OpenClaw、Hermes、Codex 继续用原来的入口，忆凡尘在后台提供记忆。
- **增量读取**：对还在增长的本机会话文件，从上次位置继续读取，减少重复扫描。
- **本地页面**：打开 `http://127.0.0.1:9850`，查看接入状态、模型选择和新生成的经验。
- **三端可用**：支持 macOS、Linux、Windows，也支持 WSL 环境。

## 2026.5.28 新增

- **Codex 本地接入**：读取本机 Codex 会话记录，进入同一个本地记忆底座。
- **通用知意入口**：新窗口可以用 `/zhiyi` 接上前情；英文环境可用 `/memory`、`/recall`、`/continue` 或 `catch me up`。
- **Skill / MCP 接入**：提供平台中立的 `yifanchen-zhiyi` Skill，以及只读的 `zhiyi_recall` 召回入口。
- **共享记忆底座**：OpenClaw、Hermes、Codex 可以使用同一套本地原始记忆，但各自窗口和 agent 仍分开管理。
- **增量与续读**：正在增长的会话文件从上次位置继续读取，旧记录回源时支持分段补查。
- **来源可回看**：知意经验带馆藏号、状态和来源线索，尽量回到原话出处。
- **行策说明补齐**：行策作为行动经验层，负责把做事过程里的经验沉淀成下一次可参考的路径。
- **本地网关加固**：只读召回网关显式限制本机回环访问，并防止续读状态误写入平台配置目录。

## 知意是什么

知意是忆凡尘里最靠近人的一层。

它不是搜索框，也不是把聊天压成几句摘要。它更像一个安静的整理者：从你反复说过的话里看见真正的意思，记住偏好、背景、案例和纠偏，让这些经验在下次需要时还能回来。

比如你多次强调“不要让我去另一个页面查，我希望原来的 AI 工具自然变聪明”，知意应该记住的不是这句话本身，而是背后的使用偏好：服务要安静、顺手、少打扰。

所以忆凡尘的页面不应该成为新的工作负担。日常你仍然在 OpenClaw、Hermes、Codex 里聊天；偶尔打开本地页面时，重点看的是有没有新的经验、这些经验是否准确、是否需要删除或保留。

需要在新窗口接上前文时，可以用 `/zhiyi` 开头；英文环境也可以用 `/memory`、`/recall`、`/continue`，或直接说 `catch me up`。这些只是入口意图，不会改变原始记录的保存方式。

## 行策是什么

知意是机器先知你意：知道你是谁、怎么想、以前怎么纠偏、这件事做到哪里。

行策是机器开始会行事：从一次次做事、失败、纠偏和验收里沉淀经验，知道下次怎么推进、怎么避坑、怎么接手。

知意现在更接近一个本地档案员：每条经验会带馆藏号、状态和来源线索，方便回到原话出处，而不是只给一段没有来路的摘要。行策则更靠近做事经验，它不替用户做最后决定，也不把经验写成空话；它把已经看清楚的东西整理成下一步能执行、能回看、能对照原话的路径。

知意负责看见，行策负责落地，合起来就是知行合一。第一版先把能看见、能回源、能继续积累的经验做好，再让这些经验进入各个平台的做事过程。

## 给 AI 工具使用知意

支持 Skill、MCP 或自定义系统提示的 AI 工具，可以使用仓库里的通用知意技能：

```text
system/skills/yifanchen-zhiyi
```

Skill 负责告诉 AI 什么时候调取知意、怎样按来源回答；MCP 或平台插件负责连接本机忆凡尘服务。它不是 Codex 专属，也可以给 Hermes、OpenClaw、Claude 或其他本地 Agent 入口使用。

## 安装

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

## 现在支持

- **OpenClaw**：从常用聊天入口获得记忆辅助。
- **Hermes**：在本机可用时读取忆凡尘提供的本地记忆。
- **Codex**：读取本机 Codex 会话记录，整理成可回源经验。
- **Skill / MCP 客户端**：通过通用知意规则和只读召回入口接入。
- **本地文件**：保留基础的本地记录读取能力。

## 文档

- [Wiki](https://github.com/strmforge/memcore-cloud/wiki)
- [第一次使用](https://github.com/strmforge/memcore-cloud/wiki/%E7%AC%AC%E4%B8%80%E6%AC%A1%E4%BD%BF%E7%94%A8)
- [知意](https://github.com/strmforge/memcore-cloud/wiki/%E7%9F%A5%E6%84%8F)

## 版本

当前版本：**2026.5.28**

更新记录见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT](LICENSE)
