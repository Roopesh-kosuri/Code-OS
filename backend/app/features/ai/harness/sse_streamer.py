"""
sse_streamer.py - Server-Sent Events (SSE) formatting and streaming utilities.

Preserves the exact frontend event contract expected by aiStore.ts and Monaco editor.
"""
from __future__ import annotations

import json
import re
from typing import Any


def _sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a typed Server-Sent Event conforming to the SSE wire standard."""
    return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


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


class StreamReasoningFilter:
    """Stream filter that intercepts reasoning tags, retry signals, and channel tokens.
    Routes reasoning text to thinking events with periodic token counts and clean user text to token events.
    """

    def __init__(self) -> None:
        self.buffer = ""
        self.in_thought = False
        self.thought_tag_close = ""
        self.accumulated_thought = ""
        self.last_reported_thought_tokens = 0

    def feed(self, token: str) -> list[tuple[str, Any]]:
        events: list[tuple[str, Any]] = []
        self.buffer += token

        # Intercept explicit retry events if yielded
        if "[STATUS_RETRY:" in self.buffer:
            m_retry = re.search(r"\[STATUS_RETRY:\s*([^\]]+)\]\n?", self.buffer)
            if m_retry:
                retry_msg = m_retry.group(1).strip()
                events.append(("retry", retry_msg))
                self.buffer = self.buffer[:m_retry.start()] + self.buffer[m_retry.end():]

        while self.buffer:
            if not self.in_thought:
                m_open = re.search(r"(<think>|<thought>|<reasoning>|<\|start\|>thought|commentary\s+to=|<\|start\|>to=)", self.buffer, re.IGNORECASE)
                if m_open:
                    prefix = self.buffer[:m_open.start()]
                    matched_str = m_open.group(0)
                    if prefix:
                        events.append(("token", prefix))
                    self.in_thought = True
                    matched_lower = matched_str.lower()
                    if "<|start|>thought" in matched_lower or "<|start|>to=" in matched_lower:
                        self.thought_tag_close = "<|end|>"
                    elif "<think>" in matched_lower:
                        self.thought_tag_close = "</think>"
                    elif "<thought>" in matched_lower:
                        self.thought_tag_close = "</thought>"
                    elif "<reasoning>" in matched_lower:
                        self.thought_tag_close = "</reasoning>"
                    elif "commentary" in matched_lower:
                        self.thought_tag_close = "\n"
                    self.buffer = self.buffer[m_open.end():]
                else:
                    m_part = re.search(r"(<[^\n]{0,20}|commentary[^\n]{0,5})$", self.buffer, re.IGNORECASE)
                    if m_part:
                        safe_len = m_part.start()
                        if safe_len > 0:
                            events.append(("token", self.buffer[:safe_len]))
                            self.buffer = self.buffer[safe_len:]
                        break
                    else:
                        events.append(("token", self.buffer))
                        self.buffer = ""
                        break
            else:
                if self.thought_tag_close:
                    idx = self.buffer.find(self.thought_tag_close)
                    if idx != -1:
                        thought_content = self.buffer[:idx]
                        self.accumulated_thought += thought_content
                        clean_thought = self.accumulated_thought.strip()
                        if clean_thought and not clean_thought.startswith("functions.") and not clean_thought.startswith("{"):
                            token_estimate = max(1, len(clean_thought) // 4)
                            events.append(("thinking", clean_thought))
                            events.append(("thinking_tokens", token_estimate))
                        self.buffer = self.buffer[idx + len(self.thought_tag_close):]
                        self.in_thought = False
                        self.thought_tag_close = ""
                        self.accumulated_thought = ""
                        self.last_reported_thought_tokens = 0
                    else:
                        self.accumulated_thought += self.buffer
                        clean_thought = self.accumulated_thought.strip()
                        if clean_thought and not clean_thought.startswith("functions.") and not clean_thought.startswith("{"):
                            token_estimate = max(1, len(clean_thought) // 4)
                            # Emit token count every ~50 tokens
                            if token_estimate - self.last_reported_thought_tokens >= 30:
                                self.last_reported_thought_tokens = token_estimate
                                events.append(("thinking_tokens", token_estimate))
                        self.buffer = ""
                        break
                else:
                    self.in_thought = False

        return events

    def flush(self) -> list[tuple[str, Any]]:
        events: list[tuple[str, Any]] = []
        if self.buffer:
            if not self.in_thought:
                events.append(("token", self.buffer))
            else:
                clean_thought = (self.accumulated_thought + self.buffer).strip()
                if clean_thought and not clean_thought.startswith("functions.") and not clean_thought.startswith("{"):
                    token_estimate = max(1, len(clean_thought) // 4)
                    events.append(("thinking", clean_thought))
                    events.append(("thinking_tokens", token_estimate))
            self.buffer = ""
        elif self.in_thought and self.accumulated_thought:
            clean_thought = self.accumulated_thought.strip()
            if clean_thought and not clean_thought.startswith("functions.") and not clean_thought.startswith("{"):
                token_estimate = max(1, len(clean_thought) // 4)
                events.append(("thinking", clean_thought))
                events.append(("thinking_tokens", token_estimate))
            self.accumulated_thought = ""
        return events


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
