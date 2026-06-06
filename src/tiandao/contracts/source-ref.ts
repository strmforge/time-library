/**
 * 天道 SourceRef — 公共合同
 * Tiandao SourceRef Public Contract
 *
 * 来源：tiandao/boundary.py
 * 天道 v0 R04: Boundary Protocol
 *
 * SourceRef 是外部参考标记，不触发记忆写入。
 * 只携带溯源元信息，可按授权读取原始内容。
 */

export type ArtifactType = 'session' | 'file' | 'api_response' | 'memory';

/** SourceRef — 外部参考标记 */
export interface TiandaoSourceRef {
  ref_id: string;
  source_system: string;
  artifact_type: ArtifactType;
  /** 文件路径或 API endpoint */
  ref_path?: string;
  /** 具体 artifact 标识 */
  artifact_id?: string;
  /** ISO datetime */
  captured_at?: string;
  /** 是否需要授权才能读取内容 */
  auth_required?: boolean;
  /** 授权是否已授予 */
  auth_granted?: boolean;
}

/** 创建 SourceRef 的工厂函数 */
export function createSourceRef(params: {
  refId: string;
  sourceSystem: string;
  artifactType: ArtifactType;
  refPath?: string;
  artifactId?: string;
  capturedAt?: string;
  authRequired?: boolean;
}): TiandaoSourceRef {
  return {
    ref_id: params.refId,
    source_system: params.sourceSystem,
    artifact_type: params.artifactType,
    ref_path: params.refPath,
    artifact_id: params.artifactId,
    captured_at: params.capturedAt || new Date().toISOString(),
    auth_required: params.authRequired ?? false,
    auth_granted: false,
  };
}

/** 判断是否可以读取 SourceRef 内容 */
export function canReadSourceRefContent(ref: TiandaoSourceRef): boolean {
  if (!ref.auth_required) return true;
  return ref.auth_granted === true;
}
