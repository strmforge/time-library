#!/usr/bin/env python3
"""
P9-System-X5: Rollback Plan Contract
Defines rollback plan schema and generation logic.
A rollback plan is a step-by-step recovery plan generated at update time.
It is NOT executed automatically; it is stored for operator review.
"""
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime

# rollback plan history file (append-only, never overwritten)
ROLLBACK_HISTORY_FILE = "update_history.jsonl"

# Steps that are ALWAYS part of any rollback
ROLLBACK_STEP_TYPES = {
    "restore": "Restore a backup",
    "reload": "Reload the service",
    "verify": "Verify integrity after restore",
    "rollback": "Rollback the current pointer",
}


@dataclass
class RollbackStep:
    """A single step in a rollback plan."""
    step: int
    action: str          # restore / reload / verify / rollback
    target: str          # What to act on
    description: str
    critical: bool = False   # If True, rollback cannot proceed without this step succeeding
    automatic: bool = True   # If True, can be executed automatically

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "action": self.action,
            "target": self.target,
            "description": self.description,
            "critical": self.critical,
            "automatic": self.automatic,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RollbackStep":
        return cls(
            step=d["step"],
            action=d["action"],
            target=d["target"],
            description=d["description"],
            critical=d.get("critical", False),
            automatic=d.get("automatic", True),
        )


@dataclass
class RollbackPlan:
    """
    A complete rollback plan for an update operation.
    Stored as a record in update_history.jsonl (append-only).
    """
    plan_id: str              # Unique ID: timestamp-based
    from_version: str
    to_version: str
    install_root: str
    package: str
    steps: List[RollbackStep] = field(default_factory=list)
    created_at: str = ""     # ISO timestamp
    status: str = "prepared" # prepared / applied / rolled_back / expired
    previous_pointer: Optional[str] = None  # What version to roll back to

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat() + "Z"
        if not self.plan_id:
            self.plan_id = f"rb_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "install_root": self.install_root,
            "package": self.package,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "status": self.status,
            "previous_pointer": self.previous_pointer,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RollbackPlan":
        return cls(
            plan_id=d["plan_id"],
            from_version=d["from_version"],
            to_version=d["to_version"],
            install_root=d["install_root"],
            package=d["package"],
            steps=[RollbackStep.from_dict(s) for s in d.get("steps", [])],
            created_at=d.get("created_at", ""),
            status=d.get("status", "prepared"),
            previous_pointer=d.get("previous_pointer"),
        )

    def to_json_line(self) -> str:
        """Return a JSONL line for appending to history."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json_line(cls, line: str) -> "RollbackPlan":
        return cls.from_dict(json.loads(line))

    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate rollback plan structural integrity.
        Returns (valid, errors).
        """
        errors = []
        if not self.plan_id:
            errors.append("plan_id is required")
        if not self.from_version or not self.to_version:
            errors.append("from_version and to_version are required")
        if not self.steps:
            errors.append("rollback plan must have at least one step")
        for i, step in enumerate(self.steps):
            if step.action not in ROLLBACK_STEP_TYPES:
                errors.append(f"step {i+1}: unknown action {step.action!r}")
            if not step.target:
                errors.append(f"step {i+1}: target is required")
            if step.step != i + 1:
                errors.append(f"step {i+1}: step number mismatch (expected {i+1})")
        # At least one restore step must be critical
        has_restore = any(s.action == "restore" and s.critical for s in self.steps)
        if not has_restore:
            errors.append("rollback plan must have at least one critical restore step")
        return len(errors) == 0, errors


def generate_rollback_plan(from_version: str, to_version: str,
                            install_root: str, package: str,
                            backup_dir: Optional[str] = None) -> RollbackPlan:
    """
    Generate a standard rollback plan for a given update.
    This is called at update-preparation time, not at rollback time.
    """
    steps = []
    backup_path = backup_dir or str(Path(install_root) / "src.bak")

    # Step 1: Restore backup
    steps.append(RollbackStep(
        step=1,
        action="restore",
        target=backup_path,
        description=f"Restore src/ from backup at {backup_path}",
        critical=True,
        automatic=True,
    ))

    # Step 2: Reload service
    steps.append(RollbackStep(
        step=2,
        action="reload",
        target="memcore-cloud.service",
        description="Reload memcore-cloud.service to pick up restored code",
        critical=True,
        automatic=True,
    ))

    # Step 3: Verify
    steps.append(RollbackStep(
        step=3,
        action="verify",
        target=f"{install_root}/VERSION",
        description=f"Verify VERSION file matches {from_version}",
        critical=True,
        automatic=False,  # Operator should verify this manually
    ))

    # Step 4: Rollback current pointer
    steps.append(RollbackStep(
        step=4,
        action="rollback",
        target=f"{install_root}/VERSION",
        description=f"Update VERSION back to {from_version}",
        critical=False,
        automatic=False,
    ))

    return RollbackPlan(
        plan_id=f"rb_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        from_version=from_version,
        to_version=to_version,
        install_root=install_root,
        package=package,
        steps=steps,
        previous_pointer=from_version,
        status="prepared",
    )


def append_rollback_history(plan: RollbackPlan, history_file: str) -> bool:
    """
    Append a rollback plan to the history file (append-only).
    Returns True on success.
    """
    try:
        p = Path(history_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(plan.to_json_line() + "\n")
        return True
    except Exception:
        return False


def load_rollback_history(history_file: str, limit: int = 10) -> List[RollbackPlan]:
    """Load recent rollback plans from history."""
    p = Path(history_file)
    if not p.exists():
        return []
    plans = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                plans.append(RollbackPlan.from_json_line(line))
            except Exception:
                pass
    return plans[-limit:]


if __name__ == "__main__":
    plan = generate_rollback_plan(
        from_version="0.1.0",
        to_version="2026.5.25",
        install_root="/opt/memcore-cloud",
        package="release/memcore-cloud-2026.5.25-linux-x86_64.tar.gz"  # rollback_asset_pending_until_clean_build,
    )
    valid, errs = plan.validate()
    print(json.dumps({"ok": valid, "errors": errs, "plan": plan.to_dict()}, indent=2, ensure_ascii=False))
