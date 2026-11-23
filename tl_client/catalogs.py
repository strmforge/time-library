"""Model catalogs an agent reports: which thinking levels each model takes.

Some agents keep the official list of their models on disk (for example a
cached copy of their provider's model catalog). An agent may report where that
file is; the client reads it in one of two published shapes and passes the
levels on, so the server can offer them as a choice instead of a guess. Nothing
here knows which agent wrote the file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

LEVEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
MAX_BYTES = 12 * 1024 * 1024


def _entries(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("models", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def levels_of(item: Any) -> tuple[list[str], str]:
    """(levels, default) from a model entry: a level list with a default, or a capability tree."""
    if not isinstance(item, dict):
        return [], ""
    levels: list[str] = []
    for name in ("supported_reasoning_levels", "supported_reasoning_efforts", "reasoning_efforts"):
        for level in item.get(name) or []:
            word = level if isinstance(level, str) else (
                level.get("effort") or level.get("reasoning_effort") or level.get("name") if isinstance(level, dict) else None
            )
            if isinstance(word, str) and LEVEL.match(word) and word not in levels:
                levels.append(word)
    capabilities = item.get("capabilities")
    effort = capabilities.get("effort") if isinstance(capabilities, dict) else None
    if isinstance(effort, dict) and effort.get("supported"):
        for word, leaf in effort.items():
            if word != "supported" and isinstance(leaf, dict) and leaf.get("supported") and LEVEL.match(word) and word not in levels:
                levels.append(word)
    default = ""
    for name in ("default_reasoning_level", "default_reasoning_effort"):
        if isinstance(item.get(name), str) and LEVEL.match(item[name]):
            default = item[name]
            break
    return levels, default


def read_catalog(path: str) -> list[dict[str, Any]]:
    """Models with levels from a catalog file; [] when it cannot be read."""
    file = Path(path).expanduser()
    try:
        if file.stat().st_size > MAX_BYTES:
            return []
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = []
    for item in _entries(data):
        if not isinstance(item, dict):
            continue
        model = item.get("slug") or item.get("id") or item.get("model")
        levels, default = levels_of(item)
        if isinstance(model, str) and model and (levels or default):
            found.append({"id": model[:128], "levels": levels, "default": default})
    return found
