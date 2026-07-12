"""OS-specific release package adapters.

All platforms delegate to the same privacy-gated release artifact builder.
"""
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

_PLATFORM_ADAPTERS = {
    "linux": "platform_adapters.linux_adapter",
    "darwin": "platform_adapters.macos_adapter",
    "win32": "platform_adapters.windows_adapter",
}

_current_adapter = None


def build_release_package(version, output_dir=None):
    """Build the canonical release ZIP from the current source checkout."""
    current_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if str(version).strip() != current_version:
        raise ValueError(
            f"requested version {version!r} does not match VERSION {current_version!r}"
        )
    builder_path = ROOT / "tools" / "build_release_artifact.py"
    if not builder_path.is_file():
        raise RuntimeError("release artifact builder is unavailable in this installation")
    spec = importlib.util.spec_from_file_location(
        "time_library_release_artifact_builder",
        builder_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("release artifact builder could not be loaded")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    result = builder.build_artifact(
        source="head" if (ROOT / ".git").exists() else "working-tree",
        output_dir=Path(output_dir) if output_dir else ROOT / "release",
    )
    return Path(result["zip"])

def get_current_platform_adapter():
    """
    返回当前平台的 package building adapter。
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
