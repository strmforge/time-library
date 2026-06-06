"""Neutral Tiandao model identity contract merged into the Python mirror."""

from __future__ import annotations

from typing import Any


def endpoint_supports_model_selection(endpoint: dict[str, Any] | None) -> bool:
    if not endpoint or not endpoint.get("platform"):
        return True
    return endpoint.get("platform") in {"openclaw", "hermes"}


def _strip_hermes_prefix(name: str) -> str:
    return name[len("hermes/") :] if name.startswith("hermes/") else name


def _split_endpoint_model_id(model_id: str, endpoint_id: str) -> str | None:
    prefix = f"{endpoint_id}/"
    return model_id[len(prefix) :] if model_id.startswith(prefix) else None


def provider_name_for_endpoint(endpoint: dict[str, Any]) -> str:
    return str(endpoint.get("providerName") or _strip_hermes_prefix(str(endpoint.get("name") or endpoint.get("id") or "")))


def api_mode_for_endpoint(endpoint: dict[str, Any]) -> str:
    explicit = str(endpoint.get("apiMode") or "").strip().lower()
    if explicit:
        return explicit

    provider_type = str(endpoint.get("providerType") or "").strip().lower()
    if provider_type == "ollama":
        return "ollama"
    if provider_type == "anthropic":
        return "anthropic-messages"
    if provider_type == "gemini":
        return "gemini"

    return "openai-completions"


def connection_key_for_endpoint(endpoint: dict[str, Any]) -> str:
    provider = provider_name_for_endpoint(endpoint).strip().lower()
    base_url = str(endpoint.get("baseUrl") or "").strip().rstrip("/").lower()
    api_mode = api_mode_for_endpoint(endpoint)
    return "@".join(part for part in [provider or "unknown", base_url or "local", api_mode] if part)


def runtime_model_id_for(endpoint: dict[str, Any], model: dict[str, Any]) -> str:
    provider_name = provider_name_for_endpoint(endpoint)
    from_id = _split_endpoint_model_id(str(model.get("id") or ""), str(endpoint.get("id") or ""))
    raw_model_name = str(model.get("modelName") or from_id or model.get("id") or "").strip()

    if not raw_model_name:
        return ""
    if "/" in raw_model_name:
        return raw_model_name

    if endpoint.get("platform") in {"openclaw", "hermes"}:
        if endpoint.get("platform") == "hermes":
            model_id = str(model.get("id") or "")
            endpoint_id = str(endpoint.get("id") or "")
            if "/" in model_id and not model_id.startswith(f"{endpoint_id}/"):
                return model_id
        return f"{provider_name}/{raw_model_name}"

    return raw_model_name


def asset_id_for(endpoint: dict[str, Any], model: dict[str, Any]) -> str:
    runtime_model_id = runtime_model_id_for(endpoint, model)
    return f"{endpoint.get('id')}/{runtime_model_id or model.get('modelName') or model.get('id')}"


def _push_unique(items: list[str], value: Any) -> None:
    normalized = str(value or "").strip()
    if normalized and normalized not in items:
        items.append(normalized)


