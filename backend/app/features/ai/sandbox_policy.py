from __future__ import annotations

import os
from enum import Enum
from typing import Any, Optional

from app.core.config import get_settings
from app.features.ai.sandbox.executor import SandboxUnavailableError
from app.features.ai.harness.tool_executor import _is_command_safe
from app.features.ai.harness.approval_coordinator import _is_command_trusted


class ExecutionMode(str, Enum):
    ALLOWLIST_HOST = "ALLOWLIST_HOST"
    TRUSTED_HOST = "TRUSTED_HOST"
    APPROVAL_HOST = "APPROVAL_HOST"
    SANDBOX_REQUIRED = "SANDBOX_REQUIRED"
    BLOCKED = "BLOCKED"


SANDBOX_UNAVAILABLE_MESSAGE = (
    "This command requires container sandboxing, but Docker is not available. "
    "Install Docker or enable a container runtime to execute non-allowlisted commands in untrusted workspaces or strict mode."
)


def decide_execution_mode(
    workspace_trust: Any,
    cmd: str,
    strict_sandbox: Optional[bool] = None,
    docker_available: bool = True,
    workspace: str = "",
) -> ExecutionMode:
    """
    Server-side policy determining command isolation mode.
    Guarantees container sandboxing for untrusted workspaces and strict mode.
    Model-supplied flags cannot override this decision.

    Returns:
      ALLOWLIST_HOST: Safe allowlisted read-only command, runs on host without approval.
      TRUSTED_HOST: Matches user's trusted commands pattern in a trusted workspace.
      APPROVAL_HOST: Trusted workspace, non-allowlisted command -> requires user approval card.
      SANDBOX_REQUIRED: Untrusted workspace (or strict mode), requires Docker container execution.
      BLOCKED: Container required but Docker is unavailable -> fail closed.
    """
    # Normalize workspace trust if passed as dict from trust service
    if isinstance(workspace_trust, dict):
        is_trusted = bool(workspace_trust.get("trusted", False))
    else:
        is_trusted = bool(workspace_trust)

    if strict_sandbox is None:
        try:
            strict_sandbox = getattr(get_settings(), "strict_sandbox", False)
        except Exception:
            strict_sandbox = False

    cmd_clean = (cmd or "").strip()

    # 1. Safe host allowlist (safe read-only inspection commands)
    if _is_command_safe(cmd_clean, workspace):
        return ExecutionMode.ALLOWLIST_HOST

    # 2. Strict sandbox mode (when enabled, all non-allowlist commands require container)
    if strict_sandbox:
        if not docker_available:
            return ExecutionMode.BLOCKED
        return ExecutionMode.SANDBOX_REQUIRED

    # 3. Trusted workspace
    if is_trusted:
        if _is_command_trusted(workspace, cmd_clean):
            return ExecutionMode.TRUSTED_HOST
        return ExecutionMode.APPROVAL_HOST

    # 4. Untrusted workspace (must run in container; fail-closed if Docker unavailable)
    if not docker_available:
        return ExecutionMode.BLOCKED
    return ExecutionMode.SANDBOX_REQUIRED
