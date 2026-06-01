#!/usr/bin/env python3
"""
memcore-cloud P0: 主入口
支持两种模式：
  --scan    批量扫描（已有 session 归档）
  --watch   inotify 实时监听新 session
"""
import os, sys, json, glob, argparse, shutil, time, signal
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from p2_extract import incremental_extract_session
from config_loader import openclaw_agents, memory_root, checkpoint_file, alias_map, node_id
try:
    from src.raw_archive_layout import preferred_raw_archive_path
except ImportError:
    from raw_archive_layout import preferred_raw_archive_path

UTC = timezone.utc

OPENCLAW_ROOT = openclaw_agents()
MEMCORE_ROOT = memory_root()
CHECKPOINT_FILE = checkpoint_file()
ALIAS_MAP_FILE = alias_map()

SOURCE_SYSTEM = "openclaw"
NATIVE_ARTIFACT_FORMAT = "openclaw_session_jsonl"
HOSTNAME = node_id()
DIALOG_ENTRY_OPENCLAW_EVENT_URL = os.environ.get(
    "MEMCORE_DIALOG_ENTRY_OPENCLAW_EVENT_URL",
    "http://127.0.0.1:9860/entry/openclaw-event",
)
try:
    OPENCLAW_EVENT_DELIVERY_TIMEOUT = max(
        5,
        min(int(os.environ.get("MEMCORE_OPENCLAW_EVENT_DELIVERY_TIMEOUT", "180")), 300),
    )
except ValueError:
    OPENCLAW_EVENT_DELIVERY_TIMEOUT = 180
OPENCLAW_EVENT_DELIVERED_KEY = "openclaw_entry_delivered_event_ids"
OPENCLAW_EVENT_PENDING_KEY = "openclaw_entry_pending_events"
OPENCLAW_EVENT_FRESH_ARCHIVE_SECONDS = 30

# ─── alias_map ───────────────────────────────────────────────

def load_alias_map():
    if not os.path.exists(ALIAS_MAP_FILE):
        return {}
    with open(ALIAS_MAP_FILE, encoding="utf-8-sig") as f:
        data = json.load(f)
    m = {}
    for canon, info in data.get("canonical_windows", {}).items():
        for obs in info.get("observed_names", []):
            m[obs] = canon
    return m

def get_canonical(observed):
    static_map = load_alias_map()
    if observed in static_map:
        return static_map[observed]
    if observed.startswith("group-"):
        parts = observed.split("--")
        if len(parts) >= 2:
            return parts[-1]
    return observed

def _agent_session_from_path(src_path):
    src = Path(src_path)
    try:
        rel = src.resolve().relative_to(Path(OPENCLAW_ROOT).resolve())
        parts = rel.parts
        if len(parts) >= 3 and parts[1] == "sessions":
            agent_dir = parts[0]
        else:
            raise ValueError("unexpected OpenClaw session path")
    except Exception:
        normalized = str(src_path).replace("\\", "/")
        agent_dir = normalized.split("/agents/")[1].split("/sessions")[0]
    session_id = os.path.basename(src_path).replace(".jsonl", "")
    return agent_dir, session_id

def _raw_dest_for_openclaw(canonical_window, session_id):
    return str(preferred_raw_archive_path(
        MEMCORE_ROOT,
        computer_name=HOSTNAME,
        source_system=SOURCE_SYSTEM,
        native_format=NATIVE_ARTIFACT_FORMAT,
        native_scope=canonical_window,
        session_id=session_id,
    ))

def _openclaw_event_message_text(event):
    message = event.get("message", {}) if isinstance(event, dict) else {}
    if not isinstance(message, dict):
        return ""
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") in ("text", "input_text"):
            parts.append(str(item.get("text", "")))
    return "\n".join(parts)

def _is_openclaw_gateway_client_event(event):
    text = _openclaw_event_message_text(event).lstrip()
    if not text.startswith("Sender (untrusted metadata):"):
        return False
    head = text[:600]
    compact = head.replace(" ", "")
    return '"id":"gateway-client"' in compact or '"label":"gateway-client"' in compact

