#!/usr/bin/env python3
"""Read-only platform model facts for Time Library.

This layer discovers model configuration facts from supported local AI
platforms and returns them to Time Library as evidence. It never writes platform
configuration and never treats discovery as proof that the model can run.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - fallback covered by simple parser use.
    yaml = None

try:
    from src.hermes_paths import hermes_config_paths, resolve_hermes_home
except Exception:
    try:
        from hermes_paths import hermes_config_paths, resolve_hermes_home
    except Exception:  # pragma: no cover - import guard for isolated tests.
        hermes_config_paths = None
        resolve_hermes_home = None


MODEL_FACTS_VERSION = "2026.6.1"
DEFAULT_RUNNABLE_STATUS = "unknown"
DOCTOR_DEFAULT_TIMEOUT_SECONDS = 45
DOCTOR_DEFAULT_PROMPT = "只回答 OK"

RUNTIME_ENV_PROBES = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "MINIMAX_API_KEY",
    "MINIMAX_BASE_URL",
    "MINIMAX_CN_API_KEY",
    "MINIMAX_CN_BASE_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "HERMES_HOME",
]

SENSITIVE_FIELD_NAMES = {
    "apikey",
    "api_key",
    "api-key",
    "auth_token",
    "bearer_token",
    "client_secret",
    "encryption_key",
    "encryption_key_b64",
    "key",
    "password",
    "private_key",
    "privatekey",
    "refresh_token",
    "secret",
    "secret_key",
    "token",
}


def _normalize_sensitive_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_sensitive_key(key)
    return normalized in SENSITIVE_FIELD_NAMES or normalized.endswith("_token") or normalized.endswith("_secret")


def _redact_text(text: Any, *, max_chars: int = 1600) -> str:
    value = str(text or "")
    value = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-[REDACTED]", value)
    value = re.sub(r"(?i)(api[_-]?key|token|secret|password|authorization)([^\n:]*):\s*[^\n]+", r"\1\2: [REDACTED]", value)
    value = re.sub(r"(?i)(api[_-]?key|token|secret|password|authorization)([^\n=]*)=\s*[^\n]+", r"\1\2=[REDACTED]", value)
    return value[:max_chars]


def _env_presence(names: Iterable[str] | None = None, env: dict[str, str] | None = None) -> dict[str, dict]:
    source = env if env is not None else os.environ
    result: dict[str, dict] = {}
    for name in names or RUNTIME_ENV_PROBES:
        value = source.get(name)
        result[name] = {
            "present": value is not None,
            "non_empty": bool(str(value or "").strip()),
            "value_returned": False,
            "length": len(value) if value is not None else 0,
        }
    return result


def _classify_runtime_failure(stdout: str, stderr: str, runtime_error: str = "") -> dict:
    combined = f"{stdout}\n{stderr}\n{runtime_error}".lower()
    if "401" in combined or "authentication" in combined or "x-api-key" in combined or "unauthorized" in combined:
        return {
            "category": "auth_failed",
            "reason": "runtime request reached provider protocol but authentication failed",
            "likely_gap": "service_env_missing_or_mismatched_runtime_credentials",
        }
    if "no module named" in combined or "modulenotfounderror" in combined or "missing" in combined and "package" in combined:
        return {
            "category": "runtime_dependency_missing",
            "reason": "Hermes runtime failed before model request because a dependency is missing",
            "likely_gap": "platform_runtime_dependency_not_installed",
        }
    if "timed out" in combined or "timeout" in combined:
        return {
            "category": "timeout",
            "reason": "Hermes command did not complete within the smoke-test timeout",
            "likely_gap": "runtime_slow_or_provider_unreachable",
        }
    if runtime_error:
        return {
            "category": "local_invocation_error",
            "reason": "Time Library could not invoke the Hermes command cleanly",
            "likely_gap": "local_command_invocation_failed",
        }
    return {
        "category": "unknown_runtime_failure",
        "reason": "Hermes command failed but no known failure pattern matched",
        "likely_gap": "inspect_redacted_stdout_stderr",
    }


def _collect_sensitive_fields(value: Any, prefix: str = "") -> list[str]:
    fields: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if _is_sensitive_key(key_text) and child not in (None, "", [], {}):
                fields.append(path)
            fields.extend(_collect_sensitive_fields(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:50]):
            fields.extend(_collect_sensitive_fields(child, f"{prefix}[{index}]" if prefix else f"[{index}]"))
    return sorted(set(fields))


def _read_json(path: Path) -> tuple[Any, str]:
    try:
        with path.open(encoding="utf-8-sig", errors="ignore") as handle:
            return json.load(handle), ""
    except Exception as exc:
        return None, str(exc)


def _read_yaml(path: Path) -> tuple[Any, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if yaml is not None:
            return yaml.safe_load(text) or {}, ""
        return _parse_simple_yaml_model_block(text), ""
    except Exception as exc:
        return None, str(exc)


def _parse_simple_scalar(value: str) -> Any:
    text = str(value or "").strip().strip("'\"")
    if text in ("true", "True"):
        return True
    if text in ("false", "False"):
        return False
    if text in ("null", "None", "~"):
        return None
    try:
        return int(text)
    except Exception:
        return text


def _parse_simple_yaml_model_block(text: str) -> dict:
    """Small fallback for common Hermes config YAML when PyYAML is unavailable."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()

    for index, raw_line in enumerate(lines):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if stripped.startswith("- "):
            item_text = stripped[2:].strip()
            if not isinstance(parent, list):
                continue
            item: Any = {}
            if item_text and ":" in item_text:
                key, raw_value = item_text.split(":", 1)
                item[key.strip()] = _parse_simple_scalar(raw_value)
            elif item_text:
                item = _parse_simple_scalar(item_text)
            parent.append(item)
            if isinstance(item, dict):
                stack.append((indent, item))
            continue

        if ":" not in stripped or not isinstance(parent, dict):
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            parent[key] = _parse_simple_scalar(raw_value)
            continue

        child: Any = {}
        for next_line in lines[index + 1:]:
            if not next_line.strip() or next_line.lstrip().startswith("#"):
                continue
            next_indent = len(next_line) - len(next_line.lstrip(" "))
            if next_indent <= indent:
                break
            child = [] if next_line.strip().startswith("- ") else {}
            break
        parent[key] = child
        stack.append((indent, child))
    return root


