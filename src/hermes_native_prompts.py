#!/usr/bin/env python3
"""Prompt builders for Hermes native review and skill-generation requests."""

from __future__ import annotations

import json
from typing import Any


def _pointer_lines(signal: dict[str, Any]) -> list[str]:
    pointers = signal.get("pointers", {}) if isinstance(signal.get("pointers"), dict) else {}
    return [
        f"- {name}: {value.get('path')}"
        for name, value in pointers.items()
        if isinstance(value, dict) and value.get("path")
    ]


def _build_hermes_self_review_prompt(signal: dict[str, Any], reason: str = "") -> str:
    scope = signal.get("scope", {}) if isinstance(signal.get("scope"), dict) else {}
    local_roots = scope.get("local_roots", []) if isinstance(scope.get("local_roots"), list) else []
    logical_roots = scope.get("logical_roots", []) if isinstance(scope.get("logical_roots"), list) else []
    pointer_lines = _pointer_lines(signal)
    return (
        "你是 Hermes，请做一次Time Library原始记忆自审。\n"
        "这不是摘要包，也不是让Time Library替你写 skill。你需要自己读取下面的 raw/source_refs 区域，"
        "判断是否存在值得沉淀为 Hermes native skill 或经验反馈的内容。\n\n"
        f"触发原因: {reason or 'Hermes native learning liveness is cold'}\n"
        f"read_scope: {scope.get('read_scope', 'all_raw_memory')}\n"
        f"read_hint: {scope.get('read_hint', '这一片都是你该去读的原始记忆')}\n"
        f"logical_roots: {json.dumps(logical_roots, ensure_ascii=False)}\n"
        f"local_roots: {json.dumps(local_roots, ensure_ascii=False)}\n"
        "pointers:\n"
        + ("\n".join(pointer_lines) if pointer_lines else "- none")
        + "\n\n"
        "要求:\n"
        "1. 先检查原始记忆和 source_refs，不要只看知意摘要。\n"
        "2. 如果发现可复用经验，请输出候选标题、来源路径、原话片段、适用场景、验收条件。\n"
        "3. 如果你选择写 Hermes native artifact/skill，必须由 Hermes 自己完成，Time Library不替你写。\n"
        "4. 不要修改Time Library raw/zhiyi/xingce/toolbook/errata。\n"
        "5. 最后用 JSON fenced block 输出 review_status、files_read_count、candidate_count、actions_taken。\n"
    )


def _build_hermes_skill_generation_probe_prompt(signal: dict[str, Any], reason: str = "") -> str:
    scope = signal.get("scope", {}) if isinstance(signal.get("scope"), dict) else {}
    pointer_lines = _pointer_lines(signal)
    return (
        "你是 Hermes。请做一次 native skill generation probe。\n"
        "这不是让Time Library替你写 skill，也不是输出普通自审报告。"
        "你需要自己读取Time Library raw/source_refs，判断是否存在足够稳定、可复用、可验收的工作方法。\n\n"
        f"触发原因: {reason or 'verify Hermes native skill generation trigger'}\n"
        f"read_scope: {scope.get('read_scope', 'all_raw_memory')}\n"
        f"read_hint: {scope.get('read_hint', '这一片都是你该去读的原始记忆')}\n"
        "pointers:\n"
        + ("\n".join(pointer_lines) if pointer_lines else "- none")
        + "\n\n"
        "任务:\n"
        "1. 先读取原始记忆和 source_refs，不要只看知意摘要。\n"
        "2. 找一条小而稳定的工作方法，适合作为 Hermes native skill candidate。\n"
        "3. 如果 Hermes 运行时允许使用 skill/tool 管理能力，请由 Hermes 自己创建或更新一个 scratch/test skill；"
        "Time Library不得替你写 skill。\n"
        "4. 如果不能创建 skill，请明确说明阻塞原因，例如 tool_call_not_available、policy_not_triggered、"
        "insufficient_evidence、provider_no_tool_use。\n"
        "5. 不要修改Time Library raw/zhiyi/xingce/toolbook/errata。\n"
        "6. 最后用 JSON fenced block 输出: probe_status、files_read_count、candidate_title、"
        "skill_action_attempted、skill_action_result、blocker。\n"
    )


def _build_hermes_native_generation_trigger_prompt(
    signal: dict[str, Any],
    *,
    cadence: str,
    model_hint: str,
    generation_scope: str,
) -> str:
    scope = signal.get("scope", {}) if isinstance(signal.get("scope"), dict) else {}
    pointer_lines = _pointer_lines(signal)
    return (
        "你是 Hermes。请在夜间例行回顾里做一次 native skill generation。\n"
        "这条提示由 Time Library 生成，用来提醒你读新增 raw/source_refs，"
        "再决定是否由 Hermes 自己生成或升级 native skill。\n\n"
        f"cadence: {cadence or 'nightly'}\n"
        f"model_hint: {model_hint or 'large_model'}\n"
        f"generation_scope: {generation_scope or 'read_only_new_raw'}\n"
        f"read_scope: {scope.get('read_scope', 'all_raw_memory')}\n"
        f"read_hint: {scope.get('read_hint', '这一片都是你该去读的原始记忆')}\n"
        "pointers:\n"
        + ("\n".join(pointer_lines) if pointer_lines else "- none")
        + "\n\n"
        "任务:\n"
        "1. 先读新增 raw/source_refs，不要把知意摘要当原始来源。\n"
        "2. 只挑小而稳定、可复用、可验收的工作方法。\n"
        "3. 如 Hermes 运行时允许，请由 Hermes 自己创建或升级 native skill；Time Library只提供触发计划，不替你写 skill。\n"
        "4. 如果这轮不该产 skill，请明确 blocker，例如 insufficient_evidence、tool_call_not_available、policy_not_triggered。\n"
        "5. 不要修改Time Library raw/zhiyi/xingce/toolbook/errata。\n"
    )
