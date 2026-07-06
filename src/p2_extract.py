#!/usr/bin/env python3
"""
memcore-cloud P2: 知意层重建提取脚本
从新底座 memcore-cloud/memory/ 读取 session，
提取 preference_memory / case_memory / error_memory，
输出新 source_refs 格式。
"""
import os, json, glob, re, shutil, time
from datetime import datetime, timezone
from collections import defaultdict

from config_loader import memory_root, zhiyi_root, raw_memory_subpath, alias_map as _alias_map_path, node_id, get_memcore_root
try:
    from src.evidence_bound_model import run_evidence_bound_experience_refinement
except ImportError:
    from evidence_bound_model import run_evidence_bound_experience_refinement
try:
    from src.source_system_runtime_declarations import source_system_for_raw_backfill_kind
except ImportError:
    from source_system_runtime_declarations import source_system_for_raw_backfill_kind
MEMORY_ROOT = memory_root()
MEMCORE_ROOT = os.path.join(memory_root(), raw_memory_subpath())
ZHIYI_ROOT = zhiyi_root()
os.makedirs(ZHIYI_ROOT, exist_ok=True)
LEGACY_RAW_SUBPATH_SOURCE_SYSTEM = source_system_for_raw_backfill_kind("source_artifact_copy") or "openclaw"

# ─── 关键词定义（复用旧工程经验）────────────────────

# Anti-noise: 系统内部标记和元数据不应用于经验提取
ANTI_NOISE_KW = [
    "执行工作_Start", "执行工作_End",
    "Sender (untrusted", "control-ui",
    "```json", "```html", "```bash",
    "untrusted metadata", "openclaw-control-ui",
    "Exec completed", "Exec failed",
    "[执行工作", "process_result",
]

def is_noise(text):
    """检测是否为系统内部噪音内容"""
    if not text:
        return True
    return any(kw in text for kw in ANTI_NOISE_KW)

def _split_keyword_env(value):
    return [
        item.strip().lower()
        for item in re.split(r"[,，\n]", value or "")
        if item.strip()
    ]

