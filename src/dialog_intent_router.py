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

import os
import json
import re
from typing import Literal
from config_loader import get_memcore_root
from zhiyi_entry_intent import is_zhiyi_entry_request

CONFIG_PATH = os.path.join(get_memcore_root(), "config", "intent_router_rules.json")

LEVEL_MEMORY_QUERY = 1
LEVEL_COMPLEX_TASK = 2
LEVEL_NORMAL_QA = 3
LEVEL_CHITCHAT = 4

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


def classify_intent(message: str, context: dict = None) -> int:
    msg = message.strip()
    if not msg:
        return LEVEL_CHITCHAT
    if is_zhiyi_entry_request(msg):
        return LEVEL_MEMORY_QUERY

    lowered = msg.lower()
    for kw in NEGATIVE_KEYWORDS:
        if kw.lower() in lowered:
            return LEVEL_NORMAL_QA

    for kw in CHITCHAT_KEYWORDS:
        if kw.lower() in lowered:
            return LEVEL_CHITCHAT

    for phrase in MEMORY_PHRASES:
        if phrase.lower() in lowered:
            return LEVEL_MEMORY_QUERY

    for kw in MEMORY_KEYWORDS:
        if kw.lower() in lowered:
            return LEVEL_MEMORY_QUERY

    for kw in COMPLEX_KEYWORDS:
        if kw.lower() in lowered:
            return LEVEL_COMPLEX_TASK

    return LEVEL_NORMAL_QA


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


def get_router_config_status() -> dict:
    return {
        "config_path": CONFIG_PATH,
        "config_loaded": _rules is not None,
        "memory_phrases_count": len(MEMORY_PHRASES),
        "memory_keywords_count": len(MEMORY_KEYWORDS),
        "complex_keywords_count": len(COMPLEX_KEYWORDS),
        "chitchat_keywords_count": len(CHITCHAT_KEYWORDS),
        "negative_keywords_count": len(NEGATIVE_KEYWORDS),
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
