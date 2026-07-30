from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from .dual_coder_service import (
    DualCoderRequest,
    execute_dual_coder,
    DUAL_CODER_SESSIONS
)

router = APIRouter()

@router.post("/execute")
async def run_dual_coder(payload: DualCoderRequest) -> Dict[str, Any]:
    """Execute Dual Coder task with Model A and Model B in parallel."""
    if not payload.task_description.strip():
        raise HTTPException(status_code=400, detail="Task description cannot be empty")
    return await execute_dual_coder(payload)

@router.get("/sessions/{session_id}")
async def get_dual_coder_session(session_id: str) -> Dict[str, Any]:
    """Fetch Dual Coder session by ID."""
    if session_id not in DUAL_CODER_SESSIONS:
        raise HTTPException(status_code=404, detail="Dual Coder session not found")
    return DUAL_CODER_SESSIONS[session_id]

@router.get("/sessions")
async def list_dual_coder_sessions(workspace: str) -> List[Dict[str, Any]]:
    """List all active/recent Dual Coder sessions for a workspace."""
    results = [
        sess for sess in DUAL_CODER_SESSIONS.values()
        if sess.get("workspace") == workspace
    ]
    return sorted(results, key=lambda s: s.get("created_at", ""), reverse=True)