def _load_private_relay_keywords():
    """Load local-only relay keywords without putting private names in public code."""
    keywords = []
    keywords.extend(_split_keyword_env(os.environ.get("MEMCORE_PRIVATE_RELAY_KW", "")))
    path = os.environ.get("MEMCORE_PRIVATE_RELAY_KW_FILE", "")
    if not path:
        path = os.path.join(get_memcore_root(), ".local_sensitive", "p2_private_relay_keywords.json")
    try:
        if path and os.path.exists(os.path.expanduser(path)):
            with open(os.path.expanduser(path), encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                keywords.extend(str(item).strip().lower() for item in data if str(item).strip())
            elif isinstance(data, dict):
                values = data.get("keywords", [])
                if isinstance(values, list):
                    keywords.extend(str(item).strip().lower() for item in values if str(item).strip())
    except Exception:
        pass
    return list(dict.fromkeys(keywords))

def classify_preference_intent(text):
    """Classify whether a user turn is safe to write as preference_memory.

    Preference extraction is deliberately precision-first. User repair,
    deictic disambiguation, relayed audit text, and creative prompts may be
    useful evidence for errata/toolbook/review, but they should not become a
    durable Zhiyi preference merely because they contain words such as "称呼".
    """
    content = (text or "").strip()
    lower = content.lower()
    flags = []

    if not content:
        return {"intent_type": "empty", "write_preference": False, "flags": ["empty"]}
    if any(kw in lower for kw in CREATIVE_PROMPT_KW):
        return {
            "intent_type": "creative_prompt",
            "write_preference": False,
            "flags": ["creative_prompt"],
            "target_shelf": "ignore_or_review",
        }
    relay_keywords = THIRD_PARTY_RELAY_KW + _load_private_relay_keywords()
    if any(kw in lower for kw in relay_keywords) and len(content) > 120:
        return {
            "intent_type": "third_party_relay",
            "write_preference": False,
            "flags": ["third_party_relay"],
            "target_shelf": "review",
        }

    has_preference_keyword = any(kw in lower for kw in PREFERENCE_KW)
    has_strong_preference = any(kw in lower for kw in PREFERENCE_STRONG_KW)
    has_repair = any(kw in lower for kw in REPAIR_DISAMBIGUATION_KW)
    deictic_terms = [kw for kw in DEICTIC_KW if kw in content]
    has_deictic = bool(deictic_terms)

    if has_repair:
        flags.append("repair_or_disambiguation")
    if has_deictic:
        flags.append("deictic_reference")

    if has_repair and (has_deictic or has_preference_keyword):
        return {
            "intent_type": "correction_disambiguation",
            "write_preference": False,
            "flags": flags,
            "target_shelf": "errata_or_toolbook",
            "ambiguous_terms": deictic_terms,
        }

    if has_deictic and has_preference_keyword and not has_strong_preference:
        return {
            "intent_type": "deictic_low_confidence",
            "write_preference": False,
            "flags": flags or ["deictic_reference"],
            "target_shelf": "review",
            "ambiguous_terms": deictic_terms,
        }

    if has_strong_preference or has_preference_keyword:
        return {
            "intent_type": "preference",
            "write_preference": True,
            "flags": flags,
            "target_shelf": "zhiyi",
        }

    return {
        "intent_type": "not_preference",
        "write_preference": False,
        "flags": flags,
        "target_shelf": "none",
    }

CASE_CORE_KW = [
    "验证", "测试", "方案", "流程", "判断", "结论", "决策",
    "关键", "路径", "策略", "模式", "结构", "机制", "闭环",
    "做过", "试过", "跑通", "通过", "成立", "确认"
]
CASE_CONTEXT_KW = [
    "首先", "然后", "接下来", "最后", "先", "再", "最终",
    "所以", "因此", "导致", "原因", "结果", "发现",
    "过程", "步骤", "阶段", "顺序", "之前", "之后"
]
CASE_ANTI_KW = [
    "错误", "失败", "不对", "不是", "报错", "异常", "问题",
    "bug", "error", "fail", "wrong", "incorrect",
    "无法", "不能", "不能", "不可以", "失败"
]
PREFERENCE_KW = [
    "叫我", "喊我", "你叫我", "称呼", "叫我什么",
    "prefer", "叫啥", "名字是", "外号", "昵称"
]
PREFERENCE_STRONG_KW = [
    "我喜欢", "我不喜欢", "我更喜欢", "我希望", "我习惯",
    "以后按", "以后用", "以后叫我", "你以后", "不要再", "别再",
    "prefer", "i prefer", "my preference", "call me"
]
CREATIVE_PROMPT_KW = [
    "write a dream diary entry", "dream diary", "memory fragments",
    "写一篇梦日记", "梦日记", "根据这些记忆片段"
]
THIRD_PARTY_RELAY_KW = [
    "审计", "顾问", "报告", "任务书", "外部建议", "评审意见",
    "下面是", "这里有份", "这里有一份"
]
REPAIR_DISAMBIGUATION_KW = [
    "我现在说的是", "我说的是", "现在说的是", "指的是",
    "不是", "别混", "不要混", "不会和", "不等于",
    "那个我会称呼", "那个我会叫", "这边", "那边",
    "你理解明显不对", "你搞错了", "你带偏了", "原话是不带"
]
DEICTIC_KW = ["这个", "那个", "这条", "那条", "这边", "那边", "上面", "下面"]
ERROR_KW = [
    "错误", "失败", "报错", "不对", "不是", "异常", "问题",
    "bug", "error", "fail", "wrong", "incorrect",
    "无法", "不能", "失败", "崩", "坏"
]

# ─── 工具函数 ─────────────────────────────────────

def load_alias_map():
    path = _alias_map_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    else:
        data = {}
    # 反向索引：observed_name → canonical
    reverse = {}
    for canon, info in data.get("canonical_windows", {}).items():
        for obs in info.get("observed_names", []):
            reverse[obs] = canon
    return reverse

def get_window_from_path(file_path):
    """从文件路径提取 canonical_window_id"""
    parts = file_path.replace(MEMCORE_ROOT, "").strip("/").split("/")
    if len(parts) >= 1:
        return parts[0]
    return "unknown"

def infer_source_context(filepath):
    """Infer source context from new computer-first paths and legacy source-first paths."""
    path = os.path.abspath(filepath)
    rel = ""
    try:
        rel = os.path.relpath(path, MEMORY_ROOT)
    except Exception:
        pass
    parts = rel.split(os.sep) if rel and not rel.startswith("..") else []
    if len(parts) >= 5:
        return {
            "source_system": parts[1],
            "computer_name": parts[0],
            "native_artifact_format": parts[2],
            "canonical_window_id": parts[3],
            "session_id": os.path.basename(path).replace(".jsonl", ""),
            "raw_archive_layout": "computer_first",
        }
    if len(parts) >= 4:
        return {
            "source_system": parts[0],
            "computer_name": parts[1],
            "native_artifact_format": "",
            "canonical_window_id": parts[2],
            "session_id": os.path.basename(path).replace(".jsonl", ""),
            "raw_archive_layout": "legacy_source_first",
        }
    try:
        legacy_rel = path.replace(MEMCORE_ROOT, "").strip("/").split("/")
        if len(legacy_rel) >= 2:
            return {
                "source_system": LEGACY_RAW_SUBPATH_SOURCE_SYSTEM,
                "computer_name": node_id(),
                "native_artifact_format": "",
                "canonical_window_id": legacy_rel[0],
                "session_id": os.path.basename(path).replace(".jsonl", ""),
                "raw_archive_layout": f"legacy_{LEGACY_RAW_SUBPATH_SOURCE_SYSTEM}_subpath",
            }
    except Exception:
        pass
    return {
        "source_system": LEGACY_RAW_SUBPATH_SOURCE_SYSTEM,
        "computer_name": node_id(),
        "native_artifact_format": "",
        "canonical_window_id": "unknown",
        "session_id": os.path.basename(path).replace(".jsonl", ""),
        "raw_archive_layout": "unknown_fallback",
    }

def _extract_text_from_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(item.get("thinking"), str):
                    parts.append(item.get("thinking", ""))
            elif item:
                parts.append(str(item))
        return " ".join(p for p in parts if p)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content) if content else ""