def _unique_values(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        _push_unique(result, value)
    return result


def _unique_model_count(models: list[dict[str, Any]]) -> int:
    return len(_unique_values([m.get("modelKey") or m.get("modelName") or m.get("runtimeModelId") for m in models]))


def build_tiandao_model_assets(
    endpoints: list[dict[str, Any]],
    models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    endpoint_by_id = {endpoint.get("id"): endpoint for endpoint in endpoints}
    name_counts: dict[str, int] = {}
    for model in models:
        key = str(model.get("modelName") or model.get("id") or "")
        name_counts[key] = name_counts.get(key, 0) + 1

    assets: list[dict[str, Any]] = []
    for model in models:
        endpoint = endpoint_by_id.get(model.get("endpointId"))
        fallback_endpoint = endpoint or {
            "id": model.get("endpointId") or "unknown",
            "name": model.get("endpointId") or "unknown",
            "baseUrl": "",
            "platform": None,
            "createdAt": model.get("discoveredAt") or "1970-01-01T00:00:00.000Z",
        }
        runtime_model_id = runtime_model_id_for(fallback_endpoint, model) or str(model.get("modelName") or model.get("id") or "")
        provider_name = provider_name_for_endpoint(fallback_endpoint)
        capabilities = model.get("capabilities") if isinstance(model.get("capabilities"), list) else []
        model_key = str(model.get("modelName") or "")
        asset = dict(model)
        asset.update({
            "assetId": asset_id_for(fallback_endpoint, model),
            "runtimeModelId": runtime_model_id,
            "providerName": provider_name,
            "endpointName": fallback_endpoint.get("name") or fallback_endpoint.get("id"),
            "endpointBaseUrl": fallback_endpoint.get("baseUrl") or "",
            "connectionKey": connection_key_for_endpoint(fallback_endpoint),
            "platform": fallback_endpoint.get("platform"),
            "modelKey": model_key,
            "isAmbiguousName": name_counts.get(model_key or str(model.get("id") or ""), 0) > 1,
            "supportsImageGeneration": "image_generation" in capabilities,
            "isSelectable": endpoint_supports_model_selection(endpoint),
        })
        assets.append(asset)
    return assets


def build_tiandao_model_connections(
    endpoints: list[dict[str, Any]],
    models: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    assets = build_tiandao_model_assets(endpoints, models)
    assets_by_connection: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        assets_by_connection.setdefault(str(asset.get("connectionKey")), []).append(asset)

    by_key: dict[str, dict[str, Any]] = {}
    for endpoint in endpoints:
        connection_key = connection_key_for_endpoint(endpoint)
        endpoint_assets = assets_by_connection.get(connection_key, [])
        selectable_endpoint_assets = [asset for asset in endpoint_assets if asset.get("isSelectable")]
        if connection_key not in by_key:
            by_key[connection_key] = {
                "connectionKey": connection_key,
                "providerName": provider_name_for_endpoint(endpoint),
                "displayName": endpoint.get("name") or provider_name_for_endpoint(endpoint),
                "endpointBaseUrl": endpoint.get("baseUrl") or "",
                "apiMode": api_mode_for_endpoint(endpoint),
                "providerTypes": _unique_values([endpoint.get("providerType")]),
                "platforms": _unique_values([endpoint.get("platform")]),
                "endpointIds": _unique_values([endpoint.get("id")]),
                "endpointNames": _unique_values([endpoint.get("name") or endpoint.get("id")]),
                "modelAssetIds": _unique_values([asset.get("assetId") for asset in endpoint_assets]),
                "modelCount": _unique_model_count(endpoint_assets),
                "selectableModelCount": _unique_model_count(selectable_endpoint_assets),
                "hasAmbiguousModels": any(asset.get("isAmbiguousName") for asset in endpoint_assets),
                "createdAt": endpoint.get("createdAt"),
            }
            continue

        existing = by_key[connection_key]
        for key, value in (
            ("providerTypes", endpoint.get("providerType")),
            ("platforms", endpoint.get("platform")),
            ("endpointIds", endpoint.get("id")),
            ("endpointNames", endpoint.get("name") or endpoint.get("id")),
        ):
            _push_unique(existing[key], value)
        for asset in endpoint_assets:
            _push_unique(existing["modelAssetIds"], asset.get("assetId"))
        grouped_assets = assets_by_connection.get(connection_key, [])
        selectable_grouped_assets = [asset for asset in grouped_assets if asset.get("isSelectable")]
        existing["modelCount"] = _unique_model_count(grouped_assets)
        existing["selectableModelCount"] = _unique_model_count(selectable_grouped_assets)
        existing["hasAmbiguousModels"] = any(asset.get("isAmbiguousName") for asset in grouped_assets)

    return list(by_key.values())
