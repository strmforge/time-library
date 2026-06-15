# Native Windows And Official Codex

Memcore Cloud treats native Windows as the normal Windows install path. WSL is
for development, advanced testing, or special debugging.

## What Was Verified

Memcore Cloud 2026.6.4 was verified on a clean native Windows machine with an
official Codex install.

The important detail: official Codex may not expose `codex.exe` on `PATH`.
Memcore Cloud can still find the bundled official CLI from Codex native-host
metadata and register `yifanchen-zhiyi` through the official `codex mcp add`
command.

Verified result:

- Memcore Cloud installed natively under `%LOCALAPPDATA%\memcore-cloud`;
- native Python 3.12 created the local venv;
- the Codex skill was installed under `%USERPROFILE%\.codex\skills`;
- `yifanchen-zhiyi` appeared in official `codex mcp list`;
- `zhiyi_recall` capability check returned the installed Memcore Cloud version;
- the MCP response was standard JSON-RPC;
- capability check stayed read-only and did not run real recall.

## Why This Matters

Many Windows users will install desktop apps but will not configure shells,
PATH, WSL, or developer runtimes by hand.

For Codex, the reliable path is:

1. Install Memcore Cloud natively.
2. Let Memcore Cloud discover the official bundled Codex CLI.
3. Let Memcore Cloud install the Zhiyi skill.
4. Let Memcore Cloud register `yifanchen-zhiyi` through Codex MCP.
5. Run capability check before real recall.

This keeps setup simple while still using Codex's own MCP registration command.

## Troubleshooting

If `python`, `python3`, or `py` exists but the installer still says Python is not
usable, check whether Windows is returning a Microsoft Store alias instead of a
real Python runtime.

A real Python candidate must be able to run:

```powershell
python -c "import sys; print(sys.executable); print(sys.version)"
```

If `codex` is not found on `PATH`, that is not automatically a failure. Memcore
Cloud also checks Codex native-host files such as:

```text
%USERPROFILE%\.codex\chrome-native-hosts-v2.json
%USERPROFILE%\.codex\chrome-native-hosts.json
%LOCALAPPDATA%\OpenAI\Codex\chrome-native-hosts-v2.json
%LOCALAPPDATA%\OpenAI\Codex\chrome-native-hosts.json
```

After install, the simplest verification is:

```powershell
codex mcp list
```

or, when Codex is not on PATH, use the bundled `codex.exe` found from the
native-host metadata.

The repeatable native Windows smoke check is:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\memcore-cloud\tools\windows_native_smoke.ps1"
```

It checks local service health, official Codex MCP registration, and a safe
`zhiyi_recall` capability check. It also checks that the Zhiyi model setting is
present in the local console and that a model-setting dry run stores no secret
and calls no model. It also checks Agent Work Preflight so a connected agent can
ask "what do we already have?" before coding or operational work. It does not run real recall.

Expected MCP entry:

```text
yifanchen-zhiyi
```

Expected safe capability check facts:

```text
service: raw_consumption_gateway
server: yifanchen-zhiyi
version: <installed Memcore Cloud version>
read_only: true
recall_performed: false
raw_excerpt_returned: false
mcp_tools: ["zhiyi_recall"]
```

Expected Agent Work Preflight facts:

```text
mode: work_preflight
contract: agent_work_preflight.v2026.6.16
source_preflight_contract: zhixing_preflight.v2026.6.16
read_only: true
write_performed: false
model_called: false
raw_excerpt_returned: false
receipt_scope: agent_work_preflight_read_only
```

## Boundary

Installing the Skill and MCP entry proves Codex can call Memcore Cloud. It does
not mean real memory was recalled.

Real recall should still follow the active memory routing rule: a normal Codex
window should read its own bound window/session first, and broader project or
cross-window memory should be explicit.

Agent Work Preflight is a different safe path from real recall. It is meant for
the beginning of work: classify whether the request looks like an existing
feature that was forgotten, an existing feature that is miswired, a diagnostic
gap, or something actually missing. It should guide the agent into the right
repo inspection and diagnostics, not replace source-backed recall or user
approval.

## 中文

Windows 用户默认应该走原生安装，不是 WSL。WSL 只适合开发、高级测试或特殊排障。

这次已经验证：一台原生 Windows 机器上的官方 Codex，即使 `codex.exe` 不在 PATH，
忆凡尘也能从 Codex 的 native-host JSON 找到官方 bundled CLI，然后用官方
`codex mcp add` 注册 `yifanchen-zhiyi`。

验证结果：

- 忆凡尘安装到 `%LOCALAPPDATA%\memcore-cloud`；
- 使用 Windows 原生 Python 3.12 创建 venv；
- Codex skill 安装到 `%USERPROFILE%\.codex\skills`；
- 官方 `codex mcp list` 能看到 `yifanchen-zhiyi`；
- capability check 返回当前安装的忆凡尘版本；
- MCP 返回标准 JSON-RPC；
- capability check 只读、不召回真实记忆、不返回 raw excerpt。

排障重点：

- WindowsApps 里的 `python.exe` / `python3.exe` 可能只是 Microsoft Store
  占位符，不是真 Python；
- 官方 Codex 不在 PATH 不代表没安装，要查 native-host JSON；
- 可重复的原生 Windows 验收命令是：
  `powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\memcore-cloud\tools\windows_native_smoke.ps1"`；
- 这条验收还会检查“知意模型”入口是否在控制台里、模型设置 dry-run
  是否不保存密钥、不调用模型；
- 这条验收也会检查 Agent Work Preflight：agent 动手前可以先问“我们是不是已经做过了”，
  并确认该路径只读、不写入、不调用模型、不返回 raw excerpt；
- 安装后先做 capability check，再做真实 recall；
- 当前窗口召回仍要遵守窗口优先的防污染规则；
- Work Preflight 不是第六层知识库，也不是替代召回；它只是开工前把“已做但忘了 / 已做但接错 /
  诊断缺口 / 真缺失”先分清楚。
