from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .team_schemas import HandoffArtifact, HandoffType, TeamRole

logger = logging.getLogger(__name__)


def create_handoff(
    from_role: TeamRole | str,
    to_role: TeamRole | str,
    handoff_type: HandoffType,
    payload: dict[str, Any],
    summary: str = "",
    task_id: Optional[str] = None,
) -> HandoffArtifact:
    """Create a structured inter-agent handoff artifact."""
    return HandoffArtifact(
        type=handoff_type,
        from_role=from_role,
        to_role=to_role,
        task_id=task_id,
        payload=payload,
        summary=summary,
    )


def create_diff_handoff(
    from_role: TeamRole | str,
    to_role: TeamRole | str,
    diffs: list[dict[str, Any]] | list[str],
    modified_files: Optional[list[str]] = None,
    summary: str = "",
    task_id: Optional[str] = None,
) -> HandoffArtifact:
    """Create a code diff handoff artifact (e.g. Coder -> Reviewer or Coder -> Tester)."""
    payload = {
        "diffs": diffs,
        "modified_files": modified_files or [],
    }
    desc = summary or f"Code changes applied across {len(payload['modified_files'])} file(s)."
    return create_handoff(from_role, to_role, HandoffType.DIFFS, payload, summary=desc, task_id=task_id)


def create_test_output_handoff(
    from_role: TeamRole | str,
    to_role: TeamRole | str,
    test_output: str,
    passed: bool,
    exit_code: int = 0,
    command: str = "",
    summary: str = "",
    task_id: Optional[str] = None,
) -> HandoffArtifact:
    """Create a test execution output handoff (e.g. Tester -> Coder or Tester -> Reviewer)."""
    payload = {
        "command": command,
        "passed": passed,
        "exit_code": exit_code,
        "test_output": test_output,
    }
    status = "PASSED" if passed else f"FAILED (exit code {exit_code})"
    desc = summary or f"Test suite run completed: {status}"
    return create_handoff(from_role, to_role, HandoffType.TEST_OUTPUT, payload, summary=desc, task_id=task_id)


def create_review_notes_handoff(
    from_role: TeamRole | str,
    to_role: TeamRole | str,
    notes: list[str] | str,
    approved: bool,
    critical_issues: Optional[list[str]] = None,
    summary: str = "",
    task_id: Optional[str] = None,
) -> HandoffArtifact:
    """Create a review critique/verdict handoff (e.g. Reviewer -> Coder)."""
    payload = {
        "approved": approved,
        "notes": [notes] if isinstance(notes, str) else notes,
        "critical_issues": critical_issues or [],
    }
    verdict = "APPROVED" if approved else "CHANGES_REQUESTED"
    desc = summary or f"Code review completed: {verdict}"
    return create_handoff(from_role, to_role, HandoffType.REVIEW_NOTES, payload, summary=desc, task_id=task_id)


def create_files_handoff(
    from_role: TeamRole | str,
    to_role: TeamRole | str,
    files: list[dict[str, Any]] | list[str],
    summary: str = "",
    task_id: Optional[str] = None,
) -> HandoffArtifact:
    """Create a file inspection or specification handoff (e.g. Architect -> Coder)."""
    payload = {"files": files}
    desc = summary or f"Inspected files and architectural specifications ({len(files)} items)."
    return create_handoff(from_role, to_role, HandoffType.FILES, payload, summary=desc, task_id=task_id)


def create_stack_trace_handoff(
    from_role: TeamRole | str,
    to_role: TeamRole | str,
    traces: list[str] | str,
    command: str = "",
    summary: str = "",
    task_id: Optional[str] = None,
) -> HandoffArtifact:
    """Create a stack trace or runtime failure handoff (e.g. Tester/DevOps -> Coder)."""
    payload = {
        "command": command,
        "traces": [traces] if isinstance(traces, str) else traces,
    }
    desc = summary or "Runtime stack traces and failure diagnostics."
    return create_handoff(from_role, to_role, HandoffType.STACK_TRACES, payload, summary=desc, task_id=task_id)


def serialize_handoff(artifact: HandoffArtifact) -> str:
    """Serialize a HandoffArtifact into a JSON string."""
    return artifact.model_dump_json(indent=2)


def deserialize_handoff(data: str | dict[str, Any]) -> HandoffArtifact:
    """Deserialize a JSON string or dict into a HandoffArtifact."""
    if isinstance(data, str):
        return HandoffArtifact.model_validate_json(data)
    return HandoffArtifact.model_validate(data)


def format_handoff_for_prompt(artifact: HandoffArtifact) -> str:
    """Format a HandoffArtifact into a clear prompt block for the recipient agent."""
    lines = [
        f"=== INCOMING HANDOFF FROM [{artifact.from_role.value.upper()}] ===",
        f"Type: {artifact.type.value}",
        f"Summary: {artifact.summary}",
    ]

    payload = artifact.payload
    if artifact.type == HandoffType.DIFFS:
        files = payload.get("modified_files", [])
        if files:
            lines.append(f"Modified Files: {', '.join(files)}")
        diffs = payload.get("diffs", [])
        if diffs:
            lines.append("Diffs:")
            for d in diffs:
                lines.append(f"```diff\n{d}\n```" if isinstance(d, str) else json.dumps(d, indent=2))

    elif artifact.type == HandoffType.TEST_OUTPUT:
        lines.append(f"Command: {payload.get('command', 'N/A')}")
        lines.append(f"Passed: {payload.get('passed', False)}")
        lines.append(f"Exit Code: {payload.get('exit_code', 0)}")
        out = payload.get("test_output", "")
        if out:
            lines.append(f"Output:\n```\n{out}\n```")

    elif artifact.type == HandoffType.REVIEW_NOTES:
        lines.append(f"Verdict: {'APPROVED' if payload.get('approved', False) else 'CHANGES REQUESTED'}")
        crit = payload.get("critical_issues", [])
        if crit:
            lines.append("Critical Issues:")
            for c in crit:
                lines.append(f"  - [CRITICAL] {c}")
        notes = payload.get("notes", [])
        if notes:
            lines.append("Notes:")
            for n in notes:
                lines.append(f"  - {n}")

    elif artifact.type == HandoffType.STACK_TRACES:
        lines.append(f"Command: {payload.get('command', 'N/A')}")
        traces = payload.get("traces", [])
        lines.append("Stack Traces:")
        for t in traces:
            lines.append(f"```\n{t}\n```")

    elif artifact.type == HandoffType.FILES:
        files = payload.get("files", [])
        lines.append("Files / Specs:")
        lines.append(json.dumps(files, indent=2) if isinstance(files, (dict, list)) else str(files))

    else:
        lines.append(f"Payload:\n{json.dumps(payload, indent=2)}")

    lines.append("==================================================")
    return "\n".join(lines)
