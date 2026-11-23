# 时间图书馆 / Time Library

<p align="center">
  <img src="assets/brand/time-library-logo-zh.png" alt="时间图书馆" width="220"/>
</p>

<p align="center">
  <strong>所有 AI agent 共用一份记忆，放在你自己的服务器上，每条都带原话凭据。</strong>
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="https://github.com/strmforge/time-library/releases">版本发布</a> ·
  <a href="https://github.com/strmforge/time-library/wiki">Wiki</a> ·
  <a href="LICENSE">MIT</a>
</p>

**时间图书馆（忆凡尘 · Time Library）** 记住你和各个 AI agent 定下的事、纠正过的错、
踩过的坑——跨所有 agent、跨所有电脑——并且每条记忆都能指回它出自的原话。

它由两部分组成：**NAS 上的一个服务端**（一个 Docker 容器），加上**每台电脑上的
一个轻客户端**。agent 自己接入：你把一句话发给某个 agent，它自己装客户端、
自己报"我是谁、会话记录在哪、支持哪些接入方式"，然后接进来。不需要等谁给某个
工具写适配。

## 这是一次重构

2026.11.23 不是在旧版上加功能，而是把时间图书馆从头重做了一遍。没变的是目标：
所有 agent 共用一份记忆，每条记忆都以原话为凭。架构、代码、安装方式、后台全部换了新的。

| | 2026.9.11 及更早 | 2026.11.23 起 |
|---|---|---|
| 跑在哪 | 每台电脑各跑一整套本机服务 | NAS 上一个服务端（Docker），每台电脑一个轻客户端 |
| 谁共用记忆 | 同一台电脑上的 agent | 所有电脑上的所有 agent |
| 存什么 | 整份原始会话，连工具输出等运行态一起 | 只存对话；运行态在本机就丢掉，密钥出电脑前打码 |
| 新 agent 怎么接 | 按产品写适配 | agent 自己描述会话格式、自己检查、自己报上来；没有为任何产品写的代码 |
| 记忆怎么来 | 原始记录加两层整理 | 每晚提炼成带原话的记忆，引文逐字核对；分得清用户原话、助手转述、用户贴进来的别人的话 |
| 模型 | chat/completions | 按任务选模型、可加备用；原生 Responses、Messages；自带本机模型 |
| 安装 | 安装脚本、安装器 | 服务端 `docker compose up`；客户端由服务端提供，自带 Python |
| 管理 | 每台电脑一个本机页面 | 服务端一个网页后台，中英双语 |

为什么要重做：

- **每台电脑各跑一整套，每台都有自己的问题。** 留下的大头是运行态，不是对话，
  本机硬盘越占越多。现在本机只留读取进度，对话交给 NAS。
- **记忆应该跨电脑。** 一台电脑一份记忆，换台电脑就又从头讲起。
- **按产品写适配跟不上。** 新 agent 出现得比适配写得快。现在由 agent 说清楚自己，
  时间图书馆只负责读懂这份描述。
- **记忆要能当凭据用。** 每条都要能指回原话，还要分清那句话是谁说的。

