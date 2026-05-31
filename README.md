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
  <a href="https://github.com/strmforge/memcore-cloud/releases/tag/v2026.5.31">2026.5.31</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-2026.5.31-2f5f9b">
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
- **知意整理**：从记录里提炼用户喜好、表达习惯、纠偏和常见问题，形成可以反复使用的偏好与意图经验。
- **行策沉淀**：从做事、失败、纠偏和验收里长出下一次可参考的做法。
  行策主要保存工作经验，不是技能库。比如某个项目历史上为什么不能动某个改法、排障先查哪条链路、一次失败后下次怎么验收，这些没有标准输入输出，但会影响下一次怎么做。
- **自然接入**：OpenClaw、Hermes、Codex 继续用原来的入口，忆凡尘在后台提供记忆。
- **Hermes 原始记忆供给**：Hermes native review 被触发时，可以读取忆凡尘开放的 raw/source_refs 路径指针，必要时再由 Hermes 自己去看原始资料；忆凡尘负责发出 self-review signal、观察 native feedback，不直接替 Hermes 写 skill。
  2026.5.31 起，self-review signal 有 wake dry-run 和授权 receipt gate，可记录“已产生信号”，但这仍不等于 Hermes 已执行 `background_review` 或生成 skill。
- **增量读取**：对还在增长的本机会话文件，从上次位置继续读取，减少重复扫描。
- **本地页面**：打开 `http://127.0.0.1:9850`，查看接入状态、模型选择和新生成的经验。
- **三端可用**：支持 macOS、Linux、Windows，也支持 WSL 环境。

## 2026.5.29 新增

- **知行图书馆**：原始记忆是底本，知意是理解类馆藏，行策是工作经验和工具书。图书馆里不只放“懂你”的书，也放能指导做事的工具书。
- **召回可解释**：召回结果会带 `library_id`、书架、来源、命中方式和排序理由，方便知道这条经验为什么被带出来。
- **行策对象生产化**：行策候选开始按工作场景、行动策略、禁用条件、验收方式和生命周期整理。
- **轻量图谱与混合召回契约**：先提供用户、项目、平台、任务、偏好、工作经验这些节点和强关系，配合 source_refs、关键词、向量可用状态和项目过滤。
- **效果回放计划**：新增只读回放计划，用同一批任务对比无记忆、只有知意、知意加行策的差异。
- **知行闭环 dry-run**：7 步流程穿过五书架，并用确定性规则检查 4 个防御指标和 1 个进攻指标；回放后生成待审反哺候选，不自动写入正式经验。
- **使用回执**：每次召回都会说明用了哪些馆藏号、哪些来源、为什么命中，以及本轮没有写入平台。
- **工具书候选入口**：平台事实、环境差异和命令实测可以先生成工具书候选；当前是 dry-run / validate，不直接写入馆藏。
- **Codex 本地接入**：读取本机 Codex 会话记录，进入同一个本地记忆底座。
- **通用知意入口**：新窗口可以用 `/zhiyi` 接上前情；英文环境可用 `/memory`、`/recall`、`/continue` 或 `catch me up`。
- **Skill / MCP 接入**：提供平台中立的 `yifanchen-zhiyi` Skill，以及只读的 `zhiyi_recall` 召回入口。
- **能力检查模式**：安装和冒烟测试可以用 `mode=capability_check` 验证 Skill / MCP / 只读状态，不触发召回、不返回原文。
- **共享记忆底座**：OpenClaw、Hermes、Codex 可以使用同一套本地原始记忆，但各自窗口和 agent 仍分开管理。
- **增量与续读**：正在增长的会话文件从上次位置继续读取，旧记录回源时支持分段补查。
- **来源可回看**：知意经验带馆藏号、状态和来源线索，尽量回到原话出处。
- **行策说明补齐**：行策作为工作经验层，负责把做事过程里的经验沉淀成下一次可参考的路径。
- **本地网关加固**：只读召回网关显式限制本机回环访问，并防止续读状态误写入平台配置目录。

## 2026.5.30 新增

