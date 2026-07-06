#!/usr/bin/env python3
"""Read-only raw evidence excerpt extraction under Time River.

Tiandao contract: this module is a bounded raw evidence reader. It can read
source-backed raw files and maintain small local cursor/offset caches for
bounded excerpts, but it is not the raw origin, not a recall policy owner, and
not a write path for memory or platform configuration.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from src.raw_text_decode import (
        decode_text_bytes as _decode_text_bytes,
        iter_decoded_jsonl_lines as _iter_decoded_jsonl_lines,
        jsonl_line_separator_for_sample as _jsonl_line_separator_for_sample,
    )
except Exception:
    from raw_text_decode import (
        decode_text_bytes as _decode_text_bytes,
        iter_decoded_jsonl_lines as _iter_decoded_jsonl_lines,
        jsonl_line_separator_for_sample as _jsonl_line_separator_for_sample,
    )

UTC = timezone.utc
TIANDAO_RAW_EVIDENCE_EXCERPT_CONTRACT = "tiandao_raw_evidence_excerpt_reader.v1"
MAX_RAW_STREAM_SCAN_BYTES = 8 * 1024 * 1024
DEFAULT_RAW_SEGMENT_BYTES = 1024 * 1024
MAX_RAW_SEGMENT_BYTES = 8 * 1024 * 1024
DEFAULT_RAW_SEGMENT_MAX_SEGMENTS = 4
MAX_RAW_SEGMENT_MAX_SEGMENTS = 32
RAW_SEGMENT_OVERLAP_BYTES = 4096
MAX_RAW_OFFSET_READ_BYTES = 1024 * 1024
DEFAULT_RAW_OFFSET_INDEX_MAX_SCAN_BYTES = 1024 * 1024
MAX_RAW_OFFSET_INDEX_MAX_SCAN_BYTES = 16 * 1024 * 1024
DEFAULT_RAW_EXCERPT_DEADLINE_SECONDS = 1.0
MAX_RAW_EXCERPT_DEADLINE_SECONDS = 10.0
FORBIDDEN_STATE_DIR_PARTS = {
    ".codex",
    ".hermes",
    ".openclaw",
    ".ssh",
}


def get_raw_evidence_excerpt_contract() -> Dict[str, Any]:
    return {
        "ok": True,
        "contract": TIANDAO_RAW_EVIDENCE_EXCERPT_CONTRACT,
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "reader_layer": "raw_evidence_excerpt",
        "source_authority": "raw_record_guardian",
        "not_raw_origin": True,
        "read_only_by_default": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "writes_limited_to": ["bounded_reader_cursor_cache", "bounded_reader_offset_cache"],
        "raw_origin_policy": "raw/time origin remains the source of truth; this module only returns bounded excerpts from source refs",
    }


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def _safe_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    return _safe_int(os.environ.get(name, ""), default, minimum, maximum)


def _raw_segment_bytes() -> int:
    return _safe_env_int(
        "MEMCORE_RAW_SEGMENT_BYTES",
        DEFAULT_RAW_SEGMENT_BYTES,
        4096,
        MAX_RAW_SEGMENT_BYTES,
    )


def _raw_segment_max_segments() -> int:
    return _safe_env_int(
        "MEMCORE_RAW_SEGMENT_MAX_SEGMENTS",
        DEFAULT_RAW_SEGMENT_MAX_SEGMENTS,
        1,
        MAX_RAW_SEGMENT_MAX_SEGMENTS,
    )


def _raw_offset_index_max_scan_bytes() -> int:
    return _safe_env_int(
        "MEMCORE_RAW_OFFSET_INDEX_MAX_SCAN_BYTES",
        DEFAULT_RAW_OFFSET_INDEX_MAX_SCAN_BYTES,
        64 * 1024,
        MAX_RAW_OFFSET_INDEX_MAX_SCAN_BYTES,
    )


def _raw_excerpt_deadline_seconds() -> float:
    try:
        parsed = float(str(os.environ.get("MEMCORE_RAW_EXCERPT_DEADLINE_SECONDS") or "").strip())
    except Exception:
        parsed = DEFAULT_RAW_EXCERPT_DEADLINE_SECONDS
    return max(0.05, min(parsed, MAX_RAW_EXCERPT_DEADLINE_SECONDS))


def _deadline_exceeded(deadline: float | None) -> bool:
    return bool(deadline is not None and time.perf_counter() >= deadline)


def _is_safe_relative_source_path(path_str: str) -> bool:
    if not path_str:
        return False
    norm = path_str.replace('\\', '/').strip()
    if norm.startswith('/') or norm.startswith('..') or '/../' in norm or '/..' in norm:
        return False
    return True


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_path_for_guard(path: Path) -> Path | None:
    try:
        return path.expanduser().resolve()
    except Exception:
        return None


def _is_path_inside(path: Path, root: Path, *, allow_root: bool = False) -> bool:
    resolved_path = _resolve_path_for_guard(path)
    resolved_root = _resolve_path_for_guard(root)
    if not resolved_path or not resolved_root:
        return False
    if resolved_path == resolved_root:
        return allow_root
    try:
        resolved_path.relative_to(resolved_root)
        return True
    except ValueError:
        return False


def _raw_gateway_state_allowed_roots() -> List[Path]:
    roots = [
        _project_root() / "output",
        Path(tempfile.gettempdir()),
    ]
    try:
        from src.config_loader import memory_root
    except ImportError:
        try:
            from config_loader import memory_root
        except ImportError:
            memory_root = None
    if memory_root:
        try:
            roots.append(Path(memory_root()) / "output")
        except Exception:
            pass

    resolved_roots: List[Path] = []
    for root in roots:
        resolved = _resolve_path_for_guard(root)
        if resolved and resolved not in resolved_roots:
            resolved_roots.append(resolved)
    return resolved_roots


def _is_safe_raw_gateway_state_dir(path: Path) -> bool:
    resolved = _resolve_path_for_guard(path)
    if not resolved:
        return False
    if any(part in FORBIDDEN_STATE_DIR_PARTS for part in resolved.parts):
        return False
    return any(_is_path_inside(resolved, root) for root in _raw_gateway_state_allowed_roots())


def _raw_segment_state_dir() -> Path:
    override = os.environ.get("MEMCORE_RAW_GATEWAY_STATE_DIR", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if not _is_safe_raw_gateway_state_dir(candidate):
            raise ValueError(
                "unsafe MEMCORE_RAW_GATEWAY_STATE_DIR: use project output, memcore output, or a temp child directory"
            )
        resolved = _resolve_path_for_guard(candidate)
        return resolved if resolved else candidate
    return _project_root() / "output" / "raw_gateway_state"


def _raw_segment_state_path() -> Path:
    return _raw_segment_state_dir() / "segment_cursors.json"


def _raw_offset_index_path() -> Path:
    return _raw_segment_state_dir() / "offset_index.json"


def _load_raw_segment_state() -> Dict[str, Any]:
    path = _raw_segment_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_raw_segment_state(state: Dict[str, Any]) -> None:
    try:
        path = _raw_segment_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        return None


def _load_raw_offset_index() -> Dict[str, Any]:
    path = _raw_offset_index_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_raw_offset_index(index: Dict[str, Any]) -> None:
    try:
        path = _raw_offset_index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        return None


def _file_signature(path: Path) -> Dict[str, Any]:
    try:
        st = path.stat()
        return {
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
            "inode": int(getattr(st, "st_ino", 0) or 0),
        }
    except Exception:
        return {"size": 0, "mtime_ns": 0, "inode": 0}


def _raw_segment_key(path: Path, msg_ids: List[str]) -> str:
    seed = json.dumps(
        {
            "path": str(path),
            "msg_ids": [str(mid) for mid in (msg_ids or []) if str(mid)],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()


def _allowed_source_roots() -> List[Path]:
    roots = [Path.cwd(), _project_root()]
    env_root = os.environ.get("MEMCORE_ROOT", "").strip()
    if env_root:
        roots.append(Path(env_root).expanduser() / "memory")
    try:
        from src.config_loader import memory_root
    except ImportError:
        try:
            from config_loader import memory_root
        except ImportError:
            memory_root = None
    if memory_root:
        roots.append(Path(memory_root()))

    resolved_roots: List[Path] = []
    for root in roots:
        try:
            resolved = root.expanduser().resolve()
        except Exception:
            continue
        if resolved not in resolved_roots:
            resolved_roots.append(resolved)
    return resolved_roots


def _is_under_allowed_root(path: Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        return False
    for root in _allowed_source_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _memory_relative_candidates(raw: str) -> List[Path]:
    normalized = raw.replace("\\", "/").strip()
    marker = "/memory/"
    index = normalized.find(marker)
    if index < 0:
        return []
    rel = normalized[index + len(marker):].strip("/")
    if not _is_safe_relative_source_path(rel):
        return []
    return [Path(rel)]


def _resolve_relocated_memory_path(raw: str) -> Path | None:
    candidates = _memory_relative_candidates(raw)
    if not candidates:
        return None
    for root in _allowed_source_roots():
        search_roots = [root]
        if root.name == "memory":
            search_roots.append(root.parent)
        for base in search_roots:
            for rel in candidates:
                candidate = (base / rel).resolve()
                if candidate.exists() and _is_under_allowed_root(candidate):
                    return candidate
    return None


def _resolve_source_path(source_path: str) -> Path | None:
    if not source_path:
        return None
    raw = source_path.strip()
    p = Path(raw).expanduser()
    if p.is_absolute():
        resolved = p.resolve()
        if _is_under_allowed_root(resolved):
            return resolved
        return _resolve_relocated_memory_path(raw)

    if not _is_safe_relative_source_path(raw):
        return None

    for root in _allowed_source_roots():
        resolved = (root / p).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.exists():
            return resolved
    return (Path.cwd().resolve() / p).resolve()


def _extract_content_text(content: Any) -> str:
    if isinstance(content, (bytes, bytearray, memoryview)):
        return _decode_text_bytes(bytes(content))
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, dict):
                if isinstance(part.get('text'), str):
                    parts.append(part['text'])
                elif isinstance(part.get('thinking'), str):
                    parts.append(part['thinking'])
                else:
                    parts.append(json.dumps(part, ensure_ascii=False))
            elif part:
                parts.append(str(part))
        return ' '.join(parts)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content) if content else ''


def _append_jsonl_obj_excerpt(
    obj: Dict[str, Any],
    msg_ids: List[str],
    excerpt_parts: List[str],
    pending_msg_ids: set[str] | None = None,
) -> bool:
    appended = False

    def append(role: str, content: Any, matched_id: str = "") -> None:
        nonlocal appended
        if pending_msg_ids is not None and matched_id:
            pending_msg_ids.discard(matched_id)
        excerpt_parts.append(f"[{role or 'unknown'}] {_extract_content_text(content)}")
        appended = True

    if 'messages' in obj and isinstance(obj['messages'], list):
        for idx, msg in enumerate(obj['messages']):
            indexed_id = f"msg_{idx+1:03d}"
            if msg_ids and indexed_id not in msg_ids:
                continue
            role = str(msg.get('role', 'unknown')) if isinstance(msg, dict) else 'unknown'
            content = msg.get('content', '') if isinstance(msg, dict) else msg
            append(role, content, indexed_id)
        return appended

    msg_id = str(obj.get('id', '') or '')
    payload = obj.get('payload', {}) if isinstance(obj.get('payload'), dict) else {}
    payload_type = payload.get('type', '')
    candidates = [
        msg_id,
        str(payload.get('turn_id', '') or ''),
        str(obj.get('timestamp', '') or ''),
    ]
    matched_id = next((candidate for candidate in candidates if candidate and candidate in msg_ids), candidates[0])
    if msg_ids and not any(candidate in msg_ids for candidate in candidates if candidate):
        return False

    if obj.get('type') == 'message':
        message = obj.get('message', {}) if isinstance(obj.get('message'), dict) else {}
        append(str(message.get('role', 'unknown')), message.get('content', ''), matched_id)
    elif obj.get('type') in ('response_item', 'event_msg') and payload_type in ('message', 'user_message', 'agent_message', 'function_call_output'):
        role = payload.get('role', '')
        if payload_type == 'user_message':
            role = 'user'
            content = payload.get('message', '')
        elif payload_type == 'agent_message':
            role = 'assistant'
            content = payload.get('message', '')
        elif payload_type == 'function_call_output':
            role = 'tool'
            content = payload.get('output', '')
        else:
            content = payload.get('content', '')
        append(str(role or 'unknown'), content, matched_id)
    elif obj.get('type') in ('human', 'ai'):
        role = 'user' if obj.get('type') == 'human' else 'assistant'
        append(role, obj.get('content', ''), matched_id)
    return appended


def _line_offsets_from_source_refs(source_refs: Dict[str, Any], msg_ids: List[str]) -> Dict[str, Dict[str, int]]:
    raw = source_refs.get("byte_offsets") or source_refs.get("line_offsets") or {}
    if not isinstance(raw, dict):
        return {}
    wanted = set(str(mid) for mid in (msg_ids or []) if str(mid))
    result: Dict[str, Dict[str, int]] = {}
    for msg_id, value in raw.items():
        msg_id = str(msg_id or "")
        if wanted and msg_id not in wanted:
            continue
        if not isinstance(value, dict):
            continue
        try:
            start = int(value.get("start"))
            end = int(value.get("end"))
        except Exception:
            continue
        if start < 0 or end <= start:
            continue
        result[msg_id] = {"start": start, "end": end}
    return result


def _extract_bounded_raw_excerpt_by_offsets(
    resolved: Path,
    msg_ids: List[str],
    byte_offsets: Dict[str, Dict[str, int]],
    excerpt_chars: int,
) -> Tuple[str, str, str | None]:
    if not byte_offsets:
        return ('', 'offset_missing', None)
    try:
        file_size = resolved.stat().st_size
    except Exception:
        return ('', 'offset_stat_error', None)

    ordered_ids = [str(mid) for mid in (msg_ids or []) if str(mid) in byte_offsets]
    if not ordered_ids:
        ordered_ids = list(byte_offsets.keys())
    excerpt_parts: List[str] = []
    with open(resolved, "rb") as f:
        for msg_id in ordered_ids:
            pos = byte_offsets.get(msg_id, {})
            try:
                start = max(0, min(int(pos.get("start", 0)), file_size))
                end = max(start, min(int(pos.get("end", start)), file_size))
            except Exception:
                continue
            read_len = min(end - start, MAX_RAW_OFFSET_READ_BYTES)
            if read_len <= 0:
                continue
            f.seek(start)
            raw = f.read(read_len)
            text = _decode_text_bytes(raw, at_file_start=start == 0).strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except Exception:
                continue
            _append_jsonl_obj_excerpt(obj, [msg_id], excerpt_parts, set([msg_id]))
            if len(' | '.join(excerpt_parts)) >= excerpt_chars:
                break
    if not excerpt_parts:
        return ('', 'offset_cache_miss', None)
    bounded = ' | '.join(excerpt_parts)[:excerpt_chars]
    evidence_hash = hashlib.sha256(bounded.encode('utf-8')).hexdigest() if bounded else None
    return (bounded, 'raw_offset', evidence_hash)


def _build_offset_index_for_file(
    resolved: Path, msg_ids: List[str], *, deadline: float | None = None
) -> Tuple[Dict[str, Dict[str, int]], str]:
    wanted = set(str(mid) for mid in (msg_ids or []) if str(mid))
    found: Dict[str, Dict[str, int]] = {}
    if not wanted:
        return found, "offset_index_no_msg_ids"
    scanned_end = 0
    for start, end, text in _iter_decoded_jsonl_lines(resolved):
        scanned_end = max(scanned_end, int(end or 0))
        if _deadline_exceeded(deadline):
            return found, "excerpt_timeout"
        if scanned_end > _raw_offset_index_max_scan_bytes():
            return found, "offset_index_scan_limited"
        if not wanted:
            break
        text = text.strip()
        if not text or not text.startswith("{"):
            continue
        try:
            obj = json.loads(text)
        except Exception:
            continue
        candidates: List[str] = []
        msg_id = str(obj.get("id", "") or "")
        if msg_id:
            candidates.append(msg_id)
        payload = obj.get("payload", {}) if isinstance(obj.get("payload"), dict) else {}
        turn_id = str(payload.get("turn_id", "") or "")
        if turn_id:
            candidates.append(turn_id)
        timestamp = str(obj.get("timestamp", "") or "")
        if timestamp:
            candidates.append(timestamp)
        for candidate in candidates:
            if candidate in wanted:
                found[candidate] = {"start": start, "end": end}
                wanted.discard(candidate)
    return found, "offset_index_hit" if found else "offset_index_miss"


def _offsets_from_cached_index(
    resolved: Path, msg_ids: List[str], *, deadline: float | None = None
) -> Tuple[Dict[str, Dict[str, int]], str]:
    wanted = [str(mid) for mid in (msg_ids or []) if str(mid)]
    if not wanted:
        return {}, "offset_index_no_msg_ids"
    if _deadline_exceeded(deadline):
        return {}, "excerpt_timeout"
    signature = _file_signature(resolved)
    key = hashlib.sha256(str(resolved).encode("utf-8", errors="ignore")).hexdigest()
    index = _load_raw_offset_index()
    entry = index.get(key, {}) if isinstance(index.get(key), dict) else {}
    entry_sig = entry.get("file_signature", {}) if isinstance(entry.get("file_signature"), dict) else {}
    offsets = entry.get("offsets", {}) if isinstance(entry.get("offsets"), dict) else {}
    same_file = (
        entry_sig.get("inode") == signature.get("inode")
        and int(signature.get("size", 0) or 0) >= int(entry_sig.get("size", 0) or 0)
    )
    if same_file:
        cached = {}
        for msg_id in wanted:
            value = offsets.get(msg_id)
            if isinstance(value, dict) and "start" in value and "end" in value:
                cached[msg_id] = {"start": int(value["start"]), "end": int(value["end"])}
        if len(cached) == len(wanted):
            return cached, "offset_index_cache_hit"
    else:
        offsets = {}

    found, status = _build_offset_index_for_file(resolved, wanted, deadline=deadline)
    if found:
        offsets.update(found)
        index[key] = {
            "path": str(resolved),
            "file_signature": signature,
            "offsets": offsets,
            "updated_at": ts(),
        }
        _save_raw_offset_index(index)
    return found, status


def _parse_segment_objects(segment: bytes) -> List[Dict[str, Any]]:
    text = _decode_text_bytes(segment)
    objects: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            objects.append(obj)
    return objects


def _read_jsonl_segment(path: Path, offset: int, segment_bytes: int) -> Tuple[bytes, int, int]:
    try:
        file_size = path.stat().st_size
    except Exception:
        return b"", 0, 0
    if file_size <= 0:
        return b"", 0, 0
    offset = max(0, min(int(offset or 0), file_size))
    read_start = max(0, offset - RAW_SEGMENT_OVERLAP_BYTES)
    with open(path, "rb") as f:
        f.seek(read_start)
        data = f.read(segment_bytes + (offset - read_start))
        next_offset = f.tell()
    line_sep = _jsonl_line_separator_for_sample(data)
    if read_start > 0:
        first_newline = data.find(line_sep)
        if first_newline >= 0:
            data = data[first_newline + len(line_sep):]
    if next_offset < file_size:
        last_newline = data.rfind(line_sep)
        if last_newline >= 0:
            data = data[:last_newline + len(line_sep)]
            next_offset = read_start + last_newline + len(line_sep)
    return data, next_offset, file_size


def _raw_segment_request_hash(msg_ids: List[str]) -> str:
    return hashlib.sha256(
        json.dumps([str(mid) for mid in (msg_ids or []) if str(mid)], sort_keys=True).encode()
    ).hexdigest()[:16]


def _try_segment_offset(
    resolved: Path,
    offset: int,
    msg_ids: List[str],
    excerpt_chars: int,
    segment_bytes: int,
) -> Tuple[str, str, str | None]:
    segment, _, _ = _read_jsonl_segment(resolved, offset, segment_bytes)
    if not segment:
        return ('', 'segment_cache_miss', None)
    excerpt_parts: List[str] = []
    pending = set(str(mid) for mid in (msg_ids or []) if str(mid))
    for obj in _parse_segment_objects(segment):
        _append_jsonl_obj_excerpt(obj, msg_ids, excerpt_parts, pending)
        if (msg_ids and not pending) or len(' | '.join(excerpt_parts)) >= excerpt_chars:
            break
    if not excerpt_parts:
        return ('', 'segment_cache_miss', None)
    bounded = ' | '.join(excerpt_parts)[:excerpt_chars]
    evidence_hash = hashlib.sha256(bounded.encode('utf-8')).hexdigest() if bounded else None
    status = 'raw_segmented' if not pending else 'raw_partial_segmented'
    return (bounded, status, evidence_hash)


def _extract_bounded_raw_excerpt_by_cursor_segments(
    resolved: Path, msg_ids: List[str], excerpt_chars: int, deadline: float | None = None
) -> Tuple[str, str, str | None]:
    segment_bytes = _raw_segment_bytes()
    max_segments = _raw_segment_max_segments()
    signature = _file_signature(resolved)
    file_size = int(signature.get("size") or 0)
    if file_size <= 0:
        return ('', 'segment_empty', None)

    key = _raw_segment_key(resolved, msg_ids)
    request_hash = _raw_segment_request_hash(msg_ids)
    state = _load_raw_segment_state()
    prior = state.get(key, {}) if isinstance(state.get(key), dict) else {}
    prior_sig = prior.get("file_signature", {}) if isinstance(prior.get("file_signature"), dict) else {}
    same_file = (
        prior_sig.get("inode") == signature.get("inode")
        and file_size >= int(prior_sig.get("size", 0) or 0)
    )

    if same_file and prior.get("hit_offset") is not None:
        hit_offset = int(prior.get("hit_offset") or 0)
        hit_excerpt, hit_status, hit_hash = _try_segment_offset(
            resolved,
            hit_offset,
            msg_ids,
            excerpt_chars,
            segment_bytes,
        )
        if hit_excerpt:
            prior.update({
                "file_signature": signature,
                "request_hash": request_hash,
                "updated_at": ts(),
                "last_status": hit_status,
            })
            state[key] = prior
            _save_raw_segment_state(state)
            return hit_excerpt, hit_status, hit_hash

    if same_file and prior.get("exhausted") and file_size <= int(prior_sig.get("size", 0) or 0):
        prior.update({
            "file_signature": signature,
            "request_hash": request_hash,
            "updated_at": ts(),
            "last_status": "segment_exhausted",
        })
        state[key] = prior
        _save_raw_segment_state(state)
        return ('', 'segment_exhausted', None)

    offset = int(prior.get("next_offset", 0) or 0)
    if not same_file:
        offset = 0
    offset = max(0, min(offset, file_size))

    excerpt_parts: List[str] = []
    pending = set(str(mid) for mid in (msg_ids or []) if str(mid))
    segments_read = 0
    hit_offset: int | None = None

    timed_out = False
    while segments_read < max_segments:
        if _deadline_exceeded(deadline):
            timed_out = True
            break
        segment_offset = offset
        segment, next_offset, _ = _read_jsonl_segment(resolved, offset, segment_bytes)
        if not segment:
            break
        segments_read += 1
        for obj in _parse_segment_objects(segment):
            before_count = len(excerpt_parts)
            _append_jsonl_obj_excerpt(obj, msg_ids, excerpt_parts, pending)
            if len(excerpt_parts) > before_count and hit_offset is None:
                hit_offset = segment_offset
            if (not pending and msg_ids) or len(' | '.join(excerpt_parts)) >= excerpt_chars:
                break
        offset = max(next_offset, offset + 1)
        if excerpt_parts and ((not pending and msg_ids) or len(' | '.join(excerpt_parts)) >= excerpt_chars):
            break
        if next_offset >= file_size:
            offset = file_size
            break

    if not excerpt_parts:
        if timed_out:
            return ('', 'excerpt_timeout', None)
        state[key] = {
            "path": str(resolved),
            "request_hash": request_hash,
            "file_signature": signature,
            "next_offset": offset,
            "segment_bytes": segment_bytes,
            "segments_read": segments_read,
            "updated_at": ts(),
            "last_status": "segment_exhausted" if offset >= file_size else "segment_pending",
            "exhausted": offset >= file_size,
        }
        _save_raw_segment_state(state)
        return ('', 'segment_exhausted' if offset >= file_size else 'segment_pending', None)
    state[key] = {
        "path": str(resolved),
        "request_hash": request_hash,
        "file_signature": signature,
        "next_offset": offset,
        "segment_bytes": segment_bytes,
        "segments_read": segments_read,
        "updated_at": ts(),
        "last_status": "raw_segmented",
        "exhausted": False,
    }
    if hit_offset is not None:
        state[key]["hit_offset"] = hit_offset
    _save_raw_segment_state(state)
    bounded = ' | '.join(excerpt_parts)[:excerpt_chars]
    evidence_hash = hashlib.sha256(bounded.encode('utf-8')).hexdigest() if bounded else None
    return (bounded, 'raw_segmented', evidence_hash)



def _extract_bounded_raw_excerpt(
    source_path: str, msg_ids: List[str], excerpt_chars: int,
    source_refs: Dict[str, Any] | None = None, deadline_seconds: float | None = None,
) -> Tuple[str, str, str | None]:
    resolved = _resolve_source_path(source_path)
    if resolved is None or not resolved.exists():
        return ("", "missing_source_path", None)
    deadline_budget = (
        _raw_excerpt_deadline_seconds()
        if deadline_seconds is None
        else max(0.05, min(float(deadline_seconds), MAX_RAW_EXCERPT_DEADLINE_SECONDS))
    )
    deadline = time.perf_counter() + deadline_budget

    if msg_ids:
        offset_excerpt, offset_status, offset_hash = _extract_bounded_raw_excerpt_by_offsets(
            resolved,
            msg_ids,
            _line_offsets_from_source_refs(source_refs or {}, msg_ids),
            excerpt_chars,
        )
        if offset_excerpt:
            return offset_excerpt, offset_status, offset_hash

        cached_offsets, offset_index_status = _offsets_from_cached_index(resolved, msg_ids, deadline=deadline)
        if offset_index_status == "excerpt_timeout":
            return ('', 'excerpt_timeout', None)
        offset_excerpt, offset_status, offset_hash = _extract_bounded_raw_excerpt_by_offsets(
            resolved,
            msg_ids,
            cached_offsets,
            excerpt_chars,
        )
        if offset_excerpt:
            return offset_excerpt, offset_status, offset_hash
        if offset_index_status == "offset_index_scan_limited":
            return ('', 'offset_index_scan_limited', None)

        return _extract_bounded_raw_excerpt_by_cursor_segments(resolved, msg_ids, excerpt_chars, deadline=deadline)

    try:
        if resolved.stat().st_size > MAX_RAW_STREAM_SCAN_BYTES:
            return _extract_bounded_raw_excerpt_by_cursor_segments(resolved, msg_ids, excerpt_chars, deadline=deadline)
    except Exception:
        return ('', 'segment_stat_error', None)

    excerpt_parts: List[str] = []
    pending_msg_ids = set(str(mid) for mid in (msg_ids or []) if str(mid))

    def enough() -> bool:
        if pending_msg_ids:
            return False
        return bool(excerpt_parts) and len(" | ".join(excerpt_parts)) >= excerpt_chars

    try:
        for _, _, line in _iter_decoded_jsonl_lines(resolved):
            if _deadline_exceeded(deadline):
                return ('', 'excerpt_timeout', None)
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue

            _append_jsonl_obj_excerpt(obj, msg_ids, excerpt_parts, pending_msg_ids)
            if enough():
                break
        full = ' | '.join(excerpt_parts)
        bounded = full[:excerpt_chars]
        evidence_hash = hashlib.sha256(bounded.encode('utf-8')).hexdigest() if bounded else None
        return (bounded, 'raw', evidence_hash)
    except Exception:
        return ('', 'read_error', None)



__all__ = [
    "TIANDAO_RAW_EVIDENCE_EXCERPT_CONTRACT", "MAX_RAW_STREAM_SCAN_BYTES", "DEFAULT_RAW_SEGMENT_BYTES",
    "MAX_RAW_SEGMENT_BYTES", "DEFAULT_RAW_SEGMENT_MAX_SEGMENTS", "MAX_RAW_SEGMENT_MAX_SEGMENTS",
    "RAW_SEGMENT_OVERLAP_BYTES", "MAX_RAW_OFFSET_READ_BYTES", "DEFAULT_RAW_EXCERPT_DEADLINE_SECONDS",
    "MAX_RAW_EXCERPT_DEADLINE_SECONDS", "FORBIDDEN_STATE_DIR_PARTS", "get_raw_evidence_excerpt_contract",
    "_safe_int", "_safe_env_int", "_raw_segment_bytes", "_raw_segment_max_segments",
    "_raw_excerpt_deadline_seconds", "_deadline_exceeded", "_is_safe_relative_source_path",
    "_project_root", "_resolve_path_for_guard", "_is_path_inside", "_raw_gateway_state_allowed_roots",
    "_is_safe_raw_gateway_state_dir", "_raw_segment_state_dir", "_raw_segment_state_path",
    "_raw_offset_index_path", "_load_raw_segment_state", "_save_raw_segment_state",
    "_load_raw_offset_index", "_save_raw_offset_index", "_file_signature", "_raw_segment_key",
    "_allowed_source_roots", "_is_under_allowed_root", "_resolve_source_path", "_extract_content_text",
    "_append_jsonl_obj_excerpt", "_line_offsets_from_source_refs", "_extract_bounded_raw_excerpt_by_offsets",
    "_build_offset_index_for_file", "_offsets_from_cached_index", "_parse_segment_objects",
    "_read_jsonl_segment", "_raw_segment_request_hash", "_try_segment_offset",
    "_extract_bounded_raw_excerpt_by_cursor_segments", "_extract_bounded_raw_excerpt",
]