旧版的"一键更新"不会推送新版：直接覆盖会弄坏旧安装。迁移请看[从旧版迁移](#从旧版迁移)。

## 它怎么工作

```text
 电脑 A                           电脑 B                        你的 NAS（Docker）
 ┌──────────────────────┐        ┌──────────────────────┐     ┌──────────────────────────┐
 │ Claude Code、Codex、 │        │ OpenClaw、Codex……   │     │ 时间图书馆服务端          │
 │ 任意 agent           │        │                      │     │  保存对话                 │
 │   │ 会话记录文件     │        │   │                  │     │  每晚提炼成带原话的记忆   │
 │   ▼                  │        │   ▼                  │     │  回答召回                 │
 │ 客户端：只留对话、   │──局域网▶│ 客户端               │────▶│  管理后台 :9850           │
 │ 密钥打码             │◀─召回─│                      │◀────│                          │
 └──────────────────────┘        └──────────────────────┘     └──────────────────────────┘
```

- **采集**：客户端读各个 agent 自己的会话文件。工具调用、工具输出、思考过程、
  注入的上下文都属于运行态，在本机就丢掉，不出电脑。密钥类内容一律打码；
  邮箱、手机号、证件号默认打码。会话长什么样由 agent 自己描述（一份小小的 JSON），
  先用 `tl.py check` 在自己的文件上试对了再报上来——时间图书馆没有任何为某个产品
  写的代码。
- **提炼**：每天夜里，服务端让模型读当天的新对话，提出记忆——决定、偏好、纠正、
  事实、教训。每条都必须引用它所依据的原话；服务端逐字核对引文确实出现在对话里，
  对不上就不收。别的对话里换个说法又说了一遍的，并进原来那条（可拆回）。分得清
  用户亲口说的、助手转述的、用户贴进来的别人的话（别的 AI 的报告、文章）。
- **整理与归纳**：提炼完再整理一轮：相近的说法比一比，新说法取代旧的（拿不准就都留）；
  被借用后多次评为误导的判为过时；每个项目的记忆归纳成几张经验卡。每一步都留回执，
  都能撤销。
- **召回**：按字词，也按意思（可选的向量模型，就在 NAS 上跑）。agent 通过 MCP 查
  （`time_library_recall`；看前后文用 `time_library_source`；要一个不能猜的确切答案用
  `time_library_answer`——只凭记忆作答，说出依据哪几条，记忆没说就答 UNKNOWN）。
  agent 一打开窗口就看到当前项目的书单；有提问前 hook 的，每次提问前自动查一次，
  只在记忆真的相关时才带原话出现。
- **借还**：每次召回都记一笔借出。agent 用完可以把记忆还回来并评价
  "有用 / 没用上 / 误导"（`time_library_return`），下一个借它的 agent 能看到。
- **白板**：同一个项目里几个 agent 各自写下领了什么、做到哪、交给谁，下一个窗口
  打开就接得上，不用你转述。

## 你能得到什么

- 一份跨 agent、跨电脑的记忆池，每条记忆都标明来自哪台电脑、哪个 agent
  （同一个 agent 的桌面版和命令行也分得开）。
- 凭据优先：每条记忆都带原话，要看完整前后文一次调用就到；每条都有履历
  （第一次和最后一次说起、出现在几段对话、谁借过、评价如何）。
- 证明它有用：每晚体检（原话还在不在、召回抽测），以及"记忆开/关"效果对比
  （同一批题，不给记忆和给记忆各答一遍，按钮触发）。
- 模型自由搭配：按任务（历史导入、每晚提炼、深度归纳）各选主用模型和可选备用；
  原生支持 OpenAI Responses、Anthropic Messages，chat/completions 兜底；key 只存在
  服务端。另有自带的本机模型（llama.cpp 上的 Qwen3-4B），就跑在 NAS 上。
- 断了也不丢：客户端记着读到哪，服务端记着每段对话整理到哪；模型余额不足或连不上
  会自己隔一阵再试，同一段不会提炼两次。NAS 换了地址，客户端在家里局域网里自己找回来。
- 历史导入：装之前就有的会话导进来先扣着，在「导入」页选好范围（最近几个月、哪些
  agent、哪些项目）再点开始，开始前先告诉你预计用多少 token。
- 服务端网页后台：总览、设备与 agent、模型、导入、项目（书单、各 agent、白板）、
  记忆（原话证据、演化链、借还记录、失效与清除、按记忆问一问）。管理密码可改，
  忘了可以用 NAS 上数据文件夹里的服务端钥匙重设。

## 安装

### 1. 服务端，装在 NAS 上

x86-64（Intel / AMD）芯片、能跑 Docker 的 NAS 或 Linux 机器；还没有 ARM 版镜像。在 NAS 本地盘上建个文件夹（不要放在网络共享
上——里面是 SQLite 数据库）：

```bash
mkdir -p time-library && cd time-library
curl -fLO https://raw.githubusercontent.com/strmforge/time-library/main/deploy/nas/docker-compose.yml
docker compose up -d
```

打开 `http://<NAS 地址>:9850`，设置管理密码，在「模型」页添加一个模型来源
（或者打开自带的本机模型）。可选：在 compose 文件旁边放 `.env`，写
`TL_UID` / `TL_GID`（拥有 `data/` 的 NAS 用户）、`TL_PORT`、`TL_VERSION`。

NAS 拉不到镜像？在 NAS 上克隆本仓库，运行
`docker compose -f deploy/nas/docker-compose.yml up -d --build`；如果 NAS 连不上
GitHub，先在别的机器上用 `python3 deploy/nas/llama_runtime.py --dest
deploy/nas/vendor/llama` 取好模型运行时再拷过去。

### 2. 每台电脑：给 agent 一句话

在「设备」页点「生成接入口令」，把那句话发给这台电脑上的任意一个 agent
（Claude Code、Codex、OpenClaw、WorkBuddy……能执行命令的都行）。大致是：

```text
请把你接入忆凡尘服务端 http://<NAS 地址>:9850，接入令牌 tlp_…。先检查本机有没有装
忆凡尘客户端：装了就别重装；没装就打开 http://<NAS 地址>:9850/client/install.md，
照里面的步骤装上。然后照 install.md 第 4 步描述你自己：先看你自己的会话记录长什么样、
存在哪，写成描述，用 tl.py check 在你自己的文件上试到它说看着对了，再用 report-agent
报上来；MCP、skill、提问前预检照第 6 步接……不写任何脚本，不按产品名去猜；有描述
不了的，如实告诉我缺什么。
```

客户端由服务端自己提供，**连同它自己的 Python（Python 3.14）一起**：装在客户端自己的
文件夹里，不装进系统、不改 PATH、不要管理员，电脑上原来有没有 Python 都一样。
macOS / Linux 一条 `curl | tar`，Windows 10 以上用自带的 `curl.exe` 和 `tar.exe`。
客户端版本永远和服务端对得上，装好后也会自己跟着服务端升级。令牌 24 小时内有效，
第一次使用就绑定那台电脑。同一台电脑再接别的 agent，用不带令牌的那句短话。

## 从旧版迁移

2026.9.11 及更早的版本在每台电脑上都跑一整套服务。迁移一台电脑：

1. 先装好服务端（见上）。
2. 把那句话发给这台电脑上的 agent。装好客户端后，安装说明最后一节会让它运行
   `tl.py old-install scan`：找出旧版的安装目录、旧服务和旧版留下的历史，并给出
   每一份历史的导入命令。导入的历史在服务端先扣着，不花钱，等你在「导入」页点开始
   才整理。
3. agent 停掉旧服务，删掉自己配置里指向旧目录的项，按你指定的位置留一份并核对过的
   备份（`old-install archive --to …`），最后才卸载旧版（`old-install remove`）。

旧版本一直保留在[版本发布页](https://github.com/strmforge/time-library/releases)，
需要时可以回退。

## 这一版没有的

- Hermes 的 skill 与经验升级环：不在计划内（Hermes 的对话照常收）。
- 服务端为家里局域网设计：HTTP 加每台电脑一个令牌。不要原样暴露到公网。

## 数据与隐私

- 存在你的 NAS 上：对话（去掉运行态）、记忆、借还记录。原始会话文件仍在各 agent
  自己的位置。
- 发给模型的：正在提炼、整理、作答的那段对话或那几条记忆，发到你为该任务选的地址。中转是第三方；自带的本机
  模型则全程不出 NAS。
- 上传前一律打码：API key、令牌、私钥、URL 与赋值里的密码。默认打码：邮箱、手机号、
  证件号。

## 卸载

- 某台电脑：`PY ~/.time-library-client/tl.py service uninstall`，删掉各 agent 的
  `time-library` MCP / hook / skill，再删除 `~/.time-library-client`；并在「设备」页
  吊销它。
- 服务端：`docker compose down`。它保存的一切都在 `data/` 里。

## 开发

```bash
pip install -r requirements-dev.txt                    # pytest、zstandard、按意思召回的依赖
python -m pytest tests/server_client -q
python -m tl_server --data-dir ./data --port 9850      # 服务端
python -m tl_client --help                             # 客户端
```

`tl_client/` 只用 Python 标准库（3.9 起都能跑，装机时随带 3.14）。`tl_server/` 也是，
按意思召回另需 `requirements-vectors.txt`（镜像里已带）。`system/skills/time-library/`
是客户端安装包里带的 skill。

## 许可证

[MIT](LICENSE)
