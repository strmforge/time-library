#!/usr/bin/env python3
"""
Time Library P4: Context Injection Endpoint
消费 recall 结果，生成 injectable context，
暴露 API 供 OpenClaw 接入调用。
"""
import sys, os, json, argparse, glob, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

PORT = 9840
DEFAULT_CATALOG_TARGET_TOKENS = 1500
STARTUP_INSTRUCTIONS_CHAR_BUDGET = 1500


def _estimate_tokens(text):
    value = str(text or "")
    ascii_chars = sum(1 for ch in value if ord(ch) < 128)
    non_ascii_chars = len(value) - ascii_chars
    return max(1, (ascii_chars // 4) + (non_ascii_chars // 2)) if value else 0

# ─── Prompt 模板 ─────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """你正在使用Time Library的知意档案馆。你是档案员，不是创作者。

{memories}

使用规则：
1. 只把这些档案当作带出处的候选经验，不要把向量相似当成事实本身。
2. 回答中优先引用馆藏号（catalog_id）和来源线索；没有出处时要说明不确定。
3. 如果档案之间冲突或证据不足，不要强行裁决，先列出冲突和缺口。
4. 用户要求“原话、原文、证据、来源”时，应回到 source_refs / verbatim，而不是用摘要替代。
5. 不要改写已保存内容，不要把原文替换成哈希、星号或臆测摘要。
6. 只有当档案与当前问题相关时才使用；无关时忽略。"""

USER_PROMPT_TEMPLATE = """当前问题：{query}"""


def _get_request_query(body):
    """Use the canonical p4 query field while accepting legacy entry callers."""
    return body.get("query") or body.get("message", "")


def _load_handle_recall():
    try:
        from src.p3_recall import handle_recall
    except Exception:
        from p3_recall import handle_recall
    return handle_recall


def _normalize_scope_filter(value):
    """Accept entry-layer dict scope and pass p3 its current string contract."""
    if isinstance(value, dict):
        return (
            value.get("canonical_window_id")
            or value.get("window_id")
            or value.get("scope_filter")
            or ""
        )
    if isinstance(value, str):
        return value
    return ""


def _source_ref_window(source_refs):
    if isinstance(source_refs, dict):
        return source_refs.get("canonical_window_id", "")
    if isinstance(source_refs, list):
        for item in source_refs:
            if isinstance(item, dict) and item.get("canonical_window_id"):
                return item.get("canonical_window_id", "")
    return ""


def _source_ref_text(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value or "")


def _memory_prompt_text(memory):
    mtype = memory.get("type") or memory.get("_type") or ""
    if mtype == "time_library_project_status":
        injectable = str(memory.get("injectable_context") or "").strip()
        if injectable:
            return injectable
    card = memory.get("archive_card") if isinstance(memory.get("archive_card"), dict) else {}
    catalog_id = memory.get("catalog_id") or card.get("catalog_id") or memory.get("exp_id") or ""
    title = card.get("title") or memory.get("summary") or ""
    evidence = card.get("evidence_level") or memory.get("evidence_level") or "unknown"
    summary = str(memory.get("summary") or "")
    return f"[{catalog_id}][evidence:{evidence}] {title} - {summary}".strip()


def build_context(recall_result, query):
    """从 recall 结果构建 injectable context"""
    memories = recall_result.get("matched_memories", [])
    if not memories:
        return {
            "context": "",
            "should_inject": False,
            "memory_count": 0,
        }

    # 生成 memory 段落
    memory_lines = []
    for m in memories:
        mtype = m.get("type", "")
        summary = _memory_prompt_text(m)
        window = _source_ref_window(m.get("source_refs", {}))
        memory_lines.append(f"[{mtype}][{window}] {summary}")

    memory_block = "\n".join(memory_lines)

    # 判断是否注入
    injectable_memories = [m for m in memories if m.get("should_inject", False)]
    should_inject = len(injectable_memories) > 0

    return {
        "context": memory_block,
        "should_inject": should_inject,
        "memory_count": len(memories),
        "injectable_count": len(injectable_memories),
        "system_prompt": SYSTEM_PROMPT_TEMPLATE.format(memories=memory_block),
        "user_prompt": USER_PROMPT_TEMPLATE.format(memories=memory_block, query=query),
    }


def _try_int(value, default):
    try:
        return int(value)
    except Exception:
        return default


def _first_query_value(values, key, default=""):
    value = values.get(key, [default])
    if isinstance(value, list):
        return value[0] if value else default
    return value or default


def _truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _listish(value):
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, "", [], {}):
        return []
    return [value]


def _with_xingce_root_override(xingce_root, loader):
    old_override = os.environ.get("MEMCORE_XINGCE_ROOT_OVERRIDE")
    try:
        if xingce_root:
            os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = xingce_root
        return loader()
    finally:
        if xingce_root:
            if old_override is None:
                os.environ.pop("MEMCORE_XINGCE_ROOT_OVERRIDE", None)
            else:
                os.environ["MEMCORE_XINGCE_ROOT_OVERRIDE"] = old_override


def _catalog_project_root(xingce_root=""):
    return (
        str(xingce_root or "").strip()
        or os.environ.get("MEMCORE_XINGCE_ROOT_OVERRIDE")
        or os.environ.get("MEMCORE_ROOT")
        or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


def _read_json_object(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _zhiyi_candidate_to_memory(candidate, candidate_path):
    record = dict(candidate)
    record.setdefault("_type", "zhiyi_preference_card")
    record.setdefault("type", "preference_memory")
    record.setdefault("library_shelf", "zhiyi")
    record.setdefault("lifecycle_status", candidate.get("lifecycle_status") or "active")
    record.setdefault("exp_id", candidate.get("candidate_id") or candidate.get("exp_id") or "")
    record.setdefault("score", max(float(candidate.get("confidence") or 0.72), 0.72))
    if isinstance(record.get("source_refs"), dict):
        refs = dict(record["source_refs"])
        refs["candidate_path"] = candidate_path
        record["source_refs"] = refs
        record["_source_refs"] = refs
        record.setdefault("project_id", refs.get("project_id", ""))
        record.setdefault("workstream_id", refs.get("workstream_id", ""))
        record.setdefault("task_id", refs.get("task_id", ""))
    record["_zhiyi"] = {
        "candidate_id": record.get("exp_id", ""),
        "candidate_type": candidate.get("candidate_type", ""),
        "source_mode": candidate.get("source_mode", ""),
        "candidate_path": candidate_path,
        "raw_write_performed": False,
        "zhiyi_runtime_write_performed": False,
        "zhiyi_candidate_write_performed": True,
    }
    return record


def _load_zhiyi_preference_candidate_memories(root):
    candidates_dir = os.path.join(root, "output", "zhiyi_preference_cards", "candidates")
    if not os.path.isdir(candidates_dir):
        return []
    records = []
    for path in sorted(glob.glob(os.path.join(candidates_dir, "*.json"))):
        candidate = _read_json_object(path)
        if candidate.get("candidate_type") != "zhiyi_preference_card":
            continue
        if candidate.get("library_shelf") != "zhiyi":
            continue
        if candidate.get("lifecycle_status") in ("deprecated", "superseded", "recycled", "invalid"):
            continue
        if candidate.get("source_mode") != "evidence_bound_model_distill":
            continue
        if not candidate.get("candidate_id"):
            continue
        records.append(_zhiyi_candidate_to_memory(candidate, path))
    return records


def _record_matches_borrowing_card(record, card):
    refs_text = " ".join(
        _source_ref_text(record.get(key))
        for key in ("source_refs", "evidence_refs", "_xingce")
    )
    anchors = card.get("technical_anchors") if isinstance(card.get("technical_anchors"), dict) else {}
    candidates = [
        card.get("canonical_window_id", ""),
        card.get("session_id", ""),
        anchors.get("canonical_window_id", ""),
        anchors.get("session_id", ""),
        anchors.get("source_path", ""),
        anchors.get("project_id", ""),
        anchors.get("source_refs_canonical_window_id", ""),
    ]
    return any(str(value or "").strip() and str(value).strip() in refs_text for value in candidates)


def _apply_declared_reading_area_scopes(records, registry_path=""):
    """Attach self-reported project/series ids from borrowing cards.

    This does not infer project identity from record["project_id"]. A technical
    window/project anchor may match a card only after that card already carries
    declared project/series membership.
    """
    try:
        from src.reading_area_registry import load_registry
    except Exception:
        from reading_area_registry import load_registry

    registry = load_registry(registry_path or None)
    cards = [
        card for card in (registry.get("borrowing_cards") or {}).values()
        if isinstance(card, dict)
        and (card.get("declared_project_ids") or card.get("declared_series_ids") or card.get("declared_reading_area_ids"))
    ]
    enriched = []
    matched = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        copy = dict(record)
        project_ids = set(str(item) for item in copy.get("declared_project_ids") or [] if str(item))
        series_ids = set(str(item) for item in copy.get("declared_series_ids") or [] if str(item))
        area_ids = set(str(item) for item in copy.get("declared_reading_area_ids") or [] if str(item))
        matched_cards = []
        for card in cards:
            if not _record_matches_borrowing_card(copy, card):
                continue
            matched += 1
            matched_cards.append(card.get("card_id", ""))
            project_ids.update(str(item) for item in card.get("declared_project_ids") or [] if str(item))
            series_ids.update(str(item) for item in card.get("declared_series_ids") or [] if str(item))
            area_ids.update(str(item) for item in card.get("declared_reading_area_ids") or [] if str(item))
        if project_ids:
            copy["declared_project_ids"] = sorted(project_ids)
        if series_ids:
            copy["declared_series_ids"] = sorted(series_ids)
        if area_ids:
            copy["declared_reading_area_ids"] = sorted(area_ids)
        if matched_cards:
            copy["reading_area_matched_card_ids"] = sorted(set(str(item) for item in matched_cards if str(item)))
        enriched.append(copy)
    return enriched, {"borrowing_card_count": len(cards), "matched_record_count": matched}


def load_catalog_candidate_records(xingce_root=""):
    """Load file-backed catalog candidates for startup catalog push.

    This is a naked-consumer path: it reads already accepted candidate files
    across shelves and does not require window binding, recall, or query scope.
    """
    try:
        from src.zhixing_library import load_file_backed_library_candidate_records
    except Exception:
        from zhixing_library import load_file_backed_library_candidate_records

    records = load_file_backed_library_candidate_records(xingce_root=xingce_root)
    return records if isinstance(records, list) else []


def _resolve_declared_scope_ids(scope_type, values, registry_path=""):
    try:
        from src.reading_area_registry import resolve_scope_id
    except Exception:
        from reading_area_registry import resolve_scope_id
    result = []
    raw_values = values if isinstance(values, list) else ([] if values in (None, "") else [values])
    for value in raw_values:
        text = str(value or "").strip()
        if not text:
            continue
        resolved = resolve_scope_id(scope_type, text, path=registry_path or None)
        result.append(resolved or text)
    return sorted(set(item for item in result if item))


def build_reading_area_catalog_from_candidates(
    target_tokens=DEFAULT_CATALOG_TARGET_TOKENS,
    xingce_root="",
    reading_area_registry_path="",
    records_db_path="",
    include_raw_index=False,
    project_ids=None,
    series_ids=None,
    reading_area_id="",
    startup_catalog=None,
):
    records = load_catalog_candidate_records(xingce_root=xingce_root)
    raw_index_report = {}
    if include_raw_index:
        try:
            from src.reading_area_raw_index import build_raw_session_index_records
        except Exception:
            from reading_area_raw_index import build_raw_session_index_records
        raw_index_report = build_raw_session_index_records(
            records_db_path=records_db_path or None,
            reading_area_registry_path=reading_area_registry_path or None,
            project_ids=project_ids,
            series_ids=series_ids,
        )
        if raw_index_report.get("ok"):
            records = records + [record for record in raw_index_report.get("records", []) if isinstance(record, dict)]
    scoped_records, scope_meta = _apply_declared_reading_area_scopes(records, registry_path=reading_area_registry_path)
    try:
        from src.reading_area_projection import build_reading_area_catalog_projection
    except Exception:
        from reading_area_projection import build_reading_area_catalog_projection

    resolved_projects = _resolve_declared_scope_ids("project", project_ids, reading_area_registry_path)
    resolved_series = _resolve_declared_scope_ids("series", series_ids, reading_area_registry_path)
    projection = build_reading_area_catalog_projection(
        scoped_records,
        reading_area_id=reading_area_id,
        reading_area_registry_path=reading_area_registry_path,
        project_ids=resolved_projects,
        series_ids=resolved_series,
        target_tokens=target_tokens,
        startup_catalog=startup_catalog,
    )
    return {
        **projection,
        "read_only": True,
        "write_performed": False,
        "content_write_performed": False,
        "scope_source": "borrowing_card_declared_membership",
        "technical_project_id_used_as_declared_identity": False,
        "borrowing_scope_meta": scope_meta,
        "raw_index": {
            "enabled": bool(include_raw_index),
            "contract": raw_index_report.get("contract", "") if isinstance(raw_index_report, dict) else "",
            "record_count": int(raw_index_report.get("record_count") or 0) if isinstance(raw_index_report, dict) else 0,
            "matched_session_count": int(raw_index_report.get("matched_session_count") or 0) if isinstance(raw_index_report, dict) else 0,
            "title_model_used": bool(raw_index_report.get("title_model_used")) if isinstance(raw_index_report, dict) else False,
            "scope_policy": raw_index_report.get("scope_policy", "") if isinstance(raw_index_report, dict) else "",
            "error": raw_index_report.get("error", "") if isinstance(raw_index_report, dict) else "",
        },
    }


def _short_prompt_text(value, *, limit=34):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 3)].rstrip() + "..."


def _catalog_titles_by_id(projection):
    titles = {}
    if not isinstance(projection, dict):
        return titles
    for section in (projection.get("shelf_sections") or {}).values():
        if not isinstance(section, dict):
            continue
        for entry in section.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            library_id = str(entry.get("library_id") or "").strip()
            if library_id:
                titles[library_id] = _short_prompt_text(entry.get("title") or entry.get("when_to_use") or library_id)
    return titles


def _shelf_count_summary(projection):
    parts = []
    for shelf in ("zhiyi", "xingce", "raw", "toolbook", "errata"):
        section = (projection.get("shelf_sections") or {}).get(shelf, {}) if isinstance(projection, dict) else {}
        count = int(section.get("entry_count") or 0) if isinstance(section, dict) else 0
        parts.append(f"{shelf}:{count}")
    return ", ".join(parts)


def _raw_library_ids_from_projection(projection):
    ids = []
    raw_section = (projection.get("shelf_sections") or {}).get("raw", {}) if isinstance(projection, dict) else {}
    if isinstance(raw_section, dict):
        for entry in raw_section.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            library_id = str(entry.get("library_id") or "").strip()
            if library_id and library_id not in ids:
                ids.append(library_id)
    return ids


def _bounded_instruction_lines(lines, *, char_budget=STARTUP_INSTRUCTIONS_CHAR_BUDGET):
    kept = []
    omitted = 0
    for line in lines:
        candidate = "\n".join(kept + [line]).strip()
        if len(candidate) <= char_budget:
            kept.append(line)
        else:
            omitted += 1
    if omitted:
        suffix = f"还有 {omitted} 行未展示；用已见 library_id 或 time_library_recall / catalog-card 取完整目录。"
        while kept and len("\n".join(kept + [suffix]).strip()) > char_budget:
            kept.pop()
            omitted += 1
            suffix = f"还有 {omitted} 行未展示；用已见 library_id 或 time_library_recall / catalog-card 取完整目录。"
        kept.append(suffix)
    return "\n".join(kept).strip(), omitted


def _reading_area_prompt_block(projection):
    if not isinstance(projection, dict) or not projection.get("ok"):
        return ""
    if int(projection.get("project_page_count") or 0) <= 0:
        return ""
    titles_by_id = _catalog_titles_by_id(projection)
    startup_grouped = {}
    startup_catalog = projection.get("startup_catalog") if isinstance(projection.get("startup_catalog"), dict) else {}
    for entry in (startup_catalog.get("catalog") or []):
        if not isinstance(entry, dict):
            continue
        shelf = str(entry.get("shelf") or "").strip()
        if not shelf:
            continue
        startup_grouped.setdefault(shelf, []).append(entry)
    lines = [
        "Time Library 阅读区（只读项目页目录）",
        "只推目录不推正文；用 library_id 借阅，source_ref 留在结构化 startupCatalog.catalog[]。",
        f"书架计数：{_shelf_count_summary(projection)}",
    ]
    whiteboard = projection.get("whiteboard") if isinstance(projection.get("whiteboard"), dict) else {}
    whiteboard_lines = [str(item).strip() for item in (whiteboard.get("lines") or []) if str(item).strip()]
    lines.extend(whiteboard_lines)
    all_raw_ids = [
        str(entry.get("library_id") or "").strip()
        for entry in startup_grouped.get("raw", [])
        if str(entry.get("library_id") or "").strip()
    ]
    for page in projection.get("project_pages") or []:
        if not isinstance(page, dict):
            continue
        project_id = str(page.get("project_id") or "").strip()
        lanes = int(page.get("lane_count") or 0)
        handles = page.get("library_id_pull_handles") if isinstance(page.get("library_id_pull_handles"), list) else []
        header = f"项目页 {project_id} lanes={lanes} ids={len(handles)}" if project_id else f"项目页 lanes={lanes} ids={len(handles)}"
        lines.append(header)
        raw_ids = list(all_raw_ids)
        for library_id in handles:
            if str(library_id).startswith("ZX-RAW-") and library_id not in raw_ids:
                raw_ids.append(library_id)
        if raw_ids:
            lines.append("raw把手：" + "; ".join(f"[{library_id}]" for library_id in raw_ids))
        page_history = page.get("history") if isinstance(page.get("history"), dict) else {}
        for history_line in page_history.get("lines") or []:
            clean_line = str(history_line).strip()
            if clean_line:
                lines.append(clean_line)
        page_whiteboard = page.get("whiteboard") if isinstance(page.get("whiteboard"), dict) else {}
        for whiteboard_line in page_whiteboard.get("lines") or []:
            clean_line = str(whiteboard_line).strip()
            if clean_line:
                lines.append(clean_line)
        for lane in page.get("visible_lane_summaries") or []:
            if not isinstance(lane, dict):
                continue
            agent = str(lane.get("agent") or "agent").strip()
            shelf_counts = lane.get("shelf_counts") if isinstance(lane.get("shelf_counts"), dict) else {}
            shelf_summary = ", ".join(f"{key}:{value}" for key, value in shelf_counts.items())
            ids = [str(item) for item in lane.get("library_ids") or [] if str(item)]
            entries = "; ".join(
                f"[{library_id}] {titles_by_id.get(library_id, '')}".rstrip()
                for library_id in ids
            )
            hidden = max(0, int(lane.get("item_count") or 0) - len(ids))
            hidden_text = f"; 另{hidden}条用编号取" if hidden else ""
            prefix = f"- {agent} ({shelf_summary})" if shelf_summary else f"- {agent}"
            lines.append(f"{prefix}: {entries}{hidden_text}".strip())
    lines.append("无关话题不要主动提及；聊到相关内容时再用编号拉取真卡。")
    block, _omitted = _bounded_instruction_lines(lines)
    return block


def _catalog_contains_body_markers(text):
    lowered = str(text or "").lower()
    markers = (
        "verbatim_excerpt:",
        "raw_excerpt:",
        "action_strategy:",
        "recommended_procedure:",
        "observed_facts:",
        "acceptance_checks:",
        "verification_steps:",
        "detail:",
        "详情：",
        "策略：",
    )
    return any(marker in lowered for marker in markers)


def _build_reading_area_raw_index(
    *,
    records_db_path="",
    reading_area_registry_path="",
    project_ids=None,
    series_ids=None,
):
    try:
        from src.reading_area_raw_index import build_raw_session_index_records
    except Exception:
        from reading_area_raw_index import build_raw_session_index_records
    return build_raw_session_index_records(
        records_db_path=records_db_path or None,
        reading_area_registry_path=reading_area_registry_path or None,
        project_ids=project_ids,
        series_ids=series_ids,
    )


def build_catalog_inject_from_candidates(
    target_tokens=DEFAULT_CATALOG_TARGET_TOKENS,
    xingce_root="",
    reading_area_registry_path="",
    records_db_path="",
    include_raw_index=True,
):
    records = load_catalog_candidate_records(xingce_root=xingce_root)
    raw_index_report = {}
    if include_raw_index:
        raw_index_report = _build_reading_area_raw_index(
            records_db_path=records_db_path,
            reading_area_registry_path=reading_area_registry_path,
        )
        if raw_index_report.get("ok"):
            records = records + [
                record for record in raw_index_report.get("records", [])
                if isinstance(record, dict)
            ]
    if not records:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "should_inject": False,
            "error": "no_xingce_candidate_records",
            "catalog_entry_count": 0,
            "no_window_binding_required": True,
        }
    try:
        from src.context_delivery_compaction import (
            build_catalog_compaction,
            build_catalog_inject_prompt,
            build_library_catalog_push,
        )
    except Exception:
        from context_delivery_compaction import (
            build_catalog_compaction,
            build_catalog_inject_prompt,
            build_library_catalog_push,
        )

    reading_area_projection = build_reading_area_catalog_from_candidates(
        target_tokens=target_tokens,
        xingce_root=xingce_root,
        reading_area_registry_path=reading_area_registry_path,
        records_db_path=records_db_path,
        include_raw_index=include_raw_index,
    )
    visible_library_ids = {
        str(library_id or "").strip()
        for page in (reading_area_projection.get("project_pages") or [])
        if isinstance(page, dict)
        for library_id in (page.get("visible_library_id_pull_handles") or [])
        if str(library_id or "").strip()
    }
    visible_library_ids.update(
        str(library_id or "").strip()
        for page in (reading_area_projection.get("project_pages") or [])
        if isinstance(page, dict)
        for library_id in (page.get("library_id_pull_handles") or [])
        if str(library_id or "").strip().startswith("ZX-RAW-")
    )
    startup_catalog = build_library_catalog_push(
        records,
        target_tokens=target_tokens,
        preserve_library_ids=visible_library_ids,
        trim_to_target_tokens=False,
    )
    prompt_catalog = build_library_catalog_push(
        records,
        target_tokens=target_tokens,
        preserve_library_ids=visible_library_ids,
    )
    if not startup_catalog.get("ok"):
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "should_inject": False,
            "error": startup_catalog.get("error") or "catalog_build_failed",
            "catalog_entry_count": 0,
            "no_window_binding_required": True,
        }
    reading_area_projection = build_reading_area_catalog_from_candidates(
        target_tokens=target_tokens,
        xingce_root=xingce_root,
        reading_area_registry_path=reading_area_registry_path,
        records_db_path=records_db_path,
        include_raw_index=include_raw_index,
        startup_catalog=startup_catalog,
    )
    compaction = build_catalog_compaction(prompt_catalog, target_tokens=target_tokens)
    inject = build_catalog_inject_prompt(prompt_catalog)
    reading_area_block = _reading_area_prompt_block(reading_area_projection)
    instruction_mode = "reading_area_lanes_only" if reading_area_block else "flat_catalog_fallback_no_project_page"
    system_prompt = reading_area_block or inject.get("system_prompt", "")
    flat_catalog_prompt_omitted = bool(reading_area_block)
    reading_area_block_token_count = _estimate_tokens(reading_area_block)
    system_prompt_token_count = _estimate_tokens(system_prompt)
    return {
        "ok": bool(inject.get("ok")),
        "read_only": True,
        "write_performed": False,
        "should_inject": bool(inject.get("should_inject")),
        "no_window_binding_required": True,
        "source": "file_backed_library_candidates_plus_declared_raw_index",
        "catalog_contract": startup_catalog.get("contract", ""),
        "compaction_contract": compaction.get("contract", ""),
        "projection_layer": startup_catalog.get("projection_layer", ""),
        "index_projection_contract": startup_catalog.get("index_projection_contract", ""),
        "catalog_entry_count": startup_catalog.get("entry_count", 0),
        "catalog_token_count": prompt_catalog.get("token_count", 0),
        "inject_token_count": inject.get("token_count", 0),
        "system_prompt_token_count": system_prompt_token_count,
        "startup_instruction_mode": instruction_mode,
        "flat_catalog_prompt_omitted": flat_catalog_prompt_omitted,
        "instructions_char_count": len(system_prompt),
        "instructions_byte_count": len(system_prompt.encode("utf-8")),
        "startup_instructions_char_budget": STARTUP_INSTRUCTIONS_CHAR_BUDGET,
        "target_tokens": target_tokens,
        "contains_body_markers": _catalog_contains_body_markers(startup_catalog.get("catalog_text", "")),
        "catalog": startup_catalog.get("catalog", []),
        "catalog_text": prompt_catalog.get("catalog_text", ""),
        "catalog_text_entry_count": prompt_catalog.get("entry_count", 0),
        "catalog_visibility_accounting": {
            "structured_catalog_entry_count": startup_catalog.get("entry_count", 0),
            "prompt_catalog_entry_count": prompt_catalog.get("entry_count", 0),
            "structured_catalog_trimmed": bool(startup_catalog.get("trimmed")),
            "prompt_catalog_trimmed": bool(prompt_catalog.get("trimmed")),
            "prompt_catalog_omitted_shelves": prompt_catalog.get("omitted_shelves", []),
            "hidden_active_library_ids": sorted(
                {
                    str(entry.get("library_id") or "").strip()
                    for entry in (startup_catalog.get("catalog") or [])
                    if isinstance(entry, dict)
                }
                - {
                    str(entry.get("library_id") or "").strip()
                    for entry in (prompt_catalog.get("catalog") or [])
                    if isinstance(entry, dict)
                }
            ),
        },
        "reading_area_projection": reading_area_projection,
        "reading_area_project_page_count": reading_area_projection.get("project_page_count", 0),
        "reading_area_toc_token_count": reading_area_projection.get("toc_token_count", 0),
        "reading_area_block_token_count": reading_area_block_token_count,
        "reading_area_contains_body_markers": reading_area_projection.get("contains_body_markers", False),
        "reading_area_raw_index": reading_area_projection.get("raw_index", {}) or {
            "enabled": bool(include_raw_index),
            "contract": raw_index_report.get("contract", "") if isinstance(raw_index_report, dict) else "",
            "record_count": int(raw_index_report.get("record_count") or 0) if isinstance(raw_index_report, dict) else 0,
            "matched_session_count": int(raw_index_report.get("matched_session_count") or 0) if isinstance(raw_index_report, dict) else 0,
            "title_model_used": bool(raw_index_report.get("title_model_used")) if isinstance(raw_index_report, dict) else False,
            "scope_policy": raw_index_report.get("scope_policy", "") if isinstance(raw_index_report, dict) else "",
            "error": raw_index_report.get("error", "") if isinstance(raw_index_report, dict) else "",
        },
        "system_prompt": system_prompt,
    }


def ensure_reading_area_borrowing_card_for_current_window(
    source_system,
    consumer="",
    window_registry_path="",
    reading_area_registry_path="",
):
    try:
        from src.reading_area_registry import ensure_borrowing_card_for_current_window
    except Exception:
        from reading_area_registry import ensure_borrowing_card_for_current_window
    return ensure_borrowing_card_for_current_window(
        source_system=str(source_system or ""),
        consumer=str(consumer or ""),
        window_registry_path=window_registry_path or None,
        reading_area_registry_path=reading_area_registry_path or None,
    )


def declare_reading_area_membership_for_current_window(
    source_system,
    consumer="",
    reading_area="",
    projects=None,
    series=None,
    window_registry_path="",
    reading_area_registry_path="",
):
    card_result = ensure_reading_area_borrowing_card_for_current_window(
        source_system,
        consumer=consumer,
        window_registry_path=window_registry_path,
        reading_area_registry_path=reading_area_registry_path,
    )
    if not card_result.get("ok"):
        return card_result
    try:
        from src.reading_area_registry import declare_membership
    except Exception:
        from reading_area_registry import declare_membership
    membership = declare_membership(
        card_id=card_result.get("card_id", ""),
        reading_area=reading_area,
        projects=projects,
        series=series,
        path=reading_area_registry_path or None,
    )
    return {
        **membership,
        "borrowing_card": card_result.get("card", {}),
        "window_binding_applied": card_result.get("window_binding_applied", False),
        "window_binding_key": card_result.get("window_binding_key", ""),
        "technical_project_id_used_as_declared_identity": False,
    }


def _byte_offsets_from_refs(refs):
    if not isinstance(refs, dict):
        return {}
    byte_offsets = refs.get("byte_offsets") if isinstance(refs.get("byte_offsets"), dict) else {}
    computed = byte_offsets.get("_computed_verbatim") if isinstance(byte_offsets.get("_computed_verbatim"), dict) else {}
    if computed:
        return computed
    if "start" in byte_offsets:
        return byte_offsets
    resolution = refs.get("resolution_report") if isinstance(refs.get("resolution_report"), dict) else {}
    computed = resolution.get("computed_byte_offsets") if isinstance(resolution.get("computed_byte_offsets"), dict) else {}
    return computed if computed else {}


def _read_raw_source_excerpt(refs, *, extra_allowed_roots=None):
    if not isinstance(refs, dict):
        return {"status": "missing_source_refs", "text": ""}
    source_path = (
        refs.get("resolved_source_path")
        or refs.get("source_path")
        or refs.get("path")
        or ""
    )
    offsets = _byte_offsets_from_refs(refs)
    if not source_path:
        return {"status": "missing_source_path", "text": ""}
    try:
        from src.reading_area_raw_index import is_allowed_raw_source_path
    except Exception:
        from reading_area_raw_index import is_allowed_raw_source_path
    if not is_allowed_raw_source_path(source_path, extra_allowed_roots=extra_allowed_roots):
        return {"status": "source_path_not_allowed", "source_path": source_path, "text": ""}
    if "start" not in offsets:
        return {"status": "missing_byte_offsets", "source_path": source_path, "text": ""}
    try:
        start = int(offsets.get("start"))
        end = int(offsets.get("end")) if offsets.get("end") is not None else start
    except Exception:
        return {"status": "invalid_byte_offsets", "source_path": source_path, "byte_offsets": offsets, "text": ""}
    if end < start:
        return {"status": "invalid_byte_offsets", "source_path": source_path, "byte_offsets": offsets, "text": ""}
    try:
        with open(source_path, "rb") as f:
            f.seek(start)
            raw = f.read(end - start)
        return {
            "status": "ok",
            "source_path": source_path,
            "byte_offsets": {"start": start, "end": end},
            "text": raw.decode("utf-8", errors="ignore"),
        }
    except Exception as exc:
        return {
            "status": f"read_error:{type(exc).__name__}",
            "source_path": source_path,
            "byte_offsets": {"start": start, "end": end},
            "text": "",
        }


def _source_allowed_roots_for_request(*paths):
    roots = []
    for value in paths:
        text = str(value or "").strip()
        if not text:
            continue
        path = os.path.expanduser(text)
        if os.path.isdir(path):
            roots.append(path)
        else:
            parent = os.path.dirname(path)
            if parent:
                roots.append(parent)
    return roots


def _collect_catalog_card_source_refs(card, raw_source_excerpt_ref=None):
    refs = []

    def add(value):
        for item in _listish(value):
            if item in (None, "", [], {}):
                continue
            refs.append(item)

    if isinstance(card, dict):
        add(card.get("source_refs"))
        add(card.get("evidence_refs"))
    if isinstance(raw_source_excerpt_ref, dict) and raw_source_excerpt_ref.get("source_path"):
        add(raw_source_excerpt_ref)

    seen = set()
    deduped = []
    for ref in refs:
        key = _source_ref_text(ref)
        if key not in seen:
            seen.add(key)
            deduped.append(ref)
    return deduped


def _catalog_card_source_author(card, raw_source_excerpt_ref=None):
    refs = card.get("source_refs") if isinstance(card, dict) and isinstance(card.get("source_refs"), dict) else {}
    excerpt_ref = raw_source_excerpt_ref if isinstance(raw_source_excerpt_ref, dict) else {}
    for value in (
        card.get("source_author") if isinstance(card, dict) else "",
        card.get("source_role") if isinstance(card, dict) else "",
        refs.get("source_author"),
        refs.get("source_role"),
        refs.get("role"),
        excerpt_ref.get("source_author"),
        excerpt_ref.get("source_role"),
        excerpt_ref.get("role"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _catalog_card_source_mode(card):
    if not isinstance(card, dict):
        return ""
    refs = card.get("source_refs") if isinstance(card.get("source_refs"), dict) else {}
    for value in (
        card.get("source_mode"),
        card.get("evidence_source_mode"),
        refs.get("source_mode"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    if card.get("shelf") == "raw":
        return "raw_session_shallow_index"
    return ""


def _catalog_card_byte_offsets(card, raw_source_excerpt_ref=None):
    if isinstance(card, dict):
        offsets = card.get("byte_offsets")
        if isinstance(offsets, dict) and ("start" in offsets or "end" in offsets):
            return dict(offsets)
        refs = card.get("source_refs") if isinstance(card.get("source_refs"), dict) else {}
        offsets = refs.get("byte_offsets") if isinstance(refs.get("byte_offsets"), dict) else {}
        if "start" in offsets or "end" in offsets:
            return dict(offsets)
    excerpt_ref = raw_source_excerpt_ref if isinstance(raw_source_excerpt_ref, dict) else {}
    offsets = excerpt_ref.get("byte_offsets") if isinstance(excerpt_ref.get("byte_offsets"), dict) else {}
    return dict(offsets) if ("start" in offsets or "end" in offsets) else {}


def _catalog_card_source_ref(card, raw_source_excerpt_ref=None):
    if isinstance(card, dict):
        explicit = str(card.get("source_ref") or "").strip()
        if explicit:
            return explicit
        refs = card.get("source_refs") if isinstance(card.get("source_refs"), dict) else {}
        source_path = str(refs.get("source_path") or refs.get("resolved_source_path") or "").strip()
        offsets = _catalog_card_byte_offsets(card, raw_source_excerpt_ref=raw_source_excerpt_ref)
        if source_path and offsets.get("start") is not None and offsets.get("end") is not None:
            return f"{source_path}:{offsets.get('start')}-{offsets.get('end')}"
        if source_path:
            return source_path
    excerpt_ref = raw_source_excerpt_ref if isinstance(raw_source_excerpt_ref, dict) else {}
    source_path = str(excerpt_ref.get("source_path") or "").strip()
    offsets = _catalog_card_byte_offsets({}, raw_source_excerpt_ref=excerpt_ref)
    if source_path and offsets.get("start") is not None and offsets.get("end") is not None:
        return f"{source_path}:{offsets.get('start')}-{offsets.get('end')}"
    return source_path


def _catalog_card_verbatim_sha256(card, *, raw_source_excerpt=""):
    if isinstance(card, dict):
        value = str(card.get("verbatim_sha256") or "").strip()
        if value:
            return value
        excerpt = str(card.get("verbatim_excerpt") or "")
        if excerpt:
            return hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
    if raw_source_excerpt:
        return hashlib.sha256(str(raw_source_excerpt).encode("utf-8")).hexdigest()
    return ""


def _attach_catalog_card_projection_meta(result):
    card = result.get("card") if isinstance(result.get("card"), dict) else {}
    excerpt_ref = result.get("raw_source_excerpt_ref") if isinstance(result.get("raw_source_excerpt_ref"), dict) else {}
    projected_sha = _catalog_card_verbatim_sha256(card, raw_source_excerpt=result.get("raw_source_excerpt", ""))
    if projected_sha and not result.get("verbatim_sha256"):
        result["verbatim_sha256"] = projected_sha
    if projected_sha and isinstance(card, dict) and not card.get("verbatim_sha256"):
        card["verbatim_sha256"] = projected_sha
    byte_offsets = _catalog_card_byte_offsets(card, raw_source_excerpt_ref=excerpt_ref)
    source_ref = _catalog_card_source_ref(card, raw_source_excerpt_ref=excerpt_ref)
    if byte_offsets and not result.get("byte_offsets"):
        result["byte_offsets"] = byte_offsets
    if source_ref and not result.get("source_ref"):
        result["source_ref"] = source_ref
    result["source_author"] = _catalog_card_source_author(card, raw_source_excerpt_ref=excerpt_ref)
    result["source_mode"] = _catalog_card_source_mode(card)
    result["catalog_card_projection_meta"] = {
        "source_author_projected": bool(result["source_author"]),
        "source_mode_projected": bool(result["source_mode"]),
        "verbatim_sha256_projected": bool(projected_sha),
        "projection_only": True,
        "storage_write_performed": False,
    }
    return result


def _maybe_record_catalog_card_borrowing(
    result,
    *,
    record_borrowing=False,
    borrowing_card_id="",
    request_id="",
    consumer="",
    reading_area_id="",
    project_id="",
    series_id="",
    reading_area_registry_path="",
):
    if not _truthy(record_borrowing):
        return result

    result["borrowing_record_requested"] = True
    result["borrowing_record_written"] = False
    result["borrowing_registry_write_performed"] = False
    result["reading_area_content_write_performed"] = False
    if not result.get("ok"):
        result["borrowing_record_status"] = "skipped_card_pull_failed"
        return result

    card_id = str(borrowing_card_id or "").strip()
    if not card_id:
        result["borrowing_record_status"] = "skipped_missing_borrowing_card_id"
        return result

    try:
        try:
            from src.reading_area_registry import record_borrowing as _record_borrowing
        except Exception:
            from reading_area_registry import record_borrowing as _record_borrowing

        card = result.get("card") if isinstance(result.get("card"), dict) else {}
        source_refs = _collect_catalog_card_source_refs(
            card,
            raw_source_excerpt_ref=result.get("raw_source_excerpt_ref"),
        )
        receipt = _record_borrowing(
            card_id=card_id,
            library_ids=[result.get("library_id", "")],
            source_refs=source_refs,
            request_id=str(request_id or ""),
            reading_area_id=str(reading_area_id or ""),
            project_id=str(project_id or ""),
            series_id=str(series_id or ""),
            consumer=str(consumer or ""),
            path=reading_area_registry_path or None,
        )
    except Exception as exc:
        result["borrowing_record_status"] = "error"
        result["borrowing_record_error"] = f"{type(exc).__name__}:{exc}"
        return result

    result["borrowing_record_receipt"] = receipt
    if receipt.get("ok"):
        result["borrowing_record_written"] = True
        result["borrowing_registry_write_performed"] = True
        result["borrowing_record_status"] = "recorded"
    else:
        result["borrowing_record_status"] = str(receipt.get("error") or "not_recorded")
    return result


def fetch_catalog_card_by_library_id(
    library_id,
    xingce_root="",
    reading_area_registry_path="",
    records_db_path="",
    include_raw_index=False,
    project_ids=None,
    series_ids=None,
    record_borrowing=False,
    borrowing_card_id="",
    request_id="",
    consumer="",
    reading_area_id="",
    project_id="",
    series_id="",
):
    target = str(library_id or "").strip()
    if not target:
        return {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "error": "library_id_required",
            "no_window_binding_required": True,
        }
    try:
        from src.zhixing_library import fetch_library_card_by_id_from_candidates
    except Exception:
        from zhixing_library import fetch_library_card_by_id_from_candidates

    if target.upper().startswith(("WB-", "PH-")):
        try:
            from src.reading_area_registry import load_registry, list_whiteboard_records, list_project_history_records
        except Exception:
            from reading_area_registry import load_registry, list_whiteboard_records, list_project_history_records
        registry = load_registry(reading_area_registry_path or None)
        is_project_history = target.upper().startswith("PH-")
        record_key = "record_id"
        record_store = "project_history_records" if is_project_history else "whiteboard_records"
        exact_records = [
            record for record in (registry.get(record_store) or [])
            if isinstance(record, dict) and str(record.get(record_key) or "").upper() == target.upper()
        ]
        if not exact_records:
            if is_project_history:
                listed = list_project_history_records(
                    project_ids=project_ids,
                    series_ids=series_ids,
                    statuses=[],
                    limit=200,
                    path=reading_area_registry_path or None,
                )
                record_list = listed.get("records", [])
            else:
                listed = list_whiteboard_records(
                    reading_area_ids=[],
                    project_ids=project_ids,
                    series_ids=series_ids,
                    statuses=[],
                    limit=200,
                    path=reading_area_registry_path or None,
                )
                record_list = listed.get("records", [])
            exact_records = [
                record
                for record in record_list
                if isinstance(record, dict) and str(record.get(record_key) or "").upper() == target.upper()
            ]
        for record in exact_records:
            if not isinstance(record, dict):
                continue
            source_ref = record.get("source_ref") if isinstance(record.get("source_ref"), dict) else {}
            raw_excerpt = ""
            raw_status = "not_inlined"
            if source_ref.get("source_path") and isinstance(source_ref.get("byte_offsets"), dict):
                source_read = _read_raw_source_excerpt(source_ref, extra_allowed_roots=_source_allowed_roots_for_request(
                    xingce_root, records_db_path, reading_area_registry_path, source_ref.get("source_path", "")
                ))
                raw_excerpt = source_read.get("text", "")
                raw_status = source_read.get("status", "not_inlined")
            fallback_excerpt = str(record.get("verbatim_excerpt") or record.get("summary") or "")
            excerpt = raw_excerpt or fallback_excerpt
            shelf = "project_history" if is_project_history else "whiteboard"
            source_mode = "evidence_bound_project_history_digest" if is_project_history else "whiteboard_registry_projection"
            card = {
                "library_id": str(record.get("record_id") or ""),
                "shelf": shelf,
                "type": "project_history_record" if is_project_history else "whiteboard_record",
                "title": str(record.get("title") or record.get("summary") or record.get("task_name") or record.get("record_id") or ""),
                "summary": str(record.get("summary") or ""),
                "source_refs": source_ref,
                "verbatim_excerpt": excerpt,
                "source_ref_status": "available" if source_ref else "not_inlined",
                "raw_available": bool(source_ref),
                "source_author": str(record.get("source_author") or source_ref.get("source_author") or source_ref.get("source_role") or "agent"),
                "source_mode": source_mode,
                "whiteboard_record": record if not is_project_history else {},
                "project_history_record": record if is_project_history else {},
            }
            result = {
                "ok": True,
                "read_only": True,
                "write_performed": False,
                "library_id": target,
                "no_window_binding_required": True,
                "shelf": shelf,
                "card": card,
                "source_refs": source_ref,
                "verbatim_excerpt": excerpt,
                "verbatim_sha256": str(record.get("verbatim_sha256") or ""),
                "verbatim_excerpt_status": "ok" if excerpt else "not_inlined",
                "source_ref_status": "available" if source_ref else "not_inlined",
                "raw_available": bool(source_ref),
                "raw_source_excerpt_status": raw_status,
                "raw_source_excerpt": raw_excerpt,
                "raw_source_excerpt_ref": source_ref,
            }
            return _maybe_record_catalog_card_borrowing(
                _attach_catalog_card_projection_meta(result),
                record_borrowing=record_borrowing,
                borrowing_card_id=borrowing_card_id,
                request_id=request_id,
                consumer=consumer,
                reading_area_id=reading_area_id,
                project_id=project_id,
                series_id=series_id,
                reading_area_registry_path=reading_area_registry_path,
            )

    include_inactive = _truthy(os.environ.get("MEMCORE_CATALOG_CARD_INCLUDE_INACTIVE", ""))
    card = fetch_library_card_by_id_from_candidates(target, xingce_root=xingce_root, include_inactive=include_inactive)
    allowed_roots = _source_allowed_roots_for_request(xingce_root, records_db_path, reading_area_registry_path)
    should_try_raw_index = include_raw_index or target.upper().startswith("ZX-RAW-")
    if not card and should_try_raw_index:
        try:
            from src.reading_area_raw_index import (
                fetch_raw_session_index_record_by_library_id,
                read_raw_index_source_excerpt,
            )
            from src.zhixing_library import attach_library_card
        except Exception:
            from reading_area_raw_index import (
                fetch_raw_session_index_record_by_library_id,
                read_raw_index_source_excerpt,
            )
            from zhixing_library import attach_library_card
        raw_index = _build_reading_area_raw_index(
            records_db_path=records_db_path or None,
            reading_area_registry_path=reading_area_registry_path or None,
            project_ids=project_ids,
            series_ids=series_ids,
        )
        raw_record = fetch_raw_session_index_record_by_library_id(target, raw_index.get("records", []))
        if raw_record:
            raw_excerpt = read_raw_index_source_excerpt(raw_record, extra_allowed_roots=allowed_roots)
            raw_excerpt_ref = {
                "source_path": raw_excerpt.get("source_path", ""),
                "byte_offsets": raw_excerpt.get("byte_offsets", {}),
            }
            raw_verbatim = raw_excerpt.get("text", "") if raw_excerpt.get("status") == "ok" else ""
            card_record = dict(raw_record)
            if raw_verbatim:
                card_record["verbatim_excerpt"] = raw_verbatim
            attached = attach_library_card(
                card_record,
                raw_status="raw" if raw_verbatim else "",
                raw_excerpt=raw_verbatim,
            )
            raw_card = attached.get("library_card") if isinstance(attached.get("library_card"), dict) else {}
            raw_card = dict(raw_card)
            if raw_verbatim:
                raw_card["verbatim_excerpt"] = raw_verbatim
                raw_card["source_ref_status"] = "available"
                raw_card["raw_available"] = True
            result = {
                "ok": True,
                "read_only": True,
                "write_performed": False,
                "library_id": target,
                "no_window_binding_required": True,
                "shelf": raw_card.get("shelf", "raw"),
                "card": raw_card,
                "source_refs": raw_card.get("source_refs", {}),
                "verbatim_excerpt": raw_verbatim or raw_card.get("verbatim_excerpt", ""),
                "verbatim_excerpt_status": "ok" if raw_verbatim else "not_inlined",
                "source_ref_status": raw_card.get("source_ref_status", ""),
                "raw_available": bool(raw_card.get("raw_available", False)),
                "raw_source_excerpt_status": raw_excerpt.get("status", ""),
                "raw_source_excerpt": raw_excerpt.get("text", ""),
                "raw_source_excerpt_ref": raw_excerpt_ref,
                "raw_index": {
                    "enabled": True,
                    "contract": raw_index.get("contract", ""),
                    "record_count": raw_index.get("record_count", 0),
                    "scope_policy": raw_index.get("scope_policy", ""),
                    "title_model_used": raw_index.get("title_model_used", False),
                },
            }
            result = _attach_catalog_card_projection_meta(result)
            return _maybe_record_catalog_card_borrowing(
                result,
                record_borrowing=record_borrowing,
                borrowing_card_id=borrowing_card_id,
                request_id=request_id,
                consumer=consumer,
                reading_area_id=reading_area_id,
                project_id=project_id,
                series_id=series_id,
                reading_area_registry_path=reading_area_registry_path,
            )
    if not card:
        result = {
            "ok": False,
            "read_only": True,
            "write_performed": False,
            "error": "library_card_not_found",
            "library_id": target,
            "no_window_binding_required": True,
        }
        return _maybe_record_catalog_card_borrowing(
            result,
            record_borrowing=record_borrowing,
            borrowing_card_id=borrowing_card_id,
            request_id=request_id,
            consumer=consumer,
            reading_area_id=reading_area_id,
            project_id=project_id,
            series_id=series_id,
            reading_area_registry_path=reading_area_registry_path,
        )
    raw_excerpt = _read_raw_source_excerpt(card.get("source_refs", {}), extra_allowed_roots=allowed_roots)
    raw_excerpt_ref = {
        "source_path": raw_excerpt.get("source_path", ""),
        "byte_offsets": raw_excerpt.get("byte_offsets", {}),
    }
    result = {
        "ok": True,
        "read_only": True,
        "write_performed": False,
        "library_id": target,
        "no_window_binding_required": True,
        "shelf": card.get("shelf", card.get("library_shelf", "")),
        "card": card,
        "source_refs": card.get("source_refs", {}),
        "verbatim_excerpt": card.get("verbatim_excerpt", ""),
        "verbatim_sha256": card.get("verbatim_sha256", ""),
        "verbatim_excerpt_status": "ok" if card.get("verbatim_excerpt", "") else "not_inlined",
        "source_ref_status": card.get("source_ref_status", ""),
        "raw_available": bool(card.get("raw_available", False)),
        "raw_source_excerpt_status": raw_excerpt.get("status", ""),
        "raw_source_excerpt": raw_excerpt.get("text", ""),
        "raw_source_excerpt_ref": raw_excerpt_ref,
    }
    result = _attach_catalog_card_projection_meta(result)
    return _maybe_record_catalog_card_borrowing(
        result,
        record_borrowing=record_borrowing,
        borrowing_card_id=borrowing_card_id,
        request_id=request_id,
        consumer=consumer,
        reading_area_id=reading_area_id,
        project_id=project_id,
        series_id=series_id,
        reading_area_registry_path=reading_area_registry_path,
    )

# ─── API Handler ─────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/health":
            self.send_json({"status": "ok", "service": "inject-context-endpoint", "port": PORT})
        elif parsed.path == "/ready":
            # readiness probe — check p3 is reachable
            try:
                from src.p3_recall import get_memories
                count = len(get_memories())
                self.send_json({"ready": True, "memory_count": count})
            except Exception as e:
                self.send_json({"ready": False, "error": str(e)}, 500)
        elif parsed.path in ("/catalog", "/catalog-inject"):
            target_tokens = _try_int(_first_query_value(query, "target_tokens", DEFAULT_CATALOG_TARGET_TOKENS), DEFAULT_CATALOG_TARGET_TOKENS)
            xingce_root = _first_query_value(query, "xingce_root", "")
            self.send_json(build_catalog_inject_from_candidates(
                target_tokens=target_tokens,
                xingce_root=xingce_root,
                reading_area_registry_path=_first_query_value(query, "reading_area_registry_path", ""),
                records_db_path=_first_query_value(query, "records_db_path", ""),
                include_raw_index=_first_query_value(query, "include_raw_index", "true").lower() not in ("0", "false", "no"),
            ))
        elif parsed.path == "/catalog-card":
            library_id = _first_query_value(query, "library_id", "")
            xingce_root = _first_query_value(query, "xingce_root", "")
            project = _first_query_value(query, "project", "")
            series = _first_query_value(query, "series", "")
            result = fetch_catalog_card_by_library_id(
                library_id,
                xingce_root=xingce_root,
                reading_area_registry_path=_first_query_value(query, "reading_area_registry_path", ""),
                records_db_path=_first_query_value(query, "records_db_path", ""),
                include_raw_index=_first_query_value(query, "include_raw_index", "").lower() in ("1", "true", "yes"),
                project_ids=[project] if project else None,
                series_ids=[series] if series else None,
                record_borrowing=_first_query_value(query, "record_borrowing", ""),
                borrowing_card_id=_first_query_value(query, "borrowing_card_id", "") or _first_query_value(query, "card_id", ""),
                request_id=_first_query_value(query, "request_id", ""),
                consumer=_first_query_value(query, "consumer", ""),
                reading_area_id=_first_query_value(query, "reading_area_id", ""),
                project_id=_first_query_value(query, "project_id", ""),
                series_id=_first_query_value(query, "series_id", ""),
            )
            self.send_json(result, 200 if result.get("ok") else 404)
        elif parsed.path == "/reading-area/borrowing-card":
            result = ensure_reading_area_borrowing_card_for_current_window(
                _first_query_value(query, "source_system", "codex"),
                consumer=_first_query_value(query, "consumer", ""),
                window_registry_path=_first_query_value(query, "window_registry_path", ""),
                reading_area_registry_path=_first_query_value(query, "reading_area_registry_path", ""),
            )
            self.send_json(result, 200 if result.get("ok") else 404)
        elif parsed.path == "/reading-area/catalog":
            target_tokens = _try_int(_first_query_value(query, "target_tokens", DEFAULT_CATALOG_TARGET_TOKENS), DEFAULT_CATALOG_TARGET_TOKENS)
            project = _first_query_value(query, "project", "")
            series = _first_query_value(query, "series", "")
            result = build_reading_area_catalog_from_candidates(
                target_tokens=target_tokens,
                xingce_root=_first_query_value(query, "xingce_root", ""),
                reading_area_registry_path=_first_query_value(query, "reading_area_registry_path", ""),
                records_db_path=_first_query_value(query, "records_db_path", ""),
                include_raw_index=_first_query_value(query, "include_raw_index", "").lower() in ("1", "true", "yes"),
                project_ids=[project] if project else None,
                series_ids=[series] if series else None,
                reading_area_id=_first_query_value(query, "reading_area_id", ""),
            )
            self.send_json(result)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/inject":
            try:
                cl = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
                query = _get_request_query(body)
                scope_filter = _normalize_scope_filter(body.get("scope_filter", body.get("scope", "")))
                recall_body = {
                    "query": query,
                    "scope_filter": scope_filter,
                    "type_filter": body.get("type_filter", []),
                    "top_k": body.get("top_k", 3),
                    "recall_mode": body.get("recall_mode", "substring"),
                    "threshold": body.get("threshold", 0.7),
                }
                handle_recall = _load_handle_recall()
                recall_result = handle_recall(recall_body)
                ctx = build_context(recall_result, query)
                self.send_json({
                    "query": query,
                    "should_inject": ctx["should_inject"],
                    "memory_count": ctx["memory_count"],
                    "injectable_count": ctx.get("injectable_count", 0),
                    "system_prompt": ctx.get("system_prompt", ""),
                    "user_prompt": ctx.get("user_prompt", ""),
                    "recall_result": recall_result,
                })
            except Exception as e:
                self.send_json({
                    "status": "error",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }, 500)
        elif parsed.path in ("/catalog", "/catalog-inject"):
            try:
                cl = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
                target_tokens = _try_int(body.get("target_tokens"), DEFAULT_CATALOG_TARGET_TOKENS)
                xingce_root = str(body.get("xingce_root") or "")
                include_raw_index = body.get("include_raw_index")
                self.send_json(build_catalog_inject_from_candidates(
                    target_tokens=target_tokens,
                    xingce_root=xingce_root,
                    reading_area_registry_path=str(body.get("reading_area_registry_path") or ""),
                    records_db_path=str(body.get("records_db_path") or ""),
                    include_raw_index=True if include_raw_index is None else bool(include_raw_index),
                ))
            except Exception as e:
                self.send_json({"status": "error", "error": str(e), "error_type": type(e).__name__}, 500)
        elif parsed.path == "/catalog-card":
            try:
                cl = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
                result = fetch_catalog_card_by_library_id(
                    body.get("library_id", ""),
                    xingce_root=str(body.get("xingce_root") or ""),
                    reading_area_registry_path=str(body.get("reading_area_registry_path") or ""),
                    records_db_path=str(body.get("records_db_path") or ""),
                    include_raw_index=bool(body.get("include_raw_index")),
                    project_ids=body.get("project_ids") or body.get("projects") or body.get("project") or None,
                    series_ids=body.get("series_ids") or body.get("series") or None,
                    record_borrowing=body.get("record_borrowing", False),
                    borrowing_card_id=str(body.get("borrowing_card_id") or body.get("card_id") or ""),
                    request_id=str(body.get("request_id") or ""),
                    consumer=str(body.get("consumer") or ""),
                    reading_area_id=str(body.get("reading_area_id") or ""),
                    project_id=str(body.get("project_id") or ""),
                    series_id=str(body.get("series_id") or ""),
                )
                self.send_json(result, 200 if result.get("ok") else 404)
            except Exception as e:
                self.send_json({"status": "error", "error": str(e), "error_type": type(e).__name__}, 500)
        elif parsed.path == "/reading-area/membership":
            try:
                cl = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
                result = declare_reading_area_membership_for_current_window(
                    body.get("source_system", "codex"),
                    consumer=str(body.get("consumer") or ""),
                    reading_area=str(body.get("reading_area") or ""),
                    projects=body.get("projects") or body.get("project") or [],
                    series=body.get("series") or body.get("series_id") or [],
                    window_registry_path=str(body.get("window_registry_path") or ""),
                    reading_area_registry_path=str(body.get("reading_area_registry_path") or ""),
                )
                self.send_json(result, 200 if result.get("ok") else 404)
            except Exception as e:
                self.send_json({"status": "error", "error": str(e), "error_type": type(e).__name__}, 500)
        elif parsed.path == "/reading-area/catalog":
            try:
                cl = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
                result = build_reading_area_catalog_from_candidates(
                    target_tokens=_try_int(body.get("target_tokens"), DEFAULT_CATALOG_TARGET_TOKENS),
                    xingce_root=str(body.get("xingce_root") or ""),
                    reading_area_registry_path=str(body.get("reading_area_registry_path") or ""),
                    records_db_path=str(body.get("records_db_path") or ""),
                    include_raw_index=bool(body.get("include_raw_index")),
                    project_ids=body.get("project_ids") or body.get("projects") or body.get("project") or None,
                    series_ids=body.get("series_ids") or body.get("series") or None,
                    reading_area_id=str(body.get("reading_area_id") or ""),
                )
                self.send_json(result)
            except Exception as e:
                self.send_json({"status": "error", "error": str(e), "error_type": type(e).__name__}, 500)
        else:
            self.send_json({"error": "not found"}, 404)

def run(port=PORT):
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[p4] provider-proxy running on http://127.0.0.1:{port}")
    server.serve_forever()

if __name__ == "__main__":
    import sys
    p = argparse.ArgumentParser(description="Time Library P4 Inject Context Endpoint")
    p.add_argument("--port", type=int, default=PORT)
    args = p.parse_args()
    run(args.port)

# Alias for backward compatibility
run_service = run
