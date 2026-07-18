from fastapi import APIRouter, Query, HTTPException

from backend.app.features.git.schemas import BranchCreateRequest, BranchSwitchRequest, CommitHistoryItem, CommitRequest, DiffResponse, GitStatusResponse
from backend.app.features.git.service import commit, create_branch, diff, history, pull, push, status, switch_branch

router = APIRouter()


async def _ensure_trusted(workspace: str):
    from backend.app.features.workspaces.trust_service import get_workspace_trust
    trust = await get_workspace_trust(workspace)
    if not trust.get("trusted", False):
        raise HTTPException(status_code=403, detail="Workspace is in Restricted Mode. Git mutation operations are disabled.")


@router.get("/status", response_model=GitStatusResponse)
async def git_status(workspace: str = Query(...)) -> GitStatusResponse:
    return GitStatusResponse(**status(workspace))


@router.get("/diff", response_model=DiffResponse)
async def git_diff(workspace: str = Query(...), path: str | None = Query(default=None)) -> DiffResponse:
    return DiffResponse(diff=diff(workspace, path))


@router.post("/commit")
async def git_commit(payload: CommitRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    return {"sha": commit(payload.workspace, payload.message)}


@router.post("/pull")
async def git_pull(workspace: str = Query(...)) -> dict[str, str]:
    await _ensure_trusted(workspace)
    return {"output": pull(workspace)}


@router.post("/push")
async def git_push(workspace: str = Query(...)) -> dict[str, str]:
    await _ensure_trusted(workspace)
    return {"output": push(workspace)}


@router.post("/branch")
async def branch(payload: BranchSwitchRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    return {"branch": switch_branch(payload.workspace, payload.branch)}


@router.post("/branch/create")
async def branch_create(payload: BranchCreateRequest) -> dict[str, str]:
    await _ensure_trusted(payload.workspace)
    return {"branch": create_branch(payload.workspace, payload.branch, payload.checkout)}


@router.get("/history", response_model=list[CommitHistoryItem])
async def git_history(workspace: str = Query(...), limit: int = Query(30, ge=1, le=100)) -> list[CommitHistoryItem]:
    return [CommitHistoryItem(**item) for item in history(workspace, limit)]
