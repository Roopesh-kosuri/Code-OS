"""
failure_handler.py - Centralized resilient failure logging and flagging for chat_harness.

Ensures that errors during intermediate harness stages (RAG, streaming, tool execution, etc.)
are never silently swallowed, but also NEVER crash the SSE stream.
"""
from __future__ import annotations

import json
import logging
import traceback
from typing import Any

logger = logging.getLogger(__name__)


def log_and_flag_failure(
    stage: str,
    exc: Exception,
    context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """
    Safely log a stage failure with full traceback and return a structured flag dict
    along with an SSE-formatted status warning event.

    GUARANTEE: This function NEVER raises an exception.
    """
    try:
        ctx = context or {}
        tb_str = traceback.format_exc()
        logger.warning(
            "chat_harness failure in stage '%s': %s (context: %s)\n%s",
            stage,
            exc,
            ctx,
            tb_str,
        )
        flag_data = {
            "stage": stage,
            "error": str(exc),
            "degraded": True,
            "warning_message": f"⚠️ {stage.replace('_', ' ').title()} degraded: {exc}",
            "context": ctx,
        }
        # Format as standard SSE status event without changing the wire contract
        data_json = json.dumps({
            "type": "warning",
            "message": flag_data["warning_message"],
            "degraded_stage": stage,
            "error_detail": str(exc),
        })
        sse_event = f"event: status\ndata: {data_json}\n\n"
        return flag_data, sse_event
    except Exception as inner_exc:
        # Ultimate fallback guardrail - never crash caller
        fallback_msg = f"⚠️ Stage {stage} encountered an issue: {exc}"
        return (
            {"stage": stage, "error": str(exc), "degraded": True, "warning_message": fallback_msg},
            f"event: status\ndata: {json.dumps({'type': 'warning', 'message': fallback_msg})}\n\n",
        )