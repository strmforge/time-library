#!/usr/bin/env python3
"""Debug Claude Code connector discovery without printing message bodies."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    import claude_code_local_connector as c  # noqa: PLC0415

    sessions_root = c.claude_code_projects_root()
    files = [p for p in sessions_root.rglob("*.jsonl") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out = {
        "sessions_root": str(sessions_root),
        "root_exists": sessions_root.exists(),
        "file_count": len(files),
        "first_files": [],
        "discover_count_5": len(c.discover_sessions(limit=5)),
        "discover_count_all": len(c.discover_sessions(limit=0)),
    }
    for path in files[:8]:
        item = {
            "path": str(path),
            "size": path.stat().st_size,
            "summary": c._read_session_summary(path),
        }
        try:
            artifact = c.artifact_from_path(path)
            item["artifact_ok"] = True
            item["artifact_counts"] = {
                "session_id": artifact.get("session_id"),
                "user_message_count": artifact.get("user_message_count"),
                "assistant_message_count": artifact.get("assistant_message_count"),
                "content_message_count": artifact.get("content_message_count"),
                "complete_conversation_candidate": artifact.get("complete_conversation_candidate"),
            }
        except Exception as exc:
            item["artifact_ok"] = False
            item["artifact_error"] = f"{type(exc).__name__}: {exc}"
        out["first_files"].append(item)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
