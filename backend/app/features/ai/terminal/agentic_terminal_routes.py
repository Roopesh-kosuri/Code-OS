"""
agentic_terminal_routes.py — FastAPI routes for real-time Agentic Terminal streaming.

Endpoints:
- POST /api/terminal/create (body: {job_id, workspace})
- GET /api/terminal/stream/{terminal_id} → SSE
- POST /api/terminal/execute (body: {terminal_id, command, args})
- POST /api/terminal/signal (body: {terminal_id, signal})
- GET /api/terminal/history/{terminal_id}
- POST /api/terminal/close (body: {terminal_id})
- GET /api/terminal/active-sessions
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agentic_terminal_service import (
    create_session,
    get_session,
    close_session,
    execute_command,
    send_signal,
    stream_output,
    list_active_sessions,
)

router = APIRouter()


class CreateSessionRequest(BaseModel):
    job_id: str
    workspace: str


class ExecuteCommandRequest(BaseModel):
    terminal_id: str
    command: str
    args: Optional[List[str]] = None


class SignalRequest(BaseModel):
    terminal_id: str
    signal: str = "SIGINT"


class CloseSessionRequest(BaseModel):
    terminal_id: str


@router.post("/create")
async def handle_create_session(req: CreateSessionRequest):
    """Create a new agentic terminal session."""
    terminal_id = create_session(job_id=req.job_id, workspace=req.workspace)
    session = get_session(terminal_id)
    return {
        "ok": True,
        "terminal_id": terminal_id,
        "session": session,
    }


@router.get("/stream/{terminal_id}")
async def handle_stream(terminal_id: str):
    """Connect to SSE stream for live agent command output."""
    session = get_session(terminal_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Terminal session {terminal_id} not found")

    return StreamingResponse(
        stream_output(terminal_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/execute")
async def handle_execute_command(req: ExecuteCommandRequest):
    """Execute command in agentic terminal with live streaming output."""
    session = get_session(req.terminal_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Terminal session {req.terminal_id} not found")

    result = await execute_command(
        terminal_id=req.terminal_id,
        command=req.command,
        args=req.args,
    )
    return {"ok": True, "result": result}


@router.post("/signal")
async def handle_send_signal(req: SignalRequest):
    """Send signal to running process in terminal (e.g. SIGINT/SIGTERM)."""
    session = get_session(req.terminal_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Terminal session {req.terminal_id} not found")

    success = await send_signal(terminal_id=req.terminal_id, sig_name=req.signal)
    return {"ok": True, "signaled": success}


@router.get("/history/{terminal_id}")
async def handle_get_history(terminal_id: str):
    """Retrieve execution history for a terminal session."""
    session = get_session(terminal_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Terminal session {terminal_id} not found")

    return {
        "ok": True,
        "terminal_id": terminal_id,
        "history": session.get("history", []),
        "status": session.get("status", "idle"),
    }


@router.post("/close")
async def handle_close_session(req: CloseSessionRequest):
    """Close terminal session and cleanup resources."""
    success = await close_session(req.terminal_id)
    return {"ok": True, "closed": success}


@router.get("/active-sessions")
async def handle_list_sessions():
    """List all active agentic terminal sessions."""
    sessions = list_active_sessions()
    return {"ok": True, "sessions": sessions}