def _home_candidates() -> list[Path]:
    paths = [Path.home()]
    for env_name in ("HOME", "USERPROFILE"):
        value = os.environ.get(env_name, "").strip()
        if value:
            paths.append(Path(value).expanduser())
    return _unique_existing_paths(paths, require_exists=False)


def _unique_existing_paths(paths: Iterable[Path | str | None], *, require_exists: bool = True) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for item in paths:
        if not item:
            continue
        path = Path(str(item)).expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if require_exists and not path.exists():
            continue
        result.append(path)
    return result


def _default_openclaw_roots() -> list[Path]:
    roots: list[Path | str | None] = [os.environ.get("OPENCLAW_HOME")]
    roots.extend(home / ".openclaw" for home in _home_candidates())
    return _unique_existing_paths(roots)


def _default_hermes_roots() -> list[Path]:
    roots: list[Path | str | None] = []
    if resolve_hermes_home is not None:
        try:
            roots.append(resolve_hermes_home())
        except Exception:
            pass
    roots.append(os.environ.get("HERMES_HOME"))
    roots.extend(home / ".hermes" for home in _home_candidates())
    return _unique_existing_paths(roots)


def _default_codex_roots() -> list[Path]:
    roots: list[Path | str | None] = [os.environ.get("CODEX_HOME")]
    roots.extend(home / ".codex" for home in _home_candidates())
    return _unique_existing_paths(roots)


def _fact_id(parts: Iterable[Any]) -> str:
    text = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def _split_provider_model(model_name: Any, provider_hint: Any = "") -> tuple[str, str]:
    provider = str(provider_hint or "").strip()
    model = str(model_name or "").strip()
    if not provider and "/" in model:
        left, right = model.split("/", 1)
        if left and right:
            provider = left
            model = right
    return provider, model


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _model_items(models: Any) -> list[dict]:
    items: list[dict] = []
    if isinstance(models, dict):
        for model_id, model_data in models.items():
            if isinstance(model_data, dict):
                item = dict(model_data)
                item.setdefault("id", model_id)
                items.append(item)
            else:
                items.append({"id": model_id, "label": model_data})
    elif isinstance(models, list):
        for item in models:
            if isinstance(item, dict):
                items.append(dict(item))
            else:
                items.append({"id": item})
    elif isinstance(models, str):
        items.append({"id": models})
    return items


