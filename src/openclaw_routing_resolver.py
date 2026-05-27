"""
openclaw_routing_resolver.py
P9-System-H H3: Routing Resolver
P9-System-H H7: Routing Audit Log

输入: target_hint (session_key / agent_id / window_id / None)
输出: route_decision { ok, session_key, canonical_window_id, action, reason }

约束：
- 禁止默认 main
- 禁止默认最近 session
- 未绑定窗口 → REJECT（不注入）
- 绑定优先级：registry > catalog inference > direct session_key
"""

import os
import json
import time as time_module
from config_loader import get_memcore_root

REGISTRY_PATH = os.path.join(get_memcore_root(), "config", "window_binding_registry.json")
ROUTING_AUDIT_PATH = os.path.join(get_memcore_root(), "logs", "routing_audit.jsonl")

ACTION_INJECT = "inject"
ACTION_REJECT = "reject"


def _audit_log(entry: dict):
    try:
        os.makedirs(os.path.dirname(ROUTING_AUDIT_PATH), exist_ok=True)
        with open(ROUTING_AUDIT_PATH, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_registry():
    if os.path.exists(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"bindings": {}, "inferred_from_catalog": {}, "_meta": {}}


def _save_registry(registry):
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


def _session_key_exists_in_gateway(session_key: str) -> bool:
    """H5: 验证 session_key 是否真实存在于 Gateway 的 session 列表"""
    try:
        import openclaw_ws_rpc_client as _rc
        client = _rc.OpenClawWsRpcClient(max_retries=1)
        if not client.connect(timeout=5):
            return False
        result = client.sessions_list(timeout=5)
        client.close()
        if result.get("ok"):
            sessions = result.get("payload", {}).get("sessions", [])
            valid_keys = {s.get("key") for s in sessions}
            return session_key in valid_keys
    except Exception:
        pass
    return False


def _infer_window_from_key(key: str) -> str:
    parts = key.split(":")
    if len(parts) >= 2:
        return parts[1]
    return "unknown"


def _log_and_return(entry: dict, target_hint: str = None) -> dict:
    log_entry = {"ts": time_module.strftime("%Y-%m-%dT%H:%M:%S"), "type": "routing_decision"}
    if target_hint is not None:
        log_entry["target_hint"] = target_hint
    log_entry.update(entry)
    _audit_log(log_entry)
    return entry


def resolve(target_hint: str = None, message: str = None) -> dict:
    """解析路由决策。"""
    if not target_hint:
        return _log_and_return({
            "ok": False, "session_key": None, "canonical_window_id": None,
            "action": ACTION_REJECT,
            "reason": "no target_hint provided, injection forbidden",
            "source": "rejected",
        })

    target_hint = target_hint.strip()
    registry = _load_registry()
    bindings = registry.get("bindings", {})

    # 情况1: target_hint 是 registry 中的 binding key
    if target_hint in bindings:
        binding = bindings[target_hint]
        return _log_and_return({
            "ok": True,
            "session_key": binding["session_key"],
            "canonical_window_id": binding["canonical_window_id"],
            "action": ACTION_INJECT,
            "reason": f"bound via registry: {target_hint}",
            "source": "registry",
        }, target_hint)

    # 情况2: target_hint 反向查找 session_key
    for bind_key, binding in bindings.items():
        if binding.get("session_key") == target_hint:
            return _log_and_return({
                "ok": True,
                "session_key": target_hint,
                "canonical_window_id": binding["canonical_window_id"],
                "action": ACTION_INJECT,
                "reason": f"session_key matched registry binding for {bind_key}",
                "source": "registry",
            }, target_hint)

    # 情况3: catalog inferred
    inferred = registry.get("inferred_from_catalog", {})
    if target_hint in inferred:
        inf = inferred[target_hint]
        return _log_and_return({
            "ok": True,
            "session_key": inf["session_key"],
            "canonical_window_id": inf["canonical_window_id"],
            "action": ACTION_INJECT,
            "reason": f"inferred from catalog: {target_hint}",
            "source": "catalog",
        }, target_hint)

    # 情况4: 完整 session_key → 验证是否真实存在于 Gateway
    if target_hint.startswith("agent:"):
        if _session_key_exists_in_gateway(target_hint):
            return _log_and_return({
                "ok": True,
                "session_key": target_hint,
                "canonical_window_id": _infer_window_from_key(target_hint),
                "action": ACTION_INJECT,
                "reason": "direct session_key verified in Gateway",
                "source": "gateway_verified",
            }, target_hint)
        else:
            return _log_and_return({
                "ok": False,
                "session_key": None,
                "canonical_window_id": None,
                "action": ACTION_REJECT,
                "reason": f"session_key {target_hint} not found in Gateway session list",
                "source": "gateway_verified_reject",
            }, target_hint)

    # 情况5: 未知 window_id/agent_id → REJECT
    return _log_and_return({
        "ok": False,
        "session_key": None,
        "canonical_window_id": None,
        "action": ACTION_REJECT,
        "reason": f"unbound target: {target_hint}, injection forbidden",
        "source": "rejected",
    }, target_hint)


def list_bindings() -> list:
    registry = _load_registry()
    return [{"key": k, **v} for k, v in registry.get("bindings", {}).items()]


def bind(binding_key: str, session_key: str, canonical_window_id: str = None) -> dict:
    if canonical_window_id is None:
        canonical_window_id = _infer_window_from_key(session_key)
    registry = _load_registry()
    registry["bindings"][binding_key] = {
        "session_key": session_key,
        "canonical_window_id": canonical_window_id,
        "bound_at": int(time_module.time() * 1000),
    }
    _save_registry(registry)
    return {"ok": True, "binding_key": binding_key, "session_key": session_key, "canonical_window_id": canonical_window_id}


def unbind(binding_key: str) -> dict:
    registry = _load_registry()
    if binding_key in registry["bindings"]:
        del registry["bindings"][binding_key]
        _save_registry(registry)
        return {"ok": True, "binding_key": binding_key, "removed": True}
    return {"ok": False, "binding_key": binding_key, "reason": "not found"}


def update_catalog_snapshot(catalog_entries: list):
    registry = _load_registry()
    inferred = {}
    for entry in catalog_entries:
        key = entry["canonical_window_id"]
        inferred[key] = {
            "session_key": entry["key"],
            "canonical_window_id": entry["canonical_window_id"],
            "agent_id": entry.get("agent_id"),
            "session_type": entry.get("session_type"),
        }
    registry["inferred_from_catalog"] = inferred
    _save_registry(registry)


def get_registry_status() -> dict:
    registry = _load_registry()
    return {
        "registry_path": REGISTRY_PATH,
        "binding_count": len(registry.get("bindings", {})),
        "inferred_count": len(registry.get("inferred_from_catalog", {})),
        "rules": registry.get("_meta", {}).get("rules", []),
    }
