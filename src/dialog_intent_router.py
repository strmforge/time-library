"""
dialog_intent_router.py
Intent router MVP.
Intent rules are loaded from config/intent_router_rules.json.

4级判断：
1 = 记忆查询（知意直答）
2 = 复杂任务（知意注入+转发）
3 = 普通问答（直接放行）
4 = 闲聊/无关（直接放行）
"""

from __future__ import annotations

import os
import json
from config_loader import get_memcore_root
from zhiyi_entry_intent import is_zhiyi_entry_request

CONFIG_PATH = os.path.join(get_memcore_root(), "config", "intent_router_rules.json")

LEVEL_MEMORY_QUERY = 1
LEVEL_COMPLEX_TASK = 2
LEVEL_NORMAL_QA = 3
LEVEL_CHITCHAT = 4

ROUTE_CORRECTION_ERRATA = "correction_errata"
ROUTE_SOURCE_LOOKUP = "source_lookup"
ROUTE_ZHIYI_LOOKUP = "zhiyi_lookup"
ROUTE_XINGCE_LOOKUP = "xingce_lookup"
ROUTE_TOOLBOOK_LOOKUP = "toolbook_lookup"
ROUTE_BENCHMARK_REPLAY = "benchmark_replay"
ROUTE_METHOD_SIGNAL = "method_signal"
ROUTE_STATE_LEDGER = "state_ledger"
ROUTE_CONTEXT_UNIT = "context_unit"
ROUTE_MEMORY_RECALL = "memory_recall"
ROUTE_NO_MEMORY = "no_memory"
ROUTE_COMPLEX_TASK = "complex_task"
ROUTE_PASS_THROUGH = "pass_through"
ROUTE_CHITCHAT = "chitchat"

_DEFAULT_RULES = {
    "memory_phrases": [
        "/zhiyi", "/memory", "/recall", "/continue", "/catchup", "/catch-up",
        "这边给你调取", "调取忆凡尘", "忆凡尘项目进度",
        "接上上次", "接上忆凡尘", "接上项目",
        "按项目继续",
        "catch me up", "continue from memory", "check local memory",
        "pick up where we left off", "resume from memory",
    ],
    "memory_keywords": [
        "记得", "以前", "之前", "过去", "历史",
        "曾经", "上次", "那天", "那个项目",
        "之前说过", "我记得", "你记得吗",
        "查找记录", "查一下", "有什么", "哪一次",
        "什么时候", "几个月前", "哪天",
        "memory", "recall", "previous context", "local memory",
        "what did we decide", "what did we say before",
    ],
    "complex_keywords": [
        "分析", "总结", "比较", "对比", "查找",
        "搜索", "整理", "归类", "评估", "判断",
        "为什么", "什么原因", "怎么做", "如何解决",
        "帮我", "请帮我", "能帮我", "需要你",
    ],
    "chitchat_keywords": [
        "你好", "嗨", "hi", "hello", "早上好", "下午好",
        "在吗", "在不在", "休息", "下班", "周末",
        "吃饭", "闲聊",
    ],
    "negative_keywords": [
        "不用", "不需要", "不要记", "不记得",
        "忘记", "忘了", "别管", "新问题",
        "do not use memory", "don't use memory", "without memory",
        "forget this", "new topic",
    ],
    "correction_keywords": [
        "这条记录不对", "这条记错了", "记错了", "记忆错了",
        "你理解偏了", "你理解错了", "不是我的意思", "不是我的原话",
        "这不是我的原话", "以后不要这么理解", "不要这么理解",
        "这不是偏好", "这不是用户偏好", "这不是行策",
        "this memory is wrong", "you misunderstood", "that is not what i meant",
        "not my original wording", "not my preference",
    ],
    "source_lookup_keywords": [
        "原话", "原文", "出处", "来源", "证据", "回源",
        "source", "source_ref", "source refs", "verbatim", "exact wording",
    ],
    "zhiyi_lookup_keywords": [
        "知意", "偏好", "喜好", "习惯", "表达习惯", "用户偏好",
        "preference", "intent experience", "user preference",
    ],
    "xingce_lookup_keywords": [
        "行策", "工作经验", "行动策略", "踩坑", "避坑", "验收",
        "下一刀", "怎么做", "排障", "work experience", "action strategy",
    ],
    "toolbook_lookup_keywords": [
        "工具书", "平台事实", "环境差异", "命令", "端口", "安装",
        "路径", "配置", "实测", "toolbook", "runbook", "platform fact",
    ],
    "benchmark_keywords": [
        "benchmark", "replay", "回放", "评测", "评估", "三组对比",
        "no_memory", "zhiyi_only", "zhiyi_plus_xingce",
    ],
    "method_signal_keywords": [
        "新方向", "新的方向", "外部信号", "方法候选", "方法卡",
        "method signal", "method_signal", "method card", "method_card",
        "external signal", "feed-to-method", "天箓", "tianlu",
        "github", "repo", "repository", "x 上", "x上", "资讯",
        "这可能对忆凡尘有用", "这个对忆凡尘有用", "另一个设想",
    ],
    "state_ledger_keywords": [
        "状态账本", "最新可信判断", "当前可信判断", "现在这件事",
        "现在的结论", "时间索引", "状态索引", "谁替代了谁",
        "state ledger", "state-ledger", "temporal index", "latest trusted judgment",
    ],
    "context_unit_keywords": [
        "上下文预算", "上下文最小单元", "最小上下文单元",
        "粒子", "离子", "context budget", "context unit",
        "context-budget-unit", "minimal context unit",
    ],
}


