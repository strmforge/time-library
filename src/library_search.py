#!/usr/bin/env python3
"""Read-only library search backed by P3 recall and the five-shelf catalog."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


LIBRARY_SEARCH_CONTRACT = "time_library_product_search.v1"
DEFAULT_P3_URL = "http://127.0.0.1:9830/recall"


def _compact(value, limit=260):
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    return text if len(text) <= limit else text[:limit]


def _memory_shelf(item):
    memory_type = str(item.get("type") or item.get("_type") or "").strip().lower()
    if item.get("_xingce") or memory_type == "xingce_work_experience_candidate":
        return "xingce"
    if "toolbook" in memory_type:
        return "toolbook"
    if "errata" in memory_type:
        return "errata"
    if memory_type in {"preference_memory", "case_memory", "error_memory"}:
        return "zhiyi"
    return "zhiyi"


def _type_label(memory_type, shelf):
    return {
        "preference_memory": "偏好",
        "case_memory": "案例",
        "error_memory": "纠错",
        "xingce_work_experience_candidate": "经验",
        "zhiyi": "偏好层",
        "xingce": "经验层",
        "toolbook": "工具书",
        "errata": "勘误",
        "raw": "原始记录",
    }.get(memory_type, {"zhiyi": "偏好层", "xingce": "经验层"}.get(shelf, shelf))


def _memory_item(item, index):
    memory_type = str(item.get("type") or item.get("_type") or "").strip()
    shelf = _memory_shelf(item)
    archive = item.get("archive_card") if isinstance(item.get("archive_card"), dict) else {}
    summary = _compact(item.get("summary") or item.get("injectable_context") or item.get("detail"), 320)
    detail = _compact(item.get("detail") or summary, 500)
    title = _compact(archive.get("title") or summary or item.get("exp_id") or "馆藏记录", 80)
    source_refs = item.get("source_refs") if isinstance(item.get("source_refs"), dict) else {}
    exp_id = str(item.get("exp_id") or "").strip()
    library_id = str(
        item.get("library_id")
        or archive.get("library_id")
        or item.get("catalog_id")
        or ""
    ).strip()
    return {
        "id": library_id or exp_id or "recall:" + str(index),
        "library_id": library_id,
        "exp_id": exp_id,
        "shelf": shelf,
        "type": memory_type,
        "type_label": _type_label(memory_type, shelf),
        "title": title,
        "one_line_description": summary,
        "detail": detail,
        "quote_excerpt": "",
        "status": str((item.get("_lifecycle") or {}).get("status") or "active"),
        "has_source_refs": bool(source_refs),
        "recyclable": bool(exp_id and memory_type in {"preference_memory", "case_memory", "error_memory"}),
        "matched_by": str(item.get("matched_by") or ""),
        "confidence": item.get("confidence"),
    }


def _catalog_item(entry, index):
    shelf = str(entry.get("shelf") or "").strip()
    title = _compact(entry.get("title") or entry.get("library_id") or "馆藏目录", 80)
    detail = _compact(entry.get("when_to_use") or title, 500)
    return {
        "id": str(entry.get("library_id") or "catalog:" + str(index)),
        "library_id": str(entry.get("library_id") or ""),
        "exp_id": "",
        "shelf": shelf,
        "type": shelf,
        "type_label": _type_label(shelf, shelf),
        "title": title,
        "one_line_description": detail,
        "detail": detail,
        "quote_excerpt": "",
        "status": "active",
        "has_source_refs": bool(entry.get("source_ref")),
        "recyclable": False,
        "matched_by": "catalog",
        "confidence": None,
    }


def _dedupe(items, limit):
    output = []
    seen = set()
    for item in items:
        key = str(item.get("library_id") or item.get("exp_id") or "").strip()
        if not key:
            key = (str(item.get("title") or "") + "|" + str(item.get("detail") or "")).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
        if len(output) >= limit:
            break
    return output


def _catalog_matches(query, memcore_root, catalog_builder):
    if catalog_builder is None:
        try:
            from src.p4_provider import build_catalog_inject_from_candidates
        except Exception:
            from p4_provider import build_catalog_inject_from_candidates
        catalog_builder = build_catalog_inject_from_candidates
    registry_path = os.path.join(str(memcore_root), "config", "reading_area_registry.json")
    result = catalog_builder(
        target_tokens=2000,
        xingce_root=str(memcore_root),
        reading_area_registry_path=registry_path,
        include_raw_index=True,
    )
    normalized = query.casefold()
    matches = []
    for index, entry in enumerate(result.get("catalog") or []):
        if not isinstance(entry, dict):
            continue
        haystack = " ".join(str(entry.get(key) or "") for key in ("library_id", "shelf", "title", "when_to_use")).casefold()
        if normalized in haystack:
            matches.append(_catalog_item(entry, index))
    return matches, {
        "ok": bool(result.get("ok")),
        "entry_count": int(result.get("catalog_entry_count") or len(result.get("catalog") or [])),
        "matched_count": len(matches),
    }


def _p3_matches(query, limit, p3_url, urlopen):
    payload = {
        "query": query,
        "top_k": limit,
        "threshold": 0.0,
        "recall_mode": "substring",
        "fts5_recall": True,
        "structure_analysis": False,
    }
    request = urllib.request.Request(
        p3_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urlopen or urllib.request.urlopen
    with opener(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))
    memories = [item for item in (result.get("matched_memories") or []) if isinstance(item, dict)]
    return [_memory_item(item, index) for index, item in enumerate(memories)], {
        "ok": True,
        "returned": int(result.get("returned") or len(memories)),
        "total_matched": int(result.get("total_matched") or len(memories)),
        "fts5_applied": bool(result.get("fts5_applied")),
        "recall_methods_used": result.get("recall_methods_used") or [],
        "freshness_boundary": result.get("freshness_boundary") or "",
    }


def search_library(
    query,
    *,
    memcore_root,
    limit=40,
    p3_url="",
    urlopen=None,
    catalog_builder=None,
):
    query = _compact(query, 500)
    limit = max(1, min(int(limit or 40), 100))
    if not query:
        return {
            "ok": False,
            "contract": LIBRARY_SEARCH_CONTRACT,
            "read_only": True,
            "write_performed": False,
            "error": "query_required",
            "items": [],
            "returned": 0,
        }

    catalog_items = []
    catalog_status = {"ok": False, "error": "catalog_unavailable"}
    try:
        catalog_items, catalog_status = _catalog_matches(query, memcore_root, catalog_builder)
    except Exception as exc:
        catalog_status = {"ok": False, "error": exc.__class__.__name__}

    p3_items = []
    p3_status = {"ok": False, "error": "p3_unavailable"}
    try:
        p3_items, p3_status = _p3_matches(
            query,
            limit,
            p3_url or os.environ.get("MEMCORE_P3_RECALL_URL", DEFAULT_P3_URL),
            urlopen,
        )
    except urllib.error.HTTPError as exc:
        p3_status = {"ok": False, "error": "http_" + str(exc.code)}
    except Exception as exc:
        p3_status = {"ok": False, "error": exc.__class__.__name__}

    items = _dedupe(catalog_items + p3_items, limit)
    backend_ok = bool(catalog_status.get("ok") or p3_status.get("ok"))
    return {
        "ok": backend_ok,
        "contract": LIBRARY_SEARCH_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "query": query,
        "scope": "all_active_memory_records_plus_five_shelf_catalog",
        "backend": "p3_fts5_plus_catalog",
        "items": items,
        "returned": len(items),
        "p3": p3_status,
        "catalog": catalog_status,
        "degraded": not bool(p3_status.get("ok") and catalog_status.get("ok")),
        "error": "" if backend_ok else "library_search_backends_unavailable",
    }


__all__ = ["LIBRARY_SEARCH_CONTRACT", "search_library"]
