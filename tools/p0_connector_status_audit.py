#!/usr/bin/env python3
"""Read-only connector status dump for P0 memory guard evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _add_src_path() -> None:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        src = parent / "src"
        if src.exists():
            sys.path.insert(0, str(src))
            return
    sys.path.insert(0, str(Path.cwd() / "src"))


def main() -> None:
    _add_src_path()
    result = {}
    for name in [
        "codex_local_connector",
        "claude_code_local_connector",
        "claude_desktop_connector",
        "kiro_local_connector",
    ]:
        try:
            mod = __import__(name)
            result[name] = mod.status() if hasattr(mod, "status") else {"ok": False, "error": "no_status"}
        except Exception as exc:
            result[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
