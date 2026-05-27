#!/usr/bin/env python3
"""
Installer flow state machine
Simulates the interactive user flow for one-command installer.

States:
  INIT → PLATFORM_DETECTED → PATH_SELECTED → PLAN_GENERATED
      → CONFIRMED → COMPLETE (or BLOCKED/ABORTED)

Usage:
  from installer_flow import InstallerFlow, FlowState
  flow = InstallerFlow()
  flow.detect_platform()
  flow.select_path(custom_path)
  flow.generate_plan()
  flow.confirm()
  print(flow.get_current_state())
"""
import sys, json
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from install_bootstrap import detect_platform, expand_windows_path, is_windows_dangerous, DEFAULT_INSTALL_ROOTS


class FlowState(Enum):
    INIT = "init"
    PLATFORM_DETECTED = "platform_detected"
    PATH_SELECTED = "path_selected"
    PLAN_GENERATED = "plan_generated"
    CONFIRMED = "confirmed"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    ABORTED = "aborted"


class InstallerFlow:
    """
    Installer user flow state machine.
    Simulates interactive user experience without real installation.
    """

    def __init__(self, simulate_platform: str = None):
        self.state = FlowState.INIT
        self.platform = None
        self.install_root = None
        self.install_mode = "user"
        self.plan = None
        self.messages = []
        self.blocked_reason = None
        self._simulate_platform = simulate_platform

    def detect_platform(self) -> dict:
        """Step 1: Detect platform."""
        if self._simulate_platform:
            self.platform = self._simulate_platform
        else:
            self.platform = detect_platform()
        self.state = FlowState.PLATFORM_DETECTED
        self.messages.append({
            "step": 1,
            "action": "platform_detected",
            "state": self.state.value,
            "platform": self.platform,
            "message": f"Platform detected: {self.platform}",
        })
        return self._last_message()

    def select_path(self, custom_path: str = None, install_mode: str = "user") -> dict:
        """Step 2: Select install path."""
        if self.state != FlowState.PLATFORM_DETECTED:
            raise ValueError(f"Cannot select path in state {self.state}")

        self.install_mode = install_mode
        if custom_path:
            self.install_root = custom_path
        else:
            self.install_root = DEFAULT_INSTALL_ROOTS.get(self.platform, "/opt/memcore-cloud")

        # Expand Windows env vars
        if self.platform == "windows":
            self.install_root = expand_windows_path(self.install_root)
            dangerous, reason = is_windows_dangerous(self.install_root)
            if dangerous:
                self.state = FlowState.BLOCKED
                self.blocked_reason = reason
                self.messages.append({
                    "step": 2,
                    "action": "path_blocked",
                    "state": self.state.value,
                    "install_root": self.install_root,
                    "dangerous": True,
                    "reason": reason,
                    "message": f"Path blocked: {reason}",
                })
                return self._last_message()

        self.state = FlowState.PATH_SELECTED
        self.messages.append({
            "step": 2,
            "action": "path_selected",
            "state": self.state.value,
            "install_root": self.install_root,
            "install_mode": self.install_mode,
            "message": f"Install root selected: {self.install_root}",
        })
        return self._last_message()

    def generate_plan(self) -> dict:
        """Step 3: Generate install plan."""
        if self.state not in (FlowState.PATH_SELECTED, FlowState.BLOCKED):
            raise ValueError(f"Cannot generate plan in state {self.state}")

        if self.state == FlowState.BLOCKED:
            self.messages.append({
                "step": 3,
                "action": "plan_blocked",
                "state": self.state.value,
                "reason": self.blocked_reason,
                "message": "Install plan blocked due to dangerous path",
            })
            return self._last_message()

        self.plan = self._make_plan()
        self.state = FlowState.PLAN_GENERATED
        self.messages.append({
            "step": 3,
            "action": "plan_generated",
            "state": self.state.value,
            "plan_id": self.plan["plan_id"],
            "message": "Install plan generated",
        })
        return self._last_message()

    def confirm(self) -> dict:
        """Step 4: User confirms installation."""
        if self.state != FlowState.PLAN_GENERATED:
            raise ValueError(f"Cannot confirm in state {self.state}")
        self.state = FlowState.CONFIRMED
        self.messages.append({
            "step": 4,
            "action": "confirmed",
            "state": self.state.value,
            "message": "User confirmed installation plan",
        })
        return self._last_message()

    def complete(self) -> dict:
        """Step 5: Complete (dry-run, no real install)."""
        if self.state != FlowState.CONFIRMED:
            raise ValueError(f"Cannot complete in state {self.state}")
        self.state = FlowState.COMPLETE
        self.messages.append({
            "step": 5,
            "action": "complete",
            "state": self.state.value,
            "note": "dry-run: no real installation executed",
            "message": "Installation flow complete (dry-run)",
        })
        return self._last_message()

    def abort(self) -> dict:
        """User aborts installation."""
        self.state = FlowState.ABORTED
        self.messages.append({
            "step": -1,
            "action": "aborted",
            "state": self.state.value,
            "message": "User aborted installation",
        })
        return self._last_message()

    def run_full_flow(self, custom_path: str = None, install_mode: str = "user", auto_confirm: bool = False) -> dict:
        """
        Run the complete flow from platform detection to completion.
        Returns the final state with all messages.
        """
        self.detect_platform()
        self.select_path(custom_path, install_mode)
        self.generate_plan()
        if self.state == FlowState.PLAN_GENERATED:
            if auto_confirm:
                self.confirm()
                self.complete()
            else:
                # In interactive mode, would prompt user here
                # In dry-run prototype, show plan and stop at CONFIRMED
                self.confirm()
        return self.to_json()

    def to_json(self) -> dict:
        """Export full flow state as JSON."""
        ok = self.state in (FlowState.PLAN_GENERATED, FlowState.CONFIRMED, FlowState.COMPLETE)
        return {
            "flow_id": f"installer_flow_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "ok": ok,
            "state": self.state.value,
            "platform": self.platform,
            "install_root": self.install_root,
            "install_mode": self.install_mode,
            "plan": self.plan,
            "blocked_reason": self.blocked_reason,
            "messages": self.messages,
            "dry_run": True,
            "installed": False,
            "post_install_smoke_plan": self._smoke_plan() if self.plan else None,
            "future_actions": self._future_actions() if self.plan else None,
            "dashboard_status": {
                "stage": f"installer_flow_{self.state.value}",
                "install_mode": self.install_mode,
                "platform": self.platform,
                "dry_run": True,
            },
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

    def get_current_state(self) -> FlowState:
        return self.state

    def _last_message(self) -> dict:
        return self.messages[-1] if self.messages else {}

    def _make_plan(self) -> dict:
        """Build install plan JSON."""
        now = datetime.utcnow().isoformat() + "Z"
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return {
            "plan_id": f"install_plan_{ts}",
            "ok": True,
            "platform": self.platform,
            "version": "2026.5.25",
            "install_root": self.install_root,
            "install_mode": self.install_mode,
            "permission_model": "user_owned",
            "stage": "install_plan_ready",
            "dry_run": True,
            "installed": False,
            "steps": [
                {"step": 1, "action": "verify_package", "description": "Verify SHA256 checksum", "required": True},
                {"step": 2, "action": "check_install_root", "description": f"Validate {self.install_root}", "required": True},
                {"step": 3, "action": "create_directories", "description": "Create config/data/memory/logs/output", "required": True},
                {"step": 4, "action": "extract_package", "description": "Extract package to install root", "required": True},
                {"step": 5, "action": "install_entrypoint", "description": "Install launcher script", "required": True},
                {"step": 6, "action": "set_permissions", "description": "Set executable permissions", "required": True},
                {"step": 7, "action": "run_smoke", "description": "Execute platform_smoke.py", "required": True},
                {"step": 8, "action": "report_status", "description": "Write install result JSON", "required": True},
            ],
        }

    def _smoke_plan(self) -> dict:
        """Post-install smoke plan."""
        return {
            "smoke_after_install": True,
            "smoke_command": "python3 tools/platform_smoke.py",
            "checks": [
                "platform_smoke.py returns 0",
                "config directory created",
                "data directory created",
                "memory directory created",
                "entrypoint executable",
            ],
            "future_uninstall": "python3 install.sh --uninstall",
            "future_repair": "python3 install.sh --repair",
            "future_rollback": "python3 install.sh --rollback",
        }

    def _future_actions(self) -> list:
        """Future action entries shown to user."""
        return [
            {"action": "uninstall", "command": "python3 install.sh --uninstall", "description": "Remove installation"},
            {"action": "repair", "command": "python3 install.sh --repair", "description": "Verify and repair installation"},
            {"action": "rollback", "command": "python3 install.sh --rollback", "description": "Rollback to previous version"},
            {"action": "update", "command": "python3 tools/update_dry_run.py --platform " + (self.platform or "linux"), "description": "Check for updates (dry-run)"},
        ]
