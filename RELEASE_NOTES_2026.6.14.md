# Memcore Cloud 2026.6.14

Memcore Cloud 2026.6.14 is a local release candidate for the Tiandao-governed
large-module cleanup. It keeps the 2026.6.12 public release base, then makes the
next codebase easier to audit by moving giant-file responsibilities into
explicit Tiandao ownership modules.

Status: local release candidate, not published yet.

## English

### Highlights

- **Tiandao-governed module split**: the former giant console, platform guard,
  Claude Desktop, raw gateway, Hermes liveness, and record-guardian surfaces
  have been split by ownership boundary rather than arbitrary line count.
- **Record origin remains first**: canonical indexing, raw evidence excerpts,
  and raw backfill now live in dedicated record modules, but raw source records
  remain the highest authority.
- **Console stays an entrypoint**: `p6_console.py` remains the human console and
  compatibility wrapper, while UI, action gates, status diagnostics, OpenClaw
  inlet, Zhiyi runtime, and experience governance live in smaller modules.
- **Platform Guard is clearer**: catalog, model identity, package inventory,
  and surface scanning are separated from authorized platform-config apply.
- **Claude Desktop capture boundary is clearer**: Claude Desktop raw ingest
  logic is isolated from the connector entrypoint, and local relay references
  remain development/compatibility metadata rather than public requirements.
- **Runtime version alignment**: the candidate reports 2026.6.14 in the version
  file, gateway health, active-memory routing, preflight metadata, local console
  text, platform storage contract, and packaged Zhiyi skill.
- **Install readiness waits for large local libraries**: macOS, Linux, and
  Windows installers now wait for slow-starting local services instead of
  failing after a single early smoke probe.
- **Current-run multi-machine validation**: local macOS, Windows191, and
  Windows123 were upgraded to 2026.6.14 in the current validation run; both
  Windows hosts passed native smoke with `raw_sync=raw_current`.
- **Record doctor and record chain**: a new read-only doctor/demo check shows
  whether source records, raw mirrors, the canonical index, and memory/experience
  links are guarded. The timeline/replay surface is framed as a record chain,
  not a memory wall.
- **Recall output is quieter by default**: Zhiyi recall now returns compact
  source refs, counts, receipts, and rank reasons by default. Bounded raw
  excerpts remain available only when explicitly requested with a raw response
  budget.
- **Runtime bootstrap starts the foundation cleanup**: new and migrated command
  entry points can share one repository/import bootstrap instead of adding more
  ad-hoc path setup snippets.
- **Double-click install entries**: release zips now include a macOS
  `Memcore Cloud Installer.command` and a Windows `Memcore Cloud Installer.cmd`;
  the Windows entry opens a folder picker before running the same installer.
- **Public wording tightened**: public copy now emphasizes local memory plus
  experience backed by raw records, while the detailed integration capability
  coverage stays maintainer test material rather than user-facing product text.
- **Release checks remain guarded**: public wording scans, private local
  agent-rule file exclusion, release artifact checks, internal direction audit,
  and full tests are expected to pass before publication.

### Boundaries

- This candidate has not been pushed, tagged, or published as a GitHub Release
  until the release workflow explicitly does so.
- Local maintainer-only files and private local agent-rule files remain ignored
  and are not part of public release artifacts.
- Capability check remains read-only and no-recall.
- LAN reachability for OpenClaw and Hermes remains supported when explicitly
  configured.
- Multi-machine validation in this note comes from the 2026-06-14 current run,
  not from earlier release notes.

## 中文

### 主要更新

- **天道管辖下拆分模块**：原先过大的 console、Platform Guard、Claude Desktop、raw gateway、Hermes liveness 和记录守护相关文件，按真实管辖边界拆分，而不是按行数硬切。
- **记录起源仍然第一**：canonical index、raw evidence excerpt、raw backfill 进入独立记录模块，但 raw source record 仍然是最高事实。
- **控制台仍是入口**：`p6_console.py` 保留为人类控制台入口和兼容 wrapper；UI、动作安全门、状态诊断、OpenClaw inlet、知意 runtime、体验治理拆到更小模块。
- **Platform Guard 更清楚**：catalog、model identity、package inventory、surface scan 与授权 platform config apply 分开。
- **Claude Desktop 采集边界更清楚**：Claude Desktop raw ingest 从 connector 入口中拆出；本地中转痕迹只保留为开发/兼容元数据，不写成公开依赖。
- **运行版本对齐**：候选版在 VERSION、gateway health、active memory routing、preflight metadata、本地控制台文本、platform storage contract 和随包 Zhiyi skill 中统一报告 2026.6.14。
- **安装 smoke 适配大库慢启动**：macOS、Linux、Windows 安装器现在会等待本地服务就绪，不再把一次过早探测失败当成最终失败。
- **当前轮多机验证**：本地 macOS、Windows191、Windows123 已在当前验证轮升级到 2026.6.14；两台 Windows 的 native smoke 都通过，且 `raw_sync=raw_current`。
- **记录医生与记录链路**：新增只读 doctor/demo 自检，展示源记录、raw 镜像、所有会话底座、记忆与经验链路是否守住；timeline/replay 按记录链路展示，不做记忆墙。
- **召回默认降噪**：知意召回默认返回精简的来源线索、计数、回执和命中理由；有界原文摘录仍可用，但必须显式请求 raw response budget。
- **运行地基统一起步**：新增统一 repository/import bootstrap，新入口和后续迁移可以复用同一套路径初始化，不再继续增加零散 path setup。
- **双击安装入口**：release zip 现在包含 macOS `Memcore Cloud Installer.command` 和 Windows `Memcore Cloud Installer.cmd`；Windows 入口会先弹出目录选择，再调用同一套安装脚本。
- **公开文案收紧**：公开文案改为强调本机记忆与经验、raw record 回源；细分接入覆盖留作维护者测试材料，不作为用户可见产品文本。
- **发布检查继续守门**：公开文案扫描、私有本机 agent 规则文件排除、发布包检查、内部方向审计和全量测试都必须在发布前通过。

### 边界

- 这是本地候选版；在发布流程明确执行前，还没有 push、tag，也没有发布 GitHub Release。
- 维护者本地文件和私有本机 agent 规则文件仍然被忽略，不进入公开发布包。
- capability check 仍然只读、无真实召回。
- 明确配置时仍然保留 OpenClaw / Hermes 的局域网访问能力。
- 本说明中的多机验证来自 2026-06-14 当前运行，不沿用旧版本结论。