def _provider_entries(providers: Any) -> list[tuple[str, dict]]:
    entries: list[tuple[str, dict]] = []
    if isinstance(providers, dict):
        for provider_id, provider_data in providers.items():
            if isinstance(provider_data, dict):
                entries.append((str(provider_id), dict(provider_data)))
            else:
                entries.append((str(provider_id), {"value": provider_data}))
    elif isinstance(providers, list):
        for provider_data in providers:
            if not isinstance(provider_data, dict):
                continue
            provider_id = (
                provider_data.get("id")
                or provider_data.get("name")
                or provider_data.get("provider")
                or provider_data.get("provider_id")
                or provider_data.get("type")
                or ""
            )
            entries.append((str(provider_id or "provider"), dict(provider_data)))
    return entries


def _extract_provider_type(provider_data: dict) -> str:
    for key in ("type", "provider_type", "api_type", "protocol", "kind"):
        value = provider_data.get(key)
        if value:
            return str(value)
    return ""


def _add_fact(
    facts: list[dict],
    *,
    platform: str,
    source_path: Path,
    source_kind: str,
    role: str,
    model_name: Any,
    provider_id: Any = "",
    provider_type: Any = "",
    label: Any = "",
    source_detail: dict | None = None,
    sensitive_source: Any = None,
    sensitive_fields: list[str] | None = None,
) -> bool:
    provider, model = _split_provider_model(model_name, provider_id)
    if not model:
        return False
    if sensitive_fields is None:
        sensitive_fields = _collect_sensitive_fields(sensitive_source if sensitive_source is not None else source_detail or {})
    fact = {
        "fact_id": _fact_id([platform, source_path, source_kind, role, provider, model, label]),
        "platform": platform,
        "source_path": str(source_path),
        "source_kind": source_kind,
        "source_detail": source_detail or {},
        "role": role,
        "provider_id": provider,
        "provider_type": str(provider_type or ""),
        "model": model,
        "label": str(label or model),
        "detected": True,
        "runnable": DEFAULT_RUNNABLE_STATUS,
        "runtime_ownership": "borrowed_runtime",
        "borrowed_runtime": {
            "platform": platform,
            "source": source_kind,
            "read_only_config": True,
            "time_library_writeback_allowed": False,
        },
        "owned_runtime": {
            "available": False,
            "reason": "time_library_reads_platform_model_facts_but_does_not_own_platform_runtime",
        },
        "credentials": {
            "has_sensitive_fields": bool(sensitive_fields),
            "sensitive_field_names": sensitive_fields[:20],
            "sensitive_values_returned": False,
        },
        "write_boundary": {
            "read_only": True,
            "write_performed": False,
            "platform_write_performed": False,
            "openclaw_write_performed": False,
            "hermes_write_performed": False,
            "codex_write_performed": False,
        },
    }
    facts.append(fact)
    return True


def _provider_registry(data: Any) -> Any:
    if not isinstance(data, dict):
        return None
    models = data.get("models")
    if isinstance(models, dict) and isinstance(models.get("providers"), (dict, list)):
        return models.get("providers")
    if isinstance(data.get("providers"), (dict, list)):
        return data.get("providers")
    return None


def _add_provider_registry_facts(
    facts: list[dict],
    *,
    platform: str,
    source_path: Path,
    source_kind: str,
    registry: Any,
) -> int:
    added = 0
    for provider_id, provider_data in _provider_entries(registry):
        provider_type = _extract_provider_type(provider_data)
        provider_sensitive_fields = _collect_sensitive_fields(provider_data)
        models = provider_data.get("models")
        if models is None and isinstance(provider_data.get("model"), (list, dict, str)):
            models = provider_data.get("model")
        for item in _model_items(models):
            model_name = item.get("id") or item.get("model") or item.get("name") or item.get("value")
            label = item.get("label") or item.get("name") or model_name
            if _add_fact(
                facts,
                platform=platform,
                source_path=source_path,
                source_kind=source_kind,
                role="catalog",
                provider_id=provider_id,
                provider_type=provider_type,
                model_name=model_name,
                label=label,
                source_detail={"provider_id": provider_id},
                sensitive_fields=provider_sensitive_fields,
            ):
                added += 1
    return added


