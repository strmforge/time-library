#!/usr/bin/env python3
"""Owner-facing read-only memory views for the product console."""

import json
import os

try:
    from src.zhiyi_archive import attach_archive_card
except Exception:
    from zhiyi_archive import attach_archive_card
try:
    from src.p6_experience_governance import _zhiyi_experience_recycle_overlay
except Exception:
    from p6_experience_governance import _zhiyi_experience_recycle_overlay

MEMCORE_ROOT = ""
_LOAD_ZHIYI_OBJECTS = None


def configure_console_memory(memcore_root, *, load_zhiyi_objects_fn):
    global MEMCORE_ROOT, _LOAD_ZHIYI_OBJECTS
    MEMCORE_ROOT = str(memcore_root)
    _LOAD_ZHIYI_OBJECTS = load_zhiyi_objects_fn


def load_zhiyi_objects(ftype=None, limit=None):
    if _LOAD_ZHIYI_OBJECTS is None:
        return []
    return _LOAD_ZHIYI_OBJECTS(ftype=ftype, limit=limit)


def _m5_raw_evidence_for_refs(refs, excerpt_chars=600):
    """Return bounded raw excerpt for owner-facing detail views."""
    refs = refs or {}
    if not isinstance(refs, dict):
        return {
            "raw_evidence_status": "invalid_source_refs",
            "raw_excerpt": "",
            "evidence_hash": None,
            "source_path": "",
            "msg_ids": [],
        }
    source_path = refs.get("source_path", "")
    msg_ids = refs.get("msg_ids", []) or []
    if not source_path:
        return {
            "raw_evidence_status": "not_raw",
            "raw_excerpt": "",
            "evidence_hash": None,
            "source_path": "",
            "msg_ids": msg_ids,
        }
    try:
        try:
            from raw_consumption_gateway import _extract_bounded_raw_excerpt
        except Exception:
            from src.raw_consumption_gateway import _extract_bounded_raw_excerpt
        raw_excerpt, raw_status, evidence_hash = _extract_bounded_raw_excerpt(source_path, msg_ids, excerpt_chars)
    except Exception as e:
        raw_excerpt, raw_status, evidence_hash = "", f"read_error:{str(e)[:80]}", None
    return {
        "raw_evidence_status": raw_status,
        "raw_excerpt": raw_excerpt,
        "raw_excerpt_chars": len(raw_excerpt or ""),
        "evidence_hash": evidence_hash,
        "source_path": source_path,
        "msg_ids": msg_ids,
    }

def _m5_safe_memories():
    """加载所有知意对象，保留已保存用户内容。"""
    objs = load_zhiyi_objects()
    for obj in objs:
        raw_refs = obj.get("_source_refs", {})
        if not raw_refs:
            raw_refs = obj.get("source_refs", {})
        if isinstance(raw_refs, str):
            try:
                raw_refs = json.loads(raw_refs)
            except Exception:
                raw_refs = {}
        obj["_source_refs"] = raw_refs if isinstance(raw_refs, dict) else {}
        obj.update(attach_archive_card(obj))
    return objs


def _m5_get_memories(params=None):
    """M5-1: 知意记忆列表（分页，只读）"""
    params = params or {}
    ftype = params.get("type")
    page = int(params.get("page", 1))
    page_size = min(int(params.get("page_size", 20)), 100)
    objs = _m5_safe_memories()
    if ftype:
        objs = [o for o in objs if o.get("_type") == ftype]
    total = len(objs)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = objs[start:end]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "items": page_items,
    }


def _m5_get_memory_detail(memory_id):
    """M5-2: 知意记忆详情（按 exp_id 查找）"""
    # memory_id in URL maps to exp_id in data (J1: memory_id 是主键，但 base JSONL 用 exp_id)
    safe_id = memory_id.replace("..", "_").replace("/", "_")
    objs = _m5_safe_memories()
    for obj in objs:
        if obj.get("exp_id") == safe_id:
            recycle_state = _zhiyi_experience_recycle_overlay().get(safe_id, {})
            # Add lifecycle info if available
            try:
                from p3_recall import _get_lifecycle_overlay
                overlay = _get_lifecycle_overlay()
                lc = overlay.get(safe_id, {})
                obj["_lifecycle"] = {
                    "status": lc.get("status", ""),
                    "lifecycle_version": lc.get("lifecycle_version", 0),
                    "conflict_decision": lc.get("conflict_decision", ""),
                    "inject_policy": lc.get("inject_policy", ""),
                }
            except Exception:
                pass
            obj["_deleted_state"] = "recycle_bin" if recycle_state else "active"
            obj["_recycle"] = recycle_state
            if "_lifecycle" not in obj:
                obj["_lifecycle"] = {}
            obj["_lifecycle"]["deleted_state"] = obj["_deleted_state"]
            obj["_lifecycle"]["suppression_marker"] = bool(recycle_state.get("suppression_marker"))
            obj["_raw_evidence"] = _m5_raw_evidence_for_refs(obj.get("_source_refs", {}))
            obj.update(attach_archive_card(obj))
            return obj
    return {"error": f"Memory {memory_id} not found", "memory_id": memory_id}


