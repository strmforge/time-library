/**
 * 公共 Memory Routing — 公共合同
 * Tiandao active-memory routing, conversation evidence, and local sync contracts.
 */

export const TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT = 'tiandao_active_memory_routing.v1';
export const TIANDAO_CONVERSATION_EVIDENCE_CONTRACT = 'tiandao_conversation_evidence.v1';
export const TIANDAO_CONTINUOUS_LOCAL_SYNC_CONTRACT = 'tiandao_continuous_local_sync.v1';
export const TIANDAO_MEMORY_EXPERIENCE_LAYERING_CONTRACT = 'tiandao_memory_experience_layering.v1';
export const TIANDAO_TIME_ORIGIN_CONTRACT = 'tiandao_time_origin.v1';
export const TIANDAO_TIME_RIVER_CONTRACT = 'tiandao_time_river.v1';
export const TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT = 'tiandao_time_river_sediment.v1';

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
export const DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS = 5000;
export const CONTINUOUS_SYNC_MODE = 'file_event_or_low_latency_loop';

export type TiandaoMemoryExperienceLayer = 'raw' | 'zhiyi' | 'xingce' | 'toolbook';

export const MEMORY_EXPERIENCE_LAYERS: readonly TiandaoMemoryExperienceLayer[] = [
  'raw',
  'zhiyi',
  'xingce',
  'toolbook',
] as const;

export type TiandaoTimeRiverStage =
  | 'source_event'
  | 'raw_preservation'
  | 'experience_sedimentation'
  | 'context_delivery'
  | 'audit_receipt'
  | 'replay_validation'
  | 'errata_or_supersession';

export const TIME_RIVER_STAGES: readonly TiandaoTimeRiverStage[] = [
  'source_event',
  'raw_preservation',
  'experience_sedimentation',
  'context_delivery',
  'audit_receipt',
  'replay_validation',
  'errata_or_supersession',
] as const;

export const TIME_RIVER_REQUIRED_ANCHORS = [
  'event_time',
  'source_refs',
  'library_id',
  'lifecycle_status',
  'audit_event',
] as const;

export const TIME_RIVER_SEDIMENT_LAYERS = [
  'raw',
  'zhiyi',
  'xingce',
  'toolbook',
  'errata',
] as const;

export const TIME_RIVER_SEDIMENT_STATUSES = [
  'origin_linked',
  'source_refs_only',
  'origin_missing_candidate',
  'raw_unavailable_untrusted',
] as const;

export type TiandaoTimeOriginStatus =
  | 'origin_witnessed'
  | 'lost_source'
  | 'lost_raw'
  | 'origin_unavailable';

export type TiandaoTimeRiverSedimentStatus =
  | 'origin_linked'
  | 'source_refs_only'
  | 'origin_missing_candidate'
  | 'raw_unavailable_untrusted';

export interface TiandaoTimeOriginContract {
  contract: typeof TIANDAO_TIME_ORIGIN_CONTRACT;
  zh_name: '时间起源';
  role: 'neutral_raw_origin_contract';
  origin_layer: 'raw';
  origin_event_required: true;
  no_raw_no_river: true;
  raw_authority_policy: 'raw_source_text_is_highest_authority';
  origin_event_policy: 'time_origin_begins_when_raw_is_witnessed';
  derived_sediment_policy: 'derived_sediment_must_reference_origin';
  local_runtime_policy: 'each_runtime_has_first_witnessed_raw_event';
  multi_machine_policy: 'source_streams_merge_not_overwrite';
  platform_policy: 'platforms_are_inlets_not_origin';
  river_endpoint_policy: 'time_river_has_no_endpoint';
  origin_statuses: readonly TiandaoTimeOriginStatus[];
  lost_source_label: '遗失源';
  lost_raw_label: '遗失 raw';
}

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

export interface TiandaoMemoryExperienceLayeringContract {
  contract: typeof TIANDAO_MEMORY_EXPERIENCE_LAYERING_CONTRACT;
  all_queryable_layers: readonly TiandaoMemoryExperienceLayer[];
  platform_is_not_memory_layer: true;
  platform_capability_policy: 'platforms_may_use_any_subset_of_neutral_capabilities';
  classification_rule: 'content_signal_not_platform_identity';
  raw_source_policy: 'derived_zhiyi_xingce_toolbook_must_keep_source_refs';
  adapter_boundary_policy: 'platform_private_protocol_stays_in_thin_adapter';
  platform_mapping_policy: 'outside_tiandao_in_adapter_or_product_layer';
  global_recall_policy: 'explicit_only';
}

export interface TiandaoTimeRiverContract {
  contract: typeof TIANDAO_TIME_RIVER_CONTRACT;
  zh_name: '时间长河';
  role: 'neutral_temporal_memory_continuity_contract';
  time_origin_contract: typeof TIANDAO_TIME_ORIGIN_CONTRACT;
  sediment_contract: typeof TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT;
  stages: readonly TiandaoTimeRiverStage[];
  sediment_layers: readonly string[];
  required_anchors: readonly string[];
  origin_policy: 'time_river_begins_at_raw_origin_event';
  source_ref_policy: 'every_derived_sediment_must_return_to_source_refs_or_state_unavailable';
  library_identity_policy: 'stable_collection_identity_required_for_recallable_sediment';
  lifecycle_policy: 'candidate_pending_review_adopted_deprecated_superseded';
  audit_policy: 'read_write_delivery_and_scope_decisions_emit_receipts';
  context_delivery_policy: 'context_packages_carry_scope_ttl_purpose_and_source_refs';
  replay_validation_metrics: readonly string[];
  platform_policy: 'platforms_are_inlets_not_river_laws';
  platform_capability_policy: 'platforms_may_use_any_subset_of_neutral_capabilities';
  adapter_boundary_policy: 'platform_private_protocol_stays_in_thin_adapter';
  raw_authority_policy: 'raw_source_text_is_highest_authority';
  summary_policy: 'summaries_are_navigation_not_source_replacement';
  time_order_policy: 'events_remain_orderable_by_event_time_and_audit_time';
  endpoint_policy: 'time_river_has_no_endpoint';
  global_recall_policy: 'explicit_only';
}

export interface TiandaoTimeRiverSedimentContract {
  contract: typeof TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT;
  zh_name: '时间长河沉积链';
  role: 'neutral_derived_memory_origin_link_contract';
  time_origin_contract: typeof TIANDAO_TIME_ORIGIN_CONTRACT;
  time_river_contract: typeof TIANDAO_TIME_RIVER_CONTRACT;
  sediment_layers: readonly string[];
  sediment_statuses: readonly TiandaoTimeRiverSedimentStatus[];
  trusted_status: 'origin_linked';
  candidate_statuses: readonly TiandaoTimeRiverSedimentStatus[];
  origin_link_policy: 'derived_sediment_must_reference_origin';
  source_ref_policy: 'source_refs_are_required_but_not_a_source_replacement';
  raw_authority_policy: 'raw_source_text_is_highest_authority';
  summary_policy: 'summaries_are_navigation_not_source_replacement';
  write_policy: 'read_only_descriptor_no_memory_write';
  platform_policy: 'platforms_are_inlets_not_river_laws';
  global_recall_policy: 'explicit_only';
}
