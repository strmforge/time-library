"""Publication gate for public memory benchmark claims.

This is a metadata gate, not a benchmark runner. It prevents internal recall
diagnostics from being promoted into public QA or leaderboard claims without a
clear source trail and reproducibility envelope.
"""

from __future__ import annotations

import re
from typing import Any


PUBLIC_METRIC_CLAIM_GATE_CONTRACT = "public_metric_claim_gate.v2026.6.21"

REQUIRED_FIELDS = (
    "benchmark",
    "split",
    "metric",
    "score",
    "measured_by",
    "reproducible_command",
    "dataset_source",
    "evaluation_scope",
    "public_wording",
)

ALLOWED_LONGMEMEVAL_RETRIEVAL_METRICS = ("recall_any@5", "recall_any@10")

PROVENANCE_FIELD_GROUPS = (
    ("claim_source_url", "source_refs"),
    ("measured_at", "source_date"),
    ("reproduction_artifact", "result_artifact"),
)

QA_ACCURACY_WORDING_PATTERNS = (
    r"\bqa\s+accuracy\b",
    r"\banswer\s+accuracy\b",
    r"\bend[-_\s]?to[-_\s]?end\b",
    r"\baccuracy\b",
    "端到端",
    "回答准确率",
    "答案准确率",
    "问答准确率",
    "QA准确率",
    "qa准确率",
)

LEADERBOARD_OVERCLAIM_PATTERNS = (
    r"\bsota\b",
    r"\bstate\s+of\s+the\s+art\b",
    r"\btop[-_\s]?1\b",
    "榜单第一",
    "三大榜单第一",
    "排名第一",
    "第一名",
    "现象级",
)


def _has_any(claim: dict[str, Any], fields: tuple[str, ...]) -> bool:
    for field in fields:
        value = claim.get(field)
        if value not in (None, "", []):
            return True
    return False


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.lower()
    for pattern in patterns:
        if pattern.startswith("\\") or "\\b" in pattern:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                return True
            continue
        if pattern.lower() in lowered:
            return True
    return False


def _score_text(score: Any) -> str:
    if isinstance(score, (int, float)):
        return f"{score:g}%"
    return str(score or "").strip()


def scan_public_metric_claim_text(text: str | None, claim: dict[str, Any] | None = None) -> dict[str, Any]:
    """Scan public-facing wording for metric boundary drift.

    This is intentionally lexical. It does not judge model quality; it only
    blocks public copy that turns retrieval recall into answer accuracy or a
    leaderboard claim.
    """

    claim = claim if isinstance(claim, dict) else {}
    text = str(text or "")
    metric = str(claim.get("metric") or "").lower()
    benchmark = str(claim.get("benchmark") or "").strip()
    errors: list[str] = []
    warnings: list[str] = []

    if metric in ALLOWED_LONGMEMEVAL_RETRIEVAL_METRICS and _matches_any(text, QA_ACCURACY_WORDING_PATTERNS):
        errors.append("retrieval_recall_public_wording_must_not_claim_qa_or_answer_accuracy")
    if _matches_any(text, LEADERBOARD_OVERCLAIM_PATTERNS):
        errors.append("public_metric_wording_must_not_claim_sota_or_leaderboard_first")

    lowered = text.lower()
    if "检索率" in text and metric in ALLOWED_LONGMEMEVAL_RETRIEVAL_METRICS:
        if metric not in lowered and "retrieval recall" not in lowered:
            errors.append("retrieval_rate_wording_must_name_recall_any_metric")
    if benchmark and benchmark.lower() not in lowered:
        warnings.append("public_wording_does_not_name_benchmark")
    if metric and metric not in lowered:
        warnings.append("public_wording_does_not_name_metric")
    if "retrieval" not in lowered and "检索" not in text:
        warnings.append("public_wording_does_not_mark_retrieval_scope")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "read_only": True,
        "write_performed": False,
        "model_call_performed": False,
        "text_supplied": bool(text.strip()),
    }


