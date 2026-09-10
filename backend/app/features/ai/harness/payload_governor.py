"""payload_governor.py — Pre-flight request sizing and payload governor for CODE OS.

Estimates total request tokens (system prompt + tools schema + attachments + history)
against provider TPM and context window limits before dispatch. Automatically
compacts history, truncates large attachments, and slims tool schemas to prevent
HTTP 413 (Payload Too Large) and rate-limit overflow errors (e.g. Groq 8,000 TPM limit).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.features.ai.schemas import ChatMessage
from app.features.ai.harness.compaction_manager import _compact_conversation_history
from app.features.ai.harness.tool_executor import SLIM_CODING_TOOLS

logger = logging.getLogger(__name__)

# Conservative provider token limits per single-turn request
PROVIDER_TOKEN_BUDGETS: dict[str, int] = {
    "groq": 7500,  # Groq on-demand has strict 8,000 TPM limit
}
DEFAULT_MAX_REQUEST_TOKENS = 28000


def estimate_request_tokens(messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None) -> int:
    """Estimate total token consumption of messages and tool definitions."""
    total_chars = 0
    for m in messages:
        c = getattr(m, "content", None) or ""
        total_chars += len(c)

    # 4 characters per token heuristic
    message_tokens = total_chars // 4

    tool_tokens = 0
    if tools:
        try:
            tools_json = json.dumps(tools)
            tool_tokens = len(tools_json) // 4
        except Exception:
            tool_tokens = len(tools) * 80

    return message_tokens + tool_tokens


def _truncate_attachment_in_text(text: str, max_chars: int = 6000) -> tuple[str, bool]:
    """Find attachment XML blocks in text and truncate content if oversized."""
    if not any(t in text for t in ("<file ", "<attachment ", "<untrusted_file_content ")):
        return text, False

    was_truncated = False

    def _replace_attachment(match: re.Match) -> str:
        nonlocal was_truncated
        full_block = match.group(0)
        inner = match.group("content")
        if len(inner) <= max_chars:
            return full_block

        was_truncated = True
        head_len = int(max_chars * 0.6)
        tail_len = int(max_chars * 0.4)
        omitted = len(inner) - (head_len + tail_len)
        truncated_inner = (
            f"{inner[:head_len]}\n\n"
            f"[... middle truncated to fit provider token limits — {omitted} characters omitted ...]\n\n"
            f"{inner[-tail_len:]}"
        )
        tag_open = match.group("open")
        if 'truncated="true"' not in tag_open:
            tag_open = tag_open[:-1] + ' truncated="true">'
        tag_close = match.group("close")
        return f"{tag_open}\n{truncated_inner}\n{tag_close}"

    # Match <file ...>content</file>, <attachment ...>content</attachment>, <untrusted_file_content ...>content</untrusted_file_content>
    pattern = re.compile(
        r"(?P<open><(?:file|attachment|untrusted_file_content)\s+[^>]*>)(?P<content>[\s\S]*?)(?P<close></(?:file|attachment|untrusted_file_content)>)",
        re.IGNORECASE,
    )
    new_text = pattern.sub(_replace_attachment, text)
    return new_text, was_truncated


def govern_payload(
    messages: list[ChatMessage],
    tools: list[dict[str, Any]] | None,
    provider: str,
    model: str = "",
    hard_tpm_limit: int | None = None,
) -> tuple[list[ChatMessage], list[dict[str, Any]] | None, bool, str]:
    """Inspect and govern request payload before dispatch to prevent HTTP 413 TPM overflow.

    Applies progressive reduction if over budget:
    1. Compact conversation history turns.
    2. Truncate attached file XML blocks.
    3. Swap tool definitions to SLIM_CODING_TOOLS.

    Returns:
        (governed_messages, governed_tools, was_adjusted, summary_reason)
    """
    prov_key = (provider or "").lower().strip()
    budget = hard_tpm_limit or PROVIDER_TOKEN_BUDGETS.get(prov_key, DEFAULT_MAX_REQUEST_TOKENS)

    estimated_tokens = estimate_request_tokens(messages, tools)
    if estimated_tokens <= budget:
        return messages, tools, False, ""

    logger.info(
        "payload_governor: payload of %d tokens exceeds %s budget (%d tokens). Applying progressive reduction.",
        estimated_tokens, prov_key, budget,
    )

    adjusted_messages = list(messages)
    adjusted_tools = list(tools) if tools else None
    adjustments_applied: list[str] = []

    # Step 1: Compact conversation history turns
    if len(adjusted_messages) > 2:
        compacted = _compact_conversation_history(adjusted_messages, keep_recent_turns=1)
        if len(compacted) < len(adjusted_messages) or sum(len(m.content) for m in compacted) < sum(len(m.content) for m in adjusted_messages):
            adjusted_messages = compacted
            adjustments_applied.append("compacted_history")
            estimated_tokens = estimate_request_tokens(adjusted_messages, adjusted_tools)
            if estimated_tokens <= budget:
                return adjusted_messages, adjusted_tools, True, ", ".join(adjustments_applied)

    # Step 2: Truncate oversized attachment blocks
    any_att_truncated = False
    new_msgs: list[ChatMessage] = []
    target_att_chars = 4000 if prov_key == "groq" else 8000
    for m in adjusted_messages:
        c = getattr(m, "content", "")
        if any(t in c for t in ("<file ", "<attachment ", "<untrusted_file_content ")):
            new_c, trunc = _truncate_attachment_in_text(c, max_chars=target_att_chars)
            if trunc:
                any_att_truncated = True
                new_msgs.append(ChatMessage(role=m.role, content=new_c))
            else:
                new_msgs.append(m)
        else:
            new_msgs.append(m)

    if any_att_truncated:
        adjusted_messages = new_msgs
        adjustments_applied.append(f"truncated_attachments_to_{target_att_chars}c")
        estimated_tokens = estimate_request_tokens(adjusted_messages, adjusted_tools)
        if estimated_tokens <= budget:
            return adjusted_messages, adjusted_tools, True, ", ".join(adjustments_applied)

    # Step 3: Switch to slim tool schema
    if adjusted_tools and len(adjusted_tools) > len(SLIM_CODING_TOOLS):
        # Keep MCP tools if present, but reduce core tools to SLIM_CODING_TOOLS
        mcp_tools = [t for t in adjusted_tools if "[MCP Tool" in str(t.get("function", {}).get("description", ""))]
        adjusted_tools = list(SLIM_CODING_TOOLS) + mcp_tools
        adjustments_applied.append("swapped_to_slim_tools")
        estimated_tokens = estimate_request_tokens(adjusted_messages, adjusted_tools)

    return adjusted_messages, adjusted_tools, bool(adjustments_applied), ", ".join(adjustments_applied)
