# Memcore Cloud 2026.6.20

2026.6.20 is a safety-focused public release for Memcore Cloud. It lowers the
risk of local agent memory overreach, especially OpenClaw-style interception,
while keeping recall source-backed and local-first.

Memcore Cloud remains a local AI memory library: original records stay on the
user's machine, recall is source-backed, and reusable experience must keep a
traceable evidence trail.

## What This Release Contains

- **Local AI memory library**: original records remain the local source of
  truth, while source refs, library ids, and receipts make recall auditable.
- **Safer local-agent authority**: Zhiyi is a memory and evidence layer, not a
  default replacement for the host agent. OpenClaw-style interception defaults
  to off; direct Zhiyi answers and platform actions require explicit entry or
  authorization.
- **Low-resource defaults**: watchers default to a light profile, a 5-second
  interval, and narrow source selection instead of full-source 250ms scans.
- **More honest local tool display**: public docs may describe supported AI
  tools, but the local console should emphasize tools actually detected on the
  current machine.
- **Pre-work checks**: `work_preflight` / preflight doctor can run as a quick
  daily smoke path, with full diagnostics reserved for explicit troubleshooting.
- **Source-backed recall**: recall remains compact by default, with source refs
  first and raw excerpts only when explicitly requested.
- **Evidence-bound model path**: MiniMax, DeepSeek, and OpenAI-compatible
  models can be used for evidence-bound answer refinement and candidate
  checking without treating models as benchmark-only toys.
- **Fast model diagnostics**: the model matrix can compare baseline top+pack
  two-call behavior with a single-call fast audit, including call count,
  latency, CPU/RSS, decision drift, and risk flags.
- **Benchmark diagnostics, not leaderboard claims**: public docs now separate
  no-key retrieval diagnostics, internal answer judging, and official
  evaluator paths so scoring work does not masquerade as a published benchmark.
- **Evaluation guardrails**: daily use, targeted regression, and offline
  benchmark entry points are separated so scoring work does not overload a
  workstation or silently become the daily path.

## 中文

2026.6.20 是一次以安全降险为核心的公开版本。它降低本机 agent 记忆层越权的
风险，尤其是 OpenClaw 这类拦截入口默认抢答的问题，同时继续保持本机优先和
可回源召回。

### 本版本包含

- **更安全的本机 agent 权限边界**：知意是记忆和证据层，不默认替代宿主
  agent。OpenClaw 这类拦截入口默认关闭；直接回答和平台动作必须有显式入口
  或授权。
- **低资源默认**：watcher 默认 light profile、5 秒间隔、窄来源选择，不再默认
  全来源 250ms 扫描。
- **更诚实的本机工具展示**：公开文档可以说明支持哪些 AI 工具，但本机控制台应
  优先展示当前机器真实检测到的工具。
- **开工前检查**：`work_preflight` / preflight doctor 支持日常快速 smoke，
  full 体检保留给显式排障。
- **可回源召回**：默认返回紧凑 source refs；只有明确需要原文证据时才取 raw
  excerpt。
- **证据绑定模型路径**：MiniMax、DeepSeek 和 OpenAI-compatible 模型可以用于
  证据绑定回答、候选判断和经验精炼，不再只作为 benchmark 工具。
- **fast 模型诊断**：模型矩阵可比较 top+pack 双调用 baseline 和单调用 fast
  audit，记录调用数、耗时、CPU/RSS、逐题漂移和风险标记。
- **评分诊断不冒充榜单**：公开文档已区分免费检索诊断、内部答案判分和官方
  evaluator 路径，避免把本地诊断说成公开 benchmark 成绩。
- **评测护栏**：日常入口、定向回归和离线 benchmark 分开，避免跑分任务拖垮
  工作机，也避免把评分路径误当成日常路径。

## Boundaries

- Local benchmark and model-matrix reports are diagnostics, not official
  leaderboard scores.
- Benchmark run outputs, caches, and local R730XD pressure-test artifacts are
  not part of the public release payload.
- Direct Zhiyi answers and platform actions remain explicit-entry or
  explicit-authorization paths; ordinary OpenClaw chat is passive by default.