def _discover_openclaw(facts: list[dict], roots: list[Path], notes: list[str], sources: list[dict]) -> None:
    for root in roots:
        openclaw_json = root / "openclaw.json"
        if openclaw_json.exists():
            data, error = _read_json(openclaw_json)
            sources.append({"platform": "openclaw", "source_path": str(openclaw_json), "exists": True, "parse_ok": not error})
            if error or not isinstance(data, dict):
                notes.append(f"openclaw_config_parse_failed:{openclaw_json}")
            else:
                registry = _provider_registry(data)
                if registry is not None:
                    _add_provider_registry_facts(
                        facts,
                        platform="openclaw",
                        source_path=openclaw_json,
                        source_kind="openclaw_provider_registry",
                        registry=registry,
                    )
                agents = data.get("agents", {}) if isinstance(data.get("agents"), dict) else {}
                defaults = agents.get("defaults", {}) if isinstance(agents.get("defaults"), dict) else {}
                default_models = defaults.get("models")
                for item in _model_items(default_models):
                    provider_id = item.get("provider") or item.get("provider_id") or item.get("providerId") or ""
                    model_name = item.get("id") or item.get("model") or item.get("name")
                    _add_fact(
                        facts,
                        platform="openclaw",
                        source_path=openclaw_json,
                        source_kind="openclaw_agents_defaults_models",
                        role="catalog",
                        provider_id=provider_id,
                        model_name=model_name,
                        label=item.get("label") or item.get("name") or model_name,
                        source_detail={"section": "agents.defaults.models"},
                        sensitive_source=data,
                    )
                model_default = defaults.get("model")
                if isinstance(model_default, dict):
                    primary = model_default.get("primary") or model_default.get("default") or model_default.get("model")
                    primary_provider = model_default.get("provider") or model_default.get("provider_id") or ""
                    _add_fact(
                        facts,
                        platform="openclaw",
                        source_path=openclaw_json,
                        source_kind="openclaw_agents_default_model",
                        role="default",
                        provider_id=primary_provider,
                        model_name=primary,
                        source_detail={"section": "agents.defaults.model.primary"},
                        sensitive_source=data,
                    )
                    for fallback in _as_list(model_default.get("fallbacks")):
                        _add_fact(
                            facts,
                            platform="openclaw",
                            source_path=openclaw_json,
                            source_kind="openclaw_agents_default_model",
                            role="fallback",
                            provider_id=primary_provider,
                            model_name=fallback,
                            source_detail={"section": "agents.defaults.model.fallbacks"},
                            sensitive_source=data,
                        )
                elif model_default:
                    _add_fact(
                        facts,
                        platform="openclaw",
                        source_path=openclaw_json,
                        source_kind="openclaw_agents_default_model",
                        role="default",
                        model_name=model_default,
                        source_detail={"section": "agents.defaults.model"},
                        sensitive_source=data,
                    )
                for agent in _as_list(agents.get("list")):
                    if not isinstance(agent, dict):
                        continue
                    raw_model = agent.get("model")
                    provider_id = ""
                    model_name = ""
                    if isinstance(raw_model, dict):
                        model_name = raw_model.get("primary") or raw_model.get("default") or raw_model.get("model") or raw_model.get("name")
                        provider_id = raw_model.get("provider") or raw_model.get("provider_id") or ""
                    else:
                        model_name = raw_model
                    _add_fact(
                        facts,
                        platform="openclaw",
                        source_path=openclaw_json,
                        source_kind="openclaw_agent_model",
                        role="agent_default",
                        provider_id=provider_id,
                        model_name=model_name,
                        source_detail={"agent_id": str(agent.get("id") or "")},
                        sensitive_source=data,
                    )

        clawui_models = root / "clawui-models.json"
        if clawui_models.exists():
            data, error = _read_json(clawui_models)
            sources.append({"platform": "openclaw", "source_path": str(clawui_models), "exists": True, "parse_ok": not error})
            if error:
                notes.append(f"openclaw_clawui_models_parse_failed:{clawui_models}")
            elif isinstance(data, dict):
                for full_model, metadata in data.items():
                    provider, model = _split_provider_model(full_model)
                    _add_fact(
                        facts,
                        platform="openclaw",
                        source_path=clawui_models,
                        source_kind="openclaw_clawui_models",
                        role="catalog",
                        provider_id=provider,
                        model_name=model or full_model,
                        source_detail={"section": "clawui-models.json"},
                        sensitive_source=metadata,
                    )
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        model_name = item.get("id") or item.get("model") or item.get("name")
                        provider_id = item.get("provider") or item.get("provider_id") or ""
                    else:
                        model_name = item
                        provider_id = ""
                    _add_fact(
                        facts,
                        platform="openclaw",
                        source_path=clawui_models,
                        source_kind="openclaw_clawui_models",
                        role="catalog",
                        provider_id=provider_id,
                        model_name=model_name,
                        source_detail={"section": "clawui-models.json"},
                        sensitive_source=item,
                    )

        for models_path in glob.glob(str(root / "agents" / "*" / "agent" / "models.json")):
            path = Path(models_path)
            data, error = _read_json(path)
            sources.append({"platform": "openclaw", "source_path": str(path), "exists": True, "parse_ok": not error})
            if error or not isinstance(data, dict):
                notes.append(f"openclaw_agent_models_parse_failed:{path}")
                continue
            registry = _provider_registry(data)
            if registry is not None:
                _add_provider_registry_facts(
                    facts,
                    platform="openclaw",
                    source_path=path,
                    source_kind="openclaw_agent_models",
                    registry=registry,
                )


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _discover_hermes(
    facts: list[dict],
    roots: list[Path],
    notes: list[str],
    sources: list[dict],
    *,
    include_recent_sessions: bool = False,
) -> None:
    for root in roots:
        config_paths: list[Path] = []
        if hermes_config_paths is not None:
            try:
                config_paths.extend(hermes_config_paths(root, existing_only=True))
            except Exception as exc:
                notes.append(f"hermes_config_paths_failed:{root}:{str(exc)[:80]}")
        for fallback in (root / "config.yaml", root / "profiles" / "default" / "config.yaml"):
            if fallback.exists() and fallback not in config_paths:
                config_paths.append(fallback)

        for config_path in config_paths:
            data, error = _read_yaml(config_path)
            sources.append({"platform": "hermes", "source_path": str(config_path), "exists": True, "parse_ok": not error})
            if error or not isinstance(data, dict):
                notes.append(f"hermes_config_parse_failed:{config_path}")
                continue
            model_cfg = data.get("model", {}) if isinstance(data.get("model"), dict) else {}
            model_name = (
                model_cfg.get("default")
                or model_cfg.get("model")
                or model_cfg.get("name")
                or data.get("default_model")
                or data.get("model")
            )
            provider_id = model_cfg.get("provider") or data.get("provider") or ""
            _add_fact(
                facts,
                platform="hermes",
                source_path=config_path,
                source_kind="hermes_config_yaml",
                role="default",
                provider_id=provider_id,
                model_name=model_name,
                source_detail={"section": "model"},
                sensitive_source=data,
            )
            custom_providers = data.get("custom_providers") or data.get("customProviders")
            for provider_id, provider_data in _provider_entries(custom_providers):
                _add_provider_registry_facts(
                    facts,
                    platform="hermes",
                    source_path=config_path,
                    source_kind="hermes_custom_providers",
                    registry={provider_id: provider_data},
                )
            providers = data.get("providers")
            if providers is not None:
                _add_provider_registry_facts(
                    facts,
                    platform="hermes",
                    source_path=config_path,
                    source_kind="hermes_providers",
                    registry=providers,
                )

        for json_name in ("models.json", "models_dev_cache.json", "config.json", "settings.json"):
            json_path = root / json_name
            if not json_path.exists():
                continue
            data, error = _read_json(json_path)
            sources.append({"platform": "hermes", "source_path": str(json_path), "exists": True, "parse_ok": not error})
            if error:
                notes.append(f"hermes_json_parse_failed:{json_path}")
                continue
            if isinstance(data, dict):
                registry = _provider_registry(data)
                if registry is not None:
                    _add_provider_registry_facts(
                        facts,
                        platform="hermes",
                        source_path=json_path,
                        source_kind=f"hermes_{json_name}",
                        registry=registry,
                    )
                elif json_name == "models_dev_cache.json":
                    _add_provider_registry_facts(
                        facts,
                        platform="hermes",
                        source_path=json_path,
                        source_kind="hermes_models_dev_cache",
                        registry=data,
                    )
                model_name = data.get("model") or data.get("default_model") or data.get("selected_model")
                provider_id = data.get("provider") or data.get("provider_id") or ""
                _add_fact(
                    facts,
                    platform="hermes",
                    source_path=json_path,
                    source_kind=f"hermes_{json_name}",
                    role="default",
                    provider_id=provider_id,
                    model_name=model_name,
                    source_detail={"section": json_name},
                    sensitive_source=data,
                )

        state_db = root / "state.db"
        if state_db.exists() and include_recent_sessions:
            sources.append({"platform": "hermes", "source_path": str(state_db), "exists": True, "parse_ok": True, "read_mode": "sqlite_ro"})
            try:
                connection = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
                rows = connection.execute(
                    "SELECT model,billing_provider FROM sessions WHERE model IS NOT NULL AND model != '' ORDER BY started_at DESC LIMIT 8"
                ).fetchall()
                connection.close()
                for model_name, provider_id in rows:
                    _add_fact(
                        facts,
                        platform="hermes",
                        source_path=state_db,
                        source_kind="hermes_recent_session",
                        role="recent",
                        provider_id=provider_id,
                        model_name=model_name,
                        source_detail={"table": "sessions"},
                    )
            except Exception as exc:
                notes.append(f"hermes_state_db_unavailable:{str(exc)[:80]}")
        elif state_db.exists():
            sources.append({
                "platform": "hermes",
                "source_path": str(state_db),
                "exists": True,
                "parse_ok": True,
                "read_mode": "sqlite_ro_skipped",
                "skip_reason": "recent_session_scan_opt_in",
            })