# ─── checkpoint ─────────────────────────────────────────────

def load_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return {}
    with open(CHECKPOINT_FILE, encoding="utf-8-sig") as f:
        return json.load(f)

def save_checkpoint(data):
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def _checkpoint_delivered_ids(src_path):
    entry = load_checkpoint().get(src_path, {})
    ids = entry.get(OPENCLAW_EVENT_DELIVERED_KEY, [])
    return set(ids if isinstance(ids, list) else [])

def _checkpoint_pending_events(src_path):
    entry = load_checkpoint().get(src_path, {})
    pending = entry.get(OPENCLAW_EVENT_PENDING_KEY, [])
    return pending if isinstance(pending, list) else []

def _mark_checkpoint_delivered(src_path, event_key):
    checkpoint = load_checkpoint()
    entry = checkpoint.get(src_path, {})
    ids = entry.get(OPENCLAW_EVENT_DELIVERED_KEY, [])
    if not isinstance(ids, list):
        ids = []
    if event_key not in ids:
        ids.append(event_key)
    entry[OPENCLAW_EVENT_DELIVERED_KEY] = ids[-500:]
    checkpoint[src_path] = entry
    save_checkpoint(checkpoint)

def _mark_checkpoint_pending(src_path, item, response=None, error=""):
    checkpoint = load_checkpoint()
    entry = checkpoint.get(src_path, {})
    pending = entry.get(OPENCLAW_EVENT_PENDING_KEY, [])
    if not isinstance(pending, list):
        pending = []
    response = response if isinstance(response, dict) else {}
    event_key = item.get("event_key", "")
    existing = next((p for p in pending if p.get("event_key") == event_key), {})
    record = {
        "event_key": event_key,
        "event_id": item.get("event_id", ""),
        "source_session_id": item.get("source_session_id", ""),
        "agent_id": item.get("agent_id", ""),
        "attempts": int(existing.get("attempts", 0) or 0) + 1,
        "last_status": response.get("status", ""),
        "last_chain": response.get("chain", ""),
        "last_reason": response.get("reason", ""),
        "last_error": error,
        "last_update": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    pending = [p for p in pending if p.get("event_key") != event_key]
    pending.append(record)
    entry[OPENCLAW_EVENT_PENDING_KEY] = pending[-500:]
    checkpoint[src_path] = entry
    save_checkpoint(checkpoint)

def _clear_checkpoint_pending(src_path, event_key):
    checkpoint = load_checkpoint()
    entry = checkpoint.get(src_path, {})
    pending = entry.get(OPENCLAW_EVENT_PENDING_KEY, [])
    if not isinstance(pending, list):
        return
    filtered = [p for p in pending if p.get("event_key") != event_key]
    if filtered:
        entry[OPENCLAW_EVENT_PENDING_KEY] = filtered[-500:]
    else:
        entry.pop(OPENCLAW_EVENT_PENDING_KEY, None)
    checkpoint[src_path] = entry
    save_checkpoint(checkpoint)

def _openclaw_event_delivery_terminal(response):
    response = response if isinstance(response, dict) else {}
    status = str(response.get("status", ""))
    if status in ("blocked", "error"):
        return False
    openclaw = response.get("openclaw", {})
    if response.get("chain") == "F3_zhiyi_direct" and isinstance(openclaw, dict):
        if openclaw and not openclaw.get("ok", False):
            return False
    platform_delivery = response.get("platform_delivery", {})
    if isinstance(platform_delivery, dict):
        if platform_delivery.get("executed") and not platform_delivery.get("openclaw_ok", False):
            return False
    return bool(status)

def _iter_pending_openclaw_user_events(src_path):
    pending = _checkpoint_pending_events(src_path)
    if not pending:
        return []
    wanted = {p.get("event_id"): p for p in pending if p.get("event_id")}
    if not wanted:
        return []
    found = {}
    try:
        with open(src_path, "rb") as f:
            for raw_line in f:
                if not raw_line.strip():
                    continue
                try:
                    event = json.loads(raw_line.decode("utf-8"))
                except Exception:
                    continue
                event_id = str(event.get("id") or "")
                if event_id not in wanted:
                    continue
                message = event.get("message", {})
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                if _is_openclaw_gateway_client_event(event):
                    continue
                pending_item = wanted[event_id]
                found[event_id] = {
                    "event_key": pending_item.get("event_key", ""),
                    "event_id": event_id,
                    "event": event,
                    "agent_id": pending_item.get("agent_id", ""),
                    "source_session_id": pending_item.get("source_session_id", ""),
                    "retry_pending": True,
                }
    except OSError:
        return []
    return [found[p.get("event_id")] for p in pending if p.get("event_id") in found]

def _iter_openclaw_user_events(src_path, prior_offset=0, status="", now=None):
    if status in ("up_to_date", "empty_append") or not status:
        return []
    if ".trajectory." in os.path.basename(src_path):
        return []

    try:
        src_stat = os.stat(src_path)
    except OSError:
        return []

    start_offset = max(0, int(prior_offset or 0))
    if start_offset == 0 and status == "archived":
        current_ts = time.time() if now is None else now
        if current_ts - src_stat.st_mtime > OPENCLAW_EVENT_FRESH_ARCHIVE_SECONDS:
            return []

    agent_dir, session_id = _agent_session_from_path(src_path)
    only_latest_user = start_offset == 0 and (status == "archived" or status.startswith("rotation"))
    events = []
    with open(src_path, "rb") as f:
        if start_offset and start_offset <= src_stat.st_size:
            f.seek(start_offset)
        else:
            start_offset = 0
        cursor = start_offset
        for raw_line in f:
            line_offset = cursor
            cursor += len(raw_line)
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except Exception:
                continue
            if event.get("type") != "message":
                continue
            message = event.get("message", {})
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            if _is_openclaw_gateway_client_event(event):
                continue
            event_id = str(event.get("id") or f"{session_id}:{line_offset}")
            events.append({
                "event_key": f"{session_id}:{event_id}",
                "event_id": event_id,
                "event": event,
                "agent_id": agent_dir,
                "source_session_id": session_id,
            })
    if only_latest_user and events:
        return events[-1:]
    return events

def deliver_openclaw_native_events(
    src_path,
    prior_offset=0,
    status="",
    url=None,
    timeout=OPENCLAW_EVENT_DELIVERY_TIMEOUT,
    now=None,
):
    """Send newly appended OpenClaw user message events to the 9860 native entry."""
    url = url or DIALOG_ENTRY_OPENCLAW_EVENT_URL
    delivered_ids = _checkpoint_delivered_ids(src_path)
    result = {
        "attempted": 0,
        "delivered": 0,
        "pending": 0,
        "retried_pending": 0,
        "skipped_duplicate": 0,
        "responses": [],
        "errors": [],
    }
    items = []
    seen = set()
    for item in _iter_pending_openclaw_user_events(src_path):
        if item["event_key"] not in seen:
            items.append(item)
            seen.add(item["event_key"])
    for item in _iter_openclaw_user_events(src_path, prior_offset, status, now=now):
        if item["event_key"] not in seen:
            items.append(item)
            seen.add(item["event_key"])
    for item in items:
        event_key = item["event_key"]
        if event_key in delivered_ids:
            _clear_checkpoint_pending(src_path, event_key)
            result["skipped_duplicate"] += 1
            continue
        payload = {
            "event": item["event"],
            "event_id": item["event_id"],
            "source_session_id": item["source_session_id"],
            "agent_id": item["agent_id"],
        }
        result["attempted"] += 1
        if item.get("retry_pending"):
            result["retried_pending"] += 1
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                http_status = getattr(resp, "status", None) or getattr(resp, "code", None)
            try:
                response = json.loads(body.decode("utf-8"))
            except Exception:
                response = {}
            terminal = _openclaw_event_delivery_terminal(response)
            result["responses"].append({
                "event_id": item["event_id"],
                "http_status": http_status,
                "status": response.get("status", ""),
                "chain": response.get("chain", ""),
                "reason": response.get("reason", ""),
                "openclaw_ok": response.get("openclaw", {}).get("ok") if isinstance(response.get("openclaw"), dict) else None,
                "terminal": terminal,
                "pending_retry": not terminal,
            })
            if terminal:
                _mark_checkpoint_delivered(src_path, event_key)
                _clear_checkpoint_pending(src_path, event_key)
                delivered_ids.add(event_key)
                result["delivered"] += 1
            else:
                _mark_checkpoint_pending(src_path, item, response=response)
                result["pending"] += 1
        except Exception as e:
            err = str(e)
            result["errors"].append(err)
            _mark_checkpoint_pending(src_path, item, error=err)
            result["pending"] += 1
    return result

# ─── sidecar metadata ─────────────────────────────────────

def _write_meta(dest, src_path, src_stat, offset, raw_order):
    """写 raw 文件的 sidecar metadata"""
    dest_meta = dest + ".meta.json"
    with open(src_path, "rb") as f:
        data = f.read()
    checksum = hex(sum(data) % (2**64))
    meta = {
        "source_path": src_path,
        "source_inode": src_stat.st_ino,
        "source_mtime": src_stat.st_mtime,
        "source_checksum": checksum,
        "file_offset": offset,
        "raw_order": raw_order,
        "archived_to": dest,
        "source_system": SOURCE_SYSTEM,
        "native_artifact_format": NATIVE_ARTIFACT_FORMAT,
        "raw_archive_layout": "computer_first",
        "last_update": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(dest_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return dest_meta

# ─── archive one session ──────────────────────────────────

def archive_session_incremental(src_path, dry_run=False):
    """增量归档：只追加新行，不重复复制整个文件。

    checkpoint 记录每个 source 文件已处理的字节偏移、source inode/mtime，
    用于 rotation 检测；每次追加后写 .meta.json sidecar。
    """
    agent_dir, session_id = _agent_session_from_path(src_path)
    canonical_window = get_canonical(agent_dir)
    dest = _raw_dest_for_openclaw(canonical_window, session_id)

    checkpoint = load_checkpoint()
    prior = checkpoint.get(src_path, {})
    last_offset = prior.get("offset", 0)

    if dry_run:
        src_size = os.path.getsize(src_path)
        return dest, f"dry_run(offset={last_offset}/{src_size})"

    try:
        src_stat = os.stat(src_path)
        src_size = src_stat.st_size
        src_inode = src_stat.st_ino
        src_mtime = src_stat.st_mtime
    except OSError:
        return dest, "error: cannot stat source"

    # 判断是否有新内容，或文件被轮换（inode 变化）
    is_rotation = prior and prior.get("source_inode") != src_inode

    if src_size <= last_offset and not is_rotation:
        # 没有新内容，且文件未被替换
        return dest, f"up_to_date(offset={last_offset})"

    if is_rotation:
        # 文件轮换（truncate/rotation），从头开始
        last_offset = 0
        raw_order = prior.get("raw_order", 0) + 1
        msg = f"rotation_detected(inode changed, {raw_order}th archive)"
    else:
        # 读取新增内容
        with open(src_path, "rb") as f:
            f.seek(last_offset)
            new_bytes = f.read()
            new_offset = f.tell()

        if not new_bytes.strip():
            return dest, f"empty_append(offset={new_offset})"

        # 追加写入目标
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "ab") as f:
            f.write(new_bytes)

        # 部分 checksum（仅新增部分）
        checksum = hex(sum(new_bytes) % (2**64))
        new_lines = new_bytes.count(b"\n")
        msg = f"appended({new_lines} lines, {len(new_bytes)} bytes, {last_offset}→{new_offset})"
        last_offset = new_offset
        raw_order = prior.get("raw_order", 0)

    delivered_ids = prior.get(OPENCLAW_EVENT_DELIVERED_KEY, [])
    pending_events = prior.get(OPENCLAW_EVENT_PENDING_KEY, [])
    # 更新 checkpoint（含 source inode/mtime 用于 rotation 检测）
    entry = {
        "offset": last_offset,
        "archived_to": dest,
        "source_inode": src_inode,
        "source_size": src_stat.st_size,
        "source_mtime": src_mtime,
        "source_checksum": checksum if not is_rotation else None,
        "raw_order": raw_order,
        "last_update": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if isinstance(delivered_ids, list):
        entry[OPENCLAW_EVENT_DELIVERED_KEY] = delivered_ids[-500:]
    if isinstance(pending_events, list):
        entry[OPENCLAW_EVENT_PENDING_KEY] = pending_events[-500:]
    checkpoint[src_path] = entry
    save_checkpoint(checkpoint)

    # 写 sidecar metadata
    _write_meta(dest, src_path, src_stat, last_offset, raw_order)

    return dest, msg


def archive_session(src_path, dry_run=False):
    """兼容旧接口：首次全量归档（copy），后续增量追加。"""
    agent_dir, session_id = _agent_session_from_path(src_path)
    canonical_window = get_canonical(agent_dir)
    dest = _raw_dest_for_openclaw(canonical_window, session_id)

    if os.path.exists(dest):
        # 已有完整副本，走增量追加
        return archive_session_incremental(src_path, dry_run=dry_run)

    # 首次全量 copy（不用 hardlink）
    if dry_run:
        return dest, "dry_run"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src_path, dest)

    # 初始化 checkpoint（含 source inode/mtime）
    src_stat = os.stat(src_path)
    checkpoint = load_checkpoint()
    prior = checkpoint.get(src_path, {})
    delivered_ids = prior.get(OPENCLAW_EVENT_DELIVERED_KEY, [])
    pending_events = prior.get(OPENCLAW_EVENT_PENDING_KEY, [])
    raw_order = 1
    entry = {
        "offset": src_stat.st_size,
        "archived_to": dest,
        "source_inode": src_stat.st_ino,
        "source_mtime": src_stat.st_mtime,
        "source_checksum": None,
        "raw_order": raw_order,
        "last_update": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if isinstance(delivered_ids, list):
        entry[OPENCLAW_EVENT_DELIVERED_KEY] = delivered_ids[-500:]
    if isinstance(pending_events, list):
        entry[OPENCLAW_EVENT_PENDING_KEY] = pending_events[-500:]
    checkpoint[src_path] = entry
    save_checkpoint(checkpoint)

    # 写 sidecar metadata
    _write_meta(dest, src_path, src_stat, src_stat.st_size, raw_order)

    return dest, "archived"

# ─── batch scan ────────────────────────────────────────────

def _source_enabled(args, source_system):
    wanted = getattr(args, "source", "all") or "all"
    return wanted in ("all", source_system)

def cmd_scan(args):
    total_archived = 0
    if _source_enabled(args, "openclaw"):
        os.makedirs(OPENCLAW_ROOT, exist_ok=True)
        for agent_dir in sorted(os.listdir(OPENCLAW_ROOT)):
            sessions_dir = os.path.join(OPENCLAW_ROOT, agent_dir, "sessions")
            if not os.path.isdir(sessions_dir):
                continue
            for sf in sorted(glob.glob(os.path.join(sessions_dir, "*.jsonl"))):
                session_id = os.path.basename(sf).replace(".jsonl", "")
                if ".checkpoint." in session_id:
                    continue
                dest, status = archive_session(sf, dry_run=args.dry_run)
                if status == "archived":
                    total_archived += 1
                    print(f"  [openclaw archived] {agent_dir} → {get_canonical(agent_dir)}/{session_id[:8]}")
                elif status == "exists":
                    pass
                if not args.dry_run and dest and status not in ("up_to_date", "empty_append"):
                    try:
                        pn, cn, en = incremental_extract_session(dest)
                        if pn or cn or en:
                            print(f"  [p2] pref={pn} case={cn} error={en}")
                    except Exception as e:
                        print(f"  [p2 error] {e}")

    if _source_enabled(args, "codex"):
        try:
            from codex_local_connector import scan_sessions as scan_codex_sessions
            result = scan_codex_sessions(dry_run=args.dry_run)
            if args.dry_run:
                total_archived += int(result.get("would_change", 0) or 0)
            for item in result.get("items", []):
                status = item.get("status", "")
                if status.startswith(("archived", "appended", "rotation")):
                    total_archived += 1
                    print(f"  [codex {status.split('(')[0]}] {item.get('canonical_window_id','')}/{item.get('session_id','')[:8]}")
                    if not args.dry_run:
                        try:
                            pn, cn, en = incremental_extract_session(item["dest"])
                            if pn or cn or en:
                                print(f"  [p2 codex] pref={pn} case={cn} error={en}")
                        except Exception as e:
                            print(f"  [p2 codex error] {e}")
        except Exception as e:
            print(f"  [codex scan error] {e}")

    if args.dry_run:
        print(f"[scan dry-run] source={getattr(args, 'source', 'all')} would archive/update {total_archived} sessions")
    else:
        print(f"[scan] source={getattr(args, 'source', 'all')} archived/updated {total_archived} sessions")

# ─── inotify watcher ──────────────────────────────────────

def cmd_watch(args):
    if _source_enabled(args, "codex") and getattr(args, "source", "all") != "openclaw":
        print("[memcore-cloud] codex source enabled; using poll mode for mixed source watching")
        return watch_poll(args)

    try:
        import inotify.adapters
    except ImportError:
        print("[memcore-cloud] inotify not available on this system (requires Linux)")
        print("[memcore-cloud] falling back to poll mode (5s interval)")
        return watch_poll(args)

    print(f"[memcore-cloud] watching {OPENCLAW_ROOT} (recursive)")
    i = inotify.adapters.Inotify()

    # 递归监听所有现有子目录
    watched = set()
    for root, dirs, files in os.walk(OPENCLAW_ROOT):
        for d in dirs:
            subdir = os.path.join(root, d)
            try:
                i.add_watch(subdir)
                watched.add(subdir)
            except Exception:
                pass
    # 监听根目录本身（捕捉顶层新建目录）
    try:
        i.add_watch(OPENCLAW_ROOT)
        watched.add(OPENCLAW_ROOT)
    except Exception:
        pass

    for event in i.event_gen(yield_nones=False):
        (header, type_names, path, filename) = event

        # 处理新建目录事件：新 agent/sessions 目录出现时立即接管
        if "IN_CREATE" in type_names and "IN_ISDIR" in type_names:
            new_dir = os.path.join(path, filename)
            if new_dir not in watched:
                try:
                    i.add_watch(new_dir)
                    watched.add(new_dir)
                    print(f"  [watch added] {new_dir}")
                except Exception:
                    pass
            continue

        # 忽略非 .jsonl 文件事件
        if not filename or not filename.endswith(".jsonl") or ".checkpoint." in filename:
            continue

        # 只处理写入完成或移动完成的 .jsonl 文件
        if "IN_CLOSE_WRITE" not in type_names and "IN_MOVED_TO" not in type_names:
            continue

        sf = os.path.join(path, filename)
        prior_offset = load_checkpoint().get(sf, {}).get("offset", 0)
        dest, status = archive_session(sf)
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        if status == "archived":
            print(f"  [{ts}] [archived] {filename}")
        elif status == "exists":
            print(f"  [{ts}] [exists]  {filename}")
        elif status.startswith("appended") or status.startswith("rotation"):
            print(f"  [{ts}] [{status.split('(')[0]}] {filename}")

        delivery = deliver_openclaw_native_events(sf, prior_offset, status)
        if delivery["attempted"] or delivery["errors"]:
            statuses = ",".join(r.get("status", "") for r in delivery.get("responses", [])[:3]) or "-"
            print(f"  [{ts}] [entry] delivered={delivery['delivered']} statuses={statuses} errors={len(delivery['errors'])}")

        # P2 incremental extraction (real-time, runs after every archive)
        if dest and status not in ("up_to_date", "empty_append"):
            try:
                pn, cn, en = incremental_extract_session(dest)
                if pn or cn or en:
                    print(f"  [{ts}] [p2] pref={pn} case={cn} error={en}")
            except Exception as e:
                print(f"  [{ts}] [p2 error] {e}")

def watch_poll(args):
    """poll fallback：每 5s 扫描一次，处理所有 session 的增量追加。"""
    print(f"[memcore-cloud] poll mode: source={getattr(args, 'source', 'all')} checking every 5s")
    if _source_enabled(args, "openclaw"):
        os.makedirs(OPENCLAW_ROOT, exist_ok=True)
    while True:
        if _source_enabled(args, "openclaw"):
            for agent_dir in sorted(os.listdir(OPENCLAW_ROOT)):
                sessions_dir = os.path.join(OPENCLAW_ROOT, agent_dir, "sessions")
                if not os.path.isdir(sessions_dir):
                    continue
                for sf in sorted(glob.glob(os.path.join(sessions_dir, "*.jsonl"))):
                    session_id = os.path.basename(sf).replace(".jsonl", "")
                    if ".checkpoint." in session_id:
                        continue
                    # 关键：已知 session 也调用 archive_session（增量追加走 archive_session_incremental）
                    prior_offset = load_checkpoint().get(sf, {}).get("offset", 0)
                    dest, status = archive_session(sf)
                    ts_now = datetime.now(UTC).strftime("%H:%M:%S")
                    if status == "archived":
                        print(f"  [{ts_now}] [openclaw archived] {agent_dir}/{session_id[:8]}")
                    elif status.startswith("appended") or status.startswith("rotation"):
                        print(f"  [{ts_now}] [openclaw {status.split('(')[0]}] {agent_dir}/{session_id[:8]}")

                    delivery = deliver_openclaw_native_events(sf, prior_offset, status)
                    if delivery["attempted"] or delivery["errors"]:
                        statuses = ",".join(r.get("status", "") for r in delivery.get("responses", [])[:3]) or "-"
                        print(f"  [{ts_now}] [entry] delivered={delivery['delivered']} statuses={statuses} errors={len(delivery['errors'])}")

                    # P2 incremental extraction (real-time)
                    if dest and status not in ("up_to_date", "empty_append"):
                        try:
                            pn, cn, en = incremental_extract_session(dest)
                            if pn or cn or en:
                                print(f"  [{ts_now}] [p2] pref={pn} case={cn} error={en}")
                        except Exception as e:
                            print(f"  [{ts_now}] [p2 error] {e}")

        if _source_enabled(args, "codex"):
            try:
                from codex_local_connector import scan_sessions as scan_codex_sessions
                result = scan_codex_sessions(dry_run=False)
                ts_now = datetime.now(UTC).strftime("%H:%M:%S")
                for item in result.get("items", []):
                    status = item.get("status", "")
                    if not status.startswith(("archived", "appended", "rotation")):
                        continue
                    print(f"  [{ts_now}] [codex {status.split('(')[0]}] {item.get('canonical_window_id','')}/{item.get('session_id','')[:8]}")
                    try:
                        pn, cn, en = incremental_extract_session(item["dest"])
                        if pn or cn or en:
                            print(f"  [{ts_now}] [p2 codex] pref={pn} case={cn} error={en}")
                    except Exception as e:
                        print(f"  [{ts_now}] [p2 codex error] {e}")
            except Exception as e:
                ts_now = datetime.now(UTC).strftime("%H:%M:%S")
                print(f"  [{ts_now}] [codex scan error] {e}")
        time.sleep(5)

# ─── main ──────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="memcore-cloud P0")
    p.add_argument("--scan", action="store_true", help="批量扫描已有 session")
    p.add_argument("--watch", action="store_true", help="实时监听新 session（inotify）")
    p.add_argument("--dry-run", action="store_true", help="干跑不写入")
    p.add_argument("--source", choices=["all", "openclaw", "codex"], default="all", help="source system to scan/watch")
    args = p.parse_args()

    if args.watch:
        cmd_watch(args)
    elif args.scan:
        cmd_scan(args)
    else:
        p.print_help()

if __name__ == "__main__":
    main()
