#!/usr/bin/env python3
"""Zhiyi model/runtime console controls under the Time River contract.

This module owns dry-run model binding, runtime-adapter preflight, request
envelope drafting for the P6 console. It is a derived
Zhiyi control surface: it may prepare authorized config writes, but it does
not create raw records and does not replace Time Origin.
"""

from __future__ import annotations

import glob
import json
import os
import urllib.request
from pathlib import Path

try:
    from src.granite_vector_assets import (
        granite_asset_status,
        granite_vector_config,
        start_granite_asset_prepare,
    )
except Exception:
    from granite_vector_assets import (
        granite_asset_status,
        granite_vector_config,
        start_granite_asset_prepare,
    )
try:
    from src.model_connection_smoke import run_model_connection_smoke as _run_model_connection_smoke
except Exception:
    from model_connection_smoke import run_model_connection_smoke as _run_model_connection_smoke
try:
    from src.model_api_key_store import (
        credential_ref_for,
        credential_status,
        default_api_key_env,
        is_valid_env_name,
        migrate_legacy_binding_secret,
        store_model_api_key,
    )
except Exception:
    from model_api_key_store import (
        credential_ref_for,
        credential_status,
        default_api_key_env,
        is_valid_env_name,
        migrate_legacy_binding_secret,
        store_model_api_key,
    )
try:
    from src import p6_model_options as _model_options
except Exception:
    import p6_model_options as _model_options

try:
    from src.config_loader import base_path
except Exception:
    from config_loader import base_path
try:
    from src.hermes_paths import hermes_config_paths, resolve_hermes_home
except Exception:
    from hermes_paths import hermes_config_paths, resolve_hermes_home
try:
    from src.p6_console_openclaw import query_openclaw_chat_send_targets
except Exception:
    from p6_console_openclaw import query_openclaw_chat_send_targets

try:
    from src import p6_zhiyi_usage_log as _zhiyi_usage_log
    from src.p6_zhiyi_usage_log import *
except Exception:
    import p6_zhiyi_usage_log as _zhiyi_usage_log
    from p6_zhiyi_usage_log import *

MEMCORE_ROOT = base_path()
ZHIYI_MODEL_RUNTIME_CONTRACT = "tiandao_zhiyi_model_runtime_console.v1"
ZHIYI_VECTOR_RECALL_PREFERENCE_VERSION = "vector-recall-preference.v1"
LAST_MODEL_CREDENTIAL_MIGRATION = {"migrated": False, "reason": "not_run"}


def configure_zhiyi_model_runtime(memcore_root):
    global MEMCORE_ROOT, LAST_MODEL_CREDENTIAL_MIGRATION
    MEMCORE_ROOT = str(memcore_root)
    try:
        LAST_MODEL_CREDENTIAL_MIGRATION = migrate_legacy_binding_secret(MEMCORE_ROOT)
    except Exception as exc:
        LAST_MODEL_CREDENTIAL_MIGRATION = {
            "migrated": False,
            "reason": "migration_failed",
            "error": exc.__class__.__name__,
            "secret_value_returned": False,
        }
    try:
        _zhiyi_usage_log.configure_zhiyi_usage_log(
            MEMCORE_ROOT,
            model_binding_plan_builder=build_zhiyi_model_binding_plan,
        )
    except Exception:
        pass


def run_model_connection_smoke(body=None, **kwargs):
    kwargs.setdefault("credential_root", MEMCORE_ROOT)
    return _run_model_connection_smoke(body, **kwargs)


try:
    _zhiyi_usage_log.configure_zhiyi_usage_log(
        MEMCORE_ROOT,
        model_binding_plan_builder=lambda body=None: build_zhiyi_model_binding_plan(body),
    )
except Exception:
    pass


def get_zhiyi_model_runtime_contract():
    return {
        "ok": True,
        "contract": ZHIYI_MODEL_RUNTIME_CONTRACT,
        "zh_name": "知意模型运行控制",
        "en_name": "Zhiyi Model Runtime Console",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "console_layer": "zhiyi_runtime_control",
        "derived_layer": "zhiyi",
        "read_only_by_default": True,
        "write_capable": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "config_write_performed": False,
        "model_call_performed": False,
        "not_raw_origin": True,
        "raw_origin_policy": "zhiyi_runtime_controls_do_not_replace_time_origin",
        "authorization_required_for_write": True,
        "live_model_call_enabled": False,
    }