def _read_codex_toml_model(path: Path) -> dict:
    result: dict[str, str] = {}
    current_section = ""
    try:
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line.strip("[]")
                continue
            if "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            value = raw_value.split("#", 1)[0].strip().strip("'\"")
            if current_section:
                full_key = f"{current_section}.{key}"
            else:
                full_key = key
            if full_key in ("model", "model_provider", "model_provider_id") or key in ("model", "model_provider"):
                result.setdefault(key, value)
    except Exception:
        return {}
    return result


def _discover_codex(facts: list[dict], roots: list[Path], notes: list[str], sources: list[dict]) -> None:
    for root in roots:
        config_path = root / "config.toml"
        if config_path.exists():
            data = _read_codex_toml_model(config_path)
            sources.append({"platform": "codex", "source_path": str(config_path), "exists": True, "parse_ok": bool(data)})
            model_name = data.get("model", "")
            provider_id = data.get("model_provider") or data.get("model_provider_id") or ""
            if not model_name:
                notes.append(f"codex_config_model_not_found:{config_path}")
            _add_fact(
                facts,
                platform="codex",
                source_path=config_path,
                source_kind="codex_config_toml",
                role="default",
                provider_id=provider_id,
                model_name=model_name,
                source_detail={"section": "config.toml"},
                sensitive_source={},
            )


