#!/usr/bin/env python3
"""
Time Library Context Gateway

知意上下文网关

架构原则：
- OpenClaw 不直接调用 recall，不直接访问 raw/LanceDB/全局记忆池
- OpenClaw 只能向 Zhiyi Context Gateway 请求可用记忆上下文
- 真正的记忆判断、召回、scope 过滤、证据包装、摘要生成、原话披露策略，统一由知意层负责

四种输出模式：
- summary：知意摘要（默认），从 matched_memories 生成可注入上下文
- evidence：摘要+来源引用，summary 基础上附加完整 source_refs
- verbatim：原话片段，从 raw 读取原始消息片段（需显式请求）
- audit：完整操作审计记录，日志化请求/召回/过滤/输出全过程

端口：9840（与 p4_inject.py 共用端口，通过路径区分）
"""

import sys, os, json, argparse, hashlib
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─── Gateway 内部依赖 ───────────────────────────────
from src.p3_recall import handle_recall, get_memories
from src.scope_enforcement import validate_scope, filter_by_scope
from src.scope_normalizer import get_scope_metadata
try:
    from src.zhiyi_archive import attach_archive_card, archive_card
except Exception:
    from zhiyi_archive import attach_archive_card, archive_card
from config_loader import get_memcore_root

# ─── 端口配置 ───────────────────────────────────
PORT = 9840

# ─── 内部模块 ────────────────────────────────────

MEMCORE_ROOT = get_memcore_root()


def detect_intent_mode(request: dict) -> str:
    """
    D2: 记忆查询意图识别

    根据请求字段或 query 内容判断输出模式。

    优先级：
    1. 请求中显式指定 mode 字段（最高优先）
    2. query 关键词推断
    3. 默认 summary

    模式推断规则：
    - verbatim 关键词："原话"、"原文"、"原始"、"verbatim"、"raw"、"原原本本"
    - evidence 关键词："证据"、"来源"、"source"、"evidence"、"reference"
    - audit 关键词："审计"、"audit"、"操作记录"、"完整日志"
    """
    # 显式指定
    explicit_mode = request.get("mode", "").lower()
    if explicit_mode in ("summary", "evidence", "verbatim", "audit"):
        return explicit_mode

    # query 关键词推断
    query = request.get("query", "").lower()

    verbatim_kw = ["原话", "原文", "原始", "verbatim", "raw", "原原本本", "一字不差", "逐字"]
    evidence_kw = ["证据", "来源", "source", "evidence", "reference", "出自", "引用"]
    audit_kw = ["审计", "audit", "操作记录", "完整日志", "全流程"]

    for kw in verbatim_kw:
        if kw in query:
            return "verbatim"
    for kw in evidence_kw:
        if kw in query:
            return "evidence"
    for kw in audit_kw:
        if kw in query:
            return "audit"

    # 默认
    return "summary"


def build_scope_from_caller(caller_scope: dict) -> dict:
    """从 caller_scope 构建 scope dict"""
    if not caller_scope:
        return {}
    canonical_window = caller_scope.get("canonical_window_id", "")
    return {
        "canonical_window_id": canonical_window,
        "source_system": caller_scope.get("source_system", "openclaw"),
        "computer_id": caller_scope.get("computer_id", "local"),
    }


def route_summary(recall_result: dict, matched_memories: list, query: str) -> dict:
    """
    D3: summary 模式
    从 matched_memories 生成知意摘要上下文（默认模式）
    """
    if not matched_memories:
        return {
            "context": "",
            "should_inject": False,
            "memory_count": 0,
            "injectable_context": "",
        }

    memory_lines = []
    archive_cards = []
    for m in matched_memories:
        m = attach_archive_card(m)
        card = m.get("archive_card") or archive_card(m)
        archive_cards.append(card)
        mtype = m.get("type", "")
        summary = m.get("summary", "")
        # 从 matched memory 提取 window（通过 scope_normalizer）
        sm = get_scope_metadata(m)
        window = sm.get("canonical_window_id", "")
        memory_lines.append(
            f"[{card['catalog_id']}][{mtype}][{window}][evidence:{card['evidence_level']}] "
            f"{card['title']} - {summary}"
        )

    memory_block = "\n".join(memory_lines)
    injectable_context = f"相关经验：{' | '.join(memory_lines[:5])}"

    injectable_memories = [m for m in matched_memories if m.get("should_inject", False)]

    return {
        "context": memory_block,
        "should_inject": len(injectable_memories) > 0,
        "memory_count": len(matched_memories),
        "injectable_context": injectable_context,
        "archive_cards": archive_cards,
    }