def _compact_text(value, limit=180):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    if len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def _json_or_none(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except Exception:
        return None


def _atomic_write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def _restore_json(path, payload):
    target = Path(path)
    if payload is None:
        target.unlink(missing_ok=True)
        return
    _atomic_write_json(target, payload)


def _warm_vector_runtime():
    request = urllib.request.Request(
        f"http://127.0.0.1:{os.environ.get('TIME_LIBRARY_INTERNAL_P3_PORT', '19300')}/health?vector=warmup",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.load(response)
    vector_status = payload.get("vector_recall") if isinstance(payload, dict) else {}
    vector_warmup = payload.get("vector_warmup") if isinstance(payload, dict) else {}
    if not isinstance(vector_status, dict):
        vector_status = {}
    if not isinstance(vector_warmup, dict):
        vector_warmup = {}
    if not (
        vector_status.get("ok")
        and vector_status.get("model_loaded")
        and vector_status.get("table_loaded")
        and vector_warmup.get("ok")
    ):
        detail = vector_warmup.get("error") or vector_status.get("issues") or "vector_runtime_not_ready"
        raise RuntimeError(f"vector runtime warmup failed: {detail}")
    return {
        "ok": True,
        "model_loaded": True,
        "table_loaded": True,
        "seconds": vector_warmup.get("seconds"),
    }


def _write_vector_runtime_and_preference(
    model_config_path, model_config, user_path, user_payload,
    *, before_preference_write=None,
):
    previous_model_config = _json_or_none(model_config_path)
    previous_user_default = _json_or_none(user_path)
    guard_result = None
    try:
        _atomic_write_json(model_config_path, model_config)
        if before_preference_write is not None:
            guard_result = before_preference_write()
        _atomic_write_json(user_path, user_payload)
    except Exception:
        _restore_json(model_config_path, previous_model_config)
        _restore_json(user_path, previous_user_default)
        raise
    return guard_result


def _truthy_setting(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled", "vector", "bge", "bge_m3"}
    return bool(value)


def _vector_recall_requested(body) -> bool:
    if not isinstance(body, dict):
        return False
    for key in (
        "vector_bge_m3_enabled",
        "enable_bge_m3_vector",
        "bge_m3_enabled",
        "vector_recall_enabled",
    ):
        if key in body:
            return _truthy_setting(body.get(key))
    return False


def _vector_recall_setting_present(body) -> bool:
    return isinstance(body, dict) and any(
        key in body for key in (
            "vector_bge_m3_enabled", "enable_bge_m3_vector",
            "bge_m3_enabled", "vector_recall_enabled",
        )
    )


def _current_vector_model(model_config: dict) -> dict:
    recall_cfg = model_config.get("recall", {}) if isinstance(model_config, dict) else {}
    if not isinstance(recall_cfg, dict):
        recall_cfg = {}
    mode = str(recall_cfg.get("mode") or "off")
    configured = recall_cfg.get(mode)
    if not isinstance(configured, dict) and mode in {"off", "substring"}:
        configured = recall_cfg.get("local_vector")
    if not isinstance(configured, dict) and mode == "vector":
        configured = recall_cfg.get("local_vector")
    if not isinstance(configured, dict) and mode == "local_bge_m3":
        configured = recall_cfg.get("local_bge_m3")
    configured = configured if isinstance(configured, dict) else {}
    model_id = str(
        configured.get("model_id")
        or configured.get("embedding_model")
        or configured.get("model_name")
        or ""
    ).strip()
    fallback = recall_cfg.get("vector_fallback")
    if not isinstance(fallback, dict):
        fallback = {}
    return {
        "enabled": mode not in {"off", "substring"} and bool(model_id),
        "mode": mode,
        "model_id": model_id,
        "model_name": str(configured.get("model_name") or model_id),
        "embedding_dim": int(configured.get("embedding_dim") or 0),
        "pooling": str(configured.get("pooling") or ""),
        "table": str(configured.get("table") or ""),
        "storage": "LanceDB",
        "fallback_model_id": str(
            fallback.get("model_id")
            or fallback.get("embedding_model")
            or fallback.get("model_name")
            or ""
        ),
        "fallback_table": str(fallback.get("table") or ""),
    }


def _default_vector_recall_preference(enabled: bool = False) -> dict:
    return {
        "schema_version": ZHIYI_VECTOR_RECALL_PREFERENCE_VERSION,
        "enabled": bool(enabled),
        "default_recall_mode": "vector" if enabled else "substring",
        "fts5_recall": not bool(enabled),
        "applies_to": ["time_library_recall_default"],
        "hot_switch_status": "effective_for_new_gateway_requests",
        "requires_restart": False,
        "source": "zhiyi_model_binding.user.json",
    }


def _vector_recall_preference_from_user_default(user_default: dict) -> dict:
    if not isinstance(user_default, dict):
        return _default_vector_recall_preference(False)
    raw = user_default.get("vector_recall_preference")
    if isinstance(raw, dict):
        enabled = _truthy_setting(raw.get("enabled", False))
        result = _default_vector_recall_preference(enabled)
        result.update({
            "schema_version": str(raw.get("schema_version") or result["schema_version"]),
            "enabled": enabled,
            "default_recall_mode": "vector" if enabled else "substring",
            "fts5_recall": not enabled,
            "hot_switch_status": str(raw.get("hot_switch_status") or result["hot_switch_status"]),
            "requires_restart": _truthy_setting(raw.get("requires_restart", False)),
            "source": str(raw.get("source") or result["source"]),
        })
        return result
    return _default_vector_recall_preference(False)


def get_zhiyi_vector_recall_preference():
    user_default_path = os.path.join(str(MEMCORE_ROOT), "config", "zhiyi_model_binding.user.json")
    user_default = _json_or_none(user_default_path) or {}
    preference = _vector_recall_preference_from_user_default(user_default)
    preference.update({
        "target_user_default_path": user_default_path,
        "configured": isinstance(user_default.get("vector_recall_preference"), dict),
    })
    return preference


def _unique_existing(paths):
    seen = set()
    result = []
    for path in paths:
        if not path:
            continue
        path = os.path.expanduser(os.path.expandvars(str(path)))
        if path in seen:
            continue
        seen.add(path)
        if os.path.exists(path):
            result.append(path)
    return result


def _home_candidates():
    candidates = [os.path.expanduser("~")]
    for env_name in ("USERPROFILE", "HOME"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)
    return _unique_existing(candidates)


def get_zhiyi_model_options():
    return _model_options.build_model_options(
        MEMCORE_ROOT,
        json_or_none=_json_or_none,
        vector_recall_preference_from_user_default=_vector_recall_preference_from_user_default,
        default_vector_recall_preference=_default_vector_recall_preference,
        current_vector_model=_current_vector_model,
        granite_asset_status_fn=granite_asset_status,
        query_openclaw_chat_send_targets_fn=query_openclaw_chat_send_targets,
        resolve_hermes_home_fn=resolve_hermes_home,
        hermes_config_paths_fn=hermes_config_paths,
        unique_existing_fn=_unique_existing,
        home_candidates_fn=_home_candidates,
    )


def build_zhiyi_model_binding_plan(body=None):
    """Return a no-write plan for Time Library's analysis-model preference."""
    body = body or {}
    requested_id = str(
        body.get("model_id")
        or body.get("option_id")
        or body.get("selected_model")
        or ""
    )
    manual_model_name = str(body.get("model_name") or body.get("manual_model_name") or "").strip()
    manual_provider = str(body.get("provider") or body.get("manual_provider") or "").strip()
    manual_provider_id = str(body.get("provider_id") or body.get("manual_provider_id") or manual_provider).strip()
    manual_base_url = str(body.get("base_url") or body.get("manual_base_url") or "").strip()
    manual_api_key_env = str(body.get("api_key_env") or body.get("manual_api_key_env") or "").strip()
    manual_api_key_value = str(body.get("api_key_value") or "").strip()
    vector_preference = _default_vector_recall_preference(_vector_recall_requested(body))
    manual_override = body.get("manual_override")
    if isinstance(manual_override, str):
        manual_override = manual_override.strip().lower() in {"1", "true", "yes", "on"}
    elif manual_override is None:
        manual_override = requested_id == "__manual__" or not requested_id
    else:
        manual_override = bool(manual_override)
    is_manual = bool(manual_override and manual_model_name) or requested_id == "__manual__"
    options_data = get_zhiyi_model_options()
    options = options_data.get("options", [])
    option_by_id = {str(item.get("id", "")): item for item in options}
    hidden_by_id = {
        str(item.get("id", "")): item
        for item in options_data.get("hidden_option_examples", [])
    }
    config_path = os.path.join(str(MEMCORE_ROOT), "config", "model_config.json")
    user_default_path = os.path.join(str(MEMCORE_ROOT), "config", "zhiyi_model_binding.user.json")
    current_config = _json_or_none(config_path) or {}
    recall_cfg = current_config.get("recall", {}) if isinstance(current_config, dict) else {}
    current_runtime = {
        "model_config_path": config_path,
        "recall_mode": recall_cfg.get("mode", "local_bge_m3") if isinstance(recall_cfg, dict) else "unknown",
        "selected_provider": "",
        "selected_model": "",
    }
    if isinstance(recall_cfg, dict):
        openclaw_cfg = recall_cfg.get("openclaw_model", {})
        if isinstance(openclaw_cfg, dict):
            current_runtime["selected_provider"] = openclaw_cfg.get("selected_provider", "") or ""
            current_runtime["selected_model"] = openclaw_cfg.get("selected_model", "") or ""

    base = {
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "runtime_binding_write_performed": False,
        "requires_authorization_for_apply": True,
        "target_user_default_path": user_default_path,
        "target_runtime_config_path": config_path,
        "current_runtime": current_runtime,
        "selection_scope": "time_library_analysis_model_preference",
        "detected_counts": options_data.get("detected_counts", {}),
        "counts": options_data.get("counts", {}),
        "vector_recall_preference": vector_preference,
    }
    if manual_api_key_env and not is_valid_env_name(manual_api_key_env):
        result = dict(base)
        result.update({
            "ok": False,
            "error": "invalid_api_key_env_name",
            "secret_like_value_rejected": True,
            "secret_value_returned": False,
            "notes": ["api_key_must_use_the_password_field_not_the_environment_name_field"],
        })
        return result

    if is_manual:
        if not manual_model_name:
            result = dict(base)
            result.update({
                "ok": False,
                "error": "manual model name is required",
                "model_id": requested_id,
                "notes": ["manual_model_name_required"],
            })
            return result
        requested_id = f"manual:{manual_provider_id or manual_provider or 'configured'}:{manual_model_name}"
        option = {
            "id": requested_id,
            "label": f"{manual_provider or 'Custom'} · {manual_model_name}",
            "provider": manual_provider or "Custom",
            "provider_id": manual_provider_id,
            "source": "manual_user_default",
            "category": "manual",
            "model_name": manual_model_name,
            "base_url": manual_base_url,
            "api_key_env": manual_api_key_env or default_api_key_env(manual_provider, manual_provider_id),
            "description": "手动填写",
        }
    elif requested_id not in option_by_id:
        hidden = hidden_by_id.get(requested_id)
        result = dict(base)
        result.update({
            "ok": False,
            "error": "model option is not in first-version user options",
            "model_id": requested_id,
            "hidden_option": hidden,
            "notes": [
                "only_visible_first_version_options_can_be_bound",
                "local_embedding_model_is_internal_not_user_llm",
            ] if hidden else ["unknown_or_hidden_model_option"],
        })
        return result
    else:
        option = dict(option_by_id[requested_id])
    provider = option.get("provider", "auto")
    provider_id = option.get("provider_id", provider)
    model_name = option.get("model_name") or requested_id
    base_url = option.get("base_url", "")
    api_key_env = str(option.get("api_key_env") or "").strip()
    if not is_valid_env_name(api_key_env):
        api_key_env = default_api_key_env(provider, provider_id)
    credential_ref = str(option.get("credential_ref") or "").strip()
    if not credential_ref and requested_id:
        credential_ref = credential_ref_for(provider, provider_id)
    if requested_id == "":
        binding_kind = "platform_default"
        provider_id = ""
        model_name = ""
        base_url = ""
        api_key_env = ""
        credential_ref = ""
    else:
        binding_kind = "user_default_platform_model"

    saved_credential = credential_status(MEMCORE_ROOT, credential_ref)
    credential_configured = bool(manual_api_key_value or saved_credential.get("configured"))
    would_write_user_default = {
        "schema_version": "1.0",
        "binding_kind": binding_kind,
        "selected_option_id": requested_id,
        "provider": provider,
        "provider_id": provider_id,
        "model_name": model_name,
        "base_url": base_url,
        "api_key_env": api_key_env,
        "credential_ref": credential_ref,
        "transport": option.get("transport", "openai_compatible_http"),
        "source": option.get("source", ""),
        "selection_scope": "time_library_analysis_model_preference",
        "applies_to": [
            "evidence_bound_analysis",
            "preflight_answer_debug",
            "experience_distillation",
            "local_tool_identification",
        ],
        "vector_recall_preference": vector_preference,
        "write_requires_authorization": True,
        "secrets_stored": credential_configured,
        "secret_storage": "encrypted_local_file" if credential_configured else "environment",
        "secret_values_returned": False,
        "model_call_performed": False,
    }
    runtime_blockers = ["platform_model_defaults_are_outside_this_preference_scope"]
    runtime_config_plan = {
        "apply_now": False,
        "reason": "analysis_model_preference_does_not_mutate_platform_defaults",
        "current_recall_mode": current_runtime["recall_mode"],
        "candidate_runtime_mode": "platform_default" if requested_id == "" else "platform_model_user_default",
        "default_gateway_recall_mode_after_save": vector_preference["default_recall_mode"],
        "default_gateway_fts5_recall_after_save": vector_preference["fts5_recall"],
        "vector_preference_hot_switch_status": vector_preference["hot_switch_status"],
        "vector_preference_requires_restart": vector_preference["requires_restart"],
        "blocked_by": runtime_blockers,
        "would_not_set_recall_mode_to_openclaw_model_without_adapter": True,
    }
    result = dict(base)
    result.update({
        "ok": True,
        "model_id": requested_id,
        "selected_option": option,
        "binding_kind": binding_kind,
        "user_default_strategy": "time_library_analysis_model_preference",
        "analysis_model_preference_ready": bool(model_name or requested_id == ""),
        "credential_write_planned": bool(manual_api_key_value),
        "credential_configured": credential_configured,
        "secret_value_returned": False,
        "analysis_model_preference_write_performed": False,
        "runtime_binding_plan_ready": True,
        "runtime_binding_ready": False,
        "runtime_binding_status": "platform_defaults_not_modified",
        "config_write_performed": False,
        "would_write_user_default": would_write_user_default,
        "runtime_config_plan": runtime_config_plan,
        "notes": [
            "backend_validated_visible_model_option",
            "preference_is_consumed_by_time_library_analysis_paths_after_save",
            "platform_default_model_is_not_modified",
        ],
    })
    return result


def apply_zhiyi_model_binding_user_default(body=None):
    body = body or {}
    plan = build_zhiyi_model_binding_plan(body)
    if not plan.get("ok"):
        return plan
    payload = dict(plan.get("would_write_user_default") or {})
    path = plan.get("target_user_default_path")
    credential_result = credential_status(MEMCORE_ROOT, payload.get("credential_ref", ""))
    api_key_value = str(body.get("api_key_value") or "").strip()
    if api_key_value:
        try:
            credential_result = store_model_api_key(
                MEMCORE_ROOT,
                payload.get("credential_ref", ""),
                api_key_value,
            )
        except Exception as exc:
            result = dict(plan)
            result.update({
                "ok": False,
                "dry_run": False,
                "write_performed": False,
                "config_write_performed": False,
                "credential_write_performed": False,
                "error": "credential_store_write_failed",
                "error_type": exc.__class__.__name__,
                "secret_value_returned": False,
            })
            return result
        payload["secrets_stored"] = True
        payload["secret_storage"] = "encrypted_local_file"
        payload["secret_values_returned"] = False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if payload.get("binding_kind") == "platform_default":
        payload = {
            "schema_version": "1.0",
            "binding_kind": "platform_default",
            "selected_option_id": "",
            "provider": "auto",
            "provider_id": "",
            "model_name": "",
            "source": "platform_default",
            "selection_scope": "time_library_analysis_model_preference",
            "applies_to": [
                "evidence_bound_analysis",
                "preflight_answer_debug",
                "experience_distillation",
                "local_tool_identification",
            ],
            "vector_recall_preference": _default_vector_recall_preference(_vector_recall_requested(body or {})),
            "secrets_stored": False,
            "model_call_performed": False,
        }
    vector_requested = _vector_recall_requested(body or {})
    vector_assets = granite_asset_status(MEMCORE_ROOT, verify=vector_requested)
    def finalize_vector_enable(result):
        if not result.get("ready"):
            return
        model_config_path = os.path.join(str(MEMCORE_ROOT), "config", "model_config.json")
        model_config = _json_or_none(model_config_path) or {}
        recall = model_config.setdefault("recall", {})
        recall["local_vector"] = granite_vector_config(MEMCORE_ROOT)
        recall["mode"] = "local_vector"
        ready_payload = dict(payload)
        ready_payload["vector_recall_preference"] = _default_vector_recall_preference(True)
        ready_payload["write_requires_authorization"] = False
        _write_vector_runtime_and_preference(
            model_config_path, model_config, path, ready_payload,
            before_preference_write=_warm_vector_runtime,
        )

    if vector_requested and not vector_assets.get("ready"):
        started = start_granite_asset_prepare(MEMCORE_ROOT, on_complete=finalize_vector_enable)
        result = dict(plan)
        result.update({
            "ok": True,
            "dry_run": False,
            "write_performed": False,
            "config_write_performed": False,
            "runtime_binding_write_performed": False,
            "credential_write_performed": bool(api_key_value),
            "credential_status": credential_result,
            "credential_configured": bool(credential_result.get("configured")),
            "secret_value_returned": False,
            "vector_enable_pending": True,
            "vector_asset_status": started,
            "vector_recall_preference": _default_vector_recall_preference(False),
            "notes": [
                "granite_download_on_enable_started",
                "vector_preference_not_enabled_until_assets_ready",
                "default_recall_remains_fts5_bm25",
            ],
        })
        return result
    runtime_mode_written = False
    if _vector_recall_setting_present(body or {}):
        model_config_path = os.path.join(str(MEMCORE_ROOT), "config", "model_config.json")
        model_config = _json_or_none(model_config_path) or {}
        recall = model_config.setdefault("recall", {})
        if vector_requested:
            recall["local_vector"] = granite_vector_config(MEMCORE_ROOT)
        recall["mode"] = "local_vector" if vector_requested else "substring"
        runtime_mode_written = True
    payload["write_requires_authorization"] = False
    if runtime_mode_written:
        vector_warmup = _write_vector_runtime_and_preference(
            model_config_path, model_config, path, payload,
            before_preference_write=_warm_vector_runtime if vector_requested else None,
        )
    else:
        vector_warmup = None
        _atomic_write_json(path, payload)
    result = dict(plan)
    result.update({
        "dry_run": False,
        "write_performed": True,
        "config_write_performed": True,
        "analysis_model_preference_write_performed": True,
        "credential_write_performed": bool(api_key_value),
        "credential_status": credential_result,
        "secret_value_returned": False,
        "platform_model_config_write_performed": False,
        "runtime_binding_write_performed": runtime_mode_written,
        "written": payload,
        "vector_asset_status": vector_assets,
        "vector_warmup": vector_warmup or {},
        "notes": [
            "user_default_model_saved",
            "time_library_analysis_paths_read_this_preference",
            "platform_default_model_not_modified",
            "vector_recall_preference_saved",
            "api_key_value_encrypted_and_not_returned" if api_key_value else "saved_credential_preserved_or_environment_used",
            "model_call_not_performed",
            "runtime_recall_mode_updated" if runtime_mode_written else "runtime_recall_mode_unchanged",
        ],
    })
    return result


ZHIYI_MODEL_BINDING_APPLY_GATE_VERSION = "p1-9.1"


def get_zhiyi_model_binding_apply_gate_policy():
    """Return the no-write authorization gate for future model binding apply."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "runtime_binding_write_performed": False,
        "policy_version": ZHIYI_MODEL_BINDING_APPLY_GATE_VERSION,
        "dry_run_endpoint": "/api/v1/zhiyi/model-binding/apply-gate/dry-run",
        "future_apply_endpoint": "/api/v1/zhiyi/model-binding/apply",
        "live_apply_endpoint_enabled": False,
        "required_authorization": [
            "confirm_write_user_default",
            "confirm_no_model_config_recall_mutation",
            "confirm_runtime_adapter_gap_understood",
            "operator",
            "reason",
        ],
        "guards": [
            "model_option_must_be_visible_first_version_option",
            "target_user_default_path_must_be_memcore_config",
            "target_runtime_config_path_must_be_read_only_model_config",
            "user_default_schema_must_be_1_0",
            "runtime_adapter_must_remain_unapplied_until_implemented",
            "dry_run_must_not_write_config",
        ],
        "write_contract": {
            "user_default_format": "json",
            "encoding": "utf-8",
            "file_mode_after_create": "0600",
            "target": "config/zhiyi_model_binding.user.json",
            "model_config_mutation": False,
        },
        "completion_claim": {
            "production_model_binding_apply_done": False,
            "runtime_adapter_done": False,
            "live_9850_updated": False,
        },
    }


def build_zhiyi_model_binding_apply_gate_dry_run(body=None):
    """Check future model-binding apply authorization without writing config."""
    body = body or {}
    binding_plan = build_zhiyi_model_binding_plan(body)
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        value = authorization.get(name, body.get(name))
        if value is True:
            return True
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "confirmed", "confirm")
        return False

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    required_checks = {
        "confirm_write_user_default": confirmed("confirm_write_user_default"),
        "confirm_no_model_config_recall_mutation": confirmed("confirm_no_model_config_recall_mutation"),
        "confirm_runtime_adapter_gap_understood": confirmed("confirm_runtime_adapter_gap_understood"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]

    target_user_default = os.path.abspath(str(binding_plan.get("target_user_default_path") or ""))
    expected_user_default = os.path.abspath(os.path.join(str(MEMCORE_ROOT), "config", "zhiyi_model_binding.user.json"))
    target_runtime_config = os.path.abspath(str(binding_plan.get("target_runtime_config_path") or ""))
    expected_runtime_config = os.path.abspath(os.path.join(str(MEMCORE_ROOT), "config", "model_config.json"))
    would_write = binding_plan.get("would_write_user_default", {}) if isinstance(binding_plan.get("would_write_user_default"), dict) else {}
    runtime_plan = binding_plan.get("runtime_config_plan", {}) if isinstance(binding_plan.get("runtime_config_plan"), dict) else {}
    blocked_by = runtime_plan.get("blocked_by", []) if isinstance(runtime_plan.get("blocked_by"), list) else []

    guard_checks = {
        "model_binding_plan_ok": bool(binding_plan.get("ok")),
        "target_user_default_path": target_user_default == expected_user_default,
        "target_runtime_config_path": target_runtime_config == expected_runtime_config,
        "user_default_schema": str(would_write.get("schema_version", "")) == "1.0",
        "user_default_write_requires_authorization": bool(would_write.get("write_requires_authorization", False)),
        "runtime_adapter_not_implemented": (
            not bool(binding_plan.get("runtime_binding_ready", False))
            and "platform_llm_selection_needs_runtime_adapter_before_apply" in blocked_by
        ),
        "model_config_recall_not_mutated": bool(runtime_plan.get("apply_now")) is False,
        "dry_run_no_write": (
            bool(binding_plan.get("write_performed", False)) is False
            and bool(binding_plan.get("config_write_performed", False)) is False
            and bool(binding_plan.get("runtime_binding_write_performed", False)) is False
        ),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    authorization_complete = not missing
    future_user_default_apply_ready = authorization_complete and not guard_failures
    future_runtime_binding_ready = False
    if guard_failures:
        gate_status = "blocked_guard_failure"
    elif not authorization_complete:
        gate_status = "blocked_missing_authorization"
    else:
        gate_status = "ready_for_future_user_default_apply_runtime_adapter_blocked"

    return {
        "ok": not guard_failures,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_binding_write_performed": False,
        "apply_allowed": False,
        "apply_performed": False,
        "live_apply_endpoint_enabled": False,
        "policy_version": ZHIYI_MODEL_BINDING_APPLY_GATE_VERSION,
        "gate_status": gate_status,
        "authorization_complete": authorization_complete,
        "authorization_missing": missing,
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "guard_failures": guard_failures,
        "future_user_default_apply_ready": future_user_default_apply_ready,
        "future_runtime_binding_ready": future_runtime_binding_ready,
        "required_authorization": get_zhiyi_model_binding_apply_gate_policy()["required_authorization"],
        "future_apply_endpoint": "/api/v1/zhiyi/model-binding/apply",
        "dry_run_endpoint": "/api/v1/zhiyi/model-binding/apply-gate/dry-run",
        "target_user_default_path": binding_plan.get("target_user_default_path"),
        "target_runtime_config_path": binding_plan.get("target_runtime_config_path"),
        "target_user_default_exists": os.path.exists(binding_plan.get("target_user_default_path", "")),
        "target_runtime_config_exists": os.path.exists(binding_plan.get("target_runtime_config_path", "")),
        "would_write_user_default": would_write,
        "runtime_adapter_plan": {
            "required_before_runtime_binding_apply": True,
            "implemented": False,
            "runtime_binding_ready": False,
            "blocked_by": blocked_by,
            "model_config_mutation_allowed_now": False,
        },
        "model_binding_plan": binding_plan,
        "completion_claim": get_zhiyi_model_binding_apply_gate_policy()["completion_claim"],
        "notes": [
            "model_binding_apply_gate_dry_run_only",
            "no_user_default_config_written",
            "no_model_config_or_runtime_adapter_write",
            "browser_storage_remains_ui_cache_until_authorized_apply",
        ],
    }


ZHIYI_RUNTIME_ADAPTER_DRY_RUN_VERSION = "p1-10.1"


def get_zhiyi_runtime_adapter_dry_run_policy():
    """Return the no-call runtime adapter preflight contract."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "model_call_performed": False,
        "policy_version": ZHIYI_RUNTIME_ADAPTER_DRY_RUN_VERSION,
        "dry_run_endpoint": "/api/v1/zhiyi/runtime-adapter/dry-run",
        "future_runtime_apply_endpoint": "/api/v1/zhiyi/runtime-adapter/apply",
        "live_runtime_apply_endpoint_enabled": False,
        "live_model_call_enabled": False,
        "requires_authorization_for_runtime_apply": True,
        "requires_authorization_for_model_call": True,
        "checks": [
            "selected_model_must_be_visible_first_version_option",
            "model_binding_apply_gate_must_be_checked",
            "runtime_config_snapshot_is_read_only",
            "user_default_config_snapshot_is_read_only",
            "adapter_contract_may_prepare_mapping_but_must_not_write",
            "platform_client_resolution_is_not_executed",
            "model_call_is_not_executed",
        ],
        "completion_claim": {
            "runtime_adapter_contract_done": True,
            "runtime_adapter_apply_done": False,
            "runtime_model_call_done": False,
            "live_9850_updated": False,
        },
    }


def _zhiyi_runtime_file_snapshot(path):
    path = str(path or "")
    snapshot = {
        "path": path,
        "exists": False,
        "is_file": False,
        "size_bytes": 0,
        "mtime_utc": "",
        "read_only_probe": True,
        "write_performed": False,
    }
    if not path:
        return snapshot
    try:
        snapshot["exists"] = os.path.exists(path)
        snapshot["is_file"] = os.path.isfile(path)
        if snapshot["exists"]:
            stat = os.stat(path)
            snapshot["size_bytes"] = stat.st_size
            snapshot["mtime_utc"] = datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception as exc:
        snapshot["error"] = str(exc)
    return snapshot


def build_zhiyi_runtime_adapter_dry_run(body=None):
    """Preflight the first runtime-adapter contract without config writes or model calls."""
    body = body or {}
    binding_plan = build_zhiyi_model_binding_plan(body)
    apply_gate = build_zhiyi_model_binding_apply_gate_dry_run(body)
    runtime_config_path = binding_plan.get("target_runtime_config_path")
    user_default_path = binding_plan.get("target_user_default_path")
    runtime_snapshot = _zhiyi_runtime_file_snapshot(runtime_config_path)
    user_default_snapshot = _zhiyi_runtime_file_snapshot(user_default_path)
    selected_option = binding_plan.get("selected_option", {}) if isinstance(binding_plan.get("selected_option"), dict) else {}
    runtime_plan = binding_plan.get("runtime_config_plan", {}) if isinstance(binding_plan.get("runtime_config_plan"), dict) else {}
    blocked_by = runtime_plan.get("blocked_by", []) if isinstance(runtime_plan.get("blocked_by"), list) else []

    binding_ok = bool(binding_plan.get("ok"))
    gate_guard_ok = not bool(apply_gate.get("guard_failures", []))
    authorization_complete = bool(apply_gate.get("authorization_complete"))
    contract_checks = {
        "model_binding_plan_ok": binding_ok,
        "apply_gate_guard_ok": gate_guard_ok,
        "runtime_config_snapshot_read_only": bool(runtime_snapshot.get("read_only_probe")) and not bool(runtime_snapshot.get("write_performed")),
        "user_default_snapshot_read_only": bool(user_default_snapshot.get("read_only_probe")) and not bool(user_default_snapshot.get("write_performed")),
        "runtime_config_plan_is_no_apply": bool(runtime_plan.get("apply_now")) is False,
        "runtime_adapter_not_live": True,
        "model_call_not_performed": True,
        "no_config_or_profile_write": (
            bool(binding_plan.get("write_performed", False)) is False
            and bool(binding_plan.get("config_write_performed", False)) is False
            and bool(binding_plan.get("runtime_binding_write_performed", False)) is False
            and bool(apply_gate.get("config_write_performed", False)) is False
            and bool(apply_gate.get("runtime_binding_write_performed", False)) is False
        ),
    }
    contract_failures = [name for name, ok in contract_checks.items() if not ok]
    if contract_failures:
        preflight_status = "blocked_contract_check_failure"
    elif not authorization_complete:
        preflight_status = "contract_ready_missing_apply_authorization_runtime_adapter_blocked"
    else:
        preflight_status = "contract_ready_runtime_adapter_blocked_no_model_call"

    adapter_stages = [
        {
            "id": "visible_model_option",
            "status": "passed" if binding_ok else "blocked",
            "evidence": binding_plan.get("model_id", ""),
        },
        {
            "id": "user_default_apply_gate",
            "status": apply_gate.get("gate_status", "unknown"),
            "authorization_complete": authorization_complete,
            "future_user_default_apply_ready": bool(apply_gate.get("future_user_default_apply_ready", False)),
        },
        {
            "id": "runtime_config_mapping_contract",
            "status": "dry_run_mapping_ready" if binding_ok else "blocked",
            "apply_now": False,
            "blocked_by": blocked_by,
        },
        {
            "id": "platform_runtime_client_resolution",
            "status": "not_executed_dry_run_only",
            "client_resolved": False,
        },
        {
            "id": "model_call_execution",
            "status": "not_executed_runtime_adapter_not_implemented",
            "model_call_allowed": False,
            "model_call_performed": False,
        },
    ]

    return {
        "ok": not contract_failures,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "model_call_allowed": False,
        "model_call_performed": False,
        "runtime_apply_allowed": False,
        "runtime_apply_performed": False,
        "policy_version": ZHIYI_RUNTIME_ADAPTER_DRY_RUN_VERSION,
        "preflight_status": preflight_status,
        "runtime_adapter_contract_ready": not contract_failures,
        "model_call_contract_preflight_ready": not contract_failures,
        "model_call_ready": False,
        "requires_authorization_for_runtime_apply": True,
        "requires_authorization_for_model_call": True,
        "selected_option": selected_option,
        "model_binding_plan": binding_plan,
        "apply_gate_summary": {
            "policy_version": apply_gate.get("policy_version"),
            "gate_status": apply_gate.get("gate_status"),
            "authorization_complete": authorization_complete,
            "authorization_missing": apply_gate.get("authorization_missing", []),
            "guard_failures": apply_gate.get("guard_failures", []),
            "future_user_default_apply_ready": bool(apply_gate.get("future_user_default_apply_ready", False)),
            "future_runtime_binding_ready": False,
        },
        "runtime_config_snapshot": runtime_snapshot,
        "user_default_snapshot": user_default_snapshot,
        "runtime_adapter_stages": adapter_stages,
        "contract_checks": contract_checks,
        "contract_failures": contract_failures,
        "model_call_contract": {
            "requested_option_id": binding_plan.get("model_id", ""),
            "provider": selected_option.get("provider", "auto"),
            "provider_id": selected_option.get("provider_id", ""),
            "model_name": selected_option.get("model_name", ""),
            "transport": "not_selected_dry_run_only",
            "platform_scope": selected_option.get("provider", "platform_default"),
            "client_resolved": False,
            "request_built": False,
            "response_received": False,
            "called": False,
            "not_called_reason": "runtime_adapter_not_implemented_no_live_model_call",
        },
        "blockers": [
            "runtime_adapter_not_implemented",
            "live_runtime_apply_endpoint_disabled",
            "model_call_disabled_for_p1_10_dry_run",
            "config_model_config_json_left_read_only",
        ],
        "completion_claim": get_zhiyi_runtime_adapter_dry_run_policy()["completion_claim"],
        "notes": [
            "runtime_adapter_preflight_contract_only",
            "no_model_call_executed",
            "no_config_or_user_default_write",
            "no_service_restart",
            "usage_log_and_model_binding_apply_remain_separate_gates",
        ],
    }


ZHIYI_RUNTIME_ADAPTER_APPLY_GATE_VERSION = "p1-11.1"


def get_zhiyi_runtime_adapter_apply_gate_policy():
    """Return the no-write/no-call gate for future runtime adapter apply."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "model_call_performed": False,
        "policy_version": ZHIYI_RUNTIME_ADAPTER_APPLY_GATE_VERSION,
        "dry_run_endpoint": "/api/v1/zhiyi/runtime-adapter/apply-gate/dry-run",
        "future_apply_endpoint": "/api/v1/zhiyi/runtime-adapter/apply",
        "live_apply_endpoint_enabled": False,
        "live_model_call_enabled": False,
        "required_authorization": [
            "confirm_write_user_default",
            "confirm_no_model_config_recall_mutation",
            "confirm_runtime_adapter_gap_understood",
            "confirm_runtime_adapter_apply_contract",
            "confirm_platform_client_resolver_read_only",
            "confirm_no_model_call",
            "operator",
            "reason",
        ],
        "guards": [
            "runtime_preflight_contract_must_be_ok",
            "user_default_apply_gate_must_have_no_guard_failures",
            "runtime_config_snapshot_must_be_read_only",
            "platform_client_resolver_must_be_read_only",
            "platform_client_contract_must_be_ready",
            "runtime_apply_endpoint_must_remain_disabled",
            "model_call_must_not_execute",
            "dry_run_must_not_write_config_or_logs",
        ],
        "completion_claim": {
            "runtime_adapter_apply_gate_done": True,
            "platform_client_resolver_contract_done": True,
            "runtime_adapter_apply_done": False,
            "runtime_model_call_done": False,
            "live_9850_updated": False,
        },
    }


def _zhiyi_platform_runtime_profile_snapshot(platform_key):
    profile = {}
    source = "tools.runtime_profile_read_only"
    try:
        import sys as _sys
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tools_dir = os.path.join(repo_root, "tools")
        if tools_dir not in _sys.path:
            _sys.path.insert(0, tools_dir)
        from runtime_profile import build_openclaw_profile, build_hermes_profile
        if platform_key == "openclaw":
            profile = build_openclaw_profile()
        elif platform_key == "hermes":
            profile = build_hermes_profile()
    except Exception as exc:
        profile = {"status": "unavailable", "error": str(exc)}
        source = "runtime_profile_unavailable"

    health = profile.get("health", {}) if isinstance(profile.get("health"), dict) else {}
    selected_runtime = profile.get("selected_runtime", {}) if isinstance(profile.get("selected_runtime"), dict) else {}
    instances = profile.get("instances", []) if isinstance(profile.get("instances"), list) else []
    running_instance = profile.get("running_instance") if isinstance(profile, dict) else None
    live_client_active = (
        bool(health.get("reachable", False))
        or str(profile.get("status", "")) == "active"
        or bool(running_instance)
    )
    return {
        "platform": platform_key,
        "profile_source": source,
        "profile_status": profile.get("status", "unknown"),
        "version": profile.get("version"),
        "selected_runtime_source": selected_runtime.get("source", ""),
        "instances_count": len(instances),
        "running_instance_detected": bool(running_instance),
        "health_reachable": bool(health.get("reachable", False)),
        "health_url": health.get("health_url"),
        "health_status_code": health.get("status_code"),
        "config_detected": bool(profile.get("config")),
        "install_root": profile.get("install_root"),
        "live_client_active_now": live_client_active,
        "read_only_probe": True,
        "write_performed": False,
        "model_call_performed": False,
    }


def _zhiyi_platform_client_resolver_dry_run(selected_option, binding_plan, body=None):
    body = body or {}
    selected_option = selected_option if isinstance(selected_option, dict) else {}
    option_id = str(binding_plan.get("model_id", ""))
    category = str(selected_option.get("category") or "").lower()
    provider = str(selected_option.get("provider") or "").lower()
    platform_key = category or provider or "platform_default"
    if not option_id:
        platform_key = "platform_default"
    elif "openclaw" in platform_key:
        platform_key = "openclaw"
    elif "hermes" in platform_key:
        platform_key = "hermes"
    elif not bool(binding_plan.get("ok")):
        platform_key = "unknown"

    base = {
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "model_call_performed": False,
        "selected_option_id": option_id,
        "platform": platform_key,
        "provider": selected_option.get("provider", "auto"),
        "provider_id": selected_option.get("provider_id", ""),
        "model_name": selected_option.get("model_name", ""),
        "resolver_read_only_probe_performed": False,
        "client_resolved_for_apply": False,
        "client_contract_ready": False,
        "live_client_active_now": False,
        "profile_snapshot": {},
        "transport_candidates": [],
    }

    if not bool(binding_plan.get("ok")):
        base.update({
            "client_resolution_status": "blocked_no_visible_model_option",
            "blockers": ["model_binding_plan_not_ok"],
        })
        return base

    if platform_key == "platform_default":
        base.update({
            "client_resolution_status": "deferred_to_platform_default",
            "client_contract_ready": True,
            "blockers": ["runtime_adapter_apply_not_enabled"],
            "transport_candidates": ["platform_default_deferred"],
        })
        return base

    if platform_key in ("openclaw", "hermes"):
        profile_snapshot = _zhiyi_platform_runtime_profile_snapshot(platform_key)
        live_active = bool(profile_snapshot.get("live_client_active_now", False))
        if live_active:
            status = "read_only_client_profile_active_model_call_blocked"
        elif profile_snapshot.get("profile_status") in ("detected", "experimental"):
            status = "read_only_client_profile_detected_model_call_blocked"
        else:
            status = "read_only_client_profile_not_active_model_call_blocked"
        transport_candidates = {
            "openclaw": ["openclaw_runtime_profile", "openclaw_gateway_protocol4_future_adapter"],
            "hermes": ["hermes_runtime_profile", "hermes_health_endpoint_future_adapter"],
        }[platform_key]
        base.update({
            "client_resolution_status": status,
            "resolver_read_only_probe_performed": True,
            "client_contract_ready": True,
            "live_client_active_now": live_active,
            "profile_snapshot": profile_snapshot,
            "transport_candidates": transport_candidates,
            "blockers": [
                "runtime_adapter_apply_not_enabled",
                "model_call_disabled_for_apply_gate_dry_run",
            ],
        })
        return base

    base.update({
        "client_resolution_status": "blocked_unknown_platform",
        "blockers": ["unknown_platform_for_runtime_adapter"],
    })
    return base


def build_zhiyi_runtime_adapter_apply_gate_dry_run(body=None):
    """Check future runtime adapter apply authorization without writes or model calls."""
    body = body or {}
    authorization = body.get("authorization", {})
    if not isinstance(authorization, dict):
        authorization = {}

    def confirmed(name):
        value = authorization.get(name, body.get(name))
        if value is True:
            return True
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "1", "confirmed", "confirm")
        return False

    def present(name):
        return bool(str(authorization.get(name, body.get(name, "")) or "").strip())

    preflight = build_zhiyi_runtime_adapter_dry_run(body)
    binding_plan = preflight.get("model_binding_plan", {}) if isinstance(preflight.get("model_binding_plan"), dict) else {}
    selected_option = preflight.get("selected_option", {}) if isinstance(preflight.get("selected_option"), dict) else {}
    apply_gate_summary = preflight.get("apply_gate_summary", {}) if isinstance(preflight.get("apply_gate_summary"), dict) else {}
    runtime_snapshot = preflight.get("runtime_config_snapshot", {}) if isinstance(preflight.get("runtime_config_snapshot"), dict) else {}
    client_resolution = _zhiyi_platform_client_resolver_dry_run(selected_option, binding_plan, body)

    required_checks = {
        "confirm_write_user_default": confirmed("confirm_write_user_default"),
        "confirm_no_model_config_recall_mutation": confirmed("confirm_no_model_config_recall_mutation"),
        "confirm_runtime_adapter_gap_understood": confirmed("confirm_runtime_adapter_gap_understood"),
        "confirm_runtime_adapter_apply_contract": confirmed("confirm_runtime_adapter_apply_contract"),
        "confirm_platform_client_resolver_read_only": confirmed("confirm_platform_client_resolver_read_only"),
        "confirm_no_model_call": confirmed("confirm_no_model_call"),
        "operator": present("operator"),
        "reason": present("reason"),
    }
    missing = [name for name, ok in required_checks.items() if not ok]
    authorization_complete = not missing

    guard_checks = {
        "runtime_preflight_contract_ok": bool(preflight.get("ok")),
        "user_default_apply_gate_has_no_guard_failures": not bool(apply_gate_summary.get("guard_failures", [])),
        "user_default_apply_gate_ready_when_authorized": (
            not authorization_complete
            or bool(apply_gate_summary.get("future_user_default_apply_ready", False))
        ),
        "runtime_config_snapshot_read_only": (
            bool(runtime_snapshot.get("read_only_probe"))
            and not bool(runtime_snapshot.get("write_performed"))
        ),
        "platform_client_resolver_read_only": (
            bool(client_resolution.get("dry_run"))
            and not bool(client_resolution.get("write_performed"))
            and not bool(client_resolution.get("model_call_performed"))
        ),
        "platform_client_contract_ready": bool(client_resolution.get("client_contract_ready")),
        "runtime_apply_endpoint_disabled": True,
        "model_call_not_performed": (
            bool(preflight.get("model_call_performed", False)) is False
            and bool(client_resolution.get("model_call_performed", False)) is False
        ),
        "dry_run_no_write": (
            bool(preflight.get("write_performed", False)) is False
            and bool(preflight.get("config_write_performed", False)) is False
            and bool(preflight.get("runtime_config_write_performed", False)) is False
            and bool(preflight.get("runtime_binding_write_performed", False)) is False
            and bool(client_resolution.get("runtime_config_write_performed", False)) is False
            and bool(client_resolution.get("runtime_binding_write_performed", False)) is False
        ),
    }
    guard_failures = [name for name, ok in guard_checks.items() if not ok]
    if guard_failures:
        gate_status = "blocked_guard_failure"
    elif not authorization_complete:
        gate_status = "blocked_missing_authorization"
    else:
        gate_status = "ready_for_future_runtime_apply_client_contract_ready_model_call_blocked"

    future_runtime_apply_ready = authorization_complete and not guard_failures
    return {
        "ok": not guard_failures,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "usage_log_write_performed": False,
        "apply_allowed": False,
        "runtime_apply_allowed": False,
        "runtime_apply_performed": False,
        "model_call_allowed": False,
        "model_call_performed": False,
        "live_apply_endpoint_enabled": False,
        "policy_version": ZHIYI_RUNTIME_ADAPTER_APPLY_GATE_VERSION,
        "gate_status": gate_status,
        "authorization_complete": authorization_complete,
        "authorization_missing": missing,
        "authorization_checks": required_checks,
        "guard_checks": guard_checks,
        "guard_failures": guard_failures,
        "future_runtime_apply_ready": future_runtime_apply_ready,
        "future_model_call_ready": False,
        "required_authorization": get_zhiyi_runtime_adapter_apply_gate_policy()["required_authorization"],
        "future_apply_endpoint": "/api/v1/zhiyi/runtime-adapter/apply",
        "dry_run_endpoint": "/api/v1/zhiyi/runtime-adapter/apply-gate/dry-run",
        "runtime_preflight": preflight,
        "platform_client_resolution": client_resolution,
        "completion_claim": get_zhiyi_runtime_adapter_apply_gate_policy()["completion_claim"],
        "blockers": [
            "live_runtime_apply_endpoint_disabled",
            "model_call_disabled_for_apply_gate_dry_run",
            "config_model_config_json_left_read_only",
        ],
        "notes": [
            "runtime_adapter_apply_gate_dry_run_only",
            "platform_client_resolver_read_only_contract",
            "no_runtime_config_or_user_default_write",
            "no_model_call_executed",
            "no_service_restart",
        ],
    }


ZHIYI_MODEL_REQUEST_ENVELOPE_DRY_RUN_VERSION = "p1-12.1"


def get_zhiyi_model_request_envelope_dry_run_policy():
    """Return the no-call model request envelope contract."""
    return {
        "ok": True,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "usage_log_write_performed": False,
        "request_sent": False,
        "response_received": False,
        "model_call_performed": False,
        "policy_version": ZHIYI_MODEL_REQUEST_ENVELOPE_DRY_RUN_VERSION,
        "dry_run_endpoint": "/api/v1/zhiyi/model-request/envelope/dry-run",
        "required_upstream_gate": "/api/v1/zhiyi/runtime-adapter/apply-gate/dry-run",
        "future_model_call_endpoint": "/api/v1/zhiyi/model-request/send",
        "live_model_call_endpoint_enabled": False,
        "requires_authorization_for_model_call": True,
        "checks": [
            "runtime_adapter_apply_gate_must_be_ok",
            "platform_client_contract_must_be_ready",
            "request_envelope_may_be_built_but_not_sent",
            "adapter_response_must_be_no_call_draft",
            "source_refs_are_evidence_anchors_not_raw_replacements",
            "dry_run_must_not_write_config_logs_or_usage",
        ],
        "completion_claim": {
            "model_request_envelope_contract_done": True,
            "no_call_adapter_response_contract_done": True,
            "runtime_model_call_done": False,
            "usage_log_persisted": False,
            "live_9850_updated": False,
        },
    }


def _zhiyi_model_request_messages_dry_run(body):
    body = body or {}
    messages = body.get("messages")
    normalized = []
    if isinstance(messages, list):
        for item in messages[:20]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user")
            content = item.get("content", "")
            if not isinstance(content, str):
                try:
                    content = json.dumps(content, ensure_ascii=False, sort_keys=True)
                except Exception:
                    content = str(content)
            normalized.append({"role": role, "content": content})
    if normalized:
        return normalized

    query = str(body.get("query") or body.get("prompt") or body.get("user_input") or "").strip()
    return [
        {
            "role": "system",
            "content": (
                "Use Time Library context with source_refs as evidence anchors. "
                "Raw text remains available through source_refs and must not be replaced by hash-only summaries."
            ),
        },
        {
            "role": "user",
            "content": query or "<user_query_placeholder>",
        },
    ]


def build_zhiyi_model_request_envelope_dry_run(body=None):
    """Draft a model request envelope and adapter response without sending it."""
    body = body or {}
    apply_gate = build_zhiyi_runtime_adapter_apply_gate_dry_run(body)
    preflight = apply_gate.get("runtime_preflight", {}) if isinstance(apply_gate.get("runtime_preflight"), dict) else {}
    binding_plan = preflight.get("model_binding_plan", {}) if isinstance(preflight.get("model_binding_plan"), dict) else {}
    selected_option = preflight.get("selected_option", {}) if isinstance(preflight.get("selected_option"), dict) else {}
    client_resolution = apply_gate.get("platform_client_resolution", {}) if isinstance(apply_gate.get("platform_client_resolution"), dict) else {}
    option_id = str(binding_plan.get("model_id", ""))
    platform = str(client_resolution.get("platform") or selected_option.get("category") or "platform_default")
    transport_candidates = client_resolution.get("transport_candidates", [])
    if not isinstance(transport_candidates, list):
        transport_candidates = []
    transport = transport_candidates[0] if transport_candidates else "not_selected_no_call_dry_run"
    if platform == "platform_default":
        transport = "platform_default_deferred"

    messages = _zhiyi_model_request_messages_dry_run(body)
    source_refs_policy = {
        "mode": "source_refs_anchor_with_raw_follow_up",
        "source_refs_are_raw_retrieval_anchors": True,
        "source_refs_are_not_raw_replacements": True,
        "raw_verbatim_required_when_raw_is_requested": True,
        "redaction_performed": False,
        "hash_only_replacement_allowed": False,
        "dry_run_does_not_attach_production_raw": True,
    }
    request_envelope = {
        "schema_version": "1.0",
        "contract_version": ZHIYI_MODEL_REQUEST_ENVELOPE_DRY_RUN_VERSION,
        "dry_run": True,
        "request_kind": str(body.get("request_kind") or "zhiyi_model_call"),
        "task_kind": str(body.get("task_kind") or "zhiyi_recall_answer"),
        "selected_option_id": option_id,
        "platform": platform,
        "provider": selected_option.get("provider", "auto"),
        "provider_id": selected_option.get("provider_id", ""),
        "model_name": selected_option.get("model_name", ""),
        "transport": transport,
        "messages": messages,
        "parameters": {
            "stream": bool(body.get("stream", False)),
            "temperature": body.get("temperature", 0.2),
        },
        "metadata": {
            "source": "zhiyi_runtime_adapter_p1_12_dry_run",
            "memcore_root": str(MEMCORE_ROOT),
            "runtime_apply_gate_status": apply_gate.get("gate_status", "unknown"),
            "platform_client_resolution_status": client_resolution.get("client_resolution_status", "unknown"),
        },
        "source_refs_policy": source_refs_policy,
        "request_sent": False,
        "response_received": False,
        "model_call_performed": False,
    }

    contract_checks = {
        "runtime_apply_gate_ok": bool(apply_gate.get("ok")),
        "model_binding_plan_ok": bool(binding_plan.get("ok")),
        "platform_client_contract_ready": bool(client_resolution.get("client_contract_ready")),
        "request_envelope_schema_present": request_envelope["schema_version"] == "1.0",
        "request_not_sent": bool(request_envelope.get("request_sent")) is False,
        "response_not_received": bool(request_envelope.get("response_received")) is False,
        "model_call_not_performed": (
            bool(apply_gate.get("model_call_performed", False)) is False
            and bool(client_resolution.get("model_call_performed", False)) is False
            and bool(request_envelope.get("model_call_performed", False)) is False
        ),
        "no_config_or_usage_write": (
            bool(apply_gate.get("write_performed", False)) is False
            and bool(apply_gate.get("config_write_performed", False)) is False
            and bool(apply_gate.get("user_default_write_performed", False)) is False
            and bool(apply_gate.get("runtime_config_write_performed", False)) is False
            and bool(apply_gate.get("runtime_binding_write_performed", False)) is False
            and bool(apply_gate.get("usage_log_write_performed", False)) is False
        ),
        "source_refs_policy_declared": (
            bool(source_refs_policy.get("source_refs_are_raw_retrieval_anchors"))
            and bool(source_refs_policy.get("source_refs_are_not_raw_replacements"))
            and bool(source_refs_policy.get("hash_only_replacement_allowed")) is False
        ),
    }
    contract_failures = [name for name, ok in contract_checks.items() if not ok]
    authorization_missing = apply_gate.get("authorization_missing", []) if isinstance(apply_gate.get("authorization_missing"), list) else []
    authorization_complete = bool(apply_gate.get("authorization_complete", False))
    if contract_failures:
        request_envelope_status = "blocked_contract_check_failure_no_request_sent"
    elif not authorization_complete:
        request_envelope_status = "blocked_missing_authorization_no_request_sent"
    else:
        request_envelope_status = "request_envelope_ready_no_call_adapter_response_draft"

    adapter_response_draft = {
        "ok": not contract_failures,
        "dry_run": True,
        "status": request_envelope_status,
        "adapter": "zhiyi_runtime_adapter",
        "response_kind": "no_call_adapter_response_draft",
        "request_sent": False,
        "response_received": False,
        "model_call_performed": False,
        "usage_log_write_performed": False,
        "not_called_reason": "p1_12_no_call_dry_run_contract",
        "next_required_gate": "explicit_model_call_authorization_and_live_endpoint",
    }

    return {
        "ok": not contract_failures,
        "dry_run": True,
        "write_performed": False,
        "config_write_performed": False,
        "user_default_write_performed": False,
        "runtime_config_write_performed": False,
        "runtime_binding_write_performed": False,
        "usage_log_write_performed": False,
        "request_sent": False,
        "response_received": False,
        "model_call_allowed": False,
        "model_call_performed": False,
        "runtime_apply_allowed": False,
        "runtime_apply_performed": False,
        "policy_version": ZHIYI_MODEL_REQUEST_ENVELOPE_DRY_RUN_VERSION,
        "request_envelope_status": request_envelope_status,
        "request_envelope_draft_ready": not contract_failures,
        "future_model_call_ready": False,
        "authorization_complete": authorization_complete,
        "authorization_missing": authorization_missing,
        "runtime_apply_gate": apply_gate,
        "platform_client_resolution": client_resolution,
        "request_envelope": request_envelope,
        "adapter_response_draft": adapter_response_draft,
        "contract_checks": contract_checks,
        "contract_failures": contract_failures,
        "completion_claim": get_zhiyi_model_request_envelope_dry_run_policy()["completion_claim"],
        "blockers": [
            "live_model_call_endpoint_disabled",
            "model_call_disabled_for_p1_12_dry_run",
            "request_envelope_not_sent",
            "usage_log_not_written",
        ],
        "notes": [
            "model_request_envelope_dry_run_only",
            "adapter_response_is_no_call_draft",
            "source_refs_remain_evidence_anchors_not_raw_replacements",
            "no_config_user_default_usage_log_or_model_call",
            "no_service_restart",
        ],
    }




__all__ = [
    "ZHIYI_MODEL_BINDING_APPLY_GATE_VERSION",
    "ZHIYI_RUNTIME_ADAPTER_DRY_RUN_VERSION",
    "ZHIYI_RUNTIME_ADAPTER_APPLY_GATE_VERSION",
    "ZHIYI_MODEL_REQUEST_ENVELOPE_DRY_RUN_VERSION",
    "ZHIYI_USAGE_LOG_CONTRACT",
    "ZHIYI_USAGE_LIGHT_PROMPT_POLICY_VERSION",
    "ZHIYI_USAGE_LOG_APPLY_GATE_VERSION",
    "ZHIYI_MODEL_RUNTIME_CONTRACT",
    "configure_zhiyi_model_runtime",
    "get_zhiyi_model_runtime_contract",
    "_compact_text",
    "_json_or_none",
    "_unique_existing",
    "_home_candidates",
    "get_zhiyi_model_options",
    "get_zhiyi_vector_recall_preference",
    "granite_asset_status",
    "start_granite_asset_prepare",
    "run_model_connection_smoke",
    "build_zhiyi_model_binding_plan",
    "apply_zhiyi_model_binding_user_default",
    "get_zhiyi_model_binding_apply_gate_policy",
    "build_zhiyi_model_binding_apply_gate_dry_run",
    "get_zhiyi_runtime_adapter_dry_run_policy",
    "_zhiyi_runtime_file_snapshot",
    "build_zhiyi_runtime_adapter_dry_run",
    "get_zhiyi_runtime_adapter_apply_gate_policy",
    "_zhiyi_platform_runtime_profile_snapshot",
    "_zhiyi_platform_client_resolver_dry_run",
    "build_zhiyi_runtime_adapter_apply_gate_dry_run",
    "get_zhiyi_model_request_envelope_dry_run_policy",
    "_zhiyi_model_request_messages_dry_run",
    "build_zhiyi_model_request_envelope_dry_run",
    "configure_zhiyi_usage_log",
    "get_zhiyi_usage_log_contract",
    "build_zhiyi_usage_log_dry_run",
    "get_zhiyi_usage_light_prompt_policy",
    "build_zhiyi_usage_light_prompt",
    "_zhiyi_usage_log_path",
    "_usage_log_positive_int",
    "get_zhiyi_usage_log_apply_gate_policy",
    "build_zhiyi_usage_log_apply_gate_dry_run",
    "build_zhiyi_usage_log_persist_dry_run",
    "query_zhiyi_usage_log_dry_run",
]
