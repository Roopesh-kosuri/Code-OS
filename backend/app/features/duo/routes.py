"""FastAPI routes for the Duo Generator/Critic loop feature."""
from __future__ import annotations

from fastapi import APIRouter

from .schemas import DuoSessionDto, DuoSessionRequest
from . import service

router = APIRouter()


@router.post("/sessions", response_model=DuoSessionDto, status_code=201)
async def create_session(req: DuoSessionRequest) -> DuoSessionDto:
    """
    Start a new Duo Generator/Critic loop session.

    The loop runs as a background task. Poll GET /sessions/{id} for status.
    The session status progresses:
        running → approved | unresolved | cancelled | error
    """
    return await service.start_session(req)


@router.get("/sessions/{session_id}", response_model=DuoSessionDto)
async def get_session(session_id: str) -> DuoSessionDto:
    """
    Poll the current state of a Duo session.

    Returns the session with all completed rounds and their Generator output +
    Critic verdict. While a round is in-progress the critic_verdict field will
    be null for the latest round.
    """
    return await service.get_session(session_id)


@router.get("/sessions", response_model=list[DuoSessionDto])
async def list_sessions(workspace: str) -> list[DuoSessionDto]:
    """List all Duo sessions for a workspace (most recent first, max 50)."""
    return await service.list_sessions(workspace)


@router.post("/sessions/{session_id}/cancel", response_model=DuoSessionDto)
async def cancel_session(session_id: str) -> DuoSessionDto:
    """
    Cancel a running Duo session.

    If the loop is between rounds it will be stopped at the next checkpoint.
    The final proposal (if any was generated) remains in edit_proposals as
    pending and can be reviewed in the DiffViewer.
    """
    return await service.cancel_session(session_id)


from pydantic import BaseModel

class DuoRecoverRequest(BaseModel):
    action: str

@router.post("/sessions/{session_id}/recover")
async def recover_session(session_id: str, payload: DuoRecoverRequest) -> dict:
    """Recover a paused Duo session."""
    if session_id in service._pending_recovery_events:
        service._pending_recovery_decisions[session_id] = payload.action
        service._pending_recovery_events[session_id].set()
        return {"status": "recovered"}
    from fastapi import HTTPException
    raise HTTPException(status_code=400, detail="No pending action for this session")
