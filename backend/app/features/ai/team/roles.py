from __future__ import annotations

import os
import re
import logging
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from ....core.paths import normalize_workspace
from ..agents.agent_tools import (
    ToolResult,
    _handle_read_file,
    _handle_list_directory,
    _handle_search_code,
    _handle_edit_file,
    _handle_run_test,
)
from .team_schemas import TeamRole

logger = logging.getLogger(__name__)


def is_test_file_path(path_str: str) -> bool:
    """Determine if a file path belongs to a test suite."""
    p = path_str.strip().replace("\\", "/").lower()
    parts = p.split("/")
    filename = parts[-1]

    # Directory checks
    if any(part in ("tests", "test", "__tests__", "spec", "specs") for part in parts[:-1]):
        return True

    # Filename checks
    if filename.startswith("test_") or filename.endswith("_test.py"):
        return True
    if any(filename.endswith(ext) for ext in (
        ".test.ts", ".test.js", ".test.tsx", ".test.jsx",
        ".spec.ts", ".spec.js", ".spec.tsx", ".spec.jsx"
    )):
        return True

    return False


DEVOPS_ALLOWLIST_PREFIXES = (
    "git ",
    "git.exe ",
    "npm ",
    "npm.cmd ",
    "npx ",
    "npx.cmd ",
    "pytest",
    "python -m pytest",
    "python.exe -m pytest",
)


class BaseTeamRole(ABC):
    """Abstract base class for all multi-agent team roles."""
    role: TeamRole
    allowed_tools: set[str]

    def validate_tool_permission(self, tool_name: str, arguments: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
        """Check whether the tool (and its specific arguments) is permitted for this role."""
        if tool_name not in self.allowed_tools:
            return False, f"Tool '{tool_name}' is disallowed for role '{self.role.value}'."
        return True, ""

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        workspace: str,
        staged_changes: Optional[list] = None,
        raise_on_disallowed: bool = True,
    ) -> ToolResult:
        """Execute a tool call subject to strict role permission enforcement."""
        allowed, reason = self.validate_tool_permission(tool_name, arguments)
        if not allowed:
            logger.warning("Tool permission denied: [%s] %s -> %s", self.role.value, tool_name, reason)
            if raise_on_disallowed:
                raise PermissionError(f"Permission denied for role '{self.role.value}': {reason}")
            return ToolResult(tool_name=tool_name, success=False, output="", error=reason)

        return self._dispatch_tool(tool_name, arguments, workspace, staged_changes)

    def _dispatch_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        workspace: str,
        staged_changes: Optional[list] = None,
    ) -> ToolResult:
        """Execute the allowed tool handler."""
        if tool_name == "read_file":
            return _handle_read_file(workspace, arguments)
        elif tool_name == "list_directory":
            return _handle_list_directory(workspace, arguments)
        elif tool_name == "search_code":
            return _handle_search_code(workspace, arguments)
        elif tool_name == "run_test":
            return _handle_run_test(workspace, arguments)
        elif tool_name == "edit_file":
            changes = staged_changes if staged_changes is not None else []
            return _handle_edit_file(workspace, arguments, changes)
        elif tool_name == "git_diff":
            return self._handle_git_diff(workspace, arguments)
        elif tool_name == "git_log":
            return self._handle_git_log(workspace, arguments)
        elif tool_name == "run_command":
            return self._handle_run_command(workspace, arguments)

        return ToolResult(tool_name=tool_name, success=False, output="", error=f"Unknown tool handler: {tool_name}")

    def _handle_git_diff(self, workspace: str, arguments: dict[str, Any]) -> ToolResult:
        """Run git diff safely in workspace."""
        norm_ws = normalize_workspace(workspace)
        target = arguments.get("target", "HEAD")
        cmd = ["git", "diff"]
        if target and target != "HEAD":
            cmd.append(target)
        try:
            res = subprocess.run(cmd, cwd=str(norm_ws), capture_output=True, text=True, timeout=20.0)
            diff_text = res.stdout or "(no diffs found)"
            return ToolResult(tool_name="git_diff", success=True, output=diff_text)
        except Exception as exc:
            return ToolResult(tool_name="git_diff", success=False, output="", error=f"git diff failed: {exc}")

    def _handle_git_log(self, workspace: str, arguments: dict[str, Any]) -> ToolResult:
        """Run git log safely in workspace."""
        norm_ws = normalize_workspace(workspace)
        limit = min(int(arguments.get("limit", 10)), 50)
        cmd = ["git", "log", f"-n{limit}", "--oneline"]
        try:
            res = subprocess.run(cmd, cwd=str(norm_ws), capture_output=True, text=True, timeout=20.0)
            log_text = res.stdout or "(empty git log)"
            return ToolResult(tool_name="git_log", success=True, output=log_text)
        except Exception as exc:
            return ToolResult(tool_name="git_log", success=False, output="", error=f"git log failed: {exc}")

    def _handle_run_command(self, workspace: str, arguments: dict[str, Any]) -> ToolResult:
        """Default run_command handler (must be overridden or guarded)."""
        return ToolResult(tool_name="run_command", success=False, output="", error="Arbitrary run_command is not permitted.")


