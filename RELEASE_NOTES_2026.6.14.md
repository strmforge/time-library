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
- **Release checks remain guarded**: public wording scans, private `AGENTS.md`
  exclusion, release artifact checks, internal direction audit, and full tests
  are expected to pass before publication.

### Boundaries

- This candidate has not been pushed, tagged, or published as a GitHub Release
  until the release workflow explicitly does so.
- Local maintainer-only files and local `AGENTS.md` remain ignored and are not
  part of public release artifacts.
- Capability check remains read-only and no-recall.
- LAN reachability for OpenClaw and Hermes remains supported when explicitly
  configured.
- Multi-machine validation must be reported from the actual run; do not infer
  Windows status from earlier releases.

## 中文

### 主要更新

- **天道管辖下拆分模块**：原先过大的 console、Platform Guard、Claude Desktop、raw gateway、Hermes liveness 和记录守护相关文件，按真实管辖边界拆分，而不是按行数硬切。
- **记录起源仍然第一**：canonical index、raw evidence excerpt、raw backfill 进入独立记录模块，但 raw source record 仍然是最高事实。
- **控制台仍是入口**：`p6_console.py` 保留为人类控制台入口和兼容 wrapper；UI、动作安全门、状态诊断、OpenClaw inlet、知意 runtime、体验治理拆到更小模块。
- **Platform Guard 更清楚**：catalog、model identity、package inventory、surface scan 与授权 platform config apply 分开。
- **Claude Desktop 采集边界更清楚**：Claude Desktop raw ingest 从 connector 入口中拆出；本地中转痕迹只保留为开发/兼容元数据，不写成公开依赖。
- **运行版本对齐**：候选版在 VERSION、gateway health、active memory routing、preflight metadata、本地控制台文本、platform storage contract 和随包 Zhiyi skill 中统一报告 2026.6.14。
- **发布检查继续守门**：公开文案扫描、私有 `AGENTS.md` 排除、发布包检查、内部方向审计和全量测试都必须在发布前通过。

### 边界

- 这是本地候选版；在发布流程明确执行前，还没有 push、tag，也没有发布 GitHub Release。
- 维护者本地文件和本地 `AGENTS.md` 仍然被忽略，不进入公开发布包。
- capability check 仍然只读、无真实召回。
- 明确配置时仍然保留 OpenClaw / Hermes 的局域网访问能力。
- 多机验证必须以真实运行结果为准；不能沿用旧版本的 Windows 结论。
