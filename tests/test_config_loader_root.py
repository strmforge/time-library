import importlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def test_config_loader_ignores_existing_memcore_root_without_config(tmp_path, monkeypatch):
    bad_root = tmp_path / "memcore-cloud-without-config"
    bad_root.mkdir()
    monkeypatch.setenv("MEMCORE_ROOT", str(bad_root))
    monkeypatch.delenv("MEMCORE_CONFIG", raising=False)
    for name in ["config_loader", "src.config_loader"]:
        sys.modules.pop(name, None)
    monkeypatch.syspath_prepend(str(SRC))

    cfg = importlib.import_module("config_loader")

    assert os.path.abspath(cfg.base_path()) == os.path.abspath(str(ROOT))
    assert str(bad_root) not in cfg.base_path()


def test_config_loader_keeps_valid_memcore_root(tmp_path, monkeypatch):
    root = tmp_path / "memcore"
    (root / "config").mkdir(parents=True)
    (root / "config" / "memcore.json").write_text(
        '{"paths":{"base":"."},"nodes":{"current":"unit-test"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MEMCORE_ROOT", str(root))
    monkeypatch.delenv("MEMCORE_CONFIG", raising=False)
    for name in ["config_loader", "src.config_loader"]:
        sys.modules.pop(name, None)
    monkeypatch.syspath_prepend(str(SRC))

    cfg = importlib.import_module("config_loader")

    assert os.path.abspath(cfg.base_path()) == os.path.abspath(str(root))
    assert cfg.node_id() == "unit-test"


def test_window_binding_registry_ignores_existing_bad_memcore_root(tmp_path, monkeypatch):
    bad_root = tmp_path / "memcore-cloud-without-config"
    bad_root.mkdir()
    monkeypatch.setenv("MEMCORE_ROOT", str(bad_root))
    monkeypatch.delenv("MEMCORE_CONFIG", raising=False)
    for name in ["config_loader", "src.config_loader", "window_binding_registry", "src.window_binding_registry"]:
        sys.modules.pop(name, None)
    monkeypatch.syspath_prepend(str(SRC))

    cfg = importlib.import_module("config_loader")
    registry = importlib.import_module("window_binding_registry")

    resolved = registry.registry_path()
    assert str(resolved).startswith(cfg.get_memcore_root())
    assert str(bad_root) not in str(resolved)
