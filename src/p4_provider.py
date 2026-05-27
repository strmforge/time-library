#!/usr/bin/env python3
"""
memcore-cloud P4: Context Injection Endpoint
消费 recall 结果，生成 injectable context，
暴露 API 供 OpenClaw 接入调用。
"""
import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from src.p3_recall import handle_recall

PORT = 9840

# ─── Prompt 模板 ─────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """你正在使用忆凡尘的知意档案馆。你是档案员，不是创作者。

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


def _memory_prompt_text(memory):
    mtype = memory.get("type") or memory.get("_type") or ""
    if mtype == "yifanchen_project_status":
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

# ─── API Handler ─────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_GET(self):
        if self.path == "/health":
            self.send_json({"status": "ok", "service": "inject-context-endpoint", "port": PORT})
        elif self.path == "/ready":
            # readiness probe — check p3 is reachable
            try:
                from src.p3_recall import get_memories
                count = len(get_memories())
                self.send_json({"ready": True, "memory_count": count})
            except Exception as e:
                self.send_json({"ready": False, "error": str(e)}, 500)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/inject":
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
        else:
            self.send_json({"error": "not found"}, 404)

def run(port=PORT):
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[p4] provider-proxy running on http://127.0.0.1:{port}")
    server.serve_forever()

if __name__ == "__main__":
    import sys
    p = argparse.ArgumentParser(description="memcore-cloud P4 Inject Context Endpoint")
    p.add_argument("--port", type=int, default=PORT)
    args = p.parse_args()
    run(args.port)

# Alias for backward compatibility
run_service = run
