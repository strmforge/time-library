# 接入 agent

时间图书馆不为任何 agent 写代码，以后也不会。agent 自己接入：描述自己的会话文件，在自己的文件
上检查，再报上来。完整的字段说明在每个服务端提供的安装说明里：
`http://<NAS 地址>:9850/client/install.md`（第 4 步）。这一页只讲大意。

## 描述

描述是一份小小的 JSON。先挑一个和自己记录最像的形状做 `base`，再改不一样的地方：

- **哪些记录是对话**：`match`、`skip_if_true`、`skip_if_equals`；
- **谁在说**：`role`，说话人的词不是 user/assistant 时用 `role_map` 说明；
- **说了什么**：`content`、`text_block_types`、`block_text`；
- **什么时候**：`timestamp`；**哪段会话**：`session_id`，或者文件夹名就是会话名时用 `session_id_from_path`；
- **在哪干的活**：`cwd`；**从哪打开的**：`surface`（同一个 agent 有桌面版和命令行时）；
- **只要用户亲手打的字**：`user_match`、`unwrap_elements`（包在用户原话外面的标签）、
  `runtime_elements`（agent 自己加的上下文）、`runtime_messages`；整份文件是子 agent
  自己的记录时用 `session_skip_if_equals`；
- **会话怎么存的**：JSON lines（zstd 压缩的照读），每个会话一个 JSON 文件（`"store": "json"`），
  或者 SQLite 数据库（`"store": "sqlite"`，只读不写）。

## 检查

```bash
PY ~/.time-library-client/tl.py check --sessions "<会话文件夹>" --glob "<哪些文件>" --format-json @description.json
```

什么都不发出去。它会说能收到多少段会话、多少轮对话，给几条看看，列出跳过了什么、为什么，
并提醒看着不对的地方：所有文件都是同一个会话名、一条用户发言都没有、有不认识的说话人、
把上下文当成了用户发言。agent 改描述，直到它说看着对了。

## 报上来

```bash
PY ~/.time-library-client/tl.py report-agent --name "<产品名>" --sessions "<会话文件夹>" --glob "<哪些文件>" --format-json @description.json --capability mcp=true --capability skill=true --capability preflight=true
```

以后再报只给变了的部分。过去的会话大多是测试、不是用户本人的对话时，加 `--since now`：
只收从现在起说的话。

## 提问前钩子

"进来是提问、出去是文字"的钩子直接指向 `tl.py preflight --agent "<产品名>"`。别的形状用
`report-agent --hook-json` 描述一次：用户的话在哪（`prompt`）、输出模板（`output`，记忆放在
`{text}` 处）、没有记忆时打印什么（`empty`）、钩子每次调模型都跑时怎么认出同一轮（`once_per`）。
用 `tl.py check --agent "<产品名>" --hook-sample @sample.json` 试。中间不夹任何脚本。

## 描述不了怎么办

不要绕。如实告诉用户缺什么（哪个字段，附一行能说明问题的记录），只报能读对的部分。
描述语言就是这样长出来的：靠 agent 说自己缺什么，而不是给某个产品写代码。