def get_model_facts_plan() -> dict:
    return {
        "ok": True,
        "version": MODEL_FACTS_VERSION,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "endpoint": "/api/v1/model-facts",
        "scope": ["openclaw", "hermes", "codex"],
        "purpose": "read platform model configuration facts back for Time Library use without becoming a model center",
        "contracts": [
            "detected_is_not_runnable",
            "runnable_defaults_to_unknown_without_smoke_test",
            "borrowed_runtime_and_owned_runtime_are_separate",
            "platform_configs_are_never_written",
            "secret_values_are_never_returned",
        ],
    }


def get_model_runnable_doctor_plan() -> dict:
    return {
        "ok": True,
        "version": MODEL_FACTS_VERSION,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "endpoint": "/api/v1/model-facts/runnable-doctor/plan",
        "smoke_endpoint": "/api/v1/model-facts/runnable-doctor/smoke",
        "purpose": "separate detected model facts from live runnable platform runtime",
        "supported_platforms": ["hermes"],
        "default_prompt": DOCTOR_DEFAULT_PROMPT,
        "default_timeout_seconds": DOCTOR_DEFAULT_TIMEOUT_SECONDS,
        "contracts": [
            "detected_true_is_not_runnable_true",
            "doctor_requires_explicit_authorization_to_run_platform_cli",
            "doctor_never_writes_platform_model_config",
            "doctor_never_returns_secret_values",
            "doctor_reports_service_environment_presence_only",
            "doctor_distinguishes_cli_runnable_from_service_trigger_runnable",
        ],
        "authorization_required": [
            "confirm_live_runtime_smoke",
            "confirm_no_platform_config_write",
            "operator",
            "reason",
        ],
    }


def _resolve_hermes_cli(requested: Any = "") -> str:
    explicit = str(requested or "").strip()
    if explicit:
        return explicit
    candidates = [
        Path.home() / ".local" / "bin" / "hermes",
        Path("/usr/local/bin/hermes"),
        Path("/opt/homebrew/bin/hermes"),
    ]
    path_env = os.environ.get("PATH", "")
    for directory in path_env.split(os.pathsep):
        if not directory:
            continue
        candidates.append(Path(directory) / "hermes")
    for candidate in candidates:
        try:
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
        except Exception:
            continue
    return "hermes"


