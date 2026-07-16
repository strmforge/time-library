#!/usr/bin/env python3
"""Read-only reading-area catalog and project-page projections."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

try:
    from src.context_delivery_compaction import build_library_catalog_push
    from src.source_system_taxonomy import canonical_reading_area_lane
    from src.zhixing_library import ZHIXING_SHELVES, attach_library_card
except Exception:  # pragma: no cover
    from context_delivery_compaction import build_library_catalog_push
    from source_system_taxonomy import canonical_reading_area_lane
    from zhixing_library import ZHIXING_SHELVES, attach_library_card


READING_AREA_PROJECTION_CONTRACT = "time_library_reading_area_projection.v1"
PROJECT_DIGEST_PROJECTION_CONTRACT = "time_library_project_digest_projection.v1"
READING_AREA_PAGE_CONTRACT = "time_library_reading_area_project_page.v1"
WHITEBOARD_PROJECTION_CONTRACT = "time_library_whiteboard_projection.v1"
PROJECT_HISTORY_PROJECTION_CONTRACT = "time_library_project_history_projection.v1"
SHELF_ORDER = ["zhiyi", "xingce", "toolbook", "raw", "errata"]
BODY_MARKERS = (
    "verbatim_excerpt",
    "detail:",
    "observed_facts",
    "recommended_procedure",
    "raw_source_excerpt",
    "正文",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value: Any, *, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _string_list(value: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in _as_list(value):
        text = _clean(item, limit=160)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _estimate_tokens(text: str) -> int:
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, (ascii_chars // 4) + (non_ascii_chars // 2)) if text else 0


def _startup_entries_by_shelf(catalog: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped = {shelf: [] for shelf in SHELF_ORDER}
    for entry in catalog.get("catalog") or []:
        if not isinstance(entry, dict):
            continue
        shelf = _clean(entry.get("shelf"), limit=60)
        if shelf in grouped:
            grouped[shelf].append(entry)
    return grouped


def _fit_text_to_token_budget(text: str, target_tokens: int) -> str:
    budget = max(0, int(target_tokens or 0))
    if not text or budget <= 0:
        return ""
    if _estimate_tokens(text) <= budget:
        return text
    suffix = " ..."
    if _estimate_tokens(suffix) > budget:
        suffix = ""
    low = 0
    high = len(text)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid].rstrip()
        if candidate and suffix:
            candidate = candidate + suffix
        if _estimate_tokens(candidate) <= budget:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


def _contains_body_markers(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in BODY_MARKERS)


def _card_for(record: dict[str, Any]) -> dict[str, Any]:
    try:
        attached = attach_library_card(record)
    except Exception:
        attached = {}
    card = attached.get("library_card") if isinstance(attached.get("library_card"), dict) else {}
    return card if isinstance(card, dict) else {}


def _shelf_for(record: dict[str, Any], card: dict[str, Any]) -> str:
    shelf = _clean(card.get("shelf") or record.get("library_shelf") or record.get("shelf"), limit=60)
    return shelf if shelf in SHELF_ORDER else "zhiyi"


def _library_id_for(record: dict[str, Any], card: dict[str, Any]) -> str:
    return _clean(card.get("library_id") or record.get("library_id") or record.get("exp_id"), limit=120)


def _title_for(record: dict[str, Any], card: dict[str, Any]) -> str:
    return _clean(card.get("title") or record.get("title") or record.get("summary") or record.get("exp_id"), limit=80)


def _source_system_for(record: dict[str, Any], card: dict[str, Any]) -> str:
    refs = card.get("source_refs") if isinstance(card.get("source_refs"), dict) else {}
    return canonical_reading_area_lane(
        record.get("source_system") or refs.get("source_system") or "unknown",
    )


def _declared_project_ids(record: dict[str, Any]) -> list[str]:
    ids = _string_list(
        record.get("declared_project_ids")
        or record.get("reading_area_project_ids")
        or record.get("reading_area_project_id")
        or record.get("project_scope_ids")
    )
    # Deliberately ignore record["project_id"]: it is a technical/window anchor
    # in current data and must not become true project identity by inference.
    return ids


def _declared_series_ids(record: dict[str, Any]) -> list[str]:
    return _string_list(
        record.get("declared_series_ids")
        or record.get("reading_area_series_ids")
        or record.get("reading_area_series_id")
        or record.get("series_scope_ids")
    )


def _scope_matches(record: dict[str, Any], *, project_ids: set[str], series_ids: set[str]) -> bool:
    if not project_ids and not series_ids:
        return True
    declared_projects = set(_declared_project_ids(record))
    declared_series = set(_declared_series_ids(record))
    return bool((project_ids and declared_projects & project_ids) or (series_ids and declared_series & series_ids))


def _compact_lane_summary(lane: dict[str, Any]) -> dict[str, Any]:
    shelf_counts = lane.get("shelf_counts") if isinstance(lane.get("shelf_counts"), dict) else {}
    return {
        "agent": _clean(lane.get("agent"), limit=80),
        "item_count": int(lane.get("item_count") or 0),
        "shelf_counts": {
            shelf: int(count)
            for shelf, count in shelf_counts.items()
            if shelf in SHELF_ORDER and int(count or 0) > 0
        },
        "library_ids": _string_list(lane.get("library_ids")),
    }


def _load_registry(path: str | None = None) -> dict[str, Any]:
    try:
        from src.reading_area_registry import load_registry
    except Exception:  # pragma: no cover
        from reading_area_registry import load_registry
    return load_registry(path)


def _whiteboard_declared_project_ids(registry: dict[str, Any]) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    for record in registry.get("whiteboard_records") or []:
        if not isinstance(record, dict):
            continue
        for project_id in _string_list(record.get("declared_project_ids")):
            if project_id and project_id not in seen:
                seen.add(project_id)
                discovered.append(project_id)
    return discovered


def _registry_declared_project_ids(registry: dict[str, Any]) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    for key in ("whiteboard_records", "project_history_records"):
        for record in registry.get(key) or []:
            if not isinstance(record, dict):
                continue
            for project_id in _string_list(record.get("declared_project_ids") or record.get("project_id")):
                if project_id and project_id not in seen:
                    seen.add(project_id)
                    discovered.append(project_id)
    return discovered


def _whiteboard_projection(
    *,
    registry_path: str = "",
    borrowing_card_id: str = "",
    reading_area_id: str = "",
    project_ids: list[str] | None = None,
    series_ids: list[str] | None = None,
    target_chars: int = 450,
    max_lines: int = 3,
) -> dict[str, Any]:
    registry = _load_registry(registry_path or None)
    try:
        from src.reading_area_registry import list_whiteboard_records
    except Exception:  # pragma: no cover
        from reading_area_registry import list_whiteboard_records

    result = list_whiteboard_records(
        borrowing_card_id=borrowing_card_id,
        reading_area_ids=[reading_area_id] if _clean(reading_area_id, limit=160) else [],
        project_ids=project_ids,
        series_ids=series_ids,
        limit=50,
        path=registry_path or None,
    )
    records = [item for item in result.get("records", []) if isinstance(item, dict)]
    kept: list[dict[str, Any]] = []
    kept_lines: list[str] = []
    omitted = 0
    for record in records:
        line = _clean(record.get("display_line"), limit=220)
        if not line:
            continue
        if len(kept_lines) >= max(1, int(max_lines or 3)):
            omitted += 1
            continue
        candidate_lines = kept_lines + [line]
        if sum(len(item) for item in candidate_lines) + max(0, len(candidate_lines) - 1) <= max(0, int(target_chars or 0)):
            kept_lines.append(line)
            kept.append(record)
        else:
            omitted += 1
    suffix = ""
    if omitted:
        suffix = f"还有 {omitted} 条白板记录用编号取。"
        while kept_lines and (
            sum(len(item) for item in kept_lines + [suffix]) + len(kept_lines)
        ) > max(0, int(target_chars or 0)):
            kept_lines.pop()
            if kept:
                kept.pop()
            omitted += 1
            suffix = f"还有 {omitted} 条白板记录用编号取。"
        if suffix and (sum(len(item) for item in kept_lines + [suffix]) + len(kept_lines)) <= max(0, int(target_chars or 0)):
            kept_lines.append(suffix)
    visible_record_ids = [_clean(item.get("record_id"), limit=40) for item in kept if _clean(item.get("record_id"), limit=40)]
    return {
        "ok": bool(result.get("ok")),
        "error": _clean(result.get("error"), limit=120),
        "contract": WHITEBOARD_PROJECTION_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "reading_area_content_write_performed": False,
        "projection_revision": int(((registry.get("_meta") or {}).get("projection_revision") or 0)),
        "updated_at": str(((registry.get("_meta") or {}).get("updated_at") or "")),
        "record_count": int(result.get("record_count") or 0),
        "visible_record_count": len(kept),
        "visible_record_ids": visible_record_ids,
        "records": kept,
        "lines": kept_lines,
        "char_count": sum(len(item) for item in kept_lines) + max(0, len(kept_lines) - 1),
        "char_budget": int(target_chars or 0),
        "max_lines": max(1, int(max_lines or 3)),
        "omitted_record_count": max(0, int(result.get("record_count") or 0) - len(kept)),
        "contains_body_markers": _contains_body_markers("\n".join(kept_lines)),
        "source_ref_policy": "whiteboard_records_are_registry_projection_only_with_source_refs_in_record",
        "scope": result.get("scope", {}),
    }


def _project_history_projection(
    *,
    registry_path: str = "",
    borrowing_card_id: str = "",
    project_ids: list[str] | None = None,
    series_ids: list[str] | None = None,
    target_chars: int = 600,
    max_lines: int = 5,
) -> dict[str, Any]:
    registry = _load_registry(registry_path or None)
    try:
        from src.reading_area_registry import list_project_history_records
    except Exception:  # pragma: no cover
        from reading_area_registry import list_project_history_records

    result = list_project_history_records(
        borrowing_card_id=borrowing_card_id,
        project_ids=project_ids,
        series_ids=series_ids,
        limit=50,
        path=registry_path or None,
    )
    records = [item for item in result.get("records", []) if isinstance(item, dict)]
    kept: list[dict[str, Any]] = []
    lines: list[str] = []
    omitted = 0
    for record in records:
        line = _clean(record.get("display_line") or record.get("title"), limit=220)
        if not line:
            continue
        if len(lines) >= max(1, int(max_lines or 5)):
            omitted += 1
            continue
        candidate = "\n".join([*lines, line]) if lines else line
        if len(candidate) <= max(0, int(target_chars or 0)):
            lines.append(line)
            kept.append(record)
        else:
            omitted += 1
    ids = [_clean(item.get("record_id"), limit=60) for item in kept if _clean(item.get("record_id"), limit=60)]
    return {
        "ok": bool(result.get("ok")),
        "error": _clean(result.get("error"), limit=120),
        "contract": PROJECT_HISTORY_PROJECTION_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "not_a_sixth_shelf": True,
        "projection_revision": int(((registry.get("_meta") or {}).get("projection_revision") or 0)),
        "record_count": int(result.get("record_count") or 0),
        "visible_record_count": len(kept),
        "visible_record_ids": ids,
        "records": kept,
        "lines": lines,
        "char_count": len("\n".join(lines)),
        "char_budget": int(target_chars or 0),
        "omitted_record_count": max(0, int(result.get("record_count") or 0) - len(kept)),
        "contains_body_markers": _contains_body_markers("\n".join(lines)),
        "source_ref_policy": "project_history_records_keep_source_ref_in_record_and_are_borrowable_by_ph_id",
    }


def build_project_digest_projection(
    records: list[dict[str, Any]] | None,
    *,
    project_id: str,
    project_name: str = "",
    series_ids: list[str] | None = None,
    per_agent_limit: int = 5,
    target_tokens: int = 600,
) -> dict[str, Any]:
    """Build a low-pollution project digest projection.

    The projection uses catalog/card metadata only: shelf, title, and library_id.
    It does not copy raw body, detail, or verbatim excerpts.
    """

    selected_project = _clean(project_id, limit=160)
    selected_series = set(_string_list(series_ids))
    lanes: dict[str, dict[str, Any]] = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if selected_project and selected_project not in _declared_project_ids(record):
            continue
        if selected_series and not (set(_declared_series_ids(record)) & selected_series):
            continue
        card = _card_for(record)
        shelf = _shelf_for(record, card)
        if shelf == "errata":
            continue
        library_id = _library_id_for(record, card)
        title = _title_for(record, card)
        if not library_id or not title:
            continue
        agent = _source_system_for(record, card)
        lane = lanes.setdefault(
            agent,
            {
                "agent": agent,
                "item_count": 0,
                "shelf_counts": {shelf_name: 0 for shelf_name in SHELF_ORDER},
                "headlines": [],
                "library_ids": [],
                "all_library_ids": [],
            },
        )
        lane["item_count"] += 1
        lane["shelf_counts"][shelf] = int(lane["shelf_counts"].get(shelf, 0)) + 1
        lane["all_library_ids"].append(library_id)
        if len(lane["headlines"]) < max(1, min(int(per_agent_limit or 5), 20)):
            lane["headlines"].append(f"[{library_id}] {title}")
            lane["library_ids"].append(library_id)

    raw_lines = []
    for lane in lanes.values():
        shelves = ", ".join(
            f"{shelf}:{count}"
            for shelf, count in lane["shelf_counts"].items()
            if count
        )
        headlines = "; ".join(lane["headlines"])
        line = f"- {lane['agent']} ({shelves or 'no shelves'}): {headlines}"
        raw_lines.append(line)
        lane["digest"] = line

    lines: list[str] = []
    truncated = False
    for line in raw_lines:
        candidate = "\n".join([*lines, line]) if lines else line
        if _estimate_tokens(candidate) <= target_tokens:
            lines.append(line)
            continue
        truncated = True
        if not lines:
            fitted = _fit_text_to_token_budget(line, target_tokens)
            if fitted:
                lines.append(fitted)
        break
    digest_text = "\n".join(lines)
    token_count = _estimate_tokens(digest_text)
    return {
        "ok": True,
        "contract": PROJECT_DIGEST_PROJECTION_CONTRACT,
        "created_at": _now(),
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "reading_area_content_write_performed": False,
        "projection_only": True,
        "summary_only": True,
        "contains_body_markers": _contains_body_markers(digest_text),
        "project_id": selected_project,
        "project_name": _clean(project_name, limit=160) or selected_project,
        "series_ids": sorted(selected_series),
        "lane_count": len(lanes),
        "visible_lane_count": len(lines),
        "truncated": truncated,
        "omitted_lane_count": max(0, len(raw_lines) - len(lines)),
        "lanes": list(lanes.values()),
        "digest_text": digest_text,
        "token_count": token_count,
        "target_tokens": target_tokens,
        "over_budget": token_count > target_tokens,
        "digest_budget_policy": "fit_digest_text_to_target_tokens_without_body",
        "raw_pull_required_for_body": True,
        "library_id_pull_handles": sorted({
            library_id
            for lane in lanes.values()
            for library_id in lane.get("all_library_ids", lane.get("library_ids", []))
        }),
    }


def build_reading_area_catalog_projection(
    records: list[dict[str, Any]] | None,
    *,
    reading_area_id: str = "",
    reading_area_registry_path: str = "",
    borrowing_card_id: str = "",
    project_ids: list[str] | None = None,
    series_ids: list[str] | None = None,
    target_tokens: int = 1200,
    startup_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a five-shelf, project-page aware catalog projection.

    This is a source/test projection only. Startup push can consume it later,
    but this function does not modify startup injection or runtime state.
    """

    requested_project_filter = set(_string_list(project_ids))
    requested_series_filter = set(_string_list(series_ids))
    project_filter = set(requested_project_filter)
    series_filter = set(requested_series_filter)
    registry = _load_registry(reading_area_registry_path or None)
    private_scope_status = "borrowing_card_required"
    scope_denied = False
    if _clean(borrowing_card_id, limit=240):
        try:
            from src.reading_area_registry import _effective_scope_for_card
        except Exception:  # pragma: no cover
            from reading_area_registry import _effective_scope_for_card

        private_scope = _effective_scope_for_card(
            registry,
            borrowing_card_id=borrowing_card_id,
            reading_area_ids=[reading_area_id] if _clean(reading_area_id, limit=160) else [],
            project_ids=sorted(requested_project_filter),
            series_ids=sorted(requested_series_filter),
        )
        if private_scope.get("ok"):
            effective = private_scope["effective"]
            project_filter = set(effective["project_ids"])
            series_filter = set(effective["series_ids"])
            private_scope_status = "granted"
            scope_denied = bool(
                (requested_project_filter or requested_series_filter or _clean(reading_area_id, limit=160))
                and not any(effective.values())
            )
            if scope_denied:
                private_scope_status = "scope_not_declared_by_borrowing_card"
        else:
            project_filter = set()
            series_filter = set()
            private_scope_status = _clean(private_scope.get("error"), limit=120) or "borrowing_card_not_found"
            scope_denied = True
    scoped_records = [
        record
        for record in (records or [])
        if not scope_denied
        and isinstance(record, dict)
        and _scope_matches(record, project_ids=project_filter, series_ids=series_filter)
    ]
    private_projection_card_id = "" if scope_denied else borrowing_card_id
    catalog = startup_catalog if isinstance(startup_catalog, dict) and startup_catalog.get("ok") else build_library_catalog_push(scoped_records, target_tokens=target_tokens)
    entries = catalog.get("catalog") if isinstance(catalog.get("catalog"), list) else []
    shelf_sections = {
        shelf: {
            "shelf": shelf,
            "description": ZHIXING_SHELVES.get(shelf, ""),
            "entry_count": 0,
            "entries": [],
            "pushable": shelf != "errata",
        }
        for shelf in SHELF_ORDER
    }
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        shelf = _clean(entry.get("shelf"), limit=60)
        if shelf not in shelf_sections:
            continue
        shelf_sections[shelf]["entry_count"] += 1
        shelf_sections[shelf]["entries"].append(
            {
                "library_id": entry.get("library_id", ""),
                "title": entry.get("title", ""),
                "when_to_use": entry.get("when_to_use", ""),
                "source_ref": entry.get("source_ref", ""),
            }
        )

    projects = sorted(project_filter)
    if not projects:
        discovered = []
        for record in scoped_records:
            discovered.extend(_declared_project_ids(record))
        if private_scope_status == "granted":
            discovered.extend(project_filter)
        projects = sorted(set(discovered))
    project_pages = []
    for project_id in projects:
        page = build_project_digest_projection(
            scoped_records,
            project_id=project_id,
            series_ids=sorted(series_filter),
            target_tokens=max(300, target_tokens // 2),
        )
        visible_lane_summaries = [
            _compact_lane_summary(lane)
            for lane in (page.get("lanes") or [])[: int(page.get("visible_lane_count") or 0)]
            if isinstance(lane, dict)
        ]
        visible_library_id_set = {
            library_id
            for summary in visible_lane_summaries
            for library_id in _string_list(summary.get("library_ids"))
        }
        visible_library_ids = sorted(visible_library_id_set)
        all_library_id_set = set(_string_list(page.get("library_id_pull_handles")))
        omitted_library_id_count = len(all_library_id_set - visible_library_id_set)
        whiteboard = _whiteboard_projection(
            registry_path=reading_area_registry_path,
            borrowing_card_id=private_projection_card_id,
            reading_area_id=reading_area_id,
            project_ids=[project_id],
            series_ids=sorted(series_filter),
        )
        history = _project_history_projection(
            registry_path=reading_area_registry_path,
            borrowing_card_id=private_projection_card_id,
            project_ids=[project_id],
            series_ids=sorted(series_filter),
        )
        project_pages.append(
            {
                "contract": READING_AREA_PAGE_CONTRACT,
                "project_id": project_id,
                "read_only": True,
                "write_performed": False,
                "contains_body_markers": page["contains_body_markers"],
                "lane_count": page["lane_count"],
                "visible_lane_count": page["visible_lane_count"],
                "truncated": page["truncated"],
                "omitted_lane_count": page["omitted_lane_count"],
                "digest_token_count": page["token_count"],
                "library_id_pull_handles": page["library_id_pull_handles"],
                "visible_library_id_pull_handles": visible_library_ids,
                "omitted_library_id_pull_handles_count": omitted_library_id_count,
                "visible_lane_summaries": visible_lane_summaries,
                "lane_summary_policy": "visible_lanes_only_no_body",
                "digest": page["digest_text"],
                "whiteboard": whiteboard,
                "history": history,
            }
        )

    whiteboard_projection = _whiteboard_projection(
        registry_path=reading_area_registry_path,
        borrowing_card_id=private_projection_card_id,
        reading_area_id=reading_area_id,
        project_ids=projects,
        series_ids=sorted(series_filter),
    )
    history_projection = _project_history_projection(
        registry_path=reading_area_registry_path,
        borrowing_card_id=private_projection_card_id,
        project_ids=projects,
        series_ids=sorted(series_filter),
    )

    startup_grouped = _startup_entries_by_shelf(catalog)
    toc_lines = []
    for shelf in SHELF_ORDER:
        startup_entries = startup_grouped[shelf]
        if startup_entries:
            sample = "; ".join(
                f"[{item['library_id']}] {item.get('title') or item.get('when_to_use') or item['library_id']}"
                for item in startup_entries[:3]
            )
            toc_lines.append(f"- {shelf}: {len(startup_entries)} | {sample}")
        else:
            toc_lines.append(f"- {shelf}: 0")
    for page in project_pages:
        toc_lines.append(f"- project_page:{page['project_id']} lanes={page['lane_count']} ids={len(page['library_id_pull_handles'])}")
    toc_text = "\n".join(toc_lines)
    return {
        "ok": True,
        "contract": READING_AREA_PROJECTION_CONTRACT,
        "created_at": _now(),
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "reading_area_content_write_performed": False,
        "projection_only": True,
        "not_a_new_memory_layer": True,
        "not_a_sixth_shelf": True,
        "startup_injection_modified": False,
        "reading_area_id": _clean(reading_area_id, limit=160),
        "borrowing_card_id": _clean(borrowing_card_id, limit=240) if private_scope_status == "granted" else "",
        "private_projection_access": private_scope_status,
        "project_ids": sorted(project_filter),
        "series_ids": sorted(series_filter),
        "record_count": len(scoped_records),
        "shelf_sections": shelf_sections,
        "project_pages": project_pages,
        "project_page_count": len(project_pages),
        "whiteboard": whiteboard_projection,
        "history": history_projection,
        "catalog_contract": catalog.get("contract", ""),
        "catalog_entry_count": int(catalog.get("entry_count") or 0),
        "catalog_token_count": int(catalog.get("token_count") or 0),
        "startup_catalog": catalog,
        "toc_text": toc_text,
        "toc_token_count": _estimate_tokens(toc_text),
        "target_tokens": target_tokens,
        "contains_body_markers": _contains_body_markers(toc_text)
        or any(page["contains_body_markers"] for page in project_pages)
        or bool(whiteboard_projection.get("contains_body_markers")),
        "history_contains_body_markers": bool(history_projection.get("contains_body_markers")),
        "raw_pull_required_for_body": True,
        "scope_policy": "declared_project_or_series_only_no_technical_project_id_inference",
    }


__all__ = [
    "READING_AREA_PROJECTION_CONTRACT",
    "PROJECT_DIGEST_PROJECTION_CONTRACT",
    "READING_AREA_PAGE_CONTRACT",
    "WHITEBOARD_PROJECTION_CONTRACT",
    "PROJECT_HISTORY_PROJECTION_CONTRACT",
    "build_project_digest_projection",
    "build_reading_area_catalog_projection",
]
