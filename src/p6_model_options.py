#!/usr/bin/env python3
"""Discovery of model options shown by the Time Library console."""

from __future__ import annotations

import glob
import os

def build_model_options(
    memcore_root,
    *,
    json_or_none,
    vector_recall_preference_from_user_default,
    default_vector_recall_preference,
    current_vector_model,
    granite_asset_status_fn,
    query_openclaw_chat_send_targets_fn,
    resolve_hermes_home_fn,
    hermes_config_paths_fn,
    unique_existing_fn,
    home_candidates_fn,
):
    """Return model preferences for Time Library analysis and distillation."""
    MEMCORE_ROOT = str(memcore_root)
    _json_or_none = json_or_none
    _vector_recall_preference_from_user_default = vector_recall_preference_from_user_default
    _default_vector_recall_preference = default_vector_recall_preference
    _current_vector_model = current_vector_model
    granite_asset_status = granite_asset_status_fn
    query_openclaw_chat_send_targets = query_openclaw_chat_send_targets_fn
    resolve_hermes_home = resolve_hermes_home_fn
    hermes_config_paths = hermes_config_paths_fn
    _unique_existing = unique_existing_fn
    _home_candidates = home_candidates_fn
    user_default_path = os.path.join(str(MEMCORE_ROOT), "config", "zhiyi_model_binding.user.json")
    user_default = _json_or_none(user_default_path) or {}
    user_model = str(user_default.get("model_name") or user_default.get("model") or "").strip()
    user_provider = str(user_default.get("provider") or "").strip()
    user_provider_id = str(user_default.get("provider_id") or "").strip()
    user_base_url = str(user_default.get("base_url") or "").strip()
    user_api_key_env = str(user_default.get("api_key_env") or "MEMCORE_ZHIYI_API_KEY").strip()
    user_selected_option_id = str(user_default.get("selected_option_id") or user_model or "").strip()
    vector_preference = _vector_recall_preference_from_user_default(user_default)
    vector_asset_status = granite_asset_status(MEMCORE_ROOT)
    if vector_preference.get("enabled") and not vector_asset_status.get("ready"):
        vector_preference = _default_vector_recall_preference(False)
        vector_preference.update({
            "configured": True,
            "forced_fallback": True,
            "fallback_reason": "vector_assets_not_ready",
            "hot_switch_status": "fts5_fallback_until_vector_assets_ready",
        })

    options = [{
        "id": "",
        "label": "默认（自动识别）",
        "provider": "auto",
        "source": "platform_default",
        "category": "default",
        "description": "按 Time Library 可用的环境配置选择，不修改接入平台。",
    }]
    selected_model = ""
    selected_provider = ""
    selected_option_id = ""
    notes = []
    detected_sources = []
    seen_ids = {""}
    counts = {"local": 0, "openclaw": 0, "hermes": 0}
    detected_counts = {"local": 0, "openclaw": 0, "hermes": 0}
    hidden_counts = {"local": 0, "openclaw": 0, "hermes": 0}
    display_limits = {"local": 0, "openclaw": 2, "hermes": 2}
    hidden_option_examples = []

    def add_note(note):
        if note not in notes:
            notes.append(note)

    def hide_option(item, category, reason):
        if category in hidden_counts:
            hidden_counts[category] += 1
        if len(hidden_option_examples) < 20:
            hidden = dict(item)
            hidden["hidden_reason"] = reason
            hidden_option_examples.append(hidden)
        add_note(reason)

    def add_option(option_id, label, provider, source, category, **extra):
        if not option_id or option_id in seen_ids:
            return False
        seen_ids.add(option_id)
        item = {
            "id": option_id,
            "label": label,
            "provider": provider,
            "source": source,
            "category": category,
        }
        item.update(extra)
        if category in detected_counts:
            detected_counts[category] += 1
            limit = display_limits.get(category)
            if limit is not None and counts[category] >= limit:
                reason = "local_embedding_model_hidden_from_user_options" if category == "local" else "model_candidates_limited_for_first_version"
                hide_option(item, category, reason)
                return False
        options.append(item)
        if category in counts:
            counts[category] += 1
        return True

    def record_hidden_option(option_id, label, provider, source, category, reason, **extra):
        if not option_id or option_id in seen_ids:
            return False
        seen_ids.add(option_id)
        item = {
            "id": option_id,
            "label": label,
            "provider": provider,
            "source": source,
            "category": category,
        }
        item.update(extra)
        if category in detected_counts:
            detected_counts[category] += 1
        hide_option(item, category, reason)
        return True

    if user_model:
        selected_model = user_model
        selected_provider = user_provider
        selected_option_id = user_selected_option_id
        add_option(
            user_selected_option_id or f"manual:{user_provider_id or user_provider or 'configured'}:{user_model}",
            f"{user_provider or 'Custom'} · {user_model}",
            user_provider or "Custom",
            user_default.get("source") or "manual_user_default",
            "manual",
            provider_id=user_provider_id,
            model_name=user_model,
            base_url=user_base_url,
            api_key_env=user_api_key_env,
            description="手动填写",
        )

    model_config_path = os.path.join(str(MEMCORE_ROOT), "config", "model_config.json")
    model_config = _json_or_none(model_config_path)
    current_vector_model = _current_vector_model(model_config or {})
    if isinstance(model_config, dict):
        recall_cfg = model_config.get("recall", {})
        openclaw_model = recall_cfg.get("openclaw_model", {})
        if not selected_model:
            selected_model = openclaw_model.get("selected_model", "") or ""
            selected_provider = openclaw_model.get("selected_provider", "") or ""
        if selected_model:
            label = f"OpenClaw · {selected_model}"
            if selected_provider:
                label += f"（{selected_provider}）"
            add_option(
                f"configured-openclaw:{selected_provider or 'default'}:{selected_model}",
                label,
                "OpenClaw",
                "zhiyi_model_config",
                "openclaw",
                provider_id=selected_provider,
                model_name=selected_model,
                description="当前知意配置",
            )
        local_bge = recall_cfg.get("local_bge_m3", {})
        add_option(
            "local:bge-m3",
            "内置基础模型 BGE-M3（本机资源）",
            "内置",
            "local_bge_m3",
            "local",
            description="用于向量化、召回、检索和经验记忆匹配，配套 LanceDB；不等同于对话大模型。",
            cost_profile="本机资源 / 不额外调用平台模型",
            model_name=local_bge.get("model_name") or local_bge.get("embedding_model") or "BAAI/bge-m3",
            table=local_bge.get("table") or "experiences_v2",
        )
    else:
        notes.append("model_config_unavailable")

    def add_provider_models(platform, registry, source):
        if not isinstance(registry, dict):
            return 0
        providers = registry.get("providers")
        if providers is None and isinstance(registry.get("models"), dict):
            providers = registry.get("models", {}).get("providers")
        if not isinstance(providers, dict):
            return 0
        added = 0
        for provider_id, provider_data in providers.items():
            if not isinstance(provider_data, dict):
                continue
            models = provider_data.get("models", [])
            if isinstance(models, dict):
                iterable = []
                for model_id, model_data in models.items():
                    if isinstance(model_data, dict):
                        merged = dict(model_data)
                        merged.setdefault("id", model_id)
                        iterable.append(merged)
                    else:
                        iterable.append({"id": model_id, "name": str(model_data)})
            elif isinstance(models, list):
                iterable = models
            else:
                iterable = []
            for model_data in iterable:
                if isinstance(model_data, dict):
                    model_id = model_data.get("id") or model_data.get("model") or model_data.get("name")
                    model_label = model_data.get("name") or model_data.get("label") or model_id
                else:
                    model_id = str(model_data)
                    model_label = model_id
                if not model_id:
                    continue
                display = str(model_label or model_id)
                label = f"{platform} · {display}"
                if provider_id and str(provider_id) not in display:
                    label += f"（{provider_id}）"
                if record_hidden_option(
                    f"{platform.lower()}-provider:{provider_id}:{model_id}",
                    label,
                    platform,
                    source,
                    platform.lower(),
                    "platform_model_registry_hidden_from_user_options",
                    provider_id=str(provider_id),
                    model_name=str(model_id),
                    description="从接入平台模型表读取",
                ):
                    added += 1
        return added

    def add_agent_models(platform, config, source):
        agents = config.get("agents", {}).get("list", []) if isinstance(config, dict) else []
        if not isinstance(agents, list):
            return 0
        added = 0
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            raw_model = agent.get("model")
            if isinstance(raw_model, dict):
                model_name = raw_model.get("primary") or raw_model.get("model") or raw_model.get("name")
            else:
                model_name = raw_model
            if not model_name:
                continue
            agent_id = agent.get("id") or "agent"
            if record_hidden_option(
                f"{platform.lower()}-agent:{agent_id}:{model_name}",
                f"{platform} · {agent_id}（{model_name}）",
                platform,
                source,
                platform.lower(),
                "platform_agent_model_table_hidden_from_user_options",
                agent_id=str(agent_id),
                model_name=str(model_name),
                description="当前平台角色正在使用的模型",
            ):
                added += 1
        return added

    openclaw_roots = _unique_existing(
        [os.environ.get("OPENCLAW_HOME")]
        + [os.path.join(home, ".openclaw") for home in _home_candidates()]
    )
    openclaw_seen = False
    try:
        targets = query_openclaw_chat_send_targets({"page": 1, "page_size": 5})
        if targets.get("ok"):
            for item in targets.get("items", []):
                model_name = item.get("model", "")
                provider_id = item.get("model_provider", "")
                if not model_name:
                    continue
                add_option(
                    f"openclaw-current:{provider_id or 'default'}:{model_name}",
                    f"OpenClaw · {model_name}",
                    "OpenClaw",
                    "openclaw_recent_session",
                    "openclaw",
                    provider_id=str(provider_id or ""),
                    model_name=str(model_name),
                    description="最近使用",
                )
                openclaw_seen = True
                break
    except Exception as exc:
        notes.append(f"openclaw_recent_model_unavailable:{str(exc)[:80]}")
    for root in openclaw_roots:
        config_path = os.path.join(root, "openclaw.json")
        if os.path.exists(config_path):
            openclaw_seen = True
            config = _json_or_none(config_path)
            if isinstance(config, dict):
                detected_sources.append(config_path)
                add_provider_models("OpenClaw", config, "openclaw_provider_registry")
                add_agent_models("OpenClaw", config, "openclaw_agent")
            else:
                notes.append(f"openclaw_config_parse_failed:{config_path}")
        clawui_path = os.path.join(root, "clawui-models.json")
        clawui_models = _json_or_none(clawui_path)
        if isinstance(clawui_models, dict):
            openclaw_seen = True
            detected_sources.append(clawui_path)
            for full_model in clawui_models.keys():
                if not isinstance(full_model, str) or "/" not in full_model:
                    continue
                provider_id, model_id = full_model.split("/", 1)
                record_hidden_option(
                    f"openclaw-clawui:{full_model}",
                    f"OpenClaw · {model_id}（{provider_id}）",
                    "OpenClaw",
                    "openclaw_clawui_models",
                    "openclaw",
                    "platform_model_cache_hidden_from_user_options",
                    provider_id=provider_id,
                    model_name=model_id,
                    description="从 OpenClaw UI 模型缓存读取",
                )
        for models_path in glob.glob(os.path.join(root, "agents", "*", "agent", "models.json")):
            registry = _json_or_none(models_path)
            if isinstance(registry, dict):
                openclaw_seen = True
                detected_sources.append(models_path)
                add_provider_models("OpenClaw", registry, "openclaw_agent_models")
    if not openclaw_seen:
        notes.append("openclaw_model_registry_not_found")

    def parse_hermes_config_yaml(path):
        result = {}
        try:
            lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
        except Exception:
            return result
        in_model = False
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "model:":
                in_model = True
                continue
            if in_model and not line.startswith((" ", "\t")):
                in_model = False
            if in_model and ":" in stripped:
                key, value = stripped.split(":", 1)
                value = value.strip().strip("'\"")
                if key in ("default", "provider", "model") and value:
                    result[key] = value
        return result

    hermes_roots = _unique_existing(
        [str(resolve_hermes_home()), os.environ.get("HERMES_HOME")]
        + [os.path.join(home, ".hermes") for home in _home_candidates()]
    )
    hermes_seen = False
    for root in hermes_roots:
        state_db_path = os.path.join(root, "state.db")
        if os.path.exists(state_db_path):
            try:
                import sqlite3
                con = sqlite3.connect(f"file:{state_db_path}?mode=ro", uri=True)
                rows = con.execute(
                    "SELECT model,billing_provider FROM sessions WHERE model IS NOT NULL AND model != '' ORDER BY started_at DESC LIMIT 8"
                ).fetchall()
                con.close()
                for model_name, provider_id in rows:
                    if add_option(
                        f"hermes-recent:{provider_id or 'default'}:{model_name}",
                        f"Hermes · {model_name}",
                        "Hermes",
                        "hermes_recent_session",
                        "hermes",
                        provider_id=str(provider_id or "Hermes"),
                        model_name=str(model_name),
                        description="最近使用",
                    ):
                        hermes_seen = True
                        break
            except Exception as exc:
                notes.append(f"hermes_recent_model_unavailable:{str(exc)[:80]}")
        for yaml_path_obj in hermes_config_paths(root, existing_only=True):
            yaml_path = str(yaml_path_obj)
            hermes_seen = True
            detected_sources.append(yaml_path)
            cfg = parse_hermes_config_yaml(yaml_path)
            model_name = cfg.get("default") or cfg.get("model")
            provider_id = cfg.get("provider") or "Hermes"
            if model_name:
                add_option(
                    f"hermes-config:{provider_id}:{model_name}",
                    f"Hermes · {model_name}（{provider_id}）",
                    "Hermes",
                    "hermes_config",
                    "hermes",
                    provider_id=provider_id,
                    model_name=model_name,
                    description="Hermes 默认模型",
                )
        for json_name in ("config.json", "settings.json"):
            config_path = os.path.join(root, json_name)
            config = _json_or_none(config_path)
            if isinstance(config, dict):
                hermes_seen = True
                detected_sources.append(config_path)
                model_name = config.get("model") or config.get("default_model") or config.get("selected_model")
                provider_id = config.get("provider") or "Hermes"
                if model_name:
                    add_option(
                        f"hermes-config:{provider_id}:{model_name}",
                        f"Hermes · {model_name}（{provider_id}）",
                        "Hermes",
                        "hermes_config",
                        "hermes",
                        provider_id=str(provider_id),
                        model_name=str(model_name),
                        description="Hermes 默认模型",
                    )
        dev_cache_path = os.path.join(root, "models_dev_cache.json")
        dev_cache = _json_or_none(dev_cache_path)
        if isinstance(dev_cache, dict):
            hermes_seen = True
            detected_sources.append(dev_cache_path)
            added = 0
            for provider_id, provider_data in dev_cache.items():
                if not isinstance(provider_data, dict):
                    continue
                models = provider_data.get("models", {})
                if not isinstance(models, dict):
                    continue
                for model_id, model_data in models.items():
                    if isinstance(model_data, dict):
                        model_label = model_data.get("name") or model_data.get("label") or model_id
                    else:
                        model_label = str(model_data) if model_data else model_id
                    if record_hidden_option(
                        f"hermes-cache:{provider_id}:{model_id}",
                        f"Hermes · {model_label}（{provider_id}）",
                        "Hermes",
                        "hermes_models_cache",
                        "hermes",
                        "platform_model_cache_hidden_from_user_options",
                        provider_id=str(provider_id),
                        model_name=str(model_id),
                        description="从 Hermes 模型缓存读取",
                    ):
                        added += 1
            if added == 0:
                notes.append("hermes_models_cache_empty")
    if not hermes_seen:
        notes.append("hermes_model_registry_not_found")

    return {
        "selected_model": selected_model,
        "selected_provider": selected_provider,
        "selected_option_id": selected_option_id,
        "user_default": {
            "configured": bool(user_model),
            "provider": user_provider,
            "provider_id": user_provider_id,
            "model_name": user_model,
            "base_url": user_base_url,
            "api_key_env": user_api_key_env,
            "selected_option_id": user_selected_option_id,
            "vector_recall_preference": vector_preference,
        },
        "vector_recall_preference": vector_preference,
        "vector_asset_status": vector_asset_status,
        "current_vector_model": current_vector_model,
        "selection_scope": "time_library_analysis_model_preference",
        "options": options,
        "counts": {
            "local": counts["local"],
            "openclaw": counts["openclaw"],
            "hermes": counts["hermes"],
            "total": max(0, len(options) - 1),
        },
        "detected_counts": {
            "local": detected_counts["local"],
            "openclaw": detected_counts["openclaw"],
            "hermes": detected_counts["hermes"],
            "total": sum(detected_counts.values()),
        },
        "hidden_counts": {
            "local": hidden_counts["local"],
            "openclaw": hidden_counts["openclaw"],
            "hermes": hidden_counts["hermes"],
            "total": sum(hidden_counts.values()),
        },
        "display_limits": {
            "local": display_limits["local"],
            "openclaw": display_limits["openclaw"],
            "hermes": display_limits["hermes"],
            "total": sum(display_limits.values()),
        },
        "display_limited": True,
        "candidate_policy": "product_surface_platform_default_and_current_config_only",
        "analysis_model_preference_configured": bool(user_model),
        "analysis_model_preference_consumers": [
            "evidence_bound_analysis",
            "preflight_answer_debug",
            "experience_distillation",
        ],
        "runtime_binding_ready": False,
        "runtime_binding_write_performed": False,
        "runtime_binding_status": "platform_defaults_not_modified",
        "hidden_option_examples": hidden_option_examples,
        "detected_sources": detected_sources[:40],
        "model_list_sources": [
            "model_config local_bge_m3 (internal recall/embedding only)",
            "model_config openclaw_model selected_model (if configured)",
            "Hermes config.yaml default model",
            "OpenClaw/Hermes recent session models",
            "OpenClaw/Hermes registries are counted but kept out of the first-version picker",
            "platform default",
        ],
        "config_write_performed": False,
        "notes": notes,
    }
