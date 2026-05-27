"""
memcore-cloud Source System Registry Runtime Interface
Source system registry

提供运行时接口读取 config/source_system_registry.json，
使 src/ 模块能动态查询当前激活的 source_system。

当 registry 文件缺失时，自动基于 runtime health probe 合成 detected sources。
"""
import json
import os
import sys
from config_loader import get_memcore_root

_REGISTRY_CACHE = None

def _get_registry_path():
    return os.path.join(get_memcore_root(), "config", "source_system_registry.json")

def _probe_openclaw_hermes_via_runtime_profile():
    """Probe OpenClaw and Hermes via tools.runtime_profile module.
    Returns list of dynamically detected source systems.
    """
    try:
        sys.path.insert(0, os.path.join(get_memcore_root(), "tools"))
        from runtime_profile import probe_openclaw_health, probe_hermes_health, detect_source_system_status
        sources = []
        # OpenClaw
        oc_status = detect_source_system_status("openclaw")
        oc_health = probe_openclaw_health()
        sources.append({
            "key": "openclaw",
            "name": "OpenClaw",
            "source_system": "openclaw",
            "status": oc_status,
            "reachable": oc_health.get("reachable", False),
            "registered": False,
            "active": oc_status == "active",
            "detection_method": "http_health_probe",
        })
        # Hermes
        h_status = detect_source_system_status("hermes")
        h_health = probe_hermes_health()
        sources.append({
            "key": "hermes",
            "name": "Hermes",
            "source_system": "hermes",
            "status": h_status,
            "reachable": h_health.get("reachable", False),
            "registered": False,
            "active": h_status == "active",
            "detection_method": "http_health_probe",
        })
        return sources
    except Exception:
        return []

def load_registry():
    """加载source_system_registry.json，支持缓存。缺失时自动合成 detected sources。"""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    path = _get_registry_path()
    if not os.path.exists(path):
        # Registry missing: synthesize from runtime probe
        dynamic = _probe_openclaw_hermes_via_runtime_profile()
        _REGISTRY_CACHE = {"version": None, "sources": dynamic, "dynamic": True}
        return _REGISTRY_CACHE
    with open(path, "r") as f:
        _REGISTRY_CACHE = json.load(f)
    return _REGISTRY_CACHE

def list_source_systems():
    """列出所有注册的source_system"""
    reg = load_registry()
    return reg.get("sources", [])

def get_active_sources():
    """获取所有状态为active的source_system"""
    return [s for s in list_source_systems() if s.get("status") == "active"]

def get_source_by_name(name):
    """按名称获取单个source_system"""
    for s in list_source_systems():
        if s.get("source_system") == name:
            return s
    return None

def reload():
    """强制重新加载registry（绕过缓存）"""
    global _REGISTRY_CACHE
    _REGISTRY_CACHE = None
    return load_registry()
