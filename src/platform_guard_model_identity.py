#!/usr/bin/env python3
"""Platform Guard model-identity dry-run helpers under Tiandao."""

from __future__ import annotations

try:
    from src.platform_guard_catalog import *
except Exception:  # pragma: no cover - direct script import fallback
    from platform_guard_catalog import *

PLATFORM_GUARD_MODEL_IDENTITY_CONTRACT = "tiandao_platform_guard_model_identity.v1"


def get_platform_guard_model_identity_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": PLATFORM_GUARD_MODEL_IDENTITY_CONTRACT,
        "zh_name": "平台守护模型识别",
        "en_name": "Platform Guard Model Identity",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "workbench_id": "platform_guard",
        "console_layer": "platform_guard_model_identity",
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "model_identity_uses_metadata_only_until_explicit_execution",
        "default_execution_policy": "metadata_only_no_model_call",
    }


def _model_identity_hints_for_surface(surface: dict[str, Any]) -> dict[str, Any]:
    system = str(surface.get("system") or "").strip()
    display_name = str(surface.get("display_name") or "").strip()
    path_tokens: list[str] = []
    for key in ("config_paths", "workspace_paths", "content_store_paths", "installation_paths"):
        for path in surface.get(key, []) if isinstance(surface.get(key), list) else []:
            for part in Path(str(path)).parts[-6:]:
                cleaned = part.strip()
                if cleaned:
                    path_tokens.append(cleaned)
    variants = sorted(_identifier_variants(system) | _identifier_variants(display_name))
    for token in path_tokens[:24]:
        variants.extend(sorted(_identifier_variants(token)))
    variants = _compact_unique(variants, limit=32)
    known_alias = _catalog_system_for_install_name(system) or _catalog_system_for_install_name(display_name)
    catalog_entry = _catalog_entry(system) or (_catalog_entry(known_alias) if known_alias else {})
    aliases = _catalog_list(catalog_entry, "aliases") if catalog_entry else ()
    return {
        "surface_id": system,
        "display_name_hint": display_name,
        "visible_identifier_variants": variants,
        "path_name_tokens": _compact_unique(path_tokens, limit=24),
        "known_catalog_match": known_alias or (system if catalog_entry else ""),
        "known_display_name": catalog_entry.get("display_name", "") if catalog_entry else "",
        "known_aliases": list(aliases)[:20],
        "identity_hint_policy": (
            "Prefer a clear product/app name from surface_id, display_name_hint, "
            "path tokens, or known_catalog_match over Unknown."
        ),
    }


def _model_runtime_chain_item(
    *,
    source: str,
    configured: bool,
    role: str,
    independent: bool,
    provider: str = "",
    provider_id: str = "",
    model_name: str = "",
    transport: str = "",
) -> dict[str, Any]:
    return {
        "source": source,
        "configured": bool(configured),
        "role": role,
        "independent": bool(independent),
        "provider": provider,
        "provider_id": provider_id,
        "model_name": model_name,
        "transport": transport,
    }


def _model_runtime_from_block(
    block: dict[str, Any],
    *,
    source: str,
    independent: bool,
    default_provider: str = "",
    default_transport: str = "openai_compatible_http",
) -> dict[str, Any] | None:
    if not isinstance(block, dict) or _truthy(block.get("enabled")) is False and "enabled" in block:
        return None
    model_name = str(
        block.get("model_name")
        or block.get("model")
        or block.get("selected_model")
        or block.get("selected_option_id")
        or ""
    ).strip()
    option_id = str(block.get("selected_option_id") or model_name).strip()
    provider = str(block.get("provider") or default_provider or "").strip()
    provider_id = str(block.get("provider_id") or block.get("selected_provider") or "").strip()
    if not model_name and not option_id:
        return None
    return {
        "configured": True,
        "source": source,
        "selected_option_id": option_id,
        "provider": provider or "configured_model",
        "provider_id": provider_id,
        "model_name": model_name or option_id,
        "transport": str(block.get("transport") or default_transport or "openai_compatible_http"),
        "base_url": str(block.get("base_url") or block.get("endpoint") or "").strip(),
        "api_key_env": str(block.get("api_key_env") or "").strip(),
        "independent": bool(independent),
    }


def _transport_for_tiandao_api_mode(api_mode: str) -> str:
    normalized = str(api_mode or "").strip().lower()
    if normalized in {"openai-completions", "openai", "openai-compatible", "openai_compatible_http"}:
        return "openai_compatible_http"
    if normalized in {"anthropic-messages", "anthropic"}:
        return "anthropic_messages_http"
    if normalized == "gemini":
        return "gemini_http"
    if normalized == "ollama":
        return "ollama_http"
    return normalized or "openai_compatible_http"


