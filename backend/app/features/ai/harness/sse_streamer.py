"""
sse_streamer.py - Server-Sent Events (SSE) formatting and streaming utilities.

Preserves the exact frontend event contract expected by aiStore.ts and Monaco editor.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .payload_governor import get_token_count


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


def _sse_escalation_recommendation(recommended: bool, reasoning: str, confidence: float, action_id: str = "") -> str:
    data = {
        "recommended": recommended,
        "reasoning": reasoning,
        "confidence": confidence,
    }
    if action_id:
        data["action_id"] = action_id
    return _sse_event("escalation_recommendation", data)



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
    surgical_edits: int = 0,
    fullfile_edits: int = 0,
) -> str:
    return _sse_event("metrics", {
        "iterations": iterations,
        "tools_executed": tools_executed,
        "duration_ms": duration_ms,
        "tier": tier,
        "tokens_used": tokens_used,
        "surgical_edits": surgical_edits,
        "fullfile_edits": fullfile_edits,
    })


def _sse_done(success: bool, message: str = "", **kwargs: Any) -> str:
    payload = {"success": success, "message": message}
    payload.update(kwargs)
    return _sse_event("done", payload)


def _sse_error(message: str, **kwargs: Any) -> str:
    payload = {"message": message}
    payload.update(kwargs)
    return _sse_event("error", payload)


_SAN_PATTERNS = [
    re.compile(r"\[PROPOSAL:\s*[^\]]+\][\s\S]*?(?:>{2,}|(?=\[(?:PROPOSAL|TOOL_CALL)|\Z))", re.IGNORECASE),
    re.compile(r"\[TOOL_CALL:\s*[a-zA-Z0-9_\-]+\][\s\S]*?(?:\[/TOOL_CALL\]|(?=\[(?:PROPOSAL|TOOL_CALL)|\Z))", re.IGNORECASE),
    re.compile(r"\[/TOOL_CALL\]", re.IGNORECASE),
    re.compile(r"<{4,}\s*(?:ORIGINAL)?", re.IGNORECASE),
    re.compile(r"={4,}", re.IGNORECASE),
    re.compile(r">{4,}", re.IGNORECASE),
    re.compile(r"\[DONE\]", re.IGNORECASE),
    re.compile(r"<\|(?:im_start|im_end|start|end|pad|eot|fim_prefix|fim_suffix|fim_middle).*?\|>", re.IGNORECASE),
    re.compile(r"<\|(?:start|to=).*?>", re.IGNORECASE),
]


def sanitize_displayed_text(text: str | None) -> str:
    """Universal marker sanitization for all agent display surfaces (Phase 10.19 Part B).
    Strips:
    - [PROPOSAL: ...], <<<<, ====, >>>>
    - [TOOL_CALL: ...], [/TOOL_CALL]
    - [DONE]
    - Leaked model control tokens (<|im_start|>, <|end|>, etc.)
    """
    if not text or not isinstance(text, str):
        return ""
    s = text
    for pat in _SAN_PATTERNS:
        s = pat.sub("", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


class StreamReasoningFilter:
    """Stream filter that intercepts reasoning tags, machine tool-call blocks, and channel tokens.
    Routes reasoning text to thinking events, suppresses machine tool calls from user prose, and emits clean user text to token events.
    """

    def __init__(self, provider: str = "", model: str = "") -> None:
        self.provider = provider
        self.model = model
        self.buffer = ""
        self.in_thought = False
        self.thought_tag_close = ""
        self.accumulated_thought = ""
        self.last_reported_thought_tokens = 0
        self.in_tool_call = False
        self.tool_tag_close = ""
        self.in_proposal = False

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
            if not self.in_thought and not self.in_tool_call and not self.in_proposal:
                # 1. Check for reasoning tag openers
                m_open = re.search(r"(<think>|<thought>|<reasoning>|<\|start\|>\s*thought|commentary\s+to=|<\|start\|>\s*to=)", self.buffer, re.IGNORECASE)
                # 2. Check for tool-call openers to suppress from chat bubble
                m_tool = re.search(r"(\[TOOL_CALL:\s*[a-zA-Z0-9_\-]+|```(?:tool_call|json)?\s*\n?\s*\{\s*\"(?:tool|name|action)\"\s*:)", self.buffer, re.IGNORECASE)
                # 3. Check for proposal openers to suppress from chat bubble prose
                m_prop = re.search(r"(\[PROPOSAL:\s*[^\]]+\])", self.buffer, re.IGNORECASE)
                # 4. Check for standalone [DONE] or control tokens
                m_done = re.search(r"(\[DONE\]|<\|start\|>assistant\n?|<\|(?:im_start|im_end|end|pad|eot|fim_prefix|fim_suffix|fim_middle).*?\|>)", self.buffer, re.IGNORECASE)

                # Find earliest match among all blockers
                candidates = []
                if m_open: candidates.append(("open", m_open.start(), m_open))
                if m_tool: candidates.append(("tool", m_tool.start(), m_tool))
                if m_prop: candidates.append(("prop", m_prop.start(), m_prop))
                if m_done: candidates.append(("done", m_done.start(), m_done))

                if candidates:
                    candidates.sort(key=lambda x: x[1])
                    kind, start_pos, m_match = candidates[0]
                    prefix = self.buffer[:start_pos]
                    if prefix:
                        events.append(("token", prefix))

                    if kind == "open":
                        self.in_thought = True
                        matched_lower = m_match.group(0).lower()
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
                        self.buffer = self.buffer[m_match.end():]
                    elif kind == "tool":
                        self.in_tool_call = True
                        if "[tool_call:" in m_match.group(0).lower():
                            self.tool_tag_close = "[/TOOL_CALL]"
                        else:
                            self.tool_tag_close = "```"
                        self.buffer = self.buffer[m_match.end():]
                    elif kind == "prop":
                        self.in_proposal = True
                        self.buffer = self.buffer[m_match.end():]
                    elif kind == "done":
                        # Simply consume and suppress [DONE] / leaked control tokens
                        self.buffer = self.buffer[m_match.end():]
                else:
                    m_part = re.search(r"(<[^\n]{0,20}|commentary[^\n]{0,5}|\[[^\n]{0,20}|```[^\n]{0,10})$", self.buffer, re.IGNORECASE)
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
            elif self.in_tool_call:
                # Suppress tool call contents from token stream
                if self.tool_tag_close:
                    idx = self.buffer.find(self.tool_tag_close)
                    if idx != -1:
                        self.buffer = self.buffer[idx + len(self.tool_tag_close):]
                        self.in_tool_call = False
                        self.tool_tag_close = ""
                    else:
                        self.buffer = ""
                        break
                else:
                    self.buffer = ""
                    break
            elif self.in_proposal:
                # Suppress proposal contents from token stream
                m_end = re.search(r"(>{4,}|\[DONE\]|(?=\[PROPOSAL:)|(?=\[TOOL_CALL:))", self.buffer, re.IGNORECASE)
                if m_end:
                    self.buffer = self.buffer[m_end.end():]
                    self.in_proposal = False
                else:
                    # Buffer inside proposal without leaking to token stream
                    self.buffer = ""
                    break
            else:
                # Inside thinking block
                if self.thought_tag_close:
                    idx = self.buffer.find(self.thought_tag_close)
                    if idx != -1:
                        thought_content = self.buffer[:idx]
                        self.accumulated_thought += thought_content
                        clean_thought = self.accumulated_thought.strip()
                        if clean_thought and not clean_thought.startswith("functions.") and not clean_thought.startswith("{"):
                            token_estimate = get_token_count(clean_thought, self.provider, self.model)
                            events.append(("thinking", clean_thought))
                            if token_estimate is not None:
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
                            token_estimate = get_token_count(clean_thought, self.provider, self.model)
                            # Emit token count every ~50 tokens
                            if token_estimate is not None and token_estimate - self.last_reported_thought_tokens >= 30:
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
            if not self.in_thought and not self.in_tool_call and not self.in_proposal:
                clean_buf = sanitize_displayed_text(self.buffer)
                if clean_buf:
                    events.append(("token", clean_buf))
            elif self.in_thought:
                clean_thought = (self.accumulated_thought + self.buffer).strip()
                if clean_thought and not clean_thought.startswith("functions.") and not clean_thought.startswith("{"):
                    token_estimate = get_token_count(clean_thought, self.provider, self.model)
                    events.append(("thinking", clean_thought))
                    if token_estimate is not None:
                        events.append(("thinking_tokens", token_estimate))
            self.buffer = ""
            self.in_tool_call = False
            self.tool_tag_close = ""
            self.in_proposal = False
        elif self.in_thought and self.accumulated_thought:
            clean_thought = self.accumulated_thought.strip()
            if clean_thought and not clean_thought.startswith("functions.") and not clean_thought.startswith("{"):
                token_estimate = get_token_count(clean_thought, self.provider, self.model)
                events.append(("thinking", clean_thought))
                if token_estimate is not None:
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
    def metrics(
        iterations: int,
        tools_executed: int,
        duration_ms: float,
        tier: int = 0,
        tokens_used: int = 0,
        surgical_edits: int = 0,
        fullfile_edits: int = 0,
    ) -> str:
        return _sse_metrics(
            iterations,
            tools_executed,
            duration_ms,
            tier=tier,
            tokens_used=tokens_used,
            surgical_edits=surgical_edits,
            fullfile_edits=fullfile_edits,
        )

    @staticmethod
    def done(success: bool, message: str = "", **kwargs: Any) -> str:
        return _sse_done(success, message, **kwargs)

    @staticmethod
    def error(message: str, **kwargs: Any) -> str:
        return _sse_error(message, **kwargs)
