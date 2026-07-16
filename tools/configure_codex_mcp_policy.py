#!/usr/bin/env python3
"""Apply narrow Codex MCP approval policy without rewriting unrelated config."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path


DEFAULT_SERVER = "time-library"
DEFAULT_APPROVED_TOOLS = (
    "time_library_recall",
    "time_library_delivery_ack",
)


def _header_variants(server: str, tool: str = "") -> set[str]:
    server_keys = (server, f'"{server}"', f"'{server}'")
    suffix = f".tools.{tool}" if tool else ""
    return {f"[mcp_servers.{server_key}{suffix}]" for server_key in server_keys}


def _is_table_header(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and "]" in stripped


def _find_sections(lines: list[str], headers: set[str]) -> list[tuple[int, int]]:
    starts = [index for index, line in enumerate(lines) if line.strip() in headers]
    sections: list[tuple[int, int]] = []
    for start in starts:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if _is_table_header(lines[index]):
                end = index
                break
        sections.append((start, end))
    return sections


def _atomic_write(path: Path, text: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.time-library-policy-",
            delete=False,
        ) as handle:
            handle.write(text)
            temporary_path = Path(handle.name)
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def configure_codex_mcp_policy(
    config_path: Path,
    *,
    server: str = DEFAULT_SERVER,
    approved_tools: tuple[str, ...] = DEFAULT_APPROVED_TOOLS,
) -> dict[str, object]:
    config_path = config_path.expanduser()
    if not config_path.is_file():
        return {
            "ok": False,
            "changed": False,
            "write_performed": False,
            "error": "codex_config_not_found",
        }

    with config_path.open("r", encoding="utf-8", newline="") as handle:
        original = handle.read()
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines(keepends=True)

    server_sections = _find_sections(lines, _header_variants(server))
    if len(server_sections) != 1:
        return {
            "ok": False,
            "changed": False,
            "write_performed": False,
            "error": "codex_mcp_server_section_missing"
            if not server_sections
            else "duplicate_codex_mcp_server_sections",
        }

    for tool in approved_tools:
        sections = _find_sections(lines, _header_variants(server, tool))
        if len(sections) > 1:
            return {
                "ok": False,
                "changed": False,
                "write_performed": False,
                "error": f"duplicate_codex_mcp_tool_section:{tool}",
            }
        if sections:
            start, end = sections[0]
            assignment_indexes = [
                index
                for index in range(start + 1, end)
                if lines[index].lstrip().startswith("approval_mode")
                and "=" in lines[index]
            ]
            if len(assignment_indexes) > 1:
                return {
                    "ok": False,
                    "changed": False,
                    "write_performed": False,
                    "error": f"duplicate_codex_mcp_approval_mode:{tool}",
                }
            if assignment_indexes:
                lines[assignment_indexes[0]] = f'approval_mode = "approve"{newline}'
            else:
                lines.insert(end, f'approval_mode = "approve"{newline}')
            continue

        if lines and lines[-1].strip():
            lines.append(newline)
        lines.extend(
            [
                f"[mcp_servers.{server}.tools.{tool}]{newline}",
                f'approval_mode = "approve"{newline}',
            ]
        )

    updated = "".join(lines)
    changed = updated != original
    backup_created = False
    if changed:
        backup_path = config_path.with_name(
            config_path.name + ".time-library-policy.backup"
        )
        shutil.copy2(config_path, backup_path)
        backup_created = True
        _atomic_write(config_path, updated)

    return {
        "ok": True,
        "changed": changed,
        "write_performed": changed,
        "backup_created": backup_created,
        "server": server,
        "approved_tools": list(approved_tools),
        "other_tools_auto_approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--approve-tool", action="append", default=[])
    args = parser.parse_args()
    approved_tools = tuple(args.approve_tool) or DEFAULT_APPROVED_TOOLS
    result = configure_codex_mcp_policy(
        args.config,
        server=args.server,
        approved_tools=approved_tools,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
