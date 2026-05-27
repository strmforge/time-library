#!/usr/bin/env python3
"""Raw evidence draft contract validator."""
from __future__ import annotations
import json
from typing import Any

SHARED_CORE_FIELDS = [
    "draft_id", "title", "source_mode", "observed_facts",
    "inferred_workflow", "recommended_procedure", "verification_steps",
    "rollback_or_stop_conditions", "failure_patterns",
    "evidence_refs", "source_refs", "raw_excerpt_hashes",
    "confidence", "limitations",
]

LIST_FIELDS = [
    "observed_facts", "inferred_workflow", "recommended_procedure",
    "verification_steps", "rollback_or_stop_conditions", "failure_patterns",
    "evidence_refs", "source_refs", "raw_excerpt_hashes", "limitations",
]


class ValidationResult:
    def __init__(self, draft: dict[str, Any]):
        self.draft = draft
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.redline_flags: list[str] = []
        self.consumer_type: str = ""
        self.shared_core_valid: bool = False
        self.consumer_extension_valid: bool = False
        self.ok: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "redline_flags": self.redline_flags,
            "consumer_type": self.consumer_type,
            "shared_core_valid": self.shared_core_valid,
            "consumer_extension_valid": self.consumer_extension_valid,
        }


class DraftContractGateError(ValueError):
    def __init__(self, message: str, result: ValidationResult | None = None):
        super().__init__(message)
        self.result = result


def validate_shared_core(draft: dict, result: ValidationResult) -> None:
    for field in SHARED_CORE_FIELDS:
        if field not in draft:
            result.errors.append(f"missing required field: {field}")

    source_mode = draft.get("source_mode")
    if source_mode is None:
        result.errors.append("missing source_mode")
    elif source_mode != "raw_source_refs":
        result.redline_flags.append(
            f"source_mode is '{source_mode}' not 'raw_source_refs'"
        )

    for field in LIST_FIELDS:
        if field in draft and not isinstance(draft[field], list):
            result.errors.append(
                f"{field} must be a list, got {type(draft[field]).__name__}"
            )

    limitations = draft.get("limitations")
    if limitations is not None and isinstance(limitations, list):
        if not limitations:
            result.warnings.append("limitations is empty list")
    elif limitations is None:
        result.errors.append("missing limitations")
    elif not isinstance(limitations, list):
        result.errors.append("limitations must be a list")

    if "confidence" not in draft:
        result.errors.append("missing confidence")
    else:
        conf = draft["confidence"]
        if not isinstance(conf, (int, float)):
            result.errors.append(
                f"confidence must be numeric, got {type(conf).__name__}"
            )

    evidence_refs = draft.get("evidence_refs", [])
    source_refs = draft.get("source_refs", [])
    if not evidence_refs and draft.get("confidence", 0) > 0:
        result.redline_flags.append("evidence_refs empty but confidence > 0")
    if not source_refs and draft.get("confidence", 0) > 0:
        result.warnings.append("source_refs empty but confidence > 0")

    result.shared_core_valid = len(result.errors) == 0


def validate_consumer_extension(draft: dict, result: ValidationResult) -> None:
    draft_type = draft.get("draft_type", "")

    if draft_type == "xingce_work_experience":
        result.consumer_type = "xingce_work_experience"
    elif draft.get("not_installed") is not None:
        result.consumer_type = "hermes_skill_draft"
    else:
        result.warnings.append(f"unknown consumer type (draft_type={draft_type!r})")

    if result.consumer_type == "hermes_skill_draft":
        if not draft.get("not_installed"):
            result.redline_flags.append("hermes not_installed is False/empty")
        if not draft.get("not_written_to_hermes"):
            result.redline_flags.append("hermes not_written_to_hermes is False/empty")
        if draft.get("install_ready") is True:
            result.redline_flags.append("hermes install_ready is True (forbidden)")

    if result.consumer_type == "xingce_work_experience":
        if not draft.get("not_ui_visible"):
            result.redline_flags.append("xingce not_ui_visible is False/empty")
        if not draft.get("not_written_to_platform"):
            result.redline_flags.append("xingce not_written_to_platform is False/empty")
        if not draft.get("not_production"):
            result.redline_flags.append("xingce not_production is False/empty")
        if draft.get("from_zhiyi_life_experience") is True:
            result.redline_flags.append("xingce from_zhiyi_life_experience is True")

    result.consumer_extension_valid = True


