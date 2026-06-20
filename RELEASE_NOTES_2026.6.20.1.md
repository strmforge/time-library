# Memcore Cloud 2026.6.20.1

2026.6.20.1 is a public-surface cleanup patch for the 2026.6.20 safety release.
It keeps the passive-first OpenClaw/Zhiyi defaults and removes internal evaluation tooling from the public product tree.

## What Changed

- Keeps 2026.6.20 passive-first delivery:
  - `zhiyi_direct=false`
  - `zhiyi_inject=false`
  - `openclaw_rpc=false`
  - `passthrough=true`
- Removes internal benchmark, judge, model-matrix, and miss-report source files
  from the public product package.
- Keeps the product runtime dependencies required by dialog entry:
  - `src/evidence_bound_model.py`
  - `src/memory_authority_policy.py`
- Adds release-gate checks so product `src/` cannot import eval modules and the
  public release source cannot carry those eval entry points again.
- Updates public README wording to focus on local diagnostics and health checks
  instead of exposing internal scoring machinery.

## Boundaries

- This release does not change the 2026.6.20 passive-first runtime behavior.
- This release does not publish benchmark scores or leaderboard claims.
- Internal benchmark work, if needed, should run from a separate maintainer
  workspace instead of the public product package.

## 中文

2026.6.20.1 是 2026.6.20 安全公开版本之后的公开面清理补丁。它保留普通聊天
passive-first 的止血结果，同时把内部评测、裁判、模型矩阵和错例报告源码从
公开产品树里移出。

### 本版本包含

- 保留 2026.6.20 的 passive-first 默认:
  - `zhiyi_direct=false`
  - `zhiyi_inject=false`
  - `openclaw_rpc=false`
  - `passthrough=true`
- 从公开产品包移除内部 benchmark / judge / model-matrix / miss-report 入口。
- 保留 9860 dialog-entry 必需的产品依赖:
  - `src/evidence_bound_model.py`
  - `src/memory_authority_policy.py`
- release gate 增加机械门，防止产品 `src/` 再 import eval 模块，也防止公开
  release source 再夹带这些评测入口。
- README 改成普通用户可理解的本地诊断和健康检查口径，不再暴露内部跑分机器。

### 边界

- 本版本不改变 2026.6.20 的 passive-first 运行行为。
- 本版本不发布 benchmark 分数，也不声明任何公开榜单成绩。
- 如需继续内部评测，应在维护者自己的独立工作区运行，不进入公开产品包。