def _load_rules():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return None


_rules = _load_rules()

MEMORY_PHRASES = _rules.get("memory_phrases", _DEFAULT_RULES["memory_phrases"]) if _rules else _DEFAULT_RULES["memory_phrases"]
MEMORY_KEYWORDS = _rules.get("memory_keywords", _DEFAULT_RULES["memory_keywords"]) if _rules else _DEFAULT_RULES["memory_keywords"]
COMPLEX_KEYWORDS = _rules.get("complex_keywords", _DEFAULT_RULES["complex_keywords"]) if _rules else _DEFAULT_RULES["complex_keywords"]
CHITCHAT_KEYWORDS = _rules.get("chitchat_keywords", _DEFAULT_RULES["chitchat_keywords"]) if _rules else _DEFAULT_RULES["chitchat_keywords"]
NEGATIVE_KEYWORDS = _rules.get("negative_keywords", _DEFAULT_RULES["negative_keywords"]) if _rules else _DEFAULT_RULES["negative_keywords"]
CORRECTION_KEYWORDS = _rules.get("correction_keywords", _DEFAULT_RULES["correction_keywords"]) if _rules else _DEFAULT_RULES["correction_keywords"]
SOURCE_LOOKUP_KEYWORDS = _rules.get("source_lookup_keywords", _DEFAULT_RULES["source_lookup_keywords"]) if _rules else _DEFAULT_RULES["source_lookup_keywords"]
ZHIYI_LOOKUP_KEYWORDS = _rules.get("zhiyi_lookup_keywords", _DEFAULT_RULES["zhiyi_lookup_keywords"]) if _rules else _DEFAULT_RULES["zhiyi_lookup_keywords"]
XINGCE_LOOKUP_KEYWORDS = _rules.get("xingce_lookup_keywords", _DEFAULT_RULES["xingce_lookup_keywords"]) if _rules else _DEFAULT_RULES["xingce_lookup_keywords"]
TOOLBOOK_LOOKUP_KEYWORDS = _rules.get("toolbook_lookup_keywords", _DEFAULT_RULES["toolbook_lookup_keywords"]) if _rules else _DEFAULT_RULES["toolbook_lookup_keywords"]
BENCHMARK_KEYWORDS = _rules.get("benchmark_keywords", _DEFAULT_RULES["benchmark_keywords"]) if _rules else _DEFAULT_RULES["benchmark_keywords"]
METHOD_SIGNAL_KEYWORDS = _rules.get("method_signal_keywords", _DEFAULT_RULES["method_signal_keywords"]) if _rules else _DEFAULT_RULES["method_signal_keywords"]
STATE_LEDGER_KEYWORDS = _rules.get("state_ledger_keywords", _DEFAULT_RULES["state_ledger_keywords"]) if _rules else _DEFAULT_RULES["state_ledger_keywords"]
CONTEXT_UNIT_KEYWORDS = _rules.get("context_unit_keywords", _DEFAULT_RULES["context_unit_keywords"]) if _rules else _DEFAULT_RULES["context_unit_keywords"]


