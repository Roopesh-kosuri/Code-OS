from __future__ import annotations

import re
from typing import Any, Dict, List

from app.features.ai.schemas import ChatMessage, FileChange

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


_INCOMPLETE_TOOL_RE = re.compile(
    r"\[TOOL_CALL:\s*[a-zA-Z0-9_\-]+[\s\S]*?(?:\[/TOOL_CALL\]|$)",
    re.IGNORECASE,
)
_INCOMPLETE_CODEBLOCK_TOOL_RE = re.compile(
    r"```(?:tool_call|json)?\s*\n?\{\s*\"(?:tool|name|action)\"\s*:\s*\"[a-zA-Z0-9_\-]+[\s\S]*?(?:```|$)",
    re.IGNORECASE,
)


META_NARRATION_PATTERNS = [
    re.compile(r"(?:^|[.\n])\s*(?:To further investigate,?\s*)?I will (?:use|call)\s+(?:the\s+)?\w+\s+(?:tool|function)[^.\n]*\.?", re.IGNORECASE),
    re.compile(r"(?:^|[.\n])\s*To further investigate,?\s*I will[^.\n]*\.?", re.IGNORECASE),
    re.compile(r"(?:^|[.\n])\s*Since the user asked[^.\n]*,?\s*I will (?:call|use)[^.\n]*\.?", re.IGNORECASE),
    re.compile(r"(?:^|[.\n])\s*The user has chosen to provide more context[^.\n]*\.?\s*I will[^.\n]*\.?", re.IGNORECASE),
    re.compile(r"(?:^|[.\n])\s*I will ask (?:another|a) clarifying question[^.\n]*\.?", re.IGNORECASE),
    re.compile(r"(?:^|[.\n])\s*I will (?:now\s+)?(?:use|call|proceed to call|execute)\s+(?:the\s+)?\w+\s+(?:tool|function)?[^.\n]*\.?", re.IGNORECASE),
    re.compile(r"(?:^|[.\n])\s*Unfortunately,?\s*(?:the\s+)?semantic search did not find any relevant information[^.\n]*\.?", re.IGNORECASE),
]


def strip_meta_narration(text: str) -> str:
    """Remove internal meta-narration sentences leaked by the model into user prose."""
    if not text:
        return ""
    cleaned = text
    for pat in META_NARRATION_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r"\n\s*\n\s*\n+", "\n\n", cleaned)
    return cleaned.strip()


def _clean_response_text(text: str) -> str:
    """Remove tool call markers, plan blocks, error tags, control tags, and meta-narration for display prose."""
    cleaned = _EXTENDED_TOOL_RE.sub("", text)
    cleaned = _CODEBLOCK_TOOL_RE.sub("", cleaned)
    # Clean up incomplete or unclosed tool call blocks (e.g. cut off or truncated)
    cleaned = _INCOMPLETE_TOOL_RE.sub("", cleaned)
    cleaned = _INCOMPLETE_CODEBLOCK_TOOL_RE.sub("", cleaned)
    cleaned = _PLAN_RE.sub("", cleaned)
    cleaned = re.sub(r"\[TRUNCATED[^\]]*\]", "", cleaned)
    cleaned = re.sub(r"\[Error:[^\]]*\]", "", cleaned)
    cleaned = cleaned.replace("[DONE]", "").replace("[ESCALATE]", "").strip()
    cleaned = strip_meta_narration(cleaned)
    return cleaned


def _compact_conversation_history(messages: list[ChatMessage], keep_recent_turns: int = 2) -> list[ChatMessage]:
    total_len = sum(len(m.content) for m in messages if getattr(m, "content", None))
    # If history is getting large, compact more aggressively to keep under TPM/context limits
    effective_turns = 1 if total_len > 4000 else keep_recent_turns
    if len(messages) <= effective_turns * 2:
        return messages

    compacted: list[ChatMessage] = []
    cutoff_index = len(messages) - (effective_turns * 2)

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
