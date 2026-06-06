/**
 * Tiandao model contract.
 *
 * This layer owns cross-system model identity:
 * endpoint/provider + runtime model id + model asset id.
 * Platform-specific file writes stay in thin adapters.
 */

export interface TiandaoModelEndpointRef {
  id: string;
  name?: string;
  providerName?: string;
  providerType?: string;
  baseUrl?: string;
  apiMode?: string;
  platform?: string;
  createdAt?: string;
}

export interface TiandaoModelEntryRef {
  id: string;
  endpointId: string;
  modelName: string;
  displayName?: string;
  capabilities?: string[];
  isVision?: boolean;
  isDefault?: boolean;
  discoveredAt?: string;
}

export interface TiandaoModelAsset extends TiandaoModelEntryRef {
  assetId: string;
  runtimeModelId: string;
  providerName: string;
  endpointName: string;
  endpointBaseUrl: string;
  connectionKey: string;
  platform?: string;
  modelKey: string;
  isAmbiguousName: boolean;
  supportsImageGeneration: boolean;
  isSelectable: boolean;
}

export interface TiandaoModelConnectionAsset {
  connectionKey: string;
  /** Provider/vendor id, aligned with CC-Switch's provider identifier. */
  providerName: string;
  /** Provider/vendor display name. Model aliases live on TiandaoModelEntryRef.displayName. */
  displayName: string;
  note?: string;
  endpointBaseUrl: string;
  apiMode: string;
  providerTypes: string[];
  platforms: string[];
  endpointIds: string[];
  endpointNames: string[];
  modelAssetIds: string[];
  modelCount: number;
  selectableModelCount: number;
  hasAmbiguousModels: boolean;
  createdAt?: string;
}

export function endpointSupportsModelSelection(endpoint: TiandaoModelEndpointRef | undefined): boolean {
  if (!endpoint?.platform) return true;
  return endpoint.platform === 'openclaw' || endpoint.platform === 'hermes';
}

function stripHermesPrefix(name: string): string {
  return name.startsWith('hermes/') ? name.slice('hermes/'.length) : name;
}

function splitEndpointModelId(id: string, endpointId: string): string | null {
  const prefix = `${endpointId}/`;
  return id.startsWith(prefix) ? id.slice(prefix.length) : null;
}

export function providerNameForEndpoint(endpoint: TiandaoModelEndpointRef): string {
  return endpoint.providerName || stripHermesPrefix(endpoint.name || endpoint.id);
}

export function apiModeForEndpoint(endpoint: TiandaoModelEndpointRef): string {
  const explicit = String(endpoint.apiMode || '').trim().toLowerCase();
  if (explicit) return explicit;

  const providerType = String(endpoint.providerType || '').trim().toLowerCase();
  if (providerType === 'ollama') return 'ollama';
  if (providerType === 'anthropic') return 'anthropic-messages';
  if (providerType === 'gemini') return 'gemini';

  return 'openai-completions';
}

export function connectionKeyForEndpoint(endpoint: TiandaoModelEndpointRef): string {
  const provider = providerNameForEndpoint(endpoint).trim().toLowerCase();
  const baseUrl = String(endpoint.baseUrl || '').trim().replace(/\/$/, '').toLowerCase();
  const apiMode = apiModeForEndpoint(endpoint);
  return [provider || 'unknown', baseUrl || 'local', apiMode].filter(Boolean).join('@');
}

export function runtimeModelIdFor(
  endpoint: TiandaoModelEndpointRef,
  model: TiandaoModelEntryRef,
): string {
  const providerName = providerNameForEndpoint(endpoint);
  const fromId = splitEndpointModelId(model.id, endpoint.id);
  const rawModelName = String(model.modelName || fromId || model.id || '').trim();

  if (!rawModelName) return '';
  if (rawModelName.includes('/')) return rawModelName;

  if (endpoint.platform === 'openclaw') {
    return `${providerName}/${rawModelName}`;
  }

  if (endpoint.platform === 'hermes') {
    if (model.id.includes('/') && !model.id.startsWith(`${endpoint.id}/`)) {
      return model.id;
    }
    return `${providerName}/${rawModelName}`;
  }

  return rawModelName;
}

export function assetIdFor(
  endpoint: TiandaoModelEndpointRef,
  model: TiandaoModelEntryRef,
): string {
  const runtimeModelId = runtimeModelIdFor(endpoint, model);
  return `${endpoint.id}/${runtimeModelId || model.modelName || model.id}`;
}

export function buildTiandaoModelAssets<
  TEndpoint extends TiandaoModelEndpointRef,
  TModel extends TiandaoModelEntryRef,
>(
  endpoints: TEndpoint[],
  models: TModel[],
): Array<TModel & TiandaoModelAsset> {
  const endpointById = new Map(endpoints.map(ep => [ep.id, ep]));
  const nameCounts = new Map<string, number>();

  for (const model of models) {
    const key = model.modelName || model.id;
    nameCounts.set(key, (nameCounts.get(key) ?? 0) + 1);
  }

  return models.map(model => {
    const endpoint = model.endpointId ? endpointById.get(model.endpointId) : undefined;
    const fallbackEndpoint: TiandaoModelEndpointRef = endpoint ?? {
      id: model.endpointId || 'unknown',
      name: model.endpointId || 'unknown',
      baseUrl: '',
      platform: undefined,
      createdAt: model.discoveredAt || new Date(0).toISOString(),
    };
    const runtimeModelId = runtimeModelIdFor(fallbackEndpoint, model) || model.modelName || model.id;
    const providerName = providerNameForEndpoint(fallbackEndpoint);
    const capabilities = model.capabilities ?? [];

    return {
      ...model,
      assetId: assetIdFor(fallbackEndpoint, model),
      runtimeModelId,
      providerName,
      endpointName: fallbackEndpoint.name || fallbackEndpoint.id,
      endpointBaseUrl: fallbackEndpoint.baseUrl || '',
      connectionKey: connectionKeyForEndpoint(fallbackEndpoint),
      platform: fallbackEndpoint.platform,
      modelKey: model.modelName,
      isAmbiguousName: (nameCounts.get(model.modelName || model.id) ?? 0) > 1,
      supportsImageGeneration: capabilities.includes('image_generation'),
      isSelectable: endpointSupportsModelSelection(endpoint),
    };
  });
}

