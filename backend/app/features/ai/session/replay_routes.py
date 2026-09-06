"""
replay_routes.py — API endpoints for Session Replay, Timeline Scrubber, Forking & Export.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .session_store import (
    get_session_list,
    get_session_timeline,
    get_session_snapshot,
    fork_session,
    export_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["session-replay"])


class ForkSessionRequest(BaseModel):
    step_id: str = Field(..., description="Step ID to rewind and fork from")
    new_prompt: str = Field(..., min_length=1, description="New prompt directive for forked timeline")


@router.get("")
async def list_sessions_endpoint(
    workspace: str = Query(default="", description="Optional workspace path"),
    limit: int = Query(default=50, ge=1, le=200, description="Max sessions to return"),
) -> list[dict[str, Any]]:
    """Get list of past agent sessions / jobs."""
    return await get_session_list(workspace=workspace, limit=limit)


@router.get("/{job_id}/timeline")
async def get_session_timeline_endpoint(job_id: str) -> list[dict[str, Any]]:
    """Get full step-by-step chronological timeline for a session."""
    return await get_session_timeline(job_id)


@router.get("/{job_id}/snapshot")
async def get_session_snapshot_endpoint(
    job_id: str,
    step_id: str = Query(default="", description="Step ID for snapshot reconstruction"),
) -> dict[str, Any]:
    """Reconstruct exact state snapshot at a specific step in the session."""
    return await get_session_snapshot(job_id, step_id)


@router.post("/{job_id}/fork")
async def fork_session_endpoint(
    job_id: str,
    payload: ForkSessionRequest,
) -> dict[str, Any]:
    """Fork session from a specific step with new directive instructions."""
    try:
        return await fork_session(
            original_job_id=job_id,
            step_id=payload.step_id,
            new_prompt=payload.new_prompt,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))
    except Exception as exc:
        logger.exception("Fork session failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to fork session: {exc}")


@router.get("/{job_id}/export")
async def export_session_endpoint(
    job_id: str,
    format: str = Query(default="markdown", description="'markdown' or 'json'"),
) -> Response:
    """Export session transcript as Markdown or JSON."""
    fmt = format.lower()
    if fmt not in ("markdown", "json"):
        fmt = "markdown"

    content = await export_session(job_id, format=fmt)
    media_type = "application/json" if fmt == "json" else "text/markdown; charset=utf-8"
    ext = "json" if fmt == "json" else "md"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="session_{job_id}.{ext}"',
        },
    )
