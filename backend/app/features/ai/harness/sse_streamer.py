"""
sse_streamer.py - Server-Sent Events (SSE) formatting and streaming utilities.

Preserves the exact frontend event contract expected by aiStore.ts and Monaco editor.
"""
from __future__ import annotations

import json
from typing import Any


def _sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a typed Server-Sent Event conforming to the SSE wire standard."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _sse_status(status_type: str, message: str, **kwargs: Any) -> str:
    payload = {"type": status_type, "message": message}
    payload.update(kwargs)
    return _sse_event("status", payload)


def _sse_checkpoint(turn_number: int, commit_hash: str, touched_files: list[str]) -> str:
    return _sse_event("checkpoint", {
        "turn_number": turn_number,
        "commit_hash": commit_hash,
        "touched_files": touched_files,
    })


def _sse_token(content: str) -> str:
    return _sse_event("token", {"content": content})


def _sse_tier_routing(tier: int, label: str, reason: str = "") -> str:
    return _sse_event("tier_routing", {
        "tier": tier,
        "label": label,
        "reason": reason,
    })


def _sse_ask_user(action_id: str, question: str, options: list[str]) -> str:
    return _sse_event("ask_user", {
        "action_id": action_id,
        "question": question,
        "options": options,
    })


def _sse_memory_updated(fact: str) -> str:
    return _sse_event("memory_updated", {
        "fact": fact,
    })


def _sse_plan(steps: list[Any], current: int = 0, **kwargs: Any) -> str:
    formatted_steps: list[dict[str, Any]] = []
    for s in steps:
        if hasattr(s, "to_dict"):
            formatted_steps.append(s.to_dict())
        elif isinstance(s, dict):
            formatted_steps.append(s)
        else:
            step_idx = len(formatted_steps)
            status_val = "done" if step_idx < current else ("running" if step_idx == current else "pending")
            formatted_steps.append({
                "id": f"step_{step_idx + 1}",
                "title": str(s),
                "status": status_val,
                "depends_on": [f"step_{step_idx}"] if step_idx > 0 else [],
            })
    payload: dict[str, Any] = {"steps": formatted_steps, "current": current}
    payload.update(kwargs)
    return _sse_event("plan", payload)


def _sse_approval_request(
    action_id: str,
    action_type: str,
    detail: str,
    reason: str,
    proposal_id: str = "",
    path: str = "",
    diff_summary: str = "",
    command: str = "",
    is_native_fallback: bool = False,
    **kwargs: Any,
) -> str:
    payload = {
        "action_id": action_id,
        "action_type": action_type,
        "detail": detail,
        "reason": reason,
        "proposal_id": proposal_id,
        "path": path,
        "diff_summary": diff_summary,
        "command": command or (detail if action_type == "command" else ""),
        "is_native_fallback": is_native_fallback,
    }
    payload.update(kwargs)
    return _sse_event("approval_request", payload)


def _sse_proposal(proposal_id: str, path: str, **kwargs: Any) -> str:
    payload = {"proposal_id": proposal_id, "path": path}
    payload.update(kwargs)
    return _sse_event("proposal", payload)


def _sse_command_result(
    command: str,
    output: str,
    exit_code: int = 0,
    success: bool = True,
    reason: str = "",
    **kwargs: Any,
) -> str:
    payload = {
        "command": command,
        "output": output,
        "exit_code": exit_code,
        "success": success,
    }
    if reason:
        payload["reason"] = reason
    payload.update(kwargs)
    return _sse_event("command_result", payload)


def _sse_metrics(
    iterations: int,
    tools_executed: int,
    duration_ms: float,
    tier: int = 0,
    tokens_used: int = 0,
) -> str:
    return _sse_event("metrics", {
        "iterations": iterations,
        "tools_executed": tools_executed,
        "duration_ms": duration_ms,
        "tier": tier,
        "tokens_used": tokens_used,
    })


def _sse_done(success: bool, message: str = "", **kwargs: Any) -> str:
    payload = {"success": success, "message": message}
    payload.update(kwargs)
    return _sse_event("done", payload)


def _sse_error(message: str, **kwargs: Any) -> str:
    payload = {"message": message}
    payload.update(kwargs)
    return _sse_event("error", payload)


class SSEStreamer:
    """Helper wrapper for structuring and emitting SSE events."""

    @staticmethod
    def status(status_type: str, message: str, **kwargs: Any) -> str:
        return _sse_status(status_type, message, **kwargs)

    @staticmethod
    def token(content: str) -> str:
        return _sse_token(content)

    @staticmethod
    def plan(steps: list[Any], current: int = 0, **kwargs: Any) -> str:
        return _sse_plan(steps, current, **kwargs)

    @staticmethod
    def approval_request(action_id: str, action_type: str, detail: str, reason: str, **kwargs: Any) -> str:
        return _sse_approval_request(action_id, action_type, detail, reason, **kwargs)

    @staticmethod
    def proposal(proposal_id: str, path: str, **kwargs: Any) -> str:
        return _sse_proposal(proposal_id, path, **kwargs)

    @staticmethod
    def command_result(command: str, output: str, exit_code: int = 0, success: bool = True, **kwargs: Any) -> str:
        return _sse_command_result(command, output, exit_code=exit_code, success=success, **kwargs)

    @staticmethod
    def metrics(iterations: int, tools_executed: int, duration_ms: float, tier: int = 0, tokens_used: int = 0) -> str:
        return _sse_metrics(iterations, tools_executed, duration_ms, tier=tier, tokens_used=tokens_used)

    @staticmethod
    def done(success: bool, message: str = "", **kwargs: Any) -> str:
        return _sse_done(success, message, **kwargs)

    @staticmethod
    def error(message: str, **kwargs: Any) -> str:
        return _sse_error(message, **kwargs)