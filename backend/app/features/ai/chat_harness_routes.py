"""
chat_harness_routes.py — FastAPI routes for the lightweight chat agent harness.

Provides SSE streaming endpoint, health/boot endpoint, user interactive response endpoint,
and approval/rejection endpoints.
This is a dedicated router — does NOT modify any existing Agent Console routes.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

BOOT_TIMESTAMP = time.time()


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
    agent_mode: bool = False  # Default OFF, Agent toggle enables manual override


class ApprovalResponse(BaseModel):
    success: bool
    message: str = ""


class UserAnswerRequest(BaseModel):
    answer: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/chat-agent/health")
async def chat_agent_health() -> dict:
    """Return backend health and boot timestamp for stale-process discipline."""
    return {
        "status": "ok",
        "boot_timestamp": BOOT_TIMESTAMP,
        "uptime_seconds": time.time() - BOOT_TIMESTAMP,
    }


@router.post("/chat-agent/stream")
async def chat_agent_stream(payload: ChatAgentStreamRequest) -> StreamingResponse:
    """Stream SSE events from the chat agent harness.
    
    Runs adaptive tiered execution (Tier 0 Fast Answer, Tier 1 Quick Task, Tier 2 Deep Task)
    with tool execution, budgeted RAG, DAG planning, and verification.
    """
    from app.core.rate_limiter import rate_limiter
    rate_limiter.check("chat_agent_stream", max_requests=30, window_seconds=60.0)
    
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
        is_agent_mode=payload.agent_mode,
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
    """Approve a pending agent action (e.g., command execution or file edit proposal)."""
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


@router.post("/chat-agent/respond/{action_id}", response_model=ApprovalResponse)
async def respond_to_agent_question(action_id: str, payload: UserAnswerRequest) -> ApprovalResponse:
    """Respond to an ask_user question posed by Rony Agent."""
    from .chat_harness import respond_to_user_question
    
    success = respond_to_user_question(action_id, payload.answer)
    if success:
        return ApprovalResponse(success=True, message=f"Response submitted for action {action_id}")
    raise HTTPException(status_code=404, detail=f"No pending user question with ID {action_id}")