- **真实任务集 benchmark**：新增多案例 dry-run，用同一批真实任务形状对比无记忆、只有知意、知意加行策，先看信号质量，再决定是否建设 Replay 反哺队列。
- **偏好提取更谨慎**：新增偏好意图 gate。用户纠错、指代澄清、转述审计材料和创作提示不会因为出现“称呼”“偏好”等词就被写成长期知意偏好。
- **Windows 大样本实测**：施工版已在 Windows 本地服务上做运行测试，验证 Web、Replay/benchmark、MCP、OpenClaw raw 查询、source_refs 和错误日志状态。

## 2026.5.31 新增

- **自然语言纠错入口**：当用户在原来的 AI 工具里说“这条记错了”“你理解偏了”“不是我的意思”时，忆凡尘会把它识别为勘误候选，而不是继续当作普通偏好写入。
- **方法信号候选**：外部资讯、工具仓库和实践反馈可以先进入 `external_method_signal_candidate` dry-run，作为“新方法是否值得沉淀”的候选，不直接安装或激活。
- **Agent 安装闭环**：README 提供可直接发给 AI agent 的安装提示；安装器会自动安装 Codex skill，并在检测到 Codex CLI 时注册 `yifanchen-zhiyi` MCP，用户不需要先理解 Skill 或 MCP。
- **Hermes 学习心跳**：新增只读 native learning liveness 检查，报告最近是否有 Hermes `background_review`、`skill_manage` 和 skill 文件变化，帮助区分“会被触发时能学”和“这几天自然链路冷掉了”。
- **Hermes 消费回执**：按 Hermes 官方 MemoryProvider 生命周期补齐 `sync_turn` 回执和 `queue_prefetch` 预热；`sync_turn` 回执走后台线程，避免阻塞 Hermes hook。Hermes 不复制 OpenClaw 的 before-dispatch 拦截形态，但每轮可以记录“是否召回、命中多少、是否进入 turn 后回执”。
- **Hermes 技能与经验对比升级**：新增只读 `skill-experience-diff` dry-run，把 Hermes 生成或修改的 skill 与忆凡尘现有经验对照，产出待审 adoption / upgrade 候选；不直接写 Hermes skill，也不直接写正式经验。
- **状态账本 / 时间索引**：新增只读 dry-run，回答“当前最新可信判断是什么”，同时把已采用、待复核、已废弃、被替代和冲突记录放在同一条时间线上；时间索引只是导航，不替代 raw。
- **上下文预算最小单元**：新增 `context_budget_unit_candidate` dry-run，把纠错、工具事实、方法信号、工作经验等整理成可回源、可组合、可过期复核的上下文最小单元；“粒子/离子”命名仍按待核验方向处理，不写成已确认原话。

## 知意是什么

知意是忆凡尘里最靠近人的一层。

它不是搜索框，也不是把聊天压成几句摘要。它更像一个安静的整理者：从你反复说过的话里看见真正的意思，记住偏好、背景、案例和纠偏，让这些经验在下次需要时还能回来。

比如你多次强调“不要让我去另一个页面查，我希望原来的 AI 工具自然变聪明”，知意应该记住的不是这句话本身，而是背后的使用偏好：服务要安静、顺手、少打扰。

所以忆凡尘的页面不应该成为新的工作负担。日常你仍然在 OpenClaw、Hermes、Codex 里聊天；偶尔打开本地页面时，重点看的是有没有新的经验、这些经验是否准确、是否需要删除或保留。

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

原始记忆是底本，永远不被知意或行策替代。知意更像理解类馆藏，保存用户喜好、表达习惯、纠偏、意图和背景；行策更像工具书和工作手册，保存做事路径、项目边界、排障顺序、踩坑记录和验收方法。

每条馆藏都应该能回答几个问题：它的馆藏号是什么，来自哪段原话，属于哪个书架，现在是候选还是已采用，有没有冲突或被替代，什么时候最后验证过，适用范围和禁用条件是什么。工具书也一样不能凭空出现：外部文档和平台探测日志要先进入 `raw/external_docs/` 或 `raw/probe_logs/`，再长成工具书馆藏。

