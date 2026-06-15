# Memcore Cloud 2026.6.15

Memcore Cloud 2026.6.15 is a release for the Tiandao-governed memory and
experience system. It keeps the 2026.6.14 cleanup base, then makes
the next codebase easier to audit by turning experience adoption into a
receipt-backed, source-traceable dry-run flow.

Status: published GitHub Release.

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
- **Runtime version alignment**: the release reports 2026.6.15 in the version
  file, gateway health, active-memory routing, preflight metadata, local console
  text, platform storage contract, and packaged Zhiyi skill.
- **Install readiness waits for large local libraries**: macOS, Linux, and
  Windows installers now wait for slow-starting local services instead of
  failing after a single early smoke probe.
- **Experience validation receipts**: Xingce can now emit a dry-run validation
  receipt schema that records pass/fail status, evidence links, and adoption
  blockers without mutating the experience library.
- **Receipt-backed apply gate**: adoption checks prefer validation receipts when
  present, while preserving compatibility with the older validation-report
  fallback path.
- **Apply package preview**: a ready apply package can be built as a local
  dry-run artifact. `package_status=ready` means ready for a future authorized
  apply, not already adopted.
- **Experience flow overview**: the console can now show a compact record chain
  across experience evolution, review action, validation report, validation
  receipt, review queue, apply gate, apply receipt schema, and apply package.
- **Release validation**: 2026.6.15 was tested in this
  run on macOS and two Windows hosts. Full local tests passed, the working-tree
  release gate passed before commit, the committed-HEAD release gate passed
  before publication, Windows native smoke passed, and the record-chain audit
  found no lost source or lost raw. Claude Desktop bridge presence was verified
  on detected Windows Claude config homes; one package-scoped Windows config
  is still malformed JSON and remains a local follow-up.
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
- **Public wording tightened**: public copy now leads with local continuity,
  source-backed records, recall, and reusable work paths, while the detailed
  integration capability coverage stays maintainer test material rather than
  user-facing product text.
- **Release checks remain guarded**: public wording scans, private local
  agent-rule file exclusion, release artifact checks, internal direction audit,
  and full tests passed before publication.

### Boundaries

- Release assets are built from committed `HEAD` after the release gate passes.
- Local maintainer-only files and private local agent-rule files remain ignored
  and are not part of public release artifacts.
- Capability check remains read-only and no-recall.
- LAN reachability for OpenClaw and Hermes remains supported when explicitly
  configured.
- Multi-machine validation for 2026.6.15 was filled from the 2026-06-15
  current run only; older 2026.6.14 results were not reused as proof.

## 中文

### 主要更新

- **天道管辖下拆分模块**：原先过大的 console、Platform Guard、Claude Desktop、raw gateway、Hermes liveness 和记录守护相关文件，按真实管辖边界拆分，而不是按行数硬切。
- **记录起源仍然第一**：canonical index、raw evidence excerpt、raw backfill 进入独立记录模块，但 raw source record 仍然是最高事实。
- **控制台仍是入口**：`p6_console.py` 保留为人类控制台入口和兼容 wrapper；UI、动作安全门、状态诊断、OpenClaw inlet、知意 runtime、体验治理拆到更小模块。
- **Platform Guard 更清楚**：catalog、model identity、package inventory、surface scan 与授权 platform config apply 分开。
- **Claude Desktop 采集边界更清楚**：Claude Desktop raw ingest 从 connector 入口中拆出；本地中转痕迹只保留为开发/兼容元数据，不写成公开依赖。
- **运行版本对齐**：发布版在 VERSION、gateway health、active memory routing、preflight metadata、本地控制台文本、platform storage contract 和随包 Zhiyi skill 中统一报告 2026.6.15。
- **安装 smoke 适配大库慢启动**：macOS、Linux、Windows 安装器现在会等待本地服务就绪，不再把一次过早探测失败当成最终失败。
- **经验验证回执**：行策可以生成 dry-run 验证回执格式，记录通过/失败状态、证据链接和采纳阻断点，但不改写经验库。
- **采纳门禁引用回执**：采纳检查会优先使用验证回执；旧的验证报告路径仍然保持兼容。
- **采纳包预览**：可以生成本地 dry-run 采纳包。`package_status=ready` 只表示未来授权采纳已准备好，不表示已经采纳。
- **经验链路总览**：控制台可以展示经验演进、review action、验证报告、验证回执、review queue、采纳门禁、采纳回执格式、采纳包的紧凑记录链路。
- **发布验证**：2026.6.15 已在本轮对本机 macOS 和两台 Windows 主机实测；本地全量测试通过、提交前 working-tree release gate 通过、发布前 committed-HEAD release gate 通过、Windows 原生 smoke 通过，记录链路巡检未发现遗失源或遗失 raw。已在检测到的 Windows Claude 配置位置确认 Claude Desktop bridge 存在；其中一个 package-scoped Windows 配置仍是异常 JSON，作为本机后续项保留。
- **记录医生与记录链路**：新增只读 doctor/demo 自检，展示源记录、raw 镜像、所有会话底座、记忆与经验链路是否守住；timeline/replay 按记录链路展示，不做记忆墙。
- **召回默认降噪**：知意召回默认返回精简的来源线索、计数、回执和命中理由；有界原文摘录仍可用，但必须显式请求 raw response budget。
- **运行地基统一起步**：新增统一 repository/import bootstrap，新入口和后续迁移可以复用同一套路径初始化，不再继续增加零散 path setup。
- **双击安装入口**：release zip 现在包含 macOS `Memcore Cloud Installer.command` 和 Windows `Memcore Cloud Installer.cmd`；Windows 入口会先弹出目录选择，再调用同一套安装脚本。
- **公开文案收紧**：公开文案改为强调本机工作续接、可回源记录、召回和可复用工作路径；细分接入覆盖留作维护者测试材料，不作为用户可见产品文本。
- **发布检查继续守门**：公开文案扫描、私有本机 agent 规则文件排除、发布包检查、内部方向审计和全量测试已在发布前通过。

### 边界

- 发布资源从提交后的 `HEAD` 构建，并在 release gate 通过后上传到 GitHub Release。
- 维护者本地文件和私有本机 agent 规则文件仍然被忽略，不进入公开发布包。
- capability check 仍然只读、无真实召回。
- 明确配置时仍然保留 OpenClaw / Hermes 的局域网访问能力。
- 2026.6.15 的多机验证已来自 2026-06-15 当前运行；没有沿用旧版 2026.6.14 的结论。