def _codex_payload_message(rec):
    payload = rec.get("payload", {})
    if not isinstance(payload, dict):
        return None
    role = payload.get("role")
    content = ""
    msg_id = ""
    if payload.get("type") == "user_message":
        role = "user"
        content = payload.get("message", "")
        msg_id = payload.get("turn_id", "")
    elif payload.get("type") == "agent_message":
        role = "assistant"
        content = payload.get("message", "")
        msg_id = payload.get("turn_id", "")
    elif payload.get("type") == "message" and role in ("user", "assistant"):
        content = _extract_text_from_content(payload.get("content", ""))
    if role not in ("user", "assistant"):
        return None
    content = _extract_text_from_content(content)
    if not content or len(content) <= 10:
        return None
    return {
        "role": role,
        "content": content,
        "id": rec.get("id", "") or msg_id or rec.get("timestamp", ""),
        "parentId": "",
    }

def _claude_code_record_message(rec):
    if rec.get("type") not in ("user", "assistant"):
        return None
    msg = rec.get("message", {})
    if not isinstance(msg, dict):
        return None
    role = msg.get("role") or rec.get("type")
    if role not in ("user", "assistant"):
        return None
    content = _extract_text_from_content(msg.get("content", ""))
    if not content or len(content) <= 10:
        return None
    return {
        "role": role,
        "content": content,
        "id": rec.get("uuid", "") or rec.get("id", "") or rec.get("timestamp", ""),
        "parentId": rec.get("parentUuid", "") or msg.get("parentUuid", ""),
    }

def _attach_source_offset(msg, line_start, line_end):
    msg["source_offset"] = int(line_start)
    msg["source_end_offset"] = int(line_end)
    return msg

