"""payload_governor.py — Pre-flight request sizing and payload governor for CODE OS.

Estimates total request tokens (system prompt + tools schema + attachments + history + RAG)
against provider TPM and context window limits before dispatch. Automatically
compacts history, truncates RAG to top-2, truncates large attachments, and slims tool schemas
to prevent HTTP 413 (Payload Too Large) and rate-limit overflow errors (e.g. Groq 8,000 TPM limit).
Fails closed with a transparent error when request cannot be safely budgeted.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.features.ai.schemas import ChatMessage
from app.features.ai.harness.compaction_manager import _compact_conversation_history
from app.features.ai.harness.tool_executor import SLIM_CODING_TOOLS

logger = logging.getLogger(__name__)

# Conservative provider token limits per single-turn request
PROVIDER_TOKEN_BUDGETS: dict[str, int] = {
    "groq": 7500,  # Groq on-demand has strict 8,000 TPM limit
}
DEFAULT_MAX_REQUEST_TOKENS = 28000


class GovernanceResult(tuple):
    """Backwards-compatible 4-tuple: (messages, tools, was_adjusted, summary_reason) with metadata attributes."""
    messages: list[ChatMessage]
    tools: list[dict[str, Any]] | None
    was_adjusted: bool
    summary_reason: str
    breakdown: dict[str, int]
    failed_closed: bool

    def __new__(
        cls,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        was_adjusted: bool,
        summary_reason: str,
        breakdown: Optional[dict[str, int]] = None,
        failed_closed: bool = False,
    ):
        instance = super().__new__(cls, (messages, tools, was_adjusted, summary_reason))
        instance.messages = messages
        instance.tools = tools
        instance.was_adjusted = was_adjusted
        instance.summary_reason = summary_reason
        instance.breakdown = breakdown or {}
        instance.failed_closed = failed_closed
        return instance


def estimate_payload_breakdown(
    messages: list[ChatMessage],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Calculate token breakdown across all parts of the request payload."""
    system_chars = 0
    history_chars = 0
    rag_chars = 0
    attachment_chars = 0

    for m in messages:
        c = getattr(m, "content", None) or ""
        role = getattr(m, "role", "")
        # Heuristic tagging for RAG context blocks
        if any(marker in c for marker in ("Relevant files from codebase:", "## Symbol Definition Locations:", "### Symbol '")):
            rag_chars += len(c)
        elif any(marker in c for marker in ("<file ", "<attachment ", "<untrusted_file_content ")):
            attachment_chars += len(c)
        elif role == "system":
            system_chars += len(c)
        else:
            history_chars += len(c)

    tool_chars = 0
    if tools:
        try:
            tools_json = json.dumps(tools)
            tool_chars = len(tools_json)
        except Exception:
            tool_chars = len(tools) * 320

    system_tokens = system_chars // 4
    history_tokens = history_chars // 4
    rag_tokens = rag_chars // 4
    attachment_tokens = attachment_chars // 4
    tool_tokens = tool_chars // 4
    total_tokens = system_tokens + history_tokens + rag_tokens + attachment_tokens + tool_tokens

    return {
        "system_tokens": system_tokens,
        "history_tokens": history_tokens,
        "rag_tokens": rag_tokens,
        "attachment_tokens": attachment_tokens,
        "tool_tokens": tool_tokens,
        "total_tokens": total_tokens,
    }


def estimate_request_tokens(messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None) -> int:
    """Estimate total token consumption of messages and tool definitions."""
    breakdown = estimate_payload_breakdown(messages, tools)
    return breakdown["total_tokens"]


