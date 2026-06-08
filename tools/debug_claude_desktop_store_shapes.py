#!/usr/bin/env python3
"""Redacted Claude Desktop local-store shape probe.

This diagnostic intentionally reports structure only: key paths, array shapes,
role-like enum values, parser candidate counts, and file metadata. It must not
print conversation text, raw excerpts, cookies, tokens, or config values.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src import claude_desktop_connector as connector
except ImportError:
    sys.path.insert(0, str(ROOT / "src"))
    import claude_desktop_connector as connector  # type: ignore


INTERESTING_KEY_RE = re.compile(
    r"conversation|message|chat|content|role|sender|author|uuid|session|thread|title|prompt|completion|text|artifact|turn|node|mapping",
    re.I,
)
ROLE_VALUES = {"user", "human", "assistant", "ai", "model", "system", "tool"}
SENSITIVE_KEY_RE = re.compile(r"key|token|secret|password|auth|credential|cookie", re.I)


def _safe_path(path: str | Path) -> str:
    text = str(path)
    try:
        home = str(Path.home())
        if home and text.startswith(home):
            return "~" + text[len(home):]
    except Exception:
        pass
    return text


def _value_shape(value: Any) -> dict[str, Any]:
    shape: dict[str, Any] = {"type": type(value).__name__}
    if isinstance(value, str):
        stripped = value.strip()
        shape["len"] = len(value)
        if stripped.lower() in ROLE_VALUES:
            shape["enum_value"] = stripped.lower()
    elif isinstance(value, (int, float, bool)) or value is None:
        text = str(value)
        shape["len"] = len(text)
        if text.strip().lower() in ROLE_VALUES:
            shape["enum_value"] = text.strip().lower()
    elif isinstance(value, list):
        shape["len"] = len(value)
        shape["item_types"] = sorted({type(item).__name__ for item in value[:20]})
        dict_keys: list[list[str]] = []
        for item in value[:5]:
            if isinstance(item, dict):
                dict_keys.append(list(item.keys())[:30])
        if dict_keys:
            shape["sample_item_keys"] = dict_keys
    elif isinstance(value, dict):
        shape["keys"] = [
            "<sensitive>" if SENSITIVE_KEY_RE.search(str(key)) else str(key)
            for key in list(value.keys())[:40]
        ]
    return shape


def _walk_shapes(value: Any, prefix: str = "", depth: int = 0, out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if out is None:
        out = []
    if depth > 7:
        return out
    if isinstance(value, dict):
        for key, child in list(value.items())[:120]:
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if INTERESTING_KEY_RE.search(key_text):
                safe_path = re.sub(SENSITIVE_KEY_RE, "<sensitive>", path)
                out.append({"path": safe_path, **_value_shape(child)})
            _walk_shapes(child, path, depth + 1, out)
    elif isinstance(value, list):
        if value and any(isinstance(item, dict) for item in value[:20]):
            out.append({
                "path": prefix or "[]",
                **_value_shape(value),
            })
        for index, item in enumerate(value[:40]):
            _walk_shapes(item, f"{prefix}[{index}]", depth + 1, out)
    return out


def _object_summary(obj: dict[str, Any], artifact: dict[str, Any], path: Path, index: int) -> dict[str, Any]:
    messages = connector._collect_messages(obj)  # noqa: SLF001 - diagnostic intentionally exercises parser internals.
    try:
        candidate = connector._candidate_from_obj(obj, artifact, path, index)  # noqa: SLF001
    except Exception as exc:
        candidate = {"error": f"{type(exc).__name__}:{str(exc)[:80]}"}
    return {
        "object_index": index,
        "top_keys": [
            "<sensitive>" if SENSITIVE_KEY_RE.search(str(key)) else str(key)
            for key in list(obj.keys())[:60]
        ],
        "interesting_shapes": _walk_shapes(obj)[:80],
        "parser_messages_count": len(messages),
        "parser_roles": sorted({str(message.get("role") or "") for message in messages if message.get("role")}),
        "candidate_now": bool(candidate),
        "candidate_roles": candidate.get("roles", []) if isinstance(candidate, dict) else [],
        "candidate_message_count": candidate.get("message_count", 0) if isinstance(candidate, dict) else 0,
    }


def build_probe(file_limit: int, object_limit: int, sample_limit: int) -> dict[str, Any]:
    artifacts = [
        item for item in connector.discover_artifacts(limit=80)
        if item.get("artifact_type") in connector.PARSER_ARTIFACT_TYPES
    ]
    output: dict[str, Any] = {
        "ok": True,
        "source_system": connector.SOURCE_SYSTEM,
        "redacted": True,
        "message_text_returned": False,
        "raw_excerpt_returned": False,
        "artifact_count": len(artifacts),
        "objects_seen": 0,
        "objects_with_interesting_shapes": 0,
        "objects_with_parser_messages": 0,
        "candidate_count": 0,
        "artifacts": [],
        "samples": [],
    }

    for artifact in artifacts:
        files = connector._parser_files_from_artifact(artifact, file_limit)  # noqa: SLF001
        artifact_out = {
            "artifact_type": artifact.get("artifact_type", ""),
            "source_path": _safe_path(artifact.get("source_path", "")),
            "file_count": len(files),
            "files": [],
        }
        for path in files:
            file_out: dict[str, Any] = {
                "path": _safe_path(path),
                "suffix": path.suffix.lower(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "json_objects": 0,
                "interesting_objects": 0,
                "parser_message_objects": 0,
                "candidate_objects": 0,
            }
            fragments = connector._decode_file_fragments(path)  # noqa: SLF001
            for fragment in fragments:
                for index, obj in enumerate(connector._balanced_json_objects(fragment, limit=object_limit)):  # noqa: SLF001
                    output["objects_seen"] += 1
                    file_out["json_objects"] += 1
                    summary = _object_summary(obj, artifact, path, index)
                    interesting = bool(summary["interesting_shapes"])
                    if interesting:
                        output["objects_with_interesting_shapes"] += 1
                        file_out["interesting_objects"] += 1
                    if summary["parser_messages_count"]:
                        output["objects_with_parser_messages"] += 1
                        file_out["parser_message_objects"] += 1
                    if summary["candidate_now"]:
                        output["candidate_count"] += 1
                        file_out["candidate_objects"] += 1
                    if (
                        (interesting or summary["parser_messages_count"] or summary["candidate_now"])
                        and len(output["samples"]) < sample_limit
                    ):
                        output["samples"].append({
                            "artifact_type": artifact.get("artifact_type", ""),
                            "file": _safe_path(path),
                            **summary,
                        })
            if file_out["json_objects"] or file_out["interesting_objects"]:
                artifact_out["files"].append(file_out)
        output["artifacts"].append(artifact_out)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Claude Desktop local-store shapes without returning message text.")
    parser.add_argument("--file-limit", type=int, default=80)
    parser.add_argument("--object-limit", type=int, default=300)
    parser.add_argument("--sample-limit", type=int, default=40)
    args = parser.parse_args()
    payload = build_probe(
        file_limit=max(1, min(args.file_limit, 500)),
        object_limit=max(1, min(args.object_limit, 1000)),
        sample_limit=max(0, min(args.sample_limit, 200)),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
