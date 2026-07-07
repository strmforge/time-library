/**
 * 公共 AuditEvent — 共用合同
 * Tiandao AuditEvent Schema
 *
 * 设计口径：
 *   公共规则是跨系统的中性公共规则层，随着各系统实践而完善。
 *   各系统共用一套公共规则合同，只使用自己需要的公共规则面。
 *
 *   AuditEvent 是跨系统通用的审计事件信封。
 *   不归属于任何单个子系统。
 *   归属公共规则层。
 *
 *   旧系统内的同名类型只应作为兼容 re-export，不拥有公共合同。
 */

/** 审计动作类型 */
export type AuditAction =
  | 'task.create'
  | 'task.execute'
  | 'task.complete'
  | 'task.fail'
  | 'verdict.create'
  | 'verdict.approve'
  | 'verdict.reject'
  | 'role.create'
  | 'role.assign'
  | 'role.revoke'
  | 'context.assemble'
  | 'context.inject'
  | 'evidence.collect'
  | 'source_ref.track'
  | 'connection.open'
  | 'connection.close'
  | 'registry.register'
  | 'registry.unregister';

/** 审计事件结果 */
export type AuditResult = 'success' | 'failure' | 'pending' | 'partial';

/** AuditEvent — 公共规则共用审计事件 */
export interface TiandaoAuditEvent {
  /** 事件 ID */
  event_id: string;
  /** 时间戳 */
  timestamp: string; // ISO datetime
  /** 执行者 */
  actor: string;
  /** 动作类型 */
  action: AuditAction;
  /** 目标对象 */
  target: string;
  /** 执行结果 */
  result: AuditResult;
  /** 详情 */
  details?: Record<string, unknown>;
  /** 来源 IP */
  source_ip?: string;
  /** User Agent */
  user_agent?: string;
}

/** 创建审计事件的工厂函数 */
export function createAuditEvent(params: {
  eventId?: string;
  actor: string;
  action: AuditAction;
  target: string;
  result: AuditResult;
  details?: Record<string, unknown>;
  sourceIp?: string;
  userAgent?: string;
}): TiandaoAuditEvent {
  return {
    event_id: params.eventId || `audit_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    timestamp: new Date().toISOString(),
    actor: params.actor,
    action: params.action,
    target: params.target,
    result: params.result,
    details: params.details,
    source_ip: params.sourceIp,
    user_agent: params.userAgent,
  };
}
