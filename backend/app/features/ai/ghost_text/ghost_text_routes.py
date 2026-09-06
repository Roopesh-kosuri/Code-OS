"""
ghost_text_routes.py — FastAPI endpoints for Monaco Ghost Text & Inline Diffs.
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Body, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .ghost_text_service import (
    register_editor,
    unregister_editor,
    get_active_editors,
    stream_inline_diff,
    accept_ghost_text,
    reject_ghost_text,
    get_pending_ghost_text,
)

router = APIRouter()


class RegisterEditorRequest(BaseModel):
    workspace: str
    file_path: str
    editor_id: str


class UnregisterEditorRequest(BaseModel):
    editor_id: str


class GhostActionRequest(BaseModel):
    editor_id: str
    file_path: Optional[str] = ""


@router.post("/register")
async def handle_register_editor(req: RegisterEditorRequest):
    """Register an open Monaco editor tab for ghost text streaming."""
    result = register_editor(
        workspace=req.workspace,
        file_path=req.file_path,
        editor_id=req.editor_id,
    )
    return {"ok": True, "editor": result}


@router.post("/unregister")
async def handle_unregister_editor(req: UnregisterEditorRequest):
    """Unregister an editor tab when closed."""
    result = unregister_editor(req.editor_id)
    return {"ok": True, "result": result}


@router.get("/editors")
async def handle_get_active_editors(workspace: str = Query(default="")):
    """Get all active open Monaco editor tabs."""
    editors = get_active_editors(workspace)
    return {"ok": True, "editors": editors}


@router.get("/pending")
async def handle_get_pending(editor_id: str = Query(default=""), file_path: str = Query(default="")):
    """Inspect pending ghost text for an editor or file."""
    pending = get_pending_ghost_text(editor_id, file_path)
    return {"ok": True, "pending": pending}


@router.post("/accept")
async def handle_accept_ghost_text(req: GhostActionRequest):
    """Accept ghost text and commit changes to disk."""
    res = accept_ghost_text(req.editor_id, req.file_path or "")
    return {"ok": res.get("status") == "accepted", "result": res}


@router.post("/reject")
async def handle_reject_ghost_text(req: GhostActionRequest):
    """Reject ghost text and discard changes."""
    res = reject_ghost_text(req.editor_id, req.file_path or "")
    return {"ok": res.get("status") == "rejected", "result": res}


class StreamRequest(BaseModel):
    job_id: Optional[str] = ""
    file_path: str
    editor_id: str


@router.post("/stream")
async def handle_stream_inline_diff_post(req: StreamRequest):
    """POST endpoint emitting live diff chunks via SSE for api.streamSSE client."""
    return StreamingResponse(
        stream_inline_diff(job_id=req.job_id or "", file_path=req.file_path, editor_id=req.editor_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream/{job_id}/{file_path:path}/{editor_id}")
async def handle_stream_inline_diff(
    job_id: str,
    file_path: str,
    editor_id: str,
):
    """SSE streaming endpoint emitting live diff chunks for an active editor."""
    return StreamingResponse(
        stream_inline_diff(job_id=job_id, file_path=file_path, editor_id=editor_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
