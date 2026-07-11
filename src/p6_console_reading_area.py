#!/usr/bin/env python3
"""Read-only Reading Room projection for the product console."""

import os


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _safe_string(value, limit=240):
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _reading_area_registry_path(memcore_root):
    return os.path.join(str(memcore_root), "config", "reading_area_registry.json")


def _project_name_map_from_registry(registry):
    projects = registry.get("projects") if isinstance(registry, dict) and isinstance(registry.get("projects"), dict) else {}
    result = {}
    for project_id, project in projects.items():
        if not isinstance(project, dict):
            continue
        name = _safe_string(project.get("name") or project_id, 120)
        if project_id and name:
            result[str(project_id)] = name
    return result


def _compact_reading_area_lane(lane):
    shelf_counts = lane.get("shelf_counts") if isinstance(lane, dict) and isinstance(lane.get("shelf_counts"), dict) else {}
    return {
        "agent": _safe_string(lane.get("agent"), 80) if isinstance(lane, dict) else "",
        "item_count": _safe_int(lane.get("item_count")) if isinstance(lane, dict) else 0,
        "shelf_counts": {str(key): _safe_int(value) for key, value in shelf_counts.items()},
        "library_ids": [
            _safe_string(item, 80)
            for item in (lane.get("library_ids") if isinstance(lane, dict) and isinstance(lane.get("library_ids"), list) else [])
            if _safe_string(item, 80)
        ][:8],
    }


def _compact_reading_area_page(page, project_names):
    page = page if isinstance(page, dict) else {}
    project_id = _safe_string(page.get("project_id"), 180)
    whiteboard = page.get("whiteboard") if isinstance(page.get("whiteboard"), dict) else {}
    history = page.get("history") if isinstance(page.get("history"), dict) else {}
    return {
        "contract": page.get("contract", ""),
        "project_id": project_id,
        "project_name": project_names.get(project_id) or project_id,
        "read_only": True,
        "write_performed": False,
        "lane_count": _safe_int(page.get("lane_count")),
        "visible_lane_count": _safe_int(page.get("visible_lane_count")),
        "library_id_count": len(page.get("library_id_pull_handles") or []) if isinstance(page.get("library_id_pull_handles"), list) else 0,
        "visible_library_ids": [
            _safe_string(item, 80)
            for item in (page.get("visible_library_id_pull_handles") if isinstance(page.get("visible_library_id_pull_handles"), list) else [])
            if _safe_string(item, 80)
        ][:12],
        "whiteboard": {
            "record_count": _safe_int(whiteboard.get("record_count")),
            "visible_record_count": _safe_int(whiteboard.get("visible_record_count")),
            "lines": [_safe_string(item, 220) for item in (whiteboard.get("lines") or []) if _safe_string(item, 220)][:6],
            "record_ids": [_safe_string(item, 80) for item in (whiteboard.get("visible_record_ids") or []) if _safe_string(item, 80)][:8],
            "contains_body_markers": bool(whiteboard.get("contains_body_markers")),
        },
        "history": {
            "record_count": _safe_int(history.get("record_count")),
            "visible_record_count": _safe_int(history.get("visible_record_count")),
            "lines": [_safe_string(item, 220) for item in (history.get("lines") or []) if _safe_string(item, 220)][:6],
            "record_ids": [_safe_string(item, 80) for item in (history.get("visible_record_ids") or []) if _safe_string(item, 80)][:8],
            "contains_body_markers": bool(history.get("contains_body_markers")),
        },
        "lanes": [_compact_reading_area_lane(lane) for lane in (page.get("visible_lane_summaries") or []) if isinstance(lane, dict)][:8],
    }


