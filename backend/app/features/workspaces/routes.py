from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.features.workspaces.file_watcher import watcher
from backend.app.features.workspaces.schemas import WorkspaceListResponse, WorkspaceOpenRequest, WorkspaceDto
from backend.app.features.workspaces.service import get_last_workspace, list_recent_workspaces, open_workspace
from backend.app.features.workspaces.trust_service import get_workspace_trust, set_workspace_trust, list_trusted_workspaces, remove_workspace_trust, clear_all_trust

router = APIRouter()


@router.get("", response_model=WorkspaceListResponse)
async def recent_workspaces() -> WorkspaceListResponse:
    workspaces = await list_recent_workspaces()
    return WorkspaceListResponse(workspaces=workspaces, last_workspace=workspaces[0] if workspaces else None)


@router.post("/open", response_model=WorkspaceDto)
async def open_workspace_route(payload: WorkspaceOpenRequest) -> WorkspaceDto:
    return await open_workspace(payload.path)


@router.get("/last", response_model=WorkspaceDto | None)
async def last_workspace() -> WorkspaceDto | None:
    return await get_last_workspace()


@router.get("/watcher")
async def watcher_status() -> dict[str, object]:
    return watcher.status()


# Trust management endpoints
class TrustRequest(BaseModel):
    path: str
    trusted: bool
    trust_level: str = "full"


@router.get("/trust/{workspace_path:path}")
async def get_trust_status(workspace_path: str) -> dict:
    return await get_workspace_trust(workspace_path)


@router.post("/trust")
async def set_trust_status(payload: TrustRequest) -> dict:
    return await set_workspace_trust(payload.path, payload.trusted, payload.trust_level)


@router.get("/trust")
async def get_all_trusted() -> list[dict]:
    return await list_trusted_workspaces()


@router.delete("/trust/{workspace_path:path}")
async def remove_trust(workspace_path: str) -> dict:
    return await remove_workspace_trust(workspace_path)


@router.delete("/trust")
async def clear_all_trust_status() -> dict:
    return await clear_all_trust()
