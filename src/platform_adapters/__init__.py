"""
platform_adapters: OS-specific package building adapters
统一整改 Module B: 自动平台识别
"""
import sys

_PLATFORM_ADAPTERS = {
    "linux": "platform_adapters.linux_adapter",
    "darwin": "platform_adapters.macos_adapter",
    "win32": "platform_adapters.windows_adapter",
}

_current_adapter = None

def get_current_platform_adapter():
    """
    返回当前平台的package building adapter。
    N1A仅Linux有真实实现，Windows/macOS为stub。
    """
    global _current_adapter
    if _current_adapter is not None:
        return _current_adapter

    platform = sys.platform
    if platform not in _PLATFORM_ADAPTERS:
        raise NotImplementedError(f"Unsupported platform: {platform}")

    import importlib
    module_name = _PLATFORM_ADAPTERS[platform]
    mod = importlib.import_module(module_name)
    _current_adapter = mod
    return mod

def get_current_platform_name():
    """返回当前平台名称：linux / darwin / win32"""
    return sys.platform

def is_linux():
    return sys.platform == "linux"

def is_macos():
    return sys.platform == "darwin"

def is_windows():
    return sys.platform == "win32"