def build_reading_area_summary(memcore_root, *, load_registry, build_catalog):
    """Return the product-console Reading Room summary without exposing bodies."""
    load_reading_area_registry = load_registry
    build_catalog_inject_from_candidates = build_catalog
    MEMCORE_ROOT = memcore_root

    registry_path = _reading_area_registry_path(memcore_root)
    registry = load_reading_area_registry(registry_path)
    project_names = _project_name_map_from_registry(registry)
    try:
        catalog = build_catalog_inject_from_candidates(
            target_tokens=1500,
            xingce_root=str(MEMCORE_ROOT),
            reading_area_registry_path=registry_path,
            include_raw_index=True,
        )
    except Exception as exc:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
            "reading_area_content_write_performed": False,
            "error": "reading_area_summary_failed",
            "detail": f"{type(exc).__name__}: {str(exc)[:180]}",
            "project_pages": [],
            "project_page_count": 0,
            "whiteboard": {"record_count": 0, "lines": []},
            "history": {"record_count": 0, "lines": []},
            "shelf_counts": {},
        }

    projection = catalog.get("reading_area_projection") if isinstance(catalog.get("reading_area_projection"), dict) else {}
    shelf_counts = {}
    for shelf, section in (projection.get("shelf_sections") or {}).items():
        if isinstance(section, dict):
            shelf_counts[str(shelf)] = _safe_int(section.get("entry_count"))
    whiteboard = projection.get("whiteboard") if isinstance(projection.get("whiteboard"), dict) else {}
    history = projection.get("history") if isinstance(projection.get("history"), dict) else {}
    project_pages = [
        _compact_reading_area_page(page, project_names)
        for page in (projection.get("project_pages") or [])
        if isinstance(page, dict)
    ]
    return {
        "ok": bool(catalog.get("ok")),
        "contract": "time_library_console_reading_area_summary.v1",
        "source_contract": projection.get("contract", ""),
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "reading_area_content_write_performed": False,
        "projection_only": True,
        "summary_only": True,
        "not_a_new_memory_layer": True,
        "not_a_sixth_shelf": True,
        "raw_pull_required_for_body": True,
        "startup_instruction_mode": catalog.get("startup_instruction_mode", ""),
        "catalog_entry_count": _safe_int(catalog.get("catalog_entry_count")),
        "catalog_token_count": _safe_int(catalog.get("catalog_token_count")),
        "reading_area_project_page_count": _safe_int(catalog.get("reading_area_project_page_count")),
        "project_page_count": len(project_pages),
        "shelf_counts": shelf_counts,
        "project_pages": project_pages,
        "whiteboard": {
            "record_count": _safe_int(whiteboard.get("record_count")),
            "visible_record_count": _safe_int(whiteboard.get("visible_record_count")),
            "lines": [_safe_string(item, 220) for item in (whiteboard.get("lines") or []) if _safe_string(item, 220)][:8],
            "record_ids": [_safe_string(item, 80) for item in (whiteboard.get("visible_record_ids") or []) if _safe_string(item, 80)][:8],
            "contains_body_markers": bool(whiteboard.get("contains_body_markers")),
        },
        "history": {
            "record_count": _safe_int(history.get("record_count")),
            "visible_record_count": _safe_int(history.get("visible_record_count")),
            "lines": [_safe_string(item, 220) for item in (history.get("lines") or []) if _safe_string(item, 220)][:8],
            "record_ids": [_safe_string(item, 80) for item in (history.get("visible_record_ids") or []) if _safe_string(item, 80)][:8],
            "contains_body_markers": bool(history.get("contains_body_markers")),
        },
        "registry_counts": {
            "borrowing_cards": len(registry.get("borrowing_cards") or {}) if isinstance(registry.get("borrowing_cards"), dict) else 0,
            "projects": len(registry.get("projects") or {}) if isinstance(registry.get("projects"), dict) else 0,
            "whiteboard_records": len(registry.get("whiteboard_records") or []) if isinstance(registry.get("whiteboard_records"), list) else 0,
            "project_history_records": len(registry.get("project_history_records") or []) if isinstance(registry.get("project_history_records"), list) else 0,
        },
        "contains_body_markers": bool(projection.get("contains_body_markers"))
        or bool(whiteboard.get("contains_body_markers"))
        or bool(history.get("contains_body_markers")),
    }