例如一条平台探测事实：“某工具的 profile 配置会被立即读取，而大小写敏感系统只识别官方大写文件名”，应该先保存对应命令输出或官方文档片段，再生成工具书候选。这样它是可回看的平台事实，不是模型凭印象写出的结论。

所以忆凡尘接下来不是只追求“召回一段看似聪明的总结”，而是追求：知意可回源，行策可验收，召回可解释，效果可回放。知行闭环按 7 步流转：原样保存、知意回源、行策沉淀、工具书补事实、勘误处理冲突、Replay 验证、反哺召回或行动。回放评分优先走确定性规则：预期来源、预期行为、禁踩旧坑、必要验收项，以及能否主动浮现用户忘了但过去做对过的东西，而不是让模型自己夸自己。当前反哺先生成 adoption / errata / proactive resurfacing 候选；授权 apply 只写审阅收据，不自动写正式经验。

工具书候选入口先做只读预检：`/api/v1/zhixing/toolbook-candidates/dry-run` 会根据平台、环境、实测现象、原话片段和 raw 来源生成候选；`/api/v1/zhixing/toolbook-candidates/validate` 只校验候选是否满足证据契约。两者都不会写 raw、知意、行策或平台配置。

2026.5.31 起，状态账本和上下文最小单元也先以只读入口出现：`/api/v1/zhixing/state-ledger/plan`、`/api/v1/zhixing/state-ledger/dry-run` 用来复核“最新可信判断”和同主题时间线；`/api/v1/zhixing/context-units/contract`、`/api/v1/zhixing/context-units/dry-run` 用来生成待审 `context_budget_unit_candidate`。这些入口都不写 raw、知意、行策、工具书、勘误或平台配置。

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

如果你正在使用 Codex、OpenClaw、Hermes、Claude Code 或其他能操作本机终端的 AI agent，可以直接把下面这段话发给它：

```text
请帮我在本机安装忆凡尘（Yifanchen），仓库是 https://github.com/strmforge/memcore-cloud 。
安装完成后请启动本机服务；请自动安装 Codex skill；如果检测到 Codex CLI，请自动把 Codex MCP 接到 http://127.0.0.1:9851/mcp，MCP 名称用 yifanchen-zhiyi。
如果检测到 OpenClaw 或 Hermes，也请按安装器默认方式接入。
最后只做 capability check，不要召回我的真实记忆。
```

安装器会尽量自动完成本机接入：OpenClaw 插件、Hermes provider、Codex skill、Codex MCP 都会按平台能力接好，用户不需要先理解 Skill 或 MCP。Codex skill 会给新开的 Codex 会话一个明确锚点：忆凡尘是一座本机记忆图书馆；Codex MCP 注册成功后，新会话可以看到 `yifanchen-zhiyi` / `zhiyi_recall`；已经打开的会话可能需要重开后才会加载新连接。

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
- **Hermes**：在本机可用时读取忆凡尘提供的本地记忆；Hermes native review 触发并产生 skill/learning 变化时，忆凡尘可以观察变化并生成待审升级输入。
- **Codex**：读取本机 Codex 会话记录，整理成可回源经验。
- **Skill / MCP 客户端**：通过通用知意规则和只读召回入口接入。
- **本地文件**：保留基础的本地记录读取能力。

## 文档

- [为什么叫忆凡尘](INTRODUCTION.md)
- [Wiki](https://github.com/strmforge/memcore-cloud/wiki)
- [第一次使用](https://github.com/strmforge/memcore-cloud/wiki/%E7%AC%AC%E4%B8%80%E6%AC%A1%E4%BD%BF%E7%94%A8)
- [知意](https://github.com/strmforge/memcore-cloud/wiki/%E7%9F%A5%E6%84%8F)
- [行策](https://github.com/strmforge/memcore-cloud/wiki/%E8%A1%8C%E7%AD%96)

## 版本

当前版本：**2026.5.31**

更新记录见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[MIT](LICENSE)
