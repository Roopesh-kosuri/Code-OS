"""Marathon Autopilot — FastAPI routes (REST + SSE)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .marathon_schemas import BudgetConfig, MarathonStateResponse, StartMarathonRequest
from .marathon_service import (
    abort_marathon,
    check_for_active_marathon,
    get_marathon_state,
    list_marathons,
    pause_marathon,
    resume_marathon,
    start_marathon,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/marathon", tags=["marathon"])


# ── SSE subscriber registry ───────────────────────────────────────────────────

_sse_subscribers: dict[str, list[asyncio.Queue]] = {}  # marathon_id -> [queue, ...]


def _register_subscriber(marathon_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_subscribers.setdefault(marathon_id, []).append(q)
    return q


def _unregister_subscriber(marathon_id: str, q: asyncio.Queue) -> None:
    if marathon_id in _sse_subscribers:
        try:
            _sse_subscribers[marathon_id].remove(q)
        except ValueError:
            pass


def broadcast_marathon_event(marathon_id: str, data: dict[str, Any]) -> None:
    """Called by the executor to push SSE updates to connected clients."""
    for q in list(_sse_subscribers.get(marathon_id, [])):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass


# Hook into event bus so executor SSE emissions reach the route streams
try:
    from app.features.ai.event_bus import event_bus

    def _on_marathon_update(data: dict[str, Any]) -> None:
        mid = data.get("marathon_id", "")
        if mid:
            broadcast_marathon_event(mid, data)

    event_bus.subscribe("marathon_update", _on_marathon_update)
except Exception:
    pass


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/start", response_model=MarathonStateResponse)
async def api_start_marathon(req: StartMarathonRequest):
    """Decompose a goal into a DAG and launch the autonomous executor."""
    try:
        state = await start_marathon(
            goal=req.goal,
            workspace=req.workspace,
            budget=req.budget,
            provider_config=req.provider_config,
            clarifying_answer=req.clarifying_answer,
        )
        return MarathonStateResponse.from_state(state)
    except Exception as exc:
        logger.error("start_marathon error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{marathon_id}/pause", response_model=MarathonStateResponse)
async def api_pause_marathon(marathon_id: str, workspace: str = Query(...)):
    try:
        state = await pause_marathon(marathon_id, workspace)
        return MarathonStateResponse.from_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{marathon_id}/resume", response_model=MarathonStateResponse)
async def api_resume_marathon(marathon_id: str, workspace: str = Query(...)):
    try:
        state = await resume_marathon(marathon_id, workspace)
        return MarathonStateResponse.from_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{marathon_id}/abort", response_model=MarathonStateResponse)
async def api_abort_marathon(marathon_id: str, workspace: str = Query(...)):
    try:
        state = await abort_marathon(marathon_id, workspace)
        return MarathonStateResponse.from_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/active/list")
async def api_list_active_marathons(workspace: str = Query(...)):
    """List all marathon state files for a workspace."""
    states = list_marathons(workspace)
    return [MarathonStateResponse.from_state(s) for s in states]


@router.get("/active/resume-check")
async def api_resume_check(workspace: str = Query(...)):
    """Boot-time check: return a paused/running marathon if one exists."""
    state = check_for_active_marathon(workspace)
    if state:
        return {"found": True, "marathon": MarathonStateResponse.from_state(state)}
    return {"found": False, "marathon": None}


@router.get("/{marathon_id}", response_model=MarathonStateResponse)
async def api_get_marathon(marathon_id: str, workspace: str = Query(...)):
    state = get_marathon_state(marathon_id, workspace)
    if not state:
        raise HTTPException(status_code=404, detail=f"Marathon {marathon_id} not found")
    return MarathonStateResponse.from_state(state)


@router.get("/{marathon_id}/stream")
async def api_marathon_stream(marathon_id: str, workspace: str = Query(...)):
    """SSE stream of marathon_update events for a specific marathon."""
    q = _register_subscriber(marathon_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        # Send current state immediately on connect
        state = get_marathon_state(marathon_id, workspace)
        if state:
            resp = MarathonStateResponse.from_state(state)
            yield f"event: marathon_update\ndata: {resp.model_dump_json()}\n\n"

        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"event: marathon_update\ndata: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive ping
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _unregister_subscriber(marathon_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