class ArchitectRole(BaseTeamRole):
    """Architect Role: Read-only workspace inspection and planning ONLY."""
    role = TeamRole.ARCHITECT
    allowed_tools = {"read_file", "list_directory", "search_code"}


class CoderRole(BaseTeamRole):
    """Coder Role: Read, search, edit files, and execute targeted test runs."""
    role = TeamRole.CODER
    allowed_tools = {"read_file", "list_directory", "search_code", "edit_file", "run_test"}


class ReviewerRole(BaseTeamRole):
    """Reviewer Role: Read-only audits using file reading, searching, git diff, and git log."""
    role = TeamRole.REVIEWER
    allowed_tools = {"read_file", "list_directory", "search_code", "git_diff", "git_log"}


class TesterRole(BaseTeamRole):
    """Tester Role: Execute test suites, read files, and edit test files ONLY."""
    role = TeamRole.TESTER
    allowed_tools = {"read_file", "list_directory", "run_test", "edit_file"}

    def validate_tool_permission(self, tool_name: str, arguments: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
        base_allowed, base_reason = super().validate_tool_permission(tool_name, arguments)
        if not base_allowed:
            return False, base_reason

        # Tester is strictly restricted to editing test files
        if tool_name == "edit_file":
            target_path = ""
            if arguments:
                target_path = arguments.get("path", "")
            if not target_path or not is_test_file_path(target_path):
                return False, f"TesterRole is strictly restricted to test files (e.g. tests/**, *.test.*). Cannot edit '{target_path}'."

        return True, ""


class DevOpsRole(BaseTeamRole):
    """DevOps Role: Workspace inspection and allowlisted command execution (git, npm, pytest)."""
    role = TeamRole.DEVOPS
    allowed_tools = {"read_file", "list_directory", "run_command"}

    def validate_tool_permission(self, tool_name: str, arguments: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
        base_allowed, base_reason = super().validate_tool_permission(tool_name, arguments)
        if not base_allowed:
            return False, base_reason

        if tool_name == "run_command":
            cmd = ""
            if arguments:
                cmd = (arguments.get("command", "") or arguments.get("cmd", "")).strip()
            if not cmd:
                return False, "DevOpsRole: run_command requires a non-empty 'command' argument."

            # Check against allowlist prefixes
            cmd_lower = cmd.lower()
            if not any(cmd_lower.startswith(p) or cmd_lower == p.strip() for p in DEVOPS_ALLOWLIST_PREFIXES):
                return False, f"DevOpsRole command '{cmd}' is not allowlisted. Permitted: git, npm, npx, pytest."

        return True, ""

    def _handle_run_command(self, workspace: str, arguments: dict[str, Any]) -> ToolResult:
        """Run allowlisted shell commands safely in workspace."""
        cmd = arguments.get("command", "") or arguments.get("cmd", "")
        norm_ws = normalize_workspace(workspace)
        try:
            if os.name == "nt":
                args = ["powershell", "-NoLogo", "-NoProfile", "-Command", cmd]
            else:
                args = ["bash", "-c", cmd]

            proc = subprocess.run(
                args,
                cwd=str(norm_ws),
                capture_output=True,
                text=True,
                timeout=45.0,
            )
            raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
            success = proc.returncode == 0
            return ToolResult(
                tool_name="run_command",
                success=success,
                output=raw.strip(),
                error="" if success else f"Command exited with code {proc.returncode}",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(tool_name="run_command", success=False, output="", error=f"Command timed out: {cmd}")
        except Exception as exc:
            return ToolResult(tool_name="run_command", success=False, output="", error=f"Execution error: {exc}")


ROLE_REGISTRY: dict[TeamRole, type[BaseTeamRole]] = {
    TeamRole.ARCHITECT: ArchitectRole,
    TeamRole.CODER: CoderRole,
    TeamRole.REVIEWER: ReviewerRole,
    TeamRole.TESTER: TesterRole,
    TeamRole.DEVOPS: DevOpsRole,
}


def get_role_instance(role: TeamRole | str) -> BaseTeamRole:
    """Instantiate a role handler from a TeamRole enum or string."""
    r = TeamRole(role) if isinstance(role, str) else role
    cls = ROLE_REGISTRY.get(r)
    if not cls:
        raise ValueError(f"No role implementation registered for {role}")
    return cls()
