#!/usr/bin/env python3
"""Build a GitHub-ranked AI agent/panel watchlist for platform discovery."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "config" / "platform_watchlist.github_top100.json"

QUERIES = [
    "topic:ai-agent stars:>100",
    "topic:ai-agents stars:>100",
    "topic:llm-agent stars:>100",
    "topic:autonomous-agents stars:>100",
    "topic:agent-framework stars:>50",
    "topic:mcp-server stars:>50",
    "topic:mcp-client stars:>50",
    "topic:chatbot stars:>1000",
    '"AI agent" stars:>1000',
    '"coding agent" stars:>100',
    '"agent UI" stars:>50',
    '"AI coding" stars:>500',
    '"agentic" stars:>500',
]

FIELDS = "fullName,name,owner,description,stargazersCount,language,url,homepage,updatedAt,pushedAt,isArchived"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return cleaned or "unknown"


def classify(item: dict[str, Any]) -> str:
    text = f"{item.get('fullName', '')} {item.get('description', '')}".lower()
    if any(word in text for word in ("mcp server", "mcp-client", "mcp client", " mcp ")):
        return "mcp_tooling"
    if any(word in text for word in ("coding agent", "code assistant", "terminal", "cli", "claude code", "codex")):
        return "agent_cli_or_coding_harness"
    if any(word in text for word in ("dashboard", "studio", "client", "panel", "ui", "chatgpt clone", "chatbot")):
        return "agent_panel_or_client"
    if any(word in text for word in ("framework", "sdk", "library", "orchestrat", "multi-agent")):
        return "agent_framework"
    if any(word in text for word in ("awesome", "guide", "tutorial", "lessons", "best-practice", "collection")):
        return "agent_resource_collection"
    return "agent_project"


def is_agentish(item: dict[str, Any]) -> bool:
    text = f"{item.get('fullName', '')} {item.get('description', '')}".lower()
    include = (
        "agent",
        "agentic",
        "mcp",
        "chatbot",
        "coding assistant",
        "coding tool",
        "ai client",
        "llm app",
        "workflow automation",
        "claude code",
        "codex",
        "gemini cli",
    )
    exclude = (
        "no agents to install",
        "front-end checklist",
        "telegram-bot",
        "text-to-speech",
    )
    return any(word in text for word in include) and not any(word in text for word in exclude)


def gh_search(query: str) -> list[dict[str, Any]]:
    cmd = [
        "gh",
        "search",
        "repos",
        query,
        "--sort",
        "stars",
        "--limit",
        "80",
        "--json",
        FIELDS,
    ]
    output = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=45)
    data = json.loads(output)
    return [item for item in data if not item.get("isArchived")]


def build_watchlist() -> dict[str, Any]:
    seen: dict[str, dict[str, Any]] = {}
    for query in QUERIES:
        for item in gh_search(query):
            full_name = str(item.get("fullName") or "")
            if not full_name:
                continue
            if full_name not in seen:
                item["_matched_queries"] = []
                seen[full_name] = item
            seen[full_name]["_matched_queries"].append(query)

    ranked = [
        item
        for item in sorted(seen.values(), key=lambda value: int(value.get("stargazersCount") or 0), reverse=True)
        if is_agentish(item)
    ][:100]

    entries = []
    for rank, item in enumerate(ranked, 1):
        owner = item.get("owner") or {}
        owner_login = owner.get("login") if isinstance(owner, dict) else ""
        full_name = str(item.get("fullName") or "")
        repo_name = str(item.get("name") or full_name.rsplit("/", 1)[-1])
        entries.append({
            "id": f"github_{slug(full_name)}",
            "display_name": full_name,
            "family": classify(item),
            "catalog_level": "github_top100_watchlist",
            "rank": rank,
            "aliases": sorted({repo_name, full_name, repo_name.lower(), slug(repo_name)}),
            "repo": {
                "owner": owner_login,
                "name": repo_name,
                "full_name": full_name,
                "url": item.get("url") or f"https://github.com/{full_name}",
                "homepage": item.get("homepage") or "",
                "stars": int(item.get("stargazersCount") or 0),
                "language": item.get("language") or "",
                "updated_at": item.get("updatedAt") or "",
                "pushed_at": item.get("pushedAt") or "",
                "matched_queries": item.get("_matched_queries", []),
            },
            "description": item.get("description") or "",
            "mcp": {
                "supported": "mcp" in f"{full_name} {item.get('description', '')}".lower(),
                "config_keys": ["mcpServers"],
                "candidate_config_paths": [],
            },
            "workspace_markers": [repo_name, full_name],
            "confidence": "github_watchlist",
            "source_urls": [item.get("url") or f"https://github.com/{full_name}"],
            "autoconnect_policy": "discover_only_until_local_mcp_config_or_adapter_is_confirmed",
        })

    return {
        "watchlist_version": "2026.6.1-github-top100.1",
        "generated_from_public_sources_at": ts(),
        "read_only": True,
        "source": "github_search_top_starred",
        "ranking_policy": "Deduplicate GitHub repo search results for AI agents, MCP tooling, coding agents, agent UIs, and chat panels; rank by stars.",
        "query_count": len(QUERIES),
        "entry_count": len(entries),
        "queries": QUERIES,
        "entries": entries,
    }


def main() -> int:
    watchlist = build_watchlist()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(watchlist, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "output": str(OUTPUT),
        "entry_count": watchlist["entry_count"],
        "top": [entry["display_name"] for entry in watchlist["entries"][:10]],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
