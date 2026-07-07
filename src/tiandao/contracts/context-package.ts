/**
 * 公共 ContextPackage — 公共合同
 * Tiandao ContextPackage Schema v1
 *
 * 来源：tiandao/schemas/context_package.schema.json
 * 公共规则 v0 R04: Boundary Protocol
 *
 * 上下文服务公共合同。
 * 描述：intent_mode / memory_context_mode / memory_write 等字段的语义。
 */

/** 意图模式 */
export type TiandaoIntentMode =
  | 'summary'    // 摘要模式
  | 'evidence'  // 证据模式
  | 'verbatim'   // 原文模式
  | 'audit';    // 审计模式

/** 记忆上下文模式 */
export type TiandaoMemoryContextMode =
  | 'mode_a'  // Mode A: 执行上下文，TTL=1天，无需授权
  | 'mode_b'  // Mode B: 学习影子，TTL=30天，无需授权
  | 'mode_c'; // Mode C: 原始回放，按需，需授权

/** TTL 秒数常量 */
export const MEMORY_CONTEXT_TTL: Record<TiandaoMemoryContextMode, number> = {
  mode_a: 86400,     // 1 day
  mode_b: 2592000,   // 30 days
  mode_c: -1,        // 按需，无穷
};

/** ContextPackage Schema 版本 */
export const CONTEXT_PACKAGE_SCHEMA_ID = 'tiandao_context_package.v1';

/** 禁止进入 ContextPackage 的字段 */
export const CONTEXT_PACKAGE_FORBIDDEN_FIELDS: readonly string[] = [
  'token', 'tokens', 'api_key', 'password', 'secret', 'private_key',
  'raw_fulltext', 'raw_content', 'final_answer', 'final_strategy',
  'golden_answer', 'golden_answer_text', 'message_content',
];

/**
 * ContextPackage — 公共规则公共上下文合同
 *
 * 核心原则：
 * - memory_write 必须为 false（不得写 memory，除非显式授权）
 * - 禁止字段不得进入 package
 * - source_refs 是外部参考标记，不携带原始内容
 */
export interface TiandaoContextPackage {
  /** Schema 版本标识 */
  schema: 'tiandao_context_package.v1';
  /** SHA256 hash — query 明文不存储 */
  query_hash: string;
  /** 来源系统：openclaw / hermes / codex / local_files */
  source_system?: string;
  /** 规范窗口 ID */
  canonical_window_id?: string;
  /** 会话 ID */
  session_id?: string;
  /** 意图模式 */
  intent_mode: TiandaoIntentMode;
  /** 记忆上下文模式 */
  memory_context_mode: TiandaoMemoryContextMode;
  /** TTL 秒数：Mode A=86400, Mode B=2592000, Mode C=-1 */
  ttl_seconds: number;
  /** Matched memory entries. */
  matched_memories?: object[];
  /** 外部参考标记（不触发记忆写入） */
  source_refs?: import('./source-ref.js').TiandaoSourceRef[];
  /** Active-memory routing public contract id */
  active_memory_routing_contract?: string;
  /** Active routing layers used to assemble this package */
  active_layers_used?: import('./memory-routing.js').TiandaoActiveMemoryLayer[];
  /** Whether current-window binding was applied */
  current_window_binding_applied?: boolean;
  /** Whether this package reads across windows/surfaces */
  cross_window_read?: boolean;
  /** Whether cross-window read was explicitly allowed */
  cross_window_read_allowed?: boolean;
  /** 是否强制 scope 隔离 */
  scope_enforced?: boolean;
  /** 是否阻止注入 */
  injection_blocked?: boolean;
  /** 阻止原因 */
  block_reason?: string | null;
  /** Tiandao: 不得写 memory（必须为 false） */
  memory_write: boolean;
  /** 组装时间 */
  assembled_at?: string;
}

/** 创建 ContextPackage 的工厂函数 */
export function createTiandaoContextPackage(params: {
  queryHash: string;
  intentMode: TiandaoIntentMode;
  memoryContextMode: TiandaoMemoryContextMode;
  sourceSystem?: string;
  canonicalWindowId?: string;
  sessionId?: string;
  matchedMemories?: object[];
  sourceRefs?: import('./source-ref.js').TiandaoSourceRef[];
  activeMemoryRoutingContract?: string;
  activeLayersUsed?: import('./memory-routing.js').TiandaoActiveMemoryLayer[];
  currentWindowBindingApplied?: boolean;
  crossWindowRead?: boolean;
  crossWindowReadAllowed?: boolean;
}): TiandaoContextPackage {
  return {
    schema: CONTEXT_PACKAGE_SCHEMA_ID,
    query_hash: params.queryHash,
    source_system: params.sourceSystem,
    canonical_window_id: params.canonicalWindowId,
    session_id: params.sessionId,
    intent_mode: params.intentMode,
    memory_context_mode: params.memoryContextMode,
    ttl_seconds: MEMORY_CONTEXT_TTL[params.memoryContextMode],
    matched_memories: params.matchedMemories,
    source_refs: params.sourceRefs,
    active_memory_routing_contract: params.activeMemoryRoutingContract,
    active_layers_used: params.activeLayersUsed,
    current_window_binding_applied: params.currentWindowBindingApplied ?? false,
    cross_window_read: params.crossWindowRead ?? false,
    cross_window_read_allowed: params.crossWindowReadAllowed ?? false,
    scope_enforced: true,
    injection_blocked: false,
    block_reason: null,
    memory_write: false,
    assembled_at: new Date().toISOString(),
  };
}