def _safe_public_wording(claim: dict[str, Any], *, ready: bool) -> str:
    benchmark = str(claim.get("benchmark") or "LongMemEval-S").strip()
    metric = str(claim.get("metric") or "recall_any@5").strip()
    score = _score_text(claim.get("score"))
    suffix = "source/provenance recorded" if ready else "source/provenance required before publication"
    return (
        f"{benchmark} retrieval {metric} = {score} "
        f"(retrieval-only; not a generated-answer metric; {suffix})."
    )


def gate_public_metric_claim(claim: dict[str, Any] | None = None) -> dict[str, Any]:
    claim = claim if isinstance(claim, dict) else {}
    errors: list[str] = []
    warnings: list[str] = []
    for field in REQUIRED_FIELDS:
        if claim.get(field) in (None, "", []):
            errors.append(f"missing_required_field:{field}")
    for fields in PROVENANCE_FIELD_GROUPS:
        if not _has_any(claim, fields):
            errors.append("missing_provenance_field_one_of:" + "|".join(fields))
    benchmark = str(claim.get("benchmark") or "").lower()
    metric = str(claim.get("metric") or "").lower()
    evaluation_scope = str(claim.get("evaluation_scope") or "").lower()
    measured_by = str(claim.get("measured_by") or "").strip().lower()
    if benchmark == "longmemeval-s" and metric not in ALLOWED_LONGMEMEVAL_RETRIEVAL_METRICS:
        errors.append("longmemeval_s_public_retrieval_claim_must_use_recall_any_metric")
    if (
        "qa" in evaluation_scope
        or "answer" in evaluation_scope
        or "accuracy" in evaluation_scope
        or "end_to_end" in evaluation_scope
        or "end-to-end" in evaluation_scope
    ):
        if metric in ALLOWED_LONGMEMEVAL_RETRIEVAL_METRICS:
            errors.append("retrieval_recall_must_not_be_labeled_qa_accuracy")
    if claim.get("self_eval") is True and not claim.get("independent_reproduction"):
        errors.append("self_eval_claim_requires_independent_reproduction_before_public_homepage")
    if measured_by in {"self", "internal", "ourselves", "local"} and not claim.get("independent_reproduction"):
        errors.append("internal_or_self_measured_public_claim_requires_independent_reproduction")
    wording_scan = scan_public_metric_claim_text(claim.get("public_wording"), claim)
    errors.extend(wording_scan["errors"])
    warnings.extend(wording_scan["warnings"])
    if not claim.get("judge_or_evaluator"):
        warnings.append("judge_or_evaluator_not_declared")
    if not claim.get("prompt_or_config"):
        warnings.append("prompt_or_config_not_declared")
    if not claim.get("token_budget"):
        warnings.append("token_budget_not_declared")
    ready = not errors
    return {
        "ok": ready,
        "contract": PUBLIC_METRIC_CLAIM_GATE_CONTRACT,
        "errors": errors,
        "warnings": warnings,
        "read_only": True,
        "write_performed": False,
        "model_call_performed": False,
        "is_publication_ready": ready,
        "official_leaderboard_score": bool(claim.get("official_leaderboard_score", False)),
        "metric_boundary": "retrieval_recall_not_qa_accuracy",
        "required_fields": list(REQUIRED_FIELDS),
        "provenance_field_groups": [list(fields) for fields in PROVENANCE_FIELD_GROUPS],
        "public_wording_scan": wording_scan,
        "publication_label": "retrieval_recall_with_source_gate" if ready else "blocked_until_source_gate_passes",
        "safe_public_wording": _safe_public_wording(claim, ready=ready),
    }


__all__ = [
    "PUBLIC_METRIC_CLAIM_GATE_CONTRACT",
    "gate_public_metric_claim",
    "scan_public_metric_claim_text",
]
