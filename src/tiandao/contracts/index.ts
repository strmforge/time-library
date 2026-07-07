/**
 * Tiandao Contracts Public API.
 *
 * Current orchestration system mirror exports SourceRef, ContextPackage, AuditEvent,
 * EvidenceLevel, and model identity contracts. ShadowLayer was removed from
 * the active orchestration system implementation on 2026-05-27.
 */

export {
  type TiandaoSourceRef,
  type ArtifactType,
  createSourceRef,
  canReadSourceRefContent,
} from './source-ref.js';

export {
  type TiandaoContextPackage,
  type TiandaoIntentMode,
  type TiandaoMemoryContextMode,
  CONTEXT_PACKAGE_SCHEMA_ID,
  CONTEXT_PACKAGE_FORBIDDEN_FIELDS,
  MEMORY_CONTEXT_TTL,
  createTiandaoContextPackage,
} from './context-package.js';

export {
  type TiandaoActiveMemoryLayer,
  type TiandaoActiveMemoryRoutingContract,
  type TiandaoConversationEvidenceVerdict,
  type TiandaoContinuousLocalSyncContract,
  type TiandaoMemoryExperienceLayer,
  type TiandaoMemoryExperienceLayeringContract,
  type TiandaoTimeOriginContract,
  type TiandaoTimeOriginStatus,
  type TiandaoTimeRiverContract,
  type TiandaoTimeRiverSedimentContract,
  type TiandaoTimeRiverSedimentStatus,
  type TiandaoTimeRiverStage,
  ACTIVE_MEMORY_DEFAULT_RECALL_ORDER,
  COMPLETE_CONVERSATION_REQUIRED_ROLES,
  CONTINUOUS_SYNC_MODE,
  CROSS_WINDOW_RECALL_FLAG,
  DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS,
  MEMORY_EXPERIENCE_LAYERS,
  TIME_RIVER_REQUIRED_ANCHORS,
  TIME_RIVER_SEDIMENT_LAYERS,
  TIME_RIVER_SEDIMENT_STATUSES,
  TIME_RIVER_STAGES,
  TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
  TIANDAO_CONTINUOUS_LOCAL_SYNC_CONTRACT,
  TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
  TIANDAO_MEMORY_EXPERIENCE_LAYERING_CONTRACT,
  TIANDAO_TIME_ORIGIN_CONTRACT,
  TIANDAO_TIME_RIVER_CONTRACT,
  TIANDAO_TIME_RIVER_SEDIMENT_CONTRACT,
  WINDOW_IDENTITY_FIELDS,
} from './memory-routing.js';

export {
  type TiandaoAuditEvent,
  type AuditAction,
  type AuditResult,
  createAuditEvent,
} from './audit-event.js';

export {
  type TiandaoEvidenceLevel,
  EVIDENCE_LEVEL_RANK,
  isEvidenceLevelAtLeast,
} from './evidence-level.js';

export {
  type TiandaoModelAsset,
  type TiandaoModelConnectionAsset,
  type TiandaoModelEndpointRef,
  type TiandaoModelEntryRef,
  providerNameForEndpoint,
  apiModeForEndpoint,
  connectionKeyForEndpoint,
  runtimeModelIdFor,
  assetIdFor,
  buildTiandaoModelAssets,
  buildTiandaoModelConnections,
  resolveRuntimeModelId,
  resolveRuntimeModelIds,
} from './model.js';