def build_model_runnable_doctor_smoke(
    payload: dict | None = None,
    *,
    env: dict[str, str] | None = None,
    run_command=None,
) -> dict:
    """Run an explicitly authorized minimal runtime smoke.

    The doctor intentionally checks platform runtime liveness without turning
    Time Library into a model center. It invokes supported platform CLIs, records
    redacted output, and never writes model/platform configuration.
    """
    body = payload or {}
    authorization = body.get("authorization") if isinstance(body.get("authorization"), dict) else body
    required = [
        "confirm_live_runtime_smoke",
        "confirm_no_platform_config_write",
        "operator",
        "reason",
    ]
    missing = [key for key in required if not authorization.get(key)]
    platform = str(body.get("platform") or "hermes").strip().lower()
    if platform not in {"hermes"}:
        missing.append("supported_platform:hermes")
    if missing:
        return {
            "ok": False,
            "version": MODEL_FACTS_VERSION,
            "requires_authorization": True,
            "missing_authorization": sorted(set(missing)),
            "read_only": False,
            "write_capable": False,
            "write_performed": False,
            "platform_write_performed": False,
            "model_config_write_performed": False,
            "runtime_smoke_performed": False,
            "detected_is_not_runnable": True,
        }

    prompt = str(body.get("prompt") or DOCTOR_DEFAULT_PROMPT)
    if len(prompt) > 500:
        prompt = prompt[:500]
    timeout_seconds = body.get("timeout_seconds", DOCTOR_DEFAULT_TIMEOUT_SECONDS)
    try:
        timeout_seconds = int(timeout_seconds)
    except Exception:
        timeout_seconds = DOCTOR_DEFAULT_TIMEOUT_SECONDS
    timeout_seconds = max(3, min(timeout_seconds, 180))
    max_turns = body.get("max_turns", 1)
    try:
        max_turns = int(max_turns)
    except Exception:
        max_turns = 1
    max_turns = max(1, min(max_turns, 3))

    hermes_cli = _resolve_hermes_cli(body.get("hermes_cli"))
    command = [hermes_cli, "chat", "-q", prompt, "-Q", "--max-turns", str(max_turns)]
    env_source = dict(env if env is not None else os.environ)
    started = time.time()
    stdout = ""
    stderr = ""
    exit_code: int | None = None
    timed_out = False
    runtime_error = ""

    try:
        runner = run_command or subprocess.run
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env_source,
        )
        exit_code = int(getattr(completed, "returncode", 1))
        stdout = str(getattr(completed, "stdout", "") or "")
        stderr = str(getattr(completed, "stderr", "") or "")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        stdout = str(exc.stdout or "")
        stderr = str(exc.stderr or "")
        runtime_error = f"timeout_after_{timeout_seconds}s"
    except Exception as exc:
        exit_code = None
        runtime_error = f"{type(exc).__name__}: {str(exc)[:300]}"

    elapsed = round(time.time() - started, 2)
    runnable = exit_code == 0 and not timed_out
    failure = None if runnable else _classify_runtime_failure(stdout, stderr, runtime_error)
    service_env = _env_presence(env=env_source)

    return {
        "ok": runnable,
        "version": MODEL_FACTS_VERSION,
        "platform": platform,
        "read_only": False,
        "write_capable": False,
        "write_performed": False,
        "platform_write_performed": False,
        "model_config_write_performed": False,
        "openclaw_write_performed": False,
        "hermes_write_performed": False,
        "codex_write_performed": False,
        "runtime_smoke_performed": True,
        "detected_is_not_runnable": True,
        "detected": "not_checked_by_doctor",
        "runnable": bool(runnable),
        "runnable_status": "runnable" if runnable else "failed",
        "runtime_boundary": {
            "model_facts_are_read_back_for_time_library_use": True,
            "time_library_is_not_a_model_center": True,
            "borrowed_runtime_is_separate_from_owned_runtime": True,
            "platform_writeback_allowed": False,
            "owned_runtime_invocation_configured": False,
            "doctor_uses_platform_cli": True,
        },
        "command_preview": [command[0], "chat", "-q", "[doctor prompt]", "-Q", "--max-turns", str(max_turns)],
        "hermes_cli_found": Path(hermes_cli).exists() if hermes_cli != "hermes" else None,
        "timeout_seconds": timeout_seconds,
        "elapsed_seconds": elapsed,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout_excerpt": _redact_text(stdout),
        "stderr_excerpt": _redact_text(stderr),
        "runtime_error": _redact_text(runtime_error),
        "failure": failure,
        "service_environment": {
            "secret_values_returned": False,
            "presence_only": True,
            "probes": service_env,
            "diagnostic_hint": (
                "If shell CLI succeeds but service doctor fails, the service process likely "
                "does not inherit the same runtime credentials or provider env."
            ),
        },
        "authorization": {
            "operator": str(authorization.get("operator") or ""),
            "reason": str(authorization.get("reason") or ""),
            "confirm_live_runtime_smoke": True,
            "confirm_no_platform_config_write": True,
        },
    }


