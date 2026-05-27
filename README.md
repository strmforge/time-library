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
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.5.27">2026.5.27</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.5.27-2f5f9b">
  <img alt="Platforms" src="https://img.shields.io/badge/macOS%20%7C%20Linux%20%7C%20Windows-ready-247447">
  <img alt="Local first" src="https://img.shields.io/badge/local--first-memory-b07d35">
</p>

## 人间会忘，忆凡尘会记得

人和 AI 的对话，常常像一天里擦肩而过的话。

今天说清楚了一个想法，明天又要重新解释；这台电脑懂了，换一个入口又像从头认识。真正有用的，不只是那一轮回答，而是你一路说过的话、做过的选择、留下的偏好、踩过的坑。

忆凡尘做的事很朴素：把这些人间的细节留在本机。你继续在 OpenClaw、Hermes、Codex 等工具里正常聊天，它在旁边安静记下原始对话，整理成可回看的经验。你感觉到的，不应该是多了一个复杂东西，而是原来的工具更顺手了，更像认识你了。

## 它能做什么

- **原样保存**：对话按来源、会话和时间留在本机，尽量不改变原始内容。
- **知意整理**：从记录里提炼案例、偏好和常见问题，形成可以反复使用的经验。
- **自然接入**：OpenClaw、Hermes、Codex 继续用原来的入口，忆凡尘在后台提供记忆。
- **增量读取**：对还在增长的本机会话文件，从上次位置继续读取，减少重复扫描。
- **本地页面**：打开 `http://127.0.0.1:9850`，查看接入状态、模型选择和新生成的经验。
- **三端可用**：支持 macOS、Linux、Windows，也支持 WSL 环境。

## 知意是什么

知意是忆凡尘里最靠近人的一层。

它不是搜索框，也不是把聊天压成几句摘要。它更像一个安静的整理者：从你反复说过的话里看见真正的意思，记住偏好、背景、案例和纠偏，让这些经验在下次需要时还能回来。

比如你多次强调“不要让我去另一个页面查，我希望原来的 AI 工具自然变聪明”，知意应该记住的不是这句话本身，而是背后的使用偏好：服务要安静、顺手、少打扰。

所以忆凡尘的页面不应该成为新的工作负担。日常你仍然在 OpenClaw、Hermes、Codex 里聊天；偶尔打开本地页面时，重点看的是有没有新的经验、这些经验是否准确、是否需要删除或保留。

知意偏向“懂你”，行策偏向“知道怎么做”。第一版先把能看见、能回源、能继续积累的经验做好。

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
- **Codex**：读取本机 Codex 会话记录，整理成可回源经验；不读取登录、token 或 auth 文件。
- **本地文件**：保留基础的本地记录读取能力。

## 文档

- [Wiki](https://github.com/strmforge/memcore-cloud/wiki)
- [第一次使用](https://github.com/strmforge/memcore-cloud/wiki/%E7%AC%AC%E4%B8%80%E6%AC%A1%E4%BD%BF%E7%94%A8)
- [知意](https://github.com/strmforge/memcore-cloud/wiki/%E7%9F%A5%E6%84%8F)

## 版本

当前版本：**2026.5.27**

更新记录见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT](LICENSE)