def route_evidence(recall_result: dict, matched_memories: list, query: str) -> dict:
    """
    D3: evidence 模式
    摘要 + 完整来源引用（source_refs）
    """
    base = route_summary(recall_result, matched_memories, query)

    # 为每条 memory 附加完整 source_refs
    evidence_list = []
    for m in matched_memories:
        m = attach_archive_card(m)
        card = m.get("archive_card") or archive_card(m)
        sr_raw = m.get("source_refs", {})
        if isinstance(sr_raw, str):
            try:
                sr = json.loads(sr_raw)
            except:
                sr = {}
        elif isinstance(sr_raw, dict):
            sr = sr_raw
        else:
            sr = {}

        sm = get_scope_metadata(m)
        evidence_list.append({
            "catalog_id": card["catalog_id"],
            "exp_id": m.get("exp_id", ""),
            "type": m.get("type", ""),
            "title": card["title"],
            "status": card["status"],
            "evidence_level": card["evidence_level"],
            "confidence": card["confidence"],
            "canonical_window_id": sm.get("canonical_window_id", ""),
            "session_id": sm.get("session_id", ""),
            "scope": m.get("scope", ""),
            "summary": m.get("summary", ""),
            "source_path": sr.get("source_path", ""),
            "msg_ids": sr.get("msg_ids", []),
        })

    base["evidence"] = evidence_list
    base["evidence_count"] = len(evidence_list)
    return base


