#!/usr/bin/env python3
"""Redacted Claude Desktop log shape probe.

Reports JSON/log structure only. It never prints conversation text, raw
excerpts, tokens, cookies, or config values.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


INTERESTING_KEY_RE = re.compile(
    r"conversation|message|chat|content|role|sender|author|uuid|session|thread|title|prompt|completion|text|artifact|turn|user|assistant|model|request|response",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"key|token|secret|password|auth|credential|cookie|bearer", re.I)
ROLE_VALUES = {"user", "human", "assistant", "ai", "model", "system", "tool"}


def _safe_path(path: Path) -> str:
    text = str(path)
    home = str(Path.home())
    if home and text.startswith(home):
        return "~" + text[len(home):]
    return text


def _safe_key(key: Any) -> str:
    text = str(key)
    return "<sensitive>" if SENSITIVE_KEY_RE.search(text) else text


def _value_shape(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"type": type(value).__name__}
    if isinstance(value, str):
        stripped = value.strip()
        result["len"] = len(value)
        if stripped.lower() in ROLE_VALUES:
            result["enum_value"] = stripped.lower()
    elif isinstance(value, (int, float, bool)) or value is None:
        result["len"] = len(str(value))
    elif isinstance(value, list):
        result["len"] = len(value)
        result["item_types"] = sorted({type(item).__name__ for item in value[:20]})
        sample_item_keys: list[list[str]] = []
        for item in value[:5]:
            if isinstance(item, dict):
                sample_item_keys.append([_safe_key(key) for key in list(item.keys())[:30]])
        if sample_item_keys:
            result["sample_item_keys"] = sample_item_keys
    elif isinstance(value, dict):
        result["keys"] = [_safe_key(key) for key in list(value.keys())[:50]]
    return result


def _walk_shapes(value: Any, prefix: str = "", depth: int = 0, out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if out is None:
        out = []
    if depth > 8:
        return out
    if isinstance(value, dict):
        for key, child in list(value.items())[:180]:
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if INTERESTING_KEY_RE.search(key_text):
                out.append({"path": SENSITIVE_KEY_RE.sub("<sensitive>", path), **_value_shape(child)})
            _walk_shapes(child, path, depth + 1, out)
    elif isinstance(value, list):
        if value and any(isinstance(item, dict) for item in value[:20]):
            out.append({"path": prefix or "[]", **_value_shape(value)})
        for index, item in enumerate(value[:40]):
            _walk_shapes(item, f"{prefix}[{index}]", depth + 1, out)
    return out


def _balanced_json_objects(text: str, limit: int) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for match in re.finditer(r"[\[{]", text):
        if len(objects) >= limit:
            break
        try:
            obj, _ = decoder.raw_decode(text[match.start():])
        except Exception:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict):
                    objects.append(item)
                    if len(objects) >= limit:
                        break
    return objects


def _line_json_objects(text: str, limit: int) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for line in text.splitlines():
        if len(objects) >= limit:
            break
        stripped = line.strip()
        if not stripped:
            continue
        for start in ("{", "["):
            index = stripped.find(start)
            if index < 0:
                continue
            try:
                obj = json.loads(stripped[index:])
            except Exception:
                continue
            if isinstance(obj, dict):
                objects.append(obj)
            elif isinstance(obj, list):
                objects.extend(item for item in obj if isinstance(item, dict))
            break
    return objects[:limit]


def build_probe(log_path: Path, limit: int, sample_limit: int) -> dict[str, Any]:
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}:{str(exc)[:120]}",
            "file": _safe_path(log_path),
            "message_text_returned": False,
            "raw_excerpt_returned": False,
        }

    objects = _line_json_objects(text, limit)
    if len(objects) < min(20, limit):
        objects = _balanced_json_objects(text, limit)

    top_key_counts: dict[str, int] = {}
    shape_path_counts: dict[str, int] = {}
    role_enum_counts: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    for obj in objects:
        for key in obj:
            safe = _safe_key(key)
            top_key_counts[safe] = top_key_counts.get(safe, 0) + 1
        shapes = _walk_shapes(obj)
        for shape in shapes:
            path = str(shape.get("path", ""))
            shape_path_counts[path] = shape_path_counts.get(path, 0) + 1
            enum_value = shape.get("enum_value")
            if enum_value:
                role_enum_counts[str(enum_value)] = role_enum_counts.get(str(enum_value), 0) + 1
        if shapes and len(samples) < sample_limit:
            samples.append({
                "top_keys": [_safe_key(key) for key in list(obj.keys())[:80]],
                "shapes": shapes[:120],
            })

    return {
        "ok": True,
        "file": _safe_path(log_path),
        "size_bytes": log_path.stat().st_size,
        "objects": len(objects),
        "redacted": True,
        "message_text_returned": False,
        "raw_excerpt_returned": False,
        "top_key_counts": dict(sorted(top_key_counts.items(), key=lambda item: item[1], reverse=True)[:100]),
        "shape_path_counts": dict(sorted(shape_path_counts.items(), key=lambda item: item[1], reverse=True)[:160]),
        "role_enum_counts": dict(sorted(role_enum_counts.items(), key=lambda item: item[1], reverse=True)),
        "samples": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Claude Desktop log shapes without returning message text.")
    parser.add_argument(
        "--log-path",
        default=str(Path.home() / "AppData" / "Roaming" / "Claude" / "logs" / "main.log"),
    )
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--sample-limit", type=int, default=80)
    args = parser.parse_args()
    payload = build_probe(
        Path(args.log_path),
        limit=max(1, min(args.limit, 20000)),
        sample_limit=max(0, min(args.sample_limit, 200)),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