def build_model_facts_report(
    *,
    openclaw_roots: Iterable[Path | str] | None = None,
    hermes_roots: Iterable[Path | str] | None = None,
    codex_roots: Iterable[Path | str] | None = None,
    include_recent_sessions: bool | None = None,
    fact_limit: int | None = None,
) -> dict:
    facts: list[dict] = []
    notes: list[str] = []
    sources: list[dict] = []

    oc_roots = _unique_existing_paths(openclaw_roots, require_exists=True) if openclaw_roots is not None else _default_openclaw_roots()
    hm_roots = _unique_existing_paths(hermes_roots, require_exists=True) if hermes_roots is not None else _default_hermes_roots()
    cx_roots = _unique_existing_paths(codex_roots, require_exists=True) if codex_roots is not None else _default_codex_roots()

    _discover_openclaw(facts, oc_roots, notes, sources)
    if include_recent_sessions is None:
        include_recent_sessions = _truthy_env("MEMCORE_MODEL_FACTS_INCLUDE_RECENT")
    _discover_hermes(facts, hm_roots, notes, sources, include_recent_sessions=include_recent_sessions)
    _discover_codex(facts, cx_roots, notes, sources)

    deduped: list[dict] = []
    seen_ids: set[str] = set()
    for fact in facts:
        fact_id = str(fact.get("fact_id") or "")
        if fact_id in seen_ids:
            continue
        seen_ids.add(fact_id)
        deduped.append(fact)

    counts_by_platform = {"openclaw": 0, "hermes": 0, "codex": 0}
    counts_by_role: dict[str, int] = {}
    for fact in deduped:
        platform = str(fact.get("platform") or "")
        if platform in counts_by_platform:
            counts_by_platform[platform] += 1
        role = str(fact.get("role") or "unknown")
        counts_by_role[role] = counts_by_role.get(role, 0) + 1

    if fact_limit is None:
        fact_limit = 500
    try:
        fact_limit = int(fact_limit)
    except Exception:
        fact_limit = 500
    if fact_limit < 0:
        fact_limit = 0
    visible_facts = deduped[:fact_limit] if fact_limit else []

    return {
        "ok": True,
        "version": MODEL_FACTS_VERSION,
        "read_only": True,
        "write_performed": False,
        "config_write_performed": False,
        "platform_write_performed": False,
        "openclaw_write_performed": False,
        "hermes_write_performed": False,
        "codex_write_performed": False,
        "detected_is_not_runnable": True,
        "runnable_default": DEFAULT_RUNNABLE_STATUS,
        "runtime_boundary": {
            "model_facts_are_read_back_for_time_library_use": True,
            "time_library_is_not_a_model_center": True,
            "borrowed_runtime_is_separate_from_owned_runtime": True,
            "platform_writeback_allowed": False,
            "owned_runtime_invocation_configured": False,
        },
        "scan_policy": {
            "recent_sessions_included": bool(include_recent_sessions),
            "recent_sessions_default": "skipped_for_stable_config_fact_endpoint",
        },
        "roots": {
            "openclaw": [str(path) for path in oc_roots],
            "hermes": [str(path) for path in hm_roots],
            "codex": [str(path) for path in cx_roots],
        },
        "sources": sources,
        "counts": {
            "total": len(deduped),
            "by_platform": counts_by_platform,
            "by_role": counts_by_role,
            "returned": len(visible_facts),
            "hidden_by_limit": max(0, len(deduped) - len(visible_facts)),
        },
        "facts": visible_facts,
        "fact_return_policy": {
            "limit": fact_limit,
            "truncated": len(visible_facts) < len(deduped),
            "reason": "keep_frontstage_model_fact_endpoint_lightweight",
        },
        "notes": notes,
    }