def _truncate_rag_in_text(text: str, top_k: int = 2) -> tuple[str, bool]:
    """Find RAG context sections and truncate to top_k snippets."""
    if not any(marker in text for marker in ("Relevant files from codebase:", "## Symbol Definition Locations:", "### Symbol '")):
        return text, False

    was_truncated = False

    # 1. Truncate Symbol Definition blocks
    if "### Symbol '" in text:
        parts = text.split("### Symbol '")
        if len(parts) > top_k + 1:
            header = parts[0]
            kept = parts[1:top_k + 1]
            text = header + "".join(f"### Symbol '{p}" for p in kept) + f"\n... [RAG truncated to top-{top_k} symbol definitions to stay within token budget]\n"
            was_truncated = True

    # 2. Truncate Relevant files from codebase
    if "Relevant files from codebase:\n" in text:
        parts = text.split("\n\n")
        rag_idx = -1
        for idx, part in enumerate(parts):
            if "Relevant files from codebase:" in part:
                rag_idx = idx
                break
        if rag_idx != -1:
            pre = parts[:rag_idx + 1]
            snippets = parts[rag_idx + 1:]
            if len(snippets) > top_k:
                text = "\n\n".join(pre + snippets[:top_k]) + f"\n\n... [RAG truncated to top-{top_k} files to stay within token budget]"
                was_truncated = True

    return text, was_truncated


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
    workspace: str = "",
) -> GovernanceResult:
    """Inspect and govern request payload before dispatch to prevent HTTP 413 TPM overflow.

    Applies progressive reduction if over budget:
    1. Compact conversation history turns.
    2. Truncate RAG context to top-2 instead of top-5 and truncate large attachment blocks.
    3. Swap tool definitions to SLIM_CODING_TOOLS.
    4. If still over budget, fail closed with an honest error.

    Returns:
        GovernanceResult tuple: (governed_messages, governed_tools, was_adjusted, summary_reason)
    """
    prov_key = (provider or "").lower().strip()
    budget = hard_tpm_limit or PROVIDER_TOKEN_BUDGETS.get(prov_key, DEFAULT_MAX_REQUEST_TOKENS)

    breakdown = estimate_payload_breakdown(messages, tools)
    estimated_tokens = breakdown["total_tokens"]

    if estimated_tokens <= budget:
        return GovernanceResult(messages, tools, False, "", breakdown, False)

    logger.info(
        "payload_governor: payload of %d tokens exceeds %s budget (%d tokens). Breakdown: %s. Applying progressive reduction.",
        estimated_tokens, prov_key, budget, breakdown,
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
            breakdown = estimate_payload_breakdown(adjusted_messages, adjusted_tools)
            if breakdown["total_tokens"] <= budget:
                _log_governance_event(workspace, prov_key, budget, breakdown, adjustments_applied, failed_closed=False)
                return GovernanceResult(adjusted_messages, adjusted_tools, True, ", ".join(adjustments_applied), breakdown, False)

    # Step 2: Truncate RAG context to top-2 instead of top-5, and truncate oversized attachments
    rag_or_att_truncated = False
    new_msgs: list[ChatMessage] = []
    target_att_chars = 4000 if prov_key == "groq" else 8000

    for m in adjusted_messages:
        c = getattr(m, "content", "")
        # Check RAG truncation
        c, rag_trunc = _truncate_rag_in_text(c, top_k=2)
        if rag_trunc:
            rag_or_att_truncated = True
            if "truncated_rag_to_top_2" not in adjustments_applied:
                adjustments_applied.append("truncated_rag_to_top_2")

        # Check attachment truncation
        if any(t in c for t in ("<file ", "<attachment ", "<untrusted_file_content ")):
            c, att_trunc = _truncate_attachment_in_text(c, max_chars=target_att_chars)
            if att_trunc:
                rag_or_att_truncated = True
                att_tag = f"truncated_attachments_to_{target_att_chars}c"
                if att_tag not in adjustments_applied:
                    adjustments_applied.append(att_tag)

        new_msgs.append(ChatMessage(role=m.role, content=c))

    if rag_or_att_truncated:
        adjusted_messages = new_msgs
        breakdown = estimate_payload_breakdown(adjusted_messages, adjusted_tools)
        if breakdown["total_tokens"] <= budget:
            _log_governance_event(workspace, prov_key, budget, breakdown, adjustments_applied, failed_closed=False)
            return GovernanceResult(adjusted_messages, adjusted_tools, True, ", ".join(adjustments_applied), breakdown, False)

    # Step 3: Switch to slim tool schema
    if adjusted_tools and len(adjusted_tools) > len(SLIM_CODING_TOOLS):
        mcp_tools = [t for t in adjusted_tools if "[MCP Tool" in str(t.get("function", {}).get("description", ""))]
        adjusted_tools = list(SLIM_CODING_TOOLS) + mcp_tools
        adjustments_applied.append("swapped_to_slim_tools")
        breakdown = estimate_payload_breakdown(adjusted_messages, adjusted_tools)
        if breakdown["total_tokens"] <= budget:
            _log_governance_event(workspace, prov_key, budget, breakdown, adjustments_applied, failed_closed=False)
            return GovernanceResult(adjusted_messages, adjusted_tools, True, ", ".join(adjustments_applied), breakdown, False)

    # Step 4: If still over budget, fail closed with honest error
    failed_closed = breakdown["total_tokens"] > budget
    if failed_closed:
        adjustments_applied.append("fail_closed_budget_exceeded")
        summary = (
            f"fail_closed: Request payload ({breakdown['total_tokens']} tokens) exceeds provider budget "
            f"({budget} tokens) after full progressive reduction. Failing closed to prevent TPM exhaustion."
        )
        logger.warning("payload_governor: %s", summary)
    else:
        summary = ", ".join(adjustments_applied)

    _log_governance_event(workspace, prov_key, budget, breakdown, adjustments_applied, failed_closed=failed_closed)
    return GovernanceResult(adjusted_messages, adjusted_tools, bool(adjustments_applied), summary, breakdown, failed_closed)


def _log_governance_event(
    workspace: str,
    provider: str,
    budget: int,
    breakdown: dict[str, int],
    adjustments: list[str],
    failed_closed: bool,
) -> None:
    """Log the token budget audit breakdown in workspace activity log for observability."""
    if not workspace:
        return
    try:
        from app.features.ai.harness.activity_logger import _append_activity_log
        _append_activity_log(workspace, {
            "action_type": "token_budget_audit",
            "provider": provider,
            "budget": budget,
            "breakdown": breakdown,
            "adjustments": adjustments,
            "status": "fail_closed" if failed_closed else "within_budget",
        })
    except Exception as exc:
        logger.debug("Failed to log governance event: %s", exc)
