import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_bootstrap import ensure_repo_import_paths, memcore_root, repo_root_from_file  # noqa: E402


def test_runtime_bootstrap_resolves_repo_root_from_tool_file(monkeypatch):
    monkeypatch.delenv("MEMCORE_REPO_ROOT", raising=False)
    root = ensure_repo_import_paths(ROOT / "tools" / "record_doctor.py", include_tools=True)

    assert root == ROOT
    assert repo_root_from_file(ROOT / "tools" / "record_doctor.py") == ROOT
    assert str(ROOT) in sys.path[:3]
    assert str(SRC) in sys.path[:3]
    assert str(ROOT / "tools") in sys.path[:3]
    assert os.environ["MEMCORE_REPO_ROOT"] == str(ROOT)


def test_memcore_root_prefers_env_without_mutating(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime-root"
    monkeypatch.setenv("MEMCORE_ROOT", str(runtime_root))

    assert memcore_root(ROOT / "tools" / "record_doctor.py") == runtime_root