def _matches_any(lowered: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw.lower() in lowered]


def _fine_result(
    message: str,
    route: str,
    level: int,
    action: str,
    target_shelf: str = "",
    matched_by: str = "keyword",
    matched_keywords: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict:
    return {
        "ok": True,
        "version": "2026.5.31",
        "message": message,
        "route": route,
        "level": level,
        "label": fine_route_to_label(route),
        "action": action,
        "target_shelf": target_shelf,
        "matched_by": matched_by,
        "matched_keywords": matched_keywords or [],
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "correction_candidate_suggested": route == ROUTE_CORRECTION_ERRATA,
        "notes": notes or [],
    }


def classify_fine_intent(message: str, context: dict = None) -> dict:
    """Classify memory governance intent without querying or writing memory."""
    msg = str(message or "").strip()
    if not msg:
        return _fine_result(msg, ROUTE_CHITCHAT, LEVEL_CHITCHAT, "pass_through", matched_by="empty")

    lowered = msg.lower()

    correction = _matches_any(lowered, CORRECTION_KEYWORDS)
    if correction:
        return _fine_result(
            msg,
            ROUTE_CORRECTION_ERRATA,
            LEVEL_MEMORY_QUERY,
            "zhiyi_errata_candidate",
            target_shelf="errata",
            matched_keywords=correction,
            notes=["natural_language_memory_correction", "candidate_only_no_raw_mutation"],
        )

    negative = _matches_any(lowered, NEGATIVE_KEYWORDS)
    if negative:
        return _fine_result(
            msg,
            ROUTE_NO_MEMORY,
            LEVEL_NORMAL_QA,
            "pass_through",
            matched_keywords=negative,
            notes=["memory_disabled_for_this_turn"],
        )

    benchmark = _matches_any(lowered, BENCHMARK_KEYWORDS)
    if benchmark:
        return _fine_result(
            msg,
            ROUTE_BENCHMARK_REPLAY,
            LEVEL_MEMORY_QUERY,
            "zhixing_benchmark_or_replay",
            target_shelf="evaluation",
            matched_keywords=benchmark,
        )

    method_signal = _matches_any(lowered, METHOD_SIGNAL_KEYWORDS)
    if method_signal:
        return _fine_result(
            msg,
            ROUTE_METHOD_SIGNAL,
            LEVEL_MEMORY_QUERY,
            "zhixing_method_signal_candidate",
            target_shelf="incubator",
            matched_keywords=method_signal,
            notes=["external_or_prior_signal_requires_recall_before_judgment", "candidate_only_no_activation"],
        )

    state_ledger = _matches_any(lowered, STATE_LEDGER_KEYWORDS)
    if state_ledger:
        return _fine_result(
            msg,
            ROUTE_STATE_LEDGER,
            LEVEL_MEMORY_QUERY,
            "zhixing_state_ledger",
            target_shelf="evaluation",
            matched_keywords=state_ledger,
            notes=["latest_trusted_judgment_requires_source_backed_state_records", "temporal_index_is_navigation_only"],
        )

    context_unit = _matches_any(lowered, CONTEXT_UNIT_KEYWORDS)
    if context_unit:
        return _fine_result(
            msg,
            ROUTE_CONTEXT_UNIT,
            LEVEL_MEMORY_QUERY,
            "context_budget_unit_candidate",
            target_shelf="incubator",
            matched_keywords=context_unit,
            notes=["minimal_context_unit_candidate_only", "requires_source_refs_and_verbatim_excerpt"],
        )

    source = _matches_any(lowered, SOURCE_LOOKUP_KEYWORDS)
    if source:
        return _fine_result(
            msg,
            ROUTE_SOURCE_LOOKUP,
            LEVEL_MEMORY_QUERY,
            "source_backed_lookup",
            target_shelf="raw",
            matched_keywords=source,
        )

    toolbook = _matches_any(lowered, TOOLBOOK_LOOKUP_KEYWORDS)
    if toolbook:
        return _fine_result(
            msg,
            ROUTE_TOOLBOOK_LOOKUP,
            LEVEL_MEMORY_QUERY,
            "toolbook_lookup",
            target_shelf="toolbook",
            matched_keywords=toolbook,
        )

    xingce = _matches_any(lowered, XINGCE_LOOKUP_KEYWORDS)
    if xingce:
        return _fine_result(
            msg,
            ROUTE_XINGCE_LOOKUP,
            LEVEL_MEMORY_QUERY,
            "xingce_lookup",
            target_shelf="xingce",
            matched_keywords=xingce,
        )

    zhiyi = _matches_any(lowered, ZHIYI_LOOKUP_KEYWORDS)
    if zhiyi:
        return _fine_result(
            msg,
            ROUTE_ZHIYI_LOOKUP,
            LEVEL_MEMORY_QUERY,
            "zhiyi_lookup",
            target_shelf="zhiyi",
            matched_keywords=zhiyi,
        )

    if is_zhiyi_entry_request(msg):
        return _fine_result(
            msg,
            ROUTE_MEMORY_RECALL,
            LEVEL_MEMORY_QUERY,
            "zhiyi_direct",
            target_shelf="zhiyi",
            matched_by="zhiyi_entry",
        )

    for kw in CHITCHAT_KEYWORDS:
        if kw.lower() in lowered:
            return _fine_result(msg, ROUTE_CHITCHAT, LEVEL_CHITCHAT, "pass_through", matched_keywords=[kw])

    for phrase in MEMORY_PHRASES:
        if phrase.lower() in lowered:
            return _fine_result(msg, ROUTE_MEMORY_RECALL, LEVEL_MEMORY_QUERY, "zhiyi_direct", target_shelf="zhiyi", matched_keywords=[phrase])

    memory_keywords = _matches_any(lowered, MEMORY_KEYWORDS)
    if memory_keywords:
        return _fine_result(msg, ROUTE_MEMORY_RECALL, LEVEL_MEMORY_QUERY, "zhiyi_direct", target_shelf="zhiyi", matched_keywords=memory_keywords)

    complex_keywords = _matches_any(lowered, COMPLEX_KEYWORDS)
    if complex_keywords:
        return _fine_result(msg, ROUTE_COMPLEX_TASK, LEVEL_COMPLEX_TASK, "zhiyi_inject", matched_keywords=complex_keywords)

    return _fine_result(msg, ROUTE_PASS_THROUGH, LEVEL_NORMAL_QA, "pass_through", matched_by="fallback")


def classify_intent(message: str, context: dict = None) -> int:
    return int(classify_fine_intent(message, context).get("level", LEVEL_NORMAL_QA))


def level_to_action(level: int) -> str:
    return {
        LEVEL_MEMORY_QUERY: "zhiyi_direct",
        LEVEL_COMPLEX_TASK: "zhiyi_inject",
        LEVEL_NORMAL_QA: "pass_through",
        LEVEL_CHITCHAT: "pass_through",
    }.get(level, "pass_through")


def level_to_label(level: int) -> str:
    return {
        LEVEL_MEMORY_QUERY: "记忆查询",
        LEVEL_COMPLEX_TASK: "复杂任务",
        LEVEL_NORMAL_QA: "普通问答",
        LEVEL_CHITCHAT: "闲聊/无关",
    }.get(level, "未知")


def fine_route_to_label(route: str) -> str:
    return {
        ROUTE_CORRECTION_ERRATA: "纠错/勘误",
        ROUTE_SOURCE_LOOKUP: "查原话/来源",
        ROUTE_ZHIYI_LOOKUP: "查知意",
        ROUTE_XINGCE_LOOKUP: "查行策",
        ROUTE_TOOLBOOK_LOOKUP: "查工具书",
        ROUTE_BENCHMARK_REPLAY: "Benchmark/Replay",
        ROUTE_METHOD_SIGNAL: "方法信号候选",
        ROUTE_STATE_LEDGER: "状态账本/时间索引",
        ROUTE_CONTEXT_UNIT: "上下文最小单元候选",
        ROUTE_MEMORY_RECALL: "记忆召回",
        ROUTE_NO_MEMORY: "本轮不用记忆",
        ROUTE_COMPLEX_TASK: "复杂任务",
        ROUTE_PASS_THROUGH: "普通放行",
        ROUTE_CHITCHAT: "闲聊/无关",
    }.get(route, "未知")


def get_router_config_status() -> dict:
    return {
        "config_path": CONFIG_PATH,
        "config_loaded": _rules is not None,
        "memory_phrases_count": len(MEMORY_PHRASES),
        "memory_keywords_count": len(MEMORY_KEYWORDS),
        "complex_keywords_count": len(COMPLEX_KEYWORDS),
        "chitchat_keywords_count": len(CHITCHAT_KEYWORDS),
        "negative_keywords_count": len(NEGATIVE_KEYWORDS),
        "correction_keywords_count": len(CORRECTION_KEYWORDS),
        "source_lookup_keywords_count": len(SOURCE_LOOKUP_KEYWORDS),
        "zhiyi_lookup_keywords_count": len(ZHIYI_LOOKUP_KEYWORDS),
        "xingce_lookup_keywords_count": len(XINGCE_LOOKUP_KEYWORDS),
        "toolbook_lookup_keywords_count": len(TOOLBOOK_LOOKUP_KEYWORDS),
        "benchmark_keywords_count": len(BENCHMARK_KEYWORDS),
        "method_signal_keywords_count": len(METHOD_SIGNAL_KEYWORDS),
        "state_ledger_keywords_count": len(STATE_LEDGER_KEYWORDS),
        "context_unit_keywords_count": len(CONTEXT_UNIT_KEYWORDS),
    }


if __name__ == "__main__":
    test_cases = [
        # config: "记得" in memory_keywords → MEMORY_QUERY
        ("你之前说过什么？", LEVEL_MEMORY_QUERY),  # "之前" now in config memory_keywords
        ("帮我分析一下这个项目", LEVEL_COMPLEX_TASK),
        ("今天天气怎么样", LEVEL_CHITCHAT),     # config: "天气" in chitchat_keywords
        ("你好啊", LEVEL_CHITCHAT),
        ("不需要记得", LEVEL_NORMAL_QA),
        ("忘记上次的内容了", LEVEL_NORMAL_QA),
        # config: "有什么" not in memory; "记录" not in memory → normal
        ("有什么记录吗", LEVEL_NORMAL_QA),
        ("对比一下两个方案", LEVEL_COMPLEX_TASK),
    ]
    print("=== 意图判断器测试 ===")
    for msg, expected in test_cases:
        result = classify_intent(msg)
        status = "✅" if result == expected else "❌"
        print(f"{status} [{expected}] {level_to_label(result)} | {msg}")
    print("=== 配置状态 ===")
    print(get_router_config_status())