def extract_messages(filepath, offset=0):
    """从 session 文件提取消息"""
    messages = []
    try:
        with open(filepath, "rb") as f:
            if offset:
                f.seek(offset)
            while True:
                line_start = f.tell()
                raw_line = f.readline()
                if not raw_line:
                    break
                line_end = f.tell()
                encoding = "utf-8-sig" if line_start == 0 else "utf-8"
                line = raw_line.decode(encoding, errors="replace")
                line = line.strip()
                if not line: continue
                try:
                    rec = json.loads(line)
                    if rec.get("type") == "message":
                        msg = rec.get("message", {})
                        content = msg.get("content", "")
                        content = _extract_text_from_content(content)
                        if content and len(content) > 10:
                            messages.append(_attach_source_offset({
                                "role": msg.get("role", "?"),
                                "content": content,
                                "id": rec.get("id", ""),
                                "parentId": msg.get("parentId", ""),
                            }, line_start, line_end))
                    elif rec.get("type") in ("response_item", "event_msg"):
                        msg = _codex_payload_message(rec)
                        if msg:
                            messages.append(_attach_source_offset(msg, line_start, line_end))
                    elif rec.get("type") in ("user", "assistant"):
                        msg = _claude_code_record_message(rec)
                        if msg:
                            messages.append(_attach_source_offset(msg, line_start, line_end))
                except: pass
    except: pass
    return messages

def _msg_offset_map(msg):
    msg_id = str(msg.get("id", "") or "")
    if not msg_id:
        return {}
    try:
        start = int(msg.get("source_offset"))
        end = int(msg.get("source_end_offset"))
    except Exception:
        return {}
    if start < 0 or end <= start:
        return {}
    return {msg_id: {"start": start, "end": end}}

