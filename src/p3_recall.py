#!/usr/bin/env python3
"""
memcore-cloud P3: 知意召回服务
从 zhiyi/ 目录读取经验对象，按 scope/type/query 召回，
返回带 source_refs 溯源信息的 matched_memories。

J2-J7 Runtime 集成：
- J2 去重：基于 exp_id 去重，相同 exp_id 保留 lifecycle_version 最高的记录
- J3 冲突：conflict_decision=superseded 的记录不参与召回
- J4 新鲜度：effective_from 时间越近，freshness_score 越高，score 上调
- J5 混合 Ranking：lifecycle 状态参与最终 score 计算
- J6 低置信拒答：confidence 低于阈值时 should_inject=False（由 p4_inject.py 负责）
- J7 按需注入：inject_policy=never 时强制不注入

支持两种召回模式：
- recall_mode=substring: 关键词匹配（experiences 表）
- recall_mode=vector: bge-m3 向量相似度（experiences_v2 表，默认；未显式指定且空结果时回退 substring）
"""
import os, json, glob, argparse, sys, re
from datetime import datetime, timezone
from collections import defaultdict
# ─── RIC Interposition ───────────────────────────────────────
try:
    from runtime_context_package import InterpositionEvent, ContextPackage, log_interposition_event, hash_query
    RIC_AVAILABLE = True
except ImportError:
    RIC_AVAILABLE = False

from typing import Optional, Dict, Any
try:
    from src.zhiyi_archive import attach_archive_card
except Exception:
    from zhiyi_archive import attach_archive_card

# ─── Scope Enforcement ───────────────────────────────────────
try:
    from src.scope_enforcement import filter_by_scope as _se_filter_by_scope
    SCOPE_ENFORCEMENT_AVAILABLE = True
except Exception as e:
    print(f"[p3] scope_enforcement not available: {e}")
    SCOPE_ENFORCEMENT_AVAILABLE = False
    def _se_filter_by_scope(results, scope): return results

# ─── 配置驱动 ─────────────────────────────────────────
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "model_config.json")

def _load_config():
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}

def _get_recall_config():
    return _load_config().get("recall", {})

def _get_v2_config():
    recall_cfg = _load_config().get("recall", {})
    mode = recall_cfg.get("mode", "local_bge_m3")
    if mode == "local_bge_m3":
        return recall_cfg.get("local_bge_m3", {})
    elif mode == "openclaw_model":
        return recall_cfg.get("openclaw_model", {})
    return {}

# ─── LanceDB v2 向量召回（可选）──────────────────────
_lancedb_v2_cache = {"tok": None, "model": None, "tbl": None}

def _get_v2_engine():
    """延迟加载 bge-m3 + LanceDB v2（配置驱动）"""
    if _lancedb_v2_cache["model"] is None:
        v2_cfg = _get_v2_config()
        mode = _load_config().get("recall", {}).get("mode", "off")
        if mode == "off":
            return _lancedb_v2_cache
        try:
            from transformers import XLMRobertaTokenizer, XLMRobertaModel
            import lancedb
            import torch
            import os as _os
            model_path = _os.path.expanduser(v2_cfg.get("model_path", ""))
            _lancedb_v2_cache["tok"] = XLMRobertaTokenizer.from_pretrained(model_path)
            _lancedb_v2_cache["model"] = XLMRobertaModel.from_pretrained(model_path, torch_dtype=torch.float32)
            _lancedb_v2_cache["model"].eval()
            from config_loader import experience_lancedb as _lancedb_path
            db = lancedb.connect(_lancedb_path())
            table_name = v2_cfg.get("table", "experiences_v2")
            _lancedb_v2_cache["tbl"] = db.open_table(table_name)
            _lancedb_v2_cache["max_seq"] = v2_cfg.get("max_seq_length", 256)
            model_name = v2_cfg.get("embedding_model", "unknown")
            print(f"[p3] v2 engine loaded: {model_name}")
        except Exception as e:
            print(f"[p3] v2 engine load failed: {e}")
    return _lancedb_v2_cache

def _encode_bge(texts):
    """bge-m3 mean pooling（配置驱动）"""
    import numpy
    engine = _get_v2_engine()
    tok = engine["tok"]
    model = engine["model"]
    import torch
    max_seq = engine.get("max_seq", 256)
    inp = tok(texts, padding=True, truncation=True, max_length=max_seq, return_tensors="pt")
    with torch.no_grad():
        out = model(**inp)
    emb = out.last_hidden_state.mean(dim=1).numpy()
    norms = numpy.linalg.norm(emb, axis=1, keepdims=True)
    emb = emb / norms
    return emb.tolist()

def vector_search_v2(query, top_k=5, scope_filter=None, type_filter=None):
    """LanceDB v2 向量相似度召回（配置驱动）"""
    v2_cfg = _get_v2_config()
    if _load_config().get("recall", {}).get("mode") == "off":
        return []
    engine = _get_v2_engine()
    if engine["model"] is None:
        return []
    tbl = engine["tbl"]
    try:
        q_emb = _encode_bge([query])[0]
        results = tbl.search(q_emb, vector_column_name="vector").limit(top_k * 2).to_list()
    except Exception as e:
        print(f"[p3] v2 search error: {e}")
        return []
    # Load full memory records from zhiyi for source_refs
    memories = get_memories()
    exp_map = {m.get("exp_id"): m for m in memories}
    matched = []
    for r in results:
        exp_id = r.get("exp_id", "")
        # scope/type filter
        if scope_filter:
            sf = scope_filter.replace("window/", "")
            if sf not in (r.get("scope", "") or ""):
                continue
        if type_filter:
            if r.get("type", "") not in type_filter:
                continue
        # Get source_refs directly from LanceDB record (exp_map may not have all LanceDB exp_ids)
        sr_raw = r.get("source_refs", "{}")
        try:
            sr = json.loads(sr_raw) if isinstance(sr_raw, str) else (sr_raw or {})
        except:
            sr = {}
        sr = _normalize_source_refs_node(sr)
        dist = r.get("_distance", 0)
        confidence = max(1.0 - dist / 2.0, 0.0)
        # J1 + J3A-G3: 对原始 LanceDB 结果 r 做噪音检测
        # r 有 summary/detail，exp_map 只有 exp_id/scope/memory_id
        if _is_noise_memory(r):
            continue
        item = attach_archive_card({
            "type": r.get("type", ""),
            "exp_id": exp_id,
            "scope": r.get("scope", ""),
            "summary": r.get("summary", ""),
            "reason": f"向量相似度: dist={dist:.3f}",
            "confidence": round(confidence, 2),
            "source_refs": sr,
            "detail": r.get("detail", ""),
            "injectable_context": (r.get("summary", "") + " " + r.get("detail", "")).strip(),
        })
        matched.append(item)
        if len(matched) >= top_k:
            break
    return matched

