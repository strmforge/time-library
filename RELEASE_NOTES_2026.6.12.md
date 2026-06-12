# Memcore Cloud 2026.6.12

Memcore Cloud 2026.6.12 is a public-wording and release-gate patch release. It
keeps the 2026.6.11 reliability base, then removes local relay tool names from
the open-source surface, preserves compatibility with older local relay traces,
and turns the wording cleanup into a repeatable release check.

## English

### Highlights

- **Public relay denaming**: public docs, catalogs, watchlists, diagnostics, and
  tests no longer expose a specific local relay product as a supported public
  dependency or platform entry.
- **Compatibility without publicity**: older local relay paths, environment
  variables, database names, and raw formats can still be recognized through
  legacy-compatible code paths, but user-facing payloads use neutral
  `local_relay` wording.
- **Lost-source wording**: record diagnostics keep the preferred lost source /
  lost raw semantics instead of legacy stray-record wording.
- **Release-gate regression scan**: `tools/release_gate.py` now scans the
  public and repository text surfaces for the removed relay names and legacy
  stray-record diagnostics so the cleanup does not regress in future releases.
- **Runtime version alignment**: installers, gateway health, active-memory
  routing, preflight metadata, the local console, and packaged Zhiyi skill
  metadata report 2026.6.12 consistently.
- **Windows install validation hardening**: native Windows smoke now recognizes
  running watcher processes even when PowerShell normalizes install paths
  differently, tolerates prefixed JSON from Codex status checks while still
  validating `raw_sync`, and avoids an OpenClaw config traceback when the
  dialog-entry token is empty.
- **Real-machine validation**: the 2026.6.12 package was validated on local
  macOS plus two Windows hosts, with Windows native smoke confirming
  `codex_capture_status raw_sync=raw_current`.

### Boundaries

- 2026.6.12 does not add a new user workflow; it hardens naming, attribution,
  Windows install validation, and release checks around already-built record and
  recall behavior.
- Local relay compatibility is retained for existing personal setups, but the
  public project does not present any relay product as required infrastructure.
- Capability check remains read-only and no-recall.
- LAN reachability for OpenClaw and Hermes remains supported when explicitly
  configured.

## 中文

### 主要更新

- **公开仓库去名化**：公开文档、平台目录、watchlist、诊断和测试不再把某个本地中转工具写成公开依赖或平台入口。
- **兼容但不宣传**：旧的本地中转路径、环境变量、数据库名和 raw format 仍能被兼容识别，但用户可见 payload 使用中性的
  `local_relay` 表达。
- **遗失措辞统一**：记录诊断继续使用遗失源 / 遗失 raw 语义，不再回到旧的游离记录说法。
- **release gate 防回归**：`tools/release_gate.py` 会扫描公开面和仓库文本，阻止被移除的中转工具名和旧的游离记录诊断重新进入发布包。
- **运行版本对齐**：安装器、gateway health、active memory routing、preflight metadata、本地控制台和随包 Zhiyi skill 都统一报告
  2026.6.12。
- **Windows 安装验收加固**：原生 Windows smoke 能识别 PowerShell 路径归一化差异下仍在运行的 watcher；Codex 状态检查即使夹杂前缀输出，也会提取 JSON 后继续校验
  `raw_sync`；OpenClaw config helper 在 dialog-entry token 为空时不再抛 traceback。
- **真机验证**：2026.6.12 包已在本机 macOS 和两台 Windows 主机上验证，Windows native smoke 均确认
  `codex_capture_status raw_sync=raw_current`。

### 边界

- 2026.6.12 不新增普通用户工作流；它加固已有记录和召回能力周围的命名、归属、Windows 安装验收和发布检查。
- 旧本地中转兼容保留给已有个人环境，但公开项目不把任何中转产品写成必要基础设施。
- capability check 仍然只读、无真实召回。
- 明确配置时仍然保留 OpenClaw / Hermes 的局域网访问能力。
