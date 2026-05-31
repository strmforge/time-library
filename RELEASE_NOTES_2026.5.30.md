# Yifanchen 2026.5.30

## 中文

忆凡尘 2026.5.30 继续完善本机 AI 记忆与经验底座。这一版重点不是增加更多花哨入口，而是让记忆更少误写、更容易验证。

### 新增

- **真实任务 benchmark 入口**：新增 benchmark plan / dry-run，用同一批任务形状对比“无记忆 / 只有知意 / 知意 + 行策”，帮助判断记忆和工作经验是否真的改善 agent 表现。
- **偏好提取更谨慎**：新增偏好意图 gate。用户纠错、指代澄清、转述材料和创作提示，不会因为出现“称呼”“偏好”等词就被写成长期偏好。
- **知行闭环继续收口**：继续沿用原始记忆、知意、行策、工具书、勘误的五书架结构；召回和回放都尽量保留来源、命中方式和可检查的证据。
- **Skill / MCP 版本对齐**：Web console、知行图书馆、raw MCP gateway、安装脚本和 `yifanchen-zhiyi` skill 的运行可见版本对齐到 2026.5.30。

### 边界

- benchmark 目前是验证入口，不代表“机器飞升”已经完成。
- Replay 反哺仍是审阅路径，不会自动写入正式经验。
- 更新不会覆盖本机记忆、raw 记录、知意记录、日志、备份和本地配置。

### 更新

已经安装过的用户，优先打开 `http://127.0.0.1:9850`，进入“设置与更新”，使用“检查更新”和“一键更新”。

如果本地页面打不开，可以重新运行安装命令：

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```

## English

Yifanchen 2026.5.30 continues to improve the local-first memory and experience layer for AI agents. This release focuses on safer memory extraction and better evaluation signals.

### What's New

- **Real-task benchmark entry points**: added benchmark plan / dry-run APIs to compare `no_memory`, `zhiyi_only`, and `zhiyi_plus_xingce` on the same task shapes.
- **Safer preference extraction**: added a precision-first intent gate so corrections, ambiguous references, relayed material, and creative prompts are not written as durable preferences just because they contain preference-like words.
- **Zhiyi/Xingce evidence loop refinements**: keeps the five-shelf structure of raw records, Zhiyi, Xingce, toolbook, and errata, with source-backed recall and explainable results.
- **Skill / MCP version alignment**: runtime-visible versions for the Web console, Zhixing Library, raw MCP gateway, installers, and `yifanchen-zhiyi` skill are aligned to 2026.5.30.

### Notes

- The benchmark is an evaluation surface, not a claim that autonomous feedback adoption is complete.
- Replay feedback remains review-first and does not automatically write adopted production experience.
- Local memory, raw records, Zhiyi records, logs, backups, and local configuration are preserved during updates.

### Update

If Yifanchen is already installed, open `http://127.0.0.1:9850`, go to Settings & Update, then use Check for updates and One-click update.

If the local page cannot open, rerun the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/strmforge/memcore-cloud/main/install.ps1 | iex
```