def make_source_refs(session_id, window, filepath, msg_ids, source_system=None, computer_name=None, msg_offsets=None):
    """生成新格式 source_refs"""
    ctx = infer_source_context(filepath)
    artifact_type = ctx.get("native_artifact_format") or f"{source_system or ctx['source_system']}_session_jsonl"
    refs = {
        "source_system": source_system or ctx["source_system"],
        "computer_name": computer_name or ctx["computer_name"],
        "canonical_window_id": window,
        "session_id": session_id,
        "source_path": filepath,
        "msg_ids": msg_ids,
        "artifact_type": artifact_type,
        "native_artifact_format": artifact_type,
        "raw_archive_layout": ctx.get("raw_archive_layout", ""),
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if msg_offsets:
        refs["byte_offsets"] = msg_offsets
    meta_path = filepath + ".meta.json"
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8-sig") as f:
                meta = json.load(f)
            if meta.get("project_root"):
                refs["project_root"] = meta.get("project_root", "")
            if meta.get("thread_name"):
                refs["thread_name"] = meta.get("thread_name", "")
        except Exception:
            pass
    return refs

def make_exp_id(type_name, content_hash):
    """生成稳定 exp_id：基于 type_name + content_hash 的 SHA256 前8位。

    同一输入连续运行得到相同 ID（幂等）。
    """
    import hashlib
    h = hashlib.sha256(f"{type_name}:{content_hash}".encode()).hexdigest()[:8]
    return f"exp-{type_name}-{h}"


def build_p2_refinement_evidence(candidate):
    if not isinstance(candidate, dict):
        return []
    text_parts = [
        str(candidate.get("summary") or ""),
        str(candidate.get("detail") or ""),
    ]
    text = "\n".join(part for part in text_parts if part.strip()).strip()
    if not text:
        return []
    refs = {}
    raw_refs = candidate.get("source_refs")
    if isinstance(raw_refs, str) and raw_refs.strip():
        try:
            parsed = json.loads(raw_refs)
            if isinstance(parsed, dict):
                refs = parsed
        except json.JSONDecodeError:
            refs = {"source_refs_text": raw_refs[:500]}
    elif isinstance(raw_refs, dict):
        refs = raw_refs
    source_id = str(candidate.get("exp_id") or candidate.get("session_id") or "p2-candidate")
    return [
        {
            "source_id": source_id,
            "evidence_ref": str(candidate.get("exp_id") or source_id),
            "role": "candidate",
            "timestamp": str(candidate.get("extracted_at") or ""),
            "text": text,
            "source_refs": refs,
            "score": candidate.get("score"),
        }
    ]


def refine_p2_candidate_with_model(candidate, *, execute=False, client=None, model_config=None):
    evidence = build_p2_refinement_evidence(candidate)
    result = run_evidence_bound_experience_refinement(
        candidate if isinstance(candidate, dict) else {},
        evidence,
        execute=execute,
        client=client,
        model_config=model_config,
    )
    result["candidate_write_performed"] = False
    result["candidate_exp_id"] = candidate.get("exp_id", "") if isinstance(candidate, dict) else ""
    return result

# ─── 提取逻辑 ─────────────────────────────────────

def extract_preference(messages, session_id, window, filepath):
    """提取 preference_memory"""
    results = []
    for msg in messages:
        if msg["role"] != "user":
            continue
        content = msg["content"]
        if is_noise(content):
            continue
        content_lower = content.lower()
        intent = classify_preference_intent(content)
        if intent.get("write_preference"):
            refs = make_source_refs(session_id, window, filepath, [msg.get("id","")], msg_offsets=_msg_offset_map(msg))
            results.append({
                "exp_id": make_exp_id("pref", content[:50]),
                "type": "preference_memory",
                # Scope metadata fields are structured, not just a string.
                "canonical_window_id": window,
                "session_id": session_id,
                "computer_id": refs["computer_name"],
                "source_system": refs["source_system"],
                "scope": f"window/{window}",
                "summary": content[:80],
                "detail": f"用户在 session {session_id} 中表达了偏好：{content}",
                "source_refs": json.dumps(refs, ensure_ascii=False),
                "evidence_level": "medium",
                "score": 0.7,
                "extract_intent": intent,
                "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            })
    return results

def extract_error(messages, session_id, window, filepath):
    """提取 error_memory"""
    results = []
    last_user_content = ""
    for msg in messages:
        if msg.get("role") == "user":
            last_user_content = msg.get("content", "")
            continue
        if msg["role"] != "assistant":
            continue
        content = msg["content"]
        if is_noise(content):
            continue
        content_lower = content.lower()
        found_kw = [kw for kw in ERROR_KW if kw in content_lower]
        if found_kw:
            # 向前找 user 消息
            user_content = ""
            for prev in messages:
                if prev["id"] == msg.get("parentId") and prev["role"] == "user":
                    user_content = prev["content"]
                    break
            if not user_content:
                user_content = last_user_content
            refs = make_source_refs(session_id, window, filepath, [msg.get("id","")], msg_offsets=_msg_offset_map(msg))
            results.append({
                "exp_id": make_exp_id("err", content[:50]),
                "type": "error_memory",
                # Scope metadata fields are structured, not just a string.
                "canonical_window_id": window,
                "session_id": session_id,
                "computer_id": refs["computer_name"],
                "source_system": refs["source_system"],
                "scope": f"window/{window}",
                "summary": f"错误相关：{content[:80]}",
                "detail": f"assistant 在 {session_id} 中提到错误，关键词：{', '.join(found_kw)}。用户原话：{user_content}。assistant 原话：{content}",
                "source_refs": json.dumps(refs, ensure_ascii=False),
                "evidence_level": "medium",
                "score": 0.65,
                "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            })
    return results

def extract_case(messages, session_id, window, filepath):
    """提取 case_memory"""
    results = []
    text_by_role = {msg.get("id", ""): msg for msg in messages}

    last_user_content = ""
    for msg in messages:
        if msg.get("role") == "user":
            last_user_content = msg.get("content", "")
            continue
        if msg["role"] != "assistant":
            continue
        content = msg["content"]
        if is_noise(content):
            continue
        content_lower = content.lower()

        core_hits = [kw for kw in CASE_CORE_KW if kw in content]
        anti_hits = [kw for kw in CASE_ANTI_KW if kw in content_lower]

        if core_hits and not anti_hits:
            # 向前找 context
            context = ""
            if msg.get("parentId"):
                p = text_by_role.get(msg["parentId"], {})
                context = p.get("content", "")
            if not context:
                context = last_user_content

            # 同时要求 context 有内容
            has_context = any(kw in context for kw in CASE_CONTEXT_KW) if context else False
            if has_context or len(core_hits) >= 2:
                refs = make_source_refs(session_id, window, filepath, [msg.get("id","")], msg_offsets=_msg_offset_map(msg))
                results.append({
                    "exp_id": make_exp_id("case", content[:50]),
                    "type": "case_memory",
                    # Scope metadata fields are structured, not just a string.
                    "canonical_window_id": window,
                    "session_id": session_id,
                    "computer_id": refs["computer_name"],
                    "source_system": refs["source_system"],
                    "scope": f"window/{window}",
                    "summary": f"案例：{content[:80]}",
                    "detail": f"在 {session_id} 中提取。核心词：{', '.join(core_hits)}。上下文：{context}。assistant 原话：{content}",
                    "source_refs": json.dumps(refs, ensure_ascii=False),
                    "evidence_level": "medium",
                    "score": 0.7,
                    "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                })
    return results

# ─── 主流程 ─────────────────────────────────────


# ─── 增量提取 ─────────────────────────────────────

# P2 checkpoint path: env MEMCORE_P2_CHECKPOINT overrides default
_DEFAULT_P2_CHECKPOINT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "..", ".checkpoint_p2.json")
P2_CHECKPOINT = os.environ.get("MEMCORE_P2_CHECKPOINT") or _DEFAULT_P2_CHECKPOINT


def load_p2_checkpoint():
    if not os.path.exists(P2_CHECKPOINT):
        return {}
    try:
        with open(P2_CHECKPOINT, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, ValueError):
        _backup_corrupt_p2_checkpoint(P2_CHECKPOINT)
        return {}


def save_p2_checkpoint(data):
    checkpoint_dir = os.path.dirname(os.path.abspath(P2_CHECKPOINT))
    if checkpoint_dir:
        os.makedirs(checkpoint_dir, exist_ok=True)
    tmp = f"{P2_CHECKPOINT}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, P2_CHECKPOINT)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _backup_corrupt_p2_checkpoint(path):
    if not os.path.exists(path):
        return ""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{path}.corrupt-backup-{stamp}-{os.getpid()}"
    backup = base
    suffix = 1
    while os.path.exists(backup):
        suffix += 1
        backup = f"{base}-{suffix}"
    try:
        shutil.move(path, backup)
    except OSError:
        return ""
    return backup


def _load_existing_exp_ids():
    """Load all exp_ids from existing JSONL files for dedup."""
    ids = set()
    for subtype in ("preference_memory", "case_memory", "error_memory"):
        fp = os.path.join(ZHIYI_ROOT, subtype, "{}.jsonl".format(subtype))
        if os.path.exists(fp):
            try:
                with open(fp, encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            ids.add(rec["exp_id"])
                        except (json.JSONDecodeError, KeyError):
                            continue
            except IOError:
                continue
    return ids


def _append_jsonl(items, subtype, existing_ids):
    """Append to JSONL with dedup, return count of new items."""
    dir_path = os.path.join(ZHIYI_ROOT, subtype)
    os.makedirs(dir_path, exist_ok=True)
    out_path = os.path.join(dir_path, "{}.jsonl".format(subtype))
    new_count = 0
    try:
        with open(out_path, "a", encoding="utf-8") as f:
            for item in items:
                if item["exp_id"] not in existing_ids:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    new_count += 1
                    existing_ids.add(item["exp_id"])
    except IOError:
        print("[p2] ERROR: cannot write", out_path)
        return 0
    return new_count


def incremental_extract_session(filepath, session_id=None, window=None):
    """Incremental extraction for a single session file.

    Reads P2 checkpoint offset, processes only new messages,
    dedup-appends to JSONL, updates checkpoint.

    Returns (pref_new, case_new, error_new)
    """
    if not os.path.exists(filepath):
        print("[p2] ERROR: file not found", filepath)
        return 0, 0, 0

    # Infer session_id / window from path if not provided
    if not session_id or not window:
        try:
            ctx = infer_source_context(filepath)
            window = ctx["canonical_window_id"]
            session_id = ctx["session_id"]
        except Exception:
            print("[p2] ERROR: cannot parse window/session_id from", filepath)
            return 0, 0, 0
    if "." in session_id:
        session_id = session_id.split(".")[0]

    # Read P2 checkpoint
    ckpt = load_p2_checkpoint()
    prior = ckpt.get(filepath, {})
    last_offset = prior.get("offset", 0)

    # Check file size
    file_size = os.path.getsize(filepath)
    if file_size <= last_offset:
        return 0, 0, 0

    # Incrementally read new messages
    messages = extract_messages(filepath, offset=last_offset)
    if not messages:
        ckpt[filepath] = {
            "offset": file_size,
            "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "last_status": "no_extractable_messages",
        }
        save_p2_checkpoint(ckpt)
        return 0, 0, 0

    # Extract
    prefs = extract_preference(messages, session_id, window, filepath)
    errors = extract_error(messages, session_id, window, filepath)
    cases = extract_case(messages, session_id, window, filepath)

    # Dedup append
    existing_ids = _load_existing_exp_ids()
    pref_new = _append_jsonl(prefs, "preference_memory", existing_ids)
    case_new = _append_jsonl(cases, "case_memory", existing_ids)
    error_new = _append_jsonl(errors, "error_memory", existing_ids)

    # Update checkpoint
    ckpt[filepath] = {
        "offset": file_size,
        "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_p2_checkpoint(ckpt)

    return pref_new, case_new, error_new

def main():
    print(f"[p2] 开始从 {MEMORY_ROOT} 提取知意对象...")
    all_prefs, all_cases, all_errors = [], [], []

    total = 0

    raw_files = []
    if os.path.isdir(MEMORY_ROOT):
        raw_files.extend(glob.glob(os.path.join(MEMORY_ROOT, "*", "*", "*", "*.jsonl")))
        raw_files.extend(glob.glob(os.path.join(MEMORY_ROOT, "*", "*", "*", "*", "*.jsonl")))
    for sf in sorted(set(raw_files)):
        ctx = infer_source_context(sf)
        session_id = ctx["session_id"]
        window = ctx["canonical_window_id"]
        messages = extract_messages(sf)
        total += 1

        all_prefs.extend(extract_preference(messages, session_id, window, sf))
        all_errors.extend(extract_error(messages, session_id, window, sf))
        all_cases.extend(extract_case(messages, session_id, window, sf))

    print(f"[p2] 处理了 {total} 个 session 文件")
    print(f"[p2] 提取结果: preference={len(all_prefs)} case={len(all_cases)} error={len(all_errors)}")

    # 写入
    def write_jsonl(items, subtype):
        dir_path = os.path.join(ZHIYI_ROOT, subtype)
        os.makedirs(dir_path, exist_ok=True)
        out_path = os.path.join(dir_path, f"{subtype}.jsonl")
        with open(out_path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"[p2] 写入: {out_path} ({len(items)} 条)")
        return out_path

    prefs_out = write_jsonl(all_prefs, "preference_memory")
    cases_out = write_jsonl(all_cases, "case_memory")
    errors_out = write_jsonl(all_errors, "error_memory")

    print(f"\n[p2] 提取完成!")
    print(f"  preference_memory: {len(all_prefs)} 条 → {prefs_out}")
    print(f"  case_memory: {len(all_cases)} 条 → {cases_out}")
    print(f"  error_memory: {len(all_errors)} 条 → {errors_out}")

    # 统计
    print(f"\n=== 按 window 统计 ===")
    for subtype, items in [("preference", all_prefs), ("case", all_cases), ("error", all_errors)]:
        by_window = defaultdict(int)
        for item in items:
            try:
                refs = json.loads(item["source_refs"])
                w = refs.get("canonical_window_id", "unknown")
                by_window[w] += 1
            except: pass
        for w, cnt in sorted(by_window.items()):
            print(f"  {subtype:12} [{w}]: {cnt}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="P2 \u77e5\u610f\u5c42\u63d0\u53d6")
    p.add_argument("--incremental", metavar="PATH", help="\u589e\u91cf\u63d0\u53d6\u5355\u4e2a session \u6587\u4ef6")
    args = p.parse_args()
    if args.incremental:
        pn, cn, en = incremental_extract_session(args.incremental)
        print("[p2] incremental: preference={} case={} error={}".format(pn, cn, en))
    else:
        main()