def route_verbatim(matched_memories: list, query: str) -> dict:
    """
    D3: verbatim 模式
    从 raw 读取原始消息片段
    """
    if not matched_memories:
        return {"verbatim_count": 0, "fragments": []}

    fragments = []
    for m in matched_memories:
        m = attach_archive_card(m)
        card = m.get("archive_card") or archive_card(m)
        sr_raw = m.get("source_refs", {})
        if isinstance(sr_raw, str):
            try:
                sr = json.loads(sr_raw)
            except:
                sr = {}
        elif isinstance(sr_raw, dict):
            sr = sr_raw
        else:
            sr = {}

        source_path = sr.get("source_path", "")
        msg_ids = sr.get("msg_ids", [])

        if not source_path or not os.path.exists(source_path):
            fragments.append({
                "catalog_id": card["catalog_id"],
                "exp_id": m.get("exp_id", ""),
                "type": m.get("type", ""),
                "scope": m.get("scope", ""),
                "error": f"source_path not found: {source_path}",
            })
            continue

        # 读取 session 文件，按 msg_id 提取消息
        verbatim_texts = []
        try:
            with open(source_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        msg_id = rec.get("id", "")
                        if msg_id in msg_ids:
                            # 提取消息内容
                            if rec.get("type") == "message":
                                content = rec.get("message", {}).get("content", "")
                                role = rec.get("message", {}).get("role", "")
                                verbatim_texts.append(f"[{role}]: {content}")
                            elif rec.get("type") == "human":
                                content = rec.get("content", "")
                                verbatim_texts.append(f"[user]: {content}")
                            elif rec.get("type") == "ai":
                                content = rec.get("content", "")
                                verbatim_texts.append(f"[assistant]: {content}")
                    except:
                        pass
        except Exception as e:
            fragments.append({
                "catalog_id": card["catalog_id"],
                "exp_id": m.get("exp_id", ""),
                "error": f"read error: {e}",
            })
            continue

        if verbatim_texts:
            fragments.append({
                "catalog_id": card["catalog_id"],
                "exp_id": m.get("exp_id", ""),
                "type": m.get("type", ""),
                "scope": m.get("scope", ""),
                "source_path": source_path,
                "msg_ids": msg_ids,
                "fragments": verbatim_texts,
            })

    return {
        "verbatim_count": len(fragments),
        "fragments": fragments,
    }


def route_audit(request: dict, recall_result: dict, matched_memories: list,
                 intent_mode: str, scope_valid: bool, scope_err: str) -> dict:
    """
    D3: audit 模式
    完整操作审计记录（仅记录请求索引与匹配结果）

    J-Prep-2: query 不落明文，用 SHA256-16-char hash 替代
    """
    raw_query = request.get("query", "") or ""
    audit_record = {
        "audit_version": "1.0",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "request": {
            "query_hash": hashlib.sha256(raw_query.encode()).hexdigest()[:16] if raw_query else None,
            "query_len": len(raw_query),
            "caller_scope": request.get("caller_scope", {}),
            "requested_mode": request.get("mode", ""),
            "detected_mode": intent_mode,
            "type_filter": request.get("type_filter", []),
            "top_k": request.get("top_k", 5),
        },
        "scope_validation": {
            "valid": scope_valid,
            "error": scope_err or None,
        },
        "recall": {
            "total_matched": recall_result.get("total_matched", 0),
            "returned": recall_result.get("returned", 0),
            "scope_enforced": recall_result.get("_scope_enforced", False),
            "_scope_used": recall_result.get("_scope_used", {}),
        },
        "memories": [
            {
                "exp_id": m.get("exp_id", ""),
                "catalog_id": (m.get("archive_card") or archive_card(m)).get("catalog_id", ""),
                "type": m.get("type", ""),
                "scope": m.get("scope", ""),
                "summary": m.get("summary", ""),
                "confidence": m.get("confidence", 0),
                "should_inject": m.get("should_inject", False),
            }
            for m in matched_memories
        ],
        "intent_mode": intent_mode,
    }
    return audit_record


# ─── Gateway 主入口 ──────────────────────────────

class ZhiyiGateway:
    """
    知意上下文网关主入口
    """

    def __init__(self):
        self.version = "1.0"

    def handle(self, request: dict) -> dict:
        """
        处理请求，统一入口

        Args:
            request: {
                "query": str,
                "caller_scope": dict,       # 必填
                "mode": str,                # summary/evidence/verbatim/audit，默认自动识别
                "type_filter": list,
                "top_k": int,
            }

        Returns:
            dict: 根据 mode 返回不同结构
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        response = {
            "gateway_version": self.version,
            "timestamp": now,
        }

        # ─── 1. scope 检查 ───
        caller_scope = request.get("caller_scope", {})
        if not caller_scope:
            response["error"] = "caller_scope is required"
            response["code"] = "SCOPE_REQUIRED"
            return response

        scope_valid, scope_err = validate_scope(caller_scope)
        if not scope_valid:
            response["error"] = f"invalid caller_scope: {scope_err}"
            response["code"] = "INVALID_SCOPE"
            return response

        # ─── 2. 意图识别 ───
        intent_mode = detect_intent_mode(request)
        response["intent_mode"] = intent_mode
        response["caller_scope"] = caller_scope

        # ─── 3. recall ───
        scope_dict = build_scope_from_caller(caller_scope)
        scope_filter = f"window/{caller_scope.get('canonical_window_id', '')}"

        recall_body = {
            "query": request.get("query", ""),
            "scope_filter": scope_filter,
            "type_filter": request.get("type_filter", []),
            "top_k": request.get("top_k", 5),
            "recall_mode": "substring",  # 固定 substring 模式避免 bge-m3 依赖
        }
        recall_result = handle_recall(recall_body)
        matched_memories = recall_result.get("matched_memories", [])

        response["recall"] = {
            "total_matched": recall_result.get("total_matched", 0),
            "returned": recall_result.get("returned", 0),
            "_scope_enforced": recall_result.get("_scope_enforced", False),
        }

        # ─── 4. 按模式路由 ───
        if intent_mode == "summary":
            ctx = route_summary(recall_result, matched_memories, request.get("query", ""))
            response.update(ctx)

        elif intent_mode == "evidence":
            ctx = route_evidence(recall_result, matched_memories, request.get("query", ""))
            response.update(ctx)

        elif intent_mode == "verbatim":
            ctx = route_verbatim(matched_memories, request.get("query", ""))
            response.update(ctx)
            response["should_inject"] = False  # verbatim 不生成注入 prompt

        elif intent_mode == "audit":
            audit = route_audit(request, recall_result, matched_memories,
                                intent_mode, scope_valid, scope_err)
            response["audit"] = audit
            response["should_inject"] = False

        return response


# ─── HTTP Handler ───────────────────────────────

_gateway = ZhiyiGateway()


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
                "service": "zhiyi-context-gateway",
                "version": _gateway.version,
                "port": PORT,
            })
        elif self.path == "/modes":
            self.send_json({
                "modes": ["summary", "evidence", "verbatim", "audit"],
                "default": "summary",
                "description": {
                    "summary": "知意摘要（默认），从 matched_memories 生成可注入上下文",
                    "evidence": "摘要+来源引用，summary 基础上附加完整 source_refs",
                    "verbatim": "原话片段，从 raw 读取原始消息片段（需显式请求）",
                    "audit": "完整操作审计记录，日志化请求/召回/过滤/输出全过程",
                }
            })
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/gateway":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = _gateway.handle(body)
            code = 200 if "error" not in result else 400
            self.send_json(result, code)
        else:
            self.send_json({"error": "not found"}, 404)


def run(port=PORT):
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[zhiyi_gateway] running on http://127.0.0.1:{port}")
    print(f"[zhiyi_gateway] endpoints: POST /gateway, GET /health, GET /modes")
    server.serve_forever()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Time Library Context Gateway")
    p.add_argument("--port", type=int, default=PORT)
    args = p.parse_args()
    run(args.port)
