/**
 * 天道 Memory Routing — 公共合同
 * Tiandao active-memory routing, conversation evidence, and local sync contracts.
 */

export const TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT = 'tiandao_active_memory_routing.v1';
export const TIANDAO_CONVERSATION_EVIDENCE_CONTRACT = 'tiandao_conversation_evidence.v1';
export const TIANDAO_CONTINUOUS_LOCAL_SYNC_CONTRACT = 'tiandao_continuous_local_sync.v1';

export type TiandaoActiveMemoryLayer =
  | 'current_window'
  | 'current_session'
  | 'same_project_workspace'
  | 'same_workstream_task'
  | 'stable_user_preferences_tool_facts'
  | 'explicit_raw_pool_global_only_when_requested';

export const ACTIVE_MEMORY_DEFAULT_RECALL_ORDER: readonly TiandaoActiveMemoryLayer[] = [
  'current_window',
  'current_session',
  'same_project_workspace',
  'same_workstream_task',
  'stable_user_preferences_tool_facts',
  'explicit_raw_pool_global_only_when_requested',
] as const;

export const WINDOW_IDENTITY_FIELDS = ['canonical_window_id', 'session_id'] as const;
export const CROSS_WINDOW_RECALL_FLAG = 'allow_cross_window_recall';
export const COMPLETE_CONVERSATION_REQUIRED_ROLES = ['user', 'assistant'] as const;
export const DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS = 250;
export const CONTINUOUS_SYNC_MODE = 'file_event_or_low_latency_loop';

export interface TiandaoActiveMemoryRoutingContract {
  contract: typeof TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT;
  default_recall_order: readonly TiandaoActiveMemoryLayer[];
  window_identity_fields: readonly string[];
  cross_window_flag: typeof CROSS_WINDOW_RECALL_FLAG;
  missing_window_identity_is_not_no_memory: boolean;
  raw_pool_or_global_policy: 'explicit_only';
}

export interface TiandaoConversationEvidenceVerdict {
  contract: typeof TIANDAO_CONVERSATION_EVIDENCE_CONTRACT;
  complete_conversation_candidate: boolean;
  required_roles: readonly string[];
  roles_observed: readonly string[];
  assistant_reply_persistence: 'verified' | 'unverified';
  current_window_memory_registerable: boolean;
  not_no_memory: boolean;
  partial_source_policy?: 'evidence_only_not_current_window_memory';
}

export interface TiandaoContinuousLocalSyncContract {
  contract: typeof TIANDAO_CONTINUOUS_LOCAL_SYNC_CONTRACT;
  install_scan_only: false;
  mode: typeof CONTINUOUS_SYNC_MODE;
  default_target_latency_milliseconds: number;
  event_driven_preferred: true;
  fallback_policy: 'low_latency_poll';
}