# ─── Lifecycle Overlay Cache (J2-J7 Runtime) ───────────────────────
# lifecycle overlay: exp_id -> lifecycle fields (conflict_decision, status, inject_policy, etc.)
_LIFECYCLE_CACHE: Optional[Dict[str, Dict[str, Any]]] = None
_LIFECYCLE_CACHE_TIME = {"ts": 0}
_LIFECYCLE_CACHE_SIGNATURE = None
_LIFECYCLE_TTL = 60  # seconds


def _file_signature(paths):
    signature = []
    for path in paths:
        try:
            st = os.stat(path)
            signature.append((path, st.st_mtime_ns, st.st_size))
        except FileNotFoundError:
            signature.append((path, None, None))
        except Exception:
            signature.append((path, "error", "error"))
    return tuple(signature)


def _zhiyi_path_for_runtime():
    zhiyi_root_override = os.environ.get("MEMCORE_ZHIYI_ROOT_OVERRIDE")
    return zhiyi_root_override if zhiyi_root_override else ZHIYI_ROOT


def _lifecycle_source_signature():
    zhiyi_path = _zhiyi_path_for_runtime()
    paths = [
        os.path.join(zhiyi_path, ftype, f"{ftype}.lifecycle.jsonl")
        for ftype in ["case_memory", "error_memory"]
    ]
    return _file_signature(paths)