function pushUnique(list: string[], value: string | undefined): void {
  const normalized = String(value || '').trim();
  if (!normalized || list.includes(normalized)) return;
  list.push(normalized);
}

function uniqueValues(values: Array<string | undefined>): string[] {
  const result: string[] = [];
  for (const value of values) pushUnique(result, value);
  return result;
}

function uniqueModelCount(models: TiandaoModelAsset[]): number {
  return uniqueValues(models.map(model => model.modelKey || model.modelName || model.runtimeModelId)).length;
}

export function buildTiandaoModelConnections<
  TEndpoint extends TiandaoModelEndpointRef,
  TModel extends TiandaoModelEntryRef,
>(
  endpoints: TEndpoint[],
  models: TModel[],
): TiandaoModelConnectionAsset[] {
  const assets = buildTiandaoModelAssets(endpoints, models);
  const assetsByConnection = new Map<string, typeof assets>();
  for (const asset of assets) {
    const list = assetsByConnection.get(asset.connectionKey) ?? [];
    list.push(asset);
    assetsByConnection.set(asset.connectionKey, list);
  }

  const byKey = new Map<string, TiandaoModelConnectionAsset>();
  for (const endpoint of endpoints) {
    const connectionKey = connectionKeyForEndpoint(endpoint);
      const endpointAssets = assetsByConnection.get(connectionKey) ?? [];
      const selectableEndpointAssets = endpointAssets.filter(asset => asset.isSelectable);
      const existing = byKey.get(connectionKey);
      if (!existing) {
        const modelAssetIds = uniqueValues(endpointAssets.map(asset => asset.assetId));
        const modelCount = uniqueModelCount(endpointAssets);
        const selectableModelCount = uniqueModelCount(selectableEndpointAssets);
        byKey.set(connectionKey, {
        connectionKey,
        providerName: providerNameForEndpoint(endpoint),
        displayName: providerNameForEndpoint(endpoint),
        endpointBaseUrl: String(endpoint.baseUrl || '').replace(/\/$/, ''),
        apiMode: apiModeForEndpoint(endpoint),
        providerTypes: endpoint.providerType ? [endpoint.providerType] : [],
        platforms: endpoint.platform ? [endpoint.platform] : [],
        endpointIds: [endpoint.id],
        endpointNames: endpoint.name ? [endpoint.name] : [endpoint.id],
          modelAssetIds,
          modelCount,
          selectableModelCount,
          hasAmbiguousModels: endpointAssets.some(asset => asset.isAmbiguousName),
          createdAt: endpoint.createdAt,
        });
      continue;
    }

    pushUnique(existing.providerTypes, endpoint.providerType);
    pushUnique(existing.platforms, endpoint.platform);
    pushUnique(existing.endpointIds, endpoint.id);
    pushUnique(existing.endpointNames, endpoint.name || endpoint.id);
    for (const asset of endpointAssets) pushUnique(existing.modelAssetIds, asset.assetId);
    const existingAssets = assets.filter(asset => asset.connectionKey === connectionKey);
    const selectableExistingAssets = existingAssets.filter(asset => asset.isSelectable);
    existing.modelCount = uniqueModelCount(existingAssets);
    existing.selectableModelCount = uniqueModelCount(selectableExistingAssets);
    existing.hasAmbiguousModels ||= endpointAssets.some(asset => asset.isAmbiguousName);
    if (!existing.createdAt || (endpoint.createdAt && endpoint.createdAt < existing.createdAt)) {
      existing.createdAt = endpoint.createdAt;
    }
  }

  return Array.from(byKey.values()).sort((a, b) =>
    a.displayName.localeCompare(b.displayName) ||
    a.endpointBaseUrl.localeCompare(b.endpointBaseUrl)
  );
}

export function resolveRuntimeModelId(
  value: string | null | undefined,
  endpoints: TiandaoModelEndpointRef[],
  models: TiandaoModelEntryRef[],
): string | null {
  const raw = String(value ?? '').trim();
  if (!raw) return null;

  const assets = buildTiandaoModelAssets(endpoints, models);

  const direct = assets.find(asset =>
    asset.assetId === raw ||
    asset.runtimeModelId === raw ||
    asset.id === raw,
  );
  if (direct) return direct.runtimeModelId;

  const byModelName = assets.filter(asset => asset.modelName === raw);
  if (byModelName.length === 1) return byModelName[0].runtimeModelId;

  return raw;
}

export function resolveRuntimeModelIds(
  values: unknown,
  endpoints: TiandaoModelEndpointRef[],
  models: TiandaoModelEntryRef[],
): string[] {
  if (!Array.isArray(values)) return [];
  const result: string[] = [];
  const seen = new Set<string>();
  for (const item of values) {
    const resolved = resolveRuntimeModelId(String(item ?? ''), endpoints, models);
    if (!resolved || seen.has(resolved)) continue;
    seen.add(resolved);
    result.push(resolved);
  }
  return result;
}
