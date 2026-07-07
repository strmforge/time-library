/**
 * 公共 EvidenceLevel — 共用合同
 * Tiandao Evidence Level Schema
 *
 * 设计口径：
 *   公共规则是跨系统的中性公共规则层，随着各系统实践而完善。
 *   各系统共用一套公共规则合同，只使用自己需要的公共规则面。
 *
 *   EvidenceLevel 是跨系统通用的证据可信度等级。
 *   不归属于任何单个子系统。归属公共规则层。
 *
 *   旧系统内的同名类型只应作为兼容 re-export，不拥有公共合同。
 *
 * 硬规则（来自公共规则 ADR-000 事实源与验收规则）：
 * - SELF_REPORTED PASS ≠ 真实完成
 * - 看不到真实现场的 agent 不得做现场审计
 * - LOCAL_REVIEWED PASS ≠ CODEX_REVIEWED
 * - CODEX_REVIEWED PASS ≠ OWNER_ACCEPTED
 */

/** 证据可信度等级 */
export type TiandaoEvidenceLevel =
  /** Agent 自报。最低可信度。 */
  | 'SELF_REPORTED'
  /** 自动采集证据（命令输出、diff、日志）。系统自动收集，未经人工复核。 */
  | 'AUTO_EVIDENCED'
  /** 本地验收官复核。有现场访问权限的人员复核。 */
  | 'LOCAL_REVIEWED'
  /** Codex 现场审计。Codex 进入真实 project_root 现场执行审计。 */
  | 'CODEX_REVIEWED'
  /** 甲方最终接收。人类 owner 最终确认。 */
  | 'OWNER_ACCEPTED';

/** 证据等级优先序（数字越大越可信） */
export const EVIDENCE_LEVEL_RANK: Record<TiandaoEvidenceLevel, number> = {
  SELF_REPORTED: 0,
  AUTO_EVIDENCED: 1,
  LOCAL_REVIEWED: 2,
  CODEX_REVIEWED: 3,
  OWNER_ACCEPTED: 4,
};

/** 判断等级 A 是否高于等于等级 B */
export function isEvidenceLevelAtLeast(
  level: TiandaoEvidenceLevel,
  minimum: TiandaoEvidenceLevel
): boolean {
  return EVIDENCE_LEVEL_RANK[level] >= EVIDENCE_LEVEL_RANK[minimum];
}