def _m5_get_memory_refs(memory_id):
    """M5-3: source_refs 回指和原文回源。"""
    obj = _m5_get_memory_detail(memory_id)
    if "error" in obj:
        return {"error": obj["error"]}
    # Return refs + bounded raw excerpt for owner-facing detail.
    refs = obj.get("_source_refs", {})
    raw_evidence = _m5_raw_evidence_for_refs(refs)
    source_path = raw_evidence.get("source_path", "")
    raw_exists = bool(source_path and os.path.exists(source_path))
    return {
        "memory_id": memory_id,
        "exp_id": obj.get("exp_id", ""),
        "catalog_id": obj.get("catalog_id", ""),
        "archive_card": obj.get("archive_card", {}),
        "_type": obj.get("_type", ""),
        "_source_refs": refs,
        "_raw_exists": raw_exists,
        "_raw_evidence": raw_evidence,
        "_payload_exposed": "payload" in obj,
        "_note": "source_refs metadata and bounded raw excerpt; saved user content is not rewritten",
    }


def _m5_get_lifecycle_overlay_stats():
    """M5-4: Lifecycle Overlay 统计"""
    try:
        from p3_recall import _get_lifecycle_overlay
        overlay = _get_lifecycle_overlay()
        from collections import Counter
        status_ctr = Counter(v.get("status", "") for v in overlay.values())
        decision_ctr = Counter(v.get("conflict_decision", "") for v in overlay.values())
        visibility_ctr = Counter(v.get("visibility", "") for v in overlay.values())
        return {
            "total_overlay_entries": len(overlay),
            "status_distribution": dict(status_ctr),
            "conflict_decision_distribution": dict(decision_ctr),
            "visibility_distribution": dict(visibility_ctr),
            "j2_unique_base_exp_ids": 291,
            "_note": "overlay keyed by exp_id, total entries from lifecycle JSONL files",
        }
    except Exception as e:
        return {"error": str(e), "lifecycle_overlay_ready": False}


def _m5_recall_preview(params):
    """M5-5: Recall Preview（dry-view，不触发真实注入）"""
    try:
        import sys as _sys
        _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
        from p3_recall import handle_recall
        query = params.get("query", "")
        scope = params.get("scope_filter", "")
        top_k = min(int(params.get("top_k", 5)), 20)
        threshold = float(params.get("threshold", 0.5))
        ftype = params.get("type")
        body = {
            "query": query,
            "scope_filter": scope,
            "top_k": top_k,
            "threshold": threshold,
        }
        if ftype:
            body["type_filter"] = [ftype]
        result = handle_recall(body)
        # Return summary only, no payload
        mems = result.get("matched_memories", [])
        safe_mems = []
        for m in mems:
            safe_m = {
                "exp_id": m.get("exp_id", ""),
                "_type": m.get("type", ""),
                "scope": m.get("scope", ""),
                "confidence": m.get("confidence", 0),
                "summary": m.get("summary", ""),
                "should_inject": m.get("should_inject", False),
                "_lifecycle": m.get("_lifecycle", {}),
                "_adjusted_score": m.get("_adjusted_score"),
            }
            safe_mems.append(safe_m)
        return {
            "_dry_view": True,
            "_injection_triggered": False,
            "query": query,
            "scope_filter": scope,
            "total_matched": result.get("total_matched", 0),
            "returned": result.get("returned", 0),
            "matched_memories": safe_mems,
        }
    except Exception as e:
        return {"error": str(e), "_dry_view": True, "_injection_triggered": False}


def _m5_injection_explain(params):
    """M5-6: 注入决策解释（只读分析）"""
    try:
        import sys as _sys
        _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
        from p3_recall import handle_recall
        query = params.get("query", "")
        scope = params.get("scope_filter", "")
        top_k = min(int(params.get("top_k", 10)), 20)
        threshold = float(params.get("threshold", 0.5))
        body = {
            "query": query,
            "scope_filter": scope,
            "top_k": top_k,
            "threshold": threshold,
        }
        result = handle_recall(body)
        mems = result.get("matched_memories", [])
        explain_items = []
        for m in mems:
            lc = m.get("_lifecycle", {})
            conf = m.get("confidence", 0)
            should_inject = m.get("should_inject", False)
            reasons = []
            if conf < threshold:
                reasons.append(f"confidence={conf:.2f} < threshold={threshold}")
            if lc.get("inject_policy") == "never":
                reasons.append("inject_policy=never overrides")
            if lc.get("status") == "superseded":
                reasons.append("lifecycle status=superseded")
            if not reasons:
                reasons.append("confidence >= threshold, no lifecycle override")
            explain_items.append({
                "exp_id": m.get("exp_id", ""),
                "confidence": conf,
                "should_inject": should_inject,
                "reasons": reasons,
                "lifecycle_status": lc.get("status", ""),
                "lifecycle_inject_policy": lc.get("inject_policy", ""),
                "adjusted_score": m.get("_adjusted_score"),
            })
        injectable = [x for x in explain_items if x["should_inject"]]
        return {
            "query": query,
            "scope_filter": scope,
            "threshold": threshold,
            "total_candidates": len(explain_items),
            "injectable_count": len(injectable),
            "decision_explained": explain_items,
            "_injection_triggered": False,
            "_note": "analysis only; real injection requires explicit trigger",
        }
    except Exception as e:
        return {"error": str(e)}
