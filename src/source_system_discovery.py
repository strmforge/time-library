#!/usr/bin/env python3
"""
P9-System-SDC-B: SourceSystemDiscovery — 统一 Discovery 接口
================================================================
统一所有 source_system 的 discover 入口。
discover(source_system) -> list[artifact]
discover_all() -> dict[source_system, list[artifact]]
discover_with_profile(source_system) -> dict(profile_info, artifacts)
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# Add src/ to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from source_system_profile import (
    get_profile, list_registered_profiles,
    SourceSystemProfile, CAPTURE_SHADOW, CAPTURE_DERIVED, CAPTURE_EXTERNAL
)

UTC = timezone.utc


def discover(source_system: str, dry_run: bool = True) -> List[Dict[str, Any]]:
    """
    统一 discover 入口。

    发现指定 source_system 的所有可用 artifacts。
    始终 dry_run=True（只发现，不采集）。

    Returns:
        list of artifact descriptors
    """
    profile = get_profile(source_system)
    artifacts = profile.discover()

    # Annotate with metadata
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for a in artifacts:
        a["_discovered_at"] = ts
        a["_source_system"] = source_system
        a["_profile"] = profile.profile
        a["_dry_run"] = dry_run

    return artifacts


def discover_all(dry_run: bool = True) -> Dict[str, List[Dict[str, Any]]]:
    """
    发现所有已注册 source_system 的 artifacts。

    Returns:
        dict: {source_system: [artifacts]}
    """
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = {}

    for ss in list_registered_profiles():
        try:
            artifacts = discover(ss, dry_run=dry_run)
            results[ss] = {
                "source_system": ss,
                "profile": get_profile(ss).profile,
                "discovered_at": ts,
                "artifact_count": len(artifacts),
                "artifacts": artifacts,
            }
        except Exception as e:
            results[ss] = {
                "source_system": ss,
                "profile": "unknown",
                "discovered_at": ts,
                "artifact_count": 0,
                "error": str(e),
                "artifacts": [],
            }

    return results


def discover_with_profile(source_system: str) -> Dict[str, Any]:
    """
    返回 profile_info + artifacts 的完整发现结果。
    """
    profile = get_profile(source_system)
    artifacts = discover(source_system)

    return {
        "source_system": source_system,
        "profile_info": profile.profile_info(),
        "discovered_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "capture_classification": profile.capture_classification,
        "scope_level": profile.scope_level,
    }


def classify_artifacts(artifacts: List[dict]) -> Dict[str, List[dict]]:
    """
    按 capture_classification 对 artifacts 分类。

    Returns:
        {
            "SHADOW": [...],
            "DERIVED": [...],
            "EXTERNAL": [...],
            "RAW": [...],
        }
    """
    classified = {
        "SHADOW": [],
        "DERIVED": [],
        "EXTERNAL": [],
        "RAW": [],
    }
    for a in artifacts:
        cls = a.get("capture_classification", "UNKNOWN")
        classified.get(cls, classified["EXTERNAL"]).append(a)
    return classified


def discovery_summary(results: Dict[str, Any]) -> dict:
    """
    生成 discovery 结果摘要。
    """
    total = 0
    by_classification = {"SHADOW": 0, "DERIVED": 0, "EXTERNAL": 0, "RAW": 0}
    by_source = {}

    for ss, data in results.items():
        if "error" in data:
            by_source[ss] = {"error": data["error"], "count": 0}
            continue

        artifacts = data.get("artifacts", [])
        by_source[ss] = {
            "count": len(artifacts),
            "profile": data.get("profile", ""),
        }

        for a in artifacts:
            cls = a.get("capture_classification", "UNKNOWN")
            by_classification[cls] = by_classification.get(cls, 0) + 1
            total += 1

    return {
        "total_artifacts": total,
        "by_source_system": by_source,
        "by_classification": by_classification,
        "source_systems": list(results.keys()),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(description="SourceSystemDiscovery unified discovery")
    p.add_argument("--source", default="", help="指定 source_system（默认所有）")
    p.add_argument("--all", action="store_true", help="discover 所有 source_system")
    p.add_argument("--summary", action="store_true", help="仅显示摘要")
    p.add_argument("--classify", action="store_true", help="按 capture_classification 分类")
    args = p.parse_args()

    if args.all or args.source:
        ss = args.source if args.source else None

        if ss:
            result = discover_with_profile(ss)
        else:
            results = discover_all()
            result = {
                "results": results,
                "summary": discovery_summary(results),
            }

        if args.summary:
            if "summary" in result:
                print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
            else:
                print(f"artifact_count: {result.get('artifact_count', 0)}")
        elif args.classify:
            if ss:
                artifacts = result.get("artifacts", [])
            else:
                all_artifacts = []
                for data in result.get("results", {}).values():
                    all_artifacts.extend(data.get("artifacts", []))
                artifacts = all_artifacts
            classified = classify_artifacts(artifacts)
            for cls, items in classified.items():
                print(f"\n=== {cls} ({len(items)}) ===")
                for a in items[:5]:
                    print(f"  [{a.get('source_system')}] {a.get('source_path', a.get('session_id', a.get('filename', '?')))}")
                if len(items) > 5:
                    print(f"  ... and {len(items) - 5} more")
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
