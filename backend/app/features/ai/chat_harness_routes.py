"""
chat_harness_routes.py — FastAPI routes for the lightweight chat agent harness.

Provides SSE streaming endpoint and approval/rejection endpoints.
This is a NEW router — does NOT modify any existing Agent Console routes.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Request / Response schemas ───────────────────────────────────────────────

class ChatAgentStreamRequest(BaseModel):
    """Request body for the chat agent SSE stream."""
    provider: str = "auto"
    model: str = ""
    base_url: str | None = None
    temperature: float = 0.2
    api_key_provider: str | None = None
    messages: list[dict] = Field(default_factory=list)  # [{role, content}]
    workspace: str = ""
    attached_paths: list[str] = Field(default_factory=list)
    agent_mode: bool = True  # Always true when hitting this endpoint


class ApprovalResponse(BaseModel):
    success: bool
    message: str = ""


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat-agent/stream")
async def chat_agent_stream(payload: ChatAgentStreamRequest) -> StreamingResponse:
    """Stream SSE events from the chat agent harness.
    
    Unlike /chat/stream (which just proxies LLM tokens), this endpoint
    runs a full autonomous agent loop with tool calling, retrieval,
    plan decomposition, and Duo Loop escalation.
    """
    from app.core.rate_limiter import rate_limiter
    rate_limiter.check("chat_agent_stream", max_requests=15, window_seconds=60.0)
    
    from .chat_harness import run_chat_agent, ChatAgentRequest
    
    agent_request = ChatAgentRequest(
        provider=payload.provider,
        model=payload.model,
        base_url=payload.base_url,
        temperature=payload.temperature,
        api_key_provider=payload.api_key_provider,
        messages=payload.messages,
        workspace=payload.workspace,
        attached_paths=payload.attached_paths,
    )
    
    return StreamingResponse(
        run_chat_agent(agent_request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat-agent/approve/{action_id}", response_model=ApprovalResponse)
async def approve_agent_action(action_id: str) -> ApprovalResponse:
    """Approve a pending agent action (e.g., a non-safe terminal command)."""
    from .chat_harness import approve_action
    
    success = await approve_action(action_id)
    if success:
        return ApprovalResponse(success=True, message=f"Action {action_id} approved")
    raise HTTPException(status_code=404, detail=f"No pending action with ID {action_id}")


@router.post("/chat-agent/reject/{action_id}", response_model=ApprovalResponse)
async def reject_agent_action(action_id: str) -> ApprovalResponse:
    """Reject a pending agent action."""
    from .chat_harness import reject_action
    
    success = await reject_action(action_id)
    if success:
        return ApprovalResponse(success=True, message=f"Action {action_id} rejected")
    raise HTTPException(status_code=404, detail=f"No pending action with ID {action_id}")
