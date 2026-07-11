#!/usr/bin/env python3
"""
Time Library P1: 原始回查增强查询工具
支持:
  --timeline YYYY-MM-DD      按日期查 session
  --window WINDOW            按 canonical window 查
  --channel CHANNEL          按 channel 查 (openclaw/webchat/telegram/feishu/qq)
  --search QUERY             关键词全文搜索
  --session-id SID           精确查单条 session
  --list-windows             列出所有 canonical windows
  --explain SID              解释单条 session 的关键内容
"""
import os, json, glob, argparse
from datetime import datetime, timezone
from collections import defaultdict

from config_loader import memory_root, raw_memory_subpath
MEMCORE_ROOT = os.path.join(memory_root(), raw_memory_subpath())

# ─── 加载索引 ───────────────────────────────────────

def load_timeline():
    path = os.path.join(MEMCORE_ROOT, ".timeline_index.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None

def load_channels():
    path = os.path.join(MEMCORE_ROOT, ".channel_index.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f).get("channels", {})
    return {}

def load_alias_map():
    from config_loader import alias_map as _alias_map_path
    path = _alias_map_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

# ─── 工具函数 ─────────────────────────────────────

def ts_to_date(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

# ─── 查询模式 ─────────────────────────────────────

def cmd_list_windows(args):
    timeline = load_timeline()
    alias_map = load_alias_map()
    windows = defaultdict(int)
    for s in timeline.get("sessions", []):
        windows[s["canonical_window"]] += 1
    print(f"\ncanonical windows ({len(windows)} 个):")
    print(f"{'window':<20} {'sessions':<10} {'alias':<20}")
    print("-" * 52)
    am = alias_map.get("canonical_windows", {})
    for w, cnt in sorted(windows.items()):
        aliases = am.get(w, {}).get("observed_names", [])
        print(f"{w:<20} {cnt:<10} {','.join(aliases[:2]):<20}")
    return windows

def cmd_timeline(args):
    timeline = load_timeline()
    if not timeline:
        print("[p1] timeline 索引不存在，请先运行 --rebuild-index")
        return
    target_date = args.timeline
    results = []
    for s in timeline.get("sessions", []):
        if ts_to_date(s["archived_at_ts"]) == target_date:
            results.append(s)
    print(f"\n=== {target_date} 的 sessions ({len(results)} 个) ===")
    for r in results:
        print(f"  [{r['canonical_window']}] {r['session_id'][:16]}...  size={r['file_size']//1024}KB")
    return results

def cmd_window(args):
    timeline = load_timeline()
    if not timeline:
        print("[p1] timeline 索引不存在")
        return
    results = [s for s in timeline.get("sessions", []) if s["canonical_window"] == args.window]
    print(f"\n=== window={args.window} ({len(results)} sessions) ===")
    for r in results:
        print(f"  {r['session_id'][:32]}  archived={r['archived_at']}  {r['file_size']//1024}KB")
    return results

def cmd_channel(args):
    channels = load_channels()
    timeline = load_timeline()
    if not timeline:
        print("[p1] timeline 索引不存在")
        return
    results = []
    for s in timeline.get("sessions", []):
        sid = s["session_id"]
        ch = channels.get(sid, {}).get("channel", "unknown")
        if ch == args.channel:
            results.append((s, ch))
    print(f"\n=== channel={args.channel} ({len(results)} sessions) ===")
    for s, ch in results:
        print(f"  [{s['canonical_window']}] {s['session_id'][:32]}")
    return results

def cmd_search(args):
    timeline = load_timeline()
    if not timeline:
        print("[p1] timeline 索引不存在")
        return
    query_lower = args.search.lower()
    results = []
    for s in timeline.get("sessions", []):
        sf = s["file_path"]
        if not os.path.exists(sf):
            continue
        try:
            with open(sf) as f:
                content = f.read()
                if query_lower in content.lower():
                    # 找匹配片段
                    lines = content.split("\n")
                    snippet = ""
                    for line in lines:
                        if query_lower in line.lower():
                            try:
                                rec = json.loads(line.strip())
                                msg = rec.get("message", {})
                                c = msg.get("content", "")
                                if isinstance(c, list):
                                    c = " ".join(x.get("text","") for x in c if isinstance(x,dict))
                                if c and len(c) > 10:
                                    snippet = c[:150].replace("\n"," ")
                                    break
                            except: pass
                    results.append((s, snippet))
        except: pass
    print(f"\n=== search=\"{args.search}\" ({len(results)} 个 session 含匹配) ===")
    for s, snippet in results[:5]:
        print(f"  [{s['canonical_window']}] {s['session_id'][:16]}")
        if snippet:
            print(f"    → {snippet[:120]}")
    return results

def cmd_explain(args):
    timeline = load_timeline()
    channels = load_channels()
    if not timeline:
        print("[p1] timeline 索引不存在")
        return
    sessions = {s["session_id"]: s for s in timeline.get("sessions", [])}
    if args.session_id not in sessions:
        print(f"[p1] session_id={args.session_id} 不在索引中")
        return
    s = sessions[args.session_id]
    sf = s["file_path"]
    ch = channels.get(args.session_id, {}).get("channel", "unknown")
    print(f"\n=== session 解释 ===")
    print(f"  session_id:      {s['session_id']}")
    print(f"  canonical_window: {s['canonical_window']}")
    print(f"  channel:         {ch}")
    print(f"  archived_at:     {s['archived_at']}")
    print(f"  file_size:       {s['file_size']//1024} KB")
    print(f"  file_path:       {sf}")
    if not os.path.exists(sf):
        print("[p1] 文件不存在")
        return
    # 提取关键内容片段
    msg_count = 0
    assistant_msgs = []
    user_msgs = []
    with open(sf) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                rec = json.loads(line)
                if rec.get("type") == "message":
                    msg = rec.get("message", {})
                    role = msg.get("role", "?")
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(x.get("text","") for x in content if isinstance(x,dict))
                    if content and len(content) > 20:
                        if role == "assistant":
                            assistant_msgs.append(content[:200])
                        elif role == "user":
                            user_msgs.append(content[:200])
                    msg_count += 1
            except: pass
    print(f"  message_count:   {msg_count}")
    print(f"  user_msgs:       {len(user_msgs)}")
    print(f"  assistant_msgs:  {len(assistant_msgs)}")
    if assistant_msgs:
        print(f"  最新 assistant 回复:")
        print(f"    {assistant_msgs[-1][:150]}")
    if user_msgs:
        print(f"  最新 user 消息:")
        print(f"    {user_msgs[-1][:150]}")
    # alias map
    alias_map = load_alias_map()
    am = alias_map.get("canonical_windows", {}).get(s["canonical_window"], {})
    if am:
        print(f"  observed_names:  {', '.join(am.get('observed_names', []))}")
    print()

def cmd_rebuild_index(args):
    timeline = []
    for window in sorted(os.listdir(MEMCORE_ROOT)):
        wp = os.path.join(MEMCORE_ROOT, window)
        if not os.path.isdir(wp): continue
        for sf in sorted(glob.glob(os.path.join(wp, "*.jsonl"))):
            sid = os.path.basename(sf).replace(".jsonl", "")
            stat = os.stat(sf)
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            timeline.append({
                "session_id": sid,
                "canonical_window": window,
                "file_path": sf,
                "archived_at_ts": stat.st_mtime,
                "archived_at": mtime.strftime("%Y-%m-%d %H:%M:%S"),
                "file_size": stat.st_size,
            })
    idx = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "total_sessions": len(timeline),
        "sessions": sorted(timeline, key=lambda x: x["archived_at_ts"])
    }
    with open(os.path.join(MEMCORE_ROOT, ".timeline_index.json"), "w") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    print(f"[p1] timeline_index 已重建: {len(timeline)} sessions")

    # channel 检测
    CHANNEL_KW = {
        "telegram": ["telegram","TG_","chat_id"],
        "webchat": ["webchat","openclaw-control-ui"],
        "feishu": ["feishu","飞书","lark"],
        "qq": ["qqbot","qq_"],
        "discord": ["discord"],
    }
    channels = {}
    for window in sorted(os.listdir(MEMCORE_ROOT)):
        wp = os.path.join(MEMCORE_ROOT, window)
        if not os.path.isdir(wp): continue
        for sf in sorted(glob.glob(os.path.join(wp, "*.jsonl"))):
            sid = os.path.basename(sf).replace(".jsonl", "")
            detected = "openclaw"
            try:
                with open(sf) as f:
                    sample = f.read(4096)
                    for ch, kws in CHANNEL_KW.items():
                        if any(kw in sample for kw in kws):
                            detected = ch
                            break
            except: pass
            channels[sid] = {"channel": detected, "window": window}
    with open(os.path.join(MEMCORE_ROOT, ".channel_index.json"), "w") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "channels": channels}, f, ensure_ascii=False, indent=2)
    print(f"[p1] channel_index 已重建: {len(channels)} sessions")