def _model_runtime_from_tiandao_block(
    block: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any] | None:
    if not isinstance(block, dict) or _truthy(block.get("enabled")) is False and "enabled" in block:
        return None

    endpoints = block.get("endpoints") or block.get("model_endpoints") or block.get("connections")
    models = block.get("models") or block.get("model_assets") or block.get("assets")
    if not isinstance(endpoints, list) or not isinstance(models, list):
        return None

    try:
        from tiandao.model_identity import (
            api_mode_for_endpoint,
            build_tiandao_model_assets,
            provider_name_for_endpoint,
        )
    except Exception:
        return None

    endpoint_by_id = {
        str(endpoint.get("id") or ""): endpoint
        for endpoint in endpoints
        if isinstance(endpoint, dict)
    }
    model_items = [model for model in models if isinstance(model, dict)]
    assets = build_tiandao_model_assets(
        [endpoint for endpoint in endpoints if isinstance(endpoint, dict)],
        model_items,
    )
    selected = str(
        block.get("selected_model_asset_id")
        or block.get("selected_asset_id")
        or block.get("selected_option_id")
        or block.get("selected_model_id")
        or block.get("selected_model")
        or block.get("model_name")
        or ""
    ).strip()
    if selected:
        selected_asset = next(
            (
                asset
                for asset in assets
                if selected in {
                    str(asset.get("assetId") or ""),
                    str(asset.get("runtimeModelId") or ""),
                    str(asset.get("id") or ""),
                    str(asset.get("modelName") or ""),
                    str(asset.get("modelKey") or ""),
                }
            ),
            None,
        )
    else:
        selected_asset = assets[0] if len(assets) == 1 else None
    if not selected_asset:
        return None

    endpoint = endpoint_by_id.get(str(selected_asset.get("endpointId") or "")) or {}
    api_mode = str(selected_asset.get("apiMode") or api_mode_for_endpoint(endpoint)).strip()
    provider_name = str(selected_asset.get("providerName") or provider_name_for_endpoint(endpoint)).strip()
    runtime_model_id = str(
        selected_asset.get("runtimeModelId")
        or selected_asset.get("modelName")
        or selected_asset.get("id")
        or ""
    ).strip()
    if not runtime_model_id:
        return None

    base_url = str(
        block.get("base_url")
        or block.get("endpoint")
        or selected_asset.get("endpointBaseUrl")
        or endpoint.get("baseUrl")
        or ""
    ).strip()
    api_key_env = str(
        block.get("api_key_env")
        or selected_asset.get("apiKeyEnv")
        or selected_asset.get("api_key_env")
        or endpoint.get("apiKeyEnv")
        or endpoint.get("api_key_env")
        or ""
    ).strip()
    return {
        "configured": True,
        "source": source,
        "selected_option_id": str(selected_asset.get("assetId") or selected or runtime_model_id),
        "provider": provider_name or "tiandao_model_identity",
        "provider_id": str(endpoint.get("id") or selected_asset.get("endpointId") or provider_name),
        "model_name": runtime_model_id,
        "transport": _transport_for_tiandao_api_mode(api_mode),
        "base_url": base_url,
        "api_key_env": api_key_env,
        "independent": True,
        "tiandao_model_identity": {
            "asset_id": str(selected_asset.get("assetId") or ""),
            "connection_key": str(selected_asset.get("connectionKey") or ""),
            "endpoint_id": str(endpoint.get("id") or selected_asset.get("endpointId") or ""),
            "endpoint_name": str(selected_asset.get("endpointName") or endpoint.get("name") or ""),
            "endpoint_base_url": base_url,
            "api_mode": api_mode,
            "platform": str(selected_asset.get("platform") or endpoint.get("platform") or ""),
            "source_contract": "tiandao_model_identity",
        },
    }


