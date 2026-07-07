#!/usr/bin/env python3
"""Read-only Hermes skill vs Time Library experience diff helpers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    from hermes_paths import resolve_hermes_home
except Exception:
    from src.hermes_paths import resolve_hermes_home


HERMES_SKILL_EXPERIENCE_DIFF_VERSION = "2026.6.1"
DEFAULT_MAX_SKILLS = 20
DEFAULT_MAX_EXPERIENCES = 200
MATCH_THRESHOLD = 0.12


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in ("", None):
        return []
    return [value]


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _positive_int(value: Any, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(1, min(parsed, maximum))


def _sha(seed: str, size: int = 12) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:size]


def _compact(value: Any, limit: int = 400) -> str:
    text = re.sub(r"\s+", " ", _clean_text(value))
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "..."


def _tokens(text: str) -> set[str]:
    text = _clean_text(text).lower()
    found = re.findall(r"[a-z0-9_./:-]{2,}|[\u4e00-\u9fff]{2,}", text)
    tokens: set[str] = set()
    for item in found:
        if len(item) > 16 and re.search(r"[\u4e00-\u9fff]", item):
            for i in range(0, max(len(item) - 1, 0)):
                tokens.add(item[i:i + 2])
        else:
            tokens.add(item)
    return {item for item in tokens if item and item not in {"the", "and", "with", "this", "that"}}


def _source_refs_for_experience(record: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("source_refs", "_source_refs"):
        refs = record.get(key)
        if isinstance(refs, dict):
            return dict(refs)
        if isinstance(refs, str) and refs.strip():
            try:
                parsed = json.loads(refs)
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                return parsed
    source_path = _clean_text(record.get("source_path"))
    if source_path:
        return {
            "source_system": record.get("source_system", ""),
            "source_path": source_path,
            "session_id": record.get("session_id", ""),
        }
    return {}


def _experience_id(record: Dict[str, Any]) -> str:
    for key in ("library_id", "exp_id", "memory_id", "candidate_id", "id"):
        text = _clean_text(record.get(key))
        if text:
            return text
    seed = "|".join([
        _clean_text(record.get("summary")),
        _clean_text(record.get("detail")),
        _clean_text(_source_refs_for_experience(record).get("source_path")),
    ])
    return "experience-" + _sha(seed)


def _experience_text(record: Dict[str, Any]) -> str:
    parts = [
        record.get("title", ""),
        record.get("summary", ""),
        record.get("detail", ""),
        record.get("verbatim_excerpt", ""),
        record.get("raw_excerpt", ""),
    ]
    return "\n".join(_clean_text(part) for part in parts if _clean_text(part))


def _skill_title(text: str, fallback: str) -> str:
    for line in str(text or "").splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or fallback
    return fallback


def _skill_id_from_path(path: Path, hermes_home: Path) -> str:
    try:
        rel = path.relative_to(hermes_home / "skills")
    except Exception:
        rel = path.name
    text = str(rel).replace("\\", "/")
    if text.endswith("/SKILL.md"):
        text = text[:-len("/SKILL.md")]
    return text or path.stem


def _skill_record_from_file(path: Path, hermes_home: Path) -> Dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = ""
    stat = path.stat()
    skill_id = _skill_id_from_path(path, hermes_home)
    return {
        "skill_id": skill_id,
        "title": _skill_title(text, skill_id),
        "text": text,
        "source_refs": {
            "source_system": "hermes",
            "artifact_type": "hermes_skill_file",
            "source_path": str(path),
            "skill_id": skill_id,
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "verbatim_excerpt": _compact(text, 800),
    }


def _scan_hermes_skills(hermes_home: Path, max_skills: int, exclude_time_library: bool = True) -> List[Dict[str, Any]]:
    skills_root = hermes_home / "skills"
    if not skills_root.is_dir():
        return []
    paths = [path for path in skills_root.rglob("*.md") if path.is_file()]
    if exclude_time_library:
        paths = [
            path for path in paths
            if "time_library" not in str(path).lower() and "memcore" not in str(path).lower()
        ]
    paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [_skill_record_from_file(path, hermes_home) for path in paths[:max_skills]]


def _skills_from_body(body: Dict[str, Any], hermes_home: Path, max_skills: int) -> List[Dict[str, Any]]:
    supplied = [item for item in _as_list(body.get("skills") or body.get("skill_records")) if isinstance(item, dict)]
    if supplied:
        records = []
        for item in supplied[:max_skills]:
            text = _clean_text(item.get("text") or item.get("content") or item.get("verbatim_excerpt"))
            skill_id = _clean_text(item.get("skill_id") or item.get("id") or item.get("title")) or "hermes-skill-" + _sha(text)
            source_refs = _dict(item.get("source_refs"))
            if not source_refs:
                source_path = _clean_text(item.get("source_path"))
                source_refs = {
                    "source_system": "hermes",
                    "artifact_type": "hermes_skill_file",
                    "source_path": source_path,
                    "skill_id": skill_id,
                }
            records.append({
                "skill_id": skill_id,
                "title": _clean_text(item.get("title")) or _skill_title(text, skill_id),
                "text": text,
                "source_refs": source_refs,
                "verbatim_excerpt": _clean_text(item.get("verbatim_excerpt")) or _compact(text, 800),
            })
        return records
    return _scan_hermes_skills(
        hermes_home,
        max_skills=max_skills,
        exclude_time_library=body.get("exclude_time_library", True) is not False,
    )


def _read_jsonl(path: Path, limit: int) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                text = line.strip()
                if not text:
                    continue
                try:
                    item = json.loads(text)
                except Exception:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except Exception:
        return []
    return rows[-limit:]


def _experiences_from_body(body: Dict[str, Any], memcore_root: Path | None, max_experiences: int) -> List[Dict[str, Any]]:
    supplied = [
        item for item in _as_list(body.get("experiences") or body.get("records"))
        if isinstance(item, dict)
    ]
    if supplied:
        return supplied[:max_experiences]
    if not memcore_root:
        return []
    case_memory = memcore_root / "zhiyi" / "case_memory" / "case_memory.jsonl"
    return _read_jsonl(case_memory, max_experiences)


def _best_experience_match(skill_text: str, experiences: List[Dict[str, Any]]) -> Dict[str, Any]:
    skill_tokens = _tokens(skill_text)
    best: Dict[str, Any] = {"score": 0.0, "experience": None, "shared_terms": [], "skill_only_terms": sorted(skill_tokens)[:20]}
    if not skill_tokens:
        return best
    for exp in experiences:
        exp_text = _experience_text(exp)
        exp_tokens = _tokens(exp_text)
        if not exp_tokens:
            continue
        shared = sorted(skill_tokens & exp_tokens)
        union = skill_tokens | exp_tokens
        score = round(len(shared) / max(len(union), 1), 4)
        if score > best["score"]:
            best = {
                "score": score,
                "experience": exp,
                "shared_terms": shared[:20],
                "skill_only_terms": sorted(skill_tokens - exp_tokens)[:20],
            }
    return best


def _candidate_id(kind: str, skill_id: str, experience_id: str = "") -> str:
    return f"hermes-skill-exp-{kind}-" + _sha("|".join([kind, skill_id, experience_id]))


def _skill_source_refs(skill: Dict[str, Any]) -> Dict[str, Any]:
    refs = skill.get("source_refs")
    return refs if isinstance(refs, dict) else {}


def _candidate_for_comparison(skill: Dict[str, Any], comparison: Dict[str, Any], status: str) -> Dict[str, Any]:
    experience = comparison.get("matched_experience") or {}
    experience_id = _clean_text(experience.get("experience_id"))
    skill_id = _clean_text(skill.get("skill_id"))
    candidate_kind = "adoption" if not experience_id else "upgrade"
    candidate_type = (
        "hermes_skill_experience_adoption_candidate"
        if candidate_kind == "adoption"
        else "hermes_skill_experience_upgrade_candidate"
    )
    candidate = {
        "candidate_id": _candidate_id(candidate_kind, skill_id, experience_id),
        "candidate_type": candidate_type,
        "schema_version": HERMES_SKILL_EXPERIENCE_DIFF_VERSION,
        "status": "candidate",
        "source_mode": "hermes_skill_experience_diff",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "skill": {
            "skill_id": skill_id,
            "title": skill.get("title", ""),
            "source_refs": _skill_source_refs(skill),
            "verbatim_excerpt": skill.get("verbatim_excerpt", ""),
        },
        "matched_experience": experience,
        "comparison_result": comparison,
        "recommended_action": status,
        "experience_upgrade_ready": status in {
            "review_skill_as_new_experience_candidate",
            "review_skill_as_existing_experience_upgrade",
        },
        "requires_review": True,
        "activation_allowed": False,
        "write_boundary": {
            "write_performed": False,
            "raw_write_performed": False,
            "zhiyi_write_performed": False,
            "xingce_write_performed": False,
            "toolbook_write_performed": False,
            "errata_write_performed": False,
            "hermes_write_performed": False,
            "hermes_skill_write_performed": False,
            "openclaw_write_performed": False,
            "platform_write_performed": False,
            "production_experience_write_performed": False,
        },
        "notes": [
            "candidate_only",
            "skill_vs_experience_diff_is_read_only",
            "do_not_apply_without_separate_upgrade_gate",
        ],
    }
    return candidate


def get_hermes_skill_experience_diff_plan() -> Dict[str, Any]:
    """Return the read-only Hermes skill vs experience diff contract."""
    return {
        "ok": True,
        "version": HERMES_SKILL_EXPERIENCE_DIFF_VERSION,
        "read_only": True,
        "write_performed": False,
        "name": "Hermes Skill vs Experience Diff / Upgrade Loop",
        "zh_name": "Hermes 技能与经验对比升级",
        "endpoint": "/api/v1/hermes/skill-experience-diff/dry-run",
        "inputs": [
            "hermes_home or skills[]",
            "memcore_root or experiences[]",
        ],
        "outputs": [
            "skill_experience_comparisons",
            "hermes_skill_experience_upgrade_candidate",
            "hermes_skill_experience_adoption_candidate",
        ],
        "forbidden_by_default": [
            "write_hermes_skill",
            "write_hermes_memory",
            "write_production_experience",
            "promote_without_source_refs_or_user_gate",
        ],
        "notes": [
            "this fills the missing comparison layer between Hermes skill output and Time Library experience",
            "existing experience apply gates remain separate",
            "raw and source_refs stay authoritative",
        ],
    }


def build_hermes_skill_experience_diff_dry_run(
    body: Dict[str, Any] | None = None,
    *,
    hermes_home: str | Path | None = None,
    memcore_root: str | Path | None = None,
) -> Dict[str, Any]:
    """Compare Hermes skill files with Time Library experience records without writing."""
    body = body if isinstance(body, dict) else {}
    home = Path(hermes_home or body.get("hermes_home") or resolve_hermes_home()).expanduser()
    root = Path(memcore_root or body.get("memcore_root")).expanduser() if (memcore_root or body.get("memcore_root")) else None
    max_skills = _positive_int(body.get("max_skills"), DEFAULT_MAX_SKILLS, 100)
    max_experiences = _positive_int(body.get("max_experiences"), DEFAULT_MAX_EXPERIENCES, 1000)
    skills = _skills_from_body(body, home, max_skills=max_skills)
    experiences = _experiences_from_body(body, root, max_experiences=max_experiences)
    comparisons: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    for skill in skills:
        skill_text = _clean_text(skill.get("text") or skill.get("verbatim_excerpt"))
        match = _best_experience_match(skill_text, experiences)
        exp = match.get("experience") if isinstance(match.get("experience"), dict) else None
        matched_experience: Dict[str, Any] = {}
        if exp and match.get("score", 0.0) >= MATCH_THRESHOLD:
            exp_id = _experience_id(exp)
            matched_experience = {
                "experience_id": exp_id,
                "title": _compact(exp.get("title") or exp.get("summary") or exp_id, 120),
                "source_refs": _source_refs_for_experience(exp),
                "verbatim_excerpt": _clean_text(exp.get("verbatim_excerpt") or exp.get("raw_excerpt")),
            }
            status = (
                "review_skill_as_existing_experience_upgrade"
                if match.get("skill_only_terms")
                else "skill_already_covered_by_existing_experience"
            )
        else:
            status = "review_skill_as_new_experience_candidate"
        comparison = {
            "skill_id": skill.get("skill_id", ""),
            "skill_title": skill.get("title", ""),
            "skill_source_refs": _skill_source_refs(skill),
            "skill_verbatim_excerpt": skill.get("verbatim_excerpt", ""),
            "match_score": match.get("score", 0.0),
            "matched_experience": matched_experience,
            "shared_terms": match.get("shared_terms", []),
            "skill_only_terms": match.get("skill_only_terms", []),
            "comparison_status": status,
            "raw_authority": True,
        }
        comparisons.append(comparison)
        if status in {
            "review_skill_as_new_experience_candidate",
            "review_skill_as_existing_experience_upgrade",
        }:
            candidates.append(_candidate_for_comparison(skill, comparison, status))
    candidate_types = sorted({item.get("candidate_type", "") for item in candidates if item.get("candidate_type")})
    return {
        "ok": True,
        "version": HERMES_SKILL_EXPERIENCE_DIFF_VERSION,
        "dry_run": True,
        "read_only": True,
        "write_performed": False,
        "hermes_write_performed": False,
        "hermes_skill_write_performed": False,
        "production_experience_write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "hermes_home": str(home),
        "memcore_root": str(root) if root else "",
        "skills_count": len(skills),
        "experiences_count": len(experiences),
        "skill_experience_comparisons": comparisons,
        "upgrade_candidates": {
            "write_performed": False,
            "candidate_count": len(candidates),
            "candidate_types": candidate_types,
            "candidates": candidates,
        },
        "summary": {
            "matched_skill_count": sum(1 for item in comparisons if item.get("matched_experience")),
            "new_skill_candidate_count": sum(
                1 for item in comparisons
                if item.get("comparison_status") == "review_skill_as_new_experience_candidate"
            ),
            "upgrade_candidate_count": sum(
                1 for item in comparisons
                if item.get("comparison_status") == "review_skill_as_existing_experience_upgrade"
            ),
            "already_covered_count": sum(
                1 for item in comparisons
                if item.get("comparison_status") == "skill_already_covered_by_existing_experience"
            ),
        },
        "notes": [
            "fills_skill_vs_experience_comparison_gap",
            "candidate_only_no_apply",
            "no_hermes_skill_or_memory_write",
            "no_production_experience_write",
        ],
    }