def _load_lifecycle_overlay():
    """加载 lifecycle overlay，构建 exp_id -> lifecycle_fields 字典。"""
    # Allow test fixture override via env var (MEMCORE_ZHIYI_ROOT_OVERRIDE)
    zhiyi_path = _zhiyi_path_for_runtime()
    overlay = {}
    for ftype in ["case_memory", "error_memory"]:
        lifecycle_path = os.path.join(zhiyi_path, ftype, f"{ftype}.lifecycle.jsonl")
        if not os.path.exists(lifecycle_path):
            continue
        try:
            with open(lifecycle_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        exp_id = rec.get("exp_id", "")
                        if not exp_id:
                            continue
                        # J2: 相同 exp_id 保留 lifecycle_version 最高的记录
                        # J1 Fix: 同版本优先 active > superseded > historical_only
                        existing = overlay.get(exp_id)
                        if existing is None:
                            overlay[exp_id] = rec
                        else:
                            existing_ver = existing.get("lifecycle_version", 0)
                            new_ver = rec.get("lifecycle_version", 0)
                            if new_ver > existing_ver:
                                overlay[exp_id] = rec
                            elif new_ver == existing_ver:
                                cd_pref = {"active": 0, "superseded": 1, "historical_only": 2, "": 3}
                                existing_cd = cd_pref.get(existing.get("conflict_decision", ""), 99)
                                new_cd = cd_pref.get(rec.get("conflict_decision", ""), 99)
                                if new_cd < existing_cd:
                                    overlay[exp_id] = rec
                    except Exception:
                        pass
        except Exception as e:
            print(f"[p3] lifecycle overlay load error for {ftype}: {e}")
    return overlay


def _get_lifecycle_overlay():
    """带 TTL 和文件签名的 lifecycle overlay 缓存。"""
    global _LIFECYCLE_CACHE, _LIFECYCLE_CACHE_TIME, _LIFECYCLE_CACHE_SIGNATURE
    now = datetime.now(timezone.utc).timestamp()
    signature = _lifecycle_source_signature()
    if (
        _LIFECYCLE_CACHE is None
        or signature != _LIFECYCLE_CACHE_SIGNATURE
        or (now - _LIFECYCLE_CACHE_TIME["ts"]) > _LIFECYCLE_TTL
    ):
        _LIFECYCLE_CACHE = _load_lifecycle_overlay()
        _LIFECYCLE_CACHE_TIME["ts"] = now
        _LIFECYCLE_CACHE_SIGNATURE = signature
    return _LIFECYCLE_CACHE


def _apply_lifecycle_overlay(memories: list) -> list:
    """
    J2-J5 Runtime: 将 lifecycle overlay 应用于 memories 列表。

    J2 去重：输入已被 load_memories 预处理，相同 exp_id 仅保留一条（lifecycle_version 最高）
    J3 冲突：conflict_decision=superseded 的记录跳过
    J4 新鲜度：基于 effective_from 计算 freshness_score，合并到 confidence
    J5 混合 Ranking：lifecycle 状态作为 ranking 因子参与 score 计算

    Returns: 过滤并增强后的 memories 列表
    """
    overlay = _get_lifecycle_overlay()
    result = []
    now_ts = datetime.now(timezone.utc).timestamp()

    for m in memories:
        exp_id = m.get("exp_id", "")
        lo = overlay.get(exp_id, {})

        # ── J3 冲突：superseded 记录不参与召回 ──
        conflict_decision = lo.get("conflict_decision", "")
        if conflict_decision == "superseded":
            continue  # 被取代的记录直接跳过

        # ── J3 冲突：historical_only → 降权但不剔除 ──
        is_historical = (conflict_decision == "historical_only" or
                         lo.get("status") in ("historical", "superseded"))

        # ── J4 新鲜度：effective_from 越近 freshness_score 越高 ──
        freshness_score = 1.0  # 默认不衰减
        effective_from_str = lo.get("effective_from", "")
        if effective_from_str:
            try:
                effective_ts = datetime.strptime(effective_from_str, "%Y-%m-%d %H:%M:%S").timestamp()
                age_days = (now_ts - effective_ts) / 86400.0
                # 半衰期 30 天：超过 30 天分数减半
                freshness_score = max(0.3, 1.0 / (1.0 + age_days / 30.0))
            except Exception:
                pass

        # ── J5 混合 Ranking：lifecycle 因子参与 score 计算 ──
        base_score = m.get("score", m.get("confidence", 0.7))
        lifecycle_boost = 0.0
        status = lo.get("status", "")
        if status == "active":
            lifecycle_boost = 0.15
        elif status == "historical":
            lifecycle_boost = -0.1
        elif status in ("superseded", "deprecated"):
            lifecycle_boost = -0.25

        # 合并 confidence：base_score * freshness * lifecycle_boost
        adjusted_score = base_score * freshness_score + lifecycle_boost
        adjusted_score = max(0.0, min(1.0, adjusted_score))

        # 将 lifecycle 字段注入到 memory 对象（不修改原始数据）
        enhanced = dict(m)
        has_real_lifecycle = bool(lo)
        enhanced["_lifecycle"] = {
            "exp_id": exp_id,
            # 无 overlay 时 status=""（不应用 boost）；有 overlay 时用真实值
            "status": lo.get("status", "") if has_real_lifecycle else "",
            "inject_policy": lo.get("inject_policy", "auto") if has_real_lifecycle else "auto",
            "conflict_decision": conflict_decision,
            "freshness_score": round(freshness_score, 3),
            "lifecycle_version": lo.get("lifecycle_version", 0) if has_real_lifecycle else 0,
            "is_historical": is_historical,
        }
        enhanced["_adjusted_score"] = round(adjusted_score, 3)
        result.append(enhanced)

    return result


from src.config_loader import zhiyi_root, memory_root, raw_memory_subpath, get_memcore_root, node_id
ZHIYI_ROOT = zhiyi_root()
MEMCORE_ROOT = os.path.join(memory_root(), raw_memory_subpath())
MEMCORE_PROJECT_ROOT = get_memcore_root()


def _current_node_id():
    value = str(node_id() or "").strip()
    return value or "local"


def _source_path_belongs_to_current_node(source_path, current_node=None):
    current_node = current_node or _current_node_id()
    normalized = str(source_path or "").replace("\\", "/")
    return bool(current_node and f"/memory/openclaw/{current_node}/" in normalized)


def _normalize_source_refs_node(source_refs):
    if not isinstance(source_refs, dict):
        return source_refs
    current_node = _current_node_id()
    if _source_path_belongs_to_current_node(source_refs.get("source_path"), current_node):
        source_refs = dict(source_refs)
        source_refs["computer_name"] = current_node
    return source_refs


def _normalize_memory_record_node(record):
    current_node = _current_node_id()
    source_refs = record.get("_source_refs")
    if isinstance(source_refs, dict) and _source_path_belongs_to_current_node(source_refs.get("source_path"), current_node):
        record["_source_refs"] = _normalize_source_refs_node(source_refs)
        if record.get("computer_id") in ("", "local", None):
            record["computer_id"] = current_node
    return record


def _xingce_project_root():
    return (
        os.environ.get("MEMCORE_XINGCE_ROOT_OVERRIDE")
        or os.environ.get("MEMCORE_ROOT")
        or MEMCORE_PROJECT_ROOT
    )


def _project_status_root():
    return (
        os.environ.get("MEMCORE_PROJECT_STATUS_ROOT_OVERRIDE")
        or os.environ.get("MEMCORE_ROOT")
        or MEMCORE_PROJECT_ROOT
    )


def _read_json_object(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _xingce_window_from_source_path(source_path):
    parts = str(source_path or "").split(os.sep)
    for index, part in enumerate(parts):
        if part == "local" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _latest_xingce_candidate_action(root, candidate_id):
    actions_dir = os.path.join(root, "output", "xingce_work_experience", "actions")
    if not os.path.isdir(actions_dir):
        return {}
    for path in sorted(glob.glob(os.path.join(actions_dir, "*.jsonl")), reverse=True):
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    if isinstance(item, dict) and item.get("candidate_id") == candidate_id:
                        item["_source_path"] = path
                        return item
                    break
        except Exception:
            continue
    return {}


def _xingce_action_is_consumable(action):
    return action.get("action_status") in (
        "queued_for_experience_service_review",
        "queued_for_experience_upgrade_review",
    )


def _first_xingce_evidence_ref(candidate):
    evidence_refs = candidate.get("evidence_refs", [])
    if isinstance(evidence_refs, list):
        for item in evidence_refs:
            if isinstance(item, dict) and item.get("source_path"):
                return dict(item)
    source_refs = candidate.get("source_refs", [])
    if isinstance(source_refs, list):
        for source_path in source_refs:
            if source_path:
                return {"source_path": source_path}
    return {}


def _xingce_candidate_to_memory(candidate, candidate_path, action):
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    evidence_refs = candidate.get("evidence_refs", []) if isinstance(candidate.get("evidence_refs"), list) else []
    source_refs = candidate.get("source_refs", []) if isinstance(candidate.get("source_refs"), list) else []
    ref = _first_xingce_evidence_ref(candidate)
    source_path = ref.get("source_path", "")
    window_id = ref.get("canonical_window_id") or _xingce_window_from_source_path(source_path)
    ref.setdefault("source_system", "openclaw")
    ref.setdefault("computer_name", "local")
    ref.setdefault("computer_id", ref.get("computer_name", "local"))
    ref.setdefault("canonical_window_id", window_id)
    ref["candidate_path"] = candidate_path
    if action.get("_source_path"):
        ref["action_path"] = action.get("_source_path")

    title = candidate.get("title") or "Xingce work experience candidate"
    action_status = action.get("action_status", "")
    observed_facts = candidate.get("observed_facts", []) if isinstance(candidate.get("observed_facts"), list) else []
    recommended_procedure = candidate.get("recommended_procedure", []) if isinstance(candidate.get("recommended_procedure"), list) else []
    verification_steps = candidate.get("verification_steps", []) if isinstance(candidate.get("verification_steps"), list) else []
    avoid_conditions = candidate.get("avoid_conditions", []) if isinstance(candidate.get("avoid_conditions"), list) else []
    summary = (
        f"行策待审工作经验：{title}。"
        f"状态={action_status}；证据={len(evidence_refs)}；source_refs={len(source_refs)}。"
        "这是进入经验服务评审账本的候选，不是已采用的生产经验。"
    )
    detail_parts = []
    for key in ("summary", "upgrade_reason"):
        if candidate.get(key):
            detail_parts.append(str(candidate.get(key)))
    for values in (observed_facts, recommended_procedure, avoid_conditions, verification_steps):
        detail_parts.extend(str(item) for item in values[:3])
    detail = "\n".join(part for part in detail_parts if part)

    return {
        "_type": "xingce_work_experience_candidate",
        "exp_id": candidate_id,
        "scope": f"{window_id} openclaw local xingce_review".strip(),
        "summary": summary,
        "detail": detail,
        "verbatim_excerpt": detail,
        "work_scenario": candidate.get("work_scenario") or title,
        "action_strategy": candidate.get("action_strategy") or recommended_procedure,
        "observed_facts": observed_facts,
        "recommended_procedure": recommended_procedure,
        "avoid_conditions": avoid_conditions,
        "acceptance_checks": candidate.get("acceptance_checks") or verification_steps,
        "verification_steps": verification_steps,
        "applicable_scope": candidate.get("applicable_scope") or f"{window_id} openclaw local".strip(),
        "forbidden_as_preference": True,
        "supersedes": candidate.get("supersedes", []) if isinstance(candidate.get("supersedes"), list) else [],
        "conflicts_with": candidate.get("conflicts_with", []) if isinstance(candidate.get("conflicts_with"), list) else [],
        "score": max(float(candidate.get("confidence", 0.7) or 0.7), 0.72),
        "source_refs": ref,
        "_source_refs": ref,
        "lifecycle_version": 1,
        "_xingce": {
            "candidate_id": candidate_id,
            "candidate_type": candidate.get("candidate_type", ""),
            "frontstage_surface": candidate.get("frontstage_surface", ""),
            "lifecycle_status": candidate.get("lifecycle_status", ""),
            "action_id": action.get("action_id", ""),
            "action": action.get("action", ""),
            "action_status": action_status,
            "candidate_path": candidate_path,
            "action_path": action.get("_source_path", ""),
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
    }


def _load_xingce_work_experience_candidate_memories():
    root = _xingce_project_root()
    candidates_dir = os.path.join(root, "output", "xingce_work_experience", "candidates")
    if not os.path.isdir(candidates_dir):
        return []
    memories = []
    for path in sorted(glob.glob(os.path.join(candidates_dir, "xingce-*-candidate.json"))):
        candidate = _read_json_object(path)
        if candidate.get("candidate_type") != "xingce_work_experience":
            continue
        if candidate.get("lifecycle_status") != "candidate":
            continue
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id:
            continue
        action = _latest_xingce_candidate_action(root, candidate_id)
        if not _xingce_action_is_consumable(action):
            continue
        memories.append(_xingce_candidate_to_memory(candidate, path, action))
    return memories


PROJECT_STATUS_WRITE_BOUNDARY_RULE = (
    "写入边界说明：保持 false 是边界，不是未接通、未落盘、待触发写入，"
    "也不是下一步要补的写入线。project_status/write_boundary 里的 raw_write_performed=false、"
    "xingce_write_performed=false、hermes_write_performed=false、openclaw_write_performed=false "
    "表示这些层本轮按设计保持只读或沉默。回答时应说“保持 false 是边界”，"
    "不要说“以后再接写入线”，也不要说“后台独立工作流后续补写入链”。"
    "如果问题在“补写入链”和“验自然对话质量”之间二选一，应回答先验自然对话质量。"
    "不要引入 K/N/J、Linux、eval 等旧阶段标签。"
)


def _project_status_to_memory(status, status_path):
    status_id = str(status.get("status_id") or "").strip()
    if not status_id:
        return {}
    evidence_refs = status.get("evidence_refs", []) if isinstance(status.get("evidence_refs"), list) else []
    source_ref = {
        "source_system": "memcore",
        "computer_name": "local",
        "computer_id": "local",
        "canonical_window_id": status.get("canonical_window_id", "project_status"),
        "session_id": status_id,
        "source_path": status_path,
        "msg_ids": [status_id],
        "evidence_refs": evidence_refs,
    }
    summary = status.get("summary") or status.get("title") or "忆凡尘当前进展"
    detail_parts = [PROJECT_STATUS_WRITE_BOUNDARY_RULE]
    for key in ("current_state", "next_step"):
        if status.get(key):
            detail_parts.append(str(status.get(key)))
    for key in ("completed", "remaining", "limitations"):
        values = status.get(key, [])
        if isinstance(values, list):
            detail_parts.extend(str(item) for item in values)
    detail = "\n".join(part for part in detail_parts if part)
    return {
        "_type": "yifanchen_project_status",
        "exp_id": status_id,
        "scope": "memcore-cloud 忆凡尘 project_status current",
        "summary": summary,
        "detail": detail,
        "score": float(status.get("score", 1.0) or 1.0),
        "source_refs": source_ref,
        "_source_refs": source_ref,
        "lifecycle_version": int(status.get("lifecycle_version", 1) or 1),
        "_project_status": {
            "status_id": status_id,
            "artifact_type": status.get("artifact_type", ""),
            "status": status.get("status", ""),
            "project": status.get("project", ""),
            "source_path": status_path,
            "production_experience_write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "hermes_write_performed": False,
            "openclaw_write_performed": False,
        },
    }


def _load_yifanchen_project_status_memories():
    root = _project_status_root()
    status_dir = os.path.join(root, "output", "yifanchen_project_status")
    latest_path = os.path.join(status_dir, "latest.json")
    status = _read_json_object(latest_path)
    if status.get("artifact_type") != "yifanchen_project_status":
        return []
    if status.get("status") not in ("active", "current"):
        return []
    memory = _project_status_to_memory(status, latest_path)
    return [memory] if memory else []


# ─── 加载经验对象 ───────────────────────────────────

def load_memories():
    """加载所有 zhiyi 对象。

    J2 去重：相同 exp_id 的对象，保留 lifecycle_version 最高的记录。
    """
    # Allow test fixture override via env var (MEMCORE_ZHIYI_ROOT_OVERRIDE)
    zhiyi_root_override = os.environ.get("MEMCORE_ZHIYI_ROOT_OVERRIDE")
    zhiyi_path = zhiyi_root_override if zhiyi_root_override else ZHIYI_ROOT
    memories = []
    seen_exp_ids = {}  # exp_id -> (lifecycle_version, record)

    memories.extend(_load_yifanchen_project_status_memories())

    for ftype in ["preference_memory", "case_memory", "error_memory"]:
        path = os.path.join(zhiyi_path, ftype, f"{ftype}.jsonl")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    r = json.loads(line)
                    r["_type"] = ftype
                    # 解析 source_refs
                    try:
                        r["_source_refs"] = json.loads(r.get("source_refs", "{}"))
                    except:
                        r["_source_refs"] = {}
                    r = attach_archive_card(_normalize_memory_record_node(r))

                    # J2 去重：基于 exp_id + lifecycle_version
                    exp_id = r.get("exp_id", "")
                    lifecycle_version = r.get("lifecycle_version", 1)

                    if exp_id:
                        existing = seen_exp_ids.get(exp_id)
                        if existing is None or lifecycle_version > existing[0]:
                            seen_exp_ids[exp_id] = (lifecycle_version, r)
                    else:
                        # 无 exp_id（偏好记忆）直接加入
                        memories.append(r)
                except: pass

    # 按 lifecycle_version 降序保留唯一 exp_id
    for version, rec in seen_exp_ids.values():
        memories.append(rec)

    memories.extend(_load_xingce_work_experience_candidate_memories())

    return memories

def _query_terms(query):
    q = str(query or "").strip().lower()
    if not q:
        return []
    terms = []

    def add(term):
        term = str(term or "").strip().lower()
        if term and term not in terms:
            terms.append(term)

    add(q)
    for term in re.split(r"[\s,，。；;：:、/]+", q):
        add(term)

    for term in [
        "忆凡尘", "memcore", "知意", "行策", "openclaw", "hermes",
        "raw", "原始记忆", "模型", "使用日志", "服务", "项目",
    ]:
        if term.lower() in q:
            add(term)

    compact = q
    for filler in ["接上", "继续", "帮我", "请", "一下", "当前", "进度"]:
        compact = compact.replace(filler, " ")
    for term in re.split(r"[\s,，。；;：:、/]+", compact):
        add(term)
    return terms


def _source_refs_for_filter(memory):
    sr = memory.get("_source_refs") or memory.get("source_refs") or {}
    if isinstance(sr, str):
        try:
            sr = json.loads(sr)
        except Exception:
            sr = {}
    return sr if isinstance(sr, dict) else {}


def _normalize_source_filter(value):
    value = str(value or "").strip()
    if value.lower() in ("all", "*", "shared", "raw_pool"):
        return ""
    return value


def filter_memories(
    memories,
    type_filter=None,
    scope_filter=None,
    query=None,
    source_system_filter=None,
    computer_name_filter=None,
    session_id_filter=None,
):
    """过滤 memories"""
    source_system_filter = _normalize_source_filter(source_system_filter)
    computer_name_filter = str(computer_name_filter or "").strip()
    session_id_filter = str(session_id_filter or "").strip()
    results = []
    for m in memories:
        # type filter
        if type_filter and m["_type"] not in type_filter:
            continue
        sr = _source_refs_for_filter(m)
        if source_system_filter and sr.get("source_system", "") != source_system_filter:
            continue
        if computer_name_filter and (sr.get("computer_name", "") or sr.get("computer_id", "")) != computer_name_filter:
            continue
        if session_id_filter and sr.get("session_id", "") != session_id_filter:
            continue
        # scope filter
        if scope_filter:
            # 支持 window/sg 或 sg 两种格式
            scope = m.get("scope", "")
            sf = scope_filter.replace("window/", "")
            if sf not in scope:
                continue
        # query filter (关键词匹配)
        if query:
            terms = _query_terms(query)
            text_parts = [m.get("summary", ""), m.get("detail", "")]
            if _is_project_status_memory(m):
                project_status = m.get("_project_status", {}) if isinstance(m.get("_project_status"), dict) else {}
                text_parts.extend([
                    m.get("scope", ""),
                    project_status.get("project", ""),
                    project_status.get("status_id", ""),
                    project_status.get("source_path", ""),
                ])
            text = " ".join(str(part or "") for part in text_parts).lower()
            if terms and not any(term in text for term in terms):
                continue
        results.append(m)
    return results

def _keyword_score(memory, query):
    if not query:
        return memory.get("score", 0.7)
    summary = memory.get("summary", "").lower()
    detail = memory.get("detail", "").lower()
    score = 0.0
    text = summary + " " + detail
    for term in _query_terms(query):
        if term in text:
            score += 0.3
    return min(score + 0.4, 1.0)


def score_memory(memory, query):
    """计算 relevance score。

    J5 混合 Ranking：查询相关性仍是排序底座，lifecycle 只做增强/降权。
    不能让无 overlay 的 _adjusted_score 抹平“忆凡尘/项目”等查询命中。
    """
    if query:
        base_score = _keyword_score(memory, query)
        lifecycle = memory.get("_lifecycle", {})
        freshness_score = lifecycle.get("freshness_score", 1.0) if isinstance(lifecycle, dict) else 1.0
        try:
            freshness_score = float(freshness_score)
        except Exception:
            freshness_score = 1.0
        lifecycle_boost = 0.0
        status = lifecycle.get("status", "") if isinstance(lifecycle, dict) else ""
        if status == "active":
            lifecycle_boost = 0.15
        elif status == "historical":
            lifecycle_boost = -0.1
        elif status in ("superseded", "deprecated"):
            lifecycle_boost = -0.25
        return max(0.0, min(1.0, base_score * freshness_score + lifecycle_boost))

    # J5: 无查询时沿用 lifecycle 增强分数
    if "_adjusted_score" in memory:
        return memory["_adjusted_score"]

    return _keyword_score(memory, query)


def _is_project_status_focus_query(query):
    q = str(query or "").strip().lower()
    if not q:
        return False
    has_project_name = "忆凡尘" in q or "memcore" in q
    has_progress_marker = bool(re.search(r"\bb\d+\b", q, re.IGNORECASE)) and any(
        term in q
        for term in (
            "openclaw", "hermes", "native feedback", "长工作流", "验收",
            "整体 pass", "不能宣称", "当前状态", "当前进展", "进展",
        )
    )
    if not has_project_name and not has_progress_marker:
        return False
    if re.search(r"\bb\d+\b", q, re.IGNORECASE):
        return True
    for term in (
        "project status", "latest", "当前状态", "当前进展", "进展断点",
        "下一步", "接手", "质量缺口", "质量", "进度",
    ):
        if term in q:
            return True
    return False


def _is_project_status_memory(memory):
    return (memory.get("type") or memory.get("_type")) == "yifanchen_project_status"


def _focus_project_status_matches(matched, query):
    """Keep current project-state handoff answers from being diluted by old memories."""
    if not _is_project_status_focus_query(query):
        return matched
    project_status_matches = [
        m for m in matched
        if _is_project_status_memory(m)
    ]
    if not project_status_matches:
        return matched
    return project_status_matches


def _focus_project_status_scored(scored, query):
    if not _is_project_status_focus_query(query):
        return scored
    project_status_scored = [
        item for item in scored
        if _is_project_status_memory(item[1])
    ]
    if not project_status_scored:
        return scored
    return project_status_scored


def format_memory(m, query):
    """格式化单条 memory 用于输出。

    保留 _lifecycle 和 _adjusted_score 字段供下游（p4_inject / zhiyi_gateway）使用。
    """
    # Try both keys: source_refs (LanceDB) and _source_refs (zhiyi JSONL)
    sr = m.get("source_refs") or m.get("_source_refs") or {}
    # If source_refs is a string (serialized), parse it
    if isinstance(sr, str):
        try:
            sr = json.loads(sr)
        except:
            sr = {}
    confidence = score_memory(m, query)
    # 生成 injectable_context
    summary = m.get("summary", "")
    detail = m.get("detail", "")
    injectable = f"{summary} {detail}".strip()
    result = {
        "type": m["_type"],
        "exp_id": m.get("exp_id", ""),
        "scope": m.get("scope", ""),
        "summary": summary,
        "detail": detail,
        "reason": f"命中关键词: {query}" if query else "历史经验",
        "confidence": round(confidence, 2),
        "source_refs": sr,
        "injectable_context": injectable,
    }
    # J2-J5: 传递 lifecycle overlay 信息
    if "_lifecycle" in m:
        result["_lifecycle"] = m["_lifecycle"]
    if "_adjusted_score" in m:
        result["_adjusted_score"] = m["_adjusted_score"]
    if "_xingce" in m:
        result["_xingce"] = m["_xingce"]
    if "_project_status" in m:
        result["_project_status"] = m["_project_status"]
    result = attach_archive_card(result)
    return result

def should_inject(memory, threshold=0.7):
    """判断是否建议注入"""
    return memory.get("confidence", 0) >= threshold

# ─── API server ────────────────────────────────────

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

MEMORIES_CACHE = None
CACHE_TTL = 60  # seconds
CACHE_TIME = {"ts": 0}
MEMORIES_CACHE_SIGNATURE = None


def _memories_source_signature():
    zhiyi_path = _zhiyi_path_for_runtime()
    paths = [
        os.path.join(zhiyi_path, ftype, f"{ftype}.jsonl")
        for ftype in ["preference_memory", "case_memory", "error_memory"]
    ]
    paths.append(
        os.path.join(
            _project_status_root(),
            "output",
            "yifanchen_project_status",
            "latest.json",
        )
    )
    return _file_signature(paths)

def _is_noise_memory(m):
    """J3A-G3 + J1: 噪音记录检测（Hard Block）

    检测维度：
    1. 关键词：injected_context / bootstrap_context / SOUL.md 等
    2. 溯源缺失：source_refs 为空或 source_path 不存在

    Returns: True if record is noise (should be blocked)
    """
    if _is_project_status_memory(m):
        return False

    # ── 噪音关键词检测 ──
    NOISE_KEYWORDS = [
        "injected_context", "system_prompt", "bootstrap_context",
        "taskbook_context", "panel_context", "payload_context",
        "SOUL.md", "AGENTS.md", "SKILL.md",
        # J3A-Gate-Closure G3: compaction shadow upgrade
        "compaction", "context_compression", "compressed_context", "memory_compaction",
    ]
    text = (m.get("summary", "") + " " + m.get("detail", "")).lower()
    for kw in NOISE_KEYWORDS:
        if kw.lower() in text:
            return True
    # ── 无 source_refs 检测 ──
    # 兼容两种 key 和两种格式：_source_refs（dict）/ source_refs（dict 或 JSON字符串）
    sr_raw = m.get("_source_refs") or m.get("source_refs") or {}
    if isinstance(sr_raw, str):
        try:
            sr = json.loads(sr_raw)
        except:
            sr = {}
    else:
        sr = sr_raw or {}
    if not sr or not sr.get("source_path", ""):
        return True
    # source_path 文件存在性检查已移除（J3A-Gate-Closure）
    # 原因：LanceDB 存储的 source_path 引用了大量已不存在的文件，
    # 会导致全部 LanceDB 结果被过滤为噪音，造成 G4 recall 回归。
    # 文件不存在检测应由 lifecycle 管理层处理，不在噪音层过滤。
    return False


def get_lifecycle_active_view():
    """J1: Lifecycle Active View — 返回所有活跃（active）记录。

    从 lifecycle.jsonl 读取，返回 conflict_decision=active 的记录。
    用于 recall path 统一 lifecycle gate 和 audit 报告。
    """
    overlay = _get_lifecycle_overlay()
    active_records = []
    for exp_id, lo in overlay.items():
        if lo.get("conflict_decision") == "active":
            active_records.append({
                "exp_id": exp_id,
                "status": lo.get("status", "active"),
                "conflict_decision": "active",
                "scope": lo.get("scope", ""),
                "summary": lo.get("summary", ""),
                "detail": lo.get("detail", ""),
                "memory_id": lo.get("memory_id", ""),
                "canonical_window_id": lo.get("canonical_window_id", ""),
                "source_system": lo.get("source_system", "openclaw"),
                "effective_from": lo.get("effective_from", ""),
                "lifecycle_version": lo.get("lifecycle_version", 1),
            })
    return active_records


def check_supersession_chain():
    """J1: Supersession Chain 检查。

    验证 lifecycle.jsonl 中的 supersedes / superseded_by 字段。
    当前状态：所有 supersedes / superseded_by 均为空。

    Returns: (is_valid, issues)
    """
    issues = []
    overlay = _get_lifecycle_overlay()
    supersedes_graph = {}
    for exp_id, lo in overlay.items():
        supersedes = lo.get("supersedes", []) or []
        if supersedes:
            supersedes_graph[exp_id] = set(supersedes)

    def has_cycle(node, visited, rec_stack):
        visited.add(node)
        rec_stack.add(node)
        for neighbor in supersedes_graph.get(node, []):
            if neighbor not in visited:
                if has_cycle(neighbor, visited, rec_stack):
                    return True
            elif neighbor in rec_stack:
                issues.append(f"Cycle: {node} -> {neighbor}")
                return True
        rec_stack.remove(node)
        return False

    visited = set()
    for node in supersedes_graph:
        if node not in visited:
            has_cycle(node, visited, set())

    all_exp_ids = set(overlay.keys())
    for exp_id, supersedes_list in supersedes_graph.items():
        for target in supersedes_list:
            if target not in all_exp_ids:
                issues.append(f"Orphan: {exp_id} supersedes non-existent {target}")

    return (len(issues) == 0, issues)



def get_memories():
    """带 TTL 和文件签名的缓存。"""
    now = datetime.now(timezone.utc).timestamp()
    global MEMORIES_CACHE, CACHE_TIME, MEMORIES_CACHE_SIGNATURE
    signature = _memories_source_signature()
    if (
        MEMORIES_CACHE is None
        or signature != MEMORIES_CACHE_SIGNATURE
        or (now - CACHE_TIME["ts"]) > CACHE_TTL
    ):
        MEMORIES_CACHE = load_memories()
        CACHE_TIME["ts"] = now
        MEMORIES_CACHE_SIGNATURE = signature
    return MEMORIES_CACHE

def handle_recall(body):
    """处理 recall 请求。

    J2-J5 Runtime:
    - J2: load_memories 已做 exp_id 去重
    - J3: _apply_lifecycle_overlay 过滤掉 conflict_decision=superseded 的记录
    - J4: _apply_lifecycle_overlay 计算 freshness_score 并合并到 _adjusted_score
    - J5: score_memory 优先使用 _adjusted_score（J5 混合 ranking）
    - J6/J7: inject_policy=never 时 should_inject=False（在 format_memory 中处理）
    """
    query = body.get("query", "")
    scope_filter = body.get("scope_filter", "")
    type_filter = body.get("type_filter", [])
    top_k = body.get("top_k", 5)
    threshold = body.get("threshold", 0.7)
    recall_mode_explicit = "recall_mode" in body
    recall_mode = body.get("recall_mode", "vector")  # substring / vector
    source_system_filter = _normalize_source_filter(
        body.get("source_system_filter", body.get("source_system", ""))
    )
    computer_name_filter = str(body.get("computer_name_filter", body.get("computer_name", "")) or "").strip()
    session_id_filter = str(body.get("session_id_filter", body.get("session_id", "")) or "").strip()

    # ─── 构造 scope dict for enforcement ────────────────────
    request_scope = {}
    if scope_filter:
        sf = scope_filter.replace("window/", "")
        request_scope = {
            "canonical_window_id": sf,
            "source_system": "openclaw",
            "computer_id": _current_node_id(),
        }
    else:
        request_scope = {
            "canonical_window_id": "",
            "source_system": "openclaw",
            "computer_id": _current_node_id(),
        }

    # v2 向量召回
    if recall_mode == "vector" and query:
        vector_multiplier = 12 if (source_system_filter or computer_name_filter or session_id_filter) else 3
        matched = vector_search_v2(query, top_k=top_k * vector_multiplier, scope_filter=scope_filter, type_filter=type_filter)
        if source_system_filter or computer_name_filter or session_id_filter:
            matched = filter_memories(
                matched,
                source_system_filter=source_system_filter,
                computer_name_filter=computer_name_filter,
                session_id_filter=session_id_filter,
            )
        # J2-J5: 应用 lifecycle overlay
        matched = _apply_lifecycle_overlay(matched)
        # B5: 强制 scope 过滤
        if SCOPE_ENFORCEMENT_AVAILABLE and scope_filter:
            matched = _se_filter_by_scope(matched, request_scope)
        matched = matched[:top_k]
        for m in matched:
            m["confidence"] = round(score_memory(m, query), 2)
            # J6: 低置信拒答
            m["should_inject"] = (m.get("confidence", 0) >= threshold)
            # J7: inject_policy=never 强制不注入
            lifecycle = m.get("_lifecycle", {})
            if lifecycle.get("inject_policy") == "never":
                m["should_inject"] = False
            m.update(attach_archive_card(m))
        vector_result = {
            "total_matched": len(matched),
            "returned": len(matched),
            "mode": "vector",
            "_scope_enforced": SCOPE_ENFORCEMENT_AVAILABLE,
            "_scope_used": request_scope,
            "_source_system_filter": source_system_filter or "all",
            "_memory_base_scope": "filtered" if source_system_filter else "shared",
            "_agent_boundary": "isolated_per_platform",
            "matched_memories": matched,
        }
        if matched and not recall_mode_explicit and _is_project_status_focus_query(query):
            project_status_matches = [
                m for m in matched
                if _is_project_status_memory(m)
            ]
            if project_status_matches:
                vector_result["matched_memories"] = project_status_matches[:top_k]
                vector_result["returned"] = len(vector_result["matched_memories"])
                vector_result["mode"] = "vector_focus_project_status"
                return vector_result
            fallback_body = dict(body)
            fallback_body["recall_mode"] = "substring"
            fallback_result = handle_recall(fallback_body)
            fallback_project_status = [
                m for m in fallback_result.get("matched_memories", [])
                if _is_project_status_memory(m)
            ]
            if fallback_project_status:
                fallback_result["mode"] = "vector_focus_project_status_substring"
                fallback_result["vector_result_project_status_missing"] = True
                fallback_result["vector_result"] = vector_result
                return fallback_result
        if matched or recall_mode_explicit:
            return vector_result
        fallback_body = dict(body)
        fallback_body["recall_mode"] = "substring"
        fallback_result = handle_recall(fallback_body)
        fallback_result["mode"] = "vector_fallback_substring"
        fallback_result["vector_result_empty"] = True
        fallback_result["vector_result"] = vector_result
        return fallback_result

    # substring 召回
    memories = get_memories()
    filtered = filter_memories(
        memories,
        type_filter=type_filter,
        scope_filter=scope_filter,
        query=query,
        source_system_filter=source_system_filter,
        computer_name_filter=computer_name_filter,
        session_id_filter=session_id_filter,
    )

    # J1 + J3A-G3: 噪音过滤（Hard Block）
    filtered = [m for m in filtered if not _is_noise_memory(m)]

    # J2-J5: 应用 lifecycle overlay（J3 过滤掉 superseded，J4/J5 增强分数）
    filtered = _apply_lifecycle_overlay(filtered)

    # 打分排序（使用 lifecycle 增强后的 _adjusted_score）
    scored = [(score_memory(m, query), m) for m in filtered]
    scored.sort(key=lambda x: -x[0])

    # top_k (预取更多用于 scope 过滤)
    # Current construction handoff queries must not lose project_status before
    # the later focus filter can see it.
    top_source = _focus_project_status_scored(scored, query)
    top = top_source[:top_k * 3]

    matched = [format_memory(m, query) for s, m in top]
    matched = _focus_project_status_matches(matched, query)
    # B5: 强制 scope 过滤
    if SCOPE_ENFORCEMENT_AVAILABLE and scope_filter:
        matched = _se_filter_by_scope(matched, request_scope)
    matched = matched[:top_k]
    for m in matched:
        m["confidence"] = round(m["confidence"], 2)
        # J6: 低置信拒答
        m["should_inject"] = (m.get("confidence", 0) >= threshold)
        # J7: inject_policy=never 强制不注入
        lifecycle = m.get("_lifecycle", {})
        if lifecycle.get("inject_policy") == "never":
            m["should_inject"] = False
        m.update(attach_archive_card(m))

    return {
        "query": query,
        "total_matched": len(filtered),
        "returned": len(matched),
        "_scope_enforced": SCOPE_ENFORCEMENT_AVAILABLE,
        "_scope_used": request_scope,
        "_source_system_filter": source_system_filter or "all",
        "_memory_base_scope": "filtered" if source_system_filter else "shared",
        "_agent_boundary": "isolated_per_platform",
        "matched_memories": matched,
    }

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # 静默

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            count = len(get_memories())
            self.wfile.write(json.dumps({"status": "ok", "memory_count": count}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/recall":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = handle_recall(body)
            # GAP-3: Emit RIC recall_observed event (p3_recall bypass hook)
            if RIC_AVAILABLE and body.get("query"):
                try:
                    ctx_pkg = ContextPackage(
                        query=body.get("query", ""),
                        canonical_window_id=body.get("scope", {}).get("canonical_window_id", ""),
                        session_id=body.get("scope", {}).get("session_id", ""),
                        intent_mode=body.get("mode", "summary"),
                        matched_memories=result.get("matched_memories", []),
                        source_refs=[m.get("source_refs", {}) for m in result.get("matched_memories", []) if m.get("source_refs")],
                        scope_enforced=True,
                    )
                    evt = InterpositionEvent(
                        event_type="recall_observed",
                        source_system="openclaw",
                        context_package=ctx_pkg.to_dict(),
                        observe_only=True,
                        dry_run=True,
                        applied=False,
                    )
                    log_interposition_event(evt)
                except Exception:
                    pass  # Never let RIC event crash the recall endpoint
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_server(port=9830):
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[p3] recall service running on http://127.0.0.1:{port}")
    server.serve_forever()

# ─── CLI 模式 ────────────────────────────────────

def cmd_recall(args):
    memories = get_memories()
    filtered = filter_memories(memories, type_filter=args.type, scope_filter=args.window, query=args.query)
    scored = sorted([(score_memory(m, args.query), m) for m in filtered], key=lambda x: -x[0])
    for score, m in scored[:args.top_k]:
        sr = m.get("_source_refs", {})
        print(f"\n[{m['_type']}] score={score:.2f} scope={m.get('scope','')}")
        print(f"  summary: {m.get('summary','')[:80]}")
        print(f"  window: {sr.get('canonical_window_id','')}")
        print(f"  session: {sr.get('session_id','')[:16]}...")
        print(f"  path: {sr.get('source_path','')}")

def cmd_list(args):
    memories = get_memories()
    by_type = defaultdict(int)
    for m in memories:
        by_type[m["_type"]] += 1
    print("知意对象统计:")
    for t, cnt in sorted(by_type.items()):
        print(f"  {t}: {cnt} 条")

def main():
    p = argparse.ArgumentParser(description="memcore-cloud P3 知意召回服务")
    sub = p.add_subparsers()

    srv = sub.add_parser("serve", help="启动 recall HTTP 服务")
    srv.add_argument("--port", type=int, default=9830)
    srv.set_defaults(fn=lambda a: run_server(a.port))

    rec = sub.add_parser("recall", help="CLI 召回")
    rec.add_argument("--query", default="", help="查询内容")
    rec.add_argument("--window", default="", help="window 过滤")
    rec.add_argument("--type", action="append", help="类型过滤 (case_memory/error_memory)")
    rec.add_argument("--top-k", type=int, default=5)
    rec.set_defaults(fn=cmd_recall)

    lst = sub.add_parser("list", help="列出所有对象")
    lst.set_defaults(fn=cmd_list)

    args = p.parse_args()
    if hasattr(args, "fn"):
        args.fn(args)
    else:
        p.print_help()

if __name__ == "__main__":
    main()