def _tiandao_model_center_blocks(model_config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for key in ("tiandao_model_center", "model_center", "tiandao_model_identity"):
        value = model_config.get(key)
        if isinstance(value, dict):
            candidates.append((f"model_config.{key}", value))
    tiandao_cfg = model_config.get("tiandao")
    if isinstance(tiandao_cfg, dict):
        for key in ("model_center", "model_identity"):
            value = tiandao_cfg.get(key)
            if isinstance(value, dict):
                candidates.append((f"model_config.tiandao.{key}", value))
    return candidates


def _inherited_platform_model_runtime(
    block: dict[str, Any],
    *,
    source: str,
    provider: str,
    transport: str,
) -> dict[str, Any] | None:
    if not isinstance(block, dict):
        return None
    selected_model = str(block.get("selected_model") or block.get("model_name") or block.get("model") or "").strip()
    selected_provider = str(block.get("selected_provider") or block.get("provider_id") or "").strip()
    if not selected_model:
        return None
    return {
        "configured": True,
        "source": source,
        "selected_option_id": f"configured-{provider.lower()}:{selected_provider or 'default'}:{selected_model}",
        "provider": provider,
        "provider_id": selected_provider,
        "model_name": selected_model,
        "transport": transport,
        "base_url": str(block.get("base_url") or block.get("endpoint") or "").strip(),
        "api_key_env": str(block.get("api_key_env") or "").strip(),
        "independent": False,
    }


def _model_identification_runtime(env: dict[str, str]) -> dict[str, Any]:
    memcore_root = _memcore_root_from_env(env)
    explicit_provider = str(env.get("MEMCORE_ZHIYI_PROVIDER") or env.get("MEMCORE_MODEL_IDENTIFICATION_PROVIDER") or "").strip()
    explicit_model = str(env.get("MEMCORE_ZHIYI_MODEL") or env.get("MEMCORE_MODEL_IDENTIFICATION_MODEL") or "").strip()
    explicit_transport = str(env.get("MEMCORE_ZHIYI_TRANSPORT") or env.get("MEMCORE_MODEL_IDENTIFICATION_TRANSPORT") or "openai_compatible_http")
    explicit_base_url = str(env.get("MEMCORE_ZHIYI_BASE_URL") or env.get("MEMCORE_MODEL_IDENTIFICATION_BASE_URL") or "").strip()
    explicit_zhiyi_configured = any(
        str(env.get(name) or "").strip()
        for name in ("MEMCORE_ZHIYI_PROVIDER", "MEMCORE_ZHIYI_MODEL", "MEMCORE_ZHIYI_TRANSPORT", "MEMCORE_ZHIYI_BASE_URL")
    )
    explicit_api_key_env = (
        "MEMCORE_ZHIYI_API_KEY"
        if explicit_zhiyi_configured or env.get("MEMCORE_ZHIYI_API_KEY")
        else "MEMCORE_MODEL_IDENTIFICATION_API_KEY"
    )
    chain: list[dict[str, Any]] = []
    if explicit_model:
        runtime = {
            "configured": True,
            "source": "env",
            "selected_option_id": explicit_model,
            "provider": explicit_provider or "configured_model",
            "provider_id": explicit_provider,
            "model_name": explicit_model,
            "transport": explicit_transport,
            "base_url": explicit_base_url,
            "api_key_env": explicit_api_key_env,
            "independent": True,
        }
        runtime["provider_chain"] = [
            _model_runtime_chain_item(
                source="env",
                configured=True,
                role="primary",
                independent=True,
                provider=runtime["provider"],
                provider_id=runtime["provider_id"],
                model_name=runtime["model_name"],
                transport=runtime["transport"],
            ),
        ]
        return runtime
    chain.append(_model_runtime_chain_item(
        source="env",
        configured=False,
        role="primary",
        independent=True,
        transport="openai_compatible_http",
    ))

    user_default = _load_json_object(memcore_root / "config" / "zhiyi_model_binding.user.json")
    user_runtime = _model_runtime_from_block(
        user_default,
        source="zhiyi_model_binding.user.json",
        independent=True,
    )
    if user_runtime:
        user_runtime["provider_chain"] = [
            *chain,
            _model_runtime_chain_item(
                source=user_runtime["source"],
                configured=True,
                role="primary",
                independent=True,
                provider=user_runtime["provider"],
                provider_id=user_runtime["provider_id"],
                model_name=user_runtime["model_name"],
                transport=user_runtime["transport"],
            ),
        ]
        return user_runtime
    chain.append(_model_runtime_chain_item(
        source="zhiyi_model_binding.user.json",
        configured=False,
        role="primary",
        independent=True,
        transport="openai_compatible_http",
    ))

    model_config = _load_json_object(memcore_root / "config" / "model_config.json")
    for key in ("zhiyi_model", "local_tool_identification", "model_identification", "ai_discovery"):
        config_runtime = _model_runtime_from_block(
            model_config.get(key) if isinstance(model_config.get(key), dict) else {},
            source=f"model_config.{key}",
            independent=True,
        )
        if config_runtime:
            config_runtime["provider_chain"] = [
                *chain,
                _model_runtime_chain_item(
                    source=config_runtime["source"],
                    configured=True,
                    role="primary",
                    independent=True,
                    provider=config_runtime["provider"],
                    provider_id=config_runtime["provider_id"],
                    model_name=config_runtime["model_name"],
                    transport=config_runtime["transport"],
                ),
            ]
            return config_runtime

    recall_cfg = model_config.get("recall") if isinstance(model_config.get("recall"), dict) else {}
    recall_identification = _model_runtime_from_block(
        recall_cfg.get("model_identification") if isinstance(recall_cfg.get("model_identification"), dict) else {},
        source="model_config.recall.model_identification",
        independent=True,
    )
    if recall_identification:
        recall_identification["provider_chain"] = [
            *chain,
            _model_runtime_chain_item(
                source=recall_identification["source"],
                configured=True,
                role="primary",
                independent=True,
                provider=recall_identification["provider"],
                provider_id=recall_identification["provider_id"],
                model_name=recall_identification["model_name"],
                transport=recall_identification["transport"],
            ),
        ]
        return recall_identification

    chain.append(_model_runtime_chain_item(
        source="model_config.zhiyi_model",
        configured=False,
        role="primary",
        independent=True,
        transport="openai_compatible_http",
    ))

    for source, block in _tiandao_model_center_blocks(model_config):
        tiandao_runtime = _model_runtime_from_tiandao_block(block, source=source)
        if tiandao_runtime:
            tiandao_runtime["provider_chain"] = [
                *chain,
                _model_runtime_chain_item(
                    source=tiandao_runtime["source"],
                    configured=True,
                    role="shared_tiandao_identity",
                    independent=True,
                    provider=tiandao_runtime["provider"],
                    provider_id=tiandao_runtime["provider_id"],
                    model_name=tiandao_runtime["model_name"],
                    transport=tiandao_runtime["transport"],
                ),
            ]
            return tiandao_runtime

    chain.append(_model_runtime_chain_item(
        source="model_config.tiandao_model_center",
        configured=False,
        role="shared_tiandao_identity",
        independent=True,
        transport="openai_compatible_http",
    ))

    inherited_sources = (
        (
            "model_config.openclaw_model",
            recall_cfg.get("openclaw_model") if isinstance(recall_cfg.get("openclaw_model"), dict) else {},
            "OpenClaw",
            "inherited_openclaw_model",
        ),
        (
            "model_config.hermes_model",
            recall_cfg.get("hermes_model") if isinstance(recall_cfg.get("hermes_model"), dict) else {},
            "Hermes",
            "inherited_hermes_model",
        ),
    )
    for source, block, provider, transport in inherited_sources:
        runtime = _inherited_platform_model_runtime(
            block,
            source=source,
            provider=provider,
            transport=transport,
        )
        if runtime:
            role = "optional_inherited"
            runtime["provider_chain"] = [
                *chain,
                _model_runtime_chain_item(
                    source=source,
                    configured=True,
                    role=role,
                    independent=False,
                    provider=provider,
                    provider_id=runtime["provider_id"],
                    model_name=runtime["model_name"],
                    transport=transport,
                ),
            ]
            return runtime

    optional_chain = []
    for source, _block, provider, transport in inherited_sources:
        optional_chain.append(_model_runtime_chain_item(
            source=source,
            configured=False,
            role="optional_inherited",
            independent=False,
            provider=provider,
            transport=transport,
        ))

    return {
        "configured": False,
        "source": "not_configured",
        "selected_option_id": "",
        "provider": "",
        "provider_id": "",
        "model_name": "",
        "transport": "",
        "base_url": "",
        "api_key_env": "",
        "independent": True,
        "provider_chain": [
            *chain,
            *optional_chain,
        ],
    }
def _signal_metadata_for_model(signal: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = (
        "kind",
        "role",
        "artifact_format",
        "path_pattern",
        "reported_keys",
        "mcp_detected",
        "mcp_server_names",
        "memcore_mcp_detected",
        "memcore_mcp_server_names",
        "intent_signal_detected",
        "manager",
        "name",
        "version",
        "app_installed",
        "cli_installed",
        "complete_conversation_candidate",
        "assistant_replies_may_persist",
    )
    metadata = {key: signal.get(key) for key in allowed_keys if key in signal}
    if signal.get("path"):
        metadata["path_tail"] = _path_tail(str(signal.get("path")))
    return metadata


def _surface_metadata_for_model(surface: dict[str, Any]) -> dict[str, Any]:
    signals = [
        _signal_metadata_for_model(signal)
        for signal in surface.get("signals", [])[:12]
        if isinstance(signal, dict)
    ]
    software = surface.get("software") if isinstance(surface.get("software"), dict) else {}
    app = software.get("app") if isinstance(software.get("app"), dict) else {}
    cli = software.get("cli") if isinstance(software.get("cli"), dict) else {}
    return {
        "surface_id": surface.get("system", ""),
        "display_name_hint": surface.get("display_name", ""),
        "identity_hints": _model_identity_hints_for_surface(surface),
        "source": surface.get("source", ""),
        "platform_family_hint": surface.get("platform_family", ""),
        "catalog_driven": bool(surface.get("catalog_driven")),
        "mcp_config_detected": bool(surface.get("mcp_config_detected")),
        "memcore_mcp_detected": bool(surface.get("memcore_mcp_detected")),
        "intent_signal_detected": bool(surface.get("intent_signal_detected")),
        "config_file_names": _compact_unique(Path(path).name for path in surface.get("config_paths", [])),
        "config_path_tails": _compact_unique(_path_tail(path) for path in surface.get("config_paths", [])),
        "workspace_path_tails": _compact_unique(_path_tail(path) for path in surface.get("workspace_paths", [])),
        "content_store_path_tails": _compact_unique(_path_tail(path) for path in surface.get("content_store_paths", [])),
        "installation_path_tails": _compact_unique(_path_tail(path) for path in surface.get("installation_paths", [])),
        "app_bundle": {
            "installed": bool(app.get("installed")),
            "name": Path(str(app.get("bundle_path") or "")).name if app.get("bundle_path") else "",
            "version": str(app.get("version") or ""),
        },
        "cli_binary": {
            "installed": bool(cli.get("installed")),
            "name": Path(str(cli.get("path") or "")).name if cli.get("path") else "",
            "version": str(cli.get("version") or ""),
        },
        "signals": signals,
        "chat_body_included": False,
        "raw_excerpt_included": False,
    }


def _category_from_family(family: Any) -> str:
    family_text = str(family or "").lower()
    if "cli" in family_text:
        return "agent_cli"
    if "ide" in family_text or "editor" in family_text:
        return "editor_agent"
    if "desktop" in family_text or "app" in family_text:
        return "agent_app"
    if "panel" in family_text:
        return "agent_panel"
    if "mcp" in family_text or "config" in family_text:
        return "agent_config_surface"
    return "unknown"


def _storage_candidate_for_surface(surface: dict[str, Any]) -> str:
    for key in ("content_store_paths", "workspace_paths", "config_paths", "installation_paths"):
        values = surface.get(key)
        if isinstance(values, list) and values:
            return _path_tail(str(values[0]))
    return ""


def _rule_identification_result(surface: dict[str, Any]) -> dict[str, Any]:
    catalog_driven = bool(surface.get("catalog_driven"))
    mcp_detected = bool(surface.get("mcp_config_detected"))
    intent_detected = bool(surface.get("intent_signal_detected"))
    confidence = 0.9 if catalog_driven else 0.62 if (mcp_detected or intent_detected) else 0.45
    if str(surface.get("source") or "").startswith("verified_storage"):
        confidence = max(confidence, 0.86)
    return {
        "likely_name": surface.get("display_name") or surface.get("system") or "Unknown local AI tool",
        "category": _category_from_family(surface.get("platform_family")),
        "supports_mcp_likely": mcp_detected or "mcp" in str(surface.get("platform_family") or "").lower(),
        "skill_surface_likely": any(
            isinstance(signal, dict) and "skill" in str(signal.get("kind") or "").lower()
            for signal in surface.get("signals", [])
        ),
        "storage_candidate": _storage_candidate_for_surface(surface),
        "confidence": round(confidence, 2),
        "reason": (
            "matched verified local catalog or storage pattern"
            if confidence >= 0.86
            else "matched local config or MCP-shaped metadata"
            if confidence >= 0.6
            else "only weak local metadata was available"
        ),
    }


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _normalize_model_confidence(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(float(value), 1.0))
    text = str(value or "").strip().lower()
    if not text:
        return 0.0
    word_values = {
        "very high": 0.95,
        "high": 0.85,
        "medium": 0.6,
        "moderate": 0.6,
        "low": 0.3,
        "very low": 0.15,
        "unknown": 0.0,
    }
    if text in word_values:
        return word_values[text]
    try:
        numeric = float(text.rstrip("%"))
    except Exception:
        return 0.0
    if numeric > 1.0:
        numeric = numeric / 100.0
    return max(0.0, min(numeric, 1.0))


def _is_unknown_model_name(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {
        "",
        "unknown",
        "unknown local ai tool",
        "unknown local tool",
        "unknown tool",
        "local ai tool",
    }


def _visible_identity_name(metadata: dict[str, Any]) -> str:
    hints = metadata.get("identity_hints") if isinstance(metadata.get("identity_hints"), dict) else {}
    for key in ("known_display_name", "display_name_hint", "surface_id"):
        value = str(hints.get(key) or metadata.get(key) or "").strip()
        if value and not _is_unknown_model_name(value):
            return value.replace("_", " ").replace("-", " ").title()
    return ""


def _repair_model_identification_result(
    result: dict[str, Any],
    *,
    rule_result: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    repaired = dict(result)
    if _is_unknown_model_name(repaired.get("likely_name")):
        visible_name = _visible_identity_name(metadata)
        if visible_name:
            repaired["likely_name"] = visible_name
            repaired["visible_identity_fallback_applied"] = True
            repaired["reason"] = (
                f"{repaired.get('reason') or 'model returned unknown'}; "
                "used visible local identifier"
            )
            repaired["confidence"] = max(
                _normalize_model_confidence(rule_result.get("confidence")),
                min(_normalize_model_confidence(repaired.get("confidence")), 0.78),
            )
    if str(repaired.get("category") or "").strip().lower() == "unknown" and rule_result.get("category"):
        repaired["category"] = rule_result.get("category")
    repaired["confidence"] = _normalize_model_confidence(repaired.get("confidence", 0.0))
    return repaired


def _parse_model_identification_response(text: str) -> dict[str, Any]:
    data = None
    parse_error = ""
    for candidate in _json_object_candidates(text):
        try:
            data = json.loads(candidate)
            break
        except Exception as exc:
            parse_error = f"{type(exc).__name__}: {exc}"
    if data is None:
        return {
            "ok": False,
            "error": "model_response_not_json",
            "parse_error": parse_error,
            "raw_preview": text[:500],
        }
    if not isinstance(data, dict):
        return {
            "ok": False,
            "error": "model_response_not_object",
            "raw_type": type(data).__name__,
        }
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    allowed = {
        "likely_name",
        "category",
        "supports_mcp_likely",
        "skill_surface_likely",
        "storage_candidate",
        "confidence",
        "reason",
    }
    normalized = {key: result.get(key) for key in allowed if key in result}
    if not normalized.get("likely_name"):
        normalized["likely_name"] = "Unknown local AI tool"
    if not normalized.get("category"):
        normalized["category"] = "unknown"
    normalized["confidence"] = _normalize_model_confidence(normalized.get("confidence", 0.0))
    return {
        "ok": True,
        "result": normalized,
        "raw_keys": sorted(str(key) for key in data.keys()),
    }


def _json_object_candidates(text: str) -> list[str]:
    stripped = str(text or "").strip()
    if not stripped:
        return []
    candidates = [stripped]
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", stripped, re.I | re.S):
        fenced = match.group(1).strip()
        if fenced and fenced not in candidates:
            candidates.append(fenced)
    for candidate in _balanced_json_objects(stripped):
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _balanced_json_objects(text: str) -> list[str]:
    results: list[str] = []
    for start, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            current = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    results.append(text[start : index + 1])
                    break
    return results[:5]


def _run_model_identification_command(
    request_envelope: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any] | None:
    command = str(
        env.get("MEMCORE_ZHIYI_MODEL_COMMAND")
        or env.get("MEMCORE_MODEL_IDENTIFICATION_COMMAND")
        or ""
    ).strip()
    if not command:
        return None
    try:
        timeout = int(str(
            env.get("MEMCORE_ZHIYI_MODEL_TIMEOUT_SECONDS")
            or env.get("MEMCORE_MODEL_IDENTIFICATION_TIMEOUT_SECONDS")
            or "45"
        ))
    except Exception:
        timeout = 45
    payload = json.dumps(
        {"request_envelope": request_envelope},
        ensure_ascii=False,
        sort_keys=True,
    )
    try:
        completed = subprocess.run(
            shlex.split(command),
            input=payload,
            text=True,
            capture_output=True,
            timeout=max(1, min(timeout, 120)),
            check=False,
        )
    except Exception as exc:
        return {
            "ok": False,
            "executor": "local_command",
            "model_call_performed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    parsed = _parse_model_identification_response(completed.stdout.strip())
    return {
        "ok": completed.returncode == 0 and bool(parsed.get("ok")),
        "executor": "local_command",
        "model_call_performed": completed.returncode == 0,
        "returncode": completed.returncode,
        "stderr_preview": completed.stderr[:500],
        **parsed,
    }


def _provider_env_candidates(provider: str, provider_id: str) -> tuple[list[str], list[str], str]:
    marker = f"{provider} {provider_id}".lower()
    if "deepseek" in marker:
        return (
            ["MEMCORE_ZHIYI_API_KEY", "MEMCORE_MODEL_IDENTIFICATION_API_KEY", "DEEPSEEK_API_KEY"],
            ["MEMCORE_ZHIYI_BASE_URL", "MEMCORE_MODEL_IDENTIFICATION_BASE_URL", "DEEPSEEK_BASE_URL"],
            "https://api.deepseek.com/v1",
        )
    if "minimax" in marker or "mimo" in marker:
        return (
            ["MEMCORE_ZHIYI_API_KEY", "MEMCORE_MODEL_IDENTIFICATION_API_KEY", "MINIMAX_API_KEY", "MINIMAX_CN_API_KEY"],
            ["MEMCORE_ZHIYI_BASE_URL", "MEMCORE_MODEL_IDENTIFICATION_BASE_URL", "MINIMAX_BASE_URL", "MINIMAX_CN_BASE_URL"],
            "https://api.minimaxi.com/v1",
        )
    if "openai" in marker:
        return (
            ["MEMCORE_ZHIYI_API_KEY", "MEMCORE_MODEL_IDENTIFICATION_API_KEY", "OPENAI_API_KEY"],
            ["MEMCORE_ZHIYI_BASE_URL", "MEMCORE_MODEL_IDENTIFICATION_BASE_URL", "OPENAI_BASE_URL"],
            "https://api.openai.com/v1",
        )
    return (
        ["MEMCORE_ZHIYI_API_KEY", "MEMCORE_MODEL_IDENTIFICATION_API_KEY"],
        ["MEMCORE_ZHIYI_BASE_URL", "MEMCORE_MODEL_IDENTIFICATION_BASE_URL"],
        "",
    )


def _first_env_value(env: dict[str, str], names: list[str]) -> str:
    for name in names:
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return ""


def _run_openai_compatible_model_identification(
    request_envelope: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any] | None:
    transport = str(request_envelope.get("transport") or "openai_compatible_http").strip().lower()
    if transport and transport not in {"openai_compatible_http", "openai-compatible", "openai"}:
        return None
    provider = str(request_envelope.get("provider") or "")
    provider_id = str(request_envelope.get("provider_id") or "")
    model_name = str(request_envelope.get("model_name") or "").strip()
    key_names, base_names, default_base_url = _provider_env_candidates(provider, provider_id)
    explicit_key_env = str(request_envelope.get("api_key_env") or "").strip()
    api_key = str(env.get(explicit_key_env) or "").strip() if explicit_key_env else ""
    if not api_key:
        api_key = _first_env_value(env, key_names)
    base_url = str(request_envelope.get("base_url") or "").strip()
    if not base_url:
        base_url = _first_env_value(env, base_names) or default_base_url
    if not api_key or not base_url or not model_name:
        return None
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"
    payload = {
        "model": model_name,
        "messages": request_envelope.get("messages", []),
        "temperature": 0,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        timeout = int(str(
            env.get("MEMCORE_ZHIYI_MODEL_TIMEOUT_SECONDS")
            or env.get("MEMCORE_MODEL_IDENTIFICATION_TIMEOUT_SECONDS")
            or "45"
        ))
    except Exception:
        timeout = 45
    try:
        with urllib.request.urlopen(req, timeout=max(1, min(timeout, 120))) as response:
            body = response.read(2_000_000).decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "executor": "openai_compatible_http",
            "model_call_performed": True,
            "status_code": exc.code,
            "error": exc.read(2000).decode("utf-8", errors="ignore"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "executor": "openai_compatible_http",
            "model_call_performed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        payload_obj = json.loads(body)
        content = payload_obj["choices"][0]["message"]["content"]
    except Exception:
        return {
            "ok": False,
            "executor": "openai_compatible_http",
            "model_call_performed": True,
            "error": "chat_completion_response_missing_message_content",
            "raw_preview": body[:500],
        }
    parsed = _parse_model_identification_response(str(content).strip())
    return {
        "ok": bool(parsed.get("ok")),
        "executor": "openai_compatible_http",
        "model_call_performed": True,
        **parsed,
    }


def _execute_model_identification_request(
    request_envelope: dict[str, Any],
    env: dict[str, str],
) -> dict[str, Any]:
    command_result = _run_model_identification_command(request_envelope, env)
    if command_result is not None:
        return command_result
    http_result = _run_openai_compatible_model_identification(request_envelope, env)
    if http_result is not None:
        return http_result
    transport = str(request_envelope.get("transport") or "").strip()
    if transport and transport not in {"openai_compatible_http", "openai-compatible", "openai"}:
        return {
            "ok": False,
            "executor": "unsupported_transport",
            "model_call_performed": False,
            "error": f"unsupported_model_identification_transport:{transport}",
        }
    return {
        "ok": False,
        "executor": "not_configured",
        "model_call_performed": False,
        "error": "model_identification_executor_not_configured",
    }


def _build_model_identification(
    surface: dict[str, Any],
    env: dict[str, str],
    *,
    execute_model: bool = False,
) -> dict[str, Any]:
    rule_result = _rule_identification_result(surface)
    metadata = _surface_metadata_for_model(surface)
    runtime = _model_identification_runtime(env)
    needs_model = not bool(surface.get("catalog_driven")) or float(rule_result.get("confidence") or 0.0) < 0.75
    base = {
        "contract": MODEL_IDENTIFICATION_CONTRACT,
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "input_kind": "local_metadata_only",
        "local_scanner_role": "collect_paths_configs_package_and_marker_metadata",
        "model_role": "identify_unknown_or_low_confidence_local_ai_tool",
        "chat_body_included": False,
        "raw_excerpt_included": False,
        "rule_result": rule_result,
        "local_metadata": metadata,
    }
    if not needs_model:
        return {
            **base,
            "enabled": False,
            "mode": "rules_confident",
            "reason": "local_rules_already_identified_surface",
            "configured_model": {
                "configured": bool(runtime.get("configured")),
                "source": runtime.get("source", ""),
                "provider": runtime.get("provider", ""),
                "provider_id": runtime.get("provider_id", ""),
                "model_name": runtime.get("model_name", ""),
                "transport": runtime.get("transport", ""),
                "independent": bool(runtime.get("independent", True)),
                "provider_chain": runtime.get("provider_chain", []),
            },
            "result": rule_result,
        }
    if not runtime.get("configured"):
        return {
            **base,
            "enabled": False,
            "mode": "fallback_rules",
            "reason": "model_not_configured",
            "configured_model": {
                "configured": False,
                "source": runtime.get("source", "not_configured"),
                "provider": "",
                "provider_id": "",
                "model_name": "",
                "transport": "",
                "independent": True,
                "provider_chain": runtime.get("provider_chain", []),
            },
            "result": rule_result,
        }
    request_envelope = {
        "schema_version": "1.0",
        "request_kind": "local_ai_tool_identification",
        "task_kind": "identify_local_ai_tool_from_metadata",
        "selected_option_id": runtime.get("selected_option_id", ""),
        "provider": runtime.get("provider", ""),
        "provider_id": runtime.get("provider_id", ""),
        "model_name": runtime.get("model_name", ""),
        "transport": runtime.get("transport", ""),
        "base_url": runtime.get("base_url", ""),
        "api_key_env": runtime.get("api_key_env", ""),
        "independent_provider": bool(runtime.get("independent", True)),
        "provider_chain": runtime.get("provider_chain", []),
        "messages": [
            {
                "role": "system",
                "content": (
                    "Identify the local AI coding tool or agent surface from local metadata only. "
                    "Return only a JSON object. Do not infer from chat bodies. "
                    "Use visible identifiers such as surface_id, display_name_hint, path_name_tokens, "
                    "config_file_names, known_catalog_match, and app or CLI names. "
                    "If the visible identifier is a product-like name, return that name instead of "
                    "Unknown local AI tool, even when the exact platform is not in your prior knowledge. "
                    "Set confidence as a number from 0 to 1."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            },
        ],
        "expected_response_schema": {
            "likely_name": "string",
            "category": "agent_ide|agent_cli|editor_agent|agent_panel|agent_app|agent_config_surface|unknown",
            "supports_mcp_likely": "boolean",
            "skill_surface_likely": "boolean",
            "storage_candidate": "string",
            "confidence": "number",
            "reason": "string",
        },
        "request_sent": False,
        "response_received": False,
        "model_call_performed": False,
    }
    response = {
        **base,
        "enabled": True,
        "mode": "configured_model",
        "reason": "model_configured_for_unknown_or_low_confidence_surface",
        "configured_model": {
            "configured": True,
            "source": runtime.get("source", ""),
            "provider": runtime.get("provider", ""),
            "provider_id": runtime.get("provider_id", ""),
            "model_name": runtime.get("model_name", ""),
            "transport": runtime.get("transport", ""),
            "independent": bool(runtime.get("independent", True)),
            "provider_chain": runtime.get("provider_chain", []),
        },
        "request_envelope": request_envelope,
        "result": {
            **rule_result,
            "status": "pending_model_identification",
            "provisional": True,
        },
    }
    if not execute_model:
        return response
    execution = _execute_model_identification_request(request_envelope, env)
    response["executor"] = execution.get("executor", "")
    response["model_call_performed"] = bool(execution.get("model_call_performed"))
    response["request_envelope"] = {
        **request_envelope,
        "request_sent": bool(execution.get("model_call_performed")),
        "response_received": bool(execution.get("ok")),
        "model_call_performed": bool(execution.get("model_call_performed")),
    }
    if execution.get("ok") and isinstance(execution.get("result"), dict):
        model_result = _repair_model_identification_result(
            execution["result"],
            rule_result=rule_result,
            metadata=metadata,
        )
        response["result"] = {
            **rule_result,
            **model_result,
            "status": "identified_by_model",
            "provisional": False,
        }
        response["execution"] = {
            "ok": True,
            "executor": execution.get("executor", ""),
            "model_call_performed": bool(execution.get("model_call_performed")),
        }
        return response
    response["result"] = {
        **rule_result,
        "status": "model_identification_failed_fallback_rules",
        "provisional": True,
    }
    response["execution"] = {
        "ok": False,
        "executor": execution.get("executor", ""),
        "model_call_performed": bool(execution.get("model_call_performed")),
        "error": execution.get("error", "model_identification_failed"),
    }
    return response




__all__ = [name for name in globals() if not name.startswith("__")]
