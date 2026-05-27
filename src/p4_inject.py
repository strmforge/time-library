#!/usr/bin/env python3
"""
memcore-cloud P4: Inject Context Endpoint (via Zhiyi Gateway)

P9-System-D D4: 重构 p4_inject.py 调用 Zhiyi Context Gateway

核心变更：
- 不再裸调 recall
- 改为调用 ZhiyiGateway.handle()
- 保持 caller_scope 必填和无 scope deny 逻辑
- Gateway 负责 scope 过滤、意图识别、模式路由

端口：9840（与 Zhiyi Gateway 共用端口）
"""

import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import HTTPServer, BaseHTTPRequestHandler
from src.zhiyi_gateway import ZhiyiGateway

PORT = 9840
_gateway = ZhiyiGateway()

# ─── Prompt 模板（由 Gateway 模式决定是否使用）───────────

SYSTEM_PROMPT_TEMPLATE = """你有一个助手记忆库，里面记录了以下相关经验：

{memories}

如果以上记忆与当前问题相关，请结合使用。"""


def build_inject_prompt(gateway_result: dict, query: str) -> dict:
    """
    从 gateway result 构建 injectable prompt。
    gateway 已返回 context/summary，这里做最后一层包装。
    """
    intent_mode = gateway_result.get("intent_mode", "summary")

    # verbatim 和 audit 模式不生成注入 prompt
    if intent_mode in ("verbatim", "audit"):
        return {
            "system_prompt": "",
            "user_prompt": "",
            "should_inject": False,
        }

    # summary / evidence 使用 context
    context = gateway_result.get("context", "")
    if not context:
        return {
            "system_prompt": "",
            "user_prompt": "",
            "should_inject": gateway_result.get("should_inject", False),
        }

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(memories=context)
    user_prompt = f"当前问题：{query}"

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "should_inject": gateway_result.get("should_inject", False),
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
            self.send_json({
                "status": "ok",
                "service": "inject-context-endpoint",
                "port": PORT,
                "backend": "zhiyi_gateway",
            })
        elif self.path == "/ready":
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
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}

            # caller_scope 必填
            caller_scope = body.get("caller_scope")
            if not caller_scope or not caller_scope.get("canonical_window_id"):
                self.send_json({
                    "error": "caller_scope.canonical_window_id is required",
                    "code": "SCOPE_REQUIRED",
                    "message": "Inject request must include caller_scope.canonical_window_id. Requests without scope are denied by default.",
                }, 400)
                return

            # 调用 Zhiyi Gateway
            gateway_result = _gateway.handle(body)

            # 构建 inject prompt
            inject = build_inject_prompt(gateway_result, body.get("query", ""))

            # 合并响应
            response = {
                "query": body.get("query", ""),
                "intent_mode": gateway_result.get("intent_mode", "summary"),
                "gateway_version": gateway_result.get("gateway_version", ""),
                "should_inject": inject["should_inject"],
                "memory_count": gateway_result.get("memory_count", 0),
                "system_prompt": inject["system_prompt"],
                "user_prompt": inject["user_prompt"],
                "_gateway_result": gateway_result,  # 透传完整 gateway 输出
            }

            # 如果有 error（scope 问题），返回 400
            if "error" in gateway_result:
                self.send_json(response, 400)
            else:
                self.send_json(response)

        else:
            self.send_json({"error": "not found"}, 404)


def run(port=PORT):
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[p4_inject] running on http://127.0.0.1:{port}")
    print(f"[p4_inject] backend: ZhiyiGateway (src/zhiyi_gateway.py)")
    server.serve_forever()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="memcore-cloud P4 Inject Context Endpoint (via Zhiyi Gateway)")
    p.add_argument("--port", type=int, default=PORT)
    args = p.parse_args()
    run(args.port)
