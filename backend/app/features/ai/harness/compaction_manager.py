from __future__ import annotations

import re
from typing import Any, Dict, List

from app.features.ai.schemas import ChatMessage

_EXTENDED_TOOL_RE = re.compile(
    r"\[TOOL_CALL:\s*(?P<name>[a-z_]+)\s*\]\s*(?P<body>.*?)\s*\[/TOOL_CALL\]",
    re.DOTALL | re.IGNORECASE,
)
_CODEBLOCK_TOOL_RE = re.compile(
    r"```(?:tool_call|json)\s*\n(\{\s*\"(?:tool|name)\"\s*:\s*\"[a-z_]+\"[\s\S]*?\})\s*```",
    re.IGNORECASE,
)
_PLAN_RE = re.compile(r"\[PLAN(?:_DAG)?\].*?\[/PLAN(?:_DAG)?\]", re.DOTALL | re.IGNORECASE)

def _is_response_truncated(text: str) -> bool:
    if "[TRUNCATED" in text:
        return True
    lower = text.lower()
    if "[error:" in lower and ("timeout" in lower or "timed out" in lower or "connection error" in lower):
        return True
    if "[TOOL_CALL:" in text and "[/TOOL_CALL]" not in text:
        return True
    if text.count("```") % 2 != 0 and len(text) > 800:
        return True
    return False


def _clean_response_text(text: str) -> str:
    """Remove tool call markers, plan blocks, error tags, and control tags for display prose."""
    cleaned = _EXTENDED_TOOL_RE.sub("", text)
    cleaned = _CODEBLOCK_TOOL_RE.sub("", cleaned)
    cleaned = _PLAN_RE.sub("", cleaned)
    cleaned = re.sub(r"\[TRUNCATED[^\]]*\]", "", cleaned)
    cleaned = re.sub(r"\[Error:[^\]]*\]", "", cleaned)
    cleaned = cleaned.replace("[DONE]", "").replace("[ESCALATE]", "").strip()
    return cleaned


def _compact_conversation_history(messages: list[ChatMessage], keep_recent_turns: int = 2) -> list[ChatMessage]:
    if len(messages) <= keep_recent_turns * 2:
        return messages

    compacted: list[ChatMessage] = []
    cutoff_index = len(messages) - (keep_recent_turns * 2)

    for idx, msg in enumerate(messages):
        if idx == 0 or idx >= cutoff_index:
            compacted.append(msg)
            continue

        content = msg.content
        if msg.role == "user":
            if "Tool results:" in content or "[TOOL_RESULT:" in content or "Tool observation results:" in content:
                tool_names = re.findall(r"\[TOOL_RESULT:\s*([a-z_]+)\]", content)
                if tool_names:
                    summary = f"(Historical tool results for: {', '.join(set(tool_names))} — compacted to save context tokens)"
                    compacted.append(ChatMessage(role="user", content=summary))
                else:
                    compacted.append(msg)
            else:
                compacted.append(msg)
        elif msg.role == "assistant":
            if "[TOOL_CALL:" in content and len(content) > 300:
                compact_tool_calls = re.sub(
                    r"(\[\s*TOOL_CALL:\s*([a-z_]+)\s*\])([\s\S]*?)(\[\s*/\s*TOOL_CALL\s*\])",
                    r"\1\n(Tool payload for \2 — compacted to save context tokens)\n\4",
                    content
                )
                compacted.append(ChatMessage(role="assistant", content=compact_tool_calls))
            else:
                compacted.append(msg)
        else:
            compacted.append(msg)

    return compacted


def _generate_diff_summary(change: FileChange) -> str:
    if not change.original:
        line_count = len(change.updated.splitlines())
        return f"+ [New file] {change.path} ({line_count} lines)"
    orig_lines = len(change.original.splitlines())
    upd_lines = len(change.updated.splitlines())
    diff_sign = f"+{upd_lines - orig_lines}" if upd_lines >= orig_lines else f"-{orig_lines - upd_lines}"
    return f"~ [Modified] {change.path} ({diff_sign} lines)"


class CompactionManager:
    @staticmethod
    def compact(messages, keep_recent_turns: int = 5):
        return _compact_conversation_history(messages, keep_recent_turns)

    @staticmethod
    def clean(text: str) -> str:
        return _clean_response_text(text)

    @staticmethod
    def is_truncated(text: str) -> bool:
        return _is_response_truncated(text)