def validate_raw_evidence_draft(draft: dict[str, Any]) -> ValidationResult:
    result = ValidationResult(draft)
    validate_shared_core(draft, result)
    validate_consumer_extension(draft, result)
    result.ok = len(result.errors) == 0
    return result


def gate_raw_evidence_draft(
    draft: dict[str, Any],
    *,
    reject_redline: bool = True,
) -> ValidationResult:
    result = validate_raw_evidence_draft(draft)
    blockers: list[str] = []
    if result.errors:
        blockers.append("errors=" + "; ".join(result.errors))
    if reject_redline and result.redline_flags:
        blockers.append("redline_flags=" + "; ".join(result.redline_flags))
    if blockers:
        raise DraftContractGateError(
            "raw evidence draft contract gate blocked: " + " | ".join(blockers),
            result=result,
        )
    return result


HERMES_EXAMPLE = {
    "draft_id": "draft-abc123",
    "title": "Skill: Troubleshooting evidence review",
    "source_mode": "raw_source_refs",
    "observed_facts": ["Found evidence of session troubleshooting"],
    "inferred_workflow": ["1. Identify source files", "2. Extract evidence"],
    "recommended_procedure": ["1. Review source paths", "2. Verify hashes"],
    "verification_steps": ["1. Check evidence refs", "2. Run cross-check"],
    "rollback_or_stop_conditions": ["1. Stop if no matching evidence"],
    "failure_patterns": ["No matching data for query"],
    "evidence_refs": [{"source_path": "example.jsonl"}],
    "source_refs": ["example.jsonl"],
    "raw_excerpt_hashes": ["abc123"],
    "confidence": 0.7,
    "limitations": ["Draft only", "Not installed", "Not production ready"],
    "purpose": "Generate troubleshooting skill from evidence",
    "not_installed": True,
    "not_written_to_hermes": True,
}

XINGCE_EXAMPLE = {
    "draft_id": "xingce-def456",
    "title": "Xingce: Troubleshooting work experience",
    "source_mode": "raw_source_refs",
    "observed_facts": ["Observed troubleshooting pattern"],
    "inferred_workflow": ["1. Identify problem", "2. Check evidence"],
    "recommended_procedure": ["1. Verify source paths", "2. Apply procedure"],
    "verification_steps": ["1. Confirm evidence", "2. Validate scope"],
    "rollback_or_stop_conditions": ["1. Stop if no match"],
    "failure_patterns": ["No matching data"],
    "evidence_refs": [{"source_path": "example.jsonl"}],
    "source_refs": ["example.jsonl"],
    "raw_excerpt_hashes": ["def456"],
    "confidence": 0.7,
    "limitations": ["Draft only", "Not installed", "Not production ready"],
    "draft_type": "xingce_work_experience",
    "problem_pattern": "Troubleshooting session evidence",
    "not_ui_visible": True,
    "not_written_to_platform": True,
    "not_production": True,
    "from_zhiyi_life_experience": False,
}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", type=str, default=None)
    args = ap.parse_args()

    if args.draft:
        draft = json.loads(args.draft)
        result = validate_raw_evidence_draft(draft)
        print(json.dumps(result.to_dict(), indent=2))
    else:
        h = validate_raw_evidence_draft(HERMES_EXAMPLE)
        x = validate_raw_evidence_draft(XINGCE_EXAMPLE)
        print("Hermes example:", json.dumps(h.to_dict(), indent=2))
        print("Xingce example:", json.dumps(x.to_dict(), indent=2))


if __name__ == "__main__":
    main()