# ─── main ──────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Time Library P1 查询工具")
    p.add_argument("--timeline", metavar="YYYY-MM-DD", help="按日期查 session")
    p.add_argument("--window", metavar="WINDOW", help="按 canonical window 查")
    p.add_argument("--channel", metavar="CHANNEL", help="按 channel 查")
    p.add_argument("--search", metavar="QUERY", help="关键词全文搜索")
    p.add_argument("--session-id", metavar="SID", help="精确查单条 session")
    p.add_argument("--explain", metavar="SID", dest="explain_sid", help="解释单条 session")
    p.add_argument("--list-windows", action="store_true", help="列出所有 canonical windows")
    p.add_argument("--rebuild-index", action="store_true", help="重建索引")
    args = p.parse_args()

    if args.list_windows:
        cmd_list_windows(args)
    elif args.rebuild_index:
        cmd_rebuild_index(args)
    elif args.timeline:
        cmd_timeline(args)
    elif args.window:
        cmd_window(args)
    elif args.channel:
        cmd_channel(args)
    elif args.search:
        cmd_search(args)
    elif args.explain_sid:
        args.session_id = args.explain_sid
        cmd_explain(args)
    elif args.session_id:
        cmd_explain(args)
    else:
        p.print_help()

if __name__ == "__main__":
    main()
